"""AUT-6 WP1 bwrap rows (plan r15 §3.1.1; E-7a; E-15), unit half.

The real-namespace half is ``tests/integration/test_aut6_bwrap_rows.py`` (gate phase 2). WP1 owns
one row, ``breezy-autonomy-alert-redeliver``; every later AUT-6 work package adds its row here.
"""

from __future__ import annotations

import ast
import shlex
from pathlib import Path
from typing import Final

import pytest

from breezy.runtime.autonomy_sandbox.binds import OpenedBind, OpenedBinds
from breezy.runtime.autonomy_sandbox.bwrap import build_bwrap_argv
from breezy.runtime.autonomy_sandbox.table import AUTONOMY_BWRAP_TABLE, BwrapRow, SandboxRoots
from breezy.runtime.autonomy_sandbox.unit_lint import WRAPPER_PATH, parse_unit
from tests.support.entry_points import DEPLOY_SYSTEMD_DIR, SRC_DIR

ROW: Final = "breezy-autonomy-alert-redeliver"
#: AUT-6 rows and their exact bind sets (§3.1.1). Rows with ``host_proc`` are the named
#: ``--unshare-pid`` exceptions; the health row (WP3 S2) is the only one.
CANARY_ROW: Final = "breezy-autonomy-canary"  # AUT-6 WP2
HEALTH_ROW: Final = "breezy-autonomy-health"  # AUT-6 WP3 S2 (E7A_R2_PROC, network none)
AUT6_ROWS: Final[dict[str, tuple[str, ...]]] = {
    ROW: ("evidence/alerts",),
    CANARY_ROW: ("evidence/alerts",),
    HEALTH_ROW: (
        "evidence/unit_health",
        "derived/verdicts",
        "evidence/alerts",
        "cache/aut6_health_bus",
    ),
}
AUT6_PROC_EXCEPTION_ROWS: Final[frozenset[str]] = frozenset({HEALTH_ROW})
ROOTS: Final = SandboxRoots(
    home=Path("/home/u"),
    data_root=Path("/home/u/.local/share/breezy"),
    repo_root=Path("/home/u/repo"),
    python_prefix=Path("/home/u/py"),
    uid=1000,
    run_user=Path("/run/user/1000"),
)
_CLOSURE: Final = (
    "runtime/alert_redeliver_cli",
    "runtime/autonomy_canary_cli",
    "runtime/alert_delivery",
    "runtime/alert_drain",
    "runtime/alert_proof",
    "runtime/alert_outbox",
)


def _argv(row: BwrapRow) -> list[str]:
    binds = tuple(
        OpenedBind(rel, f"/home/u/.local/share/breezy/{rel}", 100 + i, 1, 100 + i)
        for i, rel in enumerate(row.binds)
    )
    return build_bwrap_argv(
        row,
        ("/usr/bin/true",),
        roots=ROOTS,
        opened=OpenedBinds(binds=binds, config_files=(), config_dirs=()),
        rebinds=(),
        environ={},
        cwd="/",
    )


def _exec_row_name(unit_file: Path) -> str:
    unit = parse_unit(unit_file.read_text(encoding="utf-8"))
    (line,) = unit.values("Service", "ExecStart")
    tokens = shlex.split(line)
    return tokens[tokens.index(WRAPPER_PATH) + 1]


def test_every_aut6_unit_execstart_and_onfailure_target_goes_through_wrapper() -> None:
    for row_name in AUT6_ROWS:
        unit_file = DEPLOY_SYSTEMD_DIR / f"{row_name}.service"
        assert unit_file.is_file(), row_name
        name = _exec_row_name(unit_file)
        assert name == row_name and name.startswith(unit_file.stem)
        assert f"{row_name}.service" in AUTONOMY_BWRAP_TABLE[name].units
        unit = parse_unit(unit_file.read_text(encoding="utf-8"))
        # X-3: the notifier row does not exist yet (WP4/WP7); the target is named, the gap recorded
        # by the contract test that pins the unit lint's one ``onfailure_scope`` error.
        targets = " ".join(unit.values("Unit", "OnFailure")).split()
        assert [t.split("%")[0] for t in targets] == ["breezy-autonomy-failed@"]
        assert not any("breezy-autonomy-failed@" in r.units for r in AUTONOMY_BWRAP_TABLE.values())


def test_aut6_bwrap_rows_exact_binds_and_unshare_pid_exceptions() -> None:
    for name, binds in AUT6_ROWS.items():
        row = AUTONOMY_BWRAP_TABLE[name]
        assert row.binds == binds, name
        assert row.host_proc is (name in AUT6_PROC_EXCEPTION_ROWS), name
        argv = _argv(row)
        # The shipped wrapper always unshares the pid namespace; a ``host_proc`` row (E7A_R2_PROC)
        # differs by not mounting a fresh ``/proc``, so the read-only root's host procfs stays
        # (V-6: a host pid's /proc/<pid>/status is readable in-row). Every other row gets both.
        assert "--unshare-pid" in argv, name
        assert ("--proc" in argv) is (name not in AUT6_PROC_EXCEPTION_ROWS), name
        # egress rows keep the host network; a network-none row (health) unshares it
        assert ("--unshare-net" in argv) is (row.network == "none"), name
        assert row.credential_names == () and row.credential_env == {}


def test_aut6_proc_consumers_rows_drop_unshare_pid() -> None:
    """E-7a rule 2: a closure that reads /proc must sit in a row that drops --unshare-pid."""
    for module in _CLOSURE:
        text = (SRC_DIR / "breezy" / f"{module}.py").read_text(encoding="utf-8")
        assert "/proc/" not in text, module
    planted = 'LOCKS = "/proc/locks"\n'
    assert "/proc/" in planted and ROW not in AUT6_PROC_EXCEPTION_ROWS


def _lock_open_calls(source: str) -> list[ast.Call]:
    tree = ast.parse(source)
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "open"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "os"
        and node.args
        and "lock" in ast.unparse(node.args[0])
    ]


def test_aut6_lock_files_opened_rdonly_and_missing_is_integrity() -> None:
    source = (SRC_DIR / "breezy" / "runtime" / "alert_redeliver_cli.py").read_text(encoding="utf-8")
    (call,) = _lock_open_calls(source)
    assert ast.unparse(call.args[1]) == "os.O_RDONLY | os.O_CLOEXEC"
    assert "INTEGRITY lock_file_missing" in source
    assert "return 3" in source
    assert '".redeliver.lock"' in source


@pytest.mark.parametrize(
    "flags", ["os.O_RDWR", "os.O_RDONLY | os.O_CREAT", "os.O_WRONLY | os.O_CLOEXEC"]
)
def test_aut6_lock_open_check_fires_on_a_writable_or_creating_open(flags: str) -> None:
    (call,) = _lock_open_calls(f"import os\nfd = os.open(lock_path, {flags})\n")
    assert ast.unparse(call.args[1]) != "os.O_RDONLY | os.O_CLOEXEC"
