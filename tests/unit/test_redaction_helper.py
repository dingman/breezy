"""RED/GREEN coverage for ``tests/unit/redaction.py`` (SP-6 row 7)."""

from __future__ import annotations

import pytest

from tests.unit.redaction import assert_secret_absent, assert_value_absent


def test_matcher_flags_a_planted_secret() -> None:
    with pytest.raises(AssertionError):
        assert_value_absent("the sentinel 100 leaked here", "100")


def test_matcher_ignores_a_value_inside_an_epoch_ns_timestamp() -> None:
    # "100" is glued to a much longer digit run here -- no boundary match,
    # so this must NOT raise, even though "100" is a substring.
    assert_value_absent("issued_at_ns=1700000000000000100", "100")


def test_matcher_documents_its_glued_suffix_blind_spot() -> None:
    """Pins the STATED trade-off as a property: a sentinel glued to a
    non-separator suffix is a genuine MISS, not a bug -- assert_secret_absent
    has no such blind spot and is the one to use for a real secret."""
    text_with_glued_leak = "duration=100ms"

    assert_value_absent(text_with_glued_leak, "100")  # MISSES it -- documented

    with pytest.raises(AssertionError):
        assert_secret_absent(text_with_glued_leak, "100ms")  # catches it
