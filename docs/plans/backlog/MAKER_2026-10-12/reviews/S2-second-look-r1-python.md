## MAKER-S2 second-look plan r1: Python domain review

**Verdict: REQUEST_CHANGES**

The plan's skeleton is sound. The ledger needs no change, the v1 constants do refuse every block-2 date, and the tail annotation is unreachable from `--tail-only`. But one premise behind C3 is false, C5 misses a hidden block-1 literal, and W3 and W6 collide with existing tests. P-3 is also left open.

I read the code and tests directly. The codegraph calls returned stale "already sent" stubs, so I did not use them for the quotes below.

### Scores (1-10)

| Axis | Score |
|---|---|
| Correctness vs governing texts | 6 |
| Architecture / idiom fit | 7 |
| Test coverage (happy / failure / edge) | 6 |
| Risk mitigation | 6 |
| Scope minimality | 6 |
| Feasibility | 6 |

**Overall confidence: MEDIUM.** The plan states about 0.75. I would put it nearer 0.6 until B1-B3 are fixed.

### Verify-first results

1. **Ledger: confirmed.**
   - `maker_stage0_ledger.py:203-205`: `mine = [e ... e["amendment_sha"] == amendment_sha]`, and `if not mine: return None`.
   - `:238-253` then appends. A new Doc B sha is therefore a fresh claim with no code change.
   - **There is no date-overlap guard.** The entry (`:243-251`) carries no dates at all.
   - Any byte-different FINAL copy of the v1 amendment claims a second scoring pass on block 1 (see P-3).
2. **Frozen constants: confirmed.**
   - `frozen.py:36` has `LAST_ALLOWED_DAY = 2026-10-13`. `_check_dates:126-127` refuses `day > LAST_ALLOWED_DAY`.
   - `:149-150` has `first not in FIRST_REPLAYABLE_CHOICES`, which are (09-18, 09-19) at `:37`.
   - `rule_dates:71` returns `()` for any first day of 10-14 or later. All block-2 dates are refused today.
3. **Driver ordering: confirmed, but see B1.**
   - `claim_verdict_run` (`driver.py:~176-185`) runs first, then `mkdir`, then `_execute`, then `_wp0`.
   - The equality check at `driver.py:225-229` raises `InputRefused`, which `:191-196` turns into `RunVoided`.
   - So a failing check does void the one claimed run.
4. **Census firewall: confirmed.**
   - One range (`maker_tape_census.py:71-73`) and one sha (`:76-78`).
   - `require_firewall_clearance:178-200` is the only clearance path. Its sole census caller is `scripts/analysis/maker_tape_census.py:251` via `declaration_sha256`.
   - A second consumer exists that the plan does not mention: `trade_quantity_unit_crosscheck.py:121-128`. It binds one sha and is untouched by C1, but it belongs in the C1 blast radius.
5. **Tail wiring: confirmed.**
   - `run_tail` (`report.py:181-212`) writes only `tail_reliability.csv` and the manifest.
   - `tail_table` is called only at `tables.py:300`, inside `render_tables`.
   - `render_verdict` (`tables.py:127-128`) is the only emitter.
   - The verdict run's tail rows are empty by construction. `stats.py:~363` returns `miscalibrated=False` for `not tail`.
6. **Hidden literals: found one the plan misses.**
   - `render.py:86` (`_D5`) is as the plan says.
   - **`render.py:41-47` `HOLDOUT_LINE` is a second block-1 literal.** It reads "replay days 2026-09-18..2026-09-30 ... 2026-10-02..2026-10-13 statistics are disclosed contamination". This is false for block 2.
   - `driver.py:113` `TAIL_RANGE` is intended. `frozen.py:36-37` is covered by C2.
   - Other grep hits are docstrings or comments (`runio.py:96`, `inputs.py:334`, `frozen.py:4-10`, `:70`).
