"""6c driver: score filled trials against settlement truth, write parquet.

`docs/plans/SCORER_TALLY_BCA_BRIEF_2026-09-04.md` section 6c. Thin glue only
-- all scoring logic lives in `breezy.settlement.trial_scorer` (pure); this
module's only job is I/O: read fills, resolve each fill's rung and
settlement record, score, write.

FILL SOURCE DECISION (stated per the task, since neither the trial latch nor
a live exec client exists yet -- see `trial_scorer.py`'s module docstring):
this driver reads `FilledTrial` inputs from a JSONL file, one object per
line, with exactly `FilledTrial`'s fields (`climate_day` as an ISO date
string, Decimal fields as strings). This is a narrow, explicit placeholder
input reader -- NOT the `OrderFilled` -> `FilledTrial` adapter (that lands
with R-7/R-8) -- and is expected to be replaced wholesale once a real fill
source exists; nothing downstream of `read_filled_trials_jsonl` depends on
its shape.

Instrument lookup (review item 7): `_read_bucket_facts_by_instrument_id`
reads every instrument definition from the station's catalog via the native,
UNFILTERED `catalog.instruments()` -- per `252918a`'s pinned layout note, a
BinaryOption identifier-filtered query does not see the flat files the
native per-file converter wrote, so this driver never filters by identifier.

Re-score discipline (review item 1): once a trial's LATEST stored row
carries `settlement_basis="venue_last_fair_price_fallback"`, this driver
must not re-score that trial against a later-arriving FINAL -- `_due_for_scoring`
enforces that by skipping any trial whose latest stored score is already a
fallback score.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import sys
import time
from collections.abc import Mapping, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any

from breezy.domain.nws_climate_day import NwsClimateDay
from breezy.domain.weather_bucket_facts import (
    Measure,
    WeatherBucketFacts,
    read_weather_bucket_facts,
)
from breezy.persistence.catalog import open_station_catalog, read_climate_day_including_corrections
from breezy.persistence.scored_trial_store import read_scored_trials, write_scored_trials
from breezy.settlement.trial_scorer import (
    FilledTrial,
    ScoredTrial,
    ScoreRefusal,
    score_trials,
)

DEFAULT_NWS_CATALOG_BASE: Path = Path.home() / ".local/share/breezy/catalog"
DEFAULT_DERIVED_DIR: Path = Path.home() / ".local/share/breezy/derived/scored_trials"


def read_filled_trials_jsonl(path: Path) -> tuple[FilledTrial, ...]:
    """Read `FilledTrial` records from a JSONL placeholder fill source.

    See the module docstring: this is an explicit stand-in until a real
    `OrderFilled` -> `FilledTrial` adapter lands (R-7/R-8), not the adapter
    itself.
    """
    trials: list[FilledTrial] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        trials.append(_filled_trial_from_json(json.loads(line)))
    return tuple(trials)


def _filled_trial_from_json(row: Mapping[str, Any]) -> FilledTrial:
    bucket: WeatherBucketFacts | None = None
    if row.get("bucket") is not None:
        b = row["bucket"]
        bucket = WeatherBucketFacts(
            settlement_station=row["station"],
            climate_day=dt.date.fromisoformat(row["climate_day"]),
            measure=Measure.HIGH,
            lower_f=b.get("lower_f"),
            upper_f=b.get("upper_f"),
        )
    return FilledTrial(
        trial_id=row["trial_id"],
        station=row["station"],
        climate_day=row["climate_day"],
        instrument_id=row["instrument_id"],
        bucket=bucket,
        fill_px=Decimal(row["fill_px"]),
        fee=Decimal(row["fee"]),
        qty=Decimal(row["qty"]),
        filled_at_ns=int(row["filled_at_ns"]),
        entry_ask=Decimal(row["entry_ask"]),
        scheduled_release_at_ns=int(row["scheduled_release_at_ns"]),
        venue_settlement_tmax_f=row.get("venue_settlement_tmax_f"),
    )


def _read_bucket_facts_by_instrument_id(
    catalog_base: Path, *, venue: str, city: str
) -> dict[str, WeatherBucketFacts]:
    """Resolve every persisted instrument definition's rung facts, keyed by id.

    Absence for a given `instrument_id` is the caller's `instrument_unavailable`
    refusal signal (item 7) -- this function returns only what it found.
    """
    catalog = open_station_catalog(catalog_base, venue, city)
    facts: dict[str, WeatherBucketFacts] = {}
    for instrument in catalog.instruments():
        try:
            facts[str(instrument.id)] = read_weather_bucket_facts(instrument.info)
        except Exception as exc:  # noqa: BLE001 -- a non-weather instrument is skipped, not fatal
            logging.getLogger(__name__).debug(
                "skipping non-weather instrument %s: %s", instrument.id, exc
            )
    return facts


def _already_fallback_scored(derived_dir: Path, trial_id: str) -> bool:
    for row in read_scored_trials(derived_dir):
        if row.trial_id == trial_id:
            return row.settlement_basis == "venue_last_fair_price_fallback"
    return False


def _next_score_seq(derived_dir: Path, trial_id: str) -> int:
    for row in read_scored_trials(derived_dir):
        if row.trial_id == trial_id:
            return row.score_seq + 1
    return 0


def score_live_trials(
    *,
    fills_path: Path,
    catalog_base: Path,
    venue: str,
    city: str,
    derived_dir: Path,
    now_ns: int,
) -> tuple[tuple[ScoredTrial, ...], tuple[ScoreRefusal, ...]]:
    """Read fills, join to settlement truth, score, and write the parquet run."""
    filled_trials = read_filled_trials_jsonl(fills_path)
    bucket_by_instrument = _read_bucket_facts_by_instrument_id(catalog_base, venue=venue, city=city)
    catalog = open_station_catalog(catalog_base, venue, city)

    pairs: list[tuple[FilledTrial, NwsClimateDay | None]] = []
    extra_refusals: list[ScoreRefusal] = []
    for trial in filled_trials:
        if _already_fallback_scored(derived_dir, trial.trial_id):
            continue
        if trial.bucket is None and trial.instrument_id not in bucket_by_instrument:
            extra_refusals.append(
                ScoreRefusal(
                    trial_id=trial.trial_id,
                    reason="instrument_unavailable",
                    detail=f"no persisted instrument definition for {trial.instrument_id!r}",
                )
            )
            continue
        resolved_trial = trial
        if trial.bucket is None:
            resolved_trial = FilledTrial(
                trial_id=trial.trial_id,
                station=trial.station,
                climate_day=trial.climate_day,
                instrument_id=trial.instrument_id,
                bucket=bucket_by_instrument[trial.instrument_id],
                fill_px=trial.fill_px,
                fee=trial.fee,
                qty=trial.qty,
                filled_at_ns=trial.filled_at_ns,
                entry_ask=trial.entry_ask,
                scheduled_release_at_ns=trial.scheduled_release_at_ns,
                venue_settlement_tmax_f=trial.venue_settlement_tmax_f,
            )
        record = read_climate_day_including_corrections(
            catalog, station=trial.station, climate_day=dt.date.fromisoformat(trial.climate_day)
        )
        pairs.append((resolved_trial, record))

    scored, refused = score_trials(pairs, now_ns=now_ns)
    refused = refused + tuple(extra_refusals)

    stamped_scored = tuple(
        ScoredTrial(
            trial_id=row.trial_id,
            station=row.station,
            climate_day=row.climate_day,
            instrument_id=row.instrument_id,
            settlement_tmax_f=row.settlement_tmax_f,
            held=row.held,
            pnl=row.pnl,
            revision_seq=row.revision_seq,
            raw_sha256=row.raw_sha256,
            scored_at_ns=row.scored_at_ns,
            score_seq=_next_score_seq(derived_dir, row.trial_id),
            settlement_basis=row.settlement_basis,
            excluded_reason=row.excluded_reason,
            slippage=row.slippage,
            entry_ask=row.entry_ask,
            fill_px=row.fill_px,
            fee=row.fee,
        )
        for row in scored
    )
    if stamped_scored:
        write_scored_trials(derived_dir, stamped_scored, now_ns=now_ns)
    return stamped_scored, refused


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fills", type=Path, required=True, help="JSONL FilledTrial input path")
    parser.add_argument("--venue", type=str, default="polymarket_us")
    parser.add_argument("--city", type=str, required=True)
    parser.add_argument("--catalog-base", type=Path, default=DEFAULT_NWS_CATALOG_BASE)
    parser.add_argument("--derived-dir", type=Path, default=DEFAULT_DERIVED_DIR)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    scored, refused = score_live_trials(
        fills_path=args.fills,
        catalog_base=args.catalog_base,
        venue=args.venue,
        city=args.city,
        derived_dir=args.derived_dir,
        now_ns=time.time_ns(),
    )
    print(f"scored {len(scored)} trial(s), refused {len(refused)} trial(s)")
    for refusal in refused:
        print(f"  refused {refusal.trial_id}: {refusal.reason} -- {refusal.detail}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
