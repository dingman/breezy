"""Tests for breezy.normalize.cli_parse.

Extracts, from verbatim CLI product text: the headline summary_date
(never issuanceTime), the station/site header line, tmax/tmin/tavg in
degrees F with sentinel flags preserved (never imputed), and rejects
ambiguous/unparseable products explicitly rather than returning a
partially-populated result.
"""

from __future__ import annotations

import hashlib
import re
from datetime import date
from pathlib import Path

import pytest

from breezy.normalize import cli_parse
from breezy.normalize.classify import classify_issuance
from breezy.normalize.cli_parse import (
    CliNotOurProductError,
    CliParseError,
    CliStructuralError,
    check_structural_allowlist,
    parse_cli_product,
    parse_temperature_token,
)
from breezy.normalize.units import TemperatureReadingF

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "nws"
CLI_EQUIVALENCE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "cli_equivalence"
NYC_HEADER_REGEX = re.compile(
    r"^\.\.\.THE\s+CENTRAL\s+PARK\s+NY\s+CLIMATE\s+SUMMARY\s+FOR\b", re.MULTILINE
)
MIA_HEADER_REGEX = re.compile(
    r"^\.\.\.THE\s+MIAMI\s+CLIMATE\s+SUMMARY\s+FOR\b", re.MULTILINE
)

# A minimal WMO/AWIPS prefix that satisfies the structural allowlist
# (line count/length, "000" indicator, WMO heading shape, PIL == CLINYC)
# so hand-built test bodies below reach the specific downstream check
# each test targets, rather than being rejected earlier by the gate.
_VALID_NYC_PREFIX = "\n000\nCDUS41 KOKX 220626\nCLINYC\n"


def _load(name: str) -> str:
    return (FIXTURES_DIR / name / "product.txt").read_text()


def _load_cli_equivalence_bytes(name: str) -> bytes:
    return (CLI_EQUIVALENCE_DIR / name).read_bytes()


def _with_transmission_sequence(text: str, sequence: str) -> str:
    lines = text.split("\n")
    lines[1] = sequence
    return "\n".join(lines)


def _valid_nyc_body_with_sequence(sequence: str) -> str:
    return _with_transmission_sequence(
        _VALID_NYC_PREFIX
        + "...THE CENTRAL PARK NY CLIMATE SUMMARY FOR AUGUST 21 2026...\n"
        "TEMPERATURE (F)\n"
        " YESTERDAY\n"
        "  MAXIMUM         79\n"
        "  MINIMUM         63\n"
        "  AVERAGE         71\n"
        "\n"
        "PRECIPITATION (IN)\n",
        sequence,
    )


def test_summary_date_from_headline_not_issuance_time() -> None:
    """Both fixtures share climate day 2026-08-21, even though their
    issuanceTime values (in meta.json: 2026-08-21T20:44Z preliminary,
    2026-08-22T06:26Z final) span two different UTC calendar dates.
    A bug that derived summary_date from issuanceTime's date component
    would get the final wrong (2026-08-22 instead of 2026-08-21).
    """
    preliminary = parse_cli_product(
        _load("nyc_preliminary_2026-08-21"),
        cli_location="NYC",
        body_header_regex=NYC_HEADER_REGEX,
    )
    final = parse_cli_product(
        _load("nyc_final_2026-08-21"), cli_location="NYC", body_header_regex=NYC_HEADER_REGEX
    )

    assert preliminary.summary_date == date(2026, 8, 21)
    assert final.summary_date == date(2026, 8, 21)


def test_parse_real_final_fixture_matches_expected() -> None:
    result = parse_cli_product(
        _load("nyc_final_2026-08-21"), cli_location="NYC", body_header_regex=NYC_HEADER_REGEX
    )

    assert (
        result.station_header_line
        == "...THE CENTRAL PARK NY CLIMATE SUMMARY FOR AUGUST 21 2026..."
    )
    assert result.tmax == TemperatureReadingF(value_f=79, sentinel="NONE")
    assert result.tmin == TemperatureReadingF(value_f=63, sentinel="NONE")
    assert result.tavg == TemperatureReadingF(value_f=71, sentinel="NONE")


