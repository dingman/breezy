"""The shared bwrap wrapper's argv builder and entry point (plan r5, AC-1).

``deploy/systemd/breezy-autonomy-bwrap ROW CMD [ARGS...]`` checks, in this
order, and exits on the first failure::

    ROW syntax 64 -> validate_table 78 -> row 78 -> cgroup unit 78 -> binds 78
    -> run_rebinds 78 -> command 127/126 -> bwrap present -> notifier preflight
    -> execv

and only then ``os.execv("/usr/bin/bwrap", argv)`` -- a list, never a shell. Every
failure prints a reason *code* (never a path) to stderr. Fallback to an unwrapped
exec exists only for ``NOTIFIER_FALLBACK_ROWS`` (empty in seam B), only after every
64/78/126/127 check, and is announced to the child by
``BREEZY_AUTONOMY_SANDBOX_DEGRADED``.

The unit check is integrity against misconfiguration, not an authorisation
boundary. The wrapper never creates a bind source.

``breezy-autonomy-bwrap --bus-snapshot ROW`` (WP-B2c) is the one other mode: it runs
unsandboxed in ``ExecStartPre``, passes the same syntax (64), table, row and cgroup unit
checks (78) and then hands the bind to ``bus_handoff.write_bus_snapshot``. It never reaches
``os.execv``.
"""

from __future__ import annotations

import os
import pwd
import stat
import subprocess
import sys
from collections.abc import Callable, Mapping, MutableMapping, Sequence
from pathlib import Path
from typing import Final

from breezy.runtime.autonomy_sandbox.binds import (
    BindIntegrityError,
    OpenedBinds,
    bind_base_path,
    open_validated_binds,
)
from breezy.runtime.autonomy_sandbox.interp_links import (
    InterpreterLinkError,
    interpreter_symlinks,
)
from breezy.runtime.autonomy_sandbox.run_mounts import (
    RunRebind,
    close_run_rebinds,
    run_rebinds,
)
from breezy.runtime.autonomy_sandbox.table import (
    ALTERNATE_BIND_BASES,
    AUTONOMY_BWRAP_TABLE,
    DEFAULT_BIND_BASE,
    DEFAULT_TMPFS_SIZE_BYTES,
    MAX_TMPFS_SIZE_BYTES,
    NOTIFIER_FALLBACK_ROWS,
    ROW_NAME_RE,
    SANDBOX_UNSET_EXACT,
    SANDBOX_UNSET_PREFIXES,
    BwrapRow,
    SandboxRoots,
    TableError,
    unit_matches_row,
    validate_table,
)

BWRAP_PATH: Final = "/usr/bin/bwrap"
CGROUP_PATH: Final = Path("/proc/self/cgroup")
PROGRAM: Final = "breezy-autonomy-bwrap"
EX_USAGE: Final = 64
EX_CONFIG: Final = 78
EX_NOEXEC: Final = 126
EX_NOTFOUND: Final = 127
PREFLIGHT_TIMEOUT_S: Final = 2
PREFLIGHT_COMMAND: Final = "/bin/true"
DEGRADED_VAR: Final = "BREEZY_AUTONOMY_SANDBOX_DEGRADED"
ROW_VAR: Final = "BREEZY_AUTONOMY_BWRAP_ROW"
BUS_SNAPSHOT_FLAG: Final = "--bus-snapshot"
CREDENTIALS_DIRECTORY_VAR: Final = "CREDENTIALS_DIRECTORY"
DEFAULT_PATH: Final = "/usr/bin:/bin"
_CGROUP_V2_PREFIX: Final = "0::"
_SERVICE_SUFFIX: Final = ".service"
_NAMESPACE_FLAGS: Final = (
    "--unshare-user",
    "--disable-userns",
    "--assert-userns-disabled",
    "--unshare-pid",
    "--unshare-ipc",
    "--unshare-uts",
    "--unshare-cgroup-try",
)

