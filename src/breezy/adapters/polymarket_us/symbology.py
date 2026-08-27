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

Bound tokens are stored **verbatim**. Recording ``("lt", 79)`` states what the
slug says; rewriting it to ``("lte", 78)`` would be an unevidenced
venue-semantics claim, so :class:`WeatherSlug` never does that.

**THE SLUG IS NOT THE SOURCE OF TRUTH FOR THE COMPARATOR (G-19 B6).**
The venue's own ``description``/``title`` are, and this module reads them
first. The reason is empirical, not stylistic: across the 680 distinct weather
markets in ``docs/evidence/venue/polymarket_us/raw/`` the ``lt`` token is
**context dependent**, so no single comparator algebra can decode it.

============================  ==========================  ==================
slug bound segment (count)    the venue's own words        closed interval
============================  ==========================  ==================
``lt<N>f``          (113)     "less than or equal to N-1"  ``(None, N - 1)``
``gte<N>f``         (112)     "greater than or equal to N" ``(N, None)``
``gte<A>lt<B>f``    (455)     "between A and B"            ``(A, B)``
============================  ==========================  ==================

Read the ``lt`` column twice. Standalone, ``lt80`` is titled "79 or below" --
the ordinary strict reading, upper bound ``N - 1``. Inside a range,
``gte80lt81`` is titled "80 to 81" -- the SAME token now contributing an
INCLUSIVE upper bound of ``N``. One offset cannot be both.

The tie-break is the bucket ladder. For each of the 114 captured
(city, measure, climate-date) groups the venue publishes a ladder of buckets;
under the prose reading those ladders tile the whole-degree line with no gap
and no overlap in **114 of 114** cases, and under the naive strict slug reading
in **0 of 114** -- e.g. LAX 2026-08-24 reads ``<=79``, ``80-81``, ``82-83``,
``84-85``, ``86-87``, ``>=88``, a perfect partition, whereas the literal slug
reading orphans 81, 83, 85 and 87, leaving those settlement values covered by
no contract at all. A venue cannot run that ladder, so the prose is right and
the inferred grammar is wrong.

So the slug is demoted to a CORROBORATING cross-check, and the check is the
table above -- a recorded observation over 680/680 captured markets, not a
comparator algebra. A bound segment outside those three families is refused
rather than extrapolated. ``lte`` and bare ``gt`` are accepted by the token
regex but have **never been emitted by the venue**; they decode to ``None``.

**Absent or unreadable prose is a refusal, not a fallback.** Falling back to
the slug would be falling back to a reading that is provably wrong for 455 of
680 captured markets. :func:`assert_bounds_cross_checked` therefore raises, and
its refusal deliberately carries no candidate interval for a caller to salvage.

``lt79 == lte78`` also holds only if the settlement reading is a whole degree
-- this repo has already had to special-case fractional and record-qualifier
NWS temperatures -- so the caller must assert that explicitly, at the call
site, in the traceback. :func:`assert_bounds_cross_checked` decides nothing
about settlement; it only refuses to let an uncorroborated comparator through.
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
    "PROSE_BETWEEN",
    "PROSE_GE",
    "PROSE_LE",
    "ClosedInterval",
    "ProseBounds",
    "WeatherSlug",
    "assert_bounds_cross_checked",
    "assert_valid_slug",
    "instrument_id_to_slug",
    "parse_prose_bounds",
    "parse_weather_slug",
    "slug_closed_interval",
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


ClosedInterval = tuple[int | None, int | None]

#: The three comparators the venue actually writes. Enumerated over the full
#: recursive corpus BEFORE this parser was designed: 455 ``between``, 113
#: ``less than or equal to``, 112 ``greater than or equal to`` across 680
#: distinct markets, with no fourth form. Kept as a closed vocabulary so an
#: unobserved fourth spelling fails loudly instead of being silently dropped.
PROSE_LE: str = "<="
PROSE_GE: str = ">="
PROSE_BETWEEN: str = "between"

#: "between 80F and 81F", "between 64°F and 65°F" (description forms) and
#: "80 to 81", "64° to 65°" (title / titleShort forms).
_PROSE_BETWEEN_RE: re.Pattern[str] = re.compile(
    r"between\s*(\d{1,3})\s*(?:°|&deg;)?\s*F?\s*and\s*(\d{1,3})"
    r"|(?<!\d)(\d{1,3})\s*(?:°|&deg;)?\s*to\s*(\d{1,3})(?!\d)",
    re.IGNORECASE,
)

