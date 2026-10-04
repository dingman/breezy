"""``transitions.validate`` II: the rules of seam 7d (ARCH-0 seam A 7d; AC 13).

``validate`` (the module) owns the walk, ``Rule`` and ``Refusal``; this module holds the context a
check reads (``Ctx``, so that it never imports ``validate``), the checks seam 7d adds and the
helpers both share. Each check takes the walk's context and one row and returns
``(RuleII, RefusalReason)`` or ``None``. Every refusal that the closed ``RefusalReason`` set cannot
name is ``engine_inconsistency``; ``RuleII`` carries the cause.

Rules built here:

* introducers (Y6): a family unknown to the fold must enter with ``from_state`` ∅ through
  BOOTSTRAP, ROOT_ADMIT or MINT (``family_not_introduced``); a BOOTSTRAP or ROOT_ADMIT names its own
  family as its lineage root (``root_lineage_mismatch``);
* BOOTSTRAP (E-6): the genesis of an empty venue chain only, for a seed family in the seed's state;
* ROOT_ADMIT (V6): only while the venue has no CHAMPION or HALTED family, never into a
  ``terminal_frozen`` lineage;
* ``terminal_frozen`` (Y10): no →CHAMPION head (PROMOTE, DRILL_PROMOTE, ROLLBACK, ROOT_ADMIT) into
  a frozen lineage;
* MINT (Z3): at most ``MAX_MINTS_PER_LINEAGE_PER_DAY`` counted MINTs per lineage in a rolling
  day, whatever the model class and however many nominations the lineage has used; a
  no-new-lineage (drill) MINT, one that binds an artefact a sibling already holds, is never
  counted and never refused;
* sender changes (Z3): at most ``MAX_SENDER_CHANGES_PER_VENUE_PER_DAY`` in a rolling day, pending
  pairs and earlier rows of the batch counted as reservations; drill rows count only against the
  drill budget;
* ROLLBACK (A7c-R3): the target is ``rollback_eligible``, not ``target_ineligible``, left CHAMPION
  at most ``ROLLBACK_TARGET_MAX_AGE_D`` ago; a non-drill ROLLBACK keeps ``ROLLBACK_MIN_DWELL_H``
  after the latest sender change or RESUME and stays within ``MAX_ROLLBACKS_PER_VENUE_30D``, summed
  over every lineage's in-window slice (E-21);
* ATTEST (Y3, W1, Z4): ``attest_valid_until_ns`` is present and at most ``ts_ns`` plus
  ``ATTEST_VERDICT_VALIDITY_H``; one per family per ``ATTEST_PERIOD_H``, the first after the
  family's latest →CHAMPION or RESUME exempt;
* SWAP_CANCEL: every voided id is a member of a pending pair, of a pair that took effect when the
  cancel lies in [LAUNCH, launch-window end) (Z8), or of an earlier dated row of the batch;
* HWM_RESET (B9): the export's counters are a sub-multiset of ``carried_counters``, field by
  field (A7b-R2, E-21); the export is required.

The single-sender rule (``single_sender_hit``) judges the whole batch: at most one family in
{CHAMPION, HALTED} once the immediate rows apply and after each LAUNCH the batch and the venue's
pending pairs would reach. A batch of only restrictive kinds is never refused for it: restrictive
rows are always permitted, and with E-19a (no DEMOTE or HALT of an incoming family in the launch
window) none can add a sender.

Pure: no I/O, no clock beyond the arguments.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Collection, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from breezy.persistence.autonomy import pins
from breezy.persistence.autonomy.fold import (
    HEAD_KINDS,
    INTRODUCING_KINDS,
    PARTNER_KINDS,
    FamilyView,
    FoldResult,
    PairStatus,
    schedule_ns,
)
from breezy.persistence.autonomy.fold_tallies import (
    INT_COUNTERS,
    TUPLE_COUNTERS,
    VENUE_COUNTERS,
    Carried,
    CarriedLineage,
    parse_carried,
)
from breezy.persistence.autonomy.schemas import (
    CauseClass,
    CauseCode,
    Kind,
    ManifestFactsReader,
    RefusalReason,
    State,
    TransitionRow,
)
from breezy.persistence.autonomy.verdict import Verdict

__all__ = ["DAY_NS", "HOUR_NS", "Ctx", "RuleII", "hwm_floor_problem"]

HOUR_NS: Final = 3_600 * 10**9
DAY_NS: Final = 24 * HOUR_NS
FAIL: Final = RefusalReason.ENGINE_INCONSISTENCY
_ROLLBACK_AGE_NS: Final = pins.ROLLBACK_TARGET_MAX_AGE_D * DAY_NS
_ROLLBACK_WINDOW_NS: Final = 30 * DAY_NS  # MAX_ROLLBACKS_PER_VENUE_30D
_SENDER_STATES: Final = frozenset({State.CHAMPION, State.HALTED})
_ROOT_KINDS: Final = frozenset({Kind.BOOTSTRAP, Kind.ROOT_ADMIT})
_FROZEN_KINDS: Final = frozenset({Kind.PROMOTE, Kind.DRILL_PROMOTE, Kind.ROLLBACK, Kind.ROOT_ADMIT})
_RESTRICTIVE: Final = frozenset({Kind.DEMOTE, Kind.HALT, Kind.SWAP_CANCEL, Kind.TARGET_INELIGIBLE})
_SEED: Final = frozenset(pins.BOOTSTRAP_SEED)


class RuleII(StrEnum):
    """The rule a seam 7d refusal comes from."""

    FAMILY_NOT_INTRODUCED = "family_not_introduced"
    ROOT_LINEAGE_MISMATCH = "root_lineage_mismatch"
    BOOTSTRAP_NOT_GENESIS = "bootstrap_not_genesis"
    BOOTSTRAP_NOT_SEED = "bootstrap_not_seed"
    ROOT_ADMIT_VENUE_HAS_SENDER = "root_admit_venue_has_sender"
    LINEAGE_TERMINAL_FROZEN = "lineage_terminal_frozen"
    MINT_RATE = "mint_rate"
    SENDER_CHANGE_DAILY_CAP = "sender_change_daily_cap"
    ROLLBACK_TARGET_NOT_ELIGIBLE = "rollback_target_not_eligible"
    ROLLBACK_TARGET_INELIGIBLE = "rollback_target_ineligible"
    ROLLBACK_TARGET_TOO_OLD = "rollback_target_too_old"
    ROLLBACK_DWELL = "rollback_dwell"
    ROLLBACK_BUDGET = "rollback_budget"
    ATTEST_VALIDITY = "attest_validity"
    ATTEST_CADENCE = "attest_cadence"
    SWAP_CANCEL_VOIDS_NOT_PENDING = "swap_cancel_voids_not_pending"
    HWM_EXPORT_MISSING = "hwm_export_missing"
    HWM_COUNTERS_MALFORMED = "hwm_counters_malformed"
    HWM_CARRIED_BELOW_EXPORT = "hwm_carried_below_export"
    SINGLE_SENDER = "single_sender"


Hit = tuple[RuleII, RefusalReason]


@dataclass(frozen=True, slots=True)
class Ctx:
    """What a check reads: the prior fold, the batch so far and the state the batch has reached."""

    prior: FoldResult
    manifests: ManifestFactsReader
    verdicts: Mapping[str, Verdict] | None
    earlier: tuple[TransitionRow, ...]
    #: The fold's state of each family, advanced by the immediate rows earlier in the batch.
    states: Mapping[str, State]
    #: The families the earlier rows of the batch introduced.
    known: frozenset[str] = frozenset()
    #: The export's counters for an HWM_RESET row (B9); ``None`` when the caller supplied none.
    export_counters: Carried | None = None


# --- Shared helpers (also read by ``validate``) -------------------------------------------------


def effective_ns(row: TransitionRow) -> int:
    """A row's effective instant: its pair's LAUNCH for a dated row, else ``ts_ns``."""
    if row.effective_launch_date is None:
        return row.ts_ns
    return schedule_ns(row.effective_launch_date, pins.SCHEDULE_LAUNCH_UTC)


def recent(instants: Iterable[int], at: int, window_ns: int) -> int:
    """The number of instants in ``(at - window_ns, ...)``."""
    return sum(1 for instant in instants if instant > at - window_ns)


def venue_instants(prior: FoldResult, counter: str) -> Iterator[int]:
    """Every lineage's slice of a windowed counter, concatenated (a venue cap, E-21)."""
    for view in prior.lineages.values():
        yield from getattr(view.tallies, counter)


