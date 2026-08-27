"""Programme-level rollup for the asymmetric settlement gate."""

from __future__ import annotations

import enum
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Final

from breezy.settlement.coverage import (
    CellClassification,
    CityDetermination,
    CityDeterminationStatus,
    ExpiryDisposition,
    apply_expiry,
    determine_city,
)

__all__ = [
    "NYC_SECONDARY_CITY",
    "PROGRAMME_NO_GO_THRESHOLD",
    "CityProgrammeDetermination",
    "CityProgrammeScope",
    "CityStatusRecognitionError",
    "InScopeCityMismatchError",
    "PositionTakingDisposition",
    "ProgrammeDetermination",
    "ProgrammeDeterminationStatus",
    "ProgrammeInputError",
    "determine_programme",
]


NYC_SECONDARY_CITY: Final[str] = "NYC"
PROGRAMME_NO_GO_THRESHOLD: Final[int] = 2


@enum.unique
class ProgrammeDeterminationStatus(enum.Enum):
    """Programme-level outcome for the primary verdict."""

    PRIMARY_GO = "PRIMARY_GO"
    PROGRAMME_NOT_REJECTED = "PROGRAMME_NOT_REJECTED"
    PROGRAMME_NOT_YET_ANSWERABLE = "PROGRAMME_NOT_YET_ANSWERABLE"
    PROGRAMME_REJECTED = "PROGRAMME_REJECTED"
    THETA_CONTINGENT = "THETA_CONTINGENT"


@enum.unique
class PositionTakingDisposition(enum.Enum):
    """Programme-level permission state for new position taking."""

    MAY_OPEN_NEW_POSITIONS = "MAY_OPEN_NEW_POSITIONS"
    NOT_TRADEABLE = "NOT_TRADEABLE"
    HALT_NEW_POSITIONS_HOLD_OPEN_TO_SETTLEMENT = (
        "HALT_NEW_POSITIONS_HOLD_OPEN_TO_SETTLEMENT"
    )


@enum.unique
class CityProgrammeScope(enum.Enum):
    """Where a city is reported in the programme determination."""

    PRIMARY = "PRIMARY"
    SECONDARY_NYC = "SECONDARY_NYC"
    OUT_OF_SCOPE_DOM_9 = "OUT_OF_SCOPE_DOM_9"


_PRIMARY_REJECTING_STATUSES: Final[frozenset[CityDeterminationStatus]] = frozenset(
    {
        CityDeterminationStatus.NO_GO,
    }
)

_PRIMARY_NON_REJECTING_STATUSES: Final[frozenset[CityDeterminationStatus]] = frozenset(
    {
        CityDeterminationStatus.GO,
        CityDeterminationStatus.GO_PENDING_ESCALATION,
        CityDeterminationStatus.NOT_YET_ANSWERABLE,
        CityDeterminationStatus.THETA_CONTINGENT,
    }
)

_OUT_OF_SCOPE_STATUSES: Final[frozenset[CityDeterminationStatus]] = frozenset(
    {
        CityDeterminationStatus.OUT_OF_SCOPE_DOM_9,
    }
)

_RECOGNIZED_CITY_STATUSES: Final[frozenset[CityDeterminationStatus]] = frozenset(
    set(_PRIMARY_REJECTING_STATUSES)
    | set(_PRIMARY_NON_REJECTING_STATUSES)
    | set(_OUT_OF_SCOPE_STATUSES)
)


class ProgrammeInputError(Exception):
    """Base class for invalid programme rollup inputs."""


class InScopeCityMismatchError(ProgrammeInputError):
    """Raised when city-scoped inputs do not exactly match ``in_scope_cities``."""


class CityStatusRecognitionError(ProgrammeInputError):
    """Raised when a city determination carries an unrecognised status."""


@dataclass(frozen=True, slots=True, kw_only=True)
class CityProgrammeDetermination:
    """City determination after structural programme exclusions are applied."""

    city: str
    city_determination: CityDetermination
    scope: CityProgrammeScope
    position_taking: PositionTakingDisposition


@dataclass(frozen=True, slots=True, kw_only=True)
class ProgrammeDetermination:
    """Programme-level result with primary, secondary and excluded city slices."""

    determination: ProgrammeDeterminationStatus
    city_determinations: tuple[CityProgrammeDetermination, ...]
    primary_city_determinations: tuple[CityProgrammeDetermination, ...]
    secondary_city_determinations: tuple[CityProgrammeDetermination, ...]
    out_of_scope_city_determinations: tuple[CityProgrammeDetermination, ...]
    rejecting_primary_cities: tuple[str, ...]
    primary_no_go_count: int
    reason: str


