"""AUT-1 WP5 stage 2a: node-log marker events and online sinks (design S2-R1, S2-R2).

Marker lines are REAL retained lines unless the fixture says CONSTRUCTED or PINNED (see
``tests/support/capture_node_log_fixtures.py``).
"""

import datetime as dt
from pathlib import Path

import pytest

from breezy.analysis import capture_node_log as nl
from breezy.analysis.capture_audit_model import AuditInputError
from tests.support.capture_node_log_fixtures import (
    CONSTRUCTED_CAPTURE_REFUSED,
    CONSTRUCTED_CAPTURE_REFUSED_ALERT_UNDELIVERED,
    CONSTRUCTED_EPOCH_START,
    PINNED_NBP_CYCLE_MISSED,
    PINNED_NBP_CYCLE_MISSED_MESSAGE,
    REAL_FQ_VECTOR_COMPLETE,
    REAL_INSTANCE_ID,
    REAL_NBP_PUBLISHED,
    REAL_ORDER_DENIED,
    REAL_ORDER_SUBMITTED,
    REAL_PLAIN_LINE,
    REAL_TAKE,
    events_of,
    write_log,
)

# -- markers parse into typed events ---------------------------------------------------------------


def test_order_submitted_line_parses_every_field(tmp_path: Path) -> None:
    (event,) = events_of(write_log(tmp_path / "n.log", REAL_ORDER_SUBMITTED))
    assert isinstance(event, nl.OrderSubmittedLine)
    assert event.instrument_id == "tc-temp-laxhigh-2026-10-04-gte93lt94f.POLYMARKET_US"
    assert event.client_order_id == "O-20261003-165052-L001-LAX-1"
    assert event.account_id == "POLYMARKET_US-MAIN"
    assert event.ts_event == 1791046252271779297
    assert event.line_no == 1 and event.log_ts_ns > 0


def test_order_denied_warn_line_with_ansi_before_the_level_parses(tmp_path: Path) -> None:
    """Nautilus colours WARN and ERROR levels, so an ANSI code sits between the timestamp and
    ``[WARN]``; the line grammar must accept it (a real denial line)."""
    (event,) = events_of(write_log(tmp_path / "n.log", REAL_ORDER_DENIED))
    assert isinstance(event, nl.OrderDeniedLine)
    assert event.client_order_id == "O-20261003-165052-L001-LAX-2"
    assert event.instrument_id == "tc-temp-laxhigh-2026-10-04-gte91lt92f.POLYMARKET_US"
    assert (
        event.reason == "'submit intent is already OPEN for this account; wait for it to resolve'"
    )


def test_order_denied_reason_is_capped(tmp_path: Path) -> None:
    long = REAL_ORDER_DENIED.replace("wait for it to resolve", "x" * 5000)
    (event,) = events_of(write_log(tmp_path / "n.log", long))
    assert isinstance(event, nl.OrderDeniedLine)
    assert len(event.reason) <= nl.MAX_MARKER_TEXT_CHARS


def test_capture_refused_line_parses_reason_and_order_ref(tmp_path: Path) -> None:
    (event,) = events_of(write_log(tmp_path / "n.log", CONSTRUCTED_CAPTURE_REFUSED))
    assert isinstance(event, nl.CaptureRefusedLine)
    assert (event.reason, event.order_ref) == ("capture_gap", "O-20261003-165102-L001-LAX-3")


def test_the_alert_undelivered_line_is_not_a_capture_refused_marker(tmp_path: Path) -> None:
    path = write_log(tmp_path / "n.log", CONSTRUCTED_CAPTURE_REFUSED_ALERT_UNDELIVERED)
    assert events_of(path) == []


def test_nbp_published_line_parses(tmp_path: Path) -> None:
    (event,) = events_of(write_log(tmp_path / "n.log", REAL_NBP_PUBLISHED))
    assert isinstance(event, nl.NbpPublishedLine)
    assert (event.cycle_ns, event.stations, event.points) == (1791032400000000000, 4, 28)
    assert event.model_version == "5.0"


