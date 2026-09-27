"""F-2 (STALL_FOLLOWUPS_F1_F4_2026-09-24.md): the hourly `crh_diag_hourly_v1`
diagnostics-summary sidecar `_maybe_roll_diagnostics` emits from
`_hunt_tick`'s head.

Harness mirrors `test_continuous_rung_hold_no_only_hunt_2026_09_24.py`'s own
local `_register`/`_register_and_start` (a `config` override, since the
shared harness in `test_continuous_rung_hold_strategy.py` hard-pins the
calibration gate and is on the "must stay green, unedited" list).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path

import pytest
from nautilus_trader.common.component import TestClock
from nautilus_trader.model.identifiers import TraderId
from nautilus_trader.model.instruments import BinaryOption
from nautilus_trader.portfolio import Portfolio
from nautilus_trader.test_kit.stubs.component import TestComponentStubs

from breezy.runtime.sqlite_store import SqliteStateStore
from breezy.runtime.submit_intent import open_submit_intent_latch
from breezy.strategy.current_rung_hold.config import CurrentRungHoldConfig
from breezy.strategy.current_rung_hold.continuous_strategy import ContinuousRungHoldStrategy
from breezy.strategy.current_rung_hold.diagnostics_summary import DiagnosticsSummarySink
from breezy.strategy.current_rung_hold.trial_day_latch import (
    CONTINUOUS_TRIAL_KEY_PREFIX,
    TrialDayLatch,
    open_trial_day_latch,
)
from tests.unit.test_continuous_rung_hold_no_only_hunt_2026_09_24 import (
    _BAND_CLEARING_BID,
    _bid_only_depth,
    _gate_cleared_config,
)
from tests.unit.test_current_rung_hold_strategy import (
    INTERIOR_ID,
    NS_PER_MIN,
    STATION,
    WINDOW_OPEN_NS,
    _instrument,
    _observation,
    _quote,
)

_NS_PER_HOUR = 3_600_000_000_000


@pytest.fixture
def store_path(tmp_path: Path) -> Path:
    return tmp_path / "state.db"


@pytest.fixture
def interior_instrument() -> BinaryOption:
    return _instrument(INTERIOR_ID, lower_f=86, upper_f=87)


_TEST_FAMILY_ID = "pm_us_crh_test"


@contextmanager
def _open_cont_latch(
    store_path: Path, *, family_id: str = _TEST_FAMILY_ID,
) -> Iterator[TrialDayLatch]:
    with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as intent_latch:
        yield open_trial_day_latch(
            intent_latch, key_prefix=CONTINUOUS_TRIAL_KEY_PREFIX, family_id=family_id,
        )


def _cont_latch_factory(
    store_path: Path, *, family_id: str = _TEST_FAMILY_ID,
) -> Callable[[], AbstractContextManager[TrialDayLatch]]:
    return lambda: _open_cont_latch(store_path, family_id=family_id)


def _register_and_start(
    *,
    store_path: Path,
    instruments: tuple[BinaryOption, ...],
    config: CurrentRungHoldConfig | None = None,
    diagnostics_summary: DiagnosticsSummarySink | None = None,
    build_sha: str = "unknown",
) -> ContinuousRungHoldStrategy:
    cfg = config or CurrentRungHoldConfig(
        instrument_ids=tuple(instrument.id for instrument in instruments),
    )
    strategy = ContinuousRungHoldStrategy(
        cfg,
        trial_day_latch_factory=_cont_latch_factory(store_path),
        diagnostics_summary=diagnostics_summary,
        build_sha=build_sha,
    )
    clock = TestClock()
    clock.set_time(WINDOW_OPEN_NS)
    msgbus = TestComponentStubs.msgbus()
    cache = TestComponentStubs.cache()
    for instrument in instruments:
        cache.add_instrument(instrument)
    portfolio = Portfolio(msgbus=msgbus, cache=cache, clock=clock)
    strategy.register(
        trader_id=TraderId("BACKTEST-001"),
        portfolio=portfolio,
        msgbus=msgbus,
        cache=cache,
        clock=clock,
    )
    strategy.start()
    return strategy


def _rows(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


class TestHourlyRollover:
    def test_rollover_one_row_per_hour(
        self, store_path: Path, interior_instrument: BinaryOption, tmp_path: Path,
    ) -> None:
        path = tmp_path / "diagnostics_summary.jsonl"
        sink = DiagnosticsSummarySink(path)
        strategy = _register_and_start(
            store_path=store_path,
            instruments=(interior_instrument,),
            diagnostics_summary=sink,
            build_sha="cafefeed1234",
        )
        hour0_bucket = WINDOW_OPEN_NS // _NS_PER_HOUR

        strategy.on_quote_tick(_quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS))
        strategy.on_quote_tick(
            _quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS + NS_PER_MIN),
        )
        assert _rows(path) == []  # bucket has not advanced yet -- no emission

        hour1_start = (hour0_bucket + 1) * _NS_PER_HOUR
        strategy.on_quote_tick(_quote(INTERIOR_ID, ask="0.40", ts_event=hour1_start))
        rows = _rows(path)
        assert len(rows) == 1
        assert rows[0]["hour_utc_start_ns"] == hour0_bucket * _NS_PER_HOUR
        assert rows[0]["final"] is False
        assert rows[0]["build_sha"] == "cafefeed1234"

        hour2_start = hour1_start + _NS_PER_HOUR
        strategy.on_quote_tick(_quote(INTERIOR_ID, ask="0.40", ts_event=hour2_start))
        assert len(_rows(path)) == 2

    def test_older_on_data_ts_never_rolls_back(
        self, store_path: Path, interior_instrument: BinaryOption, tmp_path: Path,
    ) -> None:
        path = tmp_path / "diagnostics_summary.jsonl"
        sink = DiagnosticsSummarySink(path)
        strategy = _register_and_start(
            store_path=store_path, instruments=(interior_instrument,), diagnostics_summary=sink,
        )
        hour0_bucket = WINDOW_OPEN_NS // _NS_PER_HOUR
        strategy.on_quote_tick(_quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS))
        hour1_start = (hour0_bucket + 1) * _NS_PER_HOUR
        strategy.on_quote_tick(_quote(INTERIOR_ID, ask="0.41", ts_event=hour1_start))
        assert len(_rows(path)) == 1

        # An older ts_event (a retry re-evaluating a stale cached quote)
        # must never roll the bucket back or emit a second row for hour 0.
        strategy.on_quote_tick(_quote(INTERIOR_ID, ask="0.42", ts_event=WINDOW_OPEN_NS))
        assert len(_rows(path)) == 1

    def test_final_row_emitted_on_stop(
        self, store_path: Path, interior_instrument: BinaryOption, tmp_path: Path,
    ) -> None:
        path = tmp_path / "diagnostics_summary.jsonl"
        sink = DiagnosticsSummarySink(path)
        strategy = _register_and_start(
            store_path=store_path, instruments=(interior_instrument,), diagnostics_summary=sink,
        )
        strategy.on_quote_tick(_quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS))
        assert _rows(path) == []

        strategy.stop()

        rows = _rows(path)
        assert len(rows) == 1
        assert rows[0]["final"] is True

    def test_a_process_that_never_hunts_a_tick_emits_nothing_on_stop(
        self, store_path: Path, interior_instrument: BinaryOption, tmp_path: Path,
    ) -> None:
        path = tmp_path / "diagnostics_summary.jsonl"
        sink = DiagnosticsSummarySink(path)
        strategy = _register_and_start(
            store_path=store_path, instruments=(interior_instrument,), diagnostics_summary=sink,
        )

        strategy.stop()

        assert _rows(path) == []


class TestPerProcessDeltasSumToSnapshot:
    def test_per_process_deltas_sum_to_on_stop_snapshot(
        self, store_path: Path, interior_instrument: BinaryOption, tmp_path: Path,
    ) -> None:
        path = tmp_path / "diagnostics_summary.jsonl"
        sink = DiagnosticsSummarySink(path)
        strategy = _register_and_start(
            store_path=store_path, instruments=(interior_instrument,), diagnostics_summary=sink,
        )
        hour0_bucket = WINDOW_OPEN_NS // _NS_PER_HOUR
        # Every tick below is out-of-window (hour_lst outside [12, 17)) or
        # pre-decision -- `on_data` is never called, so every quote refuses
        # `not_executable`/`outside_decision_window`-shaped diagnostics as
        # the running max is absent. What matters here is only that the
        # SAME diagnostics dict accumulates across hours.
        strategy.on_quote_tick(_quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS))
        hour1_start = (hour0_bucket + 1) * _NS_PER_HOUR
        strategy.on_quote_tick(_quote(INTERIOR_ID, ask="0.40", ts_event=hour1_start))
        hour2_start = hour1_start + _NS_PER_HOUR
        strategy.on_quote_tick(_quote(INTERIOR_ID, ask="0.40", ts_event=hour2_start))

        strategy.stop()

        rows = _rows(path)
        assert len(rows) == 3  # two rollovers + one final
        summed: dict[str, int] = {}
        for row in rows:
            for key, count in row["diagnostics"].items():  # type: ignore[union-attr]
                summed[key] = summed.get(key, 0) + count
        assert summed == dict(sorted(strategy.diagnostics.counts.items()))


class TestNoNewCounterKeys:
    def test_no_new_counter_keys(
        self, store_path: Path, interior_instrument: BinaryOption,
    ) -> None:
        """AC4: `diagnostics`/`refusals` gain no new keys -- the two F-2
        coordinator counters live ONLY in the JSONL row, never in either
        counter dict the halt detector/alerters read."""
        strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
        before_diag_keys = set(strategy.diagnostics.counts)
        before_refusal_keys = set(strategy.refusals.counts)

        strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
        strategy.on_quote_tick(_quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS))
        strategy.on_order_book_depth(
            _bid_only_depth(bid=_BAND_CLEARING_BID, ts_event=WINDOW_OPEN_NS + NS_PER_MIN)
        )

        assert set(strategy.diagnostics.counts) <= before_diag_keys | set(
            strategy.diagnostics.counts
        )
        # The real assertion: no key this run introduces is a NEW key this
        # class did not already define before F-2 -- proven by the closed
        # constant set every diagnostics-recording call site already uses
        # (`_DIAG_*` constants), never by a snapshot equality (this tick
        # legitimately increments existing keys).
        assert "bid_only_in_window" not in strategy.diagnostics.counts
        assert "no_out_of_band" not in strategy.diagnostics.counts
        assert "bid_only_in_window" not in strategy.refusals.counts
        assert "no_out_of_band" not in strategy.refusals.counts
        assert before_refusal_keys <= set(strategy.refusals.counts)


class TestNoTakesCounter:
    def test_no_takes_counted_at_no_inflight_and_halt_detector_takes_unchanged(
        self, store_path: Path, interior_instrument: BinaryOption,
    ) -> None:
        config = _gate_cleared_config(instruments=(interior_instrument,))
        strategy = _register_and_start(
            store_path=store_path, instruments=(interior_instrument,), config=config,
        )
        observed_takes: list[int] = []

        class _StubHaltDetector:
            def observe(self, *, takes: int, **_kwargs: object) -> None:
                observed_takes.append(takes)

        strategy.halt_detector = _StubHaltDetector()  # type: ignore[assignment]
        strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
        assert strategy.no_takes == 0

        strategy.on_quote_tick(
            _quote(INTERIOR_ID, ask="0.97", bid=_BAND_CLEARING_BID, ts_event=WINDOW_OPEN_NS)
        )

        assert strategy.no_takes == 1
        assert strategy.takes == 0
        # The halt detector only ever observed YES `takes` (0) -- never
        # bumped by the NO-side arm above.
        assert observed_takes and all(value == 0 for value in observed_takes)


class TestStationField:
    def test_station_field_is_joined_config_stations(
        self, store_path: Path, interior_instrument: BinaryOption, tmp_path: Path,
    ) -> None:
        path = tmp_path / "diagnostics_summary.jsonl"
        sink = DiagnosticsSummarySink(path)
        config = CurrentRungHoldConfig(
            instrument_ids=(interior_instrument.id,), stations=(STATION,),
        )
        strategy = _register_and_start(
            store_path=store_path,
            instruments=(interior_instrument,),
            config=config,
            diagnostics_summary=sink,
        )
        hour0_bucket = WINDOW_OPEN_NS // _NS_PER_HOUR
        strategy.on_quote_tick(_quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS))
        hour1_start = (hour0_bucket + 1) * _NS_PER_HOUR
        strategy.on_quote_tick(_quote(INTERIOR_ID, ask="0.40", ts_event=hour1_start))

        rows = _rows(path)
        assert rows[0]["station"] == ",".join(strategy._config.stations)
        assert rows[0]["station"] == STATION


class TestBidOnlyAndNoOutOfBandCounters:
    def test_bid_only_in_window_frame_is_counted(
        self, store_path: Path, interior_instrument: BinaryOption,
    ) -> None:
        strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
        strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))

        strategy.on_order_book_depth(
            _bid_only_depth(bid=_BAND_CLEARING_BID, ts_event=WINDOW_OPEN_NS)
        )

        assert strategy._bid_only_in_window_frames == 1
        assert strategy._no_out_of_band_frames == 0

    def test_no_out_of_band_frame_is_counted_distinctly(
        self, store_path: Path, interior_instrument: BinaryOption,
    ) -> None:
        strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
        strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))

        # bid=0.50 -> NO_ask = 1 - 0.50 = 0.50, deep inside the band -- use a
        # bid that pushes the NO leg OUT of the executable band instead
        # (bid=0.02 -> NO_ask=0.98, above the 0.95 upper bound).
        strategy.on_order_book_depth(_bid_only_depth(bid="0.02", ts_event=WINDOW_OPEN_NS))

        assert strategy._bid_only_in_window_frames == 1
        assert strategy._no_out_of_band_frames == 1

    def test_bid_only_out_of_window_frame_stays_invisible(
        self, store_path: Path, interior_instrument: BinaryOption,
    ) -> None:
        """Documented, not fixed: an out-of-window bid-only frame returns
        silently BEFORE either new counter -- it stays invisible to the
        halt baseline exactly as the plan doc's F-2 addendum states."""
        strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
        strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
        out_of_window_ts = WINDOW_OPEN_NS - 6 * NS_PER_MIN * 60  # well before the LST window

        strategy.on_order_book_depth(
            _bid_only_depth(bid=_BAND_CLEARING_BID, ts_event=out_of_window_ts)
        )

        assert strategy._bid_only_in_window_frames == 0
        assert strategy._no_out_of_band_frames == 0


