"""AUT-1 on-change filter (C1 write-on-change, L-29; r8 section 3.3.3, D9).

Pure and deterministic: its output depends only on the input sequence, never on a clock, so the
node writer and the daily audit's replay (leg R2) agree. One filter per boot, never reset at a UTC
rollover. Nautilus-free.

``Take`` and ``TrySubmit`` always pass. Every other kind passes only when its ``(kind, reason)``
differs from the key's last recorded ``(kind, reason)``. A Take or TrySubmit also becomes the key's
last state, so the first refusal after a Take is a change and is recorded.
"""

import datetime as dt
from typing import Final

__all__ = ["ALWAYS_ADMITTED_KINDS", "OnChangeFilter"]

ALWAYS_ADMITTED_KINDS: Final[frozenset[str]] = frozenset({"Take", "TrySubmit"})
_NS_PER_DAY: Final[int] = 86_400 * 10**9
_EPOCH_ORDINAL: Final[int] = dt.date(1970, 1, 1).toordinal()

#: ``(station, climate_day ISO, rung_id, side)``.
ChangeKey = tuple[str, str, str, str]


def _utc_date_minus_one(eval_ns: int) -> str:
    """ISO date of ``eval_ns`` (UTC) minus one day: the eviction cutoff, from ``eval_ns`` alone."""
    ordinal = _EPOCH_ORDINAL + eval_ns // _NS_PER_DAY - 1
    return dt.date.fromordinal(ordinal).isoformat()


class OnChangeFilter:
    def __init__(self) -> None:
        self._last: dict[ChangeKey, tuple[str, str]] = {}

    def __len__(self) -> int:
        return len(self._last)

    def admit(self, key: ChangeKey, kind: str, reason: str, eval_ns: int) -> bool:
        if key not in self._last:
            self._evict(eval_ns)
        state = (kind, reason)
        changed = self._last.get(key) != state
        self._last[key] = state
        return changed or kind in ALWAYS_ADMITTED_KINDS

    def _evict(self, eval_ns: int) -> None:
        cutoff = _utc_date_minus_one(eval_ns)
        stale = [key for key in self._last if key[1] < cutoff]
        for key in stale:
            del self._last[key]
