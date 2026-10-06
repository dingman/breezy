"""AUT-2 r7 WP6 / section 3.10 consumers: an AUT-2 unit exits 0 on no input and non-zero on a
genuine failure, so ``OnFailure=`` fires only for real failures (never an expected condition).

The label unit is exercised behaviourally through ``run_unit``. The deployed wrappers of the
position-monitor report and the family tally are checked structurally: every expected-skip branch
exits 0, every failure branch exits non-zero, and nothing masks a status. The two WP9 reconcile
units do not exist yet: their rows are strict expected failures that go loud when the files land.
The portfolio-roi and score-live-trials wrappers are AUT-6's tests.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from breezy.analysis.labeling.label_core import InputPlan, LabelRunDeps, RunResult
from breezy.analysis.labeling.label_run import LABEL_UNIT, run_unit
from breezy.analysis.labeling.memory_gate import missing_aut6_reading
from breezy.persistence.autonomy.label_store import RunOutcome
from tests.support.aut2_run_fixtures import FQ_KIND, Sink, make_deps
from tests.unit.test_aut2_label_run import _Lock

_DEPLOY = Path(__file__).resolve().parents[2] / "deploy" / "systemd"
_FIXTURES = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "aut2_units"
_WP9 = "AUT-2 WP9 lands the reconcile units"


def _wp9(name: str) -> object:
    return pytest.param(
        name,
        id=name,
        marks=pytest.mark.xfail(strict=True, raises=FileNotFoundError, reason=_WP9),
    )


UNITS = [
    "label-outcomes",
    _wp9("aut2-reconciliation"),
    _wp9("reconcile-poststop"),
    "position-monitor-report",
    "family-tally-v2",
]
_WRAPPERS = {
    "position-monitor-report": (
        "breezy-position-monitor-report.service",
        "position-monitor-report-run.sh",
    ),
    "family-tally-v2": ("breezy-family-tally@.service", "family-tally-v2-run.sh"),
    "aut2-reconciliation": ("breezy-aut2-reconciliation.service", "aut2-reconciliation-run.sh"),
    "reconcile-poststop": (
        "breezy-autonomy-reconcile-poststop.service",
        "aut2-reconciliation-run.sh",
    ),
}


def _run(deps: LabelRunDeps) -> RunResult:
    return run_unit(
        deps,
        lock=_Lock(False),
        unit_max_bytes=2 * 1024**3,
        aut6=missing_aut6_reading(),
        measured_peak_bytes=None,
        proof_window=None,
        slot_ns=1,
    )


def _wrapper(unit: str) -> tuple[str, str]:
    service, script = _WRAPPERS[unit]
    return (_DEPLOY / service).read_text(), (_DEPLOY / script).read_text()


def _code_lines(script: str) -> list[str]:
    return [
        ln.strip() for ln in script.splitlines() if ln.strip() and not ln.strip().startswith("#")
    ]


@pytest.mark.parametrize("unit", UNITS)
def test_every_aut2_unit_exits_zero_on_no_input(unit: str, tmp_path: Path) -> None:
    if unit == "label-outcomes":
        deps = make_deps(tmp_path, n_fills=0, plan=lambda fills: InputPlan({}, {}))
        result = _run(deps)
        assert result.exit_code == 0 and result.run_outcome is RunOutcome.NO_INPUT
        return
    service, script = _wrapper(unit)
    assert "SuccessExitStatus" not in service
    code = _code_lines(script)
    skips = [ln for ln in code if re.search(r"SKIPPED(?!-INFRA)|NO_INPUT|NO_MONITOR", ln)]
    assert skips, "the wrapper has no expected-skip branch"
    assert all(re.search(r"exit 0\b", ln) or "say" in ln or "echo" in ln for ln in skips)
    assert any(re.search(r"\bexit 0\b", ln) for ln in code)


@pytest.mark.parametrize("unit", UNITS)
def test_every_aut2_unit_exits_nonzero_on_genuine_failure(unit: str, tmp_path: Path) -> None:
    if unit == "label-outcomes":
        deps = make_deps(tmp_path, n_fills=None, deliver=Sink())
        result = _run(deps)
        assert result.exit_code != 0
        return
    service, script = _wrapper(unit)
    code = _code_lines(script)
    assert re.search(r"\bexit [1-9]\b|exit \"\$STATUS\"", "\n".join(code))
    # a `|| true` may only guard a read-only probe, never the analysis run behind the unit status
    masked = [ln for ln in code if re.search(r"\|\|\s*true\b", ln)]
    assert not any("scripts/analysis" in ln or "$PY -m breezy.analysis" in ln for ln in masked)
    assert "SuccessExitStatus" not in service and "ExecStartPost" not in service


def test_the_label_fixture_unit_masks_no_exit_status() -> None:
    service = (_FIXTURES / f"{LABEL_UNIT}.service").read_text()

    assert "SuccessExitStatus" not in service and "|| true" not in service
    assert FQ_KIND  # keep the shared import honest: the label unit is the FQ family's
