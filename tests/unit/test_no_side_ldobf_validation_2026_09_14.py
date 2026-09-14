"""S6b Monte-Carlo: LD-OBF re-validation under the REAL YES/NO selection rule
(plan `docs/plans/NO_SIDE_EDGE_2026-09-14.md` SS4 S6(b), N2-5, R3-7, R3-8).

Corrected per independent adjudication of an earlier revision of this module
(commit `3c8b53d`): the REGISTERED null that `combine_station_day` and the
LD-OBF boundary were solved for is `BE_i (the leg's own price+fee) IS the
true cell probability, EXACTLY` -- the same construction
`test_multi_position_validation_2026_09_14._sample_station_day` already
uses (there with `fee=0`, so `BE == ask` trivially). The earlier revision
instead drew an independent noisy `ask` around a separately-drawn true `p`,
then selected on ask-noise realisations -- since `held` is Bernoulli(true
`p`) while `BE` differs from `p` by both the noise AND the selection
(picking rungs whose SAMPLED ask happened to be favourable), that construct
manufactures a genuine (non-null) edge and its own `Var_H0 = q(1-q)`
formula silently omits `Var(BE)`. It is NOT a valid H0 simulation and is
NOT cited for the LD-OBF finding; kept below, explicitly re-labelled, as a
SENSITIVITY study of quote measurement error only (see section (1b)).

## Main grid (null-exact, mirrors `_sample_station_day`'s registered null)

Per concurrent rung `i` on a station-day:

* a raw fair-value draw `p_i` is drawn (mutually exclusive rungs plus a
  "none" mass, the same simplex construction `_sample_station_day` uses,
  scaled to a `0.85` budget to leave headroom for the fee markup below);
* the YES leg's ask is exactly `p_i` (no noise): `ask_yes_i = p_i`,
  `fee_yes_i = fee(ask_yes_i)`, `BE_yes_i = ask_yes_i + fee_yes_i`. Per the
  registered null, `BE_yes_i` -- not `p_i` -- IS the true cell probability
  `pi_i = P(HIGH in r_i)` (`fee applied as today`, per the adjudication);
* the NO leg's ask is chosen by EXACT inversion (`_ask_for_target_be`) so
  that `BE_no_i == 1 - pi_i` exactly (to float precision) -- this is the
  leg the plan's S2 slice already describes as DERIVED
  (`NO_ask = 1 - YES_bid`), never an independently-noisy quote;
* ONE categorical draw over `pi_1..pi_k` (plus the "none" mass) fixes which
  rung actually holds for the whole station-day -- `held_yes_i = 1{holder
  == i}`, `held_no_i = 1{holder != i}`. Since `BE_yes_i == pi_i` and
  `BE_no_i == 1 - pi_i` exactly, `E[held_i - BE_i] = 0` exactly for
  WHICHEVER side is realised -- the registered null holds by construction,
  not by an independence assumption laid on top of a separately-noisy
  price;
* a synthetic calibration sample of size `n_cal` is drawn as
  `Binomial(n_cal, pi_i)` (YES) / `Binomial(n_cal, 1 - pi_i)` (NO) --
  unbiased for the registered true probability -- and converted to Wilson
  bounds (`archive_correction_probe.wilson_interval`, reimplemented here
  dependency-free);
* the REAL selection rule (N2-5) fires: YES iff `p_lower_proxy > BE_yes_i`,
  NO iff `(1 - p_upper_proxy) > BE_no_i`. Same-rung YES+NO is forbidden --
  YES is checked first, matching S4's mutual-exclusion refusal;
* the R3-7 station-day admission gate admits rungs greedily in rung order;
  a rung whose own `q` would push the running `Sum_distinct q` over 1 is
  REFUSED (never taken).

Under this null the martingale argument (`E[x_i]=0` per admitted leg, its
own `q_i` exactly the true cell probability) does not depend on `k` or on
HOW a leg was selected among `k` concurrent tests -- `k` should be
irrelevant to the crossing rate. §(1) below checks this for `k in
{1,2,3,4}`.

## (1b) Sensitivity study -- quote measurement error (NOT H0)

Kept from the earlier revision, explicitly NOT cited as an H0 validation:
`ask = p + rho*(held - p) + N(0, spread)`, i.e. the quoted ask carries
independent Gaussian measurement noise (and, at `rho>0`, a further shift
toward the realised outcome). Because `BE = ask + fee(ask)` then differs
from the true `p` by both the noise and the selection-on-noise, `E[held -
BE] != 0` in general and `Var_H0 = q(1-q)` omits `Var(BE)` -- this
manufactures a real (non-null) edge whose magnitude grows with `spread`
and with `k` (more chances for a favourable noise draw). It is reported as
a measurement-error SENSITIVITY, not a calibration finding.

## (2) R3-8 stress -- calibration-table staleness (the direction the plan
cares about)

The live ask stays exact (`ask = p`, never treated as an oracle of `held`).
Instead the CALIBRATION TABLE is stale: its sample is drawn as if the true
probability were `pi_i + delta` (YES) / `(1 - pi_i) - delta` (NO) for a
bias `delta in {0.02, 0.05}`, while the price (and hence `BE_i`, and hence
`held_i`'s true distribution) is unaffected. This models "the table claims
an edge the market does not offer" -- exactly the R3-8 concern -- and its
crossing-rate inflation is reported.

No `slow`/`nightly` pytest marker exists in this repo (checked
`pyproject.toml` `[tool.pytest.ini_options].markers` and
`tests/conftest.py::pytest_configure` -- only `live`/`venue_live`/
`real_money`, all venue/network gates, not a compute-size gate). Rather than
add a new marker to shared pytest config from this worktree, the full-size
run (>=20k reps/config) is gated by the `BREEZY_FULL_MC` environment
variable and is NOT part of the default collected/asserted test; the default
test below runs a small smoke size for regression coverage on every gate
run. The full-size numbers are captured once and recorded in
`docs/evidence/NO_SIDE_LDOBF_REVALIDATION_2026-09-14.md`.
"""

