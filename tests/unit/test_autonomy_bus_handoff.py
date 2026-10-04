"""ARCH-0 seam B (WP-B2c): the bus snapshot handoff (plan r5 AC-9, M34/M38/M41, B6-R3, L-55).

``--bus-snapshot ROW`` runs unsandboxed in ``ExecStartPre`` and writes one
``<INVOCATION_ID>.json`` into ``<bind>/.bus_snapshot``; ``read_bus_snapshot`` reads and
consumes it inside the sandbox. Every test drives ``write_bus_snapshot`` / ``main`` against
a real scratch tree with an injected ``popen`` -- nothing here runs a real ``systemctl``.
"""

from __future__ import annotations

import ast
import dataclasses
import errno
import fcntl
import inspect
import json
import os
import select
import signal
import stat
import subprocess
import time
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pytest

from breezy.runtime.autonomy_sandbox import bus_handoff, bwrap
from breezy.runtime.autonomy_sandbox.binds import forbidden_dirs
from breezy.runtime.autonomy_sandbox.bus_handoff import (
    BUS_ENV_PATH,
    BusSnapshot,
    BusSnapshotError,
    read_bus_snapshot,
    write_bus_snapshot,
)
from breezy.runtime.autonomy_sandbox.bwrap import main
from breezy.runtime.autonomy_sandbox.table import (
    AUTONOMY_BWRAP_TABLE,
    SYSTEMCTL,
    BusRead,
    BwrapRow,
    SandboxRoots,
)

ROW_NAME = "breezy-autonomy-selftest"
UNIT = f"{ROW_NAME}.service"
ROW = AUTONOMY_BWRAP_TABLE[ROW_NAME]
INVOCATION = "0123456789abcdef0123456789abcdef"
OTHER_INVOCATION = "fedcba9876543210fedcba9876543210"
SNAP_DIR = ".bus_snapshot"
OLD_AGE_S = 2 * 24 * 3600


@pytest.fixture
def world(tmp_path: Path) -> SandboxRoots:
    home = tmp_path / "home"
    bind = home / "data" / "cache" / "autonomy_selftest"
    bind.mkdir(parents=True)
    bind.chmod(0o700)
    (home / "data" / "state").mkdir()
    (home / "repo").mkdir()
    return SandboxRoots(
        home=home,
        data_root=home / "data",
        repo_root=home / "repo",
        python_prefix=home / "py",
        uid=os.getuid(),
        run_user=tmp_path / "run" / "user",
    )


def _bind(world: SandboxRoots) -> Path:
    return world.data_root / "cache" / "autonomy_selftest"


def _snap(world: SandboxRoots) -> Path:
    return _bind(world) / SNAP_DIR


def _env(**extra: str) -> dict[str, str]:
    return {"INVOCATION_ID": INVOCATION, **extra}


class Sim:
    """Simulated waiting: with a fake clock, a ``select`` that finds nothing advances it."""

    def __init__(self) -> None:
        self.clock: Clock | None = None
        self.select_timeouts: list[float | None] = []
        self.procs: list[FakeProc] = []


SIM = Sim()
_REAL_SELECT = select.select


def _fake_select(
    rlist: list[Any], wlist: list[Any], xlist: list[Any], timeout: float | None = None
) -> tuple[list[Any], list[Any], list[Any]]:
    SIM.select_timeouts.append(timeout)
    ready = _REAL_SELECT(rlist, wlist, xlist, 0)
    if ready[0]:
        return ready
    if SIM.clock is None:
        return _REAL_SELECT(rlist, wlist, xlist, timeout)
    assert timeout is not None
    SIM.clock.advance(timeout)
    return ([], [], [])


@pytest.fixture(autouse=True)
def _simulated_waiting(monkeypatch: pytest.MonkeyPatch) -> Iterator[Sim]:
    SIM.clock, SIM.select_timeouts, SIM.procs = None, [], []
    monkeypatch.setattr(select, "select", _fake_select)
    yield SIM
    for proc in SIM.procs:
        proc.close()
    SIM.clock = None


class FakeProc:
    """A ``Popen`` stand-in with a real pipe: ``done`` is at EOF, ``hang`` never writes."""

    def __init__(
        self,
        argv: list[str],
        kwargs: dict[str, Any],
        outcome: tuple[Any, ...],
    ) -> None:
        self.args, self.kwargs, self.outcome = argv, kwargs, outcome
        self.pid = 4242
        self.returncode: int | None = None
        self.waits: list[float | None] = []
        read_fd, write_fd = os.pipe()
        self._write_fd: int | None = write_fd
        if outcome[0] == "done":
            os.write(write_fd, outcome[2])
            os.close(write_fd)
            self._write_fd = None
        self.stdout = os.fdopen(read_fd, "rb")

    def wait(self, timeout: float | None = None) -> int:
        self.waits.append(timeout)
        self.returncode = self.outcome[1] if self.outcome[0] == "done" else -9
        return self.returncode

    def close(self) -> None:
        if self._write_fd is not None:
            os.close(self._write_fd)
            self._write_fd = None
        self.stdout.close()


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class Runner:
    """Records every spawn; outcomes are consumed in order (the last one repeats)."""

    def __init__(self, clock: Clock, *outcomes: tuple[Any, ...]) -> None:
        self.clock = clock
        self.outcomes = list(outcomes) or [("done", 0, b"Id=x\n")]
        self.calls: list[tuple[list[str], dict[str, Any]]] = []
        self.procs: list[FakeProc] = []

    def __call__(self, argv: list[str], **kwargs: Any) -> FakeProc:
        self.calls.append((list(argv), kwargs))
        index = min(len(self.calls) - 1, len(self.outcomes) - 1)
        proc = FakeProc(list(argv), kwargs, self.outcomes[index])
        self.procs.append(proc)
        SIM.procs.append(proc)
        SIM.clock = self.clock
        return proc


@pytest.fixture
def killpg(monkeypatch: pytest.MonkeyPatch) -> list[tuple[int, int]]:
    calls: list[tuple[int, int]] = []
    monkeypatch.setattr(os, "killpg", lambda pid, sig: calls.append((pid, sig)))
    return calls


