#!/usr/bin/env python
"""AUD-09b scheduled replay runner (base plan §6b.3; AUD-09b amendment §4).

One invocation replays AT MOST one `(station, climate_day)` for the ARMED
family only (base plan §6b.2). Owns, end to end: reading
`replay_sufficiency.jsonl` (H0), target selection under the full key
`(station, climate_day, strategy, lag_minutes)`, the ASOS-producer and
driver subprocess invocations, the RECOVERED/FAILED crash branch,
`record_blocked`, the row append (H3), the daily summary line, the B19
stall-alert escalation, and the R4 provenance-drift check.

`deploy/systemd/replay-daily-run.sh` is a thin wrapper (base plan §6b.3):
it takes the host-wide studies lock, resolves environment paths (including
the armed family's manifest, via the same `systemctl --user show
breezy-trade-supervisor.service` idiom `score-live-trials-run.sh` /
`family-tally-v2-run.sh` already use), and invokes this module twice --
`replay_sufficiency_census.py` first, then this script. It contains no
JSONL parsing and no `record_blocked` (B18).

**Why `--family-manifest` is passed (a documented divergence from the base
plan's literal command block, §6b.3).** The base plan was written before
AUD-19b landed `--family-manifest` on
`current_rung_hold_paper_replay.py` (module docstring there: "AUD-19b").
With the flag available, every row's `engine_params_source` is
`"FAMILY_MANIFEST"`, read back from the driver's own `family_params.json`
provenance sidecar -- never `"DRIVER_DEFAULTS"` (that source only applied
when the flag did not exist). B16/B20 are satisfied more strongly this way:
`params_match` reflects the ENGINE's own readback, not an inference.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import resource
import subprocess
import sys
import tempfile
import time
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

sys.path.insert(0, str(Path(__file__).resolve().parent))

from breezy.analysis.replay_results import (
    REPLAY_RESULTS_SCHEMA_VERSION,
    REPLAY_VALIDITY,
    DuplicateReplayResultError,
    ReplayResult,
    UnknownReplayResultSchemaError,
    append_replay_result,
    read_replay_results,
    terminal_keys,
)
from breezy.analysis.replay_sufficiency import (
    DuplicateReplaySufficiencyRecordError,
    ReplaySufficiency,
    UnknownReplaySufficiencySchemaError,
    is_replayable_whole_day,
    read_replay_sufficiency,
)
from breezy.domain.climate_day import standard_time_zone
from breezy.persistence.scored_trial_store import read_scored_trials
from breezy.runtime.health import (
    AlertPayload,
    AlertSink,
    emit_alert,
    resolve_alert_sink,
)
from breezy.strategy.current_rung_hold.config import SUPPORTED_STATIONS

__all__ = [
    "DEFAULT_LAG_MINUTES",
    "DEFAULT_REPLAY_DRIFT_PATH",
    "DEFAULT_REPLAY_RESULTS_PATH",
    "DEFAULT_REPLAY_SUFFICIENCY_PATH",
    "DEFAULT_STRATEGY",
    "REPLAY_DRIFT_SCHEMA_VERSION",
    "STALL_ALERT_RUN_LENGTH",
    "WEATHER_VENUE",
    "DriftRecord",
    "RunConfig",
    "SubprocessRunner",
    "build_asos_argv",
    "build_driver_argv",
    "classify_asos_failure",
    "classify_driver_failure",
    "compute_drift",
    "main",
    "read_replay_drift",
    "record_blocked",
    "run_once",
    "select_target",
    "stall_run_length",
    "write_replay_drift",
]

#: Same literal every replay driver/census script uses
#: (`run_weather_strategy_backtests.py:352`).
WEATHER_VENUE: Final[str] = "polymarket_us"

DEFAULT_STRATEGY: Final[str] = "continuous_rung_hold"
#: Matches the base plan's own literal command block (§6b.3).
DEFAULT_LAG_MINUTES: Final[int] = 30

_DERIVED_ROOT: Final[Path] = Path.home() / ".local/share/breezy/derived"
DEFAULT_REPLAY_SUFFICIENCY_PATH: Final[Path] = (
    _DERIVED_ROOT / "replay" / "replay_sufficiency.jsonl"
)
DEFAULT_REPLAY_RESULTS_PATH: Final[Path] = _DERIVED_ROOT / "replay" / "replay_results.jsonl"
DEFAULT_REPLAY_DRIFT_PATH: Final[Path] = _DERIVED_ROOT / "replay" / "replay_drift.jsonl"

#: AUD-08 §9's own three-consecutive-failure tolerance (base plan §6b.3,
#: "N = 3 is not a new number").
STALL_ALERT_RUN_LENGTH: Final[int] = 3

#: `current_rung_hold_paper_replay.py`'s own exit codes (module docstring
#: above: hardcoded rather than imported, to keep this module's import
#: surface light -- the driver runs only as a subprocess here, never
#: imported). Re-verify against the driver's own `EXIT_FAMILY_MANIFEST_*`
#: constants if that module's exit-code table ever changes.
_EXIT_FAMILY_MANIFEST_REFUSED: Final[int] = 2
_EXIT_FAMILY_MANIFEST_UNUSABLE: Final[int] = 3

_EXCEPTION_NAME_RE: Final[re.Pattern[str]] = re.compile(r"\b([A-Z][A-Za-z0-9_]*Error)\b")

REPLAY_DRIFT_SCHEMA_VERSION: Final[int] = 1


# ---------------------------------------------------------------------------
# R4: provenance drift
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class DriftRecord:
    """One replayed key whose census provenance has since changed (R4,
    resolves base plan F7). `new_verdict` is `"MISSING"` when the
    `(station, climate_day)` no longer appears in the census at all
    (Rev 2.1 item 4)."""

    schema_version: int
    station: str
    climate_day: str
    strategy: str
    lag_minutes: int
    replayed_tape_instance_id: str
    new_verdict: str
    new_winner_instance_id: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "station": self.station,
            "climate_day": self.climate_day,
            "strategy": self.strategy,
            "lag_minutes": self.lag_minutes,
            "replayed_tape_instance_id": self.replayed_tape_instance_id,
            "new_verdict": self.new_verdict,
            "new_winner_instance_id": self.new_winner_instance_id,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> DriftRecord:
        return cls(
            schema_version=payload["schema_version"],  # type: ignore[arg-type]
            station=payload["station"],  # type: ignore[arg-type]
            climate_day=payload["climate_day"],  # type: ignore[arg-type]
            strategy=payload["strategy"],  # type: ignore[arg-type]
            lag_minutes=payload["lag_minutes"],  # type: ignore[arg-type]
            replayed_tape_instance_id=payload["replayed_tape_instance_id"],  # type: ignore[arg-type]
            new_verdict=payload["new_verdict"],  # type: ignore[arg-type]
            new_winner_instance_id=payload["new_winner_instance_id"],  # type: ignore[arg-type]
        )

    @property
    def key(self) -> tuple[str, str, str, int]:
        return (self.station, self.climate_day, self.strategy, self.lag_minutes)


def compute_drift(
    *,
    replayed: Sequence[ReplayResult],
    census_by_station_day: Mapping[tuple[str, str], ReplaySufficiency],
) -> tuple[DriftRecord, ...]:
    """R4: for every TERMINAL replay result, compare its recorded
    `tape_instance_id` against the CURRENT census row for the same
    `(station, climate_day)`. Drifted iff that row is missing, no longer
    `SUFFICIENT`, or names a different winner. Sorted for a deterministic,
    byte-comparable file (mirrors `write_replay_sufficiency`)."""
    drifted: list[DriftRecord] = []
    for result in replayed:
        if result.outcome not in ("COMPLETED", "RECOVERED"):
            continue
        station_day = (result.station, result.climate_day)
        current = census_by_station_day.get(station_day)
        if current is None:
            drifted.append(
                DriftRecord(
                    schema_version=REPLAY_DRIFT_SCHEMA_VERSION,
                    station=result.station,
                    climate_day=result.climate_day,
                    strategy=result.strategy,
                    lag_minutes=result.lag_minutes,
                    replayed_tape_instance_id=result.tape_instance_id or "",
                    new_verdict="MISSING",
                    new_winner_instance_id=None,
                )
            )
            continue
        if current.verdict != "SUFFICIENT" or current.winner_instance_id != result.tape_instance_id:
            drifted.append(
                DriftRecord(
                    schema_version=REPLAY_DRIFT_SCHEMA_VERSION,
                    station=result.station,
                    climate_day=result.climate_day,
                    strategy=result.strategy,
                    lag_minutes=result.lag_minutes,
                    replayed_tape_instance_id=result.tape_instance_id or "",
                    new_verdict=current.verdict,
                    new_winner_instance_id=current.winner_instance_id,
                )
            )
    return tuple(
        sorted(drifted, key=lambda d: (d.station, d.climate_day, d.strategy, d.lag_minutes))
    )


def write_replay_drift(path: Path, records: Sequence[DriftRecord]) -> None:
    """Atomic whole-file rewrite -- a derived VIEW, recomputed every run,
    exactly like `write_replay_sufficiency`."""
    ordered = sorted(records, key=lambda d: (d.station, d.climate_day, d.strategy, d.lag_minutes))
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            for record in ordered:
                handle.write(json.dumps(record.to_dict(), sort_keys=True))
                handle.write("\n")
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def read_replay_drift(path: Path) -> tuple[DriftRecord, ...]:
    if not path.exists():
        return ()
    records: list[DriftRecord] = []
    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if line:
                records.append(DriftRecord.from_dict(json.loads(line)))
    return tuple(records)


def emit_new_drift_alerts(
    *, previous: Sequence[DriftRecord], current: Sequence[DriftRecord], sink: AlertSink
) -> None:
    """One `BREEZY_REPLAY_PROVENANCE_DRIFT` alert per key NEW to the drift
    set (durable dedupe = the previous file, R4). A raising sink never
    changes the caller's exit code -- `emit_alert` already contains it."""
    previous_keys = {record.key for record in previous}
    for record in current:
        if record.key in previous_keys:
            continue
        detail = (
            f"{record.station} {record.climate_day}: winner "
            f"{record.replayed_tape_instance_id} -> verdict={record.new_verdict} "
            f"winner={record.new_winner_instance_id}"
        )
        emit_alert(
            sink,
            AlertPayload(
                severity="warning",
                event="BREEZY_REPLAY_PROVENANCE_DRIFT",
                site=record.station,
                detail=detail,
            ),
        )


