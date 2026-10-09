"""AMBIG-LATCH-RESUME Phase A (DH1): the supervisor decode marker.

**The hazard.** The supervisor decodes the durable submit-intent singleton on
every launch (``trade_supervisor.probe_open_intent``) with the
``RetirementReason`` enum IT loaded at its own start. A node respawned from the
merged tree may one day retire an intent with a member an older supervisor does
not know; that supervisor's ``_optional_enum`` raises ``SubmitIntentCorrupt``,
the probe reads the RETIRED singleton as OPEN, and every later launch is
refused (L-48 again).

**The mechanism.** At start the supervisor writes ``<store>.supervisor_decode``
naming its own pid + ``/proc`` start-tick identity and the retirement-reason
values it can decode. A node asks :func:`supervisor_admits_retirement_reason`
before it ever writes a new reason; anything short of a live, matching, current
supervisor answers ``False`` (fail closed: the intent then stays AMBIGUOUS and
pages, which is safe).

The marker is a plain file beside the store (the ``stop_intent_marker`` shape),
never a store key: the supervisor must not write the SQLite store while a node
holds it. No Nautilus import, no network, no scheduling.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from breezy.runtime.stop_intent_marker import process_start_ticks as _default_process_start_ticks
from breezy.runtime.submit_intent import RetirementReason

__all__ = [
    "SupervisorDecodeMarker",
    "read_supervisor_decode_marker",
    "supervisor_admits_retirement_reason",
    "supervisor_decode_marker_path",
    "write_supervisor_decode_marker",
]

_MARKER_SUFFIX: Final[str] = ".supervisor_decode"
_SCHEMA_VERSION: Final[int] = 1

ProcessStartTicks = Callable[[int], int | None]


@dataclass(frozen=True, slots=True)
class SupervisorDecodeMarker:
    pid: int
    start_ticks: int
    revision: str
    retirement_reasons: frozenset[str]


def supervisor_decode_marker_path(store_path: Path) -> Path:
    """Beside ``store_path``, matching ``stop_intent_marker_path``'s convention."""
    return store_path.with_name(store_path.name + _MARKER_SUFFIX)


def write_supervisor_decode_marker(
    store_path: Path,
    *,
    revision: str,
    pid: int | None = None,
    process_start_ticks: ProcessStartTicks = _default_process_start_ticks,
) -> None:
    """Atomically (tmp file, then ``os.replace``) write the marker for ``pid``
    (default: this process). Overwrites on every supervisor start.

    Raises ``OSError`` rather than swallowing: the caller
    (``trade_supervisor.main``) logs ``supervisor_decode_marker_write_failed``
    and carries on, because without a marker the node fails closed anyway. A
    pid whose start ticks are unreadable gets NO marker (an identity-less
    marker would be worse than none).
    """
    target_pid = os.getpid() if pid is None else pid
    start_ticks = process_start_ticks(target_pid)
    if start_ticks is None:
        raise OSError("supervisor decode marker: process start ticks unreadable")
    payload = {
        "v": _SCHEMA_VERSION,
        "pid": target_pid,
        "start_ticks": start_ticks,
        "revision": revision,
        "retirement_reasons": sorted(member.value for member in RetirementReason),
    }
    marker_path = supervisor_decode_marker_path(store_path)
    tmp_path = marker_path.with_name(f"{marker_path.name}.tmp.{os.getpid()}")
    try:
        tmp_path.write_text(json.dumps(payload))
        os.replace(tmp_path, marker_path)
    except OSError:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def _is_plain_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def read_supervisor_decode_marker(store_path: Path) -> SupervisorDecodeMarker | None:
    """The decoded marker, or ``None`` for an absent, unreadable or malformed
    file (every failure is the same fail-closed answer)."""
    try:
        payload = json.loads(supervisor_decode_marker_path(store_path).read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict) or payload.get("v") != _SCHEMA_VERSION:
        return None
    pid = payload.get("pid")
    start_ticks = payload.get("start_ticks")
    revision = payload.get("revision")
    reasons = payload.get("retirement_reasons")
    if not (_is_plain_int(pid) and _is_plain_int(start_ticks) and isinstance(revision, str)):
        return None
    if not isinstance(reasons, list) or not all(isinstance(r, str) for r in reasons):
        return None
    return SupervisorDecodeMarker(
        pid=pid,  # type: ignore[arg-type]
        start_ticks=start_ticks,  # type: ignore[arg-type]
        revision=revision,
        retirement_reasons=frozenset(reasons),
    )


def supervisor_admits_retirement_reason(
    store_path: Path,
    reason: str,
    *,
    process_start_ticks: ProcessStartTicks = _default_process_start_ticks,
) -> bool:
    """``True`` iff the marker decodes, lists ``reason``, and its pid is alive
    with the SAME ``/proc`` start ticks (so the writer is the RUNNING
    supervisor, never a stale file from an older incarnation or a reused pid).
    Anything else is ``False``."""
    marker = read_supervisor_decode_marker(store_path)
    if marker is None or reason not in marker.retirement_reasons:
        return False
    current = process_start_ticks(marker.pid)
    return current is not None and current == marker.start_ticks