7. **Shrink arithmetic: the number is right, the derivation text is wrong.**
   - `station_days.csv` has 96 rows. The census_reason column gives COVERED 88, LONG_HOLE 4 (09-28) and LOW_COVERAGE 4 (09-29).
   - `wp0_agreement.json` has `listing_abstain` true on 44 coverage rows. Of those, 40 are COVERED and 4 are the LOW_COVERAGE rows.
   - COVERED and early-listed is 88 − 40 = **48**. Of those, 44 are `bid_bearing` and 4 are not, so n_sd = 44. This matches the evidence (`STAGE0_REPLAY...md:76`).
   - The plan's "96 covered − 40 − 8" is wrong. The "96" is the S1 census `N_cov` (`:35`), which includes 8 COVERED station-days outside the 24-date frozen set. The CSV's 88 COVERED rows are the right base.
   - The 48 is correct by coincidence.

### BLOCKING issues

**B1. C3's premise is false, and its `probed <= block_first_day` check can still void the run (R5 mitigation is not sound).**
- The plan says (§3 C3, `:130`) that prints exist since 09-17, so the result is at most 10-14.
- `first_print_instant` (`maker_stage0_probe.py:294-319`) is licensed to `days x stations`. Only block-2 rungs count, through `sc.licensed_rung_filter(day_set, station_set)`.
- The first licensed print is therefore that of the earliest block-2 rung. For a 10-14 rung that is on 10-13 or earlier.
- `first_replayable_day` (`probe_core.py:210-215`) returns +1 day if the print is at or before 16:50Z, else +2.
- A first licensed print on 10-13 after 16:50Z gives 10-15, which is greater than `block_first_day` 10-14. The plan's own `<=` rule would then refuse and void a legitimate tape.
- The check exists in v1 to prove the feed started before the block. In v2 the recorder has run continuously since 09-17, so the proof is vacuous.
- **Fix:**
  - In v2, make the first-replayable comparison report-only. Record `probed.first_replayable_day` in `wp0_agreement.json`, which already holds it, but do not raise.
  - Rely on the existing coverage and `listing_abstain` logic.
  - Tests: `test_v2_records_but_never_refuses_on_first_replayable_day` and `test_v1_still_requires_equality`.
  - If a hard check is wanted, derive it from a scan not limited to licensed days. That costs a new read and a new licence, so it is not recommended.

**B2. C5 and the sweep miss `HOLDOUT_LINE` (`render.py:41-47`).**
- The sweep exempts "hits outside C2/C5", and `render.py` is C5's file. Hits at `:42` and `:86` would be waved through as "C5 scope" while C5 names only `:86`.
- `HOLDOUT_LINE` is pinned by `test_maker_stage0_driver.py:258-260`. It asserts `render.HOLDOUT_LINE in text` and the phrases "clause 3", "descriptive", "open_holdout" and "2026-10-01".
- For block 2 the line would claim replay days 09-18..09-30 were read. It would misstate the AUT-4 contamination range (`2026-10-02..2026-10-13`), which is exactly the disclosure Doc A §6 promises to extend (L-4).
- **Fix:**
  - Name `HOLDOUT_LINE` explicitly in C5.
  - Keep the v1 constant byte-identical and add a v2 builder that takes the block's first and last day.
  - The v1 test must stay green. Add `test_holdout_line_reflects_the_block`.
  - Replace the sweep exemption with an explicit allowlist of expected hits (`frozen.py:36-37`, `driver.py:113`, `render.py` v1 constants).

**B3. W3 and W6 edit or break existing tests the plan treats as untouched.**
- **W3** says "delete those test lines" (`test_maker_stage0_fill.py:418-420`). They sit inside `test_delta_is_per_instance_day_max_over_instances_and_over_10min_aborts_before_scoring_s7`.
  - That is an S-7 screen test, and editing it breaks the plan's own acceptance line ("None touches an S-* screen test").
  - It also breaks the "existing tests byte-unchanged" rule.
  - The same test holds the `assert_delta_within_bound` check. Mutating its body is not a "remove an orphan's own test" case.
  - **Fix:** drop W3 entirely. It is optional and pays nothing toward the second look. If wanted later, keep the old test and add a new one.
