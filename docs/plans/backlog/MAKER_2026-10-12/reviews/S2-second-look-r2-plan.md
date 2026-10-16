# MAKER-S2 second look after UNDERPOWERED-WAIT: implementation plan, revision 2

Every mechanism claim below was re-checked against the code in this round and is quoted as file:line. Paths are relative to /home/jon/breezy unless absolute.

## Acceptance criteria

The plan is complete when all of the following hold:

1. **The block rule is outcome-blind and written first.** The start day, the counted quantity, the threshold, the cap and the definition of the end day E are FINAL in Doc A before any block-2 tape byte reaches `admit_print`.
   - E is fixed by pinned, counts-only trigger rows (A9).
   - No step before the final Stage A run shows a print count, C, an S-1/S-5 line or KILL-LIKELY (A4).
2. **Block 1 is never re-scored, and no output pools the two blocks.**
   - Block 2 contains no date ≤ 2026-10-13.
   - 2026-10-13 is an orphan day: it was declared under SEARCH 1 (`RULING_MAKER-S1_SEARCH_declaration_2026-10-12.md:28`), is in neither block, and is never recovered.
3. **Exactly one verdict claim per block is a code guarantee, not only a process rule (A7).**
   - A v1 block is accepted at claim time only with sha `cf9a4dad…`.
   - A second v2 claim for the same `block_first_day` is refused unless a dated addendum names a voided run.
4. **No known post-claim void remains.** The first-replayable equality check (A1) and the vacuous truth cross-check (A6) are moved before the claim or made report-only.
5. **Every code unit is a small TDD unit with named tests.** None touches an S-* screen test, the NO-SEND firewall, `BacktestOrderGuard`, `AS_MARGIN`, or any existing firewall assertion.
   - Freeze scope is C1–C6, C2b and W1, plus C7 only if W1's measurement triggers it.
   - All of it is merged with the full gate green (`scripts/ci/run_tests_no_egress.sh`) and `lint-imports` printing "N kept, 0 broken" before Doc B goes FINAL.
   - Nothing merges between Doc B FINAL and the evidence commit.
6. **Forfeiture is recorded as it accrues.** The census logs every Doc A–sha invocation; days after E are never read; the registry is narrowed to [S, E] after the evidence commit (A5).
7. **The tail result is disclosure only.** It is never a label, a refit, a margin change or an FQ-v2 trigger.

**Binding constraints:**
- Nautilus stays immutable; `allow_short=False`.
- Never weaken a safety, settlement, contract or S-* test. Exact sets are widened by one reviewed row (L-12).
- FINAL rulings, the PREREG and addenda are never edited; changes are new dated documents.
- Result-driven re-runs are forbidden, and GO is never an outcome.
- Nothing here touches live enablement. The operator decides only the two budget caps, and neither is involved.
- The recorder tape is the only new data source.
- Clock: no unit may start inside or run into 15:10–16:10Z or 02:05Z (`S2_RUN_PROCEDURE_2026-10-14.md:29`). Verified timers:
  - 02:05Z is `breezy-nbp-learning-nightly.timer:11`.
  - Tape rotation is 09:00Z (`breezy-quote-tape-rotate.timer:25`), not 02:05Z as the r1 brief said. Both windows are avoided.
  - Other fixed jobs: truth fetch 11:40Z (`breezy-truth-fetch.timer:13`), truth dataset 12:40Z (`breezy-truth-dataset.timer:15`), ingest at 00/06/12/18:15Z (`breezy-quote-tape-ingest.timer:19`), exit-window study 15:20Z, replay-daily 15:50Z.

## 1. Trigger and block definition

**Governing texts (quoted):**
- Amendment `RULING_MAKER-S1_SEARCH_declaration_amendment_2026-10-13.md`:
  - :71 — "A second verdict scoring pass on this set is forbidden."
  - :76 — "A result-driven re-run is forbidden."
  - :77 — "More days (S3 r3 :149 second look) need a new dated declaration with its own frozen set."
- `S3_loss_floor_reachability_plan_r3.md:149` — "once the census adds ≥ `n0` more climate dates, S2 re-emits its numbers". This sits under S3's own UNDERDETERMINED verdict (:148).
- Spec `SPEC_pm_us_no_ladder_maker_2026-10-12.md:222-224` — "effective n ≥ 30 … below it Stage 0 emits UNDERPOWERED-WAIT". The spec says nothing about pooling.
- L-56 (`LESSONS.md:310`) — "never count the motivating fills toward n".

**Pooling ruling (B10; all three reviewers agree):**
- Block 2 is disjoint from block 1 and gets its own standalone V0.
- The union would re-score block 1, which :71 forbids.
- S3 :149 belongs to a different state, and it predates the later, more specific :77.
- Doc A §3 states that block-1 numbers may be cited descriptively but never enter any n, rate or confidence interval of block 2. No pooled table is produced, even report-only.

