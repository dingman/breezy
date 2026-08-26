"""Two operational series that make the tape honest about itself.

Neither has a native Nautilus carrier, and both were checked before being
written (see the module docstring of ``adapters.polymarket_us.tape_records``).

**QuoteTapeGap** -- a reconnect drops quotes permanently. The socket's
supervisor reconnects and replays subscriptions, so the recorded tape RESUMES
and nothing in the parquet says it ever stopped. Reconnect storms plausibly
correlate with fast-moving books, i.e. with strike crossings, which are exactly
the periods the Phase 1.5 study cares about. If gaps correlate with volatility
and are invisible, the surviving sample skews toward calm periods and biases
the gate toward a FALSE GO. A study must be able to exclude or flag affected
joins, which means the gaps have to be ON DISK next to the quotes.

**VenueClockOffset** -- the read-only auth smoke recorded a ~131 second host
clock offset. ``ts_event`` correctly carries the venue's ``transactTime`` and
``ts_init`` carries host receipt time, so the offset is measurable from the
frames themselves, but only if it is recorded as it drifts.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from nautilus_trader.cache.cache import Cache
from nautilus_trader.common.component import TestClock
from nautilus_trader.config import CacheConfig
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog
from nautilus_trader.persistence.writer import StreamingFeatherWriter
from nautilus_trader.serialization.arrow.serializer import ArrowSerializer

from breezy.adapters.polymarket_us.tape_records import (
    QuoteTapeGap,
    VenueClockOffset,
)
from tests.unit.test_quote_tape_recorder import SLUG, make_instrument


class TestQuoteTapeGap:
    def make(self, **overrides: object) -> QuoteTapeGap:
        base: dict[str, object] = {
            "instrument_id": InstrumentId.from_str(f"{SLUG}.POLYMARKET_US"),
            "gap_seq": 1,
            "started_ns": 1_000_000_000,
            "ended_ns": 4_000_000_000,
            "resolved": True,
            "recorder_instance_id": "11111111-1111-1111-1111-111111111111",
            "ts_event": 1_000_000_000,
            "ts_init": 4_000_000_000,
        }
        base.update(overrides)
        return QuoteTapeGap(**base)  # type: ignore[arg-type]

    def test_a_gap_states_the_interval_during_which_quotes_are_missing(self) -> None:
        gap = self.make()

        assert gap.started_ns == 1_000_000_000
        assert gap.ended_ns == 4_000_000_000
        assert gap.duration_ns == 3_000_000_000

    def test_an_unresolved_gap_is_marked_as_such_rather_than_given_a_fake_end(self) -> None:
        """A gap open when the process died has no end. Zero would read as instant."""
        gap = self.make(ended_ns=0, resolved=False)

        assert gap.resolved is False
        assert gap.duration_ns is None

    def test_a_gap_is_keyed_by_instrument_so_a_study_can_join_it_to_the_quotes(self) -> None:
        gap = self.make()

        assert gap.instrument_id == InstrumentId.from_str(f"{SLUG}.POLYMARKET_US")

    def test_a_gap_covers_a_timestamp_inside_its_interval_only(self) -> None:
        """The predicate a study actually calls to exclude a contaminated join."""
        gap = self.make()

        assert gap.covers(1_000_000_000) is True
        assert gap.covers(2_500_000_000) is True
        assert gap.covers(4_000_000_000) is True
        assert gap.covers(999_999_999) is False
        assert gap.covers(4_000_000_001) is False

    def test_an_unresolved_gap_covers_everything_after_it_started(self) -> None:
        """Fail loud, not convenient: an open gap contaminates all later joins."""
        gap = self.make(ended_ns=0, resolved=False)

        assert gap.covers(1_000_000_000) is True
        assert gap.covers(10_000_000_000_000) is True
        assert gap.covers(1) is False

    def test_a_gap_that_ends_before_it_starts_is_refused(self) -> None:
        with pytest.raises(ValueError, match="ended_ns"):
            self.make(started_ns=5_000_000_000, ended_ns=1_000_000_000)


class TestVenueClockOffset:
    def test_it_records_the_signed_offset_between_host_and_venue_clocks(self) -> None:
        offset = VenueClockOffset(
            source="ws-transact-time",
            offset_ns=-131_000_000_000,
            samples=42,
            ts_event=1_000_000_000,
            ts_init=1_000_000_000,
        )

        assert offset.offset_ns == -131_000_000_000
        assert offset.offset_seconds == pytest.approx(-131.0)
        assert offset.samples == 42

    def test_the_source_is_recorded_so_a_reader_knows_what_was_compared(self) -> None:
        offset = VenueClockOffset(
            source="ws-transact-time",
            offset_ns=1,
            samples=1,
            ts_event=1,
            ts_init=1,
        )

        assert offset.source == "ws-transact-time"


class TestBothRoundTripToDiskAndBack:
    """The property that matters: they are readable by a separate reader."""

    def test_gaps_and_offsets_survive_the_streaming_writer_and_the_catalog(
        self, tmp_path: Path
    ) -> None:
        instrument = make_instrument(SLUG)
        cache = Cache(database=None, config=CacheConfig())
        cache.add_instrument(instrument)
        writer = StreamingFeatherWriter(
            path=str(tmp_path / "live" / "instance-1"),
            cache=cache,
            clock=TestClock(),
            include_types=[QuoteTapeGap, VenueClockOffset],
        )
        writer.write(
            QuoteTapeGap(
                instrument_id=instrument.id,
                gap_seq=1,
                started_ns=1_000_000_000,
                ended_ns=4_000_000_000,
                resolved=True,
                recorder_instance_id="11111111-1111-1111-1111-111111111111",
                ts_event=1_000_000_000,
                ts_init=4_000_000_000,
            )
        )
        writer.write(
            VenueClockOffset(
                source="ws-transact-time",
                offset_ns=-131_000_000_000,
                samples=7,
                ts_event=5_000_000_000,
                ts_init=5_000_000_000,
            )
        )
        writer.close()

        reader = ParquetDataCatalog(tmp_path)
        reader.convert_stream_to_data("instance-1", QuoteTapeGap, subdirectory="live")
        reader.convert_stream_to_data("instance-1", VenueClockOffset, subdirectory="live")

        gaps = [row.data for row in reader.query(data_cls=QuoteTapeGap)]
        offsets = [row.data for row in reader.query(data_cls=VenueClockOffset)]

        assert len(gaps) == 1
        assert gaps[0].started_ns == 1_000_000_000
        assert gaps[0].ended_ns == 4_000_000_000
        assert gaps[0].resolved is True
        assert gaps[0].instrument_id == instrument.id
        assert len(offsets) == 1
        assert offsets[0].offset_ns == -131_000_000_000
        assert offsets[0].samples == 7

    def test_a_missing_column_raises_on_read_rather_than_defaulting(self) -> None:
        """Schema drift must be loud.

        The catalog infers a schema from the first fragment and coerces later
        ones silently. A hand-written decoder that raises on a missing column is
        the only reliable detection point, so it is asserted here.
        """
        with pytest.raises(KeyError):
            QuoteTapeGap.from_dict({"instrument_id": f"{SLUG}.POLYMARKET_US"})

    def test_the_arrow_encoder_accepts_a_single_object_and_a_list(self) -> None:
        """Both call shapes occur.

        `ArrowSerializer.serialize` hands the encoder ONE object
        (`serializer.py:249`) while `catalog.write_data` hands it a list. An
        encoder written for only one of them fails at whichever call site the
        tests do not exercise.
        """
        gap = QuoteTapeGap(
            instrument_id=InstrumentId.from_str(f"{SLUG}.POLYMARKET_US"),
            gap_seq=1,
            started_ns=1,
            ended_ns=2,
            resolved=True,
            recorder_instance_id="11111111-1111-1111-1111-111111111111",
            ts_event=1,
            ts_init=2,
        )

        assert ArrowSerializer.serialize_batch([gap], data_cls=QuoteTapeGap).num_rows == 1
        assert ArrowSerializer.serialize(gap, QuoteTapeGap).num_rows == 1
