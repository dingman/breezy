"""SL-9: NBP model vs market SEARCH comparison on pre-freeze tape.

Read-only analysis script. Market prices enter only as execution-cost and
market-forecast comparison inputs; the model probabilities are built from NBP
weather rows plus the calibration artefact.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_EVEN
from pathlib import Path
from typing import Any, Final, Literal, TypeAlias

_SCRIPTS_ANALYSIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPTS_ANALYSIS_DIR.parents[1]
for _entry in (str(_SCRIPTS_ANALYSIS_DIR), str(_REPO_ROOT / "src")):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

import pyarrow.parquet as pq
from nautilus_trader.model.data import OrderBookDepth10
from nautilus_trader.model.instruments import BinaryOption
from nautilus_trader.persistence.catalog import ParquetDataCatalog

from breezy.adapters.polymarket_us import safety
from breezy.analysis.nbp_calibration import (
    FIT_STATUS_OK,
    NbpCalibrationArtefact,
    artefact_from_json_dict,
)
from breezy.domain.weather_bucket_facts import WeatherBucketFacts, read_weather_bucket_facts
from breezy.persistence.nbp_derived_store import DerivedNbpRow, read_partition
from breezy.runtime import trade_supervisor_core
from breezy.runtime.settings import QUOTE_TAPE_CATALOG_VAR, load_quote_tape_settings
from breezy.strategy.depth10 import market_quote_from_depth
from breezy.strategy.ladder_ev.quantile_density import (
    CdfMethod,
    EmosParams,
    Percentiles,
    Rung,
    apply_emos,
    build_cdf,
    rung_probability_interval,
)

from scripts.analysis.settlement_truth_dataset import SettlementTruthRow, final_rows_for_gate
from scripts.analysis.wp7b_market_as_forecaster import (
    IncompleteLadderError,
    MARKET_ASK,
    RungEvent,
    assert_complete_partition,
    paired_brier,
    paired_brier_ci,
    select_reading,
    sum_ask_row,
)
from scripts.analysis.h4_preliminary_economic_read import parse_rung

LegSide: TypeAlias = Literal["yes", "no"]
BookSource: TypeAlias = Literal["captured_yes_book", "captured_no_book", "derived_from_yes_book"]
ExecutionStatus: TypeAlias = Literal["EXECUTABLE", "NOT_EXECUTABLE"]
Verdict: TypeAlias = Literal["DROP", "KEEP"]
StationDay: TypeAlias = tuple[str, dt.date]

PRE_FREEZE_END: Final[dt.date] = dt.date(2026, 9, 25)
S4_SHADOW_TOKENS: Final[tuple[str, ...]] = ("s4_shadow", "shadow_log", "shadow-")
MAKER_THETA_CEILING: Final[Decimal] = Decimal("0.0695")
TAKER_THETA_POST_DRIFT: Final[Decimal] = Decimal("0.0695")
MAKER_HAIRCUT_WINDOW_NS: Final[int] = 5 * 60 * 1_000_000_000
NS_PER_SECOND: Final[int] = 1_000_000_000

__all__ = [
    "BookSource",
    "CalibrationArtefactRefusedError",
    "CapturedNoBookRequiredError",
    "ComparisonReport",
    "ForecastRungProbability",
    "LegSide",
    "MAKER_THETA_CEILING",
    "MarketSnapshot",
    "PostFreezeTapeRefusedError",
    "Rung",
    "Scope",
    "ShadowLogRefusedError",
    "AvailabilityLookAheadError",
    "assert_allowed_tape_day",
    "assert_not_shadow_log_path",
    "compare_model_vs_market",
    "drop_keep_json_bytes",
    "executable_ask",
    "execution_status",
    "is_inside_nominal_permit",
    "load_calibration_artefact",
    "maker_fill_ev",
    "maker_verdict",
    "rungs_by_station_day_from_catalog",
    "rounded_quadratic_fee_usd",
    "safety",
    "scope_snapshots",
    "select_forecast_for_snapshot",
    "taker_verdict",
    "trade_supervisor_core",
]


class AvailabilityLookAheadError(AssertionError):
    """A forecast vintage was not available strictly before the price snapshot."""


class PostFreezeTapeRefusedError(ValueError):
    """Tape after the sealed pre-freeze SEARCH window was supplied."""


class ShadowLogRefusedError(ValueError):
    """S4 shadow logs are not registered inputs for SL-9."""


class CapturedNoBookRequiredError(ValueError):
    """A NO leg was priced from anything other than the captured NO book."""


class CalibrationArtefactRefusedError(ValueError):
    """The S2 calibration artefact is not admissible for SEARCH."""


class IncompleteInputError(ValueError):
    """The synthetic or real input set cannot produce a scored comparison."""


@dataclass(frozen=True, slots=True)
class Scope:
    days: frozenset[dt.date]
    hours_utc: frozenset[int]


@dataclass(frozen=True, slots=True)
class ForecastRungProbability:
    station: str
    climate_day: dt.date
    rung_id: str
    available_at_ns: int
    p_point: float
    p_lower: float
    p_upper: float


@dataclass(frozen=True, slots=True)
class MarketSnapshot:
    station: str
    climate_day: dt.date
    rung_id: str
    side: LegSide
    price_ts_ns: int
    ask: float
    bid: float | None
    ask_size: float
    bid_size: float
    source: BookSource


@dataclass(frozen=True, slots=True)
class MakerFillResult:
    ev: float
    fee_theta: Decimal
    fee: Decimal
    haircut: float

    def to_dict(self) -> dict[str, object]:
        return {
            "ev": self.ev,
            "fee_theta": str(self.fee_theta),
            "fee": str(self.fee),
            "haircut": self.haircut,
        }


@dataclass(frozen=True, slots=True)
class VariantDecision:
    variant: str
    verdict: Verdict
    n_events: int
    point_estimate: float
    ci_low: float | None
    ci_high: float | None
    reading: str | None
    arithmetic: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "variant": self.variant,
            "drop_keep": self.verdict,
            "n_events": self.n_events,
            "point_estimate": self.point_estimate,
            "ci_low": self.ci_low,
            "ci_high": self.ci_high,
            "reading": self.reading,
            "arithmetic": self.arithmetic,
        }


@dataclass(frozen=True, slots=True)
class ComparisonReport:
    decisions: Mapping[str, VariantDecision]
    all_hours: Mapping[str, object]
    counts: Mapping[str, int]

    def to_dict(self) -> dict[str, object]:
        return {
            "decisions": {
                key: decision.to_dict() for key, decision in sorted(self.decisions.items())
            },
            "all_hours": dict(self.all_hours),
            "counts": dict(self.counts),
        }


@dataclass(frozen=True, slots=True)
class InstrumentRungSpec:
    instrument_id: str
    station: str
    climate_day: dt.date
    rung_id: str
    lo: int | None
    hi: int | None
    partition_instrument_id: str


def assert_allowed_tape_day(day: dt.date) -> None:
    if day > PRE_FREEZE_END:
        raise PostFreezeTapeRefusedError(
            f"{day.isoformat()} is after the sealed pre-freeze tape cutoff "
            f"{PRE_FREEZE_END.isoformat()}"
        )


def _utc_date(ts_ns: int) -> dt.date:
    return dt.datetime.fromtimestamp(ts_ns / NS_PER_SECOND, tz=dt.UTC).date()


def assert_allowed_tape_snapshot(snapshot: MarketSnapshot) -> None:
    assert_allowed_tape_day(snapshot.climate_day)
    price_day = _utc_date(snapshot.price_ts_ns)
    if price_day > PRE_FREEZE_END:
        raise PostFreezeTapeRefusedError(
            f"price_ts UTC date {price_day.isoformat()} is after the sealed pre-freeze tape "
            f"cutoff {PRE_FREEZE_END.isoformat()}"
        )


def assert_not_shadow_log_path(path: str | Path) -> None:
    lowered = str(path).lower()
    if any(token in lowered for token in S4_SHADOW_TOKENS):
        raise ShadowLogRefusedError(
            f"refusing S4 shadow log input {path!s}; SL-9 reads pre-freeze tape only"
        )


def _utc_hour(ts_ns: int) -> int:
    return dt.datetime.fromtimestamp(ts_ns / NS_PER_SECOND, tz=dt.UTC).hour


def scope_snapshots(
    snapshots: Sequence[MarketSnapshot], *, scope: Scope
) -> tuple[MarketSnapshot, ...]:
    return tuple(
        snapshot
        for snapshot in snapshots
        if snapshot.climate_day in scope.days and _utc_hour(snapshot.price_ts_ns) in scope.hours_utc
    )


def _forecast_key(row: ForecastRungProbability) -> tuple[str, dt.date, str]:
    return (row.station, row.climate_day, row.rung_id)


def select_forecast_for_snapshot(
    forecasts: Sequence[ForecastRungProbability], snapshot: MarketSnapshot
) -> ForecastRungProbability:
    key = (snapshot.station, snapshot.climate_day, snapshot.rung_id)
    matched = [row for row in forecasts if _forecast_key(row) == key]
    if not matched:
        raise IncompleteInputError(f"no NBP probability for {key!r}")
    eligible = [row for row in matched if row.available_at_ns < snapshot.price_ts_ns]
    if not eligible:
        first = min(matched, key=lambda row: row.available_at_ns)
        if first.available_at_ns >= snapshot.price_ts_ns:
            raise AvailabilityLookAheadError(
                f"{key!r}: forecast available_at_ns={first.available_at_ns} is not before "
                f"price_ts={snapshot.price_ts_ns}"
            )
        raise IncompleteInputError(f"no visible NBP probability for {key!r}")
    return max(eligible, key=lambda row: row.available_at_ns)


def executable_ask(snapshot: MarketSnapshot) -> float:
    if snapshot.side == "no" and snapshot.source != "captured_no_book":
        raise CapturedNoBookRequiredError(
            f"{snapshot.station} {snapshot.climate_day} {snapshot.rung_id}: NO leg price "
            "must come from the captured NO book"
        )
    return snapshot.ask


def rounded_quadratic_fee_usd(*, quantity: Decimal, price: Decimal, theta: Decimal) -> Decimal:
    if price < Decimal("0") or price > Decimal("1"):
        raise ValueError(f"price {price!s} is outside [0, 1]")
    exact = theta * quantity * price * (Decimal("1") - price)
    return exact.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)


def is_inside_nominal_permit(ts_ns: int) -> bool:
    now_dt = dt.datetime.fromtimestamp(ts_ns / NS_PER_SECOND, tz=dt.UTC)
    for day in (now_dt.date(), now_dt.date() - dt.timedelta(days=1)):
        start_dt = dt.datetime.combine(day, trade_supervisor_core.LAUNCH_UTC, tzinfo=dt.UTC)
        start_ns = int(start_dt.timestamp()) * NS_PER_SECOND
        end_ns = start_ns + safety.PERMIT_TTL_NS
        if start_ns <= ts_ns < end_ns:
            return True
    return False


def execution_status(snapshot: MarketSnapshot) -> ExecutionStatus:
    return "EXECUTABLE" if is_inside_nominal_permit(snapshot.price_ts_ns) else "NOT_EXECUTABLE"


def _same_leg(left: MarketSnapshot, right: MarketSnapshot) -> bool:
    return (
        left.station == right.station
        and left.climate_day == right.climate_day
        and left.rung_id == right.rung_id
        and left.side == right.side
    )


def maker_fill_ev(
    *,
    fill: MarketSnapshot,
    forecast: ForecastRungProbability,
    later_same_leg_snapshots: Sequence[MarketSnapshot],
) -> MakerFillResult:
    fill_ask = executable_ask(fill)
    window_end = fill.price_ts_ns + MAKER_HAIRCUT_WINDOW_NS
    later_bids: list[float] = []
    for row in later_same_leg_snapshots:
        if not _same_leg(fill, row):
            continue
        executable_ask(row)
        if fill.price_ts_ns < row.price_ts_ns <= window_end and row.bid is not None:
            later_bids.append(row.bid)
    min_later_bid = min(later_bids) if later_bids else fill.bid
    haircut = 0.0
    if min_later_bid is not None:
        haircut = max(0.0, fill_ask - min_later_bid)
    fee = rounded_quadratic_fee_usd(
        quantity=Decimal("1"), price=Decimal(str(fill_ask)), theta=MAKER_THETA_CEILING
    )
    settlement_ev = _model_prob_for_side(forecast, fill.side) - fill_ask
    ev = settlement_ev - float(fee) - haircut
    return MakerFillResult(ev=ev, fee_theta=MAKER_THETA_CEILING, fee=fee, haircut=haircut)


def taker_verdict(*, ci_upper: float) -> Verdict:
    return "DROP" if ci_upper < 0.0 else "KEEP"


def maker_verdict(*, ev_point: float) -> Verdict:
    return "DROP" if ev_point <= 0.0 else "KEEP"


def _model_prob_for_side(forecast: ForecastRungProbability, side: LegSide) -> float:
    if side == "yes":
        return forecast.p_point
    return 1.0 - forecast.p_point


def _truth_for_side(truths: Mapping[tuple[str, dt.date, str], bool], snapshot: MarketSnapshot) -> bool:
    settled_yes = truths[(snapshot.station, snapshot.climate_day, snapshot.rung_id)]
    return settled_yes if snapshot.side == "yes" else not settled_yes


def _event_from(
    *,
    snapshot: MarketSnapshot,
    forecast: ForecastRungProbability,
    truths: Mapping[tuple[str, dt.date, str], bool],
) -> RungEvent:
    ask = executable_ask(snapshot)
    p_fc = _model_prob_for_side(forecast, snapshot.side)
    rung_id = snapshot.rung_id if snapshot.side == "yes" else f"{snapshot.rung_id}^no"
    return RungEvent(
        station=snapshot.station,
        climate_day=snapshot.climate_day,
        rung_id=rung_id,
        ts_ns=snapshot.price_ts_ns,
        p_fc=p_fc,
        ask=ask,
        ask_size=snapshot.ask_size,
        bid=snapshot.bid,
        bid_size=snapshot.bid_size,
        settled=_truth_for_side(truths, snapshot),
    )


def _events_for(
    *,
    forecasts: Sequence[ForecastRungProbability],
    snapshots: Sequence[MarketSnapshot],
    truths: Mapping[tuple[str, dt.date, str], bool],
) -> tuple[RungEvent, ...]:
    events: list[RungEvent] = []
    for snapshot in snapshots:
        forecast = select_forecast_for_snapshot(forecasts, snapshot)
        events.append(_event_from(snapshot=snapshot, forecast=forecast, truths=truths))
    return tuple(events)


def _partition_rung_id(rung_id: str) -> str:
    return rung_id.removesuffix("^no")


def _event_for_partition(event: RungEvent) -> RungEvent:
    return RungEvent(
        station=event.station,
        climate_day=event.climate_day,
        rung_id=_partition_check_id(event),
        ts_ns=event.ts_ns,
        p_fc=event.p_fc,
        ask=event.ask,
        ask_size=event.ask_size,
        bid=event.bid,
        bid_size=event.bid_size,
        settled=event.settled,
    )


def _event_instant_key(event: RungEvent) -> tuple[str, dt.date, int]:
    return (event.station, event.climate_day, event.ts_ns)


def _expected_rung_ids(rungs: Sequence[Rung]) -> frozenset[str]:
    return frozenset(rung.rung_id for rung in rungs)


def _filter_complete_partition_instants(
    events: Sequence[RungEvent],
    *,
    rungs_by_station_day: Mapping[StationDay, Sequence[Rung]] | None,
) -> tuple[tuple[RungEvent, ...], dict[str, int]]:
    if rungs_by_station_day is None:
        return tuple(events), {
            "instants_partition_checked": 0,
            "instants_partition_incomplete": 0,
        }
    grouped: dict[tuple[str, dt.date, int], list[RungEvent]] = {}
    for event in events:
        grouped.setdefault(_event_instant_key(event), []).append(event)

    kept: list[RungEvent] = []
    incomplete = 0
    for (station, climate_day, _ts_ns), group in sorted(grouped.items()):
        expected = rungs_by_station_day.get((station, climate_day))
        observed = frozenset(_partition_rung_id(event.rung_id) for event in group)
        try:
            partition_events = tuple(_event_for_partition(event) for event in group)
            if expected is None or observed != _expected_rung_ids(expected):
                raise IncompleteInputError(
                    f"{station} {climate_day.isoformat()}: instant has "
                    f"{len(observed)} of {0 if expected is None else len(expected)} catalog rungs"
                )
            assert_complete_partition(tuple(parse_rung(event.rung_id) for event in partition_events))
            sum_ask_row(partition_events)
        except (IncompleteInputError, IncompleteLadderError, ValueError):
            incomplete += 1
            continue
        kept.extend(group)

    return tuple(kept), {
        "instants_partition_checked": len(grouped),
        "instants_partition_incomplete": incomplete,
    }


def _partition_check_id(event: RungEvent) -> str:
    return _partition_instrument_id(
        station=event.station,
        climate_day=event.climate_day,
        lo=_bounds_from_rung_id(event.rung_id)[0],
        hi=_bounds_from_rung_id(event.rung_id)[1],
    )


def _variant_from_events(variant: str, events: Sequence[RungEvent]) -> VariantDecision:
    if not events:
        return VariantDecision(
            variant=variant,
            verdict="DROP",
            n_events=0,
            point_estimate=float("nan"),
            ci_low=None,
            ci_high=None,
            reading=None,
            arithmetic="no permit-covered events",
        )
    fc, market, diff = paired_brier(events, market=MARKET_ASK)
    ci = paired_brier_ci(events, market=MARKET_ASK)
    mean_gap = math.fsum(abs(event.p_fc - event.ask) for event in events) / len(events)
    mean_hurdle = math.fsum(
        float(
            rounded_quadratic_fee_usd(
                quantity=Decimal("1"),
                price=Decimal(str(event.ask)),
                theta=TAKER_THETA_POST_DRIFT,
            )
        )
        for event in events
    ) / len(events)
    reading, arithmetic = select_reading(ci=ci, mean_gap=mean_gap, mean_hurdle=mean_hurdle)
    _ = (fc, market)
    return VariantDecision(
        variant=variant,
        verdict=taker_verdict(ci_upper=ci.high),
        n_events=len(events),
        point_estimate=diff,
        ci_low=ci.low,
        ci_high=ci.high,
        reading=reading,
        arithmetic=arithmetic,
    )


def _maker_decision(
    *,
    forecasts: Sequence[ForecastRungProbability],
    snapshots: Sequence[MarketSnapshot],
) -> VariantDecision:
    fills: list[MakerFillResult] = []
    for snapshot in snapshots:
        forecast = select_forecast_for_snapshot(forecasts, snapshot)
        fills.append(
            maker_fill_ev(fill=snapshot, forecast=forecast, later_same_leg_snapshots=snapshots)
        )
    ev_point = math.fsum(fill.ev for fill in fills) / len(fills) if fills else float("nan")
    return VariantDecision(
        variant="maker_v2",
        verdict=maker_verdict(ev_point=ev_point if fills else 0.0),
        n_events=len(fills),
        point_estimate=ev_point,
        ci_low=None,
        ci_high=None,
        reading=None,
        arithmetic="maker EV point estimate after theta ceiling and W=5m haircut",
    )


def compare_model_vs_market(
    *,
    forecasts: Sequence[ForecastRungProbability],
    snapshots: Sequence[MarketSnapshot],
    truths: Mapping[tuple[str, dt.date, str], bool],
    rungs_by_station_day: Mapping[StationDay, Sequence[Rung]] | None = None,
) -> ComparisonReport:
    for snapshot in snapshots:
        assert_allowed_tape_snapshot(snapshot)
    ordered = tuple(sorted(snapshots, key=lambda row: row.price_ts_ns))
    permit_snapshots = tuple(row for row in ordered if execution_status(row) == "EXECUTABLE")
    raw_decisive_events = _events_for(forecasts=forecasts, snapshots=permit_snapshots, truths=truths)
    raw_all_events = _events_for(forecasts=forecasts, snapshots=ordered, truths=truths)
    decisive_events, decisive_partition_counts = _filter_complete_partition_instants(
        raw_decisive_events,
        rungs_by_station_day=rungs_by_station_day,
    )
    all_events, all_partition_counts = _filter_complete_partition_instants(
        raw_all_events,
        rungs_by_station_day=rungs_by_station_day,
    )
    maker_event_keys = frozenset(_event_instant_key(event) for event in decisive_events)
    maker_snapshots = tuple(
        row
        for row in permit_snapshots
        if rungs_by_station_day is None
        or (row.station, row.climate_day, row.price_ts_ns) in maker_event_keys
    )
    all_fc, all_market, all_diff = (
        paired_brier(all_events, market=MARKET_ASK) if all_events else (float("nan"),) * 3
    )
    decisions = {
        "taker_v1": _variant_from_events("taker_v1", decisive_events),
        "maker_v2": _maker_decision(forecasts=forecasts, snapshots=maker_snapshots),
    }
    return ComparisonReport(
        decisions=decisions,
        all_hours={
            "label": "descriptive forecast-skill only",
            "n_events": len(all_events),
            "brier_model": all_fc,
            "brier_market_ask": all_market,
            "model_minus_market_ask": all_diff,
        },
        counts={
            "snapshots_total": len(ordered),
            "snapshots_permit": len(permit_snapshots),
            "snapshots_not_executable": len(ordered) - len(permit_snapshots),
            "instants_partition_checked": all_partition_counts["instants_partition_checked"],
            "instants_partition_incomplete": all_partition_counts["instants_partition_incomplete"],
            "decisive_instants_partition_incomplete": decisive_partition_counts[
                "instants_partition_incomplete"
            ],
            "all_hours_instants_partition_incomplete": all_partition_counts[
                "instants_partition_incomplete"
            ],
        },
    )


def drop_keep_json_bytes(report: ComparisonReport) -> bytes:
    payload = {
        key: decision.to_dict()
        for key, decision in sorted(report.decisions.items())
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def load_calibration_artefact(path: Path) -> NbpCalibrationArtefact:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise CalibrationArtefactRefusedError(f"{path}: artefact JSON is not an object")
    artefact = artefact_from_json_dict(payload)
    if artefact.fit_status != FIT_STATUS_OK:
        raise CalibrationArtefactRefusedError(
            f"{path}: fit_status={artefact.fit_status!r}, not {FIT_STATUS_OK!r}"
        )
    return artefact


def _method(value: str) -> CdfMethod:
    return CdfMethod(value)


def _emos_draws_for_version(
    artefact: NbpCalibrationArtefact, version: str
) -> tuple[EmosParams, ...]:
    entries = artefact.emos_draws_by_version.get(version)
    if not entries:
        raise IncompleteInputError(f"artefact has no EMOS draws for NBP version {version!r}")
    return tuple(EmosParams(a=a, gamma=gamma, delta=delta) for a, gamma, delta in entries)


def _percentiles_from_rows(rows: Sequence[DerivedNbpRow]) -> Percentiles:
    values = {row.variable: row.value_f for row in rows}
    required = ("TXN_Q10", "TXN_Q25", "TXN_Q50", "TXN_Q75", "TXN_Q90", "TXN_MEAN", "TXN_SD")
    missing = [name for name in required if values.get(name) is None]
    if missing:
        raise IncompleteInputError(f"NBP row group missing {missing!r}")
    q10 = values["TXN_Q10"]
    q25 = values["TXN_Q25"]
    q50 = values["TXN_Q50"]
    q75 = values["TXN_Q75"]
    q90 = values["TXN_Q90"]
    mean = values["TXN_MEAN"]
    sd = values["TXN_SD"]
    if (
        q10 is None
        or q25 is None
        or q50 is None
        or q75 is None
        or q90 is None
        or mean is None
        or sd is None
    ):
        raise IncompleteInputError("NBP row group has null percentile values")
    return Percentiles(
        q10=float(q10),
        q25=float(q25),
        q50=float(q50),
        q75=float(q75),
        q90=float(q90),
        mean=float(mean),
        sd=float(sd),
    )


def probabilities_from_nbp_rows(
    *,
    rows: Sequence[DerivedNbpRow],
    rungs: Sequence[Rung] | None = None,
    rungs_by_station_day: Mapping[StationDay, Sequence[Rung]] | None = None,
    artefact: NbpCalibrationArtefact,
) -> tuple[ForecastRungProbability, ...]:
    grouped: dict[tuple[str, dt.date, int], list[DerivedNbpRow]] = {}
    for row in rows:
        valid_dt = dt.datetime.fromtimestamp(row.valid_start_ns / NS_PER_SECOND, tz=dt.UTC)
        grouped.setdefault((row.station, valid_dt.date(), row.cycle_runtime_ns), []).append(row)
    out: list[ForecastRungProbability] = []
    for (station, climate_day, cycle_runtime_ns), group in sorted(grouped.items()):
        version = group[0].nbm_version_era
        percentiles = _percentiles_from_rows(group)
        draws = _emos_draws_for_version(artefact, version)
        station_day_rungs = (
            rungs_by_station_day.get((station, climate_day))
            if rungs_by_station_day is not None
            else rungs
        )
        if not station_day_rungs:
            continue
        bounds = rung_probability_interval(
            percentiles,
            _method(artefact.cdf_method),
            draws,
            station_day_rungs,
        )
        available_at_ns = max(row.available_at_ns for row in group)
        _ = cycle_runtime_ns
        for rung_id, (point, lower, upper) in bounds.items():
            out.append(
                ForecastRungProbability(
                    station=station,
                    climate_day=climate_day,
                    rung_id=rung_id,
                    available_at_ns=available_at_ns,
                    p_point=point,
                    p_lower=lower,
                    p_upper=upper,
                )
            )
    return tuple(out)


def _station_day_key(row: SettlementTruthRow) -> tuple[str, dt.date]:
    return (row.station, row.climate_day)


def _load_truths(path: Path, rung_by_key: Mapping[tuple[str, dt.date, str], Rung]) -> dict[tuple[str, dt.date, str], bool]:
    table = pq.read_table(path)
    rows = tuple(SettlementTruthRow(**record) for record in table.to_pylist())
    gated = final_rows_for_gate(rows)
    by_day = {_station_day_key(row): row for row in gated}
    truths: dict[tuple[str, dt.date, str], bool] = {}
    for (station, climate_day, rung_id), rung in rung_by_key.items():
        truth = by_day.get((station, climate_day))
        if truth is None or truth.tmax_f is None:
            continue
        lower_ok = rung.lo is None or truth.tmax_f >= rung.lo
        upper_ok = rung.hi is None or truth.tmax_f <= rung.hi
        truths[(station, climate_day, rung_id)] = lower_ok and upper_ok
    return truths


def _read_nbp_rows(root: Path) -> tuple[DerivedNbpRow, ...]:
    rows: list[DerivedNbpRow] = []
    for path in sorted(root.glob("**/nbp_*.parquet")):
        rows.extend(read_partition(path))
    return tuple(rows)


def _catalog_root_from_settings() -> Path:
    settings = load_quote_tape_settings(total_bytes_probe=lambda _path: 1_000_000_000_000)
    return settings.catalog_root


def _rung_id_from_facts(facts: WeatherBucketFacts) -> str:
    if facts.lower_f is None:
        if facts.upper_f is None:
            raise IncompleteInputError("weather rung cannot have two open tails")
        return f"lt{facts.upper_f + 1}f"
    if facts.upper_f is None:
        return f"gte{facts.lower_f}f"
    return f"gte{facts.lower_f}lt{facts.upper_f}f"


def _partition_instrument_id(
    *,
    station: str,
    climate_day: dt.date,
    lo: int | None,
    hi: int | None,
) -> str:
    city = station.lower()
    if lo is None:
        if hi is None:
            raise IncompleteInputError("weather rung cannot have two open tails")
        band = f"lt{hi + 1}f"
    elif hi is None:
        band = f"gte{lo}f"
    else:
        band = f"gte{lo}lt{hi}f"
    return f"tc-temp-{city}high-{climate_day.isoformat()}-{band}.POLYMARKET_US"


def _bounds_from_rung_id(rung_id: str) -> tuple[int | None, int | None]:
    rung = parse_rung(
        f"tc-temp-xhigh-2026-09-25-{_partition_rung_id(rung_id)}.POLYMARKET_US"
    )
    return rung.lower_f, rung.upper_f


def _instrument_spec(instrument: object) -> InstrumentRungSpec:
    if not isinstance(instrument, BinaryOption):
        instrument_id = getattr(getattr(instrument, "id", None), "value", "<unknown>")
        raise TypeError(f"{instrument_id} is a {type(instrument).__name__}, not a BinaryOption")
    facts = read_weather_bucket_facts(instrument.info)
    rung_id = _rung_id_from_facts(facts)
    return InstrumentRungSpec(
        instrument_id=instrument.id.value,
        station=facts.settlement_station,
        climate_day=facts.climate_day,
        rung_id=rung_id,
        lo=facts.lower_f,
        hi=facts.upper_f,
        partition_instrument_id=_partition_instrument_id(
            station=facts.settlement_station,
            climate_day=facts.climate_day,
            lo=facts.lower_f,
            hi=facts.upper_f,
        ),
    )


def _instrument_specs_by_id(catalog: object) -> dict[str, InstrumentRungSpec]:
    by_id: dict[str, object] = {}
    for instrument in catalog.instruments():  # type: ignore[attr-defined]
        instrument_id = getattr(getattr(instrument, "id", None), "value", None)
        if isinstance(instrument_id, str):
            by_id.setdefault(instrument_id, instrument)
    return {
        instrument_id: _instrument_spec(instrument)
        for instrument_id, instrument in sorted(by_id.items())
    }


def _rung_sort_key(rung: Rung) -> tuple[int, int]:
    return (
        rung.lo if rung.lo is not None else -10_000,
        rung.hi if rung.hi is not None else 10_000,
    )


def rungs_by_station_day_from_catalog(
    catalog: object,
) -> tuple[dict[StationDay, tuple[Rung, ...]], dict[str, int]]:
    grouped: dict[StationDay, list[InstrumentRungSpec]] = {}
    for spec in _instrument_specs_by_id(catalog).values():
        grouped.setdefault((spec.station, spec.climate_day), []).append(spec)

    rungs_by_key: dict[StationDay, tuple[Rung, ...]] = {}
    incomplete = 0
    for key, specs in sorted(grouped.items()):
        try:
            assert_complete_partition(tuple(parse_rung(spec.partition_instrument_id) for spec in specs))
        except (IncompleteLadderError, ValueError):
            incomplete += 1
            continue
        rungs = tuple(
            sorted(
                (Rung(rung_id=spec.rung_id, lo=spec.lo, hi=spec.hi) for spec in specs),
                key=_rung_sort_key,
            )
        )
        rungs_by_key[key] = rungs

    return rungs_by_key, {
        "catalog_station_days_total": len(grouped),
        "catalog_station_days_complete_partition": len(rungs_by_key),
        "catalog_station_days_incomplete_partition": incomplete,
    }


def _snapshot_from_depth(
    depth: OrderBookDepth10,
    *,
    side: LegSide,
    source: BookSource,
    specs_by_instrument_id: Mapping[str, InstrumentRungSpec],
) -> MarketSnapshot | None:
    quote = market_quote_from_depth(depth, include_bid_ladder=True)
    if quote is None or quote.ask is None or quote.ask_size is None:
        return None
    spec = specs_by_instrument_id.get(str(depth.instrument_id))
    if spec is None:
        return None
    return MarketSnapshot(
        station=spec.station,
        climate_day=spec.climate_day,
        rung_id=spec.rung_id,
        side=side,
        price_ts_ns=int(depth.ts_event),
        ask=quote.ask,
        bid=quote.bid,
        ask_size=quote.ask_size,
        bid_size=0.0 if quote.bid_size is None else quote.bid_size,
        source=source,
    )


def _load_market_snapshots_from_catalog(
    catalog: ParquetDataCatalog,
    *,
    side: LegSide,
) -> tuple[MarketSnapshot, ...]:
    rows = catalog.query(OrderBookDepth10)
    specs_by_instrument_id = _instrument_specs_by_id(catalog)
    snapshots: list[MarketSnapshot] = []
    source: BookSource = "captured_no_book" if side == "no" else "captured_yes_book"
    for row in rows:
        snapshot = _snapshot_from_depth(
            row,
            side=side,
            source=source,
            specs_by_instrument_id=specs_by_instrument_id,
        )
        if snapshot is not None:
            assert_allowed_tape_snapshot(snapshot)
            snapshots.append(snapshot)
    return tuple(snapshots)


def _load_market_snapshots(catalog_root: Path, *, side: LegSide) -> tuple[MarketSnapshot, ...]:
    assert_not_shadow_log_path(catalog_root)
    catalog = ParquetDataCatalog(str(catalog_root))
    return _load_market_snapshots_from_catalog(catalog, side=side)


def _rung_by_key(
    snapshots: Iterable[MarketSnapshot], rungs_by_station_day: Mapping[StationDay, Sequence[Rung]]
) -> dict[tuple[str, dt.date, str], Rung]:
    out: dict[tuple[str, dt.date, str], Rung] = {}
    for snapshot in snapshots:
        rungs = rungs_by_station_day.get((snapshot.station, snapshot.climate_day), ())
        rung_by_id = {rung.rung_id: rung for rung in rungs}
        rung = rung_by_id.get(snapshot.rung_id)
        if rung is not None:
            out[(snapshot.station, snapshot.climate_day, snapshot.rung_id)] = rung
    return out


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quote-tape-catalog", default=None)
    parser.add_argument("--nbp-derived-root", required=True)
    parser.add_argument("--settlement-truth-parquet", required=True)
    parser.add_argument("--artefact", required=True)
    parser.add_argument("--side", choices=("yes", "no"), default="yes")
    parser.add_argument("--output", required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    quote_tape_catalog = (
        _catalog_root_from_settings()
        if args.quote_tape_catalog is None
        else Path(str(args.quote_tape_catalog))
    )
    _ = QUOTE_TAPE_CATALOG_VAR
    assert_not_shadow_log_path(quote_tape_catalog)
    catalog = ParquetDataCatalog(str(quote_tape_catalog))
    rungs_by_station_day, catalog_counts = rungs_by_station_day_from_catalog(catalog)
    artefact = load_calibration_artefact(Path(args.artefact))
    snapshots = _load_market_snapshots_from_catalog(catalog, side=args.side)
    nbp_rows = _read_nbp_rows(Path(args.nbp_derived_root))
    forecasts = probabilities_from_nbp_rows(
        rows=nbp_rows,
        rungs_by_station_day=rungs_by_station_day,
        artefact=artefact,
    )
    truths = _load_truths(
        Path(args.settlement_truth_parquet),
        _rung_by_key(snapshots, rungs_by_station_day),
    )
    report = compare_model_vs_market(
        forecasts=forecasts,
        snapshots=snapshots,
        truths=truths,
        rungs_by_station_day=rungs_by_station_day,
    )
    report = ComparisonReport(
        decisions=report.decisions,
        all_hours=report.all_hours,
        counts={**catalog_counts, **report.counts},
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
