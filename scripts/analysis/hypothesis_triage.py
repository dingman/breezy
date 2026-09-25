#!/usr/bin/env python3
"""AUD-18 triage runner (§6.4 / §7 steps 3–4).

I/O wrapper around `breezy.analysis.hypothesis_ledger`. Reads the hypothesis
ledger plus AUD-09's `replay_sufficiency.jsonl` and `replay_results.jsonl`
(read-only) and, only when a pre-registered SINGLE_LOOK is due, the per-day
scored-trial store AUD-09 already writes. Writes only under
`<derived_root>/hypothesis/`.

An empty ledger, or a ledger whose records are all zero-look
(`REJECTED` disposition, `UNDERPOWERED_NOT_REGISTERED`), is a clean success:
exit 0, no alert. That is the programme's honest state when nothing has been
registered to take a look. A missing or unreadable AUD-09 artefact, or an
unknown schema version, is a failure: one CRITICAL alert, then a non-zero exit.

Never run against the real derived directory from a test. Pass `--derived-root`.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import re
import sys
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path

from breezy.analysis.hypothesis_ledger import (
    HYPOTHESIS_LEDGER_SCHEMA_VERSION,
    HypothesisLedgerRecordError,
    HypothesisLook,
    HypothesisRecord,
    UnknownHypothesisLedgerSchemaError,
    evaluate_pooled_pnl_veto,
    filter_zero_take_station_days,
    is_variant_eligible,
    max_single_day_leg_share,
    pooled_net_pnl_per_contract,
    read_hypothesis_ledger,
    station_day_mean_x,
    write_hypothesis_ledger,
)
from breezy.analysis.replay_results import (
    REPLAY_VALIDITY,
    ReplayResult,
    UnknownReplayResultSchemaError,
    read_replay_results,
)
from breezy.analysis.replay_sufficiency import (
    UnknownReplaySufficiencySchemaError,
    is_replayable_whole_day,
    read_replay_sufficiency,
)
from breezy.persistence.realized_draws import load_realized_draws
from breezy.runtime.health import AlertPayload, emit_alert, resolve_alert_sink
from breezy.settlement.current_rung_hold_v2 import (
    CombinedDraw,
    combine_station_day,
    score_combined,
)

__all__ = [
    "EVALUATION_SCHEMA_VERSION",
    "AlreadyLookedRefusal",
    "DuplicateHypothesisLookError",
    "UnknownEvaluationSchemaError",
    "ZeroLookRefusal",
    "append_hypothesis_evaluation",
    "assert_look_permitted",
    "main",
    "read_hypothesis_evaluations",
]

EVALUATION_SCHEMA_VERSION: int = HYPOTHESIS_LEDGER_SCHEMA_VERSION
_BOOTSTRAP_ITERATIONS: int = 400
_BOOTSTRAP_SEED: int = 20260925
_DEFAULT_HORIZON_DAYS: int = 21
#: Shared schema for every per-hypothesis one-shot alert state file (see
#: `_alert_state_path`/`_read_alert_state`/`_write_alert_state`). Each alert
#: KIND (`_HORIZON_ALERT_KIND`, `_MISSING_STRATUM_BINDING_ALERT_KIND`) gets
#: its own file, so the two kinds can never suppress each other -- only the
#: on-disk shape is shared.
_ALERT_STATE_SCHEMA_VERSION: int = 1
_HORIZON_ALERT_KIND: str = "horizon"
_MISSING_STRATUM_BINDING_ALERT_KIND: str = "missing_stratum_binding"
_MISSING_STRATUM_BINDING: str = "MISSING_STRATUM_BINDING"
_ACTIVE_STATUSES = frozenset(
    {"REGISTERED", "PARKED_INSUFFICIENT_DATA", "EVALUATING"}
)
_DERIVED_ROOT_ENV_VAR = "BREEZY_DERIVED_ROOT"
_PATH_RE = re.compile(r"/[^\\s]*")


class DuplicateHypothesisLookError(ValueError):
    """A second `(hypothesis_id, variant_id, looked_at)` row is a hard error."""


class UnknownEvaluationSchemaError(ValueError):
    """`hypothesis_evaluations.jsonl` carries an unrecognised schema_version."""


class ZeroLookRefusal(ValueError):
    """A look against a zero-look record is refused and appends nothing."""


class AlreadyLookedRefusal(ValueError):
    """SINGLE_LOOK evaluates a variant exactly once."""


class _TriageFailure(Exception):
    """A scored failure that must page exactly once and exit non-zero."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


