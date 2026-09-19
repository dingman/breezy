"""Unit tests for the IEM 1-minute ASOS backfill CLI (FC-0a-2 / WP-3).

Every test runs against fakes. ``tests/conftest.py`` blocks real sockets for
anything not marked ``live``/``allow_socket``, and nothing here carries
either marker: no test in this module performs, or may perform, network I/O.
"""

from __future__ import annotations

import gc
import importlib.util
import sys
import weakref
from pathlib import Path
from types import ModuleType
from typing import Any, Final
from urllib.parse import parse_qs, urlsplit

import pytest

from breezy.persistence.archive_cache import (
    IEM_ASOS_1MIN_SOURCE,
    ArchiveCache,
    ArchiveCachePathError,
)

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
CLI_PATH: Final[Path] = REPO_ROOT / "scripts/archive/iem_asos1min_backfill.py"
TEST_UA: Final[str] = "breezy-asos1min-backfill-ua-token-TESTONLY"


def _load_script(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"breezy_script_{path.stem}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def cli() -> ModuleType:
    return _load_script(CLI_PATH)


class _Clock:
    """Monotonic fake nanosecond clock; never the wall clock."""

    def __init__(self, start_ns: int = 1_609_459_200_000_000_000) -> None:
        self.now_ns = start_ns

    def __call__(self) -> int:
        return self.now_ns

    def timestamp_ns(self) -> int:
        return self.now_ns


def _durable_root(home: Path) -> Path:
    return home / ".local/share/breezy/archive/iem-asos-1min"


def _csv(station: str, year: int, rows: int = 3) -> bytes:
    head = "station,valid(UTC),tmpf,dwpf\n"
    body = "".join(
        f"{station},{year}-01-01 00:{minute:02d},32.0,30.0\n" for minute in range(rows)
    )
    return (head + body).encode()


# --------------------------------------------------------------------------
# 1. Named pacer, >= 1 request/second, asserted with a fake clock.
# --------------------------------------------------------------------------


def test_the_pacer_is_a_named_object_whose_interval_is_at_least_one_second(
    cli: ModuleType,
) -> None:
    assert cli.ASOS1MIN_MIN_INTERVAL_NS >= 1_000_000_000
    pacer = cli.build_pacer(clock=_Clock(), sleeper=None)
    assert type(pacer).__name__ == "IemPacer"


@pytest.mark.parametrize(
    ("elapsed_ns", "expected_sleeps"),
    [
        (0, [1.0]),
        (250_000_000, [0.75]),
        (1_000_000_000, []),
        (5_000_000_000, []),
    ],
)
def test_the_pacer_waits_out_the_residual_second_on_a_fake_clock(
    cli: ModuleType, elapsed_ns: int, expected_sleeps: list[float]
) -> None:
    import asyncio

    clock = _Clock()
    slept: list[float] = []

    async def sleeper(seconds: float) -> None:
        slept.append(round(seconds, 6))

    pacer = cli.build_pacer(clock=clock, sleeper=sleeper)

    async def drive() -> None:
        await pacer.wait()
        clock.now_ns += elapsed_ns
        await pacer.wait()

    asyncio.run(drive())
    assert slept == expected_sleeps


# --------------------------------------------------------------------------
# 5. Root safety: durable layout, disjointness BEFORE any mkdir.
# --------------------------------------------------------------------------


def test_the_default_cache_root_is_the_durable_layout_and_never_tmp(
    cli: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from breezy.persistence.archive_layout import DEFAULT_IEM_CACHE_DIR

    assert cli.default_cache_root() == DEFAULT_IEM_CACHE_DIR
    assert cli.default_cache_root().parts[-5:] == cli.DURABLE_ROOT_TAIL

    monkeypatch.setenv("HOME", str(tmp_path))
    assert cli.default_cache_root() == _durable_root(tmp_path)


@pytest.mark.parametrize(
    "bad",
    ["/tmp/breezy-archive", "/tmp", "/var/tmp/iem-asos-1min", "/dev/shm/iem-asos-1min"],
)
def test_a_volatile_cache_root_is_refused(cli: ModuleType, bad: str) -> None:
    with pytest.raises(cli.CacheRootPolicyError):
        cli.assert_durable_cache_root(Path(bad))


def test_the_disjointness_assertion_runs_before_any_mkdir(
    cli: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = _durable_root(tmp_path)
    calls: list[Path] = []

    def refusing(path: Path) -> None:
        calls.append(Path(path))
        raise ArchiveCachePathError("refused for the test")

    monkeypatch.setattr(cli, "assert_cache_root_disjoint_from_backup", refusing)

    with pytest.raises(ArchiveCachePathError):
        cli.prepare_cache_root(root)

    assert calls == [root]
    assert not root.exists(), "the root was created despite the startup refusal"


def test_prepare_cache_root_creates_the_root_when_the_policy_passes(
    cli: ModuleType, tmp_path: Path
) -> None:
    root = _durable_root(tmp_path)
    assert cli.prepare_cache_root(root) == root
    assert root.is_dir()


def test_a_root_containing_the_settlement_backup_is_refused(cli: ModuleType) -> None:
    from breezy.persistence.archive_layout import BACKED_UP_ARCHIVE_DATASET_DIR

    with pytest.raises(ArchiveCachePathError):
        cli.prepare_cache_root(BACKED_UP_ARCHIVE_DATASET_DIR.parent)


# --------------------------------------------------------------------------
# 6. L-13: cadence is carried, and mixing without a downsample is refused.
# --------------------------------------------------------------------------


def test_each_cadence_maps_to_its_own_product_so_a_cache_slot_cannot_mix(
    cli: ModuleType,
) -> None:
    assert cli.CADENCE_PRODUCTS["1min"] == "asos-1min"
    assert cli.CADENCE_PRODUCTS["5min"] == "asos-5min"
    assert len(set(cli.CADENCE_PRODUCTS.values())) == len(cli.CADENCE_PRODUCTS)

    one = cli.request_for(cli.StationYear("KMIA", 2021, "1min"))
    five = cli.request_for(cli.StationYear("KMIA", 2021, "5min"))

    assert one.product == "asos-1min"
    assert five.product == "asos-5min"
    assert one.cache_key() != five.cache_key()
    assert one.source == five.source == IEM_ASOS_1MIN_SOURCE


def test_the_one_minute_request_is_the_shared_factory_verbatim(cli: ModuleType) -> None:
    from breezy.persistence.archive_request import iem_asos_1min_request

    assert cli.request_for(cli.StationYear("KSFO", 2023, "1min")) == iem_asos_1min_request(
        "KSFO", 2023
    )


def test_mixing_cadences_without_a_downsample_is_refused_not_averaged(
    cli: ModuleType,
) -> None:
    assert cli.refuse_cadence_mix(["1min", "1min"]) == "1min"
    with pytest.raises(cli.CadenceMixError) as excinfo:
        cli.refuse_cadence_mix(["1min", "5min"])
    assert "downsample" in str(excinfo.value).lower()
    with pytest.raises(cli.CadenceMixError):
        cli.refuse_cadence_mix([])


def test_an_unknown_cadence_is_refused_rather_than_sanitised(cli: ModuleType) -> None:
    with pytest.raises(ValueError):
        cli.request_for(cli.StationYear("KMIA", 2021, "3min"))


def test_every_outcome_names_its_cadence(cli: ModuleType, tmp_path: Path) -> None:
    cache = ArchiveCache(
        root=_durable_root(tmp_path),
        fetch=lambda request: _csv(request.station, 2021),
        clock=_Clock(),
    )
    report = cli.run_backfill(
        cache=cache,
        plan=cli.build_plan(stations=("KMIA",), first_year=2021, through_year=2021),
        progress=lambda line: None,
    )
    assert [outcome.cadence for outcome in report.outcomes] == ["1min"]
    assert report.cadence == "1min"


# --------------------------------------------------------------------------
# Plan construction: stations, years, current-year policy.
# --------------------------------------------------------------------------


def test_the_plan_is_four_stations_by_complete_years_from_2021(cli: ModuleType) -> None:
    assert cli.STATIONS == ("KLAX", "KMDW", "KMIA", "KSFO")
    assert cli.FIRST_YEAR == 2021

    plan = cli.build_plan(first_year=2021, through_year=2025)
    assert len(plan) == 20
    assert {item.station for item in plan} == set(cli.STATIONS)
    assert sorted({item.year for item in plan}) == [2021, 2022, 2023, 2024, 2025]


def test_the_current_incomplete_year_is_excluded_by_default(cli: ModuleType) -> None:
    clock = _Clock(start_ns=1_789_000_000 * 1_000_000_000)  # 2026-09-xx UTC
    assert cli.last_complete_year(clock) == 2025


# --------------------------------------------------------------------------
# 3. Resumability / idempotence, and 8. dry run makes zero requests.
# --------------------------------------------------------------------------


def test_a_rerun_after_a_complete_run_issues_zero_requests(
    cli: ModuleType, tmp_path: Path
) -> None:
    root = _durable_root(tmp_path)
    fetched: list[str] = []

    def fetch(request: Any) -> bytes:
        fetched.append(request.station)
        return _csv(request.station, 2021)

    plan = cli.build_plan(stations=("KMIA", "KSFO"), first_year=2021, through_year=2022)

    first = cli.run_backfill(
        cache=ArchiveCache(root=root, fetch=fetch, clock=_Clock()),
        plan=plan,
        progress=lambda line: None,
    )
    assert first.fetched == 4
    assert len(fetched) == 4

    second = cli.run_backfill(
        cache=ArchiveCache(root=root, fetch=fetch, clock=_Clock()),
        plan=plan,
        progress=lambda line: None,
    )
    assert len(fetched) == 4, "a re-run issued a request for an already-covered station-year"
    assert second.fetched == 0
    assert second.skipped == 4
    assert second.failed == ()


def test_a_dry_run_reports_what_would_be_fetched_and_makes_no_request(
    cli: ModuleType, tmp_path: Path
) -> None:
    def exploding_fetch(request: Any) -> bytes:
        raise AssertionError("a dry run must never fetch")

    cache = ArchiveCache(
        root=_durable_root(tmp_path), fetch=exploding_fetch, clock=_Clock()
    )
    plan = cli.build_plan(stations=("KMIA",), first_year=2021, through_year=2023)
    report = cli.run_backfill(
        cache=cache, plan=plan, progress=lambda line: None, dry_run=True
    )

    assert report.dry_run is True
    assert report.fetched == 0
    assert {outcome.status for outcome in report.outcomes} == {"WOULD_FETCH"}
    assert [(o.station, o.year) for o in report.outcomes] == [
        ("KMIA", 2021),
        ("KMIA", 2022),
        ("KMIA", 2023),
    ]


def test_a_dry_run_after_a_partial_run_names_only_the_missing_station_years(
    cli: ModuleType, tmp_path: Path
) -> None:
    root = _durable_root(tmp_path)
    cli.run_backfill(
        cache=ArchiveCache(
            root=root, fetch=lambda r: _csv(r.station, 2021), clock=_Clock()
        ),
        plan=cli.build_plan(stations=("KMIA",), first_year=2021, through_year=2021),
        progress=lambda line: None,
    )

    report = cli.run_backfill(
        cache=ArchiveCache(
            root=root,
            fetch=lambda r: (_ for _ in ()).throw(AssertionError("no fetch")),
            clock=_Clock(),
        ),
        plan=cli.build_plan(stations=("KMIA",), first_year=2021, through_year=2022),
        progress=lambda line: None,
        dry_run=True,
    )
    statuses = {(o.year, o.status) for o in report.outcomes}
    assert statuses == {(2021, "SKIPPED"), (2022, "WOULD_FETCH")}


# --------------------------------------------------------------------------
# 2. Process-then-discard: one station-year of payload alive at a time.
# --------------------------------------------------------------------------


class _Sentinel:
    """A weak-referenceable stand-in for a payload's lifetime."""


class _TrackedPayload(bytes):
    """A payload whose lifetime is observable.

    ``bytes`` itself cannot be weak-referenced, and neither can a
    variable-size subclass of it -- but a subclass carries a ``__dict__``, so
    an attached sentinel dies exactly when the payload is released. Tracking
    the sentinel therefore tracks the payload.
    """

    sentinel: _Sentinel


def _tracked(body: bytes) -> tuple[_TrackedPayload, weakref.ref[_Sentinel]]:
    payload = _TrackedPayload(body)
    sentinel = _Sentinel()
    payload.sentinel = sentinel
    return payload, weakref.ref(sentinel)


def test_no_more_than_one_station_year_payload_is_held_at_a_time(
    cli: ModuleType, tmp_path: Path
) -> None:
    alive: list[weakref.ref[_Sentinel]] = []
    live_counts: list[int] = []

    def fetch(request: Any) -> bytes:
        gc.collect()
        live_counts.append(sum(1 for ref in alive if ref() is not None))
        payload, ref = _tracked(_csv(request.station, 2021, rows=64))
        alive.append(ref)
        return payload

    cache = ArchiveCache(root=_durable_root(tmp_path), fetch=fetch, clock=_Clock())
    report = cli.run_backfill(
        cache=cache,
        plan=cli.build_plan(stations=cli.STATIONS, first_year=2021, through_year=2022),
        progress=lambda line: None,
    )

    assert report.fetched == 8
    assert live_counts == [0] * 8, (
        f"a previous station-year payload was still alive: {live_counts}"
    )
    gc.collect()
    assert [ref() for ref in alive] == [None] * 8


def test_the_report_carries_statistics_only_and_never_a_payload(
    cli: ModuleType, tmp_path: Path
) -> None:
    cache = ArchiveCache(
        root=_durable_root(tmp_path),
        fetch=lambda request: _csv(request.station, 2021, rows=5),
        clock=_Clock(),
    )
    report = cli.run_backfill(
        cache=cache,
        plan=cli.build_plan(stations=("KMIA",), first_year=2021, through_year=2021),
        progress=lambda line: None,
    )
    outcome = report.outcomes[0]
    assert outcome.rows == 5
    assert outcome.bytes > 0
    assert len(outcome.sha256) == 64
    for field in outcome.__dataclass_fields__:
        assert not isinstance(getattr(outcome, field), bytes | bytearray | memoryview)


# --------------------------------------------------------------------------
# 7. Progress + failure reporting: a failed station-year is NAMED.
# --------------------------------------------------------------------------


def test_a_failed_station_year_is_named_and_never_swallowed(
    cli: ModuleType, tmp_path: Path
) -> None:
    def fetch(request: Any) -> bytes:
        if request.station == "KSFO":
            raise RuntimeError("upstream 500")
        return _csv(request.station, 2021)

    cache = ArchiveCache(root=_durable_root(tmp_path), fetch=fetch, clock=_Clock())
    lines: list[str] = []
    report = cli.run_backfill(
        cache=cache,
        plan=cli.build_plan(stations=("KMIA", "KSFO"), first_year=2021, through_year=2021),
        progress=lines.append,
    )

    assert report.fetched == 1
    assert [(item.station, item.year) for item in report.failed] == [("KSFO", 2021)]
    summary = cli.render_summary(report)
    assert "KSFO 2021" in summary
    assert "upstream 500" in summary
    assert "FAILED" in summary
    assert any("KMIA 2021" in line for line in lines), "no per-station-year progress line"
    assert any("KSFO 2021" in line for line in lines)


def test_a_failure_does_not_abort_the_remaining_station_years(
    cli: ModuleType, tmp_path: Path
) -> None:
    def fetch(request: Any) -> bytes:
        if request.station == "KLAX":
            raise RuntimeError("boom")
        return _csv(request.station, 2021)

    cache = ArchiveCache(root=_durable_root(tmp_path), fetch=fetch, clock=_Clock())
    report = cli.run_backfill(
        cache=cache,
        plan=cli.build_plan(stations=cli.STATIONS, first_year=2021, through_year=2021),
        progress=lambda line: None,
    )
    assert report.fetched == 3
    assert len(report.failed) == 1


# --------------------------------------------------------------------------
# Payload validation: an empty or error body is NOT coverage.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"   \n\n",
        b"station,valid(UTC),tmpf\n",
        b"<html><body>Service unavailable</body></html>",
        b"ERROR: no data found",
    ],
)
def test_an_empty_or_error_body_is_refused_before_it_can_become_coverage(
    cli: ModuleType, body: bytes
) -> None:
    with pytest.raises(cli.EmptyPayloadError):
        cli.validate_payload(body, station="KMIA", cadence="1min")


def test_a_refused_body_leaves_the_cache_without_coverage(
    cli: ModuleType, tmp_path: Path
) -> None:
    root = _durable_root(tmp_path)

    def fetch(request: Any) -> bytes:
        cli.validate_payload(b"ERROR: no data found", station=request.station, cadence="1min")
        raise AssertionError("unreachable")

    cache = ArchiveCache(root=root, fetch=fetch, clock=_Clock())
    plan = cli.build_plan(stations=("KMIA",), first_year=2021, through_year=2021)
    report = cli.run_backfill(cache=cache, plan=plan, progress=lambda line: None)

    assert report.fetched == 0
    assert len(report.failed) == 1
    assert cache.missing(cli.request_for(plan[0])) is True
    assert list(root.rglob("*.csv")) == []


def test_a_good_body_validates_and_reports_its_row_count(cli: ModuleType) -> None:
    assert cli.validate_payload(_csv("KMIA", 2021, rows=7), station="KMIA", cadence="1min") == 7


# --------------------------------------------------------------------------
# Transport: URL grammar, closed station set, cadence in the query.
# --------------------------------------------------------------------------


def _transport(cli: ModuleType) -> Any:
    from breezy.ingest.probe_transport import RequestBudget

    clock = _Clock()
    return cli.Asos1MinTransport(
        budget=RequestBudget(limit=4),
        pacer=cli.build_pacer(clock=clock, sleeper=None),
        user_agent=TEST_UA,
        clock=clock,
        check_proxy_env=False,
    )


def test_the_url_names_the_cadence_the_product_claims(cli: ModuleType) -> None:
    url = _transport(cli)._asos1min_url("KMIA", "1min", "2021-01-01T00:00Z", "2022-01-01T00:00Z")
    parts = urlsplit(url)
    query = parse_qs(parts.query)

    assert parts.scheme == "https"
    assert parts.path == cli.IEM_ASOS1MIN_PATH
    # The IEM identifier, not the ICAO call sign the plan speaks (VERIFIED).
    assert query["station"] == ["MIA"]
    assert query["sample"] == ["1min"]
    assert query["tz"] == ["UTC"]
    assert "tmpf" in query["vars"]
    assert cli.CADENCE_PRODUCTS[query["sample"][0]] == "asos-1min"


def test_the_transport_refuses_an_unlisted_station_or_cadence(cli: ModuleType) -> None:
    transport = _transport(cli)
    with pytest.raises(ValueError):
        transport._asos1min_url("KJFK", "1min", "2021-01-01T00:00Z", "2022-01-01T00:00Z")
    with pytest.raises(ValueError):
        transport._asos1min_url("KMIA", "3min", "2021-01-01T00:00Z", "2022-01-01T00:00Z")
    with pytest.raises(ValueError):
        transport._asos1min_url("KMIA", "1min", "2021-01-01", "2022-01-01T00:00Z")


def test_the_transport_is_aimed_only_at_the_iem_origin(cli: ModuleType) -> None:
    from breezy.ingest.probe_transport import RequestBudget

    clock = _Clock()
    with pytest.raises(ValueError):
        cli.Asos1MinTransport(
            budget=RequestBudget(limit=1),
            pacer=cli.build_pacer(clock=clock, sleeper=None),
            user_agent=TEST_UA,
            clock=clock,
            check_proxy_env=False,
            allowed_hosts=frozenset({"example.invalid"}),
            base_url="https://example.invalid",
        )


# --------------------------------------------------------------------------
# main(): refusals, exit codes, dry run.
# --------------------------------------------------------------------------


def test_main_refuses_a_real_run_without_the_live_unlock(
    cli: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: Any
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv(cli.LIVE_ENV_VAR, raising=False)
    assert cli.main(["--apply"]) == 2
    assert cli.LIVE_ENV_VAR in capsys.readouterr().err
    assert not _durable_root(tmp_path).exists()


def test_main_refuses_a_real_run_without_apply(
    cli: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: Any
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv(cli.LIVE_ENV_VAR, "1")
    monkeypatch.setenv(cli.USER_AGENT_ENV_VAR, TEST_UA)
    assert cli.main([]) == 2
    assert "--apply" in capsys.readouterr().err


def test_main_refuses_a_real_run_without_a_contact_user_agent(
    cli: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: Any
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv(cli.LIVE_ENV_VAR, "1")
    monkeypatch.delenv(cli.USER_AGENT_ENV_VAR, raising=False)
    assert cli.main(["--apply"]) == 2
    assert cli.USER_AGENT_ENV_VAR in capsys.readouterr().err


def test_main_dry_run_needs_no_unlock_and_lists_the_station_years(
    cli: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: Any
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv(cli.LIVE_ENV_VAR, raising=False)

    exit_code = cli.main(["--dry-run", "--first-year", "2021", "--through-year", "2022"])
    err = capsys.readouterr().err

    assert exit_code == 0
    assert "WOULD_FETCH" in err
    assert "KMIA 2021" in err
    assert "8" in err
    assert _durable_root(tmp_path).is_dir()


def test_main_refuses_a_volatile_cache_root_before_creating_anything(
    cli: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    target = Path("/tmp/breezy-asos1min-should-not-exist")
    assert cli.main(["--dry-run", "--cache-root", str(target)]) == 2
    assert "durable" in capsys.readouterr().err.lower()
    assert not target.exists()


# --------------------------------------------------------------------------
# VERIFIED grammar (live, 2026-09-19). The fixture beside these tests is the
# byte-for-byte body of the request that succeeded, so a future silent change
# to the query shape -- or to the station identifier the service accepts --
# fails here instead of at the next operator backfill.
# --------------------------------------------------------------------------

VERIFIED_FIXTURE: Final[Path] = (
    REPO_ROOT / "tests/fixtures/iem/asos1min_MIA_2021-06-15T12Z_10min.csv"
)
#: The exact query the live service answered 200 for. `station` is the 3-letter
#: IEM/FAA identifier: the 4-letter ICAO form is rejected 422 "Unknown station
#: provided: KMIA".
VERIFIED_QUERY: Final[dict[str, list[str]]] = {
    "station": ["MIA"],
    "vars": ["tmpf", "dwpf"],
    "sample": ["1min"],
    "sts": ["2021-06-15T12:00Z"],
    "ets": ["2021-06-15T12:10Z"],
    "tz": ["UTC"],
    "format": ["comma"],
    "what": ["download"],
}


def test_the_url_reproduces_the_verified_live_request_exactly(cli: ModuleType) -> None:
    url = _transport(cli)._asos1min_url("KMIA", "1min", "2021-06-15T12:00Z", "2021-06-15T12:10Z")
    parts = urlsplit(url)

    assert parts.scheme == "https"
    assert parts.netloc == "mesonet.agron.iastate.edu"
    assert parts.path == "/cgi-bin/request/asos1min.py"
    assert parse_qs(parts.query) == VERIFIED_QUERY


def test_the_url_carries_the_iem_station_id_not_the_icao_call_sign(cli: ModuleType) -> None:
    """The 422 that stalled the first backfill was exactly this substitution."""
    for icao in cli.STATIONS:
        url = _transport(cli)._asos1min_url(icao, "1min", "2021-06-15T12:00Z", "2021-06-15T12:10Z")
        station = parse_qs(urlsplit(url).query)["station"]
        assert station == [cli.IEM_1MIN_STATION_IDS[icao]]
        assert station != [icao]
        assert len(station[0]) == 3


def test_every_backfill_station_has_a_verified_iem_1min_identifier(cli: ModuleType) -> None:
    assert tuple(cli.IEM_1MIN_STATION_IDS) == cli.STATIONS


def test_the_verified_response_body_validates_as_real_coverage(cli: ModuleType) -> None:
    body = VERIFIED_FIXTURE.read_bytes()
    header = body.split(b"\n", 1)[0]

    assert header == b"station,station_name,valid(UTC),tmpf,dwpf"
    assert cli.validate_payload(body, station="KMIA", cadence="1min") == 10
