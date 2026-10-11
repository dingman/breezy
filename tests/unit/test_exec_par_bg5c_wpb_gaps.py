"""EXEC-PAR BG-5c WP-B (R7): append-only lapse record, boot/in-run gap spans and ``mark_gaps``."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from breezy.runtime.exec_par_gap_marking import (
    GapMarkWriteError,
    GapReadError,
    LapseWriteError,
    mark_gaps,
    record_final_lapse_before_stop,
    record_lapse_if_any,
    record_unclean_shutdowns,
    unclean_shutdown_lapses,
)
from breezy.runtime.exec_par_governed_days import governed_days_for
from breezy.runtime.exec_par_reconcile import HEARTBEAT_LAPSE_NS, GapKind
from breezy.runtime.exec_par_records import (
    EXEC_PAR_PREFIX,
    EpochRow,
    ExecParRecordError,
    HeartbeatLapse,
    decode_record,
    encode_record,
)
from breezy.runtime.submit_intent import SubmitIntentCorrupt, SubmitIntentLatch
from breezy.runtime.submit_intent import open_submit_intent_latch as open_latch

S = 1_000_000_000
H = 3_600 * S
DAY = 24 * H
D0 = 20_000 * DAY  # 2024-10-04T00:00Z
LAPSE = GapKind.HEARTBEAT_LAPSE.value
UNCLEAN = GapKind.UNCLEAN_SHUTDOWN.value


def _utc_open(ns: int) -> frozenset[str]:
    import datetime as dt

    return frozenset({dt.datetime.fromtimestamp(ns // S, dt.UTC).date().isoformat()})


class _Ledger:
    """In-memory ``GapLedgerPort``."""

    def __init__(self) -> None:
        self.rows: dict[tuple[int, int], HeartbeatLapse] = {}
        self.fail_write = False
        self.fail_read = False
        self.fail_stamp = False

    def by_start(self, start_ns: int) -> HeartbeatLapse:
        (row,) = [r for r in self.rows.values() if r.start_ns == start_ns]
        return row

    def write_heartbeat_lapse(self, record: HeartbeatLapse) -> bool:
        if self.fail_write:
            raise OSError("write failed")
        key = (record.start_ns, record.end_ns)
        if key in self.rows:
            return False
        self.rows[key] = record
        return True

    def read_heartbeat_lapses(self) -> tuple[HeartbeatLapse, ...]:
        if self.fail_read:
            raise OSError("read failed")
        return tuple(sorted(self.rows.values(), key=lambda r: (r.start_ns, r.end_ns)))

    def set_lapse_marked(self, start_ns: int, end_ns: int, marked_ts: int) -> bool:
        if self.fail_stamp:
            raise OSError("stamp failed")
        row = self.rows[(start_ns, end_ns)]
        if row.marked_ts is not None:
            return False
        self.rows[(start_ns, end_ns)] = HeartbeatLapse(start_ns, end_ns, row.kind, marked_ts)
        return True


class _Counters:
    """In-memory ``GapMarkPort`` (first mark of a day wins, like the latch)."""

    def __init__(self) -> None:
        self.gappy: dict[str, str] = {}
        self.attempts: list[str] = []
        self.fail_days: set[str] = set()
        self.fail_read = False

    def read_gappy_days(self) -> frozenset[str]:
        if self.fail_read:
            raise OSError("read failed")
        return frozenset(self.gappy)

    def mark_gappy_day(self, day: str, kind: str) -> None:
        self.attempts.append(day)
        if day in self.fail_days:
            raise OSError("mark failed")
        self.gappy.setdefault(day, kind)


def _epoch(boot: int, stop: int | None = None, k: int = 2) -> EpochRow:
    return EpochRow(commit_sha="abc", effective_k=k, force_reason=None, boot_ts=boot, stop_ts=stop)


# -- record and latch ----------------------------------------------------------


def test_lapse_record_round_trips_and_rejects_garbage() -> None:
    row = HeartbeatLapse(start_ns=D0, end_ns=D0 + 90 * S, kind=LAPSE)
    assert decode_record(HeartbeatLapse, encode_record(row)) == row
    with pytest.raises(ExecParRecordError):
        encode_record(HeartbeatLapse(start_ns=D0, end_ns=D0 + 1, kind=""))
    with pytest.raises(ExecParRecordError):
        decode_record(HeartbeatLapse, b'{"v":1,"start_ns":1}')


class _Store:
    def __init__(self) -> None:
        self.data: dict[str, bytes] = {}

    def get(self, key: str) -> bytes | None:
        return self.data.get(key)

    def keys_with_prefix(self, prefix: str) -> list[str]:
        return sorted(k for k in self.data if k.startswith(prefix))

    def set(self, key: str, value: bytes) -> None:
        self.data[key] = value


@contextmanager
def _latch(store: _Store, tmp_path: Path) -> Iterator[SubmitIntentLatch]:
    with open_latch(store, tmp_path / "s.db", clock_ns=lambda: 777) as latch:
        yield latch


def test_heartbeat_history_is_a_single_overwritten_row_and_lapses_are_append_only(
    tmp_path: Path,
) -> None:
    """R7.3 finding: ``write_breaker_heartbeat`` overwrites ONE key, so history needs lapse rows."""
    store = _Store()
    with _latch(store, tmp_path) as latch:
        latch.write_breaker_heartbeat(hb_ns=D0, resolver_pass_ns=D0)
        latch.write_breaker_heartbeat(hb_ns=D0 + 500 * S, resolver_pass_ns=D0)
        breaker_keys = [k for k in store.data if "/breaker" in k]
        record = latch.read_breaker_record()
        assert len(breaker_keys) == 1
        assert record is not None and record.hb_ns == D0 + 500 * S  # the first beat is gone

        assert latch.write_heartbeat_lapse(HeartbeatLapse(D0, D0 + 500 * S, LAPSE)) is True
        assert latch.write_heartbeat_lapse(HeartbeatLapse(D0 + 900 * S, D0 + 990 * S, LAPSE))
        assert [r.start_ns for r in latch.read_heartbeat_lapses()] == [D0, D0 + 900 * S]


def test_latch_lapse_write_is_idempotent_and_overlapping_spans_coexist(tmp_path: Path) -> None:
    store = _Store()
    with _latch(store, tmp_path) as latch:
        row = HeartbeatLapse(D0, D0 + 100 * S, LAPSE)
        assert latch.write_heartbeat_lapse(row) is True
        assert latch.write_heartbeat_lapse(row) is False
        # same start, different end (HIGH 1): both spans are kept, nothing raises
        assert latch.write_heartbeat_lapse(HeartbeatLapse(D0, D0 + 200 * S, UNCLEAN)) is True
        assert [(r.start_ns, r.end_ns) for r in latch.read_heartbeat_lapses()] == [
            (D0, D0 + 100 * S),
            (D0, D0 + 200 * S),
        ]
        with pytest.raises(ValueError):
            latch.write_heartbeat_lapse(HeartbeatLapse(D0, D0, LAPSE))


def test_crash_between_the_inrun_lapse_and_the_boot_unclean_span_never_refuses_boot(
    tmp_path: Path,
) -> None:
    """First-beat case: the in-run lapse starts at boot_ts, and so does the unclean span."""
    store = _Store()
    with _latch(store, tmp_path) as latch:
        boot = D0
        in_run = record_lapse_if_any(latch, last_hb_ns=boot, now_ns=boot + 5 * HEARTBEAT_LAPSE_NS)
        assert in_run is not None and in_run.start_ns == boot
        # node crashes; next boot finds the epoch without stop_ts and no usable heartbeat
        epochs = (_epoch(boot), _epoch(boot + 10 * H))
        rows = record_unclean_shutdowns(latch, epochs, None)  # raised LapseWriteError before
        assert rows[0].start_ns == boot
        # a repeat of both writes is an idempotent no-op
        record_lapse_if_any(latch, last_hb_ns=boot, now_ns=boot + 5 * HEARTBEAT_LAPSE_NS)
        record_unclean_shutdowns(latch, epochs, None)
        assert len(latch.read_heartbeat_lapses()) == 2


def test_latch_marked_stamp_is_set_once_per_span_and_a_rewrite_stays_a_no_op(
    tmp_path: Path,
) -> None:
    store = _Store()
    with _latch(store, tmp_path) as latch:
        row = HeartbeatLapse(D0, D0 + 100 * S, LAPSE)
        other = HeartbeatLapse(D0, D0 + 200 * S, UNCLEAN)
        latch.write_heartbeat_lapse(row)
        latch.write_heartbeat_lapse(other)
        assert latch.set_lapse_marked(D0, D0 + 100 * S, 5) is True
        assert latch.set_lapse_marked(D0, D0 + 100 * S, 9) is False
        assert latch.write_heartbeat_lapse(row) is False  # same span, already stamped
        stamped = {r.end_ns: r.marked_ts for r in latch.read_heartbeat_lapses()}
        assert stamped == {D0 + 100 * S: 5, D0 + 200 * S: None}
        with pytest.raises(ValueError):
            latch.set_lapse_marked(D0 + 1, D0 + 2, 5)  # absent row


def test_latch_lapse_reader_raises_on_a_garbled_or_mis_keyed_row(tmp_path: Path) -> None:
    store = _Store()
    with _latch(store, tmp_path) as latch:
        key = f"{EXEC_PAR_PREFIX}lapse/{D0}/{D0 + 5}"
        store.data[key] = b"not json"
        with pytest.raises(SubmitIntentCorrupt):
            latch.read_heartbeat_lapses()
        store.data[key] = encode_record(HeartbeatLapse(D0 + 1, D0 + 2, LAPSE))
        with pytest.raises(SubmitIntentCorrupt):
            latch.read_heartbeat_lapses()


# -- in-run lapse recording ----------------------------------------------------


def test_no_lapse_at_exactly_the_bound_or_without_a_baseline() -> None:
    ledger = _Ledger()
    assert record_lapse_if_any(ledger, last_hb_ns=D0, now_ns=D0 + HEARTBEAT_LAPSE_NS) is None
    assert record_lapse_if_any(ledger, last_hb_ns=None, now_ns=D0) is None
    assert ledger.rows == {}


def test_a_lapse_over_the_bound_is_recorded_once() -> None:
    ledger = _Ledger()
    now = D0 + HEARTBEAT_LAPSE_NS + 1
    first = record_lapse_if_any(ledger, last_hb_ns=D0, now_ns=now)
    again = record_lapse_if_any(ledger, last_hb_ns=D0, now_ns=now)
    assert first == HeartbeatLapse(D0, now, LAPSE)
    assert again == first
    assert len(ledger.rows) == 1


def test_a_lapse_write_failure_is_a_typed_error_not_a_silent_skip() -> None:
    ledger = _Ledger()
    ledger.fail_write = True
    with pytest.raises(LapseWriteError):
        record_lapse_if_any(ledger, last_hb_ns=D0, now_ns=D0 + 2 * HEARTBEAT_LAPSE_NS)


def test_a_clock_going_backwards_records_nothing() -> None:
    ledger = _Ledger()
    assert record_lapse_if_any(ledger, last_hb_ns=D0 + 5 * H, now_ns=D0) is None
    assert ledger.rows == {}


# -- boot: unclean shutdown ------------------------------------------------------


def test_unclean_prior_epoch_spans_from_its_last_heartbeat_to_the_next_boot() -> None:
    epochs = (_epoch(D0), _epoch(D0 + 10 * H))
    (row,) = unclean_shutdown_lapses(epochs, last_heartbeat_ns=D0 + 2 * H)
    assert row == HeartbeatLapse(D0 + 2 * H, D0 + 10 * H, UNCLEAN)


def test_unclean_epoch_without_a_known_heartbeat_spans_from_its_boot() -> None:
    epochs = (_epoch(D0), _epoch(D0 + 10 * H))
    (row,) = unclean_shutdown_lapses(epochs, last_heartbeat_ns=None)
    assert row.start_ns == D0
    # a heartbeat outside the epoch (a stale or foreign value) is not trusted either
    (row2,) = unclean_shutdown_lapses(epochs, last_heartbeat_ns=D0 + 20 * H)
    assert row2.start_ns == D0


def test_clean_stop_current_epoch_and_k1_epochs_are_not_unclean() -> None:
    clean = (_epoch(D0, stop=D0 + H), _epoch(D0 + 10 * H))
    assert unclean_shutdown_lapses(clean, last_heartbeat_ns=D0 + 30 * 60 * S) == ()
    k1 = (_epoch(D0, k=1), _epoch(D0 + 10 * H))
    assert unclean_shutdown_lapses(k1, last_heartbeat_ns=D0 + H) == ()
    only_current = (_epoch(D0),)
    assert unclean_shutdown_lapses(only_current, last_heartbeat_ns=D0 + H) == ()


def test_only_the_epoch_just_before_the_boot_uses_the_heartbeat() -> None:
    epochs = (_epoch(D0), _epoch(D0 + 10 * H), _epoch(D0 + 20 * H))
    rows = unclean_shutdown_lapses(epochs, last_heartbeat_ns=D0 + 12 * H)
    assert [(r.start_ns, r.end_ns) for r in rows] == [
        (D0, D0 + 10 * H),
        (D0 + 12 * H, D0 + 20 * H),
    ]


def test_record_unclean_shutdowns_writes_and_is_idempotent_and_typed_on_failure() -> None:
    ledger = _Ledger()
    epochs = (_epoch(D0), _epoch(D0 + 10 * H))
    assert len(record_unclean_shutdowns(ledger, epochs, last_heartbeat_ns=D0 + H)) == 1
    record_unclean_shutdowns(ledger, epochs, last_heartbeat_ns=D0 + H)
    assert len(ledger.rows) == 1
    ledger.fail_write = True
    with pytest.raises(LapseWriteError):
        record_unclean_shutdowns(ledger, (_epoch(D0 + 50 * H), _epoch(D0 + 60 * H)), None)


# -- mark_gaps -------------------------------------------------------------------


def test_mark_gaps_marks_every_open_day_of_a_multi_day_span_with_its_kind() -> None:
    ledger, counters = _Ledger(), _Counters()
    ledger.write_heartbeat_lapse(HeartbeatLapse(D0 + 12 * H, D0 + 2 * DAY + 12 * H, UNCLEAN))
    result = mark_gaps(ledger=ledger, counters=counters, open_days_at=_utc_open, wall_ns=lambda: 42)
    assert counters.gappy == {
        "2024-10-04": UNCLEAN,
        "2024-10-05": UNCLEAN,
        "2024-10-06": UNCLEAN,
    }
    assert result.marked_days == ("2024-10-04", "2024-10-05", "2024-10-06")
    assert ledger.by_start(D0 + 12 * H).marked_ts == 42


def test_mark_gaps_marks_every_governed_stations_open_day() -> None:
    offsets = {"EAST": -5.0, "WEST": -8.0}
    days = governed_days_for(["EAST", "WEST"], offsets.__getitem__)
    ledger, counters = _Ledger(), _Counters()
    # 06:00Z..07:00Z: EAST (UTC-5) is already on the 05th, WEST (UTC-8) still on the 04th
    start = D0 + DAY + 6 * H
    ledger.write_heartbeat_lapse(HeartbeatLapse(start, start + H, LAPSE))
    mark_gaps(ledger=ledger, counters=counters, open_days_at=days.open_days_at, wall_ns=lambda: 1)
    assert set(counters.gappy) == {"2024-10-04", "2024-10-05"}


def test_mark_gaps_is_idempotent_even_after_reconcile_cleared_a_mark() -> None:
    ledger, counters = _Ledger(), _Counters()
    ledger.write_heartbeat_lapse(HeartbeatLapse(D0 + H, D0 + 2 * H, LAPSE))
    mark_gaps(ledger=ledger, counters=counters, open_days_at=_utc_open, wall_ns=lambda: 1)
    counters.gappy.clear()  # BG-1d rebuilt the day and deleted its mark
    counters.attempts.clear()
    again = mark_gaps(ledger=ledger, counters=counters, open_days_at=_utc_open, wall_ns=lambda: 2)
    assert counters.attempts == [] and counters.gappy == {}
    assert again.marked_days == ()


def test_mark_gaps_skips_a_day_that_is_already_marked() -> None:
    ledger, counters = _Ledger(), _Counters()
    counters.gappy["2024-10-04"] = "counter_missing"
    ledger.write_heartbeat_lapse(HeartbeatLapse(D0 + H, D0 + 2 * H, LAPSE))
    result = mark_gaps(ledger=ledger, counters=counters, open_days_at=_utc_open, wall_ns=lambda: 1)
    assert counters.attempts == []
    assert counters.gappy["2024-10-04"] == "counter_missing"
    assert result.marked_days == ()
    assert ledger.by_start(D0 + H).marked_ts == 1  # the span is satisfied, so it is stamped


def test_mark_gaps_with_nothing_pending_writes_nothing() -> None:
    ledger, counters = _Ledger(), _Counters()
    result = mark_gaps(ledger=ledger, counters=counters, open_days_at=_utc_open, wall_ns=lambda: 1)
    assert result.marked_days == () and counters.attempts == []


def test_mark_gaps_write_failure_raises_typed_names_the_pending_days_and_retries() -> None:
    ledger, counters = _Ledger(), _Counters()
    ledger.write_heartbeat_lapse(HeartbeatLapse(D0 + 12 * H, D0 + DAY + 12 * H, LAPSE))
    counters.fail_days = {"2024-10-05"}
    with pytest.raises(GapMarkWriteError) as info:
        mark_gaps(ledger=ledger, counters=counters, open_days_at=_utc_open, wall_ns=lambda: 1)
    assert info.value.pending_days == frozenset({"2024-10-05"})
    assert "2024-10-04" in counters.gappy  # the other day still landed
    assert ledger.by_start(D0 + 12 * H).marked_ts is None  # not stamped, so it retries
    counters.fail_days = set()
    result = mark_gaps(ledger=ledger, counters=counters, open_days_at=_utc_open, wall_ns=lambda: 2)
    assert result.marked_days == ("2024-10-05",)
    assert ledger.by_start(D0 + 12 * H).marked_ts == 2


def test_mark_gaps_stamp_failure_is_typed() -> None:
    ledger, counters = _Ledger(), _Counters()
    ledger.write_heartbeat_lapse(HeartbeatLapse(D0 + H, D0 + 2 * H, LAPSE))
    ledger.fail_stamp = True
    with pytest.raises(GapMarkWriteError):
        mark_gaps(ledger=ledger, counters=counters, open_days_at=_utc_open, wall_ns=lambda: 1)


def test_mark_gaps_read_failures_are_typed_never_an_empty_pass() -> None:
    ledger, counters = _Ledger(), _Counters()
    ledger.write_heartbeat_lapse(HeartbeatLapse(D0 + H, D0 + 2 * H, LAPSE))
    ledger.fail_read = True
    with pytest.raises(GapReadError):
        mark_gaps(ledger=ledger, counters=counters, open_days_at=_utc_open, wall_ns=lambda: 1)
    ledger.fail_read = False
    counters.fail_read = True
    with pytest.raises(GapReadError):
        mark_gaps(ledger=ledger, counters=counters, open_days_at=_utc_open, wall_ns=lambda: 1)


def test_mark_gaps_open_days_failure_is_a_write_error_for_that_span() -> None:
    ledger, counters = _Ledger(), _Counters()
    ledger.write_heartbeat_lapse(HeartbeatLapse(D0 + H, D0 + 2 * H, LAPSE))

    def boom(ns: int) -> frozenset[str]:
        raise ValueError("bad clock")

    with pytest.raises(GapMarkWriteError):
        mark_gaps(ledger=ledger, counters=counters, open_days_at=boom, wall_ns=lambda: 1)
    assert ledger.by_start(D0 + H).marked_ts is None


def test_mark_gaps_unions_overlapping_spans_that_share_a_start() -> None:
    ledger, counters = _Ledger(), _Counters()
    ledger.write_heartbeat_lapse(HeartbeatLapse(D0 + H, D0 + 2 * H, LAPSE))
    ledger.write_heartbeat_lapse(HeartbeatLapse(D0 + H, D0 + DAY + 2 * H, UNCLEAN))
    result = mark_gaps(ledger=ledger, counters=counters, open_days_at=_utc_open, wall_ns=lambda: 7)
    assert set(counters.gappy) == {"2024-10-04", "2024-10-05"}
    assert result.spans_stamped == 2
    assert all(r.marked_ts == 7 for r in ledger.rows.values())


def test_pending_days_are_failed_minus_marked_and_a_stamp_failure_names_its_days() -> None:
    ledger, counters = _Ledger(), _Counters()
    ledger.write_heartbeat_lapse(HeartbeatLapse(D0 + H, D0 + DAY + 2 * H, LAPSE))
    ledger.write_heartbeat_lapse(HeartbeatLapse(D0 + 2 * H, D0 + 3 * H, LAPSE))
    counters.fail_days = {"2024-10-05"}
    with pytest.raises(GapMarkWriteError) as info:
        mark_gaps(ledger=ledger, counters=counters, open_days_at=_utc_open, wall_ns=lambda: 1)
    assert info.value.pending_days == frozenset({"2024-10-05"})  # 10-04 landed via both spans

    ledger2, counters2 = _Ledger(), _Counters()
    ledger2.write_heartbeat_lapse(HeartbeatLapse(D0 + H, D0 + DAY + 2 * H, LAPSE))
    ledger2.fail_stamp = True
    with pytest.raises(GapMarkWriteError) as info2:
        mark_gaps(ledger=ledger2, counters=counters2, open_days_at=_utc_open, wall_ns=lambda: 1)
    assert info2.value.pending_days == frozenset({"2024-10-04", "2024-10-05"})


def test_pending_days_include_the_days_of_a_span_whose_day_computation_fails() -> None:
    ledger, counters = _Ledger(), _Counters()
    start = D0 + H
    ledger.write_heartbeat_lapse(HeartbeatLapse(start, start + 3 * H, LAPSE))

    def flaky(ns: int) -> frozenset[str]:
        if ns == start + H:  # one interior instant fails; the endpoints still resolve
            raise ValueError("bad instant")
        return _utc_open(ns)

    with pytest.raises(GapMarkWriteError) as info:
        mark_gaps(ledger=ledger, counters=counters, open_days_at=flaky, wall_ns=lambda: 1)
    assert info.value.pending_days == frozenset({"2024-10-04"})
    assert ledger.by_start(start).marked_ts is None


def test_record_final_lapse_before_stop_records_the_tail_and_is_typed_on_failure() -> None:
    ledger = _Ledger()
    stop = D0 + 5 * HEARTBEAT_LAPSE_NS
    row = record_final_lapse_before_stop(ledger, last_hb_ns=D0, stop_ts_ns=stop)
    assert row == HeartbeatLapse(D0, stop, LAPSE)
    assert record_final_lapse_before_stop(ledger, last_hb_ns=stop - S, stop_ts_ns=stop) is None
    ledger.fail_write = True
    with pytest.raises(LapseWriteError):
        record_final_lapse_before_stop(ledger, last_hb_ns=D0, stop_ts_ns=D0 + 9 * H)