@dataclass(frozen=True, slots=True)
class _Args:
    derived_root: Path
    as_of: str
    horizon_days: int
    alert_log: Path | None
    attempt_hypothesis_id: str | None


def default_derived_root() -> Path:
    override = os.environ.get(_DERIVED_ROOT_ENV_VAR)
    if override:
        return Path(override).expanduser()
    return Path.home() / ".local" / "share" / "breezy" / "derived"


def ledger_path(derived_root: Path) -> Path:
    return derived_root / "hypothesis" / "hypothesis_ledger.jsonl"


def evaluations_path(derived_root: Path) -> Path:
    return derived_root / "hypothesis" / "hypothesis_evaluations.jsonl"


def _alert_state_path(derived_root: Path, *, kind: str) -> Path:
    return derived_root / "hypothesis" / f"{kind}_alerts.json"


def _sufficiency_path(derived_root: Path) -> Path:
    return derived_root / "replay" / "replay_sufficiency.jsonl"


def _results_path(derived_root: Path) -> Path:
    return derived_root / "replay" / "replay_results.jsonl"


def _store_dir(derived_root: Path, station: str, climate_day: str, lag_minutes: int) -> Path:
    return (
        derived_root
        / "paper_replay"
        / "scored_trials"
        / "v3"
        / station
        / climate_day
        / f"lag_{lag_minutes}"
    )


def _public_detail(exc: BaseException) -> str:
    """Alert text with filesystem paths removed. `AlertPayload.detail` must
    not carry an absolute path."""
    return _PATH_RE.sub("<path>", " ".join(str(exc).split()))


def _look_dict(look: HypothesisLook) -> dict[str, object]:
    return {
        "schema_version": EVALUATION_SCHEMA_VERSION,
        "hypothesis_id": look.hypothesis_id,
        "variant_id": look.variant_id,
        "looked_at": look.looked_at,
        "n_station_days": look.n_station_days,
        "n_station_days_observed": look.n_station_days_observed,
        "n_station_days_with_takes": look.n_station_days_with_takes,
        "take_rate": look.take_rate,
        "ci_lower": look.ci_lower,
        "ci_upper": look.ci_upper,
        "pooled_net_pnl_per_contract": look.pooled_net_pnl_per_contract,
        "max_single_day_leg_share": look.max_single_day_leg_share,
        "veto_reason": look.veto_reason,
        "alpha_spent_cumulative": look.alpha_spent_cumulative,
        "is_terminal_look": look.is_terminal_look,
    }


def _look_from_payload(payload: Mapping[str, object]) -> HypothesisLook:
    return HypothesisLook(
        hypothesis_id=str(payload["hypothesis_id"]),
        variant_id=str(payload["variant_id"]),
        looked_at=str(payload["looked_at"]),
        n_station_days=int(payload["n_station_days"]),  # type: ignore[call-overload]
        n_station_days_observed=int(payload["n_station_days_observed"]),  # type: ignore[call-overload]
        n_station_days_with_takes=int(payload["n_station_days_with_takes"]),  # type: ignore[call-overload]
        take_rate=float(payload["take_rate"]),  # type: ignore[arg-type]
        ci_lower=float(payload["ci_lower"]),  # type: ignore[arg-type]
        ci_upper=float(payload["ci_upper"]),  # type: ignore[arg-type]
        pooled_net_pnl_per_contract=float(payload["pooled_net_pnl_per_contract"]),  # type: ignore[arg-type]
        max_single_day_leg_share=float(payload["max_single_day_leg_share"]),  # type: ignore[arg-type]
        veto_reason=payload["veto_reason"],  # type: ignore[arg-type]
        alpha_spent_cumulative=float(payload["alpha_spent_cumulative"]),  # type: ignore[arg-type]
        is_terminal_look=bool(payload["is_terminal_look"]),
    )


