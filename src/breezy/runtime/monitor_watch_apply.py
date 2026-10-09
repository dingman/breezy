"""The meta-detectors' hook into the unit health pass (WP3 S5): judge, commit findings, report.

Kept apart from ``monitor_watch`` so that ``unit_health_types`` can name ``WatchWiring`` without a
cycle: this module needs ``HostVerdict`` from ``unit_health_types``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from typing import Protocol

from breezy.runtime.monitor_watch import (
    PRODUCER_TIMERS,
    SUMMARY_LOOKBACK_S,
    SUMMARY_MAX_LOOKBACK_S,
    WatchWiring,
    evaluate_watch,
)
from breezy.runtime.monitor_watch_model import NS, SEVERITY_WARNING, WatchFinding, WatchResult
from breezy.runtime.unit_health_obs import UnitObservation
from breezy.runtime.unit_health_store import HealthStore, day_of_ns
from breezy.runtime.unit_health_types import HostVerdict

# --------------------------------------------------------------------------- the pass hook


_LOG = logging.getLogger(__name__)


class WatchScan(Protocol):
    reasons: list[str]
    not_deployed: list[str]
    #: Measured ``(node, recorder)`` resident KiB for the memory sample's add-back.
    resident_kib: tuple[int, int] | None
    #: Replaced-state fields of ``seen/<unit>.json`` committed with the pass.
    daemon_seen: dict[str, dict[str, object]]


class WatchEnv(Protocol):
    watch: WatchWiring | None
    host_verdict: Callable[[HostVerdict], None] | None

    @property
    def store(self) -> HealthStore: ...


class WatchHost(Protocol):
    """The part of the health pass the hook uses (``unit_health._Pass``)."""

    @property
    def env(self) -> WatchEnv: ...

    @property
    def store(self) -> HealthStore: ...

    @property
    def scan(self) -> WatchScan: ...

    @property
    def now(self) -> int: ...

    def allowance(self) -> float: ...

    def commit_finding(
        self,
        kind: str,
        unit: str,
        key: str,
        severity: str,
        detail: str,
        extra: Mapping[str, object] | None = ...,
        *,
        page: bool = ...,
    ) -> None: ...


def _summary_since_ns(host: WatchHost) -> tuple[int, bool]:
    """Where the summary-line read starts, and whether the gap had to be clamped.

    From the end of the last COMPLETED pass (``ts_ns``, which an UNKNOWN pass leaves alone), so a
    line is read again until a pass that saw it has committed its findings. A first pass looks
    back 15 minutes; a gap beyond 48 hours is clamped and reported, never silently shortened.
    """
    beat = host.store.read_heartbeat() or {}
    stamp = beat.get("ts_ns")
    if type(stamp) is not int or stamp <= 0:
        return host.now - SUMMARY_LOOKBACK_S * NS, False
    floor = host.now - SUMMARY_MAX_LOOKBACK_S * NS
    return (floor, True) if stamp < floor else (min(stamp, host.now), False)


def _first_seen(host: WatchHost) -> dict[str, int]:
    stored: dict[str, int] = {}
    for timer in PRODUCER_TIMERS:
        seen = host.store.read_seen(timer) or {}
        stamp = seen.get("first_seen_ns")
        if type(stamp) is int:
            stored[timer] = stamp
    return stored


def apply_watch(host: WatchHost, observation: UnitObservation) -> WatchResult | None:
    """Judge the meta-detectors, commit each finding (one page per key) and report the rest.

    Unreadable inputs append to ``scan.reasons`` (the pass becomes UNKNOWN); INCONCLUSIVE
    not-deployed outcomes are listed for the rollup and never reach ``reasons``. Findings are
    committed before any verdict sink runs, and a failing sink is a reason, not a lost finding.
    """
    wiring = host.env.watch
    if wiring is None:
        return None
    since, clamped = _summary_since_ns(host)
    stored = _first_seen(host)
    result = evaluate_watch(
        wiring,
        observation,
        now_ns=host.now,
        window=host.store.memavail_window(host.now),
        summary_since_ns=since,
        summary_timeout_s=host.allowance(),
        first_seen=stored,
    )
    reasons = host.scan.reasons
    reasons.extend(r for r in dict.fromkeys(result.unknown_reasons) if r not in reasons)
    host.scan.not_deployed = sorted({*host.scan.not_deployed, *result.not_deployed})
    host.scan.resident_kib = result.resident_kib
    for timer, stamp in result.sightings.items():
        if timer not in stored:  # write-once in effect: a stored sighting is never moved
            host.scan.daemon_seen.setdefault(timer, {})["first_seen_ns"] = stamp
    if clamped:
        host.commit_finding(
            "summary_lookback_clamped",
            "_host",
            f"summary_lookback_clamped-{day_of_ns(host.now)}",
            SEVERITY_WARNING,
            "no completed health pass for 48h: summary lines older than that are not read",
        )
    for finding in result.findings:
        host.commit_finding(
            finding.kind,
            finding.subject,
            finding.key,
            finding.severity,
            finding.detail,
            finding_extra(finding),
        )
    sink = host.env.host_verdict
    if sink is not None:
        for item in result.results:
            try:
                sink(HostVerdict(item.detector, item.outcome.value, dict(item.metrics), host.now))
            except Exception as exc:  # noqa: BLE001 - the findings are already committed
                _LOG.error("host_verdict_sink_failed exception_type=%s", type(exc).__name__)
                if "host_verdict_sink_failed" not in reasons:
                    reasons.append("host_verdict_sink_failed")
    return result


def finding_extra(finding: WatchFinding) -> dict[str, object]:
    return {"detector": finding.detector, "metrics": dict(finding.metrics)}
