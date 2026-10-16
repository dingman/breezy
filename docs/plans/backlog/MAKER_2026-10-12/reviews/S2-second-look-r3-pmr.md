**Verdict: APPROVE.** Nothing BLOCKING remains. Round-3 reviews are required to say what would void the single run, break a hard constraint or make a pre-registration non-blind, and I found none of those. I re-checked the r3 mechanism claims against code. I did not run the plan's full file:line list.

**Scores (1–10)**

| Criterion | Score |
|---|---|
| Correctness vs governing texts | 8 |
| Architecture/idiom fit | 8 |
| Test coverage | 8 |
| Risk mitigation | 8 |
| Scope minimality | 6 |
| Feasibility | 7 |

Scope is the lowest score because the plan carries about 10 freeze-scope units.

**What I checked in code**

- **Ledger (P-3, C5).** `maker_stage0_ledger.py:200-205`: `_refusal` selects `mine` on `kind == START and amendment_sha == sha`. A copied amendment with a new sha therefore is a fresh claim. That matches the plan's "no code change today" statement. C5's `block_first_day` match is the right guard.
- **Frozen day limits.** `maker_stage0_frozen.py:125-127` raises `FrozenSetRefused` for any day > `LAST_ALLOWED_DAY`. All block-2 dates are refused today, so the v2 branch is needed.
- **First-replayable check.** `maker_stage0_driver.py:224-229` has `require_clean()` and then the equality check, both after the claim. C3's report-only v2 handling is correct.
- **Preflight (C2).** `maker_stage0_preflight.py:153-168` checks only the truth sha, at :161. The pre-claim hash and E-recompute additions are real gaps being closed.
- **`listed_in_time`.** `maker_stage0_rule.py:250-255`: `None` gives False, and `listed_ns <= D-1 12:00Z` is inclusive. The plan matches this, including the D13 boundary test.
- **Census (C1b).** `scripts/analysis/maker_tape_census.py:285-296` classifies and scans every instance on each invocation. That justifies batching, and it honestly means reads past E are touched. `first_seen_ns` exists at `src/breezy/analysis/maker_tape_census.py:448`, so the counts-only file is feasible.
- **C6b storage claim.** `settlement_truth_dataset.py:280` has `_EXTENSION_WINDOW_END = 2026-09-28`, and the window list at :296-342 is built in code. The zip-fetch need is real. `afos_url` accepts `limit=3000` because `IEM_AFOS_MAX_LIMIT` is 9,999 at `settlement_alignment_study.py:52`. The 50 in `iem_mos_probe_transport.py:84` is a different transport. `iem_cli_fetch.py` lives at `scripts/archive/iem_cli_fetch.py`, so cite that path in the implementation.
- **Tail path (`--tail-csv`).**
  - `finish.py:67` reads `cfg.tail_csv`.
  - `_extra_pins` (`finish.py:80-86`) pins its sha and run manifest.
  - `tables.py:127-128` emits "TAIL-MISCALIBRATED (annotation; never changes the label)".
  - So `--tail-csv` on the block-2 verdict is a licensed disclosure, not a label path.
  - Tail rows are block-1 data and the tail annotation is not an input to the label. It must stay out of all n and CI computations. Doc A §3 and §10 say so.
- **Frozen constants.** `stats.py:26` has `AS_MARGIN = 1.5`, and `MIN_EXPECTED_LOSSES = 10.0` is at :28. D12 pre-registers the likely Test A FAIL without touching either. I accept that.

**Focus-question answers**

1. **Single-look discipline is code-enforced.**
   - C4 stops at the first crossing and writes a terminal CROSSED row.
   - Later `check` calls are refused.
   - The census refuses a second full run, and refuses a full run before `close`.
   - Counts-only exits 0 and writes four fields, so no S-1/S-5/KILL signal reaches the operator.
   - The chain hash is committed to the ledger line before the next read.
   - One residual gap: the batched read crosses E inside one invocation, so those reads past E are touched but not shown. They count toward forfeiture. The plan states this.
2. **E is recomputed pre-claim (C2).**
   - It is recomputed from the committed, hashed, counts-only rows.
   - It uses the frozen `T=34`, `RHO_ASSUMED` and `listed_in_time`.
   - Rows are hashed only up to E, and the dates are bound to `min(E, last_final_day)`.
   - The trigger is blind to prints and outcomes. COVERED and `first_seen_ns` are capture facts only.
3. **Forfeiture accounting is honest.** Realised forfeiture is 4 × (max invoked day − S + 1), and the ceiling is 132. The narrowing risk is disclosed with a fallback to 132. D4 closes the library bypass.
4. **Doc A §8 does not soften the margin.** It says Test A FAIL (NO-GO) is likely at a 2.5× tail excess against 1.5, and "that path stands".
5. **`--tail-csv` is a disclosure.** The block-1 tail CSV is pinned by sha, the annotation is label-neutral, and it is never used for refits or FQ-v2 triggers.

**BLOCKING issues**

None.

**Non-blocking items to fold in at implementation time**

