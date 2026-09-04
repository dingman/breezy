"""Standard meteorological season lookup, shared by the archive study and
every strategy that needs to key into an archive cell by season.

Mirrors ``scripts/analysis/pmr_climatology_study.py:181-187``
(``_SEASON_BY_MONTH``/``season_for``) verbatim. Re-derived here rather than
imported: ``scripts/`` is unimportable from ``src/breezy`` (the layers
contract, ``pyproject.toml``), so this is the ONE place inside ``src/breezy``
that owns the table; every strategy imports this module instead of keeping
its own private copy.
"""

from __future__ import annotations

import datetime as dt
from typing import Final

__all__ = ["season_for"]

#: Mirrors ``scripts/analysis/pmr_climatology_study.py:182-187``
#: (``_SEASON_BY_MONTH``) verbatim.
_SEASON_BY_MONTH: Final[dict[int, str]] = {
    12: "DJF", 1: "DJF", 2: "DJF",
    3: "MAM", 4: "MAM", 5: "MAM",
    6: "JJA", 7: "JJA", 8: "JJA",
    9: "SON", 10: "SON", 11: "SON",
}


def season_for(climate_day: dt.date) -> str:
    """Standard meteorological season for ``climate_day``'s month."""
    return _SEASON_BY_MONTH[climate_day.month]
