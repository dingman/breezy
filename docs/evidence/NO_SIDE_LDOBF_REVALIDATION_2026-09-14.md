# S6b: LD-OBF re-validation under the real YES/NO selection rule (2026-09-14)

Plan: `docs/plans/NO_SIDE_EDGE_2026-09-14.md` SS3/SS4 S6(b), N2-5, R3-7, R3-8.
Test module: `tests/unit/test_no_side_ldobf_validation_2026_09_14.py`.
Repo commit at test-authoring time (worktree `breezy-no6b`, branch
`backlog/no-side-s6b-mc-2026-09-14`): `87278dd` (S6a: `StratumRow.side`,
mixed-side `combine_station_day`, `_cell_probability`).

## H0 assumption (R3-8, stated verbatim)

Conditional on the cell probability `q_i`, the realised `held_i` is
independent of the quoted `BE_i` (no adverse selection beyond the calibrated
price).

## Simulation design (N2-5: the real selection rule)

Per concurrent rung `i` on a simulated station-day (`k` in {1,2,3,4}
mutually-exclusive rungs plus an implicit "none" mass, drawn as a random
simplex point exactly as `_sample_station_day` draws `BE_i`):

- a true H0 probability `p_i` is drawn (the simplex point);
- one categorical draw over the `k` rungs plus "none" fixes which rung
  (if any) actually holds for that station-day -- shared by every leg
  tested on that day;
- the quoted ask on each side is `p_i` (YES) / `1 - p_i` (NO) plus
  `N(0, 0.04)` market-spread noise, clipped to `[0.03, 0.97]`;
  `BE_i = ask_i + fee(ask_i)`, `fee = 0.06 * ask * (1 - ask)` (same theta as
  the rest of this test family);
- a synthetic calibration sample of size `n_cal` in `{90, 300}` is drawn as
  `Binomial(n_cal, p_i)` (`random.Random.binomialvariate`, exact and O(1) --
  the earlier per-trial-loop implementation was replaced for speed, see
  "Performance" below) and converted to Wilson bounds (formula ported from
  `scripts/analysis/archive_correction_probe.wilson_interval`);
- the REAL selection rule fires: YES iff `p_lower_proxy > BE_yes`; NO iff
  `(1 - p_upper_proxy) > BE_no`. YES is checked first per rung, so a rung
  can contribute at most one leg (same-rung YES+NO is structurally
  impossible, pinned by
  `test_same_rung_yes_and_no_are_never_both_admitted`);
- the R3-7 arm-time admission gate admits legs greedily in rung order,
  refusing (dropping) any leg whose own `q` would push the running
  distinct-rung `Sum q` over 1 (pinned by
  `test_admission_gate_refuses_a_take_that_would_breach_distinct_q_sum`).

A "look" advances only on an ADMITTED trade (>=1 leg station-day), not on
every simulated station-day -- most simulated days fire no edge at all, so
many station-days are drawn per look-worth of trades. Boundaries are read
from the artefact's own `reference_table` by linear interpolation at the
realised information fraction, exactly as
`test_multi_position_validation_2026_09_14._run_h0_monte_carlo` already
does; no boundary re-solve.

## (1) Crossing rate per look, k in {1,2,3,4} x n_cal in {90,300}, qty=1

20000 replications/config, `n_max=160`, `look_step=10`, seed
`20260914_000 + k*10 + n_cal`. `alpha=0.025` (artefact
`deploy/families/gs_boundary_pm_us_crh_v2.json`, `inputs_sha256` unchanged --
see "Artefact integrity" below). Cumulative one-sided efficacy-crossing rate
at each look (rate = crossings-by-this-look / 20000):

