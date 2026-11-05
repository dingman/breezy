#!/usr/bin/env python
"""P2 Probe A -- read-only evidence probe for Open-Meteo previous-model-run data.

Authority: ``docs/plans/DATA_CAPTURE_AND_RISK_PLAN.md`` section 4.P2. This
probe decides OQ-2, which gates an irreversible Arrow schema (I-4's first
write), so its output is evidence and nothing else.

EVIDENCE ONLY -- NEVER INGEST. Every payload this script writes carries the
``.probe.json`` suffix that no production loader reads, and lands in a
directory whose README repeats the rule. A captured forecast payload
backfilled under a plausible retrieval timestamp would be backdating and would
destroy the point-in-time property the whole forecast design rests on.

WHAT THE 2026-08-31 RUN TAUGHT US
---------------------------------
The first live execution sent 22 requests to ``/v1/previous-runs`` and got
HTTP 404 -- ``{"error":true,"reason":"Not Found"}`` -- from every one of them.
That path was inherited from ``WEATHER_INGESTION_PROPOSAL.md:152`` and had
never been verified. Two defects, both fixed here:

1. **A non-2xx was reported as an answer.** The report marked all 22 exchanges
   ``ok``, all nine questions ``answered``, and "Findings: None recorded." A
   reader could have concluded Branch H was viable from a run that carried no
   data at all. Now: a non-2xx is classified as a FINDING by the transport; a
   question is ``answered`` only when a step returned 2xx **and** yielded the
   datum it was designed to extract; a failed BASELINE step aborts the rest of
   the plan and the report says how many steps were skipped and why; and the
   report ends with a computed ``VERDICT:`` line rather than leaving the
   judgement to the reader.
2. **The endpoint shape was assumed.** Now a low-budget
   (:data:`DISCOVERY_BUDGET`) discovery phase ESTABLISHES the shape before the
   plan is dispatched, trying the regular forecast endpoint first and the
   dedicated previous-runs host second, and ABORTS the whole plan if neither
   serves previous-run variables.

WHAT IT MUST ANSWER
-------------------
Nine pre-registered questions (:data:`QUESTIONS`), each mapped to at least one
labelled request across the discovery plan and the main plan, so coverage is
computable rather than asserted. Q4 -- *valid-time or run-time anchored* -- is
the whole lookahead question, and it is CLASSIFIED from two captures
(:func:`classify_anchor`), never inherited from a document.

CONTAINMENT
-----------
* Transport is :class:`breezy.ingest.probe_transport.ProbeTransport`, a
  subclass of the hardened ``breezy.ingest.http.HttpTransport``. No other HTTP
  client is imported (AST-asserted).
* ``allowed_hosts`` is per-probe and per-transport: each transport is built
  with the single host of the candidate shape it is aimed at. The two
  candidate hosts are both Open-Meteo origins; the settlement origin is
  refused by the transport's constructor and is not named anywhere in this
  file. The shipped default allowlist is neither imported nor touched (plan
  section 1.2 item 10).
* ``max_body_bytes`` is per-instance. No global body-cap lever is touched.
* :data:`REQUEST_BUDGET` is hard: the (N+1)th request raises and aborts. The
  discovery phase spends from the SAME budget, and a test asserts
  ``DISCOVERY_BUDGET + len(plan) <= REQUEST_BUDGET``.
* The run refuses to start without ``BREEZY_LIVE=1`` and ``--apply``.
* One request at a time, with a courtesy pause between them. No retries.

Licence capture (Q8): the operator closed the licence gate on 2026-08-31
(*"open mateo doesn't require a license, we're using the freely accessible
API"*). The text is still captured as a record of what the endpoint said on
the day we relied on it. Note honestly: the terms page is on a DIFFERENT host,
which is deliberately not allowlisted, so what is capturable here is whatever
the API origin itself serves. If nothing licence-bearing is served, THAT is
the finding -- widening the allowlist to chase it is not an option. Likewise,
if a candidate demands an API key, that is a FINDING that closes Branch H on
the free tier: no authentication is attempted.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import os
import re
import sys
import time
from collections.abc import Callable, Mapping, Sequence
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


@dataclass(frozen=True, slots=True)
class EndpointShape:
    """One candidate way the previous-run variables might be served."""

    name: str
    host: str
    path: str
    rationale: str = ""

    @property
    def base_url(self) -> str:
        return f"https://{self.host}"


#: The candidate shapes, in the order they are tried. ``/v1/previous-runs`` on
#: the main host is NOT among them: the 2026-08-31 run proved it absent, and
#: re-asking is budget spent to re-learn a recorded negative.
CANDIDATE_SHAPES: tuple[EndpointShape, ...] = (
    EndpointShape(
        name="regular_forecast_endpoint",
        host="api.open-meteo.com",
        path="/v1/forecast",
        rationale=(
            "Cheapest hypothesis: the `_previous_dayN` variables are served by "
            "the ordinary forecast endpoint rather than by a dedicated path."
        ),
    ),
    EndpointShape(
        name="dedicated_previous_runs_host",
        host="previous-runs-api.open-meteo.com",
        path="/v1/forecast",
        rationale=(
            "Second hypothesis: previous model runs live on their own host. A "
            "different HOST is permitted for this probe instance only; the "
            "shipped default allowlist is untouched."
        ),
    ),
)

#: The union of the candidate hosts. Per-probe, and per-transport narrower
#: still: each transport is allowlisted to exactly the one host it targets.
ALLOWED_HOSTS: frozenset[str] = frozenset(shape.host for shape in CANDIDATE_SHAPES)

#: Retained for the live harness: the first candidate's origin.
BASE_URL: str = CANDIDATE_SHAPES[0].base_url

#: Per-INSTANCE cap. Open-Meteo hourly payloads across many variables are the
#: largest thing this probe asks for; Q9 measures the real sizes so a
#: production client can be capped from evidence rather than from a guess.
MAX_BODY_BYTES: int = 512 * 1024

#: HARD. The (N+1)th request raises and aborts the run. Discovery spends from
#: this same budget.
REQUEST_BUDGET: int = 24

#: The discovery phase's own ceiling. Establishing WHICH shape works is worth
#: a handful of requests; re-learning a 404 twenty-one more times is not.
DISCOVERY_BUDGET: int = 4

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

#: The two captures :func:`classify_anchor` compares.
ANCHOR_WINDOW_LABEL: str = "q4_anchor_daily_window"
ANCHOR_CONTROL_LABEL: str = "q4_anchor_single_day_control"

#: The ONE step that tests the archive clause. The 2026-08-31 run proved the
#: archive is non-contiguous -- 2022-01 populated, 2024-01 all null -- so
#: "some older window had data" must never satisfy "the archive reaches
#: 2024-01". Only this step's own capture can.
ARCHIVE_BAR_LABEL: str = "q3_archive_depth_2024"

#: How far in the past a populated capture must sit, relative to the newest
#: capture in the same run, to rule out a previous-run series chosen relative
#: to the REQUEST INSTANT rather than to the valid time.
HISTORICAL_CORROBORATION_DAYS: int = 30

# -- the Branch H bar, verbatim from the plan's decision table --------------

VERDICT_VIABLE: str = "BRANCH H VIABLE"
VERDICT_NOT_VIABLE: str = "BRANCH H NOT VIABLE"
VERDICT_INCONCLUSIVE: str = "BRANCH H INCONCLUSIVE"

CLAUSE_ENDPOINT: str = "endpoint_serves_previous_run_variables"
CLAUSE_UNKEYED: str = "unkeyed_on_the_free_tier"
CLAUSE_MAX_N: str = "previous_day_n_at_least_5"
CLAUSE_ARCHIVE: str = "archive_reaches_2024_01"
CLAUSE_ANCHOR: str = "valid_time_anchored"

BAR_MIN_PREVIOUS_DAY_INDEX: int = 5
BAR_ARCHIVE_START: str = "2024-01-01"

_PREVIOUS_DAY_PATTERN = re.compile(r"\A(?P<base>.+)_previous_day(?P<index>\d+)\Z")

_LICENCE_MARKERS: tuple[str, ...] = (
    "licen",
    "terms",
    "attribution",
    "creative commons",
    "cc by",
    "copyright",
)

_KEY_MARKERS: tuple[str, ...] = ("api key", "apikey", "api_key", "unauthorized", "unauthorised")


# ==========================================================================
# The request plan
# ==========================================================================


@dataclass(frozen=True, slots=True)
class ProbeStep:
    """One labelled request, which questions it serves, and how to read it.

    ``questions`` is what makes coverage computable: a test asserts the union
    over discovery plus the main plan equals :data:`QUESTIONS`, so a question
    cannot be quietly dropped from the probe while remaining in the report.

    ``extractor`` is what makes an ANSWER computable. It returns the datum the
    step was designed to obtain, or ``None`` when the payload did not carry
    it. A step whose extractor returns ``None`` answers nothing, however
    healthy its status line looked.
    """

    label: str
    path: str
    query: Mapping[str, str]
    questions: tuple[str, ...]
    rationale: str
    extractor: Callable[[ProbeExchange], Mapping[str, object] | None]
    shape: EndpointShape | None = None
    baseline: bool = False
    single_run_answerable: bool = True


def _coordinates(city: str) -> tuple[str, str]:
    coords = default_registry().enrichment_coordinates(VENUE, city)
    return (f"{coords.lat:.5f}", f"{coords.lon:.5f}")


def _base_variable(surface: str) -> str:
    return "temperature_2m_max" if surface == "daily" else "temperature_2m"


def _variables(surface: str, count: int) -> dict[str, str]:
    """The ``daily=``/``hourly=`` parameter naming N previous-run variables."""
    base = _base_variable(surface)
    names = [base]
    names.extend(f"{base}_previous_day{index}" for index in range(1, count + 1))
    return {surface: ",".join(names)}


def _other_surface(surface: str) -> str:
    return "hourly" if surface == "daily" else "daily"


# ==========================================================================
# Extractors -- what "the datum this step was designed to obtain" means
# ==========================================================================


def _payload(exchange: ProbeExchange) -> Mapping[str, object] | None:
    if exchange.text is None:
        return None
    try:
        parsed = json.loads(exchange.text)
    except ValueError:
        return None
    return parsed if isinstance(parsed, Mapping) else None


def _previous_run_block(
    payload: Mapping[str, object],
) -> tuple[str, Mapping[str, object], tuple[str, ...]] | None:
    """The first surface block that actually carries ``_previous_dayN`` series."""
    for surface in ("daily", "hourly"):
        block = payload.get(surface)
        if not isinstance(block, Mapping):
            continue
        names = tuple(
            sorted(name for name in block if _PREVIOUS_DAY_PATTERN.match(str(name)) is not None)
        )
        if names:
            return surface, block, names
    return None


def _index_of(name: str) -> int:
    match = _PREVIOUS_DAY_PATTERN.match(name)
    return int(match.group("index")) if match is not None else 0


def _has_value(values: object) -> bool:
    return isinstance(values, list) and any(value is not None for value in values)


def extract_previous_day_variables(exchange: ProbeExchange) -> Mapping[str, object] | None:
    """The core datum: named previous-run series carrying at least one value.

    An all-null series is NOT a datum. For the archive-depth steps that is the
    whole point: a 200 that returns the requested window with nothing in it
    tells us the archive does not reach that far, and must not be counted as
    an answer that it does.
    """
    payload = _payload(exchange)
    if payload is None:
        return None
    found = _previous_run_block(payload)
    if found is None:
        return None
    surface, block, names = found
    # A NAMED variable is not a SERVED variable: the regular forecast endpoint
    # answers 200 for `temperature_2m_previous_day1` with every value null.
    # Only populated series count, and only they set the maximum N.
    populated = tuple(name for name in names if _has_value(block.get(name)))
    if not populated:
        return None
    times = block.get("time")
    stamps = [str(stamp) for stamp in times] if isinstance(times, list) else []
    return {
        "surface": surface,
        "previous_day_variables": populated,
        "max_previous_day_index": max(_index_of(name) for name in populated),
        "rows": len(stamps),
        "first_time": stamps[0] if stamps else None,
        "last_time": stamps[-1] if stamps else None,
        "bytes": exchange.body_bytes,
    }


def extract_anchor_grid(exchange: ProbeExchange) -> Mapping[str, object] | None:
    """The (valid time x previous_dayN) grid Q4's classification compares."""
    payload = _payload(exchange)
    if payload is None:
        return None
    found = _previous_run_block(payload)
    if found is None:
        return None
    _surface, block, names = found
    times = block.get("time")
    if not isinstance(times, list) or not times:
        return None
    series: dict[str, tuple[object, ...]] = {}
    for name in names:
        values = block.get(name)
        if isinstance(values, list):
            series[name] = tuple(values)
    if not series or not any(_has_value(list(values)) for values in series.values()):
        return None
    return {"times": tuple(str(stamp) for stamp in times), "series": series}


