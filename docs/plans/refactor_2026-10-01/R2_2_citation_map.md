# R2.2 citation map

Pre-move `docs/` citations of `scripts/analysis/score_live_trials.py:<line>`,
mapped at the R2.2 move. The symbol is the definition whose pre-move AST span
contained that line (tightest span; a cite in a gap between definitions uses the
nearer neighbour). Stale prose is not rewritten: the line is what was cited, so
the symbol may differ from the name in the surrounding sentence.

`from __future__ import annotations` is not a symbol. Cite ranges that fall in
the module docstring, before any definition, have no owner:

- lines 39-41 inside `score_live_trials.py:39-41,198-201,230-232,289-292,465-468`
- lines 47-60 inside `score_live_trials.py:47-60,161-185`

Every other line in those cites is a row below. Two further hits of the
grep are not line numbers: this file's own `score_live_trials.py:<line>`
placeholder, and `score_live_trials.py:_admit_fill` in
`reviews/PLAN_Rev1_superseded.md` (the symbol is the `_admit_fill` rows).
A same-sentence continuation that drops the filename,
`:677-679,:709-710` in `docs/evidence/RA-5a_residual_sidecar_family_keying_2026-09-27.md`,
sits inside the pre-move `read_filled_trials_state_db` span.

Moved definitions live in `src/breezy/analysis/prereg_admission.py` and are
re-exported from `scripts/analysis/score_live_trials.py`. `fill_time_count.py`
(sqlite-only; no Nautilus import and no catalog) lives in
`src/breezy/analysis/fill_time_count.py` and is re-exported from the script path.
The `catalog.instruments()` walk stays in `score_live_trials.py`.

`script_module` is the attribute's import path after `scripts/analysis` is on
`sys.path`. `new_module` is where that name is bound after the move (the script
module itself when the definition, or a stayed import, was not moved).
`new_location` is that binding's line.

