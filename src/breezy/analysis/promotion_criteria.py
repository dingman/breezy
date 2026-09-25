"""Evidence-gated promotion criteria (AUD-10b).

Pure decisions over already-loaded evidence. This module never writes a
registered manifest, never arms a family, and never promotes on its own.
A `MECHANISM_ONLY` replay row is never an edge input (ruling Q2).

The champion KILL-clock file is the AUD-05 sibling
``covered_listed_station_days_champion_<UTC-day>.json``: same six keys the
plan binds, distinct from the v1/v2-scoped ``covered_listed_station_days_<day>.json``
which is not the champion's clock. A sha mismatch is `INERT`, never a
fallback onto that other file.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import importlib.util
import json
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Protocol, cast

import numpy as np
from numpy.random import default_rng
from scipy.stats import bootstrap, norm

from breezy.analysis.replay_results import REPLAY_VALIDITY, ReplayResult
from breezy.analysis.replay_sufficiency import ReplaySufficiency, is_replayable_whole_day
from breezy.persistence.family_manifest import _UNPINNED_SHA256, FamilyManifest
from breezy.persistence.realized_draws import load_realized_draws
from breezy.settlement.current_rung_hold_v2 import (
    CombinedDraw,
    StationDayAdmissionRefusal,
    combine_station_day,
)
from breezy.settlement.roi_bound import (
    _CONFIDENCE_LEVEL,
    B_RESAMPLES,
    MIN_NON_EXCLUDED_N,
    SEED,
)
from breezy.strategy.current_rung_hold.config import SUPPORTED_STATIONS

KILL_CLOCK_MAX_AGE_SECONDS: Final[int] = 26 * 3600
CRITERIA_MODULE_VERSION: Final[str] = "aud-10b.1"
PROVISIONAL_TAG: Final[str] = (
    "STATUS=PROVISIONAL, SOURCE=FORECAST_FAMILY_R5, "
    "ADAPTED_BY=RULING_replay_evidence_citability_and_promotion_criteria_2026-09-21"
)
ADAPTED_R5_IDS: Final[frozenset[str]] = frozenset(
    {"C-KILL", "C-PAIRED", "C-ESTIMATOR", "C-REVISION", "C-PIN"}
)
LIFTING_RULING_RELATIVE: Final[Path] = Path(
    "docs/evidence/RULING_promotion_criteria_provisional_lift.md"
)
#: sha256 of the unissued-ruling sentence. Not the hash of any file in the
#: tree; a lift requires this constant to change with the ruling artefact.
LIFTING_RULING_SHA256: Final[str] = (
    "db14b89647c744ce1ac5b7e6f890caa172d61e9119ba133a22d51da00eda114b"
)
_KILL_CLOCK_KEYS: Final[frozenset[str]] = frozenset(
    {
        "count",
        "depth_root_present",
        "fetch_end",
        "fetch_start",
        "manifest_sha256",
        "stations",
    }
)
_EDGE_OUTCOMES: Final[frozenset[str]] = frozenset({"COMPLETED", "RECOVERED"})
_PROVENANCE_SIDECAR: Final[str] = "provenance.json"
_LIVE_PROVENANCE: Final[str] = "live"

DrawBook = Sequence[tuple[tuple[str, str], CombinedDraw]]


class _DeadVerdict(Protocol):
    structural_dead: bool
    evaluable: bool
    covered_listed_station_days: int
    filled_takes: int | None


class RunRefusal(Exception):
    """The whole promotion run refuses. Not a `NO_PROPOSAL` data verdict."""

    def __init__(self, reason: str, detail: str) -> None:
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason}: {detail}")


@dataclass(frozen=True, slots=True, kw_only=True)
class CriterionRow:
    id: str
    verdict: str
    value: object
    threshold: object
    input_artefact: str
    source: str
    tag: str | None
    inert_reason: str | None
    detail: str | None


@dataclass(frozen=True, slots=True, kw_only=True)
class AdmissionReport:
    outcome: str
    refusal_type: str | None
    message: str | None
    draw: CombinedDraw | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class PairedComparison:
    paired_keys: tuple[tuple[str, str], ...]
    challenger_ci_lower: float
    champion_ci_lower: float
    champion_point: float
    beats_on_ci_lower: bool
    beats_on_point: bool
    decision_rule: str


@dataclass(frozen=True, slots=True, kw_only=True)
class PromotionVerdict:
    outcome: str
    criteria_status: str
    rows: tuple[CriterionRow, ...]
    failed: tuple[str, ...]
    inert: tuple[str, ...]


def champion_kill_clock_path(tally_dir: Path, *, on_date: dt.date) -> Path:
    """AUD-05 champion counter, not the v1/v2-scoped sibling."""
    return tally_dir / f"covered_listed_station_days_champion_{on_date.isoformat()}.json"


def _tag(predicate_id: str) -> str | None:
    if predicate_id in ADAPTED_R5_IDS:
        return PROVISIONAL_TAG
    return None


def _row(
    *,
    predicate_id: str,
    verdict: str,
    value: object,
    threshold: object,
    input_artefact: str,
    source: str,
    inert_reason: str | None = None,
    detail: str | None = None,
) -> CriterionRow:
    return CriterionRow(
        id=predicate_id,
        verdict=verdict,
        value=value,
        threshold=threshold,
        input_artefact=input_artefact,
        source=source,
        tag=_tag(predicate_id),
        inert_reason=inert_reason,
        detail=detail,
    )


def _structural_dead(
    *, covered_listed_station_days: int, filled_takes: int | None
) -> _DeadVerdict:
    """The shipped `structural_dead`, loaded from the script that owns it.

    Not a re-implementation. Imported by file location so this module's
    static imports do not name `nautilus_trader` (the script does).
    """
    path = Path(__file__).resolve().parents[3] / "scripts" / "analysis" / "structural_dead_stop.py"
    module_name = "_breezy_structural_dead_stop"
    module = sys.modules.get(module_name)
    if module is None:
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise RunRefusal("KILL_CLOCK_NOT_EVALUABLE", f"cannot load {path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
    return cast(
        _DeadVerdict,
        module.structural_dead(
            covered_listed_station_days=covered_listed_station_days,
            filled_takes=filled_takes,
        ),
    )


def evaluate_c_kill(
    *,
    clock_path: Path,
    champion: FamilyManifest,
    now_unix: float,
    fill_count: Callable[[], int | None],
    exec_state_db: Path,
) -> CriterionRow:
    """Champion-scope first. A wrong-family file is INERT, never permissive.

    Staleness, `depth_root_present`, provenance, and `structural_dead` run
    only after `manifest_sha256` matches the champion. `fill_count` is not
    called before that match.
    """
    if not clock_path.is_file():
        raise RunRefusal("KILL_CLOCK_ABSENT", f"no KILL clock at {clock_path}")
    try:
        payload = json.loads(clock_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RunRefusal("KILL_CLOCK_NOT_EVALUABLE", f"{clock_path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise RunRefusal("KILL_CLOCK_NOT_EVALUABLE", f"{clock_path}: not a JSON object")
    file_sha = payload.get("manifest_sha256")
    if file_sha != champion.manifest_sha256:
        return _row(
            predicate_id="C-KILL",
            verdict="INERT",
            value={"manifest_sha256": file_sha},
            threshold=champion.manifest_sha256,
            input_artefact=str(clock_path),
            source="R5-8 adapted, PROVISIONAL",
            inert_reason="NO_CHAMPION_SCOPED_KILL_CLOCK",
            detail="counter manifest_sha256 is not the champion's",
        )
    if set(payload) != _KILL_CLOCK_KEYS:
        raise RunRefusal(
            "KILL_CLOCK_PROVENANCE_MISMATCH",
            f"{clock_path}: keys {sorted(payload)} != {sorted(_KILL_CLOCK_KEYS)}",
        )
    age = now_unix - clock_path.stat().st_mtime
    if age > KILL_CLOCK_MAX_AGE_SECONDS:
        raise RunRefusal(
            "KILL_CLOCK_STALE",
            f"{clock_path}: age {age:.0f}s > {KILL_CLOCK_MAX_AGE_SECONDS}s",
        )
    if payload["depth_root_present"] is not True:
        raise RunRefusal(
            "KILL_CLOCK_NOT_EVALUABLE",
            f"{clock_path}: depth_root_present is not true",
        )
    stations = payload["stations"]
    if payload["fetch_start"] != champion.d0_climate_day or not (
        isinstance(stations, list) and set(stations) <= set(champion.stations)
    ):
        raise RunRefusal(
            "KILL_CLOCK_PROVENANCE_MISMATCH",
            f"{clock_path}: fetch_start/stations do not match the champion manifest",
        )
    count = payload["count"]
    if isinstance(count, bool) or not isinstance(count, int):
        raise RunRefusal("KILL_CLOCK_PROVENANCE_MISMATCH", f"{clock_path}: count is not an int")
    filled = fill_count()
    if filled is None:
        raise RunRefusal(
            "KILL_CLOCK_NOT_EVALUABLE",
            f"count_filled_takes returned None for {exec_state_db}",
        )
    verdict = _structural_dead(covered_listed_station_days=count, filled_takes=filled)
    if verdict.evaluable is not True:
        raise RunRefusal(
            "KILL_CLOCK_NOT_EVALUABLE",
            "structural_dead evaluable is False; structural_dead False is not permission",
        )
    return _row(
        predicate_id="C-KILL",
        verdict="false" if verdict.structural_dead else "true",
        value={
            "structural_dead": verdict.structural_dead,
            "evaluable": verdict.evaluable,
            "covered_listed_station_days": verdict.covered_listed_station_days,
            "filled_takes": verdict.filled_takes,
        },
        threshold=None,
        input_artefact=f"{clock_path} + {exec_state_db}",
        source="R5-8 adapted, PROVISIONAL",
        detail=None,
    )


def _edge(draws: Sequence[CombinedDraw]) -> tuple[float, float, float]:
    qty = float(sum(draw.n_constituents for draw in draws))
    total_x = float(sum(draw.x for draw in draws))
    information = float(sum(draw.variance for draw in draws))
    if qty <= 0.0:
        raise ValueError("edge estimator is undefined at Σqty <= 0")
    edge_hat = total_x / qty
    se = float(np.sqrt(information) / qty) if information > 0.0 else 0.0
    z = float(norm.ppf(0.975))
    return edge_hat, se, edge_hat - z * se


def paired_ci_comparison(
    *,
    champion_draws: DrawBook,
    challenger_draws: DrawBook,
    d0_climate_day: str,
) -> PairedComparison:
    """CI-lower versus CI-lower on station-days on or after `d0_climate_day`.

    `d0_climate_day` is the family's admission boundary (inclusive). There is
    no `fit_date` on this family. The pre-d0 book is ignored on both sides.
    """
    champion_by = {key: draw for key, draw in champion_draws if key[1] >= d0_climate_day}
    challenger_by = {key: draw for key, draw in challenger_draws if key[1] >= d0_climate_day}
    keys = tuple(sorted(set(champion_by) & set(challenger_by)))
    champion_edge, _se, champion_lower = _edge([champion_by[key] for key in keys])
    _challenger_edge, _se2, challenger_lower = _edge([challenger_by[key] for key in keys])
    return PairedComparison(
        paired_keys=keys,
        challenger_ci_lower=challenger_lower,
        champion_ci_lower=champion_lower,
        champion_point=champion_edge,
        beats_on_ci_lower=challenger_lower > champion_lower,
        beats_on_point=challenger_lower > champion_edge,
        decision_rule="ci_lower_vs_ci_lower",
    )


def evaluate_c_paired(
    *,
    challenger_draws: DrawBook | None,
    champion_draws: DrawBook,
    d0_climate_day: str,
    replay_results_path: str,
) -> CriterionRow:
    """No challenger stream in the armed-family replay file → INERT, never false.

    AUD-19b's `--family-manifest` flag exists, but the scheduled runner still
    replays the armed family only, so a not-yet-armed challenger has no rows.
    """
    if not challenger_draws:
        return _row(
            predicate_id="C-PAIRED",
            verdict="INERT",
            value=None,
            threshold=None,
            input_artefact=replay_results_path,
            source="R5-7 adapted, PROVISIONAL",
            inert_reason="NO_CHALLENGER_REPLAY_PATH",
            detail="scheduled replay is the armed family only; no challenger rows",
        )
    compared = paired_ci_comparison(
        champion_draws=champion_draws,
        challenger_draws=challenger_draws,
        d0_climate_day=d0_climate_day,
    )
    return _row(
        predicate_id="C-PAIRED",
        verdict="true" if compared.beats_on_ci_lower else "false",
        value={
            "decision_rule": compared.decision_rule,
            "challenger_ci_lower": compared.challenger_ci_lower,
            "champion_ci_lower": compared.champion_ci_lower,
        },
        threshold="challenger_ci_lower > champion_ci_lower",
        input_artefact=replay_results_path,
        source="R5-7 adapted, PROVISIONAL",
        detail=None,
    )


def evaluate_c_stations(stations: Sequence[str]) -> CriterionRow:
    """Subset of `SUPPORTED_STATIONS`. Reads no file; the input is the proposal."""
    allowed = set(SUPPORTED_STATIONS)
    proposed = set(stations)
    if stations and proposed <= allowed:
        verdict, detail = "true", None
    else:
        verdict, detail = "false", "EXPANSION_REQUIRES_RULING"
    return _row(
        predicate_id="C-STATIONS",
        verdict=verdict,
        value={"stations": list(stations)},
        threshold=tuple(SUPPORTED_STATIONS),
        input_artefact="proposal.stations",
        source="AUD-10 C-STATIONS",
        detail=detail,
    )


def _edge_rows(results: Sequence[ReplayResult]) -> tuple[ReplayResult, ...]:
    return tuple(row for row in results if row.outcome in _EDGE_OUTCOMES)


def evaluate_c_validity(
    *,
    results: Sequence[ReplayResult],
    census_by_station_day: Mapping[tuple[str, str], ReplaySufficiency] | None,
    drift_station_days: frozenset[tuple[str, str]] | None,
    results_path: str,
    census_path: str,
    drift_path: str,
) -> CriterionRow:
    """No edge statistic unless every edge row clears validity, whole-day, and drift.

    `drift_station_days is None` means the drift file was absent (unknown),
    which fails closed when any edge row exists and is vacuous when none do.
    """
    artefact = f"{results_path} + {census_path} + {drift_path}"
    rows = _edge_rows(results)
    if not rows:
        return _row(
            predicate_id="C-VALIDITY",
            verdict="true",
            value={"n_edge_rows": 0},
            threshold=None,
            input_artefact=artefact,
            source="AUD-11/AUD-12; AUD-09b B27",
            detail="vacuous over zero edge rows",
        )
    reasons: list[str] = []
    if drift_station_days is None:
        reasons.append(f"replay_drift file absent: {drift_path}")
    if census_by_station_day is None:
        reasons.append(f"census absent: {census_path}")
    for row in rows:
        if row.validity == REPLAY_VALIDITY:
            reasons.append(f"{row.station} {row.climate_day}: MECHANISM_ONLY")
        if row.params_match is not True:
            reasons.append(f"{row.station} {row.climate_day}: params_match is not true")
        if row.window_complete is False:
            reasons.append(f"{row.station} {row.climate_day}: window_complete is false")
        key = (row.station, row.climate_day)
        if drift_station_days is not None and key in drift_station_days:
            reasons.append(f"{row.station} {row.climate_day}: drift set")
        if census_by_station_day is None:
            continue
        census = census_by_station_day.get(key)
        if census is None:
            reasons.append(f"{row.station} {row.climate_day}: no census row")
            continue
        if not is_replayable_whole_day(census):
            reasons.append(
                f"{row.station} {row.climate_day}: not a whole day "
                f"(verdict={census.verdict}, window_complete={census.window_complete}, "
                f"coverage_kind={census.coverage_kind!r} is not WHOLE)"
            )
    if reasons:
        return _row(
            predicate_id="C-VALIDITY",
            verdict="false",
            value={"reasons": reasons},
            threshold="validity != MECHANISM_ONLY, params_match, whole day, not drifted",
            input_artefact=artefact,
            source="AUD-11/AUD-12; AUD-09b B27",
            detail="; ".join(reasons),
        )
    return _row(
        predicate_id="C-VALIDITY",
        verdict="true",
        value={"n_edge_rows": len(rows)},
        threshold=None,
        input_artefact=artefact,
        source="AUD-11/AUD-12; AUD-09b B27",
        detail=None,
    )


def _admissible_n(store_dir: Path) -> int:
    if not store_dir.is_dir():
        return 0
    sidecar = store_dir / _PROVENANCE_SIDECAR
    if not sidecar.is_file():
        return 0
    try:
        payload = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    if not isinstance(payload, dict) or payload.get("provenance") != _LIVE_PROVENANCE:
        return 0
    try:
        loaded = load_realized_draws(store_dir)
    except (StationDayAdmissionRefusal, ValueError, OSError):
        return 0
    return loaded.n_admissible_fills


def evaluate_c_n(*, store_dir: Path) -> CriterionRow:
    n = _admissible_n(store_dir)
    passed = n >= MIN_NON_EXCLUDED_N
    return _row(
        predicate_id="C-N",
        verdict="true" if passed else "false",
        value={"n": n},
        threshold=MIN_NON_EXCLUDED_N,
        input_artefact=str(store_dir),
        source="V3 plan §2",
        detail=None if passed else "NO_PROPOSAL citing C-N",
    )


def _ratio_of_sums(
    values: np.ndarray, qty: np.ndarray, axis: int = -1
) -> np.ndarray:
    return np.sum(values, axis=axis) / np.sum(qty, axis=axis)


def block_bootstrap_ci_lower(draws: Sequence[CombinedDraw]) -> float:
    """Station-day block bootstrap using `roi_bound`'s pinned resample and seed.

    No local resample count and no local seed: both names are the shipped
    constants. The statistic is Σx/Σqty over the resampled station-days.
    """
    x_arr = np.array([draw.x for draw in draws], dtype=np.float64)
    qty_arr = np.array([float(draw.n_constituents) for draw in draws], dtype=np.float64)
    result = bootstrap(
        (x_arr, qty_arr),
        _ratio_of_sums,
        paired=True,
        vectorized=True,
        n_resamples=B_RESAMPLES,
        random_state=default_rng(SEED),
        confidence_level=_CONFIDENCE_LEVEL,
        alternative="greater",
        method="BCa",
    )
    return float(result.confidence_interval.low)


def evaluate_c_estimator(*, store_dir: Path, validity_allows_edge: bool) -> CriterionRow:
    n_row = evaluate_c_n(store_dir=store_dir)
    n = int(n_row.value["n"])  # type: ignore[index]
    if not validity_allows_edge or n_row.verdict != "true":
        return _row(
            predicate_id="C-ESTIMATOR",
            verdict="false",
            value={"n": n},
            threshold=MIN_NON_EXCLUDED_N,
            input_artefact=str(store_dir),
            source="R5-7 adapted, PROVISIONAL",
            detail="NO_PROPOSAL citing C-N",
        )
    loaded = load_realized_draws(store_dir)
    edge_hat, se, analytic_lower = _edge(loaded.draws)
    boot_lower = block_bootstrap_ci_lower(loaded.draws)
    return _row(
        predicate_id="C-ESTIMATOR",
        verdict="true",
        value={
            "n": n,
            "edge_hat": edge_hat,
            "se": se,
            "analytic_ci_lower": analytic_lower,
            "bootstrap_ci_lower": boot_lower,
        },
        threshold=MIN_NON_EXCLUDED_N,
        input_artefact=str(store_dir),
        source="R5-7 adapted, PROVISIONAL",
        detail=None,
    )


def admit_station_day(rows: Sequence[object]) -> AdmissionReport:
    """Catch every `combine_station_day` refusal at the ValueError base."""
    try:
        draw = combine_station_day(rows)  # type: ignore[arg-type]
    except (StationDayAdmissionRefusal, ValueError) as exc:
        return AdmissionReport(
            outcome="NO_PROPOSAL",
            refusal_type=type(exc).__name__,
            message=str(exc),
        )
    return AdmissionReport(outcome="ADMITTED", refusal_type=None, message=None, draw=draw)


def evaluate_c_revision(
    *, champion: FamilyManifest | None, proposal: FamilyManifest
) -> CriterionRow:
    if champion is None:
        raise RunRefusal("NO_CHAMPION_MANIFEST", "no champion manifest; nothing to revise")
    artefact = f"deploy/families/{champion.family_id}.json"
    fresh = (
        proposal.family_id != champion.family_id
        and proposal.trial_id_prefix != champion.trial_id_prefix
        and proposal.d0_climate_day > champion.d0_climate_day
    )
    return _row(
        predicate_id="C-REVISION",
        verdict="true" if fresh else "false",
        value={"n": 0, "family_id": proposal.family_id, "d0_climate_day": proposal.d0_climate_day},
        threshold="new family_id, new trial_id_prefix, d0 after the champion",
        input_artefact=artefact,
        source="R5-8 adapted, PROVISIONAL",
        detail=None if fresh else "proposal is not a new revision",
    )


def evaluate_c_pin(proposal: FamilyManifest) -> CriterionRow:
    unpinned = (
        proposal.boundary_inputs_sha256 == _UNPINNED_SHA256
        or proposal.density_artefact_sha256 == _UNPINNED_SHA256
    )
    return _row(
        predicate_id="C-PIN",
        verdict="PROPOSAL_INCOMPLETE" if unpinned else "true",
        value={
            "boundary_inputs_sha256": proposal.boundary_inputs_sha256,
            "density_artefact_sha256": proposal.density_artefact_sha256,
        },
        threshold="real boundary and density shas",
        input_artefact=str(proposal.boundary_artefact_path),
        source="R5-8 adapted, PROVISIONAL",
        detail="PROPOSAL_INCOMPLETE" if unpinned else None,
    )


def resolve_criteria_status(repo_root: Path) -> str:
    """LIFTED only when the pinned ruling file's sha256 matches. Never raises."""
    path = repo_root / LIFTING_RULING_RELATIVE
    try:
        raw = path.read_bytes()
    except OSError:
        return "PROVISIONAL"
    digest = hashlib.sha256(raw).hexdigest()
    if digest != LIFTING_RULING_SHA256:
        return "PROVISIONAL"
    return "LIFTED"


