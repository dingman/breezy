"""The live-proof window rules (AUT-2 r7 WP8, section 6): a pure evaluator over per-day evidence.

A window needs ``PROOF_QUALIFYING_DAYS`` qualifying days and ``PROOF_MIN_REAL_FILLS`` real fills.
A day with real fills qualifies only when every label and reconciliation check holds. A zero-fill
day qualifies only as a canary day (the canary labelled with a non-null probability, passed its own
reconciliation, and the day's REAL reconciliation is PASS); a canary never satisfies the
"every live fill labelled" check (``live_fill_check="vacuous"``) and its fills never count
toward the real-fill minimum. Any other zero-fill day extends the window. A failing day, a held
label slot or a non-C1 entry row fails the day and restarts the window the next day.

The start is refused before the first UTC day fully after ``capture_epoch_start``, without WP7, or
while a label hold exists on that day or later (Q1, Q2, Q4). Pre-epoch days are never evidence.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from breezy.analysis.labeling.constants import (
    LABEL_LAG_MAX_H,
    PROOF_MIN_REAL_FILLS,
    PROOF_QUALIFYING_DAYS,
)
from breezy.persistence.autonomy.verdict import VerdictOutcome

__all__ = [
    "DayEvidence",
    "DayResult",
    "DayStatus",
    "ProofWindowRefused",
    "WindowResult",
    "evaluate_window",
]

_NS_PER_DAY: Final = 86_400_000_000_000
_PASS: Final = VerdictOutcome.PASS


class ProofWindowRefused(Exception):
    """The window cannot start here; ``reason`` is the machine-readable cause."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class DayStatus(StrEnum):
    QUALIFIES = "qualifies"
    QUALIFIES_CANARY = "qualifies_canary"
    EXTENDS = "extends"
    FAILS = "fails"
    EXCLUDED = "excluded"


@dataclass(frozen=True)
class DayEvidence:
    """What the stores say about one UTC day (assembled by the caller, never by this module)."""

    utc_day: str
    real_fills: int
    final_labelled: int
    unresolved: int
    missing_label: int
    non_c1_post_epoch_count: int
    non_c1_entry_rows: int
    p_null_count: int
    daily_recon: VerdictOutcome | None
    post_stop: VerdictOutcome | None
    intraday_non_pass_ids: tuple[str, ...]
    position_mismatches_transient: int
    max_label_lag_h: float
    fills_never_position_compared: int
    canary_fills: int
    canary_labelled_with_p: bool
    canary_recon_passes: bool
    label_slot_held: bool
    no_leg_fills: int = 0
    exit_fills: int = 0
    marker_file: str | None = None
    invocation_id: str | None = None


@dataclass(frozen=True)
class DayResult:
    utc_day: str
    status: DayStatus
    reasons: tuple[str, ...]
    real_fills: int
    canary_fills: int
    live_fill_check: str
    evidence: DayEvidence


@dataclass(frozen=True)
class WindowResult:
    start_day: str
    end_day: str | None
    days: tuple[DayResult, ...]
    qualifying_days: int
    real_fills: int
    no_leg_fills: int
    exit_fills: int
    canary_fills: int
    restarted_on: tuple[str, ...]
    complete: bool


def _day_start_ns(day: str) -> int:
    date = dt.date.fromisoformat(day)
    return int(dt.datetime(date.year, date.month, date.day, tzinfo=dt.UTC).timestamp()) * (
        1_000_000_000
    )


def _check_start(
    start_day: str,
    capture_epoch_start_ns: int | None,
    wp7_active: bool,
    hold_days: Collection[str],
) -> None:
    if capture_epoch_start_ns is None:
        raise ProofWindowRefused("capture_epoch_unwritten")
    if not wp7_active:
        raise ProofWindowRefused("wp7_not_active")
    if _day_start_ns(start_day) < capture_epoch_start_ns:
        raise ProofWindowRefused("start_before_capture_epoch")
    if any(held >= start_day for held in hold_days):
        raise ProofWindowRefused("label_timer_held")


