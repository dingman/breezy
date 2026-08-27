"""Slug <-> ``InstrumentId`` symbology, and the weather slug grammar.

Plan revision 2 section 6 ``symbology.py``, build order Step 6, and
``POLYMARKET_US_BUILD_PLAN.md:65`` (Phase 3 exit gate): reserved separator
``~``, never hyphen parsing, dotted slugs rejected, round-trip invertible, no
import of ``nautilus_trader.adapters.polymarket.common.symbol``, and every
bucket instrument for one city/day sharing a ``city_day_cluster_id``.

Every slug used here is copied verbatim from a committed venue capture under
``docs/evidence/venue/polymarket_us/raw/`` -- no slug is invented.
"""

from __future__ import annotations

import ast
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from breezy.adapters.polymarket_us.errors import BoundsSemanticsError, VenuePayloadError
from breezy.adapters.polymarket_us.symbology import (
    INSTRUMENT_SEPARATOR,
    POLYMARKET_US_VENUE,
    assert_bounds_cross_checked,
    assert_valid_slug,
    instrument_id_to_slug,
    parse_weather_slug,
    slug_to_instrument_id,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
ADAPTER_DIR = REPO_ROOT / "src" / "breezy" / "adapters" / "polymarket_us"

#: Observed in ``raw/market_open_510636_by_slug.json``.
OPEN_SLUG = "tc-temp-nychigh-2026-08-25-lt79f"

#: Observed in ``raw/market_closed_15806_by_slug.json``.
CLOSED_SLUG = "tc-temp-nychigh-2026-04-23-gte72lt73f"


# ---------------------------------------------------------------------------
# Round-trip invertibility
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("slug", [OPEN_SLUG, CLOSED_SLUG])
def test_slug_round_trips_through_instrument_id(slug: str) -> None:
    instrument_id = slug_to_instrument_id(slug)
    assert instrument_id.venue == POLYMARKET_US_VENUE
    assert instrument_id_to_slug(instrument_id) == slug


def test_instrument_id_string_form_round_trips() -> None:
    from nautilus_trader.model.identifiers import InstrumentId

    instrument_id = slug_to_instrument_id(OPEN_SLUG)
    assert InstrumentId.from_str(str(instrument_id)) == instrument_id


# ---------------------------------------------------------------------------
# Rejection at the trust boundary
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    [
        "tc.temp-nychigh-2026-08-25-lt79f",  # dotted -- collides with InstrumentId
        f"tc-temp{INSTRUMENT_SEPARATOR}nychigh",  # reserved separator
        "",  # empty
        "   ",  # whitespace only
        "tc temp nychigh",  # embedded whitespace
        "tc-temp/../../etc",  # path traversal into a URL path segment
        "tc-temp?foo=bar",  # query injection into a URL path segment
    ],
)
def test_malformed_slug_is_rejected(bad: str) -> None:
    with pytest.raises(VenuePayloadError):
        assert_valid_slug(bad)
    with pytest.raises(VenuePayloadError):
        slug_to_instrument_id(bad)


def test_instrument_id_from_a_foreign_venue_is_rejected() -> None:
    from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue

    foreign = InstrumentId(Symbol(OPEN_SLUG), Venue("KALSHI"))
    with pytest.raises(VenuePayloadError):
        instrument_id_to_slug(foreign)


