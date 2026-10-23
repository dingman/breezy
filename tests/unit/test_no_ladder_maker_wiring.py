"""ARM C2: the ``no_ladder_maker`` composition kind and the family ``pm_us_no_maker_sharp_v1``.

Every exact-set pin the new kind touches is widened by ONE named row (L-12); each widened site has
a plant here proving the pin is non-vacuous (the old set no longer equals the live one). Live
sending is ON for this family: the manifest names its ruling, exactly one allowlist row pins that
ruling's sha, and the family is still absent from ``DROPIN_ALLOWLIST``. ``exit_rule`` stays absent.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Final, get_args

import pytest

from breezy.analysis.autonomy import offline_plugins
from breezy.persistence import family_manifest as fm
from breezy.persistence import live_orders_gate
from breezy.persistence.autonomy.paths import MODEL_CLASS_RE
from breezy.persistence.autonomy.plugin import RefusingPlugin
from breezy.persistence.family_manifest import load_family_manifest
from breezy.runtime import health_dropins
from breezy.runtime.trade_supervisor_core import (
    COMPOSITION_KIND_SUBSCRIBED_MARKERS,
    strategy_subscribed_in,
)
from breezy.strategy.autonomy import node_plugins
from breezy.strategy.current_rung_hold import family_id_arg

REPO: Final[Path] = Path(__file__).resolve().parents[2]
MANIFEST: Final[Path] = REPO / "deploy" / "families" / "pm_us_no_maker_sharp_v1.json"
FQ_MANIFEST: Final[Path] = REPO / "deploy" / "families" / "pm_us_crh_fq_v1.json"
KIND: Final[str] = "no_ladder_maker"
FAMILY: Final[str] = "pm_us_no_maker_sharp_v1"
RULING_ID: Final[str] = "RULING_MAKER_sharp_v1_live_small_2026-10-21"
RULING_SHA256: Final[str] = "3dd44653bd9d6814ca2b0ea87e9d8bc1f028fa6f612e655216a486c113825152"
OLD_KINDS: Final[frozenset[str]] = frozenset(
    {"current_rung_hold", "continuous_rung_hold", "forecast_ladder", "forecast_quantile_ladder"}
)


# --- the manifest ----------------------------------------------------------------------------


def test_the_manifest_loads_registered_with_the_arm_shape() -> None:
    manifest = load_family_manifest(MANIFEST)  # REGISTERED: loads without allow_draft
    assert manifest.family_id == FAMILY
    assert manifest.venue == "polymarket_us"
    assert manifest.status == "REGISTERED"
    assert manifest.composition_kind == KIND
    assert manifest.stations == ("LAX", "MDW", "MIA", "SFO")
    assert str(manifest.taker_fee_coefficient) == "0.0695"
    assert manifest.exit_rule is None and manifest.no_leg_exit is False
    assert manifest.terminal_climate_day is None
    assert manifest.boundary_artefact_path.name == "not_applicable_boundary.json"


def test_the_calibration_is_the_design_run_artefact_pinned_by_path_and_sha() -> None:
    manifest = load_family_manifest(MANIFEST)
    fq = load_family_manifest(FQ_MANIFEST)
    assert manifest.density_artefact_path.name == "nbp_calibration_pm_us_crh_fq_v1_2026-09-30.json"
    assert manifest.density_artefact_sha256 == fq.density_artefact_sha256
    on_disk = (
        REPO / "deploy/families/artefacts" / manifest.density_artefact_path.name
    ).read_bytes()
    assert hashlib.sha256(on_disk).hexdigest() == manifest.density_artefact_sha256


def test_live_sending_is_on_for_the_sharp_ruling() -> None:
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert payload["live_orders_ruling"] == RULING_ID
    assert "exit_rule" not in payload
    manifest = load_family_manifest(MANIFEST)
    assert manifest.live_orders_ruling == RULING_ID
    decision = live_orders_gate.live_orders_authorized(manifest, REPO, permit_present=True)
    assert (decision.enabled, decision.reason) == (True, "ok")
    assert decision.ruling_sha256 == RULING_SHA256
    rows = [row for row in live_orders_gate._LIVE_ORDERS_ALLOWLIST if row[0] == FAMILY]
    assert rows == [(FAMILY, RULING_ID, RULING_SHA256)]
    assert FAMILY not in repr(health_dropins.DROPIN_ALLOWLIST)


# --- CompositionKind (family_manifest.py) -----------------------------------------------------


def test_composition_kinds_are_widened_by_exactly_the_one_new_row() -> None:
    assert fm._COMPOSITION_KINDS == OLD_KINDS | {KIND}
    assert fm._COMPOSITION_KINDS != OLD_KINDS  # plant: the old four-row pin no longer holds
    assert set(get_args(fm.CompositionKind)) == fm._COMPOSITION_KINDS  # type and runtime set agree


def test_an_unknown_composition_kind_is_still_refused(tmp_path: Path) -> None:
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    payload["composition_kind"] = "no_ladder_maker_v2"
    path = tmp_path / "deploy" / "families" / "x.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(fm.FamilyManifestValidationError, match="composition_kind"):
        load_family_manifest(path)


# --- family halt (family_id_arg.py) -----------------------------------------------------------


def test_the_kind_is_haltable_but_has_no_exit_path() -> None:
    assert family_id_arg.HALTABLE_COMPOSITION_KINDS == {
        "continuous_rung_hold",
        "forecast_quantile_ladder",
        KIND,
    }
    assert family_id_arg.HALTABLE_COMPOSITION_KINDS != {
        "continuous_rung_hold",
        "forecast_quantile_ladder",
    }  # plant
    assert KIND not in family_id_arg.KINDS_WITH_EXIT_PATH  # buys only; nothing to strand


def test_the_halt_cli_resolves_the_maker_manifest() -> None:
    manifest = family_id_arg.resolve_haltable_family_arg(FAMILY, REPO / "deploy" / "families")
    assert manifest.composition_kind == KIND


# --- autonomy registries ---------------------------------------------------------------------


def test_the_autonomy_model_class_pattern_admits_the_kind() -> None:
    assert MODEL_CLASS_RE.fullmatch(f"{KIND}:density_table") is not None
    assert MODEL_CLASS_RE.fullmatch("no_ladder_makerx:density_table") is None  # plant


def test_both_c6_registries_carry_the_kind_as_a_plain_refusing_plugin() -> None:
    for registry in (node_plugins.NODE_PLUGINS, offline_plugins.OFFLINE_PLUGINS):
        assert set(registry) == OLD_KINDS | {KIND}
        assert type(registry[KIND]) is RefusingPlugin
        assert set(registry) != OLD_KINDS  # plant


# --- the supervisor's subscribe marker --------------------------------------------------------


def test_the_subscribe_marker_row_names_the_strategy_class() -> None:
    from breezy.strategy.no_ladder_maker.strategy import NoLadderMakerStrategy

    marker = COMPOSITION_KIND_SUBSCRIBED_MARKERS[KIND]
    assert marker == f"{NoLadderMakerStrategy.__name__} subscribed"
    assert strategy_subscribed_in(f"... {marker} n=24 ...")
    assert KIND not in {k for k in COMPOSITION_KIND_SUBSCRIBED_MARKERS if k in OLD_KINDS - {KIND}}