# ---------------------------------------------------------------------------
# R1: target selection
# ---------------------------------------------------------------------------


def select_target(
    *,
    rows: Sequence[ReplaySufficiency],
    replayed: Sequence[ReplayResult],
    drift: Sequence[DriftRecord],
    strategy: str = DEFAULT_STRATEGY,
    lag_minutes: int = DEFAULT_LAG_MINUTES,
) -> ReplaySufficiency | None:
    """The oldest eligible `(station, climate_day)`, tie-broken by
    `SUPPORTED_STATIONS` order (base plan §6b.3; AUD-09b amendment R1).

    Eligible: `is_replayable_whole_day(row)` -- never bare
    `verdict == "SUFFICIENT"` (a Stage B `FRAGMENT` or
    `window_complete=False` winner is real but partial, §5) -- AND
    `live_instance_count == 0`, AND `station in SUPPORTED_STATIONS` (the
    census also emits candidate/NYC rows the queue must never take, H1),
    AND no TERMINAL result row under the full key, AND the key is not in
    the drift set (a drifted key is never re-replayed, R4).
    """
    done = terminal_keys(replayed)
    drifted_keys = {d.key for d in drift}
    eligible = [
        row
        for row in rows
        if is_replayable_whole_day(row)
        and row.live_instance_count == 0
        and row.station in SUPPORTED_STATIONS
        and (row.station, row.climate_day, strategy, lag_minutes) not in done
        and (row.station, row.climate_day, strategy, lag_minutes) not in drifted_keys
    ]
    if not eligible:
        return None
    station_rank = {station: index for index, station in enumerate(SUPPORTED_STATIONS)}
    eligible.sort(key=lambda row: (row.climate_day, station_rank[row.station]))
    return eligible[0]


