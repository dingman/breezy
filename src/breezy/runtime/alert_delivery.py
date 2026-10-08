"""Delivery proof, per-attempt records and the durable alert outbox (AUT-6 §3.6, E-1).

The webhook POST goes through ``WebhookAlertSink._client`` directly. ``emit_alert`` and the tee
swallow branch failures (G25), so they are used only for the local log branch. Claim order is
``os.utime`` then ``os.rename`` into ``outbox/claimed/<drainer>/`` then a directory fsync. Entry
age is the filename ``ts_ns``; only claim staleness reads mtime.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import re
import ssl
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal
from weakref import WeakKeyDictionary

import httpx

from breezy.registry.health_model import AlertPayload
from breezy.runtime.health import (
    TeeAlertSink,
    WebhookAlertSink,
    emit_alert,
    resolve_alert_sink,
)

_LOG = logging.getLogger(__name__)

ALERT_CLAIM_STALE_S: Final[int] = 60
ALERT_DELIVERY_TIMEOUT_S: Final[int] = 5
ALERT_OUTBOX_MAX: Final[int] = 128
ALERT_OUTBOX_CRITICAL_RESERVED: Final[int] = 16
REDELIVER_MIN_AGE_S: Final[int] = 60
ALERT_OUTBOX_STALE_S: Final[int] = 300
_ABANDON_AFTER_S: Final[int] = 24 * 60 * 60
_NS: Final[int] = 1_000_000_000
_SCHEMA: Final[str] = "alert_delivery/v1"
_OUTBOX_SCHEMA: Final[str] = "alert_outbox/v1"
_FILE_MODE: Final[int] = 0o600
_DIR_MODE: Final[int] = 0o700
_WRITER_RE: Final[re.Pattern[str]] = re.compile(r"[a-z0-9_]{1,64}\Z")
_EVENT_SAFE: Final[re.Pattern[str]] = re.compile(r"[^A-Za-z0-9_]")
_ATTEMPTS: Final[frozenset[str]] = frozenset({"alert", "retry", "canary", "drain"})

StatusClass = Literal["2xx", "3xx", "4xx", "5xx", "transport", "not_configured", "outbox_overflow"]
AttemptKind = Literal["alert", "retry", "canary", "drain"]

#: Detector CRITICAL events plus the named failure modes. WARNING ``CAPTURE_VENUE_SILENT`` is absent.
PROOF_BEARING_EVENTS: Final[frozenset[str]] = frozenset(
    {
        "CAPTURE_PUBLISH_FAILED",
        "CAPTURE_REFUSED",
        "NBP_CYCLE_MISSED",
        "CAPTURE_EPOCH_UNREADABLE",
        "CAPTURE_STREAM_TYPE_FLAT",
        "CAPTURE_WATCHDOG_EVIDENCE_GAP",
        "CAPTURE_JOIN_GAP",
        "CAPTURE_TAPE_INGEST",
        "CAPTURE_NBP_CENSUS",
        "CAPTURE_AUDIT_ERROR",
        "CAPTURE_REFUSAL_REFS_UNRESOLVED",
        "CAPTURE_SETTLEMENT_MISSING",
        "CAPTURE_AUDIT_STUCK_INCONCLUSIVE",
        "CAPTURE_LIVE_PROOF_STALE",
        "CAPTURE_AUDIT_DEADMAN",
        "CAPTURE_AUDIT_FILE_MISSING",
        "CAPTURE_SETTLEMENT_ERROR",
        "CAPTURE_DRILL_NOT_HEALED",
        "CAPTURE_DRILL_SKIPPED",
        "autonomy_canary_undelivered",
        "bwrap_self_probe_failed",
    }
)

_BINDINGS: WeakKeyDictionary[WebhookAlertSink, str] = WeakKeyDictionary()


@dataclass
class DeliveryCounters:
    """Process-lifetime counts printed by a unit summary line."""

    journal_write_failures: int = 0
    outbox_write_failures: int = 0


COUNTERS = DeliveryCounters()


@dataclass(frozen=True, slots=True)
class DeliveryProof:
    """One attempt. ``delivered`` is true only for an HTTP 2xx."""

    delivered: bool
    status_class: StatusClass
    event: str
    ts_ns: int
    recorded: bool


@dataclass(frozen=True, slots=True)
class DrainSummary:
    """What one ``drain_outbox`` pass did. ``abandoned`` names entries older than 24 h."""

    delivered: int
    attempted: int
    reclaims: int
    failures: int
    abandoned: tuple[str, ...]


class AlertNotDeliveredError(Exception):
    """The journaling webhook branch did not get an HTTP 2xx."""


def default_alerts_root() -> Path:
    """``~/.local/share/breezy/evidence/alerts``. Tests patch this; construction does not mkdir."""
    return Path.home() / ".local" / "share" / "breezy" / "evidence" / "alerts"


def is_proof_bearing(payload: AlertPayload) -> bool:
    """Every CRITICAL, plus any severity whose event is a detector or named failure mode."""
    return payload.severity == "CRITICAL" or payload.event in PROOF_BEARING_EVENTS


def _validate(writer: str, attempt_kind: str) -> None:
    if _WRITER_RE.fullmatch(writer) is None:
        raise ValueError("writer id must match [a-z0-9_]{1,64}")
    if attempt_kind not in _ATTEMPTS:
        raise ValueError("attempt_kind must be alert, retry, canary or drain")


def _day(ts_ns: int) -> str:
    return dt.datetime.fromtimestamp(ts_ns / _NS, tz=dt.UTC).date().isoformat()


def _ts_ns_of(path: Path) -> int | None:
    head = path.name.split("_", 1)[0]
    if not head.isdigit():
        return None
    return int(head)


def _fsync_dir(directory: Path) -> None:
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _mkdir(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    os.chmod(directory, _DIR_MODE)


def _publish(directory: Path, name: str, body: dict[str, object]) -> Path:
    """mkstemp, fsync, ``os.link`` onto ``name``. ``FileExistsError`` if ``name`` is taken."""
    _mkdir(directory)
    fd, tmp_name = tempfile.mkstemp(prefix=".", suffix=".partial", dir=directory)
    tmp = Path(tmp_name)
    try:
        os.fchmod(fd, _FILE_MODE)
        os.write(fd, json.dumps(body, sort_keys=True).encode())
        os.fsync(fd)
    finally:
        os.close(fd)
    dest = directory / name
    try:
        os.link(tmp, dest)
    except FileExistsError:
        os.unlink(tmp)
        raise
    os.unlink(tmp)
    os.chmod(dest, _FILE_MODE)
    _fsync_dir(directory)
    return dest


class AlertOutbox:
    """Write-once entries under ``<root>/outbox``. Claimed copies live in ``claimed/<drainer>/``."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def occupancy(self) -> int:
        """JSON files in ``outbox/`` and ``outbox/claimed/`` (the 128-slot bound)."""
        out = self.root / "outbox"
        if not out.is_dir():
            return 0
        return sum(1 for path in out.rglob("*.json") if path.is_file())

    def refuses(self, severity: str) -> bool:
        """Non-CRITICAL stops at 112; CRITICAL stops at 128."""
        count = self.occupancy()
        if severity == "CRITICAL":
            return count >= ALERT_OUTBOX_MAX
        return count >= ALERT_OUTBOX_MAX - ALERT_OUTBOX_CRITICAL_RESERVED

    def write_entry(self, payload: AlertPayload, *, writer: str, drill: bool, ts_ns: int) -> Path:
        """Write ``<ts>_<event>.json``. A same-name collision retries at ``ts_ns + 1``."""
        _validate(writer, "alert")
        token = _EVENT_SAFE.sub("_", payload.event) or "event"
        stamp = ts_ns
        directory = self.root / "outbox"
        while True:
            body: dict[str, object] = {
                "schema": _OUTBOX_SCHEMA,
                "ts_ns": stamp,
                "severity": payload.severity,
                "event": payload.event,
                "site": payload.site,
                "detail": payload.detail,
                "writer": writer,
                "drill": drill,
            }
            try:
                return _publish(directory, f"{stamp}_{token}.json", body)
            except FileExistsError:
                stamp += 1

    def claim(self, entry: Path, drainer: str) -> Path | None:
        """E-1: utime, then rename into ``claimed/<drainer>/``, then directory fsync.

        ``FileNotFoundError`` (the loser) returns ``None``. Any other ``OSError`` propagates so a
        crash between utime and rename leaves the entry where it was.
        """
        try:
            os.utime(entry)
        except FileNotFoundError:
            return None
        dest_dir = self.root / "outbox" / "claimed" / drainer
        _mkdir(dest_dir)
        dest = dest_dir / entry.name
        try:
            os.rename(entry, dest)
        except FileNotFoundError:
            return None
        _fsync_dir(dest_dir)
        return dest

    def restamp(self, claimed: Path) -> bool:
        """Refresh the claim mtime. ``False`` on ENOENT: another drainer already took it."""
        try:
            os.utime(claimed)
        except FileNotFoundError:
            return False
        return True

    def reclaim_stale(self, drainer: str, now: float | None = None) -> list[Path]:
        """Reclaim other drainers' claims whose mtime age is strictly greater than 60 s."""
        clock = time.time() if now is None else now
        claimed_root = self.root / "outbox" / "claimed"
        if not claimed_root.is_dir():
            return []
        found: list[Path] = []
        for holder in claimed_root.iterdir():
            if not holder.is_dir() or holder.name == drainer:
                continue
            for entry in holder.glob("*.json"):
                if clock - entry.stat().st_mtime <= ALERT_CLAIM_STALE_S:
                    continue
                moved = self.claim(entry, drainer)
                if moved is not None:
                    found.append(moved)
        return found

    def complete(self, claimed: Path) -> None:
        """Remove a claimed entry only after a delivered record was written, then fsync."""
        directory = claimed.parent
        os.unlink(claimed)
        if directory.is_dir():
            _fsync_dir(directory)


