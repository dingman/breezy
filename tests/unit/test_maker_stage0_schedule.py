"""MAKER-S2 WP1: process schedule (PRIMARY), logged-relaunch overlay, outage and log patterns.

Plan r4 delta (d). Log files are synthetic ``tmp_path`` files shaped like the node's real stdout
(the boot/permit line shapes are also pinned against the repo's discovery_pull fixture log).
"""

from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path

import pytest

from breezy.runtime.trade_supervisor_core import (
    LAUNCH_UTC,
    PERMIT_ISSUED_MARKER,
    STOP_PRIOR_UTC,
)
from scripts.analysis.maker_stage0_nodelog import (
    BOOT_LINE_RE,
    PERMIT_LINE_RE,
    LogStatus,
    PermitLine,
    boot_to_permit_latencies_ns,
    boots_without_permit,
    classify_day,
    permit_meets_window,
    scan_node_log,
)
from scripts.analysis.maker_stage0_schedule import (
    day_log_status,
    overlay_schedule,
    primary_schedule,
    process_schedule,
    schedule_to_dict,
    write_schedule,
)

NS = 1_000_000_000
D = dt.date(2026, 9, 20)
REAL_LOG = Path("tests/fixtures/discovery_pull/breezy-trade-20261002T165039Z.log")


def _ns(day: dt.date, hh: int, mm: int = 0, ss: int = 0) -> int:
    return (
        int(dt.datetime(day.year, day.month, day.day, hh, mm, ss, tzinfo=dt.UTC).timestamp()) * NS
    )