def determine_programme(
    *,
    in_scope_cities: Iterable[str],
    city_cells: Mapping[str, Mapping[str, CellClassification]] | None = None,
    evaluations_elapsed_by_city: Mapping[str, int] | None = None,
    city_determinations: Mapping[str, CityDetermination] | None = None,
) -> ProgrammeDetermination:
    """Roll up city coverage determinations into the preregistered verdict.

    Pure: all city identities, classifications and expiry counts are explicit
    inputs. NYC is structurally secondary and DOM-9 out-of-scope cities are
    structurally excluded from the primary failure count.
    """
    in_scope = _sorted_unique(in_scope_cities, label="in_scope_cities")
    determinations = _resolve_city_determinations(
        in_scope,
        city_cells=city_cells,
        evaluations_elapsed_by_city=evaluations_elapsed_by_city,
        city_determinations=city_determinations,
    )

    scoped = tuple(
        CityProgrammeDetermination(
            city=city,
            city_determination=determination,
            scope=_scope_for(city, determination),
            position_taking=PositionTakingDisposition.NOT_TRADEABLE,
        )
        for city, determination in sorted(determinations.items())
    )
    primary = tuple(city for city in scoped if city.scope is CityProgrammeScope.PRIMARY)
    if not primary:
        raise ProgrammeInputError("programme rollup has no primary cities after exclusions")

    rejecting_primary_cities = tuple(
        city.city
        for city in primary
        if city.city_determination.determination in _PRIMARY_REJECTING_STATUSES
    )
    programme_status = _programme_status(primary, rejecting_primary_cities)
    final_scoped = tuple(
        _with_position_taking(city, programme_status=programme_status) for city in scoped
    )

    return ProgrammeDetermination(
        determination=programme_status,
        city_determinations=final_scoped,
        primary_city_determinations=tuple(
            city for city in final_scoped if city.scope is CityProgrammeScope.PRIMARY
        ),
        secondary_city_determinations=tuple(
            city for city in final_scoped if city.scope is CityProgrammeScope.SECONDARY_NYC
        ),
        out_of_scope_city_determinations=tuple(
            city for city in final_scoped if city.scope is CityProgrammeScope.OUT_OF_SCOPE_DOM_9
        ),
        rejecting_primary_cities=rejecting_primary_cities,
        primary_no_go_count=len(rejecting_primary_cities),
        reason=_reason(programme_status, rejecting_primary_cities),
    )


def _resolve_city_determinations(
    in_scope: tuple[str, ...],
    *,
    city_cells: Mapping[str, Mapping[str, CellClassification]] | None,
    evaluations_elapsed_by_city: Mapping[str, int] | None,
    city_determinations: Mapping[str, CityDetermination] | None,
) -> dict[str, CityDetermination]:
    if city_determinations is not None:
        if city_cells is not None or evaluations_elapsed_by_city is not None:
            raise ProgrammeInputError(
                "pass either city_determinations or city_cells plus evaluations_elapsed_by_city"
            )
        _assert_exact_city_set(
            in_scope,
            tuple(sorted(city_determinations)),
            label="city_determinations",
        )
        return {city: city_determinations[city] for city in in_scope}

    if city_cells is None or evaluations_elapsed_by_city is None:
        raise ProgrammeInputError(
            "city_cells and evaluations_elapsed_by_city are required together"
        )
    _assert_exact_city_set(in_scope, tuple(sorted(city_cells)), label="city_cells")
    _assert_exact_city_set(
        in_scope,
        tuple(sorted(evaluations_elapsed_by_city)),
        label="evaluations_elapsed_by_city",
    )

    resolved: dict[str, CityDetermination] = {}
    for city in in_scope:
        evaluations_elapsed = evaluations_elapsed_by_city[city]
        if evaluations_elapsed < 1:
            raise ProgrammeInputError(
                f"evaluations_elapsed_by_city[{city!r}] must be >= 1; got {evaluations_elapsed}"
            )
        determination = determine_city(city, city_cells[city])
        if determination.expiry_disposition is ExpiryDisposition.CLOCK_RUNS:
            determination = apply_expiry(
                determination,
                evaluations_elapsed=evaluations_elapsed,
            )
        resolved[city] = determination
    return resolved


def _scope_for(
    city: str,
    determination: CityDetermination,
) -> CityProgrammeScope:
    status = determination.determination
    _ensure_recognized(status, city=city)
    if city == NYC_SECONDARY_CITY:
        return CityProgrammeScope.SECONDARY_NYC
    if status in _OUT_OF_SCOPE_STATUSES:
        return CityProgrammeScope.OUT_OF_SCOPE_DOM_9
    return CityProgrammeScope.PRIMARY


