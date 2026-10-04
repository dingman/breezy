"""AUT-1 WP5-R4: node-log hostile-input, classification, duplicate, window and hygiene tests."""

import ast
import datetime as dt
from pathlib import Path
from typing import Final

import pytest

from breezy.analysis import capture_node_log as nl
from tests.support.capture_node_log_fixtures import (
    NS,
    REAL_INSTANCE_ID,
    REAL_ORDER_FILLED,
    REAL_REFUSE,
    REAL_SUP_LAUNCHED,
    REAL_TAKE,
    REAL_TRY_SUBMIT,
    node_log_path,
    spawn_event,
    write_log,
)

# ------------------------------------------------------------------------------------------
# WP5-R4: hostile input never aborts a scan (SEC H1, H2, M3)
# ------------------------------------------------------------------------------------------

_TS0: Final[str] = "2026-10-02T20:00:00.000000000Z"


@pytest.mark.parametrize("body", ["{[]: 1}", "{{1}: 2}", "{'a': {[]: 2}}"])
def test_unhashable_dict_key_in_a_decision_line_is_unparseable_not_a_crash(
    tmp_path: Path, body: str
) -> None:
    """SEC H1: ``literal_eval`` raises ``TypeError`` for an unhashable key; the scan must go on."""
    hostile = f"{_TS0} [INFO] X: SHADOW_DECISION {body}"
    scan = nl.scan_node_log(write_log(tmp_path / "n.log", REAL_REFUSE, hostile, REAL_REFUSE))
    assert scan.unparseable_total == 1 and scan.decision_line_count == 2
    assert scan.unparseable[0].marker == "SHADOW_DECISION"


def test_overflow_error_in_literal_eval_is_unparseable_not_a_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(_text: str) -> object:
        raise OverflowError("probe")

    monkeypatch.setattr(ast, "literal_eval", boom)
    scan = nl.scan_node_log(write_log(tmp_path / "n.log", REAL_REFUSE))
    assert scan.unparseable_total == 1 and scan.decision_line_count == 0


def test_supervisor_timestamp_that_fails_strptime_is_bad_fields_not_a_crash() -> None:
    scan = nl.parse_supervisor_lines(
        [
            "2026-13-45T99:99:99Z INFO breezy.runtime.trade_supervisor launched pid=1",
            REAL_SUP_LAUNCHED,
        ]
    )
    assert scan.unparseable_total == 1 and scan.unparseable[0].cause == nl.CAUSE_BAD_FIELDS
    assert [e.pid for e in scan.spawns] == [529436]


def test_log_name_with_an_impossible_stamp_is_a_finding_and_skipped(tmp_path: Path) -> None:
    for name in ("breezy-trade-20261399T999999Z.log", "breezy-trade-20261003T165045Z.log"):
        (tmp_path / name).write_text("x")
    listing = nl.list_node_logs(tmp_path)
    assert [p.name for p in listing.paths] == ["breezy-trade-20261003T165045Z.log"]
    assert [(f.name, f.cause) for f in listing.findings] == [
        ("breezy-trade-20261399T999999Z.log", nl.CAUSE_INVALID_LOG_NAME)
    ]


# ------------------------------------------------------------------------------------------
# WP5-R4: failure vs decision by message prefix (py M2, SEC L7)
# ------------------------------------------------------------------------------------------


def test_failure_marker_beside_a_shadow_decision_mention_still_counts(tmp_path: Path) -> None:
    """The R4 fail-open: a writer failure whose text quotes a SHADOW_DECISION is a failure."""
    quoting = f"{_TS0} [ERROR] BREEZY-L001.W: sink for SHADOW_DECISION: Failed to serialize cls=<c>"
    scan = nl.scan_node_log(write_log(tmp_path / "n.log", quoting))
    assert scan.writer_failure_total == 1 and scan.unparseable_total == 0
    assert scan.decision_line_count == 0
    assert scan.writer_failures[0].marker == nl.MARKER_FAILED_TO_SERIALIZE


