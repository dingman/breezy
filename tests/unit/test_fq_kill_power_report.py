"""KILL power at non-positive edges: clamp, δ = 0 harness, A0 pins, schema.

Reporting only (F5-pin-request r2 §3.4 plus the r2-verification corrections).
No constant changes.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
for _entry in (str(REPO_ROOT), str(REPO_ROOT / "src")):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from breezy.analysis.autonomy import confidence_sequence as cs
from scripts.analysis import fq_kill_power_report as report
from scripts.analysis import fq_mc_eprocess as mc
from scripts.analysis.fq_mc_eprocess import outcome_probability
from scripts.analysis.fq_mc_livedata import DayTemplate, TakeRecord, simulate_pooled
from scripts.analysis.fq_mc_livedata import Design as McDesign
from scripts.analysis.multisource_blend_pin_guards import UNFROZEN
from scripts.analysis.multisource_blend_refusal import Refusal

_PLAN = REPO_ROOT / "docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04"
_A0 = _PLAN / "F5_prereg_v2_amendment_A0.json"

_ROW_KEYS = frozenset(
    {
        "delta",
        "p_kill_by_kill_date",
        "se_p_kill_by_kill_date",
        "p_kill_by_n_max",
        "se_p_kill_by_n_max",
        "median_n_at_kill",
        "se_median_n_at_kill",
        "clipped_mean_y",
        "take_rate",
        "take_rate_target",
        "take_rate_realised",
        "be_ask_source",
    }
)
_DOC_KEYS = frozenset(
    {
        "seed",
        "replicates",
        "deltas",
        "design",
        "rows",
        "be_ask_source",
        "take_rate",
        "take_rate_target",
        "take_rate_realised",
        "take_rate_source",
        "n_max",
        "n_by_kill_date",
        "kill_date",
        "d0",
        "uptime_floor",
        "amendment_id",
        "provenance",
    }
)


def _flat_templates() -> list[DayTemplate]:
    """Two BE = 0.50 takes per day: upside 1.0 is inside x_max 4, so the clip does not bite."""
    take = TakeRecord(
        station="NYC",
        rung_id="T80",
        side="yes",
        ask=0.49,
        be=0.50,
        p_side=0.50,
        ev_net=0.0,
    )
    origin = dt.date(2024, 1, 1)
    return [DayTemplate(origin + dt.timedelta(days=i), (take, take)) for i in range(5)]


def _low_be_templates() -> list[DayTemplate]:
    take = TakeRecord(
        station="NYC",
        rung_id="T80",
        side="yes",
        ask=0.09,
        be=0.10,
        p_side=0.10,
        ev_net=0.0,
    )
    return [DayTemplate(dt.date(2024, 1, 1), (take,))]


def test_clamp_negative_delta_below_be_is_zero_never_negative() -> None:
    """δ = −0.16 at BE 0.10 is below zero. The MC alternative has no lower clamp."""
    p = report.clamped_outcome_probability(0.10, delta=-0.16)
    assert p == 0.0
    assert p >= 0.0
    assert outcome_probability(0.10, delta_h=-0.16, null=False) < 0.0

    batch = report.simulate_clamped(
        _low_be_templates(),
        McDesign(delta_h=-0.16),
        reps=6,
        days=4,
        seed=20261008,
    )
    assert np.all(batch.h[batch.valid] == 0.0)
    assert float(batch.h[batch.valid].min()) >= 0.0


def test_delta_zero_harness_row_matches_null_and_does_not_kill() -> None:
    """δ = 0 is the harness row: same stream as the MC null, and p_kill ≈ 0."""
    templates = _flat_templates()
    seed = 20261008
    reps, days = 8, 40
    design = McDesign(delta_h=0.0, m_cap=2, x_max=4.0, earliest_look_n=20, alpha_kill=0.05)
    clamped = report.simulate_clamped(templates, design, reps=reps, days=days, seed=seed)
    null = simulate_pooled(templates, design, reps=reps, days=days, seed=seed, null=True)
    assert np.array_equal(clamped.h, null.h)
    assert np.array_equal(clamped.be, null.be)

    row = report.run_delta(
        templates,
        delta=0.0,
        m_cap=2,
        x_max=4.0,
        alpha_kill=0.05,
        earliest_look_n=20,
        replicates=reps,
        days=days,
        n_max=80,
        n_by_kill_date_n=24,
        seed=seed,
        take_rate_target=0.25,
        take_rate_realised=2.0,
    )
    assert row["delta"] == 0.0
    assert row["p_kill_by_n_max"] == 0.0
    assert row["p_kill_by_kill_date"] == 0.0
    assert row["median_n_at_kill"] is None
    mean_y = row["clipped_mean_y"]
    assert isinstance(mean_y, float)
    assert abs(mean_y) < 0.25


def test_a0_constants_equal_imported_constants() -> None:
    amendment, parent = report.load_verified_pins(_A0)
    kill = amendment["kill"]
    assert kill["kill_grid_points"] == cs.KILL_GRID_POINTS == mc.KILL_GRID_POINTS
    assert kill["kill_lambda_max"] == cs.KILL_MAX_LAMBDA == mc.MAX_LAMBDA
    assert kill["kill_min_range"] == cs._MIN_RANGE
    assert kill["kill_var_floor"] == cs._VAR_FLOOR
    assert kill["kill_prior_pseudo_days"] == cs.PRIOR_PSEUDO_DAYS == mc.PRIOR_PSEUDO_DAYS
    assert kill["kill_prior_second_moment"] == cs.PRIOR_SECOND_MOMENT == mc.PRIOR_SECOND_MOMENT
    assert parent["m_cap"] == 2
    assert parent["x_max"] == 4.0
    assert parent["alpha_kill"] == mc.ALPHA_KILL
    assert parent["earliest_look_n"] == 20
    assert (
        report.n_by_kill_date(
            0.25,
            d0=report.mc_d0(),
            kill_date=report.KILL_DATE,
            uptime_floor=0.9,
        )
        == 24
    )


def test_unfrozen_a0_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = json.loads(_A0.read_text(encoding="utf-8"))
    payload["frozen_sha"] = UNFROZEN
    draft = tmp_path / "F5_prereg_v2_amendment_A0.json"
    draft.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(report, "DEFAULT_AMENDMENT_PATH", draft)

    with pytest.raises(Refusal, match="UNFROZEN"):
        report.load_verified_pins()


def test_output_schema_keys() -> None:
    row = report.run_delta(
        _flat_templates(),
        delta=0.0,
        m_cap=2,
        x_max=4.0,
        alpha_kill=0.05,
        earliest_look_n=20,
        replicates=4,
        days=12,
        n_max=40,
        n_by_kill_date_n=24,
        seed=7,
        take_rate_target=0.25,
        take_rate_realised=2.0,
    )
    assert set(row) == _ROW_KEYS
    assert row["be_ask_source"]
    assert isinstance(row["take_rate"], float)
    assert isinstance(row["clipped_mean_y"], float)

    amendment, parent = report.load_verified_pins(_A0)
    document = report.build_document(
        amendment=amendment,
        parent=parent,
        rows=[row],
        replicates=4,
        n_max=40,
        pool=None,
        seed=20261008,
    )
    assert _DOC_KEYS <= set(document)
    assert document["deltas"][0] == 0.0
    assert -0.04 in document["deltas"]
    assert document["rows"][0]["be_ask_source"]
    encoded = json.dumps(document)
    assert "p_kill_by_kill_date" in encoded
    assert "clipped_mean_y" in encoded
    assert "be_ask_source" in encoded