class DeliveryRecordWriter:
    """One ``<ts>_<writer>_<d|f>.json`` per attempt. Collision bumps ``ts_ns`` by 1."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def write(
        self,
        *,
        event: str,
        ts_ns: int,
        writer: str,
        delivered: bool,
        status_class: str,
        severity: str,
        attempt_kind: str,
        drill: bool,
        site: str,
        outbox_entry: str,
        outbox_write_failed: bool = False,
    ) -> Path:
        _validate(writer, attempt_kind)
        stamp = ts_ns
        suffix = "d" if delivered else "f"
        while True:
            body: dict[str, object] = {
                "event": event,
                "ts_ns": stamp,
                "delivered": delivered,
                "status_class": status_class,
                "severity": severity,
                "attempt_kind": attempt_kind,
                "drill": drill,
                "schema": _SCHEMA,
                "site": site,
                "outbox_entry": outbox_entry,
            }
            if outbox_write_failed:
                body["outbox_write_failed"] = True
            directory = self.root / _day(stamp)
            try:
                return _publish(directory, f"{stamp}_{writer}_{suffix}.json", body)
            except FileExistsError:
                stamp += 1


def _branches(sink: object) -> tuple[object, ...]:
    if isinstance(sink, TeeAlertSink):
        return sink.sinks
    return (sink,)


def _emit_local(sink: object, payload: AlertPayload) -> None:
    for branch in _branches(sink):
        if isinstance(branch, WebhookAlertSink):
            continue
        emit_alert(branch, payload)


def _status_of(code: int) -> StatusClass:
    bucket = code // 100
    if bucket == 2:
        return "2xx"
    if bucket == 3:
        return "3xx"
    if bucket == 4:
        return "4xx"
    if bucket == 5:
        return "5xx"
    return "transport"


def _post(sink: object, payload: AlertPayload) -> StatusClass:
    """POST the webhook branch directly. 3xx is not delivery. Never log the exception text."""
    for branch in _branches(sink):
        if not isinstance(branch, WebhookAlertSink):
            continue
        try:
            response = branch._client.post(branch._url, json=payload.to_dict())
        except (httpx.HTTPError, ssl.SSLError, OSError) as exc:
            _LOG.error("alert delivery transport failure exception_type=%s", type(exc).__name__)
            return "transport"
        return _status_of(response.status_code)
    return "not_configured"


def _try_record(records: DeliveryRecordWriter, **kwargs: object) -> tuple[bool, int]:
    try:
        path = records.write(**kwargs)  # type: ignore[arg-type]
    except OSError:
        COUNTERS.journal_write_failures += 1
        _LOG.error("alert_delivery_journal_unwritable exception_type=OSError")
        ts = kwargs.get("ts_ns")
        return False, ts if isinstance(ts, int) else 0
    head = path.name.split("_", 1)[0]
    return True, int(head) if head.isdigit() else 0


def deliver_with_proof(
    sink: object,
    payload: AlertPayload,
    *,
    writer: str,
    records: DeliveryRecordWriter,
    attempt_kind: AttemptKind,
    drill: bool = False,
    now_ns: Callable[[], int] = time.time_ns,
    outbox: AlertOutbox | None = None,
    claimed: Path | None = None,
) -> DeliveryProof:
    """Record one attempt. Queue a proof-bearing alert before the POST when ``claimed`` is unset."""
    _validate(writer, attempt_kind)
    ts_ns = now_ns()
    _emit_local(sink, payload)
    outbox_write_failed = False
    claimed_path = claimed
    entry_name = claimed.name if claimed is not None else ""

    if outbox is not None and claimed is None and outbox.refuses(payload.severity):
        recorded, used = _try_record(
            records,
            event=payload.event,
            ts_ns=ts_ns,
            writer=writer,
            delivered=False,
            status_class="outbox_overflow",
            severity=payload.severity,
            attempt_kind=attempt_kind,
            drill=drill,
            site=payload.site,
            outbox_entry="",
        )
        return DeliveryProof(False, "outbox_overflow", payload.event, used or ts_ns, recorded)

    if is_proof_bearing(payload) and claimed is None and outbox is not None:
        try:
            entry = outbox.write_entry(payload, writer=writer, drill=drill, ts_ns=ts_ns)
            claimed_path = outbox.claim(entry, writer)
            entry_name = entry.name
        except OSError:
            COUNTERS.outbox_write_failures += 1
            _LOG.error("alert_outbox_unwritable exception_type=OSError")
            outbox_write_failed = True
            claimed_path = None
            entry_name = ""
        else:
            if claimed_path is None:
                return DeliveryProof(False, "transport", payload.event, ts_ns, False)

    if claimed_path is not None:
        restamped = (
            outbox.restamp(claimed_path) if outbox is not None else _bare_restamp(claimed_path)
        )
        if not restamped:
            return DeliveryProof(False, "transport", payload.event, ts_ns, False)
        entry_name = claimed_path.name

    status = _post(sink, payload)
    delivered = status == "2xx"
    recorded, used = _try_record(
        records,
        event=payload.event,
        ts_ns=ts_ns,
        writer=writer,
        delivered=delivered,
        status_class=status,
        severity=payload.severity,
        attempt_kind=attempt_kind,
        drill=drill,
        site=payload.site,
        outbox_entry=entry_name,
        outbox_write_failed=outbox_write_failed,
    )
    if delivered and recorded and claimed_path is not None and outbox is not None:
        outbox.complete(claimed_path)
    elif delivered and recorded and claimed_path is not None:
        os.unlink(claimed_path)
    return DeliveryProof(delivered, status, payload.event, used or ts_ns, recorded)


def _bare_restamp(claimed: Path) -> bool:
    try:
        os.utime(claimed)
    except FileNotFoundError:
        return False
    return True


def enqueue_alert(
    payload: AlertPayload,
    *,
    writer: str,
    outbox: AlertOutbox,
    records: DeliveryRecordWriter,
    drill: bool = False,
    now_ns: Callable[[], int] = time.time_ns,
) -> bool:
    """Queue one alert and return. No HTTP, and no record when the enqueue itself succeeds."""
    _validate(writer, "alert")
    if outbox.refuses(payload.severity):
        _try_record(
            records,
            event=payload.event,
            ts_ns=now_ns(),
            writer=writer,
            delivered=False,
            status_class="outbox_overflow",
            severity=payload.severity,
            attempt_kind="alert",
            drill=drill,
            site=payload.site,
            outbox_entry="",
        )
        return False
    try:
        outbox.write_entry(payload, writer=writer, drill=drill, ts_ns=now_ns())
    except OSError:
        COUNTERS.outbox_write_failures += 1
        _LOG.error("alert_outbox_unwritable exception_type=OSError")
        _try_record(
            records,
            event=payload.event,
            ts_ns=now_ns(),
            writer=writer,
            delivered=False,
            status_class="transport",
            severity=payload.severity,
            attempt_kind="alert",
            drill=drill,
            site=payload.site,
            outbox_entry="",
            outbox_write_failed=True,
        )
        return False
    return True


def _filename_old(path: Path, now_ns: int, min_age_s: int) -> bool:
    ts_ns = _ts_ns_of(path)
    if ts_ns is None:
        return False
    return now_ns - ts_ns >= min_age_s * _NS


def _is_abandoned(path: Path, now_ns: int) -> bool:
    ts_ns = _ts_ns_of(path)
    if ts_ns is None:
        return False
    return now_ns - ts_ns > _ABANDON_AFTER_S * _NS


def _load_entry(path: Path) -> tuple[AlertPayload, bool] | None:
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(body, dict):
        return None
    try:
        payload = AlertPayload(
            severity=str(body["severity"]),
            event=str(body["event"]),
            site=str(body["site"]),
            detail=str(body["detail"]),
        )
    except (KeyError, TypeError):
        return None
    return payload, bool(body.get("drill", False))


def drain_outbox(
    *,
    drainer: str,
    outbox: AlertOutbox,
    sink: object,
    records: DeliveryRecordWriter,
    min_age_s: int,
    budget_s: int = 40,
    monotonic: Callable[[], float] = time.monotonic,
    now_ns: Callable[[], int] = time.time_ns,
) -> DrainSummary:
    """Claim entries whose filename age is at least ``min_age_s`` and attempt each once.

    Stops taking new claims once ``budget_s`` has elapsed. An entry older than 24 h is still
    attempted and named in ``abandoned``. The record writer id is the drainer, not the originator.
    """
    _validate(drainer, "drain")
    started = monotonic()
    reclaimed = outbox.reclaim_stale(drainer)
    clock = now_ns()
    work: list[tuple[Path, bool]] = []
    own = outbox.root / "outbox" / "claimed" / drainer
    if own.is_dir():
        for path in sorted(own.glob("*.json")):
            if _filename_old(path, clock, min_age_s):
                work.append((path, True))
    for path in sorted((outbox.root / "outbox").glob("*.json")):
        if _filename_old(path, clock, min_age_s):
            work.append((path, False))
    delivered = 0
    failures = 0
    abandoned: list[str] = []
    for path, already in work:
        if monotonic() - started >= budget_s:
            break
        claimed = path if already else outbox.claim(path, drainer)
        if claimed is None:
            continue
        if _is_abandoned(claimed, clock):
            abandoned.append(claimed.name)
        loaded = _load_entry(claimed)
        if loaded is None:
            failures += 1
            continue
        payload, drill = loaded
        proof = deliver_with_proof(
            sink,
            payload,
            writer=drainer,
            records=records,
            attempt_kind="drain",
            drill=drill,
            now_ns=lambda clock=clock: clock,
            outbox=outbox,
            claimed=claimed,
        )
        if proof.delivered:
            delivered += 1
        else:
            failures += 1
    return DrainSummary(delivered, len(work), len(reclaimed), failures, tuple(abandoned))


def run_deadman_drain() -> DrainSummary:
    """The one call AUT-5's dead-man makes: entries whose filename age is at least 300 s."""
    root = default_alerts_root()
    sink = resolve_alert_sink()
    try:
        return drain_outbox(
            drainer="deadman",
            outbox=AlertOutbox(root),
            sink=sink,
            records=DeliveryRecordWriter(root),
            min_age_s=ALERT_OUTBOX_STALE_S,
        )
    finally:
        closer = getattr(sink, "close", None)
        if callable(closer):
            closer()


def JournalingWebhookAlertSink(
    url: str,
    *,
    client: httpx.Client | None = None,
    writer: str = "legacy_runtime",
) -> WebhookAlertSink:
    """A real ``WebhookAlertSink`` whose ``emit`` records, queues and re-raises on non-2xx.

    The binding lives in ``_BINDINGS``, not on the instance. Construction does not touch disk.
    """
    sink = WebhookAlertSink(url, client=client)
    _BINDINGS[sink] = writer

    def _emit(payload: AlertPayload) -> None:
        bound = _BINDINGS.get(sink, writer)
        root = default_alerts_root()
        proof = deliver_with_proof(
            sink,
            payload,
            writer=bound,
            records=DeliveryRecordWriter(root),
            attempt_kind="alert",
            outbox=AlertOutbox(root),
        )
        if not proof.delivered:
            raise AlertNotDeliveredError(proof.status_class)

    setattr(sink, "emit", _emit)
    return sink
