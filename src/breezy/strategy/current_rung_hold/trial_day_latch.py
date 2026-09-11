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

Keys live in the namespace ``{key_prefix}{station}/{climate_day}``. The
default ``key_prefix`` is ``current_rung_hold/trial/`` -- byte-identical to
the v2 live family. A sibling family (continuous-rung-hold) passes
``continuous_rung_hold/trial/``. Both are disjoint from
``breezy.runtime.submit_intent.CURRENT_INTENT_KEY`` and its
``exec/polymarket_us/intent/...`` history keys, so both latches share one
SQLite file without key collision.

IN_FLIGHT is a **separate clearable key** in this same primitive (L-22),
keyed ``(station, climate_day)``, under ``{family}/inflight/{station}/{day}``
derived from the trial prefix. v2 never writes it.

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
import threading
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Final

from breezy.runtime.submit_intent import (
    StateStore,
    SubmitIntentLatch,
    SubmitIntentLockNotHeld,
    _HeldSubmitIntentLock,
)
from breezy.strategy.current_rung_hold.decision import REFUSAL_REASONS

#: Default trial-key prefix -- byte-identical to the v2 live family.
DEFAULT_TRIAL_KEY_PREFIX: Final[str] = "current_rung_hold/trial/"
#: v3 continuous-rung-hold family prefix. Disjoint from the v2 default.
CONTINUOUS_TRIAL_KEY_PREFIX: Final[str] = "continuous_rung_hold/trial/"
_TRIAL_SUFFIX: Final[str] = "trial/"
_INFLIGHT_SUFFIX: Final[str] = "inflight/"
_INFLIGHT_OPEN: Final[bytes] = b'{"v":1,"state":"open"}'
_INFLIGHT_CLEARED: Final[bytes] = b'{"v":1,"state":"cleared"}'

#: The closed set of trial-day outcomes: every `decision.py` refusal reason
#: (`REFUSAL_REASONS`) the caller might record verbatim, plus `"taken"` for
#: a `Take`. Widening this set is a schema change to every already-written
#: record, so it is intentionally not exposed as a public constant callers
#: are invited to extend independently -- it derives from `REFUSAL_REASONS`
#: itself rather than duplicating it, so the two can never silently drift.
#:
#: There used to be a bare, collapsed `"not_taken"` outcome here. It had
#: zero production callers (no wiring site exists yet -- `strategy.py`,
#: build order step 6, is not built) and would have thrown away exactly the
#: fact an operator dashboard needs: WHICH `decision.py` rule refused the
#: trial. Recording the real reason string instead is the more honest
#: mapping, not a narrower one -- every `not_taken` caller this latch ever
#: had is still representable, now with the actual reason preserved.
_REASONS: Final[frozenset[str]] = frozenset(REFUSAL_REASONS | {"taken"})
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


def _inflight_prefix(trial_prefix: str) -> str:
    if not trial_prefix.endswith(_TRIAL_SUFFIX):
        raise ValueError(
            f"trial key prefix must end with {_TRIAL_SUFFIX!r}, was {trial_prefix!r}"
        )
    return trial_prefix[: -len(_TRIAL_SUFFIX)] + _INFLIGHT_SUFFIX


