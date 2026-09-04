"""Trial-day latch for ``current_rung_hold``, over the SAME store as R-7's
submit-intent latch (``breezy.runtime.submit_intent``).

Why this is not a second store, a second flock, or a second opener
--------------------------------------------------------------------

``current_rung_hold``'s trial rule is: at most ONE trial per station-day.
The natural place to persist that is a durable, restart-surviving latch --
exactly the shape ``breezy.runtime.submit_intent.SubmitIntentLatch`` already
is. The peer-reviewed blueprint
(``docs/plans/CURRENT_RUNG_HOLD_BLUEPRINT_2026-09-04.md``, "Contradiction
resolved -- latch store: FOLD") rejected keeping these as two independent
SQLite files with two independent flocks: two locks leave crash windows that
do not align, so this module is a THIN API over the ONE store and ONE flock
an already-opened ``SubmitIntentLatch`` holds. :class:`TrialDayLatch` is
constructed only by :func:`open_trial_day_latch`, which takes that opened
latch and binds through its ``shared_state_binding()`` accessor -- never a
raw store path, never a second ``open_submit_intent_latch`` call. Every
public method here asserts the SAME flock is still held, mirroring
``SubmitIntentLatch``'s own ``_require_held`` (L-22: exclusion is
unforgeable, not offered).

Keys live in the namespace ``current_rung_hold/trial/{station}/{climate_day}``,
disjoint from ``breezy.runtime.submit_intent.CURRENT_INTENT_KEY`` and its
``exec/polymarket_us/intent/...`` history keys, so both latches share one
SQLite file without key collision.

Ordering rule (binding, peer review "Ordering rule (security, binding)")
--------------------------------------------------------------------------

``TrialDayLatch.consume`` MUST durably commit (the underlying
``SqliteStateStore.set`` call returns, which itself ``COMMIT``\\ s before
returning) STRICTLY BEFORE ``SubmitIntentLatch.arm()`` is called; ``arm()``
precedes the POST; the POST precedes ``retire()``. On restart, the trial
latch is authoritative for "may this station-day be evaluated again" --
checked first, unconditionally, before the submit-intent latch's own
``reconcile_at_startup`` (which answers a different question: "does an
in-flight order need reconciliation"). A consumed trial day with no intent
record is SAFE -- a lost trial, excluded from the day's tally, but no order
was ever sent. An OPEN intent with no trial-day record is the FORBIDDEN
state this ordering makes unreachable: nothing may call ``arm()`` before its
``consume()`` has already durably committed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Final

from breezy.runtime.submit_intent import (
    StateStore,
    SubmitIntentLatch,
    SubmitIntentLockNotHeld,
    _HeldSubmitIntentLock,
)

#: The closed set of trial-day outcomes. Widening this set is a schema
#: change to every already-written record; it is intentionally not exposed
#: as a public constant callers are invited to extend.
_REASONS: Final[frozenset[str]] = frozenset(
    {"observation_unavailable", "observation_ambiguous", "not_taken", "taken"}
)
_SCHEMA_VERSION: Final[int] = 1


class TrialDayLatchError(Exception):
    """Base error for the trial-day latch."""


class TrialDayAlreadyConsumed(TrialDayLatchError):
    """Raised by a second ``consume`` for the same station-day.

    ``consume`` is idempotent-refusing, not idempotent-succeeding: a second
    call is a bug in the caller (evaluating a station-day twice in one
    process, or after a restart without checking ``is_consumed`` first), not
    a benign retry, so it fails loudly rather than silently keeping the
    first record.
    """

    def __init__(self, station: str, climate_day: str) -> None:
        self.station = station
        self.climate_day = climate_day
        super().__init__(f"trial day already consumed: {station}/{climate_day}")


class TrialDayInvalidReason(TrialDayLatchError):
    """Raised when ``consume`` is given a reason outside the closed set."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"trial day reason not in the closed set: {reason!r}")


class TrialDayRecordCorrupt(TrialDayLatchError):
    """Raised when a stored record cannot be decoded. Fail closed."""

    def __init__(self) -> None:
        super().__init__("trial day record is corrupt")


def _key(station: str, climate_day: str) -> str:
    return f"current_rung_hold/trial/{station}/{climate_day}"