def _grid_parts(
    grid: Mapping[str, object] | None,
) -> tuple[list[str], dict[str, list[object]]] | None:
    """Narrow an anchor grid to (times, series), or ``None`` if it is not one."""
    if not grid:
        return None
    raw_times = grid.get("times")
    raw_series = grid.get("series")
    if not isinstance(raw_times, list | tuple) or not isinstance(raw_series, Mapping):
        return None
    times = [str(stamp) for stamp in raw_times]
    series: dict[str, list[object]] = {}
    for name, values in raw_series.items():
        if isinstance(values, list | tuple):
            series[str(name)] = list(values)
    if not times or not series:
        return None
    return times, series


def extract_publication_lag(exchange: ProbeExchange) -> Mapping[str, object] | None:
    """The newest valid time for which a previous-run value is retrievable NOW."""
    parts = _grid_parts(extract_anchor_grid(exchange))
    if parts is None:
        return None
    times, series = parts
    latest: str | None = None
    for values in series.values():
        for stamp, value in zip(times, values, strict=False):
            if value is not None and (latest is None or stamp > latest):
                latest = stamp
    if latest is None:
        return None
    return {
        "latest_time_with_previous_run_value": latest,
        "captured_at_utc": exchange.requested_at_utc,
        "rows": len(times),
    }


