"""F13 A1: LAMP archive backfill (MDL yearly tars, monthly gz, IEM LAV gap-fill).

The coordinator runs the real thing; every test here is offline: a ``httpx.MockTransport`` under
the real hardened transports, or a stub fetch, with tiny archives built in ``tmp_path`` from the
real-format bulletin in ``tests/fixtures/us_sources``.
"""

from __future__ import annotations

import ast
import calendar
import datetime as dt
import gzip
import io
import json
import tarfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from breezy.analysis.nbp_calibration import DEFAULT_SPLITS
from breezy.ingest.mdl_lamp_transport import (
    DEFAULT_LAMP_MONTH_LIMITS,
    DEFAULT_LAMP_YEAR_LIMITS,
    LAMP_ALLOWED_HOSTS,
    LAMP_MDL_HOST,
    LampArchiveLimits,
    MdlLampTransport,
    build_mdl_lamp_transport,
)
from breezy.persistence.archive_cache import ArchiveCache
from breezy.persistence.us_source_request import (
    US_LAMP_MDL_SOURCE,
    US_LAV_IEM_SOURCE,
    lav_iem_request,
    revision_request,
)
from breezy.persistence.us_source_revision_store import (
    RevisionStoreError,
    UsSourceRevisionStore,
)
from scripts.analysis import release_census as census
from scripts.archive import lamp_archive_backfill as lb
from tests.support.mock_http import install_mock_http

_NS = 1_000_000_000
_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "us_sources"
_SCRIPT = Path(lb.__file__)
_CLOSED = ("KLAX", "KMDW", "KMIA", "KNYC", "KSFO")
_ARCHIVES = f"https://{LAMP_MDL_HOST}/lamp/Data/archives/"
_NOW = dt.datetime(2026, 10, 7, 12, 0, tzinfo=dt.UTC)


def _ns(year: int, month: int, day: int, hour: int = 23, minute: int = 30) -> int:
    return int(dt.datetime(year, month, day, hour, minute, tzinfo=dt.UTC).timestamp()) * _NS


class _Clock:
    """A settable clock whose sleep advances it, so pacing is observable."""

    def __init__(self, now: dt.datetime = _NOW) -> None:
        self.now_ns = int(now.timestamp()) * _NS
        self.sleeps: list[float] = []

    def __call__(self) -> int:
        return self.now_ns

    def timestamp_ns(self) -> int:
        return self.now_ns

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now_ns += int(seconds * _NS)

    async def asleep(self, seconds: float) -> None:
        self.sleep(seconds)


# ------------------------------------------------------------------ archive builders


def _real_text() -> str:
    raw = (_FIXTURES / "lamp_lavtxt_real_20261005_2330z.txt").read_text()
    return "".join(ln for ln in raw.splitlines(keepends=True) if not ln.startswith("#"))


def _bulletin(year: int, month: int, day: int) -> str:
    """The real 2330z bulletin (5 closed stations + KNYG) re-dated to ``year-month-day``."""
    return "1\n\n" + _real_text().replace("10/05/2026", f"{month:02d}/{day:02d}/{year}") + "\n"


def _month_text(year: int, month: int, days: list[int]) -> str:
    return "".join(_bulletin(year, month, d) for d in days)


def _gz(text: str | bytes) -> bytes:
    return gzip.compress(text.encode() if isinstance(text, str) else text)


