"""The ONE shared `DataType` for `ForecastPoint` (WP-12 Seam B).

Its own module rather than a fourth construction site inside ``nws_actor.py``,
for the reason ``iem_observations.py`` gives: the factory belongs with the
seam that publishes the record, and barrier W1
(``tests/unit/test_weather_data_type_barrier.py``) binds its exemption to the
module, not to the function name.

Carries NO metadata, matching ``nws_actor.py``'s Phase-1 convention. That is
not cosmetic: ``DataType.topic`` is built from the metadata in INSERTION
order while ``__eq__``/``__hash__`` compare a ``frozenset``, so two metadata-
bearing `DataType` objects can be equal to every unit test and still route to
different topics -- a subscriber that silently receives nothing. An empty
mapping here and an omitted ``BacktestDataConfig(metadata=...)`` elsewhere
match by construction.
"""

from __future__ import annotations

from functools import lru_cache

from nautilus_trader.model.data import DataType

from breezy.domain.forecast_point import ForecastPoint

__all__ = ["nbm_forecast_point_data_type"]


@lru_cache(maxsize=1)
def nbm_forecast_point_data_type() -> DataType:
    """The ONE `DataType` for `ForecastPoint`. Never construct another.

    ``lru_cache`` so every caller gets the SAME object, not merely an equal
    one -- identity is what barrier W1 asserts.
    """
    return DataType(ForecastPoint)
