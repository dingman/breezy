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
import subprocess
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
# (5) test_promoted_revision_requires_no_src_edit -- promoting a REAL,
# booting family (continuous_rung_hold) to a successor changes ONLY a
# manifest file + a density artefact + the ``BREEZY_SENDING_FAMILY_ID`` env
# value, and each boot's composition is built from ITS OWN manifest data
# (never a value captured once and reused). THIS TEST IS THE POINT OF THE
# WHOLE WP.
#
# Superseded design note: an earlier version of this test used two
# ``forecast_ladder`` fixtures and asserted (a) ``_APP_TRADE_SOURCE ==
# src_before`` -- comparing the same in-memory string to itself, since
# nothing in the test process ever writes to ``src/`` under ANY
# implementation, including a hardcoded one -- and (b)
# ``EXIT_CONFIG_ERROR`` for both. ``forecast_ladder`` boots never reach
# composition at all (``app/trade.py`` refuses it unconditionally --
# ``ForecastLadderStrategy`` does not exist yet, WP-14), so that test
# proved only that two manifest files hit the SAME hard-coded refusal
# branch. It would have passed identically had ``run()`` ignored the
# manifest's ``family_id``, ``stations`` and ``trial_id_prefix`` entirely.
# The replacement below boots for real and reads a value straight off the
# constructed runtime object.
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


def _write_continuous_promotion_manifest(
    families_dir: Path,
    *,
    family_id: str,
    trial_suffix: str,
    stations: tuple[str, ...],
) -> None:
    """A REGISTERED ``continuous_rung_hold`` fixture manifest -- unlike
    ``_write_forecast_ladder_manifest``'s, this composition_kind actually
    boots, so it can prove data-driven promotion rather than a shared
    refusal path."""
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
        "trial_id_prefix": f"continuous_rung_hold/trial/{trial_suffix}/",
        "d0_climate_day": "2026-09-19",
        "boundary_artefact_path": str(boundary_path),
        "boundary_inputs_sha256": boundary_sha,
        "composition_kind": "continuous_rung_hold",
        "density_artefact_path": str(density_path),
        "density_artefact_sha256": density_sha,
        "stations": list(stations),
        "status": "REGISTERED",
    }
    (families_dir / f"{family_id}.json").write_text(json.dumps(payload))


