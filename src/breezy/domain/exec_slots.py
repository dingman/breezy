"""Pure slot admission model (EXEC-PAR WP1; inert, no caller yet).

``admit`` decides whether a new exec intent may open a slot, given an
immutable view of the slot table. It performs no I/O and reads no clock:
``now_ns`` is a parameter. At ``k == 1`` it is exactly the single-slot latch
(deny iff anything is open); at ``k > 1`` it adds slug exclusivity, a K cap and
cool-off for entries, and an operator entry halt.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["Admit", "SlotRecord", "SlotTableView", "Wait", "admit"]


@dataclass(frozen=True)
class SlotRecord:
    """One readable open slot."""

    key: str
    slug: str
    is_exit: bool


@dataclass(frozen=True)
class SlotTableView:
    """Immutable snapshot of the slot table.

    ``unreadable_slots`` counts slots that could not be decoded; any such slot
    quarantines the table. ``cooloff`` holds ``(slug, until_ns)`` pairs.
    """

    open_slots: tuple[SlotRecord, ...] = ()
    unreadable_slots: int = 0
    cooloff: tuple[tuple[str, int], ...] = ()


@dataclass(frozen=True)
class Admit:
    """The intent may open a slot."""


@dataclass(frozen=True)
class Wait:
    """The intent is denied for ``reason``."""

    reason: str


def admit(
    table: SlotTableView,
    slug: str,
    is_exit: bool,
    k: int,
    entry_halted: bool,
    now_ns: int,
) -> Admit | Wait:
    """Return ``Admit()`` or ``Wait(reason)`` for a would-be slot on ``slug``.

    Reason order (first match wins): quarantine -> slot_open (k == 1) /
    slug_open (k > 1) -> entry_halt -> k_full -> cooloff. ``slug_open`` is
    reported before ``entry_halt`` on purpose: the allow/deny outcome is
    identical either way, only the reported reason differs.
    """
    if table.unreadable_slots > 0:
        return Wait("quarantine")
    if k == 1:
        return Wait("slot_open") if table.open_slots else Admit()
    if any(slot.slug == slug for slot in table.open_slots):
        return Wait("slug_open")
    if is_exit:
        return Admit()
    if entry_halted:
        return Wait("entry_halt")
    if sum(1 for slot in table.open_slots if not slot.is_exit) >= k:
        return Wait("k_full")
    if any(s == slug and until_ns > now_ns for s, until_ns in table.cooloff):
        return Wait("cooloff")
    return Admit()
