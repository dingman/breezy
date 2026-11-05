"""AUT-1 WP5 stage 3 S1: the heal duty's I/O (design r3 D6, D7; plan r12 sections 3.10.3, 3.11.6).

``run_heal_duty`` runs once per audit run, after the studies lock and before the family loop (3c
wires it, S3-R18). It

1. reads the recorder journal one UTC day at a time over the last ``HEAL_JOURNAL_DAYS`` days
   (S3-R3),
   matches each watchdog kill to its restart by ``instance_id`` and, when the heal is confirmed
   (``capture_heal``), writes the write-once heal record and sends ``CAPTURE_HEALED_<sha>``;
2. re-sends every heal record of the last ``HEAL_ALERT_RETRY_DAYS`` dates that has no delivered
   record (``attempt_kind="retry"``; a node record only once it is older than 600 s), abandons the
   ones in ``[today-30, today-8]`` (the marker is written only after a delivered proof) and logs
   the unmarked ones older than that;
3. does the same for the leg-W evidence gaps recorded in the audit files, dropping a gap whose stall
   record and notifier marker have since appeared.

Alerts go through the injected ``HealSender``; this module never imports the audit's delivery
class. Running past ``heal_deadline`` (or the run's ``DEADLINE``) is a FAILURE, never a deferral
(S3-R29, S3-R41). Every failure is counted and returned; a heal never raises into the audit.
"""

import datetime as dt
import json
import logging
import os
import re
import stat
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Protocol

from breezy.analysis import capture_audit_inputs
from breezy.analysis.capture_audit_host import RECORDER_JOURNAL_ARGV, journal_slot, run_journal
from breezy.analysis.capture_audit_host import parse_recorder_journal as _parse_journal
from breezy.analysis.capture_audit_io import list_names, read_file
from breezy.analysis.capture_audit_model import AUDIT_DIR_REL, AuditInputError, WatchdogGap
from breezy.analysis.capture_audit_wire import AuditWireError, audit_from_wire
from breezy.analysis.capture_aut6_contract import NOTIFIER_MARKER_RE, delivered_events
from breezy.analysis.capture_heal import (
    HEAL_ABANDON_DAYS,
    HEAL_JOURNAL_DAYS,
    RECORDER_UNIT,
    HealPlan,
    InstanceEvidence,
    alert_phase,
    gap_key,
    heal_body,
    heal_record_matches,
    instance_lines,
    node_record_resendable,
    plan_heals,
)
from breezy.persistence.autonomy.capture_alerts import abandoned_alert_event, heal_alert_event
from breezy.persistence.autonomy.single_read import (
    ReadPolicy,
    SingleReadRefused,
    ensure_dir,
    open_root,
    write_once,
)
from breezy.runtime.capture_recorder_hook_cli import STALL_RELATIVE, STALL_SUFFIX

__all__ = ["HealSender", "run_heal_duty"]

_LOGGER = logging.getLogger(__name__)

HEAL_REL: Final[tuple[str, ...]] = ("evidence", "capture", "heal")
ABANDONED_REL: Final[tuple[str, ...]] = ("evidence", "capture", "heal_alert_abandoned")
DRILL_REL: Final[tuple[str, ...]] = ("evidence", "capture", "drill")
NOTIFY_REL: Final[tuple[str, ...]] = ("evidence", "alerts", "notify")
LIVE_REL: Final[tuple[str, ...]] = ("catalog", "quote_tape", "polymarket_us", "live")
RECORD_MODE: Final[int] = 0o444
GAP_EVENT: Final[str] = "CAPTURE_WATCHDOG_EVIDENCE_GAP"
KIND_FIRST: Final[str] = "alert"
KIND_RETRY: Final[str] = "retry"

_NS: Final[int] = 1_000_000_000
_DAY_S: Final[int] = 86_400
_DATE_RE: Final[re.Pattern[str]] = re.compile(r"\A\d{4}-\d\d-\d\d\Z")
_HEAL_NAME_RE: Final[re.Pattern[str]] = re.compile(
    r"\A(?P<ts>\d{1,20})_(?P<who>audit|node)_[A-Za-z0-9_.-]{1,96}\.json\Z"
)
_AUDIT_NAME_RE: Final[re.Pattern[str]] = re.compile(r"\A(\d{4}-\d\d-\d\d)(?:_(\d+))?\.json\Z")
_INVOCATION_RE: Final[re.Pattern[str]] = re.compile(r"\A[0-9a-f]{32}\Z")
_SHA_RE: Final[re.Pattern[str]] = re.compile(r"\A[0-9a-f]{64}\Z")
#: What an unreadable or malformed evidence file raises.
_UNREADABLE: Final = (SingleReadRefused, ValueError, TypeError, OSError)


