# AUD-06b — Round 3 review (prediction-market-reviewer, portfolio accounting/risk lens)

Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-06b-bounded-allocation-sizing.md
SHA256: 200bfecb3a00d457672e402ee827c8655ef69236daed3078bbf6fbc3b211274d
Round: 3
Reviewer: prediction-market-reviewer (independent, blind)

## Round-2 defect disposition verification

All round-2 findings attributed to this lens are genuinely closed:

- Cap-free pre-merge sweep (imports AUD-06a's `R` grid, no cap read): CONFIRMED against AUD-06a's
  current text — the grid `{2, 3, 5, 8, 13, 21}` and the `qty_i = clip(floor(R/ask_i), 1, q_max)`
  form match verbatim between the two plans, so they cannot diverge as claimed.
- Envelope pin cannot advance without a fresh sweep (`ENVELOPE_SWEEP_RECORD_SHA256`): CONFIRMED
  specified with a named test.
- G2 edge-unit convention (`edge_unit: "usd_per_contract_after_fees"`, structural `>1.0` sanity
  bound): CONFIRMED, and it is a sound defence-in-depth pattern — a contractual label plus a
  structural check that does not trust the label.
- In-flight/mid-session gate-lapse disposition: CONFIRMED against source.
  `continuous_strategy.py:2531-2538` (`_maybe_submit`, verified in full below) does construct the
  order with `time_in_force=TimeInForce.IOC, post_only=False` and submit at `self.submit_order(order)`
  immediately after — the IOC/never-rests argument is accurate.

No round-2 disposition is misrepresented.

## Fresh review of the full revision — MATERIAL, new this round

**MATERIAL — §5's D6 no-currency-log claim misdescribes the actual `_maybe_submit` log line, which
today prints price and quantity together and would leak the derived qty the moment sizing stops
being constant.**

File: AUD-06b §5 (second bullet under "Explicitly excluded") and §6 D1/§7 step 3
(`test_the_take_log_line_never_carries_a_derived_quantity`).

Evidence, read from source: the plan states "the `_maybe_submit` INFO line logs instrument, price
and a `qty_present` token. With a price, a qty reconstructs the cap." I read `_maybe_submit` in full
(`src/breezy/strategy/current_rung_hold/continuous_strategy.py:2514-2540`). There is **no
`qty_present` token anywhere in this file** (`grep -n "qty_present"` returns zero hits). The actual
log line, inside `_maybe_submit`'s early-return branch (armed check fails), is:

```
f"{instrument_id} qty={decision.quantity} px={decision.limit_price} "
f"p_hold_lower={decision.p_hold_lower} break_even={decision.break_even}",
```

(`:2523`) — this logs the **raw derived quantity and price together**, verbatim, not a redacted
boolean token. At today's constant `qty=1` this line is harmless (no information — `qty` never
varies). The moment this item ships and `qty` is derived from the per-position cap, this EXISTING,
unmodified log line becomes exactly the leak D6 and MP plan S6 exist to prevent: price plus qty lets
a reader reconstruct `cap ≈ qty × price` to within one lot's precision, directly exposing the
operator-reserved per-position cap this backlog's binding constraints (and L-39) forbid assigning,
restating, or leaking.

This is precisely the class of defect the review brief calls out: "a citation that does not say what
the plan claims is a defect." The plan's own scope-exclusion for the money-safety-critical no-leak
rule is factually wrong about the current code, which risks an implementer believing a redaction
mechanism (`qty_present`) already exists and only needs preserving, when in fact this specific log
line must be actively changed (e.g. `qty` dropped, or replaced with a boolean/threshold token) as
part of this item's own work.

Mitigating factor, and why this is MATERIAL rather than a documentation nit: §7 step 3's
`test_the_take_log_line_never_carries_a_derived_quantity` and §8 AC#5 ("No journal line anywhere
carries a derived qty; proven by the extended scan test, not by review") are worded generally enough
that a correctly-implemented scan test *would* catch this specific line if the implementer thinks to
scan `_maybe_submit`'s early-return log alongside the submission path. But the plan's own §5/§6
description actively misdirects that search by asserting the leak is already closed with a named
token that does not exist — increasing, not decreasing, the odds this exact line is missed. Given
this is the ONE item in the cluster that can move real money and the ONE place where a printed number
directly reconstructs an operator-reserved cap, a wrong citation on the controlling exclusion is not
a cosmetic issue.