- **W6** adds `tail_summary.json` to `--tail-only` output.
  - `test_maker_stage0_driver.py:579` asserts `names == {"tail_reliability.csv", "run_manifest.json"}`. That is exact-set equality, so it breaks.
  - It needs an L-12 one-row widening, which the plan does not mention (it flags L-12 for W4 only).
  - W6's wiring also contradicts §5's licensed recompute. Doc B item 5 recomputes from the committed sidecar "no new NBP read". `run_tail` reads NBP through `PNoStore` and `load_tail_truth` (`report.py:189-208`).
  - **Fix:** implement W6 as a pure function over `read_tail_csv` plus `tail_table` (`rows.py:225`, `stats.py:355`). It writes nothing under `--tail-only`, or it is a separate tiny CLI. Add the widening row explicitly if a file is written. Keep `test_tail_annotation_never_changes_the_label`.

**B4. C2 is under-specified for the consumers of `FrozenDateSet.first_replayable_day`.**
- The v2 field list (`block_first_day`, `trigger_day`, ...) has no `first_replayable_day`.
- The dataclass still requires it (`frozen.py:62`). It is consumed at `driver.py:225-228` and in `rule_dates` and `_check_dates` (`frozen.py:69,148-150`).
- `verify_set_matches_rule` (`:193-216`) also hard-codes `LAST_ALLOWED_DAY` in `:202-204`.
- **Fix:**
  - State what the v2 object stores in that field. The simplest is `block_first_day`, with a `block` discriminator.
  - Spell out the v2 branch in `verify_set_matches_rule` (cap at `SECOND_LOOK_MAX_DAY`, and `min(trigger_day, last_final_day, MAX)`).
  - Add a test that the v1 `FrozenDateSet` construction call sites still compile and pass byte-for-byte.
- Parser mechanics are fine. `_OPEN_FENCE` is a prefix of the V2 fence, so a V2-only Doc B is refused by `parse_frozen_block`'s count. `_BLOCK_RE` also fails to match it. Both-fence refusal is correct but needs the test the plan names.

**B5. P-3 / R8 is left open, and the v1 gap is pre-existing and real.**
- Today any byte-different FINAL copy of the v1 amendment claims another verdict pass on block 1 (`ledger.py:203-205`).
- That would be a hidden re-score of set 1, forbidden by amendment `:71`.
- See P-3 below. The fix is small and belongs before CODE_SHA freeze.

### Non-blocking suggestions

- **T=34 is dimensionally loose.**
  - 0.917 is a station-day ratio (44/48), but T is applied to the concave `n_eff` measure.
  - In set 1, n_eff for 48 sd over 12 dates is about 19.2 against 18.73 observed, a ratio of about 0.976.
  - 34 is therefore conservative by roughly 2 dates, not "30/0.917". Say so, or recompute the margin on `n_eff`. It is fine to keep 34 as long as it is pinned before any read.
- **FINAL lag can shrink the block after E.**
  - A day at E with no FINAL is dropped at freeze (amendment `:20`) and could push n_eff below T, giving a second WAIT.
  - Add "`last_final_day >= E`" as a hard precondition of Doc B FINAL. R10 mentions it, but make it a STOP.
- **Realised-only forfeiture assumes no missed daily checks.**
  - If a check is missed, the next one reads past E.
  - Ledger the realised range as `max(checked day) - 2`, not `E`, as Doc A §5 words it.