**Block rule (pinned in Doc A before any read):**
- **Start day:** S = 2026-10-14. This is the conservative reading: it is the first day after the amendment ceiling ("a date > 2026-10-13", :21), and 2026-10-13 stays orphaned (Doc A §1).
- **Stations:** LAX, MDW, MIA, SFO; never NYC. No sealed day falls in range.
- **Counted station-day:** census `reason == "COVERED"` and `maker_stage0_rule.listed_in_time(first_seen_ns, day)` is true.
  - `listed_in_time` is at `maker_stage0_rule.py:250-251`: "S must be listed by D-1 12:00Z, else abstain". The driver applies the same predicate (`maker_stage0_driver.py:208-210`).
  - `first_seen_ns` is a census row field (`src/breezy/analysis/maker_tape_census.py:448`).
- **Proxy:** `n_eff_proxy([S,d]) = Σ m_d/(1+(m_d−1)·0.5)`, computed with `n_eff_gov` (`maker_stage0_inputs.py:143-145`).
- **Threshold T = 34**, in n_eff units (A3). The block-1 shrink from proxy to V0 is derived as follows:
  - `station_days.csv` has 96 rows, of which 88 are COVERED. The other 8 are LONG_HOLE on 09-28 and LOW_COVERAGE on 09-29 (`stage0_2026-10-16/station_days.csv:42-49`).
  - `wp0_agreement.json` has `"listing_abstain": true` on 44 rows: 40 COVERED rows plus the 4 LOW_COVERAGE rows (grep count 44).
  - COVERED and listed early: 88 − 40 = 48 station-days, which is all 4 stations on each of 12 dates. That gives proxy n_eff = 12 × 1.6 = 19.20.
  - The realised `n_eff_gov` was 18.73 (44 bid-bearing station-days; LAX 10-03, SFO 10-03, SFO 10-04 and LAX 10-08 were not bid-bearing).
  - Shrink = 18.73 / 19.20 = 0.976, so the bare requirement is 30 / 0.976 ≈ 30.7.
  - **Coordinator ruling: T = 34.** The extra ≈ 3.3 n_eff (about 2 dates) is a deliberate conservative margin, pinned before any read. The shrink is a posting fact and involves no fill.
- **End day E:** the first day d ≥ S with `n_eff_proxy([S,d]) ≥ 34`, computed from the pinned incremental trigger rows (A9). It does not depend on which day the check runs.
- **Cap:** E_max = 2026-11-15 (33 dates). If the trigger never fires, E := E_max.
- **Frozen dates:** S through min(E, last FINAL day), where `last_final_day ≥ E` is a hard STOP precondition for Doc B going FINAL (B2).
- **Expected calendar:** at m_d = 4, 34 / 1.6 = 21.25, so 22 dates, giving E = 11-04. With block 1's hole rate (2 of 24 dates not COVERED), E ≈ 11-06. Twenty-two dates is ≥ n0 = 12.

## 2. Documents

### Doc A — `docs/evidence/RULING_MAKER-S2_second_look_SEARCH_declaration_<date>.md`

Doc A must be FINAL before C1 pins its sha; the census runs only after that. This follows the 10-12 pattern at :7-8.

Sections:
1. **Basis.**
   - Cites RA-13 B-3 (`RULING_RA-13_programme_kill_2026-09-27.md:90`), amendment :77, S3 :149 and spec :222-224.
   - States the 2026-10-13 orphan and the S = 10-14 conservative reading.
2. **Declaration.** Stations; days 10-14..11-15 as the ceiling. Covers the counts-only trigger census, the final Stage A over [S, E], and the reads licensed in Doc B. It never covers S5.
3. **Pooling ruling** (B10, verbatim as in §1).
4. **Trigger rule** (§1 verbatim), plus:
   - **S-1 and S-5 bind only on the final Stage A over [S, E].**
   - Every other census output is counts-only. Anything else a run prints is sealed (log mode 0400) and never read (A4-iii).
   - The S-1 STOP stays in the entry criteria. Because T exceeds 30 it is unlikely to fire, but it can.
5. **SEARCH cost (A5, B9):**
   - Realised accrual = 4 × (max day ever passed to a census run under the Doc A sha − S + 1). It is read from the census read-ledger (C1b) and written into the closing ledger line.
   - Ceiling 4 × 33 = 132.
   - EDGE-4 date effect, computed both at the ceiling (upper bound, about 26 days at the nominal 5 station-days/day of 10-12 :61-64) and at the realised value.
   - Any read of a day > E is a violation and is reported on the ledger line.
   - After the evidence commit, C1's row is narrowed to [S, E]. If peers reject the narrowing, the fallback is full-scope forfeiture of 132 at Doc A FINAL.
   - RA-13 backstop 2027-01-25 is firm (`RULING_RA-13…:97`).
