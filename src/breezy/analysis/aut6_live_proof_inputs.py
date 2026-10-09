"""AUT-6 WP9: evidence loader and artefact writer of the live-proof report (plan r15 section 6).

Strictly read-only against the evidence tree. It reads rollups, delivery records, notifier markers,
AUT-1 audit and heal records, C5 exports, verdicts and node logs, and writes ONE file: its own
artefact ``<out root>/aut6/live_proof_<from>_<to>.json``, by temp file, fsync and ``os.replace``.
It never pages, never writes a store, registry or outbox, and imports no adapter, no
``current_rung_hold`` package and no Nautilus.

Choices the plan leaves open:

* **C1 EntryVeto and permit lines** are read from the node log, not decoded from the Arrow capture
  streams (that decode loads Nautilus, past this unit's memory bound). Deviation from plan
  L1531/L1540, which quote ``entry_veto reason=<r>``: no producer emits that line. The strategy
  logs ``SHADOW_DECISION {repr}`` and a refusal is a ``kind='TrySubmit'`` line whose ``reason`` is a
  ``VetoReason`` (``capture_audit_replay._follow_up_kind`` reads it the same way). So the vetoes
  are the ``TrySubmit`` lines ``capture_node_log_decisions.classify_line`` returns with such a
  reason; no parser is duplicated. The boot line ``live-trading permit issued ...
  expires_at_ns=<ns>`` gives the expiry.
* **A #21 verdict** is the ``aut6.unit_health`` verdict with an explicit ``invocation_id`` (body or
  metrics) equal to the ended invocation. TODO(WP4): #21's verdict shape is not written yet; until
  it is, a verdict whose body merely contains the id matches and is marked
  ``verdict_basis=unverifiable_substring`` in the report.
* **Per-kill page**: the notifier marker, else a delivered record naming the invocation.
* **Unreadable evidence is absence**: it can only fail a day or leave a class unproven.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import tempfile
from collections.abc import Iterable, Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any, Final

from breezy.analysis.aut6_live_proof_report import (
    DeliveryFact,
    FillFact,
    ProofInputs,
    RestartFact,
    VetoFact,
    evaluate_live_proof,
)
from breezy.analysis.capture_audit_io import list_names, read_file
from breezy.analysis.capture_audit_model import AUDIT_DIR_REL
from breezy.analysis.capture_audit_wire import audit_from_wire
from breezy.analysis.capture_aut6_contract import (
    ALERTS_REL,
    DELIVERY_RECORD_NAME_RE,
    read_notifier_proofs,
)
from breezy.analysis.capture_live_proof import newest_audit_by_day
from breezy.analysis.capture_node_log_decisions import DecisionLine, classify_line
from breezy.persistence.autonomy.single_read import ReadPolicy, SingleReadRefused
from breezy.persistence.autonomy.veto import VetoReason
from breezy.runtime.capture_recorder_hook_cli import UNIT as RECORDER_UNIT

__all__ = ["artefact_name", "build_report", "load_inputs", "main", "write_artefact"]

LOOKBACK_DAYS: Final = 30
NS: Final = 1_000_000_000
ARTEFACT_DIR: Final = "aut6"
ROLLUP_REL: Final = ("evidence", "unit_health")
HEAL_REL: Final = ("evidence", "capture", "heal")
EXPORT_REL: Final = ("evidence", "registry")
VERDICT_REL: Final = ("derived", "verdicts")
UNIT_HEALTH_DETECTOR: Final = "aut6.unit_health"
FILL_DETECTOR: Final = "aut6.fill_better_than_ask"
WATCHDOG_DECIDER: Final = "systemd_watchdog"
_ROLLUP_RE: Final = re.compile(r"\Aday_(\d{4}-\d\d-\d\d)\.json\Z")
_EXPORT_RE: Final = re.compile(r"\Aregistry_[a-z0-9_]{1,32}_\d{4}-\d\d-\d\d(?:_hwm\d+)?\.jsonl\Z")
_PERMIT_RE: Final = re.compile(r"live-trading permit issued .*?expires_at_ns=(\d+)")
_LOG_NAME_RE: Final = re.compile(r"\Abreezy-trade-.*\.log(?:\.[A-Za-z0-9]+)?\Z")


def _json(data_root: Path, rel: Sequence[str], name: str) -> dict[str, Any] | None:
    try:
        body = json.loads(read_file(data_root, rel, name, ReadPolicy.REPO) or b"")
    except (SingleReadRefused, OSError, ValueError):
        return None
    return body if isinstance(body, dict) else None


def _days(asof: dt.date) -> list[dt.date]:
    return [asof - dt.timedelta(days=n) for n in range(LOOKBACK_DAYS, -1, -1)]


def _names(data_root: Path, rel: Sequence[str]) -> list[str]:
    try:
        return sorted(list_names(data_root, rel))
    except (SingleReadRefused, OSError):
        return []


# -- file-backed evidence -----------------------------------------------------------------------


def _rollups(data_root: Path, days: Iterable[dt.date]) -> dict[str, Mapping[str, Any]]:
    found: dict[str, Mapping[str, Any]] = {}
    for day in days:
        body = _json(data_root, ROLLUP_REL, f"day_{day.isoformat()}.json")
        if body is not None:
            found[day.isoformat()] = body
    return found


def _deliveries(data_root: Path, days: Iterable[dt.date]) -> tuple[DeliveryFact, ...]:
    facts: list[DeliveryFact] = []
    for day in days:
        rel = (*ALERTS_REL, day.isoformat())
        for name in _names(data_root, rel):
            body = _json(data_root, rel, name) if DELIVERY_RECORD_NAME_RE.fullmatch(name) else None
            if body is not None and body.get("schema") == "alert_delivery/v1":
                facts.append(DeliveryFact(day.isoformat(), name, body))
    return tuple(facts)


def _fills(data_root: Path) -> tuple[FillFact, ...]:
    facts: list[FillFact] = []
    for family in _names(data_root, tuple(AUDIT_DIR_REL.split("/"))):
        rel = (*AUDIT_DIR_REL.split("/"), family)
        for day, name in sorted(newest_audit_by_day(_names(data_root, rel)).items()):
            try:
                result = audit_from_wire(_json(data_root, rel, name) or {})
            except (ValueError, KeyError, TypeError):
                continue
            facts.extend(
                FillFact(day.isoformat(), f.source, f.drill, f"{family}/{name}:{f.client_order_id}")
                for f in result.fills
            )
    return tuple(facts)


def _verdict_files(
    data_root: Path, days: Iterable[dt.date]
) -> Iterator[tuple[str, str, dict[str, Any]]]:
    """``(day, path-ish ref, body)`` of every verdict file of the days (read-only)."""
    for family in _names(data_root, VERDICT_REL):
        for day in days:
            rel = (*VERDICT_REL, family, day.isoformat())
            for name in _names(data_root, rel):
                body = _json(data_root, rel, name) if name.endswith(".json") else None
                if body is not None:
                    yield day.isoformat(), f"{family}/{day.isoformat()}/{name}", body


def _verdicts(
    data_root: Path, days: Sequence[dt.date]
) -> tuple[
    dict[str, dict[str, Any]], tuple[tuple[str, int], ...], list[tuple[str, dict[str, Any]]]
]:
    """Cited-verdict index, frame-gap days, and the unit-health verdicts (for #21)."""
    index: dict[str, dict[str, Any]] = {}
    gaps: dict[str, int] = {}
    health: list[tuple[str, dict[str, Any]]] = []
    for day, ref, body in _verdict_files(data_root, days):
        vid, detector = body.get("verdict_id"), body.get("detector")
        if isinstance(vid, str) and isinstance(detector, str):
            index[vid] = {k: body.get(k) for k in ("detector", "outcome", "kind", "verdict_id")}
        if detector == UNIT_HEALTH_DETECTOR:
            health.append((ref, body))
        metrics = body.get("metrics")
        count = metrics.get("inconclusive_frame_gap") if isinstance(metrics, dict) else None
        if detector == FILL_DETECTOR and isinstance(count, int | str):
            try:
                if int(count) > 0:
                    gaps[day] = gaps.get(day, 0) + int(count)
            except ValueError:
                continue
    return index, tuple(sorted(gaps.items())), health


def _transitions(data_root: Path) -> tuple[Mapping[str, Any], ...]:
    rows: dict[str, Mapping[str, Any]] = {}
    for name in _names(data_root, EXPORT_REL):
        if _EXPORT_RE.fullmatch(name) is None:
            continue
        try:
            raw = read_file(data_root, EXPORT_REL, name, ReadPolicy.REPO) or b""
        except (SingleReadRefused, OSError):
            continue
        for line in raw.decode("utf-8", "replace").splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict) and isinstance(row.get("transition_id"), str):
                rows[row["transition_id"]] = row
    return tuple(rows.values())


