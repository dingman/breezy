"""AUT-1 WP5-C: the streaming node-log parser (plan r12 section 3.11, r8 WP5, build ruling WP0-R7).

Fixtures are REAL retained lines from ``~/.local/share/breezy/logs/`` unless the constant says
CONSTRUCTED. The supervisor and Nautilus-logger lines are produced by the real formatters.
"""

import ast
import datetime as dt
import logging
import tracemalloc
from collections.abc import Iterator
from pathlib import Path
from typing import Final

import pytest

from breezy.analysis import capture_node_log as nl

_ANSI_ON: Final[str] = "\x1b[1m"
_ANSI_OFF: Final[str] = "\x1b[0m"

# --- REAL lines: breezy-trade-20261002T200526Z.log (ANSI as written by Nautilus) ---------------
REAL_TAKE: Final[str] = (
    f"{_ANSI_ON}2026-10-02T20:20:32.924873907Z{_ANSI_OFF} [INFO] "
    "BREEZY-L001.FORECAST-QUANTILE-LADDER: SHADOW_DECISION {'now_ns': 1790972432790092624, "
    "'station': 'LAX', 'climate_day': datetime.date(2026, 10, 3), 'rung_id': '93_94', "
    "'side': 'yes', 'instrument_id': 'tc-temp-laxhigh-2026-10-03-gte93lt94f.POLYMARKET_US', "
    "'kind': 'Take', 'qty': 1, 'ev_net': 0.06568776856525851, 'p_hat': 0.2538513678202191, "
    f"'p_lower': 0.2345490185652585, 'p_upper': 0.27614249327505075}}{_ANSI_OFF}"
)
REAL_TRY_SUBMIT: Final[str] = (
    f"{_ANSI_ON}2026-10-02T20:20:32.924972237Z{_ANSI_OFF} [INFO] "
    "BREEZY-L001.FORECAST-QUANTILE-LADDER: SHADOW_DECISION {'now_ns': 1790972432924965987, "
    "'station': 'LAX', 'climate_day': datetime.date(2026, 10, 3), 'rung_id': '93_94', "
    "'side': 'yes', 'instrument_id': 'tc-temp-laxhigh-2026-10-03-gte93lt94f.POLYMARKET_US', "
    f"'kind': 'TrySubmit', 'reason': 'submitted'}}{_ANSI_OFF}"
)
REAL_REFUSE: Final[str] = (
    f"{_ANSI_ON}2026-10-02T20:05:32.018121135Z{_ANSI_OFF} [INFO] "
    "BREEZY-L001.FORECAST-QUANTILE-LADDER: SHADOW_DECISION {'now_ns': 1790971531951257557, "
    "'station': 'MDW', 'climate_day': datetime.date(2026, 10, 3), 'rung_id': 'lt_63', "
    "'side': 'yes', 'instrument_id': 'tc-temp-mdwhigh-2026-10-03-lt64f.POLYMARKET_US', "
    f"'kind': 'Refuse', 'reason': 'forecast_unavailable'}}{_ANSI_OFF}"
)
REAL_ORDER_FILLED: Final[str] = (
    f"{_ANSI_ON}2026-10-02T20:20:33.123853693Z{_ANSI_OFF} [INFO] "
    "BREEZY-L001.FORECAST-QUANTILE-LADDER: <--[EVT] OrderFilled("
    "instrument_id=tc-temp-laxhigh-2026-10-03-gte93lt94f.POLYMARKET_US, "
    "client_order_id=O-20261002-202032-L001-LAX-1, venue_order_id=CVW455HKJYGE, "
    "account_id=POLYMARKET_US-MAIN, trade_id=CVWEANWH8YHR, "
    "position_id=tc-temp-laxhigh-2026-10-03-gte93lt94f.POLYMARKET_US-FORECAST-QUANTILE-LADDER-LAX, "
    "order_side=BUY, order_type=LIMIT, last_qty=1.00, last_px=0.15 USD, commission=0.01 USD, "
    f"liquidity_side=TAKER, ts_event=1790972433034078620){_ANSI_OFF}"
)
REAL_INSTANCE_ID: Final[str] = (
    f"{_ANSI_ON}2026-10-02T20:05:30.434292449Z{_ANSI_OFF} [INFO] "
    f"BREEZY-L001.TradingNode: instance_id: 01cea9fc-cf7d-4efa-b132-cbbaf5d0bde4{_ANSI_OFF}"
)
# The ANSI-stripped disposal lines of the same log (lines 70915 and 70928).
REAL_DISPOSED_STRATEGY: Final[str] = (
    "2026-10-02T20:55:21.478676119Z [INFO] BREEZY-L001.FORECAST-QUANTILE-LADDER: DISPOSED"
)
REAL_DISPOSED_NODE: Final[str] = (
    "2026-10-02T20:55:21.494523448Z [INFO] BREEZY-L001.TradingNode: DISPOSED"
)
REAL_PLAIN_LINE: Final[str] = (
    "2026-10-02T20:55:21.494375108Z [INFO] BREEZY-L001.MessageBus: Closed message bus"
)