Execv = Callable[[str, list[str]], object]
SnapshotWriter = Callable[..., int]


class WrapperError(Exception):
    """A wrapper refusal: ``code`` is the stderr reason, ``exit_status`` the exit code."""

    exit_status: int = EX_CONFIG

    def __init__(self, code: str, exit_status: int | None = None) -> None:
        super().__init__(code)
        self.code = code
        if exit_status is not None:
            self.exit_status = exit_status


class UnitCheckError(WrapperError):
    """The calling cgroup is not a unit the row lists (exit 78)."""


def current_unit_name(cgroup_text: str) -> str:
    """The ``.service`` leaf of the single ``0::<path>`` line, else ``UnitCheckError``."""
    paths = [
        line[len(_CGROUP_V2_PREFIX) :]
        for line in cgroup_text.splitlines()
        if line.startswith(_CGROUP_V2_PREFIX)
    ]
    if len(paths) != 1:
        raise UnitCheckError("cgroup_lines")
    leaf = paths[0].rstrip("/").rsplit("/", 1)[-1]
    if not leaf.endswith(_SERVICE_SUFFIX):
        raise UnitCheckError("cgroup_leaf")
    return leaf


def default_roots() -> SandboxRoots:
    """The production roots: the passwd home, its data root and this checkout."""
    uid = os.getuid()
    home = Path(pwd.getpwuid(uid).pw_dir)
    return SandboxRoots(
        home=home,
        data_root=home / ".local" / "share" / "breezy",
        repo_root=Path(__file__).resolve().parents[4],
        python_prefix=Path(sys.base_prefix).resolve(),
        uid=uid,
        run_user=Path(f"/run/user/{uid}"),
    )


def _tmpfs_size(row: BwrapRow) -> int:
    size = row.tmpfs_size_bytes
    if size is None:
        return DEFAULT_TMPFS_SIZE_BYTES
    if type(size) is not int or not 0 < size <= MAX_TMPFS_SIZE_BYTES:
        raise WrapperError("tmpfs_size")
    return size


def _row_base(row: BwrapRow, roots: SandboxRoots) -> Path:
    return bind_base_path(row, roots)


def _home_rebinds(row: BwrapRow, roots: SandboxRoots) -> list[Path]:
    paths = [roots.repo_root]
    if roots.python_prefix.is_relative_to(roots.home):
        paths.append(roots.python_prefix)
    paths.append(roots.data_root)
    if row.bind_base != DEFAULT_BIND_BASE:
        paths.append(roots.home / ALTERNATE_BIND_BASES[row.bind_base])
    return paths


def _chdir(row: BwrapRow, roots: SandboxRoots, cwd: str) -> str:
    if not cwd.startswith("/"):
        return "/"
    here = Path(os.path.normpath(cwd))
    for base in (roots.repo_root, _row_base(row, roots)):
        if here == base or here.is_relative_to(base):
            return str(here)
    return "/"


def interpreter_hops(
    row: BwrapRow, roots: SandboxRoots, opened: OpenedBinds
) -> tuple[tuple[str, str], ...]:
    """The interpreter symlink hops (B11-R1, B12-R4): excluded are every path the argv binds."""
    bound = [
        *_home_rebinds(row, roots),
        *(Path(f.path) for f in (*opened.config_files, *opened.config_dirs, *opened.binds)),
    ]
    try:
        return interpreter_symlinks(roots, bound)
    except InterpreterLinkError:
        raise WrapperError("interpreter_link") from None


def _symlink_args(hops: tuple[tuple[str, str], ...]) -> list[str]:
    """``--symlink`` for each hop; never a bind."""
    return [arg for link, target in hops for arg in ("--symlink", target, link)]


