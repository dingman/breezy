"""AUT-6 read-only closure lint, WP1 slice (plan r15 §3.1; E-7 rules 3 and 4; E-7a rule 4).

This reuses ``tests/support/capture_closure_lint.py`` (AUT-1's allowlist lint) with AUT-6's rows.
The single write scope of every WP1 entry point (redeliver, check, node sinks) is
``evidence/alerts/**``, and only ``alert_outbox`` holds the write sites that reach it. Every later
AUT-6 work package adds its entry point and its module rows here. The lint is a defence in depth:
each wrapped unit's bwrap row is the control.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

import pytest

from breezy.persistence.autonomy.detector_catalog import AUT6_WRITE_AUTHORITY
from tests.support.autonomy_scan import Finding
from tests.support.capture_closure_lint import AuthorityRow, lint_files, lint_source, module_of
from tests.support.entry_points import DEPLOY_SYSTEMD_DIR, SRC_DIR

_RUNTIME: Final = SRC_DIR / "breezy" / "runtime"
_ALERTS_WRITES: Final = "evidence/alerts/**"
_OUTBOX: Final = "breezy.runtime.alert_outbox"

#: Function scopes of ``alert_outbox`` that hold a filesystem write site. A new write function
#: needs a reviewed entry here. Every entry point below has ``evidence/alerts/**`` authority.
_OUTBOX_WRITE_SCOPES: Final[tuple[str, ...]] = (
    "_mkdir",
    "_publish",
    "AlertOutbox.claim",
    "AlertOutbox.restamp",
    "AlertOutbox.complete",
)

#: The WP1 modules the closure lint judges, with the minimum call sites each must hold.
AUT6_WP1_ROWS: Final[tuple[AuthorityRow, ...]] = (
    AuthorityRow(_OUTBOX, writes=_OUTBOX_WRITE_SCOPES, min_calls=50),
    AuthorityRow("breezy.runtime.alert_proof", min_calls=45),
    AuthorityRow("breezy.runtime.alert_drain", min_calls=32),
    AuthorityRow("breezy.runtime.alert_delivery", min_calls=12),
    AuthorityRow("breezy.runtime.alert_redeliver_cli", min_calls=22),
    AuthorityRow("breezy.runtime.check_alerts_cli", min_calls=24),
    AuthorityRow("breezy.persistence.autonomy.detector_catalog", min_calls=8),
)

#: Entry point (a key of ``AUT6_WRITE_AUTHORITY``) -> the WP1 modules in its closure.
AUT6_ENTRY_MODULES: Final[dict[str, tuple[str, ...]]] = {
    "breezy-autonomy-alert-redeliver": (
        "breezy.runtime.alert_redeliver_cli",
        "breezy.runtime.alert_delivery",
        "breezy.runtime.alert_drain",
        "breezy.runtime.alert_proof",
        _OUTBOX,
    ),
    "breezy-check-alerts": (
        "breezy.runtime.check_alerts_cli",
        "breezy.runtime.alert_delivery",
        "breezy.runtime.alert_proof",
        _OUTBOX,
    ),
    "node-sinks": (
        "breezy.runtime.alert_delivery",
        "breezy.runtime.alert_proof",
        _OUTBOX,
    ),
}


def _path_of(module: str) -> Path:
    return SRC_DIR.joinpath(*module.split(".")).with_suffix(".py")


def _findings(files: list[Path]) -> list[Finding]:
    return lint_files(files, AUT6_WP1_ROWS)


def _judged_files() -> list[Path]:
    return [_path_of(row.module) for row in AUT6_WP1_ROWS]


def test_aut6_closures_read_only_outside_one_writer_rows() -> None:
    files = _judged_files()
    assert all(path.is_file() for path in files)
    found = _findings(files)
    assert found == [], [(f.path, f.lineno, f.rule, f.detail) for f in found]


def test_aut6_only_the_outbox_module_holds_write_authority() -> None:
    with_writes = [row.module for row in AUT6_WP1_ROWS if row.writes]
    assert with_writes == [_OUTBOX]
    for row in AUT6_WP1_ROWS:
        assert row.argvs == () and row.sqlite == () and row.write_imports == frozenset(), row.module


def test_aut6_closure_entry_points_with_the_outbox_have_alerts_write_authority() -> None:
    for entry, modules in AUT6_ENTRY_MODULES.items():
        row = AUT6_WRITE_AUTHORITY[entry]
        assert row.writes == (_ALERTS_WRITES,), entry
        assert row.process_calls == (), entry
        assert {row.module for row in AUT6_WP1_ROWS} >= set(modules), entry


def test_aut6_write_authority_table_lists_every_aut6_unit() -> None:
    units = {
        path.name.removesuffix(".service").removesuffix(".timer")
        for path in DEPLOY_SYSTEMD_DIR.glob("breezy-autonomy-*")
        if path.suffix in {".service", ".timer"}
    }
    assert "breezy-autonomy-alert-redeliver" in units
    # the shared wrapper is a script, not a unit; AUT-5's engine rows are judged under AUT-5's table
    own = {unit for unit in units if not unit.startswith(("breezy-autonomy-bwrap",))}
    rows = {key.split("#")[0] for key in AUT6_WRITE_AUTHORITY}
    assert own <= rows
    for key, row in AUT6_WRITE_AUTHORITY.items():
        assert row.writes == tuple(sorted(set(row.writes), key=row.writes.index)), key
        assert all(not path.startswith(("/", "~")) for path in row.writes), key


def test_aut6_lint_is_non_vacuous_per_entry_point() -> None:
    """The M2 floor: an entry point whose closure judges no call sites cannot pass."""
    floors = {row.module: row.min_calls for row in AUT6_WP1_ROWS}
    for entry, modules in AUT6_ENTRY_MODULES.items():
        assert sum(floors[m] for m in modules) > 0, entry
    emptied = "X = 1\n"
    found = lint_source(
        "src/breezy/runtime/alert_proof.py",
        emptied,
        module="breezy.runtime.alert_proof",
        authority=AUT6_WP1_ROWS,
    )
    assert {f.rule for f in found} == {"aut1_vacuous"}


_PLANTED: Final[dict[str, str]] = {
    "write_mode_open": "def f(p):\n    open(p, 'w').close()\n",
    "sqlite_connect": "import sqlite3\ndef f(p):\n    sqlite3.connect(p)\n",
    "subprocess_call": "import subprocess\ndef f():\n    subprocess.run(['true'])\n",
    "os_system": "import os\ndef f():\n    os.system('true')\n",
    "unlink_outside_row": "import os\ndef f(p):\n    os.unlink(p)\n",
    "ctypes": "import ctypes\n",
}


@pytest.mark.parametrize("case", sorted(_PLANTED))
def test_aut6_closure_positive_control_planted_write_outside_a_row_fails(case: str) -> None:
    row = AuthorityRow("breezy.runtime.alert_planted", min_calls=0)
    found = lint_source(
        "src/breezy/runtime/alert_planted.py",
        _PLANTED[case],
        module="breezy.runtime.alert_planted",
        authority=(row,),
    )
    assert found, f"the lint did not fire on {case!r}"


def test_aut6_write_row_scope_is_a_function_not_the_whole_module() -> None:
    row = AuthorityRow("breezy.runtime.alert_planted", writes=("_publish",), min_calls=0)
    src = "import os\ndef _publish(p):\n    os.unlink(p)\ndef other(p):\n    os.unlink(p)\n"
    found = lint_source(
        "src/breezy/runtime/alert_planted.py",
        src,
        module="breezy.runtime.alert_planted",
        authority=(row,),
    )
    assert [f.scope for f in found] == ["other"]


def test_aut6_real_files_resolve_to_their_module_names() -> None:
    for row in AUT6_WP1_ROWS:
        assert module_of(_path_of(row.module)) == row.module
    assert _RUNTIME.is_dir()
