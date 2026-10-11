"""Durable, value-free submit-intent latch over a ``StateStore``.

A process that has POSTed a submit and not yet observed a definitive outcome
must not POST another. The singleton at ``CURRENT_INTENT_KEY`` is that latch:
``arm`` writes an OPEN record before the caller is allowed to POST, and
``retire`` writes the history key first so a crash leaves the singleton OPEN
(closed to a new arm) with a history record ``reconcile_at_startup`` can
repair locally.

Exclusion is unforgeable: ``open_submit_intent_latch`` is the only constructor
and it holds an exclusive flock for the factory's lifetime. A second factory
over the same store path raises ``SubmitIntentLockHeld``. Using a yielded
latch after the ``with`` exits raises ``SubmitIntentLockNotHeld``. Hold the
latch for the process lifetime; ``arm`` → POST → ``retire`` on one thread.

The record is value-free by design: str/repr of the dataclass and of every
exception carry intent_id and state only, never a fingerprint, never a store
payload. This module performs no venue call and imports no HTTP client.
"""

from __future__ import annotations

import errno
import fcntl
import hashlib
import json
import logging
import os
import re
import threading
import time
import uuid
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path
from typing import Final, Protocol, Self

from breezy.domain.exec_slots import SlotRecord, SlotTableView, Wait, admit
from breezy.runtime.exec_par_latch_counters import ExecParCounterRowsMixin
from breezy.runtime.submit_intent_slots import (
    BREAKER_ABSENT_GRACE_NS,
    BREAKER_FUTURE_SKEW_NS,
    BREAKER_HEARTBEAT_MAX_AGE_NS,
    BREAKER_KEY,
    BREAKER_RESOLVER_PASS_MAX_AGE_NS,
    DEFAULT_COOLOFF_NS,
    BreakerRecord,
    SlotTableError,
    canonical_text,
    encode_breaker,
    encode_v2,
    parse_breaker,
    parse_table,
)

_LOG = logging.getLogger(__name__)

__all__ = [
    "BREAKER_KEY",
    "CURRENT_INTENT_KEY",
    "DEFAULT_COOLOFF_NS",
    "BreakerRecord",
    "RetirementReason",
    "SlotTable",
    "StateStore",
    "SubmitIntent",
    "SubmitIntentAdmissionDenied",
    "SubmitIntentBootOrderError",
    "SubmitIntentCorrupt",
    "SubmitIntentError",
    "SubmitIntentInvalidFingerprint",
    "SubmitIntentInvalidSlug",
    "SubmitIntentLatch",
    "SubmitIntentLatched",
    "SubmitIntentLockError",
    "SubmitIntentLockHeld",
    "SubmitIntentLockNotHeld",
    "SubmitIntentMismatch",
    "SubmitIntentState",
    "decode_slot_table",
    "history_key",
    "hold_submit_intent_process_lock",
    "open_submit_intent_latch",
]

CURRENT_INTENT_KEY: Final[str] = "exec/polymarket_us/intent/current"
_SCHEMA_VERSION: Final[int] = 1
_FINGERPRINT_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")
_INTENT_ID_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{32}$")
_MAX_SLUG_LEN: Final[int] = 256
#: EXEC-PAR E14.2: how long a resolver failure keeps a slot behind healthy ones
#: (the global backoff cap, 300 s). Mirrors the exec client's backoff cap.
FAILURE_PENALTY_NS: Final[int] = 300 * 1_000_000_000


class StateStore(Protocol):
    """The minimal persistence seam this module needs.

    Structurally identical to ``gate.StateStore`` on purpose: declared here
    rather than imported so this module carries no ingest.gate dependency
    (and therefore no path into Nautilus via ingest).
    """

    def get(self, key: str) -> bytes | None: ...

    def set(self, key: str, value: bytes) -> None: ...


def history_key(intent_id: str) -> str:
    """Return the durable history key for one intent id.

    ``retire`` writes this key BEFORE the singleton so a crash between the
    two sets leaves the latch closed (OPEN singleton) with a history record
    that ``reconcile_at_startup`` can copy back verbatim. The id is an opaque
    32-hex digest; callers must validate before interpolation so a tampered
    id cannot escape this namespace.
    """
    return f"exec/polymarket_us/intent/history/{intent_id}"


class SubmitIntentState(str, Enum):
    OPEN = "OPEN"
    RETIRED = "RETIRED"


class RetirementReason(str, Enum):
    DEFINITIVE_REJECT = "DEFINITIVE_REJECT"
    ACCEPTED_WITH_DURABLE_FILL = "ACCEPTED_WITH_DURABLE_FILL"
    ACCEPTED_ZERO_FILL_TERMINAL = "ACCEPTED_ZERO_FILL_TERMINAL"
    STARTUP_FILL_RECORD_MATCH = "STARTUP_FILL_RECORD_MATCH"
    OPERATOR_CLEARED = "OPERATOR_CLEARED"
    #: L-36 / plan rev 6.1, Resolution A2/D: a with-id AMBIGUOUS create-order
    #: outcome resolved by the resolver's own bounded GET (never the create
    #: response) to a terminal state with filled_qty==0, confirmed by an
    #: eof-complete positions read showing no LONG. Distinct from
    #: ACCEPTED_ZERO_FILL_TERMINAL, which is set from the CREATE response
    #: itself and (per L-36) is unreachable in practice.
    STATUS_REPORT_ZERO_FILL_TERMINAL = "STATUS_REPORT_ZERO_FILL_TERMINAL"
    #: Resolution A2/E (plan rev 6.1, slice 3): a with-id AMBIGUOUS
    #: create-order outcome resolved by the resolver's own bounded GET to a
    #: terminal FILLED/PARTIALLY_FILLED state with a confirmed LONG present
    #: on an eof-complete positions read. The venue's Order schema carries no
    #: execution legs, so the fill is SYNTHESIZED from ``cumQuantity``/
    #: ``avgPx`` -- distinct from ACCEPTED_WITH_DURABLE_FILL, which is set
    #: from real per-leg execution evidence in the CREATE response.
    STATUS_REPORT_ACCEPT_FILL_TERMINAL = "STATUS_REPORT_ACCEPT_FILL_TERMINAL"
    #: AMBIG-LATCH-RESUME C0 (CH1): a NO-ID AMBIGUOUS intent (the venue
    #: issues no client order id, so a POST that never returned a venue id
    #: cannot be looked up by GET) retired by the node resolver on complete,
    #: consistent negative venue evidence. Landed in Phase A, supervisor side,
    #: BEFORE any node can write it: an older supervisor decoding it would
    #: raise SubmitIntentCorrupt (``_optional_enum``), read the singleton as
    #: OPEN and refuse every launch (L-48). Never reverted (plan r6 section 6).
    RESOLVER_NO_ID_NO_FILL = "RESOLVER_NO_ID_NO_FILL"


