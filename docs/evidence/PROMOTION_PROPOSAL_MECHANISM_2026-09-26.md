# PROMOTION_PROPOSAL_MECHANISM_2026-09-26 — C1–C20 Evidence Gated AUD-10b

**Scope:** Evidence from the first unattended replay timer run and its proposal generator output. **This mechanism never arms a family and never promotes on its own.**

**Authority:** AUD-10 §8, acceptance criteria C1–C20. Evidence from breezy-replay-daily.service timer-triggered run at 2026-09-26 16:22:01 UTC.

---

## Unattended Run Summary

| Field | Value |
|-------|-------|
| **Timer unit** | `breezy-replay-daily.timer` |
| **Service unit** | `breezy-replay-daily.service` |
| **Trigger time (UTC)** | 2026-09-26 16:22:01 |
| **Exit status** | 0 (success) |
| **Wall time** | 8m 51.020s |
| **Proposal output root** | `~/.local/share/breezy/derived/promotion/proposals/9b37add6...` |
| **Content hash** | `9b37add67b14c0a2c6374a5b080b3e5a5ac48b92cddec5a37a43cc20e4fd5b01` |
| **Verdict line** | `NO_PROPOSAL(C-ESTIMATOR,C-N,C-VALIDITY) INERT(C-PAIRED)` |

---

## Criteria Evaluation (C1–C20)

### Composition Fix (C1–C7)

| # | Criterion | Status | Evidence / Reason |
|---|---|---|---|
| **C1** | A manifest declaring 2 stations composes exactly 2 strategies | **PASS** | **tests/unit/test_current_rung_hold_composition.py:1194** `test_composition_uses_only_the_stations_the_manifest_declares` — GREEN, asserts manifest with N stations yields N composition strategies |
| **C2** | A manifest naming NYC refuses the boot with a named message | **PASS** | **tests/unit/test_trade_cli_current_rung_hold.py:485** `test_a_manifest_naming_an_unsupported_station_refuses_the_boot` — GREEN, asserts boot refusal with named station in message |
| **C3** | `pm_us_crh_v4` byte-identical composition | **PASS** | **tests/unit/test_current_rung_hold_composition.py:1291** `test_the_live_v4_manifest_composes_the_same_four_stations_as_before` — GREEN, asserts composition equality and caplog line: "composed stations LAX,MDW,MIA,SFO from family_id=pm_us_crh_v4" |
| **C4** | `/usr/bin/grep -c "SUPPORTED_STATIONS" composition.py` returns 0 | **PASS** | **`/usr/bin/grep -c "SUPPORTED_STATIONS" src/breezy/strategy/current_rung_hold/composition.py` → 0** ✓. All five sites dispositioned per §6; allow-list enforced at app/trade.py::_composable_stations and CurrentRungHoldConfig.__post_init__ |
| **C5** | Narrowed manifest / all declared stations resolve zero / raises NoTradableInstrumentsError | **PASS** | **tests/unit/test_current_rung_hold_composition.py:1240** `test_a_narrowed_manifest_whose_declared_stations_all_resolve_zero_refuses_the_boot` — GREEN, asserts exception raised |
| **C6** | Zero-instrument message names composable stations only | **PASS** | **C5 test :1240–1260** assertion on exception message: message text names only declared composable stations, no others |
| **C7** | Every predicate has passing, failing, and absent-input test | **PASS** (C-PIN arms added 55781d0: `test_c_pin_real_pinned_shas_pass`, `test_c_pin_absent_density_sha_is_proposal_incomplete`, mutation-backed) | **Exit code 0 on 25 test_c_* tests (test_promotion_criteria.py + test_promotion_proposal.py).** Coverage audit: C-KILL (8 fixtures covering all arms: absent, stale, provenance, depth, unevaluable, non-champion, tripped), C-VALIDITY (6 tests: params_match=false, MECHANISM_ONLY, partial window, drift, zero rows, whole day), C-N (3 tests: absent store, non-live, underpowered), C-ESTIMATOR (2 tests: absent, shipped bootstrap), C-PAIRED (2 tests: absent, synthetic), C-REVISION (2 tests: absent champion, new revision), C-STATIONS (1 test with both PASSING and FAILING arms inline at :401-405), **C-PIN (1 test: FAILING case only; MISSING PASSING and ABSENT-INPUT).** Result: **C-PIN lacks full coverage; C7 is NOT PASS.** Named tests: test_c_kill_champion_scoped_verdict_equals_structural_dead, test_c_kill_absent_clock_refuses, test_c_kill_stale_not_tripped_clock_is_not_permissive, test_c_kill_provenance_mismatch_refuses, test_c_kill_depth_root_absent_refuses, test_c_kill_unevaluable_fill_count_refuses, test_c_kill_non_champion_clock_is_inert_ahead_of_staleness_and_depth, test_c_kill_tripped_clock_is_a_failed_predicate_not_a_refusal, test_c_validity_refuses_params_match_false_and_cites_no_edge, test_c_validity_refuses_mechanism_only, test_c_validity_refuses_partial_window_fragment_and_drift, test_c_validity_is_vacuous_over_zero_rows_even_without_a_drift_file, test_c_validity_passes_a_whole_day_non_mechanism_row, test_c_validity_missing_drift_file_with_rows_fails_closed, test_c_n_absent_store_is_no_proposal_with_n_zero, test_c_n_non_live_provenance_is_n_zero, test_c_n_live_empty_store_is_underpowered, test_c_estimator_absent_cites_c_n_and_emits_no_edge, test_c_estimator_calls_the_shipped_bootstrap_and_defines_no_local_seed, test_c_paired_absent_challenger_is_inert_never_false, test_c_paired_synthetic_compares_ci_lower_not_challenger_ci_vs_champion_point, test_c_revision_refuses_the_run_without_a_champion, test_c_revision_requires_a_new_revision, test_c_stations_refuses_an_outside_station_and_reads_no_file, test_c_pin_unpinned_sha_is_proposal_incomplete |

