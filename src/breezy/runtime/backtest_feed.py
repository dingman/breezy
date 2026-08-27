"""The backtest wiring seam for Breezy's weather custom data.

Two things live here, and they are the two halves of ONE routing identity: the
`ClientId` the weather stream is registered under, and the `CustomData`
envelope that lets a weather record survive the `DataEngine`. Both exist only
where a `BacktestEngine` does. The live ingest path has neither -- it is
Actor-driven with `data_clients={}` (``runtime/node_config.py``) and publishes
through ``Actor.publish_data``, which takes no ``ClientId`` at all.

Null hypothesis, checked against the installed ``nautilus-trader==1.231.0``
before this module was written
-----------------------------------------------------------------------------

**Native, and therefore used rather than rebuilt:**

* The envelope itself -- ``nautilus_trader.model.data.CustomData``. Nothing is
  subclassed and no parallel record type is introduced; the wrapper is
  constructed and handed straight to ``BacktestEngine.add_data``.
* The routing identity -- ``DataType``, built ONLY by the shared factories in
  :mod:`breezy.ingest.nws_actor`. This module constructs no ``DataType`` of
  its own; that rule is enforced by
  ``tests/unit/test_weather_data_type_barrier.py``.
* The client registration -- ``BacktestEngine.add_data(..., client_id=...)``
  creates the ``BacktestDataClient``. Breezy registers none itself.

**Genuinely absent, and therefore authored here (with the evidence):**

* *A canonical `ClientId`.* ``add_data(client_id=X)`` and
  ``Actor.subscribe_data(client_id=Y)`` are two independent call sites in two
  different files with no shared symbol between them. On a mismatch
  ``DataEngine._execute_command`` (``data/engine.pyx``) logs "no data client
  configured for ... `client_id` ..." and returns -- no raise, no
  subscription, no other signal. :data:`NWS_BACKTEST_CLIENT_ID` is the shared
  symbol that makes the two agree by construction.
* *A wrapping step.* ``DataEngine._handle_data`` (``data/engine.pyx``)
  dispatches on ``isinstance`` and its terminal ``else`` calls
  ``self._log.error("Cannot handle data: unrecognized type ...")``. It LOGS
  AND DROPS -- it does not raise. A bare ``NwsClimateDay`` therefore vanishes,
  and :func:`breezy.persistence.catalog.read_climate_days` returns exactly
  that shape (unwrapped, by design -- ``on_data`` delivers the unwrapped
  record, so the reader returns what handlers actually see). The reader's
  contract is deliberately NOT changed; the wrapping is a separate step,
  applied at the one boundary that needs it.

Why not in ``breezy.ingest.nws_actor`` next to the ``DataType`` factories: the
ingest Actor can never use either name. It has no ``DataClient``, so a
``ClientId`` is meaningless to it, and it publishes through
``Actor.publish_data``, which wraps internally. Putting a backtest-only
constant in the live ingest module would make it look like live routing
configuration, which is precisely the confusion the module docstring there
spends four paragraphs preventing.

Why not in ``breezy.persistence.catalog`` next to the readers: the layer
contract (``pyproject.toml``, import-linter) puts ``persistence`` BELOW
``ingest``, so the catalog cannot reach the shared ``DataType`` factories at
all. ``runtime`` is the top layer and may import both.

This module is deliberately NOT re-exported from ``breezy.runtime``'s facade:
that package is imported eagerly by the ingest process, and re-exporting here
would drag ``breezy.ingest.nws_actor`` into every one of those imports. Import
it directly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from nautilus_trader.model.data import CustomData
from nautilus_trader.model.identifiers import ClientId

from breezy.domain.nws_climate_day import NwsClimateDay
from breezy.domain.nws_raw_product import NwsRawProduct
from breezy.ingest.nws_actor import nws_climate_day_data_type, nws_raw_product_data_type

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Callable, Sequence

    from nautilus_trader.core.data import Data
    from nautilus_trader.model.data import DataType

__all__ = [
    "NWS_BACKTEST_CLIENT_ID",
    "UnfeedableRecordError",
    "as_backtest_data",
]

#: The ONE `ClientId` for Breezy's weather custom-data stream in a backtest.
#:
#: Both call sites MUST name this constant rather than a string literal:
#: ``BacktestEngine.add_data(records, client_id=NWS_BACKTEST_CLIENT_ID)`` and
#: ``Actor.subscribe_data(data_type, client_id=NWS_BACKTEST_CLIENT_ID)``. A
#: disagreement between them is not an error the platform raises: the
#: ``SubscribeData`` command is dropped with a single ERROR log line and the
#: run completes looking healthy.
#:
#: Scoping is by CLIENT, never by ``instrument_id``. An instrument-scoped
#: subscription builds the pattern ``data.NwsClimateDay.<venue>.<symbol>``
#: while ``DataType(NwsClimateDay).topic`` is ``NwsClimateDay*``;
#: ``is_matching_py`` returns False for that pair, so such a subscriber
#: receives ZERO records. That is also semantically right: one climate day
#: settles many markets, so weather is not per-instrument data.
NWS_BACKTEST_CLIENT_ID: Final[ClientId] = ClientId("BREEZY-NWS")


class UnfeedableRecordError(TypeError):
    """A record has no shared `DataType` and therefore no canonical topic.

    Raised rather than skipped or wrapped in an invented ``DataType``: the
    whole point of this module is that weather records stop disappearing
    quietly, and a silently invented topic is the same disappearance with an
    extra step.
    """


#: Record class -> its shared `DataType` factory. Type-EXACT: the key is
#: ``type(record)``, not an ``isinstance`` walk, so a subclass of a weather
#: record is refused instead of being routed onto its parent's topic. That is
#: not pedantry -- ``is_matching_py("data.NwsClimateDayExtra*",
#: "data.NwsClimateDay*")`` is **True**, so a record class whose name merely
#: STARTS WITH another's leaks into that subscription.
_DATA_TYPE_FACTORIES: Final[dict[type[Data], Callable[[], DataType]]] = {
    NwsClimateDay: nws_climate_day_data_type,
    NwsRawProduct: nws_raw_product_data_type,
}


def as_backtest_data(records: Sequence[Data]) -> list[CustomData]:
    """Wrap weather `records` so `BacktestEngine.add_data` can carry them.

    Parameters
    ----------
    records : Sequence[Data]
        ``NwsClimateDay`` and/or ``NwsRawProduct`` records, in any mix -- the
        shape :func:`breezy.persistence.catalog.read_climate_days` and
        :func:`breezy.persistence.catalog.read_raw_products` return.

    Returns
    -------
    list[CustomData]
        One envelope per record, in input order, each carrying the record
        object itself (not a copy) and the shared ``DataType`` for its class.
        Feed the result to ``BacktestEngine.add_data(..., client_id=``
        :data:`NWS_BACKTEST_CLIENT_ID` ``)``. Subscribers still receive the
        UNWRAPPED record in ``on_data``: ``DataEngine._handle_data`` publishes
        ``data.data`` on the envelope's topic, so the wrapper never reaches a
        handler.

    Raises
    ------
    UnfeedableRecordError
        If any record's exact class has no shared ``DataType`` factory.

    """
    wrapped: list[CustomData] = []
    for record in records:
        factory = _DATA_TYPE_FACTORIES.get(type(record))
        if factory is None:
            raise UnfeedableRecordError(
                f"{type(record).__name__} has no shared `DataType` factory; "
                f"feedable record classes are "
                f"{sorted(cls.__name__ for cls in _DATA_TYPE_FACTORIES)}",
            )
        wrapped.append(CustomData(data_type=factory(), data=record))
    return wrapped