6. **NBP holdout / AUT-4:**
   - Days ≥ 2026-10-02 are forward data (holdout ruling :9-11, as cited at 10-12 :38-39).
   - MAKER-S2 NBP-vs-outcome statistics on [10-14, E] are disclosed contamination for AUT-4 forward windows; this extends amendment :66 with the new range. Nothing calls `open_holdout`.
7. **S5:** `holdout_start_date` ≥ (max census-invoked day) + 2. This tightens `S5_shadow_run_and_gates_plan_r3.md:218` ("≥ last Stage 0 climate day + 2").
8. **Outcome and disposition:**
   - Exploratory; GO is never an outcome (spec :224). Labels map to the S2 procedure's Step 8.
   - A second WAIT goes to a dated peer ruling; there is no automatic third block (L-3).
   - B3: passing V0 does not secure §6.9 power (`MIN_EXPECTED_LOSSES` = 10.0, `maker_stage0_stats.py:28`; run 1 needed 469 pooled fills, evidence :87). A NOT-KILLED-UNSCREENED result is therefore likely and is admissible: S3's allowlist accepts it, and S5 G9 re-screens (`S5_…_r3.md:27`, "UNSCREENED suffices").
   - An outcome-blind power check is not added to the trigger because it was never pre-registered; it is disclosed only.
9. **Trade unit reused.** `trade_quantity_unit.json` (sha `6459e9f6…`, evidence :403) is reused as is. Stage B re-reads nothing: its licensed fills are the 28 pinned rows dated ≤ 10-06 (10-12 :79-117).
10. **Tail disclosure** (§5).
11. **Ledger lines:** one line in `RA-13-FW_firewall_audit_2026-09-27.md`, and a final section in `RULING_H-ARCHIVE-RECAL-2026-09_horizon_2026-09-25.md` (pattern from 10-12 :130-134). Precondition B6 must hold first (§6).
12. **Doc B template**, verbatim.

### Doc B — `docs/evidence/RULING_MAKER-S2_second_look_licence_<date>.md`

Committed as DRAFT alongside Doc A; goes FINAL once, mechanically, after E is fixed and the truth copy is pinned.

**§1 licensed reads (exhaustive):**
1. One verdict scoring pass over block days only: NBP 13Z/19Z D−1 and 01Z D, tape including Depth10 and `DepthTruncation`, the pinned truth CSV and the pinned cross-check (A6).
2. `--bench` 4 and 8 on block days.
3. Verify-first on 2026-06-30 (amendment :12) at the new CODE_SHA.
4. WP0 direction check and the SFO positive control on block days.
5. Report-only annotation via W6's pure function over the committed block-1 sidecar `tail_reliability.csv` (sha `6749a921…`). This makes no new NBP read and writes no file.

`--tail-only` is not licensed, and C3 refuses it for a v2 block.

**Fence `FROZEN_DATE_SET_V2`:** `stations`, `block_first_day`, `trigger_day`, `trigger_rows_sha256`, `truth_csv_path`, `truth_csv_sha256`, `cross_check_path`, `cross_check_sha256`, `last_final_day`, `dates`.

**§3 re-run rule:** copies amendment :71-77, with the addendum named `RULING_MAKER-S2_second_look_addendum_<date>.md`.

**Ledger:** Doc B's sha is a fresh claim. `_refusal` keys on `e["amendment_sha"] == amendment_sha` and returns `None` with no match (`maker_stage0_ledger.py:200-205`); the sha comes from the CLI (`maker_stage0_replay.py:95-97`). C2b and the ledger widening (§3) make the one-claim rule hold even for a byte-different copy of Doc B.

**What S1 re-runs:**
- Counts-only incremental trigger runs (C4).
- The final Stage A over [S, E] with `--search-declaration <Doc A>` (`scripts/analysis/maker_tape_census.py:473,485-488`); its STOP lines bind.
- Stage B and WP3 are not re-run.

## 3. Code changes (TDD; keep RED→GREEN; focused gate → `lint-imports` → full gate after every merge, L-43)

### C1 — census firewall registry

New module `src/breezy/analysis/maker_search_declarations.py` (B1). The census module is 764 lines, so the registry does not go there.

- Rows are `(stations, first, last, sha)`.
  - Row 0 = today's `SEARCH_DECLARED` and sha (`maker_tape_census.py:71-78`).
  - Row 1 = (MAKER_STATIONS, 10-14, 11-15, Doc A sha).
