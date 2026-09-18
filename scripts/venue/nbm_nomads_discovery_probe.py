#!/usr/bin/env python
"""FC-0a-3 -- one-shot NOMADS/NBM discovery probe (Seam A only).

EVIDENCE ONLY -- NEVER INGEST. Candidate URL shapes are UNVERIFIED constants.
Pinned ANSWERED/ABSENT values belong in a follow-up commit citing evidence.

Containment: ProbeTransport, allowed_hosts={nomads.ncep.noaa.gov}, hard
REQUEST_BUDGET=18, GET only, no host/URL flag or env override. Header-bearing
steps use probe_get_strict (FetchResult.headers); robots.txt uses probe_get.
Triple unlock: BREEZY_LIVE=1 + --apply + BREEZY_USER_AGENT.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import os
import re
import sys
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from email.utils import parsedate_to_datetime
from pathlib import Path

from breezy.ingest.http import FetchResult, RedirectError, TransportError
from breezy.ingest.probe_transport import (
    ProbeEvidenceWriter,
    ProbeExchange,
    ProbeTransport,
    RequestBudget,
    RequestBudgetExceededError,
)

HOST: str = "nomads.ncep.noaa.gov"
BASE_URL: str = f"https://{HOST}"
ALLOWED_HOSTS: frozenset[str] = frozenset({HOST})
MAX_BODY_BYTES: int = 4 * 1024 * 1024
REQUEST_BUDGET: int = 18
P1_INDEX_DESCENT_BUDGET: int = 3
P2_BULLETIN_SHAPES_BUDGET: int = 4
P3_CONDITIONAL_REGET_BUDGET: int = 2
P4_RETENTION_SAMPLES_BUDGET: int = 3
P5_RETROSPECTIVE_LAG_BUDGET: int = 4
P6_ROBOTS_BUDGET: int = 1
BUDGET_RESERVE: int = 1
MIN_REQUEST_INTERVAL_SECONDS: float = 1.0
LIVE_ENV_VAR: str = "BREEZY_LIVE"
USER_AGENT_ENV_VAR: str = "BREEZY_USER_AGENT"

QUESTIONS: tuple[str, ...] = (
    "q1_nbs_bulletin_path",
    "q2_last_modified_and_etag",
    "q3_body_size",
    "q4_cycles_per_day_with_txn",
    "q5_retention_horizon",
    "q6_station_block_grammar",
    "q7_robots_and_rate_limit",
    "q8_retrospective_lag_samples",
)
QUESTION_PRIORITY: tuple[str, ...] = (
    "q1_nbs_bulletin_path",
    "q3_body_size",
    "q2_last_modified_and_etag",
    "q8_retrospective_lag_samples",
    "q5_retention_horizon",
    "q4_cycles_per_day_with_txn",
    "q6_station_block_grammar",
    "q7_robots_and_rate_limit",
)
STATIONS: tuple[str, ...] = ("KLAX", "KMDW", "KMIA", "KSFO")

_NS = 1_000_000_000
_BLEND = "/pub/data/nccf/com/blend/prod"
_STATION_HEADER_RE = re.compile(
    r"^[ ]?(?P<icao>K[A-Z]{3})\s+NBM\s+NBS\s+GUIDANCE\b", re.MULTILINE
)
_TXN_ROW_RE = re.compile(r"^[ ]*TXN\b(?P<fields>.*)$", re.MULTILINE)
_ROW_RE = re.compile(r"^[ ]*(?P<id>[A-Z][A-Z0-9]{1,3})\s+\S", re.MULTILINE)
_TXN_FIELD_RE = re.compile(r"\d+")


@dataclass(frozen=True, slots=True)
class CandidateShape:
    name: str
    kind: str
    path_template: str
    rationale: str
    phase: str


def _shape(name: str, kind: str, path: str, why: str, phase: str) -> CandidateShape:
    return CandidateShape(name, kind, path, f"UNVERIFIED: {why}", phase)


#: UNVERIFIED. Every path/filename/cycle/retention claim is a hypothesis.
_C1 = f"{_BLEND}/blend.{{yyyymmdd}}"
_TEXT = f"{_C1}/{{hh}}/text"
CANDIDATE_SHAPES: tuple[CandidateShape, ...] = tuple(
    _shape(*row)
    for row in (
        ("blend_prod_index", "index", f"{_BLEND}/", "C1 blend prod root.", "p1_index"),
        ("blend_dated_index", "index", f"{_C1}/", "C1 dated cycle directory.", "p1_index"),
        ("blend_cycle_text_index", "index", f"{_TEXT}/", "C1 text/ of one cycle.", "p1_index"),
        (
            "collective_nbsta",
            "collective_bulletin",
            f"{_TEXT}/blend_nbsta.t{{hh}}z",
            "C2 collective NBS bulletin.",
            "p2_bulletin",
        ),
        (
            "per_station_nbsta_suffix",
            "per_station_bulletin",
            f"{_TEXT}/blend_nbsta.t{{hh}}z.{{icao}}",
            "C3 ICAO suffix.",
            "p2_bulletin",
        ),
        (
            "per_station_nbsta_prefix",
            "per_station_bulletin",
            f"{_TEXT}/{{icao}}.nbsta.t{{hh}}z",
            "C3 ICAO prefix.",
            "p2_bulletin",
        ),
        (
            "per_station_nbstx",
            "per_station_bulletin",
            f"{_TEXT}/blend_nbstx.t{{hh}}z.{{icao}}",
            "C3 NBS TX variant.",
            "p2_bulletin",
        ),
    )
)


@dataclass(frozen=True, slots=True)
class ProbeStep:
    label: str
    path: str
    phase: str
    questions: tuple[str, ...]
    rationale: str
    kind: str
    uses_strict: bool = False
    if_none_match: str | None = None
    if_modified_since: str | None = None
    allow_not_modified: bool = False


@dataclass(frozen=True, slots=True)
class ShapeVerdict:
    state: str
    station_blocks: int
    txn_groups: int
    row_count: int
    field_count: int


@dataclass(frozen=True, slots=True)
class TxnGroup:
    row_count: int
    field_count: int
    excerpt: str


@dataclass(frozen=True, slots=True)
class StepOutcome:
    label: str
    status_code: int
    succeeded: bool
    verdict: ShapeVerdict | None
    last_modified: str | None
    etag: str | None
    body_bytes: int
    path: str
    phase: str
    questions: tuple[str, ...]
    not_modified: bool = False


@dataclass(frozen=True, slots=True)
class QuestionAnswer:
    question: str
    state: str
    counts: Mapping[str, int]
    detail: str


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    exchanges: tuple[ProbeExchange, ...]
    outcomes: tuple[StepOutcome, ...]
    aborted: str | None
    skipped: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CycleIndexSample:
    cycle_hour: str
    cycle_date: str
    last_modified: str | None
    nominal_runtime_utc: str


@dataclass(frozen=True, slots=True)
class LagSample:
    cycle_hour: str
    station: str
    last_modified: str
    nominal_runtime_utc: str
    lag_seconds: int | None


def parse_station_blocks(text: str) -> tuple[str, ...]:
    """Split a bulletin into station blocks. Garbled input yields () and never raises."""
    if not text:
        return ()
    matches = list(_STATION_HEADER_RE.finditer(text))
    blocks = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        blocks.append(text[match.start() : end])
    return tuple(blocks)


def confirm_txn_group(block: str) -> TxnGroup | None:
    match = _TXN_ROW_RE.search(block)
    if match is None:
        return None
    fields = _TXN_FIELD_RE.findall(match.group("fields"))
    return TxnGroup(len(_ROW_RE.findall(block)), len(fields), block[:240])


def evaluate_shape_verdict(*, status_code: int, body: str | None) -> ShapeVerdict:
    """Classify a response. A 2xx without a TXN group is ABSENT with counts."""
    empty = ShapeVerdict("ABSENT", 0, 0, 0, 0)
    if not (200 <= status_code < 300) or not body:
        return empty
    blocks = parse_station_blocks(body)
    if not blocks:
        return empty
    txn_groups = 0
    row_count = 0
    field_count = 0
    for block in blocks:
        row_count += len(_ROW_RE.findall(block))
        confirmed = confirm_txn_group(block)
        if confirmed is not None:
            txn_groups += 1
            field_count += confirmed.field_count
    if txn_groups == 0:
        return ShapeVerdict("ABSENT", len(blocks), 0, row_count, 0)
    if field_count == 0:
        return ShapeVerdict("PARTIAL", len(blocks), txn_groups, row_count, 0)
    return ShapeVerdict("ANSWERED", len(blocks), txn_groups, row_count, field_count)


def reconstruct_lag_samples(
    samples: Sequence[CycleIndexSample],
    *,
    stations: Sequence[str] = STATIONS,
) -> tuple[LagSample, ...]:
    """Q8: Last-Modified vs the cycle's nominal runtime, per station."""
    out: list[LagSample] = []
    for sample in samples:
        if not sample.last_modified:
            continue
        try:
            modified = parsedate_to_datetime(sample.last_modified)
            if modified.tzinfo is None:
                modified = modified.replace(tzinfo=dt.UTC)
            nominal = dt.datetime.fromisoformat(sample.nominal_runtime_utc)
            if nominal.tzinfo is None:
                nominal = nominal.replace(tzinfo=dt.UTC)
            lag_seconds: int | None = int((modified - nominal).total_seconds())
        except (TypeError, ValueError, OverflowError):
            lag_seconds = None
        out.extend(
            LagSample(
                sample.cycle_hour,
                station,
                sample.last_modified,
                sample.nominal_runtime_utc,
                lag_seconds,
            )
            for station in stations
        )
    return tuple(out)


