"""Alert delivery, ``#23 aut6.alert_delivery`` (plan r15 sections 3.2, 3.6 and 3.7; WP3 S5).

FAIL (CRITICAL) on any of:

* a scheduled canary slot (15:45Z, 16:30Z, 16:45Z) with no ``delivered=true`` canary record at or
  after it. The 16:30Z and 16:45Z retries are deferred to the 17:10Z firing (U12), so those two
  slots are judged only once that firing's record (``d`` or ``f``) exists or by a pass starting at
  or after 17:21Z (r6, S2); until then the verdict carries ``metrics.canary_slot_pending``;
* ``armed.json`` still absent 24 h after the oldest delivered canary record
  (``armed_marker_missing``);
* an outbox or claimed entry whose filename ``ts_ns`` is older than 24 h (``abandoned``), or one
  with more than 3 failed delivery attempts (``failed_attempts``);
* an ``outbox_overflow``, ``outbox_write_failed`` or ``integrity_demand_write_failed`` record in
  the last 24 h; a non-zero ``journal_write_failures``, ``outbox_write_failures`` or
  ``integrity_demand_write_failures`` counter, or a ``PRODUCER_INTRADAY_DEMAND INTEGRITY`` line, in
  an AUT-6 unit's summary line; an ``alert_delivery_journal_unwritable`` line in the node log tail;
* a record root that fails ``os.access(W_OK)`` or holds under 64 MiB.

Failed attempts are counted from the failed delivery records naming the entry: no per-entry
reclaim counter is stored anywhere, and every reclaim is followed by one attempt that leaves a
record.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from breezy.runtime.alert_outbox import read_armed_marker
from breezy.runtime.monitor_watch_model import (
    DAY_S,
    NS,
    SEVERITY_CRITICAL,
    DetectorResult,
    Outcome,
    WatchFinding,
)

DETECTOR_DELIVERY: Final = "aut6.alert_delivery"
RECORD_ROOT_MIN_FREE_BYTES: Final = 64 * 2**20
ABANDON_AFTER_S: Final = 24 * 3600
FAILED_ATTEMPTS_MAX: Final = 3
#: Per day directory; a larger one cannot be judged inside the pass budget.
MAX_RECORDS_PER_DAY: Final = 5000
SLOT_SETTLE_S: Final = 120
SLOT_1710_S: Final = 17 * 3600 + 10 * 60
SLOT_1710_END_S: Final = SLOT_1710_S + 120
JUDGE_DEFERRED_FROM_S: Final = 17 * 3600 + 21 * 60
CANARY_SLOTS: Final[Mapping[str, int]] = {
    "1545": 15 * 3600 + 45 * 60,
    "1630": 16 * 3600 + 30 * 60,
    "1645": 16 * 3600 + 45 * 60,
}
DEFERRED_SLOTS: Final = frozenset({"1630", "1645"})
_RECORD_RE: Final = re.compile(r"(\d+)_([a-z0-9_]{1,64})_([df])\.json\Z")
_ENTRY_RE: Final = re.compile(r"(\d+)_[A-Za-z0-9_]+\.json\Z")
_COUNTERS: Final = (
    "journal_write_failures",
    "outbox_write_failures",
    "integrity_demand_write_failures",
)
_COUNTER_RES: Final = {c: re.compile(rf"\b{c}=(\d+)") for c in _COUNTERS}
_DEMAND_INTEGRITY: Final = "PRODUCER_INTRADAY_DEMAND INTEGRITY"
_JOURNAL_UNWRITABLE: Final = "alert_delivery_journal_unwritable"
_BAD_STATUS: Final = frozenset({"outbox_overflow"})


def _free_bytes(path: Path) -> int:
    info = os.statvfs(path)
    return info.f_bavail * info.f_frsize


@dataclass(frozen=True, slots=True)
class DeliveryInputs:
    alerts_root: Path
    now_ns: int
    #: When the canary timer became active: earlier slots were never due. ``None`` judges all.
    canary_since_ns: int | None = None
    #: Summary lines of the AUT-6 units since the last pass; ``None`` = the read was impossible.
    summary_lines: Sequence[str] | None = ()
    node_log_tail: str | None = ""
    access: Callable[[Path, int], bool] = os.access
    free_bytes: Callable[[Path], int] = _free_bytes


@dataclass(frozen=True, slots=True)
class _Record:
    name: str
    ts_ns: int
    writer: str
    delivered: bool
    body: Mapping[str, Any]


def _day(ts_ns: int) -> dt.date:
    return dt.datetime.fromtimestamp(ts_ns / NS, tz=dt.UTC).date()


def _read_body(path: Path) -> Mapping[str, Any]:
    try:
        with path.open("rb") as handle:
            raw = handle.read(65_536)
        body = json.loads(raw)
    except (OSError, ValueError):
        return {}
    return body if isinstance(body, dict) else {}


def _records(root: Path, now_ns: int) -> tuple[list[_Record], list[str]]:
    """Records of today and yesterday; ``unknown`` names every directory that cannot be listed."""
    found: list[_Record] = []
    unknown: list[str] = []
    for back in (0, 1):
        directory = root / (_day(now_ns) - dt.timedelta(days=back)).isoformat()
        try:
            names = sorted(os.listdir(directory))
        except FileNotFoundError:
            continue
        except OSError:
            unknown.append("alert_records_unreadable")
            continue
        if len(names) > MAX_RECORDS_PER_DAY:
            unknown.append("alert_records_over_cap")
            names = names[-MAX_RECORDS_PER_DAY:]
        for name in names:
            match = _RECORD_RE.fullmatch(name)
            if match is None:
                continue
            found.append(
                _Record(
                    name,
                    int(match.group(1)),
                    match.group(2),
                    match.group(3) == "d",
                    _read_body(directory / name),
                )
            )
    return found, unknown


def _outbox_entries(root: Path) -> tuple[list[Path], list[str]]:
    """Outbox and claimed entries; a directory that cannot be listed is a reason, not a crash."""
    out = root / "outbox"
    paths: list[Path] = []
    try:
        for entry in out.iterdir():
            if entry.is_file() and not entry.is_symlink():
                paths.append(entry)
            elif entry.name == "claimed" and entry.is_dir() and not entry.is_symlink():
                for holder in entry.iterdir():
                    if holder.is_dir() and not holder.is_symlink():
                        paths.extend(p for p in holder.iterdir() if p.is_file())
    except FileNotFoundError:
        return [], []
    except OSError:
        return paths, ["outbox_unreadable"]
    return paths, []


def _finding(
    kind: str,
    today: str,
    detail: str,
    metrics: Mapping[str, str] | None = None,
    *,
    suffix: str = "",
) -> WatchFinding:
    key = f"{kind}{('-' + suffix) if suffix else ''}-{today}"
    return WatchFinding(
        DETECTOR_DELIVERY, kind, "_host", SEVERITY_CRITICAL, key, detail, dict(metrics or {})
    )


# --------------------------------------------------------------------------- canary slots


def _canary(records: Sequence[_Record]) -> list[_Record]:
    return [
        r
        for r in records
        if r.writer == "canary" and r.body.get("attempt_kind", "canary") == "canary"
    ]


def _armed_mtime_ns(root: Path) -> int | None:
    try:
        return os.lstat(root / "armed.json").st_mtime_ns
    except OSError:
        return None


def _evidence_start_ns(inputs: DeliveryInputs, canary: Sequence[_Record]) -> int | None:
    """When the canary is first known to have been live: the oldest canary record in the scanned
    days or the arming marker's mtime. Only with neither does the timer's start bound the slots
    (a timer restart must not hide a slot the canary already proved it serves)."""
    marks = [r.ts_ns for r in canary]
    armed = _armed_mtime_ns(inputs.alerts_root)
    if armed is not None:
        marks.append(armed)
    return min(marks) if marks else inputs.canary_since_ns


def _slot_findings(
    inputs: DeliveryInputs, canary: Sequence[_Record], today: str
) -> tuple[list[WatchFinding], list[str], list[str]]:
    """``(findings, pending slots, skipped slots)``."""
    findings: list[WatchFinding] = []
    pending: list[str] = []
    skipped: list[str] = []
    midnight_ns = int(dt.datetime.combine(_day(inputs.now_ns), dt.time(), dt.UTC).timestamp()) * NS
    second = (inputs.now_ns - midnight_ns) // NS
    started = _evidence_start_ns(inputs, canary)
    ran_1710 = any(
        SLOT_1710_S <= (r.ts_ns - midnight_ns) // NS < SLOT_1710_END_S
        for r in canary
        if r.ts_ns >= midnight_ns
    )
    for slot, start_s in CANARY_SLOTS.items():
        start_ns = midnight_ns + start_s * NS
        if second < start_s + SLOT_SETTLE_S:
            continue
        if started is not None and start_ns + SLOT_SETTLE_S * NS <= started:  # the slot ended first
            skipped.append(slot)
            continue
        if any(r.delivered and r.ts_ns >= start_ns for r in canary):
            continue
        if slot in DEFERRED_SLOTS and not ran_1710 and second < JUDGE_DEFERRED_FROM_S:
            pending.append(slot)
            continue
        findings.append(
            _finding(
                "canary_slot_undelivered",
                today,
                f"canary slot {slot} has no delivered record",
                {"slot": slot},
                suffix=slot,
            )
        )
    return findings, pending, skipped


def _armed_findings(
    inputs: DeliveryInputs, canary: Sequence[_Record], today: str
) -> tuple[list[WatchFinding], dict[str, str]]:
    delivered = [r.ts_ns for r in canary if r.delivered]
    if not delivered:
        return [], {}
    old = inputs.now_ns - min(delivered) > ABANDON_AFTER_S * NS
    try:
        marker = read_armed_marker(inputs.alerts_root)
    except (OSError, ValueError):
        if old:
            return [_finding("armed_marker_unreadable", today, "armed.json unreadable")], {}
        return [], {"armed_marker_unreadable": "1"}
    if marker is None and old:
        return [_finding("armed_marker_missing", today, "armed.json absent 24h after delivery")], {}
    return [], {}


# --------------------------------------------------------------------------- the rest


def _record_findings(
    records: Sequence[_Record], inputs: DeliveryInputs, today: str
) -> list[WatchFinding]:
    floor = inputs.now_ns - ABANDON_AFTER_S * NS
    kinds: set[str] = set()
    for rec in records:
        if rec.ts_ns < floor:
            continue
        if rec.body.get("status_class") in _BAD_STATUS:
            kinds.add("outbox_overflow")
        if rec.body.get("outbox_write_failed") is True:
            kinds.add("outbox_write_failed")
        if rec.body.get("event") == "integrity_demand_write_failed":
            kinds.add("integrity_demand_write_failed")
    return [_finding(kind, today, f"{kind} record in the last 24h") for kind in sorted(kinds)]


def _outbox_findings(
    records: Sequence[_Record], inputs: DeliveryInputs, today: str
) -> tuple[list[WatchFinding], list[str], str]:
    findings: list[WatchFinding] = []
    failed: dict[str, int] = {}
    for rec in records:
        entry = rec.body.get("outbox_entry")
        if not rec.delivered and isinstance(entry, str) and entry:
            failed[entry] = failed.get(entry, 0) + 1
    abandoned: list[str] = []
    worst = 0
    entries, unreadable = _outbox_entries(inputs.alerts_root)
    for path in entries:
        match = _ENTRY_RE.fullmatch(path.name)
        if match is None:
            continue
        if inputs.now_ns - int(match.group(1)) > ABANDON_AFTER_S * NS:
            abandoned.append(path.name)
        worst = max(worst, failed.get(path.name, 0))
    if abandoned:
        names = ",".join(sorted(abandoned)[:5])
        findings.append(
            _finding("outbox_abandoned", today, f"abandoned entries: {names}", {"abandoned": names})
        )
    if worst > FAILED_ATTEMPTS_MAX:
        findings.append(
            _finding(
                "outbox_repeated_failed_attempts",
                today,
                "entry failed delivery repeatedly",
                {"failed_attempts": str(worst)},
            )
        )
    return findings, unreadable, str(worst) if worst > FAILED_ATTEMPTS_MAX else ""


def _root_findings(inputs: DeliveryInputs, today: str) -> tuple[list[WatchFinding], list[str]]:
    root = inputs.alerts_root
    findings: list[WatchFinding] = []
    if not inputs.access(root, os.W_OK):
        findings.append(_finding("record_root_unwritable", today, "record root not writable"))
        return findings, []
    try:
        free = inputs.free_bytes(root)
    except OSError:
        return findings, ["alert_root_statvfs_failed"]
    if free < RECORD_ROOT_MIN_FREE_BYTES:
        findings.append(
            _finding(
                "record_root_full", today, "record root under 64 MiB", {"free_bytes": str(free)}
            )
        )
    return findings, []


def _line_findings(inputs: DeliveryInputs, today: str) -> tuple[list[WatchFinding], list[str]]:
    findings: list[WatchFinding] = []
    unknown: list[str] = []
    if inputs.summary_lines is None:
        unknown.append("summary_lines_unreadable")
    else:
        text = "\n".join(inputs.summary_lines)
        for counter, pattern in _COUNTER_RES.items():
            if any(int(m) > 0 for m in pattern.findall(text)):
                findings.append(_finding(counter, today, f"{counter} above zero in a summary line"))
        if _DEMAND_INTEGRITY in text:
            findings.append(
                _finding("demand_stage_integrity_line", today, "demand stage INTEGRITY")
            )
    if inputs.node_log_tail is None:
        unknown.append("node_log_tail_unreadable")
    elif _JOURNAL_UNWRITABLE in inputs.node_log_tail:
        findings.append(_finding("journal_unwritable_line", today, "node log journal unwritable"))
    return findings, unknown


def evaluate_delivery(inputs: DeliveryInputs) -> DetectorResult:
    today = _day(inputs.now_ns).isoformat()
    records, unknown = _records(inputs.alerts_root, inputs.now_ns)
    canary = _canary(records)
    findings: list[WatchFinding] = []
    metrics: dict[str, str] = {}
    root_found, root_unknown = _root_findings(inputs, today)
    line_found, line_unknown = _line_findings(inputs, today)
    slot_found, pending, skipped = _slot_findings(inputs, canary, today)
    armed_found, armed_metrics = _armed_findings(inputs, canary, today)
    outbox_found, outbox_unknown, failed_attempts = _outbox_findings(records, inputs, today)
    for batch in (
        root_found,
        slot_found,
        armed_found,
        _record_findings(records, inputs, today),
        outbox_found,
        line_found,
    ):
        findings.extend(batch)
    unknown.extend([*root_unknown, *line_unknown, *outbox_unknown])
    metrics.update(armed_metrics)
    if pending:
        metrics["canary_slot_pending"] = ",".join(pending)
    if skipped:
        metrics["canary_slots_skipped"] = ",".join(skipped)
    if failed_attempts:
        metrics["failed_attempts"] = failed_attempts
    if findings:
        outcome = Outcome.FAIL
    elif skipped:
        outcome = Outcome.INCONCLUSIVE  # a slot nothing proves was due is never a PASS
    else:
        outcome = Outcome.PASS
    return DetectorResult(DETECTOR_DELIVERY, outcome, tuple(findings), metrics, tuple(unknown))


__all__ = ["DAY_S", "DeliveryInputs", "evaluate_delivery"]