def is_restore(row: TransitionRow) -> bool:
    return row.kind is Kind.RESUME and row.cause_code is CauseCode.DRILL_CLOSE_RESTORE


def _senders(states: Mapping[str, State]) -> int:
    return sum(1 for state in states.values() if state in _SENDER_STATES)


def _drill_open(prior: FoldResult) -> bool:
    return any(e.end_ns is None for e in prior.drill_episodes)


# --- Introducers ----------------------------------------------------------------------------


def introduction(ctx: Ctx, row: TransitionRow) -> Hit | None:
    """Y6: who may introduce a family, and what a root names as its lineage."""
    view = ctx.prior.families.get(row.family_id)
    unknown = view is None and row.family_id not in ctx.known
    if unknown and (row.from_state is not None or row.kind not in INTRODUCING_KINDS):
        return RuleII.FAMILY_NOT_INTRODUCED, RefusalReason.FAMILY_NOT_INTRODUCED
    if row.kind in _ROOT_KINDS and (
        row.lineage_root_family_id != row.family_id
        or (view is not None and view.lineage_root_family_id != row.family_id)
    ):
        return RuleII.ROOT_LINEAGE_MISMATCH, RefusalReason.ROOT_LINEAGE_MISMATCH
    return None


def bootstrap(ctx: Ctx, row: TransitionRow) -> Hit | None:
    """E-6: BOOTSTRAP is the genesis of an empty chain, for a seed family in its seed state."""
    if ctx.prior.head_venue_seq != 0:
        return RuleII.BOOTSTRAP_NOT_GENESIS, FAIL
    if (row.family_id, row.to_state.value) not in _SEED:
        return RuleII.BOOTSTRAP_NOT_SEED, FAIL
    return None