def _step(
    label: str,
    path: str,
    phase: str,
    questions: tuple[str, ...],
    rationale: str,
    kind: str,
    *,
    strict: bool = True,
    allow_not_modified: bool = False,
) -> ProbeStep:
    return ProbeStep(
        label, path, phase, questions, rationale, kind, strict, None, None, allow_not_modified
    )


_PHASE_Q: dict[str, tuple[str, ...]] = {
    "p1_index": ("q5_retention_horizon", "q4_cycles_per_day_with_txn"),
    "p2_bulletin": (
        "q1_nbs_bulletin_path",
        "q3_body_size",
        "q6_station_block_grammar",
        "q2_last_modified_and_etag",
    ),
}


def build_discovery_plan(
    *,
    cycle_date: str | None = None,
    cycle_hour: str | None = None,
) -> tuple[ProbeStep, ...]:
    """Cheapest-first plan. Early stop is applied at run time, not here."""
    now = dt.datetime.now(tz=dt.UTC)
    yyyymmdd = cycle_date or now.strftime("%Y%m%d")
    fmt = {"yyyymmdd": yyyymmdd, "hh": cycle_hour or "12", "icao": STATIONS[2]}
    steps = [
        _step(
            f"{shape.phase[:2]}_{shape.name}",
            shape.path_template.format(**fmt),
            shape.phase,
            _PHASE_Q[shape.phase],
            shape.rationale,
            shape.kind,
        )
        for shape in CANDIDATE_SHAPES
    ]
    index_path = next(s.path for s in steps if s.phase == "p1_index")
    bulletin_path = next(s.path for s in steps if s.phase == "p2_bulletin")
    for label, path, why in (
        ("p3_conditional_index", index_path, "directory index"),
        ("p3_conditional_bulletin", bulletin_path, "bulletin"),
    ):
        steps.append(
            _step(
                label,
                path,
                "p3_conditional",
                ("q2_last_modified_and_etag",),
                f"UNVERIFIED: conditional re-GET of the {why}.",
                "conditional",
                allow_not_modified=True,
            )
        )
    for delta_days in (1, 7, 30):
        older = (now - dt.timedelta(days=delta_days)).strftime("%Y%m%d")
        steps.append(
            _step(
                f"p4_retention_{older}",
                f"{_BLEND}/blend.{older}/",
                "p4_retention",
                ("q5_retention_horizon",),
                "UNVERIFIED: older dated index for the retention horizon.",
                "index",
            )
        )
    for hour in ("00", "06", "12", "18"):
        nominal = f"{yyyymmdd[:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:]}T{hour}:00:00+00:00"
        steps.append(
            _step(
                f"p5_lag_{yyyymmdd}_{hour}",
                f"{_BLEND}/blend.{yyyymmdd}/{hour}/text/",
                "p5_lag",
                ("q8_retrospective_lag_samples", "q4_cycles_per_day_with_txn"),
                f"UNVERIFIED: cycle-hour {hour}Z index (nominal {nominal}).",
                "index",
            )
        )
    steps.append(
        _step(
            "p6_robots",
            "/robots.txt",
            "p6_robots",
            ("q7_robots_and_rate_limit",),
            "robots.txt via ProbeTransport.probe_get, inside the budget.",
            "robots",
            strict=False,
        )
    )
    return tuple(steps)


