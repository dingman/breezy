"""Contracts a CONSUMER of the tape must honour, in executable form.

Three facts that are each safe in isolation and misleading if a reader assumes
the obvious thing:

1. Gap rows are append-only, so BOTH edges of one outage survive forever and
   the ``resolved=False`` row covers every later timestamp. Iterating raw rows
   marks everything after the first-ever reconnect as contaminated -- safe, but
   it silently destroys statistical power in the per-city / per-day breakdowns
   that plan items 1.5.2 and 1.5.4 rest on.
2. ``quote_parse_failures`` and ``dropped_frames`` OVERLAP. They are not a
   partition of the frame count and must never be summed.
3. The tape root is operator-configured, and a path that walks upward with
   ``..`` is refused rather than normalised.
"""

from __future__ import annotations

import json
from typing import ClassVar

import pytest
from nautilus_trader.model.identifiers import InstrumentId

# ``_harness``/``_loop`` are imported for their side effect of registering the
# ``harness``/``loop`` fixtures in this module's namespace -- pytest resolves a
# fixture by the decorated function object, not by its defining module.
from breezy.adapters.polymarket_us.data import MARKET_SLUG_KEY
from breezy.adapters.polymarket_us.tape_records import QuoteTapeGap, resolved_gaps_by_seq
from breezy.runtime.settings import SettingsError, load_quote_tape_settings
from tests.unit.test_polymarket_us_tape_routing import (  # noqa: F401
    SLUG,
    Harness,
    _harness,
    _loop,
    market_frame,
)

INSTRUMENT_ID = InstrumentId.from_str(f"{SLUG}.POLYMARKET_US")


RECORDER_A = "11111111-1111-1111-1111-111111111111"


def gap(
    seq: int, start: int, end: int, resolved: bool, instance: str = RECORDER_A
) -> QuoteTapeGap:
    return QuoteTapeGap(
        instrument_id=INSTRUMENT_ID,
        gap_seq=seq,
        started_ns=start,
        ended_ns=end,
        resolved=resolved,
        recorder_instance_id=instance,
        ts_event=start,
        ts_init=end or start,
    )


class TestGapJoinContract:
    def test_raw_rows_over_exclude_which_is_why_the_contract_exists(self) -> None:
        """Demonstrates the hazard before demonstrating the fix.

        The open row for gap 1 is still on disk after gap 1 closed, and it
        covers every later timestamp forever.
        """
        rows = [gap(1, 100, 0, False), gap(1, 100, 200, True)]

        assert any(row.covers(10_000) for row in rows)

    def test_collapsing_by_gap_seq_prefers_the_resolved_terminus(self) -> None:
        rows = [gap(1, 100, 0, False), gap(1, 100, 200, True)]

        collapsed = resolved_gaps_by_seq(rows)

        assert len(collapsed) == 1
        assert collapsed[0].resolved is True
        assert collapsed[0].ended_ns == 200
        assert collapsed[0].covers(10_000) is False
        assert collapsed[0].covers(150) is True

    def test_a_genuinely_unresolved_gap_survives_collapsing(self) -> None:
        """An outage that never closed MUST keep contaminating what follows."""
        rows = [gap(1, 100, 200, True), gap(2, 300, 0, False)]

        collapsed = resolved_gaps_by_seq(rows)

        assert [row.gap_seq for row in collapsed] == [1, 2]
        assert collapsed[1].resolved is False
        assert collapsed[1].covers(10_000) is True

    def test_the_result_is_ordered_by_gap_seq_regardless_of_input_order(self) -> None:
        """Catalog row order is not guaranteed; the contract must not depend on it."""
        rows = [gap(3, 500, 600, True), gap(1, 100, 0, False), gap(1, 100, 200, True)]

        assert [row.gap_seq for row in resolved_gaps_by_seq(rows)] == [1, 3]

    def test_ordering_of_the_two_edges_within_one_seq_does_not_matter(self) -> None:
        forwards = resolved_gaps_by_seq([gap(1, 100, 0, False), gap(1, 100, 200, True)])
        backwards = resolved_gaps_by_seq([gap(1, 100, 200, True), gap(1, 100, 0, False)])

        assert forwards[0].resolved is backwards[0].resolved is True

    def test_two_instruments_reusing_the_same_gap_seq_do_not_collide(self) -> None:
        """``gap_seq`` is PER-INSTRUMENT, so it is not a key on its own.

        Two markets recorded by one process each number their own outages from
        1. Collapsing on ``gap_seq`` alone would silently discard one city's
        outage and stamp the other city's boundaries onto it -- which is worse
        than no gap dataset, because the contamination filter would then be
        confidently wrong rather than merely absent.
        """
        other = InstrumentId.from_str("tc-temp-denhigh-2026-08-25-lt61f.POLYMARKET_US")
        rows = [
            gap(1, 100, 200, True),
            QuoteTapeGap(
                instrument_id=other,
                gap_seq=1,
                started_ns=900,
                ended_ns=950,
                resolved=True,
                recorder_instance_id=RECORDER_A,
                ts_event=900,
                ts_init=950,
            ),
        ]

        collapsed = resolved_gaps_by_seq(rows)

        assert len(collapsed) == 2
        assert {row.instrument_id for row in collapsed} == {INSTRUMENT_ID, other}
        assert {row.started_ns for row in collapsed} == {100, 900}

    def test_an_open_row_for_one_instrument_does_not_resolve_another(self) -> None:
        """The resolved-preference must not leak across instruments either."""
        other = InstrumentId.from_str("tc-temp-denhigh-2026-08-25-lt61f.POLYMARKET_US")
        rows = [
            gap(1, 100, 0, False),
            QuoteTapeGap(
                instrument_id=other,
                gap_seq=1,
                started_ns=900,
                ended_ns=950,
                resolved=True,
                recorder_instance_id=RECORDER_A,
                ts_event=900,
                ts_init=950,
            ),
        ]

        collapsed = resolved_gaps_by_seq(rows)

        mine = next(r for r in collapsed if r.instrument_id == INSTRUMENT_ID)
        assert mine.resolved is False
        assert mine.covers(10_000) is True

    def test_an_empty_input_collapses_to_nothing(self) -> None:
        assert resolved_gaps_by_seq([]) == []


