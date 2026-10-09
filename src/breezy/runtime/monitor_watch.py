"""The AUT-6 meta-detectors of the unit health pass (plan r15 sections 3.9-3.11; WP3 S5).

``#28 aut6.timer_liveness``, ``#26 aut6.producer_stale``, ``#27 aut6.daily_verdict_absent``,
``#23 aut6.alert_delivery`` and ``#31 aut6.memory_budget``, judged from the S2 bus snapshot (six
reads, including the loaded and on-disk inventories), the committed ``deploy/systemd`` files and
the alert, producer and memory stores. Nothing here reads systemd itself or any trading gate.

Not-deployed rule (execution decision X-8): ``NOT_YET_DEPLOYED`` holds ``(unit, owner_wp,
not_expected_until)`` rows for units a later work package builds. An absent unit reads
INCONCLUSIVE(not_deployed) only while its row stands, today is before ``not_expected_until``, the
host holds no file or broken link for it and none of its artifacts exists. That outcome never
pages, never counts toward ``unknown_streak`` and is listed as ``not_deployed=[...]`` in
``day_<date>.json``.
The owning WP's activation commit deletes its rows.
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Final

from breezy.runtime.monitor_watch_delivery import DeliveryInputs, evaluate_delivery
from breezy.runtime.monitor_watch_deploy import KIND_OVERDUE, NotDeployedRow, classify_unit
from breezy.runtime.monitor_watch_memory import RECORDER_UNIT, evaluate_memory
from breezy.runtime.monitor_watch_model import (
    NS,
    Deployment,
    DetectorResult,
    Inventory,
    Outcome,
    WatchResult,
    parse_inventory,
    timestamp_or_zero,
)
from breezy.runtime.monitor_watch_producer import (
    FileProducerSource,
    ProducerSource,
    evaluate_daily,
    evaluate_producer,
    scan_verdict_cadences,
)
from breezy.runtime.monitor_watch_timers import evaluate_timers
from breezy.runtime.process_lookup import find_pid_by_argv_checked
from breezy.runtime.trade_supervisor_core import NODE_ARGV_ANCHOR
from breezy.runtime.unit_health_journal import JOURNALCTL, JournalError, Run, run_bounded
from breezy.runtime.unit_health_model import parse_show_blocks
from breezy.runtime.unit_health_obs import UnitObservation
from breezy.runtime.unit_health_store import MemAvailWindow, day_of_ns

#: ``(interval_s, assumed_accuracy_s)`` per ``deploy/systemd/*.timer`` file. The interval is the
#: longest wait between two firings of its ``OnCalendar`` (a test derives it from the file); the
#: accuracy is the ``AccuracySec`` the 900 s grace assumes (Y7): 60 for the 1min timers, 30 for
#: ``breezy-quote-tape-ingest-frequent``, 1 for every ``breezy-autonomy-*`` timer and for the
#: ``us-source-collector@`` template, which declares ``AccuracySec=1s``.
TIMER_MAX_INTERVAL_S: Final[Mapping[str, tuple[int, int]]] = {
    "breezy-asos-refresh.timer": (86_400, 60),
    "breezy-autonomy-alert-redeliver.timer": (300, 1),
    "breezy-autonomy-canary.timer": (3_600, 1),
    "breezy-autonomy-health.timer": (600, 1),
    "breezy-capital-flow-pull.timer": (86_400, 60),
    "breezy-decision-funnel-digest.timer": (86_400, 60),
    "breezy-decisions-retention.timer": (86_400, 60),
    "breezy-discovery-pull.timer": (86_400, 60),
    "breezy-exit-window-study.timer": (86_400, 60),
    "breezy-family-tally@.timer": (86_400, 60),
    "breezy-fee-evidence-pull.timer": (86_400, 60),
    "breezy-hypothesis-triage.timer": (86_400, 60),
    "breezy-nbp-learning-nightly.timer": (86_400, 60),
    "breezy-portfolio-roi.timer": (86_400, 60),
    "breezy-position-monitor-report.timer": (86_400, 60),
    "breezy-quote-tape-ingest-frequent.timer": (3_600, 30),
    "breezy-quote-tape-ingest.timer": (21_600, 60),
    "breezy-quote-tape-rotate.timer": (86_400, 60),
    "breezy-replay-daily.timer": (86_400, 60),
    "breezy-score-live-trials.timer": (86_400, 60),
    "breezy-truth-dataset.timer": (86_400, 60),
    "breezy-truth-fetch.timer": (86_400, 60),
    "us-source-collector@.timer": (5_940, 1),
}
#: Instances whose drop-in schedule differs from their template's (same shape as the table).
TIMER_INSTANCE_INTERVAL_S: Final[Mapping[str, tuple[int, int]]] = {
    "us-source-collector@lav.timer": (3_000, 1),
    "us-source-collector@mos.timer": (3_600, 1),
    "us-source-collector@nbp.timer": (21_600, 1),
    "us-source-collector@obs.timer": (3_000, 1),
    "us-source-collector@pfm.timer": (5_400, 1),
}
TIMER_RETIRED_BY_RULING: Final[Mapping[str, str]] = {
    "breezy-live-tally.timer": "RULING_R5_prereg_v1_tally_2026-09-24",
}
#: Units a later work package builds (X-8). WP6 (intraday producer) and WP7 (daily producer) are
#: gated on rows 5 and 7 of the programme and the FQ-v2 no-trade ruling; 2026-11-16 leaves two
#: weeks of WARNING before the AUT-4 clock (``NOT_DEPLOYED_CRITICAL_FROM``) turns it CRITICAL.
NOT_YET_DEPLOYED: Final[Mapping[str, NotDeployedRow]] = {
    row.unit: row
    for row in (
        NotDeployedRow("breezy-autonomy-producer-intraday.service", "AUT-6.WP6", "2026-11-16"),
        NotDeployedRow("breezy-autonomy-producer-intraday.timer", "AUT-6.WP6", "2026-11-16"),
        NotDeployedRow("breezy-autonomy-producer-daily.service", "AUT-6.WP7", "2026-11-16"),
        NotDeployedRow("breezy-autonomy-producer-daily.timer", "AUT-6.WP7", "2026-11-16"),
    )
}
#: ``AUT4_REPLAY_EXPECTED_BY`` (2026-11-30): AUT-4's ETA plus 7 days. WP7 owns the shared constant.
NOT_DEPLOYED_CRITICAL_FROM: Final = "2026-11-30"
#: Files a unit leaves under the data root once it has run (relative paths; fail closed on error).
NOT_DEPLOYED_ARTIFACTS: Final[Mapping[str, tuple[str, ...]]] = {
    "breezy-autonomy-producer-intraday.service": (
        "derived/verdicts/.aut6-intraday.heartbeat",
        "derived/verdicts/.aut6-intraday.stage_status",
    ),
    "breezy-autonomy-producer-intraday.timer": (
        "derived/verdicts/.aut6-intraday.heartbeat",
        "derived/verdicts/.aut6-intraday.stage_status",
    ),
    "breezy-autonomy-producer-daily.service": (
        "derived/verdicts/_aut6_daily_skips",
        "derived/verdicts/_aut6_daily_state",
    ),
    "breezy-autonomy-producer-daily.timer": (
        "derived/verdicts/_aut6_daily_skips",
        "derived/verdicts/_aut6_daily_state",
    ),
}
TIMER_DETECTOR: Final = "aut6.timer_liveness"
PRODUCER_DETECTOR: Final = "aut6.producer_stale"
DAILY_DETECTOR: Final = "aut6.daily_verdict_absent"
DELIVERY_DETECTOR: Final = "aut6.alert_delivery"
MEMORY_DETECTOR: Final = "aut6.memory_budget"
INTRADAY_UNITS: Final = (
    "breezy-autonomy-producer-intraday.service",
    "breezy-autonomy-producer-intraday.timer",
)
DAILY_UNITS: Final = (
    "breezy-autonomy-producer-daily.service",
    "breezy-autonomy-producer-daily.timer",
)
CANARY_TIMER: Final = "breezy-autonomy-canary.timer"
#: Units whose stdout summary lines #23 reads.
SUMMARY_UNITS: Final = (
    "breezy-autonomy-canary.service",
    "breezy-autonomy-alert-redeliver.service",
    "breezy-autonomy-producer-intraday.service",
    "breezy-autonomy-producer-daily.service",
    "breezy-autonomy-health.service",
)
SUMMARY_LOOKBACK_S: Final = 15 * 60
SUMMARY_MAX_LOOKBACK_S: Final = 48 * 3600
NODE_LOG_TAIL_BYTES: Final = 4 * 1024 * 1024
_NODE_LOG_RE: Final = re.compile(r"breezy-trade-\d{8}T\d{6}Z\.log")
_LOG = logging.getLogger(__name__)
_DEPLOY_DIR: Final = Path(__file__).resolve().parents[3] / "deploy" / "systemd"
_PROC: Final = Path("/proc")
_RSS_RE: Final = re.compile(r"^VmRSS:\s+(\d+)\s+kB$", re.MULTILINE)
_SUMMARY_MARKERS: Final = (
    "journal_write_failures=",
    "outbox_write_failures=",
    "integrity_demand_write_failures=",
    "PRODUCER_INTRADAY_DEMAND",
)

SummaryReader = Callable[[int, float], Sequence[str]]
EvidenceReader = Callable[[str, float], bool]


def journal_summary_reader(run: Run = run_bounded) -> SummaryReader:
    """Summary lines of ``SUMMARY_UNITS`` since ``since_ns`` (``journalctl --user -o cat``)."""

    def read(since_ns: int, timeout_s: float) -> Sequence[str]:
        argv = [
            JOURNALCTL,
            "--user",
            "-o",
            "cat",
            "--no-pager",
            f"--since=@{since_ns // NS}",
            *(f"_SYSTEMD_USER_UNIT={unit}" for unit in SUMMARY_UNITS),
        ]
        result = run(argv, timeout_s)
        if result.timed_out:
            raise JournalError("timed_out")
        if result.oversize:
            raise JournalError("oversize")
        if result.rc != 0:
            raise JournalError(f"rc={result.rc}")
        return [ln for ln in result.stdout.splitlines() if any(m in ln for m in _SUMMARY_MARKERS)]

    return read


def read_node_log_tail(logs_dir: Path) -> str | None:
    """The tail of the newest node log; ``""`` when there is none, ``None`` when unreadable."""
    try:
        logs = sorted(p for p in logs_dir.iterdir() if _NODE_LOG_RE.fullmatch(p.name))
    except FileNotFoundError:
        return ""
    except OSError:
        return None
    if not logs:
        return ""
    try:
        with logs[-1].open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            handle.seek(max(0, handle.tell() - NODE_LOG_TAIL_BYTES))
            return handle.read().decode("utf-8", errors="replace")
    except OSError:
        return None


def read_pid_rss_kib(pid: int, proc: Path = _PROC) -> int | None:
    """``VmRSS`` of ``/proc/<pid>/status`` in KiB; ``None`` when unreadable or absent (a kernel
    thread has no ``VmRSS`` line). The caller decides whether a zero or a ``None`` is fatal."""
    try:
        found = _RSS_RE.search((proc / str(pid) / "status").read_text(encoding="utf-8"))
    except OSError:
        return None
    return int(found.group(1)) if found else None


def journal_evidence_reader(run: Run = run_bounded) -> EvidenceReader:
    """Whether the user journal holds any line of ``SYSLOG_IDENTIFIER=<identifier>`` (a unit that
    has ever run leaves one): evidence that an absent unit was once deployed."""

    def seen(identifier: str, timeout_s: float) -> bool:
        argv = [
            JOURNALCTL,
            "--user",
            "-q",
            "-o",
            "cat",
            "--no-pager",
            "-n",
            "1",
            f"SYSLOG_IDENTIFIER={identifier}",
        ]
        result = run(argv, timeout_s)
        if result.timed_out:
            raise JournalError("timed_out")
        if result.oversize:
            raise JournalError("oversize")
        if result.rc != 0:
            raise JournalError(f"rc={result.rc}")
        return bool(result.stdout.strip())

    return seen


@dataclass
class WatchWiring:
    """The meta-detectors' seams. ``data_root`` holds the alerts, verdicts and logs."""

    data_root: Path
    deploy_dir: Path = _DEPLOY_DIR
    producer: ProducerSource | None = None
    summary: SummaryReader | None = None
    node_log_tail: Callable[[], str | None] | None = None
    #: The node's PID by the supervisor's own argv anchor; raises ``OSError`` when pgrep fails.
    find_node_pid: Callable[[], int | None] = lambda: find_pid_by_argv_checked(NODE_ARGV_ANCHOR)
    pid_rss_kib: Callable[[int], int | None] = read_pid_rss_kib
    journal_evidence: EvidenceReader | None = None
    #: Which producers left verdict files; ``None`` scans the data root.
    verdict_cadences: Callable[[], frozenset[str]] | None = None
    access: Callable[[Path, int], bool] = os.access
    free_bytes: Callable[[Path], int] | None = None
    table: Mapping[str, tuple[int, int]] = field(default_factory=lambda: TIMER_MAX_INTERVAL_S)
    instance_intervals: Mapping[str, tuple[int, int]] = field(
        default_factory=lambda: TIMER_INSTANCE_INTERVAL_S
    )
    retired: Mapping[str, str] = field(default_factory=lambda: TIMER_RETIRED_BY_RULING)
    rows: Mapping[str, NotDeployedRow] = field(default_factory=lambda: NOT_YET_DEPLOYED)
    artifacts: Mapping[str, tuple[str, ...]] = field(default_factory=lambda: NOT_DEPLOYED_ARTIFACTS)
    critical_from: str = NOT_DEPLOYED_CRITICAL_FROM


