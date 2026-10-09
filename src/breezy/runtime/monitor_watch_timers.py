"""Timer liveness, ``#28 aut6.timer_liveness`` (plan r15 section 3.9; WP3 S5).

Judged from the bus snapshot only. For every key of the interval table (a template expanded to its
enabled instances) the pass reads ``UnitFileState``, ``ActiveState``, ``ActiveEnterTimestamp``,
``LastTriggerUSec`` and the next-elapse property (the monotonic one for a timer with a
``TimersMonotonic`` spec, the realtime one otherwise). FAIL when the timer is not ``enabled``, not
``active``, has no future elapse, has never triggered once ``ActiveEnterTimestamp + interval +
900 s`` has passed, or last triggered longer ago than ``interval + 900 s``; when a template has no
enabled instance; and when a retired timer is loaded and enabled. Every ``deploy/systemd`` unit
file must also be installed or listed in the not-deployed table (the inventory completeness check).
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping, Sequence
from pathlib import Path
from typing import Final

from breezy.runtime.monitor_watch_model import (
    NS,
    SEVERITY_CRITICAL,
    Deployment,
    DetectorResult,
    Inventory,
    Outcome,
    WatchFinding,
    deploy_unit_names,
    instances_of,
    is_monotonic_timer,
    timestamp_or_zero,
)

DETECTOR_TIMERS: Final = "aut6.timer_liveness"
#: Added to a timer's interval before its last trigger counts as stale (covers ``AccuracySec``
#: lateness, the start latency of the oneshot and a missed minute).
TIMER_GRACE_S: Final = 900
KIND_NOT_ENABLED = "timer_not_enabled"
KIND_NOT_ACTIVE = "timer_not_active"
KIND_NO_NEXT_ELAPSE = "timer_no_next_elapse"
KIND_NEVER_TRIGGERED = "timer_never_triggered"
KIND_STALE = "timer_last_trigger_stale"
KIND_NO_INSTANCES = "timer_template_no_instances"
KIND_RETIRED_ENABLED = "retired_timer_enabled"
_NO_FUTURE_MONOTONIC: Final = frozenset({"", "0", "infinity", "n/a"})

Classify = Callable[[str], Deployment]


def _finding(kind: str, unit: str, today: str, detail: str) -> WatchFinding:
    return WatchFinding(
        DETECTOR_TIMERS, kind, unit, SEVERITY_CRITICAL, f"{kind}-{today}", detail, {"unit": unit}
    )


def _check_block(
    unit: str,
    block: Mapping[str, str],
    *,
    interval_s: int,
    monotonic: bool,
    now_ns: int,
    today: str,
) -> tuple[list[WatchFinding], list[str]]:
    """``(findings, unknown reasons)`` for one present timer."""
    findings: list[WatchFinding] = []
    unreadable: list[str] = []
    needed: tuple[str, ...] = (
        "UnitFileState",
        "ActiveState",
        "LastTriggerUSec",
        "ActiveEnterTimestamp",
    )
    needed += ("NextElapseUSecMonotonic",) if monotonic else ("NextElapseUSecRealtime",)
    missing = [key for key in needed if key not in block]
    if missing:
        return [], [f"timer_property_missing:{unit}:{','.join(missing)}"]
    if block["UnitFileState"] != "enabled":
        findings.append(_finding(KIND_NOT_ENABLED, unit, today, f"unit={unit} not enabled"))
    if block["ActiveState"] != "active":
        findings.append(_finding(KIND_NOT_ACTIVE, unit, today, f"unit={unit} not active"))
    if monotonic:
        future = block["NextElapseUSecMonotonic"].strip() not in _NO_FUTURE_MONOTONIC
    else:
        readable, elapse = timestamp_or_zero(block["NextElapseUSecRealtime"])
        if not readable:
            unreadable.append(f"timer_property_unparseable:{unit}:NextElapseUSecRealtime")
        future = elapse is not None and elapse > now_ns
    if not unreadable and not future:
        findings.append(_finding(KIND_NO_NEXT_ELAPSE, unit, today, f"unit={unit} no next elapse"))
    ok_last, last = timestamp_or_zero(block["LastTriggerUSec"])
    ok_enter, entered = timestamp_or_zero(block["ActiveEnterTimestamp"])
    if not ok_last or not ok_enter:
        unreadable.append(f"timer_property_unparseable:{unit}:timestamps")
        return findings, unreadable
    limit_ns = (interval_s + TIMER_GRACE_S) * NS
    if last is None:
        if entered is not None and now_ns - entered > limit_ns:
            findings.append(
                _finding(KIND_NEVER_TRIGGERED, unit, today, f"unit={unit} never triggered")
            )
    elif now_ns - last > limit_ns:
        findings.append(_finding(KIND_STALE, unit, today, f"unit={unit} last trigger stale"))
    return findings, unreadable


def inventory_findings(
    deploy_dir: Path,
    classify: Classify,
    today: str,
    extra_units: Sequence[str] = (),
    skip: Collection[str] = (),
) -> tuple[list[WatchFinding], list[str]]:
    """Every deploy unit file, and every listed future unit, must be installed or listed as not
    yet deployed (X-8). ``skip`` names units that are meant to be absent (retired timers)."""
    findings: list[WatchFinding] = []
    not_deployed: list[str] = []
    for name in sorted({*deploy_unit_names(deploy_dir), *extra_units} - set(skip)):
        verdict = classify(name)
        if verdict.state == "not_deployed":
            not_deployed.append(name)
        elif verdict.state == "finding":
            findings.append(
                WatchFinding(
                    DETECTOR_TIMERS,
                    verdict.kind,
                    name,
                    verdict.severity,
                    f"{verdict.kind}-{today}",
                    f"unit={name} {verdict.kind}",
                    {"unit": name},
                )
            )
    return findings, not_deployed


def evaluate_timers(
    *,
    deploy_dir: Path,
    inventory: Inventory,
    table: Mapping[str, tuple[int, int]],
    instance_intervals: Mapping[str, tuple[int, int]],
    retired: Mapping[str, str],
    classify: Classify,
    extra_units: Sequence[str] = (),
    now_ns: int,
    today: str,
) -> tuple[DetectorResult, tuple[str, ...]]:
    """``(#28 result, unit names read as not deployed)``."""
    findings, not_deployed = inventory_findings(
        deploy_dir, classify, today, extra_units, skip=retired
    )
    unknown: list[str] = []
    judged = 0
    for key, (interval_s, _accuracy) in sorted(table.items()):
        if "@." in key:
            units = instances_of(key, inventory)
            if not units:
                findings.append(
                    _finding(KIND_NO_INSTANCES, key, today, f"template={key} no enabled instance")
                )
                continue
        else:
            units = (key,)
        for unit in units:
            if classify(unit).state != "deployed":
                continue  # absent: the inventory check above already judged it
            block = inventory.blocks.get(unit)
            if block is None:
                unknown.append(f"timer_property_missing:{unit}:block")
                continue
            interval = instance_intervals.get(unit, (interval_s, 0))[0]
            monotonic = is_monotonic_timer(deploy_dir, unit, block)
            found, unreadable = _check_block(
                unit,
                block,
                interval_s=interval,
                monotonic=monotonic,
                now_ns=now_ns,
                today=today,
            )
            findings.extend(found)
            unknown.extend(unreadable)
            judged += 1
    for unit in sorted(retired):
        block = inventory.blocks.get(unit)
        loaded = block is not None and block.get("LoadState") == "loaded"
        if loaded and block is not None and block.get("UnitFileState", "").startswith("enabled"):
            findings.append(
                _finding(KIND_RETIRED_ENABLED, unit, today, f"retired unit={unit} is enabled")
            )
    outcome = Outcome.FAIL if findings else Outcome.PASS
    metrics = {"timers_judged": str(judged)}
    return (
        DetectorResult(DETECTOR_TIMERS, outcome, tuple(findings), metrics, tuple(unknown)),
        tuple(not_deployed),
    )
