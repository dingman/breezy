"""EXEC-PAR BG-1c: SettledPnlDay codec, latch writer/readers, K=1 pre-boot fill ledger."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from breezy.runtime.breaker_watcher import ExecParStorePort
from breezy.runtime.exec_par_records import (
    EXEC_PAR_PREFIX,
    EpochRow,
    ExecParRecordError,
    SettledPnlDay,
    decode_record,
    encode_record,
)
from breezy.runtime.exec_par_settled_pnl import (
    FILL_PREFIX,
    FillLedgerCorrupt,
    SettledPnlRegression,
    persist_settled_pnl,
    pre_boot_fill_ledger,
)
from breezy.runtime.submit_intent import (
    SubmitIntentCorrupt,
    SubmitIntentLockNotHeld,
    open_submit_intent_latch,
)

ROW = SettledPnlDay(
    day="2026-10-12", pnl="-1.25", settled_entries=2, ambiguous_entries=1, unsettled_entries=0
)


class _Store:
    def __init__(self) -> None:
        self.data: dict[str, bytes] = {}
        self.sets = 0

    def get(self, key: str) -> bytes | None:
        return self.data.get(key)

    def set(self, key: str, value: bytes) -> None:
        self.sets += 1
        self.data[key] = value

    def keys_with_prefix(self, prefix: str) -> list[str]:
        return sorted(k for k in self.data if k.startswith(prefix))


@dataclass(frozen=True)
class DurableFillRecord:
    """Structural stand-in for the exec client's record (tests never import exec/)."""

    venue_order_id: str
    instrument_id: str
    ts_event: int

    def to_bytes(self) -> bytes:
        return json.dumps(self.__dict__).encode()

    @classmethod
    def from_bytes(cls, raw: bytes) -> DurableFillRecord:
        return cls(**json.loads(raw.decode()))


def _fill(oid: str, inst: str, ts: int) -> DurableFillRecord:
    return DurableFillRecord(venue_order_id=oid, instrument_id=inst, ts_event=ts)


def _seed(store: _Store, *fills: DurableFillRecord) -> None:
    for f in fills:
        store.data[f"{FILL_PREFIX}{f.venue_order_id}"] = f.to_bytes()


def _all(f: DurableFillRecord) -> bool:
    return True


# -- codec ------------------------------------------------------------------


def test_fill_prefix_matches_the_exec_client_constant() -> None:
    root = Path(__file__).resolve().parents[2]
    src = (root / "src/breezy/adapters/polymarket_us/exec/client.py").read_text()
    namespace = re.search(r'^STATE_KEY_NAMESPACE: Final\[str\] = "([^"]+)"', src, re.MULTILINE)
    suffix = re.search(
        r'^FILL_KEY_PREFIX: Final\[str\] = f"\{STATE_KEY_NAMESPACE\}([^"]+)"', src, re.MULTILINE
    )
    assert namespace is not None and suffix is not None
    assert FILL_PREFIX == namespace.group(1) + suffix.group(1)


def test_record_round_trips_with_deterministic_bytes() -> None:
    raw = encode_record(ROW)
    assert decode_record(SettledPnlDay, raw) == ROW
    assert encode_record(decode_record(SettledPnlDay, raw)) == raw
    assert ROW.pnl_decimal == Decimal("-1.25")


@pytest.mark.parametrize(
    "bad",
    [
        {"pnl": "NaN"},
        {"pnl": "1e3"},
        {"pnl": " 1"},
        {"pnl": "-0"},
        {"pnl": ""},
        {"day": "2026-1-2"},
        {"day": "../x"},
        {"settled_entries": -1},
        {"ambiguous_entries": True},
    ],
)
def test_encode_refuses_invalid_fields(bad: dict[str, Any]) -> None:
    fields: dict[str, Any] = {
        "day": "2026-10-12",
        "pnl": "1",
        "settled_entries": 0,
        "ambiguous_entries": 0,
        "unsettled_entries": 0,
    }
    fields.update(bad)
    with pytest.raises(ExecParRecordError):
        encode_record(SettledPnlDay(**fields))


def test_decode_rejects_none_pnl_and_extra_keys() -> None:
    null_pnl = (
        b'{"v":1,"day":"2026-10-12","pnl":null,"settled_entries":0,'
        b'"ambiguous_entries":0,"unsettled_entries":0}'
    )
    with pytest.raises(ExecParRecordError):
        decode_record(SettledPnlDay, null_pnl)
    with pytest.raises(ExecParRecordError):
        decode_record(SettledPnlDay, encode_record(ROW)[:-1] + b',"x":1}')


