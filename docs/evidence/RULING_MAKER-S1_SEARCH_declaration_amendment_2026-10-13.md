# RULING_MAKER-S1_SEARCH_declaration_amendment_2026-10-13

Status: DRAFT (coordinator ruling; FINAL on commit with the date set filled). Immutable once FINAL; any change is a new dated ruling.
Date: 2026-10-13. Type: dated amendment to `docs/evidence/RULING_MAKER-S1_SEARCH_declaration_2026-10-12.md` (6068a00e), under RA-13 B-3. Decision owner per Pre-Auth; no operator cap involved.
Hash: `S2_NBP_LICENCE_SHA256` = sha256 of this file's committed bytes. S2 pins it in `pins.json` (S2 r4 delta (b), E5).
The 10-12 file is not edited. S1's pinned `SEARCH_DECLARATION_SHA256` (`src/breezy/analysis/maker_tape_census.py:76-78`) is unaffected.

## 1. Amendment
The 10-12 declaration's "Not licensed: … any forecast-store read" (:32) and "permits no forecast-store read" (:40) are amended for **one consumer only**:
- **Read licensed:** S2 Stage 0 reads the NBP derived store `~/.local/share/breezy/derived/nbp/` (+ `_manifest.json`), only the 13Z D−1, 19Z D−1 and 01Z D cycles of each replayed day. The read covers stations LAX, MDW, MIA and SFO, and only the frozen date set below. The verdict run reads it **once**.
- **Tape reads made explicit:** Depth10 (`order_book_depths`) and `DepthTruncation` rows for the same station-days are licensed as part of the "Stage 0 replay" read (:31).
- **Frozen replay date set:** `<enumerated after the S1 run, before P2>`. It runs from the first replayable day per S2 WP0 (global first print instant; 2026-09-18, or 09-19 if the first print is after 09-17 16:50Z) to the last S1-censused day with CLI FINAL truth, and never past 2026-10-13. NYC is excluded.

## 2. Why this complies with RA-13 B-3 (`RULING_RA-13_programme_kill_2026-09-27.md:89-92`)
- **No new forfeiture.** B-3 binds the corpus. Every station-day in the set is already PRE_FREEZE (≤ 09-25) or SEARCH_DECLARED (09-26..10-13, forfeited at 6068a00e, cost 72). The forecast read adds no station-day, so the SEARCH cost stays 72.
- **Stage 0 is exploratory, never promotion evidence** (spec v0.3 §6.0 :211, :225; declaration §5). Nothing read here feeds a CONFIRM leg, a GO, or the FQ-v2 NO-TRADE re-open triggers.
- **The read is pre-declared and the date set is frozen before any fill number exists.** It is fixed here after the S1 census and before P2, and is never re-chosen on S2 results.
- **There is a single verdict run on a committed sha,** with a clean tree and `code_sha` in the sidecar. A post-run code change voids it (S2 r4 delta (c)).
- **NBP holdout** (`RULING_holdout_freeze_and_forward_window_2026-10-03.md:5-13`):
  - days ≤ 10-01 are read under clause 3 as descriptive evidence only;
  - days ≥ 10-02 are forward data, read descriptively;
  - S2 fits nothing and never calls `open_holdout` (`nbp_calibration.py:353`).

## 3. Still forbidden
- **Any refit or recalibration** on these rows; any day > 2026-10-13; any other station; any other consumer, including S5, which needs its own declaration.
- **A second verdict run on this set.** A re-emission on more days (S3 r3 :149 second look) needs a new dated declaration covering the new days and its own frozen set.
- **Using S2 numbers as a gate for anything except:**
  - S3's `r_lo` inputs (`s3_inputs.json`);
  - the S2 label (NO-GO / NOT-KILLED / NOT-KILLED-UNSCREENED / UNDERPOWERED-WAIT).

## 4. Provenance
- Plan: `docs/plans/backlog/MAKER_2026-10-12/S2_stage0_replay_plan_r3.md` + `S2_stage0_replay_plan_r4_delta.md` (b).
- Reviews: `reviews/S2-r3-pmr-verification.md` F-4/E-2; `reviews/S2-r3-mle-verification.md`.
- Spec v0.3 §6.0 :196-230.
- `docs/evidence/RULING_MAKER-S1_SEARCH_declaration_2026-10-12.md` §2-§5; RA-13 B-3.
- Ledger: one line goes in `docs/evidence/RA-13-FW_firewall_audit_2026-09-27.md` in the same commit that makes this FINAL: "MAKER-S1 amendment 2026-10-13: S2 NBP read licensed; forfeiture unchanged at 72".
