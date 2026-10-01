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
real ``on_order_book_depth`` handler. Review item 2 (SL-13p2): the permit's
``now_ns`` reader is bound to the strategy's own native engine clock (never a
value captured once before the run) -- see :class:`_NowBox`. That clock is
``ts_init``; :func:`_depth_clocked_at_decision_instant` stamps it onto
``ts_event`` so the one-sided check is the decision instant (spec check 4).
"""

from __future__ import annotations

import argparse
import gc
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, Literal, SupportsFloat, SupportsIndex, SupportsInt, cast

import msgspec

from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.data import BookOrder, CustomData, OrderBookDepth10
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.instruments import BinaryOption, Instrument
from nautilus_trader.model.objects import Money

from breezy.adapters.polymarket_us.symbology import (
    leg_of,
    parse_weather_slug,
    sibling_instrument_id,
)
from breezy.domain.forecast_point import ForecastPoint
from breezy.domain.weather_bucket_facts import WeatherFactsUnavailableError, read_weather_bucket_facts
from breezy.ingest.nbm_forecast_data_type import nbm_forecast_point_data_type
from breezy.ingest.nbm_quantile_parse import NbpQuantilePoint, max_column_lst_climate_day
from breezy.persistence.family_manifest import load_family_manifest
from breezy.persistence.nbp_derived_store import DerivedNbpRow, read_partition
from breezy.runtime.backtest_harness import BreezyBacktestConfig, build_backtest_engine
from breezy.runtime.settings import SettingsError, load_quote_tape_settings
from breezy.registry.sites import default_registry
from breezy.strategy.forecast_quantile_ladder.bounds import BoundsProvider
from breezy.strategy.forecast_quantile_ladder.artefact_bounds import ArtefactBoundsProvider
from breezy.strategy.forecast_quantile_ladder.calibration_artefact import (
    CalibrationArtefactPinMismatchError,
    LiveCalibration,
    load_live_calibration,
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
from breezy.strategy.ladder_ev.quantile_density import Rung
from scripts.analysis.nbp_shadow_parity_pure import (
    BatchCalibration,
    DecisionKey,
    DepthSnapshotRow,
    NbpQuantileRow,
    ParityReport,
    PostFreezeTapeRefusedError,
    assert_pre_freeze_tape_day,
    diff_decision_keys,
    no_depth_census,
    nominal_permit_expiry_upper_bound,
    run_batch_parity,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from nautilus_trader.common.component import Clock

_Side = Literal["yes", "no"]
_IntLike = str | bytes | bytearray | SupportsInt | SupportsIndex
_FloatLike = str | bytes | bytearray | SupportsFloat | SupportsIndex

# Measured on this quote-tape catalog: depth filenames sit in [-14.2h, +43.8h]
# of the slug climate date, instrument files in [-14.0h, +32.1h]. The pad is
# wider than both, so the ts_init bound keeps every row the climate-day
# predicate already keeps. Nautilus names the filter `identifiers`.
_QUERY_PAD_BEFORE = timedelta(days=2)
_QUERY_PAD_AFTER = timedelta(days=3)
_NBP_CYCLE_FILE = re.compile(r"nbp_(\d{4})(\d{2})(\d{2})_\d{2}z\.parquet\Z")
_NO_LEG_DIR_SUFFIX = "^no"
_FAMILY_MANIFEST_NAME: Final[str] = "pm_us_crh_fq_v1.json"

__all__ = [
    "run_batch_parity",
    "run_live_parity",
]


# ---------------------------------------------------------------------------
# The permit workaround (see module docstring, item 1).
# ---------------------------------------------------------------------------


class _NowBox:
    """Review item 2 (SL-13p2): bound to the ENGINE's own native clock once
    the strategy that owns it is registered (:func:`run_live_parity`), never
    a single ``now_ns`` captured once before the run.

    The previous shape set ``value`` ONCE, to the max ``ts_event`` across the
    whole tape, before ``engine.run()`` -- so :class:`_NominalWindowPermit`
    handed the strategy the SAME ``expires_at_ns`` for every tick regardless
    of that tick's own timestamp, making an early, pre-window tick appear
    covered by a window computed from the LAST tick in the run.

    ``BacktestEngine`` advances a strategy's own ``self.clock`` (a
    ``TestClock``) to the data's ``ts_init`` before dispatching the handler
    (``engine.pyx`` ``_advance_time(data.ts_init)``). The strategy then
    evaluates at ``ts_event``. Those differ on the captured tape, and the
    one-sided permit stub returns this clock time when it is outside the
    window, so ``ts_event < ts_init`` false-covers a pre-window tick.
    :func:`_depth_clocked_at_decision_instant` stamps ``ts_init`` onto
    ``ts_event`` before ``engine.run()``, which makes this clock the
    decision instant the stub was written against. Reading it HERE, at
    ``expires_at_ns`` access time (called from inside
    ``evaluate_snapshot`` -> ``_permit_covers``, synchronously within that
    SAME tick's handler call), is therefore tick-local: the CURRENTLY
    processing event's decision instant, never a value fixed ahead of the run.
    """

    __slots__ = ("_clock",)

    def __init__(self) -> None:
        self._clock: Clock | None = None

    def bind(self, clock: Clock) -> None:
        self._clock = clock

    @property
    def now_ns(self) -> int:
        if self._clock is None:
            raise RuntimeError(
                "_NowBox.bind(clock) must be called (after engine.add_strategy) "
                "before any expires_at_ns read",
            )
        return int(self._clock.timestamp_ns())


@dataclass(frozen=True, slots=True)
class _NominalWindowPermit:
    """``SupportsExpiresAtNs`` reconstructing the two-sided nominal permit
    window through the strategy's one-sided check -- see the module
    docstring, item 1, and
    ``nbp_shadow_parity_pure.nominal_permit_expiry_upper_bound``."""

    now_box: _NowBox

    @property
    def expires_at_ns(self) -> int:
        return nominal_permit_expiry_upper_bound(self.now_box.now_ns)


def _assert_supports_expires_at_ns(permit: SupportsExpiresAtNs) -> None:
    """Fails loudly, at construction, if the Protocol shape ever drifts."""
    _ = permit.expires_at_ns


def _depth_clocked_at_decision_instant(depth: OrderBookDepth10) -> OrderBookDepth10:
    """Stamp ``ts_init`` onto ``ts_event`` so the engine clock is the decision instant.

    Nautilus clocks to ``ts_init``. ``_permit_covers`` compares ``ts_event``
    with a stub expiry read off that clock, and outside the window the stub
    returns the clock time. ``ts_event < ts_init`` then reads as covered.
    Spec check (4) is ``NotExecutable`` at the decision instant. The shadow
    key stays ``ts_event``. Same object when the timestamps already agree.
    """
    if depth.ts_init == depth.ts_event:
        return depth
    return OrderBookDepth10(
        instrument_id=depth.instrument_id,
        bids=depth.bids,
        asks=depth.asks,
        bid_counts=depth.bid_counts,
        ask_counts=depth.ask_counts,
        flags=depth.flags,
        sequence=depth.sequence,
        ts_event=depth.ts_event,
        ts_init=depth.ts_event,
    )


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
    calibration: LiveCalibration,
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
    # A station with no LST offset cannot be served. The manifest allowlist
    # may name cities this tape does not; an empty intersection is no decisions,
    # not an actor that refuses to construct.
    stations = tuple(
        station for station in stations if station in std_utc_offset_hours_by_station
    )
    if not stations:
        return ()
    instrument_ids = [str(instrument.id) for instrument in instruments]
    market_data = [
        _depth_clocked_at_decision_instant(depth) for depth in market_data
    ]
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
        calibration_artefact_sha256=calibration.sha256,
        required_fee_coefficient=fee_coefficient,
    )
    # Review item 4 (SL-13p2): the strategy no longer retains a
    # `shadow_decisions` list -- every evaluated snapshot is emitted to the
    # injected sink instead. This harness's OWN records list is its
    # observability surface, never a strategy attribute.
    shadow_records: list[ShadowDecisionLogLine] = []
    # A-6 has no slippage term. The explicit argument wins over
    # LadderEvConfig's 0.01 default, which the strategy reads at evaluate.
    applied_ladder_cfg = msgspec.structs.replace(
        ladder_cfg, slippage_floor_prob=slippage_floor_prob,
    )
    strategy = ForecastQuantileLadderStrategy(
        strategy_config,
        quantile_actor=quantile_actor,
        calibration=calibration,
        ladder_cfg=applied_ladder_cfg,
        bounds_provider=bounds_provider,
        latch=latch,
        order_submission_permit=permit,
        submit_veto=lambda: "shadow_parity_harness",
        instrument_ids=tuple(instrument_ids),
        quantile_station_keys=station_key_map,
        shadow_decision_sink=shadow_records.append,
    )

    engine = build_backtest_engine(config)
    try:
        engine.add_actor(quantile_actor)
        engine.add_strategy(strategy)
        # Review item 2: bind the permit's clock reader to the strategy's
        # OWN native clock only now that `add_strategy` has replaced the
        # placeholder `Clock` with the engine's real `TestClock` -- doing
        # this any earlier would bind an unusable clock; doing it via a
        # value captured before `engine.run()` is exactly the bug this item
        # fixes.
        now_box.bind(strategy.clock)
        _assert_supports_expires_at_ns(permit)
        engine.run()
    finally:
        engine.dispose()

    return tuple(_shadow_log_key(line) for line in shadow_records)


# ---------------------------------------------------------------------------
# CLI (production I/O -- disk reads only).
# ---------------------------------------------------------------------------


def _assert_pre_freeze_range(start: date, end: date) -> None:
    if end < start:
        raise ValueError(f"end-date {end.isoformat()} is before start-date {start.isoformat()}")
    assert_pre_freeze_tape_day(start)
    assert_pre_freeze_tape_day(end)


def _std_offset_hours_by_icao() -> dict[str, float]:
    """ICAO -> fixed standard-time offset, from the polymarket_us registry."""
    registry = default_registry()
    offsets: dict[str, float] = {}
    for venue, city in registry.pairs():
        if venue != "polymarket_us":
            continue
        site = registry.settlement_site(venue, city)
        offsets[site.icao] = registry.climate_day_window(venue, city).std_utc_offset_hours
    return offsets


def _load_nbp_rows(root: Path, *, start: date, end: date) -> tuple[NbpQuantileRow, ...]:
    """Nearest MAX column per (station, variable, cycle), then LST climate day.

    Same nearest rule as ``nbm_quantile_actor._nearest_per_station_variable``
    (smallest ``valid_start_ns``); the cycle is part of the key because this
    loader spans cycles. ``climate_day`` comes from
    ``max_column_lst_climate_day``, not the UTC date of ``valid_start_ns``.
    A cycle is kept only when that nearest column's climate day is inside
    ``[start, end]``. A later lead is never substituted.
    """
    nearest: dict[tuple[str, str, int], DerivedNbpRow] = {}
    for path in sorted(root.rglob("*.parquet")):
        if not _nbp_cycle_file_in_window(path, start=start, end=end):
            continue
        for row in read_partition(path):
            key = (row.station, row.variable, row.cycle_runtime_ns)
            current = nearest.get(key)
            if current is None or row.valid_start_ns < current.valid_start_ns:
                nearest[key] = row
    offsets = _std_offset_hours_by_icao()
    loaded: list[NbpQuantileRow] = []
    for row in nearest.values():
        offset = offsets.get(row.station)
        if offset is None:
            raise ValueError(
                f"no polymarket_us std_utc_offset_hours for NBP station {row.station!r}",
            )
        point = NbpQuantilePoint(
            station=row.station,
            model_version=row.header_model_version,
            cycle_runtime_ns=row.cycle_runtime_ns,
            variable=row.variable,
            valid_start_ns=row.valid_start_ns,
            valid_end_ns=row.valid_end_ns,
            value_f=row.value_f,
            absence_reason=row.absence_reason,
        )
        climate_day = max_column_lst_climate_day(point, std_utc_offset_hours=offset)
        if not (start <= climate_day <= end):
            continue
        loaded.append(
            NbpQuantileRow(
                station=row.station,
                variable=row.variable,
                cycle_runtime_ns=row.cycle_runtime_ns,
                valid_start_ns=row.valid_start_ns,
                valid_end_ns=row.valid_end_ns,
                value_f=row.value_f,
                available_at_ns=row.available_at_ns,
                climate_day=climate_day,
                header_model_version=row.header_model_version,
            ),
        )
    return tuple(loaded)


def _nbp_cycle_file_in_window(path: Path, *, start: date, end: date) -> bool:
    """Cycle files outside this pad cannot yield an LST D+1 day inside [start, end].

    ``max_column_lst_climate_day`` is the cycle's local date plus one, not a
    later lead. US standard offsets are negative, so the cycle instant falls
    on the climate day or the day before. A name that is not a cycle file is
    read, not skipped.
    """
    match = _NBP_CYCLE_FILE.search(path.name)
    if match is None:
        return True
    cycle_day = date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    return (start - timedelta(days=3)) <= cycle_day <= (end + timedelta(days=1))


def _inclusive_days(start: date, end: date) -> tuple[date, ...]:
    days: list[date] = []
    day = start
    while day <= end:
        days.append(day)
        day += timedelta(days=1)
    return tuple(days)


def _tape_query_bounds(start: date, end: date) -> tuple[datetime, datetime]:
    """Inclusive ts_init window covering every file of these climate days."""
    start_ts = datetime(start.year, start.month, start.day, tzinfo=timezone.utc) - _QUERY_PAD_BEFORE
    end_ts = datetime(end.year, end.month, end.day, tzinfo=timezone.utc) + _QUERY_PAD_AFTER
    return start_ts, end_ts


def _climate_day_from_catalog_id(name: str) -> date | None:
    """Slug climate date embedded in a catalog instrument-id directory name."""
    symbol = name.split(".", 1)[0]
    if symbol.endswith(_NO_LEG_DIR_SUFFIX):
        symbol = symbol[: -len(_NO_LEG_DIR_SUFFIX)]
    parsed = parse_weather_slug(symbol)
    if parsed is None:
        return None
    return date.fromisoformat(parsed.climate_date)


def _binary_option_root(catalog_root: Path) -> Path:
    return catalog_root / "data" / "binary_option"


def _instrument_ids_in_window(catalog_root: Path, *, start: date, end: date) -> tuple[str, ...]:
    """Per-instrument directory names whose slug climate date is in [start, end]."""
    root = _binary_option_root(catalog_root)
    if not root.is_dir():
        return ()
    chosen: list[str] = []
    for entry in root.iterdir():
        if not entry.is_dir():
            continue
        climate_day = _climate_day_from_catalog_id(entry.name)
        if climate_day is not None and start <= climate_day <= end:
            chosen.append(entry.name)
    chosen.sort()
    return tuple(chosen)


def _loose_binary_option_files(catalog_root: Path) -> tuple[str, ...]:
    """Top-level instrument parquet not partitioned into an id directory.

    Early Aug 30-31 captures live only in these files. They are tiny; the
    climate-day predicate still drops rows outside [start, end].
    """
    root = _binary_option_root(catalog_root)
    if not root.is_dir():
        return ()
    return tuple(
        sorted(str(entry) for entry in root.iterdir() if entry.is_file() and entry.suffix == ".parquet"),
    )


def _merge_parity_reports(reports: Sequence[ParityReport]) -> ParityReport:
    """Sum per-day reports. Identity keys include climate_day, so days are disjoint."""
    if not reports:
        return diff_decision_keys((), ())
    side_counts: dict[str, int] = {}
    for report in reports:
        for key, value in report.side_kind_counts.items():
            side_counts[key] = side_counts.get(key, 0) + value
    return ParityReport(
        n_live=sum(report.n_live for report in reports),
        n_batch=sum(report.n_batch for report in reports),
        n_matched=sum(report.n_matched for report in reports),
        live_only=tuple(key for report in reports for key in report.live_only),
        batch_only=tuple(key for report in reports for key in report.batch_only),
        side_kind_counts=side_counts,
        numeric_mismatches=tuple(
            pair for report in reports for pair in report.numeric_mismatches
        ),
    )


def _merge_no_depth_census(parts: Sequence[Mapping[str, int]]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for part in parts:
        for station, count in part.items():
            totals[station] = totals.get(station, 0) + count
    return {station: totals[station] for station in sorted(totals)}


def _forecast_points(nbp_rows: Sequence[NbpQuantileRow]) -> tuple[ForecastPoint, ...]:
    return tuple(
        ForecastPoint(
            station=row.station,
            model="NBM_NBP",
            model_version=row.header_model_version,
            variable=row.variable,
            cycle_runtime_ns=row.cycle_runtime_ns,
            valid_start_ns=row.valid_start_ns,
            valid_end_ns=row.valid_end_ns,
            value_f=row.value_f,
            issuance_seq=0,
            measured_publication_lag_ns=max(0, row.available_at_ns - row.cycle_runtime_ns),
            available_at_ns=row.available_at_ns,
            ingested_at_ns=row.available_at_ns,
        )
        for row in nbp_rows
    )


def _parity_report_payload(
    report: ParityReport, depth_rows: Sequence[DepthSnapshotRow],
) -> dict[str, object]:
    """On-disk report: mismatch counts, per-(side, kind) counts, NO-depth census."""
    payload: dict[str, object] = {}
    for key, value in report.to_counts_dict().items():
        payload[key] = value
    payload["no_depth_days_by_station"] = no_depth_census(depth_rows)
    return payload


def manifest_stations(repo_root: Path) -> tuple[str, ...]:
    """Stations ``pm_us_crh_fq_v1`` trades, read from the manifest, in file order."""
    manifest = load_family_manifest(repo_root / "deploy" / "families" / _FAMILY_MANIFEST_NAME)
    return manifest.stations


def _load_catalog_inputs(
    catalog_root: Path,
    *,
    start: date,
    end: date,
    catalog: Any = None,
    stations: Sequence[str] | None = None,
) -> tuple[
    tuple[BinaryOption, ...],
    tuple[OrderBookDepth10, ...],
    tuple[DepthSnapshotRow, ...],
    dict[tuple[str, date], tuple[Rung, ...]],
    dict[str, float],
    dict[str, float],
    dict[str, str],
]:
    """Load one climate-day window.

    Instrument ids come from the slug date in the catalog directory name
    (the same date ``Instrument.info`` records). ``catalog.query`` is then
    called with those ids and a ts_init pad around the window, so Nautilus
    opens only those partitions. A second instrument query reads the few
    unpartitioned binary-option files (Aug 30-31). Rows whose facts
    climate day is outside ``[start, end]`` are still dropped — the same
    predicate as before.
    """
    if catalog is None:
        catalog = ParquetDataCatalog(str(catalog_root))
    allowed = None if stations is None else frozenset(stations)
    start_ts, end_ts = _tape_query_bounds(start, end)
    instrument_ids = _instrument_ids_in_window(catalog_root, start=start, end=end)
    queried: list[Any] = []
    if instrument_ids:
        queried.extend(
            catalog.query(
                data_cls=BinaryOption,
                identifiers=list(instrument_ids),
                start=start_ts,
                end=end_ts,
            ),
        )
    loose_files = _loose_binary_option_files(catalog_root)
    if loose_files:
        queried.extend(
            catalog.query(
                data_cls=BinaryOption,
                files=list(loose_files),
                start=start_ts,
                end=end_ts,
            ),
        )
    facts_by_id: dict[str, tuple[str, date, str, _Side]] = {}
    ladder_by_key: dict[tuple[str, date], list[Rung]] = {}
    seen_ids: set[str] = set()
    kept: list[BinaryOption] = []
    for instrument in queried:
        instrument_key = str(instrument.id)
        if instrument_key in seen_ids:
            continue
        try:
            facts = read_weather_bucket_facts(instrument.info)
        except WeatherFactsUnavailableError:
            continue
        seen_ids.add(instrument_key)
        if not (start <= facts.climate_day <= end):
            continue
        if allowed is not None and facts.settlement_station not in allowed:
            continue
        kept.append(instrument)
        side = _trusted_side(leg_of(instrument.id))
        rung_id = _rung_id_from_bounds(facts.lower_f, facts.upper_f)
        facts_by_id[instrument_key] = (
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

    depth_ids = [str(instrument.id) for instrument in kept]
    if depth_ids:
        depths = tuple(
            cast(
                list[OrderBookDepth10],
                catalog.query(
                    data_cls=OrderBookDepth10,
                    identifiers=depth_ids,
                    start=start_ts,
                    end=end_ts,
                ),
            ),
        )
    else:
        depths = ()
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
    present_stations = sorted({station for station, _day in ladder_by_key})
    std_offsets = {
        station: registry.climate_day_window("polymarket_us", station).std_utc_offset_hours
        for station in present_stations
    }
    latitude_deg_by_station = {
        station: registry.enrichment_coordinates("polymarket_us", station).lat
        for station in present_stations
    }
    quantile_station_keys = {
        station: registry.settlement_site("polymarket_us", station).icao
        for station in present_stations
    }
    return (
        tuple(kept),
        tuple(filtered_depths),
        tuple(batch_rows),
        {key: tuple(value) for key, value in ladder_by_key.items()},
        std_offsets,
        latitude_deg_by_station,
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


#: FQ-S4b vacuity guard (plan §3 S4b item 6, peer review disposition 6): a
#: decision kind that counts as "evaluated", i.e. neither `NotExecutable` nor
#: `NotDPlus1` (both are non-trials the strategy itself never counts either).
_VACUOUS_KINDS: Final[frozenset[str]] = frozenset({"NotExecutable", "NotDPlus1"})
_NON_VACUOUS_KINDS: Final[tuple[str, ...]] = ("Refuse", "Take")
_PARITY_PATHS: Final[tuple[str, ...]] = ("live", "batch")
_PARITY_SIDES: Final[tuple[str, ...]] = ("yes", "no")


def _non_vacuous_count(side_kind_counts: Mapping[str, int], *, path: str, side: str) -> int:
    return sum(side_kind_counts[f"n_{path}_{side}_{kind}"] for kind in _NON_VACUOUS_KINDS)


def vacuity_guard_failures(
    side_kind_counts: Mapping[str, int], *, no_side_unexercisable_in_window: bool,
) -> tuple[str, ...]:
    """The closed set of ``"{path}_{side}"`` buckets with ZERO evaluated
    (non-`NotExecutable`/`NotDPlus1`) decisions (plan §3 S4b item 6).

    Empty means the guard passes. When ``no_side_unexercisable_in_window`` is
    ``True`` (the S4a NO-depth census found no NO-leg depth for any
    station-day on either path's own window), the NO side is exempted on
    BOTH paths -- disposition 6: "the guard requires YES only" -- and the
    mandatory synthetic NO-path parity test
    (``tests/unit/test_nbp_shadow_parity_no_side_synthetic.py``) is what
    proves the NO-path formulas themselves still agree.
    """
    failures: list[str] = []
    for path in _PARITY_PATHS:
        for side in _PARITY_SIDES:
            if side == "no" and no_side_unexercisable_in_window:
                continue
            if _non_vacuous_count(side_kind_counts, path=path, side=side) < 1:
                failures.append(f"{path}_{side}")
    return tuple(failures)


def production_slippage_floor_prob() -> float:
    """Floor the deployed composition subtracts.

    ``build_forecast_quantile_ladder_strategies`` builds ``LadderEvConfig()``
    when the caller passes no ladder config. Both replay legs pass this
    value explicitly, so a change to that default moves the harness with it.
    """
    return LadderEvConfig().slippage_floor_prob


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        _assert_pre_freeze_range(args.start_date, args.end_date)
        live_calibration = load_live_calibration(
            str(args.calibration_artefact), expected_sha256=args.calibration_sha256,
        )
        batch_calibration = BatchCalibration(
            cdf_method=live_calibration.cdf_method,
            correction_form=live_calibration.correction_form,
            linear_coefficients=live_calibration.linear_coefficients,
            month_offsets=live_calibration.month_offsets,
            point_by_version=live_calibration.point_by_version,
            draws_by_version=live_calibration.draws_by_version,
        )
        # Both legs use the SAME real bootstrap-draw bounds implementation
        # (plan §3 S4b: "Both legs use the S2 calibration and bounds") --
        # one `ArtefactBoundsProvider` instance, injected into both paths.
        bounds_provider = ArtefactBoundsProvider(cdf_method=live_calibration.cdf_method)
        quote_settings = load_quote_tape_settings()
        # One climate day at a time. A 7-day Depth10 materialisation is millions
        # of OrderBookDepth10 objects (past 6G). Latch keys include climate_day,
        # so a fresh latch per day matches one shared latch. Each day still sees
        # the whole window's NBP rows, so value_at's latest-visible vector matches
        # a single combined run. Counts are summed; days' identity keys are disjoint.
        nbp_rows = _load_nbp_rows(args.nbp_derived_root, start=args.start_date, end=args.end_date)
        forecast_points = _forecast_points(nbp_rows)
        allowed_stations = manifest_stations(Path(__file__).resolve().parents[2])
        day_reports: list[ParityReport] = []
        censuses: list[dict[str, int]] = []
        for day in _inclusive_days(args.start_date, args.end_date):
            (
                instruments,
                market_data,
                depth_rows,
                ladder_by_key,
                std_offsets,
                latitude_deg_by_station,
                quantile_station_keys,
            ) = _load_catalog_inputs(
                quote_settings.catalog_root,
                start=day,
                end=day,
                stations=allowed_stations,
            )
            if not std_offsets:
                continue
            # Free the ts_init-stamped originals before the engine retains
            # the decision-instant copies. See ``_depth_clocked_at_decision_instant``.
            market_data = tuple(
                _depth_clocked_at_decision_instant(depth) for depth in market_data
            )
            gc.collect()
            active_stations = tuple(
                station for station in allowed_stations if station in std_offsets
            )
            live = run_live_parity(
                instruments=instruments,
                market_data=market_data,
                forecast_points=forecast_points,
                ladder_by_key=ladder_by_key,
                calibration=live_calibration,
                ladder_cfg=LadderEvConfig(),
                bounds_provider=bounds_provider,
                fee_coefficient=0.0695,
                slippage_floor_prob=production_slippage_floor_prob(),
                std_utc_offset_hours_by_station=std_offsets,
                stations=active_stations,
                quantile_station_keys=quantile_station_keys,
            )
            batch = run_batch_parity(
                depth_snapshots=depth_rows,
                nbp_rows=nbp_rows,
                ladder_by_key=ladder_by_key,
                calibration=batch_calibration,
                ladder_cfg=LadderEvConfig(),
                bounds_provider=bounds_provider,
                fee_coefficient=0.0695,
                slippage_floor_prob=production_slippage_floor_prob(),
                std_utc_offset_hours_by_station=std_offsets,
                latitude_deg_by_station=latitude_deg_by_station,
                quantile_station_keys=quantile_station_keys,
                stations=allowed_stations,
            )
            day_reports.append(diff_decision_keys(live, batch))
            censuses.append(dict(no_depth_census(depth_rows)))
            del instruments, market_data, depth_rows, live, batch
            gc.collect()
        report = _merge_parity_reports(day_reports)
        no_depth_by_station = _merge_no_depth_census(censuses)
        no_side_unexercisable_in_window = not any(no_depth_by_station.values())
        payload = _parity_report_payload(report, ())
        payload["no_depth_days_by_station"] = no_depth_by_station
        payload["no_side_unexercisable_in_window"] = no_side_unexercisable_in_window
        guard_failures = vacuity_guard_failures(
            report.side_kind_counts,
            no_side_unexercisable_in_window=no_side_unexercisable_in_window,
        )
        payload["vacuity_guard_failures"] = list(guard_failures)
        _write_report(args.output, payload)
        if guard_failures:
            return 1
    except (
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
