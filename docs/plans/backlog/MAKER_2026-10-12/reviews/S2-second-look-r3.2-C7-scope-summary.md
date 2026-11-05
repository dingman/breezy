# S2 second look r3.2 — C7 scope (D-1) review summary, 2026-10-20
Coordinator record of the 2026-10-20 blind reviews of delta row 2.21. The reviewers' full returns were not persisted; this file records their verdicts and conditions as received. It is not a substitute review.
Subject: `S2_second_look_plan_r3_delta_coordinator.md` row 2.21 (commit 0c132124); ruling `docs/evidence/RULING_MAKER-S2_second_look_C7_scope_2026-10-20.md`.

## Verdicts
- python-reviewer: HIGH, conditional. Conditions folded into the C7 build brief (branch `backlog/s2-c7-prefilter-2026-10-20`).
- architect: REQUEST_CHANGES. Conditions folded into the same build brief.
- Both conditional verdicts close only on the C7 diff plus a full gate with EXIT=0, verified by the coordinator against the artifact.
- Post-build independent review (2026-10-20, blind, on diff 2924e011..3190eb3d): python-reviewer MEDIUM (one BLOCKING: production callers dropped the earliest-licensed-listing cutoff term); code-reviewer WARN (same defect as MEDIUM; refactor verified as a pure move; scope-guard pins verified against 35dbc2dd with 0 mismatches). Fix commit follows on the same branch; re-review required before merge.

## Premise P (verified 2026-10-20, counts-only and stat-only, no block-2 byte read)
- Cutoff 2026-10-12T12:00:00Z (epoch 1791806400).
- Earliest licensed first_seen = 2026-10-13T10:00:13.334700Z (16 rows, S..10-17, all COVERED; W1 :75-96).
- HOLDS for all 78 CLEAN instances:
  - 70 pre-cutoff instances (count by subtraction, W1 :101) all precede every observed first_seen.
  - 8 post-cutoff instances are kept, not skipped.
- Limit: evidenced on S..10-17 only. C2 refuses any pinned licensed row with first_seen < cutoff.

## Unchanged
Thresholds 17,280 s / 21,600 s, S, E_max, the pre-registered dates, the NO-SEND firewall, either operator cap.
