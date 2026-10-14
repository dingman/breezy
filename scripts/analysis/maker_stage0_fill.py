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
episode boundaries are identical, a rung is held from its own pass's fill onward.
"""

from __future__ import annotations

import statistics
from collections.abc import Iterable
from dataclasses import dataclass
from itertools import groupby
from types import MappingProxyType

from scripts.analysis.maker_stage0_fill_events import (
    BUYER,
    CENTS,
    NS_PER_HOUR,
    Cut,
    Decision,
    DecisionContext,
    DepthFrame,
    Desired,
    Episode,
    Event,
    ForecastVector,
    GapMark,
    Kind,
    LeakageError,
    Print,
    RungSelector,
    StationDayResult,
    StationDaySummary,
    apply_clock_shift,
    assert_leak_free,
)

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


@dataclass
class _Live:
    rung_id: str
    t0_ns: int
    bid_cents: int
    a_gt: float
    a_eq: float
    r: float
    g: float
    depth_ts_used_ns: int
    vector: ForecastVector
    gap_ns: int = 0
    gap_since: int | None = None


@dataclass(frozen=True)
class _Rest:
    rung_id: str
    t0_ns: int
    end_ns: int
    end_reason: str
    bid_cents: int
    a_gt: float
    a_eq: float
    refused_reason: str | None
    filled_ns: int | None
    gap_ns: int
    vector: ForecastVector | None
    depth_ts_used_ns: int | None


def _queue_sizes(frame: DepthFrame, bid_cents: int) -> tuple[float, float]:
    """(A_gt, A_eq): displayed NO size at prices > b / exactly b = YES asks at < / = 100 - b."""
    level = CENTS - bid_cents
    a_gt = sum(s for p, s in frame.yes_asks if p < level)
    a_eq = sum(s for p, s in frame.yes_asks if p == level)
    return a_gt, a_eq


def _no_ask_cents(frame: DepthFrame) -> int | None:
    bids = [p for p, s in frame.yes_bids if s > 0]
    return CENTS - max(bids) if bids else None


class _Pass:
    """One full pass of the event stream under the base or the stress rule."""

    def __init__(
        self, selector: RungSelector, stress: bool, live_from_ns: int, delta_ns: int
    ) -> None:
        self.selector, self.stress, self.live_from, self.delta = (
            selector,
            stress,
            live_from_ns,
            delta_ns,
        )
        self.books: dict[str, DepthFrame] = {}
        self.stale: set[str] = set()
        self.open_gaps: dict[str | None, int] = {}
        self.live: dict[str, _Live] = {}
        self.held: set[str] = set()
        self.rests: list[_Rest] = []
        self.vector: ForecastVector | None = None
        self.staged: ForecastVector | None = None
        self.instance = ""
        self.started = self.terminated = self.forecast_valid = False
        self.last_ts = 0
        self.live_ns = self.valid_ns = self.gap_ns = 0
        self.process_cuts = self.gtd_cuts = self.attempts = 0
        self.k1_rung: str | None = None

    def run(self, events: Iterable[Event]) -> _Pass:
        last = self.live_from
        for ts, group in groupby(events, key=lambda e: e.ts_ns):
            self._advance(ts)
            triggered = False
            for event in group:
                triggered = self._apply(event) or triggered
            if triggered and self.started and not self.terminated:
                self._decide(ts)
            if self.staged is not None:
                self.vector, self.staged = self.staged, None
            last = ts
        for ep in list(self.live.values()):
            self._end(ep, last, "END_OF_DATA")
        return self

    def _gapped(self, rung: str) -> bool:
        return rung in self.open_gaps or None in self.open_gaps

    def _advance(self, ts: int) -> None:
        if not self.started and not self.terminated and ts >= self.live_from:
            self.started, self.last_ts = True, self.live_from
        if self.started and not self.terminated:
            dt = ts - self.last_ts
            self.live_ns += dt
            self.valid_ns += dt if self.forecast_valid else 0
            self.gap_ns += dt if self.open_gaps else 0
            self.last_ts = ts

    def _apply(self, event: Event) -> bool:
        """Apply one event; True when it is a decision instant."""
        payload, ts = event.payload, event.ts_ns
        if isinstance(payload, GapMark):
            self._on_gap(event.kind is Kind.GAP_START, payload, ts)
        elif isinstance(payload, Cut):
            return self._on_cut(payload, ts)
        elif isinstance(payload, Print):
            self._on_print(payload, ts)
        elif isinstance(payload, DepthFrame):
            self._on_depth(payload)
            return True
        elif isinstance(payload, ForecastVector):
            self.staged = payload
            return True
        return False

    def _on_gap(self, starting: bool, mark: GapMark, ts: int) -> None:
        if starting:
            self.open_gaps.setdefault(mark.rung_id, ts)
            self.stale.update(self.books if mark.rung_id is None else [mark.rung_id])
            for ep in self.live.values():
                if ep.gap_since is None and self._gapped(ep.rung_id):
                    ep.gap_since = max(ep.t0_ns, ts)
            return
        self.open_gaps.pop(mark.rung_id, None)
        for ep in self.live.values():
            if ep.gap_since is not None and not self._gapped(ep.rung_id):
                ep.gap_ns += ts - ep.gap_since
                ep.gap_since = None

    def _on_cut(self, cut: Cut, ts: int) -> bool:
        if self.started:
            self.gtd_cuts += cut.reason == "GTD_EXPIRY"
            self.process_cuts += cut.reason == "CANCEL_PROCESS"
        for ep in list(self.live.values()):
            self._end(ep, ts, cut.reason)
        if not cut.resume:
            self.terminated = True
        return cut.resume

    def _on_depth(self, frame: DepthFrame) -> None:
        self.books[frame.rung_id] = frame
        self.instance = frame.instance_id or self.instance
        if not self._gapped(frame.rung_id):
            self.stale.discard(frame.rung_id)

    def _on_print(self, pr: Print, ts: int) -> None:
        self.instance = pr.instance_id or self.instance
        ep = self.live.get(pr.rung_id)
        if ep is None or pr.aggressor != BUYER or self._gapped(pr.rung_id) or ts <= ep.t0_ns:
            return
        if CENTS - pr.yes_price_cents > ep.bid_cents:  # consumed better-priced bids
            taken = min(pr.size, ep.g)
            ep.g -= taken
            ep.r -= taken
        else:  # at or below b: consumes the remaining queue
            ep.r -= pr.size
            ep.g = max(0.0, ep.g - pr.size)
        if ep.r <= 0:
            self._end(ep, ts, "FILLED", filled=ts)

    def _decide(self, ts: int) -> None:
        ctx = DecisionContext(
            ts,
            self.vector,
            MappingProxyType(self.books),
            {r: ep.bid_cents for r, ep in self.live.items()},
            frozenset(self.held),
        )
        dec = self.selector(ctx)
        self.forecast_valid = dec.forecast_valid
        want = {d.rung_id: d for d in dec.desired if d.rung_id not in self.held}
        if want and self.k1_rung is None:
            self.k1_rung = next(iter(want))
        for rung, ep in list(self.live.items()):
            if rung not in want:
                self._end(ep, ts, dec.drop_reason)
            elif want[rung].bid_cents != ep.bid_cents:
                self._end(ep, ts, "REPLACED")
            elif self.vector is not None:
                ep.vector = (
                    self.vector
                )  # same price: the episode continues under the vector in force
        for rung, desired in want.items():
            if rung not in self.live:
                self._attempt(ts, desired)

    def _refusal(self, rung: str, bid: int) -> str | None:
        frame = self.books.get(rung)
        if frame is None or rung in self.stale or frame.instance_id != self.instance:
            return "STALE_FRAME"
        if frame.truncated:
            return "TRUNCATED_FRAME"
        no_ask = _no_ask_cents(frame)
        return "MARKETABLE" if no_ask is not None and bid >= no_ask else None

    def _attempt(self, ts: int, d: Desired) -> None:
        self.attempts += 1
        reason = self._refusal(d.rung_id, d.bid_cents)
        if reason is not None:
            self.rests.append(
                _Rest(d.rung_id, ts, ts, "REFUSED", d.bid_cents, 0, 0, reason, None, 0, None, None)
            )
            return
        frame, vector = self.books[d.rung_id], self.vector
        if vector is None:
            raise LeakageError(f"selector desired {d.rung_id} with no forecast vector in force")
        a_gt, a_eq = _queue_sizes(frame, d.bid_cents)
        factor = 2 if self.stress else 1
        assert_leak_free(
            available_at_ns=vector.available_at_ns,
            delta_ns=self.delta,
            t0_ns=ts,
            depth_ts_used_ns=ts,
            filled_ns=None,
        )
        self.live[d.rung_id] = _Live(
            d.rung_id,
            ts,
            d.bid_cents,
            a_gt,
            a_eq,
            factor * (a_gt + a_eq + 1),
            factor * a_gt,
            ts,
            vector,
        )

    def _end(self, ep: _Live, ts: int, reason: str, filled: int | None = None) -> None:
        if ep.gap_since is not None:
            ep.gap_ns += ts - ep.gap_since
        if filled is not None:
            self.held.add(ep.rung_id)
        del self.live[ep.rung_id]
        self.rests.append(
            _Rest(
                ep.rung_id,
                ep.t0_ns,
                ts,
                reason,
                ep.bid_cents,
                ep.a_gt,
                ep.a_eq,
                None,
                filled,
                ep.gap_ns,
                ep.vector,
                ep.depth_ts_used_ns,
            )
        )


def _to_episode(
    rest: _Rest, base: _Rest | None, stress: _Rest | None, station: str, day: str, unit: str
) -> Episode:
    vec = rest.vector
    return Episode(
        station, day, rest.rung_id, rest.t0_ns, rest.end_ns, rest.end_reason, rest.bid_cents,
        rest.a_gt, rest.a_eq, rest.refused_reason,
        base.filled_ns if base else None, stress.filled_ns if stress else None, rest.gap_ns,
        vec.p_yes_point[rest.rung_id] if vec else None,
        vec.p_yes_upper[rest.rung_id] if vec else None,
        vec.cycle_runtime_ns if vec else None, vec.raw_sha256 if vec else None,
        vec.nbm_era if vec else None, vec.available_at_ns if vec else None,
        rest.depth_ts_used_ns, unit,
    )  # fmt: skip


def _merge(base: _Pass, stress: _Pass, station: str, day: str, unit: str) -> tuple[Episode, ...]:
    """Key (rung, t0): the base record leads; stress-only rests follow a base fill (rung held)."""
    b = {(r.rung_id, r.t0_ns): r for r in base.rests}
    s = {(r.rung_id, r.t0_ns): r for r in stress.rests}
    keys = sorted(b.keys() | s.keys(), key=lambda k: (k[1], k[0]))
    return tuple(
        _to_episode(b.get(k) or s[k], b.get(k), s.get(k), station, day, unit) for k in keys
    )


def _filled_rungs(eps: Iterable[Episode], stressed: bool) -> set[str]:
    return {
        e.rung_id for e in eps if (e.filled_ns_stress if stressed else e.filled_ns_base) is not None
    }


def _summarize(
    eps: tuple[Episode, ...], base: _Pass, k1: str | None, ctx: tuple[str, str, str, int]
) -> StationDaySummary:
    station, day, unit, delta = ctx
    placed = [e for e in eps if e.refused_reason is None]
    f_base, f_stress = _filled_rungs(placed, False), _filled_rungs(placed, True)
    refused = sum(1 for r in base.rests if r.refused_reason is not None)
    n_eps = sum(1 for r in base.rests if r.refused_reason is None)
    fills = [e.bid_cents / CENTS for e in placed if e.filled_ns_stress is not None]
    live_h, valid_h = base.live_ns / NS_PER_HOUR, base.valid_ns / NS_PER_HOUR
    gap_h = base.gap_ns / NS_PER_HOUR
    return StationDaySummary(
        station, day, unit, base.attempts > 0, base.attempts > 0 and n_eps == 0,
        base.attempts, n_eps, refused, base.process_cuts, base.gtd_cuts,
        len({e.rung_id for e in placed}), len(f_base), len(f_stress), len(f_base), len(f_stress),
        k1, int(k1 in f_base), int(k1 in f_stress),
        statistics.median(fills) if fills else None, delta,
        live_h, valid_h, gap_h, live_h - gap_h, gap_h / valid_h if valid_h > 0 else None,
    )  # fmt: skip


def simulate_station_day(
    events: Iterable[Event],
    selector: RungSelector,
    *,
    station: str,
    climate_day: str,
    unit_hypothesis: str,
    live_from_ns: int,
    delta_ns: int = 0,
) -> StationDayResult:
    """Run the base and the stress rule over one station-day's events (venue clock).

    ``delta_ns`` is applied as a magnitude, pessimistically (forecast +, cancels -); the live
    window opens ``|delta|`` later. Decisions need the selector; nothing here reads truth.
    """
    delta = abs(delta_ns)
    ordered = apply_clock_shift(events, delta)
    start = live_from_ns + delta
    base = _Pass(selector, False, start, delta).run(ordered)
    stress = _Pass(selector, True, start, delta).run(ordered)
    eps = _merge(base, stress, station, climate_day, unit_hypothesis)
    summary = _summarize(eps, base, base.k1_rung, (station, climate_day, unit_hypothesis, delta))
    return StationDayResult(eps, summary)
