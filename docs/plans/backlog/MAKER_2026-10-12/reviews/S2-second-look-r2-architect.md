**Verdict: REQUEST_CHANGES**

Most r1 items are fixed in r2 and check out against the code. Two blocking items remain: C6 has no cross-check source that can cover the block, and the end day E is pinned only in a document, with no code check. One sequencing contradiction (bench vs the merge freeze) also needs an explicit rule.

### Scores (1–10)
| Axis | Score | Note |
|---|---|---|
| Correctness vs the governing texts | 8 | Pooling, the 10-13 orphan, report-only C3 and the one-claim ledger rule are all sound |
| Architecture / idiom fit | 8 | New registry module, exact-set widening, preflight placement |
| Test coverage | 7 | Some exact-set and exit-code tests are missing (see N-2, N-3) |
| Risk mitigation | 6 | C6 fails for certain on its stated source; E is not verified in code |
| Scope minimality | 8 | Freeze scope is stated and the W-items are moved after the evidence commit |
| Feasibility | 6 | The cross-check source is infeasible without a code change |

### r1 items: verified in code
- **A1 / C3: resolved, and the premise is now correct.**
  - The equality check runs after the claim. The claim is at `maker_stage0_driver.py:177-187`; the check is in `_wp0` at `:225-229`, reached through `_execute` at `:190`, so a mismatch hits the `RunVoided` path at `:191-196`.
  - `first_replayable_day` (`probe_core.py:210-215`) gives D+1 or D+2 from the first print. A first print on 10-12 would give 10-13, and one after 16:50Z on 10-13 would give 10-15. Either is a mismatch, so making v2 report-only is required.
  - The value is already recorded at `probe.py:381-383`.
- **A6 / C6 mechanism: confirmed.**
  - `load_truth` refuses an empty overlap as vacuous (`inputs.py:357-360`). It is called from `score` after the simulation (`report.py:117-122`).
  - `preflight` (`preflight.py:153-168`) runs before the claim (`driver.py:148`), so the new check sits in the right place.
  - **But the source is wrong** (B-1 below).
- **A7 / C2b: correct.**
  - `_refusal` today keys only on the sha (`ledger.py:203`). The start entry has six keys (`:66-69`, `:244-251`).
  - The plan's "mine = same sha or same block_first_day" rule, plus C2's refusal of any `block_first_day ≠ 10-14`, does make one claim per block a code guarantee.
  - The v1 sha pin closes the copied-v1-amendment route, since `load_amendment` accepts any supplied sha (`frozen.py:163-171`).
- **A10 / C2: correct.**
  - `_OPEN_FENCE` is a prefix of the v2 fence name (`frozen.py:47`, used at `:139`), so exact anchored fences are needed.
  - `_check_dates` refuses any day after 10-13 (`frozen.py:126-127`), and `FIRST_REPLAYABLE_CHOICES` (`:37`) refuses every block-2 date today.
- **C1 / B1: correct.**
  - The registry is a single chokepoint at `src/breezy/analysis/maker_tape_census.py:178-200`, with one range at `:71-73` and one sha at `:76-78`.
  - The census reason does not depend on prints: COVERED is decided from coverage alone (`:634-661`), so a counts-only trigger is outcome-blind.
- **A3 shrink arithmetic: verified.**
  - `station_days.csv` has 88 COVERED rows, and `wp0_agreement.json` has 44 `"listing_abstain": true` rows.
  - The abstentions are 09-18..09-27 and 09-29 only. From 09-30 every station is listed early, so the plan's ≈22-date calendar is plausible.
- **A2 / C5 literals: verified.** `render.py:42-45` (HOLDOUT_LINE) and `:86` (D5) are the only block-1 date literals with run-time effect besides `frozen.py:35-37` and `driver.py:113`.
- **A4 / C4: counts-only design is sound.** It needs the extra test in N-3.
- **A5 / C1b, A8, A9 (sha pinned; see B-2), A11 / C7: present.**

### BLOCKING

**B-1. §3 C6 / Doc B fence: `settlement_truth_dataset.py` cannot produce a cross-check covering [S, E].**
- **Evidence:**
  - The archive windows are hard-coded: `_EXTENSION_WINDOW_END = dt.date(2026, 9, 28)` (`settlement_truth_dataset.py:280`, used at `:335-336`); validation ends 08-23 (`:269`).
  - The `--include-extension` help confirms "2026-01-01..2026-09-28" (`:1253-1263`), and a cache miss is a refusal (`:13-14`).
  - So re-running it as C6 says gives zero block-2 rows. C6 would then STOP before the claim with certainty, and the case would go to a peer ruling at E+2. U-3 is already answered: no.
