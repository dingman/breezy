# MAKER-S2 second look after UNDERPOWERED-WAIT: plan, revision 3

Every mechanism claim below was re-checked against the code this round and carries its file:line. Paths are relative to /home/jon/breezy. The round-2 resolutions still stand except where an item below replaces them.

**What changed from r2:**
- **Cross-check source.** The r2 producer could not have worked: the settlement dataset's archive window is hard-coded to end on 09-28. r3 adds a one-shot fetch into the same IEM CLI source and an opt-in archive window covering the block (unit C6b). This is the item reviewers should check first.
- **Pre-claim checks.** The trigger day E, the cross-check file, the trigger rows and the census output are now hashed or recomputed and checked before the ledger claim (C2).
- **Trigger tool.** It now stops at the first crossing, refuses later checks, and allows exactly one full census.
- **v1 sha pin** moved to the command-line layer, so every existing driver test stays unchanged.
- **W6 dropped.** The verdict run already embeds the tail table via `--tail-csv`.

## Acceptance criteria

1. **Outcome-blind block rule, fixed before any read.**
   - Doc A is FINAL before any block-2 byte reaches `admit_print`. It fixes the start day, the counted quantity, T = 34, the cap and the definition of E.
   - E is fixed by the trigger rows. Those rows are counts-only, committed and hashed. Before the claim the driver recomputes E and refuses on any mismatch (C2).
   - Before the final Stage A run, nothing shows C, a print count, an S-1/S-5 line or KILL-LIKELY (C4).
2. **No block-1 re-score and no pooling.**
   - Block 2 holds no date ≤ 2026-10-13.
   - 2026-10-13 is an orphan: it was declared under SEARCH 1 (`RULING_MAKER-S1_SEARCH_declaration_2026-10-12.md:28`), belongs to neither block, and is never recovered.
3. **One claim per block, enforced in code.**
   - The command-line tool accepts a v1 block only with sha `cf9a4dad…` (C2b).
   - The ledger refuses a second v2 claim on the same `block_first_day` unless a dated addendum names a voided run (C5).
4. **Known post-claim voids are moved before the claim.**
   - For v2 blocks these run before the claim: first-replayable check (report-only), truth-vs-cross-check agreement and overlap, frozen-set rule, cross-check sha, census-days sha, trigger E.
   - Remaining post-claim voids are all non-result. Each is re-runnable only via a dated addendum and is listed in Doc B §3:
     - S-2 direction (`driver.py:224`, `probed.require_clean()`)
     - S-7 Δ bound (`driver.py:230`)
     - S-5 RSS abort (`maker_stage0_modes.py:222-224`)
     - RTMAX, OOM, host kill, unexpected exceptions
5. **Small TDD units with named tests.** No unit touches an S-* screen test, the NO-SEND firewall, `BacktestOrderGuard`, `AS_MARGIN` or any existing firewall assertion.
   - Freeze scope: C1, C1b, C2, C2b, C3, C4, C5, C6, C6b, W1, plus C7 if W1 or a bench STOP triggers it.
   - Every merge passes the full gate with EXIT=0 and `lint-imports` reports "N kept, 0 broken".
   - Between Doc B FINAL and the evidence commit, the only permitted merge is the single pre-declared C7 exception (§4).
6. **Forfeiture accrues as reads happen.**
   - Every second-look census invocation is ledgered before tape is touched, with a chain hash.
   - Days after E are refused in code.
   - The registry is narrowed to [S, E] after the evidence commit.
7. **Tail result is disclosure only.** The block-2 verdict embeds the block-1 tail table through `--tail-csv`. It is never a label, a refit, a margin change or an FQ-v2 trigger.

**Binding constraints:**
- Nautilus immutable; `allow_short=False`.
- Never weaken a safety, settlement, contract or S-* test. Widen exact sets by one reviewed row only (L-12).
- Never edit a FINAL ruling, PREREG or addendum. Changes are new dated documents.
- No result-driven re-runs. GO is never an outcome. No live enablement.
- The operator controls only the two budget caps; neither is involved here.
- Clock: no unit starts inside or runs into 15:10–16:10Z or 02:05Z (`S2_RUN_PROCEDURE_2026-10-14.md:29`). Verified timers:
  - nbp-nightly 02:05Z (`breezy-nbp-learning-nightly.timer:11`)
  - tape rotation 09:00Z (`breezy-quote-tape-rotate.timer:25`)
  - truth fetch 11:40Z (`breezy-truth-fetch.timer:13`)
  - truth dataset 12:40Z (`breezy-truth-dataset.timer:15`)
  - ingest-frequent every 15 min except 16:30–17:00Z (`breezy-quote-tape-ingest-frequent.timer:27-30`)

## 1. Trigger and block definition

**Governing texts:**
- Amendment :71: "A second verdict scoring pass on this set is forbidden."
- Amendment :76: "A result-driven re-run is forbidden."
- Amendment :77: "More days … need a new dated declaration with its own frozen set."
- S3 r3 :149 is S3's UNDERDETERMINED trigger.
- Spec :222-224: n_eff ≥ 30 or UNDERPOWERED-WAIT.
- L-56 (`LESSONS.md:310`): "never count the motivating fills toward n".

**Pooling.** The blocks are disjoint, and block 2 gets its own standalone V0. Block-1 numbers may be cited descriptively only; they never enter any n, rate or confidence interval. No pooled table is produced.

