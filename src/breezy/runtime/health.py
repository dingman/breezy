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
from pathlib import Path
from typing import Final
from urllib.parse import urlsplit

import httpx

from breezy.registry.health_model import (
    ALLOWED_ALERT_PAYLOAD_KEYS,
    FINAL_OVERDUE,  # noqa: F401 - re-exported kind constant
    GAP_RETENTION_WARNING,  # noqa: F401 - re-exported kind constant
    MAX_ALERT_DETAIL_CHARS,
    POLL_STALE,  # noqa: F401 - re-exported kind constant
    POST_SETTLEMENT_REVISION,  # noqa: F401 - re-exported kind constant
    SCHEMA_VERSION,
    SITE_BLOCKED,  # noqa: F401 - re-exported kind constant
    UA_TRAP_LATCHED,  # noqa: F401 - re-exported kind constant
    AlertCondition,
    AlertConditionKey,
    AlertPayload,
    AlertSink,
    GapSummary,
    HealthSnapshot,
    SiteHealth,
)

__all__ = [
    "ALERT_EGRESS_UNCONFIGURED_EVENT",
    "ALERT_WEBHOOK_URL_ENV_VAR",
    "ALLOWED_ALERT_PAYLOAD_KEYS",
    "DEFAULT_RENOTIFY_AFTER_NS",
    "MAX_ALERT_DETAIL_CHARS",
    "SCHEMA_VERSION",
    "SNAPSHOT_DIR_MODE",
    "SNAPSHOT_FILE_MODE",
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
    "alert_egress_configured",
    "emit_alert",
    "log_alert_egress_status",
    "resolve_alert_sink",
    "write_snapshot_atomic",
]

logger = logging.getLogger(__name__)

#: Re-notify cadence while a condition remains continuously active: 24h in
#: nanoseconds, matching the design's "slow re-notify" default.
DEFAULT_RENOTIFY_AFTER_NS: Final[int] = 24 * 60 * 60 * 1_000_000_000

#: `WebhookAlertSink` is constructed by `resolve_alert_sink` ONLY when this
#: variable is set. Unset (the default) is not a placeholder empty string
#: baked into source -- it is the literal absence of any endpoint.
ALERT_WEBHOOK_URL_ENV_VAR: Final[str] = "BREEZY_ALERT_WEBHOOK_URL"

#: [WP-B0] Event name on the one-line boot WARNING emitted by
#: :func:`log_alert_egress_status` when no webhook is configured. Greppable
#: in the node/supervisor log and in `journalctl`, so "did anyone ever have
#: a delivery channel?" is answerable from the log alone.
ALERT_EGRESS_UNCONFIGURED_EVENT: Final[str] = "BREEZY_ALERT_EGRESS_UNCONFIGURED"

#: Mode of the health snapshot FILE: owner read/write only. Gap and gate
#: contents disclose exactly when and how collection is degraded.
SNAPSHOT_FILE_MODE: Final[int] = 0o600

#: Mode of the DIRECTORY holding those files: owner only. Write access to
#: the directory is enough to forge a snapshot by unlink-and-replace even
#: without read access to the 0600 files themselves.
SNAPSHOT_DIR_MODE: Final[int] = 0o700


# --------------------------------------------------------------------------
# Snapshot data model
# --------------------------------------------------------------------------


