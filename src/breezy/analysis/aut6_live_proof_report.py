"""AUT-6 WP9: the live-proof evaluator (plan r15 sections 6 and 7 (f), WP9; X-7; R-22).

Pure: ``evaluate_live_proof`` reads a ``ProofInputs`` of already-parsed evidence and returns the
report document. It touches no file, store, outbox or clock; ``aut6_live_proof_inputs`` loads the
evidence and writes the artefact.

Rules fixed here where the plan leaves room:

* **Window.** Complete days only (``asof`` is still running), from the day after the AUT-5b ruling
  and after the ING-2-AMEND2 landing. A failed day (section 6) restarts the run. A healthy day
  with no fill is neutral, as in AUT-1's roll-up: it neither counts nor breaks, so zero-fill days
  extend the window. A healthy day with only canary or drill fills qualifies and adds no real fill.
* **Rollup freshness.** Passes run every 10 minutes, so a day's final rollup is written up to one
  interval before midnight. "Produced before the day ended" therefore means older than
  ``ROLLUP_FINAL_GRACE_S`` before the day's end: a mid-day snapshot, not the last pass.
* **Missing evidence fails.** A malformed counter, an absent rollup or an unknown halt-key count
  never reads as healthy.
* **Verdict.** ``PROVEN`` means the whole section 6 protocol is met: evidence class "machinery
  proven, edge unproven". Anything less is ``NOT_YET`` with named blockers (X-7).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Final

__all__ = [
    "ACTION_CLASSES",
    "REPORT_SCHEMA",
    "DeliveryFact",
    "FillFact",
    "ProofInputs",
    "RestartFact",
    "VetoFact",
    "evaluate_live_proof",
]

REPORT_SCHEMA: Final = "aut6_live_proof/v1"
EVIDENCE_CLASS: Final = "machinery proven, edge unproven"
NS: Final = 1_000_000_000
WINDOW_DAYS: Final = 7
MIN_REAL_FILLS: Final = 5
MIN_PASSES_COMPLETED: Final = 130
MAX_PASSES_UNKNOWN: Final = 6
UNKNOWN_STREAK_PAGE_AT: Final = 3
PERMIT_VETO_WITHIN_NS: Final = 120 * NS
ROLLUP_FINAL_GRACE_S: Final = 1200
ACTION_CLASSES: Final = ("ENTRY_VETO", "ALERT", "SELF_HEAL", "DEMOTE", "HALT")
RECORDER_UNITS: Final = frozenset({"breezy-quote-tape", "breezy-quote-tape.service"})
MONITOR_STALE_DETECTOR: Final = "aut6.health_monitor_stale"
LIVE_SOURCE: Final = "live"
DEMOTE_VERDICT: Final = "DRILL_INJECT"
HALT_VERDICT: Final = "DRILL_INJECT_HALT"
DEMOTE_VETO: Final = "registry_not_champion"
HALT_VETO: Final = "registry_halted"


@dataclass(frozen=True, slots=True)
class FillFact:
    day: str
    source: str
    drill: bool = False
    ref: str = ""


@dataclass(frozen=True, slots=True)
class DeliveryFact:
    """One ``alert_delivery/v1`` record under ``evidence/alerts/<day>/``."""

    day: str
    name: str
    body: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class VetoFact:
    ts_ns: int
    reason: str
    ref: str = ""
    drill: bool = False


@dataclass(frozen=True, slots=True)
class RestartFact:
    """A watchdog ending of a unit with its #21 verdict and delivery evidence."""

    unit: str
    invocation_id: str
    unit_result: str
    injected: bool
    verdict_id: str
    notifier_delivered: bool
    fallback_page_delivered: bool
    ts_ns: int


