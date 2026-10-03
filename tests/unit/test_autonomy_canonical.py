"""ARCH-0 seam 2a: canonical bytes and decimal strings (AC 6)."""

from __future__ import annotations

import hashlib
from decimal import Decimal

import pytest

from breezy.persistence.autonomy.canonical import (
    CanonicalTypeError,
    canonical_json,
    decimal_str,
    sha256_hex,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("-0", "0"),
        ("0E-10", "0"),
        ("0", "0"),
        ("1E+2", "100"),
        ("1.50", "1.5"),
        ("-12.340", "-12.34"),
        ("0.0000001", "0.0000001"),
        ("123456789012345678", "123456789012345678"),
    ],
)
def test_decimal_str_goldens(raw: str, expected: str) -> None:
    assert decimal_str(Decimal(raw)) == expected


@pytest.mark.parametrize("raw", ["NaN", "sNaN", "Infinity", "-Infinity"])
def test_decimal_str_refuses_non_finite(raw: str) -> None:
    with pytest.raises(CanonicalTypeError):
        decimal_str(Decimal(raw))


def test_decimal_str_refuses_more_than_38_digits() -> None:
    at_limit = Decimal("1." + "1" * 37)
    assert decimal_str(at_limit) == "1." + "1" * 37
    with pytest.raises(CanonicalTypeError):
        decimal_str(Decimal("1." + "1" * 38))


@pytest.mark.parametrize("raw", ["1E+19", "1E-19", "-1E+19"])
def test_decimal_str_refuses_adjusted_beyond_18(raw: str) -> None:
    with pytest.raises(CanonicalTypeError):
        decimal_str(Decimal(raw))


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("1E+18", "1000000000000000000"), ("1E-18", "0.000000000000000001")],
)
def test_decimal_str_accepts_adjusted_at_18(raw: str, expected: str) -> None:
    assert decimal_str(Decimal(raw)) == expected


def test_decimal_str_refuses_non_decimal() -> None:
    with pytest.raises(CanonicalTypeError):
        decimal_str(1)  # type: ignore[arg-type]


def test_canonical_json_golden_record_sorted_compact() -> None:
    value = {"b": [1, None, True], "a": {"z": "x", "y": Decimal("1.50")}}
    assert canonical_json(value) == b'{"a":{"y":"1.5","z":"x"},"b":[1,null,true]}'


def test_canonical_json_golden_tuple_and_empty() -> None:
    assert canonical_json({"t": (1, 2), "e": {}, "l": []}) == b'{"e":{},"l":[],"t":[1,2]}'


def test_canonical_json_golden_unicode_is_utf8_not_escaped() -> None:
    assert canonical_json({"k": "é€😀"}) == '{"k":"é€😀"}'.encode()


def test_canonical_json_is_key_order_independent() -> None:
    assert canonical_json({"a": 1, "b": 2}) == canonical_json({"b": 2, "a": 1})


def test_canonical_json_top_level_scalars() -> None:
    assert canonical_json(None) == b"null"
    assert canonical_json(False) == b"false"
    assert canonical_json(7) == b"7"


def test_canonical_json_decimal_normalised_inside_containers() -> None:
    assert canonical_json([Decimal("-0"), Decimal("1E+2")]) == b'["0","100"]'


@pytest.mark.parametrize(
    "bad",
    [
        {1: "x"},
        {None: "x"},
        {"a": {2: 1}},
        1.5,
        {"a": 0.0},
        [float("nan")],
        {"a": "\ud800"},
        {"\udfff": 1},
        {1, 2},
        b"bytes",
        object(),
        {"a": [object()]},
        Decimal("NaN"),
    ],
)
def test_canonical_json_refuses(bad: object) -> None:
    with pytest.raises(CanonicalTypeError):
        canonical_json(bad)


def test_canonical_type_error_is_a_type_error() -> None:
    assert issubclass(CanonicalTypeError, TypeError)


def test_canonical_json_refuses_cycle() -> None:
    cyclic: list[object] = []
    cyclic.append(cyclic)
    with pytest.raises(CanonicalTypeError):
        canonical_json(cyclic)


def test_sha256_hex_matches_hashlib() -> None:
    assert sha256_hex(b"abc") == hashlib.sha256(b"abc").hexdigest()
    assert len(sha256_hex(b"")) == 64
