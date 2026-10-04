"""Pure ``AuditInputs`` builders for the daily completeness audit's tests (AUT-1 WP5 stage 2a).

Every builder returns a fully populated, internally consistent value and takes keyword overrides, so
a leg test states only what it varies: ``make_inputs(boots=(make_boot(ended=False),))``. No I/O, no
clock, no randomness. Each stage-2b worktree builds on these; a worktree that needs more adds its
OWN fixtures file rather than editing this one (S2-R15).
"""

import datetime as dt
from collections.abc import Iterable, Mapping
from typing import Any, Final

from breezy.analysis.capture_audit_input_types import (
    AuditInputs,
    BootEvidence,
    ExecFill,
    ExecOrder,
    ExecView,
    FunnelCount,
    FunnelRow,
    HeartbeatSummary,
    IngestLine,
    LogMarkers,
    NotifierProof,
    RecorderJournalEntry,
    RecorderProps,
    ReplayResult,
    ResolverContext,
    StallRecord,
    StreamSummary,
)
from breezy.analysis.capture_settlement import SettlementRecord
from breezy.persistence.autonomy.capture_epoch import EpochRecord
from breezy.persistence.autonomy.capture_reader import C1View, CaptureStream

__all__ = [
    "DAY",
    "FAMILY_ID",
    "GOOD_INGEST",
    "INSTANCE_ID",
    "INSTRUMENT_ID",
    "NS",
    "EmptyTape",
    "make_boot",
    "make_exec_view",
    "make_inputs",
    "make_replay",
    "make_stream_summary",
]

NS: Final[int] = 1_000_000_000
DAY: Final[dt.date] = dt.date(2026, 10, 3)
FAMILY_ID: Final[str] = "pm_us_crh_fq_v1"
INSTANCE_ID: Final[str] = "01cea9fc-cf7d-4efa-b132-cbbaf5d0bde4"
INSTRUMENT_ID: Final[str] = "tc-temp-laxhigh-2026-10-04-gte93lt94f.POLYMARKET_US"
_DAY_START_NS: Final[int] = (
    int(dt.datetime(DAY.year, DAY.month, DAY.day, tzinfo=dt.UTC).timestamp()) * NS
)
_SHA: Final[str] = "ab" * 32
#: One ``extend_dedupe:`` line in the strict grammar of the ingest leg (T).
GOOD_INGEST: Final[str] = (
    "extend_dedupe: chunks=3 filtered=3 unfiltered=0 "
    "by_type=custom_depth_truncation:3/0,quote_tick:3/0 flat_root=none"
)


class EmptyTape:
    """A ``TapeIndex`` holding no rows: every lookup misses."""

    def lookup(
        self, frame_kind: str, instrument_id: str, ts_event: int
    ) -> Mapping[str, Any] | None:
        return None

    def quote_rows(
        self, instrument_id: str, start_ns: int, end_ns: int
    ) -> Iterable[Mapping[str, Any]]:
        return ()

    def depth_rows(
        self, instrument_id: str, start_ns: int, end_ns: int
    ) -> Iterable[Mapping[str, Any]]:
        return ()

    def best_ask_at(self, instrument_id: str, ts_ns: int) -> float | None:
        return None


def make_stream_summary(**over: Any) -> StreamSummary:
    heartbeat = HeartbeatSummary(
        ts_ns=_DAY_START_NS + 3600 * NS, seq=1, final=True, written_by_type={}, write_drops=0
    )
    fields: dict[str, Any] = {
        # The real table names (S2-R25): no decision was written, and the heartbeat table holds the
        # final heartbeat that its own snapshot does not yet count.
        "row_counts": {"custom_capture_heartbeat": 1},
        "heartbeats": (heartbeat,),
        "torn_tail_count": 0,
        "unrecognised_file_count": 0,
        "forecast_cycles": frozenset({("KLAX", 1791032400 * NS)}),
    }
    fields.update(over)
    return StreamSummary(**fields)


