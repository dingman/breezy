"""AUT-1 WP5 stage 3, S2: the live-proof roll-up (design r3 D8; plan r12 sections 3.11.5 and 6).

``build_live_proof`` answers PROVEN or NOT_PROVEN for one family as of one date, from the evidence
the other units wrote. Nothing here writes: the CLI publishes the document.

Qualifying days (plan section 6, the README rule). Each audited day below ``asof`` is judged by its
NEWEST audit file:

* ``PASS`` with at least one fill qualifies. Only a live, non-drill fill is a REAL fill; a canary or
  drill fill qualifies the day and adds nothing to the real-fill count. A ``PASS`` day with no fill,
  a ``NO_INPUT`` day, ``PRE_CAPTURE`` and ``PARTIAL_EPOCH`` never count and never break the run.
* ``FAIL`` and ``ERROR`` break the run, and so does an ``INCONCLUSIVE`` day (or a day with no audit
  file) older than ``BACKFILL_DAYS``: the audit no longer revisits it. A younger one is pending: it
  neither counts nor breaks.

The window is the run of qualifying days after the last break, over the last ``LOOKBACK_DAYS``. It
needs ``QUALIFYING_DAYS`` days and ``MIN_REAL_FILLS`` real fills, and one heal that satisfies the
stall leg (a recorder watchdog heal paired with its stall record, its journal ``UNIT_RESULT`` field
and AUT-6's delivered per-kill marker, or an NBP poll-reset heal) and whose ``CAPTURE_HEALED_<sha>``
alert has a delivery record dated from the heal date to ``HEAL_ALERT_RETRY_DAYS`` after it.

The closure is deliberately lean: the audit file reader, the contract reader and the capture
constants load no Nautilus, which the unit's ``MemoryMax=256M`` needs. No adapter, no HTTP client.
"""

import datetime as dt
import json
import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from breezy.analysis.capture_audit_io import list_names, read_file
from breezy.analysis.capture_audit_model import (
    AUDIT_DIR_REL,
    BACKFILL_DAYS,
    AuditResult,
    DayStatus,
)
from breezy.analysis.capture_audit_wire import audit_from_wire
from breezy.analysis.capture_aut6_contract import delivered_events_by_day, read_notifier_proofs
from breezy.analysis.capture_heal import HEAL_ALERT_RETRY_DAYS  # S3-R53: the one source
from breezy.persistence.autonomy.capture_alerts import heal_alert_event
from breezy.persistence.autonomy.paths import family_component
from breezy.persistence.autonomy.single_read import SingleReadRefused
from breezy.runtime.capture_recorder_hook_cli import STALL_RELATIVE, STALL_SUFFIX
from breezy.runtime.capture_recorder_hook_cli import UNIT as RECORDER_UNIT

__all__ = [
    "HEAL_ALERT_RETRY_DAYS",
    "LIVE_PROOF_SCHEMA",
    "LOOKBACK_DAYS",
    "MIN_REAL_FILLS",
    "QUALIFYING_DAYS",
    "build_live_proof",
    "newest_audit_by_day",
]

_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)
LIVE_PROOF_SCHEMA: Final[str] = "live_proof/v1"
QUALIFYING_DAYS: Final[int] = 7
MIN_REAL_FILLS: Final[int] = 5
#: How far back the roll-up looks for audited days and heal records.
LOOKBACK_DAYS: Final[int] = 30
WATCHDOG_DECIDER: Final[str] = "systemd_watchdog"
NBP_DECIDER: Final[str] = "nbm_quantile_actor"
HEAL_REL: Final[tuple[str, ...]] = ("evidence", "capture", "heal")
_AUDIT_FILE_RE: Final[re.Pattern[str]] = re.compile(r"\A(\d{4}-\d\d-\d\d)(?:_(\d+))?\.json\Z")
_SHA_RE: Final[re.Pattern[str]] = re.compile(r"\A[0-9a-f]{64}\Z")
#: Statuses that never count and never break the run.
_NEUTRAL: Final[frozenset[DayStatus]] = frozenset(
    {DayStatus.NO_INPUT, DayStatus.PRE_CAPTURE, DayStatus.PARTIAL_EPOCH}
)
_BREAKING: Final[frozenset[DayStatus]] = frozenset({DayStatus.FAIL, DayStatus.ERROR})


