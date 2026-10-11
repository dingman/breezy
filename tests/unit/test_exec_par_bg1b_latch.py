"""EXEC-PAR BG-1b: single-writer counter-row methods on ``SubmitIntentLatch``."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path

import pytest

from breezy.runtime.exec_par_records import (
    EXEC_PAR_PREFIX,
    AmbiguousRow,
    DenialRow,
    FillRow,
    GappyMark,
    OpenCostFlag,
    OrderAnchor,
    encode_record,
)
from breezy.runtime.submit_intent import (
    SubmitIntentCorrupt,
    SubmitIntentLatch,
    SubmitIntentLockNotHeld,
    open_submit_intent_latch,
)

P = EXEC_PAR_PREFIX
DAY = "2026-10-11"


class _Store:
    def __init__(self) -> None:
        self.data: dict[str, bytes] = {}
        self.fail_set = False

    def get(self, key: str) -> bytes | None:
        return self.data.get(key)

    def keys_with_prefix(self, prefix: str) -> list[str]:
        return sorted(k for k in self.data if k.startswith(prefix))

    def set(self, key: str, value: bytes) -> None:
        if self.fail_set:
            raise OSError("simulated set failure")
        self.data[key] = value


@contextmanager
def _open(store: _Store, tmp_path: Path) -> Iterator[SubmitIntentLatch]:
    with open_submit_intent_latch(store, tmp_path / "s.db", clock_ns=lambda: 777) as latch:
        yield latch


def _anchor(coid: str = "O-1", day: str = DAY, ask: str = "0.40") -> OrderAnchor:
    return OrderAnchor(coid, "slug-a", day, 100, ask, "10", "4.00", 100)


def _fill(trade: str = "TR-1", coid: str = "O-1", day: str = DAY) -> FillRow:
    return FillRow(trade, coid, day, 100, "10", "0.41", "0.40", "0.01", "0.17", "0.168", "0.0695")


def test_anchor_is_exclusive_idempotent_and_keyed_by_client_order_id(tmp_path: Path) -> None:
    store = _Store()
    with _open(store, tmp_path) as latch:
        assert latch.write_order_anchor(_anchor()) is True
        assert latch.write_order_anchor(_anchor()) is False  # identical replay: no-op
        assert latch.read_order_anchor("O-1") == _anchor()
        assert latch.read_order_anchor("O-9") is None
        with pytest.raises(ValueError):
            latch.write_order_anchor(_anchor(ask="0.41"))  # conflicting row never overwrites
        assert latch.read_order_anchor("O-1") == _anchor()
    assert store.data[f"{P}order/O-1"] == encode_record(_anchor())


def test_readers_filter_by_day_and_are_scan_based(tmp_path: Path) -> None:
    store = _Store()
    with _open(store, tmp_path) as latch:
        for coid, day in (("O-1", DAY), ("O-2", DAY), ("O-3", "2026-10-12")):
            latch.write_order_anchor(_anchor(coid, day))
        assert [a.client_order_id for a in latch.read_order_anchors(DAY)] == ["O-1", "O-2"]
        assert latch.read_order_anchors("2026-10-13") == ()
        with pytest.raises(ValueError):
            latch.read_order_anchors("")
    assert not any(k.endswith("latest") for k in store.data)  # no pointers


def test_denial_ambiguous_fill_rows_round_trip_by_day(tmp_path: Path) -> None:
    with _open(_Store(), tmp_path) as latch:
        d = DenialRow("O-2", "k-full", DAY, 5)
        a = AmbiguousRow("a1", "unknown", DAY, 5, "slot", 6)
        f = _fill()
        assert latch.write_denial(d) and latch.write_ambiguous(a) and latch.write_fill(f)
        assert not latch.write_denial(d)
        assert latch.read_denials(DAY) == (d,)
        assert latch.read_ambiguous(DAY) == (a,)
        assert latch.read_fills(DAY) == (f,)
        assert latch.read_fills("2026-10-12") == ()


def test_key_components_with_separators_are_refused(tmp_path: Path) -> None:
    store = _Store()
    with _open(store, tmp_path) as latch:
        with pytest.raises(ValueError):
            latch.write_order_anchor(_anchor("O/1"))
        with pytest.raises(ValueError):
            latch.write_fill(_fill(trade="a/b"))
    assert store.data == {} or all(not k.startswith(P + "order/") for k in store.data)


def test_open_cost_flag_never_downgrades_within_a_station_day(tmp_path: Path) -> None:
    with _open(_Store(), tmp_path) as latch:
        up = OpenCostFlag("NYC@" + DAY, DAY, True, 1)
        down = OpenCostFlag("NYC@" + DAY, DAY, False, 2)
        assert latch.write_open_cost_flag(up) == up
        assert latch.write_open_cost_flag(down).exceeded is True
        other = OpenCostFlag("BOS@" + DAY, DAY, False, 3)
        latch.write_open_cost_flag(other)
        assert {f.station_day for f in latch.read_open_cost_flags(DAY)} == {
            "NYC@" + DAY,
            "BOS@" + DAY,
        }


def test_window_accumulates_per_five_second_window_and_exposes_the_peak(tmp_path: Path) -> None:
    with _open(_Store(), tmp_path) as latch:
        w1 = latch.add_window_order(DAY, 5_000, Decimal("4.00"))
        assert (w1.orders, w1.notional) == (1, "4.00")
        w1 = latch.add_window_order(DAY, 5_000, Decimal("1.50"))
        assert (w1.orders, w1.notional) == (2, "5.50")
        latch.add_window_order(DAY, 10_000, Decimal("9.00"))
        latch.add_window_order("2026-10-12", 5_000, Decimal(99))
        windows = latch.read_window_peaks(DAY)
        assert [(w.window_start_ns, w.orders) for w in windows] == [(5_000, 2), (10_000, 1)]
        with pytest.raises(ValueError):
            latch.add_window_order(DAY, 5_000, Decimal("NaN"))


def test_gappy_mark_is_first_wins_and_listed(tmp_path: Path) -> None:
    with _open(_Store(), tmp_path) as latch:
        m = GappyMark(DAY, "heartbeat_lapse", 1, None)
        assert latch.write_gappy_mark(m) is True
        assert latch.write_gappy_mark(GappyMark(DAY, "other", 2, None)) is False
        assert latch.read_gappy_marks() == (m,)


def test_garbled_row_raises_corrupt_never_a_default(tmp_path: Path) -> None:
    store = _Store()
    with _open(store, tmp_path) as latch:
        latch.write_order_anchor(_anchor())
        store.data[f"{P}order/O-1"] = b"garbage"
        with pytest.raises(SubmitIntentCorrupt):
            latch.read_order_anchor("O-1")
        with pytest.raises(SubmitIntentCorrupt):
            latch.read_order_anchors(DAY)


def test_row_whose_key_disagrees_with_its_own_id_is_corrupt(tmp_path: Path) -> None:
    store = _Store()
    with _open(store, tmp_path) as latch:
        store.data[f"{P}order/O-2"] = encode_record(_anchor("O-1"))
        with pytest.raises(SubmitIntentCorrupt):
            latch.read_order_anchors(DAY)


def test_store_failure_propagates_and_leaves_nothing(tmp_path: Path) -> None:
    store = _Store()
    with _open(store, tmp_path) as latch:
        store.fail_set = True
        with pytest.raises(OSError):
            latch.write_fill(_fill())
        store.fail_set = False
        assert latch.read_fills(DAY) == ()


def test_not_held_latch_raises_before_touching_the_store(tmp_path: Path) -> None:
    store = _Store()
    with _open(store, tmp_path) as latch:
        pass
    for op in (
        lambda: latch.write_order_anchor(_anchor()),
        lambda: latch.read_fills(DAY),
        lambda: latch.add_window_order(DAY, 5, Decimal(1)),
        lambda: latch.read_gappy_marks(),
    ):
        with pytest.raises(SubmitIntentLockNotHeld):
            op()
    assert store.data == {} or all(not k.startswith(P) for k in store.data)


def test_concurrent_window_adds_from_threads_do_not_lose_counts(tmp_path: Path) -> None:
    with _open(_Store(), tmp_path) as latch:
        threads = [
            threading.Thread(target=lambda: [latch.add_window_order(DAY, 5, Decimal(1))] * 1)
            for _ in range(8)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert latch.read_window_peaks(DAY)[0].orders == 8