def root_admit(ctx: Ctx, row: TransitionRow) -> Hit | None:
    """V6: a ROOT_ADMIT recovers a venue that has no CHAMPION or HALTED family."""
    if _senders(ctx.states):
        return RuleII.ROOT_ADMIT_VENUE_HAS_SENDER, FAIL
    return None


def terminal_frozen(ctx: Ctx, row: TransitionRow) -> Hit | None:
    """Y10: nothing becomes CHAMPION in a ``terminal_frozen`` lineage."""
    if row.kind not in _FROZEN_KINDS or row.to_state is not State.CHAMPION:
        return None
    view = ctx.prior.families.get(row.family_id)
    root = row.lineage_root_family_id if view is None else view.lineage_root_family_id
    lineage = ctx.prior.lineages.get(root or "")
    if (view is not None and view.terminal_frozen) or (
        lineage is not None and lineage.tallies.terminal_frozen
    ):
        return RuleII.LINEAGE_TERMINAL_FROZEN, FAIL
    return None


# --- MINT and sender-change budgets -----------------------------------------------------------


def _reuses_artefact(ctx: Ctx, row: TransitionRow, before: Sequence[TransitionRow]) -> bool:
    """Whether the MINT binds an artefact a family of its lineage already holds (C3 Y2).

    ``before`` are the batch rows that precede ``row``.
    """
    sha, root = row.artefact_sha256, row.lineage_root_family_id
    if sha is None:
        return False
    held = (
        f.artefact_sha256
        for f in ctx.prior.families.values()
        if f.lineage_root_family_id == root and f.family_id != row.family_id
    )
    batch = (
        e.artefact_sha256
        for e in before
        if e.lineage_root_family_id == root
        and e.kind in INTRODUCING_KINDS
        and e.effective_launch_date is None  # a pending ROOT_ADMIT is not applied (as in fold)
    )
    return sha in {*held, *batch}


