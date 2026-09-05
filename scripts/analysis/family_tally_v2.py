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
import re
import sys
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Final, cast

import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fill_time_count import count_filled_takes
from mb_current_rung_edge_study import ASK_BANDS, classify_ask_band  # v1, read-only reuse
from structural_dead_stop import StructuralDeadVerdict, structural_dead

from breezy.persistence.family_manifest import FamilyManifest, load_family_manifest
from breezy.persistence.gs_boundary_artefact import BoundaryArtefact, load_boundary_artefact
from breezy.persistence.scored_trial_store import SCORED_TRIAL_SCHEMA, read_scored_trials
from breezy.settlement.current_rung_hold_v2 import (
    ScoreState,
    StratumRow,
    StratumV2,
    TruncationReason,
    build_stratum_v2,
    information_fraction,
    look_verdict,
    score,
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
    "FamilyTallyV2",
    "LookRecord",
    "ProvenanceRefusal",
    "ScoredTrialDataIntegrityError",
    "build_family_tally_v2",
    "coverage_rows",
    "main",
    "read_excluded_fills",
    "render_markdown_v2",
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

#: v1 SS6:124-128, restated (never imported -- `mb_current_rung_edge_study`
#: has no module-level constant for this; it is inlined in prose there).
LOSS_STOP_PNL: Final[Decimal] = Decimal(-60)

STRATUM_TABLE_HEADER = (
    "| stratum | n | k | mean ask | mean BE (pi) | Wilson-lower | Wilson-upper | |"
)
STRATUM_TABLE_DIVIDER = "|---|---:|---:|---:|---:|---:|---:|---|"


class ScoredTrialDataIntegrityError(Exception):
    """An independent-reviewer fail-closed guard refused the whole tally."""


class ProvenanceRefusal(ScoredTrialDataIntegrityError):
    """B1 (ruling Q4): `--store-dir` lacks a v2 live-provenance sidecar, or
    the sidecar declares a provenance other than `"live"` (e.g.
    `"paper_replay"`)."""


#: I3c (`docs/plans/LIVE_FILL_SCORING_CHAIN_2026-09-05.md` 3.0(c)): the
#: driver-local `FillExclusion`'s 8-key artefact line, read back here.
_EXCLUDED_FILLS_FILENAME: Final[str] = "excluded_fills.jsonl"
_EXCLUDED_FILL_KEYS: Final[tuple[str, ...]] = (
    "trial_id",
    "station",
    "climate_day",
    "venue_order_id",
    "qty",
    "reason",
    "filled_at_ns",
    "scored_run_utc",
)
#: 3.0(g): `YYYY-MM-DDTHH:MM:SSZ`, UTC and lexically sortable.
_SCORED_RUN_UTC_RE: Final[re.Pattern[str]] = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
#: shape only (mirrors `_SCORED_RUN_UTC_RE`'s non-calendar-validating style).
_CLIMATE_DAY_RE: Final[re.Pattern[str]] = re.compile(r"^\d{4}-\d{2}-\d{2}$")
#: 3.0(c)/I2 BLOCK-3: the sole reason for which `trial_id`/`station`/
#: `climate_day` may be blank -- a fill whose instrument never reached a
#: taken latch has no trial identity yet.
_NO_TAKEN_LATCH_REASON: Final[str] = "no_taken_latch"


@dataclass(frozen=True, slots=True, kw_only=True)
class ExcludedFill:
    """One line of `<store_dir>/excluded_fills.jsonl` (I3c, 3.0(c)) --
    driver-local, never a `ScoreRefusal` (that struct carries only
    `trial_id, reason, detail` and is v1-BINDING inside the AST-pure
    `settlement` package)."""

    trial_id: str
    station: str
    climate_day: str
    venue_order_id: str
    qty: Decimal
    reason: str
    filled_at_ns: int
    scored_run_utc: str


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


def _assert_no_raw_score_seq_collisions(store_dir: Path) -> None:
    """Obligation (c): refuse a `(trial_id, score_seq)` collision found in
    the RAW parquet corpus, before `read_scored_trials`'s own max-score_seq
    dedup would silently resolve an exact-score_seq tie by file-iteration
    order (`current is None or trial.score_seq > current.score_seq` never
    updates on an EQUAL score_seq, so it keeps whichever file sorts first).

    Performs its own scan directly against the store's files -- restating
    the `scored_trials_*.parquet` glob and reusing the PUBLIC
    `SCORED_TRIAL_SCHEMA` export -- rather than modifying
    `scored_trial_store.py` (binding, out of scope).
    """
    if not store_dir.exists():
        return
    seen: dict[tuple[str, int], Path] = {}
    collisions: list[str] = []
    for path in sorted(store_dir.glob("scored_trials_*.parquet")):
        table = pq.read_table(path, schema=SCORED_TRIAL_SCHEMA)
        for row in table.to_pylist():
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


def _stratum_row(trial: ScoredTrial) -> StratumRow:
    return StratumRow(
        entry_ask=trial.entry_ask, fee=trial.fee, held=trial.held, station=trial.station
    )


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


def build_family_tally_v2(
    rows: Sequence[ScoredTrial],
    *,
    manifest: FamilyManifest,
    artefact: BoundaryArtefact,
    store_dir: Path | None = None,
    covered_listed_station_days: int | None = None,
    filled_takes: int | None = None,
    truncation: TruncationReason | None = None,
) -> FamilyTallyV2:
    """Build the pooled sequential trail, strata, and terminal-only BCa line.

    `store_dir`, if given, is scanned independently for obligation (c)
    (never re-derived from `rows`, which is already deduped by the time it
    reaches this function). `truncation`, if given, forces a terminal look
    at the CURRENT `n` (an off-grid look, per rev b SS4) with the given
    reason -- used for an explicit `--truncate` CLI override; `LOSS_STOP`
    and the natural `I_MAX`/`n_max` triggers are otherwise auto-detected
    from the data at each scheduled look.
    """
    _assert_held_matches_pnl_sign(rows)
    _assert_no_partial_or_multi_fill(rows)
    store_empty_no_sidecar = False
    if store_dir is not None:
        _assert_no_raw_score_seq_collisions(store_dir)
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

    non_excluded = tuple(row for row in rows if row.excluded_reason is None)
    ordered = _ordered_for_looks(non_excluded, store_dir=store_dir)
    pooled_rows = tuple(_stratum_row(t) for t in ordered)
    pooled = build_stratum_v2("pooled", pooled_rows) if pooled_rows else None
    station_strata = _station_strata(non_excluded)
    ask_band_strata = _ask_band_strata(non_excluded)
    any_cell_dead = any(s.cell_dead for s in (*station_strata, *ask_band_strata))

    total_pnl = sum((row.pnl for row in non_excluded), start=Decimal(0))

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

    n = len(pooled_rows)
    look_step = artefact.spending.look_step
    n_max = artefact.spending.n_max

    looks: list[LookRecord] = []
    t_history: list[float] = []
    verdict = "CONTINUE"
    bca_line: str | None = None
    registered = manifest.status == "REGISTERED"

    # Structural-dead is a separate KILL authority: never overwritten by a
    # later look_verdict/terminal_look assignment. Skip the look loop.
    if structural_fired and registered:
        verdict = "KILL"
        scheduled_ns = range(0)
    else:
        scheduled_ns = range(look_step, min(n, n_max) + 1, look_step)
    for look_n in scheduled_ns:
        state = score(pooled_rows[:look_n])
        t = information_fraction(state.information, i_max=artefact.i_max)
        t_history.append(t)

        reached_loss_stop = total_pnl <= LOSS_STOP_PNL
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
            b_eff, b_fut = artefact.boundary_for(tuple(t_history), is_terminal=True)
            verdict = terminal_look(
                state,
                reason=reason,
                b_eff=b_eff,
                b_fut=b_fut,
                total_pnl=total_pnl,
                cell_dead=any_cell_dead,
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
            bca_line = _roi_bound_line_v2(rows)
            break

        b_eff, b_fut = artefact.boundary_for(tuple(t_history), is_terminal=False)
        verdict = look_verdict(
            state,
            b_eff=b_eff,
            b_fut=b_fut,
            total_pnl=total_pnl,
            cell_dead=any_cell_dead,
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
            bca_line = _roi_bound_line_v2(rows)
            break

    already_terminal = bool(looks) and looks[-1].terminal
    if (
        not (structural_fired and registered)
        and truncation is not None
        and not already_terminal
        and pooled_rows
    ):
        # An off-grid explicit truncation (n does not land on a look_step
        # boundary): treated as a look too, never a skipped None (rev b
        # SS4).
        state = score(pooled_rows)
        t = information_fraction(state.information, i_max=artefact.i_max)
        t_history.append(t)
        b_eff, b_fut = artefact.boundary_for(tuple(t_history), is_terminal=True)
        verdict = terminal_look(
            state,
            reason=truncation,
            b_eff=b_eff,
            b_fut=b_fut,
            total_pnl=total_pnl,
            cell_dead=any_cell_dead,
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
        bca_line = _roi_bound_line_v2(rows)

    return FamilyTallyV2(
        family_id=manifest.family_id,
        manifest_sha256=manifest.manifest_sha256,
        boundary_inputs_sha256=artefact.inputs_sha256,
        status=manifest.status,
        n_scored=len(rows),
        n_excluded=len(rows) - len(non_excluded),
        pooled=pooled,
        station_strata=station_strata,
        ask_band_strata=ask_band_strata,
        looks=tuple(looks),
        verdict=verdict,
        total_pnl=total_pnl,
        bca_line=bca_line,
        structural_dead=structural,
        store_empty_no_sidecar=store_empty_no_sidecar,
    )


def _fmt_stratum_row(stratum: StratumV2) -> str:
    dead = "CELL-DEAD" if stratum.cell_dead else ""
    return (
        f"| {stratum.label} | {stratum.n} | {stratum.k} | {stratum.mean_ask:.4f} | "
        f"{stratum.pi:.4f} | {stratum.wilson_lower:.4f} | {stratum.wilson_upper:.4f} | {dead} |"
    )


def read_excluded_fills(store_dir: Path) -> tuple[ExcludedFill, ...]:
    """Read `<store_dir>/excluded_fills.jsonl` (I3c, 3.0(c)).

    An absent file returns no rows, never an error -- day one has none, not
    a refusal. A malformed line (missing key, bad JSON, a `scored_run_utc`
    not shaped `YYYY-MM-DDTHH:MM:SSZ`, a non-decimal `qty`, a blank
    `venue_order_id`, a blank `trial_id`/`station`/`climate_day` for any
    reason other than `no_taken_latch`, or a `climate_day` not shaped
    `YYYY-MM-DD`) refuses the whole tally loudly.
    """
    path = store_dir / _EXCLUDED_FILLS_FILENAME
    if not path.exists():
        return ()
    fills: list[ExcludedFill] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        fills.append(_excluded_fill_from_line(line, path=path, lineno=lineno))
    return tuple(fills)


def _excluded_fill_from_line(line: str, *, path: Path, lineno: int) -> ExcludedFill:
    try:
        row = json.loads(line)
    except json.JSONDecodeError as exc:
        raise ScoredTrialDataIntegrityError(
            f"refusing to tally: malformed {path}:{lineno} -- invalid JSON: {exc}"
        ) from exc
    missing = [key for key in _EXCLUDED_FILL_KEYS if key not in row]
    if missing:
        raise ScoredTrialDataIntegrityError(
            f"refusing to tally: malformed {path}:{lineno} -- missing key(s) {missing!r}"
        )
    scored_run_utc = row["scored_run_utc"]
    if not isinstance(scored_run_utc, str) or not _SCORED_RUN_UTC_RE.match(scored_run_utc):
        raise ScoredTrialDataIntegrityError(
            f"refusing to tally: malformed {path}:{lineno} -- scored_run_utc "
            f"{scored_run_utc!r} is not YYYY-MM-DDTHH:MM:SSZ"
        )
    try:
        qty = Decimal(str(row["qty"]))
    except (InvalidOperation, TypeError) as exc:
        raise ScoredTrialDataIntegrityError(
            f"refusing to tally: malformed {path}:{lineno} -- non-decimal qty {row['qty']!r}"
        ) from exc
    try:
        filled_at_ns = int(row["filled_at_ns"])
    except (TypeError, ValueError) as exc:
        raise ScoredTrialDataIntegrityError(
            f"refusing to tally: malformed {path}:{lineno} -- non-integer filled_at_ns "
            f"{row['filled_at_ns']!r}"
        ) from exc
    reason = row["reason"]
    if not isinstance(reason, str) or not reason:
        raise ScoredTrialDataIntegrityError(
            f"refusing to tally: malformed {path}:{lineno} -- empty/non-string reason"
        )
    venue_order_id = row["venue_order_id"]
    if not isinstance(venue_order_id, str) or not venue_order_id:
        raise ScoredTrialDataIntegrityError(
            f"refusing to tally: malformed {path}:{lineno} -- empty/non-string venue_order_id"
        )
    trial_id = row["trial_id"]
    station = row["station"]
    climate_day = row["climate_day"]
    if reason != _NO_TAKEN_LATCH_REASON:
        for field_name, value in (
            ("trial_id", trial_id),
            ("station", station),
            ("climate_day", climate_day),
        ):
            if not isinstance(value, str) or not value:
                raise ScoredTrialDataIntegrityError(
                    f"refusing to tally: malformed {path}:{lineno} -- empty/non-string "
                    f"{field_name} (reason {reason!r} requires it; only "
                    f"{_NO_TAKEN_LATCH_REASON!r} may leave it blank)"
                )
    if climate_day and (not isinstance(climate_day, str) or not _CLIMATE_DAY_RE.match(climate_day)):
        raise ScoredTrialDataIntegrityError(
            f"refusing to tally: malformed {path}:{lineno} -- climate_day "
            f"{climate_day!r} is not YYYY-MM-DD"
        )
    return ExcludedFill(
        trial_id=trial_id,
        station=station,
        climate_day=climate_day,
        venue_order_id=venue_order_id,
        qty=qty,
        reason=reason,
        filled_at_ns=filled_at_ns,
        scored_run_utc=scored_run_utc,
    )


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


def coverage_rows(
    excluded: Sequence[ExcludedFill], scored_trial_ids: frozenset[str]
) -> tuple[CoverageRow, ...]:
    """I3c count rule (strategy-lead Q2: "append-only jsonl is evidence,
    not the count"): dedup to one entry per `venue_order_id`, drop any
    entry whose `trial_id` already has a scored row (any `score_seq`), and
    group/count the survivors by `(reason, station, climate_day)`, sorted.
    """
    latest = _dedup_excluded_fills_by_venue_order_id(excluded)
    counts: dict[tuple[str, str, str], int] = defaultdict(int)
    for fill in latest.values():
        if fill.trial_id in scored_trial_ids:
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
    dropped = sum(1 for fill in latest.values() if fill.trial_id in scored_trial_ids)
    rows = coverage_rows(excluded, scored_trial_ids)
    lines.append("| reason | station | climate_day | count |")
    lines.append("|---|---|---|---:|")
    for row in rows:
        lines.append(f"| {row.reason} | {row.station} | {row.climate_day} | {row.count} |")
    lines.append("")
    lines.append(
        f"artefact: {artefact_path}; lines read: {len(excluded)}; "
        f"distinct venue_order_ids: {len(latest)}; dropped as already-scored: {dropped}"
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
        add(_fmt_stratum_row(tally.pooled))
    for stratum in (*tally.station_strata, *tally.ask_band_strata):
        add(_fmt_stratum_row(stratum))
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
            family_prefix=_LIVE_TRIAL_ID_PREFIX,
            since_climate_day=args.fill_since_climate_day,
        )
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
