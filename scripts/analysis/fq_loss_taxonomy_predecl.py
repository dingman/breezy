"""TE-2 WP1c: the predeclaration reader and the pin-coverage check (I/O).

``TE2_PREDECLARATION.json`` is frozen before Phase B (plan S0-H). Phase B reads its thresholds from
it instead of re-hardcoding them. Constants that are baked into the pinned family modules
(alphas, PIT bands, the clamp, materiality, the power floor) are checked for DRIFT: a predeclared
value that differs from the code constant is a refusal, because the frozen code would otherwise
run a different test than the one declared. Constants the code does not bake in (the cycle-age
maximum, the cheap-ask flag, the fee theta, the audit expectation, the forward-feasibility bound)
are taken from the predeclaration as they stand.

Schema (all keys required): ``phase_a_table_sha256``, ``thresholds`` (the keys of
``thresholds_block``), ``consumer_map`` (finding -> consumer), ``s0i_statuses`` (the S0-I
testability list per test) and ``terminal_climate_day``. It does NOT store its own sha.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from scripts.analysis.fq_loss_taxonomy_classify import PIT_CENTRAL_HIGH, PIT_CENTRAL_LOW
from scripts.analysis.fq_loss_taxonomy_stats import (
    ALPHA_ART,
    ALPHA_PRIMARY,
    P_CLAMP,
    PIT_TAIL_HIGH,
    PIT_TAIL_LOW,
)
from scripts.analysis.fq_loss_taxonomy_verdict import MATERIAL_DELTA_P, POWER_FLOOR

ANALYSIS_DIR: Final = "scripts/analysis"
FAMILY_GLOB: Final = "fq_loss_taxonomy_*.py"
CLI_MODULE: Final = "fq_v1_loss_taxonomy.py"
_TOP_KEYS: Final = (
    "phase_a_table_sha256", "thresholds", "consumer_map", "s0i_statuses", "terminal_climate_day",
)  # fmt: skip
_CAMPAIGN_SOFT_TARGET: Final = "2026-10-20"
#: Predeclared name -> the frozen code constant it must equal.
_BOUND_TO_CODE: Final[Mapping[str, float]] = {
    "alpha_primary": ALPHA_PRIMARY,
    "alpha_art": ALPHA_ART,
    "p_clamp": P_CLAMP,
    "pit_tail_low": PIT_TAIL_LOW,
    "pit_tail_high": PIT_TAIL_HIGH,
    "pit_central_low": PIT_CENTRAL_LOW,
    "pit_central_high": PIT_CENTRAL_HIGH,
    "material_delta_p": MATERIAL_DELTA_P,
    "power_floor": POWER_FLOOR,
}
_CONSUMERS: Final[Mapping[str, str]] = {
    "FIXABLE_DEFECT": "Bug row against the named module; blocks any FQ re-open (T2).",
    "MODEL_LIMITATION": "PROGRESS row 'F13 r-next / T2-T3 candidate input' (calibration note).",
    "MODEL_MISCALIBRATED_UNATTRIBUTED": "F13 r-next / T3 input; next evidence is T1 (12-07).",
    "VARIANCE": "Closed 'no action' with test, p-value, power, qualifier and T1-T3 footer.",
    "INCONCLUSIVE": "Forward-only evidence plan handed to T2, or closed until T1 (12-07).",
    "NOT_TESTABLE_OR_CONDITIONAL": "Feeds the INCONCLUSIVE forward-evidence sizing (route 1).",
    "K1a": "Bug row against the named module; blocks any FQ re-open (T2).",
    "K1b": "Closed, no action: incident already fixed (0fe98eb4 + orders-off drop-in).",
    "K2": "Descriptive only; a feed-latency input to the F13 source review.",
    "K3": "Descriptive only; F13 US-source list if a route is wanted.",
    "K4": "Venue-semantics row; settlement alignment fixed before any family trades this venue.",
    "BOUNDARY": "T2 input only; T-EDGE is exploratory (within model-expected near-misses).",
    "SIBLING_WON": "T2 take-rule input (rung stacking).",
    "TAIL": "PROGRESS row 'F13 r-next / T2-T3 candidate input' (descriptive baseline).",
    "BAND_SELECTION": "T2 take-rule input (minimum-ask filter, consistent with M1).",
    "BODY_MISS": "Closed 'no action' with the test, p-value, power and the T1-T3 footer.",
}


class PredeclarationError(Exception):
    """Phase B refuses: the predeclaration is unreadable, drifted or not for this Phase A table."""


@dataclass(frozen=True)
class Predeclaration:
    phase_a_table_sha256: str
    thresholds: Mapping[str, Any]
    consumer_map: Mapping[str, str]
    s0i_statuses: Mapping[str, str]
    terminal_climate_day: str
    raw_sha256: str


def thresholds_block() -> dict[str, Any]:
    """The thresholds block a predeclaration carries (code-bound values come from the code)."""
    return {
        **_BOUND_TO_CODE,
        "cycle_age_max_s": 86400,
        "flank_cheap_ask": 0.10,
        "fee_theta": 0.0695,
        "forward_clusters_feasible": 60,
        "delivery_soft_target": _CAMPAIGN_SOFT_TARGET,
        "audit": {"n_fills": 25, "n_wins": 2, "net_pnl": "-2.17", "tolerance": "0.005"},
    }


def default_consumer_map() -> dict[str, str]:
    return dict(_CONSUMERS)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_predeclaration(path: Path, phase_a_table: Path) -> Predeclaration:
    """Read and validate; every failure is a ``PredeclarationError`` (a Phase B refusal)."""
    try:
        raw = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise PredeclarationError(f"predeclaration unreadable: {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise PredeclarationError("predeclaration is not a JSON object")
    missing = [key for key in _TOP_KEYS if key not in raw]
    if missing:
        raise PredeclarationError(f"predeclaration missing keys: {missing}")
    if raw["phase_a_table_sha256"] != sha256_file(phase_a_table):
        raise PredeclarationError(
            "phase_a_table_sha256 does not match the Phase A table passed in "
            f"({phase_a_table.name})"
        )
    thresholds = raw["thresholds"]
    absent = [key for key in thresholds_block() if key not in thresholds]
    if absent:
        raise PredeclarationError(f"predeclaration thresholds missing keys: {absent}")
    for name, code_value in _BOUND_TO_CODE.items():
        if thresholds[name] != code_value:
            raise PredeclarationError(
                f"threshold drift: {name} = {thresholds[name]}, frozen code uses {code_value}"
            )
    return Predeclaration(
        phase_a_table_sha256=raw["phase_a_table_sha256"],
        thresholds=thresholds,
        consumer_map=raw["consumer_map"],
        s0i_statuses=raw["s0i_statuses"],
        terminal_climate_day=raw["terminal_climate_day"],
        raw_sha256=sha256_file(path),
    )


def unpinned_family_modules(repo_root: Path, pinned_paths: Iterable[str]) -> tuple[str, ...]:
    """Every ``fq_loss_taxonomy_*.py`` (plus the CLI) on disk that the pins file does not list."""
    folder = repo_root / ANALYSIS_DIR
    on_disk = {f"{ANALYSIS_DIR}/{p.name}" for p in folder.glob(FAMILY_GLOB)}
    if (folder / CLI_MODULE).is_file():
        on_disk.add(f"{ANALYSIS_DIR}/{CLI_MODULE}")
    return tuple(sorted(on_disk - set(pinned_paths)))
