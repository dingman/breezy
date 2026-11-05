# MAKER-S2 second look (after UNDERPOWERED-WAIT): implementation plan

## Acceptance criteria

The plan is done when:

- **Rule written first.** The rule that fixes the second frozen block (start day, count condition, cap, end-day definition) is written out and does not depend on any fill, rate, settlement or label value. It is FINAL in Doc A (§2) before any block-2 tape byte reaches `admit_print`.
- **Block 1 is never re-scored.** The second block contains no date ≤ 2026-10-13, and no artefact pools block-1 outcomes with block-2 outcomes.
- **Code units are small and safe.** Every code change is a small TDD unit with named tests. None touches an S-* screen test, the NO-SEND firewall, `BacktestOrderGuard`, or any existing firewall test assertion.
- **CODE_SHA freeze is real.** All must-land units are merged and full-gate green (`scripts/ci/run_tests_no_egress.sh`, `lint-imports` "N kept, 0 broken") before Doc B FINAL. From Doc B FINAL to the evidence commit, nothing merges.
- **Exactly one ledger claim**, keyed by Doc B's FINAL sha. A non-result void is re-run only through a dated addendum.
- **The tail result routes as disclosure only**, never as a label, refit, spec change or FQ-v2 trigger.

Binding constraints, restated:
- Nautilus immutable. `allow_short=False`. Never weaken a safety, settlement, contract or S-* screen test (widen exact sets by one reviewed row, L-12). Never edit a FINAL ruling, PREREG or addendum (changes are new dated documents). Result-driven re-runs are forbidden. GO is never an outcome. Nothing touches live enablement. The operator decides only the two budget caps (none is involved here). Recorder tape is the only new data source.
- Clock: no unit may start inside or run into 15:10–16:10Z or 02:05Z (02:05Z also starts the daily tape rotation): `S2_RUN_PROCEDURE_2026-10-14.md:29`, "Rule: unit start + its `RuntimeMaxSec` must end before the next blocked window."

## 1. Trigger and block definition

### Governing texts (quoted)

- Amendment `RULING_MAKER-S1_SEARCH_declaration_amendment_2026-10-13.md`:
  - :71: "A second verdict scoring pass on this set is forbidden."
  - :76: "A result-driven re-run is forbidden."
  - :77: "More days (S3 r3 :149 second look) need a new dated declaration with its own frozen set."
  - :21: the driver fails closed on "a date > 2026-10-13".
- `S3_loss_floor_reachability_plan_r3.md:149`: "Trigger: once the census adds ≥ `n0` more climate dates, S2 re-emits its numbers and S3 re-runs the binding run once." This is the UNDERDETERMINED trigger of S3's verdict (:148), a state S3 has not reached.
- Spec `SPEC_pm_us_no_ladder_maker_2026-10-12.md:222-224`: "A verdict requires the S1 station-day floor (effective n ≥ 30 climate-date-adjusted); below it Stage 0 emits UNDERPOWERED-WAIT". The spec says nothing about pooling.
- PROGRESS row 2 (`docs/core/PROGRESS.md:63`): "UNDERPOWERED-WAIT (n_eff < 30) is not a STOP".
- L-56 ("A hypothesis picked from a handful of fills cannot be powered by them…"), `LESSONS.md:310`: "never count the motivating fills toward n".

### Pooling ruling: the new block is new days only, never the union, never a pooled statistic

- **The union** would re-score set-1 station-days. That is a second scoring pass on that set, which amendment :71 forbids.
- **Pooling block-1 rows with block-2 rows at the statistics level** (for example, concatenating `station_days.csv`) re-emits a label from set-1 outcomes that have already been seen. It also counts the motivating sample toward n (L-56 :310).
- **S3 r3 :149** ("adds … re-emits") reads as cumulative. But it governs S3's UNDERDETERMINED state, not S2's V0. It predates the FINAL amendment, whose :77 "its own frozen set" is the later and more specific text.
- **Ruling:** the texts support disjoint blocks. Where they are silent (the spec), the conservative reading is chosen and stated as such. Block 2 is scored standalone: its own n_sd, n0 and `n_eff_gov`, and its own V0.
- Set-1 numbers stay descriptive. No pooled table, even report-only, is produced.

### Block rule (mechanical; pinned in Doc A before any read)

