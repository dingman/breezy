"""TE-2 pre-freeze fixes (RED then GREEN): the pins must bind the RUNNING code and the committed
tree (H1-H5, M7). Fully synthetic: a tmp git repo with stub family + src dependency files; the
running-module locator is patched to that tree except where H1 itself is under test."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from scripts.analysis import fq_loss_taxonomy_provenance as prov
from scripts.analysis import fq_v1_loss_taxonomy as cli
from scripts.analysis.fq_loss_taxonomy_phase_b import (
    PhaseBInputs,
    PhaseBRefused,
    check_gates,
)
from scripts.analysis.fq_loss_taxonomy_pins import SubprocessGit
from scripts.analysis.fq_loss_taxonomy_predecl import SRC_DEPENDENCIES, unpinned_src_dependencies
from tests.support.te2_fixtures import git_cmd
from tests.support.te2_phase_b_fixtures import (
    FAMILY,
    NOW_NS,
    PINS_REL,
    BPaths,
    build_phase_b,
    faithful_locate,
    rewrite_pins,
    sha256_path,
)
from tests.unit.test_fq_loss_taxonomy_phase_b import (
    _records,
    _router,
)
from tests.unit.test_fq_loss_taxonomy_phase_b import phase_a as shared_phase_a  # noqa: F401

REAL_LOCATE = prov.locate_running
REPO = Path(__file__).resolve().parents[2]
_REQUIRED_DEPS = (
    "src/breezy/settlement/trial_scorer.py",
    "src/breezy/analysis/labeling/fill_source.py",
    "src/breezy/analysis/labeling/settlement_source.py",
    "src/breezy/analysis/labeling/instrument_facts.py",
    "src/breezy/domain/nws_climate_day.py",
    "src/breezy/persistence/catalog.py",
    "src/breezy/registry/sites.py",
)


@pytest.fixture
def phase_a(shared_phase_a: Any) -> Any:  # noqa: F811
    """The module-scoped synthetic Phase A world, re-exported under the usual name."""
    return shared_phase_a


@pytest.fixture(autouse=True)
def _frozen_tmp_tree_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(prov, "locate_running", faithful_locate)


def _built(tmp: Path, phase_a: Any) -> BPaths:
    world, table = phase_a
    return build_phase_b(tmp, world, table)


def _inputs(b: BPaths) -> PhaseBInputs:
    return PhaseBInputs(b.out, b.repo, b.pins, b.predeclaration, b.table, NOW_NS)


def _refusals(b: BPaths, **kw: Any) -> list[str]:
    with pytest.raises(PhaseBRefused) as caught:
        check_gates(_inputs(b), SubprocessGit(b.repo), **kw)
    return caught.value.reasons


def _text(reasons: list[str]) -> str:
    return " | ".join(reasons)


# ---- H1: pins bind the RUNNING code ------------------------------------------------------


def test_a_clean_tree_that_is_the_running_code_passes_and_hashes_the_running_script(
    phase_a: Any, tmp_path: Path
) -> None:
    b = _built(tmp_path, phase_a)

    gates = check_gates(_inputs(b), SubprocessGit(b.repo))

    assert gates.script_sha256 == sha256_path(b.repo / FAMILY[2])


def test_phase_b_refuses_when_a_pinned_module_runs_from_a_different_file(
    phase_a: Any, tmp_path: Path
) -> None:
    b = _built(tmp_path, phase_a)
    other = tmp_path / "elsewhere"
    shutil.copytree(b.repo, other)  # byte-identical, but NOT the file that runs

    reasons = _refusals(b, locate=lambda rel: other / rel)

    assert "running_module_mismatch" in _text(reasons) and FAMILY[0] in _text(reasons)


def test_phase_b_refuses_a_module_that_cannot_be_located(phase_a: Any, tmp_path: Path) -> None:
    b = _built(tmp_path, phase_a)

    assert "running_module_mismatch" in _text(_refusals(b, locate=lambda rel: None))


def test_phase_b_refuses_a_working_file_that_differs_from_its_pin_even_if_git_says_clean(
    phase_a: Any, tmp_path: Path
) -> None:
    class _LyingGit(SubprocessGit):
        def porcelain_clean(self, paths: Any) -> bool:
            return True

    b = _built(tmp_path, phase_a)
    (b.repo / FAMILY[0]).write_text("# tampered after the freeze\n")

    with pytest.raises(PhaseBRefused) as caught:
        check_gates(_inputs(b), _LyingGit(b.repo))

    assert "working_file_mismatch" in _text(caught.value.reasons)


def test_the_real_locator_returns_the_file_that_runs() -> None:
    import breezy.settlement.trial_scorer as scorer
    import scripts.analysis.fq_loss_taxonomy_core as core

    assert REAL_LOCATE(FAMILY[0]) == Path(core.__file__).resolve()
    assert REAL_LOCATE("src/breezy/settlement/trial_scorer.py") == Path(scorer.__file__).resolve()
    assert REAL_LOCATE("scripts/analysis/fq_v1_loss_taxonomy.py") == Path(cli.__file__).resolve()
    assert REAL_LOCATE("src/breezy/registry/sites.toml") is None  # data, not a module
    for rel in (*SRC_DEPENDENCIES, *FAMILY):  # the CLI import loads every pinned module
        if rel.endswith(".py"):
            assert REAL_LOCATE(rel) == (REPO / rel).resolve(), rel


# ---- H2: the src semantics dependencies --------------------------------------------------


def test_the_src_dependency_set_names_the_semantics_modules_phase_b_relies_on() -> None:
    assert set(_REQUIRED_DEPS) <= set(SRC_DEPENDENCIES)
    assert all((REPO / rel).is_file() for rel in SRC_DEPENDENCIES)


def test_unpinned_src_dependencies_lists_every_dependency_missing_from_the_pins() -> None:
    assert unpinned_src_dependencies(SRC_DEPENDENCIES) == ()
    assert unpinned_src_dependencies(SRC_DEPENDENCIES[1:]) == (SRC_DEPENDENCIES[0],)
    assert unpinned_src_dependencies([]) == tuple(sorted(SRC_DEPENDENCIES))


def test_the_dependency_map_generator_hashes_the_head_blobs(phase_a: Any, tmp_path: Path) -> None:
    b = _built(tmp_path, phase_a)

    generated = prov.generate_src_dependency_sha256(SubprocessGit(b.repo))

    assert generated == {rel: sha256_path(b.repo / rel) for rel in SRC_DEPENDENCIES}
    real = prov.generate_src_dependency_sha256(SubprocessGit(REPO))
    assert set(real) == set(SRC_DEPENDENCIES) and all(len(v) == 64 for v in real.values())


def test_phase_b_refuses_pins_that_omit_a_src_dependency(phase_a: Any, tmp_path: Path) -> None:
    b = _built(tmp_path, phase_a)
    rewrite_pins(b, lambda p: p["src_dependency_sha256"].pop(SRC_DEPENDENCIES[0]))

    assert "unpinned_src_dependency" in _text(_refusals(b))


def test_phase_b_refuses_pins_without_the_dependency_map(phase_a: Any, tmp_path: Path) -> None:
    b = _built(tmp_path, phase_a)
    rewrite_pins(b, lambda p: p.pop("src_dependency_sha256"))

    reasons = _refusals(b)

    assert "pins_unusable" in _text(reasons) or "unpinned_src_dependency" in _text(reasons)


def test_phase_b_refuses_a_src_dependency_changed_after_the_freeze(
    phase_a: Any, tmp_path: Path
) -> None:
    b = _built(tmp_path, phase_a)
    (b.repo / SRC_DEPENDENCIES[0]).write_text("# edited and committed\n")
    git_cmd(b.repo, "add", SRC_DEPENDENCIES[0])
    git_cmd(b.repo, "commit", "-q", "-m", "drift")

    assert "head_blob_mismatch" in _text(_refusals(b))


def test_phase_b_refuses_a_dirty_src_dependency(phase_a: Any, tmp_path: Path) -> None:
    b = _built(tmp_path, phase_a)
    (b.repo / SRC_DEPENDENCIES[1]).write_text("# dirty\n")

    assert "dirty_pinned_path" in _text(_refusals(b))


# ---- H3: the pins file itself ------------------------------------------------------------


def test_phase_b_refuses_a_pins_file_outside_the_repo(phase_a: Any, tmp_path: Path) -> None:
    b = _built(tmp_path, phase_a)
    outside = tmp_path / "TE2_PINS.json"
    shutil.copy(b.pins, outside)
    inp = _inputs(b)
    inp = PhaseBInputs(inp.output_dir, inp.repo_root, outside, *(
        getattr(inp, f) for f in ("predeclaration", "phase_a_table", "now_ns")))  # fmt: skip

    with pytest.raises(PhaseBRefused) as caught:
        check_gates(inp, SubprocessGit(b.repo))

    assert "pins_json_outside_repo" in _text(caught.value.reasons)


def test_phase_b_refuses_an_edited_uncommitted_pins_file(phase_a: Any, tmp_path: Path) -> None:
    b = _built(tmp_path, phase_a)
    b.pins.write_text(b.pins.read_text() + "\n")

    assert "pins_json_uncommitted" in _text(_refusals(b))


def test_phase_b_refuses_an_untracked_pins_file(phase_a: Any, tmp_path: Path) -> None:
    b = _built(tmp_path, phase_a)
    git_cmd(b.repo, "rm", "-q", "--cached", PINS_REL)
    git_cmd(b.repo, "commit", "-q", "-m", "untrack pins")

    assert "pins_json_uncommitted" in _text(_refusals(b))


# ---- H4: the predeclaration commit is a full sha -----------------------------------------


@pytest.mark.parametrize(
    "bad", ["HEAD", "b0fe067c", "B0FE067CB6E0902D39CF8FF8E41AD3F2C22BBC8F", ""]
)
def test_phase_b_refuses_a_predeclaration_commit_that_is_not_a_full_lowercase_sha(
    phase_a: Any, tmp_path: Path, bad: str
) -> None:
    b = _built(tmp_path, phase_a)
    rewrite_pins(b, lambda p: p.__setitem__("predeclaration_commit", bad))

    assert "predeclaration_commit_invalid" in _text(_refusals(b))


# ---- M7: malformed pins are a structured refusal, never a traceback ----------------------


@pytest.mark.parametrize(
    "payload",
    [[], "x", {"head_blob_sha256": [], "predeclaration_commit": 5},
     {"head_blob_sha256": "abc", "predeclaration_commit": "0" * 40},
     {"head_blob_sha256": {"a": 1}, "src_dependency_sha256": {}, "predeclaration_commit": "0" * 40},
     {"head_blob_sha256": {"a": "b"}, "src_dependency_sha256": [], "predeclaration_commit": None}],
)  # fmt: skip
def test_malformed_pins_are_refused_with_exit_2_not_a_traceback(
    phase_a: Any, tmp_path: Path, capsys: pytest.CaptureFixture[str], payload: Any
) -> None:
    b = _built(tmp_path, phase_a)
    b.pins.write_text(json.dumps(payload))
    git_cmd(b.repo, "add", PINS_REL)
    git_cmd(b.repo, "commit", "-q", "-m", "bad pins")

    assert cli.main(b.argv()) == cli.EXIT_STOP
    assert "PHASE B REFUSED" in capsys.readouterr().err


def test_a_non_object_phase_a_table_is_refused_not_a_traceback(
    phase_a: Any, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    b = _built(tmp_path, phase_a)
    bad = tmp_path / "list_table.json"
    bad.write_text("[]")
    argv = [str(bad) if a == str(b.table) else a for a in b.argv()]

    assert cli.main(argv) == cli.EXIT_STOP
    assert "PHASE B REFUSED" in capsys.readouterr().err


# ---- H5: verify binds the whole committed tree -------------------------------------------

_EVIDENCE = "docs/evidence/te2"


def _commit_artefact(
    b: BPaths, monkeypatch: pytest.MonkeyPatch, *, tweak: Any = None, skip: tuple[str, ...] = ()
) -> Path:
    """Run Phase B for real over the synthetic tree, then commit its outputs inside the repo."""
    monkeypatch.setattr(cli, "_CatalogRouter", _router(_records()))
    assert cli.main(b.argv()) == 0
    dest = b.repo / _EVIDENCE
    for src in (b.result_json, b.result_md, b.out / "phase_b_audit.json"):
        shutil.copy(src, dest / src.name)
    if tweak is not None:
        tweak(dest)
    paths = [f"{_EVIDENCE}/{p.name}" for p in dest.iterdir() if p.name not in skip]
    paths = [p for p in paths if "PINS" not in p and "PREDECLARATION" not in p]
    git_cmd(b.repo, "add", *paths)
    git_cmd(b.repo, "commit", "-q", "-m", "artefact")
    return dest / b.result_json.name


def _verify(b: BPaths, artefact: Path) -> tuple[str, ...]:
    return prov.verify_artefact(b.repo, b.pins, artefact, SubprocessGit(b.repo))


def test_verify_passes_for_a_clean_complete_committed_artefact(
    phase_a: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    b = _built(tmp_path, phase_a)
    art = _commit_artefact(b, monkeypatch)

    assert _verify(b, art) == ()
    argv = [
        "verify",
        "--repo-root",
        str(b.repo),
        "--pins-json",
        str(b.pins),
        "--artefact",
        str(art),
    ]
    assert cli.main(argv) == 0


def test_verify_fails_when_a_pinned_blob_changed_by_the_artefact_commit(
    phase_a: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    b = _built(tmp_path, phase_a)

    def drift(_dest: Path) -> None:
        (b.repo / FAMILY[0]).write_text("# drifted in the artefact commit\n")
        git_cmd(b.repo, "add", FAMILY[0])

    art = _commit_artefact(b, monkeypatch, tweak=drift)

    assert "pinned_blob_changed_at_artefact_commit" in _text(list(_verify(b, art)))


def test_verify_fails_when_a_src_dependency_changed_by_the_artefact_commit(
    phase_a: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    b = _built(tmp_path, phase_a)

    def drift(_dest: Path) -> None:
        (b.repo / SRC_DEPENDENCIES[2]).write_text("# drifted\n")
        git_cmd(b.repo, "add", SRC_DEPENDENCIES[2])

    art = _commit_artefact(b, monkeypatch, tweak=drift)

    assert "pinned_blob_changed_at_artefact_commit" in _text(list(_verify(b, art)))


@pytest.mark.parametrize(
    "section,key",
    [
        ("provenance", "pins_json_sha256"),
        ("predeclaration", "sha256"),
        ("provenance", "script_sha256"),
    ],
)
def test_verify_fails_when_the_artefact_provenance_differs_from_the_committed_blobs(
    phase_a: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, section: str, key: str
) -> None:
    b = _built(tmp_path, phase_a)

    def forge(dest: Path) -> None:
        path = dest / b.result_json.name
        payload = json.loads(path.read_text())
        payload[section][key] = "0" * 64
        path.write_text(json.dumps(payload))

    art = _commit_artefact(b, monkeypatch, tweak=forge)

    assert "artefact_provenance_mismatch" in _text(list(_verify(b, art)))


@pytest.mark.parametrize("missing", ["md", "audit"])
def test_verify_fails_when_a_sibling_is_not_committed(
    phase_a: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    b = _built(tmp_path, phase_a)
    name = b.result_md.name if missing == "md" else "phase_b_audit.json"
    art = _commit_artefact(b, monkeypatch, skip=(name,))

    assert "artefact_sibling_uncommitted" in _text(list(_verify(b, art)))


def test_verify_fails_when_a_committed_sibling_was_edited_afterwards(
    phase_a: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    b = _built(tmp_path, phase_a)
    art = _commit_artefact(b, monkeypatch)
    art.with_suffix(".md").write_text("edited\n")

    assert "artefact_sibling_uncommitted" in _text(list(_verify(b, art)))


@pytest.mark.parametrize(
    "payload",
    ["{}", "[]", "not json", '{"predeclaration_commit": "0"}', '{"head_blob_sha256": []}'],
)
def test_verify_returns_a_violation_for_unusable_pins_never_a_traceback(
    phase_a: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, payload: str
) -> None:
    b = _built(tmp_path, phase_a)
    art = _commit_artefact(b, monkeypatch)
    b.pins.write_text(payload)

    violations = _verify(b, art)

    assert violations and "pins_unusable" in _text(list(violations))


def test_verify_returns_a_violation_for_a_missing_pins_file(
    phase_a: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    b = _built(tmp_path, phase_a)
    art = _commit_artefact(b, monkeypatch)

    violations = prov.verify_artefact(b.repo, tmp_path / "nope.json", art, SubprocessGit(b.repo))

    assert "pins_unusable" in _text(list(violations))


def test_verify_rejects_a_pins_file_with_a_non_full_sha_predeclaration_commit(
    phase_a: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    b = _built(tmp_path, phase_a)
    art = _commit_artefact(b, monkeypatch)
    payload = json.loads(b.pins.read_text())
    payload["predeclaration_commit"] = "HEAD"
    b.pins.write_text(json.dumps(payload))

    assert "predeclaration_commit_invalid" in _text(list(_verify(b, art)))
