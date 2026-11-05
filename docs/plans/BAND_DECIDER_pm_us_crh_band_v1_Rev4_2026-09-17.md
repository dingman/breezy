# PLAN Rev 4: Band-Resolved Decision Path for `observation_ambiguous`

Scope: DESIGN ONLY, read-only against /home/jon/breezy. Rev 3's 4 items
were satisfied; this rev applies exactly 2 residuals, nothing else.
CODEGRAPH_USED: yes (line numbers carried from Rev 1/2/3 verification).

## Rev 1-3 changes (resolved, carried forward)
`BE_i` stays market-quoted (`decision.py:394`); `band_decision.py` calls
`_finalize_take`/`is_legal_cell`/`_rung_index` directly, zero copied math;
calibration table is a generated frozen Python module, not JSON; label is
NWS CLI `settled_f`; `p_bound_band` is UNCONDITIONAL per candidate rung
(denominator = all in-window rows for the cell, including outside-band
ones, T11); at most ONE Take per ambiguous frame, sibling refused
`"band_sibling_selected"` (T12); Stage 0b is stratified by ask band, gate
holds in `0.25-0.75` only; `width_code`/`m_code`/`is_legal_cell` recomputed
per candidate rung from the ladder, never inherited (T13); Stage 0a/0b gate
the build before any code; `REFUSAL_REASONS` widens by two members with a
pinning test. Full detail in §1-§7 below, which are the current,
authoritative state.

## Rev 4 changes (this revision — 2 items only)
1. **[HIGH] Numerator drops the "AND v3 hold condition" clause.** The
   numerator is rows where NWS CLI `settled_f` equals the candidate rung's
   value — full stop. `settled_f` IS the day's max, so "the max stays
   inside the rung through settlement" is exactly `settled_f ∈ rung`; a
   separate hold sub-event is vacuous. For the LOWER candidate of a
   spanning band, the literal v3 hold test (`decision.py:251-257`, reached
   only when `spans()==False`, `:335-336`) is already false at decision
   time and must never be applied here. The unconditional denominator and
   T11 are unchanged.
2. **[MEDIUM] New T14:** `BandRungHoldStrategy` on a NON-ambiguous frame
   (`running_max.spans(ladder)` is `False`) produces a `Decision`
   byte-identical to `ContinuousRungHoldStrategy` — i.e. `band_decision` is
   invoked iff `spans()` is `True`. Required as a Stage 3 completion gate,
   before Stage 4.

## 1. Recommendation
**Primary: calibrated per-candidate-rung `p_bound_band` fed into the
existing, unmodified `_finalize_take`, under a NEW family `pm_us_crh_band_v1`.**
6-hourly METAR remarks are one input feature to the table, never shipped
standalone: MIA 09-16's `10333` 6-hour remark resolved the true value (92)
only at 17:53Z, ask already 0.94 — the real edge (12:00-13:01 LST, ask
0.12-0.75) was already gone. "Trust the lower bound" is rejected: sampled
5-min maxima are structurally biased LOW vs. truth (mechanism below), the
losing direction for the 09-16 shape. "Do nothing" remains the correct
default until Stage 0b/2/4 pass.

**Mechanism (confirmed in code):** even the hourly METAR's 5-min HF T-group
is whole-°C (`T0330` example, MIA) — tenths exist only in the hourly :53
METAR body. `value_at` (`running_extreme.py:286-297`) already takes the max
lower bound over every eligible row and the arg-max-upper row for `upper_f`
— fully monotone already — so a prior exact anchor is dominated by any
later, still-rising row's own higher upper bound; nothing is left to
intersect. The true day max can also exceed every discrete 5-min sample
(continuous peak between polls), biasing sampled maxima low — the model
must estimate an ASYMMETRIC, unconditional `P(settled_f==candidate rung)`
per rung (§3 item 1), not assume 50/50.

**Unchanged:** new family id + PREREG v4-style amendment before first fill;
`pm_us_crh_cont`'s trial/decision behaviour stays byte-identical (T1, golden
replay contract test).

## 2. Architecture
**Untouched:** `NwsObservationActor`, `RunningExtremeAccumulator.push/value_at`,
`RunningMax.spans` (facts layer). `evaluate_decision`, `_finalize_take`
(`decision.py:367-414`), `_evaluate_no_side` (`:417-441`), `is_legal_cell`/
`_rung_index` (`:275-305`), `tick_eval.evaluate_both_sides` (`:238-310`) —
called, never edited. No new market-data/WS subscription (A7): the shadow
family reads the SAME node's existing 4-station bus data.

**Two narrow widenings:** `REFUSAL_REASONS` (`:120-148`) gains
`"band_resolution_uncalibrated"` and `"band_sibling_selected"` (item 2).