- **Independence:** both the dataset (the IEM AFOS CLI archive, `:1-14`) and fq-truth (`iem_cli_fetch.py`, per `breezy-truth-fetch.service:35` and `breezy-truth-dataset.service:29`) are IEM CLI products. The independence caveat therefore almost certainly applies, rather than being merely possible.
- **Required fix, decided before Doc A FINAL** (Doc A carries the Doc B template verbatim, and Doc A is immutable once FINAL):
  - Name a feasible cross-check producer for [S, E] and its refresh path. For example: a reviewed one-row widening of the archive window with a pinned window-end constant plus the cache fill it needs, inside the freeze scope; or a different settlement source that has the `station / climate_day(date) / status / tmax_f` schema (`inputs.py:303-307`).
  - Write the independence verdict into Doc A, not as a caveat for later.
  - Never relax the vacuous-overlap guard.

**B-2. §1 / §3 C2 / C4: E is a hand-copied field, not a code-verified fact.**
- The fence has `trigger_rows_sha256` but no `trigger_rows_path`.
- C2's v2 rule takes `trigger_day` from the document and checks only `trigger_day ≤ 11-15` and `last_final_day ≥ trigger_day`.
- Nothing in preflight hashes the trigger rows or recomputes the first crossing. Acceptance criterion 1 ("E is fixed by pinned, counts-only trigger rows") is a process rule, which is exactly what A7 asked to be turned into code for the claim.
- `trigger_rows.jsonl` also sits in an untracked derived directory and can be rewritten before `close`.
- **Required fix:**
  - Add `trigger_rows_path` to the v2 fence, as a committed, repo-relative copy; the rows are counts-only and outcome-blind, so committing them is safe.
  - In verdict-mode preflight: hash it against the fence; recompute E with C4's pure first-crossing function, using the same frozen T = 34, `RHO_ASSUMED` and `listed_in_time`; refuse on any mismatch before the claim.
  - Test: `test_v2_trigger_day_must_recompute_from_pinned_rows`.
  - Fold the new fence field into the Doc B template before Doc A FINAL.

### Sequencing / governance (should fix in r3; not blocking on its own)
- **S-1. Bench vs the merge freeze.**
  - `--bench` loads the amendment (`driver.py:161-164` calls `preflight.py:154`), so the decisive bench projection can only run after Doc B FINAL.
  - But "nothing merges between Doc B FINAL and the evidence commit" (acceptance criterion 5), and §4 W1 re-measures at Doc B FINAL. If the bench says PROJ > 21,600 s, the plan has a bare STOP with no next action (L-3).
  - Fix: pre-declare that a STOP at bench time allows one C7 merge before the claim, followed by a full gate and a re-bench. Nothing has been scored, so this does not touch the outcome. Disclose it in the ledger line.
  - Alternatively, license a bench under Doc A on a fixed, pre-named block-2 subset.
- **S-2. Doc A FINAL → C1 sha → census: correct order.** C1 cannot exist before Doc A's bytes (`test_pinned_second_declaration_sha_matches_committed_file`). B-1 and B-2 must be folded into Doc A before it goes FINAL.
- **S-3. The final Stage A must precede Doc B FINAL** so that S-1/S-5 can STOP before the fence is written. §6 lists these in one cell. State the order explicitly: truth copy pinned → cross-check pinned → final Stage A → STOP check → trigger verification (B-2) → Doc B FINAL.
- **S-4. The 10:00Z cadence check (B5) is incomplete.**
  - The plan omits `breezy-quote-tape-ingest-frequent.timer:27`, which runs every 15 minutes from 00:00 to 15:45Z, so 10:00Z coincides with an ingest tick.
  - It also omits the 09:20/09:25Z digest/retention timers (`breezy-decision-funnel-digest.timer:15`, `breezy-decisions-retention.timer:15`), which are light.
  - Either take the studies `flock` against ingest-frequent too, or justify that the two are non-conflicting.

