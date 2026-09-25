"""Unit tests for the IEM MOS (NBS/GFS) backfill CLI (FC-0a-3 / WP-4).

Every test runs against fakes and against CHECKED-IN bodies captured from the
live service. ``tests/conftest.py`` blocks real sockets for anything not
marked ``live``/``allow_socket``, and nothing here carries either marker: no
test in this module performs, or may perform, network I/O.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import gc
import importlib.util
import sys
import weakref
from pathlib import Path
from types import ModuleType
from typing import Any, Final
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from breezy.ingest.http import (
    FetchResult,
    ForbiddenError,
    HttpTransport,
    RateLimitedError,
    ServerError,
    TransportTimeoutError,
)
from breezy.ingest.probe_transport import RequestBudget, RequestBudgetExceededError
from breezy.persistence.archive_cache import (
    IEM_MOS_SOURCE,
    ArchiveCache,
    ArchiveCachePathError,
    iem_asos_1min_request,
    iem_mos_request,
)
from breezy.persistence.archive_request import iem_mos_window_request

_ANALYSIS_DIR: Final[Path] = Path(__file__).resolve().parents[2] / "scripts" / "analysis"
if str(_ANALYSIS_DIR) not in sys.path:
    sys.path.insert(0, str(_ANALYSIS_DIR))

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
CLI_PATH: Final[Path] = REPO_ROOT / "scripts/archive/iem_mos_backfill.py"
FIXTURES: Final[Path] = REPO_ROOT / "tests/fixtures/iem"
TEST_UA: Final[str] = "breezy-mos-backfill-ua-token-TESTONLY"

#: The exact request that answered HTTP 200 with CSV on 2026-09-19. The URL
#: shape is pinned against it so a silent grammar drift fails here rather than
#: in an operator backfill.
VERIFIED_URL: Final[str] = (
    "https://mesonet.agron.iastate.edu/cgi-bin/request/mos.py"
    "?station=KMIA&model=NBS&format=csv"
    "&sts=2021-06-15T00%3A00Z&ets=2021-06-15T23%3A59Z"
)


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


@pytest.fixture(scope="module")
def nbs_day() -> bytes:
    return (FIXTURES / "mos_NBS_KMIA_2021-06-15_1day.csv").read_bytes()


@pytest.fixture(scope="module")
def gfs_day() -> bytes:
    return (FIXTURES / "mos_GFS_KMIA_2021-06-15_1day.csv").read_bytes()


@pytest.fixture(scope="module")
def three_letter_zero_rows() -> bytes:
    return (FIXTURES / "mos_NBS_MIA_2021-06-15_zero_rows.csv").read_bytes()


class _Clock:
    """Monotonic fake nanosecond clock; never the wall clock."""

    def __init__(self, start_ns: int = 1_609_459_200_000_000_000) -> None:
        self.now_ns = start_ns

    def __call__(self) -> int:
        return self.now_ns

    def timestamp_ns(self) -> int:
        return self.now_ns


def _durable_root(home: Path) -> Path:
    return home / ".local/share/breezy/archive/iem-mos"


def _transport(cli: ModuleType, budget_limit: int = 8) -> Any:
    from breezy.ingest.probe_transport import RequestBudget

    clock = _Clock()
    return cli.IemMosBackfillTransport(
        budget=RequestBudget(limit=budget_limit),
        pacer=cli.build_pacer(clock=clock),
        user_agent=TEST_UA,
        clock=clock,
    )


# --------------------------------------------------------------------------
# 1. The URL grammar, pinned against the body the real service returned.
# --------------------------------------------------------------------------


def test_the_url_shape_is_the_one_verified_live(cli: ModuleType) -> None:
    url = _transport(cli)._mos_url("KMIA", "NBS", "2021-06-15T00:00Z", "2021-06-15T23:59Z")

    assert url == VERIFIED_URL


def test_the_station_parameter_is_the_four_letter_icao_not_the_three_letter_id(
    cli: ModuleType,
) -> None:
    """MOS is NOT asos1min: `mos.py` keys on the ICAO call sign.

    A three-letter IEM/FAA id is not an error here -- the service answers
    HTTP 200 with a HEADER ONLY (see the checked-in zero-row body), which is
    the silent shape that would poison the corpus. The identifier therefore
    stays ICAO, and the closed station set refuses anything else.
    """
    url = _transport(cli)._mos_url("KMIA", "NBS", "2021-06-15T00:00Z", "2021-06-15T23:59Z")
    query = parse_qs(urlsplit(url).query)

    assert query["station"] == ["KMIA"]
    assert len(query["station"][0]) == 4
    assert set(query) == {"station", "model", "format", "sts", "ets"}
    assert query["format"] == ["csv"]
    assert urlsplit(url).path == "/cgi-bin/request/mos.py"


def test_a_three_letter_identifier_is_refused_at_the_url_boundary(cli: ModuleType) -> None:
    with pytest.raises(ValueError):
        _transport(cli)._mos_url("MIA", "NBS", "2021-06-15T00:00Z", "2021-06-15T23:59Z")


def test_an_unknown_model_is_refused_rather_than_sanitised(cli: ModuleType) -> None:
    with pytest.raises(ValueError):
        _transport(cli)._mos_url("KMIA", "ECMWF", "2021-06-15T00:00Z", "2021-06-15T23:59Z")


def test_a_malformed_window_bound_is_refused(cli: ModuleType) -> None:
    with pytest.raises(ValueError):
        _transport(cli)._mos_url("KMIA", "NBS", "2021-06-15", "2021-06-15T23:59Z")


# --------------------------------------------------------------------------
# 2. Payload validation against the REAL bodies.
# --------------------------------------------------------------------------


def test_the_real_nbs_body_validates_and_counts_its_data_rows(
    cli: ModuleType, nbs_day: bytes
) -> None:
    rows = cli.validate_payload(nbs_day, station="KMIA", model="NBS")

    assert rows == len(nbs_day.decode().strip().splitlines()) - 1
    assert rows > 0


def test_a_header_only_two_hundred_is_a_failure_not_coverage(
    cli: ModuleType, three_letter_zero_rows: bytes
) -> None:
    """The exact body a three-letter station id returned: HTTP 200, no rows."""
    with pytest.raises(cli.EmptyPayloadError):
        cli.validate_payload(three_letter_zero_rows, station="KMIA", model="NBS")


def test_a_gfs_body_may_never_be_committed_into_an_nbs_slot(
    cli: ModuleType, gfs_day: bytes
) -> None:
    """L-13: model identity is checked in the PAYLOAD, not just in the key."""
    with pytest.raises(cli.ModelMismatchError):
        cli.validate_payload(gfs_day, model="NBS", station="KMIA")

    assert cli.validate_payload(gfs_day, model="GFS", station="KMIA") > 0


def test_a_body_for_the_wrong_station_is_refused(cli: ModuleType, nbs_day: bytes) -> None:
    with pytest.raises(cli.StationMismatchError):
        cli.validate_payload(nbs_day, station="KSFO", model="NBS")


def test_markup_and_empty_bodies_are_refused(cli: ModuleType) -> None:
    with pytest.raises(cli.EmptyPayloadError):
        cli.validate_payload(b"<html>nope</html>", station="KMIA", model="NBS")
    with pytest.raises(cli.EmptyPayloadError):
        cli.validate_payload(b"   ", station="KMIA", model="NBS")


# --------------------------------------------------------------------------
# 3. Cache identity: MOS can never collide with ASOS, NBS never with GFS.
# --------------------------------------------------------------------------


def test_nbs_and_gfs_never_share_a_cache_slot(cli: ModuleType) -> None:
    nbs = iem_mos_request("KMIA", 2021, "NBS")
    gfs = iem_mos_request("KMIA", 2021, "GFS")

    assert nbs.model == "NBS"
    assert gfs.model == "GFS"
    assert nbs.product != gfs.product
    assert nbs.cache_key() != gfs.cache_key()


def test_a_mos_entry_is_distinguishable_from_an_asos_entry(cli: ModuleType) -> None:
    mos = iem_mos_request("KMIA", 2021, "NBS")
    asos = iem_asos_1min_request("KMIA", 2021)

    assert mos.source == IEM_MOS_SOURCE != asos.source
    assert mos.product.startswith("mos-")
    assert asos.model is None and mos.model is not None
    assert mos.cache_key() != asos.cache_key()


def test_the_url_window_is_the_manifest_window(cli: ModuleType) -> None:
    """The bounds the URL carries are DERIVED from the cached request itself."""
    item = cli.StationYear("KMIA", 2021, "NBS")
    sts, ets = cli.window_bounds(item)

    assert (sts, ets) == ("2021-01-01T00:00Z", "2021-12-31T23:59Z")
    url = _transport(cli)._mos_url("KMIA", "NBS", sts, ets)
    query = parse_qs(urlsplit(url).query)
    assert query["sts"] == [sts] and query["ets"] == [ets]


def test_station_years_are_disjoint_windows(cli: ModuleType) -> None:
    first = iem_mos_request("KMIA", 2021, "NBS")
    second = iem_mos_request("KMIA", 2022, "NBS")

    assert first.window_end < second.window_start


# --------------------------------------------------------------------------
# 4. The pacer.
# --------------------------------------------------------------------------


def test_the_pacer_is_a_named_object_whose_interval_is_at_least_one_second(
    cli: ModuleType,
) -> None:
    assert cli.MOS_MIN_INTERVAL_NS >= 1_000_000_000
    pacer = cli.build_pacer(clock=_Clock())

    assert isinstance(pacer, cli.IemPacer)


# --------------------------------------------------------------------------
# 5. The run: plan, dry run, resumability, failures.
# --------------------------------------------------------------------------


def test_a_dry_run_makes_no_request_and_claims_no_coverage(
    cli: ModuleType, tmp_path: Path
) -> None:
    root = _durable_root(tmp_path)
    cache = ArchiveCache(root=root, fetch=cli._dry_run_fetch, clock=_Clock())
    plan = cli.build_plan(stations=("KMIA",), first_year=2021, through_year=2022, model="NBS")

    report = cli.run_backfill(cache=cache, plan=plan, progress=lambda _: None, dry_run=True)

    assert report.would_fetch == 2
    assert report.fetched == 0
    assert not report.failed
    assert not root.exists() or not list(root.rglob("*.csv"))


def test_a_second_run_over_covered_station_years_spends_no_request(
    cli: ModuleType, tmp_path: Path, nbs_day: bytes
) -> None:
    root = _durable_root(tmp_path)
    calls: list[str] = []

    def fetch(request: Any) -> bytes:
        calls.append(request.cache_key())
        return nbs_day

    plan = cli.build_plan(stations=("KMIA",), first_year=2021, through_year=2021, model="NBS")
    first = cli.run_backfill(
        cache=ArchiveCache(root=root, fetch=fetch, clock=_Clock()),
        plan=plan,
        progress=lambda _: None,
    )
    second = cli.run_backfill(
        cache=ArchiveCache(root=root, fetch=fetch, clock=_Clock()),
        plan=plan,
        progress=lambda _: None,
    )

    assert first.fetched == 1
    assert second.fetched == 0 and second.skipped == 1
    assert len(calls) == 1


def test_a_failed_station_year_is_named_and_never_becomes_coverage(
    cli: ModuleType, tmp_path: Path
) -> None:
    root = _durable_root(tmp_path)

    def fetch(request: Any) -> bytes:
        raise cli.EmptyPayloadError("zero rows")

    plan = cli.build_plan(stations=("KMIA",), first_year=2021, through_year=2021, model="NBS")
    report = cli.run_backfill(
        cache=ArchiveCache(root=root, fetch=fetch, clock=_Clock()),
        plan=plan,
        progress=lambda _: None,
    )

    assert report.fetched == 0
    assert [outcome.label for outcome in report.failed] == ["KMIA 2021 NBS"]
    assert "FAILED" in cli.render_summary(report)
    assert ArchiveCache(root=root, fetch=fetch, clock=_Clock()).missing(
        cli.request_for(plan[0])
    )


def test_a_run_refuses_to_mix_models(cli: ModuleType) -> None:
    mixed = (cli.StationYear("KMIA", 2021, "NBS"), cli.StationYear("KMIA", 2021, "GFS"))

    with pytest.raises(cli.ModelMixError):
        cli.refuse_model_mix(item.model for item in mixed)


class _Sentinel:
    """A weak-referenceable stand-in whose life is the payload's life."""


