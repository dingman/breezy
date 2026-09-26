"""AUD-02 WP-D1: discovery set equality (plan r2 / r2.1 / r3 / r3.1).

Offline, pure comparison of Breezy's Polymarket.us discovery cycles (replayed
entirely from the trade-node's own log FILES -- never journald, see
``docs/plans/backlog/AUDIT_2026-09-21/AUD-02_WP-D1_plan_r2_2026-09-26.md``
r3's "Stage 0 finding") against an unattended venue pull
(:mod:`scripts.analysis.discovery_venue_pull`).

This module makes NO network calls and writes only to a path the caller
supplies (``--out``). Every log-derived fact is replayed from a
``breezy-trade-<ts>.log`` file's own lines: the node is a bare
``subprocess.Popen`` (``trade_supervisor.spawn_node``), never a systemd unit,
so there is no journal to read for it.
"""

from __future__ import annotations

import argparse
import ast
import calendar
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Final

__all__ = [
    "ANSI_RE",
    "LINE_RE",
    "NODE_LOG_GLOB",
    "PREVIOUS_DAY_SCOPE_END",
    "RELAUNCH_DEADLINE",
    "SUMMARY_PREFIX_RE",
    "WINDOW_END",
    "WINDOW_START",
    "ClassifiedDifference",
    "CycleReplay",
    "DayVerdict",
    "DiscoveryCount",
    "DiscoverySummary",
    "ErrorCounts",
    "NodeLogRecord",
    "PairResult",
    "ReplayResult",
    "VenueActiveSetResult",
    "classify_differences",
    "count_errors",
    "day_verdict",
    "detect_relaunch_failed",
    "file_stamp",
    "filter_unit_records",
    "iter_node_log_records",
    "overall_verdict",
    "pair_pull",
    "parse_ts_ns",
    "render_note",
    "replay_cycles",
    "replay_file",
    "select_day_files",
    "venue_active_set",
]

# ---------------------------------------------------------------------------
# Log parsing
# ---------------------------------------------------------------------------

#: Nautilus wraps every line in an ANSI colour/style escape. Stripped before
#: any other pattern is applied.
ANSI_RE: Final[re.Pattern[str]] = re.compile(r"\x1b\[[0-9;]*m")

#: r3 "Format": ``2026-09-23T16:50:50.404256598Z [INFO] <component>: <msg>``,
#: nanosecond precision, UTC. A line that does not match this (a stdlib
#: logging line such as ``breezy-trade: configuration error: ...; refusing to
#: start``, or a bare traceback) is "stdlib/unprefixed" and is IGNORED for
#: replay -- it carries no component/level Nautilus itself vouches for.
LINE_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?P<ts>\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{9})Z "
    r"\[(?P<level>[A-Z]+)\] (?P<component>\S+): (?P<message>.*)$"
)

#: r3 "The replay unit is the log FILE ... The glob is
#: `breezy-trade-[0-9]*T*Z.log`, which excludes supervisor logs" (and every
#: other file under the log directory: quote-tape logs, `.log.try2` retries).
NODE_LOG_GLOB: Final[str] = "breezy-trade-[0-9]*T*Z.log"

_FILE_STAMP_RE: Final[re.Pattern[str]] = re.compile(r"breezy-trade-(\d{8}T\d{6}Z)\.log$")

#: The protected no-start window `[16:35Z, 01:15Z)` (deploy/systemd/README.md)
#: also bounds one day's evidence window for this plan (AC6).
WINDOW_START: Final[time] = time(16, 35)
WINDOW_END: Final[time] = time(1, 15)
#: AC7 RELAUNCH-FAILED: no `initial` summary by this deadline.
RELAUNCH_DEADLINE: Final[time] = time(17, 12)
#: F1: the previous day's node file stays in scope only until about this
#: instant -- after which an in-scope line belongs to the NEW day only.
PREVIOUS_DAY_SCOPE_END: Final[time] = time(16, 41)

_REFUSING_TO_START_RE: Final[re.Pattern[str]] = re.compile(r"refusing to start")

_COUNT_RE: Final[re.Pattern[str]] = re.compile(
    r"^Polymarket\.us discovery cycle loaded (?P<n>\d+) active market\(s\), "
    r"observed (?P<resolved>\d+) resolved market\(s\), discovered (?P<discovered>\d+) total$"
)
SUMMARY_PREFIX_RE: Final[re.Pattern[str]] = re.compile(
    r"^Polymarket\.us discovery cycle (?P<cycle>\w+): subscribed=(?P<rest>.*)$"
)

