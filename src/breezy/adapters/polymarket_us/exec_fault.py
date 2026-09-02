"""A process-scoped latch recording a FATAL, unrecoverable execution-client fault.

Mirrors :mod:`breezy.adapters.polymarket_us.feed_fault` exactly, one venue
surface over. See that module's docstring for the full null-hypothesis
argument; it applies here without change:

* Nautilus already owns shutdown and clean teardown.
* What Nautilus does NOT supply is a process exit status: a failed
  ``_connect`` is swallowed by ``LiveExecutionClient``'s own task-completion
  handler (``nautilus_trader/live/execution_client.py:212-226``) -- it logs
  the exception and skips the ``_set_connected(True)`` action, but the task
  itself completes normally from the event loop's point of view. Nothing
  downstream re-raises it. ``_await_engines_connected``
  (``nautilus_trader/system/kernel.py:1310-1316``) only WARNS on a timeout,
  and ``start_async`` (``:1024``) returns regardless. Without this latch,
  ``breezy-trade`` would exit ``EXIT_OK`` having never reconciled and never
  traded -- EXEC SPINE ``docs/plans/EXEC_SPINE_R5_R6_2026-09-02.md`` risk 2.

DESIGN NOTES
------------
* **First fault wins**, same as the feed-fault latch: the first cause is what
  an operator needs, not the last symptom a cascade produced.
* **Module-scoped, not injected.** ``PolymarketUSExecutionClient`` is built by
  a Nautilus factory from config; the CLI never sees the instance. There is no
  seam to thread a handle through without reaching into kernel internals.
* **No Nautilus import, no network import, stdlib only** -- readable from
  either side of the ``runtime -> adapters`` import-linter layer, and legal
  for :mod:`breezy.adapters.polymarket_us.exec.client` to import: it sits
  beside ``exec/``, not under it, so it carries none of the E0/E0-INERT
  execution-egress classification (it moves no order, opens no socket).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

__all__ = [
    "FatalExecFault",
    "clear_fatal_exec_fault",
    "fatal_exec_fault",
    "record_fatal_exec_fault",
]


@dataclass(frozen=True, slots=True)
class FatalExecFault:
    """The first unrecoverable execution-client fault observed in this process."""

    component: str
    """Identity of the component that declared the fault (e.g. the client id)."""

    reason: str
    """Operator-facing explanation, safe to print to stderr and to a log."""


_LOCK = threading.Lock()
_FAULT: FatalExecFault | None = None


def record_fatal_exec_fault(component: str, reason: str) -> None:
    """Latch an unrecoverable execution-client fault. The FIRST call wins.

    Idempotent: a `_connect` that is retried after a reconnect must not
    overwrite the original cause, matching R-4's own never-self-clearing
    refusal latch (``exec/client.py`` invariant 1).
    """
    global _FAULT

    with _LOCK:
        if _FAULT is None:
            _FAULT = FatalExecFault(component=component, reason=reason)


def fatal_exec_fault() -> FatalExecFault | None:
    """Return the latched fault, or ``None`` if this process has had none."""
    with _LOCK:
        return _FAULT


def clear_fatal_exec_fault() -> None:
    """Reset the latch.

    Called once at the trading process's start-up so a run can only ever
    report its OWN fault, and used by tests for isolation. Deliberately NOT
    called on shutdown: the CLI reads the latch after the node has stopped.
    """
    global _FAULT

    with _LOCK:
        _FAULT = None