def production_watch(data_root: Path) -> WatchWiring:
    return WatchWiring(
        data_root=data_root,
        producer=FileProducerSource(data_root),
        summary=journal_summary_reader(),
        node_log_tail=lambda: read_node_log_tail(data_root / "logs"),
        journal_evidence=journal_evidence_reader(),
    )


# --------------------------------------------------------------------------- evaluation

PRODUCER_TIMERS: Final = (INTRADAY_UNITS[1], DAILY_UNITS[1])
_EVIDENCE_CADENCE: Final = {
    **dict.fromkeys(INTRADAY_UNITS, "intraday"),
    **dict.fromkeys(DAILY_UNITS, "daily"),
}


class _Evidence:
    """Has an absent unit ever run? Files, verdict files and journal lines, each read once."""

    def __init__(self, wiring: WatchWiring, timeout_s: float) -> None:
        self.wiring = wiring
        self.timeout_s = timeout_s
        self.reasons: list[str] = []
        self._known: dict[str, bool] = {}
        self._cadences: frozenset[str] | None = None
        self._identifiers: dict[str, bool] = {}

    def _files(self, name: str) -> bool:
        for rel in self.wiring.artifacts.get(name, ()):
            try:
                os.lstat(self.wiring.data_root / rel)
            except FileNotFoundError:
                continue
            except OSError:
                return True  # unreadable: assume it exists, so an absent unit is a finding
            return True
        return False

    def _verdicts(self, name: str) -> bool:
        cadence = _EVIDENCE_CADENCE.get(name)
        if cadence is None:
            return False
        if self._cadences is None:
            try:
                reader = self.wiring.verdict_cadences
                self._cadences = (
                    reader() if reader is not None else scan_verdict_cadences(self.wiring.data_root)
                )
            except OSError:
                return True  # unreadable verdict root: fail closed, like the file artifacts
        return cadence in self._cadences

    def _journal(self, name: str) -> bool:
        reader = self.wiring.journal_evidence
        if reader is None or name not in _EVIDENCE_CADENCE:
            return False
        identifier = name.rsplit(".", 1)[0]
        if identifier not in self._identifiers:
            try:
                self._identifiers[identifier] = reader(identifier, self.timeout_s)
            except JournalError:
                self.reasons.append("journal_evidence_unreadable")
                self._identifiers[identifier] = False
        return self._identifiers[identifier]

    def __call__(self, name: str) -> bool:
        if name not in self.wiring.artifacts:
            return False
        if name not in self._known:
            self._known[name] = self._files(name) or self._verdicts(name) or self._journal(name)
        return self._known[name]


