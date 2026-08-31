#!/usr/bin/env python
"""P2 Probe A -- read-only evidence probe of Open-Meteo `/v1/previous-runs`.

Authority: ``docs/plans/DATA_CAPTURE_AND_RISK_PLAN.md`` section 4.P2. This
probe decides OQ-2, which gates an irreversible Arrow schema (I-4's first
write), so its output is evidence and nothing else.

EVIDENCE ONLY -- NEVER INGEST. Every payload this script writes carries the
``.probe.json`` suffix that no production loader reads, and lands in a
directory whose README repeats the rule. A captured forecast payload
backfilled under a plausible retrieval timestamp would be backdating and would
destroy the point-in-time property the whole forecast design rests on.

WHAT IT MUST ANSWER
-------------------
Nine pre-registered questions (:data:`QUESTIONS`), each mapped to at least one
labelled request in :func:`build_request_plan` so coverage is computable rather
than asserted. Q4 -- *valid-time or run-time anchored* -- is the whole
lookahead question. ``WEATHER_INGESTION_PROPOSAL.md:159`` asserts an answer;
this probe exists to CONFIRM it, not to inherit it.

CONTAINMENT
-----------
* Transport is :class:`breezy.ingest.probe_transport.ProbeTransport`, a
  subclass of the hardened ``breezy.ingest.http.HttpTransport``. No other HTTP
  client is imported (AST-asserted).
* ``allowed_hosts`` is this probe's host alone; the settlement origin is
  refused by the transport's constructor.
* ``max_body_bytes`` is per-instance. No global body-cap lever is touched and
  ``DEFAULT_ALLOWED_HOSTS`` is not widened (plan section 1.2 item 10).
* :data:`REQUEST_BUDGET` is hard: the (N+1)th request raises and aborts.
* The run refuses to start without ``BREEZY_LIVE=1`` and ``--apply``.

Licence capture (Q8): the operator closed the licence gate on 2026-08-31
(*"open mateo doesn't require a license, we're using the freely accessible
API"*). The text is still captured as a record of what the endpoint said on
the day we relied on it. Note honestly: the terms page is on a DIFFERENT host,
which is deliberately not allowlisted, so what is capturable here is whatever
the API origin itself serves. If nothing licence-bearing is served, THAT is
the finding -- widening the allowlist to chase it is not an option.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import os
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

HOST: str = "api.open-meteo.com"
BASE_URL: str = f"https://{HOST}"
ALLOWED_HOSTS: frozenset[str] = frozenset({HOST})

#: Per-INSTANCE cap. Open-Meteo hourly payloads across many variables are the
#: largest thing this probe asks for; Q9 measures the real sizes so a
#: production client can be capped from evidence rather than from a guess.
MAX_BODY_BYTES: int = 512 * 1024

#: HARD. The (N+1)th request raises and aborts the run.
REQUEST_BUDGET: int = 24

DEFAULT_OUTPUT_DIRECTORY: str = "open_meteo_previous_runs_probe"

LIVE_ENV_VAR: str = "BREEZY_LIVE"
USER_AGENT_ENV_VAR: str = "BREEZY_USER_AGENT"

#: The nine pre-registered questions, verbatim from the plan.
QUESTIONS: tuple[str, ...] = (
    "q1_unkeyed_and_on_which_host",
    "q2_variable_naming_and_real_max_n",
    "q3_archive_depth_for_one_site",
    "q4_valid_time_or_run_time_anchored",
    "q5_observable_publication_lag",
    "q6_values_ever_restated",
    "q7_accepted_model_identifiers",
    "q8_licence_terms_text_verbatim",
    "q9_response_sizes_for_a_body_cap",
)

#: The site whose archive depth and anchoring are probed in detail. One site,
#: per the plan; the registry is the only source of coordinates and this probe
#: never invents one.
PRIMARY_CITY: str = "NYC"
SECONDARY_CITY: str = "SFO"
VENUE: str = "polymarket_us"

_MODEL_IDENTIFIERS: tuple[str, ...] = (
    "best_match",
    "ecmwf_ifs025",
    "gfs_seamless",
    "icon_seamless",
    "meteofrance_seamless",
)


@dataclass(frozen=True, slots=True)
class ProbeStep:
    """One labelled request, and which pre-registered questions it serves.

    ``questions`` is what makes coverage computable: a test asserts the union
    over the plan equals :data:`QUESTIONS`, so a question cannot be quietly
    dropped from the probe while remaining in the report.
    """

    label: str
    path: str
    query: Mapping[str, str]
    questions: tuple[str, ...]
    rationale: str


def _coordinates(city: str) -> tuple[str, str]:
    coords = default_registry().enrichment_coordinates(VENUE, city)
    return (f"{coords.lat:.5f}", f"{coords.lon:.5f}")


def _previous_day_variables(count: int) -> str:
    names = ["temperature_2m_max"]
    names.extend(f"temperature_2m_max_previous_day{index}" for index in range(1, count + 1))
    return ",".join(names)


def build_request_plan() -> tuple[ProbeStep, ...]:
    """The full pre-registered request plan, in dispatch order.

    Every step is a GET. The plan is built ONCE and its length is asserted
    against :data:`REQUEST_BUDGET` by test, so an over-spend is impossible to
    introduce by adding a step without also raising the ceiling deliberately.
    """
    lat, lon = _coordinates(PRIMARY_CITY)
    lat2, lon2 = _coordinates(SECONDARY_CITY)
    today = dt.datetime.now(tz=dt.UTC).date()
    recent_start = (today - dt.timedelta(days=8)).isoformat()
    recent_end = (today - dt.timedelta(days=2)).isoformat()

    base: dict[str, str] = {"latitude": lat, "longitude": lon, "timezone": "UTC"}

    steps: list[ProbeStep] = [
        ProbeStep(
            label="q1_baseline_unkeyed",
            path="/v1/previous-runs",
            query={**base, "daily": _previous_day_variables(3)},
            questions=("q1_unkeyed_and_on_which_host", "q9_response_sizes_for_a_body_cap"),
            rationale=(
                "Does the endpoint answer at all with NO key, on this host? "
                "A 401/403 here settles Q1 negatively and Branch H closes."
            ),
        ),
        ProbeStep(
            label="q2_previous_day_7",
            path="/v1/previous-runs",
            query={**base, "daily": _previous_day_variables(7)},
            questions=("q2_variable_naming_and_real_max_n",),
            rationale="Confirms the documented naming and that N=7 is served.",
        ),
        ProbeStep(
            label="q2_previous_day_boundary_probe",
            path="/v1/previous-runs",
            query={**base, "daily": "temperature_2m_max_previous_day8"},
            questions=("q2_variable_naming_and_real_max_n",),
            rationale=(
                "The REAL maximum N. An error payload here typically names the "
                "accepted range, which is the answer we want rather than a guess."
            ),
        ),
        ProbeStep(
            label="q2_previous_day_far_boundary",
            path="/v1/previous-runs",
            query={**base, "daily": "temperature_2m_max_previous_day16"},
            questions=("q2_variable_naming_and_real_max_n",),
            rationale="A second, clearly-out-of-range N to disambiguate the error shape.",
        ),
        ProbeStep(
            label="q2_hourly_variable_naming",
            path="/v1/previous-runs",
            query={
                **base,
                "hourly": "temperature_2m,temperature_2m_previous_day1",
                "start_date": recent_end,
                "end_date": recent_end,
            },
            questions=("q2_variable_naming_and_real_max_n",),
            rationale="Whether the hourly surface names variables the same way as daily.",
        ),
        ProbeStep(
            label="q3_archive_depth_2024",
            path="/v1/previous-runs",
            query={
                **base,
                "daily": _previous_day_variables(1),
                "start_date": "2024-01-01",
                "end_date": "2024-01-07",
            },
            questions=("q3_archive_depth_for_one_site",),
            rationale=(
                "The plan's Branch H bar requires the archive to reach 2024-01. "
                "This is the decisive request for that clause."
            ),
        ),
        ProbeStep(
            label="q3_archive_depth_2022",
            path="/v1/previous-runs",
            query={
                **base,
                "daily": _previous_day_variables(1),
                "start_date": "2022-01-01",
                "end_date": "2022-01-07",
            },
            questions=("q3_archive_depth_for_one_site",),
            rationale="How much DEEPER than the bar the archive actually reaches.",
        ),
        ProbeStep(
            label="q3_archive_depth_2019",
            path="/v1/previous-runs",
            query={
                **base,
                "daily": _previous_day_variables(1),
                "start_date": "2019-01-01",
                "end_date": "2019-01-07",
            },
            questions=("q3_archive_depth_for_one_site",),
            rationale="Bracket the floor: an error here bounds the depth from below.",
        ),
        ProbeStep(
            label="q4_anchor_daily_window",
            path="/v1/previous-runs",
            query={
                **base,
                "daily": _previous_day_variables(5),
                "start_date": recent_start,
                "end_date": recent_end,
            },
            questions=("q4_valid_time_or_run_time_anchored",),
            rationale=(
                "THE lookahead question. Over a multi-day window, a VALID-time "
                "anchored series has previous_dayN[d] describing target day d as "
                "seen N days earlier; a RUN-time anchored one describes a "
                "different target. The captured grid is what decides it -- the "
                "proposal's claim is confirmed here, never inherited."
            ),
        ),
        ProbeStep(
            label="q4_anchor_single_day_control",
            path="/v1/previous-runs",
            query={
                **base,
                "daily": _previous_day_variables(5),
                "start_date": recent_end,
                "end_date": recent_end,
            },
            questions=("q4_valid_time_or_run_time_anchored",),
            rationale=(
                "Control for the above: one target day only. If the previous_dayN "
                "values here match the same row of the multi-day capture, the "
                "series is anchored on the valid day and not on the request window."
            ),
        ),
        ProbeStep(
            label="q4_anchor_second_site",
            path="/v1/previous-runs",
            query={
                "latitude": lat2,
                "longitude": lon2,
                "timezone": "UTC",
                "daily": _previous_day_variables(5),
                "start_date": recent_start,
                "end_date": recent_end,
            },
            questions=("q4_valid_time_or_run_time_anchored",),
            rationale="The anchoring conclusion must not rest on one location.",
        ),
        ProbeStep(
            label="q5_publication_lag_today",
            path="/v1/previous-runs",
            query={
                **base,
                "hourly": "temperature_2m,temperature_2m_previous_day1",
                "forecast_days": "2",
                "past_days": "1",
            },
            questions=("q5_observable_publication_lag",),
            rationale=(
                "Which runs are retrievable RIGHT NOW. Wall-clock is recorded in "
                "the manifest, so the earliest retrievable instant for run R is "
                "read off a second execution rather than assumed."
            ),
        ),
        ProbeStep(
            label="q5_publication_lag_yesterday",
            path="/v1/previous-runs",
            query={
                **base,
                "hourly": "temperature_2m,temperature_2m_previous_day1",
                "start_date": (today - dt.timedelta(days=1)).isoformat(),
                "end_date": today.isoformat(),
            },
            questions=("q5_observable_publication_lag",),
            rationale="A settled window to contrast against the still-publishing one.",
        ),
        ProbeStep(
            label="q6_restatement_key_capture",
            path="/v1/previous-runs",
            query={
                **base,
                "daily": _previous_day_variables(3),
                "start_date": recent_start,
                "end_date": recent_end,
                "models": "best_match",
            },
            questions=("q6_values_ever_restated",),
            rationale=(
                "Q6 cannot be answered inside ONE run: restatement is a change "
                "over wall-clock time. This step captures the digested "
                "(model, init_time, valid_time, variable) grid; the operator "
                "re-runs the probe on a later day and diffs the sha256 in the "
                "manifest. A second identical request in the same run would "
                "prove nothing, so this probe does not pretend otherwise."
            ),
        ),
        ProbeStep(
            label="q6_restatement_key_capture_older",
            path="/v1/previous-runs",
            query={
                **base,
                "daily": _previous_day_variables(3),
                "start_date": "2025-01-06",
                "end_date": "2025-01-12",
                "models": "best_match",
            },
            questions=("q6_values_ever_restated",),
            rationale=(
                "A long-settled window. If even THIS digest moves between two "
                "executions, restatement is not confined to recent runs."
            ),
        ),
    ]

    steps.extend(
        ProbeStep(
            label=f"q7_model_{identifier}",
            path="/v1/previous-runs",
            query={
                **base,
                "daily": _previous_day_variables(1),
                "start_date": recent_end,
                "end_date": recent_end,
                "models": identifier,
            },
            questions=("q7_accepted_model_identifiers",),
            rationale=f"Is {identifier!r} an accepted `models=` identifier on this endpoint?",
        )
        for identifier in _MODEL_IDENTIFIERS
    )

    steps.append(
        ProbeStep(
            label="q8_licence_and_error_shape",
            path="/v1/previous-runs",
            query={},
            questions=("q8_licence_terms_text_verbatim",),
            rationale=(
                "A parameterless call. Whatever the ORIGIN itself says about "
                "terms, attribution or licensing is captured verbatim here. The "
                "terms page lives on a different host that is deliberately NOT "
                "allowlisted; if this payload carries no licence text, that "
                "absence is the finding and the allowlist stays as it is."
            ),
        )
    )
    steps.append(
        ProbeStep(
            label="q9_largest_plausible_payload",
            path="/v1/previous-runs",
            query={
                **base,
                "hourly": (
                    "temperature_2m,temperature_2m_previous_day1,"
                    "temperature_2m_previous_day2,temperature_2m_previous_day3"
                ),
                "start_date": recent_start,
                "end_date": recent_end,
            },
            questions=("q9_response_sizes_for_a_body_cap",),
            rationale=(
                "The biggest request a production client would plausibly make. "
                "Its size sets the per-instance body cap from evidence."
            ),
        )
    )
    return tuple(steps)


def render_report(
    plan: Sequence[ProbeStep],
    exchanges: Sequence[ProbeExchange],
    *,
    budget: RequestBudget,
    aborted: str | None,
) -> str:
    """Render the honest, self-accounting evidence header and summary."""
    lines: list[str] = [
        "# Open-Meteo `/v1/previous-runs` probe (P2 Probe A)",
        "",
        "## EVIDENCE ONLY - NEVER INGEST",
        "",
        "These captures must NEVER be ingested into the production forecast",
        "catalog. Backfilling them under a plausible retrieval timestamp would",
        "be backdating and would violate the point-in-time forecast design.",
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
        f"Planned steps: {len(plan)}",
        "",
    ]
    if aborted is not None:
        lines.extend(["## RUN ABORTED", "", aborted, ""])
    lines.extend(
        [
            "## Outcomes",
            "",
            "| # | label | status | bytes | outcome |",
            "|--:|---|--:|--:|---|",
        ]
    )
    for exchange in exchanges:
        lines.append(
            f"| {exchange.ordinal} | `{exchange.label}` | {exchange.status_code} "
            f"| {exchange.body_bytes} | {exchange.outcome} |"
        )
    lines.extend(["", "## Question coverage", ""])
    for question in QUESTIONS:
        labels = [step.label for step in plan if question in step.questions]
        answered = [e.label for e in exchanges if e.label in labels and e.outcome == "ok"]
        lines.append(f"- `{question}`: planned {labels}; answered {answered}")
    findings = [e for e in exchanges if e.finding is not None]
    lines.extend(["", "## Findings", ""])
    if not findings:
        lines.append("- None recorded.")
    for exchange in findings:
        lines.append(f"- `{exchange.label}`: {exchange.finding}")
    return "\n".join(lines) + "\n"


async def execute(
    transport: ProbeTransport,
    writer: ProbeEvidenceWriter,
    plan: Sequence[ProbeStep],
    *,
    pause_seconds: float = 1.0,
    sleeper: object | None = None,
) -> tuple[tuple[ProbeExchange, ...], str | None]:
    """Dispatch the plan, recording every exchange. Abort on budget exhaustion."""
    exchanges: list[ProbeExchange] = []
    aborted: str | None = None
    for index, step in enumerate(plan):
        try:
            exchange = await transport.probe_get(step.path, query=step.query, label=step.label)
        except RequestBudgetExceededError as exc:
            aborted = f"Budget exhausted before `{step.label}`: {exc}"
            break
        exchanges.append(exchange)
        writer.record(step.label, exchange)
        if sleeper is None and index + 1 < len(plan):
            await asyncio.sleep(pause_seconds)
    return tuple(exchanges), aborted


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, add_help=True)
    parser.add_argument("--output-directory", required=True)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually dispatch. Without it the plan is printed and nothing is sent.",
    )
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
        sys.stderr.write(
            f"REFUSED: --apply is required. Planned steps: {len(plan)} (budget {REQUEST_BUDGET}).\n"
        )
        return 2
    if not os.environ.get(USER_AGENT_ENV_VAR):
        sys.stderr.write(f"REFUSED: {USER_AGENT_ENV_VAR} must name a monitored contact.\n")
        return 2

    budget = RequestBudget(limit=REQUEST_BUDGET)
    transport = ProbeTransport(
        base_url=BASE_URL,
        allowed_hosts=ALLOWED_HOSTS,
        budget=budget,
        max_body_bytes=MAX_BODY_BYTES,
        user_agent=os.environ[USER_AGENT_ENV_VAR],
        accept="application/json",
        clock=time.time_ns,
    )
    writer = ProbeEvidenceWriter(Path(args.output_directory))
    exchanges, aborted = asyncio.run(execute(transport, writer, plan))
    writer.write_report(
        "PROBE_REPORT.md", render_report(plan, exchanges, budget=budget, aborted=aborted)
    )
    sys.stderr.write(
        f"Probe A finished: {budget.spent}/{budget.limit} requests spent, "
        f"{len(exchanges)} exchanges recorded in {args.output_directory}.\n"
    )
    return 1 if aborted is not None else 0


if __name__ == "__main__":  # pragma: no cover - operator entry point
    raise SystemExit(main())