| cite | symbol | script_module | new_module | new_location |
|---|---|---|---|---|
| `score_live_trials.py:1584-1586` | `score_live_trials` | `score_live_trials` | `score_live_trials` | `scripts/analysis/score_live_trials.py:621` |
| `score_live_trials.py:326-465, 1544-1626` | `FillExclusion` | `score_live_trials` | `breezy.analysis.prereg_admission` | `src/breezy/analysis/prereg_admission.py:93` |
| `score_live_trials.py:326-465, 1544-1626` | `_validate_qty` | `score_live_trials` | `score_live_trials` | `scripts/analysis/score_live_trials.py:291` |
| `score_live_trials.py:326-465, 1544-1626` | `_admit_fill` | `score_live_trials` | `breezy.analysis.prereg_admission` | `src/breezy/analysis/prereg_admission.py:124` |
| `score_live_trials.py:326-465, 1544-1626` | `score_live_trials` | `score_live_trials` | `score_live_trials` | `scripts/analysis/score_live_trials.py:621` |
| `score_live_trials.py:326-465, 1544-1626` | `_append_excluded_fills` | `score_live_trials` | `score_live_trials` | `scripts/analysis/score_live_trials.py:889` |
| `score_live_trials.py:379` | `_admit_fill` | `score_live_trials` | `breezy.analysis.prereg_admission` | `src/breezy/analysis/prereg_admission.py:124` |
| `score_live_trials.py:364-376` | `_validate_qty` | `score_live_trials` | `score_live_trials` | `scripts/analysis/score_live_trials.py:291` |
| `score_live_trials.py:364-376` | `_admit_fill` | `score_live_trials` | `breezy.analysis.prereg_admission` | `src/breezy/analysis/prereg_admission.py:124` |
| `score_live_trials.py:449` | `_admit_fill` | `score_live_trials` | `breezy.analysis.prereg_admission` | `src/breezy/analysis/prereg_admission.py:124` |
| `score_live_trials.py:379-446` | `_admit_fill` | `score_live_trials` | `breezy.analysis.prereg_admission` | `src/breezy/analysis/prereg_admission.py:124` |
| `score_live_trials.py:1402-1406` | `score_live_trials` | `score_live_trials` | `score_live_trials` | `scripts/analysis/score_live_trials.py:621` |
| `score_live_trials.py:238-252` | `ProvenanceConflict` | `score_live_trials` | `score_live_trials` | `scripts/analysis/score_live_trials.py:229` |
| `score_live_trials.py:238-252` | `_write_or_assert_live_provenance_sidecar` | `score_live_trials` | `score_live_trials` | `scripts/analysis/score_live_trials.py:233` |
| `score_live_trials.py:530` | `_filled_trial_from_json` | `score_live_trials` | `score_live_trials` | `scripts/analysis/score_live_trials.py:349` |
| `score_live_trials.py:39-41,198-201,230-232,289-292,465-468` | `FillSourceUnreadableError` | `score_live_trials` | `breezy.analysis.prereg_admission` | `src/breezy/analysis/prereg_admission.py:48` |
| `score_live_trials.py:39-41,198-201,230-232,289-292,465-468` | `StorePositiveControlFailedError` | `score_live_trials` | `breezy.analysis.prereg_admission` | `src/breezy/analysis/prereg_admission.py:56` |
| `score_live_trials.py:39-41,198-201,230-232,289-292,465-468` | `_LIVE_PROVENANCE_VALUE` | `score_live_trials` | `score_live_trials` | `scripts/analysis/score_live_trials.py:219` |
| `score_live_trials.py:39-41,198-201,230-232,289-292,465-468` | `_FILL_ORDER_SIDECAR_NAME` | `score_live_trials` | `score_live_trials` | `scripts/analysis/score_live_trials.py:226` |
| `score_live_trials.py:39-41,198-201,230-232,289-292,465-468` | `_MALFORMED_ROW_ERRORS` | `score_live_trials` | `score_live_trials` | `scripts/analysis/score_live_trials.py:283` |
| `score_live_trials.py:39-41,198-201,230-232,289-292,465-468` | `_admit_fill` | `score_live_trials` | `breezy.analysis.prereg_admission` | `src/breezy/analysis/prereg_admission.py:124` |
| `score_live_trials.py:39-41,198-201,230-232,289-292,465-468` | `compute_residual` | `score_live_trials` | `breezy.analysis.prereg_admission` | `src/breezy/analysis/prereg_admission.py:216` |
| `score_live_trials.py:205-220` | `StorePositiveControlFailedError` | `score_live_trials` | `breezy.analysis.prereg_admission` | `src/breezy/analysis/prereg_admission.py:56` |
| `score_live_trials.py:205-220` | `NodeStorePreflightRefused` | `score_live_trials` | `score_live_trials` | `scripts/analysis/score_live_trials.py:200` |
| `score_live_trials.py:245` | `_write_or_assert_live_provenance_sidecar` | `score_live_trials` | `score_live_trials` | `scripts/analysis/score_live_trials.py:233` |
| `score_live_trials.py:466,475,489` | `_admit_fill` | `score_live_trials` | `breezy.analysis.prereg_admission` | `src/breezy/analysis/prereg_admission.py:124` |
| `score_live_trials.py:466,475,489` | `compute_residual` | `score_live_trials` | `breezy.analysis.prereg_admission` | `src/breezy/analysis/prereg_admission.py:216` |
| `score_live_trials.py:466,475,489` | `read_filled_trials_jsonl` | `score_live_trials` | `score_live_trials` | `scripts/analysis/score_live_trials.py:306` |
| `score_live_trials.py:534` | `_filled_trial_from_json` | `score_live_trials` | `score_live_trials` | `scripts/analysis/score_live_trials.py:349` |
| `score_live_trials.py:366-370` | `_validate_qty` | `score_live_trials` | `score_live_trials` | `scripts/analysis/score_live_trials.py:291` |
| `score_live_trials.py:496` | `read_filled_trials_jsonl` | `score_live_trials` | `score_live_trials` | `scripts/analysis/score_live_trials.py:306` |
| `score_live_trials.py:472-474` | `compute_residual` | `score_live_trials` | `breezy.analysis.prereg_admission` | `src/breezy/analysis/prereg_admission.py:216` |
| `score_live_trials.py:554-560` | `_filled_trial_from_json` | `score_live_trials` | `score_live_trials` | `scripts/analysis/score_live_trials.py:349` |
| `score_live_trials.py:554-560` | `read_filled_trials_state_db` | `score_live_trials` | `breezy.analysis.prereg_admission` | `src/breezy/analysis/prereg_admission.py:234` |
| `score_live_trials.py:611,675,689,707,861,1079,1788` | `read_filled_trials_state_db` | `score_live_trials` | `breezy.analysis.prereg_admission` | `src/breezy/analysis/prereg_admission.py:234` |
| `score_live_trials.py:611,675,689,707,861,1079,1788` | `find_unresolved_takes` | `score_live_trials` | `score_live_trials` | `scripts/analysis/score_live_trials.py:425` |
| `score_live_trials.py:611,675,689,707,861,1079,1788` | `main` | `score_live_trials` | `score_live_trials` | `scripts/analysis/score_live_trials.py:1151` |
| `score_live_trials.py:131` | `resolve_store_path` | `score_live_trials` | `score_live_trials` | `scripts/analysis/score_live_trials.py:142` |
| `score_live_trials.py:556` | `read_filled_trials_state_db` | `score_live_trials` | `breezy.analysis.prereg_admission` | `src/breezy/analysis/prereg_admission.py:234` |
| `score_live_trials.py:1803,1813` | `main` | `score_live_trials` | `score_live_trials` | `scripts/analysis/score_live_trials.py:1151` |
| `score_live_trials.py:724-725` | `read_filled_trials_state_db` | `score_live_trials` | `breezy.analysis.prereg_admission` | `src/breezy/analysis/prereg_admission.py:234` |
| `score_live_trials.py:255-295` | `_write_or_assert_live_provenance_sidecar` | `score_live_trials` | `score_live_trials` | `scripts/analysis/score_live_trials.py:233` |
| `score_live_trials.py:255-295` | `_append_fill_order_entries` | `score_live_trials` | `score_live_trials` | `scripts/analysis/score_live_trials.py:252` |
| `score_live_trials.py:255-295` | `_MALFORMED_ROW_ERRORS` | `score_live_trials` | `score_live_trials` | `scripts/analysis/score_live_trials.py:283` |
| `score_live_trials.py:402-525` | `_admit_fill` | `score_live_trials` | `breezy.analysis.prereg_admission` | `src/breezy/analysis/prereg_admission.py:124` |
| `score_live_trials.py:402-525` | `compute_residual` | `score_live_trials` | `breezy.analysis.prereg_admission` | `src/breezy/analysis/prereg_admission.py:216` |
| `score_live_trials.py:402-525` | `read_filled_trials_jsonl` | `score_live_trials` | `score_live_trials` | `scripts/analysis/score_live_trials.py:306` |
| `score_live_trials.py:47-60,161-185` | `_EXCLUDED_FILLS_ARTEFACT_NAME` | `score_live_trials` | `score_live_trials` | `scripts/analysis/score_live_trials.py:168` |
| `score_live_trials.py:47-60,161-185` | `_UNRESOLVED_TAKES_ARTEFACT_NAME` | `score_live_trials` | `score_live_trials` | `scripts/analysis/score_live_trials.py:177` |
| `score_live_trials.py:47-60,161-185` | `_TICK` | `score_live_trials` | `breezy.analysis.prereg_admission` | `src/breezy/analysis/prereg_admission.py:45` |
| `score_live_trials.py:47-60,161-185` | `_TAKEN_REASON` | `score_live_trials` | `score_live_trials` | `scripts/analysis/score_live_trials.py:181` |
| `score_live_trials.py:47-60,161-185` | `_CURRENT_INTENT_KEY` | `score_live_trials` | `score_live_trials` | `scripts/analysis/score_live_trials.py:190` |
| `score_live_trials.py:138-144` | `assert_scored_pairs_are_unit_qty` | `score_live_trials` | `score_live_trials` | `scripts/analysis/score_live_trials.py:149` |
| `score_live_trials.py:138-144` | `score_trials` | `score_live_trials` | `score_live_trials` | `scripts/analysis/score_live_trials.py:150` |
| `score_live_trials.py:138-144` | `TrialDayRecord` | `score_live_trials` | `score_live_trials` | `scripts/analysis/score_live_trials.py:155` |
| `score_live_trials.py:138-144` | `TrialDayRecordCorrupt` | `score_live_trials` | `score_live_trials` | `scripts/analysis/score_live_trials.py:155` |
| `score_live_trials.py:138-144` | `TAKEN_FROM_FILL_WALK_REASON` | `score_live_trials` | `score_live_trials` | `scripts/analysis/score_live_trials.py:153` |
| `score_live_trials.py:722` | `read_filled_trials_state_db` | `score_live_trials` | `breezy.analysis.prereg_admission` | `src/breezy/analysis/prereg_admission.py:234` |
| `score_live_trials.py:1213` | `_read_bucket_facts_by_instrument_id` | `score_live_trials` | `score_live_trials` | `scripts/analysis/score_live_trials.py:107` |
| `score_live_trials.py:557-950` | `read_filled_trials_state_db` | `score_live_trials` | `breezy.analysis.prereg_admission` | `src/breezy/analysis/prereg_admission.py:234` |
| `score_live_trials.py:557-950` | `_admit_one_fill` | `score_live_trials` | `breezy.analysis.prereg_admission` | `src/breezy/analysis/prereg_admission.py:627` |
| `score_live_trials.py:1465-1467` | `score_live_trials` | `score_live_trials` | `score_live_trials` | `scripts/analysis/score_live_trials.py:621` |
| `score_live_trials.py:610` | `read_filled_trials_state_db` | `score_live_trials` | `breezy.analysis.prereg_admission` | `src/breezy/analysis/prereg_admission.py:234` |
| `score_live_trials.py:1789` | `main` | `score_live_trials` | `score_live_trials` | `scripts/analysis/score_live_trials.py:1151` |
| `score_live_trials.py:1161-1187` | `find_unresolved_takes` | `score_live_trials` | `score_live_trials` | `scripts/analysis/score_live_trials.py:425` |
| `score_live_trials.py:1161-1187` | `_with_scheduled_release_at_ns` | `score_live_trials` | `score_live_trials` | `scripts/analysis/score_live_trials.py:556` |
| `score_live_trials.py:1277-1284` | `_bucket_facts_from_instrument_id` | `score_live_trials` | `score_live_trials` | `scripts/analysis/score_live_trials.py:104` |
| `score_live_trials.py:1277-1284` | `_latest_stored_row` | `score_live_trials` | `score_live_trials` | `scripts/analysis/score_live_trials.py:585` |
| `score_live_trials.py:1030-1158` | `_decode_intent_state` | `score_live_trials` | `score_live_trials` | `scripts/analysis/score_live_trials.py:399` |
| `score_live_trials.py:1030-1158` | `find_unresolved_takes` | `score_live_trials` | `score_live_trials` | `scripts/analysis/score_live_trials.py:425` |
| `score_live_trials.py:1527` | `score_live_trials` | `score_live_trials` | `score_live_trials` | `scripts/analysis/score_live_trials.py:621` |
| `score_live_trials.py:360-372` | `_validate_qty` | `score_live_trials` | `score_live_trials` | `scripts/analysis/score_live_trials.py:291` |
| `score_live_trials.py:133-138` | `BucketSource` | `score_live_trials` | `score_live_trials` | `scripts/analysis/score_live_trials.py:145` |
| `score_live_trials.py:133-138` | `FilledTrial` | `score_live_trials` | `score_live_trials` | `scripts/analysis/score_live_trials.py:146` |
| `score_live_trials.py:133-138` | `ScoredTrial` | `score_live_trials` | `score_live_trials` | `scripts/analysis/score_live_trials.py:147` |
| `score_live_trials.py:133-138` | `ScoreRefusal` | `score_live_trials` | `score_live_trials` | `scripts/analysis/score_live_trials.py:148` |
| `score_live_trials.py:133-138` | `assert_scored_pairs_are_unit_qty` | `score_live_trials` | `score_live_trials` | `scripts/analysis/score_live_trials.py:149` |
| `score_live_trials.py:1519` | `score_live_trials` | `score_live_trials` | `score_live_trials` | `scripts/analysis/score_live_trials.py:621` |
| `score_live_trials.py:877-891` | `read_filled_trials_state_db` | `score_live_trials` | `breezy.analysis.prereg_admission` | `src/breezy/analysis/prereg_admission.py:234` |
| `score_live_trials.py:1450-1468` | `score_live_trials` | `score_live_trials` | `score_live_trials` | `scripts/analysis/score_live_trials.py:621` |
| `score_live_trials.py:361-1588` | `_validate_qty` | `score_live_trials` | `score_live_trials` | `scripts/analysis/score_live_trials.py:291` |
| `score_live_trials.py:361-1588` | `_admit_fill` | `score_live_trials` | `breezy.analysis.prereg_admission` | `src/breezy/analysis/prereg_admission.py:124` |
| `score_live_trials.py:361-1588` | `compute_residual` | `score_live_trials` | `breezy.analysis.prereg_admission` | `src/breezy/analysis/prereg_admission.py:216` |
| `score_live_trials.py:361-1588` | `read_filled_trials_jsonl` | `score_live_trials` | `score_live_trials` | `scripts/analysis/score_live_trials.py:306` |
| `score_live_trials.py:361-1588` | `_filled_trial_from_json` | `score_live_trials` | `score_live_trials` | `scripts/analysis/score_live_trials.py:349` |
| `score_live_trials.py:361-1588` | `read_filled_trials_state_db` | `score_live_trials` | `breezy.analysis.prereg_admission` | `src/breezy/analysis/prereg_admission.py:234` |
| `score_live_trials.py:361-1588` | `_admit_one_fill` | `score_live_trials` | `breezy.analysis.prereg_admission` | `src/breezy/analysis/prereg_admission.py:627` |
| `score_live_trials.py:361-1588` | `UnresolvedTake` | `score_live_trials` | `score_live_trials` | `scripts/analysis/score_live_trials.py:376` |
| `score_live_trials.py:361-1588` | `_decode_intent_state` | `score_live_trials` | `score_live_trials` | `scripts/analysis/score_live_trials.py:399` |
| `score_live_trials.py:361-1588` | `find_unresolved_takes` | `score_live_trials` | `score_live_trials` | `scripts/analysis/score_live_trials.py:425` |
| `score_live_trials.py:361-1588` | `_with_scheduled_release_at_ns` | `score_live_trials` | `score_live_trials` | `scripts/analysis/score_live_trials.py:556` |
| `score_live_trials.py:361-1588` | `_read_bucket_facts_by_instrument_id` | `score_live_trials` | `score_live_trials` | `scripts/analysis/score_live_trials.py:107` |
| `score_live_trials.py:361-1588` | `_bucket_facts_from_instrument_id` | `score_live_trials` | `score_live_trials` | `scripts/analysis/score_live_trials.py:104` |
| `score_live_trials.py:361-1588` | `_latest_stored_row` | `score_live_trials` | `score_live_trials` | `scripts/analysis/score_live_trials.py:585` |
| `score_live_trials.py:361-1588` | `_already_fallback_scored` | `score_live_trials` | `score_live_trials` | `scripts/analysis/score_live_trials.py:595` |
| `score_live_trials.py:361-1588` | `_next_score_seq` | `score_live_trials` | `score_live_trials` | `scripts/analysis/score_live_trials.py:600` |
| `score_live_trials.py:361-1588` | `_unchanged_since_last_score` | `score_live_trials` | `score_live_trials` | `scripts/analysis/score_live_trials.py:605` |
| `score_live_trials.py:361-1588` | `score_live_trials` | `score_live_trials` | `score_live_trials` | `scripts/analysis/score_live_trials.py:621` |
| `score_live_trials.py:361-1588` | `_append_excluded_fills` | `score_live_trials` | `score_live_trials` | `scripts/analysis/score_live_trials.py:889` |
| `fill_time_count.py:84` | `_open_readonly` | `fill_time_count` | `breezy.analysis.fill_time_count` | `src/breezy/analysis/fill_time_count.py:84` |
| `fill_time_count.py:101` | `count_filled_takes` | `fill_time_count` | `breezy.analysis.fill_time_count` | `src/breezy/analysis/fill_time_count.py:101` |
| `fill_time_count.py:81` | `_TAKEN_REASON` | `fill_time_count` | `breezy.analysis.fill_time_count` | `src/breezy/analysis/fill_time_count.py:81` |