def write_snapshot_atomic(path: Path, snapshot: HealthSnapshot) -> None:
    """Atomically write `snapshot` as JSON to `path`.

    `tempfile.mkstemp(dir=<path's own parent directory>)` so `os.replace`
    is a same-filesystem, atomic rename; `0o600` is applied ONCE, to the
    temp file's open DESCRIPTOR via `fchmod`, before any bytes are written.
    The default `tempfile`/`os.open` mode is umask-dependent and typically
    group- or world-readable by default umasks; gap and gate contents
    reveal exactly when and how collection is degraded, which is
    reconnaissance value for timing an attack against the UA-trap or
    freshness watchdog, so this does not rely on the process umask being
    configured correctly.

    **No by-name `chmod` on either the temp path or the final path.**
    `os.chmod(path, ...)` FOLLOWS symlinks and resolves by name, so an
    attacker with write access to the directory who wins the window after
    `os.replace` could plant a symlink at `path` aimed at any file this
    process owns and have it restricted to 0600 -- a local denial of
    service. `os.replace` itself does NOT follow a destination symlink, so
    the rename was never the hazard; the trailing chmods were, and they
    were redundant besides: a mode set with `fchmod` belongs to the inode
    and survives the rename unchanged. See
    `test_write_snapshot_atomic_never_chmods_the_snapshot_by_name`, which
    pins both properties (no by-name chmod, final mode still 0600).

    **Directory mode 0700, enforced on every write.** `mkdir` without an
    explicit mode uses `0o777 & ~umask` -- commonly 0o775, i.e. group
    writable -- and `exist_ok=True` silently accepts whatever mode an
    existing directory already carries. A group-writable snapshot
    directory lets a local user unlink or rename over `health-*.json` and
    FORGE a plausible, freshly-timestamped snapshot claiming an OPEN gate
    with no open gaps: they cannot read the 0600 contents, but they can
    mask a dead collector across a settlement window, which defeats the
    documented monitor contract just as effectively. The mode is therefore
    both requested at creation and re-asserted afterwards so a
    pre-existing permissive directory is corrected rather than inherited.
    (`parents=True` intermediates are left alone -- those are the
    operator's own directories, not the artifact's container.)

    On ANY failure (including a failure inside `os.replace` itself) the
    temp file is unlinked in a `finally`-equivalent handler and the
    original exception re-raised -- a partial snapshot must never be
    observable at `path`, and a stray temp file must never be left behind
    for a future `mkstemp` collision or for local disclosure.
    """
    directory = path.parent
    directory.mkdir(parents=True, exist_ok=True, mode=SNAPSHOT_DIR_MODE)
    # `mkdir(mode=...)` is still masked by the umask, and is a no-op when
    # the directory already exists; this makes the mode exact in both cases.
    os.chmod(directory, SNAPSHOT_DIR_MODE)
    payload = json.dumps(snapshot.to_dict(), sort_keys=True).encode("utf-8")

    fd, tmp_name = tempfile.mkstemp(dir=directory, prefix=".health-snapshot-", suffix=".tmp")
    tmp_path = Path(tmp_name)
    try:
        os.fchmod(fd, SNAPSHOT_FILE_MODE)
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


# --------------------------------------------------------------------------
# Alert payload + sinks
# --------------------------------------------------------------------------


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
            f"{ALERT_WEBHOOK_URL_ENV_VAR} must use https (found scheme={parts.scheme!r})"
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

    def __init__(
        self, url: str, *, timeout_s: float = 5.0, client: httpx.Client | None = None
    ) -> None:
        _validate_webhook_url(url)
        self._url = url
        self._client = client if client is not None else _build_webhook_client(timeout_s)

    def emit(self, payload: AlertPayload) -> None:
        response = self._client.post(self._url, json=payload.to_dict())
        response.raise_for_status()

    def close(self) -> None:
        """Release the `httpx.Client` (and with it the pooled connections
        and the TLS context) this sink owns.

        `composition._close_alert_sink` duck-types `getattr(sink, "close")`
        precisely so a sink that owns a transport can be torn down with the
        rest of the runtime while `LoggingAlertSink`, which owns nothing,
        needs no such method. This is the ONLY sink that owns a transport,
        so without this method that teardown callback was a permanent
        no-op. `httpx.Client.close()` is itself idempotent, so repeated
        teardown (a failed construction unwinding through the same
        `ExitStack`) is safe.
        """
        self._client.close()


