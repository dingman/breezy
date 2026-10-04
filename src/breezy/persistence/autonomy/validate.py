"""``transitions.validate`` I: drill, RESUME, E-5, d0 and trial prefix (ARCH-0 seam A 7c; AC 13).

``validate(prior, rows, ...)`` is pure: it judges a batch of new rows against the fold of the rows
already written and returns the first refusal, or ``None``. It is the one home of every
fold-decidable C5 rule; seam 7d's rules (Z3, introducers, mint, ROLLBACK, ATTEST, SWAP_CANCEL,
single sender, HWM_RESET floors) live in ``validate_ii`` and are wired into the same walk.
``transitions`` re-exports ``validate``; the code lives here so that ``transitions`` stays under its
size cap.

Rules built here, each named by a ``Rule`` that ``first_refusal`` reports:

* drill (W2, V12, V15): a DRILL_ADMIT or DRILL_PROMOTE needs exactly one sender, CHAMPION and not
  HALTED and not ``demoted_for_cause`` (R7), with no integrity freeze standing, and an
  ``artefact_sha256`` equal to the incumbent's; a DRILL-class DEMOTE or HALT (a ROLLBACK_FAILED
  one under trigger DRILL included) is refused unless the family is CHAMPION with no standing
  cause (R2); every drill counter is capped at ``pins.DRILL_BUDGET_PER_VENUE_30D`` in a 30 day
  window;
* a ROLLBACK's ``drill`` column equals whether a drill episode is open (A7b);
* a nomination that is infeasible carries no α (AUT-4 r11:567; A7b);
* every row's ``from_state`` equals the fold's state of its family, ∅ for an introducer (A7c-R2),
  and no row rebinds a family's artefact sha (A7c-R5);
* RESUME (Y8, Z10, W2, V12): the family is HALTED with a halt instant, no pair is pending and no
  integrity freeze stands (the engine owns the live exec-store halt check), the row cites cause
  verdicts (each a PASS produced after the halt when the caller resolves them, A7c-R8), the
  cooldown has passed, the standing cause class is
  RECOVERABLE_MODEL, RECOVERABLE_INFRA or DRILL (a ROLLBACK_FAILED halt counts as its
  ``trigger_cause_class``) and that class's own budget has room;
* E-5: a RESUME with cause ``drill_close_restore`` is the restorative RESUME of the incumbent after
  a failed drill close; it charges no budget but keeps the cooldown (A7c-R1), and is refused for a
  drill child, after any other cause, outside the latest closed drill episode or for any family
  but the incumbent that episode superseded (A7c-R4), while an integrity freeze stands, when its
  shas differ from the family's, and past ``pins.DRILL_CLOSE_RESTORES_PER_VENUE_PER_DAY`` in a
  rolling day;
* d0 and ``trial_id_prefix`` at a family's first →CHAMPION row (PROMOTE, DRILL_PROMOTE; ROLLBACK,
  RESUME and ROOT_ADMIT are exempt, U1): the manifest facts must read and match the row, the prefix
  must equal ``f"{composition_kind}/trial/{child}/"``, ``d0_climate_day`` must be at least the
  ``effective_launch_date`` and strictly above every earlier child's d0 in the lineage;
* Y8 clear: a PROMOTE, DRILL_PROMOTE or ROLLBACK of a ``demoted_for_cause`` family needs a cited
  FORWARD_SHADOW PASS of that family produced after its latest cause;
* E-19a: no DEMOTE or HALT of the incoming family of an activated pair in [LAUNCH, launch-window
  end). The cause is written as a SWAP_CANCEL ``pair_cause_incoming``, which no rule here refuses.

Choices ARCH leaves open, fixed here (each pinned by a test):

* A refusal the closed ``RefusalReason`` set cannot name is ``engine_inconsistency`` (A6e-A1);
  ``Rule`` carries the precise cause.
* A windowed budget is the count of in-window instants (E-21), ``(at - window, ...)`` where ``at``
  is the row's effective instant (the pair's LAUNCH for a dated row, else ``ts_ns``), plus the
  pending DRILL_PROMOTE pairs and the earlier rows of the same batch. A venue cap sums the slices
  across lineages. The window lengths follow the names of their pins: 14, 7 and 30 days and one
  rolling 24 hours (``pins`` holds the caps, not the window lengths).
* The restorative RESUME keeps ``RESUME_COOLDOWN_H``: the cooldown delays it to the next eligible
  pass and strands nothing (A7c-R1).
* Not decidable from the fold and left to the replay and the engine: that a cited verdict PASSes and
  that the §4.4 preconditions hold. A RESUME that cites no verdict is refused.
* The d0 ordering reads the manifests of earlier CHILD families that have been CHAMPION, never the
  root's (a root's d0 is committed, Z1); a manifest that cannot be read refuses.

Restrictive rows (DEMOTE, HALT, SWAP_CANCEL, TARGET_INELIGIBLE) are refused only by the rules that
cannot fail open: the generic ``from_state`` rule, E-19a, the DRILL-class rules and (7d) the
SWAP_CANCEL subset rule; they never reach ``manifests`` and no single-sender rule judges a batch
made of them alone. ATTEST is judged by its own validity and cadence rules.

Pure: no I/O, no clock beyond the arguments.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from breezy.persistence.autonomy import pins
from breezy.persistence.autonomy import validate_ii as ii
from breezy.persistence.autonomy.fold import FamilyView, FoldResult, Origin, PairStatus, schedule_ns
from breezy.persistence.autonomy.fold_tallies import Carried, parse_carried
from breezy.persistence.autonomy.schemas import (
    CauseClass,
    CauseCode,
    Kind,
    ManifestFacts,
    ManifestFactsReader,
    RefusalReason,
    StageView,
    State,
    TransitionRow,
    WriterMode,
)
from breezy.persistence.autonomy.verdict import Verdict, VerdictKind, VerdictOutcome

__all__ = ["Refusal", "Rule", "RuleII", "first_refusal", "validate"]

RuleII = ii.RuleII
_HOUR_NS: Final = ii.HOUR_NS
_DAY_NS: Final = ii.DAY_NS
_DRILL_WINDOW_NS: Final = 30 * _DAY_NS  # DRILL_BUDGET_PER_VENUE_30D
_MODEL_RESUME_WINDOW_NS: Final = 14 * _DAY_NS  # MAX_RECOVERABLE_RESUMES_PER_LINEAGE_14D
_INFRA_RESUME_WINDOW_NS: Final = 7 * _DAY_NS  # MAX_INFRA_RESUMES_PER_VENUE_7D
_RESTORE_WINDOW_NS: Final = _DAY_NS  # DRILL_CLOSE_RESTORES_PER_VENUE_PER_DAY
_RESUMABLE: Final = frozenset(
    {CauseClass.RECOVERABLE_MODEL, CauseClass.RECOVERABLE_INFRA, CauseClass.DRILL}
)
_HALT_KINDS: Final = frozenset({Kind.DEMOTE, Kind.HALT})
_FAIL: Final = ii.FAIL


class Rule(StrEnum):
    """The rule a refusal comes from; ``Refusal.reason`` is the closed reason it maps to."""

    DRILL_NO_SINGLE_INCUMBENT = "drill_no_single_incumbent"
    DRILL_OVER_HALTED_INCUMBENT = "drill_over_halted_incumbent"
    DRILL_CAUSE_STANDS = "drill_cause_stands"
    DRILL_ARTEFACT_NOT_CHAMPION = "drill_artefact_not_champion"
    DRILL_BUDGET = "drill_budget"
    ROLLBACK_DRILL_COLUMN = "rollback_drill_column"
    INFEASIBLE_ALPHA = "infeasible_alpha"
    RESUME_NOT_HALTED = "resume_not_halted"
    RESUME_PAIR_PENDING = "resume_pair_pending"
    RESUME_EXEC_HALT = "resume_exec_halt"
    RESUME_CLASS = "resume_class"
    RESUME_UNCITED = "resume_uncited"
    RESUME_VERDICT_NOT_PASS = "resume_verdict_not_pass"
    RESUME_NO_HALT_INSTANT = "resume_no_halt_instant"
    FROM_STATE_MISMATCH = "from_state_mismatch"
    ARTEFACT_BINDING_IMMUTABLE = "artefact_binding_immutable"
    MANIFEST_DENSITY_NOT_BOUND = "manifest_density_not_bound"
    MANIFEST_BINDING_IMMUTABLE = "manifest_binding_immutable"
    RESTORE_NOT_THE_INCUMBENT = "restore_not_the_incumbent"
    RESUME_COOLDOWN = "resume_cooldown"
    RESUME_BUDGET = "resume_budget"
    RESTORE_NOT_FAILED_DRILL_CLOSE = "restore_not_failed_drill_close"
    RESTORE_DRILL_CHILD = "restore_drill_child"
    RESTORE_SHA_MISMATCH = "restore_sha_mismatch"
    RESTORE_DAILY_CAP = "restore_daily_cap"
    FIRST_CHAMPION_MANIFEST = "first_champion_manifest"
    FIRST_CHAMPION_PREFIX = "first_champion_prefix"
    FIRST_CHAMPION_D0 = "first_champion_d0"
    DEMOTED_NOT_CLEARED = "demoted_not_cleared"
    LAUNCH_WINDOW_CAUSE = "launch_window_cause"


@dataclass(frozen=True, slots=True)
class Refusal:
    """The first refusal of a batch: the closed reason, the rule and the row's batch index."""

    reason: RefusalReason
    rule: Rule | RuleII
    row_index: int


