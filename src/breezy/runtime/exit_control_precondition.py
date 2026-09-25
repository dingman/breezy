"""AUD-07 step 7c: the halt-state precondition for the positive control
(read-only; builds and sends no order).

The registration package's pre-control checklist gains a sender-global
halt-state read (plan ``AUD-07-exit-seam-arming-verification-path.md`` §7
step 7c). This reuses :func:`breezy.runtime.trade_supervisor.
read_continuous_family_store_state` and
:func:`breezy.runtime.trade_supervisor_core.continuous_family_halt_key` --
the SAME store and the SAME key the exit veto
(``exit_wiring.submit_exit`` -> ``TrialDayLatch.is_family_halted``) already
reads. No new mechanism, no new key, no new veto.

Runtime layer only: this module never imports ``strategy`` or ``adapters``
(the layers contract, ``pyproject.toml``, forbids ``runtime`` from reaching
up into ``strategy``). ``reader`` is an injected callable rather than a
hardcoded call so this stays true regardless of what future callers pass.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from breezy.runtime.trade_supervisor import (
    ContinuousFamilyStoreState,
    read_continuous_family_store_state,
)
from breezy.runtime.trade_supervisor_core import continuous_family_halt_key

#: Exactly three verdicts. None contains "FAIL" -- this is a precondition
#: reading, not a test-style pass/fail outcome.
HALT_CLEAR_NEXT_PRECONDITION: Final[str] = "HALT_CLEAR_NEXT_PRECONDITION"
BLOCKED_FAMILY_HALT_SET: Final[str] = "BLOCKED_FAMILY_HALT_SET"
BLOCKED_HALT_STATE_UNREADABLE: Final[str] = "BLOCKED_HALT_STATE_UNREADABLE"

HaltStateReader = Callable[[Path, str], ContinuousFamilyStoreState]


@dataclass(frozen=True, slots=True)
class HaltPreconditionReading:
    verdict: str
    halt_key: str
    store_path: Path
    read_at_ns: int


def read_exit_control_halt_precondition(
    store_path: Path,
    sending_family_id: str,
    *,
    now_ns: int,
    reader: HaltStateReader = read_continuous_family_store_state,
) -> HaltPreconditionReading:
    """Read-only sender-global halt-state check. Never writes, never
    raises: any ``reader`` exception fails closed as
    :data:`BLOCKED_HALT_STATE_UNREADABLE` rather than propagating.

    ``reader``'s connection (the default ``read_continuous_family_store_
    state`` -> ``SqliteStateStore``) is opened read-write in MODE -- but
    performs no write on an EXISTING store, since it only ever ``get``\\ s.
    On a non-existent ``store_path`` it would instead ``mkdir(parents=True)``
    and ``CREATE TABLE IF NOT EXISTS`` a fresh, empty database and read no
    halt from it -- silently returning :data:`HALT_CLEAR_NEXT_PRECONDITION`
    for a path that names nothing (fail-open). This function therefore
    checks ``store_path.is_file()`` FIRST and returns
    :data:`BLOCKED_HALT_STATE_UNREADABLE` without ever calling ``reader``,
    and without creating the file or its parent directory, when the store
    does not already exist.
    """
    halt_key = continuous_family_halt_key(sending_family_id)
    if not store_path.is_file():
        verdict = BLOCKED_HALT_STATE_UNREADABLE
    else:
        try:
            state = reader(store_path, sending_family_id)
        except Exception:  # noqa: BLE001 - any reader failure fails closed, never propagates
            verdict = BLOCKED_HALT_STATE_UNREADABLE
        else:
            verdict = (
                BLOCKED_FAMILY_HALT_SET if state.family_halted else HALT_CLEAR_NEXT_PRECONDITION
            )
    return HaltPreconditionReading(
        verdict=verdict,
        halt_key=halt_key,
        store_path=Path(store_path),
        read_at_ns=now_ns,
    )