@dataclass(frozen=True, slots=True)
class ProofInputs:
    asof: str
    aut5b_ruling_date: str | None = None
    ing2_amend2_landed_date: str | None = None
    rollups: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    fills: tuple[FillFact, ...] = ()
    deliveries: tuple[DeliveryFact, ...] = ()
    permit_expiries_ns: tuple[int, ...] = ()
    entry_vetos: tuple[VetoFact, ...] = ()
    node_log_vetos: tuple[VetoFact, ...] = ()
    restarts: tuple[RestartFact, ...] = ()
    wp4_mechanism_proof: str | None = None
    transitions: tuple[Mapping[str, Any], ...] = ()
    verdicts: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    new_exec_store_halt_keys: int | None = None
    frame_gap_days: tuple[tuple[str, int], ...] = ()


def _day_of_ns(ts_ns: int) -> dt.date:
    return dt.datetime.fromtimestamp(ts_ns / NS, tz=dt.UTC).date()


def _end_ns(day: dt.date) -> int:
    nxt = dt.datetime.combine(day + dt.timedelta(days=1), dt.time(), tzinfo=dt.UTC)
    return int(nxt.timestamp()) * NS


def _int(body: Mapping[str, Any], key: str) -> int | None:
    value = body.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _is_true(value: object) -> bool:
    return value is True


# -- the window ---------------------------------------------------------------------------------


def _paged(deliveries: Iterable[DeliveryFact], day: str) -> bool:
    """A delivered CRITICAL record of the #29 detector dated ``day``."""
    for fact in deliveries:
        body = fact.body
        if fact.day != day or not _is_true(body.get("delivered")):
            continue
        if body.get("severity") != "CRITICAL":
            continue
        if MONITOR_STALE_DETECTOR in f"{body.get('event', '')} {body.get('site', '')}":
            return True
    return False


def _day_failures(
    day: dt.date, rollup: Mapping[str, Any] | None, deliveries: tuple[DeliveryFact, ...]
) -> list[str]:
    if rollup is None:
        return ["rollup_missing"]
    produced = _int(rollup, "produced_at_ns")
    completed = _int(rollup, "passes_completed")
    unknown = _int(rollup, "passes_unknown")
    streak = _int(rollup, "max_passes_unknown_streak")
    unexplained = rollup.get("unexplained_failed_units")
    count = _int(unexplained, "count") if isinstance(unexplained, dict) else None
    if None in (produced, completed, unknown, streak, count):
        return ["rollup_malformed"]
    assert produced is not None and completed is not None and unknown is not None
    assert streak is not None and count is not None
    reasons: list[str] = []
    if produced < _end_ns(day) - ROLLUP_FINAL_GRACE_S * NS:
        reasons.append("rollup_stale")
    if completed < MIN_PASSES_COMPLETED:
        reasons.append("passes_completed_below_130")
    if unknown > MAX_PASSES_UNKNOWN:
        reasons.append("passes_unknown_above_6")
    if streak >= UNKNOWN_STREAK_PAGE_AT and not _paged(deliveries, day.isoformat()):
        reasons.append("unknown_streak_without_delivered_page")
    if count > 0:
        reasons.append("unexplained_failed_units")
    return reasons


def _fills_of(fills: Iterable[FillFact], day: str) -> tuple[int, int]:
    """``(any fill, real fills)`` of ``day``: real = a live, non-drill fill (canary excluded)."""
    todays = [f for f in fills if f.day == day]
    real = sum(1 for f in todays if f.source == LIVE_SOURCE and not f.drill)
    return len(todays), real


def _floor(inputs: ProofInputs) -> tuple[dt.date | None, list[str]]:
    blockers: list[str] = []
    dates: list[dt.date] = []
    for name, value in (
        ("aut5b_ruling_not_filed", inputs.aut5b_ruling_date),
        ("ing2_amend2_not_landed", inputs.ing2_amend2_landed_date),
    ):
        if value is None:
            blockers.append(name)
        else:
            dates.append(dt.date.fromisoformat(value))
    if blockers:
        return None, blockers
    return max(dates) + dt.timedelta(days=1), blockers


