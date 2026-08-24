"""Tests for the NWS CLI "record" (``R``) qualifier suffix.

REAL LIVE FAILURE (2026-08-24): a five-site collection run BLOCKED
polymarket_us/MIA with::

    CliContentError: unrecognized temperature token: '100R'

NWS CLI climate reports append a trailing ``R`` to an observed value that
tied or broke the daily period-of-record for that date (see the product's
own footer legend: ``R  INDICATES RECORD WAS SET OR TIED.``). The observed
value is still exactly the published number -- 100 F is still 100 F -- and
is fully settlement-valid; it is precisely the day a weather-prediction
market is most likely to be near a strike, so silently blocking the site
on a record day is the worst possible failure mode.

`parse_temperature_token` must:
  * accept ``<int>R`` and preserve BOTH the numeric value and the fact
    that it was a record, via `TemperatureReadingF.is_record`;
  * keep rejecting anything that is not a bare signed integer optionally
    followed by a single trailing ``R`` -- the parser is settlement-truth
    and must fail LOUDLY on a genuinely malformed token, not quietly
    widen to accept it.

The two real fixtures below are verbatim captures from api.weather.gov
(see each `meta.json` for product UUID/issuance provenance) proving the
fix generalizes across two different days and two different values (100R,
96R), not just the single value from the original live failure.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

from breezy.normalize.cli_parse import CliContentError, parse_cli_product, parse_temperature_token
from breezy.normalize.units import TemperatureReadingF

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "nws"
SITES_TOML = (
    Path(__file__).resolve().parent.parent.parent / "src" / "breezy" / "registry" / "sites.toml"
)


def _load(name: str) -> str:
    return (FIXTURES_DIR / name / "product.txt").read_text()


def _mia_header_regex() -> re.Pattern[str]:
    with SITES_TOML.open("rb") as handle:
        data = tomllib.load(handle)
    return re.compile(data["sites"]["polymarket_us"]["MIA"]["body_header_regex"], re.MULTILINE)


# ---------------------------------------------------------------------------
# Token-level: `parse_temperature_token`
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("token", "expected"),
    [
        ("100R", TemperatureReadingF(value_f=100, sentinel="NONE", is_record=True)),
        ("96R", TemperatureReadingF(value_f=96, sentinel="NONE", is_record=True)),
        ("0R", TemperatureReadingF(value_f=0, sentinel="NONE", is_record=True)),
        ("-3R", TemperatureReadingF(value_f=-3, sentinel="NONE", is_record=True)),
    ],
)
def test_parse_temperature_token_preserves_record_suffix(
    token: str, expected: TemperatureReadingF
) -> None:
    assert parse_temperature_token(token) == expected


def test_parse_temperature_token_without_record_suffix_is_not_a_record() -> None:
    reading = parse_temperature_token("79")
    assert reading == TemperatureReadingF(value_f=79, sentinel="NONE", is_record=False)
    assert reading.is_record is False


@pytest.mark.parametrize(
    "token",
    [
        "ABC",  # not numeric at all
        "R",  # bare qualifier, no value
        "10RR",  # doubled qualifier
        "10R5",  # qualifier not trailing
        "R100",  # qualifier leading, not trailing
        "10X",  # unrecognized, non-record suffix
        "--5R",  # malformed sign
    ],
)
def test_parse_temperature_token_still_rejects_malformed_tokens(token: str) -> None:
    """The fix must not loosen the parser into accepting genuinely
    malformed tokens -- only the exact `<signed-int>R` shape is a record.
    """
    with pytest.raises(CliContentError):
        parse_temperature_token(token)


def test_parse_temperature_token_sentinel_tokens_are_never_records() -> None:
    """A missing/trace/sentinel token can never also be a record -- there
    is no value to have tied or broken anything.
    """
    reading = parse_temperature_token("M")
    assert reading.sentinel == "M"
    assert reading.value_f is None
    assert reading.is_record is False


# ---------------------------------------------------------------------------
# Product-level: real, live-captured Miami fixtures
# ---------------------------------------------------------------------------


def test_real_miami_fixture_with_100r_maximum_parses_and_preserves_record() -> None:
    """The exact live failure: MAXIMUM row renders '100R', 2:47 PM (colon
    time format, unlike NYC's '214 PM'). Must parse to tmax=100 with the
    record preserved, not raise `CliContentError`.
    """
    result = parse_cli_product(
        _load("mia_record_final_2026-08-18"),
        cli_location="MIA",
        body_header_regex=_mia_header_regex(),
    )

    assert result.tmax == TemperatureReadingF(value_f=100, sentinel="NONE", is_record=True)
    assert result.tmin == TemperatureReadingF(value_f=82, sentinel="NONE", is_record=False)
    assert result.tavg == TemperatureReadingF(value_f=91, sentinel="NONE", is_record=False)


def test_real_miami_fixture_with_96r_maximum_parses_and_preserves_record() -> None:
    """A second, independent real capture -- different day, different
    value -- proving the fix generalizes rather than special-casing 100R.
    """
    result = parse_cli_product(
        _load("mia_record_final_2026-08-19"),
        cli_location="MIA",
        body_header_regex=_mia_header_regex(),
    )

    assert result.tmax == TemperatureReadingF(value_f=96, sentinel="NONE", is_record=True)
    assert result.tmin == TemperatureReadingF(value_f=76, sentinel="NONE", is_record=False)
    assert result.tavg == TemperatureReadingF(value_f=86, sentinel="NONE", is_record=False)