# -- latch ------------------------------------------------------------------


def test_port_declares_the_settled_pnl_writer() -> None:
    assert hasattr(ExecParStorePort, "write_settled_pnl_day")


def test_latch_writes_reads_and_overwrites_a_day(tmp_path: Path) -> None:
    store = _Store()
    with open_submit_intent_latch(store, tmp_path / "s.db") as latch:
        assert latch.read_settled_pnl_day("2026-10-12") is None
        latch.write_settled_pnl_day(ROW)
        assert latch.read_settled_pnl_day("2026-10-12") == ROW
        newer = SettledPnlDay("2026-10-12", "-3", 3, 0, 0)
        latch.write_settled_pnl_day(newer)
        other = SettledPnlDay("2026-10-11", "0.5", 1, 0, 0)
        latch.write_settled_pnl_day(other)
        assert latch.read_settled_pnl_days() == (other, newer)
    assert f"{EXEC_PAR_PREFIX}settled_pnl/2026-10-12" in store.data


def test_latch_garbled_row_raises_corrupt_never_default(tmp_path: Path) -> None:
    store = _Store()
    store.data[f"{EXEC_PAR_PREFIX}settled_pnl/2026-10-12"] = b"garbage"
    with open_submit_intent_latch(store, tmp_path / "s.db") as latch:
        with pytest.raises(SubmitIntentCorrupt):
            latch.read_settled_pnl_day("2026-10-12")
        with pytest.raises(SubmitIntentCorrupt):
            latch.read_settled_pnl_days()


def test_row_stored_under_the_wrong_day_key_is_corrupt(tmp_path: Path) -> None:
    store = _Store()
    store.data[f"{EXEC_PAR_PREFIX}settled_pnl/2026-10-13"] = encode_record(ROW)
    with (
        open_submit_intent_latch(store, tmp_path / "s.db") as latch,
        pytest.raises(SubmitIntentCorrupt),
    ):
        latch.read_settled_pnl_days()


def test_methods_refuse_after_the_lock_is_released(tmp_path: Path) -> None:
    store = _Store()
    with open_submit_intent_latch(store, tmp_path / "s.db") as latch:
        pass
    with pytest.raises(SubmitIntentLockNotHeld):
        latch.write_settled_pnl_day(ROW)
    with pytest.raises(SubmitIntentLockNotHeld):
        latch.read_settled_pnl_days()
    assert store.sets == 0


def test_persist_writes_days_in_order_and_propagates_failure(tmp_path: Path) -> None:
    store = _Store()
    rows = {"2026-10-13": SettledPnlDay("2026-10-13", "1", 1, 0, 0), "2026-10-12": ROW}
    with open_submit_intent_latch(store, tmp_path / "s.db") as latch:
        persist_settled_pnl(latch, rows)
        assert latch.read_settled_pnl_days() == (ROW, rows["2026-10-13"])

    class Boom:
        def write_settled_pnl_day(self, record: SettledPnlDay) -> None:
            raise OSError("disk")

    with pytest.raises(OSError):
        persist_settled_pnl(Boom(), rows)


# -- K=1 pre-boot fill ledger -------------------------------------------------


def test_ledger_returns_only_fills_before_the_first_k_gt1_epoch(tmp_path: Path) -> None:
    store = _Store()
    _seed(store, _fill("o1", "A", 10), _fill("o2", "A", 100), _fill("o3", "A", 150))
    with open_submit_intent_latch(store, tmp_path / "s.db") as latch:
        for boot, k in ((5, 1), (100, 2), (200, 1), (300, 4)):
            latch.write_epoch_row(EpochRow("sha", k, None, boot))
        assert latch.read_first_k_gt1_boot_ts() == 100
        got = latch.read_k1_pre_boot_fills(DurableFillRecord.from_bytes, _all)
    assert [f.venue_order_id for f in got.fills] == ["o1"]


def test_ledger_with_no_k_gt1_epoch_is_every_fill(tmp_path: Path) -> None:
    store = _Store()
    _seed(store, _fill("o1", "A", 10), _fill("o2", "A", 100))
    with open_submit_intent_latch(store, tmp_path / "s.db") as latch:
        latch.write_epoch_row(EpochRow("sha", 1, None, 5))
        assert latch.read_first_k_gt1_boot_ts() is None
        got = latch.read_k1_pre_boot_fills(DurableFillRecord.from_bytes, _all)
    assert [f.venue_order_id for f in got.fills] == ["o1", "o2"]


