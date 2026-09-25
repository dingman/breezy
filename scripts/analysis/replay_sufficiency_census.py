#!/usr/bin/env python3
"""AUD-09a: the replay-sufficiency census.

Disk-only, per `(station, climate_day)`, machine-readable, versioned census
of which station-days can be replayed at all -- see
`docs/plans/backlog/AUDIT_2026-09-21/AUD-09-scheduled-per-station-replay.md`
§6a. Cheap: it never runs an engine, never fetches over the network, and
never touches the live path.

This module is the impure I/O wrapper around the pure core in
`breezy.analysis.replay_sufficiency`. It reuses, without modification:

- `breezy.persistence.feather_preflight.list_instance_ids` / `scan_instance`;
- `cli_basis_offer_gate_scan.classify_instance` and
  `station_days_only_on_corrupt_tape`;
- `current_rung_hold_paper_replay._convert_live_capture` /
  `_select_capture_instruments` and `whole_tape_paper_replay._corrupt_instance_station_days`
  for the same feather-to-work-catalog conversion and corrupt-tape identity
  read the whole-tape driver already performs, so this script derives no new
  reading of the raw capture format;
- `breezy.strategy.current_rung_hold.strategy._local_hour` for the same LST
  decision-window hour derivation `assert_decision_window_has_coverage`
  (`current_rung_hold_paper_replay.py:257`) uses, so the census's coverage
  decision cannot silently diverge from the strategy's own.

**H1 (AUD-08b -> AUD-09a)** is read via AUD-08b's own
`breezy.persistence.station_candidates.read_station_candidates` (merged).
`_read_station_candidates` below is a thin wrapper: it prints the plan's
mandated WARN when the register file is absent (§6a: "a missing register is
a WARN and an empty candidate set, never a census failure"), then delegates
to the real reader, which itself returns `()` for a missing file and raises
`UnknownStationCandidateSchemaError`/`StationCandidateRegisterCorruptError`
on a corrupt or unversioned register -- never swallowed here.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
import tempfile
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cli_basis_offer_gate_scan import (
    classify_instance,
    station_days_only_on_corrupt_tape,
)
from current_rung_hold_paper_replay import (  # type: ignore[attr-defined]
    _convert_live_capture,
    _select_capture_instruments,
)
from run_weather_strategy_backtests import WEATHER_VENUE, TapeInstrument
from whole_tape_paper_replay import _corrupt_instance_station_days

from breezy.analysis.replay_sufficiency import (
    CANDIDATE_UNSUPPORTED_STATION,
    REPLAY_SUFFICIENCY_SCHEMA_VERSION,
    InstanceSpan,
    ReplaySufficiency,
    classify_station_day,
    write_replay_sufficiency,
)
from breezy.domain.weather_bucket_facts import (
    WeatherFactsUnavailableError,
    read_weather_bucket_facts,
)
from breezy.persistence.feather_preflight import (
    DEFAULT_SUBDIRECTORY,
    PreflightError,
    list_instance_ids,
    scan_instance,
)
from breezy.persistence.station_candidates import StationCandidate, read_station_candidates
from breezy.registry import SiteNotFoundError, default_registry
from breezy.strategy.current_rung_hold.strategy import _local_hour
from breezy.strategy.depth10 import best_order

__all__ = [
    "CensusCompletenessError",
    "_assert_census_is_complete",
    "_candidate_rows_to_replay_sufficiency",
    "_read_station_candidates",
    "build_census",
    "main",
    "run_census",
]

#: The same LST decision window `assert_decision_window_has_coverage`'s
#: `source="depth"` branch checks (`current_rung_hold_paper_replay.py:128-129`),
#: imported nowhere as a constant (that module keeps it private) but
#: numerically identical and re-derived here via the SAME `_local_hour`
#: function, never a re-implementation of the hour arithmetic.
_WINDOW_START_HOUR_LST: Final[int] = 12
_WINDOW_END_HOUR_LST: Final[int] = 17  # exclusive

DEFAULT_QUOTE_TAPE_CATALOG: Final[Path] = (
    Path.home() / ".local/share/breezy/catalog/quote_tape/polymarket_us"
)
DEFAULT_OUTPUT_PATH: Final[Path] = (
    Path.home() / ".local/share/breezy/derived/replay/replay_sufficiency.jsonl"
)
DEFAULT_STATION_CANDIDATES_PATH: Final[Path] = (
    Path.home() / ".local/share/breezy/derived/station_candidates/station_candidates.jsonl"
)


def _read_station_candidates(path: Path) -> tuple[StationCandidate, ...]:
    """H1: a missing register WARNs and yields an empty candidate set.

    Never a census failure. The WARN is printed here (the plan's own H1
    text); the actual read -- including the missing-file empty return and
    the unknown-schema / corrupt-register refusals -- is AUD-08b's real
    `breezy.persistence.station_candidates.read_station_candidates`, never
    swallowed.
    """
    if not path.is_file():
        print(
            f"replay-sufficiency-census: WARN -- no station candidate register at {path}; "
            "treating as an empty candidate set (AUD-08b not yet merged or not yet run)",
            file=sys.stderr,
        )
    return read_station_candidates(path)


def _candidate_rows_to_replay_sufficiency(
    candidates: Sequence[StationCandidate], *, computed_day: str,
) -> tuple[ReplaySufficiency, ...]:
    """H1: one row per candidate, `CANDIDATE_UNSUPPORTED_STATION`, never queued.

    `winner_instance_id` is always `None`: no station outside
    `SUPPORTED_STATIONS` can ever be selected for replay (plan §6a).
    """
    registry = default_registry()
    rows: list[ReplaySufficiency] = []
    for candidate in candidates:
        try:
            station = registry.site_for_venue_city_token(candidate.venue, candidate.city_token).city
        except SiteNotFoundError:
            station = candidate.city_token.upper()
            print(
                f"replay-sufficiency-census: WARN -- ({candidate.venue}, "
                f"{candidate.city_token}) is not yet in the registry; using the raw "
                "token as a best-effort station label",
                file=sys.stderr,
            )
        rows.append(
            ReplaySufficiency(
                schema_version=REPLAY_SUFFICIENCY_SCHEMA_VERSION,
                station=station,
                climate_day=candidate.last_seen_day,
                verdict="INSUFFICIENT",
                reason=CANDIDATE_UNSUPPORTED_STATION,
                winner_instance_id=None,
                depth_window_minutes=0.0,
                quote_window_minutes=0.0,
                distinct_instruments=0,
                computed_day=computed_day,
            )
        )
    return tuple(rows)


def build_census(
    *,
    station_day_spans: Mapping[tuple[str, str], Sequence[InstanceSpan]],
    candidate_rows: Sequence[ReplaySufficiency] = (),
    computed_day: str,
) -> tuple[ReplaySufficiency, ...]:
    """Pure aggregation: one `classify_station_day` call per tape-derived key,
    plus every H1 candidate row, sorted for determinism."""
    rows = [
        classify_station_day(
            station=station,
            climate_day=climate_day,
            instances=instances,
            computed_day=computed_day,
        )
        for (station, climate_day), instances in station_day_spans.items()
    ]
    rows.extend(candidate_rows)
    return tuple(sorted(rows, key=lambda row: (row.station, row.climate_day)))


class CensusCompletenessError(Exception):
    """The written tape rows do not cover every station-day discovered in the
    raw instance metadata.

    B1 requires a row for every `(station, climate_day)` the tape contains;
    a silently-missing row is worse than a wrong reason, so a mismatch here
    is a loud failure, never a partial write.
    """


def _assert_census_is_complete(
    *, discovered: set[tuple[str, str]], written: set[tuple[str, str]],
) -> None:
    missing = discovered - written
    extra = written - discovered
    if missing or extra:
        raise CensusCompletenessError(
            f"census completeness check failed: {len(missing)} station-day(s) discovered in "
            f"raw instance metadata but not written ({sorted(missing)}); {len(extra)} written "
            f"but not discovered ({sorted(extra)})"
        )


def _in_decision_window(ts_event_ns: int, std_utc_offset_hours: float) -> bool:
    hour = _local_hour(ts_event_ns, std_utc_offset_hours)
    return _WINDOW_START_HOUR_LST <= hour < _WINDOW_END_HOUR_LST


def _window_span_minutes(ts_event_ns_values: Sequence[int]) -> float:
    """Span between the first and last in-window instant, in minutes.

    Zero for 0 or 1 instants -- a single snapshot covers no SPAN, the same
    rule `ma_prelock_winner_ask_study.afternoon_coverage_minutes` applies.
    """
    if len(ts_event_ns_values) < 2:
        return 0.0
    return (max(ts_event_ns_values) - min(ts_event_ns_values)) / 1_000_000_000.0 / 60.0


def _discover_clean_spans(
    *, catalog_root: Path, subdirectory: str, clean_ids: Sequence[str], work_root: Path,
) -> tuple[dict[tuple[str, str], list[InstanceSpan]], set[tuple[str, str]]]:
    """Real catalog conversion + per-station-day depth/quote span computation.

    Not directly unit-tested (see the test module's docstring): this is the
    same conversion `whole_tape_paper_replay._load_clean_instance` performs,
    reused rather than re-derived, and validated by the plan's real run
    against production data.
    """
    registry = default_registry()
    spans: dict[tuple[str, str], list[InstanceSpan]] = defaultdict(list)
    clean_station_days: set[tuple[str, str]] = set()
    for instance_id in clean_ids:
        work_catalog = work_root / f"{instance_id}"
        catalog = _convert_live_capture(
            quote_catalog=catalog_root,
            instance_id=instance_id,
            subdirectory=subdirectory,
            work_catalog=work_catalog,
        )
        climate_days: dict[dt.date, None] = {}
        for instrument in catalog.instruments():
            try:
                facts = read_weather_bucket_facts(instrument.info)
            except WeatherFactsUnavailableError:
                continue
            climate_days.setdefault(facts.climate_day, None)

        by_station_day: dict[tuple[str, str], list[TapeInstrument]] = defaultdict(list)
        for climate_day in climate_days:
            for tape_instrument in _select_capture_instruments(catalog, climate_day=climate_day):
                key = (tape_instrument.facts.settlement_station, climate_day.isoformat())
                by_station_day[key].append(tape_instrument)

        for (station, day), tape_instruments in by_station_day.items():
            std_offset = registry.climate_day_window(WEATHER_VENUE, station).std_utc_offset_hours
            depth_ts = [
                depth.ts_event
                for tape_instrument in tape_instruments
                for depth in tape_instrument.depths
                if _in_decision_window(depth.ts_event, std_offset)
                and best_order(depth.asks) is not None
            ]
            quote_ts = [
                quote.ts_event
                for tape_instrument in tape_instruments
                for quote in tape_instrument.quotes
                if _in_decision_window(quote.ts_event, std_offset)
            ]
            spans[(station, day)].append(
                InstanceSpan(
                    instance_id=instance_id,
                    verdict="CLEAN",
                    depth_window_minutes=_window_span_minutes(depth_ts),
                    quote_window_minutes=_window_span_minutes(quote_ts),
                    distinct_instruments=len(tape_instruments),
                )
            )
            clean_station_days.add((station, day))
    return dict(spans), clean_station_days


def run_census(
    *,
    catalog_root: Path,
    subdirectory: str,
    work_root: Path,
    station_candidates_path: Path,
    computed_day: str,
    now_ns: int,
) -> tuple[ReplaySufficiency, ...]:
    """The real, end-to-end census over one feather capture root."""
    try:
        instance_ids = list_instance_ids(catalog_root, subdirectory)
    except PreflightError:
        instance_ids = ()

    clean_ids: list[str] = []
    corrupt_ids: list[str] = []
    live_or_empty_ids: list[str] = []
    for instance_id in instance_ids:
        report = scan_instance(catalog_root, instance_id, subdirectory)
        verdict = classify_instance(report, now_ns=now_ns)
        if verdict == "CLEAN":
            clean_ids.append(instance_id)
        elif verdict == "CORRUPT":
            corrupt_ids.append(instance_id)
        else:
            # LIVE (writer may still be appending) or EMPTY (zero rows
            # anywhere). Neither is ever a winner, but B1 requires a row for
            # every (station, climate_day) the tape contains -- silently
            # dropping a LIVE-only day's identity was the completeness bug.
            live_or_empty_ids.append(instance_id)

    spans, clean_station_days = _discover_clean_spans(
        catalog_root=catalog_root,
        subdirectory=subdirectory,
        clean_ids=clean_ids,
        work_root=work_root,
    )
    corrupt_station_days_native = _corrupt_instance_station_days(
        quote_catalog=catalog_root, subdirectory=subdirectory, corrupt_ids=corrupt_ids,
    )
    clean_station_days_native = {
        (station, dt.date.fromisoformat(day)) for station, day in clean_station_days
    }
    corrupt_only = station_days_only_on_corrupt_tape(
        corrupt_station_days=corrupt_station_days_native,
        clean_station_days=clean_station_days_native,
    )
    for station, corrupt_day in corrupt_only:
        day = corrupt_day.isoformat()
        spans.setdefault((station, day), []).append(
            InstanceSpan(
                instance_id="<corrupt-only>",
                verdict="CORRUPT",
                depth_window_minutes=0.0,
                quote_window_minutes=0.0,
                distinct_instruments=0,
            )
        )

    # Identity-only read for LIVE/EMPTY instances -- the SAME mechanism
    # `_corrupt_instance_station_days` performs for CORRUPT instances (it
    # reads only the `binary_option` registration rows, never the
    # depth/quote streams a still-appending or empty tape cannot be trusted
    # for). EMPTY structurally contributes nothing here: `captured_nothing`
    # means zero rows in EVERY file, including `binary_option`, so it can
    # never yield a registration; every entry below is therefore from a
    # LIVE instance.
    live_or_empty_station_days_native = _corrupt_instance_station_days(
        quote_catalog=catalog_root, subdirectory=subdirectory, corrupt_ids=live_or_empty_ids,
    )
    for station, live_day in live_or_empty_station_days_native:
        day = live_day.isoformat()
        spans.setdefault((station, day), []).append(
            InstanceSpan(
                instance_id="<live-or-empty>",
                verdict="LIVE",
                depth_window_minutes=0.0,
                quote_window_minutes=0.0,
                distinct_instruments=0,
            )
        )

    discovered_station_days = {
        (station, day.isoformat()) for station, day in corrupt_station_days_native
    } | clean_station_days | {
        (station, day.isoformat()) for station, day in live_or_empty_station_days_native
    }
    tape_rows = build_census(station_day_spans=spans, computed_day=computed_day)
    _assert_census_is_complete(
        discovered=discovered_station_days,
        written={(row.station, row.climate_day) for row in tape_rows},
    )

    candidates = _read_station_candidates(station_candidates_path)
    candidate_rows = _candidate_rows_to_replay_sufficiency(candidates, computed_day=computed_day)

    return build_census(
        station_day_spans=spans, candidate_rows=candidate_rows, computed_day=computed_day
    )


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog-root", default=str(DEFAULT_QUOTE_TAPE_CATALOG))
    parser.add_argument("--subdirectory", default=DEFAULT_SUBDIRECTORY)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_PATH))
    parser.add_argument("--station-candidates", default=str(DEFAULT_STATION_CANDIDATES_PATH))
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    now = dt.datetime.now(dt.UTC)
    now_ns = int(now.timestamp() * 1_000_000_000)
    computed_day = now.date().isoformat()

    with tempfile.TemporaryDirectory(prefix="replay-sufficiency-census-") as tmp:
        rows = run_census(
            catalog_root=Path(args.catalog_root).expanduser(),
            subdirectory=args.subdirectory,
            work_root=Path(tmp),
            station_candidates_path=Path(args.station_candidates).expanduser(),
            computed_day=computed_day,
            now_ns=now_ns,
        )

    write_replay_sufficiency(Path(args.output).expanduser(), rows)

    by_reason = Counter(row.reason or "SUFFICIENT" for row in rows)
    print(
        f"replay-sufficiency-census: {len(rows)} station-day(s) classified: "
        f"{dict(sorted(by_reason.items()))}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