def _window(inputs: ProofInputs, floor: dt.date | None) -> dict[str, Any]:
    last = dt.date.fromisoformat(inputs.asof) - dt.timedelta(days=1)
    days: list[str] = []
    neutral: list[str] = []
    breaks: list[dict[str, Any]] = []
    real = 0
    cursor = floor
    while floor is not None and cursor is not None and cursor <= last:
        key = cursor.isoformat()
        reasons = _day_failures(cursor, inputs.rollups.get(key), inputs.deliveries)
        any_fill, real_fills = _fills_of(inputs.fills, key)
        if reasons:
            breaks.append({"day": key, "reasons": reasons})
            days, neutral, real = [], [], 0
        elif any_fill == 0:
            neutral.append(key)
        else:
            days.append(key)
            real += real_fills
        cursor += dt.timedelta(days=1)
    criteria = {"qualifying_days": len(days) >= WINDOW_DAYS, "real_fills": real >= MIN_REAL_FILLS}
    return {
        "from": floor.isoformat() if floor else None,
        "to": last.isoformat() if floor else None,
        "days": days,
        "day_count": len(days),
        "neutral_days": neutral,
        "breaks": breaks,
        "real_fills": real,
        "criteria": criteria,
        "required_days": WINDOW_DAYS,
        "required_real_fills": MIN_REAL_FILLS,
    }


# -- the action classes -------------------------------------------------------------------------


def _verdict_detector(inputs: ProofInputs, verdict_id: object) -> str | None:
    verdict = inputs.verdicts.get(verdict_id) if isinstance(verdict_id, str) else None
    detector = verdict.get("detector") if verdict else None
    return detector if isinstance(detector, str) else None


def _unmet(reason: str) -> dict[str, Any]:
    return {"satisfied": False, "injected": False, "reason": reason, "evidence": []}


def _met(injected: bool, evidence: list[str], **extra: Any) -> dict[str, Any]:
    return {"satisfied": True, "injected": injected, "reason": "", "evidence": evidence, **extra}


def _entry_veto(inputs: ProofInputs, since: dt.date) -> dict[str, Any]:
    for expiry in inputs.permit_expiries_ns:
        if _day_of_ns(expiry) < since:
            continue
        for veto in inputs.entry_vetos:
            lag = veto.ts_ns - expiry
            if (
                veto.reason == "permit_lapsed"
                and not veto.drill
                and 0 <= lag <= PERMIT_VETO_WITHIN_NS
            ):
                return _met(False, [veto.ref, f"expires_at_ns={expiry}"], lag_ns=lag)
    return _unmet("no_permit_lapsed_veto_within_120s_of_expiry")


def _alert(inputs: ProofInputs, since: dt.date) -> dict[str, Any]:
    for fact in inputs.deliveries:
        body = fact.body
        if dt.date.fromisoformat(fact.day) < since:
            continue
        if (
            body.get("attempt_kind") == "canary"
            and _is_true(body.get("delivered"))
            and body.get("drill") is False
        ):
            return _met(False, [f"{fact.day}/{fact.name}"])
    return _unmet("no_delivered_canary_record")


def _restart_complete(restart: RestartFact) -> bool:
    return (
        restart.unit in RECORDER_UNITS
        and restart.unit_result == "watchdog"
        and bool(restart.verdict_id)
        and (restart.notifier_delivered or restart.fallback_page_delivered)
    )


def _self_heal(inputs: ProofInputs, since: dt.date) -> dict[str, Any]:
    restarts = [
        r for r in inputs.restarts if r.unit in RECORDER_UNITS and _day_of_ns(r.ts_ns) >= since
    ]
    complete = sorted((r for r in restarts if _restart_complete(r)), key=lambda r: r.injected)
    if complete:
        best = complete[0]
        return _met(
            best.injected,
            [best.invocation_id, best.verdict_id],
            basis="restart",
        )
    if restarts:
        return _unmet("restart_chain_incomplete")
    if inputs.wp4_mechanism_proof:
        return _met(True, [inputs.wp4_mechanism_proof], basis="wp4_mechanism_proof")
    return _unmet("no_watchdog_restart_in_window")