def _atomic_write_lines(path: Path, lines: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            for line in lines:
                handle.write(line)
                if not line.endswith("\n"):
                    handle.write("\n")
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def _read_alert_state(path: Path, *, label: str) -> frozenset[str]:
    """Read durable one-shot state for a per-hypothesis advisory alert.

    Missing state means no alert has been recorded yet for this KIND.
    Corrupt state fails loud so the unit does not oscillate between silent
    suppression and an uncontrolled re-alert storm.

    Shared by every alert kind that pages at most once per hypothesis
    (PARKED horizon stall, MISSING_STRATUM_BINDING) -- `label` only affects
    the failure message; each kind's `path` (see `_alert_state_path`) is
    distinct, so the two kinds can never suppress each other.
    """
    if not path.exists():
        return frozenset()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise _TriageFailure(f"corrupt {label} alert state: {_public_detail(exc)}") from exc
    except OSError as exc:
        raise _TriageFailure(f"unreadable {label} alert state: {_public_detail(exc)}") from exc
    if not isinstance(payload, Mapping):
        raise _TriageFailure(f"corrupt {label} alert state: expected JSON object")
    version = payload.get("schema_version")
    if version != _ALERT_STATE_SCHEMA_VERSION:
        raise _TriageFailure(
            f"unknown {label} alert state schema_version "
            f"{version!r} (expected {_ALERT_STATE_SCHEMA_VERSION})"
        )
    ids = payload.get("alerted_hypothesis_ids")
    if not isinstance(ids, list) or not all(isinstance(item, str) for item in ids):
        raise _TriageFailure(
            f"corrupt {label} alert state: alerted_hypothesis_ids must be a list of strings"
        )
    return frozenset(ids)


def _write_alert_state(path: Path, alerted: frozenset[str]) -> None:
    payload = {
        "schema_version": _ALERT_STATE_SCHEMA_VERSION,
        "alerted_hypothesis_ids": sorted(alerted),
    }
    _atomic_write_lines(path, [json.dumps(payload, sort_keys=True)])


def read_hypothesis_evaluations(path: Path) -> tuple[HypothesisLook, ...]:
    """Parse `hypothesis_evaluations.jsonl`. Unknown schema or a duplicate
    `(hypothesis_id, variant_id, looked_at)` is a hard error."""
    if not path.exists():
        return ()
    looks: list[HypothesisLook] = []
    seen: set[tuple[str, str, str]] = set()
    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            payload = json.loads(line)
            version = payload.get("schema_version")
            if version != EVALUATION_SCHEMA_VERSION:
                raise UnknownEvaluationSchemaError(
                    f"unknown hypothesis_evaluations schema_version {version!r} "
                    f"(expected {EVALUATION_SCHEMA_VERSION}) at line {line_number}"
                )
            look = _look_from_payload(payload)
            key = (look.hypothesis_id, look.variant_id, look.looked_at)
            if key in seen:
                raise DuplicateHypothesisLookError(
                    f"duplicate look {key[0]!r} variant={key[1]!r} looked_at={key[2]!r} "
                    f"at line {line_number}"
                )
            seen.add(key)
            looks.append(look)
    return tuple(looks)


def append_hypothesis_evaluation(path: Path, look: HypothesisLook) -> None:
    """Atomic whole-file rewrite that only adds `look`. A duplicate key
    raises and leaves the previous file untouched."""
    existing = read_hypothesis_evaluations(path) if path.exists() else ()
    key = (look.hypothesis_id, look.variant_id, look.looked_at)
    if any(
        (item.hypothesis_id, item.variant_id, item.looked_at) == key for item in existing
    ):
        raise DuplicateHypothesisLookError(
            f"duplicate look {key[0]!r} variant={key[1]!r} looked_at={key[2]!r}"
        )
    lines = [
        json.dumps(_look_dict(item), sort_keys=True) for item in (*existing, look)
    ]
    _atomic_write_lines(path, lines)


def assert_look_permitted(
    record: HypothesisRecord,
    looks: Sequence[HypothesisLook],
    variant_id: str,
) -> None:
    """Hard refusal. The nightly batch catches `AlreadyLookedRefusal` and
    records `skip_reason=ALREADY_LOOKED` instead of failing the unit; an
    explicit attempt, and any zero-look record, is not that path."""
    if record.is_zero_look:
        raise ZeroLookRefusal(
            f"zero-look record {record.hypothesis_id!r} refuses a look"
        )
    if record.look_policy != "SINGLE_LOOK":
        raise ZeroLookRefusal(
            f"look_policy {record.look_policy!r} is not SINGLE_LOOK "
            f"for {record.hypothesis_id!r}"
        )
    if not is_variant_eligible(record, looks, variant_id):
        raise AlreadyLookedRefusal(
            f"variant {variant_id!r} of {record.hypothesis_id!r} is ALREADY_LOOKED"
        )


def _variant_ids(record: HypothesisRecord) -> tuple[str, ...]:
    return tuple(f"v{index}" for index in range(1, record.k_variants + 1))


def _passes_c_validity(row: ReplayResult) -> bool:
    return row.validity != REPLAY_VALIDITY and row.params_match is True


def cluster_bootstrap_ci(
    means: Sequence[float],
    *,
    alpha: float,
    iterations: int = _BOOTSTRAP_ITERATIONS,
    seed: int = _BOOTSTRAP_SEED,
) -> tuple[float, float]:
    """Station-day cluster bootstrap of the mean. Whole station-days are
    resampled, B=400, percentile interval at `alpha` (one-sided lower) and
    `1 - alpha` (upper). A one-day sample is the point itself."""
    n = len(means)
    if n <= 0:
        raise ValueError("cluster bootstrap is undefined for an empty sample")
    rng = random.Random(seed)
    stats = sorted(
        sum(means[rng.randrange(n)] for _ in range(n)) / n for _ in range(iterations)
    )
    lower_index = min(iterations - 1, max(0, math.ceil(alpha * iterations) - 1))
    upper_index = min(iterations - 1, max(0, math.floor((1.0 - alpha) * iterations) - 1))
    if upper_index < lower_index:
        upper_index = iterations - 1
    return stats[lower_index], stats[upper_index]


def _draw_for_station_day(
    derived_root: Path,
    *,
    station: str,
    climate_day: str,
    lag_minutes: int,
) -> CombinedDraw:
    directory = _store_dir(derived_root, station, climate_day, lag_minutes)
    if not directory.is_dir():
        raise _TriageFailure("absent AUD-09 artefact: scored-trial store for a with-takes day")
    realized = load_realized_draws(directory)
    if not realized.stratum_rows:
        raise _TriageFailure("absent AUD-09 artefact: scored-trial store has no admissible draw")
    # One replay output directory is one station-day. Re-run the admission
    # primitive here so this module calls it, rather than only reaching it
    # through `load_realized_draws`.
    return combine_station_day(realized.stratum_rows)


def _terminal_status(record: HypothesisRecord, looks: Sequence[HypothesisLook]) -> str | None:
    mine = [look for look in looks if look.hypothesis_id == record.hypothesis_id]
    looked = {look.variant_id for look in mine}
    if len(looked) < record.k_variants:
        return None
    if any(look.ci_lower > 0 and look.veto_reason == "NONE" for look in mine):
        return "CONFIRMED"
    if any(look.ci_lower > 0 and look.veto_reason != "NONE" for look in mine):
        return "PRIMARY_PASSED_PNL_VETO"
    return "ABANDONED_CAP_EXHAUSTED"


def _replace_status(
    records: Sequence[HypothesisRecord], updated: HypothesisRecord
) -> tuple[HypothesisRecord, ...]:
    return tuple(
        updated if record.hypothesis_id == updated.hypothesis_id else record
        for record in records
    )


def _write_handoff(derived_root: Path, look: HypothesisLook) -> None:
    path = derived_root / "hypothesis" / f"handoff_{look.hypothesis_id}.json"
    payload = {
        "hypothesis_id": look.hypothesis_id,
        "variant_id": look.variant_id,
        "looked_at": look.looked_at,
        "ci_lower": look.ci_lower,
        "ci_upper": look.ci_upper,
        "take_rate": look.take_rate,
        "pooled_net_pnl_per_contract": look.pooled_net_pnl_per_contract,
    }
    _atomic_write_lines(path, [json.dumps(payload, sort_keys=True)])


def _emit(
    *,
    alert_log: Path | None,
    severity: str,
    event: str,
    detail: str,
) -> None:
    payload = AlertPayload(severity=severity, event=event, site="hypothesis", detail=detail)
    if alert_log is not None:
        alert_log.parent.mkdir(parents=True, exist_ok=True)
        with alert_log.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload.to_dict(), sort_keys=True))
            handle.write("\n")
    emit_alert(resolve_alert_sink(), payload)


