"""The only subprocess site for phase-2 (real bubblewrap) tests (erratum E-7d, rule 5).

Every child a phase-2 test spawns goes through here, and every child gets
``--unshare-net`` and an explicit environment (nothing is inherited from the gate
process): no network and no egress attestation can reach it. ``run_in_row`` builds
the wrapper's own argv (``build_bwrap_argv`` over nofollow-validated bind fds and the
exact ``/run`` re-binds), so the namespace a test observes is the one the production
wrapper would make, with ``SandboxRoots`` substituted for the real home.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from collections.abc import Iterator, Mapping, Sequence
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Final

from breezy.runtime.autonomy_sandbox.binds import open_validated_binds
from breezy.runtime.autonomy_sandbox.bwrap import build_bwrap_argv
from breezy.runtime.autonomy_sandbox.run_mounts import close_run_rebinds, run_rebinds
from breezy.runtime.autonomy_sandbox.table import (
    AUTONOMY_BWRAP_TABLE,
    BwrapRow,
    SandboxRoots,
    validate_table,
)

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
DEFAULT_TIMEOUT_S: Final = 60.0
_DATA_ROOT_REL: Final = Path(".local") / "share" / "breezy"
#: Directories ``make_roots`` creates (mode 0700): the negatives the probe checks and one bind.
_ROOT_DIRS: Final = ("state", "registry", "cache/autonomy_selftest")
_PRIVATE_MODE: Final = 0o700

#: Run first in a child ``python -c`` so ``roots`` is the parent's ``SandboxRoots``
#: (passed as ``json`` in ``sys.argv[1]``).
CHILD_ROOTS_PRELUDE: Final = """
import json, os, sys
from pathlib import Path
from breezy.runtime.autonomy_sandbox.table import SandboxRoots
roots = SandboxRoots(**{k: (int(v) if k == "uid" else Path(v))
                        for k, v in json.loads(sys.argv[1]).items()})
"""


def run_raw_true() -> subprocess.CompletedProcess[str]:
    bwrap = shutil.which("bwrap")
    if bwrap is None:
        raise FileNotFoundError("bwrap")
    return subprocess.run(
        [
            bwrap,
            "--unshare-net",
            "--dev-bind",
            "/",
            "/",
            "/usr/bin/env",
            "-i",
            "PATH=/usr/bin:/bin",
            f"HOME={os.environ.get('HOME', '/tmp')}",
            "LANG=C.UTF-8",
            "/bin/true",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def run_host_read(
    command: Sequence[str], *, timeout: float = 30.0
) -> subprocess.CompletedProcess[str]:
    """Run one read-only host command (for example ``journalctl``) OUTSIDE any sandbox.

    The V-6 comparison needs the host's own answer next to the in-row one. It is a plain read: the
    caller names a fixed argv, nothing is written and no shell is involved.
    """
    return subprocess.run(
        list(command),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def make_roots(tmp_path: Path) -> SandboxRoots:
    """Scratch ``SandboxRoots`` under ``tmp_path``: a fake home holding a data root.

    The data root has ``state/``, ``registry/`` and ``cache/autonomy_selftest`` (every
    directory mode 0700, owned by the caller). The repo is the real checkout, so a child
    can import the package. ``run_user`` is a scratch directory the test fills.
    """
    home = tmp_path / "home"
    data_root = home / _DATA_ROOT_REL
    for rel in _ROOT_DIRS:
        (data_root / rel).mkdir(parents=True)
    run_user = tmp_path / "run-user"
    run_user.mkdir()
    for directory in (data_root, *(data_root / rel for rel in _ROOT_DIRS), run_user):
        directory.chmod(_PRIVATE_MODE)
    return SandboxRoots(
        home=home,
        data_root=data_root,
        repo_root=REPO_ROOT,
        python_prefix=Path(sys.base_prefix).resolve(),
        uid=os.getuid(),
        run_user=run_user,
    )


def roots_json(roots: SandboxRoots) -> str:
    """``roots`` for ``CHILD_ROOTS_PRELUDE`` (one JSON object of strings and the uid)."""
    return json.dumps(
        {
            "home": str(roots.home),
            "data_root": str(roots.data_root),
            "repo_root": str(roots.repo_root),
            "python_prefix": str(roots.python_prefix),
            "uid": roots.uid,
            "run_user": str(roots.run_user),
        }
    )


def _base_env(roots: SandboxRoots) -> dict[str, str]:
    return {"PATH": "/usr/bin:/bin", "HOME": str(roots.home), "LANG": "C.UTF-8"}


def _python_env_prefix() -> list[str]:
    """Python's own variables are set by ``env`` inside the sandbox, after the wrapper's
    host-environment scrub, so the child imports this checkout's package."""
    return [
        "/usr/bin/env",
        f"PYTHONPATH={REPO_ROOT / 'src'}",
        "PYTHONDONTWRITEBYTECODE=1",
    ]


@contextmanager
def spawn_in_row(
    row_name: str,
    command: Sequence[str],
    roots: SandboxRoots,
    *,
    table: Mapping[str, BwrapRow] = AUTONOMY_BWRAP_TABLE,
    env: Mapping[str, str] | None = None,
) -> Iterator[subprocess.Popen[str]]:
    """Start ``command`` in ``row_name``'s sandbox (no network); kill it on exit if still running.

    ``env`` adds to the three-variable base (for example ``NOTIFY_SOCKET`` or
    ``CREDENTIALS_DIRECTORY``); it is also what the wrapper's ``/run`` re-binds read.
    """
    bwrap = shutil.which("bwrap")
    if bwrap is None:
        raise FileNotFoundError("bwrap")
    validate_table(table)
    row = table[row_name]
    child_env = {**_base_env(roots), **(env or {})}
    with ExitStack() as stack:
        opened = stack.enter_context(open_validated_binds(row, roots))
        rebinds = run_rebinds(row, roots, child_env, unit=f"{row_name}.service")
        stack.callback(close_run_rebinds, rebinds)
        argv = build_bwrap_argv(
            row,
            [*_python_env_prefix(), *command],
            roots=roots,
            opened=opened,
            rebinds=rebinds,
            environ=child_env,
            cwd=str(roots.repo_root),
            bwrap_path=bwrap,
        )
        argv.insert(1, "--unshare-net")
        passed = [b.fd for b in (*opened.config_files, *opened.config_dirs, *opened.binds)]
        passed += [r.fd for r in rebinds if r.fd is not None]
        with subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=child_env,
            pass_fds=passed,
            close_fds=True,
        ) as proc:
            try:
                yield proc
            finally:
                if proc.poll() is None:
                    proc.kill()


def run_in_row(
    row_name: str,
    command: Sequence[str],
    roots: SandboxRoots,
    *,
    table: Mapping[str, BwrapRow] = AUTONOMY_BWRAP_TABLE,
    env: Mapping[str, str] | None = None,
    timeout: float = DEFAULT_TIMEOUT_S,
    stdin: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run ``command`` to completion in ``row_name``'s sandbox and return its result."""
    with spawn_in_row(row_name, command, roots, table=table, env=env) as proc:
        stdout, stderr = proc.communicate(input=stdin, timeout=timeout)
    return subprocess.CompletedProcess(proc.args, proc.returncode, stdout, stderr)
