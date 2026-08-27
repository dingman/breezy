"""The asymmetric settlement gate's minimum-coverage rule, as executable code.

The pre-registration (``docs/evidence/asymmetric_gate_prereg_2026-08-26.md``,
BINDING) pre-declares at its "Minimum coverage requirement [R2]":

    the ``[0,1)`` stratum must reach a verdict -- not UNDERPOWERED -- in every
    in-scope city ... A PASS carried entirely by wide-clearance strata is void.

The defect these tests close: ``STRUCTURALLY UNREACHABLE`` **is** a verdict, so
a rule phrased as "has not reached a verdict" never fires on it, and a city
whose boundary stratum is structurally unreachable would trade on its
wide-clearance strata alone -- precisely the PASS the pre-registration voids.

The four-city scenario in
:func:`test_the_four_unanswered_primary_cities_are_refused_and_nyc_is_secondary`
is the deliverable proving it is closed.
"""

from __future__ import annotations

import enum
from typing import cast

import pytest

from breezy.settlement import coverage
from breezy.settlement.coverage import (
    BOUNDARY_STRATUM,
    COVERAGE_SATISFYING,
    CellClassification,
    CityDetermination,
    CityDeterminationStatus,
    ExpiryDisposition,
    MissingBoundaryStratumError,
    UnresolvedCellClassificationError,
    apply_expiry,
    determine_city,
    satisfies_coverage,
)

C = CellClassification
D = CityDeterminationStatus

# The five clearance bands of prereg section 4, as this suite spells them.
WIDE_STRATA = ("[1,2)", "[2,3)", "[3,5)", "[5,inf)")


def _cells(boundary: CellClassification, wide: CellClassification = C.GO) -> dict[
    str, CellClassification
]:
    """A full city row: one boundary cell plus every wide-clearance cell."""
    row = {BOUNDARY_STRATUM: boundary}
    row.update({stratum: wide for stratum in WIDE_STRATA})
    return row


# ---------------------------------------------------------------------------
# 1. The classification set is the pre-registration's, not an invented one
# ---------------------------------------------------------------------------


def test_the_classification_set_is_exactly_the_pre_registered_seven() -> None:
    assert {member.name for member in CellClassification} == {
        "GO",
        "NO_GO",
        "OUT_OF_SCOPE_DOM_9",
        "THETA_CONTINGENT",
        "UNDERPOWERED",
        "PROVISIONAL_UNDERPOWERED",
        "STRUCTURALLY_UNREACHABLE",
        "NOT_YET_ANSWERABLE",
    }


def test_cell_classification_rejects_enum_aliases() -> None:
    """A duplicate enum value would hide a member from enum iteration."""
    assert len(CellClassification.__members__) == len(set(CellClassification.__members__.values()))


def test_gate_constants_are_declared_final() -> None:
    assert coverage.__annotations__["BOUNDARY_STRATUM"] == "Final[str]"
    assert coverage.__annotations__["COVERAGE_SATISFYING"] == (
        "Final[frozenset[CellClassification]]"
    )
    assert coverage.__annotations__["_ESCALATING"] == "Final[frozenset[CellClassification]]"


def test_motivating_figure_citations_use_the_architecture_doc() -> None:
    wrong_source = "settlement_alignment_" "diagnosis_2026-08-25.md"

    assert wrong_source not in (coverage.__doc__ or "")
    assert wrong_source not in (__doc__ or "")
    assert "docs/plans/TRADING_SYSTEM_ARCHITECTURE.md" in (coverage.__doc__ or "")


# ---------------------------------------------------------------------------
# 2. COVERAGE_SATISFYING is a closed set tested by positive membership
# ---------------------------------------------------------------------------


def test_coverage_satisfying_is_exactly_the_three_resolving_classifications() -> None:
    assert COVERAGE_SATISFYING == frozenset({C.GO, C.NO_GO, C.THETA_CONTINGENT})


@pytest.mark.parametrize("verdict", [C.GO, C.NO_GO, C.THETA_CONTINGENT])
def test_the_three_resolving_classifications_satisfy_coverage(
    verdict: CellClassification,
) -> None:
    assert satisfies_coverage(verdict) is True


@pytest.mark.parametrize(
    "verdict",
    [
        C.UNDERPOWERED,
        C.PROVISIONAL_UNDERPOWERED,
        C.STRUCTURALLY_UNREACHABLE,
        C.NOT_YET_ANSWERABLE,
        C.OUT_OF_SCOPE_DOM_9,
    ],
)
def test_the_five_non_resolving_classifications_do_not_satisfy_coverage(
    verdict: CellClassification,
) -> None:
    assert satisfies_coverage(verdict) is False


