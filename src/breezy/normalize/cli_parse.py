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

An ambiguous or unparseable product raises a `CliParseError` subclass
rather than returning a partially-populated result -- a silent partial
parse is a wrong settlement.

FOUR REJECTION CATEGORIES, FOUR CONSEQUENCES. The settlement gate routes
rejection reasons differently and a hard block is sticky (it clears only
on a subsequent successful poll), so a single exception type would
hard-block a site for a routine, healthy event. Dispatch on the SUBCLASS,
most specific first, and never on a message string:

    try:
        parsed = parse_cli_product(text, cli_location=..., body_header_regex=...)
    except CliNotOurProductError:      # ROUTINE -- ignore, carry on
        continue
    except CliStructuralError:         # LOUD -- malformed/hostile body
        ...
    except CliParseError:              # CRIT -- our product, unreadable
        ...
    except CliSanityError:             # CRIT -- readable, impossible values
        ...

`CliSanityError` (from `normalize.sanity`) is deliberately OUTSIDE the
`CliParseError` hierarchy; the other three are inside it, so any existing
``except CliParseError`` keeps working. That also means
``isinstance(exc, CliParseError)`` is True for all three and COLLAPSES the
distinction -- exact-type / ordered-`except` dispatch is what separates
them.

STRUCTURAL PRE-PARSE GATE. Phase 1 parses inline on the asyncio event
loop (no executor/process containment exists for this path), so a slow
parse on a malformed product stalls the entire Nautilus event loop, not
just ingestion. `parse_cli_product` therefore runs a cheap, total
structural allowlist (line count, line length, WMO abbreviated-heading
shape, AWIPS PIL) BEFORE any of the headline/temperature regexes touch
the body. This ordering is deliberate: reject the cheap way first.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from breezy.normalize.sanity import check_physical_sanity
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

MAX_LINE_COUNT = 500
"""Real CLI products run ~90-100 lines; this gives ~5x headroom while still
rejecting a pathologically large body cheaply, well before the 128 KiB
transport-layer cap even applies."""

MAX_LINE_LENGTH = 200
"""Real CLI lines run up to ~75 characters (fixed-width columns plus
padding); this gives ~2.5x headroom while catching a single giant line
(e.g. no newlines at all) in O(1) per line, before any regex sees it."""

_WMO_HEADING_RE = re.compile(
    r"^[A-Z]{4}\d{2}\s+[A-Z]{4}\s+\d{6}(?:\s+(?P<bbb>[A-Z]{3}))?$"
)
"""WMO abbreviated heading shape: T1T2A1A2ii + WFO + ddhhmm, with an
optional trailing BBB correction token (CCA/CCB/...).

The BBB token is captured, not merely tolerated: api.weather.gov exposes
no BBB field, so this line is the ONLY place the correction signal
exists, and it drives revision/supersession decisions downstream."""


class CliParseError(ValueError):
    """Base class for every reason a CLI product did not yield a product.

    NEVER RAISED DIRECTLY -- always one of the three subclasses below.
    It exists so that pre-existing ``except CliParseError`` handlers keep
    catching everything they used to.

    Because all three subclasses satisfy ``isinstance(exc, CliParseError)``,
    an `isinstance` check against this base SILENTLY COLLAPSES the
    distinction between a routine sibling-station product and a
    stop-trading parse failure. Dispatch with ordered ``except`` clauses
    (most specific first) or with an exact-type check.

    Physically-impossible VALUES are not in this hierarchy at all -- see
    `breezy.normalize.sanity.CliSanityError`.
    """


class CliNotOurProductError(CliParseError):
    """ROUTINE: this product belongs to somebody else. Ignore it.

    Raised when the AWIPS PIL is not ``CLI{cli_location}`` -- a sibling
    station under the same WFO (KOKX issues NYC + JFK + LGA + EWR, KLOT
    issues MDW + ORD, ...), or a different product type such as a CLM
    monthly summary.

    This is an EXPECTED occurrence on a healthy system, not a defect. The
    correct response is to skip the product and carry on; recording a
    gate failure here manufactures an outage out of normal operation, and
    the block would be sticky until the next successful poll.

    Never receiving OUR product is still caught -- by the gate's
    freshness/`FINAL_CLI_OVERDUE` watchdog, which is the control designed
    for that question.
    """


