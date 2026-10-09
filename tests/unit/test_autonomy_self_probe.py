"""ARCH-0 seam B (WP-B2b-3): the in-sandbox self-probe and the selftest CLI.

Plan r5 AC-2 (E-7 rule 2, E-7e(d)). The probe is the proof that a wrapped unit
really runs inside its row: the table-derived write negatives, the credential
and ``/run`` checks, the private ``/tmp`` and the pid namespace. Phase 1 cannot
nest bwrap, so these tests drive every step against a scratch tree with the
filesystem seams (``ProbeFs``, ``os.open`` for ``O_TMPFILE``, ``statvfs``)
patched; the real namespace is exercised by
``tests/integration/test_autonomy_sandbox_namespace.py`` (phase 2).

The probe never creates a name under ``state/``, the data root or the repo: the
no-write proofs below list the trees before and after.
"""

from __future__ import annotations

import dataclasses
import errno
import io
import json
import os
import re
import socket
import stat
import subprocess
import sys
from collections.abc import Callable, Iterator
from contextlib import redirect_stdout
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pytest

from breezy.runtime.autonomy_sandbox import selftest_cli
from breezy.runtime.autonomy_sandbox.bus_handoff import (
    BusReadResult,
    BusSnapshot,
    BusSnapshotError,
)
from breezy.runtime.autonomy_sandbox.bwrap import DEGRADED_VAR, ROW_VAR, _home_rebinds
from breezy.runtime.autonomy_sandbox.self_probe import (
    FIXED_REASON_CODES,
    ProbeFs,
    SandboxIntegrityError,
    SelfProbeResult,
    degraded_write_target,
    require_sandbox,
    run_self_probe,
    self_probe_plan,
)
from breezy.runtime.autonomy_sandbox.table import (
    AUTONOMY_BWRAP_TABLE,
    BwrapRow,
    PositiveProbe,
    SandboxRoots,
)
from tests.support.bwrap_harness import make_roots

pytestmark = pytest.mark.allow_socket

ROW = "breezy-autonomy-selftest"
PROC_ROW = "breezy-autonomy-selftest-proc"
BIND = "cache/autonomy_selftest"
POSITIVE_CODE = re.compile(r"positive_[a-z0-9_]+")
Open = Callable[..., int]
_REAL_OPEN: Open = os.open


@dataclasses.dataclass
class World:
    """A scratch filesystem the probe can run against, plus its injected seams."""

    roots: SandboxRoots
    fs: ProbeFs
    environ: dict[str, str]
    table: dict[str, BwrapRow]
    tmpfile_opens: list[str]


def _mountinfo(tmp: Path) -> str:
    return f"30 1 0:25 / {tmp} rw,nosuid - tmpfs tmpfs rw,size=262144k\n"


@pytest.fixture
def world(tmp_path: Path) -> World:
    roots = make_roots(tmp_path)
    fsroot = tmp_path / "fsroot"
    for sub in ("run", "tmp", "proc/1", "var"):
        (fsroot / sub).mkdir(parents=True)
    (fsroot / "proc" / "1" / "comm").write_text("bwrap\n")
    mountinfo = fsroot / "mountinfo"
    mountinfo.write_text(_mountinfo(fsroot / "tmp"))
    fs = ProbeFs(
        host_root=fsroot,
        run=fsroot / "run",
        tmp=fsroot / "tmp",
        proc=fsroot / "proc",
        mountinfo=mountinfo,
        getpid=lambda: 4242,
    )
    return World(
        roots=roots,
        fs=fs,
        environ={ROW_VAR: ROW},
        table=dict(AUTONOMY_BWRAP_TABLE),
        tmpfile_opens=[],
    )


def _probe(world: World, row: str = ROW, **changes: Any) -> SelfProbeResult:
    kwargs: dict[str, Any] = {
        "roots": world.roots,
        "environ": world.environ,
        "fs": world.fs,
        "table": world.table,
    }
    kwargs.update(changes)
    return run_self_probe(row, **kwargs)


def _tmpfile_paths(world: World) -> set[str]:
    """Every directory the probe expects to be read-only for ``O_TMPFILE``."""
    plan = self_probe_plan(world.table[ROW], world.roots)
    return {str(target.path) for target in plan.negatives} | {str(world.fs.run)}


