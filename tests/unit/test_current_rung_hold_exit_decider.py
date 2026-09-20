"""RED-first suite for the pure exit decider (INC-E3,
``docs/plans/POSITION_EXIT_EXECUTION_2026-09-16.md`` §3,
``docs/specs/PREREG_v4_crh_exit_DRAFT_2026-09-16.md`` §3b).

Every test drives :func:`decide_exit` directly with hand-built
``MonitorDecision``/``MonitorEvidence``/``FamilyManifest`` values -- no
Nautilus, no I/O, mirroring ``test_current_rung_hold_monitor_decision.py``'s
own style.
"""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from pathlib import Path

import pytest

from breezy.persistence.family_manifest import FamilyManifest
from breezy.strategy.current_rung_hold.exit_authorization import ExitRule
from breezy.strategy.current_rung_hold.exit_decider import (
    MAX_STATION_DAY_EXIT_ORDERS,
    ExitProposal,
    ExitRefusal,
    decide_exit,
)
from breezy.strategy.current_rung_hold.monitor_decision import (
    _DEAD_MIN_CONFIRM_SPAN_NS,
    _THREATENED_MIN_SPAN_NS,
    MonitorDecision,
    ThesisState,
    Verdict,
)
from breezy.strategy.current_rung_hold.monitor_evidence import MonitorEvidence

_NOW_NS = 1_700_000_000_000_000_000
_FRESH_BOOK_NS = 10_000_000_000  # 10s, well inside the 180s staleness bound
_STALE_BOOK_NS = 200_000_000_000  # 200s, beyond the 180s bound
_FEE_COEFFICIENT = Decimal("0.06")


def _evidence(
    *,
    leg: str = "YES",
    p_hold_at_t: Decimal | None = Decimal("0.30"),
    mark_vwap: Decimal | None = Decimal("0.50"),
    mark_source: str = "depth_walk",
    depth_sufficient: bool = True,
    book_staleness_ns: int | None = _FRESH_BOOK_NS,
    held_qty: int = 1,
    instrument_id: str = "tc-temp-sfohigh-2026-09-16-gte80lt81f.POLYMARKET_US",
) -> MonitorEvidence:
    return MonitorEvidence(
        ts_ns=_NOW_NS,
        instrument_id=instrument_id,
        station="SFO",
        climate_day="2026-09-16",
        leg=leg,  # type: ignore[arg-type]
        cell_key=("SFO", "summer", 14, 2, 1),
        p_hold_at_entry=Decimal("0.60"),
        p_hold_at_t=p_hold_at_t,
        fill_px=Decimal("0.40"),
        held_qty=held_qty,
        mark_vwap=mark_vwap,
        mark_source=mark_source,  # type: ignore[arg-type]
        spread=Decimal("0.02"),
        depth_sufficient=depth_sufficient,
        staleness_ns=1_000_000_000,
        book_staleness_ns=book_staleness_ns,
        running_max_lower=85,
        running_max_upper=85,
        rung_low=84,
        rung_high=86,
        exit_fee_at_mark=Decimal("0.01"),
        unrealized_pnl=Decimal(0),
        recoverable_value=Decimal("0.39"),
        hour_lst=14,
        entry_context="live",
    )


def _decision(
    state: ThesisState, verdict: Verdict, *, ts_ns: int = _NOW_NS,
) -> MonitorDecision:
    return MonitorDecision(
        state=state, verdict=verdict, reason_codes=(), confirmations=3, ts_ns=ts_ns,
    )


_DEFAULT_EXIT_RULE: str = "crh_exit_v4:R_THREAT_PRIMARY+R_DEAD_BACKSTOP"


def _manifest(
    *, family_id: str = "pm_us_crh_exit_v4", exit_rule: str | None = _DEFAULT_EXIT_RULE,
) -> FamilyManifest:
    return FamilyManifest(
        family_id=family_id,
        venue="polymarket_us",
        taker_fee_coefficient=Decimal("0.06"),
        trial_id_prefix="current_rung_hold_exit_v4/trial/",
        d0_climate_day="2099-01-01",
        boundary_artefact_path=Path("deploy/families/gs_boundary_pm_us_crh_v2.json"),
        boundary_inputs_sha256="a" * 64,
        composition_kind="continuous_rung_hold",
        density_artefact_path=Path("deploy/families/artefacts/not_applicable_density.json"),
        density_artefact_sha256="247f636350685b38966251703c47d10531913367fbcca175b086a2c298421a65",
        stations=("SFO",),
        status="REGISTERED" if exit_rule is not None else "DRAFT_NOT_REGISTERED",
        manifest_sha256="b" * 64,
        exit_rule=exit_rule,
    )


