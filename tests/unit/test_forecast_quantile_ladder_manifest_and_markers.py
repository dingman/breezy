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

import pytest

import breezy.persistence.family_manifest as family_manifest_module
import breezy.runtime.trade_supervisor_core as trade_supervisor_core_module
from breezy.persistence.family_manifest import FamilyManifestValidationError, load_family_manifest

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
# re-pinned 2026-10-09: AMBIG-LATCH-RESUME Phase B (resume method, accept-fill/no-id clears, pre-POST context, no-id resolver; hunks H1-H12 per plan r6 section 4)  # noqa: E501
# re-pinned 2026-10-10: WP-DR day-roll settle (3 resolver sites skip prior-day true-up; fill-on-new-day latches UNBUDGETED), reviewer-approved (python-reviewer + prediction-market-reviewer)  # noqa: E501
# re-pinned 2026-10-10: EXEC-PAR WP4 parallel-slot wiring (r5 §5 WP4 + r5.1 E1-E14); python-reviewer + prediction-market-reviewer APPROVE, silent-failure-hunter READY 88  # noqa: E501
# S4 WP6 (ARM B7) re-pin once after WP3-WP5; prior a4cbd8cbbf29524a6de3c18dc4e2b565ce25e1f1b91ca54f0c2483f671b64410; reviewed in f507e5c0 (B1, B3-B6 client edits + review fixes; B7 itself edits no client byte)  # noqa: E501
# ARM post-B2 flip: re-pinned once; prior 7ff6a77534d934fabcbf48a6f36e455e32e2b0b3a26b221f53a5562a533ed05e. The only client byte change is the _sweep_resting_orders_at_boot docstring reconciled for SLUG_SCOPED_CANCEL_ALL_VERIFIED=True (S-2 PASS, docs/evidence/b2/maker_positive_control_20261022T075159Z.json); no code line changes  # noqa: E501
# ONE constant is the home of this pin for three tests: this file's byte-identity test,
# test_autonomy_envelope::test_exec_client_never_edited (reads it by AST) and the
# positive control of test_aut1_wp0_closure_premises::test_submit_chain_is_not_byte_pinned_in_tests.
# re-pinned 2026-10-28: LATCH-RECOVERY (terminal read clears resting_query_unreadable via _clear_resting_cancel_latch) + poll refusal WARN carries the mapper message (key names + own-order fields); prior f44830077501040a76a1823345e24aca2eefcc3f090d718c6d7db03ff03af17d; python-reviewer + prediction-market-reviewer APPROVE, silent-failure-hunter SAFE-WITH-FIXES applied.  # noqa: E501
# re-pinned 2026-10-29: EXEC-FOREIGN-POS Stage A (positions classified in _map_positions; reports slug match). prior 417b4613d5b7db40034922d0c8f1e97e2d1ce974be4fc26fe3313200caf01032; four reviews APPROVE, 13 LOW applied.  # noqa: E501
_EXEC_CLIENT_SHA256 = "9e5a6fb9c773f32d4ded67e89ae9a6df0aca1bcc5617da181099aa547672cd7e"
_EXEC_CLIENT_SHA256_BEFORE_POSTB2_REPIN = (
    "7ff6a77534d934fabcbf48a6f36e455e32e2b0b3a26b221f53a5562a533ed05e"
)
_EXEC_CLIENT_SHA256_BEFORE_B7_REPIN = (
    "a4cbd8cbbf29524a6de3c18dc4e2b565ce25e1f1b91ca54f0c2483f671b64410"
)


# ---------------------------------------------------------------------------
# CompositionKind / _COMPOSITION_KINDS -- widened by exactly one row (L-12)
# ---------------------------------------------------------------------------


def test_composition_kind_exact_set_is_widened_by_exactly_one_row() -> None:
    # ARM C2: widened by exactly ONE further named row, `no_ladder_maker`.
    pinned = frozenset(
        {
            "current_rung_hold",
            "continuous_rung_hold",
            "forecast_ladder",
            "forecast_quantile_ladder",
            "no_ladder_maker",
        },
    )
    assert family_manifest_module._COMPOSITION_KINDS == pinned


def test_the_no_ladder_maker_kind_is_load_bearing_for_the_shipped_maker_manifest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Plant: with the row removed the shipped maker manifest no longer loads."""
    path = _REPO_ROOT / "deploy" / "families" / "pm_us_no_maker_sharp_v1.json"
    assert load_family_manifest(path).composition_kind == "no_ladder_maker"
    monkeypatch.setattr(
        family_manifest_module,
        "_COMPOSITION_KINDS",
        family_manifest_module._COMPOSITION_KINDS - {"no_ladder_maker"},
    )
    with pytest.raises(FamilyManifestValidationError, match="no_ladder_maker"):
        load_family_manifest(path)


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
        # ARM C2: one further named row.
        "no_ladder_maker": "NoLadderMakerStrategy subscribed",
    }


def test_the_no_ladder_maker_marker_row_is_load_bearing_for_the_supervisor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Plant: with the row removed the supervisor no longer recognises the maker's boot line."""
    line = "NoLadderMakerStrategy subscribed n=6"
    assert trade_supervisor_core_module.strategy_subscribed_in(line)
    kept = tuple(
        marker
        for kind, marker in trade_supervisor_core_module.COMPOSITION_KIND_SUBSCRIBED_MARKERS.items()
        if kind != "no_ladder_maker"
    )
    monkeypatch.setattr(trade_supervisor_core_module, "STRATEGY_SUBSCRIBED_MARKERS", kept)
    assert not trade_supervisor_core_module.strategy_subscribed_in(line)


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


def test_b7_repin_is_sensitive_to_the_old_digest_and_to_a_single_flipped_byte() -> None:
    """Sensitivity plant for the one-time WP6 re-pin: the previous digest no longer matches the
    client, and flipping one byte of the real client fails the new pin."""
    original = _EXEC_CLIENT_PATH.read_bytes()
    assert hashlib.sha256(original).hexdigest() == _EXEC_CLIENT_SHA256
    assert _EXEC_CLIENT_SHA256 != _EXEC_CLIENT_SHA256_BEFORE_B7_REPIN
    assert _EXEC_CLIENT_SHA256 != _EXEC_CLIENT_SHA256_BEFORE_POSTB2_REPIN
    assert hashlib.sha256(original).hexdigest() != _EXEC_CLIENT_SHA256_BEFORE_POSTB2_REPIN
    assert hashlib.sha256(original).hexdigest() != _EXEC_CLIENT_SHA256_BEFORE_B7_REPIN
    flipped = bytes([original[0] ^ 0x01]) + original[1:]
    assert hashlib.sha256(flipped).hexdigest() != _EXEC_CLIENT_SHA256
    # B7 review T4: a flip in the middle and at the end of the file is caught as well.
    for index in (len(original) // 2, len(original) - 1):
        mutated = original[:index] + bytes([original[index] ^ 0x01]) + original[index + 1 :]
        assert hashlib.sha256(mutated).hexdigest() != _EXEC_CLIENT_SHA256, index