def extract_licence_text(exchange: ProbeExchange) -> Mapping[str, object] | None:
    """Whatever the API ORIGIN itself says about terms, licence or attribution.

    Body only: the exchange record keeps no header block, and the terms page
    lives on a host that is deliberately not allowlisted. Nothing found is a
    finding, not a reason to widen the allowlist.
    """
    text = exchange.text or ""
    lowered = text.lower()
    hits = tuple(marker for marker in _LICENCE_MARKERS if marker in lowered)
    if not hits:
        return None
    return {"licence_markers": hits, "excerpt": text[:512]}


def extract_body_size(exchange: ProbeExchange) -> Mapping[str, object] | None:
    """Q9's datum: a real measured size for a real plausible request."""
    if exchange.body_bytes <= 0:
        return None
    return {"bytes": exchange.body_bytes, "content_type": exchange.content_type}


def extract_restatement_digest(exchange: ProbeExchange) -> Mapping[str, object] | None:
    """The digest a LATER execution is diffed against. Answers nothing today."""
    datum = extract_previous_day_variables(exchange)
    if datum is None:
        return None
    return {**datum, "sha256": exchange.sha256}


def _shape_extractor(
    shape: EndpointShape,
) -> Callable[[ProbeExchange], Mapping[str, object] | None]:
    def extract(exchange: ProbeExchange) -> Mapping[str, object] | None:
        datum = extract_previous_day_variables(exchange)
        if datum is None:
            return None
        return {**datum, "host": shape.host, "path": shape.path, "unkeyed": True}

    return extract


# ==========================================================================
# Phase 1 -- LOW-BUDGET discovery of the endpoint shape
# ==========================================================================


def build_discovery_plan() -> tuple[ProbeStep, ...]:
    """At most :data:`DISCOVERY_BUDGET` requests to establish the shape.

    Ordered cheapest-hypothesis-first: the regular forecast endpoint before
    the dedicated host, and the daily surface before the hourly one. The phase
    stops at the FIRST candidate that returns previous-run values, so the
    common case costs one request.
    """
    lat, lon = _coordinates(PRIMARY_CITY)
    base = {"latitude": lat, "longitude": lon, "timezone": "UTC"}
    steps: list[ProbeStep] = []
    for shape in CANDIDATE_SHAPES:
        for surface in ("daily", "hourly"):
            steps.append(
                ProbeStep(
                    label=f"discovery_{shape.name}_{surface}",
                    path=shape.path,
                    query={**base, **_variables(surface, 1), "forecast_days": "3"},
                    questions=("q1_unkeyed_and_on_which_host",),
                    rationale=(
                        f"{shape.rationale} Does `{shape.host}{shape.path}` serve "
                        f"`{_base_variable(surface)}_previous_day1` on the {surface} "
                        "surface, with NO key?"
                    ),
                    extractor=_shape_extractor(shape),
                    shape=shape,
                )
            )
    if len(steps) > DISCOVERY_BUDGET:  # pragma: no cover - guarded by test
        raise AssertionError(
            f"The discovery plan is {len(steps)} requests against a "
            f"{DISCOVERY_BUDGET}-request ceiling."
        )
    return tuple(steps)


def looks_keyed(exchange: ProbeExchange) -> bool:
    """Does this exchange say the endpoint wants credentials we do not have?"""
    if exchange.status_code in (401, 402, 403):
        return True
    if "Forbidden" in exchange.outcome:
        return True
    lowered = (exchange.text or "").lower()
    return any(marker in lowered for marker in _KEY_MARKERS)


# ==========================================================================
# Phase 2 -- the pre-registered plan, built around the DISCOVERED shape
# ==========================================================================


