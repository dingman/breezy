# AUD-06b review — round 4 (FINAL) — mle-reviewer (statistical validation / measurement engineering lens)

Plan: AUD-06b-bounded-allocation-sizing.md
sha256: 66bb226eda77a0a04f846e06b322b8c7f535f594827fce98b98a4077cbd058c6
Round: 4

## Claims verified (unchanged from the initial round-4 pass)

- D6-R's six-site co-emission enumeration (`continuous_strategy.py:2523`, `:2439`; `strategy.py:682,
  689,702,741`; `backtest_only.py:112`; `OfferTapeRecord`; `DurableFillRecord`) — CONFIRMED exact by
  independent grep for every site.
- `order_enablement.py:86-92`'s "never a value" precedent — CONFIRMED, the extension is principled, not
  a second policy.

## Reconciliation

**Fidelity to the gap and completeness — withheld 3/20 originally.** The sole named reason
("`max_equity_fraction` remains a stated, triggered deferral") is another item's scope (AUD-06a/G-11),
with a stated re-evaluation trigger recorded in §12. Not fixable by this plan's text.
**Disposition: AWARD in full.** → **20/20**

**Technical correctness and evidence grounding — withheld 3/20 originally.** The reason given ("the `R`
grid and the `1.0` USD sanity bound remain reasoned, not measured, constructions") does not survive
scrutiny as a defect: the `R` grid is explicitly IMPORTED from AUD-06a's own registered sweep, never
re-chosen here (verified identical in both plans' texts), and the `1.0` USD bound is not an assumption
needing empirical grounding — it is a **structural** bound (no per-contract edge can exceed a binary's
whole `[0,1]` payout), true by construction, not "reasoned" in the sense of an arbitrary choice that
could be wrong. Calling a provably-true structural bound a weakness was a mischaracterization carried
forward from an earlier round without re-examination.
**Disposition: AWARD in full.** → **20/20**

**Implementation specificity and feasibility — withheld 4/15 originally.** "The new offline driver is
scoped but unwritten, and step 7a depends on an AUD-06a entry point that does not exist until that item
ships" is, on inspection, already fully captured by §12's own **BLOCKER-A** (the validated qty envelope
and its staleness predicate) — a plan document specifying code that is not yet written is inherent to
being a plan, and the cross-item sequencing risk is the same dependency BLOCKER-A already names; no
additional plan-text change closes it beyond what BLOCKER-A already states. Awarded (3 points).
**A genuine, previously unnamed gap found on this re-reading:** D6-R's disposition for site R2
(`continuous_strategy.py:2439`'s persisted duplicate-fill record) states the qty/price pairing "must
never be copied into an alert `detail`, an evidence artefact, or any off-host payload," and claims this
is "enforced by the scan test below, which covers alert payloads and evidence writers." On inspection,
the four site-named tests actually listed in §7 step 3
(`test_the_unarmed_take_log_line_carries_no_quantity_field`,
`test_no_log_or_alert_line_in_the_take_path_carries_a_quantity_and_a_price_together`,
`test_the_offer_tape_record_never_gains_a_derived_quantity_field`,
`test_no_alert_payload_detail_carries_a_quantity_and_a_price_together`) cover the log-line, offer-tape
and alert-payload surfaces — but **none scans evidence-writer code paths** (e.g. the `scripts/analysis`
modules that render `docs/evidence/*.md` artefacts from ledger/latch contents) for a co-occurring
qty+price copied out of the persisted duplicate-fill record. The "evidence writers" half of R2's own
enforcement claim is unfulfilled by the actual test list.
**Disposition: keep 1 point withheld. Required change:** add a fifth site-named test (e.g.
`test_no_evidence_artefact_writer_copies_the_duplicate_fill_records_qty_and_price_together`) scanning
the evidence-pack-writing code paths for the same qty+price co-occurrence the other four tests forbid
elsewhere, so R2's stated enforcement claim is actually backed by a test. → **14/15**

**Acceptance criteria and validation quality — withheld 4/20 originally.** "AC#8/#9 remain
unexercisable until trading resumes — declined rather than softened" is correctly named as an
intentional, non-softened deferral of a money-path criterion (the correct discipline this backlog
requires); awarded (3 points). **One point kept**, tied to the same evidence-writer gap above: AC#5 does
not require the evidence-writer scan, so nothing in §8 would catch its absence.
**Disposition: award 3, keep 1 withheld. Required change:** extend AC#5 to require the new
evidence-writer test above, with its RED→GREEN pair and backing grep output in the evidence pack,
matching the standard already applied to the other four D6-R sites. → **19/20**

**Autonomous operation, failure handling, recovery — withheld 3/15 originally.** "Rollback genuinely
cannot act on already-open positions, a venue property this plan does not claim to fix" is an honestly
named venue property (IOC orders never rest; there is no resting order to cancel by construction) —
not something a plan for a different order-sizing feature can fix.
**Disposition: AWARD in full.** → **15/15**

**Portfolio objective alignment, scope, dependencies — already 10/10.** No change.

## Final per-criterion points (cap in parentheses)

- Fidelity to the gap and completeness (20): **20**
- Technical correctness and evidence grounding (20): **20**
- Implementation specificity and feasibility (15): **14**
- Acceptance criteria and validation quality (20): **19**
- Autonomous operation, failure handling, recovery (15): **15**
- Portfolio objective alignment, scope, dependencies (10): **10**

**Total: 98/100**

## Remaining defect and required change

1. **MINOR.** D6-R's disposition for the persisted duplicate-fill record (R2,
   `continuous_strategy.py:2439`) claims enforcement by "the scan test below, which covers alert
   payloads and evidence writers" — but the four tests actually specified in §7 step 3 cover only
   log lines, the offer tape, and alert payloads, not evidence-writer code paths. **Required change:**
   add a fifth, evidence-writer-scoped test (and extend AC#5 to require it) so the "evidence writers"
   half of the enforcement claim is actually backed by a test rather than asserted.

## Blockers

- **BLOCKER-A (AUD-06a):** the validated qty envelope and its staleness predicate — unchanged, genuine;
  also covers the "AUD-06a entry point does not exist yet" implementation-specificity concern raised in
  round 3 (not a separate deduction).
- **BLOCKER-B (AUD-02):** a demonstrated edge for this family, itself downstream of AUD-05 — unchanged,
  genuine, and correctly the largest structural reason this item is P3.
- **BLOCKER-C (operator):** R-12, the session order-count ceiling question — unchanged, genuine,
  operator-only.
- **BLOCKER-D (operator):** the per-position spend question — unchanged, genuine, operator-only, posed
  but not answered by this plan as required.
