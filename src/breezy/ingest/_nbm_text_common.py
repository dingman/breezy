"""Shared pure helpers between the NBM NBS and NBP text-bulletin parsers.

PURE: no I/O, no clock access, no `nautilus_trader` import, no
`breezy.strategy`/`breezy.runtime` import. `nbm_forecast_parse.py` (NBS) and
`nbm_quantile_parse.py` (NBP) both parse a per-station header carrying
`(year, month, day, cycle)`, a row-label-then-data grid, and the same
three-way TXN-cell absence taxonomy (`not_published`/`sentinel`/
`parse_failure`) -- this module is the ONE copy of each of those three
pieces, extracted so the two parsers stop carrying byte-identical private
copies (SL-2 review, HIGH/DRY).
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Final

from breezy.domain.forecast_point import forecast_value_or_none

__all__ = ["absence_from_token", "cycle_runtime_ns", "row_label"]

_NS_PER_SECOND: Final[int] = 1_000_000_000

#: Matches the leading alphanumeric token of a grid row, regardless of the
#: label's own width -- one implementation for both NBS's fixed 4-character
#: label field (`UTC`, `FHR`, `TXN`) and NBP's variable-width one (`UTC`,
#: `FHR`, `TXNMN`, `TXNP1`, ...). A blank/separator line has no such token.
_ROW_LABEL_RE: Final[re.Pattern[str]] = re.compile(r"^\s*(?P<label>[A-Z0-9]+)")


def row_label(line: str) -> str:
    """Return a grid row's leading label token, or `''` for a blank line."""
    match = _ROW_LABEL_RE.match(line)
    if match is None:
        return ""
    return match.group("label")


def cycle_runtime_ns(match: re.Match[str]) -> int:
    """UNIX nanoseconds of a station header's cycle instant.

    `match` must carry `year`/`month`/`day`/`cycle` (a 4-digit `HHMM`)
    named groups -- both parsers' station-header regexes do.
    """
    cycle = match.group("cycle")
    hour, minute = int(cycle[:2]), int(cycle[2:])
    instant = dt.datetime(
        int(match.group("year")),
        int(match.group("month")),
        int(match.group("day")),
        hour,
        minute,
        tzinfo=dt.UTC,
    )
    return int(instant.timestamp()) * _NS_PER_SECOND


def absence_from_token(token: str) -> tuple[float | None, str | None]:
    """Return `(value_f, absence_reason)` for one TXN cell. Never invents a value."""
    if not token:
        return None, "not_published"
    try:
        raw = float(int(token))
    except ValueError:
        return None, "parse_failure"
    value = forecast_value_or_none(raw)
    if value is None:
        return None, "sentinel"
    return value, None
