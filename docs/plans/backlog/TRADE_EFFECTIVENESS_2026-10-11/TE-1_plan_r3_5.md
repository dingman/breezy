# TE-1 plan r3.5 (coordinator merge over r3.4: round-4 reviews)

Delta over `TE-1_plan_r3_4.md`, which stays binding except where amended here. Reviews: `reviews/TE-1-r4-domain.md` (80 RWC), `reviews/TE-1-r4-python.md` (84 RWC), `reviews/TE-1-r4-architecture.md` (88 REQUEST_CHANGES). No BLOCKER. Every HIGH/MED is applied below; LOWs applied where text-sized.

## Contradictions resolved
- **Pins (python H1 vs r3.4 blast radius).** The reviewer is right that no `aut2.label` pin exists *today* (`pins.py:19-21`, `test_autonomy_pins.py:101`); r3.3 WP-A is the step that *creates* it (widening `:101` to `{"aut6.health","aut2.label"}`). So `attribution.py` enters the NEW `aut2.label` closure through `unit_wiring`, and that pin is cut once, after R11 code lands. Unknown 1 is RESOLVED: `attribution.py` is NOT in the `aut6.health` closure (`closure_manifest.py` single entry `breezy.runtime.autonomy_health_cli`, no `labeling` member). Coordinator ran `regen_closure_manifest.py --check` on 32a07f87+: exit 0. The `breezy-portfolio-roi` unit pins no closure, so WP-B's import needs no second re-pin.
- **Strict-vs-straddle ordering (arch MED vs python H2 / domain F3).** The arch reviewer asked that a strict single match beat a straddle candidate; the domain and python reviewers showed that this silently relabels a predecessor's D+1 fill to a successor. Resolution: **fail closed** (R11.5 below). Both concerns are tested: the ordering mutation is still caught, and the successor conflict is UNRESOLVED instead of silently wrong.

## R11 amendments
- **R11.1 implementation shape (python L5).** `_bridge_family` keeps its signature and byte-identical body. NEW private `_straddle_family(fill, manifests, climate_day, trial_key_exists) -> str | None` is called by `backfill_family` only when the bridge returns `None`. NEW public pure predicate `post_terminal_straddle(manifest, climate_day, ts_event_ns) -> bool` covers the date/ts conditions only (stated as such in its docstring). `BridgeBasis(StrEnum)` = `FOLD`, `BRIDGE`, `BRIDGE_POST_TERMINAL`; `PreEpochAttribution.basis` defaulted to `BRIDGE`; `backfill_family` sets `FOLD` when the fold wins.
- **R11.2 latch check reuse (python L1).** The straddle is reached only after the single existing `:225` key check; `trial_key_exists` is never called a second time (keeps `test_aut2_attribution.py:285-302` green unedited).
- **R11.3 ts window (domain F2).** Condition 4 becomes `terminal 00:00Z <= fill.ts_event < (terminal + 1 day) 00:00Z`. `fill.ts_event` (not `latched_at_ns`) is used: fill ≥ latch, so it is the stricter bound and needs no signature change (arch LOW). Integer-ns compare against `datetime(..., tzinfo=UTC)`; `terminal_climate_day` parsed with `date.fromisoformat` (python L6).
- **R11.4 timezone assumption (domain F9).** UTC midnight precedes local midnight for UTC−4..UTC−10, which covers every PM.us and Kalshi US station; a test asserts the station set's offsets fall in that range.
- **R11.5 successor conflict (python H2, domain F3).** If the straddle conditions hold for a predecessor manifest P AND the strict set is a single *different* family S, `backfill_family` returns `Unresolved("straddle_successor_conflict")` (CRITICAL through the existing unresolved path). Today unreachable (one FQ manifest, P39). Registering any second FQ-kind manifest is a trigger to re-run S0-2 (noted in Risks).
- **Option 3 sentence (domain F6).** A separate "post-terminal" bucket was weighed and rejected: the boot manifest had no terminal key (P40), so v1 is the sender of record; a separate bucket would make FQ report 20 / ≠ −2.17 against a sender that placed 25 orders.

## New premises
- **P43 (domain F8, python, arch).** `fq_scorer._draft` / `_reason` (`fq_scorer.py:284-313`) perform no manifest or window check; `_rung_id` and `_score` use instrument facts only; `label_family_of` returns the storage key. Only `attribution.py:233-234` in `analysis/labeling` reads `d0_climate_day` / `terminal_climate_day`. Unknown 2 RESOLVED.
- **P44 (python L4).** `portfolio_roi_report.py:101` already imports `legacy_crh_scorer`, which imports `attribution` (`legacy_crh_scorer.py:22`); a direct import adds no new edge. `portfolio_roi_report.py:95` exec-client import is already pinned.
- **P41 restated (domain F1).** Admission is blocked three ways: `PreEpochAttribution.admissible=False` + `UNATTRIBUTED` (`attribution.py:111-119`); `fq_scorer._finish` requires `p_source is C1_DECISION` (`:261-266`); `score_live_trials.py:1142` passes `until_climate_day=terminal`. WP-A must attach the ripgrep list of every `LabelRow.family_id` reader and show each filters `admissible` (or is a P&L-only consumer).