def _credential_setenv(row: BwrapRow, environ: Mapping[str, str]) -> list[str]:
    if not row.credential_env:
        return []
    directory = environ.get(CREDENTIALS_DIRECTORY_VAR)
    if not directory:
        raise WrapperError("credentials_directory")
    args: list[str] = []
    for var in sorted(row.credential_env):
        args += ["--setenv", var, f"{directory}/{row.credential_env[var]}"]
    return args


def _hostile_unsets(row: BwrapRow, environ: Mapping[str, str]) -> list[str]:
    """``--unsetenv`` for each denylisted host name present (B6-R8); notify rows keep the socket."""
    keep = {"NOTIFY_SOCKET"} if "E7A_R2_NOTIFY" in row.exceptions else set()
    names = sorted(
        name
        for name in environ
        if name not in keep
        and (name in SANDBOX_UNSET_EXACT or name.startswith(SANDBOX_UNSET_PREFIXES))
    )
    return [arg for name in names for arg in ("--unsetenv", name)]


def _rebind_args(rebind: RunRebind) -> list[str]:
    if rebind.fd is not None:
        return ["--ro-bind-fd", str(rebind.fd), rebind.dest]
    if rebind.src is None:
        raise WrapperError("rebind_shape")
    return ["--ro-bind", rebind.src, rebind.dest]


def build_bwrap_argv(
    row: BwrapRow,
    command: Sequence[str],
    *,
    roots: SandboxRoots,
    opened: OpenedBinds,
    rebinds: tuple[RunRebind, ...],
    environ: Mapping[str, str],
    cwd: str,
    bwrap_path: str = BWRAP_PATH,
    hops: tuple[tuple[str, str], ...] | None = None,
) -> list[str]:
    """The exact AC-1.3 argv for ``row`` (argv[0] is ``bwrap_path``). Pure; opens nothing."""
    home = str(roots.home)
    argv = [bwrap_path, *_NAMESPACE_FLAGS, "--ro-bind", "/", "/", "--tmpfs", "/run"]
    argv += ["--dev", "/dev"]
    if not row.host_proc:
        argv += ["--proc", "/proc"]
    argv += ["--size", str(_tmpfs_size(row)), "--tmpfs", "/tmp", "--tmpfs", home]
    for path in _home_rebinds(row, roots):
        argv += ["--ro-bind", str(path), str(path)]
    argv += _symlink_args(hops if hops is not None else interpreter_hops(row, roots, opened))
    for rebind in rebinds:
        argv += _rebind_args(rebind)
    argv += ["--remount-ro", "/run"]
    for config in (*opened.config_files, *opened.config_dirs):
        argv += ["--ro-bind-fd", str(config.fd), config.path]
    for bind in opened.binds:
        argv += ["--bind-fd", str(bind.fd), bind.path]
    argv += ["--remount-ro", home, "--new-session", "--die-with-parent"]
    argv += ["--chdir", _chdir(row, roots, cwd)]
    argv += ["--setenv", "TMPDIR", "/tmp", "--setenv", "XDG_CACHE_HOME", "/tmp/.cache"]
    argv += ["--setenv", ROW_VAR, row.name, "--unsetenv", DEGRADED_VAR]
    argv += _hostile_unsets(row, environ)
    argv += _credential_setenv(row, environ)
    return [*argv, "--", *command]


def _passed_fds(opened: OpenedBinds, rebinds: tuple[RunRebind, ...]) -> list[int]:
    fds = [b.fd for b in (*opened.config_files, *opened.config_dirs, *opened.binds)]
    return fds + [r.fd for r in rebinds if r.fd is not None]


def _resolve_command(command: str, environ: Mapping[str, str]) -> str:
    """Host-side ``execvp`` look-alike: exits 127 if absent, 126 if present but not runnable."""
    if "/" in command:
        candidates = [command]
    else:
        entries = environ.get("PATH", DEFAULT_PATH).split(":")
        candidates = [os.path.join(entry, command) for entry in entries if entry]
    present = False
    for candidate in candidates:
        try:
            mode = os.stat(candidate).st_mode
        except OSError:
            continue
        if not stat.S_ISREG(mode):
            if "/" in command:
                raise WrapperError("command_not_executable", EX_NOEXEC)
            continue
        if os.access(candidate, os.X_OK):
            return candidate
        present = True
    if present:
        raise WrapperError("command_not_executable", EX_NOEXEC)
    raise WrapperError("command_not_found", EX_NOTFOUND)