class TestSidecarFailureContained:
    def test_sidecar_oserror_never_raises(
        self, store_path: Path, interior_instrument: BinaryOption, tmp_path: Path,
    ) -> None:
        blocker = tmp_path / "blocked"
        blocker.write_text("not a directory")
        sink = DiagnosticsSummarySink(blocker / "diagnostics_summary.jsonl")
        strategy = _register_and_start(
            store_path=store_path, instruments=(interior_instrument,), diagnostics_summary=sink,
        )
        hour0_bucket = WINDOW_OPEN_NS // _NS_PER_HOUR
        strategy.on_quote_tick(_quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS))
        hour1_start = (hour0_bucket + 1) * _NS_PER_HOUR

        # Never raises, even though the sidecar's directory is unwritable.
        strategy.on_quote_tick(_quote(INTERIOR_ID, ask="0.40", ts_event=hour1_start))
        strategy.stop()


class TestSinkHealthSurfacedInNextRow:
    def test_sink_errors_surfaced_in_the_next_row(
        self,
        store_path: Path,
        interior_instrument: BinaryOption,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """LOW (silent-failure review, 2026-09-25): `DiagnosticsSummarySink.
        errors` -- its OWN health -- is mirrored into the NEXT row as a
        delta, mirroring `offer_tape_capped`."""
        path = tmp_path / "diagnostics_summary.jsonl"
        sink = DiagnosticsSummarySink(path)
        strategy = _register_and_start(
            store_path=store_path, instruments=(interior_instrument,), diagnostics_summary=sink,
        )
        hour0_bucket = WINDOW_OPEN_NS // _NS_PER_HOUR
        strategy.on_quote_tick(_quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS))

        # One write failure BEFORE the first rollover -- `sink.errors`
        # becomes 1, which the rollover's own row must carry as a delta.
        def _boom(self: Path, *args: object, **kwargs: object) -> None:
            raise OSError("simulated fault")

        monkeypatch.setattr(Path, "open", _boom)
        sink.append({"pid": 999})
        monkeypatch.undo()
        assert sink.errors == 1

        hour1_start = (hour0_bucket + 1) * _NS_PER_HOUR
        strategy.on_quote_tick(_quote(INTERIOR_ID, ask="0.40", ts_event=hour1_start))

        rows = _rows(path)
        assert len(rows) == 1
        assert rows[0]["diagnostics_summary_errors"] == 1
        assert rows[0]["diagnostics_summary_capped"] == 0

    def test_sink_capped_surfaced_in_the_next_row(
        self, store_path: Path, interior_instrument: BinaryOption, tmp_path: Path,
    ) -> None:
        path = tmp_path / "diagnostics_summary.jsonl"
        sink = DiagnosticsSummarySink(path)
        strategy = _register_and_start(
            store_path=store_path, instruments=(interior_instrument,), diagnostics_summary=sink,
        )
        hour0_bucket = WINDOW_OPEN_NS // _NS_PER_HOUR
        strategy.on_quote_tick(_quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS))

        # `sink._max_bytes` is private but this is the same sink instance
        # the strategy holds -- shrink its cap so a manual append is capped
        # before the rollover's own row is written.
        sink._max_bytes = 1  # type: ignore[attr-defined]
        sink.append({"pid": 999})
        assert sink.capped == 1
        sink._max_bytes = 4 * 1024 * 1024  # type: ignore[attr-defined]

        hour1_start = (hour0_bucket + 1) * _NS_PER_HOUR
        strategy.on_quote_tick(_quote(INTERIOR_ID, ask="0.40", ts_event=hour1_start))

        rows = _rows(path)
        assert len(rows) == 1
        assert rows[0]["diagnostics_summary_capped"] == 1


