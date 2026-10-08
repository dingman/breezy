"""F13 B0 backfill: PFM history (AFOS) and GFS MOS (incl. KNYC), MockTransport only.

The coordinator runs the real thing; every test here runs offline against ``tmp_path``.
"""

from __future__ import annotations

import ast
import datetime as dt
import hashlib
import inspect
import json
import logging
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from breezy.ingest.http import (
    ContentEncodingError,
    DecodeError,
    DisallowedHostError,
    ForbiddenError,
    OversizeBodyError,
    RateLimitedError,
    RedirectError,
    ServerError,
    TransportError,
    TransportTimeoutError,
)
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
    if header_ddhhmm != "051901":
        # The real body prints its own issuance ("301 PM EDT Mon Oct 5 2026"); an edited WMO
        # heading would contradict it (a header_body_mismatch refusal), so the synthetic product
        # drops that line and is placed from the WMO heading alone (the cursor-relative path).
        text = "".join(ln for ln in text.splitlines(keepends=True) if "301 PM EDT" not in ln)
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


def _header_time(header: str) -> dt.datetime:
    return dt.datetime(2026, 10, int(header[:2]), int(header[2:4]), int(header[4:6]), tzinfo=dt.UTC)


class _Catalog:
    """A fake AFOS: ascending products from ``sdate`` (date or UTC instant), at most ``limit``."""

    def __init__(self, headers: list[str]) -> None:
        self.products = [(_header_time(h), _okx_product(h)) for h in headers]
        self.calls: list[tuple[str, dt.date, int]] = []

    def __call__(self, wfo: str, sdate: dt.date, limit: int) -> str:
        self.calls.append((wfo, sdate, limit))
        since = (
            sdate
            if isinstance(sdate, dt.datetime)
            else dt.datetime(sdate.year, sdate.month, sdate.day, tzinfo=dt.UTC)
        )
        eligible = [p for t, p in self.products if t >= since]
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


def test_pfm_leg_opens_one_coverage_batch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    entered: list[int] = []
    real = UsSourceRevisionStore.coverage_batch

    def spy(self: UsSourceRevisionStore) -> Any:
        entered.append(1)
        return real(self)

    monkeypatch.setattr(UsSourceRevisionStore, "coverage_batch", spy)
    report = _leg(tmp_path, lambda _wfo, _sdate, _limit: "")

    assert entered == [1]
    assert report.products_seen == 0


