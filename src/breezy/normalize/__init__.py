"""Normalization: CLI-product parsing, classification, and physical sanity.

Curates the genuine cross-module public surface (data types, configs,
exception taxonomies, and stateless parse/classify/convert functions); omits
private regexes and other module-internal parsing helpers.
"""

from breezy.normalize.classify import (
    ClassificationError,
    Issuance,
    classify_issuance,
    has_correction_evidence,
)
from breezy.normalize.cli_parse import (
    MAX_LINE_COUNT,
    MAX_LINE_LENGTH,
    CliContentError,
    CliNotOurProductError,
    CliParseError,
    CliStructuralError,
    CliStructuralHeader,
    ParsedCliProduct,
    check_structural_allowlist,
    parse_cli_product,
    parse_temperature_token,
)
from breezy.normalize.climate_day import (
    ClimateDayError,
    climate_day_for_instant,
    standard_time_zone,
)
from breezy.normalize.reading import ClimateDayReading, SourceGrade
from breezy.normalize.sanity import (
    ABSOLUTE_MAX_F,
    ABSOLUTE_MIN_F,
    MAX_DIURNAL_RANGE_F,
    CliSanityError,
    check_physical_sanity,
)
from breezy.normalize.units import SentinelFlag, TemperatureReadingF, fahrenheit_to_celsius

__all__ = [
    "ABSOLUTE_MAX_F",
    "ABSOLUTE_MIN_F",
    "MAX_DIURNAL_RANGE_F",
    "MAX_LINE_COUNT",
    "MAX_LINE_LENGTH",
    "ClassificationError",
    "CliContentError",
    "CliNotOurProductError",
    "CliParseError",
    "CliSanityError",
    "CliStructuralError",
    "CliStructuralHeader",
    "ClimateDayError",
    "ClimateDayReading",
    "Issuance",
    "ParsedCliProduct",
    "SentinelFlag",
    "SourceGrade",
    "TemperatureReadingF",
    "check_physical_sanity",
    "check_structural_allowlist",
    "classify_issuance",
    "climate_day_for_instant",
    "fahrenheit_to_celsius",
    "has_correction_evidence",
    "parse_cli_product",
    "parse_temperature_token",
    "standard_time_zone",
]