- **Start:** S = 2026-10-14. This is the first day after the amendment ceiling (:21) and the first day outside the 10-12 declaration (`RULING_MAKER-S1_SEARCH_declaration_2026-10-12.md:28`, "2026-09-26 .. 2026-10-13").
- **Stations:** LAX, MDW, MIA, SFO. NYC never. There is no sealed day in range: 2026-10-01 < S.
- **Proxy count, outcome-blind.** A station-day counts when:
  - its S1 census `reason == "COVERED"`, and
  - `maker_stage0_rule.listed_in_time(first_seen_ns, day)` is true (`maker_stage0_rule.py:250-251`: "S must be listed by D-1 12:00Z, else abstain"). This is the same predicate the driver uses (`maker_stage0_driver.py:208-210`) and the same field as `listing_abstain` (`maker_stage0_probe_core.py:286-293`).
  - `n_eff_proxy([S,d]) = Σ m_d/(1+(m_d−1)·0.5)` (`maker_stage0_inputs.py:143-145`, RHO_ASSUMED `maker_tape_census.py:96`).
- **Threshold T = 34**, not 30. In set 1, covered and early-listed station-days were 48 on 12 dates: 96 covered − 40 `listing_abstained` − 8 non-COVERED on 09-28/09-29 (`stage0_2026-10-16/station_days.csv:42-49`). Of those 48, 44 entered the V0 denominator (n_sd). Shrink 44/48 = 0.917, so 30/0.917 = 32.7, plus ≈ 1 station-day of margin gives 34. The shrink is an outcome-blind posting fact (`in_denominator`, `maker_stage0_rows.py:113-116`), not a fill.
- **End day:** E = the first day d ≥ S at which `n_eff_proxy([S,d]) ≥ 34`. E is a property of the census rows, not of the day it is checked. Only days with d ≤ check date − 2 are counted (window closed).
- **Cap:** E_max = 2026-11-15 (33 dates). If the trigger has not fired by then, E := E_max.
- **Frozen dates:** S .. min(E, last FINAL day in the pinned truth CSV). A day lacking FINAL is excluded and counted, never added (same as amendment :20).
- **Arithmetic for N.** At m_d = 4, each date adds 1.6, so 34/1.6 = 21.25, which means 22 dates and E = 2026-11-04 if every date is covered and listed before D-1 12:00Z. With set 1's hole rate (2 non-COVERED dates in 24), E ≈ 2026-11-06. Under the rejected pooled reading the brief's "≈ 7–8 more" would apply. The standalone reading needs about 22.
- **Consistency with S3 :149:** 22 ≥ n0 = 12, so S3's own "≥ n0 more" condition is also met.

## 2. Documents

### Doc A: `docs/evidence/RULING_MAKER-S2_second_look_SEARCH_declaration_<date>.md`

- FINAL and committed before any block-2 read. Its sha256 is pinned in code (unit C1) before the first census run. This mirrors 10-12 :7-8 ("`SEARCH_DECLARATION_SHA256` = sha256sum … WP1 reads exactly that repo-relative path").
- Sections:
  1. **Basis.** RA-13 B-3 (`RULING_RA-13_programme_kill_2026-09-27.md:90`, "ANY post-freeze count, outcome-blind or not, permanently spends H-ARCHIVE-RECAL CONFIRM days"); amendment :77; S3 r3 :149; spec :222-224.
  2. **Declaration table.** Stations; days 2026-10-14..2026-11-15 (ceiling). Covers: S1 census Stage A, the counts-only trigger check (C4), and the MAKER-S2 reads licensed by Doc B. Never covers S5.
  3. **Pooling ruling** (§1 above, verbatim).
  4. **Trigger rule** (§1 above, verbatim): T, predicate, E, cadence, cap, window-closed rule.
  5. **SEARCH cost.**
     - Ceiling: 4 × 33 = 132 station-days.
     - Realised: 4 × (E − S + 1), recorded in a closing ledger line. No census run's range ever extends past (check date − 2), so days after E are never read. The read definition is 10-12 :34-35 ("A read is: any row … passes `admit_print` …").
     - Date effect on the EDGE-4 revival, using the 10-12 :61-64 arithmetic.
     - The RA-13 backstop 2027-01-25 is untouched (`RULING_RA-13…:97`, "The date is firm").
  6. **NBP holdout and AUT-4.** Days ≥ 2026-10-02 are forward data (holdout ruling :9-11, cited at 10-12 :38-39). MAKER-S2 NBP-vs-outcome statistics on [2026-10-14, E] are disclosed contamination for AUT-4 forward windows, extending amendment :66 verbatim with the new range. MAKER-S2 never calls `open_holdout`.
  7. **S5 consequence.** Block-2 days become Stage 0 dev days (seen). S5 `holdout_start_date` ≥ E + 2 (`S5_shadow_run_and_gates_plan_r3.md:218`: "≥ last Stage 0 climate day + 2"). This fulfils 10-12 :41-42 ("S5 days (climate day >= 2026-10-14) are never read before their own declaration") for the Stage 0 reads only.
  8. **Outcome statement and disposition.** Exploratory, never GO (spec :224). Block-2 labels map to the S2 procedure's Step 8 dispositions. A second UNDERPOWERED-WAIT (the trigger never fired, or V0 fires anyway) goes to a dated peer ruling. There is no automatic third block (L-3).
  9. **Trade unit reused, not re-resolved.**
     - `trade_quantity_unit.json` sha `6459e9f6…` (evidence pins :403), verdict CONTRACTS.
     - Stage B's licensed fills are the 28 pinned rows in 10-12 §6 (:79-117), all ≤ 2026-10-06. The bot is not armed, so no own fill exists in block 2, and a re-run would read the same rows.
     - If any own fill is later found on a block-2 day, it is unlicensed and is reported, not read.
  10. **Tail disclosure** (§5 below).
  11. **Ledger lines.** One line in `docs/evidence/RA-13-FW_firewall_audit_2026-09-27.md`. A new final section in `RULING_H-ARCHIVE-RECAL-2026-09_horizon_2026-09-25.md` (pattern 10-12 :130-134).
  12. **Doc B template, verbatim.** Doc B may differ from it only in the filled block fields and the Status line.

