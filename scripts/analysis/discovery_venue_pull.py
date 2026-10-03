"""AUD-02 WP-D1: unattended, unauthenticated Polymarket.us discovery pull.

Triggered by the trade node's own INITIAL discovery cycle (read from its log
FILE -- the node is a bare ``subprocess.Popen``, never a systemd unit, so
there is no journal for it), this script pages ``GET /v1/markets`` with the
SAME query the node's own discovery would use, records every raw page
verbatim, and GETs any node-side slug the page set is missing -- feeding
:mod:`scripts.analysis.discovery_set_equality`'s offline comparison.

Read-only: unauthenticated public GETs only (``PolymarketUSHttpClient.
get_public``, ``signer=None`` -- see
:func:`scripts.venue.fee_drift_evidence_pull.build_default_client`, reused
here rather than re-declared). Writes only under ``--out-dir``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, Protocol

from scripts.analysis.discovery_set_equality import (
    ANSI_RE,
    LINE_RE,
    NODE_LOG_GLOB,
    RELAUNCH_DEADLINE,
    SUMMARY_PREFIX_RE,
    WINDOW_START,
    NodeLogRecord,
    file_stamp,
    parse_ts_ns,
)

__all__ = [
    "FileCursor",
    "FollowState",
    "PageRecordingClient",
    "PublicReadClient",
    "PullOutcome",
    "build_discovery_provider",
    "find_initial_trigger",
    "poll_node_logs_once",
    "run_discovery_pull",
]

#: Default poll cadence while waiting for the node's initial discovery
#: summary (r3 "Pull trigger": "Every 10 s").
POLL_INTERVAL_S: Final[float] = 10.0


class PublicReadClient(Protocol):
    """Structurally identical to
    ``fee_drift_evidence_pull.PublicReadClient`` -- the ONE method this
    script (and the provider it builds) ever calls."""

    async def get_public(
        self, path: str, *, query: Mapping[str, Any] | None = None, quota_key: str
    ) -> Mapping[str, Any]: ...


@dataclass(slots=True)
class PageRecordingClient:
    """Wraps a real client's ``get_public``: records every raw
    ``MARKET_LIST_PATH`` page verbatim before returning it, so the pull can
    persist the exact wire payloads
    :func:`scripts.analysis.discovery_set_equality.venue_active_set` is later
    computed from -- without reimplementing ``_discover_markets``'s
    pagination (r2.1 non-blocking item).

    Passed to ``PolymarketUSInstrumentProvider(client=...)`` with a narrow
    ``# type: ignore[arg-type]`` at the call site: the provider's constructor
    is typed against the concrete ``PolymarketUSHttpClient``, but only ever
    calls ``.get_public(...)`` on it, which this object implements
    structurally -- the same accepted pattern
    ``fee_drift_evidence_pull.build_default_client``'s own
    ``signer=None  # type: ignore[arg-type]`` uses.
    """

    inner: PublicReadClient
    list_path: str
    pages: list[Mapping[str, Any]] = field(default_factory=list)

    async def get_public(
        self, path: str, *, query: Mapping[str, Any] | None = None, quota_key: str
    ) -> Mapping[str, Any]:
        payload = await self.inner.get_public(path, query=query, quota_key=quota_key)
        if path == self.list_path:
            self.pages.append(payload)
        return payload


def build_discovery_provider(client: PublicReadClient) -> tuple[Any, PageRecordingClient]:
    """A throwaway ``PolymarketUSInstrumentProvider`` wired to a public-only
    client, so the pull reuses ``load_all_async``'s pagination/dedup/city
    filtering rather than re-deriving them (r2.1 non-blocking item).

    ``city_codes`` comes from ``PolymarketUSMarketDiscoveryConfig()``'s own
    default (the node's discovery config builder), never a copied literal
    (AC3).
    """
    from nautilus_trader.common.component import LiveClock, Logger
    from nautilus_trader.config import InstrumentProviderConfig

    from breezy.adapters.polymarket_us.config import PolymarketUSMarketDiscoveryConfig
    from breezy.adapters.polymarket_us.provider import (
        MARKET_LIST_PATH,
        PolymarketUSInstrumentProvider,
    )

    discovery = PolymarketUSMarketDiscoveryConfig()
    recorder = PageRecordingClient(inner=client, list_path=MARKET_LIST_PATH)
    provider = PolymarketUSInstrumentProvider(
        # Duck-typed get_public wrapper; see PageRecordingClient's own docstring.
        client=recorder,  # type: ignore[arg-type]
        config=InstrumentProviderConfig(),
        discovery=discovery,
        clock=LiveClock(),
        logger=Logger("discovery-venue-pull"),
    )
    return provider, recorder


# ---------------------------------------------------------------------------
# Pull trigger: following the node's own log files (r3's "Pull trigger")
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FileCursor:
    offset: int
    tail: str


@dataclass(frozen=True, slots=True)
class FollowState:
    cursors: Mapping[Path, FileCursor] = field(default_factory=dict)


#: A node's INITIAL discovery summary is written within moments of its spawn,
#: so a log whose FILENAME stamp is more than this far before ``since_ns``
#: cannot hold today's trigger. Generous on purpose: it only has to exclude
#: the multi-hundred-MB historical logs, never a plausible same-day launch.
HISTORICAL_STAMP_SLACK_NS: Final[int] = 60 * 60 * 1_000_000_000


def _is_historical(path: Path, since_ns: int) -> bool:
    """True when ``path``'s filename stamp predates ``since_ns`` by more than
    :data:`HISTORICAL_STAMP_SLACK_NS` (F3: the stamp, never mtime -- a
    long-lived log's mtime is as fresh as today's)."""
    stamp = datetime.strptime(file_stamp(path), "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    return int(stamp.timestamp() * 1_000_000_000) < since_ns - HISTORICAL_STAMP_SLACK_NS


def poll_node_logs_once(
    log_dir: Path, state: FollowState, *, since_ns: int | None = None
) -> tuple[FollowState, tuple[NodeLogRecord, ...], frozenset[Path]]:
    """One poll: read newly appended, COMPLETE lines from every
    ``NODE_LOG_GLOB`` file under ``log_dir``.

    F2: a line split across two polls is buffered whole (the byte offset
    still advances past it -- only the in-memory ``tail`` carries the
    unconsumed partial text -- so nothing is re-read from disk). A file
    whose size shrank since the last poll is TRUNCATED: its cursor resets to
    a fresh read from byte 0 and the path is reported in the third element.

    O1: with ``since_ns`` given, a not-yet-followed file whose filename stamp
    is historical (see :func:`_is_historical`) is seeded at EOF instead of
    read from byte 0 -- the multi-GB node history is never pulled through a
    256M cgroup -- and is then followed from EOF like any other file. Reads
    are streamed line by line, so memory is bounded by the longest line.
    """
    new_cursors: dict[Path, FileCursor] = {}
    records: list[NodeLogRecord] = []
    truncated: set[Path] = set()
    for path in sorted(log_dir.glob(NODE_LOG_GLOB)):
        try:
            size = path.stat().st_size
        except OSError:
            continue
        prior = state.cursors.get(path)
        if prior is None and since_ns is not None and _is_historical(path, since_ns):
            new_cursors[path] = FileCursor(offset=size, tail="")
            continue
        offset = prior.offset if prior is not None else 0
        carry = prior.tail if prior is not None else ""
        if size < offset:
            truncated.add(path)
            offset = 0
            carry = ""
        consumed = 0
        with open(path, "rb") as fh:
            fh.seek(offset)
            for raw in fh:
                consumed += len(raw)
                text = carry + raw.decode("utf-8", errors="replace")
                if not raw.endswith(b"\n"):
                    carry = text
                    break
                carry = ""
                for raw_line in text.splitlines():
                    stripped = ANSI_RE.sub("", raw_line)
                    match = LINE_RE.match(stripped)
                    if match is None:
                        continue
                    records.append(
                        NodeLogRecord(
                            source=path,
                            ts_ns=parse_ts_ns(match.group("ts")),
                            level=match.group("level"),
                            component=match.group("component"),
                            message=match.group("message"),
                        )
                    )
        new_cursors[path] = FileCursor(offset=offset + consumed, tail=carry)
    return FollowState(cursors=new_cursors), tuple(records), frozenset(truncated)


def find_initial_trigger(
    records: Sequence[NodeLogRecord], *, since_ns: int
) -> NodeLogRecord | None:
    """The record marking a fresh spawn's INITIAL discovery summary at or
    after ``since_ns``, scoped to the file with the newest FILENAME stamp
    (F3) among files that have one -- a stale, already-superseded spawn's
    initial line is never picked over a fresher relaunch's.
    """
    initials = [
        r
        for r in records
        if r.component.endswith("DataClient-POLYMARKET_US")
        and r.ts_ns >= since_ns
        and (m := SUMMARY_PREFIX_RE.match(r.message)) is not None
        and m.group("cycle") == "initial"
    ]
    if not initials:
        return None
    newest_file = max((r.source for r in initials), key=file_stamp)
    for record in initials:
        if record.source == newest_file:
            return record
    return None  # pragma: no cover - unreachable, kept for exhaustiveness


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PullOutcome:
    date: str
    complete: bool
    reason: str | None
    pull_start_ns: int | None
    pull_end_ns: int | None
    paired_ts_ns: int | None
    pages: tuple[Mapping[str, Any], ...]
    node_active: tuple[str, ...]
    venue_active: tuple[str, ...]
    by_slug_lookup: Mapping[str, Mapping[str, Any] | None]


def _replay_node_active_slugs(path: Path, *, up_to_ns: int) -> tuple[str, ...]:
    """N = R ∪ B (r2 AC2 finding: ``active_market_slugs = R ∪ B``,
    disjoint): replay the TRIGGERING file's own discovery cycles up to and
    including P (``up_to_ns``), using the SAME parser/replay the offline
    analysis uses -- never a second, competing reimplementation.
    """
    from scripts.analysis.discovery_set_equality import iter_node_log_records, replay_cycles

    records = tuple(r for r in iter_node_log_records(path) if r.ts_ns <= up_to_ns)
    result = replay_cycles(records)
    return tuple(sorted(set(result.final_active) | set(result.final_blocked)))


async def run_discovery_pull(
    *,
    client: PublicReadClient,
    log_dir: Path,
    node_active_slugs: Sequence[str] | None,
    since_ns: int,
    deadline_ns: int,
    poll_sleep: float = 10.0,
    now_ns: Callable[[], int] | None = None,
    sleep: Callable[[float], Any] | None = None,
) -> PullOutcome:
    """Poll ``log_dir`` every ``poll_sleep`` seconds until the first INITIAL
    discovery summary at or after ``since_ns``, or ``deadline_ns`` -- then
    pull the venue's list once and GET every node-only slug (r3 "Pull
    trigger", steps 1-6).

    ``node_active_slugs`` is ``N`` (plan step 5: GET every slug in ``N - V``
    by slug). Pass an explicit sequence to override (tests); ``None`` (the
    CLI's own default) replays the TRIGGERING file up to P via
    :func:`_replay_node_active_slugs` -- this script never re-implements
    that replay a second, independent way.
    """
    clock = now_ns if now_ns is not None else time.time_ns
    sleeper = sleep if sleep is not None else asyncio.sleep

    state = FollowState()
    triggered_ts_ns: int | None = None
    trigger_source: Path | None = None
    while True:
        state, records, _truncated = poll_node_logs_once(log_dir, state, since_ns=since_ns)
        trigger = find_initial_trigger(records, since_ns=since_ns)
        if trigger is not None:
            triggered_ts_ns = trigger.ts_ns
            trigger_source = trigger.source
            break
        if clock() >= deadline_ns:
            return PullOutcome(
                date="",
                complete=False,
                reason="NO-PULL",
                pull_start_ns=None,
                pull_end_ns=None,
                paired_ts_ns=None,
                pages=(),
                node_active=(),
                venue_active=(),
                by_slug_lookup={},
            )
        await sleeper(poll_sleep)

    if node_active_slugs is None:
        assert trigger_source is not None and triggered_ts_ns is not None
        node_active_slugs = _replay_node_active_slugs(trigger_source, up_to_ns=triggered_ts_ns)

    pull_start_ns = clock()
    provider, recorder = build_discovery_provider(client)
    incomplete_reason: str | None = None
    try:
        await provider.load_all_async()
    except Exception as exc:  # noqa: BLE001 - reported, never re-raised: a failed pull still writes evidence
        incomplete_reason = f"PULL-INCOMPLETE ({type(exc).__name__})"
    venue_active = tuple(getattr(provider, "active_market_slugs", ()))

    from breezy.adapters.polymarket_us.provider import MARKET_BY_SLUG_PATH
    from breezy.adapters.polymarket_us.transport import QUOTA_KEY_INSTRUMENTS

    missing = [slug for slug in node_active_slugs if slug not in set(venue_active)]
    by_slug_lookup: dict[str, Mapping[str, Any] | None] = {}
    for slug in missing:
        try:
            payload = await client.get_public(
                MARKET_BY_SLUG_PATH.format(slug=slug), quota_key=QUOTA_KEY_INSTRUMENTS
            )
        except Exception:  # noqa: BLE001 - a failed lookup is reported as a missing GET, never fatal
            by_slug_lookup[slug] = None
            continue
        market = payload.get("market") if isinstance(payload, Mapping) else None
        by_slug_lookup[slug] = market if isinstance(market, Mapping) else payload

    pull_end_ns = clock()
    return PullOutcome(
        date="",
        complete=incomplete_reason is None,
        reason=incomplete_reason,
        pull_start_ns=pull_start_ns,
        pull_end_ns=pull_end_ns,
        paired_ts_ns=triggered_ts_ns,
        pages=tuple(recorder.pages),
        node_active=tuple(node_active_slugs),
        venue_active=venue_active,
        by_slug_lookup=by_slug_lookup,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node-log-dir", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--user-agent", type=str, required=True)
    return parser.parse_args(argv)


def _today_window_ns(now: datetime) -> tuple[int, int]:
    today = now.astimezone(UTC).date()
    since = datetime.combine(today, WINDOW_START, tzinfo=UTC)
    deadline = datetime.combine(today, RELAUNCH_DEADLINE, tzinfo=UTC)
    return int(since.timestamp() * 1_000_000_000), int(deadline.timestamp() * 1_000_000_000)


async def _main_async(argv: Sequence[str] | None, *, now: datetime | None = None) -> int:
    args = _parse_args(argv)
    from scripts.venue.fee_drift_evidence_pull import build_default_client

    effective_now = now if now is not None else datetime.now(tz=UTC)
    since_ns, deadline_ns = _today_window_ns(effective_now)
    client = build_default_client(user_agent=args.user_agent)
    outcome = await run_discovery_pull(
        client=client,
        log_dir=args.node_log_dir,
        node_active_slugs=None,
        since_ns=since_ns,
        deadline_ns=deadline_ns,
    )
    args.out_dir.mkdir(parents=True, exist_ok=True)
    day = effective_now.astimezone(UTC).date().isoformat()
    payload = {
        "date": day,
        "complete": outcome.complete,
        "reason": outcome.reason,
        "pull_start_ns": outcome.pull_start_ns,
        "pull_end_ns": outcome.pull_end_ns,
        "paired_ts_ns": outcome.paired_ts_ns,
        "node_active": list(outcome.node_active),
        "venue_active": list(outcome.venue_active),
        "by_slug_lookup": dict(outcome.by_slug_lookup),
    }
    (args.out_dir / f"{day}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    if outcome.pages:
        (args.out_dir / f"{day}_pages.json").write_text(
            json.dumps(list(outcome.pages), indent=2), encoding="utf-8"
        )
    return 0


def main(argv: Sequence[str] | None = None, *, now: datetime | None = None) -> int:
    return asyncio.run(_main_async(argv, now=now))


if __name__ == "__main__":  # pragma: no cover - process entry point, not itself testable
    raise SystemExit(main(sys.argv[1:]))
