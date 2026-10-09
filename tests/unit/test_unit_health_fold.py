"""The health pass's fold read (plan r15 section 3.3.2, F4): the subject and the failure causes."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from breezy.persistence.autonomy.fold import FoldResult, fold
from breezy.persistence.autonomy.paths import AutonomyPaths
from breezy.persistence.autonomy.registry_store import RegistryStore
from breezy.persistence.autonomy.schemas import TransitionRow, WriterMode
from breezy.runtime import unit_health_fold
from breezy.runtime.unit_health_fold import HOST_SUBJECT, VENUE, FoldSubject
from breezy.runtime.unit_health_types import FoldUnreadable
from tests.unit.test_registry_export import put_export
from tests.unit.test_registry_store import (  # noqa: F401  (an autouse fixture, shared)
    FAMILY,
    NOW,
    SEC,
    _manifests_pin_their_rows_artefact,
    bootstrap,
    demote,
)


@pytest.fixture
def paths(tmp_path: Path) -> AutonomyPaths:
    root = tmp_path / "data"
    root.mkdir(mode=0o700)
    return AutonomyPaths(root)


@pytest.fixture
def export_dir(paths: AutonomyPaths) -> Path:
    directory = paths.export_dir()
    directory.mkdir(parents=True, mode=0o700)
    for parent in (directory.parent, directory):
        parent.chmod(0o700)
    return directory


@pytest.fixture
def stored_rows(paths: AutonomyPaths, tmp_path: Path) -> tuple[TransitionRow, ...]:
    """Two sealed rows: BOOTSTRAP (CHAMPION) then DEMOTE (HALTED)."""
    store = RegistryStore.initialise(paths, repo_root=tmp_path / "repo")
    first = store.append([bootstrap()], expected_prior_seq=0, mode=WriterMode.BOOTSTRAP, now_ns=NOW)
    second = store.append([demote()], expected_prior_seq=1, mode=WriterMode.DAILY, now_ns=NOW + SEC)
    return (*first.rows, *second.rows)


def test_the_health_venue_is_the_live_venue() -> None:
    assert VENUE == "polymarket_us"


def test_subject_is_the_sole_sender_of_the_newest_export(
    paths: AutonomyPaths, export_dir: Path, stored_rows: Any
) -> None:
    put_export(paths, stored_rows, 1)
    reader = FoldSubject(paths, now_ns=lambda: NOW + 5 * SEC)
    reader.probe()
    view = fold(stored_rows, VENUE, NOW + 5 * SEC)  # BOOTSTRAP then DEMOTE: HALTED
    assert isinstance(view, FoldResult) and view.senders == (FAMILY,)
    assert reader.subject() == FAMILY


def test_a_fold_with_no_sender_is_the_host_subject(
    paths: AutonomyPaths, export_dir: Path, stored_rows: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    put_export(paths, stored_rows, 1)
    monkeypatch.setattr(unit_health_fold, "fold", lambda *a, **k: SimpleNamespace(senders=()))
    reader = FoldSubject(paths, now_ns=lambda: NOW)
    reader.probe()
    assert reader.subject() == HOST_SUBJECT == "_host"


def test_two_senders_are_never_picked_between(
    paths: AutonomyPaths, export_dir: Path, stored_rows: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    put_export(paths, stored_rows, 1)
    two = SimpleNamespace(senders=("a_family", "b_family"))
    monkeypatch.setattr(unit_health_fold, "fold", lambda *a, **k: two)
    reader = FoldSubject(paths, now_ns=lambda: NOW)
    reader.probe()
    assert reader.subject() == HOST_SUBJECT


def test_subject_before_any_probe_is_the_host_subject(paths: AutonomyPaths) -> None:
    assert FoldSubject(paths).subject() == HOST_SUBJECT


def test_no_export_is_the_empty_fold(paths: AutonomyPaths, export_dir: Path) -> None:
    with pytest.raises(FoldUnreadable) as caught:
        FoldSubject(paths).probe()
    assert caught.value.reason == "empty"


def test_a_missing_export_directory_is_unreadable(paths: AutonomyPaths) -> None:
    with pytest.raises(FoldUnreadable) as caught:
        FoldSubject(paths).probe()
    assert caught.value.reason == "unreadable"


def test_a_corrupt_export_is_unreadable(paths: AutonomyPaths, export_dir: Path) -> None:
    (export_dir / f"registry_{VENUE}_2026-12-01.jsonl").write_bytes(b"{not json}\n")
    with pytest.raises(FoldUnreadable) as caught:
        FoldSubject(paths).probe()
    assert caught.value.reason == "unreadable"


def test_a_broken_chain_is_unreadable(
    paths: AutonomyPaths,
    export_dir: Path,
    stored_rows: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    put_export(paths, stored_rows, 1)
    from breezy.persistence.autonomy.chain import ChainBroken

    def broken(*_a: object, **_k: object) -> None:
        raise ChainBroken(0, "planted")

    monkeypatch.setattr(unit_health_fold, "verify_venue_chain", broken)
    with pytest.raises(FoldUnreadable) as caught:
        FoldSubject(paths).probe()
    assert caught.value.reason == "unreadable"


def test_an_invalid_fold_is_unreadable(
    paths: AutonomyPaths, export_dir: Path, stored_rows: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from breezy.persistence.autonomy.fold import FoldInvalid
    from breezy.persistence.autonomy.schemas import RefusalReason

    put_export(paths, stored_rows, 1)
    monkeypatch.setattr(
        unit_health_fold,
        "fold",
        lambda *a, **k: FoldInvalid(next(iter(RefusalReason))),  # type: ignore[arg-type]
    )
    with pytest.raises(FoldUnreadable) as caught:
        FoldSubject(paths, now_ns=lambda: NOW).probe()
    assert caught.value.reason == "unreadable"


def test_a_failed_probe_forgets_the_previous_subject(
    paths: AutonomyPaths, export_dir: Path, stored_rows: Any
) -> None:
    put_export(paths, stored_rows, 1)
    reader = FoldSubject(paths, now_ns=lambda: NOW + SEC)
    reader.probe()
    assert reader.subject() == FAMILY
    for entry in export_dir.iterdir():
        entry.unlink()
    with pytest.raises(FoldUnreadable):
        reader.probe()
    assert reader.subject() == HOST_SUBJECT
