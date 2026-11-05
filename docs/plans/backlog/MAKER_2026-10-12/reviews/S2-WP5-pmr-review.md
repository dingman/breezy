# S2 WP5 prediction-market review (worktree maker-s2-wp5, HEAD 12ee12ba)

Verdict: **REQUEST_CHANGES** (2 HIGH, 3 MEDIUM, 4 LOW). The V0..V5 table, Tests A/B, the ANOVA ICC and
the `s3_inputs` keys are correct. The defects are fail-open defaults and one denominator omission, and
they move the label.

Method: read all five modules plus the stats and verdict tests, and checked them against spec 6.0/6.9,
r3 1/1.1/WP5 and r4 delta (a),(e),(f),(g),(h),(i),(n). I could NOT run pytest: the N2 egress barrier
needs the full `run_tests_no_egress.sh` gate. I ran direct-python hand checks in the worktree instead.
- Test A: 3 fills at p=.05, L>=1 gives 0.2085469, equal to 1-.925^3.
- Test B: n_f=10, n_u=20, L_f=3, L_u=1 gives 0.213661, equal to the hand binomial with pi0=15/35.
- ANOVA on {a:[1,1,0], b:[0,0], c:[1]}: MSB .41667, MSW .22222, m0 1.83333, rho .323077. This matches the
  delta (a) formulas and the implementation.
- Power line: 100 fills at p=.04 gives crit count 11 and P(FAIL|k=1.5)=0.0376 (below alpha, as required).
- Constants: seed 20260919, 2000 draws, alpha .05, in `scoring_core.py:22,25,28`. The one-sided 95th is
  index `ceil(.95N)-1`.

## Findings (ranked)

**[HIGH-1] Optional CSV columns and a zero default silently flip the label.**
- File: `maker_stage0_rows.py:159-161` (`optional=("rung_trials_attempted","n_no_book_wants")`) and `:180` (`n_no_book_wants: int = 0`).
- Authority: r3 1.1 V1/V3 ("stricter of the two units"); delta (g) byte-reproducible rerun; spec 6.0 :221.
- Probe: 80 station-days, 8 filled, 2 rungs attempted each. With the columns, base_sd .10 and base_pos .05 give `NO-GO (fill)`. The same CSV with the two columns dropped reads clean, because `nz(None)` gives n=0 and `_stricter` (`verdict.py:103`) ignores the missing position unit. The result is base .10 and `NOT-KILLED`.
- Failure: `--scored` on a stale or truncated CSV returns a more favourable label than the run. A forgotten `n_no_book_wants` in WP6 silently shrinks the denominator.
- Fix:
  - Make both columns required in `read_station_days_csv`.
  - `_stricter` must raise if either unit has n=0 while `den` is non-empty.
  - Drop the default on `n_no_book_wants` in `sd_row_from_summary`.
  - Add a RED test per path.

**[HIGH-2] The position-unit denominator omits never-booked wanted rungs.**
- File: `verdict.py:85-86` (size = `rung_trials_attempted`); `rows.py:104`; `fill.py:176`.
- Authority: delta (e) and WP4 re-check M1. Those days are IN the station-day denominator as unfilled. Spec :215-216 says never book-gated.
- `rung_trials_attempted` is `len({rung_id of episodes})`, so a wanted rung with no book contributes 0. The position rate is the stricter unit and decides V1/V3, so omitting these rungs inflates it and biases the label toward NOT-KILLED.
- Fix:
  - Size = `rung_trials_attempted + n_no_book_wants`, if `n_no_book_wants` counts rungs. Say so in the docstring.
  - Add `test_position_denominator_counts_never_booked_wants`.
  - Pin the `n_no_book_wants` unit (rungs, not days) in the WP6 brief.

**[MEDIUM-1] The hypothesis set is derived from the data.**
- File: `verdict.py:274` (`names = sorted({r.unit_hypothesis ...})`).
- If the bracketed USD unit yields rows for one hypothesis only, the conservative one never governs and nothing refuses.
- Fix: `analyse_all(..., expected: Sequence[str])` and `decide` raise on a missing or extra hypothesis. WP6 passes the set from the unit loader. Delta (e) names the shared fixture set {CONTRACTS, USD_NOTIONAL_YES, USD_NOTIONAL_TAKER}.

**[MEDIUM-2] The truth-token mapping conflicts between authorities, and WP5 accepts both.**
- File: `scored.py:17-20`.
- Spec 6.5 and r3 `test_unresolved_past_d14_is_loss`: unresolved past D+14 is a LOSS. Delta (b)/(i)6: a day lacking FINAL is EXCLUDED and counted.
- The rule must be fixed before data: no FINAL row in the pinned truth CSV gives `""` (excluded and counted, the later frozen authority). `UNRESOLVED` is emitted only for a FINAL-present or venue-unresolved market past D+14.
- Write this into the WP6 brief. Derive `SdRow.void/unresolved_d14/truth_final` and `PosRow.truth_final` from ONE function.

