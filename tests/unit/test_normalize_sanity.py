"""Physical sanity bounds for parsed CLI temperatures.

`domain/validation.py` assigns physical-plausibility bounds to the
normalization layer; this is the test suite for that assignment.

Two directions are tested, and BOTH matter:

1. Physically impossible values are REJECTED with a distinct, typed error
   (`CliSanityError`) -- distinct from `CliParseError`, because the
   settlement gate routes `SANITY_VIOLATION` and `PARSER_FAILURE`
   differently and a shared exception type destroys that distinction at
   exactly the point it matters.

2. Genuine record-book extremes for the five settlement sites are
   ACCEPTED. This second class is the one that stops a future editor from
   tightening the bounds into an outage: a bound tight enough to reject a
   real Chicago cold snap or a Miami heat record would take the bot
   offline exactly when the market is most interesting.

The target is *physically impossible*, never merely *unusual*.
"""

from __future__ import annotations

import re

import pytest

from breezy.normalize.cli_parse import CliParseError, parse_cli_product
from breezy.normalize.sanity import (
    ABSOLUTE_MAX_F,
    ABSOLUTE_MIN_F,
    MAX_DIURNAL_RANGE_F,
    CliSanityError,
    check_physical_sanity,
)
from breezy.normalize.units import TemperatureReadingF

NYC_HEADER_REGEX = re.compile(
    r"^\.\.\.THE\s+CENTRAL\s+PARK\s+NY\s+CLIMATE\s+SUMMARY\s+FOR\b", re.MULTILINE
)
VALID_NYC_PREFIX = "\n000\nCDUS41 KOKX 220626\nCLINYC\n"

# ---------------------------------------------------------------------------
# Reality anchors. These are the published figures the bounds are justified
# against; they are documentation of the *reasoning*, not settlement facts
# owned by this layer.
# ---------------------------------------------------------------------------

US_RECORD_HIGH_F = 134
"""Death Valley, CA, 1913-07-10 -- the highest air temperature ever
reliably measured anywhere on Earth."""

US_RECORD_LOW_F = -80
"""Prospect Creek, AK, 1971-01-23 -- the lowest ever measured in the US.
The lower-48 record is -70 F (Rogers Pass, MT, 1954)."""

WORLD_RECORD_24H_RANGE_F = 100
"""Browning, MT, 1916-01-23/24: +44 F to -56 F in 24 hours -- the largest
temperature range ever recorded on Earth over a single day."""

# Published all-time records for the five Polymarket.us settlement sites.
# Illustrative to ~a degree; the assertion below only needs them to be
# comfortably INSIDE the accepted envelope, so a small error in a figure
# cannot make this test wrongly pass.
SITE_RECORD_EXTREMES_F: dict[str, tuple[int, int]] = {
    "NYC (Central Park)": (106, -15),
    "MDW (Chicago Midway)": (109, -27),
    "MIA (Miami)": (100, 27),
    "LAX (Los Angeles Intl)": (110, 27),
    "SFO (San Francisco Intl)": (106, 20),
}


def _f(value: int) -> TemperatureReadingF:
    return TemperatureReadingF(value_f=value, sentinel="NONE")


def _missing() -> TemperatureReadingF:
    return TemperatureReadingF(value_f=None, sentinel="M")


# ---------------------------------------------------------------------------
# The anti-outage guard: the bounds must stay WIDER than reality
# ---------------------------------------------------------------------------


def test_bounds_are_wider_than_every_temperature_ever_recorded_in_the_us() -> None:
    """If this fails, someone tightened the bounds toward "unusual" and the
    bot will go offline on the day a record is broken. Widen, never narrow.
    """
    assert ABSOLUTE_MAX_F >= US_RECORD_HIGH_F
    assert ABSOLUTE_MIN_F <= US_RECORD_LOW_F
    assert MAX_DIURNAL_RANGE_F >= WORLD_RECORD_24H_RANGE_F


def test_us_national_record_values_are_accepted() -> None:
    check_physical_sanity(
        tmax=_f(US_RECORD_HIGH_F), tmin=_f(US_RECORD_HIGH_F - 30), tavg=_f(US_RECORD_HIGH_F - 15)
    )
    check_physical_sanity(
        tmax=_f(US_RECORD_LOW_F + 30), tmin=_f(US_RECORD_LOW_F), tavg=_f(US_RECORD_LOW_F + 15)
    )


@pytest.mark.parametrize(("site", "extremes"), sorted(SITE_RECORD_EXTREMES_F.items()))
def test_site_record_book_extremes_are_accepted(site: str, extremes: tuple[int, int]) -> None:
    """Every one of the five settlement sites' all-time record high and
    record low must parse and pass sanity. These are real, published,
    settlement-relevant values -- rejecting one is an outage, not a guard.
    """
    record_high, record_low = extremes

    # The record high day (a plausible same-day minimum beneath it).
    check_physical_sanity(
        tmax=_f(record_high), tmin=_f(record_high - 25), tavg=_f(record_high - 13)
    )
    # The record low day (a plausible same-day maximum above it).
    check_physical_sanity(tmax=_f(record_low + 15), tmin=_f(record_low), tavg=_f(record_low + 7))


