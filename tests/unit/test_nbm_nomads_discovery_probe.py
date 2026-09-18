"""Unit coverage for FC-0a-3 -- the NOMADS/NBM discovery probe (Seam A only).

Authority: ``docs/plans/FORECAST_EDGE_FAMILY_Rev5_2026-09-18.md`` section 4.11
and the peer-approved FC-0a-3 plan. This is a one-shot, budget-capped,
HUMAN-RUN discovery probe. It does not harvest a lag statistic, does not
install a timer, and does not write a collector.

**Every test in this module runs against fixtures.** ``tests/conftest.py``
blocks real sockets for anything not marked ``live``/``allow_socket``, and
nothing here carries either marker. Structural containment (settlement-host
ban, write-verb ban, ``.probe.json`` suffix, live unlock, census widening)
is asserted alongside the other probes in ``tests/unit/test_probe_containment.py``.
"""

from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Final

import httpx
import pytest
import respx

from breezy.ingest.probe_transport import (
    SETTLEMENT_HOSTS,
    ProbeEvidenceWriter,
    ProbeTransport,
    RequestBudget,
    RequestBudgetExceededError,
    SettlementHostForbiddenError,
)
from breezy.ingest.shared_state import DEFAULT_ALLOWED_HOSTS

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
PROBE_PATH: Final[Path] = REPO_ROOT / "scripts/venue/nbm_nomads_discovery_probe.py"

PROBE_UA: Final[str] = "breezy-probe (contact: ops@example.invalid)"

_NOMADS_HOST: Final[str] = "nomads.ncep.noaa.gov"

#: A served NBS station block that has rows but NO TXN group. T8's datum.
_NO_TXN_BULLETIN: Final[str] = (
    " KMIA   NBM  NBS GUIDANCE  9/17/2026  1200 UTC\n"
    "\n"
    " UTC  18 21 00 03 06 09 12\n"
    " TMP  86 84 82 80 78 77 76\n"
    " DPT  74 74 73 73 74 74 74\n"
)

#: Bytes that are within any reasonable body cap and are not a bulletin.
_GARBLED_BODY: Final[str] = "<<<\x00not a bulletin>>>\n???? #####\n" * 8


def _load_script(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"breezy_probe_{path.stem}", path)
    if spec is None or spec.loader is None:  # pragma: no cover - import plumbing
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


probe = _load_script(PROBE_PATH)


def _clock() -> int:
    return 1_700_000_000_000_000_000


def _transport(*, budget: RequestBudget | None = None) -> ProbeTransport:
    return ProbeTransport(
        base_url=probe.BASE_URL,
        allowed_hosts=probe.ALLOWED_HOSTS,
        budget=budget if budget is not None else RequestBudget(limit=probe.REQUEST_BUDGET),
        max_body_bytes=probe.MAX_BODY_BYTES,
        user_agent=PROBE_UA,
        accept="text/plain",
        clock=_clock,
    )


def _add_argument_flags(tree: ast.AST) -> set[str]:
    flags: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == "add_argument":
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    flags.add(arg.value)
    return flags


# ==========================================================================
# T1 -- the probe transport can only reach NOMADS
# ==========================================================================


def test_the_probe_transport_can_only_reach_nomads() -> None:
    assert probe.HOST == _NOMADS_HOST
    assert probe.BASE_URL == f"https://{_NOMADS_HOST}"
    assert probe.ALLOWED_HOSTS == frozenset({_NOMADS_HOST})
    for shape in probe.CANDIDATE_SHAPES:
        assert "UNVERIFIED" in shape.rationale
        assert shape.path_template.startswith("/")
        assert "://" not in shape.path_template
        assert "nomads" not in shape.path_template
    transport = _transport()
    assert transport._base_url == probe.BASE_URL


# ==========================================================================
# T2 -- never aimable at the settlement host
# ==========================================================================


def test_the_probe_transport_can_never_be_aimed_at_the_settlement_host() -> None:
    assert not (probe.ALLOWED_HOSTS & SETTLEMENT_HOSTS)
    source = PROBE_PATH.read_text(encoding="utf-8")
    assert "api.weather.gov" not in source
    assert "weather.gov" not in source
    for host in sorted(SETTLEMENT_HOSTS):
        with pytest.raises(SettlementHostForbiddenError):
            ProbeTransport(
                base_url=f"https://{host}",
                allowed_hosts=frozenset({host}),
                budget=RequestBudget(limit=1),
                max_body_bytes=probe.MAX_BODY_BYTES,
                user_agent=PROBE_UA,
                accept="text/plain",
                clock=_clock,
            )
    with pytest.raises(SettlementHostForbiddenError):
        ProbeTransport(
            base_url=probe.BASE_URL,
            allowed_hosts=probe.ALLOWED_HOSTS | SETTLEMENT_HOSTS,
            budget=RequestBudget(limit=1),
            max_body_bytes=probe.MAX_BODY_BYTES,
            user_agent=PROBE_UA,
            accept="text/plain",
            clock=_clock,
        )


