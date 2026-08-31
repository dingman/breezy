"""P2 Probe B report logic: a non-2xx is a finding, and the verdict is computed.

Authority: ``docs/plans/DATA_CAPTURE_AND_RISK_PLAN.md`` section 4.P2.

Why this suite exists
---------------------
``docs/evidence/open_meteo_previous_runs_probe_2026-08-31T003816Z`` (Probe A's
first live run) reported every step ``ok``, every question ``answered`` and
"Findings: None recorded" -- off 22 consecutive HTTP 404s. The transport was
hardened afterwards (``probe_transport.ProbeExchange.finding``), but the
**per-probe report logic is separate code**, and Probe B was written alongside
Probe A's defective version. These tests pin, for Probe B, the four properties
Probe A had to be given:

1. a non-2xx is a FINDING and contributes nothing to the census;
2. a step counts only when a 2xx **actually yielded the datum it was designed
   to extract** -- a served response is not a served product;
3. a failed BASELINE aborts the remaining plan instead of spending the budget
   re-learning the same failure;
4. the report ends in an explicit ``VERDICT: PASS``/``VERDICT: FAIL`` derived
   from the counted set, never left to the reader.

Plus one defect specific to Probe B: the pre-registered bar says "spanning >= 2
sites", and two PIL types retrieved for ONE city must not be counted as two.

Every test here runs against fixtures; nothing carries ``live``/``allow_socket``.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Final

import httpx
import pytest
import respx

from breezy.ingest.probe_transport import (
    ProbeEvidenceWriter,
    ProbeExchange,
    ProbeTransport,
    RequestBudget,
)

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
PROBE_B_PATH: Final[Path] = REPO_ROOT / "scripts/venue/iem_afos_forecast_pil_probe.py"
PROBE_UA: Final[str] = "breezy-probe (contact: ops@example.invalid)"


def _load_script(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"breezy_probe_report_{path.stem}", path)
    if spec is None or spec.loader is None:  # pragma: no cover - import plumbing
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


probe_b = _load_script(PROBE_B_PATH)

AFOS_URL: Final[str] = f"{probe_b.BASE_URL}/cgi-bin/afos/retrieve.py"

#: What IEM AFOS returns when a PIL genuinely has no products in the window.
EMPTY_BODY: Final[str] = ""

#: A non-2xx body. It is captured as evidence, and it must never be parsed as
#: a product -- note that it deliberately contains a string a permissive
#: parser could mistake for a daily high.
ERROR_BODY: Final[str] = "<html><body>Not Found. HIGH NEAR 88.</body></html>"


def _product(*, office: str = "KOKX", ddhhmm: str = "301130", high: str = "88") -> str:
    return (
        f"FXUS61 {office} {ddhhmm}\n"
        f"ZFP{office[1:]}\n"
        "ZONE FORECAST PRODUCT\n"
        "NATIONAL WEATHER SERVICE NEW YORK NY\n"
        "730 AM EDT SUN AUG 30 2026\n"
        "\n"
        "NYZ072-301800-\n"
        "NEW YORK (MANHATTAN)-\n"
        "\n"
        f".TODAY...SUNNY. HIGH NEAR {high}.\n"
    )


def _bundle(count: int, *, office: str = "KOKX") -> str:
    """``count`` products, concatenated the way IEM's ``fmt=text`` emits them."""
    return "\x03".join(_product(office=office, ddhhmm=f"3011{index:02d}") for index in range(count))


def _exchange(
    *,
    label: str,
    status: int = 200,
    body: str | None = None,
    ordinal: int = 1,
) -> ProbeExchange:
    ok = 200 <= status < 300
    return ProbeExchange(
        ordinal=ordinal,
        requested_at_utc="2026-08-31T00:00:00+00:00",
        label=label,
        url=f"{AFOS_URL}?label={label}",
        status_code=status,
        body_bytes=len(body.encode("utf-8")) if body is not None else 0,
        content_type="text/plain",
        outcome="ok" if ok else f"http_{status}",
        sha256="0" * 64 if body is not None else None,
        text=body,
        finding=None if ok else f"Server answered HTTP {status} (non-2xx).",
    )