**Block rule** (pinned in Doc A):
- **Start:** S = 2026-10-14. This is the conservative reading.
- **Stations:** LAX, MDW, MIA, SFO. NYC never.
- **Counted station-day:** census `reason == "COVERED"` and `listed_in_time(first_seen_ns, day)`.
  - `listed_in_time` is `maker_stage0_rule.py:250-255`: listed if `listed_ns <= D-1 12:00Z`, inclusive; `None` means False.
  - `first_seen_ns` comes from `src/breezy/analysis/maker_tape_census.py:448`.
- **Proxy:** `n_eff_proxy = Σ m_d/(1+(m_d−1)·0.5)` via `n_eff_gov` (`maker_stage0_inputs.py:143-145`).
- **T = 34.** Derivation in n_eff units:
  - Block 1 had 88 COVERED rows (`station_days.csv` has 96 rows; the 8 non-COVERED rows are at :42-49).
  - `wp0_agreement.json` has `"listing_abstain": true` on 44 rows: 40 COVERED plus 4 LOW_COVERAGE.
  - COVERED and listed in time: 48 station-days, 12 dates × 4, giving a proxy n_eff of 19.20.
  - Realised `n_eff_gov` was 18.73, a shrink of 0.976; 30 / 0.976 ≈ 30.7.
  - T = 34 adds a deliberate margin of about 2 dates, pinned before any block-2 read.
- **E** is the first day whose cumulative proxy reaches 34, read from the pinned trigger rows.
- **Cap:** E_max = 2026-11-15.
- **Dates:** S .. min(E, last_final_day), with `last_final_day ≥ E` as a hard STOP.
- **Expected E:** about 11-04 (22 dates at m_d = 4) to 11-06 (block-1 hole rate).

## 2. Documents

### Doc A — `docs/evidence/RULING_MAKER-S2_second_look_SEARCH_declaration_<date>.md`

**Preconditions for FINAL:**
- C6b merged with the gate green. This proves the cross-check producer in code.
- The B6 pre-check is clean.
- Peer review has converged.
- If C6b cannot be made feasible, **Doc A STOPs before FINAL.** No block-2 byte is read, and the named next action is a dated peer ruling on the cross-check source (L-3).

**After FINAL:** C1 pins Doc A's sha (pattern from 10-12 :7-8).

**Sections:**
1. **Basis.**
   - RA-13 B-3 (`RULING_RA-13…:90`), amendment :77, S3 :149, spec :222-224.
   - The 10-13 orphan and S = 10-14.
   - **Independence verdict: parsing-only cross-check.** The truth CSV and the cross-check are both IEM AFOS CLI products:
     - truth: text revisions written by `iem_cli_fetch.py fetch` (`breezy-truth-fetch.service:35`) and built by `… dataset` (`breezy-truth-dataset.service:29`);
     - cross-check: AFOS zip windows parsed by `settlement_truth_dataset.py`.
   - Corroboration, disclosed and never an exit failure: each fq-truth revision marker records a catalog cross-check (`deploy/systemd/README.md:1971-1973`).
2. **Declaration.** Days 10-14..11-15 (ceiling). Covers the counts-only trigger census, the single full Stage A over [S, E], and Doc B's reads. Never S5.
3. **Pooling ruling** (§1).
4. **Trigger rule** (§1 and C4).
   - S-1 and S-5 bind only on the single full Stage A over [S, E]. Every other census output is counts-only.
   - The S-1 STOP stays in the entry criteria. It is unlikely, not impossible.
   - **Unmodelled risk (D12):** T is informed by block 1. Listing before D-1 12:00Z began only on 09-30 and may not persist. R1 covers this.
5. **SEARCH cost.**
   - Realised forfeiture = 4 × (max day in any second-look census invocation − S + 1), read from the C1b read-ledger. The ceiling is 132.
   - EDGE-4 date effect is computed at both the ceiling and the realised figure (10-12 :61-64 arithmetic).
   - Any read of a day > E is a violation reported on the ledger line.
   - Exposure window: from `close` to the narrowing commit (≈ E+5) the registry row still spans (E, 11-15]. The census path is refused in code (C1b) and the crosscheck library path is refused (D4); only ad-hoc Python remains.
   - If peers reject narrowing, 132 is forfeited at Doc A FINAL instead.
   - RA-13 2027-01-25 stays firm (`RULING_RA-13…:97`).
   - The closing ledger line embeds the read-ledger sha256. B6 is re-checked at `close` and named on that line.
6. **NBP / AUT-4.** Block days are forward data (holdout ruling :9-11). Disclosed contamination for AUT-4 extends amendment :66 to [S, E]. Nothing calls `open_holdout`.
7. **S5.** `holdout_start_date` ≥ (max census-invoked day) + 2. This tightens `S5_shadow_run_and_gates_plan_r3.md:218`.
8. **Disposition.**
   - Exploratory; GO is never emitted (spec :224). Labels follow the S2 procedure's Step 8. A second WAIT goes to a dated peer ruling, with no automatic third block.
   - Passing V0 does not secure §6.9 power (`MIN_EXPECTED_LOSSES` 10.0, `maker_stage0_stats.py:28`). NOT-KILLED-UNSCREENED is admissible (`S5_…_r3.md:27`).
   - **Pre-registered (D12):** the tail shows a 2.5× YES excess against the frozen 1.5 margin (`stats.py:26`). A Test A FAIL, meaning NO-GO (adverse selection), is therefore the likely outcome. That path stands and is not softened.
   - **Pre-declared bench exception (C6):** if a block-2 bench gives PROJ > 21,600 s, exactly one C7 merge is permitted before the claim. It requires the full gate and a re-bench; CODE_SHA is re-recorded; the exception is disclosed on the ledger line. Nothing has been scored at that point.
   - If the re-bench still exceeds 21,600 s: STOP, with a dated peer ruling as the named next action.
