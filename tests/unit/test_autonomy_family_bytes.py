"""ARCH-0 seam 6d: ``family_bytes`` root copies (E-14) and the manifest-facts reader (AC 21, 28)."""

from __future__ import annotations

import ast
import hashlib
import os
import shutil
from collections.abc import Iterator
from functools import partial
from pathlib import Path
from typing import Any

import pytest

from breezy.persistence.autonomy import family_bytes
from breezy.persistence.autonomy.canonical import canonical_json
from breezy.persistence.autonomy.family_bytes import (
    RootCopyIntegrity,
    RootCopyResult,
    read_manifest_facts,
    write_root_copy,
)
from breezy.persistence.autonomy.lineage import RootRecord, root_model_class
from breezy.persistence.autonomy.paths import AutonomyPaths, ShadowPaths
from breezy.persistence.autonomy.schemas import ManifestFacts
from breezy.persistence.autonomy.single_read import SingleReadReason, SingleReadRefused
from breezy.persistence.autonomy.wire import WireRefused
from tests.support.entry_points import REPO_ROOT

KIND = "continuous_rung_hold"
FAMILY = "pm_us_crh_v4"
ARTEFACT = b'{"placeholder":"not_applicable_density"}\n'
ARTEFACT_SHA = hashlib.sha256(ARTEFACT).hexdigest()
MANIFEST_SRC = REPO_ROOT / "deploy" / "families" / f"{FAMILY}.json"


def _record(family_id: str = FAMILY, manifest_sha: str = "a" * 64) -> RootRecord:
    return RootRecord(family_id, manifest_sha, ARTEFACT_SHA, f"deploy/families/{family_id}.json")


@pytest.fixture
def data_root(tmp_path: Path) -> Iterator[Path]:
    root = tmp_path / "data"
    root.mkdir(mode=0o700)
    yield root
    for directory in [root, *root.rglob("*")]:
        if directory.is_dir() and not directory.is_symlink():
            directory.chmod(0o700)


def _copy(paths: Any, **overrides: Any) -> RootCopyResult:
    kwargs: dict[str, Any] = {
        "record": _record(),
        "artefact_raw": ARTEFACT,
        "composition_kind": KIND,
    }
    return write_root_copy(paths, **{**kwargs, **overrides})


# ----------------------------------------------------------------------- write_root_copy


def test_write_root_copy_lays_out_the_e14_files_read_only(data_root: Path) -> None:
    paths = AutonomyPaths(data_root)
    assert _copy(paths) is RootCopyResult.WRITTEN
    sha_dir = paths.artefact_dir(root_model_class(KIND), ARTEFACT_SHA)
    record_path = paths.root_record(root_model_class(KIND), ARTEFACT_SHA, FAMILY)
    assert record_path == sha_dir / "roots" / f"{FAMILY}.json"
    assert (sha_dir / "artefact.json").read_bytes() == ARTEFACT
    assert record_path.read_bytes() == canonical_json(_record().to_wire())
    assert os.stat(sha_dir / "artefact.json").st_mode & 0o777 == 0o444
    assert os.stat(record_path).st_mode & 0o777 == 0o444
    assert sorted(p.name for p in sha_dir.iterdir()) == ["artefact.json", "roots"]


def test_write_root_copy_rerun_is_exists_equal(data_root: Path) -> None:
    paths = AutonomyPaths(data_root)
    _copy(paths)
    assert _copy(paths) is RootCopyResult.EXISTS_EQUAL


def test_a_crash_between_the_two_files_is_completed_by_the_rerun(data_root: Path) -> None:
    paths = AutonomyPaths(data_root)
    _copy(paths)
    record_path = paths.root_record(root_model_class(KIND), ARTEFACT_SHA, FAMILY)
    record_path.unlink()  # the crash window: artefact.json written, the record not
    assert _copy(paths) is RootCopyResult.WRITTEN
    assert record_path.read_bytes() == canonical_json(_record().to_wire())


def test_shadow_paths_write_under_the_shadow_root(data_root: Path) -> None:
    shadow = ShadowPaths(data_root / "registry-shadow")
    (data_root / "registry-shadow").mkdir(mode=0o700)
    assert _copy(shadow) is RootCopyResult.WRITTEN
    assert (
        shadow.artefact_dir(root_model_class(KIND), ARTEFACT_SHA) / "artefact.json"
    ).read_bytes() == ARTEFACT