def test_decision_line_that_mentions_a_failure_marker_is_still_a_decision(tmp_path: Path) -> None:
    line = REAL_REFUSE.replace("'lt_63'", "'CAPTURE_PUBLISH_FAILED'")
    scan = nl.scan_node_log(write_log(tmp_path / "n.log", line))
    assert scan.decision_line_count == 1 and scan.writer_failure_total == 0


def test_failure_marker_on_a_line_with_no_timestamp_still_counts(tmp_path: Path) -> None:
    scan = nl.scan_node_log(
        write_log(tmp_path / "n.log", "Traceback ... Can't find writer for cls: X")
    )
    assert scan.writer_failure_total == 1 and scan.writer_failures[0].log_ts_ns is None


# ------------------------------------------------------------------------------------------
# WP5-R4: last_line_ts_ns, overlong lines, caps, malformed disposal
# ------------------------------------------------------------------------------------------


def test_last_line_ts_ns_ignores_untimestamped_traceback_tail(tmp_path: Path) -> None:
    scan = nl.scan_node_log(
        write_log(
            tmp_path / "n.log",
            REAL_INSTANCE_ID,
            "Traceback (most recent call last):",
            '  File "x.py", line 1, in <module>',
            "ValueError: boom",
        )
    )
    expected = int(dt.datetime(2026, 10, 2, 20, 5, 30, tzinfo=dt.UTC).timestamp()) * NS
    assert scan.last_line_ts_ns == expected + 434292449
    assert scan.line_count == 4


def test_overlong_line_is_always_counted_even_without_a_marker(tmp_path: Path) -> None:
    path = tmp_path / "n.log"
    path.write_bytes(b"x" * (nl.MAX_LINE_BYTES + 5) + b"\n" + REAL_REFUSE.encode() + b"\n")
    scan = nl.scan_node_log(path)
    assert scan.unparseable_total == 1 and scan.unparseable[0].cause == nl.CAUSE_LINE_TOO_LONG
    assert scan.decision_line_count == 1


def test_marker_in_the_drained_remainder_of_an_overlong_line_is_found(tmp_path: Path) -> None:
    path = tmp_path / "n.log"
    filler = b"x" * (nl.MAX_LINE_BYTES + 100)
    path.write_bytes(filler + b" Failed to serialize cls=<c>\n")
    scan = nl.scan_node_log(path)
    assert scan.writer_failure_total == 1 and scan.unparseable_total == 1


def test_marker_straddling_a_drain_chunk_boundary_is_found(tmp_path: Path) -> None:
    path = tmp_path / "n.log"
    marker = b"Failed to serialize"
    pad = b"x" * (nl.MAX_LINE_BYTES * 2 - 5)  # head + one full chunk, then the marker straddles
    path.write_bytes(pad + marker + b"\n")
    assert nl.scan_node_log(path).writer_failure_total == 1


def test_entries_fills_and_instance_ids_are_capped_with_exact_totals(tmp_path: Path) -> None:
    n = nl.MAX_STORED_REPORTS + 7
    ids = [
        REAL_INSTANCE_ID.replace(
            "01cea9fc-cf7d-4efa-b132-cbbaf5d0bde4", f"{i:08x}-cf7d-4efa-b132-cbbaf5d0bde4"
        )
        for i in range(n)
    ]
    scan = nl.scan_node_log(
        write_log(tmp_path / "n.log", *([REAL_TAKE] * n), *([REAL_ORDER_FILLED] * n), *ids)
    )
    assert (
        len(scan.entry_lines) == len(scan.fills) == len(scan.instance_ids) == nl.MAX_STORED_REPORTS
    )
    assert scan.entry_total == scan.fill_total == scan.instance_id_total == n


