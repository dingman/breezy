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
