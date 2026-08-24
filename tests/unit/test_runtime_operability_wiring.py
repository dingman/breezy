"""The composition root must make the health snapshot and alerts LIVE, and
must phase-shift each site's poll timer.

Two production defects are pinned here.

**Gap 1 -- inert observability.** ``NwsIngestActor`` exposes
``health_snapshot_path`` (default ``None`` -> writes nothing) and
``alert_sink`` (default ``None`` -> each Actor lazily resolves its OWN).
Nothing in ``breezy.runtime.composition`` set either, so a production
deployment wrote no snapshot file and, with a webhook configured, would have
built five ``httpx.Client``s and five TLS contexts whose transition/re-notify
dedupe fragmented across five independent ``AlertState`` trackers.

**Gap 2 -- no poll stagger.** All five Actors armed one timer with the same
interval and no offset, so they fired simultaneously: five concurrent bursts
to ``api.weather.gov`` under a single User-Agent, which is the documented
route into the UA trap (a latch that halts all five sites and clears only by
manual operator action).

Nothing here opens a socket, starts a ``TradingNode``, or reaches the
network, and no absolute date is hard-coded.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import ssl
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from breezy.ingest.config import NwsIngestActorConfig
from breezy.ingest.nws_actor import NwsIngestActor
from breezy.persistence.catalog import FilesystemLocality, FilesystemProbe
from breezy.runtime import health
from breezy.runtime.composition import (
    BreezyIngestRuntime,
    build_ingest_actors,
    ingest_runtime,
    site_snapshot_path,
    site_stagger_offset_seconds,
)
from breezy.runtime.settings import BreezyRuntimeSettings

FIVE_SITES: tuple[tuple[str, str], ...] = (
    ("polymarket_us", "NYC"),
    ("polymarket_us", "SFO"),
    ("polymarket_us", "MIA"),
    ("polymarket_us", "MDW"),
    ("polymarket_us", "LAX"),
)


def _local_probe(path: Path) -> FilesystemProbe:
    return FilesystemProbe(
        path=str(path),
        mount_point="/",
        fs_type="ext4",
        locality=FilesystemLocality.LOCAL,
        detail="fake probe",
    )


def _settings(
    tmp_path: Path,
    *,
    snapshot_dir: Path | None = None,
    poll_interval_seconds: int = 300,
) -> BreezyRuntimeSettings:
    return BreezyRuntimeSettings(
        trader_id="BREEZY-001",
        sites=FIVE_SITES,
        catalog_base=tmp_path / "catalog",
        state_db_path=tmp_path / "state" / "breezy.sqlite3",
        poll_interval_seconds=poll_interval_seconds,
        parse_timeout_ms=250,
        log_level="INFO",
        check_proxy_env=False,
        registry_path=None,
        health_snapshot_dir=snapshot_dir,
    )


class RecordingSink:
    """An `AlertSink` that records; identity is what the tests assert."""

    def __init__(self) -> None:
        self.payloads: list[health.AlertPayload] = []

    def emit(self, payload: health.AlertPayload) -> None:
        self.payloads.append(payload)


def _runtime(
    settings: BreezyRuntimeSettings,
    **kwargs: Any,
) -> Any:
    return ingest_runtime(settings, probe=_local_probe, **kwargs)


@pytest.fixture
def sink() -> RecordingSink:
    return RecordingSink()


@pytest.fixture
def runtime(
    tmp_path: Path, sink: RecordingSink
) -> Iterator[BreezyIngestRuntime]:
    settings = _settings(tmp_path, snapshot_dir=tmp_path / "health")
    with _runtime(settings, alert_sink_factory=lambda: sink) as rt:
        yield rt


def _shutdown(actors: tuple[NwsIngestActor, ...]) -> None:
    for actor in actors:
        actor.shutdown_executor()


def _register(actor: NwsIngestActor) -> Any:
    """Register `actor` against a `TestClock` via Nautilus's own `register_base`.

    `register_base` (`common/actor.pyx:691`) hard type-checks its four
    arguments, so the stubs come from Nautilus's `test_kit` rather than being
    hand-rolled. Nothing is started; only the clock slot is needed here.
    """
    from nautilus_trader.common.component import TestClock
    from nautilus_trader.test_kit.stubs.component import TestComponentStubs

    clock = TestClock()
    actor.register_base(
        portfolio=TestComponentStubs.portfolio(),
        msgbus=TestComponentStubs.msgbus(),
        cache=TestComponentStubs.cache(),
        clock=clock,
    )
    return clock


# ---------------------------------------------------------------------------
# Gap 2 -- deterministic per-site poll stagger
# ---------------------------------------------------------------------------


class TestPollStagger:
    def test_five_actors_get_five_distinct_offsets(
        self, runtime: BreezyIngestRuntime
    ) -> None:
        actors = build_ingest_actors(runtime)
        try:
            offsets = [a.config.stagger_offset_seconds for a in actors]
        finally:
            _shutdown(actors)

        assert len(offsets) == 5
        assert len(set(offsets)) == 5, offsets

    def test_offsets_are_spread_across_one_poll_interval(
        self, runtime: BreezyIngestRuntime
    ) -> None:
        actors = build_ingest_actors(runtime)
        try:
            offsets = sorted(a.config.stagger_offset_seconds for a in actors)
        finally:
            _shutdown(actors)

        assert offsets == [0, 60, 120, 180, 240]
        assert max(offsets) < runtime.settings.poll_interval_seconds

    def test_the_same_site_gets_the_same_offset_across_two_builds(
        self, tmp_path: Path, sink: RecordingSink
    ) -> None:
        """Deterministic and stable across restarts: two INDEPENDENT runtime
        builds (separate state DBs, separate shared-state slots) must assign
        each site the identical offset, or an incident cannot be reproduced.
        """
        first: dict[str, int] = {}
        second: dict[str, int] = {}
        for target, sub in ((first, "a"), (second, "b")):
            settings = _settings(tmp_path / sub, snapshot_dir=tmp_path / sub / "h")
            with _runtime(settings, alert_sink_factory=lambda: sink) as rt:
                actors = build_ingest_actors(rt)
                try:
                    for actor in actors:
                        target[str(actor.id)] = actor.config.stagger_offset_seconds
                finally:
                    _shutdown(actors)

        assert first == second
        assert len(set(first.values())) == 5

    def test_offset_helper_is_pure_and_deterministic(self) -> None:
        got = [site_stagger_offset_seconds(i, 5, 300) for i in range(5)]
        assert got == [0, 60, 120, 180, 240]
        assert got == [site_stagger_offset_seconds(i, 5, 300) for i in range(5)]

    def test_stagger_does_not_change_the_steady_state_interval(
        self, runtime: BreezyIngestRuntime
    ) -> None:
        """The offset is a PHASE shift only.

        Asserted against Nautilus's OWN timer state (`TestClock.next_time_ns`),
        not against a recording double, because the native `Clock.set_timer`
        `start_time=` parameter is the mechanism under test. First fire lands
        at `now + offset + interval`; every fire after that is exactly one
        `interval` later, so the steady-state cadence is untouched.
        """
        interval_ns = runtime.settings.poll_interval_seconds * 1_000_000_000
        actors = build_ingest_actors(runtime)
        try:
            firsts: list[int] = []
            for actor in actors:
                clock = _register(actor)
                actor._arm_timers()
                offset_ns = actor.config.stagger_offset_seconds * 1_000_000_000
                first = clock.next_time_ns(actor._poll_timer_name)
                assert first == offset_ns + interval_ns
                firsts.append(first)

                clock.advance_time(first)
                assert clock.next_time_ns(actor._poll_timer_name) == first + interval_ns
                clock.advance_time(first + interval_ns)
                assert clock.next_time_ns(actor._poll_timer_name) == first + 2 * interval_ns

            assert len(set(firsts)) == 5
        finally:
            _shutdown(actors)


# ---------------------------------------------------------------------------
# Gap 1a -- ONE process-wide alert sink, injected
# ---------------------------------------------------------------------------


class TestSharedAlertSink:
    def test_composition_injects_one_shared_sink_into_every_actor(
        self, runtime: BreezyIngestRuntime, sink: RecordingSink
    ) -> None:
        actors = build_ingest_actors(runtime)
        try:
            assert runtime.alert_sink is sink
            for actor in actors:
                assert actor.alert_sink is sink
            assert len({id(a.alert_sink) for a in actors}) == 1
        finally:
            _shutdown(actors)

    def test_no_webhook_sink_is_constructed_when_the_url_is_unset(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With `BREEZY_ALERT_WEBHOOK_URL` unset, the default factory must
        build a `LoggingAlertSink` -- no `httpx.Client`, no TLS context.
        """
        monkeypatch.delenv(health.ALERT_WEBHOOK_URL_ENV_VAR, raising=False)

        built: list[str] = []

        def _forbidden_client(*args: Any, **kwargs: Any) -> Any:
            built.append("httpx.Client")
            raise AssertionError("an httpx.Client was built with no webhook configured")

        def _forbidden_sink(*args: Any, **kwargs: Any) -> Any:
            built.append("WebhookAlertSink")
            raise AssertionError("a WebhookAlertSink was built with no webhook configured")

        # `_build_webhook_client` is the ONLY place `health` builds a TLS
        # context (`ssl.create_default_context`). Patching that function
        # rather than the shared `ssl` module keeps the assertion scoped to
        # this module: `breezy.ingest.http` legitimately builds its own TLS
        # context for the NWS transport during runtime construction.
        monkeypatch.setattr(health, "_build_webhook_client", _forbidden_client)
        monkeypatch.setattr(health, "WebhookAlertSink", _forbidden_sink)

        settings = _settings(tmp_path)
        with _runtime(settings) as rt:
            actors = build_ingest_actors(rt)
            try:
                assert isinstance(rt.alert_sink, health.LoggingAlertSink)
                for actor in actors:
                    assert actor.alert_sink is rt.alert_sink
            finally:
                _shutdown(actors)

        assert built == []


