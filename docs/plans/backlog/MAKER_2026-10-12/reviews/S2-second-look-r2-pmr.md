**Verdict: REQUEST_CHANGES.** Two BLOCKING gaps remain, both in the single-look discipline that r2 relies on. Neither needs a redesign.

| Axis | Score |
|---|---|
| Correctness vs governing texts | 8 |
| Architecture/idiom fit | 8 |
| Test coverage | 7 |
| Risk mitigation | 7 |
| Scope minimality | 8 |
| Feasibility | 8 |

## Verified in code (claims that hold)
- **Shrink arithmetic.** I recomputed it from `station_days.csv` and `wp0_agreement.json` (stage0_2026-10-16).
  - 96 rows; 88 COVERED, 4 LONG_HOLE, 4 LOW_COVERAGE.
  - COVERED with `listing_abstain` false is 48, all 4 stations on each of the 12 dates 09-30 and 10-02..10-12.
  - Of those 48, 44 are bid-bearing; the exceptions are LAX 10-03, SFO 10-03, SFO 10-04 and LAX 10-08.
  - Proxy n_eff is 19.20 and recomputed n_eff_gov is 18.7333, so the shrink is 0.976 and 30/0.976 ≈ 30.7. T = 34 is a margin above that.
- **The trigger predicate matches the probe.**
  - I applied `rule.listed_in_time` (`maker_stage0_rule.py:250-251`) to all 96 `listing_ns` values in `wp0_agreement.json`. It agrees with `listing_abstain` on every row.
  - `wp0_agreement.json` itself states `listing_ns` is the same field as the census `first_seen_ns`.
- **COVERED is independent of fills.**
  - `classify` (`maker_tape_census.py:590-661`) decides COVERED from clean-instance count, coverage fraction and longest hole only. Prints are tallied after that decision.
  - The T trigger is therefore a posting and coverage count, not a fill statistic.
- **Block-1 refusal mechanics.**
  - `LAST_ALLOWED_DAY` is 10-13 (`frozen.py:36`) and `_check_dates` refuses later days (`:126-127`).
  - `FIRST_REPLAYABLE_CHOICES` refuses a first day of 10-14 (`:149-150`).
  - The ledger `_refusal` keys on sha only (`ledger.py:203-205`), and the six-key set is exact (`:66-69,149`).
  - The driver claims at `driver.py:177` and checks first-replayable equality at `:225-229`.
  - So A1, A7 and the C2/C2b premises are correct, and no ledger date-overlap guard exists today.
- **Annotation unreachable under `--tail-only`.**
  - `run_tail` (`report.py:181-212`) writes only the CSV and manifest.
  - The only emitter of TAIL-MISCALIBRATED is `tables.py:127-128`, fed by `tail_table` (`stats.py:355-366`).
- **Tail margin.** `AS_MARGIN = 1.5` (`stats.py:26`). The evidence table gives 137 observed vs 54.4 expected, which is 2.5×. The plan's routing is right: disclose it, leave the margin frozen, and do not soften a Test A FAIL.
- **Bench is clean.**
  - Bench runs the simulator, but progress events are whitelisted with no fill, rate, label or episode field (`runio.py:41,168`).
  - `bench4.json` carries only timing and RSS plus `n_events`.
  - Licensing bench before the verdict claim leaks no fill statistic.
- **Timers.** Verified at 02:05Z, 09:00Z rotate, 00/06/12/18:15Z ingest, 11:40Z and 12:40Z. A 10:00Z check of day c−2 is cataloged: the 09:00Z rotation on c−1 is ingested at 12:15Z on c−1.

## BLOCKING

**1. C4 `check` can read past E, so "days after E are never read" is not a code guarantee (§3 C4, acceptance 6, Doc A §5).**
- *Problem.*
  - C4 loops "for each not-yet-checked d ≤ c−2", appends rows, and only `close` computes E (plan lines 217-220). There is no stop at first crossing.
  - After a missed timer (R10 shows this happens), a catch-up batch can cross 34 mid-batch and keep reading.
  - A next-day `check` before `close` has the same effect.
- *Consequences.*
  - Days > E enter `trigger_rows.jsonl`, so `trigger_rows_sha256` covers non-pinned days.
  - The C1b max-day ledger then records days > E, so realised forfeiture exceeds 4×(E−S+1).
  - Those days become SEARCH-spent, and the S5 `holdout_start_date` ≥ max read day + 2 shifts later.
  - The C1b guard (`--to ≤ today−2`) does not prevent this.
- *Required fix.*
  - After each appended day, `check` evaluates the crossing, writes a terminal `CROSSED` row, and refuses all later `check` calls.
  - `close` hashes only rows ≤ E.
  - Add the test `test_check_stops_at_first_crossing_inside_a_catch_up_batch` and a test that a post-crossing `check` is refused.

**2. "Final Stage A" is undefined in code and unpinned, so the single fill-type look is a process rule only (§2 Doc A §4, Doc B fence, §3 C1b).**
- *Problem.*
  - The census CLI (`maker_tape_census.py:487-520`) prints C, S-1 and S-5 lines and uses the S-5 screen as its exit code on every full run.
  - Nothing in the plan stops a second full run over [S, E], or over a sub-range, with the Doc A sha.
  - The C1b read-ledger does not record run mode.
  - The Doc B fence (plan line 124; `frozen.py:38-45` `_FIELDS`) has no `census_days_sha256`. Today the census path appears only in `pins.json:10,45`, after the fact.
  - Rows can legitimately differ between runs (`instances_live_unread` flips `reason`, `maker_tape_census.py:433-435`). A re-run could therefore be repeated until Stage A is acceptable, which is the L-34 second-snapshot failure.
