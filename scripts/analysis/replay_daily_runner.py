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
when the flag did not exist). The sidecar is accepted only when its
`argv_sha256` equals `argv_digest.argv_sha256` over the argument vector
this runner actually passed (arguments after the script path, the same
slice the driver hashes). A missing file or a mismatched digest is
`BLOCKED` and the day stays queued. B16/B20 are satisfied more strongly
this way: `params_match` reflects the ENGINE's own readback, not an
inference.

**AUD-09b fee-regime plan, Phase 1.** A day the engine ever refuses on
`fee_schedule_mismatch` is recorded `BLOCKED`, never `COMPLETED`, its output
directory quarantined (never deleted), and the key durably excluded from
re-selection under the SAME armed family's theta (`fee_void_keys`) --
closing the gap where a pre-drift day looped as a meaningless
`COMPLETED trials=0` forever.

**AUD-09b fee-regime plan, Phase 2.** `select_target` also takes an
optional `fee_coefficient_as_of` callable so a real run can PRE-select only
station-days the dated schedule
(`breezy.adapters.polymarket_us.fees.taker_fee_coefficient_as_of`) pins to
the armed family's own theta -- the vast majority of the fix, since net
(1) alone would still waste a full engine run on every pre-drift day
before ever reaching one Phase 1 could catch. `main` imports that function
lazily (inside itself, not at module level) so a caller that never runs a
real replay -- every test in this suite -- never pays for pulling in
`nautilus_trader`'s Cython `FeeModel` at import time.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import resource
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Final, Literal

sys.path.insert(0, str(Path(__file__).resolve().parent))

from argv_digest import argv_sha256
from hypothesis_register import ARCHIVE_RECAL_RULING_DATE

from breezy.analysis.replay_results import (
    FEE_SCHEDULE_MISMATCH_REFUSAL,
    REPLAY_RESULTS_SCHEMA_VERSION,
    REPLAY_VALIDITY,
    DuplicateReplayResultError,
    ReplayResult,
    ResultKey,
    UnknownReplayResultSchemaError,
    append_replay_result,
    is_fee_schedule_void,
    read_replay_results,
    result_key,
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
from breezy.persistence.family_manifest import FamilyManifestError, load_family_manifest
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
    "DEFAULT_REPLAY_BATCH_RESERVE_S",
    "DEFAULT_REPLAY_DRIFT_PATH",
    "DEFAULT_REPLAY_RESULTS_PATH",
    "DEFAULT_REPLAY_SUFFICIENCY_PATH",
    "DEFAULT_SKIP_STATE_PATH",
    "DEFAULT_STRATEGY",
    "FREEZE_CLIMATE_DAY",
    "REPLAY_DRIFT_SCHEMA_VERSION",
    "REPLAY_TARGET_RSS_WARN_BYTES",
    "STALL_ALERT_RUN_LENGTH",
    "WEATHER_VENUE",
    "DriftRecord",
    "LegacyFeeVoidQuarantineResult",
    "RunConfig",
    "SkipReason",
    "SubprocessRunner",
    "UnsupportedCompositionKindError",
    "build_asos_argv",
    "build_driver_argv",
    "classify_asos_failure",
    "classify_driver_failure",
    "compute_drift",
    "fee_regime_excluded_count",
    "fee_void_keys",
    "main",
    "quarantine_legacy_fee_void",
    "read_replay_drift",
    "read_skip_state",
    "record_blocked",
    "record_skip",
    "reset_skip_state",
    "resolve_strategy_from_manifest",
    "run_batch",
    "run_once",
    "select_target",
    "stall_run_length",
    "write_replay_drift",
]

#: Same literal every replay driver/census script uses
#: (`run_weather_strategy_backtests.py:352`).
WEATHER_VENUE: Final[str] = "polymarket_us"

#: R3-VIABILITY r2 delta "R3V-b" item 2: sourced from the hypothesis
#: register's own freeze record for H-ARCHIVE-RECAL-2026-09
#: (`ARCHIVE_RECAL_RULING_DATE`, `hypothesis_register.py:207`) -- the
#: record that OWNS the 2026-09-25 tape freeze
#: (`EDGE-4_DISPOSITION_2026-09-27.md:6,19`), never a new literal. Never
#: `NO_SIDE_RULING_DATE`: that is a DIFFERENT hypothesis's ruling date that
#: happens to equal the same day today (CRITICAL fix, code review
#: 2026-09-28). A row with `climate_day == FREEZE_CLIMATE_DAY` counts as
#: pre-freeze; the COMPLETED log line below withholds `trials=`/`fills=`
#: only strictly AFTER it. `r3_viability.py` imports this same constant for
#: its own firewall.
FREEZE_CLIMATE_DAY: Final[str] = ARCHIVE_RECAL_RULING_DATE

DEFAULT_STRATEGY: Final[str] = "continuous_rung_hold"
#: Matches the base plan's own literal command block (§6b.3).
DEFAULT_LAG_MINUTES: Final[int] = 30
AUD11_AND_AUD12_LANDED: Final[bool] = False

#: R3V-a (R3-VIABILITY plan r2 delta): the batch loop stops offering new
#: targets once `budget_s - elapsed <= DEFAULT_REPLAY_BATCH_RESERVE_S` --
#: r1 plan §2's "240 s reserve" for `promotion_proposal.py` and the
#: wrapper's own tail (log flush, lock release).
DEFAULT_REPLAY_BATCH_RESERVE_S: Final[float] = 240.0
#: R3V-a item 4: a single target's own driver child exceeding this triggers
#: one `BREEZY_REPLAY_TARGET_RSS_HIGH` warning -- never a batch-stopping
#: failure, since the unit's own `MemoryHigh=3G`/`MemoryMax=4G`
#: (`breezy-replay-daily.service:32-35`) is the actual enforcement.
REPLAY_TARGET_RSS_WARN_BYTES: Final[int] = 2 * 1024**3

_DERIVED_ROOT: Final[Path] = Path.home() / ".local/share/breezy/derived"
DEFAULT_REPLAY_SUFFICIENCY_PATH: Final[Path] = (
    _DERIVED_ROOT / "replay" / "replay_sufficiency.jsonl"
)
DEFAULT_REPLAY_RESULTS_PATH: Final[Path] = _DERIVED_ROOT / "replay" / "replay_results.jsonl"
DEFAULT_REPLAY_DRIFT_PATH: Final[Path] = _DERIVED_ROOT / "replay" / "replay_drift.jsonl"
#: Review fix 3 (HIGH): a small, non-JSONL state file the WRAPPER's own
#: skip paths (lock contention, no armed family) report through -- never
#: parsed by the wrapper itself (B18: no JSONL parsing in the wrapper), so
#: this is deliberately plain text, not a `replay_results.jsonl` row.
DEFAULT_SKIP_STATE_PATH: Final[Path] = _DERIVED_ROOT / "replay" / "wrapper_skip_state"

#: The wrapper's two benign-skip reasons (review fix 3). Distinct from
#: `blocked_reason` (a REPLAY attempt that started and was refused) --
#: these mean the wrapper never even reached `run_once`.
SkipReason = Literal["LOCK_CONTENTION", "NO_ARMED_FAMILY"]

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
#: AUD-09b fee-regime plan, Phase 3: the driver's own exact preflight
#: refusal -- a tape instrument's theta disagrees with the armed family's.
#: Must equal `current_rung_hold_paper_replay.EXIT_FEE_SCHEDULE_MISMATCH`
#: (pinned by `test_fee_schedule_mismatch_exit_code_matches_the_drivers_
#: own_constant`).
_EXIT_FEE_SCHEDULE_MISMATCH: Final[int] = 4

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


def fee_void_keys(
    replayed: Sequence[ReplayResult], required_fee_coefficient: Decimal | None,
) -> frozenset[ResultKey]:
    """AC2: every queue key carrying a row `is_fee_schedule_void` whose OWN
    `manifest_taker_fee_coefficient` equals `required_fee_coefficient` --
    compared as `Decimal`, never as raw strings, so `"0.0700"` and
    `Decimal("0.07")` are the SAME theta. A key voided under a DIFFERENT
    family's theta is not excluded here: re-arming a different family must
    be free to re-replay a day another family's fee regime poisoned.

    `required_fee_coefficient is None` (no armed family resolved theta)
    excludes nothing -- every pre-existing caller that never passes this
    kwarg keeps yesterday's behaviour byte-for-byte."""
    if required_fee_coefficient is None:
        return frozenset()
    excluded: set[ResultKey] = set()
    for row in replayed:
        if not is_fee_schedule_void(row):
            continue
        if row.manifest_taker_fee_coefficient is None:
            continue
        if Decimal(row.manifest_taker_fee_coefficient) != required_fee_coefficient:
            continue
        excluded.add(result_key(row))
    return frozenset(excluded)