class HealSender(Protocol):
    """The alert seam: ``send`` is True when the alert was accepted for delivery."""

    def send(self, event: str, detail: str, attempt_kind: str) -> bool: ...


@dataclass(frozen=True, slots=True)
class _Item:
    """One alert the re-send rules govern: a heal record or a leg-W gap."""

    key: str
    day: dt.date
    event: str
    detail: str
    marker: str
    resendable: bool
    delivery_retires: bool


@dataclass(slots=True)
class _Run:
    data_root: Path
    now_ns: int
    deadline: float
    sender: HealSender
    delivered: frozenset[str]
    failures: int = 0
    unabandoned_heals: int = 0
    unabandoned_gaps: int = 0

    @property
    def today(self) -> dt.date:
        return _date_of(self.now_ns)

    def check(self) -> None:
        """Raise ``ScanDeadline`` once the heal budget or the run's ``DEADLINE`` is spent."""
        limit = self.deadline
        overall = capture_audit_inputs.DEADLINE.get()
        if overall is not None:
            limit = min(limit, overall)
        if capture_audit_inputs.MONOTONIC() >= limit:
            raise capture_audit_inputs.ScanDeadline

    def send(self, event: str, detail: str, kind: str) -> bool:
        self.check()
        try:
            accepted = bool(self.sender.send(event, detail, kind))
        except Exception:  # noqa: BLE001 - an outbox failure is a failed delivery, not a crash
            accepted = False
        if not accepted:
            self.failures += 1
            _LOGGER.error("capture heal: %s undelivered", event)
        return accepted

    def fail(self, what: str, exc: BaseException) -> None:
        self.failures += 1
        _LOGGER.error("capture heal: %s failed (%s: %s)", what, type(exc).__name__, exc)