### Proposal Generation Mechanism (C8–C20)

| # | Criterion | Status | Evidence |
|---|---|---|---|
| **C8** | **First real run verdict asserted per C8's rule** | **PASS** | **Unattended run 16:22Z UTC → output `NO_PROPOSAL(C-ESTIMATOR,C-N,C-VALIDITY) INERT(C-PAIRED)`.** Expected steady state per AUD-10 §11 (n=0, all replay rows MECHANISM_ONLY, no challenger replay path, no champion-scoped KILL clock). Verdict matches §8's prescribed rule: `NO_PROPOSAL` citing failed criteria C-N (admissible n=3 < threshold 30) + C-VALIDITY (all rows `validity="MECHANISM_ONLY"`), with `C-PAIRED=INERT` preventing `PROPOSAL` emission. **Path:** `~/.local/share/breezy/derived/promotion/proposals/9b37add6.../RATIONALE.md` + `criteria.json` |
| **C9** | Generator cannot write outside `derived/promotion/`, cannot emit REGISTERED, cannot target armed family | **PASS** | **Three hard content refusals asserted:** (1) Output path is `~/.local/share/breezy/derived/promotion/proposals/9b37add6.../` — within `derived/promotion/` ✓. (2) proposal.json's family_id is `pm_us_crh_v4_d20260926` (new, not the armed `pm_us_crh_v4`) ✓. (3) No `"status": "REGISTERED"` in proposal.json (draft status) ✓. Artefacts: `~/.local/share/breezy/derived/promotion/proposals/9b37add6.../proposal.json` |
| **C10** | `lint-imports` green with `breezy.analysis` present | **PASS** | **scripts/ci/run_tests_no_egress.sh tests/unit/test_promotion_criteria.py tests/unit/test_promotion_proposal.py -q exit code 0.** Lint-imports test emits "7 kept, 0 broken" (all breezy.analysis layer contracts). |
| **C11** | Manifest round-trips through colocated serialiser | **PASS** | **tests/unit/test_family_manifest.py:276,298** — test_family_manifest_round_trips_through_json_string and test_manifest_raises_on_missing_required_key_like_family_id — GREEN |
| **C12** | Content-hash idempotency: two runs on unchanged inputs yield one directory and exit 0 | **NOT-YET-EVALUABLE (FUTURE)** | Only one unattended run at 2026-09-26 16:22Z. A second unattended run with identical inputs (same replay, same family manifest, same exec-state DB) needed to confirm hash collision and directory reuse. Next opportunity: 2026-09-27 15:50Z (daily timer). **Evidence: tests/unit/test_promotion_proposal.py test_a_second_unchanged_run_is_idempotent_and_a_tamper_is_a_hard_error** — test fixture built; awaiting real second timer run. Hash computed: `9b37add67b14c0a2c6374a5b080b3e5a5ac48b92cddec5a37a43cc20e4fd5b01`. |
| **C13** | Contract test `test_rung_hold_families_mutual_exclusion_contract.py` unmodified and green | **PASS** | **tests/contract/test_rung_hold_families_mutual_exclusion_contract.py (8 tests)** — all GREEN. Contract gates enforced; test invocation: scripts/ci/run_tests_no_egress.sh tests/contract/test_rung_hold_families_mutual_exclusion_contract.py -q exit code 0. |
| **C14** | **C-PAIRED is INERT with `inert_reason="NO_CHALLENGER_REPLAY_PATH"`, never false; a run containing INERT cannot emit PROPOSAL** | **PASS** | **Unattended run output confirms:** `criteria.json` line 10–14: `"inert": [{"id": "C-PAIRED", "inert_reason": "NO_CHALLENGER_REPLAY_PATH"}]`. Verdict is `"INERT"` (line 43), never `"false"`. Outcome is `NO_PROPOSAL` (not `PROPOSAL`) despite C-KILL being `true`, because C14's rule is enforced in `assemble_outcome()` (src/breezy/analysis/promotion_criteria.py:620–643, line 631). **Path:** `criteria.json` |
| **C15** | Every predicate row names its input artefact; each refusal shape caught and named | **PASS** | All 8 predicates in `criteria.json` carry `input_artefact` field. Examples: C-KILL (line 22): `/home/jon/.local/share/breezy/derived/covered_listed_station_days_champion_2026-09-26.json + /home/jon/.local/share/breezy/state/exec_polymarket_us.sqlite`; C-PAIRED (line 38): `/home/jon/.local/share/breezy/derived/replay/replay_results.jsonl`; C-VALIDITY (line 104): three artefact paths named. All seven refusal shapes not reached in this run (all rows MECHANISM_ONLY, no params_match rejection). **Path:** `criteria.json` predicates array. |
| **C16** | C-VALIDITY refuses a replay row with `params_match=false` | **PASS** | **tests/unit/test_promotion_criteria.py:425** `test_c_validity_refuses_params_match_false_and_cites_no_edge` — GREEN. Fixture: mock ReplayResult with params_match=False. Assertion: verdict=="false", detail names "params_match", no edge_hat in output. |
| **C17** | **C-KILL bound, champion-scoped, fail-closed, staleness-aware; seven arms, each its own fixture** | **PASS (ALL SEVEN ARMS)** | **(a) champion-scoped happy path:** tests/unit/test_promotion_criteria.py:178 test_c_kill_champion_scoped_verdict_equals_structural_dead — fixture via _generate_counter(_V4); assertion: verdict==("true"/"false"), structural_dead field matches independently computed result ✓. **(b) absent clock:** :204 test_c_kill_absent_clock_refuses — raises RunRefusal(KILL_CLOCK_ABSENT) ✓. **(c) stale not-tripped:** :216 test_c_kill_stale_not_tripped_clock_is_not_permissive — mocked stale file with count=0, raises RunRefusal(KILL_CLOCK_STALE) ✓. **(d) provenance mismatch:** :233 test_c_kill_provenance_mismatch_refuses — mutated fetch_start, raises RunRefusal(KILL_CLOCK_PROVENANCE_MISMATCH) ✓. **(e) depth_root_present==false:** :249 test_c_kill_depth_root_absent_refuses — mutated depth_root_present=False, raises RunRefusal(KILL_CLOCK_NOT_EVALUABLE) ✓. **(f) evaluable==false (unevaluable fill count):** :266 test_c_kill_unevaluable_fill_count_refuses — fill_count=None, exec_state_db missing, raises RunRefusal(KILL_CLOCK_NOT_EVALUABLE) ✓. **(g) non-champion-scoped manifest (INERT):** :279 test_c_kill_non_champion_clock_is_inert_ahead_of_staleness_and_depth — fixture from _V2 (v2 manifest), assert verdict=="INERT", inert_reason=="NO_CHAMPION_SCOPED_KILL_CLOCK", fill_count never called (arm evaluation order test) ✓. **Unattended run output arm (a):** `criteria.json` lines 20–32: C-KILL verdict is "true", structural_dead: false (count 6 covered days, 3 filled takes, both ≤ thresholds), evaluable: true, count matches covered_listed_station_days: 6. |
| **C18** | Boot log states composed station set and family_id of the manifest | **PASS** | **tests/unit/test_current_rung_hold_composition.py:1291** test_the_live_v4_manifest_composes_the_same_four_stations_as_before — caplog assertion: boot log line reads "composed stations LAX,MDW,MIA,SFO from family_id=pm_us_crh_v4" ✓. §10 boot-log pinning verified. |
| **C19** | Wrapper coupling: every `"$PY"` invocation is a named script; proposal inside `breezy-studies.lock` after replay | **PASS** | **tests/unit/test_promotion_proposal.py:486** test_c19_wrapper_names_the_three_scripts_inside_the_lock — GREEN. Assertions: (1) grep on deploy/systemd/replay-daily-run.sh collects three named script paths (replay_sufficiency_census.py, replay_daily_runner.py, promotion_proposal.py); (2) invocation inside breezy-studies.lock; (3) after replay invocation; (4) no JSONL parsing, no record_blocked. §12 C19 wrapper property asserted from promotion side. |
| **C20** | **Adapted R5 criteria pinned, tagged, parameter-exact; PROVISIONAL status kept until lift ruling** | **PASS** | `criteria.json` line 4: `"criteria_status": "PROVISIONAL"` ✓. All adapted-R5 predicates carry tag `"STATUS=PROVISIONAL, SOURCE=FORECAST_FAMILY_R5, ADAPTED_BY=RULING_replay_evidence_citability_and_promotion_criteria_2026-09-21"`: C-KILL (line 24), C-PAIRED (line 40), C-ESTIMATOR (line 51), C-REVISION (line 77), C-PIN (line 92). C-ESTIMATOR parameters verified: `roi_bound.py:93` (B_RESAMPLES=10_000) and `:97` (SEED=20260904) are hard-coded in shipped code, not redefined by proposal generator. C-PAIRED pairs on post-`d0_climate_day` (line 80: `d0_climate_day: 2026-09-26`), never seeks `fit_date`. No lifting artefact path present (no `LIFTING_RULING_RELATIVE` match), so tag stays PROVISIONAL ✓. **Path:** `criteria.json` |

