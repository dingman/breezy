"""SL-13p A-5 shadow-parity harness: native live BacktestEngine replay vs. the
pure batch path.

Ruling `docs/evidence/RULING_forecast_nbp_reopen_2026-09-29.md` §12 A-5
(binding) and plan `FORECAST_NBP_PROBABILISTIC_FAMILY_Rev3_2026-09-29.md`
§4.4. Two modes:

* ``--path live``  -- composes the real ``NbmQuantileActor``-fed
  ``ForecastQuantileStateActor`` and ``ForecastQuantileLadderStrategy`` in a
  native ``nautilus_trader`` ``BacktestEngine`` replay of the captured
  pre-freeze tape. Orders are never sent: ``ForecastQuantileLadderStrategy.
  try_submit`` never calls ``self.submit_order`` (see its own docstring),
  and this harness never even calls ``try_submit`` -- only
  ``evaluate_snapshot``, which records a SHADOW decision.
* ``--path batch`` -- delegates to :mod:`nbp_shadow_parity_pure`, which
  recomputes decisions from the same NBP rows and tape using ONLY the pure
  modules, importing neither the strategy nor the actor classes (pinned by
  ``tests/unit/test_nbp_shadow_parity_contract.py``).

Parity = decision-key set equality, mismatches = 0 (ruling §12 A-5). The
written report carries mismatch COUNTS only (plan §4.4 item 2); no P&L, no
outcome, no ev-aggregate is ever computed here (plan §4.4 items 3-4) -- this
module imports no settlement, CLI-label, or P&L module.

A strategy hook this harness had to work AROUND rather than use, without
modifying ``src/breezy/strategy/forecast_quantile_ladder``
(see :class:`_NominalWindowPermit` and :class:`_SnapshotDriverActor`):

1. ``ForecastQuantileLadderStrategy._permit_covers`` only ever checks
   ``now_ns < permit.expires_at_ns`` -- a ONE-SIDED bound. Composing it
   against the nominal ``[LAUNCH_UTC, LAUNCH_UTC + PERMIT_TTL_NS)`` window
   needs a caller-side reconstruction (see
   ``nbp_shadow_parity_pure.nominal_permit_expiry_upper_bound``); SL-13's
   real live wiring should consider a two-sided permit Protocol instead.
2. The strategy has NO ``on_data``/``on_order_book_depth`` hook that calls
   ``evaluate_snapshot`` automatically from market data -- by its own
   module docstring, "instrument subscription... is SL-13's job, not this
   slice's." This harness's :class:`_SnapshotDriverActor` stands in for
   that missing wiring so a native ``engine.run()`` still drives every
   evaluation, without editing the strategy package.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from nautilus_trader.common.actor import Actor
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.data import BookOrder, CustomData, OrderBookDepth10
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.instruments import BinaryOption, Instrument
from nautilus_trader.model.objects import Money

from breezy.domain.forecast_point import ForecastPoint
from breezy.ingest.nbm_forecast_data_type import nbm_forecast_point_data_type
from breezy.runtime.backtest_harness import BreezyBacktestConfig, build_backtest_engine
from breezy.strategy.forecast_quantile_ladder.bounds import BoundsProvider
from breezy.strategy.forecast_quantile_ladder.calibration_artefact import CalibrationArtefact
from breezy.strategy.forecast_quantile_ladder.config import ForecastQuantileLadderConfig
from breezy.strategy.forecast_quantile_ladder.decision import SidedAsk
from breezy.strategy.forecast_quantile_ladder.latch import QuantileLadderLatch
from breezy.strategy.forecast_quantile_ladder.strategy import (
    ForecastQuantileLadderStrategy,
    SupportsExpiresAtNs,
)
from breezy.strategy.ladder_ev.config import LadderEvConfig
from breezy.strategy.ladder_ev.forecast_subscriber import ForecastQuantileStateActor
from breezy.strategy.ladder_ev.quantile_density import Rung
from scripts.analysis.nbp_shadow_parity_pure import (
    DecisionKey,
    decision_key_from,
    hours_to_settlement,
    nominal_permit_expiry_upper_bound,
    parse_rung_instrument_id,
    run_batch_parity,
)

__all__ = [
    "run_batch_parity",
    "run_live_parity",
]


# ---------------------------------------------------------------------------
# The permit workaround (see module docstring, item 1).
# ---------------------------------------------------------------------------


class _NowBox:
    """A single mutable ``now_ns``, set by :class:`_SnapshotDriverActor`
    immediately before each ``evaluate_snapshot`` call and read by
    :class:`_NominalWindowPermit` -- never a Nautilus clock read, so the
    permit's notion of "now" is always EXACTLY the ``now_ns`` the snapshot
    itself is evaluated at."""

    __slots__ = ("value",)

    def __init__(self) -> None:
        self.value: int = 0


@dataclass(frozen=True, slots=True)
class _NominalWindowPermit:
    """``SupportsExpiresAtNs`` reconstructing the two-sided nominal permit
    window through the strategy's one-sided check -- see the module
    docstring, item 1, and
    ``nbp_shadow_parity_pure.nominal_permit_expiry_upper_bound``."""

    now_box: _NowBox

    @property
    def expires_at_ns(self) -> int:
        return nominal_permit_expiry_upper_bound(self.now_box.value)


def _assert_supports_expires_at_ns(permit: SupportsExpiresAtNs) -> None:
    """Fails loudly, at construction, if the Protocol shape ever drifts."""
    _ = permit.expires_at_ns


# ---------------------------------------------------------------------------
# The driver actor (see module docstring, item 2).
# ---------------------------------------------------------------------------


def _best_ask_price(asks: Sequence[BookOrder]) -> float | None:
    """First non-zero-size level. ``OrderBookDepth10`` pads to 10 levels
    with zero-size filler (``tests/support/synthetic_binary_tape.py``'s own
    convention, matched here)."""
    for order in asks:
        if order.size.as_double() > 0.0:
            return float(order.price.as_double())
    return None


class _SnapshotDriverActor(Actor):  # type: ignore[misc]
    # `Actor` resolves to `Any` under mypy for any subclass declared outside
    # `src/` (a namespace-package stub-resolution gap, not specific to this
    # file -- the identical error already exists, unsuppressed, at
    # `scripts/venue/polymarket_us_auth_smoke.py:1650`).
    """Bridges native ``BacktestEngine`` order-book delivery to
    ``ForecastQuantileLadderStrategy.evaluate_snapshot`` -- see the module
    docstring, item 2, for why this exists rather than a strategy-side hook.

    V1 scope (stated, not hidden -- matches
    ``nbp_shadow_parity_pure.run_batch_parity``'s own note): drives
    ``side="yes"`` only, one evaluation per depth frame with a genuine ask.
    """

    def __init__(
        self,
        *,
        strategy: ForecastQuantileLadderStrategy,
        now_box: _NowBox,
        instrument_ids: Sequence[str],
        ladder_by_key: Mapping[tuple[str, date], Sequence[Rung]],
        fee_coefficient: float,
        slippage_floor_prob: float,
        std_utc_offset_hours_by_station: Mapping[str, float],
        on_decision: Callable[[DecisionKey], None],
    ) -> None:
        super().__init__()
        self._strategy = strategy
        self._now_box = now_box
        self._instrument_ids = tuple(instrument_ids)
        self._ladder_by_key = ladder_by_key
        self._fee_coefficient = fee_coefficient
        self._slippage_floor_prob = slippage_floor_prob
        self._std_utc_offset_hours_by_station = std_utc_offset_hours_by_station
        self._on_decision = on_decision

    def on_start(self) -> None:
        for instrument_id in self._instrument_ids:
            self.subscribe_order_book_depth(InstrumentId.from_str(instrument_id))

    def on_order_book_depth(self, depth: OrderBookDepth10) -> None:
        instrument_id = str(depth.instrument_id)
        station, climate_day, rung_id = parse_rung_instrument_id(instrument_id)
        best_ask = _best_ask_price(depth.asks)
        if best_ask is None:
            return
        ladder = self._ladder_by_key[(station, climate_day)]
        std_utc_offset_hours = self._std_utc_offset_hours_by_station[station]
        now_ns = depth.ts_event
        self._now_box.value = now_ns
        h_hours = hours_to_settlement(
            now_ns=now_ns, climate_day=climate_day, std_utc_offset_hours=std_utc_offset_hours,
        )
        decision = self._strategy.evaluate_snapshot(
            now_ns=now_ns,
            std_utc_offset_hours=std_utc_offset_hours,
            station=station,
            climate_day=climate_day,
            ladder=ladder,
            rung_id=rung_id,
            side="yes",
            ask=SidedAsk(side="yes", instrument_id=instrument_id, price=best_ask),
            fee_coefficient=self._fee_coefficient,
            slippage_floor_prob=self._slippage_floor_prob,
            h_hours=h_hours,
        )
        self._on_decision(
            decision_key_from(
                decision,
                station=station,
                climate_day=climate_day,
                rung_id=rung_id,
                side="yes",
                ts_ns=now_ns,
            ),
        )


# ---------------------------------------------------------------------------
# The live path.
# ---------------------------------------------------------------------------


def run_live_parity(
    *,
    instruments: Sequence[BinaryOption],
    market_data: Sequence[OrderBookDepth10],
    forecast_points: Sequence[ForecastPoint],
    ladder_by_key: Mapping[tuple[str, date], Sequence[Rung]],
    artefact: CalibrationArtefact,
    ladder_cfg: LadderEvConfig,
    bounds_provider: BoundsProvider,
    fee_coefficient: float,
    slippage_floor_prob: float,
    std_utc_offset_hours_by_station: Mapping[str, float],
    stations: Sequence[str],
) -> tuple[DecisionKey, ...]:
    """Compose the NBP actor and the strategy in a native ``BacktestEngine``
    replay; return the shadow decision-key log.

    Never submits an order: only ``evaluate_snapshot`` is called (via
    :class:`_SnapshotDriverActor`), and ``try_submit`` is never invoked at
    all -- "orders refused (no permit)" per the brief is therefore true both
    ways (no permit reaches ``try_submit``, and ``try_submit`` itself is
    dead code on this path).
    """
    instrument_ids = [str(instrument.id) for instrument in instruments]
    weather_data = [
        CustomData(data_type=nbm_forecast_point_data_type(), data=point)
        for point in forecast_points
    ]
    config = BreezyBacktestConfig(
        instruments=list[Instrument](instruments),
        market_data=list(market_data),
        settlement_prices={},
        starting_balances=[Money(10_000, USD)],
        weather_data=weather_data,
        instruments_without_close=frozenset(
            InstrumentId.from_str(instrument_id) for instrument_id in instrument_ids
        ),
    )

    now_box = _NowBox()
    permit = _NominalWindowPermit(now_box=now_box)
    _assert_supports_expires_at_ns(permit)

    quantile_actor = ForecastQuantileStateActor(
        stations=tuple(stations), std_utc_offset_hours=std_utc_offset_hours_by_station,
    )
    latch = QuantileLadderLatch()
    strategy_config = ForecastQuantileLadderConfig(
        stations=tuple(stations),
        calibration_artefact_path="",
        calibration_artefact_sha256=artefact.sha256,
        required_fee_coefficient=fee_coefficient,
    )
    strategy = ForecastQuantileLadderStrategy(
        strategy_config,
        quantile_actor=quantile_actor,
        artefact=artefact,
        ladder_cfg=ladder_cfg,
        bounds_provider=bounds_provider,
        latch=latch,
        order_submission_permit=permit,
    )

    keys: list[DecisionKey] = []
    driver = _SnapshotDriverActor(
        strategy=strategy,
        now_box=now_box,
        instrument_ids=instrument_ids,
        ladder_by_key=ladder_by_key,
        fee_coefficient=fee_coefficient,
        slippage_floor_prob=slippage_floor_prob,
        std_utc_offset_hours_by_station=std_utc_offset_hours_by_station,
        on_decision=keys.append,
    )

    engine = build_backtest_engine(config)
    try:
        engine.add_actor(quantile_actor)
        engine.add_actor(driver)
        engine.add_strategy(strategy)
        engine.run()
    finally:
        engine.dispose()

    return tuple(keys)


# ---------------------------------------------------------------------------
# CLI (production I/O -- disk reads only; every pure/composition function
# above is exercised directly by the test suite without touching disk).
# ---------------------------------------------------------------------------


def _load_ladder_fixture(path: Path) -> dict[tuple[str, date], tuple[Rung, ...]]:
    """``{"STATION|YYYY-MM-DD": [{"rung_id": ..., "lo": ..., "hi": ...}, ...]}``."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    ladder_by_key: dict[tuple[str, date], tuple[Rung, ...]] = {}
    for key, rungs in raw.items():
        station, day_text = key.split("|", 1)
        climate_day = date.fromisoformat(day_text)
        ladder_by_key[(station, climate_day)] = tuple(
            Rung(rung_id=entry["rung_id"], lo=entry["lo"], hi=entry["hi"]) for entry in rungs
        )
    return ladder_by_key


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", choices=("live", "batch"), required=True)
    parser.add_argument("--ladder-fixture", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Thin CLI entry point.

    Production disk-reading (the quote-tape ``ParquetDataCatalog``, the NBP
    derived store, and a sha-pinned calibration artefact) is deliberately
    NOT wired into this stub -- the SL-13p brief supplies fixtures for
    every test, and the backfill this harness would read from is still
    running (brief). ``--ladder-fixture`` is the one piece of glue exercised
    here; the two composition functions above (:func:`run_live_parity`,
    ``nbp_shadow_parity_pure.run_batch_parity``) are the tested surface.
    """
    args = _parse_args(argv)
    _load_ladder_fixture(args.ladder_fixture)
    raise NotImplementedError(
        f"--path {args.path}: production catalog/NBP-store wiring is not yet "
        f"connected in this stub; call run_live_parity/run_batch_parity "
        f"directly, or extend main() once the NBP backfill and a registered "
        f"calibration artefact exist",
    )


if __name__ == "__main__":
    raise SystemExit(main())