def _stamp(transport: ProbeTransport) -> str:
    return dt.datetime.fromtimestamp(transport._clock() / _NS, tz=dt.UTC).isoformat(
        timespec="seconds"
    )


def _ex(
    transport: ProbeTransport,
    step: ProbeStep,
    url: str,
    status: int,
    body_bytes: int,
    content_type: str,
    outcome: str,
    sha256: str | None,
    text: str | None,
    finding: str | None,
) -> ProbeExchange:
    return ProbeExchange(
        transport._budget.spent,
        _stamp(transport),
        step.label,
        url,
        status,
        body_bytes,
        content_type,
        outcome,
        sha256,
        text,
        finding,
    )


def _from_result(transport: ProbeTransport, step: ProbeStep, result: FetchResult) -> ProbeExchange:
    if result.status_code == 304:
        return _ex(
            transport,
            step,
            result.url,
            304,
            0,
            result.headers.get("content-type", ""),
            "not_modified",
            None,
            None,
            None,
        )
    body = result.text or ""
    ok = 200 <= result.status_code < 300
    return _ex(
        transport,
        step,
        result.url,
        result.status_code,
        len(body.encode("utf-8")),
        result.headers.get("content-type", ""),
        "ok" if ok else f"http_{result.status_code}",
        result.sha256,
        result.text,
        None if ok else f"Server answered HTTP {result.status_code} (non-2xx).",
    )