### Doc B: `docs/evidence/RULING_MAKER-S2_second_look_licence_<date>.md`

- **Lifecycle.** DRAFT is committed with Doc A. It goes FINAL only after E is known and the truth copy is pinned, applied once and mechanically, like the S2 procedure's Step 3 (`S2_RUN_PROCEDURE_2026-10-14.md:66-103`).
- **§1 licensed reads (exhaustive):**
  1. Exactly one verdict scoring pass: NBP 13Z/19Z D−1 and 01Z D, tape incl. Depth10 and `DepthTruncation`, truth CSV plus cross-check, block days only.
  2. `--bench` 4/8 on block days.
  3. WP2 verify-first on 2026-06-30 at the new CODE_SHA (amendment :12).
  4. WP0 direction check and SFO control on block days.
  5. Optional, report-only: the `TAIL-MISCALIBRATED` recompute from the committed sidecar `tail_reliability.csv` (sha `6749a921…`, evidence :100). No new NBP read.
  - `--tail-only` is **not** licensed: its range 07-01..09-17 is already reported, and re-reading the holdout adds nothing.
- **Fenced block** `FROZEN_DATE_SET_V2` with fields: `stations`, `block_first_day`, `trigger_day`, `truth_csv_path`, `truth_csv_sha256`, `last_final_day`, `dates`.
- **§2 compliance.** **§3 re-run rule**, copying amendment :71-77 with the addendum name `RULING_MAKER-S2_second_look_addendum_<date>.md`. **§4 provenance.**
- **Ledger.** The driver claims with `amendment_sha=cfg.amendment_sha`. `_refusal` filters `e["amendment_sha"] == amendment_sha` and returns `None` when there is no match (`maker_stage0_ledger.py:200-205`), and `claim_verdict_run` then appends (:238-253). The amendment path and sha come from the CLI (`maker_stage0_replay.py:95-97`). So Doc B's new sha is a fresh claim with **no ledger code change**.

### What S1 re-runs

- **Census Stage A** on [S, E] with `--search-declaration <Doc A>` (`scripts/analysis/maker_tape_census.py:473,485-488`). Its output feeds `--census-days`.
- Its STOP lines bind as in the S2 procedure's entry criteria (:20).
- Stage A reports `n_eff_ub` on all COVERED station-days, which is ≥ `n_eff_proxy` ≥ 34 > 30, so its S-1 STOP cannot fire on a triggered block. The S-5 pre-screen still can.
- Stage B and WP3 are not re-run. The trigger checks (C4) are counts-only reads of census rows.

## 3. Code changes (each a TDD unit; RED→GREEN kept; focused gate, then `lint-imports`, then the full gate after every merge, L-43)

