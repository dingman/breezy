# S2 r4 delta rev 2 FINAL verification (round 3) - mle-reviewer - 2026-10-13
Verdict: READY-WITH-EDITS (0 HIGH, 0 MED blockers, 4 small text edits E-1..E-4; none changes a design decision). Build may start on the (k) list now; E-1..E-4 land in the delta before WP5/WP1-ledger merge. Reviewed: r4 delta rev 2, amendment DRAFT rev 2, r4-mle-verification, code via codegraph (`maker_tape_census.py:96-97,689-690,715-716`).

## Disposition of round-2 findings
| Finding | Status | Evidence (rev 2) |
|---|---|---|
| H1 outcome-dependent V0 | RESOLVED | (a): "`n_eff_gov = Σ_d m_d/(1+(m_d−1)·RHO_ASSUMED)`; `RHO_ASSUMED` and `N_EFF_FLOOR` are imported ... never copied"; "n_sd is fixed before any fill, so V0 never depends on a fill outcome"; fitted ICC "REPORT-ONLY, never decides V0"; n_sd = n0 listed as "Undefined ... prints 'undefined' with no substitute"; "V0 is evaluated first ... then NO-GO > NOT-KILLED-UNSCREENED > NOT-KILLED". Tests pin all five properties (see N-1 for the `_n_eff` ruling). |
| M1 tables not reproducible | RESOLVED (see table below) | (g) rerun test byte-compares named blocks; "every other block ... 'run-time only, sha-pinned'" with three named sidecar groups |
| M2 station_days columns | RESOLVED | (g) `has_depth_frame`, `gap_share` defined, `nogo_driving` defined, four `positions_filled_*` days-to-200 inputs, rows for every census day incl. non-COVERED/outage/node_log_absent |
| M3 read-once / ledger / abort | RESOLVED | amendment §1 "one scoring pass; bench, verify-first ... read without producing fill-rate output"; (c) ledger at run start, `.void` rename, no resume, `progress.jsonl` has no fill/rate field, bench writes no episodes file; tests named |
| M4 artefact sha / window | RESOLVED | (g) `load_model` asserts 1-3 (artefact sha, v5_fit_slice last day == 06-30, no era > 06-30); RED test named |
| M5 machine-readable set | RESOLVED | amendment fenced `FROZEN_DATE_SET`; (b) parser refusals incl. placeholder, >10-13, 10-01, NYC; no-NBP-decision clause in amendment §2 |
| M6 four unnamed tests | RESOLVED | (i)1, (i)4, (i)5, (i)6 each name a test |
| L1 S-7 | RESOLVED | (i)3 pre-pass before scoring, max over instances, magnitude pessimistic |
| L2 outage | RESOLVED | (d) partial-cover = `node_log_absent`; booted-before-16:50Z fixture |
| L3 freeze scope | RESOLVED | (c) `scripts/analysis src tests pyproject.toml uv.lock` |
| L4 transitive closure | RESOLVED | (i)7 `test_simulator_transitive_import_closure_excludes_truth` |

## Verification answers
1. H1: sound. S1 form confirmed (`_n_eff`, `:689-690`; S-1 at `:715-716`; floor 30, rho 0.5). Fitted-ICC block hand-checked against the ANOVA in my round 2: m0, truncation, df edge, banner are consistent. Severity order V0-first on min n_eff_gov is stated.
2. Reproducibility: see table. Only residuals are N-3/N-4.
3. Leakage: (c) sound and testable with a tmp git repo; (b) E5 FINAL-sha pin sound (DRAFT sha cannot satisfy the pin); (g) `load_model` sound; (i)7 sound, the closure test catches shared helpers. One ordering hole N-2.
4. (i)3 pre-pass: sound (Δ is pre-fill, outcome-blind; abort is a non-result void). (i)9 heaviest-by-bytes + in-run RSS abort: sound; an S-5 abort mid-verdict is a void needing an addendum, consistent with (c). Extrapolation remains a screen.
5. Build-now: every named test yields a RED from fixtures; none needs S1 output, P2, E5 or disk. Generated-from-`CensusedDay.to_dict`/field-set fixture is right; add a write_censused_days -> read_censused_days round trip so a serialiser change also fails loudly.