def _row(*reads: BusRead, budget: int = 10) -> BwrapRow:
    return dataclasses.replace(ROW, bus_reads=reads, bus_snapshot_budget_s=budget)


def _read(name: str, *tail: str) -> BusRead:
    units = tail or ("--", "breezy-x.service")
    return BusRead(name, (SYSTEMCTL, "--user", "show", "-p", "Id", *units))


def _write(
    world: SandboxRoots,
    row: BwrapRow = ROW,
    *,
    runner: Callable[..., Any] | None = None,
    environ: Mapping[str, str] | None = None,
    unit: str = UNIT,
    clock: Callable[[], float] | None = None,
    **kwargs: Any,
) -> int:
    return write_bus_snapshot(
        row,
        roots=world,
        environ=_env() if environ is None else environ,
        unit=unit,
        popen=runner or Runner(Clock()),
        clock=clock or Clock(),
        **kwargs,
    )


def _written(world: SandboxRoots) -> dict[str, Any]:
    parsed: dict[str, Any] = json.loads((_snap(world) / f"{INVOCATION}.json").read_text())
    return parsed


def _age(path: Path, seconds: float) -> None:
    then = time.time() - seconds
    os.utime(path, (then, then), follow_symlinks=False)


def _hex_name(char: str) -> str:
    return f"{char * 32}.json"


# ------------------------------------------------------------------ write: happy path


def test_write_records_every_read_and_returns_zero(world: SandboxRoots) -> None:
    clock = Clock()
    runner = Runner(clock, ("done", 0, b"Id=breezy-autonomy-selftest.service\n"))
    assert _write(world, runner=runner, clock=clock) == 0
    doc = _written(world)
    assert doc["schema"] == "bus_snapshot/v1"
    assert (doc["invocation_id"], doc["unit"], doc["budget_s"]) == (INVOCATION, UNIT, 10)
    assert isinstance(doc["ts_ns"], int)
    (read,) = doc["reads"]
    assert read == {
        "name": "self_show",
        "argv": list(ROW.bus_reads[0].argv),
        "rc": 0,
        "timed_out": False,
        "skipped": False,
        "oversize": False,
        "stdout": "Id=breezy-autonomy-selftest.service\n",
    }
    st = os.lstat(_snap(world) / f"{INVOCATION}.json")
    assert stat.S_IMODE(st.st_mode) == 0o600
    assert stat.S_IMODE(os.lstat(_snap(world)).st_mode) == 0o700


def _head(size: int) -> Callable[..., Any]:
    def spawn(argv: list[str], **kwargs: Any) -> subprocess.Popen[bytes]:
        return subprocess.Popen(["/usr/bin/head", "-c", str(size), "/dev/zero"], **kwargs)

    return spawn


def test_write_oversize_stdout_is_recorded_empty_and_the_group_killed(
    world: SandboxRoots,
) -> None:
    began = time.monotonic()
    assert _write(world, runner=_head(40 * 1024 * 1024), clock=time.monotonic) == 0
    assert time.monotonic() - began < 8  # cut off at the cap, not read to the end
    (read,) = _written(world)["reads"]
    assert read["oversize"] is True and read["stdout"] == ""


def test_write_one_byte_over_the_limit_is_oversize(world: SandboxRoots) -> None:
    assert _write(world, runner=_head(4 * 1024 * 1024 + 1), clock=time.monotonic) == 0
    (read,) = _written(world)["reads"]
    assert read["oversize"] is True and read["stdout"] == ""


def test_write_exact_limit_stdout_is_kept(world: SandboxRoots) -> None:
    assert _write(world, runner=_head(4 * 1024 * 1024), clock=time.monotonic) == 0
    (read,) = _written(world)["reads"]
    assert read["oversize"] is False and len(read["stdout"]) == 4 * 1024 * 1024


def test_write_failed_read_is_recorded_and_exit_stays_zero(world: SandboxRoots) -> None:
    clock = Clock()
    status = _write(world, runner=Runner(clock, ("done", 1, b"")), clock=clock)
    assert status == 0
    (read,) = _written(world)["reads"]
    assert read["rc"] == 1 and read["timed_out"] is False


def test_write_missing_systemctl_is_a_recorded_failure_not_an_exit(world: SandboxRoots) -> None:
    def broken(argv: list[str], **kwargs: Any) -> Any:
        raise FileNotFoundError(errno.ENOENT, "no systemctl")

    assert _write(world, runner=broken) == 0
    (read,) = _written(world)["reads"]
    assert read["rc"] != 0 and read["stdout"] == ""


def test_write_creates_the_directory_0700_and_accepts_an_existing_one(
    world: SandboxRoots,
) -> None:
    assert _write(world) == 0
    assert _write(world, environ=_env(INVOCATION_ID=OTHER_INVOCATION)) == 0
    assert sorted(p.name for p in _snap(world).iterdir()) == [
        f"{INVOCATION}.json",
        f"{OTHER_INVOCATION}.json",
    ]


def test_write_refuses_to_overwrite_an_existing_snapshot_for_the_invocation(
    world: SandboxRoots,
) -> None:
    assert _write(world) == 0
    first = (_snap(world) / f"{INVOCATION}.json").read_bytes()
    assert _write(world) == 73
    assert (_snap(world) / f"{INVOCATION}.json").read_bytes() == first


# ------------------------------------------------------------------ write: the budget (M38)


def test_bus_snapshot_budget_below_outer_timeout_always_writes(world: SandboxRoots) -> None:
    clock = Clock()
    row = _row(_read("a"), _read("b"), _read("c"), budget=10)
    runner = Runner(clock, ("hang",))
    start = clock.now
    assert _write(world, row, runner=runner, clock=clock) == 0
    elapsed = clock.now - start
    assert elapsed <= 10 - 1.0 + 1e-9  # reads end 1 s before the deadline (drain is extra)
    reads = _written(world)["reads"]
    assert [r["name"] for r in reads] == ["a", "b", "c"]
    assert reads[0]["timed_out"] is True and reads[0]["skipped"] is False
    assert all(r["skipped"] for r in reads[1:])
    assert all(r["rc"] != 0 for r in reads)
    assert len(runner.calls) == 1  # skipped reads never spawn


