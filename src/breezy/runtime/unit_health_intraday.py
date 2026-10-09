"""Intraday-stage classification of the AUT-6 health pass (plan r15 section 3.4.2; WP3 S4).

The intraday producer unit runs two stages in one invocation: an evaluate stage (an ignored
``ExecStart=-`` line) and a demand stage. systemd records nothing for an ignored exit, so the
health pass reads each stage's own journal lines and the last ``ExecStart`` exit entry:

* the demand row of the section 3.4.2 table (exit status of the last command against the
  ``PRODUCER_INTRADAY_DEMAND`` lines);
* the evaluate outcome, independently of the demand row (AC2);
* only ended invocations are judged (AE4), so the overlapping ``*:01`` pass never pages the run
  that started at ``*:00``;
* episode dedupe (AB7, LOW-r11-2/4, LOW-r12-1/2, AG3) for the three findings that repeat every
  5 minutes while their cause stands.

Until WP6 ships the producer unit this module judges nothing in production: no intraday unit in
the snapshot means no finding and no journal read. The tests use fixtures.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from breezy.runtime.unit_health_daemon_support import (
    EVENT_BWRAP_UNAVAILABLE,
    EVENT_DEMAND_DEADLINE,
    EVENT_DEMAND_FAILED,
    EVENT_DEMAND_INTEGRITY,
    EVENT_DEMAND_TIMEOUT,
    EVENT_EVAL_FAILED,
    EVENT_EVAL_TIMEOUT,
    EVENT_EVAL_UNRECORDED,
    MSG_EXIT,
    MSG_FAILED,
    MSG_STARTED,
    DaemonWiring,
    PassHost,
    UnitEntry,
)
from breezy.runtime.unit_health_store import (
    NS,
    day_of_ns,
    finding_site,
    read_json,
    safe_key,
)

INTRADAY_UNIT: Final = "breezy-autonomy-producer-intraday.service"
#: The summed stage bounds 102 + 1 + 17 plus ``TimeoutStartSec`` slack 5 (plan section 3.10).
INTRADAY_INVOCATION_MAX_S: Final = 125
EVALUATE_STAGE_BUDGET_S: Final = 100
EXIT_INTEGRITY: Final = 3
EXIT_EVALUATE_FAILED: Final = 4
EXIT_DEMAND_DEADLINE: Final = 5
TIMEOUT_EXITS: Final = frozenset({124, 137})
FIRST_LOOKBACK_S: Final = 900
JUDGED_KEPT: Final = 64
EPISODE_REPAGE_S: Final = 86_400
EPISODE_FINDINGS: Final = (EVENT_BWRAP_UNAVAILABLE, EVENT_DEMAND_TIMEOUT, EVENT_DEMAND_DEADLINE)
EPISODE_SCHEMA: Final = "intraday_episode/v1"
EPISODE_PREFIX: Final = "_intraday_episode_"
STAGE_EPISODE_SCHEMA: Final = "demand_stage_episode/v1"
STAGE_EPISODE_FILE: Final = f"episodes/{EVENT_DEMAND_DEADLINE}.json"
DELIVERY_SCHEMA: Final = "alert_delivery/v1"
INTRADAY_SEEN_KEY: Final = "intraday"

_US: Final = 1_000_000
_EVAL_START: Final = "PRODUCER_INTRADAY START"
_EVAL_PREFIX: Final = "PRODUCER_INTRADAY "
_DEMAND_START: Final = "PRODUCER_INTRADAY_DEMAND START"
_DEMAND_PREFIX: Final = "PRODUCER_INTRADAY_DEMAND "
_SKIPPED: Final = "PRODUCER_INTRADAY SKIPPED"
_PAIR_RE: Final = re.compile(r"(\w+)=(\S+)")
_RECORD_RE: Final = re.compile(r"\d+_[a-z0-9_]{1,64}_d\.json")
_COUNTERS: Final = (
    "integrity_demand_write_failures",
    "journal_write_failures",
    "outbox_write_failures",
)
_DAY_S: Final = 86_400


@dataclass(frozen=True, slots=True)
class StageFinding:
    finding: str
    metrics: Mapping[str, str] = field(default_factory=dict)
    #: ``False`` for a finding the stage already paged itself (recorded, not paged again).
    page: bool = True


@dataclass(frozen=True, slots=True)
class InvocationJudgment:
    invocation_id: str
    first_us: int
    last_us: int
    findings: tuple[StageFinding, ...]


# --------------------------------------------------------------------------- line parsing


def _pairs(message: str) -> dict[str, str]:
    return dict(_PAIR_RE.findall(message))


def _is_eval_summary(message: str) -> bool:
    return message.startswith(_EVAL_PREFIX) and not message.startswith(_EVAL_START)


def _is_demand_summary(message: str) -> bool:
    return (
        message.startswith(_DEMAND_PREFIX)
        and not message.startswith(_DEMAND_START)
        and "exit=" in message
    )


def _eval_exit(message: str) -> int | None:
    """The evaluate summary's exit code; a ``SKIPPED lock_held`` line counts as ``exit=0``."""
    if message.startswith(_SKIPPED):
        return 0
    value = _pairs(message).get("exit", "")
    return int(value) if value.isdigit() else None


