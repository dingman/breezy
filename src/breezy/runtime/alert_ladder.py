"""Shared re-alert ladder state machine (AUD-04 plan §6 D8, R3 ownership fix).

One state machine, owned here. AUD-04's own frozen-input detector and its
open-position staleness check both drive their alerting through this
module, and AUD-07's `EXIT_CORPUS_FROZEN` / `EXIT_PNL_RECONCILIATION_MISMATCH`
controls IMPORT this module rather than re-implementing or re-specifying the
period-key/streak semantics -- round 3 of the AUD-04 plan review found the
ladder specified twice in prose and implemented twice in two modules with two
latch files, with nothing preventing the two period-key computations from
diverging. See
``docs/plans/backlog/AUDIT_2026-09-21/AUD-04-portfolio-roi-measurement.md``
section 6 D8 for the full specification this module implements.

**What this module does NOT do:** it never emits an alert itself (no
dependency on ``breezy.runtime.health``'s sink machinery), and each consumer
still owns its own latch FILE and its own event names -- only the state
machine and the period keys are shared.

Ladder (consecutive stale runs = ``streak``):

======================  ========  ===========================
Streak                  Severity  Re-emit cadence
======================  ========  ===========================
``< 3``                 --        silent
``3 .. 13``             WARN      once per UTC ISO week
``>= 14``               CRITICAL  once per UTC day
======================  ========  ===========================

Escalation within one streak is one-way: once CRITICAL has been reported for
a streak, the severity never reports back down to WARN without the streak
first clearing to zero (a fresh input -- the caller's job, via
:func:`next_streak`).
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

__all__ = [
    "CRITICAL_STREAK_THRESHOLD",
    "LATCH_SCHEMA_VERSION",
    "WARN_STREAK_THRESHOLD",
    "LadderDecision",
    "LatchState",
    "evaluate_streak",
    "next_streak",
    "read_latch_state",
    "utc_day_key",
    "utc_iso_week_key",
    "write_latch_state",
]

#: Below this consecutive-stale-run count, the ladder is silent.
WARN_STREAK_THRESHOLD: Final[int] = 3

#: At or above this consecutive-stale-run count, the ladder escalates from a
#: weekly WARN to a daily CRITICAL.
CRITICAL_STREAK_THRESHOLD: Final[int] = 14

#: Bumped whenever the persisted latch shape changes. `read_latch_state`
#: treats any other value (or an absent field) as a fresh, streak=0 state --
#: additive-only within a version, same discipline as D7's report schema.
LATCH_SCHEMA_VERSION: Final[int] = 1

_NS_PER_SECOND: Final[int] = 1_000_000_000


@dataclass(frozen=True, slots=True)
class LadderDecision:
    """The verdict for one run.

    ``should_alert is False`` means stay silent -- either the streak is
    below :data:`WARN_STREAK_THRESHOLD`, or this exact ``(severity,
    period_key)`` pair was already alerted (a same-period rerun, including
    across a process restart).
    """

    should_alert: bool
    severity: str | None  # "WARN" | "CRITICAL" | None
    period_key: str | None


@dataclass(frozen=True, slots=True)
class LatchState:
    """Persisted, restart-surviving ladder state.

    One file per consumer -- the shape is shared, the file path and event
    names are not (D8's ownership rule).
    """

    schema_version: int
    streak: int
    last_alert_severity: str | None
    last_alert_period_key: str | None


def utc_day_key(now_ns: int) -> str:
    """``YYYY-MM-DD`` UTC calendar day for ``now_ns``."""
    dt = datetime.fromtimestamp(now_ns / _NS_PER_SECOND, tz=UTC)
    return dt.strftime("%Y-%m-%d")


def utc_iso_week_key(now_ns: int) -> str:
    """``GGGG-Www`` UTC ISO-8601 week for ``now_ns``.

    Uses ``date.isocalendar()`` deliberately, not ``dt.year``: the ISO week
    number and ISO year can differ from the calendar year at the
    year boundary (e.g. 2025-12-29 is a Monday in ISO week 1 of ISO-year
    2026), and a naive ``f"{dt.year}-W{dt.isocalendar()[1]}"`` gets that case
    wrong.
    """
    dt = datetime.fromtimestamp(now_ns / _NS_PER_SECOND, tz=UTC)
    iso_year, iso_week, _ = dt.isocalendar()
    return f"{iso_year:04d}-W{iso_week:02d}"


def next_streak(*, is_fresh: bool, previous_streak: int) -> int:
    """The next persisted streak count, given whether THIS run's input is
    fresh (``days_since_newest_input <= 3`` or equivalent, entirely the
    caller's domain-specific test). A fresh run resets to zero (D8's clear
    condition); a stale run increments."""
    if is_fresh:
        return 0
    return previous_streak + 1


def evaluate_streak(
    *,
    streak: int,
    last_alert_severity: str | None,
    last_alert_period_key: str | None,
    now_ns: int,
) -> LadderDecision:
    """Pure decision function -- reads and writes nothing.

    ``streak`` is the count already computed for THIS run (typically via
    :func:`next_streak`); ``last_alert_severity``/``last_alert_period_key``
    are what the latch persisted from the previous run. The caller is
    responsible for persisting the returned decision itself (via
    :func:`write_latch_state`) and for actually emitting the alert through
    its own sink.
    """
    if streak < WARN_STREAK_THRESHOLD:
        return LadderDecision(should_alert=False, severity=None, period_key=None)

    if streak >= CRITICAL_STREAK_THRESHOLD:
        severity = "CRITICAL"
    else:
        severity = "WARN"

    # One-way escalation: a streak that has already reported CRITICAL never
    # reports back down to WARN (guards against a caller passing an
    # inconsistent streak/latch pair, not merely against the ordinary
    # monotonic-streak case, which never triggers this branch on its own).
    if last_alert_severity == "CRITICAL" and severity == "WARN":
        severity = "CRITICAL"

    period_key = utc_day_key(now_ns) if severity == "CRITICAL" else utc_iso_week_key(now_ns)

    already_alerted = last_alert_severity == severity and last_alert_period_key == period_key
    return LadderDecision(
        should_alert=not already_alerted,
        severity=severity,
        period_key=period_key,
    )


def read_latch_state(path: Path) -> LatchState:
    """Read the persisted ladder state.

    A missing file, invalid JSON, an unrecognised `schema_version`, or any
    field of the wrong shape all return a fresh state (``streak=0``, no
    prior alert) rather than raising -- D8: "a missing or unparseable latch
    file is treated as ``streak = 0`` and re-alerts on the next qualifying
    run (fail-loud, never fail-silent)." Fail-loud here means the ladder
    starts counting again immediately, not that this function raises.
    """
    fresh = LatchState(
        schema_version=LATCH_SCHEMA_VERSION,
        streak=0,
        last_alert_severity=None,
        last_alert_period_key=None,
    )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return fresh
    if not isinstance(data, dict) or data.get("schema_version") != LATCH_SCHEMA_VERSION:
        return fresh
    streak_raw = data.get("streak")
    if not isinstance(streak_raw, int) or isinstance(streak_raw, bool):
        return fresh
    last_alert_severity = data.get("last_alert_severity")
    last_alert_period_key = data.get("last_alert_period_key")
    if last_alert_severity is not None and not isinstance(last_alert_severity, str):
        return fresh
    if last_alert_period_key is not None and not isinstance(last_alert_period_key, str):
        return fresh
    return LatchState(
        schema_version=LATCH_SCHEMA_VERSION,
        streak=streak_raw,
        last_alert_severity=last_alert_severity,
        last_alert_period_key=last_alert_period_key,
    )


def write_latch_state(path: Path, state: LatchState) -> None:
    """Durable, atomic write (temp file + ``os.replace``), mirroring the
    write-then-rename idiom already used for the health snapshot
    (``health.py``'s ``_write_snapshot_atomically``)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        {
            "schema_version": state.schema_version,
            "streak": state.streak,
            "last_alert_severity": state.last_alert_severity,
            "last_alert_period_key": state.last_alert_period_key,
        },
        sort_keys=True,
    ).encode("utf-8")
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=".alert-ladder-", suffix=".tmp")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