async def _dispatch(
    transport: ProbeTransport, step: ProbeStep
) -> tuple[ProbeExchange, Mapping[str, str]]:
    if not step.uses_strict:
        return await transport.probe_get(step.path, label=step.label), {}
    try:
        result = await transport.probe_get_strict(
            step.path,
            if_none_match=step.if_none_match,
            if_modified_since=step.if_modified_since,
            allow_not_modified=step.allow_not_modified,
        )
    except RedirectError as exc:
        finding = (
            f"Server answered {exc.status_code} with Location={exc.location!r}. "
            "Redirects are NOT followed: recorded as an integrity finding."
        )
        alarm = _ex(
            transport,
            step,
            f"{BASE_URL}{step.path}",
            exc.status_code,
            0,
            "",
            "redirect_not_followed",
            None,
            None,
            finding,
        )
        return alarm, {}
    except TransportError as exc:
        alarm = _ex(
            transport,
            step,
            f"{BASE_URL}{step.path}",
            0,
            0,
            "",
            f"error:{type(exc).__name__}",
            None,
            None,
            f"{type(exc).__name__}: {exc}",
        )
        return alarm, {}
    headers = {key.lower(): value for key, value in result.headers.items()}
    return _from_result(transport, step, result), headers


def _outcome(step: ProbeStep, exchange: ProbeExchange, headers: Mapping[str, str]) -> StepOutcome:
    not_modified = exchange.status_code == 304 or exchange.outcome == "not_modified"
    verdict = (
        evaluate_shape_verdict(status_code=exchange.status_code, body=exchange.text)
        if exchange.succeeded
        else None
    )
    return StepOutcome(
        step.label,
        exchange.status_code,
        exchange.succeeded,
        verdict,
        headers.get("last-modified"),
        headers.get("etag"),
        exchange.body_bytes,
        step.path,
        step.phase,
        step.questions,
        not_modified,
    )


