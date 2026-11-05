# S1-WP0 blind review — architect — 2026-10-12

Verdict: REQUEST_CHANGES. The doc is complete and its citations hold, but its main number ("≤ 58 net") rests on a premise the doc itself says is unproven, and the evidence points the other way. It also has wording that will go stale after commit, which breaks the sha256 pin.

**Completeness against WP0's "must say" list (plan r3:160-164)**

| Required item | Status |
|---|---|
| Basis (§3.2) | present, L8-18 |
| Scope: LAX/MDW/MIA/SFO × 09-26..10-13, NYC excluded | present, L24-25 |
| Covers S1 and S2 Stage 0 only, never S5 | present, L26-27 |
| Cost table: 72 gross / 14 already SEARCH with source / net / date effect | present, L36-53 (see F1) |
| Forfeiture statement | present, L55-61 (see F3) |
| Per-fill list WP2 reads | present only as counts, L69-80 (see F4) |
| H-ARCHIVE-RECAL append entry with path | present, L84-88 (see F5) |
| Never GO / NOT-KILLED | present, L65-67 |
| Citations | present, L95-106 |

**Findings**

1. **BLOCKER — the "14 already SEARCH" premise is unverified and probably false, so "≤ 58" is not an upper bound (L39-52, L88).**
   - RA-13-FW item 3 (`RA-13-FW_firewall_audit_2026-09-27.md:25`) makes a station-day SEARCH only if the study read its Depth10 rows.
   - The doc admits this is not shown (L48). In the 2026-10-12 output, the 14 days appear only as `excluded fill (no_taken_latch: … belongs to a different family/latch shape …)`. The study drops those fills at the latch-match stage, and no `rows` entry is later than 09-22.
   - Counting them as SEARCH "conservatively" gets the direction backwards. For a cost declaration, the conservative choice is the larger cost. WP1 reads all 72 days whatever happened before, so this declaration's cost is somewhere between 58 and 72.
   - This breaks L-47 rule 3: "When a premise in a load-bearing decision record is refuted, correcting the record is mandatory even if the DECISION survives". It also breaks L-52: "A read that collapses two outcomes into one value must leave the state AMBIGUOUS or UNKNOWN, never terminal."
   - Edit, table rows L39-40: `| Possibly already SEARCH (exit-window study; Depth10 read NOT shown, see below) | 0–14 |` and `| Net new forfeiture (declared) | 72 (≥ 58 only if a later audit proves the 14 were read) |`.
   - Edit, L51-52: "the 72 net moves the revival trigger by ~14 days, from ~2026-11-24 to ~2026-12-08 (~2026-12-06 if the 14 are later proven read)".
   - Delete L49 "They are counted SEARCH conservatively … net is 72, not 58." and update the append entry (F5) to match.

2. **MAJOR — the pinned document must not change after commit, but some of its text has to (L3, L49, L86).**
   - L3 "DRAFT pending blind review" and L86 "NOT yet appended; coordinator appends after review passes" will be stale once the doc is committed. L49 leaves an open conditional. Any later fix changes WP1's `SEARCH_DECLARATION_SHA256`.
   - Edits:
     - L3 → `Status: FINAL. Immutable once committed; any change is a new dated declaration with a new sha256.`
     - L86 → `Entry appended to the accounting record in the same commit as this file:`
     - Append the entry in the same commit, so the doc never describes a future step.

3. **MAJOR — the doc does not define a "read", so it contradicts "NYC untouched" (L57-61, L24, L53).**
   - L60 says a day counts as touched "if their tape is opened".
   - But converting an instance necessarily opens NYC and D+1 (10-14) bytes (S1-r2-final:27). By the doc's own test, NYC and 10-14 are then touched, which contradicts L24 and L29.
   - Edit, replacing L59-61: "A station-day is read when any row attributed to it passes `admit_print` or enters any computation. Bytes discarded before `admit_print` (NYC, days outside 09-26..10-13) are not reads. All 72 in-scope station-days are forfeited at the first WP1 run, whether or not each yields a row."
   - This also removes the need for an "actually incurred" accounting step later (see F8).