def test_artefact_bytes_must_hash_to_the_record_sha_and_nothing_is_written(
    data_root: Path,
) -> None:
    with pytest.raises(RootCopyIntegrity):
        _copy(AutonomyPaths(data_root), artefact_raw=ARTEFACT + b" ")
    assert list(data_root.iterdir()) == []


@pytest.mark.parametrize("kind", ["unknown_kind", "", "../x", "forecast_ladder:density_table"])
def test_an_unknown_composition_kind_is_refused_before_any_write(
    data_root: Path, kind: str
) -> None:
    with pytest.raises(WireRefused):
        _copy(AutonomyPaths(data_root), composition_kind=kind)
    assert list(data_root.iterdir()) == []


def test_write_root_copy_refuses_a_non_record(data_root: Path) -> None:
    with pytest.raises(WireRefused):
        _copy(AutonomyPaths(data_root), record=_record().to_wire())
    assert list(data_root.iterdir()) == []


def test_write_root_copy_refuses_a_non_bytes_artefact(data_root: Path) -> None:
    with pytest.raises(WireRefused):
        _copy(AutonomyPaths(data_root), artefact_raw="text")
    assert list(data_root.iterdir()) == []


def test_a_symlinked_sha_directory_is_refused_and_not_followed(
    tmp_path: Path, data_root: Path
) -> None:
    paths = AutonomyPaths(data_root)
    parent = paths.artefact_dir(root_model_class(KIND), ARTEFACT_SHA).parent
    parent.mkdir(parents=True, mode=0o700)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (parent / ARTEFACT_SHA).symlink_to(elsewhere)
    with pytest.raises(SingleReadRefused) as caught:
        _copy(paths)
    assert caught.value.reason is SingleReadReason.SYMLINK
    assert list(elsewhere.iterdir()) == []


def test_a_sealed_sha_directory_refuses_a_new_root_by_mode_bit(data_root: Path) -> None:
    paths = AutonomyPaths(data_root)
    _copy(paths)
    sha_dir = paths.artefact_dir(root_model_class(KIND), ARTEFACT_SHA)
    (sha_dir / "roots").chmod(0o500)
    sha_dir.chmod(0o500)
    with pytest.raises(SingleReadRefused) as caught:
        _copy(paths, record=_record("pm_us_crh_cont", "b" * 64))
    assert caught.value.reason is SingleReadReason.DIR_NOT_WRITABLE


def test_a_symlinked_artefact_json_is_integrity_not_followed(
    tmp_path: Path, data_root: Path
) -> None:
    paths = AutonomyPaths(data_root)
    sha_dir = paths.artefact_dir(root_model_class(KIND), ARTEFACT_SHA)
    sha_dir.mkdir(parents=True, mode=0o700)
    target = tmp_path / "target.json"
    target.write_bytes(ARTEFACT)
    (sha_dir / "artefact.json").symlink_to(target)
    with pytest.raises(RootCopyIntegrity):
        _copy(paths)


def test_integrity_message_names_no_path(data_root: Path) -> None:
    paths = AutonomyPaths(data_root)
    _copy(paths)
    with pytest.raises(RootCopyIntegrity) as caught:
        _copy(paths, record=_record(manifest_sha="b" * 64))
    assert str(data_root) not in str(caught.value)


# ------------------------------------------------------------------ read_manifest_facts


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    families = tmp_path / "repo" / "deploy" / "families"
    families.mkdir(parents=True)
    shutil.copy(MANIFEST_SRC, families / MANIFEST_SRC.name)
    return tmp_path / "repo"


def _manifest_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _facts(repo: Path, data_root: Path, family: str, sha: str) -> ManifestFacts | None:
    return read_manifest_facts(family, sha, paths=AutonomyPaths(data_root), repo_root=repo)


def test_a_committed_root_manifest_yields_its_facts(repo: Path, data_root: Path) -> None:
    sha = _manifest_sha(repo / "deploy" / "families" / f"{FAMILY}.json")
    assert _facts(repo, data_root, FAMILY, sha) == ManifestFacts(
        family_id=FAMILY,
        manifest_sha256=sha,
        d0_climate_day="2026-09-20",
        trial_id_prefix="continuous_rung_hold/trial/",
        composition_kind="continuous_rung_hold",
    )