# ==========================================================================
# T3 -- no argv / env retarget
# ==========================================================================


def test_the_probe_cannot_be_re_aimed_through_argv_or_the_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = PROBE_PATH.read_text(encoding="utf-8")
    flags = _add_argument_flags(ast.parse(source))
    assert "--host" not in flags
    assert "--base-url" not in flags
    assert "--url" not in flags
    with pytest.raises(SystemExit):
        probe._parse_args(["--output-directory", str(tmp_path), "--host", "evil.example"])
    with pytest.raises(SystemExit):
        probe._parse_args(["--output-directory", str(tmp_path), "--base-url", "https://evil.example"])
    with pytest.raises(SystemExit):
        probe._parse_args(["--output-directory", str(tmp_path), "--url", "https://evil.example/x"])

    monkeypatch.setenv("NOMADS_HOST", "evil.example")
    monkeypatch.setenv("BREEZY_NOMADS_HOST", "evil.example")
    monkeypatch.setenv("BREEZY_PROBE_HOST", "evil.example")
    monkeypatch.setenv("BREEZY_BASE_URL", "https://evil.example")
    reloaded = _load_script(PROBE_PATH)
    assert reloaded.HOST == _NOMADS_HOST
    assert reloaded.BASE_URL == f"https://{_NOMADS_HOST}"
    assert reloaded.ALLOWED_HOSTS == frozenset({_NOMADS_HOST})


# ==========================================================================
# T4 -- shipped default allowlist is untouched
# ==========================================================================


