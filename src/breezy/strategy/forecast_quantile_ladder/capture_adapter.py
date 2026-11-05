"""AUT-1 ``FqCaptureAdapter`` (plan r12 sections 3.3, 3.5; r8 section 3.4 field map, ER-3/ER-4).

The C6 ``CaptureAdapter`` for ``forecast_quantile_ladder``. LIBRARY ONLY in WP2: FQ's live strategy
does not call it until WP7. Pure parts: ``decision_record``, ``frame_copy``, ``order_tags``. The
publishing part, ``capture`` and ``follow_up``, goes through the injected ``CapturePublisher`` and
never raises (L-16).

Take-path rules (section 3.3.2):

* A ``Take`` publishes its ``FrameCopy`` BEFORE its ``DecisionRecord``, so a reader that sees the
  Take sees its copy. If the copy fails the record is not published and no id is returned, which is
  FQ's ``decision_id is None`` refusal (``capture_gap``, CS-2).
* A refusal NEVER publishes a ``FrameCopy``: it cites its frame by reference (kind, ``ts_event``).
* ``TrySubmit`` and ``EntryVeto`` continue a Take's id and share its copy.

A quote-triggered decision cites the QUOTE (D2, U8) whether or not a depth is in hand. The
refusal inputs WP7 adds to ``Refuse`` (``p_hat`` and friends) are read with ``getattr``, so this
adapter works before and after that change and a refusal that does not carry them records null.
"""

import logging
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Final, Literal

from nautilus_trader.model.data import OrderBookDepth10, QuoteTick

from breezy.persistence.autonomy.capture_ids import compute_decision_id
from breezy.persistence.autonomy.capture_on_change import OnChangeFilter
from breezy.persistence.autonomy.capture_publish import CapturePublisher
from breezy.persistence.autonomy.capture_records import (
    DECISION_SCHEMA,
    FRAME_COPY_SCHEMA,
    NULL_STR,
    DecisionRecord,
    FrameCopy,
    make_record,
)
from breezy.persistence.exit_tags import DECISION_ID_TAG_PREFIX
from breezy.strategy.autonomy_capture.guarded_strategy import (
    CaptureIdentity,
    FollowUp,
    decision_follow_up,
)
from breezy.strategy.forecast_quantile_ladder.decision import (
    Decision,
    NotDPlus1,
    NotExecutable,
    Refuse,
    Take,
)
from breezy.strategy.ladder_ev.forecast_state import ForecastQuantileVector

__all__ = ["REASON_TAKE", "CaptureContext", "FqCaptureAdapter"]

REASON_TAKE: Final[str] = "take"
_SUPPORTED_RECALIBRATION: Final[str] = "none"
_TRIGGER_DEPTH: Final = "depth"
_TRIGGER_QUOTE: Final = "quote_tick"
_FRAME_KIND_DEPTH: Final[str] = "depth10"
_FRAME_KIND_QUOTE: Final[str] = "quote"
_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True, kw_only=True)
class CaptureContext:
    """What the adapter needs besides the decision. ``trigger`` is named so it cannot collide with
    C1's ``source`` (live or canary). The key fields are the instrument's own (a refusal carries
    none); ``station`` is also the forecast's station, the key FQ read the vector under."""

    eval_ns: int
    eval_seq: int
    wall_ns: int
    trigger: Literal["depth", "quote_tick"]
    depth: OrderBookDepth10 | None
    quote: QuoteTick | None
    vector: ForecastQuantileVector | None
    ask_px: Decimal
    station: str
    climate_day: date
    rung_id: str
    side: Literal["yes", "no"]
    instrument_id: str

    def __post_init__(self) -> None:
        if self.trigger not in (_TRIGGER_DEPTH, _TRIGGER_QUOTE):
            raise ValueError(f"trigger must be 'depth' or 'quote_tick', was {self.trigger!r}")
        if self.trigger == _TRIGGER_DEPTH and self.depth is None:
            raise ValueError("a depth-triggered context needs the depth frame")
        if self.trigger == _TRIGGER_QUOTE and self.quote is None:
            raise ValueError("a quote-triggered context needs the quote tick")


def _number(value: object) -> str:
    return NULL_STR if value is None else repr(float(value))  # type: ignore[arg-type]


