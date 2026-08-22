"""Multi-station CLI products: name the assumption instead of implying it.

`nws-cli-settlement` lists "Multi-station CLIs in one product (section
splitting required)" as a known NWS parsing hazard. `cli_parse.py` uses
`.search()` -- FIRST MATCH ONLY -- for both the headline and the
TEMPERATURE (F) block, which implicitly assumes the PIL-gated body carries
exactly one station's data.

Five real products from five different WFOs were captured during Phase 1
and none was multi-station, so this is a RESIDUAL hazard rather than a
live one. That is precisely why it needs a test that says plainly what the
parser does, rather than an unwritten assumption that a future reader has
to reconstruct from two `.search()` calls.

Three shapes, three different consequences, all pinned here:

1. OUR section first, a sibling second
   -> parsed, from OUR section. Correct: `body_header_regex` already
      proved the first headline is ours.

2. A sibling first, OUR section second
   -> `CliContentError`. The parser does NOT go looking for our section
      further down the body. This is a deliberate fail-closed limitation,
      not an oversight: see `test_..._is_rejected_rather_than_searched`.

3. OUR section first but carrying NO temperature block, a sibling second
   WITH one
   -> `CliContentError`. Before the fix this suite drove, the parser
      silently paired OUR headline with the SIBLING's temperatures and
      returned a fully-populated, entirely wrong settlement value.
      See `test_..._never_pairs_our_headline_with_a_sibling_block`.
"""

from __future__ import annotations

import re

import pytest

from breezy.normalize.cli_parse import CliContentError, parse_cli_product

NYC_HEADER_REGEX = re.compile(
    r"^\.\.\.THE\s+CENTRAL\s+PARK\s+NY\s+CLIMATE\s+SUMMARY\s+FOR\b", re.MULTILINE
)

_TRANSMISSION_HEADER = (
    "\n"
    "000\n"
    "CDUS41 KOKX 220626\n"
    "CLINYC\n"
    "\n"
    "CLIMATE REPORT \n"
    "NATIONAL WEATHER SERVICE NEW YORK, NY\n"
    "226 AM EDT SAT AUG 22 2026\n"
    "\n"
)

_OURS = "CENTRAL PARK NY"
_SIBLING = "JFK INTERNATIONAL AIRPORT NY"
"""KOKX issues NYC + JFK + LGA + EWR under one `issuingOffice`, so a
sibling section is the realistic contaminant, not a far-away station."""


def _section(site: str, *, tmax: int, tmin: int, tavg: int, with_temperatures: bool = True) -> str:
    """One station's CLI section, terminated by the AWIPS ``$$`` marker."""
    body = f"...THE {site} CLIMATE SUMMARY FOR AUGUST 21 2026...\n\n"
    if with_temperatures:
        body += (
            "TEMPERATURE (F)\n"
            " YESTERDAY\n"
            f"  MAXIMUM         {tmax}    301 PM  96    1955  83     -4       72\n"
            f"  MINIMUM         {tmin}    424 AM  53    1922  69     -6       59\n"
            f"  AVERAGE         {tavg}                        76     -5       66\n"
            "\n"
            "PRECIPITATION (IN)\n"
            "  YESTERDAY        T\n"
        )
    else:
        # A section that carries no TEMPERATURE (F) block at all. Unusual,
        # but it is the shape that turns "first match only" into a
        # cross-section mis-pairing, so it is the shape worth pinning.
        body += "WIND (MPH)\n  HIGHEST WIND SPEED    13\n"
    body += "\n$$\n\n"
    return body


def test_our_section_first_parses_our_values_not_the_siblings() -> None:
    """The benign shape. `body_header_regex` guarantees the FIRST headline
    is ours, so "first match only" lands on the right section -- and the
    values must come from that section, never from the one after it.
    """
    text = (
        _TRANSMISSION_HEADER
        + _section(_OURS, tmax=79, tmin=63, tavg=71)
        + _section(_SIBLING, tmax=95, tmin=80, tavg=88)
    )

    result = parse_cli_product(text, cli_location="NYC", body_header_regex=NYC_HEADER_REGEX)

    assert result.station_header_line.startswith(f"...THE {_OURS}")
    assert (result.tmax.value_f, result.tmin.value_f, result.tavg.value_f) == (79, 63, 71)