def _decide(
    decision: MonitorDecision,
    evidence: MonitorEvidence,
    *,
    manifest: FamilyManifest | None = None,
    last_exit_decided_at_ns_for_position: int | None = None,
    station_day_exit_count: int = 0,
    now_ns: int = _NOW_NS,
    client_order_id_factory: Callable[[], str] | None = None,
    fee_coefficient: Decimal = _FEE_COEFFICIENT,
) -> ExitProposal | ExitRefusal:
    return decide_exit(
        decision,
        evidence,
        manifest=manifest if manifest is not None else _manifest(),
        family_id="pm_us_crh_exit_v4",
        position_id="P-1",
        client_order_id_factory=client_order_id_factory or (lambda: "exit-coid-1"),
        last_exit_decided_at_ns_for_position=last_exit_decided_at_ns_for_position,
        station_day_exit_count=station_day_exit_count,
        fee_coefficient=fee_coefficient,
        now_ns=now_ns,
    )


# ---------------------------------------------------------------------------
# Family gate
# ---------------------------------------------------------------------------


def test_a_family_that_does_not_declare_exit_rule_always_refuses() -> None:
    outcome = _decide(
        _decision(ThesisState.DEAD_BY_OBSERVATION, Verdict.EXIT_RECOMMENDED),
        _evidence(mark_vwap=Decimal("0.10")),
        manifest=_manifest(exit_rule=None),
    )
    assert isinstance(outcome, ExitRefusal)
    assert outcome.reason == "family_not_exit_registered"
    assert outcome.rule is None


def test_pm_us_crh_cont_never_fires_even_with_an_exit_rule_string_hypothetically_set() -> None:
    """Mirrors ``test_persistence_exit_gate.py``'s own pin: membership in
    the code-registered frozenset is required too, not just a manifest
    field -- ``pm_us_crh_cont`` is not (and must never become) a member."""
    outcome = _decide(
        _decision(ThesisState.DEAD_BY_OBSERVATION, Verdict.EXIT_RECOMMENDED),
        _evidence(mark_vwap=Decimal("0.10")),
        manifest=_manifest(family_id="pm_us_crh_cont", exit_rule="hypothetically-set"),
    )
    assert isinstance(outcome, ExitRefusal)
    assert outcome.reason == "family_not_exit_registered"


# ---------------------------------------------------------------------------
# Rule selection / MISSING_STOP / no-exit-condition
# ---------------------------------------------------------------------------


def test_missing_stop_never_authorises_an_order() -> None:
    outcome = _decide(
        _decision(ThesisState.DEAD_BY_OBSERVATION, Verdict.MISSING_STOP),
        _evidence(mark_source="missing", mark_vwap=None, depth_sufficient=False),
    )
    assert isinstance(outcome, ExitRefusal)
    assert outcome.reason == "missing_stop_no_order"
    assert outcome.rule is None


@pytest.mark.parametrize(
    ("state", "verdict"),
    [
        (ThesisState.ALIVE, Verdict.HOLD),
        (ThesisState.LOCKED_BY_OBSERVATION, Verdict.HOLD),
        (ThesisState.UNKNOWN, Verdict.UNKNOWN),
    ],
)
def test_neither_rule_fires_outside_threatened_or_dead(
    state: ThesisState, verdict: Verdict,
) -> None:
    outcome = _decide(_decision(state, verdict), _evidence())
    assert isinstance(outcome, ExitRefusal)
    assert outcome.reason == "no_exit_condition"
    assert outcome.rule is None


# ---------------------------------------------------------------------------
# R_DEAD -- per leg (L-44)
# ---------------------------------------------------------------------------


def test_r_dead_fires_on_confirmed_dead_and_exit_recommended_yes_leg() -> None:
    outcome = _decide(
        _decision(ThesisState.DEAD_BY_OBSERVATION, Verdict.EXIT_RECOMMENDED),
        _evidence(leg="YES", mark_vwap=Decimal("0.05")),
    )
    assert isinstance(outcome, ExitProposal)
    assert outcome.authorization.rule is ExitRule.R_DEAD
    assert outcome.authorization.leg == "yes"
    assert outcome.authorization.expected_settlement_value == Decimal(0)


def test_r_dead_fires_on_confirmed_dead_and_exit_recommended_no_leg() -> None:
    outcome = _decide(
        _decision(ThesisState.DEAD_BY_OBSERVATION, Verdict.EXIT_RECOMMENDED),
        _evidence(leg="NO", mark_vwap=Decimal("0.05")),
    )
    assert isinstance(outcome, ExitProposal)
    assert outcome.authorization.rule is ExitRule.R_DEAD
    assert outcome.authorization.leg == "no"