def _bwrap_present(bwrap_path: str) -> bool:
    return os.path.isfile(bwrap_path) and os.access(bwrap_path, os.X_OK)


def _preflight_failure(argv: list[str], passed: list[int]) -> str | None:
    """The degraded reason if the wrapped ``/bin/true`` does not run in 2 s, else ``None``."""
    try:
        done = subprocess.run(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            pass_fds=tuple(passed),
            timeout=PREFLIGHT_TIMEOUT_S,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return "preflight_timeout"
    except OSError:
        return "bwrap_missing"
    return None if done.returncode == 0 else f"preflight_rc_{done.returncode}"


def _exec_degraded(
    row: BwrapRow,
    resolved: str,
    command: Sequence[str],
    reason: str,
    env: MutableMapping[str, str],
    execv: Execv,
) -> int:
    # B7-R1: the row variable is what the self-probe checks first (``env_row``); without it a
    # genuine notifier-fallback run would report ``env_row`` instead of ``degraded``.
    env[ROW_VAR] = row.name
    env[DEGRADED_VAR] = reason
    execv(resolved, list(command))
    return 0


def _exec_wrapped(
    row: BwrapRow,
    command: Sequence[str],
    resolved: str,
    *,
    roots: SandboxRoots,
    opened: OpenedBinds,
    rebinds: tuple[RunRebind, ...],
    env: MutableMapping[str, str],
    bwrap_path: str,
    execv: Execv,
    degradable: bool,
) -> int:
    if not _bwrap_present(bwrap_path):
        if degradable:
            return _exec_degraded(row, resolved, command, "bwrap_missing", env, execv)
        raise WrapperError("bwrap_missing", EX_NOTFOUND)
    hops = interpreter_hops(row, roots, opened)
    passed = _passed_fds(opened, rebinds)

    def argv_for(cmd: Sequence[str]) -> list[str]:
        return build_bwrap_argv(
            row,
            cmd,
            roots=roots,
            opened=opened,
            rebinds=rebinds,
            environ=env,
            cwd=_cwd(),
            bwrap_path=bwrap_path,
            hops=hops,
        )

    if degradable:
        reason = _preflight_failure(argv_for((PREFLIGHT_COMMAND,)), passed)
        if reason is not None:
            return _exec_degraded(row, resolved, command, reason, env, execv)
    argv = argv_for(command)
    for fd in passed:
        os.set_inheritable(fd, True)
    try:
        execv(bwrap_path, argv)
    except OSError:
        raise WrapperError("exec_failed", EX_NOEXEC) from None
    return 0


def _cwd() -> str:
    try:
        return os.getcwd()
    except OSError:
        return "/"


def _read_unit(cgroup_path: Path, row: BwrapRow) -> str:
    try:
        text = cgroup_path.read_text()
    except (OSError, UnicodeDecodeError):
        raise UnitCheckError("cgroup_unreadable") from None
    leaf = current_unit_name(text)
    if not unit_matches_row(row, leaf):
        raise UnitCheckError("unit_not_in_row")
    return leaf


def _run_bus_snapshot(
    argv: Sequence[str],
    *,
    roots: SandboxRoots | None,
    table: Mapping[str, BwrapRow],
    cgroup_path: Path,
    env: MutableMapping[str, str],
    snapshot: SnapshotWriter | None,
) -> int:
    """``--bus-snapshot ROW``: every check passes before the writer is reached; no ``execv``."""
    if len(argv) != 2 or not ROW_NAME_RE.fullmatch(argv[1]):
        raise WrapperError("usage", EX_USAGE)
    try:
        validate_table(table)
    except TableError:
        raise WrapperError("table_invalid") from None
    row = table.get(argv[1])
    if row is None:
        raise WrapperError("unknown_row")
    if not row.bus_reads:
        raise WrapperError("not_a_bus_row")
    leaf = _read_unit(cgroup_path, row)
    use_roots = roots if roots is not None else default_roots()
    if snapshot is None:
        from breezy.runtime.autonomy_sandbox import bus_handoff

        snapshot = bus_handoff.write_bus_snapshot
    return snapshot(row, roots=use_roots, environ=env, unit=leaf)


def _run(
    argv: Sequence[str],
    *,
    roots: SandboxRoots | None,
    table: Mapping[str, BwrapRow],
    cgroup_path: Path,
    bwrap_path: str,
    execv: Execv,
    env: MutableMapping[str, str],
    fallback_rows: frozenset[str],
    snapshot: SnapshotWriter | None = None,
) -> int:
    if argv and argv[0] == BUS_SNAPSHOT_FLAG:
        return _run_bus_snapshot(
            argv, roots=roots, table=table, cgroup_path=cgroup_path, env=env, snapshot=snapshot
        )
    if len(argv) < 2 or not ROW_NAME_RE.fullmatch(argv[0]):
        raise WrapperError("usage", EX_USAGE)
    name, command = argv[0], list(argv[1:])
    try:
        validate_table(table)
    except TableError:
        raise WrapperError("table_invalid") from None
    row = table.get(name)
    if row is None:
        raise WrapperError("unknown_row")
    leaf = _read_unit(cgroup_path, row)
    use_roots = roots if roots is not None else default_roots()
    with open_validated_binds(row, use_roots) as opened:
        rebinds = run_rebinds(row, use_roots, env, unit=leaf)
        try:
            resolved = _resolve_command(command[0], env)
            return _exec_wrapped(
                row,
                command,
                resolved,
                roots=use_roots,
                opened=opened,
                rebinds=rebinds,
                env=env,
                bwrap_path=bwrap_path,
                execv=execv,
                degradable=name in fallback_rows,
            )
        finally:
            close_run_rebinds(rebinds)


def main(
    argv: Sequence[str],
    *,
    roots: SandboxRoots | None = None,
    table: Mapping[str, BwrapRow] = AUTONOMY_BWRAP_TABLE,
    cgroup_path: Path = CGROUP_PATH,
    bwrap_path: str = BWRAP_PATH,
    execv: Execv = os.execv,
    environ: MutableMapping[str, str] | None = None,
    fallback_rows: frozenset[str] = NOTIFIER_FALLBACK_ROWS,
    snapshot: SnapshotWriter | None = None,
) -> int:
    """Run the wrapper for ``argv`` (``ROW CMD [ARGS...]`` or ``--bus-snapshot ROW``).

    Returns the process exit status.

    Real ``execv`` never returns. Everything injectable here exists so a test can run every
    refusal without a sandbox: ``roots``, ``table``, ``cgroup_path``, ``bwrap_path``,
    ``execv``, ``environ``, ``fallback_rows`` and ``snapshot`` (the ``--bus-snapshot`` writer).
    """
    env = os.environ if environ is None else environ
    try:
        return _run(
            argv,
            roots=roots,
            table=table,
            cgroup_path=cgroup_path,
            bwrap_path=bwrap_path,
            execv=execv,
            env=env,
            fallback_rows=fallback_rows,
            snapshot=snapshot,
        )
    except BindIntegrityError as exc:
        status, code = exc.exit_status, exc.code
    except WrapperError as exc:
        status, code = exc.exit_status, exc.code
    except Exception:  # noqa: BLE001 - the reason code is the whole report, never a traceback
        status, code = EX_CONFIG, "internal"
    sys.stderr.write(f"{PROGRAM}: refused: {code}\n")
    return status
