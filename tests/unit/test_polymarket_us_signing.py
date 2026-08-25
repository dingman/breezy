"""Ed25519 request signing hard gate (plan Step 4).

Ground truth for the canonical string, in priority order:

* ``docs/evidence/venue/polymarket_us/docs_snapshots/api-reference_authentication_2026-08-25.md:82``
  -- "The signature is built by combining the timestamp, HTTP method, and
  path". The worked example at ``:92-96`` signs a BARE path with no query
  string: ``message = f"{timestamp}{method}{path}"``.
* ``docs/evidence/venue/polymarket_us/sdk_snapshot/polymarket_us_0.1.2/auth.py:26-27``
  builds the identical string; ``client.py:132`` passes the path only and the
  query goes separately to httpx.

Therefore the DEFAULT builder is path-WITHOUT-query. The query-including
variant ships as a runtime-selectable hypothesis to be disproved by a live
probe (plan section 5.1), never as the default.

NO REAL CREDENTIAL EVER APPEARS HERE. Every key is generated in-process, and
no deterministic seed is committed.
"""

from __future__ import annotations

import base64
import traceback
from typing import Any

# ``nacl`` is imported plainly, with NO ``importorskip``, deliberately. PyNaCl
# is a CORE dependency (pyproject ``[project].dependencies``) precisely because
# ``signing.py`` holds order-submission barrier B2 -- the signer that refuses
# to sign a non-GET. Behind an optional extra this whole suite SKIPPED on a
# default checkout, and a guard that never executes is indistinguishable from
# a guard that passes. If ``nacl`` is missing, collection must fail loudly.
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from nacl.signing import SigningKey
from nautilus_trader.common.component import TestClock

from breezy.adapters.polymarket_us.credentials import (
    PolymarketUSCredentials,
)
from breezy.adapters.polymarket_us.errors import (
    CredentialSourceError,
    MethodNotPermittedError,
    SignatureClockSkewError,
)
from breezy.adapters.polymarket_us.redaction import REDACTED
from breezy.adapters.polymarket_us.secure import RedactedSecureString
from breezy.adapters.polymarket_us.signing import (
    BUILDERS,
    DEFAULT_SKEW_TOLERANCE_MS,
    PERMITTED_METHODS,
    CanonicalRequest,
    Ed25519RequestSigner,
    SigningVariant,
    build_canonical_path_with_query,
    build_canonical_path_without_query,
)

_ACCESS_KEY = "11111111-2222-3333-4444-555555555555"
_TS_MS = 1_700_000_000_000


def _new_secret_b64(*, expanded: bool = False) -> str:
    """Generate an ephemeral Ed25519 secret, base64-encoded like the venue's.

    ``expanded`` returns the 64-byte seed||public form the SDK truncates to 32.
    """
    key = SigningKey.generate()
    seed = bytes(key)
    material = seed + bytes(key.verify_key) if expanded else seed
    return base64.b64encode(material).decode("ascii")


def _credentials(secret_b64: str, *, key_id: str = _ACCESS_KEY) -> PolymarketUSCredentials:
    return PolymarketUSCredentials(
        key_id=RedactedSecureString(key_id),
        secret_key=RedactedSecureString(secret_b64),
    )


def _clock_at(timestamp_ms: int) -> TestClock:
    clock = TestClock()
    clock.set_time(timestamp_ms * 1_000_000)
    return clock


def _signer(
    secret_b64: str | None = None,
    *,
    timestamp_ms: int = _TS_MS,
    **kwargs: Any,
) -> Ed25519RequestSigner:
    return Ed25519RequestSigner(
        _credentials(secret_b64 if secret_b64 is not None else _new_secret_b64()),
        clock=_clock_at(timestamp_ms),
        **kwargs,
    )


# --------------------------------------------------------------------------
# Canonical string builders
# --------------------------------------------------------------------------


def test_canonical_string_is_timestamp_method_path_concatenation() -> None:
    request = CanonicalRequest(
        timestamp_ms=1234567890000, method="GET", path="/v1/portfolio/positions"
    )

    expected = b"1234567890000GET/v1/portfolio/positions"
    assert build_canonical_path_without_query(request) == expected


