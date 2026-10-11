"""EXEC-PAR D-PREREG BG-1b: ingest order events into the durable per-climate-day counters.

Pure logic over an injected writer port, so it is unit-testable without a node.
The breaker watcher feeds it from its ``events.order.*`` subscription on the
loop thread (K > 1 only).

**Decision ask (spec 7 slippage).** Nothing durable carries it today: the
strategy keeps it in ``_decision_ask_by_station_day`` (memory, popped on fill)
and ``exec/client.py`` (byte-pinned) records only the fill. But every entry is
an IOC LIMIT BUY whose limit price IS the decision ask (``Take.limit_price`` is
the ask; ``_maybe_submit`` passes it unchanged to ``order_factory.limit``), and
the order sits in the Nautilus cache when ``OrderSubmitted`` is published. So
this layer persists ``order.price`` on the posted-entry anchor row. No strategy
or client edit.

**Arm time (I2).** On the create path the client reads ``now_ns`` once and uses
it for BOTH ``arm_slot(now_ns=...)`` (the slot ``created_ns``) and
``_generate_submitted(order, now_ns)``, so ``OrderSubmitted.ts_event`` equals the
slot's ``created_ns``. Every later event of the order (fill, AMBIGUOUS) takes
its day and arm time from the anchor, never from its own timestamp. Limits: a
denial has no armed slot, so it is attributed by its own event time; the
resolver's no-id ADOPT path emits a late ``OrderSubmitted``, which would carry
the adoption time rather than the arm time.

Failures are typed and loud: a missing day, arm time, ask, quantity, fee or
theta is :class:`CounterAttributionError` (never a 0 default); any store failure
is :class:`CounterWriteError` (value-free message, cause chained). Mapping a
raise to the integrity halt is BG-6's job.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from decimal import Decimal
from typing import Any, Final, Protocol

from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.events import OrderDenied, OrderFilled, OrderSubmitted

from breezy.adapters.polymarket_us.fees import taker_fee_coefficient_as_of
from breezy.adapters.polymarket_us.symbology import base_slug_of
from breezy.runtime.exec_par_records import (
    AmbiguousRow,
    DenialRow,
    FillRow,
    GappyMark,
    OpenCostFlag,
    OrderAnchor,
    WindowPeak,
)
from breezy.runtime.exec_par_telemetry import WINDOW_NS

__all__ = [
    "UNATTRIBUTED",
    "AmbiguousMarkSource",
    "CounterAttributionError",
    "CounterWriteError",
    "CounterWriterPort",
    "ExecParCounterError",
    "ExecParCounterIngest",
    "IntentView",
    "reason_label",
]

_REASON_LABEL_MAX: Final[int] = 48
_NUMBER_RE: Final[re.Pattern[str]] = re.compile(r"[0-9$.]+")
_ONE: Final[Decimal] = Decimal(1)


class ExecParCounterError(Exception):
    """Base of the typed counter-ingestion failures (messages never carry values)."""


class CounterAttributionError(ExecParCounterError):
    """An input needed to attribute or compute a counter is missing or invalid."""


class CounterWriteError(ExecParCounterError):
    """The durable store refused or failed a counter write."""


def reason_label(reason: str) -> str:
    """A bounded, number-free denial label (never a dollar value)."""
    return _NUMBER_RE.sub("#", reason.strip().lower())[:_REASON_LABEL_MAX] or "unspecified"


UNATTRIBUTED: Final[str] = "unattributed"


class AmbiguousMarkSource(Protocol):
    """Runtime-side view of the ledger's ever-ambiguous marks (value-free; no amounts)."""

    def ambiguous_marks_pending(self) -> frozenset[tuple[str, str]]: ...
    def ack_ambiguous_marks(self, marks: Iterable[tuple[str, str]]) -> None: ...


class IntentView(Protocol):
    """The read-only fields of a ``SubmitIntent`` this layer uses (no submit_intent import)."""

    @property
    def created_ns(self) -> int: ...
    @property
    def slug(self) -> str | None: ...
    @property
    def retired_ns(self) -> int | None: ...


