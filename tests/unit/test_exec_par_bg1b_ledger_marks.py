"""EXEC-PAR BG-1b: the ledger's ever-ambiguous mark set (read + acknowledge, value-free)."""

from __future__ import annotations

import inspect
from decimal import Decimal
from typing import Any

import pytest

from breezy.adapters.polymarket_us.operator_controls import DailySpendLedger
from breezy.runtime.exec_par_counter_ingest import AmbiguousMarkSource

NOW = 1_700_000_000 * 1_000_000_000


def _register(ledger: DailySpendLedger, key: str, side: str = "BUY") -> None:
    ledger.register_open_exposure(
        key, Decimal("4.00"), booking=None, seeded_partial_usd=Decimal(0), side=side, now_ns=NOW
    )


def test_mark_ambiguous_records_a_pending_mark_with_the_unknown_source() -> None:
    ledger = DailySpendLedger()
    _register(ledger, "i1")
    assert ledger.ambiguous_marks_pending() == frozenset()
    ledger.mark_ambiguous("i1")
    assert ledger.ambiguous_marks_pending() == frozenset({("i1", "unknown")})


def test_unregistered_key_leaves_no_mark() -> None:
    ledger = DailySpendLedger()
    ledger.mark_ambiguous("exit-or-unknown")
    assert ledger.ambiguous_marks_pending() == frozenset()


def test_a_mark_survives_abandon_and_settle_so_a_fast_resolution_is_still_counted() -> None:
    ledger = DailySpendLedger()
    _register(ledger, "i1")
    _register(ledger, "i2")
    ledger.mark_ambiguous("i1")
    ledger.mark_ambiguous("i2")
    assert ledger.abandon_open_exposure("i1") is True
    assert ledger.settle("i2", booking=None, realized_usd=None, fill_ts_ns=None, now_ns=NOW + 1)
    assert ledger.has_open_exposure("i1") is False
    assert ledger.ambiguous_marks_pending() == frozenset({("i1", "unknown"), ("i2", "unknown")})


def test_repeat_marks_are_one_entry_and_acknowledge_shrinks_the_set() -> None:
    ledger = DailySpendLedger()
    for key in ("i1", "i2"):
        _register(ledger, key)
        ledger.mark_ambiguous(key)
    ledger.mark_ambiguous("i1")
    assert len(ledger.ambiguous_marks_pending()) == 2
    ledger.ack_ambiguous_marks([("i1", "unknown")])
    assert ledger.ambiguous_marks_pending() == frozenset({("i2", "unknown")})
    ledger.ack_ambiguous_marks([("i1", "unknown"), ("never-marked", "unknown")])  # tolerant
    ledger.ack_ambiguous_marks([("i2", "unknown")])
    assert ledger.ambiguous_marks_pending() == frozenset()


def test_pending_marks_are_a_snapshot_not_a_live_view() -> None:
    ledger = DailySpendLedger()
    _register(ledger, "i1")
    ledger.mark_ambiguous("i1")
    snapshot = ledger.ambiguous_marks_pending()
    ledger.ack_ambiguous_marks(snapshot)
    assert snapshot == frozenset({("i1", "unknown")})


def test_the_mark_surface_is_value_free() -> None:
    ledger = DailySpendLedger()
    _register(ledger, "i1")
    ledger.mark_ambiguous("i1")
    for mark in ledger.ambiguous_marks_pending():
        assert all(isinstance(part, str) for part in mark)
        assert "4" not in "".join(mark)
    sig = inspect.signature(DailySpendLedger.ambiguous_marks_pending)
    assert "Decimal" not in str(sig.return_annotation)


def test_ledger_satisfies_the_runtime_side_protocol_structurally() -> None:
    source: AmbiguousMarkSource = DailySpendLedger()
    assert source.ambiguous_marks_pending() == frozenset()


def test_ack_rejects_non_pair_input() -> None:
    ledger = DailySpendLedger()
    bad: Any = ["not-a-pair"]
    with pytest.raises(ValueError):
        ledger.ack_ambiguous_marks(bad)
