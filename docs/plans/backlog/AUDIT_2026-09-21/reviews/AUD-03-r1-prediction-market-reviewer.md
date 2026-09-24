# AUD-03 review — round 1 — prediction-market-reviewer

Plan: AUD-03-daily-decision-funnel-digest.md
sha256: 4e2b1bce1167be650e4c005c8041b2102c0bd0a5c52beac2a97dd93f7cd4dd1e
Round: 1
Reviewer: prediction-market-reviewer (blind, independent)

## Claims verified

- `STRUCTURAL_HALT_REASONS` closed set — CONFIRMED verbatim at `halt_detector.py:138-154` (`fee_schedule_mismatch`, `shorts_disabled`, `instrument_unresolved`, `settlement_halt`, `no_side_first_order_pending`); `observation_ambiguous`/`illegal_cell` are correctly NOT members.
- WP-R1 false-page fix (`e83fc5c`) already closed, PROGRESS.md stale ("Fix (not yet applied)") — CONFIRMED, `PROGRESS.md:119`.
- Funnel numbers reproduced from `DECISION_FUNNEL_2026-09-20.md` (40,796 / 4,816 / 0 / 0 / 0 / 0) — CONFIRMED, exact match to the source table.
- Delivery via `resolve_alert_sink`, proven by `f97c26f` — CONFIRMED (loopback TLS test, genuine `WebhookAlertSink`).
- Discipline: explicitly declines to build a fault/wait/edge classifier, correctly scoping that as a separate modelling question — appropriate restraint, avoids overclaiming an edge signal from pure observability work.

## Claim REFUTED — MATERIAL, domain-mechanics defect

§3 and §6.1 state the offer-tape schema was "confirmed by direct read" and list its fields as `station, hour_lst, reason, illegal_cell, ask, break_even, side, decision` (§6.1) / `station, hour_lst, reason, illegal_cell, ask, break_even, per-row` (§3). This list **omits `p_bound`**, which is a real, present field in `OfferTapeRecord` (`current_rung_hold/offer_tape.py:117-120`), explicitly documented there as *"The side's own edge estimand (`P_HOLD_LOWER` for YES, `1 - P_HOLD_UPPER` for NO)"* — added specifically so a snapshot's WHY could be reconstructed (`offer_tape.py`'s own module docstring, the 2026-09-15 postmortem GAP fix this plan's own §11 cites as the precedent for why delivery matters).

§6.2 defines the "margin > 0" funnel stage as: *"priced rows where `ask < break_even`, i.e. the sense used by `edge_below_break_even`."* This is WRONG. The actual live rule, verified at `decision.py:402-404`:

```python
break_even = price + _fee(price, inputs.fee_coefficient)
if not (p_bound > break_even):
    return Refuse("edge_below_break_even", ...)
```

`edge_below_break_even` fires on `p_bound <= break_even` — a comparison between a **probability** (`p_bound`) and a **price-plus-fee** (`break_even`), never `ask` vs `break_even`. Since `break_even = ask + fee(ask)` and the fee is strictly positive whenever `ask` is inside the tradeable range, `ask < break_even` is a **tautology** — true on essentially every priced row, independent of whether the decision actually had positive edge. A digest stage built on this definition will report "margin > 0" (and consequently "orders") as satisfied for nearly every row that reaches pricing, regardless of whether `p_bound` actually exceeded `break_even` — silently inverting the one funnel stage that answers the question this whole item exists to answer ("why no trades": genuinely-priced-but-unprofitable vs. genuinely profitable-but-unfilled).

The correct field is sitting in the same schema the plan claims to have read directly. This is exactly the class of defect the review brief calls out: "a citation that does not say what the plan claims is a defect," here compounded by a domain-mechanics sign/comparison error (comparing a price to a price instead of a probability to a price) of the same shape this repo's own evidence chain (`DECISION_FUNNEL_2026-09-20.md`) had to correct twice (wrong-bound comparisons on the NO-side finding).

**Why the RED test in §7/§8 does not catch it:** the exact-reproduction regression test is pinned against 09-16/09-20 data where every stage-5/6 count is already 0 (nothing reaches pricing at all today), so a stage-5 definition that is wrong only on priced rows is invisible against that fixture. The bug is latent, not inert: it activates the moment AUD-01a's gate, or any future gate change, lets decisions reach pricing again — precisely the state this digest exists to make legible.

## Defects

- **MATERIAL** — §6.2, §7 step 1: "margin > 0" funnel stage uses the wrong comparison (`ask < break_even`, tautological) instead of the actual live rule (`p_bound > break_even`, using the tape's own `p_bound` field). Required change: redefine the stage as `p_bound is not None and p_bound > break_even`, matching `decision.py:402-404` exactly, and add a synthetic-fixture RED test (not solely the all-zero 09-16/09-20 regression) with at least one row where `ask < break_even` is true but `p_bound <= break_even`, asserting that row is NOT counted as margin>0.
- **MINOR** — §3/§6.1: the schema description omits `p_bound` and several other real fields (`running_max_lower/upper`, `staleness_ns`, `admission_reason`, `exit_*`, `shadow_rest_*`) present in `OfferTapeRecord`. Omitting fields not needed for the funnel is fine; omitting the one field the funnel's own core stage needs is the MATERIAL issue above — listed separately here because the stated justification ("confirmed by direct read") implies completeness that did not hold.

## Per-criterion points

- Fidelity to audit gap and completeness: 15/20 — correctly scoped as observability-only, correctly reuses the evidence doc's stage definitions in name, but the pricing/margin stage as specified does not actually reproduce the live rule it claims to.
- Technical correctness and evidence grounding: 13/20 — the HaltDetector and delivery claims are solidly verified; the funnel-stage math is verifiably wrong against the same source the plan cites.
- Implementation specificity and feasibility: 14/20 — script/unit shape is concrete and well-modelled on a sibling unit; the core aggregation function as specified would ship an incorrect stage.
- Acceptance criteria and validation quality: 14/20 — the exact-reproduction test is a genuinely strong regression guard for the four other stages, but is blind to this specific defect by construction (see above); needs a second, synthetic fixture.
- Autonomous operation, failure handling, recovery: 14/15 — fail-closed missing-file/partial-day handling is well specified and unaffected by the above.
- Portfolio alignment, scope, dependencies: 8/10 — correctly independent of AUD-01/AUD-02, but a wrong margin>0 signal could misdirect AUD-02's future A0 evidence pack (which this plan's own §4 names as a reuse target) if not fixed first.

**Total: 78/100.**

## Required changes to reach 100

1. Fix the "margin > 0" stage definition to `p_bound > break_even` using the tape's own `p_bound` field, matching `decision.py:402-404`.
2. Correct §3/§6.1's schema list to include `p_bound` (and note which other fields are deliberately unused, if any, rather than silently omitting them).
3. Add a synthetic-fixture RED test that distinguishes `ask < break_even` (always true) from `p_bound > break_even` (the real test), so the regression guard is not blind to this class of error going forward.

## Blockers

None requiring operator/strategy-lead input — this is a plan-content correction, fully resolvable by the implementer before or during the RED step.
