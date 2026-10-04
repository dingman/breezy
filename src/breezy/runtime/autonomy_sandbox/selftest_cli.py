"""``python -I -m breezy.runtime.autonomy_sandbox.selftest_cli [--proc-checks]``.

The probe a human (or a unit) runs *inside* a wrapped row: it prints one JSON
document and exits 0 when ``run_self_probe`` held, 3 when it did not (the
integrity exit of the caller contract). Plan r5 V2 and V18.

``--proc-checks`` adds what a ``host_proc`` row is for: the host's ``/proc/locks``
line count, the answer to signalling another host process (``ESRCH``: it is outside
the pid namespace) and to reading its ``environ`` (``EACCES``), and the inode of the
re-bound studies lock, so the operator can compare them with the host's own view.

``--bus-snapshot`` (WP-B2c, V17/V21) reads the handed-over bus snapshot and reports, per
read, its exit status (or ``bus_snapshot_missing`` / ``bus_snapshot_stale`` when there is no
usable snapshot), plus ``in_row_systemctl`` (``failed``: the sandbox has no user bus).
``--exec-snapshot N`` (WP-B3, V10) takes N advisory snapshots (1..1000, ``take_flock=False``) of
the execution store into the row's ``cache/autonomy_selftest`` bind and reports the counts
as ``snap``: ``ok``, ``unstable`` and ``failed`` (a count per other failure reason). A bare
flag or a bad count is a usage error (64). Output carries names and counts only, never a path.
"""

from __future__ import annotations

import errno
import json
import os
import subprocess
import sys
from collections.abc import Callable, Collection, Mapping, Sequence
from pathlib import Path
from typing import Any, Final

from breezy.runtime.autonomy_sandbox.bus_handoff import (
    BusSnapshot,
    BusSnapshotError,
    bus_env,
    read_bus_snapshot,
)
from breezy.runtime.autonomy_sandbox.bwrap import ROW_VAR, default_roots
from breezy.runtime.autonomy_sandbox.run_mounts import STUDIES_LOCK_NAME
from breezy.runtime.autonomy_sandbox.self_probe import (
    DEFAULT_FS,
    ProbeFs,
    run_self_probe,
)
from breezy.runtime.autonomy_sandbox.table import (
    AUTONOMY_BWRAP_TABLE,
    NOTIFIER_FALLBACK_ROWS,
    BwrapRow,
    SandboxRoots,
)
from breezy.runtime.autonomy_sandbox.wal_snapshot import (
    SnapshotFailureReason,
    WalSnapshot,
    exec_snapshot,
)

EX_OK: Final = 0
EX_INTEGRITY: Final = 3
EX_USAGE: Final = 64
PROC_CHECKS_FLAG: Final = "--proc-checks"
BUS_SNAPSHOT_FLAG: Final = "--bus-snapshot"
EXEC_SNAPSHOT_FLAG: Final = "--exec-snapshot"
#: The selftest row's cache bind (``table.AUTONOMY_BWRAP_TABLE``): where the snapshots land.
EXEC_SNAPSHOT_BIND: Final = "cache/autonomy_selftest"
MAX_EXEC_SNAPSHOTS: Final = 1000
IN_ROW_SYSTEMCTL_TIMEOUT_S: Final = 10

ProcChecks = Callable[[BwrapRow, SandboxRoots, ProbeFs], dict[str, Any]]
BusReader = Callable[..., BusSnapshot]
SystemctlProbe = Callable[[BwrapRow], str]
ExecSnapshots = Callable[[int, SandboxRoots], dict[str, Any]]


def _errno_name(action: Callable[[], object]) -> str:
    try:
        action()
    except OSError as exc:
        return errno.errorcode.get(exc.errno or 0, "other")
    return "ok"


def _other_same_uid_pid(proc: Path, own: int) -> int | None:
    """The lowest host pid, other than ``own``, that this uid owns (a stable pick)."""
    for pid in sorted(int(name) for name in os.listdir(proc) if name.isdigit()):
        if pid == own:
            continue
        try:
            lines = (proc / str(pid) / "status").read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        uid_line = next((line for line in lines if line.startswith("Uid:")), "")
        if uid_line.split()[1:2] == [str(os.geteuid())]:
            return pid
    return None


def collect_proc_checks(row: BwrapRow, roots: SandboxRoots, fs: ProbeFs) -> dict[str, Any]:
    """The V18 observations. Only a ``host_proc`` row has a host procfs to observe."""
    if not row.host_proc:
        return {"skipped": "not_host_proc"}
    checks: dict[str, Any] = {
        "locks_lines": len((fs.proc / "locks").read_text(encoding="utf-8").splitlines())
    }
    target = _other_same_uid_pid(fs.proc, int(os.readlink(fs.proc / "self")))
    checks["target_found"] = target is not None
    if target is not None:
        checks["kill"] = _errno_name(lambda: os.kill(target, 0))
        checks["environ"] = _errno_name(
            lambda: (fs.proc / str(target) / "environ").read_bytes()[:1]
        )
    if row.studies_lock:
        st = os.stat(roots.run_user / STUDIES_LOCK_NAME)
        checks["lock_ino"], checks["lock_nlink"] = st.st_ino, st.st_nlink
    return checks


