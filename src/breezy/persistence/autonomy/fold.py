"""The effective-time fold of a venue chain (ARCH-0 seam A 6b, 7a; ARCH C5, Y8).

``fold(rows, venue, now_ns)`` is a pure function of one venue's rows and the clock. It computes:

* the state of every family at ``now_ns``;
* the pending pairs: a ``→CHAMPION`` head row that carries ``effective_launch_date`` D, with the
  SUPERSEDE or DISPLACED partners that cite it through ``paired_transition_id``;
* the ACTIVATE window: an ACTIVATE that names the head in ``paired_transition_id``, belongs to the
  head's family and is written in [STOP, LAUNCH) on D;
* the lapse: at LAUNCH on D a pair takes effect only with such an ACTIVATE, else it never does;
* SWAP_CANCEL voiding: a SWAP_CANCEL that lists a member of a pair voids the whole pair when it is
  written before LAUNCH, or in [LAUNCH, launch-window end) on D for a pair that took effect (Z8).
  From the window end it voids nothing. A voided or lapsed pair has no effect of any kind: no
  state, no flag, no episode;
* per-family flags: ``rollback_eligible``, ``demoted_for_cause``, ``target_ineligible`` and
  ``drill_child``; the lineage ``terminal_frozen`` freeze (Y10); the venue INTEGRITY freeze;
* drill episodes ``[DRILL_PROMOTE effective, closing partner or RETIRE effective)`` (Z2);
* ``FamilyView.origin`` (root or child, from the introducing row) and ``halted_since_ns``;
* the ARCH C5 counters as ``LineageTallies`` (one per lineage) and ``VenueTallies``, charged when a
  change takes effect, with ``HWM_RESET`` ``carried_counters`` applied as floors;
* the facts ``validate`` reads of a family (seam 7c): the shas it is bound to and the cause it
  stands halted for.

Row order and effective time. Immediate rows (no ``effective_launch_date``) apply at their
``ts_ns`` and only once ``ts_ns <= now_ns``; the members of an effective pair apply at LAUNCH.
Rows apply in ``(instant, chain position)`` order. A row whose ``from_state == to_state``
(ATTEST, HWM_RESET, ACTIVATE, SWAP_CANCEL, TARGET_INELIGIBLE) never changes a state, but
SWAP_CANCEL and TARGET_INELIGIBLE still set their flags. ``from_state`` consistency is
``validate``'s to refuse (seams 7c, 7d); the fold applies ``to_state``.

Choices ARCH leaves open, fixed here (each pinned by a test):

* A SWAP_CANCEL that lists any member of a pair voids the whole pair: a pair is atomic.
* ``demoted_for_cause`` is scoped to a champion epoch (A7a-R3, E-19b). A cause is a DEMOTE or HALT,
  or a SWAP_CANCEL with cause ``pair_cause_incoming`` on its own family. An epoch opens, at the
  row's effective instant, on every applied row whose ``to_state`` is CHAMPION and whose
  ``from_state`` is not: BOOTSTRAP, ROOT_ADMIT, the head of an effective pair and RESUME. A
  same-state row (ATTEST, HWM_RESET) opens none. The flag is true iff a cause was applied after
  the epoch opened (chain order at equal instants); a family that was never champion has no epoch,
  so any cause counts. ``demoted_cause_ns`` is the latest cause instant, kept after the flag
  clears. The FORWARD_SHADOW PASS clear of Y8 is a ``validate`` rule over verdicts.
* ``terminal_frozen`` follows a DEMOTE or HALT of class TERMINAL, or a RETIRE with cause
  ``model_budget_exhausted``. The INTEGRITY freeze follows class INTEGRITY or cause
  ``infra_budget_exhausted``. Class ROLLBACK_FAILED never freezes. Neither freeze is cleared by the
  fold: ARCH gives no autonomous clear (W15).
* A SUPERSEDE makes its family ``rollback_eligible`` unless that family is a drill child (a family
  whose DRILL_ADMIT or DRILL_PROMOTE applied; a child whose pair lapsed or was voided stays one).
  Becoming CHAMPION again clears it.
* A drill episode ends at the first SUPERSEDE or DISPLACED of its child that takes effect, or at the
  child's RETIRE.
* A lineage is named by the introducing row's ``lineage_root_family_id``, which every introducing
  row must carry (A7b-R3): a BOOTSTRAP or ROOT_ADMIT must name itself and a MINT names its root.
  Any other value, or none, is ``FoldInvalid(root_lineage_mismatch)`` (E-14 rule 3).
* Charging (tallies; E-21: every windowed counter is a sorted tuple of effective instants). A row is
  charged at its effective instant, so a pending, lapsed or voided pair charges nothing.
  ``nominations`` is the largest ``k_life`` of a feasible SHADOW to CHALLENGER PROMOTE,
  ``infeasible_nominations`` counts the infeasible ones, ``nomination_instants`` holds every
  nomination and ``alpha_spent`` is the exact sum of ``alpha_k``. ``promotions`` are PROMOTE heads
  and ``rollbacks`` ROLLBACK heads; a ROLLBACK that takes effect while a drill episode is open is a
  ``drill_rollbacks`` charge instead. DRILL_ADMIT, a DRILL_PROMOTE head and a DEMOTE or HALT of
  class DRILL charge ``drill_admits``, ``drill_promotes``, ``drill_demotes`` and ``drill_halts``.
  A RESUME is charged to the class of the family's standing DEMOTE or HALT (a ROLLBACK_FAILED one
  to its ``trigger_cause_class``): RECOVERABLE_INFRA to ``VenueTallies.infra_resumes``,
  RECOVERABLE_MODEL to ``model_resumes``, DRILL to ``drill_resumes``; a RESUME with cause
  ``drill_close_restore`` only to ``drill_close_restores``. ``VenueTallies.sender_changes`` holds
  every Z3 logical change: a non-drill →CHAMPION head taking effect (PROMOTE, ROLLBACK, ROOT_ADMIT)
  and every RESUME that is not a drill RESUME or a close restore. ATTEST, SWAP_CANCEL,
  TARGET_INELIGIBLE and HWM_RESET charge nothing.
* ``carried_counters`` (shape and merge: ``fold_tallies``) is applied at the reset row so that no
  budget is refunded (A7b-R2): ints by max, bools by OR, instant lists by sorted multiset union,
  and ``terminal_frozen`` true freezes the lineage. A malformed object is
  ``FoldInvalid(carried_counters_malformed)``, whatever the clock. A carried lineage with no
  families left keeps its tallies.
* ``manifest_sha256`` of a family is that of the latest applied row that carries one; its
  ``artefact_sha256`` is the introducing row's and never changes (A7c-R5, ARCH:367). ``validate``
  compares a drill child or a restorative RESUME against them and refuses a rebinding row.
  ``standing_cause_class`` is the class a RESUME of a HALTED family is charged to
  (the class of its standing DEMOTE or HALT, a ROLLBACK_FAILED one resolved to its
  ``trigger_cause_class``) and ``standing_cause_code`` the ``cause_code`` of that row; both are
  ``None`` while the family is not HALTED.
* A MINT whose ``artefact_sha256`` equals one already bound to another family of its lineage is a
  no-new-lineage (drill) MINT (C3 Y2) and charges no ``mints`` (Z3, seam 7d). ``last_attest_ns``
  and ``superseded_ns`` give ``validate`` the ATTEST cadence and the rollback target age.
* ``halted_since_ns`` is the effective instant of the row that moved the family into HALTED and is
  ``None`` once it leaves HALTED (AUT-6 r15 #30).

Pure: no I/O, no wall clock (the clock is the ``now_ns`` argument), no mutation of the input.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from breezy.persistence.autonomy.fold_pairs import (
    ACTIVATE_KIND,
    HEAD_KINDS,
    PARTNER_KINDS,
    Head,
    PairStatus,
    PairView,
    attach_members,
    collect_heads,
    events,
    is_head_shape,
    pair_views,
    schedule_ns,
    void_pairs,
)
from breezy.persistence.autonomy.fold_tallies import (
    Carried,
    LineageTallies,
    TallyBook,
    VenueTallies,
    parse_carried,
)
from breezy.persistence.autonomy.schemas import (
    CauseClass,
    CauseCode,
    FoldInvalidReason,
    Kind,
    State,
    TransitionRow,
    check_venue,
)

__all__ = [
    "ACTIVATE_KIND",
    "HEAD_KINDS",
    "INTRODUCING_KINDS",
    "PARTNER_KINDS",
    "DrillEpisode",
    "FamilyView",
    "FoldInvalid",
    "FoldResult",
    "LineageTallies",
    "LineageView",
    "Origin",
    "PairStatus",
    "PairView",
    "VenueTallies",
    "fold",
    "schedule_ns",
]

#: The only kinds that may be a family's first row.
INTRODUCING_KINDS: Final[frozenset[Kind]] = frozenset({Kind.BOOTSTRAP, Kind.ROOT_ADMIT, Kind.MINT})

_SENDER_STATES: Final[frozenset[State]] = frozenset({State.CHAMPION, State.HALTED})
_ROOT_KINDS: Final[frozenset[Kind]] = frozenset({Kind.BOOTSTRAP, Kind.ROOT_ADMIT})


class Origin(StrEnum):
    """How a family entered the chain: a root (BOOTSTRAP, ROOT_ADMIT) or a MINT child."""

    ROOT = "root"
    CHILD = "child"


@dataclass(frozen=True, slots=True, kw_only=True)
class FamilyView:
    family_id: str
    state: State
    lineage_root_family_id: str
    origin: Origin
    rollback_eligible: bool = False
    demoted_for_cause: bool = False
    target_ineligible: bool = False
    terminal_frozen: bool = False
    drill_child: bool = False
    #: The latest cause instant (DEMOTE, HALT or an incoming-cause SWAP_CANCEL), even once cleared.
    demoted_cause_ns: int | None = None
    #: When the current champion epoch opened; ``None`` for a family that never was CHAMPION.
    champion_epoch_start_ns: int | None = None
    #: The instant of the row that made the family HALTED; ``None`` while it is not HALTED.
    halted_since_ns: int | None = None
    #: The shas of the latest applied row that carries each; ``None`` before any row does.
    manifest_sha256: str | None = None
    artefact_sha256: str | None = None
    #: The class a RESUME is charged to and the ``cause_code`` of the standing halt row.
    standing_cause_class: CauseClass | None = None
    standing_cause_code: CauseCode | None = None
    #: The instant of the latest ATTEST and of the SUPERSEDE that left CHAMPION (7d).
    last_attest_ns: int | None = None
    superseded_ns: int | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class LineageView:
    root_family_id: str
    #: The families of the lineage that the fold has applied, by name.
    family_ids: tuple[str, ...]
    tallies: LineageTallies


@dataclass(frozen=True, slots=True, kw_only=True)
class DrillEpisode:
    family_id: str
    start_ns: int
    end_ns: int | None
    drill_promote_transition_id: str
    #: The incumbent the DRILL_PROMOTE superseded (A7c-R4); ``None`` until its partner applies.
    superseded_family_id: str | None = None

    def contains(self, ts_ns: int) -> bool:
        return self.start_ns <= ts_ns and (self.end_ns is None or ts_ns < self.end_ns)


@dataclass(frozen=True, slots=True)
class FoldResult:
    venue: str
    now_ns: int
    #: The last row's sealed ``venue_seq`` (0 for no rows).
    head_venue_seq: int
    states: Mapping[str, State]
    pairs: tuple[PairView, ...]
    families: Mapping[str, FamilyView]
    integrity_frozen: bool
    drill_episodes: tuple[DrillEpisode, ...]
    #: One view per lineage root, by root name (including a carried root with no family left).
    lineages: Mapping[str, LineageView]
    venue_tallies: VenueTallies

    @property
    def senders(self) -> tuple[str, ...]:
        """The families in {CHAMPION, HALTED}, by name: ARCH allows at most one per venue.

        Data only. A consumer must not take ``senders[0]`` as the champion before the resolver's
        own checks: a chain that ``validate`` refuses can still list two senders here.
        """
        return tuple(sorted(f for f, st in self.states.items() if st in _SENDER_STATES))


@dataclass(frozen=True, slots=True)
class FoldInvalid:
    """The rows cannot be folded. The resolver maps this to ``replay_invalid``."""

    reason: FoldInvalidReason


def _check_inputs(rows: Sequence[TransitionRow], venue: str, now_ns: int) -> None:
    try:
        check_venue(venue)
    except ValueError as exc:
        raise ValueError(f"venue is malformed: {venue!r}") from exc
    if isinstance(now_ns, bool) or not isinstance(now_ns, int) or now_ns < 0:
        raise ValueError(f"now_ns must be a non-negative int, got {now_ns!r}")
    for row in rows:
        if not isinstance(row, TransitionRow):
            raise TypeError("fold takes TransitionRow values only")
        if row.venue != venue:
            raise ValueError(f"row of venue {row.venue!r} in the chain of venue {venue!r}")


def _head_venue_seq(rows: tuple[TransitionRow, ...]) -> int:
    """The sealed ``venue_seq`` of the last row (0 for no rows); an unsealed last row is refused."""
    if not rows:
        return 0
    last = rows[-1].venue_seq
    if last is None:
        raise ValueError("fold needs sealed rows: the last row has no venue_seq")
    return last


@dataclass(slots=True)
class _OpenEpisode:
    """Private working record of a drill episode; frozen into ``DrillEpisode`` at the end."""

    family_id: str
    start_ns: int
    transition_id: str
    end_ns: int | None = None
    superseded: str | None = None


def _is_nomination(row: TransitionRow) -> bool:
    return (
        row.kind is Kind.PROMOTE
        and row.from_state is State.SHADOW
        and row.to_state is State.CHALLENGER
    )


class _Accumulator:
    """The mutable working state of one ``fold`` call; never escapes it."""

    def __init__(
        self,
        lineage_of: Mapping[str, str],
        origin_of: Mapping[str, Origin],
        carried: Mapping[str, Carried],
    ) -> None:
        self.states: dict[str, State] = {}
        self.lineage_of = lineage_of
        self.origin_of = origin_of
        self.carried = carried
        self.rollback_eligible: set[str] = set()
        self.demoted: set[str] = set()
        self.demoted_ns: dict[str, int] = {}
        self.epoch_start: dict[str, int] = {}
        self.halted_since: dict[str, int] = {}
        self.manifest_sha: dict[str, str] = {}
        self.artefact_sha: dict[str, str] = {}
        self.standing_code: dict[str, CauseCode | None] = {}
        self.attest_ns: dict[str, int] = {}
        self.superseded_ns: dict[str, int] = {}
        self.target_ineligible: set[str] = set()
        self.drill_children: set[str] = set()
        self.frozen_lineages: set[str] = set()
        self.integrity_frozen = False
        self.episodes: list[_OpenEpisode] = []
        self.book = TallyBook(lineage_of)
        #: The class a RESUME of the family is charged to: that of its standing DEMOTE or HALT.
        self.standing_class: dict[str, CauseClass | None] = {}

    def apply(self, instant: int, row: TransitionRow) -> None:
        family = row.family_id
        if row.manifest_sha256 is not None:
            self.manifest_sha[family] = row.manifest_sha256
        if row.artefact_sha256 is not None:
            self.artefact_sha.setdefault(family, row.artefact_sha256)  # immutable (A7c-R5)
        if row.from_state is not row.to_state:
            self.states[family] = row.to_state
            if row.to_state is State.HALTED:
                self.halted_since[family] = instant
            else:
                self.halted_since.pop(family, None)
        if row.to_state is State.CHAMPION and row.from_state is not State.CHAMPION:
            self.epoch_start[family] = instant
            self.demoted.discard(family)
        kind = row.kind
        if is_head_shape(row):
            self._take_champion(instant, row)
        elif kind is Kind.SUPERSEDE:
            if family not in self.drill_children:
                self.rollback_eligible.add(family)
                self.superseded_ns[family] = instant
            self._close_episode(family, instant)
            self._note_superseded(row)
        elif kind is Kind.DISPLACED:
            self._close_episode(family, instant)
        elif kind is Kind.DRILL_ADMIT:
            self.drill_children.add(family)
            self.book.charge(family, "drill_admits", instant)
        elif kind is Kind.MINT:
            if not self._reuses_artefact(row):  # a no-new-lineage (drill) MINT is not counted
                self.book.charge(family, "mints", instant)
        elif kind is Kind.ATTEST:
            self.attest_ns[family] = instant
        elif kind in (Kind.DEMOTE, Kind.HALT):
            self._halt(instant, row)
        elif kind is Kind.RESUME:
            self._charge_resume(instant, row)
        elif kind is Kind.RETIRE:
            self._close_episode(family, instant)
            if row.cause_code is CauseCode.MODEL_BUDGET_EXHAUSTED:
                self._freeze_lineage(family)
        elif kind is Kind.SWAP_CANCEL:
            if row.cause_code is CauseCode.PAIR_CAUSE_INCOMING:
                self._mark_cause(family, instant)
        elif kind is Kind.TARGET_INELIGIBLE:
            self.target_ineligible.add(family)
        elif kind is Kind.HWM_RESET:
            self._apply_floors(row)
        if _is_nomination(row):
            self.book.nomination(
                family,
                instant,
                feasible=row.nomination_feasible,
                k_life=row.k_life,
                alpha_k=row.alpha_k,
            )

    def _reuses_artefact(self, row: TransitionRow) -> bool:
        """Whether the MINT binds an artefact a sibling of its lineage is already bound to (Y2)."""
        root = self.lineage_of.get(row.family_id)
        return row.artefact_sha256 is not None and any(
            sha == row.artefact_sha256 and self.lineage_of.get(other) == root
            for other, sha in self.artefact_sha.items()
            if other != row.family_id
        )

    def _take_champion(self, instant: int, row: TransitionRow) -> None:
        family = row.family_id
        self.rollback_eligible.discard(family)
        if row.kind is Kind.DRILL_PROMOTE:
            self.drill_children.add(family)
            self.episodes.append(_OpenEpisode(family, instant, row.transition_id))
            self.book.charge(family, "drill_promotes", instant)
            return
        if row.kind is Kind.ROLLBACK and any(e.end_ns is None for e in self.episodes):
            self.book.charge(family, "drill_rollbacks", instant)  # closes a drill episode
            return
        if row.kind is Kind.PROMOTE:
            self.book.charge(family, "promotions", instant)
        elif row.kind is Kind.ROLLBACK:
            self.book.charge(family, "rollbacks", instant)
        self.book.charge_venue("sender_changes", instant)  # PROMOTE, ROLLBACK, ROOT_ADMIT (Z3)

    def _charge_resume(self, instant: int, row: TransitionRow) -> None:
        """Charge a RESUME to the budget of its own cause class (Z3, Z10, E-5, E-21)."""
        family = row.family_id
        cls = self.standing_class.pop(family, None)
        if row.cause_code is CauseCode.DRILL_CLOSE_RESTORE:
            self.book.charge_venue("drill_close_restores", instant)
            return
        if cls is CauseClass.DRILL:
            self.book.charge(family, "drill_resumes", instant)
            return
        if cls is CauseClass.RECOVERABLE_INFRA:
            self.book.charge_venue("infra_resumes", instant)
        elif cls is CauseClass.RECOVERABLE_MODEL:
            self.book.charge(family, "model_resumes", instant)
        self.book.charge_venue("sender_changes", instant)

    def _apply_floors(self, row: TransitionRow) -> None:
        carried = self.carried.get(row.transition_id)
        if carried is not None:
            self.frozen_lineages |= self.book.apply_carried(carried)

    def _mark_cause(self, family: str, instant: int) -> None:
        self.demoted.add(family)
        self.demoted_ns[family] = instant

    def _halt(self, instant: int, row: TransitionRow) -> None:
        """A failed rollback (ROLLBACK_FAILED) matches neither freeze: it halts its family only."""
        family = row.family_id
        self.rollback_eligible.discard(family)
        self._mark_cause(family, instant)
        cls = row.halt_cause_class
        self.standing_code[family] = row.cause_code
        self.standing_class[family] = (
            row.trigger_cause_class if cls is CauseClass.ROLLBACK_FAILED else cls
        )
        if cls is CauseClass.DRILL:
            counter = "drill_halts" if row.kind is Kind.HALT else "drill_demotes"
            self.book.charge(family, counter, instant)
        if cls is CauseClass.TERMINAL:
            self._freeze_lineage(family)
        if cls is CauseClass.INTEGRITY or row.cause_code is CauseCode.INFRA_BUDGET_EXHAUSTED:
            self.integrity_frozen = True

    def _freeze_lineage(self, family: str) -> None:
        self.frozen_lineages.add(self.lineage_of.get(family, family))

    def _note_superseded(self, row: TransitionRow) -> None:
        for episode in self.episodes:
            if episode.transition_id == row.paired_transition_id:
                episode.superseded = row.family_id

    def _close_episode(self, family: str, instant: int) -> None:
        for episode in self.episodes:
            if episode.family_id == family and episode.end_ns is None:
                episode.end_ns = instant

    def family_views(self) -> Mapping[str, FamilyView]:
        views: dict[str, FamilyView] = {}
        for family, state in self.states.items():
            lineage = self.lineage_of.get(family, family)
            views[family] = FamilyView(
                family_id=family,
                state=state,
                lineage_root_family_id=lineage,
                origin=self.origin_of[family],
                rollback_eligible=family in self.rollback_eligible,
                demoted_for_cause=family in self.demoted,
                target_ineligible=family in self.target_ineligible,
                terminal_frozen=lineage in self.frozen_lineages,
                drill_child=family in self.drill_children,
                demoted_cause_ns=self.demoted_ns.get(family),
                champion_epoch_start_ns=self.epoch_start.get(family),
                halted_since_ns=self.halted_since.get(family),
                manifest_sha256=self.manifest_sha.get(family),
                artefact_sha256=self.artefact_sha.get(family),
                standing_cause_class=(
                    self.standing_class.get(family) if state is State.HALTED else None
                ),
                standing_cause_code=(
                    self.standing_code.get(family) if state is State.HALTED else None
                ),
                last_attest_ns=self.attest_ns.get(family),
                superseded_ns=self.superseded_ns.get(family),
            )
        return MappingProxyType(views)

    def lineage_views(self) -> Mapping[str, LineageView]:
        roots = {self.lineage_of.get(f, f) for f in self.states} | self.book.roots()
        return MappingProxyType(
            {
                root: LineageView(
                    root_family_id=root,
                    family_ids=tuple(
                        sorted(f for f in self.states if self.lineage_of.get(f, f) == root)
                    ),
                    tallies=self.book.lineage(root, terminal_frozen=root in self.frozen_lineages),
                )
                for root in sorted(roots)
            }
        )

    def drill_episodes(self) -> tuple[DrillEpisode, ...]:
        return tuple(
            DrillEpisode(
                family_id=e.family_id,
                start_ns=e.start_ns,
                end_ns=e.end_ns,
                drill_promote_transition_id=e.transition_id,
                superseded_family_id=e.superseded,
            )
            for e in self.episodes
        )


def _introduction(row: TransitionRow) -> tuple[Origin, str] | FoldInvalidReason:
    """The origin and lineage root a family's first row gives it, or why the chain is invalid.

    Every introducing row names its lineage root (E-14 rule 3, A7b-R3): a root names itself and a
    MINT child names the root it descends from. An absent column is as invalid as a foreign one.
    """
    root = row.lineage_root_family_id
    if row.kind is Kind.MINT and root is not None:
        return Origin.CHILD, root
    if row.kind in _ROOT_KINDS:
        return (
            (Origin.ROOT, root)
            if root == row.family_id
            else FoldInvalidReason.ROOT_LINEAGE_MISMATCH
        )
    if row.kind is Kind.MINT:
        return FoldInvalidReason.ROOT_LINEAGE_MISMATCH
    return FoldInvalidReason.FAMILY_INTRODUCED_BY_OTHER_KIND


def _scan_rows(
    rows: Sequence[TransitionRow], heads: dict[str, Head]
) -> tuple[Mapping[str, str], Mapping[str, Origin], dict[str, Carried], set[str]] | FoldInvalid:
    """The lineage and origin of every family, parsed ``carried_counters`` and pending roots."""
    lineage_of: dict[str, str] = {}
    origin_of: dict[str, Origin] = {}
    carried: dict[str, Carried] = {}
    pending_roots: set[str] = set()
    for row in rows:
        if row.family_id not in lineage_of:
            intro = _introduction(row)
            if isinstance(intro, FoldInvalidReason):
                return FoldInvalid(intro)
            origin_of[row.family_id], lineage_of[row.family_id] = intro
            if row.transition_id in heads:  # a pending root: SHADOW until its pair takes effect
                pending_roots.add(row.family_id)
        if is_head_shape(row) and row.effective_launch_date is None:
            return FoldInvalid(FoldInvalidReason.HEAD_MISSING_LAUNCH_DATE)
        if row.kind is Kind.HWM_RESET and row.carried_counters is not None:
            parsed = parse_carried(row.carried_counters)
            if parsed is None:
                return FoldInvalid(FoldInvalidReason.CARRIED_COUNTERS_MALFORMED)
            carried[row.transition_id] = parsed
    return lineage_of, origin_of, carried, pending_roots


def fold(rows: Sequence[TransitionRow], venue: str, now_ns: int) -> FoldResult | FoldInvalid:
    """Fold one venue's rows (chain order) into family states, flags and pair views at ``now_ns``.

    ``ValueError`` for another venue's row, a bad clock or an unsealed last row; ``TypeError`` for
    a non-row.
    ``FoldInvalid`` for a family whose first row is not BOOTSTRAP, ROOT_ADMIT or MINT, a root kind
    that names a foreign lineage root, a →CHAMPION head row with no ``effective_launch_date``
    (E-16 c) and a ``carried_counters`` object of the wrong shape.
    """
    ordered = tuple(rows)
    _check_inputs(ordered, venue, now_ns)
    head_venue_seq = _head_venue_seq(ordered)
    heads = collect_heads(ordered)
    orphans = attach_members(ordered, heads)
    void_pairs(ordered, heads, now_ns)
    scanned = _scan_rows(ordered, heads)
    if isinstance(scanned, FoldInvalid):
        return scanned
    lineage_of, origin_of, carried, pending_roots = scanned
    acc = _Accumulator(lineage_of, origin_of, carried)
    acc.states.update((family, State.SHADOW) for family in pending_roots)
    for instant, _index, row in events(ordered, heads, orphans, now_ns):
        acc.apply(instant, row)
    return FoldResult(
        venue=venue,
        now_ns=now_ns,
        head_venue_seq=head_venue_seq,
        states=MappingProxyType(acc.states),
        pairs=pair_views(ordered, heads, now_ns),
        families=acc.family_views(),
        integrity_frozen=acc.integrity_frozen,
        drill_episodes=acc.drill_episodes(),
        lineages=acc.lineage_views(),
        venue_tallies=acc.book.venue(),
    )