def test_r_dead_refuses_when_net_proceeds_are_not_strictly_positive() -> None:
    """``0.06*p*(1-p) < p`` for every ``p`` in ``(0, 1)``, so R_DEAD's
    ``net proceeds > 0`` bar is trivially cleared by the REAL fee
    coefficient at any executable price -- this is the measured content of
    "recovering something beats a certain zero" (plan §1). To exercise the
    refusal branch at all, this test uses an artificially large
    ``fee_coefficient`` that makes the fee exceed the price -- the branch
    exists as a documented safety net (mirrors
    ``ExitAuthorization``'s own re-check), not because real fee economics
    ever reach it.
    """
    outcome = _decide(
        _decision(ThesisState.DEAD_BY_OBSERVATION, Verdict.EXIT_RECOMMENDED),
        _evidence(mark_vwap=Decimal("0.10")),
        fee_coefficient=Decimal("2.0"),
    )
    assert isinstance(outcome, ExitRefusal)
    assert outcome.reason == "r_dead_nonpositive_proceeds"
    assert outcome.rule is ExitRule.R_DEAD


# ---------------------------------------------------------------------------
# R_THREAT -- per leg (L-44)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("verdict", [Verdict.REDUCE_RECOMMENDED, Verdict.EXIT_RECOMMENDED])
def test_r_threat_fires_on_threatened_yes_leg(verdict: Verdict) -> None:
    outcome = _decide(
        _decision(ThesisState.THREATENED, verdict),
        _evidence(leg="YES", p_hold_at_t=Decimal("0.30"), mark_vwap=Decimal("0.50")),
    )
    assert isinstance(outcome, ExitProposal)
    assert outcome.authorization.rule is ExitRule.R_THREAT
    assert outcome.authorization.expected_settlement_value == Decimal("0.30")


def test_r_threat_fires_on_threatened_no_leg() -> None:
    outcome = _decide(
        _decision(ThesisState.THREATENED, Verdict.REDUCE_RECOMMENDED),
        _evidence(leg="NO", p_hold_at_t=Decimal("0.30"), mark_vwap=Decimal("0.85")),
    )
    assert isinstance(outcome, ExitProposal)
    assert outcome.authorization.rule is ExitRule.R_THREAT
    assert outcome.authorization.expected_settlement_value == Decimal("0.70")


def test_r_threat_refuses_when_proceeds_do_not_exceed_the_hold_expectation() -> None:
    outcome = _decide(
        _decision(ThesisState.THREATENED, Verdict.REDUCE_RECOMMENDED),
        _evidence(p_hold_at_t=Decimal("0.50"), mark_vwap=Decimal("0.40")),
    )
    assert isinstance(outcome, ExitRefusal)
    assert outcome.reason == "r_threat_insufficient_proceeds"
    assert outcome.rule is ExitRule.R_THREAT


def test_r_threat_never_fires_when_p_hold_is_undefined() -> None:
    outcome = _decide(
        _decision(ThesisState.THREATENED, Verdict.REDUCE_RECOMMENDED),
        _evidence(p_hold_at_t=None, mark_vwap=Decimal("0.50")),
    )
    assert isinstance(outcome, ExitRefusal)
    assert outcome.reason == "expected_settlement_undefined"
    assert outcome.rule is ExitRule.R_THREAT


# ---------------------------------------------------------------------------
# Book freshness / executability
# ---------------------------------------------------------------------------


def test_refuses_when_the_book_is_not_executable() -> None:
    outcome = _decide(
        _decision(ThesisState.THREATENED, Verdict.REDUCE_RECOMMENDED),
        _evidence(mark_source="missing", mark_vwap=None, depth_sufficient=False),
    )
    assert isinstance(outcome, ExitRefusal)
    assert outcome.reason == "book_not_executable"


def test_refuses_when_the_book_is_stale() -> None:
    outcome = _decide(
        _decision(ThesisState.THREATENED, Verdict.REDUCE_RECOMMENDED),
        _evidence(book_staleness_ns=_STALE_BOOK_NS),
    )
    assert isinstance(outcome, ExitRefusal)
    assert outcome.reason == "book_stale"


def test_refuses_when_book_staleness_is_unknown() -> None:
    outcome = _decide(
        _decision(ThesisState.THREATENED, Verdict.REDUCE_RECOMMENDED),
        _evidence(book_staleness_ns=None),
    )
    assert isinstance(outcome, ExitRefusal)
    assert outcome.reason == "book_stale"