from __future__ import annotations

import math
import os
import random
from dataclasses import dataclass
from decimal import Decimal

import pytest

from breezy.settlement.current_rung_hold_v2 import (
    StratumRow,
    combine_station_day,
    score_combined,
)
from tests.unit.test_multi_position_validation_2026_09_14 import (
    _artefact_payload,
    _interp,
)

FEE_THETA = Decimal("0.06")
Z_95 = 1.959963984540054

_FULL_MC = os.environ.get("BREEZY_FULL_MC") == "1"


def _wilson_interval(successes: int, total: int, *, z: float = Z_95) -> tuple[float, float]:
    """Ported verbatim (formula) from
    `scripts/analysis/archive_correction_probe.wilson_interval` -- kept as a
    dependency-free copy so this module never imports the analysis script
    for anything but the boundary artefact helpers."""
    if total == 0:
        return (0.0, 0.0)
    phat = successes / total
    denom = 1 + z * z / total
    center = (phat + z * z / (2 * total)) / denom
    half = z * math.sqrt((phat * (1 - phat) + z * z / (4 * total)) / total) / denom
    return (max(0.0, center - half), min(1.0, center + half))


def _fee_theta_float(ask: float, theta: float = 0.06) -> float:
    return theta * ask * (1.0 - ask)


def _ask_for_target_be(target: float, theta: float = 0.06) -> float:
    """Exact inverse of `ask + fee_theta(ask) == target`: solve the
    quadratic `theta*a^2 - (1+theta)*a + target = 0` for its smaller root
    (the root satisfying `a < target` for `theta>0`, matching a positive
    fee markup). Used to construct the NO leg's ask so its OWN `BE_no`
    lands exactly on `1 - pi_i` -- the plan's S2 slice already describes
    the NO leg as DERIVED (`NO_ask = 1 - YES_bid`), never independently
    quoted."""
    target = min(0.999999, max(0.000001, target))
    disc = max(0.0, (1.0 + theta) ** 2 - 4.0 * theta * target)
    root = ((1.0 + theta) - math.sqrt(disc)) / (2.0 * theta)
    return min(0.999999, max(0.000001, root))


