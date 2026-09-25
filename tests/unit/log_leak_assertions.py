"""Shared helper: assert a sensitive value never leaked into captured text.

Not a test module: a helper, in the shape of ``operator_control_env.py``.

WHY THIS EXISTS
----------------

``test_app_trade_main_permit_logging.py`` asserted a set of sensitive values
(``_SENSITIVE_VALUES``, including the bare digits ``"100"``) were each absent
from ``caplog.text`` via a plain ``value not in text`` substring check. That
check is a false-positive generator for any sensitive value that looks like a
number: the permit log line legitimately prints nanosecond timestamps (e.g.
``issued_at_ns=1790294992380210081``), and a purely numeric sensitive value
can appear as an *unrelated* substring of one of those timestamps by pure
chance of the wall clock -- the test then fails on a run where nothing
actually leaked.

The fix anchors the match to number boundaries instead of doing a bare
substring search: a match is only a real leak if it is not embedded inside a
longer run of digits. Two sibling test modules
(``test_polymarket_us_permit_issuance.py``,
``test_order_submission_permit_issuance.py``) run the identical
substring-over-a-tuple-of-sensitive-values pattern and share the same latent
risk, so they use this helper too rather than re-implementing (and
re-breaking) their own copy.

BOUNDARY RULE
-------------

A match is a leak only when:

* the character immediately before it is not a digit and not ``.`` (so a
  value can't be "found" as the tail of a longer number, or as the
  fractional remainder after a decimal point of an unrelated number); and
* the character immediately after it is not a digit (so it can't be found
  as the head of a longer number, e.g. ``"100"`` inside ``"1004"``).

A ``.`` immediately *after* the match is deliberately allowed: a value like
``"100"`` formatted as money (``"100.00"``) is a genuine leak of that value,
not a false positive, and must still be caught. Only a *leading* ``.`` is
treated the same as a leading digit, because a run of digits straight after a
decimal point (the fractional part of some other, unrelated number) is where
a short sensitive value like ``"00"`` would otherwise spuriously match.

This asymmetry is exactly what the RED/GREEN test pair in
``test_log_leak_assertions.py`` pins.
"""

from __future__ import annotations

import re
from collections.abc import Iterable


def value_leaked(haystack: str, value: str) -> bool:
    """Return True if ``value`` appears in ``haystack`` as a real leak.

    A non-numeric value (an email address, say) is matched as a plain
    substring, since it carries none of the digit-run false-positive risk a
    numeric value does. A value that is entirely digits/``.`` (an amount, a
    count) is matched at a number boundary -- see the module docstring.
    """
    escaped = re.escape(value)
    if re.fullmatch(r"[\d.]+", value):
        pattern = rf"(?<![\d.]){escaped}(?!\d)"
        return re.search(pattern, haystack) is not None
    return value in haystack


def assert_value_not_leaked(
    haystack: str, value: str, *, context: str = "a log record"
) -> None:
    """Assert ``value`` is not a real leak (see ``value_leaked``) in ``haystack``."""
    assert not value_leaked(haystack, value), f"{value!r} leaked into {context}"


def assert_no_values_leaked(
    haystack: str, values: Iterable[str], *, context: str = "a log record"
) -> None:
    """Assert none of ``values`` is a real leak in ``haystack``."""
    for value in values:
        assert_value_not_leaked(haystack, value, context=context)