def make_replay(**over: Any) -> ReplayResult:
    fields: dict[str, Any] = {
        "admitted_total": 0,
        "admitted_by_kind": {},
        "evaluations": 0,
        "eval_seq_final": 0,
    }
    fields.update(over)
    return ReplayResult(**fields)


def make_boot(**over: Any) -> BootEvidence:
    instance_id = over.get("instance_id", INSTANCE_ID)
    source = over.get("source", "live")
    fields: dict[str, Any] = {
        "instance_id": instance_id,
        "source": source,
        "stream": lambda: CaptureStream(instance_id=instance_id, source=source),
        "summary": make_stream_summary(),
        "c1": C1View(FAMILY_ID, (), (), (), (), ()),
        "log_name": f"breezy-trade-{DAY:%Y%m%d}T165045Z.log",
        "scan": None,
        "markers": LogMarkers(),
        "replay": make_replay(),
        "started_ns": _DAY_START_NS + 16 * 3600 * NS,
        "last_line_ts_ns": _DAY_START_NS + 20 * 3600 * NS,
        "ended": True,
        "disposed": True,
        "overlap_s": 4 * 3600,
        "subscribed": frozenset({INSTRUMENT_ID}),
    }
    fields.update(over)
    return BootEvidence(**fields)


def make_exec_view(**over: Any) -> ExecView:
    fill = ExecFill(
        client_order_id="O-20261003-165052-L001-LAX-1",
        venue_order_id_sha256=_SHA,
        trade_id="CVWEANWH8YHR",
        instrument_id=INSTRUMENT_ID,
        order_side="BUY",
        cumulative_qty="1",
        cumulative_cost="0.15",
        ts_event=_DAY_START_NS + 17 * 3600 * NS,
        fee_reconciled=True,
    )
    fields: dict[str, Any] = {
        "fills": (fill,),
        "fill_by_day": {DAY.isoformat(): (_SHA,)},
        "fill_by_fingerprint": {f"{DAY.isoformat()}:{'cd' * 32}": _SHA},
        "orders": (ExecOrder(fill.client_order_id, _SHA),),
        "resolvers": (
            ResolverContext("intent-1", fill.client_order_id, INSTRUMENT_ID, fill.ts_event),
        ),
    }
    fields.update(over)
    return ExecView(**fields)


def make_inputs(**over: Any) -> AuditInputs:
    now_ns = _DAY_START_NS + 86_400 * NS + 14 * 3600 * NS
    fields: dict[str, Any] = {
        "day": DAY,
        "family_id": FAMILY_ID,
        "epoch": EpochRecord(FAMILY_ID, _DAY_START_NS - 86_400 * NS, INSTANCE_ID, "0" * 40),
        "boots": (make_boot(),),
        "exec": make_exec_view(),
        "settlements": (
            SettlementRecord("LAX", DAY.isoformat(), 84, "NWS_CLI", _SHA, now_ns - 3600 * NS),
        ),
        "std_offsets": {"KLAX": -8.0},
        "tape": EmptyTape(),
        "ingest_lines": (IngestLine("extend_dedupe: chunks=3 flat_root=catalog"),),
        "ingest_exited_after_rotation": False,
        "recorder_journal": (
            RecorderJournalEntry(_DAY_START_NS + 3600 * NS, "inv-1", "watchdog", "killed"),
        ),
        "recorder_props": RecorderProps(
            watchdog_usec=60_000_000, notify_access="all", type="notify"
        ),
        "stall_records": (StallRecord("inv-1", _DAY_START_NS + 3600 * NS, DAY.isoformat()),),
        "notifier_proofs": (
            NotifierProof("breezy-quote-tape.service", "inv-1", True, DAY.isoformat()),
        ),
        "now_ns": now_ns,
        "funnel": (
            FunnelRow(
                _DAY_START_NS + 17 * 3600 * NS,
                DAY.isoformat(),
                (FunnelCount("LAX", "yes", "Take", "", 1),),
            ),
        ),
    }
    fields.update(over)
    return AuditInputs(**fields)