def mint_rate(ctx: Ctx, row: TransitionRow) -> Hit | None:
    """Z3: one counted MINT per lineage per day; K_LIFETIME limits nominations, never MINTs."""
    if _reuses_artefact(ctx, row, ctx.earlier):
        return None
    lineage = ctx.prior.lineages.get(row.lineage_root_family_id or "")
    slice_ = () if lineage is None else lineage.tallies.mints
    used = recent(slice_, row.ts_ns, DAY_NS)
    used += sum(
        1
        for index, e in enumerate(ctx.earlier)
        if e.kind is Kind.MINT
        and e.lineage_root_family_id == row.lineage_root_family_id
        and not _reuses_artefact(ctx, e, ctx.earlier[:index])
    )
    if used >= pins.MAX_MINTS_PER_LINEAGE_PER_DAY:
        return RuleII.MINT_RATE, FAIL
    return None


def _is_sender_change(ctx: Ctx, row: TransitionRow) -> bool:
    """Z3: a non-drill →CHAMPION head, ROOT_ADMIT or RESUME (never a restore or a drill RESUME)."""
    if row.kind in (Kind.PROMOTE, Kind.ROOT_ADMIT):
        return row.to_state is State.CHAMPION
    if row.kind is Kind.ROLLBACK:
        return not row.drill
    if row.kind is Kind.RESUME and not is_restore(row):
        view = ctx.prior.families.get(row.family_id)
        return view is None or view.standing_cause_class is not CauseClass.DRILL
    return False


def _pending_heads(ctx: Ctx, kinds: Collection[Kind], at: int, window_ns: int) -> int:
    drill = _drill_open(ctx.prior)
    return sum(
        1
        for pair in ctx.prior.pairs
        if pair.status is PairStatus.PENDING
        and pair.head_kind in kinds
        and not (pair.head_kind is Kind.ROLLBACK and drill)
        and abs(pair.launch_ns - at) < window_ns
    )


def sender_cap(ctx: Ctx, row: TransitionRow) -> Hit | None:
    """Z3: at most ``MAX_SENDER_CHANGES_PER_VENUE_PER_DAY`` logical sender changes per day."""
    if not _is_sender_change(ctx, row):
        return None
    at = effective_ns(row)
    used = recent(ctx.prior.venue_tallies.sender_changes, at, DAY_NS)
    used += _pending_heads(ctx, (Kind.PROMOTE, Kind.ROOT_ADMIT, Kind.ROLLBACK), at, DAY_NS)
    used += sum(
        1 for e in ctx.earlier if _is_sender_change(ctx, e) and abs(effective_ns(e) - at) < DAY_NS
    )
    if used >= pins.MAX_SENDER_CHANGES_PER_VENUE_PER_DAY:
        return RuleII.SENDER_CHANGE_DAILY_CAP, FAIL
    return None


# --- ROLLBACK -----------------------------------------------------------------------------------


def _dwell_anchor(prior: FoldResult) -> int | None:
    """The latest sender change or RESUME: a sender change, or the current sender's epoch start."""
    epochs = (
        prior.families[name].champion_epoch_start_ns
        for name in prior.senders
        if prior.families[name].champion_epoch_start_ns is not None
    )
    anchors = [*prior.venue_tallies.sender_changes, *(e for e in epochs if e is not None)]
    return max(anchors, default=None)


def _rollback_target(view: FamilyView | None, at: int) -> Hit | None:
    if view is None or not view.rollback_eligible:
        return RuleII.ROLLBACK_TARGET_NOT_ELIGIBLE, FAIL
    if view.target_ineligible:
        return RuleII.ROLLBACK_TARGET_INELIGIBLE, FAIL
    if view.superseded_ns is None or at - view.superseded_ns > _ROLLBACK_AGE_NS:
        return RuleII.ROLLBACK_TARGET_TOO_OLD, FAIL
    return None


