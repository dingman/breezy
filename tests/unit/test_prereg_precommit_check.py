"""FQ F5 FQ-PREREG: the design-JSON pre-commit check
(`scripts/analysis/prereg_precommit_check.py`). Pure and fixture-fed; no repo or network access.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, REPO_ROOT.as_posix())
from scripts.analysis import prereg_precommit_check as chk

SHA = "0123456789abcdef0123456789abcdef01234567"


def _valid() -> dict[str, object]:
    return {
        "frozen_sha": SHA,
        "alpha_total": 0.025,
        "gamma_schedule": "elond_heavy_tailed_v1",
        "T": 4,
        "delta_h": 0.06,
        "n_e_power": {"1": 180, "2": 220, "3": 260, "4": 300},
        "n_e_power_basis": "joint_min_ea_eb",
        "take_rate_lower": 0.5,
        "uptime_floor": 0.9,
        "earliest_look_n": 30,
        "m_cap": 2,
        "x_max": 4.0,
        "lambda_max": 0.5,
        "mu_max": 0.5,
        "betting_rule_e_a": "agrapa_v1:prior_pseudo_days=1,prior_second_moment=0.25",
        "betting_rule_e_b": "agrapa_v1:prior_pseudo_days=1,prior_second_moment=0.25",
        "alpha_kill": 0.05,
        "n_par": 40,
        "delta_par": 0.02,
        "alpha_par": 0.05,
        "parity_bootstrap_seed": 20261006,
        "parity_bootstrap_replicates": 2000,
        "stale_parity_h": 36.0,
        "ask_floor": 0.05,
        "haircut": {"ticks": 1, "tick_size": 0.01},
        "theta": 0.0695,
        "rounding": "half_even_cent_per_contract",
    }


def test_valid_design_passes() -> None:
    assert chk.validate_design(_valid()) == []


def test_design_json_requires_all_e25_keys() -> None:
    assert set(chk.REQUIRED_KEYS) >= {
        "frozen_sha",
        "gamma_schedule",
        "T",
        "delta_h",
        "n_e_power",
        "take_rate_lower",
        "uptime_floor",
        "earliest_look_n",
        "m_cap",
        "x_max",
        "lambda_max",
        "mu_max",
        "betting_rule_e_a",
        "betting_rule_e_b",
        "alpha_kill",
        "n_par",
        "delta_par",
        "alpha_par",
        "parity_bootstrap_seed",
        "parity_bootstrap_replicates",
        "stale_parity_h",
        "ask_floor",
        "haircut",
        "theta",
        "rounding",
    }
    for key in chk.REQUIRED_KEYS:
        design = _valid()
        del design[key]
        errors = chk.validate_design(design)
        assert any(key in e for e in errors), f"missing {key} not reported: {errors}"


def test_design_json_pins_ask_floor_ymax_haircut_theta_rounding() -> None:
    for key in ("ask_floor", "x_max", "haircut", "theta", "rounding"):
        assert key in chk.REQUIRED_KEYS
    bad = _valid()
    bad["ask_floor"] = 0.9
    assert any("ask_floor" in e for e in chk.validate_design(bad))
    bad = _valid()
    bad["x_max"] = 0.0
    assert any("x_max" in e for e in chk.validate_design(bad))
    bad = _valid()
    bad["theta"] = 1.5
    assert any("theta" in e for e in chk.validate_design(bad))
    bad = _valid()
    bad["rounding"] = ""
    assert any("rounding" in e for e in chk.validate_design(bad))
    bad = _valid()
    bad["haircut"] = {"ticks": -1, "tick_size": 0.01}
    assert any("haircut" in e for e in chk.validate_design(bad))


@pytest.mark.parametrize("m_cap", [0, 1, 4, 2.5, "2", True, None])
def test_precommit_refuses_m_cap_outside_2_3(m_cap: object) -> None:
    design = _valid()
    design["m_cap"] = m_cap
    assert any("m_cap" in e for e in chk.validate_design(design))


@pytest.mark.parametrize("m_cap", [2, 3])
def test_precommit_accepts_m_cap_2_and_3(m_cap: int) -> None:
    design = _valid()
    design["m_cap"] = m_cap
    assert chk.validate_design(design) == []


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("lambda_max", 0.51),
        ("lambda_max", 0.0),
        ("mu_max", 0.6),
        ("alpha_kill", 0.1),
        ("alpha_kill", 0.01),
        ("uptime_floor", 1.2),
        ("take_rate_lower", 0.0),
        ("earliest_look_n", 0),
        ("delta_h", 0.0),
        ("parity_bootstrap_replicates", 10),
        ("parity_bootstrap_seed", "abc"),
        ("stale_parity_h", -1),
        ("alpha_total", 0.05),
    ],
)
def test_precommit_refuses_out_of_range_values(key: str, value: object) -> None:
    design = _valid()
    design[key] = value
    assert any(key in e for e in chk.validate_design(design))


@pytest.mark.parametrize("sha", ["", "abc", "G" * 40, SHA.upper(), SHA + "0", None, 7])
def test_precommit_requires_a_40_hex_frozen_sha(sha: object) -> None:
    design = _valid()
    design["frozen_sha"] = sha
    assert any("frozen_sha" in e for e in chk.validate_design(design))


def test_n_e_power_must_be_joint_and_cover_every_look() -> None:
    design = _valid()
    design["n_e_power_basis"] = "e_a_only"
    assert any("joint" in e for e in chk.validate_design(design))
    design = _valid()
    design["n_e_power"] = {"1": 180, "2": 220}
    assert any("n_e_power" in e for e in chk.validate_design(design))
    design = _valid()
    design["n_e_power"] = {"1": 180, "2": 0, "3": 260, "4": 300}
    assert any("n_e_power" in e for e in chk.validate_design(design))


def test_gamma_pins_exactly_one_of_t_or_epoch_budgets() -> None:
    design = _valid()
    design["per_epoch_budgets"] = [0.01, 0.01]
    assert "GAMMA_PIN_BOTH" in {d.code for d in chk.validate_defects(design)}
    design = _valid()
    del design["T"]
    design["per_epoch_budgets"] = [0.01, 0.01]
    design["n_e_power"] = {"1": 1, "2": 2}
    # T is a required E-25 consumption key unless the budgets alternative is pinned
    assert chk.validate_defects(design) == []
    design = _valid()
    del design["T"]
    codes = {d.code for d in chk.validate_defects(design)}
    assert "MISSING_KEY" in codes
    assert "GAMMA_PIN_MISSING" not in codes  # one defect per cause, not two


def test_unknown_keys_are_refused() -> None:
    design = _valid()
    design["surprise"] = 1
    assert any("surprise" in e for e in chk.validate_design(design))


def _git(repo: Path, *args: str) -> str:
    env = {
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_SYSTEM": "/dev/null",
        "PATH": os.environ["PATH"],
        "HOME": str(repo),
    }
    done = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=repo, env=env, check=True, capture_output=True, text=True,
    )  # fmt: skip
    return done.stdout.strip()


def _committed(tmp_path: Path, design: dict[str, object]) -> Path:
    """Commit ``design`` in a throwaway repo, then stamp the commit sha into the file."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    path = repo / "design.json"
    design = {**design, "frozen_sha": "0" * 40}
    path.write_text(json.dumps(design, indent=1, sort_keys=True))
    _git(repo, "add", "design.json")
    _git(repo, "commit", "-q", "-m", "freeze")
    sha = _git(repo, "rev-parse", "HEAD")
    path.write_text(json.dumps({**design, "frozen_sha": sha}, indent=1, sort_keys=True))
    return path