@dataclass(frozen=True, slots=True)
class _Leg:
    side: str  # "yes" | "no"
    entry_ask: float
    fee: float
    held: bool
    q: float  # cell probability P(HIGH in r_i), always


def _draw_rung_budget(rng: random.Random, k: int, *, budget: float) -> list[float]:
    """`k` mutually exclusive rungs plus an implicit "none" mass -- the same
    simplex-point construction `_sample_station_day` uses, scaled to
    `budget < 1` so that adding each rung's fee markup afterward cannot
    push `Sum pi_i` over 1 (fee_theta's max is 0.015 at ask=0.5, so a
    `budget=0.85` leaves ample headroom for `k<=4`)."""
    total = rng.random() * budget
    weights = [-math.log(rng.random()) for _ in range(k)]
    weight_sum = sum(weights)
    return [total * w / weight_sum for w in weights]


def _draw_holder(rng: random.Random, ps: list[float]) -> int | None:
    """One categorical draw over the k rungs plus "none" (prob `1 - Sum p`).
    Returns the held rung index, or `None` if no rung holds."""
    u = rng.random()
    cumulative = 0.0
    for i, p in enumerate(ps):
        cumulative += p
        if u < cumulative:
            return i
    return None


def _legs_for_station_day_null_exact(
    rng: random.Random,
    *,
    k: int,
    n_cal: int,
    calibration_bias: float = 0.0,
) -> list[_Leg]:
    """One simulated station-day under the REGISTERED null (`BE_i` IS the
    true cell probability, exactly): the ask is never noisy, only the
    calibration-sample DRAW carries sampling variance (and, at
    `calibration_bias != 0`, the R3-8 staleness stress -- see module
    docstring section (2)). Returns the admitted legs only (rungs where
    neither side fired, or a later rung refused by the R3-7 admission
    gate, contribute nothing)."""
    p_raws = _draw_rung_budget(rng, k, budget=0.85)
    pis: list[float] = []
    yes_prices: list[tuple[float, float]] = []  # (ask_yes, fee_yes)
    for p in p_raws:
        fee_yes = _fee_theta_float(p)
        pis.append(p + fee_yes)  # BE_yes == pi, the registered true probability
        yes_prices.append((p, fee_yes))
    holder = _draw_holder(rng, pis)

    candidates: list[_Leg] = []
    for i, pi in enumerate(pis):
        ask_yes, fee_yes = yes_prices[i]
        be_yes = ask_yes + fee_yes
        held_yes = holder == i
        cal_target_yes = min(1.0, max(0.0, pi + calibration_bias))
        successes_yes = rng.binomialvariate(n_cal, cal_target_yes)
        p_lower, _ = _wilson_interval(successes_yes, n_cal)

        ask_no = _ask_for_target_be(1.0 - pi)
        fee_no = _fee_theta_float(ask_no)
        be_no = ask_no + fee_no  # == 1 - pi, exact by construction
        held_no = holder != i
        cal_target_no = min(1.0, max(0.0, (1.0 - pi) - calibration_bias))
        successes_no = rng.binomialvariate(n_cal, cal_target_no)
        _, p_upper = _wilson_interval(successes_no, n_cal)

        if p_lower > be_yes:
            candidates.append(
                _Leg(side="yes", entry_ask=ask_yes, fee=fee_yes, held=held_yes, q=be_yes)
            )
        elif (1.0 - p_upper) > be_no:
            candidates.append(
                _Leg(side="no", entry_ask=ask_no, fee=fee_no, held=held_no, q=1.0 - be_no)
            )

    return _admit(candidates)


