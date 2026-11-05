#!/usr/bin/env python
"""P2 Probe B -- does IEM AFOS serve usable *forecast* PILs (AFD, ZFP)?

Authority: ``docs/plans/DATA_CAPTURE_AND_RISK_PLAN.md`` section 4.P2.

EVIDENCE ONLY -- NEVER INGEST. Payloads carry the ``.probe.json`` suffix no
production loader reads.

The repo already retrieves CLI (observation) products through this path, so
transport and courtesy discipline exist. What is UNPROBED is whether the same
path serves *forecast* products in a form a deterministic parser can use.

THE PRE-REGISTERED PASS BAR, AS A COMPUTED VERDICT
--------------------------------------------------
:func:`evaluate_verdict` is the bar. It is a pure function over a
:class:`ParseCensus`, so the outcome is arithmetic rather than judgement, and
it is fixed here BEFORE any payload is seen. PASS requires ALL of:

* at least :data:`MIN_PRODUCTS` (50) products,
* spanning at least :data:`MIN_SITES` (2) sites,
* a numeric daily high extracted by a deterministic parser from at least
  :data:`MIN_PARSE_RATE` (90%) of them,
* issuance time recoverable from the WMO header on every product,
* every product attributable to the office that serves the settlement station.

ATTRIBUTION IS EVALUATED AS AN **OFFICE** MATCH, AND SAYS SO
-----------------------------------------------------------
The plan's third clause is phrased "attributable to a zone containing the
settlement station". True UGC-zone geometry is **not** in the site registry,
and `sites.toml` forbids deriving an identifier, so inventing a zone -> station
mapping is not available. This probe therefore evaluates the clause as an
OFFICE match -- the registry's ``issuing_office`` against the WMO header's
``KXXX`` -- and the report states that limitation rather than reporting a
weaker check under the stronger name.

**Anything less is a documented FAIL, and the correct response to a FAIL is to
STOP.** Writing a forecast-text parser to rescue a failing rate is a research
project masquerading as an ingestion increment; the plan says so and this
module is written so that outcome cannot be argued around.

CONTAINMENT: identical to Probe A -- hardened subclass transport, single-host
allowlist, per-instance body cap, hard request budget, GET only, refuses to
dispatch without ``BREEZY_LIVE=1`` and ``--apply``.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import os
import re
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from breezy.ingest.probe_transport import (
    ProbeEvidenceWriter,
    ProbeExchange,
    ProbeTransport,
    RequestBudget,
    RequestBudgetExceededError,
)
from breezy.registry.sites import default_registry

HOST: str = "mesonet.agron.iastate.edu"
BASE_URL: str = f"https://{HOST}"
ALLOWED_HOSTS: frozenset[str] = frozenset({HOST})

#: Per-INSTANCE cap. An AFOS text bundle of ~40 forecast products is far
#: larger than a single CLI product, and far smaller than this.
MAX_BODY_BYTES: int = 4 * 1024 * 1024

#: HARD. The (N+1)th request raises and aborts the run.
REQUEST_BUDGET: int = 12

LIVE_ENV_VAR: str = "BREEZY_LIVE"
USER_AGENT_ENV_VAR: str = "BREEZY_USER_AGENT"

VENUE: str = "polymarket_us"

#: The forecast product types under test. AFD is the forecaster discussion;
#: ZFP is the zone forecast product, which is where a numeric daily high would
#: live if it lives anywhere.
FORECAST_PIL_TYPES: tuple[str, ...] = ("AFD", "ZFP")

#: Sites probed. At least two, per the pre-registered bar.
PROBE_CITIES: tuple[str, ...] = ("NYC", "MDW")

# -- the pre-registered bar -------------------------------------------------

MIN_PRODUCTS: int = 50
MIN_SITES: int = 2
MIN_PARSE_RATE: float = 0.90

# -- deterministic parsing --------------------------------------------------

#: The WMO abbreviated heading line: ``FXUS61 KOKX 301130``. Issuance is the
#: trailing DDHHMM group. If this is not recoverable, the product cannot be
#: point-in-time attributed and the bar's issuance clause fails.
_WMO_HEADER_RE = re.compile(
    r"^(?P<designator>[A-Z]{4}\d{2})\s+(?P<office>K[A-Z]{3})\s+(?P<ddhhmm>\d{6})\s*$",
    re.MULTILINE,
)

#: A numeric daily high, in the two shapes NWS zone forecasts actually use.
#: Deterministic and narrow ON PURPOSE: a permissive pattern would inflate the
#: parse rate with matches that are not highs, which is the exact way a FAIL
#: gets talked into a PASS.
_DAILY_HIGH_RES: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bHIGHS?\s+(?:NEAR|AROUND|IN THE(?: (?:LOWER|MID|UPPER))?)?\s*(\d{1,3})\b"),
    re.compile(r"\bHIGH\s+(?:NEAR\s+)?(\d{1,3})\b"),
    re.compile(r"\bMAX\s+TEMP(?:ERATURE)?\s+(?:NEAR\s+)?(\d{1,3})\b"),
)

#: The end-of-product separator IEM emits between concatenated products.
_PRODUCT_SEPARATOR = "\x03"


@dataclass(frozen=True, slots=True)
class ParseCensus:
    """What a deterministic pass over the captured products actually found.

    Counts only. No payload, no judgement -- so :func:`evaluate_verdict` is a
    pure arithmetic statement about the pre-registered bar.
    """

    products: int
    sites: int
    highs_extracted: int
    issuance_recoverable: int
    office_attributable: int


@dataclass(frozen=True, slots=True)
class Verdict:
    """The computed PASS/FAIL, with every failing clause named."""

    passed: bool
    parse_rate: float
    failures: tuple[str, ...]


def evaluate_verdict(census: ParseCensus) -> Verdict:
    """Apply the pre-registered bar to ``census``. Pure; no I/O; no judgement.

    Zero products is a FAIL with a parse rate of 0.0, not a division by zero
    and not a vacuous PASS -- "we captured nothing, so nothing failed to parse"
    is precisely the reasoning this function exists to make impossible.
    """
    parse_rate = census.highs_extracted / census.products if census.products else 0.0
    failures: list[str] = []
    if census.products < MIN_PRODUCTS:
        failures.append(
            f"products: {census.products} < {MIN_PRODUCTS} required by the pre-registered bar"
        )
    if census.sites < MIN_SITES:
        failures.append(f"sites: {census.sites} < {MIN_SITES} required")
    if parse_rate < MIN_PARSE_RATE:
        failures.append(
            f"parse_rate: {parse_rate:.4f} < {MIN_PARSE_RATE} required "
            f"({census.highs_extracted}/{census.products} numeric daily highs)"
        )
    if census.products == 0 or census.issuance_recoverable < census.products:
        failures.append(
            f"issuance_time: recoverable from the WMO header on "
            f"{census.issuance_recoverable}/{census.products} products; all are required"
        )
    if census.products == 0 or census.office_attributable < census.products:
        failures.append(
            f"office_attribution: {census.office_attributable}/{census.products} products "
            "whose WMO-header office matches the registry `issuing_office` for the "
            "settlement station; all are required"
        )
    return Verdict(passed=not failures, parse_rate=parse_rate, failures=tuple(failures))


def split_products(raw_text: str) -> tuple[str, ...]:
    """Split an IEM AFOS text bundle into individual products."""
    products: list[str] = []
    for chunk in raw_text.split(_PRODUCT_SEPARATOR):
        stripped = chunk.strip("\n\r\x01 ")
        if stripped:
            products.append(stripped)
    return tuple(products)


def wmo_issuance(product_text: str) -> str | None:
    """Return the ``DDHHMM`` issuance group from the WMO header, or ``None``."""
    match = _WMO_HEADER_RE.search(product_text)
    return None if match is None else match.group("ddhhmm")


def extract_daily_high(product_text: str) -> int | None:
    """Return a numeric daily high, deterministically, or ``None``.

    Narrow on purpose. A parser that "usually finds something" produces a
    parse rate that measures the parser's optimism rather than the product's
    structure.
    """
    upper = product_text.upper()
    for pattern in _DAILY_HIGH_RES:
        match = pattern.search(upper)
        if match is not None:
            value = int(match.group(1))
            if -80 <= value <= 140:
                return value
    return None


def office_attributable(product_text: str, issuing_office: str) -> bool:
    """Is this product attributable to the office that serves the station?

    The registry's ``issuing_office`` (e.g. ``KOKX``) is the only source of
    truth. A geographically nearby office is NEVER an acceptable substitute --
    the registry says so at the top of ``sites.toml`` and this probe honours it.
    This is an OFFICE match, not UGC-zone containment; see the module header.
    """
    match = _WMO_HEADER_RE.search(product_text)
    return match is not None and match.group("office") == issuing_office


@dataclass(frozen=True, slots=True)
class ProbeStep:
    """One labelled AFOS retrieval.

    ``baseline`` marks the step whose failure generalises to the whole plan;
    see :func:`baseline_failure`.
    """

    label: str
    city: str
    path: str
    query: Mapping[str, str]
    rationale: str
    baseline: bool = False


@dataclass(frozen=True, slots=True)
class StepOutcome:
    """What ONE dispatched retrieval actually established.

    ``products`` is empty for every non-2xx, unconditionally: a response the
    origin refused carries no datum, and an error body that happens to contain
    forecast-shaped text must never reach the census. That is the exact defect
    Probe A's first live run shipped -- 22 HTTP 404s reported as ``ok``.
    """

    label: str
    city: str
    status_code: int
    succeeded: bool
    body_bytes: int
    products: tuple[str, ...]
    reason: str | None

    @property
    def wmo_headed(self) -> int:
        """How many chunks carry a WMO abbreviated heading.

        The test of whether the SERVED REPRESENTATION is an AFOS product
        stream at all -- distinct from whether those products parse, which is
        what the bar measures.
        """
        return sum(1 for chunk in self.products if wmo_issuance(chunk) is not None)


def evaluate_step(step: ProbeStep, exchange: ProbeExchange) -> StepOutcome:
    """Classify one exchange. A non-2xx yields no product, ever."""
    if not exchange.succeeded:
        status = f"HTTP {exchange.status_code}" if exchange.status_code else f"`{exchange.outcome}`"
        return StepOutcome(
            label=step.label,
            city=step.city,
            status_code=exchange.status_code,
            succeeded=False,
            body_bytes=exchange.body_bytes,
            products=(),
            reason=(
                f"{status} -- a non-2xx response carries no product and contributes "
                "nothing to the census"
            ),
        )
    body = exchange.text or ""
    chunks = split_products(body)
    outcome = StepOutcome(
        label=step.label,
        city=step.city,
        status_code=exchange.status_code,
        succeeded=True,
        body_bytes=exchange.body_bytes,
        products=chunks,
        reason=None,
    )
    if not chunks:
        return replace(
            outcome,
            reason=(
                "2xx, but the body carried no AFOS product the deterministic "
                "splitter could recognise (an empty result set for this PIL)"
            ),
        )
    if outcome.wmo_headed == 0:
        return replace(
            outcome,
            reason=(
                f"2xx and {exchange.body_bytes} bytes, but no chunk carried a WMO "
                "abbreviated heading -- the served representation is not a parseable "
                "AFOS product stream"
            ),
        )
    return outcome


def baseline_failure(outcome: StepOutcome) -> str | None:
    """Why, if at all, this BASELINE outcome forbids dispatching the rest.

    Two failures generalise from the baseline to every later step, so spending
    the budget on them would only re-learn the same negative:

    * a non-2xx -- the endpoint or the ``fmt=text`` representation is refused;
    * a 2xx whose body is non-empty but carries no WMO-headed product -- the
      served representation is unusable, and every later step gets the same
      representation.

    An EMPTY 2xx does **not** abort: an empty result set is a fact about one
    PIL in one window, not about the endpoint, and aborting on it would let one
    quiet PIL suppress the second site the bar requires.
    """
    if not outcome.succeeded:
        return f"non-2xx on the baseline ({outcome.reason})"
    if outcome.body_bytes > 0 and outcome.wmo_headed == 0:
        return (
            f"the baseline served {outcome.body_bytes} bytes carrying no WMO-headed "
            f"AFOS product ({outcome.reason})"
        )
    return None


def census_from_outcomes(
    outcomes: Sequence[StepOutcome], offices: Mapping[str, str]
) -> ParseCensus:
    """Build a :class:`ParseCensus` from evaluated step outcomes.

    ``offices`` maps **city** -> registry ``issuing_office``. Sites are counted
    by CITY, never by step label: the bar says "spanning >= 2 sites", and two
    PIL types retrieved for one city are one site.
    """
    products = 0
    highs = 0
    issuance = 0
    attributed = 0
    sites: set[str] = set()
    for outcome in outcomes:
        if not outcome.products:
            continue
        office = offices[outcome.city]
        sites.add(outcome.city)
        for chunk in outcome.products:
            products += 1
            if extract_daily_high(chunk) is not None:
                highs += 1
            if wmo_issuance(chunk) is not None:
                issuance += 1
            if office_attributable(chunk, office):
                attributed += 1
    return ParseCensus(
        products=products,
        sites=len(sites),
        highs_extracted=highs,
        issuance_recoverable=issuance,
        office_attributable=attributed,
    )


def build_request_plan(*, days: int = 21, limit: int = 60) -> tuple[ProbeStep, ...]:
    """One retrieval per (city, forecast PIL type), inside the hard budget."""
    registry = default_registry()
    end = dt.datetime.now(tz=dt.UTC).date()
    start = end - dt.timedelta(days=days)
    steps: list[ProbeStep] = []
    for city in PROBE_CITIES:
        office = registry.settlement_site(VENUE, city).issuing_office
        for pil_type in FORECAST_PIL_TYPES:
            steps.append(
                ProbeStep(
                    label=f"{pil_type.lower()}_{city.lower()}",
                    city=city,
                    path="/cgi-bin/afos/retrieve.py",
                    query={
                        # `fmt=text` not `fmt=zip`: the hardened transport
                        # decodes strict UTF-8 and never handles an archive.
                        "fmt": "text",
                        "order": "asc",
                        "pil": f"{pil_type}{office[1:]}",
                        "sdate": f"{start.isoformat()}T00:00Z",
                        "edate": f"{end.isoformat()}T00:00Z",
                        "limit": str(limit),
                    },
                    rationale=(
                        f"Does AFOS serve {pil_type} for {office} at all, and in a "
                        "shape a deterministic parser can read?"
                    ),
                    # The FIRST step is the baseline: whether AFOS serves any
                    # WMO-headed forecast product over `fmt=text` at all is a
                    # fact about the endpoint, not about one PIL.
                    baseline=not steps,
                )
            )
    return tuple(steps)


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    """What the plan established, including what it deliberately skipped."""

    exchanges: tuple[ProbeExchange, ...]
    outcomes: tuple[StepOutcome, ...]
    aborted: str | None
    skipped: tuple[str, ...]


async def execute(
    transport: ProbeTransport,
    writer: ProbeEvidenceWriter,
    plan: Sequence[ProbeStep],
    *,
    pause_seconds: float = 2.0,
) -> ExecutionResult:
    """Dispatch the plan, recording every exchange.

    Aborts on budget exhaustion, and on a failed BASELINE step -- see
    :func:`baseline_failure` for exactly which baseline results generalise and
    which do not. IEM is a courtesy-access public archive: one request at a
    time, ``pause_seconds`` apart, no retry.
    """
    exchanges: list[ProbeExchange] = []
    outcomes: list[StepOutcome] = []
    aborted: str | None = None
    skipped: tuple[str, ...] = ()
    for index, step in enumerate(plan):
        try:
            exchange = await transport.probe_get(step.path, query=step.query, label=step.label)
        except RequestBudgetExceededError as exc:
            aborted = f"Budget exhausted before `{step.label}`: {exc}"
            skipped = tuple(later.label for later in plan[index:])
            break
        exchanges.append(exchange)
        writer.record(step.label, exchange)
        outcome = evaluate_step(step, exchange)
        outcomes.append(outcome)
        if step.baseline:
            failure = baseline_failure(outcome)
            if failure is not None:
                remaining = len(plan) - index - 1
                aborted = (
                    f"BASELINE step `{step.label}` failed: {failure}. The remaining "
                    f"{remaining} step(s) are SKIPPED -- dispatching them would spend "
                    "the request budget re-learning the same negative."
                )
                skipped = tuple(later.label for later in plan[index + 1 :])
                break
        if pause_seconds > 0 and index + 1 < len(plan):
            await asyncio.sleep(pause_seconds)
    return ExecutionResult(
        exchanges=tuple(exchanges),
        outcomes=tuple(outcomes),
        aborted=aborted,
        skipped=skipped,
    )


def _outcome_rows(exchanges: Sequence[ProbeExchange]) -> list[str]:
    return [
        f"| {exchange.ordinal} | `{exchange.label}` | {exchange.status_code} "
        f"| {exchange.body_bytes} | {exchange.outcome} |"
        for exchange in exchanges
    ]


def _bar_row(clause: str, measured: str, bar: str, satisfied: bool) -> str:
    return f"| {clause} | {measured} | {bar} | {'PASS' if satisfied else 'FAIL'} |"


def render_report(
    census: ParseCensus,
    verdict: Verdict,
    *,
    execution: ExecutionResult,
    plan: Sequence[ProbeStep],
    budget: RequestBudget,
) -> str:
    """Render the evidence document, ending in the computed VERDICT line.

    Four properties Probe A's first live report lacked: every non-2xx appears
    under Findings, a step counts only when a 2xx carried a product, the
    skipped steps are named with the reason, and the document ENDS with an
    explicit ``VERDICT:`` derived from the counted set.
    """
    lines: list[str] = [
        "# IEM AFOS forecast-PIL probe (P2 Probe B)",
        "",
        "## EVIDENCE ONLY - NEVER INGEST",
        "",
        "These captures must NEVER be ingested into any production catalog.",
        "",
        "**A forecast archive cannot produce a backtest, because a backtest also",
        "needs prices, and prices are forward-only and permanently",
        "unrecoverable.** What a forecast archive produces is a forecast-error /",
        "calibration dataset.",
        "",
        f"Host: `{HOST}` (settlement host NOT touched)",
        (
            "Transport: `breezy.ingest.probe_transport.ProbeTransport`, "
            f"max_body_bytes={MAX_BODY_BYTES}"
        ),
        f"Request budget: {budget.limit} hard; spent {budget.spent}.",
        f"Planned steps: {len(plan)}; dispatched: {len(execution.exchanges)}.",
        "",
        "## Outcomes",
        "",
        "| # | label | status | bytes | outcome |",
        "|--:|---|--:|--:|---|",
    ]
    if execution.exchanges:
        lines.extend(_outcome_rows(execution.exchanges))
    else:
        lines.append("| - | *none dispatched* | - | - | - |")
    lines.append("")

    if execution.aborted is not None:
        lines.extend(
            [
                "## RUN ABORTED",
                "",
                execution.aborted,
                "",
                (
                    f"Steps skipped: {len(execution.skipped)} of {len(plan)} planned -- "
                    + (", ".join(f"`{label}`" for label in execution.skipped) or "none")
                ),
                "",
            ]
        )

    lines.extend(["## Step coverage", ""])
    if not execution.outcomes:
        lines.append("- no step was dispatched, so no step yielded a product")
    for outcome in execution.outcomes:
        if outcome.products:
            detail = (
                f"YIELDED {len(outcome.products)} product(s) for {outcome.city} "
                f"(WMO-headed: {outcome.wmo_headed})"
            )
            if outcome.reason:
                detail += f" -- partial: {outcome.reason}"
        else:
            detail = f"NO PRODUCT -- {outcome.reason or 'no evidence'}"
        lines.append(f"- `{outcome.label}`: {detail}")

    findings = [
        exchange
        for exchange in execution.exchanges
        if exchange.finding is not None or not exchange.succeeded
    ]
    lines.extend(["", "## Findings", ""])
    if not findings:
        lines.append("- No non-2xx response and no transport alarm was recorded.")
    for exchange in findings:
        detail = exchange.finding or f"HTTP {exchange.status_code}"
        body = (exchange.text or "").strip().replace("\n", " ")[:200]
        lines.append(
            f"- `{exchange.label}` (HTTP {exchange.status_code}): {detail}"
            + (f" Body: `{body}`" if body else "")
        )
    empty = [
        outcome for outcome in execution.outcomes if outcome.succeeded and not outcome.products
    ]
    for outcome in empty:
        lines.append(
            f"- `{outcome.label}` (HTTP {outcome.status_code}): {outcome.reason} "
            "-- a served response is not a served product."
        )

    counted = census.products > 0
    lines.extend(
        [
            "",
            "## Pre-registered bar",
            "",
            "| clause | measured | bar | state |",
            "|---|---|---|---|",
            _bar_row(
                "products",
                str(census.products),
                f">= {MIN_PRODUCTS}",
                census.products >= MIN_PRODUCTS,
            ),
            _bar_row(
                "sites (distinct cities)",
                str(census.sites),
                f">= {MIN_SITES}",
                census.sites >= MIN_SITES,
            ),
            _bar_row(
                "parse rate",
                f"{verdict.parse_rate:.4f} ({census.highs_extracted}/{census.products})",
                f">= {MIN_PARSE_RATE}",
                verdict.parse_rate >= MIN_PARSE_RATE,
            ),
            _bar_row(
                "issuance from WMO header",
                f"{census.issuance_recoverable}/{census.products}",
                "all",
                counted and census.issuance_recoverable == census.products,
            ),
            _bar_row(
                "office attribution",
                f"{census.office_attributable}/{census.products}",
                "all",
                counted and census.office_attributable == census.products,
            ),
            "",
            (
                f"Parse rate, as a number: **{verdict.parse_rate:.4f}** "
                f"({census.highs_extracted} numeric daily highs from "
                f"{census.products} products)."
            ),
            "",
            "### What the attribution clause actually checked",
            "",
            "The plan phrases this clause as containment in a UGC zone. True UGC-zone",
            "geometry is NOT in the site registry, and `sites.toml` forbids deriving an",
            "identifier, so no zone -> station mapping was invented. What was checked is",
            "an OFFICE match: the WMO header's `KXXX` against the registry's",
            "`issuing_office` for the settlement station. That is weaker than zone",
            "containment and is reported under its own name rather than the stronger one.",
            "",
        ]
    )

    if verdict.failures:
        lines.extend(["### Failing clauses", ""])
        lines.extend(f"- {failure}" for failure in verdict.failures)
        lines.extend(
            [
                "",
                "**The correct response to this FAIL is to STOP.** Writing a",
                "forecast-text parser to lift the rate is a research project",
                "masquerading as an ingestion increment (plan section 4.P2).",
                "",
            ]
        )

    lines.extend(["", f"VERDICT: {'PASS' if verdict.passed else 'FAIL'}"])
    return "\n".join(lines) + "\n"


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, add_help=True)
    parser.add_argument("--output-directory", required=True)
    parser.add_argument("--apply", action="store_true")
    return parser.parse_args(list(argv))


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point. Refuses to dispatch without the explicit live unlock."""
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    plan = build_request_plan()

    if os.environ.get(LIVE_ENV_VAR) != "1":
        sys.stderr.write(
            f"REFUSED: {LIVE_ENV_VAR}=1 is required before this probe may dispatch "
            f"any request. Planned steps: {len(plan)} (budget {REQUEST_BUDGET}).\n"
        )
        return 2
    if not args.apply:
        sys.stderr.write(f"REFUSED: --apply is required. Planned steps: {len(plan)}.\n")
        return 2
    if not os.environ.get(USER_AGENT_ENV_VAR):
        sys.stderr.write(f"REFUSED: {USER_AGENT_ENV_VAR} must name a monitored contact.\n")
        return 2

    registry = default_registry()
    budget = RequestBudget(limit=REQUEST_BUDGET)
    transport = ProbeTransport(
        base_url=BASE_URL,
        allowed_hosts=ALLOWED_HOSTS,
        budget=budget,
        max_body_bytes=MAX_BODY_BYTES,
        user_agent=os.environ[USER_AGENT_ENV_VAR],
        accept="text/plain",
        clock=time.time_ns,
    )
    writer = ProbeEvidenceWriter(Path(args.output_directory))
    execution = asyncio.run(execute(transport, writer, plan))

    offices = {city: registry.settlement_site(VENUE, city).issuing_office for city in PROBE_CITIES}
    census = census_from_outcomes(execution.outcomes, offices)
    verdict = evaluate_verdict(census)
    writer.write_report(
        "PROBE_REPORT.md",
        render_report(census, verdict, execution=execution, plan=plan, budget=budget),
    )
    sys.stderr.write(
        f"Probe B finished: {budget.spent}/{budget.limit} requests spent, "
        f"{len(execution.exchanges)} exchanges, parse_rate={verdict.parse_rate:.4f}, "
        f"VERDICT={'PASS' if verdict.passed else 'FAIL'}.\n"
    )
    if execution.aborted is not None:
        return 1
    return 0 if verdict.passed else 3


if __name__ == "__main__":  # pragma: no cover - operator entry point
    raise SystemExit(main())
