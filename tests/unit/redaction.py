"""Shared test-only redaction matchers for A4 acceptance evidence (SP-6 row 7).

A HELPER module, never collected as tests itself (no ``test_`` prefix).
Used by ``test_redaction_helper.py`` and, forward-looking, by any A4/A9/A12
acceptance test that must assert a secret (a webhook URL) or a sentinel
value never leaked into captured output.

**Documented blind spot.** :func:`assert_value_absent` matches ``value`` at
a digit/word boundary so it does not false-positive on an unrelated
substring match inside a longer token that merely CONTAINS the same
digits (the epoch-nanosecond false positive this suite has hit before):
checking a small sentinel like ``"100"`` against a log line containing
``"...at_ns=1700000000000000100"`` must not flag every log line that
happens to end in the same digits. The trade-off is real and named, not
hidden: ``assert_value_absent`` **will MISS** a leak glued to a
non-separator suffix -- e.g. checking for ``"100"`` will not catch
``"100ms"`` or ``"1000.00USD"`` (no boundary between the sentinel and the
following character). :func:`assert_secret_absent` has no such blind
spot -- it is a plain substring check -- and is the one to use for an
actual SECRET (the webhook URL), never the boundary-aware matcher, which
exists only for a value that is also a legitimately-occurring standalone
number elsewhere in the same output. Both are for NEW log/receipt sites
this plan adds; neither retrofits an existing emit site.
"""

from __future__ import annotations

import re

__all__ = ["assert_secret_absent", "assert_value_absent"]


def assert_value_absent(text: str, value: str) -> None:
    """Assert ``value`` does not appear in ``text`` at a digit/word
    boundary. See the module docstring for the documented glued-suffix
    blind spot this deliberately accepts."""
    pattern = re.compile(rf"(?<![\w]){re.escape(value)}(?![\w])")
    assert not pattern.search(text), f"a boundary-matched sentinel leaked into: {text!r}"


def assert_secret_absent(text: str, secret: str) -> None:
    """Assert ``secret`` does not appear in ``text`` anywhere, as a plain
    substring -- no blind spot. Use for an actual secret (the webhook
    URL), never a value that also occurs legitimately as part of a
    longer number elsewhere in the same output."""
    assert secret not in text, "a secret leaked into captured output"
