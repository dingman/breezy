"""ARCH-0 seam B (WP-B2b-2): the wrapper's argv, unit check, exits and fd hand-off.

Plan r5 AC-1.1 (cgroup unit check, exits 64/78), AC-1.3 (the exact argv order),
AC-1.4 (``--size`` first), AC-1.5 (exits 126/127; fallback only for
``NOTIFIER_FALLBACK_ROWS``). Argv tests are pure (synthetic fds); the ``main``
tests run against a real tmp tree with an injected ``execv``.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
import os
import stat
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pytest

from breezy.runtime.autonomy_sandbox import bwrap
from breezy.runtime.autonomy_sandbox.binds import OpenedBind, OpenedBinds
from breezy.runtime.autonomy_sandbox.bwrap import (
    BWRAP_PATH,
    UnitCheckError,
    build_bwrap_argv,
    current_unit_name,
    main,
)
from breezy.runtime.autonomy_sandbox.run_mounts import RunRebind
from breezy.runtime.autonomy_sandbox.self_probe import run_self_probe
from breezy.runtime.autonomy_sandbox.table import (
    AUTONOMY_BWRAP_TABLE,
    DEFAULT_TMPFS_SIZE_BYTES,
    NOTIFIER_FALLBACK_ROWS,
    BwrapRow,
    SandboxRoots,
)

SELFTEST = AUTONOMY_BWRAP_TABLE["breezy-autonomy-selftest"]
NOTIFY = AUTONOMY_BWRAP_TABLE["breezy-autonomy-selftest-notify"]
PROC = AUTONOMY_BWRAP_TABLE["breezy-autonomy-selftest-proc"]
ALL_ROWS = tuple(AUTONOMY_BWRAP_TABLE.values())
ARGV_SOURCE = Path(bwrap.__file__)
BWRAP_STUB = "/usr/bin/env"  # any existing executable: execv is injected, never run

PURE_ROOTS = SandboxRoots(
    home=Path("/home/u"),
    data_root=Path("/home/u/.local/share/breezy"),
    repo_root=Path("/home/u/repo"),
    python_prefix=Path("/home/u/py"),
    uid=1000,
    run_user=Path("/run/user/1000"),
)
FIXTURE_BASE = "/home/u/.local/share/breezy-autonomy-fixture"
RECONCILE = frozenset({"E7A_R2_RECONCILE"})


def _bind(rel: str, fd: int, base: str = "/home/u/.local/share/breezy") -> OpenedBind:
    return OpenedBind(rel, f"{base}/{rel}", fd, 1, fd)


def _opened(row: BwrapRow, first_fd: int = 100) -> OpenedBinds:
    base = FIXTURE_BASE if row.bind_base != "data_root" else "/home/u/.local/share/breezy"
    binds = tuple(_bind(rel, first_fd + i, base) for i, rel in enumerate(row.binds))
    files = tuple(
        OpenedBind(rel, f"/home/u/{rel}", 150 + i, 1, 1)
        for i, rel in enumerate(row.config_ro_binds)
    )
    dirs = tuple(
        OpenedBind(rel, f"/home/u/{rel}", 170 + i, 1, 1) for i, rel in enumerate(row.config_ro_dirs)
    )
    return OpenedBinds(binds=binds, config_files=files, config_dirs=dirs)


def _argv(
    row: BwrapRow = SELFTEST,
    command: Sequence[str] = ("/usr/bin/true",),
    *,
    roots: SandboxRoots = PURE_ROOTS,
    rebinds: tuple[RunRebind, ...] = (),
    environ: Mapping[str, str] | None = None,
    cwd: str = "/",
    opened: OpenedBinds | None = None,
) -> list[str]:
    return build_bwrap_argv(
        row,
        command,
        roots=roots,
        opened=opened if opened is not None else _opened(row),
        rebinds=rebinds,
        environ=environ or {},
        cwd=cwd,
    )


def _at(argv: Sequence[str], *tokens: str) -> int:
    """Index of the contiguous ``tokens`` run in ``argv`` (fails the test if absent)."""
    width = len(tokens)
    for index in range(len(argv) - width + 1):
        if tuple(argv[index : index + width]) == tokens:
            return index
    raise AssertionError(f"{tokens!r} not found in argv")


def _replace(row: BwrapRow, **changes: Any) -> BwrapRow:
    return dataclasses.replace(row, **changes)


# ------------------------------------------------------------------ argv shape


def test_argv_starts_with_bwrap_then_userns_flags_and_unshare_pid() -> None:
    argv = _argv()
    assert argv[0] == BWRAP_PATH == "/usr/bin/bwrap"
    assert argv[1:8] == [
        "--unshare-user",
        "--disable-userns",
        "--assert-userns-disabled",
        "--unshare-pid",
        "--unshare-ipc",
        "--unshare-uts",
        "--unshare-cgroup-try",
    ]
    assert argv[8:11] == ["--ro-bind", "/", "/"]


@pytest.mark.parametrize("row", ALL_ROWS, ids=lambda row: row.name)
def test_argv_every_row_unshares_pid(row: BwrapRow) -> None:
    assert "--unshare-pid" in _argv(row)


def test_extra_namespace_flags_exact_set() -> None:
    namespace_flags = {
        token
        for row in ALL_ROWS
        for token in _argv(row)
        if token.startswith(("--unshare", "--share", "--disable-", "--assert-"))
    }
    assert namespace_flags == {
        "--unshare-user",
        "--disable-userns",
        "--assert-userns-disabled",
        "--unshare-pid",
        "--unshare-ipc",
        "--unshare-uts",
        "--unshare-cgroup-try",
        "--unshare-net",  # E-15: every network="none" row
    }


def test_argv_tmpfs_run_after_root_bind_and_before_dev() -> None:
    argv = _argv()
    assert (
        _at(argv, "--ro-bind", "/", "/") < _at(argv, "--tmpfs", "/run") < _at(argv, "--dev", "/dev")
    )


def test_argv_dev_then_proc_on_non_proc_rows() -> None:
    argv = _argv(SELFTEST)
    assert _at(argv, "--dev", "/dev") + 2 == _at(argv, "--proc", "/proc")


def test_argv_proc_rows_omit_proc_mount_keep_unshare_pid() -> None:
    argv = _argv(PROC)
    assert "--proc" not in argv
    assert "--unshare-pid" in argv
    assert "--dev" in argv


def test_argv_size_immediately_before_tmpfs_tmp() -> None:
    argv = _argv(_replace(SELFTEST, tmpfs_size_bytes=4096))
    assert _at(argv, "--size", "4096", "--tmpfs", "/tmp") >= 0
    assert _at(argv, "--tmpfs", "/tmp") > _at(argv, "--dev", "/dev")


def test_argv_default_tmpfs_size_when_row_sets_none() -> None:
    assert SELFTEST.tmpfs_size_bytes is None
    argv = _argv(SELFTEST)
    assert _at(argv, "--size", str(DEFAULT_TMPFS_SIZE_BYTES), "--tmpfs", "/tmp") >= 0


def test_argv_home_tmpfs_then_rebinds_then_remount_ro() -> None:
    argv = _argv()
    home = _at(argv, "--tmpfs", "/home/u")
    repo = _at(argv, "--ro-bind", "/home/u/repo", "/home/u/repo")
    prefix = _at(argv, "--ro-bind", "/home/u/py", "/home/u/py")
    data = _at(argv, "--ro-bind", PURE_ROOTS.data_root.as_posix(), PURE_ROOTS.data_root.as_posix())
    assert _at(argv, "--tmpfs", "/tmp") < home < repo < prefix < data
    assert _at(argv, "--remount-ro", "/home/u") > _at(
        argv, "--bind-fd", "100", _opened(SELFTEST).binds[0].path
    )


def test_argv_run_tmpfs_precedes_home_tmpfs() -> None:
    argv = _argv()
    assert _at(argv, "--tmpfs", "/run") < _at(argv, "--tmpfs", "/home/u")


def test_argv_interpreter_prefix_outside_home_is_not_rebound() -> None:
    roots = dataclasses.replace(PURE_ROOTS, python_prefix=Path("/usr/local/py"))
    argv = _argv(roots=roots)
    assert "/usr/local/py" not in argv


def test_argv_fixture_row_rebinds_the_fixture_base() -> None:
    row = _replace(
        SELFTEST,
        bind_base="aut4_fixture",
        exceptions=frozenset({"E7_FIXTURE_ROOT"}),
        bus_reads=(),
        bus_snapshot_bind=None,
        bus_snapshot_budget_s=None,
    )
    argv = _argv(row)
    assert _at(argv, "--ro-bind", FIXTURE_BASE, FIXTURE_BASE) > _at(argv, "--tmpfs", "/home/u")
    assert _at(argv, "--bind-fd", "100", f"{FIXTURE_BASE}/cache/autonomy_selftest") >= 0


def test_argv_run_rebinds_exact_then_remount_ro_run() -> None:
    rebinds = (
        RunRebind("dns", dest="/run/systemd/resolve/stub-resolv.conf", fd=61),
        RunRebind(
            "notify", dest="/run/user/1000/systemd/notify", src="/run/user/1000/systemd/notify"
        ),
        RunRebind("studies_lock", dest="/run/user/1000/breezy-studies.lock", fd=62),
    )
    argv = _argv(rebinds=rebinds)
    dns = _at(argv, "--ro-bind-fd", "61", "/run/systemd/resolve/stub-resolv.conf")
    notify = _at(
        argv, "--ro-bind", "/run/user/1000/systemd/notify", "/run/user/1000/systemd/notify"
    )
    lock = _at(argv, "--ro-bind-fd", "62", "/run/user/1000/breezy-studies.lock")
    data = _at(argv, "--ro-bind", PURE_ROOTS.data_root.as_posix(), PURE_ROOTS.data_root.as_posix())
    assert data < dns < notify < lock < _at(argv, "--remount-ro", "/run")
    assert _at(argv, "--remount-ro", "/run") < _at(
        argv, "--bind-fd", "100", _opened(SELFTEST).binds[0].path
    )


def test_argv_without_rebinds_still_remounts_run_readonly() -> None:
    argv = _argv()
    assert _at(argv, "--remount-ro", "/run") > _at(argv, "--tmpfs", "/run")


def test_dns_rebind_is_resolv_target_file_only() -> None:
    argv = _argv(rebinds=(RunRebind("dns", dest="/run/systemd/resolve/stub-resolv.conf", fd=61),))
    run_binds = [
        argv[i + 2]
        for i, token in enumerate(argv)
        if token in ("--ro-bind", "--ro-bind-fd") and argv[i + 2].startswith("/run/")
    ]
    assert run_binds == ["/run/systemd/resolve/stub-resolv.conf"]


def test_argv_config_ro_then_binds_use_fds_never_path_bind() -> None:
    row = _replace(
        SELFTEST,
        binds=("cache/autonomy_selftest", "evidence/x"),
        config_ro_binds=(".config/a.conf",),
        config_ro_dirs=(".config/adir",),
    )
    argv = _argv(row)
    config_file = _at(argv, "--ro-bind-fd", "150", "/home/u/.config/a.conf")
    config_dir = _at(argv, "--ro-bind-fd", "170", "/home/u/.config/adir")
    first = _at(argv, "--bind-fd", "100", f"{PURE_ROOTS.data_root}/cache/autonomy_selftest")
    second = _at(argv, "--bind-fd", "101", f"{PURE_ROOTS.data_root}/evidence/x")
    assert config_file < config_dir < first < second < _at(argv, "--remount-ro", "/home/u")
    assert "--bind" not in argv and "--bind-try" not in argv
    assert not any(token == "--ro-bind-try" for token in argv)


def test_argv_session_flags_then_chdir_then_env_then_command() -> None:
    argv = _argv(command=("/usr/bin/true", "x"))
    remount_home = _at(argv, "--remount-ro", "/home/u")
    assert _at(argv, "--new-session", "--die-with-parent") == remount_home + 2
    assert _at(argv, "--chdir", "/") == remount_home + 4
    assert argv[-3:] == ["--", "/usr/bin/true", "x"]


def test_argv_fixed_env_and_unsetenv_degraded() -> None:
    argv = _argv(SELFTEST)
    start = _at(argv, "--setenv", "TMPDIR", "/tmp")
    assert argv[start : start + 12] == [
        "--setenv",
        "TMPDIR",
        "/tmp",
        "--setenv",
        "XDG_CACHE_HOME",
        "/tmp/.cache",
        "--setenv",
        "BREEZY_AUTONOMY_BWRAP_ROW",
        SELFTEST.name,
        "--unsetenv",
        "BREEZY_AUTONOMY_SANDBOX_DEGRADED",
        "--",
    ]


def test_credential_env_emitted_as_setenv_after_fixed_env() -> None:
    row = _replace(
        NOTIFY,
        exceptions=RECONCILE,
        credential_names=("a_key", "b_key"),
        credential_env=MappingProxyType({"Z_VAR": "a_key", "A_VAR": "b_key"}),
    )
    cred_dir = "/run/user/1000/credentials/breezy-autonomy-selftest-notify.service"
    argv = _argv(
        row,
        rebinds=(RunRebind("credentials", dest=cred_dir, fd=70),),
        environ={"CREDENTIALS_DIRECTORY": cred_dir},
    )
    unset = _at(argv, "--unsetenv", "CREDENTIALS_DIRECTORY")
    assert argv[unset + 2 : unset + 9] == [
        "--setenv",
        "A_VAR",
        f"{cred_dir}/b_key",
        "--setenv",
        "Z_VAR",
        f"{cred_dir}/a_key",
        "--",
    ]


def test_argv_no_credential_setenv_on_rows_without_credentials() -> None:
    argv = _argv(SELFTEST)
    assert argv.count("--setenv") == 3


def test_command_starting_with_dash_after_double_dash_verbatim() -> None:
    argv = _argv(command=("-weird", "--unshare-net", "--"))
    assert argv[
        argv.index("--", _at(argv, "--unsetenv", "BREEZY_AUTONOMY_SANDBOX_DEGRADED")) :
    ] == [
        "--",
        "-weird",
        "--unshare-net",
        "--",
    ]


@pytest.mark.parametrize(
    ("cwd", "expected"),
    [
        ("/home/u/repo", "/home/u/repo"),
        ("/home/u/repo/src/x", "/home/u/repo/src/x"),
        ("/home/u/.local/share/breezy/cache", "/home/u/.local/share/breezy/cache"),
        ("/home/u/repo-evil", "/"),
        ("/home/u", "/"),
        ("/tmp", "/"),
    ],
)
def test_chdir_rule(cwd: str, expected: str) -> None:
    argv = _argv(cwd=cwd)
    index = argv.index("--chdir")
    assert argv[index + 1] == expected


def test_chdir_on_fixture_row_uses_the_fixture_base_not_the_data_root() -> None:
    row = _replace(
        SELFTEST,
        bind_base="aut4_fixture",
        exceptions=frozenset({"E7_FIXTURE_ROOT"}),
        bus_reads=(),
        bus_snapshot_bind=None,
        bus_snapshot_budget_s=None,
    )
    assert _argv(row, cwd=FIXTURE_BASE + "/cache")[
        _argv(row, cwd=FIXTURE_BASE + "/cache").index("--chdir") + 1
    ] == (FIXTURE_BASE + "/cache")
    other = _argv(row, cwd="/home/u/.local/share/breezy/cache")
    assert other[other.index("--chdir") + 1] == "/"


def test_bwrap_module_has_no_shell() -> None:
    tree = ast.parse(ARGV_SOURCE.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg == "shell":
            raise AssertionError("bwrap.py must never pass shell=")
        if isinstance(node, ast.Attribute) and node.attr in {
            "system",
            "popen",
            "spawnlp",
            "execvp",
        }:
            raise AssertionError(f"bwrap.py must not use {node.attr}")


# ----------------------------------------------------------------- unit check


def _cgroup(
    leaf: str, prefix: str = "/user.slice/user-1000.slice/user@1000.service/app.slice"
) -> str:
    return f"0::{prefix}/{leaf}\n"


def test_current_unit_name_returns_the_service_leaf() -> None:
    assert current_unit_name(_cgroup("breezy-x.service")) == "breezy-x.service"


@pytest.mark.parametrize(
    "text",
    [
        "",
        "12:cpu:/foo/breezy-x.service\n",
        "0::/a/breezy-x.service\n0::/b/breezy-x.service\n",
        "0::/a/session-3.scope\n",
        "0::/a/app.slice\n",
        "0::/a/breezy-x.service/sub\n",
        "0::/\n",
    ],
    ids=["empty", "no-0-line", "two-0-lines", "scope-leaf", "slice-leaf", "sub-cgroup", "root"],
)
def test_current_unit_name_refuses_malformed_cgroups(text: str) -> None:
    with pytest.raises(UnitCheckError):
        current_unit_name(text)


def test_current_unit_name_ignores_other_hierarchy_lines() -> None:
    text = "1:name=systemd:/x\n" + _cgroup("breezy-x.service")
    assert current_unit_name(text) == "breezy-x.service"


# ------------------------------------------------------------------- main(...)


class ExecSpy:
    """An ``execv`` stand-in: records the call and which fds were inheritable."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, list[str]]] = []
        self.inheritable: set[int] = set()
        self.baseline: set[int] = _inheritable_fds()

    def __call__(self, path: str, argv: list[str]) -> None:
        self.calls.append((path, list(argv)))
        self.inheritable = _inheritable_fds() - self.baseline


