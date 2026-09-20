"""WP-7 falsification -- REALISED post-fee PnL on the takes the screen made.

WHY THIS EXISTS
---------------
``docs/specs/PREREG_WP7_MULTIPLICITY_RULE_2026-09-20.md`` §3 scores
``margin = p_fc - (price + fee)``. That is MODEL-CLAIMED edge: settlement truth
enters the screen only as a join filter, so the screen never asks whether the
forecast was RIGHT. Combined with a take rule that scans every rung at every
instant and takes the FIRST positive margin (~10^4 chances per station-day), a
~90% take rate is reachable by a pure noise model.

This module asks the question §3 does not: on the takes the screen ACTUALLY
made, what did the position realise once the NWS CLI settled daily high is
known?

It is legitimately IN-SAMPLE. In-sample confirmation proves nothing; in-sample
REFUTATION is decisive. A positive number here is therefore reported as "not
refuted in-sample", never as a confirmation.

WHAT IS REUSED, AND NOTHING IS RETUNED
--------------------------------------
* the take rule: ``forecast_cheap_screen_wp7.screen_station_day``, called
  VERBATIM under all twelve registered variants. No filter is added, no take is
  dropped, no threshold is moved.
* the fee: ``forecast_tape_screen.venue_fee``, i.e. the LIVE take rule's
  ``current_rung_hold.decision.fee_on_ask``, banker's-rounded to the cent.
* the rung bounds: ``h4_preliminary_economic_read.parse_rung`` / ``Rung.contains``
  -- a CLOSED integer-°F interval. ``gte86lt87f`` settles YES on 86 AND on 87;
  the half-open reading is the one under which the ladder is not a partition.
* settlement truth: the same NWS CLI finals the screen joins on.

No network. No clock. Starts and stops no process. Writes one artefact.
"""

from __future__ import annotations

import argparse
import datetime as dt
import math
import random
import statistics
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

_SCRIPTS_ANALYSIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPTS_ANALYSIS_DIR.parents[1]
for _entry in (str(_SCRIPTS_ANALYSIS_DIR), str(_REPO_ROOT / "src")):
    if _entry not in sys.path:
        sys.path.insert(0, str(_entry))

from forecast_tape_screen import DEFAULT_FEE_COEFFICIENT, venue_fee
from h4_preliminary_economic_read import parse_rung

__all__ = [
    "CLUSTER_DATE",
    "CLUSTER_STATION",
    "DECISIONAL_CLUSTER",
    "FEE_COEFFICIENT",
    "SUB_CENT_ASK_MAX",
    "TakeOutcome",
    "VariantSummary",
    "cluster_bootstrap_mean_ci",
    "score_take",
    "sub_cent_subset",
    "summarise",
    "take_fee",
]

#: The coefficient the screen itself ran with -- the measured 2026-09-17 wire
#: value, NOT the un-absorbed config pin. Copied, never chosen here.
FEE_COEFFICIENT: Final[float] = DEFAULT_FEE_COEFFICIENT

CLUSTER_DATE: Final[str] = "date"
CLUSTER_STATION: Final[str] = "station"
#: §2.2 of the registration: date is the single PRIMARY and DECISIONAL cluster.
DECISIONAL_CLUSTER: Final[str] = CLUSTER_DATE

BOOTSTRAP_ITERATIONS: Final[int] = 2000
BOOTSTRAP_SEED: Final[int] = 20260920
BOOTSTRAP_ALPHA: Final[float] = 0.05

#: The screen flagged 1-cent asks priced at 0.14-0.26 by the model. This is the
#: reporting cut for that subset -- a REPORT, never a filter on any take.
SUB_CENT_ASK_MAX: Final[float] = 0.02

SIDE_YES: Final[str] = "YES"
SIDE_NO: Final[str] = "NO"


def take_fee(price: float, *, fee_coefficient: float = FEE_COEFFICIENT) -> float:
    """The production per-contract fee at ``price``. Not restated here."""
    return venue_fee(ask_probability=price, fee_coefficient=fee_coefficient)


