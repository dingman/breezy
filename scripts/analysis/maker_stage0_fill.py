"""MAKER-S2 WP4: Stage 0 fill simulator (pure; no I/O, no truth).

Plan: ``docs/plans/backlog/MAKER_2026-10-12/S2_stage0_replay_plan_r3.md`` WP4 (L148-172) with the r4
delta (d)(e)(g)(i)3/(i)10. Rule source: spec v0.3 section 6.1
(``docs/strategies/SPEC_pm_us_no_ladder_maker_2026-10-12.md:232-247``).

Spec :236-242 (inversion): a resting NO bid at ``b`` is filled by a YES-BUYER print whose NO price
``q = 100 - p`` is ``<= b``; a BUYER print at ``q > b`` consumed better-priced bids and only reduces
the queue ahead ``Q0 = A_gt + A_eq + 1`` (own unit last; spec :237-239). Spec :242-244: ambiguous
aggressor is never credited; the marketability guard refuses stale or truncated frames; gaps are
subtracted. Stress (spec :245-246, gated in plan 1.1): ``Q0' = 2 (A_gt + A_eq + 1)``,
``G' = 2 A_gt``.

Rung selection is injected (``RungSelector``): WP6 adapts WP3's ``select_rungs``/``bid_price``.
The base and stress rules each run as an independent pass over the same totally ordered events;
episode boundaries are identical, a rung is held from its own pass's fill onward. The pass
machinery lives in ``maker_stage0_fill_pass``; this module merges the two passes into
``Episode`` rows and the ``StationDaySummary``.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import NamedTuple

from scripts.analysis.maker_stage0_fill_events import (
    CENTS,
    NS_PER_HOUR,
    Decision,
    DecisionContext,
    Desired,
    Episode,
    Event,
    ForecastVector,
    RungSelector,
    StationDayResult,
    StationDaySummary,
    apply_clock_shift,
    assert_delta_within_bound,
)
from scripts.analysis.maker_stage0_fill_pass import TRUNCATED_FRAME, Pass, Rest

__all__ = [
    "Decision",
    "DecisionContext",
    "Desired",
    "Episode",
    "RungSelector",
    "StationDayResult",
    "StationDaySummary",
    "simulate_station_day",
]

NS_PER_S = 1_000_000_000
DEFAULT_MAX_RUNGS = 2  # WP6 must pass WP3's MAX_RUNGS constant


class _Vec(NamedTuple):
    """The vector in force at a rest's end, flattened for the Episode record."""

    p_point: float | None
    p_upper: float | None
    cycle_runtime_ns: int | None
    raw_sha256: str | None
    nbm_era: str | None
    available_at_ns: int | None


def _vec(rest: Rest | None) -> _Vec:
    vec: ForecastVector | None = rest.vector if rest else None
    if rest is None or vec is None:
        return _Vec(None, None, None, None, None, None)
    return _Vec(
        vec.p_yes_point.get(rest.rung_id),
        vec.p_yes_upper.get(rest.rung_id),
        vec.cycle_runtime_ns,
        vec.raw_sha256,
        vec.nbm_era,
        vec.available_at_ns,
    )


def _to_episode(
    base: Rest | None, stress: Rest | None, station: str, day: str, unit: str
) -> Episode:
    lead = base or stress
    assert lead is not None
    own, st = _vec(lead), _vec(stress)
    return Episode(
        station=station,
        climate_day=day,
        rung_id=lead.rung_id,
        t0_ns=lead.t0_ns,
        end_ns=lead.end_ns,
        end_reason=lead.end_reason,
        bid_cents=lead.bid_cents,
        a_gt=lead.a_gt,
        a_eq=lead.a_eq,
        refused_reason=lead.refused_reason,
        filled_ns_base=base.filled_ns if base else None,
        filled_ns_stress=stress.filled_ns if stress else None,
        gap_ns_subtracted=lead.gap_ns,
        p_yes_point_live=own.p_point,
        p_yes_upper_live=own.p_upper,
        cycle_runtime_ns=own.cycle_runtime_ns,
        raw_sha256=own.raw_sha256,
        nbm_era=own.nbm_era,
        available_at_ns=own.available_at_ns,
        depth_ts_used_ns=lead.depth_ts_used_ns,
        unit_hypothesis=unit,
        end_ns_stress=stress.end_ns if stress else None,
        end_reason_stress=stress.end_reason if stress else None,
        p_yes_point_live_stress=st.p_point,
        p_yes_upper_live_stress=st.p_upper,
        cycle_runtime_ns_stress=st.cycle_runtime_ns,
        raw_sha256_stress=st.raw_sha256,
        nbm_era_stress=st.nbm_era,
        available_at_ns_stress=st.available_at_ns,
    )


def _merge(base: Pass, stress: Pass, station: str, day: str, unit: str) -> tuple[Episode, ...]:
    """Key (rung, t0): the base record leads; stress-only rests follow a base fill (rung held)."""
    b = {(r.rung_id, r.t0_ns): r for r in base.rests}
    s = {(r.rung_id, r.t0_ns): r for r in stress.rests}
    keys = sorted(b.keys() | s.keys(), key=lambda k: (k[1], k[0]))
    return tuple(_to_episode(b.get(k), s.get(k), station, day, unit) for k in keys)


