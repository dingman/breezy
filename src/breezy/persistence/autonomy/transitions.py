"""Closed kind tables and the shared admissibility predicate (ARCH-0 seam A 6b; AC 13).

``ALLOWED`` is the ARCH C5 "Allowed transitions" table, ``KIND_MASK`` the AUT-5 r7 3.2 writer-mode
table, ``WIDENING_KINDS`` and ``RESTRICTIVE_KINDS`` the two sets the stage flag and the restrictive
paths read. ``rows_admissible`` is the only place a stage's kind sets are compared against rows
(``test_admissibility_predicate_has_one_home``, seam 6c); the store, the resolver and the watch
actor all call it.

Choices ARCH leaves open, fixed here:

* Widening is decided per row (A6b-R1, E-16 d): a PROMOTE widens only toward CHAMPION.
  ``WIDENING_KINDS`` stays the kind set the pins subset check reads.
* RETIRE is neutral: it is in neither ``WIDENING_KINDS`` nor ``RESTRICTIVE_KINDS``, so no stage
  flag gates it and no restrictive-write rule applies to it.
* ``ALLOWED[ROOT_ADMIT]`` holds ``(SHADOW, CHAMPION)`` (the ARCH table) and ``(None, CHAMPION)``
  (A6b-R4, E-16 b: a family unknown to the fold is introduced from the empty state).
* ``PAIR_KINDS`` are the kinds that can belong to one logical sender change: the four heads, the
  two partners and ACTIVATE.
* ``validate`` (seams 7c, 7d) lives in ``validate`` (rules of 7d in ``validate_ii``) and is
  re-exported here, with ``first_refusal``, ``Refusal``, ``Rule`` and ``RuleII``; this module keeps
  the closed tables so that it stays under its size cap.

Pure; nothing here reads a clock or the filesystem.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import Final

from breezy.persistence.autonomy.fold import ACTIVATE_KIND, HEAD_KINDS, PARTNER_KINDS
from breezy.persistence.autonomy.schemas import (
    AdmissibilityResult,
    Kind,
    RefusalReason,
    StageView,
    State,
    TransitionRow,
    WriterMode,
    compute_transition_id,
)
from breezy.persistence.autonomy.validate import Refusal, Rule, RuleII, first_refusal, validate

__all__ = [
    "ALLOWED",
    "KIND_MASK",
    "PAIR_KINDS",
    "RESTRICTIVE_KINDS",
    "WIDENING_KINDS",
    "Refusal",
    "Rule",
    "RuleII",
    "first_refusal",
    "is_widening",
    "is_widening_row",
    "rows_admissible",
    "transition_id",
    "validate",
]

#: The Y9 idempotency id, under the plan's name (ruling A6a-A1; the function lives in ``schemas``).
transition_id = compute_transition_id

_Pair = tuple[State | None, State]

_ALLOWED_PAIRS: Final[dict[Kind, frozenset[_Pair]]] = {
    Kind.BOOTSTRAP: frozenset(
        {(None, State.CHAMPION), (None, State.RETIRED), (None, State.SHADOW)}
    ),
    Kind.MINT: frozenset({(None, State.SHADOW)}),
    Kind.PROMOTE: frozenset({(State.SHADOW, State.CHALLENGER), (State.CHALLENGER, State.CHAMPION)}),
    Kind.DRILL_ADMIT: frozenset({(State.SHADOW, State.CHALLENGER)}),
    Kind.DRILL_PROMOTE: frozenset({(State.CHALLENGER, State.CHAMPION)}),
    Kind.ROLLBACK: frozenset({(State.CHALLENGER, State.CHAMPION)}),
    Kind.ROOT_ADMIT: frozenset({(State.SHADOW, State.CHAMPION), (None, State.CHAMPION)}),
    Kind.SUPERSEDE: frozenset({(State.CHAMPION, State.CHALLENGER)}),
    Kind.DISPLACED: frozenset({(State.HALTED, State.CHALLENGER)}),
    Kind.ACTIVATE: frozenset({(State.CHALLENGER, State.CHALLENGER), (State.SHADOW, State.SHADOW)}),
    Kind.SWAP_CANCEL: frozenset({(State.CHALLENGER, State.CHALLENGER)}),
    Kind.TARGET_INELIGIBLE: frozenset({(State.CHALLENGER, State.CHALLENGER)}),
    Kind.ATTEST: frozenset({(State.CHAMPION, State.CHAMPION)}),
    Kind.DEMOTE: frozenset({(State.CHAMPION, State.HALTED)}),
    Kind.HALT: frozenset({(State.CHAMPION, State.HALTED)}),
    Kind.RESUME: frozenset({(State.HALTED, State.CHAMPION)}),
    Kind.RETIRE: frozenset(
        {
            (State.HALTED, State.RETIRED),
            (State.SHADOW, State.RETIRED),
            (State.CHALLENGER, State.RETIRED),
        }
    ),
    Kind.HWM_RESET: frozenset((state, state) for state in State),
}

#: Every allowed ``(from_state, to_state)`` pair per kind; ``None`` is the empty state.
ALLOWED: Final[Mapping[Kind, frozenset[_Pair]]] = MappingProxyType(_ALLOWED_PAIRS)

_MASK: Final[dict[WriterMode, frozenset[Kind]]] = {
    WriterMode.INTRADAY: frozenset(
        {Kind.DEMOTE, Kind.HALT, Kind.SWAP_CANCEL, Kind.TARGET_INELIGIBLE, Kind.ATTEST}
    ),
    WriterMode.PRELAUNCH: frozenset(
        {
            Kind.ACTIVATE,
            Kind.SWAP_CANCEL,
            Kind.TARGET_INELIGIBLE,
            Kind.RESUME,
            Kind.ROLLBACK,
            Kind.SUPERSEDE,
            Kind.DISPLACED,
            Kind.ROOT_ADMIT,
            Kind.DEMOTE,
            Kind.HALT,
        }
    ),
    WriterMode.DAILY: frozenset(
        {
            Kind.MINT,
            Kind.PROMOTE,
            Kind.DRILL_ADMIT,
            Kind.DRILL_PROMOTE,
            Kind.ROLLBACK,
            Kind.SUPERSEDE,
            Kind.DISPLACED,
            Kind.SWAP_CANCEL,
            Kind.TARGET_INELIGIBLE,
            Kind.DEMOTE,
            Kind.HALT,
            Kind.RETIRE,
        }
    ),
    WriterMode.BOOTSTRAP: frozenset({Kind.BOOTSTRAP}),
    WriterMode.OPERATOR_CLI: frozenset(
        {Kind.HWM_RESET, Kind.DEMOTE, Kind.HALT, Kind.SWAP_CANCEL, Kind.RETIRE}
    ),
}

#: The kinds each writer mode may write (AUT-5 r7 3.2 ``KIND_MASK``, literal).
KIND_MASK: Final[Mapping[WriterMode, frozenset[Kind]]] = MappingProxyType(_MASK)

#: Kinds a stage flag gates (AUT-5 r7 3.2). The partners and ACTIVATE are masked with the kinds
#: that widen sending.
WIDENING_KINDS: Final[frozenset[Kind]] = frozenset(
    {
        Kind.PROMOTE,
        Kind.DRILL_PROMOTE,
        Kind.ROLLBACK,
        Kind.RESUME,
        Kind.ROOT_ADMIT,
        Kind.ACTIVATE,
        Kind.SUPERSEDE,
        Kind.DISPLACED,
        Kind.DRILL_ADMIT,
    }
)

#: Kinds that only stop entries; never masked by a stage flag, never capped.
RESTRICTIVE_KINDS: Final[frozenset[Kind]] = frozenset(
    {Kind.DEMOTE, Kind.HALT, Kind.SWAP_CANCEL, Kind.TARGET_INELIGIBLE}
)

#: Kinds that can belong to one logical sender change (head, partner, ACTIVATE).
PAIR_KINDS: Final[frozenset[Kind]] = HEAD_KINDS | PARTNER_KINDS | {ACTIVATE_KIND}

#: Kinds whose admission rules are implemented in code. Ships empty; only an owner WP adds to it,
#: by a reviewed commit. A widening kind that is enabled but not implemented is refused.
_ADMISSION_IMPLEMENTED: Final[frozenset[Kind]] = frozenset()


def is_widening(kind: Kind) -> bool:
    """True when ``kind`` is one a stage flag gates."""
    return kind in WIDENING_KINDS


def is_widening_row(row: TransitionRow) -> bool:
    """True when ``row`` is one a stage flag gates (A6b-R1; AUT-5 r7:166).

    Widening is decided per row: a PROMOTE widens only toward CHAMPION, so a SHADOW to CHALLENGER
    nomination is never gated. Every other widening kind is gated whatever its states.
    """
    if row.kind is Kind.PROMOTE:
        return row.to_state is State.CHAMPION
    return is_widening(row.kind)


def rows_admissible(rows: Sequence[TransitionRow], *, stage: StageView) -> AdmissibilityResult:
    """Walk ``rows`` in chain order and stop at the first refused widening row.

    A widening row is refused as ``widening_kind_not_enabled`` when its kind is outside
    ``stage.enabled_widening_kinds``, else as ``admission_pending`` when outside
    ``stage.admission_implemented``. ``rows[:admitted]`` is admissible; ``reason is None`` means
    every row is. Restrictive and neutral rows are admissible only until the first refusal.
    """
    enabled = frozenset(stage.enabled_widening_kinds)
    implemented = frozenset(stage.admission_implemented)
    for position, row in enumerate(rows):
        if not is_widening_row(row):
            continue
        if row.kind not in enabled:
            return AdmissibilityResult(position, RefusalReason.WIDENING_KIND_NOT_ENABLED)
        if row.kind not in implemented:
            return AdmissibilityResult(position, RefusalReason.ADMISSION_PENDING)
    return AdmissibilityResult(len(rows), None)
