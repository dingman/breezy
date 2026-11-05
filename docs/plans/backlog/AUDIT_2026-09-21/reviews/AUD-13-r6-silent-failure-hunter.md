# AUD-13 — Round 6 review (silent-failure-hunter, ruling-application delta)

**Plan file:** AUD-13-native-venue-reconciliation-from-durable-records.md
**SHA256:** 0c3a1347c68db9277259c63cce78565f10c6dbf478963a2029ea866681f17ac0 (verified via `sha256sum`)
**Round:** 6 (delta, not a peer-scored self-revision — reviewed fresh per coordinator brief)
**Reviewer:** silent-failure-hunter (independent, blind)

## Inputs read

- `docs/evidence/RULING_venue_reconciliation_R1_R2_2026-09-21.md` (Revision 3)
- `docs/evidence/reviews/RULING_R1_R2_review_2026-09-21.md` (verdict ENDORSE, `:164`)
- `docs/evidence/venue/polymarket_us/FEE_SCHEDULE_PIN_2026-09-18.md` (evidence underlying the ruling)
- The plan diff (+200/−21) and the full current plan text
- Source: `exec/client.py` (`DurableFillRecord`, generator stubs), `fees.py` (`polymarket_us_fee`, `_fee_coefficient`), `continuous_strategy.py` (`on_order_filled` SELL branch), `trial_day_latch.py` (`consume_if_absent`)

## Claims verified against source this session

| Claim | Status |
|---|---|
| Ruling artefact status: "ENDORSED... Revision 3", review trail verdict "ENDORSE — no required change" at `:164` | CONFIRMED — read both files in full |
| Fee-schedule pin evidence: 2026-09-16 baseline 53,624/53,624 rows at `0.06`; 2026-09-17 six rows all `0.0695` with earliest `ts_event` `...17:00:00.508472Z`; three drift alerts at 17:00/18:00/20:00 UTC 09-17; the `[00:00Z,17:00Z)` gap called "open, out of scope" by the pin doc itself | CONFIRMED, exact quotes match `FEE_SCHEDULE_PIN_2026-09-18.md` |
| `DurableFillRecord.order_side: str` field exists; docstring (a few lines above the field) states "`order_side` keeps its sign: a SELL record NETS against the longs (an R-8/R-9 partial exit)" | CONFIRMED, `exec/client.py:665-670` region |
| `polymarket_us_fee` (`fees.py:277`) calls `theta = _fee_coefficient(instrument)` at call time, with no fill-time parameter | CONFIRMED, exact line for the function def; `_fee_coefficient` def one line off the plan's `:422` citation (`:421`) — immaterial |
| `on_order_filled` branches on `event.order_side is OrderSide.SELL` and routes to `_on_exit_order_filled`, with the comment "Breezy never submits any OTHER SELL -- every entry is a plain BUY... so a SELL fill is unambiguously an EXIT fill" | CONFIRMED at `continuous_strategy.py:2271-2277`, exact lines — this independently corroborates finding 8's hazard mechanism: the strategy's own code assumes the BUY/SELL split IS the entry/exit split, so a mis-tagged report is not a cosmetic labeling issue but a genuine phantom-entry risk |
| `authorize_order_cost`/`release_booking`/`true_up_booking` called only from `exec/client.py` (submit/resolver paths); zero occurrences in `continuous_strategy.py` | CONFIRMED by grep across both files |
| `consume_if_absent` at `trial_day_latch.py:780` | CONFIRMED, exact line |
| `generate_order_status_reports`/`generate_fill_reports` still `return []` stubs | CONFIRMED unchanged (expected — 13b has not shipped) |
| §12 "no blocker remains" claim | **TESTED, and CORRECT as a blocker-count claim**: R-1 and R-2 were the plan's only two named BLOCKERs (round-4/5 reviews independently confirmed this — no other blocker existed). Both are now RULED with a peer-ENDORSED artefact. §12 is careful to distinguish this from a readiness claim ("this is a statement about blockers only... it is not a readiness claim, and the plan has not been peer-reviewed in this revision") — that hedge is accurate and appropriately scoped; 13c's three conditions are correctly recorded as sequenced in-plan work, not external permission. |