def newest_audit_by_day(names: Sequence[str]) -> dict[dt.date, str]:
    """The newest audit file name of each day: ``<day>.json`` or ``<day>_<ts_ns>.json``, the
    highest ``ts_ns`` winning. Any other name is ignored."""
    newest: dict[dt.date, tuple[int, str]] = {}
    for name in names:
        match = _AUDIT_FILE_RE.fullmatch(name)
        if match is None:
            continue
        try:
            day = dt.date.fromisoformat(match[1])
        except ValueError:
            continue
        stamp = int(match[2] or 0)
        if day not in newest or stamp >= newest[day][0]:
            newest[day] = (stamp, name)
    return {day: name for day, (_stamp, name) in newest.items()}


def _audit_results(data_root: Path, family_id: str) -> dict[dt.date, AuditResult]:
    """Each day's newest audit file as a result; an unreadable file counts as no audit."""
    rel = (*AUDIT_DIR_REL.split("/"), family_component(family_id))
    found: dict[dt.date, AuditResult] = {}
    for day, name in newest_audit_by_day(list_names(data_root, rel)).items():
        try:
            raw = read_file(data_root, rel, name)
            found[day] = audit_from_wire(json.loads(raw or b""))
        except (SingleReadRefused, OSError, ValueError, KeyError, TypeError) as exc:
            _LOGGER.warning("live proof: unreadable audit file (%s)", type(exc).__name__)
    return found


def _real_fills(result: AuditResult) -> int:
    return sum(1 for f in result.fills if f.source == "live" and not f.drill)


@dataclass(slots=True)
class _Window:
    """The run after the last break: its days, its real fills, and what is pending or missing."""

    days: list[dt.date] = field(default_factory=list)
    real_fills: int = 0
    pending: list[dt.date] = field(default_factory=list)
    breaks: list[dict[str, str]] = field(default_factory=list)
    missing: list[dt.date] = field(default_factory=list)


def _window(results: Mapping[dt.date, AuditResult], asof: dt.date) -> _Window:
    window = _Window()
    earliest = min(results, default=None)
    for back in range(LOOKBACK_DAYS, 0, -1):
        day = asof - dt.timedelta(days=back)
        result = results.get(day)
        stale = back > BACKFILL_DAYS
        if result is None:
            _absent_day(window, day, stale=stale, tracked=earliest is not None and day > earliest)
        elif result.status in _BREAKING or (result.status is DayStatus.INCONCLUSIVE and stale):
            window.breaks.append({"day": day.isoformat(), "status": result.status.value})
            _restart(window)
        elif result.status is DayStatus.INCONCLUSIVE:
            window.pending.append(day)
        elif result.status is DayStatus.PASS and result.fills:
            window.days.append(day)
            window.real_fills += _real_fills(result)
    return window


def _restart(window: _Window) -> None:
    window.days.clear()
    window.real_fills = 0


def _absent_day(window: _Window, day: dt.date, *, stale: bool, tracked: bool) -> None:
    """A day with no readable audit file: pending while the audit may still backfill it, else a gap
    that restarts the run. Days before the first audit file are not gaps to report."""
    if not stale:
        window.pending.append(day)
        return
    _restart(window)
    if tracked:
        window.missing.append(day)


# -- heals -------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Heal:
    date: dt.date
    name: str
    sha: str
    decided_by: str
    invocation_id: str
    unit_result: str
    injected: bool


def _heal_from(date: dt.date, name: str, body: object) -> _Heal | None:
    if not isinstance(body, dict):
        return None
    decider, sha = body.get("decided_by"), body.get("observation_sha256")
    if decider not in {WATCHDOG_DECIDER, NBP_DECIDER}:
        return None
    if not isinstance(sha, str) or _SHA_RE.fullmatch(sha) is None:
        return None
    return _Heal(
        date,
        name,
        sha,
        str(decider),
        str(body.get("invocation_id", "")),
        str(body.get("unit_result", "")),
        body.get("injected") is True,
    )


def _read_heals(data_root: Path, asof: dt.date) -> list[_Heal]:
    heals: list[_Heal] = []
    for back in range(LOOKBACK_DAYS, -1, -1):
        date = asof - dt.timedelta(days=back)
        rel = (*HEAL_REL, date.isoformat())
        for name in list_names(data_root, rel):
            if not name.endswith(".json"):
                continue
            try:
                body = json.loads(read_file(data_root, rel, name) or b"")
            except (SingleReadRefused, OSError, ValueError):
                continue
            heal = _heal_from(date, name, body)
            if heal is not None:
                heals.append(heal)
    return heals