class CliStructuralError(CliParseError):
    """LOUD: the body shape is malformed or hostile.

    Raised for an empty body, an oversize line count or line length, a
    body too short to carry a WMO header, a bad transmission indicator,
    or a WMO abbreviated heading that does not match its documented
    shape.

    This is NOT a routine sibling product: it is a body that should never
    have been served to us at all. Treat it as an integrity signal.
    """


class CliContentError(CliParseError):
    """CRIT: the structure passed, the content could not be read.

    Raised for a missing/unrecognizable headline, an unparseable headline
    date, a missing TEMPERATURE (F) block, a missing observed
    (YESTERDAY/TODAY) subsection, an unrecognized temperature token, or a
    station header that contradicts the caller-supplied
    `body_header_regex`.

    That last case is deliberately CRIT rather than routine: the AWIPS PIL
    already claimed this product is ours, so a body header naming another
    station is a CONTRADICTION INSIDE ONE PRODUCT -- precisely the silent
    wrong-station bug this module exists to catch.
    """


@dataclass(frozen=True)
class CliStructuralHeader:
    """The header facts the structural allowlist validated.

    Returned rather than discarded so a caller never has to re-scan text
    this module has already parsed. Two independent scans of the same
    bytes for the same facts will eventually disagree, and the fact they
    would disagree about here is "was this product a correction?" -- a
    supersession decision on an already-settled climate day.
    """

    awips_pil: str
    """AWIPS PIL from line 3, e.g. ``"CLINYC"``. Validated to equal
    ``CLI{cli_location}``. Distinct identifier space from the CLI location
    used in the api.weather.gov path segment."""

    wmo_bbb: str | None
    """WMO BBB correction token from line 2, e.g. ``"CCA"``; `None` when
    the heading carries none. `None` rather than `""` deliberately: an
    empty string and a missing value are indistinguishable under a
    truthiness test but not under an Arrow round-trip."""


@dataclass(frozen=True)
class ParsedCliProduct:
    """The settlement-relevant fields extracted from one CLI product."""

    summary_date: date
    station_header_line: str
    tmax: TemperatureReadingF
    tmin: TemperatureReadingF
    tavg: TemperatureReadingF
    awips_pil: str
    """See `CliStructuralHeader.awips_pil`. Required provenance."""

    wmo_bbb: str | None
    """See `CliStructuralHeader.wmo_bbb`. Required provenance -- no
    default, because a field that silently defaults to "not a correction"
    is a supersession bug waiting to happen."""


def parse_temperature_token(token: str) -> TemperatureReadingF:
    """Parse a single raw temperature token into a `TemperatureReadingF`.

    Recognized sentinel tokens (M, MM, T, MS, MB) map to their sentinel
    flag with `value_f=None`. A signed integer token maps to `value_f`
    with `sentinel="NONE"`. Anything else raises `CliContentError` --
    never imputed to 0, never silently dropped.
    """
    if not token:
        raise CliContentError("empty temperature token")
    if token in _SENTINEL_TOKENS:
        return TemperatureReadingF(value_f=None, sentinel=_SENTINEL_TOKENS[token])  # type: ignore[arg-type]
    try:
        value = int(token)
    except ValueError as exc:
        raise CliContentError(f"unrecognized temperature token: {token!r}") from exc
    return TemperatureReadingF(value_f=value, sentinel="NONE")


def _extract_temperature(block: str, pattern: re.Pattern[str], label: str) -> TemperatureReadingF:
    match = pattern.search(block)
    if match is None:
        raise CliContentError(f"no {label} value found in TEMPERATURE (F) block")
    return parse_temperature_token(match.group("token"))


