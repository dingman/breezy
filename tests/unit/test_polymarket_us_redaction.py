"""Redaction helpers for the Polymarket.us adapter (plan Step 2, SEC-3).

These helpers exist so that no code path in the adapter can emit an
``X-PM-Signature`` or ``X-PM-Access-Key`` value into a log line, an exception
message, or an evidence artefact.
"""

from __future__ import annotations

import pytest

from breezy.adapters.polymarket_us.redaction import (
    REDACTED,
    SENSITIVE_HEADERS,
    redact_headers,
    redact_text,
    redact_url,
)


def test_redact_headers_masks_access_key_signature_and_timestamp() -> None:
    headers = {
        "X-PM-Access-Key": "8f0a1e2c-key-id",
        "X-PM-Timestamp": "1700000000000",
        "X-PM-Signature": "c2lnbmF0dXJlLWJ5dGVz",
        "User-Agent": "breezy/1.0",
    }

    redacted = redact_headers(headers)

    assert redacted["X-PM-Access-Key"] == REDACTED
    assert redacted["X-PM-Timestamp"] == REDACTED
    assert redacted["X-PM-Signature"] == REDACTED
    # Non-sensitive headers survive so the view stays useful for debugging.
    assert redacted["User-Agent"] == "breezy/1.0"
    joined = repr(redacted)
    for secret in ("8f0a1e2c-key-id", "1700000000000", "c2lnbmF0dXJlLWJ5dGVz"):
        assert secret not in joined


def test_redact_headers_is_case_insensitive_on_the_header_name() -> None:
    redacted = redact_headers({"x-pm-signature": "abc", "AUTHORIZATION": "Bearer t"})

    assert redacted["x-pm-signature"] == REDACTED
    assert redacted["AUTHORIZATION"] == REDACTED


def test_redact_headers_does_not_mutate_the_input_mapping() -> None:
    headers = {"X-PM-Signature": "abc"}

    redact_headers(headers)

    assert headers == {"X-PM-Signature": "abc"}


def test_sensitive_headers_covers_both_the_signature_and_the_access_key() -> None:
    assert "x-pm-signature" in SENSITIVE_HEADERS
    assert "x-pm-access-key" in SENSITIVE_HEADERS


def test_redact_text_masks_every_supplied_secret() -> None:
    secrets = ["sUperSecretKeyId", "c2lnbmF0dXJl"]
    text = "auth failed for sUperSecretKeyId using signature c2lnbmF0dXJl (401)"

    scrubbed = redact_text(text, secrets)

    assert "sUperSecretKeyId" not in scrubbed
    assert "c2lnbmF0dXJl" not in scrubbed
    assert scrubbed.count(REDACTED) == 2
    assert "auth failed for" in scrubbed


def test_redact_text_ignores_empty_secrets_and_leaves_text_intact() -> None:
    assert redact_text("nothing to hide", ["", None or ""]) == "nothing to hide"


def test_redact_url_strips_query_values() -> None:
    scrubbed = redact_url("https://api.polymarket.us/v1/markets?apiKey=abc123&limit=5")

    assert "abc123" not in scrubbed
    assert "/v1/markets" in scrubbed
    assert "apiKey" in scrubbed


def test_redact_url_strips_userinfo_credentials() -> None:
    scrubbed = redact_url("https://user:hunter2@api.polymarket.us/v1/portfolio/positions")

    assert "hunter2" not in scrubbed
    assert "user:" not in scrubbed
    assert "api.polymarket.us" in scrubbed


@pytest.mark.parametrize("path", ["/v1/markets", "/v1/markets/"])
def test_redact_url_preserves_a_query_free_path_verbatim(path: str) -> None:
    assert redact_url(f"https://api.polymarket.us{path}").endswith(path)
