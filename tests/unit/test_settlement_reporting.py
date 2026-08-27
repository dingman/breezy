"""Settlement programme reporting invariants."""

from __future__ import annotations

import inspect
import re
from dataclasses import replace

import pytest

from breezy.settlement.coverage import BOUNDARY_STRATUM, CellClassification
from breezy.settlement.programme import (
    ProgrammeDetermination,
    ProgrammeDeterminationStatus,
    determine_programme,
)
from breezy.settlement.reporting import (
    CityEvidence,
    CityEvidenceTable,
    EvaluationIndexMismatchError,
    FigureAvailability,
    FigureProvenance,
    IncoherentFigureError,
    MdwAnnotation,
    MdwFigureUnavailableForPassError,
    MdwHeadlineOmissionError,
    PowerFloor,
    PowerFloorStatus,
    ProgrammeHeadline,
    ProgrammeReport,
    ReportStamp,
    SignedErrorDirection,
    Stratum,
    StratumFigure,
    UnevaluatedReason,
    build_programme_report,
    render_markdown,
)

C = CellClassification
P = ProgrammeDeterminationStatus

PRIMARY_CITIES = frozenset({"LAX", "MDW", "MIA", "SFO"})
ALL_CITIES = PRIMARY_CITIES | {"NYC"}
WIDE_STRATA = ("[1,2)", "[2,3)", "[3,5)", "[5,inf)")


def _cells(boundary: CellClassification, wide: CellClassification = C.GO) -> dict[
    str, CellClassification
]:
    row = {BOUNDARY_STRATUM: boundary}
    row.update({stratum: wide for stratum in WIDE_STRATA})
    return row


def _programme(
    *,
    mdw: CellClassification = C.NO_GO,
    lax: CellClassification = C.GO,
    mia: CellClassification = C.GO,
    sfo: CellClassification = C.GO,
    nyc: CellClassification = C.GO,
    evaluations: int = 1,
) -> ProgrammeDetermination:
    cells = {
        "LAX": _cells(lax),
        "MDW": _cells(mdw),
        "MIA": _cells(mia),
        "NYC": _cells(nyc),
        "SFO": _cells(sfo),
    }
    return determine_programme(
        in_scope_cities=ALL_CITIES,
        city_cells=cells,
        evaluations_elapsed_by_city={city: evaluations for city in ALL_CITIES},
    )


def _power_floor() -> PowerFloor:
    return PowerFloor(floor_n=200, anchor="0.9800", met=PowerFloorStatus.MET)


def _figure(
    stratum: Stratum,
    availability: FigureAvailability = FigureAvailability.REPORTED,
    *,
    cases: int | None = 240,
    agreements: int | None = 238,
    wilson_lower: str | None = "0.9710",
    break_even: str | None = "0.981176",
    direction: SignedErrorDirection = SignedErrorDirection.METAR_ABOVE_CLI,
    provenance: FigureProvenance = FigureProvenance.HINDSIGHT_STRATIFIED_BY_FINAL_METAR_MAX,
    note: str = "fixture",
) -> StratumFigure:
    if availability is not FigureAvailability.REPORTED:
        wilson_lower = None
        break_even = None
    if availability is FigureAvailability.NOT_DERIVED:
        cases = None
        agreements = None
        direction = SignedErrorDirection.NOT_DERIVED
    return StratumFigure(
        stratum=stratum,
        availability=availability,
        provenance=provenance,
        cases=cases,
        agreements=agreements,
        wilson_lower=wilson_lower,
        break_even=break_even,
        signed_error_direction=direction,
        mean_signed_error="0.14" if direction is not SignedErrorDirection.NOT_DERIVED else None,
        power_floor=_power_floor(),
        note=note,
    )


def _figures(
    availability: FigureAvailability = FigureAvailability.REPORTED,
) -> dict[Stratum, StratumFigure]:
    return {stratum: _figure(stratum, availability) for stratum in Stratum}