class SubmitIntentError(Exception):
    """Base error for the submit-intent latch. Messages name id/state only."""


class SubmitIntentLatched(SubmitIntentError):
    """Raised when ``arm`` is refused because the singleton is OPEN or corrupt."""

    def __init__(self, intent_id: str | None = None) -> None:
        self.intent_id = intent_id
        if intent_id is None:
            super().__init__("submit intent is latched")
        else:
            super().__init__(f"submit intent {intent_id} is latched")


class SubmitIntentAdmissionDenied(SubmitIntentLatched):
    """``arm_slot`` refused by the slot arbiter. ``reason`` is a stable label."""

    def __init__(self, reason: str, intent_id: str | None = None) -> None:
        super().__init__(intent_id)
        self.reason = reason


class SubmitIntentBootOrderError(SubmitIntentError):
    """Raised when boot steps run out of order (cool-off seeded before adoption)."""

    def __init__(self) -> None:
        super().__init__("slot adoption must run before the boot cool-off seed")


class SubmitIntentInvalidSlug(SubmitIntentError):
    """Raised when ``arm_slot`` is given an empty or oversized slug."""

    def __init__(self) -> None:
        super().__init__("submit intent slug is invalid")


class SubmitIntentMismatch(SubmitIntentError):
    """Raised when ``retire`` does not match the OPEN singleton."""

    def __init__(
        self,
        requested_id: str,
        current_id: str | None,
        current_state: str | None,
    ) -> None:
        self.requested_id = requested_id
        self.current_id = current_id
        self.current_state = current_state
        super().__init__(
            f"submit intent mismatch: requested {requested_id}, "
            f"current {current_id} state={current_state}"
        )


class SubmitIntentCorrupt(SubmitIntentError):
    """Raised when the singleton cannot be decoded. Fail closed."""

    def __init__(self) -> None:
        super().__init__("submit intent record is corrupt")


class SubmitIntentInvalidFingerprint(SubmitIntentError):
    """Raised when ``arm`` is given a fingerprint that is not a sha256 hex digest."""

    def __init__(self) -> None:
        super().__init__("submit intent fingerprint is invalid")


class SubmitIntentLockHeld(SubmitIntentError):
    """Raised when another holder already has the process lock."""

    def __init__(self) -> None:
        super().__init__("submit intent process lock is held")


class SubmitIntentLockNotHeld(SubmitIntentError):
    """Raised when a latch method is used after its factory ``with`` exits."""

    def __init__(self) -> None:
        super().__init__("submit intent process lock is not held")


class SubmitIntentLockError(SubmitIntentError):
    """Raised when the process lock cannot be opened for a non-contention reason."""

    def __init__(self, detail: str | None = None) -> None:
        message = "submit intent process lock could not be acquired"
        if detail:
            message = f"{message}: {detail}"
        super().__init__(message)


def _require_str(payload: dict[str, object], name: str) -> str:
    try:
        value = payload[name]
    except KeyError:
        raise SubmitIntentCorrupt() from None
    if not isinstance(value, str):
        raise SubmitIntentCorrupt()
    return value


def _require_int(payload: dict[str, object], name: str) -> int:
    try:
        value = payload[name]
    except KeyError:
        raise SubmitIntentCorrupt() from None
    if isinstance(value, bool) or not isinstance(value, int):
        raise SubmitIntentCorrupt()
    return value


def _optional_int(payload: dict[str, object], name: str) -> int | None:
    try:
        value = payload[name]
    except KeyError:
        raise SubmitIntentCorrupt() from None
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise SubmitIntentCorrupt()
    return value


def _require_enum[E: Enum](payload: dict[str, object], name: str, enum_cls: type[E]) -> E:
    raw = _require_str(payload, name)
    try:
        return enum_cls(raw)
    except ValueError:
        raise SubmitIntentCorrupt() from None


def _optional_enum[E: Enum](payload: dict[str, object], name: str, enum_cls: type[E]) -> E | None:
    try:
        value = payload[name]
    except KeyError:
        raise SubmitIntentCorrupt() from None
    if value is None:
        return None
    if not isinstance(value, str):
        raise SubmitIntentCorrupt()
    try:
        return enum_cls(value)
    except ValueError:
        raise SubmitIntentCorrupt() from None


def _retired_from(
    current: SubmitIntent,
    reason: RetirementReason,
    now_ns: int,
) -> SubmitIntent:
    return replace(
        current,
        state=SubmitIntentState.RETIRED,
        retired_ns=now_ns,
        retirement_reason=reason,
    )


def _optional_slug(payload: dict[str, object]) -> str | None:
    value = payload.get("slug")
    if value is None:
        return None
    if not isinstance(value, str) or not 0 < len(value) <= _MAX_SLUG_LEN:
        raise SubmitIntentCorrupt()
    return value


def _optional_true(payload: dict[str, object], name: str) -> bool:
    value = payload.get(name)
    if value is None:
        return False
    if value is not True:
        raise SubmitIntentCorrupt()
    return True


