"""AUD-02 WP-D1: the unattended discovery venue pull.

Every test uses a fake client (no egress) and a temp log directory --
matching the plan's own instruction ("using a fake client and no egress").
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from breezy.adapters.polymarket_us.provider import MARKET_LIST_PATH
from scripts.analysis.discovery_venue_pull import (
    FollowState,
    build_discovery_provider,
    find_initial_trigger,
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