def _load_aud09(derived_root: Path) -> tuple[object, tuple[ReplayResult, ...]]:
    sufficiency_path = _sufficiency_path(derived_root)
    results_path = _results_path(derived_root)
    try:
        sufficiency = read_replay_sufficiency(sufficiency_path)
        results = read_replay_results(results_path)
    except FileNotFoundError as exc:
        raise _TriageFailure("absent AUD-09 artefact") from exc
    except OSError as exc:
        raise _TriageFailure("unreadable AUD-09 artefact") from exc
    except (UnknownReplaySufficiencySchemaError, UnknownReplayResultSchemaError) as exc:
        raise _TriageFailure(_public_detail(exc)) from exc
    return sufficiency, results


def _completed_on_whole_days(
    sufficiency: Sequence[object], results: Sequence[ReplayResult]
) -> list[ReplayResult]:
    whole = {
        (row.station, row.climate_day)  # type: ignore[attr-defined]
        for row in sufficiency
        if is_replayable_whole_day(row)  # type: ignore[arg-type]
    }
    return [
        row
        for row in results
        if row.outcome == "COMPLETED" and (row.station, row.climate_day) in whole
    ]


def _horizon_reached(record: HypothesisRecord, *, as_of: str, horizon_days: int) -> bool:
    parked_for = (date.fromisoformat(as_of) - date.fromisoformat(record.registered_at)).days
    return parked_for > horizon_days


