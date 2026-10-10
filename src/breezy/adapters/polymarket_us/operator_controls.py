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
``breezy-trade``. The operator MAY keep the two values in the gitignored root
``operator.env`` and source it from THEIR shell; repo Python still never loads
or assigns it. **No value for either control is assigned anywhere in this
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

CONSTRUCTED AND SPENT AGAINST IN PRODUCTION
-------------------------------------------

``factories.py:777`` constructs one ``DailySpendLedger()`` per execution
client (``spend_ledger=DailySpendLedger(),``), injected as
``exec/client.py``'s ``self._ledger``. The live R-7 submit path calls it
directly: :meth:`authorize_order_cost` before every POST,
:meth:`release_booking` on every denial, :meth:`true_up_booking` after
every terminal outcome. This is not a library with no caller.

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


#: Operator ruling 2026-09-14: raised ONLY by the daily-budget branch of
#: :meth:`DailySpendLedger.authorize_order_cost`, so the exec client can
#: durably mark the UTC day as spend-exhausted by exception TYPE rather than
#: by re-parsing the (unchanged) refusal message. The per-position ceiling
#: and the clock-rewind branch stay plain ``LiveTradingPermissionError`` --
#: neither means the day's dollar ceiling was reached.
class DailyBudgetExhausted(LiveTradingPermissionError):
    """The daily USD budget was reached; today's remaining orders are denied."""


class OpenExposureBoundExceeded(LiveTradingPermissionError):
    """An open-exposure bound refused this order; it is NOT a day-stop.

    Raised by :meth:`DailySpendLedger.authorize_order_cost` when the daily
    budget itself still has room but ``spent + uncharged open exposure +
    cost`` would pass it, or the AMBIGUOUS-notional bound would be passed.
    Deliberately a sibling of, not a subclass of, :class:`DailyBudgetExhausted`:
    the exec client marks the durable day-stop by exception TYPE, and open
    exposure draining (a settle) re-opens headroom within the same day.
    """


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

#: Ordered upper bounds of the ``cap / budget`` ratio -> label, for
#: :meth:`DailySpendLedger.cost_budget_bucket`. Ratios, never dollar amounts.
_COST_BUDGET_BUCKETS: Final = (
    (Decimal("0.02"), "\u22640.02"),
    (Decimal("0.05"), "0.05"),
    (Decimal("0.10"), "0.10"),
    (Decimal("0.25"), "0.25"),
    (Decimal("0.50"), "0.50"),
)

#: Label for any ratio above the last bucket; it orders above every bucket.
COST_BUDGET_BUCKET_ABOVE_SENTINEL: Final = ">0.50"

_SELL_SIDE: Final = "SELL"

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


@dataclass(slots=True)
class _OpenExposure:
    """One registered open (unsettled) BUY order's exposure.

    ``notional`` is the exposure NOT already counted in the seed
    (``None`` = unknown). ``charged`` means a same-day booking already holds
    it in ``_spent_usd``; a day roll clears that, converting it to uncharged.
    """

    notional: Decimal | None
    booking: SpendBooking | None
    seeded_partial: Decimal
    charged: bool
    ambiguous: bool = False


def _require_exact_decimal(value: object, label: str, *, allow_zero: bool = True) -> Decimal:
    """Exactly ``Decimal``, finite and non-negative; names only the TYPE."""
    if type(value) is not Decimal:
        raise LiveTradingPermissionError(
            f"{label} must be exactly Decimal, not {type(value).__name__}"
        )
    if not value.is_finite():
        raise LiveTradingPermissionError(f"{label} must be a finite decimal amount")
    if value < Decimal(0) or (value == Decimal(0) and not allow_zero):
        raise LiveTradingPermissionError(f"{label} must not be negative")
    return value


def _require_int_ns(now_ns: object) -> None:
    """``now_ns`` must be exactly ``int``: ``max`` over a float would hide it."""
    if type(now_ns) is not int:
        raise LiveTradingPermissionError(f"now_ns must be exactly int, not {type(now_ns).__name__}")


def _require_booking_type(booking: object) -> None:
    if type(booking) is not SpendBooking:
        raise LiveTradingPermissionError(
            f"booking must be exactly SpendBooking, not {type(booking).__name__}"
        )