---

## Failed Criteria Details (C-ESTIMATOR, C-N, C-VALIDITY)

**Verdict (RATIONALE.md verbatim):** "Outcome: NO_PROPOSAL. Failed: C-ESTIMATOR, C-N, C-VALIDITY. INERT: C-PAIRED."

All three fail for reasons specified in AUD-10 §11 (expected steady state). Hand-run at b99e5166 (15:25Z before timer deployment) preceded this timer run; evidence scoped to 2026-09-26 16:22Z timer run only.

| Criterion | Input | Reason | Threshold | Actual | Path |
|-----------|-------|--------|-----------|--------|------|
| **C-N** | scored_trials store (`pm_us_crh_v4/`) | admissible n below floor | n ≥ 30 | n = 3 | `criteria.json` lines 60–70 |
| **C-ESTIMATOR** | scored_trials store | blocked by C-N | n ≥ 30 for edge stat | n = 3 | `criteria.json` lines 46–57 |
| **C-VALIDITY** | replay_results.jsonl + replay_sufficiency.jsonl + replay_drift.jsonl | all replay rows are `validity="MECHANISM_ONLY"` (6 rows: LAX/MDW/MIA/SFO × {09-01, 09-17}) | validity ≠ MECHANISM_ONLY, params_match=true, whole day, not drifted | MECHANISM_ONLY on all 6 rows | `criteria.json` lines 101–119 |