def test_main_exit_codes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    good = _committed(tmp_path, _valid())
    assert chk.main([str(good)]) == 0
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({**_valid(), "m_cap": 5}))
    assert chk.main([str(bad)]) != 0
    assert "m_cap" in capsys.readouterr().err
    assert chk.main([str(tmp_path / "missing.json")]) != 0
    broken = tmp_path / "broken.json"
    broken.write_text("{not json")
    assert chk.main([str(broken)]) != 0
    arr = tmp_path / "arr.json"
    arr.write_text("[]")
    assert chk.main([str(arr)]) != 0


def test_precommit_refuses_a_design_that_differs_from_the_committed_blob(tmp_path: Path) -> None:
    path = _committed(tmp_path, _valid())
    assert chk.main([str(path)]) == 0
    edited = json.loads(path.read_text())
    edited["m_cap"] = 3  # in range, but not what was frozen
    path.write_text(json.dumps(edited, indent=1, sort_keys=True))
    assert chk.validate_design(edited) == []  # shape and range alone would accept it
    assert chk.main([str(path)]) != 0
    assert "FROZEN_BLOB_DIFFERS" in {d.code for d in chk.check_frozen_blob(path, edited)}


def test_precommit_ignores_key_order_and_whitespace_but_not_values(tmp_path: Path) -> None:
    path = _committed(tmp_path, _valid())
    reordered = dict(reversed(list(json.loads(path.read_text()).items())))
    path.write_text(json.dumps(reordered))  # compact, reversed key order
    assert chk.main([str(path)]) == 0


def test_precommit_refuses_an_unreachable_frozen_sha(tmp_path: Path) -> None:
    path = _committed(tmp_path, _valid())
    design = json.loads(path.read_text())
    design["frozen_sha"] = "ab" * 20
    path.write_text(json.dumps(design))
    assert "FROZEN_SHA_UNREACHABLE" in {d.code for d in chk.check_frozen_blob(path, design)}
    assert chk.main([str(path)]) != 0


def test_precommit_refuses_a_file_outside_any_git_repo(tmp_path: Path) -> None:
    path = tmp_path / "loose.json"
    path.write_text(json.dumps(_valid()))
    assert chk.main([str(path)]) != 0


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("theta", 0.06),
        ("ask_floor", 0.1),
        ("haircut", {"ticks": 2, "tick_size": 0.01}),
        ("betting_rule_e_a", "agrapa_v1:prior_pseudo_days=2,prior_second_moment=0.25"),
        ("betting_rule_e_b", "something_else"),
    ],
)
def test_precommit_pins_mc_constants(key: str, value: object, tmp_path: Path) -> None:
    design = _valid()
    design[key] = value
    assert "PIN_MISMATCH" in {d.code for d in chk.validate_defects(design)}
    path = _committed(tmp_path, design)  # frozen and committed, still refused
    assert chk.main([str(path)]) != 0


def test_pins_are_imported_from_the_mc_not_duplicated() -> None:
    from scripts.analysis import fq_mc_eprocess, fq_mc_livedata

    assert chk.PINNED_THETA == fq_mc_livedata.LoopConfig().theta
    assert chk.PINNED_ASK_FLOOR == fq_mc_livedata.LoopConfig().ask_floor
    assert chk.PINNED_BETTING_RULE == fq_mc_eprocess.BETTING_RULE
    source = (REPO_ROOT / "scripts/analysis/prereg_precommit_check.py").read_text()
    assert "0.0695" not in source
    assert "agrapa_v1" not in source
