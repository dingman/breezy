"""AUD-02 WP-D1: the unattended discovery venue pull.

Every test uses a fake client (no egress) and a temp log directory --
matching the plan's own instruction ("using a fake client and no egress").
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Self

import pytest

from breezy.adapters.polymarket_us.provider import MARKET_BY_SLUG_PATH, MARKET_LIST_PATH
from scripts.analysis.discovery_venue_pull import (
    FollowState,
    build_discovery_provider,
    find_initial_trigger,
    main,
    poll_node_logs_once,
    run_discovery_pull,
)
from tests.unit.test_polymarket_us_discovery import market_with_slug


def _weather_market(slug: str, city_name: str, climate_date: str) -> dict[str, Any]:
    """A structurally-VALID market (real captured fixture, re-keyed): keeps
    the base fixture's prose corroboration for its ``lt79f`` bounds token
    (``market_with_slug``'s own contract), only the slug and question change.
    """
    market = market_with_slug(slug)
    market["question"] = f"Highest temperature in {city_name} on {climate_date}?"
    return market


_MARKET = _weather_market("tc-temp-nychigh-2026-09-23-lt79f", "New York City", "2026-09-23")


@dataclass
class FakeClient:
    """No ``get_authenticated`` method exists on this object at all -- an
    accidental call to anything but ``get_public`` fails the test with a
    plain ``AttributeError`` rather than needing a special assertion."""

    page_for_offset: Callable[[int], Mapping[str, Any]]
    by_slug: dict[str, Mapping[str, Any]] = field(default_factory=dict)
    calls: list[tuple[str, dict[str, Any] | None, str]] = field(default_factory=list)

    async def get_public(
        self, path: str, *, query: Mapping[str, Any] | None = None, quota_key: str
    ) -> Mapping[str, Any]:
        self.calls.append((path, dict(query) if query else None, quota_key))
        if path == MARKET_LIST_PATH:
            offset = query.get("offset", 0) if query else 0
            assert isinstance(offset, int)
            return self.page_for_offset(offset)
        for slug, payload in self.by_slug.items():
            if slug in path:
                return {"market": payload}
        raise AssertionError(f"unexpected by-slug GET: {path}")


def _plain_line(ts: str, level: str, component: str, message: str) -> str:
    return f"{ts}Z [{level}] {component}: {message}"


def _summary_plain(ts: str, cycle: str, *, subscribed: tuple[str, ...] = ()) -> str:
    return _plain_line(
        ts,
        "INFO",
        "BREEZY-L001.DataClient-POLYMARKET_US",
        f"Polymarket.us discovery cycle {cycle}: subscribed={subscribed!r} "
        "unsubscribed=() blocked_missing_cache=()",
    )


# ---------------------------------------------------------------------------
# Provider wiring
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pull_queries_match_provider_discover_markets() -> None:
    client = FakeClient(page_for_offset=lambda offset: {"markets": [_MARKET]})
    provider, recorder = build_discovery_provider(client)
    await provider.load_all_async()
    assert recorder.pages == [{"markets": [_MARKET]}]
    assert len(client.calls) == 1
    path, query, quota_key = client.calls[0]
    assert path == MARKET_LIST_PATH
    assert quota_key == "discovery"
    assert query is not None
    # PolymarketUSMarketDiscoveryConfig()'s own defaults (config.py:190-198),
    # never a value this test copies independently of that config.
    assert query["limit"] == 100
    assert query["offset"] == 0
    assert query["active"] is True
    assert query["closed"] is False
    assert query["archived"] is False


@pytest.mark.asyncio
async def test_pull_page_cap_is_incomplete() -> None:
    full_page = {"markets": [_MARKET] * 100}
    client = FakeClient(page_for_offset=lambda offset: full_page)
    provider, _recorder = build_discovery_provider(client)
    with pytest.raises(Exception, match="exceeded the 50-page cap"):
        await provider.load_all_async()


@pytest.mark.asyncio
async def test_pull_sends_no_auth_header() -> None:
    # FakeClient exposes ONLY get_public -- a call to any signed/authenticated
    # method would raise AttributeError and fail this test outright.
    client = FakeClient(page_for_offset=lambda offset: {"markets": [_MARKET]})
    provider, _recorder = build_discovery_provider(client)
    await provider.load_all_async()
    assert provider.active_market_slugs == (_MARKET["slug"],)


# ---------------------------------------------------------------------------
# Trigger / orchestration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pull_waits_for_initial_cycle_then_pulls(tmp_path: Path) -> None:
    log_dir = tmp_path
    path = log_dir / "breezy-trade-20260923T165046Z.log"
    path.write_text("", encoding="utf-8")

    sleep_calls: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        # Blocking I/O is deliberate: this fake `sleep` simulates the node
        # itself appending its initial summary while the pull waits, not
        # real async filesystem contention.
        sleep_calls.append(seconds)
        with open(path, "a", encoding="utf-8") as fh:  # noqa: ASYNC230
            fh.write(_summary_plain("2026-09-23T16:50:51.000000000", "initial") + "\n")

    client = FakeClient(page_for_offset=lambda offset: {"markets": [_MARKET]})
    clock_values = iter(range(20))

    outcome = await run_discovery_pull(
        client=client,
        log_dir=log_dir,
        node_active_slugs=(),
        since_ns=0,
        deadline_ns=10**15,
        now_ns=lambda: next(clock_values),
        sleep=fake_sleep,
    )
    assert sleep_calls == [10.0]
    assert outcome.paired_ts_ns is not None
    assert outcome.complete is True
    assert outcome.venue_active == (_MARKET["slug"],)


@pytest.mark.asyncio
async def test_no_initial_by_deadline_writes_no_pull(tmp_path: Path) -> None:
    log_dir = tmp_path
    (log_dir / "breezy-trade-20260923T165046Z.log").write_text("", encoding="utf-8")
    client = FakeClient(page_for_offset=lambda offset: {"markets": [_MARKET]})

    async def fail_sleep(seconds: float) -> None:
        raise AssertionError("sleep should never be reached once the deadline has passed")

    outcome = await run_discovery_pull(
        client=client,
        log_dir=log_dir,
        node_active_slugs=(),
        since_ns=0,
        deadline_ns=0,
        now_ns=lambda: 1,
        sleep=fail_sleep,
    )
    assert outcome.reason == "NO-PULL"
    assert outcome.complete is False
    assert outcome.paired_ts_ns is None
    assert client.calls == []


# ---------------------------------------------------------------------------
# Follow
# ---------------------------------------------------------------------------


def test_follow_from_offset_zero_picks_newest_spawn(tmp_path: Path) -> None:
    old = tmp_path / "breezy-trade-20260918T170000Z.log"
    old.write_text(
        _summary_plain("2026-09-18T17:00:01.000000000", "initial") + "\n", encoding="utf-8"
    )
    new = tmp_path / "breezy-trade-20260918T173000Z.log"
    new.write_text(
        _summary_plain("2026-09-18T17:30:01.000000000", "initial") + "\n", encoding="utf-8"
    )

    _state, records, truncated = poll_node_logs_once(tmp_path, FollowState())
    assert not truncated
    trigger = find_initial_trigger(records, since_ns=0)
    assert trigger is not None
    assert trigger.source == new


def test_follow_detects_truncation(tmp_path: Path) -> None:
    path = tmp_path / "breezy-trade-20260923T165046Z.log"
    line1 = _summary_plain("2026-09-23T16:50:51.000000000", "initial")
    path.write_text(line1 + "\n", encoding="utf-8")

    state, records, truncated = poll_node_logs_once(tmp_path, FollowState())
    assert len(records) == 1
    assert not truncated

    path.write_text(line1[:10], encoding="utf-8")  # shrunk -- truncated on disk
    _state, _records, truncated = poll_node_logs_once(tmp_path, state)
    assert path in truncated


def test_follow_does_not_consume_a_partial_trailing_line(tmp_path: Path) -> None:
    path = tmp_path / "breezy-trade-20260923T165046Z.log"
    full_line = _summary_plain("2026-09-23T16:50:51.000000000", "initial")
    path.write_text(full_line[:40], encoding="utf-8")  # cut mid-line, no trailing newline

    state, records, truncated = poll_node_logs_once(tmp_path, FollowState())
    assert records == ()
    assert not truncated

    with open(path, "a", encoding="utf-8") as fh:
        fh.write(full_line[40:] + "\n")
    _state, records, _truncated = poll_node_logs_once(tmp_path, state)
    assert len(records) == 1
    assert records[0].message.startswith("Polymarket.us discovery cycle initial")


# ---------------------------------------------------------------------------
# End-to-end CLI
# ---------------------------------------------------------------------------


def test_cli_computes_node_active_and_gets_missing_slugs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The pull CLI must replay N from the triggering log file (never
    ``()``) and GET every slug in N - V by slug (review fix: `main` used to
    hardcode `node_active_slugs=()`, so this by-slug GET never fired)."""
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    out_dir = tmp_path / "evidence"

    slug_in_venue = _MARKET["slug"]
    slug_missing_from_venue = "tc-temp-miahigh-2026-09-23-lt79f"

    log_path = log_dir / "breezy-trade-20260923T165046Z.log"
    log_path.write_text(
        "\n".join(
            [
                _summary_plain(
                    "2026-09-23T16:36:00.000000000",
                    "initial",
                    subscribed=(slug_in_venue, slug_missing_from_venue),
                )
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    client = FakeClient(
        page_for_offset=lambda offset: {"markets": [_MARKET]},
        by_slug={slug_missing_from_venue: {"slug": slug_missing_from_venue, "closed": True}},
    )

    monkeypatch.setattr(
        "scripts.venue.fee_drift_evidence_pull.build_default_client",
        lambda *, user_agent: client,
    )

    now = datetime(2026, 9, 23, 16, 40, tzinfo=UTC)
    exit_code = main(
        [
            "--node-log-dir",
            str(log_dir),
            "--out-dir",
            str(out_dir),
            "--user-agent",
            "wp-d1-test",
        ],
        now=now,
    )
    assert exit_code == 0

    payload = json.loads((out_dir / "2026-09-23.json").read_text(encoding="utf-8"))
    node_active = set(payload["node_active"])
    assert node_active == {slug_in_venue, slug_missing_from_venue}
    assert payload["venue_active"] == [slug_in_venue]

    by_slug_calls = [call for call in client.calls if call[0] != MARKET_LIST_PATH]
    assert len(by_slug_calls) == 1
    assert by_slug_calls[0][0] == MARKET_BY_SLUG_PATH.format(slug=slug_missing_from_venue)

    by_slug_lookup = payload["by_slug_lookup"]
    assert by_slug_lookup[slug_missing_from_venue]["slug"] == slug_missing_from_venue
    assert slug_in_venue not in by_slug_lookup


# ---------------------------------------------------------------------------
# O1: the first poll must not read the node's historical logs
# ---------------------------------------------------------------------------

_SINCE_NS = int(datetime(2026, 10, 3, 16, 35, tzinfo=UTC).timestamp() * 1_000_000_000)
_OLD_LOG_BYTES = 64 * 1024 * 1024


class _CountingFile:
    """Delegating binary-file proxy that counts bytes handed to the reader."""

    def __init__(self, inner: Any, sink: dict[str, int], name: str) -> None:
        self._inner = inner
        self._sink = sink
        self._name = name

    def __enter__(self) -> Self:
        self._inner.__enter__()
        return self

    def __exit__(self, *exc: object) -> None:
        self._inner.__exit__(*exc)

    def _count(self, data: bytes) -> bytes:
        self._sink[self._name] = self._sink.get(self._name, 0) + len(data)
        return data

    def seek(self, *args: Any) -> int:
        return int(self._inner.seek(*args))

    def read(self, *args: Any) -> bytes:
        return self._count(self._inner.read(*args))

    def readline(self, *args: Any) -> bytes:
        return self._count(self._inner.readline(*args))

    def __iter__(self) -> Any:
        for chunk in self._inner:
            yield self._count(chunk)


def _count_reads(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    import builtins

    import scripts.analysis.discovery_venue_pull as module

    sink: dict[str, int] = {}
    real_open = builtins.open

    def counting_open(file: Any, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        handle = real_open(file, mode, *args, **kwargs)
        if "b" not in mode:
            return handle
        return _CountingFile(handle, sink, Path(file).name)

    monkeypatch.setattr(module, "open", counting_open, raising=False)
    return sink


def _plant_logs(tmp_path: Path, *, old_summary_ts: str) -> tuple[Path, Path]:
    old = tmp_path / "breezy-trade-20261002T205521Z.log"
    with open(old, "wb") as fh:
        fh.write((_summary_plain(old_summary_ts, "initial") + "\n").encode())
        fh.truncate(_OLD_LOG_BYTES)  # sparse: stands in for a ~1 GB historical log
    today = tmp_path / "breezy-trade-20261003T165045Z.log"
    today.write_text(
        _summary_plain("2026-10-03T16:50:49.000000000", "initial") + "\n", encoding="utf-8"
    )
    return old, today


def test_first_poll_reads_no_bytes_from_a_historical_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    old, today = _plant_logs(tmp_path, old_summary_ts="2026-10-02T20:55:25.000000000")
    sink = _count_reads(monkeypatch)

    _state, records, _truncated = poll_node_logs_once(tmp_path, FollowState(), since_ns=_SINCE_NS)

    trigger = find_initial_trigger(records, since_ns=_SINCE_NS)
    assert trigger is not None
    assert trigger.source == today
    assert sink.get(old.name, 0) == 0
    assert sink[today.name] > 0


def test_stale_summary_in_a_historical_log_is_never_paired_with_todays_launch(
    tmp_path: Path,
) -> None:
    # A historical (yesterday-stamped) file whose summary line CLAIMS today's
    # window must still be ignored; only today's launch file can pair.
    old, today = _plant_logs(tmp_path, old_summary_ts="2026-10-03T16:40:00.000000000")

    _state, records, _truncated = poll_node_logs_once(tmp_path, FollowState(), since_ns=_SINCE_NS)

    assert old not in {r.source for r in records}
    trigger = find_initial_trigger(records, since_ns=_SINCE_NS)
    assert trigger is not None
    assert trigger.source == today


def test_historical_log_is_still_followed_from_eof_on_later_polls(tmp_path: Path) -> None:
    old, _today = _plant_logs(tmp_path, old_summary_ts="2026-10-02T20:55:25.000000000")
    state, _records, _truncated = poll_node_logs_once(tmp_path, FollowState(), since_ns=_SINCE_NS)

    appended = _plain_line(
        "2026-10-03T16:55:00.000000000",
        "INFO",
        "BREEZY-L001.DataClient-POLYMARKET_US",
        "later line",
    )
    with open(old, "ab") as fh:
        fh.write(("\n" + appended + "\n").encode())

    _state, records, _truncated = poll_node_logs_once(tmp_path, state, since_ns=_SINCE_NS)

    assert [r.message for r in records if r.source == old] == ["later line"]