@dataclass(frozen=True, slots=True)
class TakeOutcome:
    """One take, scored against settlement truth."""

    station: str
    climate_day: dt.date
    variant_id: str
    side: str
    rung_id: str
    price: float
    fee: float
    claimed_margin: float
    settled_tmax_f: int
    won: bool
    realised_pnl: float

    def to_dict(self) -> dict[str, object]:
        """Explicit -- ``dataclasses.asdict`` is banned repo-wide."""
        return {
            "station": self.station,
            "climate_day": self.climate_day.isoformat(),
            "variant_id": self.variant_id,
            "side": self.side,
            "rung_id": self.rung_id,
            "price": self.price,
            "fee": self.fee,
            "claimed_margin": self.claimed_margin,
            "settled_tmax_f": self.settled_tmax_f,
            "won": self.won,
            "realised_pnl": self.realised_pnl,
        }


def score_take(
    *,
    station: str,
    climate_day: dt.date,
    variant_id: str,
    side: str,
    rung_id: str,
    price: float,
    claimed_margin: float,
    settled_tmax_f: int,
    fee_coefficient: float = FEE_COEFFICIENT,
) -> TakeOutcome:
    """Score ONE take on realised settlement.

    The rung is read through the repo's own venue-slug parser, whose interval
    is CLOSED on both ends (`Rung`: "``upper_f`` is INCLUSIVE: ``gte78lt79f``
    settles YES on 78 and on 79"). The NO leg is the exact complement of the
    YES leg on that same closed interval -- never a separately-derived bound.
    """
    if side not in (SIDE_YES, SIDE_NO):
        raise ValueError(f"side must be {SIDE_YES!r} or {SIDE_NO!r}, was {side!r}")
    rung = parse_rung(rung_id)
    in_rung = rung.contains(int(settled_tmax_f))
    won = in_rung if side == SIDE_YES else not in_rung
    fee = take_fee(price, fee_coefficient=fee_coefficient)
    return TakeOutcome(
        station=station,
        climate_day=climate_day,
        variant_id=variant_id,
        side=side,
        rung_id=rung_id,
        price=float(price),
        fee=fee,
        claimed_margin=float(claimed_margin),
        settled_tmax_f=int(settled_tmax_f),
        won=won,
        realised_pnl=(1.0 if won else 0.0) - float(price) - fee,
    )


@dataclass(frozen=True, slots=True)
class VariantSummary:
    n_takes: int
    n_wins: int
    win_rate: float | None
    mean_realised: float | None
    median_realised: float | None
    total_realised: float | None
    median_claimed_margin: float | None
    mean_claimed_margin: float | None

    def to_dict(self) -> dict[str, object]:
        return {
            "n_takes": self.n_takes,
            "n_wins": self.n_wins,
            "win_rate": self.win_rate,
            "mean_realised": self.mean_realised,
            "median_realised": self.median_realised,
            "total_realised": self.total_realised,
            "median_claimed_margin": self.median_claimed_margin,
            "mean_claimed_margin": self.mean_claimed_margin,
        }


def summarise(outcomes: Sequence[TakeOutcome] | Iterable[TakeOutcome]) -> VariantSummary:
    """Aggregate realised PnL. An empty set summarises to ``None``s, never raises."""
    outs = list(outcomes)
    if not outs:
        return VariantSummary(
            n_takes=0,
            n_wins=0,
            win_rate=None,
            mean_realised=None,
            median_realised=None,
            total_realised=None,
            median_claimed_margin=None,
            mean_claimed_margin=None,
        )
    realised = [o.realised_pnl for o in outs]
    claimed = [o.claimed_margin for o in outs]
    wins = sum(1 for o in outs if o.won)
    return VariantSummary(
        n_takes=len(outs),
        n_wins=wins,
        win_rate=wins / len(outs),
        mean_realised=statistics.fmean(realised),
        median_realised=statistics.median(realised),
        total_realised=math.fsum(realised),
        median_claimed_margin=statistics.median(claimed),
        mean_claimed_margin=statistics.fmean(claimed),
    )


