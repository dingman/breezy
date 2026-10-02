"""Pure health data types shared by the NWS ingest runtime (R1.5b).

Stdlib-only data types and constants for the machine-readable health
snapshot and the alert payload/condition vocabulary. They were moved
verbatim out of :mod:`breezy.runtime.health`, which re-exports every name
(class identity preserved), so there is one definition and every existing
import keeps working.

**Why ``registry`` hosts this module.** Two independent constraints:

* *Layer.* ``breezy.ingest`` may not import ``breezy.runtime`` (it sits
  above ``ingest``), but ``ingest`` may import ``registry`` (the layered
  contract places ``registry`` below ``ingest``).
* *Import weight.* ``registry`` loads no Nautilus and no httpx, whereas
  ``ingest``, ``domain`` and ``normalize`` all load Nautilus. Hosting the
  types in ``ingest`` would make ``runtime.health`` load Nautilus and break
  the import-isolation contract (``test_runtime_import_isolation``).

All I/O and egress (sinks, webhook, snapshot writer, ``AlertState``) stays
in :mod:`breezy.runtime.health`. This module must never import any of it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Protocol

__all__ = [
    "ALLOWED_ALERT_PAYLOAD_KEYS",
    "FINAL_OVERDUE",
    "GAP_RETENTION_WARNING",
    "MAX_ALERT_DETAIL_CHARS",
    "POLL_STALE",
    "POST_SETTLEMENT_REVISION",
    "SCHEMA_VERSION",
    "SITE_BLOCKED",
    "UA_TRAP_LATCHED",
    "AlertCondition",
    "AlertConditionKey",
    "AlertPayload",
    "AlertSink",
    "AlertTracker",
    "GapSummary",
    "HealthIO",
    "HealthSnapshot",
    "SiteHealth",
]

#: Bumped whenever `HealthSnapshot.to_dict()`'s shape changes, so an
#: operator or a future reader of the file on disk can tell an old snapshot
#: apart from a new one without inferring it from field presence.
SCHEMA_VERSION: Final[int] = 2

#: `AlertPayload`'s explicit field allowlist. A contract test asserts every
#: `AlertPayload.to_dict()` key is a subset of this constant, so a future
#: contributor cannot silently widen the payload by passing a whole
#: snapshot (or settings) dict into `AlertSink.emit`.
ALLOWED_ALERT_PAYLOAD_KEYS: Final[frozenset[str]] = frozenset(
    {"severity", "event", "site", "detail"}
)

#: `AlertPayload.detail` is truncated to this many characters. The threat
#: this bounds is payload over-collection into a typo'd or compromised
#: webhook endpoint -- a full state dump or a raw upstream HTTP body/header
#: pasted into `detail` would defeat the allowlist in spirit even though
#: every key stayed on the list.
MAX_ALERT_DETAIL_CHARS: Final[int] = 200

#: Vocabulary of alert condition kinds this module's callers are expected
#: to evaluate and pass in as `AlertCondition.key.kind`. Kept as plain
#: strings (not an `Enum`) so the not-yet-built wiring code can construct
#: `AlertConditionKey`s without importing an enum from this module for
#: every call site -- the *dedupe* logic below never branches on which
#: kind a condition is, only on its `(kind, site, extra)` identity.
UA_TRAP_LATCHED: Final[str] = "ua_trap_latched"
SITE_BLOCKED: Final[str] = "site_blocked"
FINAL_OVERDUE: Final[str] = "final_overdue"
GAP_RETENTION_WARNING: Final[str] = "gap_retention_warning"
POLL_STALE: Final[str] = "poll_stale"
POST_SETTLEMENT_REVISION: Final[str] = "post_settlement_revision"


@dataclass(frozen=True, slots=True)
class GapSummary:
    """One `open_gaps` line item for `SiteHealth`.

    **This is the seam WI-10's gap ledger (`src/breezy/ingest/gaps.py`,
    not yet built) plugs into.** `health.py` never imports `gaps.py` and
    never computes gap state itself -- it only knows how to render an
    already-decided gap entry into the snapshot and, optionally, feed it
    into `AlertState` as a `GAP_RETENTION_WARNING` condition. The future
    adapter is expected to be a thin `GapEntry -> GapSummary` mapping
    function living beside the ledger (or in the `nws_actor.py` wiring),
    producing one `GapSummary` per currently-open (or acknowledged-lost)
    entry each poll cycle.

    `state` and `severity` are plain `str`, not this module's own enums,
    deliberately: the ledger owns those vocabularies (`GapState` is
    `OPEN | RESOLVED | ACKNOWLEDGED_LOST` per the design doc), and
    `health.py` must not fork a second, competing definition of either.
    """

    climate_day: str
    state: str
    severity: str
    days_until_retention_loss: int

    def to_dict(self) -> dict[str, object]:
        return {
            "climate_day": self.climate_day,
            "state": self.state,
            "severity": self.severity,
            "days_until_retention_loss": self.days_until_retention_loss,
        }


@dataclass(frozen=True, slots=True)
class SiteHealth:
    """Per-`(venue, city)` section of a `HealthSnapshot`.

    Every field is a plain value the (later) wiring code is expected to
    extract from `SettlementGate.status`/`blocking_causes` and
    `NwsIngestActor.resume_cursor` -- this module never imports either.
    `gate_state`/`gate_reason`/`blocking_causes` are `str`, not `gate.py`'s
    own `GateState`/`GateReason` enums, so this module carries zero
    dependency on `breezy.ingest.gate`.

    **`ledger_unavailable` qualifies `open_gaps`, and is the only field
    here that may not be read independently of another.** `None` means the
    gap ledger was read successfully this cycle, so `open_gaps` is
    authoritative; any string means reconciliation FAILED and `open_gaps`
    is merely what was known before the failure -- almost always the empty
    list, which is byte-identical to a genuinely healthy site. A file-based
    monitor must therefore treat a non-`None` value as "gap state unknown",
    never as "no gaps". It is a plain `str | None` (a bool would force the
    operator back to the log to learn *which* failure, and the string is
    already bounded and scrubbed by the caller) and deliberately NOT a
    `gaps.py` type: this module imports nothing from `breezy.ingest`, which
    is the same boundary `GapSummary` exists to hold. The string is
    free-text, so it is the one field here that is not redaction-safe by
    construction -- the caller is responsible for scrubbing paths, contact
    addresses and upstream product text out of it BEFORE constructing this
    object (see `nws_actor._scrub_failure_detail`).
    """

    venue: str
    city: str
    gate_state: str
    gate_reason: str
    blocking_causes: tuple[str, ...]
    last_successful_poll_ns: int | None
    cursor: str | None
    open_gaps: tuple[GapSummary, ...]
    acknowledged_lost_count: int
    ledger_unavailable: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "venue": self.venue,
            "city": self.city,
            "gate_state": self.gate_state,
            "gate_reason": self.gate_reason,
            "blocking_causes": list(self.blocking_causes),
            "last_successful_poll_ns": self.last_successful_poll_ns,
            "cursor": self.cursor,
            "open_gaps": [gap.to_dict() for gap in self.open_gaps],
            "acknowledged_lost_count": self.acknowledged_lost_count,
            "ledger_unavailable": self.ledger_unavailable,
        }


@dataclass(frozen=True, slots=True)
class HealthSnapshot:
    """The whole machine-readable health artifact, written atomically to
    disk by `write_snapshot_atomic`.

    `snapshot_at_ns` is mandatory (never `None`): a stale file is itself
    the "process is dead" signal an operator (or a monitor reading the
    file) relies on, so the snapshot must always carry the wall-clock
    instant it was produced.

    Deliberately excludes: `user_agent_contact` (or any other
    `BreezyRuntimeSettings` field -- this module never accepts or imports
    that type), and every absolute filesystem path (state-db path, catalog
    base path). There is no field slot for either, by construction --
    see the module docstring's "Redaction" section.
    """

    schema_version: int
    process_started_at_ns: int
    snapshot_at_ns: int
    trader_id: str
    sites: tuple[SiteHealth, ...]
    ua_trap_latched: bool
    alerts_emitted_this_cycle: int

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "process_started_at_ns": self.process_started_at_ns,
            "snapshot_at_ns": self.snapshot_at_ns,
            "trader_id": self.trader_id,
            "sites": [site.to_dict() for site in self.sites],
            "ua_trap_latched": self.ua_trap_latched,
            "alerts_emitted_this_cycle": self.alerts_emitted_this_cycle,
        }


@dataclass(frozen=True, slots=True)
class AlertPayload:
    """The ONLY shape ever handed to an `AlertSink.emit`.

    Exactly four fields, matching `ALLOWED_ALERT_PAYLOAD_KEYS`. `detail` is
    truncated to `MAX_ALERT_DETAIL_CHARS` in `__post_init__` -- never
    raises on an oversize `detail`, since the caller here is always this
    module's own `AlertState`, not untrusted input; truncation is the
    correct containment, not a validation error.

    Forbidden in `detail` (enforced by callers constructing
    `AlertCondition`, not by this class, which cannot tell a full state
    dump from a short sentence): full state/snapshot dumps, absolute
    filesystem paths, raw upstream HTTP bodies or headers, and
    `user_agent_contact`.
    """

    severity: str
    event: str
    site: str
    detail: str

    def __post_init__(self) -> None:
        if len(self.detail) > MAX_ALERT_DETAIL_CHARS:
            object.__setattr__(self, "detail", self.detail[:MAX_ALERT_DETAIL_CHARS])

    def to_dict(self) -> dict[str, str]:
        return {
            "severity": self.severity,
            "event": self.event,
            "site": self.site,
            "detail": self.detail,
        }


class AlertSink(Protocol):
    """Anything that can receive an `AlertPayload`.

    Deliberately synchronous: sinks are always called through
    `emit_alert`, which contains any failure (including from a fully
    synchronous, blocking `httpx.Client.post`) so the caller never awaits
    or unwinds through sink internals.
    """

    def emit(self, payload: AlertPayload) -> None: ...


@dataclass(frozen=True, slots=True)
class AlertConditionKey:
    """Identifies one alertable condition instance for dedupe purposes.

    `site` is `"<venue>/<city>"` or `"global"`, matching `AlertPayload.site`.
    `extra` lets one `kind` track multiple simultaneous instances at the
    same site (e.g. one key per open gap `climate_day` under
    `GAP_RETENTION_WARNING`) without widening `kind` into a combinatorial
    enum. Hashable and orderless: two conditions with the same
    `(kind, site, extra)` are the same tracked condition across cycles,
    full stop.
    """

    kind: str
    site: str
    extra: str = ""


@dataclass(frozen=True, slots=True)
class AlertCondition:
    """One condition, evaluated fresh by the caller every poll cycle, fed
    into `AlertState.evaluate`/`dispatch`.

    `active`: is the condition true right now (this cycle's answer, not a
    remembered one -- `AlertState` owns the memory).
    `renotify_muted`: suppresses the periodic re-notify while `active`
    stays `True` -- the `ACKNOWLEDGED_LOST`-gap case: still alertable on
    the transition into the condition, but not repeatedly afterward, while
    still appearing in the health snapshot via `GapSummary` regardless.
    `severity`/`event`/`detail` are used verbatim to build the
    `AlertPayload` on every cycle this condition actually fires.
    """

    key: AlertConditionKey
    active: bool
    severity: str
    event: str
    detail: str
    renotify_muted: bool = False


class AlertTracker(Protocol):
    """The transition/dedupe half of ``runtime.health.AlertState`` the NWS
    ingest actor depends on: one ``evaluate`` per cycle, on the loop thread."""

    def evaluate(
        self, conditions: Sequence[AlertCondition], *, now_ns: int
    ) -> tuple[AlertPayload, ...]: ...


class HealthIO(Protocol):
    """The health I/O surface injected into the NWS ingest actor.

    Satisfied by the :mod:`breezy.runtime.health` MODULE itself (composition
    assigns the module), so ``ingest`` never imports ``runtime``. Parameter
    names copy ``runtime.health`` exactly. Every call stays late-bound on the
    injected object, so a test can monkeypatch the module attribute.
    """

    def emit_alert(self, sink: AlertSink, payload: AlertPayload) -> None: ...

    def write_snapshot_atomic(self, path: Path, snapshot: HealthSnapshot) -> None: ...

    def resolve_alert_sink(self, env: Mapping[str, str] | None = None) -> AlertSink: ...

    def new_alert_state(self) -> AlertTracker: ...
