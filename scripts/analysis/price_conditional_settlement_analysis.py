"""Price-conditional weather settlement threshold analysis.

This is not a P&L, ROI, or simulated trading result. It derives break-even
price thresholds from deterministic realized NWS settlement outcomes, an
anti-lookahead climatological base rate, and the real Polymarket.us fee
formula. Any realized profit claim would require historical executable prices,
fills, sizes, depth, and slippage; those do not exist for pre-2026 weather
markets and are deliberately not fabricated here.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal, getcontext
from pathlib import Path
from typing import Any, Final, Literal, cast

import pyarrow.parquet as pq
from nautilus_trader.model.data import QuoteTick
from nautilus_trader.model.instruments import BinaryOption
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog
from settlement_alignment_study import wilson_lower_bound

from breezy.adapters.polymarket_us.fees import PolymarketUSFeeModel
from breezy.adapters.polymarket_us.parsing import FEE_COEFFICIENT_KEY
from breezy.domain.weather_bucket_facts import Measure, WeatherBucketFacts

DEFAULT_SETTLEMENT_TRUTH_PATH: Final[Path] = Path(
    "/home/jon/.local/share/breezy/derived/settlement-truth/settlement_truth.parquet"
)
DEFAULT_QUOTE_CATALOG_PATH: Final[Path] = Path(
    "/home/jon/.local/share/breezy/catalog/quote_tape/polymarket_us"
)
DEFAULT_OUTPUT_PATH: Final[Path] = Path(
    "/home/jon/.local/share/breezy/derived/price-conditional-settlement-analysis/"
    "price_conditional_settlement_analysis.json"
)
DEFAULT_THETA: Final[Decimal] = Decimal("0.06")
DEFAULT_DAY_WINDOW_RADIUS: Final[int] = 15
DEFAULT_MIN_SAMPLE_FLOOR: Final[int] = 100
PRICE_GRID: Final[tuple[Decimal, ...]] = tuple(Decimal(i) / Decimal(100) for i in range(101))
Z_95: Final[float] = 1.959963984540054

__all__ = [
    "BaseRateCell",
    "PolymarketUSFeeModel",
    "TargetCell",
    "TruthRow",
    "break_even_executable_price",
    "compute_base_rate_cell",
    "main",
    "model_fee_for_contracts",
]

SampleScope = Literal["within_expected_window", "including_spillover"]
QuotePosition = Literal[
    "PROFITABLE_SIDE",
    "UNPROFITABLE_SIDE",
    "INSIDE_UNCERTAINTY_INTERVAL",
    "UNDERPOWERED",
]


@dataclass(frozen=True, slots=True)
class TruthRow:
    station: str
    climate_day: dt.date
    tmax_f: int
    within_expected_window: bool


@dataclass(frozen=True, slots=True)
class TargetCell:
    station: str
    climate_day: dt.date
    lower_f: int | None
    upper_f: int | None
    bucket_slug: str
    bucket_parity: str
    instrument_id: str
    theta: Decimal = DEFAULT_THETA


@dataclass(frozen=True, slots=True)
class BaseRateCell:
    station: str
    climate_day: dt.date
    bucket_slug: str
    bucket_parity: str
    lower_f: int | None
    upper_f: int | None
    sample_scope: SampleScope
    day_window_radius: int
    excluded_year: int
    observation_years: tuple[int, ...]
    sample_count: int
    yes_count: int
    no_count: int
    yes_rate: float | None
    yes_wilson_95_lower: float | None
    yes_wilson_95_upper: float | None
    no_rate: float | None
    no_wilson_95_lower: float | None
    no_wilson_95_upper: float | None
    verdict: str
    instrument_id: str
    theta: Decimal


@dataclass(frozen=True, slots=True)
class QuoteObservation:
    instrument_id: str
    bid_price: Decimal
    ask_price: Decimal
    bid_size: Decimal
    ask_size: Decimal
    ts_event: int
    ts_init: int


def _decimal(value: object, *, field: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except Exception as exc:
        raise ValueError(f"{field}: expected decimal-compatible value, got {value!r}") from exc
    if not result.is_finite():
        raise ValueError(f"{field}: expected finite decimal, got {value!r}")
    return result


def venue_fee_per_contract(*, theta: Decimal, executable_price: Decimal) -> Decimal:
    """Return the unrounded fee probability: theta * p * (1 - p)."""
    _require_probability(executable_price, "executable_price")
    _require_probability(theta, "theta")
    return theta * executable_price * (Decimal(1) - executable_price)


def model_fee_for_contracts(
    *,
    theta: Decimal,
    contracts: Decimal,
    executable_price: Decimal,
    currency_precision: int,
) -> Decimal:
    """Return the rounded fee for ``contracts`` using the real venue formula."""
    if contracts < 0:
        raise ValueError("contracts must be non-negative")
    exact = contracts * venue_fee_per_contract(theta=theta, executable_price=executable_price)
    quantum = Decimal(1).scaleb(-currency_precision)
    return exact.quantize(quantum, rounding=ROUND_HALF_EVEN)


def break_even_executable_price(*, event_probability: Decimal, theta: Decimal) -> Decimal:
    """Solve x + theta*x*(1-x) == event_probability for executable price x."""
    _require_probability(event_probability, "event_probability")
    _require_probability(theta, "theta")
    if event_probability == 0:
        return Decimal(0)
    if event_probability == 1:
        return Decimal(1)

    getcontext().prec = max(getcontext().prec, 40)
    low = Decimal(0)
    high = Decimal(1)
    for _ in range(100):
        mid = (low + high) / Decimal(2)
        cost = mid + venue_fee_per_contract(theta=theta, executable_price=mid)
        if cost <= event_probability:
            low = mid
        else:
            high = mid
    return (low + high) / Decimal(2)


def compute_base_rate_cell(
    rows: Iterable[Mapping[str, Any]] | Iterable[TruthRow],
    *,
    target: TargetCell,
    sample_scope: SampleScope,
    day_window_radius: int,
    min_sample_floor: int,
) -> BaseRateCell:
    truth_rows = _coerce_truth_rows(rows)
    excluded_year = target.climate_day.year
    target_doy = _day_of_year(target.climate_day)
    sample: list[TruthRow] = []
    facts = WeatherBucketFacts(
        settlement_station=target.station,
        climate_day=target.climate_day,
        measure=Measure.HIGH,
        lower_f=target.lower_f,
        upper_f=target.upper_f,
    )
    for row in truth_rows:
        if row.station != target.station:
            continue
        if row.climate_day.year == excluded_year:
            continue
        if sample_scope == "within_expected_window" and not row.within_expected_window:
            continue
        if _circular_day_distance(target_doy, _day_of_year(row.climate_day)) > day_window_radius:
            continue
        sample.append(row)

    sample_count = len(sample)
    yes_count = sum(1 for row in sample if facts.contains(row.tmax_f))
    no_count = sample_count - yes_count
    observation_years = tuple(sorted({row.climate_day.year for row in sample}))
    if sample_count < min_sample_floor:
        return BaseRateCell(
            station=target.station,
            climate_day=target.climate_day,
            bucket_slug=target.bucket_slug,
            bucket_parity=target.bucket_parity,
            lower_f=target.lower_f,
            upper_f=target.upper_f,
            sample_scope=sample_scope,
            day_window_radius=day_window_radius,
            excluded_year=excluded_year,
            observation_years=observation_years,
            sample_count=sample_count,
            yes_count=yes_count,
            no_count=no_count,
            yes_rate=None,
            yes_wilson_95_lower=None,
            yes_wilson_95_upper=None,
            no_rate=None,
            no_wilson_95_lower=None,
            no_wilson_95_upper=None,
            verdict="UNDERPOWERED",
            instrument_id=target.instrument_id,
            theta=target.theta,
        )

    yes_rate = yes_count / sample_count
    yes_lower = wilson_lower_bound(yes_count, sample_count, z=Z_95)
    yes_upper = 1.0 - wilson_lower_bound(no_count, sample_count, z=Z_95)
    no_rate = no_count / sample_count
    no_lower = wilson_lower_bound(no_count, sample_count, z=Z_95)
    no_upper = 1.0 - wilson_lower_bound(yes_count, sample_count, z=Z_95)
    return BaseRateCell(
        station=target.station,
        climate_day=target.climate_day,
        bucket_slug=target.bucket_slug,
        bucket_parity=target.bucket_parity,
        lower_f=target.lower_f,
        upper_f=target.upper_f,
        sample_scope=sample_scope,
        day_window_radius=day_window_radius,
        excluded_year=excluded_year,
        observation_years=observation_years,
        sample_count=sample_count,
        yes_count=yes_count,
        no_count=no_count,
        yes_rate=yes_rate,
        yes_wilson_95_lower=yes_lower,
        yes_wilson_95_upper=yes_upper,
        no_rate=no_rate,
        no_wilson_95_lower=no_lower,
        no_wilson_95_upper=no_upper,
        verdict="PASS",
        instrument_id=target.instrument_id,
        theta=target.theta,
    )


def load_settlement_truth(path: Path) -> tuple[list[TruthRow], dict[str, int]]:
    if not path.exists():
        raise FileNotFoundError(path)
    raw_rows = _load_json_rows(path) if path.suffix == ".json" else _load_parquet_rows(path)
    rows: list[TruthRow] = []
    final_rows = 0
    final_non_null_tmax_rows = 0
    final_non_null_within_rows = 0
    final_non_null_spillover_rows = 0
    for raw in raw_rows:
        if raw.get("status") != "FINAL":
            continue
        final_rows += 1
        if raw.get("tmax_f") is None:
            continue
        final_non_null_tmax_rows += 1
        row = _truth_row_from_mapping(raw)
        rows.append(row)
        if row.within_expected_window:
            final_non_null_within_rows += 1
        else:
            final_non_null_spillover_rows += 1
    summary = {
        "raw_rows": len(raw_rows),
        "final_rows": final_rows,
        "eligible_final_non_null_tmax_rows": final_non_null_tmax_rows,
        "eligible_within_expected_window_rows": final_non_null_within_rows,
        "eligible_spillover_rows": final_non_null_spillover_rows,
    }
    return rows, summary


def load_live_targets_and_quotes(
    catalog_path: Path,
) -> tuple[list[TargetCell], dict[str, QuoteObservation]]:
    if not catalog_path.exists():
        raise FileNotFoundError(catalog_path)
    catalog = ParquetDataCatalog(catalog_path)
    quote_rows = cast(Iterable[QuoteTick], catalog.query(data_cls=QuoteTick))
    latest_quotes: dict[str, QuoteObservation] = {}
    for quote in quote_rows:
        instrument_id = str(quote.instrument_id)
        observed = QuoteObservation(
            instrument_id=instrument_id,
            bid_price=quote.bid_price.as_decimal(),
            ask_price=quote.ask_price.as_decimal(),
            bid_size=quote.bid_size.as_decimal(),
            ask_size=quote.ask_size.as_decimal(),
            ts_event=int(quote.ts_event),
            ts_init=int(quote.ts_init),
        )
        previous = latest_quotes.get(instrument_id)
        if previous is None or observed.ts_init > previous.ts_init:
            latest_quotes[instrument_id] = observed

    instruments = cast(Iterable[BinaryOption], catalog.query(data_cls=BinaryOption))
    targets: list[TargetCell] = []
    for instrument in instruments:
        instrument_id = str(instrument.id)
        if instrument_id not in latest_quotes:
            continue
        targets.append(_target_from_instrument(instrument))
    targets.sort(key=lambda item: item.instrument_id)
    return targets, latest_quotes


def build_artifact(
    *,
    truth_rows: Sequence[TruthRow],
    input_summary: Mapping[str, int],
    targets: Sequence[TargetCell],
    quotes: Mapping[str, QuoteObservation],
    generated_at_utc: dt.datetime,
    settlement_truth_path: Path,
    quote_catalog_path: Path | None,
    output_path: Path,
    day_window_radius: int,
    min_sample_floor: int,
) -> dict[str, Any]:
    cells = [
        compute_base_rate_cell(
            truth_rows,
            target=target,
            sample_scope=scope,
            day_window_radius=day_window_radius,
            min_sample_floor=min_sample_floor,
        )
        for target in targets
        for scope in ("within_expected_window", "including_spillover")
    ]
    powered_count = sum(1 for cell in cells if cell.verdict != "UNDERPOWERED")
    underpowered_count = len(cells) - powered_count
    comparisons = [
        _quote_comparison_payload(cell, quotes[cell.instrument_id])
        for cell in cells
        if cell.instrument_id in quotes
    ]
    live_sample = "skipped" if quote_catalog_path is None else f"{len(quotes)} quoted instruments"
    payload: dict[str, Any] = {
        "schema": {
            "artifact_version": 1,
            "base_rate_cells": _base_rate_schema(),
            "break_even_curve_points": _curve_schema(),
            "live_quote_comparisons": _quote_schema(),
        },
        "metadata": {
            "generated_at_utc": generated_at_utc.isoformat().replace("+00:00", "Z"),
            "settlement_truth_path": settlement_truth_path.as_posix(),
            "quote_catalog_path": (
                None if quote_catalog_path is None else quote_catalog_path.as_posix()
            ),
            "output_path": output_path.as_posix(),
        },
        "methodology": {
            "not_pnl_or_roi": True,
            "anti_lookahead": "leave_one_year_out",
            "day_of_year_window": f"+/-{day_window_radius} days",
            "day_of_year_window_justification": (
                "A +/-15 day window balances seasonality against sample size: with "
                "roughly five complete prior years it yields about 155 same-season "
                "station observations per target cell before spillover filtering."
            ),
            "sample_floor": min_sample_floor,
            "sample_floor_status": (
                "Pre-stated before cell computation; cells below this floor are "
                "UNDERPOWERED and their rates are not reported."
            ),
            "fee_formula": "theta * contracts * executable_price * (1 - executable_price)",
            "fee_theta_default": str(DEFAULT_THETA),
            "bucket_predicate": "WeatherBucketFacts.contains; finite bounds are inclusive",
            "anchor_parity_note": (
                "Historical ladder anchor parity is not inferred. Target cells carry the "
                "observed instrument bucket parity label only, and no parity is presented "
                "as the historical ladder."
            ),
        },
        "limitations": [
            "This is not a P&L, ROI, or simulated trading result.",
            "It produces break-even executable price thresholds only.",
            (
                "Any realized profit statement would require actual fills, sizes, depth, "
                "and slippage at historical market prices, which are unavailable."
            ),
            (
                "The live quote confrontation is one afternoon across five quoted "
                "instruments; it is an existence check, not evidence of edge."
            ),
            "Missing or underpowered cells are refused rather than imputed.",
        ],
        "input_summary": dict(input_summary),
        "summary": {
            "target_cells": len(targets),
            "base_rate_cells": len(cells),
            "powered_cells": powered_count,
            "underpowered_cells": underpowered_count,
            "live_quote_sample": live_sample,
        },
        "base_rate_cells": [_base_rate_payload(cell) for cell in cells],
        "break_even_curves": [_break_even_curve_payload(cell) for cell in cells],
        "fee_gap_vs_flat_0_015": _flat_fee_gap_payload(DEFAULT_THETA),
        "live_quote_comparisons": comparisons,
    }
    return payload


def write_artifact(payload: Mapping[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    generated_at = _parse_generated_at(cast(str | None, args.generated_at_utc))
    settlement_truth_path = Path(cast(str, args.settlement_truth))
    output_path = Path(cast(str, args.output))
    day_window_radius = cast(int, args.day_window_radius)
    min_sample_floor = cast(int, args.min_sample_floor)
    truth_rows, input_summary = load_settlement_truth(settlement_truth_path)
    if cast(bool, args.skip_live_quotes):
        targets = [_parse_target_arg(value) for value in cast(list[str], args.target)]
        quote_catalog_path: Path | None = None
        quotes: dict[str, QuoteObservation] = {}
    else:
        quote_catalog_path = Path(cast(str, args.quote_catalog))
        targets, quotes = load_live_targets_and_quotes(quote_catalog_path)
    if not targets:
        raise ValueError("No target cells available; supply --target or a readable quote catalog")

    payload = build_artifact(
        truth_rows=truth_rows,
        input_summary=input_summary,
        targets=targets,
        quotes=quotes,
        generated_at_utc=generated_at,
        settlement_truth_path=settlement_truth_path,
        quote_catalog_path=quote_catalog_path,
        output_path=output_path,
        day_window_radius=day_window_radius,
        min_sample_floor=min_sample_floor,
    )
    write_artifact(payload, output_path)
    return 0


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--settlement-truth", default=DEFAULT_SETTLEMENT_TRUTH_PATH.as_posix())
    parser.add_argument("--quote-catalog", default=DEFAULT_QUOTE_CATALOG_PATH.as_posix())
    parser.add_argument("--output", default=DEFAULT_OUTPUT_PATH.as_posix())
    parser.add_argument("--day-window-radius", type=int, default=DEFAULT_DAY_WINDOW_RADIUS)
    parser.add_argument("--min-sample-floor", type=int, default=DEFAULT_MIN_SAMPLE_FLOOR)
    parser.add_argument("--generated-at-utc")
    parser.add_argument(
        "--skip-live-quotes",
        action="store_true",
        help="Use only explicit --target values and do not read the live quote catalog.",
    )
    parser.add_argument(
        "--target",
        action="append",
        default=[],
        help=(
            "Explicit target as station,date,lower,upper,slug,instrument_id. Use empty "
            "lower or upper for open-ended buckets."
        ),
    )
    parsed = parser.parse_args(argv)
    if parsed.day_window_radius < 0 or parsed.day_window_radius > 183:
        parser.error("--day-window-radius must be between 0 and 183")
    if parsed.min_sample_floor < 1:
        parser.error("--min-sample-floor must be positive")
    if parsed.skip_live_quotes and not parsed.target:
        parser.error("--skip-live-quotes requires at least one --target")
    return parsed


def _parse_generated_at(raw: str | None) -> dt.datetime:
    if raw is None:
        return dt.datetime.now(dt.UTC)
    normalized = raw.removesuffix("Z") + "+00:00" if raw.endswith("Z") else raw
    parsed = dt.datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        raise ValueError("--generated-at-utc must include a timezone")
    return parsed.astimezone(dt.UTC)


def _parse_target_arg(raw: str) -> TargetCell:
    parts = raw.split(",", 5)
    if len(parts) != 6:
        raise ValueError(
            "--target must be station,date,lower,upper,slug,instrument_id with six fields"
        )
    station, raw_date, raw_lower, raw_upper, slug, instrument_id = parts
    lower = None if raw_lower == "" else int(raw_lower)
    upper = None if raw_upper == "" else int(raw_upper)
    climate_day = dt.date.fromisoformat(raw_date)
    return TargetCell(
        station=station,
        climate_day=climate_day,
        lower_f=lower,
        upper_f=upper,
        bucket_slug=slug,
        bucket_parity=_bucket_parity(lower, upper),
        instrument_id=instrument_id,
    )


def _target_from_instrument(instrument: BinaryOption) -> TargetCell:
    info = instrument.info
    station = str(info["settlement_station"])
    climate_day = dt.date.fromisoformat(str(info["climate_date"]))
    lower = cast(int | None, info["strike_lower_f"])
    upper = cast(int | None, info["strike_upper_f"])
    theta = _decimal(info.get(FEE_COEFFICIENT_KEY, DEFAULT_THETA), field=FEE_COEFFICIENT_KEY)
    return TargetCell(
        station=station,
        climate_day=climate_day,
        lower_f=lower,
        upper_f=upper,
        bucket_slug=str(info["slug"]),
        bucket_parity=_bucket_parity(lower, upper),
        instrument_id=str(instrument.id),
        theta=theta,
    )


def _bucket_parity(lower: int | None, upper: int | None) -> str:
    if lower is not None:
        return "even_anchor" if lower % 2 == 0 else "odd_anchor"
    if upper is not None:
        threshold = upper + 1
        return "even_anchor" if threshold % 2 == 0 else "odd_anchor"
    raise ValueError("bucket must have at least one finite bound")


def _load_json_rows(path: Path) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise TypeError(f"{path}: expected a JSON list")
    return [cast(dict[str, Any], item) for item in raw]


def _load_parquet_rows(path: Path) -> list[dict[str, Any]]:
    table = pq.read_table(path)
    columns = cast(dict[str, list[Any]], table.to_pydict())
    rows: list[dict[str, Any]] = []
    for idx in range(table.num_rows):
        rows.append({name: values[idx] for name, values in columns.items()})
    return rows


def _truth_row_from_mapping(row: Mapping[str, Any]) -> TruthRow:
    day = row["climate_day"]
    if isinstance(day, dt.datetime):
        climate_day = day.date()
    elif isinstance(day, dt.date):
        climate_day = day
    else:
        climate_day = dt.date.fromisoformat(str(day))
    return TruthRow(
        station=str(row["station"]),
        climate_day=climate_day,
        tmax_f=int(row["tmax_f"]),
        within_expected_window=bool(row.get("within_expected_window", True)),
    )


def _coerce_truth_rows(rows: Iterable[Mapping[str, Any]] | Iterable[TruthRow]) -> list[TruthRow]:
    result: list[TruthRow] = []
    for row in rows:
        if isinstance(row, TruthRow):
            result.append(row)
        else:
            result.append(_truth_row_from_mapping(row))
    return result


def _day_of_year(day: dt.date) -> int:
    return day.timetuple().tm_yday


def _circular_day_distance(left: int, right: int) -> int:
    distance = abs(left - right)
    return min(distance, 366 - distance)


def _require_probability(value: Decimal, name: str) -> None:
    if value < 0 or value > 1:
        raise ValueError(f"{name} must be in [0, 1], got {value}")


def _threshold_payload(
    *,
    probability: float | None,
    lower: float | None,
    upper: float | None,
    theta: Decimal,
) -> dict[str, str | None]:
    if probability is None or lower is None or upper is None:
        return {"lower": None, "point": None, "upper": None}
    return {
        "lower": _probability_text(
            break_even_executable_price(event_probability=Decimal(str(lower)), theta=theta)
        ),
        "point": _probability_text(
            break_even_executable_price(event_probability=Decimal(str(probability)), theta=theta)
        ),
        "upper": _probability_text(
            break_even_executable_price(event_probability=Decimal(str(upper)), theta=theta)
        ),
    }


def _break_even_curve_payload(cell: BaseRateCell) -> dict[str, Any]:
    yes_threshold = _threshold_payload(
        probability=cell.yes_rate,
        lower=cell.yes_wilson_95_lower,
        upper=cell.yes_wilson_95_upper,
        theta=cell.theta,
    )
    no_threshold = _threshold_payload(
        probability=cell.no_rate,
        lower=cell.no_wilson_95_lower,
        upper=cell.no_wilson_95_upper,
        theta=cell.theta,
    )
    return {
        "instrument_id": cell.instrument_id,
        "station": cell.station,
        "climate_day": cell.climate_day.isoformat(),
        "bucket_slug": cell.bucket_slug,
        "bucket_parity": cell.bucket_parity,
        "sample_scope": cell.sample_scope,
        "verdict": cell.verdict,
        "theta": str(cell.theta),
        "yes_break_even_executable_price": yes_threshold,
        "no_break_even_executable_price": no_threshold,
        "curve_points": _curve_points(cell),
    }


def _curve_points(cell: BaseRateCell) -> list[dict[str, str | None]]:
    if cell.yes_rate is None or cell.no_rate is None:
        return []
    yes_probability = Decimal(str(cell.yes_rate))
    no_probability = Decimal(str(cell.no_rate))
    points: list[dict[str, str | None]] = []
    for price in PRICE_GRID:
        fee = venue_fee_per_contract(theta=cell.theta, executable_price=price)
        points.append(
            {
                "executable_price": _probability_text(price),
                "fee_probability": _probability_text(fee),
                "yes_expected_value": _probability_text(yes_probability - price - fee),
                "no_expected_value": _probability_text(no_probability - price - fee),
            }
        )
    return points


def _quote_comparison_payload(cell: BaseRateCell, quote: QuoteObservation) -> dict[str, Any]:
    yes_threshold = _threshold_payload(
        probability=cell.yes_rate,
        lower=cell.yes_wilson_95_lower,
        upper=cell.yes_wilson_95_upper,
        theta=cell.theta,
    )
    no_threshold = _threshold_payload(
        probability=cell.no_rate,
        lower=cell.no_wilson_95_lower,
        upper=cell.no_wilson_95_upper,
        theta=cell.theta,
    )
    no_ask = Decimal(1) - quote.bid_price
    no_bid = Decimal(1) - quote.ask_price
    return {
        "instrument_id": cell.instrument_id,
        "station": cell.station,
        "climate_day": cell.climate_day.isoformat(),
        "bucket_slug": cell.bucket_slug,
        "bucket_parity": cell.bucket_parity,
        "sample_scope": cell.sample_scope,
        "cell_verdict": cell.verdict,
        "yes_bid": _probability_text(quote.bid_price),
        "yes_ask": _probability_text(quote.ask_price),
        "yes_bid_position": _classify_price(quote.bid_price, yes_threshold),
        "yes_ask_position": _classify_price(quote.ask_price, yes_threshold),
        "implied_no_bid": _probability_text(no_bid),
        "implied_no_ask": _probability_text(no_ask),
        "implied_no_bid_position": _classify_price(no_bid, no_threshold),
        "implied_no_ask_position": _classify_price(no_ask, no_threshold),
        "yes_break_even_band": yes_threshold,
        "no_break_even_band": no_threshold,
        "bid_size": str(quote.bid_size),
        "ask_size": str(quote.ask_size),
        "ts_event": quote.ts_event,
        "ts_init": quote.ts_init,
        "small_sample_caveat": (
            "One afternoon and five quoted instruments only; existence check, "
            "not evidence of edge."
        ),
    }


def _classify_price(price: Decimal, band: Mapping[str, str | None]) -> QuotePosition:
    lower = band["lower"]
    upper = band["upper"]
    if lower is None or upper is None:
        return "UNDERPOWERED"
    lower_decimal = Decimal(lower)
    upper_decimal = Decimal(upper)
    if price < lower_decimal:
        return "PROFITABLE_SIDE"
    if price > upper_decimal:
        return "UNPROFITABLE_SIDE"
    return "INSIDE_UNCERTAINTY_INTERVAL"


def _flat_fee_gap_payload(theta: Decimal) -> dict[str, Any]:
    flat = Decimal("0.015")
    points = []
    max_overstatement = Decimal(0)
    max_understatement = Decimal(0)
    for price in PRICE_GRID:
        real = venue_fee_per_contract(theta=theta, executable_price=price)
        flat_minus_real = flat - real
        max_overstatement = max(max_overstatement, flat_minus_real)
        max_understatement = min(max_understatement, flat_minus_real)
        points.append(
            {
                "executable_price": _probability_text(price),
                "real_fee_probability": _probability_text(real),
                "flat_transaction_cost_probability": _probability_text(flat),
                "flat_minus_real": _probability_text(flat_minus_real),
            }
        )
    return {
        "theta": str(theta),
        "flat_transaction_cost_probability": str(flat),
        "summary": {
            "max_flat_overstatement": _probability_text(max_overstatement),
            "max_flat_understatement": _probability_text(max_understatement),
            "note": (
                "At theta=0.06 the flat 0.015 cost equals the real fee only at "
                "price 0.50 and otherwise overstates taker fee on the 0.00..1.00 grid."
            ),
        },
        "points": points,
    }


def _base_rate_payload(cell: BaseRateCell) -> dict[str, Any]:
    return {
        "instrument_id": cell.instrument_id,
        "station": cell.station,
        "climate_day": cell.climate_day.isoformat(),
        "bucket_slug": cell.bucket_slug,
        "bucket_parity": cell.bucket_parity,
        "lower_f": cell.lower_f,
        "upper_f": cell.upper_f,
        "sample_scope": cell.sample_scope,
        "day_window_radius": cell.day_window_radius,
        "excluded_year": cell.excluded_year,
        "observation_years": list(cell.observation_years),
        "sample_count": cell.sample_count,
        "yes_count": cell.yes_count,
        "no_count": cell.no_count,
        "yes_rate": _rate_or_none(cell.yes_rate),
        "yes_wilson_95_lower": _rate_or_none(cell.yes_wilson_95_lower),
        "yes_wilson_95_upper": _rate_or_none(cell.yes_wilson_95_upper),
        "no_rate": _rate_or_none(cell.no_rate),
        "no_wilson_95_lower": _rate_or_none(cell.no_wilson_95_lower),
        "no_wilson_95_upper": _rate_or_none(cell.no_wilson_95_upper),
        "verdict": cell.verdict,
        "theta": str(cell.theta),
    }


def _rate_or_none(value: float | None) -> str | None:
    if value is None:
        return None
    return f"{value:.9f}"


def _probability_text(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.000000001'))}"


def _base_rate_schema() -> dict[str, str]:
    return {
        "instrument_id": "Nautilus instrument id for the analyzed bucket",
        "station": "NWS settlement station",
        "climate_day": "Target climate day for the cell",
        "bucket_slug": "Venue bucket slug/facts label",
        "bucket_parity": "Observed bucket anchor parity label, not inferred historical parity",
        "lower_f": "Inclusive lower Fahrenheit bound, or null",
        "upper_f": "Inclusive upper Fahrenheit bound, or null",
        "sample_scope": "within_expected_window or including_spillover",
        "sample_count": "Leave-one-year-out same-season sample size",
        "yes_count": "Count whose tmax_f is contained by WeatherBucketFacts.contains",
        "yes_rate": "Empirical YES frequency, null when UNDERPOWERED",
        "yes_wilson_95_lower": "Wilson 95% lower bound, null when UNDERPOWERED",
        "yes_wilson_95_upper": "Wilson 95% upper bound, null when UNDERPOWERED",
        "verdict": "PASS when powered, UNDERPOWERED below the pre-stated floor",
    }


def _curve_schema() -> dict[str, str]:
    return {
        "yes_break_even_executable_price": "Wilson lower/point/upper YES buy threshold",
        "no_break_even_executable_price": "Wilson lower/point/upper NO buy threshold",
        "curve_points": "0.00..1.00 price grid with fee and YES/NO expected value",
    }


def _quote_schema() -> dict[str, str]:
    return {
        "yes_ask_position": "Executable YES ask versus YES break-even band",
        "implied_no_ask_position": "Executable NO ask, computed as 1 - YES bid",
        "PROFITABLE_SIDE": "Executable price is below the Wilson-lower break-even threshold",
        "UNPROFITABLE_SIDE": "Executable price is above the Wilson-upper break-even threshold",
        "INSIDE_UNCERTAINTY_INTERVAL": "Executable price falls inside the Wilson band",
    }


if __name__ == "__main__":
    raise SystemExit(main())