class _TrackedPayload(bytes):
    """A payload whose release is observable.

    ``bytes`` cannot be weak-referenced, and neither can a variable-size
    subclass of it -- but a subclass carries a ``__dict__``, so an attached
    sentinel dies exactly when the payload is released.
    """

    sentinel: _Sentinel


def _tracked(body: bytes) -> tuple[_TrackedPayload, weakref.ref[_Sentinel]]:
    payload = _TrackedPayload(body)
    sentinel = _Sentinel()
    payload.sentinel = sentinel
    return payload, weakref.ref(sentinel)


def test_no_more_than_one_station_year_payload_is_held_at_a_time(
    cli: ModuleType, tmp_path: Path, nbs_day: bytes
) -> None:
    """Process-then-discard: statistics survive an iteration, bytes do not."""
    alive: list[weakref.ref[_Sentinel]] = []
    live_counts: list[int] = []

    def fetch(request: Any) -> bytes:
        gc.collect()
        live_counts.append(sum(1 for ref in alive if ref() is not None))
        payload, ref = _tracked(nbs_day)
        alive.append(ref)
        return payload

    report = cli.run_backfill(
        cache=ArchiveCache(root=_durable_root(tmp_path), fetch=fetch, clock=_Clock()),
        plan=cli.build_plan(stations=("KMIA", "KSFO"), first_year=2021, through_year=2022),
        progress=lambda line: None,
    )

    assert report.fetched == 4
    assert live_counts == [0, 0, 0, 0]


