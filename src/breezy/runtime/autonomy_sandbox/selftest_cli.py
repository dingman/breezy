"""``python -I -m breezy.runtime.autonomy_sandbox.selftest_cli [--proc-checks]``.

The probe a human (or a unit) runs *inside* a wrapped row: it prints one JSON
document and exits 0 when ``run_self_probe`` held, 3 when it did not (the
integrity exit of the caller contract). Plan r5 V2 and V18.

``--proc-checks`` adds what a ``host_proc`` row is for: the host's ``/proc/locks``
line count, the answer to signalling another host process (``ESRCH``: it is outside
the pid namespace) and to reading its ``environ`` (``EACCES``), and the inode of the
re-bound studies lock, so the operator can compare them with the host's own view.

``--bus-snapshot`` (WP-B2c) and ``--exec-snapshot`` (WP-B3) are not landed yet and are
usage errors (64). Output carries names and counts only, never a path.
"""

from __future__ import annotations

import errno
import json
import os
import sys
from collections.abc import Callable, Collection, Mapping, Sequence
from pathlib import Path
from typing import Any, Final

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

EX_OK: Final = 0
EX_INTEGRITY: Final = 3
EX_USAGE: Final = 64
PROC_CHECKS_FLAG: Final = "--proc-checks"

ProcChecks = Callable[[BwrapRow, SandboxRoots, ProbeFs], dict[str, Any]]


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


def main(
    argv: Sequence[str],
    *,
    roots: SandboxRoots | None = None,
    environ: Mapping[str, str] | None = None,
    fs: ProbeFs = DEFAULT_FS,
    table: Mapping[str, BwrapRow] = AUTONOMY_BWRAP_TABLE,
    fallback_rows: Collection[str] = NOTIFIER_FALLBACK_ROWS,
    proc_checks: ProcChecks = collect_proc_checks,
) -> int:
    """Print the probe report for the row named by the sandbox environment; return the exit code."""
    args = list(argv)
    want_proc_checks = PROC_CHECKS_FLAG in args
    if [a for a in args if a != PROC_CHECKS_FLAG]:
        sys.stderr.write("selftest_cli: usage: selftest_cli [--proc-checks]\n")
        return EX_USAGE
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
    sys.stdout.write(json.dumps(report, sort_keys=True) + "\n")
    return EX_OK if result.ok else EX_INTEGRITY


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