def build_request_plan(
    shape: EndpointShape = CANDIDATE_SHAPES[0], surface: str = "daily"
) -> tuple[ProbeStep, ...]:
    """The full pre-registered request plan, in dispatch order.

    Every step is a GET. The plan is built ONCE and ``DISCOVERY_BUDGET`` plus
    its length is asserted against :data:`REQUEST_BUDGET` by test, so an
    over-spend is impossible to introduce by adding a step without also
    raising the ceiling deliberately.
    """
    lat, lon = _coordinates(PRIMARY_CITY)
    lat2, lon2 = _coordinates(SECONDARY_CITY)
    today = dt.datetime.now(tz=dt.UTC).date()
    recent_start = (today - dt.timedelta(days=8)).isoformat()
    recent_end = (today - dt.timedelta(days=2)).isoformat()
    path = shape.path
    variable = _base_variable(surface)

    base: dict[str, str] = {"latitude": lat, "longitude": lon, "timezone": "UTC"}

    steps: list[ProbeStep] = [
        ProbeStep(
            label="q2_previous_day_ladder",
            path=path,
            query={**base, **_variables(surface, 7)},
            questions=("q2_variable_naming_and_real_max_n", "q9_response_sizes_for_a_body_cap"),
            rationale=(
                "BASELINE. Confirms the naming and how many previous runs are "
                "served on the discovered shape. If this fails, every later step "
                "is spending budget to re-learn the same negative, so the run "
                "aborts here."
            ),
            extractor=extract_previous_day_variables,
            shape=shape,
            baseline=True,
        ),
        ProbeStep(
            label="q2_previous_day_boundary_probe",
            path=path,
            query={**base, surface: f"{variable}_previous_day8"},
            questions=("q2_variable_naming_and_real_max_n",),
            rationale=(
                "The REAL maximum N. An error payload here typically names the "
                "accepted range -- recorded as a FINDING, since a non-2xx never "
                "answers a question, but a finding that bounds N from above."
            ),
            extractor=extract_previous_day_variables,
            shape=shape,
        ),
        ProbeStep(
            label="q2_other_surface_variable_naming",
            path=path,
            query={**base, **_variables(_other_surface(surface), 1), "forecast_days": "2"},
            questions=("q2_variable_naming_and_real_max_n",),
            rationale="Whether the other surface names its variables the same way.",
            extractor=extract_previous_day_variables,
            shape=shape,
        ),
        ProbeStep(
            label="q3_archive_depth_2024",
            path=path,
            query={
                **base,
                **_variables(surface, 1),
                "start_date": "2024-01-01",
                "end_date": "2024-01-07",
            },
            questions=("q3_archive_depth_for_one_site",),
            rationale=(
                "The plan's Branch H bar requires the archive to reach 2024-01. "
                "This is the decisive request for that clause. A 200 that returns "
                "the window with only nulls is NOT an archive that reaches it."
            ),
            extractor=extract_previous_day_variables,
            shape=shape,
        ),
        ProbeStep(
            label="q3_archive_depth_2022",
            path=path,
            query={
                **base,
                **_variables(surface, 1),
                "start_date": "2022-01-01",
                "end_date": "2022-01-07",
            },
            questions=("q3_archive_depth_for_one_site",),
            rationale="How much DEEPER than the bar the archive actually reaches.",
            extractor=extract_previous_day_variables,
            shape=shape,
        ),
        ProbeStep(
            label="q3_archive_depth_2019",
            path=path,
            query={
                **base,
                **_variables(surface, 1),
                "start_date": "2019-01-01",
                "end_date": "2019-01-07",
            },
            questions=("q3_archive_depth_for_one_site",),
            rationale="Bracket the floor: an empty or refused window bounds the depth.",
            extractor=extract_previous_day_variables,
            shape=shape,
        ),
        ProbeStep(
            label=ANCHOR_WINDOW_LABEL,
            path=path,
            query={
                **base,
                **_variables(surface, 5),
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
            extractor=extract_anchor_grid,
            shape=shape,
        ),
        ProbeStep(
            label=ANCHOR_CONTROL_LABEL,
            path=path,
            query={
                **base,
                **_variables(surface, 5),
                "start_date": recent_end,
                "end_date": recent_end,
            },
            questions=("q4_valid_time_or_run_time_anchored",),
            rationale=(
                "Control for the above: one target day only. If the previous_dayN "
                "values here match the same row of the multi-day capture, the "
                "series is anchored on the valid day and not on the request "
                "window. `classify_anchor` computes that comparison."
            ),
            extractor=extract_anchor_grid,
            shape=shape,
        ),
        ProbeStep(
            label="q4_anchor_second_site",
            path=path,
            query={
                "latitude": lat2,
                "longitude": lon2,
                "timezone": "UTC",
                **_variables(surface, 5),
                "start_date": recent_start,
                "end_date": recent_end,
            },
            questions=("q4_valid_time_or_run_time_anchored",),
            rationale="The anchoring conclusion must not rest on one location.",
            extractor=extract_anchor_grid,
            shape=shape,
        ),
        ProbeStep(
            label="q5_publication_lag_today",
            path=path,
            query={**base, **_variables(surface, 1), "forecast_days": "2", "past_days": "1"},
            questions=("q5_observable_publication_lag",),
            rationale=(
                "Which runs are retrievable RIGHT NOW. Wall-clock is recorded in "
                "the manifest, so the earliest retrievable instant for run R is "
                "read off a second execution rather than assumed."
            ),
            extractor=extract_publication_lag,
            shape=shape,
        ),
        ProbeStep(
            label="q5_publication_lag_yesterday",
            path=path,
            query={
                **base,
                **_variables(surface, 1),
                "start_date": (today - dt.timedelta(days=1)).isoformat(),
                "end_date": today.isoformat(),
            },
            questions=("q5_observable_publication_lag",),
            rationale="A settled window to contrast against the still-publishing one.",
            extractor=extract_publication_lag,
            shape=shape,
        ),
        ProbeStep(
            label="q6_restatement_key_capture",
            path=path,
            query={
                **base,
                **_variables(surface, 3),
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
                "prove nothing, so this probe reports Q6 UNANSWERED by "
                "construction rather than pretending otherwise."
            ),
            extractor=extract_restatement_digest,
            shape=shape,
            single_run_answerable=False,
        ),
        ProbeStep(
            label="q6_restatement_key_capture_older",
            path=path,
            query={
                **base,
                **_variables(surface, 3),
                "start_date": "2025-01-06",
                "end_date": "2025-01-12",
                "models": "best_match",
            },
            questions=("q6_values_ever_restated",),
            rationale=(
                "A long-settled window. If even THIS digest moves between two "
                "executions, restatement is not confined to recent runs."
            ),
            extractor=extract_restatement_digest,
            shape=shape,
            single_run_answerable=False,
        ),
    ]

    steps.extend(
        ProbeStep(
            label=f"q7_model_{identifier}",
            path=path,
            query={
                **base,
                **_variables(surface, 1),
                "start_date": recent_end,
                "end_date": recent_end,
                "models": identifier,
            },
            questions=("q7_accepted_model_identifiers",),
            rationale=f"Is {identifier!r} an accepted `models=` identifier on this shape?",
            extractor=extract_previous_day_variables,
            shape=shape,
        )
        for identifier in _MODEL_IDENTIFIERS
    )

    steps.append(
        ProbeStep(
            label="q8_licence_and_terms_capture",
            path=path,
            query={**base, **_variables(surface, 1), "forecast_days": "1"},
            questions=("q8_licence_terms_text_verbatim",),
            rationale=(
                "Whatever the ORIGIN itself says about terms, attribution or "
                "licensing is captured verbatim here. The terms page lives on a "
                "different host that is deliberately NOT allowlisted; if this "
                "payload carries no licence text, that absence is the finding "
                "and the allowlist stays as it is."
            ),
            extractor=extract_licence_text,
            shape=shape,
        )
    )
    steps.append(
        ProbeStep(
            label="q9_largest_plausible_payload",
            path=path,
            query={
                **base,
                **_variables(surface, 3),
                "start_date": recent_start,
                "end_date": recent_end,
            },
            questions=("q9_response_sizes_for_a_body_cap",),
            rationale=(
                "The biggest request a production client would plausibly make. "
                "Its size sets the per-instance body cap from evidence."
            ),
            extractor=extract_body_size,
            shape=shape,
        )
    )
    return tuple(steps)


# ==========================================================================
# Evaluation -- a 2xx that carried the datum, or it is not an answer
# ==========================================================================


@dataclass(frozen=True, slots=True)
class StepOutcome:
    """What one dispatched step actually established."""

    label: str
    status_code: int
    succeeded: bool
    datum: Mapping[str, object] | None
    reason: str | None
    questions: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class QuestionOutcome:
    """Whether a pre-registered question is answered, and on what evidence."""

    question: str
    answered: bool
    answered_by: tuple[str, ...]
    data: tuple[Mapping[str, object], ...]
    reason: str | None


def evaluate_step(step: ProbeStep, exchange: ProbeExchange) -> StepOutcome:
    """Classify one exchange. A non-2xx yields no datum, ever."""
    if not exchange.succeeded:
        status = f"HTTP {exchange.status_code}" if exchange.status_code else f"`{exchange.outcome}`"
        return StepOutcome(
            label=step.label,
            status_code=exchange.status_code,
            succeeded=False,
            datum=None,
            reason=f"{status} -- a non-2xx response carries no datum and answers nothing",
            questions=step.questions,
        )
    datum = step.extractor(exchange)
    reason = (
        None
        if datum is not None
        else ("2xx, but the payload did not carry the datum this step was designed to extract")
    )
    return StepOutcome(
        label=step.label,
        status_code=exchange.status_code,
        succeeded=True,
        datum=datum,
        reason=reason,
        questions=step.questions,
    )


def classify_anchor(
    window: Mapping[str, object] | None, control: Mapping[str, object] | None
) -> str | None:
    """Is the previous-run series anchored on the VALID time or on the run?

    Compares a multi-day window capture against a single-day control for a
    date they share. If the previous_dayN values for that date are identical
    in both, the series describes the target day (valid-time anchored). If
    they move with the request window, it does not (run-time anchored).
    Returns ``None`` when the two captures cannot be compared at all -- an
    unclassifiable pair is not a licence to guess.
    """
    window_parts = _grid_parts(window)
    control_parts = _grid_parts(control)
    if window_parts is None or control_parts is None:
        return None
    window_times, window_series = window_parts
    control_times, control_series = control_parts
    shared = sorted(set(window_series) & set(control_series))
    if not shared:
        return None
    for control_index, stamp in enumerate(control_times):
        if stamp not in window_times:
            continue
        window_index = window_times.index(stamp)
        compared = 0
        matched = 0
        for name in shared:
            left = window_series[name]
            right = control_series[name]
            if window_index >= len(left) or control_index >= len(right):
                continue
            if left[window_index] is None and right[control_index] is None:
                continue
            compared += 1
            if left[window_index] == right[control_index]:
                matched += 1
        if compared == 0:
            continue
        return "valid_time" if matched == compared else "run_time"
    return None


def _capture_date(stamp: object) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(stamp)[:10])
    except ValueError:
        return None


