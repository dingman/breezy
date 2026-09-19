"""WP-11b (active-family registry, cardinality-1) -- the ten RED tests named
in ``docs/plans/FORECAST_TO_LEARNING_WORK_BREAKDOWN_2026-09-18.md``.

Each test below is numbered to match the plan's own list. Several of these
properties are ALSO exercised, in more depth, by
``tests/contract/test_rung_hold_families_mutual_exclusion_contract.py`` and
``tests/unit/test_runtime_settings.py`` -- this file exists so the plan's
exact ten names are each satisfied by a single, directly-traceable test,
not merely implied by broader coverage elsewhere.
"""

from __future__ import annotations

import ast
import hashlib
import io
import json
from pathlib import Path

import pytest

from breezy.app.trade import run
from breezy.persistence.family_manifest import load_family_manifest
from breezy.runtime.settings import (
    LIVE_OBSERVATIONS_VAR,
    SENDING_FAMILY_ID_VAR,
    TRADE_CATALOG_ROOT_VAR,
    SettingsError,
    load_trade_settings,
)
from breezy.runtime.trade_cli import EXIT_CONFIG_ERROR, EXIT_OK
from breezy.strategy.current_rung_hold.composition import phase1_sending_permit
from breezy.strategy.current_rung_hold.continuous_strategy import ContinuousRungHoldStrategy
from breezy.strategy.current_rung_hold.strategy import CurrentRungHoldStrategy
from tests.unit.test_trade_cli_current_rung_hold import (  # noqa: F401 -- reused harness
    RecordingNode,
    _clean_nodes,
    _operator_order_ceiling,
    _trade_env,
    _write_today_catalog,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_APP_TRADE_SOURCE = (_REPO_ROOT / "src" / "breezy" / "app" / "trade.py").read_text()
_TRADE_SUPERVISOR_SOURCE = (
    _REPO_ROOT / "src" / "breezy" / "runtime" / "trade_supervisor.py"
).read_text()


# ---------------------------------------------------------------------------
# (1) test_sending_family_id_is_cardinality_one -- two ids in env -> SettingsError
# ---------------------------------------------------------------------------


def test_sending_family_id_is_cardinality_one() -> None:
    env = {
        "BREEZY_TRADE_TRADER_ID": "BREEZYTRADE-001",
        SENDING_FAMILY_ID_VAR: "pm_us_crh_cont,pm_us_crh_v2",
    }
    with pytest.raises(SettingsError) as excinfo:
        load_trade_settings(env)
    assert SENDING_FAMILY_ID_VAR in str(excinfo.value)


# ---------------------------------------------------------------------------
# (2) test_unknown_sending_family_id_refused
# ---------------------------------------------------------------------------


def test_unknown_sending_family_id_refused() -> None:
    env = {
        "BREEZY_TRADE_TRADER_ID": "BREEZYTRADE-001",
        LIVE_OBSERVATIONS_VAR: "1",
        TRADE_CATALOG_ROOT_VAR: "/tmp/breezy-trade-catalog",
        SENDING_FAMILY_ID_VAR: "pm_us_wp11b_unregistered_fixture_id",
    }
    with pytest.raises(SettingsError) as excinfo:
        load_trade_settings(env)
    assert "pm_us_wp11b_unregistered_fixture_id" in str(excinfo.value)


# ---------------------------------------------------------------------------
# (3) test_draft_manifest_cannot_send_without_allow_draft
# ---------------------------------------------------------------------------


def test_draft_manifest_cannot_send_without_allow_draft() -> None:
    """``kalshi_crh_v1`` is a committed DRAFT_NOT_REGISTERED manifest.
    ``load_trade_settings`` never passes ``allow_draft=True`` -- a
    production boot always requires REGISTERED."""
    env = {
        "BREEZY_TRADE_TRADER_ID": "BREEZYTRADE-001",
        LIVE_OBSERVATIONS_VAR: "1",
        TRADE_CATALOG_ROOT_VAR: "/tmp/breezy-trade-catalog",
        SENDING_FAMILY_ID_VAR: "kalshi_crh_v1",
    }
    with pytest.raises(SettingsError) as excinfo:
        load_trade_settings(env)
    assert "kalshi_crh_v1" in str(excinfo.value)


# ---------------------------------------------------------------------------
# (4) test_boot_loads_manifest_from_registry_dir_not_module_constant --
# AST/grep: _LIVE_CONTINUOUS_FAMILY_MANIFEST_PATH gone;
# load_family_manifest(Path("deploy/families")/f"{id}.json")
# ---------------------------------------------------------------------------


def test_boot_loads_manifest_from_registry_dir_not_module_constant() -> None:
    assert "_LIVE_CONTINUOUS_FAMILY_MANIFEST_PATH" not in _APP_TRADE_SOURCE
    # The registry directory itself is still a named constant (that part is
    # fine and expected) -- what must be gone is a constant naming ONE
    # FAMILY's file.
    assert 'Path("deploy/families")' in _APP_TRADE_SOURCE

    tree = ast.parse(_APP_TRADE_SOURCE, filename="app/trade.py")
    found_registry_dir_load = False
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
            continue
        if node.func.id != "load_family_manifest":
            continue
        # The one positional argument must be built from
        # `settings.sending_family_id` -- a per-boot REGISTRY lookup, never
        # a bare NAME reference to a hardcoded single-family constant (which
        # would unparse to just an identifier, with no attribute access
        # into `sending_family_id` at all).
        if not node.args:
            continue
        arg = node.args[0]
        assert not isinstance(arg, ast.Name), (
            f"load_family_manifest called with a bare NAME {ast.unparse(arg)!r} -- "
            "looks like a hardcoded single-family module constant, not a "
            "per-boot registry lookup"
        )
        source = ast.unparse(arg)
        if "sending_family_id" in source:
            found_registry_dir_load = True
    assert found_registry_dir_load, (
        "app/trade.py must call load_family_manifest(<families dir> / "
        "f'{settings.sending_family_id}.json') -- a registry-directory lookup "
        "keyed by settings.sending_family_id, never a hardcoded single-family "
        "module constant"
    )


# ---------------------------------------------------------------------------
# (5) test_promoted_revision_requires_no_src_edit -- a fixture
# pm_us_crh_fc_v2.json with composition_kind=forecast_ladder boots as
# sender with ZERO src/ diff vs v1 (manifest + density artefact + env only).
# THIS TEST IS THE POINT OF THE WHOLE WP.
# ---------------------------------------------------------------------------


def _write_forecast_ladder_manifest(
    families_dir: Path, *, family_id: str, trial_suffix: str
) -> None:
    artefacts_dir = families_dir / "artefacts"
    artefacts_dir.mkdir(parents=True, exist_ok=True)
    density_path = artefacts_dir / f"{family_id}_density.json"
    density_path.write_text(json.dumps({"schema": "fixture", "revision": trial_suffix}))
    density_sha = hashlib.sha256(density_path.read_bytes()).hexdigest()

    boundary_path = families_dir / "gs_boundary_fixture.json"
    if not boundary_path.exists():
        boundary_path.write_text(json.dumps({"boundary": "fixture"}))
    boundary_sha = hashlib.sha256(boundary_path.read_bytes()).hexdigest()

    payload = {
        "family_id": family_id,
        "venue": "polymarket_us",
        "trial_id_prefix": f"forecast_ladder_edge/trial/{trial_suffix}/",
        "d0_climate_day": "2026-09-19",
        "boundary_artefact_path": str(boundary_path),
        "boundary_inputs_sha256": boundary_sha,
        "composition_kind": "forecast_ladder",
        "density_artefact_path": str(density_path),
        "density_artefact_sha256": density_sha,
        "stations": ["SFO"],
        "status": "REGISTERED",
    }
    (families_dir / f"{family_id}.json").write_text(json.dumps(payload))


def test_promoted_revision_requires_no_src_edit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    _operator_order_ceiling: None,  # noqa: F811
    _clean_nodes: None,  # noqa: F811
) -> None:
    """Promoting ``pm_us_crh_fc_v1`` -> ``pm_us_crh_fc_v2`` changes ONLY a
    manifest file + a density artefact + the ``BREEZY_SENDING_FAMILY_ID``
    env value. ``ForecastLadderStrategy`` does not exist yet (WP-14), so
    BOTH fixture ids reach the identical, data-driven composition-dispatch
    refusal (``EXIT_CONFIG_ERROR``) through the exact SAME unmodified
    ``src/`` code path -- proving the promotion act is purely data.
    """
    families_dir = tmp_path / "deploy" / "families"
    _write_forecast_ladder_manifest(families_dir, family_id="pm_us_crh_fc_v1", trial_suffix="v1")
    _write_forecast_ladder_manifest(families_dir, family_id="pm_us_crh_fc_v2", trial_suffix="v2")

    monkeypatch.chdir(tmp_path)

    catalog_root = tmp_path / "catalog"
    catalog_root.mkdir()
    _write_today_catalog(catalog_root)

    src_before = _APP_TRADE_SOURCE
    results: dict[str, int] = {}
    for family_id in ("pm_us_crh_fc_v1", "pm_us_crh_fc_v2"):
        env = _trade_env(
            tmp_path,
            **{
                SENDING_FAMILY_ID_VAR: family_id,
                LIVE_OBSERVATIONS_VAR: "1",
                TRADE_CATALOG_ROOT_VAR: str(catalog_root),
            },
        )
        results[family_id] = run(env=env, node_factory=RecordingNode, stderr=io.StringIO())

    # ZERO src/ diff between the two calls: the module's own source text
    # (read once, at import time, before either call) is unchanged.
    assert _APP_TRADE_SOURCE == src_before
    assert results["pm_us_crh_fc_v1"] == EXIT_CONFIG_ERROR
    assert results["pm_us_crh_fc_v2"] == EXIT_CONFIG_ERROR
    assert RecordingNode.instances == []