def assemble_outcome(
    rows: Sequence[CriterionRow], *, criteria_status: str
) -> PromotionVerdict:
    """Any INERT bars PROPOSAL and keeps the criteria tag provisional.

    A failing predicate dominates: the outcome is NO_PROPOSAL even if C-PIN
    is incomplete. The generator does not lift its own tag.
    """
    failed = tuple(row.id for row in rows if row.verdict == "false")
    inert = tuple(row.id for row in rows if row.verdict == "INERT")
    incomplete = any(row.verdict == "PROPOSAL_INCOMPLETE" for row in rows)
    status = "PROVISIONAL" if inert else criteria_status
    if failed:
        outcome = "NO_PROPOSAL"
    elif inert:
        outcome = "PROPOSAL_INCOMPLETE" if incomplete else "NO_PROPOSAL"
    elif incomplete:
        outcome = "PROPOSAL_INCOMPLETE"
    else:
        outcome = "PROPOSAL"
    return PromotionVerdict(
        outcome=outcome,
        criteria_status=status,
        rows=tuple(rows),
        failed=failed,
        inert=inert,
    )


def render_rationale(verdict: PromotionVerdict) -> str:
    """Human-readable verdict. States PROVISIONAL on both outcomes."""
    provisional = ""
    if verdict.criteria_status == "PROVISIONAL":
        provisional = (
            "criteria_status: PROVISIONAL. Adapted R5 criteria "
            f"({PROVISIONAL_TAG}) have not been lifted.\n"
        )
    inert = ", ".join(verdict.inert) if verdict.inert else "none"
    failed = ", ".join(verdict.failed) if verdict.failed else "none"
    return (
        "This mechanism never arms a family and never promotes on its own.\n"
        f"Outcome: {verdict.outcome}.\n"
        f"{provisional}"
        f"Failed: {failed}. INERT: {inert}.\n"
    )
