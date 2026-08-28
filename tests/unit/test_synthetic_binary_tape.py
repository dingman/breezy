"""Guards on the fabricated tape itself.

The tape is test infrastructure, so nothing else fails when it quietly stops
being what it claims. Three properties are worth pinning:

* it is labelled synthetic, in the object and not only in prose;
* every ``BookOrder`` matches the INSTRUMENT's precisions, which is the whole
  reason the instrument is parsed from a capture rather than invented
  (``engine.pyx:4444-4471`` raises ``RuntimeError`` otherwise); and
* it satisfies the ordering invariant it exists to exercise -- a tape whose
  close preceded its data would make the stop-gate suite test nothing.
"""

from __future__ import annotations

import pytest
from nautilus_trader.model.data import InstrumentClose, OrderBookDepth10, QuoteTick
from nautilus_trader.model.enums import InstrumentCloseType, OrderSide

from tests.support.synthetic_binary_tape import SYNTHETIC_TAPE_MARKER, synthetic_binary_tape

SIZE_PRECISIONS = [0, 2]


@pytest.mark.parametrize("size_precision", SIZE_PRECISIONS)
def test_the_tape_labels_itself_synthetic(size_precision: int) -> None:
    assert synthetic_binary_tape(size_precision=size_precision).marker == SYNTHETIC_TAPE_MARKER


@pytest.mark.parametrize("size_precision", SIZE_PRECISIONS)
def test_the_requested_size_precision_is_the_one_delivered(size_precision: int) -> None:
    """Not a fallback: `_captured_instrument` raises rather than substituting."""
    assert synthetic_binary_tape(size_precision=size_precision).instrument.size_precision == (
        size_precision
    )


@pytest.mark.parametrize("size_precision", SIZE_PRECISIONS)
def test_every_book_order_matches_the_instruments_own_precisions(size_precision: int) -> None:
    tape = synthetic_binary_tape(size_precision=size_precision)
    depths = [r for r in tape.market_data if isinstance(r, OrderBookDepth10)]

    assert depths
    for depth in depths:
        for order in [*depth.bids, *depth.asks]:
            assert order.side is not OrderSide.NO_ORDER_SIDE
            assert order.price.precision == tape.instrument.price_precision
            assert order.size.precision == tape.instrument.size_precision
        assert len(depth.bids) == 10
        assert len(depth.asks) == 10


@pytest.mark.parametrize("size_precision", SIZE_PRECISIONS)
def test_the_tape_carries_both_a_depth_and_a_quote_stream(size_precision: int) -> None:
    tape = synthetic_binary_tape(size_precision=size_precision)

    assert any(isinstance(r, OrderBookDepth10) for r in tape.market_data)
    assert any(isinstance(r, QuoteTick) for r in tape.market_data)


def test_market_data_is_ascending_in_ts_init() -> None:
    tape = synthetic_binary_tape(size_precision=0)
    stamps = [r.ts_init for r in tape.market_data]

    assert stamps == sorted(stamps)


def test_the_close_is_a_contract_expiry_and_strictly_follows_the_last_market_data() -> None:
    """The invariant the tape exists to exercise. `END_OF_SESSION` would be
    silently discarded by the exchange, and a tied timestamp would trip the
    harness's own ordering guard.
    """
    tape = synthetic_binary_tape(size_precision=0)

    assert tape.instrument_close.close_type == InstrumentCloseType.CONTRACT_EXPIRED
    assert tape.instrument_close.ts_init > tape.last_market_data_ts_ns
    assert tape.last_market_data_ts_ns == max(r.ts_init for r in tape.market_data)


def test_the_weather_timestamp_sits_inside_the_tape() -> None:
    tape = synthetic_binary_tape(size_precision=0)

    assert tape.market_data[0].ts_init < tape.weather_ts_ns < tape.last_market_data_ts_ns


def test_all_data_appends_exactly_one_close_to_the_market_data() -> None:
    tape = synthetic_binary_tape(size_precision=0)

    assert tape.all_data() == [*tape.market_data, tape.instrument_close]
    assert sum(isinstance(r, InstrumentClose) for r in tape.all_data()) == 1


@pytest.mark.parametrize("settlement_price", [0.0, 1.0])
def test_the_settlement_price_is_carried_onto_the_audit_only_close_price(
    settlement_price: float,
) -> None:
    """The engine never reads `close_price` -- it is recorded for audit. The
    tape still keeps the two consistent so a reader is not misled.
    """
    tape = synthetic_binary_tape(size_precision=0, settlement_price=settlement_price)

    assert tape.settlement_price == settlement_price
    assert float(tape.instrument_close.close_price) == settlement_price


def test_an_unavailable_size_precision_raises_rather_than_substituting() -> None:
    with pytest.raises(LookupError, match="no captured Polymarket.us market"):
        synthetic_binary_tape(size_precision=7)
