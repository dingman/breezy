# AUD-04 — Measure portfolio-level ROI: an unattended daily realised-P&L, capital-deployed and balance-series report with a registered baseline, a versioned schema and a frozen-input detector

## 1. ID and actionable title

**AUD-04** — Ship `scripts/analysis/portfolio_roi_report.py` plus a `breezy-portfolio-roi` systemd
oneshot+timer that, unattended and read-only, produces a dated, **schema-versioned** portfolio-level
report carrying: realised P&L after fees per settled fill, capital deployed, the account-balance
series, an explicit unexplained-capital-flow line, the measurement period, an explicit
n-underpowered header line, and ROI against two registered baselines — and that **detects and alerts
when its inputs are present but frozen**.

## 2. Source finding and class

- **Gap:** G-03 (`docs/evidence/AUTONOMY_ROI_AUDIT_2026-09-21.md:44-49`). Verdict **FALSE** —
  "No equity curve, balance series, capital-flow accounting or baseline." Coordinator-verified (V)
  for the plan text (`FORECAST_EDGE_FAMILY_Rev5_2026-09-18.md:182-186` defines "Portfolio ROI" as
  `trial_count × mean_realized_edge`, "never annualized"); agent-reported (A) for the absence claim.
- **Also cited:** AccountState logged once per boot (`breezy-trade-20260920T165028Z.log:199`);
  `snapshot_positions=False`; no realised-P&L figure for the 6 venue-confirmed fills exists in docs
  or tally output.
- **Class:** **verification gap** (primary) with a **missing capability** component — the inputs
  exist and are already persisted; nothing joins them into a portfolio-level statement.

## 3. Current behaviour, required behaviour, concrete gap

**Current.** Measurement is exclusively *per family* and *per registered statistic*:
`family_tally_v2.py` reports `n`, a sequential verdict and a BCa ROI bound for ONE
`trial_id_prefix`; `live_family_tally.py` does the v1 equivalent; `position_monitor_nightly_report`
reports exit-rule series. Every one of these is scoped by `manifest.trial_id_prefix`
(`family_tally_v2.py:532-564 filter_rows_to_manifest_prefix`, which REFUSES foreign rows). None of
them answers "what did the account do". No artefact states capital deployed, the balance series, or
a baseline, and the only balance observation is one `AccountState` per boot.

**Required.** One dated, unattended artefact per day stating, for an explicit measurement period:
(a) realised P&L after fees per settled fill and in total; (b) capital deployed (gross entry cost,
fee-inclusive, **per leg, never netted**); (c) the account-balance series at daily granularity;
(d) capital flows in/out, detected and named, never silently netted; (e) ROI against two named
baselines, headed by an explicit statistical-power caveat; (f) a fail-closed reconciliation that
every ledger fill is accounted for exactly once; (g) a machine-readable sibling whose **schema is
versioned and refused when unknown**; (h) an alert when the inputs stop growing;
(i) an independent open-position staleness check that names capital deployed into a position which
has never settled — a state the cash identity in (f) structurally cannot detect.

**Concrete gap.** There is no consumer that reads the exec-state fill ledger and the scored-trial
store *together*, family-agnostically, across the whole live record.

## 4. Priority, rationale, dependencies, execution order

**Priority: P0.** The programme's stated objective is increasing risk-aware ROI. The audit's overall
verdict records ROI as UNVERIFIED *because it is not measured at all*. Every other item in this
backlog is evaluated against a number that does not yet exist. It is also cheap: read-only, offline,
no node change, no venue call, no exposure.

**Dependency ordering (this item is STAGE 1 — the measurement substrate everything else is read
through):**
- **Depends on: nothing.** It measures whatever record exists, including the current record of
  6 fills and zero trading since 2026-09-15.
- **Consumes, does not require:** AUD-05 (the family tally). Deliberately independent — AUD-04 must
  produce a number *while* AUD-05's tally is failing.