Failure: the item ships; the `_maybe_submit` early-return branch continues to log
`qty={decision.quantity} px={decision.limit_price}` with a real derived qty; any operator, log
aggregator, or third party with journal read access can reconstruct the per-position cap from a
single log line, violating the PROGRESS.md:17-24 / L-39 no-read-no-restate-no-leak rule this very
item claims to honor.

Fix: (1) correct §5/§6's description to state accurately what the current log line does (there is no
existing `qty_present` token); (2) explicitly name `continuous_strategy.py:2523` (the `_maybe_submit`
early-return log) as a call site this item must modify — replace `qty={decision.quantity}` with a
redacted form (a boolean presence token, or omit qty entirely) — not merely rely on a generic scan
test to discover it; (3) verify no other log call site in the take/decision path interpolates
`decision.quantity` alongside a price (a targeted grep across `strategy/current_rung_hold/` for
`decision.quantity` combined with `limit_price`/`price` in the same f-string, recorded in the
evidence pack).

## Per-criterion points (cap in parentheses)

- Fidelity to gap and completeness (20): **16** — re-scopes MP-B correctly and adds the edge-gate
  symmetry the audit could not have anticipated. −4 for the material defect: the plan's own
  no-leak exclusion (part of what G-11's "no allocation logic" gap implies must be closed safely)
  misdescribes the current code it claims already satisfies it.
- Technical correctness and evidence grounding (20): **14** — the IOC disposition, the replay-driver
  survey, the native notional cap and the cent-rounding reuse are all independently verified accurate
  this round. −6 for the material defect above, on the single highest-stakes correctness claim in
  the plan (the one guarding against a direct operator-cap leak).
- Implementation specificity and feasibility (15): **9** — the sweep is executable as specified,
  parameterisation named, driver situation resolved by inspection. −6, more than round 2's mark:
  the log-redaction work item is not merely "unwritten" (round 2's framing for the sweep driver) but
  actively mis-specified, which is a worse defect than an unwritten-but-correctly-scoped driver.
- Acceptance criteria and validation quality (20): **15** — AC#5 is worded generally enough to catch
  the leak if implemented faithfully, and AC#6/#7b/#7c/#7d each have negative controls. −5 because
  AC#5 does not name the specific call site it must cover, and the plan text actively points away
  from it (citing a non-existent token), which is exactly the gap between "acceptance criterion
  exists" and "acceptance criterion is reliably exercised."
- Autonomous operation, failure handling, recovery (15): **12** — both gates and every clamp are
  fail-closed with no silent fallback; the mid-session lapse rule is correctly derived from the IOC
  submission path. Matching round 2's mark: rollback still cannot act on already-open positions,
  which is a venue property this plan correctly does not claim to fix.
- Portfolio objective alignment, scope and dependencies (10): **10** — §11 is a field-level
  evaluation contract with fixed baselines, an explicit "this item can REDUCE ROI" row treated as
  load-bearing, a cohort-review revert rule and a falsifier. Per the brief's rule, round 2's
  disposition #9 (no named defect) is resolved here: I find no separate defect in §11 itself
  (the log-leak defect is scored under correctness/specificity, not here), so full marks are
  awarded, matching the round-2 pm score.

**Total: 76/100**

## Required changes to reach 100

1. Correct §5/§6's description of the `_maybe_submit` INFO line — there is no existing
   `qty_present` token; the current line at `continuous_strategy.py:2523` logs
   `qty={decision.quantity} px={decision.limit_price}` directly.
2. Name `continuous_strategy.py:2523` explicitly as a call site this item must modify (redact or
   drop the qty field), rather than relying solely on a generic scan test to discover it.
3. Add a step to the evidence pack (or §7) that greps the full decision/take/submit path for any
   f-string combining `decision.quantity` (or the derived qty variable, post-implementation) with a
   price field, so the scan test's coverage is demonstrably complete rather than assumed.

## Blockers

BLOCKER-A, BLOCKER-B, BLOCKER-C and BLOCKER-D (from the plan itself) remain open and are not
resolvable by any reviewer, as the plan's own §12 states; BLOCKER-C and BLOCKER-D are explicitly
operator-only rulings. The log-line defect above is not a blocker — it is fixable entirely within
this plan's own text and does not require an operator or strategy-lead ruling.