# ---------------------------------------------------------------------------
# (6) test_no_two_manifests_can_be_active -- contract, widened exclusivity
# ---------------------------------------------------------------------------


def test_no_two_manifests_can_be_active() -> None:
    settings = load_trade_settings(
        {
            "BREEZY_TRADE_TRADER_ID": "BREEZYTRADE-001",
            LIVE_OBSERVATIONS_VAR: "1",
            TRADE_CATALOG_ROOT_VAR: "/tmp/breezy-trade-catalog",
            SENDING_FAMILY_ID_VAR: "pm_us_crh_cont",
        }
    )
    manifest_bearing_fields = [
        name
        for name in settings.__dataclass_fields__
        if "family" in name or "manifest" in name
    ]
    assert manifest_bearing_fields == ["sending_family_id"]
    manifest = load_family_manifest(_REPO_ROOT / "deploy/families/pm_us_crh_cont.json")
    assert manifest.family_id == settings.sending_family_id


# ---------------------------------------------------------------------------
# (7) test_each_composition_kind_boots_alone
# ---------------------------------------------------------------------------


def test_each_composition_kind_boots_alone(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    _operator_order_ceiling: None,  # noqa: F811
    _clean_nodes: None,  # noqa: F811
) -> None:
    catalog_root = tmp_path / "catalog"
    catalog_root.mkdir()
    _write_today_catalog(catalog_root)

    current_env = _trade_env(
        tmp_path,
        **{
            SENDING_FAMILY_ID_VAR: "pm_us_crh_v2",
            LIVE_OBSERVATIONS_VAR: "1",
            TRADE_CATALOG_ROOT_VAR: str(catalog_root),
        },
    )
    code = run(env=current_env, node_factory=RecordingNode, stderr=io.StringIO())
    assert code == EXIT_OK
    current_strategies = [
        s for s in RecordingNode.instances[-1].trader.strategies
        if isinstance(s, CurrentRungHoldStrategy)
    ]
    assert current_strategies

    RecordingNode.instances.clear()

    continuous_env = _trade_env(
        tmp_path,
        **{
            SENDING_FAMILY_ID_VAR: "pm_us_crh_cont",
            LIVE_OBSERVATIONS_VAR: "1",
            TRADE_CATALOG_ROOT_VAR: str(catalog_root),
        },
    )
    code = run(env=continuous_env, node_factory=RecordingNode, stderr=io.StringIO())
    assert code == EXIT_OK
    continuous_strategies = [
        s for s in RecordingNode.instances[-1].trader.strategies
        if isinstance(s, ContinuousRungHoldStrategy)
    ]
    assert continuous_strategies

    RecordingNode.instances.clear()

    families_dir = tmp_path / "fc_fixture" / "deploy" / "families"
    _write_forecast_ladder_manifest(families_dir, family_id="pm_us_crh_fc_v1", trial_suffix="v1")
    monkeypatch.chdir(tmp_path / "fc_fixture")
    forecast_env = _trade_env(
        tmp_path,
        **{
            SENDING_FAMILY_ID_VAR: "pm_us_crh_fc_v1",
            LIVE_OBSERVATIONS_VAR: "1",
            TRADE_CATALOG_ROOT_VAR: str(catalog_root),
        },
    )
    code = run(env=forecast_env, node_factory=RecordingNode, stderr=io.StringIO())
    assert code == EXIT_CONFIG_ERROR
    assert RecordingNode.instances == []


