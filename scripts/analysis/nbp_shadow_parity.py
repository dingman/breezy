"""SL-13p A-5 shadow-parity harness: native live BacktestEngine replay vs. the
pure batch path.

Ruling `docs/evidence/RULING_forecast_nbp_reopen_2026-09-29.md` §12 A-5
(binding) and plan `FORECAST_NBP_PROBABILISTIC_FAMILY_Rev3_2026-09-29.md`
§4.4. Two modes:

* the LIVE path composes the real ``ForecastQuantileStateActor`` and
  ``ForecastQuantileLadderStrategy`` in a native ``nautilus_trader``
  ``BacktestEngine`` replay of the captured pre-freeze tape. Orders are
  never sent: the strategy runs with an always-refusing submit veto, so a
  shadow ``Take`` still stops before ``submit_order``.
* ``--path batch`` -- delegates to :mod:`nbp_shadow_parity_pure`, which
  recomputes decisions from the same NBP rows and tape using ONLY the pure
  modules, importing neither the strategy nor the actor classes (pinned by
  ``tests/unit/test_nbp_shadow_parity_contract.py``).

Parity = decision-key set equality, mismatches = 0 (ruling §12 A-5). The
written report carries mismatch COUNTS only (plan §4.4 item 2); no P&L, no
outcome, no ev-aggregate is ever computed here (plan §4.4 items 3-4) -- this
module imports no settlement, CLI-label, or P&L module.

``ForecastQuantileLadderStrategy._permit_covers`` only checks the permit's
``expires_at_ns`` upper bound. This harness preserves the pre-existing permit
stub shape, while the actual tick evaluation is now driven by the strategy's
real ``on_order_book_depth`` handler.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Literal, SupportsFloat, SupportsIndex, SupportsInt, cast

from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.data import BookOrder, CustomData, OrderBookDepth10
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.instruments import BinaryOption, Instrument
from nautilus_trader.model.objects import Money

from breezy.adapters.polymarket_us.symbology import leg_of, sibling_instrument_id
from breezy.domain.forecast_point import ForecastPoint
from breezy.domain.weather_bucket_facts import WeatherFactsUnavailableError, read_weather_bucket_facts
from breezy.ingest.nbm_forecast_data_type import nbm_forecast_point_data_type
from breezy.persistence.nbp_derived_store import read_partition
from breezy.runtime.backtest_harness import BreezyBacktestConfig, build_backtest_engine
from breezy.runtime.settings import SettingsError, load_quote_tape_settings
from breezy.registry.sites import default_registry
from breezy.strategy.forecast_quantile_ladder.bounds import BoundsProvider, RungBounds
from breezy.strategy.forecast_quantile_ladder.artefact_bounds import (
    BoundsArtefactPinMismatchError,
    load_bounds_artefact_draws,
)
from breezy.strategy.forecast_quantile_ladder.calibration_artefact import (
    CalibrationArtefact,
    CalibrationArtefactPinMismatchError,
    load_calibration_artefact,
)
from breezy.strategy.forecast_quantile_ladder.config import ForecastQuantileLadderConfig
from breezy.strategy.forecast_quantile_ladder.latch import QuantileLadderLatch
from breezy.strategy.forecast_quantile_ladder.strategy import (
    ForecastQuantileLadderStrategy,
    ShadowDecisionLogLine,
    SupportsExpiresAtNs,
)
from breezy.strategy.ladder_ev.config import LadderEvConfig
from breezy.strategy.ladder_ev.forecast_subscriber import ForecastQuantileStateActor
from breezy.strategy.ladder_ev.quantile_density import Rung, rung_probabilities
from scripts.analysis.nbp_shadow_parity_pure import (
    DecisionKey,
    DepthSnapshotRow,
    NbpQuantileRow,
    PostFreezeTapeRefusedError,
    assert_pre_freeze_tape_day,
    diff_decision_keys,
    nominal_permit_expiry_upper_bound,
    run_batch_parity,
)

_Side = Literal["yes", "no"]
_IntLike = str | bytes | bytearray | SupportsInt | SupportsIndex
_FloatLike = str | bytes | bytearray | SupportsFloat | SupportsIndex

__all__ = [
    "run_batch_parity",
    "run_live_parity",
]


# ---------------------------------------------------------------------------
# The permit workaround (see module docstring, item 1).
# ---------------------------------------------------------------------------


class _NowBox:
    """A single mutable ``now_ns`` read by :class:`_NominalWindowPermit`."""

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


def _best_ask_price(asks: Sequence[BookOrder]) -> float | None:
    """First non-zero-size level. ``OrderBookDepth10`` pads to 10 levels
    with zero-size filler (``tests/support/synthetic_binary_tape.py``'s own
    convention, matched here)."""
    for order in asks:
        if order.size.as_double() > 0.0:
            return float(order.price.as_double())
    return None


def _rung_id_from_bounds(lower_f: int | None, upper_f: int | None) -> str:
    return f"{lower_f if lower_f is not None else 'lt'}_{upper_f if upper_f is not None else 'gte'}"


def _trusted_side(value: object) -> _Side:
    return cast("_Side", str(value))


def _trusted_int(value: object) -> int:
    return int(cast("_IntLike", value))


def _trusted_float_or_none(value: object | None) -> float | None:
    if value is None:
        return None
    return float(cast("_FloatLike", value))


def _shadow_log_key(line: ShadowDecisionLogLine) -> DecisionKey:
    climate_day_raw = line["climate_day"]
    climate_day = (
        climate_day_raw
        if isinstance(climate_day_raw, date)
        else date.fromisoformat(str(climate_day_raw))
    )
    ev_net = line.get("ev_net")
    p_hat = line.get("p_hat")
    p_lower = line.get("p_lower")
    p_upper = line.get("p_upper")
    return DecisionKey(
        station=str(line["station"]),
        climate_day=climate_day,
        rung_id=str(line["rung_id"]),
        instrument_id=str(line["instrument_id"]),
        side=_trusted_side(line["side"]),
        action=str(line["kind"]),
        reason=None if "reason" not in line else str(line["reason"]),
        ts_ns=_trusted_int(line["now_ns"]),
        ev_net=_trusted_float_or_none(ev_net),
        p_hat=_trusted_float_or_none(p_hat),
        p_lower=_trusted_float_or_none(p_lower),
        p_upper=_trusted_float_or_none(p_upper),
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
    quantile_station_keys: Mapping[str, str] | None = None,
) -> tuple[DecisionKey, ...]:
    """Compose the NBP actor and the strategy in a native ``BacktestEngine``
    replay; return the shadow decision-key log.

    Never submits an order: ``submit_veto`` always refuses after
    ``evaluate_snapshot`` records the shadow decision, so a ``Take`` remains
    observable without reaching ``submit_order``.
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
    for depth in market_data:
        now_box.value = max(now_box.value, depth.ts_event)
    permit = _NominalWindowPermit(now_box=now_box)
    _assert_supports_expires_at_ns(permit)

    station_key_map = quantile_station_keys if quantile_station_keys is not None else {}
    forecast_stations = tuple(station_key_map.get(station, station) for station in stations)
    std_offset_by_forecast_station = {
        station_key_map.get(station, station): offset
        for station, offset in std_utc_offset_hours_by_station.items()
    }
    quantile_actor = ForecastQuantileStateActor(
        stations=forecast_stations, std_utc_offset_hours=std_offset_by_forecast_station,
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
        submit_veto=lambda: "shadow_parity_harness",
        instrument_ids=tuple(instrument_ids),
        quantile_station_keys=station_key_map,
    )

    engine = build_backtest_engine(config)
    try:
        engine.add_actor(quantile_actor)
        engine.add_strategy(strategy)
        engine.run()
    finally:
        engine.dispose()

    return tuple(_shadow_log_key(line) for line in strategy.shadow_decisions)


