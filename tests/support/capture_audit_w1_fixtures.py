"""Pure builders for the W1 fill-leg tests (AUT-1 WP5 stage 2b W1; design S2-R15).

``entry_day()`` returns a fully consistent one-fill day: a Take and a ``TrySubmit(submitted)`` whose
id recomputes, an ``OrderInitialized`` link whose fingerprint is in the exec store, a node
``FILLED`` event, a position mark, a frame copy equal to the tape, a forecast vector inside the
boot's own stream, and a settlement record. ``exit_day()`` is the same for an exit SELL. Each leg
test changes only the one thing it varies, with ``dataclasses.replace``. No I/O, no clock.
"""

import dataclasses
import datetime as dt
import json
from collections.abc import Iterable, Mapping
from types import SimpleNamespace
from typing import Any, Final

from breezy.analysis.capture_audit_input_types import (
    AuditInputs,
    BootEvidence,
    ExecFill,
    ExecOrder,
    LogMarkers,
    ResolverContext,
)
from breezy.analysis.capture_node_log_markers import OrderDeniedLine, OrderSubmittedLine
from breezy.analysis.capture_settlement import SettlementRecord
from breezy.domain.exec_intent import intent_fingerprint
from breezy.persistence.autonomy.capture_ids import (
    compute_decision_id,
    compute_exit_decision_id,
    forecast_ref_of,
    frame_ref_of,
)
from breezy.persistence.autonomy.capture_reader import (
    C1View,
    CaptureStream,
    DecisionView,
    LifecycleEventView,
    OrderLinkView,
    PositionMarkView,
)
from breezy.persistence.autonomy.capture_records import FrameCopy, make_record
from tests.support.capture_audit_fixtures import (
    DAY,
    FAMILY_ID,
    INSTANCE_ID,
    NS,
    make_boot,
    make_exec_view,
    make_inputs,
)
from tests.unit.capture_reader_support import HOUR_NS, full_cycle

__all__ = [
    "ARTEFACT",
    "COID",
    "DAY_START_NS",
    "FILL_TS",
    "FRAME_TS",
    "INSTRUMENT",
    "NO_INSTRUMENT",
    "STATION",
    "TRADE_ID",
    "VSHA",
    "DictTape",
    "decision_view",
    "entry_day",
    "exit_day",
    "link_view",
    "markers_with",
    "replace_boot",
    "replace_c1",
    "resolver",
    "with_decisions",
]

DAY_START_NS: Final[int] = (
    int(dt.datetime(DAY.year, DAY.month, DAY.day, tzinfo=dt.UTC).timestamp()) * NS
)
STATION: Final[str] = "LAX"
FORECAST_STATION: Final[str] = "KLAX"
INSTRUMENT: Final[str] = "tc-temp-laxhigh-2026-10-03-gte93lt94f.POLYMARKET_US"
NO_INSTRUMENT: Final[str] = "tc-temp-laxhigh-2026-10-03-gte93lt94f^no.POLYMARKET_US"
COID: Final[str] = "O-20261003-170000-L001-LAX-1"
TRADE_ID: Final[str] = "CVWEANWH8YHR"
VSHA: Final[str] = "ab" * 32
ARTEFACT: Final[str] = "cd" * 32
MANIFEST: Final[str] = "ef" * 32
EVAL_NS: Final[int] = DAY_START_NS + 17 * 3600 * NS
FRAME_TS: Final[int] = EVAL_NS - 1_000_000
FILL_TS: Final[int] = EVAL_NS + 5 * NS
CYCLE_NS: Final[int] = 100 * HOUR_NS
VINTAGE_NS: Final[int] = 102 * HOUR_NS
RUNG: Final[str] = "gte93lt94f"
DEPTH_BODY: Final[dict[str, Any]] = {
    "ts_event": FRAME_TS,
    "bids": [["0.14", "10"]],
    "asks": [["0.15", "5"], ["0.16", "7"]],
}
QUOTE_BODY: Final[dict[str, Any]] = {"ask": "0.15", "bid": "0.14", "ts_event": FRAME_TS}


class DictTape:
    """A ``TapeIndex`` backed by dicts: ``rows[(kind, instrument, ts)]``, ``asks[(instr, ts)]``."""

    def __init__(
        self,
        rows: Mapping[tuple[str, str, int], Mapping[str, Any]] | None = None,
        asks: Mapping[tuple[str, int], float | None] | None = None,
    ) -> None:
        self.rows = dict(rows or {})
        self.asks = dict(asks or {})
        self.lookups: list[tuple[str, str, int]] = []

    def lookup(
        self, frame_kind: str, instrument_id: str, ts_event: int
    ) -> Mapping[str, Any] | None:
        self.lookups.append((frame_kind, instrument_id, ts_event))
        return self.rows.get((frame_kind, instrument_id, ts_event))

    def quote_rows(self, instrument_id: str, start_ns: int, end_ns: int) -> Iterable[Any]:
        return ()

    def depth_rows(self, instrument_id: str, start_ns: int, end_ns: int) -> Iterable[Any]:
        return ()

    def best_ask_at(self, instrument_id: str, ts_ns: int) -> float | None:
        return self.asks.get((instrument_id, ts_ns))


