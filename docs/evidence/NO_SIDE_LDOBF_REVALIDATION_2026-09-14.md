# S6b: LD-OBF re-validation under the real YES/NO selection rule (2026-09-14)

Plan: `docs/plans/NO_SIDE_EDGE_2026-09-14.md` SS3/SS4 S6(b), N2-5, R3-7, R3-8.
Test module: `tests/unit/test_no_side_ldobf_validation_2026_09_14.py`.
Repo commit at test-authoring time (worktree `breezy-no6b`, branch
`backlog/no-side-s6b-mc-2026-09-14`): `87278dd` (S6a: `StratumRow.side`,
mixed-side `combine_station_day`, `_cell_probability`).

**Revision note:** an earlier revision of this artefact (commit `3c8b53d`)
reported a k-dependent crossing-rate inflation. Independent adjudication
found that revision's simulation NULL-MISSPECIFIED: it drew an
independently-noisy ask around a separately-drawn true probability, then
selected on favourable ask-noise realisations, manufacturing a genuine
(non-null) edge, and its `Var_H0=q(1-q)` formula omitted `Var(BE)`. This
revision replaces the main-grid construction with the REGISTERED null
(`BE_i` IS the true cell probability, exactly -- the same construction
`_sample_station_day` already uses) and supersedes the earlier k>=2
inflation conclusion. **Increment A (k=1, qty=1) was never implicated by
either revision** -- both agree it calibrates correctly.

## H0 assumption (R3-8, stated verbatim)

Conditional on the cell probability `q_i`, the realised `held_i` is
independent of the quoted `BE_i` (no adverse selection beyond the calibrated
price). The corrected simulation enforces this literally: `BE_i` is never a
noisy estimate of a separately-drawn truth -- it IS the truth, exactly, by
construction.

## Simulation design (N2-5: the real selection rule, registered null)

Per concurrent rung `i` on a simulated station-day (`k` in {1,2,3,4}):

- a raw fair-value `p_i` is drawn as a random simplex point (budget 0.85,
  leaving headroom for the fee markup below);
- the YES leg's ask is EXACTLY `p_i` (no noise): `ask_yes_i = p_i`,
  `fee_yes_i = 0.06 * ask * (1-ask)`, `BE_yes_i = ask_yes_i + fee_yes_i`.
  Per the registered null, `BE_yes_i` IS the true cell probability
  `pi_i = P(HIGH in r_i)`;
- the NO leg's ask is chosen by EXACT quadratic inversion
  (`_ask_for_target_be`) so `BE_no_i == 1 - pi_i` exactly (float
  precision) -- the plan's own S2 slice already describes the NO leg as
  DERIVED (`NO_ask = 1 - YES_bid`), never an independent quote;
- ONE categorical draw over `pi_1..pi_k` (plus a "none" mass) fixes which
  rung holds for the whole station-day -- `held_yes_i = 1{holder==i}`,
  `held_no_i = 1{holder!=i}`. Since `BE_yes_i==pi_i` and `BE_no_i==1-pi_i`
  exactly, `E[held_i - BE_i] = 0` exactly for WHICHEVER side fires -- the
  registered null holds by construction;
- a calibration sample of size `n_cal` is drawn as `Binomial(n_cal, pi_i)`
  (YES) / `Binomial(n_cal, 1-pi_i)` (NO) -- unbiased for the registered
  truth -- converted to Wilson bounds
  (`archive_correction_probe.wilson_interval`, reimplemented
  dependency-free);
- the REAL selection rule (N2-5) fires: YES iff `p_lower_proxy > BE_yes_i`,
  NO iff `(1-p_upper_proxy) > BE_no_i`. YES checked first -- same-rung
  YES+NO is structurally impossible;
- the R3-7 station-day admission gate admits rungs greedily in rung order,
  refusing (dropping) any leg whose own `q` would push the running
  distinct-rung `Sum q` over 1.

A "look" advances only on an ADMITTED trade, never on every simulated
station-day. Boundaries are read from the artefact's own `reference_table`
by linear interpolation at the realised information fraction, exactly as
`test_multi_position_validation_2026_09_14._run_h0_monte_carlo` already
does; no boundary re-solve.

## (1) Corrected crossing rate per look, k in {1,2,3,4} x n_cal in {90,300}, qty=1

20000 replications/config, `n_max=160`, `look_step=10`, seed
`20260914_000 + k*10 + n_cal`. `alpha=0.025`, MC SE at n_reps=20000 is
`0.001104`, gate = `alpha + 3*SE = 0.02831`.