def test_every_classification_outside_the_closed_set_fails_coverage() -> None:
    """Adding a member to the enum without adding it here must fail loudly."""
    non_satisfying = {member for member in CellClassification if member not in COVERAGE_SATISFYING}

    assert non_satisfying == {
        C.UNDERPOWERED,
        C.PROVISIONAL_UNDERPOWERED,
        C.STRUCTURALLY_UNREACHABLE,
        C.NOT_YET_ANSWERABLE,
        C.OUT_OF_SCOPE_DOM_9,
    }


class _HypotheticalFutureClassification(enum.Enum):
    """Stands in for a classification a later revision might add."""

    NEEDS_ARCHIVE_REDERIVATION = "NEEDS_ARCHIVE_REDERIVATION"


def test_a_hypothetical_new_classification_does_not_satisfy_coverage() -> None:
    """The anti-negation guard.

    Implemented as ``verdict in COVERAGE_SATISFYING`` this is False.
    Implemented as ``verdict not in {UNDERPOWERED, ...}`` -- the forbidden
    negation form -- an unlisted newcomer silently satisfies coverage and this
    test goes RED. That is the mutation this test exists to catch.
    """
    newcomer = cast(
        CellClassification,
        _HypotheticalFutureClassification.NEEDS_ARCHIVE_REDERIVATION,
    )

    assert satisfies_coverage(newcomer) is False


def test_a_hypothetical_new_classification_cannot_make_a_city_tradeable() -> None:
    newcomer = cast(
        CellClassification,
        _HypotheticalFutureClassification.NEEDS_ARCHIVE_REDERIVATION,
    )

    result = determine_city("XXX", _cells(newcomer))

    assert result.tradeable is False
    assert result.determination is D.NOT_YET_ANSWERABLE


def test_a_hypothetical_new_wide_classification_blocks_the_city() -> None:
    """The anti-negation guard applies to every in-scope stratum, not just [0,1)."""
    newcomer = cast(
        CellClassification,
        _HypotheticalFutureClassification.NEEDS_ARCHIVE_REDERIVATION,
    )
    row = _cells(C.GO)
    row["[1,2)"] = newcomer

    result = determine_city("XXX", row)

    assert result.tradeable is False
    assert result.determination is D.NOT_YET_ANSWERABLE
    assert result.blocking_cells == ("[1,2)",)


# ---------------------------------------------------------------------------
# 3. A missing boundary cell fails loudly -- absence never reads as satisfied
# ---------------------------------------------------------------------------


def test_a_missing_boundary_cell_raises_rather_than_defaulting() -> None:
    wide_only = {stratum: C.GO for stratum in WIDE_STRATA}

    with pytest.raises(MissingBoundaryStratumError) as excinfo:
        determine_city("NYC", wide_only)

    assert BOUNDARY_STRATUM in str(excinfo.value)
    assert "NYC" in str(excinfo.value)
    assert not isinstance(excinfo.value, KeyError)


def test_an_entirely_empty_cell_map_raises() -> None:
    with pytest.raises(MissingBoundaryStratumError):
        determine_city("NYC", {})


def test_boundary_stratum_is_not_caller_configurable() -> None:
    row = {"[0,1)": C.UNDERPOWERED, "[5,inf)": C.GO}

    with pytest.raises(TypeError):
        determine_city("LAX", row, boundary_stratum="[5,inf)")  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# 4. City determination
# ---------------------------------------------------------------------------


def test_a_city_whose_boundary_stratum_clears_is_tradeable() -> None:
    result = determine_city("NYC", _cells(C.GO))

    assert result.determination is D.GO
    assert result.tradeable is True
    assert result.boundary_classification is C.GO
    assert result.escalation_required is False
    assert result.expiry_disposition is ExpiryDisposition.NOT_APPLICABLE


def test_structurally_unreachable_at_the_boundary_voids_the_city() -> None:
    """STRUCTURALLY_UNREACHABLE is pre-resolution, not a final input."""
    with pytest.raises(UnresolvedCellClassificationError):
        determine_city("LAX", _cells(C.STRUCTURALLY_UNREACHABLE))


@pytest.mark.parametrize(
    "boundary",
    [
        C.UNDERPOWERED,
        C.NOT_YET_ANSWERABLE,
    ],
)
def test_every_non_resolving_boundary_classification_voids_the_city(
    boundary: CellClassification,
) -> None:
    result = determine_city("LAX", _cells(boundary))

    assert result.tradeable is False
    assert result.determination is D.NOT_YET_ANSWERABLE
    assert result.boundary_classification is boundary


