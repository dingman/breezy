**Verdict: APPROVE.** Round 3's HIGH and all six MEDIUMs are closed in the plan body itself, not only in the §R4 table. I found no new blocking defect. Everything below is non-blocking and can be fixed in the text or at seam brief time.

**How I checked.**
- **Code facts.**
  - V25 is correct: `client.py:663` has `LONG_ONLY_SIDE = "BUY"`, and `:668-671` has `_RECORD_SIGNS`. My r3 citation of `:3442` was wrong.
  - V13 holds: `:399`/`:412` (key prefix), `:923` (`DurableFillRecord`), `:4593` (`record_fill`).
  - V26 holds: `live_orders_gate.py:53` imports `FamilyManifest`, and `:62-70` is the 7-member Literal.
  - V27 holds: `trade_supervisor.py:304-307` is `<store>.intent.lock`.
  - `family_manifest` and `live_orders_gate` import no `breezy.domain`, so contract (b) holds for the pyarrow-reaching modules.
- **V23 is confirmed from the installed import-linter source** (`importlinter/contracts/forbidden.py:74,139-143`). `as_packages` defaults to True, and `find_shortest_chains(..., as_packages=True)` treats a package in `source_modules` as including all its descendants. Listing modules only is the right fix.
- **V22 is plausible.** I did not re-run it. The edge set is consistent with the File plan, and the `TYPE_CHECKING` point holds because nothing excludes those imports.
- **Sizing re-summed from the table:** 27 seams; 6,640 src + 12,300 test = 18,940 lines; largest seams 950 (5a, 8c); all ≤ 1,000; 27 × 23–25 min = 621–675 min. All correct.
- **Seam dependencies are acyclic and in merge order:** schemas ← rollback_journal (5b), transitions ← fold, stage_policy ← transitions, registry_store ← family_bytes (6d). The early-start table is still valid.
- **LESSONS:** all 20 L-numbers cited match their headers in `docs/core/LESSONS.md`. None is fabricated.

## r3 findings: status
| # | Status | Note |
|---|---|---|
| 1 HIGH, `schemas` breaks contract (c) | Resolved | Types moved; local `LiveOrdersRefusal` plus mirror test; planted control at 2b and 6a |
| 2, AC 10.4 vs one-home rule | Resolved | AC 10.5; `[store]` param |
| 3, HWM pickup | Resolved | AC 16, 17 (steps 3 and 4 swapped; no export = 0), AC 19 `hwm` and `verified_export_seq`; binding note 6b/c; data flow |
| 4, tallies | Resolved | 13 + 2 fields add up exactly to ARCH `:431-434` plus E-5, minus `holdout_opens`; R24; (b) item 33. See N5 |
| 5, `LegFill` | Resolved | |
| 6, E-14 liveness | Resolved | See N4 |
| 7, sizing | Resolved | |
| 8, store tests vs seams | **Partial** | See N1 |
| 9 to 15 | Resolved | Note 6d agrees with AUT-5 r7 `:937`/`:940` |

## Non-blocking issues
**N1 (MEDIUM, Test Strategy seam column: some tests sit in a seam before their code lands).**
- **Problem:** 6e lists `test_bootstrap_seed_genesis_only` and `test_store_refuses_second_bootstrap_per_venue`. The rules they exercise, BOOTSTRAP genesis/seed and BOOTSTRAP only when the venue has no sender, land in 7d (AC 13; WP table 7d). 7c lists `test_drill_mint_not_counted`, but the mint-rate rule is in 7d. As written, 6e and 7c each go red at their own gate (AC 29, L-43), or the implementer pulls 7d code forward.
- **Fix:** move these tests to 7d. Alternatively, mark which store test needs which validate rule.

**N2 (MEDIUM, AC 17 step 3 and `newest_export`: the listing filter is unspecified).**
- **Problem:** AUT-5 r7 `:487`/`:189` writes `evidence/registry/hwm_reset_<ts>.json` into the same directory, and exports are per venue. If an implementation fails closed on unknown file names, the first HWM reset bricks resolution.
- **Fix:** define the filter as a venue-scoped `\Aregistry_<venue>_\d{4}-\d{2}-\d{2}(_hwm\d+)?\.jsonl\Z`. Name `hwm_reset_*.json` as known and ignored, and say what happens to any other name.

**N3 (LOW, AC 17 step 1 vs AC 18).**
- **Problem:** step 1 ("`is_shadow` → `paths_role_mismatch`") reads as part of `_resolve`. AC 18 runs `_resolve` and skips only step 4, so shadow resolution would always refuse. Step 0 already enforces role consistency. Separately, AC 18 never says whether steps 9–11 run for shadow.
- **Fix:** make step 1 belong to the public sending entry only, and state the shadow step set explicitly.

**N4 (LOW, AC 31 and E-14 rule 7).**
- (a) The test hashes `/home/jon/breezy/deploy/families/...` by absolute path. In a worktree that reads the primary tree, which is the worktree-PYTHONPATH failure mode, so a worktree edit is not caught at merge. Use `entry_points.REPO_ROOT`.
- (b) `test_bootstrapped_root_pin_is_append_only` uses `git show <merge-base>`, but no ref is named, and nothing says what happens when `pins.py` is absent at the base (seam 3a itself).
- (c) Until ROOT_ADMIT is enabled (it is not at L1), the only clearing path is the revert, and from the stage-S bootstrap onward the live fq manifest is frozen. State both.

**N5 (LOW, AC 14).** ARCH `:431` defines `nominations` as "max `k_life`". The plan restricts it to feasible rows. If `k_life` also counts infeasible nominations, these differ. WP1b owns that question under binding note 1b, so record it there.

**N6 (MEDIUM, AC 15(ii) collateral).**
- **Problem:** the ban covers every `dataclasses.replace` and `copy.*` call across `strategy/autonomy` and `analysis/autonomy`. AUT-3 r6 `:137` already plans `dataclasses.replace(row, split=...)`, and AUT-4 and AUT-6 build in these packages. §ERRATA (b) does not tell them. A4-R5 makes the ban binding, but consumers will meet it as a red gate.
- **Fix:** add (b) items for AUT-3, AUT-4 and AUT-6, and state how an exemption gets added (reviewed literal). The `stage is STAGE` identity check already defeats copies, so the ban is defence in depth.

**N7 (LOW, binding note 6d).** Only the production cut-over creates `evidence/registry/`. A shadow root without the directory gets `export_unreadable` on day 1 (AC 18 applies step 3 unchanged). Require every bootstrap, shadow included, to create it.

## Scores
| Axis | Score |
|---|---|
| Correctness vs ARCH | 8 |
| Architecture and idiom fit | 8 |
| Test coverage | 8 |
| Risk mitigation | 8 |
| Scope minimality | 6 (18.9k lines, 27 gated seams; justified by the rulings, but heavy) |
| Feasibility | 7 (about 11 h serial gate floor; N1 would make two seam gates red as written) |

**E-14 (rule 7 included):** ADOPT. Its ordering matches binding note 9 and (b) item 28: the pins commit lands before the first bootstrap on any root.

Evidence paths:
- `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/ARCH-0-seamA_plan_r4.md`
- `/home/jon/breezy/.venv/lib/python3.13/site-packages/importlinter/contracts/forbidden.py`
- `/home/jon/breezy/src/breezy/adapters/polymarket_us/exec/client.py`
- `/home/jon/breezy/src/breezy/persistence/live_orders_gate.py`
- `/home/jon/breezy/src/breezy/runtime/trade_supervisor.py`
- `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/AUT-5-promotion-demotion_plan_r7.md`
- `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/AUT-3-retraining_plan_r6.md`