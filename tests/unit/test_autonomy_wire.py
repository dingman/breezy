"""ARCH-0 seam 2a: exact-parse wire validators (AC 5)."""

from __future__ import annotations

import re
from decimal import Decimal

import pytest

from breezy.persistence.autonomy import wire
from breezy.persistence.autonomy.wire import (
    ACCEPTED_SCHEMAS,
    FAMILY_ID_RE,
    SHA256_RE,
    WireRefusalReason,
    WireRefused,
    parse_json_exact,
)
from breezy.strategy.current_rung_hold.trial_day_latch import FAMILY_ID_PATTERN

_GOOD_SCHEMA = min(ACCEPTED_SCHEMAS)


def _reason(raw: bytes | str) -> WireRefusalReason:
    with pytest.raises(WireRefused) as info:
        parse_json_exact(raw)
    return info.value.reason


def test_parse_returns_plain_object_for_valid_bytes() -> None:
    obj = parse_json_exact(b'{"a":1,"b":[true,null,"x"],"c":{"d":-3}}')
    assert obj == {"a": 1, "b": [True, None, "x"], "c": {"d": -3}}


def test_parse_accepts_str_input() -> None:
    assert parse_json_exact('{"a":1}') == {"a": 1}


def test_parse_accepts_known_schema() -> None:
    assert parse_json_exact(f'{{"schema":"{_GOOD_SCHEMA}"}}'.encode())["schema"] == _GOOD_SCHEMA


def test_closed_reason_set() -> None:
    assert {r.value for r in WireRefusalReason} == {
        "malformed_json",
        "not_an_object",
        "duplicate_key",
        "non_finite_number",
        "float_token",
        "missing_key",
        "unknown_key",
        "wrong_type",
        "bool_as_int",
        "unknown_schema",
        "bad_value",
    }


def test_duplicate_key_refused_at_top_and_nested() -> None:
    assert _reason(b'{"a":1,"a":2}') is WireRefusalReason.DUPLICATE_KEY
    assert _reason(b'{"x":{"a":1,"a":1}}') is WireRefusalReason.DUPLICATE_KEY


@pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity"])
def test_non_finite_constants_refused(token: str) -> None:
    assert _reason(f'{{"a":{token}}}'.encode()) is WireRefusalReason.NON_FINITE_NUMBER


@pytest.mark.parametrize("token", ["1.0", "1.50", "0.0", "1e2", "1E+2", "-0.5", "1e-3", "1e999"])
def test_any_float_token_refused(token: str) -> None:
    assert _reason(f'{{"a":{token}}}'.encode()) is WireRefusalReason.FLOAT_TOKEN


def test_float_token_refused_inside_list() -> None:
    assert _reason(b'{"a":[1,2.5]}') is WireRefusalReason.FLOAT_TOKEN


@pytest.mark.parametrize("raw", [b"", b"{", b'{"a":}', b"\xff\xfe", b'{"a":1} x', b"{'a':1}"])
def test_malformed_refused(raw: bytes) -> None:
    assert _reason(raw) is WireRefusalReason.MALFORMED_JSON


@pytest.mark.parametrize("raw", [b"[1]", b"1", b'"s"', b"null", b"true"])
def test_top_level_must_be_object(raw: bytes) -> None:
    assert _reason(raw) is WireRefusalReason.NOT_AN_OBJECT


def test_unknown_schema_refused() -> None:
    assert _reason(b'{"schema":"nope/v9"}') is WireRefusalReason.UNKNOWN_SCHEMA


def test_non_string_schema_refused() -> None:
    assert _reason(b'{"schema":1}') is WireRefusalReason.UNKNOWN_SCHEMA


def test_accepted_schemas_is_frozen_and_versioned() -> None:
    assert isinstance(ACCEPTED_SCHEMAS, frozenset)
    assert ACCEPTED_SCHEMAS
    assert all(re.fullmatch(r"[a-z_0-9]+/v[0-9]+", s) for s in ACCEPTED_SCHEMAS)


def test_wire_refused_carries_reason_and_str() -> None:
    err = WireRefused(WireRefusalReason.MISSING_KEY, "k")
    assert err.reason is WireRefusalReason.MISSING_KEY
    assert "missing_key" in str(err)


def test_wire_refusal_reason_is_strenum() -> None:
    assert str(WireRefusalReason.BOOL_AS_INT) == "bool_as_int"


