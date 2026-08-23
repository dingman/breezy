"""Health snapshot + alert sink for the NWS collection runtime (WI-12).

**Null hypothesis, checked before writing this module.** `grep`ing
`src/breezy` for an atomic-write helper turned up none: `SqliteStateStore`
(`runtime/sqlite_store.py`) is a database, not a file writer, and the
catalog's durability story (`persistence/catalog.py`) is flock plus
read-back, never temp-then-rename. Nautilus's `LoggingConfig` gives log
*output*, not a machine-readable state file. Both the atomic writer and the
alert-dedupe state machine below are genuinely net-new. HTTP hardening is
**duplicated, not subclassed**, from `breezy.ingest.http.HttpTransport`
(`_build_ssl_context`, `:464-468`): that class also carries an NWS-only
host allowlist (`:572-575`) a webhook must never inherit.

**Scope boundary.** This module is deliberately self-contained: it imports
nothing from `breezy.ingest` or `breezy.runtime.composition`, and it never
constructs or reads a `BreezyRuntimeSettings`. Wiring it into the actor's
poll cycle (calling this module from `nws_actor.py`, sourcing `SiteHealth`
from `SettlementGate.status`/`blocking_causes`, and sourcing `open_gaps`
from the not-yet-built `breezy.ingest.gaps` ledger) is a separate,
later work item. Every field this module needs from those two systems is
accepted as a plain value (`str`/`int`/`bool`/tuple) or through
:class:`GapSummary`, a narrow local data shape -- see that class's
docstring for the seam a future `gaps.py` adapter fills.

**Redaction.** `HealthSnapshot`/`SiteHealth`/`GapSummary` are `slots=True`
frozen dataclasses with an explicit, hand-written `to_dict()` -- never
`dataclasses.asdict()` -- so serialization is an allowlist by construction:
a field this module was never told about (e.g. a settings object's
`user_agent_contact`, or an absolute state-db/catalog path) cannot reach
the JSON because there is no attribute slot to hold it and no code path
that would write it out even if there were. See
`test_health_snapshot_slots_reject_arbitrary_attribute_injection` for the
attribute-level proof and `test_snapshot_json_excludes_user_agent_contact`
for the document-level one.

**Cold start (BLOCKING design rule).** :class:`AlertState` seeds every
condition key as ALL-CLEAR the instant it is constructed, never from
persisted state. A UA-trap latch, a BLOCKED gate, or an open gap that is
already true at process start must read as a false->true transition on the
very first `evaluate`/`dispatch` call and fire immediately. Computing
transitions against empty prior state would make exactly those
persistent, silent conditions never alert -- the one failure class this
module exists to prevent. There is no persisted alert-dedupe state and
none should ever be added: that would defeat this rule on the next restart.
"""

from __future__ import annotations

import json
import logging
import os
import ssl
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Protocol
from urllib.parse import urlsplit

import httpx

__all__ = [
    "ALERT_WEBHOOK_URL_ENV_VAR",
    "ALLOWED_ALERT_PAYLOAD_KEYS",
    "DEFAULT_RENOTIFY_AFTER_NS",
    "MAX_ALERT_DETAIL_CHARS",
    "SCHEMA_VERSION",
    "AlertCondition",
    "AlertConditionKey",
    "AlertPayload",
    "AlertSink",
    "AlertState",
    "GapSummary",
    "HealthSnapshot",
    "LoggingAlertSink",
    "SiteHealth",
    "WebhookAlertSink",
    "emit_alert",
    "resolve_alert_sink",
    "write_snapshot_atomic",
]

logger = logging.getLogger(__name__)

#: Bumped whenever `HealthSnapshot.to_dict()`'s shape changes, so an
#: operator or a future reader of the file on disk can tell an old snapshot
#: apart from a new one without inferring it from field presence.
SCHEMA_VERSION: Final[int] = 1

