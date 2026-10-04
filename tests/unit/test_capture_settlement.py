"""AUT-1 WP5-B: the capture settlement writer and its CLI (plan r12 section 3.12, r8 section 3.9).

Real station catalogs are seeded under ``tmp_path`` through ``write_records``; the writer reads them
through the audit accessor and appends ``SettlementRecord`` lines to
``<decisions_dir>/settlement_<climate_day>.jsonl``. Alerts go through an injected
``offer(event, severity, detail) -> accepted`` (the WP1/WP4 seam).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Final

import pytest

from breezy.analysis import capture_settlement as cs
from breezy.analysis import capture_settlement_cli as cli
from breezy.domain.nws_climate_day import CLIMATE_DAY_SCHEMA_VERSION, NwsClimateDay
from breezy.persistence.catalog import open_station_catalog, write_records
from tests.support.capture_closure_lint import AUT1_WRITE_AUTHORITY, aut1_files, lint_files
from tests.unit.autonomy_writer_table import AUTONOMY_FILE_WRITERS

VENUE: Final = "polymarket_us"
TODAY: Final = dt.date(2026, 10, 4)
NS: Final = 1_000_000_000
SITES: Final = (cs.SettlementSite("NYC", "NYC"), cs.SettlementSite("MDW", "MDW"))
ERROR_EVENT: Final = "CAPTURE_SETTLEMENT_ERROR"


class Offers:
    """A recording outbox: ``accepted`` is the return of every offer."""

    def __init__(self, accepted: bool = True) -> None:
        self.accepted = accepted
        self.calls: list[tuple[str, str, str]] = []

    def __call__(self, event: str, severity: str, detail: str) -> bool:
        self.calls.append((event, severity, detail))
        return self.accepted


def _sha(tag: str) -> str:
    return hashlib.sha256(tag.encode()).hexdigest()


def _climate_day(
    station: str, day: dt.date, *, tmax: int | None = 84, sha: str | None = None, **over: Any
) -> NwsClimateDay:
    retrieved = (
        int(dt.datetime(day.year, day.month, day.day, 6, 31, tzinfo=dt.UTC).timestamp() * NS)
        + 86_400 * NS
    )
    kwargs: dict[str, Any] = {
        "station": station,
        "climate_day": day,
        "tmax_f": tmax,
        "tmin_f": 63,
        "tavg_f": 74,
        "tmax_flag": None,
        "tmin_flag": None,
        "tavg_flag": None,
        "is_final": True,
        "correction_flag": False,
        "revision_seq": 1,
        "is_superseded": False,
        "issuing_office": "KOKX",
        "issuance_time_ns": retrieved - 240 * NS,
        "retrieved_at_ns": retrieved,
        "parser_version": "pyiem==1.27.0",
        "registry_version": "1.0.0",
        "raw_sha256": sha or _sha(f"{station}{day}"),
        "source_channel": f"api.weather.gov/products/types/CLI/locations/{station}",
        "schema_version": CLIMATE_DAY_SCHEMA_VERSION,
        "ts_event": retrieved - 3600 * NS,
    }
    kwargs.update(over)
    return NwsClimateDay(**kwargs)


def _seed(base: Path, city: str, *records: NwsClimateDay) -> None:
    write_records(open_station_catalog(base, VENUE, city), list(records))


def _seed_window(base: Path, *, cities: tuple[str, ...] = ("NYC", "MDW")) -> None:
    for city in cities:
        for back in range(1, 8):
            day = TODAY - dt.timedelta(days=back)
            _seed(base, city, _climate_day(city, day))


def _run(
    tmp_path: Path,
    offer: Offers | None = None,
    *,
    sites: tuple[cs.SettlementSite, ...] = SITES,
    **kwargs: Any,
) -> tuple[cs.SettlementRunResult, Offers, Path]:
    decisions = tmp_path / "decisions"
    decisions.mkdir(exist_ok=True, mode=0o700)
    outbox = offer or Offers()
    result = cs.run_settlement(
        venue=VENUE,
        today=TODAY,
        decisions_dir=decisions,
        catalog_base=tmp_path / "catalog",
        sites=sites,
        offer=outbox,
        **kwargs,
    )
    return result, outbox, decisions


def _lines(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def _file(decisions: Path, day: dt.date) -> Path:
    return decisions / f"settlement_{day.isoformat()}.jsonl"


# -- scan window ---------------------------------------------------------------------------------


def test_scan_days_are_today_minus_7_through_today_minus_1() -> None:
    days = cs.scan_days(TODAY)
    assert days[0] == TODAY - dt.timedelta(days=7)
    assert days[-1] == TODAY - dt.timedelta(days=1)
    assert len(days) == 7


def test_settlement_scans_only_the_trailing_seven_days(tmp_path: Path) -> None:
    base = tmp_path / "catalog"
    for back in (0, 1, 7, 8):
        _seed(base, "NYC", _climate_day("NYC", TODAY - dt.timedelta(days=back)))
    _seed(base, "MDW", _climate_day("MDW", TODAY - dt.timedelta(days=1)))
    result, _, decisions = _run(tmp_path)
    written = sorted(p.name for p in decisions.glob("settlement_*.jsonl"))
    assert written == [
        f"settlement_{(TODAY - dt.timedelta(days=7)).isoformat()}.jsonl",
        f"settlement_{(TODAY - dt.timedelta(days=1)).isoformat()}.jsonl",
    ]
    assert result.appended == 3


# -- append once per raw_sha256 / corrections / basis --------------------------------------------


def test_settlement_appends_once_per_raw_sha(tmp_path: Path) -> None:
    _seed_window(tmp_path / "catalog")
    first, _, decisions = _run(tmp_path)
    before = {p.name: p.read_bytes() for p in decisions.glob("settlement_*.jsonl")}
    second, _, _ = _run(tmp_path)
    after = {p.name: p.read_bytes() for p in decisions.glob("settlement_*.jsonl")}
    assert first.appended == 14 and first.errors == ()
    assert second.appended == 0 and second.already_present == 14
    assert before == after
    rows = _lines(_file(decisions, TODAY - dt.timedelta(days=1)))
    assert sorted(r["station"] for r in rows) == ["MDW", "NYC"]
    one = next(r for r in rows if r["station"] == "NYC")
    assert one == {
        "station": "NYC",
        "climate_day": (TODAY - dt.timedelta(days=1)).isoformat(),
        "settlement_tmax_f": 84,
        "basis": "NWS_CLI",
        "raw_sha256": _sha(f"NYC{TODAY - dt.timedelta(days=1)}"),
        "ts_ns": one["ts_ns"],
    }
    assert isinstance(one["ts_ns"], int)


def test_settlement_correction_appends_new_record(tmp_path: Path) -> None:
    day = TODAY - dt.timedelta(days=2)
    base = tmp_path / "catalog"
    original = _climate_day("NYC", day, tmax=84)
    _seed(base, "NYC", original)
    _, _, decisions = _run(tmp_path, sites=(cs.SettlementSite("NYC", "NYC"),))
    before = _file(decisions, day).read_bytes()
    corrected = _climate_day(
        "NYC",
        day,
        tmax=85,
        sha=_sha("corrected"),
        correction_flag=True,
        revision_seq=2,
        retrieved_at_ns=original.retrieved_at_ns + 3600 * NS,
        issuance_time_ns=original.retrieved_at_ns + 3500 * NS,
    )
    _seed(base, "NYC", corrected)
    result, _, _ = _run(tmp_path, sites=(cs.SettlementSite("NYC", "NYC"),))
    rows = _lines(_file(decisions, day))
    assert result.appended == 1
    assert _file(decisions, day).read_bytes().startswith(before)
    assert [r["settlement_tmax_f"] for r in rows] == [84, 85]
    assert rows[1]["ts_ns"] > rows[0]["ts_ns"]
    assert rows[1]["raw_sha256"] == _sha("corrected")


def test_settlement_basis_is_venue_owned(tmp_path: Path) -> None:
    assert cs.VENUE_BASIS[VENUE] == "NWS_CLI"
    _seed_window(tmp_path / "catalog", cities=("NYC",))
    _, _, decisions = _run(
        tmp_path, sites=(cs.SettlementSite("NYC", "NYC"),), basis_by_venue={VENUE: "OTHER_BASIS"}
    )
    rows = _lines(_file(decisions, TODAY - dt.timedelta(days=1)))
    assert {r["basis"] for r in rows} == {"OTHER_BASIS"}


def test_a_venue_with_no_basis_is_refused_not_defaulted(tmp_path: Path) -> None:
    with pytest.raises(cs.UnknownVenueBasis):
        _run(tmp_path, basis_by_venue={"kalshi": "TWC"})


def test_non_final_and_null_tmax_records_are_pending_not_written(tmp_path: Path) -> None:
    base = tmp_path / "catalog"
    day = TODAY - dt.timedelta(days=1)
    _seed(base, "NYC", _climate_day("NYC", day, is_final=False))
    _seed(base, "MDW", _climate_day("MDW", day, tmax=None, tmax_flag="M"))
    result, offers, decisions = _run(tmp_path)
    assert result.appended == 0 and result.pending == 2 + 2 * 6
    assert not list(decisions.glob("settlement_*.jsonl"))
    assert offers.calls == [] and result.exit_code == 0


def test_a_station_day_with_no_record_is_pending_without_alert(tmp_path: Path) -> None:
    _seed(tmp_path / "catalog", "NYC", _climate_day("NYC", TODAY - dt.timedelta(days=1)))
    (tmp_path / "catalog" / VENUE / "MDW").mkdir(parents=True)
    result, offers, _ = _run(tmp_path)
    assert result.appended == 1 and offers.calls == [] and result.exit_code == 0


# -- failure: CRITICAL CAPTURE_SETTLEMENT_ERROR, carry on, exit 1 --------------------------------


def test_settlement_read_error_sends_critical_and_exits_nonzero(tmp_path: Path) -> None:
    _seed_window(tmp_path / "catalog")
    boom_day = TODAY - dt.timedelta(days=3)
    real = cs.read_catalog_day

    def reader(base: Path, venue: str, site: cs.SettlementSite, day: dt.date) -> Any:
        if site.city == "NYC" and day == boom_day:
            raise OSError("secret path /x/y leaks here")
        return real(base, venue, site, day)

    result, offers, decisions = _run(tmp_path, read_day=reader)
    assert offers.calls == [
        (
            ERROR_EVENT,
            "CRITICAL",
            f"station=NYC climate_day={boom_day.isoformat()} cause=OSError",
        )
    ]
    assert "secret" not in offers.calls[0][2]
    assert result.exit_code == 1 and not result.delivery_failed
    # every other station-day was still written
    assert result.appended == 13
    rows = _lines(_file(decisions, boom_day))
    assert [r["station"] for r in rows] == ["MDW"]


def test_settlement_failed_delivery_exits_nonzero(tmp_path: Path) -> None:
    _seed(tmp_path / "catalog", "NYC", _climate_day("NYC", TODAY - dt.timedelta(days=1)))
    (tmp_path / "catalog" / VENUE / "MDW").mkdir(parents=True)

    def reader(base: Path, venue: str, site: cs.SettlementSite, day: dt.date) -> Any:
        if site.city == "MDW":
            raise ValueError("bad")
        return cs.read_catalog_day(base, venue, site, day)

    result, offers, decisions = _run(tmp_path, Offers(accepted=False), read_day=reader)
    assert result.delivery_failed and result.exit_code == 1
    assert len(offers.calls) == 7
    assert _file(decisions, TODAY - dt.timedelta(days=1)).exists()  # durable work first


def test_an_offer_that_raises_counts_as_failed_delivery(tmp_path: Path) -> None:
    def reader(*_: Any) -> Any:
        raise RuntimeError("x")

    def offer(event: str, severity: str, detail: str) -> bool:
        raise ConnectionError("outbox down")

    result, _, _ = _run(tmp_path, sites=(SITES[0],), read_day=reader)  # default offer works
    assert result.exit_code == 1
    decisions = tmp_path / "decisions"
    again = cs.run_settlement(
        venue=VENUE,
        today=TODAY,
        decisions_dir=decisions,
        catalog_base=tmp_path / "catalog",
        sites=(SITES[0],),
        offer=offer,
        read_day=reader,
    )
    assert again.delivery_failed and again.exit_code == 1


def test_a_missing_station_catalog_is_an_error_and_is_never_created(tmp_path: Path) -> None:
    _seed(tmp_path / "catalog", "NYC", _climate_day("NYC", TODAY - dt.timedelta(days=1)))
    result, offers, _ = _run(tmp_path)
    assert not (tmp_path / "catalog" / VENUE / "MDW").exists()
    assert result.exit_code == 1
    assert {c[0] for c in offers.calls} == {ERROR_EVENT}
    assert all("station=MDW" in c[2] and "cause=CatalogMissing" in c[2] for c in offers.calls)
    assert len(offers.calls) == 7


def test_a_corrupt_existing_file_is_an_error_and_is_left_untouched(tmp_path: Path) -> None:
    _seed_window(tmp_path / "catalog")
    day = TODAY - dt.timedelta(days=1)
    decisions = tmp_path / "decisions"
    decisions.mkdir(mode=0o700)
    _file(decisions, day).write_text('{"station": "NYC"}\nnot json\n')
    _file(decisions, day).chmod(0o600)
    before = _file(decisions, day).read_bytes()
    result, offers, _ = _run(tmp_path)
    assert _file(decisions, day).read_bytes() == before
    assert result.exit_code == 1
    assert sorted(c[2] for c in offers.calls) == [
        f"station=MDW climate_day={day.isoformat()} cause=SettlementFileCorrupt",
        f"station=NYC climate_day={day.isoformat()} cause=SettlementFileCorrupt",
    ]
    assert result.appended == 12  # the other six days still landed


def test_a_symlinked_settlement_file_is_refused(tmp_path: Path) -> None:
    _seed_window(tmp_path / "catalog", cities=("NYC",))
    day = TODAY - dt.timedelta(days=1)
    decisions = tmp_path / "decisions"
    decisions.mkdir(mode=0o700)
    target = tmp_path / "elsewhere.jsonl"
    target.write_text("")
    _file(decisions, day).symlink_to(target)
    result, offers, _ = _run(tmp_path, sites=(SITES[0],))
    assert target.read_text() == ""
    assert result.exit_code == 1 and len(offers.calls) == 1


def test_a_write_failure_alerts_each_affected_station_day(tmp_path: Path) -> None:
    _seed(tmp_path / "catalog", "NYC", _climate_day("NYC", TODAY - dt.timedelta(days=1)))
    _seed(tmp_path / "catalog", "MDW", _climate_day("MDW", TODAY - dt.timedelta(days=1)))

    def failing(path: Path, data: bytes, *, root: Path, mode: int) -> None:
        raise PermissionError("no")

    result, offers, decisions = _run(tmp_path, replace=failing)
    assert result.appended == 0 and result.exit_code == 1
    assert sorted(c[2].split()[0] for c in offers.calls) == ["station=MDW", "station=NYC"]
    assert all(c[2].endswith("cause=PermissionError") for c in offers.calls)
    assert not list(decisions.glob("settlement_*.jsonl"))


# -- files, modes, lock --------------------------------------------------------------------------


def test_files_are_private_and_no_temp_file_remains(tmp_path: Path) -> None:
    _seed_window(tmp_path / "catalog")
    _, _, decisions = _run(tmp_path)
    names = {p.name for p in decisions.iterdir()}
    assert all(n.startswith("settlement_") or n == cs.LOCK_FILE for n in names), names
    for path in decisions.glob("settlement_*.jsonl"):
        assert path.stat().st_mode & 0o777 == 0o600


def test_lock_file_name_does_not_match_the_retention_glob() -> None:
    assert not cs.LOCK_FILE.startswith(("settlement_", "capture_"))


def test_a_second_run_cannot_take_the_lock_and_writes_nothing(tmp_path: Path) -> None:
    _seed_window(tmp_path / "catalog")
    decisions = tmp_path / "decisions"
    decisions.mkdir(mode=0o700)
    with cs.settlement_lock(decisions):
        with pytest.raises(cs.SettlementLockBusy):
            cs.run_settlement(
                venue=VENUE,
                today=TODAY,
                decisions_dir=decisions,
                catalog_base=tmp_path / "catalog",
                sites=SITES,
                offer=Offers(),
            )
        assert not list(decisions.glob("settlement_*.jsonl"))
    result, _, _ = _run(tmp_path)  # released
    assert result.appended == 14


def test_the_lock_is_released_after_an_error(tmp_path: Path) -> None:
    def reader(*_: Any) -> Any:
        raise RuntimeError("x")

    _run(tmp_path, read_day=reader)
    with cs.settlement_lock(tmp_path / "decisions"):
        pass


# -- sole writer ---------------------------------------------------------------------------------


def test_settlement_writer_is_sole_writer() -> None:
    rows = {r.path: r for r in AUTONOMY_FILE_WRITERS}
    row = rows["<decisions_dir>/settlement_<climate_day>.jsonl"]
    assert "capture_settlement" in row.writers
    assert row.mechanism == "replace_atomic"
    authority = {r.module: r for r in AUT1_WRITE_AUTHORITY}
    mine = authority["breezy.analysis.capture_settlement"]
    assert mine.writes == ("_acquire_lock",)
    assert mine.write_imports == frozenset({"replace_atomic"})
    cli_row = authority["breezy.analysis.capture_settlement_cli"]
    assert cli_row.writes == () and cli_row.write_imports == frozenset()
    names = {p.name for p in aut1_files()}
    assert {"capture_settlement.py", "capture_settlement_cli.py"} <= names
    assert lint_files(aut1_files()) == []


# -- registry sites ------------------------------------------------------------------------------


def test_venue_sites_come_from_the_registry_cli_locations() -> None:
    from breezy.registry.sites import default_registry

    registry = default_registry()
    sites = cs.venue_sites(registry, VENUE)
    assert sites
    for site in sites:
        assert site.cli_location == registry.settlement_site(VENUE, site.city).cli_location
    assert {s.city for s in sites} == {c for v, c in registry.pairs() if v == VENUE}


# -- CLI -----------------------------------------------------------------------------------------


def _argv(tmp_path: Path, *extra: str) -> list[str]:
    decisions = tmp_path / "decisions"
    decisions.mkdir(exist_ok=True, mode=0o700)
    return [
        "--venue",
        VENUE,
        "--decisions-dir",
        str(decisions),
        "--catalog-base",
        str(tmp_path / "catalog"),
        *extra,
    ]


def _clock(hour: int, minute: int = 0) -> Any:
    ns = int(dt.datetime(2026, 10, 4, hour, minute, tzinfo=dt.UTC).timestamp() * NS)
    return lambda: ns


def test_cli_writes_and_exits_zero(tmp_path: Path) -> None:
    _seed_window(tmp_path / "catalog")
    offers = Offers()
    code = cli.main(_argv(tmp_path), offer=offers, clock=_clock(13, 35), sites=SITES)
    assert code == 0 and offers.calls == []
    assert len(list((tmp_path / "decisions").glob("settlement_*.jsonl"))) == 7


def test_cli_exits_one_on_error_even_with_delivered_alert(tmp_path: Path) -> None:
    _seed(tmp_path / "catalog", "NYC", _climate_day("NYC", TODAY - dt.timedelta(days=1)))
    offers = Offers()
    code = cli.main(_argv(tmp_path), offer=offers, clock=_clock(13, 35), sites=SITES)
    assert code == 1 and offers.calls


def test_cli_exits_one_when_the_lock_is_busy(tmp_path: Path) -> None:
    decisions = tmp_path / "decisions"
    decisions.mkdir(mode=0o700)
    with cs.settlement_lock(decisions):
        code = cli.main(_argv(tmp_path), offer=Offers(), clock=_clock(13, 35), sites=SITES)
    assert code == 1


@pytest.mark.parametrize(("hour", "minute"), [(16, 30), (16, 55), (17, 9), (16, 25), (12, 31)])
def test_cli_defers_inside_launch_window(tmp_path: Path, hour: int, minute: int) -> None:
    """A start whose worst-case span (flock wait + start timeout) meets the launch window defers."""
    _seed_window(tmp_path / "catalog")
    code = cli.main(_argv(tmp_path), offer=Offers(), clock=_clock(hour, minute), sites=SITES)
    deferred = (hour, minute) != (12, 31)
    assert code == 0
    assert bool(list((tmp_path / "decisions").glob("settlement_*"))) is (not deferred)


def test_cli_does_not_defer_at_the_documented_slot_or_after_the_window(tmp_path: Path) -> None:
    _seed_window(tmp_path / "catalog")
    assert cli.main(_argv(tmp_path), offer=Offers(), clock=_clock(17, 10), sites=SITES) == 0
    assert list((tmp_path / "decisions").glob("settlement_*"))


def test_cli_requires_a_catalog_base(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BREEZY_CATALOG_BASE", raising=False)
    argv = ["--decisions-dir", str(tmp_path)]
    with pytest.raises(SystemExit) as exc:
        cli.main(argv, offer=Offers(), clock=_clock(13, 35))
    assert exc.value.code == 2


def test_cli_reads_the_catalog_base_from_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_window(tmp_path / "catalog")
    monkeypatch.setenv("BREEZY_CATALOG_BASE", str(tmp_path / "catalog"))
    decisions = tmp_path / "decisions"
    decisions.mkdir(mode=0o700)
    code = cli.main(
        ["--decisions-dir", str(decisions)], offer=Offers(), clock=_clock(13, 35), sites=SITES
    )
    assert code == 0 and list(decisions.glob("settlement_*"))


def test_the_default_offer_is_undeliverable_so_an_error_still_exits_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = cli.main(_argv(tmp_path), clock=_clock(13, 35), sites=SITES)
    assert code == 1  # no catalog at all: every station-day errors, delivery is undeliverable
    assert ERROR_EVENT in capsys.readouterr().err


def test_the_cli_entry_points_import_no_venue_adapter_and_make_no_network_call() -> None:
    code = (
        "import sys\n"
        "import breezy.analysis.capture_settlement_cli, breezy.analysis.capture_settlement\n"
        "bad = sorted(m for m in sys.modules if m.startswith('breezy.adapters')"
        " or m in ('httpx', 'requests', 'aiohttp', 'urllib3'))\n"
        "print(bad)\n"
        "raise SystemExit(1 if bad else 0)\n"
    )
    env = {**os.environ, "PYTHONPATH": str(Path(cs.__file__).parents[2])}
    done = subprocess.run(
        [sys.executable, "-c", code], env=env, capture_output=True, text=True, check=False
    )
    assert done.returncode == 0, done.stdout + done.stderr


def test_the_cli_never_writes_outside_the_decisions_dir(tmp_path: Path) -> None:
    _seed_window(tmp_path / "catalog")
    snapshot = sorted(str(p.relative_to(tmp_path)) for p in (tmp_path / "catalog").rglob("*"))
    cli.main(_argv(tmp_path), offer=Offers(), clock=_clock(13, 35), sites=SITES)
    after = sorted(str(p.relative_to(tmp_path)) for p in (tmp_path / "catalog").rglob("*"))
    assert snapshot == after
