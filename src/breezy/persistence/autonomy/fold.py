"""The structural effective-time fold of a venue chain (ARCH-0 seam A 6b; ARCH C5 "Effective-time
fold", Y8).

``fold(rows, venue, now_ns)`` is a pure function of one venue's rows and the clock. It computes:

* the state of every family at ``now_ns``;
* the pending pairs: a ``→CHAMPION`` head row that carries ``effective_launch_date`` D, with the
  SUPERSEDE or DISPLACED partners that cite it through ``paired_transition_id``;
* the ACTIVATE window: an ACTIVATE that names the head in ``paired_transition_id``, belongs to the
  head's family and is written in [STOP, LAUNCH) on D;
* the lapse: at LAUNCH on D a pair takes effect only with such an ACTIVATE, else it never does.

Row order and effective time. Immediate rows (no ``effective_launch_date``) apply at their
``ts_ns``; the members of an effective pair apply at LAUNCH. Rows apply in ``(instant, chain
position)`` order. A row whose ``from_state == to_state`` (ATTEST, HWM_RESET, ACTIVATE,
SWAP_CANCEL, TARGET_INELIGIBLE) never changes a state. ``from_state`` consistency is ``validate``'s
to refuse (seams 7c, 7d); the fold applies ``to_state``.

Not here (seam 7a/7b): SWAP_CANCEL voiding, ``demoted_for_cause``, freezes, tallies, drill episodes,
``FamilyView`` origins and the root-lineage check. Until 7a lands nothing consumes this fold.

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

_NS_PER_S: Final = 10**9
_SECONDS_PER_DAY: Final = 86_400
_UNIX_EPOCH_ORDINAL: Final = date(1970, 1, 1).toordinal()


class PairStatus(StrEnum):
    PENDING = "pending"
    EFFECTIVE = "effective"
    LAPSED = "lapsed"


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


@dataclass(frozen=True, slots=True)
class FoldResult:
    venue: str
    now_ns: int
    #: Rows folded (the chain's head ``venue_seq`` when given a whole chain).
    head_venue_seq: int
    states: Mapping[str, State]
    pairs: tuple[PairView, ...]


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


def _hhmm_ns(hhmm: str) -> int:
    hours, minutes = hhmm.split(":")
    return (int(hours) * 3_600 + int(minutes) * 60) * _NS_PER_S


def _day_start_ns(iso_day: str) -> int:
    days = date.fromisoformat(iso_day).toordinal() - _UNIX_EPOCH_ORDINAL
    return days * _SECONDS_PER_DAY * _NS_PER_S


def _is_head(row: TransitionRow) -> bool:
    return (
        row.kind in HEAD_KINDS
        and row.to_state is State.CHAMPION
        and row.effective_launch_date is not None
    )


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


def _pair_status(head: _Head, now_ns: int) -> PairStatus:
    if now_ns < head.launch_ns:
        return PairStatus.PENDING
    return PairStatus.EFFECTIVE if head.activate is not None else PairStatus.LAPSED


def _events(
    rows: Sequence[TransitionRow], heads: dict[str, _Head], orphans: set[int], now_ns: int
) -> list[tuple[int, int, TransitionRow]]:
    """``(instant, chain position, row)`` for every row that can change a state."""
    pair_members = {i for head in heads.values() for i in head.members}
    out: list[tuple[int, int, TransitionRow]] = []
    for index, row in enumerate(rows):
        if index in orphans or index in pair_members or row.from_state is row.to_state:
            continue
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
            )
        )
    return tuple(views)


def fold(rows: Sequence[TransitionRow], venue: str, now_ns: int) -> FoldResult | FoldInvalid:
    """Fold one venue's rows (chain order) into family states and pair views at ``now_ns``.

    ``ValueError`` for another venue's row or a bad clock, ``TypeError`` for a non-row.
    ``FoldInvalid`` for a family whose first row is not BOOTSTRAP, ROOT_ADMIT or MINT.
    """
    ordered = tuple(rows)
    _check_inputs(ordered, venue, now_ns)
    heads = _collect_heads(ordered)
    orphans = _attach_members(ordered, heads)
    states: dict[str, State] = {}
    seen: set[str] = set()
    for row in ordered:
        if row.family_id in seen:
            continue
        if row.kind not in INTRODUCING_KINDS:
            return FoldInvalid(FoldInvalidReason.FAMILY_INTRODUCED_BY_OTHER_KIND)
        seen.add(row.family_id)
        if row.transition_id in heads:  # a pending root: SHADOW until its pair takes effect
            states[row.family_id] = State.SHADOW
    for _instant, _index, row in _events(ordered, heads, orphans, now_ns):
        states[row.family_id] = row.to_state
    return FoldResult(
        venue=venue,
        now_ns=now_ns,
        head_venue_seq=len(ordered),
        states=MappingProxyType(states),
        pairs=_pair_views(ordered, heads, now_ns),
    )