# ---------------------------------------------------------------------------
# record_blocked
# ---------------------------------------------------------------------------


def _now_ts() -> str:
    return dt.datetime.now(dt.UTC).isoformat()


def record_blocked(
    *,
    results_path: Path,
    station: str,
    climate_day: str,
    strategy: str,
    lag_minutes: int,
    blocked_reason: str,
    sufficiency_reason: str = "",
    census_schema_version: int | None = None,
    sink: AlertSink | None = None,
    now_ts: Callable[[], str] = _now_ts,
) -> None:
    """Append one `outcome="BLOCKED"` row (day stays queued, exit 0 at the
    call site) and escalate via B19's stall rule."""
    row = ReplayResult(
        schema_version=REPLAY_RESULTS_SCHEMA_VERSION,
        run_ts=now_ts(),
        station=station,
        climate_day=climate_day,
        strategy=strategy,
        lag_minutes=lag_minutes,
        outcome="BLOCKED",
        validity=REPLAY_VALIDITY,
        blocked_reason=blocked_reason,
        exception_type=None,
        family_id=None,
        manifest_sha256=None,
        manifest_taker_fee_coefficient=None,
        engine_required_fee_coefficient=None,
        engine_params_source=None,
        params_match=None,
        composition_kind=None,
        tape_instance_id=None,
        sufficiency_reason=sufficiency_reason,
        trials=0,
        fills=0,
        fill_price_vs_decision_ask=(),
        refusal_counts={},
        wall_s=None,
        peak_rss_bytes=None,
        parquet_sha256=None,
        window_complete=None,
        replayed_first_ns=None,
        replayed_last_ns=None,
        census_schema_version=census_schema_version,
    )
    append_replay_result(results_path, row)
    results = read_replay_results(results_path)
    run_length = stall_run_length(results, blocked_reason=blocked_reason)
    if run_length == STALL_ALERT_RUN_LENGTH:
        active_sink = sink if sink is not None else resolve_alert_sink(os.environ)
        emit_alert(
            active_sink,
            AlertPayload(
                severity="warning",
                event="BREEZY_REPLAY_STALLED",
                site=station,
                detail=(
                    f"{run_length} consecutive BLOCKED replays reason={blocked_reason}; "
                    "widen asos_recent_refresh.py --since or target a recent climate day"
                ),
            ),
        )