class TeeAlertSink:
    """Fan ONE `AlertPayload` out to several sinks, containing each branch
    INDEPENDENTLY.

    Why this exists (a measured 2026-09-20 regression). `resolve_alert_sink`
    used to return EITHER `LoggingAlertSink` OR `WebhookAlertSink`. While
    `BREEZY_ALERT_WEBHOOK_URL` was unset everywhere, every alert reached the
    node log. The afternoon the webhook was configured, the same node went
    from 10 `breezy alert` lines in its first ~51 minutes of uptime to
    ZERO, while 11 alerts were delivered to the webhook. Enabling delivery
    had silently destroyed local diagnosability -- and the node log is the
    authoritative forensic record here (it alone carries the boot-time
    permit line that proves order capability). A channel that costs the
    record is not an upgrade; it is a trade.

    **Composition, not modification.** Neither `LoggingAlertSink` nor
    `WebhookAlertSink` knows this class exists; both are unchanged, and
    either can still be used alone. This type adds fan-out and nothing
    else -- no formatting, no filtering, no retry, no ordering guarantee
    beyond "in the order given".

    **Per-branch containment is the whole point.** Every branch is invoked
    through `emit_alert` -- the same function, with the same deliberate
    `BaseException` catch, that already guarantees a sink can never abort
    the poll cycle it is reporting on. So a webhook that throws, times out
    or hangs does NOT suppress the local log line, a local logger that
    throws does NOT suppress delivery, and nothing propagates out of
    `emit`. A tee that let one branch's failure become two would recreate
    the very loss it was built to prevent. Calling `emit_alert` per branch
    rather than re-implementing a `try/except` here is deliberate: there is
    then exactly ONE definition of "contained" in this module.

    **Never names the endpoint.** The webhook URL is a bearer credential.
    This class logs only an exception TYPE (in `close`), never a message --
    `httpx` and `ssl` embed the full URL in theirs.
    """

    __slots__ = ("_sinks",)

    def __init__(self, *sinks: AlertSink) -> None:
        if not sinks:
            raise ValueError("TeeAlertSink requires at least one branch sink")
        self._sinks: tuple[AlertSink, ...] = tuple(sinks)

    @property
    def sinks(self) -> tuple[AlertSink, ...]:
        """The branches, in invocation order. Read-only by construction."""
        return self._sinks

    def emit(self, payload: AlertPayload) -> None:
        """Hand the SAME payload object to every branch, each contained."""
        for sink in self._sinks:
            emit_alert(sink, payload)

    def close(self) -> None:
        """Close every branch that owns a transport, duck-typed exactly as
        `composition._close_alert_sink` does.

        Never raises, and never stops early: one branch failing to close
        must not leak another branch's socket. Only the exception TYPE is
        logged -- a transport error's message can carry the webhook URL.
        """
        for sink in self._sinks:
            closer = getattr(sink, "close", None)
            if not callable(closer):
                continue
            try:
                closer()
            except BaseException as exc:  # noqa: BLE001 - teardown must never unwind
                # `logger.exception` is deliberately NOT used here: an
                # `httpx`/`ssl` traceback embeds the full webhook URL,
                # which is a bearer credential. Only the TYPE is logged.
                logger.error("alert sink branch close() failed: %s", type(exc).__name__)


def resolve_alert_sink(env: Mapping[str, str] | None = None) -> AlertSink:
    """Return the `AlertSink` this process should use.

    `env` defaults to `os.environ` but is always taken as a parameter,
    matching `runtime/settings.py`'s own convention, so this is testable
    without monkeypatching the real process environment.

    `WebhookAlertSink` -- and the `httpx.Client` (and TLS context) inside
    it -- is constructed ONLY when `BREEZY_ALERT_WEBHOOK_URL` is set to a
    non-empty value. Unset (the default) returns a bare `LoggingAlertSink()`
    and builds no client, opens no socket, and touches no `ssl` module
    state.

    **Configured means BOTH, never either/or.** A configured webhook
    returns a `TeeAlertSink` whose branches are the local log FIRST and the
    webhook second -- delivery off the box must never cost the node log
    line, which is the authoritative forensic record (see
    `TeeAlertSink`'s docstring for the regression this ordering and
    fan-out exist to prevent). The log branch runs first so the local
    record is written before a webhook POST that may block up to its
    timeout; per-branch containment means the ordering is an ordering, not
    a dependency.

    A malformed URL still raises `ValueError` out of this function, loudly
    and at construction: `WebhookAlertSink` is built before the tee, so a
    bad endpoint can never be silently demoted to log-only.
    """
    active_env: Mapping[str, str] = os.environ if env is None else env
    url = active_env.get(ALERT_WEBHOOK_URL_ENV_VAR)
    if not url:
        return LoggingAlertSink()
    return TeeAlertSink(LoggingAlertSink(), WebhookAlertSink(url))