# --- REAL supervisor lines (breezy-trade-supervisor.log) ----------------------------------------
REAL_SUP_LAUNCHED: Final[str] = (
    "2026-10-03T16:50:45Z INFO breezy.runtime.trade_supervisor launched pid=529436"
)
REAL_SUP_RELAUNCHING: Final[str] = (
    "2026-09-18T16:51:20Z INFO breezy.runtime.trade_supervisor relaunching attempt=1"
)

_NS: Final[int] = 1_000_000_000


def _write(path: Path, *lines: str, tail: str = "\n") -> Path:
    path.write_bytes(("\n".join(lines) + tail).encode("utf-8"))
    return path


def _events(path: Path) -> list[object]:
    return list(nl.iter_node_log(path))


# ------------------------------------------------------------------------------------------
# (a) decision lines
# ------------------------------------------------------------------------------------------


def test_parses_shadow_decision_take_and_trysubmit_lines_with_date_repr(tmp_path: Path) -> None:
    path = _write(tmp_path / "n.log", REAL_TAKE, REAL_TRY_SUBMIT, REAL_REFUSE)
    take, try_submit, refuse = _events(path)
    assert isinstance(take, nl.DecisionLine) and take.kind == "Take"
    assert take.climate_day == dt.date(2026, 10, 3)
    assert take.now_ns == 1790972432790092624
    assert (take.station, take.rung_id, take.side) == ("LAX", "93_94", "yes")
    assert take.instrument_id == "tc-temp-laxhigh-2026-10-03-gte93lt94f.POLYMARKET_US"
    assert take.take is not None and take.take.qty == 1
    assert take.take.ev_net == pytest.approx(0.06568776856525851)
    assert take.reason is None and take.line_no == 1
    assert (
        take.log_ts_ns
        == int(dt.datetime(2026, 10, 2, 20, 20, 32, tzinfo=dt.UTC).timestamp()) * _NS + 924873907
    )
    assert isinstance(try_submit, nl.DecisionLine) and try_submit.kind == "TrySubmit"
    assert try_submit.reason == "submitted" and try_submit.take is None
    assert isinstance(refuse, nl.DecisionLine) and refuse.reason == "forecast_unavailable"


def test_decision_line_parses_without_ansi_too(tmp_path: Path) -> None:
    plain = REAL_REFUSE.replace(_ANSI_ON, "").replace(_ANSI_OFF, "")
    (event,) = _events(_write(tmp_path / "n.log", plain))
    assert isinstance(event, nl.DecisionLine) and event.kind == "Refuse"


def test_each_decision_kind_is_classified_by_kind(tmp_path: Path) -> None:
    lines = [
        REAL_REFUSE.replace("'Refuse'", f"'{kind}'")
        for kind in ("NotExecutable", "NotDPlus1", "Refuse")
    ]
    scan = nl.scan_node_log(_write(tmp_path / "n.log", *lines, REAL_TAKE, REAL_TRY_SUBMIT))
    assert dict(scan.kind_counts) == {
        "NotExecutable": 1,
        "NotDPlus1": 1,
        "Refuse": 1,
        "Take": 1,
        "TrySubmit": 1,
    }
    assert scan.decision_line_count == 5


def test_evaluation_count_is_total_minus_trysubmit(tmp_path: Path) -> None:
    """WP0-R7 R3: a Take adds one TrySubmit line, so evaluations = total - TrySubmit."""
    scan = nl.scan_node_log(
        _write(tmp_path / "n.log", REAL_REFUSE, REAL_REFUSE, REAL_TAKE, REAL_TRY_SUBMIT)
    )
    assert scan.decision_line_count == 4
    assert scan.evaluation_count == 3


