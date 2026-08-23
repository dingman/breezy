"""The `breezy` console entrypoint: compose, run, shut down.

Null hypothesis, checked against the installed ``nautilus-trader==1.231.0``
before this module was written:

* **SIGINT/SIGTERM/SIGABRT handling is already provided.**
  ``NautilusKernel._setup_loop`` (``system/kernel.py:558-572``) registers all
  three on the event loop for every non-BACKTEST environment, dispatching to
  ``TradingNode._loop_sig_handler`` (``live/node.py:491-493``), which calls
  ``node.stop()``. ``TradingNode.__init__`` always supplies a loop
  (``live/node.py:65-76``), so the registration always happens on POSIX.
  This module therefore installs **no** handlers of its own: doing so would
  replace the native shutdown path with a worse copy of it. Graceful shutdown
  on SIGINT/SIGTERM is Nautilus's, and ``node.dispose()`` in a ``finally``
  plus the composition root's ``ExitStack`` complete it.
* **Exception logging inside the node is already provided** -- ``node.run()``
  logs through the kernel logger. What is added here is the *process exit
  contract*: a non-zero status and one clear line on stderr.

The exit contract:

===========================  ====  ==========================================
Outcome                      Code  Example
===========================  ====  ==========================================
Clean shutdown                  0  SIGTERM -> graceful stop
Configuration / environment     2  ``BREEZY_SITES`` unset, unknown site,
                                   malformed ``BREEZY_TRADER_ID``, station
                                   root on a network filesystem
Runtime failure                 1  the node raised while building or running
===========================  ====  ==========================================

A failure is always reported as a single human-readable line naming the
cause. Full tracebacks go to the ``logging`` module (``logger.exception``),
never to stderr as the only output, and never swallowed silently.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Protocol, TextIO

from nautilus_trader.config import TradingNodeConfig
from nautilus_trader.live.node import TradingNode

from breezy.ingest.gate import CachePersistenceMisconfiguredError
from breezy.ingest.http import ProxyEnvironmentError
from breezy.ingest.shared_state import SharedIngestState, SharedIngestStateError
from breezy.persistence.catalog import (
    FilesystemProbe,
    WriterLockFilesystemError,
    probe_filesystem,
)
from breezy.registry.sites import RegistryError
from breezy.runtime.composition import ingest_runtime
from breezy.runtime.node_config import NodeConfigError
from breezy.runtime.settings import SettingsError, load_settings

logger = logging.getLogger(__name__)

EXIT_OK = 0
EXIT_RUNTIME_ERROR = 1
EXIT_CONFIG_ERROR = 2

#: Failures that mean "this deployment is misconfigured", not "the run broke".
#: ``OSError`` is included because every startup resource this process opens --
#: the registry TOML, the SQLite state file, the catalog roots -- fails that way
#: when a path or permission is wrong, which is a configuration problem.
_CONFIG_ERRORS: tuple[type[BaseException], ...] = (
    SettingsError,
    NodeConfigError,
    RegistryError,
    SharedIngestStateError,
    WriterLockFilesystemError,
    CachePersistenceMisconfiguredError,
    ProxyEnvironmentError,
    OSError,
)


class Node(Protocol):
    """The `TradingNode` surface this module drives."""

    def build(self) -> None: ...

    def run(self) -> None: ...

    def dispose(self) -> None: ...


NodeFactory = Callable[[TradingNodeConfig], Node]
ProbeFactory = Callable[[Path], FilesystemProbe]


def _report(stderr: TextIO, prefix: str, exc: BaseException, *, expected: bool) -> None:
    """Write one clear line to ``stderr`` and route the traceback to logging.

    ``expected`` separates the two audiences. A misconfigured deployment is an
    operator problem: the named cause is the whole answer, and the traceback is
    noise, so it is logged at DEBUG. An unexpected failure is an engineering
    problem: the traceback is the answer, so it is logged at ERROR with
    ``exc_info``. Either way the traceback is never the process's ONLY output,
    and it is never silently discarded.
    """
    print(f"breezy: {prefix}: {exc}", file=stderr)
    level = logging.DEBUG if expected else logging.ERROR
    logger.log(level, "%s: %s", prefix, exc, exc_info=True)


def _run_node(config: TradingNodeConfig, node_factory: NodeFactory, stderr: TextIO) -> int:
    """Build, run and always dispose the node. Never raises."""
    node: Node | None = None
    try:
        node = node_factory(config)
        node.build()
        node.run()
        return EXIT_OK
    except BaseException as exc:  # noqa: BLE001 - the process exit contract lives here
        _report(stderr, "trading node failed", exc, expected=False)
        return EXIT_RUNTIME_ERROR
    finally:
        if node is not None:
            try:
                node.dispose()
            except Exception as exc:  # noqa: BLE001  # pragma: no cover - defensive
                _report(stderr, "error disposing the trading node", exc, expected=False)


def run(
    *,
    env: Mapping[str, str] | None = None,
    node_factory: NodeFactory = TradingNode,
    probe: ProbeFactory = probe_filesystem,
    stderr: TextIO | None = None,
    on_runtime: Callable[[SharedIngestState], None] | None = None,
) -> int:
    """Load settings, compose the runtime, run the node, and return an exit code.

    ``env``, ``node_factory`` and ``probe`` are injected so the whole contract
    -- including every failure path -- is exercisable without an event loop,
    a real filesystem probe, or the real process environment. ``on_runtime``
    is a composition-time observation hook; it takes part in no control flow.
    """
    out = sys.stderr if stderr is None else stderr

    try:
        settings = load_settings(env)
    except SettingsError as exc:
        _report(out, "configuration error", exc, expected=True)
        return EXIT_CONFIG_ERROR

    try:
        with ingest_runtime(settings, probe=probe) as runtime:
            if on_runtime is not None:
                on_runtime(runtime.shared)
            return _run_node(runtime.node_config, node_factory, out)
    except _CONFIG_ERRORS as exc:
        _report(out, "configuration error", exc, expected=True)
        return EXIT_CONFIG_ERROR
    except Exception as exc:  # noqa: BLE001 - the process exit contract lives here
        _report(out, "failed to start", exc, expected=False)
        return EXIT_RUNTIME_ERROR


def main() -> int:
    """Console-script entrypoint. Returns the process exit code."""
    return run()
