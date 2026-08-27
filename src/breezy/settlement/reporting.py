"""Pure settlement programme reporting.

Pure reporting: this module performs no I/O, clock, environment, or network access.
Programme reports are constructed through build_programme_report.
A PRIMARY_GO report requires MDW's boundary figure to be REPORTED.
"""

from __future__ import annotations

import enum
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from breezy.settlement.coverage import CityDeterminationStatus
from breezy.settlement.programme import (
    CityProgrammeDetermination,
    CityProgrammeScope,
    PositionTakingDisposition,
    ProgrammeDetermination,
    ProgrammeDeterminationStatus,
)

__all__ = [
    "MDW_MANDATORY_REVIEW_CITY",
    "PRE_DECLARED_PRIMARY_CITIES",
    "CityEvidence",
    "CityEvidenceTable",
    "CityHeadlineLine",
    "EvaluationIndexMismatchError",
    "EvidenceCityMismatchError",
    "EvidenceStratumMismatchError",
    "FigureAvailability",
    "FigureProvenance",
    "IncoherentFigureError",
    "MalformedHeadlineError",
    "MdwAbsentFromProgrammeError",
    "MdwAnnotation",
    "MdwFigureUnavailableForPassError",
    "MdwHeadlineOmissionError",
    "NoGoBasis",
    "PowerFloor",
    "PowerFloorStatus",
    "PrimaryCityRosterError",
    "ProgrammeHeadline",
    "ProgrammeReport",
    "ReportStamp",
    "SettlementReportError",
    "SignedErrorDirection",
    "Stratum",
    "StratumFigure",
    "UnevaluatedEntry",
    "UnevaluatedLedger",
    "UnevaluatedReason",
    "UnrecognisedScopeError",
    "VerdictStatus",
    "build_programme_report",
    "render_markdown",
]

MDW_MANDATORY_REVIEW_CITY: Final[str] = "MDW"
PRE_DECLARED_PRIMARY_CITIES: Final[frozenset[str]] = frozenset(
    {"LAX", "MDW", "MIA", "SFO"}
)


class SettlementReportError(Exception):
    """Base class for settlement report failures."""


class EvaluationIndexMismatchError(SettlementReportError):
    """Raised when evidence rows disagree about the evaluation index."""


class EvidenceCityMismatchError(SettlementReportError):
    """Raised when determination and evidence city sets differ."""


class EvidenceStratumMismatchError(SettlementReportError):
    """Raised when a city is missing a pre-registered stratum figure."""


class IncoherentFigureError(SettlementReportError):
    """Raised when a figure's availability and numeric fields disagree."""


class MalformedHeadlineError(SettlementReportError):
    """Raised when a headline object is structurally malformed."""


class MdwAbsentFromProgrammeError(SettlementReportError):
    """Raised when MDW is absent from a sanctioned report."""


class MdwFigureUnavailableForPassError(SettlementReportError):
    """Raised when a pass lacks MDW's boundary figure."""


class MdwHeadlineOmissionError(SettlementReportError):
    """Raised when the headline does not carry the actual MDW line."""


class PrimaryCityRosterError(SettlementReportError):
    """Raised when a primary line is outside the pre-declared primary roster."""


class UnrecognisedScopeError(SettlementReportError):
    """Raised when a city line carries an unknown programme scope."""


@enum.unique
class Stratum(enum.Enum):
    BOUNDARY_0_1 = "[0,1)"
    CLEAR_1_2 = "[1,2)"
    CLEAR_2_3 = "[2,3)"
    CLEAR_3_5 = "[3,5)"
    CLEAR_5_INF = "[5,inf)"


@enum.unique
class FigureAvailability(enum.Enum):
    REPORTED = "REPORTED"
    UNDERPOWERED = "UNDERPOWERED"
    STRUCTURALLY_UNREACHABLE = "STRUCTURALLY_UNREACHABLE"
    PROVISIONAL_UNDERPOWERED = "PROVISIONAL_UNDERPOWERED"
    NOT_DERIVED = "NOT_DERIVED"


