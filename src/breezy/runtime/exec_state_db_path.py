"""The ONE runtime resolver for ``POLYMARKET_US_EXEC_STATE_DB`` (R8/REVISE-1/2).

Three sites resolved this env var independently before this module existed:
``trade_supervisor.py`` (no path validation), ``clear_submit_intent_cli.py``
(no validation at all), and ``adapters.polymarket_us.factories`` (full
validation, echoes the value in its error messages). This module becomes the
ONE resolver for the two RUNTIME consumers -- :mod:`breezy.runtime.trade_supervisor`
and :mod:`breezy.runtime.clear_submit_intent_cli` import :func:`resolve_store_path`
and :class:`ExecStateDbNotConfiguredError` from here rather than each keeping
its own copy.

``adapters.polymarket_us.factories`` KEEPS its own copy, deliberately:
``adapters`` may not import ``runtime`` (the import-linter layers contract,
``pyproject.toml``, places ``runtime`` ABOVE ``adapters``, so that import
would be upward and forbidden). This is a known, LAYERED duplicate, stated
rather than hidden -- both implementations accept/reject the same set of
values (absolute path, no ``..`` segment), pinned by test.

Every message here names the env var and which rule failed, and NEVER the
value -- a deliberate divergence from ``factories.py``, whose messages echo
the offending path.

This module also carries the REVISE-1 node-env pre-flight
(:func:`node_store_path_check`): a value-free comparison of the scorer's (or
any same-uid consumer's) resolved path against the LIVE ``breezy-trade``
node's own environment, read from ``/proc``. Neither the expected nor the
actual path is ever returned, logged, or raised -- only one of four enum
outcomes: ``MATCH``, ``MISMATCH``, ``NO_NODE``, ``DISCOVERY_FAILED``.
"""

from __future__ import annotations

import os
import re
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Final, Literal

from breezy.adapters.polymarket_us.factories import EXEC_STATE_DB_ENV_VAR

__all__ = [
    "EXEC_STATE_DB_ENV_VAR",
    "ExecStateDbNotConfiguredError",
    "NodeStorePathCheckResult",
    "main",
    "node_store_path_check",
    "resolve_store_path",
]

NodeStorePathCheckResult = Literal["MATCH", "MISMATCH", "NO_NODE", "DISCOVERY_FAILED"]

#: Deliberately NOT ``trade_supervisor_core.NODE_ARGV_ANCHOR`` -- that
#: constant feeds a ``pgrep -f`` substring pattern, a different matching
#: semantic than this module's anchored basename match over a joined,
#: NUL-split ``/proc/<pid>/cmdline``. Matches the node's real joined argv
#: (``".../.venv/bin/breezy-trade"``, a single Popen argv element, see
#: ``trade_supervisor.py:506-507,973,90``) and never the supervisor's own
#: (``"...-supervisor-daily"``, ``trade_supervisor_core.py:52``).
_NODE_ARGV_PATTERN: Final[re.Pattern[str]] = re.compile(r"(^|/)breezy-trade$")

EXIT_OK: Final[int] = 0
EXIT_CONFIG_ERROR: Final[int] = 2
EXIT_MISMATCH: Final[int] = 3

_MATCH_OR_NO_NODE: Final[frozenset[str]] = frozenset({"MATCH", "NO_NODE"})


class ExecStateDbNotConfiguredError(RuntimeError):
    """The env var carrying the exec state-DB path is unset or invalid.

    The message names :data:`EXEC_STATE_DB_ENV_VAR` and which rule failed --
    unset, not absolute, or a ``..`` segment -- and NEVER the offending
    value.
    """


def resolve_store_path(environ: Mapping[str, str]) -> Path:
    """Resolve and validate the exec state-DB path from ``environ``.

    Applies the same two validations as
    ``adapters.polymarket_us.factories.exec_config_from_env`` (absolute, no
    ``..`` segment), so the runtime consumers cannot drift onto a path shape
    the adapter would reject at node build anyway. Unlike that function,
    this one never echoes the offending value in its error message.
    """
    raw = environ.get(EXEC_STATE_DB_ENV_VAR, "").strip()
    if not raw:
        raise ExecStateDbNotConfiguredError(f"{EXEC_STATE_DB_ENV_VAR} is unset and has no default")
    path = Path(raw)
    if not path.is_absolute():
        raise ExecStateDbNotConfiguredError(f"{EXEC_STATE_DB_ENV_VAR} must be an absolute path")
    if any(part == ".." for part in path.parts):
        raise ExecStateDbNotConfiguredError(
            f"{EXEC_STATE_DB_ENV_VAR} must not contain a '..' segment"
        )
    return path


