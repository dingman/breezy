"""Programme-level rollup for the asymmetric settlement gate."""

from __future__ import annotations

import enum
from typing import cast

import pytest

from breezy.settlement.coverage import BOUNDARY_STRATUM, CellClassification
from breezy.settlement.programme import (
    CityProgrammeDetermination,
    CityProgrammeScope,
    CityStatusRecognitionError,
    InScopeCityMismatchError,
    PositionTakingDisposition,
    ProgrammeDeterminationStatus,
    determine_programme,
)

C = CellClassification
P = ProgrammeDeterminationStatus
A = PositionTakingDisposition
S = CityProgrammeScope

PRIMARY_CITIES = frozenset({"LAX", "MDW", "MIA", "SFO"})
ALL_CITIES = PRIMARY_CITIES | {"NYC"}
WIDE_STRATA = ("[1,2)", "[2,3)", "[3,5)", "[5,inf)")


def _cells(boundary: CellClassification, wide: CellClassification = C.GO) -> dict[
    str, CellClassification
]:
    row = {BOUNDARY_STRATUM: boundary}
    row.update({stratum: wide for stratum in WIDE_STRATA})
    return row


def _all_go_cells() -> dict[str, dict[str, CellClassification]]:
    return {city: _cells(C.GO) for city in ALL_CITIES}


def _evaluation_counts(value: int = 1) -> dict[str, int]:
    return {city: value for city in ALL_CITIES}


def _city_action(
    result_city_actions: tuple[CityProgrammeDetermination, ...],
    city: str,
) -> PositionTakingDisposition:
    for result in result_city_actions:
        if result.city == city:
            return result.position_taking
    raise AssertionError(f"missing city action for {city}")


def test_two_primary_no_gos_reject_the_formulation_programme_wide() -> None:
    cells = _all_go_cells()
    cells["LAX"] = _cells(C.NO_GO)
    cells["SFO"] = _cells(C.NO_GO)
    cells["MIA"] = _cells(C.UNDERPOWERED)

    result = determine_programme(
        in_scope_cities=ALL_CITIES,
        city_cells=cells,
        evaluations_elapsed_by_city=_evaluation_counts(),
    )

    assert result.determination is P.PROGRAMME_REJECTED
    assert result.rejecting_primary_cities == ("LAX", "SFO")
    assert result.primary_no_go_count == 2


def test_expiry_converted_no_go_counts_toward_programme_rejection() -> None:
    cells = _all_go_cells()
    cells["LAX"] = _cells(C.NO_GO)
    cells["SFO"] = _cells(C.UNDERPOWERED)
    counts = _evaluation_counts()
    counts["SFO"] = 3

    result = determine_programme(
        in_scope_cities=ALL_CITIES,
        city_cells=cells,
        evaluations_elapsed_by_city=counts,
    )

    assert result.determination is P.PROGRAMME_REJECTED
    assert result.rejecting_primary_cities == ("LAX", "SFO")


def test_programme_rejection_halts_new_positions_in_every_city_including_live_go() -> None:
    cells = _all_go_cells()
    cells["LAX"] = _cells(C.NO_GO)
    cells["SFO"] = _cells(C.NO_GO)

    result = determine_programme(
        in_scope_cities=ALL_CITIES,
        city_cells=cells,
        evaluations_elapsed_by_city=_evaluation_counts(),
    )

    assert _city_action(result.city_determinations, "MDW") is (
        A.HALT_NEW_POSITIONS_HOLD_OPEN_TO_SETTLEMENT
    )
    assert _city_action(result.city_determinations, "MIA") is (
        A.HALT_NEW_POSITIONS_HOLD_OPEN_TO_SETTLEMENT
    )
    assert {city.position_taking for city in result.city_determinations} == {
        A.HALT_NEW_POSITIONS_HOLD_OPEN_TO_SETTLEMENT
    }


def test_live_primary_go_city_may_take_positions_before_programme_rejection() -> None:
    cells = _all_go_cells()
    cells["LAX"] = _cells(C.NO_GO)

    result = determine_programme(
        in_scope_cities=ALL_CITIES,
        city_cells=cells,
        evaluations_elapsed_by_city=_evaluation_counts(),
    )

    assert result.determination is P.PROGRAMME_NOT_REJECTED
    assert _city_action(result.city_determinations, "MDW") is A.MAY_OPEN_NEW_POSITIONS


def test_nyc_is_secondary_and_excluded_from_the_primary_no_go_tally() -> None:
    cells = _all_go_cells()
    cells["LAX"] = _cells(C.NO_GO)
    cells["NYC"] = _cells(C.NO_GO)

    result = determine_programme(
        in_scope_cities=ALL_CITIES,
        city_cells=cells,
        evaluations_elapsed_by_city=_evaluation_counts(),
    )

    assert result.determination is P.PROGRAMME_NOT_REJECTED
    assert result.primary_no_go_count == 1
    assert result.rejecting_primary_cities == ("LAX",)
    assert tuple(city.city for city in result.primary_city_determinations) == (
        "LAX",
        "MDW",
        "MIA",
        "SFO",
    )
    assert tuple(city.city for city in result.secondary_city_determinations) == ("NYC",)
    assert result.secondary_city_determinations[0].scope is S.SECONDARY_NYC
    assert result.secondary_city_determinations[0].position_taking is A.NOT_TRADEABLE


