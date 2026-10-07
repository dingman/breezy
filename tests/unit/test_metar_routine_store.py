"""F13 FB-R13: routine-METAR archive store, read helper and 1-min derivation diagnostic.

Injected fetchers/readers only (``tests/conftest.py`` blocks sockets); archives are ``tmp_path``.
"""

from __future__ import annotations

import datetime as dt
import hashlib
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
SCRIPT_PATH: Final[Path] = REPO_ROOT / "scripts/archive/metar_routine_store.py"
for _sibling in ("analysis", "venue", "archive"):
    _path = str(REPO_ROOT / "scripts" / _sibling)
    if _path not in sys.path:
        sys.path.insert(0, _path)

NOON_NS: Final[int] = int(dt.datetime(2026, 10, 7, 12, 0, tzinfo=dt.UTC).timestamp()) * 10**9
WINDOW_NS: Final[int] = int(dt.datetime(2026, 10, 7, 16, 45, tzinfo=dt.UTC).timestamp()) * 10**9
HEADER: Final[str] = "station,valid,tmpf,metar\n"
OTHER_TGROUP: Final[str] = "KNYC X RMK T00170022"  # 1.7 C -> 35 F


@pytest.fixture(scope="module")
def store() -> ModuleType:
    spec = importlib.util.spec_from_file_location("breezy_script_metar_store", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _Resp:
    def __init__(self, status_code: int, text: str) -> None:
        self.status_code = status_code
        self.text = text


def _body(year: int, n: int = 6, raw: str = OTHER_TGROUP, tmpf: str = "35.06") -> str:
    return HEADER + "".join(f"NYC,{year}-02-01 {i:02d}:51,{tmpf},{raw}\n" for i in range(n))


class FakeFetcher:
    def __init__(self, behaviour: Any = None) -> None:
        self.urls: list[str] = []
        self._behaviour = behaviour

    async def fetch_metar_text(self, url: str) -> Any:
        self.urls.append(url)
        if self._behaviour is not None:
            return self._behaviour(url, len(self.urls))
        year = int(url.split("year1=")[1][:4])
        return _Resp(200, _body(year))


async def _no_sleep(_s: float) -> None:
    return None


def _fetch(
    store: ModuleType,
    tmp_path: Path,
    *extra: str,
    fetcher: Any = None,
    clock_ns: int = NOON_NS,
    apply: bool = True,
    sleep: Any = None,
) -> tuple[int, dict[str, Any]]:
    report = tmp_path / "report.json"
    argv = [
        "fetch",
        "--apply" if apply else "--dry-run",
        "--archive-root", str(tmp_path / "root"),
        "--report-json", str(report),
        *extra,
    ]  # fmt: skip
    code = store.main(argv, clock=lambda: clock_ns, fetcher=fetcher, sleep=sleep or _no_sleep)
    return code, json.loads(report.read_text())


@pytest.fixture(autouse=True)
def _live(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BREEZY_LIVE", "1")


# ------------------------------------------------------------------ fetch / idempotence


def test_dry_run_plans_30_requests_and_writes_nothing(store: ModuleType, tmp_path: Path) -> None:
    fetcher = FakeFetcher()
    code, report = _fetch(store, tmp_path, fetcher=fetcher, apply=False)
    assert code == 0 and report["planned_requests"] == 30 and report["cached_station_years"] == 0
    assert fetcher.urls == [] and not (tmp_path / "root").exists()
    last = next(p for p in report["plan"] if p["year"] == 2026)["url"]
    assert "year2=2026&month2=7&day2=1" in last and "report_type=3" in last


def test_full_span_ends_before_the_holdout(store: ModuleType) -> None:
    plan = store.build_store_plan(["KNYC"], list(range(2021, 2027)), dt.date(2026, 7, 1))
    assert (plan[0].start, plan[0].end) == (dt.date(2021, 1, 1), dt.date(2022, 1, 1))
    assert plan[-1].end == dt.date(2026, 7, 1)


@pytest.mark.parametrize("end", ["2026-07-02", "2027-01-01"])
def test_holdout_end_is_refused_with_report(store: ModuleType, tmp_path: Path, end: str) -> None:
    fetcher = FakeFetcher()
    code, report = _fetch(store, tmp_path, "--end-exclusive", end, fetcher=fetcher)
    assert code == 2 and "holdout" in report["error"] and fetcher.urls == []


def test_year_after_holdout_is_refused(store: ModuleType, tmp_path: Path) -> None:
    code, report = _fetch(store, tmp_path, "--years", "2027", fetcher=FakeFetcher())
    assert code == 2 and report["status"] == "error"


def test_fetch_persists_columns_manifest_and_is_idempotent(
    store: ModuleType, tmp_path: Path
) -> None:
    args = ("--stations", "KNYC", "--years", "2021", "2022", "--request-budget", "5")
    fetcher = FakeFetcher()
    code, report = _fetch(store, tmp_path, *args, fetcher=fetcher)
    root = tmp_path / "root"
    assert code == 0 and len(fetcher.urls) == 2 and report["results"]["KNYC/2021"] == "fetched"
    text = (root / "KNYC" / "2021.csv").read_text().splitlines()
    assert text[0] == "station,valid_utc,tmpf,tgroup_c,report_type,tmpf_source,metar"
    assert text[1] == "KNYC,2021-02-01T00:51Z,35,1.7,3,tgroup,KNYC X RMK T00170022"
    manifest = json.loads((root / "manifest.json").read_text())
    entry = manifest["entries"]["KNYC/2021"]
    assert entry["sha256"] == hashlib.sha256((root / "KNYC" / "2021.csv").read_bytes()).hexdigest()
    assert entry["rows"] == 6
    again = FakeFetcher()
    code, report = _fetch(store, tmp_path, *args, fetcher=again)
    assert code == 0 and again.urls == [] and report["results"]["KNYC/2021"] == "cached"


def test_corrupt_file_is_refetched(store: ModuleType, tmp_path: Path) -> None:
    args = ("--stations", "KNYC", "--years", "2021", "--request-budget", "3")
    _fetch(store, tmp_path, *args, fetcher=FakeFetcher())
    (tmp_path / "root" / "KNYC" / "2021.csv").write_text("corrupt")
    again = FakeFetcher()
    code, _ = _fetch(store, tmp_path, *args, fetcher=again)
    assert code == 0 and len(again.urls) == 1


def test_tmpf_falls_back_to_column_with_flag_and_missing(store: ModuleType) -> None:
    from metar_routine_minute_probe import parse_metar_csv

    rows = parse_metar_csv(
        HEADER
        + "NYC,2021-02-01 00:51,40.4,KNYC X RMK AO2\n"
        + "NYC,2021-02-01 01:51,M,KNYC X RMK AO2\n"
        + "NYC,2021-02-01 02:51,M,KNYC X RMK T11001125\n"
        + "NYC,2021-02-01 00:51,99.0,DUPLICATE X\n"
    )
    lines = store.serialise_year("KNYC", rows).decode().splitlines()[1:]
    assert lines[0].split(",")[2:6] == ["40", "", "3", "column"]
    assert lines[1].split(",")[2:6] == ["", "", "3", "missing"]
    assert lines[2].split(",")[2:6] == ["14", "-10.0", "3", "tgroup"]  # -10.0 C = 14 F
    assert len(lines) == 3  # the duplicate instant is dropped


# ------------------------------------------------------------------ gates


def test_apply_needs_live_env_and_budget(
    store: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    code, report = _fetch(store, tmp_path, "--request-budget", "29", fetcher=FakeFetcher())
    assert code == 2 and "budget" in report["error"]
    monkeypatch.delenv("BREEZY_LIVE")
    code, report = _fetch(store, tmp_path, "--request-budget", "60", fetcher=FakeFetcher())
    assert code == 2 and "BREEZY_LIVE" in report["error"]


def test_launch_window_refused(store: ModuleType, tmp_path: Path) -> None:
    fetcher = FakeFetcher()
    code, report = _fetch(
        store, tmp_path, "--request-budget", "60", fetcher=fetcher, clock_ns=WINDOW_NS
    )
    assert code == 6 and report["status"] == "refused_launch_window" and fetcher.urls == []


def test_budget_exhaustion_exit_3_keeps_completed_years(store: ModuleType, tmp_path: Path) -> None:
    def behaviour(url: str, call: int) -> Any:
        if call > 1:
            raise RequestBudgetExceededError("spent")
        return _Resp(200, _body(int(url.split("year1=")[1][:4])))

    code, report = _fetch(
        store, tmp_path, "--stations", "KNYC", "--years", "2021", "2022",
        "--request-budget", "5", fetcher=FakeFetcher(behaviour),
    )  # fmt: skip
    assert code == 3 and report["status"] == "budget_exhausted"
    assert (tmp_path / "root" / "KNYC" / "2021.csv").exists()
    assert not (tmp_path / "root" / "KNYC" / "2022.csv").exists()


def test_bad_status_timeouts_and_empty_fail_the_year_only(
    store: ModuleType, tmp_path: Path
) -> None:
    def behaviour(_url: str, call: int) -> Any:
        if call <= 3:
            raise TransportTimeoutError("slow")
        if call == 4:
            return _Resp(422, "Unknown")
        return _Resp(200, HEADER)

    code, report = _fetch(
        store, tmp_path, "--stations", "KNYC", "--years", "2021", "2022", "2023",
        "--request-budget", "9", fetcher=FakeFetcher(behaviour),
    )  # fmt: skip
    assert code == 1
    assert report["results"] == {
        "KNYC/2021": "fetch_error: TransportTimeoutError",
        "KNYC/2022": "http_422",
        "KNYC/2023": "empty",
    }
    assert not (tmp_path / "root" / "manifest.json").exists()


def test_unexpected_error_writes_report_exit_2(store: ModuleType, tmp_path: Path) -> None:
    def behaviour(_url: str, _call: int) -> Any:
        raise RuntimeError("boom")

    code, report = _fetch(store, tmp_path, "--request-budget", "60", fetcher=FakeFetcher(behaviour))
    assert code == 2 and "boom" in report["error"] and report["exit_code"] == 2


# ------------------------------------------------------------------ read helper


def _populate(store: ModuleType, tmp_path: Path, years: str = "2021") -> Path:
    _fetch(
        store,
        tmp_path,
        "--stations",
        "KNYC",
        "--years",
        years,
        "--request-budget",
        "3",
        fetcher=FakeFetcher(),
    )
    return tmp_path / "root"


def test_read_routine_metar_window_and_values(store: ModuleType, tmp_path: Path) -> None:
    root = _populate(store, tmp_path)
    start = dt.datetime(2021, 2, 1, 2, 0, tzinfo=dt.UTC)
    rows = store.read_routine_metar(
        "KNYC", start, dt.datetime(2021, 2, 1, 4, 0, tzinfo=dt.UTC), root
    )
    assert [r.valid_utc.hour for r in rows] == [2, 3]
    assert rows[0].tmpf == 35 and rows[0].tgroup_c == 1.7 and rows[0].tmpf_source == "tgroup"
    assert store.read_routine_metar("KNYC", dt.date(2021, 2, 2), dt.date(2021, 2, 3), root) == []


def test_read_refuses_missing_corrupt_and_holdout(store: ModuleType, tmp_path: Path) -> None:
    root = _populate(store, tmp_path)
    with pytest.raises(store.RoutineMetarError, match="not in the routine-METAR archive"):
        store.read_routine_metar("KNYC", dt.date(2022, 1, 1), dt.date(2022, 1, 2), root)
    with pytest.raises(store.RoutineMetarError, match="holdout"):
        store.read_routine_metar("KNYC", dt.date(2026, 6, 30), dt.date(2026, 7, 2), root)
    (root / "KNYC" / "2021.csv").write_text("tampered")
    with pytest.raises(store.RoutineMetarError, match="sha256"):
        store.read_routine_metar("KNYC", dt.date(2021, 2, 1), dt.date(2021, 2, 2), root)


# ------------------------------------------------------------------ diagnostic


def test_variant_values_offsets_mean_and_alternative_roundings(store: ModuleType) -> None:
    when = dt.datetime(2021, 2, 1, 0, 51, tzinfo=dt.UTC)
    minute = dt.timedelta(minutes=1)
    onemin = {when + i * minute: 36.0 for i in range(-5, 3)}
    onemin[when] = 35.0
    onemin[when - minute] = 37.0
    out = store.variant_values(when, 17, onemin)  # 1.7 C -> 35.06 F -> 35
    assert (
        out["offset+0"] == (35, 35) and out["offset-1"] == (37, 35) and out["offset+2"] == (36, 35)
    )
    assert out["max5"] == (37, 35) and out["min5"] == (35, 35)
    assert out["mean5_via_round_half_up_f"] == (36, 35)  # mean 36.0
    assert out["metar_floor_vs_offset+0"] == (35, 35) and out["metar_ceil_vs_offset+0"] == (35, 36)
    assert out["roundtrip_c_tenths_offset+0"] == (35, 35)
    assert out["any_offset_-5..+2_equals"] == (35, 35)


def test_variants_requiring_a_full_window_are_skipped_when_incomplete(store: ModuleType) -> None:
    when = dt.datetime(2021, 2, 1, 0, 51, tzinfo=dt.UTC)
    out = store.variant_values(when, 17, {when: 35.0})
    assert "mean5_via_round_half_up_f" not in out and "offset-1" not in out and "offset+0" in out


def test_floor_ceil_exact_arithmetic(store: ModuleType) -> None:
    assert store.metar_exact_f_floor_ceil(0) == (32, 32)
    assert store.metar_exact_f_floor_ceil(17) == (35, 36)
    assert store.metar_exact_f_floor_ceil(-10) == (30, 31)  # -1.0 C = 30.2 F


def test_diag_leg_reports_mismatch_per_variant(store: ModuleType, tmp_path: Path) -> None:
    root = _populate(store, tmp_path)
    lines = ["station,station_name,valid(UTC),tmpf,dwpf"]
    for hour in range(6):
        value = 35 if hour < 4 else 36  # two of six rows disagree at offset 0
        lines.append(f"NYC,X,2021-02-01 {hour:02d}:51,{value},30")
    report_path = tmp_path / "diag.json"
    code = store.main(
        ["diag", "--archive-root", str(root), "--report-json", str(report_path),
         "--stations", "KNYC", "--years", "2021"],
        clock=lambda: NOON_NS,
        onemin_reader=lambda _s, _y: ("\n".join(lines) + "\n").encode(),
    )  # fmt: skip
    report = json.loads(report_path.read_text())
    off0 = report["stations"]["KNYC"]["variants"]["offset+0"]
    assert code == 0 and off0["n"] == 6 and off0["mismatch_rate"] == pytest.approx(2 / 6)
    assert off0["max_abs_diff"] == 1


def test_diag_records_missing_onemin_year(store: ModuleType, tmp_path: Path) -> None:
    root = _populate(store, tmp_path)
    report_path = tmp_path / "diag.json"
    code = store.main(
        ["diag", "--archive-root", str(root), "--report-json", str(report_path),
         "--stations", "KNYC", "--years", "2021"],
        clock=lambda: NOON_NS,
        onemin_reader=lambda _s, _y: None,
    )  # fmt: skip
    report = json.loads(report_path.read_text())
    assert code == 0 and report["stations"]["KNYC"]["years_missing_onemin"] == [2021]


def test_diag_on_an_unstored_year_is_an_error_report(store: ModuleType, tmp_path: Path) -> None:
    report_path = tmp_path / "diag.json"
    code = store.main(
        ["diag", "--archive-root", str(tmp_path / "empty"), "--report-json", str(report_path),
         "--stations", "KNYC", "--years", "2021"],
        clock=lambda: NOON_NS,
        onemin_reader=lambda _s, _y: None,
    )  # fmt: skip
    assert code == 2 and json.loads(report_path.read_text())["status"] == "error"