def _verdict_for(inv: str, health: Sequence[tuple[str, dict[str, Any]]]) -> tuple[str, str]:
    """``(verdict_id, basis)`` of the #21 verdict of ``inv``: an explicit invocation id first."""
    if not inv:
        return "", "field"
    for _ref, body in health:
        metrics = body.get("metrics")
        held = [body.get("invocation_id")] + (
            [metrics.get("invocation_id")] if isinstance(metrics, dict) else []
        )
        if inv in held:
            return str(body.get("verdict_id") or ""), "field"
    for _ref, body in health:  # TODO(WP4): drop once #21's verdict carries an invocation id
        if inv in json.dumps(body):
            return str(body.get("verdict_id") or ""), "unverifiable_substring"
    return "", "field"


def _restarts(
    data_root: Path,
    days: Sequence[dt.date],
    deliveries: Sequence[DeliveryFact],
    health: Sequence[tuple[str, dict[str, Any]]],
) -> tuple[RestartFact, ...]:
    facts: list[RestartFact] = []
    for day in days:
        proofs = read_notifier_proofs(data_root, day)
        rel = (*HEAL_REL, day.isoformat())
        for name in _names(data_root, rel):
            body = _json(data_root, rel, name) if name.endswith(".json") else None
            if body is None or body.get("decided_by") != WATCHDOG_DECIDER:
                continue
            inv = str(body.get("invocation_id", ""))
            verdict, basis = _verdict_for(inv, health)
            paged = any(
                inv
                and inv in f"{d.body.get('event', '')} {d.body.get('site', '')}"
                and d.body.get("delivered") is True
                for d in deliveries
            )
            marker = any(
                p.unit == RECORDER_UNIT and p.invocation_id == inv and p.delivered for p in proofs
            )
            ts = body.get("detected_ns")
            facts.append(
                RestartFact(
                    RECORDER_UNIT,
                    inv,
                    str(body.get("unit_result", "")),
                    body.get("injected") is True,
                    str(verdict or ""),
                    marker,
                    paged,
                    ts
                    if isinstance(ts, int)
                    else int(dt.datetime.combine(day, dt.time(), dt.UTC).timestamp()) * NS,
                    basis,
                )
            )
    return tuple(facts)