def stall_run_length(results: Sequence[ReplayResult], *, blocked_reason: str) -> int:
    """Length of the trailing run of `BLOCKED` rows sharing `blocked_reason`
    (B19). Any other outcome, or a different `blocked_reason`, ends the run."""
    run = 0
    for row in reversed(results):
        if row.outcome == "BLOCKED" and row.blocked_reason == blocked_reason:
            run += 1
        else:
            break
    return run


# ---------------------------------------------------------------------------
# Subprocess argument vectors (B17)
# ---------------------------------------------------------------------------

SubprocessRunner = Callable[[Sequence[str]], "subprocess.CompletedProcess[str]"]


def build_asos_argv(
    *, python_executable: str, station: str, climate_day: str, out_path: Path
) -> list[str]:
    return [
        python_executable,
        str(_SCRIPTS_DIR / "asos_cache_csv.py"),
        "--station",
        station,
        "--climate-day",
        climate_day,
        "--out",
        str(out_path),
    ]


_SCRIPTS_DIR: Final[Path] = Path(__file__).resolve().parent


def build_driver_argv(
    *,
    python_executable: str,
    station: str,
    climate_day: str,
    tape_instance_id: str,
    quote_catalog: Path,
    work_catalog: Path,
    asos_cache_csv: Path,
    weather_catalog_root: Path,
    output_dir: Path,
    family_manifest_path: Path,
    strategy: str = DEFAULT_STRATEGY,
    lag_minutes: int = DEFAULT_LAG_MINUTES,
) -> list[str]:
    """The complete argument vector for
    `current_rung_hold_paper_replay.py` -- every `required=True` argument
    of that parser is present (B17; `test_replay_daily_runner.py` asserts
    this set against the driver's own source)."""
    return [
        python_executable,
        str(_SCRIPTS_DIR / "current_rung_hold_paper_replay.py"),
        "--strategy",
        strategy,
        "--station",
        station,
        "--climate-day",
        climate_day,
        "--tape-instance-id",
        tape_instance_id,
        "--lag-minutes",
        str(lag_minutes),
        "--quote-catalog",
        str(quote_catalog),
        "--work-catalog",
        str(work_catalog),
        "--asos-cache-csv",
        str(asos_cache_csv),
        "--weather-catalog-root",
        str(weather_catalog_root),
        "--output-dir",
        str(output_dir),
        "--family-manifest",
        str(family_manifest_path),
    ]


