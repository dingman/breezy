"""``app/trade.py::main`` permit-issuance and refusal logging.

A session-independent daily relaunch supervisor
(``docs/plans/TRADE_NODE_DAILY_RELAUNCH_2026-09-04.md``) must gate on a
Breezy-owned signal, not process liveness: before this module, the ONLY
permit log in ``main()`` was the refusal at INFO
(``"live-trading permit not issued: %s"``), so a node that reaches RUNNING
in shadow mode was indistinguishable, from the log alone, from one that is
actually live-trading.

This module adds the missing positive signal (both permits minted -> one
INFO line naming only the two non-sensitive ``LiveTradingPermit`` fields,
``issued_at_ns``/``expires_at_ns``, security R2) and the missing operator
alert on the refusal path that continues in shadow mode (a WARN through the
existing alert sink, ``detail`` a static closed-set reason, never exception
text).

``main()`` is exercised directly (not ``run()``): ``trade_module.run`` and
``trade_module.load_trade_settings`` are monkeypatched to isolate the
permit-issuance and logging behaviour from strategy/node construction,
which is out of scope here and already covered by
``test_trade_cli_current_rung_hold.py``. The live-trading permit itself is
minted for real, through ``issue_live_trading_permit``, using the same
``enable_operator_gate``/``operator_control_env`` rig as
``test_order_submission_permit_issuance.py`` -- reused, not reinvented, per
that module's own docstring precedent.
"""

from __future__ import annotations

import logging
import re
import sys
from dataclasses import dataclass

import pytest

from breezy.adapters.polymarket_us.operator_controls import (
    MAX_DAILY_BUDGET_USD_ENV_VAR,
    MAX_POSITION_COST_USD_ENV_VAR,
)
from breezy.adapters.polymarket_us.safety import PERMIT_TTL_NS, TRADING_ENABLED_ENV_VAR
from breezy.app import trade as trade_module
from breezy.runtime import trade_cli
from breezy.runtime.order_enablement import OrderSubmissionPermit
from breezy.runtime.settings import ORDERS_ENABLED_VAR, SettingsError
from breezy.runtime.trade_cli import EXIT_RUNTIME_ERROR
from tests.unit.operator_control_env import operator_control_env
from tests.unit.test_polymarket_us_permit_issuance import enable_operator_gate
from tests.unit.test_polymarket_us_submit_order_chain import (
    write_canonical_verified,  # noqa: F401 -- reused fixture, see module docstring
)

#: Values `enable_operator_gate`'s defaults plant in the environment for the
#: live-trading permit -- asserted ABSENT from every captured log line, the
#: same shape as the R2 test in `test_polymarket_us_permit_issuance.py`.
_SENSITIVE_VALUES = ("operator@example.com", "5.00", "1000.00", "100")


@dataclass(frozen=True, slots=True)
class _FakeSettings:
    """The narrow ``SettingsLike`` surface ``main()``/``issue`` need."""

    orders_enabled_requested: bool = True
    current_rung_hold: bool = True
    live_observations: bool = True


def test_main_logs_live_trading_permit_issued_when_both_permits_are_minted(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    enable_operator_gate(monkeypatch)
    monkeypatch.setattr(trade_module, "load_trade_settings", lambda: _FakeSettings())

    captured: list[dict[str, object]] = []

    def _fake_run(**kwargs: object) -> int:
        captured.append(kwargs)
        return 0

    monkeypatch.setattr(trade_module, "run", _fake_run)

    with (
        operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "1000.00"),
        operator_control_env(MAX_POSITION_COST_USD_ENV_VAR, "10.00"),
        caplog.at_level(logging.INFO),
    ):
        exit_code = trade_module.main()

    assert exit_code == 0
    assert len(captured) == 1
    order_submission_permit = captured[0]["order_submission_permit"]
    assert isinstance(order_submission_permit, OrderSubmissionPermit)
    assert captured[0]["live_trading_permit"] is not None

    issued_records = [
        r for r in caplog.records if r.getMessage().startswith("live-trading permit issued")
    ]
    assert len(issued_records) == 1
    message = issued_records[0].getMessage()

    match = re.fullmatch(
        r"live-trading permit issued issued_at_ns=(\d+) expires_at_ns=(\d+) ttl_s=(\d+)",
        message,
    )
    assert match is not None, message
    issued_at_ns, expires_at_ns, ttl_s = (int(group) for group in match.groups())
    assert expires_at_ns - issued_at_ns == PERMIT_TTL_NS
    assert ttl_s == PERMIT_TTL_NS // 1_000_000_000

    for value in _SENSITIVE_VALUES:
        assert value not in caplog.text, f"{value!r} leaked into a log record"