## WP-A edits (adds to r3.4)
- **Stub shape (python M1).** The stub ships `BridgeBasis`, `PreEpochAttribution.basis` (defaulted), `post_terminal_straddle` (returns `False`) and `_straddle_family` (returns `None`), so no test fails on import.
- **RED vs positive controls (python M1).** RED (fail on assertion under the stub): `test_post_terminal_straddle_bridges_with_basis`, `test_backfill_fold_basis_is_fold`, `test_planner_post_terminal_fq_fills_bridge_to_v1_and_count_logged`, `test_legacy_join_matches_latch_row_with_null_venue_order_id`. The negative tests (`…after_terminal_day_end…`, `…two_days_past…`, `…relaxed_ambiguity…`, `…never_falls_through…`, `…requires_stored_latch_key`, `…open_manifest_never_takes_straddle_branch`) are **positive controls, expected green at RED**; each must be shown failing against a named one-line mutation in the return.
- **New tests:**
  - `test_post_terminal_fill_before_terminal_day_start_is_unresolved` (R11.3 lower bound; mutation: drop the lower bound).
  - `test_strict_single_match_wins_when_no_straddle_candidate` (arch MED: v2 strict, no predecessor straddle → v2 `BRIDGE`; mutation: straddle-before-strict).
  - `test_straddle_successor_conflict_is_unresolved` (R11.5: v1 terminal 10-05, v2 d0 10-06, fill 10-06 at 10-05T17:00Z → `Unresolved("straddle_successor_conflict")`).
  - `test_station_utc_offsets_within_straddle_assumption` (R11.4).
  - `test_post_terminal_rows_excluded_from_every_label_consumer` (domain F1): over the 34-fill fixture, adding/removing the 5 rows changes no admissible tally, PREREG input or M1-v3 input builder output; only the P&L consumer changes.
- **L-55 (arch MED).** `test_planner_post_terminal_fq_fills_bridge_to_v1_and_count_logged` uses the production `latch_key_exists` against a real SQLite store written by `PersistentQuantileLadderLatch.latch` (`test_aut2_attribution.py:342-346` pattern), never a lambda; 10-06 slug, ts 10-05T17:00Z, `terminal_climate_day="2026-10-05"` override.
- **Fixtures (python M3).** New tests build fills via `tests/support/aut2_fixtures.py` (`durable_fill`), never a direct `exec.client` import (x1 set-equality pin, `test_execution_egress_firewall_guard.py`).
- **AST guard (python M4).** No code outside `attribution.py` reads `.storage_key` (`test_aut2_attribution.py:305-320`): the planner reads `.basis`; WP-B reads `LabelRow.family_id`.
- **Pins.** `regen_closure_manifest.py --check` stays a no-op assertion for `aut6.health`; the new `aut2.label` pin is cut in WP-A's re-pin commit after the R11 code lands.

## WP-B edits (adds to r3.4)
- **Basis recompute scope (arch HIGH, python M2).** WP-B calls `post_terminal_straddle` only for rows whose `LabelRow.family_id` equals the manifest it passes and whose climate day equals that manifest's `terminal + 1`; the plan states the predicate covers the date/ts conditions only. NEW RED `test_label_and_report_post_terminal_sets_identical`: on the 34-fill fixture, the 5 `fill_key_sha` the labeler logs equal, as a set, the 5 the report books as `pre_epoch_bridge_post_terminal`. A non-empty fold registry re-opens this rule (noted in Risks).
- **Disclosures (domain F4, F5).** Add `post_terminal_pnl` and `post_terminal_wins=0` beside `n_post_terminal_bridge`, with the text: "sent by the live v1 node after the failed 10-05 halt; included in family P&L; excluded from the v1 tally by the terminal window (`score_live_trials.py:1142`)". The disclosure and test docstring state that `n_no_fill_intents` and `n_post_terminal_bridge` are unrelated counts.
- **Cross-report note (domain F7, arch LOW).** `position_monitor_nightly_report` and `score_live_trials` deliberately still window-resolve the 5 to UNKNOWN / out-of-tally; `post_terminal_ref` is the reconciling disclosure; those reports are unchanged (P41).
- **Focused gate (arch LOW).** WP-B's focused gate adds `cd <tree> && lint-imports` ("N kept, 0 broken") and `test_execution_egress_firewall_guard.py`.

## Risks (adds)
- A second FQ-kind manifest makes R11.5 reachable → re-run S0-2 before any relabel.
- A non-empty fold registry can make labeler basis (`FOLD`) and report basis diverge → `test_label_and_report_post_terminal_sets_identical` fails first; re-open WP-B rule.

## Unknowns
None open from r3.4 (both resolved above).
