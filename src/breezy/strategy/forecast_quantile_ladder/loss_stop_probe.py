"""F6 FQ-BRIDGE: the interim FQ loss-stop (a TEMPORARY BRIDGE).

Plan: ``docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04/FQ-LOSS-RESPONSE_plan_r3.md``
(row F6, FQ-R3/R17/R31/R32/R36) and ``F1-errata-and-deltas_r3.md`` (§R8-1, E-28).

THE BRIDGE IS A VETO. It can only REFUSE entries; nothing here enables, arms or
sizes anything, and nothing here reads or names an operator-reserved control,
the permit, or live enablement. Every input that is missing, stale, forged or
unreadable refuses (fail closed). The probe never re-opens or clears a halt: its
one write is ``record_policy_halt`` (set-only), injected as ``set_family_halted``.

Three pieces, composed by ``app/trade.py::_compose_forecast_quantile_ladder``:

* :class:`LossStopProbe` reads ``$DATA/derived/fq-loss-stop/latest.json``
  (``loss_stop/v1``) on an actor timer and CACHES a :class:`Verdict`;
  :meth:`LossStopProbe.veto_reason` reads the cache only.
* :class:`ParityGate` is the F5-pinned single-look shadow/live parity veto.
* :class:`FqComposedVeto` is the ONE callable handed to both the strategies and
  the exec client: family halt first, then the loss stop, then parity.

Artefact schema ``loss_stop/v1`` (a JSON object, written by the F6 producer):
``schema``, ``verdict`` (``PASS`` | ``FAIL``), ``as_of`` (ISO-8601 with zone),
``c2_hwm`` (C2 high-water mark), ``truth_sha`` and ``digest``, where
``digest == compute_digest(...)``, i.e. recomputable from the C2 high-water
mark and the truth SHA [FQ-R17]. Owner, mode and mtime are checked and ``as_of``
must be monotonic in memory. Until the producer exists the file is absent and
the probe reads UNKNOWN, which vetoes.

In-memory monotonicity caveat: ``as_of`` monotonicity (and the parity fill
count's monotonicity) is held in process memory only. A producer that rewinds
``as_of`` or the live-fill count is refused until the node restarts; the
restart is the only recovery (note for the future producer owner).

Retirement: the retirement commit (plan §R8-2) deletes this module and its
wiring by hand. Nothing here auto-retires.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import stat
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from nautilus_trader.common.actor import Actor

from breezy.runtime.health import AlertPayload, AlertSink, LoggingAlertSink, TeeAlertSink

if TYPE_CHECKING:
    from nautilus_trader.common.component import TimeEvent

logger = logging.getLogger(__name__)

SCHEMA: Final[str] = "loss_stop/v1"
PARITY_SCHEMA: Final[str] = "parity_gate/v1"
FILL_COUNT_SCHEMA: Final[str] = "live_fill_count/v1"

#: From the frozen F5 design JSON (``F5_prereg_v2_design.json``); pinned equal
#: to it by ``test_stale_parity_h_equals_design_json``.
STALE_PARITY_H: Final[int] = 36
PARITY_N_PAR: Final[int] = 15
#: The one family the parity look is defined for; v1 rows never feed parity.
PARITY_SUBJECT: Final[str] = "pm_us_crh_fq_v2"

#: Loss-stop artefact age bounds, in hours. Past ``MAX_AGE_H`` the verdict is
#: UNKNOWN_STALE (CRITICAL on every probe); past ``STALE_VETO_H`` the entry
#: veto applies, regardless of whether any alert was delivered [FQ-R31].
MAX_AGE_H: Final[int] = 26
STALE_VETO_H: Final[int] = 36

PROBE_INTERVAL_SECONDS: Final[int] = 300
#: Deadman: a cached verdict whose last successful probe settle is older than
#: this many probe intervals is no longer trusted (a dead timer must refuse).
DEADMAN_INTERVALS: Final[int] = 3
_MAX_ARTEFACT_BYTES: Final[int] = 1 << 20
_FUTURE_SKEW: Final[timedelta] = timedelta(minutes=5)
_UNSAFE_MODE_BITS: Final[int] = stat.S_IWGRP | stat.S_IWOTH
_SITE: Final[str] = "fq_loss_stop_probe"
_HALT_REASON: Final[str] = "fq_loss_stop"

REASON_FAIL: Final[str] = "fq_loss_stop_fail"
REASON_UNKNOWN: Final[str] = "fq_loss_stop_unknown"
REASON_PROBE_STALE: Final[str] = "fq_loss_stop_probe_stale"
REASON_HALT_UNREADABLE: Final[str] = "fq_halt_veto_unreadable"
REASON_STALE: Final[str] = "fq_loss_stop_stale"
REASON_LOSS_UNREADABLE: Final[str] = "fq_loss_stop_unreadable"
REASON_PARITY_UNREADABLE: Final[str] = "fq_parity_unreadable"
REASON_PARITY_COUNT_STALE: Final[str] = "fq_parity_count_stale"
REASON_PARITY_COUNT_REGRESSED: Final[str] = "fq_parity_count_regressed"


class Verdict(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"
    UNKNOWN_STALE = "UNKNOWN_STALE"


def compute_digest(*, verdict: str, as_of: str, c2_hwm: str, truth_sha: str) -> str:
    """The artefact digest, recomputable from the C2 high-water mark and truth SHA."""
    return hashlib.sha256(f"{SCHEMA}|{verdict}|{as_of}|{c2_hwm}|{truth_sha}".encode()).hexdigest()


# --------------------------------------------------------------------------
# production paths (siblings of the quote-tape catalog root, like decisions/)
# --------------------------------------------------------------------------


def loss_stop_artefact_path(catalog_root: Path) -> Path:
    return catalog_root.parent / "derived" / "fq-loss-stop" / "latest.json"


def parity_verdict_path(catalog_root: Path) -> Path:
    return catalog_root.parent / "derived" / "fq-parity" / "latest.json"


def parity_fill_count_path(catalog_root: Path) -> Path:
    return catalog_root.parent / "derived" / "fq-parity" / "live_fill_count.json"


# --------------------------------------------------------------------------
# guarded file reads
# --------------------------------------------------------------------------


class _ArtefactError(Exception):
    """An input is missing, forged, mis-owned or malformed: UNKNOWN, never PASS."""


def _utc(text: str) -> datetime:
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        raise _ArtefactError("naive timestamp")
    return parsed.astimezone(UTC)


def _deadman_window() -> timedelta:
    return timedelta(seconds=DEADMAN_INTERVALS * PROBE_INTERVAL_SECONDS)


def _check_parent_dir(path: Path, *, dir_uid: int) -> None:
    """The directory must be ours and not group/other writable (no rename-over)."""
    try:
        info = os.stat(path.parent)
    except FileNotFoundError as exc:
        raise _ArtefactError("missing") from exc
    if not stat.S_ISDIR(info.st_mode):
        raise _ArtefactError("parent is not a directory")
    if info.st_uid != dir_uid:
        raise _ArtefactError("parent directory wrong owner")
    if info.st_mode & _UNSAFE_MODE_BITS:
        raise _ArtefactError("parent directory group/other writable")


def _read_guarded(
    path: Path, *, expected_uid: int, now: datetime, dir_uid: int | None = None
) -> tuple[dict[str, Any], datetime]:
    """Owner, mode and mtime checked ON THE OPENED DESCRIPTOR; returns body and mtime.

    ``O_NOFOLLOW`` refuses a symlink; ``O_NONBLOCK`` keeps a FIFO from hanging
    the open. Every check uses ``fstat`` of the fd that is then read, so the
    path cannot be swapped between check and use.
    """
    _check_parent_dir(path, dir_uid=expected_uid if dir_uid is None else dir_uid)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    except FileNotFoundError as exc:
        raise _ArtefactError("missing") from exc
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise _ArtefactError("not a regular file")
        if info.st_uid != expected_uid:
            raise _ArtefactError("wrong owner")
        if info.st_mode & _UNSAFE_MODE_BITS:
            raise _ArtefactError("group/other writable")
        mtime = datetime.fromtimestamp(info.st_mtime, tz=UTC)
        if mtime > now + _FUTURE_SKEW:
            raise _ArtefactError("mtime in the future")
        raw = os.read(fd, _MAX_ARTEFACT_BYTES + 1)
    finally:
        os.close(fd)
    if len(raw) > _MAX_ARTEFACT_BYTES:
        raise _ArtefactError("artefact too large")
    body = json.loads(raw.decode())
    if not isinstance(body, dict):
        raise _ArtefactError("not an object")
    return body, mtime


# --------------------------------------------------------------------------
# alert delivery
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Delivery:
    """``emitted``: no sink branch raised/refused. ``off_box``: something beyond
    the local log took it. A detector without delivery is not a control."""

    emitted: bool
    off_box: bool


def _emit_branch(sink: AlertSink, payload: AlertPayload) -> bool:
    try:
        # the protocol returns None; a sink that reports failure by returning
        # False is honoured too (hence the Any hop).
        emit: Callable[[AlertPayload], Any] = sink.emit
        result = emit(payload)
    except Exception:
        logger.exception("fq loss-stop alert sink branch failed event=%s", payload.event)
        return False
    return result is not False


def _deliver(sink: AlertSink, payload: AlertPayload) -> _Delivery:
    """Emit and OBSERVE the outcome (``TeeAlertSink.emit`` itself swallows branch errors)."""
    if isinstance(sink, TeeAlertSink):
        outcomes = [(_deliver(branch, payload)) for branch in sink.sinks]
        return _Delivery(
            emitted=any(o.emitted for o in outcomes), off_box=any(o.off_box for o in outcomes)
        )
    ok = _emit_branch(sink, payload)
    return _Delivery(emitted=ok, off_box=ok and not isinstance(sink, LoggingAlertSink))


# --------------------------------------------------------------------------
# the loss-stop probe
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Snapshot:
    """The WHOLE cached state, published by a single assignment.

    ``anchor`` is ``min(as_of, mtime)`` of the last accepted artefact (staleness
    is re-derived from it at veto time); ``settled_at`` is the clock reading at
    the last probe settle (the deadman); ``alert_delivered`` says the CRITICAL
    alert for this probe left the box.
    """

    verdict: Verdict
    anchor: datetime | None = None
    settled_at: datetime | None = None
    alert_delivered: bool = False


class LossStopProbe:
    """Reads the artefact, caches one :class:`_Snapshot`; the veto reads it only."""

    def __init__(
        self,
        *,
        path: Path,
        clock: Callable[[], datetime],
        set_family_halted: Callable[[str, str], None],
        alert_sink: AlertSink,
        alert_every_probe: Callable[[], bool],
        expected_uid: int,
    ) -> None:
        self._path = path
        self._clock = clock
        self._set_family_halted = set_family_halted
        self._alert_sink = alert_sink
        self._alert_every_probe = alert_every_probe
        self._expected_uid = expected_uid
        self._state: _Snapshot = _Snapshot(Verdict.UNKNOWN)
        self._last_as_of: datetime | None = None
        self._halt_set = False
        self._fail_alerted = False
        self._unknown_alert_day: date | None = None
        self.counters: Counter[str] = Counter()

    # -- the veto: one snapshot read, no I/O ---------------------------------

    def veto_reason(self) -> str | None:
        state = self._state  # the ONLY mutable read; everything below is derived from it
        if state.verdict is Verdict.FAIL:
            return REASON_FAIL
        if state.verdict is Verdict.UNKNOWN:
            return REASON_UNKNOWN
        try:
            now = self._clock()
        except Exception:
            logger.exception("fq loss-stop veto could not read the clock")
            return REASON_UNKNOWN
        return _derive_veto(state, now)

    # -- the probe ----------------------------------------------------------

    def probe_once(self) -> Verdict:
        """Evaluate, cache, alert, halt on FAIL. Never raises."""
        try:
            return self._probe()
        except Exception as exc:
            logger.exception("fq loss-stop probe failed: %s", type(exc).__name__)
            return self._fail_unknown(f"probe_exception:{type(exc).__name__}")

    def _fail_unknown(self, detail: str) -> Verdict:
        """UNKNOWN even when settling itself raises; NEVER moves out of FAIL."""
        if self._state.verdict is Verdict.FAIL:
            return Verdict.FAIL
        try:
            return self._settle(Verdict.UNKNOWN, detail=detail, now=None)
        except Exception:
            logger.exception("fq loss-stop settle failed; forcing UNKNOWN")
            self._state = _Snapshot(Verdict.UNKNOWN)
            self.counters["unknown"] += 1
            return Verdict.UNKNOWN

    def _probe(self) -> Verdict:
        if self._state.verdict is Verdict.FAIL:
            self.counters["fail_latched"] += 1
            self._on_fail()
            return Verdict.FAIL
        now = self._clock()
        try:
            verdict, as_of, mtime = self._evaluate(now)
        except (_ArtefactError, ValueError, KeyError, TypeError, OSError) as exc:
            return self._settle(
                Verdict.UNKNOWN, detail=f"input_{type(exc).__name__}:{exc}", now=now
            )
        self._last_as_of = as_of  # only an ACCEPTED artefact advances the monotonic bound
        anchor = min(as_of, mtime)
        if verdict is Verdict.FAIL:
            return self._settle(Verdict.FAIL, detail="loss stop FAIL", now=now, anchor=anchor)
        age_h = (now - anchor).total_seconds() / 3600
        if age_h > MAX_AGE_H:
            return self._settle(
                Verdict.UNKNOWN_STALE, detail=f"age_h={age_h:.1f}", now=now, anchor=anchor
            )
        return self._settle(Verdict.PASS, detail="", now=now, anchor=anchor)

    def _evaluate(self, now: datetime) -> tuple[Verdict, datetime, datetime]:
        body, mtime = _read_guarded(self._path, expected_uid=self._expected_uid, now=now)
        if body.get("schema") != SCHEMA:
            raise _ArtefactError("schema mismatch")
        verdict_text = body["verdict"]
        if verdict_text not in (Verdict.PASS.value, Verdict.FAIL.value):
            raise _ArtefactError("unknown verdict")
        as_of_text, c2_hwm, truth_sha = body["as_of"], body["c2_hwm"], body["truth_sha"]
        expected = compute_digest(
            verdict=verdict_text, as_of=as_of_text, c2_hwm=c2_hwm, truth_sha=truth_sha
        )
        if not hmac.compare_digest(str(body["digest"]), expected):
            raise _ArtefactError("digest mismatch")
        as_of = _utc(as_of_text)
        if as_of > now + _FUTURE_SKEW:  # rejected BEFORE any bound is recorded
            raise _ArtefactError("as_of in the future")
        if self._last_as_of is not None and as_of < self._last_as_of:
            raise _ArtefactError("as_of went backwards")
        return Verdict(verdict_text), as_of, mtime

    def _settle(
        self,
        verdict: Verdict,
        *,
        detail: str,
        now: datetime | None,
        anchor: datetime | None = None,
    ) -> Verdict:
        """Publish ONE snapshot, then run side effects; nothing after can undo it."""
        if self._state.verdict is Verdict.FAIL:
            return Verdict.FAIL  # the latch: no settle ever leaves FAIL
        self._state = _Snapshot(verdict, anchor=anchor, settled_at=now)
        self.counters[verdict.value.lower()] += 1
        try:
            self._side_effects(verdict, detail)
        except Exception:
            logger.exception("fq loss-stop settle side effects failed verdict=%s", verdict.value)
        return verdict

    def _side_effects(self, verdict: Verdict, detail: str) -> None:
        if verdict is Verdict.PASS:
            self._unknown_alert_day = None
        elif verdict is Verdict.FAIL:
            self._on_fail()
        elif verdict is Verdict.UNKNOWN_STALE:
            delivery = self._alert("FQ_LOSS_STOP_STALE", detail)
            # re-publish ONCE, atomically, with the delivery outcome
            self._state = replace(self._state, alert_delivered=delivery.off_box)
        elif self._should_alert_unknown() and self._alert("FQ_LOSS_STOP_UNKNOWN", detail).emitted:
            self._unknown_alert_day = self._clock().date()

    def _should_alert_unknown(self) -> bool:
        return self._alert_every_probe() or self._unknown_alert_day != self._clock().date()

    def _on_fail(self) -> None:
        if not self._fail_alerted:
            delivery = self._alert("FQ_LOSS_STOP_FAIL", "loss stop FAIL: family halt requested")
            self._fail_alerted = delivery.emitted
        self._ensure_halt()

    def _ensure_halt(self) -> None:
        """Set-only; retried each probe until it takes. The veto holds regardless."""
        if self._halt_set:
            return
        try:
            evidence = hashlib.sha256(f"{_HALT_REASON}:{self._last_as_of}".encode()).hexdigest()
            self._set_family_halted(_HALT_REASON, evidence)
        except Exception as exc:
            logger.exception("fq loss-stop family halt could not be set")
            self._alert("FQ_LOSS_STOP_HALT_SET_FAILED", type(exc).__name__)
            return
        self._halt_set = True

    def _alert(self, event: str, detail: str) -> _Delivery:
        try:
            payload = AlertPayload(severity="CRITICAL", event=event, site=_SITE, detail=detail)
            delivery = _deliver(self._alert_sink, payload)
        except Exception:
            logger.exception("fq loss-stop alert could not be built or sent event=%s", event)
            delivery = _Delivery(emitted=False, off_box=False)
        if not delivery.emitted:
            self.counters["alert_delivery_failed"] += 1
            logger.error("fq loss-stop alert undelivered event=%s", event)
        return delivery


def _derive_veto(state: _Snapshot, now: datetime) -> str | None:
    """PASS / UNKNOWN_STALE, re-derived at veto time from the cached anchor and deadman."""
    if state.settled_at is None or state.anchor is None:
        return REASON_UNKNOWN
    if now - state.settled_at > _deadman_window():
        return REASON_PROBE_STALE  # the probe timer is dead: do not trust the cache
    age_h = (now - state.anchor).total_seconds() / 3600
    if age_h > STALE_VETO_H:
        return REASON_STALE
    if age_h > MAX_AGE_H:
        # entries only while THIS probe's CRITICAL alert actually left the box
        if state.verdict is Verdict.UNKNOWN_STALE and state.alert_delivered:
            return None
        return REASON_STALE
    return None


class LossStopProbeActor(Actor):
    """Runs the probe (and any parity refreshers) on a timer. The veto never waits on it."""

    _TIMER_NAME: Final = "fq-loss-stop-probe-timer"

    def __init__(
        self,
        probe: LossStopProbe,
        *,
        interval_seconds: int = PROBE_INTERVAL_SECONDS,
        refreshers: Sequence[Callable[[], object]] = (),
    ) -> None:
        super().__init__()
        if interval_seconds <= 0:
            raise ValueError("`interval_seconds` must be positive")
        self._probe = probe
        self._refreshers = tuple(refreshers)
        self._interval_seconds = interval_seconds
        self._timer_armed = False

    def on_start(self) -> None:
        self._run_once()
        self.clock.set_timer(
            name=self._TIMER_NAME,
            interval=timedelta(seconds=self._interval_seconds),
            callback=self._on_timer,
        )
        self._timer_armed = True

    def on_stop(self) -> None:
        if self._timer_armed:
            self.clock.cancel_timer(self._TIMER_NAME)
            self._timer_armed = False

    def _on_timer(self, event: TimeEvent) -> None:
        self._run_once()

    def _run_once(self) -> None:
        self._probe.probe_once()
        for refresh in self._refreshers:
            try:
                refresh()
            except Exception:
                logger.exception("fq parity refresh failed")


# --------------------------------------------------------------------------
# parity gate (F5-pinned single look; veto only)
# --------------------------------------------------------------------------


class ParityCountStale(Exception):
    """The live-fill-count file is older than ``STALE_PARITY_H``: refuse, never "no veto"."""


@dataclass(frozen=True, slots=True)
class ParityVerdict:
    subject: str
    family_id: str
    verdict: str  # "PASS" | "FAIL" | "UNDERPOWERED"
    as_of: datetime


class ParityGate:
    """Refuses on an accepted parity FAIL; the refusal latches for the process.

    The readers are injected; in production they answer from a
    :class:`ParityFileCache` refreshed on the actor timer, so this veto path
    does no file I/O.
    """

    def __init__(
        self,
        *,
        subject: str,
        family_id: str,
        n_par: int,
        stale_parity_h: int,
        clock: Callable[[], datetime],
        fill_count_reader: Callable[[], int | None],
        verdict_reader: Callable[[], ParityVerdict | None],
    ) -> None:
        self._subject = subject
        self._family_id = family_id
        self._n_par = n_par
        self._stale = timedelta(hours=stale_parity_h)
        self._clock = clock
        self._fill_count_reader = fill_count_reader
        self._verdict_reader = verdict_reader
        self._latched = False
        self._max_count = 0  # in-memory high-water mark; the count never decreases

    def veto_reason(self) -> str | None:
        if self._latched:
            return "fq_parity_fail"
        try:
            n = self._read_count()
        except ParityCountStale:
            return REASON_PARITY_COUNT_STALE
        if n is None:
            return "fq_parity_fill_count_unreadable"
        if n < self._max_count:
            return REASON_PARITY_COUNT_REGRESSED
        self._max_count = n
        # FQ-R spec (F5-pinned single look): below N_PAR live fills the parity
        # look is not yet defined, so there is NO parity veto. Deliberate; do
        # not "fix" this into a refusal without a ruling. It holds ONLY while
        # the count is fresh (<= STALE_PARITY_H) and non-regressed, so a stale
        # or rewound count file can never silently disable the veto.
        if n < self._n_par:
            return None
        return self._judge(self._read_verdict())

    def _read_count(self) -> int | None:
        try:
            n = self._fill_count_reader()
        except ParityCountStale:
            raise
        except Exception:
            logger.exception("fq parity fill-count reader failed")
            return None
        return n if isinstance(n, int) and not isinstance(n, bool) and n >= 0 else None

    def _read_verdict(self) -> ParityVerdict | None:
        try:
            return self._verdict_reader()
        except Exception:
            logger.exception("fq parity verdict reader failed")
            return None

    def _judge(self, v: ParityVerdict | None) -> str | None:
        if v is None:
            return "fq_parity_unavailable"
        if v.subject != self._subject:
            return "fq_parity_wrong_subject"
        if v.family_id != self._family_id:
            return "fq_parity_wrong_family"
        now = self._clock()
        if v.as_of > now + _FUTURE_SKEW:
            return "fq_parity_unavailable"
        if now - v.as_of > self._stale:
            return "fq_parity_stale"
        if v.verdict == "FAIL":
            self._latched = True
            return "fq_parity_fail"
        if v.verdict in ("PASS", "UNDERPOWERED"):
            return None
        return "fq_parity_unavailable"


@dataclass(frozen=True, slots=True)
class _ParitySnapshot:
    """Both parity inputs plus the refresh time, published by ONE assignment."""

    count: int | None = None
    verdict: ParityVerdict | None = None
    settled_at: datetime | None = None
    count_stale: bool = False


class ParityFileCache:
    """Guarded ``derived/fq-parity`` reads, done on the actor timer only.

    ``count()`` / ``verdict()`` answer from one frozen snapshot with the same
    deadman as the loss-stop probe: never refreshed, or last refreshed more
    than ``DEADMAN_INTERVALS`` probe intervals ago, reads as unreadable (the
    gate then refuses).
    """

    def __init__(
        self, catalog_root: Path, *, clock: Callable[[], datetime], expected_uid: int
    ) -> None:
        self._verdict_path = parity_verdict_path(catalog_root)
        self._count_path = parity_fill_count_path(catalog_root)
        self._clock = clock
        self._expected_uid = expected_uid
        self._state: _ParitySnapshot = _ParitySnapshot()

    def refresh(self) -> None:
        """Re-read both files. Never raises; unreadable inputs cache as ``None``."""
        try:
            now = self._clock()
            count, count_stale = self._read_count(now)
            verdict = self._read_verdict(now)
            self._state = _ParitySnapshot(
                count=count, verdict=verdict, settled_at=now, count_stale=count_stale
            )
        except Exception:
            logger.exception("fq parity cache refresh failed")

    def count(self) -> int | None:
        state = self._state
        if not self._live(state):
            return None
        if state.count_stale:
            raise ParityCountStale
        return state.count

    def verdict(self) -> ParityVerdict | None:
        state = self._state
        return state.verdict if self._live(state) else None

    def _live(self, state: _ParitySnapshot) -> bool:
        if state.settled_at is None:
            return False
        try:
            return self._clock() - state.settled_at <= _deadman_window()
        except Exception:
            logger.exception("fq parity cache could not read the clock")
            return False

    def _read_verdict(self, now: datetime) -> ParityVerdict | None:
        try:
            body, _mtime = _read_guarded(
                self._verdict_path, expected_uid=self._expected_uid, now=now
            )
            if body.get("schema") != PARITY_SCHEMA:
                return None
            return ParityVerdict(
                subject=str(body["subject"]),
                family_id=str(body["family_id"]),
                verdict=str(body["verdict"]),
                as_of=_utc(str(body["as_of"])),
            )
        except (_ArtefactError, ValueError, KeyError, TypeError, OSError):
            logger.exception("fq parity verdict file unreadable")
            return None

    def _read_count(self, now: datetime) -> tuple[int | None, bool]:
        """``(count, is_stale)``; stale when the fstat mtime or an ``as_of`` is too old."""
        try:
            body, mtime = _read_guarded(self._count_path, expected_uid=self._expected_uid, now=now)
            if body.get("schema") != FILL_COUNT_SCHEMA or body.get("subject") != PARITY_SUBJECT:
                return None, False
            n = body["n_live_fills"]
            if not isinstance(n, int) or isinstance(n, bool):
                return None, False
            stale = timedelta(hours=STALE_PARITY_H)
            if now - mtime > stale:
                return n, True
            if "as_of" in body:  # optional in the schema; obeyed when present
                as_of = _utc(str(body["as_of"]))
                if as_of > now + _FUTURE_SKEW:
                    return None, False
                if now - as_of > stale:
                    return n, True
            return n, False
        except (_ArtefactError, ValueError, KeyError, TypeError, OSError):
            logger.exception("fq parity fill-count file unreadable")
            return None, False


def make_file_parity_gate(
    *, family_id: str, clock: Callable[[], datetime], cache: ParityFileCache
) -> ParityGate:
    """The production :class:`ParityGate` over a timer-refreshed :class:`ParityFileCache`."""
    return ParityGate(
        subject=PARITY_SUBJECT,
        family_id=family_id,
        n_par=PARITY_N_PAR,
        stale_parity_h=STALE_PARITY_H,
        clock=clock,
        fill_count_reader=cache.count,
        verdict_reader=cache.verdict,
    )


# --------------------------------------------------------------------------
# the composed veto
# --------------------------------------------------------------------------


class FqComposedVeto:
    """Family halt, then loss stop, then parity: an add-only OR.

    Every branch is evaluated on every call; the first non-``None`` reason in
    that order is returned, so wherever the old halt veto refused this refuses
    with the SAME reason. Any branch that raises refuses (a raising halt branch
    refuses with its own reason; the other branches are still evaluated).
    """

    def __init__(
        self,
        *,
        halt_veto: Callable[[], str | None],
        loss_stop_veto: Callable[[], str | None],
        parity_veto: Callable[[], str | None] | None = None,
    ) -> None:
        self._halt_veto = halt_veto
        self._loss_stop_veto = loss_stop_veto
        self._parity_veto = parity_veto

    def __call__(self) -> str | None:
        halt = _guarded(self._halt_veto, REASON_HALT_UNREADABLE)
        loss = _guarded(self._loss_stop_veto, REASON_LOSS_UNREADABLE)
        parity = (
            None
            if self._parity_veto is None
            else _guarded(self._parity_veto, REASON_PARITY_UNREADABLE)
        )
        for reason in (halt, loss, parity):
            if reason is not None:
                return reason
        return None


def _guarded(branch: Callable[[], str | None], on_error: str) -> str | None:
    try:
        return branch()
    except Exception:
        logger.exception("fq composed veto branch raised; refusing with %s", on_error)
        return on_error
