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
import hashlib
import json
from dataclasses import FrozenInstanceError, dataclass, replace
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


def _sha(label: str) -> str:
    """A deterministic 64-hex digest standing in for `NwsClimateDay.raw_sha256`.

    Derived from a label, never from a clock or the network, so the same
    product text always yields the same digest across runs and orderings --
    which is exactly the property the duplicate-re-persist tests assert on.
    """
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


#: The digest of the ORIGINAL product text in every fixture below. A second
#: record carrying this same digest is the same bytes re-persisted, never a
#: revision, no matter what catalog ordinal it was assigned.
SHA_ORIGINAL = _sha("original-cli-product")

#: Settlement-relevant readings of the original product.
TMAX_ORIGINAL = 41
TMIN_ORIGINAL = 30
TAVG_ORIGINAL = 36

#: A PRELIMINARY and the FINAL that supersedes it are different products, so
#: they ALWAYS carry different digests -- even when they report the very same
#: temperatures. That is precisely why the digest alone cannot decide whether
#: an observation is a revision: the readings have to be compared too.
SHA_PRELIMINARY = _sha("preliminary-cli-product")
SHA_FINAL = _sha("final-cli-product")
SHA_CORRECTED = _sha("corrected-cli-product")


@dataclass(frozen=True, slots=True)
class _Record:
    """A minimal `gaps.ObservedRecord`-shaped stand-in for `NwsClimateDay`.

    Carries the settlement-relevant readings (`tmax_f`/`tmin_f`/`tavg_f`) and
    the content digest (`raw_sha256`) because revision detection is a question
    about the OBSERVATION, not about `revision_seq` -- which is not an NWS
    field at all but an internal per-`(station, climate_day)` catalog ordinal
    assigned by `NwsIngestActor._persist_batch`.
    """

    station: str
    climate_day: dt.date
    ts_init: int
    is_final: bool
    revision_seq: int
    correction_flag: bool = False
    is_superseded: bool = False
    raw_sha256: str = SHA_ORIGINAL
    tmax_f: int | None = TMAX_ORIGINAL
    tmin_f: int | None = TMIN_ORIGINAL
    tavg_f: int | None = TAVG_ORIGINAL


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
# Record builders.
#
# `revision_seq` is an internal per-`(station, climate_day)` catalog ORDINAL,
# assigned in `NwsIngestActor._persist_batch` as
# `seq_by_day[day] = seq_by_day.get(day, 0) + 1` counted over every record
# already on disk for that day -- NOT an NWS-published field. Every builder
# below therefore takes the ordinal EXPLICITLY, and every multi-record fixture
# assigns it the way `_persist_batch` actually would: 1 for the first record
# ever persisted for a day, 2 for the second, and so on, whatever those
# records contain.
# ---------------------------------------------------------------------------


def _original_final(day: dt.date, *, seq: int = 1, ts_init: int = 1) -> _Record:
    """The first FINAL persisted for `day`: the settlement baseline."""
    return _Record(
        station=STATION, climate_day=day, ts_init=ts_init, is_final=True, revision_seq=seq
    )


def _prelim_record(
    day: dt.date,
    *,
    seq: int = 1,
    ts_init: int = 1,
    tmax_f: int | None = TMAX_ORIGINAL,
) -> _Record:
    """The ~preliminary issuance for `day`, always the FIRST record persisted."""
    return _Record(
        station=STATION,
        climate_day=day,
        ts_init=ts_init,
        is_final=False,
        revision_seq=seq,
        raw_sha256=SHA_PRELIMINARY,
        tmax_f=tmax_f,
    )


