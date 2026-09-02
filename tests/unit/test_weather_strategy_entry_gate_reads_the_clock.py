"""The ENTRY time gates read the clock, not the forecast's self-reported horizon.

T-8 reduced (``docs/core/findings/BLIND_RISK_VIEWS_2026-09-02.md``, whose
original T-8 is RETRACTED -- read that block before this one).

THE DEFECT
----------
``_maybe_submit`` in ``forecast_mispricing``, ``calibration_mean_reversion``
and ``forecast_revision`` is byte-identical at the line under test::

    risk_decision = self._risk.evaluate_order(
        ...
        hours_to_settlement=forecast.horizon_hours,

``ForecastSnapshot.horizon_hours`` is live-hours-to-settlement *by prose
contract only* (T-7: the ``ForecastSource`` ``Protocol`` carries no liveness
constraint, and two of four in-repo implementations are frozen). A frozen
source holding 24.0 while the clock says T-minus-90-minutes therefore hands
``RiskManager.evaluate_order`` a 24.0, and the ``min_hours_to_settlement``
gate at ``risk.py:519`` (default 2.0) fails open.

THE WINDOW IS ONE HOUR WIDE, AND THAT IS THE WHOLE EXPOSURE
-----------------------------------------------------------
Below ``halt_hours_before_settlement`` (default 1.0) T-5's clock-derived halt
flattens and returns before ``_maybe_submit`` is ever reached, so the entry
gate is moot there. Above ``min_hours_to_settlement`` (default 2.0) the gate
is satisfied on any time base. What is left is exactly
``T-t in (1.0, 2.0) h``: T-minus-90-minutes, the instant these tests are set
to. The original T-8 claimed a much larger hole; it was wrong, because
``risk.py:531`` refuses on ``forecast_age_hours``, which is clock-derived and
immune to a lying horizon. This module pins the hole that is actually there.

AND ONE EXIT A FROZEN SOURCE DISABLES OUTRIGHT
-----------------------------------------------
``calibration_mean_reversion/decision.py`` gates its
``calibration_horizon_flatten`` on ``hours_left = forecast.horizon_hours``
against ``min_horizon_hours`` (6.0). Against a frozen 24.0 that exit can never
fire at all -- same class as T-5, a different exit. T-11 already put the
instrument's own native deadline in scope there as ``settlement_deadline``, and
``now`` was always a parameter, so the fix needs no new plumbing.

WHAT MUST NOT MOVE, AND IS PINNED HERE AS A CONTROL
----------------------------------------------------
* The fix must not become "always refuse" -- :func:`test_an_entry_outside_the
  _window_is_not_refused_on_hours` holds the clock at T-minus-3h and requires
  the order through.
* ``ForecastErrorModel.sigma`` keeps the ISSUANCE lead T-11 gave it, and
  ``expected_probability_se`` keeps the LIVE horizon. Neither is touched here;
  ``test_forecast_sigma_uses_issuance_lead.py`` owns both.
* A CONFORMING source must be indistinguishable before and after: its
  ``horizon_hours`` already equals the clock-derived value, so nothing about
  its behaviour may change.

FIDELITY
--------
Real ``Cache``, ``MessageBus``, ``TestClock``, ``OrderFactory`` and Nautilus
order state, with the emitted commands captured off the
``RiskEngine.execute`` / ``ExecEngine.execute`` endpoints, and the REAL
captured Polymarket.us instrument -- so ``expiration_ns`` is a real venue
settlement instant and the clock is set relative to it rather than to an
invented deadline. The rig shape is
``test_weather_strategy_settlement_halt_without_forecast.py``; the direct
``_maybe_submit`` drive (with a stated ``SignalDecision``, so the three
different decision layers are not under test here) is the seam
``test_weather_strategy_inflight_orders.py`` already uses.

Doubles, all narrow: ``PortfolioFacade`` so a settled position and an observed
balance can be STATED, a recording proxy over ``log`` that forwards to the
real ``Logger``, and a recording proxy over the REAL ``RiskManager`` that
records the ``hours_to_settlement`` it was handed and delegates unchanged --
a spy, never a stub, so every refusal below is the shipped risk logic's own.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import pytest
from nautilus_trader.cache.cache import Cache
from nautilus_trader.common.component import MessageBus, TestClock
from nautilus_trader.config import CacheConfig
from nautilus_trader.execution.messages import SubmitOrder
from nautilus_trader.model.identifiers import TraderId
from nautilus_trader.portfolio.base import PortfolioFacade

from breezy.adapters.polymarket_us.parsing import parse_binary_option
from breezy.domain.weather_bucket_facts import read_weather_bucket_facts
from breezy.strategy.calibration_mean_reversion.config import CalibrationMeanReversionConfig
from breezy.strategy.calibration_mean_reversion.decision import (
    evaluate_instrument as evaluate_calibration,
)
from breezy.strategy.calibration_mean_reversion.strategy import CalibrationMeanReversionStrategy
from breezy.strategy.forecast_mispricing.config import ForecastMispricingConfig
from breezy.strategy.forecast_mispricing.strategy import ForecastMispricingStrategy
from breezy.strategy.forecast_revision.config import ForecastRevisionConfig
from breezy.strategy.forecast_revision.strategy import ForecastRevisionStrategy
from breezy.strategy.weather_common.bucket_contract import MispricingContract
from breezy.strategy.weather_common.models import (
    ForecastSnapshot,
    MarketQuote,
    SideIntent,
    SignalDecision,
    hours_until,
)
from breezy.strategy.weather_common.probability import (
    WeatherProbabilityEngine,
    default_conus_summer_error_model,
)
from breezy.strategy.weather_common.risk import RiskLimits, RiskManager
from tests.unit.conftest import iter_captured_market_payloads

if TYPE_CHECKING:  # pragma: no cover - typing only
    from nautilus_trader.model.instruments import BinaryOption
    from nautilus_trader.trading.strategy import Strategy

TRADER_ID = TraderId("BREEZY-ENTRY-008")

_NS_PER_SECOND = 1_000_000_000

#: The one-hour fail-open window, in the middle: below `min_hours_to_settlement`
#: (2.0) and above `halt_hours_before_settlement` (1.0), where T-5's halt takes
#: over.
HOURS_INSIDE_WINDOW = 1.5
#: Comfortably outside it, for the must-still-trade control.
HOURS_OUTSIDE_WINDOW = 3.0

#: What a frozen `ForecastSource` reports forever -- the literal
#: `_ConstantForecastSource` value named in T-7.
FROZEN_HORIZON_H = 24.0

#: The refusal the `min_hours_to_settlement` gate returns (`risk.py:520`).
TOO_CLOSE = "too_close_to_settlement"
#: Its neighbour one line up, which T-5 already covers upstream.
SETTLEMENT_HALT = "settlement_halt"

ORDER_QTY = 200.0

#: Keeps the equity-fraction clip out of the way of what this module measures
#: (0.08 x 10_000 = 800 contracts against an `ORDER_QTY` of 200), while still
#: STATING an observation rather than leaning on the absence of one (T-4).
OBSERVED_EQUITY = 10_000.0

#: `calibration_mean_reversion`'s shipped `min_horizon_hours`, restated so the
#: clock positions below are visibly relative to the gate under test.
CALIBRATION_MIN_HORIZON_H = 6.0
CALIBRATION_HOURS_INSIDE = 3.0
CALIBRATION_HOURS_OUTSIDE = 24.0
CALIBRATION_FLATTEN = "calibration_horizon_flatten"


def _instrument() -> BinaryOption:
    payloads = iter_captured_market_payloads()
    assert payloads, "no captured Polymarket.us market payloads on disk"
    return parse_binary_option(payloads[0], ts_init=0)


def _deadline_of(instrument: BinaryOption) -> dt.datetime:
    return dt.datetime.fromtimestamp(instrument.expiration_ns / _NS_PER_SECOND, tz=dt.UTC)


class _StubForecastSource:
    """Never consulted: every test here drives the decision-side entry directly."""

    def snapshot(
        self,
        *,
        station: str,
        climate_day: dt.date,
        now: dt.datetime,
    ) -> ForecastSnapshot | None:
        del station, climate_day, now
        return None


class _StubBalance:
    def __init__(self, amount: float) -> None:
        self._amount = amount

    def as_double(self) -> float:
        return self._amount


class _StubAccount:
    def __init__(self, balance: float) -> None:
        self._balance = balance

    def balance_total(self, currency: Any) -> _StubBalance:
        del currency
        return _StubBalance(self._balance)


class _SettledPositionPortfolio(PortfolioFacade):  # type: ignore[misc]  # compiled Cython base erases to Any
    """States the SETTLED position and an OBSERVED balance, nothing else."""

    def __init__(self, net: float) -> None:
        self._net = Decimal(str(net))

    def net_position(self, instrument_id: Any, account_id: Any = None) -> Decimal:
        del instrument_id, account_id
        return self._net

    def account(self, venue: Any) -> _StubAccount:
        del venue
        return _StubAccount(OBSERVED_EQUITY)


class _RecordingRisk:
    """A SPY over the real `RiskManager`: records, delegates, changes nothing.

    Records the `hours_to_settlement` each `evaluate_order` was handed -- the
    value under test -- and forwards every call, including the attribute
    lookups `_portfolio_snapshot` makes, to the real manager. No refusal below
    is manufactured here; all of them are the shipped risk logic's own.
    """

    def __init__(self, real: RiskManager) -> None:
        self._real = real
        self.hours_seen: list[float] = []

    def evaluate_order(self, **kwargs: Any) -> Any:
        self.hours_seen.append(float(kwargs["hours_to_settlement"]))
        return self._real.evaluate_order(**kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._real, name)


class _RecordingLog:
    """Records every message and forwards it to the real ``Logger``."""

    def __init__(self, real: Any, messages: list[str]) -> None:
        self._real = real
        self._messages = messages

    def info(self, message: str, **kwargs: Any) -> None:
        self._messages.append(message)
        self._real.info(message, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._real, name)


class _Rig:
    """One real strategy, clock set relative to the instrument's real expiry."""

    name: str = "base"
    strategy_cls: type[Strategy]
    config_cls: Any

    def __init__(
        self,
        monkeypatch: pytest.MonkeyPatch,
        *,
        hours_to_settlement: float,
        settled_qty: float = 0.0,
    ) -> None:
        self.instrument = _instrument()
        self.instrument_id = self.instrument.id
        self.local_id = str(self.instrument.id)
        self.deadline = _deadline_of(self.instrument)

        self.clock = TestClock()
        self.now_ns = self.instrument.expiration_ns - int(
            hours_to_settlement * 3600 * _NS_PER_SECOND,
        )
        self.clock.set_time(self.now_ns)

        msgbus = MessageBus(trader_id=TRADER_ID, clock=self.clock)
        self.cache = Cache(
            database=None,
            config=CacheConfig(database=None, flush_on_start=False),
        )
        self.cache.add_instrument(self.instrument)

        self.commands: list[Any] = []
        msgbus.register("RiskEngine.execute", self.commands.append)
        msgbus.register("ExecEngine.execute", self.commands.append)

        self.strategy = self.build_strategy(self.instrument_id)
        self.strategy.register(
            TRADER_ID,
            _SettledPositionPortfolio(settled_qty),
            msgbus,
            self.cache,
            self.clock,
        )

        self.contract = MispricingContract(
            instrument_id=self.local_id,
            facts=read_weather_bucket_facts(self.instrument.info),
            tick_size=float(self.instrument.price_increment),
        )
        # `on_start` is bypassed: it subscribes to live data feeds no unit test
        # has. `_deadlines`'s POPULATION from the native `expiration_ns` is
        # pinned by `test_weather_strategy_settlement_halt_without_forecast.py`.
        self.strategy._contracts = {self.local_id: self.contract}
        self.strategy._nt_ids = {self.local_id: self.instrument_id}
        self.strategy._deadlines = {self.local_id: self.deadline}
        self.risk = _RecordingRisk(
            RiskManager(
                RiskLimits(),
                {self.local_id: self.contract},
                native_instrument_ids=self.strategy._nt_ids,
            ),
        )
        self.strategy._risk = self.risk

        self.log_messages: list[str] = []
        real_log = self.strategy.log
        monkeypatch.setattr(
            type(self.strategy),
            "log",
            property(lambda _self: _RecordingLog(real_log, self.log_messages)),
            raising=False,
        )

    # -- per-strategy seam -----------------------------------------------

    @classmethod
    def build_strategy(cls, instrument_id: Any) -> Strategy:
        return cls.strategy_cls(
            cls.config_cls(instrument_ids=(instrument_id,)),
            _StubForecastSource(),
        )

    # -- action ----------------------------------------------------------

    @property
    def now(self) -> dt.datetime:
        # The STRATEGY's own clock, never a separately stated instant: the
        # whole subject here is which time base the gate reads.
        now: dt.datetime = self.clock.utc_now()
        return now

    def frozen_forecast(self) -> ForecastSnapshot:
        """What a frozen source reports: 24.0, whatever the clock says."""
        return ForecastSnapshot(
            location_id=self.contract.facts.settlement_station,
            target_date=self.contract.facts.climate_day,
            published_at=self.now - dt.timedelta(hours=1),
            expected_high_f=66.5,
            horizon_hours=FROZEN_HORIZON_H,
        )

    def conforming_forecast(self) -> ForecastSnapshot:
        """A source obeying the stated contract: horizon recomputed from `now`."""
        return ForecastSnapshot(
            location_id=self.contract.facts.settlement_station,
            target_date=self.contract.facts.climate_day,
            published_at=self.now - dt.timedelta(hours=1),
            expected_high_f=66.5,
            horizon_hours=hours_until(self.deadline, self.now),
        )

    def quote(self) -> MarketQuote:
        return MarketQuote(
            instrument_id=self.local_id,
            bid=0.28,
            ask=0.30,
            bid_size=1_000.0,
            ask_size=1_000.0,
            ts_event=self.now,
        )

    def decision(self) -> SignalDecision:
        return SignalDecision(
            instrument_id=self.local_id,
            intent=SideIntent.LONG_YES,
            model_probability=0.95,
            market_probability=0.30,
            edge=0.20,
            conviction=1.0,
            quantity=ORDER_QTY,
            reason="test_long_yes",
        )

    def maybe_submit(
        self,
        *,
        forecast: ForecastSnapshot | None = None,
        current_qty: float = 0.0,
    ) -> None:
        self.strategy._maybe_submit(
            self.contract,
            self.quote(),
            self.decision(),
            self.frozen_forecast() if forecast is None else forecast,
            self.now,
            current_qty,
        )

    # -- observation -----------------------------------------------------

    def submit_commands(self) -> list[SubmitOrder]:
        return [c for c in self.commands if isinstance(c, SubmitOrder)]

    def risk_block_lines(self) -> list[str]:
        return [m for m in self.log_messages if m.startswith("RISK block ")]