def _real_day_failures(ev: DayEvidence) -> list[str]:
    checks = (
        ("labels_not_all_final", ev.final_labelled != ev.real_fills),
        ("unresolved", ev.unresolved != 0),
        ("missing_label", ev.missing_label != 0),
        ("non_c1_post_epoch", ev.non_c1_post_epoch_count != 0),
        ("p_null", ev.p_null_count != 0),
        ("daily_recon_not_pass", ev.daily_recon is not _PASS),
        ("post_stop_not_pass", ev.post_stop is not _PASS),
        ("label_lag", ev.max_label_lag_h > LABEL_LAG_MAX_H),
        ("fill_never_position_compared", ev.fills_never_position_compared != 0),
    )
    return [name for name, failed in checks if failed]


def _is_canary_day(ev: DayEvidence) -> bool:
    return (
        ev.canary_fills > 0
        and ev.canary_labelled_with_p
        and ev.canary_recon_passes
        and ev.daily_recon is _PASS
    )


def _classify(ev: DayEvidence) -> tuple[DayStatus, tuple[str, ...], str]:
    if ev.label_slot_held:
        return DayStatus.FAILS, ("label_slot_held",), "not_checked"
    if ev.non_c1_entry_rows > 0:
        return DayStatus.FAILS, ("non_c1_entry_row",), "not_checked"
    if ev.real_fills > 0:
        failures = _real_day_failures(ev)
        if failures:
            return DayStatus.FAILS, tuple(failures), "not_all_labelled"
        return DayStatus.QUALIFIES, (), "all_labelled"
    if _is_canary_day(ev):
        return DayStatus.QUALIFIES_CANARY, (), "vacuous"
    reasons = ("zero_fill_day",) if ev.canary_fills == 0 else ("canary_day_not_qualified",)
    return DayStatus.EXTENDS, reasons, "vacuous"


def _next_day(day: str) -> str:
    return (dt.date.fromisoformat(day) + dt.timedelta(days=1)).isoformat()


def evaluate_window(
    *,
    start_day: str,
    days: Sequence[DayEvidence],
    capture_epoch_start_ns: int | None,
    wp7_active: bool,
    hold_days: Collection[str],
) -> WindowResult:
    """Evaluate ``days`` (any order) from ``start_day``; refuses an invalid start first."""
    _check_start(start_day, capture_epoch_start_ns, wp7_active, hold_days)
    results: list[DayResult] = []
    current_start = start_day
    restarts: list[str] = []
    live: list[DayResult] = []
    for ev in sorted(days, key=lambda d: d.utc_day):
        if ev.utc_day < start_day:
            reason = (
                "pre_epoch"
                if _day_start_ns(ev.utc_day) < (capture_epoch_start_ns or 0)
                else "before_start"
            )
            results.append(
                DayResult(ev.utc_day, DayStatus.EXCLUDED, (reason,), 0, 0, "excluded", ev)
            )
            continue
        status, reasons, check = _classify(ev)
        result = DayResult(ev.utc_day, status, reasons, ev.real_fills, ev.canary_fills, check, ev)
        results.append(result)
        if status is DayStatus.FAILS:
            restarts.append(ev.utc_day)
            current_start = _next_day(ev.utc_day)
            live = []
        else:
            live.append(result)
    qualifying = [r for r in live if r.status in (DayStatus.QUALIFIES, DayStatus.QUALIFIES_CANARY)]
    real = sum(r.real_fills for r in qualifying if r.status is DayStatus.QUALIFIES)
    return WindowResult(
        start_day=current_start,
        end_day=results[-1].utc_day if results else None,
        days=tuple(results),
        qualifying_days=len(qualifying),
        real_fills=real,
        no_leg_fills=sum(r.evidence.no_leg_fills for r in qualifying),
        exit_fills=sum(r.evidence.exit_fills for r in qualifying),
        canary_fills=sum(
            r.canary_fills for r in qualifying if r.status is DayStatus.QUALIFIES_CANARY
        ),
        restarted_on=tuple(restarts),
        complete=len(qualifying) >= PROOF_QUALIFYING_DAYS and real >= PROOF_MIN_REAL_FILLS,
    )
