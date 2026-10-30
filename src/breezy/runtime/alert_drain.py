"""Outbox draining: claim, attempt once, record (AUT-6 plan r15 §3.6.3, E-1)."""

from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, Literal

from breezy.registry.health_model import AlertPayload
from breezy.runtime.alert_outbox import (
    NS,
    AlertOutbox,
    DeliveryRecordWriter,
    is_regular,
    ts_ns_of,
    validate_ids,
)
from breezy.runtime.alert_proof import deliver_with_proof

REDELIVER_MIN_AGE_S: Final[int] = 60
ALERT_OUTBOX_STALE_S: Final[int] = 300
_ABANDON_AFTER_S: Final[int] = 24 * 60 * 60
_BACKOFF_BASE_S: Final[int] = 300
_BACKOFF_CAP_S: Final[int] = 1800
_BACKOFF_STATUS: Final[frozenset[int]] = frozenset({429, 401, 403, 404, 410})
_STREAK_N: Final[int] = 8
_ENTRY_MAX_BYTES: Final[int] = 64 * 1024
_FIELD_MAX_CHARS: Final[int] = 512
_LOG = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class DrainSummary:
    """What one ``drain_outbox`` pass did. ``abandoned`` names entries older than 24 h.

    The last three fields are keyword-only so ``DrainSummary(0, 0, 0, 0, ())`` stays valid.
    ``skipped_backoff`` counts due entries not claimed while a global backoff is in the future.
    """

    delivered: int
    attempted: int
    reclaims: int
    failures: int
    abandoned: tuple[str, ...]
    skipped_backoff: int = field(default=0, kw_only=True)
    http_4xx: int = field(default=0, kw_only=True)
    probe: int = field(default=0, kw_only=True)


@dataclass(frozen=True, slots=True)
class _Backoff:
    """``probe`` is a due file (one oldest POST). ``hold`` posts nothing. ``open`` is fail-open."""

    kind: Literal["off", "hold", "probe", "open"]
    failures: int = 0


def _is_older(path: Path, now_ns: int, age_s: int, *, strictly: bool) -> bool:
    ts_ns = ts_ns_of(path)
    if ts_ns is None:
        return False
    age_ns = now_ns - ts_ns
    return age_ns > age_s * NS if strictly else age_ns >= age_s * NS