_Hit = tuple[Rule, RefusalReason]
_AnyHit = tuple[Rule | RuleII, RefusalReason]


_Ctx = ii.Ctx
_Check = Callable[[_Ctx, TransitionRow], _AnyHit | None]
_effective_ns = ii.effective_ns
_recent = ii.recent
_venue_instants = ii.venue_instants
_is_restore = ii.is_restore


def _resume_class(prior: FoldResult, row: TransitionRow) -> CauseClass | None:
    family = prior.families.get(row.family_id)
    return None if family is None else family.standing_cause_class


def _drill_counter(prior: FoldResult, row: TransitionRow) -> str | None:
    """The drill counter ``row`` charges when it takes effect, if any (the fold's own rule)."""
    kind = row.kind
    if kind is Kind.DRILL_ADMIT:
        return "drill_admits"
    if kind is Kind.DRILL_PROMOTE:
        return "drill_promotes"
    if kind in _HALT_KINDS and row.halt_cause_class is CauseClass.DRILL:
        return "drill_halts" if kind is Kind.HALT else "drill_demotes"
    if kind is Kind.ROLLBACK and row.drill:
        return "drill_rollbacks"
    if kind is Kind.RESUME and not _is_restore(row):
        return "drill_resumes" if _resume_class(prior, row) is CauseClass.DRILL else None
    return None