# ---------------------------------------------------------------------------
# Rate limit
# ---------------------------------------------------------------------------


def test_r_threat_refuses_a_second_exit_inside_the_confirmation_span() -> None:
    outcome = _decide(
        _decision(ThesisState.THREATENED, Verdict.REDUCE_RECOMMENDED),
        _evidence(),
        last_exit_decided_at_ns_for_position=_NOW_NS - 1,
    )
    assert isinstance(outcome, ExitRefusal)
    assert outcome.reason == "exit_rate_limited"


def test_r_threat_fires_again_once_the_confirmation_span_has_elapsed() -> None:
    outcome = _decide(
        _decision(ThesisState.THREATENED, Verdict.REDUCE_RECOMMENDED),
        _evidence(),
        last_exit_decided_at_ns_for_position=_NOW_NS - _THREATENED_MIN_SPAN_NS - 1,
    )
    assert isinstance(outcome, ExitProposal)


def test_r_dead_refuses_a_second_exit_inside_its_shorter_confirmation_span() -> None:
    outcome = _decide(
        _decision(ThesisState.DEAD_BY_OBSERVATION, Verdict.EXIT_RECOMMENDED),
        _evidence(mark_vwap=Decimal("0.05")),
        last_exit_decided_at_ns_for_position=_NOW_NS - _DEAD_MIN_CONFIRM_SPAN_NS + 1,
    )
    assert isinstance(outcome, ExitRefusal)
    assert outcome.reason == "exit_rate_limited"


# ---------------------------------------------------------------------------
# Per-station-day cap
# ---------------------------------------------------------------------------


def test_refuses_once_the_per_station_day_cap_is_reached() -> None:
    outcome = _decide(
        _decision(ThesisState.THREATENED, Verdict.REDUCE_RECOMMENDED),
        _evidence(),
        station_day_exit_count=MAX_STATION_DAY_EXIT_ORDERS,
    )
    assert isinstance(outcome, ExitRefusal)
    assert outcome.reason == "station_day_exit_cap"


def test_fires_one_below_the_per_station_day_cap() -> None:
    outcome = _decide(
        _decision(ThesisState.THREATENED, Verdict.REDUCE_RECOMMENDED),
        _evidence(),
        station_day_exit_count=MAX_STATION_DAY_EXIT_ORDERS - 1,
    )
    assert isinstance(outcome, ExitProposal)


# ---------------------------------------------------------------------------
# ExitAuthorization construction / client_order_id economy
# ---------------------------------------------------------------------------


def test_a_fired_proposal_carries_a_fully_populated_authorization() -> None:
    outcome = _decide(
        _decision(ThesisState.THREATENED, Verdict.REDUCE_RECOMMENDED),
        _evidence(instrument_id="IID.POLYMARKET_US"),
    )
    assert isinstance(outcome, ExitProposal)
    auth = outcome.authorization
    assert outcome.instrument_id == "IID.POLYMARKET_US"
    assert auth.family_id == "pm_us_crh_exit_v4"
    assert auth.position_id == "P-1"
    assert auth.client_order_id == "exit-coid-1"
    assert auth.quantity == 1
    assert auth.attributed_net_long == 1
    assert auth.working_sell_qty == 0
    assert auth.limit_price == Decimal("0.50")
    assert auth.fee_coefficient == _FEE_COEFFICIENT
    assert auth.decided_at_ns == _NOW_NS
    assert auth.book_staleness_ns == _FRESH_BOOK_NS


def test_client_order_id_factory_is_never_called_on_a_refusal() -> None:
    calls: list[str] = []

    def _factory() -> str:
        calls.append("called")
        return "should-never-appear"

    outcome = _decide(
        _decision(ThesisState.ALIVE, Verdict.HOLD),
        _evidence(),
        client_order_id_factory=_factory,
    )
    assert isinstance(outcome, ExitRefusal)
    assert calls == []


def test_client_order_id_factory_is_called_exactly_once_on_a_fired_proposal() -> None:
    calls: list[str] = []

    def _factory() -> str:
        calls.append("called")
        return f"exit-{len(calls)}"

    outcome = _decide(
        _decision(ThesisState.THREATENED, Verdict.REDUCE_RECOMMENDED),
        _evidence(),
        client_order_id_factory=_factory,
    )
    assert isinstance(outcome, ExitProposal)
    assert calls == ["called"]
    assert outcome.authorization.client_order_id == "exit-1"