def test_parse_real_preliminary_fixture_matches_expected() -> None:
    result = parse_cli_product(
        _load("nyc_preliminary_2026-08-21"),
        cli_location="NYC",
        body_header_regex=NYC_HEADER_REGEX,
    )

    assert result.tmax == TemperatureReadingF(value_f=79, sentinel="NONE")
    assert result.tmin == TemperatureReadingF(value_f=63, sentinel="NONE")
    assert result.tavg == TemperatureReadingF(value_f=71, sentinel="NONE")


def test_live_and_archive_cli_equivalence_fixture_parse_identically() -> None:
    live_bytes = _load_cli_equivalence_bytes("MIA_20260824_live.txt")
    archive_bytes = _load_cli_equivalence_bytes("MIA_20260824_archive.txt")
    assert (
        hashlib.sha256(live_bytes).hexdigest()
        == "5107e7fb9cd56d2ee49b3cad302dee76f72a0e9f42c7f1b4ebec988ea5dac87f"
    )
    assert (
        hashlib.sha256(archive_bytes).hexdigest()
        == "fd57ce50dea7295624651e7034f9a4de84843b0974439f43cc391fa9ce9627a7"
    )
    # These digests are byte-level provenance, so the inequality is correct:
    # the live API normalized the sequence to 000 while the archive preserved 100.
    assert hashlib.sha256(live_bytes).digest() != hashlib.sha256(archive_bytes).digest()

    live_text = live_bytes.decode()
    archive_text = archive_bytes.decode()

    live = parse_cli_product(
        live_text,
        cli_location="MIA",
        body_header_regex=MIA_HEADER_REGEX,
    )
    archive = parse_cli_product(
        archive_text,
        cli_location="MIA",
        body_header_regex=MIA_HEADER_REGEX,
    )

    assert live == archive
    assert classify_issuance(live_text) == classify_issuance(archive_text)
    assert live.is_correction_bbb == archive.is_correction_bbb


@pytest.mark.parametrize("sequence", ["000", "100", "507", "487"])
def test_structural_allowlist_accepts_digits_only_transmission_sequences(sequence: str) -> None:
    header = check_structural_allowlist(
        _valid_nyc_body_with_sequence(sequence),
        cli_location="NYC",
    )

    assert header.wmo_transmission_sequence == sequence


@pytest.mark.parametrize("sequence", ["", "   ", "5O7", "O00", "123456789"])
def test_structural_allowlist_refuses_invalid_transmission_sequences(sequence: str) -> None:
    with pytest.raises(CliStructuralError, match="transmission indicator"):
        check_structural_allowlist(
            _valid_nyc_body_with_sequence(sequence),
            cli_location="NYC",
        )


def test_transmission_sequence_pattern_refuses_embedded_newline() -> None:
    # A `$` anchor would match before this trailing newline. Keep this pinned
    # even though the current line split plus strip path masks the case.
    assert cli_parse._WMO_TRANSMISSION_SEQUENCE_RE.match("507\n") is None


def test_structural_header_carries_live_and_archive_transmission_sequences() -> None:
    live = _load_cli_equivalence_bytes("MIA_20260824_live.txt").decode()
    archive = _load_cli_equivalence_bytes("MIA_20260824_archive.txt").decode()

    live_header = check_structural_allowlist(live, cli_location="MIA")
    archive_header = check_structural_allowlist(archive, cli_location="MIA")

    assert live_header.wmo_transmission_sequence == "000"
    assert archive_header.wmo_transmission_sequence == "100"


def test_sibling_station_still_refused_by_pil_after_sequence_widening() -> None:
    sibling = _valid_nyc_body_with_sequence("507").replace("CLINYC", "CLIJFK", 1)

    with pytest.raises(CliNotOurProductError):
        parse_cli_product(sibling, cli_location="NYC", body_header_regex=NYC_HEADER_REGEX)


