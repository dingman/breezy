"""F13 B0 backfill: PFM history (AFOS) and GFS MOS (incl. KNYC), MockTransport only.

The coordinator runs the real thing; every test here runs offline against ``tmp_path``.
"""

from __future__ import annotations

import ast
import datetime as dt
import hashlib
import json
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from breezy.ingest.http import RateLimitedError
from breezy.ingest.probe_transport import RequestBudgetExceededError
from breezy.persistence.us_source_request import US_PFM_AFOS_SOURCE
from breezy.persistence.us_source_revision_store import UsSourceRevisionStore
from scripts.analysis import release_census as census
from scripts.archive import us_source_backfill as bf
from tests.support.mock_http import install_mock_http

_NS = 1_000_000_000
_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "us_sources"
_SCRIPT = Path(bf.__file__)


def _utc(day: int, hour: int = 0, minute: int = 0, *, month: int = 10) -> int:
    return int(dt.datetime(2026, month, day, hour, minute, tzinfo=dt.UTC).timestamp()) * _NS


def _okx_product(header_ddhhmm: str = "051901") -> str:
    lines = (_FIXTURES / "pfm_okx_real_20261006.txt").read_text().splitlines(keepends=True)
    text = "".join(ln for ln in lines if not ln.startswith("#"))
    return text.replace("051901", header_ddhhmm)


class _Clock:
    def __init__(self, now_ns: int) -> None:
        self.now = now_ns

    def __call__(self) -> int:
        return self.now

    def timestamp_ns(self) -> int:
        return self.now


class _Sleeps:
    def __init__(self) -> None:
        self.seconds: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.seconds.append(seconds)


class _Catalog:
    """A fake AFOS: ascending products from ``sdate``, at most ``limit`` per call."""

    def __init__(self, headers: list[str]) -> None:
        self.products = [(h, _okx_product(h)) for h in headers]
        self.calls: list[tuple[str, dt.date, int]] = []

    def __call__(self, wfo: str, sdate: dt.date, limit: int) -> str:
        self.calls.append((wfo, sdate, limit))
        eligible = [p for h, p in self.products if int(h[:2]) >= sdate.day]
        return "".join(eligible[:limit])


def _store(root: Path, clock: _Clock) -> UsSourceRevisionStore:
    return UsSourceRevisionStore(root, clock)


def _leg(
    tmp_path: Path,
    fetch: Any,
    *,
    start: dt.date = dt.date(2026, 10, 5),
    end: dt.date = dt.date(2026, 10, 9),
    page_limit: int = 2,
    window_ok: Any = None,
    sleep: Any = None,
    clock: _Clock | None = None,
    station: str = "KNYC",
) -> bf.LegReport:
    clk = clock or _Clock(_utc(9, 12))
    return bf.run_pfm_leg(
        station=station,
        start=start,
        end=end,
        fetch=fetch,
        store=_store(tmp_path, clk),
        clock_ns=clk,
        window_ok=window_ok or (lambda _now: True),
        sleep=sleep or _Sleeps(),
        page_limit=page_limit,
    )


# ------------------------------------------------------------ pure helpers


def test_split_products_splits_on_soh_strips_etx_and_drops_empties() -> None:
    text = "\x01\nA header\nbody\n\x03\x01\nB header\nbody2\n\x03"

    products = bf.split_products(text)

    assert products == ("\x01\nA header\nbody", "\x01\nB header\nbody2")
    assert bf.split_products("") == ()
    assert bf.split_products("   \n") == ()


def test_wmo_header_fields_come_from_the_header_line_only() -> None:
    assert bf.wmo_header_fields(_okx_product("051901")) == ("KOKX", 5, 19, 1)
    assert bf.wmo_header_fields("\x01\nno header here\n") is None