def _programme_status(
    primary: tuple[CityProgrammeDetermination, ...],
    rejecting_primary_cities: tuple[str, ...],
) -> ProgrammeDeterminationStatus:
    if len(rejecting_primary_cities) >= PROGRAMME_NO_GO_THRESHOLD:
        return ProgrammeDeterminationStatus.PROGRAMME_REJECTED

    statuses = tuple(city.city_determination.determination for city in primary)
    if any(status is CityDeterminationStatus.NOT_YET_ANSWERABLE for status in statuses):
        return ProgrammeDeterminationStatus.PROGRAMME_NOT_YET_ANSWERABLE
    if any(status is CityDeterminationStatus.GO_PENDING_ESCALATION for status in statuses):
        return ProgrammeDeterminationStatus.PROGRAMME_NOT_YET_ANSWERABLE
    if any(status is CityDeterminationStatus.THETA_CONTINGENT for status in statuses):
        return ProgrammeDeterminationStatus.THETA_CONTINGENT
    if any(status in _PRIMARY_REJECTING_STATUSES for status in statuses):
        return ProgrammeDeterminationStatus.PROGRAMME_NOT_REJECTED
    return ProgrammeDeterminationStatus.PRIMARY_GO


def _with_position_taking(
    city: CityProgrammeDetermination,
    *,
    programme_status: ProgrammeDeterminationStatus,
) -> CityProgrammeDetermination:
    if programme_status is ProgrammeDeterminationStatus.PROGRAMME_REJECTED:
        position_taking = PositionTakingDisposition.HALT_NEW_POSITIONS_HOLD_OPEN_TO_SETTLEMENT
    elif city.scope is not CityProgrammeScope.PRIMARY:
        position_taking = PositionTakingDisposition.NOT_TRADEABLE
    elif city.city_determination.determination is CityDeterminationStatus.GO:
        position_taking = PositionTakingDisposition.MAY_OPEN_NEW_POSITIONS
    elif (
        city.city_determination.determination in _PRIMARY_NON_REJECTING_STATUSES
        or city.city_determination.determination in _PRIMARY_REJECTING_STATUSES
    ):
        position_taking = PositionTakingDisposition.NOT_TRADEABLE
    else:
        _ensure_recognized(city.city_determination.determination, city=city.city)
        raise AssertionError("unreachable city determination status")

    return CityProgrammeDetermination(
        city=city.city,
        city_determination=city.city_determination,
        scope=city.scope,
        position_taking=position_taking,
    )


def _ensure_recognized(status: object, *, city: str) -> None:
    if status not in _RECOGNIZED_CITY_STATUSES:
        raise CityStatusRecognitionError(
            f"city {city!r} has unrecognized determination status {_label(status)}"
        )


def _assert_exact_city_set(
    expected: tuple[str, ...],
    actual: tuple[str, ...],
    *,
    label: str,
) -> None:
    expected_set = frozenset(expected)
    actual_set = frozenset(actual)
    missing = tuple(sorted(expected_set - actual_set))
    unexpected = tuple(sorted(actual_set - expected_set))
    if missing or unexpected:
        raise InScopeCityMismatchError(
            f"{label} must exactly match in_scope_cities; "
            f"missing={missing!r}, unexpected={unexpected!r}"
        )


def _sorted_unique(cities: Iterable[str], *, label: str) -> tuple[str, ...]:
    result = tuple(sorted(cities))
    if len(result) != len(set(result)):
        raise InScopeCityMismatchError(f"{label} contains duplicate city identities")
    if not result:
        raise InScopeCityMismatchError(f"{label} must not be empty")
    return result


def _reason(
    programme_status: ProgrammeDeterminationStatus,
    rejecting_primary_cities: tuple[str, ...],
) -> str:
    if programme_status is ProgrammeDeterminationStatus.PROGRAMME_REJECTED:
        return (
            f"{len(rejecting_primary_cities)} primary cities are NO_GO "
            f"({', '.join(rejecting_primary_cities)}); rule 3 rejects the programme"
        )
    if programme_status is ProgrammeDeterminationStatus.PROGRAMME_NOT_YET_ANSWERABLE:
        return "fewer than two primary cities are NO_GO, but a primary verdict is pending"
    if programme_status is ProgrammeDeterminationStatus.THETA_CONTINGENT:
        return "all primary cities resolved, with at least one THETA_CONTINGENT city"
    if programme_status is ProgrammeDeterminationStatus.PROGRAMME_NOT_REJECTED:
        return "fewer than two primary cities are NO_GO, so rule 3 has not rejected"
    return "all primary cities are GO"


def _label(value: object) -> str:
    return getattr(value, "name", repr(value))
