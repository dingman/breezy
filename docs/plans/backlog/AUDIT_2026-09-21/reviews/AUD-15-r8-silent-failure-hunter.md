# AUD-15 — Round 8 review (silent-failure-hunter, delta on round-7 defects)

**Plan file:** AUD-15-failing-study-units-fix-or-retire-and-alert.md
**SHA256:** 3b46e14d8e322887ad886f618d677f2c117b6c23e3d61beb3f7312bb52dc38b7 (verified via `sha256sum`)
**Round:** 8 (delta)
**Reviewer:** silent-failure-hunter (independent, blind)

## Grep sweep for residual "silently stale" language

`grep -n "ages silently\|ever-older\|ever-staler\|never raises.*SystemExit\|goes stale silently\|fails silently"` over the full current plan returns only: line 14 (the original, unrelated G-14 class descriptor — both units failing with no `OnFailure=`, accurate as written), line 625 (the new provenance sentence, explicitly quoting the ruling's superseded language as a historical attribution, correctly framed as pre-rotation-discovery), and three §13 review-history entries quoting the now-fixed old language as something that *was* corrected. **No live, uncorrected instance remains.** §5 and §9 now state the accurate shape (today's key left unwritten, loud `SystemExit` at `current_rung_hold_monitor_hypothetical_hold.py:169-170` on essentially the first day), and §6's mtime-leg rationale is correctly re-based on the anchor-change case as the only scenario producing a present-but-old file. The provenance sentence correctly identifies this as a refinement that strengthens (not weakens or re-litigates) the endorsed ruling's §A1 condition, so leaving the ruling artefact itself unedited is the right call.

## Verification of the `_CANDIDATE_UNITS` addition (architect's round-7 required change)

| Claim | Status |
|---|---|
| `_CANDIDATE_UNITS` at `test_analysis_units_memory_capped.py:29` | CONFIRMED exact |
| `_EXISTING_UNITS = [name for name in _CANDIDATE_UNITS if (_DEPLOY_DIR / name).is_file()]` at `:43-45` | CONFIRMED exact — corrects the architect's earlier `:25-27` citation drift |
| `test_candidate_unit_exists_or_is_explicitly_skippable` — a documented tautology, never fails | CONFIRMED, `:90` |
| Three parametrized tests over `_EXISTING_UNITS`: `..._memory_max_ceiling` (`:103`), `..._memory_high_below_memory_max` (`:113`), `..._cites_the_2026_09_11_k1_incident` (`:128`) | CONFIRMED, all exact |
| The new unit's §6-specified ceilings (`MemoryHigh=512M`/`MemoryMax=1G`) satisfy the first two tests trivially (`512M < 1G ≤ 16G`) | CONFIRMED by arithmetic against the assertions read from source |

The reasoning is sound: `_CANDIDATE_UNITS` is correctly identified as a curated, per-unit editorial list (not an exact-set pin), distinct from the exact-set `_HEAVY_TIMERS`/`_HEAVY_SERVICES` pins in the sibling test file that genuinely require pruning retired names — the plan correctly treats the two files' different designs differently (prune the exact-set pins; leave the tolerant existence-filtered list's retired entries alone, since `_EXISTING_UNITS`'s `is_file()` filter already silently skips them, consistent with that file's own stated design). Ordering the addition after step 7a (so the entry is filter-exercised, not vacuously absent) and requiring the K1-incident citation to land in the same unit file rather than be discovered red are both correctly reasoned to avoid a vacuous "added but filtered out" pass — §8 item 14's explicit non-acceptance clause for that shape closes exactly the vacuous-detector risk this lens exists to catch.

## Sweep of all six hunks

No regression found. No new silent-failure path, no re-latch risk, no weakened pin. The two edits (round-7's stale-language fix and the architect's `_CANDIDATE_UNITS` decision) are independent, additive, and both verified precisely against source.

## Per-criterion points

| Criterion | Cap | Points | Reason |
|---|---|---|---|
| Fidelity to the audit gap and completeness | 20 | 20 | Unchanged, unaffected. |
| Technical correctness and evidence grounding | 20 | **20** | Round-7's internal-consistency defect is fully closed — verified by direct grep, no remaining contradiction anywhere in the current text. |
| Implementation specificity and feasibility | 15 | 15 | Unchanged; the new `_CANDIDATE_UNITS` decision adds further, precise specificity (ordering, node-id verification, non-vacuity). |
| Acceptance criteria and validation quality | 20 | 20 | Item 14 now explicitly excludes the "added but filtered out" vacuous-pass shape. |
| Autonomous operation, failure handling, recovery | 15 | 15 | Unchanged; the round-6 mechanism fix remains intact and unaffected by this round's documentation/test-coverage edits. |
| Portfolio objective alignment, scope, dependencies | 10 | 10 | Unaffected. |
| **Total** | **100** | **100** | |

## Required changes

None. Both round-7 required changes (mine and the architect's) are closed and verified against source; no new defect found in the six-hunk sweep.

## Blockers

None. Unchanged — R-1/R-2-equivalent rulings for 15b/15c remain RULED and peer-ENDORSED.