class _CmdlineReadFailure(Exception):
    """A ``cmdline`` read failed for a reason other than a vanished pid.

    Raised for ``EACCES``/``EIO``-shaped errors (or, in tests, a directory
    standing in for the file) so :func:`node_store_path_check` can fail
    closed with ``DISCOVERY_FAILED`` instead of letting the exception
    escape. Carries no path or value -- the caller never needs one.
    """


def _read_cmdline(pid_dir: Path) -> str | None:
    """Return the joined argv, or ``None`` if the process vanished.

    Raises :class:`_CmdlineReadFailure` for any other ``OSError`` (e.g.
    ``PermissionError``/``EACCES``, ``EIO``) so the caller fails closed
    rather than letting the exception escape.
    """
    try:
        raw = (pid_dir / "cmdline").read_bytes()
    except (FileNotFoundError, ProcessLookupError):
        return None
    except OSError:
        raise _CmdlineReadFailure from None
    parts = raw.split(b"\0")
    if parts and parts[-1] == b"":
        parts = parts[:-1]
    return " ".join(part.decode("utf-8", errors="replace") for part in parts)


def _read_environ_value(pid_dir: Path, var: str) -> tuple[bool, str | None]:
    """Return ``(readable, value)``; ``value`` is ``None`` when absent."""
    try:
        raw = (pid_dir / "environ").read_bytes()
    except (FileNotFoundError, ProcessLookupError, PermissionError):
        return False, None
    prefix = var.encode("utf-8") + b"="
    for entry in raw.split(b"\0"):
        if entry.startswith(prefix):
            return True, entry[len(prefix) :].decode("utf-8", errors="replace")
    return True, None


def node_store_path_check(
    expected_path: Path, *, proc_root: Path = Path("/proc")
) -> NodeStorePathCheckResult:
    """Compare the running ``breezy-trade`` node's env value to ``expected_path``.

    Scans ``proc_root`` for numeric directories, reads each ``cmdline`` and
    matches the anchored ``breezy-trade`` basename pattern; for every match,
    reads ``environ`` and compares :data:`EXEC_STATE_DB_ENV_VAR` to
    ``expected_path`` (both resolved with :func:`os.path.realpath`). Never
    returns, logs, or raises either compared value -- only one of four enum
    outcomes.
    """
    try:
        pid_dirs = [entry for entry in proc_root.iterdir() if entry.name.isdigit()]
    except OSError:
        return "DISCOVERY_FAILED"

    expected_real = os.path.realpath(str(expected_path))
    matched_any = False
    mismatch = False

    for pid_dir in pid_dirs:
        try:
            cmdline = _read_cmdline(pid_dir)
        except _CmdlineReadFailure:
            return "DISCOVERY_FAILED"
        if cmdline is None:
            continue  # vanished between listing and read: a race, not a mismatch
        if not _NODE_ARGV_PATTERN.search(cmdline):
            continue
        matched_any = True
        readable, value = _read_environ_value(pid_dir, EXEC_STATE_DB_ENV_VAR)
        if not readable or value is None:
            mismatch = True
            continue
        if os.path.realpath(value) != expected_real:
            mismatch = True

    if not matched_any:
        return "NO_NODE"
    return "MISMATCH" if mismatch else "MATCH"


def main(
    argv: list[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    proc_root: Path = Path("/proc"),
) -> int:
    """``python -m breezy.runtime.exec_state_db_path --check`` entrypoint.

    Resolves the expected path via :func:`resolve_store_path`, then runs
    :func:`node_store_path_check` against it. Prints EXACTLY one token on
    stdout and nothing else: the enum result on success, or one value-free
    line on stderr naming the env var and the failed rule when it is
    unset/invalid. Exit codes: 0 on ``MATCH``/``NO_NODE``, 3 on
    ``MISMATCH``/``DISCOVERY_FAILED``, 2 when the var is unset/invalid.
    """
    args = sys.argv[1:] if argv is None else argv
    if args != ["--check"]:
        print("exec-state-db-path: usage: --check", file=sys.stderr)
        return EXIT_CONFIG_ERROR

    source = os.environ if environ is None else environ
    try:
        expected_path = resolve_store_path(source)
    except ExecStateDbNotConfiguredError as exc:
        print(f"exec-state-db-path: {exc}", file=sys.stderr)
        return EXIT_CONFIG_ERROR

    result = node_store_path_check(expected_path, proc_root=proc_root)
    print(result)
    return EXIT_OK if result in _MATCH_OR_NO_NODE else EXIT_MISMATCH


if __name__ == "__main__":
    raise SystemExit(main())
