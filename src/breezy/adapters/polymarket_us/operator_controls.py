(
    """The two operator-reserved controls, as MECHANISM ONLY (EXEC SPINE R-6e).

WHAT THIS MODULE IS
-------------------

Two controls, and only the operator sets them:

* :data:`MAX_DAILY_BUDGET_USD_ENV_VAR` -- a rolling **calendar-day USD
  notional** ceiling, accumulated across every order the process authorises in
  one day.
* :data:`MAX_POSITION_COST_USD_ENV_VAR` -- a per-position ceiling whose unit is
  **USD cost, not contracts**. On a long-only binary book the maximum loss on a
  position IS its premium: ``price x quantity``. Contracts are the wrong unit
  for a loss ceiling because the same 250 contracts cost $12.50 at $0.05 and
  $237.50 at $0.95.

**This is NOT** :attr:`breezy.strategy.weather_common.risk.RiskLimits.
max_position_contracts`. That is a per-strategy sizing tunable in CONTRACTS,
carried in a config object, and nothing here reads, widens or replaces it.

THE ARRIVAL PATH, AND THE ONE RULE
----------------------------------

The operator exports both variables in the shell that launches
``breezy-trade``. **No value for either control is assigned anywhere in this
repository** -- not in ``src/``, ``scripts/``, ``tests/``, a fixture, a
``conftest``, a committed ``.env``, a systemd unit, a default argument, or an
``os.environ.get(NAME, <fallback>)``. That is not a convention: it is scanned
and proven by ``tests/unit/test_operator_control_assignment_scan.py``, whose
non-vacuity is demonstrated by planting the assignment forms it must catch.

Half of that was already true and is cited rather than re-implemented:
``test_no_shipped_code_can_set_the_operator_trading_gate``
(``tests/unit/test_polymarket_us_permit_issuance.py``) already bans EVERY
environment write from ``src/`` and ``scripts/``, name-agnostic, plus
``load_dotenv``/``putenv``/``unsetenv``. What R-6e adds is the ``tests/`` half
-- where a default actually creeps in, as a fixture -- and the READ-with-a-
default form, which that scan passes untouched because it is not a write.

**Absence FAILS CLOSED.** Both controls are read on EVERY authorisation, so
with either unset every order is refused, forever, with no cached grant to go
stale. The refusal names the missing control and NEVER its value -- the
precedent is ``safety._refuse``, which emits only ``type(value).__name__``.

WHY THERE IS NO NEW READ MECHANISM
----------------------------------

``safety._require_operator_value`` already reads an operator value from the
environment and refuses on absence or blankness, and
``safety._read_operator_money`` layers the USD form check, the decimal parse
and the positivity check on top of it -- calling it, so there is still exactly
ONE reader and ONE refusal policy for every operator control in this package.
Both controls are USD amounts, so they are read through that same function.
Building a second reader would fork the refusal policy, which is the defect
that function exists to prevent.

WHICH CALENDAR DAY -- and it is not the climate day
---------------------------------------------------

**UTC.** The repo already has exactly one PROCESS-WIDE day boundary and it is
midnight UTC: the quote tape rotates ``SCHEDULED_DATES`` daily at
``QUOTE_TAPE_ROTATION_TIME = 00:00:00`` in ``QUOTE_TAPE_ROTATION_TIMEZONE =
"UTC"`` (``breezy/runtime/node_config.py``), whose own comment states the
reason: *"DAILY in UTC because the study's unit of analysis is a market-day."*
A day's spending and a day's tape therefore cover the same window, so an
operator reconciling "what did it spend on 2026-09-02" reads one file set.

The repo's OTHER day -- the **climate day** (``normalize/climate_day.py``:
local-STANDARD-time midnight to midnight, per site) -- is deliberately NOT used
here, and the reason is structural rather than aesthetic: it is a **per-site**
window. New York, Chicago and Los Angeles roll over at three different
instants, so a portfolio-wide accumulator keyed on it would have no single
"today" at all -- it would either need N ledgers (N budgets, which is not the
control the operator set) or an arbitrary choice of one site's clock to govern
spending on all the others. Settlement is per-site; money is not.

No fourth day is invented, and no wall clock is sampled here: ``now_ns`` is
always supplied by the caller from the injected Nautilus clock, exactly as
``safety`` does it, which is what makes the day boundary testable without
sleeping.

ZERO PRODUCTION CALL SITES, DELIBERATELY
----------------------------------------

This ships as a library with no caller, the same shape R-4's chokepoint and
R-6d's refusal classifier landed in. The consumer is the R-7 submit path,
which does not exist yet; pre-wiring it into ``exec/client.py`` now would put
an order-path change inside an increment whose whole subject is a policy
mechanism, and R-4's standing refusal keeps that path closed regardless.

THE FEE FLOOR, AND WHY THIS CAP IS PRE-FEE
------------------------------------------

"""
    "R-8 does not proceed until the venue's minimum taker fee is measured and "
    "`fees.py` models it; until then the per-position cost control "
    "(`operator_max_position_cost_usd()`) is cost-BEFORE-fee and the operator "
    "sizes accordingly."
)

