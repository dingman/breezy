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
from tests.support.capture_audit_s2c_fixtures import PASS_FIXTURES
from tests.support.capture_audit_w3_fixtures import stub_legs
from tests.unit.test_capture_audit import Offers, _fake_gather, _quiet_duties, _run
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
    decoded = cache._decode_result(cache.encode_result(result))
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


def test_an_error_day_is_re_audited_with_the_inconclusive_days_oldest_first() -> None:
    def day(back: int) -> dt.date:
        return TODAY - dt.timedelta(days=back)

    audited = {d: DayStatus.PASS for d in (day(n) for n in range(2, 9))}
    audited[day(5)] = DayStatus.ERROR
    audited[day(3)] = DayStatus.INCONCLUSIVE
    audited[day(7)] = DayStatus.ERROR
    assert audit.days_to_audit(TODAY, audited) == (day(1), day(7), day(5), day(3))


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