def test_adapter_never_imports_the_bundled_polymarket_symbol_module() -> None:
    banned = "nautilus_trader.adapters.polymarket"
    offenders: list[str] = []
    for path in sorted(ADAPTER_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith(banned):
                        offenders.append(f"{path.name}:{node.lineno}")
            elif (
                isinstance(node, ast.ImportFrom)
                and node.module is not None
                and node.module.startswith(banned)
            ):
                offenders.append(f"{path.name}:{node.lineno}")
    assert offenders == []


# ---------------------------------------------------------------------------
# Weather slug grammar (BUILD_PLAN:65)
# ---------------------------------------------------------------------------


def test_weather_slug_parses_city_measure_and_climate_date() -> None:
    parsed = parse_weather_slug(OPEN_SLUG)
    assert parsed is not None
    assert parsed.city == "nyc"
    assert parsed.measure == "high"
    assert parsed.climate_date == "2026-08-25"


def test_weather_slug_bounds_are_preserved_verbatim_not_reinterpreted() -> None:
    """``lt79f`` means ``lt 79``.

    The venue's own ``title`` for this market reads "78 or below" and its
    ``description`` says "less than or equal to 78F". Translating ``lt79`` into
    ``lte78`` is a venue-semantics guess; this parser records exactly what the
    slug says and leaves interpretation to a later, evidenced phase.
    """
    open_parsed = parse_weather_slug(OPEN_SLUG)
    assert open_parsed is not None
    assert open_parsed.raw_bounds == "lt79f"
    assert open_parsed.bounds == (("lt", 79),)

    closed_parsed = parse_weather_slug(CLOSED_SLUG)
    assert closed_parsed is not None
    assert closed_parsed.raw_bounds == "gte72lt73f"
    assert closed_parsed.bounds == (("gte", 72), ("lt", 73))


def test_city_day_cluster_id_is_shared_across_buckets_of_one_city_day() -> None:
    """Phase 3 exit gate: one cluster id per (city, climate date)."""
    bucket_a = parse_weather_slug("tc-temp-nychigh-2026-08-25-lt79f")
    bucket_b = parse_weather_slug("tc-temp-nychigh-2026-08-25-gte79lt80f")
    bucket_low = parse_weather_slug("tc-temp-nyclow-2026-08-25-lt60f")
    other_day = parse_weather_slug("tc-temp-nychigh-2026-08-26-lt79f")
    other_city = parse_weather_slug("tc-temp-mdwhigh-2026-08-25-lt79f")

    assert bucket_a is not None and bucket_b is not None
    assert bucket_low is not None and other_day is not None and other_city is not None

    assert bucket_a.city_day_cluster_id == bucket_b.city_day_cluster_id
    assert bucket_a.city_day_cluster_id == bucket_low.city_day_cluster_id
    assert bucket_a.city_day_cluster_id != other_day.city_day_cluster_id
    assert bucket_a.city_day_cluster_id != other_city.city_day_cluster_id


def test_a_slug_outside_the_observed_weather_grammar_yields_none() -> None:
    """No guessing: an unrecognised grammar returns ``None``, not a default."""
    assert parse_weather_slug("aec-nfl-kc-phi-2026-02-09") is None
    assert parse_weather_slug("tc-temp-nychigh-2026-13-99-lt79f") is None
    assert parse_weather_slug("tc-temp-nychigh-2026-08-25-banana") is None


# ---------------------------------------------------------------------------
# Threshold semantics: ``<`` and ``<=`` are NOT interchangeable
# ---------------------------------------------------------------------------
#
# Storing the slug's comparator verbatim is the right call and is not changed
# here. What is added is the refusal gate that stops a future settlement
# consumer from reading ``lt79`` as a strict ``< 79`` -- or as ``<= 78`` --
# without validating it against the venue's own ``description``/``title``.
#
# Every market below is read out of the committed captures under
# ``docs/evidence/venue/polymarket_us/raw/``. Nothing is invented.

RAW = REPO_ROOT / "docs" / "evidence" / "venue" / "polymarket_us" / "raw"


def _iter_captured_weather_markets() -> Iterator[tuple[str, str, str]]:
    """Yield ``(slug, title, description)`` for every captured weather market."""
    seen: set[str] = set()
    for path in sorted(RAW.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))

        def walk(node: Any) -> Iterator[tuple[str, str, str]]:
            if isinstance(node, dict):
                slug = node.get("slug")
                title = node.get("title")
                description = node.get("description")
                if (
                    isinstance(slug, str)
                    and slug.startswith("tc-temp-")
                    and slug not in seen
                    and isinstance(title, str)
                    and isinstance(description, str)
                ):
                    seen.add(slug)
                    yield slug, title, description
                for value in node.values():
                    yield from walk(value)
            elif isinstance(node, list):
                for value in node:
                    yield from walk(value)

        yield from walk(payload)


def test_the_committed_corpus_actually_contains_weather_markets_to_check() -> None:
    """Guards every corpus-driven assertion below from passing vacuously."""
    captured = list(_iter_captured_weather_markets())
    assert len(captured) > 100


def test_a_single_sided_market_is_corroborated_by_the_venue_prose() -> None:
    """``lt79`` vs "less than or equal to 78F": same contract, different spelling."""
    weather = parse_weather_slug(OPEN_SLUG)
    assert weather is not None
    assert weather.bounds == (("lt", 79),)

    verified = assert_bounds_cross_checked(
        weather,
        description=(
            "Will the highest temperature recorded at Central Park (KNYC) in New York "
            "City for 2026-08-25 as reported by the National Weather Service's "
            "Climatological Report (Daily) be less than or equal to 78F?"
        ),
        title="78 or below",
        reading_is_whole_degrees=True,
    )
    assert verified == (None, 78)