# ---------------------------------------------------------------------------
# Gap 1b -- per-site snapshot paths that cannot clobber each other
# ---------------------------------------------------------------------------


class TestSnapshotPaths:
    def test_every_actor_gets_a_distinct_snapshot_path_under_the_configured_dir(
        self, runtime: BreezyIngestRuntime
    ) -> None:
        actors = build_ingest_actors(runtime)
        try:
            paths = [a.health_snapshot_path for a in actors]
            assert all(p is not None for p in paths)
            assert len({str(p) for p in paths}) == 5
            snapshot_dir = runtime.settings.health_snapshot_dir
            assert snapshot_dir is not None
            for path in paths:
                assert path is not None
                assert path.parent == snapshot_dir
        finally:
            _shutdown(actors)

    def test_five_actors_writing_concurrently_do_not_clobber_each_other(
        self, runtime: BreezyIngestRuntime
    ) -> None:
        """The actual invariant of the per-site design: five snapshots written
        to the configured directory leave FIVE readable files, one per site.
        """
        actors = build_ingest_actors(runtime)
        try:
            for actor in actors:
                path = actor.health_snapshot_path
                assert path is not None
                health.write_snapshot_atomic(
                    path,
                    health.HealthSnapshot(
                        schema_version=health.SCHEMA_VERSION,
                        process_started_at_ns=1,
                        snapshot_at_ns=2,
                        trader_id="BREEZY-001",
                        sites=(),
                        ua_trap_latched=False,
                        alerts_emitted_this_cycle=0,
                    ),
                )
            snapshot_dir = runtime.settings.health_snapshot_dir
            assert snapshot_dir is not None
            written = sorted(p.name for p in snapshot_dir.glob("*.json"))
            assert len(written) == 5
            for name in written:
                json.loads((snapshot_dir / name).read_text())
        finally:
            _shutdown(actors)

    def test_snapshot_path_is_none_and_nothing_is_written_when_unconfigured(
        self, tmp_path: Path, sink: RecordingSink
    ) -> None:
        settings = _settings(tmp_path, snapshot_dir=None)
        with _runtime(settings, alert_sink_factory=lambda: sink) as rt:
            actors = build_ingest_actors(rt)
            try:
                assert all(a.health_snapshot_path is None for a in actors)
                # And nothing raised: an unset snapshot dir is a VALID
                # configuration, not a degraded one.
                assert rt.settings.health_snapshot_dir is None
            finally:
                _shutdown(actors)
        assert list(tmp_path.rglob("health-*.json")) == []
        assert list(tmp_path.rglob(".health-snapshot-*.tmp")) == []

    def test_site_snapshot_path_helper_is_deterministic_and_per_site(
        self, tmp_path: Path
    ) -> None:
        a = site_snapshot_path(tmp_path, "polymarket_us", "NYC")
        b = site_snapshot_path(tmp_path, "polymarket_us", "NYC")
        c = site_snapshot_path(tmp_path, "polymarket_us", "LAX")
        assert a == b
        assert a != c
        assert a.parent == tmp_path
        assert a.suffix == ".json"

    def test_site_snapshot_path_rejects_a_traversing_site_label(
        self, tmp_path: Path
    ) -> None:
        with pytest.raises(ValueError, match="unsafe"):
            site_snapshot_path(tmp_path, "polymarket_us", "../../etc/passwd")