def _drill_budget(ctx: _Ctx, row: TransitionRow) -> _Hit | None:
    counter = _drill_counter(ctx.prior, row)
    if counter is None:
        return None
    used = _recent(_venue_instants(ctx.prior, counter), _effective_ns(row), _DRILL_WINDOW_NS)
    if row.kind is Kind.DRILL_PROMOTE:
        used += sum(
            1
            for pair in ctx.prior.pairs
            if pair.status is PairStatus.PENDING and pair.head_kind is Kind.DRILL_PROMOTE
        )
    used += sum(1 for e in ctx.earlier if _drill_counter(ctx.prior, e) == counter)
    if used >= pins.DRILL_BUDGET_PER_VENUE_30D:
        return Rule.DRILL_BUDGET, _FAIL
    return None


def _drill_entry(ctx: _Ctx, row: TransitionRow) -> _Hit | None:
    """DRILL_ADMIT and DRILL_PROMOTE: one CHAMPION incumbent, no exec halt, same artefact."""
    prior = ctx.prior
    senders = [prior.families[name] for name in prior.senders]
    if len(senders) != 1:
        return Rule.DRILL_NO_SINGLE_INCUMBENT, _FAIL
    incumbent = senders[0]
    if incumbent.state is State.HALTED:
        return Rule.DRILL_OVER_HALTED_INCUMBENT, _FAIL
    if prior.integrity_frozen or incumbent.demoted_for_cause:
        return Rule.DRILL_CAUSE_STANDS, _FAIL
    if row.artefact_sha256 is None or row.artefact_sha256 != incumbent.artefact_sha256:
        return Rule.DRILL_ARTEFACT_NOT_CHAMPION, _FAIL
    return None