_NWS_WHITELIST_RE: Final[re.Pattern[str]] = re.compile(r"BREEZY-NWS subscribe")
_DISCOVERY_ERROR_FILTER_RE: Final[re.Pattern[str]] = re.compile(
    r"(discover|provider|listing|instrument)", re.IGNORECASE
)


@dataclass(frozen=True, slots=True)
class NodeLogRecord:
    """One parsed Nautilus-format line from a node log file."""

    source: Path
    ts_ns: int
    level: str
    component: str
    message: str


def parse_ts_ns(ts: str) -> int:
    """``2026-09-23T16:50:50.404256598`` -> epoch nanoseconds.

    ``calendar.timegm`` (not ``datetime.timestamp()``) avoids float rounding
    on the whole-second part; the 9-digit fractional part is already
    nanoseconds and is added verbatim.
    """
    date_part, _, frac = ts.partition(".")
    parsed = datetime.strptime(date_part, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=UTC)
    epoch_s = calendar.timegm(parsed.timetuple())
    return epoch_s * 1_000_000_000 + int(frac)


def file_stamp(path: Path) -> str:
    """F3: "newest" is decided by the FILENAME stamp, never ctime/mtime."""
    match = _FILE_STAMP_RE.search(path.name)
    if match is None:
        raise ValueError(f"{path.name!r} does not match {NODE_LOG_GLOB!r}")
    return match.group(1)


def iter_node_log_records(path: Path) -> tuple[NodeLogRecord, ...]:
    """Every Nautilus-format line in ``path``, ANSI-stripped and parsed.

    A line that fails :data:`LINE_RE` (stdlib logging, a bare traceback, a
    truncated final line) is silently skipped here -- callers that need to
    detect a truncation or an unparseable line compare the byte length they
    read against what parsed, e.g. :func:`select_day_files`.
    """
    text = path.read_text(encoding="utf-8", errors="replace")
    records: list[NodeLogRecord] = []
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
    return tuple(records)


def _window_bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, WINDOW_START, tzinfo=UTC)
    end = datetime.combine(day + timedelta(days=1), WINDOW_END, tzinfo=UTC)
    return start, end


def select_day_files(log_dir: Path, day: date) -> tuple[Path, ...]:
    """AC2 amended by r3: every node log file with at least one line inside
    ``day``'s window ``[16:35Z day, 01:15Z day+1)``, sorted oldest-to-newest
    by FILENAME stamp (F3). NODE-DOWN (no file with any line after
    :data:`PREVIOUS_DAY_SCOPE_END`) and the AC7 (a)-(c) file-shape gaps are
    evaluated by the caller over exactly this file set (F1: those checks
    apply ONLY to files that actually have discovery lines inside the
    window, which is exactly the set this function returns).
    """
    start, end = _window_bounds(day)
    start_ns = int(start.timestamp() * 1_000_000_000)
    end_ns = int(end.timestamp() * 1_000_000_000)
    matched: list[Path] = []
    for path in sorted(log_dir.glob(NODE_LOG_GLOB), key=file_stamp):
        records = iter_node_log_records(path)
        if any(start_ns <= r.ts_ns < end_ns for r in records):
            matched.append(path)
    return tuple(matched)


def filter_unit_records(
    records: Sequence[NodeLogRecord], *, day: date
) -> tuple[NodeLogRecord, ...]:
    """AC6 scope: records whose timestamp falls in ``[16:35Z day, 01:15Z
    day+1)``, regardless of which file they came from."""
    start, end = _window_bounds(day)
    start_ns = int(start.timestamp() * 1_000_000_000)
    end_ns = int(end.timestamp() * 1_000_000_000)
    return tuple(r for r in records if start_ns <= r.ts_ns < end_ns)


# ---------------------------------------------------------------------------
# AC2 -- replay
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DiscoveryCount:
    ts_ns: int
    n: int


@dataclass(frozen=True, slots=True)
class DiscoverySummary:
    ts_ns: int
    cycle: str
    subscribed: tuple[str, ...]
    unsubscribed: tuple[str, ...]
    unsubscribed_pairs: tuple[tuple[str, str], ...]
    blocked: tuple[str, ...]


