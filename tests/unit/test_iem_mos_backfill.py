"""Unit tests for the IEM MOS (NBS/GFS) backfill CLI (FC-0a-3 / WP-4).

Every test runs against fakes and against CHECKED-IN bodies captured from the
live service. ``tests/conftest.py`` blocks real sockets for anything not
marked ``live``/``allow_socket``, and nothing here carries either marker: no
test in this module performs, or may perform, network I/O.
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
    IEM_MOS_SOURCE,
    ArchiveCache,
    ArchiveCachePathError,
    iem_asos_1min_request,
    iem_mos_request,
)

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
