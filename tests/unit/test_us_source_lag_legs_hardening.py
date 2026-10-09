"""RED-first tests: C1 legs hardening (never-seen alert, IEM back-off, refusal dedupe, obs
transport back-off) on top of the lav / mos / obs legs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from breezy.ingest.http import ForbiddenError, RateLimitedError, ServerError
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

DAY = ts(2026, 10, 7)
SOURCES = {
    "lav": col.SOURCE_KEYS["lav"],
    "mos": col.SOURCE_KEYS["mos"],
    "obs": col.SOURCE_KEYS["obs"],
}


def _stale(rec: Recorder) -> list[tuple[str, str, str]]:
    return [a for a in rec.alerts if a[0] == "stale_source"]


def _missing(_station: str, _run: int) -> Any:
    raise col.NotPublishedError("no row")


def _quiet_obs(clock: FakeClock) -> Any:
    def feed(_station: str) -> Any:
        return col.FetchedPayload(b'{"features": []}', clock(), None, "nws")

    return feed


# ----------------------------------------------------------------- 1. never-seen alert


@pytest.mark.parametrize(
    ("source", "start", "grace_h"),
    [("lav", DAY + 6 * HOUR + 20 * MIN, 3), ("mos", DAY + 2 * HOUR + 10 * MIN, 12)],
)
def test_iem_leg_with_only_misses_alerts_after_its_grace_once_per_six_hours(
    tmp_path: Path, source: str, start: int, grace_h: int
) -> None:
    clock, rec = FakeClock(start), Recorder()
    feeds: dict[str, Any] = {f"fetch_{source}": _missing}
    ctx = make_ctx(tmp_path, clock, rec, **feeds)
    col.run_cycle(source, ctx)
    clock.now = start + (grace_h * HOUR - 10 * MIN)
    col.run_cycle(source, ctx)
    assert _stale(rec) == []
    clock.now = start + grace_h * HOUR + 5 * MIN
    col.run_cycle(source, ctx)
    assert [a[1] for a in _stale(rec)] == [SOURCES[source]]
    clock.now += 1 * HOUR
    col.run_cycle(source, ctx)
    assert len(_stale(rec)) == 1  # deduped inside 6 h
    clock.now += 6 * HOUR
    col.run_cycle(source, ctx)
    assert len(_stale(rec)) == 2


def test_obs_leg_that_never_sees_a_routine_report_alerts_after_three_hours(
    tmp_path: Path,
) -> None:
    clock, rec = FakeClock(DAY + 7 * HOUR + 58 * MIN), Recorder()
    ctx = make_ctx(tmp_path, clock, rec, fetch_obs=_quiet_obs(clock))
    col.run_cycle("obs", ctx)
    clock.now = DAY + 9 * HOUR + 58 * MIN
    col.run_cycle("obs", ctx)
    assert _stale(rec) == []
    clock.now = DAY + 10 * HOUR + 58 * MIN
    col.run_cycle("obs", ctx)
    assert [a[1] for a in _stale(rec)] == [SOURCES["obs"]]


def test_undelivered_never_seen_alert_is_retried_next_cycle(tmp_path: Path) -> None:
    clock, rec = FakeClock(DAY + 6 * HOUR + 20 * MIN), Recorder()
    ctx = make_ctx(tmp_path, clock, rec, fetch_lav=_missing)
    col.run_cycle("lav", ctx)
    rec.ok = False
    clock.now += 4 * HOUR
    col.run_cycle("lav", ctx)
    clock.now += 10 * MIN
    col.run_cycle("lav", ctx)
    assert len(_stale(rec)) == 2


def test_leg_that_has_seen_rows_never_raises_the_never_seen_alert(tmp_path: Path) -> None:
    clock, rec = FakeClock(DAY + 6 * HOUR + 20 * MIN), Recorder()

    def feed(station: str, run: int) -> Any:
        from tests.unit.test_us_source_lag_legs import _csv

        return col.FetchedPayload(_csv(station, run, "LAV"), clock(), None, "iem")

    ctx = make_ctx(tmp_path, clock, rec, fetch_lav=feed)
    col.run_cycle("lav", ctx)
    clock.now += 2 * HOUR  # inside the 4 h stale limit
    col.run_cycle("lav", ctx)
    assert _stale(rec) == []


# ----------------------------------------------------------------- 2. IEM back-off


@pytest.mark.parametrize("source", ["lav", "mos"])
@pytest.mark.parametrize("failure", ["429", "503", "403", "ratelimited"])
def test_iem_leg_backs_off_on_rate_limit_or_server_error(
    tmp_path: Path, source: str, failure: str
) -> None:
    start = DAY + 8 * HOUR + 20 * MIN
    clock, rec = FakeClock(start), Recorder()
    calls: list[str] = []
    state = {"fail": True}

    def feed(station: str, _run: int) -> Any:
        calls.append(station)
        if state["fail"] and len(calls) == 2:
            raise {
                "429": RateLimitedError("429", retry_after=None),
                "503": ServerError("503", status_code=503),
                "403": ForbiddenError("403"),
                "ratelimited": RateLimitedError("slow down", retry_after="60"),
            }[failure]
        raise col.NotPublishedError("no row")

    feeds: dict[str, Any] = {f"fetch_{source}": feed}
    ctx = make_ctx(tmp_path, clock, rec, **feeds)
    report = col.run_cycle(source, ctx)
    rate_limited = failure in {"429", "ratelimited"}
    # a 429 back-off is expected, alerted and self-healing: BACKED_OFF, exit 0 (5xx/403 stay errors)
    assert report.status is (col.CycleStatus.BACKED_OFF if rate_limited else col.CycleStatus.ERROR)
    assert report.exit_code == (0 if rate_limited else 1)
    assert len(calls) == 2  # the pass stopped at the failing station
    assert [a[0] for a in rec.alerts] == ["rate_limited"]
    assert any(e["kind"] == "backoff" for e in _events(tmp_path, SOURCES[source]))
    state["fail"] = False
    clock.now += 10 * MIN  # still silent
    col.run_cycle(source, ctx)
    assert len(calls) == 2
    clock.now += 25 * MIN  # 30 min over
    col.run_cycle(source, ctx)
    assert len(calls) > 2


# ----------------------------------------------------------------- 3. refusal dedupe


def test_obs_shape_refusal_alerts_once_per_six_hours_but_every_refusal_is_ledgered(
    tmp_path: Path,
) -> None:
    clock, rec = FakeClock(DAY + 1 * HOUR + 58 * MIN), Recorder()

    def bad(_station: str) -> Any:
        return col.FetchedPayload(b"<html>", clock(), None, "nws")

    ctx = make_ctx(tmp_path, clock, rec, fetch_obs=bad)
    col.run_cycle("obs", ctx)
    clock.now += 5 * MIN
    col.run_cycle("obs", ctx)
    refused = [e for e in _events(tmp_path, SOURCES["obs"]) if e["kind"] == "refused"]
    assert len(refused) == 10
    assert len([a for a in rec.alerts if a[0] == "payload_refused"]) == 1
    clock.now = DAY + 7 * HOUR + 58 * MIN
    col.run_cycle("obs", ctx)
    assert len([a for a in rec.alerts if a[0] == "payload_refused"]) == 2


# ----------------------------------------------------------------- 4. obs transport back-off


def test_obs_backs_off_after_three_consecutive_failed_firings(tmp_path: Path) -> None:
    clock, rec = FakeClock(DAY + 7 * HOUR + 58 * MIN), Recorder()
    calls: list[str] = []

    def feed(station: str) -> Any:
        calls.append(station)
        raise OSError("timed out")

    ctx = make_ctx(tmp_path, clock, rec, fetch_obs=feed)
    for hour in (7, 8):
        clock.now = DAY + hour * HOUR + 58 * MIN
        col.run_cycle("obs", ctx)
    assert not [a for a in rec.alerts if a[0] == "rate_limited"]
    clock.now = DAY + 9 * HOUR + 58 * MIN
    col.run_cycle("obs", ctx)
    assert [a[0] for a in rec.alerts if a[0] == "rate_limited"] == ["rate_limited"]
    assert any(e["kind"] == "backoff" for e in _events(tmp_path, SOURCES["obs"]))
    seen_calls = len(calls)
    clock.now = DAY + 10 * HOUR + 5 * MIN  # inside the 30 min back-off, windows still open
    col.run_cycle("obs", ctx)
    assert len(calls) == seen_calls


def test_obs_successful_firing_resets_the_transport_failure_streak(tmp_path: Path) -> None:
    clock, rec = FakeClock(DAY + 7 * HOUR + 58 * MIN), Recorder()
    state = {"ok": False}
    quiet = _quiet_obs(clock)

    def feed(station: str) -> Any:
        if state["ok"]:
            return quiet(station)
        raise OSError("timed out")

    ctx = make_ctx(tmp_path, clock, rec, fetch_obs=feed)
    plan = [False, False, True, False, False]
    for index, ok in enumerate(plan):
        state["ok"] = ok
        clock.now = DAY + (7 + index) * HOUR + 58 * MIN
        col.run_cycle("obs", ctx)
    assert not [a for a in rec.alerts if a[0] == "rate_limited"]


# ----------------------------------------------------------------- 5. 429 back-off exits 0


@pytest.mark.parametrize("source", ["lav", "mos"])
def test_a_pure_429_backoff_exits_zero_with_backed_off_status_alert_and_ledger_record(
    tmp_path: Path, source: str
) -> None:
    clock, rec = FakeClock(DAY + 8 * HOUR + 20 * MIN), Recorder()

    def feed(_station: str, _run: int) -> Any:
        raise RateLimitedError("429", retry_after=None)

    feeds: dict[str, Any] = {f"fetch_{source}": feed}
    ctx = make_ctx(tmp_path, clock, rec, **feeds)
    report = col.run_cycle(source, ctx)
    assert report.status is col.CycleStatus.BACKED_OFF
    assert report.exit_code == 0
    assert [a[0] for a in rec.alerts] == ["rate_limited"]
    assert [e for e in _events(tmp_path, SOURCES[source]) if e["kind"] == "backoff"]


def test_a_429_on_one_station_and_a_transport_error_on_another_still_exits_one(
    tmp_path: Path,
) -> None:
    clock, rec = FakeClock(DAY + 8 * HOUR + 20 * MIN), Recorder()
    calls: list[str] = []

    def feed(station: str, _run: int) -> Any:
        calls.append(station)
        if len(calls) == 1:
            raise OSError("timed out")
        raise RateLimitedError("429", retry_after=None)

    report = col.run_cycle("lav", make_ctx(tmp_path, clock, rec, fetch_lav=feed))
    assert report.status is col.CycleStatus.ERROR
    assert report.exit_code == 1
    assert [a[0] for a in rec.alerts] == ["rate_limited"]


def test_a_429_after_collected_rows_reports_backed_off_not_collected(tmp_path: Path) -> None:
    from tests.unit.test_us_source_lag_legs import _csv

    clock, rec = FakeClock(DAY + 8 * HOUR + 20 * MIN), Recorder()
    calls: list[str] = []

    def feed(station: str, run: int) -> Any:
        calls.append(station)
        if len(calls) == 1:
            return col.FetchedPayload(_csv(station, run, "LAV"), clock(), None, "iem")
        raise RateLimitedError("429", retry_after=None)

    report = col.run_cycle("lav", make_ctx(tmp_path, clock, rec, fetch_lav=feed))
    assert report.status is col.CycleStatus.BACKED_OFF
    assert report.exit_code == 0