def test_bus_snapshot_each_read_gets_at_most_ten_seconds_and_a_second_of_margin(
    world: SandboxRoots,
) -> None:
    clock = Clock()
    runner = Runner(clock, ("done", 0, b""))
    assert _write(world, _row(_read("a"), budget=25), runner=runner, clock=clock) == 0
    assert SIM.select_timeouts[0] == 10.0
    SIM.select_timeouts.clear()
    clock2 = Clock()
    runner2 = Runner(clock2, ("done", 0, b""))
    assert (
        _write(
            world,
            _row(_read("a"), budget=5),
            runner=runner2,
            clock=clock2,
            environ=_env(INVOCATION_ID=OTHER_INVOCATION),
        )
        == 0
    )
    assert SIM.select_timeouts[0] == 4.0


def test_bus_snapshot_read_with_under_half_a_second_left_is_skipped(world: SandboxRoots) -> None:
    clock = Clock()
    runner = Runner(clock, ("done", 0, b""))
    assert _write(world, _row(_read("a"), budget=1), runner=runner, clock=clock) == 0
    (read,) = _written(world)["reads"]
    assert read["skipped"] is True and not runner.calls


def test_bus_snapshot_hung_read_kills_process_group(
    world: SandboxRoots, killpg: list[tuple[int, int]]
) -> None:
    clock = Clock()
    runner = Runner(clock, ("hang",))
    assert _write(world, _row(_read("a"), budget=5), runner=runner, clock=clock) == 0
    assert killpg == [(4242, signal.SIGKILL)]
    assert SIM.select_timeouts == [4.0]  # the read; then a 1 s drain of the killed leader
    assert runner.procs[0].waits == [1.0]
    (read,) = _written(world)["reads"]
    assert read["timed_out"] is True


def test_bus_snapshot_hung_read_really_kills_a_grandchild(world: SandboxRoots) -> None:
    pidfile = world.home / "grandchild.pid"
    script = f"sleep 300 & echo $! > {pidfile}; wait"

    def spawn(argv: list[str], **kwargs: Any) -> subprocess.Popen[bytes]:
        return subprocess.Popen(["/bin/sh", "-c", script], **kwargs)

    began = time.monotonic()
    assert _write(world, _row(_read("a"), budget=3), runner=spawn, clock=time.monotonic) == 0
    assert time.monotonic() - began < 6
    grandchild = int(pidfile.read_text())
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        try:
            state = Path(f"/proc/{grandchild}/stat").read_text().rsplit(")", 1)[1].split()[0]
        except FileNotFoundError:
            break
        if state == "Z":
            break
        time.sleep(0.05)
    else:
        os.kill(grandchild, signal.SIGKILL)
        pytest.fail("the hung read's grandchild survived the process-group kill")
    (read,) = _written(world)["reads"]
    assert read["timed_out"] is True


# ------------------------------------------------------------------ write: the directory (M41)


def test_bus_snapshot_dir_symlink_refused_writes_nothing_and_sweeps_nothing(
    world: SandboxRoots, tmp_path: Path
) -> None:
    target = tmp_path / "elsewhere"
    target.mkdir(mode=0o700)
    victim = target / _hex_name("a")
    victim.write_text("keep")
    _age(victim, OLD_AGE_S)
    (_bind(world) / SNAP_DIR).symlink_to(target)
    runner = Runner(Clock())
    assert _write(world, runner=runner) == 78
    assert sorted(p.name for p in target.iterdir()) == [victim.name]
    assert victim.read_text() == "keep"
    assert not runner.calls


def test_bus_snapshot_dir_that_is_a_file_is_refused(world: SandboxRoots) -> None:
    (_bind(world) / SNAP_DIR).write_text("not a dir")
    runner = Runner(Clock())
    assert _write(world, runner=runner) == 78
    assert not runner.calls


@pytest.mark.parametrize("mode", [0o755, 0o750, 0o707, 0o770])
def test_bus_snapshot_dir_owner_mode_device_and_forbidden_inode_refused(
    world: SandboxRoots, mode: int
) -> None:
    snap = _snap(world)
    snap.mkdir()
    snap.chmod(mode)
    runner = Runner(Clock())
    assert _write(world, runner=runner) == 78
    assert not runner.calls and list(snap.iterdir()) == []


