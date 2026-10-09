"""AUT-6 WP3 S5: ``#23 aut6.alert_delivery`` (plan r15 sections 3.2, 3.6 and 3.7).

Records, outbox entries and the armed marker are real files under a temp alerts root; the summary
lines, the node-log tail, ``os.access`` and ``statvfs`` are injected.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from breezy.runtime.alert_outbox import write_armed_marker
from breezy.runtime.monitor_watch_delivery import (
    RECORD_ROOT_MIN_FREE_BYTES,
    DeliveryInputs,
    evaluate_delivery,
)
from tests.support.unit_health_fixtures import NOW_NS, NS

DAY_NS = 86_400 * NS
MIDNIGHT = NOW_NS - 12 * 3600 * NS  # 2026-10-08T00:00:00Z


def at(hhmm: str, seconds: int = 0, day_offset: int = 0) -> int:
    hours, minutes = (int(x) for x in hhmm.split(":"))
    return MIDNIGHT + day_offset * DAY_NS + (hours * 3600 + minutes * 60 + seconds) * NS


def put(root: Path, ts_ns: int, writer: str = "canary", delivered: bool = True, **body: Any) -> str:
    day = dt.datetime.fromtimestamp(ts_ns / NS, tz=dt.UTC).date().isoformat()
    directory = root / day
    directory.mkdir(parents=True, exist_ok=True)
    name = f"{ts_ns}_{writer}_{'d' if delivered else 'f'}.json"
    record = {
        "schema": "alert_delivery/v1",
        "event": "autonomy_canary",
        "ts_ns": ts_ns,
        "delivered": delivered,
        "attempt_kind": "canary" if writer == "canary" else "drain",
        "status_class": "2xx" if delivered else "5xx",
        "severity": "INFO",
        "drill": False,
        "site": "global",
        "outbox_entry": "",
        **body,
    }
    (directory / name).write_text(json.dumps(record), encoding="utf-8")
    return name


def entry(root: Path, ts_ns: int, event: str = "x_event", claimed_by: str | None = None) -> str:
    base = root / "outbox" / "claimed" / claimed_by if claimed_by else root / "outbox"
    base.mkdir(parents=True, exist_ok=True)
    name = f"{ts_ns}_{event}.json"
    (base / name).write_text("{}", encoding="utf-8")
    return name


def judge(root: Path, now_ns: int, **kw: Any) -> Any:
    root.mkdir(parents=True, exist_ok=True)
    defaults: dict[str, Any] = {
        "alerts_root": root,
        "now_ns": now_ns,
        "summary_lines": [],
        "node_log_tail": "",
        "free_bytes": lambda _p: 10 * RECORD_ROOT_MIN_FREE_BYTES,
    }
    defaults.update(kw)
    return evaluate_delivery(DeliveryInputs(**defaults))


def kinds(result: Any) -> list[str]:
    return sorted(f.kind for f in result.findings)


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path / "alerts"


def delivered_slots(root: Path, *slots: str) -> None:
    for slot in slots:
        put(root, at(slot, 2))


# --------------------------------------------------------------------------- healthy


def test_a_quiet_root_with_all_slots_delivered_passes(root: Path) -> None:
    delivered_slots(root, "15:45", "16:30", "16:45")
    result = judge(root, at("17:30"))
    assert result.outcome == "PASS" and not result.unknown_reasons, result.findings
    assert "canary_slot_pending" not in result.metrics


def test_before_the_first_slot_nothing_is_due(root: Path) -> None:
    assert judge(root, at("15:46")).outcome == "PASS"  # 15:45 settles at 15:47
    assert judge(root, at("09:00")).outcome == "PASS"


# --------------------------------------------------------------------------- canary slots


def test_alert_delivery_fails_on_undelivered_scheduled_canary_slot(root: Path) -> None:
    put(root, at("15:45", 1), delivered=False, status_class="5xx")
    result = judge(root, at("15:48"))
    assert kinds(result) == ["canary_slot_undelivered"]
    assert result.findings[0].metrics["slot"] == "1545"
    assert result.findings[0].severity == "CRITICAL"
    put(root, at("16:30", 1))  # a later delivery clears the earlier slot (its retry)
    assert judge(root, at("16:33")).outcome == "PASS"


def test_a_slot_with_no_record_at_all_is_undelivered_once_settled(root: Path) -> None:
    assert kinds(judge(root, at("15:48"))) == ["canary_slot_undelivered"]
    assert judge(root, at("15:46")).outcome == "PASS"


def test_alert_delivery_judges_1630_1645_slots_only_after_1710_record_or_1721(root: Path) -> None:
    """r6, S2: at the real 17:11:00Z pass with the 17:10Z firing still running (no record) the
    slot is pending; with an ``f`` record it fails; at 17:21Z with no record it fails."""
    delivered_slots(root, "15:45")
    put(root, at("16:30", 1), delivered=False)
    put(root, at("16:45", 1), delivered=False)
    pending = judge(root, at("17:11", 0))
    assert pending.outcome == "PASS" and pending.metrics["canary_slot_pending"] == "1630,1645"
    put(root, at("17:10", 3), delivered=False)
    failed = judge(root, at("17:11", 0))
    assert [f.metrics["slot"] for f in failed.findings] == ["1630", "1645"]
    assert "canary_slot_pending" not in failed.metrics


def test_alert_delivery_1711_boundary_with_1710_retry_in_flight_is_pending(root: Path) -> None:
    delivered_slots(root, "15:45")
    put(root, at("16:30", 1), delivered=False)
    put(root, at("16:45", 1), delivered=False)
    for hhmm, second in (("17:11", 0), ("17:15", 30), ("17:20", 59)):
        result = judge(root, at(hhmm, second))
        assert result.outcome == "PASS", hhmm
        assert result.metrics["canary_slot_pending"] == "1630,1645"
    assert kinds(judge(root, at("17:21", 0))) == ["canary_slot_undelivered"] * 2


def test_a_delivered_1710_record_clears_the_deferred_slots(root: Path) -> None:
    delivered_slots(root, "15:45")
    put(root, at("16:30", 1), delivered=False)
    put(root, at("16:45", 1), delivered=False)
    put(root, at("17:10", 5))
    assert judge(root, at("17:11")).outcome == "PASS"


def test_a_failed_slot_followed_by_a_delivery_inside_the_window_is_not_pending(
    root: Path,
) -> None:
    delivered_slots(root, "15:45")
    put(root, at("16:30", 1), delivered=False)
    put(root, at("16:45", 1))  # 16:45 delivered: the 16:30 slot has its later delivery
    result = judge(root, at("16:50"))
    assert result.outcome == "PASS" and "canary_slot_pending" not in result.metrics


def test_a_slot_before_any_canary_evidence_is_skipped_inconclusive_with_a_metric(
    root: Path,
) -> None:
    """With no record and no marker the timer's start is the only bound; the skipped slot is
    never read as a PASS."""
    result = judge(root, at("16:00"), canary_since_ns=at("15:50"))
    assert result.outcome == "INCONCLUSIVE" and not result.findings
    assert result.metrics["canary_slots_skipped"] == "1545"
    assert kinds(judge(root, at("16:00"), canary_since_ns=at("09:00"))) == [
        "canary_slot_undelivered"
    ]


def test_earliest_evidence_beats_a_restarted_timers_active_enter(root: Path) -> None:
    """A timer restart at 15:50 must not hide the 15:45 slot once a record from before exists."""
    put(root, at("09:00", 1), delivered=True)  # the canary ran this morning
    result = judge(root, at("16:00"), canary_since_ns=at("15:50"))
    assert kinds(result) == ["canary_slot_undelivered"]
    assert "canary_slots_skipped" not in result.metrics


def test_armed_marker_mtime_counts_as_earliest_evidence(root: Path) -> None:
    import os

    write_armed_marker(root, record="x", ts_ns=at("08:00"))
    os.utime(root / "armed.json", ns=(at("08:00"), at("08:00")))
    result = judge(root, at("16:00"), canary_since_ns=at("15:50"))
    assert kinds(result) == ["canary_slot_undelivered"]


# --------------------------------------------------------------------------- armed marker


def test_alert_delivery_fails_when_armed_marker_missing_24h_after_delivered_canary(
    root: Path,
) -> None:
    put(root, at("15:45", 1, day_offset=-1))  # yesterday: 24 h 5 min before the pass below
    result = judge(root, at("15:50"), summary_lines=[])
    assert "armed_marker_missing" in kinds(result)
    write_armed_marker(root, record="x", ts_ns=at("15:45", day_offset=-1))
    assert "armed_marker_missing" not in kinds(judge(root, at("15:50")))


def test_armed_marker_not_yet_24h_old_is_not_a_fail(root: Path) -> None:
    put(root, at("16:30", 1, day_offset=-1))
    assert "armed_marker_missing" not in kinds(judge(root, at("15:50")))


def test_a_corrupt_armed_marker_is_a_finding_after_24h_and_a_metric_before(root: Path) -> None:
    put(root, at("15:45", 1, day_offset=-1))
    (root / "armed.json").write_text("not json", encoding="utf-8")
    old = judge(root, at("15:50"))
    finding = next(f for f in old.findings if f.kind == "armed_marker_unreadable")
    assert finding.severity == "CRITICAL" and "armed_marker_missing" not in kinds(old)
    assert not old.unknown_reasons
    young = judge(root, at("16:00", day_offset=-1))  # 15 min after the first delivery
    assert "armed_marker_unreadable" not in kinds(young)
    assert young.metrics["armed_marker_unreadable"] == "1"


# --------------------------------------------------------------------------- the outbox


def test_alert_delivery_fails_on_abandoned_entry_or_repeated_reclaim(root: Path) -> None:
    old = entry(root, at("10:00", day_offset=-1) - NS)  # > 24 h before 10:00 the next day
    result = judge(root, at("10:01"))
    assert kinds(result) == ["outbox_abandoned"] and old in result.findings[0].detail
    assert judge(root, at("09:00")).outcome == "PASS"  # 23 h old: not abandoned
    claimed = entry(root, at("08:00"), "stuck", claimed_by="redeliver")
    for i in range(4):
        put(root, at("08:10") + i * NS, "redeliver", delivered=False, outbox_entry=claimed)
    result = judge(root, at("09:00"))
    assert "outbox_repeated_failed_attempts" in kinds(result)
    assert result.metrics["failed_attempts"] == "4" and "reclaims" not in result.metrics


def test_three_failed_reattempts_are_not_a_repeated_reclaim(root: Path) -> None:
    claimed = entry(root, at("08:00"), "stuck", claimed_by="redeliver")
    for i in range(3):
        put(root, at("08:10") + i * NS, "redeliver", delivered=False, outbox_entry=claimed)
    assert judge(root, at("09:00")).outcome == "PASS"


@pytest.mark.parametrize(
    ("body", "kind"),
    [
        ({"status_class": "outbox_overflow"}, "outbox_overflow"),
        ({"outbox_write_failed": True}, "outbox_write_failed"),
        ({"event": "integrity_demand_write_failed"}, "integrity_demand_write_failed"),
    ],
)
def test_overflow_write_failed_and_integrity_records_fail(
    root: Path, body: dict[str, Any], kind: str
) -> None:
    put(root, at("08:00"), "health", delivered=False, **body)
    assert kinds(judge(root, at("09:00"))) == [kind]
    assert judge(root, at("09:00", day_offset=1)).outcome == "PASS"  # 25 h old: out of the window


def test_alert_delivery_fails_on_integrity_demand_write_failure(root: Path) -> None:
    """F3: a record of the failed write, or the stage's own counter, fails #23."""
    put(root, at("08:00"), "intraday", event="integrity_demand_write_failed", delivered=False)
    assert "integrity_demand_write_failed" in kinds(judge(root, at("09:00")))
    result = judge(
        root / "other",
        at("09:00"),
        summary_lines=["PRODUCER_INTRADAY_DEMAND wrote=0 integrity_demand_write_failures=2"],
    )
    assert "integrity_demand_write_failures" in kinds(result)


