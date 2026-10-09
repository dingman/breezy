"""Heartbeat and daily rollups of the AUT-6 unit health pass (plan r15 sections 3.9 and 3.11)."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Final

from breezy.runtime.unit_health_store import previous_day
from breezy.runtime.unit_health_support import unexplained_for_day
from breezy.runtime.unit_health_types import PassEnv

#: Days back from today whose rollup is rewritten when any record there is not yet explained.
EXPLAIN_LOOKBACK_DAYS: Final = 2
#: Days back whose stored rollup still shows unexplained units: refreshed until it reads zero.
REFRESH_LOOKBACK_DAYS: Final = 7


def heartbeat_body(env: PassEnv, completed: bool, result: str) -> dict[str, Any]:
    previous = env.store.read_heartbeat() or {}
    end = env.now_ns()
    old_ts = previous.get("ts_ns")
    old_streak = previous.get("passes_unknown_streak")
    streak = 0 if completed else (old_streak if isinstance(old_streak, int) else 0) + 1
    ts_ns = end if completed else (old_ts if isinstance(old_ts, int) else 0)
    return {
        "schema": "health_heartbeat/v1",
        "ts_ns": ts_ns,
        "last_attempt_ns": end,
        "invocation_id": env.invocation_id,
        "pass_result": result,
        "passes_unknown_streak": streak,
    }


def _days_back(today: str, count: int) -> list[str]:
    days = [today]
    for _ in range(count):
        days.append(previous_day(days[-1]))
    return days


def rollup_days(env: PassEnv, today: str, touched: Iterable[str]) -> list[str]:
    """Today, every day this pass wrote a record for, every recent day with an unexplained record,
    and every recent day whose stored rollup still shows unexplained units."""
    days = {today, *touched}
    for day in _days_back(today, EXPLAIN_LOOKBACK_DAYS):
        if unexplained_for_day(env.store, day, env.delivered):
            days.add(day)
    for day in _days_back(today, REFRESH_LOOKBACK_DAYS):
        stored = env.store.read_rollup(day) or {}
        if (stored.get("unexplained_failed_units") or {}).get("count"):
            days.add(day)
    return sorted(days)


def rollup_body(
    env: PassEnv,
    day: str,
    *,
    own_day: bool,
    completed: bool,
    streak: int,
    foreign: Iterable[str],
    cursor_reset: bool,
) -> dict[str, Any]:
    """The rollup of ``day``. Pass counters move only on the pass's own day."""
    previous = env.store.read_rollup_strict(day)
    names = unexplained_for_day(env.store, day, env.delivered)
    merged = sorted({*previous.get("foreign_failed", []), *(foreign if own_day else ())})
    return {
        "schema": "unit_health_day/v1",
        "day": day,
        "unexplained_failed_units": {"count": len(names), "names": list(names)},
        "foreign_failed": merged,
        "passes_completed": int(previous.get("passes_completed", 0)) + int(own_day and completed),
        "passes_unknown": int(previous.get("passes_unknown", 0)) + int(own_day and not completed),
        "max_passes_unknown_streak": max(
            int(previous.get("max_passes_unknown_streak", 0)), streak if own_day else 0
        ),
        "cursor_reset": bool(previous.get("cursor_reset")) or (own_day and cursor_reset),
        "produced_at_ns": env.now_ns(),
    }
