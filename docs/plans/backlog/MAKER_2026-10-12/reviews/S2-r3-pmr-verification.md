# S2 r3 verification: prediction-market-reviewer, 2026-10-13
Verdict: READY-WITH-EDITS. R1-R5 are substantively fixed in the body (fill rule, STALE_H, process schedule, pooled exact screen, denominator). Three HIGH items are plan-text/interface gaps (E-1..E-3 below), each fixable without redesign. Do not run S2 until E-1..E-3 land.
Read: plan r3, S2-r2-final, spec v0.3, ruling S3-window (FINAL), S3 r3 + r4 delta, S5 r3 :24-30, S1 run procedure, SEARCH declaration 2026-10-12.

## 1. Disposition R1..R5
| # | r3 status | Evidence (r3 line) | Conformance-table claim vs body |
|---|---|---|---|
| R1 base fill rule | RESOLVED | WP4 :159-164: Q0 = A_gt + A_eq + 1, q > b reduces by min(v,G), q <= b consumes R, FILLED at R <= 0 ("reaches Q0"), stress Q0' = 2(A_gt+A_eq+1), G' = 2 A_gt. Matches spec 6.1 :236-241 and 6.7. Tests :171 named | Matches body |
| R2 STALE_H = 8 | RESOLVED | WP3 :141 + `test_constants_match_spec`; 3.1 arithmetic re-checked: 13Z D-1 avail 14:04Z, 01Z D avail 02:04Z + 8h = 10:04Z, 20.0 h; bids end 18:50/20:50/21:50 LST = 02:50Z minus 8/6/5... correct; dead 7.2 h / 2.8 h correct | Matches. Row text "spec input 5 dropped" is confusing: a new, different input 5 exists |
| R3 process schedule | RESOLVED with MED caveats (F-6, F-7) | WP1 :124, WP4 :150-156, 3.1 :73-81, `CANCEL_PROCESS`/`GTD_EXPIRY`, cut share in goal item 2 | Matches |
| R4 verdict + 6.9 | PARTLY | Exact pooled Test A/B, E >= 10 else UNSCREENED, bootstrap descriptive (WP5 :177-183): fixed. NOT fixed: spec 6.0 :222-224 UNDERPOWERED-WAIT (effective n >= 30) is absent (F-1). Spec input 1/2 claims about the spec are false (F-2) | Table says R4 done; F-1 contradicts |
| R5 denominator | RESOLVED with MED caveats (F-5) | WP5 :175 covered = depth frames in process-live window, print presence excluded; print-less windows unfilled; gaps subtracted (WP4 :156); start day measured (3 :67) | Matches |
Conformance rows R6, R7 hold. R8 is FALSE: "list pruned to gaps v0.3 does not cover" but spec inputs 1-6 are all already in v0.3 text (F-2). R9 effort sum 22 h is arithmetically right.

## 2. Spec v0.3 conformance (item 2)
- 6.1 base rule, stress: conform (R1). STALE_H = 8, age from `available_at`, day-match abstention: conform. Cycle map (13Z/19Z D-1, 01Z D feed day D) is consistent with the "first MAX column = cycle LST date + 1" memory; WP2 verify-first guards it.
- Denominator: conforms in wording; see F-5 for bid-bearing and covered definitions.
- 6.9: conforms (pooled, 1.5 margin, E >= 10, FAIL only if screened).
- Verdict table: V1/V2/V4/V5 conform. V3 (base >= 0.10, stressed < 0.10 -> NO-GO (stress)) CONFORMS to spec :221-222 ("Base passes but stressed fails is NO-GO"). Plan Spec input 1 ("no row") is wrong. Missing from the plan: the sample-floor label UNDERPOWERED-WAIT (F-1).

