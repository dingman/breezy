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
* drill episodes ``[DRILL_PROMOTE effective, closing partner or RETIRE effective)`` (Z2).

Row order and effective time. Immediate rows (no ``effective_launch_date``) apply at their
``ts_ns`` and only once ``ts_ns <= now_ns``; the members of an effective pair apply at LAUNCH.
Rows apply in ``(instant, chain position)`` order. A row whose ``from_state == to_state``
(ATTEST, HWM_RESET, ACTIVATE, SWAP_CANCEL, TARGET_INELIGIBLE) never changes a state, but
SWAP_CANCEL and TARGET_INELIGIBLE still set their flags. ``from_state`` consistency is
``validate``'s to refuse (seams 7c, 7d); the fold applies ``to_state``.

Choices ARCH leaves open, fixed here (each pinned by a test):

* A SWAP_CANCEL that lists any member of a pair voids the whole pair: a pair is atomic.
* ``demoted_for_cause`` is set by a DEMOTE or HALT, and by a SWAP_CANCEL with cause
  ``pair_cause_incoming`` on its own family. The fold never clears it (a fresh FORWARD_SHADOW PASS
  that post-dates the cause is a ``validate`` rule over verdicts).
* ``terminal_frozen`` follows a DEMOTE or HALT of class TERMINAL, or a RETIRE with cause
  ``model_budget_exhausted``. The INTEGRITY freeze follows class INTEGRITY or cause
  ``infra_budget_exhausted``. Class ROLLBACK_FAILED never freezes. Neither freeze is cleared by the
  fold: ARCH gives no autonomous clear (W15).
* A SUPERSEDE makes its family ``rollback_eligible`` unless that family is a drill child (a family
  whose DRILL_PROMOTE took effect). Becoming CHAMPION again clears it.
* A drill episode ends at the first SUPERSEDE or DISPLACED of its child that takes effect, or at the
  child's RETIRE.
* A lineage is named by the introducing row's ``lineage_root_family_id``, else the family itself.

Not here (seam 7b): tallies, ``FamilyView`` origins and the root-lineage check.

Pure: no I/O, no wall clock (the clock is the ``now_ns`` argument), no mutation of the input.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from breezy.persistence.autonomy import pins
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
    "PairStatus",
    "PairView",
    "fold",
]

#: ``→CHAMPION`` kinds that open a pending pair when they carry ``effective_launch_date``.
HEAD_KINDS: Final[frozenset[Kind]] = frozenset(
    {Kind.PROMOTE, Kind.DRILL_PROMOTE, Kind.ROLLBACK, Kind.ROOT_ADMIT}
)
#: The atomic partners of a head; each cites its head's ``transition_id``.
PARTNER_KINDS: Final[frozenset[Kind]] = frozenset({Kind.SUPERSEDE, Kind.DISPLACED})
ACTIVATE_KIND: Final = Kind.ACTIVATE
#: The only kinds that may be a family's first row.
INTRODUCING_KINDS: Final[frozenset[Kind]] = frozenset({Kind.BOOTSTRAP, Kind.ROOT_ADMIT, Kind.MINT})

_SENDER_STATES: Final[frozenset[State]] = frozenset({State.CHAMPION, State.HALTED})

_NS_PER_S: Final = 10**9
_SECONDS_PER_DAY: Final = 86_400
_UNIX_EPOCH_ORDINAL: Final = date(1970, 1, 1).toordinal()


class PairStatus(StrEnum):
    PENDING = "pending"
    EFFECTIVE = "effective"
    LAPSED = "lapsed"
    VOIDED = "voided"


@dataclass(frozen=True, slots=True, kw_only=True)
class PairView:
    """One pending-pair group and what became of it at ``now_ns``."""

    head_transition_id: str
    head_kind: Kind
    incoming_family_id: str
    #: The head first, then its partners in chain order.
    member_transition_ids: tuple[str, ...]
    effective_launch_date: str
    launch_ns: int
    #: The first ACTIVATE that fell inside the window, if any.
    activate_transition_id: str | None
    status: PairStatus
    voided_by_transition_id: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class FamilyView:
    family_id: str
    state: State
    lineage_root_family_id: str
    rollback_eligible: bool = False
    demoted_for_cause: bool = False
    target_ineligible: bool = False
    terminal_frozen: bool = False
    drill_child: bool = False