def test_main_emits_warn_alert_when_live_trading_permit_refused_and_continues_in_shadow_mode(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.delenv(TRADING_ENABLED_ENV_VAR, raising=False)
    monkeypatch.setattr(
        trade_module,
        "load_trade_settings",
        lambda: _FakeSettings(orders_enabled_requested=False),
    )

    captured: list[dict[str, object]] = []

    def _fake_run(**kwargs: object) -> int:
        captured.append(kwargs)
        return 0

    monkeypatch.setattr(trade_module, "run", _fake_run)

    with caplog.at_level(logging.INFO):
        exit_code = trade_module.main()

    assert exit_code == 0
    assert len(captured) == 1
    assert captured[0]["live_trading_permit"] is None  # shadow mode, not fatal

    info_records = [
        r
        for r in caplog.records
        if r.name == trade_module._BOOT_LOGGER_NAME
        and r.getMessage().startswith("live-trading permit not issued")
    ]
    assert len(info_records) == 1

    warn_records = [
        r
        for r in caplog.records
        if r.name == "breezy.runtime.health" and r.levelno == logging.WARNING
    ]
    assert len(warn_records) == 1
    assert warn_records[0].getMessage() == (
        "breezy alert event=LIVE_TRADING_PERMIT_REFUSED site=global "
        "severity=WARN detail=permit_missing"
    )
    # A static enum member, never the caught exception's own text.
    assert "TRADING_ENABLED" not in warn_records[0].getMessage()


# ---------------------------------------------------------------------------
# 2026-09-05 investigation: the "silent path" -- a settings-load failure, or
# an orders-enabled-falsy skip, previously left NO trace in the log at all.
# These pin the fix: every branch now logs one unmistakable line, and a
# settings-load failure while BREEZY_ORDERS_ENABLED="1" was requested is now
# FATAL (EXIT_RUNTIME_ERROR) rather than silently running a node that can
# never submit.
# ---------------------------------------------------------------------------


def _raising_load_trade_settings() -> object:
    raise SettingsError("fake settings load failure")


def test_main_exits_runtime_error_when_settings_fail_and_orders_were_requested(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """BREEZY_ORDERS_ENABLED="1" but the loader itself blew up: the operator's
    request can never be honoured, so this must stop the process loudly
    instead of degrading to a node that can never submit."""
    monkeypatch.delenv(TRADING_ENABLED_ENV_VAR, raising=False)
    monkeypatch.setenv(ORDERS_ENABLED_VAR, "1")
    monkeypatch.setattr(trade_module, "load_trade_settings", _raising_load_trade_settings)

    captured: list[dict[str, object]] = []

    def _fake_run(**kwargs: object) -> int:
        captured.append(kwargs)
        return 0

    monkeypatch.setattr(trade_module, "run", _fake_run)

    with caplog.at_level(logging.INFO):
        exit_code = trade_module.main()

    assert exit_code == EXIT_RUNTIME_ERROR
    assert captured == []  # run() must never be reached on this fatal path

    error_records = [
        r
        for r in caplog.records
        if r.name == trade_module._BOOT_LOGGER_NAME and r.levelno == logging.ERROR
    ]
    assert len(error_records) == 1
    message = error_records[0].getMessage()
    # Substring pinned against `trade_supervisor_core.PERMIT_NOT_ISSUED_MARKER`
    # so the daily-relaunch supervisor classifies this exit-1 deterministically.
    assert "order submission permit not issued" in message
    assert "SettingsError" in message


def test_main_logs_and_continues_when_settings_fail_and_orders_were_not_requested(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A settings-load failure with no order-path request is non-fatal here
    (``run`` reports the real configuration error), but must never be
    silent -- and must never claim the "not issued" marker, which is
    reserved for a genuine refused REQUEST."""
    monkeypatch.delenv(TRADING_ENABLED_ENV_VAR, raising=False)
    monkeypatch.delenv(ORDERS_ENABLED_VAR, raising=False)
    monkeypatch.setattr(trade_module, "load_trade_settings", _raising_load_trade_settings)

    captured: list[dict[str, object]] = []

    def _fake_run(**kwargs: object) -> int:
        captured.append(kwargs)
        return 0

    monkeypatch.setattr(trade_module, "run", _fake_run)

    with caplog.at_level(logging.INFO):
        exit_code = trade_module.main()

    assert exit_code == 0
    assert len(captured) == 1
    assert captured[0]["order_submission_permit"] is None

    info_records = [
        r
        for r in caplog.records
        if r.name == trade_module._BOOT_LOGGER_NAME
        and r.getMessage().startswith("order submission permit not minted")
    ]
    assert len(info_records) == 1
    assert "SettingsError" in info_records[0].getMessage()
    assert "not issued" not in info_records[0].getMessage()


def test_main_logs_when_orders_enabled_requested_is_false(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The legitimate shadow-mode skip (settings loaded fine, orders simply
    were not requested) is not an error, but it must no longer be silent."""
    monkeypatch.delenv(TRADING_ENABLED_ENV_VAR, raising=False)
    monkeypatch.setattr(
        trade_module,
        "load_trade_settings",
        lambda: _FakeSettings(orders_enabled_requested=False),
    )
    monkeypatch.setattr(trade_module, "run", lambda **kwargs: 0)

    with caplog.at_level(logging.INFO):
        trade_module.main()

    skip_records = [
        r
        for r in caplog.records
        if r.name == trade_module._BOOT_LOGGER_NAME
        and r.getMessage() == "order submission permit not minted: orders not requested"
    ]
    assert len(skip_records) == 1


# ---------------------------------------------------------------------------
# 2026-09-05: the boot-time audit handler must never leak onto
# `trade_cli.logger` -- that logger is reused by `trade_cli.run()` for every
# runtime fault for the node's whole life, and once `trade_cli.run()`
# installs the Nautilus logging bridge on top of it, a leftover boot handler
# there prints every such fault twice (once raw, once via the bridge).
# ---------------------------------------------------------------------------


def test_main_leaves_no_handler_on_trade_cli_logger_and_never_double_logs(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """After `main()` reaches `run()`, `trade_cli.logger` must carry no
    handler of its own. The stubbed `run()` below simulates `trade_cli.run()`
    installing a handler on `trade_cli.logger` (the shape the real Nautilus
    logging bridge takes) and logging one runtime fault through it; that
    fault must appear at most once on stderr, never twice."""
    monkeypatch.delenv(TRADING_ENABLED_ENV_VAR, raising=False)
    monkeypatch.setattr(
        trade_module,
        "load_trade_settings",
        lambda: _FakeSettings(orders_enabled_requested=False),
    )

    def _fake_run(**kwargs: object) -> int:
        assert trade_cli.logger.handlers == []
        bridge_handler = logging.StreamHandler(sys.stderr)
        trade_cli.logger.addHandler(bridge_handler)
        try:
            trade_cli.logger.error("simulated runtime fault")
        finally:
            trade_cli.logger.removeHandler(bridge_handler)
        return 0

    monkeypatch.setattr(trade_module, "run", _fake_run)

    trade_module.main()

    captured = capsys.readouterr()
    assert captured.err.count("simulated runtime fault") == 1