def _drill_class_halt(ctx: _Ctx, row: TransitionRow) -> _Hit | None:
    """V12, A7c-R2: a DRILL-class halt needs a CHAMPION with no standing cause (first cause wins).

    A ROLLBACK_FAILED halt under trigger DRILL is DRILL-class too.
    """
    drill_class = row.halt_cause_class is CauseClass.DRILL or (
        row.halt_cause_class is CauseClass.ROLLBACK_FAILED
        and row.trigger_cause_class is CauseClass.DRILL
    )
    if not drill_class:
        return None
    family = ctx.prior.families.get(row.family_id)
    standing = ctx.prior.integrity_frozen or family is None or family.demoted_for_cause
    if standing or ctx.states.get(row.family_id) is not State.CHAMPION:
        return Rule.DRILL_CAUSE_STANDS, _FAIL
    return None


def _launch_window_cause(ctx: _Ctx, row: TransitionRow) -> _Hit | None:
    """E-19a: the cause goes through SWAP_CANCEL, not a DEMOTE or HALT of the incoming family."""
    for pair in ctx.prior.pairs:
        if pair.status is not PairStatus.EFFECTIVE or pair.incoming_family_id != row.family_id:
            continue
        end = schedule_ns(pair.effective_launch_date, pins.SCHEDULE_LAUNCH_WINDOW_END_UTC)
        if pair.launch_ns <= row.ts_ns < end:
            return Rule.LAUNCH_WINDOW_CAUSE, _FAIL
    return None


def _rollback_drill_column(ctx: _Ctx, row: TransitionRow) -> _Hit | None:
    """A ROLLBACK is a drill ROLLBACK exactly while a drill episode is open (A7b)."""
    if row.drill != any(e.end_ns is None for e in ctx.prior.drill_episodes):
        return Rule.ROLLBACK_DRILL_COLUMN, _FAIL
    return None


def _infeasible_alpha(_ctx: _Ctx, row: TransitionRow) -> _Hit | None:
    """AUT-4 r11:567: an infeasible nomination charges no α."""
    if (
        row.from_state is State.SHADOW
        and row.to_state is State.CHALLENGER
        and row.nomination_feasible is False
        and row.alpha_k is not None
        and row.alpha_k != 0
    ):
        return Rule.INFEASIBLE_ALPHA, _FAIL
    return None


def _earlier_resumes(ctx: _Ctx, cls: CauseClass, lineage: str) -> int:
    def counts(e: TransitionRow) -> bool:
        family = ctx.prior.families.get(e.family_id)
        return (
            e.kind is Kind.RESUME
            and not _is_restore(e)
            and family is not None
            and family.standing_cause_class is cls
            and (
                cls is not CauseClass.RECOVERABLE_MODEL or family.lineage_root_family_id == lineage
            )
        )

    return sum(1 for e in ctx.earlier if counts(e))


def _resume_budget(ctx: _Ctx, row: TransitionRow, cls: CauseClass, lineage: str) -> _Hit | None:
    at = _effective_ns(row)
    if cls is CauseClass.RECOVERABLE_MODEL:
        tallies = ctx.prior.lineages.get(lineage)
        slice_ = () if tallies is None else tallies.tallies.model_resumes
        used = _recent(slice_, at, _MODEL_RESUME_WINDOW_NS)
        cap = pins.MAX_RECOVERABLE_RESUMES_PER_LINEAGE_14D
    elif cls is CauseClass.RECOVERABLE_INFRA:
        used = _recent(ctx.prior.venue_tallies.infra_resumes, at, _INFRA_RESUME_WINDOW_NS)
        cap = pins.MAX_INFRA_RESUMES_PER_VENUE_7D
    else:
        return None  # DRILL: the drill budget check owns it
    if used + _earlier_resumes(ctx, cls, lineage) >= cap:
        return Rule.RESUME_BUDGET, _FAIL
    return None