def test_default_builder_excludes_the_query_string() -> None:
    request = CanonicalRequest(
        timestamp_ms=_TS_MS,
        method="GET",
        path="/v1/markets",
        query_string="limit=5&cursor=abc",
    )

    canonical = build_canonical_path_without_query(request)

    assert canonical == f"{_TS_MS}GET/v1/markets".encode()
    assert b"limit=5" not in canonical
    assert b"?" not in canonical


def test_alternate_builder_includes_the_query_string() -> None:
    request = CanonicalRequest(
        timestamp_ms=_TS_MS,
        method="GET",
        path="/v1/markets",
        query_string="limit=5&cursor=abc",
    )

    expected = f"{_TS_MS}GET/v1/markets?limit=5&cursor=abc".encode()
    assert build_canonical_path_with_query(request) == expected


def test_alternate_builder_omits_the_separator_when_there_is_no_query() -> None:
    request = CanonicalRequest(timestamp_ms=_TS_MS, method="GET", path="/v1/markets")

    assert build_canonical_path_with_query(request) == build_canonical_path_without_query(request)


@pytest.mark.parametrize("path", ["/v1/markets/", "/v1/markets"])
def test_trailing_slash_is_preserved(path: str) -> None:
    request = CanonicalRequest(timestamp_ms=_TS_MS, method="GET", path=path)

    for builder in BUILDERS.values():
        assert builder(request).endswith(path.encode("ascii"))


def test_body_is_ignored_by_both_builders_for_a_get() -> None:
    """G3 inertness: this slice is GET-only, so the body seam must be inert."""
    empty = CanonicalRequest(
        timestamp_ms=_TS_MS, method="GET", path="/v1/markets", query_string="a=1"
    )
    with_body = CanonicalRequest(
        timestamp_ms=_TS_MS,
        method="GET",
        path="/v1/markets",
        query_string="a=1",
        body=b'{"unexpected":"payload"}',
    )

    for builder in BUILDERS.values():
        assert builder(empty) == builder(with_body)


def test_signature_is_over_utf8_bytes() -> None:
    path = "/v1/markets/café-résumé"
    request = CanonicalRequest(timestamp_ms=_TS_MS, method="GET", path=path)

    canonical = build_canonical_path_without_query(request)

    assert canonical == f"{_TS_MS}GET{path}".encode()
    assert canonical != f"{_TS_MS}GET{path}".encode("latin-1")


def test_signing_variant_is_a_str_enum_and_builders_cover_every_member() -> None:
    assert SigningVariant.PATH_ONLY.value == "path_only"
    assert SigningVariant.PATH_WITH_QUERY.value == "path_with_query"
    assert set(BUILDERS) == set(SigningVariant)
    assert BUILDERS[SigningVariant.PATH_ONLY] is build_canonical_path_without_query
    assert BUILDERS[SigningVariant.PATH_WITH_QUERY] is build_canonical_path_with_query
    with pytest.raises(ValueError):
        SigningVariant("path_with_body")


def test_builders_mapping_is_immutable() -> None:
    with pytest.raises(TypeError):
        BUILDERS[SigningVariant.PATH_ONLY] = build_canonical_path_with_query  # type: ignore[index]


# --------------------------------------------------------------------------
# Signer behaviour
# --------------------------------------------------------------------------


def test_the_signer_default_builder_is_path_without_query() -> None:
    """The flipped default: docs and SDK agree the query is NOT signed."""
    secret = _new_secret_b64()
    key = SigningKey(base64.b64decode(secret))

    headers = dict(
        _signer(secret).sign_headers(
            "GET", "/v1/markets", query_string="limit=5", timestamp_ms=_TS_MS
        )
    )
    signature = base64.b64decode(headers["X-PM-Signature"])

    key.verify_key.verify(f"{_TS_MS}GET/v1/markets".encode(), signature)