def test_bus_snapshot_dir_other_owner_refused(
    world: SandboxRoots, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(os, "geteuid", lambda: os.getuid() + 1)
    runner = Runner(Clock())
    assert _write(world, runner=runner) == 78
    assert not runner.calls and not list(_snap(world).iterdir())


def test_bus_snapshot_dir_on_another_device_refused(
    world: SandboxRoots, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = os.fstat

    def other_device(fd: int) -> os.stat_result:
        st = real(fd)
        if stat.S_ISDIR(st.st_mode) and (st.st_mode & 0o777) == 0o700 and _is_snapshot_fd(fd):
            values = list(st)
            values[stat.ST_DEV] = st.st_dev + 1
            return os.stat_result(values)
        return st

    def _is_snapshot_fd(fd: int) -> bool:
        try:
            return os.readlink(f"/proc/self/fd/{fd}").endswith(SNAP_DIR)
        except OSError:
            return False

    monkeypatch.setattr(os, "fstat", other_device)
    runner = Runner(Clock())
    assert _write(world, runner=runner) == 78
    assert not runner.calls and not list(_snap(world).iterdir())


def test_bus_snapshot_dir_forbidden_inode_refused(
    world: SandboxRoots, monkeypatch: pytest.MonkeyPatch
) -> None:
    _snap(world).mkdir(mode=0o700)
    st = os.stat(_snap(world))
    monkeypatch.setattr(
        bus_handoff, "forbidden_dirs", lambda roots: frozenset({(st.st_dev, st.st_ino)})
    )
    runner = Runner(Clock())
    assert _write(world, runner=runner) == 78
    assert not runner.calls and not list(_snap(world).iterdir())


def test_bus_snapshot_opens_only_the_snapshot_bind(world: SandboxRoots) -> None:
    """AC-9.2: the mode needs ``bus_snapshot_bind`` alone; a row's other binds are not walked."""
    row = dataclasses.replace(ROW, binds=(*ROW.binds, "cache/does_not_exist"))
    assert _write(world, row) == 0
    assert (_snap(world) / f"{INVOCATION}.json").is_file()


def test_bus_snapshot_bind_not_among_the_binds_is_refused(world: SandboxRoots) -> None:
    row = dataclasses.replace(ROW, bus_snapshot_bind="cache/elsewhere")
    runner = Runner(Clock())
    assert _write(world, row, runner=runner) == 78
    assert not runner.calls


def test_bus_snapshot_bind_symlink_refused_by_the_bind_walk(
    world: SandboxRoots, tmp_path: Path
) -> None:
    real = tmp_path / "real"
    real.mkdir(mode=0o700)
    bind = _bind(world)
    bind.rmdir()
    bind.symlink_to(real)
    runner = Runner(Clock())
    assert _write(world, runner=runner) == 78
    assert not runner.calls and list(real.iterdir()) == []


# ------------------------------------------------------------------ write: the sweep


def test_bus_snapshot_sweep_deletes_only_matching_regular_files(
    world: SandboxRoots, tmp_path: Path
) -> None:
    snap = _snap(world)
    snap.mkdir(mode=0o700)
    doomed = snap / _hex_name("a")
    fresh = snap / _hex_name("b")
    short = snap / f"{'c' * 31}.json"
    upper = snap / f"{'D' * 32}.json"
    other = snap / "notes.json"
    suffixed = snap / f"{'e' * 32}.json.bak"
    adir = snap / _hex_name("f")
    link = snap / _hex_name("1")
    for path in (doomed, fresh, short, upper, other, suffixed):
        path.write_text("x")
    adir.mkdir()
    link.symlink_to(tmp_path)
    for path in (doomed, short, upper, other, suffixed, adir):
        _age(path, OLD_AGE_S)
    _age(link, OLD_AGE_S)
    _age(fresh, 3600)
    assert _write(world) == 0
    survivors = {p.name for p in snap.iterdir()}
    assert doomed.name not in survivors
    assert survivors == {
        fresh.name,
        short.name,
        upper.name,
        other.name,
        suffixed.name,
        adir.name,
        link.name,
        f"{INVOCATION}.json",
    }
    assert tmp_path.exists()


def test_bus_snapshot_sweep_contention_skips_sweep_not_write(world: SandboxRoots) -> None:
    snap = _snap(world)
    snap.mkdir(mode=0o700)
    old = snap / _hex_name("a")
    old.write_text("x")
    _age(old, OLD_AGE_S)
    holder = os.open(snap, os.O_RDONLY | os.O_DIRECTORY)
    try:
        fcntl.flock(holder, fcntl.LOCK_EX)
        assert _write(world) == 0
    finally:
        os.close(holder)
    assert (snap / f"{INVOCATION}.json").is_file()
    assert old.exists()  # swept by nobody: the sweep was skipped
    assert _write(world, environ=_env(INVOCATION_ID=OTHER_INVOCATION)) == 0
    assert not old.exists()  # the next uncontended run sweeps it


# ------------------------------------------------------------------ write: tokens and verbs


TEMPLATE_UNIT = "breezy-autonomy-failed@breezy-foo.service.service"


def _failed_row() -> BwrapRow:
    return _row(_read("failed", "--", "{instance}"), budget=10)


def test_bus_snapshot_instance_revalidated_and_double_dash(world: SandboxRoots) -> None:
    runner = Runner(Clock())
    assert _write(world, _failed_row(), runner=runner, unit=TEMPLATE_UNIT) == 0
    ((argv, _),) = runner.calls
    assert argv == [SYSTEMCTL, "--user", "show", "-p", "Id", "--", "breezy-foo.service"]
    doc = _written(world)
    assert doc["reads"][0]["argv"] == argv  # the substituted argv is what is recorded


@pytest.mark.parametrize(
    "unit",
    [
        "breezy-autonomy-failed@evil.service",
        "breezy-autonomy-failed@-oHost.service",
        "breezy-autonomy-failed@--user.service",
        "breezy-autonomy-selftest.service",
        "breezy-autonomy-failed@Breezy-x.service",
    ],
    ids=["no-prefix", "dash-o", "double-dash-word", "no-instance", "uppercase"],
)
def test_bus_snapshot_instance_that_is_not_a_unit_token_is_refused(
    world: SandboxRoots, unit: str
) -> None:
    runner = Runner(Clock())
    assert _write(world, _failed_row(), runner=runner, unit=unit) == 78
    assert not runner.calls and not list(_snap(world).glob("*.json"))


@pytest.mark.parametrize(
    "verb", ["kill", "start", "stop", "restart", "try-restart", "reset-failed"]
)
def test_bus_snapshot_refuses_every_state_changing_verb(world: SandboxRoots, verb: str) -> None:
    row = _row(BusRead("bad", (SYSTEMCTL, "--user", verb, "--", "breezy-x.service")))
    runner = Runner(Clock())
    assert _write(world, row, runner=runner) == 78
    assert not runner.calls and not list(_snap(world).glob("*.json"))


@pytest.mark.parametrize(
    "argv",
    [
        ("/usr/bin/systemd-run", "--user", "show", "--", "breezy-x.service"),
        (SYSTEMCTL, "--system", "show", "--", "breezy-x.service"),
        (SYSTEMCTL, "--user", "show", "-p", "Environment", "--", "breezy-x.service"),
        (SYSTEMCTL, "--user", "show", "--property=LoadCredential", "--", "breezy-x.service"),
        (SYSTEMCTL, "--user", "show", "--", "breezy-x.service", "-p", "Id"),
        (SYSTEMCTL, "--user", "show", "-p", "Id", "--", "not-breezy.service"),
    ],
    ids=["systemd-run", "system", "env-property", "credential-property", "option-after", "unit"],
)
def test_bus_snapshot_refuses_argv_outside_the_grammar_at_run_time(
    world: SandboxRoots, argv: tuple[str, ...]
) -> None:
    runner = Runner(Clock())
    assert _write(world, _row(BusRead("bad", argv)), runner=runner) == 78
    assert not runner.calls


def test_bus_snapshot_template_token_without_an_instance_is_refused(
    world: SandboxRoots,
) -> None:
    runner = Runner(Clock())
    assert _write(world, _failed_row(), runner=runner, unit=UNIT) == 78
    assert not runner.calls


# ------------------------------------------------------------------ write: the invocation check


@pytest.mark.parametrize(
    "invocation",
    [
        None,
        "",
        "abc",
        "A" * 32,
        "g" * 32,
        INVOCATION + "\n",
        INVOCATION + "0",
        "../" + INVOCATION[:29],
        INVOCATION[:-1] + "/",
    ],
    ids=["missing", "empty", "short", "upper", "nonhex", "newline", "long", "traversal", "slash"],
)
def test_write_refuses_a_bad_invocation_id_before_anything(
    world: SandboxRoots, invocation: str | None
) -> None:
    runner = Runner(Clock())
    environ = {} if invocation is None else {"INVOCATION_ID": invocation}
    assert _write(world, runner=runner, environ=environ) == 78
    assert not runner.calls and not _snap(world).exists()


def test_write_refuses_a_row_without_bus_reads_or_bind(world: SandboxRoots) -> None:
    runner = Runner(Clock())
    no_reads = dataclasses.replace(
        ROW, bus_reads=(), bus_snapshot_bind=None, bus_snapshot_budget_s=None
    )
    assert _write(world, no_reads, runner=runner) == 78
    assert not runner.calls and not _snap(world).exists()


def test_write_failure_returns_73_and_leaves_no_partial_file(
    world: SandboxRoots, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_write = os.write

    def failing(fd: int, data: bytes) -> int:
        if os.readlink(f"/proc/self/fd/{fd}").endswith(".json"):
            raise OSError(errno.ENOSPC, "full")
        return real_write(fd, data)

    monkeypatch.setattr(os, "write", failing)
    assert _write(world) == 73
    assert list(_snap(world).glob("*.json")) == []


# ------------------------------------------------------------------ main: --bus-snapshot mode


class Spy:
    def __init__(self, status: int = 0) -> None:
        self.status = status
        self.calls: list[dict[str, Any]] = []

    def __call__(self, row: BwrapRow, **kwargs: Any) -> int:
        self.calls.append({"row": row, **kwargs})
        return self.status


class ExecSpy:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[str]]] = []

    def __call__(self, path: str, argv: list[str]) -> None:
        self.calls.append((path, argv))


def _cgroup(tmp_path: Path, leaf: str = UNIT) -> Path:
    path = tmp_path / "cgroup"
    path.write_text(f"0::/user.slice/user-1000.slice/user@1000.service/app.slice/{leaf}\n")
    return path


def _main(
    argv: list[str],
    world: SandboxRoots,
    tmp_path: Path,
    *,
    spy: Spy | None = None,
    execv: ExecSpy | None = None,
    leaf: str = UNIT,
    table: Mapping[str, BwrapRow] | None = None,
    environ: dict[str, str] | None = None,
) -> int:
    kwargs: dict[str, Any] = {}
    if spy is not None:
        kwargs["snapshot"] = spy
    return main(
        argv,
        roots=world,
        table=table if table is not None else AUTONOMY_BWRAP_TABLE,
        cgroup_path=_cgroup(tmp_path, leaf),
        execv=execv or ExecSpy(),
        environ=environ if environ is not None else _env(),
        **kwargs,
    )


def test_main_bus_snapshot_mode_calls_the_writer_once_and_never_execs(
    world: SandboxRoots, tmp_path: Path
) -> None:
    spy, execv = Spy(0), ExecSpy()
    assert _main(["--bus-snapshot", ROW_NAME], world, tmp_path, spy=spy, execv=execv) == 0
    (call,) = spy.calls
    assert call["row"] is ROW and call["roots"] is world and call["unit"] == UNIT
    assert call["environ"]["INVOCATION_ID"] == INVOCATION
    assert not execv.calls


def test_main_bus_snapshot_mode_returns_the_writers_status(
    world: SandboxRoots, tmp_path: Path
) -> None:
    assert _main(["--bus-snapshot", ROW_NAME], world, tmp_path, spy=Spy(73)) == 73


@pytest.mark.parametrize(
    "argv",
    [
        ["--bus-snapshot"],
        ["--bus-snapshot", "bad row"],
        ["--bus-snapshot", "Breezy-Upper"],
        ["--bus-snapshot", "breezy-x;rm"],
        ["--bus-snapshot", ROW_NAME, "/usr/bin/true"],
        ["--bus-snapshot", "--bus-snapshot"],
    ],
    ids=["no-row", "space", "upper", "semi", "extra-arg", "flag-as-row"],
)
def test_main_bus_snapshot_syntax_errors_exit_64_before_anything(
    argv: list[str], world: SandboxRoots, tmp_path: Path
) -> None:
    spy, execv = Spy(), ExecSpy()
    assert _main(argv, world, tmp_path, spy=spy, execv=execv) == 64
    assert not spy.calls and not execv.calls


def test_bus_snapshot_writes_only_after_all_checks_never_execv(
    world: SandboxRoots, tmp_path: Path
) -> None:
    bad_table = MappingProxyType({ROW_NAME: dataclasses.replace(ROW, bus_snapshot_budget_s=999)})
    notify = "breezy-autonomy-selftest-notify"
    cases: list[tuple[str, dict[str, Any]]] = [
        (ROW_NAME, {"table": bad_table}),
        ("breezy-no-such-row", {}),
        (notify, {"leaf": f"{notify}.service"}),  # a row without bus reads
        (ROW_NAME, {"leaf": "run-r1.service"}),
        (ROW_NAME, {"leaf": "breezy-other.service"}),
    ]
    for name, extra in cases:
        spy, execv = Spy(), ExecSpy()
        status = _main(["--bus-snapshot", name], world, tmp_path, spy=spy, execv=execv, **extra)
        assert status == 78, (name, extra)
        assert not spy.calls and not execv.calls, (name, extra)


def test_main_bus_snapshot_with_a_missing_cgroup_exits_78(
    world: SandboxRoots, tmp_path: Path
) -> None:
    spy = Spy()
    status = main(
        ["--bus-snapshot", ROW_NAME],
        roots=world,
        cgroup_path=tmp_path / "no-such-cgroup",
        execv=ExecSpy(),
        environ=_env(),
        snapshot=spy,
    )
    assert status == 78 and not spy.calls


def test_main_bus_snapshot_default_writer_is_the_real_one(
    world: SandboxRoots, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[str] = []

    def fake(row: BwrapRow, **kwargs: Any) -> int:
        seen.append(kwargs["unit"])
        return 0

    monkeypatch.setattr(bus_handoff, "write_bus_snapshot", fake)
    assert _main(["--bus-snapshot", ROW_NAME], world, tmp_path) == 0
    assert seen == [UNIT]


def test_main_bus_snapshot_reasons_never_print_a_path(
    world: SandboxRoots, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    runner_status = write_bus_snapshot(
        ROW, roots=world, environ={}, unit=UNIT, popen=Runner(Clock()), clock=Clock()
    )
    err = capsys.readouterr().err
    assert runner_status == 78
    assert err.strip() and "/" not in err.replace("breezy-autonomy-bwrap", "")
    assert str(world.home) not in err and str(tmp_path) not in err


# ------------------------------------------------------------------ read_bus_snapshot


def _doc(**changes: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "schema": "bus_snapshot/v1",
        "invocation_id": INVOCATION,
        "unit": UNIT,
        "ts_ns": time.time_ns(),
        "budget_s": 10,
        "reads": [
            {
                "name": "self_show",
                "argv": list(ROW.bus_reads[0].argv),
                "rc": 0,
                "timed_out": False,
                "skipped": False,
                "oversize": False,
                "stdout": "Id=x\n",
            }
        ],
    }
    doc.update(changes)
    return doc


def _plant(world: SandboxRoots, doc: Any, name: str | None = None) -> Path:
    snap = _snap(world)
    snap.mkdir(mode=0o700, exist_ok=True)
    path = snap / (name or f"{INVOCATION}.json")
    path.write_text(doc if isinstance(doc, str) else json.dumps(doc))
    return path


def test_read_bus_snapshot_returns_the_reads_and_consumes_the_file(world: SandboxRoots) -> None:
    path = _plant(world, _doc())
    snapshot = read_bus_snapshot(ROW, environ=_env(), roots=world)
    assert (snapshot.invocation_id, snapshot.unit, snapshot.budget_s) == (INVOCATION, UNIT, 10)
    (read,) = snapshot.reads
    assert (read.name, read.rc, read.stdout) == ("self_show", 0, "Id=x\n")
    assert (read.timed_out, read.skipped, read.oversize) == (False, False, False)
    assert not path.exists()
    with pytest.raises(BusSnapshotError) as again:
        read_bus_snapshot(ROW, environ=_env(), roots=world)
    assert again.value.code == "bus_snapshot_missing"


def test_read_bus_snapshot_round_trips_what_the_writer_wrote(world: SandboxRoots) -> None:
    clock = Clock()
    runner = Runner(clock, ("done", 0, b"Id=a\nActiveState=active\n"))
    assert _write(world, runner=runner, clock=clock) == 0
    (read,) = read_bus_snapshot(ROW, environ=_env(), roots=world).reads
    assert read.stdout == "Id=a\nActiveState=active\n"


def test_read_bus_snapshot_missing_raises_never_empty(world: SandboxRoots, tmp_path: Path) -> None:
    def missing(environ: Mapping[str, str] | None = None) -> None:
        with pytest.raises(BusSnapshotError) as info:
            read_bus_snapshot(ROW, environ=_env() if environ is None else environ, roots=world)
        assert info.value.code == "bus_snapshot_missing"

    missing()  # no directory
    missing({})  # no INVOCATION_ID
    missing({"INVOCATION_ID": "../x"})
    _snap(world).mkdir(mode=0o700)
    missing()  # no file
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / f"{INVOCATION}.json").write_text(json.dumps(_doc()))
    (_snap(world) / f"{INVOCATION}.json").symlink_to(elsewhere / f"{INVOCATION}.json")
    missing()  # a symlinked file is never followed
    assert (elsewhere / f"{INVOCATION}.json").exists()
    (_snap(world) / f"{INVOCATION}.json").unlink()
    _snap(world).rmdir()
    _snap(world).symlink_to(elsewhere)
    missing()  # a symlinked directory is never followed


@pytest.mark.parametrize(
    "doc",
    [
        _doc(invocation_id=OTHER_INVOCATION),
        _doc(unit="breezy-autonomy-selftest-notify.service"),
        _doc(schema="bus_snapshot/v0"),
        _doc(reads=[]),
        _doc(reads="nope"),
        _doc(reads=[{"name": "other", "rc": 0}]),
        "not json",
        "[]",
        "{}",
    ],
    ids=[
        "other-invocation",
        "other-unit",
        "schema",
        "no-reads",
        "reads-type",
        "read-names",
        "garbage",
        "list",
        "empty-object",
    ],
)
def test_read_bus_snapshot_forged_or_stale_documents_raise_stale_and_are_consumed(
    world: SandboxRoots, doc: Any
) -> None:
    path = _plant(world, doc)
    with pytest.raises(BusSnapshotError) as info:
        read_bus_snapshot(ROW, environ=_env(), roots=world)
    assert info.value.code == "bus_snapshot_stale"
    assert not path.exists()


def test_read_bus_snapshot_unit_template_row_matches_by_row(world: SandboxRoots) -> None:
    row = dataclasses.replace(_failed_row(), units=frozenset({"breezy-autonomy-failed@"}))
    doc = _doc(unit=TEMPLATE_UNIT)
    doc["reads"][0]["name"] = "failed"
    _plant(world, doc)
    snapshot = read_bus_snapshot(row, environ=_env(), roots=world)
    assert snapshot.unit == TEMPLATE_UNIT


# ------------------------------------------------------------------ the production runner (L-55)


def test_bus_handoff_production_default_runner_is_list_argv_popen_new_session(
    world: SandboxRoots,
) -> None:
    params = inspect.signature(write_bus_snapshot).parameters
    assert params["popen"].default is subprocess.Popen
    assert params["clock"].default is time.monotonic

    seen: list[tuple[Any, dict[str, Any]]] = []

    def spy(argv: Any, **kwargs: Any) -> Any:
        seen.append((argv, kwargs))
        return subprocess.Popen(["/bin/true"], **kwargs)

    assert _write(world, runner=spy) == 0
    ((argv, kwargs),) = seen
    assert isinstance(argv, list) and all(isinstance(token, str) for token in argv)
    assert kwargs["stdin"] is subprocess.DEVNULL
    assert kwargs["stdout"] is subprocess.PIPE
    assert kwargs["stderr"] is subprocess.DEVNULL
    assert kwargs["start_new_session"] is True and kwargs["close_fds"] is True
    assert not kwargs.get("shell")
    env = kwargs["env"]
    assert env == {
        "PATH": BUS_ENV_PATH,
        "XDG_RUNTIME_DIR": f"/run/user/{os.getuid()}",
        "LANG": "C.UTF-8",
        "SYSTEMD_PAGER": "",
        "SYSTEMD_COLORS": "0",
    }


def _code_facts(path: str) -> tuple[set[str], set[str], bool]:
    """Dotted attribute names, non-docstring string constants and any ``shell=True``."""
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef))
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
    }
    dotted: set[str] = set()
    strings: set[str] = set()
    shell = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            dotted.add(f"{node.value.id}.{node.attr}")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) not in docstrings:
                strings.add(node.value)
        elif isinstance(node, ast.keyword) and node.arg == "shell":
            shell = True
    return dotted, strings, shell