- `require_firewall_clearance` (:178-200) clears a post-freeze day only if the row containing that day has a matching sha.
- `SEARCH_DECLARED` and `SEARCH_DECLARATION_SHA256` are re-exported from the census module.
- Existing tests at `tests/unit/test_maker_tape_census.py:112-116` and `:119-126` stay byte-unchanged and green. The latter clears 10-14 against the first sha, which the registry still refuses, so r1's unknown (a) is closed and no widening is needed.
- Blast radius, file untouched: `trade_quantity_unit_crosscheck.py:121-128` binds one sha through `require_firewall_clearance`.
- New tests:
  - `test_second_look_day_cleared_only_with_second_declaration_sha`
  - `test_first_block_day_refused_with_second_declaration_sha`
  - `test_day_after_second_look_ceiling_refused`
  - `test_registry_rows_are_disjoint_and_pinned`
  - `test_pinned_second_declaration_sha_matches_committed_file`

### C1b — census read-ledger and range guard (A5)

File: `scripts/analysis/maker_tape_census.py`, in `main` (:481-520).

- Refuse with `REFUSED` when `--to > today_utc − 2`, using an injectable clock.
- Before reading, append `{declaration_sha, from, to, ts}` to `~/.local/share/breezy/derived/maker_stage0/search_read_ledger.jsonl` when the sha is in registry row ≥ 1.
- Tests:
  - `test_census_refuses_range_end_after_check_date_minus_two`
  - `test_census_records_every_second_look_invocation_before_reading`

### C2 — frozen block v2

File: `scripts/analysis/maker_stage0_frozen.py`. Today `LAST_ALLOWED_DAY` and `FIRST_REPLAYABLE_CHOICES` (:36-37) refuse every block-2 date (`_check_dates`, :126-127).

- **Fence matching:** `_OPEN_FENCE` (:47) is a prefix of the v2 fence, so both parsers switch to exact, anchored MULTILINE fence regexes. A document carrying both fences is refused.
- **Dataclass:** `FrozenDateSet` gains `block: int = 1`, `trigger_day: date | None = None`, `trigger_rows_sha256: str | None = None`. The defaults keep every v1 construction site unchanged. For v2, `first_replayable_day = block_first_day` and `block = 2`.
- **v2 rule:** `rule_dates_v2 = block_first_day..min(trigger_day, last_final_day, SECOND_LOOK_MAX_DAY)`.
- **v2 refusals:** any date ≤ 10-13; `block_first_day ≠ 10-14`; `trigger_day > 11-15`; `last_final_day < trigger_day` (B2); NYC; an unfilled `<FILL`; a DRAFT status.
- `verify_set_matches_rule` (:193-216) dispatches on `block`; the v1 branch is byte-identical.
- Tests:
  - `test_v2_block_parses_and_matches_rule`
  - `test_v2_refuses_any_block1_date`
  - `test_v2_refuses_last_final_before_trigger_day`
  - `test_v2_refuses_trigger_day_after_cap`
  - `test_v1_parser_refuses_v2_only_doc`
  - `test_v2_parser_refuses_v1_doc`
  - `test_both_fences_refused`
  - `test_v1_parse_of_committed_amendment_is_unchanged` (real file, sha `cf9a4dad…`)
  - All existing tests (`tests/unit/test_maker_stage0_frozen.py:97-235`) stay untouched.

### C2b — one-shot guarantee (A7)

- **(i) Pin the v1 sha.** Add `V1_AMENDMENT_SHA256 = "cf9a4dad…"` in `frozen.py`. In verdict mode (`driver._run_verdict`, before the claim at :177), a v1 block with any other sha is refused, and a v2 block carrying that sha is refused.
  - The verdict-world fixture `tests/fixtures/maker_stage0/replay_world.py` patches the constant to its own fixture sha. This is a fixture-only change and no assertion changes.
  - Tests: `test_v1_block_refused_for_any_other_sha`, `test_v2_block_refused_for_the_v1_sha`.
- **(ii) Key the ledger by block.**
  - `_KEYS_BY_KIND[KIND_START]` (`ledger.py:66-69`) becomes two exact accepted key sets: the current six, and the six plus `block_first_day`. This is an L-12 one-row widening.
  - `_read_entries` exact-set check (:149) is otherwise unchanged.
  - `claim_verdict_run` (:224-253) gains `block_first_day: str | None = None`.
  - `_refusal` (:200-211) counts as "mine" every start entry with the same `amendment_sha` or the same `block_first_day`. The addendum path is unchanged.
  - Tests: `test_second_v2_licence_same_block_refused_without_addendum`, `test_v2_start_entry_records_block_first_day`, `test_legacy_six_key_entries_still_read`.

### C3 — first-replayable check for v2 is report-only (A1)

Correct mechanism:
- `first_print_instant` scans only licensed day × station rungs (`maker_stage0_probe.py:300-311`, `station_day_key`).
- For block 2 it returns the first print on a 10-14 rung, so `first_replayable_day` (`probe_core.py:210-215`) can be 10-15.
- The driver checks for equality after the claim (`driver.py:225-229`); a mismatch raises, and `_run_verdict` then voids the run (:189-196).

