"""Pins the shared NBS/NBP text-bulletin helpers (SL-2 review, HIGH/DRY).

`nbm_forecast_parse.py` (NBS) and `nbm_quantile_parse.py` (NBP) used to
carry byte-identical private copies of `_row_label`, `_cycle_runtime_ns` and
`_absence_from_token`. This module is now the ONE copy of each; both
parsers import it. These tests pin the shared behaviour directly, so a
future edit to either parser cannot silently fork it again.
"""

from __future__ import annotations

import datetime as dt
import re

from breezy.ingest._nbm_text_common import (
    absence_from_token,
    cycle_runtime_ns,
    row_label,
)

NS = 1_000_000_000


# ---------------------------------------------------------------------------
# row_label
# ---------------------------------------------------------------------------


def test_row_label_reads_a_three_character_label() -> None:
    assert row_label(" UTC    12| 00  12") == "UTC"
    assert row_label(" FHR    23| 35  47") == "FHR"


def test_row_label_reads_a_five_character_label() -> None:
    assert row_label(" TXNMN  67| 82  68") == "TXNMN"
    assert row_label(" TXNP9  69| 86  71") == "TXNP9"


def test_row_label_of_a_blank_line_is_empty() -> None:
    assert row_label("                                                       ") == ""
    assert row_label("") == ""


# ---------------------------------------------------------------------------
# cycle_runtime_ns
# ---------------------------------------------------------------------------


def test_cycle_runtime_ns_reads_year_month_day_and_hhmm_cycle() -> None:
    pattern = re.compile(
        r"(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2}) (?P<cycle>\d{4})"
    )
    match = pattern.match("2026-09-28 1300")

    assert match is not None
    result = cycle_runtime_ns(match)

    expected = int(dt.datetime(2026, 9, 28, 13, 0, tzinfo=dt.UTC).timestamp()) * NS
    assert result == expected


def test_cycle_runtime_ns_reads_a_non_zero_minute() -> None:
    pattern = re.compile(
        r"(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2}) (?P<cycle>\d{4})"
    )
    match = pattern.match("2026-09-29 0100")

    assert match is not None
    result = cycle_runtime_ns(match)

    expected = int(dt.datetime(2026, 9, 29, 1, 0, tzinfo=dt.UTC).timestamp()) * NS
    assert result == expected


# ---------------------------------------------------------------------------
# absence_from_token
# ---------------------------------------------------------------------------


def test_absence_from_token_blank_is_not_published() -> None:
    assert absence_from_token("") == (None, "not_published")


def test_absence_from_token_sentinel_minus_99_is_sentinel() -> None:
    assert absence_from_token("-99") == (None, "sentinel")


def test_absence_from_token_sentinel_999_is_sentinel() -> None:
    assert absence_from_token("999") == (None, "sentinel")


def test_absence_from_token_unreadable_is_parse_failure() -> None:
    assert absence_from_token("**") == (None, "parse_failure")


def test_absence_from_token_a_genuine_value_passes_through() -> None:
    assert absence_from_token("84") == (84.0, None)


def test_absence_from_token_a_clamped_but_genuine_value_is_not_a_sentinel() -> None:
    """-98 and 998 are the NBM text-card's own display CLAMPS, not sentinels
    (only -99 is documented as the missing-data code); `forecast_value_or_none`
    already distinguishes the two, and this pins that distinction here too."""
    assert absence_from_token("-98") == (-98.0, None)
    assert absence_from_token("998") == (998.0, None)
