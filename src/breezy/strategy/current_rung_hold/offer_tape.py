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
from typing import Final, cast

__all__ = [
    "DEFAULT_OFFER_TAPE_MAXLEN",
    "DEFAULT_OFFER_TAPE_SIDECAR_MAX_BYTES",
    "OfferTape",
    "OfferTapeRecord",
]

logger = logging.getLogger(__name__)

#: M2 review finding (commit 309dab6): the NO-side wiring (S3b) doubled the
#: rows-per-eligible-tick from one (YES only) to two (YES + NO), so the old
#: 8192 halved effective YES retention. Doubled to keep the same YES-row
#: history depth a long-running shadow had before the NO leg started
#: sharing this tape.
DEFAULT_OFFER_TAPE_MAXLEN: Final[int] = 16384

#: PROVISIONAL (2026-09-16 GAP fix, first live-day offer-tape postmortem):
#: the first live day wrote 7.9 MB / 9612 rows in ONE hour for ONE station
#: (one row per eligible snapshot per leg, by design -- the in-memory
#: deque is already bounded by :data:`DEFAULT_OFFER_TAPE_MAXLEN`, but the
#: JSONL sidecar was an unbounded plain append). 64 MiB is a round, generous
#: multiple of that measured rate (~8x the single busiest hour observed so
#: far) -- revisit once more live days are measured. Applies PER sidecar
#: file (one per climate day), never across files.
DEFAULT_OFFER_TAPE_SIDECAR_MAX_BYTES: Final[int] = 64 * 1024 * 1024