# --------------------------------------------------------------------------
# 6. Root policy and reporting.
# --------------------------------------------------------------------------


def test_a_volatile_cache_root_is_refused(cli: ModuleType) -> None:
    with pytest.raises(ArchiveCachePathError):
        cli.assert_durable_cache_root(Path("/tmp/breezy-mos"))


def test_the_durable_root_is_the_mos_source_not_the_asos_one(cli: ModuleType) -> None:
    assert cli.DURABLE_ROOT_TAIL[-1] == IEM_MOS_SOURCE
    cli.assert_durable_cache_root(_durable_root(Path("/home/someone")))


def test_the_report_json_names_its_fields_and_carries_the_model(
    cli: ModuleType, tmp_path: Path, nbs_day: bytes
) -> None:
    import json

    root = _durable_root(tmp_path)
    plan = cli.build_plan(stations=("KMIA",), first_year=2021, through_year=2021, model="NBS")
    report = cli.run_backfill(
        cache=ArchiveCache(root=root, fetch=lambda request: nbs_day, clock=_Clock()),
        plan=plan,
        progress=lambda _: None,
    )
    payload = json.loads(cli.report_to_json(report))

    assert payload["model"] == "NBS"
    assert payload["product"] == "mos-nbs"
    assert payload["outcomes"][0]["model"] == "NBS"
    assert payload["outcomes"][0]["sha256"]


