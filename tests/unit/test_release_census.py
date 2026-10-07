"""F13 B0 release census (read-only): PFM issuance times, NBP vintages, LAMP nominal times.

Everything runs over ``tmp_path`` archives written with the real stores; no network.
"""

from __future__ import annotations

import ast
import datetime as dt
import hashlib
import json
import resource
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from breezy.analysis import memory_cap
from breezy.domain.forecast_point import ForecastPoint
from breezy.persistence.us_source_request import US_PFM_AFOS_SOURCE
from breezy.persistence.us_source_revision_store import UsSourceRevisionStore
from breezy.strategy.ladder_ev.forecast_catalog import (
    open_forecast_catalog,
    write_forecast_points,
)
from scripts.analysis import release_census as census

_NS = 1_000_000_000
_MINUTE_NS = 60 * _NS
_HOUR_NS = 3600 * _NS
_SCRIPT = Path(census.__file__)


class _Clock:
    def timestamp_ns(self) -> int:
        return 1_790_000_000 * _NS


def _ts(day: int, hour: int, minute: int) -> int:
    return int(dt.datetime(2026, 9, day, hour, minute, tzinfo=dt.UTC).timestamp()) * _NS


def _store(root: Path) -> UsSourceRevisionStore:
    return UsSourceRevisionStore(root, _Clock())


def _put(store: UsSourceRevisionStore, station: str, wfo: str, run_ts: int, body: str) -> None:
    store.append_if_new(
        source=US_PFM_AFOS_SOURCE,
        station=station,
        run_ts_ns=run_ts,
        model=wfo,
        payload=body.encode(),
    )


def _recording_cap(sink: list[float]) -> Callable[[float], int]:
    def cap(gib: float) -> int:
        sink.append(gib)
        return 0

    return cap


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        digest.update(str(path.relative_to(root)).encode())
        digest.update(path.read_bytes())
        digest.update(str(path.stat().st_mtime_ns).encode())
    return digest.hexdigest()


# ------------------------------------------------------------------ PFM times