def _has_registered_draw_binding(record: HypothesisRecord, variant_id: str) -> bool:
    """Current schema has no hypothesis/variant -> stratum/draw-population key.

    The strict ledger reader accepts exactly the fields on `HypothesisRecord`;
    none names a stratum, station set, replay strategy/lag, or variant-specific
    draw population. Until a future schema adds that field, every look-taking
    record fails closed instead of consuming the global replay corpus.
    """
    _ = (record, variant_id)
    return False


def _skip(record: HypothesisRecord, variant_id: str, reason: str) -> None:
    print(
        f"SKIP hypothesis_id={record.hypothesis_id} variant_id={variant_id} "
        f"skip_reason={reason}"
    )


def _triage_record(
    record: HypothesisRecord,
    *,
    derived_root: Path,
    looks: Sequence[HypothesisLook],
    completed: Sequence[ReplayResult],
    as_of: str,
    horizon_days: int,
) -> tuple[HypothesisRecord, HypothesisLook | None, str | None]:
    """Returns `(updated_record, new_look_or_none, alert_event_or_none)`.

    `alert_event` is `HYPOTHESIS_ABANDONED_CAP_EXHAUSTED` or
    `HYPOTHESIS_TRIAGE_HORIZON_STALL`. CRITICAL failures raise `_TriageFailure`.
    """
    variants = _variant_ids(record)
    eligible = [
        variant_id
        for variant_id in variants
        if is_variant_eligible(record, looks, variant_id)
    ]
    if not eligible:
        for variant_id in variants:
            _skip(record, variant_id, "ALREADY_LOOKED")
        rolled = _terminal_status(record, looks)
        if rolled is not None and rolled != record.status:
            return replace(record, status=rolled), None, (
                "HYPOTHESIS_ABANDONED_CAP_EXHAUSTED"
                if rolled == "ABANDONED_CAP_EXHAUSTED"
                else None
            )
        return record, None, None

    if _horizon_reached(record, as_of=as_of, horizon_days=horizon_days):
        return record, None, "HYPOTHESIS_TRIAGE_HORIZON_STALL"

    missing_binding = [
        variant_id
        for variant_id in eligible
        if not _has_registered_draw_binding(record, variant_id)
    ]
    if missing_binding:
        for variant_id in missing_binding:
            _skip(record, variant_id, _MISSING_STRATUM_BINDING)
        return record, None, "HYPOTHESIS_TRIAGE_MISSING_STRATUM_BINDING"

    if completed and any(not _passes_c_validity(row) for row in completed):
        for variant_id in variants:
            _skip(record, variant_id, "C_VALIDITY")
        return record, None, None

    by_day: dict[tuple[str, str], list[ReplayResult]] = {}
    for row in completed:
        if not _passes_c_validity(row):
            continue
        by_day.setdefault((row.station, row.climate_day), []).append(row)
    ordered_keys = sorted(by_day)
    fills = [max(row.fills for row in by_day[key]) for key in ordered_keys]
    counted = filter_zero_take_station_days(fills)
    with_takes = [key for key, count in zip(ordered_keys, fills, strict=True) if count >= 1]

    if counted.n_station_days_with_takes < record.min_station_days:
        updated = record
        if record.status != "PARKED_INSUFFICIENT_DATA":
            updated = replace(record, status="PARKED_INSUFFICIENT_DATA")
        event = None
        if _horizon_reached(updated, as_of=as_of, horizon_days=horizon_days):
            event = "HYPOTHESIS_TRIAGE_HORIZON_STALL"
        return updated, None, event

    variant_id = eligible[0]
    assert_look_permitted(record, looks, variant_id)
    draws = tuple(
        _draw_for_station_day(
            derived_root,
            station=station,
            climate_day=climate_day,
            lag_minutes=max(row.lag_minutes for row in by_day[(station, climate_day)]),
        )
        for station, climate_day in with_takes
    )
    score_combined(draws)
    means = tuple(station_day_mean_x(draw) for draw in draws)
    ci_lower, ci_upper = cluster_bootstrap_ci(means, alpha=record.per_variant_alpha)
    pooled = pooled_net_pnl_per_contract(draws)
    share = max_single_day_leg_share(draws)
    veto = evaluate_pooled_pnl_veto(
        primary_excludes_zero=ci_lower > 0,
        pooled_net_pnl_per_contract=pooled,
        max_single_day_leg_share=share,
        max_single_day_leg_share_cap=record.max_single_day_leg_share_cap,
    )
    look = HypothesisLook(
        hypothesis_id=record.hypothesis_id,
        variant_id=variant_id,
        looked_at=as_of,
        n_station_days=counted.n_station_days_with_takes,
        n_station_days_observed=counted.n_station_days_observed,
        n_station_days_with_takes=counted.n_station_days_with_takes,
        take_rate=counted.take_rate,
        ci_lower=ci_lower,
        ci_upper=ci_upper,
        pooled_net_pnl_per_contract=pooled,
        max_single_day_leg_share=share,
        veto_reason=veto.veto_reason,
        alpha_spent_cumulative=record.per_variant_alpha,
        is_terminal_look=True,
    )
    rolled = _terminal_status(record, (*looks, look))
    status = rolled if rolled is not None else "EVALUATING"
    event = "HYPOTHESIS_ABANDONED_CAP_EXHAUSTED" if status == "ABANDONED_CAP_EXHAUSTED" else None
    print(
        f"LOOK hypothesis_id={record.hypothesis_id} variant_id={variant_id} status={status}"
    )
    return replace(record, status=status), look, event


