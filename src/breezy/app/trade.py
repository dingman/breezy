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
import logging
import os
import sys
from collections.abc import Mapping
from contextlib import ExitStack
from pathlib import Path
from typing import Final, TextIO

from nautilus_trader.live.node import TradingNode

from breezy.adapters.polymarket_us.factories import exec_config_from_env
from breezy.domain.climate_day import climate_day_for_instant
from breezy.registry.sites import default_registry
from breezy.runtime import trade_cli
from breezy.runtime.health import AlertPayload, emit_alert, resolve_alert_sink
from breezy.runtime.order_enablement import OrderSubmissionPermit, OrderSubmissionRefused
from breezy.runtime.settings import ORDERS_ENABLED_VAR, SettingsError, load_trade_settings
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

#: ``AlertPayload.event``/``site``/``severity`` for a refused live-trading
#: permit in ``main()`` -- the ONLY refusal here that continues the run in
#: shadow mode (an ``OrderSubmissionPermit`` refusal a few lines later is
#: FATAL and is not an alert candidate). ``site`` is ``"global"``, matching
#: ``component_health_watch.py``'s convention for a process-wide condition.
LIVE_TRADING_PERMIT_REFUSED_EVENT: Final[str] = "LIVE_TRADING_PERMIT_REFUSED"
LIVE_TRADING_PERMIT_REFUSED_SEVERITY: Final[str] = "WARN"
LIVE_TRADING_PERMIT_REFUSED_SITE: Final[str] = "global"

#: ``AlertPayload.detail`` is a small closed set of static reasons -- never
#: exception text, never a permit/config value (L-22 shape). ``main()`` has
#: exactly one catch site for ``issue_live_trading_permit``'s
#: ``LiveTradingPermissionError``, and distinguishing WHY it refused
#: (``orders_not_enabled`` / ``permit_expired`` / ``permit_missing``) would
#: mean parsing the exception's message -- not done here. So today this is
#: the one reason ever emitted; the name stays a closed enum for when a
#: second call site needs a different member.
LIVE_TRADING_PERMIT_REFUSED_DETAIL: Final[str] = "permit_missing"


#: ``main()``'s permit-audit lines run BEFORE ``trade_cli.run()`` ever
#: builds a ``TradingNode`` -- and it is that construction which both
#: installs ``runtime.logging_bridge`` on the ``breezy`` namespace AND
#: initialises NautilusTrader's own native logging subsystem (the
#: bridge's target ``Logger`` is a documented no-op until then). Without a
#: handler, an audit line logged prior to that point inherits the stdlib
#: root logger's default (WARNING, no handler), so it is silently
#: discarded -- not queued, not raised, never seen -- regardless of
#: whether the permit it describes was actually minted. That is the root
#: cause of the missing "live-trading permit issued"/"order submission
#: permit not issued" lines: the process's real stdout+stderr ARE
#: captured into the per-launch log file (``trade_supervisor.py::spawn``,
#: ``stdout=log_fh, stderr=STDOUT``), so a plain stdlib handler attached
#: directly here -- independent of Nautilus's own init order -- is
#: sufficient.
#:
#: The audit lines are logged through a DEDICATED logger
#: (``breezy.app.trade.boot``, below), never ``trade_cli.logger``
#: (``breezy.runtime.trade_cli``): ``trade_cli.logger`` is the same logger
#: ``trade_cli.run()`` uses for the whole node's runtime faults
#: (``trade_cli.py:208,222,243,262``), and once ``run()`` installs
#: ``runtime.logging_bridge`` on the ``breezy`` namespace, any handler left
#: attached directly to ``trade_cli.logger`` would print every one of
#: those lines twice for the node's entire life -- once raw, once via the
#: bridge. The dedicated boot logger keeps this handler scoped to the
#: boot-only audit lines and off ``trade_cli.logger`` entirely. Idempotent:
#: safe to call on every ``main()`` invocation.
_BOOT_LOG_FORMAT: Final[str] = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"

#: Name of the dedicated boot-audit logger -- deliberately NOT
#: ``trade_cli.logger`` (``breezy.runtime.trade_cli``); see the module
#: note above ``_BOOT_LOG_FORMAT``.
_BOOT_LOGGER_NAME: Final[str] = "breezy.app.trade.boot"
_boot_logger = logging.getLogger(_BOOT_LOGGER_NAME)