def decision_view(kind: str = "Take", reason: str = "take", **over: Any) -> DecisionView:
    """A decision view; ``decision_id`` recomputes from its own fields unless overridden."""
    frame_kind = over.pop("frame_kind", "depth10")
    ref = frame_ref_of(frame_kind, INSTRUMENT, FRAME_TS)
    fields: dict[str, Any] = {
        "schema": "capture_decision/v2",
        "family_id": FAMILY_ID,
        "node_boot_id": INSTANCE_ID,
        "build_sha": "0" * 40,
        "registry_seq": 1,
        "drill": False,
        "source": "live",
        "kind": kind,
        "reason": reason,
        "eval_ns": EVAL_NS,
        "eval_seq": 0,
        "wall_ns": EVAL_NS + NS,
        "ts_ns": EVAL_NS + NS,
        "station": STATION,
        "climate_day": DAY.isoformat(),
        "rung_id": RUNG,
        "side": "yes",
        "instrument_id": INSTRUMENT,
        "ask_px": "0.15",
        "depth_ref": ref if frame_kind == "depth10" else "",
        "quote_ref": ref if frame_kind == "quote" else "",
        "p_hat": "0.5",
        "p_hat_raw": "0.5",
        "p_lower": "0.4",
        "p_upper": "0.6",
        "ev_net": "0.1",
        "margin": "0.05",
        "forecast_input_ref": forecast_ref_of(FORECAST_STATION, CYCLE_NS, VINTAGE_NS),
        "artefact_sha256": ARTEFACT,
        "manifest_sha256": MANIFEST,
    }
    fields.update(over)
    if "decision_id" not in fields:
        fields["decision_id"] = compute_decision_id(
            fields["family_id"],
            fields["manifest_sha256"],
            fields["artefact_sha256"],
            fields["station"],
            fields["climate_day"],
            fields["rung_id"],
            fields["side"],
            fields["eval_ns"],
            fields["eval_seq"],
        )
    return DecisionView(**fields)


def link_view(decision_id: str, **over: Any) -> OrderLinkView:
    """An ``OrderLink`` whose stored fingerprint is the real ``intent_fingerprint``."""
    fields: dict[str, Any] = {
        "decision_id": decision_id,
        "client_order_id": COID,
        "venue_order_id_sha256": VSHA,
        "instrument_id": INSTRUMENT,
        "side": "BUY",
        "qty": "1",
        "px": "0.15",
        "time_in_force": "IOC",
        "ts_ns": EVAL_NS + 2 * NS,
        "source": "live",
    }
    fields.update(over)
    fields["intent_fingerprint"] = fingerprint_of(fields)
    return OrderLinkView(**fields)


def fingerprint_of(link: Mapping[str, Any]) -> str:
    return intent_fingerprint(
        SimpleNamespace(
            instrument_id=link["instrument_id"],
            side=link["side"],
            quantity=link["qty"],
            price=link["px"],
            time_in_force=link["time_in_force"],
            client_order_id=link["client_order_id"],
        )
    )


def _filled(**over: Any) -> LifecycleEventView:
    fields: dict[str, Any] = {
        "event": "FILLED",
        "client_order_id": COID,
        "trade_id": TRADE_ID,
        "qty": "1",
        "px": "0.15",
        "fee": "0.01",
        "decision_id": "",
        "venue_order_id_sha256": VSHA,
        "reason": "",
        "ts_ns": FILL_TS,
        "source": "live",
    }
    fields.update(over)
    return LifecycleEventView(**fields)


def _mark(**over: Any) -> PositionMarkView:
    fields: dict[str, Any] = {
        "instrument_id": INSTRUMENT,
        "leg": "yes",
        "net_qty": "1",
        "mark_px": "0.15",
        "reconciliation_source": "node_belief",
        "source": "live",
        "ts_ns": FILL_TS + 60 * NS,
        "event_type": "position_opened",
    }
    fields.update(over)
    return PositionMarkView(**fields)


def _copy(decision_id: str, kind: str, body: Mapping[str, Any]) -> Any:
    return make_record(
        FrameCopy,
        ts_event=FRAME_TS,
        ts_init=EVAL_NS,
        schema="capture_frame_copy/v1",
        decision_id=decision_id,
        frame_kind=kind,
        instrument=INSTRUMENT,
        frame_ts_event=FRAME_TS,
        frame_body=dict(body),
    )


def _boot(c1: C1View, stream: CaptureStream, **over: Any) -> BootEvidence:
    return make_boot(c1=c1, stream=lambda: stream, **over)


def _exec_fill(**over: Any) -> ExecFill:
    fields: dict[str, Any] = {
        "client_order_id": COID,
        "venue_order_id_sha256": VSHA,
        "trade_id": TRADE_ID,
        "instrument_id": INSTRUMENT,
        "order_side": "BUY",
        "cumulative_qty": "1",
        "cumulative_cost": "0.15",
        "ts_event": FILL_TS,
        "fee_reconciled": True,
    }
    fields.update(over)
    return ExecFill(**fields)


