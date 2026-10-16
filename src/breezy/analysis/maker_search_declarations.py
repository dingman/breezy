"""MAKER SEARCH-declaration registry (S2 second look, unit C1).

Each row is one dated SEARCH declaration: the stations and the closed climate-day
range it licenses, plus the sha256 of the committed declaration bytes. A post-freeze
station-day is cleared only by the row that CONTAINS it, with that row's sha256
(RA-13 B-3). Rows are disjoint, so one sha never licenses another row's days.

This module must not import ``breezy.analysis.maker_tape_census`` (that module
imports this one); ``MAKER_STATIONS`` is therefore a literal, aligned with the
census constant by a unit test.
"""

from __future__ import annotations

import datetime as dt
from typing import Final, NamedTuple

MAKER_STATIONS: Final[frozenset[str]] = frozenset({"LAX", "MDW", "MIA", "SFO"})

#: Environment variable the C4 trigger ``check`` sets (while it holds the trigger
#: lock) so a counts-only census before ``close`` can tell it is the sanctioned caller.
TRIGGER_CHECK_ENV: Final[str] = "BREEZY_MAKER_S2_TRIGGER_CHECK"


class SearchDeclared(NamedTuple):
    stations: frozenset[str]
    first_day: dt.date
    last_day: dt.date
    sha256: str


SEARCH_DECLARATIONS: Final[tuple[SearchDeclared, ...]] = (
    # Row 0: RULING_MAKER-S1_SEARCH_declaration_2026-10-12.md (6068a00e).
    SearchDeclared(
        MAKER_STATIONS,
        dt.date(2026, 9, 26),
        dt.date(2026, 10, 13),
        "38663caad38e455ab1512ca91a049f97d31c2dcfb1477c42db02ceca407abbc6",
    ),
    # Row 1: RULING_MAKER-S2_second_look_SEARCH_declaration_2026-10-16.md, S = 2026-10-14,
    # provisional ceiling 2026-11-15 (a later narrowing commit tightens it to [S, E]).
    SearchDeclared(
        MAKER_STATIONS,
        dt.date(2026, 10, 14),
        dt.date(2026, 11, 15),
        "bc15908052ff223abc889859133edb4645d4a6642b5fae559c0101251df9a05b",
    ),
)


def declaration_row(station: str, day: dt.date) -> int | None:
    """Index of the registry row whose station set and day range contain the station-day."""
    for index, row in enumerate(SEARCH_DECLARATIONS):
        if station in row.stations and row.first_day <= day <= row.last_day:
            return index
    return None


def is_trigger_check_token(token: object) -> bool:
    """The trigger-check marker contract: a non-blank string."""
    return isinstance(token, str) and bool(token.strip())