def _last(entries: Sequence[UnitEntry]) -> UnitEntry | None:
    return entries[-1] if entries else None


def _exit_status(entries: Sequence[UnitEntry]) -> tuple[int | None, int]:
    """The status of the last ``ExecStart`` exit entry by timestamp, and how many there were."""
    exits = [
        e for e in entries if e.message_id == MSG_EXIT and e.fields.get("COMMAND") == "ExecStart"
    ]
    if not exits:
        return None, 0
    newest = max(range(len(exits)), key=lambda i: (exits[i].ts_us, i))
    raw = exits[newest].fields.get("EXIT_STATUS", "")
    return (int(raw) if raw.isdigit() else None), len(exits)


def demand_summary_counters(entries: Sequence[UnitEntry]) -> dict[str, int] | None:
    """The write-failure counters of the demand stage's summary line (the input of #23).

    ``None`` when the invocation has no demand summary: the caller treats that as unrecorded,
    never as zero failures.
    """
    summary = _last([e for e in entries if _is_demand_summary(e.message)])
    if summary is None:
        return None
    pairs = _pairs(summary.message)
    if not all(pairs.get(k, "").isdigit() for k in _COUNTERS):
        return None
    return {k: int(pairs[k]) for k in _COUNTERS}


# --------------------------------------------------------------------------- the judgment


def _ended(entries: Sequence[UnitEntry], now_us: int, current_activating: bool) -> bool:
    """AE4: ended by (a) an exit, unit-failed or job-completion entry, (b) age, or (c) state."""
    if any(e.message_id in {MSG_EXIT, MSG_FAILED, MSG_STARTED} for e in entries):
        return True
    newest = max(e.ts_us for e in entries)
    if now_us - newest > INTRADAY_INVOCATION_MAX_S * _US:
        return True
    return not current_activating


def _demand_row(
    status: int | None,
    summary: Mapping[str, str] | None,
    *,
    demand_started: bool,
    bwrap: bool,
    extra: Mapping[str, str],
) -> StageFinding | None:
    if status in {None, 0}:
        return None
    if status == EXIT_INTEGRITY and summary is not None:
        return StageFinding(EVENT_DEMAND_INTEGRITY, dict(extra), page=False)
    if (
        status == EXIT_DEMAND_DEADLINE
        and summary is not None
        and summary.get("deadline_hit") == "1"
    ):
        return StageFinding(
            EVENT_DEMAND_DEADLINE, {**extra, "unprocessed": summary.get("unprocessed", "")}
        )
    if status == EXIT_EVALUATE_FAILED and summary is not None:
        return None  # the evaluate rule reports the cause
    metrics = {**extra, "exit_status": str(status)}
    if summary is not None:
        return StageFinding(EVENT_DEMAND_FAILED, metrics)
    if status in TIMEOUT_EXITS:
        return StageFinding(EVENT_DEMAND_TIMEOUT, metrics)
    if not demand_started:
        hint = "bwrap_launch" if bwrap else "unknown"
        return StageFinding(EVENT_BWRAP_UNAVAILABLE, {**metrics, "cause_hint": hint})
    return StageFinding(EVENT_DEMAND_FAILED, {**metrics, "cause_hint": "interpreter_or_import"})