def test_evaluation_count_when_shadow_only_has_no_trysubmit(tmp_path: Path) -> None:
    scan = nl.scan_node_log(_write(tmp_path / "n.log", REAL_REFUSE, REAL_TAKE))
    assert scan.evaluation_count == scan.decision_line_count == 2


def _decision(kind: str, *, now_ns: int, rung: str = "93_94", side: str = "yes") -> nl.DecisionLine:
    return nl.DecisionLine(
        line_no=1,
        log_ts_ns=now_ns,
        component="C",
        now_ns=now_ns,
        station="LAX",
        climate_day=dt.date(2026, 10, 3),
        rung_id=rung,
        side=side,
        instrument_id="i",
        kind=kind,
        reason=None if kind == "Take" else "submitted",
        take=(
            nl.TakeInputs(qty=1, ev_net=0.1, p_hat=0.2, p_lower=0.1, p_upper=0.3)
            if kind == "Take"
            else None
        ),
    )


def test_take_trysubmit_pairing_on_instrument_rung_side() -> None:
    a_take = _decision("Take", now_ns=10)
    b_take = _decision("Take", now_ns=11, side="no")
    b_sub = _decision("TrySubmit", now_ns=12, side="no")
    a_sub = _decision("TrySubmit", now_ns=13)
    pairing = nl.pair_take_trysubmit([a_take, b_take, b_sub, a_sub])
    assert pairing.pairs == ((b_take, b_sub), (a_take, a_sub))
    assert pairing.unpaired_takes == () and pairing.unpaired_try_submits == ()


def test_shadow_only_takes_are_unpaired_takes_and_orphan_trysubmit_is_reported() -> None:
    lone_take = _decision("Take", now_ns=10)
    orphan = _decision("TrySubmit", now_ns=20, rung="other")
    pairing = nl.pair_take_trysubmit([lone_take, orphan])
    assert pairing.pairs == ()
    assert pairing.unpaired_takes == (lone_take,)
    assert pairing.unpaired_try_submits == (orphan,)


def test_trysubmit_older_than_its_take_is_not_paired() -> None:
    take = _decision("Take", now_ns=50)
    stale = _decision("TrySubmit", now_ns=40)
    pairing = nl.pair_take_trysubmit([take, stale])
    assert pairing.pairs == () and pairing.unpaired_try_submits == (stale,)


def test_a_second_take_on_one_key_orphans_the_first() -> None:
    first = _decision("Take", now_ns=10)
    second = _decision("Take", now_ns=20)
    sub = _decision("TrySubmit", now_ns=30)
    pairing = nl.pair_take_trysubmit([first, second, sub])
    assert pairing.pairs == ((second, sub),)
    assert pairing.unpaired_takes == (first,)


def test_trysubmit_is_dropped_before_the_replay_filter() -> None:
    lines = [
        _decision("Refuse", now_ns=1),
        _decision("Take", now_ns=2),
        _decision("TrySubmit", now_ns=3),
    ]
    kept = list(nl.drop_try_submits(iter(lines)))
    assert [line.kind for line in kept] == ["Refuse", "Take"]
    assert all(not nl.is_try_submit(line) for line in kept)


@pytest.mark.parametrize(
    ("mutate", "cause"),
    [
        (lambda s: s.replace("'kind': 'Take'", "'kind': 'Mystery'"), "unknown_kind"),
        (lambda s: s.replace("datetime.date(2026, 10, 3)", "datetime.date(2026, 13, 3)"), None),
        (lambda s: s.replace("'now_ns': 1790972432790092624", "'now_ns': 'x'"), None),
        (lambda s: s.replace("'qty': 1, ", ""), None),
        (lambda s: s.replace("'side': 'yes'", "'side': 'maybe'"), None),
        (lambda s: s[: s.index("'p_lower'")], None),
        (lambda s: s.replace("{'now_ns'", "{'now_ns'", 1).replace("'station'", "'stn'", 1), None),
    ],
)
def test_malformed_shadow_decision_line_is_reported_never_skipped(
    tmp_path: Path, mutate: object, cause: str | None
) -> None:
    bad = mutate(REAL_TAKE)  # type: ignore[operator]
    scan = nl.scan_node_log(_write(tmp_path / "n.log", REAL_REFUSE, bad, REAL_REFUSE))
    assert scan.unparseable_total == 1
    (report,) = scan.unparseable
    assert report.marker == "SHADOW_DECISION" and report.line_no == 2
    assert cause is None or report.cause == cause
    assert scan.decision_line_count == 2  # the good neighbours still count