def _later_veto(inputs: ProofInputs, reason: str, after_ns: int) -> VetoFact | None:
    for veto in inputs.node_log_vetos:
        if veto.reason == reason and veto.ts_ns >= after_ns:
            return veto
    return None


def _cited_drill_verdict(inputs: ProofInputs, row: Mapping[str, Any], detector: str) -> str | None:
    ids = row.get("cause_verdict_ids")
    for vid in ids if isinstance(ids, list | tuple) else ():
        if _verdict_detector(inputs, vid) == detector:
            return str(vid)
    return None


def _drill_row_class(
    inputs: ProofInputs,
    since: dt.date,
    kind: str,
    detector: str,
    veto_reason: str,
    is_drill: Callable[[Mapping[str, Any]], bool],
) -> dict[str, Any]:
    reason = f"no_{kind.lower()}_row_citing_{detector.lower()}"
    for row in inputs.transitions:
        ts = _int(row, "ts_ns")
        if row.get("kind") != kind or row.get("decided_by") != "engine" or ts is None:
            continue
        if _day_of_ns(ts) < since or not is_drill(row):
            continue
        verdict_id = _cited_drill_verdict(inputs, row, detector)
        if verdict_id is None:
            continue
        veto = _later_veto(inputs, veto_reason, ts)
        if veto is None:
            reason = f"node_log_{veto_reason}_line_missing"
            continue
        return _met(True, [str(row.get("transition_id")), verdict_id, veto.ref])
    return _unmet(reason)


def _demote(inputs: ProofInputs, since: dt.date) -> dict[str, Any]:
    return _drill_row_class(
        inputs, since, "DEMOTE", DEMOTE_VERDICT, DEMOTE_VETO, lambda r: r.get("drill") is True
    )


def _halt(inputs: ProofInputs, since: dt.date) -> dict[str, Any]:
    found = _drill_row_class(
        inputs,
        since,
        "HALT",
        HALT_VERDICT,
        HALT_VETO,
        lambda r: r.get("halt_cause_class") == "DRILL",
    )
    if not found["satisfied"]:
        return found
    if inputs.new_exec_store_halt_keys is None:
        return _unmet("exec_store_halt_keys_unknown")
    if inputs.new_exec_store_halt_keys != 0:
        return _unmet("new_exec_store_halt_key_written")
    return found


def _classes(inputs: ProofInputs, since: dt.date) -> dict[str, dict[str, Any]]:
    return {
        "ENTRY_VETO": _entry_veto(inputs, since),
        "ALERT": _alert(inputs, since),
        "SELF_HEAL": _self_heal(inputs, since),
        "DEMOTE": _demote(inputs, since),
        "HALT": _halt(inputs, since),
    }


# -- the report ---------------------------------------------------------------------------------


def evaluate_live_proof(inputs: ProofInputs) -> dict[str, Any]:
    """The live-proof report of ``inputs``: window, per-class proof, blockers and the verdict."""
    floor, blockers = _floor(inputs)
    window = _window(inputs, floor)
    classes = _classes(inputs, floor or dt.date.min)
    if floor is not None:
        blockers += [f"window_{name}_unmet" for name, ok in window["criteria"].items() if not ok]
    blockers += [
        f"action_class_unproven:{n}" for n in ACTION_CLASSES if not classes[n]["satisfied"]
    ]
    return {
        "schema": REPORT_SCHEMA,
        "asof": inputs.asof,
        "verdict": "NOT_YET" if blockers else "PROVEN",
        "evidence_class": EVIDENCE_CLASS,
        "blockers": blockers,
        "prerequisites": {
            "aut5b_ruling_date": inputs.aut5b_ruling_date,
            "ing2_amend2_landed_date": inputs.ing2_amend2_landed_date,
        },
        "window": window,
        "classes": classes,
        "frame_gap_review": [{"day": d, "fills": n} for d, n in sorted(inputs.frame_gap_days)],
    }
