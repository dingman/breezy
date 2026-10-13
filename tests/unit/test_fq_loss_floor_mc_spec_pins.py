"""S3 WP0: characterisation pins for the FQ floor MC (GREEN on HEAD before any edit).

These freeze today's behaviour so a later ``FloorSpec`` refactor can prove the FQ
default is byte-identical. They are not RED-first: the hashes were taken from HEAD.
Each document hash is sha256 of ``json.dumps(doc, sort_keys=True)``; ``run_floor``'s
provenance arguments default to None, so the documents carry no run-specific text.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Any

from breezy.analysis.fq_loss_stop_core import ALPHA_FLOOR_GRID, G3_FLOOR_MULTIPLIER, T_MIN_GRID
from scripts.analysis import fq_loss_floor_mc_e2 as e2
from scripts.analysis import fq_loss_floor_mc_engine as engine
from scripts.analysis import fq_loss_floor_mc_gate as gate
from scripts.analysis import fq_loss_floor_mc_outer as outer
from scripts.analysis import fq_loss_floor_mc_report as report
from scripts.analysis import fq_loss_floor_mc_solve as solve
from scripts.analysis.fq_loss_floor_mc_gate import FloorConfig
from scripts.analysis.fq_loss_floor_mc_rows import StationDay, make_leg, make_station_day

# Pinned from HEAD 5b82b3de (2026-10-13). A change here means the FQ default moved.
PASS_DOC_SHA256 = "3d7e1554027c191f7bd66b45f98cfea182de14bab1e12d35972699ce78005b21"
VETO_DOC_SHA256 = "3b02cc4646efd9ee6544755cb7e1e1b21498d7f8c708a4b38d14b57ee803f81d"

_SEED = 11
_REPLICATES = 64
_OUTER_RESAMPLES = 2
_OUTER_REPLICATES = 32
_MIXES = ("M-pool", "M-yes", "M-no")
_CAL_ROWS = (
    ("H0", "none"),
    ("S1", "none"),
    ("S2", "none"),
    ("S4", "none"),
    ("S5", "bind"),
    ("S5", "half"),
    ("S6", "none"),
    ("S7", "none"),
)
_BINDING_ROWS = {("H0", "none"), ("S4", "none"), ("S5", "bind")}


def _config(**overrides: object) -> FloorConfig:
    base: dict[str, object] = {
        "take_rate_lower": 0.25,
        "theta": 0.0,
        "lambda_pool": 0.40,
        "r_sd": 1.0,
        "lambda_sd": 1.0,
        "half_spread": 0.03,
        "pool_exit_fraction": 0.0,
        "rho_hat": None,
    }
    base.update(overrides)
    return FloorConfig(**base)  # type: ignore[arg-type]


def _mixed_world() -> tuple[StationDay, ...]:
    """Fixture A days: one YES and one NO leg per day, BEs varying with the index."""
    return tuple(
        make_station_day(
            f"S{i % 4}",
            (
                make_leg("T70", "yes", 0.30 + 0.02 * (i % 5)),
                make_leg("T71", "no", 0.25 + 0.03 * (i % 4)),
            ),
        )
        for i in range(6)
    )


def _yes_world() -> tuple[StationDay, ...]:
    """Fixture B days: a single YES leg per day (vetoes once lambda_sd is tiny)."""
    return tuple(make_station_day(f"S{i % 4}", (make_leg("T70", "yes", 0.45),)) for i in range(6))


def _floor(days: tuple[StationDay, ...], **config: object) -> dict[str, Any]:
    groups = (days[0::2], days[1::2])
    gate_groups = (days[0::3], days[1::3], days[2::3])
    document = engine.run_floor(
        groups,
        gate_groups=gate_groups,
        replicates=_REPLICATES,
        seed=_SEED,
        config=_config(**config),
        alphas=None,
        outer_resamples=_OUTER_RESAMPLES,
        outer_replicates=_OUTER_REPLICATES,
    )
    assert isinstance(document, dict)
    return document


def _sha(document: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(document, sort_keys=True).encode()).hexdigest()


def test_fq_floor_pass_document_hash_is_pinned() -> None:
    document = _floor(_mixed_world())

    outcome = document["outcome"]
    assert outcome["floor_mode"] == "sqrt_boundary"
    assert outcome["veto_cause"] is None
    assert document["outer_resamples"] == _OUTER_RESAMPLES
    assert document["outer_replicates"] == _OUTER_REPLICATES
    assert _sha(document) == PASS_DOC_SHA256


def test_fq_floor_veto_document_hash_is_pinned() -> None:
    document = _floor(_yes_world(), lambda_sd=0.01)

    outcome = document["outcome"]
    assert outcome["floor_mode"] == "unreachable_veto"
    assert outcome["veto_cause"] == "g1_unreachable"
    assert outcome["failing_mix"] == "M-pool"
    assert _sha(document) == VETO_DOC_SHA256


def test_fq_module_constants_are_unchanged() -> None:
    assert engine.MIXES == report.MIXES == e2._MIX_ORDER == _MIXES
    assert engine._CAL == report._CAL == _CAL_ROWS
    assert engine.PATH_FAMILIES == 60
    # 8 calibration rows x 3 mixes + 3 deltas x 3 mixes x 4 epoch lengths.
    assert len(_CAL_ROWS) * len(_MIXES) + len(gate.DELTAS) * len(_MIXES) * 4 == 60
    assert report._BINDING == frozenset(_BINDING_ROWS)
    assert outer._BINDING == (("H0", "none"), ("S4", "none"), ("S5", "bind"))
    assert gate.DEFAULT_FREEZE == date(2026, 10, 8)
    assert gate.HORIZON == date(2027, 1, 25)
    assert gate._EPOCH_FIXED == (date(2026, 11, 1), date(2026, 11, 15), date(2026, 12, 1))
    assert gate.DELTAS == (-0.16, -0.08, -0.04)
    assert ALPHA_FLOOR_GRID == (0.10, 0.20, 0.30)
    assert G3_FLOOR_MULTIPLIER == 2.5
    assert T_MIN_GRID == (1, 2, 3, 5)
    assert solve.GRID_STEP == 0.01


def test_all_no_world_under_fq_spec_vetoes_g1_unreachable_on_m_yes() -> None:
    days = tuple(
        make_station_day(f"S{i % 4}", (make_leg("T70", "no", 0.78), make_leg("T72", "no", 0.78)))
        for i in range(8)
    )

    document = engine.run_floor(
        (days[0::2], days[1::2]),
        replicates=16,
        seed=3,
        config=_config(),
        alphas=(0.10,),
        outer_resamples=0,
    )

    outcome = document["outcome"]
    assert isinstance(outcome, dict)
    assert outcome["floor_mode"] == "unreachable_veto"
    assert outcome["veto_cause"] == "g1_unreachable"
    assert outcome["failing_mix"] == "M-yes"


def test_fq_floor_document_hash_is_stable_across_identical_runs() -> None:
    # No timing, RSS or timestamp field may vary: nothing is stripped before hashing.
    for days, config in ((_mixed_world(), {}), (_yes_world(), {"lambda_sd": 0.01})):
        first = _floor(days, **config)
        second = _floor(days, **config)
        assert first == second
        assert _sha(first) == _sha(second)
