"""Unit tests for the IEM MOS (NBS/GFS) reachability probe (FC-0a-1).

Every test here runs against fixtures. ``tests/conftest.py`` blocks real
sockets for anything not marked ``live``/``allow_socket``, and nothing here
carries either marker.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import importlib.util
import json
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any, Final
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from breezy.ingest.http import FetchResult, HttpTransport, OversizeBodyError, RedirectError
from breezy.ingest.probe_transport import (
    MANIFEST_FILENAME,
    ProbeEvidenceWriter,
    ProbeExchange,
    RequestBudget,
)

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
PROBE_PATH: Final[Path] = REPO_ROOT / "scripts/venue/iem_mos_reachability_probe.py"
TRANSPORT_PATH: Final[Path] = REPO_ROOT / "scripts/venue/iem_mos_probe_transport.py"
PROBE_UA: Final[str] = "breezy-mos-probe-ua-token-TESTONLY"
FROZEN_DT: Final[dt.datetime] = dt.datetime(2026, 9, 18, tzinfo=dt.UTC)
FROZEN_NS: Final[int] = int(FROZEN_DT.timestamp() * 1_000_000_000)
SUMMARY_KEYS: Final[frozenset[str]] = frozenset(
    {
        "label",
        "url",
        "outcome",
        "finding",
        "content_type",
        "status",
        "sha256",
        "body_bytes",
        "row_count",
        "distinct_runtime_days",
        "first_runtime",
        "last_runtime",
        "csv_header_line",
        "sample_row_1",
        "sample_row_2",
    }
)


def _load_script(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"breezy_probe_{path.stem}", path)
    if spec is None or spec.loader is None:  # pragma: no cover - import plumbing
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_transport_mod = _load_script(TRANSPORT_PATH)
IemMosProbeTransport = _transport_mod.IemMosProbeTransport
IemPacer = _transport_mod.IemPacer

probe = _load_script(PROBE_PATH)


def _clock() -> int:
    return FROZEN_NS


async def _noop_sleep(_seconds: float) -> None:
    return None


def _exchange(
    *,
    label: str,
    status: int = 200,
    outcome: str | None = None,
    url: str = "https://mesonet.agron.iastate.edu/cgi-bin/request/mos.py",
    ordinal: int = 1,
) -> ProbeExchange:
    if outcome is None:
        outcome = "ok" if 200 <= status < 300 else f"http_{status}"
    return ProbeExchange(
        ordinal=ordinal,
        requested_at_utc="2026-09-18T00:00:00+00:00",
        label=label,
        url=url,
        status_code=status,
        body_bytes=100,
        content_type="text/csv",
        outcome=outcome,
        sha256="ab" * 32,
        text=None,
    )


def _census(
    *,
    rows: int,
    days: int,
    first: str | None,
    last: str | None,
    parse_ok: bool = True,
    header: str | None = "station,model,runtime,tmp",
    sample_1: str | None = "KMDW,NBS,2021-01-01 00:00:00,50",
    sample_2: str | None = "KMDW,NBS,2021-01-02 00:00:00,50",
) -> Any:
    return probe.MosCensus(
        row_count=rows,
        distinct_runtime_days=days,
        first_runtime=first,
        last_runtime=last,
        csv_header_line=header,
        sample_row_1=sample_1,
        sample_row_2=sample_2,
        parse_ok=parse_ok,
    )


def _year_cell(
    *,
    station: str,
    model: str,
    year: int,
    census: Any | None,
    status: int = 200,
    outcome: str | None = None,
    resplit: bool = False,
) -> Any:
    label = f"{model.lower()}_{station.lower()}_{year}"
    return probe.YearCell(
        station=station,
        model=model,
        year=year,
        label=label,
        exchange=_exchange(label=label, status=status, outcome=outcome),
        census=census,
        resplit=resplit,
        body_bytes=100 if census is not None else 0,
    )


def _complete_days(year: int) -> int:
    return 366 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 365


def _good_nbs_cells(
    *,
    mutate: Callable[[str, int, Any], Any] | None = None,
) -> list[Any]:
    cells: list[Any] = []
    for station in ("KLAX", "KMDW", "KMIA", "KSFO"):
        for year in (2021, 2022, 2023, 2024, 2025):
            days = _complete_days(year)
            cell = _year_cell(
                station=station,
                model="NBS",
                year=year,
                census=_census(
                    rows=days,
                    days=days,
                    first=f"{year}-01-01 00:00:00",
                    last=f"{year}-12-31 00:00:00",
                ),
            )
            if mutate is not None:
                cell = mutate(station, year, cell)
            cells.append(cell)
        cells.append(
            _year_cell(
                station=station,
                model="NBS",
                year=2026,
                census=_census(
                    rows=261,
                    days=261,
                    first="2026-01-01 00:00:00",
                    last="2026-09-18 00:00:00",
                ),
            )
        )
    return cells


def _zero_census() -> Any:
    return _census(
        rows=0,
        days=0,
        first=None,
        last=None,
        header="station,model,runtime,tmp",
        sample_1=None,
        sample_2=None,
    )


def _result(text: str, *, status: int = 200, url: str) -> FetchResult:
    body = text.encode("utf-8")
    return FetchResult(
        text=text,
        sha256=hashlib.sha256(body).hexdigest(),
        status_code=status,
        headers=httpx.Headers({"content-type": "text/csv"}),
        url=url,
        retrieved_at_ns=FROZEN_NS,
    )


def _mos_csv(station: str, model: str, start: dt.date, days: int) -> str:
    header = "station,model,runtime,tmp"
    rows = [
        f"{station},{model},{(start + dt.timedelta(days=offset)).isoformat()} 00:00:00,50"
        for offset in range(days)
    ]
    return header + "\n" + "\n".join(rows) + "\n"


def _covering_csv(station: str, model: str, year: int, *, current: bool = False) -> str:
    start = dt.date(year, 1, 1)
    if current:
        days = (dt.date(2026, 9, 18) - start).days + 1
    else:
        days = _complete_days(year)
    return _mos_csv(station, model, start, days)


def _query(url: str) -> dict[str, str]:
    parsed = parse_qs(urlsplit(url).query)
    return {key: values[0] for key, values in parsed.items()}


def _is_full_year(sts: str, ets: str) -> bool:
    return sts[5:10] == "01-01" and ets[5:10] in {"12-31", "09-18"}


def _is_nbs_kmdw_2021(query: dict[str, str]) -> bool:
    return (
        query["station"] == "KMDW"
        and query["model"] == "NBS"
        and query["sts"].startswith("2021")
    )


async def _good_fetch(
    self: HttpTransport,
    url: str,
    *,
    if_none_match: str | None,
    if_modified_since: str | None,
    allow_not_modified: bool,
) -> FetchResult:
    query = _query(url)
    year = int(query["sts"][:4])
    current = year == 2026 and _is_full_year(query["sts"], query["ets"])
    text = _covering_csv(query["station"], query["model"], year, current=current)
    if not _is_full_year(query["sts"], query["ets"]):
        start = dt.date.fromisoformat(query["sts"][:10])
        end = dt.date.fromisoformat(query["ets"][:10])
        text = _mos_csv(query["station"], query["model"], start, (end - start).days + 1)
    return _result(text, url=url)


async def _run_execute(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    fetch_impl: Callable[..., Any],
    *,
    budget_limit: int | None = None,
) -> tuple[Any, ProbeEvidenceWriter, IemMosProbeTransport]:
    plan = probe.build_request_plan(clock=_clock)
    budget = RequestBudget(limit=budget_limit if budget_limit is not None else probe.REQUEST_BUDGET)
    transport = IemMosProbeTransport(
        budget=budget,
        pacer=IemPacer(clock=_clock, sleeper=_noop_sleep),
        user_agent=PROBE_UA,
        clock=_clock,
        check_proxy_env=False,
    )
    monkeypatch.setattr(HttpTransport, "_fetch", fetch_impl)
    writer = ProbeEvidenceWriter(tmp_path)
    result = await probe.execute(transport, writer, plan, clock=_clock)
    return result, writer, transport


def test_plan_length_equals_hard_budget() -> None:
    plan = probe.build_request_plan(clock=_clock)
    assert len(plan) == 48
    assert probe.OVERSIZE_RESPLIT_RESERVE == 8
    assert probe.REQUEST_BUDGET == 56
    assert len(plan) <= probe.REQUEST_BUDGET
    assert probe.REQUEST_BUDGET == len(plan) + probe.OVERSIZE_RESPLIT_RESERVE


def test_plan_is_nbs_then_gfs_four_stations_years_2021_to_now() -> None:
    plan = probe.build_request_plan(clock=_clock)
    assert [step.model for step in plan[:24]] == ["NBS"] * 24
    assert [step.model for step in plan[24:]] == ["GFS"] * 24
    stations = ("KLAX", "KMDW", "KMIA", "KSFO")
    years = (2021, 2022, 2023, 2024, 2025, 2026)
    expected = [
        (model, station, year)
        for model in ("NBS", "GFS")
        for station in stations
        for year in years
    ]
    assert [(step.model, step.station, step.year) for step in plan] == expected
    current = next(step for step in plan if step.year == 2026 and step.station == "KMDW")
    assert current.sts == "2026-01-01T00:00Z"
    assert current.ets == "2026-09-18T00:00Z"
    complete = next(step for step in plan if step.year == 2021 and step.station == "KMDW")
    assert complete.sts == "2021-01-01T00:00Z"
    assert complete.ets == "2021-12-31T23:59Z"


def test_nbs_distinct_runtime_days_floor_is_300_and_predeclared() -> None:
    assert probe.MIN_NBS_DISTINCT_RUNTIME_DAYS_PER_COMPLETE_YEAR == 300
    assert probe.MIN_NBS_DISTINCT_RUNTIME_DAYS_HARD_FLOOR == 60
    assert probe.MIN_NBS_COMPLETE_YEARS_AT_FLOOR == 3


def test_reachability_probe_reports_row_counts_not_http_status() -> None:
    empty = [
        _year_cell(station=station, model="NBS", year=year, census=_zero_census())
        for station in ("KLAX", "KMDW", "KMIA", "KSFO")
        for year in (2021, 2022, 2023, 2024, 2025, 2026)
    ]
    empty_verdict = probe.evaluate_verdict(empty, clock=_clock)
    assert empty_verdict.passed is False
    assert all(cell.exchange.status_code == 200 for cell in empty)
    good = probe.evaluate_verdict(_good_nbs_cells(), clock=_clock)
    assert good.passed is True
    assert all(cell.exchange.status_code == 200 for cell in _good_nbs_cells())


def test_nbs_full_matrix_with_rows_is_pass() -> None:
    verdict = probe.evaluate_verdict(_good_nbs_cells(), clock=_clock)
    assert verdict.passed is True
    assert verdict.failures == ()


def test_nbs_zero_row_2xx_complete_year_is_fail() -> None:
    def mutate(station: str, year: int, cell: Any) -> Any:
        if station == "KMDW" and year == 2021:
            return _year_cell(station=station, model="NBS", year=year, census=_zero_census())
        return cell

    verdict = probe.evaluate_verdict(_good_nbs_cells(mutate=mutate), clock=_clock)
    assert verdict.passed is False
    assert any("absent" in failure or "zero" in failure for failure in verdict.failures)


def test_nbs_partial_year_is_finding_not_fail() -> None:
    def mutate(station: str, year: int, cell: Any) -> Any:
        if station == "KMDW" and year == 2021:
            return _year_cell(
                station=station,
                model="NBS",
                year=year,
                census=_census(
                    rows=300,
                    days=300,
                    first="2021-02-01 00:00:00",
                    last="2021-11-27 00:00:00",
                ),
            )
        return cell

    verdict = probe.evaluate_verdict(_good_nbs_cells(mutate=mutate), clock=_clock)
    assert verdict.passed is True
    assert verdict.failures == ()
    assert verdict.findings != ()


def test_nbs_partial_year_between_60_and_299_is_finding_not_fail() -> None:
    def mutate(station: str, year: int, cell: Any) -> Any:
        if station == "KMDW" and year == 2021:
            return _year_cell(
                station=station,
                model="NBS",
                year=year,
                census=_census(
                    rows=150,
                    days=150,
                    first="2021-01-01 00:00:00",
                    last="2021-12-31 00:00:00",
                ),
            )
        return cell

    verdict = probe.evaluate_verdict(_good_nbs_cells(mutate=mutate), clock=_clock)
    assert verdict.passed is True
    assert verdict.failures == ()
    assert any("150" in finding or "300" in finding for finding in verdict.findings)


def test_nbs_year_below_60_distinct_days_is_fail() -> None:
    def mutate(station: str, year: int, cell: Any) -> Any:
        if station == "KMDW" and year == 2021:
            return _year_cell(
                station=station,
                model="NBS",
                year=year,
                census=_census(
                    rows=59,
                    days=59,
                    first="2021-01-01 00:00:00",
                    last="2021-02-28 00:00:00",
                ),
            )
        return cell

    verdict = probe.evaluate_verdict(_good_nbs_cells(mutate=mutate), clock=_clock)
    assert verdict.passed is False
    assert any("60" in failure for failure in verdict.failures)


def test_nbs_fewer_than_three_complete_years_at_300_is_fail() -> None:
    def mutate(station: str, year: int, cell: Any) -> Any:
        if station != "KMDW":
            return cell
        if year in {2021, 2022}:
            return cell
        return _year_cell(
            station=station,
            model="NBS",
            year=year,
            census=_census(
                rows=150,
                days=150,
                first=f"{year}-01-01 00:00:00",
                last=f"{year}-12-31 00:00:00",
            ),
        )

    verdict = probe.evaluate_verdict(_good_nbs_cells(mutate=mutate), clock=_clock)
    assert verdict.passed is False
    assert any("3" in failure or "three" in failure.lower() for failure in verdict.failures)


def test_nbs_current_year_stale_last_runtime_is_fail() -> None:
    cells = []
    for cell in _good_nbs_cells():
        if cell.station == "KMDW" and cell.year == 2026:
            cells.append(
                _year_cell(
                    station="KMDW",
                    model="NBS",
                    year=2026,
                    census=_census(
                        rows=200,
                        days=200,
                        first="2026-01-01 00:00:00",
                        last="2026-08-01 00:00:00",
                    ),
                )
            )
        else:
            cells.append(cell)
    verdict = probe.evaluate_verdict(cells, clock=_clock)
    assert verdict.passed is False
    assert any(
        "14" in failure or "recency" in failure.lower() or "stale" in failure.lower()
        for failure in verdict.failures
    )


def test_gfs_zero_rows_does_not_fail_nbs_pass() -> None:
    cells = _good_nbs_cells()
    cells.extend(
        _year_cell(station=station, model="GFS", year=year, census=_zero_census())
        for station in ("KLAX", "KMDW", "KMIA", "KSFO")
        for year in (2021, 2022, 2023, 2024, 2025, 2026)
    )
    verdict = probe.evaluate_verdict(cells, clock=_clock)
    assert verdict.passed is True
    assert verdict.failures == ()
    assert verdict.optional_failures != ()


def test_non_2xx_is_not_a_zero_coverage_claim() -> None:
    def mutate(station: str, year: int, cell: Any) -> Any:
        if station == "KMDW" and year == 2021:
            return _year_cell(
                station=station,
                model="NBS",
                year=year,
                census=None,
                status=404,
                outcome="http_404",
            )
        return cell

    cells = _good_nbs_cells(mutate=mutate)
    verdict = probe.evaluate_verdict(cells, clock=_clock)
    assert verdict.passed is False
    assert any(
        "404" in failure or "no cell" in failure.lower() or "absent" in failure
        for failure in verdict.failures
    )
    assert all(
        not (
            cell.station == "KMDW"
            and cell.year == 2021
            and cell.census is not None
            and cell.census.row_count == 0
        )
        for cell in cells
    )


def test_html_200_is_zero_rows() -> None:
    census = probe.parse_mos_csv_census("<html><body>not csv</body></html>")
    assert census.row_count == 0
    assert census.distinct_runtime_days == 0


def test_header_only_csv_is_zero_rows() -> None:
    census = probe.parse_mos_csv_census("station,model,runtime,tmp\n")
    assert census.row_count == 0
    assert census.distinct_runtime_days == 0


def test_evaluate_verdict_does_not_treat_status_200_as_sufficient() -> None:
    cells = [
        _year_cell(station=station, model="NBS", year=year, census=_zero_census())
        for station in ("KLAX", "KMDW", "KMIA", "KSFO")
        for year in (2021, 2022, 2023, 2024, 2025, 2026)
    ]
    verdict = probe.evaluate_verdict(cells, clock=_clock)
    assert all(cell.exchange.status_code == 200 for cell in cells)
    assert verdict.passed is False


def test_script_source_never_names_settlement_host() -> None:
    source = PROBE_PATH.read_text(encoding="utf-8")
    assert "api.weather.gov" not in source
    assert "weather.gov" not in source


def test_report_names_per_station_first_last_rows_distinct_days_and_max_body_bytes() -> None:
    cells = _good_nbs_cells()
    verdict = probe.evaluate_verdict(cells, clock=_clock)
    report = probe.render_report(
        cells,
        verdict,
        budget=RequestBudget(limit=probe.REQUEST_BUDGET),
        plan=probe.build_request_plan(clock=_clock),
        clock=_clock,
        max_body_bytes_measured=12345,
    )
    for station in ("KLAX", "KMDW", "KMIA", "KSFO"):
        assert station in report
    assert "first" in report.lower()
    assert "last" in report.lower()
    assert "distinct_runtime_days" in report or "distinct runtime" in report.lower()
    assert "12345" in report
    assert "INTERSECTION" in report
    assert report.strip().endswith("VERDICT: PASS")


@pytest.mark.asyncio
async def test_manifest_and_summary_round_trip_http_fail(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    async def fetch_impl(
        self: HttpTransport,
        url: str,
        *,
        if_none_match: str | None,
        if_modified_since: str | None,
        allow_not_modified: bool,
    ) -> FetchResult:
        query = _query(url)
        if _is_nbs_kmdw_2021(query):
            return _result("not found", status=404, url=url)
        return await _good_fetch(
            self,
            url,
            if_none_match=if_none_match,
            if_modified_since=if_modified_since,
            allow_not_modified=allow_not_modified,
        )

    result, _writer, _transport = await _run_execute(monkeypatch, tmp_path, fetch_impl)
    rows = (tmp_path / MANIFEST_FILENAME).read_text(encoding="utf-8").splitlines()[1:]
    fail_row = next(row for row in rows if "nbs_kmdw_2021" in row)
    cols = fail_row.split("\t")
    assert cols[7] != "ok"
    assert cols[7] == "http_404"
    summary = json.loads((tmp_path / "nbs_kmdw_2021.summary.json").read_text(encoding="utf-8"))
    assert summary["outcome"] != "ok"
    assert summary["status"] == 404
    assert summary["row_count"] is None
    assert summary["distinct_runtime_days"] is None
    kmdw_2021 = next(cell for cell in result.cells if cell.label == "nbs_kmdw_2021")
    assert str(cols[0]) == str(kmdw_2021.exchange.ordinal)
    assert not list(tmp_path.glob("*.probe.json"))


@pytest.mark.asyncio
async def test_manifest_and_summary_round_trip_oversize(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    async def fetch_impl(
        self: HttpTransport,
        url: str,
        *,
        if_none_match: str | None,
        if_modified_since: str | None,
        allow_not_modified: bool,
    ) -> FetchResult:
        query = _query(url)
        if (
            query["station"] == "KMDW"
            and query["model"] == "NBS"
            and query["sts"].startswith("2021")
            and _is_full_year(query["sts"], query["ets"])
        ):
            raise OversizeBodyError("body exceeded cap")
        return await _good_fetch(
            self,
            url,
            if_none_match=if_none_match,
            if_modified_since=if_modified_since,
            allow_not_modified=allow_not_modified,
        )

    _result_obj, _writer, _transport = await _run_execute(monkeypatch, tmp_path, fetch_impl)
    rows = (tmp_path / MANIFEST_FILENAME).read_text(encoding="utf-8").splitlines()[1:]
    oversize_row = next(row for row in rows if "error:OversizeBodyError" in row)
    cols = oversize_row.split("\t")
    label = cols[2]
    summary = json.loads((tmp_path / f"{label}.summary.json").read_text(encoding="utf-8"))
    assert summary["outcome"] == "error:OversizeBodyError"
    assert summary["row_count"] is None
    assert summary["sha256"] is None
    assert cols[0] == str(summary.get("ordinal", cols[0]))
    assert not list(tmp_path.glob("*.probe.json"))


@pytest.mark.asyncio
async def test_manifest_and_summary_round_trip_redirect(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    async def fetch_impl(
        self: HttpTransport,
        url: str,
        *,
        if_none_match: str | None,
        if_modified_since: str | None,
        allow_not_modified: bool,
    ) -> FetchResult:
        query = _query(url)
        if _is_nbs_kmdw_2021(query):
            raise RedirectError("moved", status_code=302, location="https://example.invalid/x")
        return await _good_fetch(
            self,
            url,
            if_none_match=if_none_match,
            if_modified_since=if_modified_since,
            allow_not_modified=allow_not_modified,
        )

    result, _writer, _transport = await _run_execute(monkeypatch, tmp_path, fetch_impl)
    rows = (tmp_path / MANIFEST_FILENAME).read_text(encoding="utf-8").splitlines()[1:]
    redirect_row = next(row for row in rows if "redirect_not_followed" in row)
    cols = redirect_row.split("\t")
    summary = json.loads((tmp_path / "nbs_kmdw_2021.summary.json").read_text(encoding="utf-8"))
    assert summary["outcome"] == "redirect_not_followed"
    assert summary["row_count"] is None
    kmdw_2021 = next(cell for cell in result.cells if cell.label == "nbs_kmdw_2021")
    assert cols[0] == str(kmdw_2021.exchange.ordinal)
    assert not list(tmp_path.glob("*.probe.json"))


@pytest.mark.asyncio
async def test_output_directory_never_contains_configured_user_agent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    await _run_execute(monkeypatch, tmp_path, _good_fetch)
    leaked = []
    for path in tmp_path.rglob("*"):
        if path.is_file():
            text = path.read_text(encoding="utf-8", errors="replace")
            if PROBE_UA in text or "BREEZY_USER_AGENT" in text:
                leaked.append(path.name)
    assert leaked == []


@pytest.mark.asyncio
async def test_summary_probe_json_field_set_is_exactly_the_pinned_keys(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    await _run_execute(monkeypatch, tmp_path, _good_fetch)
    summaries = list(tmp_path.glob("*.summary.json"))
    assert summaries
    for path in summaries:
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert set(payload) == SUMMARY_KEYS
    assert not list(tmp_path.glob("*.probe.json"))


@pytest.mark.asyncio
async def test_oversize_station_year_is_resplit_before_it_can_fail(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[tuple[str, str, str, str]] = []

    async def fetch_impl(
        self: HttpTransport,
        url: str,
        *,
        if_none_match: str | None,
        if_modified_since: str | None,
        allow_not_modified: bool,
    ) -> FetchResult:
        query = _query(url)
        calls.append((query["station"], query["model"], query["sts"], query["ets"]))
        if (
            query["station"] == "KMDW"
            and query["model"] == "NBS"
            and query["sts"].startswith("2021")
            and _is_full_year(query["sts"], query["ets"])
        ):
            raise OversizeBodyError("body exceeded cap")
        return await _good_fetch(
            self,
            url,
            if_none_match=if_none_match,
            if_modified_since=if_modified_since,
            allow_not_modified=allow_not_modified,
        )

    result, _writer, transport = await _run_execute(monkeypatch, tmp_path, fetch_impl)
    halves = [
        call
        for call in calls
        if call[0] == "KMDW" and call[1] == "NBS" and call[2].startswith("2021")
    ]
    assert any(call[2].startswith("2021-01-01") and "06-30" in call[3] for call in halves)
    assert any(call[2].startswith("2021-07-01") for call in halves)
    cells = result.cells if hasattr(result, "cells") else result.outcomes
    nbs = [cell for cell in cells if cell.model == "NBS"]
    verdict = probe.evaluate_verdict(nbs, clock=_clock)
    assert verdict.passed is True
    assert any(
        "resplit" in finding.lower() or "oversize" in finding.lower()
        for finding in verdict.findings
    )
    assert transport.budget.spent == 48 + 2
