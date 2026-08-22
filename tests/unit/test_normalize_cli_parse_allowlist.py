"""Tests for the structural pre-parse allowlist in breezy.normalize.cli_parse.

Plan Sec 2.5 requires a structural allowlist -- line count, line length,
WMO header shape, AWIPS PIL == CLI{loc} -- applied BEFORE any expensive
regex touches the product body. This matters because Phase 1 parses
inline on the asyncio event loop: a slow (not necessarily catastrophic)
parse on a malformed product stalls the entire Nautilus event loop, not
just ingestion. The allowlist must reject cheaply, first, and with the
same fail-closed CliParseError discipline as the rest of the module.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from breezy.normalize.cli_parse import CliParseError, parse_cli_product

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "nws"
NYC_HEADER_REGEX = re.compile(
    r"^\.\.\.THE\s+CENTRAL\s+PARK\s+NY\s+CLIMATE\s+SUMMARY\s+FOR\b", re.MULTILINE
)

_VALID_BODY = (
    "\n"
    "000\n"
    "CDUS41 KOKX 220626\n"
    "CLINYC\n"
    "\n"
    "CLIMATE REPORT \n"
    "NATIONAL WEATHER SERVICE NEW YORK, NY\n"
    "226 AM EDT SAT AUG 22 2026\n"
    "\n"
    "...THE CENTRAL PARK NY CLIMATE SUMMARY FOR AUGUST 21 2026...\n"
    "\n"
    "TEMPERATURE (F)\n"
    " YESTERDAY\n"
    "  MAXIMUM         79    301 PM  96    1955  83     -4       72\n"
    "  MINIMUM         63    424 AM  53    1922  69     -6       59\n"
    "  AVERAGE         71                        76     -5       66\n"
    "\n"
    "PRECIPITATION (IN)\n"
)


def _load(name: str) -> str:
    return (FIXTURES_DIR / name / "product.txt").read_text()


def test_real_fixtures_parse_cleanly_through_the_allowlist() -> None:
    """The allowlist must never reject a genuine, real CLI product."""
    parse_cli_product(
        _load("nyc_final_2026-08-21"), cli_location="NYC", body_header_regex=NYC_HEADER_REGEX
    )
    parse_cli_product(
        _load("nyc_preliminary_2026-08-21"), cli_location="NYC", body_header_regex=NYC_HEADER_REGEX
    )


def test_hand_built_valid_body_parses_cleanly() -> None:
    result = parse_cli_product(_VALID_BODY, cli_location="NYC", body_header_regex=NYC_HEADER_REGEX)
    assert result.summary_date.isoformat() == "2026-08-21"


def test_allowlist_rejects_excessive_line_count() -> None:
    pathological = "X\n" * 5000
    with pytest.raises(CliParseError, match="line"):
        parse_cli_product(pathological, cli_location="NYC", body_header_regex=NYC_HEADER_REGEX)


def test_allowlist_rejects_excessive_line_length() -> None:
    pathological = "000\n" + ("A" * 100_000) + "\nCDUS41 KOKX 220626\nCLINYC\n"
    with pytest.raises(CliParseError, match="line"):
        parse_cli_product(pathological, cli_location="NYC", body_header_regex=NYC_HEADER_REGEX)


def test_allowlist_rejects_missing_transmission_indicator() -> None:
    bad = _VALID_BODY.replace("\n000\n", "\nNOT000\n")
    with pytest.raises(CliParseError, match="transmission indicator"):
        parse_cli_product(bad, cli_location="NYC", body_header_regex=NYC_HEADER_REGEX)


def test_allowlist_rejects_malformed_wmo_heading() -> None:
    bad = _VALID_BODY.replace("CDUS41 KOKX 220626", "NOT A WMO HEADING AT ALL")
    with pytest.raises(CliParseError, match="WMO"):
        parse_cli_product(bad, cli_location="NYC", body_header_regex=NYC_HEADER_REGEX)


def test_allowlist_rejects_wmo_heading_with_lowercase() -> None:
    bad = _VALID_BODY.replace("CDUS41 KOKX 220626", "cdus41 kokx 220626")
    with pytest.raises(CliParseError, match="WMO"):
        parse_cli_product(bad, cli_location="NYC", body_header_regex=NYC_HEADER_REGEX)


def test_allowlist_accepts_wmo_heading_with_correction_bbb_token() -> None:
    """A CCA/CCB correction suffix on the WMO heading is a legitimate shape,
    not a structural violation (see nyc_correction_synthetic fixture).
    """
    result = parse_cli_product(
        _load("nyc_correction_synthetic_2026-08-21"),
        cli_location="NYC",
        body_header_regex=NYC_HEADER_REGEX,
    )
    assert result.summary_date.isoformat() == "2026-08-21"


def test_allowlist_rejects_pil_mismatch_for_sibling_station() -> None:
    """A KOKX product for JFK carrying PIL CLIJFK must be rejected when the
    caller expects cli_location='NYC' -- this is the same-office sibling
    guard, now enforced structurally in addition to the header-text guard.
    """
    sibling = _VALID_BODY.replace("CLINYC", "CLIJFK")
    with pytest.raises(CliParseError, match="AWIPS PIL"):
        parse_cli_product(sibling, cli_location="NYC", body_header_regex=NYC_HEADER_REGEX)


def test_allowlist_rejects_clm_monthly_product_structurally() -> None:
    """A monthly CLM product carries a different PIL (CLM{loc}, not
    CLI{loc}) and must be rejected by the structural allowlist -- not
    merely excluded by never being fetched.
    """
    monthly = _VALID_BODY.replace("CLINYC", "CLMNYC")
    with pytest.raises(CliParseError, match="AWIPS PIL"):
        parse_cli_product(monthly, cli_location="NYC", body_header_regex=NYC_HEADER_REGEX)


def test_allowlist_rejects_body_too_short_to_contain_a_header() -> None:
    with pytest.raises(CliParseError):
        parse_cli_product("000\nCDUS41\n", cli_location="NYC", body_header_regex=NYC_HEADER_REGEX)


def test_allowlist_runs_before_the_headline_regex() -> None:
    """A body with a perfectly valid NYC headline but a structurally wrong
    PIL must be rejected for the STRUCTURAL reason, proving the allowlist
    gate runs first rather than falling through to headline extraction.
    """
    wrong_pil_valid_headline = _VALID_BODY.replace("CLINYC", "CLIEWR")
    with pytest.raises(CliParseError, match="AWIPS PIL"):
        parse_cli_product(
            wrong_pil_valid_headline, cli_location="NYC", body_header_regex=NYC_HEADER_REGEX
        )