Change:
- For v2, never raise. The value is already recorded in `wp0_agreement.json` through `ProbeReport.first_replayable_day` (`probe.py:381-383`). v1 keeps the equality check.
- Coverage is enforced elsewhere, per station-day: census COVERED feeds `in_denominator` (`maker_stage0_rows.py:113-116`), and `verify_set_matches_rule` requires census rows for every set date (`frozen.py:213-216`).
- Also refuse `--tail-only` for a v2 block (unlicensed).
- Tests:
  - `test_v2_records_but_never_refuses_on_first_replayable_day` (fixture with the first print after D-1 16:50Z)
  - `test_v1_still_requires_equality`
  - `test_tail_only_refused_for_a_v2_block`

### C4 — counts-only incremental trigger tool (A4, A9)

New file `scripts/analysis/maker_stage0_trigger.py`, under 150 lines (B8).

- `check` runs the census in counts-only mode (new `--counts-only` flag in census `main`) for [d, d], for each not-yet-checked d ≤ c − 2.
- It appends only `{station, climate_day, reason, first_seen_ns}` to `trigger_rows.jsonl`. No `_report` (:519), no prints file, no C, exit code 0.
- Each day is checked once; a missed day is caught up in a later run and is still run once. The rows are the pinned datum.
- `close` computes E and `sha256(trigger_rows.jsonl)`, and writes the forfeiture line from the C1b ledger.
- If the final Stage A rows for a day ≤ E disagree (for example `instances_live_unread`/`instances_corrupt_unread` changing `reason`, `src/…/maker_tape_census.py:433-435`), the disagreement is disclosed and never moves E.
- Tests:
  - `test_counts_only_output_has_exactly_four_fields_and_no_summary`
  - `test_trigger_counts_only_covered_early_listed`
  - `test_trigger_day_is_first_crossing_not_check_day`
  - `test_each_day_checked_once_and_catch_up_is_incremental`
  - `test_close_hash_matches_rows_and_e_recomputes`
  - `test_listed_in_time_agrees_with_probe_listing_abstain`

### C5 — block-driven disclosures (A2)

File: `scripts/analysis/maker_stage0_render.py`.

- The v1 constants stay byte-identical: `HOLDOUT_LINE` (:41-47, pinned by `test_maker_stage0_driver.py:258-260`) and `_D5` (:84-88).
- New v2 builders take block-first and block-last day. They render: forward-data days S..E; no tail days read; the AUT-4 contamination text; "never calls open_holdout"; and the count of block days not yet past D+14 at run time.
- The render call sites receive `FrozenDateSet`; they are to be located with codegraph during implementation.
- Tests: `test_holdout_line_reflects_the_block`, `test_d5_disclosure_reflects_the_block_and_d14_status`.
- **Literal sweep allowlist** (expected hits only): `frozen.py:35-37` and docstrings :4-10 and :70; `driver.py:113` (`TAIL_RANGE`); `render.py:41-47` and :84-88 (v1 constants); `runio.py:96` and `inputs.py:334` (docstrings). Any other `2026-09-xx`/`2026-10-xx` literal in `scripts/analysis/maker_stage0_*.py` is a defect.

### C6 — pre-claim truth cross-check overlap (A6)

The problem, verified:
- `load_truth` raises `InputRefused("…vacuous")` on an empty overlap (`maker_stage0_inputs.py:357-360`).
- It is called after the simulation (`maker_stage0_report.py:117-122`), which is after the claim.
- The default cross-check is the stale `settlement_truth.parquet` (`maker_stage0_replay.py:35-37`; "(≤ 09-28)", `S2_stage0_replay_plan_r3.md:122,216`).

Change:
- Factor the overlap computation into a helper shared with `load_truth`. Its guard is unchanged and never relaxed.
- In verdict-mode `preflight` (`maker_stage0_preflight.py:153-168`), check overlap on the frozen (station, date) keys. These equal the `sd_rows` keys, because `station_days.csv` carries every set station-day (96 rows in block 1).
- Test: `test_v2_cross_check_without_overlap_refused_before_claim`.
- **Cross-check source.** Re-run `scripts/analysis/settlement_truth_dataset.py`, which writes `settlement_truth.parquet` (:1166). It reads its archive cache "strictly read-only, and a cache miss is a refusal, not a fetch" (:13-14). A pinned copy covering [S, E] is produced before Doc B goes FINAL, and its sha goes in the fence.
  - That the cache covers November is unverified (U-3). If no source covers [S, E], C6 STOPs before the claim and the case goes to a dated peer ruling.
  - Independence caveat: if the truth CSV and the cross-check derive from the same AFOS revisions, the cross-check verifies parsing, not the source. This is disclosed.