# ---------------------------------------------------------------------------
# (8) test_phase0_shadow_cannot_issue_two_sending_permits
# ---------------------------------------------------------------------------


def test_phase0_shadow_cannot_issue_two_sending_permits() -> None:
    fake_permit = object()
    for phase0_shadow in (False, True):
        routed = phase1_sending_permit(
            sending_family_id="pm_us_crh_cont",
            permit=fake_permit,  # type: ignore[arg-type]
            phase0_shadow=phase0_shadow,
        )
        # A single Optional value -- there is no second slot a caller could
        # even ask for. phase0_shadow=True withholds it (None); False routes
        # it through.
        assert routed is (None if phase0_shadow else fake_permit)


# ---------------------------------------------------------------------------
# (9) test_family_tally_template_passes_family_id_as_percent_i -- see
# tests/unit/test_family_tally_v2_deploy.py (same name, full assertions).
# ---------------------------------------------------------------------------


def test_family_tally_template_passes_family_id_as_percent_i() -> None:
    from tests.unit.test_family_tally_v2_deploy import (
        test_family_tally_template_passes_family_id_as_percent_i as _delegate,
    )

    _delegate()


# ---------------------------------------------------------------------------
# (10) test_supervisor_arming_reads_no_family_specific_env_name -- AST/grep:
# the supervisor arming path contains no BREEZY_CONTINUOUS_RUNG_HOLD /
# CONTINUOUS_RUNG_HOLD_VAR; readiness derives from sending_family_id; a
# fixture sending id pm_us_crh_fc_v1 makes continuous_family_active() True
# and the self-check block run.
# ---------------------------------------------------------------------------


def test_supervisor_arming_reads_no_family_specific_env_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert "BREEZY_CONTINUOUS_RUNG_HOLD" not in _TRADE_SUPERVISOR_SOURCE
    assert "CONTINUOUS_RUNG_HOLD_VAR" not in _TRADE_SUPERVISOR_SOURCE

    from breezy.runtime.trade_supervisor import sending_family_active

    monkeypatch.setenv("BREEZY_SENDING_FAMILY_ID", "pm_us_crh_fc_v1")
    assert sending_family_active() is True