def _inheritable_fds() -> set[int]:
    result: set[int] = set()
    for name in os.listdir("/proc/self/fd"):
        fd = int(name)
        try:
            if os.get_inheritable(fd):
                result.add(fd)
        except OSError:
            continue
    return result


@pytest.fixture
def world(tmp_path: Path) -> SandboxRoots:
    home = tmp_path / "home"
    bind = home / "data" / "cache" / "autonomy_selftest"
    bind.mkdir(parents=True)
    bind.chmod(0o700)  # data binds refuse group/other-writable directories (B6-R2)
    (home / "repo").mkdir()
    run_user = tmp_path / "run" / "user"
    run_user.mkdir(parents=True)
    return SandboxRoots(
        home=home,
        data_root=home / "data",
        repo_root=home / "repo",
        python_prefix=home / "py",
        uid=os.getuid(),
        run_user=run_user,
    )


def _plain_row(**changes: Any) -> BwrapRow:
    return _replace(
        SELFTEST,
        resolves_dns=False,
        bus_reads=(),
        bus_snapshot_bind=None,
        bus_snapshot_budget_s=None,
        **changes,
    )


def _table(*rows: BwrapRow) -> Mapping[str, BwrapRow]:
    return MappingProxyType({row.name: row for row in rows})


def _cgroup_file(tmp_path: Path, leaf: str = "breezy-autonomy-selftest.service") -> Path:
    path = tmp_path / "cgroup"
    path.write_text(_cgroup(leaf))
    return path


