"""The one account-equity question every weather strategy asks, asked once.

WHY THIS MODULE EXISTS
----------------------
Five strategies carried five byte-identical private ``_equity()`` methods,
and every one of them ended the same way::

    return self._config.starting_equity

So the method's return type said ``float`` while its meaning was "either a
balance the venue reported, or a fabricated ``10_000.0`` nobody counted" --
and :class:`breezy.strategy.weather_common.risk.PortfolioSnapshot` then
handed that number to the equity-fraction cap, which sized real orders
against it. ``float`` cannot express "unobserved"; ``None`` can. That is the
whole of T-4.

WHAT MAKES THE FABRICATION REACHABLE
------------------------------------
Two mechanisms, and they are not equally bounded.

*Fabricated* is bounded on live: ``_connect`` publishes the account,
``PolymarketUsExecutionClient._confirm_account_registered`` bounded-waits for
it to appear in the cache and latches a node-global trading refusal if it
does not, and ``Portfolio.account`` is cache-backed -- so the event that
satisfies that wait is the same one this reader sees.

*Stale* is bounded by nothing. ``Portfolio.update_order`` returns before
touching a balance when ``calculate_account_state`` is false (which it is on
live -- see the plan's D5 for why turning it on would make the number
confidently wrong rather than merely old), and the only framework-wide
emitter of ``QueryAccount`` is ``Strategy.query_account``, which no Breezy
strategy calls. A connect-time balance read days later is byte-identical to a
fresh one. A bounded staleness rule -- an observation timestamp, a bound on
it, and a periodic refresh -- is a GO-LIVE PRECONDITION and a separate
increment; deliberately not wired here, because it puts a venue REST read on
the decision path at an unverified rate limit.

Backtest is the asymmetric case and needs no fallback at all:
``BacktestExecClient`` registers a *calculated* account whenever
``frozen_account`` is false (Breezy's ``add_venue`` never sets it) and
``BacktestEngine._run`` initialises the account before data streaming, so
``balance_total`` is live there throughout. Backtest already observes; live
is frozen at connect.

NOT IN ``inflight.py`` (whose subject is working orders) and NOT in
``risk.py``, which is pure policy over a snapshot and imports no cache.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from breezy.strategy.weather_common.risk import EQUITY_NONPOSITIVE, EQUITY_UNOBSERVED

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Mapping

    from nautilus_trader.cache.base import CacheFacade
    from nautilus_trader.model.identifiers import InstrumentId
    from nautilus_trader.portfolio.base import PortfolioFacade

__all__ = ["REDUCE_ONLY_STATE", "observed_equity", "reduce_only_refusal_note"]

#: The name an operator reads in the journal. Reduce-only entered SILENTLY is
#: indistinguishable from a strategy that saw no opportunity -- which is T-4's
#: own diagnosis (an unobservable state treated as a measurement) recurring
#: one level up. Naming it is the minimum fix and is sufficient; a persistent
#: mode flag would be a second state machine with nothing to say that this
#: string does not.
REDUCE_ONLY_STATE: Final[str] = "reduce-only"

#: The refusals that put the strategy in that state. Both are buy-side only
#: (`RiskManager.evaluate_order` gates the whole equity block on
#: `signed_qty_delta > 0`), so an exit is never gagged by either.
_REDUCE_ONLY_REASONS: Final[frozenset[str]] = frozenset(
    {EQUITY_UNOBSERVED, EQUITY_NONPOSITIVE},
)


def observed_equity(
    cache: CacheFacade,
    portfolio: PortfolioFacade,
    nt_ids: Mapping[str, InstrumentId],
) -> float | None:
    """The account balance the venue actually reported, or ``None``.

    ``None`` means NOT OBSERVED, and is returned for all three ways the
    observation can be missing: no instrument in the cache (so no quote
    currency to ask about), no account for that instrument's venue (the
    pre-``AccountState`` window), and an account holding no balance in that
    currency.

    That last case is why the check is ``is not None`` and not a truthiness
    test: ``Account.balance_total`` returns ``Money | None`` and returns
    ``None`` -- never zero -- for "I hold no balance in this currency". A
    reported ``0.0`` is a MEASUREMENT of an empty account and is passed
    through unchanged, so the policy can refuse it as
    ``equity_nonpositive`` rather than as ``equity_unobserved``. Collapsing
    the two would throw away the only fact distinguishing "broke" from
    "blind".

    The first venue that answers wins: every instrument a weather strategy
    trades settles in one currency on one venue, so the loop exists to skip
    gaps, not to aggregate across venues.
    """
    for nt_id in nt_ids.values():
        instrument = cache.instrument(nt_id)
        if instrument is None:
            continue
        account = portfolio.account(nt_id.venue)
        if account is None:
            continue
        balance = account.balance_total(instrument.quote_currency)
        if balance is not None:
            return float(balance.as_double())
    return None


def reduce_only_refusal_note(reason: str, *, tick_ts_ns: int) -> str:
    """The log suffix that makes reduce-only legible in an operator's journal.

    Empty for every other refusal -- deliberately NOT unconditional
    decoration. ``equity_fraction``, in particular, is a clip against an
    OBSERVED balance and enters no reduce-only state, so a note on it would
    be a false signal.

    ``tick_ts_ns`` is the strategy clock at the moment the order was
    screened, and it is what makes the plan's own falsifier runnable: if
    these refusals cluster anywhere but a start-up window, fail-closed was
    the wrong default and a bounded balance refresh has to come before a
    refusal. Without the timestamp there is nothing in the journal to run
    that test against.
    """
    if reason not in _REDUCE_ONLY_REASONS:
        return ""
    return (
        f" tick_ts_ns={tick_ts_ns} state={REDUCE_ONLY_STATE}"
        " (new buys refused; position-reducing sells still allowed)"
    )