def _has_stall_record(data_root: Path, heal: _Heal) -> bool:
    """A stall record of the heal's invocation carrying the heal's ``observation_sha256``, dated
    the heal's day or the next (the hook files it under the UTC date of detection)."""
    for offset in (0, 1):
        rel = (*STALL_RELATIVE.parts, (heal.date + dt.timedelta(days=offset)).isoformat())
        for name in list_names(data_root, rel):
            if not name.endswith(STALL_SUFFIX):
                continue
            try:
                body = json.loads(read_file(data_root, rel, name) or b"")
            except (SingleReadRefused, OSError, ValueError):
                continue
            if (
                isinstance(body, dict)
                and body.get("invocation_id") == heal.invocation_id
                and body.get("observation_sha256") == heal.sha
            ):
                return True
    return False


def _stall_leg(data_root: Path, heal: _Heal) -> bool:
    """The recorder heal's three-part pairing, or the NBP heal alternative."""
    if heal.decided_by == NBP_DECIDER:
        return True
    if heal.unit_result != "watchdog" or not heal.invocation_id:
        return False
    marker = any(
        p.unit == RECORDER_UNIT and p.invocation_id == heal.invocation_id and p.delivered
        for p in read_notifier_proofs(data_root, heal.date)
    )
    return marker and _has_stall_record(data_root, heal)


def _alert_delivered(ledger: Mapping[dt.date, frozenset[str]], heal: _Heal) -> bool:
    """The heal alert has a delivered record dated the heal day to ``+HEAL_ALERT_RETRY_DAYS``."""
    event = heal_alert_event(heal.sha)
    return any(
        event in ledger.get(heal.date + dt.timedelta(days=offset), frozenset())
        for offset in range(HEAL_ALERT_RETRY_DAYS + 1)
    )


def _ledger(data_root: Path, heals: Sequence[_Heal]) -> Mapping[dt.date, frozenset[str]]:
    """The delivery ledger over every heal's window, read once."""
    if not heals:
        return {}
    first = min(h.date for h in heals)
    last = max(h.date for h in heals) + dt.timedelta(days=HEAL_ALERT_RETRY_DAYS)
    return delivered_events_by_day(data_root, first, last)


# -- the document ------------------------------------------------------------------------------


def _heal_summary(heal: _Heal) -> dict[str, Any]:
    return {
        "record": f"{heal.date.isoformat()}/{heal.name}",
        "date": heal.date.isoformat(),
        "decided_by": heal.decided_by,
        "observation_sha256": heal.sha,
        "injected": heal.injected,
    }


def _heal_verdict(
    data_root: Path, asof: dt.date
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """The newest heal that satisfies the stall leg and has its delivered alert, and every heal
    still lacking a delivered alert (``heal_alert_undelivered``)."""
    qualifying: dict[str, Any] | None = None
    undelivered: list[dict[str, Any]] = []
    heals = _read_heals(data_root, asof)
    ledger = _ledger(data_root, heals)
    for heal in heals:
        if _alert_delivered(ledger, heal):
            if _stall_leg(data_root, heal):
                qualifying = _heal_summary(heal)
            continue
        undelivered.append(
            {
                "heal_record": f"{heal.date.isoformat()}/{heal.name}",
                "event": heal_alert_event(heal.sha),
                "age_days": (asof - heal.date).days,
            }
        )
    return qualifying, undelivered


def build_live_proof(data_root: Path, family_id: str, asof: dt.date) -> Mapping[str, Any]:
    """The roll-up of ``family_id`` as of ``asof``: a plain JSON document (schema ``live_proof/v1``)
    whose ``status`` is ``PROVEN`` only when the window, the real fills and a delivered, paired heal
    all hold."""
    window = _window(_audit_results(data_root, family_id), asof)
    heal, undelivered = _heal_verdict(data_root, asof)
    criteria = {
        "qualifying_days": len(window.days) >= QUALIFYING_DAYS,
        "real_fills": window.real_fills >= MIN_REAL_FILLS,
        "heal": heal is not None,
    }
    return {
        "schema": LIVE_PROOF_SCHEMA,
        "family_id": family_id,
        "asof": asof.isoformat(),
        "status": "PROVEN" if all(criteria.values()) else "NOT_PROVEN",
        "criteria": criteria,
        "qualifying_days": [d.isoformat() for d in window.days],
        "qualifying_day_count": len(window.days),
        "real_fills": window.real_fills,
        "pending_days": [d.isoformat() for d in window.pending],
        "breaking_days": list(window.breaks),
        "missing_days": [d.isoformat() for d in window.missing],
        "heal": heal,
        "heal_alert_undelivered": undelivered,
        "heal_alert_undelivered_count": len(undelivered),
    }
