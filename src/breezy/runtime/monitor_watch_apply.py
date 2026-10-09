"""The meta-detectors' hook into the unit health pass (WP3 S5): judge, commit findings, report.

Kept apart from ``monitor_watch`` so that ``unit_health_types`` can name ``WatchWiring`` without a
cycle: this module needs ``HostVerdict`` from ``unit_health_types``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Protocol

from breezy.runtime.monitor_watch import (
    SUMMARY_LOOKBACK_S,
    SUMMARY_MAX_LOOKBACK_S,
    WatchWiring,
    evaluate_watch,
)
from breezy.runtime.monitor_watch_model import NS, WatchFinding, WatchResult
from breezy.runtime.unit_health_obs import UnitObservation
from breezy.runtime.unit_health_store import HealthStore
from breezy.runtime.unit_health_types import HostVerdict

# --------------------------------------------------------------------------- the pass hook


class WatchScan(Protocol):
    reasons: list[str]
    not_deployed: list[str]


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


def apply_watch(host: WatchHost, observation: UnitObservation) -> WatchResult | None:
    """Judge the meta-detectors, commit each finding (one page per key) and report the rest.

    Unreadable inputs append to ``scan.reasons`` (the pass becomes UNKNOWN); INCONCLUSIVE
    not-deployed outcomes are listed for the rollup and never reach ``reasons``.
    """
    wiring = host.env.watch
    if wiring is None:
        return None
    beat = host.store.read_heartbeat() or {}
    last = beat.get("last_attempt_ns")
    floor = host.now - SUMMARY_MAX_LOOKBACK_S * NS
    since = last if isinstance(last, int) and last > floor else host.now - SUMMARY_LOOKBACK_S * NS
    result = evaluate_watch(
        wiring,
        observation,
        now_ns=host.now,
        window=host.store.memavail_window(host.now),
        summary_since_ns=since,
        summary_timeout_s=host.allowance(),
    )
    for reason in result.unknown_reasons:
        if reason not in host.scan.reasons:
            host.scan.reasons.append(reason)
    host.scan.not_deployed = list(result.not_deployed)
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
            sink(HostVerdict(item.detector, item.outcome.value, dict(item.metrics), host.now))
    return result


def finding_extra(finding: WatchFinding) -> dict[str, object]:
    return {"detector": finding.detector, "metrics": dict(finding.metrics)}
