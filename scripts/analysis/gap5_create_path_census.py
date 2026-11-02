"""Read-only GAP-5a reverse join, frozen by coordinator on 2026-11-02.
ANCHOR follows inline confirm, without a resting flag. Inclusive confirm window:
[anchor - (deadline + JOIN_SLACK_S), anchor]. Confirm-bearing anchors are resting
candidates; others need NEW evidence or remain NO_EXIT. Overlap makes BOTH UNKNOWN.
Last terminal wins; retries stay ordered. Bind-raised uses private keys, never output."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from collections import Counter
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from breezy.analysis.capture_node_log_io import read_lines, ts_ns
from breezy.analysis.capture_node_log_spawns import list_node_logs, scan_supervisor_log

JOIN_SLACK_S = 2.0
RESTING_CONFIRM_DEADLINE_S = 5
RESOLVER_BASE_S, RESOLVER_CAP_S, THRESHOLD_SHARE = 5.0, 300.0, 0.5
WINDOW_NS = int((RESTING_CONFIRM_DEADLINE_S + JOIN_SLACK_S) * 1e9)
START, END = b"2026-10-31T00:00:00Z", b"2026-11-02T00:00:00Z"
CREATE_EMITTER = "create-order classified kind="
WAIT_EMITTER = "submit intent is already OPEN for this account; wait for it to resolve"
NEW_EMITTER = "resting bind: cleared the AMBIGUOUS trading refusal"
MESSAGES = {
    "ALLOWLIST": "resting confirm: the venue order id failed the allowlist; holding",
    "TIMEOUT": "resting confirm: the GET timed out; holding",
    "REFUSED": "resting confirm: GET refused (HTTP status",
    "DIDNOTMAP": "resting confirm: GET did not map (",
    "ECHO": "resting confirm: not a clean matching NEW; holding",
    "NONNEW": "resting confirm: a non-NEW state (filled, partial or terminal); holding",
    "DEADLINE": "resting confirm: deadline reached without a NEW; holding",
    "BIND_RAISED": "resting bind raised; holding",
}
TERMINALS = {"ECHO": "SIG_H2_ECHO", "NONNEW": "SIG_H3_NONNEW", "TIMEOUT": "SIG_X_TIMEOUT"}
TERMINALS.update(ALLOWLIST="SIG_X_ALLOWLIST", BIND_RAISED="SIG_X_BIND_RAISED")
HYPOTHESES = {"SIG_H2_ECHO": "H2", "SIG_H3_NONNEW": "H3", "SIG_X_TIMEOUT": "X1"}
HYPOTHESES.update(SIG_X_ALLOWLIST="X2", SIG_X_BIND_RAISED="X3")
HYPOTHESES.update(SIG_H1_404_DEADLINE="H1", SIG_DIDNOTMAP="DIDNOTMAP")
SIGNATURES = ["SIG_NEW", *HYPOTHESES, "SIG_NO_EXIT", "UNKNOWN"]
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
LINE = re.compile(r"^(\d{4}-\d\d-\d\d[T ]\d\d:\d\d:\d\d(?:[.,]\d+)?Z?)\s+\[(\w+)\]")
KEY = re.compile(r"client_order_id=([^\s,)'\"]+)")
BACKOFF = re.compile(r"\(backoff: (\d+) consecutive failure\(s\)\)")
PUBLIC = ["ordinal", "log", "create_line", "signature", "sequence", "exit_lines"]
PUBLIC += ["exit_relative_s", "bind_delay_s", "hold_bind_delay_s", "backoff_in_force"]
PUBLIC += ["waits", "replaced_before_accepted", "new_label", "join_label"]
NOTES = """Anchors lack resting flags; delays start at anchor. Late unkeyed binds stay unjoined.
Overlap is UNKNOWN; WAITs count OrderDenied once. H4 needs OrderAccepted. Unmatched stay unjoined.
Backoff resets can be unlogged. No DB cross-check. Historical DIDNOTMAP is never relabelled.
Raw mentions include duplicates/outside-window. Sink: WARN retries, ERROR creates, INFO NEW."""
Row = dict[str, Any]


def strip_ansi(text: str) -> str:
    return ANSI.sub("", text)


def match_line(text: str, line_no: int = 1) -> Row | None:
    text = strip_ansi(text)
    match = LINE.match(text)
    if not match or match[2] == "DEBUG":
        return None
    stamp = match[1].replace(" ", "T").replace(",", ".").removesuffix("Z") + "Z"
    when = ts_ns(stamp.encode())
    key, backoff = KEY.search(text), BACKOFF.search(text)
    kind = next((k for k, message in MESSAGES.items() if message in text), "")
    if CREATE_EMITTER + "ambiguous " in text and "body_kind=empty-executions" in text:
        kind = "CREATE"
    elif "OrderAccepted(" in text:
        kind = "NEW"
    elif NEW_EMITTER in text:
        kind = "BIND"
    elif WAIT_EMITTER in text and "OrderDenied(" in text:
        kind = "WAIT"
    elif "REPLACED" in text:
        kind = "REPLACED"
    elif backoff:
        kind = "BACKOFF"
    if when is None:
        raise ValueError("invalid log timestamp")
    event: Row = {"ns": when, "kind": kind, "line": line_no, "level": match[2]}
    event.update(_key=key[1] if key else "", refused_404="GET refused (HTTP status 404)" in text)
    event.update(failure_count=int(backoff[1]) if backoff else None)
    return event


def classify_create(
    sequence: list[str], *, refused_404: bool = False, overlap: bool = False, new: bool = False
) -> str:
    if overlap:
        return "UNKNOWN"
    terminals = [k for k in sequence if k in TERMINALS or k == "DEADLINE"]
    if not terminals:
        return "SIG_NEW" if new else "SIG_NO_EXIT"
    if terminals[-1] in TERMINALS:
        return TERMINALS[terminals[-1]]
    prefix = sequence[: max(i for i, kind in enumerate(sequence) if kind == "DEADLINE")]
    if refused_404 and "REFUSED" in prefix:
        return "SIG_H1_404_DEADLINE"
    return "SIG_DIDNOTMAP" if prefix and set(prefix) == {"DIDNOTMAP"} else "UNKNOWN"


def derive_backoff(failures: int | None, *, success_window: bool = False) -> float | str:
    if failures is None or success_window:
        return "UNKNOWN"
    return float(min(RESOLVER_CAP_S, RESOLVER_BASE_S * 2 ** min(6, max(0, failures - 1))))


def segment_creates(lines: Iterable[str]) -> list[Row]:
    events = [e for n, text in enumerate(lines, 1) if (e := match_line(text, n)) is not None]
    events.sort(key=lambda e: (e["ns"], e["line"]))
    anchors = [e for e in events if e["kind"] == "CREATE"]
    rows = []
    for i, anchor in enumerate(anchors):
        exits = [
            e
            for e in events
            if anchor["ns"] - WINDOW_NS <= e["ns"] <= anchor["ns"]
            and e["line"] <= anchor["line"]
            and e["kind"] in MESSAGES
            and (e["kind"] != "BIND_RAISED" or bool(anchor["_key"]) and e["_key"] == anchor["_key"])
        ]
        overlap = any(
            abs(e["ns"] - anchor["ns"]) <= WINDOW_NS for j, e in enumerate(anchors) if j != i
        )
        rows.append(_record(i, anchor, exits, events, overlap))
    _attach_lifecycle(rows, events)
    return rows


def _record(i: int, anchor: Row, exits: list[Row], events: list[Row], overlap: bool) -> Row:
    sequence = [e["kind"] for e in exits]
    terminal = [e for e in exits if e["kind"] in TERMINALS or e["kind"] == "DEADLINE"]
    hold_ns = terminal[-1]["ns"] if terminal else anchor["ns"]
    markers = [e for e in events if e["kind"] == "BACKOFF" and e["ns"] < hold_ns]
    marker = markers[-1] if markers else None
    success = bool(
        marker
        and any(e["kind"] in {"NEW", "BIND"} and marker["ns"] < e["ns"] < hold_ns for e in events)
    )
    row: Row = {"ordinal": f"c{i + 1:03d}", "create_line": anchor["line"], "sequence": sequence}
    row.update(_ns=anchor["ns"], _key=anchor["_key"], _hold_ns=hold_ns)
    refused = any(e["refused_404"] and e["ns"] <= hold_ns for e in exits)
    row.update(signature=classify_create(sequence, overlap=overlap, refused_404=refused))
    row.update(exit_lines=[e["line"] for e in exits], bind_delay_s="never bound")
    row.update(exit_relative_s=[(e["ns"] - anchor["ns"]) / 1e9 for e in exits])
    row.update(hold_bind_delay_s="never bound", waits=[], replaced_before_accepted=0)
    backoff = derive_backoff(marker["failure_count"] if marker else None, success_window=success)
    row.update(new_label="unobserved", backoff_in_force=backoff)
    row["join_label"] = "unassignable" if overlap else "joined"
    return row


def _attach_lifecycle(rows: list[Row], events: list[Row]) -> None:
    for event in events:
        pending = [
            r for r in rows if r["_ns"] <= event["ns"] and r["bind_delay_s"] == "never bound"
        ]
        if event["kind"] in {"NEW", "BIND"}:
            choices = [r for r in pending if event["ns"] - r["_ns"] <= WINDOW_NS]
            if event["kind"] == "NEW":
                choices = [r for r in pending if r["_key"] and r["_key"] == event["_key"]]
            if len(choices) != 1:
                continue
            row = choices[0]
            row["bind_delay_s"] = (event["ns"] - row["_ns"]) / 1e9
            row["hold_bind_delay_s"] = (event["ns"] - row["_hold_ns"]) / 1e9
            row["new_label"] = "observed"
            key = row["_key"] if event["kind"] == "NEW" else ""
            replaced = [e for e in events if key and e["kind"] == "REPLACED" and e["_key"] == key]
            row["replaced_before_accepted"] = sum(
                row["_ns"] <= e["ns"] < event["ns"] for e in replaced
            )
            if row["signature"] == "SIG_NO_EXIT" and row["bind_delay_s"] <= WINDOW_NS / 1e9:
                row["signature"] = "SIG_NEW"
        elif event["kind"] == "WAIT" and len(pending) == 1:
            row = pending[0]
            if row["signature"] in HYPOTHESES:
                delay = (event["ns"] - row["_ns"]) / 1e9
                wait = {"line": event["line"], "delay_s": delay}
                wait["backoff_in_force"] = row["backoff_in_force"]
                row["waits"].append(wait)


def _majority(count: int, total: int) -> bool:
    return bool(total) and count / total >= THRESHOLD_SHARE


def _h5(holds: list[Row]) -> str:
    bound = [r for r in holds if isinstance(r["bind_delay_s"], (int, float))]
    unknown = sum(r.get("backoff_in_force", "UNKNOWN") == "UNKNOWN" for r in bound)
    if not bound or _majority(unknown, len(bound)):
        return "UNDECIDABLE"
    for label, high in (("H5a", True), ("H5b", False)):
        matching = [
            r
            for r in bound
            if isinstance(r.get("backoff_in_force"), (int, float))
            and r["hold_bind_delay_s"] > 30
            and (r["backoff_in_force"] > 30) == high
        ]
        if _majority(len(matching), len(bound)):
            return label
    return "UNCONFIRMED"


def evaluate_predicates(rows: list[Row], *, n_wait_total: int | None = None) -> Row:
    holds = [r for r in rows if r["signature"] in HYPOTHESES]
    confirmed = [
        name
        for sig, name in HYPOTHESES.items()
        if _majority(sum(r["signature"] == sig for r in holds), len(holds))
    ]
    h5 = _h5(holds)
    waits = [(r, w) for r in rows for w in r.get("waits", [])]
    fast = sum(
        isinstance(r["bind_delay_s"], (int, float))
        and r["bind_delay_s"] <= 6
        and w["delay_s"] <= r["bind_delay_s"]
        for r, w in waits
    )
    total = len(waits) if n_wait_total is None else n_wait_total
    if any(r.get("replaced_before_accepted", 0) for r in rows) and _majority(fast, total):
        confirmed.append("H4")
    if h5 == "H5a":
        confirmed.append(h5)
    x_dominant = _majority(sum(r["signature"].startswith("SIG_X_") for r in holds), len(holds))
    reasons = ["L-37 names-only logging gap"] if "H2" in confirmed else []
    flags = {"H5 UNDECIDABLE": h5 == "UNDECIDABLE", "UNEXPLAINED": not confirmed}
    flags.update(H5b=h5 == "H5b", x_dominant=x_dominant)
    reasons += [f"STOP-REPORT: {label}" for label, active in flags.items() if active]
    verdict: Row = {"confirmed": confirmed, "x_dominant": x_dominant, "h5": h5}
    verdict.update(UNEXPLAINED=not confirmed, stop_report_reasons=reasons)
    verdict.update(step2_schema_check="H3" in confirmed)
    return verdict


def _counts(rows: list[Row]) -> Row:
    signatures = Counter(r["signature"] for r in rows)
    holds = sum(signatures[s] for s in HYPOTHESES)
    counts: Row = {"N_create": len(rows), "N_NEW": signatures["SIG_NEW"], "N_HOLD": holds}
    counts.update(N_NO_EXIT=signatures["SIG_NO_EXIT"], N_UNKNOWN=signatures["UNKNOWN"])
    counts.update(signatures={s: signatures[s] for s in SIGNATURES})
    counts.update(hold_shares={s: signatures[s] / holds if holds else 0 for s in HYPOTHESES})
    return counts


def hygiene_scan(text: str) -> None:
    pattern = (
        r"client_order_id=|\bBearer\b|\b[A-Z0-9]{12}\b|\b0x[0-9a-fA-F]{40,}\b|\b\d{8,}\b|"
        r"[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}|"
        r"(?i:private.?key|secret.?key|api.?key|account.?number)"
    )
    if re.search(pattern, text):
        raise ValueError("hygiene refusal: sensitive output")


def verify_sources(root: Path) -> Row:
    base = root / "src/breezy/adapters/polymarket_us/exec"
    pins = {**MESSAGES, "anchor": CREATE_EMITTER, "new": NEW_EMITTER, "resting": "resting=True,"}
    pins.update(confirm_call="resting_verdict = await self._confirm_resting_order(")
    pins.update(anchor_error="self._log.error(classified_line)")
    pins.update(base="_RESOLVER_POLL_INTERVAL_SECS: Final[float] = 5.0")
    pins.update(cap="_RESOLVER_BACKOFF_CAP_SECS: Final[float] = 300.0")
    pins.update(
        formula="doubled = base_interval * (2 ** (self._resolver_consecutive_failures - 1))"
    )
    pins.update(
        reset="self._resolver_consecutive_failures = 0", accepted="self.generate_order_accepted("
    )
    chain = {"deadline": "RESTING_CONFIRM_DEADLINE_S: Final[int] = 5", "wait": WAIT_EMITTER}
    result: Row = {}
    for filename, needles in (("client.py", pins), ("submit_chain.py", chain)):
        if not (base / filename).is_file():
            raise ValueError("source drift: unreadable")
        lines = (base / filename).read_text().splitlines()
        hits = {
            key: [i for i, text in enumerate(lines, 1) if needle in text]
            for key, needle in needles.items()
        }
        if not all(hits.values()):
            raise ValueError("source drift: pinned text missing")
        result[filename] = hits
        if filename == "client.py":
            for label, needle in {**MESSAGES, "new": NEW_EMITTER}.items():
                level = "error" if label in {"ALLOWLIST", "BIND_RAISED"} else "warning"
                level = "info" if label == "new" else level
                pattern = rf"self\._log\.{level}\(\s*f?[\"']{re.escape(needle)}"
                if not re.search(pattern, "\n".join(lines)):
                    raise ValueError("source drift: emitter level changed")
    result["note"] = "RE-CHECKED AGAINST TEXT AT RUN TIME; confirm precedes anchor."
    return result


def render(payload: Row) -> tuple[str, str]:
    public: Row = {
        k: payload[k] for k in ("git_sha", "citations", "logs", "counts", "verdict") if k in payload
    }
    public["rows"] = [{k: r[k] for k in PUBLIC if k in r} for r in payload["rows"]]
    public = json.loads(json.dumps(public), parse_float=lambda f: round(float(f), 3))
    machine = json.dumps(public, indent=2, sort_keys=True) + "\n"
    md = [f"# GAP-5a create-path census\n\ngit_sha: {payload['git_sha']}", NOTES]
    md.append("Window: 2026-10-31T00:00Z to 2026-11-02T00:00Z, end exclusive.")
    md += ["Counts/input sha256s: " + json.dumps(public["logs"], sort_keys=True)]
    md += ["Citations: " + json.dumps(public["citations"], sort_keys=True)]
    counts = [("window", _counts(payload["rows"]))]
    counts += [(log["filename"], log["counts"]) for log in public["logs"]]
    for label, count in counts:
        for sig in SIGNATURES:
            if count["signatures"][sig] == 0:
                level = "ERROR" if sig in {"SIG_X_ALLOWLIST", "SIG_X_BIND_RAISED"} else "WARN"
                if sig in {"SIG_NEW", "SIG_NO_EXIT", "UNKNOWN"}:
                    level = "INFO NEW; absence/ambiguity is derived"
                md.append(f"ZERO {label} {sig}: {level}; source and sink proof above.")
    md += ["Ordinals:", json.dumps(public["rows"], indent=2, sort_keys=True)]
    markdown = "\n\n".join(md) + "\n"
    hygiene_scan(machine + markdown)
    return machine, markdown


def _scan_log(path: Path, start: int, end: int) -> Row | None:
    lines: list[str] = []
    stamps: list[int] = []
    levels: dict[str, int] = {}
    raw_counts: Counter[str] = Counter()
    for raw in read_lines(path):
        if raw.truncated or not raw.terminated:
            raise ValueError("incomplete input line")
        text = raw.raw.decode("utf-8", "strict")
        event = match_line(text, raw.line_no)
        if event:
            stamps.append(event["ns"])
            levels.setdefault(event["level"], raw.line_no)
        in_window = bool(event and start <= event["ns"] < end)
        for marker, name in (
            ("body_kind=empty-executions", "empty_mentions"),
            ("resting confirm:", "confirm_lines"),
        ):
            if marker in text:
                raw_counts[name + "_full"] += 1
                raw_counts[name + "_window"] += in_window
        lines.append(text if event and start - WINDOW_NS <= event["ns"] < end else "")
    if not stamps or stamps[0] >= end or stamps[-1] < start:
        return None
    rows = [r for r in segment_creates(lines) if start <= r["_ns"] < end]
    for row in rows:
        row["log"] = path.name
    waits = sum(bool((e := match_line(text)) and e["kind"] == "WAIT") for text in lines)
    result: Row = {"filename": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    result.update(counts=_counts(rows), raw_counts=dict(raw_counts), sink_level_lines=levels)
    result.update(N_WAIT=waits, N_WAIT_unjoined=waits - sum(len(r["waits"]) for r in rows))
    result.update(first_relative_s=(stamps[0] - start) / 1e9)
    result.update(last_relative_s=(stamps[-1] - start) / 1e9, rows=rows)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--logs", nargs="+", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--supervisor-log", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    if subprocess.check_output(["git", "status", "--porcelain"], cwd=root):
        raise ValueError("writer requires a clean worktree")
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    citations = verify_sources(root)
    paths: set[Path] = set()
    for requested in args.logs:
        listing = list_node_logs(requested if requested.is_dir() else requested.parent)
        paths.update(p for p in listing.paths if requested.is_dir() or p == requested)
        if not requested.is_dir() and requested not in listing.paths:
            raise ValueError("input not a node log")
    start, end = ts_ns(START) or 0, ts_ns(END) or 0
    logs = [log for p in sorted(paths) if (log := _scan_log(p, start, end)) is not None]
    if not logs:
        raise ValueError("no input overlaps window")
    rows = [r for log in logs for r in log.pop("rows")]
    for i, row in enumerate(rows, 1):
        row["ordinal"] = f"c{i:03d}"
    verdict = evaluate_predicates(rows, n_wait_total=sum(log["N_WAIT"] for log in logs))
    payload: Row = {"git_sha": sha, "citations": citations, "logs": logs, "rows": rows}
    payload["verdict"] = verdict
    payload["counts"] = _counts(rows)
    if args.supervisor_log:
        payload["N_supervisor_spawns"] = len(scan_supervisor_log(args.supervisor_log).spawns)
    machine, markdown = render(payload)
    args.out.mkdir(parents=True, exist_ok=True)
    for suffix, content in (("json", machine), ("md", markdown)):
        (args.out / f"create_path_census.{suffix}").write_text(content)


if __name__ == "__main__":
    main()
