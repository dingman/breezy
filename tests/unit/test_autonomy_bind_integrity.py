"""ARCH-0 seam B (WP-B2b-1): nofollow bind walks and ``open_validated_binds``.

Plan r5 AC-1.2. The walks run against a real temporary directory tree; no test
needs bwrap. Alias, escape and "never create a bind source" cases are the point.
"""

from __future__ import annotations

import dataclasses
import os
import socket
import stat
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from breezy.runtime.autonomy_sandbox import binds as binds_module
from breezy.runtime.autonomy_sandbox.binds import (
    BindIntegrityError,
    forbidden_dirs,
    open_validated_binds,
    walk_nofollow,
)
from breezy.runtime.autonomy_sandbox.table import (
    AUTONOMY_BWRAP_TABLE,
    BwrapRow,
    SandboxRoots,
)

FIXTURE_LABEL = frozenset({"E7_FIXTURE_ROOT"})


def _roots(tmp_path: Path, **changes: Any) -> SandboxRoots:
    home = tmp_path / "home"
    roots = SandboxRoots(
        home=home,
        data_root=home / ".local" / "share" / "breezy",
        repo_root=home / "repo",
        python_prefix=home / "py",
        uid=os.getuid(),
        run_user=tmp_path / "run" / "user",
    )
    return dataclasses.replace(roots, **changes)


@pytest.fixture
def roots(tmp_path: Path) -> SandboxRoots:
    for rel in ("state/inner", "registry", "cache/a", "cache/b", "cache/a2"):
        (_roots(tmp_path).data_root / rel).mkdir(parents=True)
    return _roots(tmp_path)


def _row(*binds: str, **changes: Any) -> BwrapRow:
    return dataclasses.replace(
        AUTONOMY_BWRAP_TABLE["breezy-autonomy-selftest-notify"], binds=tuple(binds), **changes
    )


def _ident(path: Path) -> tuple[int, int]:
    st = os.stat(path)
    return (st.st_dev, st.st_ino)


def _open_fds() -> set[str]:
    return set(os.listdir("/proc/self/fd"))


def _refused(roots: SandboxRoots, row: BwrapRow, code: str) -> None:
    with pytest.raises(BindIntegrityError) as caught, open_validated_binds(row, roots):
        pass
    assert caught.value.code == code
    assert caught.value.exit_status == 78
    assert str(caught.value) == code


# ---------------------------------------------------------------- walk_nofollow


def test_walk_dir_returns_fd_identity_and_every_ancestor(tmp_path: Path) -> None:
    target = tmp_path / "a" / "b"
    target.mkdir(parents=True)
    walked = walk_nofollow(target, kind="dir")
    try:
        st = os.fstat(walked.fd)
        assert stat.S_ISDIR(st.st_mode)
        assert (st.st_dev, st.st_ino) == _ident(target) == walked.ident
        assert walked.chain[-1] == walked.ident
        assert walked.chain[0] == _ident(Path("/"))
        assert _ident(tmp_path / "a") in walked.chain
        assert len(walked.chain) == len(target.parts)
    finally:
        os.close(walked.fd)


def test_walk_file_and_socket_kinds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "f").write_text("x")
    walked = walk_nofollow(tmp_path / "f", kind="file")
    os.close(walked.fd)
    monkeypatch.chdir(tmp_path)
    with socket.socket(socket.AF_UNIX) as sock:
        sock.bind("sock")
        sockwalk = walk_nofollow(tmp_path / "sock", kind="socket")
        os.close(sockwalk.fd)
        for kind in ("file", "dir"):
            with pytest.raises(BindIntegrityError):
                walk_nofollow(tmp_path / "sock", kind=kind)
    with pytest.raises(BindIntegrityError, match="not_file"):
        walk_nofollow(tmp_path, kind="file")
    with pytest.raises(BindIntegrityError, match="not_dir"):
        walk_nofollow(tmp_path / "f", kind="dir")