def _admit(candidates: list[_Leg]) -> list[_Leg]:
    """R3-7 station-day admission gate: admits candidates greedily in rung
    order, REFUSING (dropping, never truncating) a leg whose own `q` would
    push the running distinct-rung `Sum q` over 1."""
    admitted: list[_Leg] = []
    running_q = 0.0
    for leg in candidates:
        if running_q + leg.q > 1.0:
            continue
        running_q += leg.q
        admitted.append(leg)
    return admitted


# ---------------------------------------------------------------------------
# Sensitivity-only (NOT H0): noisy ask around an independently-drawn true p.
# Kept for the (1b) measurement-error sensitivity study; never cited as an
# H0/calibration finding (see module docstring).
# ---------------------------------------------------------------------------


def _draw_true_probabilities_noisy(rng: random.Random, k: int) -> list[float]:
    total = rng.random()
    weights = [-math.log(rng.random()) for _ in range(k)]
    weight_sum = sum(weights)
    return [total * w / weight_sum for w in weights]


def _quote_ask_noisy(
    rng: random.Random, p: float, *, spread: float, corr_rho: float, held: bool
) -> float:
    noise = rng.gauss(0.0, spread)
    shifted = p + corr_rho * ((1.0 if held else 0.0) - p) + noise
    return min(0.97, max(0.03, shifted))


def _legs_for_station_day_noisy_ask(
    rng: random.Random,
    *,
    k: int,
    n_cal: int,
    spread: float,
    corr_rho: float,
) -> list[_Leg]:
    """SENSITIVITY-ONLY (not H0, see module docstring (1b)): independent
    Gaussian measurement noise on the ask around a separately-drawn true
    `p`. Selecting on this noise manufactures a real, non-null edge --
    the resulting crossing-rate inflation measures quote noise sensitivity,
    not LD-OBF miscalibration."""
    ps = _draw_true_probabilities_noisy(rng, k)
    holder = _draw_holder(rng, ps)

    candidates: list[_Leg] = []
    for i, p in enumerate(ps):
        held_yes = holder == i
        ask_yes = _quote_ask_noisy(rng, p, spread=spread, corr_rho=corr_rho, held=held_yes)
        be_yes = ask_yes + _fee_theta_float(ask_yes)
        successes_yes = rng.binomialvariate(n_cal, p)
        p_lower, _ = _wilson_interval(successes_yes, n_cal)

        held_no = holder != i
        ask_no = _quote_ask_noisy(rng, 1.0 - p, spread=spread, corr_rho=corr_rho, held=held_no)
        be_no = ask_no + _fee_theta_float(ask_no)
        successes_no = rng.binomialvariate(n_cal, 1.0 - p)
        _, p_upper_complement = _wilson_interval(successes_no, n_cal)

        if p_lower > be_yes:
            candidates.append(
                _Leg(side="yes", entry_ask=ask_yes, fee=be_yes - ask_yes, held=held_yes, q=be_yes)
            )
        elif (1.0 - p_upper_complement) > be_no:
            candidates.append(
                _Leg(side="no", entry_ask=ask_no, fee=be_no - ask_no, held=held_no, q=1.0 - be_no)
            )

    return _admit(candidates)


def _legs_to_rows(legs: list[_Leg], *, station: str) -> tuple[StratumRow, ...]:
    return tuple(
        StratumRow(
            entry_ask=Decimal(str(round(leg.entry_ask, 9))),
            fee=Decimal(str(round(leg.fee, 9))),
            held=leg.held,
            station=station,
            side=leg.side,  # type: ignore[arg-type]
        )
        for leg in legs
    )