def _decision_kind(decision: Decision) -> str:
    for cls in (Take, NotExecutable, NotDPlus1, Refuse):
        if isinstance(decision, cls):
            return cls.__name__
    raise TypeError(f"not a decision: {type(decision).__name__}")


class FqCaptureAdapter:
    def __init__(
        self,
        *,
        publisher: CapturePublisher,
        identity: CaptureIdentity,
        recalibration: str,
        on_take: Any = None,
        on_change: OnChangeFilter | None = None,
    ) -> None:
        if recalibration != _SUPPORTED_RECALIBRATION:
            raise ValueError(
                f"recalibration must be {_SUPPORTED_RECALIBRATION!r} (p_hat_raw is p_hat only "
                f"then), was {recalibration!r}; widening it needs a raw field on Take"
            )
        self._publisher = publisher
        self._identity = identity
        self._on_take = on_take
        self._on_change = on_change if on_change is not None else OnChangeFilter()

    # -- C6 --------------------------------------------------------------------------------------

    def order_tags(self, decision_id: str) -> tuple[str, ...]:
        return (f"{DECISION_ID_TAG_PREFIX}{decision_id}",)

    def decision_record(self, decision: Decision, ctx: CaptureContext) -> DecisionRecord:
        """Pure: no I/O. The id is computed from this record's own key and clock."""
        kind = _decision_kind(decision)
        ident = self._identity
        key = _key_of(decision, ctx)
        frame_kind, frame_ts = _frame_ref(ctx)
        fields: dict[str, Any] = {
            "schema": DECISION_SCHEMA,
            "family_id": ident.family_id,
            "node_boot_id": ident.node_boot_id,
            "build_sha": ident.build_sha,
            "registry_seq": ident.registry_seq,
            "drill": ident.drill,
            "source": ident.source,
            "kind": kind,
            "eval_ns": ctx.eval_ns,
            "eval_seq": ctx.eval_seq,
            "wall_ns": ctx.wall_ns,
            "station": key[0],
            "climate_day": key[1],
            "rung_id": key[2],
            "side": key[3],
            "instrument": key[4],
            "ask_px": str(ctx.ask_px),
            "frame_kind": frame_kind,
            "frame_ts_event": frame_ts,
            "artefact_sha256": ident.artefact_sha256,
            "manifest_sha256": ident.manifest_sha256,
        }
        fields.update(self._inputs(decision))
        fields.update(self._forecast_ref(ctx))
        fields["decision_id"] = compute_decision_id(
            ident.family_id,
            ident.manifest_sha256,
            ident.artefact_sha256,
            key[0],
            key[1],
            key[2],
            key[3],
            ctx.eval_ns,
            ctx.eval_seq,
        )
        # The two ``reason=`` keywords below: a constant for a Take, and the refusal's own reason
        # read off the decision (an enumerated copy site of the closure lint, WP2-R2).
        if isinstance(decision, Take):
            return make_record(
                DecisionRecord,
                ts_event=ctx.eval_ns,
                ts_init=ctx.wall_ns,
                reason=REASON_TAKE,
                **fields,
            )
        return make_record(
            DecisionRecord,
            ts_event=ctx.eval_ns,
            ts_init=ctx.wall_ns,
            reason=decision.reason,
            **fields,
        )

    @staticmethod
    def _inputs(decision: Decision) -> dict[str, str]:
        """The numeric decision inputs, or null where the decision does not carry them. A
        ``Take`` always does; a refusal does once WP7 adds the fields (section 3.5.2)."""
        values = {
            name: _number(getattr(decision, name, None))
            for name in ("p_hat", "p_lower", "p_upper", "ev_net", "margin")
        }
        values["p_hat_raw"] = values["p_hat"]  # recalibration is "none" (checked at construction)
        return values

    @staticmethod
    def _forecast_ref(ctx: CaptureContext) -> dict[str, Any]:
        vector = ctx.vector
        if vector is None:
            return {
                "forecast_station": NULL_STR,
                "forecast_cycle_ns": 0,
                "forecast_available_at_ns": 0,
            }
        return {
            "forecast_station": ctx.station,
            "forecast_cycle_ns": vector.cycle_runtime_ns,
            "forecast_available_at_ns": vector.available_at_ns,
        }

    def frame_copy(self, record: DecisionRecord, ctx: CaptureContext) -> FrameCopy:
        """The Take-path copy of the triggering frame. Pure."""
        return make_record(
            FrameCopy,
            ts_event=record.frame_ts_event,
            ts_init=ctx.wall_ns,
            schema=FRAME_COPY_SCHEMA,
            decision_id=record.decision_id,
            frame_kind=record.frame_kind,
            instrument=record.instrument,
            frame_ts_event=record.frame_ts_event,
            frame_body=_frame_body(ctx),
        )

    # -- publishing ------------------------------------------------------------------------------

    def capture(self, decision: Decision, ctx: CaptureContext) -> str | None:
        """Publish one evaluation. Returns its ``decision_id``, or ``None`` when it could not be
        recorded (FQ refuses a Take with no id, CS-2). A refusal the on-change filter does not admit
        writes nothing and still returns its id. Never raises."""
        try:
            record = self.decision_record(decision, ctx)
            is_take = record.kind == "Take"
            copy = self.frame_copy(record, ctx) if is_take else None
            key = (record.station, record.climate_day, record.rung_id, record.side)
            if not self._on_change.admit(key, record.kind, record.reason, ctx.eval_ns):
                return str(record.decision_id)
        except Exception:  # noqa: BLE001 - L-16: nothing escapes into a handler
            _LOGGER.error("CAPTURE_RECORD_BUILD_FAILED type=%s", type(decision).__name__)
            return None
        if copy is not None and not self._publisher.write(copy):
            return None
        if not self._publisher.write(record):
            return None
        if is_take and not self._notify_take(record):
            return None
        return str(record.decision_id)

    def follow_up(self, take: DecisionRecord, *, kind: str, reason: str, wall_ns: int) -> bool:
        """Publish a ``TrySubmit`` / ``EntryVeto`` / ``Refuse`` that continues a Take. It shares the
        Take's id and frame copy, so no copy is published. On-change per key."""
        try:
            record = decision_follow_up(take, FollowUp(kind=kind, reason=reason, wall_ns=wall_ns))
            key = (take.station, take.climate_day, take.rung_id, take.side)
            if not self._on_change.admit(key, kind, reason, take.eval_ns):
                return True
        except Exception:  # noqa: BLE001 - L-16
            _LOGGER.error("CAPTURE_RECORD_BUILD_FAILED type=%s", kind)
            return False
        return self._publisher.write(record)

    def _notify_take(self, record: DecisionRecord) -> bool:
        if self._on_take is None:
            return True
        try:
            self._on_take(record)
        except Exception:  # noqa: BLE001 - L-16
            _LOGGER.error("CAPTURE_TAKE_NOTIFY_FAILED decision_id=%s", record.decision_id)
            return False
        return True


