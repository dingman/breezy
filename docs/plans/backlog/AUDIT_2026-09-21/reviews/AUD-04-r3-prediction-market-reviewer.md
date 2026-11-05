# AUD-04 — Round 3 review (prediction-market-reviewer, portfolio accounting/risk lens)

Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-04-portfolio-roi-measurement.md
SHA256: 6d29c68a1f6f018ddbd8bb382dd1cbbc1dd7503c5edfd3b71c26d7e23055d0df
Round: 3
Reviewer: prediction-market-reviewer (independent, blind)

## Round-2 defect disposition verification

Both round-2 required changes are ACTUALLY implemented, not just claimed in §13:

- Worked two-day D4 example: CONFIRMED. §6 D4 replaces the four-term identity with the pure cash
  form `unexplained(D) = Δbalance(D) − proceeds(D) + capital_deployed(D)`; the worked table (buy
  $0.40+$0.03 on D1, settle $1.00 on D5) reconciles to `0` on both days independently, with
  `Σ Δbalance = Σ realised P&L = +0.57`. I substituted the round-1 four-term form myself
  (`realised_pnl = proceeds − cost − fee`) and reproduced the double-count the plan describes; the
  new cash-only identity does not have that defect — verified algebraically against a settled
  winning YES, a settled losing NO (symmetric, no sign special-case per the table), and an
  unsettled open position (contributes to `capital_deployed` only, `unexplained == 0` trivially
  since no `Δbalance`/`proceeds` term exists yet for it).
- Loader signatures: CONFIRMED against source, all four exact —
  `read_scored_trials(directory: Path) -> tuple[ScoredTrial, ...]` (`scored_trial_store.py:118`),
  `residual_trial_ids(store_dir: Path) -> frozenset[str]` (`persistence/residual_fills.py:234`),
  `admissible_scored_trials(rows, *, residual_trial_ids) -> tuple[ScoredTrial, ...]`
  (`persistence/realized_draws.py:187-189`), `DurableFillRecord` (`exec/client.py:641`) under
  `FILL_KEY_PREFIX` (`:384`, confirmed `FILL_KEY_PREFIX: Final[str] = f"{STATE_KEY_NAMESPACE}fill/"`).
- `_round_cost_up_to_cent` re-anchor: CONFIRMED at `operator_controls.py:220`, `order_cost_usd` body
  through `:244` (calls it at `:244`) — the `:220-244` citation is accurate.

No round-2 disposition is misrepresented.

## Fresh review of the full revision (new defect, round-3 lens)

**MINOR — the D4 identity has no named source for "settlement date", and neither ledger record
carries one.**
File: AUD-04 §6 D4 (term scoping), §7 step 2 (loader signatures).
Issue: D4 defines `proceeds(D)` as the sum over positions whose "settlement is dated D". I read
`DurableFillRecord` in full (`exec/client.py:641-710`): its only timestamp is `ts_event` (the FILL
time), not a settlement time — there is no settlement field anywhere on the ledger. I then read
`ScoredTrial` (`settlement/trial_scorer.py:131-151`) and `score_trial` (`:163-227`): it carries
`climate_day` (the date the weather event covers) and `scored_at_ns` (when the scoring script ran),
neither of which is a persisted venue settlement/payout timestamp either. So "the day proceeds hit
the balance" is not literally recoverable from any field the plan names — an implementer must pick
one (most plausibly `scored_at_ns`'s UTC day, which is *when settlement info became available to
Breezy*, not necessarily when the venue credited the account) without the plan saying so. The
report's own self-score already flags this precisely ("the ledger's settlement-date field has not
been named from source"), so this is a self-conceded, still-open gap, not a new hypothesis.
Failure: if `proceeds(D)` is dated by `climate_day` (the weather day) rather than an actual
credit/scoring day, and the venue does not credit the account until several days later (residual
protocol, NWS revision windows, or the venue fallback at scheduled_release + 7 days all imply
multi-day lags are routine), `unexplained(D)` will show a nonzero delta on both the assumed day and
the true credit day even though nothing is actually wrong — exactly the false-page risk this
detector exists to avoid (WP-R1). This is a genuine correctness risk in an artefact whose entire job
is catching unexplained money movement, the same class of finding round 2 raised and fixed for the
four-term identity.
Fix: name the field D4 actually reads for "settlement is dated D" (most defensible candidate:
`scored_at_ns`'s UTC calendar day, since that is the only timestamp on a `ScoredTrial`), state the
known lag this introduces relative to the venue's true credit date as an explicit caveat in the
artefact header, and add the assertion to step 0(a)/(c) so the real record's lag between
`climate_day` and `scored_at_ns` is measured before the tolerance is trusted.

No MATERIAL defect found. The partition invariant, the leg-sum correctness (verified:
`no_leg_instrument_id`/`leg_of` at `symbology.py`), the cash-identity worked example, the schema-
version refusal, the re-alert ladder's period-key/restart/clear semantics, and the B0/B1 baseline
separation are all sound and re-verified this round against current source.

## Per-criterion points (cap in parentheses)

- Fidelity to gap and completeness (20): **19** — every element of G-03 covered; the balance-vs-
  equity-curve honesty is a transparent scope statement. −1 continuing the round-2 mark, not a new
  deduction: "equity curve" is delivered as a balance-log proxy.
- Technical correctness and evidence grounding (20): **18** — the D4 double-count is now genuinely
  fixed (verified by substitution), not merely documented; all four loaders and the alert API
  re-verified line-for-line against current source. −2 for the unresolved settlement-date field
  above, which is exactly the kind of ambiguity that produced the round-2 defect.
- Implementation specificity and feasibility (15): **13** — files, timer tick, lock discipline,
  parser anchor, schema policy, loader signatures all pinned. −2 for the same settlement-date gap
  (an implementer still has to choose a field D4 never names).
- Acceptance criteria and validation quality (20): **18** — AC#4's join-key definition, AC#9's
  worked-example requirement, and the ladder tests are all concrete and machine-checkable. −2
  because no AC requires the settlement-date field itself to be named/tested, so an implementer
  could satisfy every AC while still choosing the wrong field.
- Autonomous operation, failure handling, recovery (15): **15** — the re-alert ladder closes the
  round-2 MATERIAL gap in full: persisted restart-surviving latch, one-way escalation within a
  streak, observable clear. Fully met.
- Portfolio objective alignment, scope and dependencies (10): **10** — §11 is a complete field-level
  evaluation contract with two registered baselines fixed before any number is read, an explicit
  falsifier, and a stated dependency stage. Per the brief's rule ("a deduction with no named defect
  and no requested change is not actionable"), disposition #8 from round 2 is resolved here: I find
  no defect in §11 itself, so the withheld points are awarded in full, matching the round-2 pm score.

**Total: 93/100**

## Required changes to reach 100

1. Name the field D4 actually uses for "settlement is dated D" — since neither `DurableFillRecord`
   nor `ScoredTrial` carries a true venue settlement/credit timestamp, either (a) name
   `scored_at_ns`'s UTC day as the operational definition and state the known lag as a caveat, or
   (b) if a settlement timestamp is added elsewhere in this item's scope, cite it. Add a step-0
   measurement of the `climate_day`→`scored_at_ns` lag on the real record.
2. Add an acceptance criterion / test asserting the settlement-date field used by D4 matches the
   one documented, so a future implementer cannot silently substitute `climate_day`.

## Blockers

None. No operator-reserved value is read or assigned; the baseline choice remains a build decision,
not a PREREG endpoint. The settlement-date gap above is fixable entirely within this plan's own text
and does not require an operator/strategy-lead ruling.