**[MEDIUM-3] Voids are counted as non-wins, and a missing p defaults to 1.0.**
- File: `verdict.py:142-149`. A VOID enters `win_rate`, `win_rate_boot` and `mean_p_no` as a loss.
- Spec 6.8 reports voids separately, so the win-rate comparison to p_NO is biased down.
- `p_yes_point_live or 0` gives p_NO=1.0 on None (VOID rows bypass the raise in `section_69`).
- Fix: win/p_NO over NO/YES/UNRESOLVED only; add `n_void` to `Expectancy`; raise on None.

**[LOW]**
- (L1) delta (g) gains two undocumented `station_days.csv` columns (`rung_trials_attempted`, `n_no_book_wants`); amend the delta (g) list so the byte test and the contract agree.
- (L2) Test A and Test B are each run at 0.05 with no correction (r3 :181 as frozen). The combined false-FAIL rate is up to ~0.10. State it once in the s69 block.
- (L3) `days_to_200` (`scored.py:80`) also drops `outage_excluded` days; delta (g) says "covered true". Defensible (outage leaves numerator and denominator), but note it.
- (L4) `theta` is not range-checked (0 < theta < 1, equal to the pinned 0.0695). WP6 should assert the pin site.

## Checks that PASS (authority)
- V0 (delta (a)): `n_eff_gov`, `is_underpowered`, `RHO_ASSUMED` and `N_EFF_FLOOR` are imported (`verdict.py:19`, `tables.py:18`), not copied. `decide` takes the min `n_eff_gov` first (`verdict.py:331-336`), then the severity order. Fitted ICC is report-only; the banner text is exact. V1-V5 print as threshold comparisons under V0. `n_sd=0` raises (S-4). Hand check: 4 per date with rho .5 gives 1.6 per date, so 19 dates is 30.4 (clear) and 18 is 28.8 (fires).
- Table: first-match order V1,V2,V3,V4, else V5. A base fail takes V1 before V3, so V3 is reached only when base >= .10. The strict `< .10` comparison is exact at k/n=.1. Ties go to the lower `r_lo`. Label strings are exact.
- Test A: one-sided upper tail, Poisson-binomial with Bernoulli(min(1,1.5p)), alpha .05, on `p_yes_point_live`, loss = YES or UNRESOLVED. Test B: `pi0 = 1.5 n_f/(1.5 n_f + n_u)`, `binomtest(alternative="greater")`, L=0 cannot FAIL. Label text and cluster counts are printed. UNSCREENED when expected < 10 (filled, FINAL-bearing only); the power line is analytic.
- ICC: no pre-clip. `fill_icc_rung_trial` is truncated only to [0,1], so values above 3/7 reach S3's `MakerRefusal` (templates :144) untouched. Undefined gives null, never 0.5. The floor (0.5/7) is S3's.
- `s3_inputs`: all (f) keys are present, and there is no `k`. The `r_lo*` minima are right. `r_lo_se` is taken from the min-LCB hypothesis. `b` is the lower median (on-tick). The IQR uses `inverted_cdf`. LCB is the 2.5th percentile. The bootstrap says "not estimable" below 5 clusters.
- Exclusions: §6.9 excludes no-FINAL rows for filled and unfilled alike and counts them. The UNSCREENED-TERMINAL note is present. The coverage-sensitivity threshold is 0.5 and report-only. The tail annotation does not touch `decide`.

## WP6 obligations (completeness vs delta (g))
- Truth tokens: see MEDIUM-2.
- `rung_trials_attempted`: now flows via `_SHARED`, so WP6 needs nothing, but the CSV column must be required (HIGH-1).
- `n_no_book_wants`: WP6 must supply it; no default (HIGH-1/2).
- `theta`: per replayed row, the pinned 0.0695; a scored fill without theta already raises (good).
- Tail CSV: columns are `station, climate_day, vector, p_yes, outcome`. They are absent from delta (g); add them.
- Hypothesis set from the unit loader (MEDIUM-1). `code_sha` is non-default in the driver (default `UNPINNED-RERUN` is fine for reruns only).

## Rulings on the four judgement calls
1. **§6.9 and expectancy use the BASE rule: ACCEPT.** Spec :294 says "filled episodes", and r3 WP5 and goal 7 never mention stress. Add a report-only §6.9 block on stressed fills beside it (queue-delayed fills are the likelier adverse-selected set); never a label.
2. **VOID: excluded from §6.9 (correct, no YES/NO outcome). In the expectancy, w=0 with fee charged is correct per spec 6.5 and r3 goal 7 (refund assumed 0).** Win rate and p_NO comparison must exclude voids, with `n_void` reported (MEDIUM-3).
3. **Two-sided doubled-tail tail test: ACCEPT for the report-only annotation.** Same-vector bands are correlated, so the p is anti-conservative; this is harmless because it never sets a label (verified), but footnote it.
4. **`r_lo*` null if any hypothesis is not estimable: ACCEPT** (never optimistic; the min over only the estimable ones could be higher than the truth). S3's brief must treat null as refuse, not as 0 or as f_pass=f_kill.