def _pre_fee_eligible_rows(
    *,
    rows: Sequence[ReplaySufficiency],
    replayed: Sequence[ReplayResult],
    drift: Sequence[DriftRecord],
    strategy: str,
    lag_minutes: int,
    required_fee_coefficient: Decimal | None,
    exclude: frozenset[ResultKey] = frozenset(),
) -> list[ReplaySufficiency]:
    """Every AUD-09b amendment R1 predicate, PLUS AC2's durable fee-void
    exclusion. Factored out so a future consumer of "otherwise eligible"
    (e.g. a fee-regime exclusion count) shares this exact definition rather
    than re-deriving it.

    `exclude` (R3V-a) is keys `run_batch` already TRIED earlier in the same
    batch -- regardless of outcome, including `BLOCKED` (which is not
    terminal). Fixes the batch-mode head-of-line problem: a persistently
    BLOCKED day no longer stalls every remaining target this batch.
    Defaults to empty, so every pre-existing caller (never passing this
    kwarg) selects byte-identically to before this plan."""
    done = terminal_keys(replayed)
    drifted_keys = {d.key for d in drift}
    fee_blocked_keys = fee_void_keys(replayed, required_fee_coefficient)
    return [
        row
        for row in rows
        if is_replayable_whole_day(row)
        and row.live_instance_count == 0
        and row.station in SUPPORTED_STATIONS
        and (row.station, row.climate_day, strategy, lag_minutes) not in done
        and (row.station, row.climate_day, strategy, lag_minutes) not in drifted_keys
        and (row.station, row.climate_day, strategy, lag_minutes) not in fee_blocked_keys
        and (row.station, row.climate_day, strategy, lag_minutes) not in exclude
    ]


def _fee_regime_eligible(
    row: ReplaySufficiency,
    *,
    required_fee_coefficient: Decimal | None,
    fee_coefficient_as_of: Callable[[int], Decimal | None] | None,
) -> bool:
    """AC3: `row` is eligible only when the DATED schedule
    (`fee_coefficient_as_of`) pins the SAME theta at BOTH the row's own
    `window_start_ns` and `window_end_ns` -- `None` at either edge (the
    AMBIGUOUS window, or before the earliest pinned date) fails closed.

    `fee_coefficient_as_of is None` or `required_fee_coefficient is None`
    admits every row: Phase 2 is opt-in via these two kwargs, so a caller
    that never passes them (every pre-existing test) keeps the date-blind
    behaviour byte-for-byte."""
    if fee_coefficient_as_of is None or required_fee_coefficient is None:
        return True
    start = fee_coefficient_as_of(row.window_start_ns)
    end = fee_coefficient_as_of(row.window_end_ns)
    return start == required_fee_coefficient and end == required_fee_coefficient


def select_target(
    *,
    rows: Sequence[ReplaySufficiency],
    replayed: Sequence[ReplayResult],
    drift: Sequence[DriftRecord],
    strategy: str = DEFAULT_STRATEGY,
    lag_minutes: int = DEFAULT_LAG_MINUTES,
    required_fee_coefficient: Decimal | None = None,
    fee_coefficient_as_of: Callable[[int], Decimal | None] | None = None,
    exclude: frozenset[ResultKey] = frozenset(),
) -> ReplaySufficiency | None:
    """The oldest eligible `(station, climate_day)`, tie-broken by
    `SUPPORTED_STATIONS` order (base plan §6b.3; AUD-09b amendment R1).

    Eligible: `is_replayable_whole_day(row)` -- never bare
    `verdict == "SUFFICIENT"` (a Stage B `FRAGMENT` or
    `window_complete=False` winner is real but partial, §5) -- AND
    `live_instance_count == 0`, AND `station in SUPPORTED_STATIONS` (the
    census also emits candidate/NYC rows the queue must never take, H1),
    AND no TERMINAL result row under the full key, AND the key is not in
    the drift set (a drifted key is never re-replayed, R4), AND the key
    carries no durable `FEE_SCHEDULE_MISMATCH` void under THIS theta (AC2),
    AND (Phase 2, opt-in) the dated fee schedule pins THIS theta across the
    row's own decision window (AC3).
    """
    pre_fee_eligible = _pre_fee_eligible_rows(
        rows=rows, replayed=replayed, drift=drift, strategy=strategy, lag_minutes=lag_minutes,
        required_fee_coefficient=required_fee_coefficient, exclude=exclude,
    )
    eligible = [
        row
        for row in pre_fee_eligible
        if _fee_regime_eligible(
            row,
            required_fee_coefficient=required_fee_coefficient,
            fee_coefficient_as_of=fee_coefficient_as_of,
        )
    ]
    if not eligible:
        return None
    station_rank = {station: index for index, station in enumerate(SUPPORTED_STATIONS)}
    eligible.sort(key=lambda row: (row.climate_day, station_rank[row.station]))
    return eligible[0]


def fee_regime_excluded_count(
    *,
    rows: Sequence[ReplaySufficiency],
    replayed: Sequence[ReplayResult],
    drift: Sequence[DriftRecord],
    strategy: str = DEFAULT_STRATEGY,
    lag_minutes: int = DEFAULT_LAG_MINUTES,
    required_fee_coefficient: Decimal | None,
    fee_coefficient_as_of: Callable[[int], Decimal | None] | None,
) -> int:
    """AC4: how many rows that pass every OTHER `select_target` predicate
    the AC3 dated-schedule check alone excludes -- the count the daily
    `FEE_REGIME_EXCLUDED n ...` line names. Zero whenever
    `fee_coefficient_as_of` is `None` (Phase 2 not wired) or
    `required_fee_coefficient` is `None` (no armed family theta)."""
    pre_fee_eligible = _pre_fee_eligible_rows(
        rows=rows, replayed=replayed, drift=drift, strategy=strategy, lag_minutes=lag_minutes,
        required_fee_coefficient=required_fee_coefficient,
    )
    return sum(
        1
        for row in pre_fee_eligible
        if not _fee_regime_eligible(
            row,
            required_fee_coefficient=required_fee_coefficient,
            fee_coefficient_as_of=fee_coefficient_as_of,
        )
    )


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
    family_id: str | None = None,
    manifest_taker_fee_coefficient: str | None = None,
    engine_required_fee_coefficient: str | None = None,
    tape_instance_id: str | None = None,
    refusal_counts: Mapping[str, int] | None = None,
    sink: AlertSink | None = None,
    now_ts: Callable[[], str] = _now_ts,
) -> None:
    """Append one `outcome="BLOCKED"` row (day stays queued, exit 0 at the
    call site) and escalate via B19's stall rule.

    `family_id`/`manifest_taker_fee_coefficient`/`engine_required_fee_
    coefficient`/`tape_instance_id`/`refusal_counts` are AUD-09b amendment
    fee-regime plan additions (Phase 1) -- keyword-only, all defaulting to
    the pre-existing hardcoded `None`/`{}` so every pre-existing call site
    writes a byte-identical row. A `FEE_SCHEDULE_MISMATCH` block needs them
    so `fee_void_keys` can compare the row's OWN theta against an armed
    family's (AC2); every other `blocked_reason` still writes them `None`.
    """
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
        family_id=family_id,
        manifest_sha256=None,
        manifest_taker_fee_coefficient=manifest_taker_fee_coefficient,
        engine_required_fee_coefficient=engine_required_fee_coefficient,
        engine_params_source=None,
        params_match=None,
        composition_kind=None,
        tape_instance_id=tape_instance_id,
        sufficiency_reason=sufficiency_reason,
        trials=0,
        fills=0,
        fill_price_vs_decision_ask=(),
        refusal_counts=dict(refusal_counts or {}),
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
    run_length = stall_run_length(results)
    # Review fix 5 (MEDIUM): fire on EVERY run once the trailing BLOCKED run
    # reaches 3, not only at the instant it first equals 3 -- a send that
    # fails (or a webhook outage) at n==3 must not silence the schedule's
    # ONLY escalation forever. The timer is daily, so this is at most one
    # alert per day; a resolved day (COMPLETED/RECOVERED/FAILED) resets the
    # run back to 0 and re-arms the next three.
    if run_length >= STALL_ALERT_RUN_LENGTH:
        active_sink = sink if sink is not None else resolve_alert_sink(os.environ)
        emit_alert(
            active_sink,
            AlertPayload(
                severity="warning",
                event="BREEZY_REPLAY_STALLED",
                site=station,
                detail=(
                    f"{run_length} consecutive BLOCKED replays reason={blocked_reason}; "
                    f"{_remediation_for(blocked_reason)}"
                ),
            ),
        )