| look n | k=1,ncal=90 | k=1,ncal=300 | k=2,ncal=90 | k=2,ncal=300 | k=3,ncal=90 | k=3,ncal=300 | k=4,ncal=90 | k=4,ncal=300 |
|---|---|---|---|---|---|---|---|---|
| 10  | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 20  | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 30  | 0 | 0 | 0 | 0 | 0 | 0.00005 | 0 | 0 |
| 40  | 0 | 0 | 0 | 0 | 0.0001 | 0.0001 | 0 | 0.00005 |
| 50  | 0 | 0 | 0.00025 | 0.00025 | 0.0003 | 0.0006 | 0.0002 | 0.00025 |
| 60  | 0.0001 | 0.0001 | 0.0007 | 0.00105 | 0.00115 | 0.00155 | 0.00065 | 0.0011 |
| 70  | 0.0002 | 0.00035 | 0.00165 | 0.00255 | 0.00265 | 0.00355 | 0.00215 | 0.003 |
| 80  | 0.0005 | 0.001 | 0.00345 | 0.0053 | 0.0056 | 0.00745 | 0.0046 | 0.00745 |
| 90  | 0.00085 | 0.0016 | 0.00585 | 0.00895 | 0.009 | 0.01335 | 0.0084 | 0.01595 |
| 100 | 0.00105 | 0.0023 | 0.008 | 0.0133 | 0.01405 | 0.0206 | 0.015 | 0.02645 |
| 110 | 0.00145 | 0.00325 | 0.01055 | 0.0185 | 0.0193 | 0.02975 | 0.02255 | 0.04055 |
| 120 | 0.00235 | 0.0044 | 0.0139 | 0.0248 | 0.02625 | 0.0414 | 0.03445 | 0.0545 |
| 130 | 0.0035 | 0.0061 | 0.01775 | 0.03125 | 0.03465 | 0.0564 | 0.04715 | 0.0722 |
| 140 | 0.0041 | 0.00775 | 0.02145 | 0.03885 | 0.0443 | 0.07175 | 0.06155 | 0.0928 |
| 150 | 0.00565 | 0.0094 | 0.02565 | 0.04745 | 0.0551 | 0.0868 | 0.077 | 0.11615 |
| 160 (terminal) | **0.00685** | **0.0121** | **0.03105** | **0.056** | **0.0666** | **0.10445** | **0.0967** | **0.14105** |

Monte-Carlo SE at `n_reps=20000`, `alpha=0.025`: `SE = sqrt(alpha*(1-alpha)/20000) = 0.001104`,
so the gate is `alpha + 3*SE = 0.02831`.

**k=1**: both `n_cal` well under the gate (0.0069, 0.0121) -- correctly
calibrated, even somewhat conservative.

**k=2**: `n_cal=90` = 0.03105, marginally over the gate (0.02831); `n_cal=300`
= 0.056, clearly over. **k=3,4**: far over at both `n_cal` (0.067-0.141).
The inflation is monotonically increasing in `k` and in `n_cal` -- more
concurrent rungs tested per station-day, and a tighter (larger-`n_cal`)
calibration sample sharpening the Wilson bound, both increase the rate at
which SOME rung's sampling noise clears its own price bar. This is a
multiple-comparison / winner's-curse effect of the real selection rule
(admit whichever of `k` simultaneous edge tests fires), not a bug in the
admission gate or the mutual-exclusion guard -- both are separately pinned
and hold at every `k` (see structural-guard tests, all pass).

**Disposition (evidence for the ruling, not asserted in the gate test at
k>=2):** the plan's LD-OBF re-validation requirement is **NOT met** for
`k>=2` at qty=1 under the real selection rule. Increment A's k=1 case (the
only case that ships today, per R3-2/plan Increment A) is correctly
calibrated. `k>=2` concurrent-rung admission needs a corrected boundary
(likely a multiple-comparison adjustment scaled by admitted-leg count) or
an explicit ruling before it can rely on this artefact -- this mirrors the
existing `test_under_h0_the_ld_obf_boundary_crossing_rate_is_at_most_alpha`
mixed-qty finding in `test_multi_position_validation_2026_09_14.py`, now
shown to recur for mixed-rung-count under the real rule even at qty=1.

## Var(S_terminal) per configuration

`Var_H0(S_terminal)` should be ~1 by the martingale/unit-variance property
if the statistic were correctly calibrated for the admitted-leg population
at that `k`. Measured (terminal, 20000 reps):

| config | Var(S_terminal) |
|---|---|
| k=1, n_cal=90  | 1.036 |
| k=1, n_cal=300 | 1.029 |
| k=2, n_cal=90  | 1.130 |
| k=2, n_cal=300 | 1.159 |
| k=3, n_cal=90  | 1.204 |
| k=3, n_cal=300 | 1.244 |
| k=4, n_cal=90  | 1.295 |
| k=4, n_cal=300 | 1.309 |

Var(S) inflates with `k` in lockstep with the crossing-rate inflation above
-- the same underlying effect (selection among `k` simultaneous tests biases
the admitted population's actual variance above the nominal `Var_H0=1` the
boundary assumes). Only terminal-look variance was computed (not a
per-look variance grid); the per-look table above is the primary evidence.

