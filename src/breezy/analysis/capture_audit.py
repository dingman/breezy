"""AUT-1 WP5 stage 2b, W3: audit orchestration (plan r12 section 3.11; design S2-R6, S2-R9, S2-R12).

``audit_day`` is a PURE status table over the legs. Precedence (S2-R9), first match wins:

1. a data-integrity ERROR (exec store, node log, journal, epoch, stream, tape, a leg's own ERROR);
2. ``PRE_CAPTURE`` (no epoch, or the day is before its UTC day), which masks everything below;
3. a run-time host-state ERROR (``recorder_watchdog_unarmed``, ``bus_snapshot_*``);
4. ``FAIL`` (any failing leg but R6, which reports and never fails the day, §R9 row 3);
5. ``PARTIAL_EPOCH`` (the epoch's own UTC day);
6. ``INCONCLUSIVE`` (a pending leg);
7. ``NO_INPUT`` (no fills, resolver contexts or Take lines);
8. ``PASS``.

``days_to_audit`` orders a run: yesterday, then INCONCLUSIVE re-audits, then the days never audited
oldest-first (a missing day never ages out of the 8-day window), then ERROR re-audits (S2-R44).
``run_audit`` checks the work deadline on a monotonic clock; a day it does not reach gets NO file
and is listed in ``audit_deferred_days``, which never causes exit 1. A day is written only after
every input of it was read and every leg ran, so a partial day cannot exist. ``write_audit_file``
publishes through ``single_read.write_once`` at 0444.

``CAPTURE_AUDIT_ERROR`` is sent once per (day, cause set) (S2-R44). No outbox in this repo dedupes
(the alert offer is an injected callable; the default one is undeliverable, AUT-6 is not wired), so
the audit does: a day whose newest audit file is already an ERROR with the same cause set sends
nothing again, and a changed cause set sends. A re-audited ERROR day still counts toward the exit
code, so the unit stays loud.

Only a ``health.capture_join`` HEALTH verdict is written (S2-R12); a refused verdict write is INFO.
The three duties moved from the retired watchdog (§3.11.5) each run in their own ``try``. The exit
code is 1 on any ERROR day or failed delivery, decided only after every write.
"""

import datetime as dt
import json
import logging
import os
import re
import sys
from collections.abc import Callable, Mapping, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Final

from breezy.analysis import capture_audit_inputs
from breezy.analysis.capture_audit_fill_legs import audit_fills, leg_f, leg_o, leg_r6, tape_marks
from breezy.analysis.capture_audit_input_types import AuditInputs
from breezy.analysis.capture_audit_inputs import (
    DEADLINE,
    ScanDeadline,
    gather_inputs,
    read_exec_view,
)
from breezy.analysis.capture_audit_model import (
    AUDIT_DIR_REL,
    AUDIT_WORK_BUDGET_S,
    BACKFILL_DAYS,
    LIVE_PROOF_MAX_AGE_H,
    LIVE_PROOF_NAME_RE,
    METRIC_NAMES,
    SETTLEMENT_ALERT_H,
    AuditInputError,
    AuditResult,
    DayStatus,
    FillAudit,
    Leg,
    LegOutcome,
    LegResult,
    MetricValue,
    WatchdogGap,
)
from breezy.analysis.capture_audit_replay import leg_r1, leg_r2, leg_r3
from breezy.analysis.capture_audit_stream_legs import (
    leg_n,
    leg_r4,
    leg_r5,
    leg_r7,
    leg_t,
    leg_w,
    positive_control,
)
from breezy.analysis.capture_audit_wire import audit_from_wire, audit_to_wire
from breezy.analysis.capture_settlement import (
    SCAN_BACK_DAYS,
    AlertOffer,
    SettlementFileCorrupt,
    read_settlement_day,
)
from breezy.persistence.autonomy.capture_alerts import CAPTURE_ALERT_SEVERITIES
from breezy.persistence.autonomy.capture_epoch import read_epoch
from breezy.persistence.autonomy.paths import AutonomyPaths, family_component
from breezy.persistence.autonomy.pins import PRODUCER_SOURCE_SHA256
from breezy.persistence.autonomy.single_read import (
    ReadPolicy,
    SingleReadReason,
    SingleReadRefused,
    ensure_dir,
    open_root,
    read_once_at,
    walk_dirs,
    write_once,
)
from breezy.persistence.autonomy.verdict import (
    ActionClass,
    Assumption,
    Verdict,
    VerdictKind,
    VerdictOutcome,
    write_verdict,
)

