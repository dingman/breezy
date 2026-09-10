"""Bounded offer tape for continuous-rung-hold (L-29).

Every eligible snapshot (Take and retry-Refuse) is recorded. The in-memory
buffer is a ``deque(maxlen=...)`` so a long-running shadow cannot grow
without bound. Optional JSONL is a named production consumer; tests inject
a throwaway path, never the live exec-state DB.
"""

from __future__ import annotations

import json
import logging
from collections import deque
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final

__all__ = ["DEFAULT_OFFER_TAPE_MAXLEN", "OfferTape", "OfferTapeRecord"]

logger = logging.getLogger(__name__)

DEFAULT_OFFER_TAPE_MAXLEN: Final[int] = 8192


@dataclass(frozen=True, slots=True)
class OfferTapeRecord:
    """One eligible snapshot. Money fields are Decimal strings."""

    station: str
    climate_day: str
    instrument_id: str
    ask: str
    size: int
    reason: str
    ts_event: int
    hour_lst: int
    width_code: int
    m_code: int
    trigger: str
    quote_age_ns: int | None
    minutes_since_window_open: int
    prior_eligible_snaps: int
    illegal_cell: bool
    source: str


class OfferTape:
    """Bounded eligible-snapshot tape. Memory is O(1) in message count."""

    def __init__(
        self,
        path: Path | None = None,
        *,
        maxlen: int = DEFAULT_OFFER_TAPE_MAXLEN,
    ) -> None:
        if maxlen < 1:
            raise ValueError("offer tape maxlen must be >= 1")
        self._buf: deque[OfferTapeRecord] = deque(maxlen=maxlen)
        self._path = path
        self._maxlen = maxlen
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def maxlen(self) -> int:
        return self._maxlen

    def __len__(self) -> int:
        return len(self._buf)

    def records(self) -> tuple[OfferTapeRecord, ...]:
        return tuple(self._buf)

    def append(self, record: OfferTapeRecord) -> None:
        """Record into the bounded in-memory deque, then best-effort JSONL.

        The in-memory record above always happens first and unconditionally:
        a disk error on the optional JSONL sidecar must never propagate out
        of a live strategy's `on_quote_tick`/`on_data` (this is called
        directly from `ContinuousRungHoldStrategy._hunt_tick`), so it is
        caught and logged here rather than left to the caller.
        """
        self._buf.append(record)
        if self._path is None:
            return
        line = json.dumps(asdict(record), sort_keys=True)
        try:
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(line)
                handle.write("\n")
        except OSError:
            logger.exception("OfferTape: failed to append to %s", self._path)

    def as_dicts(self) -> tuple[Mapping[str, object], ...]:
        return tuple(asdict(record) for record in self._buf)