def test_temperature_extraction_anchors_to_yesterday_not_normal_or_record() -> None:
    """Real CLI products carry the YESTERDAY (observed) row alongside RECORD
    and NORMAL values inline in the SAME row (as trailing columns) -- but a
    naive "first MAXIMUM in the block" search is still vulnerable to any
    product that renders NORMAL/RECORD as their OWN labeled sub-rows ahead of
    YESTERDAY. This fixture models that ordering explicitly: NORMAL and
    RECORD sub-blocks, each with their own MAXIMUM/MINIMUM lines carrying
    decoy values, appear BEFORE the YESTERDAY sub-block. Extraction must
    still return the YESTERDAY (observed) values, never the first match in
    the block.
    """
    text = (
        _VALID_NYC_PREFIX
        + "...THE CENTRAL PARK NY CLIMATE SUMMARY FOR AUGUST 21 2026...\n"
        "TEMPERATURE (F)\n"
        " NORMAL\n"
        "  MAXIMUM         83\n"
        "  MINIMUM         68\n"
        " RECORD\n"
        "  MAXIMUM         96    1955\n"
        "  MINIMUM         53    1922\n"
        " YESTERDAY\n"
        "  MAXIMUM         79    301 PM  96    1955  83     -4       72\n"
        "  MINIMUM         63    424 AM  53    1922  69     -6       59\n"
        "  AVERAGE         71                        76     -5       66\n"
        "\n"
        "PRECIPITATION (IN)\n"
    )

    result = parse_cli_product(text, cli_location="NYC", body_header_regex=NYC_HEADER_REGEX)

    assert result.tmax == TemperatureReadingF(value_f=79, sentinel="NONE")
    assert result.tmin == TemperatureReadingF(value_f=63, sentinel="NONE")
    assert result.tavg == TemperatureReadingF(value_f=71, sentinel="NONE")


def test_temperature_extraction_anchors_to_today_for_preliminary() -> None:
    """The preliminary issuance uses a TODAY sub-block instead of YESTERDAY;
    the anchor must recognize both labels as the observed-value subsection.
    """
    text = (
        _VALID_NYC_PREFIX
        + "...THE CENTRAL PARK NY CLIMATE SUMMARY FOR AUGUST 21 2026...\n"
        "VALID TODAY AS OF 0400 PM LOCAL TIME.\n"
        "TEMPERATURE (F)\n"
        " NORMAL\n"
        "  MAXIMUM         83\n"
        "  MINIMUM         68\n"
        " TODAY\n"
        "  MAXIMUM         79    259 PM  96    1955  83     -4       72\n"
        "  MINIMUM         63    424 AM  53    1922  69     -6       59\n"
        "  AVERAGE         71                        76     -5       66\n"
        "\n"
        "PRECIPITATION (IN)\n"
    )

    result = parse_cli_product(text, cli_location="NYC", body_header_regex=NYC_HEADER_REGEX)

    assert result.tmax == TemperatureReadingF(value_f=79, sentinel="NONE")
    assert result.tmin == TemperatureReadingF(value_f=63, sentinel="NONE")


def test_ambiguous_product_rejected_when_no_observed_subsection_found() -> None:
    """A TEMPERATURE (F) block with only NORMAL/RECORD rows and no
    YESTERDAY/TODAY observed subsection must reject, never fall back to a
    NORMAL or RECORD value as if it were observed.
    """
    text = (
        _VALID_NYC_PREFIX
        + "...THE CENTRAL PARK NY CLIMATE SUMMARY FOR AUGUST 21 2026...\n"
        "TEMPERATURE (F)\n"
        " NORMAL\n"
        "  MAXIMUM         83\n"
        "  MINIMUM         68\n"
        "\n"
        "PRECIPITATION (IN)\n"
    )
    with pytest.raises(CliParseError):
        parse_cli_product(text, cli_location="NYC", body_header_regex=NYC_HEADER_REGEX)


def test_sentinel_flags_are_preserved_not_imputed() -> None:
    result = parse_cli_product(
        _load("nyc_sentinel_synthetic"), cli_location="NYC", body_header_regex=NYC_HEADER_REGEX
    )

    assert result.tmax.value_f is None
    assert result.tmax.sentinel == "M"
    assert result.tmin.value_f is None
    assert result.tmin.sentinel == "T"
    assert result.tavg.value_f is None
    assert result.tavg.sentinel == "MS"


@pytest.mark.parametrize(
    ("token", "expected"),
    [
        ("79", TemperatureReadingF(value_f=79, sentinel="NONE")),
        ("-3", TemperatureReadingF(value_f=-3, sentinel="NONE")),
        ("0", TemperatureReadingF(value_f=0, sentinel="NONE")),
        ("M", TemperatureReadingF(value_f=None, sentinel="M")),
        ("MM", TemperatureReadingF(value_f=None, sentinel="M")),
        ("T", TemperatureReadingF(value_f=None, sentinel="T")),
        ("MS", TemperatureReadingF(value_f=None, sentinel="MS")),
        ("MB", TemperatureReadingF(value_f=None, sentinel="MB")),
    ],
)
def test_parse_temperature_token_all_sentinel_kinds(
    token: str, expected: TemperatureReadingF
) -> None:
    assert parse_temperature_token(token) == expected