- *Required fix.*
  - Registry rows ≥ 1 refuse a non-`--counts-only` census run unless `--to` equals the closed trigger E and the ledger holds no prior full run for that sha.
  - Add `mode` to the C1b ledger line.
  - Add `census_days_sha256` to the `FROZEN_DATE_SET_V2` fence, verified in preflight.
  - A second full run requires a dated addendum.
  - Tests: `test_second_full_census_under_doc_a_sha_refused`, `test_full_census_before_close_refused`.

## Non-blocking suggestions
- **Chain-hash each trigger append.**
  - The trigger datum is committed only at `close`, so rows are editable until then. The "each day checked once" rule rests on the file's own contents.
  - Write a running chain hash of the rows into the C1b ledger line at each `check`. That is a contemporaneous commitment and costs one field.
- **Make the read-ledger tamper-evident.** `~/.local/share/breezy/derived/maker_stage0/search_read_ledger.jsonl` is mutable and outside the repo. The closing ledger line should embed its sha256.
- **Library-level callers bypass the CLI guard.** Registry row 1 clears 10-14..11-15 for any caller of `require_firewall_clearance` (for example `trade_quantity_unit_crosscheck.py:121-128` and the `maker_stage0_*` modules), and only the census CLI writes the read-ledger. The narrowing to [S, E] after the evidence commit closes this. State that the window between E and that commit is the exposure.
- **B6 is a one-time check.** The 10-17 pre-check cannot cover nightly consumers over 10-18..E. RA-13-FW found the exit-window study reads Depth10 for filled positions (`RA-13-FW_firewall_audit_2026-09-27.md:17`). Add a re-check at `close` and name it on the ledger line.
- **Pre-register the expected tail path.** Doc A §8 should state that, given the 2.5× tail excess, a Test A FAIL (NO-GO) is the likely outcome. That is prediction-market discipline, not softening.
- **Disclose that T is block-1-informed.** T = 34 uses block-1 bid-bearing facts (a posting fact, not a fill), fixed before any block-2 read. That is acceptable. Doc A should say so and name the unmodelled risk that early listing, which began 09-30 in block 1, may not persist (R1).
- **C4 invocation.** Make sure the subprocess exit code in counts-only mode cannot carry `_EXIT_UNSCREENED` (`maker_tape_census.py:523`), which encodes the S-5 screen. The plan says exit 0; add a test.

## Answers to the planner's questions
- **P-1 (disjoint blocks vs pooling): disjoint, standalone V0, no pooled table, even report-only.**
  - Amendment :71 forbids a second scoring pass on the block-1 set, and a pooled V0 is one.
  - :77 requires a new dated declaration with its own frozen set for more days.
  - S3 :149 sits under S3's own UNDERDETERMINED state and predates the later :77.
  - L-56 backs the same separation: block-1 fills never count toward block-2 n.
- **P-2 (realised vs full-range forfeiture): realised, conditional on fixes 1 and 2 plus the narrowing.**
  - Unread days are not spent, so 4×(max read day − S + 1) is the honest cost.
  - It is only trustworthy if the tool structurally cannot read past E (BLOCKING 1). Keep the 132 fallback if peers reject the narrowing.
- **P-3 (ledger date-overlap guard): not needed beyond r2.**
  - C2 refuses any date ≤ 10-13 and any `block_first_day` other than 10-14.
  - C2b pins the v1 sha and adds the `block_first_day` ledger key. Together these give one claim per block, covering a byte-different Doc B′ or a v1-format copy.
  - A general overlap guard would add a widened-key surface for no extra protection.

## Round-2 resolution table audit

| Item | Status |
|---|---|
| A1, A2, A3, A6, A7, A8, A10, A11, B1-B10 | Implemented as claimed; code citations check out |
| A4 | Counts-only emitter is correct, but the "single look" is unenforced (BLOCKING 2) |
| A5 | Forfeiture accounting is sound only with stop-at-crossing (BLOCKING 1) |
| A9 | Pinned datum is incomplete: nothing pins the final census output, and the trigger rows are not chained before `close` |

## Claims found false
None. Every mechanism claim I checked held: timers, shrink, `first_print_instant` scope, `_refusal`, literals, and the `run_tail` and `tail_table` unreachability.

## Hard constraints
No violations found. Nautilus, `allow_short`, the NO-SEND firewall and the frozen constants are untouched. W3 is dropped, and S-* screen tests are not touched.

Files:
- Plan: `/tmp/claude-1000/-home-jon-breezy/dd6a5e89-5467-4ea7-b244-350f42894389/scratchpad/S2_second_look_plan_r2_draft.md`
- `/home/jon/breezy/scripts/analysis/maker_tape_census.py`
- `/home/jon/breezy/src/breezy/analysis/maker_tape_census.py`
- `/home/jon/breezy/scripts/analysis/maker_stage0_ledger.py`
- `/home/jon/breezy/scripts/analysis/maker_stage0_frozen.py`
- `/home/jon/breezy/scripts/analysis/maker_stage0_driver.py`
- `/home/jon/breezy/scripts/analysis/maker_stage0_report.py`
- `/home/jon/breezy/scripts/analysis/maker_stage0_stats.py`
- `/home/jon/breezy/docs/evidence/maker/stage0_2026-10-16/wp0_agreement.json`
- `/home/jon/breezy/docs/evidence/maker/stage0_2026-10-16/station_days.csv`