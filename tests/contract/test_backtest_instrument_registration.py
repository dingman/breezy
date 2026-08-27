"""``add_data`` registers only ``data[0]``'s instrument. Verified, then closed.

The mechanism, read from ``backtest/engine.pyx``
------------------------------------------------

``BacktestEngine.add_data`` (``engine.pyx:852-899``) takes ``first =
data[0]`` and registers **that one** ``instrument_id`` into ``self._has_data``
and -- if ``type(first)`` is a book type -- into ``self._has_book_data``. Its
own docstring says so: *"Assumes all data elements are of the same type."*

``BacktestEngine.run`` (``engine.pyx:1552-1562``) then raises
``InvalidConfiguration: No order book data found for instrument ...`` for any
instrument that has data but no BOOK data, under an ``L2_MBP`` venue. That is
the guard which tells a strategy author "your orders on this market can never
fill".

Feed a flat, heterogeneous, multi-instrument list and the guard covers
instrument **one** only. Instruments 2..N are absent from ``_has_data``, so the
condition ``has_data and missing_book_data`` is False for them and the check is
skipped -- and every order they receive is silently ``REJECTED (no market)``.

The harness therefore groups ``market_data`` by ``(instrument_id, type)`` and
calls ``add_data`` once per group: one call per instrument per record type is
exactly the shape ``add_data`` documents itself as assuming.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from nautilus_trader.common.config import InvalidConfiguration
from nautilus_trader.model.objects import Money

from breezy.runtime.backtest_feed import as_backtest_data
from breezy.runtime.backtest_harness import BreezyBacktestConfig, run_backtest
from breezy.strategy.harness_probe import BreezyHarnessProbe, BreezyHarnessProbeConfig
from tests.support.synthetic_binary_tape import synthetic_binary_tape
from tests.unit.test_persistence_catalog import make_climate_day

if TYPE_CHECKING:  # pragma: no cover - typing only
    from nautilus_trader.core.data import Data

pytestmark = pytest.mark.contract


def test_a_second_instrument_with_no_book_data_is_refused_rather_than_ignored() -> None:
    """The RED case: quotes-only on the SECOND instrument.

    Instrument one carries depth, so under a single flat ``add_data`` call it
    is the only one registered and the whole run passes validation. Instrument
    two, whose book is empty for the entire run, is not checked at all -- and
    an order on it is rejected with ``no market`` and no exception.
    """
    with_book = synthetic_binary_tape(size_precision=0, settlement_price=1.0)
    without_book = synthetic_binary_tape(size_precision=2, settlement_price=0.0)
    quotes_only: list[Data] = [
        record
        for record in without_book.market_data
        if type(record).__name__ == "QuoteTick"
    ]
    market_data: list[Data] = [
        *with_book.all_data(),
        *quotes_only,
        without_book.instrument_close,
    ]
    probe = BreezyHarnessProbe(
        BreezyHarnessProbeConfig(
            instrument_id=with_book.instrument.id,
            trade_quantity=Decimal(10),
        ),
    )
    config = BreezyBacktestConfig(
        instruments=(with_book.instrument, without_book.instrument),
        market_data=market_data,
        weather_data=as_backtest_data(
            [make_climate_day(retrieved_at_ns=with_book.weather_ts_ns)],
        ),
        settlement_prices={
            with_book.instrument.id: 1.0,
            without_book.instrument.id: 0.0,
        },
        starting_balances=(Money(1_000, with_book.instrument.quote_currency),),
    )

    with pytest.raises(InvalidConfiguration) as excinfo:
        run_backtest(config, strategies=(probe,))

    assert str(without_book.instrument.id) in str(excinfo.value)