def entry_day(frame_kind: str = "depth10", **over: Any) -> AuditInputs:
    """A consistent day with one BUY fill; every leg of ``audit_fills`` passes."""
    body = DEPTH_BODY if frame_kind == "depth10" else QUOTE_BODY
    take = decision_view("Take", "take", frame_kind=frame_kind)
    submit = decision_view(
        "TrySubmit", "submitted", decision_id=take.decision_id, frame_kind=frame_kind
    )
    link = link_view(take.decision_id)
    c1 = C1View(FAMILY_ID, (take, submit), (link,), (_filled(),), (_mark(),), ())
    stream = CaptureStream(
        INSTANCE_ID,
        "live",
        frame_copies=(_copy(take.decision_id, frame_kind, body),),
        forecast_points=tuple(full_cycle(cycle_ns=CYCLE_NS, station=FORECAST_STATION)),
    )
    fill = _exec_fill()
    day = DAY.isoformat()
    exec_view = make_exec_view(
        fills=(fill,),
        fill_by_day={day: (VSHA,)},
        fill_by_fingerprint={f"{day}:{link.intent_fingerprint}": VSHA},
        orders=(ExecOrder(COID, VSHA),),
        resolvers=(),
    )
    tape = DictTape(rows={(frame_kind, INSTRUMENT, FRAME_TS): body})
    fields: dict[str, Any] = {
        "boots": (_boot(c1, stream),),
        "exec": exec_view,
        "tape": tape,
        "std_offsets": {"KLAX": -8.0, "LAX": -8.0},
        "settlements": (
            SettlementRecord(STATION, day, 84, "NWS_CLI", VSHA, DAY_START_NS + 100_000 * NS),
        ),
    }
    fields.update(over)
    return make_inputs(**fields)


def exit_day(**over: Any) -> AuditInputs:
    """A day with one exit SELL fill: an ``Exit`` record whose id recomputes from the four tags."""
    values = ("stop_loss", "pos-1", FAMILY_ID, "O-20261003-160000-L001-LAX-0")
    exit_id = compute_exit_decision_id(*values)
    record = decision_view(
        "Exit",
        "exit",
        decision_id=exit_id,
        frame_kind="",
        eval_ns=FILL_TS - NS,
        eval_seq=0,
    )
    link = link_view(exit_id, side="SELL")
    tags = [
        f"exit_rule={values[0]}",
        f"exit_position_id={values[1]}",
        f"exit_family_id={values[2]}",
        f"exit_client_order_id={values[3]}",
    ]
    row = {"client_order_id": COID, "tags": json.dumps(tags)}
    c1 = C1View(FAMILY_ID, (record,), (link,), (_filled(),), (_mark(net_qty="0"),), ())
    stream = CaptureStream(
        INSTANCE_ID,
        "live",
        frame_copies=(_copy(exit_id, "", {"price": "0.15"}),),
        order_initialized=(row,),
    )
    day = DAY.isoformat()
    fill = _exec_fill(order_side="SELL")
    exec_view = make_exec_view(
        fills=(fill,),
        fill_by_day={day: (VSHA,)},
        fill_by_fingerprint={f"{day}:{link.intent_fingerprint}": VSHA},
        orders=(ExecOrder(COID, VSHA),),
        resolvers=(),
    )
    fields: dict[str, Any] = {
        "boots": (_boot(c1, stream),),
        "exec": exec_view,
        "std_offsets": {"KLAX": -8.0, "LAX": -8.0},
        "settlements": (
            SettlementRecord(STATION, day, 84, "NWS_CLI", VSHA, DAY_START_NS + 100_000 * NS),
        ),
    }
    fields.update(over)
    return make_inputs(**fields)


def replace_c1(inp: AuditInputs, **changes: Any) -> AuditInputs:
    """``inp`` with the first boot's ``c1`` fields replaced (its stream handle is kept)."""
    boot = inp.boots[0]
    return dataclasses.replace(
        inp,
        boots=(
            dataclasses.replace(boot, c1=dataclasses.replace(boot.c1, **changes)),
            *inp.boots[1:],
        ),
    )


def with_decisions(inp: AuditInputs, *extra: DecisionView) -> AuditInputs:
    return replace_c1(inp, decisions=(*inp.boots[0].c1.decisions, *extra))


def replace_boot(inp: AuditInputs, **changes: Any) -> AuditInputs:
    return dataclasses.replace(
        inp, boots=(dataclasses.replace(inp.boots[0], **changes), *inp.boots[1:])
    )


def markers_with(submitted: Iterable[str] = (), denied: Iterable[str] = ()) -> LogMarkers:
    return LogMarkers(
        order_submitted=tuple(
            OrderSubmittedLine(1, EVAL_NS, INSTRUMENT, coid, "ACC", EVAL_NS) for coid in submitted
        ),
        order_denied=tuple(OrderDeniedLine(2, EVAL_NS, INSTRUMENT, coid, "x") for coid in denied),
    )


def resolver(coid: str = COID, *, created_ns: int = FILL_TS) -> ResolverContext:
    return ResolverContext("intent-1", coid, INSTRUMENT, created_ns)