def _restore(ctx: _Ctx, row: TransitionRow, family: FamilyView) -> _Hit | None:
    """E-5: the restorative RESUME of the incumbent after a failed drill close."""
    prior = ctx.prior
    if family.drill_child:
        return Rule.RESTORE_DRILL_CHILD, _FAIL
    episode = max(prior.drill_episodes, key=lambda e: e.start_ns, default=None)
    failed_close = (
        family.standing_cause_code is CauseCode.ROLLBACK_FAILED
        and family.standing_cause_class is CauseClass.DRILL
        and episode is not None
        and episode.end_ns is not None
        and family.halted_since_ns is not None
        and family.halted_since_ns >= episode.end_ns
    )
    if not failed_close:
        return Rule.RESTORE_NOT_FAILED_DRILL_CLOSE, _FAIL
    if episode is not None and episode.superseded_family_id != family.family_id:
        return Rule.RESTORE_NOT_THE_INCUMBENT, _FAIL
    if _in_cooldown(row, family):
        return Rule.RESUME_COOLDOWN, _FAIL
    shas = (row.artefact_sha256, row.manifest_sha256)
    if None in shas or shas != (family.artefact_sha256, family.manifest_sha256):
        return Rule.RESTORE_SHA_MISMATCH, _FAIL
    used = _recent(prior.venue_tallies.drill_close_restores, row.ts_ns, _RESTORE_WINDOW_NS)
    if used >= pins.DRILL_CLOSE_RESTORES_PER_VENUE_PER_DAY:
        return Rule.RESTORE_DAILY_CAP, _FAIL
    return None


def _in_cooldown(row: TransitionRow, family: FamilyView) -> bool:
    since = family.halted_since_ns
    return since is not None and row.ts_ns - since < pins.RESUME_COOLDOWN_H * _HOUR_NS


def _verdicts_pass_after_halt(ctx: _Ctx, row: TransitionRow, family: FamilyView) -> bool:
    """A8: with resolved verdicts, each cited one is a PASS produced after the halt."""
    if ctx.verdicts is None:
        return True  # the replay (8b) resolves them
    since = family.halted_since_ns or 0
    for verdict_id in row.cause_verdict_ids:
        verdict = ctx.verdicts.get(verdict_id)
        if (
            verdict is None
            or verdict.outcome is not VerdictOutcome.PASS
            or verdict.produced_at_ns <= since
        ):
            return False
    return True


def _resume(ctx: _Ctx, row: TransitionRow) -> _Hit | None:
    prior = ctx.prior
    family = prior.families.get(row.family_id)
    if family is None or family.state is not State.HALTED:
        return Rule.RESUME_NOT_HALTED, _FAIL
    if any(pair.status is PairStatus.PENDING for pair in prior.pairs):
        return Rule.RESUME_PAIR_PENDING, _FAIL
    if prior.integrity_frozen:
        return Rule.RESUME_EXEC_HALT, _FAIL
    if family.halted_since_ns is None:
        return Rule.RESUME_NO_HALT_INSTANT, _FAIL  # never exempt from the cooldown
    if _is_restore(row):
        return _restore(ctx, row, family)
    cls = family.standing_cause_class
    if cls is None or cls not in _RESUMABLE:
        return Rule.RESUME_CLASS, _FAIL
    if not row.cause_verdict_ids:
        return Rule.RESUME_UNCITED, _FAIL
    if _in_cooldown(row, family):
        return Rule.RESUME_COOLDOWN, _FAIL
    if not _verdicts_pass_after_halt(ctx, row, family):
        return Rule.RESUME_VERDICT_NOT_PASS, _FAIL
    return _resume_budget(ctx, row, cls, family.lineage_root_family_id)


