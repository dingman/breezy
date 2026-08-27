"""Minimum-coverage rule of the asymmetric settlement gate.

Authority: ``docs/evidence/asymmetric_gate_prereg_2026-08-26.md`` (BINDING).
Every rule below is transcribed from it; none is invented here.

The rule, verbatim from "Minimum coverage requirement [R2]"::

    Pre-declared: the `[0,1)` stratum must reach a verdict -- not UNDERPOWERED
    -- in every in-scope city. If it does not, the overall determination is
    NOT YET ANSWERABLE, which is distinct from and may not be reported as PASS.
    A PASS carried entirely by wide-clearance strata is void.

**The defect this module closes.** Rendering that as "no listed blocker was
seen" defeats it: an unlisted or pre-resolution state can fall through to a
wide-stratum ``GO``, so a city whose boundary stratum never satisfied the closed
coverage set would trade on its wide-clearance strata alone -- exactly the void
PASS.

The rule is therefore implemented as **positive membership in a closed set**
(:data:`COVERAGE_SATISFYING`), never as the negation of a list of excluded
classifications. Under the negation form, a classification added by a later
revision of the pre-registration would silently satisfy coverage. Under this
form it silently does not, which is the safe direction.

Motivating figures (``docs/plans/TRADING_SYSTEM_ARCHITECTURE.md:537-540`` and
``:885-889``): at break-even 0.981176, four primary cities' ``[0,1)`` Wilson
lower bounds (LAX 0.7935, MDW 0.7800, MIA 0.8334, SFO 0.7917) are structurally
unreachable while every wide-clearance stratum clears at 0.996+.

**Caveat, binding.** That table is itself stratified by distance from the day's
FINAL METAR max -- a hindsight quantity the pre-registration forbids as a
gating input at [R7]. It motivates this module; it is NEVER an input to it.
Nothing here reads any observed rate, price, or hindsight quantity:
``determine_city`` is pure over already-classified cells, and ``apply_expiry``
is pure over a prior determination plus an evaluation count. There is no I/O and
no mutable global state.
"""

from __future__ import annotations

import enum
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

__all__ = [
    "BOUNDARY_STRATUM",
    "COVERAGE_SATISFYING",
    "CellClassification",
    "CityDetermination",
    "CityDeterminationStatus",
    "ExpiryDisposition",
    "MissingBoundaryStratumError",
    "SettlementCoverageError",
    "UnresolvedCellClassificationError",
    "apply_expiry",
    "determine_city",
    "satisfies_coverage",
]


#: The clearance band that motivated the whole exercise (prereg section 4).
BOUNDARY_STRATUM: Final[str] = "[0,1)"


@enum.unique
class CellClassification(enum.Enum):
    """Outcome of one ``(city, clearance stratum)`` cell.

    Definitions are the pre-registration's:

    ``GO`` / ``NO_GO``
        The cell was powered and evaluated; ``H(c,k)`` cleared, or did not
        clear, ``BE(c,k)`` (prereg section 5).
    ``THETA_CONTINGENT``
        ``BE(c,k) < p̂_anchor(c,k)`` only at the optimistic theta end. Prereg
        [R6]: "proceed, but the verdict is CONDITIONAL on G-15 fee discovery".
    ``OUT_OF_SCOPE_DOM_9``
        [R10]: fewer than 10% of historical city-days reach their daily maximum
        before the venue's actual close, so the city is out of scope entirely
        rather than evidence of a failed instrument.
    ``UNDERPOWERED``
        Below the ``N(c,k)`` floor. Prereg: "contribute to no verdict, and are
        never pooled upward to manufacture power." Subject to the 42-day clock.
    ``PROVISIONAL_UNDERPOWERED``
        [R13]: the early-window crossing count is below the 200-case Branch A
        bar, so the cell "emits no numeric anchor at all". Its population is
        the fixed IEM archive and does not grow with tape, so the 42-day clock
        is meaningless against it. It must be resolved by the bounded
        archive/review workflow before this module may issue a city
        determination.
    ``STRUCTURALLY_UNREACHABLE``
        [R6]: ``BE(c,k) >= p̂_anchor(c,k)`` across the whole theta range, so no
        finite ``N`` satisfies the floor. "A finding, not a timeout ...
        explicitly distinct from UNDERPOWERED and may not be converted to NO-GO
        by the 42-day expiry clause, because more tape cannot fix it." It
        routes to mandatory escalation and is refused here until resolved.
    ``NOT_YET_ANSWERABLE``
        [R2]: the overall determination when the coverage rule is not met. Also
        accepted as a cell input so a nested/prior determination can be fed
        back in; it does not satisfy coverage.
    """

    GO = "GO"
    NO_GO = "NO_GO"
    OUT_OF_SCOPE_DOM_9 = "OUT_OF_SCOPE_DOM_9"
    THETA_CONTINGENT = "THETA_CONTINGENT"
    UNDERPOWERED = "UNDERPOWERED"
    PROVISIONAL_UNDERPOWERED = "PROVISIONAL_UNDERPOWERED"
    STRUCTURALLY_UNREACHABLE = "STRUCTURALLY_UNREACHABLE"
    NOT_YET_ANSWERABLE = "NOT_YET_ANSWERABLE"