def check_structural_allowlist(product_text: str, *, cli_location: str) -> CliStructuralHeader:
    """Cheap, total pre-parse gate; returns the header facts it validated.

    PUBLIC and separately callable. The poll sequence treats structural
    rejection and parsing as two steps with distinct consequences, which
    is only implementable if a caller can run the structural step alone.
    `parse_cli_product` ALSO calls it -- defence in depth, and it must
    stay ahead of every regex.

    Runs BEFORE any headline/temperature regex sees the body, so a
    malformed or adversarial product is rejected in bounded, near-constant
    work regardless of what the later regexes could otherwise be made to
    do with it.

    Checks, in order: total line count, per-line length, the WMO
    transmission-indicator line ("000"), the WMO abbreviated-heading shape
    (capturing the optional BBB correction token), and AWIPS PIL equality
    to ``CLI{cli_location}``.

    Raises `CliStructuralError` for a malformed or hostile SHAPE, and
    `CliNotOurProductError` for a well-formed product that simply belongs
    to another station or product type (a sibling under the same WFO, or a
    CLM monthly). Those two consequences are different -- see the module
    docstring.
    """
    if not product_text or not product_text.strip():
        raise CliStructuralError("empty product text")

    lines = product_text.split("\n")

    if len(lines) > MAX_LINE_COUNT:
        raise CliStructuralError(
            f"product has {len(lines)} lines, exceeding the {MAX_LINE_COUNT}-line "
            "structural allowlist"
        )
    for line in lines:
        if len(line) > MAX_LINE_LENGTH:
            raise CliStructuralError(
                f"product contains a line of {len(line)} characters, exceeding the "
                f"{MAX_LINE_LENGTH}-character structural allowlist"
            )

    # Expected shape (matches every real product observed across five
    # offices): [0] blank transmission leader, [1] "000" indicator,
    # [2] WMO abbreviated heading, [3] AWIPS PIL.
    if len(lines) < 4:
        raise CliStructuralError(
            "product is too short to contain a WMO header and AWIPS PIL"
        )

    if lines[1].strip() != "000":
        raise CliStructuralError(
            f"unexpected transmission indicator line: {lines[1]!r}; expected '000'"
        )

    wmo_match = _WMO_HEADING_RE.match(lines[2].strip())
    if wmo_match is None:
        raise CliStructuralError(
            f"line does not match the WMO abbreviated-heading shape: {lines[2]!r}"
        )

    actual_pil = lines[3].strip()
    if not actual_pil:
        # No PIL line at all is a SHAPE problem, not an addressing one:
        # this body is not another station's product, it is not a product.
        raise CliStructuralError(
            "product has no AWIPS PIL on line 4 of the transmission header"
        )

    expected_pil = f"CLI{cli_location}"
    if actual_pil != expected_pil:
        # ROUTINE, not a defect: one WFO issues several cities' products,
        # so a sibling station's PIL (or a CLM monthly's) arriving on this
        # poll is expected on a healthy system. Blocking here would be an
        # outage manufactured out of normal operation.
        raise CliNotOurProductError(
            f"AWIPS PIL {actual_pil!r} does not match expected {expected_pil!r} "
            f"for cli_location {cli_location!r}; this product belongs to another "
            "station or product type and is not ours to parse"
        )

    return CliStructuralHeader(awips_pil=actual_pil, wmo_bbb=wmo_match.group("bbb"))


