# AUD-04 — Round 6 (delta) — prediction-market-reviewer

Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-04-portfolio-roi-measurement.md
sha256: ec03e0c9f69ba8384fd15a6f5309581d050e9d11e1e05c7e7b03df1256c67a6e
Round: 6 (delta, final for this cluster)
Reviewer: prediction-market-reviewer (portfolio accounting / risk)

## Re-derivation: does D9 actually close the hole?

Restated my round-5 finding to confirm this revision fixes the right thing: for a position opened on
`D1` that never settles, `unexplained(D1) = Δbalance(D1) − proceeds(D1) + capital_deployed(D1) =
(−cost−fee) − 0 + (cost+fee) = 0`, forever, at any `SETTLED_THROUGH` cutoff — the cash identity
cannot carry this signal by construction. D9 does not try to make the identity carry it; it adds an
**independent** detector over a different join, which is architecturally the correct response (a
structurally blind term cannot be patched by tuning a threshold around it — a separate detector is
required, and that is what was built).

## Citations verified against current source (all exact)

- `FilledTrial` (`src/breezy/settlement/trial_scorer.py`): class def **`:83`**, `trial_id` **`:113`**,
  `climate_day` **`:115`**, `filled_at_ns` **`:121`**, `scheduled_release_at_ns` **`:124`**
  (docstring: "When the NWS FINAL was scheduled to publish for this station-day") — all CONFIRMED
  exact against the dataclass field list.
- `ScoredTrial.trial_id` at **`:134`** — CONFIRMED, the join key.
- `_resolve_settlement_basis`'s structural bound at **`trial_scorer.py:243`**
  (`now_ns >= trial.scheduled_release_at_ns + _SEVEN_DAYS_NS`) — CONFIRMED verbatim, re-verified for
  the third time this cluster against the same line.
- `read_filled_trials_state_db` at **`score_live_trials.py:556`** — CONFIRMED def line.
- `find_unresolved_takes` at **`:1030`** — CONFIRMED def line (the adjacent "taken but never filled"
  census D9 must not duplicate).
- `_with_scheduled_release_at_ns` at **`:1161`**, replacing "the reader's placeholder
  `scheduled_release_at_ns` with the venue's real settlement instant... never midnight UTC" —
  CONFIRMED verbatim against the docstring, which is the load-bearing fact for anchoring the horizon
  on a real settlement instant rather than an arbitrary placeholder.
- `_latest_stored_row` at **`:1277`**, returning `None` "if none has ever been scored" — CONFIRMED
  verbatim, the correct in-repo precedent for the "never scored" predicate D9 reuses rather than
  reinventing.
- `DurableFillRecord` (`adapters/polymarket_us/exec/client.py`): class def **`:641`**, `ts_event: int`
  at **`:675`**, and no settlement/credit timestamp field anywhere in its field list — CONFIRMED,
  which is exactly why the plan anchors D9's horizon on `scheduled_release_at_ns` (a `ScoredTrial`/
  `FilledTrial`-side quantity) rather than on anything the fill ledger itself carries.

Every citation the coordinator asked me to check is exact. No stale line reference found.

## Design check (market-mechanics correctness, not just citation accuracy)

- **Horizon anchoring is sound.** `MAX_SETTLEMENT_HORIZON_NS = scheduled_release_at_ns +
  _SEVEN_DAYS_NS + SETTLEMENT_HORIZON_GRACE_NS` (grace = 3 days) is derived from a real, cited
  structural bound plus a cadence-derived margin (nightly scorer + one missed run + a day), not
  invented; it is checked against the live record at new step 0(g) rather than trusted, with a
  stated, non-silent revision path if the live record ever exceeds it.
- **Capital stays in the denominator — verified as stated, not merely claimed.** The plan is explicit
  that `PERMANENTLY_UNSETTLED` is an orthogonal label, not a fourth partition bucket, and that AC #2's
  scored/residual/unreconciled partition is unaffected. This is the correct posture: excluding stuck
  capital from the denominator to make the identity look clean would be exactly the failure mode this
  whole item exists to prevent.
