"""Two custom ``Data`` records that make the quote tape honest about itself.

Null hypothesis first -- what was checked in the installed
``nautilus-trader==1.231.0`` before either type was written:

* **Gap intervals.** ``InstrumentStatus`` carries a market-state *action* at a
  single instant, not an interval, and its ``MarketStatusAction`` enum has no
  member meaning "our recorder was disconnected" -- a venue-state field must
  not be overloaded with a recorder-state fact, or a later reader cannot tell
  a venue halt from our own outage. ``ComponentStateChanged`` is an execution
  event, carries no ``instrument_id`` and no interval. Nothing native models a
  ``(instrument, start, end)`` coverage hole. Authored.
* **Clock offset.** Grepped the installed model for a clock/latency/offset
  data type: ``MarkPriceUpdate``, ``IndexPriceUpdate``, ``FundingRateUpdate``
  are all *prices*. There is no native carrier for "host clock minus venue
  clock". Authored.

Both use the skill's PRIMARY pattern -- a hand-written ``Data`` subclass plus
exactly ONE ``register_arrow`` call -- rather than ``@customdataclass``,
because both need an explicit decoder that RAISES on a missing column.
``ParquetDataCatalog`` infers its schema from whichever fragment sorts first
and coerces every later fragment to it silently; a hand-written decoder is the
only reliable place to notice drift, and the ``@customdataclass`` injected
decoder passes missing keys through as defaults instead.

``register_arrow`` is called exactly once per class, at module scope. A second
call silently overwrites the global registry entry while leaving ``cls._schema``
untouched, producing a permanent divergence between what serializes and what
the catalog writes.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import pyarrow as pa
from nautilus_trader.core.data import Data
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.serialization.arrow.serializer import register_arrow

__all__ = [
    "DepthTruncation",
    "QuoteTapeGap",
    "VenueClockOffset",
    "VenueSettlementSnapshot",
    "resolved_gaps_by_seq",
]


class QuoteTapeGap(Data):
    """An interval during which this recorder was NOT receiving quotes.

    Written to the same catalog root as the quotes, keyed by ``instrument_id``
    so it partitions natively into ``data/custom_quote_tape_gap/<instrument_id>/``
    and joins straight onto the quote tape.

    Why it must exist on disk rather than only in a log: a reconnect drops
    quotes permanently (Polymarket.us weather markets cannot be backfilled),
    the socket replays subscriptions on recovery, and the resulting parquet is
    indistinguishable from a continuous recording. Reconnect storms plausibly
    correlate with fast-moving books -- which is to say with strike crossings,
    the exact periods the Phase 1.5 premise test measures. An analyst who
    cannot exclude contaminated intervals will silently measure a sample skewed
    toward calm periods.

    ``resolved=False`` means the gap was still open when the record was
    written, and ``ended_ns`` is then meaningless: :attr:`duration_ns` returns
    ``None`` and :meth:`covers` returns ``True`` for every later timestamp,
    because an unterminated outage contaminates everything after it. That is
    deliberately the loud answer rather than the convenient one.

    JOIN CONTRACT -- read this before filtering a tape with these rows
    ------------------------------------------------------------------
    The stream is APPEND-ONLY, so ONE outage leaves TWO rows sharing a
    ``gap_seq``: the ``resolved=False`` row written on the falling edge, and
    the ``resolved=True`` row written on recovery. The open row is never
    retracted and stays on disk forever.

    A consumer that iterates raw rows therefore inherits the open row's
    ``covers() -> True`` for all time and marks every observation after the
    first-ever reconnect as contaminated. That is SAFE but destroys the
    statistical power of the per-city / per-day breakdowns the premise test
    depends on -- the failure is silent and looks like a null result.

    The contract is: **group by**
    ``(recorder_instance_id, instrument_id, gap_seq)`` -- the sequence is per
    instrument AND per process, so it is not a key on its own -- and **prefer
    the resolved terminus**; keep the row unresolved only when no resolved row for
    that ``gap_seq`` exists, which is the genuine still-open case that MUST go
    on contaminating what follows. :func:`resolved_gaps_by_seq` implements
    exactly this and is the supported entry point; it is order-independent,
    because catalog row order is not guaranteed. Pinned by
    ``tests/unit/test_quote_tape_consumer_contract.py::TestGapJoinContract``.

    ``gap_seq`` is per-instrument and per-PROCESS: it restarts at 1 on
    recorder restart. That is why every row carries
    :attr:`recorder_instance_id` -- the NATIVE Nautilus node ``instance_id``
    (``system/config.py:108`` -> ``system/kernel.py:160``), which is also the
    name of the streaming directory the row lands in
    (``system/kernel.py:589``), so the two agree by construction rather than
    by convention.

    Without it the merge hazard runs the UNSAFE way: a second instance's
    ``seq=1`` overwrites a genuine still-open outage from the first, the real
    contamination vanishes from the result, and the consumer UNDER-excludes --
    a bias toward a false GO. Loader-side partitioning can be tightened later;
    the field could not be added later, because a row without it is
    unpartitionable forever.
    """

    def __init__(
        self,
        instrument_id: InstrumentId,
        gap_seq: int,
        started_ns: int,
        ended_ns: int,
        resolved: bool,
        recorder_instance_id: str,
        ts_event: int,
        ts_init: int,
    ) -> None:
        if resolved and ended_ns < started_ns:
            raise ValueError(
                f"ended_ns {ended_ns} precedes started_ns {started_ns}; a gap "
                "cannot close before it opened"
            )
        # Refused rather than defaulted. A row that CLAIMS to be identifiable
        # but is not is worse than one that raises: a loader would partition on
        # `""` and reproduce the exact cross-restart collision this field
        # exists to prevent, silently and in the unsafe direction.
        if not recorder_instance_id.strip():
            raise ValueError("recorder_instance_id must be a non-blank recorder identity")
        self.instrument_id = instrument_id
        self.gap_seq = gap_seq
        self.started_ns = started_ns
        self.ended_ns = ended_ns
        self.resolved = resolved
        self.recorder_instance_id = recorder_instance_id
        self._ts_event = ts_event
        self._ts_init = ts_init

    @property
    def ts_event(self) -> int:
        return self._ts_event

    @property
    def ts_init(self) -> int:
        return self._ts_init

    @property
    def duration_ns(self) -> int | None:
        """Nanoseconds of missing quotes, or ``None`` while the gap is open."""
        if not self.resolved:
            return None
        return self.ended_ns - self.started_ns

    def covers(self, ts_ns: int) -> bool:
        """True when ``ts_ns`` falls inside this outage. Inclusive at both ends."""
        if ts_ns < self.started_ns:
            return False
        if not self.resolved:
            return True
        return ts_ns <= self.ended_ns

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(instrument_id={self.instrument_id}, "
            f"gap_seq={self.gap_seq}, started_ns={self.started_ns}, "
            f"ended_ns={self.ended_ns}, resolved={self.resolved}, "
            f"recorder_instance_id={self.recorder_instance_id!r})"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "instrument_id": self.instrument_id.value,
            "gap_seq": self.gap_seq,
            "started_ns": self.started_ns,
            "ended_ns": self.ended_ns,
            "resolved": self.resolved,
            "recorder_instance_id": self.recorder_instance_id,
            "ts_event": self._ts_event,
            "ts_init": self._ts_init,
        }

    @classmethod
    def from_dict(cls, values: dict[str, Any]) -> QuoteTapeGap:
        """Raise on a missing column rather than substituting a default.

        The only reliable schema-drift detection point -- see the module
        docstring. ``values[...]`` is used deliberately in place of ``.get``.
        """
        return cls(
            instrument_id=InstrumentId.from_str(values["instrument_id"]),
            gap_seq=int(values["gap_seq"]),
            started_ns=int(values["started_ns"]),
            ended_ns=int(values["ended_ns"]),
            resolved=bool(values["resolved"]),
            recorder_instance_id=str(values["recorder_instance_id"]),
            ts_event=int(values["ts_event"]),
            ts_init=int(values["ts_init"]),
        )

    @classmethod
    def schema(cls) -> pa.Schema:
        return pa.schema(
            [
                pa.field("instrument_id", pa.string(), nullable=False),
                pa.field("gap_seq", pa.int64(), nullable=False),
                pa.field("started_ns", pa.uint64(), nullable=False),
                pa.field("ended_ns", pa.uint64(), nullable=False),
                pa.field("resolved", pa.bool_(), nullable=False),
                # The native Nautilus node `instance_id` that produced this
                # row. `gap_seq` restarts at 1 per process, so this column is
                # what makes rows from two instance directories mergeable.
                pa.field("recorder_instance_id", pa.string(), nullable=False),
                pa.field("ts_event", pa.uint64(), nullable=False),
                pa.field("ts_init", pa.uint64(), nullable=False),
            ]
        )


class VenueClockOffset(Data):
    """Host clock minus venue clock, sampled over time.

    The read-only auth smoke recorded a ~131 second host offset against the
    venue. ``QuoteTick.ts_event`` carries the venue's ``transactTime`` and
    ``ts_init`` carries host receipt time, so every frame is itself a sample of
    the difference -- but only a recorded series lets the two clocks be
    reconciled after the fact, and only then can a crossing-time join computed
    against host-stamped weather data be trusted.

    Deliberately derived from frames already on the wire rather than from a
    fresh HTTP request: the market-data client holds no HTTP client by
    construction, and adding one to sample a clock would widen the read-only
    surface for an observation the socket already provides.

    ``offset_ns`` is signed: negative means the host clock is BEHIND the venue.
    It is a running measure over ``samples`` frames, not a single reading.
    """

    def __init__(
        self,
        source: str,
        offset_ns: int,
        samples: int,
        ts_event: int,
        ts_init: int,
    ) -> None:
        self.source = source
        self.offset_ns = offset_ns
        self.samples = samples
        self._ts_event = ts_event
        self._ts_init = ts_init

    @property
    def ts_event(self) -> int:
        return self._ts_event

    @property
    def ts_init(self) -> int:
        return self._ts_init

    @property
    def offset_seconds(self) -> float:
        """Convenience for humans reading an alert. Never used for arithmetic on disk."""
        return self.offset_ns / 1_000_000_000

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(source={self.source!r}, "
            f"offset_ns={self.offset_ns}, samples={self.samples})"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "offset_ns": self.offset_ns,
            "samples": self.samples,
            "ts_event": self._ts_event,
            "ts_init": self._ts_init,
        }

    @classmethod
    def from_dict(cls, values: dict[str, Any]) -> VenueClockOffset:
        return cls(
            source=str(values["source"]),
            offset_ns=int(values["offset_ns"]),
            samples=int(values["samples"]),
            ts_event=int(values["ts_event"]),
            ts_init=int(values["ts_init"]),
        )

    @classmethod
    def schema(cls) -> pa.Schema:
        return pa.schema(
            [
                pa.field("source", pa.string(), nullable=False),
                # SIGNED: the host can be behind or ahead of the venue.
                pa.field("offset_ns", pa.int64(), nullable=False),
                pa.field("samples", pa.int64(), nullable=False),
                pa.field("ts_event", pa.uint64(), nullable=False),
                pa.field("ts_init", pa.uint64(), nullable=False),
            ]
        )


class VenueSettlementSnapshot(Data):
    """The venue's settlement fields, VERBATIM, from one frame.

    ``settlementPx`` appears on live AND expired markets and means different
    things in each; the venue itself distinguishes the regimes with
    ``settlementPriceCalculationMethod``. Native Nautilus carriers cannot hold
    that distinction: ``MarkPriceUpdate`` and ``InstrumentClose`` are compiled
    Cython types with a price and nothing else -- no free-text field like the
    ``reason`` slot that lets ``InstrumentStatus`` carry the raw ``state``
    string. So the provenance is recorded here, next to them.

    Everything is stored as the venue spelled it:

    * ``settlement_px`` is the venue's own STRING (``"1.0000"``, four decimal
      places), not a value re-rendered at the instrument's precision. The
      number the whole system treats as settlement truth should not silently
      acquire our formatting.
    * ``method`` and ``state`` are raw enum strings. Only two method values
      have ever been observed, so this type takes no position on the rest --
      a later reader can re-derive the judgement instead of inheriting ours.

    ``is_terminal`` is the derived judgement, recorded ALONGSIDE its inputs
    rather than instead of them, so a future correction to the rule can be
    applied to the archive retrospectively.

    THREE clocks, all kept, because a disputed settlement needs all three:

    * ``ts_event`` -- the venue's ``settlementSetTime``: when it COMPUTED the
      price.
    * ``venue_transact_time_ns`` -- the frame's own ``transactTime``: when it
      TOLD us. In the committed captures these differ by HOURS, so disclosure
      lag is a real quantity and not a rounding artefact.
    * ``ts_init`` -- when this recorder received it.

    Collapsing any two would make a dispute unanswerable, and the frame is
    gone once it is off the wire.
    """

    def __init__(
        self,
        instrument_id: InstrumentId,
        state: str,
        method: str,
        settlement_px: str,
        is_terminal: bool,
        venue_transact_time_ns: int,
        ts_event: int,
        ts_init: int,
    ) -> None:
        self.instrument_id = instrument_id
        self.state = state
        self.method = method
        self.settlement_px = settlement_px
        self.is_terminal = is_terminal
        self.venue_transact_time_ns = venue_transact_time_ns
        self._ts_event = ts_event
        self._ts_init = ts_init

    @property
    def ts_event(self) -> int:
        return self._ts_event

    @property
    def ts_init(self) -> int:
        return self._ts_init

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(instrument_id={self.instrument_id}, "
            f"state={self.state!r}, method={self.method!r}, "
            f"settlement_px={self.settlement_px!r}, is_terminal={self.is_terminal}, "
            f"venue_transact_time_ns={self.venue_transact_time_ns})"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "instrument_id": self.instrument_id.value,
            "state": self.state,
            "method": self.method,
            "settlement_px": self.settlement_px,
            "is_terminal": self.is_terminal,
            "venue_transact_time_ns": self.venue_transact_time_ns,
            "ts_event": self._ts_event,
            "ts_init": self._ts_init,
        }

    @classmethod
    def from_dict(cls, values: dict[str, Any]) -> VenueSettlementSnapshot:
        return cls(
            instrument_id=InstrumentId.from_str(values["instrument_id"]),
            state=str(values["state"]),
            method=str(values["method"]),
            settlement_px=str(values["settlement_px"]),
            is_terminal=bool(values["is_terminal"]),
            venue_transact_time_ns=int(values["venue_transact_time_ns"]),
            ts_event=int(values["ts_event"]),
            ts_init=int(values["ts_init"]),
        )

    @classmethod
    def schema(cls) -> pa.Schema:
        return pa.schema(
            [
                pa.field("instrument_id", pa.string(), nullable=False),
                pa.field("state", pa.string(), nullable=False),
                pa.field("method", pa.string(), nullable=False),
                # STRING, deliberately: the venue's own spelling, not a float
                # and not a value re-rendered at our precision.
                pa.field("settlement_px", pa.string(), nullable=False),
                pa.field("is_terminal", pa.bool_(), nullable=False),
                # The frame's own `transactTime`: when the venue DISCLOSED the
                # price, as distinct from `ts_event` (when it computed it).
                pa.field("venue_transact_time_ns", pa.uint64(), nullable=False),
                pa.field("ts_event", pa.uint64(), nullable=False),
                pa.field("ts_init", pa.uint64(), nullable=False),
            ]
        )


class DepthTruncation(Data):
    """How much of one depth snapshot did not fit in ``OrderBookDepth10``.

    ``OrderBookDepth10`` carries exactly ten levels per side and the committed
    capture has 12 bids and 14 offers, so truncation is routine. A running
    counter in process memory cannot answer the question an analyst actually
    asks: *was THIS snapshot, the one next to my crossing event, truncated?*
    Runtime logs may not survive to the study; the archive does.

    Emitted only when something was actually dropped, and stamped with the
    SAME ``ts_event`` as the depth record it describes, so the join is exact
    rather than nearest-neighbour.

    Deliberately its own record rather than a value stuffed into
    ``OrderBookDepth10.flags``: that field is a Nautilus-defined bitfield with
    documented meanings, and overloading it would make Breezy's tape misread by
    any standard Nautilus consumer.
    """

    def __init__(
        self,
        instrument_id: InstrumentId,
        bid_levels_seen: int,
        ask_levels_seen: int,
        levels_dropped: int,
        ts_event: int,
        ts_init: int,
    ) -> None:
        self.instrument_id = instrument_id
        self.bid_levels_seen = bid_levels_seen
        self.ask_levels_seen = ask_levels_seen
        self.levels_dropped = levels_dropped
        self._ts_event = ts_event
        self._ts_init = ts_init

    @property
    def ts_event(self) -> int:
        return self._ts_event

    @property
    def ts_init(self) -> int:
        return self._ts_init

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(instrument_id={self.instrument_id}, "
            f"bid_levels_seen={self.bid_levels_seen}, "
            f"ask_levels_seen={self.ask_levels_seen}, "
            f"levels_dropped={self.levels_dropped})"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "instrument_id": self.instrument_id.value,
            "bid_levels_seen": self.bid_levels_seen,
            "ask_levels_seen": self.ask_levels_seen,
            "levels_dropped": self.levels_dropped,
            "ts_event": self._ts_event,
            "ts_init": self._ts_init,
        }

    @classmethod
    def from_dict(cls, values: dict[str, Any]) -> DepthTruncation:
        return cls(
            instrument_id=InstrumentId.from_str(values["instrument_id"]),
            bid_levels_seen=int(values["bid_levels_seen"]),
            ask_levels_seen=int(values["ask_levels_seen"]),
            levels_dropped=int(values["levels_dropped"]),
            ts_event=int(values["ts_event"]),
            ts_init=int(values["ts_init"]),
        )

    @classmethod
    def schema(cls) -> pa.Schema:
        return pa.schema(
            [
                pa.field("instrument_id", pa.string(), nullable=False),
                pa.field("bid_levels_seen", pa.int64(), nullable=False),
                pa.field("ask_levels_seen", pa.int64(), nullable=False),
                pa.field("levels_dropped", pa.int64(), nullable=False),
                pa.field("ts_event", pa.uint64(), nullable=False),
                pa.field("ts_init", pa.uint64(), nullable=False),
            ]
        )


def resolved_gaps_by_seq(gaps: Iterable[QuoteTapeGap]) -> list[QuoteTapeGap]:
    """Collapse raw gap rows to ONE row per outage, preferring the resolved one.

    **The join contract, in executable form.** Both edges of an outage persist
    as separate permanent rows sharing a ``gap_seq``; the ``resolved=False``
    row is never superseded on disk when its ``resolved=True`` partner arrives,
    because the tape is append-only by construction. A consumer that iterates
    every row and calls :meth:`QuoteTapeGap.covers` will therefore treat
    EVERYTHING after the first-ever reconnect as contaminated -- the open row
    covers all later timestamps forever, by design.

    That errs safe (over-exclusion, never a false GO) but it silently destroys
    statistical power in the per-city and per-day breakdowns. Every consumer of
    the gap dataset should pass its rows through this function first.

    Keyed on ``(recorder_instance_id, instrument_id, gap_seq)``, NOT on
    ``gap_seq`` alone. The sequence restarts at 1 for every market a recorder
    follows AND for every recorder process, so on its own it is not a key in
    either dimension:

    * Cross-INSTRUMENT collision would drop one city's outage and stamp
      another city's boundaries onto it.
    * Cross-RESTART collision is worse, because it fails UNSAFE: a new
      instance's ``seq=1`` would overwrite a genuine still-open outage from
      the prior instance, the real contamination would vanish from the result,
      and the consumer would UNDER-exclude -- a bias toward a false GO.

    Ordering is by the full key, so the result is stable regardless of the
    order the catalog returns rows in.
    """
    latest: dict[tuple[str, str, int], QuoteTapeGap] = {}
    for gap in gaps:
        key = (gap.recorder_instance_id, gap.instrument_id.value, gap.gap_seq)
        existing = latest.get(key)
        if existing is None or (gap.resolved and not existing.resolved):
            latest[key] = gap
    return [latest[key] for key in sorted(latest)]


def _encode_gaps(data: QuoteTapeGap | list[QuoteTapeGap]) -> pa.RecordBatch:
    """Accept ONE object or a list.

    Both call shapes occur in 1.231.0: ``ArrowSerializer.serialize`` passes a
    single object (``serialization/arrow/serializer.py:249``, the path the
    streaming writer takes) while ``ParquetDataCatalog.write_data`` passes a
    list. An encoder written for only one of them fails at the other call site.
    """
    items = data if isinstance(data, list) else [data]
    return pa.RecordBatch.from_pylist(
        [item.to_dict() for item in items], schema=QuoteTapeGap.schema()
    )


def _decode_gaps(table: pa.Table) -> list[QuoteTapeGap]:
    return [QuoteTapeGap.from_dict(row) for row in table.to_pylist()]


def _encode_offsets(data: VenueClockOffset | list[VenueClockOffset]) -> pa.RecordBatch:
    items = data if isinstance(data, list) else [data]
    return pa.RecordBatch.from_pylist(
        [item.to_dict() for item in items], schema=VenueClockOffset.schema()
    )


def _decode_offsets(table: pa.Table) -> list[VenueClockOffset]:
    return [VenueClockOffset.from_dict(row) for row in table.to_pylist()]


def _encode_snapshots(
    data: VenueSettlementSnapshot | list[VenueSettlementSnapshot],
) -> pa.RecordBatch:
    items = data if isinstance(data, list) else [data]
    return pa.RecordBatch.from_pylist(
        [item.to_dict() for item in items], schema=VenueSettlementSnapshot.schema()
    )


def _decode_snapshots(table: pa.Table) -> list[VenueSettlementSnapshot]:
    return [VenueSettlementSnapshot.from_dict(row) for row in table.to_pylist()]


def _encode_truncations(data: DepthTruncation | list[DepthTruncation]) -> pa.RecordBatch:
    items = data if isinstance(data, list) else [data]
    return pa.RecordBatch.from_pylist(
        [item.to_dict() for item in items], schema=DepthTruncation.schema()
    )


def _decode_truncations(table: pa.Table) -> list[DepthTruncation]:
    return [DepthTruncation.from_dict(row) for row in table.to_pylist()]


# Exactly once per class, at module scope. See the module docstring.
register_arrow(QuoteTapeGap, QuoteTapeGap.schema(), _encode_gaps, _decode_gaps)
register_arrow(VenueClockOffset, VenueClockOffset.schema(), _encode_offsets, _decode_offsets)
register_arrow(
    VenueSettlementSnapshot,
    VenueSettlementSnapshot.schema(),
    _encode_snapshots,
    _decode_snapshots,
)
register_arrow(
    DepthTruncation, DepthTruncation.schema(), _encode_truncations, _decode_truncations
)