# ---------------------------------------------------------------------------
# The Actor config carries the offset
# ---------------------------------------------------------------------------


def test_actor_config_stagger_offset_defaults_to_zero() -> None:
    config = NwsIngestActorConfig(venue="polymarket_us", city="NYC")
    assert config.stagger_offset_seconds == 0


# ---------------------------------------------------------------------------
# Alert dispatch must not block the event loop (latency non-propagation)
# ---------------------------------------------------------------------------


class SlowTracker:
    """An `AlertState` stand-in that DECIDES one payload without blocking.

    Mirrors the real class's shape: `evaluate` is the read-modify-write half
    (loop-thread confined, must stay fast) and `dispatch` is `evaluate` plus
    the blocking fan-out. Defining `evaluate` here is what lets the wiring
    confine the state mutation to the loop thread -- the previous stub had
    only `dispatch`, so the split raised `AttributeError`.
    """

    def __init__(self, block_s: float) -> None:
        self.block_s = block_s
        self.calls = 0

    def evaluate(self, conditions: Any, *, now_ns: int) -> tuple[health.AlertPayload, ...]:
        self.calls += 1
        return (
            health.AlertPayload(
                severity="CRITICAL", event="test", site="polymarket_us/NYC", detail="d"
            ),
        )

    def dispatch(self, sink: Any, conditions: Any, *, now_ns: int) -> int:
        payloads = self.evaluate(conditions, now_ns=now_ns)
        for payload in payloads:
            health.emit_alert(sink, payload)
        return len(payloads)


