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

Retirement: the retirement commit (plan §R8-2) deletes this module and its
wiring by hand. Nothing here auto-retires.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import stat
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any, Final

from nautilus_trader.common.actor import Actor

from breezy.runtime.health import AlertPayload, AlertSink

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
_FUTURE_SKEW: Final[timedelta] = timedelta(minutes=5)
_UNSAFE_MODE_BITS: Final[int] = stat.S_IWGRP | stat.S_IWOTH
_SITE: Final[str] = "fq_loss_stop_probe"
_HALT_REASON: Final[str] = "fq_loss_stop"

REASON_FAIL: Final[str] = "fq_loss_stop_fail"
REASON_UNKNOWN: Final[str] = "fq_loss_stop_unknown"
REASON_STALE: Final[str] = "fq_loss_stop_stale"
REASON_LOSS_UNREADABLE: Final[str] = "fq_loss_stop_unreadable"
REASON_PARITY_UNREADABLE: Final[str] = "fq_parity_unreadable"


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


def _read_guarded(
    path: Path, *, expected_uid: int, now: datetime
) -> tuple[dict[str, Any], datetime]:
    """Owner, mode and mtime checked; returns the parsed object and its mtime."""
    try:
        info = path.stat()
    except FileNotFoundError as exc:
        raise _ArtefactError("missing") from exc
    if not stat.S_ISREG(info.st_mode):
        raise _ArtefactError("not a regular file")
    if info.st_uid != expected_uid:
        raise _ArtefactError("wrong owner")
    if info.st_mode & _UNSAFE_MODE_BITS:
        raise _ArtefactError("group/other writable")
    mtime = datetime.fromtimestamp(info.st_mtime, tz=UTC)
    if mtime > now + _FUTURE_SKEW:
        raise _ArtefactError("mtime in the future")
    body = json.loads(path.read_text())
    if not isinstance(body, dict):
        raise _ArtefactError("not an object")
    return body, mtime


# --------------------------------------------------------------------------
# the loss-stop probe
# --------------------------------------------------------------------------


class LossStopProbe:
    """Reads the artefact, caches one :class:`Verdict`; the veto reads the cache only."""

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
        self._cache: Verdict = Verdict.UNKNOWN
        self._stale_veto = False
        self._last_as_of: datetime | None = None
        self._halt_set = False
        self._fail_alerted = False
        self._unknown_alert_day: object | None = None
        self.counters: Counter[str] = Counter()

    # -- the veto: cache only, no I/O -------------------------------------

    def veto_reason(self) -> str | None:
        if self._cache is Verdict.PASS:
            return None
        if self._cache is Verdict.FAIL:
            return REASON_FAIL
        if self._cache is Verdict.UNKNOWN_STALE:
            return REASON_STALE if self._stale_veto else None
        return REASON_UNKNOWN

    # -- the probe ----------------------------------------------------------

    def probe_once(self) -> Verdict:
        """Evaluate, cache, alert, halt on FAIL. Never raises."""
        try:
            return self._probe()
        except Exception as exc:  # noqa: BLE001 - any failure is UNKNOWN, never PASS
            logger.error("fq loss-stop probe failed: %s", type(exc).__name__)
            return self._fail_unknown(f"probe_exception:{type(exc).__name__}")

    def _fail_unknown(self, detail: str) -> Verdict:
        """UNKNOWN even when alerting itself raises (e.g. a broken clock)."""
        try:
            return self._settle(Verdict.UNKNOWN, detail=detail)
        except Exception:  # noqa: BLE001 - the cache must still read UNKNOWN
            self._cache = Verdict.UNKNOWN
            self._stale_veto = False
            self.counters["unknown"] += 1
            return Verdict.UNKNOWN

    def _probe(self) -> Verdict:
        if self._cache is Verdict.FAIL:
            self.counters["fail_latched"] += 1
            self._ensure_halt()
            return Verdict.FAIL
        now = self._clock()
        try:
            verdict, as_of, mtime = self._evaluate(now)
        except (_ArtefactError, ValueError, KeyError, TypeError, OSError) as exc:
            return self._settle(Verdict.UNKNOWN, detail=f"input_{type(exc).__name__}:{exc}")
        if verdict is Verdict.FAIL:
            return self._settle(Verdict.FAIL, detail="loss stop FAIL")
        age_h = (now - min(as_of, mtime)).total_seconds() / 3600
        if age_h > MAX_AGE_H:
            return self._settle(
                Verdict.UNKNOWN_STALE, detail=f"age_h={age_h:.1f}", stale_veto=age_h > STALE_VETO_H
            )
        return self._settle(Verdict.PASS, detail="")

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
        if as_of > now + _FUTURE_SKEW:
            raise _ArtefactError("as_of in the future")
        if self._last_as_of is not None and as_of < self._last_as_of:
            raise _ArtefactError("as_of went backwards")
        self._last_as_of = as_of
        return Verdict(verdict_text), as_of, mtime

    def _settle(self, verdict: Verdict, *, detail: str, stale_veto: bool = False) -> Verdict:
        self._cache = verdict
        self._stale_veto = stale_veto
        self.counters[verdict.value.lower()] += 1
        if verdict is Verdict.PASS:
            self._unknown_alert_day = None
        elif verdict is Verdict.FAIL:
            self._on_fail()
        elif verdict is Verdict.UNKNOWN_STALE:
            self._alert("FQ_LOSS_STOP_STALE", detail)
        elif self._should_alert_unknown():
            self._alert("FQ_LOSS_STOP_UNKNOWN", detail)
        return verdict

    def _should_alert_unknown(self) -> bool:
        today = self._clock().date()
        if self._alert_every_probe() or self._unknown_alert_day != today:
            self._unknown_alert_day = today
            return True
        return False

    def _on_fail(self) -> None:
        if not self._fail_alerted:
            self._fail_alerted = True
            self._alert("FQ_LOSS_STOP_FAIL", "loss stop FAIL: family halt requested")
        self._ensure_halt()

    def _ensure_halt(self) -> None:
        """Set-only; retried each probe until it takes. The veto holds regardless."""
        if self._halt_set:
            return
        evidence = hashlib.sha256(f"{_HALT_REASON}:{self._last_as_of}".encode()).hexdigest()
        try:
            self._set_family_halted(_HALT_REASON, evidence)
        except Exception as exc:  # noqa: BLE001 - the FAIL veto still applies
            self._alert("FQ_LOSS_STOP_HALT_SET_FAILED", type(exc).__name__)
            return
        self._halt_set = True

    def _alert(self, event: str, detail: str) -> None:
        payload = AlertPayload(severity="CRITICAL", event=event, site=_SITE, detail=detail)
        try:
            self._alert_sink.emit(payload)
        except Exception as exc:  # noqa: BLE001 - a dead sink must never lift the veto
            self.counters["alert_delivery_failed"] += 1
            logger.error("fq loss-stop alert undelivered event=%s: %s", event, type(exc).__name__)


