"""Unit tests for the structural (non-harness) parts of
``scripts/analysis/run_weather_strategy_backtests.py``.

Covers BL-4: the runner is collapsed to a single condition (``naive``) because
the two-condition design never produced a behavioural difference -- see the
module's own docstring. These tests exercise only pure/structural surface
(the ``CONDITIONS`` tuple and ``_forecast_sources_and_overrides``'s key/value
shape); they never touch the catalog, the harness, or Nautilus engine
construction, so they stay fast and hermetic like
``test_weather_strategy_backtest_lib.py``.

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


def test_conditions_is_collapsed_to_a_single_naive_condition() -> None:
    # BL-4: naive/realistic never produced a behavioural difference (all 18
    # pairs were byte-identical), so only one condition remains.
    assert runner.CONDITIONS == (runner.CONDITION_NAIVE,)


# ---------------------------------------------------------------------------
# _forecast_sources_and_overrides
# ---------------------------------------------------------------------------


def test_forecast_sources_and_overrides_has_exactly_one_key_per_strategy_kind() -> None:
    tape_start_dt = dt.datetime(2026, 8, 30, 16, 5, tzinfo=dt.UTC)
    settlement_deadline_by_station = {
        "NYC": dt.datetime(2026, 8, 31, 5, 0, tzinfo=dt.UTC),
        "MIA": dt.datetime(2026, 8, 31, 5, 0, tzinfo=dt.UTC),
    }

    sources, overrides = runner._forecast_sources_and_overrides(
        tape_start_dt=tape_start_dt,
        settlement_deadline_by_station=settlement_deadline_by_station,
    )

    expected_keys = {f"{runner.CONDITION_NAIVE}:{kind}" for kind in runner.STRATEGY_KINDS}
    assert set(sources) == expected_keys
    assert set(overrides) == expected_keys


def test_forecast_sources_and_overrides_never_sets_a_config_override() -> None:
    # BINDING CONSTRAINT: never set allow_short=True anywhere, and no config
    # default may be edited to fabricate a behavioural difference between
    # conditions -- the collapse must not smuggle an override back in.
    tape_start_dt = dt.datetime(2026, 8, 30, 16, 5, tzinfo=dt.UTC)
    settlement_deadline_by_station = {
        "NYC": dt.datetime(2026, 8, 31, 5, 0, tzinfo=dt.UTC),
        "MIA": dt.datetime(2026, 8, 31, 5, 0, tzinfo=dt.UTC),
    }

    _sources, overrides = runner._forecast_sources_and_overrides(
        tape_start_dt=tape_start_dt,
        settlement_deadline_by_station=settlement_deadline_by_station,
    )

    assert all(override == {} for override in overrides.values())