def test_issuance_sequence_resolves_month_rollover_from_the_start_date() -> None:
    headers = [(30, 12, 0), (31, 6, 0), (1, 5, 0), (1, 18, 30)]

    resolved = bf.resolve_issuance_sequence(headers, dt.date(2026, 1, 30))

    assert resolved == [
        dt.datetime(2026, 1, 30, 12, 0, tzinfo=dt.UTC),
        dt.datetime(2026, 1, 31, 6, 0, tzinfo=dt.UTC),
        dt.datetime(2026, 2, 1, 5, 0, tzinfo=dt.UTC),
        dt.datetime(2026, 2, 1, 18, 30, tzinfo=dt.UTC),
    ]


def test_issuance_sequence_first_day_before_the_start_day_is_next_month_and_skips_bad_days() -> (
    None
):
    assert bf.resolve_issuance_sequence([(2, 0, 0)], dt.date(2026, 1, 28)) == [
        dt.datetime(2026, 2, 2, 0, 0, tzinfo=dt.UTC)
    ]
    # day 31 does not exist in April: it must land in May, never raise
    assert bf.resolve_issuance_sequence([(31, 1, 0)], dt.date(2026, 4, 20)) == [
        dt.datetime(2026, 5, 31, 1, 0, tzinfo=dt.UTC)
    ]


def test_issuance_sequence_refuses_an_implausible_jump() -> None:
    # day 30 after Jan 31 skips invalid Feb 30 and lands in March: a 58-day hole
    with pytest.raises(ValueError, match="gap"):
        bf.resolve_issuance_sequence([(31, 0, 0), (30, 0, 0)], dt.date(2026, 1, 1))


# ----------------------------------------------------------------- PFM leg


def test_pfm_leg_stores_each_product_keyed_by_its_wmo_issuance_time(tmp_path: Path) -> None:
    catalog = _Catalog(["051901", "061901"])

    report = _leg(tmp_path, catalog, end=dt.date(2026, 10, 6), page_limit=10)

    assert report.status == "complete"
    assert (report.appended, report.unchanged, report.refused_total) == (2, 0, 0)
    times = census.pfm_issuance_times(tmp_path)
    assert times == {"OKX": (_utc(5, 19, 1), _utc(6, 19, 1))}
    store = _store(tmp_path, _Clock(0))
    assert store.revisions(US_PFM_AFOS_SOURCE, "KNYC", _utc(5, 19, 1), "pfm")[0][0] == 0


def test_identical_rerun_appends_nothing(tmp_path: Path) -> None:
    catalog = _Catalog(["051901", "061901"])
    _leg(tmp_path, catalog, end=dt.date(2026, 10, 6), page_limit=10)

    again = _leg(tmp_path, catalog, end=dt.date(2026, 10, 6), page_limit=10)

    assert (again.appended, again.unchanged) == (0, 2)


def test_pagination_advances_from_the_last_issuance_date_and_dedupes_the_overlap(
    tmp_path: Path,
) -> None:
    catalog = _Catalog(["051901", "061901", "071901"])

    report = _leg(tmp_path, catalog, page_limit=2)

    assert [c[1] for c in catalog.calls] == [
        dt.date(2026, 10, 5),
        dt.date(2026, 10, 6),
        dt.date(2026, 10, 7),
    ]
    assert report.requests == 3
    assert (report.appended, report.unchanged) == (3, 2)  # Oct 6 and Oct 7 each fetched twice
    assert report.status == "complete"


def test_a_full_page_inside_one_date_is_flagged_truncated_not_silently_skipped(
    tmp_path: Path,
) -> None:
    catalog = _Catalog(["051901", "052001"])

    report = _leg(tmp_path, catalog, page_limit=2)

    assert report.truncated_days == (dt.date(2026, 10, 5),)
    assert report.status == "complete"


def test_products_outside_the_requested_end_date_are_not_stored(tmp_path: Path) -> None:
    catalog = _Catalog(["051901", "071901"])

    report = _leg(tmp_path, catalog, end=dt.date(2026, 10, 6))

    assert report.appended == 1
    assert census.pfm_issuance_times(tmp_path) == {"OKX": (_utc(5, 19, 1),)}


