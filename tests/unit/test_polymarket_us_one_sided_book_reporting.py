"""A one-sided book is EXPECTED. Reporting it must not sound like a failure.

Commit ``b6e4982`` (BL-18) split depth capture from quoting: a book with asks
and no bids still records its ask ladder as ``OrderBookDepth10`` while
``parse_book_top`` refuses to invent a bid, so no ``QuoteTick`` forms. That
behaviour is correct and is NOT under test here -- it is pinned in
``test_polymarket_us_depth_parsing`` and ``test_polymarket_us_tape_routing``
and must keep passing on its own merits.

What was wrong was the REPORTING. The refusal arrived at ``_try_parse`` as a
bare ``VenuePayloadError``, indistinguishable from a genuinely malformed
payload, and was logged at ERROR once per frame. A live capture of ~60 weather
markets emitted 85 ERROR lines in its first minute -- roughly 50,000 over a
ten-hour unattended run -- which buries the one real error an operator needs
to see. The venue's own normal state is an empty bid side (the repo's measured
median top-of-book bid is 0.3 contracts).

These tests pin three things:

1. the benign condition is DISTINGUISHABLE AT THE CALL SITE by TYPE, not by
   message text -- ``EmptyBookSideError`` is raised only for an empty side;
2. it is reported once per INSTRUMENT with running counters, never once per
   frame, mirroring ``_report_new_silent_subscriptions``;
3. a payload malformed for any OTHER reason is still loud, and depth capture
   is byte-for-byte unchanged in both cases.
"""

from __future__ import annotations

import ast
import asyncio
import json
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

import pytest
from nautilus_trader.common.component import LiveClock, MessageBus
from nautilus_trader.config import InstrumentProviderConfig
from nautilus_trader.data.engine import DataEngine
from nautilus_trader.model.data import (
    InstrumentStatus,
    MarkPriceUpdate,
    OrderBookDepth10,
    QuoteTick,
)
from nautilus_trader.model.instruments import BinaryOption
from nautilus_trader.test_kit.stubs.component import TestComponentStubs