- **C1 — census firewall registry** (`src/breezy/analysis/maker_tape_census.py:65-78,178-200`)
  - Today: one range and one sha are hard-coded (`SEARCH_DECLARED` 09-26..10-13, `SEARCH_DECLARATION_SHA256` :76-78). "A later day is cleared only inside `SEARCH_DECLARED` AND with the supplied sha256 equal to the pinned one" (:183-185).
  - Change: add `SEARCH_DECLARATIONS: tuple[SearchDeclaration, ...]` holding (stations, first, last, sha) — row 0 unchanged, row 1 = (MAKER_STATIONS, 10-14, 11-15, Doc A sha). Keep `SEARCH_DECLARED` and `SEARCH_DECLARATION_SHA256` as aliases of row 0.
  - Clearance: the day's containing row must match the supplied sha.
  - Tests (`tests/unit/test_maker_tape_census.py`):
    - `test_second_look_day_cleared_only_with_second_declaration_sha`
    - `test_second_look_day_refused_with_first_declaration_sha`
    - `test_first_block_day_refused_with_second_declaration_sha`
    - `test_day_after_second_look_ceiling_refused`
    - `test_declared_ranges_are_disjoint_and_pinned`
    - `test_nyc_refused_in_second_look`
  - Existing tests (`test_post_freeze_day_outside_declared_range_refused`, `test_post_freeze_day_refused_without_matching_declaration_sha`) stay byte-unchanged and green. If one uses a day in 10-14..11-15 as its "outside" example, that is an L-12 one-row widening, reviewed. It is never a relaxation.
- **C2 — frozen block v2** (`scripts/analysis/maker_stage0_frozen.py`)
  - Today: `LAST_ALLOWED_DAY = 2026-10-13` and `FIRST_REPLAYABLE_CHOICES = (09-18, 09-19)` (:36-37) refuse every block-2 date. See `_check_dates`, :126-127: "`{day} is after {LAST_ALLOWED_DAY}`".
  - Change: add a `FROZEN_DATE_SET_V2` fence parser with constants `SECOND_LOOK_FIRST_DAY` and `SECOND_LOOK_MAX_DAY`, and `rule_dates_v2 = first..min(trigger_day, last_final_day, MAX)`.
  - Refuse: any date ≤ 2026-10-13, NYC, `<FILL`, DRAFT, both fences present, `block_first_day ≠ 10-14`, `trigger_day > MAX`.
  - `FrozenDateSet` gains a `block` field. `verify_set_matches_rule` (:193-216) dispatches on it. The v1 path is byte-identical.
  - Tests (`tests/unit/test_maker_stage0_frozen.py`):
    - `test_v2_block_parses_and_matches_rule`
    - `test_v2_refuses_any_block1_date`
    - `test_v2_refuses_trigger_day_after_cap`
    - `test_v2_refuses_dates_past_trigger_day`
    - `test_amendment_with_both_fences_refused`
    - `test_v1_behaviour_unchanged`: all existing v1 tests untouched.
- **C3 — first-replayable check for v2** (`scripts/analysis/maker_stage0_driver.py:225-229`)
  - Today: equality is required ("first print implies replayable day …"), and the check runs *after* the ledger claim.
  - `first_replayable_day(ns)` returns "day + 1 if first print ≤ 16:50Z else + 2" of the print's date (`maker_stage0_probe_core.py:210-215`). On block days, prints already exist since 09-17, so the result is ≤ 10-14. Equality would raise and **void the one verdict run**.
  - Change: v2 requires `probed ≤ block_first_day`; v1 keeps equality.
  - Tests (`tests/unit/test_maker_stage0_driver.py`):
    - `test_v2_accepts_earlier_first_replayable_day`
    - `test_v2_refuses_later_first_replayable_day`
    - `test_v1_still_requires_equality`
- **C4 — counts-only trigger tool** (new `scripts/analysis/maker_stage0_trigger.py`, < 150 lines)
  - Reads census JSONL rows (`first_seen_ns`, `maker_tape_census.py:448`). Reuses `listed_in_time`, `per_date_counts`, `n_eff_gov` (DRY).
  - Prints only `n_eff_proxy`, the per-date m_d and E. It never prints C, print counts or fields.
  - Tests:
    - `test_trigger_counts_only_covered_early_listed`
    - `test_trigger_day_is_first_crossing_not_check_day`
    - `test_trigger_ignores_days_within_two_of_check_date`
    - `test_trigger_output_has_no_print_or_fill_fields`
    - `test_listed_in_time_agrees_with_probe_listing_abstain`