def _transport(budget: RequestBudget) -> ProbeTransport:
    return ProbeTransport(
        base_url=probe_b.BASE_URL,
        allowed_hosts=probe_b.ALLOWED_HOSTS,
        budget=budget,
        max_body_bytes=probe_b.MAX_BODY_BYTES,
        user_agent=PROBE_UA,
        accept="text/plain",
        clock=lambda: 1_700_000_000_000_000_000,
    )


def _step(label: str, city: str, *, baseline: bool = False) -> Any:
    return probe_b.ProbeStep(
        label=label,
        city=city,
        path="/cgi-bin/afos/retrieve.py",
        query={"pil": "ZFPOKX"},
        rationale="fixture",
        baseline=baseline,
    )


# ==========================================================================
# 1. A non-2xx is a FINDING and yields nothing
# ==========================================================================


def test_a_non_2xx_step_yields_no_product_and_records_why() -> None:
    outcome = probe_b.evaluate_step(
        _step("zfp_nyc", "NYC"), _exchange(label="zfp_nyc", status=404, body=ERROR_BODY)
    )

    assert outcome.succeeded is False
    assert outcome.products == ()
    assert outcome.reason is not None
    assert "404" in outcome.reason


def test_a_non_2xx_body_never_reaches_the_census() -> None:
    """The 404 body carries `HIGH NEAR 88`; counting it would fabricate a datum."""
    outcomes = (
        probe_b.evaluate_step(
            _step("zfp_nyc", "NYC"), _exchange(label="zfp_nyc", status=404, body=ERROR_BODY)
        ),
    )

    census = probe_b.census_from_outcomes(outcomes, {"NYC": "KOKX"})

    assert census.products == 0
    assert census.highs_extracted == 0
    assert probe_b.evaluate_verdict(census).passed is False


# ==========================================================================
# 2. A 2xx counts only when it actually yielded the datum
# ==========================================================================


def test_a_2xx_that_carried_no_product_is_not_a_yield() -> None:
    outcome = probe_b.evaluate_step(
        _step("zfp_nyc", "NYC"), _exchange(label="zfp_nyc", status=200, body=EMPTY_BODY)
    )

    assert outcome.succeeded is True
    assert outcome.products == ()
    assert outcome.reason is not None
    assert "no" in outcome.reason.lower()


def test_a_2xx_that_yielded_products_is_counted() -> None:
    outcome = probe_b.evaluate_step(
        _step("zfp_nyc", "NYC"), _exchange(label="zfp_nyc", status=200, body=_bundle(3))
    )

    assert outcome.succeeded is True
    assert len(outcome.products) == 3
    assert outcome.reason is None

    census = probe_b.census_from_outcomes((outcome,), {"NYC": "KOKX"})
    assert census.products == 3
    assert census.highs_extracted == 3
    assert census.issuance_recoverable == 3
    assert census.office_attributable == 3


def test_a_product_from_another_office_is_not_office_attributable() -> None:
    outcome = probe_b.evaluate_step(
        _step("zfp_nyc", "NYC"),
        _exchange(label="zfp_nyc", status=200, body=_bundle(2, office="KPHI")),
    )

    census = probe_b.census_from_outcomes((outcome,), {"NYC": "KOKX"})

    assert census.products == 2
    assert census.office_attributable == 0


# ==========================================================================
# 3. "Spanning >= 2 sites" means two SITES, not two PIL types for one site
# ==========================================================================


def test_two_pil_types_for_one_city_count_as_one_site() -> None:
    outcomes = (
        probe_b.evaluate_step(
            _step("afd_nyc", "NYC"), _exchange(label="afd_nyc", status=200, body=_bundle(30))
        ),
        probe_b.evaluate_step(
            _step("zfp_nyc", "NYC"), _exchange(label="zfp_nyc", status=200, body=_bundle(30))
        ),
    )

    census = probe_b.census_from_outcomes(outcomes, {"NYC": "KOKX"})

    assert census.products == 60
    assert census.sites == 1, "two PILs retrieved for ONE city are one site, not two"
    assert probe_b.evaluate_verdict(census).passed is False


