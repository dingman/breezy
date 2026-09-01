"""A process-scoped latch recording a FATAL, unrecoverable market-data fault.

WHY THIS EXISTS (null hypothesis, checked before it was written)
----------------------------------------------------------------
Half of what this file's purpose looks like IS native, and is therefore not
rebuilt here:

* **Requesting the shutdown is native.** ``Component.shutdown_system(reason)``
  (``nautilus_trader/common/component.pyx:2162-2182``) publishes a
  ``ShutdownSystem`` command on ``commands.system.shutdown``, and
  ``NautilusKernel._on_shutdown_system``
  (``nautilus_trader/system/kernel.py:613-638``) handles it by calling
  ``stop_async()`` on the running loop. Every ``DataClient`` inherits it via
  ``Component``. Breezy authors no shutdown mechanism.

* **Closing the tape safely is native**, and is the reason the shutdown above
  must be used instead of ``os._exit``/``sys.exit``. A clean stop runs
  ``StreamingFeatherWriter.close()``
  (``nautilus_trader/persistence/writer.py:596-611``), which appends the Arrow
  end-of-stream marker. An unclean death can leave a truncated trailing
  message, and ``ParquetDataCatalog._read_feather_file``
  (``persistence/catalog/parquet.py:2795-2800``) swallows exactly that failure
  and returns ``None``, so ``convert_stream_to_data`` silently converts ZERO
  rows. Measured in ``tests/contract/test_quote_tape_unclean_shutdown.py``.
  Exiting hard to report a lost feed would destroy the tape recorded up to the
  moment the feed was lost.

What is NOT native is the only thing this module supplies: **the process exit
status**. ``TradingNode.run()`` returns ``None`` (``live/node.py:283-302``);
``grep -n reason nautilus_trader/system/kernel.py`` matches nothing, so the
kernel retains no record of why it stopped. After a native shutdown the CLI
sees a normal return -- byte-for-byte identical to an operator SIGTERM at the
end of the capture window. Without this latch the two are indistinguishable
and the recorder reports success over an empty tape.

That distinction is the whole point for an UNATTENDED run. A systemd unit that
stays ``active (running)``, or exits 0 after losing its feed at minute four of
an eight-hour window, tells the operator nothing. A non-zero exit makes
``systemctl status`` say ``failed`` and lets ``Restart=on-failure`` mean what
it says.

DESIGN NOTES
------------
* **First fault wins.** A lost feed produces derivative failures immediately
  afterwards; the operator needs the original cause, not the last symptom.
* **Module-scoped, not injected.** The producer (the data client, constructed
  by a Nautilus factory) and the consumer (the CLI, which never sees the
  client instance) have no shared object between them. ``TradingNode`` builds
  its clients internally from config, so there is no seam to thread a handle
  through without reaching into kernel internals -- which is the coupling this
  repo forbids.
* **Lock-guarded.** The recorder runs a disk-monitor thread alongside the event
  loop, so the latch is not assumed to be touched from one thread only.
* **No Nautilus import, no venue import, stdlib only** -- so it can be read
  from either side of the ``runtime -> adapters`` import-linter layer.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

__all__ = [
    "FatalFeedFault",
    "clear_fatal_feed_fault",
    "fatal_feed_fault",
    "record_fatal_feed_fault",
]


@dataclass(frozen=True, slots=True)
class FatalFeedFault:
    """The first unrecoverable market-data fault observed in this process."""

    component: str
    """Identity of the component that declared the fault (e.g. the client id)."""

    reason: str
    """Operator-facing explanation, safe to print to stderr and to a log."""


_LOCK = threading.Lock()
_FAULT: FatalFeedFault | None = None


def record_fatal_feed_fault(component: str, reason: str) -> None:
    """Latch an unrecoverable market-data fault. The FIRST call wins.

    Idempotent by design: the watchdog that calls this samples on a cadence
    and its caller is public, so a repeated observation of the same dead feed
    must not overwrite the original cause or re-trigger anything downstream.
    """
    global _FAULT

    with _LOCK:
        if _FAULT is None:
            _FAULT = FatalFeedFault(component=component, reason=reason)


def fatal_feed_fault() -> FatalFeedFault | None:
    """Return the latched fault, or ``None`` if this process has had none."""
    with _LOCK:
        return _FAULT


def clear_fatal_feed_fault() -> None:
    """Reset the latch.

    Called once at recorder start-up so a run can only ever report its OWN
    fault, and used by tests for isolation. Deliberately NOT called on
    shutdown: the CLI reads the latch after the node has stopped.
    """
    global _FAULT

    with _LOCK:
        _FAULT = None
