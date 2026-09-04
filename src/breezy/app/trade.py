"""Composition root for ``breezy-trade`` (shadow-mode ``current_rung_hold``).

Owns the ONE submit-intent latch opener for the process lifetime: opens
``SqliteStateStore`` + ``open_submit_intent_latch`` exactly once, on the
main thread, inside an ``ExitStack`` that unwinds on every exit path, and
injects the same opened latch into (a) the strategy factory via
``open_trial_day_latch`` and (b) the exec client via
``PolymarketUSExecClientConfig.submit_intent_latch``. The exec client never
opens its own latch.

``orders_enabled`` is never set from env and is never passed to the config.
"""

from __future__ import annotations

import datetime as dt
import sys
from collections.abc import Mapping
from contextlib import ExitStack
from pathlib import Path
from typing import TextIO

from nautilus_trader.live.node import TradingNode

from breezy.adapters.polymarket_us.factories import exec_config_from_env
from breezy.domain.climate_day import climate_day_for_instant
from breezy.registry.sites import default_registry
from breezy.runtime import trade_cli
from breezy.runtime.order_enablement import OrderSubmissionPermit, OrderSubmissionRefused
from breezy.runtime.settings import SettingsError, load_trade_settings
from breezy.runtime.sqlite_store import SqliteStateStore
from breezy.runtime.submit_intent import (
    SubmitIntentLockError,
    SubmitIntentLockHeld,
    open_submit_intent_latch,
)
from breezy.runtime.trade_cli import EXIT_CONFIG_ERROR, EXIT_RUNTIME_ERROR, NodeFactory, _report
from breezy.strategy.current_rung_hold.composition import (
    build_current_rung_hold_strategies,
    install_current_rung_hold_refusal_watch,
    make_trial_day_latch_factory,
)
from breezy.strategy.current_rung_hold.config import SUPPORTED_STATIONS

_VENUE = "polymarket_us"


def _today_by_station() -> dict[str, dt.date]:
    registry = default_registry()
    now = dt.datetime.now(tz=dt.UTC)
    return {
        station: climate_day_for_instant(
            now, registry.climate_day_window(_VENUE, station).std_utc_offset_hours
        )
        for station in SUPPORTED_STATIONS
    }


def run(
    *,
    env: Mapping[str, str] | None = None,
    node_factory: NodeFactory = TradingNode,
    stderr: TextIO | None = None,
    live_trading_permit: object | None = None,
    order_submission_permit: OrderSubmissionPermit | None = None,
) -> int:
    """Load settings, compose strategies when the flag is on, run the node."""
    out = sys.stderr if stderr is None else stderr
    try:
        settings = load_trade_settings(env)
    except SettingsError as exc:
        _report(out, "configuration error", exc, expected=True)
        return EXIT_CONFIG_ERROR

    if not settings.current_rung_hold:
        return trade_cli.run(
            env=env,
            node_factory=node_factory,
            stderr=out,
            live_trading_permit=live_trading_permit,
            settings=settings,
        )

    try:
        exec_client_config = exec_config_from_env(env)
    except SettingsError as exc:
        _report(out, "configuration error", exc, expected=True)
        return EXIT_CONFIG_ERROR

    store_path = Path(str(exec_client_config.state_store_path))
    catalog_root = settings.catalog_root
    if catalog_root is None:
        _report(
            out,
            "configuration error",
            SettingsError("current_rung_hold is on but catalog_root is unset"),
            expected=True,
        )
        return EXIT_CONFIG_ERROR

    today_by_station = _today_by_station()
    try:
        with ExitStack() as stack:
            store = stack.enter_context(SqliteStateStore(store_path))
            latch = stack.enter_context(open_submit_intent_latch(store, store_path))
            factory = make_trial_day_latch_factory(latch)
            strategies = build_current_rung_hold_strategies(
                catalog_root=catalog_root,
                today_by_station=today_by_station,
                trial_day_latch_factory=factory,
                order_submission_permit=order_submission_permit,
            )
            return trade_cli.run(
                env=env,
                node_factory=node_factory,
                stderr=out,
                strategies=strategies,
                submit_intent_latch=latch,
                after_build=lambda node: install_current_rung_hold_refusal_watch(
                    node, strategies
                ),
                live_trading_permit=live_trading_permit,
                settings=settings,
                exec_client_config=exec_client_config,
            )
    except (SettingsError, OSError, SubmitIntentLockHeld, SubmitIntentLockError) as exc:
        _report(out, "configuration error", exc, expected=True)
        return EXIT_CONFIG_ERROR


def main() -> int:
    """Console-script entrypoint. Returns the process exit code.

    B7's ONE caller: this is the composition root the ``breezy-trade``
    console script actually enters (``pyproject.toml [project.scripts]``),
    so the live-trading permit is minted here, on the main thread, exactly
    once, and threaded through to ``trade_cli.run`` -- never re-minted, and
    never issued from ``breezy.runtime.trade_cli.main`` (a library
    entrypoint other callers also reach directly).

    B11's ONE caller: ``OrderSubmissionPermit.issue`` is minted here too,
    immediately beside the live-trading permit, when ``BreezyTradeSettings.
    orders_enabled_requested`` is True. Settings are loaded a second time
    here (``run`` loads its own copy) rather than threaded through, because
    this function must decide whether to mint the order-submission permit
    BEFORE ``run`` builds anything -- both loads read the same ``env`` and
    are pure validation, so they agree. A settings load failure here is
    swallowed (``settings = None``): ``run`` performs the SAME load and
    reports the real configuration error through its existing path, so the
    error is never duplicated or reported twice.

    A refusal from ``OrderSubmissionPermit.issue`` is FATAL, unlike a
    live-trading-permit refusal (which degrades to shadow mode): the
    operator explicitly requested the order path
    (``BREEZY_ORDERS_ENABLED=1``) via ``orders_enabled_requested``, so a
    request that cannot be honoured must stop the process loudly rather
    than silently run in shadow mode with the operator's intent unmet. The
    log line names the refusal class only, never a value (L-22 shape).
    """
    from nautilus_trader.common.component import LiveClock

    from breezy.adapters.polymarket_us.safety import (
        LiveTradingPermissionError,
        issue_live_trading_permit,
    )

    permit = None
    try:
        permit = issue_live_trading_permit(clock=LiveClock())
    except LiveTradingPermissionError as exc:
        trade_cli.logger.info("live-trading permit not issued: %s", exc)

    try:
        settings = load_trade_settings()
    except SettingsError:
        settings = None

    order_submission_permit = None
    if settings is not None and settings.orders_enabled_requested:
        try:
            order_submission_permit = OrderSubmissionPermit.issue(
                settings=settings,
                live_trading_permit=permit,
                clock=LiveClock(),
            )
        except OrderSubmissionRefused as exc:
            trade_cli.logger.info(
                "order submission permit not issued: %s", type(exc).__name__
            )
            return EXIT_RUNTIME_ERROR

    return run(
        live_trading_permit=permit,
        order_submission_permit=order_submission_permit,
    )
