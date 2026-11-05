# AUD-06b — Round 4 (FINAL) — prediction-market-reviewer

Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-06b-bounded-allocation-sizing.md
sha256: 66bb226eda77a0a04f846e06b322b8c7f535f594827fce98b98a4077cbd058c6
Round: 4 (final for this cluster)
Reviewer: prediction-market-reviewer (portfolio accounting / risk)

## Claims verified against source (this round)

- Round-3's central finding was that `continuous_strategy.py:2523` co-emits
  `qty={decision.quantity} px={decision.limit_price}` in one f-string, and that revision 3's
  `qty_present` redaction claim was fictional. Re-verified directly: `_maybe_submit`'s unarmed
  early-return INFO log at `continuous_strategy.py:2523` is EXACTLY as quoted, and
  `/usr/bin/grep -rn "qty_present"` returns zero hits repo-wide — CONFIRMED.
- `continuous_strategy.py:2439` (`_latch.record_duplicate_fill(qty=…, fill_px=…, fee=…)`) —
  CONFIRMED exact call, a persisted record carrying qty and fill price together.
- `strategy.py:682, :689, :702, :741` — CONFIRMED exact, all four `qty=` sites in the non-continuous
  `current_rung_hold` strategy.
- `backtest_only.py:112` — CONFIRMED exact.
- `OfferTapeRecord.to_dict` — not independently line-checked this round beyond the plan's own citation
  (`:183-248`); no `qty=` token found via grep in `offer_tape.py`, consistent with the plan's claim
  that it carries no order-quantity field today.
- `DurableFillRecord` — the venue's own fill record; correctly out of scope as the observed fact of
  what happened, not a Breezy-derived sizing decision.

## Completeness check of the D6-R enumeration (ran the grep myself, per the brief)

The plan states the enumeration is "the complete enumeration of sites ... a literal
`/usr/bin/grep -rn "qty=" src/breezy/strategy src/breezy/adapters/polymarket_us/exec
src/breezy/runtime`". **I ran exactly this command.** It is NOT complete relative to its own stated
method:

- `src/breezy/strategy/cli_settlement_print_lock/strategy.py:938` —
  `f"ORDER {contract.instrument_id} qty={signed_delta:+.1f} " f"limit={limit_price} intent=LONG_YES
  edge={decision.edge:.3f} " f"reason={decision.reason}"` — a **qty and a limit price emitted
  together in one f-string**, falling squarely within the stated grep's scope
  (`src/breezy/strategy`), and absent from the R1-R6 table.
- `src/breezy/runtime/backtest_harness.py:845` — `f"{position.instrument_id} qty={position.quantity}
  " f"(avg_px_close={position.avg_px_close})"` — qty and price together, within
  `src/breezy/runtime`, also absent from the table.
- (Checked and found NOT co-emitting with a price, so correctly not defects: `forecast_mispricing/
  strategy.py:498`, `calibration_mean_reversion/strategy.py:524`, `forecast_revision/strategy.py:513`
  — all "FLATTEN ... qty=... working=... reason=..." with no price token on the line;
  `running_extreme_lock/strategy.py:430` similarly has no price on the same line.)

This matters because these strategies are NOT the family this item sizes, so — by the same reasoning
the plan already gives for R3/R4 (`strategy.py`, `backtest_only.py`) — today's qty on those lines is
either fixed or not yet cap-derived and leaks nothing *today*. But the plan's own §7 step 3 scan test
is explicitly scoped to `src/breezy/strategy/current_rung_hold/` and
`src/breezy/adapters/polymarket_us/exec/` only — narrower than the grep command the plan cites as the
source of its "complete enumeration" claim. If any future item derives a variable qty for
`cli_settlement_print_lock` (a real, currently-armed-adjacent strategy per its own file, distinct
from `strategy.py`/`backtest_only.py` which the plan correctly marks dormant), no RED test in this
item's scope would catch the co-emission at `:938`, because it was never named and the scan test
never covers that directory. The gap is in the plan's completeness claim and its evidence-pack
methodology, not in today's live behaviour.

## Persisted-record disposition (R2: keep qty in `record_duplicate_fill`, containment not deletion)

Checked against `docs/core/PROGRESS.md`'s operator control contract (`:17-24`): the two reserved
controls live "ONLY in the operator's gitignored `operator.env`" and are enforced by
`DailySpendLedger`. That binding text governs where the RAW cap VALUE lives, not whether a
downstream artefact happens to make it reconstructable to a human holding both numbers. Keeping the
reconstructable `qty`+`fill_px` pair in an internal, host-local persisted record (never copied
off-host, never into an alert `detail` or evidence artefact) is a reasonable, narrower containment
than deleting operationally load-bearing data, and does not itself violate the letter of the
contract. **However**, the plan's own text says this containment is "Enforced by the scan test
below" — I checked §7 step 3's actual test list and found no test asserting that the duplicate-fill
latch FILE itself is never copied wholesale into an evidence artefact or an off-host payload. The
four named tests cover log lines, the offer-tape record shape and alert-payload details — none of
them is a file-copy guard. The claim of enforcement is broader than what is actually specified.