def _run(
    argv: list[str],
    world: SandboxRoots,
    tmp_path: Path,
    *,
    table: Mapping[str, BwrapRow] | None = None,
    leaf: str = "breezy-autonomy-selftest.service",
    bwrap_path: Path = Path(BWRAP_STUB),
    spy: ExecSpy | None = None,
    **kwargs: Any,
) -> tuple[int, ExecSpy]:
    spy = spy or ExecSpy()
    status = main(
        argv,
        roots=world,
        table=table or _table(_plain_row()),
        cgroup_path=_cgroup_file(tmp_path, leaf),
        bwrap_path=str(bwrap_path),
        execv=spy,
        environ=kwargs.pop("environ", {"PATH": "/usr/bin:/bin"}),
        **kwargs,
    )
    return status, spy


def test_main_success_execs_bwrap_with_the_built_argv(world: SandboxRoots, tmp_path: Path) -> None:
    status, spy = _run(["breezy-autonomy-selftest", "/usr/bin/true", "x"], world, tmp_path)
    assert status == 0
    ((path, argv),) = spy.calls
    assert path == BWRAP_STUB and argv[0] == BWRAP_STUB
    assert argv[-3:] == ["--", "/usr/bin/true", "x"]
    assert "--unshare-pid" in argv and "--bind-fd" in argv