class SlowSink:
    """The blocking half, where the latency actually lives in production:
    `emit_alert -> WebhookAlertSink.emit -> httpx.Client.post`, whose default
    timeout is 5 seconds. No socket is opened; the block is a `time.sleep`,
    which is exactly as loop-hostile as a synchronous `post`.
    """

    def __init__(self, block_s: float) -> None:
        self.block_s = block_s
        self.emitted = 0

    def emit(self, payload: health.AlertPayload) -> None:
        self.emitted += 1
        time.sleep(self.block_s)


class RaisingTracker:
    def evaluate(self, conditions: Any, *, now_ns: int) -> tuple[health.AlertPayload, ...]:
        raise ssl.SSLError("certificate verify failed")

    def dispatch(self, sink: Any, conditions: Any, *, now_ns: int) -> int:
        raise ssl.SSLError("certificate verify failed")


class RaisingSink:
    def emit(self, payload: health.AlertPayload) -> None:
        raise ssl.SSLError("certificate verify failed")


@pytest.mark.asyncio
async def test_a_slow_alert_sink_does_not_stall_the_event_loop(
    runtime: BreezyIngestRuntime,
) -> None:
    """Latency non-propagation, the untested half of the containment contract.

    `emit_alert` already proves an EXCEPTION cannot escape into the poll path.
    Nothing proved a 5-second webhook could not hold the loop thread -- which
    is the incident case: several sites transitioning to blocked at once
    serialises the POSTs and delays every other site's final-overdue check.
    """
    actors = build_ingest_actors(runtime)
    try:
        actor = actors[0]
        _register(actor)
        tracker = SlowTracker(block_s=0.0)
        slow_sink = SlowSink(block_s=0.5)
        actor._alert_state = tracker  # type: ignore[assignment]
        actor.alert_sink = slow_sink

        ticks = 0
        running = True

        async def heartbeat() -> None:
            nonlocal ticks
            while running:
                ticks += 1
                await asyncio.sleep(0.005)

        beat = asyncio.create_task(heartbeat())
        try:
            await actor._emit_health(1, entries=(), revisions=())
        finally:
            running = False
            await beat

        assert tracker.calls == 1
        assert slow_sink.emitted == 1, "the slow sink was never actually reached"
        assert ticks >= 10, (
            f"the event loop advanced only {ticks} ticks while the sink blocked "
            "for 0.5s -- the sink fan-out is still running on the loop thread"
        )
    finally:
        _shutdown(actors)