def corroborating_historical_capture(outcomes: Sequence[StepOutcome]) -> str | None:
    """The label of a populated capture old enough to pin the anchor.

    Window-vs-control invariance (:func:`classify_anchor`) rules out a series
    anchored on the REQUEST WINDOW, but not one anchored on the request
    INSTANT -- a "run made N days before now" series is window-invariant too.
    A populated capture whose valid times are months older than the newest
    capture in the same run cannot have come from a run chosen relative to
    now, so it discriminates the two. Q4 is the lookahead question; it is not
    answered on the weaker test alone.
    """
    populated = [
        (outcome, _capture_date(outcome.datum.get("last_time")))
        for outcome in outcomes
        if outcome.datum is not None and outcome.datum.get("last_time") is not None
    ]
    dated = [(outcome, day) for outcome, day in populated if day is not None]
    if not dated:
        return None
    newest = max(day for _outcome, day in dated)
    for outcome, day in dated:
        if (newest - day).days >= HISTORICAL_CORROBORATION_DAYS:
            return outcome.label
    return None


def _anchor_outcome(
    outcomes: Mapping[str, StepOutcome], notes: list[str]
) -> Mapping[str, object] | None:
    window = outcomes.get(ANCHOR_WINDOW_LABEL)
    control = outcomes.get(ANCHOR_CONTROL_LABEL)
    anchor = classify_anchor(
        window.datum if window is not None else None,
        control.datum if control is not None else None,
    )
    if anchor is None:
        notes.append(
            "the multi-day window and the single-day control could not be "
            "compared, so anchoring is NOT classified"
        )
        return None
    corroborated_by = corroborating_historical_capture(tuple(outcomes.values()))
    if anchor == "valid_time" and corroborated_by is None:
        notes.append(
            "window-invariance was shown, but no capture old enough to rule out "
            "a series anchored on the REQUEST INSTANT was returned"
        )
    return {
        "anchor": anchor,
        "window": ANCHOR_WINDOW_LABEL,
        "control": ANCHOR_CONTROL_LABEL,
        "corroborated_by": corroborated_by,
    }


