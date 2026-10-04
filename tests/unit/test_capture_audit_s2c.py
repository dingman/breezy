"""AUT-1 WP5 stage 2c: the integration seams and the rulings S2-R18, S2-R22, S2-R23 and S2-R25.

W1, W2 and W3 were built blind to each other; these tests drive the REAL legs and the REAL reducer
sinks through the REAL orchestration, so a seam between two builders fails here.
"""

import dataclasses
import datetime as dt
from pathlib import Path
from typing import Any

import pytest

from breezy.analysis import capture_audit as audit
from breezy.analysis import capture_audit_cache as cache
from breezy.analysis import capture_audit_inputs as inputs
from breezy.analysis.capture_audit_input_types import ReplayResult
from breezy.analysis.capture_audit_log_markers import MarkerParser
from breezy.analysis.capture_audit_model import (
    ERROR_CAUSES,
    AuditInputError,
    DayStatus,
    LegOutcome,
)
from breezy.analysis.capture_audit_replay import BootReplay, leg_r1, leg_r3
from tests.support import capture_audit_fixtures as fx
from tests.support import capture_audit_w3_fixtures as w3
from tests.support.capture_audit_recon_fixtures import (
    T,
    analyse,
    boot_for,
    inputs_for,
    instance_line,
)
from tests.support.capture_audit_run_support import (
    Offers,
)
from tests.support.capture_audit_run_support import (
    fake_gather as _fake_gather,
)
from tests.support.capture_audit_run_support import (
    quiet_duties as _quiet_duties,
)
from tests.support.capture_audit_run_support import (
    run as _run,
)
from tests.support.capture_audit_s2c_fixtures import PASS_FIXTURES
from tests.support.capture_audit_w3_fixtures import leg_result, stub_legs
from tests.unit.test_capture_audit_recon_legs import take_pair

DAY = fx.DAY
TODAY = DAY + dt.timedelta(days=1)


def _real_sinks(monkeypatch: pytest.MonkeyPatch) -> None:
    """``w3.install`` plants fakes for the W2 sinks; the seam tests want the real ones."""
    monkeypatch.setattr(inputs, "BootReplay", BootReplay)
    monkeypatch.setattr(inputs, "MarkerParser", MarkerParser)


# -- the W2 sinks through W3's per-log cache ---------------------------------------------------


