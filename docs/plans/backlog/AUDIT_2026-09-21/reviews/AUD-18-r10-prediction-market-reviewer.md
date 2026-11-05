# AUD-18 — Round 10 review (prediction-market-reviewer)

Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-18-strategy-design-backtest-iterate-programme.md
SHA256: eac43837f2e9f6bec8cd2771f92b583467df58d2d9e3b2339b57f3bce12a67d1
Round: 10

## Verification

Consolidation-only edit confirmed: the full POWER-PRIMARY-ONLY derivation remains intact in §6.1 under a stable anchor (`<a id="power-primary-only">`); §9, §11, §12 and §7 step 8 clause (v) are trimmed to one sentence each plus the anchor reference, but each retains its section-specific consequence verbatim in substance — §9's "understated, never overstated," §11's "MORE likely than the numbers alone imply" plus the binding on AUD-02/A1/AUD-10b downstream citations, §12's ACCEPTED status and future-amendment route. §7 step 1's RED (`power_is_primary_only == True` asserted, `False` refused), §6.2's record field, and D13 clause (i) are untouched — these are enforcement artefacts, not restated prose, and consolidation correctly left them alone. Grepped every pinned constant (`PROGRAMME_ALPHA`, `MAX_HYPOTHESES`, `MAX_VARIANTS_PER_HYPOTHESIS`, `MIN_PER_VARIANT_ALPHA`, `POWER`, `VARIANCE_BOUND`, `PINNED_ORDER_QUANTITY`, `EVIDENCED_FEE_THETA`, `MAX_SINGLE_DAY_LEG_SHARE`) and the veto definition (`pooled_net_pnl_per_contract > 0` strict, `POOLED_PNL_VETO_REQUIRED=True`) — all numerically and definitionally unchanged from round 9. `break_even_row`/`BE_i` netting citations unchanged. Both worked MDEs (`0.1032`/`0.0730`) unchanged.

## Sweep

No market-relevant content lost: nothing that a peer ruling, AUD-02/A1, or AUD-10b would need to read is now missing or ambiguous — the anchor makes the single source of truth easier to find, not harder. No new defects found.

## Score

**Total: 100/100** (20/20 · 20/20 · 15/15 · 20/20 · 15/15 · 10/10) — pure de-duplication, nothing substantive changed, zero defects from this lens.

## Blockers

None.