def run(args: _Args) -> int:
    path = ledger_path(args.derived_root)
    if not path.exists():
        if args.attempt_hypothesis_id is not None:
            raise _TriageFailure(
                f"hypothesis_id {args.attempt_hypothesis_id!r} is not registered"
            )
        print("CLEAN no look-taking hypothesis")
        return 0

    records = read_hypothesis_ledger(path)
    if args.attempt_hypothesis_id is not None:
        match = next(
            (record for record in records if record.hypothesis_id == args.attempt_hypothesis_id),
            None,
        )
        if match is None:
            raise _TriageFailure(
                f"hypothesis_id {args.attempt_hypothesis_id!r} is not registered"
            )
        looks = read_hypothesis_evaluations(evaluations_path(args.derived_root))
        assert_look_permitted(match, looks, _variant_ids(match)[0])

    look_taking = [record for record in records if not record.is_zero_look]
    if args.attempt_hypothesis_id is not None:
        look_taking = [
            record
            for record in look_taking
            if record.hypothesis_id == args.attempt_hypothesis_id
        ]
    if not look_taking:
        print("CLEAN no look-taking hypothesis")
        return 0

    looks = read_hypothesis_evaluations(evaluations_path(args.derived_root))
    if all(
        not is_variant_eligible(record, looks, variant_id)
        for record in look_taking
        for variant_id in _variant_ids(record)
    ):
        updated_records = records
        for record in look_taking:
            for variant_id in _variant_ids(record):
                _skip(record, variant_id, "ALREADY_LOOKED")
            rolled = _terminal_status(record, looks)
            if rolled is None or rolled == record.status:
                continue
            updated_records = _replace_status(updated_records, replace(record, status=rolled))
            if rolled == "CONFIRMED":
                confirming = next(
                    look
                    for look in looks
                    if look.hypothesis_id == record.hypothesis_id
                    and look.ci_lower > 0
                    and look.veto_reason == "NONE"
                )
                _write_handoff(args.derived_root, confirming)
            elif rolled == "ABANDONED_CAP_EXHAUSTED":
                _emit(
                    alert_log=args.alert_log,
                    severity="WARN",
                    event="HYPOTHESIS_ABANDONED_CAP_EXHAUSTED",
                    detail=(
                        f"hypothesis {record.hypothesis_id} disposition "
                        "ABANDONED_CAP_EXHAUSTED"
                    ),
                )
        if updated_records != records:
            write_hypothesis_ledger(path, updated_records)
        return 0

    active = [record for record in look_taking if record.status in _ACTIVE_STATUSES]
    _sufficiency, results = _load_aud09(args.derived_root)
    completed = _completed_on_whole_days(_sufficiency, results)  # type: ignore[arg-type]
    horizon_state_path = _alert_state_path(args.derived_root, kind=_HORIZON_ALERT_KIND)
    horizon_alerted = _read_alert_state(horizon_state_path, label="horizon")
    binding_state_path = _alert_state_path(
        args.derived_root, kind=_MISSING_STRATUM_BINDING_ALERT_KIND
    )
    binding_alerted = _read_alert_state(binding_state_path, label="missing stratum binding")
    updated_records = records
    for record in active:
        updated, new_look, event = _triage_record(
            record,
            derived_root=args.derived_root,
            looks=looks,
            completed=completed,
            as_of=args.as_of,
            horizon_days=args.horizon_days,
        )
        if new_look is not None:
            append_hypothesis_evaluation(evaluations_path(args.derived_root), new_look)
            looks = (*looks, new_look)
            if updated.status == "CONFIRMED":
                _write_handoff(args.derived_root, new_look)
        if updated != record:
            updated_records = _replace_status(updated_records, updated)
        if event == "HYPOTHESIS_TRIAGE_HORIZON_STALL":
            if record.hypothesis_id not in horizon_alerted:
                _emit(
                    alert_log=args.alert_log,
                    severity="WARN",
                    event=event,
                    detail=(
                        f"hypothesis {record.hypothesis_id} stayed PARKED_INSUFFICIENT_DATA "
                        f"past the {args.horizon_days}-day horizon"
                    ),
                )
                horizon_alerted = frozenset((*horizon_alerted, record.hypothesis_id))
                _write_alert_state(horizon_state_path, horizon_alerted)
        elif event == "HYPOTHESIS_TRIAGE_MISSING_STRATUM_BINDING":
            if record.hypothesis_id not in binding_alerted:
                _emit(
                    alert_log=args.alert_log,
                    severity="WARN",
                    event=event,
                    detail=(
                        f"hypothesis {record.hypothesis_id} skipped: "
                        f"{_MISSING_STRATUM_BINDING}; registered schema has no "
                        "hypothesis/variant stratum draw-population binding"
                    ),
                )
                binding_alerted = frozenset((*binding_alerted, record.hypothesis_id))
                _write_alert_state(binding_state_path, binding_alerted)
        elif event == "HYPOTHESIS_ABANDONED_CAP_EXHAUSTED":
            _emit(
                alert_log=args.alert_log,
                severity="WARN",
                event=event,
                detail=(
                    f"hypothesis {record.hypothesis_id} disposition "
                    "ABANDONED_CAP_EXHAUSTED"
                ),
            )
    if updated_records != records:
        write_hypothesis_ledger(path, updated_records)
    return 0


