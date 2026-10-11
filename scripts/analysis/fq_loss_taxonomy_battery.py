"""TE-2 WP1c STUB (RED): the Phase B test battery (pure)."""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from scripts.analysis.fq_loss_taxonomy_stats import Status
from scripts.analysis.fq_loss_taxonomy_verdict import HypothesisOutcome


@dataclass(frozen=True)
class DayRecord:
    station: str
    climate_day: dt.date
    p_d: float
    won: bool
    ask_prob: float
    fill_qs: tuple[float, ...] | None
    tail_flags: tuple[bool, ...] | None
    pi: float | None
    corr_err: float | None
    raw_err: float | None


@dataclass(frozen=True)
class BatteryResult:
    report: dict[str, Any]
    outcomes: Mapping[str, HypothesisOutcome]
    loo_rejects: bool
    after_ties: Mapping[str, Status]
    decisions: Mapping[str, bool]


def run_battery(
    days: Sequence[DayRecord],
    *,
    level: Literal["cluster", "day"],
    alpha_primary: float,
    alpha_art: float,
) -> BatteryResult:
    raise NotImplementedError


def s0i_statuses_from_phase_a(table: Mapping[str, Any], *, alpha_primary: float) -> dict[str, str]:
    raise NotImplementedError