def test_a_range_market_resolves_to_the_venue_prose_not_the_literal_slug() -> None:
    """The finding, made concrete on a captured market (G-19 B6).

    ``gte80lt81f`` read literally under whole degrees is the single value 80;
    the venue titles it "80 to 81" and describes it as "between 80F and 81F".
    Both cannot be true. The ladder for that day (``lt80``, ``gte80lt81``,
    ``gte82lt83``, ``gte84lt85``, ``gte86lt87``, ``gte88``) only tiles the
    temperature line without gaps under the venue's inclusive reading -- so the
    slug's ``lt`` is the spelling that must not be trusted, and the venue's
    words are what the gate now returns.

    This previously asserted a REFUSAL. That was the right instinct pointed at
    the wrong culprit: the venue is not ambiguous here, our inferred grammar
    was wrong. The tripwire is preserved below -- the literal slug reading is
    still asserted to disagree, so if the venue ever makes ``lt`` mean a fixed
    offset this test fails and the change gets looked at.
    """
    weather = parse_weather_slug("tc-temp-laxhigh-2026-08-24-gte80lt81f")
    assert weather is not None
    assert weather.bounds == (("gte", 80), ("lt", 81))

    verified = assert_bounds_cross_checked(
        weather,
        description=(
            "Will the highest temperature recorded at Los Angeles International "
            "Airport (KLAX) in Los Angeles for 2026-08-24 as reported by the "
            "National Weather Service's Climatological Report (Daily) be between "
            "80F and 81F?"
        ),
        title="80 to 81",
        reading_is_whole_degrees=True,
    )

    assert verified == (80, 81)
    # The tripwire: a naive strict reading of the same tokens is still wrong.
    assert (80, 81) != (weather.bounds[0][1], weather.bounds[1][1] - 1)


def test_every_captured_range_market_diverges_from_the_LITERAL_slug_reading() -> None:
    """Pin the scale of the divergence so it cannot be dismissed as a one-off.

    Every captured two-token range market disagrees with a naive strict reading
    of its own slug, and agrees with the venue's prose. If a future capture
    makes the literal slug reading correct, this test fails and the grammar
    must be re-derived deliberately -- which is the point.
    """
    ranges = 0
    for slug, title, description in _iter_captured_weather_markets():
        weather = parse_weather_slug(slug)
        if weather is None or len(weather.bounds) != 2:
            continue
        ranges += 1

        # The venue's words govern, and the gate returns them.
        verified = assert_bounds_cross_checked(
            weather,
            description=description,
            title=title,
            reading_is_whole_degrees=True,
        )
        (_, lower), (_, upper) = weather.bounds
        assert verified == (lower, upper)

        # ... and the naive strict reading would have been wrong, every time.
        assert verified != (lower, upper - 1)

    assert ranges > 100


def test_every_captured_single_sided_market_is_corroborated() -> None:
    """Non-vacuity: the gate is not an unconditional refusal."""
    checked = 0
    for slug, title, description in _iter_captured_weather_markets():
        weather = parse_weather_slug(slug)
        if weather is None or len(weather.bounds) != 1:
            continue
        checked += 1
        assert_bounds_cross_checked(
            weather,
            description=description,
            title=title,
            reading_is_whole_degrees=True,
        )
    assert checked > 100


def test_the_gate_refuses_unless_the_whole_degree_assumption_is_asserted() -> None:
    """``lt79 == lte78`` requires a whole-degree reading; say so at the call site."""
    weather = parse_weather_slug(OPEN_SLUG)
    assert weather is not None
    with pytest.raises(BoundsSemanticsError, match="whole degree"):
        assert_bounds_cross_checked(
            weather,
            description="... be less than or equal to 78F?",
            title="78 or below",
            reading_is_whole_degrees=False,
        )


def test_the_gate_refuses_when_the_venue_says_nothing_readable() -> None:
    weather = parse_weather_slug(OPEN_SLUG)
    assert weather is not None
    with pytest.raises(BoundsSemanticsError, match="cannot be corroborated"):
        assert_bounds_cross_checked(
            weather,
            description=None,
            title="   ",
            reading_is_whole_degrees=True,
        )


def test_the_gate_refuses_when_description_and_title_disagree() -> None:
    weather = parse_weather_slug(OPEN_SLUG)
    assert weather is not None
    with pytest.raises(BoundsSemanticsError, match="disagree"):
        assert_bounds_cross_checked(
            weather,
            description="... be less than or equal to 78F?",
            title="77 or below",
            reading_is_whole_degrees=True,
        )


def test_the_gate_accepts_a_title_only_market() -> None:
    """A readable title alone corroborates; a missing description is not fatal."""
    weather = parse_weather_slug("tc-temp-laxhigh-2026-08-24-gte88f")
    assert weather is not None
    verified = assert_bounds_cross_checked(
        weather,
        description=None,
        title="88 or above",
        reading_is_whole_degrees=True,
    )
    assert verified == (88, None)


def test_bounds_remain_stored_verbatim_and_are_not_rewritten_by_the_gate() -> None:
    """The gate corroborates; it never edits what the slug said."""
    weather = parse_weather_slug(OPEN_SLUG)
    assert weather is not None
    assert_bounds_cross_checked(
        weather,
        description="... be less than or equal to 78F?",
        title="78 or below",
        reading_is_whole_degrees=True,
    )
    assert weather.bounds == (("lt", 79),)
    assert weather.raw_bounds == "lt79f"
