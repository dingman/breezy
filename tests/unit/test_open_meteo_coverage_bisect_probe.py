"""Unit coverage for P2 Probe C -- the Open-Meteo archive-coverage bisect.

Authority: ``docs/plans/DATA_CAPTURE_AND_RISK_PLAN.md`` section 4.P2, clause
``archive_reaches_2024_01``, left UNRESOLVED by Probe A
(``docs/evidence/open_meteo_previous_runs_probe_2026-08-31T005848Z``).

Probe A found a NON-MONOTONIC result for ``temperature_2m_previous_day1`` at
the NYC coordinates -- 2019 all-null, 2022 fully populated, 2024 all-null, all
HTTP 200. No simple "the archive starts on date D" can produce that shape, so
the clause cannot be closed from Probe A's captures. Probe C exists to decide
whether the null-ness is a function of DATE, of MODEL, or of both, and where
the contiguous boundary of the best-covered model sits.

**Every test in this module runs against fixtures.** ``tests/conftest.py``
blocks real sockets for anything not marked ``live``/``allow_socket``, and
nothing here carries either marker. The structural containment properties
(budget, redirect refusal, body cap, settlement-host ban, ``.probe.json``
suffix, live unlock) are asserted for this probe alongside the other two in
``tests/unit/test_probe_containment.py``; what is asserted HERE is the probe's
own arithmetic -- how a coverage cell is counted, how the two axes are
separated, how the bisect steps, and how the verdict is computed.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Final

import httpx
import pytest
import respx

from breezy.ingest.probe_transport import (
    MANIFEST_FILENAME,
    ProbeEvidenceWriter,
    ProbeExchange,
    ProbeTransport,
    RequestBudget,
)

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
PROBE_C_PATH: Final[Path] = REPO_ROOT / "scripts/venue/open_meteo_coverage_bisect_probe.py"

PROBE_UA: Final[str] = "breezy-ingest/1.0 (+mailto:weather-breezy@jonathan.vc)"


def _load_script(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"breezy_probe_{path.stem}", path)
    if spec is None or spec.loader is None:  # pragma: no cover - import plumbing
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


probe_c = _load_script(PROBE_C_PATH)


def _clock() -> int:
    return 1_700_000_000_000_000_000


def _exchange(
    *,
    label: str = "cell",
    status: int = 200,
    text: str | None = None,
    ordinal: int = 1,
) -> ProbeExchange:
    return ProbeExchange(
        ordinal=ordinal,
        requested_at_utc="2026-08-31T00:00:00+00:00",
        label=label,
        url="https://previous-runs-api.open-meteo.com/v1/forecast",
        status_code=status,
        body_bytes=len(text.encode("utf-8")) if text is not None else 0,
        content_type="application/json",
        outcome="ok" if 200 <= status < 300 else f"http_{status}",
        sha256=None,
        text=text,
    )


def _hourly_body(values: list[float | None]) -> str:
    times = [f"2022-01-01T{index:02d}:00" for index in range(len(values))]
    series = ", ".join("null" if value is None else repr(value) for value in values)
    quoted = ", ".join(f'"{stamp}"' for stamp in times)
    return (
        '{"latitude": 40.75, "longitude": -73.99, "hourly": {'
        f'"time": [{quoted}], '
        f'"{probe_c.PREVIOUS_DAY_VARIABLE}": [{series}]'
        "}}"
    )


def _cell(non_null: int, rows: int = 168) -> object:
    return probe_c.CoverageCell(rows=rows, non_null=non_null)


# ==========================================================================
# 1 -- the hard budget covers every phase, and cannot be over-committed
# ==========================================================================


def test_the_hard_budget_is_the_sixteen_requests_that_were_authorised() -> None:
    assert probe_c.REQUEST_BUDGET == 16


def test_every_phase_ceiling_fits_inside_the_hard_budget() -> None:
    """An added step cannot over-spend without deliberately raising the ceiling."""
    committed = probe_c.MATRIX_BUDGET + probe_c.BISECT_BUDGET + probe_c.CONTIGUITY_BUDGET
    assert committed <= probe_c.REQUEST_BUDGET, (
        f"phases commit {committed} requests against a budget of {probe_c.REQUEST_BUDGET}"
    )


def test_the_matrix_plan_is_exactly_the_matrix_budget() -> None:
    plan = probe_c.build_matrix_plan()
    assert len(plan) == probe_c.MATRIX_BUDGET


def test_the_matrix_crosses_every_date_with_every_model() -> None:
    """The whole point of phase 1: separate the DATE axis from the MODEL axis."""
    plan = probe_c.build_matrix_plan()
    assert {(step.start, step.model) for step in plan} == {
        (date, model) for date in probe_c.MATRIX_DATES for model in probe_c.MATRIX_MODELS
    }


def test_the_matrix_includes_the_bar_date_and_a_known_populated_control() -> None:
    assert probe_c.BAR_DATE in probe_c.MATRIX_DATES
    assert dt.date(2022, 1, 1) in probe_c.MATRIX_DATES


def test_the_matrix_includes_the_default_best_match_and_explicit_models() -> None:
    assert "best_match" in probe_c.MATRIX_MODELS
    assert {"ecmwf_ifs025", "gfs_seamless", "icon_seamless"} <= set(probe_c.MATRIX_MODELS)


def test_a_matrix_step_names_its_model_explicitly_in_the_query() -> None:
    plan = probe_c.build_matrix_plan()
    step = next(step for step in plan if step.model == "ecmwf_ifs025")
    assert step.query["models"] == "ecmwf_ifs025"
    assert step.query["start_date"] == step.start.isoformat()
    assert probe_c.PREVIOUS_DAY_VARIABLE in step.query["hourly"]


def test_the_probe_never_names_the_settlement_host() -> None:
    source = PROBE_C_PATH.read_text(encoding="utf-8")
    assert "api.weather.gov" not in source


# ==========================================================================
# 2 -- counting a coverage cell: a 200 is not an answer
# ==========================================================================


def test_a_full_window_counts_every_hour() -> None:
    cell = probe_c.count_coverage(_exchange(text=_hourly_body([21.5, 22.0, 22.5])))
    assert cell == _cell(non_null=3, rows=3)
    assert cell is not None and cell.covered is True


def test_an_all_null_window_is_a_zero_cell_not_a_missing_one() -> None:
    """The distinction the anomaly turns on: served-and-empty != not served."""
    cell = probe_c.count_coverage(_exchange(text=_hourly_body([None, None, None])))
    assert cell == _cell(non_null=0, rows=3)
    assert cell is not None and cell.covered is False


def test_a_partially_null_window_counts_only_the_values() -> None:
    cell = probe_c.count_coverage(_exchange(text=_hourly_body([21.5, None, 22.5, None])))
    assert cell == _cell(non_null=2, rows=4)


def test_a_non_2xx_yields_no_cell_at_all() -> None:
    """A 404/5xx carries no datum: it must not be read as 'zero coverage'."""
    assert probe_c.count_coverage(_exchange(status=404, text='{"error": true}')) is None


def test_a_missing_variable_key_yields_no_cell() -> None:
    body = '{"hourly": {"time": ["2022-01-01T00:00"], "temperature_2m": [1.0]}}'
    assert probe_c.count_coverage(_exchange(text=body)) is None


def test_malformed_json_yields_no_cell() -> None:
    assert probe_c.count_coverage(_exchange(text="not json at all")) is None


def test_an_empty_body_yields_no_cell() -> None:
    assert probe_c.count_coverage(_exchange(text=None)) is None


def test_an_empty_series_yields_no_cell_rather_than_a_zero_row_division() -> None:
    body = f'{{"hourly": {{"time": [], "{probe_c.PREVIOUS_DAY_VARIABLE}": []}}}}'
    assert probe_c.count_coverage(_exchange(text=body)) is None


# ==========================================================================
# 3 -- separating the two axes
# ==========================================================================

_D2022: Final[dt.date] = dt.date(2022, 1, 1)
_D2024: Final[dt.date] = dt.date(2024, 1, 1)


def test_dependence_is_model_when_only_the_model_axis_moves() -> None:
    cells = {
        (_D2022, "best_match"): _cell(0),
        (_D2022, "ecmwf_ifs025"): _cell(168),
        (_D2024, "best_match"): _cell(0),
        (_D2024, "ecmwf_ifs025"): _cell(168),
    }
    assert probe_c.classify_dependence(cells) == probe_c.DEPENDENCE_MODEL


def test_dependence_is_date_when_only_the_date_axis_moves() -> None:
    cells = {
        (_D2022, "best_match"): _cell(168),
        (_D2022, "ecmwf_ifs025"): _cell(168),
        (_D2024, "best_match"): _cell(0),
        (_D2024, "ecmwf_ifs025"): _cell(0),
    }
    assert probe_c.classify_dependence(cells) == probe_c.DEPENDENCE_DATE


def test_dependence_is_both_when_each_axis_moves_independently() -> None:
    cells = {
        (_D2022, "best_match"): _cell(168),
        (_D2022, "ecmwf_ifs025"): _cell(0),
        (_D2024, "best_match"): _cell(0),
        (_D2024, "ecmwf_ifs025"): _cell(0),
    }
    assert probe_c.classify_dependence(cells) == probe_c.DEPENDENCE_BOTH


def test_dependence_is_neither_when_everything_is_covered() -> None:
    cells = {
        (_D2022, "best_match"): _cell(168),
        (_D2024, "best_match"): _cell(168),
    }
    assert probe_c.classify_dependence(cells) == probe_c.DEPENDENCE_NEITHER_COVERED


def test_dependence_is_uniformly_empty_when_nothing_anywhere_carried_a_value() -> None:
    cells = {
        (_D2022, "best_match"): _cell(0),
        (_D2024, "best_match"): _cell(0),
    }
    assert probe_c.classify_dependence(cells) == probe_c.DEPENDENCE_NEITHER_EMPTY


def test_dependence_is_undetermined_when_no_cell_was_obtained() -> None:
    assert probe_c.classify_dependence({}) == probe_c.DEPENDENCE_UNDETERMINED


# ==========================================================================
# 4 -- picking the reference model, then bisecting its boundary
# ==========================================================================


def test_the_reference_model_is_the_one_with_the_most_non_null_hours() -> None:
    cells = {
        (_D2022, "best_match"): _cell(10),
        (_D2022, "gfs_seamless"): _cell(168),
        (_D2024, "best_match"): _cell(0),
        (_D2024, "gfs_seamless"): _cell(100),
    }
    assert probe_c.choose_reference_model(cells) == "gfs_seamless"


def test_the_reference_model_is_none_when_nothing_is_covered() -> None:
    cells = {(_D2022, "best_match"): _cell(0), (_D2024, "best_match"): _cell(0)}
    assert probe_c.choose_reference_model(cells) is None


def test_the_reference_model_tie_breaks_deterministically() -> None:
    """Two models with identical coverage must not make the run irreproducible."""
    cells = {
        (_D2022, "gfs_seamless"): _cell(168),
        (_D2022, "icon_seamless"): _cell(168),
    }
    first = probe_c.choose_reference_model(cells)
    assert first == probe_c.choose_reference_model(dict(reversed(list(cells.items()))))
    assert first is not None


def test_the_bracket_is_the_closest_covered_empty_pair() -> None:
    observations = {
        dt.date(2019, 1, 1): False,
        dt.date(2022, 1, 1): True,
        dt.date(2024, 1, 1): False,
    }
    assert probe_c.bisect_bracket(observations) == (dt.date(2022, 1, 1), dt.date(2024, 1, 1))


def test_there_is_no_bracket_without_both_a_covered_and_an_empty_observation() -> None:
    assert probe_c.bisect_bracket({dt.date(2022, 1, 1): True}) is None
    assert probe_c.bisect_bracket({dt.date(2024, 1, 1): False}) is None
    assert probe_c.bisect_bracket({}) is None


def test_the_bisect_midpoint_halves_the_bracket() -> None:
    midpoint = probe_c.next_bisect_date(dt.date(2022, 1, 1), dt.date(2024, 1, 1))
    assert midpoint == dt.date(2023, 1, 1)


def test_the_bisect_stops_once_the_bracket_is_within_the_resolution() -> None:
    """Bisecting past the stated resolution would spend budget for no answer."""
    covered = dt.date(2023, 1, 1)
    empty = covered + dt.timedelta(days=probe_c.BISECT_RESOLUTION_DAYS)
    assert probe_c.next_bisect_date(covered, empty) is None


def test_the_bisect_works_in_either_direction() -> None:
    """The boundary may be an archive START (empty older) or an END (empty newer)."""
    assert probe_c.next_bisect_date(dt.date(2024, 1, 1), dt.date(2022, 1, 1)) == dt.date(2023, 1, 1)


def test_the_bisect_never_re_asks_a_date_it_already_has() -> None:
    observations = {dt.date(2022, 1, 1): True, dt.date(2024, 1, 1): False}
    midpoint = probe_c.next_bisect_date(dt.date(2022, 1, 1), dt.date(2024, 1, 1))
    assert midpoint is not None
    assert midpoint not in observations


# ==========================================================================
# 5 -- contiguity inside the covered range
# ==========================================================================


def test_contiguity_dates_lie_strictly_inside_the_covered_span() -> None:
    low, high = dt.date(2021, 1, 1), dt.date(2023, 1, 1)
    samples = probe_c.contiguity_dates(low, high, 3)
    assert len(samples) == 3
    assert all(low < sample < high for sample in samples)
    assert list(samples) == sorted(samples)
    assert len(set(samples)) == 3


def test_contiguity_sampling_returns_nothing_when_the_span_cannot_hold_samples() -> None:
    assert probe_c.contiguity_dates(dt.date(2022, 1, 1), dt.date(2022, 1, 2), 3) == ()


def test_contiguity_is_patchy_when_an_interior_sample_is_empty() -> None:
    samples = {dt.date(2022, 4, 1): _cell(168), dt.date(2022, 8, 1): _cell(0)}
    assert probe_c.contiguity_of(samples) == probe_c.CONTIGUITY_PATCHY


def test_contiguity_is_contiguous_when_every_interior_sample_carries_values() -> None:
    samples = {dt.date(2022, 4, 1): _cell(168), dt.date(2022, 8, 1): _cell(168)}
    assert probe_c.contiguity_of(samples) == probe_c.CONTIGUITY_CONTIGUOUS


def test_contiguity_is_unsampled_when_no_interior_sample_was_taken() -> None:
    assert probe_c.contiguity_of({}) == probe_c.CONTIGUITY_UNSAMPLED


# ==========================================================================
# 6 -- the verdict on ``archive_reaches_2024_01``
# ==========================================================================


def test_the_clause_is_satisfied_when_any_model_answers_at_the_bar_date() -> None:
    cells = {
        (_D2022, "best_match"): _cell(0),
        (probe_c.BAR_DATE, "ecmwf_ifs025"): _cell(168),
    }
    verdict = probe_c.evaluate_archive_clause(cells, contiguity=probe_c.CONTIGUITY_CONTIGUOUS)
    assert verdict.state == probe_c.STATE_SATISFIED
    assert "ecmwf_ifs025" in verdict.evidence


def test_the_clause_is_refuted_when_the_bar_date_is_empty_for_every_model_tested() -> None:
    """Refuted needs a POSITIVE control: the request shape provably works."""
    cells = {
        (_D2022, "best_match"): _cell(168),
        (_D2022, "ecmwf_ifs025"): _cell(168),
        (probe_c.BAR_DATE, "best_match"): _cell(0),
        (probe_c.BAR_DATE, "ecmwf_ifs025"): _cell(0),
    }
    verdict = probe_c.evaluate_archive_clause(cells, contiguity=probe_c.CONTIGUITY_CONTIGUOUS)
    assert verdict.state == probe_c.STATE_REFUTED
    assert "2022" in verdict.evidence


def test_the_clause_stays_inconclusive_when_nothing_anywhere_returned_a_value() -> None:
    """No positive control means the null could be OUR request, not the archive."""
    cells = {
        (_D2022, "best_match"): _cell(0),
        (probe_c.BAR_DATE, "best_match"): _cell(0),
    }
    verdict = probe_c.evaluate_archive_clause(cells, contiguity=probe_c.CONTIGUITY_UNSAMPLED)
    assert verdict.state == probe_c.STATE_INCONCLUSIVE


def test_the_clause_stays_inconclusive_when_the_bar_date_was_never_requested() -> None:
    cells = {(_D2022, "best_match"): _cell(168)}
    verdict = probe_c.evaluate_archive_clause(cells, contiguity=probe_c.CONTIGUITY_UNSAMPLED)
    assert verdict.state == probe_c.STATE_INCONCLUSIVE


def test_a_satisfied_clause_over_a_patchy_range_says_so_rather_than_reading_clean() -> None:
    cells = {(probe_c.BAR_DATE, "ecmwf_ifs025"): _cell(168)}
    verdict = probe_c.evaluate_archive_clause(cells, contiguity=probe_c.CONTIGUITY_PATCHY)
    assert verdict.state == probe_c.STATE_SATISFIED
    assert "patchy" in verdict.evidence.lower()


# ==========================================================================
# 7 -- the run: it stays inside its budget and ends with a verdict
# ==========================================================================


def _mock_open_meteo(*, populated_before: dt.date) -> None:
    """Serve a populated window before ``populated_before`` and nulls after."""

    def handler(request: httpx.Request) -> httpx.Response:
        start = dt.date.fromisoformat(request.url.params["start_date"])
        values: list[float | None] = [20.0] * 24 if start < populated_before else [None] * 24
        times = [f"{start.isoformat()}T{index:02d}:00" for index in range(24)]
        return httpx.Response(
            200,
            json={
                "hourly": {
                    "time": times,
                    probe_c.PREVIOUS_DAY_VARIABLE: values,
                }
            },
        )

    respx.get(url__startswith=f"{probe_c.BASE_URL}{probe_c.PATH}").mock(side_effect=handler)


def _transport(budget: RequestBudget) -> ProbeTransport:
    return ProbeTransport(
        base_url=probe_c.BASE_URL,
        allowed_hosts=probe_c.ALLOWED_HOSTS,
        budget=budget,
        max_body_bytes=probe_c.MAX_BODY_BYTES,
        user_agent=PROBE_UA,
        accept="application/json",
        clock=_clock,
    )


@respx.mock
@pytest.mark.asyncio
async def test_the_run_never_exceeds_its_hard_budget(tmp_path: Path) -> None:
    _mock_open_meteo(populated_before=dt.date(2023, 6, 1))
    budget = RequestBudget(limit=probe_c.REQUEST_BUDGET)
    writer = ProbeEvidenceWriter(tmp_path)

    result = await probe_c.run_probe(_transport(budget), writer, pause_seconds=0.0)

    assert budget.spent <= probe_c.REQUEST_BUDGET
    assert result.aborted is None


@respx.mock
@pytest.mark.asyncio
async def test_every_dispatched_request_gets_a_manifest_row(tmp_path: Path) -> None:
    _mock_open_meteo(populated_before=dt.date(2023, 6, 1))
    budget = RequestBudget(limit=probe_c.REQUEST_BUDGET)
    writer = ProbeEvidenceWriter(tmp_path)

    result = await probe_c.run_probe(_transport(budget), writer, pause_seconds=0.0)

    rows = (tmp_path / MANIFEST_FILENAME).read_text(encoding="utf-8").splitlines()
    assert len(rows) - 1 == len(result.exchanges) == budget.spent


@respx.mock
@pytest.mark.asyncio
async def test_the_run_localises_the_boundary_it_was_built_to_find(tmp_path: Path) -> None:
    """End-to-end against a KNOWN synthetic boundary: the bisect must find it."""
    truth = dt.date(2023, 6, 1)
    _mock_open_meteo(populated_before=truth)
    budget = RequestBudget(limit=probe_c.REQUEST_BUDGET)

    result = await probe_c.run_probe(
        _transport(budget), ProbeEvidenceWriter(tmp_path), pause_seconds=0.0
    )

    assert result.boundary is not None
    covered, empty = result.boundary
    assert covered < truth <= empty
    assert (empty - covered).days <= probe_c.BISECT_RESOLUTION_DAYS


@respx.mock
@pytest.mark.asyncio
async def test_a_totally_empty_archive_produces_an_inconclusive_verdict(tmp_path: Path) -> None:
    """A clean negative: nothing answered, so nothing may be concluded."""
    _mock_open_meteo(populated_before=dt.date(1900, 1, 1))
    budget = RequestBudget(limit=probe_c.REQUEST_BUDGET)

    result = await probe_c.run_probe(
        _transport(budget), ProbeEvidenceWriter(tmp_path), pause_seconds=0.0
    )

    assert result.verdict.state == probe_c.STATE_INCONCLUSIVE
    assert result.boundary is None
    assert budget.spent == probe_c.MATRIX_BUDGET, "no budget spent bisecting an empty result"


@respx.mock
@pytest.mark.asyncio
async def test_a_non_2xx_matrix_is_a_finding_not_a_zero_coverage_claim(tmp_path: Path) -> None:
    respx.get(url__startswith=f"{probe_c.BASE_URL}{probe_c.PATH}").mock(
        return_value=httpx.Response(429, json={"error": True, "reason": "rate limited"})
    )
    budget = RequestBudget(limit=probe_c.REQUEST_BUDGET)

    result = await probe_c.run_probe(
        _transport(budget), ProbeEvidenceWriter(tmp_path), pause_seconds=0.0
    )

    assert result.verdict.state == probe_c.STATE_INCONCLUSIVE
    assert result.cells == {}
    assert result.findings, "a 429 on every matrix cell must be reported as a finding"


@respx.mock
@pytest.mark.asyncio
async def test_the_report_ends_with_the_explicit_clause_verdict(tmp_path: Path) -> None:
    _mock_open_meteo(populated_before=dt.date(2023, 6, 1))
    budget = RequestBudget(limit=probe_c.REQUEST_BUDGET)

    result = await probe_c.run_probe(
        _transport(budget), ProbeEvidenceWriter(tmp_path), pause_seconds=0.0
    )
    report = probe_c.render_report(result, budget=budget)

    assert isinstance(report, str)
    last = report.strip().splitlines()[-1]
    assert last.startswith(f"VERDICT: {probe_c.CLAUSE_ARCHIVE} = ")
    assert result.verdict.state in last


@respx.mock
@pytest.mark.asyncio
async def test_the_report_carries_the_full_date_by_model_matrix(tmp_path: Path) -> None:
    _mock_open_meteo(populated_before=dt.date(2023, 6, 1))
    budget = RequestBudget(limit=probe_c.REQUEST_BUDGET)

    result = await probe_c.run_probe(
        _transport(budget), ProbeEvidenceWriter(tmp_path), pause_seconds=0.0
    )
    report = probe_c.render_report(result, budget=budget)

    for model in probe_c.MATRIX_MODELS:
        assert model in report
    for date in probe_c.MATRIX_DATES:
        assert date.isoformat() in report


@respx.mock
@pytest.mark.asyncio
async def test_the_run_aborts_rather_than_over_spending_a_short_budget(tmp_path: Path) -> None:
    """Budget exhaustion is terminal and REPORTED -- never silently truncated."""
    _mock_open_meteo(populated_before=dt.date(2023, 6, 1))
    budget = RequestBudget(limit=3)

    result = await probe_c.run_probe(
        _transport(budget), ProbeEvidenceWriter(tmp_path), pause_seconds=0.0
    )

    assert budget.spent == 3
    assert result.aborted is not None
    assert result.verdict.state == probe_c.STATE_INCONCLUSIVE


def test_the_cli_refuses_without_the_live_unlock(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("BREEZY_LIVE", raising=False)
    assert probe_c.main(["--output-directory", str(tmp_path)]) != 0


def test_the_cli_refuses_without_apply_even_when_live(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("BREEZY_LIVE", "1")
    monkeypatch.setenv("BREEZY_USER_AGENT", PROBE_UA)
    assert probe_c.main(["--output-directory", str(tmp_path)]) != 0


def test_the_cli_refuses_without_a_contactable_user_agent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("BREEZY_LIVE", "1")
    monkeypatch.delenv("BREEZY_USER_AGENT", raising=False)
    assert probe_c.main(["--output-directory", str(tmp_path), "--apply"]) != 0