def test_the_reader_binds_with_partial_to_the_manifest_reader_protocol(
    repo: Path, data_root: Path
) -> None:
    sha = _manifest_sha(repo / "deploy" / "families" / f"{FAMILY}.json")
    reader = partial(read_manifest_facts, paths=AutonomyPaths(data_root), repo_root=repo)
    facts = reader(FAMILY, sha)
    assert facts is not None and facts.family_id == FAMILY


def test_a_wrong_sha_is_unreadable(repo: Path, data_root: Path) -> None:
    assert _facts(repo, data_root, FAMILY, "0" * 64) is None


def test_an_edited_committed_manifest_is_unreadable_at_the_old_sha(
    repo: Path, data_root: Path
) -> None:
    path = repo / "deploy" / "families" / f"{FAMILY}.json"
    old_sha = _manifest_sha(path)
    path.write_bytes(path.read_bytes() + b"\n")
    assert _facts(repo, data_root, FAMILY, old_sha) is None
    assert _facts(repo, data_root, FAMILY, _manifest_sha(path)) is not None


def test_a_missing_family_and_a_missing_directory_are_unreadable(
    repo: Path, data_root: Path, tmp_path: Path
) -> None:
    assert _facts(repo, data_root, "pm_us_crh_nope", "a" * 64) is None
    assert _facts(tmp_path / "no_repo", data_root, FAMILY, "a" * 64) is None
    assert _facts(repo, tmp_path / "no_data", FAMILY, "a" * 64) is None


@pytest.mark.parametrize("family", ["", "../x", "A", "a/b", "x" * 65, "a\0b"])
def test_a_malformed_family_id_is_unreadable(repo: Path, data_root: Path, family: str) -> None:
    assert _facts(repo, data_root, family, "a" * 64) is None


@pytest.mark.parametrize("sha", ["", "A" * 64, "a" * 63, "a" * 64 + "\n"])
def test_a_malformed_sha_is_unreadable(repo: Path, data_root: Path, sha: str) -> None:
    assert _facts(repo, data_root, FAMILY, sha) is None


def test_a_draft_manifest_is_never_loaded(repo: Path, data_root: Path) -> None:
    path = repo / "deploy" / "families" / f"{FAMILY}.json"
    path.write_bytes(path.read_bytes().replace(b"REGISTERED", b"DRAFT_NOT_REGISTERED"))
    assert _facts(repo, data_root, FAMILY, _manifest_sha(path)) is None


def test_an_invalid_manifest_is_unreadable(repo: Path, data_root: Path) -> None:
    path = repo / "deploy" / "families" / f"{FAMILY}.json"
    path.write_bytes(b"{not json")
    assert _facts(repo, data_root, FAMILY, _manifest_sha(path)) is None


def test_a_manifest_naming_another_family_is_unreadable(repo: Path, data_root: Path) -> None:
    families = repo / "deploy" / "families"
    (families / "pm_us_crh_cont.json").write_bytes((families / f"{FAMILY}.json").read_bytes())
    sha = _manifest_sha(families / "pm_us_crh_cont.json")
    assert _facts(repo, data_root, "pm_us_crh_cont", sha) is None


def test_a_symlinked_manifest_is_unreadable(repo: Path, data_root: Path, tmp_path: Path) -> None:
    families = repo / "deploy" / "families"
    real = tmp_path / "real.json"
    shutil.copy(families / f"{FAMILY}.json", real)
    (families / f"{FAMILY}.json").unlink()
    (families / f"{FAMILY}.json").symlink_to(real)
    assert _facts(repo, data_root, FAMILY, _manifest_sha(real)) is None


def test_a_symlinked_families_directory_is_unreadable(
    repo: Path, data_root: Path, tmp_path: Path
) -> None:
    sha = _manifest_sha(repo / "deploy" / "families" / f"{FAMILY}.json")
    moved = tmp_path / "moved"
    (repo / "deploy" / "families").rename(moved)
    (repo / "deploy" / "families").symlink_to(moved)
    assert _facts(repo, data_root, FAMILY, sha) is None