def test_unparsable_or_foreign_products_are_refused_with_a_reason_and_never_written(
    tmp_path: Path,
) -> None:
    good = _okx_product("051901")
    foreign = _okx_product("061901").replace("KOKX", "KLOT")
    garbled = "\x01\n854 \nFOUS51 KOKX 071901\nPFMOKX\n\nnot a matrix\n"

    def fetch(_wfo: str, _sdate: dt.date, _limit: int) -> str:
        return good + foreign + garbled

    report = _leg(tmp_path, fetch, page_limit=50)

    assert report.appended == 1
    assert report.refused_total == 2
    assert set(report.refused) == {"wfo_mismatch", "point_not_unique"}
    assert census.pfm_issuance_times(tmp_path) == {"OKX": (_utc(5, 19, 1),)}


def test_budget_exhaustion_stops_the_leg_and_names_the_resume_date(tmp_path: Path) -> None:
    catalog = _Catalog(["051901", "061901", "071901"])
    state = {"n": 0}

    def fetch(wfo: str, sdate: dt.date, limit: int) -> str:
        state["n"] += 1
        if state["n"] == 2:
            raise RequestBudgetExceededError("budget")
        return catalog(wfo, sdate, limit)

    report = _leg(tmp_path, fetch, page_limit=2)

    assert report.status == "budget_exhausted"
    assert report.appended == 2
    assert report.resume_sdate == dt.date(2026, 10, 6)


def test_the_leg_pauses_before_any_request_inside_the_launch_window(tmp_path: Path) -> None:
    catalog = _Catalog(["051901"])
    clock = _Clock(_utc(9, 16, 45))

    report = _leg(
        tmp_path,
        catalog,
        clock=clock,
        window_ok=bf.make_window_guard(),
    )

    assert report.status == "paused_launch_window"
    assert report.requests == 0
    assert catalog.calls == []
    assert report.resume_sdate == dt.date(2026, 10, 5)


def test_window_guard_allows_outside_and_refuses_when_a_request_could_meet_the_window() -> None:
    guard = bf.make_window_guard()
    assert guard(_utc(9, 12)) is True
    assert guard(_utc(9, 16, 29) + 5 * _NS) is True  # the worst-case request ends before 16:30
    assert guard(_utc(9, 16, 29) + 50 * _NS) is False  # it could run into the window
    assert guard(_utc(9, 16, 30)) is False
    assert guard(_utc(9, 17, 10)) is True


