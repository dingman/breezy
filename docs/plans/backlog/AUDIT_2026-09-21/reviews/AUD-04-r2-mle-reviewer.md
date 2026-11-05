# AUD-04 review — round 2 — mle-reviewer (statistical validation / measurement engineering lens)

Plan: AUD-04-portfolio-roi-measurement.md
sha256: a6c079912ac3b359b1dbf49ecec87df9182118834529c774dcfc6080599b7b8d
Round: 2
Reviewer: mle-reviewer (independent, blind)

## Round-1 remedy verification

| # | R1 defect (mine) | Verified in body against source |
|---|---|---|
| 1 (mine, MATERIAL) | no versioned output schema | CONFIRMED fixed and premise corrected honestly. §6 D7 adds `schema_version: 1`, additive-only-within-major policy, and a single sanctioned reader `read_portfolio_roi_report()` raising `UnknownPortfolioRoiSchemaError`. I independently re-verified the cited precedent: `station_observation.py:110,126,213,234,248` (declared field, constructor default, `to_dict`, `from_dict`, and `pa.field("schema_version", pa.int64(), nullable=False)`) and `trial_day_latch.py:1221` both carry the idiom exactly as claimed — this is a correct, checkable citation, not a restatement. |
| 2 (mine, MATERIAL) | no frozen-input detector | Present as D8. See NEW finding below — the mechanism exists but has a real gap in its own semantics that round 1 did not test for. |
| 3 (mine+pm) | tolerance asserted without basis | CONFIRMED re-derived: `TOLERANCE_day = n_fills_that_day × $0.01`, grounded in `_round_cost_up_to_cent` (`operator_controls.py:218-225`, re-read directly — confirmed it is the shared quantisation the plan claims, used by both `order_cost_usd` and the true-up booking). This is a legitimate derivation, not an asserted number. |
| 4 (mine+pm) | balance-line parser unspecified | CONFIRMED, anchor + fixture-from-step-0 + fail-closed UNKNOWN specified in §7 step 2. |

I re-checked the other three (5-9) against the record described in round 1's dispositions and find
the described text present in the current body (leg-aware capital-deployed test at §7 step 1, power
caveat header line pinned in §7 step 3 and §8 AC#3, standing cross-check in §8 AC#4, AC#2 restated
around a measured-not-assumed count). No discrepancy found between §13's claimed remedy and the
plan body for these.

## NEW finding this round (whole revised plan, source-checked)

**MATERIAL — D8's frozen-input alert fires once per streak and then goes permanently silent for
the duration of an ongoing outage, unlike every other alert this backlog round ships.**

File: AUD-04 §6 D8, §8 AC#6, §9 "Inputs present but frozen."

