"""The parser surfaces the header facts it already validated.

`check_structural_allowlist` inspects lines 2-3 of every product to
validate the WMO abbreviated heading and to assert the AWIPS PIL equals
``CLI{cli_location}``. Downstream provenance needs BOTH the AWIPS PIL and
the WMO ``BBB`` correction token (``CCA``/``CCB``/... -- the primary
correction signal, and one api.weather.gov does not expose as a field).

Before this suite, the parser threw both away and the caller had to
re-scan text the parser had already parsed. Two independent scans of the
same bytes for the same facts will eventually disagree, and the fact they
would disagree about is "was this product a correction?" -- a
supersession decision on an already-settled climate day.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from breezy.normalize.cli_parse import (
    CliStructuralHeader,
    check_structural_allowlist,
    parse_cli_product,
)

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "nws"
NYC_HEADER_REGEX = re.compile(
    r"^\.\.\.THE\s+CENTRAL\s+PARK\s+NY\s+CLIMATE\s+SUMMARY\s+FOR\b", re.MULTILINE
)


def _load(name: str) -> str:
    return (FIXTURES_DIR / name / "product.txt").read_text()


def test_awips_pil_is_surfaced_from_the_real_final_fixture() -> None:
    result = parse_cli_product(
        _load("nyc_final_2026-08-21"), cli_location="NYC", body_header_regex=NYC_HEADER_REGEX
    )

    assert result.awips_pil == "CLINYC"


def test_bbb_token_is_none_when_the_product_is_not_a_correction() -> None:
    """Absence must be an explicit `None`, never an empty string: a caller
    testing truthiness on `""` and on `None` behaves the same, but a
    caller round-tripping the field through Arrow does not.
    """
    result = parse_cli_product(
        _load("nyc_final_2026-08-21"), cli_location="NYC", body_header_regex=NYC_HEADER_REGEX
    )

    assert result.wmo_bbb is None


def test_bbb_token_is_surfaced_for_a_corrected_product() -> None:
    """`CDUS41 KOKX 220626 CCA` -- the CCA token is the WMO correction
    signal. api.weather.gov does not expose a BBB field, so the raw
    heading line is the only place it exists.
    """
    result = parse_cli_product(
        _load("nyc_correction_synthetic_2026-08-21"),
        cli_location="NYC",
        body_header_regex=NYC_HEADER_REGEX,
    )

    assert result.wmo_bbb == "CCA"
    assert result.awips_pil == "CLINYC"


@pytest.mark.parametrize(
    ("fixture", "cli_location", "expected_pil"),
    [
        ("nyc_final_2026-08-21", "NYC", "CLINYC"),
        ("sfo_final_2026-08-21", "SFO", "CLISFO"),
        ("mia_final_2026-08-21", "MIA", "CLIMIA"),
        ("mdw_final_2026-08-21", "MDW", "CLIMDW"),
        ("lax_final_2026-08-21", "LAX", "CLILAX"),
    ],
)
def test_every_city_fixture_surfaces_its_own_pil(
    fixture: str, cli_location: str, expected_pil: str
) -> None:
    header = check_structural_allowlist(_load(fixture), cli_location=cli_location)

    assert header.awips_pil == expected_pil
    assert header.wmo_bbb is None


def test_structural_allowlist_returns_the_header_it_validated() -> None:
    """The single-scan guarantee: the object the caller reads its
    provenance from is the same object the gate check was performed on.
    """
    header = check_structural_allowlist(
        _load("nyc_correction_synthetic_2026-08-21"), cli_location="NYC"
    )

    assert isinstance(header, CliStructuralHeader)
    assert header == CliStructuralHeader(awips_pil="CLINYC", wmo_bbb="CCA")


def test_parsed_product_and_standalone_allowlist_agree() -> None:
    """The two entry points must never disagree -- that is the whole
    reason the facts are returned rather than re-scanned.
    """
    text = _load("nyc_correction_synthetic_2026-08-21")

    header = check_structural_allowlist(text, cli_location="NYC")
    parsed = parse_cli_product(
        text, cli_location="NYC", body_header_regex=NYC_HEADER_REGEX
    )

    assert (parsed.awips_pil, parsed.wmo_bbb) == (header.awips_pil, header.wmo_bbb)


def test_existing_fields_are_unchanged() -> None:
    """Additive change: nothing existing was removed or renamed."""
    result = parse_cli_product(
        _load("nyc_final_2026-08-21"), cli_location="NYC", body_header_regex=NYC_HEADER_REGEX
    )

    assert result.summary_date.isoformat() == "2026-08-21"
    assert result.station_header_line.startswith("...THE CENTRAL PARK NY")
    assert result.tmax.value_f == 79
    assert result.tmin.value_f == 63
    assert result.tavg.value_f == 71