# ---------------------------------------------------------------------------
# CLI (production I/O -- disk reads only).
# ---------------------------------------------------------------------------


def _assert_pre_freeze_range(start: date, end: date) -> None:
    if end < start:
        raise ValueError(f"end-date {end.isoformat()} is before start-date {start.isoformat()}")
    assert_pre_freeze_tape_day(start)
    assert_pre_freeze_tape_day(end)


def _point_bounds_provider(
    *, cdf: Callable[[float], float], ladder: Sequence[Rung], rung_id: str,
) -> RungBounds:
    probabilities = rung_probabilities(cdf, ladder)
    p_hat = probabilities[rung_id]
    return RungBounds(p_hat=p_hat, p_lower=p_hat, p_upper=p_hat)


def _load_nbp_rows(root: Path, *, start: date, end: date) -> tuple[NbpQuantileRow, ...]:
    rows: list[NbpQuantileRow] = []
    for path in sorted(root.rglob("*.parquet")):
        for row in read_partition(path):
            climate_day = datetime.fromtimestamp(row.valid_start_ns / 1_000_000_000, tz=UTC).date()
            if start <= climate_day <= end:
                rows.append(
                    NbpQuantileRow(
                        station=row.station,
                        variable=row.variable,
                        cycle_runtime_ns=row.cycle_runtime_ns,
                        value_f=row.value_f,
                        available_at_ns=row.available_at_ns,
                        climate_day=climate_day,
                    ),
                )
    return tuple(rows)


