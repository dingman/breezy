"""AUT-6 WP3 S4: intraday-stage classification, episodes and the real-journal scratch unit
(plan r15 section 3.4.2).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from breezy.runtime import unit_health, unit_health_model
from breezy.runtime.unit_health import unexplained_for_day
from breezy.runtime.unit_health_daemon_support import (
    MSG_EXIT,
    MSG_FAILED,
    DaemonWiring,
    SubprocessDaemonJournal,
    UnitEntry,
)
from breezy.runtime.unit_health_intraday import (
    EVALUATE_STAGE_BUDGET_S,
    INTRADAY_INVOCATION_MAX_S,
    InvocationJudgment,
    demand_summary_counters,
    judge_invocation,
)
from breezy.runtime.unit_health_store import day_of_ns
from tests.support.unit_health_daemon_fixtures import (
    INTRADAY,
    at_us,
    exited,
    failed,
    intraday_run,
    line,
    started,
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


@pytest.fixture
def w(tmp_path: Path) -> World:
    return World(tmp_path)


# --------------------------------------------------------------------------- intraday: pure


def _findings(
    entries: Sequence[UnitEntry], *, now_s: float = 400, activating: bool = False
) -> dict[str, dict[str, str]]:
    verdict = judge_invocation(entries, now_us=at_us(now_s), current_activating=activating)
    assert verdict is not None, "the invocation was not judged"
    return {f.finding: dict(f.metrics) for f in verdict.findings}


_OK_DEMAND = (
    "PRODUCER_INTRADAY_DEMAND wrote=0 skipped_existing=0 invalid=0 "
    "integrity_demand_write_failures=0 journal_write_failures=0 outbox_write_failures=0 "
    "deadline_hit={dh} unprocessed={un} "
    "evaluate_exit={ev} exit={ex}"
)


def _demand(dh: int = 0, un: int = 0, ev: str = "0", ex: int = 0) -> str:
    return _OK_DEMAND.format(dh=dh, un=un, ev=ev, ex=ex)


@pytest.mark.parametrize(
    ("run_kwargs", "expected"),
    [
        # exit 3, summary present: the stage's own INTEGRITY cause, already paged by the stage
        ({"exit_status": 3, "demand_summary": _demand(ex=3)}, {"demand_stage_integrity": {}}),
        # exit 5, deadline_hit=1: demand_stage_deadline_hit with metrics.unprocessed
        (
            {"exit_status": 5, "demand_summary": _demand(dh=1, un=4, ex=5)},
            {"demand_stage_deadline_hit": {"unprocessed": "4"}},
        ),
        # exit 4: no demand-row finding; the evaluate rule reports the cause
        (
            {
                "exit_status": 4,
                "eval_summary": "PRODUCER_INTRADAY wrote=0 exit=1",
                "demand_summary": _demand(ev="1", ex=4),
            },
            {"evaluate_stage_failed": {"evaluate_exit": "1"}},
        ),
        # 124 (timeout SIGTERM), summary absent
        (
            {"exit_status": 124, "demand_summary": None},
            {"demand_stage_timeout": {"exit_status": "124"}},
        ),
        # any other non-zero, START and summary both absent: bwrap_unavailable
        (
            {"exit_status": 1, "demand_start": False, "demand_summary": None},
            {"bwrap_unavailable": {"cause_hint": "unknown"}},
        ),
        # START present, summary absent
        (
            {"exit_status": 1, "demand_summary": None},
            {"demand_stage_failed": {"cause_hint": "interpreter_or_import"}},
        ),
        # any other non-zero, summary present
        (
            {"exit_status": 2, "demand_summary": _demand(ex=2)},
            {"demand_stage_failed": {"exit_status": "2"}},
        ),
    ],
)
def test_intraday_stage_outcomes_classified_from_exit_status_and_demand_line(
    run_kwargs: dict[str, Any], expected: dict[str, dict[str, str]]
) -> None:
    got = _findings(intraday_run(inv(1), 0, **run_kwargs))
    assert set(got) == set(expected)
    for name, metrics in expected.items():
        for key, value in metrics.items():
            assert got[name][key] == value, (name, key, got[name])


def test_clean_intraday_invocation_has_no_finding() -> None:
    verdict = judge_invocation(intraday_run(inv(1), 0), now_us=at_us(400), current_activating=False)
    assert isinstance(verdict, InvocationJudgment) and verdict.findings == ()


def test_bwrap_launch_failure_is_critical_bwrap_unavailable(w: World) -> None:
    w.units = [show_block(INTRADAY, ActiveState="inactive", InvocationID=inv(9))]
    w.journal.add(
        intraday_run(inv(1), -300, demand_start=False, demand_summary=None, exit_status=1)
    )
    w.journal.add(
        intraday_run(
            inv(2), -100, demand_start=False, demand_summary=None, exit_status=1, bwrap_line=True
        )
    )
    w.run(0)
    pages = w.payloads("bwrap_unavailable")
    assert len(pages) == 1 and pages[0].severity == "CRITICAL"
    hints = {r["key"]: r["metrics"]["cause_hint"] for r in w.records("bwrap_unavailable")}
    assert hints == {
        f"bwrap_unavailable-{inv(1)}": "unknown",
        f"bwrap_unavailable-{inv(2)}": "bwrap_launch",
    }


@pytest.mark.parametrize("evaluate", ["exit1", "killed100", "nolines"])
@pytest.mark.parametrize("demand", ["exit0", "exit3", "exit5", "exit124", "bwrap"])
def test_evaluate_stage_failure_reported_independently_of_demand_row(
    evaluate: str, demand: str
) -> None:
    kwargs: dict[str, Any] = {}
    if evaluate == "exit1":
        kwargs["eval_summary"] = "PRODUCER_INTRADAY wrote=0 exit=1"
        ev_label = "1"
    elif evaluate == "killed100":
        kwargs.update(eval_summary=None, eval_end_s=100.5)
        ev_label = "unrecorded"
    else:
        kwargs.update(eval_summary=None, eval_start=False)
        ev_label = "unrecorded"
    if demand == "exit0":
        kwargs["demand_summary"] = _demand(ev=ev_label)
    elif demand == "exit3":
        kwargs.update(exit_status=3, demand_summary=_demand(ev=ev_label, ex=3))
    elif demand == "exit5":
        kwargs.update(exit_status=5, demand_summary=_demand(dh=1, un=1, ev=ev_label, ex=5))
    elif demand == "exit124":
        kwargs.update(exit_status=124, demand_summary=None)
    else:
        kwargs.update(exit_status=1, demand_start=False, demand_summary=None)
    got = _findings(intraday_run(inv(1), 0, **kwargs))
    want = {
        "exit1": "evaluate_stage_failed",
        "killed100": "evaluate_stage_timeout",
        "nolines": "evaluate_stage_unrecorded",
    }[evaluate]
    assert want in got, got
    if evaluate == "exit1":
        assert got[want]["evaluate_exit"] == "1"
    # in addition to the demand-row finding, never instead of it
    demand_row = {
        "exit0": None,
        "exit3": "demand_stage_integrity",
        "exit5": "demand_stage_deadline_hit",
        "exit124": "demand_stage_timeout",
        "bwrap": "bwrap_unavailable",
    }[demand]
    if demand_row is not None:
        assert demand_row in got, got
    assert set(got) <= {want, demand_row}


def test_evaluate_positive_control_exit0_with_demand_exit0_raises_none() -> None:
    assert _findings(intraday_run(inv(1), 0)) == {}


def test_demand_line_disagreeing_with_a_clean_evaluate_summary_is_unrecorded() -> None:
    got = _findings(intraday_run(inv(1), 0, demand_summary=_demand(ev="unrecorded")))
    assert "evaluate_stage_unrecorded" in got
    got = _findings(intraday_run(inv(1), 0, eval_summary=None, demand_summary=_demand(ev="1")))
    assert "evaluate_stage_unrecorded" in got


def test_skipped_lock_held_counts_as_an_evaluate_summary_with_exit_zero() -> None:
    entries = intraday_run(inv(1), 0, eval_summary="PRODUCER_INTRADAY SKIPPED lock_held")
    assert _findings(entries) == {}


def test_evaluate_timeout_needs_the_full_budget_between_start_and_demand_start() -> None:
    short = intraday_run(inv(1), 0, eval_summary=None, eval_end_s=EVALUATE_STAGE_BUDGET_S - 1)
    assert "evaluate_stage_unrecorded" in _findings(short)
    long = intraday_run(inv(1), 0, eval_summary=None, eval_end_s=EVALUATE_STAGE_BUDGET_S)
    assert "evaluate_stage_timeout" in _findings(long)


def test_demand_stage_cause_hint_separates_bwrap_launch_from_import_crash() -> None:
    plain: dict[str, Any] = {"demand_start": False, "demand_summary": None, "exit_status": 1}
    assert (
        _findings(intraday_run(inv(1), 0, **plain))["bwrap_unavailable"]["cause_hint"] == "unknown"
    )
    with_line = _findings(intraday_run(inv(1), 0, bwrap_line=True, **plain))
    assert with_line["bwrap_unavailable"]["cause_hint"] == "bwrap_launch"
    crash = _findings(intraday_run(inv(1), 0, demand_summary=None, exit_status=1))
    assert crash["demand_stage_failed"]["cause_hint"] == "interpreter_or_import"
    # the evaluate-stage case: no evaluate START and a journaled bwrap: line
    ev = _findings(intraday_run(inv(1), 0, eval_start=False, eval_summary=None, bwrap_line=True))
    assert ev["evaluate_stage_unrecorded"]["cause_hint"] == "bwrap_launch"
    ev_plain = _findings(intraday_run(inv(1), 0, eval_start=False, eval_summary=None))
    assert "cause_hint" not in ev_plain["evaluate_stage_unrecorded"]


def test_intraday_exit_status_read_from_latest_exit_entry_by_timestamp() -> None:
    entries = intraday_run(inv(1), 0, exit_status=None, demand_summary=_demand(ex=3))
    entries += [
        exited(INTRADAY, inv(1), 30, "3"),
        exited(INTRADAY, inv(1), 25, "1"),
    ]  # out of order
    entries.append(failed(INTRADAY, inv(1), 30.1))
    got = _findings(entries)
    assert "demand_stage_integrity" in got and "demand_stage_failed" not in got
    assert got["demand_stage_integrity"]["exit_entries"] == "2"


def test_intraday_exit_entry_selected_by_command_execstart() -> None:
    entries = intraday_run(inv(1), 0, exit_status=None, demand_summary=_demand(ex=3))
    entries += [
        exited(INTRADAY, inv(1), 40, "7", command="ExecStartPre"),
        exited(INTRADAY, inv(1), 30, "3", command="ExecStart"),
        exited(INTRADAY, inv(1), 41, "9", command="ExecStartPost"),
        failed(INTRADAY, inv(1), 41.1),
    ]
    got = _findings(entries)
    assert set(got) == {"demand_stage_integrity"}
    assert "exit_entries" not in got["demand_stage_integrity"]  # one ExecStart entry: no note


@pytest.mark.parametrize(
    "ender", ["exit_entry", "unit_failed", "job_completion", "age", "not_activating"]
)
def test_intraday_invocation_ended_by_exit_entry_age_or_not_activating(ender: str) -> None:
    # an invocation with START lines only: judged (evaluate unrecorded) iff one of (a)-(c) holds
    base = intraday_run(
        inv(1), 0, eval_summary=None, demand_start=False, demand_summary=None, finish=False
    )
    now_s, activating = 30.0, True
    if ender == "exit_entry":
        base.append(exited(INTRADAY, inv(1), 29, "0"))
    elif ender == "unit_failed":
        base.append(failed(INTRADAY, inv(1), 29))
    elif ender == "job_completion":
        base.append(started(INTRADAY, inv(1), 29))
    elif ender == "age":
        now_s = 0.5 + INTRADAY_INVOCATION_MAX_S + 1
    else:
        activating = False
    verdict = judge_invocation(base, now_us=at_us(now_s), current_activating=activating)
    assert verdict is not None and verdict.findings


def test_intraday_in_flight_invocation_is_not_judged() -> None:
    base = intraday_run(
        inv(1), 0, eval_summary=None, demand_start=False, demand_summary=None, finish=False
    )
    assert judge_invocation(base, now_us=at_us(30), current_activating=True) is None
    assert judge_invocation([], now_us=at_us(30), current_activating=False) is None


def test_alert_delivery_keys_on_producer_intraday_demand_line_and_record() -> None:
    entries = intraday_run(
        inv(1),
        0,
        demand_summary=(
            "PRODUCER_INTRADAY_DEMAND wrote=2 skipped_existing=1 invalid=0 "
            "integrity_demand_write_failures=2 journal_write_failures=3 outbox_write_failures=4 "
            "deadline_hit=0 unprocessed=0 evaluate_exit=0 exit=0"
        ),
    )
    assert demand_summary_counters(entries) == {
        "integrity_demand_write_failures": 2,
        "journal_write_failures": 3,
        "outbox_write_failures": 4,
    }
    assert demand_summary_counters(intraday_run(inv(1), 0, demand_summary=None)) is None
    # the evaluate summary line is not the demand line
    assert (
        demand_summary_counters([line(INTRADAY, inv(1), 1, "PRODUCER_INTRADAY wrote=0 exit=0")])
        is None
    )


# --------------------------------------------------------------------------- intraday: the pass


def _intraday_world(w: World, current: int = 9, state: str = "inactive") -> None:
    w.units = [show_block(INTRADAY, ActiveState=state, InvocationID=inv(current))]


def test_production_yields_no_finding_without_an_intraday_unit(w: World) -> None:
    w.units = [show_block("breezy-portfolio-roi.service")]
    w.journal.add(
        intraday_run(inv(1), -300, demand_start=False, demand_summary=None, exit_status=1)
    )
    result = w.run(0)
    assert result.pass_result in {"OK", "FINDINGS"}
    assert w.events == []
    assert ("unit_entries", INTRADAY) not in w.journal.calls
    assert unit_health_model.WATCHDOG_DAEMON_UNITS == frozenset()  # filled by WP4


def test_production_env_wires_the_real_daemon_journal() -> None:
    env = unit_health.production_env(environ={}, data_root=Path("/nonexistent-aut6-s4"))
    assert isinstance(env.daemons, DaemonWiring)
    assert isinstance(env.daemons.journal, SubprocessDaemonJournal)


def test_overlapping_health_pass_does_not_page_in_flight_intraday_invocation(w: World) -> None:
    _intraday_world(w)
    w.journal.add(intraday_run(inv(9), -100))  # the unit's placeholder invocation ran clean
    w.run(0)
    # the :00:01 run is still activating at the :01 pass: START line, no summary
    partial = intraday_run(
        inv(1), 1, eval_summary=None, demand_start=False, demand_summary=None, finish=False
    )
    w.journal.add(partial)
    _intraday_world(w, current=1, state="activating")
    w.run(60)
    assert w.events == []
    assert list(w.store.root.glob("*/*__class.json")) == []
    # the run ends failing; the :11 pass judges it once
    w.journal.entries = [e for e in w.journal.entries if e.invocation_id != inv(1)]
    w.journal.add(intraday_run(inv(1), 1, exit_status=3, demand_summary=_demand(ex=3)))
    _intraday_world(w, current=2, state="inactive")
    w.run(540)
    assert len(w.records("demand_stage_integrity")) == 1
    w.run(600)
    assert len(w.records("demand_stage_integrity")) == 1


def test_demand_stage_deadline_hit_is_critical_22_finding(w: World) -> None:
    _intraday_world(w)
    w.journal.add(
        intraday_run(inv(1), -200, exit_status=5, demand_summary=_demand(dh=1, un=3, ex=5))
    )
    w.run(0)
    pages = w.payloads("demand_stage_deadline_hit")
    assert len(pages) == 1 and pages[0].severity == "CRITICAL"
    assert w.records("demand_stage_deadline_hit")[0]["metrics"]["unprocessed"] == "3"


def test_integrity_exit_3_is_recorded_but_not_paged_again_by_the_health_pass(w: World) -> None:
    _intraday_world(w)
    w.journal.add(intraday_run(inv(1), -200, exit_status=3, demand_summary=_demand(ex=3)))
    _outbox_entry(w, "bwrap_self_probe_failed", at_us(-190) * 1000)  # the stage's own page
    w.run(0)
    assert w.payloads("demand_stage_integrity") == []  # the stage already paged its own cause
    assert len(w.records("demand_stage_integrity")) == 1
    day = day_of_ns(w.h.clock.now_ns)
    assert unexplained_for_day(w.store, day, w.h.env.delivered) == ()


def _outbox_entry(w: World, event: str, ts_ns: int) -> None:
    directory = w.alerts_root / "outbox"
    directory.mkdir(parents=True, exist_ok=True)
    body = {"schema": "alert_outbox/v1", "ts_ns": ts_ns, "event": event, "site": "x"}
    (directory / f"{ts_ns}_{event}.json").write_text(json.dumps(body))


EPISODE_RUNS: dict[str, dict[str, Any]] = {
    "bwrap_unavailable": {"demand_start": False, "demand_summary": None, "exit_status": 1},
    "demand_stage_timeout": {"demand_summary": None, "exit_status": 124},
    "demand_stage_deadline_hit": {"exit_status": 5, "demand_summary": _demand(dh=1, un=2, ex=5)},
}


@pytest.mark.parametrize("finding", sorted(EPISODE_RUNS))
def test_bwrap_unavailable_and_demand_stage_timeout_paged_once_per_episode_repaged_24h(
    w: World, finding: str
) -> None:
    run = EPISODE_RUNS[finding]
    _intraday_world(w)
    w.journal.add(intraday_run(inv(1), -500, **run), intraday_run(inv(2), -200, **run))
    w.run(0)
    assert len(w.payloads(finding)) == 1  # one page for the first invocation of the episode
    first = w.payloads(finding)[0]
    # the later invocation has a classification record and an action citing the delivered page
    assert len(w.records(finding)) == 2
    action = w.store.read_action(INTRADAY, f"{finding}-{inv(2)}")
    assert action is not None and (action["event"], action["site"]) == (first.event, first.site)
    w.deliver_all()
    # a third failure the same day: still the same episode, no page
    w.journal.add(intraday_run(inv(3), 300, **run))
    w.run(600)
    assert len(w.payloads(finding)) == 1
    # 24 h after the page the episode re-pages
    w.journal.add(intraday_run(inv(4), 600 + DAY_S + 100, **run))
    w.run(DAY_S + 300)
    assert len(w.payloads(finding)) == 2


def test_episode_last_paged_ns_set_only_on_delivered(w: World) -> None:
    run = EPISODE_RUNS["bwrap_unavailable"]
    _intraday_world(w)
    w.journal.add(intraday_run(inv(1), -200, **run))
    w.run(0)
    path = w.store.root / "seen" / "_intraday_episode_bwrap_unavailable.json"
    episode = json.loads(path.read_text())
    assert episode["last_paged_ns"] is None and episode["first_ns"] == at_us(-200) * 1000
    # undelivered: the next invocation in the episode pages again (the outbox retries the first)
    w.journal.add(intraday_run(inv(2), 100, **run))
    w.run(600)
    assert len(w.payloads("bwrap_unavailable")) == 2
    w.deliver_all()
    w.journal.add(intraday_run(inv(3), 700, **run))
    w.run(600)
    assert len(w.payloads("bwrap_unavailable")) == 2
    assert json.loads(path.read_text())["last_paged_ns"] is not None


def test_episode_ends_only_on_a_judged_ended_invocation(w: World) -> None:
    bad = EPISODE_RUNS["bwrap_unavailable"]
    path = w.store.root / "seen" / "_intraday_episode_bwrap_unavailable.json"
    _intraday_world(w)
    w.journal.add(intraday_run(inv(1), -200, **bad))
    w.run(0)
    w.deliver_all()
    assert json.loads(path.read_text())["state"] == "active"
    # a clean invocation still activating at the pass does not end the episode
    w.journal.add(
        intraday_run(
            inv(2), 380, eval_summary=None, demand_start=False, demand_summary=None, finish=False
        )
    )
    _intraday_world(w, current=2, state="activating")
    w.run(400)
    assert json.loads(path.read_text())["state"] == "active"
    # judged ended at the next pass (it finished clean) it does
    w.journal.entries = [e for e in w.journal.entries if e.invocation_id != inv(2)]
    w.journal.add(intraday_run(inv(2), 380))
    _intraday_world(w, current=3, state="inactive")
    w.run(600)
    assert json.loads(path.read_text())["state"] == "ended"
    w.journal.add(intraday_run(inv(4), 1500, **bad))
    w.run(600)
    assert len(w.payloads("bwrap_unavailable")) == 2  # a new episode pages at once


def test_a_failing_invocation_between_keeps_one_episode_and_one_page(w: World) -> None:
    bad = EPISODE_RUNS["bwrap_unavailable"]
    _intraday_world(w)
    w.journal.add(intraday_run(inv(1), -300, **bad), intraday_run(inv(2), -100, **bad))
    w.run(0)
    w.deliver_all()
    w.journal.add(intraday_run(inv(3), 200, **bad))
    w.run(600)
    assert len(w.payloads("bwrap_unavailable")) == 1


def test_unreadable_episode_file_pages(w: World) -> None:
    run = EPISODE_RUNS["bwrap_unavailable"]
    _intraday_world(w)
    path = w.store.root / "seen" / "_intraday_episode_bwrap_unavailable.json"
    path.parent.mkdir(parents=True)
    path.write_text("{ not json")
    w.journal.add(intraday_run(inv(1), -200, **run))
    w.run(0)
    assert len(w.payloads("bwrap_unavailable")) == 1


# --------------------------------------------------------------------------- stage episode record


def _action_site(w: World, finding: str, n: int) -> str:
    action = w.store.read_action(INTRADAY, f"{finding}-{inv(n)}")
    assert action is not None
    return str(action["site"])


def _stage_record(w: World, body: dict[str, Any] | str) -> Path:
    path = w.alerts_root / "episodes" / "demand_stage_deadline_hit.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body if isinstance(body, str) else json.dumps(body))
    return path


def _delivery_record(
    w: World,
    *,
    ts_ns: int,
    entry: str,
    delivered: bool = True,
    event: str = "demand_stage_deadline_hit",
) -> dict[str, Any]:
    body = {
        "event": event,
        "ts_ns": ts_ns,
        "delivered": delivered,
        "status_class": "2xx",
        "severity": "CRITICAL",
        "attempt_kind": "alert",
        "drill": False,
        "schema": "alert_delivery/v1",
        "site": "demand_stage:deadline",
        "outbox_entry": entry,
    }
    directory = w.alerts_root / day_of_ns(ts_ns)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{ts_ns}_redeliver_{'d' if delivered else 'f'}.json").write_text(json.dumps(body))
    if delivered:
        w.h.delivered.add((str(body["event"]), str(body["site"])))
    return body


HIT_RUN = EPISODE_RUNS["demand_stage_deadline_hit"]
ENTRY = "1791460700000000000_demand_stage_deadline_hit.json"


def _stage_queued(w: World, queued_ns: int) -> None:
    _stage_record(
        w,
        {
            "schema": "demand_stage_episode/v1",
            "first_ns": queued_ns,
            "last_queued_ns": queued_ns,
            "outbox_entry": ENTRY,
            "invocation_id": inv(1),
        },
    )


def test_stage_page_recorded_and_bound_to_episode_without_double_page(w: World) -> None:
    _intraday_world(w)
    hit_ns = (at_us(-200) + 5_000_000) * 1000
    w.journal.add(intraday_run(inv(1), -200, **HIT_RUN))
    _stage_queued(w, hit_ns)
    # while the entry is undelivered the episode is alert_pending: the health pass does not page
    w.run(0)
    assert w.payloads("demand_stage_deadline_hit") == []
    assert w.records("demand_stage_deadline_hit") == []
    # redeliver drains the entry and writes one delivered record
    _delivery_record(w, ts_ns=hit_ns + 120 * NS, entry=ENTRY)
    w.run(600)
    assert w.payloads("demand_stage_deadline_hit") == []  # exactly one page across both writers
    assert len(w.records("demand_stage_deadline_hit")) == 1
    action = w.store.read_action(INTRADAY, f"demand_stage_deadline_hit-{inv(1)}")
    assert action is not None and action["site"] == "demand_stage:deadline"
    episode = json.loads(
        (w.store.root / "seen" / "_intraday_episode_demand_stage_deadline_hit.json").read_text()
    )
    assert episode["last_paged_ns"] == hit_ns + 120 * NS
    day = day_of_ns(w.h.clock.now_ns)
    assert not [n for n in unexplained_for_day(w.store, day, w.h.env.delivered) if "deadline" in n]


def test_unreadable_stage_record_pages_again(w: World) -> None:
    _intraday_world(w)
    w.journal.add(intraday_run(inv(1), -200, **HIT_RUN))
    _stage_record(w, "{ garbage")
    w.run(0)
    assert len(w.payloads("demand_stage_deadline_hit")) == 1


def test_stage_delivery_record_binds_only_at_or_after_episode_first_ns_and_resets_on_clean_pass(
    w: World,
) -> None:
    first_ns = at_us(-200) * 1000  # the episode's first_ns: the invocation's first journal entry

    # (a) a delivered record older than first_ns is not bound: the episode pages
    _intraday_world(w)
    w.journal.add(intraday_run(inv(1), -200, **HIT_RUN))
    _stage_queued(w, first_ns - 3600 * NS)  # the stage's record still names an earlier episode
    _delivery_record(w, ts_ns=first_ns - 1, entry=ENTRY)
    w.run(0)
    assert len(w.payloads("demand_stage_deadline_hit")) == 1
    assert _action_site(w, "demand_stage_deadline_hit", 1) != "demand_stage:deadline"


def test_stage_delivery_record_at_first_ns_is_bound(w: World) -> None:
    first_ns = at_us(-200) * 1000
    _intraday_world(w)
    w.journal.add(intraday_run(inv(1), -200, **HIT_RUN))
    _stage_queued(w, first_ns + 5 * NS)
    _delivery_record(w, ts_ns=first_ns, entry=ENTRY)
    w.run(0)
    assert w.payloads("demand_stage_deadline_hit") == []
    assert _action_site(w, "demand_stage_deadline_hit", 1) == "demand_stage:deadline"


def test_stage_reset_record_does_not_bind_and_the_next_hit_pages(w: World) -> None:
    first_ns = at_us(-200) * 1000
    _intraday_world(w)
    w.journal.add(intraday_run(inv(1), -200, **HIT_RUN))
    _stage_record(
        w, {"schema": "demand_stage_episode/v1", "state": "reset", "reset_ns": first_ns - NS}
    )
    _delivery_record(w, ts_ns=first_ns + NS, entry=ENTRY)
    w.run(0)
    assert len(w.payloads("demand_stage_deadline_hit")) == 1


# --------------------------------------------------------------------------- real journal


def _user_manager_usable() -> bool:
    systemd_run = shutil.which("systemd-run")
    if systemd_run is None:
        return False
    probe = subprocess.run(
        ["/usr/bin/systemctl", "--user", "show", "-p", "Version", "--value"],
        capture_output=True,
        timeout=10,
        check=False,
    )
    return probe.returncode == 0


def test_intraday_exit_entries_on_real_journal_scratch_unit() -> None:
    """The production two-line shape on the real journal (LOW-r11-7).

    A scratch user unit ``claude-aut6-*`` (never a ``breezy-*`` unit) runs an ignored
    ``ExecStart=-`` line that exits 1 and a second line that exits 3. The journal must hold
    exactly one ``98e32220...`` entry for the invocation, ``COMMAND=ExecStart``, ``EXIT_STATUS=3``.
    """
    if not _user_manager_usable():
        pytest.skip("no usable systemd --user manager in this environment")
    name = f"claude-aut6-{uuid.uuid4().hex[:8]}"
    unit = f"{name}.service"
    began = int(time.time()) - 2
    first = (
        "echo 'PRODUCER_INTRADAY START ts_ns=1'; echo 'PRODUCER_INTRADAY wrote=0 exit=0'; exit 1"
    )
    second = "echo 'PRODUCER_INTRADAY_DEMAND START'; echo '" + _demand(ex=3) + "'; exit 3"
    try:
        try:
            run = subprocess.run(
                [
                    "/usr/bin/systemd-run",
                    "--user",
                    f"--unit={name}",
                    "--wait",
                    "--collect",
                    "-p",
                    "Type=oneshot",
                    "-p",
                    f'ExecStart=-/bin/sh -c "{first}"',
                    "/bin/sh",
                    "-c",
                    second,
                ],
                capture_output=True,
                timeout=60,
                check=False,
            )
        except subprocess.TimeoutExpired:
            pytest.fail(f"scratch unit {name} did not finish in 60 s")
        if b"Failed to connect" in run.stderr:
            pytest.skip("systemd-run could not reach the user bus")
        journal = SubprocessDaemonJournal()
        deadline = time.monotonic() + 10
        entries: tuple[UnitEntry, ...] = ()
        while time.monotonic() < deadline:
            seen = journal.unit_entries(
                unit,
                since_us=began * 1_000_000,
                until_us=(int(time.time()) + 5) * 1_000_000,
                lifecycle_only=True,
                timeout_s=10,
            )
            ids = {e.invocation_id for e in seen if e.message_id == MSG_EXIT}
            if ids:
                (invocation,) = ids
                entries = journal.invocation_entries(
                    unit, invocation, lifecycle_only=False, timeout_s=10
                )
                if any(e.message_id == MSG_FAILED for e in entries) and any(
                    "PRODUCER_INTRADAY_DEMAND wrote" in e.message for e in entries
                ):
                    break
            time.sleep(0.5)
        exits = [e for e in entries if e.message_id == MSG_EXIT]
        assert len(exits) == 1
        assert exits[0].fields["COMMAND"] == "ExecStart" and exits[0].fields["EXIT_STATUS"] == "3"
        verdict = judge_invocation(
            entries, now_us=int(time.time() * 1_000_000), current_activating=False
        )
        assert verdict is not None
        assert {f.finding for f in verdict.findings} == {"demand_stage_integrity"}
    finally:
        _cleanup_scratch(unit)


def _cleanup_scratch(unit: str) -> None:
    """Stop and reset a scratch unit; only ever a ``claude-aut6-*`` unit, never a ``breezy-*``."""
    assert unit.startswith("claude-aut6-")
    for verb in ("stop", "reset-failed"):
        try:
            subprocess.run(
                ["/usr/bin/systemctl", "--user", verb, unit],
                capture_output=True,
                timeout=10,
                check=False,
            )
        except subprocess.TimeoutExpired:
            continue  # best effort: the unit was started with --collect
