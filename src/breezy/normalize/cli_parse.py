"""Extract settlement fields from verbatim NWS CLI product text.

PURE module: no I/O, no clock access, no `nautilus_trader` import, no
global state.

Extracts: the headline `summary_date` (never derived from issuanceTime),
the station/site header line (for the caller to validate against the
registry's `body_header_regex` -- this module accepts that regex as a
parameter and does not import the registry itself, to keep this island
free of any dependency beyond pure text), and tmax/tmin/tavg in whole
degrees Fahrenheit with sentinel flags (M/T/MS/MB) preserved rather than
imputed.

An ambiguous or unparseable product raises `CliParseError` rather than
returning a partially-populated result -- a silent partial parse is a
wrong settlement.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from breezy.normalize.units import TemperatureReadingF

_MONTH_NAME_TO_NUMBER: dict[str, int] = {
    "JANUARY": 1,
    "FEBRUARY": 2,
    "MARCH": 3,
    "APRIL": 4,
    "MAY": 5,
    "JUNE": 6,
    "JULY": 7,
    "AUGUST": 8,
    "SEPTEMBER": 9,
    "OCTOBER": 10,
    "NOVEMBER": 11,
    "DECEMBER": 12,
}

_HEADLINE_RE = re.compile(
    r"^(?P<line>\.\.\.THE\s+.+?\s+CLIMATE\s+SUMMARY\s+FOR\s+"
    r"(?P<month>[A-Z]+)\s+(?P<day>\d{1,2})\s+(?P<year>\d{4})\.\.\.)\s*$",
    re.MULTILINE,
)

_TEMPERATURE_BLOCK_RE = re.compile(r"TEMPERATURE\s*\(F\)(?P<block>.*?)PRECIPITATION", re.DOTALL)

# The TEMPERATURE (F) block may carry NORMAL and RECORD sub-blocks (their
# own labeled MAXIMUM/MINIMUM rows) alongside the actual observed values.
# The observed sub-block is always labeled YESTERDAY (finals) or TODAY
# (preliminaries) -- extraction MUST anchor there and nowhere else, or a
# reordered/unusual product could silently parse a record or normal value
# as the observed extreme. This is a mis-parse, not a rejection, which is
# exactly the failure mode this module exists to prevent.
_OBSERVED_SUBSECTION_RE = re.compile(
    r"^[ \t]*(?:YESTERDAY|TODAY)[ \t]*$\n(?P<subsection>.*?)(?=\n[ \t]*\n|\Z)",
    re.MULTILINE | re.DOTALL,
)

_MAXIMUM_RE = re.compile(r"MAXIMUM\s+(?P<token>-?\S+)")
_MINIMUM_RE = re.compile(r"MINIMUM\s+(?P<token>-?\S+)")
_AVERAGE_RE = re.compile(r"AVERAGE\s+(?P<token>-?\S+)")

_SENTINEL_TOKENS: dict[str, str] = {
    "M": "M",
    "MM": "M",
    "T": "T",
    "MS": "MS",
    "MB": "MB",
}


class CliParseError(ValueError):
    """Raised when a CLI product cannot be unambiguously parsed.

    Covers: no recognizable headline, an unparseable headline date, a
    missing TEMPERATURE (F) block, an unrecognized temperature token, or a
    station header that does not match the caller-supplied
    `body_header_regex`. Always raised rather than returning a
    partially-populated result.
    """


@dataclass(frozen=True)
class ParsedCliProduct:
    """The settlement-relevant fields extracted from one CLI product."""

    summary_date: date
    station_header_line: str
    tmax: TemperatureReadingF
    tmin: TemperatureReadingF
    tavg: TemperatureReadingF


def parse_temperature_token(token: str) -> TemperatureReadingF:
    """Parse a single raw temperature token into a `TemperatureReadingF`.

    Recognized sentinel tokens (M, MM, T, MS, MB) map to their sentinel
    flag with `value_f=None`. A signed integer token maps to `value_f`
    with `sentinel="NONE"`. Anything else raises `CliParseError` -- never
    imputed to 0, never silently dropped.
    """
    if not token:
        raise CliParseError("empty temperature token")
    if token in _SENTINEL_TOKENS:
        return TemperatureReadingF(value_f=None, sentinel=_SENTINEL_TOKENS[token])  # type: ignore[arg-type]
    try:
        value = int(token)
    except ValueError as exc:
        raise CliParseError(f"unrecognized temperature token: {token!r}") from exc
    return TemperatureReadingF(value_f=value, sentinel="NONE")


def _extract_temperature(block: str, pattern: re.Pattern[str], label: str) -> TemperatureReadingF:
    match = pattern.search(block)
    if match is None:
        raise CliParseError(f"no {label} value found in TEMPERATURE (F) block")
    return parse_temperature_token(match.group("token"))


def parse_cli_product(product_text: str, *, body_header_regex: str) -> ParsedCliProduct:
    """Parse a verbatim CLI product into its settlement-relevant fields.

    `body_header_regex` is the caller-supplied (registry-owned) pattern
    that the extracted station header line must match -- this is the
    guard against a same-office sibling product (e.g. a KOKX product that
    is silently JFK rather than Central Park). This module never derives
    or hardcodes that pattern itself.
    """
    if not product_text or not product_text.strip():
        raise CliParseError("empty product text")

    headline_match = _HEADLINE_RE.search(product_text)
    if headline_match is None:
        raise CliParseError(
            "no recognizable '...THE <SITE> CLIMATE SUMMARY FOR <DATE>...' headline found"
        )

    station_header_line = headline_match.group("line")
    if re.match(body_header_regex, station_header_line) is None:
        raise CliParseError(
            f"station header {station_header_line!r} does not match the expected "
            "body_header_regex; refusing to attribute this product to the wrong station"
        )

    month_number = _MONTH_NAME_TO_NUMBER.get(headline_match.group("month").upper())
    if month_number is None:
        raise CliParseError(
            f"unrecognized month name in headline: {station_header_line!r}"
        )
    try:
        summary_date = date(
            int(headline_match.group("year")),
            month_number,
            int(headline_match.group("day")),
        )
    except ValueError as exc:
        raise CliParseError(
            f"unparseable summary date in headline: {station_header_line!r}"
        ) from exc

    temperature_block_match = _TEMPERATURE_BLOCK_RE.search(product_text)
    if temperature_block_match is None:
        raise CliParseError("no TEMPERATURE (F) block found")
    block = temperature_block_match.group("block")

    observed_match = _OBSERVED_SUBSECTION_RE.search(block)
    if observed_match is None:
        raise CliParseError(
            "no YESTERDAY/TODAY observed subsection found in TEMPERATURE (F) block; "
            "refusing to guess an observed value from a NORMAL or RECORD row"
        )
    observed = observed_match.group("subsection")

    tmax = _extract_temperature(observed, _MAXIMUM_RE, "MAXIMUM")
    tmin = _extract_temperature(observed, _MINIMUM_RE, "MINIMUM")
    tavg = _extract_temperature(observed, _AVERAGE_RE, "AVERAGE")

    return ParsedCliProduct(
        summary_date=summary_date,
        station_header_line=station_header_line,
        tmax=tmax,
        tmin=tmin,
        tavg=tavg,
    )
