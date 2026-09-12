"""RED/GREEN coverage for ``breezy.runtime.alert_detail`` (SP-6 row 6)."""

from __future__ import annotations

import pytest

from breezy.runtime.alert_detail import assert_payload_detail_is_safe
from breezy.runtime.health import MAX_ALERT_DETAIL_CHARS


def test_rejects_an_absolute_path() -> None:
    with pytest.raises(ValueError, match="path"):
        assert_payload_detail_is_safe("failed reading /home/operator/secret.env")


def test_rejects_a_url() -> None:
    with pytest.raises(ValueError, match="URL"):
        assert_payload_detail_is_safe("see https://example.invalid/webhook for details")


def test_rejects_an_at_sign() -> None:
    with pytest.raises(ValueError, match="'@'"):
        assert_payload_detail_is_safe("contact operator@example.invalid")


def test_rejects_over_max_chars() -> None:
    with pytest.raises(ValueError, match="MAX_ALERT_DETAIL_CHARS"):
        assert_payload_detail_is_safe("x" * (MAX_ALERT_DETAIL_CHARS + 1))


def test_accepts_a_short_closed_detail() -> None:
    assert_payload_detail_is_safe("trade_node_absent")  # must not raise


def test_the_error_names_the_rule_not_the_offending_text() -> None:
    secret_looking_text = "/home/operator/.config/breezy/alerts.env"
    with pytest.raises(ValueError) as exc_info:
        assert_payload_detail_is_safe(secret_looking_text)
    assert secret_looking_text not in str(exc_info.value)
