"""ForecastQuantileLadderStrategy -- construction, guard wiring, shadow log.

Not wired into ``app/trade.py`` in this slice (SL-13); this suite exercises
the class directly, mirroring ``test_forecast_actor_push.py``'s real-Actor,
real-MessageBus style (no Nautilus internals monkeypatched).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass

from nautilus_trader.common.component import TestClock
from nautilus_trader.test_kit.stubs.component import TestComponentStubs

from breezy.strategy.forecast_quantile_ladder.calibration_artefact import CalibrationArtefact
from breezy.strategy.forecast_quantile_ladder.config import ForecastQuantileLadderConfig
from breezy.strategy.forecast_quantile_ladder.decision import NotExecutable, Take
from breezy.strategy.forecast_quantile_ladder.strategy import (
    ForecastQuantileLadderStrategy,
    SupportsExpiresAtNs,
)
from breezy.strategy.ladder_ev.config import LadderEvConfig
from breezy.strategy.ladder_ev.forecast_subscriber import ForecastQuantileStateActor
from breezy.strategy.ladder_ev.quantile_density import CdfMethod, EmosParams, Rung

_DAY = dt.date(2026, 10, 1)
_LADDER = (
    Rung("lt", None, 77),
    Rung("i0", 78, 79),
    Rung("i1", 80, 81),
    Rung("i2", 82, 83),
    Rung("i3", 84, 85),
    Rung("gte", 86, None),
)


def _config() -> ForecastQuantileLadderConfig:
    return ForecastQuantileLadderConfig(
        stations=("KMIA",),
        calibration_artefact_path="/tmp/unused.json",
        calibration_artefact_sha256="a" * 64,
    )


def _artefact() -> CalibrationArtefact:
    return CalibrationArtefact(
        sha256="a" * 64,
        cdf_method=CdfMethod.NORMAL,
        emos=EmosParams(a=0.0, gamma=0.0, delta=1.0),
        p_lower_haircut=0.03,
        p_upper_haircut=0.03,
    )


def _build(
    *,
    order_submission_permit: SupportsExpiresAtNs | None = None,
    submit_veto: Callable[[], str | None] | None = None,
    fee_verified: Callable[[], bool] | None = None,
) -> ForecastQuantileLadderStrategy:
    quantile_actor = ForecastQuantileStateActor(stations=("KMIA",))
    clock = TestClock()
    clock.set_time(1_000_000_000_000)
    quantile_actor.register_base(
        portfolio=TestComponentStubs.portfolio(),
        msgbus=TestComponentStubs.msgbus(),
        cache=TestComponentStubs.cache(),
        clock=clock,
    )
    quantile_actor.start()
    return ForecastQuantileLadderStrategy(
        _config(),
        quantile_actor=quantile_actor,
        artefact=_artefact(),
        ladder_cfg=LadderEvConfig(),
        order_submission_permit=order_submission_permit,
        submit_veto=submit_veto,
        fee_verified=fee_verified,
    )


def test_construction_succeeds_with_no_permit_shadow_only() -> None:
    strategy = _build()

    assert strategy.shadow_decisions == []


def test_evaluate_snapshot_with_no_forecast_yet_refuses_and_logs_it() -> None:
    strategy = _build()

    decision = strategy.evaluate_snapshot(
        now_ns=1_000_000_000_000,
        station="KMIA",
        climate_day=_DAY,
        instrument_id="KMIA-2026-10-01-i1.POLY_US",
        ladder=_LADDER,
        rung_id="i1",
        ask=0.30,
        fee_coefficient=0.0695,
        slippage_floor_prob=0.01,
        h_hours=6.0,
        n_cell=90,
    )

    assert isinstance(decision, NotExecutable)
    assert len(strategy.shadow_decisions) == 1
    assert strategy.shadow_decisions[0]["kind"] == "NotExecutable"


def test_try_submit_with_no_permit_is_phase0_refused() -> None:
    strategy = _build()
    take = Take(
        instrument_id="x",
        station="KMIA",
        climate_day=_DAY,
        side="yes",
        rung_id="i1",
        qty=1,
        ev_net=0.1,
        p_hat=0.2,
        p_lower=0.17,
        p_upper=0.23,
    )

    reason = strategy.try_submit(take)

    assert reason == "phase0_permit_absent"


@dataclass(frozen=True, slots=True)
class _FakePermit:
    """A ``SupportsExpiresAtNs`` test double -- never the real, unforgeable
    ``OrderSubmissionPermit`` (minted only via ``.issue()``, which requires
    the live operator enablement environment). Exercising the guard ORDER
    below must never touch that environment (plan §8)."""

    expires_at_ns: int


def _open_permit() -> _FakePermit:
    return _FakePermit(expires_at_ns=1_000_000_000_000 + 10 * 3_600_000_000_000)


def _take() -> Take:
    return Take(
        instrument_id="x",
        station="KMIA",
        climate_day=_DAY,
        side="yes",
        rung_id="i1",
        qty=1,
        ev_net=0.1,
        p_hat=0.2,
        p_lower=0.17,
        p_upper=0.23,
    )


def test_try_submit_with_a_real_permit_and_no_veto_or_fee_check_passes() -> None:
    strategy = _build(order_submission_permit=_open_permit())

    assert strategy.try_submit(_take()) is None


def test_try_submit_honours_the_family_halt_veto() -> None:
    strategy = _build(order_submission_permit=_open_permit(), submit_veto=lambda: "family_halt")

    assert strategy.try_submit(_take()) == "family_halt"


def test_try_submit_honours_an_unverified_fee_coefficient() -> None:
    strategy = _build(order_submission_permit=_open_permit(), fee_verified=lambda: False)

    assert strategy.try_submit(_take()) == "fee_unverified"


def test_permit_checked_before_the_veto() -> None:
    """Guard order matches ``continuous_strategy``: permit first."""
    strategy = _build(submit_veto=lambda: "family_halt")

    assert strategy.try_submit(_take()) == "phase0_permit_absent"