- **C1 size and layout.**
  - `src/breezy/analysis/maker_tape_census.py` is already 764 lines, so it is over the 400-line target (the hard limit is 800).
  - C1 adds a registry and a new test class; `tests/unit/test_maker_tape_census.py` is already 997 lines.
  - Put the registry in a small new module, for example `maker_search_declarations.py`, and keep `SEARCH_DECLARED` and `SEARCH_DECLARATION_SHA256` as re-exported aliases.
  - Existing tests at `:112-116` and `:119-126` stay byte-unchanged and green. `test_post_freeze_day_outside_declared_range_refused` uses 10-14 with the first sha (`:123`). That is refused under the registry because row 1's sha differs, so no L-12 widening is needed. **This closes the plan's unknown (a).**
  - `test_trade_quantity_unit.py:522` uses a fake and is unaffected.
- **C4 "never prints C".** The census run it feeds already logs `C`, `n_prints` and STOP lines (`census summary` at `maker_tape_census.py:~406-444`, evidence `:35`). The counts-only restriction is cosmetic unless the daily census is wrapped. Say what the run shows and accept it as outcome-blind.
- **Import contracts.**
  - `[tool.importlinter] root_packages = ["breezy", "nautilus_trader"]` (`pyproject.toml:71`). `scripts` is not in the graph.
  - `lint-imports` will not check the `scripts/analysis` -> `breezy.analysis` direction.
  - The real exposure is the other way round: `src` must not import from `scripts`. C1 respects that.
  - The "N kept, 0 broken" line is still required. Expect it to be unaffected by C2-C5.
- **Size checks.**
  - `probe.py` is 398 lines, confirmed. W2(a)'s split is needed before any other edit to that file.
  - `frozen.py` is 216, so about 330 after C2, which is fine. `driver.py` is 288, `render.py` 287 and `report.py` 212, all fine. A C4 of under 150 lines is fine.
  - No cited function passes 50 lines. `verify_set_matches_rule` is 24.
- **W4 (sidecar).**
  - `_from_csv` (`rows.py:199-206`) treats every dataclass field as a required column, so the plan's separate-file design is right. A new `station_days.csv` column would break re-reading the set-1 sidecar.
  - W4 also touches the `SIDECARS` exact set used by `test_maker_stage0_driver.py:140-150`. It is a one-row L-12 widening, as the plan says.
- **`asdict` / NO-SEND.** No `dataclasses.asdict` appears in `scripts/analysis/maker_stage0_*.py`. C1-C5 touch no firewall pin and no `BacktestOrderGuard`.
- **W5 (RSS double-count).** Leave it alone, as the plan does.
- **Clock rule.** The 10:00Z check with `RuntimeMaxSec` 3600 ends at 11:00Z, which is clear of 15:10-16:10Z and 02:05Z.

### Answers to the planner's questions

**P-1: disjoint blocks, not pooling. Agree.**
- Amendment `:71` forbids "a second verdict scoring pass on this set". A pooled V0 re-scores set 1.
- Amendment `:77` requires "a new dated declaration with its own frozen set".
- S3 r3 `:149` governs S3's UNDERDETERMINED trigger, not S2's V0.
- L-56 (`LESSONS.md:310`) forbids counting seen outcomes toward n.
- The spec is silent, so the conservative reading wins.
- Cost: about 22 dates instead of about 8. Accept it.
- One addition: Doc A should say explicitly that block-1 numbers may be cited descriptively but never enter any n, rate or CI.

**P-2: realised-only forfeiture.**
- Prefer realised, with the ceiling still pinned.
- A "read" is defined by `admit_print` (`maker_tape_census.py:203`), and the firewall clears by range plus sha.
- The 10-12 precedent forfeits the whole declared range because that census ran over the whole range at once.
- Block 2 reads incrementally, so unread days after E are genuinely unspent. RA-13 B-3 counts reads, not declarations.
- Hold realised accounting to two conditions:
  - The ledger line is written by the same tool that issues the census run, using `max(checked day) - 2`.
  - Row 1's `last_day` stays at 11-15 so a later read cannot silently extend it.
- If the peers want one number for EDGE-4 date arithmetic, use the 132 station-day ceiling as the upper bound and report realised alongside.

