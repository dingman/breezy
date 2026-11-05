"""MAKER-S2 WP4: one pass (base or stress) of the Stage 0 fill simulator (pure; no I/O, no truth).

Split from ``maker_stage0_fill``. Rule source: spec v0.3 section 6.1
(``docs/strategies/SPEC_pm_us_no_ladder_maker_2026-10-12.md:232-247``); plan r3 WP4 (L148-172).

Ordering notes (documented behaviour, all conservative or neutral for the fill rate):
* Equal-timestamp order is ``Kind``: gap-start, process/GTD/hard cuts, prints, depth frames,
  gap-end, releases, decisions. A DEPTH or PRINT at a GAP_END timestamp is still inside the gap.
* Selector-driven cancels (``DECIDE``/DEPTH-triggered) run after same-timestamp prints are credited
  (a reaction cannot precede the trade it reacts to); only clock ``Cut`` events precede credits.
* A day that never sees a terminating cut closes with ``END_OF_DATA``; WP6 reports that count.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from itertools import groupby
from types import MappingProxyType

from scripts.analysis.maker_stage0_fill_events import (
    BUYER,
    CENTS,
    Cut,
    DecideMark,
    Decision,
    DecisionContext,
    DepthFrame,
    Desired,
    Event,
    ForecastVector,
    GapMark,
    Kind,
    LeakageError,
    Print,
    RungSelector,
    assert_leak_free,
)

REFUSED = "REFUSED"
STALE_FRAME = "STALE_FRAME"
TRUNCATED_FRAME = "TRUNCATED_FRAME"
MARKETABLE = "MARKETABLE"


@dataclass
class Live:
    rung_id: str
    t0_ns: int
    bid_cents: int
    a_gt: int
    a_eq: int
    r: int  # remaining queue ahead of (and including) our unit
    g: int  # strictly-better-priced size a print may still consume
    depth_ts_used_ns: int
    placed_vector: ForecastVector
    gap_ns: int = 0
    gap_since: int | None = None


@dataclass(frozen=True)
class Rest:
    """A finished episode of one pass (a refused attempt is a zero-length ``REFUSED`` rest)."""

    rung_id: str
    t0_ns: int
    end_ns: int
    end_reason: str
    bid_cents: int
    a_gt: int
    a_eq: int
    refused_reason: str | None
    filled_ns: int | None
    gap_ns: int
    vector: ForecastVector | None  # the vector in force at the end (the fill instant if filled)
    depth_ts_used_ns: int | None


def queue_sizes(frame: DepthFrame, bid_cents: int) -> tuple[int, int]:
    """(A_gt, A_eq): displayed NO size at prices > b / exactly b = YES asks at < / = 100 - b."""
    level = CENTS - bid_cents
    a_gt = sum(s for p, s in frame.yes_asks if p < level)
    a_eq = sum(s for p, s in frame.yes_asks if p == level)
    return a_gt, a_eq


def no_ask_cents(frame: DepthFrame) -> int | None:
    bids = [p for p, s in frame.yes_bids if s > 0]
    return CENTS - max(bids) if bids else None


def _validate_desired(dec: Decision, max_rungs: int) -> dict[str, Desired]:
    seen: dict[str, Desired] = {}
    for d in dec.desired:
        if d.rung_id in seen:
            raise ValueError(f"duplicate rung {d.rung_id} in Decision.desired")
        if not 1 <= d.bid_cents <= CENTS - 1:
            raise ValueError(f"bid {d.bid_cents} for {d.rung_id} outside 1..99 cents")
        seen[d.rung_id] = d
    if max_rungs < 1:
        raise ValueError("max_rungs must be >= 1")
    return seen


class Pass:
    """One full pass of the event stream under the base or the stress rule."""

    def __init__(
        self,
        selector: RungSelector,
        stress: bool,
        live_from_ns: int,
        delta_ns: int,
        max_rungs: int,
    ) -> None:
        self.selector = selector
        self.stress = stress
        self.live_from = live_from_ns
        self.delta = delta_ns
        self.max_rungs = max_rungs
        self.books: dict[str, DepthFrame] = {}
        self.stale: set[str] = set()
        self.open_gaps: dict[str | None, int] = {}  # key -> number of overlapping open gaps
        self.live: dict[str, Live] = {}
        self.held: set[str] = set()
        self.posted: set[str] = set()
        self.rests: list[Rest] = []
        self.vector: ForecastVector | None = None
        self.staged: ForecastVector | None = None
        self.instance = ""
        self.started = self.terminated = self.forecast_valid = False
        self.last_ts = 0
        self.live_ns = self.valid_ns = self.gap_ns = 0
        self.process_cuts = self.gtd_cuts = self.attempts = 0
        self.k1_rung: str | None = None

    def run(self, events: Iterable[Event]) -> Pass:
        last = self.live_from
        for ts, group in groupby(events, key=lambda e: e.ts_ns):
            self._advance(ts)
            triggered = False
            for event in group:
                triggered = self._apply(event) or triggered
            if triggered and self.started and not self.terminated:
                self._decide(ts)
            if self.staged is not None:  # visible strictly after its (shifted) release ts
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
            self.staged = payload  # the decision is the DECIDE event at release + 1 ns
        elif isinstance(payload, DecideMark):
            return True
        return False

    def _on_gap(self, starting: bool, mark: GapMark, ts: int) -> None:
        key = mark.rung_id
        if starting:
            self.open_gaps[key] = self.open_gaps.get(key, 0) + 1
            self.stale.update(self.books if key is None else [key])
            for ep in self.live.values():
                if ep.gap_since is None and self._gapped(ep.rung_id):
                    ep.gap_since = max(ep.t0_ns, ts)
            return
        remaining = self.open_gaps.get(key, 0) - 1
        if remaining > 0:
            self.open_gaps[key] = remaining
        else:
            self.open_gaps.pop(key, None)
        for ep in self.live.values():
            if ep.gap_since is not None and not self._gapped(ep.rung_id):
                ep.gap_ns += ts - ep.gap_since
                ep.gap_since = None

    def _on_cut(self, cut: Cut, ts: int) -> bool:
        if self.started and cut.reason == "GTD_EXPIRY":
            self.gtd_cuts += 1
        elif self.started and cut.reason == "CANCEL_PROCESS":
            self.process_cuts += 1
        for ep in list(self.live.values()):
            self._end(ep, ts, cut.reason)
        if not cut.resume:
            self.terminated = True
        return cut.resume

    def _on_depth(self, frame: DepthFrame) -> None:
        self.books[frame.rung_id] = frame
        self.instance = frame.instance_id or self.instance
        if self._gapped(frame.rung_id):
            self.stale.add(frame.rung_id)  # a frame received inside a gap is not trusted
        else:
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
            ep.g = max(0, ep.g - pr.size)
        if ep.r <= 0:
            assert_leak_free(
                available_at_ns=ep.placed_vector.available_at_ns,
                delta_ns=self.delta,
                t0_ns=ep.t0_ns,
                depth_ts_used_ns=ep.depth_ts_used_ns,
                filled_ns=ts,
            )
            self._end(ep, ts, "FILLED", filled=ts)

    def _decide(self, ts: int) -> None:
        ctx = DecisionContext(
            now_ns=ts,
            vector=self.vector,
            books=MappingProxyType(dict(self.books)),
            live_bids={r: ep.bid_cents for r, ep in self.live.items()},
            held=frozenset(self.held),
        )
        dec = self.selector(ctx)
        self.forecast_valid = dec.forecast_valid
        want = {
            r: d for r, d in _validate_desired(dec, self.max_rungs).items() if r not in self.held
        }
        if want and self.k1_rung is None:
            self.k1_rung = next(iter(want))
        for rung, ep in list(self.live.items()):
            if rung not in want:
                self._end(ep, ts, dec.reason_for(rung))
            elif want[rung].bid_cents != ep.bid_cents:
                self._end(ep, ts, "REPLACED")
        slots = self.max_rungs - len(self.held) - len(self.live)
        for rung, desired in want.items():
            if rung in self.live or rung not in self.books:
                continue  # already resting, or no book yet to bid against (not an attempt)
            if slots <= 0:
                break  # position cap: never more than max_rungs held + live
            slots -= self._attempt(ts, desired)

    def _refusal(self, rung: str, bid: int) -> str | None:
        frame = self.books[rung]
        if rung in self.stale or frame.instance_id != self.instance:
            return STALE_FRAME
        level = CENTS - bid
        if frame.asks_truncated and (
            not frame.yes_asks or level > max(p for p, _ in frame.yes_asks)
        ):
            return TRUNCATED_FRAME  # YES-ask side censored at our level: A_gt / A_eq are unknown
        no_ask = no_ask_cents(frame)
        return MARKETABLE if no_ask is not None and bid >= no_ask else None

    def _attempt(self, ts: int, d: Desired) -> int:
        """Try to place; returns 1 when a live rest results (consumes a position slot)."""
        vector = self.vector
        if vector is None:
            raise LeakageError(f"selector desired {d.rung_id} with no forecast vector in force")
        self.attempts += 1
        reason = self._refusal(d.rung_id, d.bid_cents)
        if reason is not None:
            self.rests.append(
                Rest(d.rung_id, ts, ts, REFUSED, d.bid_cents, 0, 0, reason, None, 0, None, None)
            )
            return 0
        frame = self.books[d.rung_id]
        a_gt, a_eq = queue_sizes(frame, d.bid_cents)
        factor = 2 if self.stress else 1
        assert_leak_free(
            available_at_ns=vector.available_at_ns,
            delta_ns=self.delta,
            t0_ns=ts,
            depth_ts_used_ns=frame.ts_ns,
            filled_ns=None,
        )
        self.posted.add(d.rung_id)
        self.live[d.rung_id] = Live(
            d.rung_id, ts, d.bid_cents, a_gt, a_eq,
            factor * (a_gt + a_eq + 1), factor * a_gt, frame.ts_ns, vector,
        )  # fmt: skip
        return 1

    def _end(self, ep: Live, ts: int, reason: str, filled: int | None = None) -> None:
        if ep.gap_since is not None:
            ep.gap_ns += ts - ep.gap_since
        if filled is not None:
            self.held.add(ep.rung_id)
        del self.live[ep.rung_id]
        self.rests.append(
            Rest(
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
                self.vector or ep.placed_vector,
                ep.depth_ts_used_ns,
            )
        )