## 3. Findings
HIGH
1. F-1 No UNDERPOWERED-WAIT row. Spec :222-224: a verdict requires effective n >= 30 (climate-date adjusted); below that Stage 0 emits UNDERPOWERED-WAIT with n and interval and no build starts. Plan 1.1 has five rows; S-4 stops only at zero (:59, Spec input 2 says "no minimum"). Failure: n = 12 covered bid-bearing days with fill rate 0.08 emits NO-GO (fill) and terminates the family on a sample the spec calls unverdictable; or a label chosen after seeing n (forking path). Fix: add row V0 `UNDERPOWERED-WAIT` ahead of V1, frozen: effective n = covered bid-bearing station-days / realised design effect, floor 30, on the base unit hypothesis; print n and interval; S-1 does not fire. Add test `test_below_n30_emits_underpowered_wait_not_no_go`. Delete Spec input 2.
2. F-2 (HIGH as a conformance claim, mechanical fix) Spec inputs 1-6 misstate v0.3. Input 1 (spec :221-222), 2 (:222-224), 3 (:88), 4 (:85), 5 ("reaches Q0", :239-240), 6 (:105-118) are all in the spec. Fix: delete the section; replace with one line "none; v0.3 covers all". Correct the conformance rows R4/R8.
3. F-3 S3 interface is unnamed and partly absent (section 4). Fix: add a machine-readable `s3_inputs.json` to the sidecar with the keys in section 4, test `test_s3_inputs_json_has_every_named_key`.
4. F-4 Forecast-store read has no licence. `RULING_MAKER-S1_SEARCH_declaration_2026-10-12.md` :32/:38-39 covers "S2 Stage 0 reads" of tape but states "Not licensed: any forecast-store read" and "permits no forecast-store read". WP2 reads the NBP store for every replayed day, and S2 E1 admits SEARCH days 09-26..10-13. Failure: the run on SEARCH days breaks RA-13 B-3 or the replay silently shrinks to 09-18..09-25 (about 8 dates) after the fact. Fix: add entry E5 "a dated declaration amendment licensing S2's NBP read for exactly the replayed station-days exists (sha pinned), else the replay set is 09-18..09-25 only and the report says so"; fix the replay set before the run; WP0's "SFO 10-0x" positive control must be a declared day and Depth10 frames must be inside the licensed read list.
MED
5. F-5 Denominator definitions leave two choices. (a) "bid-bearing = rule placed >= 1 episode" (:175) comes after the marketability guard, so days where every attempt was refused (stale, truncated, marketable) leave the denominator and raise the rate; spec says bid-bearing. Define bid-bearing as "the rule produced a bid >= B_FLOOR at some decision instant", before the guard; report guard-refused days separately. (b) "covered = >= 1 depth frame" (:175) is weaker than S1's `COVERED` (fraction and hole rules, `maker_tape_census.py:126-134`); two covered definitions. Use the census row `COVERED` intersected with depth in the live window, or state why weaker and print both rates.
6. F-6 Node-log coverage is UNVERIFIED (:217) and relaunch cuts are overlaid only where logs exist (:124). Days with logs get more churn than days without: mixed schedule biases the rate up where logs are missing. Fix: freeze before the run: verdict uses the nominal schedule + midnight cut only (logged relaunches as a report-only second run), or if coverage < 100% report both and the stricter governs.
7. F-7 Contradiction at :124: node outages are "not simulated" but "make a station-day non-bid-bearing". Pick one and freeze. Recommend: a logged full-day outage removes the day from the denominator and is counted (live clock does not tick it either).
8. F-8 No code-freeze clause. S3 has "any post-result change is void"; S2 does not. Add: verdict run only from a committed sha pinned in `run_manifest.json`; the benchmark's fill outputs are not inspected for rate; any post-run code/threshold change voids the run.
9. F-9 WP0 "inverted" (agreement <= 0.1) silently flips the credited side (:111). That is a data-chosen change to the fill rule and contradicts 6.1 (YES BUYER). Make inverted a STOP S-2 to the spec, not a recorded mapping.
10. F-10 `MAX_RUNGS1` subset = "first selected rung" (:143) is ill-defined across decision instants. Define: the rung with the lowest p_YES passing P_MIN at the episode's first placement on that station-day, held for the day; simulate the stressed pass for it too (S3 k = 1 cells need the stressed rate).
11. F-11 Test B pools by row counts, not exposure (:180-181). Filled and unfilled rows have different p mixes, so a stratum mix shift moves the test. Spec form is unstandardised so it conforms; keep, but print the mix-adjusted rate ratio and state it never decides. Also label Test B "Poisson-conditional approx", not "exact".
LOW
12. Test A/B assume independent outcomes; same-date correlation inflates FAIL probability (kill-direction bias). Report climate-date cluster count beside the p-value. 
13. Goal item 2 reports a Wilson interval on a clustered binomial. Wilson is too narrow here; see section 4.
14. GTD cut at 00:00Z re-posts at the same instant (:150-156); live re-post waits for the next event. Immaterial, state it.
15. `--stations/--days` flags exist on the verdict run (:193). Freeze: verdict run takes no subset flags.

## 4. S3 interface check (what WP4 reads: r3 :41, r4 delta (a),(h),(j), ruling O-4)
| S3 needs | S2 r3 delivers? |
|---|---|
| S2 verdict | Yes (goal item 1); no key name |
| `r_lo` = stressed station-day fill rate point (delta (h); S5 :27 "r_lo") = `f_kill` | Rate present (item 2) but NO key `r_lo`. Unit choice: S3 uses the station-day unit; S2's verdict uses the stricter of two units. Name both: `r_lo_station_day`, `r_lo_position`, and say which is S3's |
| `f_pass` = stressed 95% lower bound, climate-date cluster-bootstrap | NOT delivered. Item 2 gives a Wilson interval; bootstrap exists only for win rate and expectancy. Wilson on date-clustered data is too narrow, so S3 would REACH REACHABLE too easily. Add `r_lo_lcb_cluster_boot` (2000 draws, seed 20260919) |
| Fill-rate SE | NOT delivered. Add `r_lo_se_cluster_boot` and base equivalents |
| Base station-day point + CI | Point yes; CI Wilson only (as above) |
| MAX_RUNGS = 1 rate, base and stressed | NOT delivered as rates (only "days to 200"). Add `r_lo_k1`, base k1 (needs F-10) |
| two_fill_share | NOT delivered |
| bid-bearing share of covered listed station-days | NOT delivered (n of bid-bearing and covered are implicit) |
| per-date fill ICC | NOT delivered |
| n0 (Stage 0 climate-date count) | Cluster count appears for win rate only; add `n0_climate_dates` |
| Realised bid median (delta (a)) / IQR (r3 :41) | Histogram only (item 4), no median or IQR key. Add `realised_bid_median`, `realised_bid_iqr`. Bid is bounded by the rule to [0.70, 0.80], so the b-out-of-range refusal is a guard, not an S2 output |
| Realised k (admitted MAX_RUNGS) | Not an S2 output (spec 3 admission); S2 must carry `max_rungs_hypothesis` per run |
| Sha of the artifact, sample provenance | `pins.json` yes |
Edit E-3 below names every key.