@pytest.fixture
def sandboxed(world: World, monkeypatch: pytest.MonkeyPatch) -> World:
    """Make every read-only target answer ``O_TMPFILE`` with EROFS, as bwrap would."""
    erofs = _tmpfile_paths(world)
    _patch_open(monkeypatch, world, erofs=erofs)
    return world


def _patch_open(
    monkeypatch: pytest.MonkeyPatch,
    world: World,
    *,
    erofs: set[str] | None = None,
    errors: dict[str, int] | None = None,
) -> None:
    erofs, errors = erofs or set(), errors or {}

    def fake(path: Any, flags: int, mode: int = 0o777, **kwargs: Any) -> int:
        if flags & getattr(os, "O_TMPFILE", 0) == getattr(os, "O_TMPFILE", 0):
            world.tmpfile_opens.append(str(path))
            if str(path) in errors:
                raise OSError(errors[str(path)], os.strerror(errors[str(path)]))
            if str(path) in erofs:
                raise OSError(errno.EROFS, os.strerror(errno.EROFS))
        return _REAL_OPEN(path, flags, mode, **kwargs)

    monkeypatch.setattr(os, "open", fake)


def _tree(root: Path) -> set[tuple[str, int, int]]:
    seen: set[tuple[str, int, int]] = set()
    for base, dirs, files in os.walk(root):
        for name in (*dirs, *files):
            st = os.lstat(os.path.join(base, name))
            seen.add((os.path.join(base, name), st.st_ino, st.st_mode))
    return seen


# --- step 1 and 2: the env row and the degraded flag -------------------------------


def test_probe_passes_when_every_step_holds(sandboxed: World) -> None:
    result = _probe(sandboxed)
    assert result.failures == ()
    assert result.ok is True
    assert result.degraded is False


def test_env_row_checked_before_any_open(world: World) -> None:
    opens: list[str] = []
    armed = {"on": True}

    def hook(event: str, args: tuple[Any, ...]) -> None:
        if armed["on"] and event in {"open", "os.listdir", "os.scandir", "socket.connect"}:
            opens.append(event)

    sys.addaudithook(hook)
    try:
        result = _probe(world, environ={ROW_VAR: "breezy-autonomy-selftest-notify"})
    finally:
        armed["on"] = False
    assert result.failures == ("env_row",)
    assert result.ok is False
    assert opens == []


def test_env_row_missing_is_env_row(world: World) -> None:
    assert _probe(world, environ={}).failures == ("env_row",)


def test_unknown_row_is_refused_not_defaulted(world: World) -> None:
    with pytest.raises(KeyError):
        _probe(world, row="breezy-no-such-row", environ={ROW_VAR: "breezy-no-such-row"})


def test_degraded_honoured_only_for_notifier_rows(world: World) -> None:
    environ = {ROW_VAR: ROW, DEGRADED_VAR: "preflight_timeout"}
    result = _probe(world, environ=environ, fallback_rows=frozenset({ROW}))
    assert (result.ok, result.degraded, result.failures) == (False, True, ())
    assert world.tmpfile_opens == []


def test_degraded_forged_for_other_rows(world: World) -> None:
    environ = {ROW_VAR: ROW, DEGRADED_VAR: "1"}
    result = _probe(world, environ=environ, fallback_rows=frozenset())
    assert (result.ok, result.degraded, result.failures) == (False, False, ("degraded_forged",))
    assert world.tmpfile_opens == []


# --- step 3: negatives -------------------------------------------------------------


