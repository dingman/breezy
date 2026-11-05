# AUD-06a — Round 3 review (prediction-market-reviewer, portfolio accounting/risk lens)

Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-06a-r11-boundary-revalidation.md
SHA256: 7dd0fb65405ceb44ebbdedf0419b1579147bd5b82c3582e63dcb0b9e86397fd5
Round: 3
Reviewer: prediction-market-reviewer (independent, blind)

## Round-2 defect disposition verification

All round-2 findings are genuinely closed in the plan body, re-verified against current source:

- `side_mix` axis added (mle's option (b), not the rejected option (a)): CONFIRMED. §6 adds
  `side_mix ∈ {all-YES, all-NO, mixed}` as a fourth swept axis. The anti-conservatism argument is
  sound and I re-derived it independently: `combine_station_day`'s cross term
  (`current_rung_hold_v2.py:344`, `variance -= 2*qty_i*qty_j*s_i*s_j*q_i*q_j`, `signs` at `:329`)
  gives `s_i*s_j = +1` (variance-reducing) for same-side pairs and `s_i*s_j = -1`
  (variance-raising) for a YES/NO pair — so a mixed-side day is strictly more adverse to the
  recorded mechanism (faster `I` saturation) at equal `q`/`qty`, confirming a YES-only envelope
  would be anti-conservative if applied to mixed-side days. `_sample_station_day`
  (`tests/unit/test_multi_position_validation_2026_09_14.py:69-99`, read in full) indeed never sets
  `side`, so `StratumRow.side` defaults to `"yes"` (`current_rung_hold_v2.py:129`) — the round-2
  premise is accurate.
- `cap-shaped` dispersion class defined without reading a cap: CONFIRMED.
  `qty_i = clip(floor(R / ask_i), 1, q_max)` with `R` a literal dimensionless grid
  `{2, 3, 5, 8, 13, 21}` — no cap value, cap quotient, or currency figure anywhere in the
  construction. `test_the_cap_shaped_dispersion_reads_no_operator_reserved_value` is the correct
  regression floor for this property.
- Machine-checkable mechanism verdict (Spearman ρ, permutation p-value, cell-count floor, CP-interval
  refutation criterion): CONFIRMED concrete and reproducible from the stated thresholds, with an
  `INDETERMINATE` third outcome that also stops the item.
- `_SameRungOppositeSidesRefusal` (`:237-241`, raised `:269-273`) and the `Σ q_i > 1` gate
  (`:331-336`) citations for the `mixed`-cell admission guards: both confirmed at those exact lines.

No round-2 disposition is misrepresented.

## Fresh review of the full revision (new defects, round-3 lens)

I re-read the full plan against source with particular attention to the interaction with AUD-06b
(which imports this item's `R` grid and `side_mix`-scoped envelope) and to the `Var_H0` formula this
item's Monte-Carlo must reproduce exactly.

No MATERIAL defect found. Specifically checked and sound:
- The registered H0 formulas quoted in §6 (`X_sd`, `Var_H0`, admission gate) match
  `MULTI_POSITION_PER_STATION_2026-09-14.md:130-132` and the NO-side amendment §3 exactly, and the
  plan correctly imports `score_combined`/`information_fraction`/the artefact loader rather than
  reimplementing them (checked: no new statistic function is introduced anywhere in §6/§7).
- The `side_mix`-scoped publication rule (AC #4: "a single scalar envelope may be published only
  when `all-YES` is not the binding cell") is the correct safety direction and is consistent with
  AUD-06b's own consumption contract (`derive_order_quantity` applying the value matching the
  station-day being sized) — I cross-checked AUD-06b §6 G1 and confirmed it reads
  `Q_MAX_VALIDATED` per `side_mix` where published, so the two plans do not diverge on this point.
- The staleness trigger's two dimensionless conditions (live median outside `[p25,p75]`; IQR
  ±50%/−33%) are reasoned constants, correctly labelled as build-side rather than derived from a
  registered study — an honest self-scoring, not an overclaim.
- No operator-reserved value (either cap) is read, restated, defaulted, or inferrable from any
  output this item publishes — verified across §6, §7, and the new tests
  (`test_the_cap_shaped_dispersion_reads_no_operator_reserved_value`).

One MINOR observation, not previously raised: the plan states the sweep "must not be added to any
timer" (§9) and is a one-shot artefact, but AUD-06b's staleness check (imported by reference) is
evaluated at AUD-06b's gate "before each sized cohort" — this creates an implicit dependency where
AUD-06a's artefact must be re-read fresh by AUD-06b on every sizing decision, not cached at AUD-06b's
own boot. The plan does not state this operational detail (it is arguably AUD-06b's responsibility to
specify, and AUD-06b's own G1 does specify a fail-closed `envelope_is_stale` check), so this is not a
deduction against AUD-06a specifically — noted for completeness only, not scored.

## Per-criterion points (cap in parentheses)

- Fidelity to gap and completeness (20): **19** — R-11/G-11's boundary blocker is squarely addressed
  against the codebase's own recorded mechanism, now over the station-day shapes the envelope will
  actually be applied to (the `side_mix` axis closes the population-mismatch risk). −1 continuing the
  round-2 mark: `max_equity_fraction` (also named in G-11) is correctly deferred to AUD-06b, genuinely
  outside this item's scope.
- Technical correctness and evidence grounding (20): **19** — every cited formula, line number and
  sign argument re-verified against current source this round; the mechanism instrumentation
  (`Δt_k`) and its CONFIRM/REFUTE criteria are machine-checkable and grounded in the amendment's own
  registered figures (20000 reps, CP one-sided 95%). −1 because the mechanism itself remains a
  hypothesis until step 4 actually runs — correctly deferred, but it is the item's central analytical
  claim and is still open at plan time.
- Implementation specificity and feasibility (15): **13** — reps, CI construction, seeds, tolerance,
  all three dispersion classes, the `side_mix` axis and the verdict statistic are all pinned in
  Amendment C's own text, ready to implement without further design choices. −2 because the
  fourth axis (`side_mix`) multiplies the sweep grid and the plan does not re-estimate wall-time for
  a host with a documented history of memory pressure from nightly studies.
- Acceptance criteria and validation quality (20): **19** — reproduce-first gate, a computed
  three-outcome verdict, an honest empty-envelope branch, no pre-asserted threshold, and a
  `side_mix`-aware publication rule are all concrete and independently checkable from the sweep
  table alone. −1 because the `ρ ≥ 0.70`/`p < 0.01` thresholds are reasoned defaults rather than
  values inherited from a registered study (the plan is honest about this, which is why it loses
  only one point, not more).
- Autonomous operation, failure handling, recovery (15): **14** — correctly forbids a timer; the
  staleness predicate is fail-closed at its one real consumer, consistent across both plans. −1
  because this item ships the predicate but cannot itself enforce AUD-06b evaluates it every cycle
  (the interface risk is named in §12, which is the right disposition, but the point is not free).
- Portfolio objective alignment, scope and dependencies (10): **10** — §11 gives the enabling chain,
  a numeric baseline, an explicit decline of the ROI claim, and a falsifier. Per the brief's rule
  ("a deduction with no named defect ... is not actionable"), round 2's disposition #4 is resolved
  here: I find no defect in §11 on its own terms, so full marks are awarded, matching the round-2 pm
  score.

**Total: 94/100**

## Required changes to reach 100

1. Re-estimate (or bound) the wall-time/memory budget for the four-axis sweep (`q_max` × dispersion
   × `k` × `side_mix`) given the host's documented memory pressure from nightly studies, and state
   the mitigation (e.g. chunking, or explicit sequencing against `breezy-studies.slice`).
2. State the `ρ ≥ 0.70`/permutation-p thresholds' provenance explicitly as "reasoned, not inherited"
   in the artefact header (already implied by the self-score; making it explicit in the plan text
   closes the last point).

## Blockers

None. No operator or strategy-lead ruling is required — the item is constructed so that no
operator-reserved value enters the analysis, and R-11 is a strategy-lead question this artefact is
designed to answer rather than escalate.