def _parse_summary(ts_ns: int, cycle: str, rest: str) -> DiscoverySummary:
    """``rest`` is ``(...) unsubscribed=(...) blocked_missing_cache=(...)``.

    Split on the literal field markers (never regex-captured as ``\\(.*\\)``,
    which cannot tell three adjacent parenthesised tuples apart) and
    ``ast.literal_eval`` each piece -- the exact tuple ``repr()`` Python wrote,
    including a reason string that itself carries embedded quotes (AC2:
    "Parse with ``ast.literal_eval``").
    """
    subscribed_text, _, tail = rest.partition(" unsubscribed=")
    unsub_text, _, blocked_text = tail.partition(" blocked_missing_cache=")
    subscribed = ast.literal_eval(subscribed_text)
    unsub_pairs = ast.literal_eval(unsub_text)
    blocked = ast.literal_eval(blocked_text)
    return DiscoverySummary(
        ts_ns=ts_ns,
        cycle=cycle,
        subscribed=tuple(subscribed),
        unsubscribed=tuple(pair[0] for pair in unsub_pairs),
        unsubscribed_pairs=tuple(tuple(pair) for pair in unsub_pairs),
        blocked=tuple(blocked),
    )


@dataclass(frozen=True, slots=True)
class CycleReplay:
    ts_ns: int
    cycle: str
    n: int | None
    subscribed: tuple[str, ...]
    unsubscribed: tuple[str, ...]
    blocked: tuple[str, ...]
    active_after: tuple[str, ...]
    count_matches: bool


@dataclass(frozen=True, slots=True)
class ReplayResult:
    cycles: tuple[CycleReplay, ...]
    final_active: tuple[str, ...]
    final_blocked: tuple[str, ...]
    gap: str | None
    #: r2.1: "A count line with no following summary counts as a failed
    #: cycle attempt for AC4[6]" -- an interior or trailing orphan count,
    #: never itself a REPLAY-GAP (the 09-10/09-11 shape).
    raised_cycle_count: int = 0


#: Per-slug line (``data.py:1318``), redundant with a summary's own
#: ``subscribed`` tuple for replay purposes -- its PRESENCE without a
#: following summary is itself gap evidence (AC7 (c)).
_SUBSCRIBING_RE: Final[re.Pattern[str]] = re.compile(
    r"^Polymarket\.us discovery cycle (\w+): subscribing \S+ \((new|reload)\)$"
)


def _is_count_record(record: NodeLogRecord) -> DiscoveryCount | None:
    if not record.component.endswith("POLYMARKET_US-discovery"):
        return None
    match = _COUNT_RE.match(record.message)
    if match is None:
        return None
    return DiscoveryCount(ts_ns=record.ts_ns, n=int(match.group("n")))


def _is_summary_record(record: NodeLogRecord) -> DiscoverySummary | None:
    if not record.component.endswith("DataClient-POLYMARKET_US"):
        return None
    match = SUMMARY_PREFIX_RE.match(record.message)
    if match is None:
        return None
    return _parse_summary(record.ts_ns, match.group("cycle"), match.group("rest"))


def _is_subscribing_record(record: NodeLogRecord) -> bool:
    return record.component.endswith("DataClient-POLYMARKET_US") and bool(
        _SUBSCRIBING_RE.match(record.message)
    )