@pytest.mark.asyncio
async def test_an_alert_sink_failure_still_never_reaches_the_poll_path(
    runtime: BreezyIngestRuntime,
) -> None:
    """Moving the dispatch off the loop must not lose the existing guarantee."""
    actors = build_ingest_actors(runtime)
    try:
        actor = actors[0]
        _register(actor)
        actor._alert_state = RaisingTracker()  # type: ignore[assignment]

        await actor.reconcile_and_report()  # must not raise
    finally:
        _shutdown(actors)


@pytest.mark.asyncio
async def test_a_raising_alert_sink_still_never_reaches_the_poll_path(
    runtime: BreezyIngestRuntime,
) -> None:
    """The containment contract's real shape after the evaluate/emit split:
    the failure is in the SINK, and `emit_alert` must still swallow it inside
    the executor rather than letting it surface as poll-cycle death.
    """
    actors = build_ingest_actors(runtime)
    try:
        actor = actors[0]
        _register(actor)
        actor._alert_state = SlowTracker(block_s=0.0)  # type: ignore[assignment]
        actor.alert_sink = RaisingSink()

        await actor.reconcile_and_report()  # must not raise
    finally:
        _shutdown(actors)


# ---------------------------------------------------------------------------
# End to end: the environment actually reaches the Actors
# ---------------------------------------------------------------------------


def test_the_snapshot_dir_env_var_reaches_every_actor(tmp_path: Path) -> None:
    """`load_settings` -> `ingest_runtime` -> `build_ingest_actors`, the exact
    path `runtime.cli` takes. Pinned end to end because the whole defect was
    a wiring gap: every individual component already worked.
    """
    from breezy.runtime.settings import load_settings

    snapshot_dir = tmp_path / "health"
    env = {
        "BREEZY_SITES": ",".join(f"{v}:{c}" for v, c in FIVE_SITES),
        "BREEZY_CATALOG_BASE": str(tmp_path / "catalog"),
        "BREEZY_HEALTH_SNAPSHOT_DIR": str(snapshot_dir),
    }
    settings = load_settings(env)
    assert settings.health_snapshot_dir == snapshot_dir

    sink = RecordingSink()
    with _runtime(settings, alert_sink_factory=lambda: sink) as rt:
        actors = build_ingest_actors(rt)
        try:
            assert {str(a.health_snapshot_path) for a in actors} == {
                # `.` separates venue from city, and is excluded from the
                # label alphabet, so the mapping is injective -- see
                # `site_snapshot_path`'s docstring and
                # `test_site_snapshot_path_is_injective_*`.
                str(snapshot_dir / f"health-{v}.{c}.json")
                for v, c in FIVE_SITES
            }
            assert all(a.alert_sink is sink for a in actors)
            assert sorted(a.config.stagger_offset_seconds for a in actors) == [
                0,
                60,
                120,
                180,
                240,
            ]
        finally:
            _shutdown(actors)


# ---------------------------------------------------------------------------
# Stagger vs. the cross-site 403 burst window
# ---------------------------------------------------------------------------


def test_stagger_spacing_stays_inside_the_cross_site_burst_window() -> None:
    """Staggering must not blind the cross-site 403 burst detector.

    `SharedIngestState`'s burst signal is process-wide and time-boxed:
    `DEFAULT_BURST_POLICY` (`ingest/gate.py:276-279`) fires when
    `site_threshold=2` DISTINCT sites report the same cause inside
    `window_ns=120s`. Before this change all five sites polled together, so a
    UA trap produced five 403s in one instant and tripped it immediately.
    With a phase shift, two ADJACENT sites now 403 `poll_interval /
    site_count` apart -- 60s on the 300s/5-site default -- which still fits
    inside the 120s window with 2x headroom, so a trap is still detected
    (just up to one spacing later).

    This is the invariant that must not silently break: raising
    `BREEZY_POLL_INTERVAL_SECONDS` far enough (e.g. to 900s with five sites)
    pushes adjacent spacing to 180s, past the window, and a genuine
    process-wide UA trap would stop being recognised as cross-site. That
    would be an invisible regression, so it fails here instead.
    """
    from breezy.ingest.gate import DEFAULT_BURST_POLICY

    site_count = len(FIVE_SITES)
    poll_interval = 300
    offsets = sorted(
        site_stagger_offset_seconds(i, site_count, poll_interval) for i in range(site_count)
    )
    spacings = [b - a for a, b in itertools.pairwise(offsets)]
    worst_spacing_ns = max(spacings) * 1_000_000_000

    assert DEFAULT_BURST_POLICY.site_threshold == 2
    assert worst_spacing_ns < DEFAULT_BURST_POLICY.window_ns, (
        f"adjacent sites are staggered {max(spacings)}s apart but the cross-site "
        f"burst window is only {DEFAULT_BURST_POLICY.window_ns / 1e9}s -- a "
        "process-wide UA trap would no longer register as cross-site"
    )