def test_bus_handoff_never_uses_run_shell_or_a_state_changing_call() -> None:
    dotted, strings, shell = _code_facts(bus_handoff.__file__)
    assert not shell
    assert dotted.isdisjoint(
        {
            "subprocess.run",
            "subprocess.call",
            "subprocess.check_call",
            "subprocess.check_output",
            "os.system",
            "os.popen",
            "os.execv",
            "os.execve",
            "os.execvp",
            "os.posix_spawn",
        }
    )
    assert strings.isdisjoint(
        {"kill", "start", "stop", "restart", "try-restart", "systemd-run", "--bus-action"}
    )
    assert "subprocess.Popen" in dotted  # positive control: the scan sees the real runner


def test_bwrap_module_keeps_the_bus_mode_free_of_execv_of_its_own() -> None:
    source = Path(bwrap.__file__).read_text(encoding="utf-8")
    assert "--bus-snapshot" in source


def test_snapshot_directory_and_names_are_the_planned_constants() -> None:
    assert bus_handoff.SNAPSHOT_DIR == SNAP_DIR
    assert bus_handoff.MAX_STDOUT_BYTES == 4 * 1024 * 1024
    assert bus_handoff.BUS_READ_TIMEOUT_S == 10
    assert bus_handoff.SWEEP_AGE_S == 24 * 3600