# ------------------------------------------------------------------------------------------
# other node-log lines: instance_id, OrderFilled, disposal
# ------------------------------------------------------------------------------------------


def test_reads_instance_id_line(tmp_path: Path) -> None:
    scan = nl.scan_node_log(_write(tmp_path / "n.log", REAL_PLAIN_LINE, REAL_INSTANCE_ID))
    assert scan.instance_ids == ("01cea9fc-cf7d-4efa-b132-cbbaf5d0bde4",)


def test_parses_orderfilled_client_and_venue_ids(tmp_path: Path) -> None:
    (fill,) = _events(_write(tmp_path / "n.log", REAL_ORDER_FILLED))
    assert isinstance(fill, nl.OrderFilledLine)
    assert fill.client_order_id == "O-20261002-202032-L001-LAX-1"
    assert fill.venue_order_id == "CVW455HKJYGE"
    assert fill.trade_id == "CVWEANWH8YHR"
    assert fill.ts_event == 1790972433034078620
    assert fill.instrument_id.endswith("gte93lt94f.POLYMARKET_US")


def test_malformed_orderfilled_line_is_reported(tmp_path: Path) -> None:
    bad = REAL_ORDER_FILLED.replace("venue_order_id=CVW455HKJYGE, ", "")
    scan = nl.scan_node_log(_write(tmp_path / "n.log", bad))
    assert scan.unparseable_total == 1 and scan.fills == ()
    assert scan.unparseable[0].marker == "OrderFilled"


def test_disposal_line_text_matches_the_recorded_line() -> None:
    """The disposal text is ``<component>: DISPOSED`` at INFO, as retained at line 70915."""
    event = nl.classify_line(REAL_DISPOSED_STRATEGY.encode(), 70915)
    assert isinstance(event, nl.DisposedLine)
    assert event.component == "BREEZY-L001.FORECAST-QUANTILE-LADDER"
    assert not event.is_trading_node
    assert nl.DISPOSED_TEXT == "DISPOSED"


def test_boot_is_disposed_only_by_the_trading_node_disposal_line(tmp_path: Path) -> None:
    components_only = nl.scan_node_log(_write(tmp_path / "a.log", REAL_DISPOSED_STRATEGY))
    assert components_only.node_disposed is False and components_only.disposed_count == 1
    ended = nl.scan_node_log(_write(tmp_path / "b.log", REAL_DISPOSED_STRATEGY, REAL_DISPOSED_NODE))
    assert ended.node_disposed is True and ended.disposed_count == 2


def test_disposing_transient_state_is_not_a_disposal_line() -> None:
    line = REAL_DISPOSED_NODE.replace("DISPOSED", "DISPOSING")
    assert nl.classify_line(line.encode(), 1) is None


def test_scan_reports_last_log_line_timestamp(tmp_path: Path) -> None:
    scan = nl.scan_node_log(_write(tmp_path / "n.log", REAL_INSTANCE_ID, REAL_DISPOSED_NODE))
    expected = int(dt.datetime(2026, 10, 2, 20, 55, 21, tzinfo=dt.UTC).timestamp()) * _NS
    assert scan.last_line_ts_ns == expected + 494523448
    assert scan.line_count == 2


# ------------------------------------------------------------------------------------------
# (c) writer failure markers, driven through the real Nautilus logger
# ------------------------------------------------------------------------------------------


def test_failed_to_serialize_log_line_fails_r4(tmp_path: Path) -> None:
    """The text is Nautilus's own (``persistence/writer.py:286``, ``:244``) and capture's
    ``CAPTURE_PUBLISH_FAILED``; the lines are emitted by the real Nautilus ``Logger``."""
    from nautilus_trader.common.component import Logger

    from tests.support.nautilus_log_capture import capture_nautilus_logs

    read = capture_nautilus_logs()
    log = Logger("BREEZY-TEST-WRITER")
    log.error("Failed to serialize cls=<class 'nautilus_trader.model.events.order.OrderFilled'>")
    log.error("ERROR = `boom`")
    log.warning(
        "Can't find writer for cls: <class 'nautilus_trader.model.events.order.OrderDenied'>"
    )
    log.error("CAPTURE_PUBLISH_FAILED family=fq type=DecisionRecord cause=OSError")
    log.info("CAPTURE_PUBLISH_FAILED_SUPPRESSED family=fq cause=OSError count=3 window_s=300")
    log.info("an unrelated line")
    lines = [ln for ln in read() if "BREEZY-TEST-WRITER" in ln]
    scan = nl.scan_node_log(_write(tmp_path / "n.log", *lines))
    assert [f.marker for f in scan.writer_failures] == [
        nl.MARKER_FAILED_TO_SERIALIZE,
        nl.MARKER_MISSING_WRITER,
        nl.MARKER_CAPTURE_PUBLISH_FAILED,
        nl.MARKER_CAPTURE_PUBLISH_FAILED,
    ]
    assert scan.writer_failure_total == 4 and scan.has_writer_failure
    assert scan.unparseable_total == 0


