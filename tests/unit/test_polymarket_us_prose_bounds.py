"""G-19 B6: the venue's own prose is the PRIMARY source of strike and comparator.

The slug bound segment (``lt79``, ``gte80lt81``) encodes a comparator whose
meaning was INFERRED, never documented -- ``polymarket-us-integration`` records
the weather slug grammar as UNRESOLVED. Getting ``<`` versus ``<=`` wrong on a
temperature threshold silently flips a winner into a loser at exactly one
degree, which is the boundary where nearly all of the risk sits.

Every market, slug, title and description exercised here is read out of the
committed captures under ``docs/evidence/venue/polymarket_us/raw/`` by a
RECURSIVE walk. Markets appear both at the top level and nested under
``events[].markets[]``; a top-level-only scan sees ~45 of them and a recursive
walk sees 729 observations across 680 distinct slugs. Nothing here is invented.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from itertools import pairwise
from pathlib import Path
from typing import Any, NamedTuple

import pytest

from breezy.adapters.polymarket_us.errors import BoundsSemanticsError
from breezy.adapters.polymarket_us.symbology import (
    PROSE_BETWEEN,
    PROSE_GE,
    PROSE_LE,
    ProseBounds,
    assert_bounds_cross_checked,
    parse_prose_bounds,
    parse_weather_slug,
    slug_closed_interval,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW = REPO_ROOT / "docs" / "evidence" / "venue" / "polymarket_us" / "raw"

#: Floors that keep every corpus-driven assertion below from passing vacuously.
#: Measured on the committed captures: 729 observations, 680 distinct slugs,
#: 114 distinct (city, measure, climate-date) bucket ladders.
MIN_OBSERVATIONS = 700
MIN_DISTINCT_SLUGS = 650
MIN_LADDERS = 100


class CapturedMarket(NamedTuple):
    """One captured market payload, reduced to the fields this seam reads."""

    slug: str
    title: str
    title_short: str
    question: str
    description: str
    sort_order: int


def _walk(node: Any) -> Iterator[CapturedMarket]:
    if isinstance(node, dict):
        slug = node.get("slug")
        if isinstance(slug, str) and slug.startswith("tc-temp-") and "description" in node:
            yield CapturedMarket(
                slug=slug,
                title=str(node.get("title", "")),
                title_short=str(node.get("titleShort", "")),
                question=str(node.get("question", "")),
                description=str(node.get("description", "")),
                sort_order=int(node.get("sortOrder", -1)),
            )
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value)


def captured_observations() -> list[CapturedMarket]:
    """Every weather-market observation in the corpus, duplicates included.

    Globbed, never a frozen file list: a newly committed capture must be picked
    up automatically, because a capture that silently escapes these checks is
    exactly the regression this module exists to catch.
    """
    found: list[CapturedMarket] = []
    for path in sorted(RAW.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        found.extend(_walk(payload))
    return found


def captured_markets() -> list[CapturedMarket]:
    """One record per distinct slug, first observation wins."""
    by_slug: dict[str, CapturedMarket] = {}
    for market in captured_observations():
        by_slug.setdefault(market.slug, market)
    return [by_slug[slug] for slug in sorted(by_slug)]


# ---------------------------------------------------------------------------
# Non-vacuity
# ---------------------------------------------------------------------------


def test_the_recursive_walk_reaches_the_nested_event_markets() -> None:
    """A top-level-only scan finds ~45 markets; the real corpus is far larger."""
    observations = captured_observations()
    markets = captured_markets()

    assert len(observations) >= MIN_OBSERVATIONS, (
        f"only {len(observations)} observations found -- the walk is probably not "
        "recursing into events[].markets[]"
    )
    assert len(markets) >= MIN_DISTINCT_SLUGS


# ---------------------------------------------------------------------------
# The comparator vocabulary is CLOSED and derived from the corpus
# ---------------------------------------------------------------------------


def test_the_only_prose_comparators_in_the_corpus_are_the_three_we_parse() -> None:
    """Enumerated before the parser was designed; refuse anything unobserved.

    A fourth spelling appearing in a future capture must fail here rather than
    be silently dropped by a parser that only knows three.
    """
    seen: set[str] = set()
    for market in captured_markets():
        parsed = parse_prose_bounds(market.description)
        assert parsed is not None, f"unreadable venue description for {market.slug}"
        seen.add(parsed.comparator)

    assert seen == {PROSE_LE, PROSE_GE, PROSE_BETWEEN}


def test_every_captured_description_and_title_is_parseable() -> None:
    """No market may fall through to the "prose absent" branch on real data."""
    for market in captured_markets():
        assert parse_prose_bounds(market.description) is not None, market.slug
        assert parse_prose_bounds(market.title) is not None, market.slug
        assert parse_prose_bounds(market.title_short) is not None, market.slug


@pytest.mark.parametrize(
    ("text", "comparator", "strikes", "interval"),
    [
        # description spellings, both unit variants, verbatim from the corpus
        ("... be less than or equal to 78F? Outcome verified", PROSE_LE, (78,), (None, 78)),
        ("... be less than or equal to 79°F? Outcome verified", PROSE_LE, (79,), (None, 79)),
        ("... be greater than or equal to 88F? Outcome verified", PROSE_GE, (88,), (88, None)),
        ("... be greater than or equal to 64°F? Outcome", PROSE_GE, (64,), (64, None)),
        ("... be between 80F and 81F? Outcome verified", PROSE_BETWEEN, (80, 81), (80, 81)),
        (
            "... be between 64°F and 65°F? Outcome verified",
            PROSE_BETWEEN,
            (64, 65),
            (64, 65),
        ),
        # title / titleShort spellings
        ("78 or below", PROSE_LE, (78,), (None, 78)),
        ("78° or below", PROSE_LE, (78,), (None, 78)),
        ("88 or above", PROSE_GE, (88,), (88, None)),
        ("88° or above", PROSE_GE, (88,), (88, None)),
        ("80 to 81", PROSE_BETWEEN, (80, 81), (80, 81)),
        ("64° to 65°", PROSE_BETWEEN, (64, 65), (64, 65)),
    ],
)
def test_prose_forms_parse_to_their_stated_strike_and_comparator(
    text: str,
    comparator: str,
    strikes: tuple[int, ...],
    interval: tuple[int | None, int | None],
) -> None:
    parsed = parse_prose_bounds(text)

    assert parsed == ProseBounds(
        comparator=comparator, strikes=strikes, closed_interval=interval
    )


# ---------------------------------------------------------------------------
# THE FINDING: the slug's `lt` token is CONTEXT DEPENDENT
# ---------------------------------------------------------------------------


def test_the_lt_token_means_a_different_bound_standalone_than_inside_a_range() -> None:
    """The single most important assertion in this module.

    ``lt80f`` standalone is titled "79 or below" -- ``lt N`` behaving as
    ``<= N-1``, the ordinary strict reading. But ``gte80lt81f`` is titled
    "80 to 81", where the very same ``lt`` token contributes an INCLUSIVE upper
    bound of 81, not 80. One comparator algebra cannot produce both, which is
    precisely why the slug may not be the primary source.
    """
    standalone = parse_prose_bounds("79 or below")
    ranged = parse_prose_bounds("80 to 81")
    assert standalone is not None and ranged is not None

    # Same literal token `lt80` / `lt81`, two different offsets from the number.
    assert standalone.closed_interval == (None, 79)  # lt80 -> upper 79  (offset -1)
    assert ranged.closed_interval == (80, 81)  # lt81 -> upper 81  (offset  0)

    # And the observed slug table must encode exactly that context dependence.
    assert slug_closed_interval((("lt", 80),)) == (None, 79)
    assert slug_closed_interval((("gte", 80), ("lt", 81))) == (80, 81)


def test_the_prose_ladder_tiles_the_temperature_line_and_the_literal_slug_never_does() -> None:
    """The evidence that settles the ``lt`` question, corpus-wide.

    For each (city, measure, climate date) the venue publishes a bucket ladder.
    Under the venue's prose the buckets tile the whole-degree line with no gap
    and no overlap. Under a naive strict reading of the slug (``lt N`` always
    ``<= N-1``) every other degree belongs to no bucket at all -- an impossible
    market, since some day would settle to a temperature no contract covers.
    """
    ladders: dict[tuple[str, str], list[tuple[int, int | None, int | None]]] = {}
    for market in captured_markets():
        weather = parse_weather_slug(market.slug)
        assert weather is not None, market.slug
        prose = parse_prose_bounds(market.description)
        assert prose is not None, market.slug
        key = (weather.city + weather.measure, weather.climate_date)
        lower, upper = prose.closed_interval
        ladders.setdefault(key, []).append((market.sort_order, lower, upper))

    assert len(ladders) >= MIN_LADDERS

    def contiguous(buckets: list[tuple[int, int | None, int | None]]) -> bool:
        ordered = sorted(buckets, key=lambda b: (b[1] is not None, b[1] if b[1] else -999))
        for (_, _, upper), (_, lower, _) in pairwise(ordered):
            if upper is None or lower is None or lower != upper + 1:
                return False
        return True

    gapped = [key for key, buckets in ladders.items() if not contiguous(buckets)]
    assert gapped == [], f"prose ladders are not contiguous for {gapped[:3]}"

    # Now the naive strict reading, on the same ladders: it must fail everywhere.
    naive_ok = 0
    naive_ladders: dict[tuple[str, str], list[tuple[int, int | None, int | None]]] = {}
    for market in captured_markets():
        weather = parse_weather_slug(market.slug)
        assert weather is not None
        lower_n: int | None = None
        upper_n: int | None = None
        for comparator, value in weather.bounds:
            if comparator == "lt":
                upper_n = value - 1
            elif comparator == "gte":
                lower_n = value
        key = (weather.city + weather.measure, weather.climate_date)
        naive_ladders.setdefault(key, []).append((market.sort_order, lower_n, upper_n))
    for buckets in naive_ladders.values():
        if contiguous(buckets):
            naive_ok += 1
    assert naive_ok == 0, (
        f"{naive_ok} ladders tile under the naive strict slug reading -- the "
        "context dependence of `lt` may have changed and must be re-derived"
    )


def test_lt79_and_lte78_describe_the_same_half_line_but_lte_is_never_emitted() -> None:
    """The brief's explicit question, answered from the captures.

    ``tc-temp-nychigh-2026-08-25-lt79f`` carries title "78 or below" and the
    description "less than or equal to 78F". So YES: for the STANDALONE family,
    ``lt79`` and a hypothetical ``lte78`` denote the same closed half-line
    ``(-inf, 78]`` under a whole-degree reading.

    But ``lte`` is never actually emitted by the venue. It appears in this
    adapter's inherited token regex and in prose about the grammar, never in a
    captured slug. Asserted so nobody reasons from a token the venue does not
    use.
    """
    markets = captured_markets()
    assert [m.slug for m in markets if "lte" in m.slug] == []

    target = next(m for m in markets if m.slug == "tc-temp-nychigh-2026-08-25-lt79f")
    assert target.title == "78 or below"
    assert "less than or equal to 78F" in target.description

    weather = parse_weather_slug(target.slug)
    assert weather is not None
    assert weather.bounds == (("lt", 79),)
    assert slug_closed_interval(weather.bounds) == (None, 78)

    from_prose = parse_prose_bounds(target.description)
    assert from_prose is not None
    assert from_prose.closed_interval == (None, 78)


# ---------------------------------------------------------------------------
# Prose PRIMARY, slug corroborating -- over the whole real corpus
# ---------------------------------------------------------------------------


def test_prose_derived_bounds_agree_with_the_slug_for_every_captured_market() -> None:
    """The corpus test. Every market, prose primary, slug corroborating.

    This is what the inverted design buys: under the previous slug-primary
    reading 455 of 680 captured markets were REFUSED by the cross-check.
    """
    checked = 0
    for market in captured_markets():
        weather = parse_weather_slug(market.slug)
        assert weather is not None, market.slug
        verified = assert_bounds_cross_checked(
            weather,
            description=market.description,
            title=market.title,
            reading_is_whole_degrees=True,
        )
        prose = parse_prose_bounds(market.description)
        assert prose is not None
        assert verified == prose.closed_interval
        checked += 1

    assert checked >= MIN_DISTINCT_SLUGS


def test_the_verified_interval_actually_varies_with_the_market() -> None:
    """Anti-constant guard: a stubbed implementation must not satisfy the corpus test."""
    intervals = set()
    for market in captured_markets():
        weather = parse_weather_slug(market.slug)
        assert weather is not None
        intervals.add(
            assert_bounds_cross_checked(
                weather,
                description=market.description,
                title=market.title,
                reading_is_whole_degrees=True,
            )
        )
    assert len(intervals) > 50


def test_each_slug_family_maps_to_a_distinct_prose_comparator() -> None:
    """All three families are exercised by the corpus, in real volume."""
    families: dict[tuple[str, ...], set[str]] = {}
    counts: dict[tuple[str, ...], int] = {}
    for market in captured_markets():
        weather = parse_weather_slug(market.slug)
        assert weather is not None
        prose = parse_prose_bounds(market.description)
        assert prose is not None
        family = tuple(comparator for comparator, _ in weather.bounds)
        families.setdefault(family, set()).add(prose.comparator)
        counts[family] = counts.get(family, 0) + 1

    assert families == {
        ("lt",): {PROSE_LE},
        ("gte",): {PROSE_GE},
        ("gte", "lt"): {PROSE_BETWEEN},
    }
    for family, count in counts.items():
        assert count >= 100, f"family {family} only seen {count} times"


# ---------------------------------------------------------------------------
# Failing loudly
# ---------------------------------------------------------------------------


def test_a_prose_slug_disagreement_raises_loudly() -> None:
    """Synthetic disagreement: real slug, prose moved by one degree."""
    weather = parse_weather_slug("tc-temp-nychigh-2026-08-25-lt79f")
    assert weather is not None

    with pytest.raises(BoundsSemanticsError, match="not corroborated"):
        assert_bounds_cross_checked(
            weather,
            description="... be less than or equal to 77F?",
            title="77 or below",
            reading_is_whole_degrees=True,
        )


def test_a_description_title_disagreement_raises_loudly() -> None:
    weather = parse_weather_slug("tc-temp-nychigh-2026-08-25-lt79f")
    assert weather is not None

    with pytest.raises(BoundsSemanticsError, match="disagree"):
        assert_bounds_cross_checked(
            weather,
            description="... be less than or equal to 78F?",
            title="77 or below",
            reading_is_whole_degrees=True,
        )


def test_absent_prose_refuses_and_never_falls_back_to_the_inferred_grammar() -> None:
    """The decided behaviour, and the reason it is not a fallback.

    The slug grammar is not merely UNVERIFIED, it is KNOWN CONTEXT DEPENDENT:
    the same ``lt`` token means ``<= N-1`` standalone and ``<= N`` inside a
    range. Falling back to it would be falling back to a reading that is
    provably wrong for 455 of 680 captured markets. So an absent or unreadable
    prose is a refusal, and the refusal must not leak a slug-derived value.
    """
    weather = parse_weather_slug("tc-temp-laxhigh-2026-08-24-gte80lt81f")
    assert weather is not None

    with pytest.raises(BoundsSemanticsError, match="cannot be corroborated") as excinfo:
        assert_bounds_cross_checked(
            weather,
            description=None,
            title="   ",
            reading_is_whole_degrees=True,
        )
    # Nothing that looks like a decided interval may appear in the refusal.
    assert "(80, 81)" not in str(excinfo.value)
    assert "(80, 80)" not in str(excinfo.value)


def test_unreadable_prose_refuses_rather_than_guessing() -> None:
    weather = parse_weather_slug("tc-temp-laxhigh-2026-08-24-gte80lt81f")
    assert weather is not None

    with pytest.raises(BoundsSemanticsError, match="cannot be corroborated"):
        assert_bounds_cross_checked(
            weather,
            description="Settlement terms to be announced.",
            title="TBD",
            reading_is_whole_degrees=True,
        )


def test_an_unobserved_slug_family_is_refused_rather_than_extrapolated() -> None:
    """``lte`` and wide ranges are unobserved; the table must not extrapolate."""
    assert slug_closed_interval((("lte", 78),)) is None
    assert slug_closed_interval((("gt", 78),)) is None
    assert slug_closed_interval((("lt", 80), ("gte", 78))) is None  # wrong order


def test_the_whole_degree_assumption_is_still_required_at_the_call_site() -> None:
    """Unchanged and load-bearing: the identity collapses on a fractional reading."""
    weather = parse_weather_slug("tc-temp-nychigh-2026-08-25-lt79f")
    assert weather is not None

    with pytest.raises(BoundsSemanticsError, match="whole degree"):
        assert_bounds_cross_checked(
            weather,
            description="... be less than or equal to 78F?",
            title="78 or below",
            reading_is_whole_degrees=False,
        )


def test_the_gate_never_rewrites_the_verbatim_slug_bounds() -> None:
    weather = parse_weather_slug("tc-temp-laxhigh-2026-08-24-gte80lt81f")
    assert weather is not None

    assert_bounds_cross_checked(
        weather,
        description="... be between 80F and 81F?",
        title="80 to 81",
        reading_is_whole_degrees=True,
    )

    assert weather.bounds == (("gte", 80), ("lt", 81))
    assert weather.raw_bounds == "gte80lt81f"


def test_a_title_only_market_is_still_corroborated() -> None:
    weather = parse_weather_slug("tc-temp-laxhigh-2026-08-24-gte88f")
    assert weather is not None

    assert (
        assert_bounds_cross_checked(
            weather,
            description=None,
            title="88 or above",
            reading_is_whole_degrees=True,
        )
        == (88, None)
    )


def test_prose_parsing_ignores_the_climate_date_digits_in_the_description() -> None:
    """``for 2026-08-25`` sits before the comparator clause and must not be read."""
    parsed = parse_prose_bounds(
        "Will the highest temperature recorded at Central Park (KNYC) in New York "
        "City for 2026-08-25 as reported by the National Weather Service's "
        "Climatological Report (Daily) be less than or equal to 78F? Outcome "
        "verified from NWS Climatological Report."
    )

    assert parsed is not None
    assert parsed.strikes == (78,)
    assert parsed.closed_interval == (None, 78)


def test_the_april_vintage_descriptions_without_an_icao_still_parse() -> None:
    """38 captured descriptions carry no parenthetical ICAO; phrasing differs."""
    without_icao = [
        market
        for market in captured_markets()
        if not re.search(r"\(K[A-Z]{3}\)", market.description)
    ]
    assert len(without_icao) >= 20

    for market in without_icao:
        parsed = parse_prose_bounds(market.description)
        assert parsed is not None, market.description
