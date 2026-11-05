**Verdict: REQUEST_CHANGES**

The disjoint-block ruling and the C1–C5 architecture are sound. But the plan as written would almost certainly void the one block-2 verdict run after the ledger claim (B1, likely B2). It also leaves the one-claim rule unenforced for block 2 (B4) and lets the daily trigger checks look at the S-5 fill screen (B3).

## Scores (1–10)
| Axis | Score |
|---|---|
| Correctness vs the governing texts | 7 |
| Architecture / idiom fit | 7 |
| Test coverage (happy, failure, edge) | 6 |
| Risk mitigation | 4 |
| Scope minimality | 6 |
| Feasibility | 5 |

## Verify-first results
1. **Ledger.** Confirmed. `_refusal` matches only `e["amendment_sha"] == amendment_sha` and returns `None` when nothing matches (`maker_stage0_ledger.py:203-205`). The sha comes from the CLI (`maker_stage0_replay.py:95-97`). So a new sha is a fresh claim with no code change. There is **no date-overlap guard** (see B4).
2. **Frozen set.** Confirmed. `LAST_ALLOWED_DAY = 2026-10-13` (`maker_stage0_frozen.py:36`) is refused at `:126-127`. `FIRST_REPLAYABLE_CHOICES` is checked at `:149-150`. `verify_set_matches_rule` clamps with `min(..., LAST_ALLOWED_DAY)` at `:202-203`, so it must dispatch on the block too. The plan covers this.
3. **Driver first-replayable check.** The order is confirmed: claim at `maker_stage0_driver.py:177-187`, then `_execute` → `_wp0`, then the equality check at `:225-229`. A failure voids the run. **The plan's reasoning for C3 is false** (see B2).
4. **Census firewall.** Confirmed: one range and one sha (`maker_tape_census.py:71-78`, `:191-199`).
5. **Tail annotation.** Confirmed unreachable from `--tail-only`. `run_tail` writes only the CSV and manifest and never calls `tail_table` (`maker_stage0_report.py:181-212`). The only emitter is `render_verdict` (`maker_stage0_tables.py:127-128`).
6. **Block-1 literals.** `render.py:86` is confirmed, and **there is a second one: `HOLDOUT_LINE`, `maker_stage0_render.py:41-47`** (see B5). The others are docstrings or comments (`inputs.py:334`, `runio.py:96`) or intended (`driver.py:113` `TAIL_RANGE`).
7. **Shrink arithmetic.** 44 of 48 is correct. Rows 50-97 of `station_days.csv` hold 12 dates × 4 = 48 COVERED rows. Four have `bid_bearing=false`: 10-03 LAX and SFO, 10-04 SFO, 10-08 LAX. But the derivation shown is wrong, and so is the unit (see non-blocking item 1).

## BLOCKING issues

**B1 — §6 calendar / §3: the truth cross-check is stale, so the run voids after the claim.**
- `load_truth` raises `InputRefused("...vacuous")` when the truth CSV and the cross-check share no keys (`maker_stage0_inputs.py:357-360`).
- It runs post-simulation, which is after the claim (`maker_stage0_report.py:117-122`).
- The cross-check `settlement_truth.parquet` is "stale (≤ 09-28)" (`S2_stage0_replay_plan_r3.md:122,216`). The CLI default is `maker_stage0_replay.py:35-37`.
- Block 2 is ≥ 10-14, so there is no overlap and the run voids for certain. The plan never mentions this. R10 checks only the truth CSV's `last_final_day`.
- **Fix:**
  - Pin a cross-check source that covers [S, E], and license it in Doc B §1.
  - Add a C6 unit: an overlap check before the claim, in `preflight`, using the same keys. Test: `test_v2_cross_check_without_overlap_refused_before_claim`.
  - Never relax the vacuous-overlap guard.

**B2 — §3 C3: the premise is false, and the `≤` rule can still void the run.**
- The plan says "prints already exist since 09-17, so the result is ≤ 10-14". That is wrong. `first_print_instant` counts only prints licensed to the requested maker stations × frozen days (`maker_stage0_probe.py:294-320`, via `station_day_key` → `admit_print`, `probe_core.py:260-275`).
- For block 2 it returns the first print on a **10-14 rung**. If that print falls after 10-13 16:50Z, the result is 10-15 (`probe_core.py:210-215`). `probed ≤ block_first_day` then fails after the claim.
- **Fix:** state what the check means for v2: the feed covers D-1 16:50Z for `block_first_day`. Then either:
  - (a) evaluate it before the claim, by running step 2 (first print) before Doc B FINAL and pinning the result in the fence, or
  - (b) make it report-only for v2, because census COVERED and `verify_set_matches_rule` already enforce coverage for each station-day.

  Add a test for a first print after D-1 16:50Z.