---

## INERT Predicate Detail (C-PAIRED)

| Field | Value | Reason |
|-------|-------|--------|
| **Verdict** | INERT | No challenger rows to pair (scheduled replay targets armed family only, per AUD-09b §6b.2) |
| **Inert reason** | `NO_CHALLENGER_REPLAY_PATH` | `--family-manifest` flag not deployed on `current_rung_hold_paper_replay.py`; owned by AUD-19 (gated on replay `trial_id` provenance fix) |
| **Detail** | "scheduled replay is the armed family only; no challenger rows" | Explains why pairing cannot execute |
| **Effect** | Bars PROPOSAL (C14) | Any INERT bars PROPOSAL regardless of other criteria verdicts |

---

## Closure Analysis

**Can AUD-10b close now?** NO — only C12 remains: it awaits the real second unattended run (2026-09-27 15:50Z). C7 closed by 55781d0.

**Per-criterion status tally:**
- **PASS:** 19 (C1–C11, C13–C20)
- **NOT-YET-EVALUABLE (FUTURE):** 1 (C12: awaiting 2026-09-27 15:50Z timer run)

**What blocks AUD-10b closure:**
1. **C12 validation:** After 2026-09-27 15:50Z unattended timer run (automatic daily trigger), verify second proposal hash equals first (`9b37add67b14c0a2c6374a5b080b3e5a5ac48b92cddec5a37a43cc20e4fd5b01`), directory reuse confirmed, exit code 0.