def test_parse_temperature_token_rejects_garbage() -> None:
    with pytest.raises(CliParseError):
        parse_temperature_token("NOTANUMBER")


def test_parse_temperature_token_rejects_empty_token() -> None:
    with pytest.raises(CliParseError):
        parse_temperature_token("")


def test_ambiguous_product_rejected_when_a_single_temperature_line_is_missing() -> None:
    """MAXIMUM present but MINIMUM absent from the YESTERDAY observed
    subsection must reject the whole product rather than return tmin as a
    guess.
    """
    missing_minimum = (
        _VALID_NYC_PREFIX
        + "...THE CENTRAL PARK NY CLIMATE SUMMARY FOR AUGUST 21 2026...\n"
        "TEMPERATURE (F)\n YESTERDAY\n  MAXIMUM 79\n\nPRECIPITATION\n"
    )
    with pytest.raises(CliParseError):
        parse_cli_product(missing_minimum, cli_location="NYC", body_header_regex=NYC_HEADER_REGEX)


def test_ambiguous_product_is_rejected_not_partially_parsed() -> None:
    """A product with no recognizable CLIMATE SUMMARY headline must raise,
    never return a reading with some fields populated and others guessed.
    """
    garbage = _VALID_NYC_PREFIX + "THIS IS NOT A CLI PRODUCT AT ALL\nNO HEADLINE HERE\n"
    with pytest.raises(CliParseError):
        parse_cli_product(garbage, cli_location="NYC", body_header_regex=NYC_HEADER_REGEX)


def test_ambiguous_product_rejected_when_headline_date_is_unparseable() -> None:
    garbled = (
        _VALID_NYC_PREFIX
        + "...THE CENTRAL PARK NY CLIMATE SUMMARY FOR NOTAMONTH 21 2026...\n"
        "TEMPERATURE (F)\n MAXIMUM 79\n MINIMUM 63\n AVERAGE 71\nPRECIPITATION\n"
    )
    with pytest.raises(CliParseError):
        parse_cli_product(garbled, cli_location="NYC", body_header_regex=NYC_HEADER_REGEX)


def test_ambiguous_product_rejected_when_headline_day_is_out_of_range() -> None:
    """A recognized month name with an impossible day (e.g. Feb 30) must
    still be rejected -- not silently clamped or guessed.
    """
    impossible_day = (
        _VALID_NYC_PREFIX
        + "...THE CENTRAL PARK NY CLIMATE SUMMARY FOR FEBRUARY 30 2026...\n"
        "TEMPERATURE (F)\n MAXIMUM 79\n MINIMUM 63\n AVERAGE 71\nPRECIPITATION\n"
    )
    with pytest.raises(CliParseError):
        parse_cli_product(impossible_day, cli_location="NYC", body_header_regex=NYC_HEADER_REGEX)


def test_ambiguous_product_rejected_when_temperature_block_missing() -> None:
    no_temp_block = (
        _VALID_NYC_PREFIX
        + "...THE CENTRAL PARK NY CLIMATE SUMMARY FOR AUGUST 21 2026...\nno temperature data here\n"
    )
    with pytest.raises(CliParseError):
        parse_cli_product(no_temp_block, cli_location="NYC", body_header_regex=NYC_HEADER_REGEX)


def test_ambiguous_product_rejected_when_station_header_does_not_match_registry_regex() -> None:
    """A KOKX product that is silently for a sibling station (e.g. JFK) must
    be rejected by the caller-supplied body_header_regex, never accepted as
    NYC's Central Park reading.
    """
    wrong_station = (
        _VALID_NYC_PREFIX
        + "...THE KENNEDY NY CLIMATE SUMMARY FOR AUGUST 21 2026...\n"
        "TEMPERATURE (F)\n MAXIMUM 79\n MINIMUM 63\n AVERAGE 71\nPRECIPITATION\n"
    )
    with pytest.raises(CliParseError):
        parse_cli_product(wrong_station, cli_location="NYC", body_header_regex=NYC_HEADER_REGEX)


def test_ambiguous_product_rejected_for_empty_text() -> None:
    with pytest.raises(CliParseError):
        parse_cli_product("", cli_location="NYC", body_header_regex=NYC_HEADER_REGEX)