def test_alert_delivery_keys_on_producer_intraday_demand_line_and_record(root: Path) -> None:
    """AA3: the demand stage's own line decides, never the evaluate stage's line."""
    clean = ["PRODUCER_INTRADAY exit=0 integrity_demand_write_failures=0 wrote=1"]
    assert judge(root, at("09:00"), summary_lines=clean).outcome == "PASS"
    line = ["PRODUCER_INTRADAY_DEMAND INTEGRITY demand_listing_unreadable"]
    assert kinds(judge(root, at("09:00"), summary_lines=line)) == ["demand_stage_integrity_line"]
    counter = ["PRODUCER_INTRADAY_DEMAND wrote=0 integrity_demand_write_failures=1"]
    assert kinds(judge(root, at("09:00"), summary_lines=counter)) == [
        "integrity_demand_write_failures"
    ]


# --------------------------------------------------------------------------- counters and root


@pytest.mark.parametrize(
    "counter",
    ["journal_write_failures", "outbox_write_failures", "integrity_demand_write_failures"],
)
def test_alert_delivery_fails_on_journal_write_failures_counter(root: Path, counter: str) -> None:
    zero = [f"AUTONOMY_REDELIVER delivered=0 {counter}=0"]
    assert judge(root, at("09:00"), summary_lines=zero).outcome == "PASS"
    bad = [f"AUTONOMY_REDELIVER delivered=0 {counter}=3"]
    result = judge(root, at("09:00"), summary_lines=bad)
    assert kinds(result) == [counter]