#: L1 review finding (commit 309dab6): the 16 keys every pre-GAP-fix JSONL
#: line carries -- :meth:`OfferTapeRecord.from_dict` requires all of them
#: and defaults the 11 GAP-fix keys added below, so an old line still reads
#: back cleanly.
_LEGACY_KEYS: Final[frozenset[str]] = frozenset(
    {
        "station",
        "climate_day",
        "instrument_id",
        "ask",
        "size",
        "reason",
        "ts_event",
        "hour_lst",
        "width_code",
        "m_code",
        "trigger",
        "quote_age_ns",
        "minutes_since_window_open",
        "prior_eligible_snaps",
        "illegal_cell",
        "source",
    }
)


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
    #: M1 review finding (commit 309dab6): `None` for a NO-side row whose
    #: Depth10 frame carried no bid at all -- there is no `1 - bid` ask to
    #: report, so this is "undefined", not the (unrelated) empty-string
    #: sentinel the pre-fix code wrote. Every other row (YES, and a NO row
    #: with a real bid) still carries a Decimal string exactly as before.
    ask: str | None
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
    #: INC-E3 (plan §3, PREREG v4 §3b/§12) adds "exit_fired"/"exit_refused"
    #: for the intra-day position monitor's own exit-decision rows -- a
    #: DIFFERENT source ("position_monitor", never "quote_tick"/"depth"),
    #: additive and never read by the entry-hunt's own consumers.
    decision: str = "refuse"
    #: INC-E3: the registered exit rule (``"R_THREAT"``/``"R_DEAD"``) an
    #: exit decision was evaluated under. `None` for every entry-hunt row
    #: (every row before this increment, and every row this increment adds
    #: for a decision that never even reached rule selection).
    exit_rule: str | None = None
    #: INC-E3: `"fired"` or `"refused"` -- `None` for every entry-hunt row.
    exit_decision: str | None = None
    #: INC-E3: the exit decider's own distinct refusal reason code (see
    #: `exit_decider.py`), or `"fired"` on a proposal. `None` for every
    #: entry-hunt row.
    exit_reason_code: str | None = None
    #: INC-E3: the authorised 1-contract limit price, when fired. `None`
    #: otherwise (including every entry-hunt row).
    exit_limit_price: Decimal | None = None
    #: INC-E3: the archive's own hold expectation the fired exit cleared
    #: (`ExitAuthorization.expected_settlement_value`). `None` otherwise
    #: (including every entry-hunt row).
    expected_settlement_value: Decimal | None = None

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
            "exit_rule": self.exit_rule,
            "exit_decision": self.exit_decision,
            "exit_reason_code": self.exit_reason_code,
            "exit_limit_price": (
                None if self.exit_limit_price is None else str(self.exit_limit_price)
            ),
            "expected_settlement_value": (
                None
                if self.expected_settlement_value is None
                else str(self.expected_settlement_value)
            ),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OfferTapeRecord:
        """The reader half of :meth:`to_dict` (L1 review finding, commit
        309dab6) -- deliberately narrow: this is the seed of a future
        offer-tape reader, not a general JSON-to-dataclass mapper.

        Strict on the 16 legacy keys (:data:`_LEGACY_KEYS`) -- a payload
        missing any of them raises, since those keys have never been
        optional. The 11 GAP-fix keys default exactly as a directly
        constructed record would (``side="YES"``, ``decision="refuse"``,
        the rest ``None``/``False``), so an old (pre-GAP-fix) JSONL line
        round-trips cleanly. The Decimal-valued GAP-fix fields are
        re-hydrated from their ``to_dict`` string form; ``None`` stays
        ``None``.
        """
        missing = _LEGACY_KEYS - set(payload)
        if missing:
            raise ValueError(
                f"OfferTapeRecord.from_dict: payload missing legacy keys {sorted(missing)}"
            )

        def _decimal(key: str) -> Decimal | None:
            value = payload.get(key)
            return None if value is None else Decimal(str(value))

        return cls(
            station=cast(str, payload["station"]),
            climate_day=cast(str, payload["climate_day"]),
            instrument_id=cast(str, payload["instrument_id"]),
            ask=cast("str | None", payload["ask"]),
            size=cast(int, payload["size"]),
            reason=cast(str, payload["reason"]),
            ts_event=cast(int, payload["ts_event"]),
            hour_lst=cast(int, payload["hour_lst"]),
            width_code=cast(int, payload["width_code"]),
            m_code=cast(int, payload["m_code"]),
            trigger=cast(str, payload["trigger"]),
            quote_age_ns=cast("int | None", payload["quote_age_ns"]),
            minutes_since_window_open=cast(int, payload["minutes_since_window_open"]),
            prior_eligible_snaps=cast(int, payload["prior_eligible_snaps"]),
            illegal_cell=cast(bool, payload["illegal_cell"]),
            source=cast(str, payload["source"]),
            side=cast(str, payload.get("side", "YES")),
            p_bound=_decimal("p_bound"),
            break_even=_decimal("break_even"),
            running_max_lower=_decimal("running_max_lower"),
            running_max_upper=_decimal("running_max_upper"),
            running_max_exact=cast(bool, payload.get("running_max_exact", False)),
            staleness_ns=cast("int | None", payload.get("staleness_ns")),
            fee_coefficient=_decimal("fee_coefficient"),
            observed_at_ns=cast("int | None", payload.get("observed_at_ns")),
            admission_reason=cast("str | None", payload.get("admission_reason")),
            decision=cast(str, payload.get("decision", "refuse")),
            exit_rule=cast("str | None", payload.get("exit_rule")),
            exit_decision=cast("str | None", payload.get("exit_decision")),
            exit_reason_code=cast("str | None", payload.get("exit_reason_code")),
            exit_limit_price=_decimal("exit_limit_price"),
            expected_settlement_value=_decimal("expected_settlement_value"),
        )