### C7 — conditional must-land (A11): name-based instance pre-filter

- `_for_each_clean_instance` classifies and converts every instance (`probe.py:261-281`).
- The remedy skips an instance whose rung directory names contain no licensed station-day before `scan_instance_memoized`. The census already lists station-days from directory names (`CensusedDay` docstring :433-435). Skips are recorded in `skipped` with a reason.
- It requires the W2(a) split first, because `probe.py` is at 398/400 lines (B8).
- Tests: `test_unlicensed_instance_skipped_before_scan_and_recorded`, `test_licensed_output_identical_with_and_without_prefilter`.

### Not changed

- `assert_delta_within_bound` (`fill_events.py:227-234`).
- The S-5 abort (`modes.py:222-224`).
- `AS_MARGIN` (`stats.py:26`).
- All S-* screen tests and the NO-SEND firewall.
- B7: `lint-imports` covers `breezy`/`nautilus_trader` only (`pyproject.toml:71`). C1 keeps `src` free of imports from `scripts`, and "N kept, 0 broken" is still required.

## 4. WAIT-period engineering backlog (verdict-blind)

**Freeze scope:** C1, C1b, C2, C2b, C3, C4, C5, C6 and W1, plus C7 (with the W2(a) split) if W1 triggers it. Everything else lands after the evidence commit.

- **W1 (must) — preamble enters PROJ.**
  - Run 1 measured a preamble of ≈ 7,800 s and scoring of ≈ 7,400 s for 96 station-days (evidence :22, 02:07→04:17→≈06:20Z).
  - The procedure only adds 2×`T_FP` = 2,796 s (`S2_RUN_PROCEDURE…:166`).
  - Procedure delta:
    - `PREAMBLE_S = 7,800 × N_inst(now) / N_inst(run 1)`. N_inst(run 1) comes from the `instances` counts in the S1 census provenance (`scripts/analysis/maker_tape_census.py:407`).
    - `SCORE_S = 7,400 × n_station_days / 96`.
    - `PROJ = PREAMBLE_S + SCORE_S` (or the bench projection, whichever is larger).
    - The pre-progress stall alert is set at 1.5 × `PREAMBLE_S`.
  - **Decision measurement:** take N_inst on 10-21, project it linearly to E_max = 11-15 with 132 station-days, and decide by 10-24.
    - If PROJ > 0.8 × 21,600 = 17,280 s, C7 becomes must-land before the freeze.
    - Re-measure at Doc B FINAL. If PROJ > 21,600 s, STOP before the claim (procedure :169).
- **W2 (after the evidence commit, unless C7 triggers):**
  - (a) Pure split of `probe.py`, with mutation evidence (L-33).
  - (b) Bench records the preamble and first-print wall time.
- **W3: dropped (A8).** Its deleted lines would sit inside an S-7 screen test (`test_maker_stage0_fill.py:~408-420`).
- **W4 (after the evidence commit):** a `listing_abstain.csv` sidecar (not a new `station_days.csv` column; `rows.py:204-206` would refuse old files), with a one-row widening of the canonical sidecar set (L-12).
- **W5 (deferred):** the `peak + parent_rss` reading is the S-5 abort formula (`modes.py:196-197,222`). It is not changed.
- **W6 (optional, post-verdict):** a pure function `read_tail_csv` → `tail_table` (`rows.py:225`, `stats.py:355-366`) over the committed sidecar.
  - It writes nothing under `--tail-only`; the tail-only output set is pinned at `test_maker_stage0_driver.py:579`.
  - If it ever writes a file, that is an explicit L-12 widening.
  - `test_tail_annotation_never_changes_the_label` (`test_maker_stage0_verdict.py:794-801`) is kept.

## 5. Tail diagnostic routing

**Why no annotation fired — verified:**
- `tail_table` sets `miscalibrated = p_value < ALPHA` (`maker_stage0_stats.py:355-366`).
- Its only emitter is `render_verdict` (`maker_stage0_tables.py:127-128`).
- The verdict run's tail rows are empty by construction (`S2_RUN_PROCEDURE…:271`).
- `run_tail` writes only the CSV and the manifest and never calls `tail_table` (`maker_stage0_report.py:181-212`).

So the annotation licensed at amendment :14 and procedure :239 was unreachable. This is a report-path defect; the label is unaffected. W6 is the fix.

**Where the result goes:**
- Already in `STAGE0_REPLAY_2026-10-16.md:100-111`.
- Doc A §10.
- S5 PREREG `holdout_freeze_disclosure` (`S5_…_r3.md:226`), as a descriptive model-risk note (B4):
  - The observed 2.5× excess is larger than the 1.5 Test A margin (`stats.py:26`, spec :296), so block-2 Test A may FAIL → NO-GO (adverse selection).
  - That is the pre-registered path and is not softened; the margin stays frozen.