4. **MAJOR — the per-fill list is a count summary, not a list (L71-80).**
   - WP2 "re-derives" the set, so nothing pinned can catch it drifting. A different 28 would still match on count.
   - Edit: replace the "Kept" row with a 28-row table (`venue tradeId | station | climate day | leg | price | tsEvent`). Replace the "Excluded" row with 6 rows, each giving its reason. Make WP2 assert set equality against this pinned list.

5. **MAJOR — the append target is a signed ruling, and the second ledger is left stale (L84-88).**
   - `RULING_H-ARCHIVE-RECAL…:13` is SIGNED. The doc's "(§0 SEARCH vs CONFIRM boundary)" reads as an edit to §0. House practice is a dated section appended at the end (as at :132 and :141).
   - L85 names `RA-13-FW_firewall_audit_2026-09-27.md:28` ("Forfeiture to date: 0") as stale but gives no entry for it. That breaks L-5 ("A state document that outgrows re-verification becomes a source of false claims"). EDGE-4:19 requires the cost "recorded in both plans".
   - Edit, L84: "Append, as a new dated section `## SEARCH declaration MAKER-S1 (2026-10-12)` at end of file; §0 and §1 unchanged."
   - Add a second one-line entry for RA-13-FW: "2026-10-12: superseded by `RULING_MAKER-S1_SEARCH_declaration_2026-10-12.md` §3; post-freeze forfeiture now 72 (LAX/MDW/MIA/SFO 09-26..10-13)."

6. **MAJOR — WP1's hash input is underspecified (L6).**
   - The doc does not say whether the hash covers raw file bytes or the git blob hash, or which path WP1 reads.
   - Edit, L6: "`SEARCH_DECLARATION_SHA256` = `sha256sum docs/evidence/RULING_MAKER-S1_SEARCH_declaration_2026-10-12.md` over the committed file bytes (not the git blob id); WP1 reads exactly this repo-relative path."

7. **MINOR — citation hygiene (L11, L13-14, L43 vs L105).**
   - Every cited file exists. Line refs check out: RA-13 :89-92 is B-3, :94-97 is B-5; EDGE-4 :19 and :22; RA-13-FW :21-29 and :28; spec 196-206, 361, 398.
   - The doc correctly fixes the plan's wrong EDGE-4 path (L101-102), but the inline refs at L11, L13 and L14 still use bare filenames. Use repo-relative paths, e.g. `docs/plans/backlog/EDGE_2026-09-27/EDGE-4_DISPOSITION_2026-09-27.md:19`.
   - The glob is `2026-10-*_nightly` at L43 but `*_nightly` at L105. Use one form.
   - Spec citation (L99): "~360" should be "361".

8. **MINOR — simplest path.**
   - The L60 parenthetical ("`PRE_TRADE_CAPTURE` is not applicable here") adds nothing. Delete it.
   - The "net forfeiture actually incurred" reporting (L60-61) becomes unnecessary once F3 forfeits the full scope. Drop it.
   - §8 Invariants (L90-93) is not on WP0's list and repeats plan §4. Reduce it to one line, "Docs only; plan r3 §4 invariants apply", or delete it.

9. **Path hygiene: PASS.** The doc sits under `docs/evidence/` as `RULING_*`, and no paths are plugin-namespaced.

**Lessons checked**
- L-8, L-56 and L-34: no violation. §5 bars citing anything toward a CONFIRM leg, and the fills are premises only.
- L-47 and L-52: violated (F1).
- L-5: violated (F5).

The coordinator should save this text as `/home/jon/breezy/docs/plans/backlog/MAKER_2026-10-12/reviews/S1-WP0-architect.md`.