- **C5 — data-driven D5 disclosure** (`scripts/analysis/maker_stage0_render.py:86`)
  - Today's literal: "days 2026-09-18..2026-09-30 are already past D+14 at run time". For block 2 this would be false.
  - Change: render the block's first and last day and the count of days not yet past D+14 at run time. Report text only.
  - Test `test_d5_disclosure_reflects_the_block_and_d14_status`.
  - The reproducible-block byte-identity test for set-1 CSVs must stay green: render v1 text unchanged when the block is v1.
- **Not changed:** ledger (above); S-7 bound (`assert_delta_within_bound`, `maker_stage0_fill_events.py:227-234`); S-5 abort (`maker_stage0_modes.py:222-224`); every S-* screen test; NO-SEND firewall.
- **Pre-merge sweep (architect brief).** Grep `scripts/analysis/maker_stage0_*.py` for literals `2026, 10, 13`, `2026-09-30` and `2026, 9, 1[89]`. Any hit outside C2/C5 is a defect to fix in the same unit.

## 4. WAIT-period engineering backlog (verdict-blind; no frozen constant re-tuned)

Order: C1 → C2 → C3 → C4 → C5 (must), then W1 (must), then W2–W5 (optional).

- **W1 MUST — preamble and first-print timing enters PROJ.**
  - The procedure's PROJ adds 2×`T_FP` = 2,796 s (`S2_RUN_PROCEDURE_2026-10-14.md:166`). The measured preamble was ≈ 7,800 s (evidence :22, "02:07Z → ≈04:17Z"). The pre-progress stall alert of 6×`T_FP` + 600 = 8,988 s (:199) was only ≈ 1,200 s above the measured 7,800 s.
  - The catalog walk is alphabetical over all instances, so it grows with the tape (L-53).
  - Minimum (no code): the second-look procedure delta sets `PREAMBLE_S = 7,800 × (instances now / instances at run 1)`, uses `PROJ = projected_total_s + PREAMBLE_S`, and sets the stall alert at 1.5×`PREAMBLE_S`.
  - Acceptance: PROJ ≤ 21,600 or STOP before claim.
  - Optional coded form: W2b.
- **W2 OPTIONAL — probe split, then coded preamble bench.**
  - `scripts/analysis/maker_stage0_probe.py` is at 398/400 lines.
  - (a) Pure split: move the first-print scan into `maker_stage0_probe_scan.py` with re-exports. Tests `test_probe_split_reexports_keep_public_import_paths`, plus mutation evidence (L-33: no RED for a characterisation).
  - (b) `--bench` records preamble and first-print wall in `bench.json`. Test `test_bench_reports_preamble_and_first_print_seconds`.
  - Lands before freeze only if both are green. Otherwise W1's procedural form governs.
- **W3 OPTIONAL — DRY the Δ estimators.**
  - `maker_stage0_fill_events.py:208-224` keeps a raw `instance_day_deltas` (same name as `maker_stage0_clock_offset.py:77`). Its `station_day_delta_ns` returns "0 when no sample", which contradicts "None (unknown, NOT zero)" (`clock_offset.py:100-102`). It is off the driver path; its only caller is `tests/unit/test_maker_stage0_fill.py:419-420`.
  - Delete both functions and those test lines. This removes an orphan's own test, not a safety test. `assert_delta_within_bound` stays.
  - Test `test_fill_events_exposes_no_second_delta_estimator`. Safe before freeze.
- **W4 OPTIONAL — `listing_abstain` as a report-only sidecar.**
  - Write `listing_abstain.csv`, not a `station_days.csv` column. A new required column would break `_from_csv` on the set-1 sidecar (`maker_stage0_rows.py:204-206`, "csv is missing required columns") and the byte-identity re-render.
  - Requires a one-row widening of the canonical sidecar set (L-12).
  - Test `test_listing_abstain_sidecar_matches_wp0_abstained_set`.
  - Value: it audits proxy vs n_sd after the run.
- **W5 DEFER — bench `peak_rss + parent_rss` double count.**
  - This is the S-5 abort formula: it "aborts on the largest of the three and on `peak + parent_rss`" (`maker_stage0_modes.py:196-197,222`). It is fail-closed. Changing it touches an S-* screen, so it is not done.
  - At most, a report-only `child_peak_rss_bytes` field, after the verdict.