# ------------------------------------------------------------------ B9 rulings


def test_bus_snapshot_deadline_clock_starts_at_entry_to_write(
    world: SandboxRoots, monkeypatch: pytest.MonkeyPatch
) -> None:
    """B9-R3: time spent opening the bind and directory is charged to the budget."""
    clock = Clock()
    real = forbidden_dirs

    def slow_setup(roots: SandboxRoots) -> Any:
        clock.advance(8.0)  # a slow bind walk / directory check
        return real(roots)

    monkeypatch.setattr(bus_handoff, "forbidden_dirs", slow_setup)
    runner = Runner(clock, ("done", 0, b""))
    assert _write(world, _row(_read("a"), budget=10), runner=runner, clock=clock) == 0
    assert SIM.select_timeouts[0] == 1.0  # 10 - 8 - 1 margin, not 9


def _ts_doc(world: SandboxRoots, ts_ns: int) -> Path:
    return _plant(world, _doc(ts_ns=ts_ns))


def _read_at(world: SandboxRoots, now_ns: int) -> BusSnapshot:
    return read_bus_snapshot(ROW, environ=_env(), roots=world, now_ns=lambda: now_ns)


NOW_NS = 1_700_000_000 * 1_000_000_000
SEC = 1_000_000_000


@pytest.mark.parametrize(
    "ts_ns",
    [
        NOW_NS - (10 + 60) * SEC - 1,
        NOW_NS - 3600 * SEC,
        NOW_NS + 5 * SEC + 1,
        NOW_NS + 3600 * SEC,
        0,
        -1,
    ],
    ids=["just-too-old", "hour-old", "just-future", "hour-future", "zero", "negative"],
)
def test_read_bus_snapshot_ts_outside_bounds_is_stale_and_consumed(
    world: SandboxRoots, ts_ns: int
) -> None:
    path = _ts_doc(world, ts_ns)
    with pytest.raises(BusSnapshotError) as info:
        _read_at(world, NOW_NS)
    assert info.value.code == "bus_snapshot_stale"
    assert not path.exists()