@dataclass(frozen=True, slots=True)
class TrialDayRecord:
    """The durable outcome of one station-day's single trial.

    ``ask`` is serialised as ``str(Decimal)`` and parsed back through
    ``Decimal(...)`` so money never round-trips through binary float.
    """

    latched_at_ns: int
    instrument_id: str
    ask: Decimal
    reason: str

    def to_bytes(self) -> bytes:
        payload = {
            "v": _SCHEMA_VERSION,
            "latched_at_ns": self.latched_at_ns,
            "instrument_id": self.instrument_id,
            "ask": str(self.ask),
            "reason": self.reason,
        }
        return json.dumps(payload, sort_keys=True).encode("utf-8")

    @classmethod
    def from_bytes(cls, raw: bytes) -> TrialDayRecord:
        try:
            decoded: object = json.loads(raw.decode("utf-8"))
        except ValueError:
            decoded = None
        if not isinstance(decoded, dict):
            raise TrialDayRecordCorrupt()
        payload: dict[str, object] = decoded
        try:
            version = payload["v"]
            latched_at_ns = payload["latched_at_ns"]
            instrument_id = payload["instrument_id"]
            ask_raw = payload["ask"]
            reason = payload["reason"]
        except KeyError:
            raise TrialDayRecordCorrupt() from None
        if version != _SCHEMA_VERSION:
            raise TrialDayRecordCorrupt()
        if isinstance(latched_at_ns, bool) or not isinstance(latched_at_ns, int):
            raise TrialDayRecordCorrupt()
        if not isinstance(instrument_id, str) or not isinstance(ask_raw, str):
            raise TrialDayRecordCorrupt()
        if not isinstance(reason, str) or reason not in _REASONS:
            raise TrialDayRecordCorrupt()
        try:
            ask = Decimal(ask_raw)
        except InvalidOperation:
            raise TrialDayRecordCorrupt() from None
        return cls(
            latched_at_ns=latched_at_ns,
            instrument_id=instrument_id,
            ask=ask,
            reason=reason,
        )


class TrialDayLatch:
    """At-most-one-trial-per-station-day latch sharing R-7's submit-intent
    store and flock.

    Constructed only by :func:`open_trial_day_latch`, which binds this
    instance to the SAME ``StateStore`` and the SAME
    ``_HeldSubmitIntentLock`` an already-opened
    ``breezy.runtime.submit_intent.SubmitIntentLatch`` holds -- never a
    second store, never a second flock. Every public method asserts that
    flock is still held.
    """

    def __init__(self, store: StateStore, lock: _HeldSubmitIntentLock) -> None:
        self._store = store
        self._lock = lock

    def _require_held(self) -> None:
        if not self._lock.held:
            raise SubmitIntentLockNotHeld()

    def record(self, station: str, climate_day: str) -> TrialDayRecord | None:
        """Return the durable record for this station-day, or ``None``."""
        self._require_held()
        raw = self._store.get(_key(station, climate_day))
        if raw is None:
            return None
        return TrialDayRecord.from_bytes(raw)

    def is_consumed(self, station: str, climate_day: str) -> bool:
        """``True`` once this station-day's single trial has been recorded."""
        self._require_held()
        return self.record(station, climate_day) is not None

    def consume(
        self,
        station: str,
        climate_day: str,
        *,
        latched_at_ns: int,
        instrument_id: str,
        ask: Decimal,
        reason: str,
    ) -> None:
        """Durably record this station-day's single trial.

        Returns only after the write has ``COMMIT``\\ ed (``StateStore.set``
        on the real ``SqliteStateStore`` commits before returning -- see its
        module docstring). Per the ordering rule, this MUST be called, and
        MUST return, before ``SubmitIntentLatch.arm()`` for any order this
        trial leads to.
        """
        self._require_held()
        if reason not in _REASONS:
            raise TrialDayInvalidReason(reason)
        if self.is_consumed(station, climate_day):
            raise TrialDayAlreadyConsumed(station, climate_day)
        record = TrialDayRecord(
            latched_at_ns=latched_at_ns,
            instrument_id=instrument_id,
            ask=ask,
            reason=reason,
        )
        self._store.set(_key(station, climate_day), record.to_bytes())


def open_trial_day_latch(intent_latch: SubmitIntentLatch) -> TrialDayLatch:
    """Bind a :class:`TrialDayLatch` to an already-opened ``SubmitIntentLatch``.

    This is NOT a second opener: ``intent_latch.shared_state_binding()`` is
    the only path to a store and lock here, and it raises
    ``SubmitIntentLockNotHeld`` the moment the intent latch's own factory
    ``with`` has exited -- so a caller cannot construct a working
    ``TrialDayLatch`` from a latch it does not currently, genuinely hold.
    """
    store, lock = intent_latch.shared_state_binding()
    return TrialDayLatch(store, lock)