def _filled_rungs(eps: Iterable[Episode], stressed: bool) -> set[str]:
    return {
        e.rung_id for e in eps if (e.filled_ns_stress if stressed else e.filled_ns_base) is not None
    }


def _lower_median_cents(cents: list[int]) -> float | None:
    """On-tick lower median: sorted index floor((n - 1) / 2), in integer cents (delta (f))."""
    if not cents:
        return None
    return sorted(cents)[(len(cents) - 1) // 2] / CENTS


def _truncation_stats(base: Pass) -> tuple[float | None, float | None]:
    """(truncated-refusal share of attempts, seconds from the first one to the next placement)."""
    refusals = [r.t0_ns for r in base.rests if r.refused_reason == TRUNCATED_FRAME]
    share = len(refusals) / base.attempts if base.attempts else None
    if not refusals:
        return share, None
    first = min(refusals)
    placed = [r.t0_ns for r in base.rests if r.refused_reason is None and r.t0_ns >= first]
    return share, ((min(placed) - first) / NS_PER_S if placed else None)


def _summarize(
    eps: tuple[Episode, ...], base: Pass, station: str, day: str, unit: str, delta: int
) -> StationDaySummary:
    placed = [e for e in eps if e.refused_reason is None]
    f_base, f_stress = _filled_rungs(placed, False), _filled_rungs(placed, True)
    n_refused = sum(1 for r in base.rests if r.refused_reason is not None)
    n_eps = len(base.rests) - n_refused
    live_h, valid_h = base.live_ns / NS_PER_HOUR, base.valid_ns / NS_PER_HOUR
    gap_h = base.gap_ns / NS_PER_HOUR
    share, delay_s = _truncation_stats(base)
    k1 = base.k1_rung
    return StationDaySummary(
        station=station,
        climate_day=day,
        unit_hypothesis=unit,
        bid_bearing=base.attempts > 0,
        guard_refused_only=base.attempts > 0 and n_eps == 0,
        n_attempts=base.attempts,
        n_episodes=n_eps,
        n_refused=n_refused,
        n_process_cuts=base.process_cuts,
        n_gtd_cuts=base.gtd_cuts,
        rung_trials_attempted=len({e.rung_id for e in eps}),
        rung_trials_posted=len({e.rung_id for e in placed}),
        rung_trials_filled_base=len(f_base),
        rung_trials_filled_stress=len(f_stress),
        rungs_ever_posted=len(base.posted),
        filled_pairs_base=len(f_base),
        filled_pairs_stress=len(f_stress),
        k1_rung_id=k1,
        k1_filled_base=int(k1 in f_base),
        k1_filled_stress=int(k1 in f_stress),
        bid_median_fills_stress=_lower_median_cents(
            [e.bid_cents for e in placed if e.filled_ns_stress is not None]
        ),
        delta_ns=delta,
        truncation_refused_share=share,
        first_refusal_to_first_placement_s=delay_s,
        process_live_h=live_h,
        forecast_valid_h=valid_h,
        gap_h=gap_h,
        covered_live_h=live_h - gap_h,
        gap_share=gap_h / valid_h if valid_h > 0 else None,
    )


def simulate_station_day(
    events: Iterable[Event],
    selector: RungSelector,
    *,
    station: str,
    climate_day: str,
    unit_hypothesis: str,
    live_from_ns: int,
    delta_ns: int = 0,
    max_rungs: int = DEFAULT_MAX_RUNGS,
) -> StationDayResult:
    """Run the base and the stress rule over one station-day's events (venue clock).

    ``delta_ns`` is applied as a magnitude (forecast releases +, cancels -; ``DeltaBoundExceeded``
    above the S-7 ten-minute bound) and the live window opens ``|delta|`` later. The shift is
    leak-safe, NOT uniformly pessimistic for the fill rate: a delayed release also delays
    forecast-driven cancels (CANCEL_PMIN/STALE are decisions at the later release), so such a
    rest can be exposed to extra prints for up to ``delta``. ``max_rungs`` caps held + live rungs in
    each pass (WP6 passes WP3's constant); ``rungs_ever_posted`` reports rotation. Events must be
    in canonical ``(ts, kind, seq)`` order (``EventError`` otherwise). The selector must be pure.
    """
    delta = assert_delta_within_bound([delta_ns])  # max |delta|; raises above the S-7 bound
    ordered = apply_clock_shift(events, delta)
    start = live_from_ns + delta
    base = Pass(selector, False, start, delta, max_rungs).run(ordered)
    stress = Pass(selector, True, start, delta, max_rungs).run(ordered)
    eps = _merge(base, stress, station, climate_day, unit_hypothesis)
    summary = _summarize(eps, base, station, climate_day, unit_hypothesis, delta)
    return StationDayResult(eps, summary)