def test_fq_vector_complete_line_parses(tmp_path: Path) -> None:
    (event,) = events_of(write_log(tmp_path / "n.log", REAL_FQ_VECTOR_COMPLETE))
    assert isinstance(event, nl.FqVectorCompleteLine)
    assert (event.station, event.cycle_ns) == ("KLAX", 1791032400000000000)
    assert event.climate_day == dt.date(2026, 10, 4) and event.era == "v5.0"


def test_nbp_cycle_missed_pinned_text_parses(tmp_path: Path) -> None:
    (event,) = events_of(write_log(tmp_path / "n.log", PINNED_NBP_CYCLE_MISSED))
    assert isinstance(event, nl.NbpCycleMissedLine)
    assert (event.cycle_ns, event.now_ns) == (1791032400000000000, 1791054000000000000)
    assert event.model == "NBM_NBP" and event.offered is False


def test_nbp_cycle_missed_pinned_message_is_the_wp4_source_literal() -> None:
    assert PINNED_NBP_CYCLE_MISSED_MESSAGE == (
        "NBP_CYCLE_MISSED cycle_ns=1791032400000000000 now_ns=1791054000000000000 "
        "model=NBM_NBP (no alert_offer wired)"
    )


def test_epoch_start_line_parses(tmp_path: Path) -> None:
    (event,) = events_of(write_log(tmp_path / "n.log", CONSTRUCTED_EPOCH_START))
    assert isinstance(event, nl.CaptureEpochStartLine)
    assert (event.family_id, event.epoch_ns) == ("pm_us_crh_fq_v1", 1791046248000000000)


# -- a marker line that does not parse is reported, never dropped (S2-R2) -----------------------

_BROKEN: list[tuple[str, str]] = [
    (
        REAL_ORDER_SUBMITTED.replace("ts_event=1791046252271779297", "ts_event=soon"),
        "OrderSubmitted",
    ),
    (REAL_ORDER_DENIED.replace("client_order_id=", "cid="), "OrderDenied"),
    (CONSTRUCTED_CAPTURE_REFUSED.replace("reason=", "why="), "CAPTURE_REFUSED"),
    (
        REAL_NBP_PUBLISHED.replace("cycle_ns=1791032400000000000", "cycle_ns=abc"),
        "NBM_NBP_PUBLISHED",
    ),
    (REAL_FQ_VECTOR_COMPLETE.replace("2026-10-04", "2026-13-45"), "FQ_VECTOR_COMPLETE"),
    (PINNED_NBP_CYCLE_MISSED.replace("now_ns=1791054000000000000", "now_ns="), "NBP_CYCLE_MISSED"),
    (
        CONSTRUCTED_EPOCH_START.replace("epoch_ns=1791046248000000000", "epoch_ns=-1"),
        "CAPTURE_EPOCH_START",
    ),
]


@pytest.mark.parametrize(("line", "marker"), _BROKEN)
def test_an_unparseable_marker_line_is_reported(line: str, marker: str, tmp_path: Path) -> None:
    (event,) = events_of(write_log(tmp_path / "n.log", line))
    assert isinstance(event, nl.UnparseableLine)
    assert event.marker == marker and event.cause == nl.CAUSE_BAD_FIELDS


@pytest.mark.parametrize(("line", "marker"), _BROKEN)
def test_a_marker_line_without_the_line_grammar_is_reported(
    line: str, marker: str, tmp_path: Path
) -> None:
    torn = "    File x.py: " + line.split(": ", 1)[1]
    (event,) = events_of(write_log(tmp_path / "n.log", torn))
    assert isinstance(event, nl.UnparseableLine)
    assert event.marker == marker and event.cause == nl.CAUSE_NO_MATCH


def test_a_marker_scan_counts_markers_and_reports_no_unparseable(tmp_path: Path) -> None:
    path = write_log(
        tmp_path / "n.log",
        REAL_INSTANCE_ID,
        REAL_NBP_PUBLISHED,
        REAL_FQ_VECTOR_COMPLETE,
        REAL_ORDER_SUBMITTED,
        REAL_ORDER_DENIED,
        CONSTRUCTED_CAPTURE_REFUSED,
        PINNED_NBP_CYCLE_MISSED,
        CONSTRUCTED_EPOCH_START,
        REAL_PLAIN_LINE,
    )
    scan = nl.scan_node_log(path)
    assert scan.unparseable_total == 0
    assert dict(scan.marker_counts) == {
        "NBM_NBP_PUBLISHED": 1,
        "FQ_VECTOR_COMPLETE": 1,
        "OrderSubmitted": 1,
        "OrderDenied": 1,
        "CAPTURE_REFUSED": 1,
        "NBP_CYCLE_MISSED": 1,
        "CAPTURE_EPOCH_START": 1,
    }