def _stamp(ns: int) -> str:
    moment = dt.datetime.fromtimestamp(ns // NS, dt.UTC)
    return moment.strftime("%Y-%m-%d %H:%M:%S") + f",{(ns % NS) // 1_000_000:03d}"


def _boot(ns: int) -> str:
    return f"{_stamp(ns)} [INFO] breezy.app.trade.boot: boot_family_declared id=pm_us_crh_fq_v1"


def _permit(ns: int, *, issued: int | None = None, ttl_s: int = 36000) -> str:
    issued_ns = ns if issued is None else issued
    return (
        f"{_stamp(ns)} [INFO] breezy.app.trade.boot: live-trading permit issued "
        f"issued_at_ns={issued_ns} expires_at_ns={issued_ns + ttl_s * NS} ttl_s={ttl_s}"
    )


def _nautilus(ns: int) -> str:
    moment = dt.datetime.fromtimestamp(ns // NS, dt.UTC)
    return (
        moment.strftime("%Y-%m-%dT%H:%M:%S")
        + f".{ns % NS:09d}Z [INF] BREEZY-L001.TradingNode: tick"
    )


def _log(path: Path, *lines: str, skew_s: int = 0, name: str | None = None) -> Path:
    """Write ``lines`` to ``breezy-trade-<UTC stamp of the first line>.log`` (as the node does).

    ``path`` only supplies the directory; ``skew_s`` moves the file-name stamp away from the
    first line, ``name`` overrides the whole file name.
    """
    first = dt.datetime.strptime(lines[0][:19].replace("T", " "), "%Y-%m-%d %H:%M:%S").replace(
        tzinfo=dt.UTC
    )
    stamped = first - dt.timedelta(seconds=skew_s)
    target = path.parent / (name or f"breezy-trade-{stamped:%Y%m%dT%H%M%S}Z.log")
    target.write_text("\n".join(lines) + "\n")
    return target


def _window(day: dt.date) -> tuple[int, int]:
    start = _ns(day - dt.timedelta(days=1), 16, 50)
    return start, _ns(day, 2, 50)


# --- line patterns pinned against real-shaped lines ---------------------------------------


def test_boot_and_permit_patterns_match_the_repo_discovery_pull_log_shapes() -> None:
    lines = REAL_LOG.read_text().splitlines()
    boot = BOOT_LINE_RE.match(lines[0])
    assert boot is not None and boot["family"] == "pm_us_crh_fq_v1"
    permit = PERMIT_LINE_RE.match(lines[1])
    assert permit is not None
    assert (permit["issued"], permit["expires"], permit["ttl"]) == (
        "1790959840786860859",
        "1790995840786860859",
        "36000",
    )
    assert PERMIT_ISSUED_MARKER in lines[1]  # same wording as the supervisor's own marker
    assert BOOT_LINE_RE.match(lines[1]) is None and PERMIT_LINE_RE.match(lines[0]) is None


def test_patterns_reject_near_misses() -> None:
    assert BOOT_LINE_RE.match("2026-10-02 16:50:40,786 [INFO] x.y: boot_family id=abc") is None
    assert (
        PERMIT_LINE_RE.match(
            "2026-10-02 16:50:40,787 [INFO] x.y: order submission permit not issued: E"
        )
        is None
    )


# --- primary schedule ---------------------------------------------------------------------


def test_nominal_schedule_is_1650z_to_0250z_with_midnight_cut() -> None:
    sched = primary_schedule(D)
    assert (sched.window_start_ns, sched.window_end_ns) == (
        _ns(D - dt.timedelta(days=1), 16, 50),
        _ns(D, 2, 50),
    )
    assert dt.time(16, 50) == LAUNCH_UTC
    cuts = {c.kind: c.instant_ns for c in sched.cuts}
    assert cuts["GTD_MIDNIGHT"] == _ns(D, 0, 0)
    assert cuts["STOP_PRIOR"] == _ns(D, STOP_PRIOR_UTC.hour, STOP_PRIOR_UTC.minute)
    assert cuts["PERMIT_EXPIRY"] == sched.window_end_ns
    assert [c.instant_ns for c in sched.cuts] == sorted(c.instant_ns for c in sched.cuts)
    assert "RELAUNCH" not in cuts


def test_nominal_schedule_is_primary_on_every_day(tmp_path: Path) -> None:
    days = [D + dt.timedelta(days=i) for i in range(3)]
    a = process_schedule(days)
    assert list(a) == days and all(a[d] == primary_schedule(d) for d in days)
    # The overlay never touches the primary mapping.
    start, end = _window(days[0])
    log = _log(
        tmp_path / "n.log",
        _boot(start - 600 * NS),
        _permit(start - 600 * NS),
        _boot(start + 3 * 3600 * NS),
        _nautilus(end + 60 * NS),
    )
    overlay_schedule(days, [scan_node_log(log)])
    assert process_schedule(days) == a


# --- overlay ------------------------------------------------------------------------------


def test_logged_relaunch_adds_a_cut_in_overlay_only(tmp_path: Path) -> None:
    start, end = _window(D)
    relaunch = start + 4 * 3600 * NS
    log = _log(
        tmp_path / "n.log",
        _boot(start + 40 * NS),
        _permit(start + 41 * NS),
        _boot(relaunch),
        _permit(relaunch + NS),
        _nautilus(end + 3600 * NS),
    )
    scans = [scan_node_log(log)]
    primary = process_schedule([D])[D]
    overlay = overlay_schedule([D], scans)[D]
    assert [c for c in primary.cuts if c.kind == "RELAUNCH"] == []
    assert [(c.kind, c.instant_ns) for c in overlay.cuts if c.kind == "RELAUNCH"] == [
        ("RELAUNCH", relaunch)
    ]
    assert {c for c in overlay.cuts if c.kind != "RELAUNCH"} == set(primary.cuts)
    assert [c.instant_ns for c in overlay.cuts] == sorted(c.instant_ns for c in overlay.cuts)


def test_the_launch_boot_is_not_a_relaunch_cut(tmp_path: Path) -> None:
    start, end = _window(D)
    log = _log(
        tmp_path / "n.log",
        _boot(start + 40 * NS),
        _permit(start + 41 * NS),
        _nautilus(end + 60 * NS),
    )
    assert overlay_schedule([D], [scan_node_log(log)])[D] == primary_schedule(D)


def test_node_booted_before_the_window_has_no_in_window_boot_but_a_permit(tmp_path: Path) -> None:
    start, end = _window(D)
    early = start - 1200 * NS
    log = _log(tmp_path / "n.log", _boot(early), _permit(early), _nautilus(end + 60 * NS))
    scan = scan_node_log(log)
    assert classify_day([scan], (start, end)) is LogStatus.LIVE
    # A later boot inside the window is a relaunch in that case.
    relaunch = start + 2 * 3600 * NS
    log2 = _log(
        tmp_path / "n2.log",
        _boot(early),
        _permit(early),
        _boot(relaunch),
        _permit(relaunch + NS),
        _nautilus(end + 60 * NS),
    )
    cuts = overlay_schedule([D], [scan_node_log(log2)])[D].cuts
    assert [c.instant_ns for c in cuts if c.kind == "RELAUNCH"] == [relaunch]


# --- pinned readings (plan delta (d), review M2-M4) ---------------------------------------


def test_permit_validity_is_half_open_issued_inclusive_expires_exclusive() -> None:
    window = (1000 * NS, 2000 * NS)
    assert permit_meets_window(PermitLine(0, 900 * NS, 1001 * NS), window)
    assert not permit_meets_window(PermitLine(0, 900 * NS, 1000 * NS), window)  # expires at start
    assert permit_meets_window(PermitLine(0, 1999 * NS, 3000 * NS), window)
    assert not permit_meets_window(PermitLine(0, 2000 * NS, 3000 * NS), window)  # issued at end


def test_a_log_whose_file_name_stamp_disagrees_with_its_first_line_is_node_log_absent(
    tmp_path: Path,
) -> None:
    start, end = _window(D)
    lines = (_boot(start + 30 * NS), _permit(start + 31 * NS), _nautilus(end + 60 * NS))
    near = scan_node_log(_log(tmp_path / "a.log", *lines, skew_s=119))
    assert near.rejected is None
    assert classify_day([near], (start, end)) is LogStatus.LIVE
    far = scan_node_log(_log(tmp_path / "b.log", *lines, skew_s=-121))
    assert far.rejected is not None and "120 s" in far.rejected
    assert classify_day([far], (start, end)) is LogStatus.NODE_LOG_ABSENT
    # A local-time host would shift asctime by hours: the same check catches it.
    shifted = scan_node_log(_log(tmp_path / "c.log", *lines, skew_s=-7 * 3600))
    assert classify_day([shifted], (start, end)) is LogStatus.NODE_LOG_ABSENT
    assert overlay_schedule([D], [far])[D] == primary_schedule(D)


def test_a_log_without_a_utc_file_name_stamp_cannot_be_verified_and_is_absent(
    tmp_path: Path,
) -> None:
    start, end = _window(D)
    log = _log(tmp_path / "n.log", _boot(start + 30 * NS), _nautilus(end + 60 * NS), name="n.log")
    scan = scan_node_log(log)
    assert scan.rejected is not None and "file name" in scan.rejected
    assert classify_day([scan], (start, end)) is LogStatus.NODE_LOG_ABSENT


def test_the_real_repo_fixture_log_passes_the_file_name_check() -> None:
    assert scan_node_log(REAL_LOG).rejected is None


def test_launch_grace_applies_only_when_the_first_line_is_the_boot_line(tmp_path: Path) -> None:
    start, end = _window(D)
    boot_first = _log(tmp_path / "a.log", _boot(start + 500 * NS), _nautilus(end + 60 * NS))
    scan = scan_node_log(boot_first)
    assert scan.first_is_boot
    assert classify_day([scan], (start, end)) is LogStatus.LIVE
    # The same late start behind a non-boot first line leaves up to 10 min unobserved.
    other_first = _log(
        tmp_path / "b.log",
        _nautilus(start + 500 * NS),
        _boot(start + 501 * NS),
        _nautilus(end + 60 * NS),
    )
    scan2 = scan_node_log(other_first)
    assert not scan2.first_is_boot
    assert classify_day([scan2], (start, end)) is LogStatus.NODE_LOG_ABSENT
    # Past the grace even a boot-first log does not cover.
    late = scan_node_log(
        _log(tmp_path / "c.log", _boot(start + 601 * NS), _nautilus(end + 60 * NS))
    )
    assert classify_day([late], (start, end)) is LogStatus.NODE_LOG_ABSENT


def test_a_hand_boot_before_the_window_in_a_covering_log_is_up_not_outage(tmp_path: Path) -> None:
    start, end = _window(D)
    early = start - 900 * NS  # orders-off node: boot line, no permit line
    log = _log(tmp_path / "n.log", _boot(early), _nautilus(end + 60 * NS))
    scan = scan_node_log(log)
    assert classify_day([scan], (start, end)) is LogStatus.LIVE
    # A boot before the window in a log that stops mid-window does not make the day LIVE.
    stops = scan_node_log(_log(tmp_path / "m.log", _boot(early), _nautilus(end - 3600 * NS)))
    assert classify_day([stops], (start, end)) is LogStatus.NODE_LOG_ABSENT
    # And a later in-window boot is then a relaunch (it minted a permit).
    relaunch = start + 2 * 3600 * NS
    log2 = _log(
        tmp_path / "n2.log",
        _boot(early),
        _boot(relaunch),
        _permit(relaunch + NS),
        _nautilus(end + 60 * NS),
    )
    cuts = overlay_schedule([D], [scan_node_log(log2)])[D].cuts
    assert [c.instant_ns for c in cuts if c.kind == "RELAUNCH"] == [relaunch]


def test_a_boot_that_never_mints_a_permit_is_not_a_relaunch_cut(tmp_path: Path) -> None:
    start, end = _window(D)
    dead, live = start + 3600 * NS, start + 2 * 3600 * NS
    log = _log(
        tmp_path / "n.log",
        _boot(start + 30 * NS),
        _permit(start + 31 * NS),
        _boot(dead),  # died at the permit mint: no permit line before the next boot
        _boot(live),
        _permit(live + NS),
        _boot(end - 3600 * NS),  # a trailing boot with no permit at all
        _nautilus(end + 60 * NS),
    )
    scans = [scan_node_log(log)]
    cuts = overlay_schedule([D], scans)[D].cuts
    assert [c.instant_ns for c in cuts if c.kind == "RELAUNCH"] == [live]
    # The dead boots are surfaced for the report, never silently dropped.
    assert boots_without_permit(scans, (start, end)) == [dead, end - 3600 * NS]


def test_the_first_in_window_boot_is_the_launch_even_without_a_permit(tmp_path: Path) -> None:
    start, end = _window(D)
    second = start + 2 * 3600 * NS
    log = _log(
        tmp_path / "n.log",
        _boot(start + 30 * NS),
        _boot(second),
        _permit(second + NS),
        _nautilus(end + 60 * NS),
    )
    cuts = overlay_schedule([D], [scan_node_log(log)])[D].cuts
    assert [c.instant_ns for c in cuts if c.kind == "RELAUNCH"] == [second]


# --- outage / absence ---------------------------------------------------------------------


def test_full_day_outage_needs_covering_log_without_boot_or_permit_line(tmp_path: Path) -> None:
    start, end = _window(D)
    quiet = _log(
        tmp_path / "q.log",
        _nautilus(start - 7200 * NS),
        _nautilus(start + 3600 * NS),
        _nautilus(end + 7200 * NS),
    )
    assert classify_day([scan_node_log(quiet)], (start, end)) is LogStatus.OUTAGE
    # A boot line anywhere inside the window: not an outage.
    with_boot = _log(
        tmp_path / "b.log",
        _nautilus(start - 7200 * NS),
        _boot(start + 60 * NS),
        _nautilus(end + 7200 * NS),
    )
    assert classify_day([scan_node_log(with_boot)], (start, end)) is LogStatus.LIVE
    # A permit line printed before the window whose validity reaches into it.
    permit_only = _log(
        tmp_path / "p.log",
        _nautilus(start - 7200 * NS),
        _permit(start - 600 * NS),
        _nautilus(end + 7200 * NS),
    )
    assert classify_day([scan_node_log(permit_only)], (start, end)) is LogStatus.LIVE
    # A permit that expired before the window does not count.
    stale = _log(
        tmp_path / "s.log",
        _nautilus(start - 90000 * NS),
        _permit(start - 80000 * NS, ttl_s=3600),
        _nautilus(end + 7200 * NS),
    )
    assert classify_day([scan_node_log(stale)], (start, end)) is LogStatus.OUTAGE


def test_absent_or_partial_node_log_keeps_day_on_primary_schedule(tmp_path: Path) -> None:
    start, end = _window(D)
    partial_tail = _log(tmp_path / "a.log", _nautilus(start - 600 * NS), _nautilus(end - 3600 * NS))
    partial_head = _log(
        tmp_path / "b.log", _nautilus(start + 3 * 3600 * NS), _nautilus(end + 3600 * NS)
    )
    for log in (partial_tail, partial_head):
        scan = scan_node_log(log)
        assert classify_day([scan], (start, end)) is LogStatus.NODE_LOG_ABSENT
    assert classify_day([], (start, end)) is LogStatus.NODE_LOG_ABSENT
    # No logs at all: the day is node_log_absent and its schedule is the primary one.
    status = day_log_status([D], [])
    assert status == {D: LogStatus.NODE_LOG_ABSENT}
    assert overlay_schedule([D], [])[D] == primary_schedule(D)
    assert overlay_schedule([D], [scan_node_log(partial_tail)])[D] == primary_schedule(D)


def test_two_files_that_abut_cover_a_window_together(tmp_path: Path) -> None:
    start, end = _window(D)
    mid = start + 5 * 3600 * NS
    one = _log(tmp_path / "1.log", _boot(start + 30 * NS), _nautilus(mid))
    two = _log(tmp_path / "2.log", _nautilus(mid - 60 * NS), _nautilus(end + 60 * NS))
    assert classify_day([scan_node_log(one), scan_node_log(two)], (start, end)) is LogStatus.LIVE
    gap = _log(tmp_path / "3.log", _nautilus(mid + 600 * NS), _nautilus(end + 60 * NS))
    assert classify_day([scan_node_log(one), scan_node_log(gap)], (start, end)) is (
        LogStatus.NODE_LOG_ABSENT
    )


def test_a_log_that_starts_within_the_launch_grace_still_covers_the_window_start(
    tmp_path: Path,
) -> None:
    start, end = _window(D)
    log = _log(
        tmp_path / "g.log",
        _boot(start + 39 * NS),
        _permit(start + 40 * NS),
        _nautilus(end + 60 * NS),
    )
    assert classify_day([scan_node_log(log)], (start, end)) is LogStatus.LIVE


# --- scan facts ---------------------------------------------------------------------------


def test_scan_records_pinned_file_facts_and_boot_to_permit_latency(tmp_path: Path) -> None:
    start, _ = _window(D)
    log = _log(
        tmp_path / "n.log",
        _boot(start + 10 * NS),
        _permit(start + 12 * NS),
        "garbage line",
        _nautilus(start + 100 * NS),
    )
    scan = scan_node_log(log)
    assert scan.size == log.stat().st_size and len(scan.sha256) == 64
    assert (scan.first_ns, scan.last_ns) == (start + 10 * NS, start + 100 * NS)
    assert scan.boots == (start + 10 * NS,)
    assert [(p.issued_ns, p.expires_ns) for p in scan.permits] == [
        (start + 12 * NS, start + 12 * NS + 36000 * NS)
    ]
    assert boot_to_permit_latencies_ns([scan]) == [2 * NS]


def test_an_empty_or_unparseable_log_covers_nothing(tmp_path: Path) -> None:
    empty = tmp_path / "e.log"
    empty.write_text("")
    scan = scan_node_log(empty)
    assert scan.first_ns is None and classify_day([scan], _window(D)) is LogStatus.NODE_LOG_ABSENT


# --- serialisation ------------------------------------------------------------------------


def test_schedule_json_is_deterministic_and_keyed_by_day(tmp_path: Path) -> None:
    days = [D + dt.timedelta(days=1), D]
    out = tmp_path / "process_schedule.json"
    write_schedule(out, process_schedule(days))
    first = out.read_bytes()
    write_schedule(out, process_schedule(list(reversed(days))))
    assert out.read_bytes() == first
    body = json.loads(first)
    assert list(body["days"]) == sorted(body["days"])
    day = body["days"][D.isoformat()]
    assert day["window_start_ns"] < day["window_end_ns"] and day["cuts"][0]["kind"]
    assert schedule_to_dict(process_schedule([D]))["days"][D.isoformat()] == day
    assert body["schedule"] == "PRIMARY"


def test_schedule_json_is_written_atomically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = tmp_path / "process_schedule.json"
    out.write_text("OLD")

    def boom(*args: object, **kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError, match="disk full"):
        write_schedule(out, process_schedule([D]))
    assert out.read_text() == "OLD"