def in_row_systemctl(row: BwrapRow) -> str:
    """``failed`` when ``systemctl --user`` cannot reach a bus from inside the row, else ``ok``.

    A read-only ``show`` of the row's own unit; the sandbox has no user bus, so ``failed`` is
    the expected answer (V17).
    """
    argv = [
        "/usr/bin/systemctl",
        "--user",
        "show",
        "-p",
        "Id",
        "--",
        f"{row.name}.service",
    ]
    try:
        done = subprocess.run(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=bus_env(os.getuid()),
            timeout=IN_ROW_SYSTEMCTL_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return "failed"
    return "ok" if done.returncode == 0 else "failed"


def collect_bus_snapshot(
    row: BwrapRow,
    environ: Mapping[str, str],
    roots: SandboxRoots,
    reader: BusReader,
    systemctl: SystemctlProbe,
) -> dict[str, Any]:
    """The V17/V21 observations: each read's status, or why there is no snapshot."""
    if not row.bus_reads:
        return {"bus_snapshot": "not_a_bus_row"}
    try:
        snapshot = reader(row, environ=environ, roots=roots)
    except BusSnapshotError as exc:
        report: Any = exc.code
    else:
        report = {r.name: {"rc": r.rc} for r in snapshot.reads}
    return {"bus_snapshot": report, "in_row_systemctl": systemctl(row)}


def run_exec_snapshots(count: int, roots: SandboxRoots) -> dict[str, Any]:
    """``count`` advisory snapshots of the exec store into the selftest cache bind (V10)."""
    cache_dir = roots.data_root / EXEC_SNAPSHOT_BIND
    ok = unstable = 0
    failed: dict[str, int] = {}
    for _ in range(count):
        with exec_snapshot(
            cache_dir=cache_dir, take_flock=False, lock_path=None, data_root=roots.data_root
        ) as outcome:
            if isinstance(outcome, WalSnapshot):
                ok += 1
            elif outcome.reason is SnapshotFailureReason.FINGERPRINT_UNSTABLE:
                unstable += 1
            else:
                failed[outcome.reason.value] = failed.get(outcome.reason.value, 0) + 1
    return {"ok": ok, "unstable": unstable, "failed": dict(sorted(failed.items()))}


def _snapshot_count(text: str) -> int | None:
    """``text`` as a count in 1..``MAX_EXEC_SNAPSHOTS`` (ASCII digits only), else ``None``."""
    if not (text.isascii() and text.isdigit()):
        return None
    count = int(text)
    return count if 1 <= count <= MAX_EXEC_SNAPSHOTS else None


def _parse_args(args: Sequence[str]) -> tuple[set[str], int | None] | None:
    """The boolean flags and the ``--exec-snapshot`` count; ``None`` is a usage error."""
    flags: set[str] = set()
    count: int | None = None
    pending = iter(args)
    for arg in pending:
        if arg in (PROC_CHECKS_FLAG, BUS_SNAPSHOT_FLAG):
            flags.add(arg)
        elif arg == EXEC_SNAPSHOT_FLAG:
            count = _snapshot_count(next(pending, ""))
            if count is None:
                return None
        else:
            return None
    return flags, count


def main(
    argv: Sequence[str],
    *,
    roots: SandboxRoots | None = None,
    environ: Mapping[str, str] | None = None,
    fs: ProbeFs = DEFAULT_FS,
    table: Mapping[str, BwrapRow] = AUTONOMY_BWRAP_TABLE,
    fallback_rows: Collection[str] = NOTIFIER_FALLBACK_ROWS,
    proc_checks: ProcChecks = collect_proc_checks,
    bus_reader: BusReader = read_bus_snapshot,
    systemctl: SystemctlProbe = in_row_systemctl,
    exec_snapshots: ExecSnapshots = run_exec_snapshots,
) -> int:
    """Print the probe report for the row named by the sandbox environment; return the exit code."""
    parsed = _parse_args(argv)
    if parsed is None:
        sys.stderr.write(
            "selftest_cli: usage: selftest_cli [--proc-checks] [--bus-snapshot] "
            f"[--exec-snapshot 1..{MAX_EXEC_SNAPSHOTS}]\n"
        )
        return EX_USAGE
    flags, snapshot_count = parsed
    want_proc_checks = PROC_CHECKS_FLAG in flags
    want_bus_snapshot = BUS_SNAPSHOT_FLAG in flags
    env = os.environ if environ is None else environ
    use_roots = roots if roots is not None else default_roots()
    row_name = env.get(ROW_VAR)
    # A missing or unknown row is the probe's ``env_row`` failure, never a traceback.
    result = run_self_probe(
        row_name if row_name is not None and row_name in table else "",
        roots=use_roots,
        environ=env,
        fs=fs,
        table=table,
        fallback_rows=fallback_rows,
    )
    report: dict[str, Any] = {
        "ok": result.ok,
        "degraded": result.degraded,
        "failures": list(result.failures),
        "row": row_name,
        **result.facts,
    }
    if want_proc_checks and row_name is not None and row_name in table:
        report["proc_checks"] = proc_checks(table[row_name], use_roots, fs)
    if want_bus_snapshot and row_name is not None and row_name in table:
        report.update(collect_bus_snapshot(table[row_name], env, use_roots, bus_reader, systemctl))
    if snapshot_count is not None and row_name is not None and row_name in table:
        report["snap"] = exec_snapshots(snapshot_count, use_roots)
    sys.stdout.write(json.dumps(report, sort_keys=True) + "\n")
    return EX_OK if result.ok else EX_INTEGRITY


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