class LossStopProbeActor(Actor):
    """Runs :meth:`LossStopProbe.probe_once` on a timer. The veto never waits on it."""

    _TIMER_NAME: Final = "fq-loss-stop-probe-timer"

    def __init__(
        self, probe: LossStopProbe, *, interval_seconds: int = PROBE_INTERVAL_SECONDS
    ) -> None:
        super().__init__()
        if interval_seconds <= 0:
            raise ValueError("`interval_seconds` must be positive")
        self._probe = probe
        self._interval_seconds = interval_seconds
        self._timer_armed = False

    def on_start(self) -> None:
        self._probe.probe_once()
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

    def _on_timer(self, event: object) -> None:
        self._probe.probe_once()


# --------------------------------------------------------------------------
# parity gate (F5-pinned single look; veto only)
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ParityVerdict:
    subject: str
    family_id: str
    verdict: str  # "PASS" | "FAIL" | "UNDERPOWERED"
    as_of: datetime


class ParityGate:
    """Refuses on an accepted parity FAIL; the refusal latches for the process."""

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

    def veto_reason(self) -> str | None:
        if self._latched:
            return "fq_parity_fail"
        n = self._read_count()
        if n is None:
            return "fq_parity_fill_count_unreadable"
        if n < self._n_par:
            return None
        return self._judge(self._read_verdict())

    def _read_count(self) -> int | None:
        try:
            n = self._fill_count_reader()
        except Exception:  # noqa: BLE001 - unreadable refuses
            return None
        return n if isinstance(n, int) and not isinstance(n, bool) and n >= 0 else None

    def _read_verdict(self) -> ParityVerdict | None:
        try:
            return self._verdict_reader()
        except Exception:  # noqa: BLE001 - unreadable refuses
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


def make_file_parity_gate(
    catalog_root: Path,
    *,
    family_id: str,
    clock: Callable[[], datetime],
    expected_uid: int,
) -> ParityGate:
    """The production :class:`ParityGate` over the guarded ``derived/fq-parity`` files."""
    verdict_path = parity_verdict_path(catalog_root)
    count_path = parity_fill_count_path(catalog_root)

    def _verdict() -> ParityVerdict | None:
        try:
            body, _mtime = _read_guarded(verdict_path, expected_uid=expected_uid, now=clock())
            if body.get("schema") != PARITY_SCHEMA:
                return None
            return ParityVerdict(
                subject=str(body["subject"]),
                family_id=str(body["family_id"]),
                verdict=str(body["verdict"]),
                as_of=_utc(str(body["as_of"])),
            )
        except (_ArtefactError, ValueError, KeyError, TypeError, OSError):
            return None

    def _count() -> int | None:
        try:
            body, _mtime = _read_guarded(count_path, expected_uid=expected_uid, now=clock())
            if body.get("schema") != FILL_COUNT_SCHEMA or body.get("subject") != PARITY_SUBJECT:
                return None
            n = body["n_live_fills"]
            return n if isinstance(n, int) else None
        except (_ArtefactError, ValueError, KeyError, TypeError, OSError):
            return None

    return ParityGate(
        subject=PARITY_SUBJECT,
        family_id=family_id,
        n_par=PARITY_N_PAR,
        stale_parity_h=STALE_PARITY_H,
        clock=clock,
        fill_count_reader=_count,
        verdict_reader=_verdict,
    )


# --------------------------------------------------------------------------
# the composed veto
# --------------------------------------------------------------------------


class FqComposedVeto:
    """Family halt, then loss stop, then parity: an add-only OR.

    Every branch is evaluated on every call; the first non-``None`` reason in
    that order is returned, so wherever the old halt veto refused this refuses
    with the SAME reason. A loss-stop or parity branch that raises refuses.
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
        halt = self._halt_veto()
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
    except Exception:  # noqa: BLE001 - an unreadable branch refuses
        return on_error
