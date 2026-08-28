"""Cross-city rejection evidence: registry `body_header_regex` patterns.

One NWS office issues CLI products for multiple cities under an
identical `issuingOffice` (KOKX -> NYC+JFK+LGA+EWR; KLOT -> MDW+ORD;
KMTR -> SFO+OAK+SJC; KMFL -> MIA+FLL+APF; KLOX -> LAX+BUR+LGB). The
per-city `body_header_regex` in `sites.toml` is the ONLY guard that
catches a same-office sibling product silently being attributed to the
wrong station. This test proves each site's regex rejects every OTHER
site's real product header -- using the five headers actually extracted
by `parse_cli_product` from live fixtures, and reading the patterns from
the registry itself (never copied into this file) so the test exercises
the production pattern, not a duplicate.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Any, cast

import pytest

from breezy.normalize.cli_parse import parse_cli_product

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "nws"
SITES_TOML = (
    Path(__file__).resolve().parent.parent.parent / "src" / "breezy" / "registry" / "sites.toml"
)

CITY_FIXTURE_DIRS = {
    "NYC": "nyc_final_2026-08-21",
    "SFO": "sfo_final_2026-08-21",
    "MIA": "mia_final_2026-08-21",
    "MDW": "mdw_final_2026-08-21",
    "LAX": "lax_final_2026-08-21",
}


def _load_text(dirname: str) -> str:
    return (FIXTURES_DIR / dirname / "product.txt").read_text()


def _load_sites() -> dict[str, dict[str, Any]]:
    with SITES_TOML.open("rb") as handle:
        data = tomllib.load(handle)
    # tomllib.load returns dict[str, Any]; the nested chain below is
    # genuinely Any until we assert the shape at this parsing boundary.
    return cast("dict[str, dict[str, Any]]", data["sites"]["polymarket_us"])


@pytest.fixture(scope="module")
def sites() -> dict[str, dict[str, Any]]:
    return _load_sites()


@pytest.fixture(scope="module")
def station_header_lines(sites: dict[str, dict[str, Any]]) -> dict[str, str]:
    """Each city's real station header line, extracted via its OWN registry
    regex (i.e. each fixture is confirmed self-consistent first).
    """
    headers = {}
    for city, fixture_dir in CITY_FIXTURE_DIRS.items():
        body_header_regex = re.compile(sites[city]["body_header_regex"], re.MULTILINE)
        parsed = parse_cli_product(
            _load_text(fixture_dir), cli_location=city, body_header_regex=body_header_regex
        )
        headers[city] = parsed.station_header_line
    return headers


@pytest.mark.parametrize("city", ["NYC", "SFO", "MIA", "MDW", "LAX"])
def test_body_header_regex_rejects_every_other_city(
    city: str, sites: dict[str, dict[str, Any]], station_header_lines: dict[str, str]
) -> None:
    own_regex = sites[city]["body_header_regex"]

    for other_city, header_line in station_header_lines.items():
        if other_city == city:
            continue
        assert re.match(own_regex, header_line) is None, (
            f"{city}'s body_header_regex matched {other_city}'s real product "
            f"header {header_line!r} -- the cross-office collision guard failed"
        )
