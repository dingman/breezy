"""Cross-office format-drift evidence for breezy.normalize.cli_parse.

Phase 1 only trades NYC, but the parser's regexes had -- until this test
-- only ever been exercised against KOKX (NYC) text. This module proves
`parse_cli_product` extracts the correct tmax/tmin/tavg from a REAL,
live-captured CLI product for each of the other four Polymarket.us
cities, issued by four different WFOs (KMTR, KMFL, KLOT, KLOX). Each
site's `body_header_regex` is read from the registry (`sites.toml`), not
copied into this file, so this test exercises the actual production
pattern.

Finding: all four offices render the CLIMATE SUMMARY headline and the
TEMPERATURE (F) / YESTERDAY block in the SAME structural shape NYC uses
(only the observed-time column format varies -- e.g. "2:19 PM" at KMTR
vs "301 PM" at KOKX -- which the parser never reads). All four fixtures
parsed cleanly with the existing regexes; no format drift was found that
the hand-rolled parser could not handle.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Any, cast

import pytest

from breezy.normalize.cli_parse import parse_cli_product
from breezy.normalize.units import TemperatureReadingF

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "nws"
SITES_TOML = (
    Path(__file__).resolve().parent.parent.parent / "src" / "breezy" / "registry" / "sites.toml"
)


def _load_text(dirname: str) -> str:
    return (FIXTURES_DIR / dirname / "product.txt").read_text()


def _load_sites() -> dict[str, dict[str, Any]]:
    with SITES_TOML.open("rb") as handle:
        data = tomllib.load(handle)
    # tomllib.load returns dict[str, Any]; the nested chain below is
    # genuinely Any until we assert the shape at this parsing boundary.
    return cast("dict[str, dict[str, Any]]", data["sites"]["polymarket_us"])


CITY_CASES = [
    # (registry city key, fixture dirname, tmax, tmin, tavg)
    ("SFO", "sfo_final_2026-08-21", 68, 58, 63),
    ("MIA", "mia_final_2026-08-21", 94, 81, 88),
    ("MDW", "mdw_final_2026-08-21", 80, 62, 71),
    ("LAX", "lax_final_2026-08-21", 83, 69, 76),
]


@pytest.mark.parametrize(("city", "fixture_dir", "tmax", "tmin", "tavg"), CITY_CASES)
def test_parse_real_fixture_for_each_remaining_city(
    city: str, fixture_dir: str, tmax: int, tmin: int, tavg: int
) -> None:
    sites = _load_sites()
    body_header_regex = re.compile(sites[city]["body_header_regex"], re.MULTILINE)

    result = parse_cli_product(
        _load_text(fixture_dir), cli_location=city, body_header_regex=body_header_regex
    )

    assert result.tmax == TemperatureReadingF(value_f=tmax, sentinel="NONE")
    assert result.tmin == TemperatureReadingF(value_f=tmin, sentinel="NONE")
    assert result.tavg == TemperatureReadingF(value_f=tavg, sentinel="NONE")
