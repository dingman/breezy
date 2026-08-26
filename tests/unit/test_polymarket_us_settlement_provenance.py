"""The settlement-truth label, and what may be allowed to create one.

Why this file exists
--------------------
``settlementPx`` appears on BOTH a live and an expired market, and it means
different things in each. The venue distinguishes the two regimes with its own
field, ``settlementPriceCalculationMethod``, and the committed captures show it
moving in lockstep with ``state``:

* ``book_open_510636.json``  -- ``MARKET_STATE_OPEN``,    ``settlementPx=0.4900``,
  ``closePx=0.4900``, method ``..._EVENT_TIER_2``
* ``book_closed_15806.json`` -- ``MARKET_STATE_EXPIRED``, ``settlementPx=1.0000``,
  ``closePx`` absent,        method ``..._EVENT_TIER_1``

Gating a TERMINAL settlement on the state string alone is therefore one frame
away from a permanent corruption: if the venue flips ``state`` to EXPIRED before
it republishes a TIER_1-computed price, a mark-derived number gets recorded as
the settlement truth that REQ-SETTLE-04/08 -- and everything trained on it --
treats as ground truth. The archive can never be re-recorded, so there is no
later correction.

The rule this file pins: **an ``InstrumentClose`` requires the venue to have
said, in its own words, that the price was computed by the terminal method.**
And the raw method string is captured verbatim on every settlement-bearing
frame, so a future reader can re-derive the judgement rather than inherit ours.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from nautilus_trader.model.instruments import BinaryOption
from nautilus_trader.model.objects import Price

from breezy.adapters.polymarket_us.parsing import (
    TERMINAL_SETTLEMENT_METHOD,
    parse_binary_option,
    parse_instrument_close,
    parse_mark_price,
    parse_rfc3339_nanos,
    parse_settlement_snapshot,
    venue_settlement_method,
)
from breezy.adapters.polymarket_us.symbology import POLYMARKET_US_VENUE
from breezy.adapters.polymarket_us.tape_records import VenueSettlementSnapshot

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW = REPO_ROOT / "docs" / "evidence" / "venue" / "polymarket_us" / "raw"
TS_INIT = 1_787_617_213_000_000_000


def load_raw(name: str) -> dict[str, Any]:
    payload: dict[str, Any] = json.loads((RAW / name).read_text(encoding="utf-8"))
    return payload


@pytest.fixture
def open_book() -> dict[str, Any]:
    return load_raw("book_open_510636.json")


@pytest.fixture
def closed_book() -> dict[str, Any]:
    return load_raw("book_closed_15806.json")


@pytest.fixture
def instrument() -> BinaryOption:
    return parse_binary_option(
        load_raw("market_open_510636_by_slug.json"), venue=POLYMARKET_US_VENUE, ts_init=TS_INIT
    )


class TestTheVenueSaysWhichRegimeItIsIn:
    def test_the_captures_carry_the_method_and_the_two_regimes_differ(
        self, open_book: dict[str, Any], closed_book: dict[str, Any]
    ) -> None:
        """Anchors the file against the real evidence, not against our reading."""
        assert venue_settlement_method(open_book) == (
            "SETTLEMENT_PRICE_CALCULATION_METHOD_EVENT_TIER_2"
        )
        assert venue_settlement_method(closed_book) == TERMINAL_SETTLEMENT_METHOD
        assert TERMINAL_SETTLEMENT_METHOD == (
            "SETTLEMENT_PRICE_CALCULATION_METHOD_EVENT_TIER_1"
        )

    def test_a_frame_without_the_method_reports_none_rather_than_a_default(
        self, closed_book: dict[str, Any]
    ) -> None:
        book = json.loads(json.dumps(closed_book))
        del book["marketData"]["stats"]["settlementPriceCalculationMethod"]

        assert venue_settlement_method(book) is None


class TestTerminalSettlementGating:
    def test_an_expired_market_computed_by_the_terminal_method_settles(
        self, closed_book: dict[str, Any], instrument: BinaryOption
    ) -> None:
        close = parse_instrument_close(closed_book, instrument=instrument, ts_init=TS_INIT)

        assert close is not None
        assert close.close_price == Price.from_str("1.000")

    def test_an_expired_state_with_a_non_terminal_method_does_NOT_settle(
        self, closed_book: dict[str, Any], instrument: BinaryOption
    ) -> None:
        """THE failure this file exists for.

        The venue has flipped `state` but has not yet republished a
        terminally-computed price. Recording the mark-derived number here would
        write a wrong settlement-truth label into an archive that can never be
        corrected.
        """
        book = json.loads(json.dumps(closed_book))
        book["marketData"]["stats"]["settlementPriceCalculationMethod"] = (
            "SETTLEMENT_PRICE_CALCULATION_METHOD_EVENT_TIER_2"
        )

        assert parse_instrument_close(book, instrument=instrument, ts_init=TS_INIT) is None

    def test_an_expired_state_with_a_missing_method_does_NOT_settle(
        self, closed_book: dict[str, Any], instrument: BinaryOption
    ) -> None:
        """Absence is not permission."""
        book = json.loads(json.dumps(closed_book))
        del book["marketData"]["stats"]["settlementPriceCalculationMethod"]

        assert parse_instrument_close(book, instrument=instrument, ts_init=TS_INIT) is None

    def test_an_unknown_third_method_does_NOT_settle(
        self, closed_book: dict[str, Any], instrument: BinaryOption
    ) -> None:
        """The enum is UNRESOLVED beyond the two observed values. Fail closed.

        Only TIER_1 and TIER_2 have ever been seen. A third value might be a
        new terminal method or a new intraday one; guessing which would be
        guessing about settlement truth.
        """
        book = json.loads(json.dumps(closed_book))
        book["marketData"]["stats"]["settlementPriceCalculationMethod"] = (
            "SETTLEMENT_PRICE_CALCULATION_METHOD_SOMETHING_NEW"
        )

        assert parse_instrument_close(book, instrument=instrument, ts_init=TS_INIT) is None

    def test_a_live_market_never_settles_even_under_the_terminal_method(
        self, open_book: dict[str, Any], instrument: BinaryOption
    ) -> None:
        """Both conditions are required, not either."""
        book = json.loads(json.dumps(open_book))
        book["marketData"]["stats"]["settlementPriceCalculationMethod"] = (
            TERMINAL_SETTLEMENT_METHOD
        )

        assert parse_instrument_close(book, instrument=instrument, ts_init=TS_INIT) is None


class TestTheEvidenceIsKeptEvenWhenWeRefuseToSettle:
    def test_every_settlement_bearing_frame_yields_a_verbatim_snapshot(
        self, open_book: dict[str, Any], instrument: BinaryOption
    ) -> None:
        snapshot = parse_settlement_snapshot(
            open_book, instrument=instrument, ts_init=TS_INIT
        )

        assert isinstance(snapshot, VenueSettlementSnapshot)
        assert snapshot.state == "MARKET_STATE_OPEN"
        assert snapshot.method == "SETTLEMENT_PRICE_CALCULATION_METHOD_EVENT_TIER_2"
        assert snapshot.settlement_px == "0.4900"
        assert snapshot.is_terminal is False

    def test_the_refused_case_is_still_recorded_so_the_wait_is_visible(
        self, closed_book: dict[str, Any], instrument: BinaryOption
    ) -> None:
        """"Record it and wait" -- the refusal must not also be a silence.

        An EXPIRED market whose price is not yet terminally computed produces
        no `InstrumentClose`, but the frame is exactly the evidence an analyst
        needs to see that the venue was mid-transition.
        """
        book = json.loads(json.dumps(closed_book))
        book["marketData"]["stats"]["settlementPriceCalculationMethod"] = (
            "SETTLEMENT_PRICE_CALCULATION_METHOD_EVENT_TIER_2"
        )

        assert parse_instrument_close(book, instrument=instrument, ts_init=TS_INIT) is None
        snapshot = parse_settlement_snapshot(book, instrument=instrument, ts_init=TS_INIT)
        assert snapshot is not None
        assert snapshot.state == "MARKET_STATE_EXPIRED"
        assert snapshot.method == "SETTLEMENT_PRICE_CALCULATION_METHOD_EVENT_TIER_2"
        assert snapshot.is_terminal is False

    def test_the_snapshot_preserves_the_price_exactly_as_the_venue_spelled_it(
        self, closed_book: dict[str, Any], instrument: BinaryOption
    ) -> None:
        """Four decimal places, verbatim -- not rounded to the instrument's three.

        The price the venue settles on is the venue's string. Storing a
        re-rendered number would silently substitute our precision for theirs
        in the one record the whole system treats as truth.
        """
        snapshot = parse_settlement_snapshot(
            closed_book, instrument=instrument, ts_init=TS_INIT
        )

        assert snapshot is not None
        assert snapshot.settlement_px == "1.0000"

    def test_a_terminal_snapshot_is_marked_terminal(
        self, closed_book: dict[str, Any], instrument: BinaryOption
    ) -> None:
        snapshot = parse_settlement_snapshot(
            closed_book, instrument=instrument, ts_init=TS_INIT
        )

        assert snapshot is not None
        assert snapshot.is_terminal is True

    def test_a_frame_with_no_settlement_price_yields_no_snapshot(
        self, open_book: dict[str, Any], instrument: BinaryOption
    ) -> None:
        book = json.loads(json.dumps(open_book))
        del book["marketData"]["stats"]["settlementPx"]

        assert parse_settlement_snapshot(book, instrument=instrument, ts_init=TS_INIT) is None

    def test_the_mark_price_path_is_unaffected_by_the_terminal_gate(
        self, open_book: dict[str, Any], instrument: BinaryOption
    ) -> None:
        """The mark is a continuous series; only the TERMINAL label is gated."""
        mark = parse_mark_price(open_book, instrument=instrument, ts_init=TS_INIT)

        assert mark is not None
        assert mark.value == Price.from_str("0.490")


class TestVenueTransactTimeIsRetained:
    """The frame's OWN ``transactTime``, alongside ``settlementSetTime``.

    A disputed settlement needs two different clocks: when the venue COMPUTED
    the price (``settlementSetTime``, carried as ``ts_event``) and when the
    venue TOLD us (``transactTime``). In the committed captures these differ by
    hours. Only ``ts_event`` survived before this test, so a reconcile could
    establish what the venue decided but not when it disclosed it -- and
    disclosure lag is precisely what a dispute turns on.

    Unrecoverable if not captured on the wire: the frame is gone afterwards.
    """

    def test_the_frames_transact_time_is_recorded_separately_from_ts_event(
        self, closed_book: dict[str, Any], instrument: BinaryOption
    ) -> None:
        payload = closed_book

        snapshot = parse_settlement_snapshot(
            payload, instrument=instrument, ts_init=TS_INIT
        )

        assert snapshot is not None
        expected = parse_rfc3339_nanos(
            payload["marketData"]["transactTime"], field="transactTime"
        )
        assert snapshot.venue_transact_time_ns == expected

    def test_transact_time_and_ts_event_are_genuinely_different_clocks(
        self, closed_book: dict[str, Any], instrument: BinaryOption
    ) -> None:
        """Guards against someone "simplifying" the field away as a duplicate."""
        snapshot = parse_settlement_snapshot(
            closed_book, instrument=instrument, ts_init=TS_INIT
        )

        assert snapshot is not None
        assert snapshot.venue_transact_time_ns != snapshot.ts_event

    def test_the_transact_time_round_trips_through_the_catalog_schema(
        self, closed_book: dict[str, Any], instrument: BinaryOption
    ) -> None:
        snapshot = parse_settlement_snapshot(
            closed_book, instrument=instrument, ts_init=TS_INIT
        )
        assert snapshot is not None

        restored = VenueSettlementSnapshot.from_dict(snapshot.to_dict())

        assert restored.venue_transact_time_ns == snapshot.venue_transact_time_ns