# ---------------------------------------------------------------------------
# `site_snapshot_path` must be INJECTIVE (review finding 1)
# ---------------------------------------------------------------------------


def test_site_snapshot_path_is_injective_across_the_venue_city_boundary(
    tmp_path: Path,
) -> None:
    """Two DIFFERENT sites must never resolve to one file.

    `POLYMARKET-US` is an ordinary venue value. If the separator between
    `venue` and `city` can also occur INSIDE a label, `("POLY-US", "NYC")`
    and `("POLY", "US-NYC")` collide, two Actors clobber one file every
    poll cycle, and a WEDGED site's file keeps receiving a fresh mtime and
    healthy contents from its sibling -- so the runbook's per-file staleness
    check reports healthy for a site that stopped collecting. That defeats
    the entire reason per-site files were chosen over an aggregator.
    """
    left = site_snapshot_path(tmp_path, "POLY-US", "NYC")
    right = site_snapshot_path(tmp_path, "POLY", "US-NYC")

    assert left != right, f"distinct sites collided onto {left}"


def test_site_snapshot_path_is_injective_over_a_grid_of_labels(tmp_path: Path) -> None:
    """Exhaustive over a small grid whose members are exactly the shapes
    that can alias under a naive `f"health-{venue}-{city}.json"`.
    """
    labels = ("A", "B", "A-B", "B-A", "A_B", "A-B-C", "AB")
    seen: dict[Path, tuple[str, str]] = {}
    for venue in labels:
        for city in labels:
            path = site_snapshot_path(tmp_path, venue, city)
            assert path not in seen, f"{(venue, city)} collided with {seen[path]} onto {path}"
            seen[path] = (venue, city)
    assert len(seen) == len(labels) ** 2


def test_site_snapshot_path_still_rejects_every_traversal_shape(tmp_path: Path) -> None:
    """The containment guard must not be weakened by the injectivity fix."""
    for bad in (
        "../../etc/cron.d",
        "/etc/passwd",
        "",
        ".",
        "..",
        "a/b",
        "a\x00b",
        "a\n",
        "a\r\n../x",
        "ａ",  # fullwidth
        "а",  # cyrillic homoglyph
        "a.b",
        "a b",
    ):
        with pytest.raises(ValueError, match="unsafe"):
            site_snapshot_path(tmp_path, "polymarket_us", bad)
        with pytest.raises(ValueError, match="unsafe"):
            site_snapshot_path(tmp_path, bad, "NYC")


# ---------------------------------------------------------------------------
# Label length bound (review finding 5)
# ---------------------------------------------------------------------------


def test_site_snapshot_path_rejects_an_overlong_label(tmp_path: Path) -> None:
    """An unbounded label yields a filename past NAME_MAX, so every write
    raises ENAMETOOLONG inside the executor and `reconcile_and_report`'s
    blanket `except Exception` swallows it -- the deployment starts clean
    and monitors a file that never exists. This is startup-known input, so
    it must fail loudly at composition instead.
    """
    with pytest.raises(ValueError, match="unsafe"):
        site_snapshot_path(tmp_path, "polymarket_us", "C" * 65)
    with pytest.raises(ValueError, match="unsafe"):
        site_snapshot_path(tmp_path, "V" * 65, "NYC")

    # The bound itself is accepted, and the resulting name stays inside the
    # 255-byte NAME_MAX every mainstream filesystem enforces.
    at_bound = site_snapshot_path(tmp_path, "V" * 64, "C" * 64)
    assert len(at_bound.name.encode("utf-8")) <= 255