## Defects

1. **MATERIAL — the D6-R enumeration is not complete relative to the plan's own stated grep
   command**, and the standing scan test's scope (`current_rung_hold/` + `polymarket_us/exec/` only)
   is narrower than what the cited command covers, silently excluding a genuine qty+price
   co-emission at `cli_settlement_print_lock/strategy.py:938` and `runtime/backtest_harness.py:845`.
   **Required change:** either (a) narrow the cited grep command in §6 D6-R's lead-in to match what
   was actually enumerated (`src/breezy/strategy/current_rung_hold src/breezy/adapters/
   polymarket_us/exec src/breezy/runtime`), so the "complete enumeration" claim is accurate about its
   own method, or (b) run the broader command as literally stated and add named rows for the two
   omitted sites with an explicit disposition (most likely "out of this item's live scope but in the
   scan test's scope", mirroring R3/R4's treatment) — and widen the scan test's directory scope to
   match. AC #5's evidence-pack grep output will otherwise silently contradict the table it is meant
   to back.
2. **MINOR — R2's disposition claims "enforced by the scan test below" for a property (the persisted
   duplicate-fill record is never copied into an evidence artefact) that no test in §7 step 3 actually
   checks.** **Required change:** either name a fifth test (e.g.
   `test_the_duplicate_fill_latch_file_is_never_referenced_by_an_evidence_pack_writer`) or restate the
   claim as an operational rule enforced by code review / directory convention rather than by a test
   that does not exist.

## Per-criterion points (cap in parentheses)

- Fidelity to gap and completeness (20): **17** — closes the G-11 "no allocation logic" cap-leak
  surface with a per-site table rather than a generic assumption, and correctly withdraws revision
  3's fictional `qty_present` claim. −3 for defect #1: the completeness claim does not survive
  running the plan's own cited command.
- Technical correctness and evidence grounding (20): **16** — the single highest-stakes correctness
  claim from round 3 (the `:2523` co-emission) is now correctly stated and fixed, and every cited
  line for R1-R4 re-verified exact. −4 for defect #1 (an incomplete enumeration presented as complete
  is a correctness claim about evidence, not just a documentation nicety) and defect #2 (an
  enforcement claim not backed by the named test).
- Implementation specificity and feasibility (15): **10** — the redaction work is now a per-site
  table with named dispositions and four named tests, a real improvement over "unwritten and
  mis-specified". −1 for defect #2 (a fifth test needed for the persisted-record claim). Held at the
  round-3 mle mark for the still-unwritten offline sweep driver and the still-not-yet-existing
  AUD-06a entry point step 7a depends on.
- Acceptance criteria and validation quality (20): **15** — AC #5 requires the `:2523` diff, a
  RED→GREEN pair and the backing grep output; AC #6/#7b/#7c/#7d retain their negative controls; the
  property test (AC #2) is unconditional. −5: AC #5's own text asks for "the literal grep output
  backing the §6 D6-R enumeration ... so the scan test's coverage is demonstrated complete rather
  than assumed" — but that evidence, if actually produced by the stated command, contradicts the
  table it is meant to validate (defect #1); AC #5 as written cannot currently be satisfied honestly.
- Autonomous operation, failure handling, recovery (15): **12** — both gates and every sizing clamp
  stay fail-closed with no silent fallback; the mid-session IOC lapse rule is grounded in the actual
  submission path. Held at the round-3 mark: rollback genuinely cannot act on already-open positions,
  a venue property this plan correctly does not claim to fix.
- Portfolio objective alignment, scope, dependencies (10): **10** — §11 is a field-level evaluation
  contract with fixed baselines, an explicit "this item can REDUCE ROI" row treated as load-bearing,
  a cohort-review revert rule and a falsifier; both round-3 reviewers awarded 10/10 with no named
  defect, and I find none either.

**Total: 80/100**

## Required changes to reach 100

1. Fix defect #1: reconcile the D6-R enumeration's stated methodology with its actual output — either
   narrow the cited grep command to match the current table, or run it as stated and add the two
   omitted sites (`cli_settlement_print_lock/strategy.py:938`, `runtime/backtest_harness.py:845`)
   with a named disposition, widening the scan test's directory scope to match whichever command is
   the one actually claimed.
2. Fix defect #2: add a test (or downgrade the claim) for the "never copied into an evidence
   artefact" property of the persisted duplicate-fill record.

## Blockers (named separately, not scored as deductions)

- **BLOCKER-A** — AUD-06a's validated qty envelope and staleness predicate (unresolved dependency,
  not this plan's to close).
- **BLOCKER-B** — AUD-02's family-scoped edge estimate with a CI excluding 0 (unresolved dependency).
- **BLOCKER-C** — operator ruling, R-12, on the permit's session order-count ceiling.
- **BLOCKER-D** — operator ruling on whether the current per-position cap is still the intended
  per-order spend once qty is derived from it.

None of these four are resolvable by this reviewer or by any plan-text change; they are correctly
named as blockers rather than decided in-plan.
