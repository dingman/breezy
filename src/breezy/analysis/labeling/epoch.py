"""Fill epoch class: the capture epoch decides which fills C1 may attribute (AUT-2 r7 3.4.2).

A fill is ``POST_EPOCH`` iff ``ts_event >= capture_epoch_start`` and its ``client_order_id`` has a
C1 ``OrderLink``. A fill with ``ts_event >= capture_epoch_start`` and no link is UNRESOLVED (C1
invariant (ii) broken), never a backfill candidate.

An absent epoch file makes every fill ``PRE_EPOCH`` only while the venue's C1 store holds no
``OrderLink`` (today's state). Where the epoch cannot be trusted against C1 (P10) the outcome is
UNRESOLVED with a CRITICAL: the epoch is absent or unreadable while an ``OrderLink`` exists, or an
``OrderLink`` is older than the epoch. An unreadable epoch with no ``OrderLink`` at all is an
unreadable input (exit 1, no marker), raised as ``EpochUnreadableInput``.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final, Protocol

from breezy.adapters.polymarket_us.exec.client import DurableFillRecord
from breezy.persistence.autonomy.capture_epoch import EpochUnreadable, read_epoch
from breezy.persistence.autonomy.capture_reader import (
    C1View,
    DecisionView,
    OrderLinkView,
    project_c1,
    read_capture_stream,
)
from breezy.persistence.autonomy.paths import family_component, venue_component
from breezy.persistence.autonomy.single_read import SingleReadRefused

__all__ = [
    "C1Epoch",
    "C1Index",
    "EpochClass",
    "EpochOutcome",
    "EpochReader",
    "EpochUnreadableInput",
    "UnresolvedCause",
    "fill_epoch_class",
    "load_live_c1_views",
]

_LIVE_SOURCE: Final = "live"
_STREAM_DIR: Final = ("derived", "capture_stream")


class EpochClass(StrEnum):
    POST_EPOCH = "POST_EPOCH"
    PRE_EPOCH = "PRE_EPOCH"


class UnresolvedCause(StrEnum):
    EPOCH_INCONSISTENT_WITH_C1 = "epoch_inconsistent_with_c1"
    ORDER_LINK_BEFORE_EPOCH = "order_link_before_epoch"
    POST_EPOCH_WITHOUT_ORDER_LINK = "post_epoch_fill_without_order_link"


class EpochUnreadableInput(Exception):
    """The epoch file is unreadable and no OrderLink exists: an unreadable input, never NO_INPUT."""


@dataclass(frozen=True)
class EpochOutcome:
    """Either an ``epoch_class`` or an ``unresolved_cause`` (never both). ``critical`` is True for
    every UNRESOLVED outcome: the label run alerts on it and writes the unresolved journal row."""

    epoch_class: EpochClass | None
    unresolved_cause: UnresolvedCause | None
    critical: bool


class EpochReader(Protocol):
    """What the epoch decision reads: the family's epoch and the venue's C1 order links."""

    def epoch_start_ns(self) -> int | None:
        """The epoch instant, ``None`` when absent; ``EpochUnreadable`` when untrustworthy."""
        ...

    def order_link(self, client_order_id: str) -> OrderLinkView | None: ...

    def earliest_order_link_ns(self) -> int | None:
        """The oldest OrderLink ``ts_ns`` in the venue's C1 store; ``None`` when it holds none."""
        ...


def _pre_epoch() -> EpochOutcome:
    return EpochOutcome(EpochClass.PRE_EPOCH, None, critical=False)


def _unresolved(cause: UnresolvedCause) -> EpochOutcome:
    return EpochOutcome(None, cause, critical=True)


