"""Per-replay result record (AUD-09 plan §6b.3-4; AUD-09b amendment §10
item 4: H3 plus the R2 fields; `REPLAY_VALIDITY` unchanged).

One line per replay attempt, append-only. Unlike `replay_sufficiency.jsonl`
(a whole-file-rewritten VIEW of the tape), this is a ledger: every
`record_blocked` call, every crash recovery, and every completed/failed
replay adds exactly one line, and old lines are never rewritten.

**Duplicate-key policy, stated because it differs from H0's flat rule.** A
duplicate `(station, climate_day, strategy, lag_minutes)` key is refused --
but ONLY across the three TERMINAL outcomes (`COMPLETED`, `RECOVERED`,
`FAILED`): those each retire a station-day, and the runner's own target
selection (`replay_daily_runner.py`) never reselects a key that already
carries one. A `BLOCKED` row does the opposite -- the day stays queued, so
the SAME key is expected to repeat night after night, and the runner's own
stall-escalation rule (B19) counts exactly that run of repeats. Treating a
`BLOCKED` repeat as a "duplicate" would make the stall alert unbuildable.

`validity` is written from exactly one named constant, `REPLAY_VALIDITY`,
here and nowhere else (AUD-09 plan §6b.3, "The validity constant"): AUD-11
and AUD-12 flip this one symbol once look-ahead and cost items land.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

__all__ = [
    "FEE_SCHEDULE_MISMATCH_REFUSAL",
    "REPLAY_RESULTS_SCHEMA_VERSION",
    "REPLAY_VALIDITY",
    "DuplicateReplayResultError",
    "ReplayOutcome",
    "ReplayResult",
    "ReplayResultRecordError",
    "ResultKey",
    "UnknownReplayResultSchemaError",
    "append_replay_result",
    "is_fee_schedule_void",
    "read_replay_results",
    "result_key",
]

#: Hand-off H3 (AUD-09 plan §6b.4): every writer/reader agrees on this
#: version. Stays 1 -- the amendment's R2 fields are ADDITIVE to a schema
#: that has never shipped a row yet (§10 item 4: "REPLAY_VALIDITY
#: unchanged" and no version bump is asked for).
REPLAY_RESULTS_SCHEMA_VERSION: Final[int] = 1

#: The ONE named validity constant (AUD-09 plan §6b.3). AUD-11 (look-ahead)
#: and AUD-12 (costs) flip this symbol, and only this symbol, once both
#: land; until then every row this module writes carries it.
REPLAY_VALIDITY: Final[str] = "MECHANISM_ONLY"

ReplayOutcome = Literal["COMPLETED", "RECOVERED", "BLOCKED", "FAILED"]

#: `(station, climate_day, strategy, lag_minutes)` -- the queue key (AUD-09b
#: amendment §6b.2: `family_id` is provenance, never a queue dimension).
ResultKey = tuple[str, str, str, int]

#: Terminal outcomes retire a `ResultKey`; `BLOCKED` never does (module
#: docstring).
_TERMINAL_OUTCOMES: Final[frozenset[str]] = frozenset({"COMPLETED", "RECOVERED", "FAILED"})

#: AUD-09b amendment (fee-regime plan, Phase 1): the exact `Refuse` reason
#: literal `evaluate_decision` returns (`current_rung_hold/decision.py:344`,
#: `Refuse("fee_schedule_mismatch")`) when a tape instrument's own theta
#: disagrees with `CurrentRungHoldConfig.required_fee_coefficient`. Named
#: here, once, so `is_fee_schedule_void` and the runner's own net never
#: duplicate the string.
FEE_SCHEDULE_MISMATCH_REFUSAL: Final[str] = "fee_schedule_mismatch"


@dataclass(frozen=True, slots=True, kw_only=True)
class ReplayResult:
    """One row of `replay_results.jsonl`.

    Every field beyond the queue key + `outcome`/`validity` is `None` (or
    the degenerate empty value) when the outcome does not produce it --
    e.g. a `BLOCKED` row carries no `family_id`/`params_match`, because the
    engine never started.
    """

    schema_version: int
    run_ts: str
    station: str
    climate_day: str
    strategy: str
    lag_minutes: int
    outcome: ReplayOutcome
    validity: str
    blocked_reason: str | None
    exception_type: str | None
    family_id: str | None
    manifest_sha256: str | None
    manifest_taker_fee_coefficient: str | None
    engine_required_fee_coefficient: str | None
    engine_params_source: str | None
    params_match: bool | None
    composition_kind: str | None
    tape_instance_id: str | None
    sufficiency_reason: str
    trials: int
    fills: int
    fill_price_vs_decision_ask: tuple[str, ...]
    refusal_counts: Mapping[str, int]
    wall_s: float | None
    peak_rss_bytes: int | None
    parquet_sha256: str | None
    #: AUD-09b amendment R2 fields, below.
    window_complete: bool | None
    replayed_first_ns: int | None
    replayed_last_ns: int | None
    census_schema_version: int | None

    def to_dict(self) -> dict[str, object]:
        """Explicit field-by-field row -- never `dataclasses.asdict`
        (mirrors `ReplaySufficiency.to_dict`'s own house rule)."""
        return {
            "schema_version": self.schema_version,
            "run_ts": self.run_ts,
            "station": self.station,
            "climate_day": self.climate_day,
            "strategy": self.strategy,
            "lag_minutes": self.lag_minutes,
            "outcome": self.outcome,
            "validity": self.validity,
            "blocked_reason": self.blocked_reason,
            "exception_type": self.exception_type,
            "family_id": self.family_id,
            "manifest_sha256": self.manifest_sha256,
            "manifest_taker_fee_coefficient": self.manifest_taker_fee_coefficient,
            "engine_required_fee_coefficient": self.engine_required_fee_coefficient,
            "engine_params_source": self.engine_params_source,
            "params_match": self.params_match,
            "composition_kind": self.composition_kind,
            "tape_instance_id": self.tape_instance_id,
            "sufficiency_reason": self.sufficiency_reason,
            "trials": self.trials,
            "fills": self.fills,
            "fill_price_vs_decision_ask": list(self.fill_price_vs_decision_ask),
            "refusal_counts": dict(self.refusal_counts),
            "wall_s": self.wall_s,
            "peak_rss_bytes": self.peak_rss_bytes,
            "parquet_sha256": self.parquet_sha256,
            "window_complete": self.window_complete,
            "replayed_first_ns": self.replayed_first_ns,
            "replayed_last_ns": self.replayed_last_ns,
            "census_schema_version": self.census_schema_version,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> ReplayResult:
        """Reconstruct from a `to_dict` payload; never `cls(**payload)`.

        Raises `ReplayResultRecordError`, naming the offending key, on a
        missing key, an extra key, or a wrong type.
        """
        keys = set(payload)
        known = _FIELD_TYPES.keys() | _NESTED_FIELDS
        missing = known - keys
        if missing:
            raise ReplayResultRecordError(f"replay_result missing key(s): {sorted(missing)}")
        extra = keys - known
        if extra:
            raise ReplayResultRecordError(f"replay_result has unexpected key(s): {sorted(extra)}")

        for name, expected_type in _FIELD_TYPES.items():
            value = payload[name]
            if value is None:
                if name in _NULLABLE_FIELDS:
                    continue
                raise ReplayResultRecordError(f"{name!r} must not be null")
            is_bool_value = isinstance(value, bool)
            if expected_type is bool and not is_bool_value:
                raise ReplayResultRecordError(
                    f"{name!r} must be a bool, got {type(value).__name__}"
                )
            if expected_type is int and (not isinstance(value, int) or is_bool_value):
                raise ReplayResultRecordError(
                    f"{name!r} must be an int, got {type(value).__name__}"
                )
            if expected_type is float and not isinstance(value, float):
                raise ReplayResultRecordError(
                    f"{name!r} must be a float, got {type(value).__name__}"
                )
            if expected_type is str and not isinstance(value, str):
                raise ReplayResultRecordError(
                    f"{name!r} must be a str, got {type(value).__name__}"
                )

        fill_prices = payload["fill_price_vs_decision_ask"]
        if not isinstance(fill_prices, list) or not all(
            isinstance(item, str) for item in fill_prices
        ):
            raise ReplayResultRecordError(
                "'fill_price_vs_decision_ask' must be a list of str"
            )
        refusal_counts = payload["refusal_counts"]
        if not isinstance(refusal_counts, Mapping) or not all(
            isinstance(k, str) and isinstance(v, int) and not isinstance(v, bool)
            for k, v in refusal_counts.items()
        ):
            raise ReplayResultRecordError("'refusal_counts' must be a mapping of str to int")

        return cls(
            schema_version=payload["schema_version"],  # type: ignore[arg-type]
            run_ts=payload["run_ts"],  # type: ignore[arg-type]
            station=payload["station"],  # type: ignore[arg-type]
            climate_day=payload["climate_day"],  # type: ignore[arg-type]
            strategy=payload["strategy"],  # type: ignore[arg-type]
            lag_minutes=payload["lag_minutes"],  # type: ignore[arg-type]
            outcome=payload["outcome"],  # type: ignore[arg-type]
            validity=payload["validity"],  # type: ignore[arg-type]
            blocked_reason=payload["blocked_reason"],  # type: ignore[arg-type]
            exception_type=payload["exception_type"],  # type: ignore[arg-type]
            family_id=payload["family_id"],  # type: ignore[arg-type]
            manifest_sha256=payload["manifest_sha256"],  # type: ignore[arg-type]
            manifest_taker_fee_coefficient=payload[  # type: ignore[arg-type]
                "manifest_taker_fee_coefficient"
            ],
            engine_required_fee_coefficient=payload[  # type: ignore[arg-type]
                "engine_required_fee_coefficient"
            ],
            engine_params_source=payload["engine_params_source"],  # type: ignore[arg-type]
            params_match=payload["params_match"],  # type: ignore[arg-type]
            composition_kind=payload["composition_kind"],  # type: ignore[arg-type]
            tape_instance_id=payload["tape_instance_id"],  # type: ignore[arg-type]
            sufficiency_reason=payload["sufficiency_reason"],  # type: ignore[arg-type]
            trials=payload["trials"],  # type: ignore[arg-type]
            fills=payload["fills"],  # type: ignore[arg-type]
            fill_price_vs_decision_ask=tuple(fill_prices),
            refusal_counts=dict(refusal_counts),
            wall_s=payload["wall_s"],  # type: ignore[arg-type]
            peak_rss_bytes=payload["peak_rss_bytes"],  # type: ignore[arg-type]
            parquet_sha256=payload["parquet_sha256"],  # type: ignore[arg-type]
            window_complete=payload["window_complete"],  # type: ignore[arg-type]
            replayed_first_ns=payload["replayed_first_ns"],  # type: ignore[arg-type]
            replayed_last_ns=payload["replayed_last_ns"],  # type: ignore[arg-type]
            census_schema_version=payload["census_schema_version"],  # type: ignore[arg-type]
        )


_FIELD_TYPES: Final[dict[str, type]] = {
    "schema_version": int,
    "run_ts": str,
    "station": str,
    "climate_day": str,
    "strategy": str,
    "lag_minutes": int,
    "outcome": str,
    "validity": str,
    "blocked_reason": str,
    "exception_type": str,
    "family_id": str,
    "manifest_sha256": str,
    "manifest_taker_fee_coefficient": str,
    "engine_required_fee_coefficient": str,
    "engine_params_source": str,
    "params_match": bool,
    "composition_kind": str,
    "tape_instance_id": str,
    "sufficiency_reason": str,
    "trials": int,
    "fills": int,
    "wall_s": float,
    "peak_rss_bytes": int,
    "parquet_sha256": str,
    "window_complete": bool,
    "replayed_first_ns": int,
    "replayed_last_ns": int,
    "census_schema_version": int,
}

_NESTED_FIELDS: Final[frozenset[str]] = frozenset(
    {"fill_price_vs_decision_ask", "refusal_counts"}
)

_NULLABLE_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "blocked_reason",
        "exception_type",
        "family_id",
        "manifest_sha256",
        "manifest_taker_fee_coefficient",
        "engine_required_fee_coefficient",
        "engine_params_source",
        "params_match",
        "composition_kind",
        "tape_instance_id",
        "wall_s",
        "peak_rss_bytes",
        "parquet_sha256",
        "window_complete",
        "replayed_first_ns",
        "replayed_last_ns",
        "census_schema_version",
    }
)


