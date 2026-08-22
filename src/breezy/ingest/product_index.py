"""First-write-wins ``product_uuid -> raw_sha256`` integrity index.

Governing ruling: ``docs/plans/PHASE1_ACTOR_BRIEF.md`` SS3.4, consumed at step 5
of the SS6 poll sequence.

**The blind spot this closes.** Supersession keys on
``(venue, city, climate_day, issuance_class, revision_seq)`` and resolves by
``(is_final, ts_init, revision_seq)``. That is correct for genuine reissues --
NWS re-issuing a corrected product assigns it a *new* ``product_uuid``, which
supersession sees as an ordinary later revision. But it makes the most alarming
case invisible: the **same** ``product_uuid`` observed twice with a **different**
``raw_sha256``. An already-issued product's bytes changing underneath us is
upstream mutation, an integrity event -- not a revision -- and the supersession
key silently absorbs it as a normal update.

So this index answers exactly one question, and nothing else:

    have I seen this uuid before, and if so, were the bytes the same?

**First-write-wins is the whole design.** The first observation is the
evidence. It is written once and never overwritten -- not on mismatch, not on
retry, not ever -- because a later write would destroy the only record of what
the product said when we first saw it.

**Durability is not optional.** An in-memory-only index makes every restart a
clean slate, which is precisely the laundering this exists to prevent: crash,
restart, re-observe the mutated bytes, and the mutation reads as first-seen.
State therefore goes through an injected :class:`StateStore`, exactly as
``ingest/gate.py`` does, and the Actor backs that with ``Cache.add`` /
``Cache.get`` (which require all three of ``ActorConfig.save_state``,
``ActorConfig.load_state`` and ``CacheConfig.database`` -- see
``gate.assert_cache_persistence_configured``). Keys are namespaced under
``productidx:`` so one store can serve both this index and the gate.

**No gate dependency, by design.** A digest mismatch is a CRIT integrity signal,
but this module does not call the gate -- it returns a typed outcome and the
Actor wires the two together. That keeps the index independently testable and
keeps a safety state machine from being reachable through two doors.

This module is deliberately dependency-free (no ``import nautilus_trader``, and
no ``breezy.domain`` import either -- importing that package executes every
record module's module-scope ``register_arrow``, a heavyweight global side
effect an integrity index has no business triggering). The ~6 lines of digest
validation duplicated from ``domain/validation.py`` are the price of that
isolation, and they are stated here rather than hidden.

**Growth.** One entry per NWS product, forever. It is deliberately **not**
bounded -- see the module-level note under :data:`PRODUCT_INDEX_KEY_PREFIX`.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol

logger = logging.getLogger(__name__)

#: Key namespace for this index inside a shared :class:`StateStore`.
#:
#: **Growth is unbounded, on purpose.** One entry accumulates per distinct NWS
#: product and is never evicted. At five cities x two CLI issuances per day that
#: is ~3,650 entries/year; each entry is a ~46-byte key plus a ~110-byte JSON
#: value, so ~600 KB/year, ~6 MB/decade, mirrored by an in-process cache of the
#: uuids this process has actually touched. That cost is accepted rather than
#: engineered away, because every eviction policy reintroduces the exact hole
#: this module closes: a pruned uuid re-observed with mutated bytes reads as
#: first-seen. If the durable store ever must be trimmed, it has to be an
#: audited archival that RETAINS the digest and leaves this index able to fail
#: closed on the archived uuid -- never a delete.
PRODUCT_INDEX_KEY_PREFIX = "productidx:"

_HEX_DIGEST = re.compile(r"\A[0-9a-f]{64}\Z")


def _index_key(product_uuid: str) -> str:
    return f"{PRODUCT_INDEX_KEY_PREFIX}{product_uuid}"


# ---------------------------------------------------------------------------
# Public value types
# ---------------------------------------------------------------------------


class ProductIntegrityOutcome(str, Enum):
    """The three-way result of observing a ``(product_uuid, raw_sha256)`` pair.

    Deliberately three-way and no wider: corrupt persisted state resolves to
    :attr:`MISMATCH` rather than to a fourth member, so no caller can ever
    forget to branch on it. :attr:`ProductIntegrityResult.first_seen_sha256`
    is ``None`` in exactly that case if the distinction matters for logging.
    """

    #: This uuid had never been observed. The digest has just been recorded.
    FIRST_SEEN = "first_seen"
    #: Known uuid, identical digest -- the ordinary re-poll. Not an alarm.
    MATCH = "match"
    #: Known uuid, DIFFERENT digest (or unreadable persisted evidence).
    #: A CRIT integrity event: the caller hard-blocks the site.
    MISMATCH = "mismatch"


@dataclass(frozen=True, slots=True)
class ProductIntegrityResult:
    """Immutable outcome of a single :meth:`ProductIntegrityIndex.observe`.

    Attributes
    ----------
    product_uuid : str
        The uuid observed.
    observed_sha256 : str
        The digest just presented.
    outcome : ProductIntegrityOutcome
        The three-way verdict.
    first_seen_sha256 : str or None
        The digest recorded on the FIRST observation of this uuid -- the value
        that is never overwritten. ``None`` **only** when the persisted entry
        existed but could not be read; that case is reported as
        :attr:`~ProductIntegrityOutcome.MISMATCH`, never as first-seen.
    first_seen_at_ns : int or None
        Injected-clock nanosecond timestamp of the first observation, or
        ``None`` under the same unreadable-entry case.
    observed_at_ns : int
        Injected-clock nanosecond timestamp of this observation.
    detail : str
        Human-facing explanation, for logs and 07:30 incident triage.
    """

    product_uuid: str
    observed_sha256: str
    outcome: ProductIntegrityOutcome
    first_seen_sha256: str | None
    first_seen_at_ns: int | None
    observed_at_ns: int
    detail: str

    @property
    def is_integrity_alarm(self) -> bool:
        """Whether this outcome is the CRIT integrity event of SS3.4."""
        return self.outcome is ProductIntegrityOutcome.MISMATCH


class CorruptProductIndexEntryError(Exception):
    """Raised by :meth:`ProductIntegrityIndex.known_digest` when persisted
    evidence for a uuid exists but cannot be decoded.

    ``known_digest`` returns ``None`` for "never observed", so an unreadable
    entry cannot be reported through the return value without reading as a
    clean slate. It raises instead -- corruption must never be a free pass for
    a mutated product.
    """

    def __init__(self, product_uuid: str, detail: str) -> None:
        super().__init__(f"unreadable product-index entry for {product_uuid}: {detail}")
        self.product_uuid = product_uuid
        self.detail = detail


# ---------------------------------------------------------------------------
# Injectable persistence seam
# ---------------------------------------------------------------------------


class StateStore(Protocol):
    """The minimal persistence seam this module needs.

    Structurally identical to ``gate.StateStore`` on purpose: the Actor backs
    both with the same ``Cache.add`` / ``Cache.get`` pair and may pass one
    object to both (the key namespaces do not collide). It is declared here
    rather than imported so this module carries no gate dependency.
    """

    def get(self, key: str) -> bytes | None: ...

    def set(self, key: str, value: bytes) -> None: ...


# ---------------------------------------------------------------------------
# Internal persisted state
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _IndexEntry:
    raw_sha256: str
    first_seen_at_ns: int


@dataclass(frozen=True, slots=True)
class _CorruptEntry:
    """In-memory marker that persisted bytes for a uuid could not be decoded.

    Never written back to the store -- the bad bytes stay put as forensic
    evidence, matching ``gate._load_site``'s posture.
    """

    detail: str


def _require_product_uuid(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError(f"`product_uuid` must be a `str`, was {type(value).__name__}")
    if not value.strip():
        raise ValueError("`product_uuid` must be a non-empty `str`")
    return value


def _require_hex_digest(value: object, name: str) -> str:
    """Return `value` if it is a 64-character lowercase hex SHA-256 digest.

    Strict rather than normalising: silently lower-casing an upper-case digest
    would mask whichever component produced a non-canonical value, and an
    empty or truncated digest first-written into the index would be an
    integrity hole rather than an integrity record.
    """
    if not isinstance(value, str) or not _HEX_DIGEST.match(value):
        raise ValueError(
            f"`{name}` must be a 64-character lowercase hex SHA-256 digest, was {value!r}",
        )
    return value


def _entry_to_bytes(entry: _IndexEntry) -> bytes:
    return json.dumps(
        {"raw_sha256": entry.raw_sha256, "first_seen_at_ns": entry.first_seen_at_ns},
    ).encode("utf-8")


def _entry_from_bytes(raw: bytes) -> _IndexEntry:
    """Decode a persisted entry, validating every field.

    Structure alone is not enough: a syntactically valid entry carrying a
    non-canonical digest would produce a confident but meaningless MATCH or
    MISMATCH verdict, so the digest is re-validated on read.
    """
    payload: Any = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(
            f"persisted entry must be a JSON object, was {type(payload).__name__}",
        )
    digest = _require_hex_digest(payload["raw_sha256"], "raw_sha256")
    at_ns = payload["first_seen_at_ns"]
    if isinstance(at_ns, bool) or not isinstance(at_ns, int):
        raise TypeError(
            f"`first_seen_at_ns` must be an `int`, was {type(at_ns).__name__}",
        )
    return _IndexEntry(raw_sha256=digest, first_seen_at_ns=at_ns)


# ---------------------------------------------------------------------------
# The index
# ---------------------------------------------------------------------------


class ProductIntegrityIndex:
    """First-write-wins ``product_uuid -> raw_sha256`` index.

    Construct once per process, backed by a persistent :class:`StateStore` and
    an injected nanosecond clock (never the wall clock directly, so replay
    stays deterministic). Entries load lazily per uuid, are cached in memory
    after a successful durable read or write, and are written back **exactly
    once** -- on the first observation of a uuid and never again.
    """

    def __init__(self, *, store: StateStore, clock: Callable[[], int]) -> None:
        self._store = store
        self._clock = clock
        self._entries: dict[str, _IndexEntry | _CorruptEntry] = {}

    # -- internals ------------------------------------------------------

    def _load(self, product_uuid: str) -> _IndexEntry | _CorruptEntry | None:
        """Return the cached/persisted entry for `product_uuid`, or ``None``
        if it has genuinely never been observed.

        A ``store.get`` that *raises* is deliberately allowed to propagate
        rather than being folded into a MISMATCH. An unreachable cache
        database is an infrastructure outage, and reporting it as an integrity
        alarm would both cry wolf on the most serious signal this module has
        and latch a sticky CRIT for a transient blip. Propagating is still
        fail-closed -- no outcome is returned at all, so the poll aborts into
        the Actor's task supervision and the site blocks. What must never
        happen is the third option: reading an unavailable store as
        "never seen".
        """
        cached = self._entries.get(product_uuid)
        if cached is not None:
            return cached

        raw = self._store.get(_index_key(product_uuid))
        if raw is None:
            # Deliberately NOT cached. Absence is the one state a later
            # successful write must be able to replace; caching it would let a
            # failed persist look settled.
            return None

        try:
            entry: _IndexEntry | _CorruptEntry = _entry_from_bytes(raw)
        except (ValueError, TypeError, KeyError) as exc:
            # Fail closed. Corrupt bytes mean something overwrote our integrity
            # evidence, so the safe reading is "we can no longer vouch for this
            # uuid", never "we have never seen it". The bad bytes are left in
            # the store untouched -- an in-memory recovery, not a silent
            # rewrite of forensic evidence.
            logger.critical(
                "product index: UNREADABLE persisted entry for product_uuid=%s "
                "-- failing closed to MISMATCH. error=%s",
                product_uuid,
                exc,
            )
            entry = _CorruptEntry(detail=f"corrupt persisted bytes: {exc}")

        self._entries[product_uuid] = entry
        return entry

    # -- public API -----------------------------------------------------

    def observe(self, product_uuid: str, raw_sha256: str) -> ProductIntegrityResult:
        """Record or verify the digest first seen for `product_uuid`.

        Returns the three-way :class:`ProductIntegrityResult`. Writes to the
        store on -- and only on -- :attr:`~ProductIntegrityOutcome.FIRST_SEEN`;
        a match and a mismatch are both read-only, so the first-seen digest is
        never overwritten.

        Raises
        ------
        TypeError
            If `product_uuid` is not a `str`.
        ValueError
            If `product_uuid` is empty, or `raw_sha256` is not a canonical
            64-character lowercase hex SHA-256 digest. Validation runs before
            any store access, so a malformed digest can never be first-written.
        """
        uuid = _require_product_uuid(product_uuid)
        observed = _require_hex_digest(raw_sha256, "raw_sha256")

        entry = self._load(uuid)
        now = self._clock()

        if entry is None:
            new_entry = _IndexEntry(raw_sha256=observed, first_seen_at_ns=now)
            # Persist FIRST, cache second. If store.set() raises (or the
            # process dies between the two statements), the in-memory view
            # must never advance ahead of the durable one -- a memory-only
            # first-seen would report MATCH on the next observation while the
            # store still knows nothing, laundering a mutation across the
            # restart that follows.
            self._store.set(_index_key(uuid), _entry_to_bytes(new_entry))
            self._entries[uuid] = new_entry
            return ProductIntegrityResult(
                product_uuid=uuid,
                observed_sha256=observed,
                outcome=ProductIntegrityOutcome.FIRST_SEEN,
                first_seen_sha256=observed,
                first_seen_at_ns=now,
                observed_at_ns=now,
                detail=f"first observation of product_uuid={uuid}",
            )

        if isinstance(entry, _CorruptEntry):
            return ProductIntegrityResult(
                product_uuid=uuid,
                observed_sha256=observed,
                outcome=ProductIntegrityOutcome.MISMATCH,
                first_seen_sha256=None,
                first_seen_at_ns=None,
                observed_at_ns=now,
                detail=(
                    f"cannot verify product_uuid={uuid}: {entry.detail}. "
                    "Failing closed -- an unreadable entry is not a clean slate."
                ),
            )

        if entry.raw_sha256 == observed:
            return ProductIntegrityResult(
                product_uuid=uuid,
                observed_sha256=observed,
                outcome=ProductIntegrityOutcome.MATCH,
                first_seen_sha256=entry.raw_sha256,
                first_seen_at_ns=entry.first_seen_at_ns,
                observed_at_ns=now,
                detail=f"digest unchanged since first observation of product_uuid={uuid}",
            )

        detail = (
            f"INTEGRITY: product_uuid={uuid} was first seen with "
            f"raw_sha256={entry.raw_sha256} at ts={entry.first_seen_at_ns} and is now "
            f"reported as raw_sha256={observed}. An already-issued NWS product "
            "changed bytes under a stable uuid -- upstream mutation, not a revision."
        )
        logger.critical("product index: %s", detail)
        return ProductIntegrityResult(
            product_uuid=uuid,
            observed_sha256=observed,
            outcome=ProductIntegrityOutcome.MISMATCH,
            first_seen_sha256=entry.raw_sha256,
            first_seen_at_ns=entry.first_seen_at_ns,
            observed_at_ns=now,
            detail=detail,
        )

    def known_digest(self, product_uuid: str) -> str | None:
        """Return the first-seen digest for `product_uuid` without recording
        an observation, or ``None`` if it has never been observed.

        Read-only: never writes, never creates an entry.

        Raises
        ------
        TypeError
            If `product_uuid` is not a `str`.
        ValueError
            If `product_uuid` is empty.
        CorruptProductIndexEntryError
            If persisted evidence exists but cannot be decoded. ``None`` is
            reserved for "never observed" and must not be overloaded to mean
            "unreadable" -- that would turn corruption into a clean slate.
        """
        uuid = _require_product_uuid(product_uuid)
        entry = self._load(uuid)
        if entry is None:
            return None
        if isinstance(entry, _CorruptEntry):
            raise CorruptProductIndexEntryError(uuid, entry.detail)
        return entry.raw_sha256
