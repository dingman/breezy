"""W2(a): ``ProbeReport`` and ``CLOCKS`` live in ``maker_stage0_probe_report``.

``maker_stage0_probe`` re-exports both. The line ceiling is the same one
``test_maker_stage0_verdict.py`` pins on the WP5 split.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from scripts.analysis import maker_stage0_probe as p
from scripts.analysis import maker_stage0_probe_report as r

_ANALYSIS = Path(__file__).resolve().parents[2] / "scripts" / "analysis"


def test_probe_report_and_clocks_are_the_split_objects() -> None:
    assert "CLOCKS" in p.__all__
    assert "ProbeReport" in p.__all__
    assert p.ProbeReport is r.ProbeReport
    assert p.CLOCKS is r.CLOCKS


def test_every_probe_all_name_resolves() -> None:
    for name in p.__all__:
        getattr(p, name)


def test_probe_and_report_modules_stay_under_400_lines() -> None:
    for name in ("maker_stage0_probe.py", "maker_stage0_probe_report.py"):
        path = _ANALYSIS / name
        assert len(path.read_text(encoding="utf-8").splitlines()) < 400, name


def _sample(report_cls: type[p.ProbeReport]) -> dict[str, Any]:
    direction = p.DirectionResult("INSUFFICIENT", p.SideTally(), p.SideTally())
    report = report_cls(
        days=("2026-09-22",),
        stations=("LAX",),
        first_print_ns=None,
        first_replayable_day=None,
        direction=direction,
        control=None,
        census=p.CensusCounts(0, 0, 0, 0, 0),
        depth_frames=0,
        truncated_frames=0,
        coverage=(p.StationDayCoverage("LAX", "2026-09-22", 0.0, 0.0, None, True, None),),
        delta_instance_days=(p.InstanceDayDelta(1, 1, -1, 1, raw_delta_ns=1),),
        delta_distribution={"n": 0, "min": None},
        ladder_parity={"LAX": {"rungs_per_day": {"1": 1}, "uniform": True}},
    )
    return report.to_dict()


def test_to_dict_sample_is_identical_via_either_module() -> None:
    assert _sample(p.ProbeReport) == _sample(r.ProbeReport)
