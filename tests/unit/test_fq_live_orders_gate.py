"""FQ-S5 RED suite -- the live-orders enable path (plan
`FQ_GO_LIVE_PLAN_2026-10-01.md` D3, S5): the manifest's `live_orders_ruling`
declaration, `persistence.live_orders_gate.live_orders_authorized`'s
code-committed allowlist + ruling-sha pin + path containment, the artefact
path containment on `boundary_artefact_path`/`density_artefact_path`, and
`build_forecast_quantile_ladder_strategies`'s `shadow_only` propagation.

Items 3-6 assert `LiveOrdersGateRefusedError` -- the typed, fail-closed
refusal `app/trade.py`'s fq branch converts 1:1 into `SettingsError`, which
`main()`'s existing `except SettingsError` handler already maps to
`EXIT_CONFIG_ERROR` for every other artefact-load failure in this family
(see `app/trade.py`'s fq branch, item F1-F4 fail-closed tuple). Re-driving
the full `TradingNode` boot here would duplicate that existing, already-
tested mapping rather than add coverage; this suite tests the gate
function directly, at its own unit boundary.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import pytest

from breezy.persistence.family_manifest import (
    FamilyManifestValidationError,
    load_family_manifest,
)
from breezy.persistence.live_orders_gate import (
    LiveOrdersGateRefusedError,
    live_orders_authorized,
)
from breezy.strategy.forecast_quantile_ladder.composition import (
    build_forecast_quantile_ladder_strategies,
)
from breezy.strategy.forecast_quantile_ladder.latch import QuantileLadderLatch
from tests.unit.test_family_manifest import _VALID, _write

_REPO_ROOT = Path(__file__).resolve().parents[2]
_RULING_ID = "RULING_operator_fq_live_real_orders_2026-10-01"
_RULING_SHA256 = "11c69d132a70d8e328d3720314336aa6f2cf176d52fd25d5f2e20a7189711c1f"
_FAMILY_ID = "pm_us_crh_fq_v1"
_DEPLOY_RULING_PATH = _REPO_ROOT / "deploy" / "families" / "rulings" / f"{_RULING_ID}.md"

_FQ_VALID: dict[str, Any] = dict(
    _VALID,
    family_id=_FAMILY_ID,
    composition_kind="forecast_quantile_ladder",
)


def _manifest(tmp_path: Path, **overrides: Any) -> Any:
    payload = dict(_FQ_VALID, **overrides)
    return load_family_manifest(_write(tmp_path, payload), allow_draft=payload.get("status") != "REGISTERED")


def _seed_real_ruling(repo_root: Path, *, corrupt: bool = False) -> Path:
    """Copy the real committed ruling file under
    `repo_root/deploy/families/rulings/` (the gate's live-copy location --
    see `live_orders_gate`'s "Deviation from plan" docstring note),
    optionally with one appended byte (RED test 5: a single-byte tamper)."""
    rulings_dir = repo_root / "deploy" / "families" / "rulings"
    rulings_dir.mkdir(parents=True, exist_ok=True)
    raw = _DEPLOY_RULING_PATH.read_bytes()
    if corrupt:
        raw = raw + b"\n"
    path = rulings_dir / f"{_RULING_ID}.md"
    path.write_bytes(raw)
    return path


# ---------------------------------------------------------------------------
# Test 1 -- live_orders_ruling on a draft manifest is refused
# ---------------------------------------------------------------------------


def test_live_orders_ruling_on_a_draft_manifest_is_refused(tmp_path: Path) -> None:
    payload = dict(_FQ_VALID, status="DRAFT_NOT_REGISTERED", live_orders_ruling=_RULING_ID)
    with pytest.raises(FamilyManifestValidationError, match="REGISTERED"):
        load_family_manifest(_write(tmp_path, payload), allow_draft=True)


def test_live_orders_ruling_pattern_is_enforced(tmp_path: Path) -> None:
    payload = dict(_FQ_VALID, live_orders_ruling="not-a-ruling-id")
    with pytest.raises(FamilyManifestValidationError):
        load_family_manifest(_write(tmp_path, payload))


# ---------------------------------------------------------------------------
# Test 2 -- REGISTERED without the key: shadow_only stays True, reason=no_ruling
# ---------------------------------------------------------------------------


def test_registered_without_the_key_gates_no_ruling_and_stays_shadow(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    assert manifest.live_orders_ruling is None

    decision = live_orders_authorized(manifest, tmp_path, permit_present=True)

    assert decision.enabled is False
    assert decision.reason == "no_ruling"


# ---------------------------------------------------------------------------
# Test 3 -- not allowlisted
# ---------------------------------------------------------------------------


def test_an_unallowlisted_ruling_refuses(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path, live_orders_ruling="RULING_some_other_decision_2026-10-01")

    with pytest.raises(LiveOrdersGateRefusedError) as excinfo:
        live_orders_authorized(manifest, tmp_path, permit_present=True)

    assert excinfo.value.reason == "not_allowlisted"


def test_a_correct_ruling_id_for_the_wrong_family_id_refuses(tmp_path: Path) -> None:
    manifest = _manifest(
        tmp_path, family_id="some_other_family", live_orders_ruling=_RULING_ID
    )

    with pytest.raises(LiveOrdersGateRefusedError) as excinfo:
        live_orders_authorized(manifest, tmp_path, permit_present=True)

    assert excinfo.value.reason == "not_allowlisted"


# ---------------------------------------------------------------------------
# Test 4 -- ruling file missing
# ---------------------------------------------------------------------------


def test_a_missing_ruling_file_refuses(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path, live_orders_ruling=_RULING_ID)
    # Deliberately never seeded under tmp_path/docs/evidence/.

    with pytest.raises(LiveOrdersGateRefusedError) as excinfo:
        live_orders_authorized(manifest, tmp_path, permit_present=True)

    assert excinfo.value.reason == "ruling_missing"


# ---------------------------------------------------------------------------
# Test 5 -- ruling sha mismatch (one byte appended)
# ---------------------------------------------------------------------------


def test_a_one_byte_tampered_ruling_file_refuses_on_sha_mismatch(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path, live_orders_ruling=_RULING_ID)
    _seed_real_ruling(tmp_path, corrupt=True)

    with pytest.raises(LiveOrdersGateRefusedError) as excinfo:
        live_orders_authorized(manifest, tmp_path, permit_present=True)

    assert excinfo.value.reason == "ruling_sha_mismatch"


# ---------------------------------------------------------------------------
# Test 6 -- ruling path escapes docs/evidence via a symlink
# ---------------------------------------------------------------------------


def test_a_ruling_file_symlinked_outside_evidence_refuses(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path, live_orders_ruling=_RULING_ID)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "payload.md").write_bytes(_DEPLOY_RULING_PATH.read_bytes())

    rulings_dir = tmp_path / "deploy" / "families" / "rulings"
    rulings_dir.mkdir(parents=True)
    (rulings_dir / f"{_RULING_ID}.md").symlink_to(outside / "payload.md")

    with pytest.raises(LiveOrdersGateRefusedError) as excinfo:
        live_orders_authorized(manifest, tmp_path, permit_present=True)

    assert excinfo.value.reason == "ruling_outside_evidence"


# ---------------------------------------------------------------------------
# Test 7 -- permit absent
# ---------------------------------------------------------------------------


def test_permit_absent_stays_shadow_with_a_clean_ruling(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path, live_orders_ruling=_RULING_ID)
    _seed_real_ruling(tmp_path)

    decision = live_orders_authorized(manifest, tmp_path, permit_present=False)

    assert decision.enabled is False
    assert decision.reason == "permit_absent"
    # Security review (dae1b13b, item required-before-go-live): the boot
    # log's `ruling_sha256=` field must carry the VERIFIED sha even in the
    # permit_absent state -- the ruling itself was already proven clean by
    # the time this reason is reached, only the permit is missing.
    assert decision.ruling_sha256 == _RULING_SHA256


# ---------------------------------------------------------------------------
# Test 8 -- all good: shadow_only=False everywhere (gate + composition)
# ---------------------------------------------------------------------------


def test_all_good_enables_live_orders(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path, live_orders_ruling=_RULING_ID)
    _seed_real_ruling(tmp_path)

    decision = live_orders_authorized(manifest, tmp_path, permit_present=True)

    assert decision.enabled is True
    assert decision.reason == "ok"
    # Security review (dae1b13b): the `fq_live_orders` boot log's
    # `ruling_sha256=` field logs the SHA when the gate is enabled.
    assert decision.ruling_sha256 == _RULING_SHA256


# ---------------------------------------------------------------------------
# Security review required-change: `ruling_sha256=<sha|none>` on the boot
# log line -- the sha when the gate is enabled, `none` when refused.
# ---------------------------------------------------------------------------


def test_ruling_sha256_is_none_when_no_ruling_is_declared(tmp_path: Path) -> None:
    """`app/trade.py` logs `manifest.live_orders_ruling or "none"` for
    `ruling=`, and would do the same for `ruling_sha256=` if the decision
    carried one here -- it must not: nothing was ever verified."""
    manifest = _manifest(tmp_path)

    decision = live_orders_authorized(manifest, tmp_path, permit_present=True)

    assert decision.reason == "no_ruling"
    assert decision.ruling_sha256 is None


@pytest.mark.parametrize(
    "build_manifest",
    [
        lambda tmp_path: _manifest(
            tmp_path, live_orders_ruling="RULING_some_other_decision_2026-10-01"
        ),
    ],
)
def test_a_refused_gate_never_exposes_a_ruling_sha256(
    tmp_path: Path, build_manifest: Any
) -> None:
    """`app/trade.py`'s `except LiveOrdersGateRefusedError` branch hardcodes
    `ruling_sha256=none` on the boot log line -- correct only because the
    exception itself never carries a verified sha for ANY refusing reason
    (not_allowlisted, ruling_missing, ruling_outside_evidence,
    ruling_sha_mismatch alike: none of them completed verification)."""
    manifest = build_manifest(tmp_path)

    with pytest.raises(LiveOrdersGateRefusedError) as excinfo:
        live_orders_authorized(manifest, tmp_path, permit_present=True)

    assert not hasattr(excinfo.value, "ruling_sha256")


def test_the_fq_live_orders_boot_log_line_carries_ruling_sha256() -> None:
    """Pins the actual `app/trade.py` log call shapes -- the refusal branch
    hardcodes the literal `ruling_sha256=none` (nothing was ever verified at
    that point), and the success branch logs the gate's own
    `live_orders.ruling_sha256 or "none"` (the sha when enabled or
    permit_absent, `"none"` only for `no_ruling`)."""
    source = (_REPO_ROOT / "src" / "breezy" / "app" / "trade.py").read_text(encoding="utf-8")

    assert re.search(r"fq_live_orders enabled=False.{0,120}ruling_sha256=none", source, re.DOTALL)
    assert "live_orders.ruling_sha256 or \"none\"" in source
    assert re.search(r"fq_live_orders enabled=%s.{0,160}ruling_sha256=%s", source, re.DOTALL)


def test_shadow_only_propagates_to_every_composed_strategy(tmp_path: Path) -> None:
    """`build_forecast_quantile_ladder_strategies`'s own `shadow_only`
    parameter (FQ-S5) reaches every composed station's config -- the
    composition-level half of items 2 and 8. Reuses the SAME catalog/
    artefact fixtures `test_sl13c_d_plus_1_resolution.py` already builds."""
    from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog

    from tests.strategy.forecast_quantile_ladder.test_sl13c_d_plus_1_resolution import (
        _NOW_NS,
        _BOOT_DAY,
        _D_PLUS_1,
        _LAX,
        _artefact_files,
        _no_instrument,
        _yes_instrument,
    )

    catalog_root = tmp_path / "catalog"
    catalog = ParquetDataCatalog(str(catalog_root))
    yes = _yes_instrument(station=_LAX, climate_day=_D_PLUS_1)
    catalog.write_data([yes, _no_instrument(yes)])
    artefact_path, artefact_sha = _artefact_files(tmp_path)

    for shadow_only in (True, False):
        strategies, _quantile_actor = build_forecast_quantile_ladder_strategies(
            catalog_root=catalog_root,
            today_by_station={_LAX: _BOOT_DAY},
            latch=QuantileLadderLatch(),
            calibration_artefact_path=artefact_path,
            calibration_artefact_sha256=artefact_sha,
            now_ns_fn=lambda: _NOW_NS,
            shadow_only=shadow_only,
        )
        assert strategies
        assert all(s.config.shadow_only is shadow_only for s in strategies)


# ---------------------------------------------------------------------------
# Test 9 -- artefact path containment
# ---------------------------------------------------------------------------


def test_a_traversal_density_artefact_path_is_refused(tmp_path: Path) -> None:
    payload = dict(_FQ_VALID, density_artefact_path="../../etc/x")
    with pytest.raises(FamilyManifestValidationError, match=r"\.\."):
        load_family_manifest(_write(tmp_path, payload))


def test_an_absolute_density_artefact_path_is_refused(tmp_path: Path) -> None:
    payload = dict(_FQ_VALID, density_artefact_path="/etc/x")
    with pytest.raises(FamilyManifestValidationError, match="relative"):
        load_family_manifest(_write(tmp_path, payload))


def test_a_symlinked_density_artefact_path_escaping_the_subtree_is_refused(
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    families_dir = tmp_path / "deploy" / "families"
    families_dir.mkdir(parents=True)
    (families_dir / "evil").symlink_to(outside)

    payload = dict(_FQ_VALID, density_artefact_path="deploy/families/evil/x.json")
    with pytest.raises(FamilyManifestValidationError, match="escapes"):
        load_family_manifest(_write(tmp_path, payload))


def test_a_traversal_boundary_artefact_path_is_refused(tmp_path: Path) -> None:
    payload = dict(_FQ_VALID, boundary_artefact_path="../../etc/x")
    with pytest.raises(FamilyManifestValidationError, match=r"\.\."):
        load_family_manifest(_write(tmp_path, payload))


# ---------------------------------------------------------------------------
# Test 12 -- every committed manifest still loads, byte-identical sha256
# ---------------------------------------------------------------------------


def test_every_committed_manifest_still_loads_with_an_unchanged_sha256() -> None:
    """`deploy/families/*.json` also holds non-manifest artefact files (e.g.
    `gs_boundary_pm_us_crh_v2.json`, a `boundary_artefact_path` TARGET, not
    a manifest) -- a real manifest is any file whose top-level JSON object
    declares `family_id`."""
    families_dir = _REPO_ROOT / "deploy" / "families"
    all_json = sorted(families_dir.glob("*.json"))
    manifest_paths = [
        path for path in all_json if "family_id" in json.loads(path.read_text())
    ]
    assert manifest_paths, "no committed family manifests found"
    assert len(manifest_paths) < len(all_json), (
        "expected at least one non-manifest artefact file alongside the manifests"
    )

    for path in manifest_paths:
        manifest = load_family_manifest(path, allow_draft=True)
        assert manifest.manifest_sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