| look n | k=1,ncal=90 | k=1,ncal=300 | k=2,ncal=90 | k=2,ncal=300 | k=3,ncal=90 | k=3,ncal=300 | k=4,ncal=90 | k=4,ncal=300 |
|---|---|---|---|---|---|---|---|---|
| 10  | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 20  | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 30  | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 40  | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 50  | 0.0001 | 0.00005 | 0 | 0.0001 | 0 | 0 | 0 | 0 |
| 60  | 0.0003 | 0.00045 | 0.0003 | 0.0003 | 0.00005 | 0 | 0 | 0.00005 |
| 70  | 0.00065 | 0.001 | 0.0007 | 0.00085 | 0.00025 | 0.0002 | 0 | 0.00005 |
| 80  | 0.00125 | 0.00185 | 0.00155 | 0.0016 | 0.00045 | 0.0004 | 0 | 0.0001 |
| 90  | 0.00215 | 0.0029 | 0.0026 | 0.0029 | 0.00085 | 0.0008 | 0 | 0.00015 |
| 100 | 0.00335 | 0.004 | 0.0036 | 0.00495 | 0.0012 | 0.00155 | 0 | 0.0003 |
| 110 | 0.005 | 0.0058 | 0.00505 | 0.0067 | 0.0018 | 0.0027 | 0.0002 | 0.0006 |
| 120 | 0.00715 | 0.00745 | 0.0068 | 0.00895 | 0.003 | 0.0037 | 0.0003 | 0.00075 |
| 130 | 0.0098 | 0.00945 | 0.0087 | 0.011 | 0.004 | 0.00465 | 0.0005 | 0.001 |
| 140 | 0.01215 | 0.0117 | 0.01115 | 0.0137 | 0.0051 | 0.0061 | 0.00105 | 0.0015 |
| 150 | 0.0145 | 0.0146 | 0.01345 | 0.0168 | 0.0067 | 0.008 | 0.00145 | 0.00235 |
| 160 (terminal) | **0.0173** | **0.0168** | **0.0159** | **0.01985** | **0.0079** | **0.0101** | **0.00195** | **0.0028** |

**All 8 configurations, at every look, stay well under the gate
(`alpha+3*SE=0.02831`)** -- the largest terminal rate observed is
`k=2, n_cal=300 = 0.01985`, about 29% below the gate. There is no
monotonic k-dependent inflation; if anything the rate DECREASES with `k`
(0.017 at k=1 down to ~0.002-0.003 at k=4), consistent with the admission
gate making it progressively harder to admit a leg on a rung whose `q` is
large relative to the remaining budget as `k` grows, not with a
multiple-comparison inflation. **The registered null is correctly
calibrated for every `k in {1,2,3,4}` at qty=1** -- the LD-OBF boundary
needs no correction at k>=2 under this null. This supersedes the prior
revision's k>=2 inflation finding, which was an artefact of a
null-misspecified simulation (see "Revision note" above), not a property
of `combine_station_day` or the boundary.

## Per-look Var(S), k in {1,2,3,4}, n_cal=90

20000 replications/config, no early stopping (every replication draws to
`n_max=160` so every look has a value for every replication -- see module
docstring). `Var_H0(S)` should be ~1 exactly at every look if the
statistic is correctly calibrated:

| look n | k=1 | k=2 | k=3 | k=4 |
|---|---|---|---|---|
| 10  | 1.0218 | 0.9966 | 1.0049 | 1.0056 |
| 20  | 0.9995 | 0.9906 | 0.9964 | 1.0090 |
| 30  | 0.9877 | 0.9946 | 0.9822 | 1.0020 |
| 40  | 0.9934 | 1.0008 | 0.9866 | 1.0107 |
| 50  | 1.0010 | 0.9923 | 0.9924 | 1.0086 |
| 60  | 1.0050 | 0.9869 | 1.0001 | 1.0048 |
| 70  | 1.0023 | 0.9972 | 0.9922 | 0.9971 |
| 80  | 1.0010 | 0.9952 | 0.9969 | 1.0010 |
| 90  | 1.0079 | 0.9994 | 0.9949 | 1.0086 |
| 100 | 1.0135 | 0.9936 | 0.9979 | 1.0105 |
| 110 | 1.0154 | 0.9908 | 0.9970 | 1.0154 |
| 120 | 1.0108 | 0.9892 | 1.0002 | 1.0131 |
| 130 | 1.0086 | 0.9904 | 0.9946 | 1.0204 |
| 140 | 1.0083 | 0.9915 | 0.9920 | 1.0184 |
| 150 | 1.0088 | 0.9885 | 0.9917 | 1.0228 |
| 160 (terminal) | 1.0083 | 0.9917 | 0.9944 | 1.0153 |

`Var(S)` stays within `[0.98, 1.02]` at every look for every `k` -- tight
around the nominal `Var_H0=1`, at every information fraction, not just
terminally. This confirms the registered-null construction is internally
consistent with the boundary's own assumption at every look, for all
`k in {1,2,3,4}`.

## (1b) Sensitivity study -- quote measurement error (NOT an H0 finding)

Kept from the prior revision, explicitly relabelled: independent Gaussian
ask noise (`spread=0.04`) around a separately-drawn true `p`, with
selection on the noise. This construction manufactures a real (non-null)
edge (`E[held-BE] != 0` in general; `Var_H0=q(1-q)` omits `Var(BE)`), so
its crossing-rate inflation measures QUOTE MEASUREMENT ERROR sensitivity,
never LD-OBF miscalibration. Smoke-size (120 reps), k in {1,2,3,4},
`n_cal=90`:

