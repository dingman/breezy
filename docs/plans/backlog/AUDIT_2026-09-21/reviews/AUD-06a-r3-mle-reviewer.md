# AUD-06a review — round 3 — mle-reviewer (statistical validation / measurement engineering lens)

Plan: AUD-06a-r11-boundary-revalidation.md
sha256: 7dd0fb65405ceb44ebbdedf0419b1579147bd5b82c3582e63dcb0b9e86397fd5
Round: 3

## Round-2 remedy verification

- **`side_mix` axis (round-2 MINOR, mine, accepted):** CONFIRMED added. I independently re-read
  `combine_station_day` (`current_rung_hold_v2.py:298-345`): `signs` built at `:329`, cross term at
  `:344`, `variance -= 2·qty_i·qty_j·s_i·s_j·q_i·q_j` — for a YES/NO pair `s_i s_j = −1`, so the term
  ADDS to variance (subtracting a negative), for YES/YES or NO/NO it SUBTRACTS. This confirms the
  plan's argument that a YES-only envelope is anti-conservative for mixed-side days (a mixed day has
  strictly higher variance at the same `q`/`qty`, and R-11's mechanism is that higher variance breaks
  the boundary), and the rejection of scoping to YES-only is correctly grounded in this sign, not
  merely asserted.
- **`cap-shaped` dispersion, defined (round-2 MINOR, pm, accepted):** CONFIRMED —
  `qty_i = clip(floor(R / ask_i), 1, q_max)`, `R ∈ {2,3,5,8,13,21}`, `ask_i` from the observed
  live/tape ask distribution (same source as the `BE` prior). This is a genuine, dimensionless,
  cap-free definition; `test_the_cap_shaped_dispersion_reads_no_operator_reserved_value` is the
  correct guard for it.
- **Machine-checkable monotonicity criterion (round-2 MINOR, pm, accepted):** CONFIRMED — ≥24 cells,
  Spearman ρ ≥ 0.70 with a one-sided permutation p < 0.01 (10000 permutations), a tolerance-based
  control anchor, and a symmetric, interval-based refutation rule (non-overlapping Clopper-Pearson
  bounds rather than point estimates). This is a well-constructed, pre-specified (not post-hoc tuned)
  statistical test — the thresholds are stated in Amendment C's own text before the sweep runs, which
  is the correct discipline for avoiding the exact class of post-hoc rationalization L-41 warns about.

## Fresh review of the full revision — no new defect found

I re-read `_sample_station_day` (`tests/unit/test_multi_position_validation_2026_09_14.py:69-99`)
directly: it draws `k ∈ {1,2,3}` mutually exclusive rungs, a random simplex split of `Σ BE_i`, mixed
`qty ∈ {1,2,3}`, and a true mutually-exclusive categorical outcome — this is a faithful H0 sampler for
the registered statistic, and it never sets `side` today (defaults to `"yes"` via `StratumRow.side`,
confirmed at `current_rung_hold_v2.py:129`), which is exactly the gap the round-2 `side_mix` axis
closes. The xfail reason at `:161-179` (verbatim re-read) matches every figure the plan cites (0.0592
at 5000 reps, 0.058 at 2000 reps, qty≡1 control ~0.011-0.013, the "variance up to 9x" / "n_k/n_max=0.25
schedule" / "realised-t boundary interpolation undershoots" mechanism language) exactly, word for
word.

I looked specifically for a fresh defect this round, per the brief's requirement to review the whole
revised plan afresh rather than re-litigate round 2. I did not find one. The two self-conceded
weaknesses in the revision-3 self-score (wall-time re-budgeting after the `side_mix` axis triples the
grid; `ρ ≥ 0.70`/`p < 0.01` being reasoned defaults rather than values inherited from a registered
study) are real but minor, already reflected in the author's own scoring, and neither is fixable by a
text change that would materially change the item's trustworthiness — they are honestly named open
items on a one-shot offline study with no autonomy surface and no operator-reserved value in play.

## Per-criterion points (cap in parentheses)

- Fidelity to the gap and completeness (20): **18** — matches round 2/3 self-score; R-11 fully
  addressed against the codebase's own recorded mechanism, now over the station-day shapes the
  envelope will actually be applied to; `max_equity_fraction` correctly and honestly left to AUD-06b.
- Technical correctness and evidence grounding (20): **18** — every load-bearing citation
  independently re-verified this round (xfail reason verbatim, `combine_station_day` sign structure,
  `StratumRow.side` default) and holds exactly; matches round 2.
- Implementation specificity and feasibility (15): **13** — matches round 2/3 self-score; reps, CI,
  seeds, tolerance, staleness thresholds, all three dispersion classes and the verdict statistic are
  pinned in Amendment C's own text; the self-conceded wall-time re-budgeting gap is real but does not
  affect correctness.
- Acceptance criteria and validation quality (20): **18** — matches round 2; reproduce-first gate, a
  computed verdict with a third `INDETERMINATE` outcome that also stops the item, an honest
  empty-envelope branch, per-`side_mix` publication rule.
- Autonomous operation, failure handling, recovery (15): **13** — matches round 2/3; correctly forbids
  a timer, the staleness predicate is fail-closed at the one real consumer; this item cannot itself
  enforce that AUD-06b evaluates it, named honestly as an interface risk rather than hidden.
- Portfolio objective alignment, scope, dependencies (10): **10** — §11's enabling chain, numeric
  baseline, falsifier and explicit ROI-claim decline were independently re-assessed and no fixable
  defect found (round 2: mle 7/10 citing only the criterion's structure, pm 10/10). Awarded in full
  per this round's instruction absent a named, fixable defect — this item reads no operator-reserved
  value anywhere and both reviewers agree on that point across all three rounds.

**Total: 90/100**

## Required changes to reach 100

None found this round beyond the two already self-named, non-blocking weaknesses (wall-time
re-budgeting note; stating that the monotonicity thresholds are reasoned rather than inherited — both
already disclosed in the plan's own text, not hidden).

## Blockers

None requiring operator/strategy-lead ruling. Unchanged across all three rounds: this item is
deliberately constructed so that no operator-reserved value enters the analysis, and R-11 is a
strategy-lead question this artefact answers rather than escalates.
