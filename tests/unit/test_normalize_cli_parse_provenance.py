"""The parser surfaces the header facts it already validated.

`check_structural_allowlist` inspects lines 2-3 of every product to
validate the WMO abbreviated heading and to assert the AWIPS PIL equals
``CLI{cli_location}``. Downstream provenance needs BOTH the AWIPS PIL and
the WMO ``BBB`` indicator (line 2), which api.weather.gov does not expose
as a field -- the raw heading is the only place it exists.

``BBB`` is NOT a correction flag. It spans corrections (``CCx``),
amendments (``AAx``), delayed/retransmitted reports (``RRx``) and message
segments (``Pxx``). The token is kept verbatim for provenance and the
correction verdict is published separately as a derived property, so no
caller has to know that distinction to get it right.

Before this suite, the parser threw both away and the caller had to
re-scan text the parser had already parsed. Two independent scans of the
same bytes for the same facts will eventually disagree, and the fact they
would disagree about is "was this product a correction?" -- a
supersession decision on an already-settled climate day.
"""

from __future__ import annotations

import re
import typing
from datetime import date
from pathlib import Path

import pytest

from breezy.normalize import cli_parse
from breezy.normalize.cli_parse import (
    CliStructuralHeader,
    ParsedCliProduct,
    check_structural_allowlist,
    parse_cli_product,
)
from breezy.normalize.units import SentinelFlag, TemperatureReadingF

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
    assert header == CliStructuralHeader(
        awips_pil="CLINYC",
        wmo_transmission_sequence="000",
        wmo_bbb="CCA",
    )


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


# --------------------------------------------------------------------------
# WMO BBB: the captured token is the WHOLE BBB space, not just corrections.
#
# `bbb` is a bare `[A-Z]{3}`, and the BBB space includes amendments (AAx),
# delayed/retransmitted reports (RRx) and message segments (Pxx) alongside
# corrections (CCx). None of the first three is a correction.
#
# The obvious-looking downstream implementation --
#     if parsed.wmo_bbb is not None: treat_as_correction()
# -- is therefore WRONG: it would misclassify a delayed RETRANSMISSION of an
# otherwise-unchanged final as a correction, forcing a spurious revision_seq
# bump or a false post-settlement supersession alert.
#
# The fix keeps the general capture (an RRA retransmission is genuine, useful
# provenance and must not be thrown away) and publishes the correction verdict
# as a DERIVED, non-settable property, so no caller ever re-derives it.
# --------------------------------------------------------------------------

_NON_CORRECTION_BBB = ["RRA", "RRB", "AAA", "AAB", "PAA", "PZZ"]
_CORRECTION_BBB = ["CCA", "CCB", "CCC", "CCZ"]


def _with_bbb(bbb: str | None) -> str:
    """The NYC final fixture, re-headed with (or without) a BBB token."""
    text = _load("nyc_final_2026-08-21")
    heading = "CDUS41 KOKX 220626"
    replacement = heading if bbb is None else f"{heading} {bbb}"
    assert heading in text
    return text.replace(heading, replacement, 1)


@pytest.mark.parametrize("bbb", _NON_CORRECTION_BBB + _CORRECTION_BBB)
def test_every_bbb_indicator_still_passes_the_structural_allowlist(bbb: str) -> None:
    """Narrowing the CAPTURE to `CC[AB]` would have turned every non-correction
    BBB indicator into a `CliStructuralError` -- a loud integrity alarm, and a
    sticky hard block, raised on a routine WMO retransmission. The heading
    SHAPE stays permissive; only the interpretation is strict.
    """
    header = check_structural_allowlist(_with_bbb(bbb), cli_location="NYC")

    assert header.wmo_bbb == bbb


@pytest.mark.parametrize("bbb", _NON_CORRECTION_BBB)
def test_non_correction_bbb_indicators_are_retained_as_provenance(bbb: str) -> None:
    """Discarding an RRA/AAA/PAA token is a real loss, not a free
    simplification: knowing a product arrived as a delayed retransmission is
    exactly what explains a late or duplicated final after the fact.
    """
    parsed = parse_cli_product(
        _with_bbb(bbb), cli_location="NYC", body_header_regex=NYC_HEADER_REGEX
    )

    assert parsed.wmo_bbb == bbb


@pytest.mark.parametrize("bbb", _NON_CORRECTION_BBB)
def test_a_non_correction_bbb_indicator_is_not_a_correction(bbb: str) -> None:
    """THE TRAP. A delayed retransmission (RRx), an amendment (AAx) and a
    message segment (Pxx) all make `wmo_bbb is not None` true, and none of
    them is a correction.
    """
    header = check_structural_allowlist(_with_bbb(bbb), cli_location="NYC")
    parsed = parse_cli_product(
        _with_bbb(bbb), cli_location="NYC", body_header_regex=NYC_HEADER_REGEX
    )

    assert header.wmo_bbb is not None
    assert header.is_correction_bbb is False
    assert parsed.is_correction_bbb is False