@pytest.mark.parametrize(
    "ts_ns",
    [NOW_NS - (10 + 60) * SEC, NOW_NS - SEC, NOW_NS, NOW_NS + 5 * SEC],
    ids=["oldest", "past", "now", "newest"],
)
def test_read_bus_snapshot_ts_inside_bounds_is_accepted(world: SandboxRoots, ts_ns: int) -> None:
    _ts_doc(world, ts_ns)
    assert _read_at(world, NOW_NS).ts_ns == ts_ns


def test_read_bus_snapshot_ts_window_uses_the_rows_budget_not_the_documents(
    world: SandboxRoots,
) -> None:
    _plant(world, _doc(ts_ns=NOW_NS - 3600 * SEC, budget_s=10_000))
    with pytest.raises(BusSnapshotError) as info:
        _read_at(world, NOW_NS)
    assert info.value.code == "bus_snapshot_stale"


def test_read_bus_snapshot_fifo_is_missing_and_never_blocks(world: SandboxRoots) -> None:
    snap = _snap(world)
    snap.mkdir(mode=0o700)
    fifo = snap / f"{INVOCATION}.json"
    os.mkfifo(fifo)
    with pytest.raises(BusSnapshotError) as info:
        read_bus_snapshot(ROW, environ=_env(), roots=world)
    assert info.value.code == "bus_snapshot_missing"
    assert stat.S_ISFIFO(os.lstat(fifo).st_mode)


