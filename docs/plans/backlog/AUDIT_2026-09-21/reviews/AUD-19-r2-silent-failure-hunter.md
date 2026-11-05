# AUD-19 — round 2 — silent-failure-hunter

Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-19-family-manifest-flag-on-replay-driver.md
sha256: 20d471ca04e3c16c1c6287e3c7f22b8ed4b8442a8a4d9b945df6431b1db4b452
Reviewer: silent-failure-hunter (blind, independent)

## Round-1 defects — verified fixed
1. Stale sidecar (MATERIAL) — FIXED. C6: unconditional pre-run `unlink` after `:1127`
   (`assert_paper_write_path_is_not_live` confirmed at `current_rung_hold_paper_replay.py:333`,
   called near `:1127`), `argv_sha256` run id, atomic `os.replace`. Steps 17-19, A9/A10.
2. `unscoped`-id selector coverage (MATERIAL) — FIXED. Step 20 tests all three live selectors
   (`live_family_tally.py:148,168` confirmed, `family_tally_v2.py:532` confirmed,
   `fill_time_count.py:101` confirmed) + family-scoped read + `params_match` never true. A11.
3. `whole_tape_paper_replay.py` call site (MATERIAL) — FIXED. Step 21 RED/GREEN test; codegraph
   confirms `run_one_precision_arm` (`current_rung_hold_paper_replay.py:813`) is called from
   `whole_tape_paper_replay.py`, matching the plan's `:41` citation. A12, added to A8 allow-list.
4. C2 `:1118` ambiguity (MINOR) — FIXED. Branch now explicitly reads resolved `strategy_name`.

## New: AUD-19c, attacked per brief
- E3 refusal mapping verified against the two named risks: a refused/failed driver invocation
  (non-zero exit) → `record_blocked`, never a silent defaults row — CONFIRMED correct. A sidecar
  whose `argv_sha256` mismatches → refused, not trusted — CONFIRMED explicit in E3 and step 22.
  A missing sidecar → same BLOCKED path. No silent-defaults path found in 19c.
- **MATERIAL — "AUD-09 is CLOSED" is false.** Asserted 5 times (§4, §5, §6 E-header, §9, §13) as
  the basis for treating AUD-09's cited line numbers as stable and never re-verifying them. Read
  AUD-09's own document: `**Readiness:** **NOT READY.**` (`:1249`), round 7 is self-scored 96 and
  explicitly `**unreviewed**` (`:1244`, "Round 7 is unreviewed... had no peer pass"). AUD-19c cites
  AUD-09 `:486-490,498-509,546,698-702,852-854` as fixed anchors (all verified accurate *today*)
  but supplies no re-verification step before 19c's GREEN build, so if AUD-09's still-open round 8
  moves those lines, 19c's citations go stale silently — no test would catch a drifted line number,
  only a reader. **Required change:** correct "CLOSED" to AUD-09's actual status, and add a step to
  §7 (before step 23's GREEN) re-reading the cited AUD-09 sections and confirming they still say
  what §6/§9 quote, failing the increment loudly if they don't.
- MINOR — no RED test proves the runner's `argv_sha256` recomputation (step 22) uses the identical
  hash function/input ordering as the driver's (step 18); step 22 exercises a hand-built fixture
  sidecar rather than round-tripping through both real implementations. Low severity if the same
  helper is reused, but nothing pins that reuse.

## Per-criterion (cap)
Fidelity 18/20 · Technical correctness 16/20 · Implementation specificity 13/15 ·
Acceptance criteria 18/20 · Autonomous operation/failure handling 13/15 · Portfolio alignment 9/10.
**Total: 87/100.**

## Blockers
None operator/evidence-side. The "AUD-09 CLOSED" defect is a plan-authoring correction, not a
ruling or access blocker.