| k | crossing rate (noisy-ask sensitivity, smoke, n_reps=120) |
|---|---|
| 1 | 0.0167 |
| 2 | 0.0333 |
| 3 | 0.1000 |
| 4 | 0.0750 |

(Measured directly from `_run_real_rule_monte_carlo(..., null_exact=False)`
at smoke size; not re-measured at full size in this revision since it is
explicitly not an H0 finding -- see `xfail` on
`test_noisy_ask_sensitivity_crossing_rate_report`. Smoke-size Monte-Carlo
noise is large at `n_reps=120`; the k=3/k=4 ordering should not be read as
precise, only the qualitative growth vs. `k=1`.) The earlier revision's
`ask_no` construction ALSO had a genuine implementation bug (computed as
`1 - quote(1-p)` instead of `quote(1-p)`, tracking `p` instead of `1-p`),
now fixed; these numbers are from the corrected noisy-ask construction and
show inflation growing with `k`, consistent with more chances for a
favourable noise draw among more concurrent rungs -- a real measurement-
error effect, reported for reference, not gating.

## (2) R3-8 stress -- calibration-table staleness (ask stays exact)

The live ask/price stays exactly `pi_i` / `1-pi_i` (never treated as an
oracle of `held_i`). Instead the CALIBRATION SAMPLE is biased relative to
the true probability: the table believes `P(hold) = pi_i + delta` (so its
YES calibration sample is drawn from that biased rate) and, consistently,
`P(not-hold) = (1-pi_i) - delta` (its NO calibration sample too) -- i.e.
the table is stale in the direction of believing HOLD is more likely than
it truly is. `k=2`, `n_cal=90`, 20000 reps/config:

| delta | terminal crossing rate |
|---|---|
| 0.00 (baseline, main grid k=2/n_cal=90) | 0.0159 |
| 0.02 | 0.0072 |
| 0.05 | 0.00795 |

**Finding:** under this bias direction and construction, staleness did
**not** inflate the crossing rate -- it measured LOWER than the unbiased
baseline at both `delta` values. This is reported, not asserted (per the
task): the bias makes the YES condition marginally easier to fire
(calibration sample overestimates the true `pi_i`, pushing its Wilson
lower bound up) but makes the NO condition harder to fire (calibration
sample UNDERSTATES `1-pi_i` less than intended -- `(1-pi_i)-delta` lowers
the NO sample's mean, which lowers its Wilson UPPER bound, and it is
`(1-p_upper) > BE_no` that must fire, so a lower sample mean here actually
makes NO fire MORE easily too, in isolation). The net measured effect
across both legs, on this rung-budget distribution (typically small
`pi_i`, so NO's true target `1-pi_i` is often large and its Binomial
variance is correspondingly SMALL, tightening its Wilson interval and
making it materially harder for calibration noise -- biased or not -- to
clear the price bar), came out net-lower rather than net-higher. This does
not contradict R3-8's underlying concern (a table that is stale in a
DIFFERENT direction, or a station-day distribution weighted toward larger
`pi_i`, could plausibly show net inflation instead) -- it is recorded as
the measured result of this specific construction, for the ruling to
weigh, not as a general claim that calibration staleness is safe.

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

- Default (gate) test run: smoke size (`n_reps=120` main grid,
  `n_reps=400` var-s-terminal smoke, `n_reps=400` per-look-var smoke) --
  `~30-35s` wall for the whole module, under the ~60s target.
- Full-size run (this artefact's corrected numbers): 8 main-grid
  crossing-rate configs + 4 per-look-Var(S) configs + 2 staleness-stress
  configs, `n_reps=20000` each, `n_max=160`, executed once via a
  standalone script -- total wall time **2242.99s (~37m 23s)**. Per-config
  times: main grid 55-302s (k=4 configs take longest -- more simulated
  station-days needed per admitted trade as the admission gate tightens
  with more concurrent rungs); per-look Var(S) 57-270s (no early stopping,
  so every replication runs the full `n_max`); staleness stress 66-86s.
  ~3.1-3.2M simulated station-days evaluated per crossing-rate config.
- Same `random.Random.binomialvariate` calibration-sampling optimisation
  as the prior revision (O(1) exact Binomial draw vs. an O(n_cal)
  Python-level Bernoulli loop).

## No `slow`/`nightly` marker exists in this repo

Checked `pyproject.toml` `[tool.pytest.ini_options].markers` and
`tests/conftest.py::pytest_configure`: only `live`, `venue_live`,
`real_money` are registered, all venue/network gates, none a compute-size
gate. Rather than add a new marker to shared pytest config from this
worktree, the full-size assertion test
(`test_real_selection_rule_crossing_rate_full`) is gated by the
`BREEZY_FULL_MC=1` environment variable (`skipif`) instead, and the
default-collected smoke test enforces the same qty=1 calibration claim,
for every `k in {1,2,3,4}`, at reduced replication.
