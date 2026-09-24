# AUD-04 review — round 6 (delta, FINAL) — mle-reviewer (statistical validation / measurement engineering lens)

Plan: AUD-04-portfolio-roi-measurement.md
sha256: ec03e0c9f69ba8384fd15a6f5309581d050e9d11e1e05c7e7b03df1256c67a6e
Round: 6 (delta review of the round-5 mle minor plus the round-5 pm MATERIAL, plus the coordinator's §5
reconciliation edit)

## Fix verification: MIN_LAG_SAMPLE_N and the small-sample fallback

§6 D4 gains `MIN_LAG_SAMPLE_N = 20`: below it, `SETTLED_THROUGH` uses `max(observed
settlement_lag_days)`; at or above it, `p99`; an empty sample falls back to the bare structural floor
`7`. The header states `settled_through_statistic=<max|p99> lag_sample_n=<n>`, and step 0(f) now
records `lag_sample_n` alongside the distribution. This closes my round-5 finding exactly as required:
the threshold is stated as a sample-size rule deliberately not derived from the pipeline's own data
(avoiding circularity), and the monotonicity argument (`max() >= p99` always, both branches floored by
`7`) correctly shows the small-`n` branch can only widen the cutoff, never narrow it — so the
anti-suppression property from round 5 is preserved, not reopened. **New test**
`test_a_small_lag_sample_uses_max_not_p99_and_says_so_in_the_header` covers all three branches
(`n=6` forcing `max`, `n=20` forcing `p99`, `n=0` forcing the bare floor) — this is the right test,
not merely a smoke test of one branch.

## Fix verification: D9, the open-position staleness/aging check

**Independently re-verified every cited source location, without trusting the plan's account:**

- `FilledTrial` (`src/breezy/settlement/trial_scorer.py`): class def at `:80` (plan cites `:83`, inside
  the same class's docstring/body — immaterial drift), fields `trial_id` `:113`, `climate_day` `:115`,
  `filled_at_ns` `:121`, `scheduled_release_at_ns` `:124` — CONFIRMED all four exact.
- `ScoredTrial.trial_id` at `:134` — CONFIRMED (within the cited `:131-151` range).
- `_resolve_settlement_basis`'s `_SEVEN_DAYS_NS` check at `:243` — CONFIRMED (re-verified a third time
  across rounds 4-6, unchanged).
- `read_filled_trials_state_db` def at `scripts/analysis/score_live_trials.py:556` — CONFIRMED exact.
- `find_unresolved_takes` def at `:1030` — CONFIRMED, matches the cited `:1030-1158` range.
- `_with_scheduled_release_at_ns` def at `:1161` — CONFIRMED, matches `:1161-1187`; its body genuinely
  replaces "the reader's placeholder `scheduled_release_at_ns`" with "the venue's real settlement
  instant... never midnight UTC" — the plan's characterization is exact, not paraphrased loosely.
- `_latest_stored_row` def at `:1277`, returning `None` when no row has ever been scored for a
  `trial_id` — CONFIRMED exact, matches `:1277-1284` precisely (the function body is exactly 8 lines,
  1277-1284).
- `DurableFillRecord` (`src/breezy/adapters/polymarket_us/exec/client.py`): class def at `:639` (cited
  `:641-685`, immaterial drift), `ts_event: int` field at `:675` — CONFIRMED exact — and no settlement
  timestamp field anywhere in the class, confirming the plan's claim that the horizon must anchor on
  `scheduled_release_at_ns` rather than anything the ledger itself carries.