def replay_cycles(records: Sequence[NodeLogRecord]) -> ReplayResult:
    """AC2 (r2), amended by r3/r3.1: replay one file's discovery cycles.

    ``R`` (the live subscription set) starts empty and is updated by every
    summary: ``R <- (R - unsubscribed) | subscribed``. Each cycle's own
    ``blocked_missing_cache`` (``B``) is reported separately (never folded
    into ``R``), and the invariant ``N == |R ∪ B|`` is checked per cycle
    against the count line paired with it. Any violation of AC7's REPLAY-GAP
    triggers stops the replay and reports the reason.
    """
    counts = [c for r in records if (c := _is_count_record(r)) is not None]
    summaries = [s for r in records if (s := _is_summary_record(r)) is not None]

    if not summaries:
        has_activity = bool(counts) or any(_is_subscribing_record(r) for r in records)
        no_summary_gap = "COUNT-AND-SLUGS-WITHOUT-INITIAL" if has_activity else "NO-SUMMARY"
        return ReplayResult(cycles=(), final_active=(), final_blocked=(), gap=no_summary_gap)
    if summaries[0].cycle != "initial":
        return ReplayResult(cycles=(), final_active=(), final_blocked=(), gap="STARTS-MID-PROCESS")

    active: tuple[str, ...] = ()
    cycles: list[CycleReplay] = []
    gap: str | None = None
    count_idx = 0
    consumed_count_indices: set[int] = set()
    for summary in summaries:
        n_value: int | None = None
        last_consumed_idx: int | None = None
        while count_idx < len(counts) and counts[count_idx].ts_ns <= summary.ts_ns:
            n_value = counts[count_idx].n
            last_consumed_idx = count_idx
            count_idx += 1
        if last_consumed_idx is not None:
            consumed_count_indices.add(last_consumed_idx)
        active_set = set(active)
        unknown = [slug for slug in summary.unsubscribed if slug not in active_set]
        if unknown:
            gap = "UNSUBSCRIBE-OF-UNKNOWN-SLUG"
            break
        active_set = (active_set - set(summary.unsubscribed)) | set(summary.subscribed)
        active = tuple(sorted(active_set))
        matches = n_value is not None and n_value == len(active) + len(summary.blocked)
        cycles.append(
            CycleReplay(
                ts_ns=summary.ts_ns,
                cycle=summary.cycle,
                n=n_value,
                subscribed=summary.subscribed,
                unsubscribed=summary.unsubscribed,
                blocked=summary.blocked,
                active_after=active,
                count_matches=matches,
            )
        )
        if n_value is not None and not matches:
            gap = "COUNT-MISMATCH"
            break

    raised_cycle_count = len(counts) - len(consumed_count_indices)
    final_active = cycles[-1].active_after if cycles else ()
    final_blocked = cycles[-1].blocked if cycles else ()
    return ReplayResult(
        cycles=tuple(cycles),
        final_active=final_active,
        final_blocked=final_blocked,
        gap=gap,
        raised_cycle_count=raised_cycle_count,
    )


def _is_truncated(text: str) -> bool:
    """AC7 (b): a file is TRUNCATED when its last non-empty line, once
    ANSI-stripped, does not fully match the Nautilus line format -- a write
    was cut off mid-line."""
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return False
    stripped = ANSI_RE.sub("", lines[-1])
    return LINE_RE.match(stripped) is None


def replay_file(path: Path) -> ReplayResult:
    """Convenience wrapper: :func:`replay_cycles` over one file's own
    records, additionally checking AC7 (b) truncation over the file's raw
    last line (a check :func:`replay_cycles` cannot make from records alone,
    since a cut trailing line is never parsed into one)."""
    text = path.read_text(encoding="utf-8", errors="replace")
    result = replay_cycles(iter_node_log_records(path))
    if result.gap is None and _is_truncated(text):
        return ReplayResult(
            cycles=result.cycles,
            final_active=result.final_active,
            final_blocked=result.final_blocked,
            gap="TRUNCATED-FILE",
            raised_cycle_count=result.raised_cycle_count,
        )
    return result


def detect_relaunch_failed(path: Path, *, deadline_ns: int) -> bool:
    """AC7 RELAUNCH-FAILED: no ``initial`` summary anywhere by
    ``deadline_ns`` -- covers both the 09-25 shape (the stdlib
    ``breezy-trade: configuration error: ...; refusing to start`` line,
    invisible to :func:`iter_node_log_records` since it is unprefixed) and a
    file that simply never got an initial summary before the deadline.
    """
    text = path.read_text(encoding="utf-8", errors="replace")
    if _REFUSING_TO_START_RE.search(text):
        return True
    summaries = [s for r in iter_node_log_records(path) if (s := _is_summary_record(r)) is not None]
    return not any(s.cycle == "initial" and s.ts_ns <= deadline_ns for s in summaries)


# ---------------------------------------------------------------------------
# AC3 -- venue set
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class VenueActiveSetResult:
    active: tuple[str, ...]
    resolved_count: int
    unregistered_count: int