@dataclass(frozen=True, slots=True)
class SubmitIntent:
    """One submit-intent record.

    ``slug`` and ``is_exit`` are trailing-optional (EXEC-PAR WP2) and emitted
    only when set, so a K=1 record's bytes are identical to the pre-WP2 ones.
    """

    intent_id: str
    fingerprint: str = field(repr=False)
    created_ns: int
    state: SubmitIntentState
    retired_ns: int | None
    retirement_reason: RetirementReason | None
    slug: str | None = None
    is_exit: bool = False

    def __post_init__(self) -> None:
        if self.state is SubmitIntentState.RETIRED:
            if self.retired_ns is None or self.retirement_reason is None:
                raise SubmitIntentCorrupt()
        elif self.state is SubmitIntentState.OPEN:
            if self.retired_ns is not None or self.retirement_reason is not None:
                raise SubmitIntentCorrupt()
        else:
            raise SubmitIntentCorrupt()

    def to_bytes(self) -> bytes:
        return json.dumps(self.to_payload(), sort_keys=True).encode("utf-8")

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "v": _SCHEMA_VERSION,
            "intent_id": self.intent_id,
            "fingerprint": self.fingerprint,
            "created_ns": self.created_ns,
            "state": self.state.value,
            "retired_ns": self.retired_ns,
            "retirement_reason": (
                None if self.retirement_reason is None else self.retirement_reason.value
            ),
        }
        if self.slug is not None:
            payload["slug"] = self.slug
        if self.is_exit:
            payload["is_exit"] = True
        return payload

    @classmethod
    def from_bytes(cls, raw: bytes) -> Self:
        try:
            decoded: object = json.loads(raw.decode("utf-8"))
        except ValueError:
            decoded = None
        if not isinstance(decoded, dict):
            raise SubmitIntentCorrupt()
        return cls.from_payload(decoded)

    @classmethod
    def from_payload(cls, payload: dict[str, object]) -> Self:
        if _require_int(payload, "v") != _SCHEMA_VERSION:
            raise SubmitIntentCorrupt()
        intent_id = _require_str(payload, "intent_id")
        fingerprint = _require_str(payload, "fingerprint")
        if not _INTENT_ID_RE.fullmatch(intent_id) or not _FINGERPRINT_RE.fullmatch(fingerprint):
            raise SubmitIntentCorrupt()
        return cls(
            intent_id=intent_id,
            fingerprint=fingerprint,
            created_ns=_require_int(payload, "created_ns"),
            state=_require_enum(payload, "state", SubmitIntentState),
            retired_ns=_optional_int(payload, "retired_ns"),
            retirement_reason=_optional_enum(payload, "retirement_reason", RetirementReason),
            slug=_optional_slug(payload),
            is_exit=_optional_true(payload, "is_exit"),
        )


class _HeldSubmitIntentLock:
    """Exclusive flock token. ``held`` is True only inside the factory."""

    __slots__ = ("_fd", "_held")

    def __init__(self, fd: int) -> None:
        self._fd = fd
        self._held = True

    @property
    def held(self) -> bool:
        return self._held

    def release(self) -> None:
        if not self._held:
            return
        self._held = False
        try:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
        finally:
            os.close(self._fd)


#: Retirement reasons after which no cool-off is written: nothing reached the
#: venue (definitive reject) or the operator cleared the slot by hand.
_NO_COOLOFF_REASONS: Final[frozenset[RetirementReason]] = frozenset(
    {RetirementReason.DEFINITIVE_REJECT, RetirementReason.OPERATOR_CLEARED}
)
_LEGACY_KEY_PREFIX: Final[str] = "?:"


@dataclass(frozen=True, slots=True)
class SlotTable:
    """Decoded slot table: readable OPEN slots, unreadable slots, cool-offs.

    ``last`` is the v1 RETIRED record when no slot is open. ``version`` is 0
    (absent), 1 or 2 as stored.
    """

    version: int
    open: tuple[SubmitIntent, ...] = ()
    unreadable: tuple[tuple[str, bytes], ...] = ()
    cooloff: tuple[tuple[str, int], ...] = ()
    last: SubmitIntent | None = None


def _live_cooloff(cooloff: tuple[tuple[str, int], ...], now_ns: int) -> tuple[tuple[str, int], ...]:
    return tuple((slug, until) for slug, until in cooloff if until > now_ns)


def _with_cooloff(
    cooloff: tuple[tuple[str, int], ...], slug: str, until_ns: int
) -> tuple[tuple[str, int], ...]:
    merged = dict(cooloff)
    merged[slug] = max(merged.get(slug, 0), until_ns)
    return tuple(sorted(merged.items()))


def _slot_from_value(key: str, value: object) -> SubmitIntent | None:
    """A readable OPEN slot keyed by its own intent id, else ``None``."""
    if not isinstance(value, dict):
        return None
    try:
        record = SubmitIntent.from_payload(value)
    except SubmitIntentCorrupt:
        return None
    if record.state is not SubmitIntentState.OPEN or record.intent_id != key:
        return None
    return record


def decode_slot_table(raw: bytes | None) -> SlotTable:
    """Decode a stored ``CURRENT_INTENT_KEY`` value (``None`` = absent); pure, no I/O.

    The read-only seam for consumers that hold no latch (the supervisor probes,
    the operator CLI, the analysis readers). Whole-table corruption raises
    :class:`SubmitIntentCorrupt`; an unreadable slot is reported in
    ``unreadable`` and counts as OPEN for every caller.
    """
    if raw is None:
        return SlotTable(version=0)
    try:
        parsed = parse_table(raw)
    except SlotTableError:
        raise SubmitIntentCorrupt() from None
    if parsed.v1_record is not None:
        record = SubmitIntent.from_payload(parsed.v1_record)
        is_open = record.state is SubmitIntentState.OPEN
        return SlotTable(
            version=1,
            open=(record,) if is_open else (),
            cooloff=parsed.cooloff,
            last=None if is_open else record,
        )
    readable: list[SubmitIntent] = []
    unreadable: dict[str, bytes] = dict(parsed.raw_slots)
    for key, value in parsed.slots:
        slot = _slot_from_value(key, value)
        if slot is None:
            unreadable[key] = canonical_text(value)
        else:
            readable.append(slot)
    readable.sort(key=lambda i: (i.created_ns, i.intent_id))
    return SlotTable(
        version=2,
        open=tuple(readable),
        unreadable=tuple(sorted(unreadable.items())),
        cooloff=parsed.cooloff,
    )


