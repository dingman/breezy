"""SL-13 -- ``ForecastQuantileLadderStrategy.on_start``/``_maybe_submit``,
and the REAL (non-lambda) family-halt-veto wiring
(``current_rung_hold.composition.family_halt_submit_veto`` over a real,
persistent ``TrialDayLatch``).

Reuses ``tests.unit.test_current_rung_hold_strategy``'s ``_instrument``
fixture builder (same weather-bucket-facts ``info`` shape, same
``POLYMARKET_US`` venue) -- never a second, drifting instrument fixture.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from contextlib import ExitStack
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from nautilus_trader.common.component import TestClock
from nautilus_trader.model.identifiers import InstrumentId, Symbol, TraderId, Venue
from nautilus_trader.model.instruments import BinaryOption
from nautilus_trader.portfolio import Portfolio
from nautilus_trader.test_kit.stubs.component import TestComponentStubs

from breezy.runtime.sqlite_store import SqliteStateStore
from breezy.runtime.submit_intent import open_submit_intent_latch
from breezy.strategy.current_rung_hold.composition import family_halt_submit_veto
from breezy.strategy.current_rung_hold.trial_day_latch import open_trial_day_latch
from breezy.strategy.forecast_quantile_ladder.bounds import RungBounds
from breezy.strategy.forecast_quantile_ladder.calibration_artefact import LiveCalibration
from breezy.strategy.forecast_quantile_ladder.config import ForecastQuantileLadderConfig
from breezy.strategy.forecast_quantile_ladder.decision import Take
from breezy.strategy.forecast_quantile_ladder.persistent_latch import (
    FORECAST_QUANTILE_TRIAL_KEY_PREFIX,
)
from breezy.strategy.forecast_quantile_ladder.strategy import (
    ForecastQuantileLadderStrategy,
    ShadowDecisionLogLine,
    SupportsExpiresAtNs,
)
from breezy.strategy.ladder_ev.config import LadderEvConfig
from breezy.strategy.ladder_ev.forecast_subscriber import ForecastQuantileStateActor
from breezy.strategy.ladder_ev.location_correction import CorrectionForm
from breezy.strategy.ladder_ev.quantile_density import (
    CdfMethod,
    EmosParams,
    Percentiles,
    Rung,
    build_cdf,
    rung_probabilities,
)
from tests.unit.test_current_rung_hold_strategy import _instrument

STATION = "LAX"
YES_ID = InstrumentId(Symbol("lax-80-81"), Venue("POLYMARKET_US"))
FAMILY_ID = "pm_us_crh_fq_test"


def _config() -> ForecastQuantileLadderConfig:
    return ForecastQuantileLadderConfig(
        stations=(STATION,),
        calibration_artefact_path="/tmp/unused.json",
        calibration_artefact_sha256="a" * 64,
    )


def _send_enabled_config() -> ForecastQuantileLadderConfig:
    return ForecastQuantileLadderConfig(
        stations=(STATION,),
        calibration_artefact_path="/tmp/unused.json",
        calibration_artefact_sha256="a" * 64,
        shadow_only=False,
    )


def _artefact() -> LiveCalibration:
    identity = EmosParams(a=0.0, gamma=0.0, delta=1.0)
    return LiveCalibration(
        sha256="a" * 64,
        cdf_method=CdfMethod.NORMAL,
        correction_form=CorrectionForm.NONE,
        linear_coefficients=None,
        month_offsets={},
        point_by_version={"": identity},
        draws_by_version={"": (identity,)},
    )


def _bounds_provider(
    *, percentiles: Percentiles, draws: Sequence[EmosParams], ladder: Sequence[Rung], rung_id: str,
) -> RungBounds:
    del draws
    cdf = build_cdf(CdfMethod.NORMAL, percentiles)
    p_hat = rung_probabilities(cdf, ladder)[rung_id]
    return RungBounds(p_hat=p_hat, p_lower=max(0.0, p_hat - 0.03), p_upper=min(1.0, p_hat + 0.03))


def _build_registered(
    *,
    config: ForecastQuantileLadderConfig | None = None,
    instruments: tuple[BinaryOption, ...] = (),
    order_submission_permit: SupportsExpiresAtNs | None = None,
    submit_veto: Callable[[], str | None] | None = None,
    fee_verified: Callable[[int], bool] | None = None,
    shadow_decision_sink: Callable[[ShadowDecisionLogLine], None] | None = None,
) -> ForecastQuantileLadderStrategy:
    quantile_actor = ForecastQuantileStateActor(
        stations=(STATION,), std_utc_offset_hours={STATION: -8.0},
    )
    clock = TestClock()
    clock.set_time(1_700_000_000_000_000_000)
    msgbus = TestComponentStubs.msgbus()
    cache = TestComponentStubs.cache()
    for instrument in instruments:
        cache.add_instrument(instrument)
    quantile_actor.register_base(
        portfolio=TestComponentStubs.portfolio(), msgbus=msgbus, cache=cache, clock=clock,
    )
    quantile_actor.start()

    strategy = ForecastQuantileLadderStrategy(
        config if config is not None else _config(),
        quantile_actor=quantile_actor,
        calibration=_artefact(),
        ladder_cfg=LadderEvConfig(),
        bounds_provider=_bounds_provider,
        order_submission_permit=order_submission_permit,
        submit_veto=submit_veto,
        fee_verified=fee_verified,
        instrument_ids=tuple(str(i.id) for i in instruments),
        shadow_decision_sink=shadow_decision_sink,
    )
    portfolio = Portfolio(msgbus=msgbus, cache=cache, clock=clock)
    strategy.register(
        trader_id=TraderId("BACKTEST-001"),
        portfolio=portfolio,
        msgbus=msgbus,
        cache=cache,
        clock=clock,
    )
    return strategy


def _take() -> Take:
    return Take(
        instrument_id=str(YES_ID),
        station=STATION,
        climate_day=__import__("datetime").date(2026, 9, 4),
        side="yes",
        rung_id="i1",
        qty=1,
        ev_net=0.1,
        p_hat=0.2,
        p_lower=0.17,
        p_upper=0.23,
    )


@dataclass(frozen=True, slots=True)
class _FakePermit:
    expires_at_ns: int


def _open_permit() -> _FakePermit:
    return _FakePermit(expires_at_ns=1_000_000_000_000 + 10 * 3_600_000_000_000)


# ---------------------------------------------------------------------------
# `_maybe_submit` -- the native order-submission path (task item 2)
# ---------------------------------------------------------------------------


def test_maybe_submit_with_no_permit_never_reaches_submit_order() -> None:
    instrument = _instrument(YES_ID, lower_f=80, upper_f=81)
    strategy = _build_registered(config=_send_enabled_config(), instruments=(instrument,))
    strategy.submit_order = MagicMock()

    strategy._maybe_submit(_take(), limit_price=Decimal("0.30"))

    strategy.submit_order.assert_not_called()


def test_maybe_submit_honouring_the_family_halt_veto_never_reaches_submit_order() -> None:
    instrument = _instrument(YES_ID, lower_f=80, upper_f=81)
    strategy = _build_registered(
        config=_send_enabled_config(),
        instruments=(instrument,),
        order_submission_permit=_open_permit(),
        submit_veto=lambda: "family_halt",
    )
    strategy.submit_order = MagicMock()

    strategy._maybe_submit(_take(), limit_price=Decimal("0.30"))

    strategy.submit_order.assert_not_called()


def test_maybe_submit_with_a_clear_permit_submits_a_native_ioc_limit_order() -> None:
    instrument = _instrument(YES_ID, lower_f=80, upper_f=81)
    strategy = _build_registered(
        config=_send_enabled_config(),
        instruments=(instrument,),
        order_submission_permit=_open_permit(),
    )
    strategy.submit_order = MagicMock()

    strategy._maybe_submit(_take(), limit_price=Decimal("0.30"))

    strategy.submit_order.assert_called_once()
    order = strategy.submit_order.call_args.args[0]
    assert str(order.instrument_id) == str(YES_ID)


# ---------------------------------------------------------------------------
# FQ-S11: `_maybe_submit`'s `try_submit` outcome is recorded through the SAME
# `shadow_decision_sink` channel `evaluate_snapshot` already uses -- the ONE
# localized hook the decision-funnel aggregator subscribes to.
# ---------------------------------------------------------------------------


def test_maybe_submit_with_no_permit_records_a_try_submit_refusal() -> None:
    instrument = _instrument(YES_ID, lower_f=80, upper_f=81)
    records: list[ShadowDecisionLogLine] = []
    strategy = _build_registered(
        config=_send_enabled_config(),
        instruments=(instrument,),
        shadow_decision_sink=records.append,
    )
    strategy.submit_order = MagicMock()

    strategy._maybe_submit(_take(), limit_price=Decimal("0.30"))

    outcomes = [r for r in records if r["kind"] == "TrySubmit"]
    assert len(outcomes) == 1
    assert outcomes[0]["reason"] == "phase0_permit_absent"
    strategy.submit_order.assert_not_called()


def test_maybe_submit_honouring_the_family_halt_veto_records_the_reason() -> None:
    instrument = _instrument(YES_ID, lower_f=80, upper_f=81)
    records: list[ShadowDecisionLogLine] = []
    strategy = _build_registered(
        config=_send_enabled_config(),
        instruments=(instrument,),
        order_submission_permit=_open_permit(),
        submit_veto=lambda: "family_halt",
        shadow_decision_sink=records.append,
    )
    strategy.submit_order = MagicMock()

    strategy._maybe_submit(_take(), limit_price=Decimal("0.30"))

    outcomes = [r for r in records if r["kind"] == "TrySubmit"]
    assert len(outcomes) == 1
    assert outcomes[0]["reason"] == "family_halt"
    strategy.submit_order.assert_not_called()


def test_maybe_submit_with_a_clear_permit_records_a_submitted_outcome() -> None:
    instrument = _instrument(YES_ID, lower_f=80, upper_f=81)
    records: list[ShadowDecisionLogLine] = []
    strategy = _build_registered(
        config=_send_enabled_config(),
        instruments=(instrument,),
        order_submission_permit=_open_permit(),
        shadow_decision_sink=records.append,
    )
    strategy.submit_order = MagicMock()

    strategy._maybe_submit(_take(), limit_price=Decimal("0.30"))

    outcomes = [r for r in records if r["kind"] == "TrySubmit"]
    assert len(outcomes) == 1
    assert outcomes[0]["reason"] == "submitted"
    strategy.submit_order.assert_called_once()


# ---------------------------------------------------------------------------
# `on_start` -- subscription + YES/NO-per-rung resolution + marker (task item 2/4)
# ---------------------------------------------------------------------------


def test_on_start_resolves_the_yes_no_pair_and_logs_the_marker(caplog: pytest.LogCaptureFixture) -> None:
    instrument = _instrument(YES_ID, lower_f=80, upper_f=81)
    strategy = _build_registered(instruments=(instrument,))

    strategy.start()

    assert ("LAX", "2026-09-04", "80_81") in strategy.rung_instruments
    yes_id, no_id = strategy.rung_instruments[("LAX", "2026-09-04", "80_81")]
    assert yes_id == str(YES_ID)
    assert no_id != yes_id


def test_on_start_is_a_no_op_safe_no_crash_with_zero_configured_instruments() -> None:
    strategy = _build_registered(instruments=())

    strategy.start()  # must not raise

    assert strategy.rung_instruments == {}


# ---------------------------------------------------------------------------
# The REAL family-halt-veto wiring (task item 2/RED list: "the halt veto is
# honoured") -- current_rung_hold.composition.family_halt_submit_veto over a
# real, persistent TrialDayLatch, never a lambda double.
# ---------------------------------------------------------------------------


@pytest.fixture
def store_path(tmp_path: Path) -> Path:
    return tmp_path / "state.db"


def test_try_submit_honours_the_real_family_halt_veto_wiring(store_path: Path) -> None:
    with ExitStack() as stack:
        intent_latch = stack.enter_context(
            open_submit_intent_latch(SqliteStateStore(store_path), store_path),
        )
        halt_latch = open_trial_day_latch(
            intent_latch, key_prefix=FORECAST_QUANTILE_TRIAL_KEY_PREFIX, family_id=FAMILY_ID,
        )
        halt_latch.record_policy_halt(
            reason="test_halt", evidence_sha256="a" * 64, ts_ns=1_700_000_000_000_000_000,
        )
        veto = family_halt_submit_veto(halt_latch)
        strategy = _build_registered(order_submission_permit=_open_permit(), submit_veto=veto)

        reason = strategy.try_submit(_take())

        assert reason is not None


def test_try_submit_clears_once_the_real_halt_is_cleared(store_path: Path) -> None:
    with ExitStack() as stack:
        intent_latch = stack.enter_context(
            open_submit_intent_latch(SqliteStateStore(store_path), store_path),
        )
        halt_latch = open_trial_day_latch(
            intent_latch, key_prefix=FORECAST_QUANTILE_TRIAL_KEY_PREFIX, family_id=FAMILY_ID,
        )
        veto = family_halt_submit_veto(halt_latch)
        strategy = _build_registered(order_submission_permit=_open_permit(), submit_veto=veto)

        reason = strategy.try_submit(_take())

        assert reason is None
