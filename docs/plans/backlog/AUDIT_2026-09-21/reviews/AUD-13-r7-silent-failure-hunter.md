# AUD-13 — Round 7 review (silent-failure-hunter, delta on round-6 required changes)

**Plan file:** AUD-13-native-venue-reconciliation-from-durable-records.md
**SHA256:** 7812b68e16cc2016944ef9b602c5b22225145894b79cf75c465edb10606c7c0a (verified via `sha256sum`)
**Round:** 7 (delta, six hunks, +77/-4)
**Reviewer:** silent-failure-hunter (independent, blind)

## Verification of both edits against source

| Claim | Status |
|---|---|
| `_redact_order_id` function, `exec/client.py:414-416` | CONFIRMED exact — `def _redact_order_id(venue_order_id: str) -> str:` at `:414`, body through `:416` |
| `DurableFillRecord.venue_order_id: str` at `exec/client.py:667` | CONFIRMED exact line |
| `DurableFillRecord.ts_event: int` at `exec/client.py:675` | CONFIRMED exact line |
| `MAKER_FEE_COEFFICIENT` at `fees.py:77`, `DOCUMENTED_TAKER_FEE_COEFFICIENT` at `fees.py:86`, `__all__` at `:53-54` | CONFIRMED — exact lines; docstring at `:83-85` independently states "Public because the schedule-pin capture test is the only legal cross-package reader -- nothing in `src/` may import it," which corroborates the plan's own "no fork" framing rather than contradicting it |
| `polymarket_us_fee` at `fees.py:277`, unmodified per the plan | CONFIRMED — read the current function body; nothing in the diff touches it |
| `test_every_in_scope_theta_site_agrees_with_its_venue_constant` at `test_polymarket_us_fee_schedule_pin.py:240`, `study_theta_sites_from_source` at `:195` | CONFIRMED exact lines |
| "CORPUS REFRESH POLICY... widen, never relax `==`" | CONFIRMED, verbatim in the module docstring at `:16-23` |
| Census currently scans only `scripts/analysis/*.py` (`study_theta_sites_from_analysis_scripts`) plus two `src/` config sites by direct import — **not** `fees.py` or `exec/client.py` today | CONFIRMED by reading `study_theta_sites_from_analysis_scripts` and `test_every_in_scope_theta_site_agrees_with_its_venue_constant` bodies — the plan's "widen" framing is accurate, not an overstatement of existing coverage |
| The census's matcher (`study_theta_sites_from_source`) filters module-level bindings by `_THETA_NAME.search(name)` before extracting a literal `Decimal` — a **name-pattern** match, not "every module-level literal" | CONFIRMED — this means widening the scan to `exec/client.py` (a large file with many unrelated `Decimal` constants) will not produce false positives from unrelated constants; the "declares no fee-coefficient literal" assertion is technically sound against the real implementation, not a naive over-broad claim |

Both round-6 required changes are implemented precisely as specified, with every supporting citation verified accurate against current source.

## Sweep of all six hunks for regressions or new silent-failure paths

No regression found. Specifically checked and cleared:
- **Alert-loop / re-latch risk**: none introduced — the new latch/alert follows the existing pattern exactly (latch key, WARN severity, fixed-enum detail, no retry).
- **Counts-line consistency**: the plan states the per-cause fields sum to the total `refusals=<n>`, and the new multi-refusal test (`test_the_ambiguous_fee_window_refusal_is_observably_distinct_from_the_other_latches`) exercises all three causes in one reconciliation, which is the correct falsifier for a per-cause field silently double-counting or a cause being folded into the wrong bucket.
- **`venue_order_id` redaction**: correctly reuses the existing `_redact_order_id` helper rather than introducing a second, potentially-inconsistent redaction path — consistent with the one existing call site (`exec/client.py:3187`).
- **No-fork pin mechanics**: the AST census's name-pattern filtering (confirmed above) means the widened test is a genuine reuse, not a second parallel mechanism dressed up as one; `polymarket_us_fee` is independently confirmed untouched.

One pre-existing, non-scored observation (not introduced or worsened by this round): the base §6 text (unchanged since round 1) has never named an explicit alert `detail=` enum member for the two *original* refusal cases (`positions_read_failed`, `record_venue_disagreement`) — only a latch key and "WARN severity." Round 7's new `event="reconciliation_refusal"` / `detail="FEE_COEFFICIENT_AMBIGUOUS"` pairing is the first place in the plan any refusal gets a fully-spelled alert shape, and it now stands as an implicit, obvious pattern for the other two (`detail=<LATCH_KEY_UPPER>`) that an implementer would naturally follow. This has survived five prior review rounds by two independent reviewers without being flagged, is not made worse by this revision, and round 7's own new test only requires the fee-ambiguous case's detail to differ from whatever the other two use — it does not depend on the other two being independently named. Not treated as a defect this round; noted for completeness only, per the "sweep for regressions" instruction.

## Reconciliation of round-6 withheld points (round 6: 98/100)

| Criterion | R6 | Reason | Disposition |
|---|---|---|---|
| Implementation specificity | 14/15 | fee-ambiguous refusal had no named latch/alert/reason code | **CLOSED — 15/15.** Named precisely (`fee_coefficient_ambiguous` / `event="reconciliation_refusal"` / `detail="FEE_COEFFICIENT_AMBIGUOUS"`), verified against source, and the no-fork ownership question (module, not a second table) is now equally precise. |
| Acceptance criteria | 19/20 | item 15 not independently verifiable as distinguishable from the other two fail-closed cases | **CLOSED — 20/20.** New item 17 requires the three-refusals-in-one-run transcript with three distinct keys/details/counters; new item 18 requires the widened census green with `polymarket_us_fee` unmodified. Both are concrete, falsifiable artefacts. |
| All other criteria | 20/20/15/10 | (full) | Unchanged — unaffected by this round's edit, re-confirmed by the regression sweep above. |

## Per-criterion points (final)

| Criterion | Cap | Points |
|---|---|---|
| Fidelity to the audit gap and completeness | 20 | 20 |
| Technical correctness and evidence grounding | 20 | 20 |
| Implementation specificity and feasibility | 15 | 15 |
| Acceptance criteria and validation quality | 20 | 20 |
| Autonomous operation, failure handling, recovery | 15 | 15 |
| Portfolio objective alignment, scope, dependencies | 10 | 10 |
| **Total** | **100** | **100** |

## Required changes

None. Both round-6 defects are closed and verified against source; no new defect or regression found in the six-hunk sweep.

## Blockers

None. Unchanged from round 6 — R-1/R-2 are RULED and peer-ENDORSED; 13c's three conditions remain in-plan sequenced work, not external permission.