class SubmitIntentLatch(ExecParCounterRowsMixin):
    """One-at-a-time submit latch persisted through ``StateStore.get``/``set``.

    Constructed only by :func:`open_submit_intent_latch`, which binds this
    instance to an exclusive flock. Every public method asserts that flock
    is still held.
    """

    #: This latch's own corrupt-singleton exception, exposed as a class
    #: attribute so an INJECTED consumer (an adapter, which the layers
    #: contract forbids from importing ``breezy.runtime`` at all -- see
    #: ``adapters/polymarket_us/exec/client.py``'s module docstring) can
    #: catch it via ``except self._latch.CorruptError`` without ever
    #: importing this module.
    CorruptError = SubmitIntentCorrupt

    def __init__(
        self,
        store: StateStore,
        lock: _HeldSubmitIntentLock,
        *,
        max_slots: int = 1,
        cooloff_ns: int = DEFAULT_COOLOFF_NS,
        v2_predicate: Callable[[], bool] | None = None,
        clock_ns: Callable[[], int] | None = None,
    ) -> None:
        if max_slots < 1 or cooloff_ns < 0:
            raise ValueError("max_slots must be >= 1 and cooloff_ns >= 0")
        self._store = store
        self._lock = lock
        self._k_configured = max_slots
        self._cooloff_ns = cooloff_ns
        self._v2_predicate: Callable[[], bool] = v2_predicate or (lambda: False)
        self._clock_ns: Callable[[], int] = clock_ns or time.time_ns
        self._boot_ns = self._clock_ns()
        self._k_forced_reason: str | None = None
        self._adoption_ran = False
        self._logged_unreadable: set[str] = set()
        self._mutex = threading.Lock()
        #: The thread that OPENED this latch (recorded here, at construction
        #: -- :func:`open_submit_intent_latch` is the only factory). A
        #: consumer that is handed the already-opened latch (R-7's exec
        #: client) asserts against this before reconciling, so adopting the
        #: latch from a second thread fails closed instead of racing the
        #: `_mutex` from two threads at once.
        self._opening_thread_ident = threading.get_ident()

    @property
    def opening_thread_ident(self) -> int:
        """The ``threading.get_ident()`` value of the thread that opened this latch."""
        return self._opening_thread_ident

    @property
    def boot_ns(self) -> int:
        """The clock reading taken when this latch was constructed (read-only)."""
        return self._boot_ns

    def _require_held(self) -> None:
        if not self._lock.held:
            raise SubmitIntentLockNotHeld()

    def current(self) -> SubmitIntent | None:
        self._require_held()
        raw = self._store.get(CURRENT_INTENT_KEY)
        if raw is None:
            return None
        return SubmitIntent.from_bytes(raw)

    def current_open(self) -> SubmitIntent | None:
        """The current armed intent, iff it is OPEN -- ``None`` otherwise.

        The read-only surface an INJECTED consumer needs (the OPEN-only
        processing check, the foreign-intent guard via ``.intent_id``)
        without ever importing :class:`SubmitIntentState` -- an adapter
        importing anything from ``breezy.runtime`` breaks the layers
        contract (``breezy.adapters`` sits below it). Raises
        :class:`SubmitIntentCorrupt` (``self.CorruptError``) exactly like
        :meth:`current`/:meth:`is_latched` do on an undecodable singleton --
        never silently treats corruption as OPEN or as absent.
        """
        self._require_held()
        current = self.current()
        if current is None or current.state is not SubmitIntentState.OPEN:
            return None
        return current

    def is_latched(self) -> bool:
        """True when a new ``arm`` must be refused.

        A corrupt singleton is latched: damaged ledger stays closed rather
        than being repaired or treated as empty.
        """
        self._require_held()
        try:
            current = self.current()
        except SubmitIntentCorrupt:
            return True
        return current is not None and current.state is SubmitIntentState.OPEN

    def arm(self, fingerprint: str, *, now_ns: int) -> SubmitIntent:
        """Write the OPEN singleton, or refuse.

        The fingerprint is validated before any store write. The get-then-set
        is serialised by the instance mutex and the exclusive flock, so two
        callers cannot both observe empty and both persist OPEN. Callers hold
        this latch for the process lifetime and run ``arm`` → POST → ``retire``
        on one thread.
        """
        self._require_held()
        if _FINGERPRINT_RE.fullmatch(fingerprint) is None:
            raise SubmitIntentInvalidFingerprint()
        with self._mutex:
            try:
                current = self.current()
            except SubmitIntentCorrupt:
                raise SubmitIntentLatched() from None
            if current is not None and current.state is SubmitIntentState.OPEN:
                raise SubmitIntentLatched(current.intent_id)
            intent = SubmitIntent(
                intent_id=uuid.uuid4().hex,
                fingerprint=fingerprint,
                created_ns=now_ns,
                state=SubmitIntentState.OPEN,
                retired_ns=None,
                retirement_reason=None,
            )
            # Share the slot encoder so an unexpired cool-off carried by a v1
            # RETIRED record survives. Without one the bytes equal to_bytes().
            cooloff = _live_cooloff(self._read_table().cooloff, now_ns)
            self._store.set(
                CURRENT_INTENT_KEY,
                self._encode(SlotTable(version=1, open=(intent,), cooloff=cooloff)),
            )
            return intent

    def retire(
        self,
        intent_id: str,
        reason: RetirementReason,
        *,
        now_ns: int,
    ) -> SubmitIntent:
        """Retire the OPEN singleton matching ``intent_id``.

        History is written before the singleton so a crash after the first
        ``set`` leaves the latch closed with a history record
        ``reconcile_at_startup`` can copy back. A tampered id is rejected
        before it is interpolated into a store key.
        """
        self._require_held()
        if _INTENT_ID_RE.fullmatch(intent_id) is None:
            raise SubmitIntentCorrupt()
        with self._mutex:
            return self._retire_unlocked(intent_id, reason, now_ns)

    def reconcile_at_startup(
        self,
        *,
        has_durable_fill_record: Callable[[str, int], object],
        now_ns: int,
    ) -> SubmitIntent | None:
        """Repair a crash between history write and singleton write.

        History matching the OPEN singleton (id, fingerprint, created_ns)
        is copied verbatim onto the singleton -- the original reason and
        ``retired_ns`` are the audit fact, not a stamped startup reason.
        A corrupt singleton raises ``SubmitIntentCorrupt`` (never repaired).
        A damaged or mismatched history record leaves the singleton OPEN
        and does not consult the fill probe: a damaged ledger stays closed.

        SP-3r: the probe is called with the OPEN singleton's OWN
        ``fingerprint`` AND ``created_ns`` -- never the boot wall-clock time
        -- so an injected probe can derive the exact day-scoped index key a
        crashed process would have written, even when boot happens after a
        UTC-midnight rollover.
        """
        self._require_held()
        with self._mutex:
            table = self._read_table()
            if table.version == 2:
                return self._reconcile_slots(table, has_durable_fill_record, now_ns)
            current = self.current()
            if current is None:
                return None
            if current.state is not SubmitIntentState.OPEN:
                return current
            try:
                history = self._retired_history(current)
            except SubmitIntentCorrupt:
                return current
            if history is not None:
                record, raw = history
                repaired = self._table_after_retire(table, current, record)
                # Without any cool-off the history bytes are copied verbatim
                # (the K=1 behaviour); otherwise the shared encoder keeps the
                # cool-off and adds the retire's own.
                self._store.set(
                    CURRENT_INTENT_KEY,
                    self._encode(repaired) if repaired.cooloff else raw,
                )
                return record
            if has_durable_fill_record(current.fingerprint, current.created_ns) is True:
                return self._retire_unlocked(
                    current.intent_id,
                    RetirementReason.STARTUP_FILL_RECORD_MATCH,
                    now_ns,
                )
            return current

    def _retire_unlocked(
        self,
        intent_id: str,
        reason: RetirementReason,
        now_ns: int,
    ) -> SubmitIntent:
        table = self._read_table()
        slot = next((i for i in table.open if i.intent_id == intent_id), None)
        if slot is None:
            ref = table.open[0] if table.open else table.last
            current_id = None if ref is None else ref.intent_id
            current_state = None if ref is None else ref.state.value
            raise SubmitIntentMismatch(intent_id, current_id, current_state)
        retired = _retired_from(slot, reason, now_ns)
        self._store.set(history_key(intent_id), retired.to_bytes())
        self._store.set(CURRENT_INTENT_KEY, self._after_retire(table, slot, retired))
        return retired

    def _after_retire(self, table: SlotTable, slot: SubmitIntent, retired: SubmitIntent) -> bytes:
        return self._encode(self._table_after_retire(table, slot, retired))

    def _table_after_retire(
        self, table: SlotTable, slot: SubmitIntent, retired: SubmitIntent
    ) -> SlotTable:
        """The table once ``slot`` is retired (cool-off added; ``last`` set when drained)."""
        rest = tuple(i for i in table.open if i.intent_id != slot.intent_id)
        now_ns = retired.retired_ns or 0
        cooloff = _live_cooloff(table.cooloff, now_ns)
        if (
            self._k_configured > 1
            and self._cooloff_ns > 0
            and slot.slug is not None
            and not slot.is_exit
            and retired.retirement_reason not in _NO_COOLOFF_REASONS
        ):
            cooloff = _with_cooloff(cooloff, slot.slug, now_ns + self._cooloff_ns)
        return SlotTable(
            version=table.version,
            open=rest,
            unreadable=table.unreadable,
            cooloff=cooloff,
            last=None if rest else retired,
        )

    def _reconcile_slots(
        self,
        table: SlotTable,
        has_durable_fill_record: Callable[[str, int], object],
        now_ns: int,
    ) -> SubmitIntent | None:
        """Repair every open slot of a v2 table that history or a fill record retires.

        Returns the oldest slot still open, else the last repaired record.
        """
        working = table
        repaired: SubmitIntent | None = None
        for slot in table.open:
            try:
                history = self._retired_history(slot)
            except SubmitIntentCorrupt:
                continue
            if history is not None:
                record = history[0]
            elif has_durable_fill_record(slot.fingerprint, slot.created_ns) is True:
                record = _retired_from(slot, RetirementReason.STARTUP_FILL_RECORD_MATCH, now_ns)
                self._store.set(history_key(slot.intent_id), record.to_bytes())
            else:
                continue
            working = self._table_after_retire(working, slot, record)
            repaired = record
        if repaired is not None:
            self._store.set(CURRENT_INTENT_KEY, self._encode(working))
        if working.open:
            return working.open[0]
        if working.unreadable:
            # "No intent" and "only quarantined slots" must never look alike.
            raise SubmitIntentCorrupt()
        return repaired

    @staticmethod
    def _encode(table: SlotTable) -> bytes:
        """v1 bytes while at most one slot is open and none is unreadable, else v2."""
        if len(table.open) + len(table.unreadable) <= 1 and not table.unreadable:
            record = table.open[0] if table.open else table.last
            if record is None:
                raise SubmitIntentCorrupt()
            payload = record.to_payload()
            if table.cooloff:
                payload["cooloff"] = dict(table.cooloff)
            return json.dumps(payload, sort_keys=True).encode("utf-8")
        return encode_v2(
            {i.intent_id: i.to_payload() for i in table.open},
            dict(table.unreadable),
            dict(table.cooloff),
        )

    def _read_table(self) -> SlotTable:
        """Decode ``CURRENT_INTENT_KEY``; whole-table corruption raises ``SubmitIntentCorrupt``."""
        table = decode_slot_table(self._store.get(CURRENT_INTENT_KEY))
        self._note_unreadable(table)
        return table

    def _note_unreadable(self, table: SlotTable) -> None:
        for key, _ in table.unreadable:
            if key not in self._logged_unreadable:
                self._logged_unreadable.add(key)
                _LOG.error("submit intent slot %s is unreadable; slot table quarantined", key)

    # ------------------------------------------------------------------
    # EXEC-PAR slot API (inert: no production caller yet)
    # ------------------------------------------------------------------

    def max_slots(self) -> int:
        """The effective K: the configured K, or 1 once :meth:`force_k1` ran."""
        return 1 if self._k_forced_reason is not None else self._k_configured

    @property
    def k_forced_reason(self) -> str | None:
        return self._k_forced_reason

    def force_k1(self, reason: str) -> None:
        """Pin the effective K to 1 for the rest of this process (first reason wins).

        Process-local and not persisted: every boot re-evaluates the cause and
        calls this again if it still holds.
        """
        with self._mutex:
            if self._k_forced_reason is None:
                self._k_forced_reason = reason
                _LOG.error("submit intent slots forced to K=1: %s", reason)

    def open_slot_count(self) -> int:
        """Open slots, unreadable ones included. Raises on a corrupt table."""
        self._require_held()
        with self._mutex:
            table = self._read_table()
        return len(table.open) + len(table.unreadable)

    def is_open_intent(self, intent_id: str) -> bool:
        self._require_held()
        with self._mutex:
            table = self._read_table()
        return any(i.intent_id == intent_id for i in table.open)

    def open_submit_intents(self) -> tuple[SubmitIntent, ...]:
        """Readable OPEN slots, oldest first. Unreadable slots are not included."""
        self._require_held()
        with self._mutex:
            return self._read_table().open

    def read_intent(self, intent_id: str) -> SubmitIntent | None:
        """The OPEN slot for ``intent_id``, else its retired ``history`` record, else ``None``.

        A malformed id raises ``ValueError``; a garbled table or record raises
        ``SubmitIntentCorrupt`` (never a default).
        """
        self._require_held()
        if _INTENT_ID_RE.fullmatch(intent_id) is None:
            raise ValueError("invalid intent id")
        with self._mutex:
            for slot in self._read_table().open:
                if slot.intent_id == intent_id:
                    return slot
            raw = self._store.get(history_key(intent_id))
            if raw is None:
                return None
            record = SubmitIntent.from_bytes(raw)
            if record.intent_id != intent_id:
                raise SubmitIntentCorrupt()
            return record

    def unreadable_slot_keys(self) -> tuple[str, ...]:
        """Keys of unreadable slots, plus ``?:<id>`` for slug-less slots when K > 1."""
        self._require_held()
        with self._mutex:
            table = self._read_table()
        keys = [key for key, _ in table.unreadable]
        if self.max_slots() > 1:
            keys.extend(f"{_LEGACY_KEY_PREFIX}{i.intent_id}" for i in table.open if i.slug is None)
        return tuple(sorted(keys))

    def next_open_for_resolution(
        self,
        failures: Mapping[str, int],
        served: Mapping[str, int],
        last_failure_ns: Mapping[str, int] | None = None,
    ) -> SubmitIntent | None:
        """The readable OPEN slot to resolve next, independent of ``max_slots``.

        Sorted by (failure penalty, last served, created); unreadable slots are
        skipped (logged once per key). A slot is PENALISED while it has a failure
        count and, when ``last_failure_ns`` is given, that failure is less than
        :data:`FAILURE_PENALTY_NS` old: failing slots then order after healthy
        ones. After the window the penalty lapses and ordering is by last-served,
        so no slot waits longer than (K x poll) + the window while healthy slots
        cycle. Without ``last_failure_ns`` any failure count penalises (the
        pre-E14 two-argument behaviour).
        """
        self._require_held()
        with self._mutex:
            table = self._read_table()
        if not table.open:
            return None
        now_ns = self._clock_ns()

        def penalised(intent_id: str) -> int:
            if failures.get(intent_id, 0) <= 0:
                return 0
            if last_failure_ns is None or intent_id not in last_failure_ns:
                return 1
            return 1 if now_ns - last_failure_ns[intent_id] < FAILURE_PENALTY_NS else 0

        return min(
            table.open,
            key=lambda i: (
                penalised(i.intent_id),
                served.get(i.intent_id, 0),
                i.created_ns,
                i.intent_id,
            ),
        )

    def admission_refusal(self, slug: str, is_exit: bool) -> str | None:
        """Why a new slot on ``slug`` would be refused now, or ``None``. Read-only."""
        self._require_held()
        with self._mutex:
            try:
                table = self._read_table()
            except SubmitIntentCorrupt:
                _LOG.warning("slot table is corrupt; refusing admission (fail closed)")
                return "corrupt"
            return self._admission_locked(table, slug, is_exit, self._clock_ns())

    def arm_slot(self, fingerprint: str, *, slug: str, is_exit: bool, now_ns: int) -> SubmitIntent:
        """Write a new OPEN slot if ``admit`` allows it, or raise.

        At an effective K of 1 the record carries neither slug nor exit flag,
        so the bytes equal :meth:`arm`'s.
        """
        self._require_held()
        if _FINGERPRINT_RE.fullmatch(fingerprint) is None:
            raise SubmitIntentInvalidFingerprint()
        if not 0 < len(slug) <= _MAX_SLUG_LEN:
            raise SubmitIntentInvalidSlug()
        with self._mutex:
            try:
                table = self._read_table()
            except SubmitIntentCorrupt:
                _LOG.warning("slot table is corrupt; arm_slot refused (fail closed)")
                raise SubmitIntentLatched() from None
            refusal = self._admission_locked(table, slug, is_exit, now_ns)
            if refusal is not None:
                blocker = table.open[0].intent_id if table.open else None
                raise SubmitIntentAdmissionDenied(refusal, blocker)
            single = self.max_slots() == 1
            intent = SubmitIntent(
                intent_id=uuid.uuid4().hex,
                fingerprint=fingerprint,
                created_ns=now_ns,
                state=SubmitIntentState.OPEN,
                retired_ns=None,
                retirement_reason=None,
                slug=None if single else slug,
                is_exit=False if single else is_exit,
            )
            self._store.set(
                CURRENT_INTENT_KEY,
                self._encode(
                    SlotTable(
                        version=table.version,
                        open=(*table.open, intent),
                        unreadable=table.unreadable,
                        cooloff=_live_cooloff(table.cooloff, now_ns),
                    )
                ),
            )
            return intent

    def _admission_locked(
        self, table: SlotTable, slug: str, is_exit: bool, now_ns: int
    ) -> str | None:
        k = self.max_slots()
        breaker_reason = None if k == 1 or is_exit else self._breaker_denial(now_ns)
        slugless = sum(1 for i in table.open if i.slug is None) if k > 1 else 0
        view = SlotTableView(
            open_slots=tuple(SlotRecord(i.intent_id, i.slug or "", i.is_exit) for i in table.open),
            unreadable_slots=len(table.unreadable) + slugless,
            cooloff=table.cooloff,
        )
        verdict = admit(view, slug, is_exit, k, breaker_reason is not None, now_ns)
        if isinstance(verdict, Wait):
            if verdict.reason == "entry_halt" and breaker_reason is not None:
                return breaker_reason
            return verdict.reason
        if len(table.open) + len(table.unreadable) >= 1 and not self._v2_permitted():
            return "v2_predicate"
        return None

    def _v2_permitted(self) -> bool:
        try:
            return bool(self._v2_predicate())
        except Exception:  # noqa: BLE001 - contained by contract: a raising predicate is a WAIT
            _LOG.exception("v2 slot-table predicate raised; treating as not permitted")
            return False

    def adopt_legacy_open_slugs(self, slug_of: Callable[[str], str | None]) -> int:
        """Give slug-less OPEN slots the slug ``slug_of(intent_id)`` finds (K > 1 only).

        A slot with no findable slug stays slug-less and so quarantined
        (``?:<id>``). Returns the number adopted; a no-op at an effective K of 1.
        """
        self._require_held()
        self._adoption_ran = True
        if self.max_slots() == 1:
            return 0
        with self._mutex:
            table = self._read_table()
            adopted = 0
            slots: list[SubmitIntent] = []
            for slot in table.open:
                found = self._find_slug(slug_of, slot) if slot.slug is None else None
                if found is None:
                    slots.append(slot)
                else:
                    slots.append(replace(slot, slug=found))
                    adopted += 1
            if adopted:
                self._store.set(CURRENT_INTENT_KEY, self._encode(replace(table, open=tuple(slots))))
            return adopted

    @staticmethod
    def _find_slug(slug_of: Callable[[str], str | None], slot: SubmitIntent) -> str | None:
        try:
            found = slug_of(slot.intent_id)
            if not isinstance(found, str) or not 0 < len(found) <= _MAX_SLUG_LEN:
                return None
        except Exception:  # noqa: BLE001 - a missing context quarantines, it never raises
            return None
        return found

    def seed_boot_cooloff(self, *, now_ns: int) -> int:
        """Give every non-exit slug OPEN at boot a synthetic cool-off (K > 1 only).

        Boot order is adopt-then-seed: a slug-less slot has nothing to cool, so
        seeding before :meth:`adopt_legacy_open_slugs` ran raises
        :class:`SubmitIntentBootOrderError`.
        """
        self._require_held()
        if self._k_configured == 1 or self._cooloff_ns == 0:
            return 0
        if not self._adoption_ran:
            raise SubmitIntentBootOrderError()
        with self._mutex:
            table = self._read_table()
            cooloff = _live_cooloff(table.cooloff, now_ns)
            slugs = [i.slug for i in table.open if i.slug is not None and not i.is_exit]
            for slug in slugs:
                cooloff = _with_cooloff(cooloff, slug, now_ns + self._cooloff_ns)
            if slugs:
                self._store.set(CURRENT_INTENT_KEY, self._encode(replace(table, cooloff=cooloff)))
            return len(slugs)

    # ------------------------------------------------------------------
    # Breaker record (latch side only; the watcher is the single writer)
    # ------------------------------------------------------------------

    def read_breaker_record(self) -> BreakerRecord | None:
        """The breaker record, ``None`` if absent; a garbled one raises ``SubmitIntentCorrupt``."""
        self._require_held()
        with self._mutex:
            return self._read_breaker()

    def write_breaker_heartbeat(self, *, hb_ns: int, resolver_pass_ns: int) -> None:
        """Write a heartbeat, preserving ``halted``. Never overwrites a garbled record."""
        self._require_held()
        with self._mutex:
            existing = self._read_breaker()
            self._store.set(
                BREAKER_KEY,
                encode_breaker(
                    BreakerRecord(
                        halted_reason=None if existing is None else existing.halted_reason,
                        halted_ts_ns=None if existing is None else existing.halted_ts_ns,
                        hb_ns=hb_ns,
                        resolver_pass_ns=resolver_pass_ns,
                        flag_write_failed=existing is not None and existing.flag_write_failed,
                    )
                ),
            )

    def write_breaker_halt(self, reason: str, *, ts_ns: int) -> None:
        """Latch the entry halt (sticky: the first reason stays). Overwrites a garbled record."""
        self._require_held()
        with self._mutex:
            try:
                existing = self._read_breaker()
            except SubmitIntentCorrupt:
                existing = None
            if existing is not None and existing.is_halted:
                return
            self._store.set(
                BREAKER_KEY,
                encode_breaker(
                    BreakerRecord(
                        halted_reason=reason,
                        halted_ts_ns=ts_ns,
                        hb_ns=0 if existing is None else existing.hb_ns,
                        resolver_pass_ns=0 if existing is None else existing.resolver_pass_ns,
                        flag_write_failed=existing is not None and existing.flag_write_failed,
                    )
                ),
            )

    def discard_unreadable_slot(
        self, key: str, *, now_ns: int, evidence_path: str, evidence_sha256: str
    ) -> None:
        """Operator recovery (node down): drop the unreadable slot ``key``.

        Only the recovery CLI calls this, and only after the original table
        bytes were dumped durably to ``evidence_path`` (whose SHA-256 is
        ``evidence_sha256``). Like :meth:`retire`, a history entry is written
        BEFORE the table: a valid RETIRED record (``OPERATOR_CLEARED``) whose
        id derives from ``key`` and whose fingerprint is the dump hash, plus
        trailing ``unreadable_slot_key``/``evidence_path``/``evidence_sha256``
        keys (the record decoder ignores them). Every other slot is re-emitted
        unchanged; removing the last slot makes that same record the v1
        RETIRED record, so an older reader still sees a valid one. A key that
        is not an unreadable slot raises :class:`SubmitIntentMismatch`.
        """
        self._require_held()
        if _FINGERPRINT_RE.fullmatch(evidence_sha256) is None:
            raise SubmitIntentInvalidFingerprint()
        with self._mutex:
            table = self._read_table()
            rest = tuple((k, v) for k, v in table.unreadable if k != key)
            if len(rest) == len(table.unreadable):
                raise SubmitIntentMismatch(key, None, None)
            record = SubmitIntent(
                intent_id=hashlib.sha256(key.encode("utf-8")).hexdigest()[:32],
                fingerprint=evidence_sha256,
                created_ns=now_ns,
                state=SubmitIntentState.RETIRED,
                retired_ns=now_ns,
                retirement_reason=RetirementReason.OPERATOR_CLEARED,
            )
            history = {
                **record.to_payload(),
                "unreadable_slot_key": key,
                "evidence_path": evidence_path,
                "evidence_sha256": evidence_sha256,
            }
            self._store.set(
                history_key(record.intent_id), json.dumps(history, sort_keys=True).encode("utf-8")
            )
            last = record if not rest and not table.open else None
            self._store.set(
                CURRENT_INTENT_KEY,
                self._encode(replace(table, unreadable=rest, last=last)),
            )

    def reset_breaker_halt(self) -> bool:
        """Operator reset (node down): clear ``halted``, keep the stamps.

        Returns ``False`` when no halted record exists. A garbled record
        raises ``SubmitIntentCorrupt`` and nothing is written: it may hide a
        halt and a ``flag_write_failed``, so it is never rebuilt silently.
        """
        self._require_held()
        with self._mutex:
            existing = self._read_breaker()
            if existing is None or not existing.is_halted:
                return False
            self._store.set(
                BREAKER_KEY,
                encode_breaker(
                    BreakerRecord(
                        None,
                        None,
                        hb_ns=existing.hb_ns,
                        resolver_pass_ns=existing.resolver_pass_ns,
                        flag_write_failed=existing.flag_write_failed,
                    )
                ),
            )
            return True

    def mark_flag_write_failed(self) -> None:
        """M3: record a lost force-K1 flag write on the breaker record (same single writer).

        A garbled breaker record raises ``SubmitIntentCorrupt`` and is left
        untouched. The caller (BG-5/BG-6) must treat that raise as an
        integrity stop: stop the heartbeat per D3.
        """
        self._set_flag_write_failed(True)

    def clear_flag_write_failed(self) -> None:
        """Clear the M3 field (N2: only ``--clear-force-k1`` calls this). Garbled raises."""
        self._set_flag_write_failed(False)

    def _set_flag_write_failed(self, value: bool) -> None:
        self._require_held()
        with self._mutex:
            # A garbled record raises: overwriting it would silently drop a halt.
            existing = self._read_breaker()
            self._store.set(
                BREAKER_KEY,
                encode_breaker(
                    BreakerRecord(
                        halted_reason=None if existing is None else existing.halted_reason,
                        halted_ts_ns=None if existing is None else existing.halted_ts_ns,
                        hb_ns=0 if existing is None else existing.hb_ns,
                        resolver_pass_ns=0 if existing is None else existing.resolver_pass_ns,
                        flag_write_failed=value,
                    )
                ),
            )

    def _read_breaker(self) -> BreakerRecord | None:
        raw = self._store.get(BREAKER_KEY)
        if raw is None:
            return None
        try:
            return parse_breaker(raw)
        except SlotTableError:
            raise SubmitIntentCorrupt() from None

    def _breaker_denial(self, now_ns: int) -> str | None:
        """Entry-denial label from ONE breaker ``get`` (K > 1), fail closed.

        ``now_ns`` is the caller's clock. A stamp more than
        ``BREAKER_FUTURE_SKEW_NS`` ahead of it is a clock fault and counts as
        stale.
        """
        try:
            record = self._read_breaker()
        except Exception as exc:  # noqa: BLE001 - unreadable breaker state denies entries
            _LOG.warning(
                "breaker record unreadable (%s); denying entries (fail closed)",
                type(exc).__name__,
            )
            return "breaker_unreadable"
        if record is None:
            return "breaker_absent" if now_ns - self._boot_ns > BREAKER_ABSENT_GRACE_NS else None
        if record.is_halted:
            return "breaker_halted"
        if not -BREAKER_FUTURE_SKEW_NS <= now_ns - record.hb_ns <= BREAKER_HEARTBEAT_MAX_AGE_NS:
            return "breaker_heartbeat_stale"
        age = now_ns - record.resolver_pass_ns
        if not -BREAKER_FUTURE_SKEW_NS <= age <= BREAKER_RESOLVER_PASS_MAX_AGE_NS:
            return "breaker_resolver_stale"
        return None

    def shared_state_binding(self) -> tuple[StateStore, _HeldSubmitIntentLock]:
        """Return the exact ``(store, lock)`` this latch was opened with.

        Read-only; grants no new access. Exists solely so
        ``current_rung_hold.trial_day_latch.open_trial_day_latch`` can bind a
        ``TrialDayLatch`` to the SAME store and the SAME exclusive flock this
        instance already holds, rather than opening a second store or a
        second flock (L-22: exclusion is unforgeable, not offered -- a
        parallel opener would leave two independent locks with crash windows
        that do not align, which is exactly the hazard the current_rung_hold
        peer review folded away). The caller receives no more than this
        instance already has: the store reference is the one already bound
        to this latch, and the lock token's ``.held`` still reflects this
        latch's own flock, so it flips to ``False`` the moment this latch's
        factory ``with`` exits. Raises ``SubmitIntentLockNotHeld`` if that
        has already happened.
        """
        self._require_held()
        return self._store, self._lock

    def _retired_history(self, current: SubmitIntent) -> tuple[SubmitIntent, bytes] | None:
        if _INTENT_ID_RE.fullmatch(current.intent_id) is None:
            raise SubmitIntentCorrupt()
        raw = self._store.get(history_key(current.intent_id))
        if raw is None:
            return None
        record = SubmitIntent.from_bytes(raw)
        if (
            record.state is SubmitIntentState.RETIRED
            and record.intent_id == current.intent_id
            and record.fingerprint == current.fingerprint
            and record.created_ns == current.created_ns
        ):
            return record, raw
        raise SubmitIntentCorrupt()