def test_timestamped_disposed_line_that_fails_the_grammar_is_counted(tmp_path: Path) -> None:
    malformed = "2026-10-02T20:55:21.494523448Z TradingNode DISPOSED"  # CONSTRUCTED: no level
    untimestamped = "state DISPOSED"
    scan = nl.scan_node_log(write_log(tmp_path / "n.log", malformed, untimestamped))
    assert scan.unparseable_total == 1 and scan.unparseable[0].marker == "DISPOSED"
    assert scan.node_disposed is False


# ------------------------------------------------------------------------------------------
# WP5-R4: duplicates and keep_kinds
# ------------------------------------------------------------------------------------------


def same_tick_twin(line: str) -> str:
    """The same decision text logged again 104 us later (the older-build duplicate)."""
    return line.replace("20:05:32.018121135", "20:05:32.018225178")


def test_byte_identical_decision_repeats_are_counted_and_deduped(tmp_path: Path) -> None:
    other = REAL_REFUSE.replace("'lt_63'", "'lt_64'")
    path = write_log(tmp_path / "n.log", REAL_REFUSE, same_tick_twin(REAL_REFUSE), other, REAL_TAKE)
    scan = nl.scan_node_log(path)
    assert scan.decision_line_count == 4 and scan.evaluation_count == 4
    assert scan.duplicate_decision_count == 1
    assert scan.evaluation_count_deduped == 3
    kept = list(
        nl.dedupe_decisions(e for e in nl.iter_node_log(path) if isinstance(e, nl.DecisionLine))
    )
    assert [k.rung_id for k in kept] == ["lt_63", "lt_64", "93_94"]


def test_same_text_on_a_later_tick_is_not_a_duplicate(tmp_path: Path) -> None:
    later = REAL_REFUSE.replace("1790971531951257557", "1790971531951257558")
    scan = nl.scan_node_log(write_log(tmp_path / "n.log", REAL_REFUSE, later, REAL_REFUSE))
    assert scan.duplicate_decision_count == 0


def test_decision_digest_is_stable_and_ignores_the_log_prefix(tmp_path: Path) -> None:
    a, b = (
        nl.classify_line(line.encode(), 1) for line in (REAL_REFUSE, same_tick_twin(REAL_REFUSE))
    )
    assert isinstance(a, nl.DecisionLine) and isinstance(b, nl.DecisionLine)
    assert a.digest == b.digest and len(a.digest) == 8
    other = nl.classify_line(REAL_REFUSE.replace("lt_63", "lt_64").encode(), 1)
    assert isinstance(other, nl.DecisionLine) and other.digest != a.digest


def test_keep_kinds_retains_every_requested_decision_kind_in_one_pass(tmp_path: Path) -> None:
    path = write_log(tmp_path / "n.log", REAL_REFUSE, REAL_TAKE, REAL_TRY_SUBMIT)
    default = nl.scan_node_log(path)
    assert [ln.kind for ln in default.entry_lines] == ["Take", "TrySubmit"]
    wide = nl.scan_node_log(path, keep_kinds=frozenset({"Refuse", "Take", "TrySubmit"}))
    assert [ln.kind for ln in wide.entry_lines] == ["Refuse", "Take", "TrySubmit"]
    assert wide.entry_total == 3


# ------------------------------------------------------------------------------------------
# WP5-R4: per-kind spawn windows, nearest stamp, leftover warnings
# ------------------------------------------------------------------------------------------


def test_post_spawn_event_window_is_30s_before_to_5s_after() -> None:
    event = spawn_event("2026-10-03T16:50:45", "launched", pid=1)
    for stamp, ok in (
        ("20261003T165015Z", True),
        ("20261003T165014Z", False),
        ("20261003T165050Z", True),
        ("20261003T165051Z", False),
    ):
        census = nl.match_spawns_to_logs([event], [node_log_path(stamp)])
        assert (census.missing == ()) is ok, stamp


