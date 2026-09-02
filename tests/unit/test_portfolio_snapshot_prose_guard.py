"""`PortfolioSnapshot`'s prose must describe the covers it actually has.

T-1 D6 (``docs/plans/T1_STRATEGY_INFLIGHT_BLINDNESS_2026-09-02.md``). Same
recurring defect this repo already guards against in
``tests/unit/test_backtest_harness_prose_guard.py``: a docstring stating a
mechanism the code does not implement. ``settled_qty`` carried three false
claims at once, and it is the docstring that MOTIVATED T-1, so it gets a
guard rather than a silent edit:

1. It named **two independent covers** for the jointly-naked sell case. Both
   read ``cache.orders_open``, so they were ONE query with ONE hole.
2. It called the guard **backtest-only**. ``install_live_order_guard`` wires
   the identical class onto a live ``MessageBus``; the last test here pins
   that at the CODE, so this file cannot degrade into string-matching prose
   against prose.
3. It said **"every strategy skips evaluation entirely while any order is
   working"**. That was never true of the FLAT path, which reaches
   ``close_all_positions`` without consulting any gate -- and T-1 deleted the
   one query that path did make (a cancel pre-filter narrower than the native
   ``cancel_all_orders`` it guarded).

What must NOT reappear is a claim that the signed-net limitation is fixed. It
is not: T-1 widened the QUERY behind ``pending_qty`` and deliberately left the
REPRESENTATION alone.
"""

from __future__ import annotations

from typing import Final

from breezy.runtime import backtest_order_guard
from breezy.strategy.weather_common.risk import PortfolioSnapshot


def _flat(doc: str | None) -> str:
    """Docstring with its line wrapping removed, so pins are whole CLAIMS."""
    return " ".join((doc or "").split())


SETTLED_DOC: Final[str] = _flat(PortfolioSnapshot.settled_qty.__doc__)
SNAPSHOT_DOC: Final[str] = _flat(PortfolioSnapshot.__doc__)


def test_settled_qty_no_longer_calls_the_guard_backtest_only() -> None:
    """Claim 2, pinned as absent -- the same class is wired onto a live bus."""
    assert "the second is backtest-only" not in SETTLED_DOC
    assert "in backtests :class:`breezy.runtime.backtest_order_guard" not in SETTLED_DOC


def test_settled_qty_no_longer_claims_a_gate_covers_the_jointly_naked_case() -> None:
    """Claims 1 and 3, pinned as absent."""
    assert "every strategy skips evaluation entirely while any order is working" not in SETTLED_DOC


def test_settled_qty_names_the_one_cover_it_has_and_says_it_holds_in_both_modes() -> None:
    assert "exactly one thing, at submit time, in BOTH modes" in SETTLED_DOC
    assert "`install_live_order_guard` wires that same class onto a live `MessageBus`" in (
        SETTLED_DOC
    )


def test_settled_qty_does_not_advertise_the_signed_net_limitation_as_fixed() -> None:
    """The representation is UNCHANGED by T-1, and the prose has to say so."""
    assert "still a signed net and still cannot express the jointly-naked case" in SETTLED_DOC
    assert "`settled_qty` itself is unchanged" in SETTLED_DOC


def test_the_snapshot_docstring_names_the_query_the_strategies_actually_make() -> None:
    """`pending_qty` is fed by `inflight.working_orders`, not by `orders_open`."""
    assert "``Strategy.cache.orders_open`` (both native)" not in SNAPSHOT_DOC
    assert "``not order.is_closed``" in SNAPSHOT_DOC


def test_the_live_cover_the_docstring_claims_is_a_real_exported_function() -> None:
    """The prose pin above is only worth having if the mechanism exists.

    Checked at the CODE so this module cannot pass by matching one docstring
    against another: the live installer must be present AND exported.
    """
    assert callable(backtest_order_guard.install_live_order_guard)
    assert "install_live_order_guard" in backtest_order_guard.__all__