**Design judgment.** The substitution proving the cash identity's blindness
(`unexplained(D1) = (−cost−fee) − 0 + (cost+fee) = 0` on the open day, forever, since no settlement day
ever arrives to carry a `proceeds` term) is correct and is exactly the failure mode a per-day/cumulative
cash reconciliation cannot see by construction — no cutoff, however chosen, changes this, because the
blindness is about a term that never gets a value, not about timing. D9 is a genuinely orthogonal
detector (a left-anti-join on `trial_id` against a fixed horizon), not a patch to D4, and correctly does
not attempt to fold this signal into the cumulative pass/fail check. The horizon formula
(`scheduled_release_at_ns + _SEVEN_DAYS_NS + SETTLEMENT_HORIZON_GRACE_NS`, `GRACE_DAYS=3`) is grounded
in the same structural bound as D4's floor, with the grace margin justified by the scorer's own nightly
cadence (one missed run ≤2 days, one full day beyond that) — a stated, checkable-at-step-0 basis, not an
arbitrary constant. The fail-closed ROI gating (`roi_status: "GATED_UNSETTLED_CAPITAL"`,
`UnsettledCapitalRoiError` raised by the D7 reader on any ROI field while gated, but the run itself still
exits 0 and the flagged position's capital stays in every total) is the correct shape: it protects
downstream consumers (AUD-06b, AUD-07) from reading a clean ROI number that is silently blind to stuck
capital, without turning a detected-and-reported condition into an operational failure.

**Test design judgment.** The new RED test's structure is sound: it first asserts the cash identity's
own blindness is real (`unexplained(D1) == 0`, cumulative PASSES) rather than assuming it away, then
asserts the independent detector catches what the identity cannot, and its negative half (identical
fixture one day inside the horizon, not flagged) is the correct guard against over-flagging every open
position.

## "Node-unimported" claim — verified true and consistent with the import-linter contract

The coordinator's added §5 sentence states the only `src/` addition is "the new, pure, node-unimported
`src/breezy/runtime/alert_ladder.py`." I checked this two ways: **(1) Design consistency** — both of the
module's named consumers (AUD-04's own `scripts/analysis/portfolio_roi_report.py` and AUD-07's
equivalent exit-window-study script) are offline, systemd-oneshot-triggered analysis scripts, not the
live trading node's composition path (`app/`, `runtime/composition.py`, or wherever strategies are
wired and started) — nothing in either plan's design has the live node importing this module, so the
claim is accurate as a description of what this plan builds. **(2) Contract consistency** — I re-read
`pyproject.toml`'s `[tool.importlinter]` layers contract: it constrains *direction* (which layers may
import which), not that every module in a layer must have an importer; a `runtime`-layer module with
zero importers from `app`/`strategy` today does not violate the layers contract, which only fires on a
violation of direction. `runtime`'s own position in the layer list (above `adapters`/`persistence`/
`settlement`/`domain`) is unaffected by whether `app`/`strategy` currently choose to import a given
`runtime` module. This claim is accurate and requires no additional test — it is a negative-scope
statement of the same kind as this plan's other §5 exclusions, none of which carry individual tests.

## Regression sweep

Checked step 0's lettering (`(a)`-`(g)`, no collision from the new `(g)`), the AC list (`1`-`13`,
sequential, no renumbering collision), and the §11 field-table additions (`settled_through`,
`settled_through_statistic`, `lag_sample_n`, `roi_status`, `unsettled_capital_positions` — none collides
with an existing field name). No regression found in any section this diff touches or is adjacent to.

## Per-criterion points (cap in parentheses)

- Fidelity to the gap and completeness (20): **20** — D9 closes a real, previously-undetectable class of
  unexplained capital (a position that opens and never settles); the round-5 pm MATERIAL is fully
  closed.
- Technical correctness and evidence grounding (20): **20** — the round-5 mle MINOR (percentile at tiny
  `n`) is closed with a correct, monotonicity-preserving fallback; every D9 citation independently
  re-verified exact against source.
- Implementation specificity and feasibility (15): **15** — the horizon formula, join key, flag,
  gated `roi_status`, reader exception, separate latch file, and the three-branch statistic rule are all
  concretely named; the shared-ladder sequencing risk is already covered by the existing ship-order
  contingency (not a new gap).
- Acceptance criteria and validation quality (20): **20** — AC #12 now forbids a bare percentile call at
  any sample size, AC #13 requires the D9 test whose structure (pin the blindness, then prove the
  detector, then prove the negative control) is exactly right.
- Autonomous operation, failure handling, recovery (15): **15** — stuck capital is now detected,
  delivered, and fail-closed on the ROI figure without stopping the run or being suppressible by a
  GREEN reconciliation.
- Portfolio objective alignment, scope, dependencies (10): **10** — §11 now exposes the settled-through
  and ROI-gate fields so no consumer can read a headline ROI over capital that may never return.

**Total: 100/100**

## Remaining defects and required changes

None found this round.

## Blockers

None requiring operator/strategy-lead ruling. `SETTLEMENT_HORIZON_GRACE_DAYS` and `MIN_LAG_SAMPLE_N` are
measurement constants with stated, checkable bases, not operator-reserved values. The mark-to-market
equity-curve gap (a prior-round note, not a blocker) remains a recommended future item outside this
item's scope.