def inventory_of(observation: UnitObservation) -> Inventory:
    blocks = parse_show_blocks(observation.raw["units_show"])
    for name, block in observation.blocks.items():
        blocks.setdefault(name, block)
    return parse_inventory(
        observation.raw["units_inventory"], observation.raw["unit_files_inventory"], blocks
    )


def _enabled_since(inventory: Inventory, timer: str) -> int | None:
    readable, stamp = timestamp_or_zero(
        inventory.blocks.get(timer, {}).get("ActiveEnterTimestamp", "")
    )
    return stamp if readable else None


def _sightings(inventory: Inventory, first_seen: Mapping[str, int], now_ns: int) -> dict[str, int]:
    """The earliest known instant of each present producer timer: its stored first sighting, else
    its ``ActiveEnterTimestamp`` (or now). A restart moves the latter, never the former."""
    found: dict[str, int] = {}
    for timer in PRODUCER_TIMERS:
        if inventory.link_state(timer) != "present":
            continue
        entered = _enabled_since(inventory, timer)
        candidate = min(now_ns, entered) if entered is not None else now_ns
        found[timer] = min(first_seen.get(timer, candidate), candidate)
    return found


def _guarded(detector: str, run: Callable[[], DetectorResult]) -> DetectorResult:
    """One detector failing must not blind the others: its exception becomes a named reason."""
    try:
        return run()
    except Exception as exc:  # noqa: BLE001 - isolation is the point; the type is reported
        _LOG.error(
            "meta_detector_failed detector=%s exception_type=%s", detector, type(exc).__name__
        )
        return DetectorResult(
            detector,
            Outcome.INCONCLUSIVE,
            (),
            {},
            (f"detector_error:{detector}:{type(exc).__name__}",),
        )