def _should_stop(phase: str, outcome: StepOutcome) -> bool:
    if phase == "p1_index":
        return outcome.succeeded
    if phase == "p2_bulletin":
        return outcome.verdict is not None and outcome.verdict.state == "ANSWERED"
    return False


async def execute(
    transport: ProbeTransport,
    writer: ProbeEvidenceWriter,
    plan: Sequence[ProbeStep],
    *,
    pause_seconds: float = MIN_REQUEST_INTERVAL_SECONDS,
    sleeper: Callable[[float], Awaitable[None]] | None = None,
    early_stop: bool = False,
) -> ExecutionResult:
    """Dispatch ``plan`` in order. Budget exhaustion aborts rather than over-spends."""
    sleep = sleeper if sleeper is not None else asyncio.sleep
    exchanges: list[ProbeExchange] = []
    outcomes: list[StepOutcome] = []
    aborted: str | None = None
    skipped: list[str] = []
    stop_phase: str | None = None
    index_meta: tuple[str | None, str | None, str | None] = (None, None, None)
    bulletin_meta: tuple[str | None, str | None, str | None] = (None, None, None)

    for index, step in enumerate(plan):
        if stop_phase is not None and step.phase == stop_phase:
            skipped.append(step.label)
            continue
        if stop_phase is not None and step.phase != stop_phase:
            stop_phase = None
        dispatch_step = step
        if early_stop and step.phase == "p3_conditional":
            etag, last_modified, path = (
                index_meta if "index" in step.label else bulletin_meta
            )
            if path is None or (etag is None and last_modified is None):
                skipped.append(step.label)
                continue
            dispatch_step = replace(
                step,
                path=path,
                if_none_match=etag,
                if_modified_since=last_modified,
                allow_not_modified=True,
            )
        try:
            exchange, headers = await _dispatch(transport, dispatch_step)
        except RequestBudgetExceededError as exc:
            aborted = f"Budget exhausted before `{step.label}`: {exc}"
            skipped.extend(later.label for later in plan[index:])
            break
        exchanges.append(exchange)
        writer.record(step.label, exchange)
        outcome = _outcome(dispatch_step, exchange, headers)
        outcomes.append(outcome)
        if step.phase == "p1_index" and outcome.succeeded:
            index_meta = (outcome.etag, outcome.last_modified, dispatch_step.path)
        if step.phase == "p2_bulletin" and outcome.succeeded:
            bulletin_meta = (outcome.etag, outcome.last_modified, dispatch_step.path)
        if early_stop and _should_stop(step.phase, outcome):
            stop_phase = step.phase
        will_dispatch_more = any(
            later.phase != stop_phase for later in plan[index + 1 :]
        ) if stop_phase is not None else index + 1 < len(plan)
        if pause_seconds > 0 and will_dispatch_more and aborted is None:
            await sleep(pause_seconds)
    return ExecutionResult(tuple(exchanges), tuple(outcomes), aborted, tuple(skipped))


async def run_probe(
    transport: ProbeTransport,
    writer: ProbeEvidenceWriter,
    *,
    pause_seconds: float = MIN_REQUEST_INTERVAL_SECONDS,
    sleeper: Callable[[float], Awaitable[None]] | None = None,
) -> ExecutionResult:
    """Walk phases cheapest-first; early-stop a phase on ANSWERED."""
    return await execute(
        transport,
        writer,
        build_discovery_plan(),
        pause_seconds=pause_seconds,
        sleeper=sleeper,
        early_stop=True,
    )


def _answer(question: str, state: str, counts: Mapping[str, int], detail: str) -> QuestionAnswer:
    return QuestionAnswer(question, state, counts, detail)