def test_two_cities_count_as_two_sites() -> None:
    outcomes = (
        probe_b.evaluate_step(
            _step("zfp_nyc", "NYC"), _exchange(label="zfp_nyc", status=200, body=_bundle(30))
        ),
        probe_b.evaluate_step(
            _step("zfp_mdw", "MDW"),
            _exchange(label="zfp_mdw", status=200, body=_bundle(30, office="KLOT")),
        ),
    )

    census = probe_b.census_from_outcomes(outcomes, {"NYC": "KOKX", "MDW": "KLOT"})

    assert census.sites == 2
    assert census.products == 60
    assert probe_b.evaluate_verdict(census).passed is True


# ==========================================================================
# 4. A failed baseline aborts the remaining plan
# ==========================================================================


def test_the_first_planned_step_is_the_baseline() -> None:
    plan = probe_b.build_request_plan()

    assert plan[0].baseline is True
    assert [step.baseline for step in plan[1:]] == [False] * (len(plan) - 1)


@respx.mock
@pytest.mark.asyncio
async def test_a_non_2xx_baseline_aborts_the_remaining_plan(tmp_path: Path) -> None:
    route = respx.get(url__startswith=AFOS_URL).mock(
        return_value=httpx.Response(404, text=ERROR_BODY)
    )
    budget = RequestBudget(limit=probe_b.REQUEST_BUDGET)
    plan = probe_b.build_request_plan()

    result = await probe_b.execute(
        _transport(budget), ProbeEvidenceWriter(tmp_path), plan, pause_seconds=0.0
    )

    assert route.call_count == 1
    assert budget.spent == 1
    assert result.aborted is not None
    assert "baseline" in result.aborted.lower()
    assert len(result.skipped) == len(plan) - 1


@respx.mock
@pytest.mark.asyncio
async def test_a_baseline_serving_an_unparseable_body_aborts(tmp_path: Path) -> None:
    """A 200 whose representation the splitter cannot read is a FORMAT fact.

    It generalises to every later step, so the budget is not spent re-learning
    it -- this is the `fmt=text` refusal the plan calls a finding.
    """
    route = respx.get(url__startswith=AFOS_URL).mock(
        return_value=httpx.Response(200, text="PK\x04\x05 not text at all")
    )
    budget = RequestBudget(limit=probe_b.REQUEST_BUDGET)
    plan = probe_b.build_request_plan()

    result = await probe_b.execute(
        _transport(budget), ProbeEvidenceWriter(tmp_path), plan, pause_seconds=0.0
    )

    assert route.call_count == 1
    assert result.aborted is not None
    assert len(result.skipped) == len(plan) - 1


@respx.mock
@pytest.mark.asyncio
async def test_an_empty_2xx_baseline_does_not_abort_the_plan(tmp_path: Path) -> None:
    """An empty result set is a fact about ONE PIL, not about the endpoint.

    Aborting on it would let one quiet PIL suppress the other site, which is
    how a probe under-reports coverage it actually has.
    """
    route = respx.get(url__startswith=AFOS_URL).mock(return_value=httpx.Response(200, text=""))
    budget = RequestBudget(limit=probe_b.REQUEST_BUDGET)
    plan = probe_b.build_request_plan()

    result = await probe_b.execute(
        _transport(budget), ProbeEvidenceWriter(tmp_path), plan, pause_seconds=0.0
    )

    assert route.call_count == len(plan)
    assert result.aborted is None
    assert result.skipped == ()


@respx.mock
@pytest.mark.asyncio
async def test_a_healthy_baseline_lets_the_plan_continue(tmp_path: Path) -> None:
    respx.get(url__startswith=AFOS_URL).mock(return_value=httpx.Response(200, text=_bundle(4)))
    budget = RequestBudget(limit=probe_b.REQUEST_BUDGET)
    plan = probe_b.build_request_plan()

    result = await probe_b.execute(
        _transport(budget), ProbeEvidenceWriter(tmp_path), plan, pause_seconds=0.0
    )

    assert result.aborted is None
    assert result.skipped == ()
    assert len(result.exchanges) == len(plan)
    assert len(result.outcomes) == len(plan)


