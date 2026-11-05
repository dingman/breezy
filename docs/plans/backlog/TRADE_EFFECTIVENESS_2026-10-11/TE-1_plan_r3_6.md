# TE-1 plan r3.6 (coordinator pass over r3.5: final confirmations)

Confirmations: domain 90 RWC (M1, L1, L2), python 86 RWC (H1 = same defect as domain M1; M-stub, M-fixture; LOWs). Both state READY once the text below is applied. Binding stack: r3.3 + r3.4 + r3.5 + this file; where they differ, the later file wins. No BLOCKER/HIGH remains open.

## R11 control flow (supersedes r3.4 R11 "runs ONLY when strict empty", r3.5 R11.1 "only when the bridge returns None" and R11.2)
`_bridge_family` stays byte-identical. In `backfill_family`:
1. `by_bridge = _bridge_family(...)`; `straddle = _straddle_family(fill, manifests, climate_day, trial_key_exists)` is **always** called.
2. `by_bridge is None` and `straddle is not None` → `PreEpochAttribution(straddle, basis=BRIDGE_POST_TERMINAL)`.
3. Both non-None and different → `Unresolved(_STRADDLE_CONFLICT)` with `_STRADDLE_CONFLICT: Final = "straddle_successor_conflict"` (beside `_FOLD_DISAGREEMENT`; `reason` is a plain `str`, `attribution.py:87`).
4. Otherwise as today; fold-vs-bridge disagreement check unchanged. Fold wins and agrees with the bridge → `basis=FOLD`.

The straddle result is USED only when the strict set is empty; it is EVALUATED whenever a strict match exists, for conflict detection only. Strict-ambiguous (≥2) never falls through.

`_straddle_family` order: facts, rung (via a NEW private `_trial_key_of(fill)`; `_bridge_family` is deliberately not refactored), then the manifest filter (kind, venue, station, `d0 <= day`, declared terminal parsed with `date.fromisoformat` — malformed → None, fail closed, one assertion), `day == terminal + 1`, the R11.3 ts window; then `trial_key_exists(key)` **last**, only if exactly one candidate P survives. R11.2 reworded: the key check runs at most once more, only when a straddle candidate exists (`test_aut2_attribution.py:285-302`: `old` terminal 09-30 → no candidate → single key, green unedited).

R11.3 supersedes r3.4 R11 condition 4. `post_terminal_straddle(manifest, climate_day, ts_event_ns)` (r3.5 signature) supersedes r3.4's `(fill, manifest, climate_day)`. `__all__` stays alphabetically sorted (RUF022).

## Stubs (WP-A)
The stub also ships `legacy_join` (every entry point returns `None` / empty) and the `unit_wiring` plan entry points (empty plan), so `tests/unit/test_te1_label_wiring.py` fails on assertion, never import.

## Test classification (WP-A)
- RED: `test_post_terminal_straddle_bridges_with_basis`, `test_backfill_fold_basis_is_fold`, `test_post_terminal_row_still_unattributed_and_inadmissible` (isinstance-guarded first so it fails on assertion), `test_straddle_successor_conflict_is_unresolved`, `test_post_terminal_rows_excluded_from_every_label_consumer`, `test_label_and_report_post_terminal_sets_identical` (WP-B), `test_planner_post_terminal_fq_fills_bridge_to_v1_and_count_logged`, `test_legacy_join_matches_latch_row_with_null_venue_order_id`, `test_station_utc_offsets_within_straddle_assumption` if it reads the predicate (else control).
- Positive controls (green at RED; each shown failing under a named one-line mutation): the six negative straddle tests, `test_post_terminal_fill_before_terminal_day_start_is_unresolved`, `test_strict_single_match_wins_when_no_straddle_candidate` (mutation: swap strict/straddle precedence), `test_legacy_join_refuses_when_non_null_venue_order_id_disagrees`.

## Fixtures
- Successor conflict: v1 terminal 10-05; v2 d0 2026-10-06, no terminal; fill day 10-06, ts 10-05T17:00Z; one real-writer latch row for the single shared FQ key (P39). Strict set {v2}, straddle {v1}.
- R11.4: station source = union of manifest `stations` against a pinned tz table; assert fixed UTC offsets in both January and July (two of the five fills are in DST).

## WP-A grep (non-blocking)
Confirm `label_run` / `unresolved_row_of` treat `rule_outcomes` / reasons as free-form strings (no whitelist) before adding `_STRADDLE_CONFLICT`.