def evaluate_questions(
    steps: Sequence[ProbeStep], outcomes: Sequence[StepOutcome]
) -> tuple[QuestionOutcome, ...]:
    """Compute, per question, whether the run actually answered it.

    Answered requires a step that returned 2xx AND yielded its datum. A
    question with no dispatched step, or whose steps all failed, or whose
    steps are cross-run-only, is UNANSWERED with the reason recorded.
    """
    by_label = {outcome.label: outcome for outcome in outcomes}
    results: list[QuestionOutcome] = []
    for question in QUESTIONS:
        planned = [step for step in steps if question in step.questions]
        notes: list[str] = []
        answered_by: list[str] = []
        data: list[Mapping[str, object]] = []
        if not planned:
            results.append(
                QuestionOutcome(
                    question=question,
                    answered=False,
                    answered_by=(),
                    data=(),
                    reason="no step in this run was dispatched for this question",
                )
            )
            continue
        for step in planned:
            outcome = by_label.get(step.label)
            if outcome is None:
                notes.append(f"`{step.label}`: not dispatched (the plan was aborted)")
                continue
            if outcome.datum is None:
                notes.append(f"`{step.label}`: {outcome.reason}")
                continue
            if not step.single_run_answerable:
                notes.append(
                    f"`{step.label}`: baseline digest captured, but this question is a "
                    "cross-RUN diff -- a second execution on a later date is required"
                )
                continue
            answered_by.append(step.label)
            # The step is part of the datum: a clause that must be decided by
            # ONE designated step cannot be satisfied by a sibling's capture.
            data.append({**outcome.datum, "step": step.label})
        if question == "q4_valid_time_or_run_time_anchored":
            anchor = _anchor_outcome(by_label, notes)
            if anchor is None:
                answered_by, data = [], []
            else:
                data = [anchor, *data]
        results.append(
            QuestionOutcome(
                question=question,
                answered=bool(answered_by),
                answered_by=tuple(answered_by),
                data=tuple(data),
                reason="; ".join(notes) if notes else None,
            )
        )
    return tuple(results)


# ==========================================================================
# The VERDICT -- computed from the answered set, never left to the reader
# ==========================================================================


@dataclass(frozen=True, slots=True)
class BranchHVerdict:
    """The plan's Branch H decision table, evaluated."""

    verdict: str
    satisfied: tuple[str, ...] = ()
    refuted: tuple[str, ...] = ()
    unresolved: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()


def _clause_max_n(outcome: QuestionOutcome | None) -> tuple[str, str]:
    if outcome is None or not outcome.answered:
        return "unresolved", "no 2xx step reported a populated previous-run series"
    indices: list[int] = []
    for datum in outcome.data:
        value = datum.get("max_previous_day_index")
        if isinstance(value, int):
            indices.append(value)
    if not indices:
        return "unresolved", "answered, but no maximum previous-day index was extracted"
    best = max(indices)
    if best >= BAR_MIN_PREVIOUS_DAY_INDEX:
        return "satisfied", f"max previous_day index served = {best}"
    return "refuted", f"max previous_day index served = {best} < {BAR_MIN_PREVIOUS_DAY_INDEX}"


def _clause_archive(outcome: QuestionOutcome | None) -> tuple[str, str]:
    """Decided by the step that TESTED the bar, never by a sibling window."""
    if outcome is None or not outcome.data:
        return "unresolved", "no 2xx step returned a populated historical window"
    for datum in outcome.data:
        if datum.get("step") == ARCHIVE_BAR_LABEL:
            return "satisfied", (
                f"the {BAR_ARCHIVE_START} window itself returned values "
                f"(first_time={datum.get('first_time')})"
            )
    older = [
        str(datum.get("step"))
        for datum in outcome.data
        if str(datum.get("first_time") or "")[:10] < BAR_ARCHIVE_START
    ]
    if older:
        return "unresolved", (
            f"coverage is NON-CONTIGUOUS: {', '.join(older)} returned values while the "
            f"{BAR_ARCHIVE_START} window returned none. That is an unexplained gap, not "
            "a clearance -- a dedicated coverage probe is required"
        )
    return "refuted", (f"no window at or before {BAR_ARCHIVE_START} returned previous-run values")


def _clause_anchor(outcome: QuestionOutcome | None) -> tuple[str, str]:
    if outcome is None or not outcome.answered:
        return "unresolved", "anchoring could not be classified from the captures"
    anchors = {
        str(datum.get("anchor")) for datum in outcome.data if datum.get("anchor") is not None
    }
    if "run_time" in anchors:
        return "refuted", "previous_dayN moves with the request window (run-time anchored)"
    if "valid_time" not in anchors:
        return "unresolved", "anchoring could not be classified from the captures"
    corroborated = [
        str(datum.get("corroborated_by")) for datum in outcome.data if datum.get("corroborated_by")
    ]
    if not corroborated:
        return "unresolved", (
            "window-invariance was shown, but nothing rules out a series anchored on "
            "the REQUEST INSTANT: no capture old enough to discriminate was returned"
        )
    return "satisfied", (
        "previous_dayN describes the TARGET day (valid-time anchored), corroborated by "
        f"the historical capture `{corroborated[0]}`"
    )


def evaluate_verdict(
    questions: Sequence[QuestionOutcome],
    *,
    shape: EndpointShape | None,
    keyed: bool,
) -> BranchHVerdict:
    """Apply the plan's decision table. Any refuted clause closes Branch H."""
    by_question = {outcome.question: outcome for outcome in questions}
    states: list[tuple[str, str, str]] = []

    if shape is None:
        states.append(
            (
                CLAUSE_ENDPOINT,
                "refuted",
                "no candidate endpoint shape served previous-run variables",
            )
        )
    else:
        states.append((CLAUSE_ENDPOINT, "satisfied", f"served by {shape.host}{shape.path}"))

    if keyed:
        states.append(
            (
                CLAUSE_UNKEYED,
                "refuted",
                (
                    "a candidate demanded credentials; no authentication was "
                    "attempted and the free tier therefore does not serve this data"
                ),
            )
        )
    elif shape is not None:
        states.append((CLAUSE_UNKEYED, "satisfied", "answered with no key on the free tier"))
    else:
        states.append((CLAUSE_UNKEYED, "unresolved", "nothing answered, so keying is untested"))

    max_n_state, max_n_note = _clause_max_n(by_question.get("q2_variable_naming_and_real_max_n"))
    states.append((CLAUSE_MAX_N, max_n_state, max_n_note))
    archive_state, archive_note = _clause_archive(by_question.get("q3_archive_depth_for_one_site"))
    states.append((CLAUSE_ARCHIVE, archive_state, archive_note))
    anchor_state, anchor_note = _clause_anchor(
        by_question.get("q4_valid_time_or_run_time_anchored")
    )
    states.append((CLAUSE_ANCHOR, anchor_state, anchor_note))

    satisfied = tuple(clause for clause, state, _ in states if state == "satisfied")
    refuted = tuple(clause for clause, state, _ in states if state == "refuted")
    unresolved = tuple(clause for clause, state, _ in states if state == "unresolved")
    if refuted:
        verdict = VERDICT_NOT_VIABLE
    elif unresolved:
        verdict = VERDICT_INCONCLUSIVE
    else:
        verdict = VERDICT_VIABLE
    return BranchHVerdict(
        verdict=verdict,
        satisfied=satisfied,
        refuted=refuted,
        unresolved=unresolved,
        notes=tuple(f"{clause}: {state} -- {note}" for clause, state, note in states),
    )


