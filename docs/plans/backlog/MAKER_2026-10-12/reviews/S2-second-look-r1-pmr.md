## Verdict: REQUEST_CHANGES

The block rule and the disjoint-block ruling are sound. I found four defects, two of them in enforcement (not just wording), plus two false statements in the plan. All are fixable in the plan text and small code units without redesign. The ledger, `LAST_ALLOWED_DAY`, tail-wiring and block-1 literal checks all hold up.

| Axis | Score |
|---|---|
| Correctness vs governing texts | 7 |
| Architecture/idiom fit | 8 |
| Test coverage | 7 |
| Risk mitigation | 6 |
| Scope minimality | 8 |
| Feasibility | 7 |

## Verify-first results

**1. Ledger (confirmed; the plan is right).**
- `scripts/analysis/maker_stage0_ledger.py:203-204`: `mine = [e … e["amendment_sha"] == amendment_sha]`, and `if not mine: return None`. A new amendment sha is therefore a fresh claim with no code change.
- There is no date-overlap guard. `claim_verdict_run` (:238-253) appends on a sha-only check.

**2. Frozen constants (confirmed).**
- `maker_stage0_frozen.py:36` has `LAST_ALLOWED_DAY = 2026-10-13`, and :37 has `FIRST_REPLAYABLE_CHOICES = (09-18, 09-19)`.
- `_check_dates` :126-127 raises on `day > LAST_ALLOWED_DAY`. :149-150 raises on any other `first_replayable_day`.
- `verify_set_matches_rule` :202-208 also uses `LAST_ALLOWED_DAY`.
- Every date ≥ 10-14 is refused today, so C2 is necessary. C2 must not reuse `parse_frozen_block`, because :149 would refuse a v2 first day.

