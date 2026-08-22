"""The four rejection categories, and why they are four and not one.

`SettlementGate` routes rejection reasons differently, and a hard block is
sticky: it clears only on a subsequent successful poll. So an exception
type that conflates a routine condition with a CRIT will hard-block a
site for a healthy, expected event.

The four categories, and the consequence each one carries:

1. `CliNotOurProductError` -- ROUTINE. One WFO issues several cities'
   products (KOKX issues NYC + JFK + LGA + EWR), so a `CLIJFK` product
   arriving on the NYC poll is an expected, healthy occurrence. The
   caller ignores it and carries on. Blocking here is an outage caused by
   the system working correctly.
2. `CliStructuralError` -- LOUD. Line count, line length, WMO envelope
   shape. Not a sibling product: a body that should never have been
   served to us at all.
3. `CliContentError` -- CRIT. Structure passed, content could not be read.
   Our own station's product genuinely failed to parse.
4. `CliSanityError` -- CRIT, but a DIFFERENT crit (`SANITY_VIOLATION`,
   not `PARSER_FAILURE`). Content read fine; the values are physically
   impossible. Deliberately NOT a `CliParseError` -- see
   test_normalize_sanity.py.

Discrimination must work at the call site WITHOUT inspecting a message
string. Message-sniffing is not an acceptable discriminator for a
settlement-path decision.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from breezy.normalize.cli_parse import (
    MAX_LINE_COUNT,
    MAX_LINE_LENGTH,
    CliContentError,
    CliNotOurProductError,
    CliParseError,
    CliStructuralError,
    check_structural_allowlist,
    parse_cli_product,
)
from breezy.normalize.sanity import CliSanityError

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "nws"
NYC_HEADER_REGEX = re.compile(
    r"^\.\.\.THE\s+CENTRAL\s+PARK\s+NY\s+CLIMATE\s+SUMMARY\s+FOR\b", re.MULTILINE
)
VALID_NYC_PREFIX = "\n000\nCDUS41 KOKX 220626\nCLINYC\n"
_VALID_BODY = (
    VALID_NYC_PREFIX
    + "...THE CENTRAL PARK NY CLIMATE SUMMARY FOR AUGUST 21 2026...\n"
    "TEMPERATURE (F)\n YESTERDAY\n  MAXIMUM 79\n  MINIMUM 63\n  AVERAGE 71\n\n"
    "PRECIPITATION (IN)\n"
)


def _load(name: str) -> str:
    return (FIXTURES_DIR / name / "product.txt").read_text()


def _parse(text: str) -> object:
    return parse_cli_product(text, cli_location="NYC", body_header_regex=NYC_HEADER_REGEX)


# ---------------------------------------------------------------------------
# The hierarchy itself
# ---------------------------------------------------------------------------


def test_every_parse_category_is_a_cli_parse_error() -> None:
    """Backward compatibility: an existing `except CliParseError` keeps
    catching all three parse categories, so no current caller silently
    starts leaking exceptions when this hierarchy lands.
    """
    assert issubclass(CliNotOurProductError, CliParseError)
    assert issubclass(CliStructuralError, CliParseError)
    assert issubclass(CliContentError, CliParseError)


def test_the_three_parse_categories_are_siblings_not_ancestors() -> None:
    """None may be a subclass of another, or `except`-clause ordering
    would silently route one category into another's handler.
    """
    categories = (CliNotOurProductError, CliStructuralError, CliContentError)
    for category in categories:
        for other in categories:
            if category is other:
                continue
            assert not issubclass(category, other), f"{category} must not subclass {other}"


def test_sanity_violation_is_outside_the_parse_hierarchy() -> None:
    """The fourth category. The gate routes SANITY_VIOLATION separately
    from PARSER_FAILURE; sharing an ancestor with the parse categories
    would let `except CliParseError` swallow it.
    """
    assert not issubclass(CliSanityError, CliParseError)


# ---------------------------------------------------------------------------
# ROUTINE: not our product
# ---------------------------------------------------------------------------


def test_sibling_station_pil_is_routine_not_a_parse_failure() -> None:
    """`CLIJFK` on the NYC poll. KOKX issues NYC + JFK + LGA + EWR, so this
    happens every single day on a healthy system. Hard-blocking NYC here
    is an outage manufactured out of normal operation.
    """
    sibling = _VALID_BODY.replace("CLINYC", "CLIJFK", 1)

    with pytest.raises(CliNotOurProductError):
        _parse(sibling)


def test_monthly_clm_product_is_routine_not_a_parse_failure() -> None:
    """A CLM (monthly climate) product carries a different PIL. Also not
    ours, also routine.
    """
    monthly = _VALID_BODY.replace("CLINYC", "CLMNYC", 1)

    with pytest.raises(CliNotOurProductError):
        _parse(monthly)


def test_not_our_product_is_distinguishable_without_reading_the_message() -> None:
    """The discriminator a settlement-path caller is allowed to use."""
    sibling = _VALID_BODY.replace("CLINYC", "CLIJFK", 1)

    try:
        _parse(sibling)
    except CliNotOurProductError:
        routed = "ignore"
    except CliParseError:  # pragma: no cover - the assertion below explains
        routed = "block"

    assert routed == "ignore"


def test_a_genuine_content_failure_still_blocks() -> None:
    """The counterpart to the test above: an `except CliNotOurProductError`
    handler must NOT swallow our own station's broken product.
    """
    broken = VALID_NYC_PREFIX + "...THE CENTRAL PARK NY CLIMATE SUMMARY FOR AUGUST 21 2026...\n"

    try:
        _parse(broken)
    except CliNotOurProductError:  # pragma: no cover - the assertion explains
        routed = "ignore"
    except CliParseError:
        routed = "block"

    assert routed == "block"


# ---------------------------------------------------------------------------
# LOUD: malformed / hostile shape
# ---------------------------------------------------------------------------


def test_oversize_line_count_is_structural() -> None:
    with pytest.raises(CliStructuralError):
        _parse("x\n" * (MAX_LINE_COUNT + 1))


def test_oversize_line_length_is_structural() -> None:
    with pytest.raises(CliStructuralError):
        _parse("\n000\n" + "x" * (MAX_LINE_LENGTH + 1) + "\nCLINYC\n")


def test_missing_transmission_indicator_is_structural() -> None:
    with pytest.raises(CliStructuralError):
        _parse(_VALID_BODY.replace("000", "001", 1))


def test_malformed_wmo_heading_is_structural() -> None:
    with pytest.raises(CliStructuralError):
        _parse(_VALID_BODY.replace("CDUS41 KOKX 220626", "NOT A WMO HEADING", 1))


def test_too_short_to_have_a_header_is_structural() -> None:
    with pytest.raises(CliStructuralError):
        _parse("\n000\nCDUS41 KOKX 220626\n")


def test_empty_text_is_structural() -> None:
    with pytest.raises(CliStructuralError):
        _parse("")


def test_whitespace_only_text_is_structural() -> None:
    with pytest.raises(CliStructuralError):
        _parse("   \n \t \n")


# ---------------------------------------------------------------------------
# CRIT: structure passed, content unreadable
# ---------------------------------------------------------------------------


def test_missing_headline_is_a_content_failure() -> None:
    with pytest.raises(CliContentError):
        _parse(VALID_NYC_PREFIX + "TEMPERATURE (F)\n YESTERDAY\n  MAXIMUM 79\nPRECIPITATION\n")


def test_missing_temperature_block_is_a_content_failure() -> None:
    with pytest.raises(CliContentError):
        _parse(
            VALID_NYC_PREFIX + "...THE CENTRAL PARK NY CLIMATE SUMMARY FOR AUGUST 21 2026...\n"
        )


def test_unparseable_headline_date_is_a_content_failure() -> None:
    with pytest.raises(CliContentError):
        _parse(
            VALID_NYC_PREFIX
            + "...THE CENTRAL PARK NY CLIMATE SUMMARY FOR AUGUST 99 2026...\n"
            "TEMPERATURE (F)\n YESTERDAY\n  MAXIMUM 79\n  MINIMUM 63\n  AVERAGE 71\n\n"
            "PRECIPITATION (IN)\n"
        )


def test_unrecognized_month_is_a_content_failure() -> None:
    with pytest.raises(CliContentError):
        _parse(
            VALID_NYC_PREFIX
            + "...THE CENTRAL PARK NY CLIMATE SUMMARY FOR SMARCH 21 2026...\n"
            "TEMPERATURE (F)\n YESTERDAY\n  MAXIMUM 79\n  MINIMUM 63\n  AVERAGE 71\n\n"
            "PRECIPITATION (IN)\n"
        )


def test_contradictory_station_header_is_a_content_failure_not_routine() -> None:
    """The PIL said this product is ours, and then the body header says it
    is another station's. That is a CONTRADICTION inside one product, not
    a sibling product addressed to someone else -- exactly the silent
    wrong-station bug this module exists to catch. It must stay loud.
    """
    contradictory = _VALID_BODY.replace(
        "...THE CENTRAL PARK NY CLIMATE SUMMARY FOR",
        "...THE KENNEDY NY CLIMATE SUMMARY FOR",
        1,
    )

    with pytest.raises(CliContentError):
        _parse(contradictory)


def test_missing_observed_subsection_is_a_content_failure() -> None:
    with pytest.raises(CliContentError):
        _parse(
            VALID_NYC_PREFIX
            + "...THE CENTRAL PARK NY CLIMATE SUMMARY FOR AUGUST 21 2026...\n"
            "TEMPERATURE (F)\n NORMAL\n  MAXIMUM 83\n  MINIMUM 68\n\n"
            "PRECIPITATION (IN)\n"
        )


def test_unrecognized_temperature_token_is_a_content_failure() -> None:
    with pytest.raises(CliContentError):
        _parse(
            VALID_NYC_PREFIX
            + "...THE CENTRAL PARK NY CLIMATE SUMMARY FOR AUGUST 21 2026...\n"
            "TEMPERATURE (F)\n YESTERDAY\n  MAXIMUM ABC\n  MINIMUM 63\n  AVERAGE 71\n\n"
            "PRECIPITATION (IN)\n"
        )


def test_missing_minimum_row_is_a_content_failure() -> None:
    with pytest.raises(CliContentError):
        _parse(
            VALID_NYC_PREFIX
            + "...THE CENTRAL PARK NY CLIMATE SUMMARY FOR AUGUST 21 2026...\n"
            "TEMPERATURE (F)\n YESTERDAY\n  MAXIMUM 79\n\n"
            "PRECIPITATION (IN)\n"
        )


# ---------------------------------------------------------------------------
# The allowlist is separately callable
# ---------------------------------------------------------------------------


def test_allowlist_can_be_run_alone_before_parsing() -> None:
    """The poll sequence declares structural rejection and parsing to be
    two steps with distinct consequences. That separation is only
    implementable if a caller can run the structural step by itself.
    """
    header = check_structural_allowlist(_load("nyc_final_2026-08-21"), cli_location="NYC")

    assert header.awips_pil == "CLINYC"


def test_allowlist_alone_raises_the_same_categories() -> None:
    with pytest.raises(CliNotOurProductError):
        check_structural_allowlist(_VALID_BODY.replace("CLINYC", "CLIJFK", 1), cli_location="NYC")

    with pytest.raises(CliStructuralError):
        check_structural_allowlist("\n000\nnope\nCLINYC\n", cli_location="NYC")


def test_allowlist_still_runs_inside_parse_ahead_of_every_regex() -> None:
    """Defence in depth: a caller that forgets the standalone step is
    still protected, and the cheap total gate still precedes the regexes.
    A body that is BOTH oversize and content-garbage must be rejected as
    structural -- proving the structural gate ran first.
    """
    oversize_and_garbage = "garbage\n" * (MAX_LINE_COUNT + 1)

    with pytest.raises(CliStructuralError):
        _parse(oversize_and_garbage)


def test_sanity_check_runs_after_the_structural_gate() -> None:
    """A product that is both structurally malformed and carries an
    impossible temperature is rejected as structural, never as a sanity
    violation -- the cheap gate always wins.
    """
    malformed_and_impossible = _VALID_BODY.replace("MAXIMUM 79", "MAXIMUM 250", 1).replace(
        "000", "001", 1
    )

    with pytest.raises(CliStructuralError):
        _parse(malformed_and_impossible)

    with pytest.raises(CliSanityError):
        _parse(_VALID_BODY.replace("MAXIMUM 79", "MAXIMUM 250", 1))