One non-defect observation, checked and dismissed: the ruling document's current SHA256 does not match the hash the review trail's Revision-3 entry cites (`e211bae3...` vs the file's current `8da6ca9...`). This is explained by the ruling doc's own line 3 ("Status: ENDORSED...") — a finalization header necessarily added *after* the review computed its hash and recorded ENDORSE — not a substantive post-endorsement edit; every quoted number, boundary, and finding I checked against the review trail is present verbatim in the current file. Not a defect.

## New defect found this round

### MATERIAL-leaning — the new fee-ambiguous-window refusal has no named latch, reason code, or alert event, contradicting the plan's own binding rule for every other refusal case

§6's existing "Fail-closed semantics" block (unchanged by this revision) opens with a **binding rule**: *"the generators return an empty list AND record a latched, counted, logged refusal with a reason code — emptiness is never allowed to be indistinguishable from 'nothing to report', and **no new name may be invented for `[]`**."* It then names three concrete mechanisms: `positions_read_failed` (latch), the partial-parse-treated-as-wholly-failed rule, and `record_venue_disagreement` (latch, with the instrument id attached).

The new ruled-design block adds a **fourth** refusal case — a legacy record whose `ts_event` falls in the AMBIGUOUS window `[2026-09-17T00:00:00Z, 2026-09-17T17:00:00Z)`, before the earliest pinned date, or in any future unpinned gap. Both its description (§6: "no order report and no fill report for that record, latched, counted and alerted, exactly like the three fail-closed walks above") and its acceptance item (§8 item 15: "yields no report and a latched, counted refusal") assert the SAME shape as the other three — but unlike `positions_read_failed`/`record_venue_disagreement`, **no latch key, alert event name, or reason-code string is ever given** for this case anywhere in the plan. "Exactly like the three fail-closed walks above" describes the *shape* of the guarantee, not a *name* an implementer can write into code or a test can assert against.

This matters concretely, on the coordinator's own "swallowed refusal" and "silent-failure path" framing:
- The regression-detector counts line (`order_reports=<n> fill_reports=<n> records_considered=<n> gated_out=<n> refusals=<n>`) has a single undifferentiated `refusals=<n>` counter. Without a named reason code for this case, an operator reading that line (or any per-record log line) cannot distinguish "refused because the fee schedule for this fill's date is ambiguous" from a positions-read failure or a venue/local disagreement — three semantically very different conditions currently sharing one bucket for this one case, contradicting the very sentence that introduces the rule ("emptiness is never allowed to be indistinguishable from 'nothing to report'" applies to *why* it's empty too, not only *that* it's empty).
- §7 13b step 1b's test (`test_a_legacy_record_inside_the_ambiguous_fee_window_is_refused_not_defaulted`) asserts "a latched, counted, alerted refusal" but, with no name pinned, cannot assert the latch is *distinct* from the other three — an implementer could satisfy the test's letter by reusing `record_venue_disagreement` for an unrelated reason (a fee-schedule gap is not a venue/local quantity disagreement), which would make a future reader of that latch draw the wrong conclusion about what actually happened.
- This is the same class of gap the coordinator's own AUD-14 round-3/4 review cycle found and required fixed for that plan's CORRUPT-vs-UNAVAILABLE-vs-ABSENT distinguishability — a refusal reusing an unrelated name, or no name at all, is a real (if narrow) silent-failure risk, not merely a style nit, because it defeats the operator's ability to diagnose *which* fail-closed path fired.

**Required change:** name the mechanism explicitly, matching the two existing latches' specificity — e.g. a latch key such as `fee_coefficient_ambiguous` (or `fee_schedule_gap`), carrying the record's `venue_order_id`/`trade_id` (mirroring `record_venue_disagreement`'s instrument-id attachment), its own WARN alert event/detail distinct from the other three, and a RED test asserting this refusal's reason code is *observably different* from `positions_read_failed` and `record_venue_disagreement` in the same run (not merely present).

## Everything else — faithful and complete application of the ruling

No other defect found. Specifically, and directly against the coordinator's checklist:
- **O4 fee resolution**: correctly implements recorded-else-modelled-at-fill-time, with the two-mechanism split (new `fee_coefficient_at_fill` B0 field for new writes; dated schedule for legacy rows) and the closed-interval boundary text matching the ruling's Revision-3 text and the pin document's own evidence, verbatim.
- **AMBIGUOUS window refuses loudly** (modulo the naming gap above — it does refuse, and is asserted to alert; only the *name* is missing, not the refusal-vs-default direction, which is correct and RED-tested).
- **`feeSource` ∈ {RECORDED, MODELLED_AT_FILL_TIME}**: correctly named, correctly scoped as never read by trial scoring, correctly gated as a precondition for any future `exit_guard` consumer.
- **`order_side` from the durable record, never hard-coded BUY**: correctly identified as a defect in the *09-12* plan's field map (not this plan's own prior text), correctly fixed, with a RED test (`test_a_sell_side_durable_record_reconciles_to_a_sell_report_never_a_buy`) that explicitly asserts the reconciled SELL routes to `_on_exit_order_filled` and never the entry path — verified mechanically sound against `continuous_strategy.py:2271-2277` this session.
- **Non-reorderable build order**: B0 field + `feeSource` → order-side fix → increment-C green → 13b → 13c, matching the ruling's §4 condition set exactly (three conditions, not the 09-12 plan's original one).
- **Binding safety facts**: `DailySpendLedger` never booked from `on_order_filled` (verified — zero call sites in `strategy/`); `venue_order_id` idempotency via `consume_if_absent`'s flocked read-check-write; reconciled/resolver fills stay RESIDUAL, never grow `n`; `position_check_interval_secs` stays off — all four restated as binding constraints with accurate citations, not weakened or reinterpreted from the ruling.
- **§12's "no blocker remains" claim**: tested above and correct, with the readiness-claim hedge appropriately present.