9. **Trade unit reused.** sha `6459e9f6…` (evidence :403). Stage B is not re-run.
10. **Tail disclosure** (§5).
11. **Ledger lines.** RA-13-FW audit, plus the H-ARCHIVE-RECAL section (pattern from 10-12 :130-134).
12. **Doc B template**, verbatim, including every fence field below.

### Doc B — `docs/evidence/RULING_MAKER-S2_second_look_licence_<date>.md`

DRAFT is committed with Doc A. It is filled mechanically once (§6 order).

**§1 licensed reads** (exhaustive):
1. One verdict pass over block days: NBP 13Z/19Z D−1 and 01Z D, tape including Depth10/`DepthTruncation`, the pinned truth and cross-check.
2. `--bench` 4 and 8.
3. Verify-first on 2026-06-30.
4. WP0 direction check and SFO control.
5. `--tail-csv` set to the block-1 tail table.
   - Path: `~/.local/share/breezy/derived/maker_stage0/tail/tail-20261016T062622Z/tail_reliability.csv`, sha `6749a921…` (evidence :100). Its sibling `run_manifest.json` is pinned by `finish._extra_pins` (`maker_stage0_finish.py:80-86`).
   - Fallback: the committed sidecar copy (same sha; there the run-manifest pin records `None`).
   - `--tail-only` itself is not licensed, and C3 refuses it for v2.

**Fence `FROZEN_DATE_SET_V2`:** `stations`, `block_first_day`, `trigger_day`, `trigger_rows_path` (repo-relative committed copy; the rows are counts-only and outcome-blind), `trigger_rows_sha256`, `census_days_sha256`, `truth_csv_path`, `truth_csv_sha256`, `cross_check_path`, `cross_check_sha256`, `last_final_day`, `dates`.

**§3** copies amendment :71-77 (addendum name `RULING_MAKER-S2_second_look_addendum_<date>.md`) and lists the residual post-claim voids from acceptance criterion 4.

**Ledger.** A fresh sha means a fresh claim (`ledger.py:200-205`). C5 adds the per-block guard.

## 3. Code changes (TDD; RED→GREEN kept; focused gate → `lint-imports` → full gate after every merge, L-43)

### C1 — registry module (`src/breezy/analysis/maker_search_declarations.py`, new)

- `SearchDeclared` moves here. Rows are `(stations, first, last, sha)`:
  - Row 0 is today's range and sha (`maker_tape_census.py:71-78`).
  - Row 1 is (10-14, 11-15, Doc A sha).
- It must not import the census module. Today `MAKER_STATIONS` is defined at census :62, which would create a cycle, so the registry holds its own literal. The test `test_registry_stations_equal_census_maker_stations` keeps them aligned.
- The census module re-exports `SEARCH_DECLARED` and `SEARCH_DECLARATION_SHA256`. `require_firewall_clearance` (:178-200) clears a post-freeze day only if the containing row's sha matches.
- Existing tests at `test_maker_tape_census.py:112-116` and `:119-126` stay byte-unchanged. In particular, 10-14 with the first sha is still refused.
- New tests:
  - `test_second_look_day_cleared_only_with_second_declaration_sha`
  - `test_first_block_day_refused_with_second_declaration_sha`
  - `test_day_after_second_look_ceiling_refused`
  - `test_registry_rows_are_disjoint_and_pinned`
- **Narrowing commit** after the evidence commit: row 1 becomes [S, E]. This edits the ceiling test and the pinned-row test in the same commit. It is a tightening.

### C1b — census guard, read-ledger, counts-only and full modes

All logic lives in `run_census` (`scripts/analysis/maker_tape_census.py:260`) with injectable `read_ledger`, `today` and `trigger_close`, so library callers cannot bypass it. `main` (:481-520) gains extracted helpers so it stays under 50 lines.

- When any planned day clears through registry row ≥ 1:
  - Refuse `day_to > today − 2`.
  - Refuse when no `read_ledger` is supplied.
  - After `_plan_rows` clearance (:243-257) and before the first instance is touched (:285), append `{sha, mode, from, to, rows_chain_sha256, ts}`.
  - Consequence: a firewall-refused run never counts. A run that fails with an IO error after the append does count. That is conservative and documented.
- **`--counts-only`:**
  - Writes only `{station, climate_day, reason, first_seen_ns}` to its own file.
  - `--output` becomes optional; today it is `required=True` (:474). Full rows are never written; today they are at :507.
  - No `_report` (:519), no prints file.
  - Exit 0 regardless of `s5_unscreened`; today :520 returns `_EXIT_UNSCREENED`.
- **Full mode under a row ≥ 1 sha:** refused unless:
  - `from == S` and `to ==` the E recorded in the `trigger_close` file, and
  - the read-ledger holds no earlier full run for that sha.
  - A second full run needs a dated addendum.
- Tests:
  - `test_census_refuses_range_end_after_check_date_minus_two`
  - `test_census_records_every_second_look_invocation_before_reading`
  - `test_counts_only_file_on_disk_has_exactly_four_fields_and_no_summary`
  - `test_counts_only_exit_is_zero_whatever_s5_unscreened`
  - `test_full_census_before_close_refused`
  - `test_second_full_census_under_doc_a_sha_refused`