def _date_of(ns: int) -> dt.date:
    return dt.datetime.fromtimestamp(ns // _NS, dt.UTC).date()


def _midnight_s(day: dt.date) -> int:
    return int(dt.datetime(day.year, day.month, day.day, tzinfo=dt.UTC).timestamp())


def _dump(body: Mapping[str, object]) -> bytes:
    return (json.dumps(body, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _load(data_root: Path, rel: Sequence[str], name: str, policy: ReadPolicy) -> dict[str, object]:
    body = json.loads(read_file(data_root, rel, name, policy) or b"")
    if not isinstance(body, dict):
        raise TypeError("not an object")
    return body


def _publish(data_root: Path, rel: Sequence[str], name: str, body: Mapping[str, object]) -> None:
    rootfd = open_root(data_root)
    try:
        os.close(ensure_dir(rootfd, rel))
    finally:
        os.close(rootfd)
    write_once(data_root.joinpath(*rel, name), _dump(body), root=data_root, mode=RECORD_MODE)


# -- the journal and the restart evidence --------------------------------------------------------


def _read_journals(run: _Run) -> tuple[str, ...]:
    """One journal read per UTC day over the last ``HEAL_JOURNAL_DAYS`` days, oldest first. A quiet
    day is tolerated; no output at all, or any other failure, is ``journal_failed``."""
    texts: list[str] = []
    for back in range(HEAL_JOURNAL_DAYS - 1, -1, -1):
        run.check()
        day = run.today - dt.timedelta(days=back)
        since = journal_slot(_midnight_s(day))
        until = journal_slot(_midnight_s(day) + _DAY_S)
        try:
            texts.append(run_journal(RECORDER_JOURNAL_ARGV, since, until))
        except AuditInputError as exc:
            if exc.cause != "journal_failed" or exc.detail != "empty_output":
                raise
    if not texts:
        raise AuditInputError("journal_failed", "empty_output")
    return tuple(texts)


def _stall_sha(data_root: Path, invocation_id: str, kill_ns: int) -> str:
    """The ``observation_sha256`` of the hook's stall record for the kill, or ``""``."""
    if _INVOCATION_RE.fullmatch(invocation_id) is None:
        return ""
    name_re = re.compile(rf"\A\d+_{invocation_id}{re.escape(STALL_SUFFIX)}\Z")
    for offset in (0, 1):
        rel = (*STALL_RELATIVE.parts, (_date_of(kill_ns) + dt.timedelta(days=offset)).isoformat())
        for name in list_names(data_root, rel):
            if name_re.fullmatch(name):
                body = _load(data_root, rel, name, ReadPolicy.STRICT)
                sha = body.get("observation_sha256")
                if body.get("invocation_id") != invocation_id or not isinstance(sha, str):
                    raise ValueError("stall record does not match its name")
                return sha
    return ""


def _instance_evidence(live_root: Path, instance_id: str) -> InstanceEvidence:
    """Whether ``live/<id>/config.json`` exists and how long the instance grew: the newest mtime of
    a NON-DOT entry (a non-empty ``*.feather`` or a data subdirectory) minus the ``config.json``
    mtime. Preflight memos, salvage and conversion markers are dot-files and never count."""
    directory = live_root / instance_id
    try:
        if not stat.S_ISDIR(os.lstat(directory).st_mode):
            return InstanceEvidence(False, 0)
        config = os.lstat(directory / "config.json")
    except FileNotFoundError:
        return InstanceEvidence(False, 0)
    if not stat.S_ISREG(config.st_mode):
        return InstanceEvidence(False, 0)
    newest = config.st_mtime_ns
    with os.scandir(directory) as entries:
        for entry in entries:
            if entry.name.startswith("."):
                continue
            info = entry.stat(follow_symlinks=False)
            is_data = stat.S_ISDIR(info.st_mode) or (
                stat.S_ISREG(info.st_mode) and entry.name.endswith(".feather") and info.st_size > 0
            )
            if is_data:
                newest = max(newest, info.st_mtime_ns)
    return InstanceEvidence(True, newest - config.st_mtime_ns)


def _drill_injected(data_root: Path, kill_ns: int) -> bool:
    """Whether the drill wrote ``drill/<kill date>.json`` before this heal's first write."""
    try:
        body = _load(data_root, DRILL_REL, f"{_date_of(kill_ns).isoformat()}.json", ReadPolicy.REPO)
    except _UNREADABLE:
        return False
    return body.get("injected") is True


def _write_heal(run: _Run, plan: HealPlan) -> bool:
    """Write the heal record once. A record whose name exists is never rebuilt (``injected`` is
    read at first write only): its invariant fields are verified and it is a no-op."""
    rel = (*HEAL_REL, _date_of(plan.kill.ts_ns).isoformat())
    name = f"{plan.kill.ts_ns}_audit_breezy-quote-tape.json"
    if read_file(run.data_root, rel, name, ReadPolicy.STRICT) is not None:
        if not heal_record_matches(_load(run.data_root, rel, name, ReadPolicy.STRICT), plan):
            raise ValueError("an existing heal record disagrees with the journal")
        return False
    injected = _drill_injected(run.data_root, plan.kill.ts_ns)
    _publish(run.data_root, rel, name, heal_body(plan, injected=injected))
    return True


def _heal_phase(run: _Run) -> frozenset[str]:
    """Confirm and record the recorder's heals; the shas of the records written (and offered)."""
    texts = _read_journals(run)
    kills = tuple(e for text in texts for e in _parse_journal(text) if e.unit_result == "watchdog")
    lines = tuple(line for text in texts for line in instance_lines(text))
    live_root = run.data_root.joinpath(*LIVE_REL)
    shas: dict[str, str] = {}
    for kill in kills:
        run.check()
        try:
            shas[kill.invocation_id] = _stall_sha(run.data_root, kill.invocation_id, kill.ts_ns)
        except _UNREADABLE as exc:
            run.fail("stall record", exc)
    first_kill = min((k.ts_ns for k in kills), default=0)
    evidence = {
        line.instance_id: _instance_evidence(live_root, line.instance_id)
        for line in lines
        if line.ts_ns > first_kill
    }
    sent: set[str] = set()
    for plan in plan_heals(kills, lines, shas, evidence, run.now_ns):
        run.check()
        try:
            written = _write_heal(run, plan)
        except _UNREADABLE as exc:
            run.fail("heal record", exc)
            continue
        if written:
            sent.add(plan.observation_sha256)
            day = _date_of(plan.kill.ts_ns).isoformat()
            run.send(
                heal_alert_event(plan.observation_sha256),
                f"heal={plan.observation_sha256} date={day} unit={RECORDER_UNIT}",
                KIND_FIRST,
            )
    return frozenset(sent)


# -- the re-send, abandon and age-out rules -------------------------------------------------------


def _heal_items(run: _Run, fresh: frozenset[str]) -> list[_Item]:
    items: list[_Item] = []
    for date_name in list_names(run.data_root, HEAL_REL):
        if _DATE_RE.fullmatch(date_name) is None:
            continue
        try:
            day = dt.date.fromisoformat(date_name)
        except ValueError:
            _LOGGER.warning("capture heal: heal directory %s is not a date, skipped", date_name)
            continue
        rel = (*HEAL_REL, date_name)
        for name in list_names(run.data_root, rel):
            match = _HEAL_NAME_RE.fullmatch(name)
            if match is None:
                continue
            try:
                sha = _load(run.data_root, rel, name, ReadPolicy.STRICT).get("observation_sha256")
                if not isinstance(sha, str) or _SHA_RE.fullmatch(sha) is None:
                    raise ValueError("no observation_sha256")
            except _UNREADABLE as exc:
                run.fail("heal record read", exc)
                continue
            if sha in fresh:
                continue
            node = match["who"] == "node"
            items.append(
                _Item(
                    key=sha,
                    day=day,
                    event=heal_alert_event(sha),
                    detail=f"heal={sha} date={date_name}",
                    marker=f"{sha}.json",
                    resendable=not node or node_record_resendable(int(match["ts"]), run.now_ns),
                    delivery_retires=True,
                )
            )
    return items


def _newest_audit_per_day(names: Sequence[str]) -> dict[dt.date, str]:
    newest: dict[dt.date, tuple[int, str]] = {}
    for name in names:
        match = _AUDIT_NAME_RE.fullmatch(name)
        if match is None:
            continue
        day, stamp = dt.date.fromisoformat(match[1]), int(match[2] or 0)
        if day not in newest or stamp >= newest[day][0]:
            newest[day] = (stamp, name)
    return {day: name for day, (_stamp, name) in newest.items()}


def _recorded_gaps(run: _Run) -> dict[str, WatchdogGap]:
    """The leg-W gaps of the newest audit file of each day in ``[today-31, today-1]``, by key. An
    unreadable audit file counts as no audit (the audit itself re-audits that day)."""
    first = run.today - dt.timedelta(days=HEAL_ABANDON_DAYS + 1)
    found: dict[str, WatchdogGap] = {}
    parts = tuple(AUDIT_DIR_REL.split("/"))
    for family in list_names(run.data_root, parts):
        rel = (*parts, family)
        newest = _newest_audit_per_day(list_names(run.data_root, rel))
        for day, name in sorted(newest.items()):
            if not first <= day < run.today:
                continue
            run.check()
            try:
                result = audit_from_wire(_load(run.data_root, rel, name, ReadPolicy.REPO))
            except (*_UNREADABLE, AuditWireError) as exc:
                _LOGGER.warning(
                    "capture heal: audit file %s unreadable (%s)", name, type(exc).__name__
                )
                continue
            for gap in result.watchdog_evidence_gaps:
                found.setdefault(gap_key(gap.invocation_id), gap)
    return found


def _notifier_delivered(data_root: Path, gap: WatchdogGap) -> bool:
    for offset in (0, 1):
        rel = (*NOTIFY_REL, (_date_of(gap.ts_ns) + dt.timedelta(days=offset)).isoformat())
        for name in list_names(data_root, rel):
            match = NOTIFIER_MARKER_RE.fullmatch(name)
            if match is None or match["unit"] != gap.unit or match["inv"] != gap.invocation_id:
                continue
            if _load(data_root, rel, name, ReadPolicy.REPO).get("delivered") is True:
                return True
    return False


def _evidence_appeared(data_root: Path, gap: WatchdogGap) -> bool:
    """Both the stall record and the delivered notifier marker exist now (an unreadable one does
    not count: the gap stays and is re-sent)."""
    try:
        return bool(_stall_sha(data_root, gap.invocation_id, gap.ts_ns)) and _notifier_delivered(
            data_root, gap
        )
    except _UNREADABLE:
        return False


def _gap_items(run: _Run) -> list[_Item]:
    items: list[_Item] = []
    for key, gap in sorted(_recorded_gaps(run).items()):
        if _evidence_appeared(run.data_root, gap):
            continue
        items.append(
            _Item(
                key=key,
                day=_date_of(gap.ts_ns),
                event=GAP_EVENT,
                detail=f"gap={key} invocation_id={gap.invocation_id} cause={gap.cause}",
                marker=f"gap_{key}.json",
                resendable=True,
                delivery_retires=False,
            )
        )
    return items


def _mark(run: _Run, item: _Item, markers: set[str], proof: str) -> None:
    body = {"key": item.key, "proof": proof, "written_ns": run.now_ns}
    try:
        _publish(run.data_root, ABANDONED_REL, item.marker, body)
    except (SingleReadRefused, OSError) as exc:
        run.fail("abandon marker", exc)
        return
    markers.add(item.marker)


def _process(run: _Run, item: _Item, markers: set[str]) -> None:
    phase = alert_phase((run.today - item.day).days)
    if item.marker in markers or phase == "future":
        return
    run.check()
    abandon_event = abandoned_alert_event(item.key)
    healed = item.delivery_retires and item.event in run.delivered
    if phase == "retry":
        if not healed and item.resendable:
            run.send(item.event, item.detail, KIND_RETRY)
    elif healed or abandon_event in run.delivered:
        _mark(run, item, markers, "delivered" if healed else "abandon_delivered")
    elif phase == "abandon":
        run.send(abandon_event, item.detail, KIND_RETRY)
    elif item.delivery_retires:
        run.unabandoned_heals += 1
        _LOGGER.error("CAPTURE_HEAL_UNABANDONED heal=%s", item.key)
    else:
        run.unabandoned_gaps += 1
        _LOGGER.error("CAPTURE_HEAL_UNABANDONED gap=%s", item.key)


def _resend_phase(run: _Run, fresh: frozenset[str]) -> None:
    try:
        markers = set(list_names(run.data_root, ABANDONED_REL))
    except _UNREADABLE as exc:
        run.fail("abandoned marker listing", exc)
        return
    for heals in (True, False):
        try:
            items = _heal_items(run, fresh) if heals else _gap_items(run)
        except _UNREADABLE as exc:
            run.fail("alert listing", exc)
            continue
        for item in items:
            _process(run, item, markers)


def _delivered(run: _Run) -> frozenset[str]:
    """The delivered events of the last ``HEAL_ABANDON_DAYS + 1`` days. An unreadable ledger FILE is
    not delivered: that fail-closed rule lives inside ``delivered_events`` (S3-R56). Every exception
    it RAISES is one duty failure (S3-R52), and the rest of the heal work still runs, failing closed
    toward a re-send."""
    first = run.today - dt.timedelta(days=HEAL_ABANDON_DAYS + 1)
    try:
        return delivered_events(run.data_root, first, run.today)
    except Exception as exc:  # noqa: BLE001 - the duty never raises: a reader bug is one failure
        run.fail("delivery ledger", exc)
    return frozenset()


def run_heal_duty(data_root: Path, *, now_ns: int, heal_deadline: float, sender: HealSender) -> int:
    """Run the heal duty once; returns the number of failures. ``heal_deadline`` is a monotonic
    instant: running past it (or the run's ``DEADLINE``), as a ``ScanDeadline``, is a failure."""
    run = _Run(data_root, now_ns, heal_deadline, sender, frozenset())
    try:
        run.delivered = _delivered(run)
        fresh: frozenset[str] = frozenset()
        try:
            fresh = _heal_phase(run)
        except (AuditInputError, *_UNREADABLE) as exc:
            run.fail("heal confirmation", exc)
        _resend_phase(run, fresh)
    except capture_audit_inputs.ScanDeadline:
        run.failures += 1
        _LOGGER.error("capture heal: budget exhausted")
    _LOGGER.info(
        "capture heal: heal_alert_unabandoned_count=%d gap_alert_unabandoned_count=%d",
        run.unabandoned_heals,
        run.unabandoned_gaps,
    )
    return run.failures