def rollback(ctx: Ctx, row: TransitionRow) -> Hit | None:
    """A7c-R3, A7d-R1: the fold-decidable ROLLBACK rules.

    Every ROLLBACK keeps the dwell; a drill ROLLBACK is exempt only from the rollback budget.
    """
    at = effective_ns(row)
    hit = _rollback_target(ctx.prior.families.get(row.family_id), at)
    if hit is not None:
        return hit
    anchor = _dwell_anchor(ctx.prior)
    if anchor is not None and at - anchor < pins.ROLLBACK_MIN_DWELL_H * HOUR_NS:
        return RuleII.ROLLBACK_DWELL, FAIL
    if row.drill:
        return None
    used = recent(venue_instants(ctx.prior, "rollbacks"), at, _ROLLBACK_WINDOW_NS)
    used += _pending_heads(ctx, (Kind.ROLLBACK,), at, _ROLLBACK_WINDOW_NS)
    used += sum(1 for e in ctx.earlier if e.kind is Kind.ROLLBACK and not e.drill)
    if used >= pins.MAX_ROLLBACKS_PER_VENUE_30D:
        return RuleII.ROLLBACK_BUDGET, FAIL
    return None


# --- ATTEST and SWAP_CANCEL ---------------------------------------------------------------------


def attest(ctx: Ctx, row: TransitionRow) -> Hit | None:
    """Z4 validity ceiling and the W1 cadence (the first ATTEST of an epoch is exempt)."""
    until = row.attest_valid_until_ns
    ceiling = row.ts_ns + pins.ATTEST_VERDICT_VALIDITY_H * HOUR_NS
    if until is None or until <= row.ts_ns or until > ceiling:
        return RuleII.ATTEST_VALIDITY, FAIL
    view = ctx.prior.families.get(row.family_id)
    last = None if view is None else view.last_attest_ns
    earlier = [
        e.ts_ns for e in ctx.earlier if e.kind is Kind.ATTEST and e.family_id == row.family_id
    ]
    if earlier:
        last = max(earlier)
    elif last is not None and view is not None and (view.champion_epoch_start_ns or 0) > last:
        last = None  # a →CHAMPION or RESUME since: the first ATTEST of the epoch
    if last is not None and row.ts_ns - last < pins.ATTEST_PERIOD_H * HOUR_NS:
        return RuleII.ATTEST_CADENCE, FAIL
    return None


def _cancellable(ctx: Ctx, ts_ns: int) -> set[str]:
    """The members a cancel stamped ``ts_ns`` voids, exactly as ``fold`` decides (A7d-R2).

    A member of a non-voided pair when ``ts_ns`` is before its LAUNCH, or when the pair was
    activated and ``ts_ns`` is before the launch-window end. The stamp, not the commit time,
    decides: a cancel stamped 16:49:59 and committed at 16:50:01 voids an ACTIVATEd pair.
    """
    ids = {e.transition_id for e in ctx.earlier if e.effective_launch_date is not None}
    for pair in ctx.prior.pairs:
        if pair.status is PairStatus.VOIDED:
            continue
        window_end = schedule_ns(pair.effective_launch_date, pins.SCHEDULE_LAUNCH_WINDOW_END_UTC)
        activated = pair.activate_transition_id is not None
        if ts_ns < pair.launch_ns or (activated and ts_ns < window_end):
            ids.update(pair.member_transition_ids)
    return ids


def swap_cancel(ctx: Ctx, row: TransitionRow) -> Hit | None:
    """The voided ids are a subset of the pending (or post-launch cancellable) pairs' members."""
    if not set(row.voids_transition_ids or ()) <= _cancellable(ctx, row.ts_ns):
        return RuleII.SWAP_CANCEL_VOIDS_NOT_PENDING, FAIL
    return None


# --- HWM_RESET floors ---------------------------------------------------------------------------