@enum.unique
class CityDeterminationStatus(enum.Enum):
    """City-level gate outcome.

    Deliberately distinct from :class:`CellClassification`: a city can be
    pending, expired, or conditionally blocked for reasons that are not
    classifications of one ``(city, stratum)`` cell. ``GO`` alone is the safe
    trading predicate.
    """

    GO = "GO"
    GO_PENDING_ESCALATION = "GO_PENDING_ESCALATION"
    NO_GO = "NO_GO"
    OUT_OF_SCOPE_DOM_9 = "OUT_OF_SCOPE_DOM_9"
    THETA_CONTINGENT = "THETA_CONTINGENT"
    NOT_YET_ANSWERABLE = "NOT_YET_ANSWERABLE"


@enum.unique
class ExpiryDisposition(enum.Enum):
    """Whether the [R3] expiry-to-``NO_GO`` consumer may run."""

    CLOCK_RUNS = "CLOCK_RUNS"
    EXEMPT_PENDING_ESCALATION = "EXEMPT_PENDING_ESCALATION"
    NOT_APPLICABLE = "NOT_APPLICABLE"


#: Closed set: the ONLY classifications that satisfy the ``[0,1)`` coverage
#: requirement. Membership is positive and exhaustive by construction --
#: anything not listed here, including a classification a future revision adds,
#: does not satisfy coverage. Do not reformulate as a negation.
COVERAGE_SATISFYING: Final[frozenset[CellClassification]] = frozenset(
    {
        CellClassification.GO,
        CellClassification.NO_GO,
        CellClassification.THETA_CONTINGENT,
    }
)

#: Wide strata that do not block once the fixed boundary requirement is met.
_WIDE_BENIGN: Final[frozenset[CellClassification]] = frozenset(
    {
        CellClassification.GO,
        CellClassification.UNDERPOWERED,
    }
)

#: Classifications that are pre-resolution states. More tape cannot resolve
#: them, and they require their own bounded archive/review workflow before this
#: module may issue a city determination.
_ESCALATING: Final[frozenset[CellClassification]] = frozenset(
    {
        CellClassification.STRUCTURALLY_UNREACHABLE,
        CellClassification.PROVISIONAL_UNDERPOWERED,
    }
)

_OUT_OF_SCOPE: Final[frozenset[CellClassification]] = frozenset(
    {
        CellClassification.OUT_OF_SCOPE_DOM_9,
    }
)

_CLOCKED_BOUNDARY: Final[frozenset[CellClassification]] = frozenset(
    {
        CellClassification.UNDERPOWERED,
        CellClassification.NOT_YET_ANSWERABLE,
    }
)

_EXPIRY_EVALUATION: Final[int] = 3


class SettlementCoverageError(Exception):
    """Base class for settlement coverage failures."""


class MissingBoundaryStratumError(SettlementCoverageError):
    """Raised when a city's cell map carries no ``[0,1)`` entry.

    Absence must never read as satisfaction: a city with no boundary cell has
    not evaluated the boundary condition, which is the one thing the coverage
    rule exists to require.
    """


class UnresolvedCellClassificationError(SettlementCoverageError):
    """Raised when pre-resolution cells are fed into city determination."""


def satisfies_coverage(classification: object) -> bool:
    """Does ``classification`` at ``[0,1)`` satisfy the coverage requirement?

    Positive membership in :data:`COVERAGE_SATISFYING`. Accepts any object;
    anything that is not a member -- including a classification introduced by a
    later revision -- returns ``False``.
    """
    return classification in COVERAGE_SATISFYING


