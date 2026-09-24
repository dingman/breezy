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
one-shot marker naming the target PID immediately before sending SIGTERM. The
node process itself -- after ``node.run()`` returns, at the SAME point
``trade_cli._emit_boot_halt_alert`` already reads the one-shot public
``Trader.is_running``/``is_stopped`` state -- consumes (reads-and-deletes) that
marker and asks "was this stop, for ME, requested?" A match suppresses the
CRITICAL boot-halt alert; anything else (no marker, a marker for a different
PID, a marker that fails to parse) leaves the alert alone -- fail CLOSED
toward alerting, since a spurious page is recoverable and a swallowed genuine
halt is not.

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
from pathlib import Path

logger = logging.getLogger(__name__)

__all__ = [
    "consume_stop_intent_marker",
    "stop_intent_marker_path",
    "write_stop_intent_marker",
]

_MARKER_SUFFIX: str = ".stop_intent"


def stop_intent_marker_path(store_path: Path) -> Path:
    """Beside ``store_path``, matching ``trade_supervisor.intent_lock_path``."""
    return store_path.with_name(store_path.name + _MARKER_SUFFIX)


def write_stop_intent_marker(store_path: Path, pid: int) -> None:
    """Best-effort, atomic write of ``{"pid": pid}`` beside ``store_path``.

    Called immediately before the terminator's own ``os.kill(pid, SIGTERM)``.
    A write failure is logged and swallowed -- this marker is corroborating
    evidence for the boot-halt alert, never the mechanism that stops the
    node, so it must never block or fail the SIGTERM it precedes.

    Atomic (write a sibling temp file, then ``os.replace``) so a reader can
    never observe a partially-written marker.
    """
    marker_path = stop_intent_marker_path(store_path)
    tmp_path = marker_path.with_name(f"{marker_path.name}.tmp.{os.getpid()}")
    try:
        tmp_path.write_text(json.dumps({"pid": pid}))
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


def consume_stop_intent_marker(store_path: Path, pid: int) -> bool:
    """``True`` iff a marker naming ``pid`` is found beside ``store_path``.

    Consumed (deleted) on every read that finds the file at all, matched or
    not: the marker is single-use evidence for exactly the one stop attempt
    that wrote it, and a stale leftover must never influence a later, unrelated
    boot's suppression decision.

    Fails CLOSED toward "not requested" (returns ``False``) on a missing file,
    an unreadable file, or an unparseable/unexpected payload -- an alert
    firing when it need not is recoverable; a suppressed alert on a genuine
    halt is not.
    """
    marker_path = stop_intent_marker_path(store_path)
    try:
        raw = marker_path.read_text()
    except OSError:
        return False
    try:
        marker_path.unlink()
    except OSError:
        pass
    try:
        decoded = json.loads(raw)
    except ValueError:
        return False
    if not isinstance(decoded, dict):
        return False
    return decoded.get("pid") == pid