def _key(station: str, climate_day: str, *, key_prefix: str = DEFAULT_TRIAL_KEY_PREFIX) -> str:
    return f"{key_prefix}{station}/{climate_day}"


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
    #: Slice 4 item A (plan rev 6.1): the venue order id whose durable fill
    #: consumed this station-day's trial, when known. TRAILING and OPTIONAL
    #: per the binding schema-compat rule (finding_trialrecord_compat.md):
    #: no ``_SCHEMA_VERSION`` bump (the exact-pin gate would corrupt every
    #: existing v1 row), read via ``payload.get`` so a pre-slice-4 record
    #: missing the key decodes as ``None`` -- mirrors
    #: ``DurableFillRecord.venue_fee_raw`` (client.py) exactly.
    venue_order_id: str | None = None

    def to_bytes(self) -> bytes:
        payload = {
            "v": _SCHEMA_VERSION,
            "latched_at_ns": self.latched_at_ns,
            "instrument_id": self.instrument_id,
            "ask": str(self.ask),
            "reason": self.reason,
            "venueOrderId": self.venue_order_id,
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
        # Optional-on-read (missing key -> None, same as JSON null); a
        # PRESENT non-string value is still a mapping error.
        venue_order_id_raw = payload.get("venueOrderId")
        if venue_order_id_raw is not None and not isinstance(venue_order_id_raw, str):
            raise TrialDayRecordCorrupt()
        return cls(
            latched_at_ns=latched_at_ns,
            instrument_id=instrument_id,
            ask=ask,
            reason=reason,
            venue_order_id=venue_order_id_raw,
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

    def __init__(
        self,
        store: StateStore,
        lock: _HeldSubmitIntentLock,
        *,
        key_prefix: str = DEFAULT_TRIAL_KEY_PREFIX,
        intent_latch: SubmitIntentLatch | None = None,
    ) -> None:
        self._store = store
        self._lock = lock
        self._key_prefix = key_prefix
        self._inflight_prefix = _inflight_prefix(key_prefix)
        #: Resolution B (plan rev 6.1): bound at construction by
        #: :func:`open_trial_day_latch`, never opened here. ``None`` for a
        #: ``TrialDayLatch`` built directly (existing test doubles) -- such
        #: an instance simply cannot call :meth:`is_intent_open`.
        self._intent_latch = intent_latch
        #: Slice 4 item A: the thread that constructed THIS instance,
        #: recorded here regardless of ``intent_latch`` -- mirrors
        #: ``SubmitIntentLatch.opening_thread_ident``. ``consume_if_absent``
        #: asserts against it: a read-then-write-if-absent is not atomic
        #: across threads even under the flock (the flock is process-wide,
        #: not a Python-level mutex against a second thread in THIS process).
        self._opening_thread_ident = threading.get_ident()

    def _require_held(self) -> None:
        if not self._lock.held:
            raise SubmitIntentLockNotHeld()

    def is_intent_open(self) -> bool:
        """Resolution B (plan rev 6.1): ``True`` while the account-wide
        submit-intent singleton is OPEN.

        A read-only pre-filter over the SAME store and flock ``arm()``/
        ``retire()`` already share -- delegates to
        ``SubmitIntentLatch.is_latched()`` on the ``intent_latch`` bound at
        construction. This is the cheap check ``_hunt_tick`` uses BEFORE
        ``set_inflight``/``_maybe_submit``: while OPEN (whether from a
        genuine in-flight sibling order or a stale/crash-left singleton no
        resolver has cleared yet), every station's tick is a WAIT, never a
        task hop that would only be denied later inside ``_submit_order``.
        """
        self._require_held()
        if self._intent_latch is None:
            raise TrialDayLatchError(
                "is_intent_open() requires a TrialDayLatch bound to an "
                "intent_latch at construction; see open_trial_day_latch"
            )
        return self._intent_latch.is_latched()


    def _trial_key(self, station: str, climate_day: str) -> str:
        return _key(station, climate_day, key_prefix=self._key_prefix)

    def _inflight_key(self, station: str, climate_day: str) -> str:
        return f"{self._inflight_prefix}{station}/{climate_day}"

    def record(self, station: str, climate_day: str) -> TrialDayRecord | None:
        """Return the durable record for this station-day, or ``None``."""
        self._require_held()
        raw = self._store.get(self._trial_key(station, climate_day))
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
        self._store.set(self._trial_key(station, climate_day), record.to_bytes())

    def consume_if_absent(
        self,
        station: str,
        climate_day: str,
        record: TrialDayRecord,
    ) -> bool:
        """Slice 4 item A: durably record TRIAL for a fill, idempotently.

        Returns ``True`` iff THIS call wrote the record, ``False`` if one
        already existed -- unlike :meth:`consume`, this NEVER raises on an
        already-consumed station-day. That is the whole point: a
        recon-replayed duplicate ``OrderFilled`` for a station-day whose
        trial is already consumed must be a silent no-op here (Resolution
        B's duplicate-fill handling decides what to do with the SECOND
        fill; this method's only job is "don't crash, don't overwrite, and
        never claim TWO writers both wrote it").

        Two writers racing this SAME station-day (e.g. a live
        ``on_order_filled`` and the on_start durable-fill walk observing
        the same underlying fill) leave exactly ONE record: whichever
        holds the flock first at the read-check-write below wins, and the
        loser's own ``is_consumed`` check then observes it and returns
        ``False`` -- never a second write, never a raise.

        Asserts the flock is held and that this is the SAME thread that
        opened this ``TrialDayLatch`` -- a read-then-write-if-absent is not
        atomic against a second thread in this SAME process (the flock is
        process-wide, not a Python-level mutex).
        """
        self._require_held()
        assert threading.get_ident() == self._opening_thread_ident, (
            "consume_if_absent must run on the thread that opened this "
            "TrialDayLatch; a second thread racing the read-check-write "
            "below is not made safe by the process-wide flock alone"
        )
        if record.reason not in _REASONS:
            raise TrialDayInvalidReason(record.reason)
        if self.is_consumed(station, climate_day):
            return False
        self._store.set(self._trial_key(station, climate_day), record.to_bytes())
        return True

    def is_inflight(self, station: str, climate_day: str) -> bool:
        """``True`` while this station-day has a durable IN_FLIGHT marker."""
        self._require_held()
        raw = self._store.get(self._inflight_key(station, climate_day))
        return raw == _INFLIGHT_OPEN

    def set_inflight(self, station: str, climate_day: str) -> None:
        """COMMIT the IN_FLIGHT marker for this station-day. Must precede ``arm()``."""
        self._require_held()
        self._store.set(self._inflight_key(station, climate_day), _INFLIGHT_OPEN)

    def clear_inflight(self, station: str, climate_day: str) -> None:
        """Clear the IN_FLIGHT marker (StateStore has no delete -- write cleared)."""
        self._require_held()
        self._store.set(self._inflight_key(station, climate_day), _INFLIGHT_CLEARED)


def open_trial_day_latch(
    intent_latch: SubmitIntentLatch,
    *,
    key_prefix: str = DEFAULT_TRIAL_KEY_PREFIX,
) -> TrialDayLatch:
    """Bind a :class:`TrialDayLatch` to an already-opened ``SubmitIntentLatch``.

    This is NOT a second opener: ``intent_latch.shared_state_binding()`` is
    the only path to a store and lock here, and it raises
    ``SubmitIntentLockNotHeld`` the moment the intent latch's own factory
    ``with`` has exited -- so a caller cannot construct a working
    ``TrialDayLatch`` from a latch it does not currently, genuinely hold.

    ``key_prefix`` defaults to the v2 live prefix so existing callers stay
    byte-identical.
    """
    store, lock = intent_latch.shared_state_binding()
    return TrialDayLatch(store, lock, key_prefix=key_prefix, intent_latch=intent_latch)