def _evidence(
    programme: ProgrammeDetermination,
    *,
    mdw_boundary_availability: FigureAvailability = FigureAvailability.REPORTED,
    evaluation_index: int = 1,
) -> CityEvidenceTable:
    entries: list[CityEvidence] = []
    for city in programme.city_determinations:
        figures = _figures()
        if city.city == "MDW":
            figures[Stratum.BOUNDARY_0_1] = _figure(
                Stratum.BOUNDARY_0_1,
                mdw_boundary_availability,
                cases=37,
                agreements=30,
                wilson_lower="0.7800",
                break_even="0.981176",
                direction=SignedErrorDirection.METAR_BELOW_CLI,
                note="MDW boundary fixture",
            )
        entries.append(
            CityEvidence(
                city=city.city,
                figures=figures,
                evaluation_index=evaluation_index,
                tape_window="2020-01-01..2026-08-26",
            )
        )
    return CityEvidenceTable(entries=tuple(entries), evaluation_index=evaluation_index)


def _stamp() -> ReportStamp:
    return ReportStamp(
        generated_at_utc="2026-08-27T00:00:00Z",
        cells_sha256="c" * 64,
        evidence_sha256="e" * 64,
        command="pytest fixture",
    )


def _report(
    programme: ProgrammeDetermination | None = None,
    *,
    mdw_boundary_availability: FigureAvailability = FigureAvailability.REPORTED,
) -> ProgrammeReport:
    programme = programme or _programme()
    return build_programme_report(
        programme,
        _evidence(programme, mdw_boundary_availability=mdw_boundary_availability),
        stamp=_stamp(),
    )


def test_stratum_enum_boundary_value_matches_coverage_boundary_stratum() -> None:
    assert Stratum.BOUNDARY_0_1.value == BOUNDARY_STRATUM
    assert {stratum.value for stratum in Stratum} == {
        "[0,1)",
        "[1,2)",
        "[2,3)",
        "[3,5)",
        "[5,inf)",
    }


def test_city_evidence_requires_every_pre_registered_stratum() -> None:
    figures = _figures()
    del figures[Stratum.CLEAR_1_2]

    with pytest.raises(Exception, match=r"\[1,2\)"):
        CityEvidence(city="MDW", figures=figures, evaluation_index=1, tape_window="x")


def test_join_rejects_a_city_missing_the_1_2_stratum() -> None:
    programme = _programme()
    entries = list(_evidence(programme).entries)
    figures = dict(entries[0].figures)
    del figures[Stratum.CLEAR_1_2]

    with pytest.raises(Exception, match=r"\[1,2\)"):
        entries[0] = replace(entries[0], figures=figures)


def test_join_rejects_mismatched_evaluation_index() -> None:
    programme = _programme()
    entries = list(_evidence(programme).entries)
    entries[0] = replace(entries[0], evaluation_index=2)

    with pytest.raises(EvaluationIndexMismatchError):
        CityEvidenceTable(entries=tuple(entries), evaluation_index=1)


def test_figure_numerics_iff_availability() -> None:
    with pytest.raises(IncoherentFigureError):
        StratumFigure(
            stratum=Stratum.BOUNDARY_0_1,
            availability=FigureAvailability.REPORTED,
            cases=10,
            agreements=9,
            wilson_lower=None,
            break_even="0.981176",
            signed_error_direction=SignedErrorDirection.METAR_ABOVE_CLI,
            mean_signed_error="0.1",
            power_floor=_power_floor(),
            note="bad",
        )

    with pytest.raises(IncoherentFigureError):
        StratumFigure(
            stratum=Stratum.BOUNDARY_0_1,
            availability=FigureAvailability.UNDERPOWERED,
            cases=10,
            agreements=9,
            wilson_lower="0.7",
            break_even=None,
            signed_error_direction=SignedErrorDirection.METAR_ABOVE_CLI,
            mean_signed_error="0.1",
            power_floor=_power_floor(),
            note="bad",
        )

    with pytest.raises(IncoherentFigureError):
        StratumFigure(
            stratum=Stratum.BOUNDARY_0_1,
            availability=FigureAvailability.NOT_DERIVED,
            cases=10,
            agreements=None,
            wilson_lower=None,
            break_even=None,
            signed_error_direction=SignedErrorDirection.NOT_DERIVED,
            mean_signed_error=None,
            power_floor=_power_floor(),
            note="bad",
        )