def test_the_cli_refuses_a_real_run_without_the_live_unlock(
    cli: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("BREEZY_LIVE", raising=False)
    code = cli.main(
        [
            "--cache-root",
            str(_durable_root(tmp_path)),
            "--stations",
            "KMIA",
            "--first-year",
            "2021",
            "--through-year",
            "2021",
            "--apply",
        ]
    )

    assert code == 2


# --------------------------------------------------------------------------
# 7. Explicit date-window mode (WP-7): one entry per (station, window).
#
# The year plan claims a whole calendar year, so it can never reach an
# unfinished year. The window mode is the additive answer: the cache key
# hashes the EXACT window, so re-running an identical window is a zero-request
# no-op while extending the end is a different key that fetches fresh.
# --------------------------------------------------------------------------

WINDOW_START: Final[str] = "2026-08-25"
WINDOW_END: Final[str] = "2026-09-21"  # EXCLUSIVE


def _window_plan(cli: ModuleType, *, stations: tuple[str, ...] = ("KMIA",)) -> Any:
    import datetime as dt

    return cli.build_window_plan(
        stations=stations,
        start=dt.date.fromisoformat(WINDOW_START),
        end=dt.date.fromisoformat(WINDOW_END),
        model="NBS",
    )


def test_a_windowed_entry_is_a_window_claim_not_a_year_claim(cli: ModuleType) -> None:
    import datetime as dt

    from breezy.persistence.archive_request import iem_mos_window_request

    windowed = iem_mos_window_request(
        "KMIA", dt.date.fromisoformat(WINDOW_START), dt.date.fromisoformat(WINDOW_END), "NBS"
    )
    year = iem_mos_request("KMIA", 2026, "NBS")

    assert windowed.cache_key() != year.cache_key()
    assert windowed.source == year.source
    assert windowed.product == year.product
    assert windowed.window_start > year.window_start
    assert windowed.window_end < year.window_end


def test_an_identical_window_is_the_same_key_and_an_extended_one_is_not(
    cli: ModuleType,
) -> None:
    """Resumability and correctness for an ONGOING period, with no refresh concept."""
    import datetime as dt

    from breezy.persistence.archive_request import iem_mos_window_request

    start = dt.date.fromisoformat(WINDOW_START)
    same_a = iem_mos_window_request("KMIA", start, dt.date.fromisoformat(WINDOW_END), "NBS")
    same_b = iem_mos_window_request("KMIA", start, dt.date.fromisoformat(WINDOW_END), "NBS")
    extended = iem_mos_window_request("KMIA", start, dt.date(2026, 9, 28), "NBS")

    assert same_a.cache_key() == same_b.cache_key()
    assert extended.cache_key() != same_a.cache_key()


def test_a_windowed_url_carries_the_exact_window_the_manifest_records(
    cli: ModuleType,
) -> None:
    item = _window_plan(cli)[0]
    sts, ets = cli.window_bounds(item)

    assert (sts, ets) == ("2026-08-25T00:00Z", "2026-09-20T23:59Z")
    query = parse_qs(urlsplit(_transport(cli)._mos_url("KMIA", "NBS", sts, ets)).query)
    assert query["sts"] == [sts] and query["ets"] == [ets]


def test_a_whole_calendar_year_window_is_refused_as_a_year_claim(cli: ModuleType) -> None:
    import datetime as dt

    with pytest.raises(ValueError):
        cli.build_window_plan(
            stations=("KMIA",), start=dt.date(2021, 1, 1), end=dt.date(2022, 1, 1), model="NBS"
        )


def test_an_end_at_or_before_the_start_is_refused(cli: ModuleType) -> None:
    import datetime as dt

    with pytest.raises(ValueError):
        cli.build_window_plan(
            stations=("KMIA",), start=dt.date(2026, 9, 1), end=dt.date(2026, 9, 1), model="NBS"
        )


def test_the_window_plan_is_station_major_and_one_item_per_station(cli: ModuleType) -> None:
    plan = _window_plan(cli, stations=("KMIA", "KSFO"))

    assert [item.station for item in plan] == ["KMIA", "KSFO"]
    assert all(item.model == "NBS" for item in plan)
    assert plan[0].label == "KMIA 2026-08-25..2026-09-21 NBS"


def test_a_zero_row_windowed_response_fails_and_is_never_cached(
    cli: ModuleType, tmp_path: Path, three_letter_zero_rows: bytes
) -> None:
    """HTTP 200 is not coverage in window mode either (the negative control)."""
    root = _durable_root(tmp_path)
    plan = _window_plan(cli)

    def fetch(request: Any) -> bytes:
        cli.validate_payload(three_letter_zero_rows, station="KMIA", model="NBS")
        return three_letter_zero_rows

    report = cli.run_backfill(
        cache=ArchiveCache(root=root, fetch=fetch, clock=_Clock()),
        plan=plan,
        progress=lambda _: None,
    )

    assert report.fetched == 0
    assert [outcome.label for outcome in report.failed] == [
        "KMIA 2026-08-25..2026-09-21 NBS"
    ]
    assert ArchiveCache(root=root, fetch=fetch, clock=_Clock()).missing(
        cli.request_for(plan[0])
    )


def test_re_running_the_identical_window_spends_no_request(
    cli: ModuleType, tmp_path: Path, nbs_day: bytes
) -> None:
    root = _durable_root(tmp_path)
    calls: list[str] = []

    def fetch(request: Any) -> bytes:
        calls.append(request.cache_key())
        return nbs_day

    plan = _window_plan(cli)
    first = cli.run_backfill(
        cache=ArchiveCache(root=root, fetch=fetch, clock=_Clock()),
        plan=plan,
        progress=lambda _: None,
    )
    second = cli.run_backfill(
        cache=ArchiveCache(root=root, fetch=fetch, clock=_Clock()),
        plan=plan,
        progress=lambda _: None,
    )

    assert first.fetched == 1
    assert second.fetched == 0 and second.skipped == 1
    assert len(calls) == 1


def test_an_extended_window_is_a_fresh_fetch_beside_the_shorter_one(
    cli: ModuleType, tmp_path: Path, nbs_day: bytes
) -> None:
    import datetime as dt

    root = _durable_root(tmp_path)
    calls: list[str] = []

    def fetch(request: Any) -> bytes:
        calls.append(request.cache_key())
        return nbs_day

    short = _window_plan(cli)
    longer = cli.build_window_plan(
        stations=("KMIA",),
        start=dt.date.fromisoformat(WINDOW_START),
        end=dt.date(2026, 9, 28),
        model="NBS",
    )
    cli.run_backfill(
        cache=ArchiveCache(root=root, fetch=fetch, clock=_Clock()),
        plan=short,
        progress=lambda _: None,
    )
    second = cli.run_backfill(
        cache=ArchiveCache(root=root, fetch=fetch, clock=_Clock()),
        plan=longer,
        progress=lambda _: None,
    )

    assert second.fetched == 1
    assert len(calls) == 2 and calls[0] != calls[1]


def test_the_window_report_json_names_the_window_field(
    cli: ModuleType, tmp_path: Path, nbs_day: bytes
) -> None:
    import json

    report = cli.run_backfill(
        cache=ArchiveCache(
            root=_durable_root(tmp_path), fetch=lambda request: nbs_day, clock=_Clock()
        ),
        plan=_window_plan(cli),
        progress=lambda _: None,
    )
    payload = json.loads(cli.report_to_json(report))

    assert payload["outcomes"][0]["window"] == "2026-08-25..2026-09-21"
    assert payload["outcomes"][0]["year"] is None
    assert payload["outcomes"][0]["model"] == "NBS"


def test_the_cli_refuses_a_date_window_mixed_with_the_year_plan(
    cli: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BREEZY_LIVE", "1")
    monkeypatch.setenv("BREEZY_USER_AGENT", TEST_UA)
    code = cli.main(
        [
            "--cache-root",
            str(_durable_root(tmp_path)),
            "--stations",
            "KMIA",
            "--through-year",
            "2021",
            "--start",
            WINDOW_START,
            "--end",
            WINDOW_END,
            "--dry-run",
        ]
    )

    assert code == 2


def test_the_cli_refuses_a_start_without_an_end(
    cli: ModuleType, tmp_path: Path
) -> None:
    code = cli.main(
        [
            "--cache-root",
            str(_durable_root(tmp_path)),
            "--start",
            WINDOW_START,
            "--dry-run",
        ]
    )

    assert code == 2


def test_the_cli_dry_run_plans_one_request_per_station_in_window_mode(
    cli: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = cli.main(
        [
            "--cache-root",
            str(_durable_root(tmp_path)),
            "--stations",
            "KMIA",
            "KSFO",
            "--start",
            WINDOW_START,
            "--end",
            WINDOW_END,
            "--dry-run",
        ]
    )

    assert code == 0
    assert "2026-08-25..2026-09-21" in capsys.readouterr().err


# --------------------------------------------------------------------------
# 8. Nightly closed-day refresh (AUD-18): plan, idempotence, healing, the
#    completeness guard, the retry policy, and the settled-bound guard.
# --------------------------------------------------------------------------


def _closed_day_csv(
    day: dt.date,
    *,
    station: str = "KMIA",
    model: str = "NBS",
    hours: tuple[int, ...] = (0, 6, 12, 18),
) -> bytes:
    """A minimal but VALID (per `validate_payload`) NBS closed-day body: one
    row per named UTC cycle hour, all on ``day``."""
    header = "runtime,ftime,model,station\n"
    rows = "".join(
        f"{day.isoformat()} {hour:02d}:00:00,{day.isoformat()} 00:00:00,{model},{station}\n"
        for hour in hours
    )
    return (header + rows).encode("utf-8")


async def _instant_sleeper(_seconds: float) -> None:
    """A pacer sleeper that never really sleeps -- the fake ns clock below
    never advances between calls, so the REAL `IemPacer.wait()` would
    otherwise fall back to `asyncio.sleep` for a full second per retry."""
    return


class _FakeSleepMonotonic:
    """One fake object standing in for BOTH `time.sleep` and `time.monotonic`,
    consistent with each other: a recorded sleep always advances the fake
    monotonic clock by the same amount, exactly as a real sleep would."""

    def __init__(self, start: float = 1_000.0) -> None:
        self._now = start
        self.waits: list[float] = []

    def sleep(self, seconds: float) -> None:
        self.waits.append(seconds)
        self._now += seconds

    def monotonic(self) -> float:
        return self._now


def _fetch_result(
    status_code: int, *, text: str = "ok", retry_after: str | None = None
) -> FetchResult:
    return FetchResult(
        text=text,
        sha256="0" * 64,
        status_code=status_code,
        headers=httpx.Headers({}),
        url="https://mesonet.agron.iastate.edu/cgi-bin/request/mos.py",
        retrieved_at_ns=1,
        retry_after=retry_after,
    )


def _patch_http_fetch(monkeypatch: pytest.MonkeyPatch, script: list[Any]) -> list[str]:
    """Patch the REAL `HttpTransport._fetch` (the base under
    `PacedIemTransport`), so `PacedIemTransport._fetch`'s own budget.consume()
    and pacer.wait() -- one layer up -- still run for real on every attempt,
    exactly as the Test Strategy in the plan requires. `script` is consumed
    in call order; each item is a `FetchResult` to return or a `BaseException`
    to raise.
    """
    calls: list[str] = []
    iterator = iter(script)

    async def fake_fetch(
        self: Any,
        url: str,
        *,
        if_none_match: str | None = None,
        if_modified_since: str | None = None,
        allow_not_modified: bool = False,
    ) -> FetchResult:
        calls.append(url)
        outcome = next(iterator)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    monkeypatch.setattr(HttpTransport, "_fetch", fake_fetch)
    return calls


def _build_transport(cli: ModuleType, *, budget_limit: int = 100) -> tuple[Any, Any, Any]:
    clock = _Clock()
    budget = RequestBudget(limit=budget_limit)
    pacer = cli.build_pacer(clock=clock, sleeper=_instant_sleeper)
    transport = cli.IemMosBackfillTransport(
        budget=budget, pacer=pacer, user_agent=TEST_UA, clock=clock
    )
    return transport, budget, pacer


def _drive_fetch(
    cli: ModuleType,
    item: Any,
    transport: Any,
    *,
    guard: Any = None,
    sleep_monotonic: _FakeSleepMonotonic | None = None,
) -> tuple[bytes, _FakeSleepMonotonic]:
    sm = sleep_monotonic or _FakeSleepMonotonic()
    retry_wall = cli._RetryWall()
    request = cli.request_for(item)
    with asyncio.Runner() as runner:
        fetch = cli._make_fetch(
            transport,
            runner,
            {request.cache_key(): item},
            sleep=sm.sleep,
            monotonic=sm.monotonic,
            retry_wall=retry_wall,
            guard=guard,
        )
        return fetch(request), sm


# --- plan ------------------------------------------------------------------


def test_closed_day_plan_excludes_today_and_unsettled_yesterday(cli: ModuleType) -> None:
    clock_11z = _Clock(int(dt.datetime(2026, 9, 25, 11, 0, tzinfo=dt.UTC).timestamp() * 1e9))
    bound_11z = cli.settled_day_bound(clock_11z)
    plan_11z = cli.build_closed_day_plan(
        stations=("KMIA",), settled_bound=bound_11z, lookback=1, model="NBS"
    )
    assert plan_11z[0].start == dt.date(2026, 9, 23), "yesterday (09-24) must be EXCLUDED at 11:00Z"

    clock_1330z = _Clock(int(dt.datetime(2026, 9, 25, 13, 30, tzinfo=dt.UTC).timestamp() * 1e9))
    bound_1330z = cli.settled_day_bound(clock_1330z)
    plan_1330z = cli.build_closed_day_plan(
        stations=("KMIA",), settled_bound=bound_1330z, lookback=1, model="NBS"
    )
    assert plan_1330z[0].start == dt.date(2026, 9, 24), "yesterday must be INCLUDED at 13:30Z"


def test_closed_day_plan_is_one_entry_per_station_day_newest_first(cli: ModuleType) -> None:
    plan = cli.build_closed_day_plan(
        stations=("KMIA", "KLAX"), settled_bound=dt.date(2026, 9, 25), lookback=2, model="NBS"
    )

    assert [(item.station, item.start) for item in plan] == [
        ("KMIA", dt.date(2026, 9, 24)),
        ("KLAX", dt.date(2026, 9, 24)),
        ("KMIA", dt.date(2026, 9, 23)),
        ("KLAX", dt.date(2026, 9, 23)),
    ]
    assert all(item.end == item.start + dt.timedelta(days=1) for item in plan)


def test_lookback_bounds_refused(cli: ModuleType) -> None:
    with pytest.raises(ValueError):
        cli.build_closed_day_plan(
            stations=("KMIA",), settled_bound=dt.date(2026, 9, 25), lookback=0, model="NBS"
        )
    with pytest.raises(ValueError):
        cli.build_closed_day_plan(
            stations=("KMIA",), settled_bound=dt.date(2026, 9, 25), lookback=32, model="NBS"
        )


# --- idempotence and healing -------------------------------------------------


def test_second_refresh_run_is_all_skipped_zero_requests(
    cli: ModuleType, tmp_path: Path, nbs_day: bytes
) -> None:
    root = _durable_root(tmp_path)
    calls: list[str] = []

    def fetch(request: Any) -> bytes:
        calls.append(request.cache_key())
        return nbs_day

    plan = cli.build_closed_day_plan(
        stations=("KMIA",), settled_bound=dt.date(2026, 9, 25), lookback=2, model="NBS"
    )
    first = cli.run_backfill(
        cache=ArchiveCache(root=root, fetch=fetch, clock=_Clock()), plan=plan,
        progress=lambda _: None,
    )
    second = cli.run_backfill(
        cache=ArchiveCache(root=root, fetch=fetch, clock=_Clock()), plan=plan,
        progress=lambda _: None,
    )

    assert first.fetched == 2
    assert second.fetched == 0 and second.skipped == 2
    assert len(calls) == 2


def test_missed_nights_heal_within_lookback(
    cli: ModuleType, tmp_path: Path, nbs_day: bytes
) -> None:
    root = _durable_root(tmp_path)
    calls: list[str] = []

    def fetch(request: Any) -> bytes:
        calls.append(request.cache_key())
        return nbs_day

    # Night 1: settled_bound=09-25, lookback=1 -> fetches 09-24 only.
    plan1 = cli.build_closed_day_plan(
        stations=("KMIA",), settled_bound=dt.date(2026, 9, 25), lookback=1, model="NBS"
    )
    cli.run_backfill(
        cache=ArchiveCache(root=root, fetch=fetch, clock=_Clock()), plan=plan1,
        progress=lambda _: None,
    )
    # Night 2 (09-26) is MISSED entirely -- no run happens.
    # Night 3: settled_bound=09-27, lookback=3 -> covers 09-26, 09-25, 09-24;
    # 09-24 is already covered (skip), 09-25/09-26 heal with no hand edits.
    plan3 = cli.build_closed_day_plan(
        stations=("KMIA",), settled_bound=dt.date(2026, 9, 27), lookback=3, model="NBS"
    )
    report3 = cli.run_backfill(
        cache=ArchiveCache(root=root, fetch=fetch, clock=_Clock()), plan=plan3,
        progress=lambda _: None,
    )

    assert report3.fetched == 2
    assert report3.skipped == 1
    assert len(calls) == 3


# --- resolve: narrowest-wins over the acknowledged wide 09-25 entry ---------


def test_day_entry_shadows_overwide_window_in_resolve_mos_coverage(
    cli: ModuleType, tmp_path: Path, nbs_day: bytes
) -> None:
    from forecast_conditional_corpus import resolve_mos_coverage

    root = _durable_root(tmp_path)
    wide = iem_mos_window_request("KMIA", dt.date(2026, 9, 20), dt.date(2026, 9, 27), "NBS")
    day25 = iem_mos_window_request("KMIA", dt.date(2026, 9, 25), dt.date(2026, 9, 26), "NBS")
    day26 = iem_mos_window_request("KMIA", dt.date(2026, 9, 26), dt.date(2026, 9, 27), "NBS")
    cache = ArchiveCache(root=root, fetch=lambda _r: nbs_day, clock=_Clock())
    for request in (wide, day25, day26):
        cache.get_or_fetch(request)

    coverage = resolve_mos_coverage(
        cache, station="KMIA", start=dt.date(2026, 9, 25), end=dt.date(2026, 9, 27), model="NBS"
    )

    for day, expected_owner in ((dt.date(2026, 9, 25), day25), (dt.date(2026, 9, 26), day26)):
        owner = coverage.request_by_day[day]
        assert owner.cache_key() == expected_owner.cache_key()
        assert (owner.window_end - owner.window_start) < (wide.window_end - wide.window_start)


# --- window mode: the settled-bound guard, injected clock -------------------


def test_window_mode_refuses_end_after_settled_bound_injected_clock(
    cli: ModuleType, tmp_path: Path
) -> None:
    clock = _Clock(int(dt.datetime(2026, 9, 25, 5, 35, tzinfo=dt.UTC).timestamp() * 1e9))
    code = cli.main(
        [
            "--cache-root", str(_durable_root(tmp_path)),
            "--stations", "KMIA",
            "--start", "2026-09-20",
            "--end", "2026-09-27",
            "--dry-run",
        ],
        clock=clock,
    )
    assert code == 2


def test_window_mode_accepts_end_at_settled_bound(cli: ModuleType, tmp_path: Path) -> None:
    # now-12h at 2026-09-25T13:30Z is 2026-09-25T01:30Z -> settled_bound == 2026-09-25.
    clock = _Clock(int(dt.datetime(2026, 9, 25, 13, 30, tzinfo=dt.UTC).timestamp() * 1e9))
    code = cli.main(
        [
            "--cache-root", str(_durable_root(tmp_path)),
            "--stations", "KMIA",
            "--start", "2026-09-20",
            "--end", "2026-09-25",
            "--dry-run",
        ],
        clock=clock,
    )
    assert code == 0


def test_lookback_mode_refuses_start_end_and_year_flags(cli: ModuleType, tmp_path: Path) -> None:
    code1 = cli.main(
        [
            "--cache-root", str(_durable_root(tmp_path)),
            "--closed-days-lookback", "7",
            "--start", "2026-09-20",
            "--end", "2026-09-21",
            "--dry-run",
        ]
    )
    assert code1 == 2

    code2 = cli.main(
        [
            "--cache-root", str(_durable_root(tmp_path)),
            "--closed-days-lookback", "7",
            "--first-year", "2021",
            "--through-year", "2021",
            "--dry-run",
        ]
    )
    assert code2 == 2


# --- completeness guard ------------------------------------------------------


def test_incomplete_day_guard_raises_inside_fetch_and_no_manifest_entry_exists(
    cli: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _durable_root(tmp_path)
    day = dt.date(2026, 9, 24)
    item = cli.StationWindow("KMIA", day, day + dt.timedelta(days=1), "NBS")
    incomplete_body = _closed_day_csv(day, hours=(0, 6, 12))  # missing the 18Z cycle
    _patch_http_fetch(monkeypatch, [_fetch_result(200, text=incomplete_body.decode("utf-8"))])
    transport, _budget, _pacer = _build_transport(cli)
    request = cli.request_for(item)
    sm = _FakeSleepMonotonic()
    with asyncio.Runner() as runner:
        fetch = cli._make_fetch(
            transport, runner, {request.cache_key(): item},
            sleep=sm.sleep, monotonic=sm.monotonic, retry_wall=cli._RetryWall(),
            guard=cli._closed_day_guard,
        )
        cache = ArchiveCache(root=root, fetch=fetch, clock=_Clock())
        with pytest.raises(cli.IncompleteClosedDayError):
            cache.get_or_fetch(request)

    assert cache.missing(request)
    manifest_path = root / IEM_MOS_SOURCE / "coverage.json"
    assert not manifest_path.exists() or request.cache_key() not in manifest_path.read_text()
    assert not (root / IEM_MOS_SOURCE / f"{request.cache_key()}.csv").exists()


def test_guard_is_mandatory_in_closed_day_mode(
    cli: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BREEZY_LIVE", "1")
    monkeypatch.setenv("BREEZY_USER_AGENT", TEST_UA)
    recorded: dict[str, Any] = {}
    original_make_fetch = cli._make_fetch

    def spy_make_fetch(*args: Any, **kwargs: Any) -> Any:
        recorded["guard"] = kwargs.get("guard")
        return original_make_fetch(*args, **kwargs)

    monkeypatch.setattr(cli, "_make_fetch", spy_make_fetch)
    good_body = _closed_day_csv(dt.date(2026, 9, 24))
    _patch_http_fetch(monkeypatch, [_fetch_result(200, text=good_body.decode("utf-8"))] * 8)
    clock = _Clock(int(dt.datetime(2026, 9, 25, 13, 30, tzinfo=dt.UTC).timestamp() * 1e9))

    code = cli.main(
        [
            "--cache-root", str(_durable_root(tmp_path)),
            "--stations", "KMIA",
            "--closed-days-lookback", "1",
            "--apply",
        ],
        clock=clock,
    )

    assert code == 0
    assert recorded["guard"] is cli._closed_day_guard


# --- retry policy -------------------------------------------------------------


def test_429_returned_fetchresult_retry_after_honoured_and_capped(
    cli: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    day = dt.date(2026, 9, 24)
    item = cli.StationWindow("KMIA", day, day + dt.timedelta(days=1), "NBS")
    good_body = _closed_day_csv(day)
    calls = _patch_http_fetch(
        monkeypatch,
        [
            _fetch_result(429, text="rate limited", retry_after="500"),
            _fetch_result(200, text=good_body.decode("utf-8")),
        ],
    )
    transport, budget, _pacer = _build_transport(cli)

    body, sm = _drive_fetch(cli, item, transport)

    assert body == good_body
    assert len(calls) == 2
    assert sm.waits == [cli._MAX_RETRY_WAIT_S]
    assert budget.spent == 2


def test_429_raised_ratelimitederror_retry_after_honoured(
    cli: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    day = dt.date(2026, 9, 24)
    item = cli.StationWindow("KMIA", day, day + dt.timedelta(days=1), "NBS")
    good_body = _closed_day_csv(day)
    calls = _patch_http_fetch(
        monkeypatch,
        [
            RateLimitedError("429", retry_after="7"),
            _fetch_result(200, text=good_body.decode("utf-8")),
        ],
    )
    transport, budget, _pacer = _build_transport(cli)

    body, sm = _drive_fetch(cli, item, transport)

    assert body == good_body
    assert len(calls) == 2
    assert sm.waits == [7.0]
    assert budget.spent == 2


def test_5xx_raised_servererror_retried_then_failed_not_cached(
    cli: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    day = dt.date(2026, 9, 24)
    item = cli.StationWindow("KMIA", day, day + dt.timedelta(days=1), "NBS")
    calls = _patch_http_fetch(
        monkeypatch, [ServerError("500", status_code=500) for _ in range(4)]
    )
    transport, _budget, _pacer = _build_transport(cli)
    request = cli.request_for(item)
    root = _durable_root(tmp_path)
    sm = _FakeSleepMonotonic()
    with asyncio.Runner() as runner:
        fetch = cli._make_fetch(
            transport, runner, {request.cache_key(): item},
            sleep=sm.sleep, monotonic=sm.monotonic, retry_wall=cli._RetryWall(),
        )
        cache = ArchiveCache(root=root, fetch=fetch, clock=_Clock())
        with pytest.raises(ServerError):
            cache.get_or_fetch(request)

    assert len(calls) == 1 + cli._MAX_FETCH_RETRIES
    assert cache.missing(request)
    assert not (root / IEM_MOS_SOURCE / f"{request.cache_key()}.csv").exists()


def test_5xx_returned_fetchresult_retried(
    cli: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    day = dt.date(2026, 9, 24)
    item = cli.StationWindow("KMIA", day, day + dt.timedelta(days=1), "NBS")
    good_body = _closed_day_csv(day)
    calls = _patch_http_fetch(
        monkeypatch,
        [
            _fetch_result(503, text="unavailable"),
            _fetch_result(200, text=good_body.decode("utf-8")),
        ],
    )
    transport, budget, _pacer = _build_transport(cli)

    body, sm = _drive_fetch(cli, item, transport)

    assert body == good_body
    assert len(calls) == 2
    assert sm.waits == [cli._RETRY_BACKOFF_BASE_S]
    assert budget.spent == 2


def test_4xx_non_429_and_403_not_retried(
    cli: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    day = dt.date(2026, 9, 24)
    item = cli.StationWindow("KMIA", day, day + dt.timedelta(days=1), "NBS")

    calls_404 = _patch_http_fetch(monkeypatch, [_fetch_result(404, text="not found")])
    transport_404, _b, _p = _build_transport(cli)
    with pytest.raises(cli.EmptyPayloadError):
        _drive_fetch(cli, item, transport_404)
    assert len(calls_404) == 1

    calls_403 = _patch_http_fetch(monkeypatch, [ForbiddenError("403")])
    transport_403, _b2, _p2 = _build_transport(cli)
    with pytest.raises(ForbiddenError):
        _drive_fetch(cli, item, transport_403)
    assert len(calls_403) == 1


def test_timeout_not_retried(cli: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    day = dt.date(2026, 9, 24)
    item = cli.StationWindow("KMIA", day, day + dt.timedelta(days=1), "NBS")
    calls = _patch_http_fetch(monkeypatch, [TransportTimeoutError("timed out")])
    transport, _budget, _pacer = _build_transport(cli)

    with pytest.raises(TransportTimeoutError):
        _drive_fetch(cli, item, transport)
    assert len(calls) == 1


def test_retry_reinvokes_fetch_mos_csv_so_pacer_and_budget_charge_per_attempt(
    cli: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    day = dt.date(2026, 9, 24)
    item = cli.StationWindow("KMIA", day, day + dt.timedelta(days=1), "NBS")
    good_body = _closed_day_csv(day)
    calls = _patch_http_fetch(
        monkeypatch,
        [
            _fetch_result(503, text="a"),
            _fetch_result(503, text="b"),
            _fetch_result(200, text=good_body.decode("utf-8")),
        ],
    )
    transport, budget, pacer = _build_transport(cli)
    pacer_wait_count = 0
    original_wait = pacer.wait

    async def spy_wait() -> None:
        nonlocal pacer_wait_count
        pacer_wait_count += 1
        await original_wait()

    pacer.wait = spy_wait  # type: ignore[method-assign]

    body, _sm = _drive_fetch(cli, item, transport)

    assert body == good_body
    assert len(calls) == 3
    assert budget.spent == 3
    assert pacer_wait_count == 3


def test_budget_sized_for_retries(
    cli: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, nbs_day: bytes
) -> None:
    monkeypatch.setenv("BREEZY_LIVE", "1")
    monkeypatch.setenv("BREEZY_USER_AGENT", TEST_UA)
    recorded: dict[str, int] = {}
    real_budget_cls = cli.RequestBudget

    class _SpyBudget(real_budget_cls):  # type: ignore[misc, valid-type]
        def __init__(self, *, limit: int) -> None:
            recorded["limit"] = limit
            super().__init__(limit=limit)

    monkeypatch.setattr(cli, "RequestBudget", _SpyBudget)
    _patch_http_fetch(monkeypatch, [_fetch_result(200, text=nbs_day.decode("utf-8"))])

    code = cli.main(
        [
            "--cache-root", str(_durable_root(tmp_path)),
            "--stations", "KMIA",
            "--first-year", "2021",
            "--through-year", "2021",
            "--apply",
        ]
    )

    assert code == 0
    assert recorded["limit"] == 1 * (1 + cli._MAX_FETCH_RETRIES)


def test_total_retry_wall_cap_stops_retries(
    cli: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    day = dt.date(2026, 9, 24)
    item = cli.StationWindow("KMIA", day, day + dt.timedelta(days=1), "NBS")
    calls = _patch_http_fetch(
        monkeypatch, [_fetch_result(503, text="x", retry_after="120") for _ in range(3)]
    )
    transport, _budget, _pacer = _build_transport(cli)
    sm = _FakeSleepMonotonic(start=0.0)
    request = cli.request_for(item)
    with asyncio.Runner() as runner:
        fetch = cli._make_fetch(
            transport, runner, {request.cache_key(): item},
            sleep=sm.sleep, monotonic=sm.monotonic, retry_wall=cli._RetryWall(),
        )
        with pytest.raises(cli.EmptyPayloadError):
            fetch(request)

    # Two waits of 120s land at monotonic=240; the third scheduled 120s wait
    # would cross the 300s wall, so the third fetch_mos_csv call never
    # happens -- the run raises on what it already has instead.
    assert len(calls) == 3
    assert sm.waits == [120.0, 120.0]


def test_empty_payload_error_only_after_exhaustion_or_non_retryable(
    cli: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    day = dt.date(2026, 9, 24)
    item = cli.StationWindow("KMIA", day, day + dt.timedelta(days=1), "NBS")

    calls_exhausted = _patch_http_fetch(
        monkeypatch, [_fetch_result(503, text="x") for _ in range(1 + 3)]
    )
    transport_exhausted, _b, _p = _build_transport(cli)
    with pytest.raises(cli.EmptyPayloadError):
        _drive_fetch(cli, item, transport_exhausted)
    assert len(calls_exhausted) == 1 + cli._MAX_FETCH_RETRIES

    calls_immediate = _patch_http_fetch(monkeypatch, [_fetch_result(404, text="nf")])
    transport_immediate, _b2, _p2 = _build_transport(cli)
    with pytest.raises(cli.EmptyPayloadError):
        _drive_fetch(cli, item, transport_immediate)
    assert len(calls_immediate) == 1


def test_http_date_retry_after_falls_back_to_backoff(
    cli: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An RFC 7231 HTTP-date `Retry-After` is not an integer, so `int()`
    raises inside `_retry_wait` and it is treated as absent (Low risk item)."""
    day = dt.date(2026, 9, 24)
    item = cli.StationWindow("KMIA", day, day + dt.timedelta(days=1), "NBS")
    good_body = _closed_day_csv(day)
    calls = _patch_http_fetch(
        monkeypatch,
        [
            _fetch_result(503, text="x", retry_after="Wed, 21 Oct 2026 07:28:00 GMT"),
            _fetch_result(200, text=good_body.decode("utf-8")),
        ],
    )
    transport, _budget, _pacer = _build_transport(cli)

    body, sm = _drive_fetch(cli, item, transport)

    assert body == good_body
    assert len(calls) == 2
    assert sm.waits == [cli._RETRY_BACKOFF_BASE_S]


def test_request_budget_exceeded_is_never_retried(
    cli: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    day = dt.date(2026, 9, 24)
    item = cli.StationWindow("KMIA", day, day + dt.timedelta(days=1), "NBS")
    good_body = _closed_day_csv(day)
    calls = _patch_http_fetch(monkeypatch, [_fetch_result(200, text=good_body.decode("utf-8"))])
    clock = _Clock()
    budget = RequestBudget(limit=1)
    budget.consume()  # exhausted before the fetch even starts
    pacer = cli.build_pacer(clock=clock, sleeper=_instant_sleeper)
    transport = cli.IemMosBackfillTransport(
        budget=budget, pacer=pacer, user_agent=TEST_UA, clock=clock
    )

    with pytest.raises(RequestBudgetExceededError):
        _drive_fetch(cli, item, transport)

    assert len(calls) == 0