**New modules (additive):**
1. `src/breezy/ingest/iem_asos_1min.py` — archive-only IEM `asos1min.py` parser, mirroring `iem_observations.py`'s archive-only/PORT pattern + differential-test mandate. Fetch/cache reuses `fetch_text_cached`/ `cache_path_for_url` (`settlement_alignment_study.py:343-345,359-371`) — no new HTTP path in the live ingest package.
2. `src/breezy/domain/band_resolution.py` (pure) — frozen `Band(lower_f:int, upper_f:int)` and `Covariates(station, season, hour_lst, band_width, minutes_since_window_open)` pinned first (T6); `rung_distribution(band, covariates, table) -> Mapping[int, Decimal]` restricted to rungs `_rung_index` finds spanned (at most two), each value the UNCONDITIONAL probability (§3 item 1); "uncalibrated" sentinel on a missing cell.
3. Calibration table = generated frozen Python module, `.../band_resolution_table.py`, built like `generate_current_rung_hold_archive_table.py:187-261` (`CORPUS_SHA256`, `STUDY_GIT_SHA`, sorted dict literal, `Decimal("...")`, plus per-cell outside-band mass reported alongside). Missing key → `Refuse("band_resolution_uncalibrated")`, same shape as `p_hold_undefined` (`:391-392`) — never a default guess.
4. `scripts/analysis/band_resolution_calibration_study.py` — builds (3), ≤800 lines (T7; split rather than copy the 1,239-line `mb_current_rung_edge_study.py` shape).
5. `src/breezy/strategy/current_rung_hold/band_decision.py` — imports `_finalize_take`, `is_legal_cell`, `_rung_index`. For each rung the band spans (≤2), `width_code`/`m_code` are RECOMPUTED from the ladder for THAT rung (never inherited from the ambiguous frame, item 4/T13); a candidate failing `is_legal_cell` is refused `"illegal_cell"` and dropped before any `_finalize_take` call. Each surviving candidate calls `_finalize_take(inputs, price=<that rung's own quoted ask>, size=..., p_bound=rung_distribution[rung]` (unconditional, §3), `rung=rung, side="yes")`. **At most one Take per frame (item 2):** if more than one candidate's `_finalize_take` returns a `Take`, keep the larger `(p_bound_band−BE_i)` margin (tie-break: the lower rung); the other is `Refuse("band_sibling_selected")` on the offer tape. Zero copied fee/ break-even arithmetic.
6. **Extraction, not a new Strategy:** `_hunt_tick`'s call to `evaluate_both_sides` becomes `self._evaluate_both_sides(...)`, base body verbatim (`_submission_armed` L-2 precedent, `:658-672`). `BandRungHoldStrategy(ContinuousRungHoldStrategy)` overrides only that method, routing ambiguous-band frames through `band_decision.py`; registered as an ADDITIONAL strategy in the SAME node/config as `pm_us_crh_cont` (A7), `permit=None` until registration.
7. `deploy/families/pm_us_crh_band_v1.json` (`status: DRAFT`). Offer tape: reuse `source` (`offer_tape.py:210,291`) with `source="band_shadow"`; add `rung_distribution` as one more defaulted `to_dict`/`from_dict` key, same pattern as the 11 GAP-fix keys.

**Data flow:** actor → `push/value_at` (unchanged) → `RunningMax` → NEW
`rung_distribution` (unconditional per rung) → NEW `band_decision` calling
EXISTING `_finalize_take` per legal candidate rung, at most one Take
selected → offer tape (additive fields) → NEW family statistic, form
unchanged from v3. **Nautilus null hypothesis:** unchanged — no native
facility models band probability; pure domain code, same composition v2/v3
already use.

## 3. Calibration study spec
- **Label & normalization (item 1, CRITICAL):** ground truth is NWS CLI
  `settled_f` (same `finals_by_city` truth as
  `mb_current_rung_edge_study.py:404-420`). `p_bound_band` per candidate
  rung is UNCONDITIONAL: for a given `(covariates)` cell, the denominator
  is ALL in-window rows, INCLUDING those whose `settled_f` falls outside
  `[lower_f,upper_f]`; the numerator is rows where `settled_f` EQUALS the
  candidate rung's value — no separate "hold" sub-event (Rev 4 item 1):
  `settled_f` IS the day's max, so "the max stays inside the rung through
  settlement" already means `settled_f ∈ rung`; applying the literal v3
  hold test (`decision.py:251-257`) here would be vacuous for the upper
  candidate and structurally wrong for the lower one, since that test is
  only ever reached when `spans()==False` (`:335-336`) and is already
  false, by construction, for a rung that is not the unique containing one.
  Each rung's probability therefore already nets out the outside-band
  mass, and is compared to `BE_i=ask_i+fee_i` directly, exactly as
  `P_HOLD_LOWER` is today. Outside-band mass is still reported per cell —
  it is exactly what the bot is paying for when it takes either rung,
  never silently dropped.
