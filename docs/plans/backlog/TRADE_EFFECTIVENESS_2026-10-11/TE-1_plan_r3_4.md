# TE-1 plan r3.4 (delta over r3.3: S0-2 post-terminal fills)

Delta only. Everything in `TE-1_plan_r3_3.md` not named here stays binding. Authored by `planner` (read-only) after the Stage 0 STOP recorded in `te1/TE1_STAGE0_RECORD_2026-10-11.md`; S0-2b was run by the coordinator and PASSES (same record).

## Changes from r3.3
| Source | Change |
|---|---|
| S0-2 STOP (20/25 bridge) | New premises P38–P42; new Ruling R11 (narrow disclosed post-terminal straddle branch inside `_bridge_family`, option 2'); WP-A gains code + RED tests; S0-2 restated, S0-2b added. |
| S0-5: SFO 09-11 latch row has null `venueOrderId` | WP-A `legacy_join` joins on (station, climate_day, instrument_id) via the latch key, never on `venueOrderId`; new RED test. |
| S0-5: whole-store total == SCORED Σ (TRUE) | Merge-8 resolved: WP-B uses the equal-totals LEGACY check. `test_legacy_check_uses_scored_bucket_subset_when_store_has_extra_trials` stays as a branch test only. |
| S0-11: 5 no-fill intents; strict AMBIGUOUS not knowable | WP-B disclosure split: `n_no_fill_intents=5` (+source) and `n_ambiguous_no_fill=UNKNOWN`. |
| S0-12: n=25 only if the 10-06 fills get kind FQ | R11 makes them FQ, so k=25 stands; S0-12 re-checked after R11. |

## New verified premises
| # | Premise | Evidence |
|---|---|---|
| P38 | `_bridge_family` requires climate day in `[d0, terminal]` then exactly one match; returns `str | None`; sole caller `backfill_family`. `attribute_fill`/`backfill_family` have NO production caller today (label path `not_wired`, P3); a bridge change reaches production only via WP-A. | `attribution.py:209-236,252,284`; test call sites `test_aut2_attribution.py:149,225,244,255,265,274,292` |
| P39 | The FQ latch prefix (`"forecast_quantile_ladder/trial/"`) is shared by every FQ family; only the manifest window disambiguates. Exactly one FQ manifest exists: `pm_us_crh_fq_v1` (d0 10-02, terminal 10-05). | `persistent_latch.py:68`; `attribution.py:177-188`; `deploy/families/pm_us_crh_fq_v1.json:5-6`; P36 |
| P40 | `terminal_climate_day` was added AFTER the fills: boot manifest (`4ba7f10cd1f6`, sha256 `8e1217fd…`) has no such key; `cebaab49` committed 2026-10-06T01:42:30Z; the five 10-06 fills were sent 10-05T16:50:50Z–19:31:03Z, after the failed 16:40Z halt. | S0-2b (coordinator, git read-only); `tests/unit/test_registry_replay.py:715-729`; TE-2 P16 |
| P41 | In `analysis/labeling` only `attribution.py:234` reads `terminal_climate_day`. Its meaning is statistical: it keeps a successor's rows out of a family's alpha-spending tally (`family_barrier.py:52-91`; `score_live_trials.py:1142`). A pre-epoch row is never admissible and never feeds a statistic (`attribution.py:111-119`; AST guard `test_aut2_attribution.py:305-320`). | ripgrep |
| P42 | `PreEpochAttribution(storage_key=…)` is keyword-constructed at `fq_scorer.py:451` and `test_aut2_fq_scorer.py:369,399`; any new field must be defaulted. | ripgrep |

## Ruling R11 — attribution of the five post-terminal pre-epoch fills
Option 2': a straddle branch inside `_bridge_family`. The strict rule (`attribution.py:227-236`) is unchanged and runs first. The straddle runs ONLY when the strict set is EMPTY (never when ambiguous) and requires ALL of:
1. the latch key exists (same check as `:225`);
2. exactly one manifest matches kind/venue/station with `d0 <= day`, terminal ignored, and that manifest declares a terminal day;
3. `climate_day == terminal + 1 day` (D+1 straddle; FQ trades D+1 only);
4. `fill.ts_event < (terminal + 1 day) 00:00Z` (UTC midnight precedes local midnight at every US station — conservative).

Then it returns the family with `basis=BRIDGE_POST_TERMINAL`. The row stays `PreEpochAttribution`, UNATTRIBUTED, `admissible=False`. Rationale: the order was placed by the only FQ node while the family's own trading date was <= terminal; the terminal key's purpose is statistical (P41) and cannot be breached by pre-epoch rows.

| Option | For | Against | Verdict |
|---|---|---|---|
| 1. Manifest blob at boot (git history) | Exact provenance | git/reflog at runtime inside the bwrap label unit; new closure input; heavy for 5 closed-set fills | Rejected |
| 2. Sent before the terminal key's commit time | Faithful to P40 | Needs commit time at runtime (git or magic constant) | Rejected in that form; 2' uses fill data only and its bound (10-06T00:00Z) precedes `cebaab49` (01:42Z) |
| **2'. Straddle branch** | In-seam, pure, disclosed, closed-set, fail-closed on ambiguity, no manifest edit | A prospectively-set terminal also bridges a D+1 order placed on the terminal day — still correct for accounting; no statistic moves (P41) | **Chosen** |
| 3. Leave 5 UNRESOLVED, amend goal | No code | Hides real P&L (part of FQ −2.17); daily unresolved CRITICAL; fails `missing_label=0` | Rejected |
| 4a. Planner strips terminal via `dataclasses.replace` | One line | Silent parallel rule outside the seam; ambiguous once a v2 FQ manifest exists | Rejected |
| 4b. Fold `champion_at` | In seam | Registry dir empty (S0-12) → None for every pre-epoch fill | Unavailable |
| 4c. Retroactive manifest edit | Trivial | Forbidden; breaks `test_registry_replay.py:729`, `test_set_family_halt_cli.py:1430`; changes PREREG scope | Rejected |

## WP-A edits
`src/breezy/analysis/labeling/attribution.py`:
- NEW `class BridgeBasis(StrEnum)`: `FOLD`, `BRIDGE`, `BRIDGE_POST_TERMINAL`.
- `PreEpochAttribution` gains `basis: BridgeBasis = BridgeBasis.BRIDGE` (defaulted, P42; `fq_scorer.py:451` unchanged).
- `_bridge_family` returns `tuple[str, BridgeBasis] | None`; strict body byte-identical; on an empty strict set it calls NEW public `post_terminal_straddle(fill, manifest, climate_day) -> bool` (in `__all__`).
- `backfill_family:251-258`: fold wins as today (tagged `FOLD`); otherwise bridge result + basis; the disagreement check compares family ids only.
- Docstring `:6-10` adds rule (c'). No change to `attribute_post_epoch`, `latch_key_exists`, epoch logic.

`unit_wiring.py` (planner): prints `AUT2 PRE_EPOCH_BRIDGE basis=bridge_post_terminal n=<k>` once per run (expected k=5); adds no attribution rule.

`legacy_join.py`: fill → `trial_id_for(prefix, station, climate_day, instrument_id)` → latch record → frozen ScoredTrial. `venueOrderId` is never a join key; compared only when non-null; disagreement refuses (`LegacyAttributionDisagreement`).

RED tests (`tests/unit/test_aut2_attribution.py`; latch fixtures via the real writer `PersistentQuantileLadderLatch.latch`, L-42):
- `test_post_terminal_straddle_bridges_with_basis` (day 10-06, ts 10-05T17:00Z, terminal 10-05 → `PreEpochAttribution(storage_key=v1, basis=BRIDGE_POST_TERMINAL)`; stub: `Unresolved("no_backfill_family")`)
- `test_post_terminal_fill_after_terminal_day_end_is_unresolved` (positive control; ts 10-06T00:00:00Z)
- `test_post_terminal_two_days_past_is_unresolved`
- `test_post_terminal_relaxed_ambiguity_is_unresolved`
- `test_strict_ambiguity_never_falls_through_to_straddle`
- `test_post_terminal_requires_stored_latch_key`
- `test_open_manifest_never_takes_straddle_branch`
- `test_post_terminal_row_still_unattributed_and_inadmissible`
- `test_backfill_fold_basis_is_fold` (regression pin + mutation note)

RED tests (`tests/unit/test_te1_label_wiring.py`):
- `test_planner_post_terminal_fq_fills_bridge_to_v1_and_count_logged` (stub: empty plan)
- `test_legacy_join_matches_latch_row_with_null_venue_order_id` (SFO 09-11 shape; stub: no legacy input)
- `test_legacy_join_refuses_when_non_null_venue_order_id_disagrees` (positive control)

Acceptance (amended): the 34-fill fixture includes five day-10-06 FQ fills on a terminal-10-05 manifest → `durable_fill_count=34`, `missing_label=unresolved=pending=0`, `AUT2 PRE_EPOCH_BRIDGE basis=bridge_post_terminal n=5`, `AUT2 LAG_BACKLOG n=25`.

## WP-B edits
- `fill_pnl.attribution_basis ∈ {pre_epoch_bridge, pre_epoch_bridge_post_terminal, pre_epoch_fold, legacy_latch, residual}`; FQ basis taken from `attribution.post_terminal_straddle` (same exported predicate, same manifests; never re-derived). Allowed import (`attribution` ≠ `accounting`).
- `family_id` for C2-source rows comes from the label row's storage key, never from `_family_id_of_trial` (`portfolio_roi_report.py:2537-2550`, which applies the terminal window and would book the 5 under UNKNOWN). NEW RED `test_family_pnl_fq_includes_post_terminal_fills` (FQ 25 / −2.17; stub 20).
- Disclosures replace `n_ambiguous_no_fill (S0-11)`: `n_no_fill_intents=5` + `no_fill_source="exec/polymarket_us/intent/history+resolver"`; `n_ambiguous_no_fill="UNKNOWN"` (never 0); `n_post_terminal_bridge=5` + `post_terminal_ref="TE-2 P16 / cebaab49"`. Rename `test_disclosures_ambiguous_unknown_not_zero_and_venue_positions_false` → `test_disclosures_no_fill_intents_five_ambiguous_unknown_and_venue_positions_false`, asserting both.
- LEGACY runtime check fixed to equal-totals: LEGACY Σ == `realised_pnl_after_fees_total` (`:4241`) = −0.54.

## Stage 0 edits
- S0-2 (restated): 25/25 FQ fills bridge to `pm_us_crh_fq_v1` alone — 20 `BRIDGE` + 5 `BRIDGE_POST_TERMINAL` (SFO 81_82, MDW lt_69, MDW 70_71, LAX lt_91, SFO 83_84); latch keys 25/25. Verified as WP-A acceptance. Any other split is a STOP.
- S0-2b (new): PASS (see record).
- S0-12: re-print `families()` and planned kind for the 5 fills after WP-A; expect FQ, k=25.

## Success criteria (amended)
- [ ] S0-2 25/25 (20 + 5 straddle) and S0-2b recorded before the WP-A merge.
- [ ] Live proof 1 also shows `AUT2 PRE_EPOCH_BRIDGE basis=bridge_post_terminal n=5`.
- [ ] Live proof 2 also shows `pm_us_crh_fq_v1` 25 / −2.17, `n_post_terminal_bridge=5`, `n_no_fill_intents=5`, `n_ambiguous_no_fill=UNKNOWN`.
- [ ] Every existing `test_aut2_attribution.py` and `test_aut2_fq_scorer.py` test green UNEDITED.

## Blast radius of the `_bridge_family` change
- Production: `backfill_family` (`:252`) ← `attribute_fill` (`:284`); no production caller until WP-A (P38). POST_EPOCH path (`:280-283`) untouched.
- Must stay green unedited: `test_aut2_attribution.py:224-239,242-251,254-282,285-302,305-320`; `test_aut2_fq_scorer.py:369,399`. No widening rows.
- Pins: `attribution.py` is in the `aut2.label` closure → re-pinned by WP-A's existing commit. UNVERIFIED: whether it is in the `aut6.health` closure — WP-A runs `regen_closure_manifest.py --check` and re-pins both producers if so.
- Untouched: `family_barrier.py`, `score_live_trials.py:1142`, `position_monitor_nightly_report.py:167`, `portfolio_roi_report.py:761,2537`, every manifest. PREREG scope, tally and M1-v3 inputs unchanged.

## Risks
- Straddle admits a future wrong family → pre-epoch only (closed set; future fills go through C1), fail-closed on relaxed ambiguity, tested.
- UTC-midnight bound rejects a real straddle fill after 00:00Z → fails closed to UNRESOLVED + CRITICAL (visible); the 5 fills sit ≥4.5 h inside the bound (S0-2b).
- WP-B re-derives family via the windowed resolver → storage-key rule + `test_family_pnl_fq_includes_post_terminal_fills`.
- Basis drift labeler vs report → one exported predicate.

## Unknowns
1. `attribution.py` membership of the `aut6.health` closure.
2. That `fq_scorer._draft` adds no window check of its own for pre-epoch rows (proven only by the WP-A fixture run).

Confidence: HIGH on R11, MEDIUM on execution details.
