"""F13-C1 S4: the collector cycle driver (plan r3 H4/H5/LOW, R11, R17, R28-R32, R34).

No network: every fetcher is an injected fake, and the two default-transport wiring tests
install an ``httpx.MockTransport`` (``tests.support.mock_http``). Clocks are injected, so a
test can stand at 16:29:59 or 17:10:00 without waiting.
"""

from __future__ import annotations

import ast
import datetime as dt
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any, ClassVar, Self

import httpx
import pytest

from breezy.ingest.us_source_availability import freeze_lag
from breezy.persistence.archive_cache import ArchiveCache, ArchiveRequest
from breezy.persistence.us_source_request import (
    normalised_request,
    pfm_afos_request,
    revision_request,
)
from breezy.persistence.us_source_revision_store import UsSourceRevisionStore
from tests.support.mock_http import install_mock_http

REPO_ROOT = Path(__file__).resolve().parents[2]
COLLECT_DIR = REPO_ROOT / "scripts" / "collect"
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "us_sources"


def _load(name: str) -> ModuleType:
    """Load a ``scripts/collect`` module under its bare name (the collector imports siblings
    by bare name, so one module object must serve both)."""
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, COLLECT_DIR / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


col = _load("us_source_collector")
alert_mod = _load("us_source_alert")
guards = _load("us_source_guards")
ledger_mod = _load("us_source_ledger")
norm_mod = _load("us_source_norm")

NS = 1_000_000_000
MIN = 60 * NS
HOUR = 60 * MIN
LAMP_SOURCE = col.SOURCE_KEYS["lamp"]
PFM_SOURCE = col.SOURCE_KEYS["pfm"]
NBP_SOURCE = col.SOURCE_KEYS["nbp"]
LAMP_LAST_MODIFIED = "Mon, 05 Oct 2026 23:35:44 GMT"


def ts(y: int, mo: int, d: int, h: int = 0, mi: int = 0, s: int = 0) -> int:
    return int(dt.datetime(y, mo, d, h, mi, s, tzinfo=dt.UTC).timestamp()) * NS


RUN_2330 = ts(2026, 10, 5, 23, 30)


def _fixture(name: str) -> bytes:
    raw = (FIXTURES / name).read_text(encoding="utf-8")
    return "".join(ln for ln in raw.splitlines(keepends=True) if not ln.startswith("#")).encode()


class FakeClock:
    def __init__(self, now_ns: int) -> None:
        self.now = now_ns

    def __call__(self) -> int:
        return self.now

    def timestamp_ns(self) -> int:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += int(seconds * NS)


class Recorder:
    """Collects alerts; fetchers append their calls to ``calls``."""

    def __init__(self) -> None:
        self.alerts: list[tuple[str, str, str]] = []
        self.calls: list[tuple[Any, ...]] = []

    def alert(self, event: str, source: str, detail: str) -> None:
        self.alerts.append((event, source, detail))


def _no_read(_request: ArchiveRequest) -> bytes:
    raise AssertionError("the archive must only be read in this scenario")


def _no_fetch(*_args: Any) -> Any:
    raise AssertionError("no fetch may happen in this scenario")


def make_ctx(
    tmp_path: Path,
    clock: FakeClock,
    rec: Recorder,
    *,
    lamp: Callable[..., Any] = _no_fetch,
    pfm: Callable[..., Any] = _no_fetch,
    nbp: Callable[..., Any] = _no_fetch,
    ntp: Callable[[], int | None] = lambda: 0,
    free_bytes: int = 500 * 2**30,
    **overrides: Any,
) -> Any:
    kwargs: dict[str, Any] = {
        "root": tmp_path / "archive",
        "clock": clock,
        "sleep": clock.sleep,
        "fetch_lamp": lamp,
        "fetch_pfm": pfm,
        "fetch_nbp": nbp,
        "measure_ntp_offset": ntp,
        "free_bytes": lambda _root: free_bytes,
        "alert": rec.alert,
        "poll_interval_s": 60.0,
    }
    kwargs.update(overrides)
    (tmp_path / "archive").mkdir(exist_ok=True)
    return col.CycleContext(**kwargs)


class LampFeed:
    """Publishes the real HH30 fixture at ``publish_at_ns`` (None: always published)."""

    def __init__(
        self,
        clock: FakeClock,
        rec: Recorder,
        *,
        publish_at_ns: int | None = None,
        last_modified: str | None = LAMP_LAST_MODIFIED,
        ext_body: bytes | None = None,
    ) -> None:
        self.clock = clock
        self.rec = rec
        self.publish_at_ns = publish_at_ns
        self.last_modified = last_modified
        self.ext_body = ext_body
        self.body = _fixture("lamp_lavtxt_real_20261005_2330z.txt")

    def __call__(self, run_ts_ns: int, extended: bool) -> Any:
        self.rec.calls.append(("lamp", run_ts_ns, extended, self.clock()))
        if self.publish_at_ns is not None and self.clock() < self.publish_at_ns:
            raise col.NotPublishedError("404")
        body = self.ext_body if (extended and self.ext_body is not None) else self.body
        return col.FetchedPayload(body, self.clock(), self.last_modified, "nomads")