def classify_driver_failure(
    *, returncode: int, stderr: str
) -> tuple[Literal["BLOCKED", "FAILED"], str]:
    """A non-zero driver exit is `BLOCKED` only for the two well-known
    family-manifest refusal codes (should not occur in practice -- the
    runner resolves and validates the manifest before invoking the driver
    -- but classified rather than silently mis-filed as a crash);
    everything else is `FAILED`, with the exception type parsed from the
    LAST `...Error` name in stderr (a driver crash prints an uncaught
    Python traceback -- base plan §9's `NoDecisionWindowCoverageError` /
    `EntryAskFromLatchMissingError` / `ImpossibleFillPriceError` cases)."""
    if returncode == _EXIT_FAMILY_MANIFEST_REFUSED:
        return "BLOCKED", "FAMILY_MANIFEST_REFUSED"
    if returncode == _EXIT_FAMILY_MANIFEST_UNUSABLE:
        return "BLOCKED", "FAMILY_MANIFEST_UNUSABLE"
    matches = _EXCEPTION_NAME_RE.findall(stderr)
    exception_type = matches[-1] if matches else "UnknownDriverFailure"
    return "FAILED", exception_type


def classify_asos_failure(*, returncode: int) -> str:
    """`asos_cache_csv.py`'s own exit-code table (module docstring there):
    2 -> `ASOS_CACHE_EMPTY`, 3 -> unparseable rows. Anything else is a
    generic producer failure, never silently treated as `ASOS_CACHE_EMPTY`."""
    if returncode == 2:
        return "ASOS_CACHE_EMPTY"
    if returncode == 3:
        return "ASOS_CACHE_UNPARSEABLE_ROWS"
    return "ASOS_PRODUCER_FAILED"


_STRATEGY_REFUSALS_RE: Final[re.Pattern[str]] = re.compile(
    r"^strategy refusals: (\{.*\})\s*$", re.MULTILINE
)


def _parse_strategy_refusals(stdout: str) -> dict[str, int]:
    """Parse the driver's own `"strategy refusals: {...}"` line
    (`current_rung_hold_paper_replay.py`'s `main`, sorted dict repr). Never
    raises: an unparseable or absent line yields an empty histogram rather
    than failing a otherwise-successful replay."""
    match = _STRATEGY_REFUSALS_RE.search(stdout)
    if match is None:
        return {}
    try:
        import ast

        parsed = ast.literal_eval(match.group(1))
    except (ValueError, SyntaxError):
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {str(k): int(v) for k, v in parsed.items() if isinstance(v, int)}


def _format_lst(ns: int | None, *, std_utc_offset_hours: float) -> str:
    if ns is None:
        return "?"
    moment = dt.datetime.fromtimestamp(ns / 1e9, tz=standard_time_zone(std_utc_offset_hours))
    return moment.strftime("%H:%M")


def _default_run_subprocess(argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(argv), capture_output=True, text=True, check=False, shell=False,
    )


def _default_work_dir() -> Path:
    return Path(tempfile.mkdtemp(prefix="breezy-replay-daily-"))


@dataclass(frozen=True, slots=True, kw_only=True)
class RunConfig:
    """Everything one invocation needs -- deliberately explicit (never
    read from the environment inside this module; the wrapper resolves
    every path, B18)."""

    replay_sufficiency_path: Path
    replay_results_path: Path
    replay_drift_path: Path
    quote_catalog: Path
    weather_catalog_root: Path
    family_manifest_path: Path
    output_root: Path
    python_executable: str
    strategy: str = DEFAULT_STRATEGY
    lag_minutes: int = DEFAULT_LAG_MINUTES