def _key_of(decision: Decision, ctx: CaptureContext) -> tuple[str, str, str, str, str]:
    """``(station, climate_day, rung_id, side, instrument)``: a Take's own, else the context's."""
    if isinstance(decision, Take):
        return (
            decision.station,
            decision.climate_day.isoformat(),
            decision.rung_id,
            decision.side,
            decision.instrument_id,
        )
    return ctx.station, ctx.climate_day.isoformat(), ctx.rung_id, ctx.side, ctx.instrument_id


def _frame_ref(ctx: CaptureContext) -> tuple[str, int]:
    if ctx.trigger == _TRIGGER_DEPTH:
        assert ctx.depth is not None
        return _FRAME_KIND_DEPTH, int(ctx.depth.ts_event)
    assert ctx.quote is not None
    return _FRAME_KIND_QUOTE, int(ctx.quote.ts_event)


def _frame_body(ctx: CaptureContext) -> dict[str, Any]:
    if ctx.trigger == _TRIGGER_QUOTE:
        assert ctx.quote is not None
        return {
            "ask": str(ctx.quote.ask_price),
            "bid": str(ctx.quote.bid_price),
            "ts_event": int(ctx.quote.ts_event),
        }
    assert ctx.depth is not None
    return {
        "ts_event": int(ctx.depth.ts_event),
        "bids": [[str(o.price), str(o.size)] for o in ctx.depth.bids if o.size > 0],
        "asks": [[str(o.price), str(o.size)] for o in ctx.depth.asks if o.size > 0],
    }