@dataclass(frozen=True, slots=True, kw_only=True)
class DrillEpisode:
    family_id: str
    start_ns: int
    end_ns: int | None
    drill_promote_transition_id: str

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

    @property
    def senders(self) -> tuple[str, ...]:
        """The families in {CHAMPION, HALTED}, by name: ARCH allows at most one per venue."""
        return tuple(sorted(f for f, st in self.states.items() if st in _SENDER_STATES))


@dataclass(frozen=True, slots=True)
class FoldInvalid:
    """The rows cannot be folded. The resolver maps this to ``replay_invalid``."""

    reason: FoldInvalidReason


@dataclass(slots=True)
class _Head:
    """Private working record; never escapes ``fold``."""

    index: int
    row: TransitionRow
    launch_ns: int
    members: list[int]
    activate: TransitionRow | None = None
    voided_by: TransitionRow | None = None


def _hhmm_ns(hhmm: str) -> int:
    hours, minutes = hhmm.split(":")
    return (int(hours) * 3_600 + int(minutes) * 60) * _NS_PER_S


def _day_start_ns(iso_day: str) -> int:
    days = date.fromisoformat(iso_day).toordinal() - _UNIX_EPOCH_ORDINAL
    return days * _SECONDS_PER_DAY * _NS_PER_S


def _is_head_shape(row: TransitionRow) -> bool:
    return row.kind in HEAD_KINDS and row.to_state is State.CHAMPION


def _is_head(row: TransitionRow) -> bool:
    return _is_head_shape(row) and row.effective_launch_date is not None


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


def _collect_heads(rows: Sequence[TransitionRow]) -> dict[str, _Head]:
    heads: dict[str, _Head] = {}
    for index, row in enumerate(rows):
        if _is_head(row) and row.effective_launch_date is not None:
            launch = _day_start_ns(row.effective_launch_date) + _hhmm_ns(pins.SCHEDULE_LAUNCH_UTC)
            heads[row.transition_id] = _Head(index, row, launch, [index])
    return heads


def _attach_members(rows: Sequence[TransitionRow], heads: dict[str, _Head]) -> set[int]:
    """Attach partners and the first in-window ACTIVATE to their heads.

    Returns the chain positions of rows that are partners of no head: they never take effect.
    """
    orphans: set[int] = set()
    for index, row in enumerate(rows):
        head = heads.get(row.paired_transition_id or "")
        if head is not None and head.index >= index:
            head = None  # a row cannot cite a head that follows it
        if row.kind in PARTNER_KINDS:
            if head is None:
                orphans.add(index)
            else:
                head.members.append(index)
        elif (
            row.kind is ACTIVATE_KIND
            and head is not None
            and head.activate is None
            and _in_activate_window(row, head)
        ):
            head.activate = row
    return orphans


def _in_activate_window(row: TransitionRow, head: _Head) -> bool:
    if row.family_id != head.row.family_id or head.row.effective_launch_date is None:
        return False
    day = _day_start_ns(head.row.effective_launch_date)
    return day + _hhmm_ns(pins.SCHEDULE_STOP_UTC) <= row.ts_ns < head.launch_ns


def _cancel_voids(cancel: TransitionRow, head: _Head) -> bool:
    """Whether ``cancel`` voids ``head``'s pair.

    Before LAUNCH always; from LAUNCH to the launch-window end only a pair that took effect (Z8).
    """
    if cancel.ts_ns < head.launch_ns:
        return True
    day = _day_start_ns(head.row.effective_launch_date or "")
    window_end = day + _hhmm_ns(pins.SCHEDULE_LAUNCH_WINDOW_END_UTC)
    return head.activate is not None and cancel.ts_ns < window_end