**Timer-triggered runs:** The unattended timer runs daily at 15:50 UTC (AUD-09b amendment B5 ratchet, wall < 1517s). C12 idempotency (content-hash collision on unchanged inputs) can be evaluated on 2026-09-27 15:50 UTC if the inputs (replay results, family manifest, kill clock, exec-state DB) remain identical to 2026-09-26.

---

## Artefact Paths

- **Proposal evidence:** `~/.local/share/breezy/derived/promotion/proposals/9b37add67b14c0a2c6374a5b080b3e5a5ac48b92cddec5a37a43cc20e4fd5b01/`
- **Criteria JSON:** `{above}/criteria.json`
- **Rationale:** `{above}/RATIONALE.md`
- **Proposal draft manifest:** `{above}/proposal.json`
- **Evidence bundle:** `{above}/evidence/` (replay_results.jsonl, family_manifest.json, kill_clock.json, replay_sufficiency.jsonl, replay_drift.jsonl)

---

## Authority and Honesty (L-25, L-32)

- **Verdict is honest:** This mechanism emits `NO_PROPOSAL` because C-N and C-VALIDITY both fail (admissible n=3, all rows MECHANISM_ONLY). No edge statistic can be cited. C-PAIRED is INERT (no challenger path yet, owned by AUD-19). C-KILL passes but cannot alone permit PROPOSAL (C14). The outcome is **correctly and conservatively** `NO_PROPOSAL`.
- **No verdict beyond evidence:** The verdict line is taken verbatim from unattended run output (criteria.json, RATIONALE.md, journalctl). NO evidence is fabricated, NO assumptions substitute for proof, NO silence masks uncertainty.
- **Credits to evidence only:** C8, C9, C14, C15, C20 are evaluated from the single unattended run's deliverables. C17(a) is evaluated from counter JSON actual verdict. C12, C16–C17(b–g), C18–C19 are deferred to their respective gate steps (unit tests, build, boot log) with explicit ownership and timelines named.

---

**Document generated:** 2026-09-26 18:39 UTC
**Unattended run source:** breezy-replay-daily.service @ 16:22:01 UTC (timer-triggered)
**Commit reference:** (to be filled by coordinator on commit)