def cluster_bootstrap_mean_ci(
    outcomes: Sequence[TakeOutcome] | Iterable[TakeOutcome], *, cluster: str
) -> tuple[float, float] | None:
    """Cluster block bootstrap 95% CI on the MEAN realised PnL per take.

    Same block-resample shape, iteration count and seed the registered screen
    uses for its margin CI (§2.2), so the two intervals are comparable; the
    statistic is the MEAN realised PnL rather than the median margin, because
    the money question is what the book earned per take, not where the middle
    take sat.
    """
    outs = list(outcomes)
    if not outs:
        return None
    blocks: dict[object, list[TakeOutcome]] = {}
    for outcome in outs:
        key = outcome.climate_day if cluster == CLUSTER_DATE else outcome.station
        blocks.setdefault(key, []).append(outcome)
    keys = sorted(blocks, key=repr)
    rng = random.Random(BOOTSTRAP_SEED)
    draws: list[float] = []
    for _ in range(BOOTSTRAP_ITERATIONS):
        drawn: list[float] = []
        for _ in range(len(keys)):
            drawn.extend(o.realised_pnl for o in blocks[keys[rng.randrange(len(keys))]])
        if drawn:
            draws.append(statistics.fmean(drawn))
    if not draws:
        return None
    draws.sort()
    lo = draws[max(0, math.floor((BOOTSTRAP_ALPHA / 2.0) * len(draws)))]
    hi = draws[min(len(draws) - 1, math.ceil((1.0 - BOOTSTRAP_ALPHA / 2.0) * len(draws)) - 1)]
    return (lo, hi)


def sub_cent_subset(
    outcomes: Sequence[TakeOutcome] | Iterable[TakeOutcome],
    *,
    max_price: float = SUB_CENT_ASK_MAX,
) -> list[TakeOutcome]:
    """Takes that lifted an ask AT OR BELOW ``max_price`` -- a REPORT slice."""
    return [o for o in outcomes if o.price <= max_price]


# ---------------------------------------------------------------------------
# Driver -- the screen's own corpus, streamed one station-day at a time
# ---------------------------------------------------------------------------

DEFAULT_OUTPUT: Final[Path] = Path(
    "docs/evidence/WP7_REALISED_PNL_FALSIFICATION_2026-09-20.md"
)