def test_largest_ever_recorded_diurnal_range_is_accepted() -> None:
    """Browning MT's 100 F single-day swing is real. A range bound that
    rejects it is a bound on "unusual", not on "impossible".
    """
    check_physical_sanity(tmax=_f(44), tmin=_f(-56), tavg=_f(-6))


# ---------------------------------------------------------------------------
# Physically impossible values are rejected
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("impossible_max", [250, 1000, ABSOLUTE_MAX_F + 1])
def test_impossible_maximum_is_rejected(impossible_max: int) -> None:
    with pytest.raises(CliSanityError, match="MAXIMUM"):
        check_physical_sanity(tmax=_f(impossible_max), tmin=_f(60), tavg=_f(70))


@pytest.mark.parametrize("impossible_min", [-300, -1000, ABSOLUTE_MIN_F - 1])
def test_impossible_minimum_is_rejected(impossible_min: int) -> None:
    with pytest.raises(CliSanityError, match="MINIMUM"):
        check_physical_sanity(tmax=_f(80), tmin=_f(impossible_min), tavg=_f(70))


def test_maximum_below_the_floor_is_rejected() -> None:
    """The envelope is two-sided per field: a daily MAXIMUM of -300 F is
    just as impossible as a MAXIMUM of 250 F.
    """
    with pytest.raises(CliSanityError, match="MAXIMUM"):
        check_physical_sanity(tmax=_f(ABSOLUTE_MIN_F - 1), tmin=_f(ABSOLUTE_MIN_F - 1), tavg=_f(0))


def test_minimum_above_the_ceiling_is_rejected() -> None:
    """The envelope is two-sided for MINIMUM as well. `tmax` is a sentinel
    here so the MAXIMUM check cannot fire first and mask this one.
    """
    with pytest.raises(CliSanityError, match="MINIMUM"):
        check_physical_sanity(tmax=_missing(), tmin=_f(ABSOLUTE_MAX_F + 1), tavg=_missing())


@pytest.mark.parametrize("impossible_avg", [ABSOLUTE_MAX_F + 1, ABSOLUTE_MIN_F - 1])
def test_impossible_average_is_rejected(impossible_avg: int) -> None:
    with pytest.raises(CliSanityError, match="AVERAGE"):
        check_physical_sanity(tmax=_missing(), tmin=_missing(), tavg=_f(impossible_avg))


# ---------------------------------------------------------------------------
# Mutual ordering
# ---------------------------------------------------------------------------


def test_minimum_above_maximum_is_rejected() -> None:
    """min <= max is definitional, not statistical: the minimum of a set
    cannot exceed its maximum. A violation is a column-shift or corruption.
    """
    with pytest.raises(CliSanityError, match="MINIMUM"):
        check_physical_sanity(tmax=_f(63), tmin=_f(79), tavg=_f(71))


def test_minimum_equal_to_maximum_is_accepted() -> None:
    """A flat, fog-locked marine-layer day rounds to the same whole degree
    for both extremes. Real, and must not be rejected.
    """
    check_physical_sanity(tmax=_f(55), tmin=_f(55), tavg=_f(55))


def test_average_above_maximum_is_rejected() -> None:
    with pytest.raises(CliSanityError, match="AVERAGE"):
        check_physical_sanity(tmax=_f(79), tmin=_f(63), tavg=_f(90))


def test_average_below_minimum_is_rejected() -> None:
    with pytest.raises(CliSanityError, match="AVERAGE"):
        check_physical_sanity(tmax=_f(79), tmin=_f(63), tavg=_f(50))


def test_average_equal_to_either_extreme_is_accepted() -> None:
    check_physical_sanity(tmax=_f(70), tmin=_f(70), tavg=_f(70))
    check_physical_sanity(tmax=_f(71), tmin=_f(70), tavg=_f(71))
    check_physical_sanity(tmax=_f(71), tmin=_f(70), tavg=_f(70))


# ---------------------------------------------------------------------------
# Diurnal range: the JOINT impossibility the per-field envelope cannot catch
# ---------------------------------------------------------------------------


def test_impossible_diurnal_range_is_rejected_even_when_both_endpoints_are_in_range() -> None:
    """This is why the range bound is not redundant with the per-field
    envelope: both endpoints below are individually possible values, but
    the PAIR is impossible. A column-shift that pairs a real maximum with
    another row's minimum lands exactly here.
    """
    tmax_value = ABSOLUTE_MAX_F
    tmin_value = ABSOLUTE_MIN_F
    assert ABSOLUTE_MIN_F <= tmax_value <= ABSOLUTE_MAX_F
    assert ABSOLUTE_MIN_F <= tmin_value <= ABSOLUTE_MAX_F

    with pytest.raises(CliSanityError, match="range"):
        check_physical_sanity(tmax=_f(tmax_value), tmin=_f(tmin_value), tavg=_missing())