# -- sinks (S2-R1) ---------------------------------------------------------------------------------


class _Recorder:
    def __init__(self, raise_at: int | None = None) -> None:
        self.events: list[object] = []
        self.raise_at = raise_at

    def feed(self, event: nl.NodeLogEvent) -> None:
        self.events.append(event)
        if self.raise_at is not None and len(self.events) == self.raise_at:
            raise RuntimeError("sink broke")


def test_a_sink_sees_every_event_in_file_order_including_unparseable(tmp_path: Path) -> None:
    broken = REAL_ORDER_SUBMITTED.replace("ts_event=1791046252271779297", "ts_event=soon")
    path = write_log(tmp_path / "n.log", REAL_INSTANCE_ID, REAL_TAKE, broken, REAL_ORDER_DENIED)
    rec = _Recorder()
    nl.scan_node_log(path, sinks=(rec,))
    assert [type(e) for e in rec.events] == [
        nl.InstanceIdLine,
        nl.DecisionLine,
        nl.UnparseableLine,
        nl.OrderDeniedLine,
    ]


def test_a_sink_sees_events_beyond_the_stored_report_cap(tmp_path: Path) -> None:
    total = nl.MAX_STORED_REPORTS + 50
    path = write_log(tmp_path / "n.log", *([REAL_TAKE] * total))
    rec = _Recorder()
    scan = nl.scan_node_log(path, sinks=(rec,))
    assert len(scan.entry_lines) == nl.MAX_STORED_REPORTS
    assert len(rec.events) == total


def test_every_sink_is_fed_in_order(tmp_path: Path) -> None:
    path = write_log(tmp_path / "n.log", REAL_TAKE, REAL_ORDER_SUBMITTED)
    first, second = _Recorder(), _Recorder()
    nl.scan_node_log(path, sinks=(first, second))
    assert len(first.events) == len(second.events) == 2


def test_sinks_are_fed_before_the_event_is_absorbed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    order: list[str] = []
    real_absorb = nl._absorb

    def spy(event: object, *args: object) -> None:
        order.append("absorb")
        real_absorb(event, *args)  # type: ignore[arg-type]

    class _Sink:
        def feed(self, event: nl.NodeLogEvent) -> None:
            order.append("feed")

    monkeypatch.setattr(nl, "_absorb", spy)
    nl.scan_node_log(write_log(tmp_path / "n.log", REAL_TAKE), sinks=(_Sink(),))
    assert order == ["feed", "absorb"]


def test_a_raising_sink_aborts_the_scan_with_node_log_sink_failed(tmp_path: Path) -> None:
    path = write_log(tmp_path / "n.log", REAL_TAKE, REAL_TAKE, REAL_TAKE)
    rec = _Recorder(raise_at=2)
    with pytest.raises(AuditInputError) as caught:
        nl.scan_node_log(path, sinks=(rec,))
    assert caught.value.cause == "node_log_sink_failed"
    assert isinstance(caught.value.__cause__, RuntimeError)
    assert len(rec.events) == 2  # the scan stopped at the failure


def test_a_raising_sink_does_not_hide_behind_a_later_sink(tmp_path: Path) -> None:
    path = write_log(tmp_path / "n.log", REAL_TAKE)
    later = _Recorder()
    with pytest.raises(AuditInputError):
        nl.scan_node_log(path, sinks=(_Recorder(raise_at=1), later))
    assert later.events == []


def test_scan_without_sinks_is_unchanged(tmp_path: Path) -> None:
    path = write_log(tmp_path / "n.log", REAL_TAKE)
    assert nl.scan_node_log(path).entry_total == nl.scan_node_log(path, sinks=()).entry_total == 1


def test_an_unreadable_log_still_raises_node_log_unreadable_with_sinks(tmp_path: Path) -> None:
    with pytest.raises(nl.NodeLogUnreadable):
        nl.scan_node_log(tmp_path / "absent.log", sinks=(_Recorder(),))
