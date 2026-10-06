"""AUT-1 WP5 stage 3 (design r3 D3-D5, "Rows"): the three capture rows of ``AUTONOMY_BWRAP_TABLE``.

Each row binds exactly the planned directories and nothing else: no ``evidence/alerts`` (stage 4
adds the AUT-6 spool bind), no ``state/``, and never the catalog base (the settlement row writes
only ``catalog/quote_tape/decisions``; the rest of the catalog is read-only under the data-root
re-bind). All three are ``network="none"`` with ``resolves_dns=False``.
"""

from __future__ import annotations

import importlib.util
import re
import shlex
from pathlib import Path

import pytest

from breezy.analysis import capture_audit_host as host
from breezy.analysis.capture_audit_inputs import DECISIONS_REL
from breezy.runtime.autonomy_sandbox.bwrap import default_roots
from breezy.runtime.autonomy_sandbox.table import (
    AUTONOMY_BWRAP_TABLE,
    SYSTEMCTL,
    BwrapRow,
    validate_table,
)
from breezy.runtime.autonomy_sandbox.unit_lint import parse_unit

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "capture_units"
SETTLEMENT = AUTONOMY_BWRAP_TABLE["breezy-capture-settlement"]
AUDIT = AUTONOMY_BWRAP_TABLE["breezy-capture-audit"]
LIVE_PROOF = AUTONOMY_BWRAP_TABLE["breezy-capture-live-proof"]
ROWS = (SETTLEMENT, AUDIT, LIVE_PROOF)
PLANNED_BINDS = {
    "breezy-capture-settlement": {"catalog/quote_tape/decisions"},
    "breezy-capture-audit": {
        "evidence/capture/audit",
        "evidence/capture/heal",
        "evidence/capture/heal_alert_abandoned",
        "derived/verdicts",
        "cache/capture_audit",
        "cache/capture_audit_bus",
    },
    "breezy-capture-live-proof": {"evidence/capture/live_proof"},
}
DATA_PREFIX = "%h/.local/share/breezy/"


def test_capture_rows_bind_exactly_planned_dirs() -> None:
    """MUTATION M-BIND: an extra bind (``evidence/alerts`` above all) must turn this red."""
    for row in ROWS:
        assert set(row.binds) == PLANNED_BINDS[row.name], row.name
        assert len(set(row.binds)) == len(row.binds)
        assert not any(bind.split("/")[0] in ("state", "registry") for bind in row.binds)
        assert not any("alerts" in bind for bind in row.binds)
        assert row.bind_base == "data_root" and not row.config_ro_binds and not row.config_ro_dirs
        assert row.network == "none" and row.resolves_dns is False
        assert row.owner_plan == "AUT-1" and row.units == frozenset({f"{row.name}.service"})
        assert not row.credential_names and not row.host_proc and not row.notifier_fallback
    validate_table()


def test_capture_rows_agree_with_the_unit_fixtures() -> None:
    """Each fixture's ``install -d`` line creates exactly the row's bind directories."""
    for row in ROWS:
        unit = parse_unit((FIXTURES / f"{row.name}.service").read_text())
        (install,) = [
            line for line in unit.values("Service", "ExecStartPre") if "/usr/bin/install" in line
        ]
        made = {
            t.removeprefix(DATA_PREFIX) for t in shlex.split(install) if t.startswith(DATA_PREFIX)
        }
        assert made == set(row.binds), row.name


def test_settlement_catalog_base_under_data_root_not_a_bind() -> None:
    roots = default_roots()
    catalog = roots.data_root / "catalog"
    assert SETTLEMENT.binds == ("/".join(DECISIONS_REL),) == ("catalog/quote_tape/decisions",)
    for row in ROWS:
        for bind in row.binds:
            target = roots.data_root / bind
            assert target != catalog and not catalog.is_relative_to(target), (row.name, bind)
    # The decisions bind is the ONLY write path under the catalog; the base itself stays read-only.
    assert roots.data_root.joinpath(*DECISIONS_REL).is_relative_to(catalog)
    unit = parse_unit((FIXTURES / "breezy-capture-settlement.service").read_text())
    (start,) = unit.values("Service", "ExecStart")
    assert "--catalog-base %h/.local/share/breezy/catalog" in start


def test_audit_bus_reads_equal_names() -> None:
    assert tuple(read.name for read in AUDIT.bus_reads) == host.AUDIT_BUS_READ_NAMES
    assert tuple(read.argv for read in AUDIT.bus_reads) == tuple(
        (SYSTEMCTL, "--user", "show", *tail) for tail in host.AUDIT_BUS_READS
    )
    assert AUDIT.name == host.AUDIT_ROW_NAME
    assert AUDIT.bus_snapshot_bind == "cache/capture_audit_bus"
    assert AUDIT.bus_snapshot_bind in AUDIT.binds and AUDIT.bus_snapshot_budget_s == 10
    assert AUDIT.studies_lock is True and AUDIT.exceptions == frozenset({"E7_STUDIES_LOCK"})
    for row in (SETTLEMENT, LIVE_PROOF):
        assert row.bus_reads == () and not row.studies_lock and row.exceptions == frozenset()


def test_only_the_audit_and_label_rows_take_the_studies_lock() -> None:
    # AUT-2 WP6 / E-15: the label run takes the studies flock in process under the E7_STUDIES_LOCK
    # exception (plan-owner architect ruling), like the audit row. No other row may.
    assert [row.name for row in AUTONOMY_BWRAP_TABLE.values() if row.studies_lock] == [
        "breezy-autonomy-selftest-proc",
        "breezy-capture-audit",
        "breezy-label-outcomes",
    ]


@pytest.mark.parametrize("row", ROWS, ids=lambda row: row.name)
def test_entry_module_exists_and_is_an_analysis_cli(row: BwrapRow) -> None:
    (module,) = row.entry_modules
    assert re.fullmatch(r"breezy\.analysis\.capture_[a-z_]+_cli", module)
    assert importlib.util.find_spec(module) is not None