def test_figure_provenance_defaults_to_hindsight() -> None:
    assert _figure(Stratum.BOUNDARY_0_1).provenance is (
        FigureProvenance.HINDSIGHT_STRATIFIED_BY_FINAL_METAR_MAX
    )


def test_headline_cannot_be_built_without_mdw() -> None:
    programme = _programme(mdw=C.OUT_OF_SCOPE_DOM_9)
    evidence = _evidence(programme)
    no_mdw_entries = tuple(entry for entry in evidence.entries if entry.city != "MDW")

    with pytest.raises(Exception, match="MDW"):
        build_programme_report(
            programme,
            CityEvidenceTable(entries=no_mdw_entries, evaluation_index=1),
            stamp=_stamp(),
        )


def test_headline_rejects_a_fabricated_mdw_line_not_present_in_the_body() -> None:
    report = _report()
    fabricated = replace(report.headline.mdw_line)

    with pytest.raises(MdwHeadlineOmissionError):
        ProgrammeHeadline(
            determination=report.headline.determination,
            primary_lines=report.headline.primary_lines,
            mdw_line=fabricated,
            mdw_annotation=report.headline.mdw_annotation,
            unevaluated=report.headline.unevaluated,
            reason=report.headline.reason,
        )


def test_primary_go_requires_mdw_boundary_figure_reported() -> None:
    programme = _programme(mdw=C.GO)

    with pytest.raises(MdwFigureUnavailableForPassError):
        _report(programme, mdw_boundary_availability=FigureAvailability.NOT_DERIVED)


@pytest.mark.parametrize(
    ("programme", "needle"),
    [
        (_programme(mdw=C.GO), "0.7800"),
        (_programme(mdw=C.NO_GO), "0.7800"),
        (_programme(mdw=C.THETA_CONTINGENT), "0.7800"),
        (_programme(mdw=C.UNDERPOWERED), "37"),
        (_programme(mdw=C.NO_GO, lax=C.NO_GO), "HALT_NEW_POSITIONS_HOLD_OPEN_TO_SETTLEMENT"),
    ],
)
def test_render_states_mdw_figure_values_for_every_programme_status(
    programme: ProgrammeDetermination,
    needle: str,
) -> None:
    report = _report(
        programme,
        mdw_boundary_availability=(
            FigureAvailability.UNDERPOWERED
            if programme.determination is P.PROGRAMME_NOT_YET_ANSWERABLE
            else FigureAvailability.REPORTED
        ),
    )

    rendered = render_markdown(report)

    assert "MDW" in rendered
    assert "0.981176" in rendered or "UNDERPOWERED" in rendered
    assert "METAR_BELOW_CLI" in rendered or "NOT_DERIVED" in rendered
    assert "Power floor: MET" in rendered
    assert needle in rendered


def test_mdw_pass_renders_the_contrary_to_prediction_annotation_and_explanation_block() -> None:
    rendered = render_markdown(_report(_programme(mdw=C.GO)))

    assert MdwAnnotation.PASSED_CONTRARY_TO_PRE_DECLARED_PREDICTION.value in rendered
    assert "explanation required before any GO" in rendered


def test_mdw_out_of_scope_dom_9_renders_the_exclusion_not_an_error() -> None:
    rendered = render_markdown(_report(_programme(mdw=C.OUT_OF_SCOPE_DOM_9)))

    assert "MDW" in rendered
    assert "EXCLUDED_OUT_OF_SCOPE_DOM_9" in rendered
    assert "PRIMARY CITIES: LAX, MIA, SFO" in rendered


