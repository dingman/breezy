"""Tests for the durable gap ledger (`src/breezy/ingest/gaps.py`).

Governing ruling: `docs/plans/PHASE_CD_COLLECTION_DURABILITY_DESIGN.md` SS3
(WI-10). Every test uses a frozen/injected nanosecond clock -- never
`time.time()` -- and performs zero network I/O. No hard-coded absolute
"today"; every instant used is explicitly constructed from a fixed
calendar date via `_ns_at`, so the suite cannot rot into a date time-bomb.

Test groups, matching the design's RED list:
  1. Expected-set construction: complete history, one missing day, the
     08:00->11:00 ET review-extension boundary, UTC/ET disagreement.
  2. Idempotence: reconciling twice writes byte-identical store contents.
  3. Resolution: a filled gap becomes RESOLVED and stops alarming.
  4. Severity ladder, parameterised.
  5. Real `SqliteStateStore` durability through a second connection.
  6. Revision tracking: revision_seq increase, correction_flag,
     is_superseded -- each independently.
  7. `ACKNOWLEDGED_LOST`: mutes re-notify, never transitions back, stays
     visible.
  8. Tampering: an entry missing while listed in the manifest, and
     corrupt bytes at every codec layer.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import FrozenInstanceError, dataclass
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from breezy.ingest.gaps import (
    _MANIFEST_KEY,
    CRITICAL_AT_OR_BELOW_DAYS_REMAINING,
    GAP_KEY_PREFIX,
    RETENTION_DAYS_ASSUMPTION,
    WARN_AT_OR_BELOW_DAYS_REMAINING,
    GapEntry,
    GapSeverity,
    GapState,
    ReconcileResult,
    RevisionEvent,
    TamperedGapLedgerError,
    _entry_key,
    _hw_key,
    _manifest_id,
    acknowledge,
    days_remaining_until_retention_loss,
    get_entry,
    local_standard_date,
    most_recent_completed_climate_day,
    reconcile,
    review_extension_end_ns,
    severity_for,
    site_entries,
)

VENUE = "polymarket_us"
CITY = "NYC"
STATION = "NYC"
OTHER_STATION = "LGA"
NS_PER_SECOND = 1_000_000_000
NYC_STD_UTC_OFFSET_HOURS = -5.0
SETTLEMENT_DELAY_TIME_LOCAL = "11:00"
SETTLEMENT_DELAY_TIMEZONE = "America/New_York"


def _ns_at(iso_local: str, tz_name: str = SETTLEMENT_DELAY_TIMEZONE) -> int:
    """Build a UNIX-nanosecond instant from a naive local ISO string in `tz_name`."""
    naive = dt.datetime.fromisoformat(iso_local)
    aware = naive.replace(tzinfo=ZoneInfo(tz_name))
    return int(aware.timestamp()) * NS_PER_SECOND


class _FakeStore:
    """An in-memory StateStore matching `gaps.StateStore` structurally."""

    def __init__(self) -> None:
        self.data: dict[str, bytes] = {}

    def get(self, key: str) -> bytes | None:
        return self.data.get(key)

    def set(self, key: str, value: bytes) -> None:
        self.data[key] = value


@dataclass(frozen=True, slots=True)
class _Record:
    """A minimal `gaps.ObservedRecord`-shaped stand-in for `NwsClimateDay`."""

    station: str
    climate_day: dt.date
    ts_init: int
    is_final: bool
    revision_seq: int
    correction_flag: bool = False
    is_superseded: bool = False


def _reconcile(
    store: _FakeStore,
    now_ns: int,
    records: tuple[_Record, ...] = (),
    *,
    retention_days: int = RETENTION_DAYS_ASSUMPTION,
    station: str = STATION,
) -> ReconcileResult:
    return reconcile(
        store=store,
        now_ns=now_ns,
        venue=VENUE,
        city=CITY,
        station=station,
        std_utc_offset_hours=NYC_STD_UTC_OFFSET_HOURS,
        settlement_delay_time_local=SETTLEMENT_DELAY_TIME_LOCAL,
        settlement_delay_timezone=SETTLEMENT_DELAY_TIMEZONE,
        records=records,
        retention_days=retention_days,
    )


# ---------------------------------------------------------------------------
# 1. Expected-set construction
# ---------------------------------------------------------------------------


def test_complete_history_produces_no_gaps() -> None:
    # Arrange: every candidate day in a 1-day retention window has a final.
    now_ns = _ns_at("2026-01-11T12:00:00")  # well past the 11:00 ET extension
    day = dt.date(2026, 1, 10)
    records = (_Record(station=STATION, climate_day=day, ts_init=1, is_final=True, revision_seq=1),)

    # Act
    result = _reconcile(store := _FakeStore(), now_ns, records, retention_days=1)

    # Assert
    assert result.opened == ()
    assert result.resolved == ()
    # NO GAP -- which is a statement about STATE, not about the absence of a
    # row. The day IS recorded (already RESOLVED, never OPEN) so a later
    # corrected reissue of this very final has a baseline to be compared
    # against; asserting `site_entries(...) == ()` here would re-assert the
    # settlement-correctness defect that made `RevisionEvent` unreachable for
    # every cleanly-collected day. See section 6b.
    assert [e.state for e in site_entries(store, VENUE, CITY)] == [GapState.RESOLVED]
    assert not [e for e in site_entries(store, VENUE, CITY) if e.state is GapState.OPEN]


def test_one_missing_day_opens_exactly_one_entry_with_the_reconcile_instant() -> None:
    now_ns = _ns_at("2026-01-11T12:00:00")
    day = dt.date(2026, 1, 10)

    result = _reconcile(store := _FakeStore(), now_ns, retention_days=1)

    assert result.opened == (day,)
    entries = site_entries(store, VENUE, CITY)
    assert len(entries) == 1
    entry = entries[0]
    assert entry.venue == VENUE
    assert entry.city == CITY
    assert entry.climate_day == day
    assert entry.state is GapState.OPEN
    assert entry.first_detected_ns == now_ns
    assert entry.last_reconciled_ns == now_ns
    assert entry.resolved_at_ns is None
    assert entry.observed_revision_seq == 0


def test_review_extension_not_yet_elapsed_is_not_a_gap() -> None:
    # The instant strictly before the 11:00 ET review-extension deadline.
    before_ns = _ns_at("2026-01-11T10:59:59")
    result = _reconcile(store := _FakeStore(), before_ns, retention_days=1)

    assert result.opened == ()
    assert site_entries(store, VENUE, CITY) == ()


def test_review_extension_elapsed_is_a_gap() -> None:
    # The instant at-or-after the 11:00 ET review-extension deadline.
    after_ns = _ns_at("2026-01-11T11:00:00")
    result = _reconcile(_FakeStore(), after_ns, retention_days=1)

    assert result.opened == (dt.date(2026, 1, 10),)


def test_a_final_arriving_inside_the_review_window_never_creates_an_entry() -> None:
    # 09:30 ET is inside the 08:00-11:00 review window: the day is not yet
    # EXPECTED, so even though nothing was ever observed, no entry is
    # written -- the false positive is designed out, not suppressed later.
    now_ns = _ns_at("2026-01-11T09:30:00")
    result = _reconcile(store := _FakeStore(), now_ns, retention_days=1)

    assert result.opened == ()
    assert site_entries(store, VENUE, CITY) == ()


def test_utc_and_et_disagreement_is_attributed_to_the_et_climate_day() -> None:
    # 2026-01-15T02:00:00Z is 2026-01-14T21:00:00 in fixed -5h standard time
    # -- a UTC-only reading would compute the wrong climate day entirely.
    now_ns = int(dt.datetime(2026, 1, 15, 2, 0, 0, tzinfo=dt.UTC).timestamp()) * NS_PER_SECOND

    assert local_standard_date(now_ns, NYC_STD_UTC_OFFSET_HOURS) == dt.date(2026, 1, 14)
    most_recent = most_recent_completed_climate_day(now_ns, NYC_STD_UTC_OFFSET_HOURS)
    assert most_recent == dt.date(2026, 1, 13)


def test_utc_et_disagreement_end_to_end_resolves_against_the_et_day() -> None:
    # A record stamped for the ET-correct climate day resolves the gap even
    # though `now_ns`'s raw UTC calendar date is one day later.
    now_ns = _ns_at("2026-01-15T12:00:00")  # ET noon, well past the extension
    et_day = dt.date(2026, 1, 14)
    records = (
        _Record(station=STATION, climate_day=et_day, ts_init=1, is_final=True, revision_seq=1),
    )

    result = _reconcile(store := _FakeStore(), now_ns, records, retention_days=1)

    assert result.opened == ()
    # Recorded against the ET climate day and already RESOLVED -- no OPEN gap.
    # (See the note on `test_complete_history_produces_no_gaps` for why this
    # is not `== ()`.)
    entries = site_entries(store, VENUE, CITY)
    assert [(e.climate_day, e.state) for e in entries] == [(et_day, GapState.RESOLVED)]


def test_observed_records_from_a_different_station_are_ignored() -> None:
    now_ns = _ns_at("2026-01-11T12:00:00")
    day = dt.date(2026, 1, 10)
    records = (
        _Record(station=OTHER_STATION, climate_day=day, ts_init=1, is_final=True, revision_seq=1),
    )

    result = _reconcile(_FakeStore(), now_ns, records, retention_days=1)

    # The other station's product does not count as an observation for ours.
    assert result.opened == (day,)


def test_a_lower_ranked_duplicate_record_never_overrides_the_higher_ranked_one() -> None:
    # Two records for the same day: a final arrives before a stale
    # re-delivery of an earlier preliminary in the same batch. Selection
    # must keep the final (higher `(is_final, ts_init, revision_seq)`
    # rank), never let a later-iterated but lower-ranked record win.
    now_ns = _ns_at("2026-01-11T12:00:00")
    day = dt.date(2026, 1, 10)
    higher = _Record(station=STATION, climate_day=day, ts_init=5, is_final=True, revision_seq=2)
    lower = _Record(station=STATION, climate_day=day, ts_init=1, is_final=False, revision_seq=1)

    result = _reconcile(_FakeStore(), now_ns, (higher, lower), retention_days=1)

    assert result.opened == ()


# ---------------------------------------------------------------------------
# 2. Idempotence
# ---------------------------------------------------------------------------


def test_reconciling_twice_with_the_same_clock_writes_identical_bytes() -> None:
    now_ns = _ns_at("2026-01-11T12:00:00")
    store = _FakeStore()

    _reconcile(store, now_ns, retention_days=1)
    snapshot = dict(store.data)

    _reconcile(store, now_ns, retention_days=1)

    assert store.data == snapshot


def test_reconciling_twice_reports_no_new_transitions_the_second_time() -> None:
    now_ns = _ns_at("2026-01-11T12:00:00")
    store = _FakeStore()

    first = _reconcile(store, now_ns, retention_days=1)
    second = _reconcile(store, now_ns, retention_days=1)

    assert first.opened == (dt.date(2026, 1, 10),)
    assert second.opened == ()
    assert second.resolved == ()
    assert second.revisions == ()


# ---------------------------------------------------------------------------
# 3. Resolution
# ---------------------------------------------------------------------------


def test_a_filled_gap_becomes_resolved_and_stops_alarming() -> None:
    # Both instants fall on the SAME ET calendar day (only the hour differs)
    # so `most_recent_completed_climate_day` never advances between calls --
    # otherwise a later call would legitimately open a NEW day's gap too,
    # which is not what this test is isolating.
    store = _FakeStore()
    day = dt.date(2026, 1, 10)
    opened_ns = _ns_at("2026-01-11T12:00:00")
    resolved_ns = _ns_at("2026-01-11T14:00:00")

    opened = _reconcile(store, opened_ns, retention_days=1)
    assert opened.opened == (day,)

    records = (_Record(station=STATION, climate_day=day, ts_init=1, is_final=True, revision_seq=1),)
    resolved = _reconcile(store, resolved_ns, records, retention_days=1)

    assert resolved.opened == ()
    assert resolved.resolved == (day,)
    entry = get_entry(store, VENUE, CITY, day)
    assert entry is not None
    assert entry.state is GapState.RESOLVED
    assert entry.resolved_at_ns == resolved_ns
    assert entry.observed_revision_seq == 1
    assert entry.observed_is_final is True

    # A further reconcile with the same observation never re-alarms.
    again = _reconcile(store, resolved_ns, records, retention_days=1)
    assert again.opened == ()
    assert again.resolved == ()
    assert get_entry(store, VENUE, CITY, day).state is GapState.RESOLVED  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# 4. Severity ladder
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("days_remaining", "expected"),
    [
        (100, GapSeverity.INFO),
        (6, GapSeverity.INFO),
        (WARN_AT_OR_BELOW_DAYS_REMAINING + 1, GapSeverity.INFO),
        (WARN_AT_OR_BELOW_DAYS_REMAINING, GapSeverity.WARN),
        (3, GapSeverity.WARN),
        (CRITICAL_AT_OR_BELOW_DAYS_REMAINING + 1, GapSeverity.WARN),
        (CRITICAL_AT_OR_BELOW_DAYS_REMAINING, GapSeverity.CRITICAL),
        (1, GapSeverity.CRITICAL),
        (0, GapSeverity.CRITICAL),
        (-1, GapSeverity.CRITICAL),
        (-100, GapSeverity.CRITICAL),
    ],
)
def test_severity_ladder(days_remaining: int, expected: GapSeverity) -> None:
    today = dt.date(2026, 1, 20)
    climate_day = today - dt.timedelta(days=RETENTION_DAYS_ASSUMPTION - days_remaining)

    assert days_remaining_until_retention_loss(climate_day, today) == days_remaining
    assert severity_for(climate_day, today) == expected


def test_severity_ladder_respects_an_explicit_retention_days() -> None:
    today = dt.date(2026, 1, 20)
    climate_day = today - dt.timedelta(days=1)  # 1 day old

    # With a 2-day retention window, 1 day old leaves 1 day remaining: CRITICAL.
    assert severity_for(climate_day, today, retention_days=2) == GapSeverity.CRITICAL
    # With a 10-day retention window, 1 day old leaves 9 remaining: INFO.
    assert severity_for(climate_day, today, retention_days=10) == GapSeverity.INFO


# ---------------------------------------------------------------------------
# 5. Real SqliteStateStore durability
# ---------------------------------------------------------------------------


def test_ledger_survives_a_real_sqlite_round_trip_through_a_second_connection(
    tmp_path: Any,
) -> None:
    from breezy.runtime.sqlite_store import SqliteStateStore

    db_path = tmp_path / "gaps.db"
    now_ns = _ns_at("2026-01-11T12:00:00")
    day = dt.date(2026, 1, 10)

    store1 = SqliteStateStore(db_path)
    result = reconcile(
        store=store1,
        now_ns=now_ns,
        venue=VENUE,
        city=CITY,
        station=STATION,
        std_utc_offset_hours=NYC_STD_UTC_OFFSET_HOURS,
        settlement_delay_time_local=SETTLEMENT_DELAY_TIME_LOCAL,
        settlement_delay_timezone=SETTLEMENT_DELAY_TIMEZONE,
        records=(),
        retention_days=1,
    )
    assert result.opened == (day,)
    store1.close()

    # A SECOND, independent connection over the same file must see the write.
    store2 = SqliteStateStore(db_path)
    try:
        entries = site_entries(store2, VENUE, CITY)
        assert len(entries) == 1
        assert entries[0].climate_day == day
        assert entries[0].state is GapState.OPEN
        assert entries[0].first_detected_ns == now_ns
    finally:
        store2.close()


# ---------------------------------------------------------------------------
# 6. Revision tracking
# ---------------------------------------------------------------------------


def _resolved_gap_store(*, revision_seq: int = 1) -> tuple[_FakeStore, dt.date, int]:
    # Same-day instants (see the comment on
    # `test_a_filled_gap_becomes_resolved_and_stops_alarming`) so no new
    # candidate day enters the window between the two calls.
    store = _FakeStore()
    day = dt.date(2026, 1, 10)
    opened_ns = _ns_at("2026-01-11T12:00:00")
    resolved_ns = _ns_at("2026-01-11T14:00:00")
    _reconcile(store, opened_ns, retention_days=1)
    records = (
        _Record(
            station=STATION,
            climate_day=day,
            ts_init=1,
            is_final=True,
            revision_seq=revision_seq,
        ),
    )
    _reconcile(store, resolved_ns, records, retention_days=1)
    return store, day, resolved_ns


def test_a_revision_seq_increase_on_a_resolved_day_emits_a_revision_event() -> None:
    store, day, resolved_ns = _resolved_gap_store(revision_seq=1)
    later_ns = resolved_ns + NS_PER_SECOND
    records = (
        _Record(station=STATION, climate_day=day, ts_init=2, is_final=True, revision_seq=2),
    )

    result = _reconcile(store, later_ns, records, retention_days=2)

    assert len(result.revisions) == 1
    event = result.revisions[0]
    assert isinstance(event, RevisionEvent)
    assert event.climate_day == day
    assert event.previous_revision_seq == 1
    assert event.new_revision_seq == 2
    entry = get_entry(store, VENUE, CITY, day)
    assert entry is not None
    assert entry.observed_revision_seq == 2


def test_correction_flag_flipping_true_emits_a_revision_event_independently() -> None:
    store, day, resolved_ns = _resolved_gap_store(revision_seq=1)
    later_ns = resolved_ns + NS_PER_SECOND
    records = (
        _Record(
            station=STATION,
            climate_day=day,
            ts_init=2,
            is_final=True,
            revision_seq=1,
            correction_flag=True,
        ),
    )

    result = _reconcile(store, later_ns, records, retention_days=2)

    assert len(result.revisions) == 1
    assert result.revisions[0].correction_flag is True
    entry = get_entry(store, VENUE, CITY, day)
    assert entry is not None
    assert entry.correction_flag is True


def test_is_superseded_flipping_true_emits_a_revision_event_independently() -> None:
    store, day, resolved_ns = _resolved_gap_store(revision_seq=1)
    later_ns = resolved_ns + NS_PER_SECOND
    records = (
        _Record(
            station=STATION,
            climate_day=day,
            ts_init=2,
            is_final=True,
            revision_seq=1,
            is_superseded=True,
        ),
    )

    result = _reconcile(store, later_ns, records, retention_days=2)

    assert len(result.revisions) == 1
    assert result.revisions[0].is_superseded is True
    entry = get_entry(store, VENUE, CITY, day)
    assert entry is not None
    assert entry.is_superseded is True


def test_no_change_on_a_resolved_day_emits_no_revision_event_and_no_write() -> None:
    store, day, resolved_ns = _resolved_gap_store(revision_seq=1)
    before = store.data[_entry_key(VENUE, CITY, day)]
    later_ns = resolved_ns + NS_PER_SECOND
    records = (
        _Record(station=STATION, climate_day=day, ts_init=1, is_final=True, revision_seq=1),
    )

    result = _reconcile(store, later_ns, records, retention_days=2)

    assert result.revisions == ()
    assert store.data[_entry_key(VENUE, CITY, day)] == before


# ---------------------------------------------------------------------------
# 6b. Revision tracking for days that were NEVER a gap
#
# The settlement-correctness case: NWS reissues a corrected climate-day final
# hours after a day that was collected cleanly and on time. Revision detection
# must cover EVERY observed final, not only days that were once missing --
# otherwise `RevisionEvent` is structurally unreachable for the overwhelming
# majority of days and a settled position on a wrong temperature is silent.
# ---------------------------------------------------------------------------


def _clean_day_store(*, revision_seq: int = 1) -> tuple[_FakeStore, dt.date, int]:
    """A site whose climate day was observed cleanly and on time: never a gap.

    Both instants used by callers fall on the SAME ET calendar day (see the
    comment on `test_a_filled_gap_becomes_resolved_and_stops_alarming`) so no
    new candidate day enters the window between reconciles.
    """
    store = _FakeStore()
    day = dt.date(2026, 1, 10)
    first_ns = _ns_at("2026-01-11T12:00:00")
    records = (
        _Record(
            station=STATION,
            climate_day=day,
            ts_init=1,
            is_final=True,
            revision_seq=revision_seq,
        ),
    )
    result = _reconcile(store, first_ns, records, retention_days=1)

    # A day that was never missing is never reported as opened OR as resolved:
    # recording it must not manufacture a phantom gap-then-fill transition.
    assert result.opened == ()
    assert result.resolved == ()
    assert result.revisions == ()
    return store, day, first_ns


def test_a_cleanly_observed_day_is_recorded_so_later_revisions_stay_detectable() -> None:
    store, day, first_ns = _clean_day_store(revision_seq=1)

    entry = get_entry(store, VENUE, CITY, day)
    assert entry is not None
    assert entry.state is GapState.RESOLVED
    assert entry.first_detected_ns == first_ns
    assert entry.last_reconciled_ns == first_ns
    assert entry.resolved_at_ns == first_ns
    assert entry.observed_revision_seq == 1
    assert entry.observed_is_final is True
    assert entry.correction_flag is False
    assert entry.is_superseded is False
    assert entry.acknowledged_by is None
    # Reachable through the durable manifest, not just by point lookup --
    # an entry the manifest does not list can never be enumerated again.
    assert [e.climate_day for e in site_entries(store, VENUE, CITY)] == [day]


def test_a_revision_seq_increase_on_a_never_missing_day_emits_a_revision_event() -> None:
    # The headline settlement-correctness case: collected cleanly and on
    # time, then reissued with an incremented revision.
    store, day, first_ns = _clean_day_store(revision_seq=1)
    later_ns = first_ns + 2 * NS_PER_SECOND
    records = (
        _Record(station=STATION, climate_day=day, ts_init=2, is_final=True, revision_seq=2),
    )

    result = _reconcile(store, later_ns, records, retention_days=1)

    assert len(result.revisions) == 1
    event = result.revisions[0]
    assert isinstance(event, RevisionEvent)
    assert event.venue == VENUE
    assert event.city == CITY
    assert event.climate_day == day
    assert event.previous_revision_seq == 1
    assert event.new_revision_seq == 2
    entry = get_entry(store, VENUE, CITY, day)
    assert entry is not None
    assert entry.observed_revision_seq == 2
    assert entry.state is GapState.RESOLVED


def test_correction_flag_flipping_true_on_a_never_missing_day_emits_a_revision_event() -> None:
    # A station reporting error corrected hours later, with NO revision-seq
    # bump: the correction flag alone must still alert.
    store, day, first_ns = _clean_day_store(revision_seq=1)
    later_ns = first_ns + 2 * NS_PER_SECOND
    records = (
        _Record(
            station=STATION,
            climate_day=day,
            ts_init=2,
            is_final=True,
            revision_seq=1,
            correction_flag=True,
        ),
    )

    result = _reconcile(store, later_ns, records, retention_days=1)

    assert len(result.revisions) == 1
    assert result.revisions[0].correction_flag is True
    assert result.revisions[0].previous_revision_seq == 1
    assert result.revisions[0].new_revision_seq == 1
    entry = get_entry(store, VENUE, CITY, day)
    assert entry is not None
    assert entry.correction_flag is True


def test_is_superseded_flipping_true_on_a_never_missing_day_emits_a_revision_event() -> None:
    store, day, first_ns = _clean_day_store(revision_seq=1)
    later_ns = first_ns + 2 * NS_PER_SECOND
    records = (
        _Record(
            station=STATION,
            climate_day=day,
            ts_init=2,
            is_final=True,
            revision_seq=1,
            is_superseded=True,
        ),
    )

    result = _reconcile(store, later_ns, records, retention_days=1)

    assert len(result.revisions) == 1
    assert result.revisions[0].is_superseded is True
    entry = get_entry(store, VENUE, CITY, day)
    assert entry is not None
    assert entry.is_superseded is True


def test_a_clean_day_re_observed_unchanged_emits_no_revision_event_and_no_write() -> None:
    # NEGATIVE CONTROL: recording every observed day must not turn every
    # reconcile into a revision alert.
    store, day, first_ns = _clean_day_store(revision_seq=1)
    before = dict(store.data)
    later_ns = first_ns + 2 * NS_PER_SECOND
    records = (
        _Record(station=STATION, climate_day=day, ts_init=1, is_final=True, revision_seq=1),
    )

    result = _reconcile(store, later_ns, records, retention_days=1)

    assert result.revisions == ()
    assert result.opened == ()
    assert result.resolved == ()
    assert store.data == before


def test_recording_a_clean_day_never_re_opens_or_re_resolves_it() -> None:
    # A second reconcile at the SAME instant with the SAME records is
    # byte-identical: the clean-day entry is written exactly once.
    store, day, first_ns = _clean_day_store(revision_seq=3)
    snapshot = dict(store.data)
    records = (
        _Record(station=STATION, climate_day=day, ts_init=1, is_final=True, revision_seq=3),
    )

    result = _reconcile(store, first_ns, records, retention_days=1)

    assert result == ReconcileResult(
        venue=VENUE,
        city=CITY,
        opened=(),
        resolved=(),
        revisions=(),
        high_water_mark=day,
    )
    assert store.data == snapshot


# ---------------------------------------------------------------------------
# 6c. Preliminary -> final maturation refreshes the baseline WITHOUT alerting
#
# A preliminary maturing into a final at the SAME `revision_seq` is ordinary
# progression, not a revision to a settled value -- alerting on it would
# desensitise the operator to the corrected-final alert that actually matters.
# But leaving the entry frozen at the preliminary's values makes the durable
# ledger misdescribe what was observed, so the entry is refreshed in place and
# nothing is emitted.
# ---------------------------------------------------------------------------


def _preliminary_day_store(*, revision_seq: int = 1) -> tuple[_FakeStore, dt.date, int]:
    """A site whose climate day was first seen as a PRELIMINARY, on time.

    All instants used by callers fall on the SAME ET calendar day (see the
    comment on `test_a_filled_gap_becomes_resolved_and_stops_alarming`) so no
    new candidate day enters the window between reconciles.
    """
    store = _FakeStore()
    day = dt.date(2026, 1, 10)
    first_ns = _ns_at("2026-01-11T12:00:00")
    records = (
        _Record(
            station=STATION,
            climate_day=day,
            ts_init=1,
            is_final=False,
            revision_seq=revision_seq,
        ),
    )
    result = _reconcile(store, first_ns, records, retention_days=1)

    assert result.opened == ()
    assert result.resolved == ()
    assert result.revisions == ()
    entry = get_entry(store, VENUE, CITY, day)
    assert entry is not None
    assert entry.state is GapState.RESOLVED
    assert entry.observed_is_final is False
    return store, day, first_ns


def test_a_preliminary_maturing_into_a_final_refreshes_the_entry_without_alerting() -> None:
    # HEADLINE: same `revision_seq`, `is_final` False -> True. The durable
    # entry must stop misdescribing the observation, and NO RevisionEvent may
    # fire -- this is normal progression, not a revision to a settled value.
    store, day, first_ns = _preliminary_day_store(revision_seq=1)
    later_ns = first_ns + 2 * NS_PER_SECOND
    records = (
        _Record(station=STATION, climate_day=day, ts_init=2, is_final=True, revision_seq=1),
    )

    result = _reconcile(store, later_ns, records, retention_days=1)

    assert result.revisions == ()
    assert result.opened == ()
    assert result.resolved == ()
    entry = get_entry(store, VENUE, CITY, day)
    assert entry is not None
    assert entry.observed_is_final is True
    assert entry.observed_revision_seq == 1
    assert entry.correction_flag is False
    assert entry.is_superseded is False
    assert entry.state is GapState.RESOLVED
    assert entry.last_reconciled_ns == later_ns
    # Refreshing an already-RESOLVED day is not a re-resolution: the instant
    # the day was first accounted for must not be rewritten.
    assert entry.resolved_at_ns == first_ns


def test_a_matured_final_re_observed_unchanged_performs_no_further_write() -> None:
    # NEGATIVE CONTROL: the refresh must be a one-shot, not a per-reconcile
    # rewrite -- otherwise every poll forever writes the same bytes back.
    store, day, first_ns = _preliminary_day_store(revision_seq=1)
    matured_ns = first_ns + 2 * NS_PER_SECOND
    records = (
        _Record(station=STATION, climate_day=day, ts_init=2, is_final=True, revision_seq=1),
    )
    _reconcile(store, matured_ns, records, retention_days=1)
    after_refresh = dict(store.data)

    third_ns = matured_ns + 2 * NS_PER_SECOND
    result = _reconcile(store, third_ns, records, retention_days=1)

    assert result.revisions == ()
    assert result.opened == ()
    assert result.resolved == ()
    assert store.data == after_refresh


def test_a_correction_after_maturation_alerts_once_against_the_refreshed_baseline() -> None:
    # REGRESSION GUARD: preliminary -> final (silent refresh) -> corrected
    # final. Exactly ONE RevisionEvent across the whole sequence, and it is
    # compared against the refreshed baseline (already `is_final`), not the
    # stale preliminary one.
    store, day, first_ns = _preliminary_day_store(revision_seq=1)
    matured_ns = first_ns + 2 * NS_PER_SECOND
    matured = _reconcile(
        store,
        matured_ns,
        (_Record(station=STATION, climate_day=day, ts_init=2, is_final=True, revision_seq=1),),
        retention_days=1,
    )
    assert matured.revisions == ()
    baseline = get_entry(store, VENUE, CITY, day)
    assert baseline is not None
    assert baseline.observed_is_final is True  # the refreshed baseline

    corrected_ns = matured_ns + 2 * NS_PER_SECOND
    corrected = _reconcile(
        store,
        corrected_ns,
        (
            _Record(
                station=STATION,
                climate_day=day,
                ts_init=3,
                is_final=True,
                revision_seq=2,
                correction_flag=True,
            ),
        ),
        retention_days=1,
    )

    assert len(corrected.revisions) == 1
    event = corrected.revisions[0]
    assert event.climate_day == day
    assert event.previous_revision_seq == 1
    assert event.new_revision_seq == 2
    assert event.correction_flag is True
    entry = get_entry(store, VENUE, CITY, day)
    assert entry is not None
    assert entry.observed_revision_seq == 2
    assert entry.observed_is_final is True
    assert entry.correction_flag is True


def test_a_weaker_re_observation_never_downgrades_a_final_baseline() -> None:
    # A stale preliminary re-delivered after the final must not roll the
    # ledger's baseline backwards to `is_final=False`, which would re-arm the
    # refresh path and rewrite the entry on every poll.
    store, day, first_ns = _preliminary_day_store(revision_seq=1)
    matured_ns = first_ns + 2 * NS_PER_SECOND
    _reconcile(
        store,
        matured_ns,
        (_Record(station=STATION, climate_day=day, ts_init=2, is_final=True, revision_seq=1),),
        retention_days=1,
    )
    after_refresh = dict(store.data)

    stale_ns = matured_ns + 2 * NS_PER_SECOND
    result = _reconcile(
        store,
        stale_ns,
        (_Record(station=STATION, climate_day=day, ts_init=9, is_final=False, revision_seq=1),),
        retention_days=1,
    )

    assert result.revisions == ()
    assert store.data == after_refresh
    entry = get_entry(store, VENUE, CITY, day)
    assert entry is not None
    assert entry.observed_is_final is True


def test_a_gap_resolved_by_a_preliminary_then_matured_refreshes_without_alerting() -> None:
    # The same maturation, reached through the OPEN -> RESOLVED path rather
    # than through the never-missing path: one mechanism must serve both.
    store = _FakeStore()
    day = dt.date(2026, 1, 10)
    opened_ns = _ns_at("2026-01-11T12:00:00")
    resolved_ns = _ns_at("2026-01-11T14:00:00")
    matured_ns = _ns_at("2026-01-11T16:00:00")

    assert _reconcile(store, opened_ns, retention_days=1).opened == (day,)
    resolved = _reconcile(
        store,
        resolved_ns,
        (_Record(station=STATION, climate_day=day, ts_init=1, is_final=False, revision_seq=1),),
        retention_days=1,
    )
    assert resolved.resolved == (day,)

    result = _reconcile(
        store,
        matured_ns,
        (_Record(station=STATION, climate_day=day, ts_init=2, is_final=True, revision_seq=1),),
        retention_days=1,
    )

    assert result.revisions == ()
    assert result.resolved == ()
    entry = get_entry(store, VENUE, CITY, day)
    assert entry is not None
    assert entry.observed_is_final is True
    assert entry.resolved_at_ns == resolved_ns


# ---------------------------------------------------------------------------
# 7. ACKNOWLEDGED_LOST
# ---------------------------------------------------------------------------


def test_acknowledge_transitions_an_open_gap_to_acknowledged_lost() -> None:
    store = _FakeStore()
    now_ns = _ns_at("2026-01-11T12:00:00")
    day = dt.date(2026, 1, 10)
    _reconcile(store, now_ns, retention_days=1)
    ack_ns = now_ns + NS_PER_SECOND

    entry = acknowledge(
        store=store,
        venue=VENUE,
        city=CITY,
        climate_day=day,
        now_ns=ack_ns,
        acknowledged_by="jon@gopoint.com",
        reason="confirmed permanently lost after manual review",
    )

    assert entry.state is GapState.ACKNOWLEDGED_LOST
    assert entry.acknowledged_by == "jon@gopoint.com"
    assert entry.acknowledged_at_ns == ack_ns
    assert entry.acknowledged_reason == "confirmed permanently lost after manual review"


def test_acknowledge_refuses_a_day_with_no_entry() -> None:
    store = _FakeStore()
    with pytest.raises(ValueError, match="no gap entry exists"):
        acknowledge(
            store=store,
            venue=VENUE,
            city=CITY,
            climate_day=dt.date(2026, 1, 10),
            now_ns=1,
            acknowledged_by="jon@gopoint.com",
            reason="n/a",
        )


def test_acknowledge_refuses_a_resolved_day() -> None:
    store, day, resolved_ns = _resolved_gap_store()
    with pytest.raises(ValueError, match="not OPEN"):
        acknowledge(
            store=store,
            venue=VENUE,
            city=CITY,
            climate_day=day,
            now_ns=resolved_ns + NS_PER_SECOND,
            acknowledged_by="jon@gopoint.com",
            reason="n/a",
        )


def test_acknowledged_lost_mutes_re_alarm_but_stays_visible_and_never_reverts() -> None:
    store = _FakeStore()
    now_ns = _ns_at("2026-01-11T12:00:00")
    day = dt.date(2026, 1, 10)
    _reconcile(store, now_ns, retention_days=1)
    ack_ns = now_ns + NS_PER_SECOND
    acknowledge(
        store=store,
        venue=VENUE,
        city=CITY,
        climate_day=day,
        now_ns=ack_ns,
        acknowledged_by="jon@gopoint.com",
        reason="confirmed lost",
    )

    later_ns = ack_ns + NS_PER_SECOND
    result = _reconcile(store, later_ns, retention_days=1)

    # Never re-opened, never counted as a fresh "opened" or "resolved" event.
    assert result.opened == ()
    assert result.resolved == ()
    entry = get_entry(store, VENUE, CITY, day)
    assert entry is not None
    assert entry.state is GapState.ACKNOWLEDGED_LOST
    assert entry.last_reconciled_ns == later_ns
    # Still visible in the manifest-driven site listing.
    assert day in {e.climate_day for e in site_entries(store, VENUE, CITY)}


def test_acknowledged_lost_never_reverts_even_if_later_observed() -> None:
    store = _FakeStore()
    now_ns = _ns_at("2026-01-11T12:00:00")
    day = dt.date(2026, 1, 10)
    _reconcile(store, now_ns, retention_days=1)
    ack_ns = now_ns + NS_PER_SECOND
    acknowledge(
        store=store,
        venue=VENUE,
        city=CITY,
        climate_day=day,
        now_ns=ack_ns,
        acknowledged_by="jon@gopoint.com",
        reason="confirmed lost",
    )

    later_ns = ack_ns + NS_PER_SECOND
    records = (_Record(station=STATION, climate_day=day, ts_init=1, is_final=True, revision_seq=1),)
    result = _reconcile(store, later_ns, records, retention_days=1)

    assert result.resolved == ()
    entry = get_entry(store, VENUE, CITY, day)
    assert entry is not None
    assert entry.state is GapState.ACKNOWLEDGED_LOST


# ---------------------------------------------------------------------------
# 8. Tampering
# ---------------------------------------------------------------------------


def test_entry_missing_while_listed_in_manifest_is_tampering_not_no_gap() -> None:
    store = _FakeStore()
    day = dt.date(2026, 1, 10)
    gap_id = _manifest_id(VENUE, CITY, day)
    store.data[_MANIFEST_KEY] = json.dumps([gap_id]).encode("utf-8")
    # Deliberately never write the entry key itself.

    with pytest.raises(TamperedGapLedgerError, match="entry is missing"):
        site_entries(store, VENUE, CITY)

    with pytest.raises(TamperedGapLedgerError):
        _reconcile(store, _ns_at("2026-01-11T12:00:00"), retention_days=1)


def test_get_entry_does_not_consult_the_manifest_and_returns_none_for_a_bare_miss() -> None:
    # A direct point lookup for a day that was never written at all (and is
    # not claimed by the manifest either) is an ordinary "no gap", not
    # tampering -- distinguishing this from the case above is the point.
    store = _FakeStore()
    assert get_entry(store, VENUE, CITY, dt.date(2026, 1, 10)) is None


def test_corrupt_manifest_bytes_are_tampering() -> None:
    store = _FakeStore()
    store.data[_MANIFEST_KEY] = b"not json"

    with pytest.raises(TamperedGapLedgerError):
        site_entries(store, VENUE, CITY)


def test_manifest_that_is_not_a_json_array_of_strings_is_tampering() -> None:
    store = _FakeStore()
    store.data[_MANIFEST_KEY] = json.dumps([1, 2, 3]).encode("utf-8")

    with pytest.raises(TamperedGapLedgerError):
        site_entries(store, VENUE, CITY)


def test_corrupt_entry_bytes_are_tampering_via_get_entry() -> None:
    store = _FakeStore()
    day = dt.date(2026, 1, 10)
    store.data[_entry_key(VENUE, CITY, day)] = b"not json"

    with pytest.raises(TamperedGapLedgerError):
        get_entry(store, VENUE, CITY, day)


def test_corrupt_high_water_mark_bytes_are_tampering() -> None:
    store = _FakeStore()
    store.data[_hw_key(VENUE, CITY)] = b"not json"

    with pytest.raises(TamperedGapLedgerError):
        _reconcile(store, _ns_at("2026-01-11T12:00:00"), retention_days=1)


def test_high_water_mark_missing_the_expected_through_field_is_tampering() -> None:
    store = _FakeStore()
    store.data[_hw_key(VENUE, CITY)] = json.dumps({"wrong_field": "2026-01-10"}).encode("utf-8")

    with pytest.raises(TamperedGapLedgerError):
        _reconcile(store, _ns_at("2026-01-11T12:00:00"), retention_days=1)


def _valid_entry_payload(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "venue": VENUE,
        "city": CITY,
        "climate_day": "2026-01-10",
        "state": "open",
        "first_detected_ns": 1,
        "last_reconciled_ns": 1,
        "resolved_at_ns": None,
        "observed_revision_seq": 0,
        "observed_is_final": False,
        "correction_flag": False,
        "is_superseded": False,
        "acknowledged_by": None,
        "acknowledged_at_ns": None,
        "acknowledged_reason": None,
    }
    base.update(overrides)
    return base


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"venue": 1}, id="venue-not-str"),
        pytest.param({"state": "not-a-real-state"}, id="state-invalid-enum"),
        pytest.param({"first_detected_ns": "1"}, id="int-field-not-int"),
        pytest.param({"first_detected_ns": True}, id="int-field-is-bool"),
        pytest.param({"resolved_at_ns": "1"}, id="optional-int-field-not-int"),
        pytest.param({"resolved_at_ns": True}, id="optional-int-field-is-bool"),
        pytest.param({"observed_is_final": "yes"}, id="bool-field-not-bool"),
        pytest.param({"acknowledged_by": 5}, id="optional-str-field-not-str"),
    ],
)
def test_malformed_entry_fields_are_tampering(overrides: dict[str, Any]) -> None:
    store = _FakeStore()
    day = dt.date(2026, 1, 10)
    payload = _valid_entry_payload(**overrides)
    store.data[_entry_key(VENUE, CITY, day)] = json.dumps(payload).encode("utf-8")

    with pytest.raises(TamperedGapLedgerError):
        get_entry(store, VENUE, CITY, day)


def test_entry_payload_that_is_not_a_json_object_is_tampering() -> None:
    store = _FakeStore()
    day = dt.date(2026, 1, 10)
    store.data[_entry_key(VENUE, CITY, day)] = json.dumps([1, 2, 3]).encode("utf-8")

    with pytest.raises(TamperedGapLedgerError):
        get_entry(store, VENUE, CITY, day)


def test_manifest_write_is_idempotent_and_does_not_rewrite_when_already_listed() -> None:
    store = _FakeStore()
    now_ns = _ns_at("2026-01-11T12:00:00")
    _reconcile(store, now_ns, retention_days=1)
    manifest_snapshot = store.data[_MANIFEST_KEY]

    # A second reconcile at the same instant must not touch the manifest
    # bytes at all (already covered by the broader idempotence test, pinned
    # again here at the manifest key specifically).
    _reconcile(store, now_ns, retention_days=1)

    assert store.data[_MANIFEST_KEY] == manifest_snapshot


# ---------------------------------------------------------------------------
# Key schema smoke tests
# ---------------------------------------------------------------------------


def test_key_schema_matches_the_documented_prefixes() -> None:
    day = dt.date(2026, 1, 10)
    assert _MANIFEST_KEY == f"{GAP_KEY_PREFIX}__manifest__"
    assert _entry_key(VENUE, CITY, day) == f"{GAP_KEY_PREFIX}{VENUE}:{CITY}:2026-01-10"
    assert _hw_key(VENUE, CITY) == f"{GAP_KEY_PREFIX}hw:{VENUE}:{CITY}"
    assert _manifest_id(VENUE, CITY, day) == f"{VENUE}|{CITY}|2026-01-10"


def test_review_extension_end_ns_is_11_00_et_on_the_day_after() -> None:
    day = dt.date(2026, 1, 10)
    expected = _ns_at("2026-01-11T11:00:00")
    assert (
        review_extension_end_ns(
            day,
            settlement_delay_time_local=SETTLEMENT_DELAY_TIME_LOCAL,
            settlement_delay_timezone=SETTLEMENT_DELAY_TIMEZONE,
        )
        == expected
    )


def test_gap_entry_is_frozen() -> None:
    entry = GapEntry(
        venue=VENUE,
        city=CITY,
        climate_day=dt.date(2026, 1, 10),
        state=GapState.OPEN,
        first_detected_ns=1,
        last_reconciled_ns=1,
        resolved_at_ns=None,
        observed_revision_seq=0,
        observed_is_final=False,
        correction_flag=False,
        is_superseded=False,
        acknowledged_by=None,
        acknowledged_at_ns=None,
        acknowledged_reason=None,
    )
    with pytest.raises(FrozenInstanceError):
        entry.state = GapState.RESOLVED  # type: ignore[misc]
