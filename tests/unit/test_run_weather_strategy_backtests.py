"""Unit tests for the structural (non-harness) parts of
``scripts/analysis/run_weather_strategy_backtests.py``.

Covers the invariant behind keeping BOTH the ``naive`` and ``realistic``
conditions (see the module docstring's "WHY BOTH CONDITIONS ARE KEPT,
DELIBERATELY" section): they are byte-identical on
``orders_submitted``/``fills``/``ending_balance_usd`` for
``calibration_mean_reversion``/``forecast_revision``, but differ materially
in REFUSAL signal once ``RunResult.refusal_counts``/``status`` exist --
``naive`` never forms a signal to refuse, while ``realistic`` forms one and
gets it refused as ``shorts_disabled``. A prior version of this test file
asserted the two conditions had been collapsed to one; that assertion
encoded a decision later reversed once this refusal-signal difference was
observed (see git history) and has been removed.

These tests exercise only pure/structural surface (the ``CONDITIONS`` tuple
and ``_forecast_sources_and_overrides``'s key/value shape); they never touch
the catalog, the harness, or Nautilus engine construction, so they stay fast
and hermetic like ``test_weather_strategy_backtest_lib.py``.

Loaded via ``importlib`` from its file path, matching the existing pattern in
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


def _load_runner_module() -> ModuleType:
    path = Path("scripts/analysis/run_weather_strategy_backtests.py")
    sys.path.insert(0, path.parent.as_posix())
    spec = importlib.util.spec_from_file_location("run_weather_strategy_backtests", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


runner = _load_runner_module()


# ---------------------------------------------------------------------------
# CONDITIONS
# ---------------------------------------------------------------------------


def test_conditions_carries_both_naive_and_realistic() -> None:
    # Both conditions are retained deliberately -- see the module docstring's
    # "WHY BOTH CONDITIONS ARE KEPT, DELIBERATELY" section. They look
    # redundant on orders/fills/PnL alone but are not: they differ in
    # refusal signal (below).
    assert runner.CONDITIONS == (runner.CONDITION_NAIVE, runner.CONDITION_REALISTIC)


# ---------------------------------------------------------------------------
# _forecast_sources_and_overrides
# ---------------------------------------------------------------------------


def test_forecast_sources_and_overrides_has_one_key_per_condition_and_strategy_kind() -> None:
    tape_start_dt = dt.datetime(2026, 8, 30, 16, 5, tzinfo=dt.UTC)
    settlement_deadline_by_station = {
        "NYC": dt.datetime(2026, 8, 31, 5, 0, tzinfo=dt.UTC),
        "MIA": dt.datetime(2026, 8, 31, 5, 0, tzinfo=dt.UTC),
    }

    sources, overrides = runner._forecast_sources_and_overrides(
        tape_start_dt=tape_start_dt,
        settlement_deadline_by_station=settlement_deadline_by_station,
    )

    expected_keys = {
        f"{condition}:{kind}"
        for condition in runner.CONDITIONS
        for kind in runner.STRATEGY_KINDS
    }
    assert set(sources) == expected_keys
    assert set(overrides) == expected_keys


def test_realistic_published_at_differs_from_naive_published_at() -> None:
    # The one input `realistic` moves relative to `naive`: `published_at`,
    # REALISTIC_PUBLISHED_AT_OFFSET_HOURS earlier than the tape. This is the
    # timing shift that (together with each strategy's own
    # allow_short=False default) produces the differing refusal signal
    # documented in the module docstring.
    tape_start_dt = dt.datetime(2026, 8, 30, 16, 5, tzinfo=dt.UTC)
    settlement_deadline_by_station = {
        "NYC": dt.datetime(2026, 8, 31, 5, 0, tzinfo=dt.UTC),
        "MIA": dt.datetime(2026, 8, 31, 5, 0, tzinfo=dt.UTC),
    }

    sources, _overrides = runner._forecast_sources_and_overrides(
        tape_start_dt=tape_start_dt,
        settlement_deadline_by_station=settlement_deadline_by_station,
    )

    naive_source = sources[f"{runner.CONDITION_NAIVE}:calibration_mean_reversion"]
    realistic_source = sources[f"{runner.CONDITION_REALISTIC}:calibration_mean_reversion"]
    naive_published_at = naive_source.publications_by_station["NYC"][0][0]
    realistic_published_at = realistic_source.publications_by_station["NYC"][0][0]

    assert realistic_published_at != naive_published_at
    assert realistic_published_at == tape_start_dt - dt.timedelta(
        hours=runner.REALISTIC_PUBLISHED_AT_OFFSET_HOURS,
    )


def test_derive_completion_status_differs_between_conditions_for_a_gagged_strategy() -> None:
    # The real invariant worth protecting: the two conditions are NOT
    # redundant once refusal signal is in view. A strategy that never forms
    # a signal under `naive` (0 orders, 0 refusals -> COMPLETED) can form one
    # under `realistic` that gets wholly refused (0 orders, refusals>0 ->
    # COMPLETED_ALL_REFUSED). This models exactly the
    # calibration_mean_reversion/forecast_revision primary_real_preliminary
    # evidence cited in the module docstring, without touching the harness.
    naive_status = runner.derive_completion_status(orders_submitted=0, refusal_counts={})
    realistic_status = runner.derive_completion_status(
        orders_submitted=0, refusal_counts={"shorts_disabled": 2},
    )

    assert naive_status != realistic_status
    assert naive_status == "COMPLETED"
    assert realistic_status == "COMPLETED_ALL_REFUSED"


# ---------------------------------------------------------------------------
# BL-25 D3 -- return on CAPITAL DEPLOYED, beside return on configured balance
#
# `STARTING_BALANCE_USD = 10_000` is a harness setting, not capital at risk.
# A -$5.41 result reported against it reads -0.054%; against the ~$24.53 the
# strategy's own cost-basis anchor actually deployed it is roughly -20%.
# Return-on-configured-balance is not a return, so the honest denominator is
# reported BESIDE it (never instead of it) and `starting_balance_usd` is
# emitted per row so a reader can always reconstruct either one.
# ---------------------------------------------------------------------------


def _result(
    *,
    fills: list[Any] | None = None,
    positions: list[Any] | None = None,
    starting_balance_usd: float = 10_000.0,
) -> Any:
    return runner.RunResult(
        condition=runner.CONDITION_REALISTIC,
        strategy="cli_settlement_print_lock",
        scenario="primary_real_preliminary",
        provenance_by_station={},
        observed_by_station={},
        status=runner.STATUS_COMPLETED,
        refusal_type=None,
        refusal_message=None,
        orders_submitted=1,
        fills=fills or [],
        positions=positions or [],
        ending_balance_usd=starting_balance_usd,
        starting_balance_usd=starting_balance_usd,
    )


def _fill(side: str, quantity: float, avg_price: float) -> Any:
    return runner.FillSummary(side=side, quantity=quantity, avg_price=avg_price)


def _position(realized_pnl: float | None) -> Any:
    return runner.PositionSummary(
        instrument_id="KNYC-80-84.SIM",
        is_closed=True,
        avg_px_open=0.98,
        avg_px_close=0.0,
        realized_pnl=realized_pnl,
    )


def test_every_result_row_carries_the_starting_balance_it_was_measured_against() -> None:
    row = _result().to_json()

    assert row["starting_balance_usd"] == 10_000.0


def test_a_row_reports_both_denominators_unambiguously_labelled() -> None:
    result = _result(
        fills=[_fill("BUY", 25.0, 0.98)],
        positions=[_position(-5.41)],
    )

    row = result.to_json()

    assert row["realized_pnl_usd"] == pytest.approx(-5.41)
    assert row["capital_deployed_usd"] == pytest.approx(24.50)
    assert row["return_on_starting_balance_pct"] == pytest.approx(-0.0541)
    assert row["return_on_capital_deployed_pct"] == pytest.approx(-22.081632, abs=1e-6)


def test_the_existing_configured_balance_metric_is_kept_not_replaced() -> None:
    """The old figure stays on the record; the honest one is added beside it."""
    row = _result(
        fills=[_fill("BUY", 25.0, 0.98)],
        positions=[_position(-5.41)],
    ).to_json()

    assert "ending_balance_usd" in row
    assert "starting_balance_usd" in row
    assert "return_on_starting_balance_pct" in row
    assert "return_on_capital_deployed_pct" in row


def test_capital_deployed_is_the_buy_side_cost_basis_not_the_configured_balance() -> None:
    result = _result(
        fills=[_fill("BUY", 10.0, 0.50), _fill("BUY", 5.0, 0.60), _fill("SELL", 15.0, 0.20)],
        positions=[_position(-2.0)],
    )

    # 10 * 0.50 + 5 * 0.60 -- the cash actually put at risk. A SELL returns
    # cash and is not additional capital deployed.
    assert result.capital_deployed_usd == pytest.approx(8.0)
    assert result.capital_deployed_usd != result.starting_balance_usd


def test_a_run_that_never_deployed_capital_reports_no_deployed_return() -> None:
    """None, never a zero-division and never a fabricated 0%."""
    result = _result(fills=[], positions=[])

    assert result.capital_deployed_usd == 0.0
    assert result.return_on_capital_deployed_pct is None
    assert result.to_json()["return_on_capital_deployed_pct"] is None


def test_the_summary_table_prints_both_returns() -> None:
    header_and_rows = runner._summary_lines(
        [_result(fills=[_fill("BUY", 25.0, 0.98)], positions=[_position(-5.41)])],
    )
    text = "\n".join(header_and_rows)

    assert "ret_bal%" in text
    assert "ret_cap%" in text
    assert "-22.08" in text
    assert "-0.05" in text
