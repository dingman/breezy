# AUT-2 r3: merged review (coordinator). silent-failure-hunter 85 (1 HIGH), prediction-market-reviewer 80 (2 HIGH). Final 80, NOT READY.
Rebase on the FROZEN ARCH (Rev 7 or later, named in README) and follow PLAN_TEMPLATE's programme-wide rules.

## HIGH
- **Q1 [sf N1, pm H1]**: Use `TimeoutStartSec` everywhere in place of `RuntimeMaxSec`, covering §3.2, §3.10, §3.11, WP6, WP9, the tests and the constant names. Add a deploy test that refuses `RuntimeMaxSec` on any AUT-2 oneshot. Prefer a unit-level `TimeoutStartSec` that covers both ExecStart lines. Add the test that the 14:15Z and 05:00Z slots clear [16:30Z, 17:10Z) [pm M1].
- **Q2 [pm H2, sf N2, sf N3]: rebase onto ARCH C2.**
  - `trial_id` is the stored latch key, and attribution comes only from C1 `family_id`. Add `test_scorer_never_attributes_by_trial_id_prefix`.
  - Use the ARCH `p_source` enum `{c1_decision, artefact_recompute, none}` and emit `p_raw_at_decision`.
  - Rules (b)/(c) and the log bridge are backfill only. Pre-`capture_epoch_start` fills are `unattributed`, inadmissible, `p_source=artefact_recompute|none`. Add `test_pre_epoch_fill_never_admissible`.
  - Cut C-1 to the widenings ARCH does not already have (`venue_fallback_settlement`, the two position-compare columns).

## MEDIUM
- **Q3 [pm B4]**: Remove the "same rule as the exec client" claim and call it the standard weighted-average cost method. Keep the lifetime-identity test. State that per-label basis intentionally differs from the exec client's `avg_px_open` (net remaining cost).
- **Q4 [pm M2]**: Name which AUT-1 slice (1a or 1b) WP7 needs, and recompute the ETA.