def test_reingest_apply_opens_one_coverage_batch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from us_source_pfm_reingest import reingest_quarantine  # type: ignore[import-not-found]

    quarantine = tmp_path / "quarantine"
    quarantine.mkdir()
    (quarantine / "refusals.jsonl").write_text(
        json.dumps(
            {
                "issued": None,
                "raw_file": "ab.raw",
                "reason": "unparsed",
                "sha256": "ab",
                "station": "KNYC",
                "wfo": "OKX",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    entered: list[int] = []
    real = UsSourceRevisionStore.coverage_batch

    def spy(self: UsSourceRevisionStore) -> Any:
        entered.append(1)
        return real(self)

    monkeypatch.setattr(UsSourceRevisionStore, "coverage_batch", spy)
    store = UsSourceRevisionStore(tmp_path / "archive", _Clock(_utc(9, 12)))
    report = reingest_quarantine(quarantine, store, sleep=lambda _seconds: None)

    assert entered == [1]
    assert report["mode"] == "apply"
    assert report["skipped"] == {"no_issuance": 1}


def test_leg_report_counts_coverage_and_a_drop_is_not_complete(tmp_path: Path) -> None:
    """A csv deleted before the leg's exit flush is counted and the leg is not complete."""
    clock = _Clock(_utc(9, 12))
    inner = _store(tmp_path, clock)

    class _DropCsv:
        def coverage_batch(self) -> Any:
            return inner.coverage_batch()

        def append_if_new(self, **kwargs: Any) -> Any:
            result = inner.append_if_new(**kwargs)
            for payload in (tmp_path / US_PFM_AFOS_SOURCE).glob("*.csv"):
                payload.unlink()
            return result

    report = bf.run_pfm_leg(
        station="KNYC",
        start=dt.date(2026, 10, 5),
        end=dt.date(2026, 10, 5),
        fetch=_Catalog(["051901"]),
        store=_DropCsv(),  # type: ignore[arg-type]
        clock_ns=clock,
        window_ok=lambda _now: True,
        sleep=_Sleeps(),
        page_limit=10,
    )

    assert report.coverage_flushed == 0
    assert report.coverage_dropped == 1
    assert report.coverage_stranded_sources == ()
    assert report.status == "coverage_incomplete"
    body = report.to_dict()
    assert body["coverage_flushed"] == 0
    assert body["coverage_dropped"] == 1
    assert body["coverage_stranded_sources"] == []


def test_successful_leg_records_zero_drops(tmp_path: Path) -> None:
    report = _leg(tmp_path, _Catalog(["051901"]), end=dt.date(2026, 10, 5), page_limit=10)

    assert report.status == "complete"
    assert report.coverage_flushed == report.appended == 1
    assert report.coverage_dropped == 0
    assert report.to_dict()["coverage_stranded_sources"] == []
    assert report.to_dict()["coverage_torn_journal_lines"] == 0


def test_missing_coverage_batch_warns_once_per_run(caplog: pytest.LogCaptureFixture) -> None:
    from breezy.persistence.us_source_revision_store import RevisionStoreIntegrityError

    bf._coverage_batch_unavailable_warned = False
    caplog.set_level(logging.WARNING, logger="us_source_backfill")
    store = _FailingStore(RevisionStoreIntegrityError("digest not in set"))
    _leg_with_store(store, _Catalog(["051901"]))
    _leg_with_store(store, _Catalog(["051901"]))
    warnings = [record for record in caplog.records if record.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "batch" in warnings[0].message.lower()


def test_reingest_flush_failure_still_writes_the_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A flush that raises on the way out must still leave the report and its counters."""
    from breezy.persistence.us_source_revision_store import (
        CoverageDrop,
        RevisionStoreIntegrityError,
        _BatchedCoverageCache,
    )

    quarantine = tmp_path / "quarantine"
    quarantine.mkdir()
    (quarantine / "refusals.jsonl").write_text(
        json.dumps(
            {
                "issued": None,
                "raw_file": "ab.raw",
                "reason": "unparsed",
                "sha256": "ab",
                "station": "KNYC",
                "wfo": "OKX",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    def boom(self: _BatchedCoverageCache) -> None:
        self._batch_flushed = 2
        self._batch_dropped.append(CoverageDrop("k" * 64, "csv_missing"))
        self._batch_stranded.append(US_PFM_AFOS_SOURCE)
        self._batch_torn = 1
        raise RevisionStoreIntegrityError("injected flush failure")

    monkeypatch.setattr(_BatchedCoverageCache, "flush_coverage", boom)
    report_path = tmp_path / "report.json"
    rc = bf.main(
        [
            "--archive-root",
            str(tmp_path / "archive"),
            "--reingest-quarantine",
            str(quarantine),
            "--apply",
            "--report-json",
            str(report_path),
        ]
    )

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert rc == 1
    assert report["complete"] is False
    assert report["error"] == "RevisionStoreIntegrityError: injected flush failure"
    assert report["coverage_flushed"] == 2
    assert report["coverage_dropped"] == 1
    assert report["coverage_stranded_sources"] == [US_PFM_AFOS_SOURCE]
    assert report["coverage_torn_journal_lines"] == 1
    assert report["skipped"] == {"no_issuance": 1}


def test_reingest_report_counts_a_stranded_journal_drop(tmp_path: Path) -> None:
    from us_source_pfm_reingest import reingest_quarantine

    from breezy.persistence.archive_cache import MANIFEST_VERSION, CoverageEntry

    quarantine = tmp_path / "quarantine"
    quarantine.mkdir()
    (quarantine / "refusals.jsonl").write_text(
        json.dumps(
            {
                "issued": None,
                "raw_file": "ab.raw",
                "reason": "unparsed",
                "sha256": "ab",
                "station": "KNYC",
                "wfo": "OKX",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    archive = tmp_path / "archive"
    source = archive / US_PFM_AFOS_SOURCE
    source.mkdir(parents=True)
    entry = CoverageEntry(
        cache_key="a" * 64,
        station="KNYC",
        product="pfm-r0",
        window_start=1,
        window_end=2,
        rows=1,
        bytes=1,
        sha256="b" * 64,
        fetched_at_ns=1,
        model="OKX",
        manifest_version=MANIFEST_VERSION,
    )
    (source / "coverage.pending.jsonl").write_text(
        json.dumps(entry.to_dict(), sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    store = UsSourceRevisionStore(archive, _Clock(_utc(9, 12)))

    report = reingest_quarantine(quarantine, store, sleep=lambda _seconds: None)

    assert report["coverage_flushed"] == 0
    assert report["coverage_dropped"] == 1
    assert report["coverage_stranded_sources"] == []
    assert report["complete"] is False


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


def test_pagination_continues_from_the_last_issuance_instant_and_dedupes_the_overlap(
    tmp_path: Path,
) -> None:
    catalog = _Catalog(["051901", "061901", "071901"])

    report = _leg(tmp_path, catalog, page_limit=2)

    assert [c[1] for c in catalog.calls] == [
        dt.datetime(2026, 10, 5, tzinfo=dt.UTC),
        dt.datetime(2026, 10, 6, 19, 1, tzinfo=dt.UTC),
        dt.datetime(2026, 10, 7, 19, 1, tzinfo=dt.UTC),
    ]
    assert report.requests == 3
    assert (report.appended, report.unchanged) == (3, 2)  # each page re-reads the last product
    assert report.status == "complete"


def test_full_page_continues_same_day_without_loss(tmp_path: Path) -> None:
    headers = ["05" + f"{h:02d}05" for h in range(24)]
    catalog = _Catalog(headers)

    report = _leg(tmp_path, catalog, end=dt.date(2026, 10, 5), page_limit=20)

    assert report.appended == 24
    assert census.pfm_issuance_times(tmp_path) == {"OKX": tuple(_utc(5, h, 5) for h in range(24))}
    assert report.status == "complete"
    assert report.truncated_days == ()


def test_hourly_office_has_no_truncated_days(tmp_path: Path) -> None:
    headers = [f"{d:02d}{h:02d}05" for d in range(5, 8) for h in range(24)]
    catalog = _Catalog(headers)

    report = _leg(tmp_path, catalog, end=dt.date(2026, 10, 7), page_limit=20)

    assert report.truncated_days == ()
    assert report.appended == 72
    assert report.refused_total == 0
    assert len(census.pfm_issuance_times(tmp_path)["OKX"]) == 72
    assert report.requests <= 5  # ~19 new products per request, not one request per day


def test_a_full_page_that_cannot_advance_is_flagged_truncated_not_silently_skipped(
    tmp_path: Path,
) -> None:
    catalog = _Catalog(["051901", "051901", "051901"])

    report = _leg(tmp_path, catalog, end=dt.date(2026, 10, 5), page_limit=2)

    assert report.truncated_days == (dt.date(2026, 10, 5),)
    assert report.status == "complete"
    assert [c[1] for c in catalog.calls][-1] == dt.datetime(2026, 10, 5, 19, 2, tzinfo=dt.UTC)


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


# ======================================================================
# Review fixes P2-P8 (2026-10-06). Appended; no earlier assertion was changed.
# ======================================================================

_BAD_GAP_START = dt.date(2026, 11, 5)


def _unplaceable_catalog(_wfo: str, _sdate: dt.date, _limit: int) -> str:
    # Nov has no day 31: the header resolves to 12-31, a 56 day gap, which is unplaceable.
    return _okx_product("311901")


# ---- P2: an unplaceable header ends that station, not the run


def test_p2_a_gap_over_45_days_marks_the_leg_unplaceable_instead_of_raising(
    tmp_path: Path,
) -> None:
    report = _leg(
        tmp_path,
        _unplaceable_catalog,
        start=_BAD_GAP_START,
        end=dt.date(2027, 1, 31),
        page_limit=10,
    )

    assert report.status == "unplaceable_header"
    assert report.resume_sdate == _BAD_GAP_START
    assert report.refused == {"unplaceable_header": 1}
    assert report.appended == 0


def test_p2_main_continues_with_the_next_station_exits_1_and_still_writes_the_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BREEZY_LIVE", "1")
    seen: list[str] = []

    def factory(**_kwargs: Any) -> Any:
        def fetch(wfo: str, _sdate: dt.date, _limit: int) -> str:
            seen.append(wfo)
            return _okx_product("311901") if wfo == "OKX" else ""

        return fetch

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
            "--start-date",
            "2026-11-05",
            "--end-date",
            "2027-01-31",
        ),
        clock=lambda: _utc(9, 12, 0),
        sleep=lambda _s: None,
        pfm_fetch_factory=factory,
    )

    assert rc == 1
    assert seen == ["OKX", "LOX"]
    report = json.loads((tmp_path / "report.json").read_text())
    statuses = {leg["station"]: leg["status"] for leg in report["pfm"]["legs"]}
    assert statuses == {"KNYC": "unplaceable_header", "KLAX": "complete"}


# ---- P7: a header that cannot be placed unambiguously is refused, not mis-placed


def test_p7_an_out_of_order_header_is_refused_not_pushed_a_month_ahead(tmp_path: Path) -> None:
    # Amended 2026-10-06 (PFM history fix): the original 051901 then 051801 is a same-day
    # inversion, now placed on that day (see test_us_source_pfm_history). The refusal is kept
    # for a header from an EARLIER day (041901 after 061901), which would only "fit" as next
    # month; the refusal now covers that product alone and the station continues.
    def fetch(_wfo: str, _sdate: dt.date, _limit: int) -> str:
        return _okx_product("061901") + _okx_product("041901")

    report = _leg(tmp_path, fetch, page_limit=10)

    assert report.status == "complete"
    assert report.appended == 1
    placed = int(dt.datetime(2026, 10, 6, 19, 1, tzinfo=dt.UTC).timestamp()) * 1_000_000_000
    assert census.pfm_issuance_times(tmp_path) == {"OKX": (placed,)}
    assert report.refused == {"unplaceable_header": 1}


def test_p7_a_genuine_month_rollover_still_places() -> None:
    report = bf.LegReport(station="KNYC", wfo="OKX")
    products = (_okx_product("311901"), _okx_product("011901"))

    paired = bf._place(products, dt.date(2026, 10, 31), report)

    assert [issued for _p, issued in paired] == [
        dt.datetime(2026, 10, 31, 19, 1, tzinfo=dt.UTC),
        dt.datetime(2026, 11, 1, 19, 1, tzinfo=dt.UTC),
    ]


# ---- P3: store errors degrade the leg and the exit code


class _FailingStore:
    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    def append_if_new(self, **_kwargs: Any) -> Any:
        raise self._exc


def _leg_with_store(store: Any, fetch: Any) -> bf.LegReport:
    clk = _Clock(_utc(9, 12))
    return bf.run_pfm_leg(
        station="KNYC",
        start=dt.date(2026, 10, 5),
        end=dt.date(2026, 10, 9),
        fetch=fetch,
        store=store,
        clock_ns=clk,
        window_ok=lambda _n: True,
        sleep=_Sleeps(),
        page_limit=10,
    )


def test_p3_a_revision_store_integrity_error_degrades_the_leg_not_refuses_it() -> None:
    from breezy.persistence.us_source_revision_store import RevisionStoreIntegrityError

    report = _leg_with_store(
        _FailingStore(RevisionStoreIntegrityError("digest not in set")),
        _Catalog(["051901"]),
    )

    assert report.status == "degraded"
    assert report.refused_total == 0  # `refused` is for expected parse refusals only
    assert report.store_errors == {"RevisionStoreIntegrityError": 1}
    assert report.to_dict()["store_errors"] == {"RevisionStoreIntegrityError": 1}


def test_p3_a_payload_refused_by_the_store_is_an_expected_refusal() -> None:
    from breezy.persistence.us_source_revision_store import RevisionPayloadRefusedError

    report = _leg_with_store(
        _FailingStore(RevisionPayloadRefusedError("not csv")), _Catalog(["051901"])
    )

    assert report.status == "complete"
    assert report.refused == {"RevisionPayloadRefusedError": 1}
    assert report.store_errors == {}


def test_p3_main_exits_1_when_a_leg_is_degraded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from breezy.persistence.us_source_revision_store import RevisionStoreIntegrityError

    monkeypatch.setenv("BREEZY_LIVE", "1")

    class _Broken:
        def __init__(self, *_a: Any, **_k: Any) -> None: ...

        def append_if_new(self, **_kwargs: Any) -> Any:
            raise RevisionStoreIntegrityError("boom")

    monkeypatch.setattr(bf, "UsSourceRevisionStore", _Broken)
    catalog = _Catalog(["051901"])

    rc = bf.main(
        _args(tmp_path, "--apply", "--request-budget", "50", "--legs", "pfm", "--stations", "KNYC"),
        clock=lambda: _utc(9, 12, 0),
        sleep=lambda _s: None,
        pfm_fetch_factory=lambda **_k: catalog,
    )

    assert rc == 1
    leg = json.loads((tmp_path / "report.json").read_text())["pfm"]["legs"][0]
    assert leg["status"] == "degraded"


# ---- P4: byte-identical framing with the live collector


def _collector_payload(response_text: str) -> bytes:
    """What ``us_source_collector.default_pfm_fetcher`` stores: the whole response, UTF-8."""
    return response_text.encode("utf-8")


@pytest.mark.parametrize("suffix", ["\x03", "\x03\n", "\n\x03"])
def test_p4_a_live_collected_issuance_is_unchanged_not_a_new_revision_under_backfill(
    tmp_path: Path, suffix: str
) -> None:
    response = _okx_product("051901") + suffix  # a limit=1 AFOS response, SOH ... ETX
    clk = _Clock(_utc(9, 12))
    store = _store(tmp_path, clk)
    store.append_if_new(
        source=US_PFM_AFOS_SOURCE,
        station="KNYC",
        run_ts_ns=_utc(5, 19, 1),
        model="OKX",
        payload=_collector_payload(response),
    )

    report = _leg(tmp_path, lambda _w, _s, _l: response, page_limit=10)

    assert (report.appended, report.unchanged) == (0, 1)
    assert store.revisions(US_PFM_AFOS_SOURCE, "KNYC", _utc(5, 19, 1), "pfm")[-1][0] == 0


def test_p4_split_raw_products_keeps_each_product_exactly_as_the_response_framed_it() -> None:
    one = _okx_product("051901") + "\x03"
    two = _okx_product("061901") + "\x03\n"

    assert bf.split_raw_products(one) == (one,)
    assert bf.split_raw_products(one + two) == (one, two)
    assert bf.split_raw_products("  \n") == ()


# ---- P5: the GFS leg is re-checked against the launch window when it actually starts


def test_p5_gfs_is_refused_and_recorded_when_the_pfm_leg_ate_the_time_before_the_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BREEZY_LIVE", "1")
    clock = _Clock(_utc(9, 12, 0))
    calls: list[list[str]] = []

    def factory(**_kwargs: Any) -> Any:
        def fetch(_wfo: str, _sdate: dt.date, _limit: int) -> str:
            clock.now = _utc(9, 15, 45)  # the PFM leg ran for hours
            return ""

        return fetch

    rc = bf.main(
        _args(
            tmp_path,
            "--apply",
            "--request-budget",
            "50",
            "--legs",
            "pfm",
            "gfs",
            "--stations",
            "KNYC",
            "--max-runtime-s",
            "3600",
            "--start-date",
            "2022-01-01",
        ),
        clock=clock,
        sleep=lambda _s: None,
        pfm_fetch_factory=factory,
        gfs_runner=_recording_runner(calls),
    )

    assert rc == 1
    assert calls == []
    gfs = json.loads((tmp_path / "report.json").read_text())["gfs"]
    assert gfs["status"] == "refused_launch_window"
    assert gfs["max_runtime_s"] == 3600
    assert gfs["seconds_to_window"] == 45 * 60


def test_p5_gfs_start_records_the_remaining_time_to_the_window_when_it_proceeds(
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
    gfs = json.loads((tmp_path / "report.json").read_text())["gfs"]
    assert gfs["seconds_to_window"] == 4 * 3600 + 30 * 60
    assert gfs["max_runtime_s"] == 600


# ---- P6: a throttle or a launch-window pause stops everything that remains


def test_p6_a_throttle_stops_remaining_stations_and_the_gfs_leg(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BREEZY_LIVE", "1")
    fetched: list[str] = []
    calls: list[list[str]] = []

    def factory(**_kwargs: Any) -> Any:
        def fetch(wfo: str, _sdate: dt.date, _limit: int) -> str:
            fetched.append(wfo)
            raise RateLimitedError("Too many requests", retry_after=None)

        return fetch

    rc = bf.main(
        _args(
            tmp_path,
            "--apply",
            "--request-budget",
            "50",
            "--legs",
            "pfm",
            "gfs",
            "--stations",
            "KNYC",
            "KLAX",
            "KMIA",
            "--start-date",
            "2022-01-01",
        ),
        clock=lambda: _utc(6, 12, 0),
        sleep=lambda _s: None,
        pfm_fetch_factory=factory,
        gfs_runner=_recording_runner(calls),
    )

    assert rc == 1
    assert set(fetched) == {"OKX"}
    assert calls == []
    report = json.loads((tmp_path / "report.json").read_text())
    assert [leg["station"] for leg in report["pfm"]["legs"]] == ["KNYC"]
    assert report["pfm"]["stopped"] == {
        "reason": "throttled",
        "skipped_stations": ["KLAX", "KMIA"],
    }
    assert report["gfs"]["status"] == "skipped_after_stop"


def test_forbidden_403_stops_all_remaining_stations_and_gfs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BREEZY_LIVE", "1")
    fetched: list[str] = []
    calls: list[list[str]] = []

    def factory(**_kwargs: Any) -> Any:
        def fetch(wfo: str, _sdate: dt.date, _limit: int) -> str:
            fetched.append(wfo)
            raise ForbiddenError("403 abuse block")

        return fetch

    rc = bf.main(
        _args(
            tmp_path,
            "--apply",
            "--request-budget",
            "50",
            "--legs",
            "pfm",
            "gfs",
            "--stations",
            "KNYC",
            "KLAX",
            "KMIA",
            "--start-date",
            "2022-01-01",
        ),
        clock=lambda: _utc(6, 12, 0),
        sleep=lambda _s: None,
        pfm_fetch_factory=factory,
        gfs_runner=_recording_runner(calls),
    )

    assert rc == 1
    assert fetched == ["OKX"]
    assert calls == []
    report = json.loads((tmp_path / "report.json").read_text())
    legs = report["pfm"]["legs"]
    assert [leg["station"] for leg in legs] == ["KNYC"]
    assert legs[0]["status"] == "forbidden"
    assert legs[0]["resume_sdate"] == "2022-01-01"
    assert report["pfm"]["stopped"] == {
        "reason": "forbidden",
        "skipped_stations": ["KLAX", "KMIA"],
    }
    assert report["gfs"]["status"] == "skipped_after_stop"


def test_p6_a_launch_window_pause_stops_remaining_stations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BREEZY_LIVE", "1")
    fetched: list[str] = []

    def factory(**_kwargs: Any) -> Any:
        def fetch(wfo: str, _sdate: dt.date, _limit: int) -> str:
            fetched.append(wfo)
            return ""

        return fetch

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
        clock=lambda: _utc(6, 16, 45),
        sleep=lambda _s: None,
        pfm_fetch_factory=factory,
    )

    assert rc == 1
    assert fetched == []
    report = json.loads((tmp_path / "report.json").read_text())
    assert [leg["status"] for leg in report["pfm"]["legs"]] == ["paused_launch_window"]
    assert report["pfm"]["stopped"]["skipped_stations"] == ["KLAX"]


# ---- P8: the archive root may not sit in the holdout or the live data root


def test_p8_archive_root_under_the_live_data_root_is_refused_except_the_us_source_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    live = tmp_path / "live"
    monkeypatch.setattr(bf, "LIVE_DATA_ROOT", live)

    for bad in (live, live / "catalog" / "quote_tape", live / "exec_store"):
        argv = ["--dry-run", "--legs", "pfm", "--archive-root", str(bad)]
        assert bf.main(argv) == 2, bad
    ok = ["--dry-run", "--legs", "pfm", "--archive-root", str(live / "us_source_archive")]
    assert bf.main(ok) == 0


def test_p8_archive_root_in_a_holdout_directory_is_refused(tmp_path: Path) -> None:
    argv = ["--dry-run", "--legs", "pfm", "--archive-root", str(tmp_path / "Holdout_2026" / "a")]

    assert bf.main(argv) == 2


# ---- B0 fix: oversize AFOS pages adapt the page size; the report is always written


def _oversize() -> OversizeBodyError:
    return OversizeBodyError("Response body exceeded the 2097152-byte cap during streaming")


def _apply_main(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fetch: Any, *stations: str, **kw: Any
) -> int:
    monkeypatch.setenv("BREEZY_LIVE", "1")
    return bf.main(
        _args(
            tmp_path,
            "--apply",
            "--request-budget",
            "50",
            "--legs",
            "pfm",
            "--stations",
            *stations,
        ),
        clock=lambda: _utc(9, 12, 0),
        sleep=lambda _s: None,
        pfm_fetch_factory=lambda **_k: fetch,
        **kw,
    )


def test_oversize_page_halves_limit_and_retries_same_sdate(tmp_path: Path) -> None:
    catalog = _Catalog(["051901", "061901", "071901"])
    calls: list[tuple[str, dt.date, int]] = []

    def fetch(wfo: str, sdate: dt.date, limit: int) -> str:
        calls.append((wfo, sdate, limit))
        if limit > 5:
            raise _oversize()
        return catalog(wfo, sdate, limit)

    report = _leg(tmp_path, fetch, page_limit=20, end=dt.date(2026, 10, 9))

    assert [limit for _w, _s, limit in calls[:3]] == [20, 10, 5]
    assert {sdate for _w, sdate, _l in calls[:3]} == {dt.datetime(2026, 10, 5, tzinfo=dt.UTC)}
    assert report.status == "complete"
    assert report.appended == 3
    assert report.requests == len(calls)


def test_single_product_oversize_marks_station_and_continues(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    catalog = _Catalog(["051901"])
    calls: list[tuple[str, int]] = []

    def fetch(wfo: str, sdate: dt.date, limit: int) -> str:
        calls.append((wfo, limit))
        if wfo == "OKX":
            raise _oversize()
        return catalog(wfo, sdate, limit) if wfo == "LOX" else ""

    rc = _apply_main(tmp_path, monkeypatch, fetch, "KNYC", "KLAX")

    assert rc == 1
    assert [limit for wfo, limit in calls if wfo == "OKX"] == [20, 10, 5, 2, 1]
    assert any(wfo == "LOX" for wfo, _l in calls)
    legs = {
        leg["station"]: leg
        for leg in json.loads((tmp_path / "report.json").read_text())["pfm"]["legs"]
    }
    assert legs["KNYC"]["status"] == "oversize_product"
    assert legs["KNYC"]["resume_sdate"] == "2026-10-01"
    assert legs["KLAX"]["status"] == "complete"


def test_unexpected_exception_records_error_and_still_writes_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[str] = []

    def fetch(wfo: str, _sdate: dt.date, _limit: int) -> str:
        seen.append(wfo)
        if wfo == "OKX":
            raise RuntimeError("boom")
        return ""

    rc = _apply_main(tmp_path, monkeypatch, fetch, "KNYC", "KLAX")

    assert rc == 1
    assert seen == ["OKX", "LOX"]
    legs = {
        leg["station"]: leg
        for leg in json.loads((tmp_path / "report.json").read_text())["pfm"]["legs"]
    }
    assert legs["KNYC"]["status"] == "error"
    assert legs["KNYC"]["error"] == "RuntimeError: boom"
    assert legs["KLAX"]["status"] == "complete"


def test_an_exception_outside_any_station_still_writes_the_report_and_exits_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BREEZY_LIVE", "1")

    def exploding_gfs(_argv: Sequence[str]) -> int:
        raise RuntimeError("mos exploded")

    rc = bf.main(
        _args(
            tmp_path,
            "--apply",
            "--request-budget",
            "50",
            "--stations",
            "KNYC",
            "--start-date",
            "2024-01-01",
        ),
        clock=lambda: _utc(9, 12, 0),
        sleep=lambda _s: None,
        pfm_fetch_factory=lambda **_k: lambda _w, _s, _l: "",
        gfs_runner=exploding_gfs,
    )

    assert rc == 1
    report = json.loads((tmp_path / "report.json").read_text())
    assert report["pfm"]["legs"][0]["status"] == "complete"
    assert report["gfs"]["status"] == "error"
    assert report["gfs"]["error"] == "RuntimeError: mos exploded"


def test_a_crash_in_setup_still_writes_the_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BREEZY_LIVE", "1")

    def factory(**_kwargs: Any) -> Any:
        raise RuntimeError("no transport")

    rc = bf.main(
        _args(tmp_path, "--apply", "--request-budget", "5", "--legs", "pfm"),
        clock=lambda: _utc(9, 12, 0),
        sleep=lambda _s: None,
        pfm_fetch_factory=factory,
    )

    assert rc == 1
    report = json.loads((tmp_path / "report.json").read_text())
    assert report["error"] == "RuntimeError: no transport"


def test_retries_count_against_budget_and_are_paced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    big = b"x" * (2 * 1024 * 1024 + 1)
    small = _okx_product("051901").encode()

    def handler(request: httpx.Request) -> httpx.Response:
        limit = int(parse_qs(urlsplit(str(request.url)).query)["limit"][0])
        return httpx.Response(200, content=big if limit > 5 else small)

    mock = install_mock_http(monkeypatch, handler)
    clock = _Clock(_utc(9, 12))
    slept: list[float] = []

    async def sleeper(seconds: float) -> None:
        slept.append(seconds)
        clock.now += int(seconds * _NS)

    fetch = bf.make_pfm_fetch(
        request_budget=3,
        user_agent="breezy-test (alias)",
        clock_ns=clock,
        sleeper=sleeper,
        check_proxy_env=False,
    )

    report = _leg(tmp_path, fetch, page_limit=20, end=dt.date(2026, 10, 5), clock=clock)

    limits = [int(parse_qs(urlsplit(str(r.url)).query)["limit"][0]) for r in mock.requests]
    assert limits == [20, 10, 5]  # three requests: every oversize retry spent budget
    assert report.requests == 3 and report.appended == 1
    assert len(slept) >= 2 and all(s >= 4.0 for s in slept)  # A0-R1 spacing between retries
    with pytest.raises(RequestBudgetExceededError):
        fetch("OKX", dt.date(2026, 10, 5), 5)


def test_oversize_retry_stops_as_budget_exhausted_when_the_budget_runs_out(
    tmp_path: Path,
) -> None:
    calls = 0

    def fetch(_w: str, _s: dt.date, limit: int) -> str:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RequestBudgetExceededError("spent")
        raise _oversize()

    report = _leg(tmp_path, fetch, page_limit=20)

    assert report.status == "budget_exhausted"
    assert report.resume_sdate == dt.date(2026, 10, 5)


def test_default_page_limit_is_20_and_dry_run_estimate_uses_it(tmp_path: Path) -> None:
    assert bf.DEFAULT_PAGE_LIMIT == 20
    assert inspect.signature(bf.run_pfm_leg).parameters["page_limit"].default == 20

    rc = bf.main(_args(tmp_path, "--dry-run", "--request-budget", "100000", "--stations", "KNYC"))

    assert rc == 0
    pfm = json.loads((tmp_path / "report.json").read_text())["pfm"]
    days = 6  # 2026-10-01 .. 2026-10-06
    assert pfm["page_limit"] == 20
    assert pfm["estimated_requests"] == -(-days * bf.PLANNING_ISSUANCES_PER_DAY // 19)


# ---- transient transport errors: bounded retry with backoff (2026-10-06 LOT/MFL timeouts)


def _timeout() -> TransportTimeoutError:
    return TransportTimeoutError("Timed out fetching https://mesonet.agron.iastate.edu/x")


def test_transient_timeout_is_retried_with_backoff_then_succeeds(tmp_path: Path) -> None:
    catalog = _Catalog(["051901"])
    state = {"n": 0}

    def fetch(wfo: str, sdate: dt.date, limit: int) -> str:
        state["n"] += 1
        if state["n"] == 1:
            raise _timeout()
        if state["n"] == 2:
            raise ServerError("HTTP 503", status_code=503)
        return catalog(wfo, sdate, limit)

    sleeps = _Sleeps()
    report = _leg(tmp_path, fetch, sleep=sleeps)

    assert report.status == "complete"
    assert report.appended == 1
    assert sleeps.seconds == [30.0, 60.0]
    assert report.requests == 3


def test_timeout_retries_exhausted_ends_station_as_error_with_resume(tmp_path: Path) -> None:
    calls = 0

    def fetch(_w: str, _s: dt.date, _l: int) -> str:
        nonlocal calls
        calls += 1
        raise _timeout()

    sleeps = _Sleeps()
    report = _leg(tmp_path, fetch, sleep=sleeps)

    assert report.status == "error"
    assert "TransportTimeoutError" in (report.error or "")
    assert report.resume_sdate == dt.date(2026, 10, 5)
    assert calls == 4  # the first try plus three retries
    assert sleeps.seconds == [30.0, 60.0, 120.0]


def test_timeout_retries_are_charged_to_budget_and_paced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    small = _okx_product("051901").encode()
    state = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        state["n"] += 1
        if state["n"] <= 2:
            raise httpx.ReadTimeout("read timed out")
        return httpx.Response(200, content=small)

    mock = install_mock_http(monkeypatch, handler)
    clock = _Clock(_utc(9, 12))
    paced: list[float] = []

    async def sleeper(seconds: float) -> None:
        paced.append(seconds)
        clock.now += int(seconds * _NS)

    fetch = bf.make_pfm_fetch(
        request_budget=3,
        user_agent="breezy-test (alias)",
        clock_ns=clock,
        sleeper=sleeper,
        check_proxy_env=False,
    )
    backoffs = _Sleeps()
    windows: list[int] = []

    def window_ok(now_ns: int) -> bool:
        windows.append(now_ns)
        return True

    report = _leg(
        tmp_path,
        fetch,
        page_limit=20,
        end=dt.date(2026, 10, 5),
        clock=clock,
        sleep=backoffs,
        window_ok=window_ok,
    )

    assert len(mock.requests) == 3  # every retry spent budget
    assert report.requests == 3 and report.appended == 1
    assert len(windows) == 3  # the launch-window guard ran before every attempt
    assert len(paced) >= 2 and all(s >= 4.0 for s in paced)  # A0-R1 spacing between retries
    with pytest.raises(RequestBudgetExceededError):
        fetch("OKX", dt.date(2026, 10, 5), 5)


def test_timeout_retry_stops_when_the_launch_window_opens(tmp_path: Path) -> None:
    allowed = iter([True, False])

    def fetch(_w: str, _s: dt.date, _l: int) -> str:
        raise _timeout()

    report = _leg(tmp_path, fetch, window_ok=lambda _n: next(allowed, False))

    assert report.status == "paused_launch_window"
    assert report.resume_sdate == dt.date(2026, 10, 5)


def test_forbidden_is_never_retried(tmp_path: Path) -> None:
    calls = 0

    def fetch(_w: str, _s: dt.date, _l: int) -> str:
        nonlocal calls
        calls += 1
        raise ForbiddenError("403 abuse block")

    sleeps = _Sleeps()
    report = _leg(tmp_path, fetch, sleep=sleeps)

    assert report.status == "forbidden"
    assert calls == 1
    assert sleeps.seconds == []


# ---- connection-level transient failures (2026-10-07 LOT/LOX "Server disconnected")


def _wrapped(cause: BaseException) -> TransportError:
    err = TransportError("Transport failure fetching https://mesonet.agron.iastate.edu/x")
    err.__cause__ = cause
    return err


_CONNECTION_CAUSES: list[Callable[[], BaseException]] = [
    lambda: httpx.RemoteProtocolError("Server disconnected without sending a response."),
    lambda: httpx.ConnectError("connection refused"),
    lambda: httpx.ReadError("read failed"),
    lambda: ConnectionResetError("reset by peer"),
]


@pytest.mark.parametrize("make_cause", _CONNECTION_CAUSES)
def test_connection_level_transport_error_is_retried_then_succeeds(
    tmp_path: Path, make_cause: Callable[[], BaseException]
) -> None:
    catalog = _Catalog(["051901"])
    state = {"n": 0}

    def fetch(wfo: str, sdate: dt.date, limit: int) -> str:
        state["n"] += 1
        if state["n"] <= 2:
            raise _wrapped(make_cause())
        return catalog(wfo, sdate, limit)

    sleeps = _Sleeps()
    report = _leg(tmp_path, fetch, sleep=sleeps)

    assert report.status == "complete"
    assert sleeps.seconds == [30.0, 60.0]
    assert report.requests == 3  # each retry consumed request budget accounting


def test_connection_error_retries_exhausted_stops_station(tmp_path: Path) -> None:
    calls = 0

    def fetch(_w: str, _s: dt.date, _l: int) -> str:
        nonlocal calls
        calls += 1
        raise _wrapped(httpx.RemoteProtocolError("Server disconnected without sending a response."))

    sleeps = _Sleeps()
    report = _leg(tmp_path, fetch, sleep=sleeps)

    assert report.status == "error"
    assert calls == 4
    assert sleeps.seconds == [30.0, 60.0, 120.0]


@pytest.mark.parametrize("status", [502, 503, 504])
def test_gateway_server_errors_are_retried(tmp_path: Path, status: int) -> None:
    catalog = _Catalog(["051901"])
    state = {"n": 0}

    def fetch(wfo: str, sdate: dt.date, limit: int) -> str:
        state["n"] += 1
        if state["n"] == 1:
            raise ServerError(f"HTTP {status}", status_code=status)
        return catalog(wfo, sdate, limit)

    sleeps = _Sleeps()
    report = _leg(tmp_path, fetch, sleep=sleeps)
    assert report.status == "complete" and sleeps.seconds == [30.0]


@pytest.mark.parametrize(
    "make_error",
    [
        lambda: TransportError("Transport failure: something else"),  # no connection cause
        lambda: _wrapped(ValueError("not a connection error")),
        lambda: DecodeError("bad utf-8"),
        lambda: ContentEncodingError("bad encoding"),
        lambda: RedirectError("redirect", status_code=301, location=None),
        lambda: DisallowedHostError("host"),
    ],
)
def test_non_transient_transport_errors_are_not_retried(
    tmp_path: Path, make_error: Callable[[], BaseException]
) -> None:
    calls = 0

    def fetch(_w: str, _s: dt.date, _l: int) -> str:
        nonlocal calls
        calls += 1
        raise make_error()

    sleeps = _Sleeps()
    report = _leg(tmp_path, fetch, sleep=sleeps)

    assert report.status == "error"
    assert calls == 1
    assert sleeps.seconds == []


def test_forbidden_is_never_retried_and_stops_the_leg(tmp_path: Path) -> None:
    calls = 0

    def fetch(_w: str, _s: dt.date, _l: int) -> str:
        nonlocal calls
        calls += 1
        raise ForbiddenError("HTTP 403")

    sleeps = _Sleeps()
    report = _leg(tmp_path, fetch, sleep=sleeps)

    assert report.status == "forbidden"
    assert calls == 1 and sleeps.seconds == []


def test_connection_retry_respects_launch_window_guard(tmp_path: Path) -> None:
    calls = 0

    def fetch(_w: str, _s: dt.date, _l: int) -> str:
        nonlocal calls
        calls += 1
        raise _wrapped(httpx.RemoteProtocolError("Server disconnected"))

    allowed = iter([True, False])
    report = _leg(tmp_path, fetch, sleep=_Sleeps(), window_ok=lambda _n: next(allowed, False))

    assert report.status == "paused_launch_window"
    assert calls == 1
