"""The `breezy-quote-tape` console entrypoint: record Polymarket.us quotes.

A SEPARATE process from `breezy` (the NWS ingestion entrypoint), for the same
reason :func:`breezy.runtime.node_config.build_quote_tape_node_config` is a
separate function: the two roles have different configuration requirements and
different failure consequences. The weather collector must start on a host with
no venue configuration; this one must refuse to start without it. One process
serving both would make venue configuration a hard startup requirement of the
collector -- a regression this repo has already taken once.

What this process does, in full: connect a READ-ONLY market-data client to the
Polymarket.us markets socket and let Nautilus's native streaming writer persist
every ``QuoteTick`` (and the ``BinaryOption`` definitions needed to read them
back) to a ``ParquetDataCatalog`` root. It has no strategy, no Actor, and no
execution client -- :func:`run` registers a data-client factory and nothing
else, and the test suite asserts the exec-client registration count is zero.

Null hypothesis, checked before writing any of it:

* **Persistence is native.** ``NautilusKernel`` builds a
  ``StreamingFeatherWriter`` from ``TradingNodeConfig.streaming`` and
  subscribes it to the whole message bus (``system/kernel.py:508-509``,
  ``:586-604``). No persistence code is authored here or anywhere in Breezy.
* **Signal handling is native.** ``NautilusKernel._setup_loop``
  (``system/kernel.py:558-572``) registers SIGTERM/SIGINT/SIGABRT for every
  non-BACKTEST environment. This module installs none of its own.

Reading the tape back (deliberately NOT automated here)
-------------------------------------------------------
The writer stages feather under ``<catalog_root>/live/<instance_id>/``, one
directory per run. Converting a run into the catalog's parquet layout is a
single native call, and is left to the reader so that this process never
rewrites data it has already durably written::

    catalog = ParquetDataCatalog(catalog_root)
    catalog.convert_stream_to_data(instance_id, QuoteTick, subdirectory="live")
    catalog.convert_stream_to_data(instance_id, BinaryOption, subdirectory="live")

``instance_id`` values are the directory names under ``<catalog_root>/live/``.
The fact that there is one per run is useful rather than incidental: it is an
honest record of how many separate capture sessions there were, and therefore
of where the tape is discontinuous. See
``PolymarketUSDataClient.tape_gaps`` for gaps WITHIN a session.

Market discovery
----------------
The recorder discovers Polymarket.us weather markets through ``GET /v1/markets``
inside the read-only data adapter. The operator supplies endpoints and a reload
cadence, not per-day market slugs. Discovery remains fail-closed: a zero-market
cycle or an uncorroborated weather slug is a runtime fault, not a quiet tape.

The exit contract matches ``breezy.runtime.cli``:

===========================  ====  ==========================================
Outcome                      Code  Example
===========================  ====  ==========================================
Clean shutdown                  0  SIGTERM -> graceful stop
Configuration / environment     2  ``POLYMARKET_US_WS_URL`` unset, malformed
                                   ``BREEZY_TRADER_ID``, unreadable key file
Runtime failure                 1  the node raised while building or running
===========================  ====  ==========================================
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Callable, Mapping
from typing import Protocol, TextIO

from nautilus_trader.config import TradingNodeConfig
from nautilus_trader.live.node import TradingNode

from breezy.adapters.polymarket_us.factories import (
    POLYMARKET_US_CLIENT_NAME,
    PolymarketUSLiveDataClientFactory,
    config_from_env,
)
from breezy.persistence.catalog import CatalogPathError
from breezy.runtime.logging_bridge import install as install_logging_bridge
from breezy.runtime.logging_bridge import uninstall as uninstall_logging_bridge
from breezy.runtime.node_config import (
    NodeConfigError,
    build_quote_tape_node_config,
    prepare_quote_tape_root,
)
from breezy.runtime.quote_tape_disk_monitor import (
    DiskUsageProbe,
    QuoteTapeDiskMonitor,
    QuoteTapeDiskMonitorConfig,
)
from breezy.runtime.quote_tape_disk_monitor import (
    disk_usage_probe as default_disk_usage_probe,
)
from breezy.runtime.settings import (
    PolymarketUSQuoteTapeSettings,
    SettingsError,
    load_quote_tape_settings,
)

logger = logging.getLogger(__name__)

EXIT_OK = 0
EXIT_RUNTIME_ERROR = 1
EXIT_CONFIG_ERROR = 2

#: Failures that mean "this deployment is misconfigured", not "the run broke".
#: ``OSError`` is included because the credential key file this process opens
#: at ``build()`` time fails that way when its path or mode is wrong, which is
#: an operator problem rather than an engineering one.
_CONFIG_ERRORS: tuple[type[BaseException], ...] = (
    SettingsError,
    NodeConfigError,
    CatalogPathError,
    OSError,
)


class Node(Protocol):
    """The `TradingNode` surface this module drives."""

    def add_data_client_factory(self, name: str, factory: type) -> None: ...

    def build(self) -> None: ...

    def run(self) -> None: ...

    def dispose(self) -> None: ...


NodeFactory = Callable[[TradingNodeConfig], Node]


def _report(stderr: TextIO, prefix: str, exc: BaseException, *, expected: bool) -> None:
    """Write one clear line to ``stderr`` and route the traceback to logging."""
    print(f"breezy-quote-tape: {prefix}: {exc}", file=stderr)
    level = logging.DEBUG if expected else logging.ERROR
    logger.log(level, "%s: %s", prefix, exc, exc_info=True)


def _run_node(config: TradingNodeConfig, node_factory: NodeFactory, stderr: TextIO) -> int:
    """Build, run and ALWAYS dispose the node. Never raises.

    ``add_data_client_factory`` takes the registration NAME and the factory
    CLASS (``live/node.py:230``), and that name must equal the key used in
    ``TradingNodeConfig.data_clients`` -- otherwise the builder resolves
    nothing and the process runs happily, recording an empty tape.
    """
    node: Node | None = None
    try:
        node = node_factory(config)
        node.add_data_client_factory(
            POLYMARKET_US_CLIENT_NAME, PolymarketUSLiveDataClientFactory
        )
        node.build()
        node.run()
        return EXIT_OK
    except KeyboardInterrupt:
        # A deliberate stop is NOT a failure. `TradingNode.run` catches only
        # `RuntimeError` (`live/node.py:293-300`), and although the kernel
        # installs SIGINT/SIGTERM handlers for a LIVE environment
        # (`system/kernel.py:558-572`), a signal that arrives before the loop is
        # running -- during `build()`, or between `build()` and `run()` --
        # surfaces here as `KeyboardInterrupt`. Reporting that as exit 1 would
        # tell systemd, and the operator watching a months-long recorder, that
        # the run broke when it was simply stopped.
        print("breezy-quote-tape: interrupted; shutting down", file=stderr)
        return EXIT_OK
    except BaseException as exc:  # noqa: BLE001 - the process exit contract lives here
        _report(stderr, "quote-tape node failed", exc, expected=False)
        return EXIT_RUNTIME_ERROR
    finally:
        if node is not None:
            try:
                node.dispose()
            except Exception as exc:  # noqa: BLE001  # pragma: no cover - defensive
                _report(stderr, "error disposing the quote-tape node", exc, expected=False)


def _monitor_config(settings: PolymarketUSQuoteTapeSettings) -> QuoteTapeDiskMonitorConfig:
    """Build monitor config from the validated quote-tape settings object."""
    return QuoteTapeDiskMonitorConfig(
        catalog_root=settings.catalog_root,
        min_free_bytes_warning=settings.min_free_bytes_warning,
        min_free_bytes_error=settings.min_free_bytes_error,
        max_file_bytes_warning=settings.max_file_bytes_warning,
        max_file_bytes_error=settings.max_file_bytes_error,
        check_interval_seconds=settings.disk_check_interval_seconds,
    )


def run(
    *,
    env: Mapping[str, str] | None = None,
    node_factory: NodeFactory = TradingNode,
    disk_usage_probe: DiskUsageProbe = default_disk_usage_probe,
    stderr: TextIO | None = None,
) -> int:
    """Load settings, build the node config, run the recorder, return an exit code.

    ``env`` and ``node_factory`` are injected so every path -- including every
    failure path -- is exercisable without an event loop or a socket.

    Both loaders are called BEFORE any node is constructed, so a
    half-provisioned host exits 2 having built nothing. The venue variables
    are read by
    :func:`breezy.adapters.polymarket_us.factories.config_from_env`, which
    already owns the section 7 environment contract; they are deliberately not
    re-read here, because a second reader is a second competing policy for the
    same variables.
    """
    out = sys.stderr if stderr is None else stderr
    install_logging_bridge()
    try:
        try:
            settings = load_quote_tape_settings(env)
            data_client_config = config_from_env(env)
            # BEFORE the node exists. Nautilus reaches the streaming path
            # through `fsspec`, whose `makedirs` honours the process umask and
            # performs no symlink check, so the root has to be created on our
            # terms first -- 0700, and refused outright if it is a symlink.
            prepare_quote_tape_root(settings.catalog_root)
            config = build_quote_tape_node_config(settings, data_client_config)
            reload_override = data_client_config.instrument_reload_interval_mins
            logger.info(
                "quote-tape recording with Polymarket.us discovery reload cadence: %s",
                "derived from the discovered market set (venue endDate boundaries)"
                if reload_override is None
                else f"operator override, {reload_override} minute(s)",
            )
        except _CONFIG_ERRORS as exc:
            _report(out, "configuration error", exc, expected=True)
            return EXIT_CONFIG_ERROR

        monitor = QuoteTapeDiskMonitor(
            _monitor_config(settings),
            disk_usage_probe=disk_usage_probe,
        )
        monitor.start()
        try:
            return _run_node(config, node_factory, out)
        finally:
            monitor.stop()
    finally:
        uninstall_logging_bridge()


def main() -> int:
    """Console-script entrypoint. Returns the process exit code."""
    return run()