#: Review fix 7 (MEDIUM): the remediation act implied by each closed
#: `blocked_reason`, never one hardcoded ASOS-only sentence for every
#: reason. `AlertPayload` truncates `detail` to `MAX_ALERT_DETAIL_CHARS`
#: (health.py), so each entry stays short.
_BLOCKED_REMEDIATION: Final[dict[str, str]] = {
    "ASOS_CACHE_EMPTY": (
        "widen asos_recent_refresh.py --since or target a recent climate day"
    ),
    "ASOS_CACHE_UNPARSEABLE_ROWS": "inspect the settlement-alignment ASOS cache for the station",
    "ASOS_PRODUCER_FAILED": "check asos_cache_csv.py's own stderr in the wrapper log",
    "FAMILY_MANIFEST_REFUSED": (
        "the armed manifest's composition_kind/station conflicts; re-check it"
    ),
    "FAMILY_MANIFEST_UNUSABLE": "the armed manifest is malformed or unpinned; re-check it",
    "FEE_SCHEDULE_MISMATCH": (
        "tape instrument theta != family theta; recheck FEE_SCHEDULE_PIN table vs tape"
    ),
    "FAMILY_PARAMS_SIDECAR_MISSING": (
        "driver exited 0 with no family_params.json; re-run, do not default provenance"
    ),
    "FAMILY_PARAMS_ARGV_MISMATCH": (
        "family_params.json argv_sha256 != the vector this runner passed"
    ),
    "FAMILY_PARAMS_SIDECAR_MALFORMED": (
        "family_params.json is not valid provenance; re-run, do not default provenance"
    ),
}
_DEFAULT_BLOCKED_REMEDIATION: Final[str] = "investigate the wrapper log for this reason"


def _remediation_for(blocked_reason: str) -> str:
    return _BLOCKED_REMEDIATION.get(blocked_reason, _DEFAULT_BLOCKED_REMEDIATION)


def stall_run_length(results: Sequence[ReplayResult]) -> int:
    """Length of the trailing run of `BLOCKED` rows, of ANY
    `blocked_reason` (review fix 4 -- the stall being escalated is "the
    schedule has stopped replaying", not "the schedule keeps hitting the
    identical reason"; two different reasons in a row are still two
    replays that did not happen). Any non-`BLOCKED` outcome ends the run."""
    run = 0
    for row in reversed(results):
        if row.outcome == "BLOCKED":
            run += 1
        else:
            break
    return run


# ---------------------------------------------------------------------------
# Review fix 3 (HIGH): durable wrapper-skip record + escalation (mirrors
# B19's shape, one level up -- BEFORE any replay attempt starts).
# ---------------------------------------------------------------------------


def read_skip_state(path: Path) -> tuple[int, str | None]:
    """`(count, reason)` of the current consecutive-skip run, or `(0,
    None)` for a missing/empty/malformed file -- never raises: a corrupt
    state file degrades to "no streak yet", not a wrapper failure."""
    if not path.exists():
        return 0, None
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return 0, None
    count_text, _, reason_text = text.partition(" ")
    try:
        count = int(count_text)
    except ValueError:
        return 0, None
    return count, (reason_text or None)


