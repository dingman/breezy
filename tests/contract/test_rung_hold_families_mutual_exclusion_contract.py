"""Contract: exactly one rung-hold family may send orders (D5, Rev 2
dispositions -- ``docs/plans/DAILY_BUDGET_DAY_STOP_2026-09-14.md``).

The v3 (``continuous_rung_hold``) strategy is the only one that reads the
operator ruling 2026-09-14 day-budget marker
(``TrialDayLatch.is_day_budget_exhausted``); v2 (``current_rung_hold``,
``strategy.py``) does not. That omission is safe ONLY because
``settings.load_trade_settings`` refuses to boot BOTH families together
(Phase 1) unless the build-side ``BREEZY_CRH_CONT_PHASE0_SHADOW`` escape
hatch is set -- restoring the Phase 0 composition where only
``current_rung_hold`` may ever hold the order-submission permit
(``strategy.current_rung_hold.composition.phase0_family_permits``), so v3's
day-stop gap is unreachable from the live order path either way.

This file pins the XOR itself as a load-bearing invariant of the day-stop
design -- not merely of settings loading (already exercised in breadth by
``test_runtime_settings.py``). If this contract is ever relaxed (both
families sending orders simultaneously, with no shadow flag), the day-budget
day-stop silently stops covering the family that goes unread, and this test
must be revisited alongside it.
"""

from __future__ import annotations

import pytest

from breezy.runtime.settings import (
    CONTINUOUS_RUNG_HOLD_VAR,
    CRH_CONT_PHASE0_SHADOW_VAR,
    CURRENT_RUNG_HOLD_VAR,
    LIVE_OBSERVATIONS_VAR,
    TRADE_CATALOG_ROOT_VAR,
    TRADE_TRADER_ID_VAR,
    SettingsError,
    load_trade_settings,
)

_BASE_ENV = {
    TRADE_TRADER_ID_VAR: "BREEZY-TEST-001",
    LIVE_OBSERVATIONS_VAR: "1",
    TRADE_CATALOG_ROOT_VAR: "/tmp/breezy-trade-catalog",
}


def test_the_two_rung_hold_strategies_are_mutually_exclusive_at_boot() -> None:
    """Both flags set, no shadow escape hatch -- refused at settings load,
    never reaching either strategy's ``on_start``."""
    with pytest.raises(SettingsError) as excinfo:
        load_trade_settings(
            {
                **_BASE_ENV,
                CURRENT_RUNG_HOLD_VAR: "1",
                CONTINUOUS_RUNG_HOLD_VAR: "1",
            }
        )
    message = str(excinfo.value)
    assert CURRENT_RUNG_HOLD_VAR in message
    assert CONTINUOUS_RUNG_HOLD_VAR in message
    assert CRH_CONT_PHASE0_SHADOW_VAR in message


def test_current_rung_hold_alone_boots() -> None:
    settings = load_trade_settings({**_BASE_ENV, CURRENT_RUNG_HOLD_VAR: "1"})
    assert settings.current_rung_hold is True
    assert settings.continuous_rung_hold is False


def test_continuous_rung_hold_alone_boots() -> None:
    settings = load_trade_settings({**_BASE_ENV, CONTINUOUS_RUNG_HOLD_VAR: "1"})
    assert settings.current_rung_hold is False
    assert settings.continuous_rung_hold is True


def test_both_together_is_accepted_only_behind_the_phase0_shadow_escape_hatch() -> None:
    settings = load_trade_settings(
        {
            **_BASE_ENV,
            CURRENT_RUNG_HOLD_VAR: "1",
            CONTINUOUS_RUNG_HOLD_VAR: "1",
            CRH_CONT_PHASE0_SHADOW_VAR: "1",
        }
    )
    assert settings.current_rung_hold is True
    assert settings.continuous_rung_hold is True
    assert settings.phase0_shadow is True