def _identity_problem(ctx: _Ctx, row: TransitionRow, day: str) -> _Hit | None:
    facts = (
        None if row.manifest_sha256 is None else ctx.manifests(row.family_id, row.manifest_sha256)
    )
    if facts is None:
        return Rule.FIRST_CHAMPION_MANIFEST, RefusalReason.MANIFEST_UNREADABLE
    if (facts.family_id, facts.manifest_sha256) != (row.family_id, row.manifest_sha256):
        return Rule.FIRST_CHAMPION_MANIFEST, RefusalReason.MANIFEST_IDENTITY_MISMATCH
    if facts.trial_id_prefix != f"{facts.composition_kind}/trial/{row.family_id}/":
        return Rule.FIRST_CHAMPION_PREFIX, RefusalReason.TRIAL_PREFIX_MISMATCH
    if facts.d0_climate_day < day:
        return Rule.FIRST_CHAMPION_D0, RefusalReason.D0_BREACH
    return _earlier_d0_problem(ctx, row, facts.d0_climate_day)


def _earlier_d0_problem(ctx: _Ctx, row: TransitionRow, d0: str) -> _Hit | None:
    prior_view = ctx.prior.families.get(row.family_id)
    lineage = (
        row.lineage_root_family_id if prior_view is None else prior_view.lineage_root_family_id
    )
    for other in ctx.prior.families.values():
        if (
            other.family_id == row.family_id
            or other.lineage_root_family_id != lineage
            or other.origin is not Origin.CHILD
            or other.champion_epoch_start_ns is None
        ):
            continue
        facts = (
            None
            if other.manifest_sha256 is None
            else ctx.manifests(other.family_id, other.manifest_sha256)
        )
        if facts is None:
            return Rule.FIRST_CHAMPION_MANIFEST, RefusalReason.MANIFEST_UNREADABLE
        if d0 <= facts.d0_climate_day:
            return Rule.FIRST_CHAMPION_D0, RefusalReason.D0_BREACH
    return None


def _first_champion_identity(ctx: _Ctx, row: TransitionRow) -> _Hit | None:
    """d0 and ``trial_id_prefix`` bind a family's first →CHAMPION row only (U1)."""
    if row.to_state is not State.CHAMPION:
        return None
    family = ctx.prior.families.get(row.family_id)
    if family is not None and family.champion_epoch_start_ns is not None:
        return None
    if row.effective_launch_date is None or row.manifest_sha256 is None:
        return Rule.FIRST_CHAMPION_MANIFEST, RefusalReason.MANIFEST_UNREADABLE
    return _identity_problem(ctx, row, row.effective_launch_date)


def _demoted_clear(ctx: _Ctx, row: TransitionRow) -> _Hit | None:
    """Y8: a demoted family is promotable only after a later FORWARD_SHADOW PASS (cited)."""
    if row.to_state is not State.CHAMPION:
        return None
    family = ctx.prior.families.get(row.family_id)
    if family is None or not family.demoted_for_cause:
        return None
    cause_ns = family.demoted_cause_ns or 0
    for verdict_id in row.cause_verdict_ids:
        verdict = (ctx.verdicts or {}).get(verdict_id)
        if (
            verdict is not None
            and verdict.kind is VerdictKind.FORWARD_SHADOW
            and verdict.outcome is VerdictOutcome.PASS
            and verdict.subject_family_id == row.family_id
            and verdict.produced_at_ns > cause_ns
        ):
            return None
    return Rule.DEMOTED_NOT_CLEARED, _FAIL


def _from_state(ctx: _Ctx, row: TransitionRow) -> _Hit | None:
    """A7c-R2: ``from_state`` is the fold's state of the family, ∅ for an introducer."""
    state = ctx.states.get(row.family_id)
    if row.from_state is state or _is_retroactive_cancel(ctx, row, state):
        return None
    return Rule.FROM_STATE_MISMATCH, _FAIL