class CounterWriterPort(Protocol):
    """The latch methods this layer uses (a subset of ``ExecParStorePort`` plus one read)."""

    def write_order_anchor(self, record: OrderAnchor) -> bool: ...
    def read_order_anchor(self, client_order_id: str) -> OrderAnchor | None: ...
    def read_intent(self, intent_id: str) -> IntentView | None: ...
    def write_denial(self, record: DenialRow) -> bool: ...
    def write_ambiguous(self, record: AmbiguousRow) -> bool: ...
    def write_fill(self, record: FillRow) -> bool: ...
    def write_open_cost_flag(self, record: OpenCostFlag) -> OpenCostFlag: ...
    def add_window_order(self, day: str, window_start_ns: int, notional: Decimal) -> WindowPeak: ...
    def write_gappy_mark(self, record: GappyMark) -> bool: ...


def _need_decimal(value: object, name: str) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise CounterAttributionError(f"{name} missing or not a finite Decimal")
    return value


def _need_positive(value: object, name: str) -> Decimal:
    number = _need_decimal(value, name)
    if number <= 0:
        raise CounterAttributionError(f"{name} must be positive")
    return number


def _need_ns(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise CounterAttributionError(f"{name} missing or not a positive int")
    return value


def _need_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise CounterAttributionError(f"{name} missing or empty")
    return value


class ExecParCounterIngest:
    """Turns order facts into exclusive, idempotent counter rows (loop thread only)."""

    def __init__(
        self,
        *,
        store: CounterWriterPort,
        climate_day_of: Callable[[str, int], str],
        theta_of: Callable[[int], Decimal | None] = taker_fee_coefficient_as_of,
        station_of: Callable[[str], str] = lambda slug: slug,
        open_cost_flag_of: Callable[[str, str], bool] | None = None,
        window_ns: int = WINDOW_NS,
    ) -> None:
        self._store = store
        self._climate_day_of = climate_day_of
        self._theta_of = theta_of
        self._station_of = station_of
        self._open_cost_flag_of = open_cost_flag_of
        self._window_ns = window_ns

    # -- helpers ----------------------------------------------------------

    def _day(self, slug: str, ns: int) -> str:
        try:
            day = self._climate_day_of(slug, ns)
        except Exception as exc:
            raise CounterAttributionError("climate day unresolved") from exc
        return _need_text(day, "climate day")

    def _write(self, action: Callable[[], Any]) -> Any:
        """Run a store action; any failure becomes the typed, value-free write error."""
        try:
            return action()
        except ExecParCounterError:
            raise
        except Exception as exc:
            raise CounterWriteError(f"counter write failed ({type(exc).__name__})") from exc

    # -- posted entries ---------------------------------------------------

    def record_posted(
        self,
        *,
        client_order_id: str,
        slug: str,
        decision_ask: Decimal | None,
        qty: Decimal | None,
        arm_ns: int | None,
    ) -> bool:
        """Persist the posted entry with its decision ask; ``True`` if newly counted."""
        coid = _need_text(client_order_id, "client order id")
        slug = _need_text(slug, "slug")
        ask = _need_positive(decision_ask, "decision ask")
        if ask > _ONE:
            raise CounterAttributionError("decision ask outside (0, 1]")
        quantity = _need_positive(qty, "quantity")
        arm = _need_ns(arm_ns, "arm time")
        day = self._day(slug, arm)
        flag = self._open_cost_flag(slug, day, arm)
        anchor = OrderAnchor(
            client_order_id=coid,
            slug=slug,
            day=day,
            arm_ns=arm,
            decision_ask=str(ask),
            qty=str(quantity),
            notional=str(ask * quantity),
            window_start_ns=arm - arm % self._window_ns,
        )
        created: bool = self._write(lambda: self._store.write_order_anchor(anchor))
        if created:
            # Windows are derivable from the anchors; a crash between the two writes
            # under-counts one window and BG-1d's rebuild recomputes it.
            self._write(
                lambda: self._store.add_window_order(day, anchor.window_start_ns, ask * quantity)
            )
        if flag is not None:
            self._write(lambda: self._store.write_open_cost_flag(flag))
        return created

    def _open_cost_flag(self, slug: str, day: str, arm_ns: int) -> OpenCostFlag | None:
        predicate = self._open_cost_flag_of
        if predicate is None:
            return None  # no seam wired: no row, never a False default
        station = self._station_of(slug)
        try:
            exceeded = predicate(station, day)
        except Exception as exc:
            raise CounterAttributionError("open-cost predicate raised") from exc
        if not isinstance(exceeded, bool):
            raise CounterAttributionError("open-cost predicate returned a non-bool")
        return OpenCostFlag(
            station_day=f"{station}@{day}", day=day, exceeded=exceeded, ts_ns=arm_ns
        )

    # -- denials, AMBIGUOUS -----------------------------------------------

    def record_denial(
        self, *, client_order_id: str, slug: str, reason: str, ts_ns: int | None
    ) -> bool:
        """A denial has no armed slot, so it is attributed by its own event time."""
        coid = _need_text(client_order_id, "client order id")
        label = _need_text(reason, "denial reason")
        when = _need_ns(ts_ns, "denial time")
        row = DenialRow(coid, label, self._day(_need_text(slug, "slug"), when), when)
        created: bool = self._write(lambda: self._store.write_denial(row))
        return created

    def ingest_ambiguous_marks(self, marks: AmbiguousMarkSource, *, now_ns: int | None) -> int:
        """Count every pending ever-AMBIGUOUS mark once; return how many were newly counted.

        Each mark is acknowledged to its source only AFTER its durable row is written, so a
        failure leaves it pending and the next tick retries. One failing mark never blocks
        the others; the first failure is raised after the pass. The row is keyed by
        ``intent_id`` (idempotent: a re-mark after a restart is not counted twice).
        """
        when = _need_ns(now_ns, "tick time")
        created = 0
        first_error: ExecParCounterError | None = None
        for mark in sorted(marks.ambiguous_marks_pending()):
            try:
                row = self._ambiguous_row(mark[0], mark[1], when)
                if self._write_ambiguous(row):
                    created += 1
                marks.ack_ambiguous_marks([mark])
            except ExecParCounterError as exc:
                first_error = first_error or exc
        if first_error is not None:
            raise first_error
        return created

    def _write_ambiguous(self, row: AmbiguousRow) -> bool:
        written: bool = self._write(lambda: self._store.write_ambiguous(row))
        return written

    def _ambiguous_row(self, intent_id: str, source: str, when: int) -> AmbiguousRow:
        try:
            intent = self._store.read_intent(intent_id)
        except Exception as exc:
            raise CounterAttributionError("slot table unreadable for attribution") from exc
        if intent is None:  # neither a slot nor history: counted, never dropped
            return AmbiguousRow(intent_id, source, UNATTRIBUTED, when, UNATTRIBUTED, when)
        kind = "slot" if intent.retired_ns is None else "history"
        slug = _need_text(intent.slug, "slot slug")
        day = self._day(slug, intent.created_ns)
        return AmbiguousRow(intent_id, source, day, intent.created_ns, kind, when)

    def _anchor(self, coid: str) -> OrderAnchor:
        anchor: OrderAnchor | None = self._write(lambda: self._store.read_order_anchor(coid))
        if anchor is None:
            raise CounterAttributionError("no posted-entry anchor (decision ask / arm time)")
        return anchor

    # -- fills ------------------------------------------------------------

    def record_fill(
        self,
        *,
        trade_id: str,
        client_order_id: str,
        qty: Decimal | None,
        px: Decimal | None,
        commission: Decimal | None,
        ts_event_ns: int | None,
    ) -> bool:
        """Slippage vs the durable decision ask, the realized fee and the unrounded exact fee."""
        trade = _need_text(trade_id, "trade id")
        quantity = _need_positive(qty, "fill quantity")
        price = _need_decimal(px, "fill price")
        if not 0 <= price <= _ONE:
            raise CounterAttributionError("fill price outside [0, 1]")
        realized = _need_decimal(commission, "realized fee")
        when = _need_ns(ts_event_ns, "fill time")
        anchor = self._anchor(_need_text(client_order_id, "client order id"))
        theta = self._theta_of(when)
        if theta is None:
            raise CounterAttributionError("fee coefficient unpinned at fill time")
        ask = Decimal(anchor.decision_ask)
        row = FillRow(
            trade_id=trade,
            client_order_id=anchor.client_order_id,
            day=anchor.day,
            arm_ns=anchor.arm_ns,
            qty=str(quantity),
            px=str(price),
            decision_ask=anchor.decision_ask,
            slippage=str(price - ask),
            fee_realized=str(realized),
            fee_exact=str(theta * quantity * price * (_ONE - price)),
            fee_theta=str(theta),
        )
        created: bool = self._write(lambda: self._store.write_fill(row))
        return created

    # -- gappy marks ------------------------------------------------------

    def mark_gappy(self, *, day: str, cause: str, ts_ns: int | None) -> bool:
        row = GappyMark(
            _need_text(day, "gappy day"),
            _need_text(cause, "gappy cause"),
            _need_ns(ts_ns, "mark time"),
            None,
        )
        created: bool = self._write(lambda: self._store.write_gappy_mark(row))
        return created

    # -- native events ----------------------------------------------------

    def on_event(self, event: object, order_of: Callable[[Any], Any]) -> None:
        """Ingest one native order event; exits and other events are ignored."""
        if isinstance(event, OrderSubmitted):
            self._on_submitted(event, order_of)
        elif isinstance(event, OrderFilled):
            self._on_filled(event)
        elif isinstance(event, OrderDenied):
            self._on_denied(event, order_of)

    @staticmethod
    def _entry_order(order_of: Callable[[Any], Any], client_order_id: Any) -> Any | None:
        """The cached order if it is an entry (BUY); ``None`` for an exit; typed fail if absent."""
        order = order_of(client_order_id)
        if order is None:
            raise CounterAttributionError("order not in the cache")
        return order if order.side == OrderSide.BUY else None

    def _on_submitted(self, event: OrderSubmitted, order_of: Callable[[Any], Any]) -> None:
        order = self._entry_order(order_of, event.client_order_id)
        if order is None:
            return
        if not order.has_price:
            raise CounterAttributionError("entry order has no limit price (decision ask)")
        self.record_posted(
            client_order_id=str(event.client_order_id),
            slug=self._slug_of(event.instrument_id),
            decision_ask=order.price.as_decimal(),
            qty=order.quantity.as_decimal(),
            arm_ns=event.ts_event,
        )

    def _on_filled(self, event: OrderFilled) -> None:
        if event.order_side != OrderSide.BUY:
            return
        self.record_fill(
            trade_id=str(event.trade_id),
            client_order_id=str(event.client_order_id),
            qty=event.last_qty.as_decimal(),
            px=event.last_px.as_decimal(),
            commission=event.commission.as_decimal(),
            ts_event_ns=event.ts_event,
        )

    def _on_denied(self, event: OrderDenied, order_of: Callable[[Any], Any]) -> None:
        if self._entry_order(order_of, event.client_order_id) is None:
            return
        self.record_denial(
            client_order_id=str(event.client_order_id),
            slug=self._slug_of(event.instrument_id),
            reason=reason_label(str(event.reason)),
            ts_ns=event.ts_event,
        )

    @staticmethod
    def _slug_of(instrument_id: Any) -> str:
        try:
            return base_slug_of(instrument_id)
        except Exception as exc:
            raise CounterAttributionError("instrument has no venue slug") from exc