def _ensure_boot_logging_visible() -> None:
    """Attach a plain stderr handler to the dedicated boot-audit logger
    (``breezy.app.trade.boot``) so its INFO+ lines reach the process's own
    stdout/stderr from the first line of ``main()``, well before
    ``runtime.logging_bridge``/Nautilus's own logging subsystem exist.
    Never touches ``trade_cli.logger``, the ``breezy`` bridge namespace,
    or the root logger.
    """
    if any(isinstance(h, logging.StreamHandler) for h in _boot_logger.handlers):
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(_BOOT_LOG_FORMAT))
    _boot_logger.addHandler(handler)
    _boot_logger.setLevel(logging.INFO)


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
                after_build=lambda node: install_current_rung_hold_refusal_watch(node, strategies),
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
    are pure validation, so they agree. A settings load failure here always
    logs one unmistakable line and sets ``settings = None``; ``run``
    performs the SAME load and reports the real configuration error through
    its existing path, so the error is never duplicated or reported twice.
    If ``BREEZY_ORDERS_ENABLED=1`` was requested, the failure is additionally
    FATAL here (``EXIT_RUNTIME_ERROR``) rather than silently degrading to a
    node that can never submit.

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

    _ensure_boot_logging_visible()

    permit = None
    try:
        permit = issue_live_trading_permit(clock=LiveClock())
    except LiveTradingPermissionError as exc:
        _boot_logger.info("live-trading permit not issued: %s", exc)
        emit_alert(
            resolve_alert_sink(),
            AlertPayload(
                severity=LIVE_TRADING_PERMIT_REFUSED_SEVERITY,
                event=LIVE_TRADING_PERMIT_REFUSED_EVENT,
                site=LIVE_TRADING_PERMIT_REFUSED_SITE,
                detail=LIVE_TRADING_PERMIT_REFUSED_DETAIL,
            ),
        )

    try:
        settings = load_trade_settings()
    except SettingsError as exc:
        settings = None
        if os.environ.get(ORDERS_ENABLED_VAR) == "1":
            # The operator requested the order path
            # (``BREEZY_ORDERS_ENABLED=1``) but settings could not even be
            # validated -- a request that cannot be honoured must stop the
            # process loudly (same "requested but unminted" contract as the
            # ``OrderSubmissionRefused`` branch below), never run a node
            # that can never submit in silence. Substring matches
            # ``trade_supervisor_core.PERMIT_NOT_ISSUED_MARKER`` on purpose,
            # so the daily-relaunch supervisor classifies this exit-1 the
            # same deterministic way it already classifies a refused permit.
            _boot_logger.error(
                "order submission permit not issued: settings load failed (%s)",
                type(exc).__name__,
            )
            return EXIT_RUNTIME_ERROR
        # Orders were never requested (or the raw request can't be told from
        # here): ``run`` performs the SAME load and reports the real
        # configuration error through its existing path, so this is a
        # breadcrumb, not a duplicate report -- but it must never be silent.
        _boot_logger.info(
            "order submission permit not minted: settings load failed (%s)",
            type(exc).__name__,
        )

    order_submission_permit = None
    if settings is not None and settings.orders_enabled_requested:
        try:
            order_submission_permit = OrderSubmissionPermit.issue(
                settings=settings,
                live_trading_permit=permit,
                clock=LiveClock(),
            )
        except OrderSubmissionRefused as exc:
            _boot_logger.info("order submission permit not issued: %s", type(exc).__name__)
            return EXIT_RUNTIME_ERROR
        else:
            # Both permits are minted at this point: ``issue`` above
            # validated ``permit`` is a genuine, unexpired LiveTradingPermit,
            # so its two non-``repr=False`` fields (``issued_at_ns``,
            # ``expires_at_ns``) are the only values this line ever logs --
            # never ``operator_id`` or any of the five other repr=False
            # fields (security R2).
            ttl_s = (permit.expires_at_ns - permit.issued_at_ns) // 1_000_000_000
            _boot_logger.info(
                "live-trading permit issued issued_at_ns=%d expires_at_ns=%d ttl_s=%d",
                permit.issued_at_ns,
                permit.expires_at_ns,
                ttl_s,
            )
    elif settings is not None:
        # ``orders_enabled_requested`` is False: a legitimate shadow-mode
        # boot, not a failure -- but still a silent skip until now. Uses
        # "not minted" (never "not issued") so it never collides with
        # ``trade_supervisor_core.PERMIT_NOT_ISSUED_MARKER``, which must
        # only match a genuine refusal of an actual request.
        _boot_logger.info("order submission permit not minted: orders not requested")

    return run(
        live_trading_permit=permit,
        order_submission_permit=order_submission_permit,
    )
