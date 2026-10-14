"""MAKER-S2 S-5 time round: replay OUTCOMES stay byte-identical while the hot path is optimised.

A seeded synthetic station-day (five rungs, thousands of frames, prints, gaps, cuts, releases) runs
through ``simulate_station_day``; the SHA-256 of every episode and the summary is pinned. The pins
were taken on the pre-optimisation code (d563e702); any drift in a fill decision, a bid, a gap or a
rate input changes them.
"""

from __future__ import annotations

import hashlib
import json
import random
from typing import Any

import pytest

from scripts.analysis import maker_stage0_fill as fill
from scripts.analysis import maker_stage0_fill_events as ev

SEC = 1_000_000_000
T0 = 1_000_000 * SEC
RUNGS = ("R1", "R2", "R3", "R4", "R5")
N_STEPS = 6_000
#: delta -> sha256 of the canonical JSON of (episodes, summary); taken on d563e702
PINNED = {
    0: "ccd6aded6db48a8081aaf111bf8df4306910c59ee3adfb1e414c0c9ea857f686",
    7 * SEC: "b13393bc827497a6589b5e53c5c9ca3d11d78dc41335b69b5ad1d54120480638",
}


def _world(seed: int) -> list[ev.Event]:
    rnd = random.Random(seed)
    raw: list[tuple[int, ev.Kind, ev.Payload]] = []
    ts = T0
    for _ in range(N_STEPS):
        ts += rnd.randint(1, 4) * SEC // 2
        rung = rnd.choice(RUNGS)
        roll = rnd.random()
        if roll < 0.55:
            asks = tuple(
                sorted({(rnd.randint(8, 40), rnd.randint(0, 30)) for _ in range(rnd.randint(1, 4))})
            )
            bids = tuple((rnd.randint(1, 7), rnd.randint(1, 20)) for _ in range(rnd.randint(0, 2)))
            frame = ev.DepthFrame(
                rung_id=rung, ts_ns=ts, yes_bids=bids, yes_asks=asks,
                asks_truncated=rnd.random() < 0.05,
                instance_id="i1" if ts < T0 + 9000 * SEC else "i2",
            )  # fmt: skip
            raw.append((ts, ev.Kind.DEPTH, frame))
        elif roll < 0.93:
            aggressor = ev.BUYER if rnd.random() < 0.8 else ev.SELLER
            pr = ev.Print(rung, rnd.randint(8, 40), rnd.randint(1, 12), aggressor, "i1")
            raw.append((ts, ev.Kind.PRINT, pr))
        elif roll < 0.96:
            end = ts + rnd.randint(1, 60) * SEC
            mark = ev.GapMark(rung if rnd.random() < 0.7 else None)
            raw += [(ts, ev.Kind.GAP_START, mark), (end, ev.Kind.GAP_END, mark)]
        else:
            vec = ev.ForecastVector(
                available_at_ns=ts,
                p_yes_point={r: rnd.random() * 0.3 for r in RUNGS},
                p_yes_upper={r: 0.4 for r in RUNGS},
                cycle_runtime_ns=ts - 5 * SEC, raw_sha256="sha", nbm_era="v5",
            )  # fmt: skip
            raw.append((ts, ev.Kind.FORECAST_RELEASE, vec))
    for i, at in enumerate(range(700, 14_000, 700)):
        reason = "CANCEL_PROCESS" if i % 2 else "GTD_EXPIRY"
        raw.append((T0 + at * SEC + 1, ev.Kind.CANCEL, ev.Cut(reason, True)))
    raw.append((ts + SEC, ev.Kind.CANCEL, ev.Cut("CANCEL_HARD", False)))
    raw.sort(key=lambda r: (r[0], r[1]))
    return [ev.Event(t, k, i, p) for i, (t, k, p) in enumerate(raw)]


def _selector(ctx: ev.DecisionContext) -> ev.Decision:
    if ctx.vector is None:
        return ev.Decision()
    wants: list[ev.Desired] = []
    for rung in sorted(ctx.books):
        frame = ctx.books[rung]
        p_yes = ctx.vector.p_yes_point.get(rung, 1.0)
        if rung in ctx.held or p_yes > 0.2 or not frame.yes_asks:
            continue
        top = min(p for p, _ in frame.yes_asks)
        bid = max(1, min(99, ev.CENTS - top - (ctx.now_ns // SEC) % 2))
        wants.append(ev.Desired(rung, bid))
    return ev.Decision(tuple(wants), drop_reason=ev.CANCEL_PMIN, forecast_valid=True)


def _digest(delta: int) -> str:
    result = fill.simulate_station_day(
        _world(20261014), _selector, station="KSFO", climate_day="2026-10-10",
        unit_hypothesis="CONTRACTS", live_from_ns=T0 + 30 * SEC, delta_ns=delta, max_rungs=2,
    )  # fmt: skip
    body: dict[str, Any] = {
        "episodes": [e.to_dict() for e in result.episodes],
        "summary": result.summary.to_dict(),
    }
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()


def test_the_synthetic_world_is_rich_enough_to_pin_something() -> None:
    result = fill.simulate_station_day(
        _world(20261014), _selector, station="KSFO", climate_day="2026-10-10",
        unit_hypothesis="CONTRACTS", live_from_ns=T0 + 30 * SEC, delta_ns=0, max_rungs=2,
    )  # fmt: skip
    eps = result.episodes
    assert len(eps) > 50
    assert any(e.filled_ns_base is not None for e in eps)
    assert any(e.refused_reason is not None for e in eps)
    assert {"CANCEL_PROCESS", "GTD_EXPIRY", "REPLACED"} <= {e.end_reason for e in eps}


@pytest.mark.parametrize("delta", sorted(PINNED))
def test_simulate_station_day_outcomes_are_byte_identical_to_the_pre_optimisation_pin(
    delta: int,
) -> None:
    assert _digest(delta) == PINNED[delta]
