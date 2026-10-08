"""AUT-1 WP3 step 1: the ``breezy-quote-tape.stop-hook`` sandbox row (r12 section 3.10.2, E-7a).

The row binds only the stall-record and health directories, needs no bus read (the bus-snapshot
handoff replaced in-row systemctl, WP0-R1), no DNS and no credential, and is linted at its
wrapper lines only: the recorder's own ``ExecStart`` stays unwrapped (the rule-5 residual).
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from types import MappingProxyType

import pytest

from breezy.runtime.autonomy_sandbox.table import (
    AUTONOMY_BWRAP_TABLE,
    WRAPPER_LINE_ONLY_UNITS,
    TableError,
    effective_line_only_units,
    unit_matches_row,
    validate_table,
)
from breezy.runtime.autonomy_sandbox.unit_lint import WRAPPER_PATH, lint_units

ROW = "breezy-quote-tape.stop-hook"
UNIT = "breezy-quote-tape.service"
REPO_ROOT = Path(__file__).resolve().parents[2]


def test_row_shape() -> None:
    row = AUTONOMY_BWRAP_TABLE[ROW]
    assert row.owner_plan == "AUT-1"
    assert row.units == frozenset({UNIT})
    assert row.binds == ("evidence/capture/stall", "health/recorder_watchdog")
    assert row.entry_modules == ("breezy.runtime.capture_recorder_hook_cli",)
    assert row.resolves_dns is False and row.network == "none"
    assert row.bus_reads == () and row.bus_snapshot_bind is None
    assert row.exceptions == frozenset()
    assert row.credential_names == () and not row.host_proc and not row.studies_lock
    assert not any(bind.startswith(("state", "alerts", "evidence/alerts")) for bind in row.binds)
    assert unit_matches_row(row, UNIT)


def test_shipped_table_validates_with_the_row() -> None:
    validate_table()
    assert dict(WRAPPER_LINE_ONLY_UNITS).keys() == {UNIT}


def test_default_line_only_map_follows_the_table_it_judges() -> None:
    selftest_only = {k: v for k, v in AUTONOMY_BWRAP_TABLE.items() if k != ROW}
    assert dict(effective_line_only_units(selftest_only, None)) == {}
    validate_table(selftest_only)
    assert set(effective_line_only_units(AUTONOMY_BWRAP_TABLE, None)) == {UNIT}


def test_an_explicit_line_only_map_stays_strict() -> None:
    selftest_only = {k: v for k, v in AUTONOMY_BWRAP_TABLE.items() if k != ROW}
    with pytest.raises(TableError, match="must be listed by a row"):
        validate_table(selftest_only, wrapper_line_only_units=WRAPPER_LINE_ONLY_UNITS)
    with pytest.raises(TableError):
        validate_table(AUTONOMY_BWRAP_TABLE, wrapper_line_only_units=MappingProxyType({UNIT: ""}))


def test_row_with_a_bus_read_is_refused_to_stay_snapshot_free() -> None:
    row = AUTONOMY_BWRAP_TABLE[ROW]
    widened = dataclasses.replace(row, binds=("evidence/capture/stall", "state/x"))
    with pytest.raises(TableError, match="state"):
        validate_table({ROW: widened})


def _write(root: Path, files: dict[str, str]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (root / name).write_text(text)
    return root


HOOK_LINE = (
    f"/usr/bin/timeout -k 2 10 {WRAPPER_PATH} {ROW} "
    "/home/jon/breezy/.venv/bin/python3 -m breezy.runtime.capture_recorder_hook_cli"
)


def test_the_hook_line_lints_clean_in_the_recorder_unit(tmp_path: Path) -> None:
    unit = f"[Service]\nExecStart=/home/jon/breezy/.venv/bin/python3 x\nExecStopPost={HOOK_LINE}\n"
    assert lint_units(_write(tmp_path, {UNIT: unit}), AUTONOMY_BWRAP_TABLE) == ()


def test_the_unwrapped_recorder_unit_lints_clean_today(tmp_path: Path) -> None:
    unit = "[Service]\nExecStart=/home/jon/breezy/.venv/bin/python3 x\n"
    assert lint_units(_write(tmp_path, {UNIT: unit}), AUTONOMY_BWRAP_TABLE) == ()


def test_a_hook_line_naming_another_row_or_a_prefix_is_a_lint_error(tmp_path: Path) -> None:
    wrong = HOOK_LINE.replace(ROW, "breezy-autonomy-selftest")
    errors = lint_units(
        _write(tmp_path / "a", {UNIT: f"[Service]\nExecStopPost={wrong}\n"}), AUTONOMY_BWRAP_TABLE
    )
    assert {e.rule for e in errors} == {"row_not_listing_unit"}
    prefixed = lint_units(
        _write(tmp_path / "b", {UNIT: f"[Service]\nExecStopPost=-{HOOK_LINE}\n"}),
        AUTONOMY_BWRAP_TABLE,
    )
    # Recorded for step 2: the plan's `-` form is refused by B6-R7 today (see the WP3 return).
    assert {e.rule for e in prefixed} == {"exec_prefix"}


def test_the_real_deploy_dir_lints_clean_with_the_row() -> None:
    errors = lint_units(REPO_ROOT / "deploy" / "systemd", AUTONOMY_BWRAP_TABLE)
    # X-3 recorded gap (AUT-6 WP1): the only error is the redeliver unit's notifier OnFailure scope.
    assert [(e.unit, e.rule) for e in errors] == [
        ("breezy-autonomy-alert-redeliver.service", "onfailure_scope")
    ]