**P-3: yes, close the v1 gap, but not in the ledger schema.**
- Changing the ledger entry shape touches a safety control and `_read_entries` is strict. L-12 argues against relaxing it, and it is not necessary.
- Instead pin the v1 amendment sha in `frozen.py` as a constant. `load_amendment` (`frozen.py:163-180`) already takes `expected_sha`.
  - A v1 block is accepted only if `expected_sha == AMENDMENT_V1_SHA`.
  - A v2 block is accepted only for the Doc B sha pinned in code (the C1 pattern).
- A byte-different v1 copy is then refused before the claim.
- Tests: `test_v1_block_refused_for_any_other_sha` and `test_v2_block_refused_for_the_v1_sha`.
- This adds one small constant and two tests. It is an extra unit between C2 and C3 (call it C2b).

### Claims in the plan found to be FALSE or wrong

1. **§3 C3 `:130`**: "prints already exist since 09-17, so the result is at most 10-14". The first-print scan is limited to licensed block days (`probe.py:294-319`), so this need not hold. It can return 10-15 (B1).
2. **§1 `:48`**: "96 covered − 40 `listing_abstained` − 8 non-COVERED". The 96 is the census `N_cov`. The frozen-set COVERED count is 88 (`station_days.csv`), and 88 − 40 = 48. The final 48 and 44 are right.
3. **§3 "Pre-merge sweep" `:151`**: misses `render.py:42,45` (`HOLDOUT_LINE`), and exempts the file it sits in.
4. **§4 W3 `:170`**: "removes an orphan's own test, not a safety test". Those lines live in an S-7 screen test (`test_maker_stage0_fill.py:~408`).
5. **§5 W6 / Doc B item 5**: the recompute "from the committed sidecar, no new NBP read" cannot be done by `run_tail`, which reads NBP. The wiring must be a CSV-driven function (B3).
6. **§2 `:99` S-1 claim**: "n_eff_ub ... ≥ n_eff_proxy ≥ 34, so S-1 cannot fire". This is true only if the proxy and census predicates agree on COVERED. Keep the S-1 STOP in the entry criteria and do not rely on it.

### Required change list

1. C3: make the v2 first-replayable check report-only (B1).
2. C5: add `HOLDOUT_LINE`, replace the sweep exemption with an allowlist (B2).
3. Drop W3. Redo W6 as a CSV-driven function, with an L-12 row if it writes a file (B3).
4. C2: specify the v2 `first_replayable_day` mapping and the `verify_set_matches_rule` branch (B4).
5. Add C2b: a pinned v1 amendment sha (B5).
6. Fix the §1 arithmetic text and the `n_eff` versus n_sd wording (non-blocking).

Files read:
- `/home/jon/breezy/scripts/analysis/maker_stage0_frozen.py`
- `/home/jon/breezy/scripts/analysis/maker_stage0_ledger.py`
- `/home/jon/breezy/scripts/analysis/maker_stage0_driver.py`
- `/home/jon/breezy/scripts/analysis/maker_stage0_probe.py`
- `/home/jon/breezy/scripts/analysis/maker_stage0_probe_core.py`
- `/home/jon/breezy/scripts/analysis/maker_stage0_report.py`
- `/home/jon/breezy/scripts/analysis/maker_stage0_tables.py`
- `/home/jon/breezy/scripts/analysis/maker_stage0_stats.py`
- `/home/jon/breezy/scripts/analysis/maker_stage0_render.py`
- `/home/jon/breezy/scripts/analysis/maker_stage0_rows.py`
- `/home/jon/breezy/src/breezy/analysis/maker_tape_census.py`
- `/home/jon/breezy/tests/unit/test_maker_tape_census.py`
- `/home/jon/breezy/tests/unit/test_maker_stage0_driver.py`
- `/home/jon/breezy/tests/unit/test_maker_stage0_fill.py`
- `/home/jon/breezy/docs/evidence/maker/stage0_2026-10-16/station_days.csv`
- `/home/jon/breezy/docs/evidence/maker/stage0_2026-10-16/wp0_agreement.json`