# ==========================================================================
# Dispatch
# ==========================================================================


@dataclass(frozen=True, slots=True)
class DiscoveryResult:
    """What the low-budget discovery phase established."""

    shape: EndpointShape | None
    exchanges: tuple[ProbeExchange, ...]
    outcomes: tuple[StepOutcome, ...]
    keyed: bool
    aborted: str | None
    surface: str | None = None


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    """What the main plan established, including what it deliberately skipped."""

    exchanges: tuple[ProbeExchange, ...]
    outcomes: tuple[StepOutcome, ...]
    aborted: str | None
    skipped: tuple[str, ...]


async def run_discovery(
    factory: Callable[[EndpointShape], ProbeTransport],
    writer: ProbeEvidenceWriter,
    plan: Sequence[ProbeStep],
    *,
    pause_seconds: float = 1.0,
) -> DiscoveryResult:
    """Spend at most :data:`DISCOVERY_BUDGET` requests establishing the shape.

    Stops at the first candidate that returns previous-run values. If none
    does, the caller must NOT dispatch the main plan: the 2026-08-31 run spent
    21 further requests re-learning one 404.
    """
    exchanges: list[ProbeExchange] = []
    outcomes: list[StepOutcome] = []
    keyed = False
    for index, step in enumerate(plan):
        if step.shape is None:  # pragma: no cover - build_discovery_plan always sets it
            raise ValueError(f"discovery step `{step.label}` names no endpoint shape")
        transport = factory(step.shape)
        try:
            exchange = await transport.probe_get(step.path, query=step.query, label=step.label)
        except RequestBudgetExceededError as exc:
            return DiscoveryResult(
                shape=None,
                exchanges=tuple(exchanges),
                outcomes=tuple(outcomes),
                keyed=keyed,
                aborted=f"Budget exhausted during discovery, before `{step.label}`: {exc}",
            )
        exchanges.append(exchange)
        writer.record(step.label, exchange)
        outcome = evaluate_step(step, exchange)
        outcomes.append(outcome)
        keyed = keyed or looks_keyed(exchange)
        if outcome.datum is not None:
            return DiscoveryResult(
                shape=step.shape,
                exchanges=tuple(exchanges),
                outcomes=tuple(outcomes),
                keyed=keyed,
                aborted=None,
                surface=str(outcome.datum.get("surface") or "daily"),
            )
        if pause_seconds > 0 and index + 1 < len(plan):
            await asyncio.sleep(pause_seconds)

    detail = "; ".join(
        f"`{outcome.label}` -> {outcome.reason}" for outcome in outcomes if outcome.reason
    )
    aborted = (
        f"NO candidate endpoint shape served previous-run variables within the "
        f"{len(plan)}-request discovery budget ({detail}). The main plan is NOT "
        "dispatched: spending it would re-learn the same negative."
    )
    if keyed:
        aborted += (
            " At least one candidate demanded an API key; no authentication was "
            "attempted, and a keyed endpoint closes Branch H on the free tier."
        )
    return DiscoveryResult(
        shape=None,
        exchanges=tuple(exchanges),
        outcomes=tuple(outcomes),
        keyed=keyed,
        aborted=aborted,
    )


