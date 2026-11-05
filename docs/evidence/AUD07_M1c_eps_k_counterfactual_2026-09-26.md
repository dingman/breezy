# AUD-07 M1c eps_k Counterfactual (2026-09-26)

Pre-registered by `docs/evidence/RULING_aud07_m1c_eps_k_decision_rule_2026-09-26.md`,
step 1(a)(b)(c). Read-only, scratch-only: no new sha, no pin written, nothing
gated, against the frozen code-S snapshot
`code-0369e1218a85dd327d8282762c0642da01b7c49f` only (never the working tree;
`breezy`/`aud06a_qty_envelope_sweep` import-path asserted to resolve under the
snapshot before any computation). All heavy jobs ran under
`systemd-run --user --wait --pipe --collect -p MemoryMax=6G -p MemorySwapMax=0`
with `OPENBLAS/OMP/MKL_NUM_THREADS=1`, P ≤ 3 concurrent. No breezy unit was
touched (`systemctl --user list-units 'breezy-aud07*'` was empty before and
throughout).

## Method

**(a) Per-depth + terminal census**, 400 reps, cells {0, 15, 46, 17, 21, 45},
seed = `seed_for("cal_b", cell)` (the same seed convention
`run_census_cell` uses). Reimplements `run_census_cell`'s coarse-vs-fine
double `StreamingBoundary` walk, but buckets each look's `|Δb|` by look
ordinal ("depth") instead of pooling into one flat list, and classifies
**terminal strictly by the sim's own stop rule** (`t ≥ 1` — i.e.
`reached_i_max`, since this synthetic walk has no loss-stop/forced
truncation — **or** `look_n ≥ N_MAX`), never by ordinal position and never
by the original census's `look_n ≥ N_MAX` proxy. `t` is monotone
non-decreasing in `look_n`, so "first terminal" is unambiguous; the loop
breaks there, matching what one real replicate would ever reach.

**(b) Coarse-only replicates**, 2000 reps, cells {0, 15, 46}, seed =
`seed_for("cal_c", cell)` (byte-identical to the live CAL-c seeds). Replays
the REAL `run_sequential_looks` with a single `StreamingBoundary(npts=
COARSE_NPTS)` chain — the exact call `_run_replicate`'s coarse leg makes —
recording `(depth, look.terminal, state.s − b_eff, state.s − b_fut)` per
look actually reached (early futility stops included, since that's what a
real replicate would see).

**(c) eps_k / eps_terminal / predicted f.** `eps_k[depth] = max(0.02, 3 ×
max_over_cells(census max at that depth))`; depths with no census
observation (only depth 16, which coincides with `look_n == N_MAX` and is
therefore always classified terminal, never interim) fall back to the
**global eps** (0.6948129460990256), never the floor, per PR-1.
`eps_terminal = max(0.02, 3 × max_over_cells(terminal census max))`.
Predicted `f` replays `_needs_refine`'s eff/fut logic (never its dt check,
since CAL-c's own refine reasons are 100% `{eff, fut}` — the "dt = 0 case")
against the (b) replicates, with per-look eps = `eps_terminal` if
`look.terminal` else `eps_k[depth]`. The positive control repeats this with
one scalar `eps = 0.6948129460990256` for every look, on the same (b)
replicates.

## Per-depth / terminal census (400 reps/cell, max |Δb|)

| depth | c0 | c15 | c46 | c17 | c21 | c45 | combined max | eps_k |
|---|---|---|---|---|---|---|---|---|
| 1 | 0.002104 | 0.000998 | 0.200321 | 0.000000 | 0.000000 | 0.000000 | 0.200321 | 0.600963 |
| 2 | 0.000613 | 0.000470 | 0.003804 | 0.231604 | 0.168528 | 0.231604 | 0.231604 | 0.694813 |
| 3 | 0.002535 | 0.002532 | 0.001666 | 0.055814 | 0.070545 | 0.070545 | 0.070545 | 0.211636 |
| 4 | 0.003537 | 0.005050 | 0.003235 | 0.004039 | 0.004342 | 0.003481 | 0.005050 | 0.020000 |
| 5 | 0.006202 | 0.008121 | 0.004526 | 0.005983 | 0.006243 | 0.006432 | 0.008121 | 0.024362 |
| 6 | 0.008001 | – | 0.003012 | 0.006865 | 0.007896 | 0.006796 | 0.008001 | 0.024003 |
| 7 | 0.010885 | – | 0.006911 | 0.007103 | 0.007062 | 0.006470 | 0.010885 | 0.032655 |
| 8 | 0.010089 | – | 0.006755 | 0.004500 | 0.004786 | 0.009077 | 0.010089 | 0.030266 |
| 9 | – | – | 0.008102 | 0.009094 | 0.007872 | 0.011532 | 0.011532 | 0.034597 |
| 10 | – | – | 0.008430 | 0.009870 | 0.009969 | 0.008756 | 0.009969 | 0.029908 |
| 11 | – | – | 0.010058 | 0.009374 | 0.010197 | 0.013788 | 0.013788 | 0.041364 |
| 12 | – | – | 0.011019 | 0.011319 | 0.011083 | 0.008361 | 0.011319 | 0.033957 |
| 13 | – | – | 0.012389 | 0.010858 | 0.013283 | 0.012119 | 0.013283 | 0.039849 |
| 14 | – | – | 0.013599 | 0.009363 | 0.011958 | 0.009652 | 0.013599 | 0.040797 |
| 15 | – | – | 0.016372 | 0.011040 | 0.014024 | 0.013035 | 0.016372 | 0.049116 |
| 16 | – | – | – | – | – | – | (no obs.) | 0.694813 (global fallback) |
| **terminal** | 0.020626 | 0.011889 | 0.009566 | 0.002202 | 0.001784 | 0.002069 | 0.020626 | **eps_terminal = 0.061879** |