def test_a_real_sink_result_round_trips_through_the_scan_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SEAM: the real reducer's per-day result type must be a cacheable type, or the cache is never
    written and every run re-scans every log (S2-R6's steady state)."""
    root = w3.full_world(tmp_path, monkeypatch)
    _real_sinks(monkeypatch)
    (log,) = inputs._listed_logs(root)
    result = inputs._scan_one(log)
    assert result.replay, "the fixture's Take line must reach the replay reducer"
    decoded = cache._decode_result(cache.encode_result(result, "k"), "k")
    assert decoded is not None and dict(decoded.replay) == dict(result.replay)
    assert decoded.scan == result.scan


def test_a_rotated_log_is_scanned_once_and_then_served_from_the_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scans: list[Path] = []
    root = w3.full_world(tmp_path, monkeypatch, scans=scans)
    _real_sinks(monkeypatch)
    first = w3.gather(root)
    second = w3.gather(root)
    assert len(scans) == 1
    assert second.boots[0].replay == first.boots[0].replay
    assert first.boots[0].replay.evaluations == 1


# -- S2-R18: a truncated entry list is ERROR, never a silent pass ------------------------------


def _capped(tmp_path: Path) -> Any:
    lines, views = take_pair()
    analysis = analyse(tmp_path, [instance_line(T - 10**9), *lines])
    fields = {f.name: getattr(analysis.scan, f.name) for f in dataclasses.fields(analysis.scan)}
    capped = type(analysis.scan)(**{**fields, "entry_total": len(analysis.scan.entry_lines) + 1})
    return inputs_for(boot_for(analysis, views, scan=capped))


def test_a_truncated_entry_list_is_an_error_for_r1_and_r3(tmp_path: Path) -> None:
    inp = _capped(tmp_path)
    for leg in (leg_r1, leg_r3):
        result = leg(inp)
        assert result.outcome is LegOutcome.ERROR, leg.__name__
        assert [f.cause for f in result.findings] == ["entry_lines_capped"], leg.__name__


# -- S2-R22: a settlement read failure has its own cause ---------------------------------------


def test_settlement_unreadable_is_a_closed_error_cause() -> None:
    assert "settlement_unreadable" in ERROR_CAUSES
    assert AuditInputError("settlement_unreadable", "x").cause == "settlement_unreadable"


def test_an_unreadable_settlement_file_is_settlement_unreadable_not_a_projection_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = w3.full_world(tmp_path, monkeypatch)
    path = root / "catalog" / "quote_tape" / "decisions" / f"settlement_{DAY}.jsonl"
    path.write_text("not json\n")
    path.chmod(0o600)
    with pytest.raises(AuditInputError) as caught:
        w3.gather(root)
    assert caught.value.cause == "settlement_unreadable"


# -- S2-R23: ERROR is not terminal -------------------------------------------------------------


def test_an_error_day_is_re_audited_after_the_inconclusive_days_oldest_first() -> None:
    """S2-R23 (ERROR is not terminal) as ordered by S2-R44: yesterday, INCONCLUSIVE, the days never
    audited, then ERROR; with no missing day, INCONCLUSIVE then ERROR oldest-first."""

    def day(back: int) -> dt.date:
        return TODAY - dt.timedelta(days=back)

    audited = {d: DayStatus.PASS for d in (day(n) for n in range(2, 9))}
    audited[day(5)] = DayStatus.ERROR
    audited[day(3)] = DayStatus.INCONCLUSIVE
    audited[day(7)] = DayStatus.ERROR
    assert audit.days_to_audit(TODAY, audited) == (day(1), day(3), day(7), day(5))


def test_pass_fail_and_pre_capture_days_are_still_final() -> None:
    final = (DayStatus.PASS, DayStatus.FAIL, DayStatus.NO_INPUT, DayStatus.PRE_CAPTURE)
    for status in final:
        audited = {TODAY - dt.timedelta(days=n): status for n in range(2, 9)}
        assert audit.days_to_audit(TODAY, audited) == (TODAY - dt.timedelta(days=1),), status


def test_a_run_re_audits_a_day_that_ended_in_error_and_replaces_its_verdict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = w3.make_root(tmp_path)
    stub_legs(monkeypatch)
    _quiet_duties(monkeypatch)
    stale = AuditInputError("bus_snapshot_stale", "aged")
    old = TODAY - dt.timedelta(days=4)
    _fake_gather(monkeypatch, **{old.isoformat(): stale})
    _run(root, Offers())
    assert audit._audited_statuses(root, fx.FAMILY_ID)[old] is DayStatus.ERROR
    asked = _fake_gather(monkeypatch)  # the cause is gone
    assert _run(root, Offers()) == 0
    assert asked == [DAY, old]  # yesterday, then the ERROR day; the other days are final
    assert audit._audited_statuses(root, fx.FAMILY_ID)[old] is not DayStatus.ERROR


def test_a_scan_that_failed_is_never_cached(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only a finished, parsed scan is cached: an unparseable marker (ERROR) leaves no entry, so the
    next run scans the log again rather than serving a remembered failure."""
    root = w3.full_world(tmp_path, monkeypatch)
    _real_sinks(monkeypatch)
    (log,) = inputs._listed_logs(root)
    with log.open("a") as handle:
        handle.write("2026-10-03T22:00:00.000000000Z [WARNING] BREEZY-L001.X: CAPTURE_REFUSED {x\n")
    with pytest.raises(AuditInputError) as caught:
        inputs._scan_log(root, log)
    assert caught.value.cause == "node_log_unparseable"
    cache_dir = root.joinpath(*cache.cache_dir_parts())
    assert not cache_dir.exists() or not list(cache_dir.glob(f"{cache.CACHE_PREFIX}*"))


# -- S2-R25: every PASS fixture is consistent and audits to PASS through the real legs ----------


@pytest.mark.parametrize("name", sorted(PASS_FIXTURES))
def test_each_pass_fixture_audits_to_pass_through_the_real_legs(name: str) -> None:
    result = audit.audit_day(PASS_FIXTURES[name]())
    failing = [
        (leg.leg.value, [f.cause for f in leg.findings])
        for leg in (*result.legs, *(leg for fill in result.fills for leg in fill.legs))
        if leg.outcome not in (LegOutcome.PASS, LegOutcome.SKIPPED, LegOutcome.INFO)
    ]
    assert (result.status, result.cause, failing) == (DayStatus.PASS, "", [])


@pytest.mark.parametrize("name", sorted(PASS_FIXTURES))
def test_a_pass_fixture_replay_counts_exactly_its_decisions(name: str) -> None:
    (boot,) = PASS_FIXTURES[name]().boots
    assert boot.replay.admitted_total == len(boot.c1.decisions) > 0
    assert sum(boot.replay.admitted_by_kind.values()) == boot.replay.admitted_total


def test_the_default_replay_fixture_admits_nothing_because_the_default_boot_logs_nothing() -> None:
    """The stage-2a default said ``admitted_total=1`` for a boot with no decision."""
    boot = fx.make_boot()
    assert boot.c1.decisions == ()
    assert boot.replay == ReplayResult(
        admitted_total=0, admitted_by_kind={}, evaluations=0, eval_seq_final=0
    )


# -- S2-R27: the epoch check reads the REAL heartbeat table name ----------------------------


def test_a_boot_with_a_streamed_heartbeat_and_no_epoch_record_is_epoch_missing() -> None:
    boot = fx.make_boot(summary=fx.make_stream_summary())
    assert boot.summary.row_counts == {"custom_capture_heartbeat": 1}
    with pytest.raises(AuditInputError) as info:
        inputs._check_epoch(None, [boot], [], DAY)
    assert info.value.cause == "epoch_missing"


def test_a_boot_with_no_heartbeat_rows_and_no_epoch_record_is_fine() -> None:
    boot = fx.make_boot(summary=fx.make_stream_summary(row_counts={}, heartbeats=()))
    inputs._check_epoch(None, [boot], [], DAY)


# -- S2-R44: a day never audited is not starved by ERROR re-audits ----------------------------


def test_days_never_audited_come_before_error_re_audits() -> None:
    """MUTATION: ERROR days ordered before the missing days. A persistent ERROR must not let a
    never-audited day age out of the window."""

    def day(back: int) -> dt.date:
        return TODAY - dt.timedelta(days=back)

    audited = {day(7): DayStatus.ERROR, day(6): DayStatus.ERROR, day(2): DayStatus.PASS}
    order = audit.days_to_audit(TODAY, audited)
    assert order == (day(1), day(8), day(5), day(4), day(3), day(7), day(6))


def _errors_sent(offers: Offers) -> list[str]:
    return [detail for event, _sev, detail in offers.calls if event == "CAPTURE_AUDIT_ERROR"]


def test_capture_audit_error_is_sent_once_per_day_and_cause_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """MUTATION: send on every run. The outbox has no dedupe of its own (the offer is injected), so
    the audit re-sends only when the day's cause set changed."""
    root = w3.make_root(tmp_path)
    stub_legs(monkeypatch)
    _quiet_duties(monkeypatch)
    old = TODAY - dt.timedelta(days=4)

    def run_with(cause: str) -> Offers:
        _fake_gather(monkeypatch, **{old.isoformat(): AuditInputError(cause, "x")})
        offers = Offers()
        assert _run(root, offers) == 1  # an ERROR day always keeps the unit loud
        return offers

    first = run_with("tape_unreadable")
    second = run_with("tape_unreadable")
    third = run_with("journal_failed")
    assert [d.count(f"day={old}") for d in _errors_sent(first)] == [1]
    assert _errors_sent(second) == []
    assert [d.count(f"day={old}") for d in _errors_sent(third)] == [1]
    assert audit._audited_statuses(root, fx.FAMILY_ID)[old] is DayStatus.ERROR


def test_the_error_cause_set_names_every_errored_leg_and_the_day_cause() -> None:
    single = audit.error_result(DAY, fx.FAMILY_ID, "tape_unreadable", pre_capture=False)
    assert audit.error_cause_set(single) == frozenset({"tape_unreadable"})
    legs = (
        leg_result("R1", "ERROR", "journal_failed"),
        leg_result("PC", "ERROR", "tape_unreadable"),
    )
    result = dataclasses.replace(single, cause="journal_failed", legs=legs)
    assert audit.error_cause_set(result) == frozenset({"journal_failed", "tape_unreadable"})


# -- S2-R45: ANY data ERROR beats the PRE_CAPTURE mask ---------------------------------------


def test_a_data_error_after_a_host_state_error_still_beats_pre_capture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MUTATION: judge only the first errored leg. R1 (a host-state ERROR) precedes PC (a data
    ERROR) in leg order, and the data ERROR must still win over the mask."""
    stub_legs(
        monkeypatch,
        R1=leg_result("R1", "ERROR", "bus_snapshot_stale"),
        PC=leg_result("PC", "ERROR", "tape_unreadable"),
    )
    result = audit.audit_day(fx.make_inputs(epoch=None))
    assert (result.status, result.cause) == (DayStatus.ERROR, "tape_unreadable")


def test_only_host_state_errors_are_still_masked_before_the_epoch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_legs(
        monkeypatch,
        R1=leg_result("R1", "ERROR", "bus_snapshot_stale"),
        PC=leg_result("PC", "ERROR", "bus_snapshot_missing"),
    )
    assert audit.audit_day(fx.make_inputs(epoch=None)).status is DayStatus.PRE_CAPTURE


# -- S2-R46: the entry-list cap is checked before the missing-last-line early return ---------


def test_the_cap_is_checked_before_a_missing_last_line_in_r3(tmp_path: Path) -> None:
    """MUTATION: the ``last_ts is None`` early return before the cap check."""
    lines, views = take_pair()
    analysis = analyse(tmp_path, [instance_line(T - 10**9), *lines])
    fields = {f.name: getattr(analysis.scan, f.name) for f in dataclasses.fields(analysis.scan)}
    capped = type(analysis.scan)(
        **{
            **fields,
            "entry_total": len(analysis.scan.entry_lines) + 1,
            "last_line_ts_ns": None,
        }
    )
    boot = boot_for(analysis, views, scan=capped, last_line_ts_ns=None)
    result = leg_r3(inputs_for(boot))
    assert [f.cause for f in result.findings] == ["entry_lines_capped"]
    assert result.outcome is LegOutcome.ERROR


def test_entry_lines_capped_is_a_closed_error_cause() -> None:
    assert "entry_lines_capped" in ERROR_CAUSES