@enum.unique
class FigureProvenance(enum.Enum):
    HINDSIGHT_STRATIFIED_BY_FINAL_METAR_MAX = "HINDSIGHT_STRATIFIED_BY_FINAL_METAR_MAX"
    DECISION_TIME_OBSERVABLE = "DECISION_TIME_OBSERVABLE"


@enum.unique
class SignedErrorDirection(enum.Enum):
    METAR_ABOVE_CLI = "METAR_ABOVE_CLI"
    METAR_BELOW_CLI = "METAR_BELOW_CLI"
    MIXED = "MIXED"
    NOT_DERIVED = "NOT_DERIVED"


@enum.unique
class PowerFloorStatus(enum.Enum):
    MET = "MET"
    MET_ONLY_AT_OPTIMISTIC_THETA = "MET_ONLY_AT_OPTIMISTIC_THETA"
    NOT_MET = "NOT_MET"
    NOT_DERIVED = "NOT_DERIVED"


@enum.unique
class VerdictStatus(enum.Enum):
    ISSUED = "ISSUED"
    BLOCKED_PENDING_ADVERSARIAL_REVIEW = "BLOCKED_PENDING_ADVERSARIAL_REVIEW"


@enum.unique
class NoGoBasis(enum.Enum):
    EVIDENCE = "EVIDENCE"
    EXPIRY_CONVERSION = "EXPIRY_CONVERSION"
    NOT_APPLICABLE = "NOT_APPLICABLE"


@enum.unique
class MdwAnnotation(enum.Enum):
    FAILED_AS_PRE_DECLARED = "FAILED_AS_PRE_DECLARED"
    PASSED_CONTRARY_TO_PRE_DECLARED_PREDICTION = (
        "PASSED_CONTRARY_TO_PRE_DECLARED_PREDICTION"
    )
    NOT_YET_RESOLVED = "NOT_YET_RESOLVED"
    EXCLUDED_OUT_OF_SCOPE_DOM_9 = "EXCLUDED_OUT_OF_SCOPE_DOM_9"


@enum.unique
class UnevaluatedReason(enum.Enum):
    BOUNDARY_UNDERPOWERED = "BOUNDARY_UNDERPOWERED"
    BOUNDARY_PROVISIONAL_UNDERPOWERED = "BOUNDARY_PROVISIONAL_UNDERPOWERED"
    BOUNDARY_STRUCTURALLY_UNREACHABLE = "BOUNDARY_STRUCTURALLY_UNREACHABLE"
    BOUNDARY_NOT_YET_ANSWERABLE = "BOUNDARY_NOT_YET_ANSWERABLE"
    STRATUM_FIGURE_NOT_DERIVED = "STRATUM_FIGURE_NOT_DERIVED"
    STRATUM_FIGURE_UNDERPOWERED = "STRATUM_FIGURE_UNDERPOWERED"
    EXCLUDED_SECONDARY_NYC = "EXCLUDED_SECONDARY_NYC"
    EXCLUDED_OUT_OF_SCOPE_DOM_9 = "EXCLUDED_OUT_OF_SCOPE_DOM_9"
    VERDICT_BLOCKED_PENDING_REVIEW = "VERDICT_BLOCKED_PENDING_REVIEW"


@dataclass(frozen=True, slots=True, kw_only=True)
class PowerFloor:
    floor_n: int | None
    anchor: str | None
    met: PowerFloorStatus


