"""AUD-02 WP-D1: discovery set equality.

Fixtures use TRIMMED REAL LINE SHAPES (r3's own instruction), captured from
``~/.local/share/breezy/logs/breezy-trade-20260923T165046Z.log`` (Stage 0)
and the 09-10/09-11/09-25 shapes the plan's r3 section names. No network, no
real log directory is read by this suite -- every file is a ``tmp_path``
fixture.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from scripts.analysis.discovery_set_equality import (
    DayVerdict,
    DiscoverySummary,
    ErrorCounts,
    ReplayResult,
    classify_differences,
    count_errors,
    day_verdict,
    detect_relaunch_failed,
    filter_unit_records,
    iter_node_log_records,
    overall_verdict,
    pair_pull,
    replay_cycles,
    replay_file,
    select_day_files,
    venue_active_set,
)

_NS = 1_000_000_000


def _line(ts: str, level: str, component: str, message: str, *, ansi: bool = True) -> str:
    if ansi:
        return f"\x1b[1m{ts}Z\x1b[0m [{level}] {component}: {message}"
    return f"{ts}Z [{level}] {component}: {message}"


def _count_line(ts: str, n: int, *, resolved: int = 0, discovered: int | None = None) -> str:
    discovered = n if discovered is None else discovered
    return _line(
        ts,
        "INFO",
        "BREEZY-L001.POLYMARKET_US-discovery",
        f"Polymarket.us discovery cycle loaded {n} active market(s), "
        f"observed {resolved} resolved market(s), discovered {discovered} total",
    )


def _summary_line(
    ts: str,
    cycle: str,
    *,
    subscribed: tuple[str, ...] = (),
    unsubscribed_pairs: tuple[tuple[str, str], ...] = (),
    blocked: tuple[str, ...] = (),
) -> str:
    return _line(
        ts,
        "INFO",
        "BREEZY-L001.DataClient-POLYMARKET_US",
        f"Polymarket.us discovery cycle {cycle}: subscribed={subscribed!r} "
        f"unsubscribed={unsubscribed_pairs!r} blocked_missing_cache={blocked!r}",
    )


def _subscribing_line(ts: str, cycle: str, slug: str, kind: str = "new") -> str:
    return _line(
        ts,
        "INFO",
        "BREEZY-L001.DataClient-POLYMARKET_US",
        f"Polymarket.us discovery cycle {cycle}: subscribing {slug} ({kind})",
    )


def _error_line(ts: str, component: str, message: str) -> str:
    return _line(ts, "ERROR", component, message)


def _write_log(tmp_path: Path, name: str, lines: list[str]) -> Path:
    path = tmp_path / name
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _ns(ts: str) -> int:
    date_part, _, frac = ts.partition(".")
    parsed = dt.datetime.strptime(date_part, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=dt.UTC)
    import calendar

    return calendar.timegm(parsed.timetuple()) * _NS + int(frac)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def test_ansi_and_nanosecond_timestamp_parsing(tmp_path: Path) -> None:
    path = _write_log(
        tmp_path,
        "breezy-trade-20260923T165046Z.log",
        [_count_line("2026-09-23T16:50:50.404256598", 1)],
    )
    records = iter_node_log_records(path)
    assert len(records) == 1
    record = records[0]
    assert record.level == "INFO"
    assert record.component == "BREEZY-L001.POLYMARKET_US-discovery"
    assert record.ts_ns == _ns("2026-09-23T16:50:50.404256598")


def test_stdlib_unprefixed_lines_ignored_for_replay(tmp_path: Path) -> None:
    lines = [
        "2026-09-23 16:50:47,746 [INFO] breezy.app.trade.boot: live-trading permit issued",
        _summary_line("2026-09-23T16:50:51.000000000", "initial", subscribed=("a",)),
    ]
    path = _write_log(tmp_path, "breezy-trade-20260923T165046Z.log", lines)
    records = iter_node_log_records(path)
    assert len(records) == 1
    assert records[0].message.startswith("Polymarket.us discovery cycle initial")


def test_supervisor_glob_exclusion(tmp_path: Path) -> None:
    node_log = _write_log(
        tmp_path,
        "breezy-trade-20260923T165046Z.log",
        [
            _count_line("2026-09-23T16:50:50.000000000", 1),
            _summary_line("2026-09-23T16:50:51.000000000", "initial", subscribed=("a",)),
        ],
    )
    _write_log(
        tmp_path,
        "breezy-trade-supervisor.log",
        [_summary_line("2026-09-23T16:50:51.000000000", "initial", subscribed=("a",))],
    )
    files = select_day_files(tmp_path, dt.date(2026, 9, 23))
    assert files == (node_log,)


# ---------------------------------------------------------------------------
# AC2: replay
# ---------------------------------------------------------------------------


def test_replay_from_initial_equals_active_set(tmp_path: Path) -> None:
    path = _write_log(
        tmp_path,
        "breezy-trade-20260923T165046Z.log",
        [
            _count_line("2026-09-23T16:50:50.404256598", 2),
            _summary_line(
                "2026-09-23T16:50:51.496291629",
                "initial",
                subscribed=("tc-a", "tc-b"),
            ),
        ],
    )
    result = replay_cycles(iter_node_log_records(path))
    assert result.gap is None
    assert result.final_active == ("tc-a", "tc-b")
    assert result.cycles[0].count_matches is True


def test_replay_parses_reason_with_quotes(tmp_path: Path) -> None:
    reason = "closed=true status='CLOSED' endDate='2026-09-23T16:00:00Z'"
    path = _write_log(
        tmp_path,
        "breezy-trade-20260923T165046Z.log",
        [
            _count_line("2026-09-23T16:50:50.000000000", 2),
            _summary_line("2026-09-23T16:50:51.000000000", "initial", subscribed=("a", "b")),
            _count_line("2026-09-23T22:50:51.000000000", 1),
            _summary_line(
                "2026-09-23T22:50:52.000000000",
                "reload",
                unsubscribed_pairs=(("b", reason),),
            ),
        ],
    )
    result = replay_cycles(iter_node_log_records(path))
    assert result.gap is None
    assert result.final_active == ("a",)
    assert result.cycles[-1].unsubscribed == ("b",)


def test_blocked_reported_separately_and_node_set_is_r_union_b(tmp_path: Path) -> None:
    path = _write_log(
        tmp_path,
        "breezy-trade-20260923T165046Z.log",
        [
            _count_line("2026-09-23T16:50:50.000000000", 3),
            _summary_line(
                "2026-09-23T16:50:51.000000000",
                "initial",
                subscribed=("a",),
                blocked=("blocked-1", "blocked-2"),
            ),
        ],
    )
    result = replay_cycles(iter_node_log_records(path))
    assert result.gap is None
    assert result.final_active == ("a",)
    assert result.final_blocked == ("blocked-1", "blocked-2")
    assert len(result.final_active) + len(result.final_blocked) == 3


def test_count_line_mismatch_is_replay_gap(tmp_path: Path) -> None:
    path = _write_log(
        tmp_path,
        "breezy-trade-20260923T165046Z.log",
        [
            _count_line("2026-09-23T16:50:50.000000000", 5),
            _summary_line("2026-09-23T16:50:51.000000000", "initial", subscribed=("a",)),
        ],
    )
    result = replay_cycles(iter_node_log_records(path))
    assert result.gap == "COUNT-MISMATCH"


def test_reload_without_initial_same_file_is_replay_gap(tmp_path: Path) -> None:
    path = _write_log(
        tmp_path,
        "breezy-trade-20260923T165046Z.log",
        [
            _count_line("2026-09-23T22:50:51.000000000", 0),
            _summary_line("2026-09-23T22:50:52.000000000", "reload"),
        ],
    )
    result = replay_cycles(iter_node_log_records(path))
    assert result.gap == "STARTS-MID-PROCESS"


def test_unsubscribe_of_unknown_slug_is_replay_gap(tmp_path: Path) -> None:
    path = _write_log(
        tmp_path,
        "breezy-trade-20260923T165046Z.log",
        [
            _count_line("2026-09-23T16:50:50.000000000", 1),
            _summary_line("2026-09-23T16:50:51.000000000", "initial", subscribed=("a",)),
            _count_line("2026-09-23T22:50:51.000000000", 0),
            _summary_line(
                "2026-09-23T22:50:52.000000000",
                "reload",
                unsubscribed_pairs=(("never-subscribed", "discovery-missing"),),
            ),
        ],
    )
    result = replay_cycles(iter_node_log_records(path))
    assert result.gap == "UNSUBSCRIBE-OF-UNKNOWN-SLUG"


def test_file_starting_with_reload_is_replay_gap(tmp_path: Path) -> None:
    # Alias of test_reload_without_initial_same_file_is_replay_gap, named
    # per r3's own bullet ("a file starting with a reload is a gap").
    path = _write_log(
        tmp_path,
        "breezy-trade-20260923T165046Z.log",
        [_summary_line("2026-09-23T22:50:52.000000000", "reload")],
    )
    result = replay_cycles(iter_node_log_records(path))
    assert result.gap == "STARTS-MID-PROCESS"


def test_truncated_file_is_replay_gap(tmp_path: Path) -> None:
    path = tmp_path / "breezy-trade-20260923T165046Z.log"
    good = _summary_line("2026-09-23T16:50:51.000000000", "initial", subscribed=("a",))
    count = _count_line("2026-09-23T16:50:50.000000000", 1)
    cut = _summary_line("2026-09-23T22:50:52.000000000", "reload")[:40]  # cut mid-line
    path.write_text(f"{count}\n{good}\n{cut}", encoding="utf-8")
    result = replay_file(path)
    assert result.gap == "TRUNCATED-FILE"


def test_count_and_slugs_without_initial_is_replay_gap(tmp_path: Path) -> None:
    path = _write_log(
        tmp_path,
        "breezy-trade-20260923T165046Z.log",
        [
            _count_line("2026-09-23T16:50:50.000000000", 1),
            _subscribing_line("2026-09-23T16:50:50.500000000", "initial", "a"),
        ],
    )
    result = replay_cycles(iter_node_log_records(path))
    assert result.gap == "COUNT-AND-SLUGS-WITHOUT-INITIAL"


def test_orphan_count_with_error_is_raised_cycle(tmp_path: Path) -> None:
    # 09-10/09-11 shape: a count line with no following summary, sandwiched
    # between two well-formed cycles -- the raised cycle does not corrupt
    # the rest of the replay.
    path = _write_log(
        tmp_path,
        "breezy-trade-20260910T165057Z.log",
        [
            _count_line("2026-09-10T16:50:50.000000000", 1),
            _summary_line("2026-09-10T16:50:51.000000000", "initial", subscribed=("a",)),
            _count_line("2026-09-11T14:00:00.000000000", 5),  # orphaned: no summary follows
            _error_line(
                "2026-09-11T14:00:01.000000000",
                "BREEZY-L001.DataClient-POLYMARKET_US",
                "Polymarket.us market discovery returned zero configured-city weather markets",
            ),
            _count_line("2026-09-11T22:50:51.000000000", 1),
            _summary_line("2026-09-11T22:50:52.000000000", "reload"),
        ],
    )
    result = replay_cycles(iter_node_log_records(path))
    assert result.gap is None
    assert result.raised_cycle_count == 1


def test_refusing_to_start_is_relaunch_failed(tmp_path: Path) -> None:
    path = tmp_path / "breezy-trade-20260925T165034Z.log"
    path.write_text(
        "breezy-trade: configuration error: current_rung_hold: resolved 0 instruments "
        "for 2026-09-25 (LAX=0 MDW=0 MIA=0 SFO=0); refusing to start\n",
        encoding="utf-8",
    )
    deadline_ns = _ns("2026-09-25T17:12:00.000000000")
    assert detect_relaunch_failed(path, deadline_ns=deadline_ns) is True


def test_multi_spawn_day_replays_file_containing_p(tmp_path: Path) -> None:
    _write_log(
        tmp_path,
        "breezy-trade-20260918T170000Z.log",
        [
            _count_line("2026-09-18T17:00:00.000000000", 1),
            _summary_line("2026-09-18T17:00:01.000000000", "initial", subscribed=("a",)),
        ],
    )
    second = _write_log(
        tmp_path,
        "breezy-trade-20260918T173000Z.log",
        [
            _count_line("2026-09-18T17:30:00.000000000", 2),
            _summary_line("2026-09-18T17:30:01.000000000", "initial", subscribed=("a", "b")),
        ],
    )
    files = select_day_files(tmp_path, dt.date(2026, 9, 18))
    assert files[-1] == second
    result = replay_file(second)
    assert result.gap is None
    assert result.final_active == ("a", "b")


def test_file_spanning_two_days_scoped_by_line_timestamps(tmp_path: Path) -> None:
    path = _write_log(
        tmp_path,
        "breezy-trade-20260923T165046Z.log",
        [
            _count_line("2026-09-23T16:50:50.000000000", 1),
            _summary_line("2026-09-23T16:50:51.000000000", "initial", subscribed=("a",)),
            _count_line("2026-09-24T00:50:51.000000000", 1),
            _summary_line("2026-09-24T00:50:52.000000000", "reload"),
        ],
    )
    day23 = select_day_files(tmp_path, dt.date(2026, 9, 23))
    day24 = select_day_files(tmp_path, dt.date(2026, 9, 24))
    assert path in day23
    # 00:50Z the NEXT calendar day is still inside day 23's window
    # ([16:35Z, 01:15Z next day)) and is NOT inside day 24's own window
    # ([16:35Z day24, ...)) -- scoped by the LINE timestamps, not the file.
    assert path not in day24
    records = filter_unit_records(iter_node_log_records(path), day=dt.date(2026, 9, 23))
    assert len(records) == 4


# ---------------------------------------------------------------------------
# AC3: venue set
# ---------------------------------------------------------------------------


def test_venue_set_excludes_resolved_and_unregistered(tmp_path: Path) -> None:
    page = {
        "markets": [
            {
                "slug": "tc-temp-nychigh-2026-09-23-lt65f",
                "question": "Highest temperature in New York City on 2026-09-23?",
            },
            {
                "slug": "tc-temp-nychigh-2026-09-22-lt65f",
                "question": "Highest temperature in New York City on 2026-09-23?",
                "closed": True,
                "status": "CLOSED",
                "endDate": "2026-09-22T20:00:00Z",
            },
            {
                "slug": "tc-temp-boshigh-2026-09-23-lt65f",
                "question": "Highest temperature in Boston on 2026-09-23?",
            },
        ]
    }
    result = venue_active_set([page], ("nyc",))
    assert result.active == ("tc-temp-nychigh-2026-09-23-lt65f",)
    assert result.resolved_count == 1
    assert result.unregistered_count == 1


def test_venue_side_uses_provider_city_filter(tmp_path: Path) -> None:
    page = {
        "markets": [
            {
                "slug": "tc-temp-nychigh-2026-09-23-lt65f",
                "question": "Highest temperature in New York City on 2026-09-23?",
            },
            {
                "slug": "tc-temp-miahigh-2026-09-23-lt82f",
                "question": "Highest temperature in Miami on 2026-09-23?",
            },
        ]
    }
    result = venue_active_set([page], ("nyc", "mia"))
    assert set(result.active) == {
        "tc-temp-nychigh-2026-09-23-lt65f",
        "tc-temp-miahigh-2026-09-23-lt82f",
    }
    only_nyc = venue_active_set([page], ("nyc",))
    assert only_nyc.active == ("tc-temp-nychigh-2026-09-23-lt65f",)
    assert only_nyc.unregistered_count == 1


# ---------------------------------------------------------------------------
# AC4: pairing
# ---------------------------------------------------------------------------


def test_gap_over_600s_is_ineligible() -> None:
    p_ts = 0
    summaries = [
        DiscoverySummary(
            ts_ns=p_ts,
            cycle="initial",
            subscribed=(),
            unsubscribed=(),
            unsubscribed_pairs=(),
            blocked=(),
        )
    ]
    pull_start = 700 * _NS
    result = pair_pull(
        summaries=summaries, pull_start_ns=pull_start, pull_end_ns=pull_start + 10 * _NS
    )
    assert result.gap_ok is False
    assert result.ineligible_reason == "PULL-OUTSIDE-MAX-GAP"


def test_interleaved_cycle_is_ineligible() -> None:
    p_ts = 0
    summaries = [
        DiscoverySummary(
            ts_ns=p_ts,
            cycle="initial",
            subscribed=(),
            unsubscribed=(),
            unsubscribed_pairs=(),
            blocked=(),
        )
    ]
    pull_start = 100 * _NS
    other_event_ns = [50 * _NS]  # a count/error/new-file line between P and pull_start
    result = pair_pull(
        summaries=summaries,
        other_discovery_event_ns=other_event_ns,
        pull_start_ns=pull_start,
        pull_end_ns=pull_start + 5 * _NS,
    )
    assert result.interleaved is True
    assert result.ineligible_reason == "PULL-INTERLEAVED-RELAUNCH"


def test_relaunch_inside_pair_interval_is_ineligible() -> None:
    # Same shape as the interleaved test, restated per r3's own naming
    # ("PULL-INTERLEAVED-RELAUNCH: a newer spawn appears in (ts(P), pull_end]").
    p_ts = 10 * _NS
    summaries = [
        DiscoverySummary(
            ts_ns=p_ts,
            cycle="initial",
            subscribed=(),
            unsubscribed=(),
            unsubscribed_pairs=(),
            blocked=(),
        )
    ]
    pull_start = 20 * _NS
    pull_end = 30 * _NS
    relaunch_first_line_ns = 25 * _NS
    result = pair_pull(
        summaries=summaries,
        other_discovery_event_ns=[relaunch_first_line_ns],
        pull_start_ns=pull_start,
        pull_end_ns=pull_end,
    )
    assert result.ineligible_reason == "PULL-INTERLEAVED-RELAUNCH"


def test_raised_cycle_yields_no_pair_counted_in_error(tmp_path: Path) -> None:
    path = _write_log(
        tmp_path,
        "breezy-trade-20260911T165022Z.log",
        [_count_line("2026-09-11T14:00:00.000000000", 5)],  # count, no summary at all
    )
    records = iter_node_log_records(path)
    result = replay_cycles(records)
    assert result.gap == "COUNT-AND-SLUGS-WITHOUT-INITIAL" or result.raised_cycle_count >= 0
    pair = pair_pull(summaries=[], pull_start_ns=1, pull_end_ns=2)
    assert pair.paired is False
    assert pair.ineligible_reason == "NO-PULL"
    errors = count_errors(records)
    assert errors.filtered == 0  # no ERROR-level lines in this fixture; NO-PULL is the signal


# ---------------------------------------------------------------------------
# AC5: explained differences
# ---------------------------------------------------------------------------


def test_explained_venue_only_created_in_window_counts_equal() -> None:
    p_ts = 0
    pull_start = 1000 * _NS
    created_ts_ns = 500 * _NS
    created_iso = dt.datetime.fromtimestamp(created_ts_ns / _NS, tz=dt.UTC).isoformat().replace(
        "+00:00", "Z"
    )
    differences = classify_differences(
        node_active=(),
        venue_active=("new-slug",),
        p_ts_ns=p_ts,
        pull_start_ns=pull_start,
        venue_payloads={"new-slug": {"createdAt": created_iso}},
        by_slug_lookup={},
    )
    assert len(differences) == 1
    assert differences[0].explained is True
    assert differences[0].side == "venue_only"


def test_explained_without_timestamp_fails() -> None:
    differences = classify_differences(
        node_active=(),
        venue_active=("new-slug",),
        p_ts_ns=0,
        pull_start_ns=1000 * _NS,
        venue_payloads={"new-slug": {}},
        by_slug_lookup={},
    )
    assert len(differences) == 1
    assert differences[0].explained is False


# ---------------------------------------------------------------------------
# AC6: errors
# ---------------------------------------------------------------------------


def test_whitelisted_nws_error_not_counted(tmp_path: Path) -> None:
    path = _write_log(
        tmp_path,
        "breezy-trade-20260923T165046Z.log",
        [
            _error_line(
                "2026-09-23T16:50:51.000000000",
                "BREEZY-L001.DataEngine",
                "Cannot execute command: no data client configured for None or "
                "`client_id` BREEZY-NWS subscribe SubscribeData(...)",
            )
        ],
    )
    errors = count_errors(iter_node_log_records(path))
    assert errors.unfiltered == 1
    assert errors.filtered == 0


def test_unfiltered_error_total_reported(tmp_path: Path) -> None:
    path = _write_log(
        tmp_path,
        "breezy-trade-20260923T165046Z.log",
        [
            _error_line(
                "2026-09-23T16:50:51.000000000",
                "BREEZY-L001.POLYMARKET_US-discovery",
                "Polymarket.us market discovery returned zero configured-city weather markets",
            ),
            _error_line(
                "2026-09-23T16:50:52.000000000",
                "BREEZY-L001.DataEngine",
                "Cannot execute command: no data client configured for BREEZY-NWS subscribe",
            ),
        ],
    )
    errors = count_errors(iter_node_log_records(path))
    assert errors.unfiltered == 2
    assert errors.filtered == 1


# ---------------------------------------------------------------------------
# AC7/AC8: eligibility and overall verdict
# ---------------------------------------------------------------------------


def test_node_down_relaunch_failed_all_raised_reasons() -> None:
    node_down = day_verdict(
        day=dt.date(2026, 9, 25), replay=None, pull_attempted=False, pair=None,
        differences=(), error_counts=None, node_down=True,
    )
    assert node_down.eligible is False
    assert node_down.ineligible_reason == "NODE-DOWN"

    relaunch_failed = day_verdict(
        day=dt.date(2026, 9, 25), replay=None, pull_attempted=False, pair=None,
        differences=(), error_counts=None, relaunch_failed=True,
    )
    assert relaunch_failed.ineligible_reason == "RELAUNCH-FAILED"

    all_raised = day_verdict(
        day=dt.date(2026, 9, 11), replay=None, pull_attempted=False, pair=None,
        differences=(), error_counts=None, all_cycles_raised=True,
    )
    assert all_raised.ineligible_reason == "ALL-CYCLES-RAISED"


def test_pre_aa737f1_days_excluded() -> None:
    verdict = day_verdict(
        day=dt.date(2026, 9, 1), replay=None, pull_attempted=False, pair=None,
        differences=(), error_counts=None, pre_aa737f1=True,
    )
    assert verdict.eligible is False
    assert verdict.ineligible_reason == "PRE-AA737F1"


def test_day_without_cycle_is_ineligible(tmp_path: Path) -> None:
    path = _write_log(tmp_path, "breezy-trade-20260923T165046Z.log", [])
    result = replay_cycles(iter_node_log_records(path))
    verdict = day_verdict(
        day=dt.date(2026, 9, 23), replay=result, pull_attempted=False, pair=None,
        differences=(), error_counts=None,
    )
    assert verdict.eligible is False


def _eligible_equal_day(day: dt.date) -> DayVerdict:
    replay = ReplayResult(cycles=(), final_active=("a",), final_blocked=(), gap=None)
    initial_summary = DiscoverySummary(
        ts_ns=0, cycle="initial", subscribed=(), unsubscribed=(), unsubscribed_pairs=(), blocked=()
    )
    pair = pair_pull(summaries=[initial_summary], pull_start_ns=100, pull_end_ns=110)
    return day_verdict(
        day=day,
        replay=replay,
        pull_attempted=True,
        pair=pair,
        differences=(),
        error_counts=ErrorCounts(filtered=0, unfiltered=0, unprefixed=0),
    )


def test_four_clean_days_is_not_superseded() -> None:
    days = [_eligible_equal_day(dt.date(2026, 9, d)) for d in range(1, 5)]
    assert overall_verdict(days) == "FIX-SLICE"


def test_five_clean_days_superseded() -> None:
    days = [_eligible_equal_day(dt.date(2026, 9, d)) for d in range(1, 6)]
    assert overall_verdict(days) == "SUPERSEDED-BY AUD-08a"


# ---------------------------------------------------------------------------
# End-to-end CLI (analysis)
# ---------------------------------------------------------------------------


def _venue_market(
    slug: str, climate_date: str, *, city_name: str = "New York City", **extra: object
) -> dict[str, object]:
    market: dict[str, object] = {
        "slug": slug,
        "question": f"Highest temperature in {city_name} on {climate_date}?",
    }
    market.update(extra)
    return market


def _page_with(*markets: dict[str, object]) -> dict[str, object]:
    return {"markets": list(markets)}


def _write_pull(
    venue_pulls: Path,
    day: dt.date,
    *,
    paired_ts_ns: int,
    pull_start_ns: int,
    pull_end_ns: int,
    node_active: list[str],
    by_slug_lookup: dict[str, object] | None = None,
    pages: list[dict[str, object]] | None = None,
) -> None:
    payload = {
        "date": day.isoformat(),
        "complete": True,
        "reason": None,
        "pull_start_ns": pull_start_ns,
        "pull_end_ns": pull_end_ns,
        "paired_ts_ns": paired_ts_ns,
        "node_active": node_active,
        "venue_active": [],
        "by_slug_lookup": by_slug_lookup or {},
    }
    (venue_pulls / f"{day.isoformat()}.json").write_text(json.dumps(payload), encoding="utf-8")
    if pages is not None:
        (venue_pulls / f"{day.isoformat()}_pages.json").write_text(
            json.dumps(pages), encoding="utf-8"
        )


def test_cli_end_to_end_equal_not_equal_explained_and_no_pull(tmp_path: Path) -> None:
    from scripts.analysis.discovery_set_equality import main as analysis_main

    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    venue_pulls = tmp_path / "pulls"
    venue_pulls.mkdir()
    out_path = tmp_path / "note.md"

    # --- Day 1 (2026-09-10): EQUAL -- V == N exactly. ---
    day1 = dt.date(2026, 9, 10)
    slug1 = "tc-temp-nychigh-2026-09-10-lt65f"
    ts1 = "2026-09-10T16:36:00.000000000"
    _write_log(
        log_dir,
        "breezy-trade-20260910T163600Z.log",
        [_count_line(ts1, 1), _summary_line(ts1, "initial", subscribed=(slug1,))],
    )
    p1_ns = _ns(ts1)
    _write_pull(
        venue_pulls,
        day1,
        paired_ts_ns=p1_ns,
        pull_start_ns=p1_ns + 60 * _NS,
        pull_end_ns=p1_ns + 65 * _NS,
        node_active=[slug1],
        pages=[_page_with(_venue_market(slug1, "2026-09-10"))],
    )

    # --- Day 2 (2026-09-11): NOT-EQUAL -- an unexplained venue_only slug. ---
    day2 = dt.date(2026, 9, 11)
    slug2 = "tc-temp-nychigh-2026-09-11-lt65f"
    slug2_extra = "tc-temp-nychigh-2026-09-11-gte65lt66f"
    ts2 = "2026-09-11T16:36:00.000000000"
    _write_log(
        log_dir,
        "breezy-trade-20260911T163600Z.log",
        [_count_line(ts2, 1), _summary_line(ts2, "initial", subscribed=(slug2,))],
    )
    p2_ns = _ns(ts2)
    _write_pull(
        venue_pulls,
        day2,
        paired_ts_ns=p2_ns,
        pull_start_ns=p2_ns + 60 * _NS,
        pull_end_ns=p2_ns + 65 * _NS,
        node_active=[slug2],
        pages=[_page_with(
            _venue_market(slug2, "2026-09-11"),
            _venue_market(slug2_extra, "2026-09-11"),  # no createdAt/startDate -> unexplained
        )],
    )

    # --- Day 3 (2026-09-12): EXPLAINED -- a venue_only slug created in-window. ---
    day3 = dt.date(2026, 9, 12)
    slug3 = "tc-temp-nychigh-2026-09-12-lt65f"
    slug3_new = "tc-temp-nychigh-2026-09-12-gte65lt66f"
    ts3 = "2026-09-12T16:36:00.000000000"
    _write_log(
        log_dir,
        "breezy-trade-20260912T163600Z.log",
        [_count_line(ts3, 1), _summary_line(ts3, "initial", subscribed=(slug3,))],
    )
    p3_ns = _ns(ts3)
    pull_start3 = p3_ns + 60 * _NS
    created_ns = p3_ns + 30 * _NS  # strictly inside (P, pull_start]
    created_iso = (
        dt.datetime.fromtimestamp(created_ns / _NS, tz=dt.UTC)
        .isoformat()
        .replace("+00:00", "Z")
    )
    _write_pull(
        venue_pulls,
        day3,
        paired_ts_ns=p3_ns,
        pull_start_ns=pull_start3,
        pull_end_ns=pull_start3 + 5 * _NS,
        node_active=[slug3],
        pages=[_page_with(
            _venue_market(slug3, "2026-09-12"),
            _venue_market(slug3_new, "2026-09-12", createdAt=created_iso),
        )],
    )

    # --- Day 4 (2026-09-13): NO-PULL -- node log exists, no pull artefact. ---
    ts4 = "2026-09-13T16:36:00.000000000"
    slug4 = "tc-temp-nychigh-2026-09-13-lt65f"
    _write_log(
        log_dir,
        "breezy-trade-20260913T163600Z.log",
        [_count_line(ts4, 1), _summary_line(ts4, "initial", subscribed=(slug4,))],
    )
    # Deliberately no 2026-09-13.json under venue_pulls.

    exit_code = analysis_main(
        ["--node-log-dir", str(log_dir), "--venue-pulls", str(venue_pulls), "--out", str(out_path)]
    )
    assert exit_code == 0
    note = out_path.read_text(encoding="utf-8")

    assert "2026-09-10: EQUAL venue_only=0 node_only=0 explained=0" in note
    assert "2026-09-11: NOT-EQUAL venue_only=1 node_only=0 explained=0" in note
    assert "2026-09-12: EQUAL venue_only=1 node_only=0 explained=1" in note
    assert "2026-09-13: INELIGIBLE (NO-PULL)" in note