def venue_active_set(
    pages: Sequence[Mapping[str, Any]], city_codes: Sequence[str]
) -> VenueActiveSetResult:
    """AC3: ``V = {slug : _resolved_reason(m) is None}`` over every stored
    page, using the PROVIDER's own filter (never a reimplementation) so a
    future venue-schema change is caught in one place."""
    from breezy.adapters.polymarket_us.provider import _resolved_reason, _weather_market_payloads

    active: list[str] = []
    resolved_count = 0
    unregistered_count = 0
    codes = tuple(city_codes)
    for page in pages:
        accepted, sightings = _weather_market_payloads(page, codes, collect_unregistered=True)
        unregistered_count += len(sightings)
        for market in accepted:
            if _resolved_reason(market) is None:
                slug = market["slug"]
                assert isinstance(slug, str)
                active.append(slug)
            else:
                resolved_count += 1
    return VenueActiveSetResult(
        active=tuple(active), resolved_count=resolved_count, unregistered_count=unregistered_count
    )


# ---------------------------------------------------------------------------
# AC4 -- pairing
# ---------------------------------------------------------------------------

_MAX_GAP_DEFAULT_S: Final[float] = 600.0
_MAX_PULL_DURATION_S: Final[float] = 120.0


@dataclass(frozen=True, slots=True)
class PairResult:
    paired: bool
    p_ts_ns: int | None
    gap_s: float | None
    gap_ok: bool
    duration_ok: bool
    interleaved: bool
    ineligible_reason: str | None


def pair_pull(
    *,
    summaries: Sequence[DiscoverySummary],
    other_discovery_event_ns: Sequence[int] = (),
    pull_start_ns: int,
    pull_end_ns: int,
    max_gap_s: float = _MAX_GAP_DEFAULT_S,
) -> PairResult:
    """AC4: pair the pull with the latest summary ``P`` at or before
    ``pull_start_ns``.

    ``other_discovery_event_ns`` names every count line, ``:1262``-style
    ERROR, or new-file first-line timestamp between ``P`` and the pull --
    any of those makes the pairing INTERLEAVED (r3 amended AC4).
    """
    candidates = [s for s in summaries if s.ts_ns <= pull_start_ns]
    if not candidates:
        return PairResult(
            paired=False,
            p_ts_ns=None,
            gap_s=None,
            gap_ok=False,
            duration_ok=False,
            interleaved=False,
            ineligible_reason="NO-PULL",
        )
    p = max(candidates, key=lambda s: s.ts_ns)
    gap_s = (pull_start_ns - p.ts_ns) / 1e9
    gap_ok = gap_s <= max_gap_s
    duration_s = (pull_end_ns - pull_start_ns) / 1e9
    duration_ok = duration_s <= _MAX_PULL_DURATION_S
    # r3 amended AC4: "an interleaved attempt means any of: a count line, a
    # :1262 ERROR, or a new file's first line appearing between P and
    # pull_start" -- and separately, "PULL-INTERLEAVED-RELAUNCH: a newer
    # spawn appears in (ts(P), pull_end]". The relaunch window is the wider
    # of the two (it extends through the end of the pull, not just its
    # start), so checking every named event against `(P, pull_end]`
    # uniformly satisfies both without under- or over-counting either.
    interleaved = any(p.ts_ns < ts <= pull_end_ns for ts in other_discovery_event_ns)

    reason: str | None = None
    if not gap_ok:
        reason = "PULL-OUTSIDE-MAX-GAP"
    elif interleaved:
        reason = "PULL-INTERLEAVED-RELAUNCH"
    elif not duration_ok:
        reason = "PULL-INCOMPLETE"

    return PairResult(
        paired=True,
        p_ts_ns=p.ts_ns,
        gap_s=gap_s,
        gap_ok=gap_ok,
        duration_ok=duration_ok,
        interleaved=interleaved,
        ineligible_reason=reason,
    )


# ---------------------------------------------------------------------------
# AC5 -- explained differences
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ClassifiedDifference:
    slug: str
    side: str  # "venue_only" | "node_only"
    explained: bool
    detail: str


def _parse_rfc3339_ns(value: str) -> int | None:
    try:
        cleaned = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(cleaned)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return int(parsed.timestamp() * 1_000_000_000)