def test_log_without_failure_markers_has_none(tmp_path: Path) -> None:
    scan = nl.scan_node_log(_write(tmp_path / "n.log", REAL_PLAIN_LINE, REAL_REFUSE))
    assert not scan.has_writer_failure and scan.writer_failures == ()


def test_writer_failure_storm_is_counted_exactly_but_stored_bounded(tmp_path: Path) -> None:
    line = "2026-10-02T20:00:00.000000001Z [ERROR] BREEZY-L001.W: Failed to serialize cls=<c>"
    n = nl.MAX_STORED_REPORTS + 50
    scan = nl.scan_node_log(_write(tmp_path / "n.log", *([line] * n)))
    assert scan.writer_failure_total == n
    assert len(scan.writer_failures) == nl.MAX_STORED_REPORTS
    assert scan.has_writer_failure


# ------------------------------------------------------------------------------------------
# (d) failure handling
# ------------------------------------------------------------------------------------------


def test_unparseable_marker_line_is_counted_never_skipped_silently(tmp_path: Path) -> None:
    torn_mid = REAL_TAKE[:90] + REAL_REFUSE  # CONSTRUCTED: two writes interleaved
    garbage = "2026-10-02T20:00:00.000000000Z [INFO] X: SHADOW_DECISION {not a dict"  # CONSTRUCTED
    inst = "2026-10-02T20:00:00.000000000Z [INFO] X.TradingNode: instance_id: "  # CONSTRUCTED
    scan = nl.scan_node_log(_write(tmp_path / "n.log", torn_mid, garbage, inst, REAL_REFUSE))
    assert scan.unparseable_total == 3
    assert [u.line_no for u in scan.unparseable] == [1, 2, 3]
    assert scan.decision_line_count == 1


def test_undecodable_marker_line_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "n.log"
    path.write_bytes(REAL_REFUSE.encode()[:60] + b"\xff\xfe SHADOW_DECISION {\n")
    scan = nl.scan_node_log(path)
    assert scan.unparseable_total == 1 and scan.unparseable[0].cause == "undecodable"


def test_stream_torn_tail_after_boot_end_is_counted(tmp_path: Path) -> None:
    """An unterminated last line is ``torn_tail``, even after the disposal line."""
    path = tmp_path / "n.log"
    path.write_bytes(
        (REAL_DISPOSED_NODE + "\n").encode() + REAL_REFUSE.encode()[:50]
    )  # CONSTRUCTED torn tail
    scan = nl.scan_node_log(path)
    assert scan.node_disposed is True
    assert scan.unparseable_total == 1
    assert scan.unparseable[0].cause == nl.CAUSE_TORN_TAIL and scan.unparseable[0].line_no == 2


def test_complete_but_unterminated_last_line_is_still_torn_tail(tmp_path: Path) -> None:
    scan = nl.scan_node_log(_write(tmp_path / "n.log", REAL_REFUSE, tail=""))
    assert scan.unparseable_total == 1 and scan.decision_line_count == 0
    assert scan.unparseable[0].cause == nl.CAUSE_TORN_TAIL


def test_empty_file_is_a_clean_empty_scan(tmp_path: Path) -> None:
    path = tmp_path / "n.log"
    path.write_bytes(b"")
    scan = nl.scan_node_log(path)
    assert scan.line_count == 0 and scan.unparseable_total == 0


def test_overlong_marker_line_is_reported_and_reading_continues(tmp_path: Path) -> None:
    path = tmp_path / "n.log"
    huge = REAL_REFUSE.replace("'forecast_unavailable'", "'" + "x" * (nl.MAX_LINE_BYTES + 10) + "'")
    path.write_bytes((huge + "\n" + REAL_REFUSE + "\n").encode())
    scan = nl.scan_node_log(path)
    assert scan.unparseable_total == 1 and scan.unparseable[0].cause == nl.CAUSE_LINE_TOO_LONG
    assert scan.decision_line_count == 1 and scan.line_count == 2


