"""AUT-6 WP5: the pure NBP drift predicates moved to ``breezy.analysis.nbp_drift``.

``scripts/analysis/nbp_learning_nightly.py`` imports them back and keeps only the alerting and the
positive controls. The expected numbers below are literals worked from the thresholds (2.5 degF
mean-residual shift, 18 h cycle staleness, 72 h label staleness), not recomputed by the code under
test.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import sys
from pathlib import Path
from typing import Any, cast

import pytest

from breezy.analysis import nbp_drift
from breezy.runtime.health import AlertPayload

_MODULE_PATH = (
    Path(__file__).resolve().parents[2] / "scripts" / "analysis" / "nbp_learning_nightly.py"
)
_spec = importlib.util.spec_from_file_location("nbp_learning_nightly_move", _MODULE_PATH)
assert _spec is not None and _spec.loader is not None
_nightly = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _nightly
_spec.loader.exec_module(_nightly)
nightly = cast(Any, _nightly)

_MOVED = (
    "DRIFT_MEAN_RESIDUAL_THRESHOLD_F",
    "FINAL_LABEL_STALE_AFTER",
    "HOLDOUT_START",
    "LABEL_STATUS_FINAL",
    "LABEL_STATUS_PROVISIONAL",
    "NBP_STALE_CYCLE_AFTER",
    "DriftResult",
    "FreshnessResult",
    "LearningRow",
    "final_pre_holdout_rows",
    "newest_final_label_day",
)


class _Sink:
    def __init__(self) -> None:
        self.payloads: list[AlertPayload] = []

    def emit(self, payload: AlertPayload) -> None:
        self.payloads.append(payload)


def _row(day: dt.date, residual_f: float, status: str = "FINAL") -> Any:
    return nbp_drift.LearningRow(
        station="LAX",
        climate_day=day,
        label_status=status,
        cli_tmax_f=72.0,
        m2_median_f=72.0 - residual_f,
        p_m2=0.7,
        p_m1=0.55,
        outcome=True,
    )


def test_nightly_behaviour_identical_after_move() -> None:
    # 1. the nightly script re-binds the very same objects
    for name in _MOVED:
        assert getattr(nightly, name) is getattr(nbp_drift, name), name
    assert nbp_drift.DRIFT_MEAN_RESIDUAL_THRESHOLD_F == 2.5
    assert nbp_drift.DRIFT_CALIBRATION_CRPS_DELTA_THRESHOLD_F == 0.75
    assert nbp_drift.NBP_STALE_CYCLE_AFTER == dt.timedelta(hours=18)
    assert nbp_drift.FINAL_LABEL_STALE_AFTER == dt.timedelta(hours=72)

    # 2. a 3.0 degF mean residual drifts (> 2.5): one WARN alert with the original event name
    sink = _Sink()
    result = nightly.check_drift(rows=(_row(dt.date(2026, 6, 1), 3.0),), sink=sink)
    assert (result.n, result.mean_residual_f, result.shift_f, result.drifted) == (
        1,
        3.0,
        3.0,
        True,
    )
    assert result.calibration_drifted is False and result.calibration_crps_delta is None
    assert [(p.event, p.detail, p.severity, p.site) for p in sink.payloads] == [
        ("nbp_nightly_drift", "mean_residual_shift", "WARN", "global")
    ]

    # 3. exactly 2.5 does not drift (strict >), a provisional or empty set gives n=0 and no alert
    sink = _Sink()
    edge = nightly.check_drift(rows=(_row(dt.date(2026, 6, 1), 2.5),), sink=sink)
    assert edge.drifted is False and sink.payloads == []
    sink = _Sink()
    empty = nightly.check_drift(rows=(_row(dt.date(2026, 6, 1), 9.0, "PROVISIONAL"),), sink=sink)
    assert empty == nbp_drift.DriftResult(
        n=0,
        mean_residual_f=None,
        shift_f=None,
        drifted=False,
        calibration_crps_delta=None,
        calibration_drifted=False,
    )
    assert sink.payloads == []

    # 4. the holdout is excluded: a FINAL row on/after the holdout start never counts
    holdout = nbp_drift.HOLDOUT_START
    assert nbp_drift.final_pre_holdout_rows((_row(holdout, 9.0),)) == ()

    # 5. the positive controls still fire and are labelled
    sink = _Sink()
    controlled = nightly.check_drift(
        rows=(_row(dt.date(2026, 6, 1), 0.0),), sink=sink, positive_control=True
    )
    assert controlled.drifted and controlled.mean_residual_f == pytest.approx(2.6)
    assert [p.event for p in sink.payloads] == ["TEST_POSITIVE_CONTROL_nbp_nightly_drift"]


def test_freshness_flags_are_pure_and_match_the_nightly_alerts() -> None:
    now = dt.datetime(2026, 6, 5, 12, tzinfo=dt.UTC)
    # 18 h exactly is fresh; one second more is stale
    fresh = nbp_drift.compute_freshness(
        newest_cycle=now - dt.timedelta(hours=18), newest_label_day=dt.date(2026, 6, 4), now=now
    )
    assert (fresh.stale_cycle, fresh.stale_label) == (False, False)
    stale = nbp_drift.compute_freshness(
        newest_cycle=now - dt.timedelta(hours=18, seconds=1),
        newest_label_day=dt.date(2026, 6, 1),  # label instant 06-02 00:00Z, 106 h old
        now=now,
    )
    assert (stale.stale_cycle, stale.stale_label) == (True, True)
    missing = nbp_drift.compute_freshness(newest_cycle=None, newest_label_day=None, now=now)
    assert (missing.stale_cycle, missing.stale_label) == (True, True)
    with pytest.raises(ValueError, match="timezone-aware"):
        nbp_drift.compute_freshness(
            newest_cycle=None,
            newest_label_day=None,
            now=dt.datetime(2026, 6, 5, 12),  # noqa: DTZ001 - naive on purpose
        )
    assert nbp_drift.instant_from_ns(1_000_000_000) == dt.datetime(
        1970, 1, 1, 0, 0, 1, tzinfo=dt.UTC
    )


def test_nbp_drift_has_no_alerting_or_script_dependency() -> None:
    import ast

    tree = ast.parse(Path(nbp_drift.__file__).read_text(encoding="utf-8"))
    imported = {
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    } | {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert not {m for m in imported if m.startswith(("breezy.runtime", "breezy.strategy"))}
    assert not {m for m in imported if m.startswith("breezy.adapters")}
    assert "breezy.domain.quantile_density" in imported