@pytest.mark.parametrize(
    "unresolved",
    [
        C.PROVISIONAL_UNDERPOWERED,
        C.STRUCTURALLY_UNREACHABLE,
    ],
)
def test_unresolved_boundary_classifications_are_refused(unresolved: CellClassification) -> None:
    with pytest.raises(UnresolvedCellClassificationError) as excinfo:
        determine_city("A", _cells(unresolved))

    assert BOUNDARY_STRATUM in str(excinfo.value)


@pytest.mark.parametrize(
    "unresolved",
    [
        C.PROVISIONAL_UNDERPOWERED,
        C.STRUCTURALLY_UNREACHABLE,
    ],
)
def test_unresolved_wide_classifications_are_refused(unresolved: CellClassification) -> None:
    row = _cells(C.GO)
    row["[5,inf)"] = unresolved

    with pytest.raises(UnresolvedCellClassificationError) as excinfo:
        determine_city("A", row)

    assert "[5,inf)" in str(excinfo.value)


def test_the_42_day_expiry_disposition_runs_only_on_timed_states() -> None:
    assert determine_city("A", _cells(C.UNDERPOWERED)).expiry_disposition is (
        ExpiryDisposition.CLOCK_RUNS
    )
    assert determine_city("A", _cells(C.NOT_YET_ANSWERABLE)).expiry_disposition is (
        ExpiryDisposition.CLOCK_RUNS
    )
    assert determine_city("A", _cells(C.GO)).expiry_disposition is (
        ExpiryDisposition.NOT_APPLICABLE
    )


def test_the_two_expiry_exempt_states_demand_escalation_instead() -> None:
    """They do not silently become city determinations while escalation is pending."""
    with pytest.raises(UnresolvedCellClassificationError):
        determine_city("A", _cells(C.STRUCTURALLY_UNREACHABLE))
    with pytest.raises(UnresolvedCellClassificationError):
        determine_city("A", _cells(C.PROVISIONAL_UNDERPOWERED))
    assert determine_city("A", _cells(C.UNDERPOWERED)).escalation_required is False


def test_escalation_is_demanded_by_a_wide_stratum_too_and_refuses_determination() -> None:
    row = _cells(C.GO)
    row["[5,inf)"] = C.STRUCTURALLY_UNREACHABLE

    with pytest.raises(UnresolvedCellClassificationError):
        determine_city("A", row)


def test_a_no_go_at_any_stratum_falsifies_the_city() -> None:
    row = _cells(C.GO)
    row["[2,3)"] = C.NO_GO

    result = determine_city("A", row)

    assert result.determination is D.NO_GO
    assert result.tradeable is False
    assert result.blocking_cells == ("[2,3)",)


def test_a_no_go_at_the_boundary_is_a_no_go_not_a_void() -> None:
    """NO_GO satisfies coverage: the boundary condition WAS evaluated."""
    result = determine_city("A", _cells(C.NO_GO))

    assert result.determination is D.NO_GO
    assert result.tradeable is False


def test_theta_contingent_satisfies_coverage_but_does_not_authorise_trading() -> None:
    """Conditional on G-15 fee discovery, which this pure function cannot see."""
    result = determine_city("A", _cells(C.THETA_CONTINGENT))

    assert satisfies_coverage(C.THETA_CONTINGENT) is True
    assert result.determination is D.THETA_CONTINGENT
    assert result.tradeable is False


def test_no_go_takes_precedence_over_theta_contingent() -> None:
    row = _cells(C.GO)
    row["[1,2)"] = C.THETA_CONTINGENT
    row["[2,3)"] = C.NO_GO

    result = determine_city("A", row)

    assert result.determination is D.NO_GO
    assert result.blocking_cells == ("[1,2)", "[2,3)")


def test_underpowered_wide_strata_do_not_block_a_cleared_boundary() -> None:
    """Prereg: strata below their floor "contribute to no verdict"."""
    row = _cells(C.GO, wide=C.UNDERPOWERED)

    result = determine_city("A", row)

    assert result.determination is D.GO
    assert result.tradeable is True


def test_existing_not_yet_answerable_wide_stratum_blocks_the_city() -> None:
    row = _cells(C.GO)
    row["[1,2)"] = C.NOT_YET_ANSWERABLE

    result = determine_city("A", row)

    assert result.determination is D.NOT_YET_ANSWERABLE
    assert result.tradeable is False
    assert result.blocking_cells == ("[1,2)",)