def test_main_makes_exactly_the_passed_bind_fds_inheritable(
    world: SandboxRoots, tmp_path: Path
) -> None:
    lock = world.run_user / "breezy-studies.lock"
    lock.touch()
    status, spy = _run(
        ["breezy-autonomy-selftest-proc", "/usr/bin/true"],
        world,
        tmp_path,
        table=_table(AUTONOMY_BWRAP_TABLE["breezy-autonomy-selftest-proc"]),
        leaf="breezy-autonomy-selftest-proc.service",
    )
    assert status == 0
    ((_, argv),) = spy.calls
    passed = {
        int(argv[i + 1]) for i, token in enumerate(argv) if token in ("--bind-fd", "--ro-bind-fd")
    }
    assert len(passed) == 2  # the one bind and the studies lock
    assert spy.inheritable == passed


def test_main_closes_every_fd_it_opened_after_exec_returns(
    world: SandboxRoots, tmp_path: Path
) -> None:
    before = set(os.listdir("/proc/self/fd"))
    _run(["breezy-autonomy-selftest", "/usr/bin/true"], world, tmp_path)
    after = set(os.listdir("/proc/self/fd"))
    assert len(after - before) <= 1  # at most the listdir fd itself


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["breezy-autonomy-selftest"],
        ["breezy-autonomy-selftest\n", "/usr/bin/true"],
        ["--", "/usr/bin/true"],
        ["Breezy-Upper", "/usr/bin/true"],
        ["breezy-", "/usr/bin/true"],
        ["breezy-x;rm", "/usr/bin/true"],
    ],
    ids=[
        "no-args",
        "no-command",
        "newline-row",
        "dashdash-row",
        "upper",
        "bare",
        "semi",
    ],
)
def test_main_syntax_errors_exit_64_before_anything_else(
    argv: list[str], world: SandboxRoots, tmp_path: Path
) -> None:
    status, spy = _run(argv, world, tmp_path)
    assert status == 64 and not spy.calls