def test_ledger_filters_to_the_family_and_never_writes() -> None:
    store = _Store()
    _seed(store, _fill("o1", "A", 10), _fill("o2", "B", 11))
    store.sets = 0
    got = pre_boot_fill_ledger(
        store,
        first_k_gt1_boot_ts=50,
        has_epoch_rows=True,
        decode=DurableFillRecord.from_bytes,
        in_family=lambda f: f.instrument_id == "A",
    )
    assert [f.venue_order_id for f in got.fills] == ["o1"]
    assert store.sets == 0


def test_ledger_boundary_fill_at_the_boot_instant_is_excluded() -> None:
    store = _Store()
    _seed(store, _fill("o1", "A", 49), _fill("o2", "A", 50))
    got = pre_boot_fill_ledger(
        store,
        first_k_gt1_boot_ts=50,
        has_epoch_rows=True,
        decode=DurableFillRecord.from_bytes,
        in_family=_all,
    )
    assert [f.venue_order_id for f in got.fills] == ["o1"]


def test_ledger_garbled_fill_row_fails_closed_not_skipped() -> None:
    store = _Store()
    _seed(store, _fill("o1", "A", 10))
    store.data[f"{FILL_PREFIX}bad"] = b"not a fill"
    with pytest.raises(FillLedgerCorrupt):
        pre_boot_fill_ledger(
            store,
            first_k_gt1_boot_ts=None,
            has_epoch_rows=True,
            decode=DurableFillRecord.from_bytes,
            in_family=_all,
        )


def test_ledger_is_deterministic_and_empty_store_is_empty() -> None:
    store = _Store()
    decode = DurableFillRecord.from_bytes
    assert (
        pre_boot_fill_ledger(
            store, first_k_gt1_boot_ts=None, has_epoch_rows=True, decode=decode, in_family=_all
        ).fills
        == ()
    )
    _seed(store, _fill("o2", "A", 2), _fill("o1", "A", 1))
    a = pre_boot_fill_ledger(
        store, first_k_gt1_boot_ts=None, has_epoch_rows=True, decode=decode, in_family=_all
    )
    b = pre_boot_fill_ledger(
        store, first_k_gt1_boot_ts=None, has_epoch_rows=True, decode=decode, in_family=_all
    )
    assert a == b
    assert [f.venue_order_id for f in a.fills] == ["o1", "o2"]


# -- BG-1c review fixes ---------------------------------------------------------


def test_ledger_flags_the_no_epoch_rows_case_distinctly() -> None:
    store = _Store()
    decode = DurableFillRecord.from_bytes
    none_at_all = pre_boot_fill_ledger(
        store, first_k_gt1_boot_ts=None, has_epoch_rows=False, decode=decode, in_family=_all
    )
    no_k_gt1 = pre_boot_fill_ledger(
        store, first_k_gt1_boot_ts=None, has_epoch_rows=True, decode=decode, in_family=_all
    )
    assert none_at_all.no_epoch_rows is True
    assert no_k_gt1.no_epoch_rows is False


def test_latch_ledger_reports_no_epoch_rows(tmp_path: Path) -> None:
    store = _Store()
    with open_submit_intent_latch(store, tmp_path / "s.db") as latch:
        assert latch.read_k1_pre_boot_fills(DurableFillRecord.from_bytes, _all).no_epoch_rows
        latch.write_epoch_row(EpochRow("sha", 1, None, 5))
        assert not latch.read_k1_pre_boot_fills(DurableFillRecord.from_bytes, _all).no_epoch_rows


def test_garbled_fill_keeps_its_cause() -> None:
    store = _Store()
    store.data[f"{FILL_PREFIX}bad"] = b"not a fill"
    with pytest.raises(FillLedgerCorrupt) as info:
        pre_boot_fill_ledger(
            store,
            first_k_gt1_boot_ts=None,
            has_epoch_rows=True,
            decode=DurableFillRecord.from_bytes,
            in_family=_all,
        )
    assert info.value.__cause__ is not None


def _row(pnl: str, settled: int, amb: int = 0, pend: int = 0, over: int = 0) -> SettledPnlDay:
    return SettledPnlDay("2026-10-12", pnl, settled, amb, pend, over)


