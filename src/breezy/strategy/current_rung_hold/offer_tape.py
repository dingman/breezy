"""Bounded offer tape for continuous-rung-hold (L-29).

Every eligible snapshot (Take and retry-Refuse) is recorded. The in-memory
buffer is a ``deque(maxlen=...)`` so a long-running shadow cannot grow
without bound. Optional JSONL is a named production consumer; tests inject
a throwaway path, never the live exec-state DB.

GAP fix (2026-09-15, offer-tape postmortem observability): a 09-15 SFO take
could not be reconstructed after the fact -- the row carried no
``p_bound``/``break_even``/running-max interval/staleness/side/fee
coefficient, so nobody could tell WHY that snapshot cleared. The fields
added below are purely additive (old keys, old positions, unchanged;
``OfferTape``/``ContinuousRungHoldStrategy`` behaviour is byte-identical --
L-34/D3): this module never decides which snapshot becomes a trial, never
touches the latch, and never changes an admission/refusal outcome.
"""

from __future__ import annotations

import json
import logging
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Final

__all__ = ["DEFAULT_OFFER_TAPE_MAXLEN", "OfferTape", "OfferTapeRecord"]

logger = logging.getLogger(__name__)

DEFAULT_OFFER_TAPE_MAXLEN: Final[int] = 8192


@dataclass(frozen=True, slots=True)
class OfferTapeRecord:
    """One eligible snapshot. Money fields are Decimal strings.

    The GAP-fix fields below are the exception to that "Decimal strings"
    convention: they are typed ``Decimal | None`` in-memory (never a bare
    ``float``) and converted to strings only at :meth:`to_dict` time,
    alongside the two Fahrenheit running-max bounds (also carried as
    ``Decimal`` here purely so every numeric postmortem field shares one
    quantize-free serialization path -- they are whole-degree integers, not
    money).
    """

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
    #: "YES" or "NO" -- which leg this snapshot evaluated.
    side: str = "YES"
    #: The side's own edge estimand (`P_HOLD_LOWER` for YES, `1 -
    #: P_HOLD_UPPER` for NO) -- `None` when the decision never reached the
    #: table lookup (e.g. `not_executable`, `observation_unavailable`).
    p_bound: Decimal | None = None
    #: `price + fee(price)` -- `None` under the same conditions as `p_bound`.
    break_even: Decimal | None = None
    #: The running-max Fahrenheit interval `[lower, upper]` this snapshot was
    #: evaluated against.
    running_max_lower: Decimal | None = None
    running_max_upper: Decimal | None = None
    #: `True` iff the running max had collapsed to an exact METAR reading.
    running_max_exact: bool = False
    #: Age (ns) of the running-max observation at evaluation time.
    staleness_ns: int | None = None
    #: The fee coefficient the decision was evaluated under.
    fee_coefficient: Decimal | None = None
    #: Valid time (ns) of the observation that SET the running max.
    observed_at_ns: int | None = None
    #: The NO-side latch-gate outcome (`sibling_leg_traded`,
    #: `station_day_admission`, a day-budget/consumed reason, or
    #: `"admitted"`) -- `None` for YES (no such gate runs at this layer) and
    #: for a NO snapshot that never reached the gate chain (economic refuse).
    admission_reason: str | None = None
    #: The FINAL outcome this row represents -- "take" (would-arm/armed),
    #: "refuse", or "wait". Never "wait" in practice: a WAIT tick never
    #: reaches `OfferTape.append` at all (unbounded-log guard), so this
    #: field is always "take" or "refuse" for every row that exists.
    decision: str = "refuse"

    def to_dict(self) -> dict[str, object]:
        """Field-by-field serialization -- never ``dataclasses.asdict``.

        ``asdict`` deep-copies every field value and is banned repo-wide
        under a closed allowlist (``test_polymarket_us_credential_
        serialization.py``): an unreviewed call site can leak or re-pickle
        credential material regardless of what its argument is named. This
        record carries no credential-bearing field, but the fix is to never
        need the allowlist at all -- explicit, named fields, reviewable at a
        glance.
        """
        return {
            "station": self.station,
            "climate_day": self.climate_day,
            "instrument_id": self.instrument_id,
            "ask": self.ask,
            "size": self.size,
            "reason": self.reason,
            "ts_event": self.ts_event,
            "hour_lst": self.hour_lst,
            "width_code": self.width_code,
            "m_code": self.m_code,
            "trigger": self.trigger,
            "quote_age_ns": self.quote_age_ns,
            "minutes_since_window_open": self.minutes_since_window_open,
            "prior_eligible_snaps": self.prior_eligible_snaps,
            "illegal_cell": self.illegal_cell,
            "source": self.source,
            "side": self.side,
            "p_bound": None if self.p_bound is None else str(self.p_bound),
            "break_even": None if self.break_even is None else str(self.break_even),
            "running_max_lower": (
                None if self.running_max_lower is None else str(self.running_max_lower)
            ),
            "running_max_upper": (
                None if self.running_max_upper is None else str(self.running_max_upper)
            ),
            "running_max_exact": self.running_max_exact,
            "staleness_ns": self.staleness_ns,
            "fee_coefficient": (
                None if self.fee_coefficient is None else str(self.fee_coefficient)
            ),
            "observed_at_ns": self.observed_at_ns,
            "admission_reason": self.admission_reason,
            "decision": self.decision,
        }


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
        line = json.dumps(record.to_dict(), sort_keys=True)
        try:
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(line)
                handle.write("\n")
        except OSError:
            logger.exception("OfferTape: failed to append to %s", self._path)

    def as_dicts(self) -> tuple[Mapping[str, object], ...]:
        return tuple(record.to_dict() for record in self._buf)