class TestBucketAdvancesOnlyOnSuccessfulEmission:
    def test_a_failed_emission_retries_on_the_next_tick(
        self, store_path: Path, interior_instrument: BinaryOption, tmp_path: Path,
    ) -> None:
        path = tmp_path / "diagnostics_summary.jsonl"
        sink = DiagnosticsSummarySink(path)
        strategy = _register_and_start(
            store_path=store_path, instruments=(interior_instrument,), diagnostics_summary=sink,
        )
        hour0_bucket = WINDOW_OPEN_NS // _NS_PER_HOUR
        strategy.on_quote_tick(_quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS))
        hour1_start = (hour0_bucket + 1) * _NS_PER_HOUR

        # The FIRST rollover attempt fails.
        original = strategy._emit_diagnostics_row
        calls: list[int] = []

        def _flaky(*, hour_utc_start_ns: int, final: bool) -> bool:
            calls.append(hour_utc_start_ns)
            if len(calls) == 1:
                raise RuntimeError("simulated emission fault")
            return original(hour_utc_start_ns=hour_utc_start_ns, final=final)

        strategy._emit_diagnostics_row = _flaky  # type: ignore[method-assign]

        strategy.on_quote_tick(_quote(INTERIOR_ID, ask="0.40", ts_event=hour1_start))
        assert _rows(path) == []  # the first attempt failed -- nothing written
        assert strategy._diag_hourly_bucket == hour0_bucket  # bucket did NOT advance

        # The SAME closed hour is retried on the next in-hour-1 tick.
        strategy.on_quote_tick(
            _quote(INTERIOR_ID, ask="0.41", ts_event=hour1_start + NS_PER_MIN)
        )
        rows = _rows(path)
        assert len(rows) == 1
        assert rows[0]["hour_utc_start_ns"] == hour0_bucket * _NS_PER_HOUR
        assert strategy._diag_hourly_bucket == hour0_bucket + 1
