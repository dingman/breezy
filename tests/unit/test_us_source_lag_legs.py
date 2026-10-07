"""RED-first tests: F13 C1-R1 collector legs lav / mos / obs (availability-only lag legs).

Each leg appends first-seen rows to its own poll ledger; nothing else is written. Network is a
fake fetcher or httpx MockTransport; the unit timers are checked from the repo unit files.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from breezy.ingest.nws_observation_config import build_observation_transport
from breezy.ingest.nws_observation_transport import NwsObservationTransport
from tests.support.mock_http import install_mock_http
from tests.unit.test_us_source_collector import (
    HOUR,
    MIN,
    FakeClock,
    Recorder,
    _events,
    col,
    make_ctx,
    ts,
)

ObsTransport = sys.modules["us_source_obs_transport"].ObsTransport
LAV_SOURCE = col.SOURCE_KEYS["lav"]
MOS_SOURCE = col.SOURCE_KEYS["mos"]
OBS_SOURCE = col.SOURCE_KEYS["obs"]
STATIONS = ("KLAX", "KMDW", "KMIA", "KNYC", "KSFO")
DAY = ts(2026, 10, 7)


def _csv(station: str, run_ts_ns: int, model: str) -> bytes:
    import datetime as dt

    run = dt.datetime.fromtimestamp(run_ts_ns / 1e9, dt.UTC).strftime("%Y-%m-%d %H:%M:%S")
    return (f"runtime,ftime,model,tmp,station\n{run},{run},{model},70,{station}\n").encode()


class IemFeed:
    """Publishes every station's CSV at ``publish_at_ns`` (None: always)."""

    def __init__(
        self,
        clock: FakeClock,
        rec: Recorder,
        tag: str,
        model: str,
        publish_at_ns: int | None = None,
    ) -> None:
        self.clock, self.rec, self.tag, self.model = clock, rec, tag, model
        self.publish_at_ns = publish_at_ns

    def __call__(self, station: str, run_ts_ns: int) -> Any:
        self.rec.calls.append((self.tag, station, run_ts_ns, self.clock()))
        if self.publish_at_ns is not None and self.clock() < self.publish_at_ns:
            raise col.NotPublishedError("no row")
        return col.FetchedPayload(_csv(station, run_ts_ns, self.model), self.clock(), None, "iem")


def _run(
    tmp_path: Path, source: str, now_ns: int, **fetchers: Any
) -> tuple[Any, FakeClock, Recorder]:
    clock = FakeClock(now_ns)
    rec = Recorder()
    ctx = make_ctx(tmp_path, clock, rec, **fetchers)
    return col.run_cycle(source, ctx), clock, rec


# ------------------------------------------------------------------------------- lav


def test_lav_records_first_seen_for_every_station_against_the_hourly_run(tmp_path: Path) -> None:
    clock, rec = FakeClock(DAY + 6 * HOUR + 40 * MIN), Recorder()
    feed = IemFeed(clock, rec, "lav", "LAV")
    report = col.run_cycle("lav", make_ctx(tmp_path, clock, rec, fetch_lav=feed))
    assert report.status is col.CycleStatus.COLLECTED
    seen = [e for e in _events(tmp_path, LAV_SOURCE) if e["kind"] == "seen"]
    run = DAY + 6 * HOUR
    got = {e["station"]: e for e in seen if e["run_ts_ns"] == run}
    assert sorted(got) == list(STATIONS)
    one = got["KSFO"]
    assert one["available_ts_ns"] == DAY + 6 * HOUR + 40 * MIN
    assert one["basis"] == "first_seen@iem"
    assert one["late"] is False
    assert one["host_tag"] == "iem"