@respx.mock
@pytest.mark.asyncio
async def test_a_non_2xx_body_is_still_captured_as_evidence(tmp_path: Path) -> None:
    respx.get(url__startswith=AFOS_URL).mock(return_value=httpx.Response(404, text=ERROR_BODY))
    writer = ProbeEvidenceWriter(tmp_path)

    await probe_b.execute(
        _transport(RequestBudget(limit=probe_b.REQUEST_BUDGET)),
        writer,
        probe_b.build_request_plan(),
        pause_seconds=0.0,
    )

    payloads = sorted(tmp_path.glob("*.probe.json"))
    assert len(payloads) == 1, "the error body is evidence and is still written"


# ==========================================================================
# 5. The report tells the truth and ENDS with the computed verdict
# ==========================================================================


def _report_for(outcomes: Any, exchanges: Any, *, aborted: str | None, skipped: Any) -> str:
    plan = probe_b.build_request_plan()
    census = probe_b.census_from_outcomes(outcomes, {"NYC": "KOKX", "MDW": "KLOT"})
    execution = probe_b.ExecutionResult(
        exchanges=tuple(exchanges),
        outcomes=tuple(outcomes),
        aborted=aborted,
        skipped=tuple(skipped),
    )
    report = probe_b.render_report(
        census,
        probe_b.evaluate_verdict(census),
        execution=execution,
        plan=plan,
        budget=RequestBudget(limit=probe_b.REQUEST_BUDGET),
    )
    assert isinstance(report, str), f"render_report must return text, got {type(report)!r}"
    return report


def _report_for_a_total_404() -> str:
    plan = probe_b.build_request_plan()
    exchange = _exchange(label=plan[0].label, status=404, body=ERROR_BODY)
    outcome = probe_b.evaluate_step(plan[0], exchange)
    return _report_for(
        (outcome,),
        (exchange,),
        aborted=f"BASELINE step `{plan[0].label}` yielded no product.",
        skipped=tuple(step.label for step in plan[1:]),
    )


def test_the_report_lists_every_non_2xx_under_findings() -> None:
    report = _report_for_a_total_404()

    findings = report.split("## Findings", 1)[1]
    assert "None recorded" not in findings
    assert "404" in findings


def test_the_report_ends_with_an_explicit_verdict_line() -> None:
    report = _report_for_a_total_404()

    last = report.strip().splitlines()[-1]
    assert last == "VERDICT: FAIL"


def test_the_report_ends_with_pass_when_every_clause_holds() -> None:
    outcomes = (
        probe_b.evaluate_step(
            _step("zfp_nyc", "NYC"), _exchange(label="zfp_nyc", status=200, body=_bundle(30))
        ),
        probe_b.evaluate_step(
            _step("zfp_mdw", "MDW"),
            _exchange(label="zfp_mdw", status=200, body=_bundle(30, office="KLOT")),
        ),
    )
    exchanges = (
        _exchange(label="zfp_nyc", status=200, body=_bundle(30)),
        _exchange(label="zfp_mdw", status=200, body=_bundle(30, office="KLOT"), ordinal=2),
    )

    report = _report_for(outcomes, exchanges, aborted=None, skipped=())

    assert report.strip().splitlines()[-1] == "VERDICT: PASS"


def test_the_report_states_the_parse_rate_as_a_number() -> None:
    report = _report_for_a_total_404()

    assert "0.0000" in report
    assert "parse rate" in report.lower()


def test_the_report_marks_every_step_that_yielded_nothing() -> None:
    report = _report_for_a_total_404()

    coverage = report.split("## Step coverage", 1)[1].split("## Findings", 1)[0]
    plan = probe_b.build_request_plan()
    line = next(line for line in coverage.splitlines() if plan[0].label in line)
    assert "NO PRODUCT" in line


def test_the_report_names_how_many_steps_were_skipped_and_why() -> None:
    report = _report_for_a_total_404()

    assert "skipped" in report.lower()
    assert str(len(probe_b.build_request_plan())) in report


def test_the_report_claims_office_attribution_not_zone_containment() -> None:
    """The registry has no UGC-zone geometry; claiming zone containment overclaims."""
    report = _report_for_a_total_404()

    assert "office" in report.lower()
    assert "issuing_office" in report
    body = report.lower()
    assert "zone containing the settlement station" not in body
    assert "ugc" in body, "the report must name what it did NOT verify"
