# AUD-05 — Round 5 (FINAL) — prediction-market-reviewer

Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-05-live-family-tally-unit.md
sha256: 30c9341d411008e64fc4a0eed6247200babddb021c1fe1c151b0218e865ca949
Round: 5 (final)
Reviewer: prediction-market-reviewer (portfolio accounting / risk)

## Claim verified: mixed-side `mean ask` cell label, concretely specified and tested

Read from source before checking the plan's claims: `STRATUM_TABLE_HEADER`
(`scripts/analysis/family_tally_v2.py:182-184`) and `STRATUM_TABLE_DIVIDER` (`:185`) are the fixed
strings quoted; `_fmt_stratum_row` (`:830-835`) formats one row exactly as quoted
(`f"| {stratum.label} | {stratum.n} | {stratum.k} | {stratum.mean_ask:.4f} | {stratum.pi:.4f} | "
"{stratum.wilson_lower:.4f} | {stratum.wilson_upper:.4f} | {dead} |"`); rows render at `:1075`
(`pooled`) and `:1077` (the two frozen strata), both inside the header/divider block added at
`:1071-1072`. `StratumV2` (`current_rung_hold_v2.py:386-402`) carries no side field today —
CONFIRMED, all exact.

§6 D-A(ii) specifies the fix concretely: a keyword-only `side_mix` argument to `_fmt_stratum_row`
computed at the call site from the same row sequence the stratum was built from, three exact
literals (`""`, `" (NO-only)"`, `" (mixed-side: Y<n>/N<n>)"`) appended inside the `mean ask` cell,
plus one price-domain footnote emitted exactly once whenever any annotation is present.
`STRATUM_TABLE_HEADER`/`STRATUM_TABLE_DIVIDER` and `StratumV2` are deliberately left unchanged —
CONFIRMED this is what keeps AC #5's all-YES byte-identity floor intact, since the header/divider
strings and the dataclass shape are exactly what that floor pins.

AC #13 and its four tests
(`test_a_mixed_side_pooled_row_renders_the_side_mix_label_on_mean_ask`,
`test_a_no_only_stratum_renders_the_no_only_label_on_mean_ask`,
`test_an_all_yes_corpus_renders_no_side_mix_label_and_no_footnote`, and
`test_a_mixed_station_stratum_renders_the_side_mix_label` carried as a **strict** `xfail` naming
BLOCKER-3) are present in the plan body (§7 step 1, §8), not only in §13. Three of the four tests are
exercisable inside THIS item (`pooled` is exactly where NO rows are admitted without a ruling), which
is a genuine strengthening over the round-4 mle defect's own suggested remedy (which expected the
exercise to wait for BLOCKER-3) — correctly noted as delivering more than requested rather than less.

This is a complete, source-grounded fix: the round-4 defect (a load-bearing disclosure claim with
nothing behind it — an implementer could withdraw the partition and never build the label that made
withdrawing it safe) is closed with a concrete rendering spec, a byte-identity-preserving mechanism,
and four tests, three of which are enforced today rather than deferred behind an open ruling.

## Re-check of prior material facts (no regression)

Spot-checked that the central round-4 restructure (`cell_dead` gating at `family_tally_v2.py:655/
728/753/792`, `pooled`'s inertness, the pooled-only-doesn't-clear refutation at `:653/:654`, the
`E[held_i]=BE_i` derivation, the `PENDING_STRATA_RULING` withholding mechanism reusing
`scheduled_ns = range(0)`) is untouched by this revision's diff — the only change is D-A(ii) and its
tests/AC. No regression found.

## Defects

None MATERIAL, none MINOR remaining. The single defect carried into this round (the unspecified
mean-ask disclosure) is fixed and verified against source, with byte-identity preserved and the
fix's own safety property (labelling is visible before the partition question is even ruled on)
independently confirmed.

## Per-criterion points (cap in parentheses)

- Fidelity to gap and completeness (20): **20** — G-04 fully covered (D-A/B/C/D/E/F), the §7-frozen
  element correctly deferred to BLOCKER-3, and the disclosure that makes the pooled-only interim
  state honest is now built rather than promised.
- Technical correctness and evidence grounding (20): **20** — every citation in this round's change
  re-verified exact against current source; the byte-identity preservation mechanism (leaving
  `StratumV2` and the header/divider strings untouched) is correctly reasoned and matches the AC #5
  floor's actual pin surface.
- Implementation specificity and feasibility (15): **15** — the three label literals, the call-site
  computation, the footnote placement and emission rule are all concretely specified, not left to
  inference.
- Acceptance criteria and validation quality (20): **20** — AC #13 plus three immediately-exercisable
  tests and one strict `xfail` (which blocks the ruling from landing without the label following it)
  make the labelling commitment a checked artefact rather than an assertion.
- Autonomous operation, failure handling, recovery (15): **15** — D-F's latched CRITICAL alert and
  the WARN on a withheld verdict remain delivered, unaffected by this round's change.
- Portfolio objective alignment, scope, dependencies (10): **10** — §11's chain, numeric baseline and
  falsifier are concrete and unaffected by this round's change.

**Total: 100/100**

## Required changes

None.

## Blockers (named separately, not scored as deductions — unresolvable by any reviewer or plan text)

- **BLOCKER-1** — strategy-lead/PREREG ruling on `pm_us_crh_v4`'s `trial_id_prefix` identity.
- **BLOCKER-2** — strategy-lead ruling on whether `pm_us_crh_cont` is retired.
- **BLOCKER-3** — strategy-lead/PREREG ruling on whether NO-side rows may enter
  `station_strata`/`ask_band_strata`; the mixed-station strict `xfail` added this round is a
  standing guard that the label will follow whenever this ruling lands, not a substitute for it.