from breezy.adapters.polymarket_us.config import PolymarketUSDataClientConfig
from breezy.adapters.polymarket_us.data import (
    MISSING_ROUTING_KEY_WARN_EVERY,
    PolymarketUSDataClient,
    build_data_client,
    should_report_at_count,
    should_warn_at_count,
)
from breezy.adapters.polymarket_us.errors import EmptyBookSideError, VenuePayloadError
from breezy.adapters.polymarket_us.parsing import (
    parse_binary_option,
    parse_book_levels,
    parse_book_top,
)
from breezy.adapters.polymarket_us.symbology import POLYMARKET_US_VENUE
from tests.unit.test_polymarket_us_tape_routing import (
    CLIENT_NAME,
    RAW,
    SLUG,
    Feed,
    Harness,
    Provider,
    load_raw,
    make_instrument,
    market_frame,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_MODULE = REPO_ROOT / "src" / "breezy" / "adapters" / "polymarket_us" / "data.py"

#: A second, genuinely different weather market on the same ladder. Used to
#: prove a NEW failing instrument still produces a fresh report.
OTHER_SLUG = "tc-temp-nychigh-2026-08-26-lt79f"


def make_other_instrument() -> BinaryOption:
    """The same fixture market, re-slugged to a different climate day.

    Re-slugged through the raw TEXT rather than the parsed dict because the
    slug appears in ``marketSides[].identifier`` as well as ``market.slug``
    and the parser cross-checks the two.
    """
    raw = (RAW / "market_open_510636_by_slug.json").read_text(encoding="utf-8")
    payload: dict[str, Any] = json.loads(raw.replace(SLUG, OTHER_SLUG))
    return parse_binary_option(payload, venue=POLYMARKET_US_VENUE, ts_init=0)


def one_sided_frame(slug: str = SLUG) -> dict[str, Any]:
    """A real venue frame with the bid side emptied -- the NORMAL thin-market state."""
    frame = load_raw("book_open_510636.json")
    frame["marketData"]["marketSlug"] = slug
    frame["marketData"]["bids"] = []
    return frame


def _level(price: str, qty: str = "5.0000") -> dict[str, Any]:
    """A book level in the venue's own amount-object shape."""
    return {"px": {"value": price, "currency": "USD"}, "qty": qty}


def malformed_frame(slug: str = SLUG) -> dict[str, Any]:
    """A frame malformed for a reason that is NOT an empty side.

    A crossed book: the best bid is above the best offer. That is a genuine
    venue-integrity fault, not a routine thin market, and must stay loud.
    """
    frame = load_raw("book_open_510636.json")
    frame["marketData"]["marketSlug"] = slug
    frame["marketData"]["bids"] = [_level("0.9900")]
    frame["marketData"]["offers"] = [_level("0.0100")]
    return frame


@pytest.fixture(name="loop")
def _loop() -> Iterator[asyncio.AbstractEventLoop]:
    loop = asyncio.new_event_loop()
    try:
        yield loop
    finally:
        loop.close()


@pytest.fixture(name="harness")
def _harness(loop: asyncio.AbstractEventLoop) -> Harness:
    """Two instruments, so a second failing market is representable."""
    instruments = [make_instrument(), make_other_instrument()]
    clock = LiveClock()
    msgbus: MessageBus = TestComponentStubs.msgbus()
    cache = TestComponentStubs.cache()
    for instrument in instruments:
        cache.add_instrument(instrument)
    engine = DataEngine(msgbus=msgbus, cache=cache, clock=clock)
    feeds: list[Feed] = []

    def feed_factory(handler: Any) -> Feed:
        feed = Feed(handler)
        feeds.append(feed)
        return feed

    client: PolymarketUSDataClient = build_data_client(
        loop=loop,
        name=CLIENT_NAME,
        config=PolymarketUSDataClientConfig(
            allow_foreign_origin=True,
            api_base_url="https://api.example.invalid",
            gateway_base_url="https://gateway.example.invalid",
            ws_url="wss://api.example.invalid",
            market_slugs=(SLUG, OTHER_SLUG),
            instrument_reload_interval_mins=5,
            user_agent="breezy-test/1.0 (+mailto:ops@example.invalid)",
            instrument_provider=InstrumentProviderConfig(load_all=True),
        ),
        msgbus=msgbus,
        cache=cache,
        clock=clock,
        instrument_provider=Provider(instruments),
        feed_factory=feed_factory,
    )
    engine.register_client(client)
    harness = Harness(client, feeds[0])
    msgbus.subscribe(topic="data.*", handler=harness.seen.append)
    return harness


# ---------------------------------------------------------------------------
# The distinction, at the parsing seam: TYPE, not message text
# ---------------------------------------------------------------------------


class TestTheBenignConditionIsItsOwnType:
    def test_an_empty_bid_side_raises_the_dedicated_subclass(self) -> None:
        """The call site must be able to tell benign from real WITHOUT a substring match."""
        with pytest.raises(EmptyBookSideError) as excinfo:
            parse_book_top(one_sided_frame())

        assert excinfo.value.side == "bids"

    def test_an_empty_offer_side_raises_the_dedicated_subclass(self) -> None:
        frame = load_raw("book_open_510636.json")
        frame["marketData"]["offers"] = []

        with pytest.raises(EmptyBookSideError) as excinfo:
            parse_book_top(frame)

        assert excinfo.value.side == "offers"

    def test_the_empty_side_error_is_still_a_venue_payload_error(self) -> None:
        """BL-18 preservation: every existing ``except``/``raises`` keeps working."""
        assert issubclass(EmptyBookSideError, VenuePayloadError)

    def test_a_crossed_book_is_NOT_an_empty_side_error(self) -> None:
        """The substance of the fix: a real fault must not be classified benign."""
        with pytest.raises(VenuePayloadError) as excinfo:
            parse_book_top(malformed_frame())

        assert not isinstance(excinfo.value, EmptyBookSideError)

    def test_a_malformed_level_is_NOT_an_empty_side_error(self) -> None:
        frame = load_raw("book_open_510636.json")
        frame["marketData"]["bids"] = [{"px": "not-an-amount-object", "qty": "5.0000"}]

        with pytest.raises(VenuePayloadError) as excinfo:
            parse_book_top(frame)

        assert not isinstance(excinfo.value, EmptyBookSideError)

    def test_a_fully_empty_book_is_still_refused_by_the_depth_parser(self) -> None:
        """Unchanged BL-18 behaviour: padding both sides with zero is not a price."""
        frame = load_raw("book_open_510636.json")
        frame["marketData"]["bids"] = []
        frame["marketData"]["offers"] = []

        with pytest.raises(VenuePayloadError, match="no populated side"):
            parse_book_levels(frame)


# ---------------------------------------------------------------------------
# The cadence: once per instrument, never once per frame
# ---------------------------------------------------------------------------


class TestReportingCadence:
    FRAMES = 50

    def test_a_repeated_one_sided_book_is_reported_once_per_instrument(
        self, harness: Harness
    ) -> None:
        """50 frames must not become 50 log lines.

        The number of report lines is exactly the number of DISTINCT
        instruments seen, which is what ``one_sided_book_instruments``
        counts. The volume stays visible in ``one_sided_book_refusals``.
        """
        for _ in range(self.FRAMES):
            harness.feed.deliver(one_sided_frame())

        assert harness.client.one_sided_book_instruments == 1
        assert harness.client.one_sided_book_refusals == self.FRAMES

    def test_depth_is_still_recorded_on_every_one_sided_frame(self, harness: Harness) -> None:
        """BL-18 is load-bearing: this is a reporting change, not a capture change."""
        for _ in range(self.FRAMES):
            harness.feed.deliver(one_sided_frame())

        depths = harness.of(OrderBookDepth10)
        assert len(depths) == self.FRAMES
        assert [order for order in depths[0].asks if order.size > 0]
        assert [order for order in depths[0].bids if order.size > 0] == []
        assert harness.of(QuoteTick) == []

    def test_the_existing_failure_counters_are_unchanged(self, harness: Harness) -> None:
        """``quote_parse_failures`` still counts every unquotable frame.

        Pinned by ``test_quote_tape_consumer_contract::TestCounterSemantics``.
        The new counters are ADDITIVE and must not cannibalise it.
        """
        for _ in range(self.FRAMES):
            harness.feed.deliver(one_sided_frame())

        assert harness.client.quote_parse_failures == self.FRAMES
        assert harness.client.dropped_frames == 0

    def test_a_new_instrument_produces_a_fresh_report(self, harness: Harness) -> None:
        """A market that goes one-sided for the FIRST TIME must still be seen."""
        for _ in range(self.FRAMES):
            harness.feed.deliver(one_sided_frame())
        assert harness.client.one_sided_book_instruments == 1

        harness.feed.deliver(one_sided_frame(OTHER_SLUG))

        assert harness.client.one_sided_book_instruments == 2
        assert harness.client.one_sided_book_refusals == self.FRAMES + 1

    def test_a_two_sided_book_touches_neither_counter(self, harness: Harness) -> None:
        harness.feed.deliver(market_frame())

        assert harness.client.one_sided_book_refusals == 0
        assert harness.client.one_sided_book_instruments == 0
        assert len(harness.of(QuoteTick)) == 1


# ---------------------------------------------------------------------------
# A real fault stays loud
# ---------------------------------------------------------------------------


class TestAMalformedPayloadStaysLoud:
    def test_a_crossed_book_is_never_counted_as_a_one_sided_book(self, harness: Harness) -> None:
        """If this leaked into the benign bucket, the fix would be a silencer."""
        for _ in range(5):
            harness.feed.deliver(malformed_frame())

        assert harness.client.one_sided_book_refusals == 0
        assert harness.client.one_sided_book_instruments == 0
        assert harness.client.quote_parse_failures == 5

    def test_a_crossed_book_still_yields_no_quote_and_no_depth(self, harness: Harness) -> None:
        """Capture behaviour on the malformed path is unchanged by this fix.

        A crossed book fails BOTH ``parse_book_top`` and ``parse_book_levels``
        -- there is no honest ladder to record -- while the venue's state and
        mark price, which do not depend on the book, are still kept.
        """
        harness.feed.deliver(malformed_frame())

        assert harness.of(QuoteTick) == []
        assert harness.of(OrderBookDepth10) == []
        assert len(harness.of(InstrumentStatus)) == 1
        assert len(harness.of(MarkPriceUpdate)) == 1
        assert harness.client.dropped_frames == 0

    def test_a_malformed_frame_after_a_one_sided_one_is_still_classified_apart(
        self, harness: Harness
    ) -> None:
        """The two conditions must not smear into each other on one instrument."""
        harness.feed.deliver(one_sided_frame())
        harness.feed.deliver(malformed_frame())

        assert harness.client.one_sided_book_refusals == 1
        assert harness.client.one_sided_book_instruments == 1
        assert harness.client.quote_parse_failures == 2


# ---------------------------------------------------------------------------
# Severity, pinned on the shipped source
# ---------------------------------------------------------------------------


def _log_levels_in(method_name: str) -> set[str]:
    """Severities used by one method of the shipped ``data.py``.

    ``Component._log`` is ``cdef readonly`` (``common/component.pxd:226``) so
    the logger cannot be substituted; the repo's established way to pin a
    severity is therefore the AST of the shipped method (see
    ``test_polymarket_us_data::test_the_missing_routing_key_notice_is_logged_at_warning_not_debug``).
    """
    tree = ast.parse(DATA_MODULE.read_text(encoding="utf-8"))
    method = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == method_name
    )
    return {
        node.func.attr
        for node in ast.walk(method)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Attribute)
        and node.func.value.attr == "_log"
    }