def _resident(wiring: WatchWiring, inventory: Inventory) -> tuple[int, int] | None:
    """``(node, recorder)`` VmRSS in KiB. No process is a real zero; a process whose resident
    size cannot be read, or reads zero, is ``None`` (never 0), as is a failing lookup."""
    main_pid = inventory.blocks.get(RECORDER_UNIT, {}).get("MainPID", "")
    if not main_pid.isdigit():
        return None  # the recorder's block is missing or garbled
    try:
        node_pid = wiring.find_node_pid()
        node = 0 if node_pid is None else wiring.pid_rss_kib(node_pid)
        recorder = 0 if int(main_pid) == 0 else wiring.pid_rss_kib(int(main_pid))
    except OSError:
        return None
    if node is None or recorder is None:
        return None
    if (node_pid is not None and node == 0) or (int(main_pid) != 0 and recorder == 0):
        return None
    return node, recorder


def evaluate_watch(
    wiring: WatchWiring,
    observation: UnitObservation,
    *,
    now_ns: int,
    window: MemAvailWindow,
    summary_since_ns: int,
    summary_timeout_s: float,
    first_seen: Mapping[str, int] | None = None,
) -> WatchResult:
    today = day_of_ns(now_ns)
    inventory = inventory_of(observation)
    evidence = _Evidence(wiring, summary_timeout_s)

    def classify(name: str) -> Deployment:
        return classify_unit(
            name,
            inventory=inventory,
            rows=wiring.rows,
            has_artifacts=evidence,
            today=today,
            critical_from=wiring.critical_from,
        )

    listed: tuple[str, ...] = ()

    def run_timers() -> DetectorResult:
        nonlocal listed
        result, listed = evaluate_timers(
            deploy_dir=wiring.deploy_dir,
            inventory=inventory,
            table=wiring.table,
            instance_intervals=wiring.instance_intervals,
            retired=wiring.retired,
            classify=classify,
            extra_units=tuple(wiring.rows),
            now_ns=now_ns,
            today=today,
        )
        return result

    timers = _guarded(TIMER_DETECTOR, run_timers)
    states = {name: classify(name) for name in (*INTRADAY_UNITS, *DAILY_UNITS)}
    if evidence.reasons:
        extra = tuple(dict.fromkeys(evidence.reasons))
        timers = replace(timers, unknown_reasons=(*timers.unknown_reasons, *extra))
    not_deployed = set(listed)
    sightings = _sightings(inventory, first_seen or {}, now_ns)
    resident = _resident(wiring, inventory)
    results = [
        timers,
        _guarded(
            PRODUCER_DETECTOR,
            lambda: _producer_result(wiring, states, not_deployed, now_ns, today, sightings),
        ),
        _guarded(
            DAILY_DETECTOR,
            lambda: _daily_result(wiring, states, not_deployed, now_ns, today, sightings),
        ),
        _guarded(
            DELIVERY_DETECTOR,
            lambda: _delivery_result(
                wiring, inventory, now_ns, summary_since_ns, summary_timeout_s
            ),
        ),
        _guarded(
            MEMORY_DETECTOR,
            lambda: evaluate_memory(
                deploy_dir=wiring.deploy_dir,
                blocks=inventory.blocks,
                window=window,
                node_rss_kib=resident[0] if resident else None,
                recorder_rss_kib=resident[1] if resident else None,
                today=today,
            ),
        ),
    ]
    return WatchResult(tuple(results), tuple(sorted(not_deployed)), resident, sightings)