def test_lav_unpublished_run_is_a_miss_then_the_later_seen_row_follows_it(tmp_path: Path) -> None:
    run = DAY + 6 * HOUR
    clock, rec = FakeClock(run + 20 * MIN), Recorder()
    feed = IemFeed(clock, rec, "lav", "LAV", publish_at_ns=run + 40 * MIN)
    ctx = make_ctx(tmp_path, clock, rec, fetch_lav=feed)
    first = col.run_cycle("lav", ctx)
    assert first.status is col.CycleStatus.NOT_PUBLISHED
    assert not [e for e in _events(tmp_path, LAV_SOURCE) if e["kind"] == "seen"]
    clock.now = run + 50 * MIN
    col.run_cycle("lav", ctx)
    row = next(
        e
        for e in _events(tmp_path, LAV_SOURCE)
        if e["kind"] == "seen" and e["station"] == "KMIA" and e["run_ts_ns"] == run
    )
    assert row["miss_ts_ns"] == run + 20 * MIN
    assert row["available_ts_ns"] == run + 50 * MIN


def test_lav_does_not_poll_before_its_start_offset_or_a_station_already_seen(
    tmp_path: Path,
) -> None:
    run = DAY + 6 * HOUR
    clock, rec = FakeClock(run + 5 * MIN), Recorder()
    feed = IemFeed(clock, rec, "lav", "LAV")
    ctx = make_ctx(tmp_path, clock, rec, fetch_lav=feed)
    col.run_cycle("lav", ctx)
    assert [c for c in rec.calls if c[2] == run] == []
    clock.now = run + 30 * MIN
    col.run_cycle("lav", ctx)
    count = len(rec.calls)
    clock.now = run + 40 * MIN
    col.run_cycle("lav", ctx)
    assert len([c for c in rec.calls if c[2] == run]) == len(
        [c for c in rec.calls[:count] if c[2] == run]
    )


# ------------------------------------------------------------------------------- mos


def test_mos_nominal_is_the_six_hourly_model_runtime_and_polls_from_plus_two_hours(
    tmp_path: Path,
) -> None:
    run = DAY + 12 * HOUR
    clock, rec = FakeClock(run + 1 * HOUR), Recorder()
    feed = IemFeed(clock, rec, "mos", "GFS")
    ctx = make_ctx(tmp_path, clock, rec, fetch_mos=feed)
    col.run_cycle("mos", ctx)
    assert [c for c in rec.calls if c[2] == run] == []
    clock.now = run + 3 * HOUR + 50 * MIN
    report = col.run_cycle("mos", ctx)
    assert report.status is col.CycleStatus.COLLECTED
    seen = [
        e for e in _events(tmp_path, MOS_SOURCE) if e["kind"] == "seen" and e["run_ts_ns"] == run
    ]
    assert sorted(e["station"] for e in seen) == list(STATIONS)
    assert all(e["available_ts_ns"] == run + 3 * HOUR + 50 * MIN for e in seen)


# ------------------------------------------------------------------------------- obs


def _obs_body(station: str, stamps: list[tuple[int, str]]) -> bytes:
    import datetime as dt

    feats = [
        {
            "properties": {
                "timestamp": dt.datetime.fromtimestamp(t / 1e9, dt.UTC).isoformat(),
                "rawMessage": raw,
            }
        }
        for t, raw in stamps
    ]
    return json.dumps({"features": feats}).encode()


class ObsFeed:
    def __init__(self, clock: FakeClock, rec: Recorder, stamps: dict[str, list[tuple[int, str]]]):
        self.clock, self.rec, self.stamps = clock, rec, stamps

    def __call__(self, station: str) -> Any:
        self.rec.calls.append(("obs", station, self.clock()))
        return col.FetchedPayload(
            _obs_body(station, self.stamps.get(station, [])), self.clock(), None, "nws"
        )


