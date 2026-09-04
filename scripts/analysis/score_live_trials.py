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

Re-score-only-on-change (review item 3): before re-scoring a trial against a
resolved `nws_final` record, `_unchanged_since_last_score` compares that
record's `(raw_sha256, revision_seq)` against the latest stored row for the
same `trial_id`; an unchanged pair means the prior run already scored this
exact settlement value, so the trial is skipped and no duplicate row is
appended. A corrected record (different `raw_sha256`/`revision_seq`)
re-scores and appends `score_seq + 1`, same as today.

Malformed input (review item 2): a malformed JSONL row (invalid JSON, a
missing/mistyped field, an unparseable Decimal, a `climate_day` that is not a
real ISO date) never aborts the batch. It is converted to a
`ScoreRefusal(reason="malformed_input")` for that one row/trial and scoring
continues with the rest. `FilledTrial.climate_day` itself stays a plain `str`
(the settlement-package purity guard forbids `datetime` under
`breezy.settlement`); this script is the boundary that validates it really is
an ISO date before the value is ever used to look up a settlement record.

JSONL input schema (review item 7): one `FilledTrial`-shaped JSON object per
line --

    trial_id: str
    station: str                       # e.g. "LAX"
    climate_day: str                   # ISO-8601 date, e.g. "2026-08-31"
    instrument_id: str
    fill_px: str                       # Decimal, e.g. "0.42"
    fee: str                           # Decimal, per-contract entry fee
    qty: str                           # Decimal
    filled_at_ns: int
    entry_ask: str                     # Decimal, decision-time ask
    scheduled_release_at_ns: int
    venue_settlement_tmax_f: int | null   # optional, venue fallback only
    bucket: {                          # optional; omit to resolve via the
        "station": str,                # persisted instrument definition
        "climate_day": str,
        "lower_f": int | null,
        "upper_f": int | null,
    } | null

Example line::

    {"trial_id": "t1", "station": "LAX", "climate_day": "2026-08-31", \
"instrument_id": "LAX-2026-08-31-gte78lt80f", "fill_px": "0.42", "fee": \
"0.01", "qty": "10", "filled_at_ns": 1, "entry_ask": "0.40", \
"scheduled_release_at_ns": 1, "venue_settlement_tmax_f": null, "bucket": null}
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import sys
import time
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
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


#: Exceptions a malformed JSONL row or a malformed `FilledTrial` field can
#: raise while being parsed -- review item 2's per-row guard.
_MALFORMED_ROW_ERRORS: tuple[type[Exception], ...] = (
    KeyError,
    ValueError,
    TypeError,
    InvalidOperation,
)