def test_alert_delivery_journal_unwritable_line_in_the_node_log_tail_fails(root: Path) -> None:
    tail = "x\nERROR alert_delivery_journal_unwritable exception_type=OSError\n"
    assert kinds(judge(root, at("09:00"), node_log_tail=tail)) == ["journal_unwritable_line"]


def test_alert_delivery_fails_on_unwritable_or_full_record_root(root: Path) -> None:
    denied = judge(root, at("09:00"), access=lambda _p, _m: False)
    assert kinds(denied) == ["record_root_unwritable"]
    full = judge(root, at("09:00"), free_bytes=lambda _p: RECORD_ROOT_MIN_FREE_BYTES - 1)
    assert kinds(full) == ["record_root_full"]
    exact = judge(root, at("09:00"), free_bytes=lambda _p: RECORD_ROOT_MIN_FREE_BYTES)
    assert exact.outcome == "PASS"


def test_a_failing_statvfs_is_unknown_never_a_pass(root: Path) -> None:
    def broken(_path: Path) -> int:
        raise OSError("eio")

    assert (
        "alert_root_statvfs_failed" in judge(root, at("09:00"), free_bytes=broken).unknown_reasons
    )


def test_unreadable_summary_lines_or_node_log_are_unknown(root: Path) -> None:
    result = judge(root, at("09:00"), summary_lines=None, node_log_tail=None)
    assert set(result.unknown_reasons) == {"summary_lines_unreadable", "node_log_tail_unreadable"}


def test_unreadable_record_directory_is_unknown(root: Path) -> None:
    today = root / "2026-10-08"
    today.mkdir(parents=True)
    today.chmod(0)
    try:
        result = judge(root, at("09:00"))
    finally:
        today.chmod(0o700)
    assert "alert_records_unreadable" in result.unknown_reasons


def test_findings_are_keyed_per_day_so_a_standing_condition_pages_once_a_day(root: Path) -> None:
    keys = {f.key for f in judge(root, at("15:48")).findings}
    again = {f.key for f in judge(root, at("15:58")).findings}
    assert keys == again == {"canary_slot_undelivered-1545-2026-10-08"}
    nxt = {f.key for f in judge(root, at("15:48", day_offset=1)).findings}
    assert nxt == {"canary_slot_undelivered-1545-2026-10-09"}


def test_summary_lines_type_is_a_sequence_of_strings() -> None:
    lines: Sequence[str] = ["a"]
    assert DeliveryInputs(Path("/x"), 0, summary_lines=lines).summary_lines == lines