def _tar(members: list[tuple[str, bytes]]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        for name, body in members:
            info = tarfile.TarInfo(name)
            info.size = len(body)
            archive.addfile(info, io.BytesIO(body))
    return buffer.getvalue()


def _month_url(ym: str, hhmm: str = "2330") -> str:
    return f"{_ARCHIVES}lmp_lavtxt.{ym}.{hhmm}z.gz"


def _year_url(year: int) -> str:
    return f"{_ARCHIVES}lmp_lavtxt.{year}.tar"


def _serve(files: dict[str, bytes]) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        body = files.get(str(request.url))
        if body is None:
            return httpx.Response(404, content=b"missing")
        return httpx.Response(
            200, content=body, headers={"Last-Modified": "Thu, 01 Oct 2026 14:28:17 GMT"}
        )

    return handler


def _no_network(_request: httpx.Request) -> httpx.Response:
    raise AssertionError("this run must not touch the network")


# ------------------------------------------------------------------------ harness


def _mdl(
    *,
    month_limits: LampArchiveLimits = DEFAULT_LAMP_MONTH_LIMITS,
    year_limits: LampArchiveLimits = DEFAULT_LAMP_YEAR_LIMITS,
) -> Callable[[Callable[[], int]], MdlLampTransport]:
    def factory(clock: Callable[[], int]) -> MdlLampTransport:
        return MdlLampTransport(
            clock=clock, check_proxy_env=False, month_limits=month_limits, year_limits=year_limits
        )

    return factory


def _default_mdl(clock: Callable[[], int]) -> MdlLampTransport:
    return build_mdl_lamp_transport(clock, check_proxy_env=False)


class _Run:
    """One ``main`` invocation with a settable clock, recorded sleeps and the parsed report."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.archive = tmp_path / "archive"
        self.report_path = tmp_path / "report.json"
        self.clock = _Clock()
        self.caps: list[float] = []
        self.monkeypatch = monkeypatch

    def go(
        self,
        *args: str,
        mdl: Callable[[Callable[[], int]], MdlLampTransport] | None = _default_mdl,
        iem: Callable[..., Callable[[str, str, str], str]] | None = None,
        live: bool = True,
    ) -> int:
        if live:
            self.monkeypatch.setenv("BREEZY_LIVE", "1")
        else:
            self.monkeypatch.delenv("BREEZY_LIVE", raising=False)
        kwargs: dict[str, Any] = {}
        if iem is not None:
            kwargs["iem_fetch_factory"] = iem
        return lb.main(
            [
                "--archive-root",
                str(self.archive),
                "--report-json",
                str(self.report_path),
                *args,
            ],
            clock=self.clock,
            sleep=self.clock.sleep,
            mdl_factory=mdl,
            memory_cap=self.caps.append,
            **kwargs,
        )

    @property
    def report(self) -> dict[str, Any]:
        report: dict[str, Any] = json.loads(self.report_path.read_text())
        return report

    def units(self, leg: str) -> list[dict[str, Any]]:
        units: list[dict[str, Any]] = self.report["legs"][leg]["units"]
        return units

    def store(self, source: str = US_LAMP_MDL_SOURCE) -> UsSourceRevisionStore:
        return UsSourceRevisionStore(self.archive, self.clock)

    def stored(self, year: int, month: int, day: int, revision: int = 0) -> bytes:
        request = revision_request(
            US_LAMP_MDL_SOURCE, "ALL", _ns(year, month, day), revision, model=None
        )

        def never(_r: object) -> bytes:
            raise AssertionError("expected a stored revision")

        return ArchiveCache(self.archive, fetch=never, clock=self.clock).get_or_fetch(request)

    def revisions(self, year: int, month: int, day: int) -> tuple[tuple[int, str], ...]:
        return self.store().revisions(US_LAMP_MDL_SOURCE, "ALL", _ns(year, month, day), "lamp-mdl")

    def manifest(self, source: str = US_LAMP_MDL_SOURCE) -> list[dict[str, Any]]:
        path = self.archive / source / lb.MANIFEST_NAME
        if not path.exists():
            return []
        rows: list[dict[str, Any]] = [json.loads(ln) for ln in path.read_text().splitlines()]
        return rows


@pytest.fixture
def run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> _Run:
    return _Run(tmp_path, monkeypatch)


_MONTH = ("--legs", "mdl-monthly", "--cycles", "2330", "--request-budget", "100")


def _month_args(start: str, end: str | None = None) -> tuple[str, ...]:
    return (*_MONTH, "--apply", "--start-month", start, "--end-month", end or start)


# ============================ streamed tar iteration with byte caps ==================


def test_yearly_leg_streams_tar_members_and_stores_only_hh30_runs(
    run: _Run, monkeypatch: pytest.MonkeyPatch
) -> None:
    tar = _tar(
        [
            ("lmp_lavtxt.202501.2330z.gz", _gz(_month_text(2025, 1, [1, 2, 3]))),
            ("lmp_lavtxt.202501.2345z.gz", _gz(b"\xff not even text, must never be parsed")),
            ("README.txt", b"unrecognised"),
        ]
    )
    install_mock_http(monkeypatch, _serve({_year_url(2025): tar}))

    rc = run.go(
        "--apply", "--legs", "mdl-yearly", "--first-year", "2025", "--last-year", "2025",
        "--cycles", "2330", "--request-budget", "5",
    )  # fmt: skip

    unit = run.units("mdl-yearly")[0]
    assert rc == 0  # missing days are reported facts, not a failed run
    assert unit["status"] == "complete"
    assert unit["requests"] == 1
    assert (unit["runs_seen"], unit["appended"]) == (3, 3)
    assert unit["members_skipped"] == {"not_selected_cycle": 1, "unrecognised_name": 1}
    assert len(run.revisions(2025, 1, 1)) == 1 and len(run.revisions(2025, 1, 3)) == 1


def test_yearly_member_size_cap_is_enforced(run: _Run, monkeypatch: pytest.MonkeyPatch) -> None:
    body = _gz(_month_text(2025, 1, [1]))
    tar = _tar([("lmp_lavtxt.202501.2330z.gz", body)])
    install_mock_http(monkeypatch, _serve({_year_url(2025): tar}))
    tiny = LampArchiveLimits(
        max_compressed_bytes=10_000_000,
        max_members=10,
        max_member_bytes=16,
        max_member_decompressed_bytes=10_000_000,
        max_total_decompressed_bytes=10_000_000,
    )

    rc = run.go(
        "--apply", "--legs", "mdl-yearly", "--first-year", "2025", "--last-year", "2025",
        "--cycles", "2330", "--request-budget", "5",
        mdl=_mdl(year_limits=tiny),
    )  # fmt: skip

    assert rc == 1
    assert run.units("mdl-yearly")[0]["status"] == "oversize"
    assert run.revisions(2025, 1, 1) == ()


def test_yearly_decompression_cap_is_enforced(run: _Run, monkeypatch: pytest.MonkeyPatch) -> None:
    tar = _tar([("lmp_lavtxt.202501.2330z.gz", _gz(_month_text(2025, 1, [1, 2, 3])))])
    install_mock_http(monkeypatch, _serve({_year_url(2025): tar}))
    tiny = LampArchiveLimits(
        max_compressed_bytes=10_000_000,
        max_members=10,
        max_member_bytes=10_000_000,
        max_member_decompressed_bytes=1_000,
        max_total_decompressed_bytes=10_000_000,
    )

    run.go(
        "--apply", "--legs", "mdl-yearly", "--first-year", "2025", "--last-year", "2025",
        "--cycles", "2330", "--request-budget", "5",
        mdl=_mdl(year_limits=tiny),
    )  # fmt: skip

    assert run.units("mdl-yearly")[0]["status"] == "oversize"


# ======================= gz line reader caps (monthly concatenated text) =============


def test_monthly_gz_line_length_cap_is_enforced(run: _Run, monkeypatch: pytest.MonkeyPatch) -> None:
    install_mock_http(monkeypatch, _serve({_month_url("202606"): _gz(_month_text(2026, 6, [1]))}))
    tiny = LampArchiveLimits(
        max_compressed_bytes=10_000_000,
        max_members=1,
        max_member_bytes=10_000_000,
        max_member_decompressed_bytes=10_000_000,
        max_total_decompressed_bytes=10_000_000,
        max_line_chars=40,
    )

    rc = run.go(*_month_args("2026-06"), mdl=_mdl(month_limits=tiny))

    assert rc == 1
    assert run.units("mdl-monthly")[0]["status"] == "oversize"
    assert run.revisions(2026, 6, 1) == ()


def test_monthly_gz_compressed_and_decompressed_byte_caps_are_enforced(
    run: _Run, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_mock_http(
        monkeypatch, _serve({_month_url("202606"): _gz(_month_text(2026, 6, [1, 2]))})
    )
    base: dict[str, Any] = {
        "max_compressed_bytes": 10_000_000,
        "max_members": 1,
        "max_member_bytes": 10_000_000,
        "max_member_decompressed_bytes": 10_000_000,
        "max_total_decompressed_bytes": 10_000_000,
    }
    for cap in ("max_compressed_bytes", "max_member_decompressed_bytes"):
        limits = LampArchiveLimits(**{**base, cap: 500})
        run.go(*_month_args("2026-06"), mdl=_mdl(month_limits=limits))
        assert run.units("mdl-monthly")[0]["status"] == "oversize", cap
    assert run.revisions(2026, 6, 1) == ()


def test_monthly_truncated_gz_is_an_error_not_data(
    run: _Run, monkeypatch: pytest.MonkeyPatch
) -> None:
    whole = _gz(_month_text(2026, 6, [1, 2]))
    install_mock_http(monkeypatch, _serve({_month_url("202606"): whole[: len(whole) // 2]}))

    rc = run.go(*_month_args("2026-06"))

    assert rc == 1
    assert run.units("mdl-monthly")[0]["status"] == "error"


# ================================ missing is MISSING =================================


def test_missing_days_are_counted_missing_and_never_imputed(
    run: _Run, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_mock_http(
        monkeypatch, _serve({_month_url("202606"): _gz(_month_text(2026, 6, [1, 2, 3]))})
    )

    rc = run.go(*_month_args("2026-06"))

    unit = run.units("mdl-monthly")[0]
    assert rc == 0
    assert unit["missing_run_count"] == calendar.monthrange(2026, 6)[1] - 3
    assert unit["missing_runs"] == {"202606.2330": [f"2026-06-{d:02d}" for d in range(4, 31)]}
    assert [len(run.revisions(2026, 6, d)) for d in (1, 2, 3, 4, 15, 30)] == [1, 1, 1, 0, 0, 0]
    assert len(run.manifest()) == 3  # nothing was written for a missing run


def test_unpublished_monthly_file_is_missing_not_an_error_and_does_not_stop_the_run(
    run: _Run, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_mock_http(monkeypatch, _serve({_month_url("202606"): _gz(_month_text(2026, 6, [1]))}))

    rc = run.go(*_month_args("2026-05", "2026-06"))

    statuses = {u["unit"]: u["status"] for u in run.units("mdl-monthly")}
    assert statuses == {"202605.2330": "not_published", "202606.2330": "complete"}
    assert rc == 1
    assert len(run.revisions(2026, 6, 1)) == 1


# ====================== parse / header / station handling ============================


def test_only_the_five_closed_stations_are_extracted(
    run: _Run, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert "KNYG" in _bulletin(2026, 6, 1)  # the fixture carries a sixth, non-closed block
    install_mock_http(monkeypatch, _serve({_month_url("202606"): _gz(_month_text(2026, 6, [1]))}))

    run.go(*_month_args("2026-06"))

    payload = run.stored(2026, 6, 1).decode()
    headers = [ln.split()[0] for ln in payload.splitlines() if "GFS LAMP GUIDANCE" in ln]
    assert sorted(headers) == sorted(_CLOSED)
    assert "KNYG" not in payload and "\n1\n" not in payload


def test_a_run_with_a_bad_row_is_refused_whole_and_counted_never_stored(
    run: _Run, monkeypatch: pytest.MonkeyPatch
) -> None:
    good, bad = (
        _bulletin(2026, 6, 1),
        _bulletin(2026, 6, 2).replace(" TMP  63 61", " TMP  63 6x", 1),
    )
    install_mock_http(monkeypatch, _serve({_month_url("202606"): _gz(good + bad)}))

    run.go(*_month_args("2026-06"))

    unit = run.units("mdl-monthly")[0]
    assert unit["refused"] == {"bad_token": 1}
    assert len(run.revisions(2026, 6, 1)) == 1
    assert run.revisions(2026, 6, 2) == ()


def test_blocks_whose_header_disagrees_with_the_file_name_are_dropped_and_counted(
    run: _Run, monkeypatch: pytest.MonkeyPatch
) -> None:
    stray = _bulletin(2026, 5, 31)  # a May run inside the June file
    install_mock_http(
        monkeypatch, _serve({_month_url("202606"): _gz(_bulletin(2026, 6, 1) + stray)})
    )

    run.go(*_month_args("2026-06"))

    unit = run.units("mdl-monthly")[0]
    assert unit["dropped"]["header_mismatch"] == 5
    assert unit["runs_seen"] == 1
    assert run.revisions(2026, 5, 31) == ()


def test_a_station_missing_from_a_run_is_counted_and_the_run_is_still_stored() -> None:
    text = _bulletin(2026, 6, 1)
    start = text.index(" KMIA ")
    end = text.index(" KMDW ")
    tally: dict[str, int] = {}
    runs = list(
        lb.iter_lamp_runs(
            text[:start].splitlines(keepends=True) + text[end:].splitlines(keepends=True),
            expect_year_month=(2026, 6),
            expect_hhmm="2330",
            tally=tally,
        )
    )

    assert len(runs) == 1
    assert "KMIA" not in runs[0].blocks and len(runs[0].blocks) == 4
    assert lb.missing_stations(runs[0], _CLOSED) == ("KMIA",)


def test_a_run_that_reappears_non_contiguously_is_dropped_not_revised() -> None:
    tally: dict[str, int] = {}
    lines = (_bulletin(2026, 6, 1) + _bulletin(2026, 6, 2) + _bulletin(2026, 6, 1)).splitlines(
        keepends=True
    )

    runs = list(
        lb.iter_lamp_runs(lines, expect_year_month=(2026, 6), expect_hhmm="2330", tally=tally)
    )

    assert [r.run_at.day for r in runs] == [1, 2]
    assert tally["run_reappeared"] == 1  # item 6: once per reappearance, not once per block


# ===================================== egress / hosts ================================


def test_every_request_goes_to_the_one_mdl_host_and_nothing_widens(
    run: _Run, monkeypatch: pytest.MonkeyPatch
) -> None:
    mock = install_mock_http(
        monkeypatch, _serve({_month_url("202606"): _gz(_month_text(2026, 6, [1]))})
    )

    run.go(*_month_args("2026-06"))

    assert {r.url.host for r in mock.requests} == {LAMP_MDL_HOST} == {"lamp.mdl.nws.noaa.gov"}
    assert LAMP_ALLOWED_HOSTS == frozenset({"nomads.ncep.noaa.gov", "lamp.mdl.nws.noaa.gov"})
    assert all(r.method == "GET" for r in mock.requests)


def test_the_script_names_no_url_or_host_and_imports_no_fit_score_or_order_code() -> None:
    tree = ast.parse(_SCRIPT.read_text())
    docstring = ast.get_docstring(tree, clean=False)
    literals = [
        n.value
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value != docstring
    ]
    assert not [s for s in literals if "://" in s or ".gov" in s or "iastate" in s]
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    banned = ("calibration", "crps", "blend", "runtime", "adapters", "exec", "nautilus")
    assert not [m for m in imported if any(b in m for b in banned)], imported


# ================================== idempotency / revisions ==========================


def test_a_rerun_is_unchanged_and_never_a_duplicate_revision(
    run: _Run, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_mock_http(
        monkeypatch, _serve({_month_url("202606"): _gz(_month_text(2026, 6, [1, 2]))})
    )

    run.go(*_month_args("2026-06"))
    first = run.units("mdl-monthly")[0]
    manifest_before = run.manifest()
    run.go(*_month_args("2026-06"))
    second = run.units("mdl-monthly")[0]

    assert (first["appended"], first["unchanged"]) == (2, 0)
    assert (second["appended"], second["unchanged"]) == (0, 2)
    assert len(run.revisions(2026, 6, 1)) == 1
    assert run.manifest() == manifest_before


def test_a_republished_month_with_changed_content_appends_the_next_revision(
    run: _Run, monkeypatch: pytest.MonkeyPatch
) -> None:
    files = {_month_url("202606"): _gz(_month_text(2026, 6, [1]))}
    install_mock_http(monkeypatch, _serve(files))
    run.go(*_month_args("2026-06"))
    files[_month_url("202606")] = _gz(
        _bulletin(2026, 6, 1).replace(" TMP  63 61", " TMP  63 62", 1)
    )

    run.go(*_month_args("2026-06"))

    assert [n for n, _ in run.revisions(2026, 6, 1)] == [0, 1]
    assert run.stored(2026, 6, 1, 0) != run.stored(2026, 6, 1, 1)


# ================================ holdout tag + availability =========================


def test_holdout_start_matches_the_calibration_split() -> None:
    assert lb.HOLDOUT_START == DEFAULT_SPLITS.holdout_start == dt.date(2026, 7, 1)


def test_archives_from_the_split_date_are_stored_but_tagged_sealed(
    run: _Run, monkeypatch: pytest.MonkeyPatch
) -> None:
    files = {
        _month_url("202606"): _gz(_month_text(2026, 6, [1, 30])),
        _month_url("202607"): _gz(_month_text(2026, 7, [1])),
    }
    install_mock_http(monkeypatch, _serve(files))

    run.go(*_month_args("2026-06", "2026-07"))

    rows = {
        dt.datetime.fromtimestamp(r["run_ts_ns"] / _NS, tz=dt.UTC).date(): r for r in run.manifest()
    }
    assert len(run.revisions(2026, 7, 1)) == 1  # stored for the forward feed
    assert rows[dt.date(2026, 7, 1)]["holdout_sealed"] is True
    assert rows[dt.date(2026, 6, 30)]["holdout_sealed"] is False
    assert rows[dt.date(2026, 6, 30)]["spans_holdout_days"] is True  # its +38 h reaches July
    assert rows[dt.date(2026, 6, 1)]["spans_holdout_days"] is False


def test_availability_is_archive_basis_with_the_conservative_lag(
    run: _Run, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_mock_http(monkeypatch, _serve({_month_url("202606"): _gz(_month_text(2026, 6, [1]))}))

    run.go(*_month_args("2026-06"))

    (row,) = run.manifest()
    run_ns = _ns(2026, 6, 1)
    assert row["run_ts_ns"] == run_ns
    assert row["available_at_ns"] == run_ns + census.LAMP_CONSERVATIVE_LAG_S * _NS
    assert row["available_at_ns"] >= run_ns + 10 * 60 * _NS  # never inside the A0-measured 6-10 min
    assert row["availability_basis"] == "nominal_plus_conservative_lag@archive"
    assert row["source"] == US_LAMP_MDL_SOURCE and row["station"] == "ALL"
    assert row["leg"] == "mdl-monthly" and len(row["sha256"]) == 64


# ====================== budget / pacing / launch window / stop-all ===================


def test_the_request_budget_is_a_hard_stop_for_every_remaining_unit(
    run: _Run, monkeypatch: pytest.MonkeyPatch
) -> None:
    files = {_month_url(f"2026{m:02d}"): _gz(_month_text(2026, m, [1])) for m in (3, 4, 5)}
    mock = install_mock_http(monkeypatch, _serve(files))

    rc = run.go(
        "--apply", "--legs", "mdl-monthly", "--cycles", "2330", "--request-budget", "2",
        "--start-month", "2026-03", "--end-month", "2026-05",
    )  # fmt: skip

    assert rc == 1
    assert len(mock.requests) == 2
    units = run.units("mdl-monthly")
    assert [u["status"] for u in units] == ["complete", "complete", "budget_exhausted"]
    assert run.report["stopped"]["reason"] == "budget_exhausted"


def test_requests_are_paced_at_the_documented_interval(
    run: _Run, monkeypatch: pytest.MonkeyPatch
) -> None:
    files = {_month_url(f"2026{m:02d}"): _gz(_month_text(2026, m, [1])) for m in (3, 4, 5)}
    install_mock_http(monkeypatch, _serve(files))

    run.go(*_month_args("2026-03", "2026-05"))

    assert lb.MDL_MIN_INTERVAL_S >= 5
    assert run.clock.sleeps == [lb.MDL_MIN_INTERVAL_S] * 2


def test_no_request_starts_that_could_meet_the_launch_window(
    run: _Run, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_mock_http(monkeypatch, _no_network)
    run.clock.now_ns = int(dt.datetime(2026, 10, 7, 16, 10, tzinfo=dt.UTC).timestamp()) * _NS

    rc = run.go(*_month_args("2026-06", "2026-07"))  # a month stream may run 30 min: meets 16:30

    assert rc == 1
    units = run.units("mdl-monthly")
    assert units[0]["status"] == "paused_launch_window" and units[0]["requests"] == 0
    assert run.report["stopped"]["reason"] == "paused_launch_window"
    assert run.report["stopped"]["skipped_units"] == ["202607.2330"]


def test_a_two_hour_tar_is_refused_in_the_afternoon_and_allowed_after_the_window(
    run: _Run, monkeypatch: pytest.MonkeyPatch
) -> None:
    tar = _tar([("lmp_lavtxt.202501.2330z.gz", _gz(_month_text(2025, 1, [1])))])
    mock = install_mock_http(monkeypatch, _serve({_year_url(2025): tar}))
    args = (
        "--apply", "--legs", "mdl-yearly", "--first-year", "2025", "--last-year", "2025",
        "--cycles", "2330", "--request-budget", "5",
    )  # fmt: skip
    run.clock.now_ns = int(dt.datetime(2026, 10, 7, 15, 0, tzinfo=dt.UTC).timestamp()) * _NS

    run.go(*args)
    assert run.units("mdl-yearly")[0]["status"] == "paused_launch_window"
    assert mock.requests == []

    run.clock.now_ns = int(dt.datetime(2026, 10, 7, 17, 10, tzinfo=dt.UTC).timestamp()) * _NS
    run.go(*args)
    assert run.units("mdl-yearly")[0]["status"] == "complete"


@pytest.mark.parametrize(("status_code", "expected"), [(429, "throttled"), (403, "forbidden")])
def test_a_throttle_or_forbidden_stops_every_remaining_unit(
    run: _Run, monkeypatch: pytest.MonkeyPatch, status_code: int, expected: str
) -> None:
    mock = install_mock_http(monkeypatch, lambda _r: httpx.Response(status_code, content=b"no"))

    rc = run.go(
        "--apply", "--legs", "mdl-monthly", "--cycles", "2330", "--request-budget", "50",
        "--start-month", "2026-03", "--end-month", "2026-05",
    )  # fmt: skip

    units = run.units("mdl-monthly")
    assert rc == 1
    assert units[0]["status"] == expected and len(units) == 1
    assert run.report["stopped"]["skipped_units"] == ["202604.2330", "202605.2330"]
    if status_code == 429:
        assert [s for s in run.clock.sleeps if s >= 30] == list(lb.THROTTLE_BACKOFF_S)
    assert len(mock.requests) >= 1


# ============================== report / safety / dry-run ============================


def test_the_report_is_always_written_even_when_the_run_aborts(run: _Run) -> None:
    def boom(_clock: Callable[[], int]) -> MdlLampTransport:
        raise RuntimeError("transport construction exploded")

    rc = run.go(*_month_args("2026-06"), mdl=boom)

    assert rc == 1
    report = run.report
    assert report["mode"] == "apply"
    assert "RuntimeError" in report["error"]


def test_dry_run_plans_without_network_or_writes(
    run: _Run, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_mock_http(monkeypatch, _no_network)

    rc = run.go(
        "--dry-run", "--request-budget", "100", "--first-year", "2021", "--last-year", "2025",
        "--start-month", "2026-01", "--end-month", "2026-09",
        live=False,
    )  # fmt: skip

    assert rc == 0
    assert not run.archive.exists()
    assert run.caps == []
    plan = run.report["plan"]
    assert run.report["mode"] == "dry_run"
    assert plan["mdl-yearly"]["years"] == [2021, 2022, 2023, 2024, 2025]
    assert plan["mdl-yearly"]["estimated_requests"] == 5
    assert plan["mdl-monthly"]["estimated_requests"] == 9 * 24
    assert plan["iem-lav"]["estimated_requests"] == 9 * 5
    assert plan["estimated_requests"] == 5 + 216 + 45
    assert plan["fits_budget"] is False
    assert plan["cycles"] == [f"{h:02d}30" for h in range(24)]
    assert plan["mdl_min_interval_s"] == lb.MDL_MIN_INTERVAL_S and plan["iem_min_interval_s"] >= 4


def test_an_archive_root_under_a_holdout_directory_or_the_live_root_is_refused(
    run: _Run, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_mock_http(monkeypatch, _no_network)
    sealed = tmp_path / "holdout" / "archive"
    live = Path.home() / ".local" / "share" / "breezy" / "not_the_archive_dir"

    for root in (sealed, live):
        rc = lb.main(
            ["--dry-run", "--archive-root", str(root)], clock=run.clock, sleep=run.clock.sleep
        )
        assert rc == 2, root
    assert not sealed.exists()


def test_apply_needs_the_live_env_and_a_budget_and_exactly_one_mode(
    run: _Run, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_mock_http(monkeypatch, _no_network)
    assert run.go(*_month_args("2026-06"), live=False) == 2
    assert run.go("--apply", "--legs", "mdl-monthly") == 2  # no --request-budget
    assert run.go("--apply", "--dry-run", "--request-budget", "5") == 2
    assert run.go("--request-budget", "5") == 2  # neither mode
    assert run.go("--apply", "--request-budget", "5", "--stations", "KJFK") == 2
    assert run.go("--apply", "--request-budget", "5", "--first-year", "2020") == 2
    assert run.go("--apply", "--request-budget", "5", "--cycles", "0045") == 2
    assert not run.archive.exists()


def test_the_memory_cap_is_applied_on_apply_only_and_wired_to_the_real_cap() -> None:
    from breezy.analysis.memory_cap import apply_address_space_cap

    assert lb.DEFAULT_MEMORY_CAP_GIB > 0
    assert lb.main.__kwdefaults__["memory_cap"] is lb.apply_address_space_cap  # type: ignore[index]
    assert lb.apply_address_space_cap is apply_address_space_cap


def test_apply_calls_the_memory_cap_with_the_requested_gib(
    run: _Run, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_mock_http(monkeypatch, _serve({}))

    run.go(*_month_args("2026-06"), "--memory-cap-gib", "2.5")

    assert run.caps == [2.5]


# ===================================== IEM LAV gap-fill ==============================

_LAV_CSV = (
    "runtime,ftime,model,tmp,station\n"
    "2026-03-01 00:00:00,2026-03-01 01:00:00,LAV,40,KNYC\n"
    "2026-03-01 00:00:00,2026-03-01 02:00:00,LAV,41,KNYC\n"
    "2026-03-01 01:00:00,2026-03-01 02:00:00,LAV,42,KNYC\n"
)


def _iem_stub(
    text: str = _LAV_CSV,
) -> tuple[Callable[..., Callable[[str, str, str], str]], list[Any]]:
    calls: list[Any] = []

    def factory(**_kw: Any) -> Callable[[str, str, str], str]:
        def fetch(station: str, sts: str, ets: str) -> str:
            calls.append((station, sts, ets))
            return text

        return fetch

    return factory, calls


def test_iem_lav_splits_runs_stores_them_under_the_lav_key_and_flags_the_basis(
    run: _Run,
) -> None:
    factory, calls = _iem_stub()

    rc = run.go(
        "--apply", "--legs", "iem-lav", "--stations", "KNYC", "--request-budget", "5",
        "--start-month", "2026-03", "--end-month", "2026-03",
        iem=factory,
    )  # fmt: skip

    assert rc == 0
    assert calls == [("KNYC", "2026-03-01T00:00Z", "2026-04-01T00:00Z")]
    unit = run.units("iem-lav")[0]
    assert (unit["runs_seen"], unit["appended"]) == (2, 2)
    revs = run.store().revisions(US_LAV_IEM_SOURCE, "KNYC", _ns(2026, 3, 1, 0, 0), "lav-iem")
    assert [n for n, _ in revs] == [0]
    request = lav_iem_request("KNYC", _ns(2026, 3, 1, 0, 0))
    stored = ArchiveCache(
        run.archive, fetch=lambda _r: (_ for _ in ()).throw(AssertionError), clock=run.clock
    ).get_or_fetch(request)
    assert stored.decode().count("\n") == 3 and stored.decode().startswith("runtime,")
    rows = run.manifest(US_LAV_IEM_SOURCE)
    assert {r["basis_flag"] for r in rows} == {"iem_lav_gap_fill_run_label_inferred"}
    assert rows[0]["availability_basis"] == "nominal_plus_conservative_lag@iem-lav"
    assert rows[0]["available_at_ns"] == _ns(2026, 3, 1, 0, 0) + 90 * 60 * _NS
    assert rows[0]["leg"] == "iem-lav" and rows[0]["holdout_sealed"] is False


def test_iem_lav_rerun_is_idempotent_and_foreign_station_rows_are_dropped(run: _Run) -> None:
    factory, _ = _iem_stub(_LAV_CSV + "2026-03-01 02:00:00,2026-03-01 03:00:00,LAV,9,KLAX\n")
    args = (
        "--apply", "--legs", "iem-lav", "--stations", "KNYC", "--request-budget", "5",
        "--start-month", "2026-03", "--end-month", "2026-03",
    )  # fmt: skip

    run.go(*args, iem=factory)
    run.go(*args, iem=factory)

    unit = run.units("iem-lav")[0]
    assert (unit["appended"], unit["unchanged"]) == (0, 2)
    assert unit["dropped"] == {"wrong_station": 1}
    assert len(run.manifest(US_LAV_IEM_SOURCE)) == 2


def test_iem_lav_leg_uses_the_paced_budgeted_iem_transport_and_only_the_iem_host(
    run: _Run, monkeypatch: pytest.MonkeyPatch
) -> None:
    mock = install_mock_http(monkeypatch, lambda _r: httpx.Response(200, content=_LAV_CSV.encode()))

    fetch = lb.make_lav_fetch(
        budget=lb.RequestBudget(limit=2),
        user_agent="breezy-test (alias)",
        clock_ns=run.clock,
        sleeper=run.clock.asleep,
        check_proxy_env=False,
    )
    fetch("KNYC", "2026-03-01T00:00Z", "2026-04-01T00:00Z")
    fetch("KNYC", "2026-04-01T00:00Z", "2026-05-01T00:00Z")

    assert {r.url.host for r in mock.requests} == {"mesonet.agron.iastate.edu"}
    assert run.clock.sleeps == [4.0]
    with pytest.raises(lb.RequestBudgetExceededError):
        fetch("KNYC", "2026-05-01T00:00Z", "2026-06-01T00:00Z")


def test_iem_lav_payload_without_a_runtime_column_is_refused_not_stored(run: _Run) -> None:
    factory, _ = _iem_stub("station,model,tmp\nKNYC,LAV,40\n")

    run.go(
        "--apply", "--legs", "iem-lav", "--stations", "KNYC", "--request-budget", "5",
        "--start-month", "2026-03", "--end-month", "2026-03",
        iem=factory,
    )  # fmt: skip

    unit = run.units("iem-lav")[0]
    assert unit["status"] == "error" and "runtime" in unit["error"]
    assert run.manifest(US_LAV_IEM_SOURCE) == []


def test_iem_lav_months_from_the_split_date_are_tagged_sealed(run: _Run) -> None:
    csv_text = _LAV_CSV.replace("2026-03", "2026-07")
    factory, _ = _iem_stub(csv_text)

    run.go(
        "--apply", "--legs", "iem-lav", "--stations", "KNYC", "--request-budget", "5",
        "--start-month", "2026-07", "--end-month", "2026-07",
        iem=factory,
    )  # fmt: skip

    assert {r["holdout_sealed"] for r in run.manifest(US_LAV_IEM_SOURCE)} == {True}


# ===================== review fixes (2026-10-06): items 1-7 ==========================


def _yearly_args(cycles: str = "2330") -> tuple[str, ...]:
    return (
        "--apply", "--legs", "mdl-yearly", "--first-year", "2025", "--last-year", "2025",
        "--cycles", cycles, "--request-budget", "5",
    )  # fmt: skip


def test_item1_a_refused_run_makes_the_unit_degraded_and_its_day_missing(
    run: _Run, monkeypatch: pytest.MonkeyPatch
) -> None:
    good, bad = (
        _bulletin(2026, 6, 1),
        _bulletin(2026, 6, 2).replace(" TMP  63 61", " TMP  63 6x", 1),
    )
    install_mock_http(monkeypatch, _serve({_month_url("202606"): _gz(good + bad)}))

    rc = run.go(*_month_args("2026-06"))

    unit = run.units("mdl-monthly")[0]
    assert unit["refused"] == {"bad_token": 1}
    assert unit["status"] == "degraded" and rc == 1
    assert "2026-06-02" in unit["missing_runs"]["202606.2330"]
    assert "2026-06-01" not in unit["missing_runs"]["202606.2330"]


def test_item1_a_store_error_makes_the_unit_degraded_and_its_day_missing(
    run: _Run, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_mock_http(monkeypatch, _serve({_month_url("202606"): _gz(_month_text(2026, 6, [1]))}))

    def broken(self: object, **_kwargs: object) -> None:
        raise RevisionStoreError("integrity")

    monkeypatch.setattr(UsSourceRevisionStore, "append_if_new", broken)

    rc = run.go(*_month_args("2026-06"))

    unit = run.units("mdl-monthly")[0]
    assert unit["store_errors"] == {"RevisionStoreError": 1}
    assert unit["status"] == "degraded" and rc == 1
    assert "2026-06-01" in unit["missing_runs"]["202606.2330"]


def test_item2_absent_tar_members_are_reported_missing_and_completion_is_reported(
    run: _Run, monkeypatch: pytest.MonkeyPatch
) -> None:
    tar = _tar([("lmp_lavtxt.202501.2330z.gz", _gz(_month_text(2025, 1, [1])))])
    install_mock_http(monkeypatch, _serve({_year_url(2025): tar}))

    rc = run.go(*_yearly_args())

    unit = run.units("mdl-yearly")[0]
    assert rc == 0 and unit["status"] == "complete"
    assert unit["members_missing_count"] == 11
    assert unit["members_missing"] == [f"2025{m:02d}.2330" for m in range(2, 13)]
    assert unit["tar_stream_complete"] is True
    assert len(unit["tar_sha256"]) == 64


def test_item2_a_skipped_member_leaves_the_tar_stream_unvalidated(
    run: _Run, monkeypatch: pytest.MonkeyPatch
) -> None:
    tar = _tar(
        [
            ("lmp_lavtxt.202501.2330z.gz", _gz(_month_text(2025, 1, [1]))),
            ("lmp_lavtxt.202501.2345z.gz", _gz(b"skipped, never validated")),
        ]
    )
    install_mock_http(monkeypatch, _serve({_year_url(2025): tar}))

    run.go(*_yearly_args())

    unit = run.units("mdl-yearly")[0]
    assert unit["members_skipped"] == {"not_selected_cycle": 1}
    assert unit["tar_stream_complete"] is False and unit["tar_sha256"] is None


def test_item3_a_torn_trailing_manifest_line_is_skipped_counted_and_repaired(
    tmp_path: Path,
) -> None:
    path = tmp_path / US_LAMP_MDL_SOURCE / lb.MANIFEST_NAME
    path.parent.mkdir(parents=True)
    good = json.dumps({"station": "ALL", "run_ts_ns": 1, "sha256": "a" * 64})
    path.write_text(good + "\n" + '{"station": "ALL", "run_ts')
    manifest = lb.Manifest(tmp_path, US_LAMP_MDL_SOURCE)

    wrote = manifest.record({"station": "ALL", "run_ts_ns": 2, "sha256": "b" * 64})

    assert wrote is True and manifest.torn_lines == 1
    lines = path.read_text().splitlines()
    assert [json.loads(ln)["run_ts_ns"] for ln in lines] == [1, 2]
    assert (
        lb.Manifest(tmp_path, US_LAMP_MDL_SOURCE).record(
            {"station": "ALL", "run_ts_ns": 2, "sha256": "b" * 64}
        )
        is False
    )


def test_item3_an_invalid_non_trailing_manifest_line_still_errors(tmp_path: Path) -> None:
    path = tmp_path / US_LAMP_MDL_SOURCE / lb.MANIFEST_NAME
    path.parent.mkdir(parents=True)
    good = json.dumps({"station": "ALL", "run_ts_ns": 1, "sha256": "a" * 64})
    path.write_text(good + "\n{not json\n" + good + "\n")

    with pytest.raises(ValueError, match="Expecting"):
        lb.Manifest(tmp_path, US_LAMP_MDL_SOURCE).record(
            {"station": "ALL", "run_ts_ns": 9, "sha256": "c" * 64}
        )


def test_item3_the_torn_line_count_is_in_the_report(
    run: _Run, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = run.archive / US_LAMP_MDL_SOURCE / lb.MANIFEST_NAME
    path.parent.mkdir(parents=True)
    path.write_text('{"station": "ALL", "run')
    install_mock_http(monkeypatch, _serve({_month_url("202606"): _gz(_month_text(2026, 6, [1]))}))

    run.go(*_month_args("2026-06"))

    assert run.report["manifest_torn_lines"] == 1
    assert len(run.manifest()) == 1


def _one_block_run(extra_lines: int = 0, extra_bytes: int = 0) -> list[str]:
    head = "KNYC   GFS LAMP GUIDANCE   06/01/2026  2330 UTC\n"
    body = [" HR   00 01\n"] + [" TMP  63 61\n"] * extra_lines
    if extra_bytes:
        body.append(" X " + "9" * extra_bytes + "\n")
    return [head, *body, "\n"]


def test_item4_an_over_cap_block_is_dropped_and_tallied_never_stored() -> None:
    cases = {"lines": _one_block_run(extra_lines=400), "bytes": _one_block_run(extra_bytes=70_000)}
    for label, lines in cases.items():
        tally: dict[str, int] = {}
        runs = list(
            lb.iter_lamp_runs(lines, expect_year_month=(2026, 6), expect_hhmm="2330", tally=tally)
        )
        assert runs == [], label
        assert tally == {"oversize_blocks": 1}, label


def test_item4_a_block_under_both_caps_is_kept() -> None:
    tally: dict[str, int] = {}
    runs = list(
        lb.iter_lamp_runs(
            _one_block_run(extra_lines=150),
            expect_year_month=(2026, 6),
            expect_hhmm="2330",
            tally=tally,
        )
    )
    assert len(runs) == 1 and "oversize_blocks" not in tally


def test_item4_the_real_bulletin_blocks_fit_the_caps() -> None:
    tally: dict[str, int] = {}
    lines = _bulletin(2026, 6, 1).splitlines(keepends=True)
    runs = list(
        lb.iter_lamp_runs(lines, expect_year_month=(2026, 6), expect_hhmm="2330", tally=tally)
    )
    assert len(runs) == 1 and len(runs[0].blocks) == 5 and "oversize_blocks" not in tally


def test_item7_a_429_retry_is_charged_to_the_request_budget(
    run: _Run, monkeypatch: pytest.MonkeyPatch
) -> None:
    body = _gz(_month_text(2026, 6, [1]))
    seen: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(1)
        if len(seen) == 1:
            return httpx.Response(429, headers={"Retry-After": "1"}, content=b"slow")
        return httpx.Response(200, content=body)

    def factory(clock: Callable[[], int]) -> MdlLampTransport:
        return MdlLampTransport(clock=clock, check_proxy_env=False, sleep=run.clock.sleep)

    install_mock_http(monkeypatch, handler)
    args = (*_MONTH[:-1], "1", "--apply", "--start-month", "2026-06", "--end-month", "2026-06")

    rc = run.go(*args, mdl=factory)

    assert run.units("mdl-monthly")[0]["status"] == "budget_exhausted" and rc == 1
    assert len(seen) == 1  # the retry never reached the host

    seen.clear()
    run.go(
        *(*_MONTH[:-1], "2", "--apply", "--start-month", "2026-06", "--end-month", "2026-06"),
        mdl=factory,
    )
    assert run.units("mdl-monthly")[0]["status"] == "complete" and len(seen) == 2


def test_item7_window_worst_case_includes_two_max_retry_after_waits() -> None:
    from breezy.ingest import mdl_lamp_transport as transport

    extra = 2 * int(transport._MAX_RETRY_AFTER_SECONDS)
    assert lb.RETRY_AFTER_WORST_CASE_S == extra
    assert (
        lb.YEAR_WORST_CASE_S
        == int(DEFAULT_LAMP_YEAR_LIMITS.max_wall_seconds) + lb.REQUEST_WORST_CASE_S + extra
    )
    assert (
        lb.MONTH_WORST_CASE_S
        == int(DEFAULT_LAMP_MONTH_LIMITS.max_wall_seconds) + lb.REQUEST_WORST_CASE_S + extra
    )


# ============ one-digit month header (real MDL archive, 2026-01) =====================

_ARCHIVE_REAL = "lamp_archive_real_202601_1230z.txt"


def _archive_real_text() -> str:
    return (_FIXTURES / _ARCHIVE_REAL).read_text()


def test_live_parser_accepts_single_digit_month_header() -> None:
    from breezy.ingest.lamp_parse import parse_lamp_blocks

    text = _archive_real_text()
    assert " KNYC   GFS LAMP GUIDANCE   1/01/2026  1230 UTC" in text

    blocks = parse_lamp_blocks(text.splitlines())

    assert sorted(b.station for b in blocks) == sorted(_CLOSED)
    assert {b.issued_at for b in blocks} == {dt.datetime(2026, 1, 1, 12, 30, tzinfo=dt.UTC)}


def test_live_parser_still_parses_the_two_digit_month_fixture_identically() -> None:
    from breezy.ingest.lamp_parse import parse_lamp_blocks

    live = parse_lamp_blocks(_real_text().splitlines())
    assert {b.issued_at for b in live} == {dt.datetime(2026, 10, 5, 23, 30, tzinfo=dt.UTC)}
    assert {"KNYC", "KLAX", "KMDW", "KMIA", "KSFO"} <= {b.station for b in live}

    one_digit = _real_text().replace("10/05/2026", " 1/05/2026")  # same width, month 1 not 10
    padded = _real_text().replace("10/05/2026", "01/05/2026")
    assert parse_lamp_blocks(one_digit.replace(" 1/05/2026", "1/05/2026").splitlines()) == (
        parse_lamp_blocks(padded.splitlines())
    )


def test_one_digit_month_header_still_refuses_an_impossible_date() -> None:
    from breezy.ingest.lamp_parse import LampParseError, parse_lamp_blocks

    bad = _archive_real_text().replace("1/01/2026", "1/32/2026")
    with pytest.raises(LampParseError) as err:
        parse_lamp_blocks(bad.splitlines())
    assert err.value.reason == "bad_header_time"


def test_archive_runs_accept_single_digit_month() -> None:
    tally: dict[str, int] = {}

    runs = list(
        lb.iter_lamp_runs(
            _archive_real_text().splitlines(keepends=True),
            expect_year_month=(2026, 1),
            expect_hhmm="1230",
            tally=tally,
        )
    )

    assert tally == {}
    assert [r.run_at for r in runs] == [dt.datetime(2026, 1, 1, 12, 30, tzinfo=dt.UTC)]
    assert sorted(runs[0].blocks) == sorted(_CLOSED)


def test_all_blocks_dropped_unit_is_degraded_not_complete(
    run: _Run, monkeypatch: pytest.MonkeyPatch
) -> None:
    broken = _month_text(2026, 6, [1, 2]).replace("06/01/2026", "13/45/2026")
    broken = broken.replace("06/02/2026", "13/45/2026")
    install_mock_http(monkeypatch, _serve({_month_url("202606"): _gz(broken)}))

    rc = run.go(*_month_args("2026-06"))

    unit = run.units("mdl-monthly")[0]
    assert unit["appended"] == 0 and unit["unchanged"] == 0
    assert unit["dropped"]["bad_header"] > 0
    assert unit["status"] == "degraded"
    assert rc == 1


def test_an_expected_skip_drop_alone_keeps_the_unit_complete(run: _Run) -> None:
    rep = lb.UnitReport(unit="u", leg="iem-lav")
    rep.appended = 3
    rep.dropped = {"wrong_station": 7}
    assert lb._settled(rep).status == "complete"


def test_any_unexpected_drop_degrades_even_when_runs_were_stored() -> None:
    rep = lb.UnitReport(unit="u", leg="mdl-monthly")
    rep.appended = 3
    rep.dropped = {"bad_header": 1}
    assert lb._settled(rep).status == "degraded"


# ============ --download-deadline-s: configurable yearly tar deadline =================

_YEAR_ARGS = (
    "--legs", "mdl-yearly", "--first-year", "2025", "--last-year", "2025",
    "--cycles", "2330", "--request-budget", "5",
)  # fmt: skip


@pytest.mark.parametrize("bad", ["599", "21601", "0", "-5", "nan"])
def test_download_deadline_outside_600_to_21600_is_refused(run: _Run, bad: str) -> None:
    rc = run.go("--dry-run", *_YEAR_ARGS, "--download-deadline-s", bad)

    assert rc == 2 and not run.report_path.exists()


@pytest.mark.parametrize("ok", ["600", "7200", "21600"])
def test_download_deadline_bounds_are_inclusive(run: _Run, ok: str) -> None:
    assert run.go("--dry-run", *_YEAR_ARGS, "--download-deadline-s", ok) == 0


def test_plan_worst_case_tracks_the_configured_deadline(run: _Run) -> None:
    run.go("--dry-run", *_YEAR_ARGS, "--download-deadline-s", "21600")

    expected = 21600 + lb.REQUEST_WORST_CASE_S + lb.RETRY_AFTER_WORST_CASE_S
    assert run.report["plan"]["mdl-yearly"]["worst_case_s_per_request"] == expected
    assert run.report["inputs"]["download_deadline_s"] == 21600


def test_default_deadline_is_unchanged(run: _Run) -> None:
    run.go("--dry-run", *_YEAR_ARGS)

    assert run.report["plan"]["mdl-yearly"]["worst_case_s_per_request"] == lb.YEAR_WORST_CASE_S
    assert lb.DEFAULT_DOWNLOAD_DEADLINE_S == 7200


def test_deadline_reaches_the_yearly_transport_limits(
    run: _Run, monkeypatch: pytest.MonkeyPatch
) -> None:
    tar = _tar([("lmp_lavtxt.202501.2330z.gz", _gz(_month_text(2025, 1, [1])))])
    install_mock_http(monkeypatch, _serve({_year_url(2025): tar}))
    captured: list[float] = []

    class _Spy(MdlLampTransport):
        def __init__(self, **kw: Any) -> None:
            captured.append(kw["year_limits"].max_wall_seconds)
            super().__init__(**{**kw, "check_proxy_env": False})

    monkeypatch.setattr(lb, "MdlLampTransport", _Spy)

    run.go("--apply", *_YEAR_ARGS, "--download-deadline-s", "14400", mdl=None)

    assert captured == [14400.0]


def test_launch_window_guard_uses_the_configured_deadline(
    run: _Run, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_mock_http(monkeypatch, _no_network)
    # 10:30Z + 6 h 4.5 min worst case meets 16:30Z; the default 2 h 4.5 min does not.
    run.clock.now_ns = int(dt.datetime(2026, 10, 7, 10, 30, tzinfo=dt.UTC).timestamp()) * _NS

    run.go("--apply", *_YEAR_ARGS, "--download-deadline-s", "21600")

    unit = run.units("mdl-yearly")[0]
    assert unit["status"] == "paused_launch_window" and unit["requests"] == 0


def test_rerunning_a_partly_ingested_year_does_not_duplicate_rows(
    run: _Run, monkeypatch: pytest.MonkeyPatch
) -> None:
    tar = _tar([("lmp_lavtxt.202501.2330z.gz", _gz(_month_text(2025, 1, [1, 2, 3])))])
    install_mock_http(monkeypatch, _serve({_year_url(2025): tar}))
    run.clock.now_ns = int(dt.datetime(2026, 10, 7, 18, 0, tzinfo=dt.UTC).timestamp()) * _NS
    args = ("--apply", *_YEAR_ARGS)

    run.go(*args)
    first_manifest = run.manifest()
    first_revisions = run.revisions(2025, 1, 2)
    run.go(*args)

    second = run.units("mdl-yearly")[0]
    assert second["appended"] == 0 and second["unchanged"] == len(first_manifest) == 3
    assert run.manifest() == first_manifest
    assert run.revisions(2025, 1, 2) == first_revisions and len(first_revisions) == 1
