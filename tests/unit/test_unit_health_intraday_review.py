"""AUT-6 WP3 S4 review round: intraday unit renames, unjudged invocations, window clamp, pending
episodes, INTEGRITY verification and unit-failed endings (plan r15 section 3.4.2)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.support.unit_health_daemon_fixtures import (
    INTRADAY,
    at_us,
    exited,
    failed,
    intraday_run,
)
from tests.support.unit_health_daemon_world import (
    DAY_S,
    World,
)
from tests.support.unit_health_fixtures import (
    NS,
    inv,
    show_block,
)
from tests.unit.test_unit_health_intraday import (
    ENTRY,
    HIT_RUN,
    _delivery_record,
    _demand,
    _findings,
    _intraday_world,
    _outbox_entry,
    _stage_queued,
)

# --------------------------------------------------------------------------- review round


@pytest.fixture
def w(tmp_path: Path) -> World:
    return World(tmp_path)


def test_renamed_intraday_unit_is_a_finding_and_absence_is_silent(w: World) -> None:
    w.units = [show_block("breezy-autonomy-producer-intraday-v2.service")]
    result = w.run(0)
    assert "intraday_unit_renamed:breezy-autonomy-producer-intraday-v2.service" in (
        result.unknown_reasons
    )
    assert "intraday_unit_renamed" in w.events
    quiet = World(w.tmp_path / "quiet")
    quiet.units = [show_block("breezy-portfolio-roi.service")]
    assert quiet.run(0).unknown_reasons == ()
    assert quiet.events == []


def test_invocation_absent_from_the_journal_window_is_unjudged(w: World) -> None:
    _intraday_world(w, current=1)
    w.run(0)
    _intraday_world(w, current=2)  # inv 1 left the unit and the journal never showed it
    w.run()
    assert "daemon_invocation_unjudged" in w.events
    assert w.records("daemon_invocation_unjudged")[0]["key"].endswith(inv(1))


def test_invocation_seen_in_the_window_is_not_unjudged(w: World) -> None:
    _intraday_world(w, current=1)
    w.run(0)
    w.journal.add(intraday_run(inv(1), 100))
    _intraday_world(w, current=2)
    w.run()
    assert "daemon_invocation_unjudged" not in w.events


def test_intraday_window_is_clamped_to_the_max_lookback_with_a_reason(w: World) -> None:
    _intraday_world(w)
    w.run(0)
    result = w.run(3 * DAY_S)
    call = w.journal.unit_kwargs[-1]
    now_us = w.h.clock.now_ns // 1000
    assert call["since_us"] == now_us - 26 * 3600 * 1_000_000
    assert "intraday_window_clamped" in result.unknown_reasons


def test_episode_end_with_pending_pages_the_undelivered_pending_invocation(w: World) -> None:
    _intraday_world(w)
    hit_ns = (at_us(-200) + 5_000_000) * 1000
    w.journal.add(intraday_run(inv(1), -200, **HIT_RUN))
    _stage_queued(w, hit_ns)
    w.run(0)
    assert w.payloads("demand_stage_deadline_hit") == []  # pending
    w.journal.add(intraday_run(inv(2), 300))  # a clean ended run ends the episode
    w.run(600)
    assert len(w.payloads("demand_stage_deadline_hit")) == 1
    path = w.store.root / "seen" / "_intraday_episode_demand_stage_deadline_hit.json"
    episode = json.loads(path.read_text())
    assert episode["state"] == "ended" and episode["pending"] == []


def test_episode_end_with_pending_binds_a_delivered_stage_page_without_paging(w: World) -> None:
    _intraday_world(w)
    hit_ns = (at_us(-200) + 5_000_000) * 1000
    w.journal.add(intraday_run(inv(1), -200, **HIT_RUN))
    _stage_queued(w, hit_ns)
    w.run(0)
    _delivery_record(w, ts_ns=hit_ns + 120 * NS, entry=ENTRY)
    w.journal.add(intraday_run(inv(2), 300))
    w.run(600)
    assert w.payloads("demand_stage_deadline_hit") == []
    assert w.store.read_action(INTRADAY, f"demand_stage_deadline_hit-{inv(1)}") is not None


def test_integrity_exit_3_without_any_stage_page_pages_a_warning(w: World) -> None:
    _intraday_world(w)
    w.journal.add(intraday_run(inv(1), -200, exit_status=3, demand_summary=_demand(ex=3)))
    w.run(0)
    pages = w.payloads("demand_stage_integrity")
    assert len(pages) == 1 and pages[0].severity == "WARNING"


@pytest.mark.parametrize("evidence", ["delivered_record", "outbox_entry", "stage_record"])
def test_integrity_exit_3_with_stage_page_evidence_is_not_paged_again(
    w: World, evidence: str
) -> None:
    _intraday_world(w)
    first_ns = at_us(-200) * 1000
    w.journal.add(intraday_run(inv(1), -200, exit_status=3, demand_summary=_demand(ex=3)))
    if evidence == "delivered_record":
        _delivery_record(w, ts_ns=first_ns + NS, entry="", event="bwrap_self_probe_failed")
    elif evidence == "outbox_entry":
        _outbox_entry(w, "bwrap_self_probe_failed", first_ns + NS)
    else:
        _stage_queued(w, first_ns + NS)
    w.run(0)
    assert w.payloads("demand_stage_integrity") == []


def test_non_numeric_exit_status_of_a_killed_stage_is_demand_stage_failed() -> None:
    entries = intraday_run(inv(1), 0, exit_status=None, demand_summary=_demand(ex=0))
    entries += [exited(INTRADAY, inv(1), 30, "SEGV", "dumped"), failed(INTRADAY, inv(1), 30.1)]
    assert "demand_stage_failed" in _findings(entries)


def test_unit_failed_without_a_usable_exit_entry_is_demand_stage_failed() -> None:
    entries = intraday_run(inv(1), 0, exit_status=None, demand_summary=_demand(ex=0))
    entries.append(failed(INTRADAY, inv(1), 30.1))
    assert "demand_stage_failed" in _findings(entries)


def test_unit_failed_with_no_stage_lines_is_also_evaluate_unrecorded() -> None:
    entries = intraday_run(
        inv(1),
        0,
        eval_start=False,
        eval_summary=None,
        demand_start=False,
        demand_summary=None,
        exit_status=None,
    )
    entries.append(failed(INTRADAY, inv(1), 30.1))
    got = _findings(entries)
    assert {"demand_stage_failed", "evaluate_stage_unrecorded"} <= set(got)
