"""AUT-6 WP9: the live-proof report (plan r15 section 6, section 7 (f), WP9; X-7; R-22).

The evaluator is pure: it reads a ``ProofInputs`` of already-parsed evidence and returns the
report. Every test builds a healthy fixture and changes the one thing under test.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from typing import Any, Final

from breezy.analysis.aut6_live_proof_report import (
    DeliveryFact,
    FillFact,
    ProofInputs,
    RestartFact,
    VetoFact,
    evaluate_live_proof,
)

NS: Final = 1_000_000_000
RULING: Final = dt.date(2026, 10, 20)
FIRST: Final = dt.date(2026, 10, 21)
ASOF: Final = dt.date(2026, 11, 2)  # complete days 10-21 .. 11-01 (12 days)
RECORDER: Final = "breezy-quote-tape.service"


def _ns(day: dt.date, hour: int = 12, second: int = 0) -> int:
    start = dt.datetime(day.year, day.month, day.day, tzinfo=dt.UTC)
    return int((start + dt.timedelta(hours=hour, seconds=second)).timestamp()) * NS


def _rollup(day: dt.date, **over: Any) -> dict[str, Any]:
    end_ns = _ns(day + dt.timedelta(days=1), 0)
    body: dict[str, Any] = {
        "schema": "unit_health_day/v1",
        "day": day.isoformat(),
        "passes_completed": 143,
        "passes_unknown": 1,
        "max_passes_unknown_streak": 1,
        "unexplained_failed_units": {"count": 0, "names": []},
        "produced_at_ns": end_ns - 300 * NS,
    }
    body.update(over)
    return body


def _days(first: dt.date, last: dt.date) -> list[dt.date]:
    return [first + dt.timedelta(days=i) for i in range((last - first).days + 1)]


def _fill(day: dt.date, source: str = "live", drill: bool = False, n: int = 0) -> FillFact:
    return FillFact(day=day.isoformat(), source=source, drill=drill, ref=f"{day}/fill{n}")


def _canary(day: dt.date, **over: Any) -> DeliveryFact:
    body = {
        "schema": "alert_delivery/v1",
        "attempt_kind": "canary",
        "delivered": True,
        "drill": False,
        "event": "autonomy_canary",
        "severity": "INFO",
        "site": "global",
        "ts_ns": _ns(day, 15),
    }
    body.update(over)
    return DeliveryFact(day=day.isoformat(), name=f"{body['ts_ns']}_canary_d.json", body=body)


def _build(**over: Any) -> ProofInputs:
    days = _days(FIRST, ASOF - dt.timedelta(days=1))
    base: dict[str, Any] = {
        "asof": ASOF.isoformat(),
        "aut5b_ruling_date": RULING.isoformat(),
        "ing2_amend2_landed_date": RULING.isoformat(),
        "rollups": {d.isoformat(): _rollup(d) for d in days},
        "fills": tuple(_fill(d, n=i) for d in days for i in range(1)),
        "deliveries": tuple(_canary(d) for d in days),
    }
    base.update(over)
    return ProofInputs(**base)


def _report(**over: Any) -> Mapping[str, Any]:
    return evaluate_live_proof(_build(**over))


# -- the window ---------------------------------------------------------------------------------


def test_zero_fill_day_extends_window() -> None:
    days = _days(FIRST, ASOF - dt.timedelta(days=1))
    no_fill_day = days[3]
    fills = tuple(_fill(d) for d in days if d != no_fill_day for _ in range(1))
    report = _report(fills=fills)
    window = report["window"]
    assert no_fill_day.isoformat() in window["neutral_days"]
    assert no_fill_day.isoformat() not in window["days"]
    assert window["breaks"] == []
    assert window["day_count"] == len(days) - 1  # the empty day neither counts nor breaks
    # exactly 7 qualifying days still needs the 7th: with 7 days of which one is empty, not met
    seven = days[:7]
    short = _report(
        asof=(seven[-1] + dt.timedelta(days=1)).isoformat(),
        rollups={d.isoformat(): _rollup(d) for d in seven},
        fills=tuple(_fill(d) for d in seven if d != seven[2]),
        deliveries=tuple(_canary(d) for d in seven),
    )
    assert short["window"]["day_count"] == 6
    assert short["window"]["criteria"]["qualifying_days"] is False


def test_window_requires_5_real_fills_canary_and_drill_excluded() -> None:
    days = _days(FIRST, FIRST + dt.timedelta(days=6))
    asof = (days[-1] + dt.timedelta(days=1)).isoformat()
    rollups = {d.isoformat(): _rollup(d) for d in days}
    deliveries = tuple(_canary(d) for d in days)

    def run(fills: tuple[FillFact, ...]) -> Mapping[str, Any]:
        return _report(asof=asof, rollups=rollups, deliveries=deliveries, fills=fills)

    # one fill a day qualifies every day, but 4 real + 3 canary/drill fills is not 5 real
    mixed = (
        _fill(days[0]),
        _fill(days[1]),
        _fill(days[2]),
        _fill(days[3]),
        _fill(days[4], source="canary"),
        _fill(days[5], drill=True),
        _fill(days[6], source="canary"),
    )
    four = run(mixed)
    assert four["window"]["day_count"] == 7
    assert four["window"]["real_fills"] == 4
    assert four["window"]["criteria"]["real_fills"] is False
    five = run((*mixed, _fill(days[6], n=9)))
    assert five["window"]["real_fills"] == 5
    assert five["window"]["criteria"]["real_fills"] is True
    assert five["window"]["criteria"]["qualifying_days"] is True


def test_window_starts_after_aut5b_ruling_date() -> None:
    late_ruling = FIRST + dt.timedelta(days=4)  # days up to and including it never count
    report = _report(aut5b_ruling_date=late_ruling.isoformat())
    assert report["window"]["days"][0] == (late_ruling + dt.timedelta(days=1)).isoformat()
    assert FIRST.isoformat() not in report["window"]["days"]
    assert late_ruling.isoformat() not in report["window"]["days"]
    unfiled = _report(aut5b_ruling_date=None)
    assert unfiled["window"]["days"] == []
    assert "aut5b_ruling_not_filed" in unfiled["blockers"]
    assert unfiled["verdict"] == "NOT_YET"


def test_missing_or_stale_rollup_fails_the_day() -> None:
    days = _days(FIRST, ASOF - dt.timedelta(days=1))
    missing = days[4]
    rollups = {d.isoformat(): _rollup(d) for d in days if d != missing}
    gone = _report(rollups=rollups)["window"]
    assert [b["day"] for b in gone["breaks"]] == [missing.isoformat()]
    assert gone["breaks"][0]["reasons"] == ["rollup_missing"]
    assert gone["days"][0] == (missing + dt.timedelta(days=1)).isoformat()  # the run restarts

    stale = days[2]
    early = _ns(stale, 12)  # produced mid-day: before the day ended
    rollups = {d.isoformat(): _rollup(d) for d in days}
    rollups[stale.isoformat()] = _rollup(stale, produced_at_ns=early)
    boundary = _rollup(stale, produced_at_ns=_ns(stale + dt.timedelta(days=1), 0) - 601 * NS)
    rollups[stale.isoformat()] = boundary
    assert _report(rollups=rollups)["window"]["breaks"][0]["reasons"] == ["rollup_stale"]
    fine = _rollup(stale, produced_at_ns=_ns(stale + dt.timedelta(days=1), 0) - 600 * NS)
    rollups[stale.isoformat()] = fine
    assert _report(rollups=rollups)["window"]["breaks"] == []
    rollups[stale.isoformat()] = _rollup(stale, produced_at_ns=early)
    old = _report(rollups=rollups)["window"]
    assert old["breaks"][0]["day"] == stale.isoformat()
    assert old["breaks"][0]["reasons"] == ["rollup_stale"]


def test_day_with_passes_unknown_over_threshold_fails() -> None:
    days = _days(FIRST, ASOF - dt.timedelta(days=1))
    bad = days[1]
    cases: dict[str, dict[str, Any]] = {
        "passes_completed_below_130": {"passes_completed": 129},
        "passes_unknown_above_6": {"passes_unknown": 7},
        "unexplained_failed_units": {"unexplained_failed_units": {"count": 1, "names": ["x"]}},
        "rollup_malformed": {"passes_unknown": "3"},
    }
    for reason, change in cases.items():
        rollups = {d.isoformat(): _rollup(d) for d in days}
        rollups[bad.isoformat()] = _rollup(bad, **change)
        breaks = _report(rollups=rollups)["window"]["breaks"]
        assert [(b["day"], reason in b["reasons"]) for b in breaks] == [(bad.isoformat(), True)]
    # positive controls: the thresholds themselves pass
    rollups = {d.isoformat(): _rollup(d) for d in days}
    rollups[bad.isoformat()] = _rollup(bad, passes_completed=130, passes_unknown=6)
    assert _report(rollups=rollups)["window"]["breaks"] == []


def test_day_with_unknown_streak_ge_3_needs_delivered_page() -> None:
    days = _days(FIRST, ASOF - dt.timedelta(days=1))
    bad = days[1]
    rollups = {d.isoformat(): _rollup(d) for d in days}
    rollups[bad.isoformat()] = _rollup(bad, max_passes_unknown_streak=3)
    assert _report(rollups=rollups)["window"]["breaks"][0]["reasons"] == [
        "unknown_streak_without_delivered_page"
    ]
    page = DeliveryFact(
        day=bad.isoformat(),
        name="1_health_d.json",
        body={
            "schema": "alert_delivery/v1",
            "delivered": True,
            "severity": "CRITICAL",
            "event": "detector_alert",
            "site": "aut6.health_monitor_stale:_host",
            "attempt_kind": "alert",
            "drill": False,
            "ts_ns": _ns(bad, 9),
        },
    )
    deliveries = (*(_canary(d) for d in days), page)
    assert _report(rollups=rollups, deliveries=deliveries)["window"]["breaks"] == []
    undelivered = DeliveryFact(
        bad.isoformat(), "2_health_d.json", {**page.body, "delivered": False}
    )
    warn = DeliveryFact(bad.isoformat(), "3_health_d.json", {**page.body, "severity": "WARN"})
    for fact in (undelivered, warn):
        report = _report(rollups=rollups, deliveries=(*(_canary(d) for d in days), fact))
        assert report["window"]["breaks"][0]["day"] == bad.isoformat()


def test_frame_gap_inconclusive_days_are_listed_for_review() -> None:
    report = _report(frame_gap_days=(("2026-10-25", 2), ("2026-10-27", 1)))
    assert report["frame_gap_review"] == [
        {"day": "2026-10-25", "fills": 2},
        {"day": "2026-10-27", "fills": 1},
    ]
    assert _report()["frame_gap_review"] == []


# -- the action classes -------------------------------------------------------------------------


def _permit(day: dt.date) -> tuple[int, VetoFact]:
    expiry = _ns(day, 2, 50 * 60 + 40)
    return expiry, VetoFact(ts_ns=expiry + 40 * NS, reason="permit_lapsed", ref="node.log:41")


def test_permit_lapsed_event_matched_to_expires_at_ns() -> None:
    expiry, veto = _permit(FIRST + dt.timedelta(days=1))
    ok = _report(permit_expiries_ns=(expiry,), entry_vetos=(veto,))
    assert ok["classes"]["ENTRY_VETO"]["satisfied"] is True
    for ts in (expiry + 121 * NS, expiry - 1 * NS):
        late = VetoFact(ts_ns=ts, reason="permit_lapsed", ref="node.log:42")
        report = _report(permit_expiries_ns=(expiry,), entry_vetos=(late,))
        assert report["classes"]["ENTRY_VETO"]["satisfied"] is False
    edge = VetoFact(ts_ns=expiry + 120 * NS, reason="permit_lapsed", ref="node.log:43")
    assert _report(permit_expiries_ns=(expiry,), entry_vetos=(edge,))["classes"]["ENTRY_VETO"][
        "satisfied"
    ]
    other = VetoFact(ts_ns=expiry + 5 * NS, reason="feed_stale", ref="node.log:44")
    assert not _report(permit_expiries_ns=(expiry,), entry_vetos=(other,))["classes"]["ENTRY_VETO"][
        "satisfied"
    ]
    assert not _report(permit_expiries_ns=(), entry_vetos=(veto,))["classes"]["ENTRY_VETO"][
        "satisfied"
    ]


def _restart(**over: Any) -> RestartFact:
    base: dict[str, Any] = {
        "unit": RECORDER,
        "invocation_id": "a" * 32,
        "unit_result": "watchdog",
        "injected": False,
        "verdict_id": "b" * 64,
        "notifier_delivered": True,
        "fallback_page_delivered": False,
        "ts_ns": _ns(FIRST + dt.timedelta(days=2)),
    }
    base.update(over)
    return RestartFact(**base)


def _row(kind: str, **over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "kind": kind,
        "decided_by": "engine",
        "drill": True,
        "halt_cause_class": "DRILL" if kind == "HALT" else None,
        "trigger_cause_class": "DRILL",
        "cause_verdict_ids": ["c" * 64],
        "ts_ns": _ns(FIRST + dt.timedelta(days=3)),
        "transition_id": "d" * 64,
        "family_id": "fam",
    }
    base.update(over)
    return base


def _verdict(detector: str, vid: str = "c" * 64) -> dict[str, Any]:
    return {"verdict_id": vid, "detector": detector, "outcome": "FAIL", "kind": "DRIFT"}


def _node_veto(reason: str, after_ns: int) -> VetoFact:
    return VetoFact(ts_ns=after_ns + 2 * NS, reason=reason, ref="node.log:900")


def test_each_action_class_needs_a_live_path_event() -> None:
    empty = _report(deliveries=())
    assert {k: v["satisfied"] for k, v in empty["classes"].items()} == {
        "ENTRY_VETO": False,
        "ALERT": False,
        "SELF_HEAL": False,
        "DEMOTE": False,
        "HALT": False,
    }
    assert empty["verdict"] == "NOT_YET"
    expiry, veto = _permit(FIRST + dt.timedelta(days=1))
    demote, halt = _row("DEMOTE"), _row("HALT", cause_verdict_ids=["e" * 64])
    full = _report(
        permit_expiries_ns=(expiry,),
        entry_vetos=(veto,),
        restarts=(_restart(),),
        transitions=(demote, halt),
        verdicts={
            "c" * 64: _verdict("DRILL_INJECT"),
            "e" * 64: _verdict("DRILL_INJECT_HALT", "e" * 64),
        },
        node_log_vetos=(
            _node_veto("registry_not_champion", demote["ts_ns"]),
            _node_veto("registry_halted", halt["ts_ns"]),
        ),
        new_exec_store_halt_keys=0,
    )
    assert all(v["satisfied"] for v in full["classes"].values()), full["classes"]
    assert full["verdict"] == "PROVEN"
    assert full["evidence_class"] == "machinery proven, edge unproven"
    assert full["blockers"] == []
    one_less = _report(
        permit_expiries_ns=(expiry,),
        entry_vetos=(veto,),
        restarts=(_restart(),),
        transitions=(demote,),
        verdicts={"c" * 64: _verdict("DRILL_INJECT")},
        node_log_vetos=(_node_veto("registry_not_champion", demote["ts_ns"]),),
    )
    assert one_less["verdict"] == "NOT_YET"
    assert "action_class_unproven:HALT" in one_less["blockers"]


def test_halt_class_satisfied_by_drill_inject_halt_row_only() -> None:
    def halt_report(**over: Any) -> Mapping[str, Any]:
        row = over.pop("row", _row("HALT"))
        verdict = over.pop("verdict", _verdict("DRILL_INJECT_HALT"))
        veto = over.pop("veto", _node_veto("registry_halted", row["ts_ns"]))
        keys: int | None = over.pop("keys", 0)
        report = _report(
            transitions=(row,),
            verdicts={verdict["verdict_id"]: verdict},
            node_log_vetos=(veto,),
            new_exec_store_halt_keys=keys,
        )
        halt: Mapping[str, Any] = report["classes"]["HALT"]
        return halt

    assert halt_report()["satisfied"] is True
    assert halt_report(verdict=_verdict("DRILL_INJECT"))["satisfied"] is False
    assert halt_report(row=_row("DEMOTE"))["satisfied"] is False
    assert (
        halt_report(row=_row("HALT", halt_cause_class="INTEGRITY", drill=False))["satisfied"]
        is False
    )
    assert halt_report(row=_row("HALT", decided_by="operator_cli"))["satisfied"] is False
    row = _row("HALT")
    assert (
        halt_report(row=row, veto=_node_veto("registry_not_champion", row["ts_ns"]))["satisfied"]
        is False
    )
    assert halt_report(keys=1)["satisfied"] is False  # a new exec-store halt key voids it
    assert halt_report(keys=None)["satisfied"] is False  # unknown is not zero
    # the DEMOTE drill alone never satisfies HALT
    demote = _row("DEMOTE")
    only_demote = _report(
        transitions=(demote,),
        verdicts={"c" * 64: _verdict("DRILL_INJECT")},
        node_log_vetos=(_node_veto("registry_not_champion", demote["ts_ns"]),),
        new_exec_store_halt_keys=0,
    )
    assert only_demote["classes"]["DEMOTE"]["satisfied"] is True
    assert only_demote["classes"]["HALT"]["satisfied"] is False


def test_self_heal_class_satisfied_by_watchdog_restart_or_wp4_mechanism_proof() -> None:
    natural = _report(restarts=(_restart(),))["classes"]["SELF_HEAL"]
    assert natural["satisfied"] and natural["injected"] is False and natural["basis"] == "restart"
    drill = _report(restarts=(_restart(injected=True),))["classes"]["SELF_HEAL"]
    assert drill["satisfied"] and drill["injected"] is True
    fallback = _restart(notifier_delivered=False, fallback_page_delivered=True)
    assert _report(restarts=(fallback,))["classes"]["SELF_HEAL"]["satisfied"]
    # a broken chain does not satisfy, and does not let the mechanism proof stand in
    broken = _report(
        restarts=(_restart(notifier_delivered=False),), wp4_mechanism_proof="WP4_V-W1.md"
    )["classes"]["SELF_HEAL"]
    assert broken["satisfied"] is False and broken["reason"] == "restart_chain_incomplete"
    for change in ({"unit": "breezy-trade-supervisor.service"}, {"unit_result": "exit-code"}):
        wrong = _report(restarts=(_restart(**change),))["classes"]["SELF_HEAL"]
        assert wrong["satisfied"] is False
    no_verdict = _report(restarts=(_restart(verdict_id=""),))["classes"]["SELF_HEAL"]
    assert no_verdict["satisfied"] is False
    # only when no restart occurred at all
    proof = _report(restarts=(), wp4_mechanism_proof="WP4_V-W1.md")["classes"]["SELF_HEAL"]
    assert proof["satisfied"] is True and proof["basis"] == "wp4_mechanism_proof"
    assert _report(restarts=())["classes"]["SELF_HEAL"]["satisfied"] is False


def test_drill_events_tagged_and_counted_only_for_their_class() -> None:
    expiry, veto = _permit(FIRST + dt.timedelta(days=1))
    # a drill-tagged canary delivery is not the ALERT proof; a real one is
    drill_canary = _canary(FIRST, drill=True)
    only_drill = _report(deliveries=(drill_canary,))
    assert only_drill["classes"]["ALERT"]["satisfied"] is False
    assert _report(deliveries=(drill_canary, _canary(FIRST)))["classes"]["ALERT"]["satisfied"]
    undelivered = _canary(FIRST, delivered=False)
    assert _report(deliveries=(undelivered,))["classes"]["ALERT"]["satisfied"] is False
    # a drill-tagged veto is not the natural ENTRY_VETO proof
    tagged = VetoFact(ts_ns=veto.ts_ns, reason="permit_lapsed", ref="r", drill=True)
    assert not _report(permit_expiries_ns=(expiry,), entry_vetos=(tagged,))["classes"][
        "ENTRY_VETO"
    ]["satisfied"]
    # DRILL_INJECT counts for DEMOTE and is reported as injected, not as natural
    demote = _row("DEMOTE")
    report = _report(
        transitions=(demote,),
        verdicts={"c" * 64: _verdict("DRILL_INJECT")},
        node_log_vetos=(_node_veto("registry_not_champion", demote["ts_ns"]),),
    )
    assert report["classes"]["DEMOTE"]["injected"] is True
    assert report["classes"]["ALERT"]["injected"] is False
    # a demote row that is not a drill, or cites no DRILL_INJECT verdict, is no proof
    plain = _row("DEMOTE", drill=False, trigger_cause_class="RECOVERABLE_MODEL")
    for row, verdicts in (
        (plain, {"c" * 64: _verdict("DRILL_INJECT")}),
        (demote, {"c" * 64: _verdict("some_other_detector")}),
        (demote, {}),
    ):
        miss = _report(
            transitions=(row,),
            verdicts=verdicts,
            node_log_vetos=(_node_veto("registry_not_champion", row["ts_ns"]),),
        )
        assert miss["classes"]["DEMOTE"]["satisfied"] is False
