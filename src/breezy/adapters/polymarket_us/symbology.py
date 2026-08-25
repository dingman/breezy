"""Polymarket.us slug <-> Nautilus ``InstrumentId``, and the weather slug grammar.

Plan revision 2 section 6 ``symbology.py``; ``POLYMARKET_US_BUILD_PLAN.md:65``.

**Never hyphen parsing.** The bundled ``nautilus_trader.adapters.polymarket``
symbology splits on ``-`` and indexes ``[0]``/``[1]``
(``common/symbol.py:20-41``); a Polymarket.us slug such as
``tc-temp-nychigh-2026-08-25-lt79f`` has six hyphen-separated segments, so that
scheme would silently mis-key every weather market. Nothing here imports it.

**The reserved separator is** ``~``. It is reserved so a later phase can encode
a composite symbol without ambiguity, which means a slug that already contains
it must be refused now rather than round-trip incorrectly later.

**A dotted slug is refused.** ``InstrumentId.from_str`` splits on the LAST
``"."``, so a slug containing a dot produces an id that does not round-trip.

**The weather grammar is inferred from captured slugs, and is fallible.**
``polymarket-us-integration`` records the weather slug format as UNRESOLVED.
:func:`parse_weather_slug` therefore returns ``None`` -- never a partially
guessed record -- for anything outside the two grammars actually observed in
``docs/evidence/venue/polymarket_us/raw/``. Callers decide whether ``None`` is
tolerable; :mod:`breezy.adapters.polymarket_us.parsing` decides it is not for a
market the venue itself labels ``climate``.

Bound tokens are stored **verbatim**. The captured market
``tc-temp-nychigh-2026-08-25-lt79f`` carries the venue title "78 or below" and a
description saying "less than or equal to 78F", so ``lt79`` and ``lte78``
describe the same contract. Recording ``("lt", 79)`` states what the slug says;
translating it to ``("lte", 78)`` would be an unevidenced venue-semantics claim.

**And ``lt79 == lte78`` is NOT a general identity.** It holds only if the
settlement reading is a whole degree -- and this repo has already had to
special-case fractional and record-qualifier NWS temperatures. Worse, the
committed captures show the two spellings actively DISAGREEING on range
markets: ``tc-temp-laxhigh-2026-08-24-gte80lt81f`` is titled "80 to 81" and
described as "between 80F and 81F", while a strict whole-degree reading of
``lt81`` yields the single value 80. The bucket ladder for that day
(``lt80``, ``gte80lt81``, ``gte82lt83``, ``gte84lt85``, ``gte86lt87``,
``gte88``) tiles the temperature line without gaps ONLY under the venue's
inclusive prose reading; under the literal slug reading, 81, 83, 85 and 87
belong to no bucket at all.

So a consumer must never treat ``<`` and ``<=`` as interchangeable on the
strength of the slug alone. :func:`assert_bounds_cross_checked` is the loud,
explicit cross-check: it refuses unless the caller states that the settlement
reading is whole-degree AND the venue's own ``description``/``title``
corroborate the interval the slug spells. It decides nothing about settlement;
it only refuses to let an unverified comparator through.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue

from breezy.adapters.polymarket_us.errors import BoundsSemanticsError, VenuePayloadError

__all__ = [
    "INSTRUMENT_SEPARATOR",
    "POLYMARKET_US_VENUE",
    "WeatherSlug",
    "assert_bounds_cross_checked",
    "assert_valid_slug",
    "instrument_id_to_slug",
    "parse_weather_slug",
    "slug_to_instrument_id",
]

#: Reserved for a future composite symbol. A slug containing it is refused.
INSTRUMENT_SEPARATOR: str = "~"

#: The single venue identity for this adapter.
POLYMARKET_US_VENUE: Venue = Venue("POLYMARKET_US")

#: Permitted slug characters. Deliberately narrow: it excludes ``.`` (breaks
#: ``InstrumentId`` round-tripping), ``~`` (reserved), whitespace, ``/`` and
#: ``?`` (either of which would change the meaning of a URL path segment the
#: slug is interpolated into).
_SLUG_RE: re.Pattern[str] = re.compile(r"^[a-z0-9][a-z0-9_-]*$")

_MAX_SLUG_LENGTH: int = 128

#: Observed weather grammar: ``tc-temp-<city><measure>-<YYYY-MM-DD>-<bounds>``.
_WEATHER_SLUG_RE: re.Pattern[str] = re.compile(
    r"^tc-temp-(?P<city>[a-z]{3})(?P<measure>high|low)"
    r"-(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})"
    r"-(?P<bounds>[a-z0-9]+)$"
)

#: One comparator token inside the bounds segment, e.g. ``gte72`` or ``lt73``.
_BOUND_TOKEN_RE: re.Pattern[str] = re.compile(r"(gte|lte|gt|lt)(\d{1,3})")

#: The bounds segment as a whole: one or more comparator tokens, then a unit.
_BOUNDS_RE: re.Pattern[str] = re.compile(r"^(?:(?:gte|lte|gt|lt)\d{1,3})+f$")

_MAX_BOUND_TOKENS: int = 2


@dataclass(frozen=True, slots=True)
class WeatherSlug:
    """The structured reading of one weather-market slug.

    ``bounds`` holds the comparator tokens exactly as the slug spells them, in
    slug order. ``raw_bounds`` keeps the untouched segment so a later phase can
    re-derive semantics without re-fetching the market.

    Neither field is settlement-safe on its own. ``lt`` in a slug is NOT
    reliably a strict inequality against the venue's own description -- see the
    module docstring and :func:`assert_bounds_cross_checked`, which every
    consumer of ``bounds``/``raw_bounds`` must pass before comparing a
    temperature against them.
    """

    slug: str
    city: str
    measure: str
    climate_date: str
    raw_bounds: str
    bounds: tuple[tuple[str, int], ...]

    @property
    def city_day_cluster_id(self) -> str:
        """Correlated-exposure key.

        Every bucket of every series for one city on one climate date shares
        this value, which is the Phase 3 exit-gate requirement and what the
        Phase 5 correlated-exposure cap keys on. It deliberately does NOT
        include ``measure``: a city's high-temperature and low-temperature
        markets for the same day are driven by the same forecast error and
        belong in one cluster.
        """
        return f"{self.city}:{self.climate_date}"


def assert_valid_slug(slug: object) -> None:
    """Raise :class:`VenuePayloadError` unless ``slug`` is a usable market slug."""
    if not isinstance(slug, str):
        raise VenuePayloadError(
            f"Polymarket.us market slug must be a string, got {type(slug).__name__}"
        )
    if not slug:
        raise VenuePayloadError("Polymarket.us market slug is empty")
    if len(slug) > _MAX_SLUG_LENGTH:
        raise VenuePayloadError(
            f"Polymarket.us market slug exceeds {_MAX_SLUG_LENGTH} characters "
            f"({len(slug)}); refusing to use it as a URL path segment"
        )
    if INSTRUMENT_SEPARATOR in slug:
        raise VenuePayloadError(
            f"Polymarket.us market slug {slug!r} contains the reserved instrument "
            f"separator {INSTRUMENT_SEPARATOR!r}"
        )
    if "." in slug:
        raise VenuePayloadError(
            f"Polymarket.us market slug {slug!r} contains '.', which collides with "
            "the InstrumentId symbol/venue delimiter and would not round-trip"
        )
    if not _SLUG_RE.match(slug):
        raise VenuePayloadError(
            f"Polymarket.us market slug {slug!r} is outside the permitted character "
            f"set {_SLUG_RE.pattern}"
        )


def slug_to_instrument_id(slug: str, venue: Venue = POLYMARKET_US_VENUE) -> InstrumentId:
    """Build the Nautilus ``InstrumentId`` for ``slug``, validating it first."""
    assert_valid_slug(slug)
    return InstrumentId(Symbol(slug), venue)


def instrument_id_to_slug(instrument_id: InstrumentId, venue: Venue = POLYMARKET_US_VENUE) -> str:
    """Invert :func:`slug_to_instrument_id`, refusing a foreign venue.

    The venue check is not ceremony: an ``InstrumentId`` for another venue
    carries a symbol in another namespace, and silently treating it as a
    Polymarket.us slug would build a request for a market that does not exist.
    """
    if instrument_id.venue != venue:
        raise VenuePayloadError(
            f"InstrumentId {instrument_id} belongs to venue {instrument_id.venue}, "
            f"not {venue}; refusing to read it as a Polymarket.us slug"
        )
    slug: str = str(instrument_id.symbol.value)
    assert_valid_slug(slug)
    return slug


def _parse_bounds(raw_bounds: str) -> tuple[tuple[str, int], ...] | None:
    if not _BOUNDS_RE.match(raw_bounds):
        return None
    tokens = tuple(
        (match.group(1), int(match.group(2))) for match in _BOUND_TOKEN_RE.finditer(raw_bounds)
    )
    if not tokens or len(tokens) > _MAX_BOUND_TOKENS:
        return None
    return tokens


#: Venue prose spellings of a closed upper bound, e.g. "less than or equal to
#: 78F" / "78 or below" / "78° or below".
_PROSE_UPPER_RE: re.Pattern[str] = re.compile(
    r"less than or equal to\s*(\d{1,3})|(\d{1,3})\D{0,3}or below", re.IGNORECASE
)

#: Venue prose spellings of a closed lower bound.
_PROSE_LOWER_RE: re.Pattern[str] = re.compile(
    r"greater than or equal to\s*(\d{1,3})|(\d{1,3})\D{0,3}or above", re.IGNORECASE
)

#: Venue prose spellings of a closed interval, e.g. "between 80F and 81F" /
#: "80 to 81" / "68° to 69°".
_PROSE_INTERVAL_RE: re.Pattern[str] = re.compile(
    r"between\s*(\d{1,3})\D{0,8}?and\s*(\d{1,3})|(\d{1,3})\D{0,3}to\s*(\d{1,3})",
    re.IGNORECASE,
)

#: The closed-interval reading of each slug comparator, valid ONLY for a
#: whole-degree settlement reading. ``lt N`` excludes ``N``, so under whole
#: degrees its greatest member is ``N - 1``.
_COMPARATOR_OFFSETS: dict[str, tuple[str, int]] = {
    "lt": ("upper", -1),
    "lte": ("upper", 0),
    "gt": ("lower", 1),
    "gte": ("lower", 0),
}

ClosedInterval = tuple[int | None, int | None]


def _slug_closed_interval(bounds: tuple[tuple[str, int], ...]) -> ClosedInterval:
    """Read ``bounds`` as an inclusive integer interval (whole degrees only)."""
    lower: int | None = None
    upper: int | None = None
    for comparator, value in bounds:
        side, offset = _COMPARATOR_OFFSETS[comparator]
        if side == "upper":
            upper = value + offset
        else:
            lower = value + offset
    return lower, upper


def _prose_closed_interval(text: str | None) -> ClosedInterval | None:
    """Read the venue's own words as an inclusive integer interval, or ``None``."""
    if not isinstance(text, str) or not text.strip():
        return None
    match = _PROSE_INTERVAL_RE.search(text)
    if match is not None:
        low, high = (match.group(1), match.group(2))
        if low is None or high is None:
            low, high = (match.group(3), match.group(4))
        if low is not None and high is not None:
            return int(low), int(high)
        return None
    match = _PROSE_UPPER_RE.search(text)
    if match is not None:
        return None, int(match.group(1) or match.group(2))
    match = _PROSE_LOWER_RE.search(text)
    if match is not None:
        return int(match.group(1) or match.group(2)), None
    return None