### New holes introduced by the r2 fixes (non-blocking)
- **N-1. The C1b read-ledger is CLI-only.**
  - `trade_quantity_unit_crosscheck.firewall_clearance` (`:121-132`) calls `require_firewall_clearance` directly. Given the Doc A sha, it would clear block-2 days without writing a ledger entry, so realised forfeiture would be under-stated.
  - Fix: have that caller refuse registry rows ≥ 1, with a test. This is a two-line, guard-only edit, not a weakening.
- **N-2. No existing test pins the ledger key set.**
  - A grep of `tests/` finds no `_KEYS_BY_KIND` or exact-set assertion; only `test_maker_stage0_frozen.py:309` and `:401` touch `addendum_sha`.
  - Add `test_start_entry_key_sets_are_exactly_six_or_seven` and a driver-level test that a v2 claim writes `block_first_day` from `pre.frozen`.
  - `_refusal` must match on `block_first_day` only when it is not null, and read legacy six-key entries with `.get`.
- **N-3. Counts-only must also suppress the outcome-bearing exit code.**
  - Census `main` returns `_EXIT_UNSCREENED` when `s5_unscreened` (`scripts/analysis/maker_tape_census.py:520`).
  - Extend `test_counts_only_output_has_exactly_four_fields_and_no_summary` to assert exit 0 whatever `s5_unscreened` is.
  - Also refuse the full, non-counts-only census under the Doc A sha until `close` has written E. That turns A4 from a process rule into code.
- **N-4. C6 key equality.**
  - The preflight overlap uses frozen keys, while `score` uses `sd_rows` keys (`report.py:118`). If `sd_rows` were ever a strict subset, preflight could pass and the post-claim check could still void.
  - Pin the equality with a test, or build both key sets with one shared helper.
- **N-5. The C5 sweep allowlist is too tight.** It would flag path literals that are not date semantics: `replay.py:40` (`DEFAULT_SPEC`), `model.py:34` (`EVIDENCE_DOC_REL`), and the module docstrings (`verdict.py:3`, `stats.py:3-5`, `fill.py:3-5`, and others). Scope the sweep to date-valued literals (`dt.date(...)` / bare ISO dates outside path strings).
- **N-6. C7 / W1 scaling.**
  - The `keep_rung` conversion filter already exists (`probe.py:280`, `scoped_convert.py:71-83`). The remaining preamble cost is `scan_instance_memoized`, which "reads every byte" (~70 s per 15 GB, `scoped_convert.py:136-137`).
  - So scale `PREAMBLE_S` by total live-instance bytes, not by `N_inst`.
  - The pre-filter must not drop an instance whose start ends an earlier span (driver D3, `driver.py:17-18`). Keep `test_licensed_output_identical_with_and_without_prefilter` on a fixture that has such an instance.

### Planner questions
- **P-1 (disjoint vs pooled): disjoint, standalone V0, no pooled table.** Amendment :71 forbids a second scoring pass on block 1, and :77 requires a new frozen set. S3 :149 belongs to a different state (UNDERDETERMINED). The spec (:222-224) is silent on pooling, and L-56 settles it.
- **P-2 (forfeiture): realised accrual from the C1b ledger, with the 132 ceiling disclosed as the upper bound.** This is acceptable only once N-1 closes the non-CLI read path. Otherwise "realised" is a lower bound, and the 132 fallback should apply.
- **P-3 (date-overlap guard): C2's v2 refusal of any date ≤ 10-13 plus the `block_first_day` ledger key is sufficient.** A general overlap guard over arbitrary blocks would be speculative (YAGNI) while only two blocks exist.

### Claims found FALSE or unsupported
1. C6, "Re-run `settlement_truth_dataset.py` … a pinned copy covering [S, E]": false; the windows end 09-28 (`settlement_truth_dataset.py:280,335-336`).
2. Round-2 table, A9 "Pinned `trigger_rows_sha256`" as the guarantee for E: unsupported. Nothing in the planned code reads or verifies it (B-2).
3. Round-2 table, B5 "10:00Z cadence checked against the actual timer schedule": incomplete; ingest-frequent is omitted (S-4).
4. C5, "Any other `2026-09-xx`/`2026-10-xx` literal … is a defect": over-broad, as N-5 shows. It is not a mechanism error.

**Next action for r3:** resolve B-1 (choose the producer and state the independence verdict) and B-2 (fence path plus pre-claim recomputation of E), fold both into the Doc A/Doc B template, and add S-1's pre-declared bench exception. The rest can be handled in the same revision without another full round.