def test_walk_refuses_symlinked_final_and_intermediate_components(tmp_path: Path) -> None:
    (tmp_path / "real" / "leaf").mkdir(parents=True)
    (tmp_path / "real" / "f").write_text("x")
    (tmp_path / "link").symlink_to(tmp_path / "real")
    (tmp_path / "real" / "leaflink").symlink_to(tmp_path / "real" / "leaf")
    (tmp_path / "real" / "flink").symlink_to(tmp_path / "real" / "f")
    for path, kind in (
        (tmp_path / "link", "dir"),
        (tmp_path / "link" / "leaf", "dir"),
        (tmp_path / "real" / "leaflink", "dir"),
        (tmp_path / "link" / "f", "file"),
        (tmp_path / "real" / "flink", "file"),
    ):
        with pytest.raises(BindIntegrityError):
            walk_nofollow(path, kind=kind)  # type: ignore[arg-type]


def test_walk_missing_path_is_refused_and_never_created(tmp_path: Path) -> None:
    with pytest.raises(BindIntegrityError, match="missing"):
        walk_nofollow(tmp_path / "nope" / "deeper", kind="dir")
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("bad", ["relative/path", "/a/../b", "/a/./b", "/a//b", ""])
def test_walk_refuses_non_normalised_or_relative_paths(bad: str) -> None:
    with pytest.raises(BindIntegrityError, match="bad_path"):
        walk_nofollow(bad, kind="dir")


def test_walk_error_text_carries_no_path(tmp_path: Path) -> None:
    secret = tmp_path / "very-secret-dir-name"
    with pytest.raises(BindIntegrityError) as caught:
        walk_nofollow(secret, kind="dir")
    assert "secret" not in str(caught.value)
    assert str(tmp_path) not in repr(caught.value)


def test_walk_closes_every_intermediate_fd(tmp_path: Path) -> None:
    (tmp_path / "a" / "b").mkdir(parents=True)
    before = _open_fds()
    os.close(walk_nofollow(tmp_path / "a" / "b", kind="dir").fd)
    with pytest.raises(BindIntegrityError):
        walk_nofollow(tmp_path / "a" / "missing", kind="dir")
    assert _open_fds() == before


# --------------------------------------------------------------- forbidden_dirs


def test_forbidden_dirs_are_state_data_root_and_their_ancestors(roots: SandboxRoots) -> None:
    forbidden = forbidden_dirs(roots)
    assert _ident(roots.data_root / "state") in forbidden
    assert _ident(roots.data_root) in forbidden
    assert _ident(roots.data_root.parent) in forbidden
    assert _ident(roots.home) in forbidden
    assert _ident(Path("/")) in forbidden
    assert _ident(roots.data_root / "cache") not in forbidden
    assert _ident(roots.data_root / "cache" / "a") not in forbidden
    assert _ident(roots.data_root / "state" / "inner") not in forbidden


def test_forbidden_dirs_tolerates_an_absent_state_dir(tmp_path: Path) -> None:
    roots = _roots(tmp_path)
    roots.data_root.mkdir(parents=True)
    forbidden = forbidden_dirs(roots)
    assert _ident(roots.data_root) in forbidden
    assert not (roots.data_root / "state").exists()


def test_forbidden_dirs_refuses_a_symlinked_state_dir(roots: SandboxRoots) -> None:
    os.rename(roots.data_root / "state", roots.data_root / "state.real")
    (roots.data_root / "state").symlink_to(roots.data_root / "state.real")
    with pytest.raises(BindIntegrityError):
        forbidden_dirs(roots)


def test_forbidden_dirs_closes_its_fds(roots: SandboxRoots) -> None:
    before = _open_fds()
    forbidden_dirs(roots)
    assert _open_fds() == before


# -------------------------------------------------------- open_validated_binds