def _load_catalog_inputs(
    catalog_root: Path, *, start: date, end: date,
) -> tuple[
    tuple[BinaryOption, ...],
    tuple[OrderBookDepth10, ...],
    tuple[DepthSnapshotRow, ...],
    dict[tuple[str, date], tuple[Rung, ...]],
    dict[str, float],
    dict[str, str],
]:
    catalog = ParquetDataCatalog(str(catalog_root))
    instruments = tuple(catalog.query(data_cls=BinaryOption))
    depths = tuple(catalog.query(data_cls=OrderBookDepth10))
    facts_by_id: dict[str, tuple[str, date, str, _Side]] = {}
    ladder_by_key: dict[tuple[str, date], list[Rung]] = {}
    for instrument in instruments:
        try:
            facts = read_weather_bucket_facts(instrument.info)
        except WeatherFactsUnavailableError:
            continue
        side = _trusted_side(leg_of(instrument.id))
        rung_id = _rung_id_from_bounds(facts.lower_f, facts.upper_f)
        facts_by_id[str(instrument.id)] = (
            facts.settlement_station,
            facts.climate_day,
            rung_id,
            side,
        )
        if side == "yes":
            no_id = sibling_instrument_id(instrument.id)
            facts_by_id[str(no_id)] = (facts.settlement_station, facts.climate_day, rung_id, "no")
        ladder_by_key.setdefault((facts.settlement_station, facts.climate_day), []).append(
            Rung(rung_id=rung_id, lo=facts.lower_f, hi=facts.upper_f),
        )

    filtered_depths: list[OrderBookDepth10] = []
    batch_rows: list[DepthSnapshotRow] = []
    for depth in sorted(depths, key=lambda item: item.ts_event):
        context = facts_by_id.get(str(depth.instrument_id))
        if context is None:
            continue
        station, climate_day, rung_id, context_side = context
        if not (start <= climate_day <= end):
            continue
        assert_pre_freeze_tape_day(climate_day)
        best_ask = _best_ask_price(depth.asks)
        filtered_depths.append(depth)
        batch_rows.append(
            DepthSnapshotRow(
                instrument_id=str(depth.instrument_id),
                ts_ns=depth.ts_event,
                best_ask_price=best_ask,
                best_ask_size=None,
                station=station,
                climate_day=climate_day,
                rung_id=rung_id,
                side=context_side,
            ),
        )

    registry = default_registry()
    stations = sorted({station for station, _day in ladder_by_key})
    std_offsets = {
        station: registry.climate_day_window("polymarket_us", station).std_utc_offset_hours
        for station in stations
    }
    quantile_station_keys = {
        station: registry.settlement_site("polymarket_us", station).icao for station in stations
    }
    return (
        instruments,
        tuple(filtered_depths),
        tuple(batch_rows),
        {key: tuple(value) for key, value in ladder_by_key.items()},
        std_offsets,
        quantile_station_keys,
    )