def test_unreadable_node_log_is_error(tmp_path: Path) -> None:
    with pytest.raises(nl.NodeLogUnreadable):
        nl.scan_node_log(tmp_path / "absent.log")
    with pytest.raises(nl.NodeLogUnreadable):
        nl.scan_node_log(tmp_path)  # a directory
    locked = _write(tmp_path / "locked.log", REAL_REFUSE)
    locked.chmod(0)
    try:
        with pytest.raises(nl.NodeLogUnreadable):
            list(nl.iter_node_log(locked))
    finally:
        locked.chmod(0o600)


def test_unreadable_error_never_carries_an_absolute_path_in_its_cause(tmp_path: Path) -> None:
    with pytest.raises(nl.NodeLogUnreadable) as info:
        nl.scan_node_log(tmp_path / "absent.log")
    assert str(tmp_path) not in info.value.cause
    assert info.value.cause == "FileNotFoundError"


def test_streaming_parser_memory_is_o_matches(tmp_path: Path) -> None:
    """60k decision lines (~20 MB) scan in a few MB: only entry/fill/boot lines are kept."""
    path = tmp_path / "big.log"
    with path.open("wb") as fh:
        fh.write((REAL_INSTANCE_ID + "\n").encode())
        for i in range(60_000):
            fh.write(
                (
                    REAL_REFUSE.replace("1790971531951257557", str(1790971531951257557 + i)) + "\n"
                ).encode()
            )
            if i % 20_000 == 0:
                fh.write((REAL_TAKE + "\n" + REAL_TRY_SUBMIT + "\n").encode())
    assert path.stat().st_size > 20_000_000
    tracemalloc.start()
    try:
        scan = nl.scan_node_log(path)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert scan.decision_line_count == 60_000 + 6
    assert scan.evaluation_count == 60_000 + 3
    assert len(scan.entry_lines) == 6
    assert peak < 4_000_000, peak


# ------------------------------------------------------------------------------------------
# (b) supervisor spawn events: real formatter, AST pin, 1:1 matching
# ------------------------------------------------------------------------------------------


@pytest.fixture
def supervisor_logger_restored() -> Iterator[logging.Logger]:
    from breezy.runtime import trade_supervisor

    log = trade_supervisor.logger
    saved = (list(log.handlers), log.level, log.propagate)
    yield log
    for handler in list(log.handlers):
        if handler not in saved[0]:
            handler.close()
            log.removeHandler(handler)
    log.handlers[:] = saved[0]
    log.setLevel(saved[1])
    log.propagate = saved[2]


def test_supervisor_launched_pid_line_matches_trade_supervisor_1300(
    tmp_path: Path, supervisor_logger_restored: logging.Logger
) -> None:
    """WP0-R7 (a): all FOUR spawn events, rendered by the real ``log_decision`` through the
    supervisor's own formatter, are recognised; ``launch_spawn_failed`` is a no-spawn event."""
    from breezy.runtime import trade_supervisor

    trade_supervisor.configure_supervisor_logging(tmp_path)
    trade_supervisor.log_decision("launched", pid=529436)
    trade_supervisor.log_decision("boot_retry_launched", pid=7)
    trade_supervisor.log_decision("relaunching", attempt=2)
    trade_supervisor.log_decision("midday_relaunching", phase="midday_watch", attempt=3)
    trade_supervisor.log_decision("launch_spawn_failed", error_type="OSError")
    trade_supervisor.log_decision("relaunch_declined", reason="budget")
    for handler in supervisor_logger_restored.handlers:
        handler.flush()
    path = trade_supervisor.supervisor_log_path(tmp_path)
    scan = nl.scan_supervisor_log(path)
    assert [(e.event, e.pid, e.attempt) for e in scan.spawns] == [
        ("launched", 529436, None),
        ("boot_retry_launched", 7, None),
        ("relaunching", None, 2),
        ("midday_relaunching", None, 3),
    ]
    assert scan.spawns[3].phase == "midday_watch"
    assert scan.no_spawn_count == 1 and scan.unparseable_total == 0
    assert tuple(e.event for e in scan.spawns) == nl.SPAWN_EVENTS
    assert nl.NO_SPAWN_EVENTS == ("launch_spawn_failed",)
    # The recorded journal text parses to the same shape.
    (recorded,) = nl.parse_supervisor_lines([REAL_SUP_LAUNCHED]).spawns
    assert (recorded.event, recorded.pid) == ("launched", 529436)
    (relaunch,) = nl.parse_supervisor_lines([REAL_SUP_RELAUNCHING]).spawns
    assert (relaunch.event, relaunch.attempt) == ("relaunching", 1)


