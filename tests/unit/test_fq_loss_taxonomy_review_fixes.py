"""TE-2 WP1b (RED then GREEN): fixes from the 7f3e8661 code review (items 5-8, 10).

Items 1-4 and 9 are covered in ``test_fq_loss_taxonomy_cli.py``.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from scripts.analysis import fq_loss_taxonomy_pins as pins_module
from scripts.analysis.fq_loss_taxonomy_core import (
    holdout_violations,
    holm_decisions,
    holm_plan,
    t_spread_power,
)
from scripts.analysis.fq_loss_taxonomy_stats import T_LOC_TWO_SIDED_FORMULA
from scripts.analysis.fq_loss_taxonomy_inputs import SubprocessGit, phase_b_refusals
from tests.support.te2_fixtures import tmp_git_repo

_ALLOWED = ("math",)


def test_phase_b_refusals_rejects_an_empty_pin_set_instead_of_passing_vacuously() -> None:
    class _Git:
        def __getattr__(self, name: str) -> object:
            raise AssertionError(f"git must not be consulted for an empty pin set: {name}")

    with pytest.raises(ValueError, match="empty"):
        phase_b_refusals({}, "abc", _Git())  # type: ignore[arg-type]


def test_git_env_keeps_status_read_only_and_revisions_cannot_inject_options(tmp_path: Path) -> None:
    assert pins_module._GIT_ENV["GIT_OPTIONAL_LOCKS"] == "0"
    repo = tmp_path / "repo"
    commits = tmp_git_repo(repo, ["{}\n"])
    git = SubprocessGit(repo)

    assert git.is_ancestor(commits[0], "HEAD") is True
    with pytest.raises(RuntimeError):  # an option-shaped revision is a revision, not a flag
        git.is_ancestor("--version", "HEAD")
    with pytest.raises(RuntimeError):
        git.log_commits(("manifest.json",), "--version")


def test_show_blob_returns_the_committed_bytes_and_raises_when_absent(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    commits = tmp_git_repo(repo, ['{"a": 1}\n', '{"a": 2}\n'])
    git = SubprocessGit(repo)

    assert git.show_blob(commits[0], "manifest.json") == b'{"a": 1}\n'
    assert git.show_blob(commits[1], "manifest.json") == b'{"a": 2}\n'
    with pytest.raises(RuntimeError):
        git.show_blob(commits[0], "missing.json")


def test_ast_pin_decodes_bytes_constants_and_catches_m1v3_suffixes() -> None:
    bypasses = {
        "bytes path": "p = b'docs/evidence/m1v3/result.json'\n",
        "bytes opener": "p = b'" + "open_" + "holdout'\n",
        "suffix underscore": "p = 'data/m1v3_x.json'\n",
        "suffix star": "p = 'data/m1v3*'\n",
        "suffix dot": "p = 'data/m1v3.json'\n",
        "dash spelling": "p = 'data/M1-v3/rows'\n",
    }
    for label, source in bypasses.items():
        assert holdout_violations(source, _ALLOWED), label
    assert holdout_violations("p = 'M1-v3 CONFIRM'\n", _ALLOWED) == ()  # the route name is prose
    assert holdout_violations("p = b'plain bytes'\n", _ALLOWED) == ()


def test_t_loc_formula_is_pinned_for_the_predeclaration() -> None:
    assert T_LOC_TWO_SIDED_FORMULA == "doubled_smaller_tail"


def test_holm_decisions_apply_holm_to_the_testable_members_only() -> None:
    plan = holm_plan({"T-LOC": 0.0156, "T-SPREAD": 0.001})

    raw_only = holm_decisions({"T-LOC": 0.015, "T-SPREAD": 0.019}, plan)
    both = holm_decisions({"T-LOC": 0.004, "T-SPREAD": 0.019}, plan)
    stepped = holm_decisions({"T-LOC": 0.025, "T-SPREAD": 0.009}, plan)

    assert raw_only == {"T-LOC": False, "T-SPREAD": False}  # a raw p <= 0.02 is not a rejection
    assert both == {"T-LOC": True, "T-SPREAD": True}
    assert stepped == {"T-LOC": False, "T-SPREAD": True}  # 0.009 <= 0.02/2; then 0.025 > 0.02
    dropped = holm_plan({"T-LOC": 0.5, "T-SPREAD": 0.001})
    assert holm_decisions({"T-LOC": 0.0001, "T-SPREAD": 0.001}, dropped) == {
        "T-LOC": False, "T-SPREAD": True,
    }  # fmt: skip


def test_t_spread_power_docstring_states_the_no_reject_region_case() -> None:
    doc = inspect.getdoc(t_spread_power) or ""

    assert "0" in doc and "no x" in doc.lower()
