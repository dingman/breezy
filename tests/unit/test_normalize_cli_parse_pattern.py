"""`body_header_regex` is a compiled pattern, used exactly as given.

The registry hands out `SettlementSite.body_header_regex` as a
`Pattern[str]` compiled with `re.MULTILINE`. Passing that pattern's
`.pattern` source string and re-matching recompiles it WITHOUT the flag.

That is behaviourally equivalent for the single-line, `^`-anchored
patterns in `sites.toml` today -- which is precisely what makes it
dangerous. It is a silent flag discard, and the day someone writes a
multi-line pattern it fails looking like a data problem rather than a
code problem.

Note on how the flag discard is PROVEN below: `re.MULTILINE` is not
observable through `.match()` against a single-line header, so a
MULTILINE-based assertion could pass against a buggy implementation.
`re.IGNORECASE` is observable through the same code path and is used as
the probe. The property under test is "the caller's compiled object is
used as given, flags included", not IGNORECASE specifically.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Any

import pytest

from breezy.normalize.cli_parse import parse_cli_product

SITES_TOML = (
    Path(__file__).resolve().parents[2] / "src" / "breezy" / "registry" / "sites.toml"
)
VALID_NYC_PREFIX = "\n000\nCDUS41 KOKX 220626\nCLINYC\n"


def _body(site_phrase: str) -> str:
    return (
        VALID_NYC_PREFIX
        + f"...THE {site_phrase} CLIMATE SUMMARY FOR AUGUST 21 2026...\n"
        "TEMPERATURE (F)\n YESTERDAY\n  MAXIMUM 79\n  MINIMUM 63\n  AVERAGE 71\n\n"
        "PRECIPITATION (IN)\n"
    )


def test_compiled_pattern_flags_are_honoured() -> None:
    """A pattern compiled with IGNORECASE must match a mixed-case header.

    Under the old implementation the pattern's source string was
    recompiled with no flags, so this match would fail -- the flag was
    silently discarded.
    """
    case_insensitive = re.compile(r"^\.\.\.THE\s+CENTRAL\s+PARK\s+NY\s+CLIMATE", re.IGNORECASE)

    result = parse_cli_product(
        _body("central park ny"),
        cli_location="NYC",
        body_header_regex=case_insensitive,
    )

    assert result.station_header_line == (
        "...THE central park ny CLIMATE SUMMARY FOR AUGUST 21 2026..."
    )


def test_pattern_without_the_flag_still_rejects() -> None:
    """The control for the test above: the same source string compiled
    WITHOUT IGNORECASE must reject the mixed-case header, proving the
    previous test measured the flag and not something else.
    """
    case_sensitive = re.compile(r"^\.\.\.THE\s+CENTRAL\s+PARK\s+NY\s+CLIMATE")

    with pytest.raises(ValueError):
        parse_cli_product(
            _body("central park ny"),
            cli_location="NYC",
            body_header_regex=case_sensitive,
        )


def test_passing_a_source_string_is_rejected_loudly() -> None:
    """`site.body_header_regex.pattern` is the exact call shape that
    discarded the flag. It must fail as a programming defect (TypeError),
    not be silently accepted, and not be mistaken for a data problem
    (`CliParseError`) by a caller's `except` clause.
    """
    with pytest.raises(TypeError, match="compiled"):
        parse_cli_product(
            _body("CENTRAL PARK NY"),
            cli_location="NYC",
            body_header_regex=r"^\.\.\.THE\s+CENTRAL\s+PARK\s+NY\b",  # type: ignore[arg-type]
        )


def test_type_error_is_not_a_value_error() -> None:
    """A caller that routes every `ValueError` to the settlement gate must
    not have a coding defect laundered into a data-quality reason code.
    """
    assert not issubclass(TypeError, ValueError)


@pytest.mark.parametrize("city", ["NYC", "SFO", "MIA", "MDW", "LAX"])
def test_registry_patterns_are_accepted_as_compiled_objects(city: str) -> None:
    """The real registry patterns, compiled the way the registry compiles
    them (MULTILINE), are accepted unchanged.
    """
    with SITES_TOML.open("rb") as handle:
        data: dict[str, Any] = tomllib.load(handle)
    pattern = re.compile(data["sites"]["polymarket_us"][city]["body_header_regex"], re.MULTILINE)

    fixture_dir = {
        "NYC": "nyc_final_2026-08-21",
        "SFO": "sfo_final_2026-08-21",
        "MIA": "mia_final_2026-08-21",
        "MDW": "mdw_final_2026-08-21",
        "LAX": "lax_final_2026-08-21",
    }[city]
    text = (
        Path(__file__).resolve().parent.parent / "fixtures" / "nws" / fixture_dir / "product.txt"
    ).read_text()

    result = parse_cli_product(text, cli_location=city, body_header_regex=pattern)

    assert pattern.match(result.station_header_line) is not None