def test_a_mechanism_test_directory_is_prereg_ineligible(repo: Path, data_root: Path) -> None:
    families = repo / "deploy" / "families"
    sha = _manifest_sha(families / f"{FAMILY}.json")
    (families / "mechanism_trials.csv").write_text("mechanism_test_only\ntrue\n", encoding="utf-8")
    assert _facts(repo, data_root, FAMILY, sha) is None


def _registry_copy(data_root: Path, family: str, raw: bytes) -> str:
    directory = data_root / "registry" / "families"
    directory.mkdir(parents=True, mode=0o700)
    target = directory / f"{family}.json"
    target.write_bytes(raw)
    target.chmod(0o444)
    return hashlib.sha256(raw).hexdigest()


def _child_manifest() -> bytes:
    source = MANIFEST_SRC.read_text(encoding="utf-8")
    return source.replace(FAMILY, f"{FAMILY}_r0001").encode("utf-8")


def test_a_child_is_read_from_the_registry_copy_when_the_repo_has_none(
    repo: Path, data_root: Path
) -> None:
    child = f"{FAMILY}_r0001"
    sha = _registry_copy(data_root, child, _child_manifest())
    facts = _facts(repo, data_root, child, sha)
    assert facts is not None and facts.family_id == child and facts.manifest_sha256 == sha


def test_a_registry_copy_with_the_wrong_sha_is_unreadable(repo: Path, data_root: Path) -> None:
    child = f"{FAMILY}_r0001"
    _registry_copy(data_root, child, _child_manifest())
    assert _facts(repo, data_root, child, "f" * 64) is None


def test_a_group_writable_registry_copy_is_unreadable(repo: Path, data_root: Path) -> None:
    child = f"{FAMILY}_r0001"
    sha = _registry_copy(data_root, child, _child_manifest())
    (data_root / "registry" / "families" / f"{child}.json").chmod(0o666)
    assert _facts(repo, data_root, child, sha) is None


def test_a_root_never_falls_back_to_a_registry_copy_after_a_repo_mismatch(
    repo: Path, data_root: Path
) -> None:
    path = repo / "deploy" / "families" / f"{FAMILY}.json"
    original = path.read_bytes()
    registry_sha = _registry_copy(data_root, FAMILY, original)
    path.write_bytes(original + b"\n")  # the committed root drifted from the row
    assert _facts(repo, data_root, FAMILY, registry_sha) is None


def test_the_reader_never_raises_on_an_unreadable_source(repo: Path, data_root: Path) -> None:
    path = repo / "deploy" / "families" / f"{FAMILY}.json"
    sha = _manifest_sha(path)  # the real sha: only the unreadable file stands in the way
    assert _facts(repo, data_root, FAMILY, sha) is not None  # control
    path.chmod(0)
    if os.geteuid() == 0:  # pragma: no cover - root reads anything
        pytest.skip("mode bits do not bind root")
    assert _facts(repo, data_root, FAMILY, sha) is None


# ------------------------------------------------------------------------ module hygiene


def test_family_bytes_passes_no_draft_flag_and_writes_only_through_single_read() -> None:
    source = Path(family_bytes.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    assert "allow_draft" not in source
    imported = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    assert "breezy.persistence.autonomy.single_read" in imported
    banned = {"os.mkdir", "os.chmod", "os.link", "os.replace", "os.rename", "os.unlink"}
    called = {
        f"{n.func.value.id}.{n.func.attr}"
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and isinstance(n.func.value, ast.Name)
    }
    assert called.isdisjoint(banned)


# ------------------------------------------------------------- A6d-A2 L2: no named temp file


def test_root_copy_never_shows_a_tmp_name(data_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    opened: list[str] = []
    real_open = os.open

    def spy(path: Any, flags: int, *args: Any, **kwargs: Any) -> int:
        opened.append(os.fsdecode(path))
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", spy)
    paths = AutonomyPaths(data_root)
    _copy(paths)
    _copy(paths)  # EXISTS_EQUAL rerun
    with pytest.raises(RootCopyIntegrity):
        _copy(paths, record=_record(manifest_sha="b" * 64))
    assert not [name for name in opened if os.path.basename(name).startswith(".tmp.")]
    sha_dir = paths.artefact_dir(root_model_class(KIND), ARTEFACT_SHA)
    for directory in (sha_dir, sha_dir / "roots"):
        assert not [p.name for p in directory.iterdir() if p.name.startswith(".tmp.")]
