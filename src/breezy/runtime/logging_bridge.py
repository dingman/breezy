"""Bridges stdlib ``logging`` into NautilusTrader's native ``Logger``.

Null hypothesis, checked against the installed ``nautilus-trader==1.231.0``
before this module was written: every Breezy module logs through plain
stdlib ``logging.getLogger(__name__)`` (``composition.py``, ``cli.py``,
``node_config.py``, the ingest actor). NautilusTrader configures and owns its
*own* logging subsystem, driven through
``nautilus_trader.common.component.Logger`` and initialised from
``LoggingConfig`` (``runtime/node_config.py:149``). There is no bridge
between the two: a stdlib record -- including every ``logger.critical`` on
the ingest path -- never reaches the log stream an operator watching
Nautilus's output actually sees.

This module closes that gap with a single ``logging.Handler`` attached to
the ``breezy`` logger namespace (never the root logger, so third-party
logging is left untouched) that forwards each stdlib ``LogRecord`` to a
``nautilus_trader.common.component.Logger`` instance using only that
class's public, documented methods -- ``debug``/``info``/``warning``/
``error`` (``nautilus_trader/common/component.pyx:1425-1530``). Nautilus's
``Logger`` is treated as an immutable native surface (repo ``CLAUDE.md``):
nothing here patches, wraps-by-monkeypatching, forks, or reimplements it.

Level mapping
-------------
NautilusTrader's ``Logger`` exposes four severities: DEBUG, INFO, WARNING,
ERROR. There is no native CRITICAL level. Every stdlib level is mapped
explicitly and completely, using stdlib's own ``>=`` threshold ordering so
that *no* integer level -- including custom, non-standard levels -- is ever
silently dropped for want of an exact match:

    level >= CRITICAL (50) -> Logger.error   (highest native severity)
    level >= ERROR    (40) -> Logger.error
    level >= WARNING  (30) -> Logger.warning
    level >= INFO     (20) -> Logger.info
    level <  INFO           -> Logger.debug  (covers DEBUG and below)

Uninitialized Nautilus logging
-------------------------------
``Logger`` is safe to construct, and safe to log through, before
NautilusTrader's global logging subsystem has been initialised via
``init_logging``/``LoggingConfig``: its ``debug``/``info``/``warning``/
``error`` methods each check ``is_logging_initialized()`` internally and
return without raising or emitting anything when it is ``False``
(``nautilus_trader/common/component.pyx``, e.g. ``Logger.debug``:1450-1451).
This bridge relies on that native behaviour rather than reimplementing the
check: installing the bridge before Nautilus logging is initialised is
safe. Records logged in that window are silently discarded, not queued and
not raised, and forwarding resumes with no further action once Nautilus
logging is initialised, because the same ``Logger`` instance is reused for
the lifetime of the handler.

Handler failure contract
-------------------------
A logging handler must never let a failure inside it propagate into the
code that logged. ``emit`` follows stdlib's own documented convention:
any exception raised while formatting or forwarding a record is caught and
handed to ``self.handleError(record)`` (the same path stdlib's built-in
handlers use), never re-raised.
"""

from __future__ import annotations

import logging
from typing import Protocol

from nautilus_trader.common.component import Logger as NautilusLogger

#: The Breezy logger namespace the bridge attaches to. Every Breezy module
#: logs through a child of this name (``breezy.runtime.cli``,
#: ``breezy.ingest.nws_actor``, ...), so attaching here -- rather than to the
#: root logger -- forwards all of them without touching third-party logging.
BREEZY_LOGGER_NAME = "breezy"


class SupportsNautilusLog(Protocol):
    """The subset of ``nautilus_trader.common.component.Logger`` this bridge uses."""

    def debug(self, message: str) -> None: ...

    def info(self, message: str) -> None: ...

    def warning(self, message: str) -> None: ...

    def error(self, message: str) -> None: ...


def _nautilus_method_name(levelno: int) -> str:
    """Map a stdlib numeric level onto a ``SupportsNautilusLog`` method name.

    Threshold-based (``>=``), not a lookup table, so every level -- including
    non-standard custom levels -- resolves to a method rather than being
    silently dropped.
    """
    if levelno >= logging.ERROR:  # covers ERROR and CRITICAL
        return "error"
    if levelno >= logging.WARNING:
        return "warning"
    if levelno >= logging.INFO:
        return "info"
    return "debug"  # covers DEBUG and anything below it


class NautilusLoggingBridgeHandler(logging.Handler):
    """Forwards stdlib ``LogRecord``\\ s to a native Nautilus ``Logger``."""

    def __init__(self, nautilus_logger: SupportsNautilusLog | None = None) -> None:
        super().__init__()
        self._logger: SupportsNautilusLog = (
            nautilus_logger if nautilus_logger is not None else NautilusLogger(BREEZY_LOGGER_NAME)
        )

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = self.format(record)
            method_name = _nautilus_method_name(record.levelno)
            method = getattr(self._logger, method_name)
            method(message)
        except Exception:  # noqa: BLE001 - a handler must never raise into the caller
            self.handleError(record)


_installed_handler: NautilusLoggingBridgeHandler | None = None


def install(
    nautilus_logger: SupportsNautilusLog | None = None,
) -> NautilusLoggingBridgeHandler:
    """Attach the bridge to the ``breezy`` logger namespace.

    Idempotent: if a bridge handler is already attached, it is returned
    unchanged and no second handler is added -- calling ``install`` twice
    forwards one log call as exactly one record, never two. ``nautilus_logger``
    is only used to construct a *new* handler; it is ignored when a handler is
    already installed.

    Also raises the ``breezy`` logger's own level to ``DEBUG`` so records are
    not filtered out by stdlib's own level check before ever reaching this
    handler -- NautilusTrader's configured ``LoggingConfig.log_level`` remains
    the effective filter an operator sees.
    """
    global _installed_handler
    breezy_logger = logging.getLogger(BREEZY_LOGGER_NAME)
    if _installed_handler is not None and _installed_handler in breezy_logger.handlers:
        return _installed_handler
    handler = NautilusLoggingBridgeHandler(nautilus_logger)
    breezy_logger.addHandler(handler)
    breezy_logger.setLevel(logging.DEBUG)
    _installed_handler = handler
    return handler


def uninstall() -> None:
    """Detach the bridge handler from the ``breezy`` logger namespace.

    Safe to call when no handler is installed. Restores the ``breezy``
    logger's level to ``NOTSET`` so it reverts to inheriting from its
    parent, leaving no residual state behind for the next ``install``.
    """
    global _installed_handler
    breezy_logger = logging.getLogger(BREEZY_LOGGER_NAME)
    if _installed_handler is not None and _installed_handler in breezy_logger.handlers:
        breezy_logger.removeHandler(_installed_handler)
    breezy_logger.setLevel(logging.NOTSET)
    _installed_handler = None