def evaluate_questions(
    plan: Sequence[ProbeStep],
    outcomes: Sequence[StepOutcome],
) -> dict[str, QuestionAnswer]:
    """Mark every pre-registered question; anything unreached is UNANSWERED."""
    _ = plan
    answers = {
        question: _answer(question, "UNANSWERED", {}, "not reached in this run")
        for question in QUESTIONS
    }
    for outcome in outcomes:
        verdict = outcome.verdict
        for question in outcome.questions:
            if question == "q1_nbs_bulletin_path" and verdict is not None:
                answers[question] = _answer(
                    question,
                    verdict.state,
                    {
                        "station_blocks": verdict.station_blocks,
                        "txn_groups": verdict.txn_groups,
                        "row_count": verdict.row_count,
                        "field_count": verdict.field_count,
                    },
                    f"{outcome.label} path={outcome.path} state={verdict.state}",
                )
            elif question == "q3_body_size" and outcome.body_bytes > 0:
                answers[question] = _answer(
                    question,
                    "ANSWERED",
                    {"bytes": outcome.body_bytes},
                    f"{outcome.label} measured {outcome.body_bytes} bytes",
                )
            elif question == "q2_last_modified_and_etag":
                counts = {
                    "has_last_modified": int(bool(outcome.last_modified)),
                    "has_etag": int(bool(outcome.etag)),
                    "not_modified": int(outcome.not_modified),
                }
                if any(counts.values()):
                    answers[question] = _answer(
                        question,
                        "ANSWERED",
                        counts,
                        (
                            f"{outcome.label} Last-Modified={outcome.last_modified!r} "
                            f"ETag={outcome.etag!r} 304={outcome.not_modified}"
                        ),
                    )
            elif question == "q6_station_block_grammar" and verdict and verdict.station_blocks:
                answers[question] = _answer(
                    question,
                    "ANSWERED" if verdict.txn_groups else "PARTIAL",
                    {"station_blocks": verdict.station_blocks},
                    f"{outcome.label} blocks={verdict.station_blocks}",
                )
            elif question == "q7_robots_and_rate_limit":
                answers[question] = _answer(
                    question,
                    "ANSWERED" if outcome.status_code else "ABSENT",
                    {"status": outcome.status_code, "bytes": outcome.body_bytes},
                    f"robots.txt HTTP {outcome.status_code}",
                )
            elif question in {"q4_cycles_per_day_with_txn", "q5_retention_horizon"}:
                state = "ANSWERED" if outcome.succeeded else "ABSENT"
                if answers[question].state != "ANSWERED":
                    answers[question] = _answer(
                        question,
                        state,
                        {"status": outcome.status_code, "bytes": outcome.body_bytes},
                        f"{outcome.label} HTTP {outcome.status_code}",
                    )
            elif question == "q8_retrospective_lag_samples":
                hour = outcome.label.rsplit("_", 1)[-1]
                match = re.search(r"p5_lag_(\d{8})_", outcome.label)
                date_token = match.group(1) if match is not None else ""
                nominal = (
                    f"{date_token[:4]}-{date_token[4:6]}-{date_token[6:]}T{hour}:00:00+00:00"
                    if date_token
                    else ""
                )
                samples = reconstruct_lag_samples(
                    [
                        CycleIndexSample(
                            hour, date_token, outcome.last_modified, nominal
                        )
                    ]
                )
                if samples:
                    answers[question] = _answer(
                        question,
                        "ANSWERED",
                        {"lag_samples": len(samples)},
                        f"{len(samples)} retrospective (cycle_hour, station) lag samples",
                    )
    return answers