def classify_differences(
    *,
    node_active: Iterable[str],
    venue_active: Iterable[str],
    p_ts_ns: int,
    pull_start_ns: int,
    venue_payloads: Mapping[str, Mapping[str, Any]],
    by_slug_lookup: Mapping[str, Mapping[str, Any] | None],
) -> tuple[ClassifiedDifference, ...]:
    """AC5: a difference counts as EXPLAINED only when its timestamp falls
    strictly inside ``(p_ts_ns, pull_start_ns]``. Anything else -- including a
    missing timestamp or a missing/failed by-slug GET -- FAILS the day.
    """
    from breezy.adapters.polymarket_us.provider import _resolved_reason

    node_set = frozenset(node_active)
    venue_set = frozenset(venue_active)
    results: list[ClassifiedDifference] = []

    for slug in sorted(venue_set - node_set):
        payload = venue_payloads.get(slug, {})
        raw_ts = payload.get("createdAt")
        used_field = "createdAt"
        if not isinstance(raw_ts, str):
            raw_ts = payload.get("startDate")
            used_field = "startDate"
        ts_ns = _parse_rfc3339_ns(raw_ts) if isinstance(raw_ts, str) else None
        if ts_ns is not None and p_ts_ns < ts_ns <= pull_start_ns:
            results.append(
                ClassifiedDifference(
                    slug=slug, side="venue_only", explained=True, detail=f"{used_field}={raw_ts!r}"
                )
            )
        else:
            results.append(
                ClassifiedDifference(
                    slug=slug,
                    side="venue_only",
                    explained=False,
                    detail=f"no in-window timestamp (checked {used_field}={raw_ts!r})",
                )
            )

    for slug in sorted(node_set - venue_set):
        lookup = by_slug_lookup.get(slug)
        if lookup is None:
            results.append(
                ClassifiedDifference(
                    slug=slug,
                    side="node_only",
                    explained=False,
                    detail="missing or failed by-slug GET",
                )
            )
            continue
        reason = _resolved_reason(lookup)
        end_date = lookup.get("endDate")
        ts_ns = _parse_rfc3339_ns(end_date) if isinstance(end_date, str) else None
        if reason is not None and ts_ns is not None and p_ts_ns < ts_ns <= pull_start_ns:
            results.append(
                ClassifiedDifference(
                    slug=slug,
                    side="node_only",
                    explained=True,
                    detail=f"endDate={end_date!r} ({reason})",
                )
            )
        else:
            results.append(
                ClassifiedDifference(
                    slug=slug,
                    side="node_only",
                    explained=False,
                    detail=f"resolved_reason={reason!r} endDate={end_date!r}",
                )
            )

    return tuple(results)


# ---------------------------------------------------------------------------
# AC6 -- errors
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ErrorCounts:
    filtered: int
    unfiltered: int
    unprefixed: int


def count_errors(
    records: Sequence[NodeLogRecord], *, unprefixed_error_lines: Sequence[str] = ()
) -> ErrorCounts:
    """AC6: ERROR counts over in-scope Nautilus lines, both filtered
    (``\\bERROR\\b.*(discover|provider|listing|instrument)``, whitelisting
    ``BREEZY-NWS subscribe``) and unfiltered, plus unprefixed stderr lines
    reported separately and never whitelisted (r3 amended AC6)."""
    filtered = 0
    unfiltered = 0
    for record in records:
        if record.level != "ERROR":
            continue
        unfiltered += 1
        if _NWS_WHITELIST_RE.search(record.message):
            continue
        if _DISCOVERY_ERROR_FILTER_RE.search(record.message):
            filtered += 1
    return ErrorCounts(
        filtered=filtered, unfiltered=unfiltered, unprefixed=len(unprefixed_error_lines)
    )


# ---------------------------------------------------------------------------
# AC7 / AC8 -- eligibility and verdict
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DayVerdict:
    day: date
    eligible: bool
    ineligible_reason: str | None
    equal: bool
    differences: tuple[ClassifiedDifference, ...]
    error_counts: ErrorCounts | None


