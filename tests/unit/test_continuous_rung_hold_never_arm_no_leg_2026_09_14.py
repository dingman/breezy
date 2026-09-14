"""S5 plan E3-1 (Rev 3/Rev 4 E4-8): the never-arm walk's sibling-NO-fill
cross-check.

Replaces the earlier ``test_never_arm_cross_check_for_a_no_fill_shape_is_
undetermined`` xfail in ``test_no_side_first_order_pending_2026_09_14.py``,
which documented two candidate venue shapes without asserting either. Rev 3
adjudicated the shape (a NO fill lands the venue position on the YES id as a
LONG) and Rev 4 (E4-8) confirmed the sibling lookup cannot cross days, so
this file asserts the real implementation.

Fixtures follow the established convention in
``test_continuous_rung_hold_fill_wiring.py`` for exercising
``_run_never_arm_walk``/``iter_fill_records`` directly: a durable fill is
written under the SAME key shape ``record_fill`` produces
(``FILL_INDEX_KEY_PREFIX``/``FILL_KEY_PREFIX`` keyed by instrument id and
venue order id respectively) inside the real ``open_submit_intent_latch``
flock -- never a bare/mismatched key (L-42).
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from nautilus_trader.model.instruments import BinaryOption

from breezy.adapters.polymarket_us.exec.client import (
    FILL_INDEX_KEY_PREFIX,
    FILL_KEY_PREFIX,
    DurableFillRecord,
)
from breezy.adapters.polymarket_us.symbology import sibling_instrument_id
from breezy.runtime.sqlite_store import SqliteStateStore
from breezy.runtime.submit_intent import open_submit_intent_latch
from tests.unit.test_continuous_rung_hold_strategy import (
    _PERMISSIVE_EVIDENCE,
    _register_and_start,
)
from tests.unit.test_current_rung_hold_strategy import (
    INTERIOR_ID,
    WINDOW_OPEN_NS,
    _instrument,
)

_NO_INTERIOR_ID = sibling_instrument_id(INTERIOR_ID)


def _interior_instrument() -> BinaryOption:
    return _instrument(INTERIOR_ID, lower_f=86, upper_f=87)


def _write_fill(store_path: Path, *, instrument_id: object, venue_order_id: str) -> None:
    store = SqliteStateStore(store_path)
    with open_submit_intent_latch(store, store_path):
        fill_record = DurableFillRecord(
            venue_order_id=venue_order_id,
            client_order_id=f"C-{venue_order_id}",
            instrument_id=str(instrument_id),
            order_side="BUY",
            cumulative_qty=Decimal(1),
            cumulative_cost=Decimal("0.40"),
            cumulative_fee=Decimal(0),
            fee_reconciled=True,
            ts_event=WINDOW_OPEN_NS,
        )
        store.set(
            f"{FILL_INDEX_KEY_PREFIX}{instrument_id}",
            json.dumps([venue_order_id]).encode("utf-8"),
        )
        store.set(f"{FILL_KEY_PREFIX}{venue_order_id}", fill_record.to_bytes())
    store.close()


def _long_evidence() -> dict[str, object]:
    return {
        **_PERMISSIVE_EVIDENCE,
        "positions": [
            {"slug": str(INTERIOR_ID.symbol.value), "net_position": "1"},
        ],
    }


def test_a_no_fill_accounts_for_a_venue_long_on_the_yes_id_and_yes_arms(
    tmp_path: Path,
) -> None:
    """(a) A NO fill on the sibling instrument-day accounts for a venue
    LONG on the YES id with no YES fill of its own -- the walk arms YES
    instead of halting, logs the accounting decision, and the halt counter
    never fires."""
    store_path = tmp_path / "state.db"
    _write_fill(store_path, instrument_id=_NO_INTERIOR_ID, venue_order_id="ord-no-1")

    strategy = _register_and_start(
        store_path=store_path,
        instruments=(_interior_instrument(),),
        position_evidence_reader=_long_evidence,
    )

    assert strategy._run_never_arm_walk() is True
    assert strategy.position_events.count("unreconciled_long_no_fill") == 0
    assert strategy.last_startup_evidence_summary is not None
    assert "accounted-by-no-leg" in strategy.last_startup_evidence_summary
    assert f"'{INTERIOR_ID}': 'accounted-by-no-leg'" in strategy.last_startup_evidence_summary

    # (e) the NO leg itself stays non-armable/UNKNOWN -- the accounting of
    # the YES-side LONG never flips the NO leg's own arming decision.
    assert f"'{_NO_INTERIOR_ID}': 'UNKNOWN'" in strategy.last_startup_evidence_summary


def test_a_venue_long_with_no_fill_on_either_leg_still_halts(
    tmp_path: Path,
) -> None:
    """(b) Pin today's fail-closed behaviour: a LONG with no durable fill on
    EITHER leg halts exactly as before."""
    store_path = tmp_path / "state.db"

    strategy = _register_and_start(
        store_path=store_path,
        instruments=(_interior_instrument(),),
        position_evidence_reader=_long_evidence,
    )

    assert strategy._run_never_arm_walk() is False
    assert strategy.position_events.count("unreconciled_long_no_fill") == 1


def test_a_venue_long_with_a_yes_fill_is_unchanged(tmp_path: Path) -> None:
    """(c) A YES fill accounts for the LONG exactly as before (the
    is_consumed short-circuit fires before slug_ok is ever computed) --
    the sibling NO cross-check is irrelevant here and nothing regresses."""
    store_path = tmp_path / "state.db"
    _write_fill(store_path, instrument_id=INTERIOR_ID, venue_order_id="ord-yes-1")

    strategy = _register_and_start(
        store_path=store_path,
        instruments=(_interior_instrument(),),
        position_evidence_reader=_long_evidence,
    )

    assert strategy._run_never_arm_walk() is True
    assert strategy.position_events.count("unreconciled_long_no_fill") == 0


def test_a_no_fill_with_a_flat_venue_slug_never_enters_the_accounting_branch(
    tmp_path: Path,
) -> None:
    """(d) When the venue reports the slug flat/non-long, `slug_ok` is
    already `True` and the `if not slug_ok:` block -- including the new
    NO-leg cross-check -- is never entered at all."""
    store_path = tmp_path / "state.db"
    _write_fill(store_path, instrument_id=_NO_INTERIOR_ID, venue_order_id="ord-no-2")

    strategy = _register_and_start(
        store_path=store_path,
        instruments=(_interior_instrument(),),
        position_evidence_reader=lambda: _PERMISSIVE_EVIDENCE,
    )

    assert strategy._run_never_arm_walk() is True
    assert strategy.position_events.count("unreconciled_long_no_fill") == 0
    assert strategy.last_startup_evidence_summary is not None
    assert "accounted-by-no-leg" not in strategy.last_startup_evidence_summary