# -- node log -----------------------------------------------------------------------------------


_VETO_REASONS: Final = frozenset(r.value for r in VetoReason)


def _veto_of(raw: bytes, ref: str) -> VetoFact | None:
    """The ``EntryVeto`` a logged ``TrySubmit`` line stands for, else ``None``."""
    event = classify_line(raw.rstrip(b"\r\n"), 0)
    if not isinstance(event, DecisionLine) or event.kind != "TrySubmit":
        return None
    if event.reason not in _VETO_REASONS:
        return None
    return VetoFact(event.now_ns, event.reason, ref)


def _scan_logs(
    log_dir: Path | None, since: dt.date
) -> tuple[tuple[int, ...], tuple[VetoFact, ...], list[str]]:
    expiries: list[int] = []
    vetos: list[VetoFact] = []
    scanned: list[str] = []
    if log_dir is None or not log_dir.is_dir():
        return (), (), scanned
    floor = dt.datetime.combine(since, dt.time(), dt.UTC).timestamp()
    for path in sorted(log_dir.iterdir()):
        try:
            fresh = _LOG_NAME_RE.fullmatch(path.name) and path.stat().st_mtime >= floor
        except OSError:
            continue
        if not fresh:
            continue
        scanned.append(path.name)
        with path.open("rb") as handle:
            for number, raw in enumerate(handle, 1):
                if b"permit issued" in raw:
                    if (m := _PERMIT_RE.search(raw.decode("utf-8", "replace"))) is not None:
                        expiries.append(int(m[1]))
                elif b"SHADOW_DECISION" in raw:
                    veto = _veto_of(raw, f"{path.name}:{number}")
                    if veto is not None:
                        vetos.append(veto)
    return tuple(expiries), tuple(vetos), scanned


# -- assembly -----------------------------------------------------------------------------------