class TestCounterSemantics:
    """``quote_parse_failures`` and ``dropped_frames`` overlap. Pin it."""

    def test_a_frame_can_increment_both_counters_so_they_cannot_be_summed(
        self, harness: Harness
    ) -> None:
        """A frame carrying only its routing key hits BOTH counters.

        There is no quote in it (so ``quote_parse_failures``) and no other
        record either (so ``dropped_frames``). The two counters therefore
        OVERLAP: they are not a partition of the frame count and summing them
        double-counts this frame. This is exactly the shape a truncated or
        keep-alive-ish payload takes, so it is not a contrived case.
        """
        frame = {"marketData": {MARKET_SLUG_KEY: SLUG}}

        harness.feed.deliver(frame)

        assert harness.client.quote_parse_failures == 1
        assert harness.client.dropped_frames == 1

    def test_the_settled_market_case_increments_only_the_quote_counter(
        self, harness: Harness
    ) -> None:
        """The non-overlapping case, which is why two counters exist at all."""
        frame = json.loads(json.dumps(market_frame()))
        frame["marketData"]["bids"] = []

        harness.feed.deliver(frame)

        assert harness.client.quote_parse_failures == 1
        assert harness.client.dropped_frames == 0


class TestCatalogRootTraversal:
    BASE_ENV: ClassVar[dict[str, str]] = {
        "BREEZY_POLYMARKET_US_QUOTE_TAPE_MIN_FREE_BYTES_WARNING": str(20 * 1024**3),
        "BREEZY_POLYMARKET_US_QUOTE_TAPE_MIN_FREE_BYTES_ERROR": str(10 * 1024**3),
        "BREEZY_POLYMARKET_US_QUOTE_TAPE_MAX_FILE_BYTES_WARNING": str(400 * 1024**3),
        "BREEZY_POLYMARKET_US_QUOTE_TAPE_MAX_FILE_BYTES_ERROR": str(500 * 1024**3),
        "POLYMARKET_US_API_BASE": "https://api.example.invalid",
        "POLYMARKET_US_GATEWAY_BASE": "https://gateway.example.invalid",
        "POLYMARKET_US_WS_URL": "wss://ws.example.invalid",
        "POLYMARKET_US_MARKET_SLUGS": SLUG,
        "POLYMARKET_US_USER_AGENT": "breezy-test/1.0 (+mailto:ops@example.invalid)",
    }

    def env(self, root: str) -> dict[str, str]:
        return {**self.BASE_ENV, "BREEZY_POLYMARKET_US_QUOTE_TAPE_CATALOG": root}

    @pytest.mark.parametrize(
        "root",
        [
            "/srv/breezy/../../etc/breezy",
            "/srv/../srv/breezy/venue",
            "/srv/breezy/venue/..",
        ],
    )
    def test_an_upward_traversal_segment_is_refused_not_normalised(
        self, root: str
    ) -> None:
        """Refused rather than resolved, so the configured path IS the path.

        Silently normalising would mean the directory an operator reads in the
        unit file is not the directory the tape lands in -- and the tape is the
        one artifact that cannot be re-created if it lands somewhere unwatched.
        """
        with pytest.raises(SettingsError, match=r"\.\."):
            load_quote_tape_settings(self.env(root))

    def test_an_ordinary_absolute_path_is_still_accepted(self) -> None:
        settings = load_quote_tape_settings(self.env("/srv/breezy/venue/polymarket_us"))

        assert str(settings.catalog_root) == "/srv/breezy/venue/polymarket_us"

    def test_a_directory_merely_containing_dots_is_not_confused_with_traversal(
        self,
    ) -> None:
        """``..`` is a path SEGMENT, not a substring. ``v1..2`` is a real name."""
        settings = load_quote_tape_settings(self.env("/srv/breezy/tape..v2"))

        assert str(settings.catalog_root) == "/srv/breezy/tape..v2"