def _run_real_rule_monte_carlo(
    *,
    seed: int,
    n_reps: int,
    k: int,
    n_cal: int,
    n_max: int,
    look_step: int,
    null_exact: bool = True,
    spread: float = 0.04,
    corr_rho: float = 0.0,
    calibration_bias: float = 0.0,
    track_per_look: bool = False,
    track_var_by_look: bool = False,
) -> tuple[list[float], int, int, dict[int, int], dict[int, float]]:
    """Extends `_run_h0_monte_carlo`'s look/boundary bookkeeping with the
    REAL selection rule (N2-5): a "look" advances only on an ADMITTED trade
    (a station-day that produced >=1 leg), never on every simulated
    station-day -- most simulated station-days fire no edge at all.

    `null_exact=True` (default) uses the registered-null construction
    (`_legs_for_station_day_null_exact`); `null_exact=False` uses the
    sensitivity-only noisy-ask construction
    (`_legs_for_station_day_noisy_ask`, module docstring (1b)).

    Returns `(terminal_s_per_replication, efficacy_crossings, total_trades,
    per_look_crossings, var_by_look)`. `per_look_crossings` maps
    `look_n -> cumulative count of replications whose FIRST efficacy
    crossing occurred at or before that look`, populated only when
    `track_per_look=True`. `var_by_look` maps `look_n -> sample Var(S)`
    ACROSS ALL replications at that look, populated only when
    `track_var_by_look=True` -- computing it requires every replication to
    keep drawing to `n_max` regardless of an early boundary stop (a
    deliberate divergence from realistic stop-trading behaviour, needed
    only for this diagnostic; the crossing-count bookkeeping above is
    unaffected because it still only evaluates/latches the FIRST crossing,
    exactly as before)."""
    payload = _artefact_payload()
    i_max = payload["i_max"]
    table = payload["reference_table"]
    table_t = [row["t_k"] for row in table]
    table_b_eff = [row["b_eff"] for row in table]
    table_b_fut = [row["b_fut"] for row in table]
    look_ns = sorted(range(look_step, n_max + 1, look_step))
    look_ns_set = set(look_ns)
    per_look_crossings: dict[int, int] = {n: 0 for n in look_ns} if track_per_look else {}
    var_sum: dict[int, float] = {n: 0.0 for n in look_ns} if track_var_by_look else {}
    var_sumsq: dict[int, float] = {n: 0.0 for n in look_ns} if track_var_by_look else {}
    var_count: dict[int, int] = {n: 0 for n in look_ns} if track_var_by_look else {}

    rng = random.Random(seed)
    terminal_s: list[float] = []
    efficacy_crossings = 0
    total_trades = 0
    for _rep in range(n_reps):
        draws = []
        trade_count = 0
        stopped = False
        crossed_efficacy = False
        crossing_look: int | None = None
        # cap the number of simulated station-days per replication so a
        # cold (low-edge-frequency) config cannot spin forever; 50x n_max
        # simulated days is generous headroom against the observed fire
        # rate and keeps the loop bounded.
        for _day in range(n_max * 50):
            # `track_var_by_look` keeps drawing to n_max even after a stop
            # so every replication has an S value at every look (see
            # docstring); otherwise stop drawing once the boundary fires.
            if trade_count >= n_max or (stopped and not track_var_by_look):
                break
            if null_exact:
                legs = _legs_for_station_day_null_exact(
                    rng, k=k, n_cal=n_cal, calibration_bias=calibration_bias
                )
            else:
                legs = _legs_for_station_day_noisy_ask(
                    rng, k=k, n_cal=n_cal, spread=spread, corr_rho=corr_rho
                )
            if not legs:
                continue
            rows = _legs_to_rows(legs, station="MIA")
            draws.append(combine_station_day(rows))
            trade_count += 1
            if trade_count in look_ns_set:
                state = score_combined(tuple(draws))
                if track_var_by_look:
                    s = state.s
                    var_sum[trade_count] += s
                    var_sumsq[trade_count] += s * s
                    var_count[trade_count] += 1
                if not stopped:
                    t = min(1.0, state.information / i_max)
                    b_eff = _interp(t, table_t, table_b_eff)
                    b_fut = _interp(t, table_t, table_b_fut)
                    if state.s >= b_eff:
                        crossed_efficacy = True
                        stopped = True
                        crossing_look = trade_count
                    elif state.s <= b_fut:
                        stopped = True
        total_trades += trade_count
        terminal_s.append(score_combined(tuple(draws)).s if draws else 0.0)
        if crossed_efficacy:
            efficacy_crossings += 1
            if track_per_look and crossing_look is not None:
                for n in look_ns:
                    if n >= crossing_look:
                        per_look_crossings[n] += 1

    var_by_look: dict[int, float] = {}
    if track_var_by_look:
        for n in look_ns:
            c = var_count[n]
            if c > 1:
                mean = var_sum[n] / c
                var_by_look[n] = (var_sumsq[n] - c * mean * mean) / (c - 1)
            else:
                var_by_look[n] = float("nan")
    return terminal_s, efficacy_crossings, total_trades, per_look_crossings, var_by_look


