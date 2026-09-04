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
import json
import os
import re
import threading
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path
from typing import Final, Protocol, Self

CURRENT_INTENT_KEY: Final[str] = "exec/polymarket_us/intent/current"
_SCHEMA_VERSION: Final[int] = 1
_FINGERPRINT_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")
_INTENT_ID_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{32}$")


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

    def __init__(self) -> None:
        super().__init__("submit intent process lock could not be acquired")


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


@dataclass(frozen=True, slots=True)
class SubmitIntent:
    intent_id: str
    fingerprint: str = field(repr=False)
    created_ns: int
    state: SubmitIntentState
    retired_ns: int | None
    retirement_reason: RetirementReason | None

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
        payload = {
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
        return json.dumps(payload, sort_keys=True).encode("utf-8")

    @classmethod
    def from_bytes(cls, raw: bytes) -> Self:
        try:
            decoded: object = json.loads(raw.decode("utf-8"))
        except ValueError:
            decoded = None
        if not isinstance(decoded, dict):
            raise SubmitIntentCorrupt()
        payload: dict[str, object] = decoded
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


class SubmitIntentLatch:
    """One-at-a-time submit latch persisted through ``StateStore.get``/``set``.

    Constructed only by :func:`open_submit_intent_latch`, which binds this
    instance to an exclusive flock. Every public method asserts that flock
    is still held.
    """

    def __init__(self, store: StateStore, lock: _HeldSubmitIntentLock) -> None:
        self._store = store
        self._lock = lock
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

    def _require_held(self) -> None:
        if not self._lock.held:
            raise SubmitIntentLockNotHeld()

    def current(self) -> SubmitIntent | None:
        self._require_held()
        raw = self._store.get(CURRENT_INTENT_KEY)
        if raw is None:
            return None
        return SubmitIntent.from_bytes(raw)

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
            self._store.set(CURRENT_INTENT_KEY, intent.to_bytes())
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
        has_durable_fill_record: Callable[[str], object],
        now_ns: int,
    ) -> SubmitIntent | None:
        """Repair a crash between history write and singleton write.

        History matching the OPEN singleton (id, fingerprint, created_ns)
        is copied verbatim onto the singleton -- the original reason and
        ``retired_ns`` are the audit fact, not a stamped startup reason.
        A corrupt singleton raises ``SubmitIntentCorrupt`` (never repaired).
        A damaged or mismatched history record leaves the singleton OPEN
        and does not consult the fill probe: a damaged ledger stays closed.
        """
        self._require_held()
        with self._mutex:
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
                self._store.set(CURRENT_INTENT_KEY, raw)
                return record
            if has_durable_fill_record(current.fingerprint) is True:
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
        current = self.current()
        if (
            current is None
            or current.state is not SubmitIntentState.OPEN
            or current.intent_id != intent_id
        ):
            current_id = None if current is None else current.intent_id
            current_state = None if current is None else current.state.value
            raise SubmitIntentMismatch(intent_id, current_id, current_state)
        retired = _retired_from(current, reason, now_ns)
        self._store.set(history_key(intent_id), retired.to_bytes())
        self._store.set(CURRENT_INTENT_KEY, retired.to_bytes())
        return retired

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


@contextmanager
def hold_submit_intent_process_lock(store_path: Path) -> Iterator[_HeldSubmitIntentLock]:
    """Hold an exclusive non-blocking flock beside the store, or fail closed."""
    lock_path = store_path.with_name(store_path.name + ".intent.lock")
    if not lock_path.parent.is_dir():
        raise SubmitIntentLockError()
    flags = os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC
    try:
        fd = os.open(lock_path, flags, 0o644)
    except OSError:
        raise SubmitIntentLockError() from None
    lock: _HeldSubmitIntentLock | None = None
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno in {errno.EWOULDBLOCK, errno.EAGAIN}:
                raise SubmitIntentLockHeld() from None
            raise SubmitIntentLockError() from None
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
) -> Iterator[SubmitIntentLatch]:
    """Acquire the exclusive process lock and yield a latch bound to it.

    Hold the returned latch for the process lifetime. ``arm`` → POST →
    ``retire`` must run on one thread. A second factory over the same store
    path raises ``SubmitIntentLockHeld``. Using the latch after this ``with``
    exits raises ``SubmitIntentLockNotHeld``.
    """
    with hold_submit_intent_process_lock(store_path) as lock:
        yield SubmitIntentLatch(store, lock)