- **Tail wiring (W6)** is in §5.

## 5. Tail diagnostic routing

- **Why no annotation was emitted: a wiring defect, not a threshold or a switch.**
  - `tail_table` sets `miscalibrated = p_value < ALPHA` (0.05) (`maker_stage0_stats.py:355-366`).
  - The only emitter is `render_verdict` (`maker_stage0_tables.py:127-128`), fed by the verdict run's tail rows. Those are empty by construction (`S2_RUN_PROCEDURE…:271`, "parity is known only after the verdict run").
  - `run_tail` writes the CSV and manifest only and never calls `tail_table` (`maker_stage0_report.py:181-212`).
  - The licensed annotation (amendment :14; procedure :239; plan r3 :44) was therefore unreachable. The label is unaffected, but the procedure promised an output the code cannot produce (L-4).
- **W6 fix (optional, before freeze).** `run_tail` computes `tail_table` and writes `tail_summary.json` (n, expected, observed, p, `miscalibrated`) plus one log line.
  - Test `test_tail_only_emits_annotation_when_exact_test_fails`. Keep `test_tail_annotation_never_changes_the_label` (`tests/unit/test_maker_stage0_verdict.py:794-801`).
  - The recompute on the committed sidecar runs only under Doc B §1 item 5, and is disclosed as an annotation.
- **Disclosure targets** (never a label, refit or spec change):
  1. Already disclosed in `STAGE0_REPLAY_2026-10-16.md:100-111`.
  2. Doc A §10 quotes it.
  3. S5 PREREG `holdout_freeze_disclosure` (`S5_…_r3.md:226`), as a descriptive model-risk note: §6.9 Test A uses `p_yes_point_live` with margin 1.5 (`maker_stage0_stats.py:26`, spec :296). An under-predicted tail biases Test A toward FAIL (kill-first) and the descriptive net expectancy upward. The margin is not changed: spec-frozen, and changing it after this observation would be result-driven.
  4. AUT-4: a contamination note only, because the tail days lie in the NBP holdout read under clause 3 (amendment :64). Exact errata location: see §8.
  - **Explicitly not routed** to FQ-v2 NO-TRADE triggers or any NBP fit or promotion (amendment :58-60).

## 6. Calendar (UTC; earliest feasible; fixed by rule, never moved after seeing data)

| Milestone | Earliest | Gate |
|---|---|---|
| Plan peer review (architect, prediction-market-reviewer, python-reviewer) | 10-16..10-17 | — |
| Doc A FINAL plus Doc B DRAFT committed | 10-18 | peer-converged |
| C1–C5 merged, full gate green; W1 procedure delta committed | 10-20..10-21 | Doc A sha known (C1) |
| Trigger checks: daily at 10:00Z, `RuntimeMaxSec` 3600, counting d ≤ check − 2 | from 10-21 | avoids 02:05Z rotation and 15:10–16:10Z |
| E (trigger day) | ≈ 11-04 best case; ≈ 11-06 at set-1 hole rate; cap 11-15 | rule |
| Truth copy with `last_final_day ≥ E`; final census Stage A [S, E]; Doc B FINAL; CODE_SHA freeze | E + 2 (≈ 11-06..11-08) | procedure Step 3 analogue |
| P2 NBP backfill (cycles 10-13..E; avoid 16:30–17:10Z), verify-first, bench 4 and 8 | E + 2..E + 3 | not into 15:10Z |
| Verdict run launch after 02:05Z, `RTMAX` ≤ 21,600 (run 1: launched 02:07:07Z, hard end 08:07Z) | E + 3..E + 4 (≈ 11-08..11-10) | W1 PROJ |
| Evidence `STAGE0_REPLAY_<date>.md` plus PROGRESS row 2 | same day | — |
| S3 binding run (label ∈ {NOT-KILLED, NOT-KILLED-UNSCREENED} only; also needs S5 WP0a cap pin) | ≈ E + 5 | `RuntimeMaxSec` 18,700 (PROGRESS :64) fits 02:10Z→07:22Z |

- **Truth FINAL lag.** The run reads a pinned read-only copy of `~/.local/share/breezy/derived/fq-truth/truth_cli_finals.csv`, which the truth dataset unit rewrites daily (`deploy/systemd/README.md:1974`; procedure :67-71). The FINAL predicate is `tmax_f` non-empty and `tmax_flag` empty (:72-74). Observed lag: the 10-14 copy's last FINAL day was 10-12 (amendment :28), so about 2 days.
- **Cap path:** if E = 11-15, the verdict lands ≈ 11-19. S5 `holdout_start_date` ≥ 11-17 is still compatible with the S5 r3 :296 "From a 2026-11-23 start".

