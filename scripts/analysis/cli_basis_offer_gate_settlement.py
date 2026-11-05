"""CLI-basis candidate #2 -- did the offered rung actually WIN? (Item 1)

WHY THIS EXISTS, AND WHAT IT ADDS TO THE OFFER-GATE SCAN
-----------------------------------------------------------
`cli_basis_offer_gate_scan.py` proves an offer EXISTED: a cheap (<= $0.05),
sized (>= `min_liquidity_contracts`) ask on an open upper-tail rung at the
moment ASOS headroom sat at 1-or-2 degrees. That is necessary but not
sufficient -- an offer that existed and then LOST is not a trading edge, it is
a free lesson. This module answers the second, decisive question: for every
qualifying station-day EVENT the scan found, did the CLI final actually
settle YES, and what would the realized paper P&L have been, net of the real
venue fee?

We hold NWS settlement truth for every past day WITHOUT any network call: the
live ingest pipeline already writes one `NwsClimateDay` record per station
per revision into a dedicated, per-station `ParquetDataCatalog`
(`~/.local/share/breezy/catalog/polymarket_us/<STATION>/`), completely
independent of the AAFOS-zip archive cache the historical boundary study
reads (that cache holds only 2021-2025 windows and has NOT been asked to
fetch 2026 -- confirmed by probing it directly; every attempt raises the
cache-miss refusal). This is a DIFFERENT, already-populated native source,
and it is the one `docs/evidence/print_lock_refuted_2026-09-01.md` already
drew on to report each station's actual winning bucket for 2026-08-31.

NULL HYPOTHESIS, checked before this module was written (L-1, L-11)
---------------------------------------------------------------------
* `breezy.persistence.catalog.open_station_catalog` /
  `read_climate_day_including_corrections` -- the SANCTIONED reader for "what
  does Breezy now believe settled, corrections included" (its own docstring
  names this exact use: "audit, monitoring, truth reconstruction"). Reused
  verbatim via import. NATIVE-EXISTS-AND-REUSED. (Its sibling,
  `read_climate_day_as_of_settlement`, is for a live settlement/reconciliation
  decision that needs a venue deadline bound; this is a retrospective
  measurement, so the unbounded "current belief" reader is the right one, not
  a workaround.)
* `breezy.domain.nws_climate_day.NwsClimateDay` -- the settlement record type.
  Reused verbatim via import.
* `k1_cheap_open_settlement.settles_yes` (itself a thin pass-through to
  `settlement_truth_dataset.settles_yes` -> `WeatherBucketFacts.contains`) --
  THE settlement predicate. Reused verbatim via import, so this module cannot
  end up with a second, silently-diverging definition of "did tmax_f settle
  this rung".
  `price_conditional_settlement_analysis.model_fee_for_contracts` -- the real
  venue fee formula (`theta * contracts * p * (1 - p)`, banker's-rounded),
  already extracted there for exactly this kind of retrospective, no-live-
  Nautilus-Order arithmetic. `theta` is read per event from the scan's own
  `StationDayResult.fee_coefficient` (itself read from the market's
  `FEE_COEFFICIENT_KEY`, never hardcoded) -- reused verbatim via import.
  NATIVE-EXISTS-AND-REUSED.
* `cli_basis_offer_gate_scan.build_scan` / `StationDayResult` / `AskLevel` --
  the offer-gate scan itself, extended (this same effort) to carry the peak
  qualifying instant's strike, full ask-level breakdown, and fee facts
  forward on every `event=True` row specifically so this module never has to
  re-open or re-parse the quote tape. Reused verbatim via import.

* A join from a scan's `StationDayResult` events to their settlement record
  and a realized-P&L calculator applying the fee PER LEVEL (never on the
  aggregate notional, because the fee formula is non-linear in price) does
  NOT exist upstream. GENUINE GAP -- narrow, and built entirely from the
  pieces above.

HANDLING "NOT YET SETTLED" HONESTLY (L-8's discipline, applied to settlement)
------------------------------------------------------------------------------
A day whose CLI has not gone FINAL (or has no record at all, or is a
FINAL-but-sentinel/missing-`tmax_f` reading) resolves to `PENDING`, never
`NO`. `LESSONS L-8` refuses to read a zero as a quiet market until the tape is
verified; the same discipline applies here to settlement: an absence must
never silently become a loss (or a win).
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Final, Literal, cast

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cli_basis_offer_gate_scan import (
    DEFAULT_QUOTE_TAPE_PATH,
    StationDayResult,
    build_scan,
)
from k1_cheap_open_settlement import settles_yes
from price_conditional_settlement_analysis import model_fee_for_contracts

from breezy.domain.nws_climate_day import NwsClimateDay
from breezy.persistence.catalog import (
    open_station_catalog,
    read_climate_day_including_corrections,
)

__all__ = [
    "DEFAULT_NWS_CATALOG_BASE",
    "DEFAULT_SETTLEMENT_OUTPUT_PATH",
    "VENUE",
    "EventRealizedOutcome",
    "SettlementOutcome",
    "aggregate_realized_pnl",
    "build_settlement_report",
    "is_settlement_grade",
    "main",
    "realized_pnl_for_event",
    "render_settlement_report",
    "resolve_settlement_record",
    "settlement_outcome",
]

VENUE: Final[str] = "polymarket_us"

#: One `ParquetDataCatalog` per station, written by the live NWS ingest
#: pipeline -- see `breezy.persistence.catalog` module docstring for why this
#: is one root per `(venue, city)` rather than one shared catalog.
DEFAULT_NWS_CATALOG_BASE: Final[Path] = Path.home() / ".local/share/breezy/catalog"

DEFAULT_SETTLEMENT_OUTPUT_PATH: Final[Path] = Path(
    "docs/evidence/cli_basis_offer_gate_settlement_placeholder.md"
)

SettlementOutcome = Literal["YES", "NO", "PENDING"]


# ---------------------------------------------------------------------------
# Settlement resolution
# ---------------------------------------------------------------------------


def resolve_settlement_record(
    *, catalog_base: Path, venue: str, station: str, climate_day: dt.date
) -> NwsClimateDay | None:
    """The station's CURRENT belief for `climate_day` -- corrections included.

    Thin wrapper around the two sanctioned, already-existing accessors. No
    network access: `open_station_catalog` only opens a local
    `ParquetDataCatalog` directory (creating it, empty, if missing), and the
    read is local Parquet I/O.
    """
    catalog = open_station_catalog(catalog_base, venue, station)
    return read_climate_day_including_corrections(catalog, station=station, climate_day=climate_day)


def is_settlement_grade(record: NwsClimateDay | None) -> bool:
    """A FINAL, non-superseded record with a real (non-sentinel) `tmax_f`.

    All three conditions are required: a corrected-away final
    (`is_superseded`) is not the answer the venue paid on; a sentinel/missing
    `tmax_f` on an otherwise-FINAL record cannot be compared to a strike at
    all. Anything short of all three means "we cannot honestly say", which is
    `PENDING`, never a fabricated YES or NO.
    """
    return (
        record is not None
        and record.is_final
        and not record.is_superseded
        and record.tmax_f is not None
    )


def settlement_outcome(*, record: NwsClimateDay | None, strike_f: int) -> SettlementOutcome:
    """`YES` / `NO` / `PENDING` for one open-tail rung `>= strike_f`.

    `PENDING` covers every case where the answer is not yet knowable: no
    record at all, a preliminary-only record, a corrected-away record, or a
    FINAL whose `tmax_f` is itself a sentinel/missing reading. Never assumes;
    never lets a pending day count as a loss or a win (L-8's discipline,
    applied to settlement truth rather than tape coverage).
    """
    if not is_settlement_grade(record):
        return "PENDING"
    assert record is not None and record.tmax_f is not None  # narrowed above
    return "YES" if settles_yes(record.tmax_f, lower_f=strike_f, upper_f=None) else "NO"


# ---------------------------------------------------------------------------
# Realized P&L -- fee applied PER LEVEL, never on the aggregate notional
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EventRealizedOutcome:
    """One admissible station-day event's settlement join and realized P&L.

    `fee_paid` / `realized_pnl` are `None` exactly when the event's
    fee-coefficient could not be read (`StationDayResult.fee_coefficient` is
    `None`) -- an unknown fee is reported as unknown, never silently treated
    as zero (the same refusal `assert_fee_schedule_known` enforces live).
    """

    station: str
    climate_day: dt.date
    strike_f: int
    outcome: SettlementOutcome
    settlement_tmax_f: int | None
    contracts: Decimal
    notional_paid: Decimal
    fee_paid: Decimal | None
    realized_pnl: Decimal | None


def realized_pnl_for_event(
    *, result: StationDayResult, record: NwsClimateDay | None
) -> EventRealizedOutcome:
    """Join one qualifying event to settlement truth and price the outcome.

    Uses the PEAK-notional instant's full level breakdown
    (`result.peak_levels`), matching the scan's own no-double-counting
    convention (the same resting liquidity sampled on repeated polls is one
    unit, not one per poll). The fee is computed PER LEVEL and summed --
    `theta * C * p * (1 - p)` is concave in `p`, so pricing it off a single
    notional-weighted average price would systematically misstate it.
    """
    if result.strike_f is None:
        raise ValueError(
            f"{result.station} {result.climate_day.isoformat()}: cannot price a "
            "realized outcome for a non-event StationDayResult (no strike recorded)"
        )
    outcome = settlement_outcome(record=record, strike_f=result.strike_f)
    contracts = _sum_decimal(level.size for level in result.peak_levels)
    notional_paid = _sum_decimal(level.price * level.size for level in result.peak_levels)

    fee_paid: Decimal | None = None
    if result.fee_coefficient is not None and result.quote_currency_precision is not None:
        fee_paid = _sum_decimal(
            model_fee_for_contracts(
                theta=result.fee_coefficient,
                contracts=level.size,
                executable_price=level.price,
                currency_precision=result.quote_currency_precision,
            )
            for level in result.peak_levels
        )

    realized_pnl: Decimal | None = None
    if outcome != "PENDING" and fee_paid is not None:
        payout = contracts if outcome == "YES" else Decimal(0)
        realized_pnl = payout - notional_paid - fee_paid

    return EventRealizedOutcome(
        station=result.station,
        climate_day=result.climate_day,
        strike_f=result.strike_f,
        outcome=outcome,
        settlement_tmax_f=record.tmax_f if record is not None else None,
        contracts=contracts,
        notional_paid=notional_paid,
        fee_paid=fee_paid,
        realized_pnl=realized_pnl,
    )


def _sum_decimal(values: Iterable[Decimal]) -> Decimal:
    total = Decimal(0)
    for value in values:
        total += value
    return total


def aggregate_realized_pnl(outcomes: Sequence[EventRealizedOutcome]) -> Decimal | None:
    """Sum `realized_pnl` across every RESOLVED (non-`PENDING`, fee-known)
    outcome. `None` when nothing is resolved yet -- never silently `0`.
    """
    resolved = [o.realized_pnl for o in outcomes if o.realized_pnl is not None]
    if not resolved:
        return None
    return _sum_decimal(resolved)


# ---------------------------------------------------------------------------
# Orchestration + report
# ---------------------------------------------------------------------------


def build_settlement_report(
    *,
    tape_root: Path,
    asos_cache_dir: Path,
    catalog_base: Path,
    now_ns: int | None = None,
) -> dict[str, object]:
    """Run the offer-gate scan, then join every event to settlement truth."""
    scan = build_scan(tape_root=tape_root, asos_cache_dir=asos_cache_dir, now_ns=now_ns)
    results = cast("Sequence[StationDayResult]", scan["station_day_results"])

    outcomes: list[EventRealizedOutcome] = []
    for result in results:
        if not result.event:
            continue
        record = resolve_settlement_record(
            catalog_base=catalog_base,
            venue=VENUE,
            station=result.station,
            climate_day=result.climate_day,
        )
        outcomes.append(realized_pnl_for_event(result=result, record=record))

    return {
        "scan": scan,
        "outcomes": tuple(outcomes),
        "aggregate_realized_pnl": aggregate_realized_pnl(outcomes),
    }


def render_settlement_report(report: dict[str, object]) -> str:
    outcomes = cast("Sequence[EventRealizedOutcome]", report["outcomes"])
    lines: list[str] = []
    add = lines.append
    add("# CLI-basis candidate #2 -- did the offered rung actually WIN? (Item 1)")
    add("")
    add(
        "Realized-outcome join of every qualifying offer-gate event against "
        "NWS settlement truth, held natively in "
        "`breezy.persistence.catalog` -- zero network."
    )
    add("")
    if not outcomes:
        add("No qualifying (`event=True`) station-day exists yet. Nothing to join.")
        add("")
        return "\n".join(lines) + "\n"

    add(
        "| Station | Climate day | Strike | Settled tmax | Outcome | Contracts | "
        "Notional paid | Fee | Realized P&L |"
    )
    add("|---|---|---:|---:|:--:|---:|---:|---:|---:|")
    for outcome in outcomes:
        add(
            f"| {outcome.station} | {outcome.climate_day.isoformat()} | "
            f"gte{outcome.strike_f}f | "
            f"{outcome.settlement_tmax_f if outcome.settlement_tmax_f is not None else '-'} | "
            f"{outcome.outcome} | {outcome.contracts} | {outcome.notional_paid} | "
            f"{outcome.fee_paid if outcome.fee_paid is not None else 'unknown'} | "
            f"{outcome.realized_pnl if outcome.realized_pnl is not None else '-'} |"
        )
    add("")

    aggregate = report["aggregate_realized_pnl"]
    pending = sum(1 for o in outcomes if o.outcome == "PENDING")
    resolved = len(outcomes) - pending
    add(
        f"Resolved: {resolved}/{len(outcomes)} (pending: {pending}). "
        f"Aggregate realized P&L across resolved events: "
        f"{aggregate if aggregate is not None else 'undetermined -- nothing resolved yet'}."
    )
    add("")
    return "\n".join(lines) + "\n"


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quote-tape", default=DEFAULT_QUOTE_TAPE_PATH.as_posix())
    parser.add_argument("--asos-cache")
    parser.add_argument("--nws-catalog-base", default=DEFAULT_NWS_CATALOG_BASE.as_posix())
    parser.add_argument("--output", default=DEFAULT_SETTLEMENT_OUTPUT_PATH.as_posix())
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    from cli_basis_offer_gate_scan import DEFAULT_ASOS_CACHE_DIR

    args = _parse_args(argv)
    tape_root = Path(args.quote_tape)
    asos_cache_dir = Path(args.asos_cache) if args.asos_cache else DEFAULT_ASOS_CACHE_DIR
    catalog_base = Path(args.nws_catalog_base)
    output_path = Path(args.output)

    if not tape_root.exists():
        raise FileNotFoundError(f"quote tape not found: {tape_root}")

    report = build_settlement_report(
        tape_root=tape_root, asos_cache_dir=asos_cache_dir, catalog_base=catalog_base
    )
    rendered = render_settlement_report(report)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered, encoding="utf-8")
    print(f"wrote {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
