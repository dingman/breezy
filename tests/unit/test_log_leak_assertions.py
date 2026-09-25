"""Pins the number-boundary leak check in ``log_leak_assertions.py``.

The permit-log flake this closes: ``_SENSITIVE_VALUES`` contains the bare
digits ``"100"``, and a plain ``value not in caplog.text`` substring check
false-failed whenever ``"100"`` happened to appear inside an unrelated
nanosecond timestamp already in the log line (``issued_at_ns=...``). The
fix must still catch every REAL leak -- a standalone token, an ``=``-prefixed
value, or the integer part of a formatted decimal amount -- while no longer
tripping on a coincidental digit run inside a much larger number.
"""

from __future__ import annotations

from tests.unit.log_leak_assertions import value_leaked


def test_flags_value_surrounded_by_spaces() -> None:
    assert value_leaked(" 100 ", "100") is True


def test_flags_value_after_an_equals_sign() -> None:
    assert value_leaked("order_count=100", "100") is True


def test_flags_value_as_the_integer_part_of_a_formatted_amount() -> None:
    assert value_leaked("max_position_cost_usd=100.00", "100") is True


def test_does_not_flag_value_embedded_in_a_longer_digit_run() -> None:
    """The exact false positive: '100' sits inside a nanosecond timestamp."""
    assert value_leaked("issued_at_ns=1790294992380210081", "100") is False


def test_does_not_flag_value_as_prefix_of_a_longer_number() -> None:
    assert value_leaked("total=1004", "100") is False


def test_non_numeric_value_still_matched_as_a_plain_substring() -> None:
    assert value_leaked("operator=operator@example.com", "operator@example.com") is True
    assert value_leaked("operator=someone-else@example.com", "operator@example.com") is False