**B3 — §1 / §2 "What S1 re-runs" / C4: the daily trigger checks look at the S-5 fill screen.**
- The trigger depends on census Stage A rows. Every census run prints `C` and the `STOP S-5 NO-GO pre-screen` and `S-1` lines (`scripts/analysis/maker_tape_census.py:444-450`, printed at `:519`).
- Census rows also carry `buyer_by_bucket`, `n_prints` and `rungs_with_qualifying_buyer` (`src/breezy/analysis/maker_tape_census.py:401-421`).
- So about 20 daily runs over a growing [S, c−2] are repeated looks at a fill-type NO-GO screen. Either the screen binds on each run (no α correction) or someone peeks at it. This conflicts with the plan's own acceptance criterion and with L-34 ("a re-look is a second snapshot"). Making C4 "never print C" is cosmetic.
- **Fix:**
  - Use a counts-only census path that emits only `station, climate_day, reason, first_seen_ns` and no summary. Either a census flag or C4 calling the classifier directly. Add a test that the output has no print or C fields.
  - Doc A states that S-1 and S-5 bind **only** on the final [S, E] census.

**B4 — §2 Ledger / R8 / P-3: the one-shot rule is not enforced in code for block 2.**
- `load_amendment` accepts whatever sha the CLI supplies (`frozen.py:163-171`). The ledger keys only on that sha.
- So a byte-different Doc B′ (v2) gets a fresh claim and **re-scores block 2**, and a v1-format copy re-scores block 1. R8 names only the v1 case.
- **Minimal fix (no new architecture):**
  - (i) The v1 path pins the AMEND_SHA constant `cf9a4dad…` (evidence `:15`), so any other v1 document is refused. The ledger already holds that sha.
  - (ii) The v2 start entry records `block_first_day`. Widen `_KEYS_BY_KIND[KIND_START]` by one reviewed key (L-12). Refuse a second v2 start for the same block unless an addendum names it.
  - Tests: `test_v1_refuses_any_amendment_but_the_pinned_sha`, `test_second_v2_licence_same_block_refused_without_addendum`.

**B5 — §3 C5: it misses `HOLDOUT_LINE`.**
- `maker_stage0_render.py:41-47` hard-codes "replay days 2026-09-18..2026-09-30 ... inside the frozen NBP holdout" and "2026-10-02..2026-10-13 ... disclosed contamination".
- For block 2 this is false, and it contradicts Doc A §6 (contamination [10-14, E]). It would put a false governance claim into the evidence report.
- **Fix:** C5 renders both `_D5` and `HOLDOUT_LINE` from the block. v1 output stays byte-identical. Add a test.

**B6 — §1 End day / L-34: the trigger datum is not pinned.**
- The plan says "E is a property of the census rows". But rows change between runs: an instance that is LIVE or CORRUPT goes unread (`instances_live_unread`, `instances_corrupt_unread`), so `reason` can flip.
- The final census over [S, E] can therefore recompute a different E or n_eff_proxy.
- **Fix:** Doc A pins:
  - E is fixed by the trigger run's rows, which are hashed and pinned in the Doc B fence.
  - What happens if the final census disagrees on any day ≤ E. Recommended: the trigger rows govern E, and any disagreement is disclosed and never moves E.

## Non-blocking
1. **T = 34 derivation.**
   - The plan applies a station-day **count** shrink (0.917) to **n_eff**, but n_eff is concave in m_d. Set 1's n_eff shrink is 18.73 / 19.2 (12 dates × 1.6) = 0.9755, which gives T ≈ 30.8.
   - T = 34 is acceptable as a stated conservative margin. But the derivation must be restated in n_eff units. Either keep 34 and label the extra margin, or use 32 (saves about 1–2 dates, i.e. 4–8 SEARCH station-days).
   - Decide before any block-2 read.
2. **W1 feasibility (L-3).**
   - "PROJ ≤ 21,600 or STOP before claim" has no next action. Run 1 used a ≈7,800 s preamble plus ≈7,400 s to score 96 station-days (evidence `:22`). Block 2 has 88–132 station-days and a larger catalog.
   - Pre-plan the remedy: filter instances by the station-days in their directory names (the census already uses those names, `CensusedDay` docstring `:433-435`). Make it a conditional must-land if PROJ > 0.8 × RTMAX.
3. **Trigger cadence.**
   - `RuntimeMaxSec` 3600 for a daily census over the whole of [S, c−2] has never been measured.
   - Run incrementally on [c−2, c−2] and append. This is cheaper and also makes B6's pinning trivial.
   - Check 10:00Z against the nightly studies (one heavy job at a time) and the truth timers at 11:40/12:40.