# --- require_* validators -------------------------------------------------


def _refused(call: object) -> WireRefusalReason:
    assert callable(call)
    with pytest.raises(WireRefused) as info:
        call()
    return info.value.reason


def test_require_exact_keys_ok() -> None:
    wire.require_exact_keys({"a": 1, "b": 2}, required={"a", "b"})
    wire.require_exact_keys({"a": 1}, required={"a"}, optional={"b"})


def test_require_exact_keys_missing_and_unknown() -> None:
    assert _refused(lambda: wire.require_exact_keys({"a": 1}, required={"a", "b"})) is (
        WireRefusalReason.MISSING_KEY
    )
    assert _refused(lambda: wire.require_exact_keys({"a": 1, "z": 2}, required={"a"})) is (
        WireRefusalReason.UNKNOWN_KEY
    )


def test_require_str() -> None:
    assert wire.require_str({"a": "x"}, "a") == "x"
    assert _refused(lambda: wire.require_str({"a": 1}, "a")) is WireRefusalReason.WRONG_TYPE
    assert _refused(lambda: wire.require_str({}, "a")) is WireRefusalReason.MISSING_KEY


def test_require_int_refuses_bool_as_int() -> None:
    assert wire.require_int({"a": 5}, "a") == 5
    assert _refused(lambda: wire.require_int({"a": True}, "a")) is WireRefusalReason.BOOL_AS_INT
    assert _refused(lambda: wire.require_int({"a": False}, "a")) is WireRefusalReason.BOOL_AS_INT
    assert _refused(lambda: wire.require_int({"a": "5"}, "a")) is WireRefusalReason.WRONG_TYPE


def test_require_bool_refuses_int() -> None:
    assert wire.require_bool({"a": True}, "a") is True
    assert _refused(lambda: wire.require_bool({"a": 1}, "a")) is WireRefusalReason.WRONG_TYPE


def test_require_ns_nonnegative_int() -> None:
    assert wire.require_ns({"a": 0}, "a") == 0
    assert _refused(lambda: wire.require_ns({"a": -1}, "a")) is WireRefusalReason.BAD_VALUE
    assert _refused(lambda: wire.require_ns({"a": True}, "a")) is WireRefusalReason.BOOL_AS_INT


def test_require_sha256() -> None:
    good = "0" * 64
    assert wire.require_sha256({"a": good}, "a") == good
    for bad in ("0" * 63, "A" * 64, "g" * 64, good + "\n"):
        assert _refused(lambda bad=bad: wire.require_sha256({"a": bad}, "a")) is (
            WireRefusalReason.BAD_VALUE
        )
    assert _refused(lambda: wire.require_sha256({"a": 1}, "a")) is WireRefusalReason.WRONG_TYPE


def test_require_enum() -> None:
    assert wire.require_enum({"a": "x"}, "a", allowed={"x", "y"}) == "x"
    assert _refused(lambda: wire.require_enum({"a": "z"}, "a", allowed={"x"})) is (
        WireRefusalReason.BAD_VALUE
    )
    assert _refused(lambda: wire.require_enum({"a": 1}, "a", allowed={"x"})) is (
        WireRefusalReason.WRONG_TYPE
    )


def test_require_decimal_str_canonical_only() -> None:
    assert wire.require_decimal_str({"a": "1.5"}, "a") == Decimal("1.5")
    assert wire.require_decimal_str({"a": "0"}, "a") == Decimal(0)
    for bad in ("1.50", "-0", "1E+2", "NaN", "", " 1", "01", "+1"):
        assert _refused(lambda bad=bad: wire.require_decimal_str({"a": bad}, "a")) is (
            WireRefusalReason.BAD_VALUE
        ), bad
    assert _refused(lambda: wire.require_decimal_str({"a": 1}, "a")) is (
        WireRefusalReason.WRONG_TYPE
    )


def test_sha256_re_matches_spec() -> None:
    assert SHA256_RE.fullmatch("a" * 64)
    assert not SHA256_RE.fullmatch("a" * 64 + "\n")
    assert not SHA256_RE.fullmatch("A" * 64)


def test_family_id_re_equals_trial_day_latch_pattern() -> None:
    assert FAMILY_ID_RE.pattern == FAMILY_ID_PATTERN.pattern
    assert FAMILY_ID_RE.flags == FAMILY_ID_PATTERN.flags