1. **Reads after E in the narrowing commit.**
   - After narrowing row 1 to [S, E], days in (E, max-read] were touched by the batch.
   - They are outside the registry but inside the realised forfeiture.
   - The "any read of a day > E is a violation" line in Doc A §5 must be phrased as a disclosed expected overshoot of at most the check lag (up to about 2 days), not as an error condition. Otherwise the ledger line contradicts a normal run.
2. **S5 start.**
   - The rule "≥ max census-invoked day + 2" is correct.
   - Tie it to the read-ledger in code (a test), not only to prose in Doc A §7.
3. **Verify the `window-zip` request shape before Doc A FINAL.**
   - The request end is 11-15 while the fetch happens at E+2, so it is future-dated.
   - IEM's behaviour for a window that ends in the future (U-3) should be tested once on a bounded, past-dated range using the same code, as a dry run in the fake-transport test plus a single live smoke.
   - If the response is truncated or the `limit` is hit, the sha pin would still succeed on incomplete data.
   - Add an assertion that the last parsed CLI date ≥ E (or ≥ `last_final_day`) so a silent short window cannot pass the "overlap" guard.
4. **Independence of the cross-check.**
   - The "parsing-only" verdict is honest, so keep it.
   - Add to Doc A §1 that a shared upstream revision error would be invisible to the agreement check. Do not claim the cross-check validates truth.
5. **Trigger lock and ingest overlap.**
   - D2 accepts overlap with the ingest-frequent timer because the census treats LIVE instances as unread.
   - Add a test that a day whose instance is LIVE at check time yields "unread, not counted", so E cannot move earlier when the day is later re-read as COVERED.
   - The plan lists disagreements as "disclosed, never move E". Confirm in the test name.
6. **E drift between trigger rows and final Stage A.** The ordering is correct and disagreements never move E. Make the self-check (§6 step 5) fail closed, not report-only, when rows on days ≤ E disagree on `reason == COVERED`. That is what preflight's recompute implies.
7. **Test fixture cost.**
   - The v2 world is budgeted at one day, which is optimistic.
   - Keep the pure-function tests (`first_crossing`, `check_first_replayable`, the ledger key sets) first. They carry most of the risk.
8. **Sweep test.** `test_no_unlisted_block_date_literals…` is fine. Make the allowlist exact, as a set of (file, line-pattern), so it cannot silently absorb new literals.
9. **Bench exception.** The pre-declared C7 exception is acceptable. Require the ledger line to record the pre- and post-merge `CODE_SHA` and the bench numbers, and forbid any other diff in that merge (a test or CI check that C7 touches only `probe.py` and its split).
10. **Pinned `last_final_day` and E.** The fixed lag of about 2 days at `close` is observed, not guaranteed. The plan's STOP on `last_final_day < E` with retry is right. Add the named next action for a stuck truth timer (three days with no advance goes to a peer ruling), which R9 already covers.

**Answers to the planner's open questions**

- **P-1, disjoint blocks vs pooling: disjoint with no pooling.**
  - Amendment :71 forbids a second verdict scoring pass on the block-1 set. :77 requires a new declaration with its own frozen set for more days.
  - L-56 forbids counting the motivating fills toward n.
  - A pooled n would re-score the block-1 days.
  - Descriptive citation of block-1 numbers is acceptable.
- **P-2, realised vs full-range SEARCH forfeiture: report realised, with 132 as the ceiling and the fallback.**
  - The read-ledger makes the realised figure auditable.
  - If peers reject narrowing, 132 is forfeited at Doc A FINAL, as the plan says.
  - Compute the EDGE-4 date effect at both figures, as the plan does.
- **P-3, ledger date-overlap guard: key on `block_first_day`.**
  - A sha-only check lets a copied Doc A produce a second claim, since `ledger.py:200-205` selects on sha.
  - C5's `block_first_day` key plus C2b's CLI-layer pin of the v1 sha close this.
  - A full date-range overlap guard adds little beyond that. The census registry (C1/C1b) already refuses any day that is not under the right declaration sha.

**Claims in the plan I found false**

None. The two points I read closely, the C6b storage split and the preflight limits, both held. The r3 plan's one soft claim is U-3, which it already flags as unproven.

**Relevant files**

- `/tmp/claude-1000/-home-jon-breezy/dd6a5e89-5467-4ea7-b244-350f42894389/scratchpad/S2_second_look_plan_r3_draft.md`
- `/home/jon/breezy/scripts/analysis/maker_stage0_ledger.py`
- `/home/jon/breezy/scripts/analysis/maker_stage0_frozen.py`
- `/home/jon/breezy/scripts/analysis/maker_stage0_driver.py`
- `/home/jon/breezy/scripts/analysis/maker_stage0_preflight.py`
- `/home/jon/breezy/scripts/analysis/maker_stage0_rule.py`
- `/home/jon/breezy/scripts/analysis/maker_stage0_finish.py`
- `/home/jon/breezy/scripts/analysis/maker_stage0_tables.py`
- `/home/jon/breezy/scripts/analysis/maker_stage0_stats.py`
- `/home/jon/breezy/scripts/analysis/maker_tape_census.py`
- `/home/jon/breezy/scripts/analysis/settlement_truth_dataset.py`
- `/home/jon/breezy/scripts/analysis/settlement_alignment_study.py`
- `/home/jon/breezy/scripts/archive/iem_cli_fetch.py`