### C2 — v2 frozen block (`scripts/analysis/maker_stage0_frozen.py`)

- Today `LAST_ALLOWED_DAY` and `FIRST_REPLAYABLE_CHOICES` (:36-37) refuse every block-2 date (:126-127).
- Fence matching uses exact, anchored MULTILINE regexes: v1 `^```FROZEN_DATE_SET[ \t]*$` and v2 `^```FROZEN_DATE_SET_V2[ \t]*$`. This is needed because `_OPEN_FENCE` at :47 is a prefix of the v2 fence. A document with both fences is refused.
- `FrozenDateSet` gains `block=1`, `trigger_day`, `trigger_rows_path`, `trigger_rows_sha256`, `census_days_sha256`, `cross_check_path`, `cross_check_sha256`, all defaulted to `None`, so every v1 construction site is unchanged.
- For v2, `first_replayable_day = block_first_day`.
- v2 rule: dates = `block_first_day .. min(trigger_day, last_final_day, 11-15)`.
- v2 refuses: any date ≤ 10-13; `block_first_day ≠ 10-14`; `trigger_day > 11-15`; `last_final_day < trigger_day`; NYC; `<FILL`; DRAFT.
- `verify_set_matches_rule` (:193-216) branches on `block`; the v1 branch is byte-identical.
- **Pre-claim, verdict-mode checks for v2** in `preflight` (`maker_stage0_preflight.py:153-168`, which today checks only the truth sha at :161 and that the cross-check exists at :146). Each mismatch refuses:
  - hash the cross-check file;
  - hash the `--census-days` file;
  - hash the trigger rows;
  - recompute E with C4's pure `first_crossing` (frozen T = 34, `RHO_ASSUMED`, `listed_in_time`).
- Tests:
  - `test_v2_block_parses_and_matches_rule`
  - `test_v2_refuses_any_block1_date`
  - `test_v2_refuses_last_final_before_trigger_day`
  - `test_v1_parser_refuses_v2_only_doc`
  - `test_v2_parser_refuses_v1_doc`
  - `test_both_fences_refused`
  - `test_v1_parse_of_committed_amendment_is_unchanged`
  - `test_v2_trigger_day_must_recompute_from_pinned_rows`
  - `test_v2_cross_check_sha_mismatch_refused_before_claim`
  - `test_v2_census_days_sha_mismatch_refused_before_claim`

### C2b — v1 sha pin at the command-line layer (C4 resolution)

- In `maker_stage0_replay.py`, after `parse_args` (the sha arrives at :97 and is carried into `RunConfig` at :151) and before `drv.run` (:172):
  - In verdict mode (no `--bench`, `--tail-only` or `--verify-first`), load the amendment.
  - If it is v1 and the sha ≠ `V1_AMENDMENT_SHA256` (`cf9a4dad…`), refuse with exit 2.
  - A v2 block carrying that sha is also refused.
- The driver is untouched. `test_maker_stage0_driver.py:366-373` (a different-sha v1 amendment in verdict mode expects `RunVoided` after the claim) and every `drv.run(` call site stay byte-unchanged.
- Tests in `tests/unit/test_maker_stage0_replay.py`:
  - `test_cli_refuses_v1_block_for_any_other_sha`
  - `test_cli_refuses_v2_block_with_the_v1_sha`
  - `test_cli_bench_and_verify_first_unaffected`

### C3 — first-replayable check report-only for v2

- Verified mechanism:
  - `first_print_instant` keeps only licensed rungs (`maker_stage0_probe.py:300-311`). For block 2 its first print can fall on a 10-14 rung, so `first_replayable_day` (`probe_core.py:210-215`) can come out as 10-15.
  - The equality check sits after the claim (`driver.py:225-229`), and `_run_verdict` turns a failure there into a void (:189-196).
- Change: extract a pure `check_first_replayable(probed, frozen)`.
  - v2 never raises. The value is already recorded in `wp0_agreement.json` (`probe.py:381-383`).
  - v1 keeps equality.
  - `--tail-only` with a v2 block is refused.
- Coverage is enforced elsewhere: census COVERED feeds `in_denominator` (`rows.py:113-116`), and every set date must appear in the census rows (`frozen.py:213-216`).
- Tests:
  - `test_v2_records_but_never_refuses_on_first_replayable_day` (first print after D-1 16:50Z)
  - `test_v1_still_requires_equality`
  - `test_tail_only_refused_for_a_v2_block`

### C4 — trigger tool (`scripts/analysis/maker_stage0_trigger.py`, new, < 150 lines)

- **Pure function:** `first_crossing(rows, T=34)`.
- **`check`:**
  - Takes a lock file in the work root (single writer).
  - Runs one multi-day counts-only census for all not-yet-checked days up to c−2. Batching is needed because `run_census` scans every instance on each invocation (`scripts/analysis/maker_tape_census.py:285-296`). Per-station-day rows do not depend on the range.
  - Appends rows in date order and evaluates the crossing after each day.
  - At the first crossing, writes a terminal `CROSSED` row and ignores later days of the batch. Rows past E are discarded unread. The census pass does touch them, so they count toward forfeiture.
  - Refuses every later `check`.
  - Writes the rows' chain hash into the C1b ledger line.