def test_ledger_reports_a_gap_for_a_stratum_that_was_never_derived() -> None:
    programme = _programme()
    evidence = _evidence(programme)
    entries = list(evidence.entries)
    mdw = next(entry for entry in entries if entry.city == "MDW")
    figures = dict(mdw.figures)
    figures[Stratum.CLEAR_1_2] = _figure(
        Stratum.CLEAR_1_2,
        FigureAvailability.NOT_DERIVED,
        note="not run",
    )
    entries[entries.index(mdw)] = replace(mdw, figures=figures)
    report = build_programme_report(
        programme,
        CityEvidenceTable(entries=tuple(entries), evaluation_index=1),
        stamp=_stamp(),
    )

    assert any(
        entry.reason is UnevaluatedReason.STRATUM_FIGURE_NOT_DERIVED
        and entry.city == "MDW"
        and entry.stratum is Stratum.CLEAR_1_2
        for entry in report.headline.unevaluated.evaluation_gaps
    )
    assert "MDW [1,2) STRATUM_FIGURE_NOT_DERIVED" in render_markdown(report)


def test_underpowered_boundary_retains_its_case_count() -> None:
    report = _report(
        _programme(mdw=C.UNDERPOWERED),
        mdw_boundary_availability=FigureAvailability.UNDERPOWERED,
    )

    rendered = render_markdown(report)

    assert "MDW [0,1) BOUNDARY_UNDERPOWERED" in rendered
    assert "cases=37" in rendered


def test_structurally_unreachable_renders_as_a_finding_not_a_gap() -> None:
    programme = _programme()
    report = _report(
        programme,
        mdw_boundary_availability=FigureAvailability.STRUCTURALLY_UNREACHABLE,
    )

    rendered = render_markdown(report)

    assert "BOUNDARY_STRUCTURALLY_UNREACHABLE" in rendered
    assert "FINDING" in rendered


def test_verdict_blocked_pending_review_renders_in_place_of_a_verdict() -> None:
    programme = _programme()
    report = _report(
        programme,
        mdw_boundary_availability=FigureAvailability.PROVISIONAL_UNDERPOWERED,
    )

    rendered = render_markdown(report)

    assert "VERDICT BLOCKED PENDING ADVERSARIAL RE-REVIEW" in rendered
    assert "VERDICT_BLOCKED_PENDING_REVIEW" in rendered


def test_render_renders_the_primary_section_from_headline_lines() -> None:
    report = _report()
    body = render_markdown(report)
    primary_section = body.split("## PRIMARY CITY DETAIL")[1].split("## SECONDARY (NYC)")[0]

    assert "MDW" in primary_section
    assert "NYC" not in primary_section


def test_report_rejects_a_headline_whose_lines_disagree_with_the_determination() -> None:
    report = _report()
    headline = object.__new__(ProgrammeHeadline)
    object.__setattr__(headline, "determination", report.headline.determination)
    object.__setattr__(
        headline,
        "primary_lines",
        tuple(line for line in report.headline.primary_lines if line.city != "LAX"),
    )
    object.__setattr__(headline, "mdw_line", report.headline.mdw_line)
    object.__setattr__(headline, "mdw_annotation", report.headline.mdw_annotation)
    object.__setattr__(headline, "unevaluated", report.headline.unevaluated)
    object.__setattr__(headline, "reason", report.headline.reason)

    with pytest.raises(Exception, match="line set"):
        ProgrammeReport(
            headline=headline,
            determination=report.determination,
            evidence=report.evidence,
            secondary_lines=report.secondary_lines,
            out_of_scope_lines=report.out_of_scope_lines,
            stamp=report.stamp,
        )


