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
``ingest/gate.py`` does, and in production that store is
``breezy.runtime.sqlite_store.SqliteStateStore``. The Nautilus ``Cache`` was
evaluated for the role and rejected on measured evidence (``Cache.add``
returns before the write is durable, ``Cache.get`` never reads the database,
``Cache.reset()`` can launder a permanent halt), so durability is no longer a
matter of getting five ``Cache``/kernel settings right. It is established at
startup, empirically, by ``gate.assert_state_store_durable``, which
round-trips a probe value through the real store and an independent handle on
its backing medium rather than trusting any declared flag. Keys here are
namespaced under ``productidx:`` so one store can serve both this index and
the gate.

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

#: A durable manifest of every ``product_uuid`` this index has ever recorded
#: a FIRST_SEEN entry for -- a JSON array, written under one fixed key
#: disjoint from every real ``productidx:<uuid>`` entry (no uuid is ever
#: literally ``__manifest__``).
#:
#: **The blind spot this closes.** Unlike ``gate.py``'s single global entry,
#: absence of an individual ``productidx:<uuid>`` key is the ORDINARY case
#: for the overwhelming majority of uuids (every one never yet observed) --
#: a single yes/no sentinel cannot tell "genuinely new" apart from
#: "previously recorded, now missing" the way it can for a singleton. This
#: manifest is the per-key equivalent: on a miss for the primary key, this
#: is consulted, and only a uuid genuinely absent from BOTH counts as
#: first-seen. A uuid present in the manifest but missing its entry key
#: means something removed the entry without removing the record of having
#: seen it -- treated as :attr:`ProductIntegrityOutcome.MISMATCH`, never as
#: first-seen, exactly the WEATHER_INGESTION_PROPOSAL-mandated bias toward
#: an integrity halt over a silent pass.
#:
#: Written FIRST, before the primary entry, on every FIRST_SEEN (see
#: :meth:`ProductIntegrityIndex.observe`): if the process dies or the store
#: raises between the two writes, the manifest already lists the uuid,
#: so a retry that lands with the entry still missing correctly reads as
#: tampered rather than as a second legitimate first-seen -- the safer of
#: the two possible orderings.
#:
#: Cannot detect the whole backing medium being deleted and recreated --
#: this key lives in the same store as everything else, and no witness
#: inside a medium can outlive that medium's own destruction. It closes the
#: achievable case: a store that is still there and answering, but has lost
#: one entry.
_MANIFEST_KEY = f"{PRODUCT_INDEX_KEY_PREFIX}__manifest__"

_HEX_DIGEST = re.compile(r"\A[0-9a-f]{64}\Z")