__all__ = [
    "AUDIT_FILE_MODE",
    "DETECTOR",
    "HOST_STATE_CAUSES",
    "PRODUCER_ID",
    "audit_day",
    "days_to_audit",
    "error_result",
    "run_audit",
    "write_audit_file",
]

_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)
AUDIT_FILE_MODE: Final[int] = 0o444
DETECTOR: Final[str] = "health.capture_join"
PRODUCER_ID: Final[str] = "aut1_capture_audit"
#: Causes that describe the host at run time, not the data of the day: PRE_CAPTURE masks them.
HOST_STATE_CAUSES: Final[frozenset[str]] = frozenset(
    {"recorder_watchdog_unarmed", "bus_snapshot_missing", "bus_snapshot_stale"}
)
LIVE_PROOF_DIR_REL: Final[tuple[str, ...]] = ("evidence", "capture", "live_proof")
#: How far back the stuck-INCONCLUSIVE duty looks (a day older than this has left every retry).
STUCK_SCAN_DAYS: Final[int] = 30
_FILL_LEGS: Final[tuple[Leg, ...]] = (Leg.L, Leg.D, Leg.B, Leg.I, Leg.E, Leg.P, Leg.S)
_OK: Final[frozenset[LegOutcome]] = frozenset(
    {LegOutcome.PASS, LegOutcome.INFO, LegOutcome.SKIPPED}
)
_NS: Final[int] = 1_000_000_000
_DAY_NS: Final[int] = 86_400 * _NS
_HOUR_NS: Final[int] = 3600 * _NS
_FILE_RE: Final[re.Pattern[str]] = re.compile(r"\A(\d{4}-\d\d-\d\d)(?:_(\d+))?\.json\Z")
_SLUG_RE: Final[re.Pattern[str]] = re.compile(
    r"\Atc-temp-(?P<city>[a-z]+?)high-(?P<day>\d{4}-\d\d-\d\d)-"
)
_MAX_AUDIT_BYTES: Final[int] = 64 * 1024 * 1024


# -- the pure status table -----------------------------------------------------------------------


def _day_start_ns(day: dt.date) -> int:
    return int(dt.datetime(day.year, day.month, day.day, tzinfo=dt.UTC).timestamp()) * _NS