class TestSeverity:
    def test_the_one_sided_book_notice_is_not_logged_at_error(self) -> None:
        """The defect exactly: an expected, handled condition logged at ERROR."""
        levels = _log_levels_in("_note_one_sided_book")

        assert "error" not in levels
        assert "warning" not in levels
        assert levels == {"info"}

    def test_the_general_parse_failure_branch_still_logs_at_error(self) -> None:
        """The fix must not turn the loud path down as collateral damage."""
        assert "error" in _log_levels_in("_try_parse")


class TestRateLimitPolicy:
    def test_the_running_total_reports_first_then_on_the_given_cadence(self) -> None:
        assert should_report_at_count(1, every=1000) is True
        assert should_report_at_count(2, every=1000) is False
        assert should_report_at_count(999, every=1000) is False
        assert should_report_at_count(1000, every=1000) is True
        assert should_report_at_count(1001, every=1000) is False
        assert should_report_at_count(2000, every=1000) is True
        assert should_report_at_count(0, every=1000) is False

    def test_the_existing_warn_policy_is_the_same_policy(self) -> None:
        """Generalising must not fork the rule that ``should_warn_at_count`` states."""
        for count in (0, 1, 2, MISSING_ROUTING_KEY_WARN_EVERY, MISSING_ROUTING_KEY_WARN_EVERY + 1):
            assert should_warn_at_count(count) is should_report_at_count(
                count, every=MISSING_ROUTING_KEY_WARN_EVERY
            )


def test_the_counters_are_documented_as_public_observability() -> None:
    """An operator reads these; they must say what they mean."""
    for name in ("one_sided_book_refusals", "one_sided_book_instruments"):
        prop = getattr(PolymarketUSDataClient, name)
        assert isinstance(prop, property)
        assert prop.__doc__, f"{name} must carry an operator-facing docstring"


def test_market_frame_fixture_is_two_sided() -> None:
    """Sanity: the baseline fixture must actually carry both sides."""
    frame: Mapping[str, Any] = market_frame()
    market_data = frame["marketData"]

    assert market_data["bids"]
    assert market_data["offers"]