- **The ROI gate is fail-closed on the FIGURE, not on the run.** `roi_status:
  "GATED_UNSETTLED_CAPITAL"` plus a D7-reader exception (`UnsettledCapitalRoiError`) on `roi`/
  `roi_minus_b0`/`roi_minus_b1` while gated, with the run itself still exiting 0 (a detected condition
  is a success of the detector, not a crash) — this correctly separates "the report ran and told the
  truth" from "the headline number is safe to read," which is exactly the distinction AUD-06b's own
  gate-check (its own step 0, reading AUD-04's report through the `schema_version` reader) depends on.
- **Self-healing, checked.** Because the left-anti-join is recomputed fresh on every run, a trial that
  eventually does get scored (a late correction) drops out of the flagged set on the next run and
  ROI un-gates automatically — the detector does not need a manual "resolved" flag to stop
  over-reporting once the underlying data catches up.
- **No false-positive risk from the adjacent census.** `find_unresolved_takes` (taken, never filled)
  and D9 (filled, never scored) are confirmed operating on different keys/records
  (`TrialDayLatch` state vs `FilledTrial`/`ScoredTrial` existence) and the plan states neither
  duplicates the other — verified consistent with the source read above.
- **`MIN_LAG_SAMPLE_N` (the adjacent mle fix) is conservative in the correct direction.** `max(...) >=
  p99(...)` on any sample, and both branches stay floored by the structural `7`, so the small-sample
  branch can only widen `SETTLED_THROUGH`, never narrow it — consistent with D9 being independent of
  this cutoff entirely (D9 runs on both sides of `SETTLED_THROUGH` and is never gated by it).

## Regression sweep

- Grepped for other `roi`/`roi_minus_b0`/`roi_minus_b1` consumers that might be broken by the new
  exception-on-read behaviour: AUD-06b's own gate-check (its own step 0) and AC #9 are the only named
  consumers, and both are being built after AUD-04 ships, with AUD-06b's own gate explicitly requiring
  AUD-04's report to be readable through the `schema_version` reader as a precondition — there is no
  existing caller whose behaviour regresses, since none exists yet.
- The coordinator's separately-applied §5 edit ("No change to any existing `src/` module... the single
  `src/` addition is the new, pure, node-unimported `src/breezy/runtime/alert_ladder.py`") is present
  and accurate: it correctly narrows what was previously an absolute "no `src/` change" claim to
  account for the one addition this plan's own §6 D8 already makes, consistent with AUD-07's
  independent citation of the same module (verified in my round-4/5 review of that plan).
- No statistic, cap, or scoring formula is touched; D9 reads existing records and adds one detector,
  one JSON field pair, and one alert — no change to `capital_deployed`/`proceeds`/`Δbalance`'s own
  computation.

No new defect found.

## Defects

None MATERIAL, none MINOR. The round-5 MATERIAL finding (the cash identity's structural blindness to
a permanently unsettled position) is closed by an independent, source-grounded, correctly-scoped
detector that keeps capital in the denominator, fails closed on the ROI figure without stopping the
run, self-heals if the trial later settles, and delivers an alert through the existing sink — every
element of the fix I required is present and verified.

## Per-criterion points (cap in parentheses)

- Fidelity to gap and completeness (20): **20** — G-03's reconciliation charter now reaches the one
  class of unexplained capital it previously could not see; §3(i), §5 and §11 all updated
  consistently.
- Technical correctness and evidence grounding (20): **20** — every citation re-verified exact; the
  identity's blindness is derived by substitution and stated as a limitation in the artefact itself,
  not left implicit; the adjacent `find_unresolved_takes` census is correctly distinguished rather
  than duplicated.
- Implementation specificity and feasibility (15): **15** — the horizon formula, the join key, the
  flag, the gated `roi_status`, the reader exception, the separate latch file and the three-branch
  lag statistic are all named with no material design decision left to the implementer.
- Acceptance criteria and validation quality (20): **20** — AC #13's test pins the identity's
  blindness as a real, asserted fact rather than assuming it away, and its negative half stops
  over-flagging; AC #12's minimum-sample rule closes the adjacent percentile-instability defect.
- Autonomous operation, failure handling, recovery (15): **15** — stuck capital is detected, delivered
  and fail-closed on the figure without stopping the run, and cannot be suppressed by a GREEN
  cumulative reconciliation.
- Portfolio objective alignment, scope, dependencies (10): **10** — §11's evaluation contract now
  exposes the settled-through and ROI-gate fields alongside the numerator/denominator, so no
  consumer can read a headline ROI over capital that may never return.

**Total: 100/100**

## Required changes

None.

## Blockers

None. No operator or strategy-lead ruling is required for this item's own scope: no operator-reserved
value is read or assigned, `SETTLEMENT_HORIZON_GRACE_DAYS` and `MIN_LAG_SAMPLE_N` are measurement
constants with stated, source-derived bases and a non-silent revision path, and the fail-closed ROI
gate is a build-side detector, not an enablement decision.