def _multiset_below(export: Iterable[int], carried: Iterable[int]) -> bool:
    return not (Counter(export) - Counter(carried))


def _lineage_below(export: CarriedLineage, carried: CarriedLineage | None) -> bool:
    if carried is None:
        return True
    return (
        any(export.ints[n] > carried.ints[n] for n in INT_COUNTERS)
        or export.alpha_spent > carried.alpha_spent
        or (export.terminal_frozen and not carried.terminal_frozen)
        or any(not _multiset_below(export.instants[n], carried.instants[n]) for n in TUPLE_COUNTERS)
    )


def hwm_floor_problem(export: Carried, carried: Carried) -> str | None:
    """The first counter of ``export`` that ``carried`` does not cover, else ``None``."""
    for lineage, entry in export.lineages.items():
        if _lineage_below(entry, carried.lineages.get(lineage)):
            return "lineage"
    for name in VENUE_COUNTERS:
        if not _multiset_below(export.venue[name], carried.venue[name]):
            return f"venue {name}"
    return None


def hwm_floors(ctx: Ctx, row: TransitionRow) -> Hit | None:
    """B9: ``carried_counters`` covers the export's counters (the export is required)."""
    export = ctx.export_counters
    if export is None:
        return RuleII.HWM_EXPORT_MISSING, FAIL
    carried = None if row.carried_counters is None else parse_carried(row.carried_counters)
    if carried is None:
        return RuleII.HWM_COUNTERS_MALFORMED, FAIL
    if hwm_floor_problem(export, carried) is not None:
        return RuleII.HWM_CARRIED_BELOW_EXPORT, FAIL
    return None


# --- Single sender ------------------------------------------------------------------------------


def restrictive_only(rows: Sequence[TransitionRow]) -> bool:
    return all(row.kind in _RESTRICTIVE for row in rows)


def senders_after_row(states: Mapping[str, State]) -> bool:
    """Whether ``states`` holds more than one family in {CHAMPION, HALTED}."""
    return _senders(states) > 1


def _launch_effects(
    prior: FoldResult, rows: Sequence[TransitionRow], states: Mapping[str, State]
) -> dict[int, list[tuple[str, State]]]:
    """What each LAUNCH would do to family states: pending pairs, then the batch's dated rows."""
    voided = {
        v for row in rows if row.kind is Kind.SWAP_CANCEL for v in row.voids_transition_ids or ()
    }
    effects: dict[int, list[tuple[str, State]]] = {}
    for pair in prior.pairs:
        if pair.status is PairStatus.PENDING and not voided.intersection(
            pair.member_transition_ids
        ):
            effects.setdefault(pair.launch_ns, []).extend(pair.member_effects)
    launches = {
        pair.head_transition_id: pair.launch_ns
        for pair in prior.pairs
        if pair.status is PairStatus.PENDING
    }
    launches.update(
        (row.transition_id, schedule_ns(row.effective_launch_date, pins.SCHEDULE_LAUNCH_UTC))
        for row in rows
        if row.kind in HEAD_KINDS and row.to_state is State.CHAMPION and row.effective_launch_date
    )
    for row in rows:
        if row.transition_id in voided:
            continue
        # a head takes effect at its own LAUNCH, a partner at the LAUNCH of the head it cites
        # (as fold does), and a partner citing no head never takes effect
        key = row.transition_id if row.kind in HEAD_KINDS else row.paired_transition_id
        launch = launches.get(key or "")
        if launch is not None and (row.kind in HEAD_KINDS or row.kind in PARTNER_KINDS):
            effects.setdefault(launch, []).append((row.family_id, row.to_state))
    return effects


def single_sender_at_launch(
    prior: FoldResult, rows: Sequence[TransitionRow], states: Mapping[str, State]
) -> bool:
    """Whether some LAUNCH the batch and the pending pairs reach would leave two senders."""
    projected = dict(states)
    for launch in sorted(effects := _launch_effects(prior, rows, states)):
        projected.update(effects[launch])
        if senders_after_row(projected):
            return True
    return False