from __future__ import annotations

import itertools
import threading
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import ROUND_UP, Decimal
from typing import Final

from breezy.adapters.polymarket_us.safety import (
    LiveTradingPermissionError,
    _read_operator_money,
)

#: The operator's rolling calendar-day (UTC) ceiling on USD notional spent.
#: Operator-reserved: this repo never assigns it a value.
MAX_DAILY_BUDGET_USD_ENV_VAR: Final = "BREEZY_MAX_DAILY_BUDGET_USD"

#: The operator's ceiling on the USD COST of one position -- premium, i.e.
#: ``price x quantity``, which on a long-only binary book is the maximum loss.
#: Operator-reserved: this repo never assigns it a value.
MAX_POSITION_COST_USD_ENV_VAR: Final = "BREEZY_MAX_POSITION_COST_USD"

#: The complete inventory of operator-reserved controls introduced by R-6e.
#: The assignment scan derives its search tokens from THIS tuple, so a third
#: control added here is covered by the scan without editing the scan.
OPERATOR_RESERVED_CONTROL_ENV_VARS: Final = (
    MAX_DAILY_BUDGET_USD_ENV_VAR,
    MAX_POSITION_COST_USD_ENV_VAR,
)

#: USD are quantised to the cent, and costs round UP: a fraction of a cent of
#: premium consumes a whole cent of the operator's budget. That is the
#: conservative direction -- the ledger can only ever over-count what was
#: spent, never under-count it.
_CENT: Final = Decimal("0.01")

_NS_PER_SECOND: Final = 1_000_000_000

#: Process-wide monotonic booking ids so two ledgers cannot collide on the
#: same ``(cost, day, booking_id)`` triple. Incremented under the issuing
#: ledger's lock; ``count.__next__`` is atomic under the GIL besides.
_BOOKING_IDS = itertools.count(1)


def operator_max_daily_budget_usd() -> Decimal:
    """The operator's calendar-day USD notional ceiling.

    Read through ``safety._read_operator_money`` -- which calls
    ``safety._require_operator_value`` -- so absence, blankness, malformation
    and non-positivity all raise here and NOTHING defaults.

    Raises:
        LiveTradingPermissionError: naming the control, never its value.
    """
    return _read_operator_money(MAX_DAILY_BUDGET_USD_ENV_VAR)


def operator_max_position_cost_usd() -> Decimal:
    """The operator's per-position USD COST ceiling (premium, not contracts).

    Raises:
        LiveTradingPermissionError: naming the control, never its value.
    """
    return _read_operator_money(MAX_POSITION_COST_USD_ENV_VAR)