- AUT-4: a contamination note, because the tail days lie inside the NBP holdout read under clause 3 (amendment :64). The errata file location is unverified (U-5).
- Not routed to FQ-v2 triggers or to any NBP fit (amendment :58-60).

## 6. Calendar (UTC; earliest feasible; fixed by rule)

| Milestone | Earliest | Gate |
|---|---|---|
| B6 pre-check: no other consumer has read 10-14+ tape as a statistic (exit-window nightly `~/.local/share/breezy/derived/exit_window_study/2026-10-*_nightly/exit_window_study.json` rows/`missing_inputs`, method 10-12 :55-59; replay-daily; monitor/hold studies) | 10-17 | before Doc A FINAL |
| Doc A FINAL; Doc B DRAFT | 10-18 | peers converged |
| C1–C6 and C2b merged and gate-green; W1 delta committed | 10-21 | Doc A sha |
| N_inst measurement → C7 decision | 10-21 → 10-24 | W1 |
| Trigger `check` daily at 10:00Z: after the 09:00Z rotation, before the 11:40/12:40Z truth timers and the 12:15Z ingest; `RuntimeMaxSec` 1800; under the studies `flock`; one heavy job at a time (B5) | from 10-21 (days 10-14..c−2) | C4 |
| E | ≈ 11-04 to 11-06; cap 11-15 | rule |
| Truth copy pinned after the 12:40Z dataset run with `last_final_day ≥ E` (observed lag ≈ 2 days: the 10-14 copy ended at 10-12, amendment :28); cross-check copy; final Stage A over [S, E]; Doc B FINAL; CODE_SHA freeze | E + 2 (≈ 11-06 to 11-08) | B2, C6 |
| P2 backfill (avoid 16:30–17:10Z), verify-first, bench 4 and 8 | E + 2 to E + 3 | ends before 15:10Z |
| Verdict run after 02:05Z, before the 09:00Z rotation if possible, `RTMAX` ≤ 21,600 | E + 3 to E + 4 | W1 / C7 |
| Evidence commit; narrow C1 row 1 to [S, E]; PROGRESS row 2 | same day | A5 |
| S3 binding run (label NOT-KILLED or NOT-KILLED-UNSCREENED; also needs the S5 WP0a cap pin) | ≈ E + 5 | `RuntimeMaxSec` 18,700 (PROGRESS :64) |

Truth source: the live file `derived/fq-truth/truth_cli_finals.csv` (`deploy/systemd/README.md:1974`), copied read-only. The FINAL predicate is in the procedure at :72-74. On the cap path, the verdict lands around 11-19, and S5 can start at 11-17 or later, which is compatible with the S5 r3 :296 start of 11-23.

## 7. Risk register and LESSONS compliance

| # | Risk | Mitigation |
|---|---|---|
| R1 | Venue lists late again, so the trigger never fires | Cap at 11-15; a second WAIT goes to a peer ruling |
| R2 | Proxy overstates n_sd | T = 34 vs a bare 30.7; W4 audits after the run |
| R3 | Preamble growth → RTMAX kill → void | W1 decides C7 by 10-24; STOP before the claim |
| R4 | Memory: the 8-day bench projected 3.72 GB against a 4 GiB cap (evidence :47) | Bench re-run; MEMMAX rule unchanged |
| R5 | Post-claim voids (first-replayable, vacuous cross-check) | C3, C6 |
| R6 | Repeated looks at fill-type screens (L-34) | C4 counts-only; S-1/S-5 bind only on the final Stage A; other logs sealed |
| R7 | Registry or forfeiture leaking into S5 holdout days | C1b ledger and guard; S5 start ≥ max read day + 2; narrowing after the evidence commit |
| R8 | A copied v1 amendment or a second Doc B | C2b (i) and (ii) |
| R9 | Hidden block-1 literals | C5 sweep allowlist |
| R10 | Truth timer fails silently ("Verify a timer's first scheduled run") | B2 hard STOP |
| R11 | θ drift (`check_theta`, `preflight.py:156`) | Refused before the claim, at no cost |
| R12 | S-1/S-5 on the final Stage A over [S, E] | Pre-registered STOP; accepted |
| R13 | Cross-check not independent, or cache does not cover November | C6 STOP before the claim; disclosed |
| R14 | Another study has already read 10-14+ tape | B6 pre-check |

