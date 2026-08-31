#!/usr/bin/env python
"""P2 Probe C -- resolve the Open-Meteo previous-run ARCHIVE-COVERAGE anomaly.

Authority: ``docs/plans/DATA_CAPTURE_AND_RISK_PLAN.md`` section 4.P2, clause
``archive_reaches_2024_01``. That clause is the ONE thing Probe A left
unresolved, and it gates an irreversible decision: whether
``WeatherForecastDay`` carries ``model``, ``init_time_ns`` and
``previous_run_index``. Under ``make_strict_decoder`` plus one
``register_arrow`` those fields cannot be added after the first row is
written, ever. So this probe's output is evidence and nothing else.

EVIDENCE ONLY -- NEVER INGEST. Every payload carries the ``.probe.json``
suffix no production loader reads, in a directory whose README repeats the
rule. Backfilling a captured forecast under a plausible retrieval timestamp
would be backdating and would destroy the point-in-time property.

THE ANOMALY
-----------
``docs/evidence/open_meteo_previous_runs_probe_2026-08-31T005848Z`` recorded,
for ``temperature_2m_previous_day1`` at the NYC coordinates, all HTTP 200:

===============  ===================
window           non-null hours
===============  ===================
2019-01-01..07   0 / 168
2022-01-01..07   168 / 168
2024-01-01..07   0 / 168
===============  ===================

That shape is NON-MONOTONIC. No "the archive starts on date D" can produce it,
so "an older window had data" must never be read as "the archive reaches
2024-01". Probe A said so and marked the clause unresolved; this probe exists
to find out what actually produces the shape.

THE HYPOTHESIS UNDER TEST
-------------------------
Coverage is **per-model**. Probe A used the ``best_match`` default, which
resolves to a different underlying model by era; only some of those models
have previous-run archives. If that is right, an explicit ``models=`` is
populated exactly where ``best_match`` is null -- and then ``model`` is not an
optional nicety in the record schema, it is the key the coverage is a function
of. The alternative -- coverage is purely a function of date, and the archive
is genuinely patchy -- is the clean negative, and is reported as such.

WHAT IT DOES, IN THREE BUDGETED PHASES
--------------------------------------
1. **Matrix** (:data:`MATRIX_BUDGET` requests): the two dates that disagree,
   crossed with ``best_match`` and three explicit models. This is what
   separates the DATE axis from the MODEL axis; a cross is the only shape that
   can, and it is why the phase is worth half the budget.
2. **Bisect** (:data:`BISECT_BUDGET` requests): for the best-covered model,
   halve the interval between one covered and one empty observation until the
   bracket is inside :data:`BISECT_RESOLUTION_DAYS`. Bisecting rather than
   scanning is the whole reason the budget can be this small.
3. **Contiguity** (:data:`CONTIGUITY_BUDGET` requests): sample strictly INSIDE
   the established covered span. A range whose endpoints answer can still be
   full of holes, and a per-model harvest built on the assumption of
   contiguity would silently ship those holes as missing forecasts.

CONTAINMENT
-----------
* Transport is :class:`breezy.ingest.probe_transport.ProbeTransport`, the
  hardened ``breezy.ingest.http.HttpTransport`` subclass. No other HTTP client
  is imported (AST-asserted in ``tests/unit/test_probe_containment.py``).
* ``allowed_hosts`` is this probe's own single origin. The shipped default
  allowlist is neither imported nor widened. The settlement origin is refused
  by the transport constructor and is not named anywhere in this file.
* ``max_body_bytes`` is per-instance; no global lever is touched.
* :data:`REQUEST_BUDGET` is HARD at 16 -- the ceiling authorised for this
  question. The (N+1)th request raises and aborts the run, and a test asserts
  the three phase ceilings sum to no more than it.
* One request at a time, with a courtesy pause. No retries, no parallelism:
  this is a free public API and a tight loop against it is an abuse pattern,
  not an optimisation.
* Refuses to start without ``BREEZY_LIVE=1``, ``--apply``, and a contactable
  ``BREEZY_USER_AGENT``.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import os
import sys
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from breezy.ingest.probe_transport import (
    ProbeEvidenceWriter,
    ProbeExchange,
    ProbeTransport,
    RequestBudget,
    RequestBudgetExceededError,
)
from breezy.registry.sites import default_registry

# ==========================================================================
# The origin, and the ceilings
# ==========================================================================

#: Probe A ESTABLISHED this host and path; re-discovering it would be budget
#: spent to re-learn a recorded positive.
HOST: str = "previous-runs-api.open-meteo.com"
BASE_URL: str = f"https://{HOST}"
PATH: str = "/v1/forecast"

#: Per-PROBE, and the only host this probe's transport may reach.
ALLOWED_HOSTS: frozenset[str] = frozenset({HOST})

#: Per-INSTANCE cap. Probe A measured the largest plausible payload at ~10 KiB;
#: this leaves two orders of magnitude of headroom without touching a global.
MAX_BODY_BYTES: int = 512 * 1024

#: HARD. The (N+1)th request raises and aborts the run.
REQUEST_BUDGET: int = 16

#: Phase ceilings. A test asserts they sum to no more than the hard budget, so
#: adding a step cannot over-spend without deliberately raising the ceiling.
MATRIX_BUDGET: int = 8
BISECT_BUDGET: int = 5
CONTIGUITY_BUDGET: int = 3

LIVE_ENV_VAR: str = "BREEZY_LIVE"
USER_AGENT_ENV_VAR: str = "BREEZY_USER_AGENT"

DEFAULT_OUTPUT_DIRECTORY: str = "open_meteo_coverage_bisect_probe"

# ==========================================================================
# What is measured
# ==========================================================================

#: The surface Probe A proved works. ``daily`` returns HTTP 400 here.
SURFACE: str = "hourly"
BASE_VARIABLE: str = "temperature_2m"
PREVIOUS_DAY_VARIABLE: str = f"{BASE_VARIABLE}_previous_day1"

#: The window length, matched to Probe A's so the cells are comparable to the
#: anomaly as recorded rather than to a differently-shaped request.
WINDOW_DAYS: int = 7

#: The site. The registry is the only source of coordinates; this probe never
#: invents one.
PRIMARY_CITY: str = "NYC"
VENUE: str = "polymarket_us"

#: The clause's own date, and the control Probe A found populated. Both are in
#: the matrix: a bar date with no positive control beside it cannot be read.
BAR_DATE: dt.date = dt.date(2024, 1, 1)
CONTROL_DATE: dt.date = dt.date(2022, 1, 1)
MATRIX_DATES: tuple[dt.date, ...] = (CONTROL_DATE, BAR_DATE)

#: ``best_match`` is what Probe A used; the three explicit identifiers are the
#: ones Probe A proved are ACCEPTED by this endpoint. Testing the default
#: against explicit models is what separates the two axes.
MATRIX_MODELS: tuple[str, ...] = (
    "best_match",
    "ecmwf_ifs025",
    "gfs_seamless",
    "icon_seamless",
)

#: Stop bisecting once the bracket is this tight. A boundary located to within
#: a month answers "does it reach 2024-01"; spending further requests to name
#: the exact day answers a question nobody asked.
BISECT_RESOLUTION_DAYS: int = 31

CLAUSE_ARCHIVE: str = "archive_reaches_2024_01"

STATE_SATISFIED: str = "SATISFIED"
STATE_REFUTED: str = "REFUTED"
STATE_INCONCLUSIVE: str = "STILL INCONCLUSIVE"

DEPENDENCE_DATE: str = "date"
DEPENDENCE_MODEL: str = "model"
DEPENDENCE_BOTH: str = "both"
DEPENDENCE_NEITHER_COVERED: str = "neither (uniformly covered)"
DEPENDENCE_NEITHER_EMPTY: str = "neither (uniformly empty)"
DEPENDENCE_UNDETERMINED: str = "undetermined"

CONTIGUITY_CONTIGUOUS: str = "contiguous"
CONTIGUITY_PATCHY: str = "patchy"
CONTIGUITY_UNSAMPLED: str = "unsampled"


# ==========================================================================
# Request construction
# ==========================================================================


@dataclass(frozen=True, slots=True)
class CoverageStep:
    """One labelled request for one (window, model) coverage cell."""

    label: str
    start: dt.date
    model: str
    query: Mapping[str, str]
    phase: str


def _coordinates(city: str) -> tuple[str, str]:
    coords = default_registry().enrichment_coordinates(VENUE, city)
    return (f"{coords.lat:.5f}", f"{coords.lon:.5f}")


def window_query(start: dt.date, model: str) -> dict[str, str]:
    """The query for one ``WINDOW_DAYS`` window of one model.

    ``models=`` is always sent EXPLICITLY, including for ``best_match``: the
    hypothesis under test is that the default resolves differently by era, and
    a request that omits the parameter cannot distinguish "the default" from
    "whatever the server felt like".
    """
    lat, lon = _coordinates(PRIMARY_CITY)
    end = start + dt.timedelta(days=WINDOW_DAYS - 1)
    return {
        "latitude": lat,
        "longitude": lon,
        "timezone": "UTC",
        SURFACE: f"{BASE_VARIABLE},{PREVIOUS_DAY_VARIABLE}",
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "models": model,
    }


def _step(start: dt.date, model: str, *, phase: str) -> CoverageStep:
    return CoverageStep(
        label=f"{phase}_{start.isoformat()}_{model}",
        start=start,
        model=model,
        query=window_query(start, model),
        phase=phase,
    )


def build_matrix_plan() -> tuple[CoverageStep, ...]:
    """Phase 1: every matrix date crossed with every matrix model.

    Date-major dispatch order, so a run that is cut short by an exhausted
    budget still holds a COMPLETE row for the first date rather than a
    scattered half of both.
    """
    return tuple(
        _step(start, model, phase="matrix") for start in MATRIX_DATES for model in MATRIX_MODELS
    )


# ==========================================================================
# Reading a cell -- a 200 is not an answer
# ==========================================================================


@dataclass(frozen=True, slots=True)
class CoverageCell:
    """How much of one window the endpoint actually filled in."""

    rows: int
    non_null: int

    @property
    def covered(self) -> bool:
        return self.non_null > 0

    def __str__(self) -> str:
        return f"{self.non_null}/{self.rows}"


def count_coverage(exchange: ProbeExchange) -> CoverageCell | None:
    """Count non-null previous-run hours, or ``None`` if there is no cell.

    The distinction the whole anomaly turns on: **served-and-all-null is a
    zero cell; not served at all is no cell.** A non-2xx, a malformed body, a
    missing series or an empty series carries no measurement, and reading any
    of them as "zero coverage" would manufacture a boundary out of a transport
    failure.
    """
    if not exchange.succeeded or exchange.text is None:
        return None
    try:
        payload = json.loads(exchange.text)
    except ValueError:
        return None
    if not isinstance(payload, Mapping):
        return None
    block = payload.get(SURFACE)
    if not isinstance(block, Mapping):
        return None
    values = block.get(PREVIOUS_DAY_VARIABLE)
    if not isinstance(values, list) or not values:
        return None
    return CoverageCell(rows=len(values), non_null=sum(1 for value in values if value is not None))


# ==========================================================================
# Separating the two axes
# ==========================================================================

CellMap = Mapping[tuple[dt.date, str], CoverageCell]


def _varies(groups: Iterable[Sequence[bool]]) -> bool:
    """True when any group holds both a covered and an empty observation."""
    return any(len(set(flags)) > 1 for flags in groups)


def classify_dependence(cells: CellMap) -> str:
    """Is the null-ness a function of the DATE, of the MODEL, or of both?

    Answered only from cells that were actually measured. An axis "varies" when
    two cells sharing the other coordinate disagree -- which is why the phase-1
    request shape is a cross and not a list.
    """
    if not cells:
        return DEPENDENCE_UNDETERMINED

    by_date: dict[dt.date, list[bool]] = {}
    by_model: dict[str, list[bool]] = {}
    for (date, model), cell in cells.items():
        by_date.setdefault(date, []).append(cell.covered)
        by_model.setdefault(model, []).append(cell.covered)

    model_axis = _varies(by_date.values())  # sharing a date, differing by model
    date_axis = _varies(by_model.values())  # sharing a model, differing by date

    if model_axis and date_axis:
        return DEPENDENCE_BOTH
    if model_axis:
        return DEPENDENCE_MODEL
    if date_axis:
        return DEPENDENCE_DATE

    flags = {cell.covered for cell in cells.values()}
    if flags == {True}:
        return DEPENDENCE_NEITHER_COVERED
    if flags == {False}:
        return DEPENDENCE_NEITHER_EMPTY
    # Mixed, but no two cells share a coordinate: the matrix was too sparse to
    # attribute the difference to either axis. Say so rather than guess.
    return DEPENDENCE_UNDETERMINED


def choose_reference_model(cells: CellMap) -> str | None:
    """The best-covered model, or ``None`` when nothing anywhere is covered.

    Ties break on :data:`MATRIX_MODELS` order so two equally-covered models
    cannot make the run irreproducible.
    """
    totals: dict[str, int] = {}
    for (_, model), cell in cells.items():
        totals[model] = totals.get(model, 0) + cell.non_null
    if not totals or max(totals.values()) == 0:
        return None
    best = max(totals.values())
    candidates = [model for model, total in totals.items() if total == best]
    return min(candidates, key=lambda model: (_model_rank(model), model))


def _model_rank(model: str) -> int:
    return MATRIX_MODELS.index(model) if model in MATRIX_MODELS else len(MATRIX_MODELS)


# ==========================================================================
# The bisect
# ==========================================================================


def bisect_bracket(observations: Mapping[dt.date, bool]) -> tuple[dt.date, dt.date] | None:
    """The tightest ``(covered, empty)`` pair to halve, or ``None``.

    Direction-agnostic on purpose: the boundary may be an archive START (the
    empty side older) or an archive END (the empty side newer), and the
    anomaly is consistent with either.
    """
    covered = [date for date, flag in observations.items() if flag]
    empty = [date for date, flag in observations.items() if not flag]
    if not covered or not empty:
        return None
    return min(
        ((low, high) for low in covered for high in empty),
        key=lambda pair: (abs((pair[1] - pair[0]).days), pair[0], pair[1]),
    )


def next_bisect_date(covered: dt.date, empty: dt.date) -> dt.date | None:
    """The midpoint to request next, or ``None`` once the bracket is tight.

    Returning ``None`` at :data:`BISECT_RESOLUTION_DAYS` is what keeps the
    budget honest: past that width, another request buys precision nobody
    asked for.
    """
    low, high = sorted((covered, empty))
    span = (high - low).days
    if span <= BISECT_RESOLUTION_DAYS:
        return None
    return low + dt.timedelta(days=span // 2)


# ==========================================================================
# Contiguity inside the covered span
# ==========================================================================


def contiguity_dates(low: dt.date, high: dt.date, count: int) -> tuple[dt.date, ...]:
    """``count`` evenly spaced dates STRICTLY inside ``(low, high)``.

    Strictly inside because the endpoints are already known: re-asking them
    would spend budget confirming what the bisect already recorded.
    """
    span = (high - low).days
    step = span // (count + 1)
    if count < 1 or step < 1:
        return ()
    return tuple(low + dt.timedelta(days=step * (index + 1)) for index in range(count))


def contiguity_of(samples: Mapping[dt.date, CoverageCell]) -> str:
    """Whether every interior sample carried values.

    An unsampled range is reported as unsampled, never as contiguous: a
    per-model harvest built on an assumed-contiguous range would ship its holes
    as missing forecasts.
    """
    if not samples:
        return CONTIGUITY_UNSAMPLED
    if all(cell.covered for cell in samples.values()):
        return CONTIGUITY_CONTIGUOUS
    return CONTIGUITY_PATCHY


# ==========================================================================
# The verdict on the clause
# ==========================================================================


@dataclass(frozen=True, slots=True)
class ClauseVerdict:
    """The computed state of ``archive_reaches_2024_01``, plus its evidence."""

    state: str
    evidence: str


def evaluate_archive_clause(cells: CellMap, *, contiguity: str) -> ClauseVerdict:
    """SATISFIED / REFUTED / STILL INCONCLUSIVE, computed from the cells alone.

    REFUTED requires a POSITIVE CONTROL: some cell somewhere in this same run
    carried values, proving the request shape works. Without one, an all-null
    result is equally consistent with "our request is wrong", and the honest
    answer is inconclusive -- Probe A's 22-HTTP-404 report is the standing
    reminder of what happens when a null is read as an answer.
    """
    at_bar = {model: cell for (date, model), cell in cells.items() if date == BAR_DATE}
    covered_at_bar = sorted(model for model, cell in at_bar.items() if cell.covered)
    elsewhere = sorted(
        {date for (date, _), cell in cells.items() if cell.covered and date != BAR_DATE}
    )

    if covered_at_bar:
        note = (
            " Coverage inside the established span is PATCHY, so reaching the bar date "
            "does not imply a usable contiguous history."
            if contiguity == CONTIGUITY_PATCHY
            else ""
        )
        detail = ", ".join(f"{model}={at_bar[model]}" for model in covered_at_bar)
        return ClauseVerdict(
            state=STATE_SATISFIED,
            evidence=(
                f"{BAR_DATE.isoformat()} returned previous-run values for "
                f"{len(covered_at_bar)} model(s): {detail}.{note}"
            ),
        )

    if not at_bar:
        return ClauseVerdict(
            state=STATE_INCONCLUSIVE,
            evidence=(
                f"No measurable cell was obtained for the bar date "
                f"{BAR_DATE.isoformat()}; the clause was not tested."
            ),
        )

    if elsewhere:
        tested = ", ".join(sorted(at_bar))
        controls = ", ".join(date.isoformat() for date in elsewhere)
        return ClauseVerdict(
            state=STATE_REFUTED,
            evidence=(
                f"{BAR_DATE.isoformat()} returned an all-null "
                f"{PREVIOUS_DAY_VARIABLE} series for every model tested ({tested}), "
                f"while the SAME request shape returned values at {controls}. The "
                "null is the archive's, not the request's."
            ),
        )

    return ClauseVerdict(
        state=STATE_INCONCLUSIVE,
        evidence=(
            "Every cell in this run was all-null, including the controls. With no "
            "positive control the null is equally consistent with a wrong request, "
            "so nothing may be concluded about the archive."
        ),
    )


# ==========================================================================
# The run
# ==========================================================================


@dataclass(frozen=True, slots=True)
class ProbeResult:
    """Everything one execution measured, in the order it measured it."""

    cells: dict[tuple[dt.date, str], CoverageCell]
    exchanges: tuple[ProbeExchange, ...]
    findings: tuple[str, ...]
    dependence: str
    reference_model: str | None
    observations: dict[dt.date, bool]
    boundary: tuple[dt.date, dt.date] | None
    contiguity: str
    contiguity_samples: dict[dt.date, CoverageCell]
    verdict: ClauseVerdict
    aborted: str | None = None
    steps: tuple[CoverageStep, ...] = field(default_factory=tuple)


class _Dispatcher:
    """Dispatch, record, and count -- with budget exhaustion as a hard stop."""

    def __init__(
        self,
        transport: ProbeTransport,
        writer: ProbeEvidenceWriter,
        *,
        pause_seconds: float,
    ) -> None:
        self._transport = transport
        self._writer = writer
        self._pause = pause_seconds
        self.exchanges: list[ProbeExchange] = []
        self.steps: list[CoverageStep] = []
        self.findings: list[str] = []
        self.aborted: str | None = None

    async def send(self, step: CoverageStep) -> CoverageCell | None:
        """One request. Returns its cell, or ``None`` when it measured nothing."""
        if self.aborted is not None:
            return None
        try:
            exchange = await self._transport.probe_get(
                PATH, query=dict(step.query), label=step.label
            )
        except RequestBudgetExceededError as exc:
            self.aborted = f"Budget exhausted before `{step.label}`: {exc}"
            return None
        self.exchanges.append(exchange)
        self.steps.append(step)
        self._writer.record(step.label, exchange)
        if exchange.finding is not None:
            self.findings.append(f"`{step.label}`: {exchange.finding}")
        cell = count_coverage(exchange)
        if cell is None and exchange.finding is None:
            self.findings.append(
                f"`{step.label}`: HTTP {exchange.status_code} carried no "
                f"`{PREVIOUS_DAY_VARIABLE}` series, so it measured nothing. A 2xx is "
                "not an answer."
            )
        if self._pause > 0:
            await asyncio.sleep(self._pause)
        return cell


async def run_probe(
    transport: ProbeTransport,
    writer: ProbeEvidenceWriter,
    *,
    pause_seconds: float = 1.0,
) -> ProbeResult:
    """Matrix, then bisect, then contiguity -- each phase gated on the last.

    A phase whose predecessor produced nothing to work with is SKIPPED rather
    than dispatched: with no covered cell there is no boundary to bisect, and
    spending the remaining budget searching for one would be spending it to
    re-learn a recorded negative.
    """
    dispatcher = _Dispatcher(transport, writer, pause_seconds=pause_seconds)
    cells: dict[tuple[dt.date, str], CoverageCell] = {}

    # -- phase 1: the date x model matrix ---------------------------------
    for step in build_matrix_plan():
        cell = await dispatcher.send(step)
        if cell is not None:
            cells[(step.start, step.model)] = cell

    dependence = classify_dependence(cells)
    reference = choose_reference_model(cells)

    # -- phase 2: bisect the reference model's boundary --------------------
    observations: dict[dt.date, bool] = {}
    boundary: tuple[dt.date, dt.date] | None = None
    if reference is not None and dispatcher.aborted is None:
        observations = {
            date: cell.covered for (date, model), cell in cells.items() if model == reference
        }
        for _ in range(BISECT_BUDGET):
            bracket = bisect_bracket(observations)
            if bracket is None:
                break
            boundary = bracket
            midpoint = next_bisect_date(*bracket)
            if midpoint is None:
                break
            cell = await dispatcher.send(_step(midpoint, reference, phase="bisect"))
            if cell is None:
                break
            cells[(midpoint, reference)] = cell
            observations[midpoint] = cell.covered
        boundary = bisect_bracket(observations)

    # -- phase 3: contiguity strictly inside the covered span --------------
    samples: dict[dt.date, CoverageCell] = {}
    if reference is not None and dispatcher.aborted is None:
        covered_dates = sorted(date for date, flag in observations.items() if flag)
        if len(covered_dates) >= 2:
            for date in contiguity_dates(covered_dates[0], covered_dates[-1], CONTIGUITY_BUDGET):
                cell = await dispatcher.send(_step(date, reference, phase="contiguity"))
                if cell is None:
                    break
                cells[(date, reference)] = cell
                samples[date] = cell

    contiguity = contiguity_of(samples)
    verdict = evaluate_archive_clause(cells, contiguity=contiguity)
    if dispatcher.aborted is not None:
        verdict = ClauseVerdict(
            state=STATE_INCONCLUSIVE,
            evidence=(
                f"The run did not complete: {dispatcher.aborted} A truncated run "
                "cannot close a clause."
            ),
        )

    return ProbeResult(
        cells=cells,
        exchanges=tuple(dispatcher.exchanges),
        findings=tuple(dispatcher.findings),
        dependence=dependence,
        reference_model=reference,
        observations=observations,
        boundary=boundary,
        contiguity=contiguity,
        contiguity_samples=samples,
        verdict=verdict,
        aborted=dispatcher.aborted,
        steps=tuple(dispatcher.steps),
    )


# ==========================================================================
# The report
# ==========================================================================


def _matrix_table(result: ProbeResult) -> list[str]:
    header = "| date | " + " | ".join(f"`{model}`" for model in MATRIX_MODELS) + " |"
    rule = "|---|" + "---|" * len(MATRIX_MODELS)
    rows = [header, rule]
    for date in MATRIX_DATES:
        cells = [
            str(result.cells[(date, model)]) if (date, model) in result.cells else "no cell"
            for model in MATRIX_MODELS
        ]
        rows.append(f"| {date.isoformat()} | " + " | ".join(cells) + " |")
    return rows


def render_report(result: ProbeResult, *, budget: RequestBudget) -> str:
    """The Markdown artifact. Ends with the computed clause verdict."""
    lines: list[str] = [
        "# Open-Meteo archive-coverage bisect (P2 Probe C)",
        "",
        "## EVIDENCE ONLY - NEVER INGEST",
        "",
        "These captures must NEVER be ingested into the production forecast",
        "catalog. Backfilling them under a plausible retrieval timestamp would",
        "be backdating and would violate the point-in-time forecast design.",
        "",
        f"Host: {HOST} (settlement host NOT touched)",
        (
            "Transport: `breezy.ingest.probe_transport.ProbeTransport`, "
            f"max_body_bytes={MAX_BODY_BYTES}"
        ),
        f"Request budget: {budget.limit} hard; spent {budget.spent}.",
        (
            f"Measured variable: `{PREVIOUS_DAY_VARIABLE}` ({SURFACE}), "
            f"{WINDOW_DAYS}-day windows at {PRIMARY_CITY}."
        ),
        "",
        "## 1. Coverage matrix (non-null hours / hours returned)",
        "",
        *_matrix_table(result),
        "",
        f"**Null-ness is a function of: {result.dependence}.**",
        "",
        "## 2. Boundary bisect",
        "",
    ]
    if result.reference_model is None:
        lines.append(
            "SKIPPED: no model returned a single non-null hour in the matrix, so "
            "there is no covered/empty boundary to bisect."
        )
    else:
        lines.append(f"Reference (best-covered) model: `{result.reference_model}`")
        lines.append("")
        lines.append("| date | covered |")
        lines.append("|---|---|")
        for date in sorted(result.observations):
            lines.append(f"| {date.isoformat()} | {'yes' if result.observations[date] else 'no'} |")
        lines.append("")
        if result.boundary is None:
            lines.append(
                "No covered/empty bracket exists for the reference model: every "
                "observation fell on the same side."
            )
        else:
            covered, empty = result.boundary
            lines.append(
                f"Boundary bracketed between {covered.isoformat()} (covered) and "
                f"{empty.isoformat()} (empty) -- {abs((empty - covered).days)} days wide, "
                f"resolution target {BISECT_RESOLUTION_DAYS} days."
            )

    lines.extend(["", "## 3. Contiguity inside the covered span", ""])
    if not result.contiguity_samples:
        lines.append(f"UNSAMPLED ({result.contiguity}): no interior sample was taken.")
    else:
        lines.append("| interior date | coverage |")
        lines.append("|---|---|")
        for date in sorted(result.contiguity_samples):
            lines.append(f"| {date.isoformat()} | {result.contiguity_samples[date]} |")
        lines.append("")
        lines.append(f"**Coverage inside the span is {result.contiguity.upper()}.**")

    lines.extend(
        [
            "",
            "## Exchanges",
            "",
            "| # | label | status | bytes | outcome |",
            "|--:|---|--:|--:|---|",
        ]
    )
    lines.extend(
        f"| {exchange.ordinal} | `{exchange.label}` | {exchange.status_code} "
        f"| {exchange.body_bytes} | {exchange.outcome} |"
        for exchange in result.exchanges
    )

    lines.extend(["", "## Findings", ""])
    if result.findings:
        lines.extend(f"- {finding}" for finding in result.findings)
    else:
        lines.append("None recorded: every dispatched request returned a measurable cell.")

    if result.aborted is not None:
        lines.extend(["", "## Abort", "", result.aborted])

    lines.extend(
        [
            "",
            "## Verdict",
            "",
            result.verdict.evidence,
            "",
            f"VERDICT: {CLAUSE_ARCHIVE} = {result.verdict.state}",
        ]
    )
    return "\n".join(lines) + "\n"


# ==========================================================================
# CLI
# ==========================================================================


def build_transport(*, budget: RequestBudget, user_agent: str) -> ProbeTransport:
    """One transport, allowlisted to this probe's single origin."""
    return ProbeTransport(
        base_url=BASE_URL,
        allowed_hosts=ALLOWED_HOSTS,
        budget=budget,
        max_body_bytes=MAX_BODY_BYTES,
        user_agent=user_agent,
        accept="application/json",
        clock=time.time_ns,
    )


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="P2 Probe C", add_help=True)
    parser.add_argument("--output-directory", required=True)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually dispatch. Without it nothing is sent.",
    )
    return parser.parse_args(list(argv))


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point. Refuses to dispatch without the explicit live unlock."""
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    planned = MATRIX_BUDGET + BISECT_BUDGET + CONTIGUITY_BUDGET

    if os.environ.get(LIVE_ENV_VAR) != "1":
        sys.stderr.write(
            f"REFUSED: {LIVE_ENV_VAR}=1 is required before this probe may dispatch "
            f"any request. Planned steps: at most {planned} (budget {REQUEST_BUDGET}).\n"
        )
        return 2
    if not args.apply:
        sys.stderr.write(
            f"REFUSED: --apply is required. Planned steps: at most {planned} "
            f"(budget {REQUEST_BUDGET}).\n"
        )
        return 2
    if not os.environ.get(USER_AGENT_ENV_VAR):
        sys.stderr.write(f"REFUSED: {USER_AGENT_ENV_VAR} must name a monitored contact.\n")
        return 2

    budget = RequestBudget(limit=REQUEST_BUDGET)
    writer = ProbeEvidenceWriter(Path(args.output_directory))
    transport = build_transport(budget=budget, user_agent=os.environ[USER_AGENT_ENV_VAR])

    result = asyncio.run(run_probe(transport, writer))
    writer.write_report("PROBE_REPORT.md", render_report(result, budget=budget))
    sys.stderr.write(
        f"Probe C finished: {budget.spent}/{budget.limit} requests spent, "
        f"{len(result.exchanges)} exchanges recorded in {args.output_directory}. "
        f"VERDICT: {CLAUSE_ARCHIVE} = {result.verdict.state}\n"
    )
    return 1 if result.aborted is not None else 0


if __name__ == "__main__":  # pragma: no cover - operator entry point
    raise SystemExit(main())
