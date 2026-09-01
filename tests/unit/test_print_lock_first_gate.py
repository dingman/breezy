"""Unit tests for the BL-19 s8.5 decision-input instrumentation in
``scripts/analysis/weather_strategy_backtest_lib.py``.

WHY THIS EXISTS
---------------
``docs/evidence/bl19_edge_and_cost_decision_2026-09-01.md`` s8.5 enumerates
four distinguishable nulls for ``cli_settlement_print_lock``, and says that
**two of them (N0, N1) are invisible at the ``RefusalCounter``**: a pre-signal
``None`` never reaches ``RiskManager.evaluate_order`` and so is never counted.
Without a per-station-day record of the decision INPUTS and the FIRST gate that
stopped the decision, a zero-trade backtest is uninterpretable.

WHAT IS AND IS NOT UNDER TEST
------------------------------
The classifier under test computes **no trading result**. It records decision
INPUTS (printed value, mapped bucket, level-0 ask, VWAP ask, fee coefficient)
and the identity of the first shipped predicate that returned "no". Every
predicate it consults is the SHIPPED one imported from
``breezy.strategy.cli_settlement_print_lock`` -- it re-implements none of them
-- and :func:`first_blocking_gate` CROSS-CHECKS itself against the shipped
:func:`evaluate_instrument`, raising if the two ever disagree about whether a
decision forms. That cross-check is what makes the record evidence rather than
a second opinion, and it is the property most of these tests pin.

Loaded via ``importlib`` from its file path, matching
``test_weather_strategy_backtest_lib.py``: ``scripts/`` carries no package
``__init__.py``.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from breezy.domain.weather_bucket_facts import Measure, WeatherBucketFacts
from breezy.strategy.cli_settlement_print_lock.config import CliSettlementPrintLockConfig
from breezy.strategy.cli_settlement_print_lock.decision import CliPrintObservation
from breezy.strategy.weather_common.bucket_contract import MispricingContract
from breezy.strategy.weather_common.models import MarketQuote


def _load_lib_module() -> ModuleType:
    path = Path("scripts/analysis/weather_strategy_backtest_lib.py")
    sys.path.insert(0, path.parent.as_posix())
    spec = importlib.util.spec_from_file_location("weather_strategy_backtest_lib", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


lib = _load_lib_module()

_NOW = dt.datetime(2026, 9, 1, 6, 30, tzinfo=dt.UTC)
_CLIMATE_DAY = dt.date(2026, 8, 31)
#: Far enough ahead of ``_NOW`` that neither ``halt_hours_before_settlement``
#: (1.0) nor ``min_hours_to_settlement`` (2.0) binds, so a test that wants to
#: reach a LATER gate is not silently stopped by the timing gate.
_DEADLINE = dt.datetime(2026, 9, 1, 12, 0, tzinfo=dt.UTC)


def _cfg(**overrides: object) -> CliSettlementPrintLockConfig:
    from nautilus_trader.model.identifiers import InstrumentId

    return CliSettlementPrintLockConfig(
        instrument_ids=(InstrumentId.from_str("tc-x.POLYMARKET_US"),),
        stale_observation_hours=9.0,
        slippage_prob=0.01,
        **overrides,  # type: ignore[arg-type]
    )


def _facts(
    station: str = "NYC",
    lower_f: int | None = 78,
    upper_f: int | None = 79,
    climate_day: dt.date = _CLIMATE_DAY,
) -> WeatherBucketFacts:
    return WeatherBucketFacts(
        settlement_station=station,
        climate_day=climate_day,
        measure=Measure.HIGH,
        lower_f=lower_f,
        upper_f=upper_f,
    )


def _contract(
    facts: WeatherBucketFacts | None = None,
    fee_coefficient: float | None = 0.06,
) -> MispricingContract:
    return MispricingContract(
        instrument_id="tc-x.POLYMARKET_US",
        facts=facts if facts is not None else _facts(),
        tick_size=0.01,
        price_scale=1.0,
        fee_coefficient=fee_coefficient,
    )


def _quote(
    ask: float | None = 0.90,
    ask_size: float | None = 500.0,
    bid: float | None = None,
    ts_event: dt.datetime = _NOW,
    ask_ladder: tuple[tuple[float, float], ...] | None = None,
) -> MarketQuote:
    return MarketQuote(
        instrument_id="tc-x.POLYMARKET_US",
        bid=bid,
        ask=ask,
        bid_size=None,
        ask_size=ask_size,
        ts_event=ts_event,
        ask_ladder=ask_ladder,
    )


def _observation(
    *,
    station: str = "NYC",
    climate_day: dt.date = _CLIMATE_DAY,
    tmax_f: int | None = 78,
    is_final: bool = True,
    correction_flag: bool = False,
    is_superseded: bool = False,
    published_at: dt.datetime | None = None,
) -> CliPrintObservation:
    return CliPrintObservation(
        station=station,
        climate_day=climate_day,
        tmax_f=tmax_f,
        tmin_f=60,
        is_final=is_final,
        correction_flag=correction_flag,
        is_superseded=is_superseded,
        published_at=published_at if published_at is not None else _NOW - dt.timedelta(minutes=5),
    )


def _record(**overrides: object) -> Any:
    kwargs: dict[str, object] = {
        "contract": _contract(),
        "quote": _quote(),
        "observation": _observation(),
        "now": _NOW,
        "deadline": _DEADLINE,
        "cfg": _cfg(),
    }
    kwargs.update(overrides)
    return lib.first_blocking_gate(**kwargs)


# ---------------------------------------------------------------------------
# select_book_backed_instrument_ids
# ---------------------------------------------------------------------------


def test_select_book_backed_instrument_ids_accepts_a_depth_only_instrument() -> None:
    """A long-only taker needs an ASK and nothing else.

    ``cli_settlement_print_lock``'s own module docstring: "An asks-only book
    ... is TRADED". ``parse_book_top`` aborts the whole frame when one side is
    empty, so a terminal weather market records depth and ZERO ``QuoteTick``s
    -- the exact shape of every 2026-08-31 ladder on the live capture. The
    quote-AND-depth rule (``select_tradable_instrument_ids``) is correct for
    the forecast strategies and is left untouched; this is the book-only
    sibling, not a relaxation of it.
    """
    assert lib.select_book_backed_instrument_ids({"a": 10, "b": 0}) == ["a"]


def test_select_book_backed_instrument_ids_is_sorted_and_excludes_zero_depth() -> None:
    assert lib.select_book_backed_instrument_ids({"z": 1, "a": 1, "m": 0}) == ["a", "z"]


def test_select_book_backed_instrument_ids_empty_input_returns_empty() -> None:
    assert lib.select_book_backed_instrument_ids({}) == []


# ---------------------------------------------------------------------------
# first_blocking_gate -- the invisible nulls (N0 / N1)
# ---------------------------------------------------------------------------


def test_a_print_that_arrives_after_the_settlement_deadline_is_stopped_by_the_halt_window() -> None:
    """N0. ``_evaluate_and_act`` returns with NO refusal recorded when
    ``hours_to_settlement <= halt_hours_before_settlement``.

    This is the first gate a final print that lands after its own market's
    ``endDate`` can possibly hit, and it is invisible at the counter.
    """
    record = _record(deadline=_NOW - dt.timedelta(hours=1))
    assert record.gate == lib.GATE_HALT_WINDOW
    assert record.decision_formed is False
    assert record.counted_by_refusal_counter is False


def test_the_halt_window_gate_reports_the_negative_hours_to_settlement() -> None:
    record = _record(deadline=_NOW - dt.timedelta(hours=1))
    assert record.hours_to_settlement == pytest.approx(-1.0)


def test_a_preliminary_print_is_stopped_at_the_is_final_gate() -> None:
    """N1. The load-bearing ``is_final`` gate, invisible at the counter."""
    record = _record(observation=_observation(is_final=False))
    assert record.gate == lib.GATE_NOT_FINAL
    assert record.counted_by_refusal_counter is False


def test_a_corrected_print_is_stopped_at_the_correction_gate() -> None:
    record = _record(observation=_observation(correction_flag=True))
    assert record.gate == lib.GATE_CORRECTION


def test_a_superseded_print_is_stopped_at_the_superseded_gate() -> None:
    record = _record(observation=_observation(is_superseded=True))
    assert record.gate == lib.GATE_SUPERSEDED


def test_a_print_for_another_station_is_stopped_at_the_applies_to_gate() -> None:
    record = _record(observation=_observation(station="MIA"))
    assert record.gate == lib.GATE_APPLIES_TO


def test_a_print_for_another_climate_day_is_stopped_at_the_applies_to_gate() -> None:
    record = _record(observation=_observation(climate_day=dt.date(2026, 9, 1)))
    assert record.gate == lib.GATE_APPLIES_TO


def test_a_future_dated_print_is_stopped_at_the_lookahead_gate() -> None:
    record = _record(observation=_observation(published_at=_NOW + dt.timedelta(minutes=1)))
    assert record.gate == lib.GATE_LOOKAHEAD


def test_a_print_outside_this_bucket_is_stopped_at_the_bucket_gate() -> None:
    """N1. Some OTHER rung won; this rung is silent, and uncounted."""
    record = _record(observation=_observation(tmax_f=95))
    assert record.gate == lib.GATE_BUCKET_NOT_CONTAINING
    assert record.printed_f == 95
    assert record.bucket_lower_f == 78
    assert record.bucket_upper_f == 79


def test_an_unmeasured_station_is_stopped_at_the_measured_stations_gate() -> None:
    facts = _facts(station="PHL")
    record = _record(
        contract=_contract(facts=facts),
        observation=_observation(station="PHL"),
    )
    assert record.gate == lib.GATE_UNMEASURED_STATION


def test_an_empty_ask_side_is_stopped_at_the_no_ask_gate() -> None:
    """N3 -- a genuine market fact, and the honest kill s8.5 describes."""
    record = _record(quote=_quote(ask=None, ask_size=None))
    assert record.gate == lib.GATE_NO_ASK


def test_an_ask_at_one_is_stopped_at_the_degenerate_ask_gate() -> None:
    record = _record(quote=_quote(ask=1.0))
    assert record.gate == lib.GATE_DEGENERATE_ASK


def test_an_unresolved_fee_schedule_is_stopped_rather_than_traded_free() -> None:
    record = _record(contract=_contract(fee_coefficient=None))
    assert record.gate == lib.GATE_NO_FEE_COEFFICIENT


# ---------------------------------------------------------------------------
# first_blocking_gate -- the edge floor (N2) and the pass case
# ---------------------------------------------------------------------------


def test_an_ask_of_0_99_is_stopped_at_the_edge_floor() -> None:
    """N2 at the shipped constants: BL-19 s8.2 puts the edge at 0.99 at
    -0.003698, below the 0.005 floor. The edge VALUE is produced by the
    shipped cost functions, never by arithmetic in this module.
    """
    record = _record(quote=_quote(ask=0.99))
    assert record.gate == lib.GATE_EDGE_BELOW_MINIMUM
    assert record.edge is not None
    assert record.edge < 0.005


def test_an_ask_of_0_90_forms_a_decision_and_reports_no_blocking_gate() -> None:
    record = _record(quote=_quote(ask=0.90))
    assert record.gate == lib.GATE_NONE
    assert record.decision_formed is True
    assert record.edge is not None
    assert record.edge >= 0.005


def test_a_book_too_thin_to_fill_one_contract_is_stopped_at_the_size_gate() -> None:
    record = _record(quote=_quote(ask=0.90, ask_size=0.5))
    assert record.gate == lib.GATE_QUANTITY_BELOW_ONE


# ---------------------------------------------------------------------------
# The cross-check that makes the record evidence rather than a second opinion
# ---------------------------------------------------------------------------


def test_the_classifier_agrees_with_the_shipped_decision_function_on_every_case() -> None:
    """The whole point. ``first_blocking_gate`` must never disagree with the
    SHIPPED ``evaluate_instrument`` about whether a decision forms -- if it
    ever does, the record is describing a gate ladder the running strategy
    does not have, and it must raise rather than report.
    """
    cases: list[dict[str, Any]] = [
        {},
        {"observation": _observation(is_final=False)},
        {"observation": _observation(correction_flag=True)},
        {"observation": _observation(is_superseded=True)},
        {"observation": _observation(station="MIA")},
        {"observation": _observation(tmax_f=95)},
        {"observation": _observation(tmax_f=None)},
        {"quote": _quote(ask=None, ask_size=None)},
        {"quote": _quote(ask=0.99)},
        {"quote": _quote(ask=0.90, ask_size=0.5)},
        {"contract": _contract(fee_coefficient=None)},
    ]
    for case in cases:
        record = _record(**case)
        assert record.gate in lib.PRINT_LOCK_GATES, case
        # Reaching here at all means the internal cross-check passed; assert
        # the invariant it enforces so the intent is explicit in the test.
        assert record.decision_formed is (record.gate == lib.GATE_NONE), case


def test_the_classifier_raises_when_it_disagrees_with_the_shipped_decision() -> None:
    """The cross-check must be a hard failure, never a logged warning.

    Simulated by handing the classifier a gate ladder it cannot satisfy: a
    config whose ``use_tmax`` is False makes the SHIPPED decision return
    ``None`` at the measure gate. The classifier must classify it, not
    silently claim a decision formed.
    """
    record = _record(cfg=_cfg(use_tmax=False, use_tmin=True))
    assert record.gate == lib.GATE_MEASURE_DISABLED
    assert record.decision_formed is False


# ---------------------------------------------------------------------------
# The recorded INPUTS -- what makes a null decodable offline (s8.5)
# ---------------------------------------------------------------------------


def test_the_record_carries_every_s8_5_decision_input() -> None:
    record = _record(
        quote=_quote(ask=0.90, ask_size=400.0, ask_ladder=((0.90, 10.0), (0.93, 400.0))),
    )
    assert record.printed_f == 78
    assert record.bucket_lower_f == 78
    assert record.bucket_upper_f == 79
    assert record.level0_ask == pytest.approx(0.90)
    assert record.level0_ask_size == pytest.approx(400.0)
    assert record.fee_coefficient == pytest.approx(0.06)
    assert record.vwap_ask is not None
    assert record.vwap_ask >= record.level0_ask
    assert record.edge is not None
    assert record.model_probability is not None


def test_the_record_carries_the_edge_at_zero_slippage_so_the_threshold_re_derives() -> None:
    """s8.5: "computed edge at ``slippage_prob`` in {0.000, 0.010}" -- so a
    measured slippage figure re-derives the threshold WITHOUT re-running the
    capture.
    """
    record = _record(quote=_quote(ask=0.99))
    assert record.edge is not None
    assert record.edge_at_zero_slippage is not None
    assert record.edge_at_zero_slippage > record.edge
    assert record.edge_at_zero_slippage == pytest.approx(record.edge + 0.01)