def fill_epoch_class(fill: DurableFillRecord, reader: EpochReader) -> EpochOutcome:
    """Classify one durable fill. Raises ``EpochUnreadableInput`` (see the module docstring)."""
    earliest = reader.earliest_order_link_ns()
    link = reader.order_link(fill.client_order_id)
    try:
        start = reader.epoch_start_ns()
    except EpochUnreadable as exc:
        if earliest is None:
            raise EpochUnreadableInput("capture epoch unreadable with no OrderLink in C1") from exc
        return _inconsistent(fill, link, earliest)
    if start is None:
        if earliest is None:
            return _pre_epoch()
        return _inconsistent(fill, link, earliest)
    if link is not None and link.ts_ns < start:
        return _unresolved(UnresolvedCause.ORDER_LINK_BEFORE_EPOCH)
    if fill.ts_event < start:
        return _pre_epoch()
    if link is None:
        return _unresolved(UnresolvedCause.POST_EPOCH_WITHOUT_ORDER_LINK)
    return EpochOutcome(EpochClass.POST_EPOCH, None, critical=False)


def _inconsistent(
    fill: DurableFillRecord, link: OrderLinkView | None, earliest: int
) -> EpochOutcome:
    """The epoch is absent or unreadable while C1 holds links: only a fill that predates every
    link can still be told apart, and it stays storage-only."""
    if link is not None or fill.ts_event >= earliest:
        return _unresolved(UnresolvedCause.EPOCH_INCONSISTENT_WITH_C1)
    return _pre_epoch()


def load_live_c1_views(data_root: Path, venue: str) -> tuple[C1View, ...]:
    """Project every ``live`` boot directory of the venue's capture stream (never ``canary``).

    The tree is ``derived/capture_stream/<venue>/live/<instance_id>/``; an absent tree is empty.
    A boot directory that cannot be read or projected raises (a refusal is never a skip).
    """
    live_root = data_root.joinpath(*_STREAM_DIR, venue_component(venue), _LIVE_SOURCE)
    if not live_root.is_dir():
        return ()
    views: list[C1View] = []
    with os.scandir(live_root) as entries:
        boots = sorted(entry.name for entry in entries)
    for name in boots:
        views.append(project_c1(read_capture_stream(live_root / name)))
    return tuple(views)


class C1Index:
    """The C1 order links and decisions of a set of boots, indexed for the joins.

    The first link seen for a ``client_order_id`` wins (``capture_reader.join_fills_to_decisions``
    reports a conflicting second decision as ``LINK_CONFLICT``; the attribution refuses it).
    """

    def __init__(self, views: Iterable[C1View]) -> None:
        links: dict[str, list[OrderLinkView]] = {}
        decisions: dict[str, DecisionView] = {}
        for view in views:
            for link in view.order_links:
                links.setdefault(link.client_order_id, []).append(link)
            for decision in view.decisions:
                decisions.setdefault(decision.decision_id, decision)
        self._links = links
        self._decisions = decisions

    def order_link(self, client_order_id: str) -> OrderLinkView | None:
        found = self._links.get(client_order_id)
        return found[0] if found else None

    def order_links(self, client_order_id: str) -> tuple[OrderLinkView, ...]:
        return tuple(self._links.get(client_order_id, ()))

    def decision(self, decision_id: str) -> DecisionView | None:
        return self._decisions.get(decision_id)

    def earliest_order_link_ns(self) -> int | None:
        return min((link.ts_ns for found in self._links.values() for link in found), default=None)


class C1Epoch:
    """The production :class:`EpochReader`: a family epoch file plus the venue's live C1 streams."""

    def __init__(self, data_root: Path, *, venue: str, family_id: str) -> None:
        self._data_root = data_root
        self._family_id = family_component(family_id)
        self._venue = venue_component(venue)
        self._index: C1Index | None = None

    def epoch_start_ns(self) -> int | None:
        try:
            record = read_epoch(self._data_root, self._family_id)
        except (EpochUnreadable, SingleReadRefused) as exc:
            raise EpochUnreadable("capture epoch cannot be trusted") from exc
        return None if record is None else record.epoch_start_ns

    def c1(self) -> C1Index:
        if self._index is None:
            self._index = C1Index(load_live_c1_views(self._data_root, self._venue))
        return self._index

    def order_link(self, client_order_id: str) -> OrderLinkView | None:
        return self.c1().order_link(client_order_id)

    def decision(self, decision_id: str) -> DecisionView | None:
        return self.c1().decision(decision_id)

    def earliest_order_link_ns(self) -> int | None:
        return self.c1().earliest_order_link_ns()
