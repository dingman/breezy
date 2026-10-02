"""CT-7: continuous-strategy snapshot dedupe key is `(ts_event, ask, size)`.

Entry point: `ContinuousRungHoldStrategy.on_quote_tick`, driven by a
`TestClock` and the harness in `tests/unit/test_continuous_rung_hold_strategy.py`.
Quotes reach the real `_hunt_tick` dedupe (`continuous_strategy.py`) and the
real `OfferTape.append` writer.

Two quotes that share `ts_event` and ask but differ in size are both
recorded. A third quote with the same triple as the second is not.

A fourth quote differs from the third only in ask; a fifth differs from the
fourth only in `ts_event`. Both are kept.

Red mutations in `_hunt_tick`'s `dedupe_key`: drop `size` (the second quote
collapses onto the first), drop `snapshot.ask` (the fourth collapses onto the
third), or drop `snapshot.ts_event` (the fifth collapses onto the fourth).
"""

from __future__ import annotations

from pathlib import Path

from nautilus_trader.common.component import TestClock

from breezy.strategy.current_rung_hold.offer_tape import OfferTape
from tests.unit.test_continuous_rung_hold_strategy import _register_and_start
from tests.unit.test_current_rung_hold_strategy import (
    INTERIOR_ID,
    WINDOW_OPEN_NS,
    _instrument,
    _observation,
    _quote,
)


def test_size_distinguishes_snapshot_dedupe_and_identical_triples_collapse(
    tmp_path: Path,
) -> None:
    store_path = tmp_path / "state.db"
    tape = OfferTape(tmp_path / "offers.jsonl")
    clock = TestClock()
    clock.set_time(WINDOW_OPEN_NS)
    strategy = _register_and_start(
        store_path=store_path,
        instruments=(_instrument(INTERIOR_ID, lower_f=86, upper_f=87),),
        clock=clock,
        offer_tape=tape,
    )
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))

    # ask=0.80 refuses (`edge_below_break_even`) and still reaches the tape,
    # so the latch is not consumed and only the dedupe key can drop a row.
    strategy.on_quote_tick(_quote(INTERIOR_ID, ask="0.80", size=10, ts_event=WINDOW_OPEN_NS))
    strategy.on_quote_tick(_quote(INTERIOR_ID, ask="0.80", size=25, ts_event=WINDOW_OPEN_NS))
    strategy.on_quote_tick(_quote(INTERIOR_ID, ask="0.80", size=25, ts_event=WINDOW_OPEN_NS))

    strategy.on_quote_tick(_quote(INTERIOR_ID, ask="0.81", size=25, ts_event=WINDOW_OPEN_NS))
    strategy.on_quote_tick(_quote(INTERIOR_ID, ask="0.81", size=25, ts_event=WINDOW_OPEN_NS + 1))

    yes = [record for record in strategy.offer_tape.records() if record.side == "YES"]
    assert [(record.ts_event, record.ask, record.size) for record in yes] == [
        (WINDOW_OPEN_NS, "0.8", 10),
        (WINDOW_OPEN_NS, "0.8", 25),
        (WINDOW_OPEN_NS, "0.81", 25),
        (WINDOW_OPEN_NS + 1, "0.81", 25),
    ]
    assert {record.reason for record in yes} == {"edge_below_break_even"}
    assert tape.sidecar_errors == 0