def test_trade_supervisor_has_exactly_four_spawn_calls_each_paired_with_its_event() -> None:
    """AST pin (WP0-R7): exactly four ``ports.spawn(`` calls, each in a function logging its event;
    ``launched`` and ``boot_retry_launched`` after the spawn, ``relaunching`` and
    ``midday_relaunching`` before it."""
    from breezy.runtime import trade_supervisor

    tree = ast.parse(Path(trade_supervisor.__file__).read_text(encoding="utf-8"))
    spawn_calls: list[tuple[str, int]] = []
    paired: dict[str, list[tuple[str, int]]] = {}
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call)]
        spawns = [
            c.lineno
            for c in calls
            if isinstance(c.func, ast.Attribute)
            and c.func.attr == "spawn"
            and isinstance(c.func.value, ast.Name)
            and c.func.value.id == "ports"
        ]
        spawn_calls += [(fn.name, ln) for ln in spawns]
        if spawns:
            paired[fn.name] = sorted(
                (c.args[0].value, c.lineno)
                for c in calls
                if isinstance(c.func, ast.Name)
                and c.func.id == "log_decision"
                and c.args
                and isinstance(c.args[0], ast.Constant)
                and c.args[0].value in nl.SPAWN_EVENTS
            ) + [("spawn", ln) for ln in spawns]
    assert len(spawn_calls) == 4, spawn_calls
    order = {
        name: [label for label, _ in sorted(items, key=lambda it: it[1])]
        for name, items in paired.items()
    }
    assert order == {
        "_do_launch": ["spawn", "launched"],
        "_do_relaunch_check": ["relaunching", "spawn"],
        "_launch_boot_retry_child": ["spawn", "boot_retry_launched"],
        "_do_midday_watch": ["midday_relaunching", "spawn"],
    }
    assert set(nl.SPAWN_EVENTS) == {
        "launched",
        "boot_retry_launched",
        "relaunching",
        "midday_relaunching",
    }


def _ev(ts: str, event: str, **kw: int) -> nl.SpawnEvent:
    when = dt.datetime.fromisoformat(ts).replace(tzinfo=dt.UTC)
    return nl.SpawnEvent(
        line_no=1, ts=when, event=event, pid=kw.get("pid"), attempt=kw.get("attempt")
    )


def _log(name: str) -> Path:
    return Path("/logs") / f"breezy-trade-{name}.log"


def test_spawn_events_match_logs_one_to_one_in_time_order() -> None:
    events = [
        _ev("2026-10-03T16:50:45", "launched", pid=11),
        _ev("2026-10-03T17:05:00", "relaunching", attempt=1),
        _ev("2026-10-03T19:00:10", "boot_retry_launched", pid=12),
    ]
    logs = [_log("20261003T165045Z"), _log("20261003T170500Z"), _log("20261003T190009Z")]
    census = nl.match_spawns_to_logs(events, logs)
    assert [m.log_path for m in census.matches] == logs
    assert census.missing == () and census.unmatched_logs == ()


def test_pid_is_never_the_join_key() -> None:
    """Two spawns with the SAME pid still take two different logs (pid reuse, ruling WP0-R7)."""
    events = [
        _ev("2026-10-03T16:50:45", "launched", pid=5),
        _ev("2026-10-03T17:05:00", "boot_retry_launched", pid=5),
    ]
    census = nl.match_spawns_to_logs(events, [_log("20261003T165045Z"), _log("20261003T170500Z")])
    assert [m.log_path for m in census.matches] == [
        _log("20261003T165045Z"),
        _log("20261003T170500Z"),
    ]


def test_spawn_without_log_is_error_node_log_missing() -> None:
    events = [
        _ev("2026-10-03T16:50:45", "launched", pid=1),
        _ev("2026-10-04T16:50:45", "launched", pid=2),
    ]
    census = nl.match_spawns_to_logs(events, [_log("20261003T165045Z")])
    assert [m.event.pid for m in census.missing] == [2]
    assert census.missing[0].cause == nl.CAUSE_NODE_LOG_MISSING
    assert census.matches[1].log_path is None


