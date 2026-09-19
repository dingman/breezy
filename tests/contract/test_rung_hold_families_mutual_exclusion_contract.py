"""Contract: exactly one family may send orders (D5, Rev 2 dispositions --
``docs/plans/DAILY_BUDGET_DAY_STOP_2026-09-14.md``), WIDENED by WP-11b
(active-family registry, cardinality-1, 2026-09-19).

Before WP-11b, exclusivity was an N-BOOLEAN MUTEX that happened to be
checked (``current_rung_hold``/``continuous_rung_hold`` set together was
refused unless the Phase 0 shadow escape hatch was set). WP-11b makes
cardinality-1 STRUCTURAL instead: ``BreezyTradeSettings.sending_family_id``
is a single ``str | None`` slot, so "two sending families" is not merely
refused -- there is no representation in the type for it.

The v3 (``continuous_rung_hold``) strategy is the only one that reads the
operator ruling 2026-09-14 day-budget marker
(``TrialDayLatch.is_day_budget_exhausted``); v2 (``current_rung_hold``,
``strategy.py``) does not. That omission is safe ONLY because at most one
composition kind is ever dispatched per boot (``app/trade.py::run``,
routed by the sending family's own manifest ``composition_kind``), so v3's
day-stop gap is unreachable from a v2-sending boot either way.

This file pins the underlying exclusivity as a load-bearing invariant of
the day-stop design -- not merely of settings loading (already exercised in
breadth by ``test_runtime_settings.py``). If this contract is ever relaxed
(two families sending orders simultaneously), the day-budget day-stop
silently stops covering the family that goes unread, and this test must be
revisited alongside it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from breezy.persistence.family_manifest import load_family_manifest
from breezy.runtime.settings import (
    CRH_CONT_PHASE0_SHADOW_VAR,
    LIVE_OBSERVATIONS_VAR,
    SENDING_FAMILY_ID_VAR,
    TRADE_CATALOG_ROOT_VAR,
    TRADE_TRADER_ID_VAR,
    SettingsError,
    load_trade_settings,
)
from breezy.strategy.current_rung_hold.composition import phase1_sending_permit

_REPO_ROOT = Path(__file__).resolve().parents[2]
_FAMILIES_DIR = _REPO_ROOT / "deploy" / "families"

_BASE_ENV = {
    TRADE_TRADER_ID_VAR: "BREEZY-TEST-001",
    LIVE_OBSERVATIONS_VAR: "1",
    TRADE_CATALOG_ROOT_VAR: "/tmp/breezy-trade-catalog",
}


def test_two_ids_cannot_be_expressed_in_the_one_sending_family_slot() -> None:
    """(a) Two sending ids cannot be expressed -- type/settings level.
    A single string field cannot hold two ids; the loader refuses a value
    shaped like an attempt to smuggle two through it (comma/whitespace)."""
    with pytest.raises(SettingsError) as excinfo:
        load_trade_settings(
            {**_BASE_ENV, SENDING_FAMILY_ID_VAR: "pm_us_crh_cont,pm_us_crh_v2"}
        )
    assert SENDING_FAMILY_ID_VAR in str(excinfo.value)


def test_current_rung_hold_alone_boots() -> None:
    """(b) Each composition_kind alone boots -- current_rung_hold."""
    settings = load_trade_settings({**_BASE_ENV, SENDING_FAMILY_ID_VAR: "pm_us_crh_v2"})
    assert settings.sending_family_id == "pm_us_crh_v2"
    manifest = load_family_manifest(_FAMILIES_DIR / "pm_us_crh_v2.json")
    assert manifest.composition_kind == "current_rung_hold"


def test_continuous_rung_hold_alone_boots() -> None:
    """(b) Each composition_kind alone boots -- continuous_rung_hold."""
    settings = load_trade_settings({**_BASE_ENV, SENDING_FAMILY_ID_VAR: "pm_us_crh_cont"})
    assert settings.sending_family_id == "pm_us_crh_cont"
    manifest = load_family_manifest(_FAMILIES_DIR / "pm_us_crh_cont.json")
    assert manifest.composition_kind == "continuous_rung_hold"


def test_draft_manifest_cannot_send_without_allow_draft() -> None:
    """(c) DRAFT cannot send -- settings-load time refuses a
    DRAFT_NOT_REGISTERED sending family outright; production never passes
    allow_draft=True."""
    with pytest.raises(SettingsError) as excinfo:
        load_trade_settings({**_BASE_ENV, SENDING_FAMILY_ID_VAR: "kalshi_crh_v1"})
    assert "kalshi_crh_v1" in str(excinfo.value)


def test_unknown_sending_family_id_refused() -> None:
    with pytest.raises(SettingsError) as excinfo:
        load_trade_settings(
            {**_BASE_ENV, SENDING_FAMILY_ID_VAR: "pm_us_totally_unregistered_id"}
        )
    assert "pm_us_totally_unregistered_id" in str(excinfo.value)


def test_phase0_shadow_cannot_mint_two_sending_permits() -> None:
    """(d) phase0_shadow cannot mint two sending permits -- structurally:
    ``phase1_sending_permit`` returns a single ``OrderSubmissionPermit |
    None``, never a pair, whether or not the shadow hatch is set."""
    fake_permit = object()
    for phase0_shadow in (False, True):
        routed = phase1_sending_permit(
            sending_family_id="pm_us_crh_cont",
            permit=fake_permit,  # type: ignore[arg-type]
            phase0_shadow=phase0_shadow,
        )
        assert routed is None or routed is fake_permit
        # There is no second return value to hold a second permit -- the
        # assertion above, plus the function's own return-type annotation,
        # IS the cardinality-1 guarantee.


def test_no_two_manifests_can_be_active_in_one_boot() -> None:
    """(e) No two manifests can be active in one boot: settings carries
    exactly one ``sending_family_id``, so exactly one manifest is ever
    resolved from ``deploy/families/`` per process -- there is no second
    field, env var, or code path through which a second manifest could
    become active alongside it."""
    settings = load_trade_settings({**_BASE_ENV, SENDING_FAMILY_ID_VAR: "pm_us_crh_cont"})
    sending_family_fields = [
        f
        for f in settings.__dataclass_fields__
        if "family" in f or "manifest" in f
    ]
    assert sending_family_fields == ["sending_family_id"]


def test_both_together_is_still_impossible_even_behind_the_phase0_shadow_escape_hatch() -> (
    None
):
    """Unlike the retired two-boolean design, the shadow escape hatch does
    NOT restore a two-family mode: there is only one ``SENDING_FAMILY_ID_VAR``
    to set, so ``CRH_CONT_PHASE0_SHADOW_VAR=1`` changes only whether the ONE
    named family's permit is withheld, never which id(s) are named."""
    settings = load_trade_settings(
        {
            **_BASE_ENV,
            SENDING_FAMILY_ID_VAR: "pm_us_crh_cont",
            CRH_CONT_PHASE0_SHADOW_VAR: "1",
        }
    )
    assert settings.sending_family_id == "pm_us_crh_cont"
    assert settings.phase0_shadow is True
