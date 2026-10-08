"""Pure deferral-stall streak state machine for `quote_tape_ingest_cli` (EDGE-6 6f).

`run()` (`quote_tape_ingest_cli.py`) exits 0 on any deferral by contract --
correctly, since a deferred unit retries next run (ING-2 S2). That means a
deferral streak that never actually drains is silent: it is live now
(09-27 02:25Z and 02:40Z, 24 instances deferred each, plan §2.6). This
module is the alerting seam that closes that gap without touching the exit
contract's existing meaning: `step()` decides only whether a run's pending
work has crossed a STALL threshold, entirely independent of that run's own
exit code (AC-6f-4/C-5) -- the caller (`quote_tape_ingest_cli.run()`)
combines `alert_due` with the pre-existing failure check under an explicit
precedence (2 > 3 > 4 > 5 > 0).

Deliberately stateful and deliberately minimal, mirroring
`breezy.runtime.ingest_deadline`'s own stance: this module imports nothing
from `quote_tape_ingest_cli` and holds no venue credential, opens no
socket, and touches only its own one dotfile.

Persisted state and the `runs_since_alert` sentinel
-----------------------------------------------------
The persisted shape is exactly `{version, consecutive_runs,
first_deferred_utc, runs_since_alert}` (plan §4 6f). `runs_since_alert`
carries two things the plan folds into one field: whether the CURRENT
streak has ever crossed the stall threshold at all, and (once it has) how
many stalled runs have elapsed since the last alert.

* `_NEVER_STALLED` (-1): pending work exists, but this streak has not yet
  crossed the AC-6f-1 threshold (< 4 consecutive runs, or < 60 minutes
  old). The sentinel is never 0 here specifically so a genuine "0 runs
  since the last alert" (the run immediately after one fires) is never
  confused with "never stalled" -- both would otherwise look identical and
  make the crossing run fire a second, spurious alert one step later.
* `0..15`: the streak IS stalled; this many further stalled runs have
  elapsed since the last alert (0 immediately after an alert fires).
* Crossing into stalled, or reaching 16, both fire `alert_due=True` and
  reset the field to 0 -- AC-6f-2's "every 16th run" (~4h at the unit's
  15-minute cadence) plus the crossing run itself.

Any run with no pending work at all resets straight to `INITIAL_STATE`
(`consecutive_runs=0`), exactly like the deadline module's own instances
counter, and exactly per AC-6f-4(iv): a failure with nothing pending resets
the streak just like a clean run does.

Corrupt or unknown-version state file: fail SAFE, not stuck
--------------------------------------------------------------
`load_state_checked` treats a missing, unreadable, unparseable,
unknown-version, or field-invalid file as a FRESH streak (`INITIAL_STATE`),
logging one value-free WARNING and returning the reason. This is a deliberate
choice between two failure directions:

* Treating corruption as "still stalled" would need an invented count and
  age this module cannot know were ever real -- printing a fabricated
  `DEFERRAL_STALLED` line, or worse, treating it as "already alerted" and
  suppressing every future alert until the file is manually fixed (R6-style
  false-negative risk, but self-inflicted and permanent).
* Treating corruption as "reset" costs only a bounded, honest delay: a
  genuine stall still re-accumulates from zero and alerts again within the
  next 4 runs / 60 minutes -- the SAME bound a first-ever stall takes.

Losing history is preferred because it can never SUPPRESS an alert
forever; only delay one by, at most, one stall window.

That bound holds only for well-formed values, so every field is validated by
exact type and range (never by truthiness or coercion) before `step()` may
consume it. A reset, or a failed save, on a run that has pending work is not
left as a log line: the caller prints ``DEFERRAL_STREAK_RESET reason=<enum>``
and exits 5 so ``OnFailure=`` delivers it (DEFER-STREAK-LOAD). The unit's
``OnFailure=`` leg is journalled and durably queued by the alert sink
(AUT-6 WP1), so the page is delivered or redeliverable, not merely logged.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path

logger = logging.getLogger(__name__)

#: Bumped only on an incompatible on-disk shape change. `load_state` treats
#: any other value (including a missing key) as corrupt -- see the module
#: docstring.
STATE_VERSION = 1

#: `<catalog_root>/.ingest-deferral-streak-v1.json` (AC-6f-6): the catalog
#: root, never `live/` or an instance directory -- one streak per catalog,
#: not per instance. Dotfile, so it is invisible to `ls` and to
#: `iter_feather_files`'s glob, same convention as every other marker this
#: package writes.
STATE_FILENAME = ".ingest-deferral-streak-v1.json"

#: AC-6f-1: a stall alert requires BOTH thresholds on the same run.
STALL_MIN_CONSECUTIVE_RUNS = 4
STALL_MIN_AGE = timedelta(minutes=60)

#: AC-6f-2: re-alert every 16th stalled run (~4h at the unit's 15-minute
#: `*:0/15` cadence) rather than once.
REALERT_EVERY_RUNS = 16

#: Sentinel `runs_since_alert` value meaning "pending, but this streak has
#: never yet crossed the stall threshold" -- see the module docstring.
_NEVER_STALLED = -1


@dataclass(frozen=True)
class DeferralStreakState:
    """Persisted, JSON-round-trippable. See the module docstring."""

    version: int = STATE_VERSION
    consecutive_runs: int = 0
    first_deferred_utc: str | None = None
    runs_since_alert: int = _NEVER_STALLED


#: A run with no pending work at all, or one this module has never seen.
INITIAL_STATE = DeferralStreakState()


def step(
    state: DeferralStreakState, *, pending: bool, now: datetime
) -> tuple[DeferralStreakState, bool]:
    """Advance the streak by exactly one run.

    Independent of the run's own exit code (AC-6f-4/C-5) -- ``pending`` is
    the ONLY input besides the state and the clock. The caller decides the
    actual exit code separately, combining ``alert_due`` with whatever else
    that run found under the plan's precedence (2 > 3 > 4 > 0).

    Returns ``(new_state, alert_due)``. ``alert_due`` is True exactly on
    the run that crosses the AC-6f-1 stall threshold, and again every
    :data:`REALERT_EVERY_RUNS`th run after that while ``pending`` stays
    True (AC-6f-2).
    """
    if not pending:
        return INITIAL_STATE, False

    consecutive_runs = state.consecutive_runs + 1
    first_deferred_utc = state.first_deferred_utc or now.isoformat()
    age = now - datetime.fromisoformat(first_deferred_utc)
    is_stalled = consecutive_runs >= STALL_MIN_CONSECUTIVE_RUNS and age >= STALL_MIN_AGE

    if not is_stalled:
        return (
            replace(
                state,
                version=STATE_VERSION,
                consecutive_runs=consecutive_runs,
                first_deferred_utc=first_deferred_utc,
                runs_since_alert=_NEVER_STALLED,
            ),
            False,
        )

    if state.runs_since_alert == _NEVER_STALLED:
        # The crossing run: the first run of this streak for which BOTH
        # thresholds hold at once.
        return (
            replace(
                state,
                version=STATE_VERSION,
                consecutive_runs=consecutive_runs,
                first_deferred_utc=first_deferred_utc,
                runs_since_alert=0,
            ),
            True,
        )

    runs_since_alert = state.runs_since_alert + 1
    alert_due = runs_since_alert >= REALERT_EVERY_RUNS
    return (
        replace(
            state,
            version=STATE_VERSION,
            consecutive_runs=consecutive_runs,
            first_deferred_utc=first_deferred_utc,
            runs_since_alert=0 if alert_due else runs_since_alert,
        ),
        alert_due,
    )


class StreakResetReason(StrEnum):
    """Why a streak was reset to a fresh start (closed set; value-free).

    ``SAVE_FAILED`` is never returned by :func:`load_state_checked`; the
    caller uses it when persisting the new state fails.
    """

    IO_ERROR = "io_error"
    UNPARSEABLE = "unparseable"
    UNSUPPORTED_VERSION = "unsupported_version"
    MISSING_FIELD = "missing_field"
    BAD_FIELD = "bad_field"
    SAVE_FAILED = "save_failed"


class _FieldError(ValueError):
    """A persisted field failed validation. Carries only the field name."""

    def __init__(self, field: str) -> None:
        super().__init__(field)
        self.field = field


class _UnsupportedVersionError(ValueError):
    """Not a dict, or ``version`` is not :data:`STATE_VERSION`."""


def _require_int_in_range(raw: dict[str, object], field: str, *, lo: int, hi: int | None) -> int:
    value = raw[field]  # KeyError -> MISSING_FIELD
    if type(value) is not int or value < lo or (hi is not None and value >= hi):
        raise _FieldError(field)
    return value


def _require_aware_iso_or_none(raw: dict[str, object], field: str) -> str | None:
    value = raw[field]  # KeyError -> MISSING_FIELD
    if value is None:
        return None
    if type(value) is not str:
        raise _FieldError(field)
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise _FieldError(field) from None
    if parsed.utcoffset() is None:
        raise _FieldError(field)
    return value


def _parse_state(raw: object) -> DeferralStreakState:
    if not isinstance(raw, dict) or raw.get("version") != STATE_VERSION:
        raise _UnsupportedVersionError
    consecutive_runs = _require_int_in_range(raw, "consecutive_runs", lo=0, hi=None)
    first_deferred_utc = _require_aware_iso_or_none(raw, "first_deferred_utc")
    runs_since_alert = _require_int_in_range(
        raw, "runs_since_alert", lo=_NEVER_STALLED, hi=REALERT_EVERY_RUNS
    )
    # Holds for every state `step` emits; closes the "null with runs > 0"
    # silent age-reset path.
    if (consecutive_runs == 0) != (first_deferred_utc is None):
        raise _FieldError("first_deferred_utc")
    return DeferralStreakState(
        version=STATE_VERSION,
        consecutive_runs=consecutive_runs,
        first_deferred_utc=first_deferred_utc,
        runs_since_alert=runs_since_alert,
    )


def load_state_checked(path: Path) -> tuple[DeferralStreakState, StreakResetReason | None]:
    """Read the persisted streak state, failing SAFE on anything unexpected.

    Returns ``(state, None)`` for a valid or missing file (a missing file is
    an ordinary fresh start, no WARN), else ``(INITIAL_STATE, reason)`` after
    exactly one WARNING that names the reason and field, never the value.
    """
    field = "-"
    try:
        if not path.is_file():
            return INITIAL_STATE, None
        return _parse_state(json.loads(path.read_text(encoding="utf-8"))), None
    except OSError:
        reason = StreakResetReason.IO_ERROR
    except (json.JSONDecodeError, UnicodeDecodeError, RecursionError):
        reason = StreakResetReason.UNPARSEABLE
    except _UnsupportedVersionError:
        reason = StreakResetReason.UNSUPPORTED_VERSION
    except KeyError:
        reason = StreakResetReason.MISSING_FIELD
    except _FieldError as exc:
        reason = StreakResetReason.BAD_FIELD
        field = exc.field
    logger.warning(
        "%s is corrupt or unreadable (reason=%s field=%s); resetting the "
        "ingest deferral-stall streak to a fresh start",
        path,
        reason.value,
        field,
    )
    return INITIAL_STATE, reason


def load_state(path: Path) -> DeferralStreakState:
    """:func:`load_state_checked` without the reason."""
    return load_state_checked(path)[0]


def save_state(path: Path, state: DeferralStreakState) -> None:
    """Atomic replace: write a sibling temp file, fsync it, then `os.replace`.

    Single writer (the ingest unit, AC-6f-6/L-50) -- no lock, the same
    stance every other marker file in this package takes: concurrent-writer
    exclusion rests on systemd's oneshot single-instance semantics plus the
    hand-run ban, not on code.
    """
    payload = json.dumps(
        {
            "version": state.version,
            "consecutive_runs": state.consecutive_runs,
            "first_deferred_utc": state.first_deferred_utc,
            "runs_since_alert": state.runs_since_alert,
        },
        sort_keys=True,
    )
    tmp_path = path.with_name(f"{path.name}.tmp-{os.getpid()}")
    try:
        with tmp_path.open("w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except OSError:
        with contextlib.suppress(OSError):
            tmp_path.unlink(missing_ok=True)
        raise