def _output_dir_for(config: RunConfig, *, station: str, climate_day: str) -> Path:
    return (
        config.output_root
        / "paper_replay" / "scored_trials" / "v3" / station / climate_day
        / f"lag_{config.lag_minutes}"
    )


def _append_terminal(
    config: RunConfig,
    target: ReplaySufficiency,
    *,
    now_ts: Callable[[], str],
    outcome: Literal["COMPLETED", "RECOVERED", "FAILED"],
    exception_type: str | None = None,
    parquet_sha256: str | None = None,
    family_id: str | None = None,
    manifest_sha256: str | None = None,
    manifest_taker_fee_coefficient: str | None = None,
    engine_required_fee_coefficient: str | None = None,
    engine_params_source: str | None = None,
    params_match: bool | None = None,
    composition_kind: str | None = None,
    trials: int = 0,
    fills: int = 0,
    fill_price_vs_decision_ask: tuple[str, ...] = (),
    refusal_counts: Mapping[str, int] | None = None,
    wall_s: float | None = None,
    peak_rss_bytes: int | None = None,
) -> None:
    row = ReplayResult(
        schema_version=REPLAY_RESULTS_SCHEMA_VERSION,
        run_ts=now_ts(),
        station=target.station,
        climate_day=target.climate_day,
        strategy=config.strategy,
        lag_minutes=config.lag_minutes,
        outcome=outcome,
        validity=REPLAY_VALIDITY,
        blocked_reason=None,
        exception_type=exception_type,
        family_id=family_id,
        manifest_sha256=manifest_sha256,
        manifest_taker_fee_coefficient=manifest_taker_fee_coefficient,
        engine_required_fee_coefficient=engine_required_fee_coefficient,
        engine_params_source=engine_params_source,
        params_match=params_match,
        composition_kind=composition_kind,
        tape_instance_id=target.winner_instance_id,
        sufficiency_reason=target.reason,
        trials=trials,
        fills=fills,
        fill_price_vs_decision_ask=fill_price_vs_decision_ask,
        refusal_counts=dict(refusal_counts or {}),
        wall_s=wall_s,
        peak_rss_bytes=peak_rss_bytes,
        parquet_sha256=parquet_sha256,
        window_complete=target.window_complete,
        replayed_first_ns=target.winner_first_in_window_ns,
        replayed_last_ns=target.winner_last_in_window_ns,
        census_schema_version=target.schema_version,
    )
    append_replay_result(config.replay_results_path, row)