class TestRecorderInstanceIdentityOnTheRecord:
    """A gap row must carry the identity of the recorder that produced it.

    ``gap_seq`` restarts at 1 on every recorder restart. The reviewer confirmed
    the failure direction is UNDER-exclusion -- i.e. unsafe, biasing toward a
    false GO: merging catalogs from two instance directories lets a new
    instance's ``seq=1`` OVERWRITE a genuine unresolved outage from the prior
    instance, and the real contamination disappears from the result.

    Loader-side partitioning can be added later; the FIELD cannot. A row with
    no instance identity cannot be partitioned after the fact, however good the
    loader gets. The identity used is the NATIVE Nautilus node ``instance_id``
    -- not a second scheme -- so the field and the streaming directory name
    (``system/kernel.py:589``) agree.
    """

    def test_the_recorder_instance_id_is_part_of_the_collapse_key(self) -> None:
        """Two instances each numbering their first outage 1 must both survive."""
        first = QuoteTapeGap(
            instrument_id=INSTRUMENT_ID,
            gap_seq=1,
            started_ns=100,
            ended_ns=0,
            resolved=False,
            recorder_instance_id="11111111-1111-1111-1111-111111111111",
            ts_event=100,
            ts_init=100,
        )
        second = QuoteTapeGap(
            instrument_id=INSTRUMENT_ID,
            gap_seq=1,
            started_ns=900,
            ended_ns=950,
            resolved=True,
            recorder_instance_id="22222222-2222-2222-2222-222222222222",
            ts_event=900,
            ts_init=950,
        )

        collapsed = resolved_gaps_by_seq([first, second])

        assert len(collapsed) == 2
        # The prior instance's genuine UNRESOLVED outage must not be erased by
        # the later instance's seq=1 -- that is the under-exclusion hazard.
        survivor = next(
            row for row in collapsed if row.recorder_instance_id == first.recorder_instance_id
        )
        assert survivor.resolved is False
        assert survivor.covers(10_000) is True

    def test_the_recorder_instance_id_round_trips_through_the_catalog_schema(
        self,
    ) -> None:
        row = QuoteTapeGap(
            instrument_id=INSTRUMENT_ID,
            gap_seq=3,
            started_ns=100,
            ended_ns=200,
            resolved=True,
            recorder_instance_id="33333333-3333-3333-3333-333333333333",
            ts_event=100,
            ts_init=200,
        )

        restored = QuoteTapeGap.from_dict(row.to_dict())

        assert restored.recorder_instance_id == row.recorder_instance_id

    def test_a_blank_recorder_instance_id_is_refused_at_construction(self) -> None:
        """An empty identity is a silent hole, not a lenient default.

        A row that claims to be identifiable but is not is worse than one that
        raises, because the loader will happily partition on ``""`` and
        reproduce the exact collision this field exists to prevent.
        """
        with pytest.raises(ValueError, match="recorder_instance_id"):
            QuoteTapeGap(
                instrument_id=INSTRUMENT_ID,
                gap_seq=1,
                started_ns=100,
                ended_ns=200,
                resolved=True,
                recorder_instance_id="",
                ts_event=100,
                ts_init=200,
            )