def _void_pairs(rows: Sequence[TransitionRow], heads: dict[str, _Head], now_ns: int) -> None:
    """Record on each head the first SWAP_CANCEL (chain order, ``ts_ns <= now_ns``) voiding it."""
    members = {rows[i].transition_id: (head, i) for head in heads.values() for i in head.members}
    for index, row in enumerate(rows):
        if row.kind is not Kind.SWAP_CANCEL or row.ts_ns > now_ns:
            continue
        for cited in row.voids_transition_ids or ():
            found = members.get(cited)
            if found is None:
                continue
            head, member_index = found
            if member_index < index and head.voided_by is None and _cancel_voids(row, head):
                head.voided_by = row


def _pair_status(head: _Head, now_ns: int) -> PairStatus:
    if head.voided_by is not None:
        return PairStatus.VOIDED
    if now_ns < head.launch_ns:
        return PairStatus.PENDING
    return PairStatus.EFFECTIVE if head.activate is not None else PairStatus.LAPSED


def _events(
    rows: Sequence[TransitionRow], heads: dict[str, _Head], orphans: set[int], now_ns: int
) -> list[tuple[int, int, TransitionRow]]:
    """``(instant, chain position, row)`` for every row that can change the fold."""
    pair_members = {i for head in heads.values() for i in head.members}
    out: list[tuple[int, int, TransitionRow]] = []
    for index, row in enumerate(rows):
        if index in orphans or index in pair_members:
            continue
        if row.ts_ns <= now_ns:  # a row written after the clock has not happened yet
            out.append((row.ts_ns, index, row))
    for head in heads.values():
        if _pair_status(head, now_ns) is PairStatus.EFFECTIVE:
            out.extend((head.launch_ns, i, rows[i]) for i in head.members)
    return sorted(out, key=lambda event: (event[0], event[1]))


def _pair_views(
    rows: Sequence[TransitionRow], heads: dict[str, _Head], now_ns: int
) -> tuple[PairView, ...]:
    views: list[PairView] = []
    for head in sorted(heads.values(), key=lambda h: h.index):
        date_text = head.row.effective_launch_date or ""
        views.append(
            PairView(
                head_transition_id=head.row.transition_id,
                head_kind=head.row.kind,
                incoming_family_id=head.row.family_id,
                member_transition_ids=tuple(rows[i].transition_id for i in head.members),
                effective_launch_date=date_text,
                launch_ns=head.launch_ns,
                activate_transition_id=(
                    None if head.activate is None else head.activate.transition_id
                ),
                status=_pair_status(head, now_ns),
                voided_by_transition_id=(
                    None if head.voided_by is None else head.voided_by.transition_id
                ),
            )
        )
    return tuple(views)


@dataclass(slots=True)
class _OpenEpisode:
    """Private working record of a drill episode; frozen into ``DrillEpisode`` at the end."""

    family_id: str
    start_ns: int
    transition_id: str
    end_ns: int | None = None