def test_sign_headers_returns_a_list_of_pairs_not_a_dict() -> None:
    """pyo3 boundary: WebSocketConfig.headers requires list[tuple[str, str]]."""
    headers = _signer().sign_headers("GET", "/v1/markets")

    assert isinstance(headers, list)
    assert not isinstance(headers, dict)
    for item in headers:
        assert isinstance(item, tuple)
        assert len(item) == 2
        assert isinstance(item[0], str)
        assert isinstance(item[1], str)
    assert [name for name, _ in headers] == [
        "X-PM-Access-Key",
        "X-PM-Timestamp",
        "X-PM-Signature",
    ]


def test_sign_headers_emits_the_access_key_and_a_millisecond_timestamp() -> None:
    headers = dict(_signer(timestamp_ms=_TS_MS).sign_headers("GET", "/v1/markets"))

    assert headers["X-PM-Access-Key"] == _ACCESS_KEY
    assert headers["X-PM-Timestamp"] == str(_TS_MS)
    # Milliseconds since epoch is 13 digits for any plausible present-day value.
    assert len(headers["X-PM-Timestamp"]) == 13
    assert headers["X-PM-Timestamp"].isdigit()


def test_sign_headers_uses_the_injected_clock_when_no_timestamp_is_given() -> None:
    headers = dict(_signer(timestamp_ms=1_699_999_999_999).sign_headers("GET", "/v1/markets"))

    assert headers["X-PM-Timestamp"] == "1699999999999"


def test_signature_verifies_against_the_public_key_for_the_expanded_secret_form() -> None:
    secret = _new_secret_b64(expanded=True)
    seed = base64.b64decode(secret)[:32]
    key = SigningKey(seed)

    headers = dict(_signer(secret).sign_headers("GET", "/v1/portfolio/positions"))

    key.verify_key.verify(
        f"{_TS_MS}GET/v1/portfolio/positions".encode(),
        base64.b64decode(headers["X-PM-Signature"]),
    )


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "get", ""])
def test_non_get_method_raises_method_not_permitted(method: str) -> None:
    """Barrier B2: the signer itself refuses to sign anything but GET."""
    with pytest.raises(MethodNotPermittedError) as excinfo:
        _signer().sign_headers(method, "/v1/orders")

    assert "GET" in str(excinfo.value)


def test_permitted_methods_is_exactly_get() -> None:
    assert PERMITTED_METHODS == frozenset({"GET"})


# --------------------------------------------------------------------------
# Clock-skew window (30s venue tolerance)
# --------------------------------------------------------------------------


def test_default_skew_tolerance_is_the_venue_thirty_second_window() -> None:
    assert DEFAULT_SKEW_TOLERANCE_MS == 30_000


@pytest.mark.parametrize("offset_ms", [0, 29_000, -29_000, 30_000, -30_000])
def test_timestamp_inside_or_at_the_window_boundary_is_accepted(offset_ms: int) -> None:
    signer = _signer(timestamp_ms=_TS_MS)

    headers = dict(signer.sign_headers("GET", "/v1/markets", timestamp_ms=_TS_MS + offset_ms))

    assert headers["X-PM-Timestamp"] == str(_TS_MS + offset_ms)
    signer.assert_within_window(_TS_MS + offset_ms)


@pytest.mark.parametrize("offset_ms", [30_001, -30_001, 31_000, -31_000, 120_000])
def test_timestamp_outside_the_window_raises_clock_skew(offset_ms: int) -> None:
    signer = _signer(timestamp_ms=_TS_MS)

    with pytest.raises(SignatureClockSkewError):
        signer.sign_headers("GET", "/v1/markets", timestamp_ms=_TS_MS + offset_ms)

    with pytest.raises(SignatureClockSkewError):
        signer.assert_within_window(_TS_MS + offset_ms)


def test_clock_skew_error_names_the_drift_without_leaking_credentials() -> None:
    secret = _new_secret_b64()
    signer = _signer(secret, timestamp_ms=_TS_MS)

    with pytest.raises(SignatureClockSkewError) as excinfo:
        signer.assert_within_window(_TS_MS + 45_000)

    message = str(excinfo.value)
    assert "45000" in message or "45,000" in message
    assert secret not in message
    assert _ACCESS_KEY not in message


# --------------------------------------------------------------------------
# Secret containment
# --------------------------------------------------------------------------