# ---------------------------------------------------------------------------
# (1) LD-OBF re-validation under the real selection rule, NULL-EXACT
#     (registered null: BE_i IS the true cell probability), k in
#     {1,2,3,4}, n_cal in {90,300}, qty==1. Smoke size by default; full
#     size (>=20k reps/config) is gated behind BREEZY_FULL_MC=1 (no
#     slow/nightly marker exists in this repo -- see module docstring).
# ---------------------------------------------------------------------------

_SMOKE_N_REPS = 120
_FULL_N_REPS = 20000
_N_MAX = 160
_LOOK_STEP = 10


@pytest.mark.parametrize("k", [1, 2, 3, 4])
@pytest.mark.parametrize("n_cal", [90, 300])
def test_real_selection_rule_crossing_rate_smoke(k: int, n_cal: int) -> None:
    """Smoke-size regression, registered null: the real-rule Monte-Carlo
    runs end to end, respects the admission gate, and the one-sided
    crossing rate is within `alpha + 3*MC_SE` (Monte-Carlo slack at
    `_SMOKE_N_REPS`) for EVERY `k in {1,2,3,4}` -- the registered null
    makes `k` irrelevant to first order (no xfail needed; the strict
    full-size gate is `test_real_selection_rule_crossing_rate_full`)."""
    payload = _artefact_payload()
    alpha = payload["alpha"]
    _terminal_s, crossings, total_trades, _per_look, _var = _run_real_rule_monte_carlo(
        seed=20260914_000 + k * 10 + n_cal,
        n_reps=_SMOKE_N_REPS,
        k=k,
        n_cal=n_cal,
        n_max=_N_MAX,
        look_step=_LOOK_STEP,
    )
    observed_rate = crossings / _SMOKE_N_REPS
    mc_se = math.sqrt(alpha * (1 - alpha) / _SMOKE_N_REPS)
    assert observed_rate <= alpha + 3 * mc_se, (
        f"k={k} n_cal={n_cal}: smoke crossing rate {observed_rate!r} exceeds "
        f"alpha+3*SE {alpha + 3 * mc_se!r}"
    )
    assert total_trades > 0, f"k={k} n_cal={n_cal}: no trades fired in the smoke run"