The mechanism: a streak counter persisted in `.input_freshness.json`; when
`days_since_newest_input > 3` for ≥3 consecutive runs, emit ONE WARN,
"**latched: one alert per streak, re-armed only when the streak resets to 0**." Re-arming requires
`days_since_newest_input` to drop back under the threshold — which requires a NEW ledger fill or
scored trial to arrive. If the underlying cause is a genuinely dead pipeline (not benign
no-trading), no new input will ever arrive, so the streak never resets, and the single WARN fired on
day 3 (of continuous staleness) is the *only* signal this control will ever produce — for a month,
a quarter, indefinitely. Compare this directly against the sibling alert this same backlog round
ships in AUD-05 (§6 D-F, same sink): "**Latched: one alert per `(family_id, UTC day)`... so a
repeating daily failure pages once a day, not once per retry**" — i.e. AUD-05 deliberately re-pages
daily for as long as the failure persists, while AUD-04's D8 pages exactly once for the life of an
arbitrarily long outage. This is not a nitpick about alert-fatigue tuning; it is a genuine gap in
monitoring an unattended scheduled job over an indefinite silent period, which is exactly this
review's lens. §9's stated honest limitation ("today a frozen input is the *expected* state... the
detector's first job is to make that state legible, not to signal a regression") explains why the
alert exists at all, but does not address what happens on day 30 of a *genuine* pipeline death that
started identically to the expected quiet state — an operator who dismissed or missed the one WARN
on day 3 gets no further reminder ever, from a component whose entire job is catching exactly this
failure mode.
Fix: either (a) re-emit the WARN on a coarser daily cadence for as long as the streak remains ≥3
(e.g., once per (streak-bucket, UTC day) the same way AUD-05's D-F re-pages daily), or (b) escalate
severity on a second threshold (e.g., WARN at 3 consecutive stale runs, CRITICAL at 14) so a
month-long silent outage does not rely on a single message from three weeks earlier having been
seen and remembered.

**MINOR — AC #6's "fires exactly once... does not repeat until the streak resets" is stated as an
acceptance criterion, which locks in the gap above as intended behaviour rather than a defect to
fix.** Once this MATERIAL item is addressed, AC #6 must be rewritten to match the new re-arm
semantics rather than asserting the current single-shot behaviour as correct.

## Verification of the four brief-specified checks for AUD-04

- **`schema_version` + refusing reader:** CONFIRMED present and correctly specified (D7, precedent
  citations hold).
- **`PORTFOLIO_ROI_INPUTS_FROZEN` latch semantics — when can it be false, does it clear:** the streak
  clears to 0 the moment `days_since_newest_input` drops back at or under the threshold on any run
  (i.e., a new fill or scored trial lands), and the alert is false/silent at every run before the
  3rd consecutive stale run. This much is well-specified and I found no ambiguity in it. **What is
  under-specified is re-arming during a continuous outage — see the MATERIAL finding above.**
- **Behaviour on missing inputs:** §9 states ledger-absent/unreadable returns `None` (never `0`) and
  exits 1 with a named reason; scored-store-empty-but-ledger-has-fills labels every fill
  `unreconciled` rather than reporting a hollow ROI. Both are correctly fail-closed and distinct from
  the "present but frozen" case D8 targets — the plan does not conflate "absent" with "frozen," which
  is the right design boundary.

## Per-criterion points (cap in parentheses)

- Fidelity to the gap and completeness (20): **18** — matches the author's own honest self-docking
  (balance series vs true equity curve); G-03 otherwise fully addressed.
- Technical correctness and evidence grounding (20): **17** — every citation re-checked this round
  (Nautilus call sites from round 1 stand unchanged since no code in `src/` moved; the D7 precedent
  citations and the D4 rounding-function citation both independently re-verified true). The step-0
  UNVERIFIED null hypothesis about closed positions remains open by design, which is honest, not a
  defect.
- Implementation specificity and feasibility (15): **13** — matches round 1's assessment; loaders
  named by reuse rather than signature is a real but minor gap, unchanged this round.
- Acceptance criteria and validation quality (20): **16** — AC #6 needs the rewrite named above once
  the re-arm semantics change; every other criterion is measurable and testable as written.
- Autonomous operation, failure handling, recovery (15): **10** — docked below the author's 14
  because the frozen-input detector, this item's own headline fix for a MATERIAL round-1 defect, has
  a real re-arm gap that undermines its purpose for exactly the failure mode it exists to catch (an
  indefinitely dead pipeline). This is the same class of defect round 1 found and fixed once already
  in this item; it recurs in the fix itself.
- Portfolio objective alignment, scope, dependencies (10): **8** — matches the author's score; the
  field-level evaluation contract (§11) is concrete, the baselines are fixed before any number is
  read, and the plausible-vs-demonstrated framing is honest about measuring ROI over a near-empty
  6-fill record. No further defect found here; the criterion's own structure (this item is the
  measurement substrate, not a source of ROI itself) caps it below 10 regardless.

**Total: 82/100**

## Required changes to reach 100

1. Fix D8's re-arm semantics so a continuous, indefinite outage produces more than one signal over
   its lifetime — see the MATERIAL finding above.
2. Rewrite AC #6 to match the corrected re-arm behaviour.
3. Carried from round 1, still true: name the loaders' exact function signatures for the scored-trial
   and residual readers rather than "reuse of `family_tally_v2.py`."

## Blockers

None requiring operator/strategy-lead ruling. Both defects found this round are build-side fixes.
