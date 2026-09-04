"""The `breezy-trade` console entrypoint: the Breezy trading process.

EXEC SPINE R-2 (process shell) / W (execution client wiring). A FOURTH process
alongside `breezy` (weather ingestion), `breezy-quote-tape` (venue tape
recorder) and `breezy-quote-tape-preflight`, for the reason each of those is
separate: different configuration requirements, different failure
consequences. The weather collector must start on a host with no venue
configuration; this one must refuse to start without venue configuration AND
without a trading identity of its own (``BREEZY_TRADE_TRADER_ID``, no default
-- see ``breezy.runtime.settings.TRADE_TRADER_ID_VAR``).

WHAT THIS PROCESS CANNOT DO, STILL
-----------------------------------
It cannot submit an order. Not "does not"; cannot. EXEC SPINE W registers a
real execution-client factory (``PolymarketUSLiveExecClientFactory``) so the
process now RECONCILES the venue account and REFUSES every order -- but no
strategy and no execution algorithm exist anywhere on this path, and
:func:`breezy.runtime.node_config.build_trade_node_config` states both as
empty literals. The execution client's own cage --
``PolymarketUSExecutionClient._submit_order``/``_cancel_order`` carry an
unconditional denial body, and its other four lifecycle coroutines raise -- is
unchanged by W. This module is still a process SHELL in the sense that
matters: it starts, reconciles, refuses, reaches ``RUNNING``, and stops
cleanly.

That is not a small thing to have. The repo's standing failure mode is a green
suite over a deployment that never started, and every subsequent increment
lands inside a process that has been proven to come up.

Null hypothesis, checked before writing any of it: **Nautilus already provides
the process shell.** ``TradingNode``/``NautilusKernel`` build the engines, own
start and stop, and install SIGTERM/SIGINT/SIGABRT handlers for every
non-BACKTEST environment (``system/kernel.py:558-572``). This module installs
none of its own and authors no process machinery. It loads settings, builds
one config, registers the read-only data-client factory and the execution-
client factory, and translates the outcome into an exit code.

The exit contract matches ``breezy.runtime.quote_tape_cli``:

===========================  ====  ==========================================
Outcome                      Code  Example
===========================  ====  ==========================================
Clean shutdown                  0  SIGTERM -> graceful stop
Configuration / environment     2  ``BREEZY_TRADE_TRADER_ID`` unset,
                                   ``POLYMARKET_US_USER_AGENT`` unset,
                                   ``POLYMARKET_US_ACCOUNT_NUMBER`` unset,
                                   malformed trader id, unreadable key file
Runtime failure                 1  the node raised while building or running,
                                   OR the run ended behind a LATCHED fatal
                                   market-data fault, OR the run ended behind a
                                   LATCHED fatal execution-client fault (a
                                   failed ``_connect`` -- EXEC SPINE risk 2)
===========================  ====  ==========================================

The last row is the one that needs stating. ``TradingNode.run()`` returns
``None`` (``live/node.py:283-302``) and the kernel keeps no record of WHY it
stopped, so a node that shut itself down after losing its market-data feed, or
whose execution client never finished connecting, returns exactly like one
stopped by an operator SIGTERM. For a trading process that difference is
larger than it is for a recorder: a trader running blind, or one that never
reconciled, is a trader whose next decision is made on stale or absent state.
The process-scoped latches written by the data client and the execution
client at the instant each detects its own unrecoverable fault are where that
one bit survives, and this module is where it becomes the answer to
``systemctl status``.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Protocol, TextIO

from nautilus_trader.common.actor import Actor
from nautilus_trader.config import TradingNodeConfig
from nautilus_trader.live.node import TradingNode
from nautilus_trader.model.identifiers import ClientId
from nautilus_trader.trading.strategy import Strategy

from breezy.adapters.polymarket_us.exec_fault import (
    clear_fatal_exec_fault,
    fatal_exec_fault,
    record_fatal_exec_fault,
)
from breezy.adapters.polymarket_us.factories import (
    POLYMARKET_US_CLIENT_NAME,
    PolymarketUSLiveDataClientFactory,
    PolymarketUSLiveExecClientFactory,
    config_from_env,
    exec_config_from_env,
)
from breezy.adapters.polymarket_us.feed_fault import (
    clear_fatal_feed_fault,
    fatal_feed_fault,
)
from breezy.runtime.account_presence_halt import install_account_presence_halt
from breezy.runtime.backtest_order_guard import install_live_order_guard
from breezy.runtime.component_health_watch import install_component_degraded_alert
from breezy.runtime.logging_bridge import install as install_logging_bridge
from breezy.runtime.logging_bridge import uninstall as uninstall_logging_bridge
from breezy.runtime.node_config import NodeConfigError, build_trade_node_config
from breezy.runtime.observation_composition import build_live_observation_actors
from breezy.runtime.settings import (
    SettingsError,
    load_trade_settings,
    proxy_env_check_enabled,
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
    OSError,
)


class Node(Protocol):
    """The `TradingNode` surface this module drives.

    EXEC SPINE W adds ``add_exec_client_factory``: the trading process now
    registers exactly one execution-client factory, alongside the read-only
    data client. That is still not an order path -- ``strategies=[]`` and
    ``exec_algorithms=[]`` stay pinned in ``build_trade_node_config``, so
    nothing calls ``submit_order`` -- it is the client that RECONCILES and
    REFUSES.

    R-6a adds ``kernel``, read only AFTER ``build()`` to install the
    long-only order guard -- see ``_run_node``. Untyped (``Any``) rather than
    a hand-written Protocol: ``NautilusKernel`` (`live/node.py:80-82`) ships
    no stub, and a Protocol built to match it structurally fails mypy's
    conformance check for `TradingNode` in a way a real stub would not --
    the SAME reason :func:`install_order_guard` leaves ``engine.kernel``
    untyped for a ``BacktestEngine``.
    """

    kernel: Any

    @property
    def trader(self) -> Any:
        """BL-24 Seam B: ``trader.add_actor`` registers the observation Actors
        natively before ``build()``. A property because ``TradingNode.trader``
        is one (``live/node.py:139``); untyped for the same reason as
        ``kernel`` -- ``Trader`` (``trading/trader.py``) ships no stub this
        Protocol could conform to."""
        ...

    def add_data_client_factory(self, name: str, factory: type) -> None: ...

    def add_exec_client_factory(self, name: str, factory: type) -> None: ...

    def build(self) -> None: ...

    def run(self) -> None: ...

    def dispose(self) -> None: ...


NodeFactory = Callable[[TradingNodeConfig], Node]


def _report(stderr: TextIO, prefix: str, exc: BaseException, *, expected: bool) -> None:
    """Write one clear line to ``stderr`` and route the traceback to logging."""
    print(f"breezy-trade: {prefix}: {exc}", file=stderr)
    level = logging.DEBUG if expected else logging.ERROR
    logger.log(level, "%s: %s", prefix, exc, exc_info=True)


def _exit_code_for_completed_run(stderr: TextIO) -> int:
    """Translate a stopped node into an exit status the supervisor can read.

    A ``KeyboardInterrupt`` is routed through here too: a fatal fault followed
    by a Ctrl-C is still a failed run, and reporting the interrupt would hide
    the cause.

    The execution fault is checked FIRST. Without this check, EXEC SPINE risk
    2 is real: a failed ``_connect`` (a durability failure, or -- as measured
    live against the venue -- an account-balance read returning 500/503) is
    swallowed by ``LiveExecutionClient``'s own task-completion handler
    (``nautilus_trader/live/execution_client.py:212-226``), which logs the
    exception and simply skips marking the client connected. Nothing
    downstream re-raises it, ``_await_engines_connected``
    (``nautilus_trader/system/kernel.py:1310-1316``) only WARNS on the
    resulting timeout, and the node stops as if nothing had gone wrong. Absent
    this check the process would exit ``EXIT_OK`` having never reconciled and
    never traded, with a supervisor reading success.
    """
    exec_fault = fatal_exec_fault()
    if exec_fault is not None:
        print(
            f"breezy-trade: FATAL execution-client fault in {exec_fault.component}: "
            f"{exec_fault.reason}. The trading process shut down.",
            file=stderr,
        )
        logger.error(
            "fatal execution-client fault in %s: %s", exec_fault.component, exec_fault.reason
        )
        return EXIT_RUNTIME_ERROR

    fault = fatal_feed_fault()
    if fault is None:
        return EXIT_OK

    print(
        f"breezy-trade: FATAL market-data fault in {fault.component}: {fault.reason}. "
        "The trading process shut down.",
        file=stderr,
    )
    logger.error("fatal market-data fault in %s: %s", fault.component, fault.reason)
    return EXIT_RUNTIME_ERROR


def _order_guard_reporter(stderr: TextIO) -> Callable[[ValueError], None]:
    """Build the ``on_refusal`` callback R-6a's live installer requires.

    Reports AT THE MOMENT of refusal, not only via the latch -- latch-then-
    re-raise alone is not enough on either failure path: on the engine-queue
    path ``os._exit(1)`` (a failed non-``RuntimeError`` swallowed elsewhere in
    the kernel) beats ``_exit_code_for_completed_run``, so the ``FATAL`` line
    printed there would never run; and on a ``LiveClock`` timer callback the
    exception is discarded outright and the process exits 0, so the latch
    written here is the only signal that survives that path. ``flush=True``
    on a line-buffered ``stderr`` makes the write complete before either exit
    route can beat it.
    """

    def _report(exc: ValueError) -> None:
        print(f"breezy-trade: FATAL order-guard refusal: {exc}", file=stderr, flush=True)
        record_fatal_exec_fault(POLYMARKET_US_CLIENT_NAME, str(exc))
        logger.error("order-guard refusal: %s", exc)

    return _report


def _account_halt_reporter(stderr: TextIO) -> Callable[[str], None]:
    """Build the ``on_halt`` callback R-7-PRE's installer requires.

    A halt is not a tidy shutdown, so it gets the same treatment as an
    order-guard refusal: one line on ``stderr`` at the instant it happens, and
    the process-scoped exec-fault latch, so the run cannot end in ``EXIT_OK``
    while the node was refusing every order. ``flush=True`` for the same reason
    :func:`_order_guard_reporter` uses it -- an exit route must not beat the
    write.
    """

    def _report(reason: str) -> None:
        print(f"breezy-trade: FATAL account-presence halt: {reason}", file=stderr, flush=True)
        record_fatal_exec_fault(POLYMARKET_US_CLIENT_NAME, reason)
        logger.error("account-presence halt: %s", reason)

    return _report


def _exec_client_refusal_reader(node: Node) -> Callable[[], tuple[str, ...]]:
    """Build the ``reasons`` reader R-6c's degraded-alert subscriber requires.

    Resolved LAZILY, at the instant the alert fires, for two reasons. The
    refusals do not exist yet at wiring time -- ``_connect`` has not run --
    and holding the client object in a closure from ``build()`` onward would
    outlive the node's own registry for no benefit.

    ``ExecutionEngine._clients`` is a ``cdef readonly`` dict
    (``$NT/execution/engine.pxd:52``): read-only by declaration, and already
    the idiom ``tests/contract/test_exec_client_wiring_contract.py`` uses to
    reach the registered client. There is no public accessor -- the engine
    exposes ``registered_clients`` (``ClientId``\\ s only, ``engine.pyx:212``)
    and nothing that returns the object.

    A missing client yields ``()``, never an exception: this reader runs
    inside a message-bus handler, and a degraded component must still produce
    its alert even if the lookup comes up empty.
    """

    def _read() -> tuple[str, ...]:
        client = node.kernel.exec_engine._clients.get(ClientId(POLYMARKET_US_CLIENT_NAME))
        if client is None:
            return ()
        return tuple(client.trading_refusals)

    return _read


def _run_node(
    config: TradingNodeConfig,
    node_factory: NodeFactory,
    stderr: TextIO,
    *,
    actors: Sequence[Actor] = (),
    strategies: Sequence[Strategy] = (),
    after_build: Callable[[Node], None] | None = None,
) -> int:
    """Build, run and ALWAYS dispose the node. Never raises.

    BL-24 Seam B: ``actors`` -- the NWS observation Actors, present only
    when ``BREEZY_LIVE_OBSERVATIONS=1`` -- are registered through the NATIVE
    ``node.trader.add_actor`` BEFORE ``build()``, exactly as
    ``composition.build_ingest_node`` registers the ingest Actors.
    ``build_trade_node_config`` keeps ``actors=[]``; these are not an order
    path (an Actor is not a Strategy and cannot ``submit_order``).

    Shadow-mode ``current_rung_hold`` strategies -- constructed ABOVE this
    module by ``breezy.app.trade`` -- are registered the same way, through
    the NATIVE ``node.trader.add_strategy`` BEFORE ``build()``
    (``trading/trader.py:375-420``). ``build_trade_node_config`` keeps
    ``strategies=[]``; these are already-built objects, never an order path
    (``orders_enabled`` stays False and is unreachable from env).

    ``add_data_client_factory``/``add_exec_client_factory`` take the
    registration NAME and the factory CLASS (``live/node.py:230``, and the
    execution equivalent), and that name must equal the key used in
    ``TradingNodeConfig.data_clients``/``exec_clients``
    (``live/node_builder.py:163,177``, ``:201-246``) -- otherwise the builder
    resolves nothing, logs an error nobody reads, and the process runs happily
    with no market data, or no execution client, at all.

    Exactly TWO factories are registered here: the read-only data client, and
    -- as of EXEC SPINE W -- the reconciling, order-refusing execution client.
    Neither registration is an order path: see the ``Node`` protocol's
    docstring.

    R-6a installs the long-only order guard onto ``node.kernel.msgbus`` AFTER
    ``build()``, the same shape :func:`~breezy.runtime.backtest_order_guard.
    install_order_guard` uses for a ``BacktestEngine`` (``engine.kernel.
    msgbus``). It is a ``msgbus.subscribe(...)``, not an ``Actor`` --
    ``actors=[]`` in ``build_trade_node_config`` stays an untouched empty
    literal, and nothing here is a new order path: this node still cannot
    call ``submit_order`` (see the ``Node`` protocol's docstring).

    The ``on_refusal=_order_guard_reporter(stderr)`` argument reports a
    refusal to ``stderr`` and the exec-fault latch AT THE INSTANT it fires,
    then the guard still re-raises -- see that function's own docstring for
    why the latch alone, checked only after the node stops, is not enough.

    R-7-PRE installs :func:`~breezy.runtime.account_presence_halt.
    install_account_presence_halt` in the SAME idiom, and this call site is
    load-bearing rather than incidental. Nautilus's
    ``_check_orders_risk_for_account`` returns ``True`` -- order ALLOWED -- when
    ``cache.account_for_venue(...)`` is ``None``, and Nautilus is immutable, so
    the only available denial is the native ``TradingState.HALTED``. Nothing in
    the framework enters that state on its own; this line is what does.
    ``tests/contract/test_account_presence_halt_contract.py`` pins it, so R-7
    -- which gives the execution client's ``_submit_order`` a real body and
    removes the standing refusal that currently masks the fail-open -- cannot
    drop it by accident.
    """
    node: Node | None = None
    try:
        node = node_factory(config)
        node.add_data_client_factory(
            POLYMARKET_US_CLIENT_NAME, PolymarketUSLiveDataClientFactory
        )
        node.add_exec_client_factory(
            POLYMARKET_US_CLIENT_NAME, PolymarketUSLiveExecClientFactory
        )
        for actor in actors:
            node.trader.add_actor(actor)
        for strategy in strategies:
            node.trader.add_strategy(strategy)
        node.build()
        install_live_order_guard(
            node.kernel.portfolio,
            node.kernel.cache,
            node.kernel.msgbus,
            on_refusal=_order_guard_reporter(stderr),
        )
        install_component_degraded_alert(
            node.kernel.msgbus,
            component_id=POLYMARKET_US_CLIENT_NAME,
            reasons=_exec_client_refusal_reader(node),
        )
        install_account_presence_halt(
            node.kernel.msgbus,
            node.kernel.cache,
            node.kernel.risk_engine,
            on_halt=_account_halt_reporter(stderr),
        )
        if after_build is not None:
            after_build(node)
        node.run()
        return _exit_code_for_completed_run(stderr)
    except KeyboardInterrupt:
        # A deliberate stop is NOT a failure. `TradingNode.run` catches only
        # `RuntimeError` (`live/node.py:293-300`), and although the kernel
        # installs SIGINT/SIGTERM handlers for a LIVE environment
        # (`system/kernel.py:558-572`), a signal that arrives before the loop
        # is running -- during `build()`, or between `build()` and `run()` --
        # surfaces here as `KeyboardInterrupt`. Reporting that as a failure
        # would tell systemd the run broke when it was simply stopped.
        print("breezy-trade: interrupted; shutting down", file=stderr)
        return _exit_code_for_completed_run(stderr)
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
    stderr: TextIO | None = None,
    strategies: Sequence[Strategy] = (),
    submit_intent_latch: object | None = None,
    after_build: Callable[[Node], None] | None = None,
) -> int:
    """Load settings, build the node config, run the node, return an exit code.

    ``env`` and ``node_factory`` are injected so every path -- including every
    failure path -- is exercisable without an event loop or a socket.

    Both loaders run BEFORE any node is constructed, so a half-provisioned
    host exits 2 having built nothing. The venue variables are read by
    :func:`breezy.adapters.polymarket_us.factories.config_from_env`, which
    already owns the section 7 environment contract; they are deliberately not
    re-read here, because a second reader is a second competing policy for the
    same variables.
    """
    out = sys.stderr if stderr is None else stderr
    install_logging_bridge()
    # THIS run's fault, never an inherited one. The latch is process-scoped
    # and a stale value would fail a healthy run.
    clear_fatal_feed_fault()
    clear_fatal_exec_fault()
    try:
        try:
            settings = load_trade_settings(env)
            data_client_config = config_from_env(env)
            exec_client_config = exec_config_from_env(env)
            config = build_trade_node_config(
                settings,
                data_client_config,
                exec_client_config,
                submit_intent_latch=submit_intent_latch,
            )
        except _CONFIG_ERRORS as exc:
            _report(out, "configuration error", exc, expected=True)
            return EXIT_CONFIG_ERROR

        actors: Sequence[Actor] = ()
        if settings.live_observations:
            actors = build_live_observation_actors(check_proxy_env=proxy_env_check_enabled(env))
        return _run_node(
            config,
            node_factory,
            out,
            actors=actors,
            strategies=strategies,
            after_build=after_build,
        )
    finally:
        uninstall_logging_bridge()


def main() -> int:
    """Console-script entrypoint. Returns the process exit code."""
    return run()