def test_nyc_is_never_a_primary_tradeable_city_even_when_its_cell_is_go() -> None:
    result = determine_programme(
        in_scope_cities=ALL_CITIES,
        city_cells=_all_go_cells(),
        evaluations_elapsed_by_city=_evaluation_counts(),
    )

    assert result.determination is P.PRIMARY_GO
    assert "NYC" not in {city.city for city in result.primary_city_determinations}
    assert result.secondary_city_determinations[0].position_taking is A.NOT_TRADEABLE


def test_out_of_scope_dom_9_city_is_excluded_from_failure_count() -> None:
    cells = _all_go_cells()
    cells["LAX"] = _cells(C.NO_GO)
    cells["SFO"] = _cells(C.OUT_OF_SCOPE_DOM_9)

    result = determine_programme(
        in_scope_cities=ALL_CITIES,
        city_cells=cells,
        evaluations_elapsed_by_city=_evaluation_counts(),
    )

    assert result.determination is P.PROGRAMME_NOT_REJECTED
    assert result.primary_no_go_count == 1
    assert result.rejecting_primary_cities == ("LAX",)
    assert tuple(city.city for city in result.out_of_scope_city_determinations) == ("SFO",)
    assert _city_action(result.city_determinations, "SFO") is A.NOT_TRADEABLE


def test_dom_9_out_of_scope_at_a_wide_stratum_excludes_the_city_too() -> None:
    cells = _all_go_cells()
    cells["SFO"]["[5,inf)"] = C.OUT_OF_SCOPE_DOM_9

    result = determine_programme(
        in_scope_cities=ALL_CITIES,
        city_cells=cells,
        evaluations_elapsed_by_city=_evaluation_counts(),
    )

    assert tuple(city.city for city in result.out_of_scope_city_determinations) == ("SFO",)
    assert "SFO" not in {city.city for city in result.primary_city_determinations}


class _FutureCityStatus(enum.Enum):
    PAUSED_FOR_ARCHIVE_REDERIVATION = "PAUSED_FOR_ARCHIVE_REDERIVATION"


def test_an_unlisted_city_status_fails_closed_in_the_primary_rollup() -> None:
    cells = _all_go_cells()
    result = determine_programme(
        in_scope_cities=ALL_CITIES,
        city_cells=cells,
        evaluations_elapsed_by_city=_evaluation_counts(),
    )
    mutated = result.primary_city_determinations[0].city_determination
    foreign_status = cast(object, _FutureCityStatus.PAUSED_FOR_ARCHIVE_REDERIVATION)
    object.__setattr__(mutated, "determination", foreign_status)

    with pytest.raises(CityStatusRecognitionError):
        determinations = {
            city.city: city.city_determination for city in result.city_determinations
        }
        determine_programme(
            in_scope_cities=ALL_CITIES,
            city_determinations=determinations,
        )


class _HypotheticalFutureClassification(enum.Enum):
    NEEDS_ARCHIVE_REDERIVATION = "NEEDS_ARCHIVE_REDERIVATION"


def test_hypothetical_new_classification_cannot_make_a_programme_city_tradeable() -> None:
    newcomer = cast(
        CellClassification,
        _HypotheticalFutureClassification.NEEDS_ARCHIVE_REDERIVATION,
    )
    cells = _all_go_cells()
    cells["SFO"] = _cells(newcomer)

    result = determine_programme(
        in_scope_cities=ALL_CITIES,
        city_cells=cells,
        evaluations_elapsed_by_city=_evaluation_counts(),
    )

    assert _city_action(result.city_determinations, "SFO") is A.NOT_TRADEABLE
    assert result.determination is P.PROGRAMME_NOT_YET_ANSWERABLE


def test_city_cells_must_match_the_explicit_in_scope_city_set() -> None:
    cells = _all_go_cells()
    cells["BOS"] = _cells(C.GO)

    with pytest.raises(InScopeCityMismatchError) as excinfo:
        determine_programme(
            in_scope_cities=ALL_CITIES,
            city_cells=cells,
            evaluations_elapsed_by_city={**_evaluation_counts(), "BOS": 1},
        )

    assert "unexpected" in str(excinfo.value)
    assert "BOS" in str(excinfo.value)


def test_missing_city_cell_data_raises_instead_of_reading_as_satisfaction() -> None:
    cells = _all_go_cells()
    del cells["SFO"]

    with pytest.raises(InScopeCityMismatchError) as excinfo:
        counts = {
            city: count for city, count in _evaluation_counts().items() if city != "SFO"
        }
        determine_programme(
            in_scope_cities=ALL_CITIES,
            city_cells=cells,
            evaluations_elapsed_by_city=counts,
        )

    assert "missing" in str(excinfo.value)
    assert "SFO" in str(excinfo.value)


def test_evaluation_counts_must_match_the_explicit_in_scope_city_set() -> None:
    counts = _evaluation_counts()
    del counts["SFO"]

    with pytest.raises(InScopeCityMismatchError) as excinfo:
        determine_programme(
            in_scope_cities=ALL_CITIES,
            city_cells=_all_go_cells(),
            evaluations_elapsed_by_city=counts,
        )

    assert "evaluations_elapsed_by_city" in str(excinfo.value)
    assert "SFO" in str(excinfo.value)