def test_report_rejects_a_headline_status_differing_from_the_determination() -> None:
    report = _report()
    headline = replace(report.headline, determination=P.PRIMARY_GO)

    with pytest.raises(Exception, match="headline determination"):
        ProgrammeReport(
            headline=headline,
            determination=report.determination,
            evidence=report.evidence,
            secondary_lines=report.secondary_lines,
            out_of_scope_lines=report.out_of_scope_lines,
            stamp=report.stamp,
        )


def test_render_marks_nyc_as_secondary() -> None:
    rendered = render_markdown(_report())
    primary_idx = rendered.index("## PRIMARY CITY DETAIL")
    secondary_idx = rendered.index("## SECONDARY (NYC)")

    assert primary_idx < secondary_idx
    assert "NYC is excluded from the primary verdict" in rendered[secondary_idx:]


def test_programme_rejected_renders_halt_disposition_for_every_city_including_live_ones() -> None:
    rendered = render_markdown(_report(_programme(mdw=C.GO, lax=C.NO_GO, sfo=C.NO_GO)))

    assert rendered.count("HALT_NEW_POSITIONS_HOLD_OPEN_TO_SETTLEMENT") >= 5
    assert "MDW" in rendered


def test_render_always_emits_the_provenance_block() -> None:
    report = _report()
    rendered = render_markdown(report)
    assert "## [R7] PROVENANCE CAVEAT" in rendered

    programme = _programme()
    evidence = _evidence(programme)
    entries = list(evidence.entries)
    first = entries[0]
    figures = dict(first.figures)
    figures[Stratum.BOUNDARY_0_1] = _figure(
        Stratum.BOUNDARY_0_1,
        provenance=FigureProvenance.DECISION_TIME_OBSERVABLE,
    )
    entries[0] = replace(first, figures=figures)
    rendered = render_markdown(
        build_programme_report(
            programme,
            CityEvidenceTable(entries=tuple(entries), evaluation_index=1),
            stamp=_stamp(),
        )
    )
    assert "DECISION_TIME_OBSERVABLE: LAX [0,1)" in rendered


def test_no_go_by_expiry_renders_a_different_basis_than_no_go_on_evidence() -> None:
    evidence_no_go = render_markdown(_report(_programme(mdw=C.NO_GO)))
    expired_no_go = render_markdown(_report(_programme(mdw=C.UNDERPOWERED, evaluations=3)))

    assert "MDW basis: EVIDENCE" in evidence_no_go
    assert "MDW basis: EXPIRY_CONVERSION" in expired_no_go


def test_render_always_emits_both_ledger_partitions() -> None:
    rendered = render_markdown(_report())

    assert "## NOT EVALUATED - structural exclusions" in rendered
    assert "## NOT EVALUATED - evaluation gaps" in rendered
    assert "NONE - every in-scope city carries a reported figure" in rendered


def test_render_refuses_a_headline_built_via_object_new() -> None:
    report = _report()
    malformed = object.__new__(ProgrammeHeadline)

    with pytest.raises(MdwHeadlineOmissionError):
        ProgrammeReport(
            headline=malformed,
            determination=report.determination,
            evidence=report.evidence,
            secondary_lines=report.secondary_lines,
            out_of_scope_lines=report.out_of_scope_lines,
            stamp=report.stamp,
        )


def test_report_is_byte_identical_for_identical_inputs() -> None:
    report = _report()

    assert render_markdown(report) == render_markdown(report)


def test_reporting_module_takes_no_identity_parameter() -> None:
    from breezy.settlement import reporting

    forbidden = re.compile(r"(?i)mdw|primary_cit|secondary_cit|review_city|boundary_stratum")
    offenders = []
    for name in reporting.__all__:
        obj = getattr(reporting, name)
        if not inspect.isfunction(obj):
            continue
        for parameter in inspect.signature(obj).parameters:
            if forbidden.search(parameter):
                offenders.append(f"{name}({parameter})")

    assert offenders == []