def _final_record(
    day: dt.date,
    *,
    seq: int = 2,
    ts_init: int = 2,
    tmax_f: int | None = TMAX_ORIGINAL,
    raw_sha256: str = SHA_FINAL,
    correction_flag: bool = False,
    is_superseded: bool = False,
) -> _Record:
    """The FINAL issuance for `day`. Defaults to ordinal 2 because in
    production a final is persisted AFTER the preliminary it supersedes, and
    the preliminary is still on disk when the ordinal is assigned.
    """
    return _Record(
        station=STATION,
        climate_day=day,
        ts_init=ts_init,
        is_final=True,
        revision_seq=seq,
        correction_flag=correction_flag,
        is_superseded=is_superseded,
        raw_sha256=raw_sha256,
        tmax_f=tmax_f,
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


def test_a_reissued_final_with_a_changed_temperature_on_a_resolved_day_alerts() -> None:
    # The accumulated shape production actually produces: the original final
    # is STILL on disk when the reissue lands, so `read_climate_days` returns
    # both, and the reissue's ordinal is 2 because of that.
    store, day, resolved_ns = _resolved_gap_store(revision_seq=1)
    later_ns = resolved_ns + NS_PER_SECOND
    records = (
        _original_final(day, seq=1),
        _final_record(day, seq=2, raw_sha256=SHA_CORRECTED, tmax_f=TMAX_ORIGINAL + 2),
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
    assert entry.observed_tmax_f == TMAX_ORIGINAL + 2


def test_correction_flag_flipping_true_emits_a_revision_event_independently() -> None:
    # INDEPENDENTLY: the reissue reports the very same temperatures as the
    # original, so only the correction flag can be carrying the signal.
    store, day, resolved_ns = _resolved_gap_store(revision_seq=1)
    later_ns = resolved_ns + NS_PER_SECOND
    records = (
        _original_final(day, seq=1),
        _final_record(day, seq=2, raw_sha256=SHA_CORRECTED, correction_flag=True),
    )

    result = _reconcile(store, later_ns, records, retention_days=2)

    assert len(result.revisions) == 1
    assert result.revisions[0].correction_flag is True
    entry = get_entry(store, VENUE, CITY, day)
    assert entry is not None
    assert entry.correction_flag is True


def test_is_superseded_flipping_true_emits_a_revision_event_independently() -> None:
    # INDEPENDENTLY, and at a BYTE-IDENTICAL digest: `is_superseded` is a
    # write-time annotation, not something derived from the product text, so
    # it is the one signal that must survive the identical-content shortcut.
    store, day, resolved_ns = _resolved_gap_store(revision_seq=1)
    later_ns = resolved_ns + NS_PER_SECOND
    records = (
        _original_final(day, seq=1),
        _final_record(day, seq=2, raw_sha256=SHA_ORIGINAL, is_superseded=True),
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
    records = (_original_final(day, seq=1),)

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
    # The CONTENT baseline a later reissue is compared against -- without it,
    # revision detection has nothing to compare but the catalog ordinal.
    assert entry.observed_raw_sha256 == SHA_ORIGINAL
    assert entry.observed_tmax_f == TMAX_ORIGINAL
    assert entry.observed_tmin_f == TMIN_ORIGINAL
    assert entry.observed_tavg_f == TAVG_ORIGINAL
    assert entry.acknowledged_by is None
    # Reachable through the durable manifest, not just by point lookup --
    # an entry the manifest does not list can never be enumerated again.
    assert [e.climate_day for e in site_entries(store, VENUE, CITY)] == [day]


def test_a_changed_temperature_on_a_never_missing_day_emits_a_revision_event() -> None:
    # The headline settlement-correctness case: collected cleanly and on
    # time, then reissued reporting a DIFFERENT high. Fed in the accumulated
    # shape `read_climate_days` really returns -- the original final is still
    # on disk, which is why the reissue's catalog ordinal is 2.
    store, day, first_ns = _clean_day_store(revision_seq=1)
    later_ns = first_ns + 2 * NS_PER_SECOND
    records = (
        _original_final(day, seq=1),
        _final_record(day, seq=2, raw_sha256=SHA_CORRECTED, tmax_f=TMAX_ORIGINAL + 3),
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
    # A station reporting error corrected hours later, reporting the SAME
    # temperatures: the correction flag alone must still alert.
    store, day, first_ns = _clean_day_store(revision_seq=1)
    later_ns = first_ns + 2 * NS_PER_SECOND
    records = (
        _original_final(day, seq=1),
        _final_record(day, seq=2, raw_sha256=SHA_CORRECTED, correction_flag=True),
    )

    result = _reconcile(store, later_ns, records, retention_days=1)

    assert len(result.revisions) == 1
    assert result.revisions[0].correction_flag is True
    assert result.revisions[0].previous_revision_seq == 1
    assert result.revisions[0].new_revision_seq == 2
    entry = get_entry(store, VENUE, CITY, day)
    assert entry is not None
    assert entry.correction_flag is True


def test_is_superseded_flipping_true_on_a_never_missing_day_emits_a_revision_event() -> None:
    store, day, first_ns = _clean_day_store(revision_seq=1)
    later_ns = first_ns + 2 * NS_PER_SECOND
    records = (
        _original_final(day, seq=1),
        _final_record(day, seq=2, raw_sha256=SHA_ORIGINAL, is_superseded=True),
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
# A preliminary maturing into a final that reports the SAME temperatures is
# ordinary progression, not a revision to a settled value -- alerting on it
# would desensitise the operator to the corrected-final alert that actually
# matters. It is NOT detectable from `revision_seq`: the final is persisted
# after the preliminary, so it is ALWAYS assigned the next catalog ordinal.
# Leaving the entry frozen at the preliminary's values would make the durable
# ledger misdescribe what was observed, so the entry is refreshed in place and
# nothing is emitted.
#
# Every fixture here feeds the ACCUMULATED record set `read_climate_days`
# really returns: the catalog is append-only, so the preliminary is still
# present alongside the final on every later poll, forever.
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
    records = (_prelim_record(day, seq=revision_seq),)
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
    # HEADLINE: `is_final` False -> True at the NEXT catalog ordinal (2, the
    # only ordinal production can assign here) reporting the SAME high. The
    # durable entry must stop misdescribing the observation, and NO
    # RevisionEvent may fire -- this is normal progression, not a revision to
    # a settled value.
    store, day, first_ns = _preliminary_day_store(revision_seq=1)
    later_ns = first_ns + 2 * NS_PER_SECOND
    records = (_prelim_record(day, seq=1), _final_record(day, seq=2))

    result = _reconcile(store, later_ns, records, retention_days=1)

    assert result.revisions == ()
    assert result.opened == ()
    assert result.resolved == ()
    entry = get_entry(store, VENUE, CITY, day)
    assert entry is not None
    assert entry.observed_is_final is True
    assert entry.observed_revision_seq == 2
    assert entry.observed_raw_sha256 == SHA_FINAL
    assert entry.observed_tmax_f == TMAX_ORIGINAL
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
    records = (_prelim_record(day, seq=1), _final_record(day, seq=2))
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
        (_prelim_record(day, seq=1), _final_record(day, seq=2)),
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
            _prelim_record(day, seq=1),
            _final_record(day, seq=2),
            _final_record(
                day,
                seq=3,
                ts_init=3,
                raw_sha256=SHA_CORRECTED,
                correction_flag=True,
            ),
        ),
        retention_days=1,
    )

    assert len(corrected.revisions) == 1
    event = corrected.revisions[0]
    assert event.climate_day == day
    assert event.previous_revision_seq == 2
    assert event.new_revision_seq == 3
    assert event.correction_flag is True
    entry = get_entry(store, VENUE, CITY, day)
    assert entry is not None
    assert entry.observed_revision_seq == 3
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
        (_prelim_record(day, seq=1), _final_record(day, seq=2)),
        retention_days=1,
    )
    after_refresh = dict(store.data)

    stale_ns = matured_ns + 2 * NS_PER_SECOND
    result = _reconcile(
        store,
        stale_ns,
        (_prelim_record(day, seq=3, ts_init=9, tmax_f=TMAX_ORIGINAL + 9),),
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
        (_prelim_record(day, seq=1),),
        retention_days=1,
    )
    assert resolved.resolved == (day,)

    result = _reconcile(
        store,
        matured_ns,
        (_prelim_record(day, seq=1), _final_record(day, seq=2)),
        retention_days=1,
    )

    assert result.revisions == ()
    assert result.resolved == ()
    entry = get_entry(store, VENUE, CITY, day)
    assert entry is not None
    assert entry.observed_is_final is True
    assert entry.resolved_at_ns == resolved_ns


# ---------------------------------------------------------------------------
# 6d. Revision detection is a question about the OBSERVATION, never about the
#     catalog ordinal.
#
# `revision_seq` is NOT an NWS-published field. `NwsIngestActor._persist_batch`
# assigns it as `seq_by_day[day] = seq_by_day.get(day, 0) + 1`, counted over
# every `NwsClimateDay` already on disk for that `(station, climate_day)` --
# so it increments for a preliminary maturing into a final, and increments
# again for a crash-window re-persist of BYTE-IDENTICAL bytes. Treating an
# increment as a revision fires CRITICAL POST_SETTLEMENT_REVISION on ordinary
# days, which destroys the operator's ability to notice the one case that
# actually costs money: a settled final superseded by a different value.
# ---------------------------------------------------------------------------


def test_a_byte_identical_re_persist_at_a_higher_catalog_ordinal_is_not_a_revision() -> None:
    # HEADLINE. The crash window `NWS_COLLECTION_RUNTIME_PLAN_ADDENDUM.md`
    # documents: the catalog persist is confirmed, the process dies before the
    # durable seen-mark, so the same product is re-fetched and re-persisted.
    # Same bytes, same digest, same readings -- next ordinal. Nothing was
    # revised, so nothing may be reported.
    store, day, first_ns = _clean_day_store(revision_seq=1)
    later_ns = first_ns + 2 * NS_PER_SECOND
    records = (
        _original_final(day, seq=1, ts_init=1),
        # `_persist_batch` also nudges `retrieved_at_ns` past the catalog's
        # current max on a collision, which is why `ts_init` differs too.
        _original_final(day, seq=2, ts_init=2),
    )

    result = _reconcile(store, later_ns, records, retention_days=1)

    assert result.revisions == ()
    entry = get_entry(store, VENUE, CITY, day)
    assert entry is not None
    assert entry.observed_raw_sha256 == SHA_ORIGINAL
    assert entry.observed_tmax_f == TMAX_ORIGINAL
    assert entry.state is GapState.RESOLVED


def test_a_restart_loop_re_persisting_identical_bytes_never_produces_a_page_storm() -> None:
    # A supervisor restart loop re-persists the same bytes over and over, each
    # at the next ordinal. Under ordinal-based detection every cycle raised a
    # CRITICAL alert with a DISTINCT key, so dedupe could never suppress it.
    store, day, first_ns = _clean_day_store(revision_seq=1)
    accumulated = [_original_final(day, seq=1, ts_init=1)]
    now_ns = first_ns

    for ordinal in range(2, 8):
        accumulated.append(_original_final(day, seq=ordinal, ts_init=ordinal))
        now_ns += 2 * NS_PER_SECOND
        result = _reconcile(store, now_ns, tuple(accumulated), retention_days=1)
        assert result.revisions == (), f"ordinal {ordinal} raised a phantom revision"


@pytest.mark.parametrize(
    ("final_tmax_f", "expected_revisions"),
    [
        pytest.param(TMAX_ORIGINAL, 0, id="temperature-unchanged-is-maturation"),
        pytest.param(TMAX_ORIGINAL + 1, 1, id="temperature-changed-is-settlement-relevant"),
    ],
)
def test_maturation_alerts_only_when_the_settlement_temperature_changes(
    final_tmax_f: int,
    expected_revisions: int,
) -> None:
    # HEADLINE, as a discriminating PAIR: the two runs are identical in every
    # respect a catalog ordinal can see (preliminary at ordinal 1, final at
    # ordinal 2, both digests different because they are different products)
    # and differ ONLY in the value that settles money. Anything keyed on the
    # ordinal cannot tell them apart; the alert must.
    store, day, first_ns = _preliminary_day_store(revision_seq=1)
    later_ns = first_ns + 2 * NS_PER_SECOND
    records = (
        _prelim_record(day, seq=1),
        _final_record(day, seq=2, tmax_f=final_tmax_f),
    )

    result = _reconcile(store, later_ns, records, retention_days=1)

    assert len(result.revisions) == expected_revisions
    entry = get_entry(store, VENUE, CITY, day)
    assert entry is not None
    # Either way the durable baseline stops misdescribing the observation.
    assert entry.observed_is_final is True
    assert entry.observed_tmax_f == final_tmax_f
    assert entry.observed_raw_sha256 == SHA_FINAL


@pytest.mark.parametrize(
    ("changed_field", "changed_value"),
    [
        pytest.param("tmax_f", TMAX_ORIGINAL + 4, id="high-changed"),
        pytest.param("tmin_f", TMIN_ORIGINAL - 4, id="low-changed"),
        pytest.param("tavg_f", TAVG_ORIGINAL + 1, id="published-average-changed"),
        pytest.param("tmax_f", None, id="high-became-a-sentinel"),
        pytest.param("tmin_f", None, id="low-became-a-sentinel"),
        pytest.param("tavg_f", None, id="published-average-became-a-sentinel"),
    ],
)
def test_every_settlement_relevant_reading_change_alerts(
    changed_field: str,
    changed_value: int | None,
) -> None:
    # The venue settles on the observed high, low and published average
    # (`domain/nws_climate_day.py`, `tavg_f`), so a change to ANY of the three
    # is settlement-relevant -- including one that becomes a sentinel, which
    # turns a settleable number into no number at all.
    store, day, first_ns = _clean_day_store(revision_seq=1)
    later_ns = first_ns + 2 * NS_PER_SECOND
    reissue = replace(
        _original_final(day, seq=2, ts_init=2),
        raw_sha256=SHA_CORRECTED,
        **{changed_field: changed_value},
    )
    records = (_original_final(day, seq=1, ts_init=1), reissue)

    result = _reconcile(store, later_ns, records, retention_days=1)

    assert len(result.revisions) == 1
    assert result.revisions[0].climate_day == day


def test_a_steady_state_re_reconcile_neither_alerts_nor_writes() -> None:
    # NEGATIVE CONTROL. Production re-reads the SAME append-only record set on
    # every single poll, forever. Once the baseline matches it, further polls
    # must be completely inert: no event, and not one byte written.
    store, day, first_ns = _preliminary_day_store(revision_seq=1)
    records = (_prelim_record(day, seq=1), _final_record(day, seq=2))
    settled_ns = first_ns + 2 * NS_PER_SECOND
    _reconcile(store, settled_ns, records, retention_days=1)
    settled = dict(store.data)

    for tick in range(1, 4):
        result = _reconcile(store, settled_ns + tick * NS_PER_SECOND, records, retention_days=1)
        assert result.revisions == ()
        assert result.opened == ()
        assert result.resolved == ()
        assert store.data == settled, f"poll {tick} rewrote the ledger with no change"


# ---------------------------------------------------------------------------
# 6e. Backward-compatible decode of entries written before the content
#     baseline existed.
#
# The store cannot delete or scan, so an operator upgrading in place has
# entries on disk in the OLD format. They must decode, must NOT alert merely
# for being old, and must upgrade themselves silently on the next reconcile.
# ---------------------------------------------------------------------------


def _legacy_entry_payload(**overrides: Any) -> dict[str, Any]:
    """An entry EXACTLY as the pre-content-baseline codec wrote it.

    Spelled out literally rather than derived from `_valid_entry_payload`, so
    a future field addition cannot silently redefine what "the old format"
    means and quietly stop testing the upgrade path.
    """
    base: dict[str, Any] = {
        "venue": VENUE,
        "city": CITY,
        "climate_day": "2026-01-10",
        "state": "resolved",
        "first_detected_ns": 1,
        "last_reconciled_ns": 1,
        "resolved_at_ns": 1,
        "observed_revision_seq": 1,
        "observed_is_final": True,
        "correction_flag": False,
        "is_superseded": False,
        "acknowledged_by": None,
        "acknowledged_at_ns": None,
        "acknowledged_reason": None,
    }
    base.update(overrides)
    return base


def _legacy_store(day: dt.date) -> _FakeStore:
    store = _FakeStore()
    store.data[_MANIFEST_KEY] = json.dumps([_manifest_id(VENUE, CITY, day)]).encode("utf-8")
    store.data[_entry_key(VENUE, CITY, day)] = json.dumps(
        _legacy_entry_payload(climate_day=day.isoformat())
    ).encode("utf-8")
    store.data[_hw_key(VENUE, CITY)] = json.dumps({"expected_through": day.isoformat()}).encode(
        "utf-8"
    )
    return store


def test_an_entry_written_in_the_old_format_still_decodes() -> None:
    day = dt.date(2026, 1, 10)
    store = _legacy_store(day)

    entry = get_entry(store, VENUE, CITY, day)

    assert entry is not None
    assert entry.state is GapState.RESOLVED
    assert entry.observed_revision_seq == 1
    # The absent content baseline decodes as UNKNOWN -- the empty digest --
    # not as a fabricated one that could be compared against and "differ".
    assert entry.observed_raw_sha256 == ""
    assert entry.observed_tmax_f is None
    assert entry.observed_tmin_f is None
    assert entry.observed_tavg_f is None


def test_an_old_format_entry_upgrades_itself_silently_instead_of_alerting() -> None:
    # An operator restarting on the new code must not be paged once per
    # already-collected day. The baseline is UNKNOWN, not "different".
    day = dt.date(2026, 1, 10)
    store = _legacy_store(day)
    now_ns = _ns_at("2026-01-11T12:00:00")

    result = _reconcile(store, now_ns, (_original_final(day, seq=1),), retention_days=1)

    assert result.revisions == ()
    entry = get_entry(store, VENUE, CITY, day)
    assert entry is not None
    assert entry.observed_raw_sha256 == SHA_ORIGINAL
    assert entry.observed_tmax_f == TMAX_ORIGINAL


def test_an_old_format_entry_still_alerts_on_a_correction_before_it_is_upgraded() -> None:
    # The unknown baseline suppresses the CONTENT comparison only. A
    # correction flag is self-describing evidence and needs no baseline.
    day = dt.date(2026, 1, 10)
    store = _legacy_store(day)
    now_ns = _ns_at("2026-01-11T12:00:00")
    records = (
        _original_final(day, seq=1),
        _final_record(day, seq=2, raw_sha256=SHA_CORRECTED, correction_flag=True),
    )

    result = _reconcile(store, now_ns, records, retention_days=1)

    assert len(result.revisions) == 1
    assert result.revisions[0].correction_flag is True


def test_an_upgraded_entry_then_behaves_like_any_other_content_baseline() -> None:
    day = dt.date(2026, 1, 10)
    store = _legacy_store(day)
    now_ns = _ns_at("2026-01-11T12:00:00")
    _reconcile(store, now_ns, (_original_final(day, seq=1),), retention_days=1)
    upgraded = dict(store.data)

    # An identical re-persist at the next ordinal is now provably not a
    # revision, and is inert.
    inert = _reconcile(
        store,
        now_ns + NS_PER_SECOND,
        (_original_final(day, seq=1), _original_final(day, seq=2, ts_init=2)),
        retention_days=1,
    )
    assert inert.revisions == ()

    # ...and a genuinely different high still alerts.
    changed = _reconcile(
        store,
        now_ns + 2 * NS_PER_SECOND,
        (
            _original_final(day, seq=1),
            _final_record(
                day, seq=3, ts_init=3, raw_sha256=SHA_CORRECTED, tmax_f=TMAX_ORIGINAL + 5
            ),
        ),
        retention_days=1,
    )
    assert len(changed.revisions) == 1
    assert store.data != upgraded


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
        "observed_raw_sha256": "",
        "observed_tmax_f": None,
        "observed_tmin_f": None,
        "observed_tavg_f": None,
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
        # A field that decodes with a DEFAULT when absent must still be
        # validated when PRESENT -- tolerating the old format must never
        # become tolerating garbage.
        pytest.param({"observed_raw_sha256": 5}, id="defaulted-str-field-not-str"),
        pytest.param({"observed_tmax_f": "41"}, id="defaulted-optional-int-not-int"),
        pytest.param({"observed_tmin_f": True}, id="defaulted-optional-int-is-bool"),
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
        observed_raw_sha256="",
        observed_tmax_f=None,
        observed_tmin_f=None,
        observed_tavg_f=None,
        correction_flag=False,
        is_superseded=False,
        acknowledged_by=None,
        acknowledged_at_ns=None,
        acknowledged_reason=None,
    )
    with pytest.raises(FrozenInstanceError):
        entry.state = GapState.RESOLVED  # type: ignore[misc]
