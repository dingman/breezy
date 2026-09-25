"""Coordinator carry-forward (STALL_FOLLOWUPS_F1_F4_2026-09-24.md, F-2):
integration proof that the WRITER side (``ContinuousRungHoldStrategy`` +
``OfferTape`` + ``DiagnosticsSummarySink``) and the READER side (the AUD-03
digest) agree on ``offer_tape_capped`` -- the offer tape hitting its byte
cap must surface as ``truncated=1`` in the digest's alert detail and
artefact, end to end, with no hand-authored JSONL fixture standing in for
either side.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path
from types import ModuleType

import pytest
from nautilus_trader.common.component import TestClock
from nautilus_trader.model.identifiers import TraderId
from nautilus_trader.portfolio import Portfolio
from nautilus_trader.test_kit.stubs.component import TestComponentStubs

from breezy.runtime.sqlite_store import SqliteStateStore
from breezy.runtime.submit_intent import open_submit_intent_latch
from breezy.strategy.current_rung_hold.config import CurrentRungHoldConfig
from breezy.strategy.current_rung_hold.continuous_strategy import ContinuousRungHoldStrategy
from breezy.strategy.current_rung_hold.diagnostics_summary import DiagnosticsSummarySink
from breezy.strategy.current_rung_hold.offer_tape import OfferTape, OfferTapeRecord
from breezy.strategy.current_rung_hold.trial_day_latch import (
    CONTINUOUS_TRIAL_KEY_PREFIX,
    TrialDayLatch,
    open_trial_day_latch,
)
from tests.unit.test_current_rung_hold_strategy import (
    INTERIOR_ID,
    STATION,
    WINDOW_OPEN_NS,
    _instrument,
    _observation,
    _quote,
)

_NS_PER_HOUR = 3_600_000_000_000


@pytest.fixture
def digest_module() -> ModuleType:
    script = (
        Path(__file__).resolve().parents[2]
        / "scripts"
        / "analysis"
        / "decision_funnel_daily_digest.py"
    )
    spec = importlib.util.spec_from_file_location("decision_funnel_daily_digest_f2it", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@contextmanager
def _open_cont_latch(store_path: Path) -> Iterator[TrialDayLatch]:
    with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as intent_latch:
        yield open_trial_day_latch(intent_latch, key_prefix=CONTINUOUS_TRIAL_KEY_PREFIX)


def _cont_latch_factory(
    store_path: Path,
) -> Callable[[], AbstractContextManager[TrialDayLatch]]:
    return lambda: _open_cont_latch(store_path)


def _make_record(*, ts_event: int) -> OfferTapeRecord:
    return OfferTapeRecord(
        station=STATION,
        climate_day="2026-09-04",
        instrument_id=str(INTERIOR_ID),
        ask="0.80",
        size=1,
        reason="edge_below_break_even",
        ts_event=ts_event,
        hour_lst=12,
        width_code=0,
        m_code=0,
        trigger="on_quote_tick",
        quote_age_ns=None,
        minutes_since_window_open=1,
        prior_eligible_snaps=0,
        illegal_cell=False,
        source="quote",
    )


def test_offer_tape_cap_surfaces_as_truncated_through_the_digest(
    tmp_path: Path, digest_module: ModuleType,
) -> None:
    store_path = tmp_path / "state.db"
    tape_path = tmp_path / "offer_tape_2026-09-04.jsonl"
    summary_path = tmp_path / "diagnostics_summary_2026-09-04.jsonl"

    # A cap sized to admit exactly ONE row (903 bytes, measured from this
    # record shape) -- the first append lands on disk (the digest funnel
    # needs at least one real row to read), the second is refused by the
    # cap, exactly the writer-side condition F-2's row must carry forward.
    tape = OfferTape(tape_path, sidecar_max_bytes=903)
    diagnostics_summary = DiagnosticsSummarySink(summary_path)
    config = CurrentRungHoldConfig(
        instrument_ids=(INTERIOR_ID,), stations=(STATION,),
    )
    strategy = ContinuousRungHoldStrategy(
        config,
        trial_day_latch_factory=_cont_latch_factory(store_path),
        offer_tape=tape,
        diagnostics_summary=diagnostics_summary,
    )
    clock = TestClock()
    clock.set_time(WINDOW_OPEN_NS)
    msgbus = TestComponentStubs.msgbus()
    cache = TestComponentStubs.cache()
    cache.add_instrument(_instrument(INTERIOR_ID, lower_f=86, upper_f=87))
    portfolio = Portfolio(msgbus=msgbus, cache=cache, clock=clock)
    strategy.register(
        trader_id=TraderId("BACKTEST-001"), portfolio=portfolio, msgbus=msgbus, cache=cache,
        clock=clock,
    )
    strategy.start()

    # A real tick through `_hunt_tick`, so `_maybe_roll_diagnostics` takes
    # its first-ever baseline (`on_stop` only emits a final row once a
    # baseline exists).
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
    strategy.on_quote_tick(_quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS))

    # WRITER: two more eligible-snapshot rows -- the cap admits at most one
    # row total, and the tick above already wrote one, so BOTH of these are
    # refused by the byte cap.
    strategy.offer_tape.append(_make_record(ts_event=WINDOW_OPEN_NS + 1))
    strategy.offer_tape.append(_make_record(ts_event=WINDOW_OPEN_NS + 2))
    capped_by_writer = strategy.offer_tape.sidecar_capped
    assert capped_by_writer >= 2

    # F-2: the offer tape's own row IS on disk (bounded in-memory deque
    # never refuses), so the digest funnel has something to read.
    assert tape_path.exists()

    # F-2: the FINAL diagnostics-summary row (on_stop) carries the delta,
    # and it agrees EXACTLY with what the writer itself counted.
    strategy.stop()
    summary_rows = [
        json.loads(line) for line in summary_path.read_text().splitlines() if line.strip()
    ]
    assert len(summary_rows) == 1
    assert summary_rows[0]["offer_tape_capped"] == capped_by_writer
    assert summary_rows[0]["final"] is True

    # READER: the digest, run read-only against both real sidecars.
    sink_calls: list[object] = []

    class _RecordingSink:
        def emit(self, payload: object) -> None:
            sink_calls.append(payload)

    digest_module.resolve_alert_sink = lambda env=None: _RecordingSink()  # type: ignore[assignment]
    code = digest_module.main(
        [
            "--tape", str(tape_path),
            "--climate-day", "2026-09-04",
            "--stations", STATION,
            "--output-dir", str(tmp_path / "out"),
            "--store-path", str(tmp_path / "absent.sqlite"),
        ]
    )

    assert code == 0
    assert len(sink_calls) == 1
    assert "truncated=1" in sink_calls[0].detail  # type: ignore[attr-defined]
    artefact = json.loads(
        (tmp_path / "out" / "decision_funnel_2026-09-04.json").read_text(encoding="utf-8")
    )
    assert artefact["truncated"] == 1
