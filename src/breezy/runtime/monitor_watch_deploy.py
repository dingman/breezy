"""The not-deployed rule (execution decision X-8): is an absent unit "not yet built" or broken?

A unit is ``not_deployed`` (INCONCLUSIVE, listed in the day rollup, never paged, never counted
toward ``unknown_streak``) only when ALL hold: its row is in the committed table and today is
before ``not_expected_until``; the host has neither a file nor a broken link for it; none of its
artifacts exists. Anything else is a finding: an unlisted missing unit, a broken link, a unit that
vanished after it produced artifacts, and a listed unit past its deadline (WARNING, then CRITICAL
from ``critical_from``).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from breezy.runtime.monitor_watch_model import (
    DEPLOYED,
    NOT_DEPLOYED,
    SEVERITY_CRITICAL,
    SEVERITY_WARNING,
    Deployment,
    Inventory,
)

KIND_MISSING = "unit_missing"
KIND_LINK_BROKEN = "unit_link_broken"
KIND_VANISHED = "deployed_then_vanished"
KIND_OVERDUE = "unit_not_deployed_overdue"


@dataclass(frozen=True, slots=True)
class NotDeployedRow:
    """``(unit, owner_wp, not_expected_until)``; the owner's activation commit deletes the row."""

    unit: str
    owner_wp: str
    not_expected_until: str  # ISO date, exclusive


def classify_unit(
    name: str,
    *,
    inventory: Inventory,
    rows: Mapping[str, NotDeployedRow],
    has_artifacts: Callable[[str], bool],
    today: str,
    critical_from: str,
) -> Deployment:
    link = inventory.link_state(name)
    if link == "present":
        return DEPLOYED
    if link == "broken":
        return Deployment("finding", KIND_LINK_BROKEN, SEVERITY_CRITICAL)
    row = rows.get(name)
    if has_artifacts(name):
        return Deployment("finding", KIND_VANISHED, SEVERITY_CRITICAL)
    if row is None:
        return Deployment("finding", KIND_MISSING, SEVERITY_CRITICAL)
    if today < row.not_expected_until:
        return NOT_DEPLOYED
    severity = SEVERITY_CRITICAL if today >= critical_from else SEVERITY_WARNING
    return Deployment("finding", KIND_OVERDUE, severity)