def _lock_unavailable_detail(exc: OSError) -> str:
    """Render an OSError's errno for diagnosis without implying contention.

    A non-contention OSError (e.g. EMFILE: too many open files) is fail-closed
    identically to genuine lock contention, but must be distinguishable from
    it after the fact -- "lock unavailable" names the errno instead of
    implying another holder.
    """
    code = exc.errno
    name = errno.errorcode.get(code, str(code)) if code is not None else "unknown"
    return f"lock unavailable: {name} ({exc.strerror})"


@contextmanager
def hold_submit_intent_process_lock(store_path: Path) -> Iterator[_HeldSubmitIntentLock]:
    """Hold an exclusive non-blocking flock beside the store, or fail closed."""
    lock_path = store_path.with_name(store_path.name + ".intent.lock")
    if not lock_path.parent.is_dir():
        raise SubmitIntentLockError()
    flags = os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC
    try:
        fd = os.open(lock_path, flags, 0o644)
    except OSError as exc:
        raise SubmitIntentLockError(_lock_unavailable_detail(exc)) from exc
    lock: _HeldSubmitIntentLock | None = None
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno in {errno.EWOULDBLOCK, errno.EAGAIN}:
                raise SubmitIntentLockHeld() from None
            raise SubmitIntentLockError(_lock_unavailable_detail(exc)) from exc
        lock = _HeldSubmitIntentLock(fd)
        yield lock
    finally:
        if lock is not None:
            lock.release()
        else:
            os.close(fd)


@contextmanager
def open_submit_intent_latch(
    store: StateStore,
    store_path: Path,
    *,
    max_slots: int = 1,
    cooloff_ns: int = DEFAULT_COOLOFF_NS,
    v2_predicate: Callable[[], bool] | None = None,
    clock_ns: Callable[[], int] | None = None,
) -> Iterator[SubmitIntentLatch]:
    """Acquire the exclusive process lock and yield a latch bound to it.

    Hold the returned latch for the process lifetime. ``arm`` → POST →
    ``retire`` must run on one thread. A second factory over the same store
    path raises ``SubmitIntentLockHeld``. Using the latch after this ``with``
    exits raises ``SubmitIntentLockNotHeld``.

    The keyword arguments configure the EXEC-PAR slot table and default to
    the single-slot (K=1) behaviour: ``max_slots`` is K, ``v2_predicate`` gates
    every 1 -> 2 transition (default: never), ``clock_ns`` times the breaker
    checks.
    """
    with hold_submit_intent_process_lock(store_path) as lock:
        yield SubmitIntentLatch(
            store,
            lock,
            max_slots=max_slots,
            cooloff_ns=cooloff_ns,
            v2_predicate=v2_predicate,
            clock_ns=clock_ns,
        )