- **Is a hard prerequisite for the EVALUATION (not the build) of:** AUD-06b (§11: sizing is judged
  only through this report), AUD-07 (exit P&L lands here, as a STANDING reconciliation — §8 AC#4).
- **Is the producer in a standing bilateral reconciliation with:** AUD-07's exit-window study.

**Execution order:** step 0 (evidence) → 1 (RED) → 2 (reader) → 3 (report+schema) → 4 (freshness
detector) → 5 (deploy).

## 5. Scope and explicit exclusions

**In scope:** one new analysis script, one new systemd oneshot + timer + wrapper, their tests, and a
dated evidence doc recording the step-0 null-hypothesis verdict. Both the cash-identity
reconciliation (§6 D4) and the independent open-position staleness check (§6 D9) live inside that one
script.

**Explicitly excluded:**
- **No change to any existing `src/` module, no node change, no strategy change, no new timer inside
  the node.** The report is a pure offline reader. The single `src/` addition is the new, pure,
  node-unimported `src/breezy/runtime/alert_ladder.py` (§6 D8); the alert emission reuses the
  existing sink and adds no runtime surface.
- **No new ledger.** The exec-state SQLite store is authoritative; this item adds no second record.
- **No venue REST call** (no balance poll — see T-4 §D4: a venue read on the decision path at an
  unverified rate limit is deferred, and this item does not need one).
- **No change to `n`, admissibility, PREREG semantics, or any family tally.** Portfolio ROI and the
  registered sequential statistic are different estimands; conflating them is the defect L-2 names.
- **No annualisation, no Sharpe/Sortino, no risk-adjusted headline.** At n=6 fills those are noise
  dressed as statistics.
- No dollar figure in any journal line, alert, or committed file (§6 D6).

## 6. Proposed changes grounded in inspected code

### Null hypothesis (L-1) — what Nautilus already provides, verified against installed source

`nautilus-trader==1.231.0` at `.venv/lib/python3.13/site-packages/nautilus_trader`:

- **`PortfolioAnalyzer` EXISTS** (`analysis/analyzer.py:38`) and is constructed on every `Portfolio`
  (`portfolio/portfolio.pyx:170`), with 17 statistics pre-registered (`:173-189`), plus
  `returns()` (`analyzer.py:133`), `portfolio_returns()` (`:158`),
  `get_performance_stats_pnls()` (`:562`), `get_performance_stats_returns()` (`:609`) and a
  tearsheet renderer (`analysis/tearsheet.py:367-454`). **Breezy must not rebuild any statistic
  this library already owns.**
- **The live path never invokes it.** `analyzer.calculate_statistics(account, positions)` has
  exactly one call site in the installed tree: `backtest/engine.pyx:2211`. `get_performance_stats_*`
  are called only from `backtest/engine.pyx:1446,1470` and `analysis/tearsheet.py`. **Nothing in
  `live/` calls either.** (Independently re-confirmed by both round-1 reviewers.)
- **Its realised-P&L series is keyed on CLOSED positions.** `Portfolio._handle_position_event`
  calls `analyzer.record_trade(...)` only under
  `updated_position.is_closed_c() and updated_position.realized_pnl is not None`
  (`portfolio/portfolio.pyx:666-670`); `add_positions` likewise skips `realized_pnl is None`
  (`analysis/analyzer.py:208-211`).
- **It is process-scoped.** The analyzer lives on the `Portfolio` object and is reset with it, so it
  cannot span the daily relaunch, let alone a 16-day record.

**Verdict (to be confirmed at step 0, not assumed):** the *statistics library* is native and is
reused; the *multi-day, cross-process, settlement-based realised-P&L record* is not, because on this
venue a weather position is realised by SETTLEMENT and the live family never sells (G-12), so the
Nautilus `Position` plausibly never closes and `record_trade` never fires. Step 0 decides this from
the record rather than asserting it.

### Inputs — all already persisted, all read-only

| # | Input | Location / seam | Supplies |
|---|---|---|---|
| I1 | Durable fill ledger | `~/.local/share/breezy/state/exec_polymarket_us.sqlite`, `DurableFillRecord` under `FILL_KEY_PREFIX` (`adapters/polymarket_us/exec/client.py:641,687,707`); read-only URI open pattern already written at `scripts/analysis/fill_time_count.py:84-98` | every fill: instrument (leg-bearing), price, qty, `cumulative_fee`, `fee_reconciled`, `order_side`, ts — capital deployed, fee total, the denominator |
| I2 | Scored trials | `~/.local/share/breezy/derived/scored_trials/<family_id>/` parquet, `ScoredTrial.pnl` from `trial_scorer.score_trial` | realised P&L after fees per SETTLED fill |
| I3 | Residual sidecar | `~/.local/share/breezy/derived/scored_trials/excluded_fills.jsonl` (PREREG v3 §5 residuals; `residual_trial_ids` / `admissible_scored_trials` already consumed at `family_tally_v2.py:633-642`) | dollar P&L of fills excluded from `n` but NOT from the portfolio |
| I4 | Balance series | the per-boot `AccountState` line in `~/.local/share/breezy/logs/breezy-trade-*.log` | one balance point per boot; the daily relaunch makes that a daily series |

**I3 is the single most important correctness property of this item.** `n` excludes duplicate-fill,
`q != 1` and fee-unreconciled rows; the *account* does not. A portfolio report that inherited the
tally's admissibility filter would under-report real losses. Every ledger fill lands in exactly one
of `scored` / `residual` / `unreconciled`, and the report asserts the partition.

### Design decisions

- **D1 — offline reader, systemd oneshot.** New `scripts/analysis/portfolio_roi_report.py` and
  `deploy/systemd/breezy-portfolio-roi.{service,timer}` + `portfolio-roi-run.sh`, structurally
  mirroring `breezy-position-monitor-report` and `family-tally-v2-run.sh` (marker gate, `MemoryHigh=1G`/
  `MemoryMax=2G`, `UMask=0077`, `Type=oneshot`, no `Restart=`, `Persistent=true`, and the
  `breezy-studies.lock` `flock -n` discipline `position-monitor-report-run.sh:87-96` already uses —
  one heavy job at a time).
  **Tick: `17:40:00 UTC`** — after the 17:20 family tally, and free against every occupied tick
  enumerated in `breezy-family-tally@.timer` (`tests/unit/test_deploy_timer_hours.py` enforces
  uniqueness).
- **D2 — gate on the existing marker, never on the tally.** Require
  `derived/score_live_trials_ok_<stamp>`, exactly as `family-tally-v2-run.sh:~150` does. Do NOT
  require the family tally to have succeeded: AUD-05 is open and AUD-04 must still produce a number.
- **D3 — family-agnostic period.** Default window `[first ledger fill, --as-of]`; `--since` narrows
  it. The report is over the ACCOUNT, so it never applies `filter_rows_to_manifest_prefix`; it
  labels each fill with the family whose prefix matches (or `UNATTRIBUTED`) as a column, never as a
  filter.
- **D4 — capital flow, detected not inferred, with a DERIVED tolerance (R1 fix) and a CASH-ONLY
  identity (R2 fix).** Round 2 established that the round-1 four-term form double-counted the
  settlement payout. It is replaced by the pure cash identity, in which **realised P&L is not a term
  at all** — it is a derived quantity over the same rows, never an input to the reconciliation:

  > `unexplained(D) = Δbalance(D) − proceeds(D) + capital_deployed(D)`

  **Term scoping (the three terms partition ONE set of ledger rows; they never overlap):**
  - `capital_deployed(D)` = Σ over fills whose **open** is dated `D`, of `cost + fee` (cash OUT).
  - `proceeds(D)` = Σ over positions whose **settlement** is dated `D`, of `payout` (cash IN).
    **The field `D` is read from, named from source (R3 fix — and it is a PROXY, stated as one):**
    no persisted record carries a venue settlement/credit timestamp. `DurableFillRecord`
    (`exec/client.py:641`) carries only the FILL time; `ScoredTrial` (`settlement/trial_scorer.py:131-151`)
    carries `climate_day` (an ISO date string — the weather day the contract resolves on),
    `scored_at_ns` (assigned `now_ns` at `trial_scorer.py:219`, i.e. when the scorer ran and settlement
    first became knowable to Breezy) and `settlement_basis`. **`proceeds(D)` is dated by the UTC
    calendar day of `scored_at_ns`, and by nothing else** — it is the only timestamp on the settlement
    side of the ledger, and it is at least causally downstream of the settlement itself, which
    `climate_day` is not.
    **The error this introduces, and its two components:** (i) for `settlement_basis == "nws_final"`,
    `scored_at_ns` lags the venue's actual credit by the scorer's run cadence (the nightly job), so
    proceeds can be attributed one UTC day late; (ii) for
    `settlement_basis == "venue_last_fair_price_fallback"` the lag is **structural and large** —
    `_resolve_settlement_basis` (`trial_scorer.py:243`) only admits that basis once
    `now_ns >= trial.scheduled_release_at_ns + _SEVEN_DAYS_NS`, so such a row is dated up to a week
    after the contract actually resolved.
    **How the identity absorbs or flags it — it must do exactly one, never silently both:** a
    same-day cash-out/cash-in mismatch caused by the proxy shows up as a nonzero `unexplained(D)` on
    the credit day and an equal-and-opposite `unexplained(D')` on the scoring day, so `Σ_D unexplained`
    is still `0` while both days breach the per-day tolerance. The report therefore (a) publishes the
    **cumulative** `Σ_D unexplained` alongside the per-day series and treats the cumulative figure as
    the authoritative detector, and (b) attaches to every breaching day a
    `proceeds_date_proxy: "scored_at_ns_utc_day"` label and a `settlement_lag_days` column
    (`scored_at_ns`'s UTC day − `climate_day`), so a breach attributable to the proxy is **named**
    rather than absorbed. A day whose entire breach is explained by rows with
    `settlement_lag_days > 1` or `settlement_basis == "venue_last_fair_price_fallback"` is reported as
    `UNEXPLAINED_PROXY_LAG`, not `UNEXPLAINED` — a distinct class, never netted away, never suppressed.
    Step 0(f) measures the real distribution of `settlement_lag_days` on the live record **before** the
    tolerance is trusted.

    **Settled-through cutoff — the cumulative invariant is evaluated only where it can hold (R4 mle
    defect 1).** `Σ_D unexplained = 0` is algebraically guaranteed only once BOTH the credit day and
    the `scored_at_ns` scoring day of every settlement fall inside the measured window. In the live,
    continuously-updated operating mode (not the closed worked example above) a settlement the venue
    has already credited but the scorer has not yet scored leaves its credit-day breach
    **uncancelled** until the scorer catches up — up to the structural ≥7-day fallback this plan
    derives from `trial_scorer.py:243` (`now_ns >= trial.scheduled_release_at_ns + _SEVEN_DAYS_NS`,
    read verbatim from source) on top of the nightly-cadence lag of `scored_at_ns = now_ns`
    (`trial_scorer.py:219`). Without a cutoff a report run near "today" shows a nonzero cumulative
    figure that is not a bug and is indistinguishable in the output from one that is. The report
    therefore computes, and prints in its header:

    > `SETTLED_THROUGH = D_now − max(7, observed p99 settlement_lag_days)`

    where `observed p99 settlement_lag_days` is read from the step-0(f) measured distribution (never
    a literal, same discipline as D4's tolerance), and the `7` floor is the structural fallback lag,
    so the cutoff can only widen past the structural bound, never narrow inside it.

    **Which lag statistic — the minimum-sample rule (R5 mle defect 1).** A 99th percentile over a
    handful of observations is not a tail estimate. At the live record's current size (on the order of
    six settled fills) a linear-interpolation percentile — the common default, and the one an
    implementer reaches for — interpolates between the two highest observations and can return a value
    strictly BELOW the observed maximum, narrowing the cutoff inside the worst lag actually seen and
    reintroducing exactly the false positive the cutoff exists to close. The statistic is therefore
    selected by sample size, by a named constant in the module:

    > `MIN_LAG_SAMPLE_N = 20`. With `lag_sample_n < MIN_LAG_SAMPLE_N`, the cutoff uses
    > `max(observed settlement_lag_days)`; at or above it, `p99(observed settlement_lag_days)`. An
    > EMPTY sample (`lag_sample_n == 0`, nothing scored yet) uses neither and falls back to the bare
    > structural floor `7`.

    `MIN_LAG_SAMPLE_N` is a sample-size rule, not a tuned parameter, and is deliberately NOT derived
    from this pipeline's own data — the sample is the quantity being measured, so tuning the threshold
    on it would be circular. Its basis: a `p99` is interpolated inside the top `1/n` of the sample, so
    below `n = 20` it is an extrapolation over the top one or two order statistics rather than a tail
    estimate; `20` is the threshold the round-5 statistical review named. **The rule is conservative in
    one direction only:** `max() >= p99` on any sample and both branches are floored by the structural
    `7`, so the small-`n` branch can only WIDEN the cutoff, never narrow it — it cannot become a
    silencer, and the §7 step-1 anti-suppression assertion is unaffected. The artefact header states
    **which statistic was used and the observed sample size**, verbatim:
    `settled_through_statistic=<max|p99> lag_sample_n=<n>`, so no reader can mistake a small-sample
    `max` for a calibrated percentile. Step 0(f) records `lag_sample_n` alongside the distribution, so
    which branch the live record takes is a measured fact rather than an assumption. **The cumulative
    `Σ_D unexplained` pass/fail determination applies ONLY to days `D ≤ SETTLED_THROUGH`.** Days
    after the cutoff are still computed, still printed, and still carry `proceeds_date_proxy`,
    `settlement_lag_days` and their per-day class; they are additionally labelled
    `PROVISIONAL_IN_FLIGHT` and are **excluded from the cumulative pass/fail determination, so a
    settlement still in flight can never produce a breaching cumulative verdict** — and, symmetrically,
    can never be used to declare the reconciliation GREEN. **Nothing is suppressed:** the provisional
    tail's own `Σ unexplained` is printed as a separate, explicitly non-gating figure beside the
    settled cumulative one, so a genuine failure inside the tail is visible immediately and becomes
    gating the moment the cutoff advances past it. The cutoff changes nothing per-day: the per-day
    tolerance, the per-day breach emission and the `UNEXPLAINED_PROXY_LAG` class are unchanged on
    both sides of it.
  - Every `DurableFillRecord` contributes to `capital_deployed` on exactly one date (its open) and to
    `proceeds` on exactly one date (its settlement); the two dates are usually different and the two
    terms are disjoint by construction. **No row is counted twice, and the settlement payout appears
    in the cash identity exactly once.**
  - `realised_pnl(position) = payout − cost − fee`, booked **once**, on the settlement date. It is the
    ROI numerator (I1) and the AUD-07 reconciliation field — never a term in the identity above.

  **Worked two-day example (R2 fix — reproduced as a test fixture, §7 step 1).** One YES contract
  bought on day 1 at ask `$0.40` with fee `$0.03`, settling HIGH on day 5 for `$1.00`:

  | Day | `capital_deployed` | `proceeds` | `Δbalance` | `unexplained` | realised P&L booked |
  |---|---|---|---|---|---|
  | D1 | `0.43` | `0.00` | `−0.43` | `−0.43 − 0.00 + 0.43 = 0.00` | — |
  | D2–D4 | `0.00` | `0.00` | `0.00` | `0.00` | — |
  | D5 | `0.00` | `1.00` | `+1.00` | `+1.00 − 1.00 + 0.00 = 0.00` | `1.00 − 0.43 = +0.57` |

  The payout `$1.00` is counted **once** (as `proceeds` on D5) in the cash identity and **once** (as
  the `payout` term) in realised P&L; the outlay `$0.43` is counted **once** as `capital_deployed` on
  D1 and **once** as the `cost + fee` term in realised P&L. **Cumulative cross-check, asserted by the
  same test:** `Σ_D Δbalance = −0.43 + 1.00 = +0.57 = Σ realised P&L`, and `Σ_D unexplained = 0`. A
  losing settlement (`payout = 0.00` on D5) gives `Δbalance(D5) = 0.00`, `unexplained(D5) = 0.00` and
  realised P&L `−0.43` — the same identity with no sign special-case.

  The tolerance is **not an asserted constant**: it is
  `TOLERANCE_day = n_fills_that_day × $0.01`, because the only rounding this pipeline performs is
  the venue-cent `ROUND_UP` quantisation shared by `order_cost_usd` and the ledger true-up
  (`_round_cost_up_to_cent`, `operator_controls.py:220-244` — R2 re-anchor: the round-1 `:213-215`
  citation was the surrounding block, the `def` is at `:220`, confirmed by the round-2 review), so the
  maximum accumulated round-up error on a day is exactly one cent per fill. `|unexplained| > TOLERANCE_day` emits
  `UNEXPLAINED_CAPITAL_FLOW day=<d> magnitude_cents=<…>` into the PRIVATE artefact only. Step 0(e)
  additionally measures the observed `|unexplained|` distribution across the existing record and
  records it, so the derivation is checked against data rather than trusted.
  A deposit or withdrawal is **reported, never valued into ROI**: the ROI denominator is capital
  DEPLOYED (I1), not account size, so a flow cannot silently move the headline.
- **D5 — two registered baselines, stated before the numbers are read.**
  - **B0 — cash.** `0.00` return on the same deployed capital over the same period. The operator-facing
    comparator: did trading beat not trading.
  - **B1 — fee-drag null.** Under H0 "the quoted ask is fair", `E[pnl_i] = −fee_i`, so
    `ROI_B1 = −Σ fee_i / Σ cost_i`. The engineering comparator: did the edge recover its own costs.
  - **Explicitly NOT a baseline:** the PREREG sequential verdict (different estimand — L-2), and any
    market-index or annualised figure.
  - **Registration of the choice (R1 fix):** B0 is the headline and B1 the diagnostic. This is now
    recorded as a *build decision in the artefact's own header*, with both figures printed with equal
    prominence, so no reader depends on which one was nominated. See §12.
- **D6 — redaction is an artefact boundary, not a function.** `adapters/polymarket_us/redaction.py`
  governs headers/URLs/free-text secrets (`:33-42`, `:70-80`) and says nothing about balances
  (independently confirmed in round 1), so it is **not** the control here. The control is: every
  currency-denominated figure goes ONLY to
  `~/.local/share/breezy/derived/PRIVATE_portfolio_roi_<stamp>.{md,json}` (mode 0600, under the
  gitignored `PRIVATE_` convention already used for
  `PRIVATE_v1_portfolio_positions_open_positions_20260916.positions.json`); the journal line, the
  wrapper log and any alert carry only dimensionless ratios and counts. Rationale is L-39 and the
  MULTI_POSITION plan's S6 (`MULTI_POSITION_PER_STATION_2026-09-14.md:90`): a dollar figure printed
  beside a fill price reconstructs the operator-reserved per-position cap.
- **D7 — VERSIONED OUTPUT SCHEMA (R1 MATERIAL, accepted).** The JSON sibling carries
  `"schema_version": 1` as a top-level integer. The round-1 claim that the repo has no precedent is
  **corrected**: the precedent exists and is the one to copy — `station_observation.py:110,126,213,
  234,248` (declared field, constructor default, `to_dict`, `from_dict` read, and an explicit
  `pa.field("schema_version", pa.int64(), nullable=False)` in the schema), and
  `trial_day_latch.py:1221`. What is true is that no `scripts/analysis/` evidence artefact carries
  one, which is exactly the defect. Policy, stated here and in the module docstring:
  **additive-only within a major version; any removal or semantic change increments it; every reader
  REFUSES an unknown version rather than best-effort parsing it.** A `read_portfolio_roi_report()`
  helper in the same module is the single sanctioned reader and raises
  `UnknownPortfolioRoiSchemaError` on any version it does not know. AUD-07's standing cross-check and
  AUD-06b's post-merge reconciliation consume the report only through that helper.
- **D8 — FROZEN-INPUT DETECTOR (R1 MATERIAL, accepted).** Fail-closed on *absent* inputs is not
  enough: an input that is present, readable and **no longer growing** currently looks identical to a
  quiet account. The report therefore records, per run,
  `newest_ledger_fill_ts`, `newest_scored_trial_ts`, and `days_since_newest_input`, plus a
  streak counter persisted in `derived/portfolio_roi/.input_freshness.json`. When
  `days_since_newest_input > 3` for **≥3 consecutive runs**, emit a dimensionless
  `PORTFOLIO_ROI_INPUTS_FROZEN streak=<k> days_since_newest_input=<d>` through the existing sink
  (`resolve_alert_sink` + `emit_alert`, `src/breezy/runtime/health.py:579` / `:668`; `AlertPayload` at
  `:351`, exactly the four fields `severity`/`event`/`site`/`detail` enumerated at `:104`; delivering
  since `f97c26f`).

  **OWNERSHIP OF THE SHARED LADDER (R3 fix — one module, one test suite, one owner).** Round 3 found,
  on both this record and AUD-07's, that the ladder was specified twice in prose and implemented twice
  in two modules with two latch files, with nothing preventing the two period-key computations from
  diverging. **AUD-04 OWNS the implementation.** This item ships
  `src/breezy/runtime/alert_ladder.py` exposing one pure function —
  `evaluate_streak(*, streak: int, last_alert_severity: str | None, last_alert_period_key: str | None,
  now_ns: int) -> LadderDecision` — plus the UTC-ISO-week and UTC-day period-key helpers and the
  latch-file read/write with its `schema_version`. One shared test module,
  `tests/unit/test_alert_ladder.py`, is the single place the ladder's semantics are asserted (streak
  increment/reset/clear, one-way escalation within a streak, restart-surviving dedupe, missing/
  unparseable latch → `streak = 0` and re-alert, the ISO-week boundary and the year-boundary ISO-week
  case). **AUD-07 depends on this module by id and imports it; it does not re-specify or re-implement
  it, and its own RED-test list references `tests/unit/test_alert_ladder.py` rather than restating
  those cases.** Each consumer still owns its own latch FILE and its own event names — only the state
  machine and the period keys are shared.
  **No dependency cycle:** the code dependency runs AUD-07 → AUD-04 only. AUD-04's module imports
  nothing from AUD-07, and AUD-04's obligation to AUD-07 is the standing P&L reconciliation, which is
  a DATA read of AUD-07's published artefact performed at report time, not an import. Asserted by
  `test_the_alert_ladder_module_imports_nothing_from_the_exit_window_study` and enforced by
  `lint-imports`. If AUD-07 ships first it must not fork the ladder: it blocks on this module, which
  is a one-file dependency, or it lands with the ladder inline **and a RED-on-divergence cross-test**
  that is deleted when it switches to the shared import. AUD-05 §6 D-F's daily latch is a simpler,
  separate control and is not merged into this module.

  **RE-ALERT LADDER (R2 MATERIAL fix — replaces "one alert per streak"; implemented once, in the module above).** Round 2 established that a
  once-per-streak latch goes permanently silent for the life of an ongoing outage, because re-arming
  requires a new input that a genuinely dead pipeline will never produce — and the live record is
  already past the trigger. The latch is therefore **recurring and escalating**, and this ladder is
  the SHARED specification also used by AUD-07's `EXIT_CORPUS_FROZEN` and
  `EXIT_PNL_RECONCILIATION_MISMATCH`, so the three controls cannot drift apart:

  | Streak (consecutive stale runs) | Severity | Re-emit cadence |
  |---|---|---|
  | `< 3` | — | silent |
  | `3 … 13` | `WARN` | once per **UTC ISO week** (first qualifying run of each week) |
  | `≥ 14` | `CRITICAL` | once per **UTC day** — the same daily-repeat cadence AUD-05 §6 D-F uses |

  - **Persisted latch state, surviving restarts:** `derived/portfolio_roi/.input_freshness.json`
    carries `streak`, `first_frozen_utc_day`, `last_alert_severity` and `last_alert_period_key` (the
    ISO-week or UTC-day key already alerted at). A run whose computed period key equals
    `last_alert_period_key` at the same severity emits nothing — so a process restart, a host reboot
    or a same-period retry never re-pages, while a missed period is picked up on the next run rather
    than lost. A missing or unparseable latch file is treated as `streak = 0` and **re-alerts on the
    next qualifying run** (fail-loud, never fail-silent).
  - **Clear condition:** `days_since_newest_input <= 3` on any run resets `streak` to `0`, clears
    `last_alert_severity` / `last_alert_period_key`, and emits exactly one `INFO`
    `PORTFOLIO_ROI_INPUTS_FROZEN_CLEARED streak_len=<k>` so the recovery is observable and not merely
    an absence. The ladder then re-arms in full: a later freeze fires `WARN` again at `streak == 3`
    and escalates to `CRITICAL` again at `14`.
  - **Escalation is one-way within a streak:** once `CRITICAL` has been emitted for a streak, the
    severity never returns to `WARN` without a clear.
  - Every ladder field is dimensionless (a count of runs, a count of days) — D6's no-currency rule is
    unaffected.

  This deliberately mirrors AUD-07's `EXIT_CORPUS_FROZEN`; the two are the same control applied to the
  two halves of the same pipeline, and after this revision they are the same ladder.
  Note the honest limitation, stated in the artefact: today a frozen input is the *expected* state
  (no fills since 2026-09-15), so the detector's first job is to make that state legible, not to
  signal a regression — but the ladder ensures a *genuinely* dead pipeline, which starts identically,
  escalates to a daily CRITICAL rather than relying on a single WARN from weeks earlier having been
  seen and remembered.
- **D9 — OPEN-POSITION STALENESS / AGING CHECK (R5 pm MATERIAL, accepted). An independent detector,
  because the cash identity structurally cannot carry this signal.** Substituting D4's own term
  scoping for a position that opens on `D1` and never settles gives
  `unexplained(D1) = (−cost−fee) − 0 + (cost+fee) = 0`: `capital_deployed(D1)` cancels the balance leg
  on the open day, and the only term that could ever flag a missing payout — `proceeds` — is scoped to
  a settlement day that, for such a position, never arrives. **No cutoff fixes this.**
  `SETTLED_THROUGH` governs WHEN a day's cumulative figure becomes gating, not WHETHER a specific
  position's absence of proceeds is ever compared against anything; once `D1` ages past the cutoff the
  identity still reads `unexplained(D1) = 0` — a clean PASS, forever, while capital sits in a position
  that never resolves. **This limitation of the cash identity is stated in the artefact itself**, and
  the detector below is what closes it. It is orthogonal to D8: D8 asks whether the pipeline is still
  producing inputs at all (a growing corpus with one stuck position inside it never trips it); D9 asks,
  per position, whether this one ever settled.

  **The records that drive it, verified from source:**
  - `FilledTrial` (`src/breezy/settlement/trial_scorer.py:83`) carries `trial_id` (`:113`),
    `climate_day` (`:115`), `filled_at_ns` (`:121`) and `scheduled_release_at_ns` (`:124` — "when the
    NWS FINAL was scheduled to publish for this station-day", stamped with the venue's real settlement
    instant by `_with_scheduled_release_at_ns`, `scripts/analysis/score_live_trials.py:1161-1187`,
    never midnight UTC). It is read by `read_filled_trials_state_db`
    (`scripts/analysis/score_live_trials.py:556`) over the same exec-state store I1 reads.
  - `ScoredTrial` (`trial_scorer.py:131-151`) carries the matching `trial_id` (`:134`). **"Filled but
    never settled" is therefore decidable as a left-anti-join on `trial_id`** — the same key §8 AC #4
    already joins on — with the in-repo precedent for the "never scored" predicate at
    `score_live_trials.py:1277-1284` (`_latest_stored_row` returns `None` when no row has ever been
    scored for a `trial_id`).
  - `DurableFillRecord` (`adapters/polymarket_us/exec/client.py:641-685`) carries `ts_event` (`:675`)
    and **no settlement or credit timestamp** — re-confirming why the horizon is anchored on
    `scheduled_release_at_ns` rather than on anything the ledger itself carries.
  - **Distinct from the existing census, which it must not duplicate:** `find_unresolved_takes`
    (`score_live_trials.py:1030-1158`) already reports a TAKEN latch with no `DurableFillRecord` —
    taken-but-never-FILLED. D9 is the next link in the same chain: FILLED but never SETTLED. Neither
    covers the other, and this item adds no second definition of the first.

  **The maximum settlement horizon, named here and not left to the implementer:**

  > `MAX_SETTLEMENT_HORIZON_NS = trial.scheduled_release_at_ns + _SEVEN_DAYS_NS + SETTLEMENT_HORIZON_GRACE_NS`
  > with `SETTLEMENT_HORIZON_GRACE_DAYS = 3`.

  **Evidence basis, not a guess.** `_SEVEN_DAYS_NS` is the structural bound read verbatim from
  `_resolve_settlement_basis` (`trial_scorer.py:243`): once
  `now_ns >= trial.scheduled_release_at_ns + _SEVEN_DAYS_NS` the scorer settles the trial on the
  `venue_last_fair_price_fallback` basis as soon as a venue reading exists, so past that instant a
  trial can still be unscored only because NWS published no final AND the venue booked no settlement
  reading — which is the stuck condition itself, not ordinary lag. `SETTLEMENT_HORIZON_GRACE_DAYS = 3`
  covers the scorer's own cadence on top of that bound: the scorer is a nightly oneshot, so a trial
  becoming scorable at the 7-day boundary is scored on the next nightly run (≤1 day) and one failed or
  missed nightly run adds another (≤2); `3` leaves a full day beyond that worst case. It is a
  cadence-derived margin, **checked against step 0(f)/(g)'s measured record before it is trusted** — if
  any observed trial settles later than `7 + 3` days past its scheduled release, the constant is
  revised in a recorded evidence update, never silently tuned. It is not an operator-reserved value and
  assigns none.

  **Behaviour when the horizon is exceeded — loud, delivered, and fail-closed on the ROI figure:**
  - The trial is flagged `PERMANENTLY_UNSETTLED` and printed in its own report block with `trial_id`,
    `station`, `climate_day`, its fill's UTC day and `days_past_horizon`.
  - **It is never excluded from any total.** Its `capital_deployed` stays in the denominator exactly
    where the ledger puts it; the report never quietly drops it to make the partition or the identity
    look clean. §8 AC #2's partition is unaffected — such a trial is still in exactly one of
    `scored`/`residual`/`unreconciled`; `PERMANENTLY_UNSETTLED` is an orthogonal label, not a fourth
    bucket.
  - **Fail-closed on the ROI figure, not on the run.** The JSON carries
    `roi_status: "GATED_UNSETTLED_CAPITAL"` and `unsettled_capital_positions: <k>` whenever `k > 0`,
    and the D7 sanctioned reader `read_portfolio_roi_report()` **raises `UnsettledCapitalRoiError` when
    a consumer reads `roi` / `roi_minus_b0` / `roi_minus_b1` while gated**, so AUD-06b and AUD-07
    cannot evaluate against a headline ROI computed over capital that may never return. The run itself
    still writes its artefact and exits 0 — a detected, reported condition is a success of the
    detector, not a crash — so §8 AC #1 is unaffected.
  - **Alert:** `PORTFOLIO_ROI_POSITION_PERMANENTLY_UNSETTLED count=<k> max_days_past_horizon=<d>`
    through the same shipped sink as D8 (`resolve_alert_sink` / `emit_alert`,
    `src/breezy/runtime/health.py:579` / `:668`), driven by the D8-owned
    `src/breezy/runtime/alert_ladder.py` state machine with its **own latch file**
    `derived/portfolio_roi/.unsettled_positions.json` and its own event names — the module is shared,
    the latch file and event names are not (D8's ownership rule, unchanged). Every field is a count or
    a day count, so D6's no-currency rule holds unchanged.
  - **Standing and independent of the cumulative pass/fail determination:** it runs on every run, over
    positions on BOTH sides of `SETTLED_THROUGH`, and a GREEN cumulative reconciliation never
    suppresses it.

## 7. Ordered implementation / verification steps

0. **EVIDENCE FIRST (read-only, no code).** Produce
   `docs/evidence/PORTFOLIO_ROI_INPUTS_2026-09-__.md` recording, with commands:
   (a) the ledger fill count and the per-fill fields actually present — `DurableFillRecord` is
   confirmed (round 1) to carry `cumulative_fee`, `fee_reconciled: bool` and a sign-preserving
   `order_side`; step 0 records the *values* on the real record, which decides whether "after fees"
   is honest or requires an `UNRECONCILED_FEE` label (cf. R-1);
   (b) whether any Nautilus `Position` has ever reached `is_closed` on live — grep the node logs for
   `PositionClosed` with a positive control (L-8). This RETIRES the §6 null hypothesis either way;
   (c) how many distinct `AccountState` balance points exist across the log set, over how many
   calendar days, **and the verbatim text of one such line**, which becomes the parser fixture (see
   step 2);
   (d) whether the six venue-confirmed fills partition cleanly into scored/residual/unreconciled;
   (e) the observed `|unexplained|` distribution under D4's derived tolerance, so the tolerance is
   checked against the record before it is frozen;
   (f) **(R3)** the measured distribution of `settlement_lag_days` (`scored_at_ns`'s UTC day minus
   `climate_day`) over every `ScoredTrial` in the live store, split by `settlement_basis`, so D4's
   `proceeds(D)` proxy error is a measured quantity before the tolerance is trusted. Record the max,
   the median, **the sample size `lag_sample_n`** (which decides D4's `max`-vs-`p99` branch) and the
   count of rows with `settlement_basis == "venue_last_fair_price_fallback"`.
   (g) **(R5)** the count of `FilledTrial` rows with NO `ScoredTrial` sharing their `trial_id`
   (the left-anti-join of §6 D9), each with its `scheduled_release_at_ns` and its elapsed days past
   `MAX_SETTLEMENT_HORIZON_NS`, so D9's horizon and its `SETTLEMENT_HORIZON_GRACE_DAYS = 3` margin are
   checked against the live record before they are frozen, and so the number of
   `PERMANENTLY_UNSETTLED` positions on today's record is a measured fact at build time.
   **If (b) shows positions DO close, the design changes**: `analyzer.add_positions` +
   `get_performance_stats_pnls` is then reused for the within-session statistics and only the
   cross-process series is authored here.
1. **RED tests** (`tests/unit/test_portfolio_roi_report.py`), all failing today because the module
   does not exist:
   - `test_every_ledger_fill_lands_in_exactly_one_bucket` — a synthetic store with one scored, one
     residual and one unreconciled fill; the partition assertion holds and the totals sum.
   - `test_a_residual_fill_is_counted_in_portfolio_pnl_but_never_in_n` — the item's core invariant.
   - **NEW (R1)** `test_a_no_leg_and_a_yes_leg_fill_on_one_station_day_are_both_counted_in_capital_deployed`
     — two `DurableFillRecord` rows on one station-day, one on `<slug>` and one on the composite
     `<slug>^no` id (`symbology.no_leg_instrument_id:277`, `leg_of:289`), asserting capital deployed
     is the **sum of both legs' costs, never a net**. Grounding: the venue nets a held NO as a short
     of YES, while Breezy holds it as a LONG on a distinct `^no` instrument, and only BUYs are
     mappable (`submit_chain.py unmappable_order_reason`). So the leg-aware ledger is already
     correct *by construction* — the test exists to stop an implementer "simplifying" the reader
     into a single per-station accumulator and re-introducing the netting bug this repo has already
     corrected twice. The test asserts the **leg sign is applied before any reconciliation**, per the
     same rule.
   - `test_an_absent_ledger_returns_none_not_zero` — fail-closed, mirroring
     `fill_time_count.py:119-121`.
   - `test_a_missing_balance_point_is_unknown_not_interpolated`.
   - `test_an_unexplained_balance_delta_is_reported_and_never_netted_into_roi`.
   - `test_the_unexplained_tolerance_is_one_cent_per_fill_not_a_literal` (D4).
   - **NEW (R3)** `test_proceeds_are_dated_by_scored_at_ns_not_by_climate_day` — two fixtures with the
     same `climate_day` and `scored_at_ns` values three UTC days apart; assert `proceeds` lands on the
     `scored_at_ns` day, and that the emitted row carries `proceeds_date_proxy ==
     "scored_at_ns_utc_day"`. This is the test that stops a later implementer silently substituting
     `climate_day`.
   - **NEW (R3)** `test_a_breach_explained_entirely_by_proxy_lag_is_classified_not_netted` — a
     settlement dated `D` but scored on `D+7` (the `venue_last_fair_price_fallback` shape,
     `trial_scorer.py:243`); assert both days breach the per-day tolerance, the class is
     `UNEXPLAINED_PROXY_LAG` on both, `settlement_lag_days == 7` is reported, and
     `Σ_D unexplained == 0`.
   - **NEW (R5)** `test_an_in_flight_settlement_inside_the_settled_through_window_does_not_fail_the_cumulative_check`
     — the in-flight fixture D4's cutoff exists for: a settlement credited on `D_now − 2` (a
     `Δbalance` cash-in) whose `ScoredTrial` does **not exist yet** (unscored, so it contributes no
     `proceeds`), against a step-0(f) distribution whose p99 is below 7. Assert `SETTLED_THROUGH ==
     D_now − 7` computed from that distribution rather than a literal; that the credit day is
     printed, classified and labelled `PROVISIONAL_IN_FLIGHT`; that the settled cumulative
     `Σ_D unexplained` over `D ≤ SETTLED_THROUGH` is `0` and PASSES; and that the provisional tail's
     own nonzero `Σ unexplained` is still printed as a separate non-gating figure. **Anti-suppression
     half, asserted in the same test:** the identical breach placed at `D ≤ SETTLED_THROUGH` DOES
     fail the cumulative check, so the cutoff cannot be widened into a blanket silencer.
   - **NEW (R6)** `test_a_small_lag_sample_uses_max_not_p99_and_says_so_in_the_header` — a synthetic
     step-0(f) corpus of `lag_sample_n = 6` observations whose linear-interpolation `p99` falls BELOW
     the sample maximum; assert `SETTLED_THROUGH` is computed from `max(...)` (never the interpolated
     `p99`), that the resulting cutoff is therefore no narrower than the worst observed lag, and that
     the header carries `settled_through_statistic=max lag_sample_n=6`. A companion case at
     `lag_sample_n = 20` asserts the `p99` branch and `settled_through_statistic=p99`, and an
     `lag_sample_n = 0` case asserts the bare structural floor `7`. This is the test that stops an
     implementer hard-coding a percentile call at any sample size (§6 D4).
   - **NEW (R6)** `test_a_position_that_opens_and_never_settles_is_flagged_not_silently_reconciled`
     — the permanently-unsettled fixture §6 D9 exists for: one `FilledTrial` opened on `D1` with a
     matching `Δbalance` cash-out, **no `ScoredTrial` with that `trial_id`, ever**, and `now_ns` far
     past `scheduled_release_at_ns + _SEVEN_DAYS_NS + SETTLEMENT_HORIZON_GRACE_NS`, with `D1` aged well
     inside `D ≤ SETTLED_THROUGH`. Assert: (a) `unexplained(D1) == 0` and the cumulative check PASSES —
     i.e. the test pins the cash identity's blindness as real rather than assuming it away; (b) the
     trial is nonetheless flagged `PERMANENTLY_UNSETTLED` with its `days_past_horizon`; (c) its
     `capital_deployed` is still in the denominator and in its partition bucket, never dropped;
     (d) `roi_status == "GATED_UNSETTLED_CAPITAL"` and the D7 reader raises `UnsettledCapitalRoiError`
     on `roi`; (e) exactly one `PORTFOLIO_ROI_POSITION_PERMANENTLY_UNSETTLED` alert is emitted, carrying
     no currency-denominated field. **Negative half, asserted in the same test:** the identical fixture
     with `now_ns` one day INSIDE the horizon is NOT flagged and leaves `roi_status` ungated, so the
     detector cannot be satisfied by flagging every open position.
   - **NEW (R2)** `test_the_worked_open_then_settle_example_reconciles_to_zero_on_both_days` — the §6
     D4 table as a fixture (buy `$0.40 + $0.03` on D1, settle `$1.00` on D5), asserting
     `unexplained == 0` on **both** days independently, `Σ_D unexplained == 0`, and
     `Σ_D Δbalance == Σ realised P&L == +0.57`. This is the test that pins the settlement payout to
     exactly one appearance in the cash identity.
   - **NEW (R2)** `test_a_settled_position_payout_is_never_counted_in_both_proceeds_and_capital_deployed`
     — the disjointness of the two cash terms, asserted directly over the ledger rows.
   - **NEW (R2)** `test_a_losing_settlement_uses_the_same_identity_with_no_sign_special_case`.
   - `test_roi_is_reported_against_both_registered_baselines`.
   - `test_the_journal_line_carries_no_currency_denominated_field` (D6) — a scan over the emitted
     stdout/log line in the shape `MULTI_POSITION_PER_STATION_2026-09-14.md:89` specifies for S6.
   - `test_a_fill_whose_fee_is_unreconciled_is_labelled_not_silently_modelled`.
   - **NEW (R1)** `test_the_json_sibling_carries_a_schema_version`.
   - **NEW (R1)** `test_a_reader_refuses_an_unknown_schema_version` — raises, never best-effort.
   - **NEW (R1)** `test_the_report_header_states_the_sample_size_and_its_power_caveat`.
   - **NEW (R1)** `test_three_consecutive_stale_input_runs_emit_inputs_frozen_at_warn` — the first
     qualifying run of a streak emits exactly one `WARN`.
   - **NEW (R2, ladder)** `test_a_thirty_day_outage_re_alerts_weekly_then_escalates_to_daily_critical`
     — drive 30 consecutive stale runs and assert the **exact** emitted sequence: one `WARN` per UTC
     ISO week while `3 ≤ streak ≤ 13`, then one `CRITICAL` per UTC day from `streak == 14` onward.
     This is the day-N-repeat test the round-2 MATERIAL finding requires; it fails against the
     round-1 once-per-streak latch.
   - **NEW (R2, ladder)** `test_a_same_period_rerun_does_not_re_alert` — two runs inside one period
     key emit once.
   - **NEW (R2, ladder)** `test_the_latch_survives_a_process_restart_without_re_alerting` — reload
     `.input_freshness.json` mid-streak; no duplicate emission for an already-alerted period key.
   - **NEW (R2, ladder)** `test_a_missing_or_corrupt_latch_file_re_alerts_rather_than_failing_silent`.
   - **NEW (R2, ladder)** `test_fresh_input_clears_the_streak_emits_one_info_and_fully_re_arms` — the
     clear-then-refire test: a fresh input clears the streak and emits one `INFO` `..._CLEARED`; a
     subsequent freeze fires `WARN` again at `streak == 3` and `CRITICAL` again at `14`.
   - **NEW (R2, ladder)** `test_severity_never_de_escalates_within_one_streak`.
   - **NEW (R1)** `test_the_frozen_inputs_alert_carries_no_currency_denominated_field` — every ladder
     field (`streak`, `days_since_newest_input`, `streak_len`) is dimensionless.
2. **Reader module.** `portfolio_roi_report.py`. **Loader function signatures, verified against
   source and named here so no implementer re-opens `family_tally_v2.py` to find the call shape (R2
   fix) — all four are `src/` definitions, so this script imports `breezy.*`, never `scripts.*`:**
   - **Ledger:** `DurableFillRecord` (`src/breezy/adapters/polymarket_us/exec/client.py:641`) read
     under `FILL_KEY_PREFIX` (`:384`), via the read-only `mode=ro` URI idiom of
     `fill_time_count.py:84-98` — do not re-implement a second SQLite policy.
   - **Scored trials:** `breezy.persistence.scored_trial_store.read_scored_trials(directory: Path) ->
     tuple[ScoredTrial, ...]` (`:118`) — the same loader `family_tally_v2.py` imports at its `:108`.
     Absent/empty directory returns `()`, never an error.
   - **Residuals:** `breezy.persistence.residual_fills.residual_trial_ids(store_dir: Path) ->
     frozenset[str]` (`:234`). This is the ONE definition:
     `family_tally_v2.residual_trial_ids` (`:868`) merely delegates to it, and its own docstring says
     "this tally must never carry a second residual predicate" — so this report imports the `src/`
     function directly rather than the script's wrapper.
   - **Admissibility:** `breezy.persistence.realized_draws.admissible_scored_trials(rows:
     tuple[ScoredTrial, ...], *, residual_trial_ids: frozenset[str]) -> tuple[ScoredTrial, ...]`
     (`:187-189`), so the report's `n_scored` and the tally's `n` cannot drift apart.
   And the **balance-line parser (R1 fix)**: anchored on the literal
   `AccountState(` token in the node log, the field extracted by a named-group regex pinned in the
   module and **tested against the verbatim line captured at step 0(c)** as a fixture. A line that
   does not match is `UNKNOWN`, never a partial parse and never a fallback regex — the report
   reports how many lines failed to parse.
3. **Report + reconciliation.** Emit the PRIVATE Markdown + the versioned JSON sibling, with a
   fail-closed partition assertion, the header block (period, `n_fills`, the power caveat, the
   balance-semantics caveat, the estimand caveat) and an explicit
   `MISSING INPUTS (reported, not fabricated)` block in the exact style the exit-window study already
   prints. **Report header line, verbatim shape:**
   `n=<k> settled fills over <d> days; NOT a statistically powered estimate of improvement over B0 or B1 at this sample size.`
4. **Freshness detector (D8)** + its latch file, and the **open-position staleness check (D9)** +
   its own separate latch file, both driven by the one shared `alert_ladder.py` state machine.
5. **Deploy.** Unit + timer + wrapper, `systemctl --user enable --now breezy-portfolio-roi.timer`,
   plus a deploy test in the shape of `tests/unit/test_family_tally_v2_deploy.py` asserting every
   env var the wrapper requires is present on the unit.
6. `scripts/ci/run_tests_no_egress.sh` + `lint-imports` (L-48: adapters never import
   `breezy.runtime`; this script imports neither).

## 8. Measurable acceptance criteria and required evidence

1. The report runs unattended and writes a dated artefact on ≥3 consecutive days with exit 0, with
   the journal showing no currency figure. Evidence: `systemctl --user status`, 3 artefacts,
   `journalctl` excerpt.
2. **Partition holds:** `n_scored + n_residual + n_unreconciled == n_ledger_fills`, asserted in the
   report and non-bypassable. On today's record `n_ledger_fills` is expected to equal the count the
   audit records (6 venue-confirmed fills of 7 orders,
   `AUTONOMY_ROI_AUDIT_2026-09-21.md:110`) — but that figure is **agent-reported (A)**, so the
   criterion is: the partition holds AND the measured count is recorded; a divergence from 6 is a
   finding to record (and to correct the audit with), never a reason to adjust the report.
3. The report states, for the default period: total realised P&L after fees, capital deployed, fee
   total, ROI, `ROI − B0`, `ROI − B1`, the number of balance points, the number of days with an
   UNKNOWN balance, and the header power caveat.
4. **STANDING cross-check (R1 fix — was one-shot; R2 defines the matching key).** On **every date for
   which both** this report and the nightly exit-window study exist, realised P&L over the
   **overlapping positions** must match that study's `sum_hold_pnl`. **"Overlapping" is defined
   identically in AUD-07 §6 and here: the inner join on `trial_id`** — the one key both artefacts
   already carry (the study is per scored trial; this report labels every reconciled fill with its
   `trial_id` via `admissible_scored_trials`), so neither `(instrument_id, fill_ts)` nor station-day
   is used. **Until any exit ever fires, "hold" and "actual" are definitionally the same outcome** (the
   live family never sells; `exit_gate.py:55 _EXIT_RULE_REGISTERED_FAMILIES` contains only
   `pm_us_crh_exit_v4`, which is not the live family), so the reconciliation must match **to the cent
   on every joined row today**, not merely on average — a partial mismatch is an alarm, never expected
   slack. Today's figure is `-0.6100` at `n_positions=5` (
   `~/.local/share/breezy/derived/exit_window_study/<date>_nightly/exit_window_study.md`), or the
   divergence is named with its cause in the artefact. The check is executed by the report itself
   through the D7 reader (never by hand), and a persistent unexplained mismatch emits
   `EXIT_PNL_RECONCILIATION_MISMATCH` through the same sink. AUD-07 carries the mirror obligation.
5. The JSON sibling carries `schema_version`, and a reader handed `schema_version: 999` raises.
6. **(R2 — replaces the round-1 single-shot criterion, which locked the defect in as intended
   behaviour.)** `PORTFOLIO_ROI_INPUTS_FROZEN` follows the §6 D8 **re-alert ladder**: exactly one
   `WARN` on the first qualifying run of each UTC ISO week while `3 ≤ streak ≤ 13`, then exactly one
   `CRITICAL` per UTC day from `streak ≥ 14`; no duplicate within a period key, including across a
   process restart; a fresh input clears the streak with one `INFO` `..._CLEARED` and fully re-arms
   the ladder. Proven by the day-N-repeat test, the restart test and the clear-then-refire test in §7
   step 1, and observed on the live record — which is **already past the trigger**, so the ladder's
   behaviour is verifiable on day one rather than hypothetically.
7. RED→GREEN output for every test in §7 step 1 is the change artefact.
8. The step-0 evidence doc exists and states the L-1 verdict with its Nautilus citations, and the
   measured `|unexplained|` distribution backing D4's tolerance.
9. **(R2)** The §6 D4 worked example exists in the plan AND as the fixture behind
   `test_the_worked_open_then_settle_example_reconciles_to_zero_on_both_days`, with the three cash
   terms' scoping stated in the module docstring. Evidence: the test and the docstring.

10. **(R3) The settlement-date proxy is named, tested and measured.** `proceeds(D)` is dated by
   `scored_at_ns`'s UTC day, proven by `test_proceeds_are_dated_by_scored_at_ns_not_by_climate_day`;
   every emitted row carries `proceeds_date_proxy` and `settlement_lag_days`; a day whose breach is
   entirely attributable to proxy lag is classified `UNEXPLAINED_PROXY_LAG` and never netted away,
   proven by `test_a_breach_explained_entirely_by_proxy_lag_is_classified_not_netted`; and the step
   0(f) measured `settlement_lag_days` distribution is in the evidence pack. **An implementer cannot
   satisfy this criterion while silently substituting `climate_day`.**
11. **(R3) The re-alert ladder exists exactly once in the codebase.** `src/breezy/runtime/alert_ladder.py`
   is the only implementation of the period-key/streak state machine; `tests/unit/test_alert_ladder.py`
   is the only place its semantics are asserted; AUD-07's control imports it rather than re-implementing
   it; and `test_the_alert_ladder_module_imports_nothing_from_the_exit_window_study` plus `lint-imports`
   prove the dependency is acyclic. Evidence: the module diff, the shared test module's green output,
   and an import graph showing one definition and two consumers.

12. **(R5) The cumulative invariant carries a settled-through cutoff, and the tail is provisional
   rather than invisible.** The report prints
   `SETTLED_THROUGH = D_now − max(7, observed lag statistic)`, derived from step 0(f)'s measured
   distribution and never a literal, with the statistic selected by the §6 D4 minimum-sample rule
   (`max(...)` below `MIN_LAG_SAMPLE_N = 20`, `p99` at or above it, the bare floor `7` on an empty
   sample) and the header stating `settled_through_statistic=<max|p99> lag_sample_n=<n>`, proven by
   `test_a_small_lag_sample_uses_max_not_p99_and_says_so_in_the_header`; the cumulative `Σ_D unexplained` pass/fail
   determination covers only `D ≤ SETTLED_THROUGH`; days after the cutoff are printed, classified,
   labelled `PROVISIONAL_IN_FLIGHT`, excluded from that determination, and their own
   `Σ unexplained` is printed beside it as an explicitly non-gating figure. Proven by
   `test_an_in_flight_settlement_inside_the_settled_through_window_does_not_fail_the_cumulative_check`,
   whose anti-suppression half asserts the same breach at `D ≤ SETTLED_THROUGH` still FAILS.
   **This criterion narrows nothing:** per-day tolerance, per-day breach emission and the
   `UNEXPLAINED_PROXY_LAG` class are unchanged on both sides of the cutoff.

13. **(R6) A position that opens and never settles is detected by an independent check, not by the
   cash identity.** The report computes, every run, the §6 D9 left-anti-join of `FilledTrial` on
   `ScoredTrial` by `trial_id`, and flags every row past
   `MAX_SETTLEMENT_HORIZON_NS = scheduled_release_at_ns + _SEVEN_DAYS_NS + SETTLEMENT_HORIZON_GRACE_NS`
   (`SETTLEMENT_HORIZON_GRACE_DAYS = 3`) as `PERMANENTLY_UNSETTLED`, with `days_past_horizon`. Required
   behaviour, all four parts checkable: the flagged position's capital stays in the denominator and in
   its partition bucket (never silently excluded); the JSON carries
   `roi_status: "GATED_UNSETTLED_CAPITAL"` and `unsettled_capital_positions` and the D7 reader raises
   `UnsettledCapitalRoiError` on any ROI field while gated; a
   `PORTFOLIO_ROI_POSITION_PERMANENTLY_UNSETTLED` alert is delivered through the shipped sink with no
   currency-denominated field; and the check runs independently of — and is never suppressed by — a
   GREEN cumulative reconciliation. Proven by
   `test_a_position_that_opens_and_never_settles_is_flagged_not_silently_reconciled`, whose first
   assertion is that the cash identity itself still reads `unexplained(D1) == 0`, and whose negative
   half forbids flagging a position still inside its horizon. Evidence: the RED→GREEN output plus the
   step-0(g) measured count of unsettled trials on the live record.

## 9. Validation: failure cases, integration, autonomous operation

- **Ledger absent/unreadable** → `None`, never `0`; exit 1 with a named reason. A zero ROI printed
  from an unreadable store is the exact failure class L-38 names.
- **Scored store empty but the ledger has fills** → every fill is `unreconciled`; the report says so
  loudly rather than reporting ROI over an empty numerator.
- **Inputs present but frozen** → D8's re-alert ladder (§6): `WARN` weekly, escalating to a daily
  `CRITICAL` at `streak ≥ 14`. Round 1 insisted this failure class be closed rather than named; round
  2 established that a once-per-streak latch closes it only for the first three days. **The failure
  case this now covers: a genuinely dead pipeline, indistinguishable at the outset from the expected
  quiet state, still pages on day 30** — it does not rely on one WARN from weeks earlier having been
  seen. The residual limitation, stated honestly: every ladder rung depends on the timer firing at
  all; a stopped timer is still caught only by systemd unit state.
- **Balance line absent for a day** (node never booted, or log rotated) → that day's point is
  `UNKNOWN`; no interpolation, no carry-forward. Consecutive-day deltas skip across UNKNOWN and are
  labelled as multi-day deltas. A line present but unparseable is counted and reported, never
  silently dropped.
- **Two families, overlapping prefixes** (see AUD-05: `pm_us_crh_v4` and `pm_us_crh_cont` share
  `trial_id_prefix`) → attribution column is `AMBIGUOUS_FAMILY`, never a guess. Portfolio totals are
  unaffected because they are family-agnostic; this is precisely why D3 does not filter by prefix.
- **A YES and a NO leg on one station-day** → two instruments, two capital-deployed entries, the leg
  sign applied before any reconciliation against a venue-side netted view. Guarded by the §7 step-1
  two-leg test.
- **Fee unreconciled** → the fill's P&L is labelled `fee_modelled`, and the report prints a second
  total with those fills excluded, so the reader can see the fee exposure of the headline.
- **A position opens and never settles** → invisible to the cash identity by construction
  (`unexplained(D) = 0` on the open day and forever after, at any `SETTLED_THROUGH`), so it is caught
  by the independent D9 staleness check instead: flagged `PERMANENTLY_UNSETTLED` past
  `MAX_SETTLEMENT_HORIZON_NS`, its capital left in the denominator, the ROI figure gated for every
  consumer through the D7 reader, and an alert delivered. The identity's blindness here is stated in
  the artefact rather than implied, so a GREEN cumulative line is never read as "no capital is stuck".
- **A downstream consumer reads a changed shape** → refused by the D7 version check rather than
  silently mis-parsed.
- **Autonomous:** `Persistent=true` recovers a missed run; no `Restart=` (a missed day is subsumed
  by tomorrow's run over the same growing store); a failed run is `failed` in systemd and, since
  alert egress shipped (`f97c26f`), reaches the operator as a dimensionless CRITICAL.

## 10. Deployment, observability, rollback

- **Deploy:** commit unit files, `systemctl --user daemon-reload`, `enable --now` the timer. No node
  restart, no strategy change, so **no trading behaviour changes at all**.
- **Observability:** one dimensionless summary line per run to the journal; the numbers in the
  PRIVATE artefact; failures visible as a systemd `failed` unit and an alert; staleness visible as
  `PORTFOLIO_ROI_INPUTS_FROZEN`.
- **Rollback:** `systemctl --user disable --now breezy-portfolio-roi.timer` and revert the commit.
  Nothing else consumes the output *except through the D7 reader*, which refuses absent/unknown
  input, so rollback is total and fail-closed.

## 11. Relationship to portfolio-level ROI and how it is evaluated

This item **is** the portfolio-ROI measurement — it is the evaluation path every other item in this
backlog is evaluated *through*, so its alignment obligation is to define that path concretely rather
than to move a number itself.

**The evaluation path, stated as a contract other items cite by field name.** The versioned JSON
(D7) exposes exactly these portfolio-level fields, and they are the only sanctioned ROI surface:

| Field | Meaning | Used as the evaluation channel by |
|---|---|---|
| `realised_pnl_after_fees_total` | numerator | AUD-06b, AUD-07 |
| `capital_deployed_total` | denominator (leg-summed, never netted) | AUD-06b |
| `roi` , `roi_minus_b0` , `roi_minus_b1` | headline + both registered baselines | all |
| `n_fills`, `power_caveat` | the honesty gate on reading any of the above | all |
| `period_start`, `period_end` | matched-period comparison | AUD-06b (before/after sizing) |
| `unexplained_flow_days` | the integrity precondition | all |
| `settled_through`, `settled_through_statistic`, `lag_sample_n` | which days the cumulative check gates, and on what statistic over how many observations | all |
| `roi_status`, `unsettled_capital_positions` | the fail-closed gate on every ROI field above when capital is stuck in a never-settled position (§6 D9) | AUD-06b, AUD-07 |

**Baseline.** B0 (cash on the same deployed capital) is the explicit, registered baseline; B1
(fee-drag null) is the registered diagnostic. Both are fixed *before* any number is read, so no
item can select its own comparator after the fact.

**Plausible vs demonstrated.** This item demonstrates *nothing* about ROI; it makes ROI
**observable**. Its own benefit is therefore **demonstrated-on-delivery and binary**: either an
operator can answer "what did the account earn, on what capital, over what period, against what
baseline, and what is unaccounted for" from one artefact without running anything, or they cannot.
A negative ROI honestly measured is a complete success of this item.

**Falsifier.** If the report can be produced while the partition assertion is bypassed, or while a
day's unexplained flow is silently netted into the headline, the item has failed even if a number
appears.

**Dependency ordering.** Stage 1, no prerequisites. It must land before AUD-06b's evaluation (not
its build) and it carries a standing bilateral reconciliation with AUD-07 (§8 AC#4).

## 12. Assumptions, unresolved questions, blockers

- **UNVERIFIED (step 0 retires it):** that live Nautilus `Position`s never close, and therefore that
  `PortfolioAnalyzer`'s realised-P&L series is empty on live. The design reuses the analyzer if it
  turns out to be populated.
- **UNVERIFIED, carried not asserted (T-4 §4):** whether the venue's `currentBalance` includes
  position value. The report therefore labels I4 `venue currentBalance (cash or cash+positions —
  UNVERIFIED)` and must **not** call it equity. This bounds what "balance series" means and is
  stated in the artefact itself.
- **Assumption:** the daily relaunch gives one balance point per day. Step 0(c) measures it; if the
  series has holes, the report reports holes — it does not motivate a new balance poll here (T-4
  §D4 defers that deliberately).
- **Build decision, recorded not escalated:** B0 is the headline, B1 the diagnostic. Round 1 flagged
  this as unilateral; the disposition is to keep the decision (it is descriptive, not a PREREG
  endpoint, so it needs no ruling) and to remove the risk it carries by **printing both with equal
  prominence** and registering the choice in the artefact header. If a strategy-lead later prefers
  B1 as headline, no code changes — only the header label.
- **Assumption, measured at step 0(g) rather than asserted:** that `SETTLEMENT_HORIZON_GRACE_DAYS = 3`
  on top of the structural `_SEVEN_DAYS_NS` bound is wide enough that no legitimately-settling trial is
  ever flagged `PERMANENTLY_UNSETTLED`. The margin is derived from the scorer's nightly cadence, not
  from the data; step 0(g) checks it against the live record, and a longer observed settlement revises
  the constant through a recorded evidence update rather than a silent edit. The failure direction is
  benign and visible either way: too narrow produces a named, investigable false flag, never a silent
  exclusion of capital.
- **Blockers: none.** No operator ruling is required: no operator-reserved value is read or
  assigned, no enablement is touched, and the baselines are descriptive, not PREREG endpoints.
- **Named risk:** an operator reading a P&L figure as a verdict on a family. Mitigated by the
  artefact stating in its header that portfolio ROI and the registered sequential statistic are
  different estimands, that neither substitutes for the other, and by the n-power caveat line.

## 13. Review history

**Baseline self-score (2026-09-21, author), 78/100** — see the criterion table in the Revision 2
self-score below for the carried-forward weaknesses.

### Round 1 (2026-09-21) — independent blind peer review

| Reviewer | Total |
|---|---|
| mle-reviewer (statistical validation / measurement engineering) | 74/100 |
| prediction-market-reviewer (portfolio accounting / risk) | 78/100 |

**Dispositions:**

| # | Reviewer | Defect | Disposition |
|---|---|---|---|
| 1 | mle | MATERIAL — no versioned output schema for the JSON sibling | **ACCEPTED.** §6 D7 adds `schema_version: 1`, an additive-only policy, a single sanctioned reader that REFUSES unknown versions, and two tests (§7 step 1). **Premise partially corrected:** the reviewer's "no in-repo precedent" holds only for `scripts/analysis/`; `station_observation.py:110,126,213,234,248` and `trial_day_latch.py:1221` already carry the idiom and are now cited as the pattern to copy. |
| 2 | mle | MATERIAL — no staleness detector for "inputs present but frozen" | **ACCEPTED.** §6 D8 adds `PORTFOLIO_ROI_INPUTS_FROZEN` (3-consecutive-run streak, latched once per streak) through the shipped sink `health.py:495 resolve_alert_sink`, deliberately mirroring AUD-07's `EXIT_CORPUS_FROZEN`; two tests added; §9 and §8 AC#6 carry it. Honest limitation stated: today's frozen state is expected, so the detector's first job is legibility. |
| 3 | mle + pm | $0.05 unexplained-flow tolerance asserted without basis | **ACCEPTED, and re-derived rather than measured-then-frozen.** §6 D4 replaces the literal with `n_fills_that_day × $0.01`, derived from the only rounding in the pipeline (the shared venue-cent `ROUND_UP` at `operator_controls.py:213-215`, confirmed by the pm reviewer). Step 0(e) checks the derivation against the observed record; a test forbids re-introducing a literal. |
| 4 | mle + pm | balance-line parser regex/anchor unspecified | **ACCEPTED.** §7 step 2 pins the anchor (`AccountState(` token), a named-group regex in the module, a fixture taken verbatim from the real line captured at step 0(c), and fail-closed `UNKNOWN` (no fallback regex) with a count of unparsed lines reported. |
| 5 | pm | MINOR — no YES+NO same-station-day capital-deployed test | **ACCEPTED.** §7 step 1 adds `test_a_no_leg_and_a_yes_leg_fill_on_one_station_day_are_both_counted_in_capital_deployed`, asserting the two legs are summed and the leg sign is applied before any reconciliation against the venue's netted view. §9 carries the case. Verified: `no_leg_instrument_id:277` / `leg_of:289` make the two legs distinct instruments, so correctness is by construction — the test is a regression floor, exactly as the reviewer argued. |
| 6 | pm | MINOR — n=6 power caveat implied, not stated | **ACCEPTED.** §7 step 3 pins the verbatim header line; §8 AC#3 requires it; a test asserts it. |
| 7 | pm (AUD-07 review, folded in) | AUD-04↔AUD-07 cross-check is one-shot | **ACCEPTED.** §8 AC#4 is now a STANDING obligation executed by the report on every date both artefacts exist, through the D7 reader, with `EXIT_PNL_RECONCILIATION_MISMATCH` on persistent divergence. AUD-07 carries the mirror. |
| 8 | both | AC#2's expected fill count rests on an agent-reported (A) figure | **ACCEPTED (own carried weakness, now closed).** §8 AC#2 is restated so the criterion is the partition plus a recorded measurement; a divergence from 6 corrects the audit rather than the report. |
| 9 | both | "Portfolio objective alignment" 5/10 — baseline choice unilateral | **ACCEPTED in cause, REJECTED in remedy-as-escalation.** The cause was that §11 asserted a relationship instead of defining the evaluation path. §11 is rewritten as a field-level evaluation contract (named JSON fields, registered baselines, plausible-vs-demonstrated separation, falsifier, dependency stage). The baseline decision itself is **kept, not escalated**: it is descriptive and not a PREREG endpoint, so it needs no ruling; the risk it carried is removed by printing B0 and B1 with equal prominence and registering the choice in the header (§12). |

**Rejections:** none outright. One premise corrected (#1) and one remedy re-scoped (#9).

**Revision 2 self-score (2026-09-21, author), 88/100:**

| Criterion | Max | Score | Named remaining weakness |
|---|---|---|---|
| Fidelity to the gap and completeness | 20 | 18 | Every element of G-03 covered. Still loses points because "equity curve" is delivered as a *balance* series with UNVERIFIED semantics rather than a true equity curve — honest, but not what the gap literally asks for. |
| Technical correctness and evidence grounding | 20 | 17 | Nautilus citations independently confirmed by both reviewers; the tolerance is now derived from an inspected shared rounding function rather than asserted. Still loses points because the central null-hypothesis claim (positions never close on live) remains UNVERIFIED and is deferred to step 0; the design's shape changes if step 0 falsifies it. |
| Implementation specificity and feasibility | 15 | 13 | Files, seams, timer tick, lock discipline, parser anchor, schema policy and reader all named. Loses points because the scored-trial/residual loaders are named by reuse rather than by signature, so the implementer still reads `family_tally_v2.py` to wire them. |
| Acceptance criteria and validation quality | 20 | 18 | Criteria measurable; the cross-check is now standing and machine-executed; AC#2 no longer rests on an (A) premise. Loses points because AC#1 and AC#6 need three calendar days, so the item cannot be accepted same-day. |
| Autonomous operation, failure handling, recovery | 15 | 14 | Fail-closed on every input, frozen-input detection latched through a delivering sink, systemd-native recovery. Loses a point because the frozen detector cannot distinguish "pipeline dead" from "account legitimately quiet" — it reports the fact and leaves the interpretation to the operator, which is honest but not a diagnosis. |
| Portfolio objective alignment, scope, dependencies | 10 | 8 | §11 is now a field-level evaluation contract with registered baselines, an explicit falsifier and a stated dependency stage; this item is the substrate the rest of the backlog is evaluated through. Loses points because the ROI it measures is currently over a 6-fill record with no trading since 2026-09-15, so the contract is well-formed but exercised on an almost-empty sample. |

### Round 2 (2026-09-21) — independent blind peer review

| Reviewer | Total |
|---|---|
| prediction-market-reviewer (portfolio accounting / risk) | 95/100 |
| mle-reviewer (statistical validation / measurement engineering) | 82/100 |

**Round-2 readiness is the LOWER of the two: 82/100.**

**Dispositions (every defect, both reviewers):**

| # | Reviewer | Severity | Defect | Disposition |
|---|---|---|---|---|
| 1 | mle | MATERIAL | D8's `PORTFOLIO_ROI_INPUTS_FROZEN` fires once per streak and then goes permanently silent for the life of an ongoing outage, because re-arming needs a new input a dead pipeline will never produce | **ACCEPTED in full.** The reviewer is right that re-arming is unreachable during the failure the control exists to catch, and that the live record is already past the trigger. §6 D8 now specifies a **re-alert ladder**: `WARN` once per UTC ISO week at `3 ≤ streak ≤ 13`, escalating to `CRITICAL` once per UTC day at `streak ≥ 14` — the daily cadence deliberately matching AUD-05 §6 D-F's `(family_id, UTC day)` pattern, so the three frozen-state controls in this backlog share one specification. Latch state (`streak`, `first_frozen_utc_day`, `last_alert_severity`, `last_alert_period_key`) is persisted in `derived/portfolio_roi/.input_freshness.json` and **survives restarts** (a period key already alerted at never re-pages); a missing/corrupt latch fails loud, not silent. Clear condition and full re-arm specified, with one `INFO` `..._CLEARED`. Escalation is one-way within a streak. Sink re-verified against source: `emit_alert` `health.py:668`, `resolve_alert_sink` `:579`, `AlertPayload` `:351` with the four allowed keys enumerated at `:104`. AUD-07 carries the identical ladder by reference. |
| 2 | mle | MINOR | AC #6 states the single-shot behaviour as an acceptance criterion, locking the defect in as intended | **ACCEPTED.** AC #6 is rewritten to the ladder: per-ISO-week `WARN`, per-UTC-day `CRITICAL`, no duplicate within a period key including across restart, clear-then-full-re-arm. It explicitly notes the live record is already past the trigger, so the behaviour is verifiable on day one. §9's "inputs present but frozen" entry is rewritten to match, naming the day-30 dead-pipeline case and the residual limitation (a stopped timer is still only caught by systemd state). |
| 3 | mle | MINOR (carried from R1) | Loaders named by module reuse, not by signature | **ACCEPTED, and closed with verified signatures.** §7 step 2 now names all four, read from source: `scored_trial_store.read_scored_trials(directory: Path) -> tuple[ScoredTrial, ...]` (`:118`); `persistence.residual_fills.residual_trial_ids(store_dir: Path) -> frozenset[str]` (`:234`); `persistence.realized_draws.admissible_scored_trials(rows, *, residual_trial_ids) -> tuple[ScoredTrial, ...]` (`:187-189`); `DurableFillRecord` (`adapters/polymarket_us/exec/client.py:641`) under `FILL_KEY_PREFIX` (`:384`). **Additional finding while verifying:** `family_tally_v2.residual_trial_ids` (`:868`) is only a delegating wrapper whose own docstring says "this tally must never carry a second residual predicate" — so the report imports the `src/` definition directly, which also keeps the `src/` never-imports-`scripts/` layer contract intact. |
| 4 | pm | MINOR | D4's unexplained-flow identity has no worked example and its four terms risk double-counting the settlement payout unless the scoping is stated | **ACCEPTED — and the reviewer's suspected defect is confirmed real, not merely a documentation gap.** Substituting `realised_pnl = proceeds − cost − fee` into the round-1 four-term form yields `Δbalance − 2·proceeds + (cost+fee)_settled + (cost+fee)_opened`: the payout genuinely double-subtracts. §6 D4 therefore **replaces the identity with the pure cash form** `unexplained(D) = Δbalance(D) − proceeds(D) + capital_deployed(D)`, in which realised P&L is not a term at all but a derived quantity booked once on the settlement date. The three terms' scoping is stated explicitly (each ledger row contributes to `capital_deployed` on exactly one date and `proceeds` on exactly one date; the terms are disjoint by construction), and a **worked two-day table** (buy `$0.43` on D1, settle `$1.00` on D5) shows `unexplained == 0` on both days, `Σ Δbalance = +0.57 = Σ realised P&L`, plus the losing-settlement case. Three new tests in §7 step 1 and new AC #9 carry it. |
| 5 | pm | MINOR | Loader signatures (same as #3) | **ACCEPTED** — closed by the same change as #3. |
| 6 | pm | line drift | `_round_cost_up_to_cent` cited `:213-215`, the `def` is at `:220` | **ACCEPTED, verified, corrected** to `:220-244` in §6 D4, with the drift noted. |
| 7 | pm | (implied by AUD-07's mirror finding) | "Overlapping positions" in the AUD-04↔AUD-07 reconciliation is undefined | **ACCEPTED pre-emptively, resolved identically on both sides.** AC #4 now defines overlap as the **inner join on `trial_id`** (the one key both artefacts carry), and states that until any exit fires "hold" and "actual" are definitionally the same outcome — `exit_gate.py:55 _EXIT_RULE_REGISTERED_FAMILIES` is `frozenset({"pm_us_crh_exit_v4"})`, which is not the live family — so the reconciliation must match **to the cent on every joined row today**, and a partial mismatch is an alarm rather than expected slack. |
| 8 | mle | scoring note | Portfolio alignment 8/10 attributed to the criterion's structure ("this item is the measurement substrate, not a source of ROI itself"), with **no named defect** | **RECORDED, no change made — round 3 must justify or award.** The prediction-market reviewer scored the same §11, unchanged, at **10/10**, stating the zero-contribution answer "is the correct answer for this item's charter, not a shortfall", and the mle record itself says "No further defect found here". A deduction with no named defect and no requested change is not actionable. If round 3 deducts here it must name a concrete gap; otherwise the points should be awarded. |

**Rejections:** none. No scope was removed and no acceptance criterion softened — AC #4 and AC #6 were both tightened, and AC #9 added. No operator-reserved value is read, restated, defaulted or assigned anywhere in this revision; the baseline choice (B0 headline) remains a recorded build decision, not a PREREG endpoint.

**Revision 3 self-score (2026-09-21, author) — deliberately conservative, scored against the lower round-2 total:**

| Criterion | Max | Score | Named remaining weakness |
|---|---|---|---|
| Fidelity to the gap and completeness | 20 | 18 | G-03 fully covered. Unchanged weakness, self-conceded and not papered over: the balance series is a log-derived proxy, not a true mark-to-market equity curve, so the artefact measures realised flows rather than portfolio value. |
| Technical correctness and evidence grounding | 20 | 17 | The D4 double-count is now corrected rather than merely documented, with the substitution that proves it; all four loaders and the alert API re-verified against source with line numbers; `_round_cost_up_to_cent` re-anchored. Does not claim more: the step-0 null hypothesis about closed positions is still UNVERIFIED by design, and the worked example is arithmetic on a designed fixture, not a replay of the live record. |
| Implementation specificity and feasibility | 15 | 13 | Loader signatures, parser anchor, schema policy, latch file shape and the ladder's period keys are all pinned. Loses points because the ledger's settlement-date field has not been named from source — step 0 must establish how a settlement date is read from `DurableFillRecord`, and the D4 identity depends on it. |
| Acceptance criteria and validation quality | 20 | 17 | AC #4 now has a defined join key and a stated exactness expectation; AC #6 tests the ladder rather than asserting the defect; AC #9 requires the worked example to exist as a fixture. Loses points because AC #1 still needs three calendar days, and the AUD-07 cross-check cannot be exercised until that item ships. |
| Autonomous operation, failure handling, recovery | 15 | 12 | The ladder closes the round-2 MATERIAL gap with a persisted, restart-surviving latch, an escalation rung and an observable clear. Held well below full marks: every rung still depends on the timer firing, and the detector still cannot distinguish "pipeline dead" from "account legitimately quiet" — it escalates the fact, it does not diagnose it. |
| Portfolio objective alignment, scope, dependencies | 10 | 8 | §11 is a field-level evaluation contract with registered baselines, a falsifier and a stated dependency stage. Held at the lower reviewer's mark pending round 3 naming a defect or awarding the points (disposition #8); the contract is exercised on a 6-fill record either way. |

### Round 3 (2026-09-21) — independent blind peer review

| Reviewer | Total |
|---|---|
| prediction-market-reviewer (portfolio accounting / risk) | 93/100 |
| mle-reviewer (statistical validation / measurement engineering) | 86/100 |

**Round-3 readiness is the LOWER of the two: 86/100.**

**Dispositions (every defect, both reviewers):**

| # | Reviewer | Severity | Defect | Disposition |
|---|---|---|---|---|
| 1 | pm | MINOR | D4's `proceeds(D)` is scoped by a "settlement date" that no persisted record carries; neither `DurableFillRecord` nor `ScoredTrial` has a venue settlement/credit timestamp, so an implementer must pick a field the plan never names | **ACCEPTED in full, verified from source before writing, and answered with more than the reviewer asked for.** Read directly: `ScoredTrial` (`settlement/trial_scorer.py:131-151`) carries `climate_day`, `scored_at_ns`, `settlement_basis` and no settlement timestamp; `scored_at_ns` is assigned `now_ns` at `:219`; `DurableFillRecord` (`exec/client.py:641`) carries only the fill time. §6 D4 now **names `scored_at_ns`'s UTC calendar day** as the operational definition, states BOTH components of the error it introduces — the nightly-cadence lag for `settlement_basis == "nws_final"`, and the **structural ≥7-day lag** for `"venue_last_fair_price_fallback"`, which `_resolve_settlement_basis` only admits once `now_ns >= scheduled_release_at_ns + _SEVEN_DAYS_NS` (`trial_scorer.py:243`) — and specifies how the identity handles it: the **cumulative** `Σ_D unexplained` is the authoritative detector (a proxy misdating produces equal-and-opposite per-day breaches that cancel), while each breaching day is **flagged**, not absorbed, via `proceeds_date_proxy`, a `settlement_lag_days` column and a distinct `UNEXPLAINED_PROXY_LAG` class. Step 0(f) measures the real lag distribution before the tolerance is trusted. |
| 2 | pm | required change 2 | Add an AC/test asserting the settlement-date field used matches the one documented | **ACCEPTED.** New AC #10 plus two new step-1 RED tests (`test_proceeds_are_dated_by_scored_at_ns_not_by_climate_day`, `test_a_breach_explained_entirely_by_proxy_lag_is_classified_not_netted`). AC #10 states explicitly that an implementer cannot satisfy it while substituting `climate_day`. |
| 3 | mle (joint with AUD-07's record) | MINOR | The re-alert ladder is specified once but implemented twice, in two modules with two latch files, with no shared code and no cross-test preventing divergence | **ACCEPTED, and closed by shared code rather than by a cross-test.** §6 D8 now assigns **ownership to AUD-04**: this item ships `src/breezy/runtime/alert_ladder.py` (one pure `evaluate_streak` plus the UTC-ISO-week / UTC-day period keys and the latch read/write) and one shared `tests/unit/test_alert_ladder.py`; **AUD-07 depends on it by id and imports it**, referencing the shared test module rather than restating its cases. Each consumer keeps its own latch FILE and event names. **No cycle:** the code dependency is AUD-07 → AUD-04 only; AUD-04's obligation to AUD-07 is a data read of a published artefact at report time, not an import — asserted by `test_the_alert_ladder_module_imports_nothing_from_the_exit_window_study` and `lint-imports`. A ship-order contingency is stated for the case where AUD-07 lands first. New AC #11 requires one definition and two consumers, proven by import graph. |
| 4 | mle | required change 2 (carried) | Name the ledger's settlement-date field from source at step 0 | **ACCEPTED — this is the same defect as #1 and is closed by it**, with the step-0 measurement added as 0(f). |
| 5 | both | verification | The D4 cash identity, the worked two-day example, the ladder's period-key/restart/clear semantics, the four loader signatures, `_round_cost_up_to_cent` at `:220-244` and the leg-sum correctness were all independently re-verified this round and hold | **NOTED, no change.** |
| 6 | both | scoring note | §11 awarded 10/10 by both reviewers with no named defect, resolving round-2 disposition #8 | **RESOLVED and awarded** — the revision-4 self-score raises this criterion from 8/10 to 10/10. |

**Rejections:** none. **No scope was removed and no criterion softened:** the proxy is disclosed and classified rather than the tolerance being widened to hide it, and the ladder duplication is closed by shared code rather than by downgrading the "cannot drift apart" claim. No operator-reserved value is read or assigned anywhere in this revision.

**Points withheld in round 3 without a named defect or requested change — round 4 must justify or award:**

- **mle, "Fidelity" 18/20, "Technical correctness" 17/20, "Acceptance criteria" 17/20, "Autonomous operation" 12/15.** All four are recorded verbatim as "matches round 2" with no defect named in the revised text and no change requested; the record's own "required changes" list contains only items #3 and #4 above, both now closed.
- **pm, "Fidelity" 19/20.** The −1 is attributed to "equity curve delivered as a balance-log proxy", which the same record calls "a transparent scope statement" and does not ask to be changed.

**Revision 4 self-score (2026-09-21, author) — deliberately conservative, scored against the lower round-3 total (86):**

| Criterion | Max | Score | Named remaining weakness |
|---|---|---|---|
| Fidelity to the gap and completeness | 20 | 18 | Every element of G-03 is covered and the settlement-date scoping the identity depends on is now named from source rather than left open. Loses points because "equity curve" is still delivered as a balance-log proxy, which is a scope statement rather than the literal ask. |
| Technical correctness and evidence grounding | 20 | 18 | The cash identity is verified by substitution, all four loaders and the alert API hold line-for-line, and the `proceeds(D)` proxy is now named, its two error components derived from `trial_scorer.py:219`/`:243`, and its handling specified. Loses points because the proxy's real magnitude is a step-0 measurement, not yet a measured fact at plan time. |
| Implementation specificity and feasibility | 15 | 13 | Files, timer tick, lock discipline, parser anchor, schema policy and loader signatures were already pinned; the ladder is now one named module with one owner and one test suite, and the proxy field is named. Loses points because the ladder extraction adds a new module AUD-07 must sequence against, and a ship-order contingency (rather than a hard order) is stated. |
| Acceptance criteria and validation quality | 20 | 18 | AC #10 makes the proxy field itself testable and AC #11 makes "one ladder, two consumers" machine-checkable by import graph. Loses points because AC #1 still needs three calendar days and AC #4's cross-check cannot be exercised until AUD-07 ships. |
| Autonomous operation, failure handling, recovery | 15 | 14 | The ladder's persisted, restart-surviving latch, one-way escalation and observable clear are now single-sourced, so the two mirrored controls cannot drift. Loses a point because every rung still depends on the timer firing, and the detector escalates the fact of a freeze without diagnosing it. |
| Portfolio objective alignment, scope, dependencies | 10 | 10 | §11 is a field-level evaluation contract with two registered baselines fixed before any number is read, an explicit falsifier and a stated dependency stage; both round-3 reviewers awarded 10/10 with no named defect. |

**Latest score:** 91/100 (Revision 4 self-score); round-3 peer readiness 86/100.
**Readiness: NOT READY — round 4 peer review pending.**

### Round 4 (reconciled) (2026-09-21) — independent blind peer review, with scoring reconciliation

| Reviewer | Total |
|---|---|
| prediction-market-reviewer (portfolio accounting / risk) | 100/100 |
| mle-reviewer (statistical validation / measurement engineering) | 98/100 |

**Round-4 readiness is the LOWER of the two: 98/100.** Both records ran a reconciliation pass in
which every withheld point was either tied to a named, text-fixable defect or awarded back with its
external cause recorded as a note/blocker.

**Dispositions (every defect and every note, both reviewers):**

| # | Reviewer | Severity | Defect | Disposition |
|---|---|---|---|---|
| 1 | mle | MINOR (−1 Technical correctness, −1 Acceptance criteria) | §6 D4's cumulative `Σ_D unexplained` invariant has no stated **settled-through cutoff**, so a live, continuously-updated report can show a transient nonzero cumulative value near "today" purely from in-flight settlement lag — up to the structural ≥7-day fallback the plan itself derives — indistinguishable in the plan's own text from a genuine reconciliation failure. The algebraic cancellation D4 relies on holds only once BOTH the credit day and the scoring day fall inside the measured window; no AC would catch an implementer shipping the cumulative check without a cutoff | **ACCEPTED in full; the only change of this revision.** Verified against source before writing: `ScoredTrial.scored_at_ns` is assigned `now_ns` at `src/breezy/settlement/trial_scorer.py:219`, and `_resolve_settlement_basis` admits `"venue_last_fair_price_fallback"` only once `now_ns >= trial.scheduled_release_at_ns + _SEVEN_DAYS_NS` at `trial_scorer.py:243` — both read directly, both exactly as the reviewers quote them. Changes made: (a) §6 D4 gains a **settled-through cutoff** subsection defining `SETTLED_THROUGH = D_now − max(7, observed p99 settlement_lag_days)` — the p99 read from step 0(f)'s measured distribution, never a literal; the `7` floor is the structural fallback lag, so the cutoff can only widen past it, never narrow inside it. The cumulative pass/fail determination applies only to `D ≤ SETTLED_THROUGH`; later days are still computed, printed and classified, are labelled `PROVISIONAL_IN_FLIGHT`, are excluded from that determination (so an in-flight settlement can never breach it, and equally can never declare it GREEN), and their own `Σ unexplained` is printed as a separate, explicitly non-gating figure so nothing is hidden and a real failure becomes gating the moment the cutoff advances. (b) §7 step 1 gains the RED test `test_an_in_flight_settlement_inside_the_settled_through_window_does_not_fail_the_cumulative_check` with an unscored-settlement fixture, including an **anti-suppression half** asserting the identical breach at `D ≤ SETTLED_THROUGH` still FAILS. (c) §8 gains **AC #12** requiring the cutoff, the labelling, the exclusion and the separate tail figure. **No scope removed and no criterion softened:** per-day tolerance, per-day breach emission and the `UNEXPLAINED_PROXY_LAG` class are explicitly unchanged on both sides of the cutoff, and the cutoff is bounded below by the structural 7-day figure so it cannot be tuned into a silencer. |
| 2 | mle | note (not a deduction) | A true mark-to-market equity curve is out of this item's scope: it requires a position-valuation history pipeline that does not exist in this repo (the only per-position mark tracking, `position_monitor.py`'s `_MonitoredPosition`, is scoped to the exit-decision seam, not a historical series) | **NOTED, no change; recorded as a forward BLOCKER/note rather than absorbed.** The reviewer awarded Fidelity in full on this basis. §11 already scopes the deliverable honestly as a balance-log **cash-flow** proxy, not an equity curve. Recommendation carried: a future backlog item for a position-valuation history pipeline. This plan does not claim to deliver one and must not be read as doing so. |
| 3 | mle | reconciled, awarded | Ladder-extraction sequencing against AUD-07; the step-0 null hypothesis being UNVERIFIED by design; every rung depending on the timer firing | **NOTED, no change.** Each was re-examined by the reviewer and awarded in full: the ladder dependency is acyclic, single-owner and test-enforced with a named ship-order fallback (a firm cross-item build order is a coordinator decision no plan text can impose); a RED-first plan may not assert an unmeasured empirical fact; and "a stopped systemd timer is only caught by systemd state" is a property shared by every scheduled unit in this backlog, named honestly in §9/§13 rather than hidden. |
| 4 | pm | none | No MATERIAL and no new defect found; round 3's central defect (the unnamed settlement-date field behind `proceeds(D)`) re-verified as genuinely fixed in the plan body against `trial_scorer.py:219`/`:243`, with AC #10 and two RED tests holding it | **NOTED, no change.** The balance-log-proxy scope statement is explicitly judged not a defect by this reviewer either. Both dependency conditions the record names (trading resuming for AC #1/#6's three-day window; AUD-07 importing the shared ladder) remain stated in the plan and are not resolvable by plan text. |

**Rejections:** none. Both records' findings are accepted in full; the single fixable defect is closed in the plan body, not in this table.

**Revision 5 self-score (2026-09-21, author) — deliberately conservative, scored against the lower round-4 total (98):**

| Criterion | Max | Score | Named remaining weakness |
|---|---|---|---|
| Fidelity to the gap and completeness | 20 | 19 | Every element of G-03 is covered; the settlement-date proxy and now its settled-through cutoff are both named from source. Holds a point back because "equity curve" is still delivered as a balance-log cash-flow proxy — a scope boundary both reviewers accept as honest, but still not the literal ask, and the position-valuation pipeline that would close it is an unfiled future item. |
| Technical correctness and evidence grounding | 20 | 19 | The cash identity verifies by substitution; the cumulative invariant is now stated with the cutoff that makes it true in the live operating mode, bounded below by the structural `_SEVEN_DAYS_NS` figure read at `trial_scorer.py:243` and anchored above on the step-0(f) measured p99. Holds a point back because that p99 is a measurement this revision schedules rather than reports, so the cutoff's operative width is still unmeasured at plan time. |
| Implementation specificity and feasibility | 15 | 14 | Files, timer tick, lock discipline, parser anchor, schema policy, loader signatures, the single-owner ladder module and now the cutoff formula and its provisional-tail rendering are pinned. Holds a point back because the ladder extraction still adds a module AUD-07 must sequence against with a contingency rather than a hard build order. |
| Acceptance criteria and validation quality | 20 | 19 | AC #12 plus its RED test close the one gap round 4 named, and the test's anti-suppression half stops the cutoff becoming a blanket exclusion. Holds a point back because AC #1 still needs three calendar days of live running and AC #4's cross-check cannot be exercised until AUD-07 ships. |
| Autonomous operation, failure handling, recovery | 15 | 14 | The ladder is persisted, restart-surviving, one-way-escalating and single-sourced; the provisional tail keeps an in-flight anomaly visible rather than silencing it. Holds a point back because every rung still depends on the timer firing at all, and the detector escalates the fact of a freeze without diagnosing it. |
| Portfolio objective alignment, scope, dependencies | 10 | 10 | §11 is a field-level evaluation contract with two registered baselines fixed before any number is read, an explicit falsifier and a stated dependency stage; awarded 10/10 with no named defect by both reviewers in rounds 3 and 4. |

**Latest score:** 95/100 (Revision 5 self-score); round-4 peer readiness 98/100.
**Readiness: NOT READY — round 5 delta review pending.** No blocker requires an operator or strategy-lead ruling for this item's own scope; the mark-to-market equity-curve note (disposition 2) is a recommended future item, not a gate on this one.

### Round 5 (delta) (2026-09-21) — independent blind peer review

| Reviewer | Total |
|---|---|
| mle-reviewer (statistical validation / measurement engineering) | 98/100 |
| prediction-market-reviewer (portfolio accounting / risk) | 88/100 |

**Round-5 readiness is the LOWER of the two: 88/100.** Both records independently re-verified the
round-4 settled-through cutoff, its `7` floor at `trial_scorer.py:243`, its `PROVISIONAL_IN_FLIGHT`
labelling and its anti-suppression test, and both confirmed the coordinator's specific question (can a
permanently unscored settlement hide in the provisional tail forever?) is answered NO by the cutoff's
self-cleaning property. Each then named one new defect the fix did not reach.

**Dispositions (every defect, both reviewers):**

| # | Reviewer | Severity | Defect | Disposition |
|---|---|---|---|---|
| 1 | pm | MATERIAL | The cash identity cannot detect a position that opens and never settles, **at any `SETTLED_THROUGH` cutoff, by construction**: `capital_deployed(D1)` cancels `Δbalance(D1)` on the open day, no settlement day ever arrives, so `unexplained(D1) = 0` is a clean PASS forever while capital sits in a position that never resolves. No companion staleness/aging mechanism existed anywhere in the plan | **ACCEPTED in full.** The substitution is re-derived and correct, and the gap is this item's to close (AUD-07 tracks corpus GROWTH, which a healthy corpus with one stuck position inside it never trips). Changes: (a) **new §6 D9** — an independent open-position staleness check, stated explicitly as a detector the cash identity *cannot* carry, with the driving records verified from source before writing: `FilledTrial` carries `trial_id`/`climate_day`/`filled_at_ns`/`scheduled_release_at_ns` (`trial_scorer.py:83,113,115,121,124`, the last stamped with the venue's real settlement instant by `score_live_trials.py:1161-1187`), `ScoredTrial` carries the matching `trial_id` (`trial_scorer.py:134`), so "filled but never settled" is a left-anti-join on `trial_id` with the in-repo never-scored precedent at `score_live_trials.py:1277-1284`; `DurableFillRecord` carries `ts_event` and no settlement timestamp (`exec/client.py:641-685,675`), which is why the horizon anchors on `scheduled_release_at_ns`; and `find_unresolved_takes` (`score_live_trials.py:1030-1158`) is the adjacent taken-but-never-FILLED census this must not duplicate. (b) The horizon is **named, not left to the implementer**: `MAX_SETTLEMENT_HORIZON_NS = scheduled_release_at_ns + _SEVEN_DAYS_NS + SETTLEMENT_HORIZON_GRACE_NS` with `SETTLEMENT_HORIZON_GRACE_DAYS = 3`, the `_SEVEN_DAYS_NS` term read verbatim at `trial_scorer.py:243` (past it, an unscored trial means NWS published no final AND the venue booked no reading — the stuck condition itself) and the 3-day margin derived from the scorer's nightly cadence, checked at new step 0(g) rather than trusted. (c) Behaviour when exceeded: flagged `PERMANENTLY_UNSETTLED`, **never excluded from any total**, ROI **fail-closed** via `roi_status: "GATED_UNSETTLED_CAPITAL"` and a D7-reader `UnsettledCapitalRoiError` on every ROI field (the run still exits 0, so AC #1 is unaffected), and a dimensionless alert through the shipped sink on the D8-owned shared ladder with its own latch file. (d) New RED test `test_a_position_that_opens_and_never_settles_is_flagged_not_silently_reconciled`, whose first assertion pins `unexplained(D1) == 0` as real rather than assuming it away, plus a negative half forbidding a flag inside the horizon. (e) **New AC #13**, plus §3(i), §5, §9 and §11 field-table entries. |
| 2 | mle | MINOR | `SETTLED_THROUGH`'s `observed p99 settlement_lag_days` has no minimum-sample rule; at `n≈6` a linear-interpolation p99 can fall BELOW the observed maximum and narrow the cutoff inside the worst lag actually seen | **ACCEPTED in full, with the reviewer's own named threshold.** §6 D4 gains a minimum-sample rule: `MIN_LAG_SAMPLE_N = 20`; below it the cutoff uses `max(observed settlement_lag_days)`, at or above it `p99`, and an empty sample falls back to the bare structural floor `7`. The threshold is stated as a sample-size rule explicitly NOT derived from this pipeline's data (tuning it on the sample being measured would be circular). **Conservative in one direction only:** `max() >= p99` and both branches remain floored by `7`, so the small-`n` branch can only widen the cutoff — the anti-suppression assertion is untouched. The header now carries `settled_through_statistic=<max|p99> lag_sample_n=<n>`; step 0(f) records `lag_sample_n`; new RED test `test_a_small_lag_sample_uses_max_not_p99_and_says_so_in_the_header` covers all three branches; AC #12 is amended to require the rule and the header line. |

**Rejections:** none. **No scope was removed and no criterion softened:** AC #12 was widened rather
than relaxed, AC #13 was added, the flagged position's capital is explicitly kept in the denominator
rather than excluded to make the identity look clean, and the ROI gate fails closed on the FIGURE
without weakening AC #1's exit-0 requirement. No operator-reserved value is read, restated, defaulted
or assigned in this revision; `SETTLEMENT_HORIZON_GRACE_DAYS` and `MIN_LAG_SAMPLE_N` are measurement
constants with stated bases, not caps.

**Revision 6 self-score (2026-09-21, author) — deliberately conservative, scored against the lower
round-5 total (88):**

| Criterion | Max | Score | Named remaining weakness |
|---|---|---|---|
| Fidelity to the gap and completeness | 20 | 19 | G-03's reconciliation charter now reaches the one class of unexplained capital it previously could not see — capital deployed into a position that never resolves. Holds a point back for the unchanged, self-conceded boundary: "equity curve" is still delivered as a balance-log cash-flow proxy, and the position-valuation pipeline that would close it is an unfiled future item. |
| Technical correctness and evidence grounding | 20 | 19 | The identity's blindness is derived by substitution and now stated as a limitation rather than left implicit; D9's driving records, their fields and the adjacent census it must not duplicate are all cited from source; the lag statistic no longer depends on an uncalibrated percentile. Holds a point back because both new quantities (`SETTLEMENT_HORIZON_GRACE_DAYS`, and which `MIN_LAG_SAMPLE_N` branch the live record takes) are step-0 measurements this revision schedules rather than reports. |
| Implementation specificity and feasibility | 15 | 14 | The horizon formula, the join key, the flag, the gated `roi_status`, the reader exception, the separate latch file and the three-branch statistic rule are all named, so no material design decision is left open. Holds a point back because the shared ladder module still adds a file AUD-07 must sequence against with a contingency rather than a hard build order. |
| Acceptance criteria and validation quality | 20 | 19 | AC #13 closes the round-5 MATERIAL with a test whose first assertion pins the identity's blindness rather than assuming it away, and whose negative half stops over-flagging; AC #12 now forbids a bare percentile call. Holds a point back because AC #1 still needs three calendar days of live running and AC #4's cross-check cannot be exercised until AUD-07 ships. |
| Autonomous operation, failure handling, recovery | 15 | 14 | Stuck capital is now detected, delivered and fail-closed on the ROI figure without stopping the run, and the check cannot be suppressed by a GREEN reconciliation. Holds a point back because every rung of both detectors still depends on the timer firing at all, and they escalate facts without diagnosing causes. |
| Portfolio objective alignment, scope, dependencies | 10 | 10 | §11's evaluation contract now exposes the settled-through and ROI-gate fields alongside the numerator/denominator, so no consumer can read a headline ROI over capital that may never return; baselines, falsifier and dependency stage are unchanged and were awarded 10/10 by both reviewers in rounds 3–5. |

**Latest score:** 95/100 (Revision 6 self-score); round-5 peer readiness 88/100.
**Readiness: NOT READY — round 6 delta review pending.** No blocker requires an operator or
strategy-lead ruling for this item's own scope; the mark-to-market equity-curve note (round-4
disposition 2) remains a recommended future item, not a gate on this one.

<!-- COORDINATOR FINAL STATUS — appended after review; everything above this line is the reviewed revision -->

## Coordinator final status (2026-09-21) — authoritative

This block supersedes any score or readiness wording in §13 above, which plan revisers wrote
before review closed.

- **Reviewed revision sha256** (file content above the marker line): `ec03e0c9f69ba8384fd15a6f5309581d050e9d11e1e05c7e7b03df1256c67a6e`
- **Baseline self-score:** 78/100
- **Final score (lowest reviewer, never averaged):** 100/100
  - `mle-reviewer` round 6: 100/100 — `reviews/AUD-04-r6-mle-reviewer.md`
  - `prediction-market-reviewer` round 6: 100/100 — `reviews/AUD-04-r6-prediction-market-reviewer.md`
- **Readiness:** **READY**
- **Unresolved blockers:**
  - None.
- **Full review history:** 12 records, `reviews/AUD-04-r*-*.md`
- Planning only. Nothing in this plan has been implemented.