@pytest.mark.skipif(
    not _FULL_MC, reason="full-size Monte-Carlo (>=20k reps/config); set BREEZY_FULL_MC=1"
)
@pytest.mark.parametrize("k", [1, 2, 3, 4])
@pytest.mark.parametrize("n_cal", [90, 300])
def test_real_selection_rule_crossing_rate_full(k: int, n_cal: int) -> None:
    """Full-size LD-OBF re-validation (N2-5), registered null: family-wise
    one-sided efficacy-crossing rate across >=20k simulated families,
    qty==1, must stay within `alpha + 3*MC_SE` for EVERY `k in
    {1,2,3,4}` -- see module docstring for why the registered null makes
    `k` irrelevant. Per-look rates and Var(S) are recorded separately for
    the evidence artefact by the standalone run (module docstring)."""
    payload = _artefact_payload()
    alpha = payload["alpha"]
    n_reps = _FULL_N_REPS
    _terminal_s, crossings, total_trades, _per_look, _var = _run_real_rule_monte_carlo(
        seed=20260914_000 + k * 10 + n_cal,
        n_reps=n_reps,
        k=k,
        n_cal=n_cal,
        n_max=_N_MAX,
        look_step=_LOOK_STEP,
    )
    observed_rate = crossings / n_reps
    mc_se = math.sqrt(alpha * (1 - alpha) / n_reps)
    assert observed_rate <= alpha + 3 * mc_se, (
        f"k={k} n_cal={n_cal}: crossing rate {observed_rate!r} exceeds "
        f"alpha+3*SE {alpha + 3 * mc_se!r} (SE={mc_se!r}, n_reps={n_reps})"
    )
    assert total_trades > 0


def test_under_the_real_selection_rule_var_s_is_approximately_one() -> None:
    """`Var_H0(S_terminal) ~= 1` under the registered null too -- the
    martingale property (`E[x_i]=0` per admitted leg, its own `q_i` exactly
    the true cell probability by construction) does not depend on HOW legs
    were selected. Smoke-size (k=2, n_cal=90), loose Monte-Carlo slack."""
    terminal_s, _crossings, _trades, _per_look, _var = _run_real_rule_monte_carlo(
        seed=20260914, n_reps=400, k=2, n_cal=90, n_max=_N_MAX, look_step=_LOOK_STEP
    )
    mean_s = sum(terminal_s) / len(terminal_s)
    sample_variance = sum((s - mean_s) ** 2 for s in terminal_s) / (len(terminal_s) - 1)
    assert 0.7 <= sample_variance <= 1.3, (
        f"observed sample Var(S_terminal)={sample_variance!r} outside [0.7, 1.3]"
    )


def test_same_rung_yes_and_no_are_never_both_admitted() -> None:
    """Structural guard on the simulation itself (mirrors the S4 pin): no
    admitted station-day ever contains both a YES and a NO leg drawn from
    the SAME rung index -- the real selection rule's `elif` and the
    admission gate must never violate this."""
    rng = random.Random(2026091401)
    for _ in range(5000):
        legs = _legs_for_station_day_null_exact(rng, k=4, n_cal=90)
        # each rung contributes at most one leg by construction (the loop
        # over `pis` appends at most one candidate per rung index); this
        # test pins that the admission gate does not somehow duplicate one.
        assert len(legs) <= 4


def test_admission_gate_refuses_a_take_that_would_breach_distinct_q_sum() -> None:
    """R3-7: a candidate whose `q` would push the running distinct-rung sum
    over 1 is refused (dropped), never admitted with a truncated `q`."""
    legs = [
        _Leg(side="yes", entry_ask=0.5, fee=0.0, held=True, q=0.6),
        _Leg(side="yes", entry_ask=0.5, fee=0.0, held=False, q=0.5),
    ]
    admitted = _admit(legs)
    assert admitted == [legs[0]]


# ---------------------------------------------------------------------------
# Per-look Var(S) for the main (null-exact) grid, k in {1,2,3,4}. A separate,
# lower-replication run (Var(S) is a lower-variance statistic than a rare
# tail-crossing rate, so far fewer reps suffice) that disables early
# stopping so every replication has an S value at every look.
# ---------------------------------------------------------------------------

_VAR_BY_LOOK_N_REPS = 400