- **`close`:**
  - Hashes only rows ≤ E.
  - Writes `trigger_close.json` with E, the rows sha and the chain hash.
  - Re-verifies the forfeiture line against the read-ledger (D13).
  - Copies the rows into the repo.
- **Disagreements:** final Stage A rows that differ on any day ≤ E (`instances_live_unread`/`_corrupt_unread`, `src/…/maker_tape_census.py:433-435`) are disclosed and never move E.
- Tests:
  - `test_check_stops_at_first_crossing_inside_a_catch_up_batch`
  - `test_post_crossing_check_refused`
  - `test_trigger_counts_only_covered_listed_in_time`
  - `test_listed_in_time_boundary_exactly_d_minus_1_1200z_counts` (D13)
  - `test_close_hashes_only_rows_up_to_e`
  - `test_close_forfeiture_matches_read_ledger`
  - `test_listed_in_time_agrees_with_probe_listing_abstain`
- **Unit (D3):** repo-committed `deploy/systemd/breezy-maker-s2-trigger.{service,timer}`, parked and then enabled, with a README section. Two reviewed one-row widenings (L-12):
  - `STAGE0_ENTRY_MODULES` (`tests/unit/test_runtime_import_isolation.py:68-145`)
  - the systemd-derived entry set read by `test_persistence_import_free.py` (`tests/support/entry_points.py:26-50`)

### C5 — ledger (`scripts/analysis/maker_stage0_ledger.py`)

- `_KEYS_BY_KIND` (:66-69) becomes `Mapping[str, frozenset[frozenset[str]]]`. The read check (:149) becomes `frozenset(entry) not in accepted`. KIND_START accepts exactly the 6-key set or the 6-key set plus `block_first_day`.
- `claim_verdict_run` (:224-253) takes `block_first_day: str | None = None` and omits the key entirely when `None`. A null 7-key entry is never written.
- `_refusal` (:200-211) matches on `block_first_day` only when the claim's value is not `None`, and reads legacy entries with `.get`.
- The driver passes the block's first day from `pre.frozen` only for v2.
- Tests (RED first):
  - `test_v1_claim_writes_exactly_six_keys`
  - `test_v1_claim_never_matches_on_block_first_day`
  - `test_start_entry_key_sets_are_exactly_six_or_seven`
  - `test_second_v2_licence_same_block_refused_without_addendum`
  - `test_v2_claim_writes_block_first_day_from_pre_frozen` (driver-level, v2 world)

### C5r — render plumbing (D7)

- `HOLDOUT_LINE` (`render.py:41-47`) is consumed at `render_report` :256 and `render_stop_report` :285.
- Both functions gain optional `holdout_line: str = HOLDOUT_LINE` and `d5_line: str = _D5` (:84-88).
- `finish` computes both lines from `pre.frozen` (`finish.py:97`) through a `block_lines(frozen)` builder:
  - v1 returns the constants unchanged.
  - v2 renders: days S..E as forward data; no tail-day read; AUT-4 contamination; "never calls open_holdout"; the count of days not yet past D+14.
- Render and driver tests (including :258-260) stay unchanged.
- Tests: `test_holdout_line_reflects_the_block`, `test_d5_disclosure_reflects_the_block_and_d14_status`.
- **Sweep (D8):** named test `test_no_unlisted_block_date_literals_in_maker_stage0_modules`.
  - The regex matches `dt.date(2026, …)` and bare ISO dates, and skips string literals containing `/` or `.md`. That exempts doc paths such as `model.py:34`, `replay.py:40`, `rule.py:4`, `stats.py:5` and plan-path docstrings.
  - Allowlist: `frozen.py:35-37`, :70; `driver.py:113` (TAIL_RANGE); `render.py:41-47`, :84-88; `runio.py:96`; `inputs.py:334`.

### C6 — pre-claim truth agreement (v2)

- Verified: `load_truth` raises on an empty overlap (`inputs.py:357-360`) and on disagreement (:361-363). It runs post-simulation (`report.py:117-122`), which is after the claim.
- Change: a shared `truth_keys(stations, dates)` helper. In verdict-mode `preflight`, for v2 only:
  - run the full `load_truth` into a scratch directory, covering overlap, `TruthConflict` and the truth sha;
  - run `verify_set_matches_rule`.
- v1 is untouched, so `test_maker_stage0_driver.py:366-373` still expects `RunVoided`.
- The vacuous guard is never relaxed.
- Tests:
  - `test_v2_cross_check_without_overlap_refused_before_claim`
  - `test_v2_truth_conflict_refused_before_claim`
  - `test_preflight_and_score_truth_keys_are_equal` (pins the preflight keys equal to the `score` keys from `sd_rows`, `report.py:118`, on the v2 world)

### C6b — feasible cross-check producer (C1 resolution; merged before Doc A FINAL)

**Verified storage facts:**
- The daily truth fetch writes per-station text revisions `<cache>/afos-cli/<LOC>/<fetch_date>.<sha12>.txt` (README :1962-1966).
- `settlement_truth_dataset.py` reads URL-hashed zips, `cache_dir/sha256(url).zip` (`window_zip_path` :343-351; `cache_path_for_url` `settlement_alignment_study.py:339-341`; `afos_url` uses `fmt=zip`, :425-435), gated by a digest sidecar (:354-381).
- So the two are **different storage, and the truth-fetch cache does not hold what the dataset reads.**
- `fetch_bytes_cached` refuses to write AFOS CLI URLs; `iem_cli_fetch.py` is the single writer (`settlement_alignment_study.py:373-378, 397-415`).
- The archive window ends at `_EXTENSION_WINDOW_END = 2026-09-28` (:279-280), and the module itself documents a cache miss as a refusal (:13-14).