def test_negative_uses_o_tmpfile_and_requires_exactly_erofs(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = world.roots.data_root / "state"
    state.chmod(0o500)
    others = _tmpfile_paths(world) - {str(state)}
    _patch_open(monkeypatch, world, erofs=others)
    try:
        result = _probe(world)
    finally:
        state.chmod(0o700)
    assert result.failures == ("negative",)
    assert str(state) in world.tmpfile_opens


def test_negative_success_is_negative_and_closes_the_fd(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened: list[int] = []

    def spy(path: Any, flags: int, mode: int = 0o777, **kwargs: Any) -> int:
        fd = _REAL_OPEN(path, flags, mode, **kwargs)
        opened.append(fd)
        return fd

    monkeypatch.setattr(os, "open", spy)
    result = _probe(world)
    assert "negative" in result.failures
    for fd in opened:
        with pytest.raises(OSError):
            os.fstat(fd)


def test_negative_registry_has_its_own_code(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    registry = str(world.roots.data_root / "registry")
    _patch_open(monkeypatch, world, erofs=_tmpfile_paths(world) - {registry})
    assert _probe(world).failures == ("negative_registry",)


def test_negative_requires_owner_uid_precondition(
    sandboxed: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(os, "geteuid", lambda: os.getuid() + 1)
    sandboxed.tmpfile_opens.clear()
    result = _probe(sandboxed)
    assert "negative_unverifiable" in result.failures
    negatives = {
        str(t.path) for t in self_probe_plan(sandboxed.table[ROW], sandboxed.roots).negatives
    }
    assert negatives.isdisjoint(sandboxed.tmpfile_opens)


def test_negative_missing_directory_is_unverifiable_and_never_created(
    sandboxed: World,
) -> None:
    registry = sandboxed.roots.data_root / "registry"
    registry.rmdir()
    result = _probe(sandboxed)
    assert result.failures == ("negative_unverifiable",)
    assert not registry.exists()


def test_negative_eopnotsupp_falls_back_to_statvfs_and_mountinfo(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = self_probe_plan(world.table[ROW], world.roots)
    negatives = {str(t.path): errno.EOPNOTSUPP for t in plan.negatives}
    _patch_open(monkeypatch, world, errors=negatives, erofs={str(world.fs.run)})
    lines = [f"{40 + i} 1 0:30 / {p} ro,nosuid - ext4 /dev/x ro\n" for i, p in enumerate(negatives)]
    world.fs.mountinfo.write_text(_mountinfo(world.fs.tmp) + "".join(lines))
    readonly = os.statvfs_result((4096, 4096, 10, 0, 0, 10, 0, 0, os.ST_RDONLY, 255))
    monkeypatch.setattr(os, "statvfs", lambda path: readonly)
    assert _probe(world).failures == ()
    writable = os.statvfs_result((4096, 4096, 10, 0, 0, 10, 0, 0, 0, 255))
    monkeypatch.setattr(os, "statvfs", lambda path: writable)
    assert "negative_unverifiable" in _probe(world).failures


def test_probe_against_writable_state_leaves_listing_unchanged(world: World) -> None:
    before = (_tree(world.roots.data_root), _tree(world.roots.home))
    result = _probe(world)
    assert "negative" in result.failures
    assert (_tree(world.roots.data_root), _tree(world.roots.home)) == before


# --- step 4: positives -------------------------------------------------------------


def _subdir_row(world: World) -> None:
    base = world.table[ROW]
    world.table[ROW] = dataclasses.replace(
        base, positive_probe=MappingProxyType({BIND: PositiveProbe("subdir")})
    )


def test_positive_tmpfile_mode_leaves_no_entry(sandboxed: World) -> None:
    bind = sandboxed.roots.data_root / BIND
    before = _tree(bind)
    assert _probe(sandboxed).failures == ()
    assert _tree(bind) == before


def test_positive_subdir_mode_creates_and_unlinks_inside_probe_dir(sandboxed: World) -> None:
    _subdir_row(sandboxed)
    probe_dir = sandboxed.roots.data_root / BIND / ".bwrap_probe"
    probe_dir.mkdir()
    assert _probe(sandboxed).failures == ()
    assert list(probe_dir.iterdir()) == []


def test_positive_subdir_mode_never_creates_the_probe_dir(sandboxed: World) -> None:
    _subdir_row(sandboxed)
    probe_dir = sandboxed.roots.data_root / BIND / ".bwrap_probe"
    assert _probe(sandboxed).failures == ("positive_cache_autonomy_selftest",)
    assert not probe_dir.exists()


def test_subdir_unlink_failure_is_probe_residue(
    sandboxed: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    _subdir_row(sandboxed)
    probe_dir = sandboxed.roots.data_root / BIND / ".bwrap_probe"
    probe_dir.mkdir()

    def refuse(path: Any, *args: Any, **kwargs: Any) -> None:
        raise PermissionError(errno.EPERM, "no")

    monkeypatch.setattr(os, "unlink", refuse)
    assert _probe(sandboxed).failures == ("probe_residue",)
    monkeypatch.undo()
    for leftover in probe_dir.iterdir():
        leftover.unlink()


def test_positive_failure_names_the_bind_without_a_path(sandboxed: World) -> None:
    bind = sandboxed.roots.data_root / BIND
    bind.chmod(0o500)
    try:
        failures = _probe(sandboxed).failures
    finally:
        bind.chmod(0o700)
    assert failures == ("positive_cache_autonomy_selftest",)


# --- step 5: credentials and the home listing --------------------------------------


@pytest.mark.parametrize("rel", [".config/breezy", ".ssh", ".aws", ".gnupg", ".netrc"])
def test_credential_paths_visible_are_credentials_visible(sandboxed: World, rel: str) -> None:
    target = sandboxed.roots.home / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    if rel == ".netrc":
        target.write_text("machine x\n")
    else:
        target.mkdir()
    assert "credentials_visible" in _probe(sandboxed).failures


def test_home_listing_outside_the_rebinds_is_credentials_visible(sandboxed: World) -> None:
    (sandboxed.roots.home / "stray").mkdir()
    assert _probe(sandboxed).failures == ("credentials_visible",)


def test_home_listing_fact_is_the_rebind_first_components(sandboxed: World) -> None:
    result = _probe(sandboxed)
    assert result.facts["home_listing"] == [".local"]


def test_expected_home_listing_matches_the_wrappers_home_rebinds(world: World) -> None:
    for row in AUTONOMY_BWRAP_TABLE.values():
        plan = self_probe_plan(row, world.roots)
        derived = {
            Path(p).relative_to(world.roots.home).parts[0]
            for p in _home_rebinds(row, world.roots)
            if Path(p).is_relative_to(world.roots.home)
        }
        # the wrapper also binds each config path (X-13: the health row binds .config/systemd)
        derived |= {rel.split("/", 1)[0] for rel in (*row.config_ro_binds, *row.config_ro_dirs)}
        assert plan.home_listing_allowed == frozenset(derived)


# --- step 6: /run ------------------------------------------------------------------


def _unix_socket(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    cwd = os.getcwd()
    os.chdir(path.parent)
    try:
        sock.bind(path.name)
    finally:
        os.chdir(cwd)
    sock.close()


@pytest.mark.parametrize(
    "rel",
    [
        "run/docker.sock",
        "var/run/docker.sock",
        "run/snapd.socket",
        "run/snapd-snap.socket",
        "var/snap/lxd/common/lxd/unix.socket",
        "run/lxd-installer.socket",
        "run/dbus/system_bus_socket",
    ],
)
def test_host_socket_visible_is_host_socket_visible(sandboxed: World, rel: str) -> None:
    _unix_socket(sandboxed.fs.host_root / rel)
    assert "host_socket_visible" in _probe(sandboxed).failures


@pytest.mark.parametrize("name", ["bus", "systemd/private"])
def test_user_bus_visible_is_user_bus_visible(sandboxed: World, name: str) -> None:
    _unix_socket(sandboxed.fs.host_root / "run" / "user" / str(sandboxed.roots.uid) / name)
    assert "user_bus_visible" in _probe(sandboxed).failures


def test_run_walk_unlisted_socket_is_host_socket_visible(sandboxed: World) -> None:
    os.mknod(sandboxed.fs.run / "extra.sock", stat.S_IFSOCK | 0o600)
    assert _probe(sandboxed).failures == ("host_socket_visible",)


def test_run_walk_unlisted_regular_entry_is_run_not_private(sandboxed: World) -> None:
    (sandboxed.fs.run / "extra").write_text("x")
    assert _probe(sandboxed).failures == ("run_not_private",)


def test_run_walk_admits_exactly_the_row_rebinds_and_their_ancestors(sandboxed: World) -> None:
    run_user = sandboxed.fs.run / "user" / str(sandboxed.roots.uid)
    run_user.mkdir(parents=True)
    roots = dataclasses.replace(sandboxed.roots, run_user=run_user)
    lock = run_user / "breezy-studies.lock"
    lock.touch(mode=0o600)
    sandboxed.environ[ROW_VAR] = PROC_ROW
    sandboxed.fs.proc.joinpath("self").symlink_to("777")
    result = _probe(sandboxed, row=PROC_ROW, roots=roots)
    assert result.failures == ()
    (run_user / "other.lock").touch()
    assert _probe(sandboxed, row=PROC_ROW, roots=roots).failures == ("run_not_private",)


def test_run_writable_is_run_not_readonly(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    erofs = _tmpfile_paths(world) - {str(world.fs.run)}
    _patch_open(monkeypatch, world, erofs=erofs)
    assert _probe(world).failures == ("run_not_readonly",)


# --- step 7: /tmp ------------------------------------------------------------------


def test_tmp_not_a_tmpfs_is_tmp_not_private(sandboxed: World) -> None:
    sandboxed.fs.mountinfo.write_text(f"30 1 0:25 / {sandboxed.fs.tmp} rw - ext4 /dev/x rw\n")
    assert _probe(sandboxed).failures == ("tmp_not_private",)


def test_tmp_without_a_mount_entry_is_tmp_not_private(sandboxed: World) -> None:
    sandboxed.fs.mountinfo.write_text("")
    assert _probe(sandboxed).failures == ("tmp_not_private",)


def test_tmp_where_o_tmpfile_fails_is_tmp_not_private(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    errors = {str(world.fs.tmp): errno.EACCES}
    _patch_open(monkeypatch, world, erofs=_tmpfile_paths(world), errors=errors)
    assert _probe(world).failures == ("tmp_not_private",)


def test_tmp_size_is_reported_in_kib(sandboxed: World, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = os.statvfs_result((4096, 4096, 65536, 0, 0, 10, 0, 0, 0, 255))
    monkeypatch.setattr(os, "statvfs", lambda path: fake)
    assert _probe(sandboxed).facts["tmp_size_kib"] == 262144


# --- step 8: the pid namespace -----------------------------------------------------


def test_non_proc_row_pid_ns_reads_proc_1_comm(sandboxed: World) -> None:
    (sandboxed.fs.proc / "1" / "comm").write_text("systemd\n")
    assert _probe(sandboxed).failures == ("pid_ns",)


def test_proc_row_pid_ns_uses_proc_self(sandboxed: World) -> None:
    sandboxed.environ[ROW_VAR] = PROC_ROW
    run_user = sandboxed.fs.run / "u"
    run_user.mkdir()
    (run_user / "breezy-studies.lock").touch(mode=0o600)
    roots = dataclasses.replace(sandboxed.roots, run_user=run_user)
    (sandboxed.fs.proc / "1" / "comm").write_text("systemd\n")
    link = sandboxed.fs.proc / "self"
    link.symlink_to("777")
    assert _probe(sandboxed, row=PROC_ROW, roots=roots).failures == ()
    link.unlink()
    link.symlink_to("4242")
    assert _probe(sandboxed, row=PROC_ROW, roots=roots).failures == ("pid_ns",)
    link.unlink()
    assert _probe(sandboxed, row=PROC_ROW, roots=roots).failures == ("pid_ns",)


# --- the plan, the vocabulary and the caller contract ------------------------------


def test_self_probe_plan_derived_from_table(world: World) -> None:
    row = world.table[ROW]
    plan = self_probe_plan(row, world.roots)
    data = world.roots.data_root
    assert [(t.label, t.path, t.code) for t in plan.negatives] == [
        ("state", data / "state", "negative"),
        ("registry", data / "registry", "negative_registry"),
        ("data_root", data, "negative"),
        ("repo_root", world.roots.repo_root, "negative"),
        ("ancestor_cache", data / "cache", "negative"),
    ]
    assert [(p.label, p.path, p.kind) for p in plan.positives] == [
        ("cache_autonomy_selftest", data / BIND, "tmpfile")
    ]
    wider = dataclasses.replace(row, binds=(BIND, "evidence/alerts"))
    labels = [t.label for t in self_probe_plan(wider, world.roots).negatives]
    assert labels[-2:] == ["ancestor_cache", "ancestor_evidence"]
    bound_registry = dataclasses.replace(row, binds=("registry/demand",))
    negatives = self_probe_plan(bound_registry, world.roots).negatives
    assert [(t.label, t.code) for t in negatives if t.path == data / "registry"] == [
        ("registry", "negative_registry")
    ]


def test_fixture_base_rows_probe_the_alternate_base_too(world: World) -> None:
    row = dataclasses.replace(
        world.table[ROW], bind_base="aut4_fixture", exceptions=frozenset({"E7_FIXTURE_ROOT"})
    )
    plan = self_probe_plan(row, world.roots)
    base = world.roots.home / ".local/share/breezy-autonomy-fixture"
    assert base in {t.path for t in plan.negatives}
    assert plan.positives[0].path == base / BIND


def test_reason_codes_vocabulary_exact_and_pathless() -> None:
    assert FIXED_REASON_CODES == frozenset(
        {
            "negative",
            "negative_registry",
            "negative_unverifiable",
            "probe_residue",
            "env_row",
            "degraded_forged",
            "credentials_visible",
            "user_bus_visible",
            "host_socket_visible",
            "run_not_private",
            "run_not_readonly",
            "tmp_not_private",
            "pid_ns",
            "net_reachable",
            "net_iface_visible",
        }
    )
    assert all("/" not in code and code == code.lower() for code in FIXED_REASON_CODES)


def test_every_failure_a_run_can_produce_is_in_the_vocabulary(world: World) -> None:
    (world.roots.home / "stray").mkdir()
    (world.fs.run / "extra").write_text("x")
    (world.fs.proc / "1" / "comm").write_text("init\n")
    result = _probe(world)
    assert result.failures
    for code in result.failures:
        assert code in FIXED_REASON_CODES or POSITIVE_CODE.fullmatch(code)
        assert "/" not in code and str(world.roots.home) not in code


def test_require_sandbox_raises_first_code_without_a_path(world: World) -> None:
    with pytest.raises(SandboxIntegrityError) as caught:
        require_sandbox(
            ROW, roots=world.roots, environ=world.environ, fs=world.fs, table=world.table
        )
    error = caught.value
    assert error.code in FIXED_REASON_CODES
    assert error.codes[0] == error.code
    assert "/" not in str(error)


def test_require_sandbox_returns_the_result_when_ok(sandboxed: World) -> None:
    result = require_sandbox(
        ROW,
        roots=sandboxed.roots,
        environ=sandboxed.environ,
        fs=sandboxed.fs,
        table=sandboxed.table,
    )
    assert result.ok is True


def test_require_sandbox_degraded_notifier_row_returns_instead_of_raising(world: World) -> None:
    result = require_sandbox(
        ROW,
        roots=world.roots,
        environ={ROW_VAR: ROW, DEGRADED_VAR: "preflight_timeout"},
        fs=world.fs,
        table=world.table,
        fallback_rows=frozenset({ROW}),
    )
    assert (result.ok, result.degraded) == (False, True)


# --- degraded_write_target ---------------------------------------------------------


def test_degraded_write_target_refuses_state_and_outside_binds(world: World) -> None:
    data = world.roots.data_root
    inside = data / BIND / "alert.json"
    assert degraded_write_target(ROW, inside, roots=world.roots, table=world.table) == Path(
        os.path.realpath(inside)
    )
    for refused in (
        data / "state" / "x",
        data / "cache" / "other" / "x",
        world.roots.repo_root / "x",
        data / BIND / ".." / ".." / "state" / "x",
    ):
        with pytest.raises(ValueError, match="^(state|outside_binds)$"):
            degraded_write_target(ROW, refused, roots=world.roots, table=world.table)


def test_degraded_write_target_refuses_a_symlink_escape(world: World, tmp_path: Path) -> None:
    link = world.roots.data_root / BIND / "link"
    link.symlink_to(world.roots.data_root / "state")
    with pytest.raises(ValueError, match="^(state|outside_binds)$"):
        degraded_write_target(ROW, link / "x", roots=world.roots, table=world.table)


def test_degraded_write_target_unknown_row_raises(world: World) -> None:
    with pytest.raises(KeyError):
        degraded_write_target("breezy-nope", world.roots.data_root, roots=world.roots)


# --- the selftest CLI --------------------------------------------------------------


@pytest.fixture
def run_cli(world: World) -> Iterator[Callable[..., tuple[int, dict[str, Any]]]]:
    def run(argv: list[str], **kwargs: Any) -> tuple[int, dict[str, Any]]:
        out = io.StringIO()
        kwargs.setdefault("roots", world.roots)
        kwargs.setdefault("environ", world.environ)
        kwargs.setdefault("fs", world.fs)
        with redirect_stdout(out):
            code = selftest_cli.main(argv, **kwargs)
        text = out.getvalue()
        return code, json.loads(text) if text.strip() else {}

    yield run


def test_selftest_default_prints_one_json_document_and_exits_3_on_failure(
    world: World, run_cli: Callable[..., tuple[int, dict[str, Any]]]
) -> None:
    code, report = run_cli([])
    assert code == 3
    assert report["ok"] is False
    assert "negative" in report["failures"]
    assert {"row", "tmp_size_kib", "home_listing"} <= set(report)


def test_selftest_ok_exits_0(
    sandboxed: World, run_cli: Callable[..., tuple[int, dict[str, Any]]]
) -> None:
    code, report = run_cli([])
    assert (code, report["ok"], report["failures"]) == (0, True, [])
    assert report["row"] == ROW


def test_selftest_without_a_row_env_is_env_row(
    world: World, run_cli: Callable[..., tuple[int, dict[str, Any]]]
) -> None:
    code, report = run_cli([], environ={})
    assert (code, report["failures"]) == (3, ["env_row"])


@pytest.mark.parametrize("flag", ["--exec-snapshot", "--bogus"])
def test_selftest_modes_not_yet_landed_are_usage_errors(
    world: World, run_cli: Callable[..., tuple[int, dict[str, Any]]], flag: str
) -> None:
    code, report = run_cli([flag])
    assert (code, report) == (64, {})


def test_selftest_proc_checks_are_reported_only_when_asked(
    sandboxed: World, run_cli: Callable[..., tuple[int, dict[str, Any]]]
) -> None:
    _, plain = run_cli([])
    assert "proc_checks" not in plain
    calls: list[str] = []

    def collect(row: BwrapRow, roots: SandboxRoots, fs: ProbeFs) -> dict[str, Any]:
        calls.append(row.name)
        return {"kill": "ESRCH"}

    _, asked = run_cli(["--proc-checks"], proc_checks=collect)
    assert asked["proc_checks"] == {"kill": "ESRCH"}
    assert calls == [ROW]


# --- --bus-snapshot (WP-B2c, V17/V21) ----------------------------------------------


def _bus_snapshot(reads: dict[str, int]) -> BusSnapshot:
    return BusSnapshot(
        invocation_id="0" * 32,
        unit=f"{ROW}.service",
        ts_ns=1,
        budget_s=10,
        reads=tuple(
            BusReadResult(
                name=name, argv=(), rc=rc, timed_out=False, skipped=False, oversize=False, stdout=""
            )
            for name, rc in reads.items()
        ),
    )


def test_selftest_bus_snapshot_reports_the_reads_and_the_failing_in_row_systemctl(
    sandboxed: World, run_cli: Callable[..., tuple[int, dict[str, Any]]]
) -> None:
    seen: list[str] = []

    def reader(row: BwrapRow, **kwargs: Any) -> BusSnapshot:
        seen.append(row.name)
        return _bus_snapshot({"self_show": 0})

    code, report = run_cli(["--bus-snapshot"], bus_reader=reader, systemctl=lambda row: "failed")
    assert code == 0 and seen == [ROW]
    assert report["bus_snapshot"] == {"self_show": {"rc": 0}}
    assert report["in_row_systemctl"] == "failed"


def test_selftest_bus_snapshot_missing_is_reported_by_code_not_raised(
    sandboxed: World, run_cli: Callable[..., tuple[int, dict[str, Any]]]
) -> None:
    def reader(row: BwrapRow, **kwargs: Any) -> BusSnapshot:
        raise BusSnapshotError("bus_snapshot_missing")

    code, report = run_cli(["--bus-snapshot"], bus_reader=reader, systemctl=lambda row: "failed")
    assert code == 0 and report["bus_snapshot"] == "bus_snapshot_missing"


def test_selftest_bus_snapshot_stale_is_reported_by_code(
    sandboxed: World, run_cli: Callable[..., tuple[int, dict[str, Any]]]
) -> None:
    def reader(row: BwrapRow, **kwargs: Any) -> BusSnapshot:
        raise BusSnapshotError("bus_snapshot_stale")

    _, report = run_cli(["--bus-snapshot"], bus_reader=reader, systemctl=lambda row: "failed")
    assert report["bus_snapshot"] == "bus_snapshot_stale"


def test_selftest_bus_snapshot_on_a_row_without_bus_reads_is_skipped(
    sandboxed: World, run_cli: Callable[..., tuple[int, dict[str, Any]]]
) -> None:
    def reader(row: BwrapRow, **kwargs: Any) -> BusSnapshot:
        raise AssertionError("a row without bus reads has nothing to read")

    sandboxed.environ[ROW_VAR] = "breezy-autonomy-selftest-notify"
    _, report = run_cli(["--bus-snapshot"], bus_reader=reader, systemctl=lambda row: "failed")
    assert report["bus_snapshot"] == "not_a_bus_row"


def test_selftest_default_systemctl_probe_fails_without_a_user_bus(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []

    def fake_run(argv: list[str], **kwargs: Any) -> Any:
        calls.append(argv)
        return type("Done", (), {"returncode": 1})()

    monkeypatch.setattr(subprocess, "run", fake_run)
    row = world.table[ROW]
    assert selftest_cli.in_row_systemctl(row) == "failed"
    ((argv,),) = [(c,) for c in calls]
    assert argv[:3] == ["/usr/bin/systemctl", "--user", "show"] and argv[-2:] == [
        "--",
        f"{ROW}.service",
    ]
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda argv, **kwargs: (_ for _ in ()).throw(FileNotFoundError("x")),
    )
    assert selftest_cli.in_row_systemctl(row) == "failed"
    monkeypatch.setattr(subprocess, "run", lambda argv, **kw: type("D", (), {"returncode": 0})())
    assert selftest_cli.in_row_systemctl(row) == "ok"


# --- --exec-snapshot N (WP-B3, V10) ------------------------------------------------

EXEC_DB = "exec_polymarket_us.sqlite"


def _exec_store(world: World, *, create: bool = True) -> Path:
    """A scratch exec store under the world's data root; the cache bind's parent is 0700."""
    (world.roots.data_root / "cache").chmod(0o700)
    db = world.roots.data_root / "state" / EXEC_DB
    if create:
        import sqlite3

        conn = sqlite3.connect(db)
        conn.execute("CREATE TABLE t(v TEXT)")
        conn.execute("INSERT INTO t VALUES ('a')")
        conn.commit()
        conn.close()
    return db


def test_selftest_exec_snapshot_runs_n_advisory_snapshots_and_prints_counts(
    sandboxed: World, run_cli: Callable[..., tuple[int, dict[str, Any]]]
) -> None:
    _exec_store(sandboxed)
    state = sandboxed.roots.data_root / "state"
    listing = sorted(os.listdir(state))
    code, report = run_cli(["--exec-snapshot", "3"])
    assert code == 0
    assert report["snap"] == {"ok": 3, "unstable": 0, "failed": {}}
    assert sorted(os.listdir(state)) == listing
    assert os.listdir(sandboxed.roots.data_root / BIND) == []


def test_selftest_exec_snapshot_counts_failures_by_reason_and_leaks_no_path(
    sandboxed: World, run_cli: Callable[..., tuple[int, dict[str, Any]]], capsys: Any
) -> None:
    _exec_store(sandboxed, create=False)
    out = io.StringIO()
    with redirect_stdout(out):
        code = selftest_cli.main(
            ["--exec-snapshot", "2"],
            roots=sandboxed.roots,
            environ=sandboxed.environ,
            fs=sandboxed.fs,
        )
    report = json.loads(out.getvalue())
    assert code == 0
    assert report["snap"] == {"ok": 0, "unstable": 0, "failed": {"source_invalid": 2}}
    assert str(sandboxed.roots.data_root) not in out.getvalue()


def test_selftest_exec_snapshot_uses_the_injected_runner_with_the_count(
    sandboxed: World, run_cli: Callable[..., tuple[int, dict[str, Any]]]
) -> None:
    seen: list[tuple[int, Path]] = []

    def runner(count: int, roots: SandboxRoots) -> dict[str, Any]:
        seen.append((count, roots.data_root))
        return {"ok": count, "unstable": 0, "failed": {}}

    code, report = run_cli(["--exec-snapshot", "20"], exec_snapshots=runner)
    assert code == 0 and seen == [(20, sandboxed.roots.data_root)]
    assert report["snap"]["ok"] == 20


@pytest.mark.parametrize("count", ["0", "-1", "x", "3.5", "", "51", "1001", "٣"])
def test_selftest_exec_snapshot_rejects_a_bad_count_with_usage(
    world: World, run_cli: Callable[..., tuple[int, dict[str, Any]]], count: str
) -> None:
    code, report = run_cli(["--exec-snapshot", count])
    assert (code, report) == (64, {})


def test_selftest_exec_snapshot_is_not_reported_unless_asked(
    sandboxed: World, run_cli: Callable[..., tuple[int, dict[str, Any]]]
) -> None:
    _, plain = run_cli([])
    assert "snap" not in plain


def test_selftest_exec_snapshot_bind_is_the_selftest_rows_cache_bind() -> None:
    assert selftest_cli.EXEC_SNAPSHOT_BIND in AUTONOMY_BWRAP_TABLE[ROW].binds