def test_one_log_cannot_satisfy_two_events() -> None:
    events = [
        _ev("2026-10-03T16:50:45", "launched", pid=1),
        _ev("2026-10-03T16:50:50", "relaunching", attempt=1),
    ]
    census = nl.match_spawns_to_logs(events, [_log("20261003T165045Z")])
    assert [m.event.event for m in census.missing] == ["relaunching"]


def test_hand_launched_log_without_an_event_is_unmatched_not_an_error() -> None:
    events = [_ev("2026-10-03T16:50:45", "launched", pid=1)]
    hand = _log("20261003T200526Z")
    census = nl.match_spawns_to_logs(events, [_log("20261003T165045Z"), hand])
    assert census.missing == () and census.unmatched_logs == (hand,)


def test_event_far_from_any_later_log_does_not_take_a_distant_next_day_log() -> None:
    events = [_ev("2026-10-03T16:50:45", "launched", pid=1)]
    census = nl.match_spawns_to_logs(events, [_log("20261004T165045Z")])
    assert [m.event.pid for m in census.missing] == [1]
    assert census.unmatched_logs == (_log("20261004T165045Z"),)


def test_pre_spawn_event_matches_the_log_stamped_a_moment_later() -> None:
    events = [_ev("2026-09-18T16:51:20", "relaunching", attempt=1)]
    census = nl.match_spawns_to_logs(events, [_log("20260918T165121Z")])
    assert census.missing == ()


def test_unsorted_inputs_are_matched_in_time_order() -> None:
    later = _ev("2026-10-03T19:00:00", "boot_retry_launched", pid=2)
    earlier = _ev("2026-10-03T16:50:45", "launched", pid=1)
    census = nl.match_spawns_to_logs(
        [later, earlier], [_log("20261003T190000Z"), _log("20261003T165045Z")]
    )
    assert [(m.event.pid, m.log_path) for m in census.matches] == [
        (1, _log("20261003T165045Z")),
        (2, _log("20261003T190000Z")),
    ]


def test_list_node_logs_ignores_supervisor_logs_and_sorts_by_stamp(tmp_path: Path) -> None:
    for name in (
        "breezy-trade-20261003T165045Z.log",
        "breezy-trade-20261001T165011Z.log",
        "breezy-trade-supervisor.log",
        "breezy-trade-supervisor-stdout-20260905T004018Z.log",
        "breezy-trade-supervisor.launch-2026-09-07.log",
        "quote_tape_20260901.log",
    ):
        (tmp_path / name).write_text("x")
    assert [p.name for p in nl.list_node_logs(tmp_path)] == [
        "breezy-trade-20261001T165011Z.log",
        "breezy-trade-20261003T165045Z.log",
    ]


def test_boot_count_matches_by_instance_id_not_time_window(tmp_path: Path) -> None:
    """WP0-R5: two starts 41.2 s apart are two boots; a repeated instance_id line is one boot."""
    first = nl.scan_node_log(
        _write(tmp_path / "a.log", REAL_INSTANCE_ID, REAL_INSTANCE_ID, REAL_REFUSE)
    )
    second_line = REAL_INSTANCE_ID.replace("01cea9fc", "02cea9fc").replace(
        "20:05:30.434292449", "20:06:11.634292449"
    )
    second = nl.scan_node_log(_write(tmp_path / "b.log", second_line))
    assert nl.distinct_boot_ids([first, second]) == (
        "01cea9fc-cf7d-4efa-b132-cbbaf5d0bde4",
        "02cea9fc-cf7d-4efa-b132-cbbaf5d0bde4",
    )
    assert nl.distinct_boot_ids([first, first]) == ("01cea9fc-cf7d-4efa-b132-cbbaf5d0bde4",)


def test_supervisor_spawn_line_that_does_not_parse_is_reported() -> None:
    scan = nl.parse_supervisor_lines(
        [
            "2026-10-03T16:50:45Z INFO breezy.runtime.trade_supervisor launched pid=notanumber",
            "2026-10-03T16:50:46Z INFO breezy.runtime.trade_supervisor relaunching",
            "2026-10-03T16:50:47Z INFO breezy.runtime.trade_supervisor relaunch_declined reason=x",
            "garbage line",
        ]
    )
    assert scan.spawns == () and scan.unparseable_total == 2


def test_unreadable_supervisor_log_is_error(tmp_path: Path) -> None:
    with pytest.raises(nl.NodeLogUnreadable):
        nl.scan_supervisor_log(tmp_path / "absent.log")
