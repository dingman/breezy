"""AUT-4 WP2: ETA arithmetic, power-at-n and the single definition of the sample-size primitives."""

from __future__ import annotations

import ast
import datetime as dt
from pathlib import Path

import pytest

from breezy.analysis.autonomy import eval_stats
from breezy.persistence.autonomy import sample_size

_SRC = Path(__file__).resolve().parents[3] / "src"
_PRIMITIVES = {"mde_one_sided", "n_min_one_sided", "power_one_sided", "c_min", "deff", "n_min_eff"}


def test_eta_days() -> None:
    assert eval_stats.eta_days(28, 28, 1.0) == 0
    assert eval_stats.eta_days(28, 40, 0.0) == 0  # already reached: no rate needed
    assert eval_stats.eta_days(28, 10, 3.0) == 6
    assert eval_stats.eta_days(28, 27, 1.0) == 1
    assert eval_stats.eta_days(28, 10, 0.0) is None  # no honest ETA at a zero rate


def test_eta_date_adds_the_days_or_is_none() -> None:
    today = dt.date(2026, 10, 6)
    assert eval_stats.eta_date(today, 28, 10, 3.0) == dt.date(2026, 10, 12)
    assert eval_stats.eta_date(today, 28, 10, 0.0) is None
    assert eval_stats.eta_date(today, 28, 28, 0.0) == today


def test_eta_refuses_negative_counts() -> None:
    with pytest.raises(ValueError):
        eval_stats.eta_days(-1, 0, 1.0)


def test_power_at_n_reported() -> None:
    mde = sample_size.mde_one_sided(0.5, 403, 0.0125)
    assert eval_stats.power_at_n(0.5, 403, 0.0125, mde) == pytest.approx(0.80, abs=1e-12)
    assert eval_stats.power_at_n(0.5, 403, 0.0125, 0.0) < 0.0125 + 1e-12


def test_sample_size_primitives_single_definition() -> None:
    assert eval_stats.mde_one_sided is sample_size.mde_one_sided
    assert eval_stats.power_one_sided is sample_size.power_one_sided
    homes: dict[str, list[str]] = {name: [] for name in _PRIMITIVES}
    for path in (_SRC / "breezy").rglob("*.py"):
        for node in ast.parse(path.read_text()).body:
            if isinstance(node, ast.FunctionDef) and node.name in homes:
                homes[node.name].append(path.relative_to(_SRC).as_posix())
    assert homes == {
        name: ["breezy/persistence/autonomy/sample_size.py"] for name in sorted(_PRIMITIVES)
    }