async def execute(
    transport: ProbeTransport,
    writer: ProbeEvidenceWriter,
    plan: Sequence[ProbeStep],
    *,
    pause_seconds: float = 1.0,
) -> ExecutionResult:
    """Dispatch the plan, recording every exchange.

    Aborts on budget exhaustion, and on a failed BASELINE step -- a baseline
    that yielded no datum means every later request would spend budget to
    re-learn the same negative.
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
        if step.baseline and outcome.datum is None:
            remaining = len(plan) - index - 1
            aborted = (
                f"BASELINE step `{step.label}` yielded no datum ({outcome.reason}). "
                f"The remaining {remaining} step(s) are SKIPPED -- dispatching them "
                "would spend the request budget re-learning the same negative."
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


# ==========================================================================
# The report
# ==========================================================================


def _outcome_rows(exchanges: Sequence[ProbeExchange]) -> list[str]:
    return [
        f"| {exchange.ordinal} | `{exchange.label}` | {exchange.status_code} "
        f"| {exchange.body_bytes} | {exchange.outcome} |"
        for exchange in exchanges
    ]


def _format_datum(datum: Mapping[str, object]) -> str:
    return ", ".join(f"{key}={value!r}" for key, value in datum.items() if key != "excerpt")


def render_report(
    *,
    discovery: DiscoveryResult,
    plan: Sequence[ProbeStep],
    execution: ExecutionResult,
    questions: Sequence[QuestionOutcome],
    verdict: BranchHVerdict,
    budget: RequestBudget,
) -> str:
    """Render the honest, self-accounting evidence report.

    Three properties the 2026-08-31 report lacked: a non-2xx appears under
    Findings, a question is only ``ANSWERED`` when a 2xx carried its datum,
    and the document ends with a computed ``VERDICT:`` line.
    """
    selected = (
        f"`{discovery.shape.host}{discovery.shape.path}` (surface: {discovery.surface or 'daily'})"
        if discovery.shape is not None
        else "**NONE** -- no candidate shape served previous-run variables"
    )
    lines: list[str] = [
        "# Open-Meteo previous-model-run probe (P2 Probe A)",
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
        f"Candidate hosts: {', '.join(sorted(ALLOWED_HOSTS))} (settlement host NOT touched)",
        (
            "Transport: `breezy.ingest.probe_transport.ProbeTransport`, "
            f"max_body_bytes={MAX_BODY_BYTES}"
        ),
        f"Request budget: {budget.limit} hard; spent {budget.spent}.",
        f"Discovery budget: {DISCOVERY_BUDGET}; planned main steps: {len(plan)}",
        "",
        "## Endpoint discovery",
        "",
        f"Selected shape: {selected}",
        "",
        "| # | label | status | bytes | outcome |",
        "|--:|---|--:|--:|---|",
        *_outcome_rows(discovery.exchanges),
        "",
    ]
    if discovery.aborted is not None:
        lines.extend(["**Discovery aborted.** " + discovery.aborted, ""])

    lines.extend(
        [
            "## Outcomes (main plan)",
            "",
            "| # | label | status | bytes | outcome |",
            "|--:|---|--:|--:|---|",
        ]
    )
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

    lines.extend(["## Question coverage", ""])
    for outcome in questions:
        if outcome.answered:
            evidence = ", ".join(f"`{label}`" for label in outcome.answered_by)
            datum = " | ".join(_format_datum(item) for item in outcome.data)
            lines.append(f"- `{outcome.question}`: ANSWERED by {evidence} -- {datum}")
            if outcome.reason:
                lines.append(f"  - partial: {outcome.reason}")
        else:
            lines.append(f"- `{outcome.question}`: UNANSWERED -- {outcome.reason or 'no evidence'}")

    findings = [
        exchange
        for exchange in (*discovery.exchanges, *execution.exchanges)
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
    if discovery.keyed:
        lines.append(
            "- **A candidate endpoint demanded credentials.** No authentication was "
            "attempted. A keyed endpoint closes Branch H on the free tier."
        )

    lines.extend(["", "## Branch H bar", "", "| clause | state |", "|---|---|"])
    for note in verdict.notes:
        clause, _, state = note.partition(": ")
        lines.append(f"| `{clause}` | {state} |")

    lines.extend(
        [
            "",
            "## Verdict",
            "",
            f"Satisfied: {', '.join(verdict.satisfied) or 'none'}",
            f"Refuted: {', '.join(verdict.refuted) or 'none'}",
            f"Unresolved: {', '.join(verdict.unresolved) or 'none'}",
            "",
            f"VERDICT: {verdict.verdict}",
        ]
    )
    return "\n".join(lines) + "\n"


# ==========================================================================
# Entry point
# ==========================================================================


def build_transport(
    shape: EndpointShape,
    *,
    budget: RequestBudget,
    user_agent: str,
) -> ProbeTransport:
    """One transport per candidate origin, allowlisted to that host alone."""
    return ProbeTransport(
        base_url=shape.base_url,
        allowed_hosts=frozenset({shape.host}),
        budget=budget,
        max_body_bytes=MAX_BODY_BYTES,
        user_agent=user_agent,
        accept="application/json",
        clock=time.time_ns,
    )


async def run_probe(
    factory: Callable[[EndpointShape], ProbeTransport],
    writer: ProbeEvidenceWriter,
    *,
    pause_seconds: float = 1.0,
) -> tuple[DiscoveryResult, tuple[ProbeStep, ...], ExecutionResult, tuple[ProbeStep, ...]]:
    """Discovery, then -- only if a shape was established -- the main plan."""
    discovery_plan = build_discovery_plan()
    discovery = await run_discovery(factory, writer, discovery_plan, pause_seconds=pause_seconds)
    if discovery.shape is None:
        plan = build_request_plan()
        execution = ExecutionResult(
            exchanges=(),
            outcomes=(),
            aborted=discovery.aborted,
            skipped=tuple(step.label for step in plan),
        )
        return discovery, plan, execution, discovery_plan
    plan = build_request_plan(discovery.shape, discovery.surface or "daily")
    execution = await execute(factory(discovery.shape), writer, plan, pause_seconds=pause_seconds)
    return discovery, plan, execution, discovery_plan


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
    planned = len(build_request_plan()) + DISCOVERY_BUDGET

    if os.environ.get(LIVE_ENV_VAR) != "1":
        sys.stderr.write(
            f"REFUSED: {LIVE_ENV_VAR}=1 is required before this probe may dispatch "
            f"any request. Planned steps: {planned} (budget {REQUEST_BUDGET}).\n"
        )
        return 2
    if not args.apply:
        sys.stderr.write(
            f"REFUSED: --apply is required. Planned steps: {planned} (budget {REQUEST_BUDGET}).\n"
        )
        return 2
    if not os.environ.get(USER_AGENT_ENV_VAR):
        sys.stderr.write(f"REFUSED: {USER_AGENT_ENV_VAR} must name a monitored contact.\n")
        return 2

    budget = RequestBudget(limit=REQUEST_BUDGET)
    user_agent = os.environ[USER_AGENT_ENV_VAR]
    writer = ProbeEvidenceWriter(Path(args.output_directory))

    def factory(shape: EndpointShape) -> ProbeTransport:
        return build_transport(shape, budget=budget, user_agent=user_agent)

    discovery, plan, execution, discovery_plan = asyncio.run(run_probe(factory, writer))
    questions = evaluate_questions(
        (*discovery_plan, *plan), (*discovery.outcomes, *execution.outcomes)
    )
    verdict = evaluate_verdict(questions, shape=discovery.shape, keyed=discovery.keyed)
    writer.write_report(
        "PROBE_REPORT.md",
        render_report(
            discovery=discovery,
            plan=plan,
            execution=execution,
            questions=questions,
            verdict=verdict,
            budget=budget,
        ),
    )
    sys.stderr.write(
        f"Probe A finished: {budget.spent}/{budget.limit} requests spent, "
        f"{len(discovery.exchanges) + len(execution.exchanges)} exchanges recorded in "
        f"{args.output_directory}. VERDICT: {verdict.verdict}\n"
    )
    return 1 if execution.aborted is not None else 0


if __name__ == "__main__":  # pragma: no cover - operator entry point
    raise SystemExit(main())
