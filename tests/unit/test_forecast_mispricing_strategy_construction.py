"""Construction-time guards for `ForecastMispricingStrategy`.

The load-bearing property under test: Breezy ingests no forecast data, so a
`ForecastSource` is a REQUIRED constructor argument with no default anywhere
in the call chain. Omitting it is a `TypeError`; explicitly passing `None`
(the shape a caller with an `Optional`-typed value could produce) is refused
with a named error rather than accepted and silently never trading. Neither
path is a place where a forecast could be derived from `NwsClimateDay` --
this module proves the refusal happens before any such temptation exists.
"""

from __future__ import annotations

import pytest
from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue

from breezy.strategy.forecast_mispricing.config import ForecastMispricingConfig
from breezy.strategy.forecast_mispricing.strategy import ForecastMispricingStrategy
from breezy.strategy.weather_common.forecast_source import MissingForecastSourceError

INSTRUMENT_ID = InstrumentId(Symbol("nyc-ge80"), Venue("POLYMARKET_US"))


def _config() -> ForecastMispricingConfig:
    return ForecastMispricingConfig(instrument_ids=(INSTRUMENT_ID,))


def test_omitting_the_forecast_source_is_a_type_error() -> None:
    with pytest.raises(TypeError):
        ForecastMispricingStrategy(_config())  # type: ignore[call-arg]


def test_passing_none_as_the_forecast_source_is_refused_loudly() -> None:
    with pytest.raises(MissingForecastSourceError):
        ForecastMispricingStrategy(_config(), None)  # type: ignore[arg-type]