def _overdue(states: Mapping[str, Deployment], units: Sequence[str]) -> bool:
    return all(states[u].state == "finding" and states[u].kind == KIND_OVERDUE for u in units)


def _skipped_result(detector: str, reason: str) -> DetectorResult:
    return DetectorResult(detector, Outcome.INCONCLUSIVE, (), {"unknown_reason": reason})


def _producer_result(
    wiring: WatchWiring,
    states: Mapping[str, Deployment],
    not_deployed: set[str],
    now_ns: int,
    today: str,
    sightings: Mapping[str, int],
) -> DetectorResult:
    if all(u in not_deployed for u in INTRADAY_UNITS):
        return _skipped_result(PRODUCER_DETECTOR, "not_deployed")
    if _overdue(states, INTRADAY_UNITS):  # #28 already carries the overdue page
        return _skipped_result(PRODUCER_DETECTOR, "not_deployed_overdue")
    if wiring.producer is None:
        return DetectorResult(
            PRODUCER_DETECTOR, Outcome.INCONCLUSIVE, (), {}, ("producer_reader_unwired",)
        )
    return evaluate_producer(
        wiring.producer,
        now_ns=now_ns,
        today=today,
        enabled_since_ns=sightings.get(INTRADAY_UNITS[1]),
    )


def _daily_result(
    wiring: WatchWiring,
    states: Mapping[str, Deployment],
    not_deployed: set[str],
    now_ns: int,
    today: str,
    sightings: Mapping[str, int],
) -> DetectorResult:
    if all(u in not_deployed for u in DAILY_UNITS):
        return _skipped_result(DAILY_DETECTOR, "not_deployed")
    if _overdue(states, DAILY_UNITS):
        return _skipped_result(DAILY_DETECTOR, "not_deployed_overdue")
    if wiring.producer is None:
        return DetectorResult(
            DAILY_DETECTOR, Outcome.INCONCLUSIVE, (), {}, ("producer_reader_unwired",)
        )
    return evaluate_daily(
        wiring.producer,
        now_ns=now_ns,
        today=today,
        deployed_since_ns=sightings.get(DAILY_UNITS[1]),
    )