@dataclass(frozen=True, slots=True, kw_only=True)
class StratumFigure:
    stratum: Stratum
    availability: FigureAvailability
    cases: int | None
    agreements: int | None
    wilson_lower: str | None
    break_even: str | None
    signed_error_direction: SignedErrorDirection
    mean_signed_error: str | None
    power_floor: PowerFloor
    note: str
    provenance: FigureProvenance = (
        FigureProvenance.HINDSIGHT_STRATIFIED_BY_FINAL_METAR_MAX
    )

    def __post_init__(self) -> None:
        has_bounds = self.wilson_lower is not None and self.break_even is not None
        if (self.availability is FigureAvailability.REPORTED) != has_bounds:
            raise IncoherentFigureError(
                f"{self.stratum.value} availability {self.availability.name} is "
                "incoherent with wilson_lower/break_even"
            )
        has_counts = self.cases is not None and self.agreements is not None
        if self.availability is FigureAvailability.NOT_DERIVED:
            if has_counts:
                raise IncoherentFigureError("NOT_DERIVED figures must not carry counts")
        elif not has_counts:
            raise IncoherentFigureError(
                f"{self.availability.name} figures must retain cases and agreements"
            )
        if (self.cases is None) != (self.agreements is None):
            raise IncoherentFigureError("cases and agreements must be filled together")
        if (self.wilson_lower is None) != (self.break_even is None):
            raise IncoherentFigureError("wilson_lower and break_even must be filled together")


@dataclass(frozen=True, slots=True, kw_only=True)
class CityEvidence:
    city: str
    figures: Mapping[Stratum, StratumFigure]
    evaluation_index: int
    tape_window: str

    def __post_init__(self) -> None:
        if self.evaluation_index < 1:
            raise EvaluationIndexMismatchError("evaluation_index must be >= 1")
        actual = frozenset(self.figures)
        expected = frozenset(Stratum)
        if actual != expected:
            raise EvidenceStratumMismatchError(
                f"city {self.city!r} figures must exactly match strata; "
                f"missing={_stratum_values(expected - actual)!r}, "
                f"unexpected={_stratum_values(actual - expected)!r}"
            )
        for stratum, figure in self.figures.items():
            if figure.stratum is not stratum:
                raise EvidenceStratumMismatchError(
                    f"city {self.city!r} maps {stratum.value} to {figure.stratum.value}"
                )
        object.__setattr__(self, "figures", {stratum: self.figures[stratum] for stratum in Stratum})


