"""AUD-13d HIGH-1: a Breezy-owned, durable marker naming an intentional stop.

Null hypothesis, checked before writing this: **Nautilus Trader has no public,
stop-surviving way to tell "the operator asked for this" apart from "the
process crashed"**. ``TradingNode``/``NautilusKernel`` install their OWN
SIGTERM/SIGINT/SIGABRT handling via ``asyncio.AbstractEventLoop.
add_signal_handler`` (``nautilus_trader/system/kernel.py:558-572``), which is a
single-callback-per-signal registry -- there is no native way for Breezy to
ALSO register a handler for the same signal on the same loop without either
replacing Nautilus's own callback (forbidden) or racing its install order.
Composing at the signal layer is therefore not the simplest safe mechanism;
plain file I/O, owned entirely by Breezy and never touching the kernel, is.

The shape: the process that is ABOUT to intentionally terminate the node (here,
``breezy.runtime.trade_supervisor``'s daily ``stop_prior`` phase) writes a
one-shot marker naming the target PID *and its current process incarnation*
immediately before sending SIGTERM. The node process itself -- after
``node.run()`` returns, at the SAME point ``trade_cli._emit_boot_halt_alert``
already reads the one-shot public ``Trader.is_running``/``is_stopped`` state
-- consumes (reads-and-deletes) that marker and asks "was THIS incarnation of
ME the one a stop was requested for?" A match suppresses the CRITICAL
boot-halt alert; anything else (no marker, a marker for a different pid, a
pid-reuse mismatch, an expired marker, a marker that fails to parse) leaves
the alert alone -- fail CLOSED toward alerting, since a spurious page is
recoverable and a swallowed genuine halt is not.

[2026-09-24 review, pid-reuse hardening] A bare pid is not a safe identity: if
the terminator's own ``os.kill`` races a target that died right after the
TOCTOU recheck (``ProcessLookupError``), a marker written for that pid would
otherwise be orphaned, and a LATER, unrelated process the kernel happens to
reuse that pid for would have a genuine boot halt wrongly silenced. Two
independent defences: (1) the marker binds the pid to the target's ``/proc``
start time (see :func:`_process_start_ticks`), the same pid+starttime pair the
kernel itself uses to detect reuse, so a different incarnation of the same pid
never matches; (2) :func:`discard_stop_intent_marker` removes an orphaned
marker immediately if the signal that would have corroborated it never landed
(``breezy.runtime.trade_supervisor.terminate_after_toctou_recheck`` calls it
when ``terminate_fn`` raises). A short max age is a third, belt-and-suspenders
bound in case both of those are somehow bypassed.

**Residual scope, stated rather than hidden**: only
``trade_supervisor.terminate_after_toctou_recheck``'s ``stop_prior`` call site
writes this marker. The runbook's emergency kill switch
(``pkill -f 'breezy-trade$'``) and the hand-relaunch ``kill -TERM <OLD_PID>``
recipe (``docs/plans/R8_OPERATOR_RUNBOOK.md``) both bypass it entirely and
WILL page CRITICAL if either lands on a node that has not yet reached
RUNNING -- exactly like any other unattributed crash, by design: this module
only recognises a stop Breezy's own supervisor requested.

Beside the exec state-DB store path, matching
``trade_supervisor.intent_lock_path``'s own ``<store>.<suffix>`` convention --
same directory, same ownership boundary, a distinct file so the two never
contend.

No Nautilus import, no signal handling, no scheduling (``call_soon``/
``call_later``/``create_task``/``Thread``/``Timer``): this module is plain,
synchronous file I/O.
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Callable
from pathlib import Path

logger = logging.getLogger(__name__)

__all__ = [
    "consume_stop_intent_marker",
    "discard_stop_intent_marker",
    "process_start_ticks",
    "stop_intent_marker_path",
    "write_stop_intent_marker",
]

_MARKER_SUFFIX: str = ".stop_intent"

#: [pid-reuse hardening, belt-and-suspenders] A marker older than this can
#: never suppress an alert, even on an exact pid+start-time match. Not a
#: tuned deadline: every real stop_prior shape this repo runs completes the
#: SIGTERM -> Nautilus's own stop_async -> run() returning sequence in well
#: under a minute, so five minutes is a generous multiple of that -- it
#: bounds the window a marker can ever apply without being reachable in
#: normal operation. Cross-checked against Nautilus's OWN shutdown timeout
#: budget (installed ``nautilus_trader/system/config.py:127-129``,
#: ``NautilusKernelConfig``): ``timeout_connection=60.0``,
#: ``timeout_reconciliation=30.0``, ``timeout_portfolio=10.0`` seconds --
#: 100s total, before ``timeout_disconnection``/``timeout_post_stop``/
#: ``timeout_shutdown`` even start. 300s is a 3x multiple of that whole
#: connection+reconciliation+portfolio budget, not just of the "well under a
#: minute" happy path, so a slow-but-legitimate stop_async that eats its full
#: Nautilus-side timeout allowance still leaves headroom before this bound
#: fires.
#:
#: [2026-09-24 review, why this stays ``time.time()`` and not
#: ``time.monotonic()``] ``time.monotonic()`` on Linux is backed by
#: ``CLOCK_MONOTONIC``, which the Python docs (``time.monotonic``) and
#: ``clock_gettime(2)`` both describe as a single *system-wide* clock -- so
#: two DIFFERENT processes reading it on the SAME boot get directly
#: comparable values, unlike e.g. per-process CPU-time clocks. That property
#: alone would make it a fine fit for an age check written by one process and
#: read by another. It is rejected here anyway for one reason
#: ``CLOCK_MONOTONIC``-across-processes does not fix: it resets to (near) 0
#: at every boot. The claim "a reboot between write and consume can't
#: silently validate because start_ticks already differ across boots" does
#: NOT hold -- ``/proc/<pid>/stat`` field 22 is ALSO ticks-since-boot (see
#: :func:`_process_start_ticks`), so early in a fresh boot, PIDs are
#: routinely reused at LOW numbers with correspondingly small, collision-prone
#: start_ticks; a genuine host reboot in the write-to-consume window is the
#: one scenario the pid+start_ticks pair is least reliable against. Wall-clock
#: ``time.time()`` is what actually closes that gap: real time keeps
#: advancing across a reboot (a reboot takes far longer than an in-process
#: restart), so ``now() - written_at`` stays large and this check still fails
#: closed exactly when the identity check is at its weakest. A monotonic
#: ``now() - written_at`` computed across a reboot would instead be
#: small or even negative (the post-reboot clock starts back near 0), which
#: would WRONGLY read as "fresh" -- the opposite of fail-closed. Keep
#: ``time.time()``.
_MAX_MARKER_AGE_SECONDS: float = 300.0

#: 1-based ``/proc/<pid>/stat`` field 22 (``starttime``, clock ticks since
#: boot) is at THIS index once the line is split after the last ``)`` --
#: ``comm`` (field 2) is parenthesized and may itself contain spaces or
#: parentheses, the same parsing ``trade_supervisor._proc_state_char``
#: already uses, so after that split field 3 (``state``) becomes index 0,
#: and field N is index N-3.
_STAT_STARTTIME_FIELD_INDEX: int = 22 - 3


def stop_intent_marker_path(store_path: Path) -> Path:
    """Beside ``store_path``, matching ``trade_supervisor.intent_lock_path``."""
    return store_path.with_name(store_path.name + _MARKER_SUFFIX)


def _process_start_ticks(pid: int) -> int | None:
    """Field 22 of ``/proc/<pid>/stat`` -- clock ticks since boot at process
    start. Paired with the pid itself this is the standard Linux pid-reuse-
    safe process identity (the same pair the kernel itself hands out): a
    pid reused by an unrelated later process starts at a different tick than
    the incarnation that previously held it. ``None`` if the pid is gone or
    the file cannot be parsed -- callers must treat that as "identity
    unknown," never as a match.
    """
    try:
        raw = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return None
    after_comm = raw.rsplit(")", 1)[-1]
    fields = after_comm.split()
    if len(fields) <= _STAT_STARTTIME_FIELD_INDEX:
        return None
    try:
        return int(fields[_STAT_STARTTIME_FIELD_INDEX])
    except ValueError:
        return None


#: Public alias (AMBIG-LATCH-RESUME Phase A): ``runtime.supervisor_decode_marker``
#: binds its pid to the same /proc start-tick identity this module uses, and
#: must not import a private name across modules. Same function object.
process_start_ticks = _process_start_ticks


def write_stop_intent_marker(
    store_path: Path,
    pid: int,
    *,
    now: Callable[[], float] = time.time,
    process_start_ticks: Callable[[int], int | None] = _process_start_ticks,
) -> None:
    """Best-effort, atomic write of ``{"pid", "start_ticks", "written_at"}``
    beside ``store_path``.

    Called immediately before the terminator's own ``os.kill(pid, SIGTERM)``,
    while ``pid`` is still known-alive (the caller's own TOCTOU recheck just
    confirmed it). ``start_ticks`` binds the marker to THIS incarnation of
    ``pid`` -- see :func:`_process_start_ticks` -- so a later, unrelated
    process the kernel assigns the SAME pid can never match it. If ``pid``'s
    start time cannot be read (it has already gone -- a race between the
    recheck and this call), NOTHING is written: a missing marker fails
    closed toward alerting, which is always safe; a marker with no bound
    identity would not be.

    A write failure is logged and swallowed -- this marker is corroborating
    evidence for the boot-halt alert, never the mechanism that stops the
    node, so it must never block or fail the SIGTERM it precedes.

    Atomic (write a sibling temp file, then ``os.replace``) so a reader can
    never observe a partially-written marker.
    """
    start_ticks = process_start_ticks(pid)
    if start_ticks is None:
        logger.error(
            "stop-intent marker not written: pid=%d start time unreadable (already gone?)",
            pid,
        )
        return
    marker_path = stop_intent_marker_path(store_path)
    tmp_path = marker_path.with_name(f"{marker_path.name}.tmp.{os.getpid()}")
    payload = {"pid": pid, "start_ticks": start_ticks, "written_at": now()}
    try:
        tmp_path.write_text(json.dumps(payload))
        os.replace(tmp_path, marker_path)
    except OSError as exc:
        logger.error(
            "stop-intent marker could not be written exception_type=%s",
            type(exc).__name__,
        )
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass


def discard_stop_intent_marker(store_path: Path) -> None:
    """Best-effort removal, never raises.

    Used when the SIGTERM a just-written marker corroborates never actually
    landed (``trade_supervisor.terminate_after_toctou_recheck``'s
    ``terminate_fn`` raised, e.g. the target died between the TOCTOU recheck
    and the signal) -- an orphaned marker naming a pid that never received
    the signal must not survive to (mis)match a later, unrelated process
    reusing that pid.
    """
    marker_path = stop_intent_marker_path(store_path)
    try:
        marker_path.unlink(missing_ok=True)
    except OSError as exc:
        logger.error(
            "stop-intent marker could not be discarded exception_type=%s",
            type(exc).__name__,
        )


def consume_stop_intent_marker(
    store_path: Path,
    pid: int,
    *,
    now: Callable[[], float] = time.time,
    process_start_ticks: Callable[[int], int | None] = _process_start_ticks,
    max_age_seconds: float = _MAX_MARKER_AGE_SECONDS,
) -> bool:
    """``True`` iff a marker naming ``pid``'s CURRENT incarnation -- same pid,
    same ``start_ticks``, and no older than ``max_age_seconds`` -- is found
    beside ``store_path``.

    Consumed (deleted) on every read that finds the file at all, matched or
    not: the marker is single-use evidence for exactly the one stop attempt
    that wrote it, and a stale leftover must never influence a later,
    unrelated boot's suppression decision.

    Fails CLOSED toward "not requested" (returns ``False``) on a missing
    file, an unreadable file, an unparseable/unexpected payload, a pid or
    start-time mismatch (pid reuse), or an expired marker -- an alert firing
    when it need not is recoverable; a suppressed alert on a genuine halt is
    not.
    """
    marker_path = stop_intent_marker_path(store_path)
    try:
        raw = marker_path.read_text()
    except OSError:
        return False
    try:
        marker_path.unlink()
    except OSError as exc:
        logger.error(
            "stop-intent marker could not be removed exception_type=%s",
            type(exc).__name__,
        )
    try:
        decoded = json.loads(raw)
    except ValueError:
        return False
    if not isinstance(decoded, dict):
        return False
    if decoded.get("pid") != pid:
        return False
    written_at = decoded.get("written_at")
    if not isinstance(written_at, int | float):
        return False
    if now() - written_at > max_age_seconds:
        return False
    marker_start_ticks = decoded.get("start_ticks")
    current_start_ticks = process_start_ticks(pid)
    return current_start_ticks is not None and marker_start_ticks == current_start_ticks