def test_pre_spawn_event_window_starts_at_the_event_and_runs_300s() -> None:
    event = spawn_event("2026-10-03T17:05:00", "relaunching", attempt=1)
    for stamp, ok in (
        ("20261003T170459Z", True),  # one second of tolerance: stamp's ``now`` precedes the line
        ("20261003T170458Z", False),
        ("20261003T171000Z", True),
        ("20261003T171001Z", False),
    ):
        census = nl.match_spawns_to_logs([event], [node_log_path(stamp)])
        assert (census.missing == ()) is ok, stamp


def test_post_spawn_event_does_not_take_a_late_pre_spawn_style_stamp() -> None:
    census = nl.match_spawns_to_logs(
        [spawn_event("2026-10-03T16:50:45", "boot_retry_launched", pid=1)],
        [node_log_path("20261003T165200Z")],
    )
    assert len(census.missing) == 1


def test_nearest_stamp_wins_and_the_other_in_window_log_is_a_warning() -> None:
    far, near = node_log_path("20261003T165030Z"), node_log_path("20261003T165044Z")
    census = nl.match_spawns_to_logs(
        [spawn_event("2026-10-03T16:50:45", "launched", pid=1)], [far, near]
    )
    assert census.matches[0].log_path == near
    assert census.unmatched_logs == (far,)
    assert [(w.name, w.cause) for w in census.warnings] == [
        (far.name, nl.CAUSE_UNMATCHED_LOG_IN_WINDOW)
    ]


def test_leftover_log_outside_every_window_is_not_a_warning() -> None:
    census = nl.match_spawns_to_logs(
        [spawn_event("2026-10-03T16:50:45", "launched", pid=1)],
        [node_log_path("20261003T165045Z"), node_log_path("20261003T200526Z")],
    )
    assert census.warnings == () and len(census.unmatched_logs) == 1


def test_events_with_equal_time_are_ordered_by_line_number() -> None:
    first = nl.SpawnEvent(
        line_no=2, ts=spawn_event("2026-10-03T16:50:45", "launched").ts, event="launched", pid=2
    )
    second = nl.SpawnEvent(line_no=1, ts=first.ts, event="launched", pid=1)
    census = nl.match_spawns_to_logs([first, second], [node_log_path("20261003T165045Z")])
    assert [m.event.line_no for m in census.matches] == [1, 2]
    assert census.matches[0].log_path is not None and census.matches[1].log_path is None


# ------------------------------------------------------------------------------------------
# WP5-R4: exports, no assert, module sizes
# ------------------------------------------------------------------------------------------

_NODE_LOG_MODULES: Final[tuple[str, ...]] = (
    "capture_node_log",
    "capture_node_log_io",
    "capture_node_log_decisions",
    "capture_node_log_spawns",
)


def _module_path(name: str) -> Path:
    return Path(nl.__file__).with_name(f"{name}.py")


@pytest.mark.parametrize("name", _NODE_LOG_MODULES)
def test_node_log_modules_are_at_most_800_lines_and_use_no_assert(name: str) -> None:
    path = _module_path(name)
    text = path.read_text(encoding="utf-8")
    assert len(text.splitlines()) <= 800
    assert not any(isinstance(n, ast.Assert) for n in ast.walk(ast.parse(text)))


def test_facade_exports_every_public_name_it_documents() -> None:
    for name in (
        "InstanceIdLine",
        "KIND_TAKE",
        "KIND_TRY_SUBMIT",
        "EVALUATION_KINDS",
        "CAUSE_BAD_FIELDS",
        "CAUSE_NO_MATCH",
        "CAUSE_UNDECODABLE",
        "CAUSE_UNKNOWN_KIND",
        "CAUSE_INVALID_LOG_NAME",
        "CAUSE_UNMATCHED_LOG_IN_WINDOW",
        "LogFinding",
        "NodeLogListing",
        "dedupe_decisions",
    ):
        assert name in nl.__all__, name
        assert hasattr(nl, name), name
    assert all(hasattr(nl, n) for n in nl.__all__)