## New findings
- N-1 [LOW] (o)2 ruling. Do NOT add a public alias and do NOT import `_n_eff`. Test equality against the public `summarise(rows).n_eff_ub` with rows all `reason == "COVERED"` built from the generated `CensusedDay` fixture (same per-date counts). Public API, no lint exposure, and it also pins that the fixture matches S1's schema.
- N-2 [LOW] Ledger ordering. (c) appends at "run start, before any scoring" but does not say it follows the preflight refusals (dirty tree, frozen-block parse, amendment sha, E4 disk, subset flags). A launch refused for a trivial reason would burn the ledger and force an addendum. State: ledger append is the last step after all preflight refusals and the S-7 pre-pass is NOT a preflight (S-7 void after append is by design).
- N-3 [LOW] Days-to-200 denominator ambiguous: "÷ distinct dates" must name the set (distinct `climate_day` over rows with `covered` true, per hypothesis) so the byte-compare is defined.
- N-4 [LOW] `b`, `realised_bid_iqr`, `n_stressed_fills` and Test A/B derive from `scored_episodes.csv`, whose columns are inherited from r3 L28 and not enumerated. Name at least `position_id`, `rung_trial_id`, `bid`, `filled_base`, `filled_stress`, `p_yes_point_live`, `truth_final` so the rerun test and `fill_icc_rung_trial` (from per-date posted/filled counts) are checkable.
- N-5 [INFO] (o)3 (ICC from governing hypothesis, f from min) accepted; S3 floors/refuses per (n)3.

## Reproducibility check (three CSVs + named sidecars)
| Block | Category |
|---|---|
| V0 (n_sd, n0, n_eff_gov), fitted ICC, deff_hat, n_eff_hat, banner | byte-reproducible (`bid_bearing`, `cluster_id`, `filled_pairs_base`) |
| V1-V5, intervals, S3 block, `fill_icc_rung_trial` | byte-reproducible (counts per date; bids from episodes, see N-4) |
| Test A/B, tail table, Δ distribution, coverage sensitivity | byte-reproducible |
| non-COVERED-by-reason, >=1-frame rate, gap-share table, days-to-200 | byte-reproducible (see N-3) |
| overlay comparison, WP0 agreement, +60 min and poll-lag stress | run-time only, sha-pinned (named sidecars) |
| bench timing/RSS, S-5 projection, `run_manifest.json`, progress | run-time only; NOT listed as sha-pinned sidecars: add `progress.jsonl` and bench output to the pinned list (ordinary, non-result) |
Blocks in neither category: none in this delta other than the bench/progress item above (fold into E-3 edit).

## Required edits (verbatim text)
- E-1 (o)2 -> "Equality is tested against `summarise(rows).n_eff_ub` on all-COVERED generated `CensusedDay` rows; `_n_eff` is neither imported nor aliased."
- E-2 (c) add -> "The ledger entry is appended after every preflight refusal (clean tree, frozen block, amendment sha, E4, subset flags) and before the S-7 pre-pass."
- E-3 (g) add -> "Days-to-200 divides by distinct `climate_day` among rows with `covered` true, per hypothesis. `scored_episodes.csv` columns: `position_id`, `rung_trial_id`, `bid`, `filled_base`, `filled_stress`, `p_yes_point_live`, `truth_final`. `progress.jsonl` and bench output are run-time only, sha-pinned in `pins.json`."
- E-4 (k) add -> "Shared fixture test also round-trips `write_censused_days` -> `read_censused_days`."

## Build-now confirmation
Confirmed for WP0-WP6 as in (k); tests run: none (plan review); no mutation beyond this file.
Decision: READY-WITH-EDITS. Primary risks: other (spec wording only); weak eval and irreproducible training risks closed.
