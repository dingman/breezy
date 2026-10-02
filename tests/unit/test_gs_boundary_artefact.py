"""RED-first suite for `persistence/gs_boundary_artefact.py` (blueprint commit 2).

`docs/specs/PREREG_v2_current_rung_hold_DRAFT_2026-09-04.md` rev b SS3/SS7,
`docs/plans/FAMILY_TALLY_V2_BLUEPRINT_2026-09-04.md` "Tests" -- "Boundary
artefact".
"""

from __future__ import annotations

import ast
import copy
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

import breezy.persistence.gs_boundary_artefact as artefact_mod
from breezy.persistence.gs_boundary_artefact import (
    ALPHA_ONE_SIDED,
    I_MAX,
    BoundaryArtefact,
    BoundaryArtefactValidationError,
    BoundaryPinMismatch,
    load_boundary_artefact,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ARTEFACT_PATH = _REPO_ROOT / "deploy" / "families" / "gs_boundary_pm_us_crh_v2.json"
_FAMILIES_DIR = _REPO_ROOT / "deploy" / "families"
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "analysis" / "crh_group_sequential_boundaries.py"
_PINNED_SHA = "471fd8a7ea781365d0e892cde87a65b5408126c07d8bb28e515b4c493c150e0c"


def _payload() -> dict[str, Any]:
    payload: dict[str, Any] = json.loads(_ARTEFACT_PATH.read_text())
    return payload


def _write(tmp_path: Path, payload: dict[str, Any]) -> Path:
    path = tmp_path / "artefact.json"
    path.write_text(json.dumps(payload))
    return path


def _load_boundary_generator_script() -> ModuleType:
    module_name = "breezy_test_crh_group_sequential_boundaries_parity"
    spec = importlib.util.spec_from_file_location(module_name, _SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    previous = sys.modules.get(module_name)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        if previous is None:
            sys.modules.pop(module_name, None)
        else:
            sys.modules[module_name] = previous
    return module


def _registered_boundary_pins() -> list[tuple[str, Path, str]]:
    pins: list[tuple[str, Path, str]] = []
    for path in sorted(_FAMILIES_DIR.glob("*.json")):
        payload = json.loads(path.read_text())
        if payload.get("status") != "REGISTERED":
            continue
        artefact_rel = payload.get("boundary_artefact_path")
        if not isinstance(artefact_rel, str) or "not_applicable_boundary" in artefact_rel:
            continue
        sha = payload.get("boundary_inputs_sha256")
        assert isinstance(sha, str)
        artefact_path = _REPO_ROOT / artefact_rel
        assert artefact_path.exists()
        pins.append((payload["family_id"], artefact_path, sha))
    return pins


def _src_brentq_xtol_literals() -> list[float]:
    assert artefact_mod.__file__ is not None
    tree = ast.parse(Path(artefact_mod.__file__).read_text())
    xtols: list[float] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Name) or node.func.id != "brentq":
            continue
        for keyword in node.keywords:
            if keyword.arg == "xtol":
                value = ast.literal_eval(keyword.value)
                assert isinstance(value, float)
                xtols.append(value)
    return xtols


@pytest.fixture(scope="module")
def artefact() -> BoundaryArtefact:
    return load_boundary_artefact(_ARTEFACT_PATH, expected_sha256=_PINNED_SHA)


def test_registered_boundary_parameters_match_the_ruling_cited_script() -> None:
    """R2.1 parity pin: registered CRH manifests reuse one applicable boundary
    artefact. The script exposes `BRENTQ_XTOL`; the src implementation still
    carries the same `1e-10` as two brentq `xtol` literals, so this test pins
    both forms without editing the frozen script or the src solver.
    """
    script = _load_boundary_generator_script()
    pins = _registered_boundary_pins()
    discovered = {family_id for family_id, _path, _sha in pins}
    assert discovered
    assert {"pm_us_crh_cont", "pm_us_crh_v2", "pm_us_crh_v4"} <= discovered
    assert script.BRENTQ_XTOL == 1e-10
    assert _src_brentq_xtol_literals() == [1e-10, 1e-10]

    checked: set[tuple[Path, str]] = set()
    for _family_id, artefact_path, expected_sha in pins:
        if (artefact_path, expected_sha) in checked:
            continue
        checked.add((artefact_path, expected_sha))
        loaded = load_boundary_artefact(artefact_path, expected_sha256=expected_sha)
        generated = script.build_output(
            loaded.alpha_one_sided,
            loaded.spending.n_max,
            loaded.spending.look_step,
        )
        assert generated["spending_id"] == loaded.spending.spending_id
        assert generated["inputs_sha256"] == expected_sha
        assert generated["i_max"] == loaded.i_max
        script_rows = generated["reference_table"]
        assert len(script_rows) == len(loaded.reference_rows)
        history: list[float] = []
        for idx, script_row in enumerate(script_rows):
            row = loaded.reference_rows[idx]
            history.append(row.t_k)
            assert script_row["look_k"] == row.look_k
            assert script_row["n_k"] == row.n_k
            assert script_row["t_k"] == row.t_k
            assert script_row["alpha_spent_eff"] == row.alpha_spent_eff
            assert script_row["alpha_spent_fut"] == row.alpha_spent_fut
            src_b_eff, src_b_fut = loaded.boundary_for(
                history, is_terminal=idx == len(script_rows) - 1
            )
            assert src_b_eff == pytest.approx(script_row["b_eff"], abs=1e-6)
            assert src_b_fut == pytest.approx(script_row["b_fut"], abs=1e-6)


def test_the_committed_pm_us_artefact_loads_and_pins_correctly(
    artefact: BoundaryArtefact,
) -> None:
    assert artefact.inputs_sha256 == _PINNED_SHA
    assert artefact.i_max == I_MAX
    assert artefact.alpha_one_sided == ALPHA_ONE_SIDED
    assert artefact.spending.n_max == 160
    assert artefact.spending.look_step == 10
    assert len(artefact.reference_rows) == 16


def test_sha_mismatch_against_the_callers_pin_raises(tmp_path: Path) -> None:
    path = _write(tmp_path, _payload())
    with pytest.raises(BoundaryPinMismatch):
        load_boundary_artefact(path, expected_sha256="a" * 64)


def test_a_hand_edited_parameter_desyncs_the_self_hash_and_raises(tmp_path: Path) -> None:
    payload = _payload()
    payload["look_step"] = 5  # inputs_sha256 no longer matches the recomputed manifest
    path = _write(tmp_path, payload)
    with pytest.raises(BoundaryPinMismatch):
        load_boundary_artefact(path, expected_sha256=payload["inputs_sha256"])


def test_i_max_off_pin_is_refused(tmp_path: Path) -> None:
    payload = _payload()
    payload["i_max"] = 41.0
    # Recompute the self-hash so the sha check passes and the i_max check is
    # the one that actually fires.
    from breezy.persistence.gs_boundary_artefact import _inputs_manifest, _sha256_of_inputs

    manifest = _inputs_manifest(
        payload["alpha"],
        payload["spending_id"],
        payload["n_max"],
        payload["i_max"],
        payload["look_step"],
    )
    payload["inputs_sha256"] = _sha256_of_inputs(manifest)
    path = _write(tmp_path, payload)
    with pytest.raises(BoundaryArtefactValidationError):
        load_boundary_artefact(path, expected_sha256=payload["inputs_sha256"])


def test_alpha_off_pin_is_refused(tmp_path: Path) -> None:
    payload = _payload()
    payload["alpha"] = 0.05
    from breezy.persistence.gs_boundary_artefact import _inputs_manifest, _sha256_of_inputs

    manifest = _inputs_manifest(
        payload["alpha"],
        payload["spending_id"],
        payload["n_max"],
        payload["i_max"],
        payload["look_step"],
    )
    payload["inputs_sha256"] = _sha256_of_inputs(manifest)
    path = _write(tmp_path, payload)
    with pytest.raises(BoundaryArtefactValidationError):
        load_boundary_artefact(path, expected_sha256=payload["inputs_sha256"])


def test_a_tampered_reference_row_value_is_refused_by_the_replay(tmp_path: Path) -> None:
    payload = _payload()
    payload["reference_table"][-1]["b_eff"] = 9.999
    path = _write(tmp_path, payload)
    with pytest.raises(BoundaryPinMismatch):
        load_boundary_artefact(path, expected_sha256=payload["inputs_sha256"])


def test_an_extreme_tail_row_tolerates_a_1e_2_boundary_perturbation(tmp_path: Path) -> None:
    """B4: reference_table[0] (look_k=1, alpha_spent_eff=2.2e-15 << 1e-6) is
    an extreme-tail early look at an unreachable ~7.8 SD boundary -- the
    relaxed 5e-2 tolerance must let a 1e-2 perturbation load."""
    payload = _payload()
    payload["reference_table"][0]["b_eff"] += 1e-2
    path = _write(tmp_path, payload)
    artefact = load_boundary_artefact(path, expected_sha256=payload["inputs_sha256"])
    assert artefact.inputs_sha256 == payload["inputs_sha256"]


def test_a_non_extreme_tail_row_still_refuses_the_same_1e_2_perturbation(tmp_path: Path) -> None:
    """B4: reference_table[7] (look_k=8, alpha_spent_eff=2.8e-3 >= 1e-6) is
    NOT extreme-tail -- the tight 1e-6 tolerance must still refuse a 1e-2
    perturbation on this row."""
    payload = _payload()
    assert payload["reference_table"][7]["alpha_spent_eff"] >= 1e-6
    payload["reference_table"][7]["b_eff"] += 1e-2
    path = _write(tmp_path, payload)
    with pytest.raises(BoundaryPinMismatch):
        load_boundary_artefact(path, expected_sha256=payload["inputs_sha256"])


def test_n_max_not_a_multiple_of_look_step_is_refused(tmp_path: Path) -> None:
    """B5: the look schedule invariant -- `n_max % look_step` must be 0."""
    payload = _payload()
    payload["look_step"] = 7  # n_max=160, 160 % 7 != 0
    from breezy.persistence.gs_boundary_artefact import _inputs_manifest, _sha256_of_inputs

    manifest = _inputs_manifest(
        payload["alpha"],
        payload["spending_id"],
        payload["n_max"],
        payload["i_max"],
        payload["look_step"],
    )
    payload["inputs_sha256"] = _sha256_of_inputs(manifest)
    path = _write(tmp_path, payload)
    with pytest.raises(BoundaryArtefactValidationError):
        load_boundary_artefact(path, expected_sha256=payload["inputs_sha256"])


def test_a_missing_required_top_level_key_is_refused(tmp_path: Path) -> None:
    payload = _payload()
    del payload["look_step"]
    path = _write(tmp_path, payload)
    with pytest.raises(BoundaryArtefactValidationError):
        load_boundary_artefact(path, expected_sha256=payload.get("inputs_sha256", ""))


def test_an_empty_reference_table_is_refused(tmp_path: Path) -> None:
    payload = _payload()
    payload["reference_table"] = []
    from breezy.persistence.gs_boundary_artefact import _inputs_manifest, _sha256_of_inputs

    manifest = _inputs_manifest(
        payload["alpha"],
        payload["spending_id"],
        payload["n_max"],
        payload["i_max"],
        payload["look_step"],
    )
    payload["inputs_sha256"] = _sha256_of_inputs(manifest)
    path = _write(tmp_path, payload)
    with pytest.raises(BoundaryArtefactValidationError):
        load_boundary_artefact(path, expected_sha256=payload["inputs_sha256"])


def test_additive_top_level_keys_do_not_break_loading(tmp_path: Path) -> None:
    """Coordinator note 2026-09-04: the generator owner adds `usage` and
    `solver_fingerprint` as ADDITIVE top-level keys; the loader must not
    assert an exact top-level key set."""
    payload = _payload()
    payload["usage"] = (
        "reference_table is regression_fixture_only; "
        "live boundaries come from boundary_for(t_history)"
    )
    payload["solver_fingerprint"] = "deadbeef" * 8
    path = _write(tmp_path, payload)
    artefact = load_boundary_artefact(path, expected_sha256=payload["inputs_sha256"])
    assert artefact.inputs_sha256 == payload["inputs_sha256"]


def test_a_usage_key_missing_the_regression_fixture_only_substring_is_refused(
    tmp_path: Path,
) -> None:
    payload = _payload()
    payload["usage"] = "some other unrelated note"
    path = _write(tmp_path, payload)
    with pytest.raises(BoundaryArtefactValidationError):
        load_boundary_artefact(path, expected_sha256=payload["inputs_sha256"])


def test_invalid_json_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "artefact.json"
    path.write_text("{not json")
    with pytest.raises(BoundaryArtefactValidationError):
        load_boundary_artefact(path, expected_sha256="a" * 64)


# --- boundary_for / alpha_spent / remaining_alpha ---------------------------


def test_solver_reproduces_the_16_row_reference_fixture_to_1e_9(
    artefact: BoundaryArtefact,
) -> None:
    t_history: list[float] = []
    for idx, row in enumerate(artefact.reference_rows):
        t_history.append(row.t_k)
        is_terminal = idx == len(artefact.reference_rows) - 1
        b_eff, b_fut = artefact.boundary_for(tuple(t_history), is_terminal=is_terminal)
        assert b_eff == pytest.approx(row.b_eff, abs=1e-9)
        assert b_fut == pytest.approx(row.b_fut, abs=1e-9)


def test_terminal_look_spends_exactly_the_remaining_alpha_cumulative_0_025(
    artefact: BoundaryArtefact,
) -> None:
    last = artefact.reference_rows[-1]
    assert last.alpha_spent_eff == pytest.approx(0.025, abs=1e-6)
    assert last.alpha_spent_fut == pytest.approx(0.025, abs=1e-6)


def test_a_tie_in_t_history_does_not_raise_and_yields_a_degenerate_pair(
    artefact: BoundaryArtefact,
) -> None:
    b_eff, b_fut = artefact.boundary_for((0.0625, 0.0625))
    assert b_eff == float("inf")
    assert b_fut == float("-inf")


def test_a_strict_decrease_in_t_history_raises(artefact: BoundaryArtefact) -> None:
    with pytest.raises(ValueError):
        artefact.boundary_for((0.5, 0.25))


def test_t_history_must_be_non_empty(artefact: BoundaryArtefact) -> None:
    with pytest.raises(ValueError):
        artefact.boundary_for(())


def test_t_outside_0_1_range_raises(artefact: BoundaryArtefact) -> None:
    with pytest.raises(ValueError):
        artefact.boundary_for((1.5,))
    with pytest.raises(ValueError):
        artefact.boundary_for((0.0,))


def test_remaining_alpha_at_look_0_is_exactly_0_025(artefact: BoundaryArtefact) -> None:
    assert artefact.remaining_alpha(()) == 0.025


def test_remaining_alpha_after_a_completed_look_is_alpha_minus_spent(
    artefact: BoundaryArtefact,
) -> None:
    t_history = (0.0625,)
    spent = artefact.alpha_spent(t_history)
    assert artefact.remaining_alpha(t_history) == pytest.approx(0.025 - spent)


def test_alpha_spent_depends_only_on_the_last_t_not_the_path(
    artefact: BoundaryArtefact,
) -> None:
    direct = artefact.alpha_spent((0.25,))
    via_path = artefact.alpha_spent((0.0625, 0.125, 0.1875, 0.25))
    assert direct == pytest.approx(via_path, abs=1e-12)


def test_boundary_reference_rows_are_immutable_data(artefact: BoundaryArtefact) -> None:
    rows = artefact.reference_rows
    rows_copy = copy.deepcopy(rows)
    # calling boundary_for must not mutate the stored reference rows
    artefact.boundary_for((0.0625,))
    assert artefact.reference_rows == rows_copy


def test_load_boundary_artefact_convolves_at_most_once_per_look_gap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """K=16 equal-t load replay must be one forward walk (K-1 convolutions),
    not a triangular restart of `_solve_boundary` on each growing prefix."""
    import breezy.persistence.gs_boundary_artefact as mod

    calls = {"n": 0}
    real = mod._convolve_density

    def spy(*args: Any, **kwargs: Any) -> Any:
        calls["n"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(mod, "_convolve_density", spy)
    load_boundary_artefact(_ARTEFACT_PATH, expected_sha256=_PINNED_SHA)
    assert calls["n"] <= 15


def test_incremental_replay_matches_committed_artefact_rows_with_zero_delta() -> None:
    """Behaviour-preservation: one forward walk of the loader solver must
    reproduce every committed `b_eff`/`b_fut` exactly -- not merely within
    the 1e-6 (or extreme-tail 5e-2) load-time pin."""
    import breezy.persistence.gs_boundary_artefact as mod

    recorded = _payload()["reference_table"]
    t_history = tuple(float(row["t_k"]) for row in recorded)
    walked = list(mod._iter_boundary_looks(t_history, ALPHA_ONE_SIDED, is_terminal=True))
    max_delta = 0.0
    for (b_eff, b_fut), row in zip(walked, recorded, strict=True):
        max_delta = max(
            max_delta, abs(b_eff - float(row["b_eff"])), abs(b_fut - float(row["b_fut"]))
        )
    assert max_delta == 0.0