#: Re-notify cadence while a condition remains continuously active: 24h in
#: nanoseconds, matching the design's "slow re-notify" default.
DEFAULT_RENOTIFY_AFTER_NS: Final[int] = 24 * 60 * 60 * 1_000_000_000

#: `AlertPayload`'s explicit field allowlist. A contract test asserts every
#: `AlertPayload.to_dict()` key is a subset of this constant, so a future
#: contributor cannot silently widen the payload by passing a whole
#: snapshot (or settings) dict into `AlertSink.emit`.
ALLOWED_ALERT_PAYLOAD_KEYS: Final[frozenset[str]] = frozenset({"severity", "event", "site", "detail"})

#: `AlertPayload.detail` is truncated to this many characters. The threat
#: this bounds is payload over-collection into a typo'd or compromised
#: webhook endpoint -- a full state dump or a raw upstream HTTP body/header
#: pasted into `detail` would defeat the allowlist in spirit even though
#: every key stayed on the list.
MAX_ALERT_DETAIL_CHARS: Final[int] = 200

#: `WebhookAlertSink` is constructed by `resolve_alert_sink` ONLY when this
#: variable is set. Unset (the default) is not a placeholder empty string
#: baked into source -- it is the literal absence of any endpoint.
ALERT_WEBHOOK_URL_ENV_VAR: Final[str] = "BREEZY_ALERT_WEBHOOK_URL"

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


# --------------------------------------------------------------------------
# Snapshot data model
# --------------------------------------------------------------------------


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


def write_snapshot_atomic(path: Path, snapshot: HealthSnapshot) -> None:
    """Atomically write `snapshot` as JSON to `path`.

    `tempfile.mkstemp(dir=<path's own parent directory>)` so `os.replace`
    is a same-filesystem, atomic rename; `0o600` is applied to BOTH the
    temp file (immediately, via `fchmod`, before any bytes are written --
    and again via `chmod` right before the rename, matching the design
    checklist exactly) and the final path. The default `tempfile`/`os.open`
    mode is umask-dependent and typically group- or world-readable by
    default umasks; gap and gate contents reveal exactly when and how
    collection is degraded, which is reconnaissance value for timing an
    attack against the UA-trap or freshness watchdog, so this does not
    rely on the process umask being configured correctly.

    On ANY failure (including a failure inside `os.replace` itself) the
    temp file is unlinked in a `finally`-equivalent handler and the
    original exception re-raised -- a partial snapshot must never be
    observable at `path`, and a stray temp file must never be left behind
    for a future `mkstemp` collision or for local disclosure.
    """
    directory = path.parent
    directory.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(snapshot.to_dict(), sort_keys=True).encode("utf-8")

    fd, tmp_name = tempfile.mkstemp(dir=directory, prefix=".health-snapshot-", suffix=".tmp")
    tmp_path = Path(tmp_name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, path)
        os.chmod(path, 0o600)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


# --------------------------------------------------------------------------
# Alert payload + sinks
# --------------------------------------------------------------------------


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
        return {"severity": self.severity, "event": self.event, "site": self.site, "detail": self.detail}


class AlertSink(Protocol):
    """Anything that can receive an `AlertPayload`.

    Deliberately synchronous: sinks are always called through
    `emit_alert`, which contains any failure (including from a fully
    synchronous, blocking `httpx.Client.post`) so the caller never awaits
    or unwinds through sink internals.
    """

    def emit(self, payload: AlertPayload) -> None: ...


class LoggingAlertSink:
    """The default `AlertSink`. Logs through the `breezy` logger
    namespace, which `runtime/logging_bridge.py` forwards into the
    Nautilus log stream -- so an operator watching Nautilus's own output
    sees every alert with no separate channel to configure.
    """

    _LEVEL_FOR_SEVERITY: Final[Mapping[str, int]] = {
        "CRITICAL": logging.ERROR,
        "WARN": logging.WARNING,
        "INFO": logging.INFO,
    }

    def emit(self, payload: AlertPayload) -> None:
        level = self._LEVEL_FOR_SEVERITY.get(payload.severity, logging.WARNING)
        logger.log(
            level,
            "breezy alert event=%s site=%s severity=%s detail=%s",
            payload.event,
            payload.site,
            payload.severity,
            payload.detail,
        )