def test_blocking_cells_are_sorted_not_mapping_ordered() -> None:
    first = {
        BOUNDARY_STRATUM: C.GO,
        "[2,3)": C.NO_GO,
        "[1,2)": C.THETA_CONTINGENT,
    }
    second = {
        BOUNDARY_STRATUM: C.GO,
        "[1,2)": C.THETA_CONTINGENT,
        "[2,3)": C.NO_GO,
    }

    assert determine_city("A", first) == determine_city("A", second)
    assert determine_city("A", first).blocking_cells == ("[1,2)", "[2,3)")


def test_city_determination_is_keyword_only() -> None:
    with pytest.raises(TypeError):
        CityDetermination(  # type: ignore[call-arg]
            "A",
            D.GO,
            True,
            C.GO,
            (),
            ExpiryDisposition.NOT_APPLICABLE,
            False,
            "ok",
        )


def test_go_determination_is_sufficient_as_a_trading_predicate() -> None:
    result = determine_city("A", _cells(C.GO))

    assert result.determination is D.GO
    assert result.tradeable is True
    assert CityDeterminationStatus.__members__["GO_PENDING_ESCALATION"] is not D.GO


def test_apply_expiry_refuses_non_clock_determinations() -> None:
    with pytest.raises(ValueError):
        apply_expiry(determine_city("A", _cells(C.GO)), evaluations_elapsed=3)


def test_apply_expiry_converts_clocked_not_yet_answerable_on_third_evaluation() -> None:
    result = determine_city("A", _cells(C.UNDERPOWERED))

    expired = apply_expiry(result, evaluations_elapsed=3)

    assert expired.determination is D.NO_GO
    assert expired.tradeable is False
    assert expired.expiry_disposition is ExpiryDisposition.NOT_APPLICABLE
    assert expired.blocking_cells == (BOUNDARY_STRATUM,)


def test_apply_expiry_leaves_clocked_not_yet_answerable_before_third_evaluation() -> None:
    result = determine_city("A", _cells(C.UNDERPOWERED))

    assert apply_expiry(result, evaluations_elapsed=2) == result


# ---------------------------------------------------------------------------
# 5. THE DELIVERABLE -- the exact four-city scenario is refused
# ---------------------------------------------------------------------------


def test_the_four_unanswered_primary_cities_are_refused_and_nyc_is_secondary() -> None:
    """LAX, MDW, MIA and SFO are refused despite every wide stratum clearing.

    Motivating figures (``docs/plans/TRADING_SYSTEM_ARCHITECTURE.md:537-540``
    and ``:885-889``, break-even 0.981176 at p=0.98, theta=0.06): those four
    cities' ``[0,1)`` Wilson lower bounds are 0.7935 / 0.7800 / 0.8334 /
    0.7917 -- structurally unreachable -- while their ``>0.5F`` bounds all
    clear at 0.996+.

    CAVEAT, carried deliberately: that table is stratified by distance from the
    day's FINAL METAR max, a hindsight quantity the pre-registration forbids as
    a gating input at [R7]. It is motivation for this test's shape, and is
    NEVER consumed as a gating input by any code under test.
    """
    primary_cities = ("LAX", "MDW", "MIA", "SFO")

    results = {
        city: determine_city(city, _cells(C.UNDERPOWERED))
        for city in primary_cities
    }
    secondary_nyc = determine_city("NYC", _cells(C.GO))

    for city in primary_cities:
        assert results[city].tradeable is False, f"{city} must not trade"
        assert results[city].determination is D.NOT_YET_ANSWERABLE
        assert results[city].escalation_required is False
        assert results[city].expiry_disposition is ExpiryDisposition.CLOCK_RUNS

    assert secondary_nyc.tradeable is True
    assert secondary_nyc.determination is D.GO
    assert "NYC" not in results

    tradeable = {city for city, r in results.items() if r.tradeable}
    assert tradeable == set()


def test_the_refusal_survives_every_wide_stratum_clearing_at_theta_contingent() -> None:
    """No combination of wide-clearance results rescues a void boundary."""
    for wide in (C.GO, C.THETA_CONTINGENT):
        result = determine_city("SFO", _cells(C.UNDERPOWERED, wide=wide))
        assert result.tradeable is False


# ---------------------------------------------------------------------------
# 6. Purity
# ---------------------------------------------------------------------------


def test_determine_city_does_not_mutate_its_input() -> None:
    row = _cells(C.UNDERPOWERED)
    before = dict(row)

    determine_city("SFO", row)

    assert row == before


def test_repeated_calls_are_identical() -> None:
    row = _cells(C.GO)

    assert determine_city("NYC", row) == determine_city("NYC", row)
