"""F13 FB-R13: the routine-METAR report-minute probe and 1-min equivalence measurement.

Everything runs against injected fetchers and readers; ``tests/conftest.py`` blocks sockets, so a
regression that reached the network fails instead of spending a request. Reports go to
``tmp_path`` only.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Final

import pytest

from breezy.ingest.http import TransportTimeoutError
from breezy.ingest.probe_transport import RequestBudgetExceededError

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
SCRIPT_PATH: Final[Path] = REPO_ROOT / "scripts/archive/metar_routine_minute_probe.py"

for _sibling in ("analysis", "venue", "archive"):
    _path = str(REPO_ROOT / "scripts" / _sibling)
    if _path not in sys.path:
        sys.path.insert(0, _path)

NOON_NS: Final[int] = int(dt.datetime(2026, 10, 7, 12, 0, tzinfo=dt.UTC).timestamp()) * 10**9
WINDOW_NS: Final[int] = int(dt.datetime(2026, 10, 7, 16, 45, tzinfo=dt.UTC).timestamp()) * 10**9
HEADER: Final[str] = "station,valid,tmpf,metar\n"


@pytest.fixture(scope="module")
def probe() -> ModuleType:
    spec = importlib.util.spec_from_file_location("breezy_script_metar_probe", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _metar(day: str, hhmm: str, tmpf: str, raw: str) -> str:
    return f"NYC,{day} {hhmm},{tmpf},{raw}\n"


def _body(
    minute: str = "51", n: int = 20, tmpf: str = "63.00", raw: str | None = None, year: int = 2021
) -> str:
    rows = [
        _metar(
            f"{year}-03-{1 + i // 24:02d}",
            f"{i % 24:02d}:{minute}",
            tmpf,
            raw or "KNYC X RMK T00170000",
        )
        for i in range(n)
    ]
    return HEADER + "".join(rows)


class FakeFetcher:
    def __init__(self, behaviour: Any = None) -> None:
        self.urls: list[str] = []
        self._behaviour = behaviour

    async def fetch_metar_text(self, url: str) -> Any:
        self.urls.append(url)
        if self._behaviour is None:
            return _Resp(200, _body())
        return self._behaviour(url, len(self.urls))


class _Resp:
    def __init__(self, status_code: int, text: str) -> None:
        self.status_code = status_code
        self.text = text


def _run(
    probe: ModuleType,
    tmp_path: Path,
    *extra: str,
    fetcher: Any = None,
    clock_ns: int = NOON_NS,
    onemin: Any = lambda _icao, _year: None,  # never touch the real archive
    sleep: Any = None,
    apply: bool = False,
) -> tuple[int, dict[str, Any]]:
    report = tmp_path / "report.json"
    argv = ["--apply" if apply else "--dry-run", "--report-json", str(report), *extra]
    code = probe.main(
        argv,
        clock=lambda: clock_ns,
        fetcher=fetcher,
        onemin_reader=onemin,
        sleep=sleep or _no_sleep,
    )
    return code, json.loads(report.read_text())


async def _no_sleep(_seconds: float) -> None:
    return None


# ------------------------------------------------------------------ T-group


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("KNYC 011951Z 00000KT 10SM CLR 17/M02 A3000 RMK AO2 T01720022", 172),
        ("KMDW 011951Z 00000KT 10SM CLR M05/M10 A3000 RMK AO2 T10501100", -50),
        ("KMDW 011951Z 00000KT CLR M05/M10 A3000 RMK AO2 T11001125", -100),
        ("KMDW 011951Z 00000KT CLR 00/M01 A3000 RMK AO2 T0000", 0),
        ("KNYC 011951Z 00000KT 10SM CLR 17/M02 A3000 RMK AO2", None),
        ("KNYC 011951Z 00000KT 10SM CLR 17/M02 A3000", None),
        ("", None),
    ],
)
def test_parse_tgroup_tenths(probe: ModuleType, raw: str, expected: int | None) -> None:
    assert probe.parse_tgroup_tenths(raw) == expected


def test_tgroup_in_body_is_not_a_tgroup(probe: ModuleType) -> None:
    assert probe.parse_tgroup_tenths("KXXX T01720022 CLR 17/M02") is None


def test_tgroup_to_f_uses_the_live_quantiser(probe: ModuleType) -> None:
    assert probe.tgroup_to_f(172) == 63  # 62.96 F
    assert probe.tgroup_to_f(-50) == 23


# ------------------------------------------------------------------ parsing


def test_parse_metar_csv_handles_missing_tmpf(probe: ModuleType) -> None:
    rows = probe.parse_metar_csv(
        HEADER + _metar("2021-03-01", "00:51", "M", "KNYC X RMK T00170000")
    )
    assert rows[0].tmpf is None
    assert rows[0].valid == dt.datetime(2021, 3, 1, 0, 51, tzinfo=dt.UTC)


def test_parse_metar_csv_rejects_a_headerless_body(probe: ModuleType) -> None:
    with pytest.raises(ValueError, match="header"):
        probe.parse_metar_csv("Too many requests from your IP address\n")


# ------------------------------------------------------------------ modal stats


def test_year_stats_modal_minute_share_and_missing_rate(probe: ModuleType) -> None:
    rows = probe.parse_metar_csv(
        HEADER
        + "".join(
            _metar("2021-03-01", f"{h:02d}:51", "M" if h < 2 else "60.0", "X") for h in range(10)
        )
        + _metar("2021-03-02", "05:20", "60.0", "X")  # one special-ish off-minute report
    )
    stats = probe.year_stats(rows)
    assert stats["modal_minute"] == 51
    assert stats["n_reports"] == 11
    assert stats["modal_share"] == pytest.approx(10 / 11)
    assert stats["missing_tmpf_rate"] == pytest.approx(2 / 10)


def test_year_stats_empty(probe: ModuleType) -> None:
    assert probe.year_stats([])["modal_minute"] is None


# ------------------------------------------------------------------ verdicts


def _y(minute: int, share: float) -> dict[str, Any]:
    return {"modal_minute": minute, "modal_share": share}


def test_verdict_pin_station(probe: ModuleType) -> None:
    out = probe.classify_station({2021: _y(51, 0.99), 2022: _y(51, 0.95)}, expected_years=2)
    assert out == {"verdict": "PIN_STATION", "pin_minute": 51}


def test_verdict_pin_station_year_when_minute_drifts(probe: ModuleType) -> None:
    out = probe.classify_station({2021: _y(51, 0.99), 2022: _y(53, 0.99)}, expected_years=2)
    assert out == {"verdict": "PIN_STATION_YEAR", "pin_minute_by_year": {2021: 51, 2022: 53}}


def test_verdict_unpinnable_below_threshold_in_any_year(probe: ModuleType) -> None:
    out = probe.classify_station({2021: _y(51, 0.99), 2022: _y(51, 0.9499)}, expected_years=2)
    assert out == {"verdict": "UNPINNABLE"}


def test_verdict_incomplete_when_a_year_is_missing(probe: ModuleType) -> None:
    out = probe.classify_station(
        {2021: _y(51, 0.99), 2022: {"modal_minute": None}}, expected_years=2
    )
    assert out == {"verdict": "INCOMPLETE"}


# ------------------------------------------------------------------ plan and holdout


def test_default_plan_is_one_request_per_station_year_and_stays_pre_holdout(
    probe: ModuleType,
) -> None:
    plan = probe.build_plan(["KLAX", "KMDW", "KMIA", "KNYC", "KSFO"])
    assert len(plan) == 30
    assert all(item.end <= probe.HOLDOUT_START for item in plan)
    assert "report_type=3" in plan[0].url and "asos.py" in plan[0].url


def test_default_stations_are_the_phase_a_list(probe: ModuleType, tmp_path: Path) -> None:
    from multisource_blend_features_build import DEFAULT_STATIONS

    _code, report = _run(probe, tmp_path)
    assert {p["station"] for p in report["plan"]} == set(DEFAULT_STATIONS)


@pytest.mark.parametrize("months", [["2026=7"], ["2026=12"], ["2027=1"]])
def test_holdout_windows_are_refused_with_report(
    probe: ModuleType, tmp_path: Path, months: list[str]
) -> None:
    fetcher = FakeFetcher()
    code, report = _run(probe, tmp_path, "--months", *months, fetcher=fetcher, apply=True)
    assert code == 2
    assert report["status"] == "error" and "holdout" in report["error"]
    assert fetcher.urls == []


def test_june_2026_is_allowed(probe: ModuleType) -> None:
    assert probe.build_plan(["KNYC"], {2026: 6})[0].end == dt.date(2026, 7, 1)


def test_unknown_station_is_refused(probe: ModuleType, tmp_path: Path) -> None:
    code, report = _run(probe, tmp_path, "--stations", "KZZZ")
    assert code == 2 and "KZZZ" in report["error"]


def test_url_guard_allows_only_iem_asos(probe: ModuleType) -> None:
    probe.require_metar_url(probe.build_plan(["KNYC"], {2021: 3})[0].url)
    for bad in (
        "https://api.weather.gov/cgi-bin/request/asos.py",
        "http://mesonet.agron.iastate.edu/cgi-bin/request/asos.py",
        "https://mesonet.agron.iastate.edu/cgi-bin/request/mos.py",
    ):
        with pytest.raises(ValueError, match="refused"):
            probe.require_metar_url(bad)


# ------------------------------------------------------------------ modes and gates


def test_dry_run_plans_without_fetching(probe: ModuleType, tmp_path: Path) -> None:
    fetcher = FakeFetcher()
    code, report = _run(probe, tmp_path, fetcher=fetcher)
    assert code == 0 and report["planned_requests"] == 30 and report["status"] == "dry_run"
    assert fetcher.urls == []


def test_apply_requires_live_env(
    probe: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("BREEZY_LIVE", raising=False)
    fetcher = FakeFetcher()
    code, report = _run(probe, tmp_path, "--request-budget", "60", fetcher=fetcher, apply=True)
    assert code == 2 and "BREEZY_LIVE" in report["error"] and fetcher.urls == []


def test_apply_requires_a_budget_covering_the_plan(
    probe: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BREEZY_LIVE", "1")
    fetcher = FakeFetcher()
    code, report = _run(probe, tmp_path, "--request-budget", "29", fetcher=fetcher, apply=True)
    assert code == 2 and "budget" in report["error"] and fetcher.urls == []
    code, _ = _run(probe, tmp_path, fetcher=fetcher, apply=True)
    assert code == 2


@pytest.mark.parametrize("apply", [False, True])
def test_launch_window_is_refused_with_report(
    probe: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, apply: bool
) -> None:
    monkeypatch.setenv("BREEZY_LIVE", "1")
    fetcher = FakeFetcher()
    code, report = _run(
        probe, tmp_path, "--request-budget", "60", fetcher=fetcher, clock_ns=WINDOW_NS, apply=apply
    )
    assert code == 6 and report["status"] == "refused_launch_window" and fetcher.urls == []


def test_budget_exhaustion_aborts_with_exit_3_and_report(
    probe: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BREEZY_LIVE", "1")

    def behaviour(_url: str, call: int) -> Any:
        if call > 2:
            raise RequestBudgetExceededError("spent")
        return _Resp(200, _body())

    code, report = _run(
        probe, tmp_path, "--request-budget", "30", fetcher=FakeFetcher(behaviour), apply=True
    )
    assert code == 3 and report["status"] == "budget_exhausted"
    assert report["stations"]["KLAX"]["years"]["2021"]["status"] == "ok"


def test_unexpected_error_still_writes_report_with_exit_2(
    probe: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BREEZY_LIVE", "1")

    def behaviour(_url: str, _call: int) -> Any:
        raise RuntimeError("boom")

    code, report = _run(
        probe, tmp_path, "--request-budget", "60", fetcher=FakeFetcher(behaviour), apply=True
    )
    assert code == 2 and report["status"] == "error" and "boom" in report["error"]
    assert report["exit_code"] == 2


def test_transient_timeouts_are_retried_with_backoff(
    probe: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BREEZY_LIVE", "1")
    sleeps: list[float] = []

    async def record(seconds: float) -> None:
        sleeps.append(seconds)

    def behaviour(_url: str, call: int) -> Any:
        if call <= 2:
            raise TransportTimeoutError("slow")
        return _Resp(200, _body())

    code, report = _run(
        probe,
        tmp_path,
        "--stations",
        "KNYC",
        "--months",
        "2021=3",
        "--request-budget",
        "5",
        fetcher=FakeFetcher(behaviour),
        sleep=record,
        apply=True,
    )
    assert code == 0 and sleeps == [30.0, 60.0]
    assert report["stations"]["KNYC"]["years"]["2021"]["status"] == "ok"


def test_exhausted_retries_and_bad_status_fail_the_station_year_not_the_run(
    probe: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BREEZY_LIVE", "1")

    def behaviour(_url: str, call: int) -> Any:
        if call <= 3:
            raise TransportTimeoutError("slow")
        return _Resp(422, "Unknown station")

    code, report = _run(
        probe,
        tmp_path,
        "--stations",
        "KNYC",
        "--months",
        "2021=3",
        "2022=3",
        "--request-budget",
        "9",
        fetcher=FakeFetcher(behaviour),
        apply=True,
    )
    years = report["stations"]["KNYC"]["years"]
    assert code == 1
    assert years["2021"]["status"].startswith("fetch_error")
    assert years["2022"]["status"] == "http_422"
    assert report["stations"]["KNYC"]["verdict"] == "INCOMPLETE"


# ------------------------------------------------------------------ end to end


def _two_year_fetcher(minute_by_year: dict[str, str]) -> FakeFetcher:
    def behaviour(url: str, _call: int) -> Any:
        year = url.split("year1=")[1][:4]
        return _Resp(200, _body(minute=minute_by_year[year], tmpf="63.00", year=int(year)))

    return FakeFetcher(behaviour)


def test_end_to_end_proposals_and_equivalence(
    probe: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BREEZY_LIVE", "1")
    fetcher = _two_year_fetcher({"2021": "51", "2022": "53"})

    def onemin(icao: str, year: int) -> bytes | None:
        if year == 2022:
            return None  # month absent from the local archive: recorded, never invented
        lines = ["station,station_name,valid(UTC),tmpf,dwpf"]
        for i in range(20):
            minute = "51"
            stamp = f"2021-03-{1 + i // 24:02d} {i % 24:02d}:{minute}"
            lines.append(f"NYC,NEW YORK,{stamp},{62 if i < 10 else 63},50")
        return ("\n".join(lines) + "\n").encode()

    code, report = _run(
        probe,
        tmp_path,
        "--stations",
        "KNYC",
        "--months",
        "2021=3",
        "2022=3",
        "--request-budget",
        "5",
        fetcher=fetcher,
        onemin=onemin,
        apply=True,
    )
    station = report["stations"]["KNYC"]
    assert code == 0 and station["verdict"] == "PIN_STATION_YEAR"
    assert report["proposals"]["obs_routine_minute_by_station_year"] == {
        "KNYC": {"2021": 51, "2022": 53}
    }
    assert report["proposals"]["obs_routine_minute_by_station"] == {}
    eq = station["equivalence"]
    # T00170000 = 1.7 C = 35.06 F -> 35; the 1-min value is 62 or 63 -> diffs +27/+28 (synthetic)
    assert eq["onemin_vs_metar_tgroup"]["n_compared"] == 20
    assert eq["onemin_vs_metar_tgroup"]["mismatch_rate"] == 1.0
    assert eq["onemin_vs_metar_tgroup"]["max_abs_diff"] == 28
    assert eq["onemin_vs_metar_tgroup"]["mean_signed_bias"] == pytest.approx(27.5)
    assert eq["months_missing_in_onemin_archive"] == ["2022-03"]
    assert eq["tmpf_column_vs_tgroup"]["max_abs_diff"] == 28


def test_equivalence_exact_agreement_and_missing_tgroup(probe: ModuleType) -> None:
    rows = probe.parse_metar_csv(
        HEADER
        + _metar("2021-03-01", "00:51", "63.00", "X RMK T00170022")  # 1.7 C -> 35 F
        + _metar("2021-03-01", "01:51", "35.06", "X RMK T00170022")
        + _metar("2021-03-01", "02:51", "40.00", "X RMK AO2")  # no T-group
        + _metar("2021-03-01", "03:51", "35.00", "X RMK T00170022")  # no 1-min row
    )
    acc = probe.EquivalenceAccumulator()
    onemin = {rows[0].valid: 35.0, rows[1].valid: 36.0, rows[2].valid: 40.0}
    acc.add_month(rows, onemin, "2021-03")
    out = acc.report()
    assert out["n_no_tgroup"] == 1 and out["n_tgroup_without_onemin_row"] == 1
    cmp_ = out["onemin_vs_metar_tgroup"]
    assert cmp_["n_compared"] == 2 and cmp_["mismatch_rate"] == 0.5
    assert cmp_["mean_signed_bias"] == 0.5 and cmp_["max_abs_diff"] == 1


def test_unwritable_report_returns_exit_2(probe: ModuleType, tmp_path: Path) -> None:
    code = probe.main(
        ["--dry-run", "--report-json", str(tmp_path / "missing_dir" / "r.json")],
        clock=lambda: NOON_NS,
    )
    assert code == 2