def _rss_mb() -> float:
    try:
        with open("/proc/self/status", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("VmHWM:"):
                    return float(line.split()[1]) / 1024.0
    except OSError:
        pass
    return float("nan")


def _load_corpus(wp7, tape_root: Path, corpus_json: Path):
    """Exactly the screen's own load: tape index, truth, frozen model, forecasts."""
    from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog
    from settlement_alignment_study import load_sites

    from breezy.persistence.catalog import read_climate_days, station_catalog_path

    notes: list[str] = []
    depth_root = tape_root / "data" / "order_book_depths"
    by_station_day: dict[tuple[str, dt.date], list[Path]] = {}
    for child in sorted(depth_root.iterdir()):
        if not child.is_dir():
            continue
        try:
            rung = parse_rung(child.name)
        except ValueError:
            continue
        if rung.city not in wp7.POOL_CITIES:
            continue
        by_station_day.setdefault((rung.city, rung.climate_day), []).append(child)

    sites = {spec.city: spec for spec in load_sites()}
    catalog_base = Path.home() / ".local/share/breezy/catalog"
    truth: dict[tuple[str, dt.date], int] = {}
    for city in wp7.POOL_CITIES:
        records = read_climate_days(
            ParquetDataCatalog(str(station_catalog_path(catalog_base, "polymarket_us", city)))
        )
        for record in records:
            if not (record.is_final and not record.is_superseded):
                continue
            if record.tmax_f is None:
                continue
            truth[(city, record.climate_day)] = int(record.tmax_f)

    from forecast_conditional_corpus import FIT_END_EXCLUSIVE, FIT_START, load_cached_corpus
    from forecast_conditional_model_study import fit_train_error_model

    rows = load_cached_corpus(corpus_json)
    train = [r for r in rows if FIT_START <= r.climate_day < FIT_END_EXCLUSIVE]
    error_model = fit_train_error_model(train)
    del rows
    notes.append(f"frozen 0b error model on {len(train)} TRAIN station-days (not re-fitted)")

    from forecast_conditional_corpus import (
        MosCoverageGapError,
        _archive_cache,
        read_mos_windows,
        resolve_mos_coverage,
    )

    price_days = sorted({day for _city, day in by_station_day})
    cache = _archive_cache("iem-mos")
    runtime_start = price_days[0] - dt.timedelta(days=1)
    runtime_end = price_days[-1] + dt.timedelta(days=1)
    forecasts: dict[tuple[str, dt.date], list[tuple[int, float]]] = {}
    for city in wp7.POOL_CITIES:
        icao = wp7.CITY_TO_ICAO[city]
        try:
            coverage = resolve_mos_coverage(
                cache,
                station=icao,
                start=runtime_start,
                end=runtime_end + dt.timedelta(days=1),
                model="NBS",
            )
        except MosCoverageGapError as gap:
            notes.append(
                f"FORECAST ARCHIVE GAP for {icao}: {len(gap.missing_days)} runtime day(s) "
                f"covered by no entry ({gap.missing_days[0].isoformat()}.."
                f"{gap.missing_days[-1].isoformat()})"
            )
            coverage = gap.coverage
        for body, owned_days in read_mos_windows(cache, coverage):
            cycles = wp7.forecast_cycles_from_mos_payload(
                body,
                icao=icao,
                std_utc_offset_hours=sites[city].std_utc_offset_hours,
                runtime_days=owned_days,
            )
            for day, entries in cycles.items():
                forecasts.setdefault((city, day), []).extend(entries)
            del body, cycles
        for entries in forecasts.values():
            entries.sort()
    return by_station_day, truth, error_model, forecasts, sites, notes


def collect_outcomes(
    wp7, *, tape_root: Path, corpus_json: Path
) -> tuple[dict[str, list[TakeOutcome]], dict[str, list[object]], list[str], int]:
    """Run all twelve registered variants and score every take on settlement."""
    by_station_day, truth, error_model, forecasts, sites, notes = _load_corpus(
        wp7, tape_root, corpus_json
    )
    price_scalar, size_scalar = wp7._fixed_scalars()
    outcomes: dict[str, list[TakeOutcome]] = {v.variant_id: [] for v in wp7.ALL_VARIANTS}
    trials: dict[str, list[object]] = {v.variant_id: [] for v in wp7.ALL_VARIANTS}
    scored_days = 0

    for (city, climate_day), dirs in sorted(by_station_day.items()):
        offset = sites[city].std_utc_offset_hours
        tapes: list[object] = []
        for child in dirs:
            rung = parse_rung(child.name)
            instants, _rows = wp7.read_rung_tape(
                child,
                std_utc_offset_hours=offset,
                price_scalar=price_scalar,
                size_scalar=size_scalar,
            )
            tapes.append(
                wp7.RungTape(
                    rung_id=child.name,
                    lower_f=rung.lower_f,
                    upper_f=rung.upper_f,
                    instants=tuple(instants),
                )
            )
            del instants
        p_yes = wp7._rung_probabilities(
            city=city,
            climate_day=climate_day,
            tapes=tapes,
            forecasts=forecasts,
            error_model=error_model,
            truth=truth,
        )
        if p_yes is None:
            del tapes
            continue
        scored_days += 1
        settled = truth[(city, climate_day)]
        for variant in wp7.ALL_VARIANTS:
            trial = wp7.screen_station_day(
                station=city,
                climate_day=climate_day,
                rungs=tapes,
                variant=variant,
                p_yes_by_rung=p_yes,
            )
            trials[variant.variant_id].append(trial)
            if not trial.took:
                continue
            outcomes[variant.variant_id].append(
                score_take(
                    station=city,
                    climate_day=climate_day,
                    variant_id=variant.variant_id,
                    side=trial.side,
                    rung_id=trial.rung,
                    price=trial.ask,
                    claimed_margin=trial.margin,
                    settled_tmax_f=settled,
                )
            )
        del tapes
    return outcomes, trials, notes, scored_days


def _fmt(value: float | None, digits: int = 4) -> str:
    return "--" if value is None else f"{value:+.{digits}f}"


def _ci(interval: tuple[float, float] | None) -> str:
    return "--" if interval is None else f"[{interval[0]:+.4f}, {interval[1]:+.4f}]"


def _render(wp7, outcomes, trials, notes, scored_days, peak_rss) -> str:
    lines = [
        "# WP-7 -- REALISED post-fee PnL on the screen's own takes (2026-09-20)",
        "",
        (
            "Falsification of the `0b PASS` computed by "
            "`scripts/analysis/forecast_cheap_screen_wp7.py` (`4209fe3`). The registered "
            "§3 bar scores `p_fc - (price + fee)` -- MODEL-CLAIMED edge -- and settlement "
            "truth enters it only as a join filter, so the screen never asks whether the "
            "forecast was RIGHT. This artefact scores the SAME takes, made by the SAME "
            "take rule, against the NWS CLI settled daily high."
        ),
        "",
        (
            "**In-sample by construction.** In-sample confirmation proves nothing; "
            "in-sample REFUTATION is decisive. A positive number below is reported as "
            "NOT REFUTED, never as a confirmation."
        ),
        "",
        "## What was reused verbatim",
        "",
        (
            "- take rule: `forecast_cheap_screen_wp7.screen_station_day`, all twelve "
            "registered variants, no filter added and no take dropped."
        ),
        (
            "- fee: `forecast_tape_screen.venue_fee` -> "
            "`current_rung_hold.decision.fee_on_ask`, banker's-rounded to the cent, "
            f"coefficient {FEE_COEFFICIENT}."
        ),
        (
            "- rung bounds: `h4_preliminary_economic_read.parse_rung` / `Rung.contains`, "
            "a CLOSED integer-°F interval. `gte86lt87f` settles YES on 86 AND on 87; the "
            "half-open reading leaves every odd degree in no rung at all."
        ),
        "- settlement truth: the NWS CLI finals the screen itself joins on.",
        "",
        f"- station-days scored (complete join): **{scored_days}**",
        f"- peak RSS: **{peak_rss:.0f} MB**",
        "",
    ]
    for note in notes:
        lines.append(f"- {note}")

    lines += [
        "",
        "## Realised PnL per take, all twelve variants (§1(iv): every variant, not just the nine)",
        "",
        (
            "| variant | screen verdict | takes | win rate | mean realised | median realised "
            "| total realised |"
        ),
        "|---|---|---|---|---|---|---|",
    ]
    summaries: dict[str, VariantSummary] = {}
    for variant in wp7.ALL_VARIANTS:
        vid = variant.variant_id
        outs = outcomes[vid]
        summary = summarise(outs)
        summaries[vid] = summary
        gate = wp7.evaluate_gate(wp7.PooledCell(variant_id=vid, trials=tuple(trials[vid])))
        wr = "--" if summary.win_rate is None else f"{summary.win_rate * 100:.1f}%"
        lines.append(
            f"| `{vid}` | {gate.verdict} | {summary.n_takes} | {wr} | "
            f"{_fmt(summary.mean_realised)} | {_fmt(summary.median_realised)} | "
            f"{_fmt(summary.total_realised, 2)} |"
        )

    lines += [
        "",
        "## Model-CLAIMED margin vs REALISED PnL -- the comparison that matters",
        "",
        "| variant | median claimed | median realised | gap | mean claimed | mean realised | gap |",
        "|---|---|---|---|---|---|---|",
    ]
    for variant in wp7.ALL_VARIANTS:
        s = summaries[variant.variant_id]
        if s.n_takes == 0:
            lines.append(f"| `{variant.variant_id}` | -- | -- | -- | -- | -- | -- |")
            continue
        med_gap = s.median_realised - s.median_claimed_margin
        mean_gap = s.mean_realised - s.mean_claimed_margin
        lines.append(
            f"| `{variant.variant_id}` | {_fmt(s.median_claimed_margin)} | "
            f"{_fmt(s.median_realised)} | {_fmt(med_gap)} | {_fmt(s.mean_claimed_margin)} | "
            f"{_fmt(s.mean_realised)} | {_fmt(mean_gap)} |"
        )

    lines += [
        "",
        "## 95% CI on MEAN realised PnL per take",
        "",
        (
            "Date is the single PRIMARY and DECISIONAL cluster (registration §2.2). The "
            "station-clustered interval is sensitivity only and is non-decisional -- with "
            "four stations it is a four-block resample and is reported for completeness."
        ),
        "",
        "| variant | CI (date, DECISIONAL) | CI (station, sensitivity only) |",
        "|---|---|---|",
    ]
    for variant in wp7.ALL_VARIANTS:
        outs = outcomes[variant.variant_id]
        lines.append(
            f"| `{variant.variant_id}` | "
            f"{_ci(cluster_bootstrap_mean_ci(outs, cluster=CLUSTER_DATE))} | "
            f"{_ci(cluster_bootstrap_mean_ci(outs, cluster=CLUSTER_STATION))} |"
        )

    lines += [
        "",
        "## By side -- the B2 variants (B1 is YES-only by construction)",
        "",
        "| variant | side | takes | win rate | mean realised | median claimed | total |",
        "|---|---|---|---|---|---|---|",
    ]
    for variant in wp7.ALL_VARIANTS:
        if SIDE_NO not in variant.sides:
            continue
        for side in (SIDE_YES, SIDE_NO):
            subset = [o for o in outcomes[variant.variant_id] if o.side == side]
            s = summarise(subset)
            wr = "--" if s.win_rate is None else f"{s.win_rate * 100:.1f}%"
            lines.append(
                f"| `{variant.variant_id}` | {side} | {s.n_takes} | {wr} | "
                f"{_fmt(s.mean_realised)} | {_fmt(s.median_claimed_margin)} | "
                f"{_fmt(s.total_realised, 2)} |"
            )

    lines += [
        "",
        f"## The sub-{SUB_CENT_ASK_MAX:.2f} ask subset -- where a model-error artefact would live",
        "",
        (
            "The screen flagged 1-cent asks that the model priced at 0.14-0.26. If that is "
            "a model error rather than an edge, this is the subset where it shows."
        ),
        "",
        "| variant | takes <= 0.02 | win rate | median claimed | mean realised | total |",
        "|---|---|---|---|---|---|",
    ]
    all_cheap: list[TakeOutcome] = []
    for variant in wp7.ALL_VARIANTS:
        cheap = sub_cent_subset(outcomes[variant.variant_id])
        all_cheap.extend(cheap)
        s = summarise(cheap)
        wr = "--" if s.win_rate is None else f"{s.win_rate * 100:.1f}%"
        lines.append(
            f"| `{variant.variant_id}` | {s.n_takes} | {wr} | "
            f"{_fmt(s.median_claimed_margin)} | {_fmt(s.mean_realised)} | "
            f"{_fmt(s.total_realised, 2)} |"
        )
    pooled_cheap = summarise(all_cheap)
    lines += [
        "",
        (
            f"Pooled across all twelve variants (takes are NOT independent across "
            f"variants -- the same station-day recurs): n = {pooled_cheap.n_takes}, "
            f"win rate "
            + ("--" if pooled_cheap.win_rate is None else f"{pooled_cheap.win_rate * 100:.1f}%")
            + f", median claimed {_fmt(pooled_cheap.median_claimed_margin)}, "
            f"mean realised {_fmt(pooled_cheap.mean_realised)}."
        ),
        "",
    ]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="WP-7 realised-PnL falsification")
    parser.add_argument(
        "--tape",
        type=Path,
        default=Path.home() / ".local/share/breezy/catalog/quote_tape/polymarket_us",
    )
    parser.add_argument(
        "--corpus-json",
        type=Path,
        default=Path.home() / ".local/share/breezy/derived/forecast_conditional_corpus_wp6.json",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)

    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "forecast_cheap_screen_wp7", _SCRIPTS_ANALYSIS_DIR / "forecast_cheap_screen_wp7.py"
    )
    assert spec is not None and spec.loader is not None
    wp7 = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = wp7
    spec.loader.exec_module(wp7)

    outcomes, trials, notes, scored_days = collect_outcomes(
        wp7, tape_root=args.tape, corpus_json=args.corpus_json
    )
    artefact = _render(wp7, outcomes, trials, notes, scored_days, _rss_mb())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(artefact, encoding="utf-8")
    print(artefact)
    print(f"[falsification] peak RSS {_rss_mb():.0f} MB", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