def load_inputs(
    data_root: Path,
    asof: dt.date,
    *,
    aut5b_ruling_date: str | None = None,
    ing2_amend2_landed_date: str | None = None,
    node_log_dir: Path | None = None,
    wp4_mechanism_proof: str | None = None,
    new_exec_store_halt_keys: int | None = None,
) -> tuple[ProofInputs, dict[str, Any]]:
    """The evaluator's inputs and the citations (what was read) of one report."""
    days = _days(asof)
    deliveries = _deliveries(data_root, days)
    index, gaps, health = _verdicts(data_root, days)
    expiries, vetos, logs = _scan_logs(node_log_dir, days[0])
    rollups = _rollups(data_root, days)
    fills = _fills(data_root)
    inputs = ProofInputs(
        asof=asof.isoformat(),
        aut5b_ruling_date=aut5b_ruling_date,
        ing2_amend2_landed_date=ing2_amend2_landed_date,
        rollups=rollups,
        fills=fills,
        deliveries=deliveries,
        permit_expiries_ns=expiries,
        entry_vetos=tuple(v for v in vetos if v.reason == "permit_lapsed"),
        node_log_vetos=vetos,
        restarts=_restarts(data_root, days, deliveries, health),
        wp4_mechanism_proof=wp4_mechanism_proof,
        transitions=_transitions(data_root),
        verdicts=index,
        new_exec_store_halt_keys=new_exec_store_halt_keys,
        frame_gap_days=gaps,
    )
    citations = {
        "rollups": sorted(rollups),
        "delivery_records": [f"{d.day}/{d.name}" for d in deliveries],
        "fills": [f.ref for f in fills],
        "c5_transitions": [str(t.get("transition_id")) for t in inputs.transitions],
        "c4_verdict_ids": sorted(index),
        "node_logs": logs,
        "veto_lines": [v.ref for v in vetos],
    }
    return inputs, citations


def build_report(
    data_root: Path,
    asof: dt.date,
    *,
    aut5b_ruling_date: str | None = None,
    ing2_amend2_landed_date: str | None = None,
    node_log_dir: Path | None = None,
    wp4_mechanism_proof: str | None = None,
    new_exec_store_halt_keys: int | None = None,
) -> dict[str, Any]:
    inputs, citations = load_inputs(
        data_root,
        asof,
        aut5b_ruling_date=aut5b_ruling_date,
        ing2_amend2_landed_date=ing2_amend2_landed_date,
        node_log_dir=node_log_dir,
        wp4_mechanism_proof=wp4_mechanism_proof,
        new_exec_store_halt_keys=new_exec_store_halt_keys,
    )
    return {**evaluate_live_proof(inputs), "citations": citations}


def artefact_name(report: Mapping[str, Any]) -> str:
    window = report["window"]
    first = (
        window["from"]
        or (dt.date.fromisoformat(report["asof"]) - dt.timedelta(days=LOOKBACK_DAYS)).isoformat()
    )
    last = (
        window["to"] or (dt.date.fromisoformat(report["asof"]) - dt.timedelta(days=1)).isoformat()
    )
    return f"live_proof_{first}_{last}.json"


def write_artefact(out_root: Path, report: Mapping[str, Any]) -> Path:
    """Publish the report atomically; this is the only write the report ever makes."""
    target = out_root / ARTEFACT_DIR / artefact_name(report)
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=".tmp-")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write((json.dumps(report, sort_keys=True, indent=1) + "\n").encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, target)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return target


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AUT-6 live-proof report (read-only, offline)")
    home = Path.home() / ".local" / "share" / "breezy"
    parser.add_argument("--data-root", type=Path, default=home)
    parser.add_argument("--out-root", type=Path, default=home / "evidence")
    parser.add_argument("--asof", default=dt.datetime.now(dt.UTC).date().isoformat())
    parser.add_argument("--aut5b-ruling-date")
    parser.add_argument("--ing2-amend2-landed-date")
    parser.add_argument("--node-log-dir", type=Path, default=home / "logs")
    parser.add_argument("--wp4-mechanism-proof")
    parser.add_argument("--new-exec-store-halt-keys", type=int)
    args = parser.parse_args(argv)
    report = build_report(
        args.data_root,
        dt.date.fromisoformat(args.asof),
        aut5b_ruling_date=args.aut5b_ruling_date,
        ing2_amend2_landed_date=args.ing2_amend2_landed_date,
        node_log_dir=args.node_log_dir,
        wp4_mechanism_proof=args.wp4_mechanism_proof,
        new_exec_store_halt_keys=args.new_exec_store_halt_keys,
    )
    path = write_artefact(args.out_root, report)
    summary = f"verdict={report['verdict']} blockers={len(report['blockers'])} path={path}"
    print(f"AUT6_LIVE_PROOF {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