## 7. Risk register and LESSONS compliance

| # | Risk | Mitigation |
|---|---|---|
| R1 | Venue reverts to late listing, so the trigger never fires | Cap 11-15; a second WAIT goes to a peer ruling; no third block by default |
| R2 | Proxy overstates n_sd (posting is forecast-dependent) | T = 34 margin from set-1 shrink 0.917; W4 audits it |
| R3 | Preamble growth gives an RTMAX kill, then a non-result void | W1 (PROJ STOP before claim); addendum path amendment :73-75 |
| R4 | Memory: bench8 projected 3.72 GB vs 4 GiB (evidence :47) | bench 4 and 8 re-run at the new CODE_SHA; MEMMAX rule unchanged |
| R5 | C3 omitted: the post-claim equality check voids the run | C3 is must-land; Step-2 coordinator check before Doc B FINAL |
| R6 | Firewall cost (≤ 132) delays the EDGE-4 revival | Realised-only accounting; ledger line; RA-13 date firm |
| R7 | Hidden block-1 literals (as `render.py:86` was) | Literal sweep before merge (§3) |
| R8 | Ledger keyed only by sha: a byte-different FINAL copy of the amendment could claim block-1 days | C2 forbids ≤ 10-13 in v2. A v1 copy remains a gap: peer question P-3 |
| R9 | Peers read S3 :149 as licensing pooling | §1 ruling; mandatory peer review |
| R10 | Truth timer fails silently ("Verify a timer's first scheduled run") | Check `last_final_day ≥ E` before Doc B FINAL |
| R11 | θ drift refuses days (`check_theta`, `maker_stage0_preflight.py:156`) | Preflight runs before the claim, so it costs nothing |
| R12 | S-5 pre-screen fires on the block census | Pre-registered STOP; accepted |

LESSONS compliance:
- **L-1** "Validate the Nautilus null hypothesis BEFORE proposing to build": nothing new in Nautilus. All changes are `scripts/analysis` and `src/breezy/analysis` study code, as in S3 r3 §5.
- **L-3** "A plan whose end state is not the goal state is not a plan": every label, including a second WAIT, has a named next action.
- **L-12** "Widen an exact-set barrier, never relax it": C1 and W4.
- **L-34** "The trial's TRIGGER is pinned; a re-look is a second snapshot": the trigger is pinned in Doc A before any read; E is a census property, not a check-day choice.
- **L-38** "A stop rule whose counter cannot increment…": the C4 test shows the counter increments on a qualifying fixture day.
- **L-43** "Two slices that are each green can be jointly broken; gate … after EVERY merge": full gate after each of C1–C5.
- **L-53** "A cache cannot fix an input that never completes": W1.
- **L-56** "A hypothesis picked from a handful of fills…": no pooling.
- **L-4** "A fix is a diff against one finding; a document is a set of claims": C5 and W6.

## 8. Confidence self-assessment

Overall about 0.75.

- **High:** the ledger needs no change; v1 constants block every block-2 date (C2); C3 is necessary; the tail annotation is unreachable rather than mis-thresholded.
- **Medium:** T = 34 (the shrink was measured once, on 48 station-days); the E calendar; that disjoint-only is what peers will endorse.

Unknowns to close in review or in implementation:
- (a) Whether any existing firewall test uses a 10-14..11-15 day as its "outside" example.
- (b) Whether census rows carry any open-window marker (none found in `src/breezy/analysis/maker_tape_census.py`; C4 enforces d ≤ check − 2).
- (c) Other hard-coded block-1 literals beyond `render.py:86` (`TAIL_RANGE` and `VERIFY_FIRST_DAY` are intended).
- (d) Whether `taker_fee_coefficient_as_of` and NBP collector coverage reach November without gaps.
- (e) The AUT-4 errata file location for the contamination note.
- (f) How the preamble scales with instance count.

Questions for the peers:
- **P-1:** disjoint-only, versus pooling under S3 :149.
- **P-2:** realised-only forfeiture, versus the 10-12 :35-36 precedent of forfeiting the full declared range at the first run.
- **P-3:** whether to add a ledger date-overlap guard for v1 copies.