"""Whole-tape current-rung-hold PAPER replay wrapper.

Classifies live quote-tape instances, selects one CLEAN winner per
``(station, climate_day)`` by the first in-window ``QuoteTick``, and replays
only the ``nws_integer_c`` precision arm at the live lags. Reports are mechanism
evidence only and stay under ``derived/paper_replay/``.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import os
import sys
import time
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, Final, Literal, Protocol, cast

import pyarrow as pa
import pyarrow.parquet as pq
from nautilus_trader.model.instruments import BinaryOption

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cli_basis_offer_gate_scan import (
    _load_stream,
    classify_instance,
    station_days_only_on_corrupt_tape,
)
from current_rung_hold_paper_replay import (
    _convert_live_capture,
    _lst_instant,
    _select_capture_instruments,
    climate_day_records_to_settlement,
    read_asos_rows,
    run_one_precision_arm,
)
from run_weather_strategy_backtests import (
    DEFAULT_WEATHER_CATALOG_ROOT,
    WEATHER_VENUE,
    TapeInstrument,
)

from breezy.domain.weather_bucket_facts import (
    WeatherFactsUnavailableError,
    read_weather_bucket_facts,
)
from breezy.persistence.feather_preflight import PreflightError, list_instance_ids, scan_instance
from breezy.registry.sites import default_registry
from breezy.settlement.trial_scorer import FilledTrial
from breezy.strategy.current_rung_hold.config import SUPPORTED_STATIONS
from breezy.strategy.current_rung_hold.strategy import _local_hour

LOOK_AHEAD_CAVEAT: Final[str] = (
    "Settlement joins the highest-`revision_seq` FINAL NWS CLI record "
    "(`climate_day_records_to_settlement:582`). Those corrections are unpublished "
    "at decision time. This run is a plumbing / take-rate / L2 fill-realism "
    "mechanism test -- not a backtest of edge. MECHANISM TEST -- NO VERDICT."
)
REPORT_TITLE: Final[str] = "MECHANISM TEST -- NO VERDICT"
NWS_INTEGER_PRECISION: Final[str] = "nws_integer_c"
LIVE_REQUIRED_LAGS: Final[tuple[int, int]] = (30, 45)

#: Env override for the containment root -- same shape as the other
#: systemd jobs' `BREEZY_*_DIR`/`BREEZY_*_ROOT` overrides (family-tally-v2-run.sh,
#: score-live-trials-run.sh), which all write derived artefacts under
#: `~/.local/share/breezy/derived`. `output_root` must resolve under
#: `<derived_root>/paper_replay/` -- never the repo root, never an arbitrary path.
DERIVED_ROOT_ENV_VAR: Final[str] = "BREEZY_DERIVED_ROOT"
#: The completion marker name for one `(station, climate_day, lag)` replay
#: attempt. Written LAST, atomically, only once `mechanism_trials.csv` and
#: `.parquet` are both fully on disk -- the skip check below reads this file
#: alone, never the trial artefacts themselves, so a crash between writing
#: the trials and writing this marker reruns rather than silently skipping.
_REPLAY_COMPLETE_MARKER: Final[str] = "REPLAY_COMPLETE"

ClassificationVerdict = Literal["CLEAN", "EMPTY", "LIVE", "CORRUPT", "PREFLIGHT_ERROR"]


class _Classifier(Protocol):
    def __call__(self, report: object, *, now_ns: int) -> str: ...


@dataclass(frozen=True, slots=True)
class TapeClassification:
    instance_id: str
    verdict: ClassificationVerdict
    total_rows: int = 0
    error: str | None = None


@dataclass(frozen=True, slots=True)
class CleanInstance:
    instance_id: str
    tape_instruments: Sequence[TapeInstrument]
    #: Instrument ids whose `Instrument.info` failed `read_weather_bucket_facts`
    #: (missing/non-mapping/malformed). Listed rather than silently dropped
    #: (finding 4) -- BLOCKED accounting, never a quiet `continue`.
    malformed_instrument_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Winner:
    station: str
    climate_day: dt.date
    instance_id: str
    first_quote_ts: int
    tape_instruments: Sequence[TapeInstrument]


@dataclass(frozen=True, slots=True)
class ReplayAttempt:
    station: str
    climate_day: dt.date
    lag_minutes: int
    output_dir: Path
    work_catalog: Path
    status: str
    argv: tuple[str, ...] = ()
    n_trials: int = 0
    strategy_refusals: Mapping[str, int] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ReplayCandidateResult:
    attempts: tuple[ReplayAttempt, ...]


class StationDayBlockedError(ValueError):
    """A station-day is not replayable and belongs in BLOCKED accounting."""


class PaperReplayOutputNotContainedError(ValueError):
    """`--output-root` does not resolve under `<derived_root>/paper_replay/`.

    Resolved and checked BEFORE any write (classify, convert, or report) --
    a paper-replay output root pointed at the repo root, an arbitrary tmp
    path, or (worse) the live scored-trials tree is refused loudly rather
    than writing rows somewhere ungoverned.
    """


def default_derived_root() -> Path:
    """The derived directory every other systemd job writes under.

    `family-tally-v2-run.sh` / `score-live-trials-run.sh` both default to
    `$HOME/.local/share/breezy/derived` and accept an env override; this
    mirrors that shape under its own env var so tests can point it at
    `tmp_path` without touching the real home directory.
    """
    override = os.environ.get(DERIVED_ROOT_ENV_VAR)
    if override:
        return Path(override).expanduser()
    return Path.home() / ".local" / "share" / "breezy" / "derived"


def assert_output_root_is_contained(output_root: Path, *, derived_root: Path) -> Path:
    """Refuse `output_root` unless it resolves under `<derived_root>/paper_replay/`.

    Returns the resolved `output_root` on success so callers use the
    already-resolved path rather than re-resolving it.
    """
    contained_root = (derived_root.expanduser() / "paper_replay").resolve()
    resolved_output = output_root.resolve()
    if resolved_output != contained_root and contained_root not in resolved_output.parents:
        raise PaperReplayOutputNotContainedError(
            f"--output-root {output_root} resolves to {resolved_output}, which is "
            f"not under {contained_root}; refusing rather than writing paper "
            "rows outside the containment root."
        )
    return resolved_output


def classify_tape_instances(
    tape_root: Path,
    *,
    now_ns: int,
    subdirectory: str = "live",
    classifier: _Classifier = classify_instance,
) -> list[TapeClassification]:
    rows: list[TapeClassification] = []
    try:
        instance_ids = list_instance_ids(tape_root, subdirectory)
    except PreflightError as exc:
        return [TapeClassification("<list_instance_ids>", "PREFLIGHT_ERROR", error=str(exc))]
    for instance_id in instance_ids:
        try:
            report = scan_instance(tape_root, instance_id, subdirectory)
            verdict = cast(ClassificationVerdict, classifier(report, now_ns=now_ns))
            rows.append(TapeClassification(instance_id, verdict, total_rows=report.total_rows))
        except PreflightError as exc:
            rows.append(TapeClassification(instance_id, "PREFLIGHT_ERROR", error=str(exc)))
    return rows


def _station_instruments(
    tape_instruments: Sequence[TapeInstrument],
    *,
    station: str,
) -> list[TapeInstrument]:
    return [ti for ti in tape_instruments if ti.facts.settlement_station == station]


def _in_window_quote_ts(
    tape_instruments: Sequence[TapeInstrument],
    *,
    station: str,
    std_utc_offset_hours: float,
) -> list[int]:
    return sorted(
        int(quote.ts_event)
        for ti in _station_instruments(tape_instruments, station=station)
        for quote in ti.quotes
        if 12 <= _local_hour(int(quote.ts_event), std_utc_offset_hours) < 17
    )


def assert_station_window_coverage(
    tape_instruments: Sequence[TapeInstrument],
    *,
    station: str,
    std_utc_offset_hours: float,
) -> None:
    if _in_window_quote_ts(
        tape_instruments,
        station=station,
        std_utc_offset_hours=std_utc_offset_hours,
    ):
        return
    station_quotes = [
        int(quote.ts_event)
        for ti in _station_instruments(tape_instruments, station=station)
        for quote in ti.quotes
    ]
    if not station_quotes:
        raise StationDayBlockedError(f"{station}: BLOCKED EMPTY_WINDOW no station QuoteTicks")
    lo = _lst_instant(min(station_quotes), std_utc_offset_hours)
    hi = _lst_instant(max(station_quotes), std_utc_offset_hours)
    raise StationDayBlockedError(
        f"{station}: BLOCKED EMPTY_WINDOW station QuoteTicks span "
        f"{lo.isoformat()} to {hi.isoformat()} LST",
    )


def _station_days(tape_instruments: Sequence[TapeInstrument]) -> set[tuple[str, dt.date]]:
    return {(ti.facts.settlement_station, ti.facts.climate_day) for ti in tape_instruments}


def _own_tape_instruments(
    tape_instruments: Sequence[TapeInstrument], *, station: str, climate_day: dt.date,
) -> tuple[TapeInstrument, ...]:
    """A CLEAN instance's `tape_instruments` merges EVERY station-day it
    captured. A `Winner` for one `(station, climate_day)` must carry only its
    own instruments -- handing the whole instance's set to
    `run_one_precision_arm` lets a fill on another day's (or station's)
    instrument masquerade as this day's trial (observed on the real
    quote-tape catalog as `EntryAskFromLatchMissingError` crashing the
    SFO/2026-08-31 replay on a fill for a 2026-09-01 instrument)."""
    return tuple(
        ti
        for ti in tape_instruments
        if ti.facts.settlement_station == station and ti.facts.climate_day == climate_day
    )


def corrupt_only_blocked_days(
    *,
    clean_station_days: Iterable[tuple[str, dt.date]],
    corrupt_station_days: Iterable[tuple[str, dt.date]],
) -> dict[tuple[str, dt.date], str]:
    return {
        key: "CORRUPT_ONLY"
        for key in station_days_only_on_corrupt_tape(
            clean_station_days=clean_station_days,
            corrupt_station_days=corrupt_station_days,
        )
    }


def select_unique_clean_winners(
    clean_instances: Sequence[CleanInstance],
    *,
    std_utc_offset_hours_by_station: Mapping[str, float],
) -> tuple[dict[tuple[str, dt.date], Winner], dict[tuple[str, dt.date], str]]:
    observations: dict[tuple[str, dt.date], list[Winner]] = {}
    blocked: dict[tuple[str, dt.date], str] = {}
    for instance in clean_instances:
        for station, climate_day in sorted(_station_days(instance.tape_instruments)):
            offset = std_utc_offset_hours_by_station[station]
            quote_ts = _in_window_quote_ts(
                instance.tape_instruments,
                station=station,
                std_utc_offset_hours=offset,
            )
            if not quote_ts:
                blocked.setdefault((station, climate_day), "EMPTY_WINDOW")
                continue
            observations.setdefault((station, climate_day), []).append(
                Winner(
                    station=station,
                    climate_day=climate_day,
                    instance_id=instance.instance_id,
                    first_quote_ts=quote_ts[0],
                    tape_instruments=_own_tape_instruments(
                        instance.tape_instruments, station=station, climate_day=climate_day,
                    ),
                ),
            )

    winners: dict[tuple[str, dt.date], Winner] = {}
    for key, candidates in observations.items():
        earliest = min(candidate.first_quote_ts for candidate in candidates)
        first_covering = [
            candidate for candidate in candidates if candidate.first_quote_ts == earliest
        ]
        if len(first_covering) > 1:
            blocked[key] = "DUAL_COVER_FIRST_INSTANT"
            continue
        winners[key] = first_covering[0]
        blocked.pop(key, None)
    return winners, blocked


def output_dir_for(output_root: Path, winner: Winner, *, lag_minutes: int) -> Path:
    return (
        output_root
        / "scored_trials"
        / winner.station
        / winner.climate_day.isoformat()
        / (f"lag_{lag_minutes}")
    )


def work_catalog_for(
    work_root: Path,
    winner: Winner,
    *,
    lag_minutes: int,
    now_ns: Callable[[], int],
) -> Path:
    stamp = now_ns()
    return (
        work_root
        / "attempts"
        / winner.station
        / winner.climate_day.isoformat()
        / f"lag_{lag_minutes}"
        / f"{winner.instance_id}-{stamp}"
    )


def _is_replay_complete(output_dir: Path) -> bool:
    """The skip sentinel: the atomic completion marker, never the trial
    artefact filenames themselves (finding 2 -- the previous glob checked
    `scored_trials_*.parquet`, which this wrapper never writes)."""
    return (output_dir / _REPLAY_COMPLETE_MARKER).exists()


def _existing_mechanism_trial_count(output_dir: Path) -> int:
    with (output_dir / "mechanism_trials.csv").open(newline="", encoding="utf-8") as handle:
        return sum(1 for _row in csv.DictReader(handle))


def _mark_replay_complete(output_dir: Path) -> None:
    """Write the completion marker LAST and atomically.

    A crash between `_write_mechanism_trials` finishing and this call must
    rerun on the next attempt, never skip -- so the marker is written to a
    temp name in the same directory (same filesystem) and renamed into place,
    which is atomic on POSIX.
    """
    marker = output_dir / _REPLAY_COMPLETE_MARKER
    tmp = output_dir / f".{_REPLAY_COMPLETE_MARKER}.tmp-{os.getpid()}"
    tmp.write_text("ok\n", encoding="utf-8")
    tmp.replace(marker)


def _best_l2_ask_at_or_before(
    tape_instruments: Sequence[TapeInstrument],
    instrument_id: str,
    ts_event: int,
) -> Decimal | None:
    depths = [
        depth
        for ti in tape_instruments
        if str(ti.instrument.id) == instrument_id
        for depth in ti.depths
        if int(depth.ts_event) <= ts_event
    ]
    if not depths:
        return None
    latest = max(depths, key=lambda depth: int(depth.ts_event))
    asks = [
        Decimal(str(level.price)) for level in latest.asks if Decimal(str(level.size)) > Decimal(0)
    ]
    if not asks:
        return None
    return min(asks)


def _trial_rows(
    winner: Winner, lag_minutes: int, trials: Sequence[FilledTrial]
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for trial in trials:
        l2_ask = _best_l2_ask_at_or_before(
            winner.tape_instruments,
            trial.instrument_id,
            winner.first_quote_ts,
        )
        fill_px = Decimal(str(trial.fill_px))
        entry_ask = Decimal(str(trial.entry_ask))
        rows.append(
            {
                "station": trial.station,
                "climate_day": trial.climate_day,
                "lag_minutes": str(lag_minutes),
                "precision_mode": NWS_INTEGER_PRECISION,
                "instrument_id": trial.instrument_id,
                "fill_px": str(fill_px),
                "entry_ask": str(entry_ask),
                "best_l2_ask_at_entry": "" if l2_ask is None else str(l2_ask),
                "fill_minus_entry_ask": str(fill_px - entry_ask),
                "fill_minus_l2_ask": "" if l2_ask is None else str(fill_px - l2_ask),
                "lookahead_caveat": LOOK_AHEAD_CAVEAT,
            }
        )
    return rows


def _write_mechanism_trials(output_dir: Path, rows: Sequence[dict[str, str]]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "LOOKAHEAD_CAVEAT.txt").write_text(LOOK_AHEAD_CAVEAT + "\n", encoding="utf-8")
    fieldnames = [
        "station",
        "climate_day",
        "lag_minutes",
        "precision_mode",
        "instrument_id",
        "fill_px",
        "entry_ask",
        "best_l2_ask_at_entry",
        "fill_minus_entry_ask",
        "fill_minus_l2_ask",
        "lookahead_caveat",
    ]
    with (output_dir / "mechanism_trials.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    table = pa.Table.from_pylist(
        list(rows), schema=pa.schema([(name, pa.string()) for name in fieldnames])
    )
    metadata = dict(table.schema.metadata or {})
    metadata[b"lookahead_caveat"] = LOOK_AHEAD_CAVEAT.encode()
    pq.write_table(table.replace_schema_metadata(metadata), output_dir / "mechanism_trials.parquet")


def replay_candidate_lags(
    winner: Winner,
    *,
    lags: Sequence[int] = LIVE_REQUIRED_LAGS,
    output_root: Path,
    work_root: Path,
    observation_rows: Sequence[dict[str, str]],
    settlement_by_key: Mapping[tuple[str, str], object],
    now_ns: Callable[[], int],
) -> ReplayCandidateResult:
    attempts: list[ReplayAttempt] = []
    for lag_minutes in lags:
        output_dir = output_dir_for(output_root, winner, lag_minutes=lag_minutes)
        work_catalog = work_catalog_for(work_root, winner, lag_minutes=lag_minutes, now_ns=now_ns)
        if _is_replay_complete(output_dir):
            attempts.append(
                ReplayAttempt(
                    station=winner.station,
                    climate_day=winner.climate_day,
                    lag_minutes=lag_minutes,
                    output_dir=output_dir,
                    work_catalog=work_catalog,
                    status="SKIPPED_EXISTING",
                    n_trials=_existing_mechanism_trial_count(output_dir),
                )
            )
            continue
        result = run_one_precision_arm(
            tape_instruments=winner.tape_instruments,
            observation_rows=observation_rows,
            station=winner.station,
            lag_minutes=lag_minutes,
            precision_mode=cast(Any, NWS_INTEGER_PRECISION),
            latch_store_path=work_catalog / "latch.db",
            settlement_by_key=cast(Any, settlement_by_key),
        )
        _write_mechanism_trials(output_dir, _trial_rows(winner, lag_minutes, result.trials))
        _mark_replay_complete(output_dir)
        attempts.append(
            ReplayAttempt(
                station=winner.station,
                climate_day=winner.climate_day,
                lag_minutes=lag_minutes,
                output_dir=output_dir,
                work_catalog=work_catalog,
                status="RAN",
                argv=(
                    "--station",
                    winner.station,
                    "--climate-day",
                    winner.climate_day.isoformat(),
                    "--lag-minutes",
                    str(lag_minutes),
                ),
                n_trials=len(result.trials),
                strategy_refusals=dict(result.strategy_refusals),
            )
        )
    return ReplayCandidateResult(tuple(attempts))


def _classification_counts(classifications: Sequence[TapeClassification]) -> dict[str, int]:
    return dict(sorted(Counter(row.verdict for row in classifications).items()))


def _cap_label(*, clean_instance_ids_loaded: Sequence[str], clean_instances_total: int) -> str:
    """Cap labelling (finding 6): a capped run says PARTIAL and names the
    selected instances; an uncapped run says WHOLE TAPE. `clean_instances_total`
    is the CLEAN count BEFORE `--max-clean-instances` truncation."""
    n_loaded = len(clean_instance_ids_loaded)
    n_total = max(clean_instances_total, n_loaded)
    if n_loaded < n_total:
        return f"PARTIAL RUN -- {n_loaded} of {n_total} CLEAN instances"
    return f"WHOLE TAPE -- {n_loaded} of {n_total} CLEAN instances"


def render_report(
    *,
    station_day_counts: Mapping[str, int],
    classifications: Sequence[TapeClassification],
    attempts: Sequence[ReplayAttempt],
    take_rate_denominator: int,
    clean_instance_ids_loaded: Sequence[str] = (),
    clean_instances_total: int = 0,
) -> str:
    n_loaded = len(clean_instance_ids_loaded)
    n_total = max(clean_instances_total, n_loaded)
    lines = [REPORT_TITLE, _cap_label(
        clean_instance_ids_loaded=clean_instance_ids_loaded,
        clean_instances_total=clean_instances_total,
    )]
    if n_loaded < n_total:
        lines.append("selected CLEAN instance ids: " + ", ".join(clean_instance_ids_loaded))
    # Each lag arm is an independent replay run over the SAME eligible
    # station-days -- summing takes across arms and reporting them over a
    # single station-day denominator pools the arms into one figure that
    # neither arm alone earned (grok_whole_tape_replay_plan_review_2026-09-05
    # finding 2: "report take-rate per arm, never pooled"). One line per
    # lag arm, each with its own numerator over the SAME denominator.
    lags_present = sorted({attempt.lag_minutes for attempt in attempts})
    take_rate_lines = [
        f"lag {lag}: "
        f"{sum(1 for a in attempts if a.lag_minutes == lag and a.n_trials > 0)}"
        f"/{take_rate_denominator}"
        for lag in lags_present
    ]
    lines += [
        "",
        LOOK_AHEAD_CAVEAT,
        "",
        *take_rate_lines,
        "",
        "instance classifications:",
    ]
    for verdict, count in _classification_counts(classifications).items():
        lines.append(f"- {verdict}: {count}")
    lines.append("")
    lines.append("station-day counts:")
    for key, count in sorted(station_day_counts.items()):
        lines.append(f"- {key}: {count}")
    lines.append("")
    lines.append("replay attempts:")
    for attempt in attempts:
        lines.append(
            f"- {attempt.station} {attempt.climate_day.isoformat()} lag={attempt.lag_minutes} "
            f"{attempt.status} trials={attempt.n_trials}"
        )
    return "\n".join(lines) + "\n"


def _write_report_bundle(
    output_root: Path, report: str, station_day_counts: Mapping[str, int]
) -> None:
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "WHOLE_TAPE_PAPER_REPLAY_REPORT.md").write_text(report, encoding="utf-8")
    with (output_root / "station_day_counts.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        # finding 5: the caveat rides on every artifact, not just the
        # markdown report and the trial parquet/csv -- the counts csv is
        # claim-adjacent (station-day denominators) and was the one file
        # missing it.
        writer.writerow(["bucket", "count", "lookahead_caveat"])
        for bucket, count in sorted(station_day_counts.items()):
            writer.writerow([bucket, count, LOOK_AHEAD_CAVEAT])
    (output_root / "LOOKAHEAD_CAVEAT.txt").write_text(LOOK_AHEAD_CAVEAT + "\n", encoding="utf-8")


def _station_offsets(station_days: Iterable[tuple[str, dt.date]]) -> dict[str, float]:
    registry = default_registry()
    return {
        station: registry.climate_day_window(WEATHER_VENUE, station).std_utc_offset_hours
        for station, _day in station_days
    }


def _load_clean_instance(
    *,
    quote_catalog: Path,
    instance_id: str,
    subdirectory: str,
    work_root: Path,
    now_ns: Callable[[], int],
) -> CleanInstance:
    work_catalog = work_root / "peek" / f"{instance_id}-{now_ns()}"
    catalog = _convert_live_capture(
        quote_catalog=quote_catalog,
        instance_id=instance_id,
        subdirectory=subdirectory,
        work_catalog=work_catalog,
    )
    # Whole-tape wrapper needs all station-days carried by the instance. The
    # current single-day selector is reused per discovered date, then merged.
    #
    # finding 4: a missing/non-mapping `climate_date` (or any other malformed
    # weather fact) must not `continue` past silently. `read_weather_bucket_facts`
    # is the SAME fail-closed reader every strategy uses; its refusal is
    # caught here and the instrument is listed under BLOCKED:MALFORMED_INSTRUMENT
    # in `run()`, never dropped without a trace.
    instruments_by_id: dict[str, TapeInstrument] = {}
    malformed_instrument_ids: list[str] = []
    for instrument in catalog.instruments():
        try:
            facts = read_weather_bucket_facts(instrument.info)
        except WeatherFactsUnavailableError:
            malformed_instrument_ids.append(str(instrument.id))
            continue
        for tape_instrument in _select_capture_instruments(
            catalog,
            climate_day=facts.climate_day,
        ):
            instruments_by_id[str(tape_instrument.instrument.id)] = tape_instrument
    return CleanInstance(
        instance_id,
        tuple(instruments_by_id.values()),
        tuple(sorted(set(malformed_instrument_ids))),
    )


def _corrupt_instance_station_days(
    *,
    quote_catalog: Path,
    subdirectory: str,
    corrupt_ids: Sequence[str],
) -> set[tuple[str, dt.date]]:
    """Identity-only read of CORRUPT instances' own instrument registrations.

    Finding 3: a station-day that exists ONLY on a corrupt tape must reach
    BLOCKED accounting, never stay silently absent because
    `corrupt_station_days` was never populated. Mirrors
    `cli_basis_offer_gate_scan.build_scan`'s own corrupt-station-day
    derivation -- read the `binary_option` registrations directly (never the
    quote/depth streams a corrupt tape cannot be trusted for) and parse facts
    via the same fail-closed `read_weather_bucket_facts`, skipping a
    malformed registration here (it carries no usable station/day identity
    to block on, and CLEAN-side malformed instruments are already
    accounted for by `_load_clean_instance`).
    """
    instance_dirs = [quote_catalog / subdirectory / instance_id for instance_id in corrupt_ids]
    station_days: set[tuple[str, dt.date]] = set()
    for instrument in _load_stream(instance_dirs, "binary_option", BinaryOption):
        try:
            facts = read_weather_bucket_facts(instrument.info)
        except WeatherFactsUnavailableError:
            continue
        station_days.add((facts.settlement_station, facts.climate_day))
    return station_days


def run(
    *,
    quote_catalog: Path,
    output_root: Path,
    work_root: Path,
    asos_cache_csv: Path,
    weather_catalog_root: Path,
    subdirectory: str = "live",
    max_clean_instances: int | None = None,
    dry_run: bool = False,
    derived_root: Path | None = None,
    now_ns: Callable[[], int] = time.time_ns,
) -> str:
    # Finding 1: resolved and checked BEFORE any write -- classify, convert,
    # and report all happen after this line, never before it.
    resolved_derived_root = default_derived_root() if derived_root is None else derived_root
    resolved_output_root = assert_output_root_is_contained(
        output_root, derived_root=resolved_derived_root
    )

    classifications = classify_tape_instances(
        quote_catalog,
        now_ns=now_ns(),
        subdirectory=subdirectory,
    )
    all_clean_ids = [row.instance_id for row in classifications if row.verdict == "CLEAN"]
    corrupt_ids = [row.instance_id for row in classifications if row.verdict == "CORRUPT"]
    clean_ids = (
        all_clean_ids if max_clean_instances is None else all_clean_ids[:max_clean_instances]
    )
    clean_instances = [
        _load_clean_instance(
            quote_catalog=quote_catalog,
            instance_id=instance_id,
            subdirectory=subdirectory,
            work_root=work_root,
            now_ns=now_ns,
        )
        for instance_id in clean_ids
    ]
    malformed_instrument_count = sum(
        len(ci.malformed_instrument_ids) for ci in clean_instances
    )
    clean_station_days = (
        set().union(*(_station_days(ci.tape_instruments) for ci in clean_instances))
        if clean_instances
        else set()
    )
    # Finding 3: an identity-only read of CORRUPT instances' own instrument
    # registrations -- never left empty -- so a station-day that exists ONLY
    # on a corrupt tape reaches BLOCKED:CORRUPT_ONLY rather than staying
    # invisible.
    corrupt_station_days = _corrupt_instance_station_days(
        quote_catalog=quote_catalog,
        subdirectory=subdirectory,
        corrupt_ids=corrupt_ids,
    )
    blocked = corrupt_only_blocked_days(
        clean_station_days=clean_station_days,
        corrupt_station_days=corrupt_station_days,
    )
    offsets = _station_offsets(clean_station_days)
    all_winners, winner_blocked = select_unique_clean_winners(
        clean_instances,
        std_utc_offset_hours_by_station=offsets,
    )
    blocked.update(winner_blocked)
    # `CurrentRungHoldConfig` refuses any station outside `SUPPORTED_STATIONS`
    # at construction (NYC/KNYC is hourly-only, A14) -- a real-catalog winner
    # for an unsupported station is BLOCKED here, before `replay_candidate_lags`
    # ever calls it, rather than crashing the whole run.
    winners: dict[tuple[str, dt.date], Winner] = {}
    for key, winner in all_winners.items():
        if winner.station not in SUPPORTED_STATIONS:
            blocked[key] = "UNSUPPORTED_STATION"
            continue
        winners[key] = winner

    attempts: list[ReplayAttempt] = []
    if not dry_run:
        observation_rows = read_asos_rows(asos_cache_csv)
        settlement_by_key: dict[tuple[str, str], object] = {}
        for key, winner in list(winners.items()):
            settlement_by_key.update(
                climate_day_records_to_settlement(winner.tape_instruments, weather_catalog_root)
            )
            # `build_backtest_engine` requires a `CONTRACT_EXPIRED` close on
            # every tradeable instrument, and `_synthesize_close` can only
            # build one from a FINAL settlement record. A station-day whose
            # climate day has not closed yet (e.g. today's) has none --
            # BLOCKED here, before `replay_candidate_lags` crashes the whole
            # run on `SettlementInvariantError`.
            if (winner.station, winner.climate_day.isoformat()) not in settlement_by_key:
                blocked[key] = "NO_FINAL_SETTLEMENT"
                del winners[key]
                continue
            attempts.extend(
                replay_candidate_lags(
                    winner,
                    output_root=resolved_output_root,
                    work_root=work_root,
                    observation_rows=observation_rows,
                    settlement_by_key=settlement_by_key,
                    now_ns=now_ns,
                ).attempts
            )

    station_day_counts: dict[str, int] = {
        "replayed": len(winners) if not dry_run else 0,
        "eligible_clean_unique_winner": len(winners),
        "clean_instances_loaded": len(clean_ids),
        "clean_instances_total": len(all_clean_ids),
    }
    if malformed_instrument_count:
        station_day_counts["BLOCKED:MALFORMED_INSTRUMENT"] = malformed_instrument_count
    for reason in blocked.values():
        station_day_counts[f"BLOCKED:{reason}"] = station_day_counts.get(f"BLOCKED:{reason}", 0) + 1
    report = render_report(
        station_day_counts=station_day_counts,
        classifications=classifications,
        attempts=attempts,
        take_rate_denominator=len(winners),
        clean_instance_ids_loaded=clean_ids,
        clean_instances_total=len(all_clean_ids),
    )
    _write_report_bundle(resolved_output_root, report, station_day_counts)
    return report


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quote-catalog", required=True, type=Path)
    # `--output-root` / `--work-root` default to None here and are resolved
    # against `--derived-root` (or its env default) in `main()` -- a bare
    # `Path("derived/paper_replay")` literal is a REPO-RELATIVE path and
    # would be refused by the containment guard (finding 1).
    parser.add_argument("--output-root", default=None, type=Path)
    parser.add_argument("--work-root", default=None, type=Path)
    parser.add_argument("--derived-root", default=None, type=Path)
    parser.add_argument("--asos-cache-csv", type=Path)
    parser.add_argument(
        "--weather-catalog-root",
        default=DEFAULT_WEATHER_CATALOG_ROOT,
        type=Path,
    )
    parser.add_argument("--tape-subdirectory", default="live")
    parser.add_argument("--max-clean-instances", type=int)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(list(argv))


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    if not args.dry_run and args.asos_cache_csv is None:
        raise SystemExit("--asos-cache-csv is required unless --dry-run is set")
    derived_root = args.derived_root or default_derived_root()
    output_root = args.output_root or (derived_root / "paper_replay")
    work_root = args.work_root or (output_root / "work")
    report = run(
        quote_catalog=args.quote_catalog,
        output_root=output_root,
        work_root=work_root,
        asos_cache_csv=args.asos_cache_csv or Path("/dev/null"),
        weather_catalog_root=args.weather_catalog_root,
        subdirectory=args.tape_subdirectory,
        max_clean_instances=args.max_clean_instances,
        dry_run=args.dry_run,
        derived_root=derived_root,
    )
    print(report, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