def test_obs_records_only_routine_reports_at_the_pinned_minute_and_flags_history_late(
    tmp_path: Path,
) -> None:
    now = DAY + 18 * HOUR + 58 * MIN
    fresh = DAY + 18 * HOUR + 56 * MIN  # KSFO routine minute :56, 2 min old
    old = DAY + 12 * HOUR + 56 * MIN  # history on the first poll
    stamps = {
        "KSFO": [
            (fresh, "KSFO 071856Z 28010KT 10SM CLR 15/08 A3000 RMK AO2 T01500080"),
            (old, "KSFO 071256Z ..."),
            (DAY + 18 * HOUR + 30 * MIN, "KSFO 071830Z ..."),  # off-minute
            (DAY + 17 * HOUR + 56 * MIN, "SPECI KSFO 071756Z ..."),  # special at the minute
        ]
    }
    clock, rec = FakeClock(now), Recorder()
    ctx = make_ctx(tmp_path, clock, rec, fetch_obs=ObsFeed(clock, rec, stamps))
    report = col.run_cycle("obs", ctx)
    assert report.status is col.CycleStatus.COLLECTED
    seen = [e for e in _events(tmp_path, OBS_SOURCE) if e["kind"] == "seen"]
    by_run = {e["run_ts_ns"]: e for e in seen}
    assert set(by_run) == {fresh, old}
    assert by_run[fresh]["late"] is False and by_run[fresh]["routine"] is True
    ksfo_fetch = next(c[2] for c in rec.calls if c[1] == "KSFO")
    assert by_run[fresh]["available_ts_ns"] == ksfo_fetch >= now
    assert by_run[old]["late"] is True
    # idempotent: a rerun adds nothing
    col.run_cycle("obs", ctx)
    assert len([e for e in _events(tmp_path, OBS_SOURCE) if e["kind"] == "seen"]) == 2
    assert {c[1] for c in rec.calls} == set(STATIONS)


def test_obs_unparsable_payload_is_refused_not_recorded(tmp_path: Path) -> None:
    clock, rec = FakeClock(DAY + 10 * HOUR), Recorder()

    def bad(_station: str) -> Any:
        return col.FetchedPayload(b"<html>", clock(), None, "nws")

    report = col.run_cycle("obs", make_ctx(tmp_path, clock, rec, fetch_obs=bad))
    assert report.status is col.CycleStatus.REFUSED
    assert not [e for e in _events(tmp_path, OBS_SOURCE) if e["kind"] == "seen"]


# ------------------------------------------------------------------------ guards / adapters


@pytest.mark.parametrize("source", ["lav", "mos", "obs"])
def test_new_legs_skip_a_firing_inside_the_launch_window(tmp_path: Path, source: str) -> None:
    clock, rec = FakeClock(DAY + 16 * HOUR + 40 * MIN), Recorder()
    report = col.run_cycle(source, make_ctx(tmp_path, clock, rec))
    assert report.status is col.CycleStatus.SKIPPED_WINDOW


def test_lav_adapter_url_params_and_user_agent_match_the_backfill_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = DAY + 6 * HOUR
    mock = install_mock_http(
        monkeypatch, lambda _r: httpx.Response(200, content=_csv("KSFO", run, "LAV"))
    )
    fetch = col.default_lav_fetcher(lambda: run + 40 * MIN, check_proxy_env=False)
    payload = fetch("KSFO", run)
    request = mock.requests[0]
    url = urlsplit(str(request.url))
    assert (url.scheme, url.netloc, url.path) == (
        "https",
        "mesonet.agron.iastate.edu",
        "/cgi-bin/request/mos.py",
    )
    query = {k: v[0] for k, v in parse_qs(url.query).items()}
    assert query["model"] == "LAV" and query["station"] == "KSFO" and query["format"] == "csv"
    assert query["sts"] == "2026-10-07T06:00Z"
    assert request.method == "GET"
    assert request.headers["user-agent"] == col.COLLECTOR_USER_AGENT
    assert "@" not in col.COLLECTOR_USER_AGENT
    assert payload.host_tag == "iem" and payload.last_modified is None