- **Data/fallback (Stage 0a):** IEM 1-min archive preferred; reachability
  probed once via the existing `fetch_text_cached` path, go/no-go
  recorded. Fallback: already-cached local 5-min HF METAR data. Stage 1b's
  function signature is written against the `settled_f`-based unconditional
  label regardless of source — the fallback changes precision, never the
  label definition.
- **Covariates (YAGNI):** `station, season, hour_lst, band_width,
  minutes_since_window_open` only; since-last-exact-anchor covariate
  dropped from v1 — explicit follow-up.
- **Model:** stratified frequency table, Wilson-bound at `N_MIN=90`
  (`mb_current_rung_edge_study.py:172,350-352` pattern). No ML model.
- **Stage 2 exit gate:** at `N_MIN=90`, coverage of `(station × band_width
  × 30-min bucket)` cells inside the window's first 90 minutes (`[0,30)
  [30,60) [60,90)`) must be **≥80%** across all 4 stations before Stage
  3/4. Archive-span: targeting the full available IEM 1-min span (~5y
  measured previously); Stage 2 reports the real number, a prediction to
  be falsified, not assumed.
- **Evaluation:** calibration plot + Brier per stratum, sub-hour buckets
  reported separately, station-year holdout; T11 (synthetic 10%
  outside-band cell → the two candidate rung probabilities sum to ≤0.90)
  runs against this model before it touches real data.
- **Runtime budget:** process-then-discard per station-year, peak <8 GB,
  off-peak from other nightly studies and the live node.
- **Storage:** generated frozen module only, never hand-edited.

## 4. PREREG amendment sketch (narrowed per v2's M2)
- New family id `pm_us_crh_band_v1`, own D0, not an amendment to
  `pm_us_crh_cont`.
- **Reused verbatim:** `BE_i=ask_i+fee_i` on the candidate's own quote
  (`decision.py:394`); θ=0.06; two one-sided α=0.025 LD-OBF; `n_max=160`;
  `I_max=40`; look-every-10; strata; two operator caps.
- **What changes:** only the admission question — which rung counts as
  "current" and what `p_bound` compares against `BE_i`, plus the
  at-most-one-Take rule (item 2) that keeps trial rows independent.
  `p_bound_band` plays the same role `P_HOLD_LOWER[cell]`/`p_miss_lower`
  already play in v3 — architecturally the same kind of quantity, not a
  new class of risk.
- **Validation before registration:** Stage 0b's stratified screen plus an
  empirical `Var(S)` consistency check against the existing boundary
  artefact (reuse `gs_boundary_pm_us_crh_v2.json` if consistent; a NEW
  artefact is explicit out-of-scope follow-up).
- **Shadow-first:** `permit=None` for ≥30 covered station-days on
  `source=band_shadow` before any operator conversation about live
  enablement (operator-only, out of scope).

## New Stage 0: gates before any build
- **0a — reachability.** One bounded probe of the IEM 1-min archive via the
  existing `fetch_text_cached` path. Go → Stage 1a builds the real parser.
  No-go → documented fallback (§3); label contract unaffected.
- **0b — adverse-selection screen, STRATIFIED by ask band (item 3, hard
  go/no-go).** Score a first-cut table (built from whatever archive 0a
  reached) against contemporaneous `ask+fee` on every 09-16 tape row in the
  first 90 min of each station's window, plus a synthetic archive
  reconstruction, split into three ask buckets: `<0.25`, `0.25-0.75`,
  `>0.75`. **Material, defined:** ≥20 in-band-eligible rows, ≥50% showing
  `p_bound_band−(ask+fee)>0`, median positive margin ≥0.03 — **the gate
  must hold in the `0.25-0.75` bucket specifically** (the only bucket where
  ambiguity resolution is not near-deterministic); report the same three
  numbers for all three buckets. **Pooled numbers alone never clear the
  gate.** STOP if the `0.25-0.75` bucket fails; report every bucket
  regardless of outcome.

## 5. Test plan (RED first, named)
- T1 `test_pm_us_crh_cont_offer_tape_rows_are_unchanged_when_band_fields_absent`.
- T2 `test_offer_tape_record_round_trips_rung_distribution_through_to_dict_from_dict`.
- T3 Trimmed, COMMITTED fixture (`tests/fixtures/`), MIA 12:00-13:01 LST
  rows (+buffer) of the 09-16 tape; runs inside
  `scripts/ci/run_tests_no_egress.sh`, no network; zero `Take`s here is a
  §7 STOP condition.
- T4 `test_calibration_study_is_deterministic_given_the_same_inputs`;
  `test_band_decision_refuses_when_table_key_is_missing`.
- T5 `test_rung_distribution_is_stochastically_monotone_in_the_band`.
- T6 Pin frozen `Band`/`Covariates` before any other Stage 1b code.
- T7 Calibration script <800 lines; split rather than copy
  `mb_current_rung_edge_study.py`'s shape.
- T8 `test_evaluate_decision_never_emits_band_resolution_uncalibrated_or_band_sibling_selected`
  — pins BOTH widened reasons (item 2) to `band_decision.py` only.
- T9 Import-linter: `type='forbidden'`, `source_modules=[continuous_strategy,
  decision, tick_eval]`, `forbidden_modules=[band_decision, band_strategy]`;
  reverse direction explicitly allowed.
- T10 Golden replay contract test: T3 fixture through
  `ContinuousRungHoldStrategy` pre-/post-extraction of
  `_evaluate_both_sides`; record-for-record equality via
  `OfferTapeRecord.to_dict()` — behaviour-identity, not byte-identity.
- **T11 (item 1, new):** synthetic cell with 10% outside-band rows — the
  two candidate rung probabilities sum to ≤0.90.
- **T12 (item 2, new):** a frame where both candidate rungs clear
  break-even yields exactly one `Take` and one `Refuse("band_sibling_selected")`.
- **T13 (item 4, new):** a band whose two rungs carry different
  legal-cell classifications (one legal, one open_lower-illegal) refuses
  the illegal one and evaluates the legal one.
- **T14 (Rev 4 item 2, new):** `BandRungHoldStrategy` on a non-ambiguous
  frame (`spans()` is `False`) matches `ContinuousRungHoldStrategy` exactly —
  `band_decision` fires iff `spans()` is `True`. Stage 3 completion gate.

## 6. Build order
- **Stage 0a/0b (sequential, gate everything).** STOP here (including a
  `0.25-0.75`-bucket-only failure) is a complete, valid outcome.
- **Stage 1 (parallel, only if 0a/0b pass):** 1a `iem_asos_1min.py` +
  fixtures, verifying °C rounding direction against a real 09-16 MIA
  fixture; 1b `band_resolution.py` + T6 + T5 + T11. Reviewer:
  python-reviewer.
- **Stage 2 (depends on 1a+1b):** calibration study + generated frozen
  table; the 80% sub-hour coverage gate is the exit criterion. Reviewers:
  prediction-market-reviewer + python-reviewer.
- **Stage 3 (parallel once Stage 2's schema is fixed):** 3a
  `band_decision.py` (per-rung legal-cell recompute, item 4/T13;
  at-most-one-Take, item 2/T12) + `REFUSAL_REASONS` widening + T8; 3b
  `_evaluate_both_sides` extraction + T10 + `BandRungHoldStrategy` +
  same-node composition + offer-tape fields (T1/T2) + T9. **T14 must pass
  before Stage 3 is closed and Stage 4 starts.** Reviewers:
  prediction-market-reviewer + python-reviewer; security-reviewer only if
  scope nears the exec-client boundary (should not).
- **Stage 4 (sequential, doc-only):** PREREG v4-style amendment
  (admission-only change, item 2's independent-rows justification) +
  `Var(S)` consistency check; mandatory prediction-market-reviewer review.
- **Stage 5 (sequential, after Stage 4 registers):** shadow deployment,
  ≥30 covered station-days, re-validate, report readiness — live
  enablement stays operator-only.

## 7. Risks and plan-reaches-goal check (re-run only where Rev 3 changes it)
- Sparse-coverage, rounding-direction, and out-of-band-truth risks are
  unchanged from Rev 2 (item 1 changes how outside-band mass is USED —
  netted into the probability, not excluded — but the risk that it is
  large remains the same reported metric).
- **Goal-reach check, updated for items 2 and 3:** decisions in the first
  90 min of the window on an integer-°C day? Conditionally yes, with THREE
  stop points: (1) Stage 0b — **now scoped to the ask `0.25-0.75` bucket
  specifically** (item 3): the market pricing the bias in the extreme
  buckets does not stop the plan, since resolution there is already
  near-deterministic; a `0.25-0.75`-bucket failure does. (2) Stage 2 —
  sub-hour coverage <80% → STOP before `band_decision.py`/
  `BandRungHoldStrategy` are built. (3) Stage 3's T3 golden replay — zero
  `Take`s in the trimmed MIA fixture, even in shadow → STOP before PREREG
  registration. The at-most-one-Take rule (item 2) does not add a fourth
  stop condition: it only arbitrates the rare frame where BOTH candidates
  would clear break-even, which is required for PREREG validity, not a new
  way to fail to decide. Any of the three stops remains a complete, honest
  outcome — the goal is a real evaluation replacing a blanket refusal,
  never a guaranteed trade.