def test_the_probe_does_not_widen_the_shipped_default_allowlist() -> None:
    assert SETTLEMENT_HOSTS <= DEFAULT_ALLOWED_HOSTS
    assert not (probe.ALLOWED_HOSTS & DEFAULT_ALLOWED_HOSTS)
    tree = ast.parse(PROBE_PATH.read_text(encoding="utf-8"))
    referenced = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    referenced |= {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    referenced |= {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    assert "DEFAULT_ALLOWED_HOSTS" not in referenced
    assert "VENUE" not in referenced
    assert "default_registry" not in referenced
    assert "breezy.registry" not in {
        module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
        for module in (node.module,)
    }


# ==========================================================================
# T5 -- the run aborts rather than over-spending
# ==========================================================================


@respx.mock
@pytest.mark.asyncio
async def test_the_run_aborts_rather_than_over_spending_the_hard_budget(
    tmp_path: Path,
) -> None:
    route = respx.get(url__startswith=probe.BASE_URL).mock(
        return_value=httpx.Response(404, text="nope")
    )
    plan = probe.build_discovery_plan()
    assert len(plan) > 2
    budget = RequestBudget(limit=2)
    transport = _transport(budget=budget)
    writer = ProbeEvidenceWriter(tmp_path)
    result = await probe.execute(transport, writer, plan, pause_seconds=0)
    assert budget.spent == 2
    assert budget.spent <= budget.limit
    assert result.aborted is not None
    assert route.call_count == 2
    with pytest.raises(RequestBudgetExceededError):
        await transport.probe_get("/overspend", label="overspend")
    assert route.call_count == 2


# ==========================================================================
# T6 -- phase sub-ceilings sum to no more than the hard budget
# ==========================================================================


def test_phase_budgets_sum_to_no_more_than_the_hard_budget() -> None:
    assert probe.REQUEST_BUDGET == 18
    assert probe.P1_INDEX_DESCENT_BUDGET == 3
    assert probe.P2_BULLETIN_SHAPES_BUDGET == 4
    assert probe.P3_CONDITIONAL_REGET_BUDGET == 2
    assert probe.P4_RETENTION_SAMPLES_BUDGET == 3
    assert probe.P5_RETROSPECTIVE_LAG_BUDGET == 4
    assert probe.P6_ROBOTS_BUDGET == 1
    assert probe.BUDGET_RESERVE == 1
    committed = (
        probe.P1_INDEX_DESCENT_BUDGET
        + probe.P2_BULLETIN_SHAPES_BUDGET
        + probe.P3_CONDITIONAL_REGET_BUDGET
        + probe.P4_RETENTION_SAMPLES_BUDGET
        + probe.P5_RETROSPECTIVE_LAG_BUDGET
        + probe.P6_ROBOTS_BUDGET
        + probe.BUDGET_RESERVE
    )
    assert committed <= probe.REQUEST_BUDGET
    assert probe.QUESTION_PRIORITY == (
        "q1_nbs_bulletin_path",
        "q3_body_size",
        "q2_last_modified_and_etag",
        "q8_retrospective_lag_samples",
        "q5_retention_horizon",
        "q4_cycles_per_day_with_txn",
        "q6_station_block_grammar",
        "q7_robots_and_rate_limit",
    )
    plan = probe.build_discovery_plan()
    by_phase: dict[str, int] = {}
    for step in plan:
        by_phase[step.phase] = by_phase.get(step.phase, 0) + 1
    assert by_phase.get("p1_index", 0) <= probe.P1_INDEX_DESCENT_BUDGET
    assert by_phase.get("p2_bulletin", 0) <= probe.P2_BULLETIN_SHAPES_BUDGET
    assert by_phase.get("p3_conditional", 0) <= probe.P3_CONDITIONAL_REGET_BUDGET
    assert by_phase.get("p4_retention", 0) <= probe.P4_RETENTION_SAMPLES_BUDGET
    assert by_phase.get("p5_lag", 0) <= probe.P5_RETROSPECTIVE_LAG_BUDGET
    assert by_phase.get("p6_robots", 0) <= probe.P6_ROBOTS_BUDGET
    assert len(plan) <= probe.REQUEST_BUDGET - probe.BUDGET_RESERVE


# ==========================================================================
# T7 -- every dispatched request is a GET, paced to the minimum interval
# ==========================================================================


@respx.mock
@pytest.mark.asyncio
async def test_every_dispatched_request_is_a_get_and_is_paced_to_the_minimum_interval(
    tmp_path: Path,
) -> None:
    assert probe.MIN_REQUEST_INTERVAL_SECONDS >= 1.0
    source = PROBE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and node.value == "HEAD":
            pytest.fail("a HEAD verb is constructible in the probe module")
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "head"
        ):
            pytest.fail("a .head() call is constructible in the probe module")

    route = respx.route(host=_NOMADS_HOST).mock(return_value=httpx.Response(404, text="nope"))
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    budget = RequestBudget(limit=3)
    transport = _transport(budget=budget)
    writer = ProbeEvidenceWriter(tmp_path)
    plan = probe.build_discovery_plan()[:3]
    await probe.execute(
        transport,
        writer,
        plan,
        pause_seconds=probe.MIN_REQUEST_INTERVAL_SECONDS,
        sleeper=fake_sleep,
    )
    assert route.call_count == 3
    assert all(call.request.method == "GET" for call in route.calls)
    assert sleeps == [probe.MIN_REQUEST_INTERVAL_SECONDS, probe.MIN_REQUEST_INTERVAL_SECONDS]


# ==========================================================================
# T8 -- 2xx without a TXN group is ABSENT, with counts
# ==========================================================================


def test_a_2xx_without_a_txn_group_is_recorded_absent_with_its_counts() -> None:
    verdict = probe.evaluate_shape_verdict(status_code=200, body=_NO_TXN_BULLETIN)
    assert verdict.state == "ABSENT"
    assert verdict.station_blocks >= 1
    assert verdict.txn_groups == 0
    assert verdict.row_count >= 1
    assert verdict.field_count == 0


# ==========================================================================
# T9 -- garbled body within the size cap parses to zero blocks, no raise
# ==========================================================================


def test_a_garbled_body_within_the_size_cap_parses_to_zero_blocks_without_raising() -> None:
    assert len(_GARBLED_BODY.encode("utf-8")) < probe.MAX_BODY_BYTES
    blocks = probe.parse_station_blocks(_GARBLED_BODY)
    assert blocks == ()
    verdict = probe.evaluate_shape_verdict(status_code=200, body=_GARBLED_BODY)
    assert verdict.state == "ABSENT"
    assert verdict.station_blocks == 0
    assert verdict.txn_groups == 0
    assert verdict.row_count == 0
    assert verdict.field_count == 0


# ==========================================================================
# T10 -- a redirect is recorded and never followed
# ==========================================================================


@respx.mock
@pytest.mark.asyncio
async def test_a_redirect_is_recorded_and_never_followed(tmp_path: Path) -> None:
    moved = f"{probe.BASE_URL}/pub/data/nccf/com/blend/prod/"
    elsewhere = f"{probe.BASE_URL}/elsewhere"
    respx.get(moved).mock(return_value=httpx.Response(302, headers={"location": elsewhere}))
    followed = respx.get(elsewhere).mock(return_value=httpx.Response(200, text="chased"))
    transport = _transport()
    writer = ProbeEvidenceWriter(tmp_path)
    step = next(step for step in probe.build_discovery_plan() if step.phase == "p1_index")
    result = await probe.execute(transport, writer, (step,), pause_seconds=0)
    assert followed.call_count == 0
    assert result.exchanges
    exchange = result.exchanges[0]
    assert exchange.status_code == 302
    assert exchange.outcome == "redirect_not_followed"
    assert exchange.finding is not None


# ==========================================================================
# T11 -- refuses to dispatch without the triple live unlock
# ==========================================================================


def test_the_probe_refuses_to_dispatch_without_the_live_unlock(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("BREEZY_LIVE", raising=False)
    monkeypatch.delenv("BREEZY_USER_AGENT", raising=False)
    assert probe.main(["--output-directory", str(tmp_path), "--apply"]) != 0

    monkeypatch.setenv("BREEZY_LIVE", "1")
    monkeypatch.delenv("BREEZY_USER_AGENT", raising=False)
    assert probe.main(["--output-directory", str(tmp_path), "--apply"]) != 0

    monkeypatch.setenv("BREEZY_USER_AGENT", PROBE_UA)
    monkeypatch.delenv("BREEZY_LIVE", raising=False)
    assert probe.main(["--output-directory", str(tmp_path), "--apply"]) != 0

    monkeypatch.setenv("BREEZY_LIVE", "1")
    monkeypatch.setenv("BREEZY_USER_AGENT", PROBE_UA)
    assert probe.main(["--output-directory", str(tmp_path)]) != 0


# ==========================================================================
# T12 -- every pre-registered question appears in the report
# ==========================================================================


def test_every_pre_registered_question_appears_in_the_report(tmp_path: Path) -> None:
    assert probe.STATIONS == ("KLAX", "KMDW", "KMIA", "KSFO")
    assert probe.QUESTIONS == (
        "q1_nbs_bulletin_path",
        "q2_last_modified_and_etag",
        "q3_body_size",
        "q4_cycles_per_day_with_txn",
        "q5_retention_horizon",
        "q6_station_block_grammar",
        "q7_robots_and_rate_limit",
        "q8_retrospective_lag_samples",
    )
    plan = probe.build_discovery_plan()
    questions = probe.evaluate_questions(plan, ())
    assert set(questions) == set(probe.QUESTIONS)
    assert all(answer.state == "UNANSWERED" for answer in questions.values())
    budget = RequestBudget(limit=probe.REQUEST_BUDGET)
    report = probe.render_report(
        questions=questions,
        execution=probe.ExecutionResult(exchanges=(), outcomes=(), aborted=None, skipped=()),
        budget=budget,
        plan=plan,
    )
    for question in probe.QUESTIONS:
        assert question in report
    assert "UNANSWERED" in report


# ==========================================================================
# T15 -- robots.txt is fetched through the probe transport, inside the budget
# ==========================================================================


@respx.mock
@pytest.mark.asyncio
async def test_robots_txt_is_fetched_through_the_probe_transport_and_inside_the_budget(
    tmp_path: Path,
) -> None:
    robots_url = f"{probe.BASE_URL}/robots.txt"
    route = respx.get(robots_url).mock(
        return_value=httpx.Response(200, text="User-agent: *\nDisallow:\n")
    )
    other = respx.route(host=_NOMADS_HOST).mock(return_value=httpx.Response(404, text="nope"))
    plan = probe.build_discovery_plan()
    robots_steps = [step for step in plan if step.path == "/robots.txt"]
    assert len(robots_steps) == 1
    assert robots_steps[0].phase == "p6_robots"
    budget = RequestBudget(limit=1)
    transport = _transport(budget=budget)
    writer = ProbeEvidenceWriter(tmp_path)
    result = await probe.execute(transport, writer, tuple(robots_steps), pause_seconds=0)
    assert route.call_count == 1
    assert route.calls[0].request.method == "GET"
    assert str(route.calls[0].request.url) == robots_url
    assert other.call_count == 0
    assert budget.spent == 1
    assert result.exchanges[0].status_code == 200
    source = PROBE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    assert "breezy.ingest.probe_transport" in {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