`n_ok = 400/400` for every cell (no admissibility skips).

**Finding, corroborating and correcting the ruling's speculation.** The
0.23160431536634185 / 0.16852808884208237 values the ruling flagged as
"bit-identical across cells 21/25/29/33/37/41" are **not** terminal or
t-cap points — they sit at **depth 2** (the census's terminal bucket for
those cells tops out at 0.0022, two orders of magnitude smaller). The
global eps (0.6948129460990256 = 3 × 0.23160431536634185) is reproduced
almost exactly as `eps_k[2]`, confirming the single dominant mismatch the
current global pin was built around is an early-interim-look artifact, not
a terminal one.

## eps_k / eps_terminal

- `eps_k` table (depths 1–16): see column above. Range 0.02 (floor, depth 4)
  to 0.694813 (depth 2, ≈ global eps).
- `eps_terminal = 0.061879` (vs. global eps 0.694813 — terminal margins are
  far tighter than the worst interim depths).
- Depth 16 has no observations (structurally always terminal) → falls back
  to the global eps, never the floor.

## Predicted f per cell

| cell | f(eps_k) | f(global EPS) — positive control | n reps |
|---|---|---|---|
| 0 | 0.0155 | 0.191 | 2000 |
| 15 | 0.0240 | 0.2115 | 2000 |
| 46 | 0.0260 | 0.2075 | 2000 |

**Positive control reproduces CAL-c exactly**: {0: 0.191, 15: 0.2115, 46:
0.2075} is bit-identical to `runs/0369e1218a85/cal_check.json`'s
`f_per_cell`, confirming the replay methodology (seeds, coarse-only
`run_sequential_looks` replay, eff/fut logic) matches the live CAL-c run
byte-for-byte in its refine decisions.

Max predicted f under eps_k across cells {0, 15, 46} = **0.0260**.

## Rep reductions

None needed. Full pre-registered rep counts ran (400/cell for the census,
2000/cell for the coarse replicates); total wall time was well inside the
10:25Z budget (see below).

## Decision

Pre-registered rule: max predicted f over cells 0/15/46 ≤ 0.10 → BUILD-EPS_K;
otherwise → OVERRIDE.

**Max predicted f = 0.0260 ≤ 0.10 → DECISION: BUILD-EPS_K.**

Per the ruling's step 2: TDD code S′ per
`docs/plans/backlog/AUDIT_2026-09-21/AUD-07-M1c-eps_k-switch-plan_r1_2026-09-26.md`,
amended by PR-1 (per-depth `eps_k` + authoritative `eps_terminal`, terminal
keyed on `LookRecord.terminal`, a table length of exactly `N_MAX/LOOK_STEP`
= 16, missing depths fall back to the global eps) and PR-2 (DT_MIN stays one
global scalar). Then rerun CAL at S′ in the next A-window, then run 20k.

## Wall time

- Census batch 1 (cells 0, 15, 46; 400 reps each, P=3): 08:31–08:48Z (~17 min,
  slowest cell 46 at 17m17s).
- Census batch 2 (cells 17, 21, 45; 400 reps each, P=3): 08:49–09:12Z (~23 min
  each, ran concurrently).
- Coarse replicates (cells 0, 15, 46; 2000 reps each, P=3): 09:13–09:19Z
  (~3–6 min each, ran concurrently).
- **Total wall time: 08:31Z–09:19Z ≈ 48 minutes**, finishing well before the
  10:25Z AUD-09b C2 replay window.