def _hash_tracked_src_files() -> str:
    """Sha256 over every git-tracked file under ``src/`` -- path AND
    content -- so an added, removed, OR modified file all flip the digest.
    Reads bytes straight off disk (never ``git show``), so even an
    unstaged write shows up. Uses the repo's own git index (``git
    ls-files``) for the file list, never a glob, so a rename is caught
    too. This is the thing an implementation that actually edited
    ``src/`` during a "promotion" would break; a hardcoded-family
    implementation and a genuinely data-driven one both leave it alone,
    which is exactly the property this test needs and the retired
    ``_APP_TRADE_SOURCE == src_before`` self-comparison could never
    check.
    """
    listing = subprocess.run(
        ["git", "ls-files", "src"],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    digest = hashlib.sha256()
    for rel_path in sorted(listing.stdout.splitlines()):
        digest.update(rel_path.encode("utf-8"))
        digest.update((_REPO_ROOT / rel_path).read_bytes())
    return digest.hexdigest()


def test_promoted_revision_requires_no_src_edit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    _operator_order_ceiling: None,  # noqa: F811
    _clean_nodes: None,  # noqa: F811
) -> None:
    """Promoting ``pm_us_crh_promo_a`` -> ``pm_us_crh_promo_b`` (both
    ``continuous_rung_hold``, both REGISTERED, differing only in their own
    manifest data) changes ONLY a manifest file + a density artefact + the
    ``BREEZY_SENDING_FAMILY_ID`` env value -- and BOTH boot for real.

    Today, of a manifest's data-bearing fields, only ``family_id`` reaches
    a live runtime object: it flows through ``exit_manifest.family_id`` in
    ``app/trade.py::run`` into every constructed strategy's
    ``PositionMonitor.exit_family_id``
    (``composition.py::_build_position_monitor_for``). ``stations`` and
    ``trial_id_prefix`` are declared and validated on the manifest but not
    yet consumed by composition -- station iteration comes from the
    module-level ``SUPPORTED_STATIONS`` constant, not ``manifest.stations``
    -- so this test asserts exactly the one property that is actually true
    on disk today: each boot's monitor carries ITS OWN manifest's
    ``family_id``, never a value captured once (e.g. at import time or on
    the first boot) and silently reused on the second.
    """
    families_dir = tmp_path / "deploy" / "families"
    _write_continuous_promotion_manifest(
        families_dir, family_id="pm_us_crh_promo_a", trial_suffix="a", stations=("SFO",)
    )
    _write_continuous_promotion_manifest(
        families_dir, family_id="pm_us_crh_promo_b", trial_suffix="b", stations=("LAX",)
    )

    monkeypatch.chdir(tmp_path)

    catalog_root = tmp_path / "catalog"
    catalog_root.mkdir()
    _write_today_catalog(catalog_root)

    src_hash_before = _hash_tracked_src_files()
    exit_family_ids: dict[str, set[str | None]] = {}
    for family_id in ("pm_us_crh_promo_a", "pm_us_crh_promo_b"):
        env = _trade_env(
            tmp_path,
            **{
                SENDING_FAMILY_ID_VAR: family_id,
                LIVE_OBSERVATIONS_VAR: "1",
                TRADE_CATALOG_ROOT_VAR: str(catalog_root),
            },
        )
        code = run(env=env, node_factory=RecordingNode, stderr=io.StringIO())
        assert code == EXIT_OK, f"{family_id} failed to boot"
        node = RecordingNode.instances[-1]
        strategies = [
            s for s in node.trader.strategies if isinstance(s, ContinuousRungHoldStrategy)
        ]
        assert strategies, f"{family_id}: no ContinuousRungHoldStrategy was registered"
        exit_family_ids[family_id] = {
            strategy._position_monitor._exit_family_id for strategy in strategies
        }
        RecordingNode.instances.clear()

    # ZERO src/ diff across the promotion -- a REAL check, capable of
    # failing: hashed before the first boot, again after the second.
    assert _hash_tracked_src_files() == src_hash_before

    # Each boot's composition reflects ITS OWN manifest, not a value
    # captured once and reused across both: the two boots disagree with
    # each other, and each agrees only with its own sending_family_id.
    assert exit_family_ids["pm_us_crh_promo_a"] == {"pm_us_crh_promo_a"}
    assert exit_family_ids["pm_us_crh_promo_b"] == {"pm_us_crh_promo_b"}
    assert exit_family_ids["pm_us_crh_promo_a"] != exit_family_ids["pm_us_crh_promo_b"]


def test_forecast_ladder_composition_kind_deliberately_refuses_to_boot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    _operator_order_ceiling: None,  # noqa: F811
    _clean_nodes: None,  # noqa: F811
) -> None:
    """Kept as its OWN test, separate from the promotion proof above:
    ``composition_kind=forecast_ladder`` is a deliberate, data-driven
    refusal (``ForecastLadderStrategy`` does not exist yet -- WP-14), never
    a silent zero-strategy boot."""
    families_dir = tmp_path / "deploy" / "families"
    _write_forecast_ladder_manifest(families_dir, family_id="pm_us_crh_fc_v1", trial_suffix="v1")

    monkeypatch.chdir(tmp_path)

    catalog_root = tmp_path / "catalog"
    catalog_root.mkdir()
    _write_today_catalog(catalog_root)

    env = _trade_env(
        tmp_path,
        **{
            SENDING_FAMILY_ID_VAR: "pm_us_crh_fc_v1",
            LIVE_OBSERVATIONS_VAR: "1",
            TRADE_CATALOG_ROOT_VAR: str(catalog_root),
        },
    )
    code = run(env=env, node_factory=RecordingNode, stderr=io.StringIO())

    assert code == EXIT_CONFIG_ERROR
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
