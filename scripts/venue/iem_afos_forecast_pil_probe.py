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
* every product attributable to a zone containing the settlement station.

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
from dataclasses import dataclass
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
    zone_attributable: int


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
    if census.products == 0 or census.zone_attributable < census.products:
        failures.append(
            f"zone_attribution: {census.zone_attributable}/{census.products} products "
            "attributable to a zone containing the settlement station; all are required"
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


def zone_attributable(product_text: str, issuing_office: str) -> bool:
    """Is this product attributable to the office that serves the station?

    The registry's ``issuing_office`` (e.g. ``KOKX``) is the only source of
    truth. A geographically nearby office is NEVER an acceptable substitute --
    the registry says so at the top of ``sites.toml`` and this probe honours it.
    """
    match = _WMO_HEADER_RE.search(product_text)
    return match is not None and match.group("office") == issuing_office


def census_from_payloads(payloads: Mapping[str, str], offices: Mapping[str, str]) -> ParseCensus:
    """Build a :class:`ParseCensus` from ``{city: raw_bundle_text}``.

    ``offices`` maps city -> registry ``issuing_office``. Both are passed in so
    this function is pure and unit-testable without a network or a registry.
    """
    products = 0
    highs = 0
    issuance = 0
    zoned = 0
    sites: set[str] = set()
    for city, raw_text in payloads.items():
        office = offices[city]
        chunks = split_products(raw_text)
        if chunks:
            sites.add(city)
        for chunk in chunks:
            products += 1
            if extract_daily_high(chunk) is not None:
                highs += 1
            if wmo_issuance(chunk) is not None:
                issuance += 1
            if zone_attributable(chunk, office):
                zoned += 1
    return ParseCensus(
        products=products,
        sites=len(sites),
        highs_extracted=highs,
        issuance_recoverable=issuance,
        zone_attributable=zoned,
    )


@dataclass(frozen=True, slots=True)
class ProbeStep:
    """One labelled AFOS retrieval."""

    label: str
    city: str
    path: str
    query: Mapping[str, str]
    rationale: str


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
                )
            )
    return tuple(steps)


def render_report(
    census: ParseCensus, verdict: Verdict, *, budget: RequestBudget, aborted: str | None
) -> str:
    """Render the evidence document, verdict first."""
    lines = [
        "# IEM AFOS forecast-PIL probe (P2 Probe B)",
        "",
        "## EVIDENCE ONLY - NEVER INGEST",
        "",
        "These captures must NEVER be ingested into any production catalog.",
        "",
        "**A forecast archive cannot produce a backtest, because a backtest also",
        "needs prices, and prices are forward-only and permanently",
        "unrecoverable.**",
        "",
        f"Host: `{HOST}` (settlement host NOT touched)",
        f"Request budget: {budget.limit} hard; spent {budget.spent}.",
        "",
        "## VERDICT (pre-registered, computed)",
        "",
        f"**{'PASS' if verdict.passed else 'FAIL'}**",
        "",
        f"- products: {census.products} (bar: >= {MIN_PRODUCTS})",
        f"- sites: {census.sites} (bar: >= {MIN_SITES})",
        f"- parse rate: {verdict.parse_rate:.4f} (bar: >= {MIN_PARSE_RATE})",
        f"- issuance recoverable: {census.issuance_recoverable}/{census.products} (bar: all)",
        f"- zone attributable: {census.zone_attributable}/{census.products} (bar: all)",
        "",
    ]
    if verdict.failures:
        lines.append("### Failing clauses")
        lines.append("")
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
    if aborted is not None:
        lines.extend(["## RUN ABORTED", "", aborted, ""])
    return "\n".join(lines) + "\n"


async def execute(
    transport: ProbeTransport,
    writer: ProbeEvidenceWriter,
    plan: Sequence[ProbeStep],
    *,
    pause_seconds: float = 2.0,
    sleep_between: bool = True,
) -> tuple[tuple[ProbeExchange, ...], dict[str, str], str | None]:
    """Dispatch the plan, recording every exchange. Abort on budget exhaustion."""
    exchanges: list[ProbeExchange] = []
    payloads: dict[str, str] = {}
    aborted: str | None = None
    for index, step in enumerate(plan):
        try:
            exchange = await transport.probe_get(step.path, query=step.query, label=step.label)
        except RequestBudgetExceededError as exc:
            aborted = f"Budget exhausted before `{step.label}`: {exc}"
            break
        exchanges.append(exchange)
        writer.record(step.label, exchange)
        if exchange.text is not None:
            payloads[step.label] = exchange.text
        if sleep_between and index + 1 < len(plan):
            await asyncio.sleep(pause_seconds)
    return tuple(exchanges), payloads, aborted


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
    exchanges, payloads, aborted = asyncio.run(execute(transport, writer, plan))

    offices = {
        step.label: registry.settlement_site(VENUE, step.city).issuing_office for step in plan
    }
    census = census_from_payloads(payloads, offices)
    verdict = evaluate_verdict(census)
    writer.write_report(
        "PROBE_REPORT.md", render_report(census, verdict, budget=budget, aborted=aborted)
    )
    sys.stderr.write(
        f"Probe B finished: {budget.spent}/{budget.limit} requests spent, "
        f"{len(exchanges)} exchanges, verdict={'PASS' if verdict.passed else 'FAIL'}.\n"
    )
    if aborted is not None:
        return 1
    return 0 if verdict.passed else 3


if __name__ == "__main__":  # pragma: no cover - operator entry point
    raise SystemExit(main())
