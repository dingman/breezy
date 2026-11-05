# Rev 2 confirmation pass: status of my 15 required revisions

I read Rev 2 sections 1 to 4.3 (lines 1–579). Lines 580–745 (rest of §4.3, §4.4–4.6, §5, peer-review appendix) were not read, so anything those sections add to §4.3 per-site verdicts, tiers or the open-questions list is unchecked. I spot-checked the two new placement claims against the repo.

| # | Revision | Status | Rev 2 section |
|---|---|---|---|
| 1 | CT-12 before R3.1 | ADDRESSED | §3.2 R0.5 (CT-12, "hard prerequisite", red mutation named); R3.1 Dependencies |
| 2 | Boot smoke instead of "revert before 16:40Z", plus supervisor restart by 14:00Z | ADDRESSED | §3.0 items 4–5; R3.2a |
| 3 | R1.1 placement | ADDRESSED | Declined steps (R1.1); §2.1 item 5; §1.3 row 8 |
| 4 | R1.2: exclude `fee_drift_probe`, characterise first, affinity test is not acceptance | ADDRESSED | Appendix A (a)–(d); §2.1 item 4 |
| 5 | Hold node-loaded steps until the FQ live proof and one reconciled day | ADDRESSED | §3.0 "Hold rule" covers R3.1, R3.2, R3.4 and conditional R1.2. R1.1 and R1.3 are dropped, which is stronger. |
| 6 | R3.2 two merges, CT-13, keep forks, `spawn_node` byte-pin | ADDRESSED | R3.2a/b; CT-13 and CT-8 in R0.5; BC-13 gated on R3.2b plus one daily cycle |
| 7 | R2.2 citations, `mode=ro` test, 10:00Z cutoff, C10 | ADDRESSED, with one defect | R2.2 (see N1) |
| 8 | Rebased-tip pre-merge gate, fast-forward only, one merge per gate cycle | ADDRESSED | §3.0 "Merge procedure" 1–3 |
| 9 | R3.5 deferred, as a mixin, with a scan positive control and CT-1 first | ADDRESSED | R3.5 [R10]. It also corrects my X3 point: X3 is a vocabulary scan with no file allowlist. |
| 10 | R3.4 marker class names, no renames | ADDRESSED | R3.4; CT-8 |
| 11 | R0.1 comment edits | ADDRESSED | R0.1 folds the live-file comments into R3.1, R1.4 and R3.5. The rest have no planned edit. |
| 12 | Drop R2.4; R1.3 | ADDRESSED | Declined steps. R1.3 is declined on a different ground than I gave (distinct surfaces), which is fine. |
| 13 | Characterisation tests land before the live steps they protect | ADDRESSED | §3.2 recommended order puts R0.5 (CT-1 and CT-12 first) ahead of Phase 3. Actor characterisation is gated in Appendix A(b). CT-8 now carries the env-var literal, marker names and an FQ halt-clearing path. |
| 14 | SL-13p2 parity re-run | ADDRESSED | R3.1 acceptance; Appendix A acceptance. The CRH SFO replay is scoped to CRH only in R3.4. |
| 15 | Restate C10 | ADDRESSED | §2.2 "C10, restated", including the do-not-touch stale defaults |

## New material objections from Rev 2

**N1, MINOR (R2.2).** Shims "at their current line positions" cannot be literal. Moving `_admit_fill` (about 90 lines) and `read_filled_trials_state_db` (about 390 lines, `score_live_trials.py:557-950`) shifts every later function, and rulings cite lines such as `:611,675,689,707,861,1079,1788`. R2.2 already allows the fallback "add a citation map old → new in the same commit". Make the map mandatory, not an alternative, and add a test that each cited symbol still resolves.

**N2, none material (R1.5 destination).** I checked it. `registry/__init__.py` has one import (`breezy.registry.sites`), and `sites.py:5` states it imports no `nautilus_trader`. `settlement/__init__.py` has no imports. Both are import-light and layer-legal below `ingest`. Rev 2's conditional wording is right.

**N3, none material (R1.6).** The move to `breezy.runtime` holds. The only importer outside the module is `scripts/analysis/structural_dead_stop.py:70`. Rev 2's timer-fed treatment (10:00Z cutoff plus one consumer run) is appropriate, because that script runs in score-live-trials at 14:15Z. Keep the "no shim in `persistence`" rule, since a shim would keep the layer edge.

**N4, advisory, no revision needed (hold rule lifts).** Rev 2 puts R3.3 and R3.6 after Phase 2 and outside the hold. R3.3 sits on the every-15-minute quote-tape timer, which Rev 2 already handles with the 10:00Z cutoff. No objection.

Verdict for Rev 2: APPROVE-WITH-CHANGES (the single change is N1: make the R2.2 citation map mandatory)