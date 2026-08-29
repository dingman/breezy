"""Construction-time guards for the two ported weather strategies.

TWO defects are pinned here.

1. ``Actor.config`` IS NOT WRITABLE. Both operator bundles ended their
   ``__init__`` with ``self.config: <SomeConfig> = config`` after
   ``super().__init__(config)``. ``Actor.config`` is a read-only Cython
   ``getset_descriptor``, so that line raises::

       AttributeError: attribute 'config' of
       'nautilus_trader.common.actor.Actor' objects is not writable

   The base class already stores it. This is a HARD construction crash --
   neither strategy could ever be instantiated -- and it is pinned by simply
   constructing them.

2. ``ForecastSource`` is REQUIRED. Breezy ingests no forecast data, so a
   forecast can only arrive through the injected seam
   (``breezy.strategy.weather_common.forecast_source``). Omitting it is a
   ``TypeError``; passing ``None`` is refused with a named error rather than
   accepted and silently never trading. Same contract the first bundle's
   integration established.
"""

from __future__ import annotations

import datetime as dt

import pytest
from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue

from breezy.strategy.calibration_mean_reversion import (
    CalibrationMeanReversionConfig,
    CalibrationMeanReversionStrategy,
)
from breezy.strategy.forecast_revision import ForecastRevisionConfig, ForecastRevisionStrategy
from breezy.strategy.weather_common.forecast_source import MissingForecastSourceError
from breezy.strategy.weather_common.models import ForecastSnapshot

INSTRUMENT_ID = InstrumentId(Symbol("nyc-ge80"), Venue("POLYMARKET_US"))


class _StubForecastSource:
    """Minimal `ForecastSource`: never fabricates from a settled observation."""

    def snapshot(
        self,
        *,
        station: str,
        climate_day: dt.date,
        now: dt.datetime,
    ) -> ForecastSnapshot | None:
        return None


CASES = (
    (CalibrationMeanReversionStrategy, CalibrationMeanReversionConfig),
    (ForecastRevisionStrategy, ForecastRevisionConfig),
)
IDS = ("calibration_mean_reversion", "forecast_revision")


@pytest.mark.parametrize(("strategy_cls", "config_cls"), CASES, ids=IDS)
def test_strategy_constructs_without_touching_the_readonly_config_attribute(
    strategy_cls: type,
    config_cls: type,
) -> None:
    strategy = strategy_cls(config_cls(instrument_ids=(INSTRUMENT_ID,)), _StubForecastSource())
    assert strategy.config.instrument_ids == (INSTRUMENT_ID,)


@pytest.mark.parametrize(("strategy_cls", "config_cls"), CASES, ids=IDS)
def test_native_config_attribute_is_still_not_writable(
    strategy_cls: type,
    config_cls: type,
) -> None:
    """Non-vacuity: the crash the bundles hit is real and still present."""
    strategy = strategy_cls(config_cls(instrument_ids=(INSTRUMENT_ID,)), _StubForecastSource())
    with pytest.raises(AttributeError, match="not writable"):
        strategy.config = config_cls(instrument_ids=(INSTRUMENT_ID,))


@pytest.mark.parametrize(("strategy_cls", "config_cls"), CASES, ids=IDS)
def test_omitting_the_forecast_source_is_a_type_error(
    strategy_cls: type,
    config_cls: type,
) -> None:
    with pytest.raises(TypeError):
        strategy_cls(config_cls(instrument_ids=(INSTRUMENT_ID,)))


@pytest.mark.parametrize(("strategy_cls", "config_cls"), CASES, ids=IDS)
def test_passing_none_as_the_forecast_source_is_refused_loudly(
    strategy_cls: type,
    config_cls: type,
) -> None:
    with pytest.raises(MissingForecastSourceError):
        strategy_cls(config_cls(instrument_ids=(INSTRUMENT_ID,)), None)