@pytest.mark.parametrize(
    ("prior", "new", "ok"),
    [
        (_row("-1", 1, 0, 1), _row("-1", 1, 0, 1), True),
        (_row("0", 0, 0, 1), _row("-5", 0, 1, 0), True),
        (_row("-5", 0, 1, 0), _row("2", 1, 0, 0), True),
        (_row("0", 0, 0, 1), _row("0", 0, 0, 0), False),
        (_row("-5", 0, 1, 0), _row("-5", 0, 0, 0), False),
        (_row("-5", 0, 1, 0), _row("-4", 0, 1, 0), False),
        (_row("-5", 1, 0, 0), _row("-4", 1, 0, 0), False),
        (_row("-5", 1, 1, 0), _row("-6", 1, 1, 0), True),
    ],
)
def test_write_is_monotonic(
    prior: SettledPnlDay, new: SettledPnlDay, ok: bool, tmp_path: Path
) -> None:
    store = _Store()
    with open_submit_intent_latch(store, tmp_path / "s.db") as latch:
        latch.write_settled_pnl_day(prior)
        if ok:
            latch.write_settled_pnl_day(new)
            assert latch.read_settled_pnl_day("2026-10-12") == new
        else:
            with pytest.raises(SettledPnlRegression):
                latch.write_settled_pnl_day(new)
            assert latch.read_settled_pnl_day("2026-10-12") == prior


def test_first_write_for_a_day_is_always_allowed(tmp_path: Path) -> None:
    store = _Store()
    with open_submit_intent_latch(store, tmp_path / "s.db") as latch:
        latch.write_settled_pnl_day(_row("9", 3))
        assert latch.read_settled_pnl_day("2026-10-12") == _row("9", 3)


def test_persist_writes_ascending_and_a_mid_loop_failure_leaves_later_days_stale() -> None:
    written: list[str] = []

    class Flaky:
        def write_settled_pnl_day(self, record: SettledPnlDay) -> None:
            if record.day == "2026-10-13":
                raise OSError("disk")
            written.append(record.day)

    rows = {
        "2026-10-14": SettledPnlDay("2026-10-14", "1", 1, 0, 0),
        "2026-10-12": ROW,
        "2026-10-13": SettledPnlDay("2026-10-13", "1", 1, 0, 0),
    }
    with pytest.raises(OSError):
        persist_settled_pnl(Flaky(), rows)
    assert written == ["2026-10-12"]


def _fee_row(pnl: str, settled: int, unrec: int, floor: str, amb: int = 0) -> SettledPnlDay:
    return SettledPnlDay(
        "2026-10-12",
        pnl,
        settled,
        amb,
        0,
        0,
        fee_unreconciled_entries=unrec,
        fee_floor_total=floor,
    )


@pytest.mark.parametrize(
    ("prior", "new", "ok"),
    [
        # reconciling to a lower fee: rise 0.05 <= floor drop 0.07
        (_fee_row("-5", 1, 1, "0.07"), _fee_row("-4.95", 1, 0, "0"), True),
        # rise exactly equal to the drop
        (_fee_row("-5", 1, 1, "0.07"), _fee_row("-4.93", 1, 0, "0"), True),
        # rise larger than the fee delta
        (_fee_row("-5", 1, 1, "0.07"), _fee_row("-4.9", 1, 0, "0"), False),
        # fee-unreconciled count did not drop, so no allowance
        (_fee_row("-5", 1, 1, "0.07"), _fee_row("-4.95", 1, 1, "0.02"), False),
        # shrinking entry counts still raise even with a fee drop
        (_fee_row("-5", 2, 1, "0.07"), _fee_row("-4.95", 1, 0, "0"), False),
    ],
)
def test_pnl_rise_is_allowed_only_up_to_the_reconciled_fee_delta(
    prior: SettledPnlDay, new: SettledPnlDay, ok: bool, tmp_path: Path
) -> None:
    store = _Store()
    with open_submit_intent_latch(store, tmp_path / "s.db") as latch:
        latch.write_settled_pnl_day(prior)
        if ok:
            latch.write_settled_pnl_day(new)
            assert latch.read_settled_pnl_day("2026-10-12") == new
        else:
            with pytest.raises(SettledPnlRegression):
                latch.write_settled_pnl_day(new)


def test_fee_floor_total_must_be_a_canonical_decimal() -> None:
    with pytest.raises(ExecParRecordError):
        encode_record(_fee_row("1", 1, 0, "1e3"))
