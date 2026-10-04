"""ARCH-0 seam B defect B11 (ruling B11-R1): the venv interpreter's symlink hops in the sandbox.

``interpreter_symlinks`` walks ``<repo_root>/.venv/bin/python3`` and the ``pyvenv.cfg``
``home`` directory one component at a time and names each symlink that lies under the home
tmpfs and outside the already-bound roots, so the wrapper can recreate it with
``--symlink`` (not a bind). Every test builds a synthetic tree under ``tmp_path``.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from breezy.runtime.autonomy_sandbox.binds import OpenedBinds
from breezy.runtime.autonomy_sandbox.bwrap import WrapperError, build_bwrap_argv
from breezy.runtime.autonomy_sandbox.interp_links import (
    MAX_HOPS,
    InterpreterLinkError,
    interpreter_symlinks,
)
from breezy.runtime.autonomy_sandbox.table import AUTONOMY_BWRAP_TABLE, SandboxRoots

SELFTEST = AUTONOMY_BWRAP_TABLE["breezy-autonomy-selftest"]


class Tree:
    """A fake home holding a repo with a venv, a real python prefix and a link location."""

    def __init__(self, tmp_path: Path) -> None:
        self.home = tmp_path / "home"
        self.repo = self.home / "repo"
        self.uv = self.home / ".local" / "share" / "uv" / "python"
        self.prefix = self.uv / "cpython-3.13.13-linux"
        (self.prefix / "bin").mkdir(parents=True)
        (self.prefix / "bin" / "python3.13").write_text("")
        (self.repo / ".venv" / "bin").mkdir(parents=True)
        (self.home / ".local" / "share" / "breezy").mkdir(parents=True)

    @property
    def roots(self) -> SandboxRoots:
        return SandboxRoots(
            home=self.home,
            data_root=self.home / ".local" / "share" / "breezy",
            repo_root=self.repo,
            python_prefix=self.prefix.resolve(),
            uid=os.getuid(),
            run_user=Path("/run/user/1000"),
        )

    def venv(self, via: Path) -> None:
        """``.venv/bin/python3 -> python -> <via>/bin/python3.13`` and ``home = <via>/bin``."""
        bin_dir = self.repo / ".venv" / "bin"
        (bin_dir / "python").symlink_to(via / "bin" / "python3.13")
        (bin_dir / "python3").symlink_to("python")
        (self.repo / ".venv" / "pyvenv.cfg").write_text(f"home = {via / 'bin'}\nversion = 3.13\n")


@pytest.fixture
def tree(tmp_path: Path) -> Tree:
    return Tree(tmp_path.resolve())


def test_absolute_symlink_outside_binds_is_emitted_with_exact_target(tree: Tree) -> None:
    link = tree.uv / "cpython-3.13-linux"
    link.symlink_to(tree.prefix)
    tree.venv(link)
    assert interpreter_symlinks(tree.roots) == ((str(link), str(tree.prefix)),)


def test_relative_symlink_keeps_the_host_readlink_text(tree: Tree) -> None:
    link = tree.uv / "cpython-3.13-linux"
    link.symlink_to("cpython-3.13.13-linux")
    tree.venv(link)
    assert interpreter_symlinks(tree.roots) == ((str(link), "cpython-3.13.13-linux"),)


def test_two_hop_chain_emits_both_hops(tree: Tree) -> None:
    inner = tree.uv / "cpython-3.13-linux"
    inner.symlink_to("cpython-3.13.13-linux")
    outer = tree.uv / "default"
    outer.symlink_to(inner)
    tree.venv(outer)
    assert dict(interpreter_symlinks(tree.roots)) == {
        str(outer): str(inner),
        str(inner): "cpython-3.13.13-linux",
    }


def test_symlink_inside_the_repo_bind_is_not_emitted(tree: Tree) -> None:
    tree.venv(tree.prefix)
    assert interpreter_symlinks(tree.roots) == ()


def test_no_symlinks_yields_no_hops(tree: Tree) -> None:
    (tree.repo / ".venv" / "bin" / "python3").write_text("")
    (tree.repo / ".venv" / "pyvenv.cfg").write_text(f"home = {tree.prefix / 'bin'}\n")
    assert interpreter_symlinks(tree.roots) == ()


def test_missing_venv_yields_no_hops(tree: Tree) -> None:
    (tree.repo / ".venv" / "bin").rmdir()
    (tree.repo / ".venv").rmdir()
    assert interpreter_symlinks(tree.roots) == ()


def test_target_outside_the_prefix_is_refused(tree: Tree) -> None:
    elsewhere = tree.home / "elsewhere"
    (elsewhere / "bin").mkdir(parents=True)
    (elsewhere / "bin" / "python3.13").write_text("")
    link = tree.uv / "cpython-3.13-linux"
    link.symlink_to(elsewhere)
    tree.venv(link)
    with pytest.raises(InterpreterLinkError):
        interpreter_symlinks(tree.roots)


def test_symlink_loop_is_refused(tree: Tree) -> None:
    first, second = tree.uv / "loop-a", tree.uv / "loop-b"
    first.symlink_to(second)
    second.symlink_to(first)
    (tree.repo / ".venv" / "bin" / "python3").symlink_to(first / "bin" / "python3.13")
    with pytest.raises(InterpreterLinkError):
        interpreter_symlinks(tree.roots)


def test_chain_longer_than_the_hop_limit_is_refused(tree: Tree) -> None:
    previous = tree.prefix
    for index in range(MAX_HOPS + 1):
        hop = tree.uv / f"hop{index}"
        hop.symlink_to(previous)
        previous = hop
    tree.venv(previous)
    with pytest.raises(InterpreterLinkError):
        interpreter_symlinks(tree.roots)


def _argv(roots: SandboxRoots) -> list[str]:
    return build_bwrap_argv(
        SELFTEST,
        ("/usr/bin/true",),
        roots=roots,
        opened=OpenedBinds(binds=(), config_files=(), config_dirs=()),
        rebinds=(),
        environ={},
        cwd="/",
    )


def test_argv_recreates_each_hop_with_symlink_and_adds_no_bind(tree: Tree) -> None:
    link = tree.uv / "cpython-3.13-linux"
    link.symlink_to(tree.prefix)
    tree.venv(link)
    with_link = _argv(tree.roots)
    index = with_link.index("--symlink")
    assert with_link[index : index + 3] == ["--symlink", str(tree.prefix), str(link)]
    assert with_link.count("--symlink") == 1
    home_tmpfs = next(
        i for i, tok in enumerate(with_link) if with_link[i : i + 2] == ["--tmpfs", str(tree.home)]
    )
    prefix_bind = with_link.index("--ro-bind", with_link.index(str(tree.prefix)) - 1)
    assert home_tmpfs < prefix_bind < index
    binds = [with_link[i + 2] for i, tok in enumerate(with_link) if tok in ("--bind", "--ro-bind")]
    assert str(link) not in binds


def test_argv_without_symlinks_has_no_symlink_flag(tree: Tree) -> None:
    tree.venv(tree.prefix)
    assert "--symlink" not in _argv(tree.roots)


def test_argv_refuses_when_a_hop_leaves_the_prefix(tree: Tree) -> None:
    elsewhere = tree.home / "elsewhere"
    (elsewhere / "bin").mkdir(parents=True)
    (elsewhere / "bin" / "python3.13").write_text("")
    link = tree.uv / "cpython-3.13-linux"
    link.symlink_to(elsewhere)
    tree.venv(link)
    with pytest.raises(WrapperError) as caught:
        _argv(tree.roots)
    assert caught.value.code == "interpreter_link"


# ------------------------------------------------------------------ B12 (R1..R6)


def _cfg(tree: Tree, text: str) -> None:
    (tree.repo / ".venv" / "bin" / "python3").write_text("")
    (tree.repo / ".venv" / "pyvenv.cfg").write_text(text)


def test_chain_of_exactly_the_hop_limit_is_accepted(tree: Tree) -> None:
    previous = tree.prefix
    for index in range(MAX_HOPS):
        hop = tree.uv / f"hop{index}"
        hop.symlink_to(previous)
        previous = hop
    _cfg(tree, f"home = {previous / 'bin'}\n")
    assert len(interpreter_symlinks(tree.roots)) == MAX_HOPS


def test_hop_outside_the_home_is_not_emitted(tree: Tree) -> None:
    outside = tree.home.parent / "outside-link"
    outside.symlink_to(tree.prefix)
    _cfg(tree, f"home = {outside / 'bin'}\n")
    assert interpreter_symlinks(tree.roots) == ()


def test_hop_under_the_data_root_is_not_emitted(tree: Tree) -> None:
    link = tree.roots.data_root / "py"
    link.symlink_to(tree.prefix)
    _cfg(tree, f"home = {link / 'bin'}\n")
    assert interpreter_symlinks(tree.roots) == ()


def test_hop_under_the_prefix_is_not_emitted(tree: Tree) -> None:
    (tree.prefix / "bin2").symlink_to("bin")
    _cfg(tree, f"home = {tree.prefix / 'bin2'}\n")
    assert interpreter_symlinks(tree.roots) == ()


def test_dotdot_in_a_link_target_keeps_the_exact_text(tree: Tree) -> None:
    link = tree.uv / "cpython-3.13-linux"
    link.symlink_to("../python/cpython-3.13.13-linux")
    _cfg(tree, f"home = {link / 'bin'}\n")
    assert interpreter_symlinks(tree.roots) == ((str(link), "../python/cpython-3.13.13-linux"),)


def test_dotdot_in_the_pyvenv_home_is_resolved(tree: Tree) -> None:
    link = tree.uv / "cpython-3.13-linux"
    link.symlink_to(tree.prefix)
    _cfg(tree, f"home = {tree.uv}/../python/cpython-3.13-linux/bin\n")
    assert interpreter_symlinks(tree.roots) == ((str(link), str(tree.prefix)),)


@pytest.mark.parametrize(
    "text", ["home = bin\n", "garbage\n", "", "home =\n", "home = /ok\nhome = rel\n"]
)
def test_pyvenv_cfg_without_an_absolute_home_is_refused(tree: Tree, text: str) -> None:
    _cfg(tree, text)
    with pytest.raises(InterpreterLinkError):
        interpreter_symlinks(tree.roots)


def test_pyvenv_cfg_follows_cpython_case_and_last_home_wins(tree: Tree) -> None:
    link = tree.uv / "cpython-3.13-linux"
    link.symlink_to(tree.prefix)
    _cfg(tree, f"home = relative\n  HOME  =  {link / 'bin'}  \n")
    assert interpreter_symlinks(tree.roots) == ((str(link), str(tree.prefix)),)


def test_a_start_path_that_vanished_with_the_venv_present_is_refused(tree: Tree) -> None:
    (tree.repo / ".venv" / "pyvenv.cfg").write_text(f"home = {tree.prefix / 'bin'}\n")
    with pytest.raises(InterpreterLinkError):
        interpreter_symlinks(tree.roots)


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory modes")
def test_an_unreadable_directory_is_refused_not_treated_as_a_plain_path(tree: Tree) -> None:
    locked = tree.uv / "locked"
    locked.mkdir()
    locked.chmod(0o000)
    try:
        _cfg(tree, f"home = {locked / 'x'}\n")
        with pytest.raises(InterpreterLinkError):
            interpreter_symlinks(tree.roots)
    finally:
        locked.chmod(0o700)


def test_a_hop_equal_to_the_home_is_refused(tree: Tree) -> None:
    linked_home = tree.home.parent / "linked-home"
    linked_home.symlink_to(tree.home)
    roots = SandboxRoots(
        home=linked_home,
        data_root=linked_home / ".local" / "share" / "breezy",
        repo_root=linked_home / "repo",
        python_prefix=tree.prefix,
        uid=os.getuid(),
        run_user=Path("/run/user/1000"),
    )
    with pytest.raises(InterpreterLinkError):
        interpreter_symlinks(roots)


def test_a_symlinked_home_does_not_drop_hops_reached_by_the_real_path(tree: Tree) -> None:
    link = tree.uv / "cpython-3.13-linux"
    link.symlink_to(tree.prefix)
    tree.venv(link)
    linked_home = tree.home.parent / "linked-home"
    linked_home.symlink_to(tree.home)
    roots = SandboxRoots(
        home=linked_home,
        data_root=tree.roots.data_root,
        repo_root=tree.repo,
        python_prefix=tree.prefix,
        uid=os.getuid(),
        run_user=Path("/run/user/1000"),
    )
    assert interpreter_symlinks(roots) == ((str(link), str(tree.prefix)),)


def test_a_symlinked_ancestor_of_a_bound_root_is_refused(tree: Tree) -> None:
    real = tree.home / "real_local"
    (tree.home / ".local").rename(real)
    (tree.home / ".local").symlink_to(real)
    tree.venv(tree.uv / ".." / "python" / "cpython-3.13.13-linux")
    with pytest.raises(InterpreterLinkError):
        interpreter_symlinks(tree.roots)


def test_a_link_outside_the_prefix_parent_is_refused(tree: Tree) -> None:
    other = tree.home / "other"
    other.mkdir()
    link = other / "py"
    link.symlink_to(tree.prefix)
    _cfg(tree, f"home = {link / 'bin'}\n")
    with pytest.raises(InterpreterLinkError):
        interpreter_symlinks(tree.roots)


def test_symlinks_precede_every_remount_ro(tree: Tree) -> None:
    (tree.uv / "cpython-3.13-linux").symlink_to(tree.prefix)
    tree.venv(tree.uv / "cpython-3.13-linux")
    argv = _argv(tree.roots)
    assert argv.index("--symlink") < argv.index("--remount-ro")


def test_a_hop_under_an_opened_bind_destination_is_not_emitted(tree: Tree) -> None:
    from breezy.runtime.autonomy_sandbox.binds import OpenedBind

    bind_dir = tree.home / "bound"
    bind_dir.mkdir()
    link = bind_dir / "py"
    link.symlink_to(tree.prefix)
    _cfg(tree, f"home = {link / 'bin'}\n")
    opened = OpenedBinds(
        binds=(OpenedBind("bound", str(bind_dir), 100, 1, 100),), config_files=(), config_dirs=()
    )
    from breezy.runtime.autonomy_sandbox.bwrap import interpreter_hops

    assert interpreter_hops(SELFTEST, tree.roots, opened) == ()


def _roots_with(tree: Tree, **changes: Path) -> SandboxRoots:
    fields = {
        "home": tree.home,
        "data_root": tree.roots.data_root,
        "repo_root": tree.repo,
        "python_prefix": tree.prefix,
        **changes,
    }
    return SandboxRoots(uid=os.getuid(), run_user=Path("/run/user/1000"), **fields)


def test_a_hop_equal_to_the_home_is_refused_on_that_rule_alone(tree: Tree) -> None:
    """The link is under the prefix's parent and resolves into the prefix: only R2 refuses it."""
    home_link = tree.uv / "home-link"
    home_link.symlink_to(tree.prefix)
    _cfg(tree, f"home = {home_link / 'bin'}\n")
    with pytest.raises(InterpreterLinkError, match="bound_ancestor"):
        interpreter_symlinks(_roots_with(tree, home=home_link))


def test_a_hop_that_is_an_ancestor_of_a_bound_root_is_refused_on_that_rule_alone(
    tree: Tree,
) -> None:
    ancestor = tree.uv / "ancestor-link"
    ancestor.symlink_to(tree.prefix)
    _cfg(tree, f"home = {ancestor / 'bin'}\n")
    with pytest.raises(InterpreterLinkError, match="bound_ancestor"):
        interpreter_symlinks(_roots_with(tree, data_root=ancestor / "data"))