#: "less than or equal to 78F", "78 or below", "78° or below".
_PROSE_LE_RE: re.Pattern[str] = re.compile(
    r"less than or equal to\s*(\d{1,3})|(?<!\d)(\d{1,3})\s*(?:°|&deg;)?\s*or below",
    re.IGNORECASE,
)

#: "greater than or equal to 88F", "88 or above", "88° or above".
_PROSE_GE_RE: re.Pattern[str] = re.compile(
    r"greater than or equal to\s*(\d{1,3})|(?<!\d)(\d{1,3})\s*(?:°|&deg;)?\s*or above",
    re.IGNORECASE,
)

#: Every slug bound-segment family OBSERVED in the captures, mapped to the
#: closed whole-degree interval the venue's own prose states for it. Counts and
#: the ladder-tiling evidence are in the module docstring.
#:
#: This is a RECORDED OBSERVATION, not a comparator algebra, and that
#: distinction is the whole point of B6: ``lt`` carries offset ``-1`` in the
#: one-token family and offset ``0`` in the two-token family, so there is no
#: per-token rule to write down. A family absent from this table is refused.
_OBSERVED_SLUG_FAMILIES: frozenset[tuple[str, ...]] = frozenset(
    {("lt",), ("gte",), ("gte", "lt")}
)


@dataclass(frozen=True, slots=True)
class ProseBounds:
    """Strike and comparator as stated by the venue, in the venue's own words.

    This is the PRIMARY reading. ``strikes`` holds the numbers the venue
    actually wrote, in the order it wrote them, so a consumer can render the
    contract back without re-deriving it. ``closed_interval`` is the same
    statement as an inclusive whole-degree interval.
    """

    comparator: str
    strikes: tuple[int, ...]
    closed_interval: ClosedInterval


def parse_prose_bounds(text: str | None) -> ProseBounds | None:
    """Read the venue's own words into a comparator and strike, or ``None``.

    ``None`` means "this adapter cannot read it", never "there is no bound".
    Callers must treat ``None`` as a refusal; there is deliberately no
    slug-derived fallback, because the slug's ``lt`` is provably context
    dependent (module docstring).

    A text matching more than one comparator family is also ``None``: two
    readable-but-different statements in one field is a venue change we must
    look at, not something to resolve by match order.
    """
    if not isinstance(text, str) or not text.strip():
        return None

    candidates: list[ProseBounds] = []

    between = _PROSE_BETWEEN_RE.search(text)
    if between is not None:
        low, high = between.group(1), between.group(2)
        if low is None or high is None:
            low, high = between.group(3), between.group(4)
        if low is not None and high is not None:
            candidates.append(
                ProseBounds(
                    comparator=PROSE_BETWEEN,
                    strikes=(int(low), int(high)),
                    closed_interval=(int(low), int(high)),
                )
            )

    upper = _PROSE_LE_RE.search(text)
    if upper is not None:
        value = int(upper.group(1) or upper.group(2))
        candidates.append(
            ProseBounds(comparator=PROSE_LE, strikes=(value,), closed_interval=(None, value))
        )

    lower = _PROSE_GE_RE.search(text)
    if lower is not None:
        value = int(lower.group(1) or lower.group(2))
        candidates.append(
            ProseBounds(comparator=PROSE_GE, strikes=(value,), closed_interval=(value, None))
        )

    if len(candidates) != 1:
        return None
    return candidates[0]


def slug_closed_interval(bounds: tuple[tuple[str, int], ...]) -> ClosedInterval | None:
    """Corroborating reading of the slug, or ``None`` for an unobserved family.

    Demoted from primary to cross-check by G-19 B6. Only the three families in
    ``_OBSERVED_SLUG_FAMILIES`` decode; everything else -- an ``lte`` token the
    venue has never emitted, a bare ``gt``, a reversed or wider range -- returns
    ``None`` so the gate refuses instead of extrapolating a comparator rule that
    the corpus shows does not exist.
    """
    family = tuple(comparator for comparator, _ in bounds)
    if family not in _OBSERVED_SLUG_FAMILIES:
        return None
    values = [value for _, value in bounds]
    if family == ("lt",):
        return None, values[0] - 1
    if family == ("gte",):
        return values[0], None
    return values[0], values[1]