**The fetch is therefore needed.** It uses the existing IEM AFOS CLI source class already fetched daily, through the same writer, transport and host allowlist. It is not new market data.

- **(a) `iem_cli_fetch.py window-zip`.** A new subcommand next to `fetch`/`dataset` (:638-649).
  - Takes the cache lock, honours `_in_launch_window` (:661-662), and uses the paced `IemCliTransport` (:687-692).
  - Writes the zip for the URL `afos_url(loc, 2026-09-29, 2026-11-15, limit=3000)` per maker station, refusing to overwrite an existing file, and appends its sidecar line.
  - The window end is a request bound, not a coverage claim. Coverage is fixed by the single fetch at E+2 and pinned by digest.
  - It is a transient one-shot run. `iem_cli_fetch` is already an entry module, so no new entry row is needed.
- **(b) `settlement_truth_dataset.py`.** Add pinned `_MAKER_S2B_WINDOW_START = 2026-09-29` and `_MAKER_S2B_WINDOW_END = 2026-11-15` behind a new opt-in `--include-maker-s2b-window` flag, mirroring `--include-extension` (:1252-1263). Default behaviour and all existing callers are unchanged.
  - Output goes to `--output-dir ~/.local/share/breezy/derived/maker_stage0_inputs/cross_check_s2b/`, allowed by `validate_output_dir` (:1226-1239). The shared `settlement-truth/settlement_truth.parquet` is never overwritten.
- Tests (fake transport):
  - `test_window_zip_writes_url_hashed_zip_and_sidecar_under_lock`
  - `test_window_zip_refuses_overwrite`
  - `test_window_zip_respects_launch_window`
  - `test_maker_s2b_window_is_opt_in_and_default_windows_unchanged`
  - `test_dataset_with_s2b_window_emits_rows_for_block_days`

### C7 — conditional instance pre-filter (D9)

Must land if W1 projects PROJ > 0.8 × 21,600 s, or under the Doc A §8 bench exception.

- Requires the W2(a) split first, because `probe.py` is at 398/400 lines.
- In `_for_each_clean_instance` (`probe.py:261-281`), skip the byte scan for an instance whose newest feather file mtime is earlier than the first licensed window start minus 1 day. This uses stat only (`_signature`, `scoped_convert.py:114-118`). The scan itself reads every byte (`scoped_convert.py:136-137`); the existing `keep_rung` filter (`probe.py:280`, `scoped_convert.py:71-83`) only scopes conversion.
- An instance last written before the block began cannot start, or end, an in-window span. That preserves driver rule D3 (`driver.py:17-18`).
- Skips are recorded in `skipped`.
- Tests:
  - `test_prefilter_skips_only_instances_last_written_before_the_block`
  - `test_prefilter_keeps_an_instance_whose_start_ends_an_earlier_span`
  - `test_licensed_outputs_identical_with_and_without_prefilter` (`skipped` excluded from the comparison and disclosed)

### Also in freeze scope

- **D4:** `trade_quantity_unit_crosscheck.firewall_clearance` (:121-132) refuses any registry row ≥ 1 sha (guard-only edit). Test: `test_crosscheck_refuses_second_look_declaration_sha`.
- **D11 v2 world:** `tests/fixtures/maker_stage0/replay_world.py` is bound to 09-18..10-13, so a new `replay_world_v2.py` with dates ≥ 10-14 is budgeted at about 1 day. It serves C2/C5/C6 and one v2 end-to-end smoke test.

### Unchanged

- `assert_delta_within_bound`, the S-5 abort, `AS_MARGIN`, all S-* tests, the NO-SEND firewall.
- `lint-imports` covers `breezy` and `nautilus_trader` (`pyproject.toml:71`). The new `src` module imports no `scripts` code.

## 4. WAIT-period engineering backlog

- **Freeze scope:** C1, C1b, C2, C2b, C3, C4, C5, C5r, C6, C6b, D4, D11, W1, plus C7 if triggered.
- **Order:** C6b → Doc A FINAL → C1 → C1b → C4 (with its unit) → C2 → C2b → C3 → C5 → C5r → C6 → D4.
- **W1 (must):**
  - Run 1 baseline: ≈ 7,800 s preamble and ≈ 7,400 s scoring for 96 station-days (evidence :22).
  - Scale by bytes, not instance count: `PREAMBLE_S = 7,800 × B_now / B_run1`.
    - B = total feather bytes of CLEAN instances, from stat sizes.
    - B_run1 = the bytes of instances whose newest mtime ≤ 2026-10-16 02:07Z. Rotated instances are immutable, so this is reconstructable.
  - `SCORE_S = 7,400 × n_sd / 96`, and `PROJ = PREAMBLE_S + SCORE_S`.
  - Measure on 10-21, project to 11-15, decide C7 by 10-24.
  - Re-measure at Doc B FINAL. If PROJ > 21,600 s, the Doc A §8 exception applies.
  - The pre-progress stall alert is set at 1.5 × `PREAMBLE_S`.
- **W2(a) split:** with C7, or after the evidence commit.
- **W2(b) preamble bench:** after the evidence commit.
- **W4 `listing_abstain.csv` sidecar:** after the evidence commit; one-row widening.
- **W5:** not changed; this is the S-5 formula.
- **W3, W6:** dropped. W6 is redundant because `--tail-csv` exists.