def _write_skip_state(path: Path, *, count: int, reason: str | None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(f"{count} {reason or ''}\n")
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def reset_skip_state(path: Path) -> None:
    """Called at the top of `run_once` -- reaching it at all means the
    wrapper got past both skip gates and a real attempt is happening now,
    so any prior skip streak is over."""
    _write_skip_state(path, count=0, reason=None)


def record_skip(
    *,
    skip_state_path: Path,
    reason: SkipReason,
    site: str = "breezy-replay-daily",
    sink: AlertSink | None = None,
) -> None:
    """The wrapper's own skip paths (lock contention, no armed family) call
    into this -- never `record_blocked` (a skip means `run_once` never
    even started). Escalates on every run once the trailing run reaches
    `STALL_ALERT_RUN_LENGTH`, same self-healing cadence as B19 (fix 5): a
    failed send is retried the very next scheduled tick, never lost for
    good."""
    previous_count, previous_reason = read_skip_state(skip_state_path)
    count = previous_count + 1 if previous_reason == reason else 1
    _write_skip_state(skip_state_path, count=count, reason=reason)
    if count >= STALL_ALERT_RUN_LENGTH:
        active_sink = sink if sink is not None else resolve_alert_sink(os.environ)
        emit_alert(
            active_sink,
            AlertPayload(
                severity="warning",
                event="BREEZY_REPLAY_SKIPPED_STALLED",
                site=site,
                detail=(
                    f"{count} consecutive wrapper skips reason={reason}; the schedule "
                    "never even attempted a replay"
                ),
            ),
        )


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
    lag_minutes: int = DEFAULT_LAG_MINUTES,
) -> list[str]:
    """The complete argument vector for
    `current_rung_hold_paper_replay.py` -- every `required=True` argument
    of that parser is present (B17; `test_replay_daily_runner.py` asserts
    this set against the driver's own source).

    **Never passes `--strategy` (review fix 2, HIGH).** With
    `--family-manifest` set, the driver's own contract
    (`resolve_family_parameters`, `current_rung_hold_paper_replay.py`
    ~:461) derives the strategy from the manifest's `composition_kind` and
    REFUSES (`FamilyManifestArgumentError` -> exit
    `EXIT_FAMILY_MANIFEST_REFUSED`) an explicit `--strategy` that
    disagrees. A hardcoded `--strategy continuous_rung_hold` here would
    permanently refuse every `current_rung_hold`-composition family (e.g.
    `pm_us_crh_v2`)."""
    return [
        python_executable,
        str(_SCRIPTS_DIR / "current_rung_hold_paper_replay.py"),
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
    """Dispatch on the driver's exit code, never on its message (AUD-19 §6 E3).

    `BLOCKED` only for the mapped refusal codes: family-manifest `2`/`3`
    and the Phase 3 fee-schedule preflight `4` (should not occur in
    practice -- the runner's own Phase 2 pre-selection already excludes a
    mismatched day -- but classified rather than mis-filed as a crash).
    Exit `1` is an uncaught driver exception: the exception type is the
    LAST `...Error` name in stderr (base plan §9's
    `NoDecisionWindowCoverageError` / `EntryAskFromLatchMissingError` /
    `ImpossibleFillPriceError`), or `UnknownDriverFailure` when stderr
    names none. Every other code -- a signal (`-9`), `137`, or any future
    code -- is `FAILED` with the literal `UNCLASSIFIED_DRIVER_EXIT_<returncode>`
    and does not consult stderr. Exit `4` stays the fee-regime mapping;
    AUD-19's table predates that code and does not reclassify it.
    """
    if returncode == _EXIT_FAMILY_MANIFEST_REFUSED:
        return "BLOCKED", "FAMILY_MANIFEST_REFUSED"
    if returncode == _EXIT_FAMILY_MANIFEST_UNUSABLE:
        return "BLOCKED", "FAMILY_MANIFEST_UNUSABLE"
    if returncode == _EXIT_FEE_SCHEDULE_MISMATCH:
        return "BLOCKED", "FEE_SCHEDULE_MISMATCH"
    if returncode != 1:
        return "FAILED", f"UNCLASSIFIED_DRIVER_EXIT_{returncode}"
    matches = _EXCEPTION_NAME_RE.findall(stderr)
    exception_type = matches[-1] if matches else "UnknownDriverFailure"
    return "FAILED", exception_type


def _resolved_driver_argv(argv: Sequence[str]) -> list[str]:
    """Arguments after the driver script path.

    That is the vector `current_rung_hold_paper_replay.main` hashes
    (`resolved_argv` = `sys.argv[1:]`). `build_driver_argv` is
    `[python, script, *flags]`, so this is `flags`, never the interpreter
    or the script path -- hashing either would refuse every real sidecar.
    """
    for index, token in enumerate(argv):
        if token.endswith("current_rung_hold_paper_replay.py"):
            return list(argv[index + 1 :])
    return list(argv)


_REQUIRED_FAMILY_PARAMS_STR_KEYS: Final[frozenset[str]] = frozenset(
    {
        "family_id",
        "manifest_sha256",
        "manifest_taker_fee_coefficient",
        "engine_required_fee_coefficient",
        "engine_params_source",
        "composition_kind",
    },
)
_REQUIRED_FAMILY_PARAMS_BOOL_KEYS: Final[frozenset[str]] = frozenset({"params_match"})


def _family_params_sidecar_is_well_formed(payload: Mapping[str, object]) -> bool:
    for key in _REQUIRED_FAMILY_PARAMS_STR_KEYS:
        if not isinstance(payload.get(key), str):
            return False
    for key in _REQUIRED_FAMILY_PARAMS_BOOL_KEYS:
        if not isinstance(payload.get(key), bool):
            return False
    return True


def _verified_family_params(
    sidecar_path: Path, expected_argv_sha256: str,
) -> tuple[dict[str, object] | None, str | None]:
    """`(payload, None)` when the sidecar's `argv_sha256` matches, else
    `(None, blocked_reason)`. A missing file and a digest that does not
    match are different reasons; both are re-runnable provenance refusals.
    An unreadable, non-object, or schema-invalid file is malformed.
    """
    if not sidecar_path.is_file():
        return None, "FAMILY_PARAMS_SIDECAR_MISSING"
    try:
        payload = json.loads(sidecar_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None, "FAMILY_PARAMS_SIDECAR_MALFORMED"
    if not isinstance(payload, dict):
        return None, "FAMILY_PARAMS_SIDECAR_MALFORMED"
    actual = payload.get("argv_sha256")
    if not isinstance(actual, str) or actual != expected_argv_sha256:
        return None, "FAMILY_PARAMS_ARGV_MISMATCH"
    if not _family_params_sidecar_is_well_formed(payload):
        return None, "FAMILY_PARAMS_SIDECAR_MALFORMED"
    return payload, None


class UnsupportedCompositionKindError(Exception):
    """The armed family manifest declares `composition_kind="forecast_ladder"`
    -- `current_rung_hold_paper_replay.py` has no such strategy class
    (`resolve_family_parameters`'s own refusal); the runner refuses at
    the top of `run_once`, before any selection."""


#: `FamilyManifest.composition_kind`'s three values (`persistence/
#: family_manifest.py`); the driver supports exactly the first two.
_SUPPORTED_COMPOSITION_KINDS: Final[frozenset[str]] = frozenset(
    {"current_rung_hold", "continuous_rung_hold"}
)


def resolve_strategy_from_manifest(family_manifest_path: Path) -> str:
    """Review fix 2 (HIGH): the strategy is ALWAYS derived from the armed
    family's own `composition_kind` -- never a runner-side literal. A
    manifest declaring `composition_kind="forecast_ladder"` is refused
    (`UnsupportedCompositionKindError`); the driver itself has no such
    strategy class (`resolve_family_parameters`'s own check)."""
    manifest = load_family_manifest(family_manifest_path)
    if manifest.composition_kind not in _SUPPORTED_COMPOSITION_KINDS:
        raise UnsupportedCompositionKindError(
            f"{family_manifest_path}: composition_kind "
            f"{manifest.composition_kind!r} has no replay strategy class"
        )
    return manifest.composition_kind


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


def _run_subprocess_with_rss(
    argv: Sequence[str], *, timeout: float | None = None,
) -> tuple[subprocess.CompletedProcess[str], int]:
    """R3V-a item 4: like `_default_run_subprocess`, but returns
    `(result, peak_rss_bytes)` measured for THIS CHILD ALONE via
    `os.wait4` at reap time.

    `resource.getrusage(RUSAGE_CHILDREN).ru_maxrss` is a cumulative,
    NON-DECREASING watermark across every child a process has ever reaped
    -- a delta taken around a second, smaller target in the same batch
    reads 0 (the day the queue would otherwise silently under-report every
    target after the first, largest one). `subprocess.run`/`Popen.wait`
    reap via `os.waitpid`, which discards the child's own rusage, so the
    pipes are drained on background threads (mirrors `Popen.communicate`'s
    own approach) and the child is reaped with `os.wait4` ourselves
    instead."""
    proc = subprocess.Popen(
        list(argv), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    assert proc.stdout is not None
    assert proc.stderr is not None
    stdout_box: list[str] = []
    stderr_box: list[str] = []

    def _drain(stream: object, box: list[str]) -> None:
        box.append(stream.read())  # type: ignore[attr-defined]

    stdout_thread = threading.Thread(target=_drain, args=(proc.stdout, stdout_box))
    stderr_thread = threading.Thread(target=_drain, args=(proc.stderr, stderr_box))
    stdout_thread.start()
    stderr_thread.start()
    stdout_thread.join(timeout=timeout)
    stderr_thread.join(timeout=timeout)
    if stdout_thread.is_alive() or stderr_thread.is_alive():
        proc.kill()
        stdout_thread.join()
        stderr_thread.join()
        try:
            os.wait4(proc.pid, 0)
        except ChildProcessError:
            pass
        raise subprocess.TimeoutExpired(list(argv), timeout)
    _reaped_pid, status, rusage = os.wait4(proc.pid, 0)
    returncode = os.waitstatus_to_exitcode(status)
    result = subprocess.CompletedProcess(
        args=list(argv), returncode=returncode,
        stdout="".join(stdout_box), stderr="".join(stderr_box),
    )
    return result, rusage.ru_maxrss * 1024


def _default_batch_run_subprocess(
    argv: Sequence[str], *, timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    """`run_batch`'s own default `run_subprocess` (coordinator review
    follow-up on commit 0868fbb, CRITICAL): `_run_one` always passes
    `timeout=` to the driver call once `driver_timeout_s` is not `None` --
    true for every `run_batch` call, since it always computes a real
    numeric budget -- so the default `run_subprocess` a real (fake-free)
    `run_batch` invocation uses MUST itself accept `timeout=`.
    `_default_run_subprocess` (single-arg, `run_once`'s own default) does
    not and must stay that way: `run_once`'s byte-identity (item 7) is
    pinned against it unchanged.

    Adapts `_run_subprocess_with_rss` -- the ONLY per-child-accurate RSS
    measurement (item 4) -- to the plain `SubprocessRunner` shape
    (`Callable[[Sequence[str]], CompletedProcess]`-compatible, `timeout`
    optional) `_run_one` calls, by stashing the measured
    `peak_rss_bytes` as an attribute on the returned `CompletedProcess`
    (`_run_one` already reads exactly this via `getattr(driver_result,
    "peak_rss_bytes", None)`) -- so a real batch run wires the RSS fix
    into production, not just a test fake that sets the same attribute."""
    result, peak_rss_bytes = _run_subprocess_with_rss(argv, timeout=timeout)
    result.peak_rss_bytes = peak_rss_bytes  # type: ignore[attr-defined]
    return result


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
    #: NOT a caller-chosen dimension (review fix 2): the real strategy is
    #: always DERIVED from `family_manifest_path`'s own `composition_kind`
    #: via `resolve_strategy_from_manifest`, at the top of `run_once`.
    lag_minutes: int = DEFAULT_LAG_MINUTES
    skip_state_path: Path = DEFAULT_SKIP_STATE_PATH


def _output_dir_for_lag(
    output_root: Path, *, station: str, climate_day: str, lag_minutes: int,
) -> Path:
    return (
        output_root
        / "paper_replay" / "scored_trials" / "v3" / station / climate_day
        / f"lag_{lag_minutes}"
    )


def _output_dir_for(config: RunConfig, *, station: str, climate_day: str) -> Path:
    return _output_dir_for_lag(
        config.output_root, station=station, climate_day=climate_day,
        lag_minutes=config.lag_minutes,
    )


def _quarantine_fee_void_output_dir(
    output_dir: Path, *, now_ts: Callable[[], str] = _now_ts,
) -> bool:
    """AC5: rename (never delete) a fee-void output directory to
    `lag_<n>.fee_void.<utc-stamp>` via `os.replace`, so the `RECOVERED`
    branch can never adopt its parquet and a `paper_replay` tally globbing
    `scored_trials/v3` never pools it.

    Idempotent: returns `False` on an absent directory -- already
    quarantined under a stamped name, or nothing was ever written -- rather
    than raising. The caller's own `record_blocked` row is what matters,
    never this rename succeeding a second time."""
    if not output_dir.exists():
        return False
    stamp = now_ts().replace(":", "").replace("-", "").replace("+00:00", "Z")
    quarantined = output_dir.parent / f"{output_dir.name}.fee_void.{stamp}"
    os.replace(output_dir, quarantined)
    return True


@dataclass(frozen=True, slots=True, kw_only=True)
class LegacyFeeVoidQuarantineResult:
    """One key `quarantine_legacy_fee_void` inspected, and what it did."""

    key: ResultKey
    output_dir: Path
    action: Literal["QUARANTINED", "DRY_RUN", "ALREADY_QUARANTINED_OR_ABSENT"]


def quarantine_legacy_fee_void(
    *,
    replay_results_path: Path,
    output_root: Path,
    dry_run: bool = False,
    now_ts: Callable[[], str] = _now_ts,
) -> tuple[LegacyFeeVoidQuarantineResult, ...]:
    """AC5 backstop for rows written BEFORE this net existed (Phase 1 review
    requirement 2; e.g. the legacy MDW 2026-09-01 terminal `COMPLETED` row,
    module docstring "LOW: Legacy residue"). Scans EVERY `COMPLETED`/
    `RECOVERED` row in `replay_results.jsonl` for `is_fee_schedule_void` --
    never assumes only one row, or only one station, is affected -- and
    quarantine-renames each one's own `_output_dir_for_lag(...)` directory.

    Idempotent: a directory already renamed (or never written) reports
    `ALREADY_QUARANTINED_OR_ABSENT` rather than raising. `dry_run=True`
    reports every affected key as `DRY_RUN` without touching the
    filesystem. Never rewrites `replay_results.jsonl`, which is
    append-only."""
    results = read_replay_results(replay_results_path)
    affected_keys = sorted(
        {
            result_key(row)
            for row in results
            if row.outcome in ("COMPLETED", "RECOVERED") and is_fee_schedule_void(row)
        }
    )
    reports: list[LegacyFeeVoidQuarantineResult] = []
    for key in affected_keys:
        station, climate_day, _strategy, lag_minutes = key
        output_dir = _output_dir_for_lag(
            output_root, station=station, climate_day=climate_day, lag_minutes=lag_minutes,
        )
        action: Literal["QUARANTINED", "DRY_RUN", "ALREADY_QUARANTINED_OR_ABSENT"]
        if dry_run:
            action = "DRY_RUN"
        elif _quarantine_fee_void_output_dir(output_dir, now_ts=now_ts):
            action = "QUARANTINED"
        else:
            action = "ALREADY_QUARANTINED_OR_ABSENT"
        reports.append(
            LegacyFeeVoidQuarantineResult(key=key, output_dir=output_dir, action=action)
        )
    return tuple(reports)


def _append_terminal(
    config: RunConfig,
    target: ReplaySufficiency,
    *,
    strategy: str,
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
    validity = (
        "PARAMS_VERIFIED"
        if params_match is True and AUD11_AND_AUD12_LANDED
        else REPLAY_VALIDITY
    )
    row = ReplayResult(
        schema_version=REPLAY_RESULTS_SCHEMA_VERSION,
        run_ts=now_ts(),
        station=target.station,
        climate_day=target.climate_day,
        strategy=strategy,
        lag_minutes=config.lag_minutes,
        outcome=outcome,
        validity=validity,
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
    fee_coefficient_as_of: Callable[[int], Decimal | None] | None = None,
) -> int:
    """The whole nightly decision, end to end. Returns the process exit
    code (never raises for an expected outcome -- BLOCKED/FAILED/EMPTY are
    all ordinary returns; H0/H3 corruption is the one thing that
    propagates as a loud non-zero exit, never a silent empty queue).

    `fee_coefficient_as_of` (AUD-09b amendment fee-regime plan, Phase 2) is
    the SAME kind of optional production seam as `std_utc_offset_hours_for`
    above: `None` here (every pre-existing test's default) keeps
    `select_target` date-blind, exactly as before this plan; `main` wires
    the real `breezy.adapters.polymarket_us.fees.taker_fee_coefficient_as_
    of` in production. AC2's durable fee-void exclusion (`fee_void_keys`)
    is NOT gated behind this kwarg -- it always runs once the armed
    family's theta is known, independent of Phase 2's date table."""
    active_sink = sink if sink is not None else resolve_alert_sink(os.environ)
    # Review fix 3: reaching this function at all means the wrapper got
    # past both its own skip gates (the lock, the armed-family check) --
    # any prior wrapper-skip streak is over.
    reset_skip_state(config.skip_state_path)

    try:
        strategy = resolve_strategy_from_manifest(config.family_manifest_path)
        required_fee_coefficient = load_family_manifest(
            config.family_manifest_path,
        ).taker_fee_coefficient
    except (OSError, FamilyManifestError, UnsupportedCompositionKindError) as exc:
        print(f"replay_daily_runner: family manifest unusable: {exc}", file=sys.stderr)
        return 1

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
        strategy=strategy,
        lag_minutes=config.lag_minutes,
        required_fee_coefficient=required_fee_coefficient,
        fee_coefficient_as_of=fee_coefficient_as_of,
    )
    # AC4: nothing about the fee-regime exclusion is silent, whether or not
    # it is what emptied the queue.
    excluded_count = fee_regime_excluded_count(
        rows=rows,
        replayed=existing_results,
        drift=current_drift,
        strategy=strategy,
        lag_minutes=config.lag_minutes,
        required_fee_coefficient=required_fee_coefficient,
        fee_coefficient_as_of=fee_coefficient_as_of,
    )
    print(
        f"FEE_REGIME_EXCLUDED {excluded_count} station-day(s) "
        f"(required theta={required_fee_coefficient}; table=FEE_SCHEDULE_PIN_2026-09-18)"
    )
    if target is None:
        sufficient_count = sum(1 for row in rows if row.verdict == "SUFFICIENT")
        if sufficient_count == 0:
            histogram = dict(
                sorted(Counter(row.reason for row in rows if row.verdict == "INSUFFICIENT").items())
            )
            print(f"EVERY DAY INSUFFICIENT -- {histogram}")
        elif excluded_count > 0:
            print(
                f"QUEUE EMPTY (FEE REGIME) -- {excluded_count} station-day(s) excluded by the "
                "dated fee schedule; table=FEE_SCHEDULE_PIN_2026-09-18"
            )
        else:
            print(
                f"QUEUE EMPTY -- {sufficient_count} SUFFICIENT day(s), all replayed under "
                "key (station, climate_day, strategy, lag)"
            )
        return 0

    exit_code, _outcome, _wall_s = _run_one(
        config, target, strategy=strategy, run_subprocess=run_subprocess,
        sink=active_sink, now_ts=now_ts, work_dir_factory=work_dir_factory,
        std_utc_offset_hours_for=std_utc_offset_hours_for,
    )
    return exit_code


def _run_one(
    config: RunConfig,
    target: ReplaySufficiency,
    *,
    strategy: str,
    run_subprocess: SubprocessRunner,
    sink: AlertSink,
    now_ts: Callable[[], str],
    work_dir_factory: Callable[[], Path],
    std_utc_offset_hours_for: Callable[[str], float] | None,
    driver_timeout_s: float | None = None,
) -> tuple[int, str, float]:
    """Runs ONE already-selected target end to end: the ASOS producer, the
    driver, and every terminal/`BLOCKED` row this can produce. R3V-a
    factored this out of `run_once` (which calls it exactly once, keeping
    its own observable behaviour -- stdout and the row appended --
    unchanged) so `run_batch` can call it in a loop; batching still runs
    each target as its OWN isolated subprocess (never a single
    long-lived engine across targets) -- see the unit's own
    `MemoryHigh=3G`/`MemoryMax=4G` comment, `breezy-replay-daily.
    service:32-35`, for why that isolation matters.

    Returns `(exit_code, outcome, wall_s)`. `outcome` is one of
    `RECOVERED`/`BLOCKED`/`FAILED`/`COMPLETED` -- the caller handles the
    target-is-`None` `EMPTY` case itself, before ever calling this.
    `driver_timeout_s`, when given (R3V-a item 1, "L-53"), bounds only the
    DRIVER subprocess (never the cheap ASOS producer); a `TimeoutExpired`
    there is recorded as a terminal `FAILED` row with
    `exception_type=DRIVER_TIMEOUT` and a non-zero exit, so `run_batch`
    stops loudly rather than burning the rest of its budget on one stuck
    target."""
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
                    config, target, strategy=strategy, now_ts=now_ts, outcome="FAILED",
                    exception_type=type(exc).__name__,
                )
                print(
                    f"FAILED {station} {climate_day} -- unreadable parquet {latest}",
                    file=sys.stderr,
                )
                return 1, "FAILED", 0.0
            _append_terminal(
                config, target, strategy=strategy, now_ts=now_ts, outcome="RECOVERED",
                parquet_sha256=digest,
            )
            print(f"RECOVERED {station} {climate_day} -- {latest.name}")
            return 0, "RECOVERED", 0.0

    work_dir = work_dir_factory()
    try:
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
                strategy=strategy, lag_minutes=config.lag_minutes, blocked_reason=reason,
                sufficiency_reason=target.reason, census_schema_version=target.schema_version,
                sink=sink, now_ts=now_ts,
            )
            print(f"BLOCKED {station} {climate_day} -- {reason}")
            return 0, "BLOCKED", 0.0

        work_catalog = work_dir / "work_catalog"
        started = time.monotonic()
        rss_before = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
        driver_argv = build_driver_argv(
            python_executable=config.python_executable,
            station=station, climate_day=climate_day,
            tape_instance_id=target.winner_instance_id or "",
            quote_catalog=config.quote_catalog, work_catalog=work_catalog,
            asos_cache_csv=asos_csv, weather_catalog_root=config.weather_catalog_root,
            output_dir=output_dir, family_manifest_path=config.family_manifest_path,
            lag_minutes=config.lag_minutes,
        )
        expected_argv_sha256 = argv_sha256(_resolved_driver_argv(driver_argv))
        try:
            if driver_timeout_s is not None:
                driver_result = run_subprocess(driver_argv, timeout=driver_timeout_s)
            else:
                driver_result = run_subprocess(driver_argv)
        except subprocess.TimeoutExpired:
            wall_s = time.monotonic() - started
            _append_terminal(
                config, target, strategy=strategy, now_ts=now_ts, outcome="FAILED",
                exception_type="DRIVER_TIMEOUT", wall_s=wall_s,
            )
            print(f"FAILED {station} {climate_day} -- DRIVER_TIMEOUT", file=sys.stderr)
            return 1, "FAILED", wall_s
        wall_s = time.monotonic() - started
        measured_rss = getattr(driver_result, "peak_rss_bytes", None)
        if measured_rss is None:
            rss_after = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
            peak_rss_bytes = max(0, (rss_after - rss_before)) * 1024
        else:
            peak_rss_bytes = measured_rss
        if peak_rss_bytes > REPLAY_TARGET_RSS_WARN_BYTES:
            emit_alert(
                sink,
                AlertPayload(
                    severity="warning",
                    event="BREEZY_REPLAY_TARGET_RSS_HIGH",
                    site=station,
                    detail=(
                        f"{climate_day}: peak_rss_bytes={peak_rss_bytes} exceeds "
                        f"REPLAY_TARGET_RSS_WARN_BYTES={REPLAY_TARGET_RSS_WARN_BYTES}"
                    ),
                ),
            )

        if driver_result.returncode != 0:
            outcome, reason = classify_driver_failure(
                returncode=driver_result.returncode, stderr=driver_result.stderr or "",
            )
            if outcome == "BLOCKED":
                record_blocked(
                    results_path=config.replay_results_path, station=station,
                    climate_day=climate_day, strategy=strategy, lag_minutes=config.lag_minutes,
                    blocked_reason=reason, sufficiency_reason=target.reason,
                    census_schema_version=target.schema_version, sink=sink, now_ts=now_ts,
                )
                print(f"BLOCKED {station} {climate_day} -- {reason}")
                return 0, "BLOCKED", wall_s
            _append_terminal(
                config, target, strategy=strategy, now_ts=now_ts, outcome="FAILED",
                exception_type=reason, wall_s=wall_s, peak_rss_bytes=peak_rss_bytes,
            )
            print(f"FAILED {station} {climate_day} -- {reason}", file=sys.stderr)
            return 1, "FAILED", wall_s

        sidecar_path = output_dir / "family_params.json"
        sidecar, sidecar_refusal = _verified_family_params(sidecar_path, expected_argv_sha256)
        if sidecar is None:
            reason = sidecar_refusal or "FAMILY_PARAMS_SIDECAR_MISSING"
            record_blocked(
                results_path=config.replay_results_path, station=station, climate_day=climate_day,
                strategy=strategy, lag_minutes=config.lag_minutes, blocked_reason=reason,
                sufficiency_reason=target.reason, census_schema_version=target.schema_version,
                sink=sink, now_ts=now_ts,
            )
            print(f"BLOCKED {station} {climate_day} -- {reason}")
            return 0, "BLOCKED", wall_s
        manifest_taker_fee_coefficient = sidecar.get("manifest_taker_fee_coefficient")
        engine_required_fee_coefficient = sidecar.get("engine_required_fee_coefficient")
        scored = read_scored_trials(output_dir)
        fill_price_vs_decision_ask = tuple(str(trial.slippage) for trial in scored)
        refusal_counts = _parse_strategy_refusals(driver_result.stdout or "")

        # AUD-09b fee-regime plan, Phase 1: net (1), the exact post-hoc
        # safety backstop. A day the engine ever refused on
        # `fee_schedule_mismatch` is VOID regardless of `trials` -- a
        # partial day under a latched halt is contaminated (AC1) -- so it
        # is quarantined and recorded `BLOCKED`, never `COMPLETED`, and
        # stays queued for re-selection under a DIFFERENT family's theta
        # only (`fee_void_keys`, AC2).
        if refusal_counts.get(FEE_SCHEDULE_MISMATCH_REFUSAL, 0) >= 1:
            _quarantine_fee_void_output_dir(output_dir, now_ts=now_ts)
            record_blocked(
                results_path=config.replay_results_path, station=station, climate_day=climate_day,
                strategy=strategy, lag_minutes=config.lag_minutes,
                blocked_reason="FEE_SCHEDULE_MISMATCH",
                sufficiency_reason=target.reason, census_schema_version=target.schema_version,
                family_id=sidecar.get("family_id"),  # type: ignore[arg-type]
                manifest_taker_fee_coefficient=manifest_taker_fee_coefficient,  # type: ignore[arg-type]
                engine_required_fee_coefficient=engine_required_fee_coefficient,  # type: ignore[arg-type]
                tape_instance_id=target.winner_instance_id,
                refusal_counts=refusal_counts,
                sink=sink, now_ts=now_ts,
            )
            print(f"BLOCKED {station} {climate_day} -- FEE_SCHEDULE_MISMATCH")
            return 0, "BLOCKED", wall_s

        parquet_files = sorted(output_dir.glob("scored_trials_*.parquet"))
        parquet_sha256 = (
            hashlib.sha256(parquet_files[-1].read_bytes()).hexdigest() if parquet_files else None
        )

        _append_terminal(
            config, target, strategy=strategy, now_ts=now_ts, outcome="COMPLETED",
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
        # Review fix 6 (MEDIUM): trials=0 AND an empty refusal_counts is
        # indistinguishable from a broken engine -- a real quiet day still
        # logs at least one strategy refusal (e.g. outside_decision_window)
        # for every candidate it considered. Still COMPLETED (a genuine
        # mechanism outcome), but escalated once as a WARN so it is never
        # silently absorbed into the ordinary zero-trade case.
        if len(scored) == 0 and not refusal_counts:
            emit_alert(
                sink,
                AlertPayload(
                    severity="warning",
                    event="BREEZY_REPLAY_SUSPECT_ZERO_ACTIVITY",
                    site=station,
                    detail=(
                        f"{climate_day}: COMPLETED with 0 trials and an empty refusal "
                        "histogram -- check the engine actually evaluated this day"
                    ),
                ),
            )
        if std_utc_offset_hours_for is not None:
            offset = std_utc_offset_hours_for(station)
            interval = (
                f"[{_format_lst(target.winner_first_in_window_ns, std_utc_offset_hours=offset)}, "
                f"{_format_lst(target.winner_last_in_window_ns, std_utc_offset_hours=offset)}) LST"
            )
        else:
            interval = "[?, ?) LST"
        # R3-VIABILITY r1 §3.4 / r2 delta "R3V-b" item 5: a post-freeze
        # COMPLETED line withholds `trials=`/`fills=` entirely -- the STORED
        # row (above) still carries the real counts; only this printed line
        # hides them, so a live log tail (or `journalctl`) never leaks a
        # post-freeze take-rate. `_run_one` is the ONE place the COMPLETED
        # line is printed for both `run_once` (single target) and
        # `run_batch` (R3V-a's loop), so withholding it here covers both.
        counts = (
            "post-freeze: counts withheld"
            if climate_day > FREEZE_CLIMATE_DAY
            else f"trials={len(scored)} fills={len(scored)}"
        )
        print(
            f"COMPLETED {station} {climate_day} -- {counts} "
            f"replayed {interval} of [12:00, 17:00); window_complete={target.window_complete} "
            f"coverage_kind={target.coverage_kind}"
        )
        return 0, "COMPLETED", wall_s
    finally:
        # R3V-a item 6: a batch of `max_targets` mkdtemp work dirs is never
        # left behind -- best-effort, never masks the real outcome above.
        if work_dir.exists():
            shutil.rmtree(work_dir, ignore_errors=True)


def _queue_empty_message(*, rows: Sequence[ReplaySufficiency], excluded_count: int) -> str:
    """The same three-way "nothing to do" message `run_once` prints
    inline, kept here as an independent copy -- `run_once` itself is not
    touched by this plan at all (item 7's byte-identity guarantee), so
    this is deliberately duplicated rather than extracted out from under
    it."""
    sufficient_count = sum(1 for row in rows if row.verdict == "SUFFICIENT")
    if sufficient_count == 0:
        histogram = dict(
            sorted(Counter(row.reason for row in rows if row.verdict == "INSUFFICIENT").items())
        )
        return f"EVERY DAY INSUFFICIENT -- {histogram}"
    if excluded_count > 0:
        return (
            f"QUEUE EMPTY (FEE REGIME) -- {excluded_count} station-day(s) excluded by the "
            "dated fee schedule; table=FEE_SCHEDULE_PIN_2026-09-18"
        )
    return (
        f"QUEUE EMPTY -- {sufficient_count} SUFFICIENT day(s), all replayed under "
        "key (station, climate_day, strategy, lag)"
    )


def _in_protected_window(now: dt.datetime) -> bool:
    """R3V-a item 3: reuses the SAME `[16:35Z, 01:15Z)` no-start window
    `scripts/venue/fee_drift_evidence_pull.py` already defines
    (`deploy/systemd/README.md`) -- never a second literal copy of the
    bounds. Imported lazily (like `main`'s own `taker_fee_coefficient_as_
    of` import) so every caller that never runs `run_batch` -- every test
    in this suite except the batch ones -- never pays for that module's
    own (heavier) import surface."""
    venue_dir = str(Path(__file__).resolve().parent.parent / "venue")
    if venue_dir not in sys.path:
        sys.path.insert(0, venue_dir)
    from fee_drift_evidence_pull import is_protected_window

    return is_protected_window(now)


def run_batch(
    config: RunConfig,
    *,
    max_targets: int = 1,
    budget_s: float,
    reserve_s: float = DEFAULT_REPLAY_BATCH_RESERVE_S,
    run_subprocess: SubprocessRunner = _default_batch_run_subprocess,
    sink: AlertSink | None = None,
    now_ts: Callable[[], str] = _now_ts,
    work_dir_factory: Callable[[], Path] = _default_work_dir,
    std_utc_offset_hours_for: Callable[[str], float] | None = None,
    fee_coefficient_as_of: Callable[[int], Decimal | None] | None = None,
    monotonic: Callable[[], float] = time.monotonic,
    now_utc: Callable[[], dt.datetime] = lambda: dt.datetime.now(dt.UTC),
) -> int:
    """R3-VIABILITY plan r1 §3 items 1-3/§5-6, AS AMENDED by r2 delta
    "R3V-a" (r2 wins). One census read, drift computation, and manifest
    resolve -- "per-batch state", item 5: `reset_skip_state`, the manifest
    resolve, `compute_drift`/`write_replay_drift`/`emit_new_drift_alerts`,
    and the `FEE_REGIME_EXCLUDED` line all run EXACTLY ONCE regardless of
    `max_targets` -- then a bounded loop over `_run_one` until one of:

    - the queue is empty;
    - `max_targets` is reached;
    - the budget (`budget_s` minus `reserve_s`) is spent;
    - the protected no-start window `[16:35Z, 01:15Z)` is reached (item 3
      -- checked before EVERY new target, never only at batch start);
    - the first target with a non-zero exit, which stops the batch loudly
      so `OnFailure=` fires (item 1's `DRIVER_TIMEOUT` is one such exit).

    A key tried THIS batch is excluded from re-selection even when its
    outcome was `BLOCKED` (not terminal) -- the single-target runner's own
    head-of-line risk (r1 §3).

    `max_targets=1` still runs the FULL batch machinery below (the budget
    and protected-window checks apply, and `run_batch` never delegates to
    `run_once`) -- but prints no `BATCH_SUMMARY` line (item 5). The
    byte-identity guarantee (item 7) comes from `main`: a bare invocation
    with neither `--max-targets` nor `--budget-s` calls `run_once`
    directly, which this plan has not touched at all."""
    batch_started = monotonic()
    active_sink = sink if sink is not None else resolve_alert_sink(os.environ)
    reset_skip_state(config.skip_state_path)

    try:
        strategy = resolve_strategy_from_manifest(config.family_manifest_path)
        required_fee_coefficient = load_family_manifest(
            config.family_manifest_path,
        ).taker_fee_coefficient
    except (OSError, FamilyManifestError, UnsupportedCompositionKindError) as exc:
        print(f"replay_daily_runner: family manifest unusable: {exc}", file=sys.stderr)
        return 1

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

    excluded_count = fee_regime_excluded_count(
        rows=rows,
        replayed=existing_results,
        drift=current_drift,
        strategy=strategy,
        lag_minutes=config.lag_minutes,
        required_fee_coefficient=required_fee_coefficient,
        fee_coefficient_as_of=fee_coefficient_as_of,
    )
    print(
        f"FEE_REGIME_EXCLUDED {excluded_count} station-day(s) "
        f"(required theta={required_fee_coefficient}; table=FEE_SCHEDULE_PIN_2026-09-18)"
    )

    # Item 2: a budget at or below the reserve starts zero targets --
    # including a negative budget (a wrapper arithmetic bug must never
    # crash the runner, only pause it).
    if budget_s <= reserve_s:
        print(
            f"QUEUE PAUSED (BUDGET) -- budget_s={budget_s} <= reserve_s={reserve_s}; "
            "started 0 target(s)"
        )
        return 0

    tried: set[ResultKey] = set()
    summaries: list[tuple[str, str, str, float]] = []
    exit_code = 0
    stop_reason = "MAX_TARGETS"

    while len(summaries) < max_targets:
        elapsed = monotonic() - batch_started
        if budget_s - elapsed <= reserve_s:
            stop_reason = "BUDGET"
            break
        if _in_protected_window(now_utc()):
            stop_reason = "PROTECTED_WINDOW"
            break

        target = select_target(
            rows=rows,
            replayed=existing_results,
            drift=current_drift,
            strategy=strategy,
            lag_minutes=config.lag_minutes,
            required_fee_coefficient=required_fee_coefficient,
            fee_coefficient_as_of=fee_coefficient_as_of,
            exclude=frozenset(tried),
        )
        if target is None:
            stop_reason = "EMPTY"
            if not summaries:
                print(_queue_empty_message(rows=rows, excluded_count=excluded_count))
            break

        tried.add((target.station, target.climate_day, strategy, config.lag_minutes))
        remaining = budget_s - (monotonic() - batch_started)
        driver_timeout_s = max(0.0, remaining - reserve_s)
        target_exit_code, outcome, wall_s = _run_one(
            config, target, strategy=strategy, run_subprocess=run_subprocess,
            sink=active_sink, now_ts=now_ts, work_dir_factory=work_dir_factory,
            std_utc_offset_hours_for=std_utc_offset_hours_for,
            driver_timeout_s=driver_timeout_s,
        )
        summaries.append((target.station, target.climate_day, outcome, wall_s))
        if target_exit_code != 0:
            exit_code = target_exit_code
            stop_reason = "TARGET_FAILED"
            break

    # Item 5: no batch summary at max_targets=1. Item 10: the summary is
    # one stdout line, with per-target wall_s, so the wrapper's own $LOG
    # redirect captures it (L-52).
    if max_targets != 1:
        detail = " ".join(f"{s}/{d}={o}(wall_s={w:.1f})" for s, d, o, w in summaries)
        print(f"BATCH_SUMMARY {len(summaries)} target(s) stop={stop_reason} -- {detail}")
    return exit_code


def _resolve_std_utc_offset_hours(station: str) -> float:
    from breezy.registry.sites import default_registry

    return default_registry().climate_day_window(WEATHER_VENUE, station).std_utc_offset_hours


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replay-sufficiency", type=Path, default=DEFAULT_REPLAY_SUFFICIENCY_PATH)
    parser.add_argument("--replay-results", type=Path, default=DEFAULT_REPLAY_RESULTS_PATH)
    parser.add_argument("--replay-drift", type=Path, default=DEFAULT_REPLAY_DRIFT_PATH)
    # Not `required=True`: a `--report-skip` invocation (review fix 3) never
    # touches these -- the wrapper never reached `run_once` at all. `main`
    # enforces requiredness itself when `--report-skip` is absent, below.
    parser.add_argument("--quote-catalog", type=Path, default=None)
    parser.add_argument("--weather-catalog-root", type=Path, default=None)
    parser.add_argument("--family-manifest", type=Path, default=None)
    parser.add_argument("--output-root", type=Path, default=None)
    parser.add_argument(
        "--python", dest="python_executable", type=str, default=sys.executable,
    )
    parser.add_argument(
        "--report-skip",
        choices=("LOCK_CONTENTION", "NO_ARMED_FAMILY"),
        default=None,
        help=(
            "Review fix 3: the wrapper's OWN skip paths (lock contention, "
            "no armed family) call this instead of running the census/"
            "driver at all. Records a durable skip and escalates once the "
            "consecutive-skip run reaches 3, then exits -- run_once never "
            "starts."
        ),
    )
    parser.add_argument("--skip-state-path", type=Path, default=DEFAULT_SKIP_STATE_PATH)
    parser.add_argument(
        "--reset-skip-state",
        action="store_true",
        help=(
            "AUT-6 WP3 S1: the wrapper's healthy composition skip "
            "(forecast_quantile_ladder has no replay) clears any prior skip "
            "streak, so a stale LOCK_CONTENTION count never re-pages STALLED. "
            "Resets --skip-state-path and exits; run_once never starts."
        ),
    )
    parser.add_argument(
        "--quarantine-legacy-fee-void",
        action="store_true",
        help=(
            "AUD-09b fee-regime plan, Phase 1 review requirement 2: a "
            "coordinator-run, one-shot migration. Scans replay_results.jsonl "
            "for every COMPLETED/RECOVERED row whose refusal_counts records "
            "a fee_schedule_mismatch (e.g. the pre-net MDW 2026-09-01 row) "
            "and quarantine-renames its own output directory. Never "
            "rewrites the append-only results file, and never invokes "
            "run_once. Requires --replay-results and --output-root; every "
            "other run_once-only flag is ignored."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="With --quarantine-legacy-fee-void, list affected keys without renaming.",
    )
    parser.add_argument(
        "--max-targets",
        type=int,
        default=1,
        help=(
            "R3V-a: replay up to this many (station, climate_day) targets "
            "in one invocation, re-selecting from the same census each "
            "time (a key tried this batch is excluded even if BLOCKED). "
            "Default 1 -- today's behaviour: main() calls run_once "
            "directly (never run_batch) whenever this is left at 1, for a "
            "byte-identical default path."
        ),
    )
    parser.add_argument(
        "--budget-s",
        type=float,
        default=None,
        help=(
            "R3V-a: required whenever --max-targets != 1. Wall-clock "
            "budget for the whole batch; the loop stops offering new "
            "targets once the remaining budget reaches "
            "DEFAULT_REPLAY_BATCH_RESERVE_S. May be zero or negative "
            "(the wrapper's own arithmetic can run past TimeoutStartSec) "
            "-- that starts zero targets and exits 0, never a crash."
        ),
    )
    args = parser.parse_args(argv)
    if (
        args.report_skip is None
        and not args.reset_skip_state
        and not args.quarantine_legacy_fee_void
    ):
        missing = [
            flag
            for flag, value in (
                ("--quote-catalog", args.quote_catalog),
                ("--weather-catalog-root", args.weather_catalog_root),
                ("--family-manifest", args.family_manifest),
                ("--output-root", args.output_root),
            )
            if value is None
        ]
        if missing:
            parser.error(f"the following arguments are required: {', '.join(missing)}")
        if args.max_targets != 1 and args.budget_s is None:
            parser.error("--budget-s is required when --max-targets is not 1")
    elif args.quarantine_legacy_fee_void and args.output_root is None:
        parser.error("--quarantine-legacy-fee-void requires --output-root")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    if args.report_skip is not None:
        record_skip(skip_state_path=args.skip_state_path, reason=args.report_skip)
        return 0
    if args.reset_skip_state:
        reset_skip_state(args.skip_state_path)
        return 0
    if args.quarantine_legacy_fee_void:
        reports = quarantine_legacy_fee_void(
            replay_results_path=args.replay_results,
            output_root=args.output_root,
            dry_run=args.dry_run,
        )
        for report in reports:
            station, climate_day, _strategy, lag_minutes = report.key
            print(
                f"{report.action} {station} {climate_day} lag_{lag_minutes} -- "
                f"{report.output_dir}"
            )
        print(
            f"quarantine-legacy-fee-void: {len(reports)} key(s) affected "
            f"(dry_run={args.dry_run})"
        )
        return 0
    config = RunConfig(
        replay_sufficiency_path=args.replay_sufficiency,
        replay_results_path=args.replay_results,
        replay_drift_path=args.replay_drift,
        quote_catalog=args.quote_catalog,
        weather_catalog_root=args.weather_catalog_root,
        family_manifest_path=args.family_manifest,
        output_root=args.output_root,
        python_executable=args.python_executable,
        skip_state_path=args.skip_state_path,
    )
    from breezy.adapters.polymarket_us.fees import taker_fee_coefficient_as_of

    # item 7: a bare invocation (no --max-targets) calls run_once directly
    # -- this plan has not touched run_once at all, so the default path is
    # byte-identical to before it, not merely equivalent through run_batch.
    if args.max_targets == 1:
        return run_once(
            config,
            std_utc_offset_hours_for=_resolve_std_utc_offset_hours,
            fee_coefficient_as_of=taker_fee_coefficient_as_of,
        )
    return run_batch(
        config,
        max_targets=args.max_targets,
        budget_s=args.budget_s,
        std_utc_offset_hours_for=_resolve_std_utc_offset_hours,
        fee_coefficient_as_of=taker_fee_coefficient_as_of,
    )


if __name__ == "__main__":
    raise SystemExit(main())