#: A canonical, LOWERCASE product uuid as api.weather.gov assigns it.
#:
#: Exactly as strict as :data:`_HEX_DIGEST`, and for the same reason. When
#: this only required "a non-empty str", a uuid differing from a stored one
#: ONLY in case keyed a SECOND first-write-wins entry -- so the same product's
#: mutated bytes read as FIRST_SEEN and the integrity alarm never fired. Case
#: split the index; strictness closes it.
#:
#: Matched, never normalised. The uuid is a settlement identifier: it must be
#: byte-identical to the id fetched and the id recorded as provenance, so a
#: non-canonical form is rejected loudly rather than silently lower-cased
#: (``breezy.ingest.nws_envelope`` takes the same stance for the same reason).
_PRODUCT_UUID = re.compile(r"\A[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z")


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

    Structurally identical to ``gate.StateStore`` on purpose: the Actor hands
    ONE store object to both this index and the gate (their key namespaces,
    ``productidx:`` and ``gate:``, do not collide). It is declared here rather
    than imported so this module carries no gate dependency.

    That store is ``breezy.runtime.sqlite_store.SqliteStateStore``, **not** the
    native Nautilus ``Cache``, which was examined and DECLINED with the
    evidence recorded in that module's docstring: under this deployment's
    ``CacheConfig(database=None)`` the ``Cache`` is memory-only, and its only
    supported backing is a Redis server this deployment does not have.
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
    """Return `value` if it is a canonical lowercase product uuid.

    As strict as :func:`_require_hex_digest`, deliberately: see
    :data:`_PRODUCT_UUID` for the index-splitting defect that laxness caused.
    Never normalises -- an upper-case or `urn:uuid:`-wrapped id means some
    component produced a non-canonical settlement identifier, and that
    component is what needs fixing.
    """
    if not isinstance(value, str):
        raise TypeError(f"`product_uuid` must be a `str`, was {type(value).__name__}")
    if _PRODUCT_UUID.match(value) is None:
        raise ValueError(
            "`product_uuid` must be a canonical lowercase UUID "
            f"(8-4-4-4-12 hex, no braces or 'urn:uuid:' prefix), was {value!r}. "
            "It is matched byte-identically and never normalised, because it is "
            "a settlement identifier."
        )
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

    def _manifest_claims(self, product_uuid: str) -> bool:
        """Whether the durable manifest says `product_uuid` was previously
        recorded, consulted ONLY when the primary entry key is absent.

        Fails closed on an unreadable manifest: if the manifest itself
        cannot be decoded, this returns ``True`` for every uuid rather than
        ``False`` for this one -- corruption of the very record that proves
        a uuid is genuinely new must never be read as "therefore it must be
        new". That is a deliberate, sticky posture (every FIRST_SEEN is
        refused until the manifest is repaired), matching this module's
        stance elsewhere: corruption is itself the integrity signal, not a
        free pass.
        """
        raw = self._store.get(_MANIFEST_KEY)
        if raw is None:
            return False
        try:
            payload: Any = json.loads(raw.decode("utf-8"))
            if not isinstance(payload, list) or not all(isinstance(item, str) for item in payload):
                raise TypeError("manifest must be a JSON array of strings")
        except (ValueError, TypeError, KeyError) as exc:
            logger.critical(
                "product index: UNREADABLE bootstrap manifest -- failing closed "
                "for EVERY uuid with a missing entry (none can be proven "
                "genuinely new until the manifest is repaired). error=%s",
                exc,
            )
            return True
        return product_uuid in payload

    def _record_in_manifest(self, product_uuid: str) -> None:
        """Durably add `product_uuid` to the first-seen manifest.

        Only ever called from :meth:`observe` after :meth:`_load` has
        already returned ``None`` for this uuid -- which itself only
        happens when the manifest was either absent or successfully
        decoded (see :meth:`_manifest_claims`: a corrupt manifest makes
        `_load` return a :class:`_CorruptEntry` instead, and `observe`
        never reaches this call in that case). So the read here can never
        observe a manifest this process just proved was corrupt; no
        decode-failure recovery is needed, and a `json.loads` failure here
        would indicate a genuine, single-threaded ordering bug rather than
        ordinary corruption, so it is allowed to propagate rather than
        being silently swallowed.
        """
        raw = self._store.get(_MANIFEST_KEY)
        manifest: list[str]
        if raw is None:
            manifest = []
        else:
            payload: Any = json.loads(raw.decode("utf-8"))
            # `_manifest_claims` already validated these exact bytes as a
            # JSON array of strings before `_load` could ever return
            # `None` for this uuid -- the precondition for reaching this
            # method at all (see its docstring). A `list[str]` cast, not a
            # defensive re-check.
            manifest = list(payload)
        # `product_uuid` cannot already be in `manifest`: this is only
        # called from `observe()`'s FIRST_SEEN branch, reached only when
        # `_manifest_claims(product_uuid)` (consulted by `_load`) already
        # returned `False` for it.
        manifest.append(product_uuid)
        self._store.set(_MANIFEST_KEY, json.dumps(manifest).encode("utf-8"))

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
            if self._manifest_claims(product_uuid):
                # The manifest says this uuid was recorded before, but its
                # entry key is gone -- NOT a clean slate. Silently reading
                # this as "never seen" is exactly the laundering closed
                # here: a mutated re-fetch of a KNOWN uuid would read as
                # FIRST_SEEN instead of MISMATCH, silently accepting
                # changed bytes under a stable id. Never cached as a
                # _CorruptEntry-shaped return so the manifest is
                # re-consulted every time -- a later repair of the entry
                # key must be able to clear this without a process
                # restart.
                logger.critical(
                    "product index: entry MISSING for product_uuid=%s despite "
                    "the durable manifest recording it as previously "
                    "observed -- failing closed to MISMATCH rather than "
                    "first-seen.",
                    product_uuid,
                )
                return _CorruptEntry(
                    detail=(
                        f"product_uuid={product_uuid} is listed in the durable "
                        "manifest as previously observed, but its integrity "
                        "entry is missing"
                    )
                )
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
            # Manifest FIRST, entry SECOND -- deliberately, and the only
            # safe order. If the process dies (or store.set() raises)
            # between the two writes, the manifest already lists `uuid`; a
            # later retry that finds the entry still missing then correctly
            # reads as tampered (via _manifest_claims) rather than being
            # silently allowed a second legitimate FIRST_SEEN. The reverse
            # order would let exactly that crash window read as "never
            # seen" forever -- the same laundering this manifest exists to
            # close, just relocated to a narrower window.
            self._record_in_manifest(uuid)
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
