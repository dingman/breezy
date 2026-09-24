# AUD-06b review — round 6 (delta, FINAL) — mle-reviewer (statistical validation / measurement engineering lens)

Plan: AUD-06b-bounded-allocation-sizing.md
sha256: 6352149b3a62765fedd7babcfbea37152c22fb7dd6f470a6028d453a05ba0c66
Round: 6 (delta review of the round-5 mle minor plus the other reviewer's material)

## Fix verification: the file-count correction

Independently re-ran the cited command myself rather than trusting the plan's re-run:
`/usr/bin/grep -rn --binary-files=without-match "qty=" src/breezy/strategy
src/breezy/adapters/polymarket_us/exec src/breezy/runtime | wc -l` → **58** (unchanged, matches match
count). `/usr/bin/grep -rl --binary-files=without-match "qty=" <same trees> | wc -l` → **20** (matches
the plan's corrected figure exactly, not the withdrawn "14"). The round-5 defect (a wrong headline
number inside a "checkable, not asserted" claim) is closed, and closed mechanically: §7 step 3's
evidence requirement now includes the distinct-file count, and AC #5/the scope-equality test assert
that count equals `len(set(files))` from the same run, so this exact class of drift cannot recur
silently.

## Fix verification: the two-content-hash registry strengthening

Independently re-verified all three cited sites against source, without trusting the plan's account:

- **R9 — `running_extreme_lock/strategy.py`.** `_maybe_submit` def at `:359`; call
  `self._submit_delta(contract, risk_decision.clipped_quantity, decision)` at `:408` — CONFIRMED exact.
  `_submit_delta` def at `:410`, containing the `qty=`/`edge=` log line — CONFIRMED, matches the plan's
  `:410-432` citation.
- **R7 — `cli_settlement_print_lock/strategy.py`.** `_maybe_submit` def at `:761`; call
  `self._submit_delta(contract, risk_decision.clipped_quantity, decision, quote)` at `:837` —
  CONFIRMED exact, matching the plan's citation precisely. `_submit_delta` def at `:901`, containing the
  `qty=`/`limit=`/`edge=` log line at `:938-939` — CONFIRMED, matches the `:901-941` citation.
- **R8 — `runtime/backtest_harness.py`.** `_refuse_open_positions` def at `:833`, containing the
  `qty=`/`avg_px_close=` line at `:845` — CONFIRMED exact. `position.quantity` is read from
  `engine.cache.positions_open()`, i.e. a native Nautilus `Position` object's own attribute, set by the
  framework's fill-processing internals — CONFIRMED there is no Breezy-side assignment to hash, so the
  plan's `assigned_at: "nautilus:Position.quantity (no breezy assignment)"` disposition is an honest,
  correctly-reasoned limit rather than a gap papered over.

**Judgment on feasibility.** Hashing the normalised source text of two named, small, stable functions
(`inspect.getsource()` plus comment/whitespace normalisation is a standard, already-available technique)
is a proportionate, buildable mechanism — not the disproportionate "hash each family's whole
order-construction path" the plan explicitly declines. The RED test
(`test_a_registered_site_goes_red_when_its_upstream_assignment_changes`, mutating `_maybe_submit`'s
computation while leaving the emitted line byte-identical) is the correct test for exactly the gap it
closes: it proves the guard catches an upstream semantic change the syntactic expression-pin alone would
miss, which is precisely what R7/R9's previously-overstated "RED before the line ships" claim needed and
did not have.

**Judgment on the stated Nautilus-owned-quantity limit.** Honest and sufficient. Since Nautilus is
immutable (this repo's foundational constraint) and `Position.quantity` is computed entirely inside the
framework, there is genuinely no Breezy function to hash for R8/R13 — the only way that value could ever
become cap-derived is through a *different*, already-covered code path (the live order submission that
creates the position), not through this backtest-only, explicitly out-of-scope site. Disclosing this as
a stated limit rather than silently omitting the second hash is the correct, non-misleading choice.

## Fresh review — no new defect found

Every citation touched by this revision (§6 D6-R's lead-in, the R7/R8/R9 rows, the new "what the
registry pin actually guarantees" paragraph, §7 step 3's new test and evidence requirement, §8's
criterion 5 restatement) was independently re-verified against source this round and holds exactly. I
found no drift, no unsupported claim, and no regression in the sections this diff touches or is adjacent
to (AC numbering stays consistent; the existing five tests are correctly renumbered to six without a
collision).

## Per-criterion points (cap in parentheses)

- Fidelity to the gap and completeness (20): **20** — the enumeration is genuinely complete (58/58
  matches, all 20 files accounted for) and the registry now closes both the syntactic and the
  upstream-semantic gap.
- Technical correctness and evidence grounding (20): **20** — every citation independently re-verified
  exact; the file-count and the registry-guarantee defects are both closed with mechanically-enforced
  fixes, not prose reassurance.
- Implementation specificity and feasibility (15): **15** — the two-hash mechanism is concretely
  specified, feasibility-checked at three real sites, and uses a standard, available technique;
  R8/R13's stated limit is honestly scoped rather than hidden.
- Acceptance criteria and validation quality (20): **20** — AC #5 and the scope-equality test now
  mechanically assert both the file count and the registry's two-hash coverage.
- Autonomous operation, failure handling, recovery (15): **15** — unaffected by this revision; unchanged
  from round 5 (rollback's inability to act on already-open positions remains an honestly-named venue
  property, not a plan defect).
- Portfolio objective alignment, scope, dependencies (10): **10** — unaffected.

**Total: 100/100**

## Remaining defects and required changes

None found this round.

## Blockers

- **BLOCKER-A (AUD-06a):** the validated qty envelope and its staleness predicate — unchanged, genuine.
- **BLOCKER-B (AUD-02):** a demonstrated edge for this family, itself downstream of AUD-05 — unchanged,
  genuine.
- **BLOCKER-C (operator):** R-12, the session order-count ceiling question — unchanged, genuine,
  operator-only.
- **BLOCKER-D (operator):** the per-position spend question — unchanged, genuine, operator-only.