## (2) Exogeneity stress (R3-8) -- reported, not gated

`corr_rho` shifts the quoted ask toward the realised outcome:
`ask = p + rho*(held - p) + noise`. Baseline config k=2, n_cal=90 (terminal
rate 0.03105) as the comparison point, 20000 reps/config:

| corr_rho | terminal crossing rate |
|---|---|
| 0.00 (baseline) | 0.03105 |
| 0.02 | 0.00065 |
| 0.05 | 0.00000 |

**Finding:** under this module's stress construction, positive correlation
between the quoted ask and the realised outcome *suppresses* the crossing
rate rather than inflating it -- the ask moves toward the truth (more
expensive when it will hold, cheaper when it won't), which is a market that
is MORE informed than the calibration sample, and it makes the trader's
apparent edge (and hence the false-positive rate) smaller, not larger. This
is the opposite of the "adverse selection inflates false positives"
direction the plan text anticipates, and is recorded as a finding for the
ruling: this module's `ask -> held` correlation direction models the
market anticipating the true outcome, not the trader's model being wrong in
a way that manufactures spurious edge. A stress scenario that manufactures
inflation would need to correlate `held` with the CALIBRATION sample's
noise (biased history) instead of the live ask -- out of scope for this
slice; noted for a follow-up if the ruling wants it. Both `corr_rho` values
pass the (reported, non-strict-xfail) `<= alpha` check.

## Structural guards (pass unconditionally, every k)

- `test_same_rung_yes_and_no_are_never_both_admitted`: 5000 draws, k=4 --
  no admitted station-day ever carries both sides of the same rung.
- `test_admission_gate_refuses_a_take_that_would_breach_distinct_q_sum`:
  the R3-7 arm-time gate drops (never truncates) a leg that would breach
  `Sum q <= 1`.

## Artefact integrity

`inputs_sha256` in `deploy/families/gs_boundary_pm_us_crh_v2.json` is
unchanged; not regenerated by this slice. Verified by
`test_the_boundary_inputs_sha256_is_unchanged` in
`tests/unit/test_multi_position_validation_2026_09_14.py` (unedited,
re-run as part of this slice's gate) -- pinned value
`471fd8a7ea781365d0e892cde87a65b5408126c07d8bb28e515b4c493c150e0c`.

## Performance / runtime

- Default (gate) test run: smoke size (`n_reps=120`), `~9-11s` wall for the
  whole module (8 smoke configs + 2 structural guards + Var(S) smoke +
  2 stress smoke), well under the ~60s target.
- Full-size run (this artefact's numbers): 8 crossing-rate configs +
  2 stress configs, `n_reps=20000` each, `n_max=160`, executed once via a
  standalone script (`BREEZY_FULL_MC` gates the pytest equivalent but the
  per-look table needed extra instrumentation not wired into the pytest
  assertion path) -- total wall time **1094.3s (~18m 14s)**, per-config
  times 50-190s (higher `k` and lower `n_cal` take longer: more simulated
  station-days are needed per admitted trade when the edge fires less
  often). ~3.0-3.2M simulated station-days evaluated per config.
- Binomial calibration sampling uses `random.Random.binomialvariate`
  (Python 3.12+, exact and O(1) per draw) rather than an O(n_cal)
  Python-level Bernoulli loop -- an early implementation using the latter
  measured a false, near-certain crossing rate (~0.5-1.0) that was
  diagnosed and fixed as a genuine bug in ask construction for the NO leg
  (`ask_no` was accidentally computed as `1 - quote(1-p)` instead of
  `quote(1-p)`, tracking `p` instead of `1-p`); the binomial-variate swap
  was made at the same time and both cut per-config wall time by
  roughly 5-8x and fixed the mispricing bug.

## No `slow`/`nightly` marker exists in this repo

Checked `pyproject.toml` `[tool.pytest.ini_options].markers` and
`tests/conftest.py::pytest_configure`: only `live`, `venue_live`,
`real_money` are registered, all venue/network gates, none a compute-size
gate. Rather than add a new marker to shared pytest config from this
worktree, the full-size assertion test
(`test_real_selection_rule_crossing_rate_full`) is gated by the
`BREEZY_FULL_MC=1` environment variable (`skipif`) instead, and the
default-collected smoke test enforces the same qty=1/k=1 calibration claim
at reduced replication.