def test_main_unknown_row_exits_78(world: SandboxRoots, tmp_path: Path) -> None:
    status, spy = _run(["breezy-no-such-row", "/usr/bin/true"], world, tmp_path)
    assert status == 78 and not spy.calls


def test_main_invalid_table_exits_78_before_the_cgroup_is_read(
    world: SandboxRoots, tmp_path: Path
) -> None:
    bad = _replace(_plain_row(), tmpfs_size_bytes=-1)
    spy = ExecSpy()
    status = main(
        ["breezy-autonomy-selftest", "/usr/bin/true"],
        roots=world,
        table=_table(bad),
        cgroup_path=tmp_path / "does-not-exist",
        bwrap_path=BWRAP_STUB,
        execv=spy,
        environ={"PATH": "/usr/bin"},
    )
    assert status == 78 and not spy.calls


def test_main_transient_run_unit_exits_78(world: SandboxRoots, tmp_path: Path) -> None:
    status, spy = _run(
        ["breezy-autonomy-selftest", "/usr/bin/true"], world, tmp_path, leaf="run-r1a2b3.service"
    )
    assert status == 78 and not spy.calls


@pytest.mark.parametrize(
    "leaf",
    [
        "breezy-autonomy-selftest-notify.service",
        "breezy-autonomy-selftest.scope",
        "breezy-autonomy-selftest.slice",
        "breezy-autonomy-selftest",
    ],
)
def test_main_leaf_not_listed_by_the_row_exits_78(
    leaf: str, world: SandboxRoots, tmp_path: Path
) -> None:
    status, spy = _run(["breezy-autonomy-selftest", "/usr/bin/true"], world, tmp_path, leaf=leaf)
    assert status == 78 and not spy.calls


@pytest.mark.parametrize(
    "text", ["", "12:cpu:/x\n", "0::/a/b.service\n0::/a/breezy-autonomy-selftest.service\n"]
)
def test_main_cgroup_missing_or_multiple_0_lines_exit_78(
    text: str, world: SandboxRoots, tmp_path: Path
) -> None:
    path = tmp_path / "cg"
    path.write_text(text)
    spy = ExecSpy()
    status = main(
        ["breezy-autonomy-selftest", "/usr/bin/true"],
        roots=world,
        table=_table(_plain_row()),
        cgroup_path=path,
        bwrap_path=BWRAP_STUB,
        execv=spy,
        environ={"PATH": "/usr/bin"},
    )
    assert status == 78 and not spy.calls