def _read_capped(path: Path) -> bytes:
    """At most ``_ENTRY_MAX_BYTES`` + 1 bytes of a regular file, never through a symlink (C1)."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        return os.read(fd, _ENTRY_MAX_BYTES + 1)
    finally:
        os.close(fd)


def _load_entry(path: Path) -> tuple[AlertPayload, bool] | None:
    """The payload of one claimed entry, or ``None`` when it is oversized, unreadable or invalid.

    Fields longer than ``_FIELD_MAX_CHARS`` are truncated, not trusted (C3).
    """
    try:
        raw = _read_capped(path)
        if len(raw) > _ENTRY_MAX_BYTES:
            return None
        body = json.loads(raw.decode("utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(body, dict):
        return None
    try:
        payload = AlertPayload(
            severity=str(body["severity"])[:_FIELD_MAX_CHARS],
            event=str(body["event"])[:_FIELD_MAX_CHARS],
            site=str(body["site"])[:_FIELD_MAX_CHARS],
            detail=str(body["detail"])[:_FIELD_MAX_CHARS],
        )
    except (KeyError, TypeError):
        return None
    return payload, bool(body.get("drill", False))


def _work_list(
    outbox: AlertOutbox, drainer: str, reclaimed: list[Path], clock: int, min_age_s: int
) -> list[tuple[Path, bool]]:
    """``(path, already_claimed)``. Reclaimed claims are always attempted; the rest by age."""
    work: list[tuple[Path, bool]] = [(path, True) for path in reclaimed]
    seen = set(reclaimed)
    own = outbox.root / "outbox" / "claimed" / drainer
    if own.is_dir():
        for path in sorted(own.glob("*.json")):
            if (
                path not in seen
                and is_regular(path)
                and _is_older(path, clock, min_age_s, strictly=False)
            ):
                work.append((path, True))
    for path in sorted((outbox.root / "outbox").glob("*.json")):
        if is_regular(path) and _is_older(path, clock, min_age_s, strictly=False):
            work.append((path, False))
    return work


def _backoff_of(outbox: AlertOutbox, now_ns: int) -> _Backoff:
    """Read the global file. Missing is off. Corrupt, unreadable or too far ahead is open."""
    try:
        loaded = outbox.read_backoff()
    except (OSError, ValueError, UnicodeError, KeyError, TypeError) as exc:
        _LOG.error("alert_backoff_unreadable exception_type=%s", type(exc).__name__)
        return _Backoff("open")
    if loaded is None:
        return _Backoff("off")
    failures, nxt, _last = loaded
    if nxt > now_ns + _BACKOFF_CAP_S * NS:
        _LOG.error("alert_backoff_unreadable exception_type=ValueError")
        return _Backoff("open")
    if now_ns < nxt:
        return _Backoff("hold", failures)
    return _Backoff("probe", failures)


def _delay_s(failures: int) -> int:
    """``min(300 · 2^(failures-1), 1800)``. ``failures`` is the count after this failure."""
    shift = failures - 1
    if shift >= 6:
        return _BACKOFF_CAP_S
    return min(_BACKOFF_BASE_S * (2**shift), _BACKOFF_CAP_S)


def _r4(work: list[tuple[Path, bool]]) -> list[tuple[Path, bool]]:
    """CRITICAL, then never-drained, then oldest filename ``ts_ns``."""

    def key(item: tuple[Path, bool]) -> tuple[int, int, int, str]:
        path, already = item
        loaded = _load_entry(path)
        critical = loaded is not None and loaded[0].severity == "CRITICAL"
        return (0 if critical else 1, 1 if already else 0, ts_ns_of(path) or 0, path.name)

    return sorted(work, key=key)


def _oldest(work: list[tuple[Path, bool]]) -> list[tuple[Path, bool]]:
    return sorted(work, key=lambda item: (ts_ns_of(item[0]) or 0, item[0].name))


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

    A global backoff in the future claims nothing (the dead-man uses this same list). When the
    backoff is due, the oldest entry is the one probe. 2xx, 5xx, transport and payload 4xx clear
    it and the pass continues (a 5xx or transport probe costs one full pass). 3xx and
    not_configured leave it unchanged. Only 429, 401, 403, 404 and 410 set or extend it.
    """
    validate_ids(drainer, "drain")
    started = monotonic()
    clock = now_ns()
    view = _backoff_of(outbox, clock)
    if view.kind == "hold":
        due = _work_list(outbox, drainer, [], clock, min_age_s)
        return DrainSummary(0, 0, 0, 0, (), skipped_backoff=len(due))
    reclaimed = outbox.reclaim_stale(drainer)
    work = _work_list(outbox, drainer, reclaimed, clock, min_age_s)
    delivered = failures = http_4xx = probe = 0
    abandoned: list[str] = []
    classes: list[str] = []
    streak_logged = False
    base_failures = view.failures if view.kind == "probe" else 0
    episode_open = view.kind != "probe"

    def _claim_and_deliver(path: Path, already: bool) -> tuple[str, int | None] | None:
        nonlocal failures
        try:
            claimed = path if already else outbox.claim(path, drainer)
        except OSError:
            _LOG.error("alert_outbox_claim_failed exception_type=OSError")
            failures += 1
            return None
        if claimed is None:
            return None
        if _is_older(claimed, clock, _ABANDON_AFTER_S, strictly=True):
            abandoned.append(claimed.name)
        loaded = _load_entry(claimed)
        if loaded is None:
            _LOG.error("alert_outbox_entry_unreadable exception_type=ValueError")
            outbox.quarantine(claimed)
            failures += 1
            return None
        payload, drill = loaded
        codes: list[int | None] = []
        proof = deliver_with_proof(
            sink,
            payload,
            writer=drainer,
            records=records,
            attempt_kind="drain",
            drill=drill,
            now_ns=lambda: clock,
            outbox=outbox,
            claimed=claimed,
            http_statuses=codes,
        )
        if not codes:
            failures += 1
            return None
        return proof.status_class, codes[-1]

    def _note(status_class: str, http_status: int | None) -> bool:
        """Record one POST. True means a backoff write landed and the pass must stop."""
        nonlocal delivered, failures, http_4xx, streak_logged, base_failures, episode_open
        delivered += int(status_class == "2xx")
        failures += int(status_class != "2xx")
        if status_class == "4xx":
            http_4xx += 1
        classes.append(status_class)
        if (
            not streak_logged
            and len(classes) >= _STREAK_N
            and all(item == "4xx" for item in classes[-_STREAK_N:])
        ):
            _LOG.error("alert_delivery_4xx_streak")
            streak_logged = True
        if http_status in _BACKOFF_STATUS:
            new_failures = base_failures + 1
            wrote = outbox.set_backoff(
                failures=new_failures,
                next_attempt_ns=clock + _delay_s(new_failures) * NS,
                last_status=http_status,
            )
            if wrote and episode_open:
                _LOG.warning(
                    "alert_delivery_backoff status=%s; a 5xx or transport probe clears"
                    " backoff and one pass continues",
                    http_status,
                )
            if wrote:
                base_failures = new_failures
                episode_open = False
                return True
            return False
        if status_class in {"3xx", "not_configured"}:
            return False
        outbox.clear_backoff()
        base_failures = 0
        episode_open = True
        return False

    stop = False
    tried: set[Path] = set()
    if view.kind == "probe":
        for path, already in _oldest(work):
            if monotonic() - started >= budget_s:
                break
            tried.add(path)
            outcome = _claim_and_deliver(path, already)
            if outcome is None:
                continue
            probe = 1
            stop = _note(*outcome)
            break
        rest = [] if stop else _r4([item for item in work if item[0] not in tried])
    else:
        rest = _r4(work)
    if not stop:
        for path, already in rest:
            if monotonic() - started >= budget_s:
                break
            outcome = _claim_and_deliver(path, already)
            if outcome is None:
                continue
            if _note(*outcome):
                break
    return DrainSummary(
        delivered,
        len(work),
        len(reclaimed),
        failures,
        tuple(abandoned),
        skipped_backoff=0,
        http_4xx=http_4xx,
        probe=probe,
    )