def assert_bounds_cross_checked(
    weather: WeatherSlug,
    *,
    description: str | None,
    title: str | None,
    reading_is_whole_degrees: bool,
) -> ClosedInterval:
    """Refuse to let a slug comparator be used until the venue prose confirms it.

    This is a REFUSAL GATE, not settlement logic: it reads no observation,
    decides no outcome, and computes no payoff. It exists because
    ``bounds``/``raw_bounds`` are stored verbatim (correctly), and a verbatim
    ``lt`` is not a verified ``<``.

    Two independent things must hold, and both are checked:

    1. ``reading_is_whole_degrees`` must be ``True``. The whole identity
       ``lt N == lte N-1`` collapses the moment the settlement reading carries
       a fraction, and this repo has already met fractional and
       record-qualifier NWS temperatures. The caller has to assert the
       assumption explicitly, at the call site, in the traceback.
    2. The inclusive interval implied by the slug must equal the inclusive
       interval the venue states in ``description`` or ``title``. Where both
       are readable they must also agree with each other.

    Returns
    -------
    ClosedInterval
        The corroborated ``(lower, upper)`` inclusive bounds, either end
        ``None`` for an open side. Returned rather than discarded so a
        consumer has a *verified* value to use and no reason to re-derive one
        from the raw comparator.

    Raises
    ------
    BoundsSemanticsError
        If the whole-degree assumption is not asserted, if neither field
        yields a readable interval, if the two fields disagree, or if the
        venue's interval differs from the slug's. On the captured corpus the
        last case fires for every ``gte<A>lt<B>`` range market -- that is a
        real venue divergence, not a false positive; see the module docstring.
    """
    if not reading_is_whole_degrees:
        raise BoundsSemanticsError(
            f"Refusing to interpret bounds {weather.raw_bounds!r} of {weather.slug!r}: "
            "the slug's comparators can only be read as an integer interval when the "
            "settlement reading is a whole degree. A fractional or record-qualifier "
            "reading makes 'lt N' and 'lte N-1' different contracts."
        )

    from_description = _prose_closed_interval(description)
    from_title = _prose_closed_interval(title)
    if from_description is None and from_title is None:
        raise BoundsSemanticsError(
            f"Refusing to interpret bounds {weather.raw_bounds!r} of {weather.slug!r}: "
            "neither the venue description nor the title states an interval this "
            "adapter can read, so the slug's comparators cannot be corroborated."
        )
    if from_description is not None and from_title is not None and from_description != from_title:
        raise BoundsSemanticsError(
            f"Venue description and title disagree for {weather.slug!r}: description "
            f"reads {from_description}, title reads {from_title}."
        )

    from_prose = from_description if from_description is not None else from_title
    from_slug = _slug_closed_interval(weather.bounds)
    if from_slug != from_prose:
        raise BoundsSemanticsError(
            f"Bounds {weather.raw_bounds!r} of {weather.slug!r} are not corroborated by "
            f"the venue's own words: the slug reads {from_slug} under a whole-degree "
            f"interpretation, the venue states {from_prose}. Do NOT treat '<' and '<=' "
            "as interchangeable here -- resolve the venue's intended interval before "
            "using this market for settlement."
        )
    return from_slug


def parse_weather_slug(slug: str) -> WeatherSlug | None:
    """Read a weather slug, or return ``None`` when the grammar is unrecognised.

    ``None`` is the honest answer for an unobserved grammar. The venue
    documents no weather slug format, so a best-effort partial parse would
    fabricate a ``city_day_cluster_id`` and quietly mis-group exposure.
    """
    if not isinstance(slug, str):
        return None
    match = _WEATHER_SLUG_RE.match(slug)
    if match is None:
        return None

    try:
        climate_date = date(
            int(match.group("year")), int(match.group("month")), int(match.group("day"))
        )
    except ValueError:
        return None

    raw_bounds = match.group("bounds")
    bounds = _parse_bounds(raw_bounds)
    if bounds is None:
        return None

    return WeatherSlug(
        slug=slug,
        city=match.group("city"),
        measure=match.group("measure"),
        climate_date=climate_date.isoformat(),
        raw_bounds=raw_bounds,
        bounds=bounds,
    )