@dataclass(frozen=True, slots=True, kw_only=True)
class CityDetermination:
    """City-level outcome. Immutable; every field is derived, none is asserted.

    ``tradeable``
        ``True`` exactly when ``determination is CityDeterminationStatus.GO``.
        ``THETA_CONTINGENT`` deliberately does not authorise trading: it is
        conditional on G-15 fee discovery, which a pure function over cell
        classifications cannot observe. Fail closed.
    ``expiry_disposition``
        Explicit sum type consumed by :func:`apply_expiry`. A caller cannot infer
        expiry from a cached boolean.
    ``escalation_required``
        ``False`` for determinations returned by this module. Pending escalation
        cells instead raise :class:`UnresolvedCellClassificationError`, whose
        message names the affected strata.
    ``blocking_cells``
        Sorted stratum labels of every cell that contributed to a non-``GO``
        outcome.
    """

    city: str
    determination: CityDeterminationStatus
    tradeable: bool
    boundary_classification: CellClassification
    blocking_cells: tuple[str, ...]
    expiry_disposition: ExpiryDisposition
    escalation_required: bool
    reason: str


def determine_city(
    city: str,
    cells: Mapping[str, CellClassification],
) -> CityDetermination:
    """Apply the minimum-coverage rule to one city's ``(stratum -> cell)`` map.

    Pure: reads only its arguments, mutates nothing, returns a frozen result. It
    refuses missing boundary cells and unresolved pre-resolution cells before
    issuing any city determination.
    """
    boundary = _validated_boundary(city, cells)
    out_of_scope_cells = _strata_with(cells, _OUT_OF_SCOPE)
    if out_of_scope_cells:
        return _out_of_scope_dom_9(city, boundary, out_of_scope_cells)

    if not satisfies_coverage(boundary):
        return _not_yet_boundary(city, cells, boundary)

    no_go_cells = _strata_with(cells, {CellClassification.NO_GO})
    if no_go_cells:
        return _no_go(city, cells, boundary, no_go_cells)

    contingent_cells = _strata_with(cells, {CellClassification.THETA_CONTINGENT})
    if contingent_cells:
        return _theta_contingent(city, cells, boundary, contingent_cells)

    blocking_cells = _blocking_cells(cells)
    if blocking_cells:
        return _not_yet_wide(city, boundary, blocking_cells)

    return _go(city, boundary)


def _validated_boundary(
    city: str,
    cells: Mapping[str, CellClassification],
) -> CellClassification:
    if BOUNDARY_STRATUM not in cells:
        raise MissingBoundaryStratumError(
            f"city {city!r} has no {BOUNDARY_STRATUM!r} cell; the minimum-coverage "
            f"rule cannot be evaluated and absence does not satisfy it. "
            f"Present strata: {sorted(cells)!r}"
        )

    unresolved_cells = _strata_with(cells, _ESCALATING)
    if unresolved_cells:
        raise UnresolvedCellClassificationError(
            f"city {city!r} has unresolved pre-resolution cell(s) at "
            f"{', '.join(unresolved_cells)}; run the required archive/review "
            f"workflow before issuing a city determination"
        )
    return cells[BOUNDARY_STRATUM]


def apply_expiry(
    determination: CityDetermination,
    *,
    evaluations_elapsed: int,
) -> CityDetermination:
    """Apply [R3]'s third-evaluation expiry to a clocked determination."""
    if determination.expiry_disposition is not ExpiryDisposition.CLOCK_RUNS:
        raise ValueError(
            "apply_expiry requires ExpiryDisposition.CLOCK_RUNS; "
            f"got {determination.expiry_disposition.name}"
        )
    if evaluations_elapsed < 1:
        raise ValueError("evaluations_elapsed must count the initial evaluation and be >= 1")
    if evaluations_elapsed < _EXPIRY_EVALUATION:
        return determination

    return _build_determination(
        determination.city,
        CityDeterminationStatus.NO_GO,
        determination.boundary_classification,
        determination.blocking_cells,
        ExpiryDisposition.NOT_APPLICABLE,
        reason=(
            f"{BOUNDARY_STRATUM} still has no verdict after evaluation "
            f"{evaluations_elapsed}; [R3] converts the city to NO_GO"
        ),
    )


def _not_yet_boundary(
    city: str,
    cells: Mapping[str, CellClassification],
    boundary: CellClassification,
) -> CityDetermination:
    return _build_determination(
        city,
        CityDeterminationStatus.NOT_YET_ANSWERABLE,
        boundary,
        _blocking_cells(cells, extra=(BOUNDARY_STRATUM,)),
        _expiry_for_boundary(boundary),
        reason=_coverage_void_reason(boundary),
    )