def test_main_unreadable_cgroup_exits_78(world: SandboxRoots, tmp_path: Path) -> None:
    spy = ExecSpy()
    status = main(
        ["breezy-autonomy-selftest", "/usr/bin/true"],
        roots=world,
        table=_table(_plain_row()),
        cgroup_path=tmp_path / "absent",
        bwrap_path=BWRAP_STUB,
        execv=spy,
        environ={"PATH": "/usr/bin"},
    )
    assert status == 78 and not spy.calls


def test_main_template_instance_leaf_must_match_the_instance_regex(
    world: SandboxRoots, tmp_path: Path
) -> None:
    row = _replace(
        _plain_row(), name="breezy-autonomy-tpl", units=frozenset({"breezy-autonomy-tpl@"})
    )
    ok, _ = _run(
        ["breezy-autonomy-tpl", "/usr/bin/true"],
        world,
        tmp_path,
        table=_table(row),
        leaf="breezy-autonomy-tpl@pm_us_v4.service",
    )
    dash, spy = _run(
        ["breezy-autonomy-tpl", "/usr/bin/true"],
        world,
        tmp_path,
        table=_table(row),
        leaf="breezy-autonomy-tpl@-bad.service",
    )
    assert ok == 0 and dash == 78 and not spy.calls


def test_main_missing_bind_source_exits_78_and_creates_nothing(
    world: SandboxRoots, tmp_path: Path
) -> None:
    (world.data_root / "cache" / "autonomy_selftest").rmdir()
    before = sorted(p.as_posix() for p in world.data_root.rglob("*"))
    status, spy = _run(["breezy-autonomy-selftest", "/usr/bin/true"], world, tmp_path)
    assert status == 78 and not spy.calls
    assert sorted(p.as_posix() for p in world.data_root.rglob("*")) == before


def test_main_missing_studies_lock_exits_78(world: SandboxRoots, tmp_path: Path) -> None:
    status, spy = _run(
        ["breezy-autonomy-selftest-proc", "/usr/bin/true"],
        world,
        tmp_path,
        table=_table(AUTONOMY_BWRAP_TABLE["breezy-autonomy-selftest-proc"]),
        leaf="breezy-autonomy-selftest-proc.service",
    )
    assert status == 78 and not spy.calls


def test_main_missing_command_exits_127(world: SandboxRoots, tmp_path: Path) -> None:
    status, spy = _run(["breezy-autonomy-selftest", "/nonexistent/cmd"], world, tmp_path)
    assert status == 127 and not spy.calls


def test_main_missing_command_on_path_exits_127(world: SandboxRoots, tmp_path: Path) -> None:
    status, spy = _run(["breezy-autonomy-selftest", "no-such-command-xyz"], world, tmp_path)
    assert status == 127 and not spy.calls


def test_main_command_found_on_path_is_accepted(world: SandboxRoots, tmp_path: Path) -> None:
    status, spy = _run(["breezy-autonomy-selftest", "true"], world, tmp_path)
    assert status == 0 and spy.calls[0][1][-2:] == ["--", "true"]


def test_main_present_but_not_executable_exits_126(world: SandboxRoots, tmp_path: Path) -> None:
    script = tmp_path / "noexec.sh"
    script.write_text("#!/bin/sh\n")
    script.chmod(0o644)
    status, spy = _run(["breezy-autonomy-selftest", str(script)], world, tmp_path)
    assert status == 126 and not spy.calls


def test_main_command_that_is_a_directory_exits_126(world: SandboxRoots, tmp_path: Path) -> None:
    status, spy = _run(["breezy-autonomy-selftest", str(tmp_path)], world, tmp_path)
    assert status == 126 and not spy.calls


def test_main_missing_bwrap_exits_127(world: SandboxRoots, tmp_path: Path) -> None:
    status, spy = _run(
        ["breezy-autonomy-selftest", "/usr/bin/true"],
        world,
        tmp_path,
        bwrap_path=tmp_path / "no-bwrap",
    )
    assert status == 127 and not spy.calls