def day_verdict(
    *,
    day: date,
    replay: ReplayResult | None,
    pull_attempted: bool,
    pair: PairResult | None,
    differences: tuple[ClassifiedDifference, ...],
    error_counts: ErrorCounts | None,
    node_down: bool = False,
    relaunch_failed: bool = False,
    all_cycles_raised: bool = False,
    pre_aa737f1: bool = False,
) -> DayVerdict:
    """AC7/AC8: one day's ineligibility reason (at most one, first match
    wins in the order the plan lists them) and, for an eligible day, whether
    the sets are equal (an EXPLAINED difference still counts as equal)."""
    reason: str | None = None
    if pre_aa737f1:
        reason = "PRE-AA737F1"
    elif node_down:
        reason = "NODE-DOWN"
    elif relaunch_failed:
        reason = "RELAUNCH-FAILED"
    elif all_cycles_raised:
        reason = "ALL-CYCLES-RAISED"
    elif replay is None or replay.gap is not None:
        reason = "REPLAY-GAP"
    elif not pull_attempted:
        reason = "NO-PULL"
    elif pair is None or pair.ineligible_reason is not None:
        reason = pair.ineligible_reason if pair is not None else "NO-PULL"

    eligible = reason is None
    equal = eligible and all(d.explained for d in differences)
    return DayVerdict(
        day=day,
        eligible=eligible,
        ineligible_reason=reason,
        equal=equal,
        differences=differences,
        error_counts=error_counts,
    )


def overall_verdict(day_verdicts: Sequence[DayVerdict], *, min_eligible_days: int = 5) -> str:
    """AC8: SUPERSEDED-BY AUD-08a requires >=5 eligible days, each with equal
    sets (EXPLAINED allowed) and zero non-whitelisted ERRORs. Otherwise
    FIX-SLICE."""
    eligible = [d for d in day_verdicts if d.eligible]
    if len(eligible) < min_eligible_days:
        return "FIX-SLICE"
    if not all(d.equal for d in eligible):
        return "FIX-SLICE"
    if not all((d.error_counts is None or d.error_counts.filtered == 0) for d in eligible):
        return "FIX-SLICE"
    return "SUPERSEDED-BY AUD-08a"


def render_note(day_verdicts: Sequence[DayVerdict], *, closing_rule_header: str) -> str:
    """A minimal, deterministic per-day markdown rendering of the verdicts,
    for ``docs/evidence/WP-D1_discovery_set_equality_<date>.md`` (AC1/AC6)."""
    lines = [closing_rule_header, ""]
    for verdict in day_verdicts:
        if not verdict.eligible:
            lines.append(f"- {verdict.day.isoformat()}: INELIGIBLE ({verdict.ineligible_reason})")
            continue
        status = "EQUAL" if verdict.equal else "NOT-EQUAL"
        venue_only = sum(1 for d in verdict.differences if d.side == "venue_only")
        node_only = sum(1 for d in verdict.differences if d.side == "node_only")
        errors = verdict.error_counts
        error_text = (
            f"errors(filtered={errors.filtered}, unfiltered={errors.unfiltered})"
            if errors is not None
            else "errors(n/a)"
        )
        lines.append(
            f"- {verdict.day.isoformat()}: {status} venue_only={venue_only} "
            f"node_only={node_only} {error_text}"
        )
    lines.append("")
    lines.append(f"Verdict: {overall_verdict(day_verdicts)}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node-log-dir", type=Path, required=True)
    parser.add_argument(
        "--venue-pulls", type=Path, required=True, help="directory of per-day pull JSON"
    )
    parser.add_argument("--out", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:  # pragma: no cover - thin CLI shell
    args = _parse_args(argv)
    pull_files = sorted(args.venue_pulls.glob("*.json"))
    day_verdicts: list[DayVerdict] = []
    for pull_file in pull_files:
        pull_payload = json.loads(pull_file.read_text(encoding="utf-8"))
        day = date.fromisoformat(pull_payload["date"])
        files = select_day_files(args.node_log_dir, day)
        if not files:
            day_verdicts.append(
                day_verdict(
                    day=day, replay=None, pull_attempted=False, pair=None,
                    differences=(), error_counts=None, node_down=True,
                )
            )
            continue
        records = filter_unit_records(
            tuple(record for path in files for record in iter_node_log_records(path)), day=day
        )
        replay = replay_cycles(records)
        errors = count_errors(records)
        day_verdicts.append(
            day_verdict(
                day=day, replay=replay, pull_attempted=True, pair=None,
                differences=(), error_counts=errors,
            )
        )
    note = render_note(day_verdicts, closing_rule_header="# WP-D1 discovery set equality")
    args.out.write_text(note, encoding="utf-8")
    return 0


if __name__ == "__main__":  # pragma: no cover
    import sys

    raise SystemExit(main(sys.argv[1:]))
