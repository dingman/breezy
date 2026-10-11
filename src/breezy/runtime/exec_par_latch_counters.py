"""Single-writer EXEC-PAR D-PREREG per-climate-day COUNTER rows for ``SubmitIntentLatch`` (BG-1b).

Event-sourced rows, one key per event id, so a replayed event is an idempotent
no-op and a conflicting one raises (never an overwrite). The per-day counters
(posted, AMBIGUOUS, denials by reason, fills, fees, slippage, 5 s window peaks)
are scan-based aggregates of these rows; there is no running total to drift and
no ``latest`` pointer. The same discipline as :mod:`exec_par_latch_records`:
``_require_held()`` first, ``_mutex`` taken once per public method, a garbled or
mis-keyed row raises the latch's ``CorruptError`` (never a default).

Key layout and shapes: :mod:`breezy.runtime.exec_par_records`. ``day`` is the
climate-day label of the ARM time (I2); this layer stores it, the ingest layer
(:mod:`breezy.runtime.exec_par_counter_ingest`) computes it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from decimal import Decimal, InvalidOperation
from typing import TypeVar

from breezy.runtime.exec_par_latch_records import ExecParRecordsMixin
from breezy.runtime.exec_par_records import (
    EXEC_PAR_PREFIX,
    AmbiguousRow,
    DenialRow,
    FillRow,
    GappyMark,
    OpenCostFlag,
    OrderAnchor,
    WindowPeak,
)

T = TypeVar("T")

_ORDER = EXEC_PAR_PREFIX + "order/"
_DENIAL = EXEC_PAR_PREFIX + "denial/"
_AMBIGUOUS = EXEC_PAR_PREFIX + "ambiguous/"
_FILL = EXEC_PAR_PREFIX + "fill/"
_OPEN_FLAG = EXEC_PAR_PREFIX + "openflag/"
_WINDOW = EXEC_PAR_PREFIX + "window/"
_GAPPY = EXEC_PAR_PREFIX + "gappy/"


def _part(value: object) -> str:
    """A key component: non-empty printable text with no separator or whitespace."""
    if (
        not isinstance(value, str)
        or not value
        or "/" in value
        or not value.isprintable()
        or any(ch.isspace() for ch in value)
    ):
        raise ValueError("invalid EXEC-PAR counter key component")
    return value


def _decimal(text: str) -> Decimal:
    try:
        value = Decimal(text)
    except InvalidOperation:
        raise ValueError("invalid decimal") from None
    if not value.is_finite():
        raise ValueError("invalid decimal")
    return value


class ExecParCounterRowsMixin(ExecParRecordsMixin):
    """Counter-row writers and readers; the host supplies the mixin attributes."""

    def _ec_scan(
        self, prefix: str, cls: type[T], id_of: Callable[[T], str], day: str | None
    ) -> tuple[T, ...]:
        """Rows under ``prefix`` (key suffix must equal the row's id), optionally of one day."""
        lister = getattr(self._store, "keys_with_prefix", None)
        if lister is None:
            raise RuntimeError("store has no keys_with_prefix; cannot scan EXEC-PAR rows")
        rows: list[T] = []
        for key in lister(prefix):
            row = self._er_get(key, cls)
            if row is None or key[len(prefix) :] != id_of(row):
                raise self.CorruptError()
            if day is None or getattr(row, "day", None) == day:
                rows.append(row)
        return tuple(sorted(rows, key=id_of))

    # -- posted entries (carry the durable decision ask) ------------------

    def write_order_anchor(self, record: OrderAnchor) -> bool:
        """``True`` if newly written; identical replay ``False``; a different row raises."""
        self._require_held()
        key = _ORDER + _part(record.client_order_id)
        with self._mutex:
            return self._er_put_exclusive(key, record)

    def read_order_anchor(self, client_order_id: str) -> OrderAnchor | None:
        self._require_held()
        key = _ORDER + _part(client_order_id)
        with self._mutex:
            return self._er_get(key, OrderAnchor)

    def read_order_anchors(self, day: str) -> tuple[OrderAnchor, ...]:
        self._require_held()
        _part(day)
        with self._mutex:
            return self._ec_scan(_ORDER, OrderAnchor, lambda r: r.client_order_id, day)

    # -- denials, AMBIGUOUS, fills ----------------------------------------

    def write_denial(self, record: DenialRow) -> bool:
        self._require_held()
        key = _DENIAL + _part(record.client_order_id)
        with self._mutex:
            return self._er_put_exclusive(key, record)

    def read_denials(self, day: str) -> tuple[DenialRow, ...]:
        self._require_held()
        _part(day)
        with self._mutex:
            return self._ec_scan(_DENIAL, DenialRow, lambda r: r.client_order_id, day)

    def write_ambiguous(self, record: AmbiguousRow) -> bool:
        """First detection wins: a later row for the same order is a ``False`` no-op."""
        self._require_held()
        key = _AMBIGUOUS + _part(record.client_order_id)
        with self._mutex:
            if self._store.get(key) is not None:
                self._er_get(key, AmbiguousRow)  # a garbled existing row still raises
                return False
            return self._er_put_exclusive(key, record)

    def read_ambiguous(self, day: str) -> tuple[AmbiguousRow, ...]:
        self._require_held()
        _part(day)
        with self._mutex:
            return self._ec_scan(_AMBIGUOUS, AmbiguousRow, lambda r: r.client_order_id, day)

    def write_fill(self, record: FillRow) -> bool:
        self._require_held()
        key = _FILL + _part(record.trade_id)
        with self._mutex:
            return self._er_put_exclusive(key, record)

    def read_fills(self, day: str) -> tuple[FillRow, ...]:
        self._require_held()
        _part(day)
        with self._mutex:
            return self._ec_scan(_FILL, FillRow, lambda r: r.trade_id, day)

    # -- open-cost fraction flag (value-free; BG-1e predicates supply it) -

    def write_open_cost_flag(self, record: OpenCostFlag) -> OpenCostFlag:
        """Monotone within a station-day: once ``exceeded`` it never reads False again."""
        self._require_held()
        key = _OPEN_FLAG + _part(record.station_day)
        with self._mutex:
            existing = self._er_get(key, OpenCostFlag)
            merged = record
            if existing is not None and existing.exceeded:
                merged = replace(record, exceeded=True, ts_ns=existing.ts_ns)
            if existing != merged:
                self._er_put(key, merged)
            return merged

    def read_open_cost_flags(self, day: str) -> tuple[OpenCostFlag, ...]:
        self._require_held()
        _part(day)
        with self._mutex:
            return self._ec_scan(_OPEN_FLAG, OpenCostFlag, lambda r: r.station_day, day)

    # -- 5 s window peaks ---------------------------------------------------

    def add_window_order(self, day: str, window_start_ns: int, notional: Decimal) -> WindowPeak:
        """Count one entry (and its notional) into its fixed 5 s window; one call, one lock."""
        self._require_held()
        if not isinstance(notional, Decimal) or not notional.is_finite() or notional < 0:
            raise ValueError("window notional must be a finite non-negative Decimal")
        key = f"{_WINDOW}{_part(day)}/{window_start_ns}"
        with self._mutex:
            existing = self._er_get(key, WindowPeak)
            if existing is None:
                row = WindowPeak(day, window_start_ns, 1, str(notional))
            else:
                total = _decimal(existing.notional) + notional
                row = replace(existing, orders=existing.orders + 1, notional=str(total))
            self._er_put(key, row)
            return row

    def read_window_peaks(self, day: str) -> tuple[WindowPeak, ...]:
        """Every window of ``day`` ascending by start; the peak is the caller's ``max``."""
        self._require_held()
        prefix = f"{_WINDOW}{_part(day)}/"
        with self._mutex:
            rows = self._ec_scan(prefix, WindowPeak, lambda r: str(r.window_start_ns), None)
        if any(r.day != day for r in rows):
            raise self.CorruptError()
        return tuple(sorted(rows, key=lambda r: r.window_start_ns))

    # -- gappy-day marks (clearing is BG-1d) --------------------------------

    def write_gappy_mark(self, record: GappyMark) -> bool:
        """First mark of a day wins; a later one is a ``False`` no-op."""
        self._require_held()
        key = _GAPPY + _part(record.day)
        with self._mutex:
            if self._store.get(key) is not None:
                self._er_get(key, GappyMark)
                return False
            return self._er_put_exclusive(key, record)

    def read_gappy_marks(self) -> tuple[GappyMark, ...]:
        self._require_held()
        with self._mutex:
            return self._ec_scan(_GAPPY, GappyMark, lambda r: r.day, None)
