"""Breezy record types -- hand-written NautilusTrader `Data` subclasses.

Importing this package imports every record module, so each type's single
module-scope ``register_arrow`` call has run by the time anything reads or writes
the catalog.

Three notes for callers:

* ``BacktestDataConfig(data_cls=...)`` needs the **colon** form
  (``"breezy.domain.nws_climate_day:NwsClimateDay"``); `Data.fully_qualified_name()`
  returns exactly that. A dotted path fails mid-run.
* No record class name may be a prefix of another. A ``DataType(X)`` subscriber
  matches ``XSomething`` by msgbus glob, so handlers `isinstance`-check as well.
* Build **every** publisher and subscriber `DataType` through
  :mod:`breezy.domain.data_types`. Metadata key ORDER changes ``DataType.topic``
  while ``__eq__``/``__hash__`` ignore it, so two hand-built `DataType`s can be
  equal and still route to different topics -- silent zero delivery, which for
  settlement data reads exactly like "no product was issued". The factory lives
  here rather than in `ingest/` because it is the publisher/subscriber contract
  and names these classes: a strategy must not import `breezy.ingest` to subscribe.
"""

from breezy.domain.data_types import canonical_metadata, climate_day_type, raw_product_type
from breezy.domain.nws_climate_day import (
    CLIMATE_DAY_SCHEMA_VERSION,
    MISSING_VALUE_FLAGS,
    NwsClimateDay,
)
from breezy.domain.nws_raw_product import RAW_PRODUCT_SCHEMA_VERSION, NwsRawProduct, sha256_text
from breezy.domain.selection import (
    ClimateDayKey,
    climate_day_key,
    latest_by_climate_day,
    select_climate_day,
)
from breezy.domain.strict_arrow import SchemaDriftError

__all__ = [
    "CLIMATE_DAY_SCHEMA_VERSION",
    "MISSING_VALUE_FLAGS",
    "RAW_PRODUCT_SCHEMA_VERSION",
    "ClimateDayKey",
    "NwsClimateDay",
    "NwsRawProduct",
    "SchemaDriftError",
    "canonical_metadata",
    "climate_day_key",
    "climate_day_type",
    "latest_by_climate_day",
    "raw_product_type",
    "select_climate_day",
    "sha256_text",
]