## Per-criterion points

| Criterion | Cap | Points | Reason |
|---|---|---|---|
| Fidelity to the audit gap and completeness | 20 | 20 | The ruling is applied completely across every section it touches (§4 dependencies, §5 scope, §6 design, §7 steps, §8 acceptance, §12 blockers) — no clause of the ruling's §6 "exact text changes needed" checklist was found unapplied. |
| Technical correctness and evidence grounding | 20 | 20 | Every citation re-derived from source this session (`fees.py:277`/`:421`, `exec/client.py:665-670`, `continuous_strategy.py:2271-2277`, `trial_day_latch.py:780`, the ledger call-site grep) is accurate; the fee-schedule boundary text matches the pin document exactly. |
| Implementation specificity and feasibility | 15 | **14** | **Named defect above**: the fourth refusal case (fee-ambiguous-window) has no latch key, alert event, or reason code — the one place this revision's own new text is less specific than the base plan's pre-existing three fail-closed cases it claims to match "exactly." |
| Acceptance criteria and validation quality | 20 | **19** | Sixteen items, including two ruling-specific acceptance items (14-15) and the safety-fact item (16). Deducted 1: item 15 cannot be independently verified as *distinguishable* from items 6's existing fail-closed acceptance without the named mechanism above. |
| Autonomous operation, failure handling, recovery | 15 | 15 | Not implicated by the naming gap in a way that changes fail-open/fail-closed direction — the refusal still correctly falls closed (no report, no default), only its diagnostic distinguishability is affected. Every other autonomous-operation property (13d's boot-halt CRITICAL, the fail-closed walks' WARN posture, no auto-recovery) is unchanged and unaffected by this revision. |
| Portfolio objective alignment, scope, dependencies | 10 | 10 | Unaffected — no cap, no financial figure invented; scope and exclusions (position_check_interval_secs, auto-recovery, method changes) all correctly carried forward unchanged. |
| **Total** | **100** | **98** | |

## Required changes (summary)

1. Name the fee-ambiguous-window refusal's latch key, alert event/detail, and reason code (distinct from `positions_read_failed` and `record_venue_disagreement`), and add a RED test asserting it is observably distinct from the other two fail-closed latches in the same run.

## Blockers

**None**, confirmed independently: R-1 and R-2 were AUD-13's only two named blockers (verified against rounds 4 and 5 of this review history), and both are now resolved by a peer-ENDORSED ruling artefact with no required change outstanding on the ruling itself. 13c's three conditions are correctly recorded as in-plan sequenced work, not an external permission gate. The §12 "no readiness claim" hedge is accurate — this revision has not been peer-scored, and the one required change above should land before this round is treated as a clean pass.