def test_pfm_issuance_times_read_per_wfo_from_the_us_pfm_afos_archive(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _put(store, "KNYC", "OKX", _ts(5, 19, 1), "a,b\n1,2\n")
    _put(store, "KNYC", "OKX", _ts(6, 1, 1), "a,b\n3,4\n")
    _put(store, "KLAX", "LOX", _ts(5, 21, 52), "a,b\n5,6\n")
    # a later revision of an existing issuance is the SAME issuance, not a new one
    _put(store, "KNYC", "OKX", _ts(5, 19, 1), "a,b\n9,9\n")

    issuances = census.pfm_issuance_times(tmp_path)

    assert issuances == {
        "LOX": (_ts(5, 21, 52),),
        "OKX": (_ts(5, 19, 1), _ts(6, 1, 1)),
    }


def test_pfm_issuance_times_empty_archive_is_empty_not_an_error(tmp_path: Path) -> None:
    assert census.pfm_issuance_times(tmp_path) == {}


def test_census_is_read_only_over_the_archive(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _put(store, "KNYC", "OKX", _ts(5, 19, 1), "a,b\n1,2\n")
    before = _tree_digest(tmp_path)

    census.pfm_issuance_times(tmp_path)

    assert _tree_digest(tmp_path) == before


def test_summarise_issuances_reports_schedule_regularity() -> None:
    hourly = [_ts(d, h, 15) for d in (1, 2, 3) for h in range(24)]
    extra = [_ts(2, 8, 56)]

    summary = census.summarise_issuances(sorted(hourly + extra))

    assert summary["n_issuances"] == 73
    assert summary["n_days"] == 3
    assert summary["per_day"] == {"min": 24, "median": 24, "max": 25}
    assert summary["median_gap_s"] == pytest.approx(3600.0)
    top = summary["top_minute_of_hour"]
    assert top[0] == {"minute": 15, "count": 72}
    assert summary["first_utc"] == "2026-09-01T00:15:00Z"
    assert summary["last_utc"] == "2026-09-03T23:15:00Z"
    assert summary["fixed_schedule_share"] == pytest.approx(72 / 73)


def test_summarise_issuances_empty_is_a_zero_row() -> None:
    summary = census.summarise_issuances([])
    assert summary["n_issuances"] == 0
    assert summary["first_utc"] is None


# ------------------------------------------------------------------ NBP


def _nbp_point(station: str, cycle_ns: int, lag_ns: int, seq: int = 0) -> ForecastPoint:
    return ForecastPoint(
        station=station,
        model="NBM_NBP",
        model_version="4.2",
        variable="TXN",
        cycle_runtime_ns=cycle_ns,
        valid_start_ns=cycle_ns + 12 * _HOUR_NS,
        valid_end_ns=cycle_ns + 24 * _HOUR_NS,
        value_f=80.0,
        issuance_seq=seq,
        measured_publication_lag_ns=lag_ns,
        available_at_ns=cycle_ns + lag_ns,
        ingested_at_ns=cycle_ns + lag_ns + _MINUTE_NS,
    )


def test_b0_checks_node_nbp_vintages_exist_before_c1_nbp_poll_role(tmp_path: Path) -> None:
    catalog = open_forecast_catalog(tmp_path, "KMIA")
    write_forecast_points(
        catalog,
        [
            _nbp_point("KMIA", _ts(5, 1, 0), 76 * _MINUTE_NS),
            _nbp_point("KMIA", _ts(5, 7, 0), 80 * _MINUTE_NS),
        ],
    )

    report = census.nbp_vintage_report(tmp_path, ["KMIA", "KNYC"])

    assert report["vintages_present"] is True
    assert report["stations"]["KMIA"]["n_vintages"] == 2
    assert report["stations"]["KMIA"]["lag_min_minutes"] == pytest.approx(76.0)
    assert report["stations"]["KMIA"]["lag_max_minutes"] == pytest.approx(80.0)
    assert report["stations"]["KMIA"]["cycle_hours_utc"] == [1, 7]
    assert report["stations"]["KNYC"] == {"present": False, "n_vintages": 0}


def test_nbp_report_with_no_catalog_is_absent_and_creates_nothing(tmp_path: Path) -> None:
    base = tmp_path / "no-such-base"

    report = census.nbp_vintage_report(base, ["KMIA"])

    assert report["vintages_present"] is False
    assert not base.exists()


def test_nbp_report_with_no_base_given_is_absent() -> None:
    report = census.nbp_vintage_report(None, ["KMIA"])
    assert report["vintages_present"] is False
    assert report["reason"] == "no forecast catalog base supplied"


def test_nbp_report_ignores_other_models(tmp_path: Path) -> None:
    catalog = open_forecast_catalog(tmp_path, "KMIA")
    other = _nbp_point("KMIA", _ts(5, 1, 0), 80 * _MINUTE_NS)
    kwargs = {
        k: getattr(other, k)
        for k in (
            "station",
            "model_version",
            "variable",
            "cycle_runtime_ns",
            "valid_start_ns",
            "valid_end_ns",
            "value_f",
            "issuance_seq",
            "measured_publication_lag_ns",
            "available_at_ns",
            "ingested_at_ns",
        )
    }
    write_forecast_points(catalog, [ForecastPoint(model="NBM_NBS", **kwargs)])

    assert census.nbp_vintage_report(tmp_path, ["KMIA"])["vintages_present"] is False


# ------------------------------------------------------------------ LAMP


def test_lamp_nominal_times_are_hh30_with_the_conservative_sixty_minute_lag() -> None:
    rows = census.lamp_nominal_times(dt.date(2026, 9, 1), dt.date(2026, 9, 2))

    assert len(rows) == 48
    first = rows[0]
    assert first["run_utc"] == "2026-09-01T00:30:00Z"
    assert first["nominal_available_utc"] == "2026-09-01T01:30:00Z"
    assert first["basis"] == "nominal_plus_conservative_lag"


_MID_DAY_NS = _ts(2, 12, 45)


def test_lamp_nominal_times_never_list_runs_after_the_injected_now() -> None:
    rows = census.lamp_nominal_times(dt.date(2026, 9, 2), dt.date(2026, 9, 2), now_ns=_MID_DAY_NS)

    assert [r["run_utc"] for r in rows][-1] == "2026-09-02T12:30:00Z"
    assert len(rows) == 13
    assert all(r["run_utc"] <= "2026-09-02T12:45:00Z" for r in rows)


def test_lamp_nominal_times_include_a_run_exactly_at_now() -> None:
    rows = census.lamp_nominal_times(
        dt.date(2026, 9, 2), dt.date(2026, 9, 2), now_ns=_ts(2, 12, 30)
    )

    assert rows[-1]["run_utc"] == "2026-09-02T12:30:00Z"


def test_lamp_summary_counts_only_runs_up_to_now(tmp_path: Path) -> None:
    summary = census.lamp_summary(
        dt.date(2026, 9, 2), dt.date(2026, 9, 3), tmp_path, now_ns=_MID_DAY_NS
    )

    assert summary["n_runs"] == 13
    assert summary["last_run_utc"] == "2026-09-02T12:30:00Z"


def test_lamp_summary_all_future_is_empty_not_an_error(tmp_path: Path) -> None:
    summary = census.lamp_summary(
        dt.date(2026, 9, 3), dt.date(2026, 9, 3), tmp_path, now_ns=_MID_DAY_NS
    )

    assert summary["n_runs"] == 0
    assert summary["first_run_utc"] is None


def test_lamp_summary_marks_the_source_descriptive_nominal_only(tmp_path: Path) -> None:
    summary = census.lamp_summary(dt.date(2026, 9, 1), dt.date(2026, 9, 1), tmp_path)

    assert summary["n_runs"] == 24
    assert summary["measured_c1_rows"] == 0
    assert summary["status"] == "nominal_only_until_c1_has_data"


# ------------------------------------------------------------------ memory cap


def test_address_space_cap_lowers_only_the_soft_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[int, tuple[int, int]]] = []
    monkeypatch.setattr(resource, "getrlimit", lambda _r: (10**12, 8 * 2**30))
    monkeypatch.setattr(resource, "setrlimit", lambda r, v: calls.append((r, v)))

    assert memory_cap.apply_address_space_cap(4) == 4 * 2**30
    assert memory_cap.apply_address_space_cap(64) == 8 * 2**30  # clamped to the hard limit
    assert calls[0][1] == (4 * 2**30, 8 * 2**30)
    with pytest.raises(ValueError, match="positive"):
        memory_cap.apply_address_space_cap(0)


# ------------------------------------------------------------------ main


def test_main_writes_one_json_report_and_enforces_the_memory_cap_flag(tmp_path: Path) -> None:
    caps: list[float] = []
    archive = tmp_path / "archive"
    _put(_store(archive), "KNYC", "OKX", _ts(5, 19, 1), "a,b\n1,2\n")
    out = tmp_path / "census.json"

    rc = census.main(
        [
            "--archive-root",
            str(archive),
            "--lamp-start",
            "2026-09-01",
            "--lamp-end",
            "2026-09-02",
            "--out",
            str(out),
            "--max-memory-gib",
            "6.5",
        ],
        cap=_recording_cap(caps),
    )

    assert rc == 0
    assert caps == [6.5]
    report: dict[str, Any] = json.loads(out.read_text())
    assert report["pfm"]["OKX"]["n_issuances"] == 1
    assert report["nbp"]["vintages_present"] is False
    assert report["lamp"]["n_runs"] == 48
    assert report["inputs"]["outcomes_read"] is False


def test_main_lists_issuance_times_on_or_after_times_since_for_the_b0_placebo_pool(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "archive"
    store = _store(archive)
    _put(store, "KNYC", "OKX", _ts(1, 19, 1), "a,b\n1,2\n")
    _put(store, "KNYC", "OKX", _ts(5, 19, 1), "a,b\n3,4\n")
    out = tmp_path / "census.json"

    rc = census.main(
        [
            "--archive-root",
            str(archive),
            "--out",
            str(out),
            "--lamp-start",
            "2026-09-01",
            "--lamp-end",
            "2026-09-01",
            "--times-since",
            "2026-09-03",
        ],
        cap=lambda _gib: 0,
    )

    assert rc == 0
    report = json.loads(out.read_text())
    assert report["pfm"]["OKX"]["n_issuances"] == 2  # the summary covers everything
    assert report["pfm"]["OKX"]["issuance_times_ns"] == [_ts(5, 19, 1)]
    assert report["inputs"]["times_since"] == "2026-09-03"


def test_main_refuses_an_output_path_inside_the_archive_root(tmp_path: Path) -> None:
    archive = tmp_path / "archive"
    archive.mkdir()

    rc = census.main(
        [
            "--archive-root",
            str(archive),
            "--out",
            str(archive / "x.json"),
            "--lamp-start",
            "2026-09-01",
            "--lamp-end",
            "2026-09-01",
        ]
    )

    assert rc == 2
    assert not (archive / "x.json").exists()


def test_script_imports_no_network_client_and_reads_no_outcome_module() -> None:
    tree = ast.parse(_SCRIPT.read_text())
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    flat = " ".join(sorted(imported))
    for banned in ("httpx", "urllib", "socket", "requests", "settlement", "cli_parse", "iem_mos"):
        assert banned not in flat


# ------------------------------------------------------------------ P1 (review fix)


def test_p1_memory_cap_never_raises_an_already_lower_soft_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[int, tuple[int, int]]] = []
    monkeypatch.setattr(resource, "getrlimit", lambda _r: (2 * 2**30, 8 * 2**30))
    monkeypatch.setattr(resource, "setrlimit", lambda r, v: calls.append((r, v)))

    capped = memory_cap.apply_address_space_cap(6)

    assert capped == 2 * 2**30  # the inherited soft limit wins over the larger request
    assert calls == [(resource.RLIMIT_AS, (2 * 2**30, 8 * 2**30))]


def test_p1_infinite_soft_limit_does_not_clamp_a_smaller_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[int, tuple[int, int]]] = []
    monkeypatch.setattr(
        resource, "getrlimit", lambda _r: (resource.RLIM_INFINITY, resource.RLIM_INFINITY)
    )
    monkeypatch.setattr(resource, "setrlimit", lambda r, v: calls.append((r, v)))

    assert memory_cap.apply_address_space_cap(3) == 3 * 2**30
    assert calls[0][1][0] == 3 * 2**30