def _is_retroactive_cancel(ctx: _Ctx, row: TransitionRow, state: State | None) -> bool:
    """A post-launch SWAP_CANCEL names the incoming family as CHALLENGER: voiding undoes the swap.

    That path stays open (E-19a), so the cancel is judged against the pre-launch state.
    """
    return (
        row.kind is Kind.SWAP_CANCEL
        and row.from_state is State.CHALLENGER
        and state is State.CHAMPION
        and any(
            p.status is PairStatus.EFFECTIVE and p.incoming_family_id == row.family_id
            for p in ctx.prior.pairs
        )
    )


def _artefact_binding(ctx: _Ctx, row: TransitionRow) -> _Hit | None:
    """A7c-R5 (ARCH:367): a family's artefact sha is its introducing row's, for good."""
    family = ctx.prior.families.get(row.family_id)
    bound = None if family is None else family.artefact_sha256
    if bound is not None and row.artefact_sha256 not in (None, bound):
        return Rule.ARTEFACT_BINDING_IMMUTABLE, RefusalReason.ARTEFACT_SHA_MISMATCH
    return None


def _manifest_density_bound(ctx: _Ctx, row: TransitionRow) -> _Hit | None:
    """E-24: an introducing row's manifest pins, as its density, the artefact the row binds.

    A new density is a new child family, so a family's manifest never names another artefact.
    Fails closed: a missing or unreadable manifest is ``manifest_unreadable`` (the engine writes
    the family file before its MINT row). A sentinel root binds the sentinel file, so it holds too.
    """
    facts = (
        None if row.manifest_sha256 is None else ctx.manifests(row.family_id, row.manifest_sha256)
    )
    if facts is None:
        return Rule.MANIFEST_DENSITY_NOT_BOUND, RefusalReason.MANIFEST_UNREADABLE
    if facts.density_artefact_sha256 != row.artefact_sha256:
        return Rule.MANIFEST_DENSITY_NOT_BOUND, RefusalReason.ARTEFACT_SHA_MISMATCH
    return None


def _manifest_binding(ctx: _Ctx, row: TransitionRow) -> _Hit | None:
    """E-24: a family's manifest sha is its introducing row's, for good (the artefact's twin)."""
    if row.manifest_sha256 is None:
        return None
    family = ctx.prior.families.get(row.family_id)
    bound = None if family is None else family.manifest_sha256
    if bound is None:  # introduced by an earlier row of this very batch
        bound = next(
            (
                e.manifest_sha256
                for e in ctx.earlier
                if e.family_id == row.family_id and e.manifest_sha256 is not None
            ),
            None,
        )
    if bound is not None and row.manifest_sha256 != bound:
        return Rule.MANIFEST_BINDING_IMMUTABLE, RefusalReason.MANIFEST_SHA_MISMATCH
    return None


_CHECKS: Final[Mapping[Kind, tuple[_Check, ...]]] = {
    Kind.BOOTSTRAP: (ii.bootstrap, _manifest_density_bound),
    Kind.MINT: (ii.mint_rate, _manifest_density_bound),
    Kind.PROMOTE: (
        _infeasible_alpha,
        ii.terminal_frozen,
        ii.sender_cap,
        _first_champion_identity,
        _demoted_clear,
    ),
    Kind.DRILL_ADMIT: (_drill_entry, _drill_budget),
    Kind.DRILL_PROMOTE: (
        _drill_entry,
        _drill_budget,
        ii.terminal_frozen,
        _first_champion_identity,
        _demoted_clear,
    ),
    Kind.ROLLBACK: (
        _rollback_drill_column,
        ii.terminal_frozen,
        ii.rollback,
        ii.sender_cap,
        _demoted_clear,
        _drill_budget,
    ),
    Kind.ROOT_ADMIT: (ii.root_admit, ii.terminal_frozen, ii.sender_cap),
    Kind.DEMOTE: (_launch_window_cause, _drill_class_halt, _drill_budget),
    Kind.HALT: (_launch_window_cause, _drill_class_halt, _drill_budget),
    Kind.RESUME: (_resume, ii.sender_cap, _drill_budget),
    Kind.SWAP_CANCEL: (ii.swap_cancel,),
    Kind.ATTEST: (ii.attest,),
    Kind.HWM_RESET: (ii.hwm_floors,),
}