def run_once(
    config: RunConfig,
    *,
    run_subprocess: SubprocessRunner = _default_run_subprocess,
    sink: AlertSink | None = None,
    now_ts: Callable[[], str] = _now_ts,
    work_dir_factory: Callable[[], Path] = _default_work_dir,
    std_utc_offset_hours_for: Callable[[str], float] | None = None,
) -> int:
    """The whole nightly decision, end to end. Returns the process exit
    code (never raises for an expected outcome -- BLOCKED/FAILED/EMPTY are
    all ordinary returns; H0/H3 corruption is the one thing that
    propagates as a loud non-zero exit, never a silent empty queue)."""
    active_sink = sink if sink is not None else resolve_alert_sink(os.environ)

    try:
        rows = read_replay_sufficiency(config.replay_sufficiency_path)
    except OSError as exc:
        print(f"replay_daily_runner: cannot read replay_sufficiency.jsonl: {exc}", file=sys.stderr)
        return 1
    except (UnknownReplaySufficiencySchemaError, DuplicateReplaySufficiencyRecordError) as exc:
        print(f"replay_daily_runner: refused: {exc}", file=sys.stderr)
        return 1

    if config.replay_results_path.exists():
        try:
            existing_results = read_replay_results(config.replay_results_path)
        except (UnknownReplayResultSchemaError, DuplicateReplayResultError) as exc:
            print(f"replay_daily_runner: refused: {exc}", file=sys.stderr)
            return 1
    else:
        existing_results = ()

    census_by_station_day = {(row.station, row.climate_day): row for row in rows}
    previous_drift = read_replay_drift(config.replay_drift_path)
    current_drift = compute_drift(
        replayed=existing_results, census_by_station_day=census_by_station_day,
    )
    write_replay_drift(config.replay_drift_path, current_drift)
    emit_new_drift_alerts(previous=previous_drift, current=current_drift, sink=active_sink)

    target = select_target(
        rows=rows,
        replayed=existing_results,
        drift=current_drift,
        strategy=config.strategy,
        lag_minutes=config.lag_minutes,
    )
    if target is None:
        sufficient_count = sum(1 for row in rows if row.verdict == "SUFFICIENT")
        if sufficient_count == 0:
            histogram = dict(
                sorted(Counter(row.reason for row in rows if row.verdict == "INSUFFICIENT").items())
            )
            print(f"EVERY DAY INSUFFICIENT -- {histogram}")
        else:
            print(
                f"QUEUE EMPTY -- {sufficient_count} SUFFICIENT day(s), all replayed under "
                "key (station, climate_day, strategy, lag)"
            )
        return 0

    station, climate_day = target.station, target.climate_day
    output_dir = _output_dir_for(config, station=station, climate_day=climate_day)

    if output_dir.exists():
        parquet_files = sorted(output_dir.glob("scored_trials_*.parquet"))
        if parquet_files:
            latest = parquet_files[-1]
            try:
                digest = hashlib.sha256(latest.read_bytes()).hexdigest()
            except OSError as exc:
                _append_terminal(
                    config, target, now_ts=now_ts, outcome="FAILED",
                    exception_type=type(exc).__name__,
                )
                print(
                    f"FAILED {station} {climate_day} -- unreadable parquet {latest}",
                    file=sys.stderr,
                )
                return 1
            _append_terminal(
                config, target, now_ts=now_ts, outcome="RECOVERED", parquet_sha256=digest,
            )
            print(f"RECOVERED {station} {climate_day} -- {latest.name}")
            return 0

    work_dir = work_dir_factory()
    asos_csv = work_dir / f"asos_{station}_{climate_day}.csv"
    asos_result = run_subprocess(
        build_asos_argv(
            python_executable=config.python_executable,
            station=station, climate_day=climate_day, out_path=asos_csv,
        )
    )
    if asos_result.returncode != 0:
        reason = classify_asos_failure(returncode=asos_result.returncode)
        record_blocked(
            results_path=config.replay_results_path, station=station, climate_day=climate_day,
            strategy=config.strategy, lag_minutes=config.lag_minutes, blocked_reason=reason,
            sufficiency_reason=target.reason, census_schema_version=target.schema_version,
            sink=active_sink, now_ts=now_ts,
        )
        print(f"BLOCKED {station} {climate_day} -- {reason}")
        return 0

    work_catalog = work_dir / "work_catalog"
    started = time.monotonic()
    rss_before = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    driver_result = run_subprocess(
        build_driver_argv(
            python_executable=config.python_executable,
            station=station, climate_day=climate_day,
            tape_instance_id=target.winner_instance_id or "",
            quote_catalog=config.quote_catalog, work_catalog=work_catalog,
            asos_cache_csv=asos_csv, weather_catalog_root=config.weather_catalog_root,
            output_dir=output_dir, family_manifest_path=config.family_manifest_path,
            strategy=config.strategy, lag_minutes=config.lag_minutes,
        )
    )
    wall_s = time.monotonic() - started
    rss_after = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    peak_rss_bytes = max(0, (rss_after - rss_before)) * 1024

    if driver_result.returncode != 0:
        outcome, reason = classify_driver_failure(
            returncode=driver_result.returncode, stderr=driver_result.stderr or "",
        )
        if outcome == "BLOCKED":
            record_blocked(
                results_path=config.replay_results_path, station=station, climate_day=climate_day,
                strategy=config.strategy, lag_minutes=config.lag_minutes, blocked_reason=reason,
                sufficiency_reason=target.reason, census_schema_version=target.schema_version,
                sink=active_sink, now_ts=now_ts,
            )
            print(f"BLOCKED {station} {climate_day} -- {reason}")
            return 0
        _append_terminal(
            config, target, now_ts=now_ts, outcome="FAILED", exception_type=reason,
            wall_s=wall_s, peak_rss_bytes=peak_rss_bytes,
        )
        print(f"FAILED {station} {climate_day} -- {reason}", file=sys.stderr)
        return 1

    sidecar_path = output_dir / "family_params.json"
    sidecar: dict[str, object] = {}
    if sidecar_path.exists():
        sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    scored = read_scored_trials(output_dir)
    fill_price_vs_decision_ask = tuple(str(trial.slippage) for trial in scored)
    refusal_counts = _parse_strategy_refusals(driver_result.stdout or "")
    parquet_files = sorted(output_dir.glob("scored_trials_*.parquet"))
    parquet_sha256 = (
        hashlib.sha256(parquet_files[-1].read_bytes()).hexdigest() if parquet_files else None
    )

    manifest_taker_fee_coefficient = sidecar.get("manifest_taker_fee_coefficient")
    engine_required_fee_coefficient = sidecar.get("engine_required_fee_coefficient")
    _append_terminal(
        config, target, now_ts=now_ts, outcome="COMPLETED",
        family_id=sidecar.get("family_id"),  # type: ignore[arg-type]
        manifest_sha256=sidecar.get("manifest_sha256"),  # type: ignore[arg-type]
        manifest_taker_fee_coefficient=manifest_taker_fee_coefficient,  # type: ignore[arg-type]
        engine_required_fee_coefficient=engine_required_fee_coefficient,  # type: ignore[arg-type]
        engine_params_source=sidecar.get("engine_params_source"),  # type: ignore[arg-type]
        params_match=sidecar.get("params_match"),  # type: ignore[arg-type]
        composition_kind=sidecar.get("composition_kind"),  # type: ignore[arg-type]
        trials=len(scored),
        fills=len(scored),
        fill_price_vs_decision_ask=fill_price_vs_decision_ask,
        refusal_counts=refusal_counts,
        wall_s=wall_s,
        peak_rss_bytes=peak_rss_bytes,
        parquet_sha256=parquet_sha256,
    )
    if std_utc_offset_hours_for is not None:
        offset = std_utc_offset_hours_for(station)
        interval = (
            f"[{_format_lst(target.winner_first_in_window_ns, std_utc_offset_hours=offset)}, "
            f"{_format_lst(target.winner_last_in_window_ns, std_utc_offset_hours=offset)}) LST"
        )
    else:
        interval = "[?, ?) LST"
    print(
        f"COMPLETED {station} {climate_day} -- trials={len(scored)} fills={len(scored)} "
        f"replayed {interval} of [12:00, 17:00); window_complete={target.window_complete} "
        f"coverage_kind={target.coverage_kind}"
    )
    return 0