class ReplayResultRecordError(Exception):
    """A `replay_results.jsonl` row failed strict round-trip validation."""


class UnknownReplayResultSchemaError(Exception):
    """A line's `schema_version` is not `REPLAY_RESULTS_SCHEMA_VERSION`."""


class DuplicateReplayResultError(Exception):
    """Two TERMINAL rows (`COMPLETED`/`RECOVERED`/`FAILED`) share a queue key.

    A duplicate means two writers raced (or the runner's own selection
    guard was bypassed) and the counts under that key are untrustworthy.
    """


def result_key(result: ReplayResult) -> ResultKey:
    """The queue key AUD-09b amendment §6b.2 defines -- no `family_id`
    dimension (`family_id` is provenance on the row, never part of the
    key, so re-arming a different family never re-replays an unchanged
    day)."""
    return (result.station, result.climate_day, result.strategy, result.lag_minutes)


def append_replay_result(path: Path, result: ReplayResult) -> None:
    """Append one line to `replay_results.jsonl`. Never rewrites, never
    checks for a duplicate itself -- `read_replay_results` is the single
    place that enforces H3's duplicate-terminal-key contract, exactly as
    `read_replay_sufficiency` enforces H0's own duplicate rule on read.

    Review fix 8: `os.fdopen(fd, ...)` takes ownership of `fd` the instant
    it succeeds, so `fd` must be closed by hand ONLY when `fdopen` itself
    fails -- once it succeeds, the `with` statement's own `__exit__`
    already closes it while unwinding on any later failure (a write, a
    flush, an `fsync`), and a second `os.close(fd)` there would raise its
    OWN `OSError: Bad file descriptor`, masking the real error (mirrors
    `scripts/venue/polymarket_us_auth_smoke.py::_write_private_text`'s own
    fix for the identical shape)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(result.to_dict(), sort_keys=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        handle = os.fdopen(fd, "a", encoding="utf-8")
    except BaseException:
        os.close(fd)
        raise
    with handle:
        handle.write(line)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def read_replay_results(path: Path) -> tuple[ReplayResult, ...]:
    """Parse `replay_results.jsonl`.

    Refuses on an unrecognised `schema_version` (naming path/line/version,
    exactly like H0) or a duplicate TERMINAL key. Repeated `BLOCKED` rows
    under the identical key are expected and never flagged (module
    docstring).
    """
    records: list[ReplayResult] = []
    seen_terminal: set[ResultKey] = set()
    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            payload = json.loads(line)
            version = payload.get("schema_version")
            if version != REPLAY_RESULTS_SCHEMA_VERSION:
                raise UnknownReplayResultSchemaError(
                    f"{path}:{line_number}: unknown replay_results schema_version "
                    f"{version!r} (expected {REPLAY_RESULTS_SCHEMA_VERSION})"
                )
            record = ReplayResult.from_dict(payload)
            key = result_key(record)
            if record.outcome in _TERMINAL_OUTCOMES:
                if key in seen_terminal:
                    raise DuplicateReplayResultError(
                        f"{path}:{line_number}: duplicate terminal result for key {key!r}"
                    )
                seen_terminal.add(key)
            records.append(record)
    return tuple(records)


def terminal_keys(results: Sequence[ReplayResult]) -> frozenset[ResultKey]:
    """Every queue key that already has a TERMINAL row -- what target
    selection must never reselect (R1)."""
    return frozenset(result_key(r) for r in results if r.outcome in _TERMINAL_OUTCOMES)


def is_fee_schedule_void(result: ReplayResult) -> bool:
    """`True` iff `result.refusal_counts` records at least one
    `fee_schedule_mismatch` refusal (AUD-09b amendment fee-regime plan,
    Phase 1). Checked for ANY `outcome` -- including a legacy `COMPLETED`
    row written before this net existed (e.g. MDW 2026-09-01): the day was
    void the moment the engine ever refused on a fee-schedule mismatch,
    regardless of how the row's own `outcome` was originally classified."""
    return result.refusal_counts.get(FEE_SCHEDULE_MISMATCH_REFUSAL, 0) >= 1
