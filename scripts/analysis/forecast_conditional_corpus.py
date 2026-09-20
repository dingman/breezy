"""Stage 0b corpus: the joined station-day record and its leak guards (WP-6).

Library half of ``forecast_conditional_model_study.py`` -- the same
``*_core`` / consumer split the repo already uses for the exit-window, resting-bid
and monitor studies. It owns the PRE-DECLARATION (the split, the decision
instant, the lead set, the closed feature set, the cadence), the four leakage
guards, and the streaming readers that reduce three archives to ONE ROW PER
STATION-DAY. It scores nothing: no model, no Brier, no verdict lives here.

THE SPLIT
    Fit 2021-01-01 .. 2024-12-31 inclusive; holdout 2025, untouched while fitting.

LEAKAGE VECTORS -- WHAT IS ACTUALLY ENFORCED, AND WHAT IS ONLY DECLARED
    Two of these are real runtime guards over real runtime data. Two are
    assertions over module ``Final`` constants and CANNOT fail at run time; they
    are declarations with an assert-shaped spelling, and calling them "guards"
    without this paragraph overstated the defence (review defect 7).

    ENFORCED AT RUN TIME, over data that varies:
    1. TRAIN WINDOW -- the SHIPPED ``fit_error_model(train_end_exclusive=...)``,
       reused rather than reimplemented and never called from a strategy
       handler. It sees every training record and refuses a 2025 one.
    2. VINTAGE -- ``assert_forecast_vintage`` on the BUILD path (per MOS row) and
       ``assert_corpus_vintage`` on the CACHED-CORPUS LOAD path. A forecast may
       price a climate day only if its run was issued at or before the DECLARED
       decision instant (``DECISION_UTC_HOUR`` = 12:00Z on that day, i.e.
       04:00-07:00 local standard at every registered station). The shortest lead
       the NBS archive carries for the daily-max ftime is 17 h (run 07:00Z),
       which clears it. The load-path re-assertion exists because EVERY number in
       the artefact was produced through the cached corpus, where no forecast
       runtime survives -- without it the load path validated nothing
       vintage-related (review defect 5).
    3. DUPLICATE TRIALS -- ``assert_unique_station_days``, over corpus rows.
       THE TRIAL UNIT IS ONE STATION-DAY, never an hourly row.

    DECLARED, NOT ENFORCED (tautological over constants -- say so, do not claim
    otherwise):
    4. TARGET INTO FEATURE -- ``assert_features_exclude_target`` is called with
       ``DECLARED_FEATURE_NAMES``, a module ``Final``. It can only fail if a
       future edit adds a target-derived name to that tuple, which a test would
       catch at import. The REAL protection is that the scoring code reads only
       ``forecast_txn_f_by_lead`` and never ``settled_tmax_f`` except as the
       outcome. ``DECLARED_FEATURE_NAMES`` is a CLOSED tuple fixed before the
       holdout was scored (L-21).
    5. CADENCE -- ``assert_single_cadence`` over rows the builder stamps with a
       literal ``OBS_CADENCE_SECONDS`` is likewise tautological on the BUILD
       path. It is NOT tautological on the cached-corpus LOAD path, where the
       value comes off disk and a hand-edited or stale corpus can carry a second
       cadence; that is the only configuration in which it can fire.

KNOWN DEFECT -- WP-7 BLOCKER, NOT A WP-6 DEFECT
    ``observations_from_asos_payload`` converts UTC to local using the STANDARD
    UTC offset all year, so every local timestamp is one hour early during
    daylight saving. That does not touch any number this study scores:
    ``obs_max_f`` and ``running_max_f_by_local_hour`` are carried in the corpus
    and read by NO model here (the daily max is offset-insensitive to within the
    day boundary, and R(t) is unused). It IS wrong for the WP-7 R(t) features,
    where an hour of shift moves the running max. WP-7 MUST fix this before
    using ``running_max_f_by_local_hour``.

L-13 -- CADENCE
    An extremum is NOT comparable across sampling cadences: a running maximum
    from a sparse series is biased LOW. Every observation-derived extremum here
    is downsampled from the 1-minute archive onto ONE declared grid,
    ``OBS_CADENCE_SECONDS`` = 300 s, recorded in the artefact.
    ``assert_single_cadence`` refuses a comparison that mixes two.

MEMORY
    One station-year at a time, streamed. The ASOS archive is ~367 MB / 9.0 M rows
    across 20 station-years and is NEVER all resident: each payload is decoded
    through a streaming ``TextIOWrapper`` and reduced immediately to per-climate-day
    scalars, then dropped. Peak resident is one ASOS station-year (~23 MB) plus the
    ~7.3 k-row corpus.

No network. Reads only pre-existing local caches; writes nothing.
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import json
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

_SCRIPTS_ANALYSIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPTS_ANALYSIS_DIR.parents[1]
for _entry in (str(_SCRIPTS_ANALYSIS_DIR), str(_REPO_ROOT / "src")):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from forecast_climate_day_map import TXN_MAX_PERIOD_END_UTC_HOUR, climate_day_for_txn

NS: Final[int] = 10**9
_SECONDS_PER_HOUR: Final[int] = 3600


# ---------------------------------------------------------------------------
# THE PRE-DECLARATION. Everything below is fixed BEFORE the holdout is scored.
# ---------------------------------------------------------------------------

FIT_START: Final[dt.date] = dt.date(2021, 1, 1)
#: Inclusive fit end is 2024-12-31; the guard wants the exclusive bound.
FIT_END_EXCLUSIVE: Final[dt.date] = dt.date(2025, 1, 1)
HOLDOUT_START: Final[dt.date] = dt.date(2025, 1, 1)
HOLDOUT_END: Final[dt.date] = dt.date(2025, 12, 31)

#: The decision instant: 12:00Z on the climate day. Every registered station
#: sits at UTC-5..UTC-8, so 12:00Z is 04:00-07:00 local standard -- before the
#: local trading window opens. A forecast runtime AFTER this instant is refused.
DECISION_UTC_HOUR: Final[int] = 12

#: Leads (hours from runtime to the daily-MAX ftime at 00Z) the NBS archive
#: actually carries for a climate day, every one of them vintage-legal. The
#: PRIMARY lead -- the one the model is fitted and scored on -- is the shortest,
#: i.e. the freshest forecast a trader could hold at the decision instant.
LEAD_BINS_HOURS: Final[tuple[int, ...]] = (17, 23, 29, 35, 41, 47)
PRIMARY_LEAD_HOURS: Final[int] = 17

#: L-13. The single declared cadence for every observation-derived extremum.
OBS_CADENCE_SECONDS: Final[int] = 300

#: Local-standard hours at which the running max R(t) is recorded. Carried in
#: the corpus for WP-7; NOT a feature of either model scored here.
R_LOCAL_HOURS: Final[tuple[int, ...]] = (8, 10, 12, 14)

#: CLOSED feature set of the forecast-conditioned model (L-21). Adding a name
#: here after seeing a holdout miss is the exact move this tuple forbids.
DECLARED_FEATURE_NAMES: Final[tuple[str, ...]] = (
    "forecast_txn_f_lead17",
    "station",
    "climate_day_month",
    "lead_hours",
)
TARGET_NAME: Final[str] = "settled_tmax_f"
#: Anything derived from the CLI final. None of these may be a feature.
TARGET_DERIVED_NAMES: Final[frozenset[str]] = frozenset(
    {TARGET_NAME, "settled_tmax", "cli_tmax_f", "cli_final", "realized_high_f"}
)

#: Climatology baseline: per station, the +/- window in days-of-year pooled
#: around the target day, fit on TRAIN ONLY.
CLIMATOLOGY_DOY_HALF_WINDOW: Final[int] = 7
CLIMATOLOGY_MIN_SAMPLES: Final[int] = 30

#: Trial families, both declared now. "median" is the HEADLINE.
FAMILY_MEDIAN: Final[str] = "median"
FAMILY_RUNG: Final[str] = "rung"
TRIAL_FAMILIES: Final[tuple[str, ...]] = (FAMILY_MEDIAN, FAMILY_RUNG)
#: Venue interior rungs are 2F wide; the rung family asks whether the settled
#: integer lands in the 2F rung the point forecast itself picks out.
RUNG_WIDTH_F: Final[int] = 2

#: Sufficiency floors. Below any of these the run reports INSUFFICIENT_DATA and
#: EXITS 0 -- thin data is an outcome, never a verdict.
MIN_TRAIN_STATION_DAYS: Final[int] = 400
MIN_HOLDOUT_STATION_DAYS_POOLED: Final[int] = 200
MIN_HOLDOUT_STATION_DAYS_PER_STATION: Final[int] = 100

BOOTSTRAP_ITERATIONS: Final[int] = 2000
BOOTSTRAP_SEED: Final[int] = 20260919
BOOTSTRAP_ALPHA: Final[float] = 0.05

RELIABILITY_BUCKET_EDGES: Final[tuple[float, ...]] = (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9)

VERDICT_INSUFFICIENT_DATA: Final[str] = "INSUFFICIENT_DATA"
VERDICT_SCORED: Final[str] = "SCORED"

STATIONS: Final[tuple[tuple[str, str], ...]] = (
    ("KMIA", "MIA"),
    ("KMDW", "MDW"),
    ("KSFO", "SFO"),
    ("KLAX", "LAX"),
)
MOS_MODEL: Final[str] = "NBS"
ARTEFACT_SCHEMA: Final[str] = "breezy.forecast_conditional_model_study/2"


class LeakageError(RuntimeError):
    """Raised when a corpus or a comparison would leak information."""



# ---------------------------------------------------------------------------
# Corpus
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CorpusRow:
    """One trial unit: one station-day."""

    station: str
    climate_day: dt.date
    settled_tmax_f: int
    forecast_txn_f_by_lead: Mapping[int, float]
    obs_max_f: float | None
    running_max_f_by_local_hour: Mapping[int, float]
    obs_cadence_seconds: int

    def to_dict(self) -> dict[str, object]:
        """Explicit serialisation -- ``dataclasses.asdict`` is banned repo-wide."""
        return {
            "station": self.station,
            "climate_day": self.climate_day.isoformat(),
            "settled_tmax_f": self.settled_tmax_f,
            "forecast_txn_f_by_lead": {
                str(k): self.forecast_txn_f_by_lead[k] for k in sorted(self.forecast_txn_f_by_lead)
            },
            "obs_max_f": self.obs_max_f,
            "running_max_f_by_local_hour": {
                str(k): self.running_max_f_by_local_hour[k]
                for k in sorted(self.running_max_f_by_local_hour)
            },
            "obs_cadence_seconds": self.obs_cadence_seconds,
        }

    @classmethod
    def from_dict(cls, values: Mapping[str, object]) -> CorpusRow:
        return cls(
            station=str(values["station"]),
            climate_day=dt.date.fromisoformat(str(values["climate_day"])),
            settled_tmax_f=int(values["settled_tmax_f"]),  # type: ignore[arg-type]
            forecast_txn_f_by_lead={
                int(k): float(v)
                for k, v in dict(values["forecast_txn_f_by_lead"]).items()  # type: ignore[call-overload]
            },
            obs_max_f=None if values["obs_max_f"] is None else float(values["obs_max_f"]),  # type: ignore[arg-type]
            running_max_f_by_local_hour={
                int(k): float(v)
                for k, v in dict(values["running_max_f_by_local_hour"]).items()  # type: ignore[call-overload]
            },
            obs_cadence_seconds=int(values["obs_cadence_seconds"]),  # type: ignore[arg-type]
        )


# ---------------------------------------------------------------------------
# Leak guards
# ---------------------------------------------------------------------------


def assert_forecast_vintage(*, station: str, climate_day: dt.date, runtime_ns: int) -> None:
    """Refuse a forecast issued after the declared decision instant.

    A forecast may price a climate day ONLY if it was issued before that day's
    trading window. Without this, a 3-hour-lead run published at local noon --
    after the market has already moved -- would look like a brilliant predictor
    of a day it had half-observed.
    """
    decision = dt.datetime(
        climate_day.year, climate_day.month, climate_day.day, DECISION_UTC_HOUR, tzinfo=dt.UTC
    )
    decision_ns = int(decision.timestamp()) * NS
    if runtime_ns > decision_ns:
        issued = dt.datetime.fromtimestamp(runtime_ns / NS, tz=dt.UTC)
        raise LeakageError(
            f"forecast vintage violation: {station} {climate_day.isoformat()} would use a run "
            f"issued {issued.isoformat()}, AFTER the declared decision instant "
            f"{decision.isoformat()}; that forecast was not available to a trader standing at "
            "the window open"
        )


def assert_corpus_vintage(rows: Sequence[CorpusRow]) -> None:
    """Re-assert forecast vintage from a corpus that no longer carries runtimes.

    A ``CorpusRow`` stores forecasts keyed by LEAD, not by run time, so the
    runtime is reconstructed exactly: the daily-max ``ftime`` is 00:00Z on
    ``climate_day + 1`` (the MEASURED end hour frozen in
    ``forecast_climate_day_map``), hence ``runtime = ftime - lead``. Every lead
    in every row is then put through the same
    :func:`assert_forecast_vintage` the build path uses.

    This is the load path's ONLY vintage defence. ``build_corpus`` checks each
    MOS row as it is read, but the scored runs load a cached corpus JSON, and a
    stale or hand-edited one carrying a lead shorter than the declared set
    implies a run issued after the decision instant. Leads outside
    ``LEAD_BINS_HOURS`` are refused outright rather than merely skipped: on the
    load path a surprise lead is corruption, not a row to drop quietly.
    """
    for row in rows:
        ftime_day = row.climate_day + dt.timedelta(days=1)
        ftime = dt.datetime(
            ftime_day.year, ftime_day.month, ftime_day.day, TXN_MAX_PERIOD_END_UTC_HOUR,
            tzinfo=dt.UTC,
        )
        ftime_ns = int(ftime.timestamp()) * NS
        for lead in sorted(row.forecast_txn_f_by_lead):
            if lead not in LEAD_BINS_HOURS:
                raise LeakageError(
                    f"forecast vintage violation: {row.station} "
                    f"{row.climate_day.isoformat()} carries undeclared lead {lead} h; the "
                    f"declared set is {list(LEAD_BINS_HOURS)}. On the cached-corpus load "
                    "path an undeclared lead is corruption, not a row to drop"
                )
            assert_forecast_vintage(
                station=row.station,
                climate_day=row.climate_day,
                runtime_ns=ftime_ns - lead * _SECONDS_PER_HOUR * NS,
            )


def load_cached_corpus(path: Path) -> list[CorpusRow]:
    """Load a cached corpus JSON and re-run every guard the build path ran.

    Loading is NOT a cheaper build: the same uniqueness, vintage and cadence
    checks apply, because the file on disk is untrusted input.
    """
    rows = [
        CorpusRow.from_dict(value)
        for value in json.loads(path.read_text(encoding="utf-8"))
    ]
    assert_unique_station_days(rows)
    assert_corpus_vintage(rows)
    assert_single_cadence({row.obs_cadence_seconds for row in rows})
    return rows


def assert_unique_station_days(rows: Sequence[CorpusRow]) -> None:
    """Refuse a duplicated ``(station, climate_day)``; the trial unit is one station-day."""
    seen: set[tuple[str, dt.date]] = set()
    for row in rows:
        key = (row.station, row.climate_day)
        if key in seen:
            raise LeakageError(
                f"duplicate station-day {key[0]} {key[1].isoformat()}: the trial unit is ONE "
                "station-day, so a repeat would inflate n and shrink every interval"
            )
        seen.add(key)


def assert_features_exclude_target(names: Iterable[str]) -> None:
    """Refuse a feature set carrying anything derived from the CLI final."""
    offending = sorted(set(names) & TARGET_DERIVED_NAMES)
    if offending:
        raise LeakageError(
            f"target leakage: {offending} are derived from the CLI settlement final and may "
            "never be model features"
        )


def assert_single_cadence(cadences: Iterable[int]) -> None:
    """L-13. Refuse an extremum comparison that mixes sampling cadences."""
    distinct = sorted(set(cadences))
    if len(distinct) != 1:
        raise LeakageError(
            f"cadence mixing (L-13): extremum statistics were taken at {distinct} seconds. "
            "A running maximum from a sparse series is biased LOW, so cross-cadence "
            "comparison manufactures a difference that is pure sampling artefact."
        )


def assert_split_disjoint(train: Sequence[CorpusRow], holdout: Sequence[CorpusRow]) -> None:
    """Refuse any station-day present on both sides of the split."""
    train_keys = {(r.station, r.climate_day) for r in train}
    holdout_keys = {(r.station, r.climate_day) for r in holdout}
    shared = train_keys & holdout_keys
    if shared:
        example = min(shared)
        raise LeakageError(
            f"train/holdout overlap: {len(shared)} station-days appear on both sides "
            f"(e.g. {example[0]} {example[1].isoformat()})"
        )


def split_corpus(rows: Sequence[CorpusRow]) -> tuple[list[CorpusRow], list[CorpusRow]]:
    """Split on the declared boundary; anything outside both windows is dropped."""
    train = [r for r in rows if FIT_START <= r.climate_day < FIT_END_EXCLUSIVE]
    holdout = [r for r in rows if HOLDOUT_START <= r.climate_day <= HOLDOUT_END]
    assert_split_disjoint(train, holdout)
    return train, holdout


def downsample_running_max(
    samples: Sequence[tuple[dt.datetime, float]], *, cadence_seconds: int
) -> list[tuple[dt.datetime, float]]:
    """Keep only samples on the declared cadence grid (L-13).

    Selection is on the absolute epoch grid, not on arrival order, so the kept
    set is identical however the source series is chunked.
    """
    if cadence_seconds <= 0:
        raise ValueError("cadence_seconds must be positive")
    return [
        (when, value)
        for when, value in samples
        if int(when.timestamp()) % cadence_seconds == 0
    ]



# ---------------------------------------------------------------------------
# Real I/O -- one station-year at a time, streamed (see the MEMORY note)
# ---------------------------------------------------------------------------


def _archive_cache(source: str):
    from breezy.persistence.archive_cache import ArchiveCache

    def _refuse(_request: object) -> bytes:
        raise RuntimeError("this study never fetches; the archive must already be on disk")

    class _NoClock:
        def timestamp_ns(self) -> int:
            return 0

    return ArchiveCache(
        root=Path.home() / ".local/share/breezy/archive" / source, fetch=_refuse, clock=_NoClock()
    )


def forecasts_from_mos_payload(
    body: bytes, *, icao: str, std_utc_offset_hours: float
) -> dict[dt.date, dict[int, float]]:
    """Reduce one MOS station-year to ``climate_day -> {lead_hours: txn_f}``.

    Only the daily-MAX ftime rows carry ``txn`` at the max hour; the frozen
    ``climate_day_for_txn`` map decides the day, and ``assert_forecast_vintage``
    decides whether the run was available in time.
    """
    from forecast_climate_day_map import ForecastValidPeriodError

    out: dict[dt.date, dict[int, float]] = {}
    stream = io.TextIOWrapper(io.BytesIO(body), encoding="utf-8", newline="")
    for row in csv.DictReader(stream):
        raw = (row.get("txn") or "").strip()
        if not raw:
            continue
        runtime = dt.datetime.strptime(row["runtime"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=dt.UTC)
        ftime = dt.datetime.strptime(row["ftime"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=dt.UTC)
        runtime_ns = int(runtime.timestamp()) * NS
        ftime_ns = int(ftime.timestamp()) * NS
        try:
            climate_day = climate_day_for_txn(
                icao=icao,
                runtime_ns=runtime_ns,
                ftime_ns=ftime_ns,
                std_utc_offset_hours=std_utc_offset_hours,
                model=MOS_MODEL,
                kind="max",
            )
        except ForecastValidPeriodError:
            continue  # daily-MIN rows and off-grid ftimes are not this study's target
        lead = int((ftime - runtime).total_seconds() // 3600)
        if lead not in LEAD_BINS_HOURS:
            continue
        assert_forecast_vintage(station=icao, climate_day=climate_day, runtime_ns=runtime_ns)
        out.setdefault(climate_day, {})[lead] = float(raw)
    return out


def observations_from_asos_payload(
    body: bytes, *, std_utc_offset_hours: float
) -> dict[dt.date, tuple[float, dict[int, float]]]:
    """Reduce one ASOS station-year to ``climate_day -> (obs_max_f, R(t) by local hour)``.

    Streamed and downsampled to ``OBS_CADENCE_SECONDS`` on the epoch grid (L-13).
    Nothing larger than the payload itself is ever resident.
    """
    offset = dt.timedelta(hours=std_utc_offset_hours)
    daily_max: dict[dt.date, float] = {}
    running: dict[dt.date, dict[int, float]] = {}
    stream = io.TextIOWrapper(io.BytesIO(body), encoding="utf-8", newline="")
    reader = csv.reader(stream)
    header = next(reader)
    i_valid = header.index("valid(UTC)")
    i_temp = header.index("tmpf")
    for row in reader:
        raw = row[i_temp].strip()
        if not raw or raw == "M":
            continue
        when = dt.datetime.strptime(row[i_valid], "%Y-%m-%d %H:%M").replace(tzinfo=dt.UTC)
        if int(when.timestamp()) % OBS_CADENCE_SECONDS:
            continue  # the declared cadence grid, applied once, here
        local = when + offset
        day = local.date()
        value = float(raw)
        if value > daily_max.get(day, -999.0):
            daily_max[day] = value
        cell = running.setdefault(day, {})
        for hour in R_LOCAL_HOURS:
            if local.hour <= hour and value > cell.get(hour, -999.0):
                cell[hour] = value
    return {day: (daily_max[day], running.get(day, {})) for day in daily_max}


def build_corpus(*, start: dt.date, end: dt.date, progress=None) -> list[CorpusRow]:
    """Join the three archives into one row per station-day. Streams per station-year."""
    from settlement_alignment_cache import (
        DEFAULT_SETTLEMENT_ALIGNMENT_CACHE_DIR,
        require_settlement_alignment_cache_dir,
    )
    from settlement_alignment_study import load_sites

    from breezy.persistence.archive_request import iem_asos_1min_request, iem_mos_request

    cli_dir = require_settlement_alignment_cache_dir(DEFAULT_SETTLEMENT_ALIGNMENT_CACHE_DIR)
    sites = {spec.city: spec for spec in load_sites()}
    mos_cache = _archive_cache("iem-mos")
    asos_cache = _archive_cache("iem-asos-1min")
    years = tuple(range(start.year, end.year + 1))

    rows: list[CorpusRow] = []
    for icao, city in STATIONS:
        spec = sites[city]
        offset = spec.std_utc_offset_hours
        forecasts: dict[dt.date, dict[int, float]] = {}
        observations: dict[dt.date, tuple[float, dict[int, float]]] = {}
        for year in years:
            forecasts.update(
                forecasts_from_mos_payload(
                    mos_cache.read(iem_mos_request(icao, year, MOS_MODEL)),
                    icao=icao,
                    std_utc_offset_hours=offset,
                )
            )
            observations.update(
                observations_from_asos_payload(
                    asos_cache.read(iem_asos_1min_request(icao, year)),
                    std_utc_offset_hours=offset,
                )
            )
            if progress:
                progress(f"{icao} {year}: mos_days={len(forecasts)} obs_days={len(observations)}")
        from pmr_climatology_study import load_cli_records

        finals, _every, _drops = load_cli_records(
            cache_dir=cli_dir, spec=spec, start=start, end=end
        )
        for climate_day in sorted(finals):
            record = finals[climate_day]
            if record.tmax_f is None:
                continue
            leads = forecasts.get(climate_day)
            if not leads or PRIMARY_LEAD_HOURS not in leads:
                continue
            obs = observations.get(climate_day)
            rows.append(
                CorpusRow(
                    station=icao,
                    climate_day=climate_day,
                    settled_tmax_f=int(record.tmax_f),
                    forecast_txn_f_by_lead=dict(sorted(leads.items())),
                    obs_max_f=None if obs is None else obs[0],
                    running_max_f_by_local_hour={} if obs is None else dict(sorted(obs[1].items())),
                    obs_cadence_seconds=OBS_CADENCE_SECONDS,
                )
            )
        forecasts.clear()
        observations.clear()
    assert_unique_station_days(rows)
    return rows


def archive_payload_digests() -> dict[str, str]:
    """sha256 of every SOURCE archive payload the corpus was built from.

    Read straight out of each cache's own ``coverage.json`` manifest -- the
    digest the cache already verifies the payload against on every read -- so
    the artefact is traceable to the exact bytes on disk, not merely to the
    derived corpus. Missing or unreadable manifests are reported as a value,
    never silently omitted, because a blank provenance field reads like a
    verified one.
    """
    out: dict[str, str] = {}
    for source in ("iem-mos", "iem-asos-1min"):
        manifest = Path.home() / ".local/share/breezy/archive" / source / source / "coverage.json"
        if not manifest.is_file():
            out[f"archive:{source}"] = "MANIFEST_ABSENT"
            continue
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            entries = payload["entries"]
        except (OSError, ValueError, KeyError):
            out[f"archive:{source}"] = "MANIFEST_UNREADABLE"
            continue
        for entry in entries.values():
            key = f"archive:{source}:{entry['station']}:{entry['window_start']}"
            out[key] = str(entry["sha256"])
    return out


def corpus_digests(rows: Sequence[CorpusRow]) -> dict[str, str]:
    """sha256 over the canonical corpus, per station and pooled."""
    digests: dict[str, str] = {}
    pooled = hashlib.sha256()
    for station in sorted({r.station for r in rows}):
        per = hashlib.sha256()
        for row in sorted(
            (r for r in rows if r.station == station), key=lambda r: r.climate_day
        ):
            line = json.dumps(row.to_dict(), sort_keys=True).encode("utf-8")
            per.update(line)
            pooled.update(line)
        digests[f"corpus:{station}"] = per.hexdigest()
    digests["corpus:pooled"] = pooled.hexdigest()
    return digests