@pytest.mark.parametrize("bbb", _CORRECTION_BBB)
def test_a_correction_bbb_indicator_is_a_correction(bbb: str) -> None:
    """`CCC` and beyond matter: a third correction to one climate day is rarer
    than the first, and it is the one most likely to land after settlement.
    The BBB token is POSITIONAL (line 2 of the WMO heading), so matching the
    whole `CC[A-Z]` series here carries none of the false-positive risk that
    the free-text scan in `classify.py` has to weigh.
    """
    header = check_structural_allowlist(_with_bbb(bbb), cli_location="NYC")
    parsed = parse_cli_product(
        _with_bbb(bbb), cli_location="NYC", body_header_regex=NYC_HEADER_REGEX
    )

    assert header.is_correction_bbb is True
    assert parsed.is_correction_bbb is True


def test_absent_bbb_is_not_a_correction() -> None:
    header = check_structural_allowlist(_with_bbb(None), cli_location="NYC")

    assert header.wmo_bbb is None
    assert header.is_correction_bbb is False


def test_correction_verdict_is_derived_and_cannot_be_set_independently() -> None:
    """It is a read-only derived property, not a constructor field. A caller
    cannot hand-assemble a header whose token and verdict disagree, and the
    two can never drift apart.
    """
    header = CliStructuralHeader(
        awips_pil="CLINYC",
        wmo_transmission_sequence="000",
        wmo_bbb="RRA",
    )

    assert header.is_correction_bbb is False
    with pytest.raises((AttributeError, TypeError)):
        header.is_correction_bbb = True  # type: ignore[misc]


def test_parsed_product_and_allowlist_agree_on_the_correction_verdict() -> None:
    """Same single-scan guarantee the tokens themselves already carry."""
    text = _load("nyc_correction_synthetic_2026-08-21")

    header = check_structural_allowlist(text, cli_location="NYC")
    parsed = parse_cli_product(text, cli_location="NYC", body_header_regex=NYC_HEADER_REGEX)

    assert header.is_correction_bbb is parsed.is_correction_bbb is True


# --------------------------------------------------------------------------
# `slots=True` consistency across the frozen dataclasses in `normalize`.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "instance",
    [
        CliStructuralHeader(
            awips_pil="CLINYC",
            wmo_transmission_sequence="000",
            wmo_bbb=None,
        ),
        TemperatureReadingF(value_f=79, sentinel="NONE"),
        ParsedCliProduct(
            summary_date=date(2026, 8, 21),
            station_header_line="...THE CENTRAL PARK NY CLIMATE SUMMARY FOR AUGUST 21 2026...",
            tmax=TemperatureReadingF(value_f=79, sentinel="NONE"),
            tmin=TemperatureReadingF(value_f=63, sentinel="NONE"),
            tavg=TemperatureReadingF(value_f=71, sentinel="NONE"),
            awips_pil="CLINYC",
            wmo_bbb=None,
        ),
    ],
    ids=["CliStructuralHeader", "TemperatureReadingF", "ParsedCliProduct"],
)
def test_frozen_normalize_dataclasses_use_slots(instance: object) -> None:
    """Every other frozen dataclass in this change set carries `slots=True`;
    these three did not. None needs `__dict__` or `__weakref__` -- they are
    small, closed value objects on the settlement path, and a per-instance
    `__dict__` there is both wasted memory per ingested product and a way for
    a typo'd attribute to be silently accepted on a frozen-by-intent record.
    """
    assert hasattr(type(instance), "__slots__")
    assert not hasattr(instance, "__dict__")


# --------------------------------------------------------------------------
# The sentinel-token table's value type is the invariant, not a comment.
# --------------------------------------------------------------------------


def test_sentinel_token_table_is_typed_as_sentinel_flag() -> None:
    """`_SENTINEL_TOKENS` was `dict[str, str]`, which forced a
    `# type: ignore[arg-type]` at the one call site that feeds it into
    `TemperatureReadingF.sentinel: SentinelFlag`. The ignore switched OFF a
    real, checkable invariant -- that only five sentinel spellings exist -- to
    work around a type that was simply too wide. Typing the table correctly
    enforces it statically instead, and lets the ignore be deleted.
    """
    hints = typing.get_type_hints(cli_parse)
    _key_type, value_type = typing.get_args(hints["_SENTINEL_TOKENS"])

    assert value_type is SentinelFlag


def test_every_sentinel_token_maps_to_a_declared_sentinel_flag() -> None:
    """Runtime backstop for the same invariant, so a bogus spelling fails the
    suite even where a type checker is not in the loop.
    """
    declared = set(typing.get_args(SentinelFlag))

    assert set(cli_parse._SENTINEL_TOKENS.values()) <= declared
    assert "NONE" not in cli_parse._SENTINEL_TOKENS.values()
