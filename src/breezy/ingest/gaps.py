"""Durable gap ledger: which climate days were expected, observed, missing.

Governing ruling: ``docs/plans/PHASE_CD_COLLECTION_DURABILITY_DESIGN.md`` SS3
(WI-10), read together with ``docs/plans/NWS_COLLECTION_RUNTIME_PLAN_ADDENDUM.md``
for why the design's original citations needed re-verifying against this repo.

**The blind spot this closes.** ``gate.check_freshness`` (``ingest/gate.py``)
measures elapsed time since the last *successful* poll only -- verified here,
not taken on trust: it has no concept of a *set* of missed climate days, only
"how long since anything worked". ``gate.record_final_overdue`` /
``record_final_received`` are keyed to exactly ONE climate day
(``final_overdue_climate_day``, a single string field on the site entry) and
are cleared the instant a final for that one day arrives -- there is no
memory of a day that was overdue, then apparently cleared, then never
actually persisted. Neither mechanism can answer "which specific days did we
never actually collect", and both reset to a clean slate on every clean poll.
This module is Nautilus's null hypothesis rebutted: nothing in Nautilus
Trader models "a climate day that should exist and does not" -- there is no
adapter, no cache query, no ``Actor`` mixin for it -- so this is new, and
built as the smallest correct extension.

**Null hypothesis, second target.** Could this just be a bigger
``check_freshness``? No: freshness is a *liveness* signal (is NWS still
answering us), and this ledger is a *completeness* signal (did a specific
day's data actually land durably). A site can poll perfectly cleanly forever
while one specific day's final silently never arrives, or arrives and is lost
in the crash window between observe and persist that
``NWS_COLLECTION_RUNTIME_PLAN_ADDENDUM.md`` SS0b documents. Freshness cannot
see that; only per-day accounting can.

**The store compromise, stated plainly.** ``runtime.sqlite_store.SqliteStateStore``
exposes only ``get``/``set``/``close`` over ``bytes`` -- no scan, no delete
(verified by reading the module: see its docstring and the three public
methods). Enumeration is therefore impossible without a durable manifest, so
this ledger carries its own, under a fixed key disjoint from every real entry
key -- **exactly** the pattern already reviewed and shipped in
``ingest/product_index.py`` (SS ``_MANIFEST_KEY`` there), reused rather than
reinvented. Deletion is impossible, so **nothing is ever removed**:
resolution and acknowledgement are state transitions written into the entry
value, never a key removal.

**Two clocks, and conflating them is the top risk this module exists to
avoid.** The climate-day boundary uses the FIXED standard-time offset
(``std_utc_offset_hours``, never DST -- see
``breezy.normalize.climate_day.standard_time_zone``). The review-extension
threshold that decides when a day becomes EXPECTED uses the venue's
DST-following settlement clock (``settlement_delay_time_local`` /
``settlement_delay_timezone``, 11:00 America/New_York for every site today).
``registry.sites`` deliberately keeps these on two separate accessor types
(``ClimateDayWindow`` vs ``SettlementDeadline``) so a caller cannot reach for
the wrong one by autocomplete; this module keeps that separation in its own
parameter names rather than collapsing them into one "timezone" argument.

:func:`most_recent_completed_climate_day` is the SAME derivation
``ingest.nws_actor.NwsIngestActor._most_recent_completed_climate_day`` uses --
extracted here as the one pure copy so there is exactly one implementation of
that arithmetic in the whole repo, not two that could drift.

**The 08:00 -> 11:00 ET METAR-review extension.** A day becomes EXPECTED only
once :func:`review_extension_end_ns` (11:00 ET, ``settlement_delay_*``) has
passed -- NOT at the 08:00 ET settlement deadline
(``gate.record_final_overdue`` / ``NwsIngestActor.check_final_deadline``'s
concern, a different question entirely and not this module's). A final
arriving at 09:30 ET is inside the review window, so no entry is EVER
created for that day -- the false positive is designed out at the point of
candidacy, never suppressed after the fact by discarding an entry that was
already written.

**Retention figure is an ASSUMPTION, not a cited fact.** ``api.weather.gov``
is understood informally to retain recent products for roughly a week, but
that figure has never been confirmed against NWS's own documentation or
measured directly -- treat :data:`RETENTION_DAYS_ASSUMPTION` as a
conservative estimate, not a guarantee. It must never be confused with
``registry.sites.SettlementDeadline.no_data_fallback_days`` (7 in
``sites.toml`` too, coincidentally): that field is a VENUE SETTLEMENT rule
about when Breezy falls back to a no-data settlement outcome, not an API
retention guarantee, and this module never reads it.

**Growth.** One entry per ``(site, climate_day)`` that ever fails to arrive
by its review-extension deadline, forever (never evicted, matching
``product_index.py``'s acceptance of unbounded growth for the same
store-cannot-delete reason). At five sites this is at most 1,825 entries/year,
~200 bytes each, ~0.4 MB/year -- accepted, not engineered around.

**Attachment point (NOT wired here).** Per the design, ``reconcile`` belongs
at the very top of ``NwsIngestActor.poll_once``, beside
``self.check_staleness()`` and before the ``network_allowed()`` early return
-- the only line reached on every timer fire, including the 304 branch, the
no-new-products branch and the network-disallowed branch. Wiring
``poll_once`` is an explicitly separate work item; this module only provides
the call surface documented below.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass, replace
from enum import Enum
from typing import Any, Final, Protocol
from zoneinfo import ZoneInfo

from breezy.normalize.climate_day import standard_time_zone

logger = logging.getLogger(__name__)

_NS_PER_SECOND: Final[int] = 1_000_000_000

#: Key namespace for this ledger inside a shared :class:`StateStore`, disjoint
#: from ``gate:`` (``ingest/gate.py``) and ``productidx:`` (``ingest/product_index.py``)
#: so one store may safely serve all three.
GAP_KEY_PREFIX: Final[str] = "gaps:"

#: Durable manifest of every gap-entry id this ledger has ever written, a JSON
#: array of ``"<venue>|<city>|<YYYY-MM-DD>"`` strings under one fixed key. Pipe
#: separators, deliberately different from the colon-separated entry keys
#: below, so an id can never be mistaken for a key. Written FIRST on every new
#: entry, entry SECOND -- the same ordering, and the same reason, as
#: ``product_index.py``: if the process dies between the two writes, the
#: manifest already lists the id, so a later read that finds the entry itself
#: missing correctly reads as tampering rather than as a legitimate re-create.
_MANIFEST_KEY: Final[str] = f"{GAP_KEY_PREFIX}__manifest__"

#: Per-site high-water mark key prefix: ``gaps:hw:<venue>:<city>``. Records the
#: latest climate day this ledger has already conclusively classified as
#: EXPECTED (whether or not a gap was found), so a warm reconcile only has to
#: scan forward from there rather than re-walking all history every poll.
_HW_KEY_PREFIX: Final[str] = f"{GAP_KEY_PREFIX}hw:"

#: **ASSUMPTION, not a cited fact** -- see the module docstring. Conservative
#: estimate of how long ``api.weather.gov`` keeps a product fetchable. NOT the
#: same concept as ``registry.sites.SettlementDeadline.no_data_fallback_days``,
#: which is a venue settlement rule this module never reads.
RETENTION_DAYS_ASSUMPTION: Final[int] = 7

#: Severity ladder thresholds, in days of retention remaining. INFO is
#: anything strictly above :data:`WARN_AT_OR_BELOW_DAYS_REMAINING`.
WARN_AT_OR_BELOW_DAYS_REMAINING: Final[int] = 5
CRITICAL_AT_OR_BELOW_DAYS_REMAINING: Final[int] = 2


class GapState(str, Enum):
    """The lifecycle of one ``(venue, city, climate_day)`` gap entry.

    Deliberately three-way. ``RESOLVED`` is used rather than "closed" or
    "deleted" because the key is never removed -- see the module docstring.
    ``ACKNOWLEDGED_LOST`` is terminal and reachable only via :func:`acknowledge`,
    never written by :func:`reconcile`.
    """

    OPEN = "open"
    RESOLVED = "resolved"
    ACKNOWLEDGED_LOST = "acknowledged_lost"


class GapSeverity(str, Enum):
    """Conservative severity ladder against days-until-retention-loss.

    INFO at > :data:`WARN_AT_OR_BELOW_DAYS_REMAINING` days remaining, WARN at
    or below that, CRITICAL at or below :data:`CRITICAL_AT_OR_BELOW_DAYS_REMAINING`
    -- and an already aged-out day (negative days remaining) is CRITICAL too,
    which falls out of the same comparison without a special case.
    """

    INFO = "info"
    WARN = "warn"
    CRITICAL = "critical"


class StateStore(Protocol):
    """The minimal persistence seam this module needs.

    Structurally identical to ``gate.StateStore`` and ``product_index.StateStore``
    on purpose -- declared here rather than imported so this module carries no
    dependency on either, matching their own dependency-free stance.
    """

    def get(self, key: str) -> bytes | None: ...

    def set(self, key: str, value: bytes) -> None: ...


class ObservedRecord(Protocol):
    """The minimal shape this module needs from a catalog record.

    Structurally matches ``breezy.domain.nws_climate_day.NwsClimateDay`` --
    real instances satisfy this Protocol without this module ever importing
    that class (which would pull in ``nautilus_trader`` and trigger its
    module-scope ``register_arrow`` side effect, exactly the isolation
    ``product_index.py`` already argues for and this module matches).
    """

    station: str
    climate_day: dt.date
    ts_init: int
    is_final: bool
    revision_seq: int
    correction_flag: bool
    is_superseded: bool


class TamperedGapLedgerError(Exception):
    """Raised when the durable ledger cannot be trusted to answer a query.

    Two distinct causes, both routed here rather than through a silent
    "no gap" or "never seen" reading -- mirroring
    ``product_index.CorruptProductIndexEntryError``'s posture that corruption
    is itself the integrity signal, never a free pass:

    1. An entry key is listed in the durable manifest but its value is
       missing from the store.
    2. An entry key (or the manifest itself) holds bytes that fail to decode
       as this module's own JSON shape.
    """

    def __init__(self, *, gap_id: str, detail: str) -> None:
        super().__init__(f"tampered gap ledger entry {gap_id}: {detail}")
        self.gap_id = gap_id
        self.detail = detail


@dataclass(frozen=True, slots=True)
class GapEntry:
    """One durable ``(venue, city, climate_day)`` gap record.

    Never deleted, never truly "closed" -- only ever moved forward through
    :class:`GapState`. ``observed_revision_seq`` is ``0`` while ``OPEN``
    (nothing has ever been observed for this day); once ``RESOLVED`` it is
    the latest revision seen as of the reconcile that resolved -- or later
    revised -- it.
    """

    venue: str
    city: str
    climate_day: dt.date
    state: GapState
    first_detected_ns: int
    last_reconciled_ns: int
    resolved_at_ns: int | None
    observed_revision_seq: int
    observed_is_final: bool
    correction_flag: bool
    is_superseded: bool
    acknowledged_by: str | None
    acknowledged_at_ns: int | None
    acknowledged_reason: str | None


@dataclass(frozen=True, slots=True)
class RevisionEvent:
    """A post-resolution change observed for an already-``RESOLVED`` day.

    Fires when ``revision_seq`` increases, or when ``correction_flag`` or
    ``is_superseded`` flips from ``False`` to ``True`` -- each independently,
    per ``NwsClimateDay``'s documented semantics
    (``src/breezy/domain/nws_climate_day.py``). Consumed by WI-12's
    ``PostSettlementRevision`` alert; this module only detects and reports it.
    """

    venue: str
    city: str
    climate_day: dt.date
    previous_revision_seq: int
    new_revision_seq: int
    correction_flag: bool
    is_superseded: bool


@dataclass(frozen=True, slots=True)
class ReconcileResult:
    """The outcome of one :func:`reconcile` call, for logging/testing.

    ``opened`` / ``resolved`` / ``revisions`` are reported in ascending
    ``climate_day`` order for opened/resolved and processing order for
    revisions. Idempotent by construction: a second call with the same
    ``now_ns`` and the same ``records`` reports the empty transitions
    (nothing NEW opens, resolves or revises) even though unchanged ``OPEN``
    and ``ACKNOWLEDGED_LOST`` entries are still durably rewritten with an
    identical ``last_reconciled_ns`` -- see :func:`reconcile`.
    """

    venue: str
    city: str
    opened: tuple[dt.date, ...]
    resolved: tuple[dt.date, ...]
    revisions: tuple[RevisionEvent, ...]
    high_water_mark: dt.date | None


@dataclass(frozen=True, slots=True)
class _ObservedSummary:
    is_final: bool
    revision_seq: int
    correction_flag: bool
    is_superseded: bool


# ---------------------------------------------------------------------------
# Pure clock helpers -- the ONE copy of each derivation.
# ---------------------------------------------------------------------------


def local_standard_date(now_ns: int, std_utc_offset_hours: float) -> dt.date:
    """The calendar date `now_ns` falls on in fixed local-standard time.

    Never DST-aware -- see the module docstring's two-clocks note. Matches
    ``NwsIngestActor._most_recent_completed_climate_day``'s own conversion
    byte-for-byte (floor division on whole seconds, not float division), so
    this and that function agree on every instant, including ones exactly on
    a second boundary.
    """
    local = dt.datetime.fromtimestamp(
        now_ns // _NS_PER_SECOND,
        tz=standard_time_zone(std_utc_offset_hours),
    )
    return local.date()


def most_recent_completed_climate_day(now_ns: int, std_utc_offset_hours: float) -> dt.date:
    """The last climate day that has definitely ended, as of `now_ns`.

    The single extracted copy of
    ``NwsIngestActor._most_recent_completed_climate_day`` -- that method
    should call this rather than re-implementing the arithmetic, so there is
    exactly one copy in the repo (not built here; a separate wiring item).
    """
    return local_standard_date(now_ns, std_utc_offset_hours) - dt.timedelta(days=1)


def review_extension_end_ns(
    climate_day: dt.date,
    *,
    settlement_delay_time_local: str,
    settlement_delay_timezone: str,
) -> int:
    """The instant `climate_day` becomes EXPECTED: the venue's 08:00->11:00
    ET METAR-review extension deadline, on the day AFTER `climate_day`.

    Same construction as ``NwsIngestActor._settlement_deadline_ns``, but
    reading ``settlement_delay_time_local`` / ``settlement_delay_timezone``
    (11:00 ET) rather than ``settlement_time_local`` / ``settlement_timezone``
    (08:00 ET) -- a DIFFERENT pair of registry fields for a DIFFERENT
    question. Conflating the two would create false-positive gaps for every
    final that legitimately arrives inside the 08:00-11:00 review window.
    """
    hour_text, minute_text = settlement_delay_time_local.split(":")
    when = dt.datetime.combine(
        climate_day + dt.timedelta(days=1),
        dt.time(int(hour_text), int(minute_text)),
        tzinfo=ZoneInfo(settlement_delay_timezone),
    )
    return int(when.timestamp()) * _NS_PER_SECOND


def days_remaining_until_retention_loss(
    climate_day: dt.date,
    today: dt.date,
    *,
    retention_days: int = RETENTION_DAYS_ASSUMPTION,
) -> int:
    """Days left before `climate_day` is assumed to age out of NWS retention,
    counting from `today` (a caller-supplied local-standard calendar date --
    see :func:`local_standard_date`). Negative once aged out.
    """
    age_in_days = (today - climate_day).days
    return retention_days - age_in_days


def severity_for(
    climate_day: dt.date,
    today: dt.date,
    *,
    retention_days: int = RETENTION_DAYS_ASSUMPTION,
) -> GapSeverity:
    """The severity ladder, parameterised on an explicit `today` so it is
    testable without a clock or registry -- see the module docstring for the
    thresholds and the retention-figure caveat.
    """
    remaining = days_remaining_until_retention_loss(
        climate_day, today, retention_days=retention_days
    )
    if remaining <= CRITICAL_AT_OR_BELOW_DAYS_REMAINING:
        return GapSeverity.CRITICAL
    if remaining <= WARN_AT_OR_BELOW_DAYS_REMAINING:
        return GapSeverity.WARN
    return GapSeverity.INFO


# ---------------------------------------------------------------------------
# Key / id builders
# ---------------------------------------------------------------------------


def _entry_key(venue: str, city: str, climate_day: dt.date) -> str:
    return f"{GAP_KEY_PREFIX}{venue}:{city}:{climate_day.isoformat()}"


def _hw_key(venue: str, city: str) -> str:
    return f"{_HW_KEY_PREFIX}{venue}:{city}"


def _manifest_id(venue: str, city: str, climate_day: dt.date) -> str:
    return f"{venue}|{city}|{climate_day.isoformat()}"


def _site_prefix(venue: str, city: str) -> str:
    return f"{venue}|{city}|"


# ---------------------------------------------------------------------------
# Codec
# ---------------------------------------------------------------------------


def _entry_to_bytes(entry: GapEntry) -> bytes:
    payload = {
        "venue": entry.venue,
        "city": entry.city,
        "climate_day": entry.climate_day.isoformat(),
        "state": entry.state.value,
        "first_detected_ns": entry.first_detected_ns,
        "last_reconciled_ns": entry.last_reconciled_ns,
        "resolved_at_ns": entry.resolved_at_ns,
        "observed_revision_seq": entry.observed_revision_seq,
        "observed_is_final": entry.observed_is_final,
        "correction_flag": entry.correction_flag,
        "is_superseded": entry.is_superseded,
        "acknowledged_by": entry.acknowledged_by,
        "acknowledged_at_ns": entry.acknowledged_at_ns,
        "acknowledged_reason": entry.acknowledged_reason,
    }
    # `sort_keys=True` makes byte-identical output a property of the encoder,
    # not an accident of dict-construction order -- the idempotence RED test
    # depends on this holding for its own sake, not by coincidence.
    return json.dumps(payload, sort_keys=True).encode("utf-8")


def _require_str(payload: dict[str, Any], field: str) -> str:
    value = payload[field]
    if not isinstance(value, str):
        raise TypeError(f"`{field}` must be a `str`, was {type(value).__name__}")
    return value


def _require_optional_str(payload: dict[str, Any], field: str) -> str | None:
    value = payload[field]
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"`{field}` must be a `str` or `None`, was {type(value).__name__}")
    return value


def _require_int(payload: dict[str, Any], field: str) -> int:
    value = payload[field]
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"`{field}` must be an `int`, was {type(value).__name__}")
    return value


def _require_optional_int(payload: dict[str, Any], field: str) -> int | None:
    value = payload[field]
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"`{field}` must be an `int` or `None`, was {type(value).__name__}")
    return value


def _require_bool(payload: dict[str, Any], field: str) -> bool:
    value = payload[field]
    if not isinstance(value, bool):
        raise TypeError(f"`{field}` must be a `bool`, was {type(value).__name__}")
    return value


def _entry_from_bytes(raw: bytes) -> GapEntry:
    payload: Any = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"persisted gap entry must be a JSON object, was {type(payload).__name__}")

    state_raw = _require_str(payload, "state")
    try:
        state = GapState(state_raw)
    except ValueError as exc:
        raise ValueError(f"`state` is not a known GapState: {state_raw!r}") from exc

    return GapEntry(
        venue=_require_str(payload, "venue"),
        city=_require_str(payload, "city"),
        climate_day=dt.date.fromisoformat(_require_str(payload, "climate_day")),
        state=state,
        first_detected_ns=_require_int(payload, "first_detected_ns"),
        last_reconciled_ns=_require_int(payload, "last_reconciled_ns"),
        resolved_at_ns=_require_optional_int(payload, "resolved_at_ns"),
        observed_revision_seq=_require_int(payload, "observed_revision_seq"),
        observed_is_final=_require_bool(payload, "observed_is_final"),
        correction_flag=_require_bool(payload, "correction_flag"),
        is_superseded=_require_bool(payload, "is_superseded"),
        acknowledged_by=_require_optional_str(payload, "acknowledged_by"),
        acknowledged_at_ns=_require_optional_int(payload, "acknowledged_at_ns"),
        acknowledged_reason=_require_optional_str(payload, "acknowledged_reason"),
    )


# ---------------------------------------------------------------------------
# Manifest + entry storage
# ---------------------------------------------------------------------------


def _load_manifest(store: StateStore) -> list[str]:
    raw = store.get(_MANIFEST_KEY)
    if raw is None:
        return []
    try:
        payload: Any = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, list) or not all(isinstance(item, str) for item in payload):
            raise TypeError("manifest must be a JSON array of strings")
    except (ValueError, TypeError) as exc:
        logger.critical("gap ledger: UNREADABLE manifest -- failing closed. error=%s", exc)
        raise TamperedGapLedgerError(gap_id="__manifest__", detail=str(exc)) from exc
    return list(payload)


def _append_manifest(store: StateStore, gap_id: str) -> None:
    """Idempotent: a no-op (no write at all) if `gap_id` is already listed --
    load-bearing for :func:`reconcile`'s byte-identical-on-repeat guarantee.
    """
    manifest = _load_manifest(store)
    if gap_id in manifest:
        return
    manifest.append(gap_id)
    store.set(_MANIFEST_KEY, json.dumps(sorted(manifest)).encode("utf-8"))


def _write_entry(store: StateStore, entry: GapEntry) -> None:
    """Manifest FIRST, entry SECOND -- the safe ordering. If the process dies
    (or `store.set` raises) between the two writes, the manifest already
    lists the id, so a later read that finds the entry missing correctly
    reads as :class:`TamperedGapLedgerError` rather than as a legitimate
    second first-detection. See ``product_index.py``'s identical reasoning.
    """
    gap_id = _manifest_id(entry.venue, entry.city, entry.climate_day)
    _append_manifest(store, gap_id)
    store.set(_entry_key(entry.venue, entry.city, entry.climate_day), _entry_to_bytes(entry))


def get_entry(store: StateStore, venue: str, city: str, climate_day: dt.date) -> GapEntry | None:
    """Read a single entry, or ``None`` if `climate_day` has no entry at all.

    Does NOT consult the manifest -- callers who need the missing-despite-
    -manifest tampering check should use the manifest-driven paths inside
    :func:`reconcile`, which already perform it. A direct point lookup here
    that raises on manifest disagreement would make every incidental
    "does this day have a gap" query pay for a check it did not ask for.
    Corrupt (present but undecodable) bytes still raise
    :class:`TamperedGapLedgerError` -- unlike missing-vs-manifest, that is
    unconditionally alarming regardless of why the caller is looking.
    """
    raw = store.get(_entry_key(venue, city, climate_day))
    if raw is None:
        return None
    try:
        return _entry_from_bytes(raw)
    except (ValueError, TypeError, KeyError) as exc:
        gap_id = _manifest_id(venue, city, climate_day)
        logger.critical("gap ledger: UNREADABLE entry %s -- failing closed. error=%s", gap_id, exc)
        raise TamperedGapLedgerError(gap_id=gap_id, detail=str(exc)) from exc


def site_entries(store: StateStore, venue: str, city: str) -> tuple[GapEntry, ...]:
    """Every entry ever written for `(venue, city)`, in ascending
    `climate_day` order, driven off the durable manifest -- the only way to
    enumerate entries at all against a store with no scan. Raises
    :class:`TamperedGapLedgerError` if any listed id's entry is missing or
    corrupt, per the module's fail-closed stance.
    """
    manifest = _load_manifest(store)
    prefix = _site_prefix(venue, city)
    days = sorted(
        dt.date.fromisoformat(gap_id[len(prefix) :])
        for gap_id in manifest
        if gap_id.startswith(prefix)
    )
    entries: list[GapEntry] = []
    for day in days:
        entry = get_entry(store, venue, city, day)
        if entry is None:
            gap_id = _manifest_id(venue, city, day)
            logger.critical(
                "gap ledger: entry MISSING for %s despite the durable manifest "
                "recording it -- failing closed.",
                gap_id,
            )
            raise TamperedGapLedgerError(
                gap_id=gap_id,
                detail=f"{gap_id} is listed in the durable manifest but its entry is missing",
            )
        entries.append(entry)
    return tuple(entries)


def _load_high_water_mark(store: StateStore, venue: str, city: str) -> dt.date | None:
    raw = store.get(_hw_key(venue, city))
    if raw is None:
        return None
    try:
        payload: Any = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict) or "expected_through" not in payload:
            raise TypeError("high-water mark must be a JSON object with 'expected_through'")
        return dt.date.fromisoformat(_require_str(payload, "expected_through"))
    except (ValueError, TypeError, KeyError) as exc:
        gap_id = _hw_key(venue, city)
        logger.critical("gap ledger: UNREADABLE high-water mark %s. error=%s", gap_id, exc)
        raise TamperedGapLedgerError(gap_id=gap_id, detail=str(exc)) from exc


def _store_high_water_mark(store: StateStore, venue: str, city: str, day: dt.date) -> None:
    payload = json.dumps({"expected_through": day.isoformat()}).encode("utf-8")
    store.set(_hw_key(venue, city), payload)


# ---------------------------------------------------------------------------
# Observed-set reduction
# ---------------------------------------------------------------------------


def _reduce_observed(
    records: Sequence[ObservedRecord], station: str
) -> dict[dt.date, _ObservedSummary]:
    """Reduce `records` to the latest one per `climate_day`, for `station`
    only, by `(is_final, ts_init, revision_seq)` -- the SAME ranking
    ``NwsClimateDay``'s own module docstring specifies for reader selection
    (``domain/nws_climate_day.py``, "Revisions"), so this ledger's idea of
    "what actually landed" agrees with every other settlement-facing reader.
    """
    best: dict[dt.date, tuple[tuple[bool, int, int], ObservedRecord]] = {}
    for record in records:
        if record.station != station:
            continue
        rank = (record.is_final, record.ts_init, record.revision_seq)
        current = best.get(record.climate_day)
        if current is None or rank > current[0]:
            best[record.climate_day] = (rank, record)
    return {
        day: _ObservedSummary(
            is_final=record.is_final,
            revision_seq=record.revision_seq,
            correction_flag=record.correction_flag,
            is_superseded=record.is_superseded,
        )
        for day, (_, record) in best.items()
    }


def _is_revision(entry: GapEntry, obs: _ObservedSummary) -> bool:
    return (
        obs.revision_seq > entry.observed_revision_seq
        or (obs.correction_flag and not entry.correction_flag)
        or (obs.is_superseded and not entry.is_superseded)
    )


# ---------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------


def reconcile(
    *,
    store: StateStore,
    now_ns: int,
    venue: str,
    city: str,
    station: str,
    std_utc_offset_hours: float,
    settlement_delay_time_local: str,
    settlement_delay_timezone: str,
    records: Sequence[ObservedRecord] = (),
    retention_days: int = RETENTION_DAYS_ASSUMPTION,
) -> ReconcileResult:
    """Append-and-resolve, idempotent gap reconciliation for one site.

    Two runs with the same `now_ns` and the same `records` write byte-
    identical store contents: an already-``OPEN`` day with no new
    observation is rewritten with the SAME ``last_reconciled_ns`` (`now_ns`
    again), a ``RESOLVED`` day with no revision is left untouched (no write
    at all), and no new candidate day exists to open a second time because
    the high-water mark already covers it. Nothing here calls the wall
    clock or does I/O beyond `store` -- `records` must already be fetched
    (and, in production, fetched off the event loop) by the caller; this
    function is pure given its arguments.

    Two-pass shape, both required every call:

    1. **Revisit** every entry already in the durable manifest for this
       `(venue, city)` -- ``OPEN`` entries either resolve (an observation
       now exists) or get ``last_reconciled_ns`` bumped; ``RESOLVED``
       entries are checked for a revision event; ``ACKNOWLEDGED_LOST``
       entries never transition but still get ``last_reconciled_ns`` bumped
       so they stay visibly alive. This pass is NOT bounded by the
       high-water mark -- an ``OPEN`` day from months ago must keep being
       re-checked for resolution every single reconcile, forever, or a late
       backfill would never clear it.
    2. **Scan forward** from the high-water mark (or, on a cold store, from
       `retention_days` days before the newest completed day) through
       :func:`most_recent_completed_climate_day`, opening a new entry for
       any day that has become EXPECTED (past
       :func:`review_extension_end_ns`) and has no observation. Stops at the
       first not-yet-expected day, since every later day is even less
       expected, and does NOT advance the high-water mark past it -- that
       day is re-evaluated on the next call once its extension has elapsed.
       A day that IS observed the very first time it is checked never gets
       an entry at all: only a day that is expected AND unobserved with no
       prior entry opens one.

    Raises
    ------
    TamperedGapLedgerError
        If the manifest or any entry it lists cannot be read back cleanly --
        see :func:`site_entries` and the module docstring. Deliberately left
        to propagate to the caller rather than swallowed here: containment
        (log and continue the poll) is the ATTACHMENT point's job, not this
        pure function's -- see the module docstring's "Attachment point".
    """
    observed = _reduce_observed(records, station)
    most_recent_completed = most_recent_completed_climate_day(now_ns, std_utc_offset_hours)

    opened: list[dt.date] = []
    resolved: list[dt.date] = []
    revisions: list[RevisionEvent] = []

    # -- pass 1: revisit every known entry for this site.
    for entry in site_entries(store, venue, city):
        obs = observed.get(entry.climate_day)
        if entry.state is GapState.OPEN:
            if obs is not None:
                _write_entry(
                    store,
                    replace(
                        entry,
                        state=GapState.RESOLVED,
                        resolved_at_ns=now_ns,
                        last_reconciled_ns=now_ns,
                        observed_revision_seq=obs.revision_seq,
                        observed_is_final=obs.is_final,
                        correction_flag=obs.correction_flag,
                        is_superseded=obs.is_superseded,
                    ),
                )
                resolved.append(entry.climate_day)
            else:
                _write_entry(store, replace(entry, last_reconciled_ns=now_ns))
        elif entry.state is GapState.RESOLVED:
            if obs is not None and _is_revision(entry, obs):
                revisions.append(
                    RevisionEvent(
                        venue=venue,
                        city=city,
                        climate_day=entry.climate_day,
                        previous_revision_seq=entry.observed_revision_seq,
                        new_revision_seq=obs.revision_seq,
                        correction_flag=obs.correction_flag,
                        is_superseded=obs.is_superseded,
                    )
                )
                _write_entry(
                    store,
                    replace(
                        entry,
                        last_reconciled_ns=now_ns,
                        observed_revision_seq=obs.revision_seq,
                        observed_is_final=obs.is_final,
                        correction_flag=obs.correction_flag,
                        is_superseded=obs.is_superseded,
                    ),
                )
            # else: no change since the last reconcile -- no write.
        else:  # GapState.ACKNOWLEDGED_LOST -- never transitions back.
            _write_entry(store, replace(entry, last_reconciled_ns=now_ns))

    # -- pass 2: scan forward for newly-expected days.
    hw = _load_high_water_mark(store, venue, city)
    start_day = (
        most_recent_completed - dt.timedelta(days=retention_days - 1)
        if hw is None
        else hw + dt.timedelta(days=1)
    )

    new_hw = hw
    day = start_day
    while day <= most_recent_completed:
        extension_end_ns = review_extension_end_ns(
            day,
            settlement_delay_time_local=settlement_delay_time_local,
            settlement_delay_timezone=settlement_delay_timezone,
        )
        if now_ns < extension_end_ns:
            break
        if day not in observed:
            new_entry = GapEntry(
                venue=venue,
                city=city,
                climate_day=day,
                state=GapState.OPEN,
                first_detected_ns=now_ns,
                last_reconciled_ns=now_ns,
                resolved_at_ns=None,
                observed_revision_seq=0,
                observed_is_final=False,
                correction_flag=False,
                is_superseded=False,
                acknowledged_by=None,
                acknowledged_at_ns=None,
                acknowledged_reason=None,
            )
            _write_entry(store, new_entry)
            opened.append(day)
        # else: observed on first check -- never a gap, no entry created.
        new_hw = day
        day += dt.timedelta(days=1)

    if new_hw is not None and new_hw != hw:
        _store_high_water_mark(store, venue, city, new_hw)

    return ReconcileResult(
        venue=venue,
        city=city,
        opened=tuple(opened),
        resolved=tuple(resolved),
        revisions=tuple(revisions),
        high_water_mark=new_hw,
    )


def acknowledge(
    *,
    store: StateStore,
    venue: str,
    city: str,
    climate_day: dt.date,
    now_ns: int,
    acknowledged_by: str,
    reason: str,
) -> GapEntry:
    """Operator-only terminal transition: `climate_day` is accepted as
    permanently lost. Refuses unless the entry is currently ``OPEN`` --
    an already-``RESOLVED`` day was never lost, and an already-
    ``ACKNOWLEDGED_LOST`` day cannot be re-acknowledged (the transition is
    write-once, matching :func:`reconcile`'s "never transitions back").

    Writes a NEW entry value; the key is never removed, so the day stays in
    the manifest and every future :func:`site_entries` / snapshot read
    forever -- only re-notify is muted, and that muting is a WI-12 alert-sink
    concern, not this ledger's: this function's whole contribution is that
    :func:`reconcile` never flips ``ACKNOWLEDGED_LOST`` back to ``OPEN``.

    Raises
    ------
    ValueError
        If no entry exists for `climate_day`, or its state is not ``OPEN``.
    """
    entry = get_entry(store, venue, city, climate_day)
    if entry is None:
        raise ValueError(
            f"no gap entry exists for venue={venue!r} city={city!r} "
            f"climate_day={climate_day.isoformat()}"
        )
    if entry.state is not GapState.OPEN:
        raise ValueError(
            f"cannot acknowledge venue={venue!r} city={city!r} "
            f"climate_day={climate_day.isoformat()}: state is {entry.state.value}, not OPEN"
        )
    new_entry = replace(
        entry,
        state=GapState.ACKNOWLEDGED_LOST,
        last_reconciled_ns=now_ns,
        acknowledged_by=acknowledged_by,
        acknowledged_at_ns=now_ns,
        acknowledged_reason=reason,
    )
    _write_entry(store, new_entry)
    return new_entry
