"""Actor PUSH from the message bus into `ForecastState` -- WP-12 Seam D (R1-11).

The decider reads forecasts from an in-memory `ForecastState`, fed by this
Actor's subscription to the ONE shared ``DataType``. It never queries the
data store in the hot path: a live decision must not wait on parquet, and a
store read would also reintroduce the point-in-time hazard the vintage
columns exist to remove.

Direction of the wiring matters. ``strategy`` may reach DOWN into ``ingest``
for the shared ``DataType`` factory (the ``lint-imports`` layer contract says
so explicitly); ``ingest`` may never reach UP. So the producing Actor
publishes raw records and knows nothing about `ForecastState`, and this
consumer -- which lives beside the state it owns -- does the pushing. That is
the message bus doing exactly what it is for, not a layering workaround.

Absences are COUNTED, never stored. A `ForecastPoint` whose ``value_f`` is
``None`` carries a named ``absence_reason``; pushing it as a number would be
the single worst thing this seam could do, so it is tallied under
``absent_<reason>`` and dropped. A record for a station this Actor does not
serve is counted too, rather than silently ignored.
"""

from __future__ import annotations

from collections import Counter

from nautilus_trader.common.actor import Actor
from nautilus_trader.core.data import Data
from nautilus_trader.model.identifiers import ClientId

from breezy.domain.forecast_point import ForecastPoint
from breezy.ingest.nbm_forecast_data_type import nbm_forecast_point_data_type
from breezy.runtime.backtest_feed import NWS_BACKTEST_CLIENT_ID
from breezy.strategy.ladder_ev.forecast_state import ForecastState

__all__ = ["FORECAST_SUBSCRIBER_VARIABLE", "ForecastStateActor"]

#: The one forecast variable the ladder_ev decider consumes today.
FORECAST_SUBSCRIBER_VARIABLE: str = "TXN"


class ForecastStateActor(Actor):
    """Subscribes to `ForecastPoint` and pushes each into its station's state."""

    def __init__(
        self,
        *,
        stations: tuple[str, ...],
        variable: str = FORECAST_SUBSCRIBER_VARIABLE,
        client_id: ClientId = NWS_BACKTEST_CLIENT_ID,
    ) -> None:
        super().__init__()
        if not stations:
            raise ValueError("`stations` must name at least one station")
        self._variable = variable
        self._client_id = client_id
        self._states: dict[str, ForecastState] = {station: ForecastState() for station in stations}
        self.counters: Counter[str] = Counter()

    def state_for(self, station: str) -> ForecastState:
        """The in-memory store for `station`. Raises for a station not served."""
        try:
            return self._states[station]
        except KeyError:
            raise KeyError(
                f"{station!r} is not served by this forecast subscriber; "
                f"it holds {sorted(self._states)}"
            ) from None

    def on_start(self) -> None:
        """Subscribe to the ONE shared `DataType` -- never a second construction.

        Scoped by CLIENT, never by ``instrument_id``: an instrument-scoped
        subscription builds ``data.ForecastPoint.<venue>.<symbol>`` while the
        shared type's topic is ``ForecastPoint*``, and the pair does not
        match -- such a subscriber receives ZERO records with no error
        (``backtest_feed.NWS_BACKTEST_CLIENT_ID``'s own docstring). It is
        also semantically right: one forecast informs many markets.

        ``client_id`` is supplied for the same reason the observation
        strategy supplies it: without it Nautilus logs an ERROR and drops the
        ``SubscribeData`` command, so the catalog-replay path would go quiet
        while the live bus path kept working.
        """
        self.subscribe_data(nbm_forecast_point_data_type(), client_id=self._client_id)

    def on_data(self, data: Data) -> None:
        """Push one record. Never raises on a record it does not want."""
        # A `DataType(ForecastPoint)` subscription matches on the topic PREFIX
        # `ForecastPoint*`, so a future `ForecastPointHourly` would arrive
        # here too. The isinstance check is the documented defence.
        if not isinstance(data, ForecastPoint):
            return
        if data.variable != self._variable:
            self.counters["foreign_variable"] += 1
            return
        state = self._states.get(data.station)
        if state is None:
            self.counters["unknown_station"] += 1
            return
        if data.value_f is None:
            self.counters[f"absent_{data.absence_reason}"] += 1
            return
        state.push(
            value_f=data.value_f,
            available_at_ns=data.available_at_ns,
            cycle_runtime_ns=data.cycle_runtime_ns,
        )
        self.counters["pushed"] += 1