@dataclass(frozen=True, slots=True, kw_only=True)
class CityEvidenceTable:
    entries: tuple[CityEvidence, ...]
    evaluation_index: int

    def __post_init__(self) -> None:
        if self.evaluation_index < 1:
            raise EvaluationIndexMismatchError("evaluation_index must be >= 1")
        cities = tuple(entry.city for entry in self.entries)
        if len(cities) != len(set(cities)):
            raise EvidenceCityMismatchError("evidence contains duplicate city identities")
        for entry in self.entries:
            if entry.evaluation_index != self.evaluation_index:
                raise EvaluationIndexMismatchError(
                    f"city {entry.city!r} evaluation_index={entry.evaluation_index} "
                    f"does not match table evaluation_index={self.evaluation_index}"
                )
        object.__setattr__(
            self,
            "entries",
            tuple(sorted(self.entries, key=lambda entry: entry.city)),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ReportStamp:
    generated_at_utc: str
    cells_sha256: str
    evidence_sha256: str
    command: str


@dataclass(frozen=True, slots=True, kw_only=True)
class UnevaluatedEntry:
    city: str
    reason: UnevaluatedReason
    detail: str
    stratum: Stratum | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class UnevaluatedLedger:
    structural_exclusions: tuple[UnevaluatedEntry, ...]
    evaluation_gaps: tuple[UnevaluatedEntry, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class CityHeadlineLine:
    city: str
    scope: CityProgrammeScope
    determination: CityDeterminationStatus
    position_taking: PositionTakingDisposition
    verdict_status: VerdictStatus
    no_go_basis: NoGoBasis
    figures: tuple[StratumFigure, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class ProgrammeHeadline:
    determination: ProgrammeDeterminationStatus
    primary_lines: tuple[CityHeadlineLine, ...]
    mdw_line: CityHeadlineLine
    mdw_annotation: MdwAnnotation
    unevaluated: UnevaluatedLedger
    reason: str

    def __post_init__(self) -> None:
        _assert_headline_invariants(self)


@dataclass(frozen=True, slots=True, kw_only=True)
class ProgrammeReport:
    headline: ProgrammeHeadline
    determination: ProgrammeDetermination
    evidence: CityEvidenceTable
    secondary_lines: tuple[CityHeadlineLine, ...]
    out_of_scope_lines: tuple[CityHeadlineLine, ...]
    stamp: ReportStamp

    def __post_init__(self) -> None:
        _assert_headline_invariants(self.headline)
        if self.headline.determination is not self.determination.determination:
            raise MalformedHeadlineError(
                "headline determination does not match programme determination"
            )
        by_city = {line.city: line for line in _all_lines(self)}
        determination_cities = {city.city for city in self.determination.city_determinations}
        if set(by_city) != determination_cities or len(by_city) != len(tuple(_all_lines(self))):
            raise MalformedHeadlineError(
                f"report line set does not match determination cities; "
                f"lines={sorted(by_city)!r}, determinations={sorted(determination_cities)!r}"
            )


def build_programme_report(
    determination: ProgrammeDetermination,
    evidence: CityEvidenceTable,
    *,
    stamp: ReportStamp,
) -> ProgrammeReport:
    determination_cities = tuple(city.city for city in determination.city_determinations)
    evidence_by_city = {entry.city: entry for entry in evidence.entries}
    _assert_exact_city_set(determination_cities, tuple(evidence_by_city), label="evidence")
    if MDW_MANDATORY_REVIEW_CITY not in determination_cities:
        raise MdwAbsentFromProgrammeError("MDW is absent from the programme determination")

    lines = tuple(
        _line_for(city, evidence_by_city[city.city])
        for city in determination.city_determinations
    )
    primary_lines = tuple(line for line in lines if line.scope is CityProgrammeScope.PRIMARY)
    secondary_lines = tuple(
        line for line in lines if line.scope is CityProgrammeScope.SECONDARY_NYC
    )
    out_of_scope_lines = tuple(
        line for line in lines if line.scope is CityProgrammeScope.OUT_OF_SCOPE_DOM_9
    )
    mdw_line = _line_by_city(lines, MDW_MANDATORY_REVIEW_CITY)
    ledger = _build_ledger(lines)
    headline = ProgrammeHeadline(
        determination=determination.determination,
        primary_lines=primary_lines,
        mdw_line=mdw_line,
        mdw_annotation=_mdw_annotation(mdw_line),
        unevaluated=ledger,
        reason=determination.reason,
    )
    return ProgrammeReport(
        headline=headline,
        determination=determination,
        evidence=evidence,
        secondary_lines=secondary_lines,
        out_of_scope_lines=out_of_scope_lines,
        stamp=stamp,
    )


def render_markdown(report: ProgrammeReport) -> str:
    _assert_headline_invariants(report.headline)
    lines: list[str] = [
        "# Settlement programme report",
        "",
        f"- Generated at UTC: {report.stamp.generated_at_utc}",
        f"- Evaluation index: {report.evidence.evaluation_index}",
        f"- Cells sha256: {report.stamp.cells_sha256}",
        f"- Evidence sha256: {report.stamp.evidence_sha256}",
        f"- Command: {report.stamp.command}",
        "",
        "## HEADLINE VERDICT",
        f"Determination: {report.headline.determination.name}",
        f"PRIMARY CITIES: {', '.join(line.city for line in report.headline.primary_lines)}",
        f"Reason: {report.headline.reason}",
        "",
        "## MDW",
    ]
    lines.extend(_render_line_summary(report.headline.mdw_line, prefix="MDW"))
    lines.append(f"MDW annotation: {report.headline.mdw_annotation.value}")
    if (
        report.headline.mdw_annotation
        is MdwAnnotation.PASSED_CONTRARY_TO_PRE_DECLARED_PREDICTION
    ):
        lines.append(
            "MDW passed contrary to the pre-declared prediction; "
            "explanation required before any GO."
        )
    lines.extend(["", "## NOT EVALUATED - structural exclusions"])
    if report.headline.unevaluated.structural_exclusions:
        lines.extend(_render_unevaluated(report.headline.unevaluated.structural_exclusions))
    else:
        lines.append("NONE - no structural exclusions.")
    lines.extend(["", "## NOT EVALUATED - evaluation gaps"])
    if report.headline.unevaluated.evaluation_gaps:
        lines.extend(_render_unevaluated(report.headline.unevaluated.evaluation_gaps))
    else:
        lines.append(
            "NONE - every in-scope city carries a reported figure at every one of "
            "the five pre-registered strata."
        )
    lines.extend(["", "## PRIMARY CITY DETAIL"])
    for line in report.headline.primary_lines:
        lines.extend(_render_city_detail(line))
    lines.extend(["", "## SECONDARY (NYC) - excluded from the primary verdict"])
    if report.secondary_lines:
        for line in report.secondary_lines:
            lines.append("NYC is excluded from the primary verdict.")
            lines.extend(_render_city_detail(line))
    else:
        lines.append("NONE")
    lines.extend(["", "## OUT OF SCOPE (DOM-9)"])
    if report.out_of_scope_lines:
        for line in report.out_of_scope_lines:
            lines.extend(_render_city_detail(line))
    else:
        lines.append("NONE")
    lines.extend(["", "## [R7] PROVENANCE CAVEAT"])
    decision_time = [
        f"{line.city} {figure.stratum.value}"
        for line in _all_lines(report)
        for figure in line.figures
        if figure.provenance is FigureProvenance.DECISION_TIME_OBSERVABLE
    ]
    if decision_time:
        lines.append(f"DECISION_TIME_OBSERVABLE: {', '.join(decision_time)}")
    else:
        lines.append("DECISION_TIME_OBSERVABLE: NONE")
    lines.append(
        "All reported figures are evidence only and were input to no settlement determination."
    )
    return "\n".join(lines) + "\n"


def _line_for(
    city: CityProgrammeDetermination,
    evidence: CityEvidence,
) -> CityHeadlineLine:
    figures = tuple(evidence.figures[stratum] for stratum in Stratum)
    boundary = evidence.figures[Stratum.BOUNDARY_0_1]
    verdict_status = (
        VerdictStatus.BLOCKED_PENDING_ADVERSARIAL_REVIEW
        if boundary.availability
        in {
            FigureAvailability.PROVISIONAL_UNDERPOWERED,
            FigureAvailability.STRUCTURALLY_UNREACHABLE,
        }
        else VerdictStatus.ISSUED
    )
    return CityHeadlineLine(
        city=city.city,
        scope=city.scope,
        determination=city.city_determination.determination,
        position_taking=city.position_taking,
        verdict_status=verdict_status,
        no_go_basis=_no_go_basis(
            city.city_determination.determination,
            city.city_determination.reason,
        ),
        figures=figures,
    )


def _no_go_basis(status: CityDeterminationStatus, reason: str) -> NoGoBasis:
    if status is not CityDeterminationStatus.NO_GO:
        return NoGoBasis.NOT_APPLICABLE
    if "[R3] converts" in reason:
        return NoGoBasis.EXPIRY_CONVERSION
    return NoGoBasis.EVIDENCE


def _build_ledger(lines: tuple[CityHeadlineLine, ...]) -> UnevaluatedLedger:
    structural: list[UnevaluatedEntry] = []
    gaps: list[UnevaluatedEntry] = []
    for line in lines:
        if line.scope is CityProgrammeScope.SECONDARY_NYC:
            structural.append(
                UnevaluatedEntry(
                    city=line.city,
                    reason=UnevaluatedReason.EXCLUDED_SECONDARY_NYC,
                    detail="NYC is structurally secondary under prereg rule 5.",
                )
            )
        elif line.scope is CityProgrammeScope.OUT_OF_SCOPE_DOM_9:
            structural.append(
                UnevaluatedEntry(
                    city=line.city,
                    reason=UnevaluatedReason.EXCLUDED_OUT_OF_SCOPE_DOM_9,
                    detail="City is excluded under DOM-9.",
                )
            )
        if line.verdict_status is VerdictStatus.BLOCKED_PENDING_ADVERSARIAL_REVIEW:
            gaps.append(
                UnevaluatedEntry(
                    city=line.city,
                    reason=UnevaluatedReason.VERDICT_BLOCKED_PENDING_REVIEW,
                    detail="VERDICT BLOCKED PENDING ADVERSARIAL RE-REVIEW",
                )
            )
        for figure in line.figures:
            reason = _gap_reason(figure)
            if reason is not None:
                detail = (
                    "FINDING: structurally unreachable"
                    if reason is UnevaluatedReason.BOUNDARY_STRUCTURALLY_UNREACHABLE
                    else figure.note
                )
                gaps.append(
                    UnevaluatedEntry(
                        city=line.city,
                        reason=reason,
                        stratum=figure.stratum,
                        detail=detail,
                    )
                )
    return UnevaluatedLedger(
        structural_exclusions=tuple(structural),
        evaluation_gaps=tuple(gaps),
    )


def _gap_reason(figure: StratumFigure) -> UnevaluatedReason | None:
    if figure.availability is FigureAvailability.REPORTED:
        return None
    is_boundary = figure.stratum is Stratum.BOUNDARY_0_1
    if is_boundary and figure.availability is FigureAvailability.UNDERPOWERED:
        return UnevaluatedReason.BOUNDARY_UNDERPOWERED
    if is_boundary and figure.availability is FigureAvailability.PROVISIONAL_UNDERPOWERED:
        return UnevaluatedReason.BOUNDARY_PROVISIONAL_UNDERPOWERED
    if is_boundary and figure.availability is FigureAvailability.STRUCTURALLY_UNREACHABLE:
        return UnevaluatedReason.BOUNDARY_STRUCTURALLY_UNREACHABLE
    if is_boundary and figure.availability is FigureAvailability.NOT_DERIVED:
        return UnevaluatedReason.BOUNDARY_NOT_YET_ANSWERABLE
    if figure.availability is FigureAvailability.UNDERPOWERED:
        return UnevaluatedReason.STRATUM_FIGURE_UNDERPOWERED
    return UnevaluatedReason.STRATUM_FIGURE_NOT_DERIVED


def _assert_headline_invariants(headline: ProgrammeHeadline) -> None:
    try:
        mdw_line = headline.mdw_line
        primary_lines = headline.primary_lines
        determination = headline.determination
    except AttributeError as exc:
        raise MdwHeadlineOmissionError("headline is malformed and has no MDW line") from exc
    if mdw_line.city != MDW_MANDATORY_REVIEW_CITY:
        raise MdwHeadlineOmissionError("headline mdw_line is not MDW")
    if mdw_line.scope is CityProgrammeScope.PRIMARY and not any(
        line is mdw_line for line in primary_lines
    ):
        raise MdwHeadlineOmissionError("MDW primary line is not the body line object")
    primary_cities = {line.city for line in primary_lines}
    if not primary_cities <= PRE_DECLARED_PRIMARY_CITIES:
        raise PrimaryCityRosterError(
            f"primary city set contains undeclared cities: {sorted(primary_cities)!r}"
        )
    if (
        mdw_line.scope is CityProgrammeScope.PRIMARY
        and MDW_MANDATORY_REVIEW_CITY not in primary_cities
    ):
        raise MdwHeadlineOmissionError("MDW is missing from primary headline lines")
    for line in primary_lines:
        if line.scope is not CityProgrammeScope.PRIMARY:
            raise UnrecognisedScopeError(f"primary line {line.city!r} has scope {line.scope}")
    if determination is ProgrammeDeterminationStatus.PRIMARY_GO:
        boundary = _figure_by_stratum(mdw_line, Stratum.BOUNDARY_0_1)
        if boundary.availability is not FigureAvailability.REPORTED:
            raise MdwFigureUnavailableForPassError(
                "PRIMARY_GO requires MDW boundary figure availability REPORTED"
            )


def _mdw_annotation(line: CityHeadlineLine) -> MdwAnnotation:
    if line.scope is CityProgrammeScope.OUT_OF_SCOPE_DOM_9:
        return MdwAnnotation.EXCLUDED_OUT_OF_SCOPE_DOM_9
    if line.determination is CityDeterminationStatus.GO:
        return MdwAnnotation.PASSED_CONTRARY_TO_PRE_DECLARED_PREDICTION
    if line.determination is CityDeterminationStatus.NOT_YET_ANSWERABLE:
        return MdwAnnotation.NOT_YET_RESOLVED
    return MdwAnnotation.FAILED_AS_PRE_DECLARED


def _render_line_summary(line: CityHeadlineLine, *, prefix: str) -> list[str]:
    rendered = [
        f"{prefix} city: {line.city}",
        f"{prefix} scope: {line.scope.name}",
        (
            f"{prefix} verdict: VERDICT BLOCKED PENDING ADVERSARIAL RE-REVIEW"
            if line.verdict_status is VerdictStatus.BLOCKED_PENDING_ADVERSARIAL_REVIEW
            else f"{prefix} verdict: {line.determination.name}"
        ),
        f"{prefix} position: {line.position_taking.name}",
        f"{line.city} basis: {line.no_go_basis.name}",
    ]
    boundary = _figure_by_stratum(line, Stratum.BOUNDARY_0_1)
    rendered.append(_render_figure(boundary))
    return rendered


def _render_city_detail(line: CityHeadlineLine) -> list[str]:
    rendered = [
        f"### {line.city}",
        f"{line.city} city: {line.city}",
        f"{line.city} scope: {line.scope.name}",
        (
            f"{line.city} verdict: VERDICT BLOCKED PENDING ADVERSARIAL RE-REVIEW"
            if line.verdict_status is VerdictStatus.BLOCKED_PENDING_ADVERSARIAL_REVIEW
            else f"{line.city} verdict: {line.determination.name}"
        ),
        f"{line.city} position: {line.position_taking.name}",
        f"{line.city} basis: {line.no_go_basis.name}",
    ]
    for figure in line.figures:
        rendered.append(_render_figure(figure))
    return rendered


def _render_figure(figure: StratumFigure) -> str:
    return (
        f"- {figure.stratum.value}: availability={figure.availability.name}; "
        f"cases={figure.cases}; agreements={figure.agreements}; "
        f"wilson_lower={figure.wilson_lower}; break_even={figure.break_even}; "
        f"signed_error_direction={figure.signed_error_direction.name}; "
        f"mean_signed_error={figure.mean_signed_error}; "
        f"Power floor: {figure.power_floor.met.name}; "
        f"note={figure.note}"
    )


def _render_unevaluated(entries: tuple[UnevaluatedEntry, ...]) -> list[str]:
    rendered = []
    for entry in entries:
        if entry.stratum is None:
            rendered.append(f"{entry.city} {entry.reason.name}: {entry.detail}")
        else:
            rendered.append(
                f"{entry.city} {entry.stratum.value} {entry.reason.name}: "
                f"{entry.detail}; cases={_cases_for(entry)}"
            )
    return rendered


def _cases_for(_entry: UnevaluatedEntry) -> str:
    return "see detail table"


def _figure_by_stratum(line: CityHeadlineLine, stratum: Stratum) -> StratumFigure:
    for figure in line.figures:
        if figure.stratum is stratum:
            return figure
    raise EvidenceStratumMismatchError(f"{line.city!r} has no {stratum.value} figure")


def _line_by_city(lines: tuple[CityHeadlineLine, ...], city: str) -> CityHeadlineLine:
    for line in lines:
        if line.city == city:
            return line
    raise MdwAbsentFromProgrammeError(f"{city} is absent from the programme report")


def _all_lines(report: ProgrammeReport) -> tuple[CityHeadlineLine, ...]:
    return (
        report.headline.primary_lines
        + report.secondary_lines
        + report.out_of_scope_lines
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
        raise EvidenceCityMismatchError(
            f"{label} must exactly match determination cities; "
            f"missing={missing!r}, unexpected={unexpected!r}"
        )


def _stratum_values(strata: frozenset[Stratum]) -> tuple[str, ...]:
    return tuple(sorted(stratum.value for stratum in strata))
