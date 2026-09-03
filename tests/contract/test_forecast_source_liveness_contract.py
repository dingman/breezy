"""T-7: pin the `ForecastSource` liveness contract that was only ever prose.

``breezy.strategy.weather_common.forecast_source`` requires an implementation
to return a ``ForecastSnapshot.horizon_hours`` that is **already the live
hours-remaining-to-settlement as of the ``now`` it was called with** -- not a
value frozen at issuance. ``ForecastSource`` is a bare ``Protocol``: a
``Protocol`` can constrain a signature, never a value, so nothing in the type
system or the test suite held that requirement. It was stated in three module
docstrings and enforced nowhere
(``docs/core/findings/BLIND_RISK_VIEWS_2026-09-02.md`` s T-7).

The property pinned here is the one an implementation can only satisfy by
recomputing: calling ``snapshot(now=t)`` and ``snapshot(now=t + d)`` on the
SAME underlying publication must return horizons that differ by exactly ``d``
hours. A frozen horizon returns the same number twice and fails.

WHICH IMPLEMENTATIONS THIS COVERS, AND WHY NOT THE OTHERS
---------------------------------------------------------
This guard targets ``_SequenceForecastSource`` in
``scripts/analysis/run_weather_strategy_backtests.py`` -- the source that feeds
every measured backtest, and the only non-test ``ForecastSource`` in the repo.
It is the implementation whose horizon reaches the probability model, the risk
manager's ``hours_to_settlement``, and therefore the ROI numbers strategy
decisions are made from.

The other in-repo implementations are DELIBERATELY FROZEN test doubles
(``_SyntheticForecastSource`` and ``_ConstantForecastSource`` in
``tests/unit`` / ``tests/integration``, which say so in their own docstrings:
one holds a constant "for this short test run", the other returns 24.0 and
ignores ``now`` entirely). Forcing liveness on a double would be pinning a
fixture, not a contract -- their whole purpose is to hold one input still
while something else is measured. This guard therefore does NOT sweep every
class with a ``snapshot`` method; it names the production/analysis source
explicitly, so adding a new frozen double stays legal while a production
source that stops recomputing does not.

STATUS: this is a PIN, not a defect test. ``_SequenceForecastSource`` already
conforms (``hours_from_now_until(now, deadline)``, recomputed per call), so
this passes on the tree that introduced it. That is the point: T-7 is that
the property was unpinned, not that the shipped source violated it.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

from breezy.strategy.weather_common.forecast_source import ForecastSource

STATION = "NYC"
DEADLINE = dt.datetime(2026, 8, 31, 5, 0, tzinfo=dt.UTC)
PUBLISHED_AT = dt.datetime(2026, 8, 30, 12, 0, tzinfo=dt.UTC)
FIRST_READ_AT = dt.datetime(2026, 8, 30, 16, 0, tzinfo=dt.UTC)
#: The elapsed interval between the two reads of the SAME publication.
ELAPSED_HOURS = 5.5


def _load_runner_module() -> ModuleType:
    """Load the analysis runner by path -- ``scripts/`` carries no package init.

    Same loader pattern as ``tests/unit/test_run_weather_strategy_backtests.py``.
    """
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


def _production_source() -> ForecastSource:
    """The analysis/backtest ``ForecastSource``, with ONE publication held.

    One publication is deliberate: it removes the only other reason two reads
    could differ, so any horizon difference is the recomputation and nothing
    else.
    """
    # Annotated as `ForecastSource`: the Protocol is structural, so this is
    # itself a (static) assertion that the analysis source still satisfies the
    # seam these tests are pinning.
    source: ForecastSource = runner._SequenceForecastSource(
        publications_by_station={STATION: ((PUBLISHED_AT, 88.0),)},
        settlement_deadline_by_station={STATION: DEADLINE},
    )
    return source


def test_horizon_hours_is_recomputed_from_the_now_it_was_called_with() -> None:
    source = _production_source()
    climate_day = runner.CLIMATE_DAY

    early = source.snapshot(station=STATION, climate_day=climate_day, now=FIRST_READ_AT)
    later = source.snapshot(
        station=STATION,
        climate_day=climate_day,
        now=FIRST_READ_AT + dt.timedelta(hours=ELAPSED_HOURS),
    )

    assert early is not None
    assert later is not None
    # Same publication both times -- so nothing about the FORECAST changed.
    assert early.published_at == later.published_at == PUBLISHED_AT
    assert early.expected_high_f == later.expected_high_f
    # ... and the horizon still moved, by exactly the elapsed time.
    assert early.horizon_hours - later.horizon_hours == pytest.approx(ELAPSED_HOURS)


def test_horizon_hours_is_the_live_distance_to_the_settlement_deadline() -> None:
    """Not merely moving: moving to the RIGHT value, against the real deadline.

    A source that decremented by elapsed time from an arbitrary origin would
    satisfy the delta property above while still reporting a horizon that is
    not hours-to-settlement.
    """
    source = _production_source()

    snapshot = source.snapshot(
        station=STATION,
        climate_day=runner.CLIMATE_DAY,
        now=FIRST_READ_AT,
    )

    assert snapshot is not None
    expected = (DEADLINE - FIRST_READ_AT).total_seconds() / 3600.0
    assert snapshot.horizon_hours == pytest.approx(expected)
    # And emphatically NOT frozen at issuance: that would be 17.0 here.
    frozen_at_issuance = (DEADLINE - PUBLISHED_AT).total_seconds() / 3600.0
    assert snapshot.horizon_hours != pytest.approx(frozen_at_issuance)


def test_horizon_hours_goes_negative_past_the_deadline_rather_than_clamping() -> None:
    """Liveness includes the far side of the deadline.

    A source that floored the horizon at zero would report "settlement is
    exactly now" forever, which reads as inside every time gate rather than
    past it.
    """
    source = _production_source()

    snapshot = source.snapshot(
        station=STATION,
        climate_day=runner.CLIMATE_DAY,
        now=DEADLINE + dt.timedelta(hours=2),
    )

    assert snapshot is not None
    assert snapshot.horizon_hours == pytest.approx(-2.0)