def _parse(argv: Sequence[str]) -> _Args:
    parser = argparse.ArgumentParser(description="AUD-18 hypothesis triage")
    parser.add_argument("--derived-root", type=Path, default=None)
    parser.add_argument("--as-of", default=date.today().isoformat())
    parser.add_argument("--horizon-days", type=int, default=_DEFAULT_HORIZON_DAYS)
    parser.add_argument("--alert-log", type=Path, default=None)
    parser.add_argument("--attempt-hypothesis-id", default=None)
    namespace = parser.parse_args(list(argv))
    derived = namespace.derived_root if namespace.derived_root is not None else default_derived_root()
    return _Args(
        derived_root=derived,
        as_of=str(namespace.as_of),
        horizon_days=int(namespace.horizon_days),
        alert_log=namespace.alert_log,
        attempt_hypothesis_id=namespace.attempt_hypothesis_id,
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse(sys.argv[1:] if argv is None else argv)
    try:
        return run(args)
    except _TriageFailure as exc:
        _emit(
            alert_log=args.alert_log,
            severity="CRITICAL",
            event="HYPOTHESIS_TRIAGE_FAILED",
            detail=exc.detail,
        )
        print(exc.detail, file=sys.stderr)
        return 1
    except (
        UnknownHypothesisLedgerSchemaError,
        UnknownEvaluationSchemaError,
        HypothesisLedgerRecordError,
        DuplicateHypothesisLookError,
        json.JSONDecodeError,
        OSError,
        ZeroLookRefusal,
        AlreadyLookedRefusal,
    ) as exc:
        _emit(
            alert_log=args.alert_log,
            severity="CRITICAL",
            event="HYPOTHESIS_TRIAGE_FAILED",
            detail=_public_detail(exc),
        )
        print(_public_detail(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
