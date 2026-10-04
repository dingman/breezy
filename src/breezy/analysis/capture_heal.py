"""AUT-1 WP5 stage 3 S1: the recorder heal planner (design r3 D6, D7; plan r12 3.10.3, 3.11.6).

Pure: it turns the recorder's watchdog kills (journal ``UNIT_RESULT=watchdog`` entries) and the
restart evidence into the heal records the audit writes, and it holds the date and age rules of the
heal and gap alert re-send. Nothing here reads a file or a clock; ``capture_heal_io`` does.

A watchdog kill at ``t`` is **healed** only when all three hold, on the fresh post-lock clock:

* a later invocation of the recorder started: the FIRST later invocation whose
  ``TradingNode: instance_id: <id>`` line (ANSI codes and timestamp prefix stripped, and never the
  ``config.use_instance_id=`` decoy) names an instance that has a ``live/<id>/config.json`` (S3-R5,
  S3-R33). Matching is by that id, never by a time window;
* ``now >= restart + 1800 s``, and the instance grew for at least 900 s (S3-R4, S3-R32);
* no further watchdog kill came within 1800 s of the restart.

A kill with no stall record gets no heal: leg W carries it (S3-R46). The two budget constants are
FROZEN by 3a: S3 pins them against the unit budget (S3-R42, S3-R49).
"""

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from breezy.analysis.capture_audit_input_types import RecorderJournalEntry

__all__ = [
    "HEAL_ABANDON_DAYS",
    "HEAL_ALERT_RETRY_DAYS",
    "HEAL_BUDGET_S",
    "HEAL_JOURNAL_DAYS",
    "MIN_GROWTH_S",
    "NODE_RESEND_MIN_AGE_S",
    "RECORDER_UNIT",
    "RESTART_MIN_AGE_S",
    "SECOND_KILL_WINDOW_S",
    "HealPlan",
    "InstanceEvidence",
    "InstanceLine",
    "alert_phase",
    "gap_key",
    "heal_body",
    "heal_record_matches",
    "instance_lines",
    "node_record_resendable",
    "plan_heals",
]

#: The wall-clock budget of one heal duty (S3-R29). It is bounded below by the journal reads and
#: above by the audit work budget left after a full lock wait:
#: ``HEAL_JOURNAL_DAYS * JOURNAL_TIMEOUT_S + 30 <= HEAL_BUDGET_S``
#: ``<= AUDIT_EXEC_TIMEOUT_S - 60 - 600``.
HEAL_BUDGET_S: Final[int] = 180
#: How many UTC days of the recorder journal one heal run reads, one day at a time (S3-R3).
HEAL_JOURNAL_DAYS: Final[int] = 3

RECORDER_UNIT: Final[str] = "breezy-quote-tape.service"
#: ``HEAL_ALERT_RETRY_DAYS`` dates are re-sent daily; heal dates up to ``HEAL_ABANDON_DAYS`` old are
#: abandoned (r8 X1); an unmarked one older than that is aged out (r8-final LOW).
HEAL_ALERT_RETRY_DAYS: Final[int] = 8
HEAL_ABANDON_DAYS: Final[int] = 30
NODE_RESEND_MIN_AGE_S: Final[int] = 600
RESTART_MIN_AGE_S: Final[int] = 1800
MIN_GROWTH_S: Final[int] = 900
SECOND_KILL_WINDOW_S: Final[int] = 1800

_NS: Final[int] = 1_000_000_000
_US_NS: Final[int] = 1_000
_ANSI_RE: Final[re.Pattern[str]] = re.compile(r"\x1b\[[0-9;]*m")
#: The node-census id character set (``capture_node_log_decisions._INSTANCE_MSG_RE``). Anchored on
#: ``TradingNode:`` so the ``MessageBus: config.use_instance_id=False`` line beside it never does.
_INSTANCE_RE: Final[re.Pattern[str]] = re.compile(
    r"\A(?:\d{4}-\d\d-\d\dT[0-9:.]+Z )?(?:\[[A-Z]+\] )?(?:[\w-]+\.)?TradingNode: "
    r"instance_id: (?P<id>[0-9A-Za-z-]{8,64})\s*\Z"
)
_SHA_RE: Final[re.Pattern[str]] = re.compile(r"\A[0-9a-f]{64}\Z")


@dataclass(frozen=True, slots=True)
class InstanceLine:
    """One recorder ``TradingNode: instance_id:`` log line: the start of ``invocation_id``."""

    ts_ns: int
    invocation_id: str
    instance_id: str


@dataclass(frozen=True, slots=True)
class InstanceEvidence:
    """What the instance's ``live/<id>/`` directory shows: whether it holds ``config.json`` and how
    long it kept growing (the newest non-dot entry's mtime minus the ``config.json`` mtime)."""

    has_config: bool
    growth_ns: int


@dataclass(frozen=True, slots=True)
class HealPlan:
    """A confirmed heal: the kill, the restart that healed it and the stall record's sha."""

    kill: RecorderJournalEntry
    restart: InstanceLine
    observation_sha256: str


def _message(raw: object) -> str:
    if isinstance(raw, str):
        text = raw
    elif isinstance(raw, list) and all(isinstance(b, int) and 0 <= b < 256 for b in raw):
        text = bytes(raw).decode("utf-8", "replace")
    else:
        return ""
    return _ANSI_RE.sub("", text)