def _evaluate_rule(
    entries: Sequence[UnitEntry], summary: Mapping[str, str] | None, bwrap: bool
) -> StageFinding | None:
    """The evaluate outcome from the stage's own lines, cross-checked with the demand line."""
    eval_summary = _last([e for e in entries if _is_eval_summary(e.message)])
    demand_eval = (summary or {}).get("evaluate_exit")
    if eval_summary is not None:
        code = _eval_exit(eval_summary.message)
        if code is None:
            return StageFinding(EVENT_EVAL_UNRECORDED)
        if code != 0:
            return StageFinding(EVENT_EVAL_FAILED, {"evaluate_exit": str(code)})
        if demand_eval not in {None, "0"}:
            return StageFinding(EVENT_EVAL_UNRECORDED, {"demand_evaluate_exit": str(demand_eval)})
        return None
    start = next((e for e in entries if e.message.startswith(_EVAL_START)), None)
    if start is None:
        hint = {"cause_hint": "bwrap_launch"} if bwrap else {}
        return StageFinding(EVENT_EVAL_UNRECORDED, hint)
    demand_start = next((e for e in entries if e.message.startswith(_DEMAND_START)), None)
    end_us = demand_start.ts_us if demand_start is not None else max(e.ts_us for e in entries)
    if end_us - start.ts_us >= EVALUATE_STAGE_BUDGET_S * _US:
        return StageFinding(EVENT_EVAL_TIMEOUT)
    return StageFinding(EVENT_EVAL_UNRECORDED)


def judge_invocation(
    entries: Sequence[UnitEntry], *, now_us: int, current_activating: bool
) -> InvocationJudgment | None:
    """The findings of one intraday invocation, or ``None`` while it has not ended (AE4)."""
    if not entries or not _ended(entries, now_us, current_activating):
        return None
    demand_summary_entry = _last([e for e in entries if _is_demand_summary(e.message)])
    summary = _pairs(demand_summary_entry.message) if demand_summary_entry is not None else None
    status, count = _exit_status(entries)
    if status is None and summary is not None and summary.get("exit", "").isdigit():
        status = int(summary["exit"])
    extra = {"exit_entries": str(count)} if count > 1 else {}
    bwrap = any(e.message.startswith("bwrap:") for e in entries)
    demand_started = any(e.message.startswith(_DEMAND_START) for e in entries)
    found = (
        _demand_row(status, summary, demand_started=demand_started, bwrap=bwrap, extra=extra),
        _evaluate_rule(entries, summary, bwrap),
    )
    return InvocationJudgment(
        entries[0].invocation_id,
        min(e.ts_us for e in entries),
        max(e.ts_us for e in entries),
        tuple(f for f in found if f is not None),
    )


# --------------------------------------------------------------------------- stage records


@dataclass(frozen=True, slots=True)
class DeliveredRecord:
    ts_ns: int
    event: str
    site: str


def _int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def read_stage_episode(alerts_root: Path) -> dict[str, Any] | None:
    """The demand stage's own episode record, or ``None`` when absent, unreadable, ``reset`` or
    without a queued entry (fail closed: the caller pages)."""
    body = read_json(alerts_root / STAGE_EPISODE_FILE)
    if body is None or body.get("schema") != STAGE_EPISODE_SCHEMA or body.get("state") == "reset":
        return None
    entry = body.get("outbox_entry")
    if not (isinstance(entry, str) and entry) or _int(body.get("last_queued_ns")) is None:
        return None
    return body


def find_delivered(
    alerts_root: Path, entry: str, *, min_ts_ns: int, now_ns: int
) -> DeliveredRecord | None:
    """A ``delivered=true`` record of ``entry`` (by basename) at or after ``min_ts_ns`` (AG3)."""
    name = os.path.basename(entry)
    first, last = min_ts_ns // NS // _DAY_S, now_ns // NS // _DAY_S
    for day_index in range(first, last + 1):
        directory = alerts_root / day_of_ns(day_index * _DAY_S * NS)
        try:
            names = sorted(os.listdir(directory))
        except OSError:
            continue
        for fname in names:
            if not _RECORD_RE.fullmatch(fname):
                continue
            body = read_json(directory / fname)
            ts = _int(body.get("ts_ns")) if body else None
            if (
                body is not None
                and ts is not None
                and ts >= min_ts_ns
                and body.get("schema") == DELIVERY_SCHEMA
                and body.get("delivered") is True
                and os.path.basename(str(body.get("outbox_entry", ""))) == name
                and isinstance(body.get("event"), str)
                and isinstance(body.get("site"), str)
            ):
                return DeliveredRecord(ts, body["event"], body["site"])
    return None


# --------------------------------------------------------------------------- the pass rules