def _write_report(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _load_ladder_fixture(path: Path) -> dict[tuple[str, date], tuple[Rung, ...]]:
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
    parser.add_argument("--start-date", type=date.fromisoformat, required=True)
    parser.add_argument("--end-date", type=date.fromisoformat, required=True)
    parser.add_argument("--nbp-derived-root", type=Path, required=True)
    parser.add_argument("--calibration-artefact", type=Path, required=True)
    parser.add_argument("--calibration-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        _assert_pre_freeze_range(args.start_date, args.end_date)
        artefact = load_calibration_artefact(
            str(args.calibration_artefact), expected_sha256=args.calibration_sha256,
        )
        load_bounds_artefact_draws(
            str(args.calibration_artefact), expected_sha256=args.calibration_sha256,
        )
        quote_settings = load_quote_tape_settings()
        (
            instruments,
            market_data,
            depth_rows,
            ladder_by_key,
            std_offsets,
            quantile_station_keys,
        ) = _load_catalog_inputs(
            quote_settings.catalog_root, start=args.start_date, end=args.end_date,
        )
        nbp_rows = _load_nbp_rows(args.nbp_derived_root, start=args.start_date, end=args.end_date)
        live = run_live_parity(
            instruments=instruments,
            market_data=market_data,
            forecast_points=tuple(
                ForecastPoint(
                    station=row.station,
                    model="NBM_NBP",
                    model_version="stored",
                    variable=row.variable,
                    cycle_runtime_ns=row.cycle_runtime_ns,
                    valid_start_ns=row.cycle_runtime_ns,
                    valid_end_ns=row.cycle_runtime_ns,
                    value_f=row.value_f,
                    issuance_seq=0,
                    measured_publication_lag_ns=max(0, row.available_at_ns - row.cycle_runtime_ns),
                    available_at_ns=row.available_at_ns,
                    ingested_at_ns=row.available_at_ns,
                )
                for row in nbp_rows
            ),
            ladder_by_key=ladder_by_key,
            artefact=artefact,
            ladder_cfg=LadderEvConfig(),
            bounds_provider=_point_bounds_provider,
            fee_coefficient=0.0695,
            slippage_floor_prob=0.0,
            std_utc_offset_hours_by_station=std_offsets,
            stations=tuple(std_offsets),
            quantile_station_keys=quantile_station_keys,
        )
        batch = run_batch_parity(
            depth_snapshots=depth_rows,
            nbp_rows=nbp_rows,
            ladder_by_key=ladder_by_key,
            artefact=artefact,
            ladder_cfg=LadderEvConfig(),
            bounds_provider=_point_bounds_provider,
            fee_coefficient=0.0695,
            slippage_floor_prob=0.0,
            std_utc_offset_hours_by_station=std_offsets,
            quantile_station_keys=quantile_station_keys,
        )
        report = diff_decision_keys(live, batch)
        _write_report(args.output, report.to_counts_dict())
    except (
        BoundsArtefactPinMismatchError,
        CalibrationArtefactPinMismatchError,
        OSError,
        PostFreezeTapeRefusedError,
        SettingsError,
        ValueError,
    ):
        return 2
    return 1 if report.n_mismatches else 0


if __name__ == "__main__":
    raise SystemExit(main())
