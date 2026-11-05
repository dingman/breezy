# AUD-18 — Round 9 review (prediction-market-reviewer)

Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-18-strategy-design-backtest-iterate-programme.md
SHA256: 3da81edd563a9b64814c574a7e8ac9b231c0aed27321384463217a9bc43627ba
Round: 9

## Verified: veto definition and BE netting untouched

Grepped every pinned constant: `PROGRAMME_ALPHA=0.05`, `MAX_HYPOTHESES=4`, `MAX_VARIANTS_PER_HYPOTHESIS=4`, `MIN_PER_VARIANT_ALPHA=0.003125`, `POWER=0.80`, `VARIANCE_BOUND=0.25`, `PINNED_ORDER_QUANTITY=1`, `EVIDENCED_FEE_THETA=0.0695`, `MAX_SINGLE_DAY_LEG_SHARE=0.20` — all numerically unchanged, only comments extended. `pooled_net_pnl_per_contract > 0` (strict) and `POOLED_PNL_VETO_REQUIRED=True` appear identically at every prior site (§6.1, §6.4 step 6, §7 step 8). `break_even_row`/`BE_i` netting citations (`:76-84`) unchanged. Confirmed: round 9 is qualification-only, no substantive redefinition.

## (a) POWER relabelled primary-only — verified correct

`CONFIRMED = primary-passes AND veto-passes`; since the veto can only shrink the confirmed set (never enlarge it — the same containment used in round 8 to justify zero extra alpha), `P(CONFIRMED | true effect) <= P(primary passes | true effect) = POWER` at the design point. This is a logically valid, correctly-derived statement, not an approximation dressed up as exact. Handled honestly: no fabricated composite-power number is asserted (the shortfall genuinely depends on unknown leg-count/entry-price heterogeneity), the refusal direction is shown safe a fortiori, and `power_is_primary_only` is now a mechanical, testable record field (RED vi-a) rather than a prose caveat that could silently rot. This is the right fix and could not reasonably be more precise without inventing a number this design has no basis for.

## (b) My round-8 MINOR (`MAX_SINGLE_DAY_LEG_SHARE=0.20` framing) — verified fixed

The "coarsest bound under which no single station-day can carry a pooled result" claim is withdrawn; the plan now states plainly "a leg-COUNT share does not bound a P&L-DOLLAR share" and correctly attributes closure of the money-losing-CONFIRM gap to the strict `pooled_net_pnl_per_contract > 0` condition alone (exact realised dollar P&L at `qty=1`), with the cap reframed as a pre-registered, pragmatic, additional robustness screen — precisely the distinction I drew. Value unchanged (`0.20`), correctly noted as out of scope to alter here.

## Sweep

No new defects found. No scope, citation, test, or acceptance criterion removed; nothing renumbered; every worked number (`0.1032`/`0.0730` MDEs, `0.324595` BE example) re-verified unchanged. Length growth (1372→1487) is entirely qualifying prose plus one boolean field and its RED — proportionate to the fix.

## Score

**Total: 100/100** (20/20 · 20/20 · 15/15 · 20/20 · 15/15 · 10/10) — both round-8 defects genuinely and precisely closed; zero material or minor defects remain from this lens.

## Blockers

None.