class _Rules:
    def __init__(self, host: PassHost, wiring: DaemonWiring) -> None:
        self.host = host
        self.wiring = wiring
        store_root: Path = host.store.root
        self.alerts_root = wiring.alerts_root or store_root.parent / "alerts"
        self.episodes: dict[str, dict[str, Any]] = {}

    # ---- episode state

    def episode(self, finding: str) -> dict[str, Any] | None:
        if finding not in self.episodes:
            body = self.host.store.read_seen(EPISODE_PREFIX + finding)
            ok = body is not None and body.get("schema") == EPISODE_SCHEMA
            if body is not None and ok:
                self.episodes[finding] = body
        return self.episodes.get(finding)

    def save(self, finding: str, body: dict[str, Any]) -> None:
        self.episodes[finding] = body
        self.host.store.write_seen(EPISODE_PREFIX + finding, body)

    def refresh(self, finding: str, ep: dict[str, Any]) -> None:
        """Learn that the episode's page was delivered; bind the demand stage's own page (AG3)."""
        cite = ep.get("cite")
        if (
            isinstance(cite, dict)
            and ep.get("last_paged_ns") is None
            and self.host.env.delivered(cite["event"], cite["site"])
        ):
            ep["last_paged_ns"] = self.host.now
        if finding != EVENT_DEMAND_DEADLINE or ep.get("last_paged_ns") is not None:
            return
        stage = read_stage_episode(self.alerts_root)
        if stage is None:
            return
        found = find_delivered(
            self.alerts_root,
            stage["outbox_entry"],
            min_ts_ns=int(ep["first_ns"]),
            now_ns=self.host.now,
        )
        if found is None:
            return
        ep["last_paged_ns"] = found.ts_ns
        ep["cite"] = {"event": found.event, "site": found.site}
        for item in ep.get("pending", []):
            self.cite(finding, item["invocation_id"], item["metrics"], ep["cite"])
        ep["pending"] = []

    def stage_pending(self, ep: dict[str, Any]) -> bool:
        """The stage queued this episode's page and it is neither delivered nor abandoned."""
        stage = read_stage_episode(self.alerts_root)
        if stage is None:
            return False
        queued = int(stage["last_queued_ns"])
        return queued >= int(ep["first_ns"]) and self.host.now - queued < _DAY_S * NS

    # ---- records

    def cite(
        self, finding: str, invocation: str, metrics: Mapping[str, str], cite: Mapping[str, str]
    ) -> None:
        self.host.commit_cited_finding(
            finding,
            INTRADAY_UNIT,
            f"{finding}-{invocation}",
            "CRITICAL",
            cite["event"],
            cite["site"],
            {"metrics": dict(metrics), "invocation_id": invocation},
        )

    def page(self, finding: str, invocation: str, metrics: Mapping[str, str]) -> None:
        key = f"{finding}-{invocation}"
        detail = f"unit={INTRADAY_UNIT} invocation={invocation} finding={finding}" + "".join(
            f" {k}={v}" for k, v in sorted(metrics.items())
        )
        self.host.commit_finding(
            finding,
            INTRADAY_UNIT,
            key,
            "CRITICAL",
            detail,
            {"metrics": dict(metrics), "invocation_id": invocation},
        )

    # ---- one judged invocation

    def hit(self, finding: str, verdict: InvocationJudgment, metrics: Mapping[str, str]) -> None:
        invocation = verdict.invocation_id
        ep = self.episode(finding)
        if ep is None or ep.get("state") != "active":
            ep = {
                "schema": EPISODE_SCHEMA,
                "state": "active",
                "first_ns": verdict.first_us * 1000,
                "last_paged_ns": None,
                "last_invocation_id": invocation,
                "cite": None,
                "pending": [],
            }
        ep["last_invocation_id"] = invocation
        self.refresh(finding, ep)
        last_paged = ep.get("last_paged_ns")
        in_flight = ep.get("cite") is not None and ep.get("paged_pass_ns") == self.host.now
        if (
            last_paged is not None and self.host.now - int(last_paged) < EPISODE_REPAGE_S * NS
        ) or in_flight:
            self.cite(finding, invocation, metrics, ep["cite"])
        elif finding == EVENT_DEMAND_DEADLINE and self.stage_pending(ep):
            pending = ep.setdefault("pending", [])
            if all(p["invocation_id"] != invocation for p in pending):
                pending.append({"invocation_id": invocation, "metrics": dict(metrics)})
        else:
            self.page(finding, invocation, metrics)
            ep["cite"] = {
                "event": finding,
                "site": finding_site(finding, INTRADAY_UNIT, f"{finding}-{invocation}"),
            }
            ep["last_paged_ns"] = None
            ep["paged_pass_ns"] = self.host.now
        self.save(finding, ep)

    def end_episode(self, finding: str) -> None:
        ep = self.episode(finding)
        if ep is not None and ep.get("state") == "active":
            self.save(finding, {**ep, "state": "ended", "ended_ns": self.host.now})

    def already_done(self, finding: str, invocation: str) -> bool:
        if self.host.store.has_action(INTRADAY_UNIT, safe_key(f"{finding}-{invocation}")):
            return True
        ep = self.episode(finding)
        if ep is None:
            return False
        return any(p["invocation_id"] == invocation for p in ep.get("pending", []))

    def settle(self) -> None:
        """Bind stage pages delivered since the pass that left them pending (LOW-r12-2)."""
        ep = self.episode(EVENT_DEMAND_DEADLINE)
        if ep is None or ep.get("state") != "active" or not ep.get("pending"):
            return
        self.refresh(EVENT_DEMAND_DEADLINE, ep)
        self.save(EVENT_DEMAND_DEADLINE, ep)

    def apply(self, verdict: InvocationJudgment) -> None:
        invocation = verdict.invocation_id
        names = {f.finding for f in verdict.findings}
        for f in verdict.findings:
            if self.already_done(f.finding, invocation):
                continue
            self.host.scan.days.add(self.host.today)
            if f.finding in EPISODE_FINDINGS:
                self.hit(f.finding, verdict, f.metrics)
            elif not f.page:
                self.host.commit_finding(
                    f.finding,
                    INTRADAY_UNIT,
                    f"{f.finding}-{invocation}",
                    "CRITICAL",
                    "",
                    {"metrics": dict(f.metrics), "invocation_id": invocation},
                    page=False,
                )
            else:
                self.page(f.finding, invocation, f.metrics)
        for finding in EPISODE_FINDINGS:
            if finding not in names:
                self.end_episode(finding)