def _store(tmp_path: Path, clock: FakeClock) -> UsSourceRevisionStore:
    return UsSourceRevisionStore(tmp_path / "archive", clock)


def _events(tmp_path: Path, source: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = ledger_mod.PollLedger(tmp_path / "archive").events(source)
    return events


def _lamp_cycle(
    tmp_path: Path, now_ns: int, **feed_kwargs: Any
) -> tuple[Any, FakeClock, Recorder, LampFeed]:
    clock = FakeClock(now_ns)
    rec = Recorder()
    feed = LampFeed(clock, rec, **feed_kwargs)
    report = col.run_cycle("lamp", make_ctx(tmp_path, clock, rec, lamp=feed))
    return report, clock, rec, feed


# ----------------------------------------------------------------------- LAMP happy path


def test_lamp_cycle_persists_raw_revision_zero_and_normalised_rows(tmp_path: Path) -> None:
    report, clock, rec, _feed = _lamp_cycle(tmp_path, RUN_2330 + 6 * MIN)

    assert report.status is col.CycleStatus.COLLECTED
    assert report.exit_code == 0
    store = _store(tmp_path, clock)
    revisions = store.revisions(LAMP_SOURCE, "ALL", RUN_2330, "lamp-lavtxt")
    assert [n for n, _ in revisions] == [0]
    raw_request = revision_request(LAMP_SOURCE, "ALL", RUN_2330, 0, model=None)
    cache = ArchiveCache(tmp_path / "archive", fetch=_no_read, clock=clock)
    raw = cache.read(raw_request)
    assert hashlib.sha256(raw).hexdigest() == revisions[0][1]
    rows = cache.read(normalised_request(raw_request)).decode().splitlines()
    assert rows[0].startswith("station,issued_at_utc,valid_time_utc,tmp_f,available_ts_ns,basis")
    assert any(row.startswith("KNYC,") for row in rows[1:])
    assert rec.alerts == []


def test_lamp_target_run_is_the_latest_hh30_run(tmp_path: Path) -> None:
    _report, _clock, rec, _feed = _lamp_cycle(tmp_path, RUN_2330 + 6 * MIN)
    assert rec.calls[0][1] == RUN_2330
    assert [c[2] for c in rec.calls] == [False, True]  # lavtxt then lavtxt_ext


def test_available_at_is_observed_header_never_assumed(tmp_path: Path) -> None:
    _lamp_cycle(tmp_path, RUN_2330 + 6 * MIN)
    seen = [e for e in _events(tmp_path, LAMP_SOURCE) if e["kind"] == "seen"]
    main = next(e for e in seen if e["station"] == "ALL")
    assert main["basis"] == "measured_header@nomads"
    assert main["available_ts_ns"] == ts(2026, 10, 5, 23, 35, 44)
    assert main["basis"] != "nominal_plus_conservative_lag"


def test_first_seen_basis_and_miss_interval_recorded(tmp_path: Path) -> None:
    start = RUN_2330 + 61 * NS
    report, _clock, _rec, feed = _lamp_cycle(
        tmp_path, start, publish_at_ns=RUN_2330 + 5 * MIN + 30 * NS, last_modified=None
    )
    assert report.status is col.CycleStatus.COLLECTED
    events = [e for e in _events(tmp_path, LAMP_SOURCE) if e["station"] == "ALL"]
    misses = [e for e in events if e["kind"] == "miss"]
    seen = next(e for e in events if e["kind"] == "seen")
    assert len(misses) >= 3
    assert seen["basis"] == "first_seen@nomads"
    assert seen["miss_ts_ns"] == misses[-1]["fetched_at_ns"] < seen["first_seen_ns"]
    assert seen["available_ts_ns"] == seen["first_seen_ns"]
    assert feed.publish_at_ns is not None and seen["first_seen_ns"] >= feed.publish_at_ns


def test_mirror_host_tagged_in_basis(tmp_path: Path) -> None:
    _lamp_cycle(tmp_path, RUN_2330 + 6 * MIN, last_modified=None)
    seen = next(e for e in _events(tmp_path, LAMP_SOURCE) if e["kind"] == "seen")
    assert seen["basis"].endswith("@nomads")


def test_lamp_never_published_in_window_records_misses_and_collects_nothing(
    tmp_path: Path,
) -> None:
    report, _clock, _rec, _feed = _lamp_cycle(
        tmp_path, RUN_2330 + 31 * MIN, publish_at_ns=RUN_2330 + 6 * HOUR
    )
    assert report.status is col.CycleStatus.NOT_PUBLISHED
    assert (
        _store(tmp_path, FakeClock(0)).revisions(LAMP_SOURCE, "ALL", RUN_2330, "lamp-lavtxt") == ()
    )
    assert [e["kind"] for e in _events(tmp_path, LAMP_SOURCE)] == ["miss"] * len(
        _events(tmp_path, LAMP_SOURCE)
    )


def test_lamp_ext_is_preserved_raw_even_when_it_does_not_normalise(tmp_path: Path) -> None:
    report, clock, rec, _feed = _lamp_cycle(
        tmp_path, RUN_2330 + 6 * MIN, ext_body=b"not a lamp bulletin\n"
    )
    assert report.status is col.CycleStatus.COLLECTED
    store = _store(tmp_path, clock)
    assert [n for n, _ in store.revisions(LAMP_SOURCE, "ALLEXT", RUN_2330, "lamp-lavtxt")] == [0]
    assert rec.alerts == []  # ext format is unverified; preservation, not alarm


def test_refused_lamp_payload_leaves_no_orphan_and_alerts(tmp_path: Path) -> None:
    clock = FakeClock(RUN_2330 + 6 * MIN)
    rec = Recorder()
    feed = LampFeed(clock, rec, ext_body=_fixture("lamp_lavtxt_real_20261005_2330z.txt"))
    feed.body = b"GARBAGE\nGARBAGE\n"
    report = col.run_cycle("lamp", make_ctx(tmp_path, clock, rec, lamp=feed))
    assert report.refused == 1
    assert _store(tmp_path, clock).revisions(LAMP_SOURCE, "ALL", RUN_2330, "lamp-lavtxt") == ()
    assert [a[0] for a in rec.alerts] == ["payload_refused"]
    assert not [
        e for e in _events(tmp_path, LAMP_SOURCE) if e["kind"] == "seen" and e["station"] == "ALL"
    ]


# ------------------------------------------------------------------------- idempotency


def test_rerun_never_duplicates_payload_or_manifest_entry(tmp_path: Path) -> None:
    _lamp_cycle(tmp_path, RUN_2330 + 6 * MIN)
    manifest = (tmp_path / "archive" / LAMP_SOURCE / "coverage.json").read_bytes()
    seen_before = [e for e in _events(tmp_path, LAMP_SOURCE) if e["kind"] == "seen"]

    report, _clock, rec, _feed = _lamp_cycle(tmp_path, RUN_2330 + 36 * MIN)

    assert report.status is col.CycleStatus.UNCHANGED
    assert rec.calls == []  # a stored run is never re-polled
    assert (tmp_path / "archive" / LAMP_SOURCE / "coverage.json").read_bytes() == manifest
    assert [e for e in _events(tmp_path, LAMP_SOURCE) if e["kind"] == "seen"] == seen_before


class SimulatedKill(BaseException):
    """Stands in for SIGKILL: not an Exception, so nothing in the driver may swallow it."""


def test_cycle_is_idempotent_after_midwrite_kill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = norm_mod.write_normalised
    killed = {"n": 0}

    def kill_once(*args: Any, **kwargs: Any) -> None:
        if killed["n"] == 0:
            killed["n"] = 1
            raise SimulatedKill
        real(*args, **kwargs)

    monkeypatch.setattr(norm_mod, "write_normalised", kill_once)
    clock = FakeClock(RUN_2330 + 6 * MIN)
    rec = Recorder()
    feed = LampFeed(clock, rec)
    with pytest.raises(SimulatedKill):
        col.run_cycle("lamp", make_ctx(tmp_path, clock, rec, lamp=feed))
    first_seen = [e for e in _events(tmp_path, LAMP_SOURCE) if e["kind"] == "seen"]
    assert len(first_seen) == 1  # the interval was recorded BEFORE the raw write

    clock.now += 31 * MIN
    report = col.run_cycle("lamp", make_ctx(tmp_path, clock, rec, lamp=feed))

    assert report.status in {col.CycleStatus.COLLECTED, col.CycleStatus.UNCHANGED}
    store = _store(tmp_path, clock)
    assert [n for n, _ in store.revisions(LAMP_SOURCE, "ALL", RUN_2330, "lamp-lavtxt")] == [0]
    raw_request = revision_request(LAMP_SOURCE, "ALL", RUN_2330, 0, model=None)
    cache = ArchiveCache(tmp_path / "archive", fetch=_no_read, clock=clock)
    assert not cache.missing(normalised_request(raw_request))
    seen_after = [
        e for e in _events(tmp_path, LAMP_SOURCE) if e["kind"] == "seen" and e["station"] == "ALL"
    ]
    assert len(seen_after) == 1  # never re-stamped by the rerun
    assert seen_after[0]["first_seen_ns"] == first_seen[0]["first_seen_ns"]


def test_ledger_tolerates_a_torn_final_line_and_repairs_it(tmp_path: Path) -> None:
    ledger = ledger_mod.PollLedger(tmp_path / "archive")
    ledger.record(LAMP_SOURCE, {"kind": "miss", "station": "ALL", "fetched_at_ns": 1})
    with ledger.path(LAMP_SOURCE).open("ab") as handle:
        handle.write(b'{"kind": "seen", "stat')  # killed mid-append
    assert [e["kind"] for e in ledger.events(LAMP_SOURCE)] == ["miss"]
    ledger.record(LAMP_SOURCE, {"kind": "miss", "station": "ALL", "fetched_at_ns": 2})
    assert [e["fetched_at_ns"] for e in ledger.events(LAMP_SOURCE)] == [1, 2]


# ----------------------------------------------------------------- the 16:30Z deadline


def test_clock_boundary_16_29_59_runs(tmp_path: Path) -> None:
    now = ts(2026, 10, 6, 16, 29, 59)
    assert guards.firing_decision(now) is guards.FiringDecision.RUN
    report, _clock, rec, _feed = _lamp_cycle(tmp_path, now, publish_at_ns=now + HOUR)
    assert report.status is not col.CycleStatus.SKIPPED_WINDOW
    assert all(call[3] <= now for call in rec.calls)  # no attempt may cross 16:30Z


def test_clock_boundary_16_30_00_skips(tmp_path: Path) -> None:
    now = ts(2026, 10, 6, 16, 30, 0)
    assert guards.firing_decision(now) is guards.FiringDecision.SKIP_WINDOW
    report, _clock, rec, _feed = _lamp_cycle(tmp_path, now)
    assert report.status is col.CycleStatus.SKIPPED_WINDOW
    assert report.exit_code == 0
    assert rec.calls == []
    assert not (tmp_path / "archive" / LAMP_SOURCE).exists()


def test_clock_boundary_17_09_59_skips(tmp_path: Path) -> None:
    now = ts(2026, 10, 6, 17, 9, 59)
    report, _clock, rec, _feed = _lamp_cycle(tmp_path, now)
    assert report.status is col.CycleStatus.SKIPPED_WINDOW
    assert rec.calls == []


def test_clock_boundary_17_10_00_runs_late_flagged(tmp_path: Path) -> None:
    now = ts(2026, 10, 6, 17, 10, 0)
    run_1630 = ts(2026, 10, 6, 16, 30)
    assert guards.firing_decision(now) is guards.FiringDecision.RUN
    report, clock, rec, _feed = _lamp_cycle(tmp_path, now, last_modified=None)

    assert report.status is col.CycleStatus.COLLECTED
    assert rec.calls[0][1] == run_1630  # the displaced 16:30 run, rerun at 17:10Z
    seen = next(e for e in _events(tmp_path, LAMP_SOURCE) if e["kind"] == "seen")
    assert seen["late"] is True
    raw_request = revision_request(LAMP_SOURCE, "ALL", run_1630, 0, model=None)
    cache = ArchiveCache(tmp_path / "archive", fetch=_no_read, clock=clock)
    header, *rows = cache.read(normalised_request(raw_request)).decode().splitlines()
    late_col = header.split(",").index("late")
    assert rows and all(row.split(",")[late_col] == "true" for row in rows)


def test_on_time_rows_are_not_flagged_late(tmp_path: Path) -> None:
    _lamp_cycle(tmp_path, RUN_2330 + 6 * MIN)
    seen = next(e for e in _events(tmp_path, LAMP_SOURCE) if e["kind"] == "seen")
    assert seen["late"] is False


def test_late_rows_excluded_from_lag_freeze_maximum(tmp_path: Path) -> None:
    ledger = ledger_mod.PollLedger(tmp_path / "archive")
    for run, lag, late in ((1, 8 * MIN, False), (2, 9 * MIN, False), (3, 45 * MIN, True)):
        ledger.record(
            LAMP_SOURCE,
            {
                "kind": "seen",
                "station": "ALL",
                "run_ts_ns": run * HOUR,
                "available_ts_ns": run * HOUR + lag,
                "late": late,
                "fetched_at_ns": run * HOUR + lag,
            },
        )
    samples = col.lag_samples(ledger, LAMP_SOURCE)
    frozen = freeze_lag(samples, LAMP_SOURCE)
    assert frozen.max_lag_ns == 9 * MIN
    assert (frozen.uncensored_n, frozen.late_n) == (2, 1)


def test_collector_enforces_deadline_in_process_via_launch_window_guard(tmp_path: Path) -> None:
    sources = [
        (COLLECT_DIR / name).read_text(encoding="utf-8")
        for name in ("us_source_collector.py", "us_source_guards.py")
    ]
    joined = "\n".join(sources)
    assert "launch_window_guard" in joined and "seconds_outside_launch_window" in joined

    start = ts(2026, 10, 6, 16, 20)  # displaced rerun polling toward the window
    report, _clock, rec, _feed = _lamp_cycle(tmp_path, start, publish_at_ns=start + 3 * HOUR)
    assert report.status is col.CycleStatus.DEADLINE
    assert report.exit_code == 0
    assert rec.calls, "the early attempts must have run"
    worst_case_end = max(call[3] for call in rec.calls) + guards.ATTEMPT_BUDGET_S * NS
    assert worst_case_end < ts(2026, 10, 6, 16, 30)


def test_attempt_never_starts_if_it_could_cross_16_30z() -> None:
    assert guards.attempt_allowed(ts(2026, 10, 6, 16, 20)) is True
    assert guards.attempt_allowed(ts(2026, 10, 6, 16, 29)) is False
    assert guards.attempt_allowed(ts(2026, 10, 6, 17, 10)) is True


def test_overlapping_run_skipped_by_flock(tmp_path: Path) -> None:
    clock = FakeClock(RUN_2330 + 6 * MIN)
    rec = Recorder()
    ctx = make_ctx(tmp_path, clock, rec, lamp=LampFeed(clock, rec))
    holder = UsSourceRevisionStore(tmp_path / "archive", clock)
    with holder.unit_lock(LAMP_SOURCE):
        report = col.run_cycle("lamp", ctx)
    assert report.status is col.CycleStatus.SKIPPED_LOCKED
    assert report.exit_code == 0
    assert rec.calls == []


# ----------------------------------------------------------------------------- PFM


class PfmFeed:
    WFO_FILES: ClassVar[dict[str, str]] = {
        "OKX": "pfm_okx_real_20261006.txt",
        "LOX": "pfm_lox_real_20261006.txt",
        "LOT": "pfm_lot_real_20261006.txt",
        "MTR": "pfm_mtr_real_20261006.txt",
        "MFL": "pfm_mfl_real_20261006.txt",
    }

    def __init__(self, clock: FakeClock, rec: Recorder) -> None:
        self.clock = clock
        self.rec = rec
        self.override: dict[str, bytes] = {}

    def __call__(self, wfo: str) -> Any:
        self.rec.calls.append(("pfm", wfo, self.clock()))
        body = self.override.get(wfo) or _fixture(self.WFO_FILES[wfo])
        return col.FetchedPayload(body, self.clock(), None, "iem")


def _pfm_cycle(
    tmp_path: Path, now_ns: int, feed_setup: Callable[[PfmFeed], None] | None = None
) -> tuple[Any, FakeClock, Recorder, PfmFeed]:
    clock = FakeClock(now_ns)
    rec = Recorder()
    feed = PfmFeed(clock, rec)
    if feed_setup:
        feed_setup(feed)
    report = col.run_cycle("pfm", make_ctx(tmp_path, clock, rec, pfm=feed))
    return report, clock, rec, feed


PFM_NOW = ts(2026, 10, 6, 2, 11, 30)
OKX_ISSUED = ts(2026, 10, 5, 19, 1)


def test_pfm_cycle_stores_one_revision_per_station_keyed_by_issuance(tmp_path: Path) -> None:
    report, clock, rec, _feed = _pfm_cycle(tmp_path, PFM_NOW)
    assert report.status is col.CycleStatus.COLLECTED
    store = _store(tmp_path, clock)
    revisions = store.revisions(PFM_SOURCE, "KNYC", OKX_ISSUED, "pfm")
    assert [n for n, _ in revisions] == [0]
    assert {c[1] for c in rec.calls} == set(PfmFeed.WFO_FILES)
    cache = ArchiveCache(tmp_path / "archive", fetch=_no_read, clock=clock)
    request = pfm_afos_request("KNYC", OKX_ISSUED)
    header, *rows = cache.read(normalised_request(request)).decode().splitlines()
    assert "max_f" in header.split(",") and len(rows) >= 7
    seen = next(e for e in _events(tmp_path, PFM_SOURCE) if e["station"] == "KNYC")
    assert seen["basis"] == "wmo_header"
    assert seen["available_ts_ns"] == OKX_ISSUED
    assert seen["first_seen_ns"] == PFM_NOW  # IEM first-seen is recorded beside the WMO time


def test_pfm_unchanged_issuance_is_not_stored_twice(tmp_path: Path) -> None:
    _pfm_cycle(tmp_path, PFM_NOW)
    report, clock, _rec, _feed = _pfm_cycle(tmp_path, PFM_NOW + HOUR)
    assert report.status is col.CycleStatus.UNCHANGED
    revisions = _store(tmp_path, clock).revisions(PFM_SOURCE, "KNYC", OKX_ISSUED, "pfm")
    assert [n for n, _ in revisions] == [0]
    assert len([e for e in _events(tmp_path, PFM_SOURCE) if e["station"] == "KNYC"]) == 1


def test_pfm_changed_payload_for_same_issuance_appends_a_revision(tmp_path: Path) -> None:
    _pfm_cycle(tmp_path, PFM_NOW)

    def revise(feed: PfmFeed) -> None:
        feed.override["OKX"] = _fixture(PfmFeed.WFO_FILES["OKX"]) + b"\n"

    report, clock, _rec, _feed = _pfm_cycle(tmp_path, PFM_NOW + HOUR, revise)
    assert report.status is col.CycleStatus.COLLECTED
    revisions = _store(tmp_path, clock).revisions(PFM_SOURCE, "KNYC", OKX_ISSUED, "pfm")
    assert [n for n, _ in revisions] == [0, 1]


def test_pfm_refused_payload_alerts_and_other_stations_still_collect(tmp_path: Path) -> None:
    def break_lot(feed: PfmFeed) -> None:
        feed.override["LOT"] = b"FOUS51 KLOT 051901\nnot a forecast\n"

    report, clock, rec, _feed = _pfm_cycle(tmp_path, PFM_NOW, break_lot)
    assert report.status is col.CycleStatus.COLLECTED
    assert report.refused == 1
    assert [a[0] for a in rec.alerts] == ["payload_refused"]
    assert _store(tmp_path, clock).revisions(PFM_SOURCE, "KNYC", OKX_ISSUED, "pfm")
    cache = ArchiveCache(tmp_path / "archive", fetch=_no_read, clock=clock)
    assert {e.station for e in cache.entries(PFM_SOURCE)} == {"KNYC", "KLAX", "KSFO", "KMIA"}


# ----------------------------------------------------------------------------- NBP


class NbpFeed:
    def __init__(self, clock: FakeClock, rec: Recorder, publish_at_ns: int | None) -> None:
        self.clock = clock
        self.rec = rec
        self.publish_at_ns = publish_at_ns

    def __call__(self, cycle_date: dt.date, cycle_hour: int) -> Any:
        self.rec.calls.append(("nbp", cycle_date, cycle_hour, self.clock()))
        if self.publish_at_ns is not None and self.clock() < self.publish_at_ns:
            raise col.NotPublishedError("404 on both hosts")
        return col.FetchedPayload(
            b"NBP bulletin text\n", self.clock(), "Mon, 05 Oct 2026 14:15:47 GMT", "s3"
        )


def test_nbp_observes_availability_only_and_stops_after_first_success(tmp_path: Path) -> None:
    now = ts(2026, 10, 5, 14, 5)  # the 13Z cycle, one hour in
    clock = FakeClock(now)
    rec = Recorder()
    feed = NbpFeed(clock, rec, publish_at_ns=ts(2026, 10, 5, 14, 14))
    report = col.run_cycle("nbp", make_ctx(tmp_path, clock, rec, nbp=feed))

    assert report.status is col.CycleStatus.COLLECTED
    cycle_calls = [c for c in rec.calls if c[0] == "nbp"]
    assert {c[1:3] for c in cycle_calls} == {(dt.date(2026, 10, 5), 13)}
    successes = [e for e in _events(tmp_path, NBP_SOURCE) if e["kind"] == "seen"]
    assert len(successes) == 1  # polling stopped after the first success
    assert successes[0]["basis"] == "measured_header@s3"
    assert successes[0]["available_ts_ns"] == ts(2026, 10, 5, 14, 15, 47)
    assert successes[0]["miss_ts_ns"] is not None
    # C1 never writes NBP rows anywhere but its own ledger.
    assert not (tmp_path / "archive" / NBP_SOURCE / "coverage.json").exists()


def test_nbp_stations_argument_is_knyc_inclusive() -> None:
    assert "KNYC" in col.NBP_STATIONS
    assert {"KLAX", "KMDW", "KMIA", "KSFO"} <= col.NBP_STATIONS


# ------------------------------------------------------- LOW: NTP, disk, alerts, stale


def test_ntp_offset_recorded_and_excess_refuses(tmp_path: Path) -> None:
    report, _clock, _rec, _feed = _lamp_cycle(tmp_path, RUN_2330 + 6 * MIN)
    assert report.status is col.CycleStatus.COLLECTED
    seen = next(e for e in _events(tmp_path, LAMP_SOURCE) if e["kind"] == "seen")
    assert seen["ntp_offset_ns"] == 0

    clock = FakeClock(RUN_2330 + 6 * MIN)
    rec = Recorder()
    refused_root = tmp_path / "refused"
    refused_root.mkdir()
    ctx = make_ctx(refused_root, clock, rec, lamp=LampFeed(clock, rec), ntp=lambda: 5 * NS)
    refused = col.run_cycle("lamp", ctx)
    assert refused.status is col.CycleStatus.REFUSED_GUARD
    assert refused.exit_code == 2
    assert rec.calls == []
    assert [a[0] for a in rec.alerts] == ["ntp_offset_excess"]


def test_ntp_offset_negative_excess_also_refuses() -> None:
    with pytest.raises(guards.NtpOffsetExceededError):
        guards.check_ntp_offset(-2 * NS, bound_ns=NS)
    guards.check_ntp_offset(NS, bound_ns=NS)  # the bound itself is inside


def test_unmeasurable_ntp_is_recorded_as_null_and_does_not_stop_collection(
    tmp_path: Path,
) -> None:
    clock = FakeClock(RUN_2330 + 6 * MIN)
    rec = Recorder()
    ctx = make_ctx(tmp_path, clock, rec, lamp=LampFeed(clock, rec), ntp=lambda: None)
    assert col.run_cycle("lamp", ctx).status is col.CycleStatus.COLLECTED
    seen = next(e for e in _events(tmp_path, LAMP_SOURCE) if e["kind"] == "seen")
    assert seen["ntp_offset_ns"] is None


def test_chronyc_tracking_parses_fast_and_slow_offsets() -> None:
    fast = "System time     : 0.000116181 seconds fast of NTP time\n"
    slow = "System time     : 0.250000000 seconds slow of NTP time\n"
    assert guards.parse_chronyc_tracking(fast) == 116_181
    assert guards.parse_chronyc_tracking(slow) == -250_000_000
    with pytest.raises(ValueError):
        guards.parse_chronyc_tracking("Reference ID : none\n")


def test_measure_ntp_offset_returns_none_when_chronyc_fails() -> None:
    def failing(*_a: Any, **_k: Any) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError("chronyc")

    assert guards.measure_ntp_offset_ns(run=failing) is None


def test_disk_guard_refuses_below_threshold(tmp_path: Path) -> None:
    clock = FakeClock(RUN_2330 + 6 * MIN)
    rec = Recorder()
    ctx = make_ctx(
        tmp_path,
        clock,
        rec,
        lamp=LampFeed(clock, rec),
        free_bytes=1 * 2**30,
        min_free_bytes=10 * 2**30,
    )
    report = col.run_cycle("lamp", ctx)
    assert report.status is col.CycleStatus.REFUSED_GUARD
    assert report.exit_code == 2
    assert rec.calls == []
    assert [a[0] for a in rec.alerts] == ["disk_guard_refused"]
    assert not (tmp_path / "archive" / LAMP_SOURCE).exists()
    with pytest.raises(guards.DiskGuardRefusedError):
        guards.check_disk(tmp_path, min_free_bytes=10, free_bytes=lambda _p: 9)
    guards.check_disk(tmp_path, min_free_bytes=10, free_bytes=lambda _p: 10)


def _seed_lamp_seen(root: Path, last_seen: int) -> None:
    root.mkdir()
    ledger_mod.PollLedger(root / "archive").record(
        LAMP_SOURCE,
        {"kind": "seen", "station": "ALL", "run_ts_ns": RUN_2330, "fetched_at_ns": last_seen},
    )


def test_stale_source_alerts_after_deadline(tmp_path: Path) -> None:
    last_seen = RUN_2330 + 8 * MIN
    stale_after = guards.STALE_AFTER_NS["lamp"]

    fresh_root = tmp_path / "fresh"
    _seed_lamp_seen(fresh_root, last_seen)
    fresh = FakeClock(last_seen + stale_after - NS)
    rec = Recorder()
    col.run_cycle("lamp", make_ctx(fresh_root, fresh, rec, lamp=LampFeed(fresh, rec)))
    assert [a for a in rec.alerts if a[0] == "stale_source"] == []

    stale_root = tmp_path / "stale"
    _seed_lamp_seen(stale_root, last_seen)
    stale = FakeClock(last_seen + stale_after + 2 * HOUR)
    rec2 = Recorder()
    feed = LampFeed(stale, rec2, publish_at_ns=stale() + 10 * HOUR)
    col.run_cycle("lamp", make_ctx(stale_root, stale, rec2, lamp=feed))
    assert [a[0] for a in rec2.alerts].count("stale_source") == 1
    assert LAMP_SOURCE in [a[1] for a in rec2.alerts]

    stale.now += 30 * MIN  # an immediate rerun does not repeat the alert
    rec3 = Recorder()
    col.run_cycle("lamp", make_ctx(stale_root, stale, rec3, lamp=feed))
    assert [a for a in rec3.alerts if a[0] == "stale_source"] == []


# ------------------------------------------------------------ alerts.env and the sink


def test_alerts_env_reader_parses_a_file_without_importing_runtime(tmp_path: Path) -> None:
    env = tmp_path / "alerts.env"
    env.write_text(
        "# comment\n\nBREEZY_ALERT_WEBHOOK_URL='https://hooks.example/abc'\nOTHER=1\n",
        encoding="utf-8",
    )
    values = guards.read_alerts_env(env)
    assert values["BREEZY_ALERT_WEBHOOK_URL"] == "https://hooks.example/abc"
    assert guards.alerts_env_key_names(env) == ("BREEZY_ALERT_WEBHOOK_URL", "OTHER")
    assert guards.read_alerts_env(tmp_path / "missing.env") == {}


def test_alerts_env_holds_only_alert_sink_keys_values_never_printed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    secret = "https://hooks.example/SECRET-PATH-12345"
    env = tmp_path / "alerts.env"
    env.write_text(f"BREEZY_ALERT_WEBHOOK_URL={secret}\n", encoding="utf-8")
    names = guards.alerts_env_key_names(env)
    assert set(names) <= {guards.ALERT_SINK_KEY}
    print(names)  # key NAMES are the only thing a verifier may print
    captured = capsys.readouterr()
    assert secret not in captured.out + captured.err
    real = Path.home() / ".config" / "breezy" / "alerts.env"
    if real.is_file():
        assert set(guards.alerts_env_key_names(real)) <= {guards.ALERT_SINK_KEY}


def test_alert_sink_is_a_path_or_config_key_with_no_network_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import socket

    def no_socket(*_a: Any, **_k: Any) -> None:
        raise AssertionError("resolving the sink must not touch the network")

    monkeypatch.setattr(socket, "socket", no_socket)
    monkeypatch.setattr(socket, "create_connection", no_socket)
    env = tmp_path / "alerts.env"
    env.write_text("BREEZY_ALERT_WEBHOOK_URL=https://hooks.example/x\n", encoding="utf-8")
    assert guards.resolve_webhook_url(env) == "https://hooks.example/x"
    assert guards.resolve_webhook_url(tmp_path / "absent.env") is None


def test_webhook_poster_refuses_non_https_and_sends_only_closed_keys() -> None:
    sent: list[Any] = []

    def opener(request: Any, timeout: float) -> Any:
        sent.append((request.full_url, request.get_method(), request.data, timeout))

        class _Response:
            status = 204

            def __enter__(self) -> Self:
                return self

            def __exit__(self, *_a: object) -> None:
                return None

        return _Response()

    assert alert_mod.post_alert("http://hooks.example/x", "e", "s", "d", opener=opener) is False
    assert sent == []
    assert alert_mod.post_alert(
        "https://hooks.example/x", "stale_source", "us-lamp-live", "d", opener=opener
    )
    url, method, data, _timeout = sent[0]
    assert (url, method) == ("https://hooks.example/x", "POST")
    assert set(json.loads(data)) == {"event", "source", "detail"}


def test_webhook_poster_never_raises_on_transport_failure(
    capsys: pytest.CaptureFixture[str],
) -> None:
    def broken(_request: Any, timeout: float) -> Any:
        raise OSError("connection refused: https://hooks.example/SECRET")

    assert (
        alert_mod.post_alert("https://hooks.example/SECRET", "e", "s", "d", opener=broken) is False
    )
    err = capsys.readouterr().err
    assert "SECRET" not in err


def test_user_agent_contains_project_alias_not_operator_email() -> None:
    agent = col.COLLECTOR_USER_AGENT
    assert "@" not in agent and "project" in agent
    assert agent.startswith("breezy-us-source-ingest/")


# ---------------------------------------------- default transports under MockTransport


def test_default_lamp_adapter_sends_explicit_user_agent_with_get_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = _fixture("lamp_lavtxt_real_20261005_2330z.txt").decode()
    mock = install_mock_http(
        monkeypatch,
        lambda _r: httpx.Response(200, content=body, headers={"last-modified": LAMP_LAST_MODIFIED}),
    )
    fetch = col.default_lamp_fetcher(lambda: RUN_2330 + 6 * MIN, check_proxy_env=False)
    payload = fetch(RUN_2330, False)

    assert payload.host_tag == "nomads"
    assert payload.last_modified == LAMP_LAST_MODIFIED
    assert payload.body == body.encode()
    request = mock.requests[0]
    assert request.method == "GET"
    assert request.headers["user-agent"] == col.COLLECTOR_USER_AGENT
    assert request.url.path.endswith("lmp.t2330z.lavtxt.ascii")


def test_default_lamp_adapter_maps_404_to_not_published(monkeypatch: pytest.MonkeyPatch) -> None:
    install_mock_http(monkeypatch, lambda _r: httpx.Response(404))
    fetch = col.default_lamp_fetcher(lambda: RUN_2330, check_proxy_env=False)
    with pytest.raises(col.NotPublishedError):
        fetch(RUN_2330, False)


def test_default_nbp_adapter_passes_knyc_stations_and_tags_the_serving_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = " KNYC   NBM V5.0 NBP GUIDANCE    10/05/2026  1300 UTC\n TXNP50 70\n"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host.endswith("amazonaws.com"):
            return httpx.Response(404)
        return httpx.Response(
            200, content=text, headers={"last-modified": "Mon, 05 Oct 2026 14:15:47 GMT"}
        )

    mock = install_mock_http(monkeypatch, handler)
    fetch = col.default_nbp_fetcher(lambda: ts(2026, 10, 5, 14, 20), check_proxy_env=False)
    payload = fetch(dt.date(2026, 10, 5), 13)

    assert payload.host_tag == "nomads"
    assert payload.last_modified == "Mon, 05 Oct 2026 14:15:47 GMT"
    assert [r.method for r in mock.requests] == ["GET", "GET"]
    assert all(r.headers["user-agent"] == col.COLLECTOR_USER_AGENT for r in mock.requests)
    assert b"KNYC" in payload.body


def test_default_nbp_adapter_maps_both_hosts_404_to_not_published(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_mock_http(monkeypatch, lambda _r: httpx.Response(404))
    fetch = col.default_nbp_fetcher(lambda: ts(2026, 10, 5, 14, 20), check_proxy_env=False)
    with pytest.raises(col.NotPublishedError):
        fetch(dt.date(2026, 10, 5), 13)


# ------------------------------------------------------------------- the CLI surface


def _run_script(
    *args: str, env_extra: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    env = {
        "PATH": "/usr/bin:/bin",
        "PYTHONPATH": str(REPO_ROOT / "src"),
        **(env_extra or {}),
    }
    python = os.environ.get("BREEZY_PYTHON", sys.executable)
    return subprocess.run(
        [python, str(COLLECT_DIR / "us_source_collector.py"), *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
        check=False,
    )


def test_collector_help_works() -> None:
    done = _run_script("--help")
    assert done.returncode == 0, done.stderr
    assert "--source" in done.stdout and "--archive-root" in done.stdout


def test_collector_imports_nothing_from_breezy_runtime() -> None:
    probe = (
        "import runpy, sys\n"
        f"sys.path.insert(0, {str(COLLECT_DIR)!r})\n"
        "import us_source_collector  # noqa\n"
        "print([m for m in sys.modules if m.split('.')[:2] == ['breezy', 'runtime']])\n"
    )
    python = os.environ.get("BREEZY_PYTHON", sys.executable)
    done = subprocess.run(
        [python, "-c", probe],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "PYTHONPATH": str(REPO_ROOT / "src")},
        timeout=120,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "[]"


def test_collector_modules_pass_the_user_agent_explicitly() -> None:
    text = (COLLECT_DIR / "us_source_collector.py").read_text(encoding="utf-8")
    tree = ast.parse(text)
    constructed = {
        node.func.id: {kw.arg for kw in node.keywords}
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in {"MdlLampTransport", "NbmQuantileTransport", "PacedIemTransport"}
    }
    assert set(constructed) == {"MdlLampTransport", "NbmQuantileTransport", "PacedIemTransport"}
    assert all("user_agent" in kwargs for kwargs in constructed.values())


def test_main_refuses_a_missing_archive_root_with_exit_2(tmp_path: Path) -> None:
    done = _run_script("--source", "lamp", "--archive-root", str(tmp_path / "does-not-exist"))
    assert done.returncode == 2