def _as_carried(export: Carried | str | None) -> Carried | None:
    return parse_carried(export) if isinstance(export, str) else export


def _pending_root_state(row: TransitionRow, ctx: _Ctx) -> bool:
    """A dated root introducer is SHADOW until its pair takes effect (the fold's pending root)."""
    return (
        row.effective_launch_date is not None
        and row.family_id not in ctx.prior.families
        and row.family_id not in ctx.known
    )


def _memoised(reader: ManifestFactsReader) -> ManifestFactsReader:
    """``reader`` that reads each (family, sha) once per batch; an unreadable one is asked again."""
    seen: dict[tuple[str, str], ManifestFacts] = {}

    def read(family_id: str, manifest_sha256: str) -> ManifestFacts | None:
        key = (family_id, manifest_sha256)
        if key not in seen:
            facts = reader(family_id, manifest_sha256)
            if facts is None:
                return None
            seen[key] = facts
        return seen[key]

    return read


def first_refusal(
    prior: FoldResult,
    rows: Sequence[TransitionRow],
    *,
    manifests: ManifestFactsReader,
    verdicts: Mapping[str, Verdict] | None = None,
    export_counters: Carried | str | None = None,
) -> Refusal | None:
    """The first rule a batch breaks against ``prior``, in row order, or ``None``.

    A batch that is not restrictive-only must also leave at most one sender, now and at every
    LAUNCH it or the pending pairs reach (Z3 single sender).
    """
    manifests = _memoised(manifests)
    earlier: list[TransitionRow] = []
    states = dict(prior.states)
    known: set[str] = set()
    export = _as_carried(export_counters)
    guard_senders = not ii.restrictive_only(rows)
    for index, row in enumerate(rows):
        ctx = _Ctx(prior, manifests, verdicts, tuple(earlier), states, frozenset(known), export)
        checks = (
            ii.introduction,
            _from_state,
            *_CHECKS.get(row.kind, ()),
            _artefact_binding,
            _manifest_binding,
        )
        for check in checks:
            hit = check(ctx, row)
            if hit is not None:
                return Refusal(hit[1], hit[0], index)
        earlier.append(row)
        if row.effective_launch_date is None:  # an immediate row moves its family now
            states[row.family_id] = row.to_state
        elif _pending_root_state(row, ctx):
            states[row.family_id] = State.SHADOW
        known.add(row.family_id)
        if guard_senders and ii.senders_after_row(states):
            return Refusal(_FAIL, RuleII.SINGLE_SENDER, index)
    if guard_senders and ii.single_sender_at_launch(prior, rows, states):
        return Refusal(_FAIL, RuleII.SINGLE_SENDER, len(rows) - 1)
    return None


def validate(
    prior: FoldResult,
    rows: Sequence[TransitionRow],
    *,
    mode: WriterMode | None,
    now_ns: int,
    stage: StageView,
    manifests: ManifestFactsReader,
    export_counters: Carried | str | None = None,
    verdicts: Mapping[str, Verdict] | None = None,
) -> RefusalReason | None:
    """The closed reason of the first refusal of ``rows`` against ``prior``, else ``None``.

    ``mode``, ``now_ns`` and ``stage`` are the plan's signature (AC 10.9) and do not change a
    verdict: every rule reads the rows' own instants and the fold, and the stage gate is
    ``rows_admissible``'s. ``export_counters`` is the newest export's counters, as a parsed
    ``Carried`` or the canonical JSON text of the ``carried_counters`` shape; an HWM_RESET row is
    refused without it (B9). ``verdicts`` maps verdict ids to the verdicts the caller resolved,
    for the Y8 clear.
    """
    refusal = first_refusal(
        prior, rows, manifests=manifests, verdicts=verdicts, export_counters=export_counters
    )
    return None if refusal is None else refusal.reason
