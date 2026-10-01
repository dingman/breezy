"""FQ-S11: the fq decision-funnel aggregator and its native clock timer.

``FqDecisionCounts`` is pure (no Nautilus import, no I/O) -- tested directly.
``FqDecisionFunnelActor`` is tested on a real ``TestClock``/``register_base``
harness, mirroring ``test_strategy.py``'s own style, never a stubbed clock.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest
from nautilus_trader.common.component import TestClock
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.enums import AssetClass
from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
from nautilus_trader.model.instruments import BinaryOption
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog
from nautilus_trader.test_kit.stubs.component import TestComponentStubs

from breezy.adapters.polymarket_us.symbology import sibling_instrument_id
from breezy.domain.weather_bucket_facts import (
    CLIMATE_DAY_KEY,
    MEASURE_KEY,
    SETTLEMENT_STATION_KEY,
    STRIKE_LOWER_F_KEY,
    STRIKE_UPPER_F_KEY,
    WEATHER_FACTS_STATUS_KEY,
    WEATHER_FACTS_STATUS_KNOWN,
)
from breezy.strategy.forecast_quantile_ladder.composition import (
    build_forecast_quantile_ladder_strategies,
)
from breezy.strategy.forecast_quantile_ladder.decision_funnel import (
    DEFAULT_FLUSH_INTERVAL_SECONDS,
    FqDecisionCounts,
    FqDecisionFunnelActor,
)
from breezy.strategy.forecast_quantile_ladder.latch import QuantileLadderLatch

# ---------------------------------------------------------------------------
# FqDecisionCounts -- pure.
# ---------------------------------------------------------------------------


def test_record_counts_each_distinct_key_separately() -> None:
    counts = FqDecisionCounts()

    counts.record(station="LAX", side="yes", kind="Refuse", reason="below_margin")
    counts.record(station="LAX", side="yes", kind="Refuse", reason="below_margin")
    counts.record(station="LAX", side="no", kind="Refuse", reason="below_margin")
    counts.record(station="LAX", side="yes", kind="Take")

    rows = {
        (r["station"], r["side"], r["kind"], r["reason"]): r["count"] for r in counts.snapshot()
    }
    assert rows[("LAX", "yes", "Refuse", "below_margin")] == 2
    assert rows[("LAX", "no", "Refuse", "below_margin")] == 1
    assert rows[("LAX", "yes", "Take", "")] == 1
    assert counts.total() == 4


def test_record_line_adapts_a_shadow_decision_log_line() -> None:
    counts = FqDecisionCounts()

    counts.record_line(
        {
            "station": "MIA",
            "side": "yes",
            "kind": "NotExecutable",
            "reason": "outside_permit_window",
        }
    )

    rows = counts.snapshot()
    assert len(rows) == 1
    assert rows[0] == {
        "station": "MIA",
        "side": "yes",
        "kind": "NotExecutable",
        "reason": "outside_permit_window",
        "count": 1,
    }


def test_record_line_on_a_take_line_with_no_reason_key_uses_the_empty_string() -> None:
    counts = FqDecisionCounts()

    counts.record_line({"station": "SFO", "side": "no", "kind": "Take"})

    rows = counts.snapshot()
    assert rows[0]["reason"] == ""


def test_an_unseen_reason_string_is_counted_under_its_own_name_never_dropped() -> None:
    """FQ-S11 taxonomy-driven requirement: S10 (not merged into this
    worktree) adds the refusal reason ``opposite_side_latched`` to
    ``decision.py``. The aggregator must count it the moment it starts
    flowing through ``shadow_decision_sink``, with NO edit to this module --
    proving the vocabulary is genuinely open, not a hand-maintained enum."""
    counts = FqDecisionCounts()

    counts.record_line(
        {"station": "LAX", "side": "yes", "kind": "Refuse", "reason": "opposite_side_latched"}
    )
    counts.record_line(
        {"station": "LAX", "side": "yes", "kind": "Refuse", "reason": "opposite_side_latched"}
    )

    rows = {
        (r["station"], r["side"], r["kind"], r["reason"]): r["count"] for r in counts.snapshot()
    }
    assert rows[("LAX", "yes", "Refuse", "opposite_side_latched")] == 2


def test_snapshot_rows_carry_only_the_closed_key_set_never_a_price_or_pnl_field() -> None:
    counts = FqDecisionCounts()
    counts.record_line(
        {
            "station": "LAX",
            "side": "yes",
            "kind": "Take",
            "ev_net": 0.1,
            "p_hat": 0.2,
            "p_lower": 0.17,
            "p_upper": 0.23,
            "instrument_id": "x",
        }
    )

    row = counts.snapshot()[0]

    assert set(row) == {"station", "side", "kind", "reason", "count"}


# ---------------------------------------------------------------------------
# FqDecisionFunnelActor -- native clock timer, flush cadence.
# ---------------------------------------------------------------------------


def _build_actor(output_dir: Path, *, clock: TestClock) -> FqDecisionFunnelActor:
    actor = FqDecisionFunnelActor(output_dir=output_dir, counts=FqDecisionCounts())
    actor.register_base(
        portfolio=TestComponentStubs.portfolio(),
        msgbus=TestComponentStubs.msgbus(),
        cache=TestComponentStubs.cache(),
        clock=clock,
    )
    return actor


def _read_rows(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


_NS_PER_SECOND = 1_000_000_000
_INTERVAL_NS = DEFAULT_FLUSH_INTERVAL_SECONDS * _NS_PER_SECOND


def _fire_due_timers(clock: TestClock, to_ns: int) -> int:
    """Advance ``clock`` to the ABSOLUTE instant ``to_ns`` and run every due
    handler ORGANICALLY -- ``TestClock.advance_time`` takes a target instant,
    never a delta (``nws_observation_harness.fire_due_timers``'s own idiom)."""
    handlers = clock.advance_time(to_ns)
    for handler in handlers:
        handler.handle()
    return len(handlers)


def test_on_start_arms_a_15_minute_native_timer_and_flushes_on_each_fire(tmp_path: Path) -> None:
    start_ns = int(dt.datetime(2026, 10, 1, 0, 0, tzinfo=dt.UTC).timestamp() * _NS_PER_SECOND)
    clock = TestClock()
    clock.set_time(start_ns)
    actor = _build_actor(tmp_path, clock=clock)
    actor.start()
    actor.counts.record(station="LAX", side="yes", kind="Take")

    fired = _fire_due_timers(clock, start_ns + _INTERVAL_NS)

    assert fired == 1
    path = tmp_path / "fq_funnel_2026-10-01.jsonl"
    assert path.is_file()
    rows = _read_rows(path)
    assert len(rows) == 1
    assert rows[0]["final"] is False
    assert rows[0]["boot_day"] == "2026-10-01"
    flushed_counts = cast("list[dict[str, object]]", rows[0]["counts"])
    expected_row = {"station": "LAX", "side": "yes", "kind": "Take", "reason": "", "count": 1}
    assert expected_row in flushed_counts


def test_two_flush_ticks_append_two_rows_to_the_same_file(tmp_path: Path) -> None:
    start_ns = int(dt.datetime(2026, 10, 1, 0, 0, tzinfo=dt.UTC).timestamp() * _NS_PER_SECOND)
    clock = TestClock()
    clock.set_time(start_ns)
    actor = _build_actor(tmp_path, clock=clock)
    actor.start()

    _fire_due_timers(clock, start_ns + _INTERVAL_NS)
    _fire_due_timers(clock, start_ns + 2 * _INTERVAL_NS)

    path = tmp_path / "fq_funnel_2026-10-01.jsonl"
    rows = _read_rows(path)
    assert len(rows) == 2


def test_on_stop_writes_one_final_row_and_cancels_the_timer(tmp_path: Path) -> None:
    clock = TestClock()
    clock.set_time(int(dt.datetime(2026, 10, 1, 0, 0, tzinfo=dt.UTC).timestamp() * _NS_PER_SECOND))
    actor = _build_actor(tmp_path, clock=clock)
    actor.start()

    actor.stop()

    path = tmp_path / "fq_funnel_2026-10-01.jsonl"
    rows = _read_rows(path)
    assert len(rows) == 1
    assert rows[0]["final"] is True


def test_a_process_that_never_evaluates_a_decision_still_flushes_an_empty_row(
    tmp_path: Path,
) -> None:
    """Counts-only, never a list: an idle 15-minute window still proves the
    pipeline is alive, with an empty ``counts`` array -- never silence."""
    start_ns = int(dt.datetime(2026, 10, 1, 0, 0, tzinfo=dt.UTC).timestamp() * _NS_PER_SECOND)
    clock = TestClock()
    clock.set_time(start_ns)
    actor = _build_actor(tmp_path, clock=clock)
    actor.start()

    _fire_due_timers(clock, start_ns + _INTERVAL_NS)

    rows = _read_rows(tmp_path / "fq_funnel_2026-10-01.jsonl")
    assert rows[0]["counts"] == []


# ---------------------------------------------------------------------------
# composition.py wiring: `build_forecast_quantile_ladder_strategies`'s
# `decision_counts` wires `shadow_decision_sink` for every composed station.
# Minimal single-station D+1 catalog, same shape as
# `test_sl13c_d_plus_1_resolution.py`'s own fixtures.
# ---------------------------------------------------------------------------

_VENUE = Venue("POLYMARKET_US")
_WIRING_NOW_NS = 1_790_700_600_000_000_000  # 2026-09-29T16:50:00Z
_WIRING_BOOT_DAY = dt.date(2026, 9, 29)
_WIRING_STATION = "LAX"

_WIRING_ARTEFACT_PAYLOAD: dict[str, Any] = {
    "schema_version": 1,
    "cdf_method": "normal",
    "recalibration": "none",
    "correction_form": "none",
    "delta": 1.0,
    "kappa": 1.0,
    "emos_params_by_version": {"v1": [0.0, 0.0]},
    "emos_draws_by_version": {"v1": [[0.0, 0.0], [0.05, 0.02], [-0.05, -0.01]]},
    "emos": {"a": 0.0, "gamma": 0.0, "delta": 1.0},
    "n_min": 30,
    "sigma_d": 1.0,
    "rung_probability_bounds": {},
    "fit_status": "OK",
}


def _wiring_facts_info(*, station: str, climate_day: dt.date) -> dict[str, object]:
    return {
        WEATHER_FACTS_STATUS_KEY: WEATHER_FACTS_STATUS_KNOWN,
        SETTLEMENT_STATION_KEY: station,
        CLIMATE_DAY_KEY: climate_day.isoformat(),
        MEASURE_KEY: "high",
        STRIKE_LOWER_F_KEY: 80,
        STRIKE_UPPER_F_KEY: 81,
    }


def _wiring_yes_instrument(*, station: str, climate_day: dt.date) -> BinaryOption:
    slug = f"{station.lower()}-d{climate_day.isoformat()}-80-81"
    instrument_id = InstrumentId(Symbol(slug), _VENUE)
    increment = Price.from_str("0.01")
    size_increment = Quantity.from_str("1")
    return BinaryOption(
        instrument_id=instrument_id,
        raw_symbol=instrument_id.symbol,
        outcome="Yes",
        description=f"{station} daily high",
        asset_class=AssetClass.ALTERNATIVE,
        currency=USD,
        price_precision=increment.precision,
        price_increment=increment,
        size_precision=size_increment.precision,
        size_increment=size_increment,
        activation_ns=0,
        expiration_ns=200 * 3_600_000_000_000,
        max_quantity=None,
        min_quantity=Quantity.from_int(1),
        maker_fee=Decimal("0.06"),
        taker_fee=Decimal("0.06"),
        ts_event=0,
        ts_init=0,
        info=_wiring_facts_info(station=station, climate_day=climate_day),
    )


def _wiring_no_instrument(yes: BinaryOption) -> BinaryOption:
    no_id = sibling_instrument_id(yes.id)
    return BinaryOption(
        instrument_id=no_id,
        raw_symbol=no_id.symbol,
        outcome="No",
        description="no leg",
        asset_class=AssetClass.ALTERNATIVE,
        currency=USD,
        price_precision=yes.price_precision,
        price_increment=yes.price_increment,
        size_precision=yes.size_precision,
        size_increment=yes.size_increment,
        activation_ns=0,
        expiration_ns=yes.expiration_ns,
        max_quantity=None,
        min_quantity=Quantity.from_int(1),
        maker_fee=Decimal("0.06"),
        taker_fee=Decimal("0.06"),
        ts_event=0,
        ts_init=0,
        info=dict(yes.info),
    )


@pytest.fixture
def _wiring_catalog_root(tmp_path: Path) -> Path:
    root = tmp_path / "catalog"
    catalog = ParquetDataCatalog(str(root))
    yes = _wiring_yes_instrument(
        station=_WIRING_STATION, climate_day=_WIRING_BOOT_DAY + dt.timedelta(days=1),
    )
    catalog.write_data([yes, _wiring_no_instrument(yes)])
    return root


def _wiring_artefact_files(tmp_path: Path) -> tuple[str, str]:
    path = tmp_path / "density.json"
    raw = json.dumps(_WIRING_ARTEFACT_PAYLOAD).encode("utf-8")
    path.write_bytes(raw)
    return str(path), hashlib.sha256(raw).hexdigest()


def test_build_wires_decision_counts_as_the_shadow_decision_sink(
    _wiring_catalog_root: Path, tmp_path: Path,
) -> None:
    artefact_path, artefact_sha = _wiring_artefact_files(tmp_path)
    counts = FqDecisionCounts()

    strategies, _quantile_actor = build_forecast_quantile_ladder_strategies(
        catalog_root=_wiring_catalog_root,
        today_by_station={_WIRING_STATION: _WIRING_BOOT_DAY},
        latch=QuantileLadderLatch(),
        calibration_artefact_path=artefact_path,
        calibration_artefact_sha256=artefact_sha,
        bounds_artefact_path=artefact_path,
        bounds_artefact_sha256=artefact_sha,
        now_ns_fn=lambda: _WIRING_NOW_NS,
        decision_counts=counts,
    )

    assert len(strategies) == 1
    strategy = strategies[0]
    sink = strategy._shadow_decision_sink
    assert sink is not None
    # Bound methods compare unequal by identity on each access; assert it is
    # THIS aggregator's own `record_line`, by `__self__`/`__func__`, then
    # prove it actually feeds `counts` end to end.
    assert getattr(sink, "__self__", None) is counts
    assert getattr(sink, "__func__", None) is type(counts).record_line
    # Already proven identical to `counts.record_line` above; call it through
    # `counts` itself (same bound method) to prove it actually feeds `counts`.
    counts.record_line({"station": "LAX", "side": "yes", "kind": "Take"})
    assert counts.total() == 1


def test_build_with_no_decision_counts_leaves_the_sink_none(
    _wiring_catalog_root: Path, tmp_path: Path,
) -> None:
    artefact_path, artefact_sha = _wiring_artefact_files(tmp_path)

    strategies, _quantile_actor = build_forecast_quantile_ladder_strategies(
        catalog_root=_wiring_catalog_root,
        today_by_station={_WIRING_STATION: _WIRING_BOOT_DAY},
        latch=QuantileLadderLatch(),
        calibration_artefact_path=artefact_path,
        calibration_artefact_sha256=artefact_sha,
        bounds_artefact_path=artefact_path,
        bounds_artefact_sha256=artefact_sha,
        now_ns_fn=lambda: _WIRING_NOW_NS,
    )

    assert strategies[0]._shadow_decision_sink is None