class _Accumulator:
    """The mutable working state of one ``fold`` call; never escapes it."""

    def __init__(self, lineage_of: Mapping[str, str]) -> None:
        self.states: dict[str, State] = {}
        self.lineage_of = lineage_of
        self.rollback_eligible: set[str] = set()
        self.demoted: set[str] = set()
        self.target_ineligible: set[str] = set()
        self.drill_children: set[str] = set()
        self.frozen_lineages: set[str] = set()
        self.integrity_frozen = False
        self.episodes: list[_OpenEpisode] = []

    def apply(self, instant: int, row: TransitionRow) -> None:
        family = row.family_id
        if row.from_state is not row.to_state:
            self.states[family] = row.to_state
        kind = row.kind
        if _is_head_shape(row):
            self._take_champion(instant, row)
        elif kind is Kind.SUPERSEDE:
            if family not in self.drill_children:
                self.rollback_eligible.add(family)
            self._close_episode(family, instant)
        elif kind is Kind.DISPLACED:
            self._close_episode(family, instant)
        elif kind in (Kind.DEMOTE, Kind.HALT):
            self._halt(row)
        elif kind is Kind.RETIRE:
            self._close_episode(family, instant)
            if row.cause_code is CauseCode.MODEL_BUDGET_EXHAUSTED:
                self._freeze_lineage(family)
        elif kind is Kind.SWAP_CANCEL:
            if row.cause_code is CauseCode.PAIR_CAUSE_INCOMING:
                self.demoted.add(family)
        elif kind is Kind.TARGET_INELIGIBLE:
            self.target_ineligible.add(family)

    def _take_champion(self, instant: int, row: TransitionRow) -> None:
        self.rollback_eligible.discard(row.family_id)
        if row.kind is Kind.DRILL_PROMOTE:
            self.drill_children.add(row.family_id)
            self.episodes.append(_OpenEpisode(row.family_id, instant, row.transition_id))

    def _halt(self, row: TransitionRow) -> None:
        """A failed rollback (ROLLBACK_FAILED) matches neither freeze: it halts its family only."""
        self.rollback_eligible.discard(row.family_id)
        self.demoted.add(row.family_id)
        if row.halt_cause_class is CauseClass.TERMINAL:
            self._freeze_lineage(row.family_id)
        if (
            row.halt_cause_class is CauseClass.INTEGRITY
            or row.cause_code is CauseCode.INFRA_BUDGET_EXHAUSTED
        ):
            self.integrity_frozen = True

    def _freeze_lineage(self, family: str) -> None:
        self.frozen_lineages.add(self.lineage_of.get(family, family))

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
                rollback_eligible=family in self.rollback_eligible,
                demoted_for_cause=family in self.demoted,
                target_ineligible=family in self.target_ineligible,
                terminal_frozen=lineage in self.frozen_lineages,
                drill_child=family in self.drill_children,
            )
        return MappingProxyType(views)

    def drill_episodes(self) -> tuple[DrillEpisode, ...]:
        return tuple(
            DrillEpisode(
                family_id=e.family_id,
                start_ns=e.start_ns,
                end_ns=e.end_ns,
                drill_promote_transition_id=e.transition_id,
            )
            for e in self.episodes
        )


def fold(rows: Sequence[TransitionRow], venue: str, now_ns: int) -> FoldResult | FoldInvalid:
    """Fold one venue's rows (chain order) into family states, flags and pair views at ``now_ns``.

    ``ValueError`` for another venue's row, a bad clock or an unsealed last row; ``TypeError`` for
    a non-row.
    ``FoldInvalid`` for a family whose first row is not BOOTSTRAP, ROOT_ADMIT or MINT, and for a
    →CHAMPION head row with no ``effective_launch_date`` (E-16 c).
    """
    ordered = tuple(rows)
    _check_inputs(ordered, venue, now_ns)
    head_venue_seq = _head_venue_seq(ordered)
    heads = _collect_heads(ordered)
    orphans = _attach_members(ordered, heads)
    _void_pairs(ordered, heads, now_ns)
    lineage_of: dict[str, str] = {}
    pending_roots: set[str] = set()
    for row in ordered:
        if row.family_id not in lineage_of:
            if row.kind not in INTRODUCING_KINDS:
                return FoldInvalid(FoldInvalidReason.FAMILY_INTRODUCED_BY_OTHER_KIND)
            lineage_of[row.family_id] = row.lineage_root_family_id or row.family_id
            if row.transition_id in heads:  # a pending root: SHADOW until its pair takes effect
                pending_roots.add(row.family_id)
        if _is_head_shape(row) and row.effective_launch_date is None:
            return FoldInvalid(FoldInvalidReason.HEAD_MISSING_LAUNCH_DATE)
    acc = _Accumulator(lineage_of)
    acc.states.update((family, State.SHADOW) for family in pending_roots)
    for instant, _index, row in _events(ordered, heads, orphans, now_ns):
        acc.apply(instant, row)
    return FoldResult(
        venue=venue,
        now_ns=now_ns,
        head_venue_seq=head_venue_seq,
        states=MappingProxyType(acc.states),
        pairs=_pair_views(ordered, heads, now_ns),
        families=acc.family_views(),
        integrity_frozen=acc.integrity_frozen,
        drill_episodes=acc.drill_episodes(),
    )
