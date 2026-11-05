# AUD-18 round-3 review — mle-reviewer

Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-18-strategy-design-backtest-iterate-programme.md
sha256: 63388d3de452d87e24f776f52ae30d6f4a98e9d50928940f08d5f63e45445801
Round: 3
Reviewer: mle-reviewer (independent, blind). Self-score/§13 text ignored per instruction.

## Round-2 MATERIAL defect — verification

Holm dropped at programme level; replaced with a fixed a-priori Bonferroni split (`PROGRAMME_ALPHA=0.05`/`MAX_HYPOTHESES=8`, `allocated_alpha = PROGRAMME_ALPHA/MAX_HYPOTHESES`, `per_variant_alpha = allocated_alpha/k_variants`), never recycled, budget-exhaustion refuses intake. **This part is now mathematically sound and honestly framed**: the union-bound accounting is exact (`Σ per_variant_alpha` over a full registration set telescopes to `PROGRAMME_ALPHA`), and §6.1 correctly states Bonferroni is valid "no independence between classes assumed or needed" — CONFIRMED not overclaimed (no false independence assumption, no claim of exactness beyond the bound). `I_MAX`/`ALPHA_ONE_SIDED` citations (`gs_boundary_artefact.py:78,82,269,271`) CONFIRMED correct. One-sided/one-sided comparison (`per_variant_alpha` vs the pinned `ALPHA_ONE_SIDED=0.025`) is consistent — `PREREG_v2` describes "two one-sided α=0.025" tests (independent one-sided boundaries, not a two-sided 0.05), matching the plan's one-sided framing. No mismatch found.

## New MATERIAL defect — LD_OBF is arithmetically unreachable and this is never stated

With the plan's own declared constants, `allocated_alpha = 0.05 / 8 = 0.00625`, and `per_variant_alpha = allocated_alpha / k_variants <= 0.00625` for any `k_variants >= 1` (division by an integer >= 1 only shrinks it further). `per_variant_alpha` can **never** equal the pinned `0.025` — it is bounded above by `0.00625`, roughly 4x too small even at `k_variants=1`. **`LD_OBF` is therefore dead text under the constants this revision itself declares**: every registration attempting it is refused, unconditionally, regardless of what a peer ruling (§7 step 8) "confirms." The plan presents `LD_OBF` throughout as a live, chosen-when-needed design (§6.1: "only if repeated looks are genuinely needed"; §6.4 step 3's full LD_OBF paragraph; §7 step 8(iii) has the ruling "confirm... the `LD_OBF` pin eligibility"; D9/D12 test only refusal behaviour, never a reachable positive case) without ever computing or disclosing that it cannot be reached at these constants. This is the same failure mode as the round-1/2 defects this plan was praised in §13 for closing: an offered mechanism that silently doesn't do what it appears to. **Required change:** either (a) state plainly in §6.1 that `LD_OBF` is unreachable at `PROGRAMME_ALPHA=0.05`/`MAX_HYPOTHESES=8` (the only combination that reaches `per_variant_alpha=0.025` is the degenerate `MAX_HYPOTHESES=1, k_variants=1, PROGRAMME_ALPHA=0.025`), and reframe it explicitly as reserved for a future amendment, removing the misleading "only if genuinely needed" framing and the ruling-step language that implies an implementer can actually select it; or (b) change the allocation design (e.g. let a hypothesis register for a larger, non-equal share, or lower `MAX_HYPOTHESES`, or raise `PROGRAMME_ALPHA`) so a real registration can legitimately reach `0.025`, and add a positive-path RED proving that case exists and is exercised — not merely that mismatches are refused.

## Other checks

- **Length statement:** §13 states "the file is 730 lines"; actual `wc -l` is 731 — trivial one-line discrepancy, not material, but not exactly factual either. Fix the number.
- Bonferroni-under-dependence claim (station-day clustering): correctly and conservatively stated, not overclaimed — no defect.
- §6.4b `OnCalendar=*-*-* 01:20:00 UTC` justified against the real enumerated timer list — spot-checked plausible, no contradiction found.
- A1-ruling status wording and prior length-claim inaccuracies (round-2 issues) are now correctly stated (ENDORSED, and the round-2 length claim is corrected in §13's own history row).

## Per-criterion scoring (round 3, whole plan, fresh)

- Fidelity to audit gap and completeness: 16/20 — the SINGLE_LOOK/Bonferroni mechanism is now complete and sound, but the plan still claims to offer a working sequential-monitoring path (`LD_OBF`) that cannot be reached, undermining the "design, backtest, iterate" completeness claim for any hypothesis that would need repeated looks.
- Technical correctness and evidence grounding: 15/20 — all citations verified accurate; the core accounting is correct; but an unverified, in-fact-false operability claim (`LD_OBF` reachable/selectable) persists through the very round meant to fix exactly this class of issue.
- Implementation specificity and feasibility: 10/15 — `SINGLE_LOOK` is fully implementable as specified; a materially detailed `LD_OBF` implementation surface (schema fields, loader integration, dedicated tests) is specified for a path that can never execute, which is either wasted implementer effort or a sign the constants need revisiting.
- Acceptance criteria and validation quality: 15/20 — D9/D12 and the REDs thoroughly test refusal behaviour but no criterion tests (or could test, since none exists) a reachable `LD_OBF` case, and none catches the constants-level infeasibility itself.
- Autonomous operation, failure handling and recovery: 14/15 — §6.4b's timer slot is now concretely justified against the real tick list; solid improvement over round 2's placeholder framing.
- Portfolio objective alignment, scope and dependencies: 8/10 — scope/exclusions remain tight; length grew again (638→731 vs 120-250 target) but is honestly flagged as unreachable without losing substance.

**Total: 78/100**

## Blockers

- None requiring external/operator input. The LD_OBF-reachability defect is author-fixable (a documentation correction, or a constants/design change plus a new positive-path test) without waiting on any ruling or unavailable evidence.