def _checked_filled_cost(booking: SpendBooking, filled_cost_usd: object) -> Decimal:
    """The true-up input validation, shared by the public method and ``settle``.

    Raises in the original order: booking type, ``filled_cost_usd`` type,
    finiteness, sign. Returns the (unrounded) validated amount.
    """
    _require_booking_type(booking)
    if type(filled_cost_usd) is not Decimal:
        raise LiveTradingPermissionError(
            f"filled_cost_usd must be exactly Decimal, not {type(filled_cost_usd).__name__}"
        )
    if not filled_cost_usd.is_finite():
        raise LiveTradingPermissionError("filled_cost_usd must be a finite decimal amount")
    if filled_cost_usd < Decimal(0):
        raise LiveTradingPermissionError("filled_cost_usd must not be negative")
    return filled_cost_usd


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
        "_cross_day_settles",
        "_day",
        "_f_adm",
        "_f_breaker",
        "_last_ns",
        "_lock",
        "_open",
        "_registry_last_ns",
        "_released_ids",
        "_seeded",
        "_spent_usd",
        "_trued_up_ids",
        "_unknown_keys",
    )

    def __init__(self, *, f_adm: Decimal | None = None, f_breaker: Decimal | None = None) -> None:
        #: Optional Breezy-owned fractions of the daily budget (never operator
        #: controls). ``None`` = that bound is off.
        self._f_adm = None if f_adm is None else self._checked_fraction(f_adm, "f_adm")
        self._f_breaker = (
            None if f_breaker is None else self._checked_fraction(f_breaker, "f_breaker")
        )
        self._open: dict[str, _OpenExposure] = {}
        self._unknown_keys: set[str] = set()
        #: High-water clock of registry-driven (settle) activity, so a stale
        #: authorize can never roll the ledger back across a settle's roll.
        self._registry_last_ns = 0
        self._cross_day_settles = 0
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
        #: S0 (plan rev 3, R3-1): set by the FIRST successful `seed_spent`
        #: call this process ever makes. A second `_connect()` in the same
        #: process must not double-book, so every call after the first is a
        #: no-op regardless of the figure it carries.
        self._seeded = False

    def seed_spent(self, *, day: date, spent_usd: Decimal, now_ns: int) -> None:
        """Book prior spend into the ledger exactly once per process (S0).

        Called at most meaningfully once: every call after the first
        successful one is a no-op, so a second `_connect()` in the same
        process cannot double-count what a real order already booked in
        between. Never LOWERS an in-memory total that is already higher --
        a booking made between the durable walk and this call must survive
        it. ``spent_usd`` must be a durable-fill sum, never a value read
        from an operator-reserved control.
        """
        if type(spent_usd) is not Decimal:
            raise LiveTradingPermissionError(
                f"spent_usd must be exactly Decimal, not {type(spent_usd).__name__}"
            )
        if not spent_usd.is_finite() or spent_usd < Decimal(0):
            raise LiveTradingPermissionError(
                "spent_usd must be a non-negative finite decimal amount"
            )
        with self._lock:
            if self._seeded:
                return
            if self._day != day:
                self._day = day
                self._spent_usd = Decimal(0)
            self._spent_usd = max(self._spent_usd, spent_usd)
            self._seeded = True
            self._last_ns = max(self._last_ns, now_ns)

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
            if now_ns < max(self._last_ns, self._registry_last_ns):
                # A rewound clock would roll the ledger back into an earlier
                # day and re-grant budget already spent. Refused outright --
                # the same direction ``safety`` takes when a use-time
                # precedes issuance.
                raise LiveTradingPermissionError(
                    f"{MAX_DAILY_BUDGET_USD_ENV_VAR} refuses this order: the injected "
                    f"clock moved backwards, and spent budget is never resurrected"
                )
            if self._day != day:
                self._roll_locked(day)
            if self._spent_usd + cost > daily_budget:
                raise DailyBudgetExhausted(
                    f"{MAX_DAILY_BUDGET_USD_ENV_VAR} refuses this order: it would carry "
                    f"today's USD notional past the operator's daily budget"
                )
            self._require_exposure_headroom_locked(cost, daily_budget, rolled=False)
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
        _require_booking_type(booking)
        with self._lock:
            self._release_locked(booking, now_ns)

    def _release_locked(self, booking: SpendBooking, eff_now: int) -> None:
        """Release body; caller holds the lock and has type-checked ``booking``."""
        granted = self._require_open_booking(booking, now_ns=eff_now, action="released")
        if self._spent_usd < granted.cost:
            raise LiveTradingPermissionError("spent would go negative")
        self._spent_usd = self._spent_usd - granted.cost
        self._released_ids.add(granted.booking_id)
        self._last_ns = eff_now

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
        realized = _round_cost_up_to_cent(_checked_filled_cost(booking, filled_cost_usd))
        with self._lock:
            return self._true_up_locked(booking, realized, now_ns)

    def _true_up_locked(self, booking: SpendBooking, realized: Decimal, eff_now: int) -> Decimal:
        """True-up body; caller holds the lock and passes the validated,
        cent-up ``realized`` (see :func:`_checked_filled_cost`)."""
        if realized > booking.cost:
            raise LiveTradingPermissionError(
                "a fill cannot cost more than authorized; that is an accounting error "
                "to surface, never absorb"
            )
        granted = self._require_open_booking(booking, now_ns=eff_now, action="trued up")
        if self._spent_usd < granted.cost:
            raise LiveTradingPermissionError("spent would go negative")
        self._spent_usd = self._spent_usd - granted.cost + realized
        if self._spent_usd < Decimal(0):
            raise LiveTradingPermissionError("spent would go negative")
        self._trued_up_ids.add(granted.booking_id)
        self._last_ns = eff_now
        return realized

    # ------------------------------------------------------------------
    # EXEC-PAR WP3 -- open-exposure registry (inert until a caller wires it)
    # ------------------------------------------------------------------

    @staticmethod
    def _checked_fraction(value: object, label: str) -> Decimal:
        fraction = _require_exact_decimal(value, label, allow_zero=False)
        if fraction > Decimal(1):
            raise LiveTradingPermissionError(f"{label} must be a fraction of the budget")
        return fraction

    def _roll_locked(self, day: date) -> None:
        """Roll the accumulator to ``day``. Caller holds the lock.

        Prior-day bookings are already unreleasable / untrue-up-able by the day
        rule; drop them so a long-lived node cannot grow without bound.
        Surviving OPEN registry entries are NOT dropped: their charge is gone
        with the day's spend, so they convert to uncharged exposure.
        """
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
        for entry in self._open.values():
            entry.charged = False

    def _totals_locked(self, *, rolled: bool) -> tuple[Decimal, Decimal]:
        """``(uncharged, ambiguous)`` known-notional totals, BUY entries only.

        ``rolled`` evaluates as if the day had already rolled (a read-only view).
        """
        uncharged = Decimal(0)
        ambiguous = Decimal(0)
        for entry in self._open.values():
            if entry.notional is None:
                continue
            if rolled or not entry.charged:
                uncharged += entry.notional
            if entry.ambiguous:
                ambiguous += entry.notional
        return uncharged, ambiguous

    def _require_exposure_headroom_locked(
        self, cost: Decimal, daily_budget: Decimal, *, rolled: bool
    ) -> None:
        """The two open-exposure invariants; raises the non-day-stop type."""
        if self._unknown_keys:
            raise OpenExposureBoundExceeded(
                f"{MAX_DAILY_BUDGET_USD_ENV_VAR} refuses this order: an open order's "
                f"notional is unknown, so the daily budget cannot be shown to hold"
            )
        uncharged, ambiguous = self._totals_locked(rolled=rolled)
        spent = Decimal(0) if rolled else self._spent_usd
        if spent + uncharged + cost > daily_budget:
            raise OpenExposureBoundExceeded(
                f"{MAX_DAILY_BUDGET_USD_ENV_VAR} refuses this order: spent budget plus "
                f"unsettled open exposure would pass the operator's daily budget"
            )
        if self._f_adm is not None and ambiguous + cost > self._f_adm * daily_budget:
            raise OpenExposureBoundExceeded(
                f"{MAX_DAILY_BUDGET_USD_ENV_VAR} refuses this order: AMBIGUOUS open "
                f"exposure would pass its admission fraction of the daily budget"
            )

    def register_open_exposure(
        self,
        key: str,
        notional_usd: Decimal | None,
        *,
        booking: SpendBooking | None,
        seeded_partial_usd: Decimal,
        side: str,
        now_ns: int,
    ) -> None:
        """Register one open BUY order's exposure under ``key``.

        Charged iff a same-day booking is given (its cost is then already in
        spent); otherwise uncharged. ``notional_usd=None`` marks the key's
        notional unknown (per key). Exits never register: ``side == "SELL"``
        raises. A duplicate key raises.
        """
        if type(key) is not str or not key:
            raise LiveTradingPermissionError("exposure key must be a non-empty str")
        _require_int_ns(now_ns)
        if side == _SELL_SIDE:
            raise LiveTradingPermissionError("exits are never registered as open exposure")
        if notional_usd is not None:
            _require_exact_decimal(notional_usd, "notional_usd")
        partial = _require_exact_decimal(seeded_partial_usd, "seeded_partial_usd")
        if booking is not None:
            _require_booking_type(booking)
        with self._lock:
            if key in self._open:
                raise LiveTradingPermissionError("exposure key is already registered")
            eff_now = max(now_ns, self._last_ns, self._registry_last_ns)
            eff_day = utc_day_for_ns(eff_now)
            charged = booking is not None and booking.day == eff_day and self._day == booking.day
            if charged and booking is not None:
                self._require_open_booking(booking, now_ns=eff_now, action="registered")
            self._open[key] = _OpenExposure(
                notional=notional_usd, booking=booking, seeded_partial=partial, charged=charged
            )
            if notional_usd is None:
                self._unknown_keys.add(key)

    def mark_ambiguous(self, key: str) -> None:
        """Mark a registered key AMBIGUOUS. An unregistered (exit) key is a no-op."""
        with self._lock:
            entry = self._open.get(key)
            if entry is not None:
                entry.ambiguous = True

    def abandon_open_exposure(self, key: str) -> bool:
        """Drop ``key``'s entry, adding no spend. Never raises.

        A charged booking stays charged (conservative). Returns whether an
        entry existed.
        """
        if type(key) is not str:
            return False
        with self._lock:
            self._unknown_keys.discard(key)
            return self._open.pop(key, None) is not None

    def settle(
        self,
        key: str,
        *,
        booking: SpendBooking | None,
        realized_usd: Decimal | None,
        fill_ts_ns: int | None,
        now_ns: int,
    ) -> bool:
        """Settle ``key``'s exposure exactly once; True iff it was registered.

        Tolerates a stale ``now_ns`` (uses the high-water of all clocks seen).
        An unregistered key with ``booking=None`` is a no-op returning False;
        an unregistered key carrying a booking, a mismatched booking or a
        double settle raises. A same-day live booking is trued-up (``realized``
        set) or released through the same bodies as the public methods. A
        prior-day booking or uncharged entry adds
        ``max(round_up(realized) - seeded_partial, 0)`` iff ``fill_ts_ns`` falls
        on the effective day. Atomic: every raise leaves the entry, the
        booking and the totals untouched.
        """
        _require_int_ns(now_ns)
        if booking is not None:
            _require_booking_type(booking)
        realized = None
        if realized_usd is not None:
            realized = _round_cost_up_to_cent(_require_exact_decimal(realized_usd, "realized_usd"))
        fill_day = None if fill_ts_ns is None else utc_day_for_ns(fill_ts_ns)
        with self._lock:
            entry = self._open.get(key)
            if entry is None:
                if booking is None:
                    return False
                raise LiveTradingPermissionError("settle carries a booking for an unregistered key")
            if entry.booking != booking:
                raise LiveTradingPermissionError("settle booking does not match the registered one")
            eff_now = max(now_ns, self._last_ns, self._registry_last_ns)
            eff_day = utc_day_for_ns(eff_now)
            if booking is not None and entry.charged and self._day == eff_day:
                self._settle_live_locked(booking, realized, eff_now)
            else:
                self._settle_uncharged_locked(entry, realized, fill_day, eff_day)
                self._cross_day_settles += 1
            del self._open[key]
            self._unknown_keys.discard(key)
            self._registry_last_ns = eff_now
            return True

    def _settle_live_locked(
        self, booking: SpendBooking, realized: Decimal | None, eff_now: int
    ) -> None:
        if realized is None:
            self._release_locked(booking, eff_now)
        else:
            self._true_up_locked(booking, realized, eff_now)

    def _settle_uncharged_locked(
        self, entry: _OpenExposure, realized: Decimal | None, fill_day: date | None, eff_day: date
    ) -> None:
        """Prior-day booking or uncharged entry: roll forward, then add once."""
        if self._day is None or eff_day > self._day:
            self._roll_locked(eff_day)
        if realized is None or fill_day != eff_day or self._day != eff_day:
            return
        self._spent_usd += max(realized - entry.seeded_partial, Decimal(0))

    @property
    def cross_day_settles_total(self) -> int:
        with self._lock:
            return self._cross_day_settles

    def has_open_exposure(self, key: str) -> bool:
        with self._lock:
            return key in self._open

    def uncharged_open_total(self) -> Decimal:
        """Known notional of open entries NOT held in spent (BUY only)."""
        with self._lock:
            return self._totals_locked(rolled=False)[0]

    def ambiguous_open_total(self) -> Decimal:
        """Known notional of open entries marked AMBIGUOUS (BUY only)."""
        with self._lock:
            return self._totals_locked(rolled=False)[1]

    def unknown_key_count(self) -> int:
        with self._lock:
            return len(self._unknown_keys)

    def exposure_admission_refusal(
        self, price_usd: Decimal, quantity: Decimal, now_ns: int
    ) -> str | None:
        """Read-only pre-check; a deny REASON, or ``None`` to proceed in-lock.

        Rolls on a view (never mutates), uses the in-lock cent-up cost
        function, and reads the budget only when open-exposure totals are
        non-zero. Plain ``spent + cost > budget`` returns ``None`` so the
        in-lock check raises :class:`DailyBudgetExhausted` and the day-stop is
        marked as today. Any :class:`LiveTradingPermissionError` becomes the
        returned reason (no marker).
        """
        try:
            day = utc_day_for_ns(now_ns)
            cost = order_cost_usd(price_usd=price_usd, quantity=quantity)
            with self._lock:
                return self._exposure_refusal_locked(cost, day, now_ns)
        except LiveTradingPermissionError as exc:
            return str(exc)

    def _exposure_refusal_locked(self, cost: Decimal, day: date, now_ns: int) -> str | None:
        if now_ns < max(self._last_ns, self._registry_last_ns):
            raise LiveTradingPermissionError("the injected clock moved backwards")
        if self._unknown_keys:
            return "open exposure has an unknown notional"
        rolled = self._day != day
        uncharged, ambiguous = self._totals_locked(rolled=rolled)
        if uncharged == 0 and ambiguous == 0:
            return None
        daily_budget = operator_max_daily_budget_usd()
        if (Decimal(0) if rolled else self._spent_usd) + cost > daily_budget:
            return None
        try:
            self._require_exposure_headroom_locked(cost, daily_budget, rolled=rolled)
        except OpenExposureBoundExceeded as exc:
            return str(exc)
        return None

    def breaker_fraction_exceeded(self, f: Decimal | None = None) -> bool:
        """True iff AMBIGUOUS open exposure exceeds ``f x budget``.

        False, without reading the budget, when no AMBIGUOUS exposure is open
        or no fraction is configured. ANY raise (unset control, bad ``f``)
        counts as tripped.
        """
        try:
            with self._lock:
                ambiguous = self._totals_locked(rolled=False)[1]
            fraction = self._f_breaker if f is None else f
            if ambiguous == 0 or fraction is None:
                return False
            limit = self._checked_fraction(fraction, "f") * operator_max_daily_budget_usd()
            return ambiguous > limit
        except Exception:  # noqa: BLE001 -- every failure to evaluate is "tripped"
            return True

    def cost_budget_bucket(self) -> str:
        """The ``cap / budget`` bucket LABEL only; never a dollar value.

        Raises ``LiveTradingPermissionError`` if either control is unset.
        """
        ratio = operator_max_position_cost_usd() / operator_max_daily_budget_usd()
        for upper, label in _COST_BUDGET_BUCKETS:
            if ratio <= upper:
                return label
        return COST_BUDGET_BUCKET_ABOVE_SENTINEL