class OfferTape:
    """Bounded eligible-snapshot tape. Memory is O(1) in message count."""

    def __init__(
        self,
        path: Path | None = None,
        *,
        maxlen: int = DEFAULT_OFFER_TAPE_MAXLEN,
        sidecar_max_bytes: int = DEFAULT_OFFER_TAPE_SIDECAR_MAX_BYTES,
    ) -> None:
        if maxlen < 1:
            raise ValueError("offer tape maxlen must be >= 1")
        if sidecar_max_bytes < 1:
            raise ValueError("offer tape sidecar_max_bytes must be >= 1")
        self._buf: deque[OfferTapeRecord] = deque(maxlen=maxlen)
        self._maxlen = maxlen
        self._sidecar_max_bytes = sidecar_max_bytes
        self._sidecar_errors = 0
        #: 2026-09-16 GAP fix: rows refused by the byte cap, never the
        #: in-memory deque (which keeps working). One counter increment per
        #: refused row; see `append`'s "logs ONE WARN" behaviour below --
        #: this counter is unbounded so it never itself needs a cap.
        self._sidecar_capped = 0
        self._sidecar_cap_logged = False
        #: H1 review finding (commit 309dab6): sidecar setup is best-effort.
        #: `composition.py` now resolves a default sidecar path
        #: unconditionally, so an unwritable/read-only/full
        #: `catalog_root.parent` must never raise out of strategy
        #: construction at the live boot -- it falls back to in-memory only
        #: (`self._path` stays `None`), exactly like a later `append` disk
        #: error already does.
        self._path: Path | None = None
        #: 2026-09-16 GAP fix: bytes already on disk at THIS path, so a
        #: process restart mid-day (the file already has rows) resumes the
        #: cap from the real on-disk size rather than re-zeroing it and
        #: allowing another full `sidecar_max_bytes` past the true limit.
        #: Best-effort, like everything else here: a `stat()` failure (the
        #: file does not exist yet) is the common case, not an error.
        self._bytes_written = 0
        if path is not None:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
            except OSError:
                self._sidecar_errors += 1
                logger.exception(
                    "OfferTape: failed to create sidecar directory for %s; "
                    "falling back to in-memory only",
                    path,
                )
            else:
                self._path = path
                try:
                    self._bytes_written = path.stat().st_size
                except OSError:
                    self._bytes_written = 0

    @property
    def maxlen(self) -> int:
        return self._maxlen

    @property
    def sidecar_errors(self) -> int:
        """Count of sidecar setup/append failures (H1 review finding)."""
        return self._sidecar_errors

    @property
    def sidecar_capped(self) -> int:
        """Count of rows refused by the byte cap (2026-09-16 GAP fix).

        Disk-only: the in-memory deque never refuses a row on this account.
        """
        return self._sidecar_capped

    def __len__(self) -> int:
        return len(self._buf)

    def records(self) -> tuple[OfferTapeRecord, ...]:
        return tuple(self._buf)

    def append(self, record: OfferTapeRecord) -> None:
        """Record into the bounded in-memory deque, then best-effort JSONL.

        The in-memory record above always happens first and unconditionally:
        a disk error on the optional JSONL sidecar -- OR the sidecar hitting
        its byte cap (2026-09-16 GAP fix) -- must never propagate out of a
        live strategy's `on_quote_tick`/`on_data` (this is called directly
        from `ContinuousRungHoldStrategy._hunt_tick`), and must never starve
        the in-memory tape either. Below the cap this method is
        byte-identical to before the fix.
        """
        self._buf.append(record)
        if self._path is None:
            return
        line = json.dumps(record.to_dict(), sort_keys=True)
        encoded = line.encode("utf-8") + b"\n"
        if self._bytes_written + len(encoded) > self._sidecar_max_bytes:
            self._sidecar_capped += 1
            if not self._sidecar_cap_logged:
                self._sidecar_cap_logged = True
                logger.warning(
                    "OfferTape: sidecar %s reached its %d-byte cap; further rows are "
                    "dropped from disk only (the in-memory deque is unaffected)",
                    self._path,
                    self._sidecar_max_bytes,
                )
            return
        try:
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(line)
                handle.write("\n")
        except OSError:
            self._sidecar_errors += 1
            logger.exception("OfferTape: failed to append to %s", self._path)
            return
        self._bytes_written += len(encoded)

    def as_dicts(self) -> tuple[Mapping[str, object], ...]:
        return tuple(record.to_dict() for record in self._buf)