def unwired_without_row(rows: Mapping[str, NotDeployedRow], producer: object | None) -> list[str]:
    """Producers whose not-deployed rows are gone while their verdict reader is not wired.

    The rows are what stops #26/#27 reading a missing producer as healthy or as a FAIL; deleting
    them before the reader exists would blind both. Returns the cadences that would be blind.
    """
    blind: list[str] = []
    for cadence, units in (("intraday", INTRADAY_UNITS), ("daily", DAILY_UNITS)):
        if any(unit in rows for unit in units):
            continue
        if not getattr(producer, f"{cadence}_reader_wired", False):
            blind.append(cadence)
    return blind


def _delivery_result(
    wiring: WatchWiring,
    inventory: Inventory,
    now_ns: int,
    since_ns: int,
    timeout_s: float,
) -> DetectorResult:
    lines: Sequence[str] | None
    if wiring.summary is None:
        lines = None
    else:
        try:
            lines = wiring.summary(since_ns, timeout_s)
        except JournalError:
            lines = None
    tail = wiring.node_log_tail() if wiring.node_log_tail is not None else None
    options: dict[str, object] = {}
    if wiring.free_bytes is not None:
        options["free_bytes"] = wiring.free_bytes
    return evaluate_delivery(
        DeliveryInputs(
            alerts_root=wiring.data_root / "evidence" / "alerts",
            now_ns=now_ns,
            canary_since_ns=_enabled_since(inventory, CANARY_TIMER),
            summary_lines=lines,
            node_log_tail=tail,
            access=wiring.access,
            **options,  # type: ignore[arg-type]
        )
    )
