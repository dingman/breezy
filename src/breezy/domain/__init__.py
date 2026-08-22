"""Breezy record types -- hand-written NautilusTrader `Data` subclasses.

Importing this package imports every record module, so each type's single
module-scope ``register_arrow`` call has run by the time anything reads or writes
the catalog.

Two notes for callers:

* ``BacktestDataConfig(data_cls=...)`` needs the **colon** form
  (``"breezy.domain.nws_climate_day:NwsClimateDay"``); `Data.fully_qualified_name()`
  returns exactly that. A dotted path fails mid-run.
* No record class name may be a prefix of another. A ``DataType(X)`` subscriber
  matches ``XSomething`` by msgbus glob, so handlers `isinstance`-check as well.
"""

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
    "climate_day_key",
    "latest_by_climate_day",
    "select_climate_day",
    "sha256_text",
]
