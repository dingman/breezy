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
from dataclasses import dataclass

import pytest

from breezy.adapters.polymarket_us.operator_controls import (
    MAX_DAILY_BUDGET_USD_ENV_VAR,
    MAX_POSITION_COST_USD_ENV_VAR,
)
from breezy.adapters.polymarket_us.safety import PERMIT_TTL_NS, TRADING_ENABLED_ENV_VAR
from breezy.app import trade as trade_module
from breezy.runtime.order_enablement import OrderSubmissionPermit
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
        if r.name == "breezy.runtime.trade_cli"
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
