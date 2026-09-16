"""Persistence records for the intra-day position monitor (SHADOW-ONLY, INC-4).

L-1: ``ParquetDataCatalog`` + ``register_arrow`` are native Nautilus machinery
(skill primary pattern -- hand-written ``Data`` plus one ``register_arrow``
call); this module supplies the two record TYPES Nautilus has no native
carrier for -- a per-evaluation position mark and a per-position-day monitor
summary. See ``docs/plans/INTRADAY_POSITION_MONITOR_2026-09-15.md`` Sec 1/4.

``PositionMarkRecord`` is a hand-written ``Data`` subclass, never
``@customdataclass`` (traps 15/18): ``ParquetDataCatalog`` infers a
partition's schema from whichever fragment sorts first and coerces every
later fragment to it silently, so an explicit decoder that RAISES on drift
is the only reliable detection point.

``instrument_id`` is typed ``InstrumentId`` (not ``str``), following the
``QuoteTapeGap`` precedent (``adapters/polymarket_us/tape_records.py:55``)
rather than the plain-``str`` alternative trap 21 allows: a typed
``instrument_id`` gives this record native per-instrument catalog
partitioning (``data/custom_positionmarkrecord/<instrument_id>/``) for
free, so two instruments' marks can never merge into one flat,
indistinguishable directory the way a station-only key would. The Arrow
SCHEMA column stays ``pa.string()`` regardless -- Arrow has no
``InstrumentId`` type -- ``to_dict``/``from_dict`` convert at the boundary.

This module never imports ``monitor_evidence.py`` or ``monitor_decision.py``
(built concurrently by another agent): ``thesis_state``/``verdict`` arrive
as plain ``.value`` strings from the caller, never as the enum types
themselves.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import pyarrow as pa
from nautilus_trader.core.data import Data
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.serialization.arrow.serializer import register_arrow

from breezy.domain.strict_arrow import make_strict_decoder, make_strict_encoder
from breezy.domain.validation import (
    require_bool,
    require_int,
    require_optional_int,
    require_optional_text,
    require_text,
)

__all__ = ["PositionMarkRecord", "PositionMonitorSummary"]


def _require_decimal(value: Any, name: str) -> Decimal:
    if not isinstance(value, Decimal):
        raise TypeError(f"`{name}` must be a `Decimal`, was {type(value).__name__}")
    return value


def _require_optional_decimal(value: Any, name: str) -> Decimal | None:
    if value is None:
        return None
    return _require_decimal(value, name)


def _decimal_to_str(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _str_to_decimal(value: Any, name: str) -> Decimal | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"`{name}` must be a `str` or `None`, was {type(value).__name__}")
    return Decimal(value)


class PositionMarkRecord(Data):
    """One shadow-monitor evaluation of a currently-held position.

    Emission policy (M2, enforced by the caller in ``position_monitor.py``,
    INC-5): a row is written only on a state/verdict change or a per
    -instrument heartbeat, never once per tick.
    """

    def __init__(
        self,
        *,
        instrument_id: InstrumentId,
        station: str,
        climate_day: str,
        leg: str,
        entry_context: str,
        thesis_state: str,
        verdict: str,
        mark_vwap: Decimal | None,
        mark_source: str,
        unrealized_pnl: Decimal | None,
        recoverable_value: Decimal | None,
        running_max_lower: Decimal | None,
        running_max_upper: Decimal | None,
        staleness_ns: int,
        book_staleness_ns: int,
        held_qty: Decimal,
        reason_codes: tuple[str, ...],
        ts_event: int,
        ts_init: int,
    ) -> None:
        if not isinstance(instrument_id, InstrumentId):
            raise TypeError(
                f"`instrument_id` must be an `InstrumentId`, was {type(instrument_id).__name__}"
            )
        for code in reason_codes:
            if "," in code:
                raise ValueError(
                    f"reason code {code!r} contains a comma; `reason_codes` is "
                    "serialized comma-joined and a comma inside one code would "
                    "corrupt the round-trip"
                )

        self.instrument_id = instrument_id
        self.station = require_text(station, "station")
        self.climate_day = require_text(climate_day, "climate_day")
        self.leg = require_text(leg, "leg")
        self.entry_context = require_text(entry_context, "entry_context")
        self.thesis_state = require_text(thesis_state, "thesis_state")
        self.verdict = require_text(verdict, "verdict")
        self.mark_vwap = _require_optional_decimal(mark_vwap, "mark_vwap")
        self.mark_source = require_text(mark_source, "mark_source")
        self.unrealized_pnl = _require_optional_decimal(unrealized_pnl, "unrealized_pnl")
        self.recoverable_value = _require_optional_decimal(recoverable_value, "recoverable_value")
        self.running_max_lower = _require_optional_decimal(running_max_lower, "running_max_lower")
        self.running_max_upper = _require_optional_decimal(running_max_upper, "running_max_upper")
        self.staleness_ns = require_int(staleness_ns, "staleness_ns")
        self.book_staleness_ns = require_int(book_staleness_ns, "book_staleness_ns")
        self.held_qty = _require_decimal(held_qty, "held_qty")
        self.reason_codes = tuple(reason_codes)
        self._ts_event = require_int(ts_event, "ts_event")
        self._ts_init = require_int(ts_init, "ts_init")

    @property
    def ts_event(self) -> int:
        return self._ts_event

    @property
    def ts_init(self) -> int:
        return self._ts_init

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(instrument_id={self.instrument_id}, "
            f"station={self.station!r}, climate_day={self.climate_day!r}, "
            f"thesis_state={self.thesis_state!r}, verdict={self.verdict!r})"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "ts_event": self._ts_event,
            "ts_init": self._ts_init,
            "instrument_id": self.instrument_id.value,
            "station": self.station,
            "climate_day": self.climate_day,
            "leg": self.leg,
            "entry_context": self.entry_context,
            "thesis_state": self.thesis_state,
            "verdict": self.verdict,
            "mark_vwap": _decimal_to_str(self.mark_vwap),
            "mark_source": self.mark_source,
            "unrealized_pnl": _decimal_to_str(self.unrealized_pnl),
            "recoverable_value": _decimal_to_str(self.recoverable_value),
            "running_max_lower": _decimal_to_str(self.running_max_lower),
            "running_max_upper": _decimal_to_str(self.running_max_upper),
            "staleness_ns": self.staleness_ns,
            "book_staleness_ns": self.book_staleness_ns,
            "held_qty": str(self.held_qty),
            "reason_codes": ",".join(self.reason_codes),
        }

    @classmethod
    def from_dict(cls, values: dict[str, Any]) -> PositionMarkRecord:
        """Raise on a missing column rather than substituting a default.

        Every key is read by direct subscript (never ``.get``) -- the only
        reliable schema-drift detection point alongside the strict decoder
        registered below.
        """
        raw_reason_codes = values["reason_codes"]
        if not isinstance(raw_reason_codes, str):
            raise TypeError(
                f"`reason_codes` must be a `str`, was {type(raw_reason_codes).__name__}"
            )
        reason_codes = () if raw_reason_codes == "" else tuple(raw_reason_codes.split(","))

        return cls(
            instrument_id=InstrumentId.from_str(values["instrument_id"]),
            station=values["station"],
            climate_day=values["climate_day"],
            leg=values["leg"],
            entry_context=values["entry_context"],
            thesis_state=values["thesis_state"],
            verdict=values["verdict"],
            mark_vwap=_str_to_decimal(values["mark_vwap"], "mark_vwap"),
            mark_source=values["mark_source"],
            unrealized_pnl=_str_to_decimal(values["unrealized_pnl"], "unrealized_pnl"),
            recoverable_value=_str_to_decimal(values["recoverable_value"], "recoverable_value"),
            running_max_lower=_str_to_decimal(values["running_max_lower"], "running_max_lower"),
            running_max_upper=_str_to_decimal(values["running_max_upper"], "running_max_upper"),
            staleness_ns=values["staleness_ns"],
            book_staleness_ns=values["book_staleness_ns"],
            held_qty=Decimal(values["held_qty"]),
            reason_codes=reason_codes,
            ts_event=values["ts_event"],
            ts_init=values["ts_init"],
        )

    @classmethod
    def schema(cls) -> pa.Schema:
        return pa.schema(
            [
                pa.field("ts_event", pa.int64(), nullable=False),
                pa.field("ts_init", pa.int64(), nullable=False),
                pa.field("instrument_id", pa.string(), nullable=False),
                pa.field("station", pa.string(), nullable=False),
                pa.field("climate_day", pa.string(), nullable=False),
                pa.field("leg", pa.string(), nullable=False),
                pa.field("entry_context", pa.string(), nullable=False),
                pa.field("thesis_state", pa.string(), nullable=False),
                pa.field("verdict", pa.string(), nullable=False),
                pa.field("mark_vwap", pa.string(), nullable=True),
                pa.field("mark_source", pa.string(), nullable=False),
                pa.field("unrealized_pnl", pa.string(), nullable=True),
                pa.field("recoverable_value", pa.string(), nullable=True),
                pa.field("running_max_lower", pa.string(), nullable=True),
                pa.field("running_max_upper", pa.string(), nullable=True),
                pa.field("staleness_ns", pa.int64(), nullable=False),
                pa.field("book_staleness_ns", pa.int64(), nullable=False),
                pa.field("held_qty", pa.string(), nullable=False),
                pa.field("reason_codes", pa.string(), nullable=False),
            ]
        )


# Registered exactly once, at module scope (trap 18: a second call silently
# overwrites the registry entry while leaving `cls._schema` untouched).
# Mirrors `station_observation.py:256-261`'s call shape exactly -- passing
# `make_strict_encoder`/`make_strict_decoder`'s return values directly,
# rather than through a locally-typed wrapper, is what keeps `list[...]`
# invariance from fighting the `ArrowRecord` protocol under mypy --strict.
register_arrow(
    data_cls=PositionMarkRecord,
    schema=PositionMarkRecord.schema(),
    encoder=make_strict_encoder(PositionMarkRecord.schema()),
    decoder=make_strict_decoder(PositionMarkRecord, PositionMarkRecord.schema()),
)


@dataclass(frozen=True, slots=True, kw_only=True)
class PositionMonitorSummary:
    """Per-position-day rollup of the shadow monitor's evaluation trail.

    Written from the in-memory ``_MonitoredPosition`` on flush/``on_stop``
    (``position_monitor.py``, INC-5), upserted with an incremented
    ``monitor_seq``; ``settled_*`` fields are populated only by the nightly
    report's join against ``read_scored_trials``
    (``scored_trial_store.py:104``).
    """

    trial_id: str
    instrument_id: str
    station: str
    climate_day: str
    leg: str
    entry_context: str
    monitor_seq: int
    fill_px: Decimal
    held_qty: Decimal
    mae: Decimal
    mfe: Decimal
    first_signal_ts_ns: int | None
    first_signal_hour_lst: int | None
    first_signal_state: str | None
    verdict_at_signal: str | None
    recoverable_value_at_signal: Decimal | None
    held_duration_ns: int
    total_frames: int
    mark_missing_frames: int
    settled_pnl: Decimal | None
    settled_held: bool | None
    monitor_intervened: bool = False
    #: INC-E3 (plan §3, PREREG v4 §3b/§12): the registered exit rule
    #: (``"R_THREAT"``/``"R_DEAD"``) the MOST RECENT exit decision for this
    #: position-day was evaluated under. ``None`` for every position no
    #: decider ever evaluated (every row before this increment, and every
    #: shadow-monitored position after it).
    exit_rule: str | None = None
    #: ``"fired"`` or ``"refused"`` for the most recent exit decision.
    #: ``None`` when no decider was ever consulted.
    exit_decision: str | None = None
    #: The exit decider's own distinct reason code for the most recent
    #: decision (see ``exit_decider.py``), or ``"fired"`` on a proposal.
    exit_reason_code: str | None = None
    #: The authorised 1-contract limit price of the most recent FIRED exit
    #: decision. ``None`` otherwise.
    exit_limit_price: Decimal | None = None
    #: The archive's own hold expectation the most recent FIRED exit
    #: cleared. ``None`` otherwise.
    expected_settlement_value: Decimal | None = None

    def __post_init__(self) -> None:
        require_text(self.trial_id, "trial_id")
        require_text(self.instrument_id, "instrument_id")
        require_text(self.station, "station")
        require_text(self.climate_day, "climate_day")
        require_text(self.leg, "leg")
        require_text(self.entry_context, "entry_context")
        require_int(self.monitor_seq, "monitor_seq")
        _require_decimal(self.fill_px, "fill_px")
        _require_decimal(self.held_qty, "held_qty")
        _require_decimal(self.mae, "mae")
        _require_decimal(self.mfe, "mfe")
        require_optional_int(self.first_signal_ts_ns, "first_signal_ts_ns")
        require_optional_int(self.first_signal_hour_lst, "first_signal_hour_lst")
        require_optional_text(self.first_signal_state, "first_signal_state")
        require_optional_text(self.verdict_at_signal, "verdict_at_signal")
        _require_optional_decimal(self.recoverable_value_at_signal, "recoverable_value_at_signal")
        require_int(self.held_duration_ns, "held_duration_ns")
        require_int(self.total_frames, "total_frames")
        require_int(self.mark_missing_frames, "mark_missing_frames")
        _require_optional_decimal(self.settled_pnl, "settled_pnl")
        if self.settled_held is not None and not isinstance(self.settled_held, bool):
            raise TypeError(
                f"`settled_held` must be a `bool` or `None`, was "
                f"{type(self.settled_held).__name__}"
            )
        require_bool(self.monitor_intervened, "monitor_intervened")
        if self.monitor_intervened:
            raise ValueError(
                "`monitor_intervened` must be `False` for this increment -- CUT "
                "(plan Sec 2/4): no `on_position_closed` logic exists that could "
                "ever set it otherwise, so a `True` value here is a defect, not data"
            )
        require_optional_text(self.exit_rule, "exit_rule")
        require_optional_text(self.exit_decision, "exit_decision")
        require_optional_text(self.exit_reason_code, "exit_reason_code")
        _require_optional_decimal(self.exit_limit_price, "exit_limit_price")
        _require_optional_decimal(self.expected_settlement_value, "expected_settlement_value")

    def to_dict(self) -> dict[str, Any]:
        return {
            "trial_id": self.trial_id,
            "instrument_id": self.instrument_id,
            "station": self.station,
            "climate_day": self.climate_day,
            "leg": self.leg,
            "entry_context": self.entry_context,
            "monitor_seq": self.monitor_seq,
            "fill_px": str(self.fill_px),
            "held_qty": str(self.held_qty),
            "mae": str(self.mae),
            "mfe": str(self.mfe),
            "first_signal_ts_ns": self.first_signal_ts_ns,
            "first_signal_hour_lst": self.first_signal_hour_lst,
            "first_signal_state": self.first_signal_state,
            "verdict_at_signal": self.verdict_at_signal,
            "recoverable_value_at_signal": _decimal_to_str(self.recoverable_value_at_signal),
            "held_duration_ns": self.held_duration_ns,
            "total_frames": self.total_frames,
            "mark_missing_frames": self.mark_missing_frames,
            "monitor_intervened": self.monitor_intervened,
            "settled_pnl": _decimal_to_str(self.settled_pnl),
            "settled_held": self.settled_held,
            "exit_rule": self.exit_rule,
            "exit_decision": self.exit_decision,
            "exit_reason_code": self.exit_reason_code,
            "exit_limit_price": _decimal_to_str(self.exit_limit_price),
            "expected_settlement_value": _decimal_to_str(self.expected_settlement_value),
        }

    @classmethod
    def from_dict(cls, values: dict[str, Any]) -> PositionMonitorSummary:
        return cls(
            trial_id=str(values["trial_id"]),
            instrument_id=str(values["instrument_id"]),
            station=str(values["station"]),
            climate_day=str(values["climate_day"]),
            leg=str(values["leg"]),
            entry_context=str(values["entry_context"]),
            monitor_seq=int(values["monitor_seq"]),
            fill_px=Decimal(values["fill_px"]),
            held_qty=Decimal(values["held_qty"]),
            mae=Decimal(values["mae"]),
            mfe=Decimal(values["mfe"]),
            first_signal_ts_ns=(
                int(values["first_signal_ts_ns"])
                if values["first_signal_ts_ns"] is not None
                else None
            ),
            first_signal_hour_lst=(
                int(values["first_signal_hour_lst"])
                if values["first_signal_hour_lst"] is not None
                else None
            ),
            first_signal_state=(
                str(values["first_signal_state"])
                if values["first_signal_state"] is not None
                else None
            ),
            verdict_at_signal=(
                str(values["verdict_at_signal"]) if values["verdict_at_signal"] is not None
                else None
            ),
            recoverable_value_at_signal=_str_to_decimal(
                values["recoverable_value_at_signal"], "recoverable_value_at_signal"
            ),
            held_duration_ns=int(values["held_duration_ns"]),
            total_frames=int(values["total_frames"]),
            mark_missing_frames=int(values["mark_missing_frames"]),
            monitor_intervened=bool(values["monitor_intervened"]),
            settled_pnl=_str_to_decimal(values["settled_pnl"], "settled_pnl"),
            settled_held=(
                bool(values["settled_held"]) if values["settled_held"] is not None else None
            ),
            exit_rule=(
                str(values["exit_rule"]) if values.get("exit_rule") is not None else None
            ),
            exit_decision=(
                str(values["exit_decision"]) if values.get("exit_decision") is not None else None
            ),
            exit_reason_code=(
                str(values["exit_reason_code"])
                if values.get("exit_reason_code") is not None
                else None
            ),
            exit_limit_price=_str_to_decimal(
                values.get("exit_limit_price"), "exit_limit_price"
            ),
            expected_settlement_value=_str_to_decimal(
                values.get("expected_settlement_value"), "expected_settlement_value"
            ),
        )