**3. Driver ordering (confirmed, and the plan's reason is wrong).**
- `claim_verdict_run` is at `maker_stage0_driver.py:177`. `_wp0` is at :213, and the equality check is at :225-229. The check runs after the claim and would void the run.
- The plan says "prints already exist since 09-17, so the result is ≤ 10-14". That is false (see B3).

**4. Census firewall (confirmed).**
- `maker_tape_census.py:71-78` pins a single range and a single sha.
- :178-200: `require_firewall_clearance` checks `SEARCH_DECLARED` bounds, then `declaration_sha256 != SEARCH_DECLARATION_SHA256`.
- `SEARCH_DECLARED` is consumed only inside this file, so C1 is local.

**5. Tail annotation (confirmed unreachable from `--tail-only`).**
- `run_tail` (`maker_stage0_report.py` ~:181-212) writes only `tail_reliability.csv` and the manifest. It never calls `tail_table`.
- `tail_table` (`maker_stage0_stats.py` ~:355-366) sets `miscalibrated = p_value < ALPHA`.
- `render_verdict` (`maker_stage0_tables.py` ~:127-128) is the only emitter. It is fed the verdict run's tail rows, which are empty by construction.

**6. Block-1 literals.**
- `maker_stage0_render.py:86` is confirmed.
- The plan missed `maker_stage0_render.py:42-45`, which holds more block-1 text (see B4).
- The only other literal hit outside `frozen.py` is `driver.py:113` `TAIL_RANGE`, which is intended. `inputs.py:334` is a comment.

**7. Shrink arithmetic.** The 48 is right, the decomposition is wrong, and the proxy shrink is not 0.917.
- 96 station-days. 88 are COVERED (LONG_HOLE 4, LOW_COVERAGE 4).
- `listing_abstain` is true on 44 rows, not 40. Four of those 44 are the 09-29 non-COVERED rows.
- The 09-28 non-COVERED rows are listed early.
- 96 − 44 − 4 = 48 is correct. The plan's "96 − 40 − 8" gets 48 by offsetting errors.
- `listing_abstain` lives in `wp0_agreement.json`, not in `station_days.csv`. The cite "station_days.csv:42-49" is not where that flag is.
- Of the 48, 44 have `bid_bearing=true`. The four exceptions are LAX 10-03, SFO 10-03, SFO 10-04 and LAX 10-08.
- Proxy `n_eff` for the 48 early-listed rows is 19.200. Actual `n_eff_gov` is 18.733. The ratio on the thresholded quantity is 0.976, not 44/48 = 0.917.
- The dropped rows sit on dates with m=4, so they cost 0.47 of `n_eff`.
- T=34 is therefore more conservative than the stated derivation. Correctly derived, 30/0.976 ≈ 30.7, which is about 20 dates instead of 22.
- Over-conservatism is not harmful: it costs two extra calendar days. But the derivation must be stated correctly in Doc A, since Doc A pins it.

## BLOCKING issues

**B1. §1 / §2 C4 — the trigger is outcome-blind in rule but not in practice.**
- C4 reads census JSONL rows. Those rows carry `buyer_by_bucket`, `prints_seller`, `rungs_with_qualifying_buyer` and `n_prints` (`maker_tape_census.py` `CensusedDay`, ~:437-452). These are fill-opportunity statistics, and `first_seen_ns` is in the same row.
- Each daily Stage A census run also prints C, `n_eff_ub`, the S-1/S-5 STOP lines and the KILL-LIKELY flag (:694-719).
- The plan says C4 "never prints C". That is true of C4, but the census that feeds C4 prints it daily, on a partial block.
- The risk is an interim S-5 STOP or KILL-LIKELY line acted on mid-accumulation. That would be data-dependent early termination of the block, which L-34 forbids.
- Required fix:
  - Doc A §4 must state that only the final Stage A over [S, E] binds for S-1 and S-5.
  - Daily-check census stdout and JSONL go to a sealed path that is never read. Only C4's counts output is consumed.
  - Add a test or procedure line proving the daily-check unit does not surface C or the STOP lines. Alternatively add a counts-only census flag.
  - R12 should say interim lines are non-binding. Currently it says "pre-registered STOP; accepted", which reads as binding at any interim.

**B2. §2 Doc A §5 / §3 C1 / §6 — "realised forfeiture" is mis-defined, and the registry leaves a read and holdout hole.**
- Realised forfeiture is not 4×(E−S+1). It is 4 × (max day ever passed to a census run with the Doc A sha − S + 1).
- Under a missed or retried timer, a check at c reads through c−2, which can exceed E. "Days after E are never read" holds only under perfect daily cadence.
- C1 row 1 clears 10-14..11-15 permanently for anyone holding the Doc A sha. After E, days E+1..11-15 remain code-cleared, and S5 holdout days (≥ E+2) fall inside that range.
- That contradicts `RULING_MAKER-S1_SEARCH_declaration_2026-10-12.md:41-42` ("S5 days … never read before their own declaration") in enforcement terms. The text declaration is fine; the code gate is not.
- Required fix:
  - Define forfeiture as the max invoked census day, recorded in the closing ledger line.
  - Add a census CLI guard or test that the range end is ≤ the check date − 2.
  - Bind S5 `holdout_start_date` ≥ (max census-invoked day under the Doc A sha) + 2, not E + 2.
  - Doc A must state that any read of a day > E is a violation reported on the ledger line.
  - Consider whether row 1's `last_day` should be a Doc B-pinned cap. Note that code is frozen before E is known, so the cap must be procedural plus tested.

**B3. §3 C3 — a false premise, and a residual void path.**
- `first_print_instant` (`maker_stage0_probe.py` ~:287-320) is restricted to the licensed `days` × `stations` (`station_day_key(..., day_set, station_set)`). It is not a global first print.
- For block 2 it returns the first print on 10-14+ rungs. Then `first_replayable_day` returns that print's date +1 (or +2 if after 16:50Z).
- The result is ≤ 10-14 only if the earliest block-day print lands on or before 10-13 16:50Z.
- That is probable but not guaranteed. A later first print gives 10-15, and C3's `probed ≤ block_first_day` voids the run after the ledger claim (driver :177 vs :225-229).
- Required fix:
  - Correct the rationale in the plan.
  - Move the v2 feed-live check ahead of the claim (a pre-claim preflight), or make it non-fatal. The check's purpose is that the feed exists before the first block day, which block-1 tape already proves.
  - Tests: `test_v2_first_print_after_cutoff_cannot_void_after_claim`, plus the plan's three tests.
  - R5's "Step-2 coordinator check" is only a manual mitigation of a post-claim void.

**B4. §3 C5 — incomplete.**
- `maker_stage0_render.py:42-45` carries block-1 prose beyond :86. It says "replay days 2026-09-18..2026-09-30 … 2026-10-02..2026-10-13 statistics are disclosed contamination for AUT-4 forward windows".
- For block 2 this contamination sentence omits 10-14..E, so the report is false by omission. That is the AUT-4 disclosure.
- C5 must cover :42-45 and :86, and the v1 byte-identity test must stay green.

## Non-blocking suggestions

- **T derivation (Doc A text).** State the shrink on `n_eff` (0.976), or state that 0.917 is a deliberate conservative bound. Fix the abstained/non-COVERED decomposition, and cite `wp0_agreement.json` rather than `station_days.csv`.
- **Test A power gate.** T secures V0 only. §6.9 needs ≥ 10 expected losses pooled (`MIN_EXPECTED_LOSSES`, `maker_stage0_stats.py:28`) or the screen is UNSCREENED. A block with V0 passing can still be NOT-KILLED-UNSCREENED. Say so in Doc A §8, and consider whether the spec's outcome-blind power check belongs in the trigger.
- **10-13 is an orphan.** It was declared and read under the first SEARCH, but it is in neither block, because it lacked FINAL at run 1 and amendment :20 says "never added". Starting at S = 10-14 is the conservative, correct reading. Say so explicitly in Doc A §1 so a later reviewer does not "recover" it.
- **P-3 (below).** A ledger date-overlap guard is not blocking.
- **C4 / census runtime.** Confirm that Stage A over [S, c−2] fits the `RuntimeMaxSec` 3600 daily window as the block grows to 33 dates.
- **W6 (`tail_summary.json`).** Fine. Keep `test_tail_annotation_never_changes_the_label`. The exact p is anti-conservative because bands of one vector are correlated, so label the annotation descriptive only.

## Answers to the planner's questions

**P-1: Disjoint blocks vs pooling. Disjoint is correct.**
- The amendment `RULING_MAKER-S1_SEARCH_declaration_amendment_2026-10-13.md:71` forbids "a second verdict scoring pass on this set". Any pooled statistic re-scores set-1 station-days.
- Amendment :77 says "More days (S3 r3 :149 second look) need a new dated declaration with its own frozen set". That is later and more specific than S3 r3 :149.
- S3 r3 :149 ("S2 re-emits its numbers") is satisfied by block 2 re-emitting its own numbers. It governs S3's UNDERDETERMINED state, not S2's V0.
- L-56 (`LESSONS.md:308-310`) says to never count the motivating observations toward n. Set-1 outcomes (V1/V3 0.0814 and the tail excess) are already seen.
- This is not wasted. Set 1 remains a descriptive dev set, and 44 station-days of exploratory evidence is exactly what S5's `dev_set: "Stage 0, exploratory, seen"` records.
- The price is about 22 dates instead of 7-8 more, a few weeks of calendar. No alternative stays within :71 and :77.

**P-2: Realised vs full-range SEARCH forfeiture. Realised is defensible, but not as written.**
- The read definition in `RULING_MAKER-S1_SEARCH_declaration_2026-10-12.md:34-35` is "any row … passes `admit_print`". RA-13 B-3 (`RULING_RA-13_programme_kill_2026-09-27.md:90`) says any post-freeze count, outcome-blind or not, spends the days.
- Run 1 forfeited the full range because its census covered the full range. Block 2's census never touches days past the check date − 2, so realised accounting is consistent with B-3 if (and only if) it is measured by the max census-invoked day and mechanically capped (B2).
- If E_max is hit, realised equals the full 132.

**P-3: Ledger date-overlap guard. Recommend adding it, as a separate non-blocking unit.**
- The gap is pre-existing: a byte-different v1-format copy of the amendment, with a new sha and the same dates, gets a fresh claim today (`ledger.py:203-204`). C2's v2 parser closes it only for v2 copies.
- A cheap guard is to record the frozen set's first and last date in the start entry and refuse overlap with any non-void prior entry.
- That widens the entry schema. Do it as an L-12 one-row widening, with a test for the exact-key sets.
- The plan's §2 position, that no ledger code change is needed, is correct for this plan's mechanics. The guard is hardening, not a prerequisite.

## Other plan checks

- **Tail disclosure routing is clean.** It is disclosure only, with a model-risk note into S5 PREREG, no refit and no label. §6.9 Test A margin 1.5 is spec-frozen (`maker_stage0_stats.py:26`, spec ~:296) and is untouched.
  - The direction claim is correct: under-predicted tail p_YES biases Test A toward FAIL (kill-first).
  - Note that 137 observed vs 54.4 expected is about 2.5×, over the 1.5 margin. The frozen block-2 Test A may well FAIL on that tail. That is the pre-registered path and must not be softened.
- **Calendar and S5 holdout.** The arithmetic is fine (`holdout_start_date` ≥ E + 2, S5 plan r3 :218; the 11-23 example at :296 is compatible). Enforcement is weak until B2 is fixed.
- **GO / FQ-v2.** GO is never an outcome, and the plan does not route to FQ-v2 triggers. Good.
- **Frozen constants.** None is re-tuned (10 s / 5 min clamp, RHO_ASSUMED 0.5, N_EFF_FLOOR 30, margin 1.5). T=34 is a new constant, pinned before any read and derived from set 1, which is already seen.

## Plan claims found false or wrong

1. C3 premise: "prints already exist since 09-17, so ≤ 10-14". The first-print scan is restricted to licensed block days (`maker_stage0_probe.py` ~:287-320).
2. "96 − 40 `listing_abstained` − 8 non-COVERED". The actual split is 44 abstained (including the four 09-29 rows) and 4 early-listed non-COVERED. The total of 48 is right.
3. "Shrink 44/48 = 0.917" as the `n_eff` shrink. The actual `n_eff` ratio is 18.733/19.200 = 0.976.
4. "Days after E are never read." This holds only under uninterrupted daily cadence.
5. C5 scope of `render.py:86` alone. `:42-45` is also block-1-specific.

Relevant paths:
- `/home/jon/breezy/scripts/analysis/maker_stage0_ledger.py`
- `/home/jon/breezy/scripts/analysis/maker_stage0_frozen.py`
- `/home/jon/breezy/scripts/analysis/maker_stage0_driver.py`
- `/home/jon/breezy/scripts/analysis/maker_stage0_probe.py`
- `/home/jon/breezy/scripts/analysis/maker_stage0_render.py`
- `/home/jon/breezy/src/breezy/analysis/maker_tape_census.py`
- `/home/jon/breezy/docs/evidence/maker/stage0_2026-10-16/wp0_agreement.json`
- `/home/jon/breezy/docs/evidence/maker/stage0_2026-10-16/station_days.csv`