def _epoch_day(inp: AuditInputs) -> dt.date | None:
    if inp.epoch is None:
        return None
    return dt.datetime.fromtimestamp(inp.epoch.epoch_start_ns // _NS, dt.UTC).date()


def _is_pre_capture(epoch_day: dt.date | None, day: dt.date) -> bool:
    return epoch_day is None or day < epoch_day


def _unarmed(inp: AuditInputs) -> bool:
    props = inp.recorder_props
    return props.watchdog_usec <= 0 or props.type != "notify" or props.notify_access != "all"


def _first_cause(legs: Sequence[LegResult], outcome: LegOutcome) -> str:
    for leg in legs:
        if leg.outcome is outcome:
            return next((f.cause for f in leg.findings if f.outcome is outcome), leg.leg.value)
    return ""


def _error_causes(legs: Sequence[LegResult]) -> list[str]:
    """Every ERROR cause of ``legs``, in order (a leg with no ERROR finding names itself)."""
    causes: list[str] = []
    for leg in legs:
        causes.extend(f.cause for f in leg.findings if f.outcome is LegOutcome.ERROR)
        if not any(f.outcome is LegOutcome.ERROR for f in leg.findings):
            causes.append(leg.leg.value)
    return causes


def _all_legs(fills: Sequence[FillAudit], legs: Sequence[LegResult]) -> list[LegResult]:
    return [*legs, *(leg for fill in fills for leg in fill.legs)]


def _no_input(inp: AuditInputs, fills: Sequence[FillAudit]) -> bool:
    takes = sum(b.replay.admitted_by_kind.get("Take", 0) for b in inp.boots if b.source == "live")
    start = _day_start_ns(inp.day)
    on_day = [r for r in inp.exec.resolvers if start <= r.created_ns < start + _DAY_NS]
    return not fills and not on_day and takes == 0


def _status(
    inp: AuditInputs, fills: Sequence[FillAudit], legs: Sequence[LegResult]
) -> tuple[DayStatus, str]:
    """The S2-R9 table. Pure: the same inputs and legs always give the same row."""
    every = _all_legs(fills, legs)
    errored = [leg for leg in every if leg.outcome is LegOutcome.ERROR]
    data_cause = next((c for c in _error_causes(errored) if c not in HOST_STATE_CAUSES), None)
    if data_cause is not None:  # ANY non-host-state ERROR beats the PRE_CAPTURE mask (S2-R45)
        return DayStatus.ERROR, data_cause
    if _is_pre_capture(_epoch_day(inp), inp.day):
        return DayStatus.PRE_CAPTURE, ""
    if errored:
        return DayStatus.ERROR, _first_cause(errored, LegOutcome.ERROR)
    if _unarmed(inp):
        return DayStatus.ERROR, "recorder_watchdog_unarmed"
    failing = [leg for leg in every if leg.outcome is LegOutcome.FAIL and leg.leg is not Leg.R6]
    if failing:
        return DayStatus.FAIL, f"{failing[0].leg.value}:{_first_cause(failing, LegOutcome.FAIL)}"
    if inp.day == _epoch_day(inp):
        return DayStatus.PARTIAL_EPOCH, ""
    pending = [leg for leg in every if leg.outcome is LegOutcome.PENDING]
    if pending:
        return DayStatus.INCONCLUSIVE, _first_cause(pending, LegOutcome.PENDING)
    if _no_input(inp, fills):
        return DayStatus.NO_INPUT, ""
    return DayStatus.PASS, ""


def _leg_pass_metrics(
    fills: Sequence[FillAudit], legs: Sequence[LegResult]
) -> dict[str, MetricValue]:
    metrics: dict[str, MetricValue] = {}
    for leg in legs:
        metrics[f"leg_{leg.leg.value}_pass"] = int(leg.outcome in _OK)
    for wanted in _FILL_LEGS:
        held = [leg for fill in fills for leg in fill.legs if leg.leg is wanted]
        metrics[f"leg_{wanted.value}_pass"] = int(all(leg.outcome in _OK for leg in held))
    return metrics


def _metrics(
    status: DayStatus,
    fills: Sequence[FillAudit],
    legs: Sequence[LegResult],
    gaps: Sequence[WatchdogGap],
) -> dict[str, MetricValue]:
    joined = sum(all(leg.outcome in _OK for leg in fill.legs) for fill in fills)
    metrics: dict[str, MetricValue] = {}
    for leg in legs:
        for name, value in leg.metrics.items():
            if name in METRIC_NAMES:
                metrics.setdefault(name, value)
    metrics.update(_leg_pass_metrics(fills, legs))
    metrics.update(
        day_status=status.value,
        fills_total=len(fills),
        fills_joined=joined,
        watchdog_kills_unproven=len(gaps),
    )
    return metrics


def _run_legs(
    inp: AuditInputs,
) -> tuple[tuple[FillAudit, ...], list[LegResult], tuple[WatchdogGap, ...]]:
    """Every leg, once. A leg that cannot read its input raises ``AuditInputError`` (the caller
    turns it into an ERROR day); any other exception is a bug and propagates."""
    fills = audit_fills(inp)
    watchdog, gaps = leg_w(inp)
    legs = [
        leg_r1(inp),
        leg_r2(inp),
        leg_r3(inp),
        leg_r4(inp),
        leg_r5(inp),
        leg_r6(inp),
        watchdog,
        leg_r7(inp),
        leg_o(inp),
        leg_f(inp),
        leg_t(inp),
        leg_n(inp),
        positive_control(inp),
    ]
    order = {leg: index for index, leg in enumerate(Leg)}
    return fills, sorted(legs, key=lambda r: order[r.leg]), gaps


def error_result(day: dt.date, family_id: str, cause: str, *, pre_capture: bool) -> AuditResult:
    """The result of a day whose inputs could not be read: ``ERROR`` with ``cause``, unless the
    cause is a host-state one and the day is ``PRE_CAPTURE`` (S2-R9)."""
    status = (
        DayStatus.PRE_CAPTURE if pre_capture and cause in HOST_STATE_CAUSES else DayStatus.ERROR
    )
    shown = "" if status is DayStatus.PRE_CAPTURE else cause
    return AuditResult(
        day=day,
        family_id=family_id,
        status=status,
        cause=shown,
        legs=(),
        fills=(),
        metrics={"day_status": status.value},
    )


def audit_day(inp: AuditInputs) -> AuditResult:
    """Run every leg over ``inp`` and fold the outcomes into the day status."""
    try:
        fills, legs, gaps = _run_legs(inp)
    except AuditInputError as exc:
        return error_result(
            inp.day, inp.family_id, exc.cause, pre_capture=_is_pre_capture(_epoch_day(inp), inp.day)
        )
    status, cause = _status(inp, fills, legs)
    duplicates = sum(b.replay.duplicate_lines for b in inp.boots if b.source == "live")
    return AuditResult(
        day=inp.day,
        family_id=inp.family_id,
        status=status,
        cause=cause,
        legs=tuple(legs),
        fills=fills,
        metrics=_metrics(status, fills, legs, gaps),
        watchdog_evidence_gaps=gaps,
        duplicate_decision_lines=duplicates,
        tape_marks=tape_marks(inp),
    )


# -- scheduling ----------------------------------------------------------------------------------


def days_to_audit(today: dt.date, audited: Mapping[dt.date, DayStatus]) -> tuple[dt.date, ...]:
    """The days one run audits, in order: yesterday, then each INCONCLUSIVE day of the last
    ``BACKFILL_DAYS`` (oldest first), then each day with no audit file (oldest first), then each
    ERROR day (oldest first). ERROR is not terminal (S2-R23): its cause may be gone, so the next
    run audits the day again, but only after the days never audited, so a missing day cannot age out
    behind a persistent ERROR (S2-R44). PASS, FAIL, NO_INPUT and PRE_CAPTURE are final."""
    yesterday = today - dt.timedelta(days=1)
    window = [today - dt.timedelta(days=back) for back in range(BACKFILL_DAYS, 0, -1)]
    inconclusive = [
        d for d in window if d != yesterday and audited.get(d) is DayStatus.INCONCLUSIVE
    ]
    missing = [d for d in window if d != yesterday and d not in audited]
    errored = [d for d in window if d != yesterday and audited.get(d) is DayStatus.ERROR]
    return (yesterday, *inconclusive, *missing, *errored)


# -- the audit files -----------------------------------------------------------------------------


def _audit_dir(family_id: str) -> tuple[str, ...]:
    return (*AUDIT_DIR_REL.split("/"), family_component(family_id))


def write_audit_file(data_root: Path, result: AuditResult, *, ts_ns: int) -> None:
    """Publish one day's audit file (write-once; ``<ts_ns>`` in the name when re-audited)."""
    parts = _audit_dir(result.family_id)
    body = (
        json.dumps(audit_to_wire(result), sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()
    rootfd = open_root(data_root)
    try:
        os.close(ensure_dir(rootfd, parts))
    finally:
        os.close(rootfd)
    base = data_root.joinpath(*parts)
    first = base / f"{result.day.isoformat()}.json"
    try:
        write_once(first, body, root=data_root, mode=AUDIT_FILE_MODE)
    except SingleReadRefused as exc:
        if exc.reason is not SingleReadReason.EXISTS_DIFFERENT:
            raise
        again = base / f"{result.day.isoformat()}_{ts_ns}.json"
        write_once(again, body, root=data_root, mode=AUDIT_FILE_MODE)


def _newest_by_day(names: Sequence[str]) -> dict[dt.date, str]:
    newest: dict[dt.date, tuple[int, str]] = {}
    for name in names:
        match = _FILE_RE.fullmatch(name)
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


def _list_dir(data_root: Path, rel: Sequence[str]) -> tuple[int | None, list[str]]:
    rootfd = open_root(data_root)
    try:
        try:
            dirfd = walk_dirs(rootfd, rel)
        except SingleReadRefused as exc:
            if exc.reason is SingleReadReason.NOT_FOUND:
                return None, []
            raise
    finally:
        os.close(rootfd)
    try:
        return dirfd, sorted(os.listdir(dirfd))
    except BaseException:
        os.close(dirfd)
        raise


def _audited_statuses(data_root: Path, family_id: str) -> dict[dt.date, DayStatus]:
    """The status of each day's NEWEST audit file; an unreadable file counts as no audit."""
    return {day: result.status for day, result in _audited_results(data_root, family_id).items()}


def _audited_results(data_root: Path, family_id: str) -> dict[dt.date, AuditResult]:
    """Each day's NEWEST audit file as a result; an unreadable file counts as no audit."""
    rel = _audit_dir(family_id)
    dirfd, names = _list_dir(data_root, rel)
    if dirfd is None:
        return {}
    found: dict[dt.date, AuditResult] = {}
    try:
        for day, name in _newest_by_day(names).items():
            try:
                raw = read_once_at(
                    dirfd, name, max_bytes=_MAX_AUDIT_BYTES, policy=ReadPolicy.STRICT
                )
                found[day] = audit_from_wire(json.loads(raw))
            except (SingleReadRefused, ValueError, KeyError, TypeError) as exc:
                _LOGGER.warning("capture audit: unreadable audit file (%s)", type(exc).__name__)
    finally:
        os.close(dirfd)
    return found


# -- the HEALTH verdict ----------------------------------------------------------------------------

_OUTCOME: Final[Mapping[DayStatus, VerdictOutcome]] = {
    DayStatus.PASS: VerdictOutcome.PASS,
    DayStatus.FAIL: VerdictOutcome.FAIL,
    DayStatus.ERROR: VerdictOutcome.ERROR,
}


def _write_health_verdict(data_root: Path, result: AuditResult, now_ns: int) -> None:
    """``health.capture_join`` only (S2-R12). Anything refused is INFO: the audit file already
    holds the full result, and the producer pin belongs to AUT-5 / ARCH-0 activation."""
    sha = PRODUCER_SOURCE_SHA256.get(PRODUCER_ID)
    if sha is None:
        _LOGGER.info("capture audit: verdict not written (producer unpinned) day=%s", result.day)
        return
    fills = int(result.metrics.get("fills_total", 0))
    joined = int(result.metrics.get("fills_joined", 0))
    try:
        write_verdict(
            AutonomyPaths(data_root),
            Verdict(
                kind=VerdictKind.HEALTH,
                subject_family_id=result.family_id,
                outcome=_OUTCOME.get(result.status, VerdictOutcome.INCONCLUSIVE),
                detector=DETECTOR,
                declared_action_class=ActionClass.NONE,
                produced_at_ns=now_ns,
                valid_until_ns=now_ns + LIVE_PROOF_MAX_AGE_H * _HOUR_NS,
                producer_code_sha=sha,
                metrics=(
                    ("day_status", result.status.value),
                    ("fills_joined", Decimal(joined)),
                    ("fills_total", Decimal(fills)),
                ),
                n=fills,
                n_min=fills,
                assumptions=(Assumption.NO_POLICY_RULING,),
            ),
        )
    except Exception as exc:  # noqa: BLE001 - a refused verdict write is INFO (S2-R12)
        _LOGGER.info("capture audit: verdict refused (%s) day=%s", type(exc).__name__, result.day)


# -- delivery ------------------------------------------------------------------------------------


class _Delivery:
    """Counts failed deliveries; the exit code reads it only after every write."""

    def __init__(self, offer: AlertOffer) -> None:
        self._offer = offer
        self.failed = 0

    def send(self, event: str, detail: str) -> None:
        try:
            accepted = bool(self._offer(event, CAPTURE_ALERT_SEVERITIES[event], detail))
        except Exception:  # noqa: BLE001 - an outbox failure is a failed delivery, not a crash
            accepted = False
        if not accepted:
            self.failed += 1
            _LOGGER.error("capture audit: %s undelivered", event)


def _failed_leg_ids(result: AuditResult, legs: Sequence[Leg]) -> list[str]:
    ids = {
        leg.leg.value for leg in result.legs if leg.leg in legs and leg.outcome is LegOutcome.FAIL
    }
    return sorted(ids)


def error_cause_set(result: AuditResult) -> frozenset[str]:
    """Every cause that makes ``result`` an ERROR day: its own and its errored legs' (S2-R44)."""
    own = {result.cause} if result.cause else set()
    return frozenset(own | set(_error_causes(_all_legs(result.fills, result.legs))))


def _alert_for(
    result: AuditResult, delivery: _Delivery, prior_error: frozenset[str] | None = None
) -> None:
    """The CRITICAL alerts of one day (§3.11.4): all through the one delivery seam.
    ``prior_error`` is the cause set of the day's previous audit file when that was an ERROR: the
    same cause set is not sent again (S2-R44)."""
    head = f"day={result.day.isoformat()} family={result.family_id}"
    if result.status is DayStatus.ERROR:
        if prior_error != error_cause_set(result):
            delivery.send("CAPTURE_AUDIT_ERROR", f"{head} cause={result.cause}")
        return
    if result.status is DayStatus.PRE_CAPTURE:
        return
    if result.status is DayStatus.FAIL:
        failing = sorted(
            {leg.leg.value for leg in result.legs if leg.outcome is LegOutcome.FAIL}
            | {
                leg.leg.value
                for fill in result.fills
                for leg in fill.legs
                if leg.outcome is LegOutcome.FAIL
            }
        )
        specific = {Leg.T.value, Leg.N.value, Leg.R6.value}
        if set(failing) - specific:
            delivery.send(
                "CAPTURE_JOIN_GAP", f"{head} legs={','.join(sorted(set(failing) - specific))}"
            )
    if _failed_leg_ids(result, (Leg.T,)):
        delivery.send("CAPTURE_TAPE_INGEST", head)
    if _failed_leg_ids(result, (Leg.N,)):
        delivery.send("CAPTURE_NBP_CENSUS", head)
    if _failed_leg_ids(result, (Leg.R6,)):
        delivery.send("CAPTURE_REFUSAL_REFS_UNRESOLVED", head)


# -- the moved duties (§3.11.5) --------------------------------------------------------------------


def _station_day(instrument_id: str) -> tuple[str, dt.date] | None:
    match = _SLUG_RE.match(instrument_id)
    if match is None:
        return None
    return match["city"].upper(), dt.date.fromisoformat(match["day"])


def _check_settlements(data_root: Path, today: dt.date, now_ns: int, delivery: _Delivery) -> None:
    """A settlement record exists for every traded station-day older than 48 h (and still inside
    the settlement writer's own scan window)."""
    view = read_exec_view(data_root)
    decisions = data_root / "catalog" / "quote_tape" / "decisions"
    seen: set[tuple[str, dt.date]] = set()
    for fill in view.fills:
        parsed = _station_day(fill.instrument_id)
        if parsed is not None:
            seen.add(parsed)
    for station, day in sorted(seen, key=lambda sd: (sd[1], sd[0])):
        if not today - dt.timedelta(days=SCAN_BACK_DAYS) <= day <= today:
            continue
        ended = _day_start_ns(day + dt.timedelta(days=1))
        if now_ns - ended <= SETTLEMENT_ALERT_H * _HOUR_NS:
            continue
        try:
            records = read_settlement_day(decisions, day)
        except (SettlementFileCorrupt, SingleReadRefused, FileNotFoundError):
            records = ()
        if not any(r.station == station for r in records):
            delivery.send("CAPTURE_SETTLEMENT_MISSING", f"station={station} climate_day={day}")


def _check_stuck(data_root: Path, family_id: str, today: dt.date, delivery: _Delivery) -> None:
    """No day is still INCONCLUSIVE 8 days after it ended."""
    for day, status in sorted(_audited_statuses(data_root, family_id).items()):
        age = (today - day).days
        if status is DayStatus.INCONCLUSIVE and BACKFILL_DAYS < age <= STUCK_SCAN_DAYS:
            delivery.send("CAPTURE_AUDIT_STUCK_INCONCLUSIVE", f"day={day.isoformat()}")


def _check_live_proof(data_root: Path, family_id: str, now_ns: int, delivery: _Delivery) -> None:
    """The newest live-proof roll-up of the family is younger than 26 h."""
    dirfd, names = _list_dir(data_root, LIVE_PROOF_DIR_REL)
    newest = 0
    if dirfd is not None:
        try:
            for name in names:
                match = LIVE_PROOF_NAME_RE.fullmatch(name)
                if match is not None and match["family_id"] == family_id:
                    info = os.stat(name, dir_fd=dirfd, follow_symlinks=False)
                    newest = max(newest, info.st_mtime_ns)
        finally:
            os.close(dirfd)
    if newest == 0 or now_ns - newest > LIVE_PROOF_MAX_AGE_H * _HOUR_NS:
        delivery.send("CAPTURE_LIVE_PROOF_STALE", f"family={family_id}")


# -- the run -------------------------------------------------------------------------------------


class _Run:
    """What a run learned: days written, deferred or failed, and the ERROR days."""

    def __init__(self) -> None:
        self.deferred: list[dt.date] = []
        self.failed: list[dt.date] = []
        self.errors = 0
        self.duty_failures = 0


def _pre_capture(data_root: Path, family_id: str, day: dt.date) -> bool:
    try:
        epoch = read_epoch(data_root, family_id)
    except Exception:  # noqa: BLE001 - an unreadable epoch is not a pre-capture day
        return False
    if epoch is None:
        return True
    return day < dt.datetime.fromtimestamp(epoch.epoch_start_ns // _NS, dt.UTC).date()


def _audit_one(data_root: Path, family_id: str, day: dt.date, now_ns: int) -> AuditResult:
    try:
        return audit_day(gather_inputs(data_root, family_id, day, now_ns=now_ns))
    except AuditInputError as exc:
        return error_result(
            day, family_id, exc.cause, pre_capture=_pre_capture(data_root, family_id, day)
        )


def _publish(
    data_root: Path,
    result: AuditResult,
    now_ns: int,
    delivery: _Delivery,
    run: _Run,
    prior_error: frozenset[str] | None = None,
) -> None:
    write_audit_file(data_root, result, ts_ns=now_ns)
    _write_health_verdict(data_root, result, now_ns)
    _alert_for(result, delivery, prior_error)
    run.errors += result.status is DayStatus.ERROR


def _run_days(
    data_root: Path,
    family_id: str,
    days: Sequence[dt.date],
    now_ns: int,
    delivery: _Delivery,
    run: _Run,
    prior_errors: Mapping[dt.date, frozenset[str]],
) -> None:
    for index, day in enumerate(days):
        try:
            result = _audit_one(data_root, family_id, day, now_ns)
        except ScanDeadline:
            run.deferred.extend(days[index:])
            return
        except Exception:
            _LOGGER.exception("capture audit: day %s failed", day)
            run.failed.append(day)
            continue
        try:
            _publish(data_root, result, now_ns, delivery, run, prior_errors.get(day))
        except Exception:
            _LOGGER.exception("capture audit: day %s could not be written", day)
            run.failed.append(day)


def _run_duties(
    data_root: Path, family_id: str, today: dt.date, now_ns: int, delivery: _Delivery, run: _Run
) -> None:
    duties: tuple[tuple[str, Callable[[], None]], ...] = (
        ("settlement_missing", lambda: _check_settlements(data_root, today, now_ns, delivery)),
        ("stuck_inconclusive", lambda: _check_stuck(data_root, family_id, today, delivery)),
        ("live_proof_stale", lambda: _check_live_proof(data_root, family_id, now_ns, delivery)),
    )
    for name, duty in duties:
        try:
            duty()
        except Exception:
            _LOGGER.exception("capture audit: duty %s failed", name)
            run.duty_failures += 1


def run_audit(
    data_root: Path, family_id: str, today: dt.date, *, now_ns: int, offer: AlertOffer
) -> int:
    """The whole run; returns the exit code."""
    token = DEADLINE.set(capture_audit_inputs.MONOTONIC() + AUDIT_WORK_BUDGET_S)
    delivery, run = _Delivery(offer), _Run()
    try:
        prior = _audited_results(data_root, family_id)
        statuses = {day: result.status for day, result in prior.items()}
        prior_errors = {
            day: error_cause_set(result)
            for day, result in prior.items()
            if result.status is DayStatus.ERROR
        }
        days = days_to_audit(today, statuses)
        _run_days(data_root, family_id, days, now_ns, delivery, run, prior_errors)
    finally:
        DEADLINE.reset(token)
    _run_duties(data_root, family_id, today, now_ns, delivery, run)
    sys.stderr.write(
        f"capture audit: errors={run.errors} deliveries_failed={delivery.failed} "
        f"duty_failures={run.duty_failures} failed_days={len(run.failed)} "
        f"audit_deferred_days={[d.isoformat() for d in run.deferred]}\n"
    )
    failed = run.errors or delivery.failed or run.failed or run.duty_failures
    return 1 if failed else 0