def read_filled_trials_jsonl(
    path: Path,
) -> tuple[tuple[FilledTrial, ...], tuple[ScoreRefusal, ...]]:
    """Read `FilledTrial` records from a JSONL placeholder fill source.

    See the module docstring: this is an explicit stand-in until a real
    `OrderFilled` -> `FilledTrial` adapter lands (R-7/R-8), not the adapter
    itself. A malformed line never aborts the read (review item 2): it is
    converted to a `ScoreRefusal(reason="malformed_input")` and the remaining
    lines are still read.
    """
    trials: list[FilledTrial] = []
    refusals: list[ScoreRefusal] = []
    for line_no, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            refusals.append(
                ScoreRefusal(
                    trial_id=f"<malformed line {line_no}>",
                    reason="malformed_input",
                    detail=f"invalid JSON on line {line_no}: {exc}",
                )
            )
            continue
        try:
            trials.append(_filled_trial_from_json(row))
        except _MALFORMED_ROW_ERRORS as exc:
            trial_id = row.get("trial_id") if isinstance(row, Mapping) else None
            fallback_id = f"<malformed line {line_no}>"
            refusals.append(
                ScoreRefusal(
                    trial_id=str(trial_id) if trial_id is not None else fallback_id,
                    reason="malformed_input",
                    detail=f"malformed FilledTrial on line {line_no}: {exc}",
                )
            )
    return tuple(trials), tuple(refusals)


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

    Duplicate `instrument_id` (review item 4, mirroring `252918a`'s ingest
    idiom): the FIRST-landed definition stands. A later definition under the
    same id that diverges in content is counted, never silently taken as the
    winner, and the count is logged once as a single warning.
    """
    catalog = open_station_catalog(catalog_base, venue, city)
    facts: dict[str, WeatherBucketFacts] = {}
    divergent = 0
    for instrument in catalog.instruments():
        try:
            resolved = read_weather_bucket_facts(instrument.info)
        except Exception as exc:  # noqa: BLE001 -- a non-weather instrument is skipped, not fatal
            logging.getLogger(__name__).debug(
                "skipping non-weather instrument %s: %s", instrument.id, exc
            )
            continue
        instrument_id = str(instrument.id)
        existing = facts.get(instrument_id)
        if existing is not None:
            if existing != resolved:
                divergent += 1
            continue
        facts[instrument_id] = resolved
    if divergent:
        logging.getLogger(__name__).warning(
            "%d instrument definition(s) share an already-landed instrument_id "
            "but differ in weather-bucket facts; skipped, the first-landed "
            "definition stands",
            divergent,
        )
    return facts


def _latest_stored_row(derived_dir: Path, trial_id: str) -> ScoredTrial | None:
    """The highest-`score_seq` stored row for `trial_id`, or `None` if none
    has ever been scored."""
    latest: ScoredTrial | None = None
    for row in read_scored_trials(derived_dir):
        if row.trial_id == trial_id and (latest is None or row.score_seq > latest.score_seq):
            latest = row
    return latest


def _already_fallback_scored(derived_dir: Path, trial_id: str) -> bool:
    latest = _latest_stored_row(derived_dir, trial_id)
    return latest is not None and latest.settlement_basis == "venue_last_fair_price_fallback"


def _next_score_seq(derived_dir: Path, trial_id: str) -> int:
    latest = _latest_stored_row(derived_dir, trial_id)
    return 0 if latest is None else latest.score_seq + 1


def _unchanged_since_last_score(
    derived_dir: Path, trial_id: str, record: NwsClimateDay | None
) -> bool:
    """Review item 3: skip re-scoring an `nws_final` row when the resolved
    record's `(raw_sha256, revision_seq)` matches the latest stored row for
    `trial_id`. A `None` record, or a latest row that is not itself
    `nws_final`, is never "unchanged" -- only a genuine repeat of the same
    settlement value is."""
    if record is None:
        return False
    latest = _latest_stored_row(derived_dir, trial_id)
    if latest is None or latest.settlement_basis != "nws_final":
        return False
    return latest.raw_sha256 == record.raw_sha256 and latest.revision_seq == record.revision_seq


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
    filled_trials, jsonl_refusals = read_filled_trials_jsonl(fills_path)
    bucket_by_instrument = _read_bucket_facts_by_instrument_id(catalog_base, venue=venue, city=city)
    catalog = open_station_catalog(catalog_base, venue, city)

    pairs: list[tuple[FilledTrial, NwsClimateDay | None]] = []
    extra_refusals: list[ScoreRefusal] = list(jsonl_refusals)
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
        try:
            climate_day = dt.date.fromisoformat(trial.climate_day)
        except ValueError as exc:
            extra_refusals.append(
                ScoreRefusal(
                    trial_id=trial.trial_id,
                    reason="malformed_input",
                    detail=f"climate_day {trial.climate_day!r} is not a valid ISO date: {exc}",
                )
            )
            continue
        record = read_climate_day_including_corrections(
            catalog, station=trial.station, climate_day=climate_day
        )
        if _unchanged_since_last_score(derived_dir, trial.trial_id, record):
            continue
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