def test_main_failures_print_codes_never_paths(
    world: SandboxRoots, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _run(["breezy-autonomy-selftest", "/usr/bin/true"], world, tmp_path, leaf="run-r1.service")
    (world.data_root / "cache" / "autonomy_selftest").rmdir()
    _run(["breezy-autonomy-selftest", "/usr/bin/true"], world, tmp_path)
    err = capsys.readouterr().err
    assert err.strip()
    assert "/" not in err.replace("breezy-autonomy-bwrap", "")


def test_main_production_default_reads_real_cgroup_and_refuses() -> None:
    parameters = inspect.signature(main).parameters
    assert parameters["cgroup_path"].default == Path("/proc/self/cgroup")
    assert parameters["bwrap_path"].default == BWRAP_PATH
    assert parameters["execv"].default is os.execv
    spy = ExecSpy()
    status = main(["breezy-autonomy-selftest", "/usr/bin/true"], execv=spy)
    assert status == 78 and not spy.calls, (
        "the test process is not breezy-autonomy-selftest.service"
    )


# ------------------------------------------------------------------- fallback


def test_non_notifier_row_never_falls_back_when_bwrap_is_missing(
    world: SandboxRoots, tmp_path: Path
) -> None:
    status, spy = _run(
        ["breezy-autonomy-selftest", "/usr/bin/true"],
        world,
        tmp_path,
        bwrap_path=tmp_path / "no-bwrap",
    )
    assert status == 127 and not spy.calls


def test_notifier_fallback_set_is_empty_in_seam_b() -> None:
    assert NOTIFIER_FALLBACK_ROWS == frozenset()


FALLBACK_ROWS = frozenset({"breezy-autonomy-selftest"})


def _fallback_run(
    world: SandboxRoots,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    outcome: int | BaseException,
    **kwargs: Any,
) -> tuple[int, ExecSpy, list[dict[str, Any]], dict[str, str]]:
    seen: list[dict[str, Any]] = []

    def fake_run(argv: list[str], **options: Any) -> subprocess.CompletedProcess[bytes]:
        seen.append({"argv": argv, **options})
        if isinstance(outcome, BaseException):
            raise outcome
        return subprocess.CompletedProcess(argv, outcome)

    monkeypatch.setattr(subprocess, "run", fake_run)
    environ = {"PATH": "/usr/bin:/bin"}
    status, spy = _run(
        ["breezy-autonomy-selftest", "/usr/bin/true", "arg"],
        world,
        tmp_path,
        fallback_rows=FALLBACK_ROWS,
        environ=environ,
        **kwargs,
    )
    return status, spy, seen, environ


def test_fallback_row_preflights_with_bin_true_under_2s_then_wraps_when_ok(
    world: SandboxRoots, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    status, spy, seen, environ = _fallback_run(world, tmp_path, monkeypatch, 0)
    assert status == 0
    ((call,),) = [(c,) for c in seen]
    assert call["timeout"] == 2 and not call.get("shell")
    assert call["argv"][0] == BWRAP_STUB and call["argv"][-2:] == ["--", "/bin/true"]
    assert spy.calls[0][1][-3:] == ["--", "/usr/bin/true", "arg"]
    assert "BREEZY_AUTONOMY_SANDBOX_DEGRADED" not in environ


@pytest.mark.parametrize(
    ("outcome", "reason"),
    [(3, "preflight_rc_3"), (subprocess.TimeoutExpired("bwrap", 2), "preflight_timeout")],
)
def test_fallback_row_degrades_on_preflight_failure_with_reason(
    outcome: int | BaseException,
    reason: str,
    world: SandboxRoots,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    status, spy, _, environ = _fallback_run(world, tmp_path, monkeypatch, outcome)
    assert status == 0
    ((path, argv),) = spy.calls
    assert path == "/usr/bin/true" and argv == ["/usr/bin/true", "arg"]
    assert environ["BREEZY_AUTONOMY_SANDBOX_DEGRADED"] == reason


@pytest.mark.parametrize(
    ("outcome", "reason"),
    [(3, "preflight_rc_3"), (subprocess.TimeoutExpired("bwrap", 2), "preflight_timeout")],
)
def test_degraded_exec_also_sets_the_row_env_so_the_probe_reports_degraded(
    outcome: int | BaseException,
    reason: str,
    world: SandboxRoots,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """B7-R1: a notifier-fallback run must report ``degraded``, never ``env_row``."""
    status, _, _, environ = _fallback_run(world, tmp_path, monkeypatch, outcome)
    assert status == 0
    assert environ["BREEZY_AUTONOMY_BWRAP_ROW"] == "breezy-autonomy-selftest"
    assert environ["BREEZY_AUTONOMY_SANDBOX_DEGRADED"] == reason
    result = run_self_probe(
        "breezy-autonomy-selftest",
        roots=world,
        environ=environ,
        fallback_rows=FALLBACK_ROWS,
        table=_table(_plain_row()),
    )
    assert (result.ok, result.degraded, result.failures) == (False, True, ())


def test_degraded_exec_for_a_missing_bwrap_also_sets_the_row_env(
    world: SandboxRoots, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, _, environ = _fallback_run(
        world, tmp_path, monkeypatch, 0, bwrap_path=tmp_path / "no-bwrap"
    )
    assert environ["BREEZY_AUTONOMY_BWRAP_ROW"] == "breezy-autonomy-selftest"


def test_fallback_row_degrades_when_bwrap_is_missing_without_preflight(
    world: SandboxRoots, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    status, spy, seen, environ = _fallback_run(
        world, tmp_path, monkeypatch, 0, bwrap_path=tmp_path / "no-bwrap"
    )
    assert status == 0 and not seen
    assert spy.calls[0][1] == ["/usr/bin/true", "arg"]
    assert environ["BREEZY_AUTONOMY_SANDBOX_DEGRADED"] == "bwrap_missing"


def test_fallback_never_applies_after_a_78_check(
    world: SandboxRoots, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    status, spy, seen, environ = _fallback_run(
        world, tmp_path, monkeypatch, 1, leaf="run-r1.service"
    )
    assert status == 78 and not spy.calls and not seen
    assert "BREEZY_AUTONOMY_SANDBOX_DEGRADED" not in environ


def test_fallback_never_applies_to_a_missing_command(
    world: SandboxRoots, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[object] = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: seen.append(a))
    status, spy = _run(
        ["breezy-autonomy-selftest", "/nonexistent/cmd"],
        world,
        tmp_path,
        fallback_rows=FALLBACK_ROWS,
    )
    assert status == 127 and not spy.calls and not seen


# --------------------------------------------------------------- wrapper script


WRAPPER_FILE = Path(__file__).resolve().parents[2] / "deploy" / "systemd" / "breezy-autonomy-bwrap"


def test_wrapper_script_is_mode_0755_with_isolated_project_interpreter_shebang() -> None:
    assert stat.S_IMODE(WRAPPER_FILE.stat().st_mode) == 0o755
    first = WRAPPER_FILE.read_text().splitlines()[0]
    assert first == "#!/home/jon/breezy/.venv/bin/python3 -I"


def test_wrapper_script_only_calls_main_with_argv_tail() -> None:
    tree = ast.parse(WRAPPER_FILE.read_text())
    calls = [
        node
        for node in tree.body
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
    ]
    assert [ast.unparse(node) for node in calls] == ["sys.exit(main(sys.argv[1:]))"]
    imports = [ast.unparse(n) for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
    assert imports == ["import sys", "from breezy.runtime.autonomy_sandbox.bwrap import main"]


# ------------------------------------------------- B6-R8: namespaces and environment


def _unset_names(argv: list[str]) -> set[str]:
    return {argv[i + 1] for i, token in enumerate(argv) if token == "--unsetenv"}


def test_argv_unshares_ipc_uts_cgroup_after_pid_and_never_net_or_clearenv() -> None:
    argv = _argv()
    pid = argv.index("--unshare-pid")
    assert argv[pid + 1 : pid + 4] == ["--unshare-ipc", "--unshare-uts", "--unshare-cgroup-try"]
    assert "--unshare-net" not in argv and "--clearenv" not in argv


HOSTILE_ENV = {
    "NOTIFY_SOCKET": "/run/user/1000/systemd/notify",
    "LD_PRELOAD": "/x.so",
    "LD_LIBRARY_PATH": "/x",
    "PYTHONSTARTUP": "/s.py",
    "PYTHONPATH": "/p",
    "CREDENTIALS_DIRECTORY": "/run/user/1000/credentials/u",
    "SSL_CERT_FILE": "/c.pem",
    "GLIBC_TUNABLES": "g",
    "BASH_ENV": "/b",
    "PATH": "/usr/bin",
    "HOME": "/home/u",
    "KEEP_ME": "1",
}


def test_non_notify_row_unsets_every_hostile_environ_name_present() -> None:
    argv = _argv(SELFTEST, environ=HOSTILE_ENV)
    assert _unset_names(argv) == {
        "BREEZY_AUTONOMY_SANDBOX_DEGRADED",
        "NOTIFY_SOCKET",
        "LD_PRELOAD",
        "LD_LIBRARY_PATH",
        "PYTHONSTARTUP",
        "PYTHONPATH",
        "CREDENTIALS_DIRECTORY",
        "SSL_CERT_FILE",
        "GLIBC_TUNABLES",
        "BASH_ENV",
    }
    assert argv.index("--unsetenv") < argv.index("--")


def test_notify_row_keeps_notify_socket_but_unsets_the_rest() -> None:
    names = _unset_names(_argv(NOTIFY, environ=HOSTILE_ENV))
    assert "NOTIFY_SOCKET" not in names
    assert {"LD_PRELOAD", "PYTHONSTARTUP", "CREDENTIALS_DIRECTORY"} <= names


def test_absent_names_are_not_unset() -> None:
    assert _unset_names(_argv(SELFTEST, environ={"PATH": "/usr/bin"})) == {
        "BREEZY_AUTONOMY_SANDBOX_DEGRADED"
    }


# ---------------------------------------------------------- B6-R9: internal errors


def test_unexpected_exception_prints_internal_and_exits_78(
    world: SandboxRoots,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def boom(*_: object, **__: object) -> None:
        raise RuntimeError("/secret/path leaked")

    monkeypatch.setattr(bwrap, "validate_table", boom)
    status, spy = _run(["breezy-autonomy-selftest", "/usr/bin/true"], world, tmp_path)
    err = capsys.readouterr().err
    assert status == 78 and not spy.calls
    assert "internal" in err and "/secret" not in err and "Traceback" not in err