def test_read_bus_snapshot_document_cap_is_exact_and_read_in_chunks(
    world: SandboxRoots, monkeypatch: pytest.MonkeyPatch
) -> None:
    doc = json.dumps(_doc())
    size = len(doc.encode())
    monkeypatch.setattr(bus_handoff, "_READ_CHUNK", 64)  # many chunks, same answer
    monkeypatch.setattr(bus_handoff, "MAX_DOCUMENT_BYTES", size)
    _plant(world, doc)
    assert read_bus_snapshot(ROW, environ=_env(), roots=world).invocation_id == INVOCATION
    monkeypatch.setattr(bus_handoff, "MAX_DOCUMENT_BYTES", size - 1)
    path = _plant(world, doc)
    with pytest.raises(BusSnapshotError) as info:
        read_bus_snapshot(ROW, environ=_env(), roots=world)
    assert info.value.code == "bus_snapshot_stale"
    assert path.exists()  # refused before it was consumed: the cap stops the read


def _read_with(**changes: Any) -> dict[str, Any]:
    read = dict(_doc()["reads"][0])
    read.update(changes)
    return read


@pytest.mark.parametrize(
    "raw",
    [
        _read_with(rc=True),
        _read_with(rc="0"),
        _read_with(rc=0.0),
        _read_with(argv=[1, 2]),
        _read_with(argv="systemctl"),
        _read_with(argv=["ok", None]),
        _read_with(timed_out=1),
        _read_with(skipped="no"),
        _read_with(oversize=None),
        _read_with(stdout=5),
        _read_with(name=7),
        _read_with(extra="x"),
        {k: v for k, v in _read_with().items() if k != "stdout"},
        [],
        "self_show",
    ],
    ids=[
        "bool-rc",
        "str-rc",
        "float-rc",
        "int-argv",
        "str-argv",
        "none-in-argv",
        "int-flag",
        "str-flag",
        "none-flag",
        "int-stdout",
        "int-name",
        "extra-key",
        "missing-key",
        "list-read",
        "str-read",
    ],
)
def test_read_bus_snapshot_parse_read_is_type_strict(world: SandboxRoots, raw: Any) -> None:
    _plant(world, _doc(reads=[raw]))
    with pytest.raises(BusSnapshotError) as info:
        read_bus_snapshot(ROW, environ=_env(), roots=world)
    assert info.value.code == "bus_snapshot_stale"


@pytest.mark.parametrize("field", ["ts_ns", "budget_s"])
def test_read_bus_snapshot_bool_or_float_numbers_are_stale(world: SandboxRoots, field: str) -> None:
    for bad in (True, 1.5, "1"):
        _plant(world, _doc(**{field: bad}))
        with pytest.raises(BusSnapshotError) as info:
            read_bus_snapshot(ROW, environ=_env(), roots=world)
        assert info.value.code == "bus_snapshot_stale"


def test_read_bus_snapshot_hardlinked_snapshot_is_consumed_without_touching_the_other_link(
    world: SandboxRoots, tmp_path: Path
) -> None:
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps(_doc()))
    snap = _snap(world)
    snap.mkdir(mode=0o700)
    os.link(outside, snap / f"{INVOCATION}.json")
    assert read_bus_snapshot(ROW, environ=_env(), roots=world).invocation_id == INVOCATION
    assert not (snap / f"{INVOCATION}.json").exists()
    assert json.loads(outside.read_text())["invocation_id"] == INVOCATION  # intact


def test_bus_snapshot_sweep_unlinks_a_hardlinked_entry_without_touching_the_other_link(
    world: SandboxRoots, tmp_path: Path
) -> None:
    outside = tmp_path / "precious.txt"
    outside.write_text("precious")
    snap = _snap(world)
    snap.mkdir(mode=0o700)
    linked = snap / _hex_name("a")
    os.link(outside, linked)
    _age(outside, OLD_AGE_S)
    assert _write(world) == 0
    assert not linked.exists()
    assert outside.read_text() == "precious" and os.stat(outside).st_nlink == 1


def test_bus_snapshot_sweep_counts_skips_and_emits_one_reason_code(
    world: SandboxRoots, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """B9-R6: skipped sweep entries are counted and reported once; the exit stays 0."""
    snap = _snap(world)
    snap.mkdir(mode=0o700)
    stuck = [snap / _hex_name("a"), snap / _hex_name("b")]
    for path in stuck:
        path.write_text("x")
        _age(path, OLD_AGE_S)
    real_unlink = os.unlink

    def refuse(path: Any, *args: Any, **kwargs: Any) -> None:
        if str(path) in {p.name for p in stuck}:
            raise PermissionError(errno.EACCES, "no")
        real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(os, "unlink", refuse)
    assert _write(world) == 0
    err = capsys.readouterr().err
    assert err.count("sweep_skipped=") == 1 and "sweep_skipped=2" in err
    assert "/" not in err.replace("breezy-autonomy-bwrap", "")
    assert (snap / f"{INVOCATION}.json").is_file()


def test_bus_snapshot_clean_sweep_is_silent(
    world: SandboxRoots, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _write(world) == 0
    assert capsys.readouterr().err == ""


@pytest.mark.parametrize("pid", [0, 1, -1, -4242, "own-group"], ids=str)
def test_kill_group_refuses_pid_le_1_and_our_own_group(
    pid: Any, killpg: list[tuple[int, int]]
) -> None:
    bus_handoff._kill_group(os.getpgrp() if pid == "own-group" else pid)
    assert killpg == []


def test_kill_group_kills_an_ordinary_group(killpg: list[tuple[int, int]]) -> None:
    bus_handoff._kill_group(4242)
    assert killpg == [(4242, signal.SIGKILL)]


def test_writer_caps_the_total_document_size(
    world: SandboxRoots, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(bus_handoff, "MAX_DOCUMENT_BYTES", 2000)
    clock = Clock()
    big = b"z" * 1500
    row = _row(_read("a"), _read("b"), budget=20)
    assert _write(world, row, runner=Runner(clock, ("done", 0, big)), clock=clock) == 0
    path = _snap(world) / f"{INVOCATION}.json"
    assert path.stat().st_size <= 2000
    reads = _written(world)["reads"]
    assert all(r["oversize"] is True and r["stdout"] == "" for r in reads)
    assert [r.name for r in read_bus_snapshot(row, environ=_env(), roots=world).reads] == [
        "a",
        "b",
    ]