def test_mos_adapter_requests_the_gfs_model(monkeypatch: pytest.MonkeyPatch) -> None:
    run = DAY + 12 * HOUR
    mock = install_mock_http(
        monkeypatch, lambda _r: httpx.Response(200, content=_csv("KNYC", run, "GFS"))
    )
    fetch = col.default_mos_fetcher(lambda: run + 4 * HOUR, check_proxy_env=False)
    fetch("KNYC", run)
    query = {k: v[0] for k, v in parse_qs(urlsplit(str(mock.requests[0].url)).query).items()}
    assert query["model"] == "GFS" and query["station"] == "KNYC"


@pytest.mark.parametrize("name", ["default_lav_fetcher", "default_mos_fetcher"])
def test_iem_adapters_map_an_empty_or_other_run_response_to_not_published(
    monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    run = DAY + 12 * HOUR
    install_mock_http(
        monkeypatch,
        lambda _r: httpx.Response(200, content=b"runtime,ftime,model,tmp,station\n"),
    )
    fetch = getattr(col, name)(lambda: run + 4 * HOUR, check_proxy_env=False)
    with pytest.raises(col.NotPublishedError):
        fetch("KSFO", run)


def test_obs_adapter_uses_the_live_observation_client_and_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock = install_mock_http(
        monkeypatch, lambda _r: httpx.Response(200, content=b'{"features": []}')
    )
    fetch = col.default_obs_fetcher(lambda: DAY, check_proxy_env=False)
    payload = fetch("KSFO")
    request = mock.requests[0]
    assert str(request.url) == "https://api.weather.gov/stations/KSFO/observations?limit=12"
    assert request.headers["user-agent"] == col.COLLECTOR_USER_AGENT
    assert payload.host_tag == "nws"
    assert request.headers["accept"] == "application/geo+json"


def test_obs_request_is_in_parity_with_the_live_observation_ingest() -> None:
    live = build_observation_transport(lambda: DAY, check_proxy_env=False)
    assert type(live) is NwsObservationTransport
    mirror = ObsTransport(
        clock=lambda: DAY, user_agent=col.COLLECTOR_USER_AGENT, check_proxy_env=False
    )
    for station in STATIONS:
        assert mirror.station_observations_url(station, 12) == live._station_observations_url(
            station, 12
        )
    assert mirror._base_url == live._base_url
    assert mirror._allowed_hosts == live._allowed_hosts
    assert mirror._accept == live._accept
    assert mirror._max_body_bytes == live._max_body_bytes
    for closed in ("fetch_discovery_list", "fetch_product"):
        with pytest.raises(NotImplementedError):
            asyncio.run(getattr(mirror, closed)("x"))
    with pytest.raises(ValueError):
        mirror.station_observations_url("KORD", 12)


# ------------------------------------------------------- obs: shared-host load and back-off


def _quiet_feed(clock: FakeClock, rec: Recorder) -> Any:
    def feed(station: str) -> Any:
        rec.calls.append(("obs", station, clock()))
        return col.FetchedPayload(b'{"features": []}', clock(), None, "nws")

    return feed


def test_obs_polls_only_stations_inside_their_report_window(tmp_path: Path) -> None:
    clock, rec = FakeClock(DAY + 7 * HOUR + 40 * MIN), Recorder()  # past every window
    ctx = make_ctx(tmp_path, clock, rec, fetch_obs=_quiet_feed(clock, rec))
    assert col.run_cycle("obs", ctx).status is col.CycleStatus.UNCHANGED
    assert rec.calls == []
    clock.now = DAY + 7 * HOUR + 54 * MIN  # KNYC (:51) and KLAX/KMDW/KMIA (:53) open, KSFO not yet
    col.run_cycle("obs", ctx)
    assert {c[1] for c in rec.calls} == {"KLAX", "KMDW", "KMIA", "KNYC"}
    rec.calls.clear()
    clock.now = DAY + 7 * HOUR + 58 * MIN
    col.run_cycle("obs", ctx)
    assert {c[1] for c in rec.calls} == set(STATIONS)


def test_obs_stops_polling_a_station_once_its_report_is_seen(tmp_path: Path) -> None:
    report = DAY + 7 * HOUR + 56 * MIN
    clock, rec = FakeClock(report + 3 * MIN), Recorder()
    stamps = {"KSFO": [(report, "KSFO 080756Z ...")]}
    ctx = make_ctx(tmp_path, clock, rec, fetch_obs=ObsFeed(clock, rec, stamps))
    col.run_cycle("obs", ctx)
    rec.calls.clear()
    clock.now = report + 6 * MIN
    col.run_cycle("obs", ctx)
    assert "KSFO" not in {c[1] for c in rec.calls}


def test_obs_request_ceiling_per_station_per_hour_and_day_is_far_below_the_live_actor(
    tmp_path: Path,
) -> None:
    """Worst case (no report ever seen): replay every real timer firing of a day."""
    from tests.unit.test_us_source_collector_unit import _firing_seconds

    clock, rec = FakeClock(DAY), Recorder()
    ctx = make_ctx(tmp_path, clock, rec, fetch_obs=_quiet_feed(clock, rec))
    for second in _firing_seconds("obs"):
        clock.now = DAY + second * 10**9
        col.run_cycle("obs", ctx)
    per_day = {s: [c for c in rec.calls if c[1] == s] for s in STATIONS}
    live_actor_per_day = 288  # 300 s poll interval
    for station, calls in per_day.items():
        assert 0 < len(calls) <= 240 < live_actor_per_day, station
        hours: dict[int, int] = {}
        for call in calls:
            hours[(call[2] - DAY) // HOUR] = hours.get((call[2] - DAY) // HOUR, 0) + 1
        assert max(hours.values()) <= 10, (station, hours)


@pytest.mark.parametrize("failure", ["429", "503"])
def test_obs_backs_off_after_a_rate_limit_or_server_error(tmp_path: Path, failure: str) -> None:
    from breezy.ingest.http import RateLimitedError, ServerError

    clock, rec = FakeClock(DAY + 7 * HOUR + 58 * MIN), Recorder()
    state = {"fail": True}

    def feed(station: str) -> Any:
        rec.calls.append(("obs", station, clock()))
        if state["fail"] and len(rec.calls) == 2:
            raise (
                RateLimitedError("429", retry_after=None)
                if failure == "429"
                else ServerError("503", status_code=503)
            )
        return col.FetchedPayload(b'{"features": []}', clock(), None, "nws")

    ctx = make_ctx(tmp_path, clock, rec, fetch_obs=feed)
    report = col.run_cycle("obs", ctx)
    assert report.status is col.CycleStatus.ERROR
    assert len(rec.calls) == 2  # the pass stopped at the failing station
    assert [a[0] for a in rec.alerts] == ["rate_limited"]
    assert any(e["kind"] == "backoff" for e in _events(tmp_path, OBS_SOURCE))
    state["fail"] = False
    clock.now += 10 * MIN  # still silent
    assert col.run_cycle("obs", ctx).status is col.CycleStatus.UNCHANGED
    assert len(rec.calls) == 2
    clock.now = DAY + 8 * HOUR + 54 * MIN  # the back-off (30 min) is over, next window is open
    col.run_cycle("obs", ctx)
    assert len(rec.calls) > 2


def test_iem_csv_has_run_accepts_date_only_runtime_at_midnight() -> None:
    """IEM prints a midnight-only runtime column as a bare date (all rows share 00:00:00)."""
    legs = sys.modules["us_source_lag_legs"]
    csv_text = "runtime,ftime,model,station\n2026-10-07,2026-10-07 06:00:00,GFS,KLAX\n"
    assert legs.iem_csv_has_run(csv_text, "KLAX", DAY) is True
    assert legs.iem_csv_has_run(csv_text, "KMIA", DAY) is False
    # a bare date is not a 06Z run
    assert legs.iem_csv_has_run(csv_text, "KLAX", DAY + 6 * HOUR) is False