## 5. Forking paths that could move the label
(1) F-1 label chosen by n. (2) F-5 bid-bearing/covered definitions. (3) F-6/F-7 schedule source and outage handling. (4) F-4 replay set (SEARCH days) decided after seeing pre-freeze results. (5) F-9 inverted-direction mapping. (6) F-10 MAX_RUNGS-1 definition. (7) Stricter-unit choice is deterministic but must be fixed as "min over unit x hypothesis" before the run. (8) F-8 no code-freeze. (9) CLI subset flags. Not forking: bracketed-unit severity order, tail table (annotation only), bootstrap sidecars.

## 6. Arithmetic and statistics (item 4)
- Test A: P(L >= l_obs) under Bernoulli(min(1, 1.5 p_i)), DP tail, FAIL < 0.05: correct. Power line: critical count l* then P_k(L >= l*): correct; k = 1.5 returns the size (<= 0.05), fine as a calibration point.
- Test B: pi0 = 1.5 n_f / (1.5 n_f + n_u). Under H0 (q_f = 1.5 q_u, Poisson) L_f | L ~ Bin(L, pi0): correct; one-sided "greater": correct; L = 0 cannot FAIL: correct. Margin 1.5 matches the spec's "same test". Approximation, not exact (F-11).
- E = sum of p over ALL filled rows >= 10: matches spec "10 expected losses pooled". With p_YES <= 0.06 and about 25-60 pre-freeze fills, E is about 1-3, so UNSCREENED or NO-GO (fill) is the realistic outcome (:45) is right.
- Net expectancy w - (b + theta b (1-b)) matches spec :139-140. Wilson formula is not given; fine, but see Section 4.
- Stratum standardisation: dropped from the decision (descriptive only); conforms to spec.

## 7. Build-before-run (item 6)
Confirmed with two amendments.
- WP0: synthetic frames suffice for all five RED tests; the real-tape run needs F-4 for 10-0x data. Build now.
- WP1: build now. `CensusedDay.from_dict` (`maker_tape_census.py:490`) and the crosscheck JSON (`trade_quantity_unit_crosscheck.py:197-202`) schemas already exist; fixtures suffice. Real S1 files only for the run.
- WP2: build now (NBP store fixtures; `tests/fixtures/nbm/nbptx_t{13,19,01}z_excerpt.txt`). The verify-first STOP needs the real store and P2, so it runs at the real-data step, not in unit tests.
- WP3, WP4, WP5: build now, pure. WP5 `--scored` reproduces from a fixture CSV.
- WP6: build now with fixtures; driver real run waits.
- Wait for S1/disk: P2 backfill, the benchmark, the full run, `--tail-only`. Disk (E4) blocks even the gates today.
- No WP needs real S1 output for RED/GREEN, provided F-3 fixes the artifact schema first (a WP5/WP6 test depends on it).

## 8. Required edits (exact)
E-1 Add verdict row V0 `UNDERPOWERED-WAIT` (effective n < 30, frozen definition per F-1) before V1; test name as F-1; delete Spec inputs 1-6.
E-2 Add entry E5 (forecast-store licence per F-4) and freeze the replay set before the run; add code-freeze clause F-8; make "inverted" an S-2 STOP (F-9); freeze one schedule source and one outage rule (F-6, F-7); define bid-bearing before the guard and covered per S1 `COVERED` (F-5).
E-3 Add `s3_inputs.json` with these keys: `verdict`, `r_lo` (stressed station-day point; also `r_lo_station_day`, `r_lo_position`), `r_lo_lcb_cluster_boot`, `r_lo_se_cluster_boot`, `base_station_day_rate`, `base_station_day_rate_ci_cluster_boot`, `r_lo_k1`, `base_k1`, `two_fill_share`, `bid_bearing_share_of_covered_listed`, `fill_icc_per_date`, `n0_climate_dates`, `realised_bid_median`, `realised_bid_iqr`, `max_rungs_hypothesis`. Replace the Wilson interval in goal item 2 by the cluster-bootstrap interval (Wilson kept as a sidecar).