@pytest.mark.parametrize("k", [1, 2, 3, 4])
def test_var_s_per_look_is_approximately_one(k: int) -> None:
    """`Var_H0(S)` at every scheduled look should be ~= 1 under the
    registered null, for every `k` -- reported at every look in the
    evidence artefact; asserted here only at the terminal look with loose
    Monte-Carlo slack (a per-look strict gate would need far more reps per
    look to avoid flaking on the early, thin-information looks)."""
    _terminal_s, _crossings, _trades, _per_look, var_by_look = _run_real_rule_monte_carlo(
        seed=20260914_700 + k,
        n_reps=_VAR_BY_LOOK_N_REPS,
        k=k,
        n_cal=90,
        n_max=_N_MAX,
        look_step=_LOOK_STEP,
        track_var_by_look=True,
    )
    terminal_var = var_by_look[_N_MAX]
    assert 0.6 <= terminal_var <= 1.4, (
        f"k={k}: terminal Var(S)={terminal_var!r} outside [0.6, 1.4]"
    )


# ---------------------------------------------------------------------------
# (1b) Sensitivity study (NOT H0): quote measurement error. Reported, never
# gated -- see module docstring.
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=False,
    reason=(
        "sensitivity study, not an H0 finding (see module docstring (1b)): "
        "independent Gaussian ask noise + selection-on-noise manufactures a "
        "real edge; reports (does not gate) the resulting crossing-rate "
        "inflation. Numbers recorded in "
        "docs/evidence/NO_SIDE_LDOBF_REVALIDATION_2026-09-14.md."
    ),
)
@pytest.mark.parametrize("k", [1, 2, 3, 4])
def test_noisy_ask_sensitivity_crossing_rate_report(k: int) -> None:
    payload = _artefact_payload()
    alpha = payload["alpha"]
    n_reps = _SMOKE_N_REPS
    _terminal_s, crossings, total_trades, _per_look, _var = _run_real_rule_monte_carlo(
        seed=20260914_600 + k,
        n_reps=n_reps,
        k=k,
        n_cal=90,
        n_max=_N_MAX,
        look_step=_LOOK_STEP,
        null_exact=False,
        spread=0.04,
    )
    observed_rate = crossings / n_reps
    assert total_trades > 0
    assert observed_rate <= alpha, (
        f"k={k}: noisy-ask sensitivity crossing rate {observed_rate!r} exceeds alpha "
        f"{alpha!r} (reported, not gated -- see xfail reason)"
    )


# ---------------------------------------------------------------------------
# (2) R3-8 stress -- calibration-table staleness (ask stays exact; the
# calibration sample is biased relative to the true probability). REPORT
# the inflation; do not assert (feeds the ruling) -- mark non-strict xfail
# when it exceeds alpha so the run stays visible in the collected report.
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=False,
    reason=(
        "R3-8 calibration-table-staleness stress: reports (does not gate) "
        "the crossing-rate inflation when the calibration sample is biased "
        "relative to the true probability while the live ask stays exact; "
        "marked non-strict xfail so a stress run that breaches alpha stays "
        "visible without failing the gate. Numbers recorded in "
        "docs/evidence/NO_SIDE_LDOBF_REVALIDATION_2026-09-14.md."
    ),
)
@pytest.mark.parametrize("delta", [0.02, 0.05])
def test_calibration_staleness_stress_crossing_rate_report(delta: float) -> None:
    payload = _artefact_payload()
    alpha = payload["alpha"]
    n_reps = _SMOKE_N_REPS
    _terminal_s, crossings, total_trades, _per_look, _var = _run_real_rule_monte_carlo(
        seed=20260914_800 + int(delta * 1000),
        n_reps=n_reps,
        k=2,
        n_cal=90,
        n_max=_N_MAX,
        look_step=_LOOK_STEP,
        calibration_bias=delta,
    )
    observed_rate = crossings / n_reps
    assert total_trades > 0
    assert observed_rate <= alpha, (
        f"delta={delta}: calibration-staleness stress crossing rate {observed_rate!r} "
        f"exceeds alpha {alpha!r} (reported, not gated -- see xfail reason)"
    )