4. **W6 is dead for this look.** `--tail-only` is unlicensed. The Doc B §1 item 5 recompute from the sidecar needs a CSV → `tail_table` function, not a change to `run_tail`. Either implement that small pure function after the verdict, or drop item 5 (already disclosed at evidence `:100-111`).
5. **Scope / freeze.** Freeze only C1–C6 plus W1 (and the W2 filter if note 2 triggers). Move W2–W4 and W6 after the evidence commit. W3 deletes a pre-existing test, so keep it out of the CODE_SHA diff.
6. **Fence prefix.** `_OPEN_FENCE = "```FROZEN_DATE_SET"` is a prefix of `FROZEN_DATE_SET_V2` (`frozen.py:46-47,139`). Dispatch must use exact-fence regexes. Add tests that a v2-only doc is refused by the v1 parser and a v1 doc by the v2 parser.
7. **RA-13-FW pre-check.** Before Doc A FINAL, confirm that no other consumer (exit-window nightly, monitor or hold studies) has already read 10-14+ tape as a statistic. The 10-12 §3 declaration did this audit for its 14 possibly-read days.
8. **S5 overlap.** The firewall row 1 runs to 11-15, but the S5 holdout starts at E+2 (≈ 11-06). After the evidence commit, narrow row 1 to [S, E]. This is a tightening, so L-12 is safe. Without it, S5 holdout days stay clearable under Doc A's sha, against 10-12 `:41-42`.

## Answers to the planner's questions
- **P-1 (disjoint blocks vs pooling): disjoint. Agree.**
  - Amendment `:71` forbids a second scoring pass on set 1.
  - `:77` says "its own frozen set". It is later and more specific than S3 r3 `:149`, which governs S3's UNDERDETERMINED state, not S2's V0.
  - L-56 (`LESSONS.md:308-310`) forbids counting the motivating sample.
  - A standalone S2 re-emission still satisfies `:149`'s "S2 re-emits its numbers".
- **P-2 (realised vs full-range forfeiture): realised accrual, with conditions.** RA-13 B-3 (`:90`) spends "ANY post-freeze count", so only days actually counted are spent. The 10-12 precedent (`:35-36`) forfeits the whole scope "at the first WP1 run", but that run read the whole scope. State in Doc A:
  - each station-day is forfeited at the first census run whose range includes it;
  - the ceiling of 132 is disclosed;
  - the post-evidence narrowing (note 8) makes "never read past E" true in code.

  If peers reject the narrowing commit, fall back to full-scope forfeiture of 132 at Doc A FINAL.
- **P-3 (ledger date-overlap guard): yes.** See B4. The hole also applies to block 2, not only to v1 copies.

## False claims in the plan
1. §3 C3: "prints already exist since 09-17, so the result is ≤ 10-14". The first-print scan is limited to the frozen days (`maker_stage0_probe.py:294-320`).
2. §1 T: "96 covered − 40 `listing_abstained` − 8 non-COVERED". Census COVERED = 96 includes 10-01 and 10-13, which are outside the set (evidence `:35`: D_cov 24, LONG_HOLE 4, LOW_COVERAGE 4 separate). The frozen set has 88 COVERED rows; 88 − 40 = 48. `wp0_agreement.json` has 44 `listing_abstain: true`, 4 of them on non-COVERED days.
3. R7 / unknown (c): `render.py:86` presented as the hidden literal. `HOLDOUT_LINE` at `:41-47` is a second one.
4. §2: "The trigger checks (C4) are counts-only reads of census rows". The census run that produces those rows prints C and S-5 (`scripts/analysis/maker_tape_census.py:444-450,519`).
5. §5 "Exactly one ledger claim": true for a single launcher, but it is a process rule, not a code guarantee (`ledger.py:203-205`).

## Relevant files
- `/home/jon/breezy/scripts/analysis/maker_stage0_driver.py`
- `/home/jon/breezy/scripts/analysis/maker_stage0_frozen.py`
- `/home/jon/breezy/scripts/analysis/maker_stage0_ledger.py`
- `/home/jon/breezy/scripts/analysis/maker_stage0_inputs.py`
- `/home/jon/breezy/scripts/analysis/maker_stage0_report.py`
- `/home/jon/breezy/scripts/analysis/maker_stage0_probe.py`
- `/home/jon/breezy/scripts/analysis/maker_stage0_probe_core.py`
- `/home/jon/breezy/scripts/analysis/maker_stage0_render.py`
- `/home/jon/breezy/scripts/analysis/maker_stage0_replay.py`
- `/home/jon/breezy/scripts/analysis/maker_tape_census.py`
- `/home/jon/breezy/src/breezy/analysis/maker_tape_census.py`
- `/home/jon/breezy/docs/evidence/maker/stage0_2026-10-16/station_days.csv`
- `/home/jon/breezy/docs/evidence/maker/STAGE0_REPLAY_2026-10-16.md`
- `/home/jon/breezy/docs/plans/backlog/MAKER_2026-10-12/S2_stage0_replay_plan_r3.md`