class _ForecastMispricingRig(_Rig):
    name = "forecast_mispricing"
    strategy_cls = ForecastMispricingStrategy
    config_cls = ForecastMispricingConfig


class _CalibrationMeanReversionRig(_Rig):
    name = "calibration_mean_reversion"
    strategy_cls = CalibrationMeanReversionStrategy
    config_cls = CalibrationMeanReversionConfig


class _ForecastRevisionRig(_Rig):
    name = "forecast_revision"
    strategy_cls = ForecastRevisionStrategy
    config_cls = ForecastRevisionConfig


#: The three strategies whose entry gate reads `forecast.horizon_hours`.
ENTRY_RIGS = (
    _ForecastMispricingRig,
    _CalibrationMeanReversionRig,
    _ForecastRevisionRig,
)
ENTRY_RIG_IDS = [rig.name for rig in ENTRY_RIGS]


# ----------------------------------------------------------------------
# RED-1 -- the defect: the one-hour fail-open window, reproduced
# ----------------------------------------------------------------------


@pytest.mark.parametrize("rig_cls", ENTRY_RIGS, ids=ENTRY_RIG_IDS)
def test_a_frozen_horizon_cannot_open_a_position_inside_the_minimum_hours_gate(
    rig_cls: type[_Rig],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RED-1. Flat, T-minus-90min, source frozen at 24.0 -- the entry is refused."""
    rig = rig_cls(monkeypatch, hours_to_settlement=HOURS_INSIDE_WINDOW)

    rig.maybe_submit()

    assert rig.submit_commands() == [], (
        f"{rig_cls.name}: a NEW position of {ORDER_QTY:.0f} contracts opened at "
        f"T-minus-{HOURS_INSIDE_WINDOW:.1f}h against a `min_hours_to_settlement` "
        "of 2.0 -- the gate read the frozen forecast horizon, not the clock"
    )
    lines = rig.risk_block_lines()
    assert len(lines) == 1, f"{rig_cls.name}: silent refusal: {rig.log_messages}"
    assert TOO_CLOSE in lines[0], lines[0]


# ----------------------------------------------------------------------
# RED-2 -- the fix must not become "always refuse"
# ----------------------------------------------------------------------


@pytest.mark.parametrize("rig_cls", ENTRY_RIGS, ids=ENTRY_RIG_IDS)
def test_an_entry_outside_the_window_is_not_refused_on_hours(
    rig_cls: type[_Rig],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RED-2. Control -- passes on the pre-fix tree, states what must not move.

    Same order, same book, clock at T-minus-3h. Whatever else may stop it, it
    must not be either time gate: a fix that refused here would have traded
    one fail-open for a permanent fail-closed.
    """
    rig = rig_cls(monkeypatch, hours_to_settlement=HOURS_OUTSIDE_WINDOW)

    rig.maybe_submit()

    for line in rig.risk_block_lines():
        assert TOO_CLOSE not in line, f"{rig_cls.name}: {line}"
        assert SETTLEMENT_HALT not in line, f"{rig_cls.name}: {line}"
    assert len(rig.submit_commands()) == 1, (
        f"{rig_cls.name}: a valid entry at T-minus-{HOURS_OUTSIDE_WINDOW:.0f}h was "
        f"not submitted: {rig.risk_block_lines() or rig.log_messages}"
    )


# ----------------------------------------------------------------------
# RED-4 -- the two time bases agree BY CONSTRUCTION, not by luck
# ----------------------------------------------------------------------


@pytest.mark.parametrize("rig_cls", ENTRY_RIGS, ids=ENTRY_RIG_IDS)
def test_the_hours_handed_to_risk_are_clock_derived_even_when_the_source_is_frozen(
    rig_cls: type[_Rig],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RED-4a. The measurement behind RED-1, stated as a number."""
    rig = rig_cls(monkeypatch, hours_to_settlement=HOURS_INSIDE_WINDOW)

    rig.maybe_submit()

    assert rig.risk.hours_seen, f"{rig_cls.name}: risk was never consulted"
    expected = hours_until(rig.deadline, rig.now)
    assert rig.risk.hours_seen[0] == pytest.approx(expected, abs=1e-6), (
        f"{rig_cls.name}: risk was handed {rig.risk.hours_seen[0]}h with "
        f"{expected:.3f}h actually remaining -- the entry gate is only as live "
        "as the `ForecastSource` prose contract (T-7)"
    )
    assert rig.risk.hours_seen[0] != pytest.approx(FROZEN_HORIZON_H)


@pytest.mark.parametrize("rig_cls", ENTRY_RIGS, ids=ENTRY_RIG_IDS)
def test_a_conforming_source_is_indistinguishable_before_and_after(
    rig_cls: type[_Rig],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RED-4b. Control: with a conforming source the two bases already agree.

    Nothing about a conforming source's behaviour may change, which is why the
    in-suite fixture counts do not move.
    """
    rig = rig_cls(monkeypatch, hours_to_settlement=HOURS_OUTSIDE_WINDOW)
    forecast = rig.conforming_forecast()

    rig.maybe_submit(forecast=forecast)

    assert rig.risk.hours_seen, f"{rig_cls.name}: risk was never consulted"
    assert rig.risk.hours_seen[0] == pytest.approx(forecast.horizon_hours, abs=1e-6)
    assert rig.risk.hours_seen[0] == pytest.approx(
        hours_until(rig.deadline, rig.now), abs=1e-6,
    )
    assert len(rig.submit_commands()) == 1, rig.log_messages


# ----------------------------------------------------------------------
# RED-3 -- the exit a frozen source disables outright (calibration only)
# ----------------------------------------------------------------------


def _calibration_facts_contract() -> MispricingContract:
    instrument = _instrument()
    return MispricingContract(
        instrument_id=str(instrument.id),
        facts=read_weather_bucket_facts(instrument.info),
        tick_size=float(instrument.price_increment),
    )


def _calibration_decision(
    *,
    hours_to_settlement: float,
    horizon_hours: float,
    current_qty: float,
) -> SignalDecision | None:
    """`calibration_mean_reversion.evaluate_instrument` at a stated instant.

    `now` is already a parameter of that function and `settlement_deadline`
    was put in scope by T-11, so the deadline and the clock are both available
    to the horizon gate without any new plumbing.
    """
    contract = _calibration_facts_contract()
    now = dt.datetime(2026, 8, 28, 12, 0, tzinfo=dt.UTC)
    deadline = now + dt.timedelta(hours=hours_to_settlement)
    return evaluate_calibration(
        contract=contract,
        quote=MarketQuote(
            instrument_id=contract.instrument_id,
            bid=0.28,
            ask=0.30,
            bid_size=1_000.0,
            ask_size=1_000.0,
            ts_event=now,
        ),
        forecast=ForecastSnapshot(
            location_id=contract.facts.settlement_station,
            target_date=contract.facts.climate_day,
            published_at=now - dt.timedelta(hours=1),
            expected_high_f=66.5,
            horizon_hours=horizon_hours,
        ),
        now=now,
        current_qty=current_qty,
        engine=WeatherProbabilityEngine(default_conus_summer_error_model()),
        cfg=CalibrationMeanReversionConfig(
            instrument_ids=(),
            min_horizon_hours=CALIBRATION_MIN_HORIZON_H,
        ),
        settlement_deadline=deadline,
    )


def test_the_calibration_horizon_flatten_fires_against_a_frozen_forecast() -> None:
    """RED-3. 200 held, T-minus-3h, source frozen at 24.0 -- the exit must fire."""
    decision = _calibration_decision(
        hours_to_settlement=CALIBRATION_HOURS_INSIDE,
        horizon_hours=FROZEN_HORIZON_H,
        current_qty=ORDER_QTY,
    )

    assert decision is not None, (
        "no decision at all at T-minus-"
        f"{CALIBRATION_HOURS_INSIDE:.0f}h with {ORDER_QTY:.0f} contracts held -- "
        "the horizon flatten read the frozen 24.0 and can never fire"
    )
    assert decision.intent is SideIntent.FLAT, decision.reason
    assert decision.reason == CALIBRATION_FLATTEN, decision.reason


def test_the_calibration_horizon_flatten_still_fires_for_a_conforming_source() -> None:
    """RED-3b. Control: the conforming case must be untouched by the fix."""
    decision = _calibration_decision(
        hours_to_settlement=CALIBRATION_HOURS_INSIDE,
        horizon_hours=CALIBRATION_HOURS_INSIDE,
        current_qty=ORDER_QTY,
    )

    assert decision is not None
    assert decision.intent is SideIntent.FLAT
    assert decision.reason == CALIBRATION_FLATTEN


def test_the_calibration_horizon_flatten_does_not_fire_outside_the_window() -> None:
    """RED-3c. Control: the fix must not become "always flatten".

    A day out, with a position held, the horizon gate must let the decision
    reach the ordinary z-score branches -- whatever they return, it is not
    this flatten.
    """
    decision = _calibration_decision(
        hours_to_settlement=CALIBRATION_HOURS_OUTSIDE,
        horizon_hours=FROZEN_HORIZON_H,
        current_qty=ORDER_QTY,
    )

    if decision is not None:
        assert decision.reason != CALIBRATION_FLATTEN, decision.reason