def _no_go(
    city: str,
    cells: Mapping[str, CellClassification],
    boundary: CellClassification,
    no_go_cells: tuple[str, ...],
) -> CityDetermination:
    return _build_determination(
        city,
        CityDeterminationStatus.NO_GO,
        boundary,
        _blocking_cells(cells),
        ExpiryDisposition.NOT_APPLICABLE,
        reason=f"NO_GO at {', '.join(no_go_cells)}: the rule is falsified there",
    )


def _theta_contingent(
    city: str,
    cells: Mapping[str, CellClassification],
    boundary: CellClassification,
    contingent_cells: tuple[str, ...],
) -> CityDetermination:
    return _build_determination(
        city,
        CityDeterminationStatus.THETA_CONTINGENT,
        boundary,
        _blocking_cells(cells),
        ExpiryDisposition.NOT_APPLICABLE,
        reason=(
            f"THETA_CONTINGENT at {', '.join(contingent_cells)}: conditional on "
            f"G-15 fee discovery, which this function cannot observe [R6]"
        ),
    )


def _out_of_scope_dom_9(
    city: str,
    boundary: CellClassification,
    out_of_scope_cells: tuple[str, ...],
) -> CityDetermination:
    return _build_determination(
        city,
        CityDeterminationStatus.OUT_OF_SCOPE_DOM_9,
        boundary,
        out_of_scope_cells,
        ExpiryDisposition.NOT_APPLICABLE,
        reason=(
            f"OUT_OF_SCOPE_DOM_9 at {', '.join(out_of_scope_cells)}: [R10] "
            f"excludes the city from the programme failure count"
        ),
    )


def _not_yet_wide(
    city: str,
    boundary: CellClassification,
    blocking_cells: tuple[str, ...],
) -> CityDetermination:
    return _build_determination(
        city,
        CityDeterminationStatus.NOT_YET_ANSWERABLE,
        boundary,
        blocking_cells,
        ExpiryDisposition.NOT_APPLICABLE,
        reason=_wide_block_reason(blocking_cells),
    )


def _go(city: str, boundary: CellClassification) -> CityDetermination:
    return _build_determination(
        city,
        CityDeterminationStatus.GO,
        boundary,
        (),
        ExpiryDisposition.NOT_APPLICABLE,
        reason=f"{BOUNDARY_STRATUM} reached {_label(boundary)} and no cell blocks",
    )


def _build_determination(
    city: str,
    determination: CityDeterminationStatus,
    boundary_classification: CellClassification,
    blocking_cells: tuple[str, ...],
    expiry_disposition: ExpiryDisposition,
    *,
    reason: str,
) -> CityDetermination:
    return CityDetermination(
        city=city,
        determination=determination,
        tradeable=determination is CityDeterminationStatus.GO,
        boundary_classification=boundary_classification,
        blocking_cells=tuple(sorted(blocking_cells)),
        expiry_disposition=expiry_disposition,
        escalation_required=False,
        reason=reason,
    )


def _strata_with(
    cells: Mapping[str, CellClassification],
    classifications: set[CellClassification] | frozenset[CellClassification],
) -> tuple[str, ...]:
    return tuple(sorted(stratum for stratum, cell in cells.items() if cell in classifications))


def _blocking_cells(
    cells: Mapping[str, CellClassification],
    *,
    extra: tuple[str, ...] = (),
) -> tuple[str, ...]:
    blocking = set(extra)
    blocking.update(stratum for stratum, cell in cells.items() if cell not in _WIDE_BENIGN)
    return tuple(sorted(blocking))


def _expiry_for_boundary(classification: object) -> ExpiryDisposition:
    if classification in _CLOCKED_BOUNDARY:
        return ExpiryDisposition.CLOCK_RUNS
    if classification in _ESCALATING:
        return ExpiryDisposition.EXEMPT_PENDING_ESCALATION
    return ExpiryDisposition.NOT_APPLICABLE


def _coverage_void_reason(boundary: object) -> str:
    return (
        f"{BOUNDARY_STRATUM} is {_label(boundary)}, which is not in the closed "
        f"COVERAGE_SATISFYING set; a PASS carried entirely by wide-clearance "
        f"strata is void [R2]"
    )


def _wide_block_reason(blocking_cells: tuple[str, ...]) -> str:
    return (
        f"non-benign wide stratum at {', '.join(blocking_cells)}: only GO and "
        f"UNDERPOWERED are benign outside {BOUNDARY_STRATUM} [R2]"
    )


def _label(classification: object) -> str:
    """Name of ``classification``, tolerating a foreign object defensively."""
    return getattr(classification, "name", repr(classification))