def _resolve_std_utc_offset_hours(station: str) -> float:
    from breezy.registry.sites import default_registry

    return default_registry().climate_day_window(WEATHER_VENUE, station).std_utc_offset_hours


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replay-sufficiency", type=Path, default=DEFAULT_REPLAY_SUFFICIENCY_PATH)
    parser.add_argument("--replay-results", type=Path, default=DEFAULT_REPLAY_RESULTS_PATH)
    parser.add_argument("--replay-drift", type=Path, default=DEFAULT_REPLAY_DRIFT_PATH)
    parser.add_argument("--quote-catalog", type=Path, required=True)
    parser.add_argument("--weather-catalog-root", type=Path, required=True)
    parser.add_argument("--family-manifest", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument(
        "--python", dest="python_executable", type=str, default=sys.executable,
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    config = RunConfig(
        replay_sufficiency_path=args.replay_sufficiency,
        replay_results_path=args.replay_results,
        replay_drift_path=args.replay_drift,
        quote_catalog=args.quote_catalog,
        weather_catalog_root=args.weather_catalog_root,
        family_manifest_path=args.family_manifest,
        output_root=args.output_root,
        python_executable=args.python_executable,
    )
    return run_once(config, std_utc_offset_hours_for=_resolve_std_utc_offset_hours)


if __name__ == "__main__":
    raise SystemExit(main())
