#!/usr/bin/env python3
"""PREREG v2 family tally -- CLI sibling of `live_family_tally.py` (v1).

`docs/specs/PREREG_v2_current_rung_hold_DRAFT_2026-09-04.md` rev b and
`docs/plans/FAMILY_TALLY_V2_BLUEPRINT_2026-09-04.md` commit 7. Reads the
SAME 6c scored-trial parquet store `live_family_tally.py` reads
(`breezy.persistence.scored_trial_store`), but scopes to exactly ONE
family (`--family`, required) via its manifest
(`breezy.persistence.family_manifest`) and runs the PREREG v2 sequential
score/strata/verdict rules (`breezy.settlement.current_rung_hold_v2`)
against a group-sequential boundary artefact
(`breezy.persistence.gs_boundary_artefact`) instead of v1's fixed 60/150
Wilson rule. v1 (`live_family_tally.py`, `mb_current_rung_edge_study.py`)
is byte-unmodified and never imported for its BEHAVIOUR here -- only its
PURE classification helpers (`ASK_BANDS`, `classify_ask_band`) are reused
read-only, exactly as `live_family_tally.py` itself already does.

**Independent-reviewer obligations (fail-closed, each with a RED test):**

(a) `_assert_held_matches_pnl_sign` -- refuses any row where
    `held != (pnl > 0)`: the win definition is asserted, never relabelled.
(b) `_assert_no_partial_or_multi_fill` -- refuses any row whose fill
    `qty != 1`. GENUINE SCHEMA GAP (documented, not hidden): `ScoredTrial`
    carries no `qty` column at all -- `trial_scorer.score_trial` receives
    `FilledTrial.qty` (real per-fill data) but never threads it into the
    persisted row. Modifying `trial_scorer.py`/`scored_trial_store.py` is
    out of scope (binding, immutable). This guard is therefore DORMANT
    against today's store (see the function's own docstring) but is fully
    unit-tested against a synthetic adapter that does carry `qty`, so it
    activates the instant any future adapter attaches real qty here.
(c) `_assert_no_raw_score_seq_collisions` -- refuses a `(trial_id,
    score_seq)` collision found by an independent raw parquet scan of the
    store, BEFORE `read_scored_trials`'s own max-score_seq dedup would
    silently resolve an exact tie by file-iteration order.
(d) `_roi_bound_line_v2` -- prints the BCa point estimate (`theta_hat`,
    already on `roi_bound.ROIBound`, never printed by v1's
    `format_roi_bound`) alongside the lower bound/n/B/seed, without
    modifying `roi_bound.py` (out of scope).
(e) the rendered report header states plainly that the 17-column
    `ScoredTrial` schema carries no separate provenance column (the
    family/version barrier is trial_id-prefix + registered
    `d0_climate_day` only) and that the qty guard (b) is dormant.

**Draft gate (build order item 3):** a manifest whose `status !=
"REGISTERED"` renders SHADOW/DIAGNOSTIC output only -- no SURVIVE/KILL/
CONTINUE verdict vocabulary is ever printed for a DRAFT_NOT_REGISTERED
family (`render_markdown_v2`).

**Look ordering (documented decision, blueprint SS8 gap):** `ScoredTrial`
carries no fill timestamp, so "every `look_step` filled Takes" cannot be
replayed in true fill-time order from this store. `climate_day` (the D0
discriminant's own field) is used as the chronological proxy, tie-broken
by `trial_id` for a fully deterministic replay -- see `_ordered_for_looks`.

**Truncation reason for a naturally-exhausted schedule (documented
decision):** `TruncationReason` has exactly three members (D0_165,
LOSS_STOP, I_MAX) and is landed/frozen elsewhere (not editable here). "n =
n_max reached with I < i_max" -- the spec's third terminal trigger (rev b
SS3) -- has no dedicated enum member; this driver reports it as `I_MAX`
(both represent the trial's information/sample budget being exhausted,
never a calendar or loss event), which is behaviourally identical inside
`terminal_look` (only `LOSS_STOP` is special-cased there).

No network. No repo writes except `--output`.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Final, Protocol, cast

import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fill_time_count import count_filled_takes
from mb_current_rung_edge_study import ASK_BANDS, classify_ask_band  # v1, read-only reuse
from score_live_trials import (
    FillSourceUnreadableError,
    StorePositiveControlFailedError,
    compute_residual,
    read_filled_trials_state_db,
)
from structural_dead_stop import StructuralDeadVerdict, structural_dead

from breezy.persistence.family_manifest import FamilyManifest, load_family_manifest
from breezy.persistence.gs_boundary_artefact import BoundaryArtefact, load_boundary_artefact
from breezy.persistence.realized_draws import (
    admissible_scored_trials,
    stratum_row_from_scored_trial,
)
from breezy.persistence.residual_fills import (
    EXCLUDED_FILLS_FILENAME,
    RESIDUAL_EXCLUSION_REASONS,
    ExcludedFill,
    ExcludedFillsMalformed,
)
from breezy.persistence.residual_fills import read_excluded_fills as _read_excluded_fills
from breezy.persistence.residual_fills import residual_trial_ids as _residual_trial_ids
from breezy.persistence.scored_trial_store import SCORED_TRIAL_SCHEMA, read_scored_trials
from breezy.runtime.health import AlertPayload, emit_alert, resolve_alert_sink
from breezy.settlement.current_rung_hold_v2 import (
    CombinedDraw,
    ScoreState,
    StationDayAdmissionRefusal,
    StratumRow,
    StratumV2,
    TruncationReason,
    build_stratum_v2,
    combine_station_day,
    information_fraction,
    look_verdict,
    score_combined,
    terminal_look,
)
from breezy.settlement.family_barrier import (
    FamilyBarrierRefusal,
    FamilyIdentity,
    assert_family_only,
)
from breezy.settlement.roi_bound import ROIBound, ROIInputRow, compute_roi_bound, format_roi_bound
from breezy.settlement.trial_scorer import ScoredTrial

__all__ = [
    "STRATUM_TABLE_DIVIDER",
    "STRATUM_TABLE_HEADER",
    "CoverageRow",
    "ExcludedFill",
    "FamilyBarrierRefusal",
    "FamilyStoreContaminationError",
    "FamilyTallyV2",
    "LookRecord",
    "ProvenanceRefusal",
    "ResidualScoredContradictionError",
    "ScoredTrialDataIntegrityError",
    "assert_residual_contradictions_excluded",
    "build_family_tally_v2",
    "coverage_rows",
    "filter_rows_to_manifest_prefix",
    "main",
    "read_excluded_fills",
    "render_markdown_v2",
    "residual_scored_contradictions",
    "residual_trial_ids",
]

#: B1 (ruling Q4): the only value `family_tally_v2.py` ever admits for a
#: `--store-dir`'s `provenance.json` sidecar. `score_live_trials.py` is the
#: sole writer of `"live"`; a paper-replay code path never writes this
#: sidecar at all, so an unmarked store is refused exactly like an
#: explicitly `"paper_replay"`-marked one.
_LIVE_PROVENANCE_VALUE: Final[str] = "live"
_PROVENANCE_SIDECAR_NAME: Final[str] = "provenance.json"

#: Live latch key prefix -- the fill-time count must never see paper_replay
#: rows (`fill_time_count.py` startswith this prefix). Restated, not derived
#: from `len(scored)`.
_LIVE_TRIAL_ID_PREFIX: Final[str] = "current_rung_hold/trial/"

#: Three-seam Slice 4 review item 4: the v3 continuous-rung-hold family's
#: trial-id prefix. `main()` derives `residual` from the SAME `--fill-source`
#: store only when a manifest carries this prefix; v2 never does (`residual`
#: stays `Decimal(0)` for v2, pinned by `test_residual_defaults_to_zero_...`
#: in `test_family_tally_v2.py`).
_CONTINUOUS_TRIAL_ID_PREFIX: Final[str] = "continuous_rung_hold/trial/"

#: The only family whose CLI requires the three structural-dead population
#: args (L-28). The wrapper keeps its own ``$PM_FAMILY`` copy.
_PM_US_CRH_V2_FAMILY_ID: Final[str] = "pm_us_crh_v2"

#: v1 SS6:124-128, restated (never imported -- `mb_current_rung_edge_study`
#: has no module-level constant for this; it is inlined in prose there).
LOSS_STOP_PNL: Final[Decimal] = Decimal(-60)

STRATUM_TABLE_HEADER = (
    "| stratum | n | k | mean ask | mean BE (pi) | Wilson-lower | Wilson-upper | |"
)
STRATUM_TABLE_DIVIDER = "|---|---:|---:|---:|---:|---:|---:|---|"


logger = logging.getLogger(__name__)


class ScoredTrialDataIntegrityError(Exception):
    """An independent-reviewer fail-closed guard refused the whole tally."""


class FamilyStoreContaminationError(ScoredTrialDataIntegrityError):
    """A store declared single-family contains rows outside the manifest prefix."""


class ResidualScoredContradictionError(ScoredTrialDataIntegrityError):
    """R2/R4 (ruling `docs/evidence/RULING_v3_admissibility_divergence_2026-09-20.md`):
    a `trial_id` the scorer recorded in a PREREG v3 §5 residual bucket is
    STILL in the tally's admitted set.

    The contradiction itself (a residual sidecar entry whose `trial_id` also
    has a scored parquet row) is resolved in the only direction §5 allows --
    the row is dropped, `n` SHRINKS -- and is named, counted and reported
    rather than refused, so a store carrying the known 2026-09-15 MIA `^no`
    contradiction still renders. This refusal is the fail-closed guard on
    that resolution: if residual strictness is ever reduced and such a
    trial_id is readmitted, the whole tally refuses instead of silently
    inflating `n` on a sequential test that is spending alpha.
    """


class ProvenanceRefusal(ScoredTrialDataIntegrityError):
    """B1 (ruling Q4): `--store-dir` lacks a v2 live-provenance sidecar, or
    the sidecar declares a provenance other than `"live"` (e.g.
    `"paper_replay"`)."""


#: WP-31: the `excluded_fills.jsonl` reader and its PREREG v3 §5 residual
#: vocabulary are EXTRACTED to `breezy.persistence.residual_fills` so `src/`
#: consumers (which cannot import a script) share ONE definition rather than
#: copying it. Re-exported unchanged -- `ExcludedFill`, `read_excluded_fills`
#: and every refusal message are byte-identical, and this module's public
#: `__all__` surface is unchanged.
_EXCLUDED_FILLS_FILENAME: Final[str] = EXCLUDED_FILLS_FILENAME


@dataclass(frozen=True, slots=True, kw_only=True)
class CoverageRow:
    """One `(reason, station, climate_day)` count in the I3c coverage
    table -- reporting only (dn = dk = dI = dS = 0)."""

    reason: str
    station: str
    climate_day: str
    count: int


@dataclass(frozen=True, slots=True, kw_only=True)
class LookRecord:
    """One completed look (interim or terminal) of the pooled sequential test."""

    look_n: int
    t: float
    state: ScoreState
    b_eff: float
    b_fut: float
    verdict: str
    terminal: bool
    reason: TruncationReason | None
    #: B7 (report string only, never a new `TruncationReason` member): True
    #: exactly for the natural "n == n_max reached with I < i_max" trigger
    #: (rev b SS3's third terminal trigger) -- `reason` itself stays
    #: `TruncationReason.I_MAX` either way; this only tells the renderer to
    #: print `terminal=n_max_reached` instead of `truncation=I_MAX` for
    #: this specific sub-case.
    n_max_reached_below_i_max: bool = False


@dataclass(frozen=True, slots=True, kw_only=True)
class FamilyTallyV2:
    """The full v2 result: strata, look-by-look sequential trail, and the
    terminal-only BCa line."""

    family_id: str
    manifest_sha256: str
    boundary_inputs_sha256: str
    status: str
    n_scored: int
    n_excluded: int
    pooled: StratumV2 | None
    station_strata: tuple[StratumV2, ...]
    ask_band_strata: tuple[StratumV2, ...]
    looks: tuple[LookRecord, ...]
    verdict: str
    total_pnl: Decimal
    bca_line: str | None
    structural_dead: StructuralDeadVerdict | None
    #: R2(b): `--store-dir` had NO scored-trial rows AND no `provenance.json`
    #: sidecar -- the state before `score_live_trials.py` has ever run
    #: against a fresh live node with zero fills so far. Treated as n=0,
    #: never refused (unlike a store WITH rows and no/mismatched sidecar,
    #: which still refuses via `_assert_live_provenance`).
    store_empty_no_sidecar: bool = False
    #: R1 (ruling 2026-09-20): scored rows dropped because their `trial_id`
    #: appears in `excluded_fills.jsonl` in a PREREG v3 §5 residual bucket
    #: -- counted separately from the parquet `excluded_reason` drops, both
    #: of which are inside `n_excluded`.
    n_residual_excluded: int = 0
    #: R2: the `trial_id`s that are BOTH a scored parquet row AND a residual
    #: sidecar entry -- a reconciliation contradiction, never silent.
    residual_scored_contradictions: tuple[str, ...] = ()
    #: AUD-05 D-A(ii): label for the pooled mean-ask cell. ``""`` on an
    #: all-YES corpus, so the rendered report stays byte-identical. Not a
    #: statistic: `cell_dead` and the sequential score never read it.
    pooled_side_mix: str = ""
    #: One label per rendered `(*station_strata, *ask_band_strata)` element.
    strata_side_mix: tuple[str, ...] = ()


def _assert_held_matches_pnl_sign(rows: Sequence[ScoredTrial]) -> None:
    """Obligation (a): `held` and the scored `pnl`'s sign must never
    disagree -- the win definition is asserted, never relabelled by a
    downstream consumer."""
    offenders = tuple(row.trial_id for row in rows if row.held != (row.pnl > 0))
    if offenders:
        raise ScoredTrialDataIntegrityError(
            "refusing to tally: held/pnl-sign mismatch on trial_id(s) "
            f"{offenders!r} -- held must never disagree with sign(pnl)"
        )


def _assert_no_partial_or_multi_fill(rows: Sequence[object]) -> None:
    """Obligation (b): refuse any row whose fill `qty != 1`
    (`reason=partial_or_multi_fill`) -- a strategy-lead ruling on weighting
    is pending, so v2 must not silently score such rows.

    See the module docstring's "(b)" entry: `ScoredTrial` carries no `qty`
    column, so this is checked via `getattr(row, "qty", None)`, which
    returns `None` (never refuses) for every real store row today. The
    default-to-1 semantics match `trial_scorer.score_trial`'s own
    `pnl = 1{held} - fill_px - fee` formula, which has no qty term at all
    -- i.e. every persisted row is *already* qty=1 arithmetic by
    construction of the (immutable, out-of-scope) upstream scorer.
    """
    offenders = []
    for row in rows:
        qty = getattr(row, "qty", None)
        if qty is None:
            continue
        if Decimal(str(qty)) != 1:
            offenders.append(getattr(row, "trial_id", repr(row)))
    if offenders:
        raise ScoredTrialDataIntegrityError(
            "refusing to tally: partial_or_multi_fill on trial_id(s) "
            f"{offenders!r} -- qty != 1 requires a pending strategy-lead "
            "weighting ruling; v2 must not silently score these"
        )


def _assert_no_raw_score_seq_collisions(
    store_dir: Path, *, trial_id_prefix: str | None = None
) -> None:
    """Obligation (c): refuse a `(trial_id, score_seq)` collision found in
    the RAW parquet corpus, before `read_scored_trials`'s own max-score_seq
    dedup would silently resolve an exact-score_seq tie by file-iteration
    order (`current is None or trial.score_seq > current.score_seq` never
    updates on an EQUAL score_seq, so it keeps whichever file sorts first).

    Performs its own scan directly against the store's files -- restating
    the `scored_trials_*.parquet` glob and reusing the PUBLIC
    `SCORED_TRIAL_SCHEMA` export -- rather than modifying
    `scored_trial_store.py` (binding, out of scope).

    `trial_id_prefix`, if given, scopes the scan to rows in that family: a
    `--store-dir` may be shared across families (the reviewer-noted default,
    `score_live_trials.py:131`'s single scorer dir), so a collision entirely
    within a FOREIGN family's rows must never abort this family's tally.
    """
    if not store_dir.exists():
        return
    seen: dict[tuple[str, int], Path] = {}
    collisions: list[str] = []
    for path in sorted(store_dir.glob("scored_trials_*.parquet")):
        table = pq.read_table(path, schema=SCORED_TRIAL_SCHEMA)
        for row in table.to_pylist():
            if trial_id_prefix is not None and not row["trial_id"].startswith(trial_id_prefix):
                continue
            key = (row["trial_id"], row["score_seq"])
            prior = seen.get(key)
            if prior is not None and prior != path:
                collisions.append(f"{key!r} in both {prior.name} and {path.name}")
            else:
                seen[key] = path
    if collisions:
        raise ScoredTrialDataIntegrityError(
            "refusing to tally: (trial_id, score_seq) collision(s) in the raw "
            "store (never resolved by first-file-wins): " + "; ".join(collisions)
        )


def _assert_live_provenance(store_dir: Path) -> None:
    """B1 (ruling Q4): refuse any `--store-dir` without a
    `<store_dir>/provenance.json` sidecar declaring `provenance == "live"`.

    Written by `score_live_trials.py` (the sole live writer); a paper-replay
    code path never writes this sidecar, so an unmarked store is refused
    the same as an explicitly `"paper_replay"`-marked one -- both fail
    closed, never silently admitted.
    """
    sidecar = store_dir / _PROVENANCE_SIDECAR_NAME
    if not sidecar.exists():
        raise ProvenanceRefusal(
            f"refusing to tally {store_dir}: no {_PROVENANCE_SIDECAR_NAME} sidecar -- "
            "v2 requires provenance=='live' (ruling Q4); a paper-replay store never "
            "writes this sidecar, so it is refused the same as one explicitly "
            "marked 'paper_replay'"
        )
    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    provenance = payload.get("provenance")
    if provenance != _LIVE_PROVENANCE_VALUE:
        raise ProvenanceRefusal(
            f"refusing to tally {store_dir}: {_PROVENANCE_SIDECAR_NAME} declares "
            f"provenance={provenance!r}, not {_LIVE_PROVENANCE_VALUE!r} (ruling Q4)"
        )


#: WP-31: ONE definition, extracted to `breezy.persistence.realized_draws`
#: so the realized-outcome loader and this tally build the SAME `StratumRow`
#: from a `ScoredTrial` -- side/rung derived from `instrument_id`, `held`
#: passed through uninverted. Behaviour byte-unchanged.
_stratum_row = stratum_row_from_scored_trial


def _load_fill_order_index(store_dir: Path) -> dict[tuple[str, int], int]:
    """`(trial_id, score_seq) -> filled_at_ns` from the v2-only
    `fill_order.jsonl` sidecar `score_live_trials.py` appends (B3)."""
    path = store_dir / "fill_order.jsonl"
    index: dict[tuple[str, int], int] = {}
    if not path.exists():
        return index
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        index[(row["trial_id"], row["score_seq"])] = row["filled_at_ns"]
    return index


def _ordered_for_looks(
    rows: Sequence[ScoredTrial], *, store_dir: Path | None = None
) -> tuple[ScoredTrial, ...]:
    """Ordering for the sequential-look replay -- see module docstring
    "Look ordering".

    B3 (v2-only): when `store_dir` is given, order is
    `(filled_at_ns, climate_day, trial_id)`, joined against the
    `fill_order.jsonl` sidecar `score_live_trials.py` appends for every
    scored fill -- REFUSED fail-closed (naming the trial_id) if any row
    here has no matching `(trial_id, score_seq)` sidecar entry. When
    `store_dir` is `None` (driver-level unit tests exercising strata/verdict
    logic against synthetic rows with no real store), the prior
    `(climate_day, trial_id)` chronological-proxy ordering is used
    unchanged.
    """
    if store_dir is None:
        return tuple(sorted(rows, key=lambda r: (r.climate_day, r.trial_id)))
    fill_order = _load_fill_order_index(store_dir)
    missing = [r.trial_id for r in rows if (r.trial_id, r.score_seq) not in fill_order]
    if missing:
        raise ScoredTrialDataIntegrityError(
            "refusing to order looks: no fill_order.jsonl sidecar entry for "
            f"trial_id(s) {missing!r} -- score_live_trials.py must append one per "
            "admitted fill (B3)"
        )
    return tuple(
        sorted(
            rows,
            key=lambda r: (fill_order[(r.trial_id, r.score_seq)], r.climate_day, r.trial_id),
        )
    )


def _combined_draws_for_looks(
    ordered: Sequence[ScoredTrial],
) -> tuple[CombinedDraw, ...]:
    """S4a (plan MULTI_POSITION_PER_STATION_2026-09-14, R3-2/R3-3): one
    combined draw per `(station, climate_day)`, ordered by the EARLIEST
    constituent fill.

    `ordered` is already fill-ordered by :func:`_ordered_for_looks`, so
    grouping by first-seen `(station, climate_day)` preserves that order --
    no separate fill-time lookup is needed here. A station-day whose
    constituent break-evens sum above 1 is refused as `malformed_input`
    (`StationDayAdmissionRefusal`, raised at draw construction, never
    post-hoc) rather than silently admitted.
    """
    groups: dict[tuple[str, str], list[StratumRow]] = {}
    order: list[tuple[str, str]] = []
    for trial in ordered:
        key = (trial.station, trial.climate_day)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(_stratum_row(trial))
    draws: list[CombinedDraw] = []
    for key in order:
        try:
            draws.append(combine_station_day(groups[key]))
        except StationDayAdmissionRefusal as exc:
            raise ScoredTrialDataIntegrityError(
                f"refusing to tally station-day {key!r}: {exc} (malformed_input)"
            ) from exc
    return tuple(draws)


def _station_strata(rows: Sequence[ScoredTrial]) -> tuple[StratumV2, ...]:
    by_station: dict[str, list[ScoredTrial]] = defaultdict(list)
    for row in rows:
        by_station[row.station].append(row)
    strata = (
        build_stratum_v2(f"station:{station}", tuple(_stratum_row(t) for t in by_station[station]))
        for station in sorted(by_station)
    )
    return tuple(s for s in strata if s is not None)


def _ask_band_strata(rows: Sequence[ScoredTrial]) -> tuple[StratumV2, ...]:
    by_band: dict[tuple[float, float], list[ScoredTrial]] = defaultdict(list)
    for row in rows:
        by_band[classify_ask_band(float(row.entry_ask))].append(row)
    strata: list[StratumV2] = []
    for lo, hi in ASK_BANDS:
        group = by_band.get((lo, hi), [])
        stratum = build_stratum_v2(f"ask:({lo},{hi}]", tuple(_stratum_row(t) for t in group))
        if stratum is not None:
            strata.append(stratum)
    return tuple(strata)


def _roi_bound_line_v2(rows: Sequence[ScoredTrial]) -> str:
    """Obligation (d): `format_roi_bound`'s pinned string, PLUS the BCa
    point estimate `theta_hat` (already on `ROIBound`, never printed by
    v1's formatter) -- `roi_bound.py` itself is not modified."""
    inputs = tuple(
        ROIInputRow(pnl=t.pnl, cost=t.fill_px + t.fee, excluded_reason=t.excluded_reason)
        for t in rows
    )
    result = compute_roi_bound(inputs)
    base = format_roi_bound(result)
    if isinstance(result, ROIBound):
        return f"{base}; theta_hat (BCa point estimate) = {result.theta_hat}"
    return base


def filter_rows_to_manifest_prefix(
    rows: Sequence[ScoredTrial],
    manifest: FamilyManifest,
    *,
    store_declared_single_family: bool = True,
) -> tuple[ScoredTrial, ...]:
    """Keep rows whose trial_id starts with ``manifest.trial_id_prefix``.

    Every dropped row is counted and logged. A store declared single-family
    that still contains non-manifest rows is REFUSED (not silently dropped).
    Callers that have already isolated the batch (kept rows only) pass
    ``store_declared_single_family=False``.
    """
    kept: list[ScoredTrial] = []
    dropped: list[str] = []
    for row in rows:
        if row.trial_id.startswith(manifest.trial_id_prefix):
            kept.append(row)
        else:
            dropped.append(row.trial_id)
    if dropped:
        logger.warning(
            "family_tally_v2: dropped %d non-manifest row(s) (prefix %r): %s",
            len(dropped),
            manifest.trial_id_prefix,
            dropped,
        )
        if store_declared_single_family:
            raise FamilyStoreContaminationError(
                f"store declared single-family contains {len(dropped)} non-manifest "
                f"row(s); refusing rather than silently dropping"
            )
    return tuple(kept)


class _BoundaryFn(Protocol):
    """The exact call shape `run_sequential_looks` needs off `boundary_fn`
    -- structurally satisfied by `BoundaryArtefact.boundary_for` (a bound
    method, `t_history: Sequence[float], *, is_terminal: bool = False`)
    without importing it as a nominal type. Every call site here passes
    `is_terminal` explicitly (never relies on a default), so it is
    declared required, matching actual usage exactly rather than merely
    matching `boundary_for`'s own (wider) signature."""

    def __call__(
        self, t_history: tuple[float, ...], *, is_terminal: bool
    ) -> tuple[float, float]: ...


def run_sequential_looks(
    combined_draws: Sequence[CombinedDraw],
    *,
    artefact: BoundaryArtefact,
    boundary_fn: _BoundaryFn,
    total_pnl: Decimal,
    residual: Decimal,
    cell_dead: bool,
    structural_fired: bool,
    registered: bool,
    truncation: TruncationReason | None,
) -> tuple[tuple[LookRecord, ...], str, bool]:
    """Replay the pooled sequential look loop (rev b Sec 3/4), including the
    off-grid truncation tail -- extracted verbatim from
    `build_family_tally_v2` (AUD-07 amendment Stage M1b, L-33
    characterisation: `tests/unit/test_family_tally_v2_look_loop_golden.py`
    pins this function's behaviour unchanged by the extraction).

    Returns `(looks, verdict, decided)`. `decided` is `True` exactly when a
    terminal or non-CONTINUE interim verdict was reached (main loop `break`,
    or the off-grid tail ran) -- the caller computes `bca_line` (via
    `_roi_bound_line_v2`, which needs `roi_rows`, a caller-only concern)
    only when `decided` is `True`, byte-identical to the pre-extraction
    `bca_line is None` cases (structural KILL with zero looks; a plain
    CONTINUE below `look_step` with no truncation).

    `boundary_fn` is a separate parameter from `artefact` (whose
    `i_max`/`spending.look_step`/`spending.n_max` are still read here) so a
    future streaming solver (plan §4 M1c) can pass its own `(t_history,
    is_terminal) -> (b_eff, b_fut)` callable without touching this loop --
    production always passes `artefact.boundary_for`.
    """
    n = len(combined_draws)
    look_step = artefact.spending.look_step
    n_max = artefact.spending.n_max

    looks: list[LookRecord] = []
    t_history: list[float] = []
    verdict = "CONTINUE"

    # Structural-dead is a separate KILL authority: never overwritten by a
    # later look_verdict/terminal_look assignment. Skip the look loop
    # entirely -- no look, no BCa line.
    if structural_fired and registered:
        return (), "KILL", False

    scheduled_ns = range(look_step, min(n, n_max) + 1, look_step)
    for look_n in scheduled_ns:
        state = score_combined(combined_draws[:look_n])
        t = information_fraction(state.information, i_max=artefact.i_max)
        t_history.append(t)

        reached_loss_stop = (total_pnl + residual) <= LOSS_STOP_PNL
        reached_i_max = state.information >= artefact.i_max
        reached_n_max = (
            look_n >= n_max
        )  # B5: >= not == (see load_boundary_artefact's n_max%look_step==0 invariant)
        forced = truncation is not None and look_n == n
        is_terminal = reached_loss_stop or reached_i_max or reached_n_max or forced

        if is_terminal:
            reason = (
                TruncationReason.LOSS_STOP
                if reached_loss_stop
                else (truncation if forced and truncation is not None else TruncationReason.I_MAX)
            )
            n_max_reached_below_i_max = (
                reason is TruncationReason.I_MAX and reached_n_max and not reached_i_max
            )
            b_eff, b_fut = boundary_fn(tuple(t_history), is_terminal=True)
            verdict = terminal_look(
                state,
                reason=reason,
                b_eff=b_eff,
                b_fut=b_fut,
                total_pnl=total_pnl,
                cell_dead=cell_dead,
                structural_fired=structural_fired,
            )
            looks.append(
                LookRecord(
                    look_n=look_n,
                    t=t,
                    state=state,
                    b_eff=b_eff,
                    b_fut=b_fut,
                    verdict=verdict,
                    terminal=True,
                    reason=reason,
                    n_max_reached_below_i_max=n_max_reached_below_i_max,
                )
            )
            return tuple(looks), verdict, True

        b_eff, b_fut = boundary_fn(tuple(t_history), is_terminal=False)
        verdict = look_verdict(
            state,
            b_eff=b_eff,
            b_fut=b_fut,
            total_pnl=total_pnl,
            cell_dead=cell_dead,
            structural_fired=structural_fired,
        )
        looks.append(
            LookRecord(
                look_n=look_n,
                t=t,
                state=state,
                b_eff=b_eff,
                b_fut=b_fut,
                verdict=verdict,
                terminal=False,
                reason=None,
            )
        )
        if verdict != "CONTINUE":
            return tuple(looks), verdict, True

    already_terminal = bool(looks) and looks[-1].terminal
    if (
        not (structural_fired and registered)
        and truncation is not None
        and not already_terminal
        and combined_draws
    ):
        # An off-grid explicit truncation (n does not land on a look_step
        # boundary): treated as a look too, never a skipped None (rev b
        # SS4).
        state = score_combined(combined_draws)
        t = information_fraction(state.information, i_max=artefact.i_max)
        t_history.append(t)
        b_eff, b_fut = boundary_fn(tuple(t_history), is_terminal=True)
        verdict = terminal_look(
            state,
            reason=truncation,
            b_eff=b_eff,
            b_fut=b_fut,
            total_pnl=total_pnl,
            cell_dead=cell_dead,
            structural_fired=structural_fired,
        )
        looks.append(
            LookRecord(
                look_n=n,
                t=t,
                state=state,
                b_eff=b_eff,
                b_fut=b_fut,
                verdict=verdict,
                terminal=True,
                reason=truncation,
            )
        )
        return tuple(looks), verdict, True

    return tuple(looks), verdict, False


def build_family_tally_v2(
    rows: Sequence[ScoredTrial],
    *,
    manifest: FamilyManifest,
    artefact: BoundaryArtefact,
    store_dir: Path | None = None,
    covered_listed_station_days: int | None = None,
    filled_takes: int | None = None,
    truncation: TruncationReason | None = None,
    residual: Decimal = Decimal(0),
) -> FamilyTallyV2:
    """Build the pooled sequential trail, strata, and terminal-only BCa line.

    `store_dir`, if given, is scanned independently for obligation (c)
    (never re-derived from `rows`, which is already deduped by the time it
    reaches this function). `truncation`, if given, forces a terminal look
    at the CURRENT `n` (an off-grid look, per rev b SS4) with the given
    reason -- used for an explicit `--truncate` CLI override; `LOSS_STOP`
    and the natural `I_MAX`/`n_max` triggers are otherwise auto-detected
    from the data at each scheduled look.

    `residual` (Slice 4 item B2, plan rev 6.1): the caller's own
    `score_live_trials.compute_residual` dollar sum over unscored fills
    (`duplicate_fill`/`q != 1`/fee-unreconciled) -- defaults to `Decimal(0)`,
    so every existing caller/pinned test that never passes it is
    byte-identical. The `LOSS_STOP` gate fires on `total_pnl + residual`,
    never `total_pnl` alone, so a family with real, unscored dollar losses
    cannot look SURVIVE just because the losing fills never entered `rows`.
    """
    # Prefix-filter FIRST, before any integrity/collision/empty-store guard:
    # a foreign (e.g. v3) row must be counted, logged, and refused (or
    # dropped -- store_declared_single_family callers) here, never allowed to
    # trip a v2-scoped guard below on a row that was never v2's to begin
    # with. Also runs BEFORE assert_family_only so a v3 row cannot trip the
    # v2 family barrier either.
    rows = filter_rows_to_manifest_prefix(rows, manifest, store_declared_single_family=True)
    _assert_held_matches_pnl_sign(rows)
    _assert_no_partial_or_multi_fill(rows)
    store_empty_no_sidecar = False
    if store_dir is not None:
        _assert_no_raw_score_seq_collisions(store_dir, trial_id_prefix=manifest.trial_id_prefix)
        sidecar_exists = (store_dir / _PROVENANCE_SIDECAR_NAME).exists()
        if not rows and not sidecar_exists:
            # R2(b): an empty store with no sidecar yet is not a refusal --
            # it is the state before score_live_trials.py has ever run
            # against this live node (zero fills so far). A store WITH
            # rows and no/mismatched sidecar still refuses below.
            store_empty_no_sidecar = True
        else:
            _assert_live_provenance(store_dir)
    # `FamilyManifest` (frozen/slots) satisfies `FamilyIdentity` structurally,
    # but mypy's Protocol check wants a settable attribute for a frozen
    # dataclass field; `live_family_tally.py`'s own `_PricedRow`/
    # `CurrentRungTrial` adapter uses the identical `cast` for the same
    # structural-typing reason.
    assert_family_only(rows, cast(FamilyIdentity, manifest))

    # R1 (ruling `docs/evidence/RULING_v3_admissibility_divergence_2026-09-20.md`):
    # admissibility is NOT the parquet `excluded_reason` column alone. A
    # `trial_id` the scorer recorded in a PREREG v3 §5 residual bucket in
    # `excluded_fills.jsonl` is not admissible whatever that column says --
    # otherwise a fill this family's OWN scorer classified residual still
    # counts toward `n` on a sequential test that is spending alpha. The
    # predicate is `breezy.persistence.realized_draws.admissible_scored_trials`
    # (the WP-31 §5 loader's own, reused not re-written), so the tally's `n`
    # and `load_realized_draws`'s admissible count cannot drift apart.
    residual_ids = residual_trial_ids(store_dir) if store_dir is not None else frozenset()
    non_excluded = admissible_scored_trials(tuple(rows), residual_trial_ids=residual_ids)
    contradictions = tuple(
        sorted({row.trial_id for row in rows if row.trial_id in residual_ids})
    )
    assert_residual_contradictions_excluded(
        contradictions,
        admitted_trial_ids=frozenset(row.trial_id for row in non_excluded),
        store_declared_single_family=True,
    )
    ordered = _ordered_for_looks(non_excluded, store_dir=store_dir)
    pooled_rows = tuple(_stratum_row(t) for t in ordered)
    pooled = build_stratum_v2("pooled", pooled_rows) if pooled_rows else None
    pooled_side_mix = _side_mix_label(pooled_rows) if pooled_rows else ""
    # S4a (R3-2/R3-3): the registered statistic scores one COMBINED draw per
    # station-day, never per raw fill -- `pooled`/`station_strata`/
    # `ask_band_strata` above stay per-fill (Wilson cell_dead diagnostics are
    # unaffected by the trial-unit change). At qty=1 with one fill per
    # station-day this is a 1:1 relabelling of `pooled_rows` (the byte-
    # identity regression floor), never a behaviour change.
    combined_draws = _combined_draws_for_looks(ordered)
    station_strata = _station_strata(non_excluded)
    ask_band_strata = _ask_band_strata(non_excluded)
    strata_side_mix = (
        *_station_side_mixes(non_excluded),
        *_ask_band_side_mixes(non_excluded),
    )
    any_cell_dead = any(s.cell_dead for s in (*station_strata, *ask_band_strata))

    total_pnl = sum((row.pnl for row in non_excluded), start=Decimal(0))
    # R1/R4: `_roi_bound_line_v2` applies `excluded_reason` itself (via
    # `ROIInputRow`), but knows nothing of the residual sidecar -- so the
    # residual rows are withheld here. Without this the BCa line would keep
    # pricing a fill that §5 excludes from `n`, i.e. the same over-admission
    # in the reported ROI bound. Byte-identical whenever there is no residual
    # sidecar entry (every synthetic-row caller).
    roi_rows = tuple(row for row in rows if row.trial_id not in residual_ids)

    if filled_takes is not None and filled_takes < len(rows):
        raise ValueError(
            f"filled_takes={filled_takes} is less than len(rows)={len(rows)}: a "
            "fill-time count can only be a superset of the settled/scored rows; "
            "this looks like a settled-only count, which must never be passed here"
        )

    structural = (
        None
        if covered_listed_station_days is None
        else structural_dead(
            covered_listed_station_days=covered_listed_station_days, filled_takes=filled_takes
        )
    )
    structural_fired = structural is not None and structural.structural_dead

    registered = manifest.status == "REGISTERED"

    looks, verdict, decided = run_sequential_looks(
        combined_draws,
        artefact=artefact,
        boundary_fn=artefact.boundary_for,
        total_pnl=total_pnl,
        residual=residual,
        cell_dead=any_cell_dead,
        structural_fired=structural_fired,
        registered=registered,
        truncation=truncation,
    )
    bca_line = _roi_bound_line_v2(roi_rows) if decided else None

    return FamilyTallyV2(
        family_id=manifest.family_id,
        manifest_sha256=manifest.manifest_sha256,
        boundary_inputs_sha256=artefact.inputs_sha256,
        status=manifest.status,
        n_scored=len(rows),
        n_excluded=len(rows) - len(non_excluded),
        n_residual_excluded=len(contradictions),
        residual_scored_contradictions=contradictions,
        pooled=pooled,
        pooled_side_mix=pooled_side_mix,
        station_strata=station_strata,
        ask_band_strata=ask_band_strata,
        strata_side_mix=strata_side_mix,
        looks=tuple(looks),
        verdict=verdict,
        total_pnl=total_pnl,
        bca_line=bca_line,
        structural_dead=structural,
        store_empty_no_sidecar=store_empty_no_sidecar,
    )


def _side_mix_label(rows: Sequence[StratumRow]) -> str:
    """Disclosure for a mixed-domain mean ask. Empty on an all-YES group."""
    if not rows:
        return ""
    n_yes = sum(1 for row in rows if row.side == "yes")
    n_no = len(rows) - n_yes
    if n_no == 0:
        return ""
    if n_yes == 0:
        return " (NO-only)"
    return f" (mixed-side: Y{n_yes}/N{n_no})"


def _station_side_mixes(rows: Sequence[ScoredTrial]) -> tuple[str, ...]:
    by_station: dict[str, list[ScoredTrial]] = defaultdict(list)
    for row in rows:
        by_station[row.station].append(row)
    return tuple(
        _side_mix_label(tuple(_stratum_row(trial) for trial in by_station[station]))
        for station in sorted(by_station)
    )


def _ask_band_side_mixes(rows: Sequence[ScoredTrial]) -> tuple[str, ...]:
    by_band: dict[tuple[float, float], list[ScoredTrial]] = defaultdict(list)
    for row in rows:
        by_band[classify_ask_band(float(row.entry_ask))].append(row)
    mixes: list[str] = []
    for lo, hi in ASK_BANDS:
        group = by_band.get((lo, hi), [])
        if not group:
            continue
        mixes.append(_side_mix_label(tuple(_stratum_row(trial) for trial in group)))
    return tuple(mixes)


_SIDE_MIX_FOOTNOTE = (
    "mean ask is a per-leg average in each leg's OWN price domain; a NO leg's "
    "ask is not comparable with a YES leg's. Annotated cells mix domains and "
    "must not be read as one price. pi = mean(BE_i) is unaffected: "
    "E[held_i] = BE_i on both sides (see the family manifest and PREREG v3 "
    "amendment NO_SIDE 2026-09-14 §3)."
)


def _fmt_stratum_row(stratum: StratumV2, *, side_mix: str = "") -> str:
    dead = "CELL-DEAD" if stratum.cell_dead else ""
    return (
        f"| {stratum.label} | {stratum.n} | {stratum.k} | "
        f"{stratum.mean_ask:.4f}{side_mix} | "
        f"{stratum.pi:.4f} | {stratum.wilson_lower:.4f} | {stratum.wilson_upper:.4f} | {dead} |"
    )


def failure_detail_from_log(log_text: str) -> str:
    """Exception class and ``file:line`` only.

    The exception message is dropped: it can carry a currency figure, and
    the alert detail must not.
    """
    file_line = "family_tally_v2.py:0"
    exc_name = "FamilyTallyFailed"
    for line in log_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("File ") and ", line " in stripped:
            try:
                path_part = stripped.split('"', 2)[1]
                line_no = stripped.split(", line ", 1)[1].split(",", 1)[0].strip()
            except IndexError:
                continue
            if line_no.isdigit():
                file_line = f"{Path(path_part).name}:{line_no}"
            continue
        if ":" not in stripped or stripped.startswith("Traceback"):
            continue
        head = stripped.split(":", 1)[0].strip()
        if head.isidentifier():
            exc_name = head
    return f"{exc_name} at {file_line}"


def _latch_keys(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    if not isinstance(payload, list):
        return set()
    return {item for item in payload if isinstance(item, str)}


def _write_latch(path: Path, keys: set[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sorted(keys)), encoding="utf-8")


def emit_family_tally_failure_alert(
    *,
    family_id: str,
    log_text: str,
    latch_path: Path,
    today_utc: str,
    sink: object | None = None,
) -> bool:
    """One CRITICAL ``FAMILY_TALLY_FAILED`` per ``(family_id, UTC day)``.

    Returns True when an alert was emitted. A repeat the same day returns
    False and does not page again.
    """
    key = f"{family_id}|{today_utc}"
    keys = _latch_keys(latch_path)
    if key in keys:
        return False
    payload = AlertPayload(
        severity="CRITICAL",
        event="FAMILY_TALLY_FAILED",
        site=f"breezy-family-tally@{family_id}",
        detail=failure_detail_from_log(log_text),
    )
    emit_alert(resolve_alert_sink() if sink is None else sink, payload)  # type: ignore[arg-type]
    keys.add(key)
    _write_latch(latch_path, keys)
    return True


def read_excluded_fills(store_dir: Path) -> tuple[ExcludedFill, ...]:
    """Read `<store_dir>/excluded_fills.jsonl` (I3c, 3.0(c)).

    Delegates to the ONE implementation
    (`breezy.persistence.residual_fills.read_excluded_fills`, WP-31) and
    re-raises its `ExcludedFillsMalformed` -- message verbatim -- as this
    module's own `ScoredTrialDataIntegrityError`, so every caller's refusal
    type and text are byte-unchanged by the extraction.
    """
    try:
        return _read_excluded_fills(store_dir)
    except ExcludedFillsMalformed as exc:
        raise ScoredTrialDataIntegrityError(str(exc)) from exc


def _dedup_excluded_fills_by_venue_order_id(
    excluded: Sequence[ExcludedFill],
) -> dict[str, ExcludedFill]:
    """I3c count rule: ONE entry per `venue_order_id` -- the line with the
    lexicographically greatest `scored_run_utc` wins (3.0(g), a plain
    string compare); ties (equal `scored_run_utc`) are resolved by
    last-line-wins, since `excluded` is iterated in file order."""
    latest: dict[str, ExcludedFill] = {}
    for fill in excluded:
        current = latest.get(fill.venue_order_id)
        if current is None or fill.scored_run_utc >= current.scored_run_utc:
            latest[fill.venue_order_id] = fill
    return latest


def residual_trial_ids(store_dir: Path) -> frozenset[str]:
    """Every `trial_id` `excluded_fills.jsonl` puts in a PREREG v3 §5
    residual bucket (R1, ruling 2026-09-20).

    Delegates to the ONE definition
    (`breezy.persistence.residual_fills.residual_trial_ids`, which reads via
    `read_excluded_fills`) -- this tally must never carry a second residual
    predicate, which is the drift §5 exists to prevent. A malformed sidecar
    line is re-raised, message verbatim, as this module's own
    `ScoredTrialDataIntegrityError`, exactly as `read_excluded_fills` does.
    """
    try:
        return _residual_trial_ids(store_dir)
    except ExcludedFillsMalformed as exc:
        raise ScoredTrialDataIntegrityError(str(exc)) from exc


def residual_scored_contradictions(
    excluded: Sequence[ExcludedFill], scored_trial_ids: frozenset[str]
) -> tuple[str, ...]:
    """R2: the `trial_id`s that appear BOTH as a scored parquet row and as a
    PREREG §5 residual entry in the sidecar -- the reconciliation
    contradiction that `coverage_rows` used to discard as "already-scored".

    Deduped per `venue_order_id` first (the I3c count rule), sorted, each
    `trial_id` once.
    """
    latest = _dedup_excluded_fills_by_venue_order_id(excluded)
    return tuple(
        sorted(
            {
                fill.trial_id
                for fill in latest.values()
                if fill.trial_id
                and fill.trial_id in scored_trial_ids
                and fill.reason in RESIDUAL_EXCLUSION_REASONS
            }
        )
    )


def assert_residual_contradictions_excluded(
    contradictions: Sequence[str],
    *,
    admitted_trial_ids: frozenset[str],
    store_declared_single_family: bool = True,
) -> None:
    """R2/R4: log every residual/scored contradiction, and REFUSE if any of
    them survived into the admitted set.

    Mirrors `filter_rows_to_manifest_prefix`'s posture for non-manifest rows
    -- counted and logged always, refused when the store is declared
    single-family -- but the refusal fires only on an UNRESOLVED
    contradiction. §5 resolves a residual/scored contradiction
    deterministically in the shrink direction (the row is not admissible),
    so a resolved one is reported, not fatal; an admitted one means residual
    strictness was reduced, which R4 forbids outright.
    """
    if not contradictions:
        return
    logger.warning(
        "family_tally_v2: %d residual/scored contradiction(s) -- trial_id(s) %s carry "
        "BOTH a scored parquet row and a PREREG v3 §5 residual entry in %s; excluded "
        "from n (fail closed, ruling 2026-09-20 R1/R4)",
        len(contradictions),
        list(contradictions),
        EXCLUDED_FILLS_FILENAME,
    )
    still_admitted = tuple(t for t in contradictions if t in admitted_trial_ids)
    if still_admitted and store_declared_single_family:
        raise ResidualScoredContradictionError(
            f"refusing to tally: {len(still_admitted)} residual/scored contradiction(s) "
            f"left in the admitted set -- trial_id(s) {list(still_admitted)!r} are "
            f"recorded in {EXCLUDED_FILLS_FILENAME} in a PREREG v3 §5 residual bucket "
            "and must never count toward n (ruling 2026-09-20 R1/R4)"
        )


def coverage_rows(
    excluded: Sequence[ExcludedFill], scored_trial_ids: frozenset[str]
) -> tuple[CoverageRow, ...]:
    """I3c count rule (strategy-lead Q2: "append-only jsonl is evidence,
    not the count"): dedup to one entry per `venue_order_id`, drop any
    NON-RESIDUAL entry whose `trial_id` already has a scored row (any
    `score_seq`), and group/count the survivors by
    `(reason, station, climate_day)`, sorted.

    R2 (ruling 2026-09-20): a RESIDUAL entry (`RESIDUAL_EXCLUSION_REASONS`)
    whose `trial_id` has a scored row is NEVER dropped here. That case is not
    "the jsonl is stale evidence, the parquet is the count" -- it is a
    contradiction between the two, and dropping it hid precisely the record
    that revealed the tally over-admitting a residual fill. The original drop
    survives unchanged for every non-residual reason (a `no_taken_latch` or
    `ambiguous_latch` line later re-scored), which is the case it was written
    for.
    """
    latest = _dedup_excluded_fills_by_venue_order_id(excluded)
    counts: dict[tuple[str, str, str], int] = defaultdict(int)
    for fill in latest.values():
        if fill.trial_id in scored_trial_ids and fill.reason not in RESIDUAL_EXCLUSION_REASONS:
            continue
        counts[(fill.reason, fill.station, fill.climate_day)] += 1
    return tuple(
        CoverageRow(reason=reason, station=station, climate_day=climate_day, count=count)
        for (reason, station, climate_day), count in sorted(counts.items())
    )


def _coverage_section_lines(store_dir: Path | None) -> list[str]:
    """I3c rendered section -- reporting only, changes no statistic and no
    v2 boundary (dn = dk = dI = dS = 0)."""
    lines: list[str] = [
        "Coverage -- admission exclusions (reporting only; dn = dk = dI = dS = 0)",
        "",
    ]
    artefact_path = None if store_dir is None else store_dir / _EXCLUDED_FILLS_FILENAME
    if artefact_path is None or not artefact_path.exists():
        lines.append("no exclusions recorded (artefact absent)")
        lines.append("")
        return lines
    assert store_dir is not None
    excluded = read_excluded_fills(store_dir)
    scored_trial_ids = frozenset(t.trial_id for t in read_scored_trials(store_dir))
    latest = _dedup_excluded_fills_by_venue_order_id(excluded)
    # R2: "dropped as already-scored" now counts ONLY the non-residual case
    # it was written for; a residual entry whose trial_id has a scored row is
    # a contradiction, reported below, never a drop.
    dropped = sum(
        1
        for fill in latest.values()
        if fill.trial_id in scored_trial_ids and fill.reason not in RESIDUAL_EXCLUSION_REASONS
    )
    contradictions = residual_scored_contradictions(excluded, scored_trial_ids)
    rows = coverage_rows(excluded, scored_trial_ids)
    lines.append("| reason | station | climate_day | count |")
    lines.append("|---|---|---|---:|")
    for row in rows:
        lines.append(f"| {row.reason} | {row.station} | {row.climate_day} | {row.count} |")
    lines.append("")
    lines.append(
        f"artefact: {artefact_path}; lines read: {len(excluded)}; "
        f"distinct venue_order_ids: {len(latest)}; non-residual entries dropped as "
        f"already-scored: {dropped}; residual/scored contradictions: {len(contradictions)}"
    )
    if contradictions:
        lines.append("")
        lines.append(
            f"**residual/scored contradiction ({len(contradictions)})** -- trial_id(s) "
            f"{list(contradictions)!r} carry BOTH a scored parquet row and a PREREG v3 §5 "
            "residual entry in this artefact. §5 resolves this in the shrink direction: "
            "they are NOT admissible and are excluded from n (ruling "
            "docs/evidence/RULING_v3_admissibility_divergence_2026-09-20.md, R1/R4)."
        )
    lines.append("")
    return lines


def render_markdown_v2(tally: FamilyTallyV2, *, source_paths: Sequence[Path], as_of: str) -> str:
    lines: list[str] = []

    def add(line: str) -> None:
        lines.append(line)

    add("# PREREG v2 family tally")
    add("")
    add(f"family_id: {tally.family_id}")
    add(f"manifest_sha256: {tally.manifest_sha256}")
    add(f"boundary_inputs_sha256: {tally.boundary_inputs_sha256}")
    add(f"status: {tally.status}")
    add(f"as_of: {as_of}")
    add(f"row count: {tally.n_scored} (excluded: {tally.n_excluded})")
    if tally.n_residual_excluded:
        add(
            f"residual-sidecar exclusions (PREREG v3 §5, amendment A1 2026-09-20): "
            f"{tally.n_residual_excluded} -- scored row(s) "
            f"{list(tally.residual_scored_contradictions)!r} recorded in "
            f"{EXCLUDED_FILLS_FILENAME} in a residual bucket; NOT admissible, "
            "excluded from n"
        )
    if tally.store_empty_no_sidecar:
        add("store empty; provenance sidecar not yet written")
    add("source parquet: " + ", ".join(str(p) for p in source_paths))
    add("")
    add(
        "provenance barrier (obligation e): the 17-column ScoredTrial "
        "schema carries no separate provenance column -- family/version "
        "scope is enforced by three barriers, ANY of which refuses the "
        "whole tally: trial_id prefix match AND climate_day >= the "
        "registered d0_climate_day AND station in the registered station "
        "census (breezy.settlement.family_barrier.assert_family_only). "
        "In addition, --store-dir must carry a provenance.json sidecar "
        "declaring provenance=='live' (written by score_live_trials.py, "
        "ruling Q4) -- refused if missing or mismatched, except on an "
        "empty store with no sidecar yet (n=0, not a refusal, R2) -- and "
        "every scored fill's sequential-look position is read from the "
        "store's fill_order.jsonl sidecar (B3)."
    )
    add(
        "qty guard (partial_or_multi_fill, obligation b): DORMANT against "
        "this store -- ScoredTrial carries no qty column (dropped upstream "
        "by trial_scorer.score_trial); see family_tally_v2.py module "
        "docstring."
    )
    add("")
    add(STRATUM_TABLE_HEADER)
    add(STRATUM_TABLE_DIVIDER)
    if tally.pooled is not None:
        add(_fmt_stratum_row(tally.pooled, side_mix=tally.pooled_side_mix))
    rendered_strata = (*tally.station_strata, *tally.ask_band_strata)
    for index, stratum in enumerate(rendered_strata):
        side_mix = tally.strata_side_mix[index] if index < len(tally.strata_side_mix) else ""
        add(_fmt_stratum_row(stratum, side_mix=side_mix))
    if tally.pooled_side_mix or any(tally.strata_side_mix):
        add(_SIDE_MIX_FOOTNOTE)
    add("")

    is_shadow = tally.status != "REGISTERED"
    if is_shadow:
        add(
            "**SHADOW / DIAGNOSTIC ONLY** -- family manifest status is "
            f"{tally.status!r}, not REGISTERED. No stopping-rule verdict "
            "vocabulary is issued until registration (blueprint draft gate); "
            "the numeric score/boundary trail below is diagnostic only."
        )
    elif tally.looks:
        last = tally.looks[-1]
        if last.reason is None:
            reason_note = ""
        elif last.n_max_reached_below_i_max:
            # B7: report string only -- `reason` itself stays I_MAX (no new
            # TruncationReason member is ever added for this sub-case).
            reason_note = ", terminal=n_max_reached"
        else:
            reason_note = f", truncation={last.reason.value}"
        add(f"**{tally.verdict}** at look n={last.look_n} (t={last.t:.4f}){reason_note}")
    else:
        structural_fired = (
            tally.structural_dead is not None and tally.structural_dead.structural_dead
        )
        if structural_fired:
            sd = tally.structural_dead
            add(
                f"**{tally.verdict}** -- structural-dead stop fired "
                f"({sd.covered_listed_station_days} covered listed station-days, "
                f"{sd.filled_takes} filled Takes)"
            )
        else:
            add(
                f"**{tally.verdict}** -- fewer than one completed look so far (n < look_step)"
            )
    add("")

    if tally.structural_dead is not None:
        if not tally.structural_dead.evaluable:
            add(
                "structural-dead stop (v1 section 5:105-106): SKIPPED -- no "
                "fill-time count was available."
            )
            add("")
        else:
            sd = tally.structural_dead
            fired_note = (
                ", evaluable and fired"
                if sd.structural_dead
                else ", evaluable and not fired"
            )
            add(
                "structural-dead stop (v1 section 5:105-106): "
                f"{sd.covered_listed_station_days} covered-listed station-day(s), "
                f"{sd.filled_takes} filled Take(s){fired_note}."
            )
            add(
                "listed-vs-captured residual: process-dead with neither captured "
                "dirs nor QuoteTapeGap rows is indistinguishable from never-listed "
                "and delays the stop (fail-closed)."
            )
            add("")

    add("| look | n | t | S | I | b_eff | b_fut | verdict |")
    add("|---:|---:|---:|---:|---:|---:|---:|---|")
    for idx, look in enumerate(tally.looks, start=1):
        verdict_cell = "(shadow)" if is_shadow else look.verdict
        add(
            f"| {idx} | {look.look_n} | {look.t:.4f} | {look.state.s:.4f} | "
            f"{look.state.information:.4f} | {look.b_eff:.4f} | {look.b_fut:.4f} | "
            f"{verdict_cell} |"
        )
    add("")
    add(f"total pnl (non-excluded): {tally.total_pnl}")
    if tally.bca_line is not None:
        add(tally.bca_line)
    else:
        add("BCa: not computed (terminal-only; no completed terminal look yet)")
    add("")

    store_dir = source_paths[0] if source_paths else None
    for line in _coverage_section_lines(store_dir):
        add(line)
    return "\n".join(lines)


def v3_residual_from_fill_source(
    manifest: FamilyManifest,
    fill_source: Path,
    *,
    since_climate_day: str,
) -> Decimal:
    """Three-seam Slice 4 review item 4: the v3 continuous-rung-hold
    family's residual dollar sum, derived from the SAME `--fill-source`
    store `count_filled_takes` already reads, via
    `score_live_trials.read_filled_trials_state_db`'s exclusions
    (`duplicate_fill`/`q != 1`/fee-unreconciled) and
    `score_live_trials.compute_residual`.

    Runs the reader ONCE PER MANIFEST STATION, mirroring
    `read_filled_trials_state_db`'s own documented cross-city-store
    contract (one shared store, one invocation per city/station), and sums
    across stations. A station whose read fails closed
    (`FillSourceUnreadableError`/`StorePositiveControlFailedError`)
    contributes nothing rather than aborting the whole tally -- the SAME
    fail-open-on-absence posture `count_filled_takes` already has for
    `filled_takes`.

    v2 never calls this -- see `main()`'s prefix guard; v2's residual stays
    `Decimal(0)`.
    """
    total = Decimal(0)
    for station in manifest.stations:
        try:
            _trials, exclusions, _fee_map, _no_side_map = read_filled_trials_state_db(
                fill_source,
                family_prefix=manifest.trial_id_prefix,
                city=station,
                cli_location=station,
                since_climate_day=since_climate_day,
                stations=tuple(manifest.stations),
            )
        except (FillSourceUnreadableError, StorePositiveControlFailedError):
            continue
        # `compute_residual` returns an UNSIGNED dollar magnitude (money at
        # risk in an unscored fill); `build_family_tally_v2`'s `residual` is
        # a SIGNED contribution added to `total_pnl`, so it is negated here
        # -- an unscored fill can only ever push the stop-rule TOWARD KILL,
        # never away from it.
        total -= compute_residual(exclusions)
    return total


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--family", required=True, help="family id -- deploy/families/<id>.json")
    parser.add_argument(
        "--store-dir", type=Path, required=True, help="6c scored-trial parquet directory"
    )
    parser.add_argument("--output", type=Path, default=None, help="path to write the report")
    parser.add_argument("--as-of", type=str, default="", help="as-of stamp for the header")
    parser.add_argument(
        "--truncate",
        choices=("D0_165", "LOSS_STOP"),
        default=None,
        help="force a terminal look at the current n with this truncation reason",
    )
    parser.add_argument(
        "--fill-source",
        type=Path,
        default=None,
        help="exec-state SqliteStateStore path for the structural-dead stop's "
        "FILL-TIME filled-Takes count (see fill_time_count.py); omitted means "
        "filled_takes=None and the stop is never evaluated",
    )
    parser.add_argument(
        "--covered-listed-station-days",
        type=int,
        default=None,
        help="the structural-dead stop's covered-listed-station-days "
        "denominator (see structural_dead_stop.py); omitted means the stop "
        "is never evaluated",
    )
    parser.add_argument(
        "--fill-since-climate-day",
        type=str,
        default=None,
        help="ISO date pass-through to count_filled_takes's since_climate_day "
        "(fill_time_count.py); scopes the fill-time count. Ignored when "
        "--fill-source is not given.",
    )
    args = parser.parse_args(argv)

    repo_root = Path(__file__).resolve().parents[2]
    manifest_path = repo_root / "deploy" / "families" / f"{args.family}.json"
    if not manifest_path.exists():
        print(
            f"family_tally_v2: unknown family id {args.family!r} (no {manifest_path})",
            file=sys.stderr,
        )
        return 2

    manifest = load_family_manifest(manifest_path, allow_draft=True)
    if args.family == _PM_US_CRH_V2_FAMILY_ID and manifest.trial_id_prefix != _LIVE_TRIAL_ID_PREFIX:
        print(
            "family_tally_v2: pm_us_crh_v2 manifest prefix drifted from "
            f"{_LIVE_TRIAL_ID_PREFIX!r}",
            file=sys.stderr,
        )
        return 2
    if args.family == _PM_US_CRH_V2_FAMILY_ID and (
        args.covered_listed_station_days is None
        or args.fill_source is None
        or args.fill_since_climate_day is None
        or args.fill_since_climate_day != manifest.d0_climate_day
    ):
        print(
            "family_tally_v2: pm_us_crh_v2 requires --covered-listed-station-days, "
            "--fill-source, and --fill-since-climate-day equal to the manifest "
            f"d0_climate_day ({manifest.d0_climate_day!r}); "
            f"got fill-since-climate-day={args.fill_since_climate_day!r}",
            file=sys.stderr,
        )
        return 2
    artefact_path = repo_root / manifest.boundary_artefact_path
    artefact = load_boundary_artefact(
        artefact_path, expected_sha256=manifest.boundary_inputs_sha256
    )

    rows = read_scored_trials(args.store_dir)
    truncation = TruncationReason(args.truncate) if args.truncate else None
    filled_takes = (
        None
        if args.fill_source is None
        else count_filled_takes(
            args.fill_source,
            family_prefix=manifest.trial_id_prefix,
            since_climate_day=args.fill_since_climate_day,
        )
    )
    # Three-seam Slice 4 review item 4: v3 only -- v2's `residual` stays 0.
    residual = (
        v3_residual_from_fill_source(
            manifest,
            args.fill_source,
            since_climate_day=args.fill_since_climate_day or manifest.d0_climate_day,
        )
        if args.fill_source is not None
        and manifest.trial_id_prefix.startswith(_CONTINUOUS_TRIAL_ID_PREFIX)
        else Decimal(0)
    )

    try:
        tally = build_family_tally_v2(
            rows,
            manifest=manifest,
            artefact=artefact,
            store_dir=args.store_dir,
            covered_listed_station_days=args.covered_listed_station_days,
            filled_takes=filled_takes,
            truncation=truncation,
            residual=residual,
        )
    except ProvenanceRefusal as exc:
        print(f"family_tally_v2: {exc}", file=sys.stderr)
        return 3
    report = render_markdown_v2(tally, source_paths=(args.store_dir,), as_of=args.as_of)
    print(report)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