**LESSONS compliance:**
- L-1 "Validate the Nautilus null hypothesis BEFORE proposing to build": all changes are study code; Nautilus is untouched.
- L-3 "A plan whose end state is not the goal state is not a plan": every label, including a second WAIT, has a named next action.
- L-12 "Widen an exact-set barrier, never relax it": the C2b ledger keys and W4/W6.
- L-33 "A characterisation item has no RED; demand mutation evidence instead": the W2(a) split.
- L-34 "The trial's TRIGGER is pinned; a re-look is a second snapshot": C4/A9.
- L-38 "A stop rule whose counter cannot increment is a missing stop": C4 test that the counter increments.
- L-43 "…gate the integration branch after EVERY merge".
- L-53 "A cache cannot fix an input that never completes": W1/C7.
- L-56 "…never count the motivating fills toward n": no pooling.
- L-4 "A fix is a diff against one finding; a document is a set of claims": C5, W6.

## 8. Confidence self-assessment

Overall about 0.8, up from 0.75.

**Raised, because now verified in code:** C3's mechanism (`probe.py:300-311`); C6's mechanism (`inputs.py:357-360`, `report.py:117-122`); the ledger key set and `_refusal` (`ledger.py:66-69,149,200-211`); C1's existing tests (`test_maker_tape_census.py:112-126`); the block-1 literals (sweep above); the timer schedule; the shrink arithmetic (station_days.csv has 96 rows, wp0_agreement.json has 44 `listing_abstain: true`).

**Open unknowns:**
- U-1: How N_inst grows, which drives C7. Measured 10-21.
- U-2: The render call sites that must receive `FrozenDateSet`.
- U-3: Whether the `settlement_truth_dataset.py` archive cache covers [S, E] and whether it is independent of fq-truth. Verify with a dry run before Doc A FINAL.
- U-4: Whether the B6 pre-check finds an earlier reader of 10-14+ tape.
- U-5: Where the AUT-4 errata file lives.
- U-6: Peers' acceptance of the A5 narrowing (fallback: 132 forfeited up front).
- U-7: Whether `taker_fee_coefficient_as_of` and NBP collector coverage extend to 11-15.

## Round-2 resolutions

| Item | Resolution | Section |
|---|---|---|
| A1 | C3 made report-only for v2; correct premise and rationale; tests | §3 C3 |
| A2 | C5 builds `HOLDOUT_LINE` and D5 from the block; v1 constants byte-identical; explicit sweep allowlist | §3 C5 |
| A3 | Shrink restated in n_eff units (19.20 → 18.73, 0.976, 30.7); T = 34 as a deliberate margin; `wp0_agreement.json` cited; 10-13 orphan stated | §1; §2 Doc A §1 |
| A4 | Counts-only census, incremental single-day runs, S-1/S-5 bind only on final Stage A, S-1 kept in entry criteria, R12 reworded | §3 C4; §2 Doc A §4; §7 |
| A5 | C1b read-ledger and range guard; realised forfeiture; S5 start ≥ max read day + 2; narrowing to [S, E]; 132 fallback | §3 C1b; §2 Doc A §5, §7; §6 |
| A6 | C6 pre-claim overlap check; pinned cross-check source and producer; guard never relaxed | §3 C6; §2 Doc B |
| A7 | C2b: v1 sha pin, ledger `block_first_day` key and refusal; one claim per block is code-enforced | §3 C2b; §2 |
| A8 | W3 dropped; W6 is a pure post-verdict function; tail-only output set kept; freeze scope stated | §4 |
| A9 | Pinned `trigger_rows_sha256`; disagreements disclosed, never move E | §3 C4; §2 Doc B |
| A10 | Full C2 specification: exact fences, `block` field, v2 rule branch, cross-parser tests, v1 unchanged | §3 C2 |
| A11 | C7 name pre-filter as conditional must-land; measurement and date that decide it | §3 C7; §4 W1 |
| B1 | New registry module; tests :112-126 unchanged; `trade_quantity_unit_crosscheck.py:121-128` in blast radius | §3 C1 |
| B2 | `last_final_day ≥ E` is a hard STOP and a parser refusal | §1; §3 C2; §6 |
| B3 | §6.9 power caveat; NOT-KILLED-UNSCREENED likely; no power check added to the trigger | §2 Doc A §8 |
| B4 | 2.5× excess vs the 1.5 margin; Test A FAIL path kept; margin frozen | §5 |
| B5 | 10:00Z cadence checked against the actual timer schedule; studies lock | §6; constraints |
| B6 | RA-13-FW pre-check before Doc A FINAL | §6; §7 R14 |
| B7 | import-linter scope stated; "N kept, 0 broken" still required | §3 Not changed |
| B8 | Size limits: split before C7; C4 < 150 lines; C1 in a new module | §3; §4 |
| B9 | Realised forfeiture accrual; 132 ceiling as upper bound alongside realised | §2 Doc A §5 |
| B10 | Disjoint blocks, standalone V0, block-1 numbers descriptive only | §1; §2 Doc A §3 |