def _micros_ns(entry: Mapping[str, Any], key: str) -> int | None:
    value = entry.get(key)
    return int(value) * _US_NS if isinstance(value, str) and value.isdigit() else None


def instance_lines(text: str) -> tuple[InstanceLine, ...]:
    """The recorder's ``TradingNode: instance_id:`` lines in a ``-o json`` journal, in time order.
    A ``MESSAGE`` may be a byte array with ANSI codes (the journal stores a coloured line so)."""
    found: list[InstanceLine] = []
    for raw in text.splitlines():
        try:
            entry = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(entry, dict):
            continue
        match = _INSTANCE_RE.fullmatch(_message(entry.get("MESSAGE")))
        ts_ns = _micros_ns(entry, "__REALTIME_TIMESTAMP")
        invocation = entry.get("_SYSTEMD_INVOCATION_ID", entry.get("INVOCATION_ID"))
        if match is None or ts_ns is None or not isinstance(invocation, str) or not invocation:
            continue
        found.append(InstanceLine(ts_ns, invocation, match["id"]))
    return tuple(sorted(found, key=lambda line: (line.ts_ns, line.invocation_id)))


def _first_restart(
    kill: RecorderJournalEntry,
    lines: Sequence[InstanceLine],
    evidence: Mapping[str, InstanceEvidence],
) -> InstanceLine | None:
    """The FIRST later invocation (by its instance line) whose instance has a ``config.json``."""
    for line in sorted(lines, key=lambda x: (x.ts_ns, x.invocation_id)):
        if line.ts_ns <= kill.ts_ns or line.invocation_id == kill.invocation_id:
            continue
        seen = evidence.get(line.instance_id)
        if seen is not None and seen.has_config:
            return line
    return None


def _confirmed(
    kill: RecorderJournalEntry,
    restart: InstanceLine,
    kills: Sequence[RecorderJournalEntry],
    evidence: InstanceEvidence,
    now_ns: int,
) -> bool:
    if now_ns < restart.ts_ns + RESTART_MIN_AGE_S * _NS:
        return False
    if evidence.growth_ns < MIN_GROWTH_S * _NS:
        return False
    horizon = restart.ts_ns + SECOND_KILL_WINDOW_S * _NS
    return not any(other != kill and kill.ts_ns < other.ts_ns <= horizon for other in kills)


def plan_heals(
    kills: Sequence[RecorderJournalEntry],
    lines: Sequence[InstanceLine],
    stall_sha: Mapping[str, str],
    evidence: Mapping[str, InstanceEvidence],
    now_ns: int,
) -> tuple[HealPlan, ...]:
    """The heals confirmed at ``now_ns``. ``stall_sha`` is ``invocation_id -> observation_sha256``
    of the hook's stall records: a kill without one is not healed here (leg W carries it)."""
    watchdog = tuple(k for k in kills if k.unit_result == "watchdog")
    plans: list[HealPlan] = []
    for kill in watchdog:
        sha = stall_sha.get(kill.invocation_id, "")
        if _SHA_RE.fullmatch(sha) is None:
            continue
        restart = _first_restart(kill, lines, evidence)
        if restart is None or not _confirmed(
            kill, restart, watchdog, evidence[restart.instance_id], now_ns
        ):
            continue
        plans.append(HealPlan(kill, restart, sha))
    return tuple(plans)


def heal_body(plan: HealPlan, *, injected: bool) -> dict[str, Any]:
    """The heal record body. Everything but ``injected`` comes from the journal and the stall
    record, so a rerun rebuilds the same bytes; ``injected`` is read at first write only."""
    return {
        "cause": "watchdog",
        "decided_by": "systemd_watchdog",
        "detected_ns": plan.kill.ts_ns,
        "healed_ns": plan.restart.ts_ns,
        "injected": injected,
        "instance_id": plan.restart.instance_id,
        "invocation_id": plan.kill.invocation_id,
        "observation_sha256": plan.observation_sha256,
        "unit": RECORDER_UNIT,
        "unit_result": plan.kill.unit_result,
    }


def heal_record_matches(body: Mapping[str, Any], plan: HealPlan) -> bool:
    """Whether an existing record carries ``plan``'s invariant fields (never ``injected``)."""
    keys = ("decided_by", "invocation_id", "observation_sha256", "unit_result")
    want = heal_body(plan, injected=False)
    return all(body.get(key) == want[key] for key in keys)


def gap_key(invocation_id: str) -> str:
    """The abandon key of a leg-W gap: ``sha256(unit NUL InvocationID)`` (S3-R7)."""
    return hashlib.sha256(f"{RECORDER_UNIT}\0{invocation_id}".encode()).hexdigest()


def alert_phase(age_days: int) -> str:
    """Which re-send rule a heal or gap ``age_days`` old (today minus its date) is under:
    ``retry`` (daily), ``abandon`` (send the abandon alert, then the marker), or ``aged`` (loud
    ``CAPTURE_HEAL_UNABANDONED`` line); a future date is ``future``."""
    if age_days < 0:
        return "future"
    if age_days < HEAL_ALERT_RETRY_DAYS:
        return "retry"
    if age_days <= HEAL_ABANDON_DAYS:
        return "abandon"
    return "aged"


def node_record_resendable(record_ns: int, now_ns: int) -> bool:
    """A node (NBP actor) record is re-sent only once it is older than 600 s: the actor offers its
    own alert at the heal and may still be delivering it."""
    return now_ns - record_ns >= NODE_RESEND_MIN_AGE_S * _NS