def test_diurnal_range_boundary_is_inclusive() -> None:
    at_ceiling_max = ABSOLUTE_MIN_F + 10 + MAX_DIURNAL_RANGE_F
    check_physical_sanity(
        tmax=_f(at_ceiling_max), tmin=_f(ABSOLUTE_MIN_F + 10), tavg=_missing()
    )

    with pytest.raises(CliSanityError, match="range"):
        check_physical_sanity(
            tmax=_f(at_ceiling_max + 1), tmin=_f(ABSOLUTE_MIN_F + 10), tavg=_missing()
        )


# ---------------------------------------------------------------------------
# Boundaries of the per-field envelope are inclusive
# ---------------------------------------------------------------------------


def test_envelope_boundaries_are_inclusive() -> None:
    check_physical_sanity(tmax=_f(ABSOLUTE_MAX_F), tmin=_missing(), tavg=_missing())
    check_physical_sanity(tmax=_missing(), tmin=_f(ABSOLUTE_MIN_F), tavg=_missing())


# ---------------------------------------------------------------------------
# Sentinels: an absent value is checked for nothing, never imputed
# ---------------------------------------------------------------------------


def test_all_sentinel_readings_pass_every_check() -> None:
    check_physical_sanity(tmax=_missing(), tmin=_missing(), tavg=_missing())


def test_partially_sentinel_readings_skip_only_the_pairwise_checks() -> None:
    """A present value is still envelope-checked when its counterpart is a
    sentinel; the ordering and range checks simply have nothing to compare.
    """
    check_physical_sanity(tmax=_f(79), tmin=_missing(), tavg=_missing())
    check_physical_sanity(tmax=_missing(), tmin=_f(63), tavg=_missing())
    check_physical_sanity(tmax=_f(79), tmin=_missing(), tavg=_f(71))
    check_physical_sanity(tmax=_missing(), tmin=_f(63), tavg=_f(71))

    with pytest.raises(CliSanityError, match="MAXIMUM"):
        check_physical_sanity(tmax=_f(250), tmin=_missing(), tavg=_missing())


# ---------------------------------------------------------------------------
# The typed error is DISTINCT from a parse failure
# ---------------------------------------------------------------------------


def test_sanity_error_is_not_a_parse_error() -> None:
    """The gate routes SANITY_VIOLATION and PARSER_FAILURE differently. If
    `CliSanityError` were a `CliParseError`, every existing
    `except CliParseError` handler would silently swallow a sanity
    violation and record the wrong reason.
    """
    assert not issubclass(CliSanityError, CliParseError)
    assert not issubclass(CliParseError, CliSanityError)
    assert issubclass(CliSanityError, ValueError)


# ---------------------------------------------------------------------------
# The bound is wired into the parser, not merely available beside it
# ---------------------------------------------------------------------------


def _nyc_product(maximum: str, minimum: str, average: str) -> str:
    return (
        VALID_NYC_PREFIX
        + "...THE CENTRAL PARK NY CLIMATE SUMMARY FOR AUGUST 21 2026...\n"
        "TEMPERATURE (F)\n"
        " YESTERDAY\n"
        f"  MAXIMUM         {maximum}\n"
        f"  MINIMUM         {minimum}\n"
        f"  AVERAGE         {average}\n"
        "\n"
        "PRECIPITATION (IN)\n"
    )


def test_parse_rejects_an_impossible_maximum() -> None:
    with pytest.raises(CliSanityError):
        parse_cli_product(
            _nyc_product("250", "63", "71"),
            cli_location="NYC",
            body_header_regex=NYC_HEADER_REGEX,
        )


def test_parse_rejects_an_impossible_minimum() -> None:
    with pytest.raises(CliSanityError):
        parse_cli_product(
            _nyc_product("79", "-300", "71"),
            cli_location="NYC",
            body_header_regex=NYC_HEADER_REGEX,
        )


def test_parse_rejects_an_impossible_diurnal_range() -> None:
    with pytest.raises(CliSanityError):
        parse_cli_product(
            _nyc_product("140", "-100", "20"),
            cli_location="NYC",
            body_header_regex=NYC_HEADER_REGEX,
        )


def test_parse_rejects_inverted_extremes() -> None:
    with pytest.raises(CliSanityError):
        parse_cli_product(
            _nyc_product("63", "79", "71"),
            cli_location="NYC",
            body_header_regex=NYC_HEADER_REGEX,
        )


def test_parse_accepts_a_site_record_extreme() -> None:
    result = parse_cli_product(
        _nyc_product("106", "78", "92"),
        cli_location="NYC",
        body_header_regex=NYC_HEADER_REGEX,
    )

    assert result.tmax == TemperatureReadingF(value_f=106, sentinel="NONE")