def render_report(
    *,
    questions: Mapping[str, QuestionAnswer],
    execution: ExecutionResult,
    budget: RequestBudget,
    plan: Sequence[ProbeStep],
) -> str:
    lines = [
        "# NOMADS/NBM discovery probe (FC-0a-3 Seam A)",
        "",
        "## EVIDENCE ONLY - NEVER INGEST",
        "",
        "These captures must NEVER be ingested into any production catalog.",
        "",
        f"Host: `{HOST}` (settlement host NOT touched)",
        f"Transport: ProbeTransport, max_body_bytes={MAX_BODY_BYTES}",
        f"Request budget: {budget.limit} hard; spent {budget.spent}.",
        f"Planned steps: {len(plan)}; dispatched: {len(execution.exchanges)}.",
        f"Stations: {', '.join(STATIONS)}.",
        "",
        "Candidate URL shapes in this module are UNVERIFIED constants.",
        "",
        "## Outcomes",
        "",
        "| # | label | status | bytes | outcome |",
        "|--:|---|--:|--:|---|",
    ]
    if execution.exchanges:
        lines.extend(
            f"| {ex.ordinal} | `{ex.label}` | {ex.status_code} | {ex.body_bytes} | {ex.outcome} |"
            for ex in execution.exchanges
        )
    else:
        lines.append("| - | *none dispatched* | - | - | - |")
    if execution.aborted is not None:
        skipped = ", ".join(f"`{label}`" for label in execution.skipped) or "none"
        lines.extend(["", "## RUN ABORTED", "", execution.aborted, "", f"Skipped: {skipped}"])
    lines.extend(["", "## Questions", ""])
    for question in QUESTIONS:
        answer = questions[question]
        counts = ", ".join(f"{key}={value}" for key, value in answer.counts.items())
        suffix = f" ({counts})" if counts else ""
        lines.append(f"- `{question}`: {answer.state}{suffix} — {answer.detail}")
    lines.extend(["", "## Findings", ""])
    findings = [ex for ex in execution.exchanges if ex.finding is not None]
    if findings:
        lines.extend(f"- `{ex.label}` (HTTP {ex.status_code}): {ex.finding}" for ex in findings)
    else:
        lines.append("- No transport alarm was recorded.")
    answered = sum(1 for item in questions.values() if item.state == "ANSWERED")
    lines.extend(["", f"VERDICT: {answered}/{len(QUESTIONS)} questions ANSWERED"])
    return "\n".join(lines) + "\n"


def build_transport(*, budget: RequestBudget, user_agent: str) -> ProbeTransport:
    return ProbeTransport(
        base_url=BASE_URL,
        allowed_hosts=ALLOWED_HOSTS,
        budget=budget,
        max_body_bytes=MAX_BODY_BYTES,
        user_agent=user_agent,
        accept="text/plain",
        clock=time.time_ns,
    )


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, add_help=True)
    parser.add_argument("--output-directory", required=True)
    parser.add_argument("--apply", action="store_true")
    return parser.parse_args(list(argv))


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point. Refuses to dispatch without the explicit live unlock."""
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    planned = len(build_discovery_plan())
    if os.environ.get(LIVE_ENV_VAR) != "1":
        sys.stderr.write(
            f"REFUSED: {LIVE_ENV_VAR}=1 is required before this probe may dispatch "
            f"any request. Planned steps: {planned} (budget {REQUEST_BUDGET}).\n"
        )
        return 2
    if not args.apply:
        sys.stderr.write(
            f"REFUSED: --apply is required. Planned steps: {planned} "
            f"(budget {REQUEST_BUDGET}).\n"
        )
        return 2
    if not os.environ.get(USER_AGENT_ENV_VAR):
        sys.stderr.write(f"REFUSED: {USER_AGENT_ENV_VAR} must name a monitored contact.\n")
        return 2
    budget = RequestBudget(limit=REQUEST_BUDGET)
    writer = ProbeEvidenceWriter(Path(args.output_directory))
    transport = build_transport(budget=budget, user_agent=os.environ[USER_AGENT_ENV_VAR])
    execution = asyncio.run(run_probe(transport, writer))
    plan = build_discovery_plan()
    questions = evaluate_questions(plan, execution.outcomes)
    writer.write_report(
        "PROBE_REPORT.md",
        render_report(questions=questions, execution=execution, budget=budget, plan=plan),
    )
    sys.stderr.write(
        f"NOMADS/NBM discovery finished: {budget.spent}/{budget.limit} requests spent, "
        f"{len(execution.exchanges)} exchanges recorded in {args.output_directory}.\n"
    )
    return 1 if execution.aborted is not None else 0


if __name__ == "__main__":  # pragma: no cover - operator entry point
    raise SystemExit(main())