def test_sibling_section_first_is_rejected_rather_than_searched() -> None:
    """DOCUMENTED LIMITATION, deliberately fail-closed.

    When a multi-station body leads with a sibling station, the parser does
    NOT scan on for our section -- it reads the first headline, finds it
    contradicts `body_header_regex`, and refuses the whole product.

    That is the correct default while multi-station bodies remain
    unobserved for our five cities: the alternative (scan until a headline
    matches) would silently start trusting section-boundary detection that
    has never been exercised against a real product. If NWS ever
    collectivises our cities into one product, this raises loudly and
    ingestion stops -- it does not settle the wrong number.
    """
    text = (
        _TRANSMISSION_HEADER
        + _section(_SIBLING, tmax=95, tmin=80, tavg=88)
        + _section(_OURS, tmax=79, tmin=63, tavg=71)
    )

    with pytest.raises(CliContentError, match="does not match the expected body_header_regex"):
        parse_cli_product(text, cli_location="NYC", body_header_regex=NYC_HEADER_REGEX)


def test_multi_station_body_never_pairs_our_headline_with_a_sibling_block() -> None:
    """THE WRONG-STATION SETTLEMENT BUG this suite was written to catch.

    Our section leads (so the PIL check and `body_header_regex` both pass)
    but carries no TEMPERATURE (F) block. The temperature search used to
    run over the WHOLE product text, so it walked past our section into the
    sibling's and returned JFK's 95/80/88 under Central Park's headline --
    silently, with no error, fully populated.

    `cli_parse.py`'s own module docstring says "a silent partial parse is a
    wrong settlement". This was worse than partial: it was a complete,
    confident, wrong answer. Refusing is the only acceptable behaviour.
    """
    text = (
        _TRANSMISSION_HEADER
        + _section(_OURS, tmax=0, tmin=0, tavg=0, with_temperatures=False)
        + _section(_SIBLING, tmax=95, tmin=80, tavg=88)
    )

    with pytest.raises(CliContentError, match="TEMPERATURE"):
        parse_cli_product(text, cli_location="NYC", body_header_regex=NYC_HEADER_REGEX)


def test_temperature_block_before_our_headline_is_not_used() -> None:
    """The mirror image: a TEMPERATURE (F) block sitting AHEAD of our
    headline (a malformed body, or a preamble) must not be adopted either.
    The block is bound to the section our headline opens, on both sides.
    """
    stray_block = (
        "TEMPERATURE (F)\n"
        " YESTERDAY\n"
        "  MAXIMUM         95    301 PM  96    1955  83     -4       72\n"
        "  MINIMUM         80    424 AM  53    1922  69     -6       59\n"
        "  AVERAGE         88                        76     -5       66\n"
        "\n"
        "PRECIPITATION (IN)\n"
        "\n"
    )
    text = _TRANSMISSION_HEADER + stray_block + _section(_OURS, tmax=79, tmin=63, tavg=71)

    result = parse_cli_product(text, cli_location="NYC", body_header_regex=NYC_HEADER_REGEX)

    assert (result.tmax.value_f, result.tmin.value_f, result.tavg.value_f) == (79, 63, 71)


def test_single_station_real_shape_is_unaffected_by_section_scoping() -> None:
    """Regression guard for the scoping fix: an ordinary single-station
    body has no following headline, so the section runs to end-of-text and
    parses exactly as it always did.
    """
    text = _TRANSMISSION_HEADER + _section(_OURS, tmax=79, tmin=63, tavg=71)

    result = parse_cli_product(text, cli_location="NYC", body_header_regex=NYC_HEADER_REGEX)

    assert (result.tmax.value_f, result.tmin.value_f, result.tavg.value_f) == (79, 63, 71)