def utc_day_for_ns(now_ns: int) -> date:
    """The UTC calendar day containing ``now_ns``.

    Integer seconds, never a float: ``now_ns / 1e9`` loses nanosecond
    resolution above 2^53 ns (2255-06-05) and, more immediately, is the float
    money/time idiom this repo bans on the execution path.
    """
    if type(now_ns) is not int:
        raise LiveTradingPermissionError(
            f"now_ns must be exactly int, not {type(now_ns).__name__}; the day boundary "
            f"is never derived from a float"
        )
    if now_ns <= 0:
        raise LiveTradingPermissionError(
            "now_ns must be a positive number of nanoseconds from the injected clock"
        )
    return datetime.fromtimestamp(now_ns // _NS_PER_SECOND, UTC).date()


def _require_decimal(value: object, label: str) -> Decimal:
    """Refuse anything that is not exactly a ``Decimal``, naming only its TYPE.

    ``type(x) is Decimal`` rather than ``isinstance``: the same reasoning as
    ``safety._enc_decimal``. A subclass can lie in ``__str__`` and in
    comparison, and a ``float`` here would silently reintroduce binary
    rounding into a money ceiling.
    """
    if type(value) is not Decimal:
        raise LiveTradingPermissionError(
            f"{label} must be exactly Decimal, not {type(value).__name__}"
        )
    if not value.is_finite():
        raise LiveTradingPermissionError(f"{label} must be a finite decimal amount")
    if value <= Decimal(0):
        raise LiveTradingPermissionError(f"{label} must be greater than zero")
    return value


def _round_cost_up_to_cent(amount: Decimal) -> Decimal:
    """Quantise a USD amount UP to the cent.

    Shared by :func:`order_cost_usd` (the cap) and
    :meth:`DailySpendLedger.true_up_booking` so a true-up cannot round
    differently from an authorisation.
    """
    return amount.quantize(_CENT, rounding=ROUND_UP)


def order_cost_usd(*, price_usd: Decimal, quantity: Decimal) -> Decimal:
    """The USD cost of an order: ``price x quantity``, rounded UP to the cent.

    This is the max-loss unit for a long-only binary book (L-2): the premium
    paid IS everything at risk, because the contract cannot settle below zero
    and ``allow_short`` is ``False``.

    Raises:
        LiveTradingPermissionError: on a non-``Decimal``, non-finite or
            non-positive input. The message names the argument and its TYPE,
            never its value.
    """
    price = _require_decimal(price_usd, "price_usd")
    qty = _require_decimal(quantity, "quantity")
    return _round_cost_up_to_cent(price * qty)


@dataclass(frozen=True, slots=True)
class SpendBooking:
    """A grant made by :meth:`DailySpendLedger.authorize_order_cost`.

    ``cost`` is the USD amount booked against the day, ``day`` is the UTC
    calendar day of the grant, and ``booking_id`` is a process-monotonic
    nonce. Released or trued-up at most once. A booking from a previous UTC
    day cannot be released or trued-up against today's accumulator: the day
    already rolled, the spend is gone.
    """

    cost: Decimal
    day: date
    booking_id: int


class DailySpendLedger:
    """A UTC-calendar-day accumulator of USD notional spent.

    Breezy-owned because ``RiskLimits`` has no time dimension at all: it caps
    position, event and location notional, but nothing there knows what a day
    is, so a per-day spend-down cannot be expressed as a limit on it.

    State is process-local and in-memory, with the same consequence
    ``safety`` records for its session budget: a restart forgets the day's
    spending, and two processes do not share a ledger. That is stated rather
    than hidden; a durable ledger is a different increment with a different
    failure mode (a stale file re-granting or wrongly refusing budget).
    """

    __slots__ = (
        "_bookings",
        "_day",
        "_last_ns",
        "_lock",
        "_released_ids",
        "_spent_usd",
        "_trued_up_ids",
    )

    def __init__(self) -> None:
        #: One lock, because a strategy and a reconciliation task can
        #: authorise concurrently and a read-modify-write of the accumulator
        #: is exactly the shape that double-spends a budget under a race.
        #: Release and true-up take the same lock.
        self._lock = threading.Lock()
        self._day: date | None = None
        self._spent_usd = Decimal(0)
        self._last_ns = 0
        self._bookings: dict[int, SpendBooking] = {}
        self._released_ids: set[int] = set()
        self._trued_up_ids: set[int] = set()

    def spent_today_usd(self, *, now_ns: int) -> Decimal:
        """USD spent on the UTC day containing ``now_ns``. Never mutates.

        Reports zero for any day other than the accumulating one -- including
        a day already rolled past, which this deliberately does not resurrect.
        """
        day = utc_day_for_ns(now_ns)
        with self._lock:
            if self._day != day:
                return Decimal(0)
            return self._spent_usd

    def authorize_order_cost(
        self,
        *,
        price_usd: Decimal,
        quantity: Decimal,
        now_ns: int,
    ) -> SpendBooking:
        """Refuse or record the cost of one order against both controls.

        Both controls are read FIRST, before either is applied, so an absent
        control refuses regardless of which ceiling the order would have
        breached. Spend is recorded only on a grant, and the whole
        read-check-record sequence is under one lock.

        Args:
            price_usd: the per-contract price in USD, as a ``Decimal``.
            quantity: the number of contracts, as a ``Decimal``.
            now_ns: the current time from the caller's INJECTED clock. Never
                sampled here.

        Returns:
            A frozen :class:`SpendBooking` for the grant. ``booking.cost`` is
            the USD amount recorded against the day's budget.

        Raises:
            LiveTradingPermissionError: if either control is unset or
                malformed, if the cost exceeds the per-position ceiling, if it
                would carry the day past the daily budget, or if the clock
                moved backwards. Every message names the control, never its
                value or the amounts involved.
        """
        day = utc_day_for_ns(now_ns)
        cost = order_cost_usd(price_usd=price_usd, quantity=quantity)

        # Read BOTH before applying EITHER: absence must refuse identically
        # whichever ceiling the order would have hit first.
        daily_budget = operator_max_daily_budget_usd()
        position_cap = operator_max_position_cost_usd()

        if cost > position_cap:
            raise LiveTradingPermissionError(
                f"{MAX_POSITION_COST_USD_ENV_VAR} refuses this order: its USD cost "
                f"(price x quantity) exceeds the operator's per-position ceiling"
            )

        with self._lock:
            if now_ns < self._last_ns:
                # A rewound clock would roll the ledger back into an earlier
                # day and re-grant budget already spent. Refused outright --
                # the same direction ``safety`` takes when a use-time
                # precedes issuance.
                raise LiveTradingPermissionError(
                    f"{MAX_DAILY_BUDGET_USD_ENV_VAR} refuses this order: the injected "
                    f"clock moved backwards, and spent budget is never resurrected"
                )
            if self._day != day:
                # Prior-day bookings are already unreleasable / untrue-up-able
                # by the day rule; drop them so a long-lived node cannot grow
                # without bound. Membership checks in _require_open_booking
                # run after the day rule, so pruning cannot change the error.
                self._bookings = {
                    booking_id: booking
                    for booking_id, booking in self._bookings.items()
                    if booking.day == day
                }
                keep = set(self._bookings)
                self._released_ids.intersection_update(keep)
                self._trued_up_ids.intersection_update(keep)
                self._day = day
                self._spent_usd = Decimal(0)
            if self._spent_usd + cost > daily_budget:
                raise LiveTradingPermissionError(
                    f"{MAX_DAILY_BUDGET_USD_ENV_VAR} refuses this order: it would carry "
                    f"today's USD notional past the operator's daily budget"
                )
            booking = SpendBooking(cost=cost, day=day, booking_id=next(_BOOKING_IDS))
            self._bookings[booking.booking_id] = booking
            self._spent_usd = self._spent_usd + cost
            self._last_ns = now_ns
            return booking

    def _require_open_booking(
        self, booking: SpendBooking, *, now_ns: int, action: str
    ) -> SpendBooking:
        """Return ``booking`` if it is live on today's accumulator.

        Caller MUST hold ``self._lock``. Does not roll the day: a previous-
        UTC-day booking cannot be released or trued-up against today's
        accumulator -- the day already rolled, the spend is gone.
        """
        if now_ns < self._last_ns:
            raise LiveTradingPermissionError(
                "the injected clock moved backwards, and spent budget is never resurrected"
            )
        day = utc_day_for_ns(now_ns)
        if booking.day != day or self._day != booking.day:
            raise LiveTradingPermissionError(
                f"a booking from a previous UTC day cannot be {action} against "
                "today's accumulator: the day already rolled, the spend is gone"
            )
        stored = self._bookings.get(booking.booking_id)
        if stored is None or stored != booking:
            raise LiveTradingPermissionError("booking is not known to this ledger")
        if booking.booking_id in self._released_ids:
            raise LiveTradingPermissionError("booking has already been released")
        if booking.booking_id in self._trued_up_ids:
            raise LiveTradingPermissionError("booking has already been trued up")
        return stored

    def release_booking(self, booking: SpendBooking, *, now_ns: int) -> None:
        """Reverse a grant made by :meth:`authorize_order_cost` in full.

        A booking can be released at most once. A booking from a previous UTC
        day cannot be released against today's accumulator: the day already
        rolled, the spend is gone. Spent never goes negative. Runs under the
        same lock as :meth:`authorize_order_cost`. Does not roll the day.
        """
        if type(booking) is not SpendBooking:
            raise LiveTradingPermissionError(
                f"booking must be exactly SpendBooking, not {type(booking).__name__}"
            )
        with self._lock:
            granted = self._require_open_booking(booking, now_ns=now_ns, action="released")
            if self._spent_usd < granted.cost:
                raise LiveTradingPermissionError("spent would go negative")
            self._spent_usd = self._spent_usd - granted.cost
            self._released_ids.add(granted.booking_id)
            self._last_ns = now_ns

    def true_up_booking(
        self,
        booking: SpendBooking,
        *,
        filled_cost_usd: Decimal,
        now_ns: int,
    ) -> Decimal:
        """Replace the booked cost with the realized fill cost.

        ``filled_cost_usd`` is the realized ``avgPx x cumQuantity`` cost,
        rounded UP to the cent with the same helper :func:`order_cost_usd`
        uses. It may be less than or equal to the booking (partial or full
        fill). If it is greater, this raises: a fill cannot cost more than
        authorized; that is an accounting error to surface, never absorb.
        At most once per booking. A booking from a previous UTC day cannot
        be trued up against today's accumulator: the day already rolled,
        the spend is gone. Spent never goes negative. Runs under the same
        lock as :meth:`authorize_order_cost`. Does not roll the day.
        """
        if type(booking) is not SpendBooking:
            raise LiveTradingPermissionError(
                f"booking must be exactly SpendBooking, not {type(booking).__name__}"
            )
        if type(filled_cost_usd) is not Decimal:
            raise LiveTradingPermissionError(
                f"filled_cost_usd must be exactly Decimal, not {type(filled_cost_usd).__name__}"
            )
        if not filled_cost_usd.is_finite():
            raise LiveTradingPermissionError("filled_cost_usd must be a finite decimal amount")
        if filled_cost_usd < Decimal(0):
            raise LiveTradingPermissionError("filled_cost_usd must not be negative")
        realized = _round_cost_up_to_cent(filled_cost_usd)
        if realized > booking.cost:
            raise LiveTradingPermissionError(
                "a fill cannot cost more than authorized; that is an accounting error "
                "to surface, never absorb"
            )
        with self._lock:
            granted = self._require_open_booking(booking, now_ns=now_ns, action="trued up")
            if self._spent_usd < granted.cost:
                raise LiveTradingPermissionError("spent would go negative")
            self._spent_usd = self._spent_usd - granted.cost + realized
            if self._spent_usd < Decimal(0):
                raise LiveTradingPermissionError("spent would go negative")
            self._trued_up_ids.add(granted.booking_id)
            self._last_ns = now_ns
            return realized
