"""SL-13 -- ``forecast_quantile_ladder`` composition_kind wiring: the
manifest exact-set widening (L-12), the supervisor marker-map widening, the
committed manifest's own loadable properties (FQ-S8: REGISTERED, carrying
the operator ruling), and the exec client's byte-identity pin.

Mirrors ``tests/unit/test_wp11b_active_family_registry.py``'s
``test_forecast_ladder_composition_kind_deliberately_refuses_to_boot`` for
the pre-existing ``forecast_ladder`` refusal, and
``tests/unit/test_family_manifest.py``'s ``family_manifest_module`` private-
constant-import style for the exact-set assertions.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import breezy.persistence.family_manifest as family_manifest_module
import breezy.runtime.trade_supervisor_core as trade_supervisor_core_module
from breezy.persistence.family_manifest import load_family_manifest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MANIFEST_PATH = _REPO_ROOT / "deploy" / "families" / "pm_us_crh_fq_v1.json"
#: FQ-S8: the operator ruling the committed, REGISTERED manifest declares.
_LIVE_ORDERS_RULING_ID = "RULING_operator_fq_live_real_orders_2026-10-01"

#: Pinned at SL-13 authorship time. `client.py` is a NO-SEND execution-egress
#: module (`adapters/polymarket_us/exec/client.py`) SL-13 must leave
#: byte-unchanged -- see the module's own deny chain at lines 5327-5510.
#: A failure here means that file changed; re-verify with a real reviewer
#: before ever updating this pin.
_EXEC_CLIENT_PATH = (
    _REPO_ROOT / "src" / "breezy" / "adapters" / "polymarket_us" / "exec" / "client.py"
)
# re-pinned 2026-10-02: AMBIG-LATCH-CLEAR (resolver zero-fill clears AMBIGUOUS refusal), reviewer-approved  # noqa: E501
_EXEC_CLIENT_SHA256 = "76784ce814797bfb5480487ff0dad47cbe9c0b1727aef9ad1c7461cc33aa68a4"


# ---------------------------------------------------------------------------
# CompositionKind / _COMPOSITION_KINDS -- widened by exactly one row (L-12)
# ---------------------------------------------------------------------------


def test_composition_kind_exact_set_is_widened_by_exactly_one_row() -> None:
    assert family_manifest_module._COMPOSITION_KINDS == frozenset(
        {"current_rung_hold", "continuous_rung_hold", "forecast_ladder", "forecast_quantile_ladder"},
    )


def test_forecast_quantile_ladder_is_accepted_as_a_composition_kind(tmp_path: Path) -> None:
    from tests.unit.test_family_manifest import _VALID, _write  # reuse the shared fixture builder

    path = _write(
        tmp_path,
        dict(_VALID, composition_kind="forecast_quantile_ladder", status="DRAFT_NOT_REGISTERED"),
    )
    manifest = load_family_manifest(path, allow_draft=True)

    assert manifest.composition_kind == "forecast_quantile_ladder"


# ---------------------------------------------------------------------------
# COMPOSITION_KIND_SUBSCRIBED_MARKERS -- widened by exactly one row
# ---------------------------------------------------------------------------


def test_marker_map_is_widened_by_exactly_one_row() -> None:
    markers = trade_supervisor_core_module.COMPOSITION_KIND_SUBSCRIBED_MARKERS
    assert markers == {
        "current_rung_hold": "CurrentRungHoldStrategy subscribed",
        "continuous_rung_hold": "ContinuousRungHoldStrategy subscribed",
        "forecast_ladder": "ForecastLadderStrategy subscribed",
        "forecast_quantile_ladder": "ForecastQuantileLadderStrategy subscribed",
    }


def test_strategy_subscribed_in_recognises_the_new_marker() -> None:
    assert trade_supervisor_core_module.strategy_subscribed_in(
        "some log line\nForecastQuantileLadderStrategy subscribed\nmore log",
    )


# ---------------------------------------------------------------------------
# The committed manifest itself (FQ-S8: deliberate fixture state change --
# DRAFT_NOT_REGISTERED -> REGISTERED, carrying the operator ruling). The
# generic DRAFT refusal this used to cover stays exercised above, against a
# synthetic fixture (`test_forecast_quantile_ladder_is_accepted_as_a_
# composition_kind`), independent of this one committed manifest's status.
# ---------------------------------------------------------------------------


def test_pm_us_crh_fq_v1_is_registered_with_the_operator_ruling() -> None:
    assert _MANIFEST_PATH.exists()

    manifest = load_family_manifest(_MANIFEST_PATH)

    assert manifest.status == "REGISTERED"
    assert manifest.live_orders_ruling == _LIVE_ORDERS_RULING_ID


def test_pm_us_crh_fq_v1_loads_and_names_the_right_composition_kind() -> None:
    manifest = load_family_manifest(_MANIFEST_PATH)

    assert manifest.composition_kind == "forecast_quantile_ladder"
    assert manifest.status == "REGISTERED"
    assert manifest.family_id == "pm_us_crh_fq_v1"


# ---------------------------------------------------------------------------
# Exec client byte-identity (task hard rule: the deny chain stays untouched)
# ---------------------------------------------------------------------------


def test_exec_client_is_byte_identical_to_its_pre_sl13_sha256() -> None:
    actual = hashlib.sha256(_EXEC_CLIENT_PATH.read_bytes()).hexdigest()

    assert actual == _EXEC_CLIENT_SHA256, (
        "adapters/polymarket_us/exec/client.py changed during SL-13 -- the "
        "deny chain (lines 5327-5510) must stay byte-unchanged; this file "
        "must never be edited by this slice"
    )