## 5. Tail diagnostic routing

**Verified path:**
- `--tail-csv` is a CLI flag (`maker_stage0_replay.py:117`) that becomes `cfg.tail_csv` (:163).
- `finish._write_tables` reads it (`finish.py:67`) and the tables are rendered from it (`tables.py:325-340`).
- `tail_table` sets `miscalibrated` (`stats.py:355-366`), and `render_verdict` emits the annotation (`tables.py:127-128`). The label is unaffected (`test_maker_stage0_verdict.py:794-801`, kept).
- Run 1 passed no tail CSV ("tail csv source `none`", evidence :415). That is why no annotation appeared. It was a procedural gap, not a threshold or a disabled switch.
- The block-2 verdict passes `--tail-csv` (Doc B item 5), so the annotation is emitted there and pinned (`finish.py:80-86`).

**Disclosure targets:**
- `STAGE0_REPLAY_2026-10-16.md:100-111`.
- Doc A §8 and §10.
- S5 PREREG `holdout_freeze_disclosure` (`S5_…_r3.md:226`) as model risk. The margin stays frozen.
- AUT-4: a contamination note. The errata location is unverified (U-5).

**Never routed** to FQ-v2 triggers or to NBP fits (amendment :58-60).

## 6. Calendar and order (UTC)

**Cadence (D2).** Trigger `check` runs at 10:05Z:
- after the 09:00Z rotation and the 10:00Z ingest tick;
- before truth fetch (11:40Z) and the 12:15Z ingest;
- under the studies `flock`, with `RuntimeMaxSec` 3600.

Overlap with an ingest-frequent tick cannot be avoided on any 15-minute grid before 16:00Z. It is accepted for three reasons:
- ingest is idempotent per file (timer :7-12);
- the census treats LIVE instances as unread (`scripts/analysis/maker_tape_census.py:297`);
- days ≤ c−2 sit in instances that have already rotated.

Run 1's verdict ran alongside the same ticks. Before Doc A FINAL, measure the wall time of one single-day census with the existing CLI on [10-12, 10-12] under the 10-12 sha: a licensed S1 read of a day that is already forfeited, with the log sealed.

| Date | Step |
|---|---|
| 10-17 | B6 pre-check (exit-window nightly JSONs, method 10-12 :55-59; replay-daily; monitor/hold studies); single-day census timing |
| 10-18 to 10-19 | C6b merged, gate green → Doc A FINAL plus Doc B DRAFT |
| 10-21 | C1, C1b, C4 plus unit enabled; checks start; W1 bytes measured |
| 10-24 | C7 decision; remaining freeze-scope units merged |
| ≈ 11-04 to 11-06 (cap 11-15) | E reached by the counts-only trigger → `close` (trigger unit disabled) |

**Fixed order from `close` (D1):**
1. Pin the truth copy after the 12:40Z dataset run. STOP unless `last_final_day ≥ E` (observed lag ≈ 2 days; amendment :28).
2. Pin the cross-check: `window-zip` at 13:00Z, then the dataset with `--include-maker-s2b-window` into the s2b directory, then sha.
3. Run the final Stage A over [S, E] (full mode, once). It must end before 15:10Z.
4. Read the S-1/S-5 STOP lines from that run (they bind).
5. Verify the trigger: recompute E from the committed rows and compare the census-days sha (C2 logic, run as a self-check).
6. Doc B FINAL commit, then the full gate (EXIT read before push).
7. CODE_SHA = HEAD. All freeze-scope code was merged earlier.
8. P2 NBP backfill (avoid 16:30–17:10Z), verify-first, bench 4 and 8 (E+2 to E+3). Doc A §8 bench exception if PROJ > 21,600 s.
9. Verdict run, launched after 02:05Z (E+3 to E+4 ≈ 11-08 to 11-10), with `--tail-csv`.
10. Evidence commit, then C1 narrowing commit, then PROGRESS row 2. S5 start ≥ max read day + 2. S3 binding run at ≈ E+5 if the label is allowlisted.

## 7. Risk register and LESSONS compliance

| # | Risk | Mitigation |
|---|---|---|
| R1 | Listing before D-1 12:00Z does not persist, so no crossing | Cap 11-15; peer ruling (Doc A §4 discloses the risk) |
| R2 | Proxy overstates n_sd | T = 34 against a bare 30.7 |
| R3 | Preamble growth | W1 byte scaling; C7; the Doc A §8 single-merge exception |
| R4 | Memory: bench-8 projection 3.72 GB (evidence :47) | Bench re-run; MEMMAX rule unchanged |
| R5 | Post-claim voids | C2, C3, C6 move them pre-claim; residual list in Doc B §3 |
| R6 | Repeated looks (L-34) | Counts-only; CROSSED terminal row; single full Stage A |
| R7 | Reads past E or into S5 days | C1b guard and ledger; D4; narrowing commit; S5 start rule |
| R8 | Copied amendments | C2b at the CLI layer; C5 per-block ledger guard |
| R9 | Cross-check fetch fails at E+2 | STOP before the claim; retry the next day after 13:00Z; peer ruling after a 3-day failure |
| R10 | Truth timer fails silently | Order step 1 hard STOP |
| R11 | θ drift (`preflight.py:156`) | Refused before the claim |
| R12 | S-1/S-5 fire on the final Stage A | Pre-registered STOP |
| R13 | Other consumers already read 10-14+ tape | B6 at Doc A FINAL and again at `close` |
| R14 | The v2 test world costs more than budgeted | D11 budget; pure-function tests first |