def _build_webhook_ssl_context() -> ssl.SSLContext:
    """Duplicate of `breezy.ingest.http._build_ssl_context` (`:464-468`).

    Not imported or subclassed on purpose: `HttpTransport` bundles this
    context with an NWS-only host allowlist (`http.py:572-575`) that a
    webhook -- an arbitrary, operator-supplied HTTPS endpoint -- must never
    inherit. Six lines duplicated beats a shared base class that has to be
    told "ignore the allowlist for this one caller".
    """
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    return context


def _build_webhook_client(timeout_s: float) -> httpx.Client:
    return httpx.Client(
        verify=_build_webhook_ssl_context(),
        follow_redirects=False,
        trust_env=False,
        timeout=timeout_s,
    )


def _validate_webhook_url(url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme != "https":
        raise ValueError(
            f"{ALERT_WEBHOOK_URL_ENV_VAR} must use https (got scheme={parts.scheme!r})"
        )
    if parts.username is not None or parts.password is not None:
        raise ValueError(f"{ALERT_WEBHOOK_URL_ENV_VAR} must not carry userinfo credentials")
    if not parts.hostname:
        raise ValueError(f"{ALERT_WEBHOOK_URL_ENV_VAR} must have a hostname")


class WebhookAlertSink:
    """POSTs `AlertPayload.to_dict()` as JSON to an operator-configured
    HTTPS webhook.

    Constructed only via `resolve_alert_sink` when `BREEZY_ALERT_WEBHOOK_URL`
    is set; never construct this directly from an unset/empty URL -- the
    constructor rejects a non-`https` scheme or a URL carrying userinfo, but
    it does NOT check whether the caller was supposed to skip construction
    entirely, so that check belongs to the call site (`resolve_alert_sink`).

    `emit` never raises past this class in normal operation only insofar as
    `httpx` itself does not raise; the actual "never propagate to the
    poll path" contract is enforced by `emit_alert`, not here -- this
    class raises freely on any transport failure or non-2xx response
    (`raise_for_status`) so `emit_alert`'s catch-all has something real to
    catch in tests.
    """

    def __init__(self, url: str, *, timeout_s: float = 5.0, client: httpx.Client | None = None) -> None:
        _validate_webhook_url(url)
        self._url = url
        self._client = client if client is not None else _build_webhook_client(timeout_s)

    def emit(self, payload: AlertPayload) -> None:
        response = self._client.post(self._url, json=payload.to_dict())
        response.raise_for_status()


def resolve_alert_sink(env: Mapping[str, str] | None = None) -> AlertSink:
    """Return the `AlertSink` this process should use.

    `env` defaults to `os.environ` but is always taken as a parameter,
    matching `runtime/settings.py`'s own convention, so this is testable
    without monkeypatching the real process environment.

    `WebhookAlertSink` -- and the `httpx.Client` (and TLS context) inside
    it -- is constructed ONLY when `BREEZY_ALERT_WEBHOOK_URL` is set to a
    non-empty value. Unset (the default) returns `LoggingAlertSink()` and
    builds no client, opens no socket, and touches no `ssl` module state.
    """
    active_env: Mapping[str, str] = os.environ if env is None else env
    url = active_env.get(ALERT_WEBHOOK_URL_ENV_VAR)
    if not url:
        return LoggingAlertSink()
    return WebhookAlertSink(url)


def emit_alert(sink: AlertSink, payload: AlertPayload) -> None:
    """Call `sink.emit(payload)`, containing ANY failure.

    **The single most important function in this module.** `BaseException`
    is caught deliberately, not `Exception`: `ssl.SSLError` and
    `httpx.TimeoutException`/`httpx.TransportError` are ordinary
    `Exception` subclasses already, so a narrower `except Exception` would
    already cover them -- the point of reaching for `BaseException` is that
    an alert sink must never be able to abort the poll cycle it is
    reporting on, for ANY reason, mirroring `nws_actor.py`'s own stance in
    `_on_poll_done` toward supervision errors. A failure here is logged at
    ERROR (with the stack trace, via `logger.exception`) and swallowed.
    """
    try:
        sink.emit(payload)
    except BaseException:  # deliberate: see docstring -- this is the contract, not sloppiness.
        logger.exception(
            "alert sink failed to emit event=%s site=%s severity=%s",
            payload.event,
            payload.site,
            payload.severity,
        )


# --------------------------------------------------------------------------
# Alert dedupe / transition tracking
# --------------------------------------------------------------------------


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


class AlertState:
    """In-memory transition/dedupe tracker across successive
    `evaluate`/`dispatch` calls -- one instance per running process.

    **Cold start.** Every `AlertConditionKey` is implicitly ALL-CLEAR
    (`False`) until the first `evaluate`/`dispatch` call observes it --
    there is no constructor parameter to seed prior state from a
    persisted source, and none should be added (see the module docstring).
    A condition reported `active=True` on the very first call is therefore
    always a false->true transition and always fires.

    **Deliberately not thread-safe and not persisted.** Exactly one poll
    loop is expected to own an instance, matching every other
    single-writer assumption in this codebase (`SqliteStateStore`,
    `SettlementGate`).
    """

    def __init__(self, *, renotify_after_ns: int = DEFAULT_RENOTIFY_AFTER_NS) -> None:
        self._renotify_after_ns = renotify_after_ns
        self._active: dict[AlertConditionKey, bool] = {}
        self._last_emitted_ns: dict[AlertConditionKey, int] = {}

    def evaluate(self, conditions: Sequence[AlertCondition], *, now_ns: int) -> tuple[AlertPayload, ...]:
        """Return the `AlertPayload`s that should fire THIS cycle, updating
        internal transition/re-notify state for every condition passed in.

        Firing rule per condition: false->true transition always fires;
        true->true re-fires only once `now_ns - last_emitted_ns >=
        renotify_after_ns`, and never re-fires at all when
        `renotify_muted` is `True`; true->false and false->false never
        fire. A condition key not present in `conditions` this cycle is
        left untouched (neither cleared nor advanced) -- callers are
        expected to pass every condition they track on every cycle.
        """
        emitted: list[AlertPayload] = []
        for condition in conditions:
            was_active = self._active.get(condition.key, False)
            self._active[condition.key] = condition.active
            if not condition.active:
                continue
            if not was_active:
                emitted.append(self._payload_for(condition))
                self._last_emitted_ns[condition.key] = now_ns
                continue
            if condition.renotify_muted:
                continue
            last_emitted_ns = self._last_emitted_ns.get(condition.key)
            if last_emitted_ns is None or now_ns - last_emitted_ns >= self._renotify_after_ns:
                emitted.append(self._payload_for(condition))
                self._last_emitted_ns[condition.key] = now_ns
        return tuple(emitted)

    def dispatch(self, sink: AlertSink, conditions: Sequence[AlertCondition], *, now_ns: int) -> int:
        """`evaluate(...)`, then `emit_alert(sink, payload)` for each
        result. Returns the count of payloads this cycle decided to emit
        -- i.e. `HealthSnapshot.alerts_emitted_this_cycle` -- regardless of
        whether the sink actually succeeded, because `emit_alert` never
        reports success/failure back by design (see its docstring): a
        sink's own delivery failure must never change what this method
        returns or retry/duplicate an already-decided emission.
        """
        payloads = self.evaluate(conditions, now_ns=now_ns)
        for payload in payloads:
            emit_alert(sink, payload)
        return len(payloads)

    def _payload_for(self, condition: AlertCondition) -> AlertPayload:
        return AlertPayload(
            severity=condition.severity,
            event=condition.event,
            site=condition.key.site,
            detail=condition.detail,
        )