def test_throttle_backs_off_then_stops_as_throttled_and_alerts(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    sleeps = _Sleeps()

    def fetch(_wfo: str, _sdate: dt.date, _limit: int) -> str:
        raise RateLimitedError("Too many requests from your IP address", retry_after=None)

    report = _leg(tmp_path, fetch, sleep=sleeps)

    assert report.status == "throttled"
    assert sleeps.seconds == list(bf.THROTTLE_BACKOFF_S)
    assert report.requests == len(bf.THROTTLE_BACKOFF_S) + 1
    assert report.appended == 0
    assert "ALERT" in capsys.readouterr().err


def test_throttle_that_clears_is_retried_without_losing_the_page(tmp_path: Path) -> None:
    catalog = _Catalog(["051901"])
    state = {"n": 0}

    def fetch(wfo: str, sdate: dt.date, limit: int) -> str:
        state["n"] += 1
        if state["n"] == 1:
            raise RateLimitedError("Too many requests from your IP address", retry_after=None)
        return catalog(wfo, sdate, limit)

    sleeps = _Sleeps()
    report = _leg(tmp_path, fetch, sleep=sleeps)

    assert report.status == "complete"
    assert report.appended == 1
    assert sleeps.seconds == [bf.THROTTLE_BACKOFF_S[0]]


def test_a_store_busy_collector_is_retried_then_reported_not_clobbered(tmp_path: Path) -> None:
    catalog = _Catalog(["051901"])
    clock = _Clock(_utc(9, 12))
    store = _store(tmp_path, clock)
    holder = _store(tmp_path, clock)
    sleeps = _Sleeps()

    with holder.unit_lock(US_PFM_AFOS_SOURCE):
        report = bf.run_pfm_leg(
            station="KNYC",
            start=dt.date(2026, 10, 5),
            end=dt.date(2026, 10, 6),
            fetch=catalog,
            store=store,
            clock_ns=clock,
            window_ok=lambda _n: True,
            sleep=sleeps,
            page_limit=2,
        )

    assert report.status == "store_busy"
    assert report.appended == 0
    assert sleeps.seconds == [bf.BUSY_WAIT_S] * bf.BUSY_RETRIES


# --------------------------------------------------------- transport wiring


def test_afos_requests_go_through_the_paced_transport_with_a0_r1_spacing_and_a_hard_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = _okx_product("051901")
    mock = install_mock_http(monkeypatch, lambda _r: httpx.Response(200, content=body.encode()))
    clock = _Clock(_utc(9, 12))
    slept: list[float] = []

    async def sleeper(seconds: float) -> None:
        slept.append(seconds)

    fetch = bf.make_pfm_fetch(
        request_budget=2,
        user_agent="breezy-test (alias)",
        clock_ns=clock,
        sleeper=sleeper,
        check_proxy_env=False,
    )

    first = fetch("OKX", dt.date(2026, 10, 5), 50)
    second = fetch("OKX", dt.date(2026, 10, 6), 50)

    assert first == body and second == body
    query = parse_qs(urlsplit(str(mock.requests[0].url)).query)
    assert query == {
        "pil": ["PFMOKX"],
        "limit": ["50"],
        "sdate": ["2026-10-05"],
        "order": ["asc"],
        "fmt": ["text"],
    }
    assert slept and slept[0] >= 4.0  # A0-R1: >= 4 s between AFOS requests
    with pytest.raises(RequestBudgetExceededError):
        fetch("OKX", dt.date(2026, 10, 7), 50)
    assert len(mock.requests) == 2


# ------------------------------------------------------------ plan and main


def _args(tmp_path: Path, *extra: str) -> list[str]:
    return [
        "--archive-root",
        str(tmp_path / "archive"),
        "--start-date",
        "2026-10-01",
        "--end-date",
        "2026-10-06",
        "--report-json",
        str(tmp_path / "report.json"),
        *extra,
    ]


def _recording_runner(sink: list[list[str]]) -> Callable[[Sequence[str]], int]:
    def runner(argv: Sequence[str]) -> int:
        sink.append(list(argv))
        return 0

    return runner


def _digest(root: Path) -> str:
    digest = hashlib.sha256()
    if root.exists():
        for path in sorted(p for p in root.rglob("*") if p.is_file()):
            digest.update(str(path.relative_to(root)).encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def test_dry_run_plans_both_legs_with_no_network_and_no_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(_r: httpx.Request) -> httpx.Response:
        raise AssertionError("a dry run must not touch the network")

    install_mock_http(monkeypatch, forbidden)
    before = _digest(tmp_path / "archive")

    rc = bf.main(
        _args(tmp_path, "--dry-run", "--request-budget", "100000", "--start-date", "2022-01-01")
    )

    assert rc == 0
    assert _digest(tmp_path / "archive") == before
    plan = json.loads((tmp_path / "report.json").read_text())
    assert plan["mode"] == "dry_run"
    pfm = plan["pfm"]
    assert sorted(pfm["wfos"]) == ["LOT", "LOX", "MFL", "MTR", "OKX"]
    assert pfm["pacing_s"] >= 4
    assert pfm["estimated_requests"] >= 5
    assert pfm["fits_budget"] is True
    gfs = plan["gfs"]
    assert gfs["model"] == "GFS"
    assert "KNYC" in gfs["stations"]
    assert gfs["years"] == [2022, 2023, 2024, 2025]
    assert gfs["estimated_requests"] == 5 * 4
    assert plan["launch_window_utc"] == "16:30-17:10"


def test_dry_run_flags_a_plan_that_exceeds_the_request_budget(tmp_path: Path) -> None:
    rc = bf.main(_args(tmp_path, "--dry-run", "--request-budget", "1"))

    assert rc == 0
    assert json.loads((tmp_path / "report.json").read_text())["pfm"]["fits_budget"] is False


def test_apply_and_dry_run_are_mutually_exclusive_and_one_is_required(tmp_path: Path) -> None:
    assert bf.main(_args(tmp_path, "--dry-run", "--apply", "--request-budget", "5")) == 2
    assert bf.main(_args(tmp_path, "--request-budget", "5")) == 2


def test_apply_requires_the_live_unlock_and_a_request_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("BREEZY_LIVE", raising=False)
    assert bf.main(_args(tmp_path, "--apply", "--request-budget", "5")) == 2
    monkeypatch.setenv("BREEZY_LIVE", "1")
    assert bf.main(_args(tmp_path, "--apply")) == 2


def test_apply_refuses_to_start_when_the_gfs_span_could_meet_the_launch_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BREEZY_LIVE", "1")
    calls: list[list[str]] = []

    rc = bf.main(
        _args(
            tmp_path,
            "--apply",
            "--request-budget",
            "5",
            "--legs",
            "gfs",
            "--max-runtime-s",
            "7200",
            "--start-date",
            "2022-01-01",
        ),
        clock=lambda: _utc(6, 15, 0),
        gfs_runner=_recording_runner(calls),
    )

    assert rc == 2
    assert calls == []


def test_apply_delegates_gfs_to_the_existing_mos_path_for_every_station_including_knyc(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BREEZY_LIVE", "1")
    calls: list[list[str]] = []

    rc = bf.main(
        _args(
            tmp_path,
            "--apply",
            "--request-budget",
            "5",
            "--legs",
            "gfs",
            "--max-runtime-s",
            "600",
            "--start-date",
            "2022-01-01",
        ),
        clock=lambda: _utc(6, 12, 0),
        gfs_runner=_recording_runner(calls),
    )

    assert rc == 0
    (argv,) = calls
    assert argv[argv.index("--model") + 1] == "GFS"
    assert "--apply" in argv and "--dry-run" not in argv
    stations_at = argv.index("--stations") + 1
    assert {"KNYC", "KLAX", "KMDW", "KMIA", "KSFO"} <= set(argv[stations_at : stations_at + 5])
    assert argv[argv.index("--first-year") + 1] == "2022"
    assert argv[argv.index("--through-year") + 1] == "2025"
    assert "--request-budget" in argv


def test_apply_runs_the_pfm_leg_through_the_injected_fetch_and_reports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BREEZY_LIVE", "1")
    catalog = _Catalog(["051901", "061901"])
    made: dict[str, Any] = {}

    def factory(**kwargs: Any) -> Any:
        made.update(kwargs)
        return lambda wfo, sdate, limit: catalog(wfo, sdate, limit) if wfo == "OKX" else ""

    rc = bf.main(
        _args(
            tmp_path,
            "--apply",
            "--request-budget",
            "50",
            "--legs",
            "pfm",
            "--stations",
            "KNYC",
            "KLAX",
        ),
        clock=lambda: _utc(9, 12, 0),
        sleep=lambda _s: None,
        pfm_fetch_factory=factory,
    )

    assert rc == 0
    assert made["request_budget"] == 50
    report = json.loads((tmp_path / "report.json").read_text())
    assert report["mode"] == "apply"
    legs = {leg["station"]: leg for leg in report["pfm"]["legs"]}
    assert legs["KNYC"]["status"] == "complete" and legs["KNYC"]["appended"] == 2
    assert legs["KLAX"]["appended"] == 0
    assert census.pfm_issuance_times(tmp_path / "archive") == {
        "OKX": (_utc(5, 19, 1), _utc(6, 19, 1))
    }


# ----------------------------------------------------------------- guards


def test_script_writes_only_through_the_revision_store_and_never_names_a_settlement_origin() -> (
    None
):
    text = _SCRIPT.read_text()
    assert "api.weather.gov" not in text
    tree = ast.parse(text)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
        elif isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
    flat = " ".join(sorted(imported))
    for banned in ("breezy.runtime", "breezy.exec", "adapters", "settlement", "cli_parse"):
        assert banned not in flat
    assert "us_source_revision_store" in flat