def _group(entries: Sequence[UnitEntry]) -> dict[str, list[UnitEntry]]:
    groups: dict[str, list[UnitEntry]] = {}
    for e in entries:
        if e.invocation_id:
            groups.setdefault(e.invocation_id, []).append(e)
    return groups


def run_intraday_rules(host: PassHost, observation: Any, wiring: DaemonWiring) -> None:
    """Judge the ended intraday invocations since the previous pass; nothing without the unit."""
    block = observation.blocks.get(INTRADAY_UNIT)
    if block is None:
        return
    rules = _Rules(host, wiring)
    rules.settle()
    journal = wiring.journal
    prior = (host.store.read_seen(INTRADAY_UNIT) or {}).get(INTRADAY_SEEN_KEY)
    prior = prior if isinstance(prior, dict) else {}
    last_pass = _int(prior.get("pass_ns"))
    judged = [i for i in prior.get("judged", []) if isinstance(i, str)]
    now_us = host.now // 1000
    since_us = (
        last_pass // 1000 - INTRADAY_INVOCATION_MAX_S * _US
        if last_pass is not None
        else now_us - FIRST_LOOKBACK_S * _US
    )
    window = journal.unit_entries(
        INTRADAY_UNIT,
        since_us=since_us,
        until_us=now_us,
        lifecycle_only=False,
        timeout_s=host.allowance(),
    )
    current, activating = block.get("InvocationID", ""), block.get("ActiveState") == "activating"
    groups = _group(window)
    for invocation in sorted(groups, key=lambda i: min(e.ts_us for e in groups[i])):
        host.check_budget()
        if invocation in judged:
            continue
        in_flight = invocation == current and activating
        if (
            judge_invocation(groups[invocation], now_us=now_us, current_activating=in_flight)
            is None
        ):
            continue
        full = journal.invocation_entries(
            INTRADAY_UNIT, invocation, lifecycle_only=False, timeout_s=host.allowance()
        )
        verdict = judge_invocation(full, now_us=now_us, current_activating=in_flight)
        if verdict is None:
            continue
        rules.apply(verdict)
        judged.append(invocation)
    host.scan.daemon_seen.setdefault(INTRADAY_UNIT, {})[INTRADAY_SEEN_KEY] = {
        "pass_ns": host.now,
        "judged": judged[-JUDGED_KEPT:],
    }


__all__ = [
    "EPISODE_FINDINGS",
    "EVALUATE_STAGE_BUDGET_S",
    "INTRADAY_INVOCATION_MAX_S",
    "INTRADAY_UNIT",
    "InvocationJudgment",
    "StageFinding",
    "demand_summary_counters",
    "find_delivered",
    "judge_invocation",
    "read_stage_episode",
    "run_intraday_rules",
]