def alert_egress_configured(env: Mapping[str, str] | None = None) -> bool:
    """True iff this process can deliver an alert OFF this machine.

    [WP-B0] Deliberately the EXACT condition :func:`resolve_alert_sink`
    branches on -- a non-empty ``BREEZY_ALERT_WEBHOOK_URL`` -- so there can
    never be two competing definitions of "configured" that drift apart.
    URL *validity* is not re-checked here on purpose: a set-but-malformed
    URL makes :func:`resolve_alert_sink` raise loudly at construction,
    which is a different (and already noisy) failure from the SILENT
    degradation to `LoggingAlertSink` that this predicate exists to make
    queryable by a later health check.
    """
    active_env: Mapping[str, str] = os.environ if env is None else env
    return bool(active_env.get(ALERT_WEBHOOK_URL_ENV_VAR))


def log_alert_egress_status(env: Mapping[str, str] | None = None, *, component: str) -> bool:
    """Make alert reachability VISIBLE at boot. Returns the predicate.

    [WP-B0] Before this existed, an unset webhook degraded in total
    silence: every alert went to a log file nobody reads, and the system
    paid for it twice -- a fee-schedule halt that ran three days unnoticed
    and a live-trading permit lapse that ran eleven hours unnoticed. Both
    were emitted; neither was delivered.

    **Loud, never fatal.** An unconfigured channel logs one WARNING line
    and returns ``False``; it never raises and never blocks startup.
    Refusing to start the bot over telemetry would trade a real trading
    capability for an observability one, which is the wrong trade.

    **Never logs the URL.** An operator webhook URL is a bearer
    credential -- possession of it IS authorisation to post -- so the
    configured branch names only the environment variable, never its value
    and never the endpoint's host.
    """
    if alert_egress_configured(env):
        logger.info(
            "breezy alert egress configured component=%s source=%s",
            component,
            ALERT_WEBHOOK_URL_ENV_VAR,
        )
        return True
    logger.warning(
        "%s component=%s: NO alert egress is configured -- every alert this "
        "process emits will reach the log ONLY and no operator. Set %s to an "
        "https endpoint and verify it with `breezy-check-alerts`.",
        ALERT_EGRESS_UNCONFIGURED_EVENT,
        component,
        ALERT_WEBHOOK_URL_ENV_VAR,
    )
    return False


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
    ERROR and swallowed.

    **Only the exception TYPE is logged, never its message or traceback**
    (AUD-15 amendment, 2026-09-22) -- an `httpx`/`ssl` exception's own
    message routinely embeds the failing request's full URL, and for
    `WebhookAlertSink` that URL is a bearer credential. `logger.exception`
    (which attaches `exc_info`, and therefore the message, via the
    traceback) is deliberately NOT used here, mirroring
    `TeeAlertSink.close()`'s and `check_alerts_cli`'s own withheld-message
    discipline elsewhere in this module.
    """
    try:
        sink.emit(payload)
    except BaseException as exc:  # noqa: BLE001 - deliberate; see docstring.
        logger.error(
            "alert sink failed to emit event=%s site=%s severity=%s exception_type=%s",
            payload.event,
            payload.site,
            payload.severity,
            type(exc).__name__,
        )


# --------------------------------------------------------------------------
# Alert dedupe / transition tracking
# --------------------------------------------------------------------------


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

    That ownership binds the CALLER, and binds it per-thread, not merely
    per-instance: `evaluate` is a read-modify-write over `_active` and
    `_last_emitted_ns`, so it must run on the owning loop's own thread.
    `dispatch` is `evaluate` plus a blocking sink fan-out, so a caller that
    needs the fan-out off its loop must split the two and move only
    `emit_alert` -- never hand the whole `dispatch` to an executor, which
    silently relocates the mutation (see `nws_actor._emit_health`).
    """

    def __init__(self, *, renotify_after_ns: int = DEFAULT_RENOTIFY_AFTER_NS) -> None:
        self._renotify_after_ns = renotify_after_ns
        self._active: dict[AlertConditionKey, bool] = {}
        self._last_emitted_ns: dict[AlertConditionKey, int] = {}

    def evaluate(
        self, conditions: Sequence[AlertCondition], *, now_ns: int
    ) -> tuple[AlertPayload, ...]:
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

    def dispatch(
        self, sink: AlertSink, conditions: Sequence[AlertCondition], *, now_ns: int
    ) -> int:
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