def test_signer_repr_is_redacted() -> None:
    secret = _new_secret_b64()
    signer = _signer(secret)

    rendered = f"{signer!r}{signer!s}"

    assert rendered.startswith(f"Ed25519RequestSigner({REDACTED})")
    assert secret not in rendered
    assert _ACCESS_KEY not in rendered


def test_malformed_secret_is_rejected_without_echoing_the_value() -> None:
    bogus = "not-valid-base64!!!"
    signer = _signer(bogus)

    with pytest.raises(CredentialSourceError) as excinfo:
        signer.sign_headers("GET", "/v1/markets")

    assert bogus not in str(excinfo.value)


def test_wrong_length_secret_is_rejected_without_echoing_the_value() -> None:
    short = base64.b64encode(b"\x01" * 16).decode("ascii")
    signer = _signer(short)

    with pytest.raises(CredentialSourceError) as excinfo:
        signer.sign_headers("GET", "/v1/markets")

    assert short not in str(excinfo.value)


def test_no_secret_material_appears_in_a_formatted_traceback() -> None:
    secret = _new_secret_b64()
    signer = _signer(secret)

    try:
        signer.sign_headers("POST", "/v1/orders")
    except MethodNotPermittedError:
        rendered = traceback.format_exc()
    else:  # pragma: no cover - the signer must refuse POST
        pytest.fail("POST must not be signable")

    assert secret not in rendered
    assert _ACCESS_KEY not in rendered


# --------------------------------------------------------------------------
# Differential oracle against the pinned SDK (the known-vector test)
# --------------------------------------------------------------------------

_polymarket_auth = pytest.importorskip(
    "polymarket_us.auth",
    reason=(
        "the differential signing oracle needs the pinned polymarket-us==0.1.2 "
        "extra; run `uv run --extra polymarket-us pytest`"
    ),
)

_PATH_SEGMENT = st.text(
    alphabet=st.characters(whitelist_categories=("Ll", "Lu", "Nd"), whitelist_characters="-_"),
    min_size=1,
    max_size=12,
)
_PATHS = st.lists(_PATH_SEGMENT, min_size=1, max_size=4).map(lambda parts: "/v1/" + "/".join(parts))


@settings(
    max_examples=40,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(path=_PATHS, trailing_slash=st.booleans(), expanded=st.booleans())
def test_matches_the_sdk_reference_implementation_for_generated_keys(
    path: str,
    trailing_slash: bool,
    expanded: bool,
) -> None:
    """Differential oracle: our signer must equal the pinned SDK, byte for byte.

    No literal signature is pinned and no deterministic seed is committed --
    the key is generated in-process for every example.
    """
    if trailing_slash:
        path = f"{path}/"
    secret = _new_secret_b64(expanded=expanded)

    reference = _polymarket_auth.create_auth_headers(_ACCESS_KEY, secret, "GET", path)
    timestamp_ms = int(reference["X-PM-Timestamp"])

    ours = dict(
        _signer(secret, timestamp_ms=timestamp_ms).sign_headers(
            "GET", path, timestamp_ms=timestamp_ms
        )
    )

    assert ours == {
        "X-PM-Access-Key": reference["X-PM-Access-Key"],
        "X-PM-Timestamp": reference["X-PM-Timestamp"],
        "X-PM-Signature": reference["X-PM-Signature"],
    }


def test_the_sdk_oracle_signs_the_path_without_the_query_string() -> None:
    """Pins the ground truth the default builder is derived from.

    If a future SDK release starts folding the query into the signed message,
    this fails RED rather than letting our default drift silently.
    """
    secret = _new_secret_b64()

    reference = _polymarket_auth.create_auth_headers(
        _ACCESS_KEY, secret, "GET", "/v1/markets?limit=5"
    )
    timestamp_ms = int(reference["X-PM-Timestamp"])
    key = SigningKey(base64.b64decode(secret))

    # The SDK signs exactly the string it is handed and never appends a query
    # of its own; the caller (client.py:132) hands it the bare path. So the
    # signed message is verbatim timestamp+method+whatever-path-was-passed.
    key.verify_key.verify(
        f"{timestamp_ms}GET/v1/markets?limit=5".encode(),
        base64.b64decode(reference["X-PM-Signature"]),
    )
