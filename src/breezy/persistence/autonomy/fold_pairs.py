"""Pending-pair handling of the registry fold (ARCH-0 seam A 7d, ruling A7d-R4).

Moved out of ``fold`` unchanged so that ``fold`` stays under its size cap. A pair is a →CHAMPION
head row that carries ``effective_launch_date`` D, the SUPERSEDE or DISPLACED partners that cite it
through ``paired_transition_id``, and the first ACTIVATE of the head's family written in
[STOP, LAUNCH) on D. This module attaches the members, applies SWAP_CANCEL voiding (before LAUNCH
always; from LAUNCH to the launch-window end only a pair that took effect, Z8), decides each pair's
status at ``now_ns``, orders the rows that change the fold, and builds the ``PairView`` values.
The schedule helpers (``schedule_ns``) live here too, because the pair rules read them.

Pure: no I/O, no wall clock.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Final

from breezy.persistence.autonomy import pins
from breezy.persistence.autonomy.schemas import Kind, State, TransitionRow

__all__ = [
    "ACTIVATE_KIND",
    "HEAD_KINDS",
    "PARTNER_KINDS",
    "Head",
    "PairStatus",
    "PairView",
    "attach_members",
    "collect_heads",
    "events",
    "is_head",
    "is_head_shape",
    "pair_views",
    "schedule_ns",
    "void_pairs",
]

#: ``→CHAMPION`` kinds that open a pending pair when they carry ``effective_launch_date``.
HEAD_KINDS: Final[frozenset[Kind]] = frozenset(
    {Kind.PROMOTE, Kind.DRILL_PROMOTE, Kind.ROLLBACK, Kind.ROOT_ADMIT}
)
#: The atomic partners of a head; each cites its head's ``transition_id``.
PARTNER_KINDS: Final[frozenset[Kind]] = frozenset({Kind.SUPERSEDE, Kind.DISPLACED})
ACTIVATE_KIND: Final = Kind.ACTIVATE

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
    #: ``(family_id, to_state)`` of each member, in the same order: what the pair does at LAUNCH.
    member_effects: tuple[tuple[str, State], ...] = ()
    effective_launch_date: str
    launch_ns: int
    #: The first ACTIVATE that fell inside the window, if any.
    activate_transition_id: str | None
    status: PairStatus
    voided_by_transition_id: str | None = None


@dataclass(slots=True)
class Head:
    """Private working record; never escapes ``fold``."""

    index: int
    row: TransitionRow
    launch_ns: int
    members: list[int]
    activate: TransitionRow | None = None
    voided_by: TransitionRow | None = None


def hhmm_ns(hhmm: str) -> int:
    hours, minutes = hhmm.split(":")
    return (int(hours) * 3_600 + int(minutes) * 60) * _NS_PER_S


def day_start_ns(iso_day: str) -> int:
    days = date.fromisoformat(iso_day).toordinal() - _UNIX_EPOCH_ORDINAL
    return days * _SECONDS_PER_DAY * _NS_PER_S


def schedule_ns(iso_day: str, hhmm: str) -> int:
    """Epoch nanoseconds of ``hhmm`` UTC on ``iso_day`` (the schedule pins are ``"HH:MM"``)."""
    return day_start_ns(iso_day) + hhmm_ns(hhmm)


def is_head_shape(row: TransitionRow) -> bool:
    return row.kind in HEAD_KINDS and row.to_state is State.CHAMPION


def is_head(row: TransitionRow) -> bool:
    return is_head_shape(row) and row.effective_launch_date is not None


def collect_heads(rows: Sequence[TransitionRow]) -> dict[str, Head]:
    heads: dict[str, Head] = {}
    for index, row in enumerate(rows):
        if is_head(row) and row.effective_launch_date is not None:
            launch = schedule_ns(row.effective_launch_date, pins.SCHEDULE_LAUNCH_UTC)
            heads[row.transition_id] = Head(index, row, launch, [index])
    return heads


def attach_members(rows: Sequence[TransitionRow], heads: dict[str, Head]) -> set[int]:
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


def _in_activate_window(row: TransitionRow, head: Head) -> bool:
    if row.family_id != head.row.family_id or head.row.effective_launch_date is None:
        return False
    day = day_start_ns(head.row.effective_launch_date)
    return day + hhmm_ns(pins.SCHEDULE_STOP_UTC) <= row.ts_ns < head.launch_ns


def _cancel_voids(cancel: TransitionRow, head: Head) -> bool:
    """Whether ``cancel`` voids ``head``'s pair.

    Before LAUNCH always; from LAUNCH to the launch-window end only a pair that took effect (Z8).
    """
    if cancel.ts_ns < head.launch_ns:
        return True
    day = day_start_ns(head.row.effective_launch_date or "")
    window_end = day + hhmm_ns(pins.SCHEDULE_LAUNCH_WINDOW_END_UTC)
    return head.activate is not None and cancel.ts_ns < window_end


def void_pairs(rows: Sequence[TransitionRow], heads: dict[str, Head], now_ns: int) -> None:
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


def _pair_status(head: Head, now_ns: int) -> PairStatus:
    if head.voided_by is not None:
        return PairStatus.VOIDED
    if now_ns < head.launch_ns:
        return PairStatus.PENDING
    return PairStatus.EFFECTIVE if head.activate is not None else PairStatus.LAPSED


def events(
    rows: Sequence[TransitionRow], heads: dict[str, Head], orphans: set[int], now_ns: int
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


def pair_views(
    rows: Sequence[TransitionRow], heads: dict[str, Head], now_ns: int
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
                member_effects=tuple((rows[i].family_id, rows[i].to_state) for i in head.members),
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