**LESSONS applied:**
- L-1 "Validate the Nautilus null hypothesis BEFORE proposing to build": study code only.
- L-3 "A plan whose end state is not the goal state is not a plan": every STOP has a named next action (C6b infeasible, bench re-STOP, second WAIT).
- L-12 "Widen an exact-set barrier, never relax it": ledger key sets, the two entry-point rows, W4.
- L-33 "A characterisation item has no RED; demand mutation evidence instead": the W2(a) split.
- L-34 "The trial's TRIGGER is pinned; a re-look is a second snapshot".
- L-38 "A stop rule whose counter cannot increment is a missing stop".
- L-43 "…gate … after EVERY merge".
- L-53 "A cache cannot fix an input that never completes".
- L-56 "…never count the motivating fills toward n".
- L-4 "A fix is a diff against one finding; a document is a set of claims": render lines and the sweep.

## 8. Confidence self-assessment

Overall confidence: about 0.85, up from 0.8.

**Raised, because verified in code:**
- The C6b storage split (`settlement_truth_dataset.py:279-280, 343-381`; `settlement_alignment_study.py:339-341, 373-435`; README :1962-1970).
- The C2b placement (`replay.py:93-181`; driver test :366-373).
- `--tail-csv` (`replay.py:117`, `finish.py:67, 80-86`).
- Render consumers (`render.py:256, 285`).
- Ledger types (`ledger.py:66-69, 149, 200-253`).
- Census CLI lines (:474, 507, 519-520).
- The `listed_in_time` boundary (`rule.py:250-255`).
- Timers and the entry-point scanner (`entry_points.py:26-50`).

**Unknowns:**
- U-1: How the instance byte total grows (measured 10-21).
- U-3: Whether IEM accepts the 2026-09-29..2026-11-15 zip request at E+2. The format is proven by the SL-5 window; the live fetch is not.
- U-4: The B6 outcome.
- U-5: Where the AUT-4 errata file lives.
- U-6: Whether peers accept the narrowing (fallback: 132 forfeited up front).
- U-7: θ and NBP coverage through 11-15.
- U-8: Wall time of a single-day census (measured before Doc A FINAL).

No item needs a hard constraint broken; every STOP above has a named next action.

## Round-3 resolutions

| Item | Resolution | Section |
|---|---|---|
| C1 | Storage verified as different, so a fetch is needed (same IEM CLI class, single writer); C6b `window-zip` plus opt-in s2b window into a separate output dir; parsing-only independence verdict in Doc A §1; vacuous guard kept; Doc A STOPs before FINAL if infeasible | §3 C6b, C6; §2 Doc A |
| C2 | Fence gains `trigger_rows_path` and `census_days_sha256`; dataclass gains 4 more defaulted fields; pre-claim hashes plus E recompute; tests named | §2 Doc B; §3 C2 |
| C3 | CROSSED terminal row, post-crossing refusal, `close` hashes rows ≤ E only, batched catch-up, chain hash, lock; counts-only writes no full rows and exits 0; single full census gated on `close` plus ledger; `mode` and read-ledger sha on lines | §3 C1b, C4 |
| C4 | v1 sha pin at the CLI layer (`replay.py`), driver and existing tests unchanged | §3 C2b |
| C5 | Set of exact key sets; `block_first_day` omitted when `None`; `.get` on legacy entries; four RED tests plus a driver-level test | §3 C5 |
| C6 | Doc A §8 pre-declares one C7 merge after a bench STOP, with gate, re-bench and disclosure; re-STOP goes to a peer ruling | §2 Doc A §8; §4; §6 |
| D1 | Numbered order from truth copy to verdict | §6 |
| D2 | 10:05Z under the studies flock; ingest overlap accepted, with reasons | §6 |
| D3 | Repo timer plus two L-12 rows (`STAGE0_ENTRY_MODULES`, entry-points scan) | §3 C4 |
| D4 | Crosscheck guard refuses row ≥ 1; exposure window stated | §3; §2 Doc A §5 |
| D5 | Shared `truth_keys` with an equality test; full truth agreement and rule pre-claim for v2; residual void list in AC4 and Doc B §3 | §3 C6; Acceptance 4 |
| D6 | W6 dropped; Doc B item 5 uses `--tail-csv`; pins verified | §5; §2 Doc B |
| D7 | Optional `holdout_line`/`d5_line` params threaded from `finish` | §3 C5r |
| D8 | Named sweep test with a doc-path-exempt regex and allowlist | §3 C5r |
| D9 | Byte-based scaling; stat-only pre-filter keeps span-ending instances; identity test excludes `skipped` | §4 W1; §3 C7 |
| D10 | Registry free of census imports (stations literal plus equality test); helpers extracted; injectable ledger; append after clearance (IO-failed runs counted); narrowing edits two tests | §3 C1, C1b |
| D11 | v2 world budgeted at ~1 day; pure `check_first_replayable` | §3 C3; §3 Also in freeze scope |
| D12 | Doc A pre-registers likely Test A FAIL, block-1-informed T with listing-persistence risk, B6 re-check at `close` | §2 Doc A §4, §5, §8 |
| D13 | Boundary test at exactly D-1 12:00Z; `close` re-verifies forfeiture against the read-ledger | §3 C4 |