def test_binds_open_as_directory_fds_with_exact_destinations(roots: SandboxRoots) -> None:
    row = _row("cache/a", "cache/b")
    with open_validated_binds(row, roots) as opened:
        assert [bind.rel for bind in opened.binds] == ["cache/a", "cache/b"]
        for bind in opened.binds:
            st = os.fstat(bind.fd)
            assert stat.S_ISDIR(st.st_mode)
            assert (st.st_dev, st.st_ino) == (bind.dev, bind.ino)
            assert bind.path == str(roots.data_root / bind.rel)
            assert (bind.dev, bind.ino) == _ident(Path(bind.path))
        assert opened.config_files == () and opened.config_dirs == ()
        fds = [bind.fd for bind in opened.binds]
    for fd in fds:
        with pytest.raises(OSError):
            os.fstat(fd)


def test_fds_are_closed_when_the_body_raises(roots: SandboxRoots) -> None:
    before = _open_fds()
    with pytest.raises(RuntimeError), open_validated_binds(_row("cache/a"), roots):
        raise RuntimeError("boom")
    assert _open_fds() == before


def test_row_without_binds_opens_nothing(roots: SandboxRoots) -> None:
    with open_validated_binds(_row(), roots) as opened:
        assert opened.binds == ()


def test_missing_bind_source_is_refused_and_never_created(roots: SandboxRoots) -> None:
    before = sorted(p.name for p in (roots.data_root / "cache").iterdir())
    _refused(roots, _row("cache/never-made"), "missing")
    assert sorted(p.name for p in (roots.data_root / "cache").iterdir()) == before
    assert not (roots.data_root / "cache" / "never-made").exists()


def test_missing_intermediate_directory_is_not_created(roots: SandboxRoots) -> None:
    _refused(roots, _row("nodir/child"), "missing")
    assert not (roots.data_root / "nodir").exists()


def test_symlinked_bind_component_is_refused(roots: SandboxRoots) -> None:
    (roots.data_root / "cache" / "ln").symlink_to(roots.data_root / "cache" / "a")
    _refused(roots, _row("cache/ln"), "not_dir")
    (roots.data_root / "lncache").symlink_to(roots.data_root / "cache")
    _refused(roots, _row("lncache/a"), "not_dir")


def test_symlink_to_state_is_refused_not_followed(roots: SandboxRoots) -> None:
    (roots.data_root / "cache" / "sneaky").symlink_to(roots.data_root / "state")
    _refused(roots, _row("cache/sneaky"), "not_dir")


def test_bind_that_is_a_file_is_refused(roots: SandboxRoots) -> None:
    (roots.data_root / "cache" / "afile").write_text("x")
    _refused(roots, _row("cache/afile"), "not_dir")


def test_bind_aliasing_a_forbidden_directory_is_refused(
    roots: SandboxRoots, monkeypatch: pytest.MonkeyPatch
) -> None:
    alias = frozenset({_ident(roots.data_root / "cache" / "a")})
    monkeypatch.setattr(binds_module, "forbidden_dirs", lambda _roots: alias)
    _refused(roots, _row("cache/a"), "forbidden")