def parse_cli_product(
    product_text: str, *, cli_location: str, body_header_regex: re.Pattern[str]
) -> ParsedCliProduct:
    """Parse a verbatim CLI product into its settlement-relevant fields.

    `cli_location` is the expected CLI location (e.g. "NYC") -- used only
    to check the AWIPS PIL in the structural allowlist. This is NOT the
    same identifier as the `/products/types/CLI/locations/{loc}` path
    segment being conflated with the PIL itself: `cli_location="NYC"`
    checks that line 3 of the body reads exactly "CLINYC" (PIL = "CLI" +
    cli_location); the two are related but distinct identifier spaces.

    `body_header_regex` is the caller-supplied (registry-owned) COMPILED
    pattern that the extracted station header line must match -- this is
    the guard against a same-office sibling product (e.g. a KOKX product
    that is silently JFK rather than Central Park). This module never
    derives or hardcodes that pattern itself, and it uses the pattern
    exactly as given: passing ``pattern.pattern`` instead would recompile
    the source WITHOUT the registry's ``re.MULTILINE`` flag, which is
    behaviourally equivalent for today's single-line patterns and
    therefore fails silently the first time it is not. A `str` is
    rejected with `TypeError` -- a coding defect, deliberately NOT a
    `ValueError`, so a caller routing data problems to the settlement gate
    cannot launder a bug into a data-quality reason code.

    The structural allowlist (line count, line length, WMO header shape,
    AWIPS PIL) runs FIRST, before any headline/temperature regex touches
    the body -- see the module docstring for why that ordering matters.
    Physical sanity bounds run LAST, after every field is extracted.

    Raises `CliNotOurProductError` (routine), `CliStructuralError` (loud),
    `CliContentError` (crit) or `CliSanityError` (crit, and outside the
    `CliParseError` hierarchy). See the module docstring for how to
    dispatch on them.
    """
    if not isinstance(body_header_regex, re.Pattern):
        raise TypeError(
            "`body_header_regex` must be a compiled `re.Pattern[str]` (pass the "
            "registry's `SettlementSite.body_header_regex` itself, not its "
            "`.pattern` source string). Re-compiling the source discards the "
            "flags it was compiled with -- the registry uses re.MULTILINE -- "
            f"and that discard is silent; got {type(body_header_regex).__name__}"
        )

    header = check_structural_allowlist(product_text, cli_location=cli_location)

    headline_match = _HEADLINE_RE.search(product_text)
    if headline_match is None:
        raise CliContentError(
            "no recognizable '...THE <SITE> CLIMATE SUMMARY FOR <DATE>...' headline found"
        )

    station_header_line = headline_match.group("line")
    if body_header_regex.match(station_header_line) is None:
        raise CliContentError(
            f"station header {station_header_line!r} does not match the expected "
            "body_header_regex even though the AWIPS PIL claimed this product is "
            f"ours ({header.awips_pil}); refusing to attribute a self-contradictory "
            "product to any station"
        )

    month_number = _MONTH_NAME_TO_NUMBER.get(headline_match.group("month").upper())
    if month_number is None:
        raise CliContentError(
            f"unrecognized month name in headline: {station_header_line!r}"
        )
    try:
        summary_date = date(
            int(headline_match.group("year")),
            month_number,
            int(headline_match.group("day")),
        )
    except ValueError as exc:
        raise CliContentError(
            f"unparseable summary date in headline: {station_header_line!r}"
        ) from exc

    temperature_block_match = _TEMPERATURE_BLOCK_RE.search(product_text)
    if temperature_block_match is None:
        raise CliContentError("no TEMPERATURE (F) block found")
    block = temperature_block_match.group("block")

    observed_match = _OBSERVED_SUBSECTION_RE.search(block)
    if observed_match is None:
        raise CliContentError(
            "no YESTERDAY/TODAY observed subsection found in TEMPERATURE (F) block; "
            "refusing to guess an observed value from a NORMAL or RECORD row"
        )
    observed = observed_match.group("subsection")

    tmax = _extract_temperature(observed, _MAXIMUM_RE, "MAXIMUM")
    tmin = _extract_temperature(observed, _MINIMUM_RE, "MINIMUM")
    tavg = _extract_temperature(observed, _AVERAGE_RE, "AVERAGE")

    # Physical sanity LAST: every field is present and typed, so a
    # violation here means the product is malformed or the parser is
    # wrong -- either way it must never reach settlement. Raises
    # `CliSanityError`, which is NOT a `CliParseError`.
    check_physical_sanity(tmax=tmax, tmin=tmin, tavg=tavg)

    return ParsedCliProduct(
        summary_date=summary_date,
        station_header_line=station_header_line,
        tmax=tmax,
        tmin=tmin,
        tavg=tavg,
        awips_pil=header.awips_pil,
        wmo_bbb=header.wmo_bbb,
    )