def assert_bounds_cross_checked(
    weather: WeatherSlug,
    *,
    description: str | None,
    title: str | None,
    reading_is_whole_degrees: bool,
) -> ClosedInterval:
    """Derive the bounds from the venue's PROSE, corroborated by the slug.

    This is a REFUSAL GATE, not settlement logic: it reads no observation,
    decides no outcome, and computes no payoff.

    G-19 B6 inverted the precedence here. The venue's ``description``/``title``
    are now the source of the strike and the comparator; the slug's verbatim
    tokens only have to AGREE. Previously the slug was primary and the prose
    merely cross-checked it, which refused 455 of the 680 captured markets --
    not because the venue was ambiguous but because the inferred grammar read
    ``lt`` with a fixed offset it does not have.

    Three independent things must hold, and all three are checked:

    1. ``reading_is_whole_degrees`` must be ``True``. The identity
       ``lt N == lte N-1`` collapses the moment the settlement reading carries
       a fraction, and this repo has already met fractional and
       record-qualifier NWS temperatures. The caller asserts the assumption
       explicitly, at the call site, in the traceback.
    2. The venue must state an interval this adapter can read, in
       ``description`` or ``title``. Where both are readable they must agree.
    3. The slug's bound segment must belong to an observed family and must
       decode to the same interval the venue states.

    Returns
    -------
    ClosedInterval
        The corroborated ``(lower, upper)`` inclusive bounds, either end
        ``None`` for an open side. Returned rather than discarded so a consumer
        has a *verified* value and no reason to re-derive one from the raw
        comparator.

    Raises
    ------
    BoundsSemanticsError
        If the whole-degree assumption is not asserted, if neither prose field
        is readable, if the two fields disagree, if the slug's family is one
        the venue has never emitted, or if slug and prose disagree. The refusal
        deliberately carries no candidate interval when the prose is missing:
        there is nothing for a caller to salvage, because the slug alone is not
        an authority on the comparator.
    """
    if not reading_is_whole_degrees:
        raise BoundsSemanticsError(
            f"Refusing to interpret bounds {weather.raw_bounds!r} of {weather.slug!r}: "
            "the venue's stated threshold can only be read as an integer interval when "
            "the settlement reading is a whole degree. A fractional or record-qualifier "
            "reading makes 'lt N' and 'lte N-1' different contracts."
        )

    from_description = parse_prose_bounds(description)
    from_title = parse_prose_bounds(title)
    if (
        from_description is not None
        and from_title is not None
        and from_description.closed_interval != from_title.closed_interval
    ):
        raise BoundsSemanticsError(
            f"Venue description and title disagree for {weather.slug!r}: description "
            f"reads {from_description.closed_interval}, title reads "
            f"{from_title.closed_interval}."
        )

    from_prose: ProseBounds
    if from_description is not None:
        from_prose = from_description
    elif from_title is not None:
        from_prose = from_title
    else:
        raise BoundsSemanticsError(
            f"Refusing to interpret bounds {weather.raw_bounds!r} of {weather.slug!r}: "
            "neither the venue description nor the title states a threshold this "
            "adapter can read, so the bounds cannot be corroborated. The slug is NOT "
            "consulted as a fallback -- its 'lt' token means '<= N-1' standalone and "
            "'<= N' inside a range, so it cannot decide a comparator on its own."
        )

    from_slug = slug_closed_interval(weather.bounds)
    if from_slug is None:
        raise BoundsSemanticsError(
            f"Bounds {weather.raw_bounds!r} of {weather.slug!r} use a comparator family "
            f"{tuple(c for c, _ in weather.bounds)!r} that has never been observed in a "
            "captured Polymarket.us market. Refusing to extrapolate a comparator rule "
            "onto an unobserved slug shape; capture the market and re-derive the "
            "grammar before trading it."
        )
    if from_slug != from_prose.closed_interval:
        raise BoundsSemanticsError(
            f"Bounds {weather.raw_bounds!r} of {weather.slug!r} are not corroborated by "
            f"the venue's own words: the slug decodes to {from_slug}, the venue states "
            f"{from_prose.closed_interval} ({from_prose.comparator} "
            f"{from_prose.strikes}). The venue's words govern -- do NOT treat '<' and "
            "'<=' as interchangeable here; re-derive the slug grammar before using "
            "this market for settlement."
        )
    return from_prose.closed_interval


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