def test_bind_under_a_forbidden_directory_is_refused(
    roots: SandboxRoots, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent = frozenset({_ident(roots.data_root / "state")})
    monkeypatch.setattr(binds_module, "forbidden_dirs", lambda _roots: parent)
    _refused(roots, _row("state/inner"), "forbidden")


def test_bind_on_a_different_device_than_the_base_is_refused(tmp_path: Path) -> None:
    # /dev is devtmpfs and /dev/shm is a separate tmpfs mount, on every Linux host.
    if os.stat("/dev").st_dev == os.stat("/dev/shm").st_dev:  # pragma: no cover
        pytest.skip("host has no separate /dev/shm mount")
    roots = _roots(tmp_path, data_root=Path("/dev"))
    _refused(roots, _row("shm"), "wrong_device")


@pytest.mark.parametrize("pair", [("cache/a", "cache/a2"), ("cache/a", "cache/b")])
def test_sibling_binds_are_accepted(roots: SandboxRoots, pair: tuple[str, str]) -> None:
    with open_validated_binds(_row(*pair), roots) as opened:
        assert len(opened.binds) == 2


def test_nested_binds_are_refused_in_either_order(roots: SandboxRoots) -> None:
    (roots.data_root / "cache" / "a" / "deep").mkdir()
    _refused(roots, _row("cache/a", "cache/a/deep"), "nested")
    _refused(roots, _row("cache/a/deep", "cache/a"), "nested")


def test_duplicate_bind_is_refused(roots: SandboxRoots) -> None:
    _refused(roots, _row("cache/a", "cache/a"), "nested")


def test_a_refusal_closes_the_binds_opened_before_it(roots: SandboxRoots) -> None:
    before = _open_fds()
    _refused(roots, _row("cache/a", "cache/never-made"), "missing")
    assert _open_fds() == before


def test_fixture_root_row_resolves_against_the_alternate_base(
    roots: SandboxRoots,
) -> None:
    fixture = roots.home / ".local" / "share" / "breezy-autonomy-fixture"
    (fixture / "cache" / "only-here").mkdir(parents=True)
    row = _row("cache/only-here", bind_base="aut4_fixture", exceptions=FIXTURE_LABEL)
    with open_validated_binds(row, roots) as opened:
        assert opened.binds[0].path == str(fixture / "cache" / "only-here")
    # the same rel does not exist under the data root, so the default base refuses it
    _refused(roots, _row("cache/only-here"), "missing")


def test_unknown_bind_base_is_refused(roots: SandboxRoots) -> None:
    _refused(roots, _row("cache/a", bind_base="nope"), "bad_base")


# ------------------------------------------------------------------ config binds


@pytest.fixture
def config_files(roots: SandboxRoots) -> Iterator[Path]:
    conf = roots.home / ".config" / "breezy-x"
    (conf / "dir").mkdir(parents=True)
    (conf / "one.toml").write_text("x")
    (conf / "one.toml").chmod(0o640)
    (conf / "dir").chmod(0o755)
    yield conf


def test_config_files_and_dirs_open_read_only_relative_to_home(
    roots: SandboxRoots, config_files: Path
) -> None:
    row = _row(
        "cache/a",
        config_ro_binds=(".config/breezy-x/one.toml",),
        config_ro_dirs=(".config/breezy-x/dir",),
    )
    with open_validated_binds(row, roots) as opened:
        (file_bind,) = opened.config_files
        (dir_bind,) = opened.config_dirs
        assert stat.S_ISREG(os.fstat(file_bind.fd).st_mode)
        assert stat.S_ISDIR(os.fstat(dir_bind.fd).st_mode)
        assert file_bind.path == str(config_files / "one.toml")
        assert dir_bind.path == str(config_files / "dir")
        fds = [file_bind.fd, dir_bind.fd]
    for fd in fds:
        with pytest.raises(OSError):
            os.fstat(fd)


def test_config_symlink_wrong_kind_missing_and_absolute_are_refused(
    roots: SandboxRoots, config_files: Path
) -> None:
    (config_files / "ln.toml").symlink_to(config_files / "one.toml")
    _refused(roots, _row(config_ro_binds=(".config/breezy-x/ln.toml",)), "not_file")
    _refused(roots, _row(config_ro_binds=(".config/breezy-x/dir",)), "not_file")
    _refused(roots, _row(config_ro_dirs=(".config/breezy-x/one.toml",)), "not_dir")
    _refused(roots, _row(config_ro_binds=(".config/breezy-x/absent.toml",)), "missing")
    _refused(roots, _row(config_ro_binds=("/etc/passwd",)), "bad_path")
    _refused(roots, _row(config_ro_binds=("../escape",)), "bad_path")


def test_config_owned_by_someone_else_or_group_writable_is_refused(
    roots: SandboxRoots, config_files: Path
) -> None:
    row = _row(config_ro_binds=(".config/breezy-x/one.toml",))
    _refused(dataclasses.replace(roots, uid=os.getuid() + 1), row, "owner")
    (config_files / "one.toml").chmod(0o660)
    _refused(roots, row, "writable")
    (config_files / "one.toml").chmod(0o602)
    _refused(roots, row, "writable")


def test_config_cannot_alias_state(roots: SandboxRoots) -> None:
    _refused(roots, _row(config_ro_dirs=(".local/share/breezy/state",)), "forbidden")
