# M1v3-CONFIRM-readiness plan r3 (draft, 2026-10-09)

**Status:** DRAFT r3. It applies the round-2 merged amendments. Round-2 scores, all REVISE: security 91, python 92, architect 93, market-math 90. The target is READY ≥ 95 from each reviewer. r2 rulings stand unless changed here; §R3 maps every change.

**Plan of record:** `/home/jon/breezy/docs/evidence/DECISION_ROI_ROUTE_TO_TRADING_2026-10-09.md`, item 2.

**Governing rulings:**
- `/home/jon/breezy/docs/evidence/RULING_FQ-v2-NO-TRADE_2026-10-08.md`
- `/home/jon/breezy/docs/evidence/RULING_B3_permit_window_posture_2026-09-25.md`
- `/home/jon/breezy/docs/evidence/RULING_permit_daily_coverage_2026-09-25.md`
- the operator directive of 2026-09-29: prediction comes from US weather; venue prices are execution cost only
- the two operator caps, already in `operator.env` and never assigned here

**Hard rules for every work package and every brief:**
- Never open tape, settlement or truth for climate days **2026-10-07..2026-11-28** before the single read on or after 2026-12-07.
- Logs and evidence dated before 2026-10-07T00:00Z may be read for latency and fee fields only.
- Never edit `/home/jon/breezy/docs/evidence/m1v3/PREREG.json`.
- Nautilus Trader is immutable.
- `allow_short` stays False.
- No operator cap is assigned.
- Never weaken safety, contract or NO-SEND tests. Any guard whose shape changes is narrowed and security-reviewed.
- Briefs give the exact interpreter path and PYTHONPATH. Agents format only their own files. Never run `uv sync`. Use `--basetemp` under `~/.cache`.

## 0. Verified facts

**V1–V12 carry over from r2 unchanged.** In summary:
- V1: the frozen M1-v3 pins.
- V2: the M1V3-R1 conflict.
- V3: closed-set mirrors at:
  - `/home/jon/breezy/src/breezy/persistence/family_manifest.py:116-121`
  - `/home/jon/breezy/src/breezy/runtime/trade_supervisor_core.py:164`
  - `/home/jon/breezy/src/breezy/strategy/autonomy/node_plugins.py:13`
  - `/home/jon/breezy/src/breezy/analysis/autonomy/offline_plugins.py`
  - `/home/jon/breezy/src/breezy/persistence/autonomy/paths.py:28-29`
  - `/home/jon/breezy/src/breezy/strategy/current_rung_hold/family_id_arg.py:20`
  - `/home/jon/breezy/src/breezy/persistence/autonomy/pins.py:28` with `/home/jon/breezy/src/breezy/persistence/autonomy/resolver.py:462`
- V4: the live-orders allowlist.
- V5: the AST guard; `trade.py` is 1274 lines.
- V6: the permit gap: `trade_supervisor_core.py:37-39`, `:40`, `:139`, `:1082`, `:1188-1197`, `:1205`, `:1395-1404`.
- V7: consumers of the 16:50Z schedule.
- V8: the singleton submit intent at `/home/jon/breezy/src/breezy/runtime/submit_intent.py:386-422`.
- V9: the hard-coded floor MC constants.
- V10: the loss-stop producer is absent, and the guard is scoped to FQ.
- V11: the station set and connection sharding.
- V12: AUT-5 owns `trade.py`, `settings.py` and `trade_supervisor*.py`.

**Added in r3:**

| # | Fact | Evidence |
|---|---|---|
| V13 | **There is no node systemd unit.** The supervisor spawns `breezy-trade` with `start_new_session=True`, inside the supervisor unit's cgroup. `KillMode=process` and `KillSignal=SIGTERM` mean stopping the supervisor leaves the node running. Stopping the node is "the supervisor's STOP_PRIOR job or the operator's explicit SIGTERM — never systemd's cgroup sweep". STOP_PRIOR finds the node PID (the tracked PID, or `find_node_pid`, the PID-verified flock holder), calls `terminate_after_recheck`, then polls `intent_lock_free`. | `/home/jon/breezy/deploy/systemd/breezy-trade-supervisor.service:150-165`; `/home/jon/breezy/src/breezy/runtime/trade_supervisor.py:1230-1290` |
| V14 | `fq_loss_floor_mc_e2.py` calls `epoch_grid(freeze)` directly. | `/home/jon/breezy/scripts/analysis/fq_loss_floor_mc_e2.py:13,231` |
| V15 | `validate_ii.py` anchors registry pair semantics on `SCHEDULE_LAUNCH_UTC` (16:50) and the launch-window end: "a cancel stamped 16:49:59 and committed at 16:50:01 voids an ACTIVATEd pair". | `/home/jon/breezy/src/breezy/persistence/autonomy/validate_ii.py:146-149,378-386` |

The critical path is items 1–7 plus item 8, the permit window (WP-4). Moving the trade to D-1_18Z is prohibited (§A.3(a)).

## A. DRAFT ruling (item 1): `RULING_M1v3-CONFIRM-T2-SENDER_<ratification-date>`. Draft only; not in force.

**Ratification requires all four of:**
- (i) a WINNER read, as defined in A.1;
- (ii) the §B floor frozen, with its binding PASS committed **before the read is opened** (§C.9);
- (iii) the WP-4 B3 re-open ruling committed;
- (iv) peer convergence from trading-bot-architect, prediction-market-reviewer and security-reviewer.

A draft has no force. It is never cited by an allowlist row or a manifest.

### A.1 Condition

All of these must hold:
- the report of `/home/jon/breezy/scripts/analysis/no_longshot_pooled_test.py` is committed under `/home/jon/breezy/docs/evidence/m1v3/`;
- it was run at a HEAD descended from adb1cd8b;
- its status is READ, with `verdict == "WINNER"`;
- `bca_failed` is not true.

The ratified text pins that report's sha256. **CONFIRM means exactly this.**

### A.2 Ruled, on CONFIRM

1. **The sender.** `pm_us_nolong_d12_v1`, composition kind `no_longshot_d12`, is a permitted T2 sender, with §B as its floor prereg.
2. **M1V3-R1 is superseded for this family only.** Its "filter on a weather-sourced decision" sentence no longer limits sender eligibility. AS-R6 remains in force.
3. **Reconciling the operator directive of 09-29.**
   - The outcome term is the NWS CLI FINAL value, a US weather source, and the venue price is only the cost term. So the circularity objection behind the directive does not apply.
   - The *letter* of the directive is breached, because the price level selects the take. This is a narrow exception for this one family, decided through the peer loop.
   - **If any peer rejects it, §A.5 applies.**
4. **The population.** Frozen with the §B prereg by **2026-11-20**:
   - D0 only.
   - The first Depth10 update the node receives with `ts_event` in [12:00, 13:00)Z, for each YES rung.
   - NO ask = 1 − best YES bid (size ≥ 1). Take iff NO ask ≥ 0.90, inclusive, over the whole range [0.90, 0.99].
   - BUY NO, qty 1, IOC, limit = that NO ask.
   - One evaluation per (station, D, rung); hold to settlement.
   - Stations: LAX, MDW, MIA and SFO. NYC is added only if WP-0(a) shows support by 11-20; the default if that is undecided is the four-station set.
   - A.6 lists the residual differences from the screen.
5. **Gates:**
   - the permit;
   - the live-orders gate with an exact allowlist row;
   - the family halt;
   - the fee-drift probe;
   - the family loss stop (WP-5);
   - the submit-intent latch, under the WP-1 policy;
   - K1–K7;
   - both operator caps, unchanged.
6. **K4 formula (pinned; M2).**
   - **Count.** C_d is the number of node-evaluated rungs on trading day d whose first in-window NO ask is ≥ 0.90, taken from the decision funnel. It is independent of fills, the latch and caps.
   - **Day model.** Daily counts are negative binomial with mean μ and var = μ + αμ². Both μ and α are estimated on pre-window climate days 08-30..10-06 for the pinned stations (Stage −1).
   - **Block model.** For a 14-day block sum S, with days independent: μ_b = 14μ and α_b = α/14 (equivalently var_b = μ_b + α_b·μ_b²).
   - **Autocorrelation.** Day counts are acknowledged to be autocorrelated. var_b is multiplied by an inflation factor φ = 1 + 2·Σ_{k=1..3} ρ_k·(1 − k/14), where ρ_k are the pre-window lag-k autocorrelations, floored at 0 and pinned at the freeze.
   - **Trip rule.** Over each completed 14-day block, **K4 trips** iff the two-sided tail probability of S under the inflated block model is < 0.01 **and** S / μ_b lies outside **[0.5, 2.0]**. The band stays binding.
7. **K3 drop threshold (pinned; A1/M4).**
   - Stage −1 (§B.1) computes, from pre-window tape only, the curve d̂(L): the expected share of candidates dropped by a single serial latch with hold time L, for L ∈ {2, 5, 10, 20, 30, 45, 60} s. It reports the median (p50) and 90th percentile (p90) across days.
   - The K3 drop threshold is **τ_drop = d̂_p90(L*) + 0.10**. L* is the WP-0(c) measured p95 GET-resolution latency, rounded up to the grid and capped at 60 s.
   - The curve and the formula are frozen in the §B prereg; only L* is measured.
8. **Fee (M5).**
   - Before the freeze, WP-0(h) establishes the venue-charged fee per contract at qty 1 on the ask grid 0.90..0.99, from evidence dated before 10-07.
   - **(a)** If the venue fee is ≤ the screen primary fee, max(rounded, θ·a·(1−a)), at every grid point: no adjustment.
   - **(b)** If it exceeds the screen primary fee by at most 1¢ at some point (for example, rounding up to the cent at qty 1): ratification additionally requires the read report's slippage = 2¢ sensitivity, which adds 1¢ and dominates that excess, to show a one-sided lower bound > 0. If the report carries no lower bound for that row, the outcome is **STOP (shelve)**.
   - **(c)** If it exceeds the screen primary fee by more than 1¢ anywhere: **STOP (shelve).**
   - Which of (a), (b) or (c) applies is recorded in the §B prereg at the freeze.

### A.3 What the M1-v3 result may NOT be used for

- **(a)** Trading any other window.
- **(b)** Trading a sensitivity cell instead of the primary: an ask sub-band, a slippage variant or a fee variant.
- **(c)** Adding unscreened filters: depth, time, weather, or a station choice made after the read.
- **(d)** Serving as evidence for FQ v2, any forecast family, any model variant, the AUT-S ledger or `screen.py`.
- **(e)** Claiming an edge size. Only the lower bound is cited.
- **(f)** Re-reading, re-running or extending the screen, or relabelling UNDERPOWERED or PENDING_TRUTH.
- **(g)** Changing qty or either operator cap.
- **(h)** Trading any side other than BUY NO.
- **(i)** Trading any venue other than Polymarket.us.
- **(j)** Choosing the floor epochs, horizon or activation date after the read. Activation after 2027-01-20 means shelve.
- **(k)** Bypassing a FAIL or unrun §B floor.
- **(l)** Changing any K1–K7 threshold or formula, the latch bound L = 60 s, or any §B parameter after the read. τ_drop's curve and formula, the K4 μ, α and φ, and K5's reference composition and halt rule all live in the frozen §B prereg (M6).

### A.4 Relationships

- RULING_FQ-v2-NO-TRADE stays in force for FQ v2.
- B3 (a′) is decided by the separate WP-4 ruling.

### A.5 Any outcome other than CONFIRM

This covers:
- NO-EDGE, UNDERPOWERED or INVALID;
- PENDING_TRUTH still open past 12-21;
- a §B FAIL;
- an unratified WP-4 ruling;
- a WP-0 STOP;
- an M5 STOP;
- a peer rejection of A.2.3.

In every such case **the build is shelved**:
- the manifest stays `DRAFT_NOT_REGISTERED`, or is removed by a reviewed commit;
- no allowlist row is added;
- the code is inert;
- the WP-4 branch is not merged;
- the drop-in `fq-v1-halt-orders-off.conf` stays;
- nothing goes live.

The verdict is recorded in PROGRESS (M1V3-R11). Any re-test needs a new prereg and a new plan.

### A.6 Parity between the screen (PREREG) and the live family (disclosed)

| Dimension | Screen | Live family | Disclosure |
|---|---|---|---|
| Window and selector | First tape Depth10 row in [12, 13)Z | First Depth10 update the node receives in [12, 13)Z | WP-0(d) is a hard precondition (≥ 95% parity). |
| Incomplete station-day | Excluded whole (MNAR) | Takes per rung | K4b share is reported. |
| Truth availability | Excludes station-days without FINAL truth | Unknown at decision time | Reported at settlement. |
| Empty YES bid | Counted, no take | Same | Parity. |
| **Take-all vs serial latch** | Takes **every** qualifying rung-day | One order at a time. A candidate that arrives while an intent is OPEN is **dropped, not queued** (WP-1). | The expected drop share d̂_p50 / d̂_p90 at L* is entered here from Stage −1 **at the §B freeze, before 11-20**. |
| Execution | Blind: a fill at the ask is assumed | IOC misses, AMBIGUOUS outcomes, cap truncation | K3 and K6 fields. |
| Stations | All stations on the tape | The pinned set | NYC decision by 11-20. |
| Fee | max(rounded, unrounded) | Venue-charged | M5 rule (A.2.8); fee probe as tiebreaker. |

**Analysis population, stated honestly (A1).**
- The screen's population is *all qualifying candidates*.
- The live family trades a *time-ordered subset*: candidates whose first row arrives while no intent is OPEN, and before cap truncation.
- If arrival order within the 12:00Z burst correlates with ask level or outcome, the subset's EV differs from the screen's, and the CONFIRM does not cover that difference.
- For live evaluation:
  - the K1 loss stop runs on **attempted** takes, which are what is actually at risk;
  - K3 and K4 run on **candidates**, the screen-equivalent population;
  - the digest reports the ask-bin composition of attempted vs dropped candidates every day.
- Queueing is rejected: a queued order executes against a later book, which is a different population from the one screened.

## B. Loss-floor MC/NP design for `pm_us_nolong_d12_v1` (item 4)

**Schedule:**
- The prereg is `/home/jon/breezy/docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04/NOLONG_D12_floor_prereg.json`, frozen by a dedicated, gated commit **on or before 2026-11-20**.
- The binding run is 11-21..11-27, under a memory cap, with RuntimeMaxSec and a no-progress watch, one heavy job at a time.
- The result is committed **before the read is opened** (§C.9).
- The verdict binds. A FAIL cancels the late build.

### B.1 Pre-declared design

| Element | Value |
|---|---|
| Mix | `M-no` (existing name), over a pool containing only NO legs with ask ≥ 0.90 at the D_12Z first row, for the pinned stations. `MIXES` is unchanged. The NYC-inclusive pool is informational. |
| Data source | PM.us Depth10 tape for climate days **2026-08-30..2026-10-06**. Filtering happens on the directory index before any read; any day ≥ 10-07 is refused with exit 3 and nothing is written. Truth for days ≤ 10-06 is read only if `rho_hat` needs it. |
| Leg break-even | be = a + max(venue_fee(a), θ·a·(1−a)) + 0.01, with θ = 0.0695. |
| **be ≥ 1 threshold (P2)** | With the unrounded fee, solve a + θ·a(1−a) + 0.01 = 1. Put x = 1 − a: 0.0695x² + 0.9305x − 0.01 = 0, so x = (−0.9305 + √(0.9305² + 4·0.0695·0.01)) / (2·0.0695) = (−0.9305 + 0.931993) / 0.139 = 0.010739. **a\* = 0.98926.** On the 1¢ tick grid, a = 0.98 gives be = 0.98 + max(0.00, 0.001362) + 0.01 = 0.99136 < 1, which is kept. a = 0.99 gives be = 0.99 + max(0.00, 0.000688) + 0.01 = 1.000688, which is **excluded**. So **exactly the 0.99 asks are excluded.** (Under the M5 case (b), rounding up at qty 1, the 0.98 asks would reach be = 1.00 and also be excluded; that case is reported.) The coordinator's figure of "~0.985" is superseded by 0.98926. |
| **Exclusion cap and sensitivity (M0)** | If excluded legs are more than **5% of the pool's legs**, the verdict is **FAIL** (pre-declared). The binding run also reports an informational **clipped-be sensitivity**, in which excluded legs enter with be = 0.995. That understates cost, so it is never binding. **Exclusion is not conservative for G1:** removing legs changes the null crossing structure in either direction. The clipped sensitivity reports the direction and size of G1's change, and G1 is binding only on the primary exclusion run. |
| Feasibility under H0 | For a NO leg, q = 1 − be ≤ 0.10, so Σq ≤ 1 holds whenever a station-day has 10 or fewer legs. Station-days with Σq > 1 are counted. **More than 5% means FAIL.** |
| **Feasibility under H1 (M1)** | At the bar δ = −0.04, the H1 YES-cell mass per leg is q + \|δ\|. A station-day is H1-feasible iff Σ(q + \|δ\|) ≤ 1. Infeasible station-days are counted and **excluded from the bar's H1 draws**; **more than 5% of station-days means FAIL.** For the reported δ = −0.08 and −0.16 rows, the existing `_h1_masses`/`h1_fallback` path in `/home/jon/breezy/scripts/analysis/fq_loss_floor_mc_draw.py:61-69,216` is used unchanged, its fallback share is reported, and both rows are informational. |
| α ladder | `ALPHA_FLOOR_GRID` = (0.10, 0.20, 0.30), imported. Escalation looks at G1 only. A G3 miss is a veto. |
| δ grid | (−0.16, −0.08, −0.04, −0.02). **The bar is at δ = −0.04.** It is a *different* bar from FQ's, not a stricter one. **Drift between 0 and −4¢ per take is not protected by the stop**; it is covered only by the CONFIRM lower bound, K5 and the horizon. |
| Epochs and horizon | Epochs {**2026-12-23, 2027-01-06, 2027-01-20**}; horizon **2027-02-28**, which is also `terminal_climate_day`. No epoch precedes the read. Activation after 01-20 means shelve. |
| G-gate bar | G1 holds, and G3(−0.04) ≥ 2.5·α at the selected α, at every epoch. |
| D1-analogue bar | The NP upper bound on G3(−0.04), at the effective α (α_eff), is ≥ 0.30 at every epoch, with `e_proj` = 2027-01-20. No switch to the nominal α. |
| Seeds | 20261121 (A1 analogue) and 20261122 (Stage 0); 10k replicates each. |
| **Sensitivities (informational; M7)** | Take rate ±50% via a pre-declared thinning or duplication of pool days, reported at **every epoch, explicitly including 01-20**. At −50% (about 4.7 takes per day), the 39 days from 01-20 give about 183 takes against the about 156 needed at δ = −0.04, which is **marginal**, and stated as such. The run also reports the NYC pool and the clipped-be pool. |
| **Stage −1 (descriptive, committed before Stage 0 and before the freeze of the K-thresholds)** | Pre-window data only. It reports:<br>• the path-tick distribution per epoch;<br>• K4 inputs: μ, α, ρ₁..₃, φ;<br>• legs per station-day;<br>• the reference ask-bin composition, day-clustered, for K5;<br>• the be ≥ 1 exclusion count, the H0 Σq count and the H1 feasibility count;<br>• **(A1)** the per-day distribution of gaps between candidate first-row timestamps across all pinned rungs in [12:00, 13:00)Z, with the share arriving within 12:00:00–12:00:05Z;<br>• **(A1)** the drop curve d̂(L) for L ∈ {2, 5, 10, 20, 30, 45, 60} s, computed by replaying a single serial latch of hold L over each day's candidate arrival order (p50 and p90 across days).<br>No verdict comes from Stage −1. Its values are copied into the §B prereg (for K3, K4 and K5) and into A.6, and the prereg freeze commit follows. |
| Freeze check | `check_frozen_blob`, plus the rule that the freeze commit introduced the blob (`/home/jon/breezy/scripts/analysis/prereg_precommit_check.py`). |
| Amendment shape | The result is serialised in the schema read by `/home/jon/breezy/scripts/analysis/prereg_amendment_check.py`. If that schema is FQ-specific, WP-5 adds a per-family loader. |

### B.2 Path argument: a hypothesis, to be tested by Stage −1 and Stage 0

FQ v2's D1 failure was driven by short paths:
- the M-yes median was about 7 ticks;
- α_eff was 0.0187 and the NP bound 0.1186;
- `bound_upper_min` was 0.125 against a bar of 0.30;
- A1's G3(−0.16) in M-yes was 0.2104 against 0.25;
- M-no passed NP at 0.4927 on 11-01, but its G3 at 12-01 was 0.2334.

For this family:
- at about 9.4 takes per day over four stations, the 39 days from 01-20 to the horizon give about 135 station-day ticks;
- δ = −0.04 needs about 156 takes, roughly 17 days;
- at −50% take rate, about 183 takes are available against 156 needed, which is marginal (M7).

**Counter-hypotheses:**
- Fat single losses near a ≈ 0.97 strain the normal approximation; the NP bound measures this.
- The winter ask mix may differ (K5).
- The exclusions reduce the number of ticks.

### B.3 Tooling (WP-A, scripts only). Built 11-09..11-19.

- **Golden files first, in a separate earlier commit.** Store A1 and Stage-0 subset outputs at the current HEAD in `/home/jon/breezy/tests/fixtures/fq_floor_golden/`, so the comparisons below are against real outputs. Add an **E2 golden** produced by `fq_loss_floor_mc_e2.py` at its default (P1).
- **`McDesign` (deltas, epochs, freeze, horizon)**, as keyword-only arguments with defaults equal to today's constants, in:
  - `fq_loss_floor_mc_gate.py`
  - `fq_loss_floor_mc_engine.py`
  - `fq_loss_floor_mc_report.py`
  - `fq_loss_floor_np_bound.py`
  - **`/home/jon/breezy/scripts/analysis/fq_loss_floor_mc_e2.py`** (P1), where the `epoch_grid(freeze)` call at `:231` takes the design's epochs.

  **`/home/jon/breezy/scripts/analysis/fq_loss_floor_mc.py` is not edited**, because its blob is pinned in the F5 evidence.
- **RED tests:**
  - `test_fq_design_default_matches_golden_a1_subset`
  - `test_np_bound_default_matches_golden_stage0_subset`
  - `test_e2_default_matches_golden` (P1)
  - `test_e2_uses_injected_epochs_12_23_01_06_01_20_horizon_02_28` (P1)
  - `test_fq_loss_floor_mc_py_blob_unchanged`
- **`/home/jon/breezy/scripts/analysis/nolong_d12_mc_templates.py`** (under 300 lines). **RED tests:**
  - `test_refuses_climate_day_on_or_after_2026_10_07`
  - `test_date_filter_precedes_any_tape_read`
  - `test_be_uses_screen_primary_cost`
  - `test_be_threshold_excludes_exactly_ask_099_on_grid`
  - `test_excluded_leg_share_over_5pct_fails`
  - `test_clipped_be_sensitivity_never_binding`
  - `test_pool_all_legs_side_no_ask_ge_090`
  - `test_h0_sum_q_feasibility_counted`
  - `test_h1_feasibility_sum_q_plus_delta_counted_and_excluded_at_bar`
  - `test_d12_first_row_only`
  - `test_no_ask_none_counted_not_synthesised`
  - `test_candidate_gap_distribution_and_drop_curve_pre_window_only` (A1)
- **`/home/jon/breezy/scripts/analysis/nolong_d12_floor.py`** (under 200 lines). **RED tests:**
  - `test_refuses_unfrozen_prereg`
  - `test_no_nominal_alpha_path_after_result`
  - `test_epoch_holds_required_at_every_epoch`
  - `test_h0_h1_at_most_one_losing_leg_per_station_day`
  - `test_sensitivity_takes_rate_pm50_reported_at_every_epoch_including_01_20` (M7)
- **Gate:** focused tests, the mypy ratchet, `lint-imports` from the tree root ("N kept, 0 broken"), then the full gate.
- **Effort:** 3.5 d of build plus 1 d of review.

## C. Code work packages

### WP-0 Verify-first (read-only)

**Early (11-09..11-19):**
- **(a) NYC support.** Check the registry settlement site, climate-day window and truth feed. The decision goes into the §B prereg by 11-20; the default is four stations.
- **(b) AUT-5a routing.** Is the registry boot path mandatory? **The decision is due by 11-12.**
  - If it is: add the family to `LIVE_GATE_ROUTED_KINDS`, and make `pins.SCHEDULE_*`, `fold_pairs.py:120`, `validate_ii.py:146-149,378-386` and `wal_snapshot.py:553` follow the per-family schedule, with security review and replay tests. That is **5–6 d** (A5), with consequences in §C.7.
  - If it is not: the family boots from env and nothing is widened.
- **(c-early) Latch, read from the code (A4).**
  - Read the resolve and retire mechanics behind `/home/jon/breezy/src/breezy/runtime/submit_intent.py:386-422` and the AMBIG-LATCH B resolver path.
  - Extract GET-resolution latency from node log files dated **before 2026-10-07T00:00Z**, if any exist (FQ v1 and earlier live orders). Read latency fields only, never prices or outcomes.
  - If such evidence exists, a provisional L* is set early. If its p95 exceeds 60 s, **STOP**.
- **(e) Other mirrors.** Grep `forecast_quantile_ladder` and `forecast_ladder` across `/home/jon/breezy/src` and `/home/jon/breezy/tests` for further mirrors, and re-verify `validate_ii.py:488`.
- **(f) Exec-pin file (S4).** Identify the exact exec-import/firewall pin file and row that need a WIDENED row for `src/breezy/strategy/no_longshot_d12/strategy.py`. The candidate is `/home/jon/breezy/tests/contract/test_us_source_ingest_egress_guard.py:608`. Confirm the NO-buy path reuses the FQ venue translation (SELL/BUY_SHORT). **This must be resolved before the WP-1 merge; it is an explicit merge precondition.**
- **(g) Node-stop helper (S2).** Find the existing operator node-stop procedure, if any (for example in `R8_OPERATOR_RUNBOOK.md`). If none exists, WP-5 adds a small read-only `scripts/ops/node_pid_readback.py`, which reuses `SupervisorPorts.find_node_pid` and `intent_lock_free` and never signals anything.
- **(h) Venue fee (M5).** Find the venue-charged fee per contract at qty 1 on the grid 0.90..0.99, from fill or preview evidence dated before 10-07. Classify it as M5 case (a), (b) or (c), and record the classification in the §B prereg.

**Late (11-28..):**
- **(c-late)** Measure live GET-resolution latency, giving the final L* (p95, rounded up to the grid, capped at 60 s). If p95 exceeds 60 s, **STOP**.
- **(d)** Recorder-vs-node first-row parity, using a post-11-28 recorder sample and a scratch shadow node. ≥ 95% is required; otherwise **STOP**.

**Latch bound (A2): one number, L = 60 s, used everywhere.**
- GET-resolve after an AMBIGUOUS response at offsets of +2, +7, +15, +30 and +60 s.
- If still unresolved at 60 s, the intent stays OPEN and K6 applies.
- Why 60 s: it is 1/60 of the one-hour window. Past 60 s an OPEN latch blocks a growing share of the remaining candidates (Stage −1's d̂(60) quantifies this), and 60 s is the top of the d̂(L) grid.

### WP-1 Strategy: `/home/jon/breezy/src/breezy/strategy/no_longshot_d12/` (3.5 d)

**Files:**
- `config.py`, with `shadow_only: bool = True`;
- `decision.py`, pure, built early;
- `strategy.py`, using native Nautilus depth subscriptions and an IOC limit `submit_order`, with the persistent latch and its own key prefix;
- `composition.py`.

**Latch policy:**
- One order at a time: arm, then POST, then retire.
- A candidate seen while an intent is OPEN is **dropped and counted**, never queued.
- GET-retire follows the schedule above, with L = 60 s.
- The digest carries `candidates`, `attempted`, `filled`, `zero_fill`, `latch_dropped`, `ambiguous_resolved`, `ambiguous_open`, and the ask-bin composition of attempted vs dropped.

**RED tests:**
- `test_decision_parity_with_m1_selector_on_fixtures`, with ≥ 30 pre-window fixtures asserted non-empty
- `test_ask_090_inclusive_no_upper_subband`
- `test_first_row_only`
- `test_outside_window_never_evaluated`
- `test_d0_only`
- `test_one_take_per_rung_day_latched_across_restart`
- `test_buys_no_leg_only`
- `test_qty_is_one`
- `test_empty_yes_bid_no_take_counted`
- `test_latch_refusal_is_counted_not_silently_skipped`
- `test_latched_candidate_never_queued`
- `test_ambiguous_get_retire_offsets_and_60s_bound`
- `test_try_submit_order_permit_veto_fee`
- `test_no_order_when_shadow_only`
- `test_fee_grid_live_vs_screen`, on asks 0.90..0.99. It pins the screen's primary fee, including a = 0.95, where the rounded fee is 0.00 and the unrounded fee 0.0033, and pins the WP-0(h) venue value per M5.
- The WIDENED exec-pin row (S4).

**Replay (not RED):** pre-window days only; it must reproduce ≥ 99% of m1's takes.

**Merge preconditions:** WP-0(f) resolved, and the full gate passes with GATE_EXIT=0.

### WP-2 Composition kind, dispatch and guards (3 d)

**Mirrors.** Each V3 site is widened by one row, with these RED tests:
- `test_composition_kinds_widened_by_exactly_nolong`
- `test_subscribed_marker_map_has_nolong`, which updates `/home/jon/breezy/tests/unit/test_app_trade_boot_family_log.py:217` and `/home/jon/breezy/tests/unit/test_forecast_quantile_ladder_manifest_and_markers.py:64`
- `test_node_plugins_equal_offline_plugins_equal_kinds`
- `test_autonomy_paths_kinds_mirror_and_model_class_re_matches`
- `test_haltable_kinds_include_nolong_exit_kinds_unchanged`
- `test_live_gate_routed_kinds_unchanged`, or `…_widened` if WP-0(b) forces routing

**`trade.py` keeps only the gate site.**
- The non-gate logic goes in `/home/jon/breezy/src/breezy/app/compose_no_longshot.py`: the halt preamble, `LossStopProbe(path=<nolong path>)`, the veto (halt, then loss stop), the fee probe, the funnel, and the builder.
- A shared helper `_live_orders_gate_preamble(manifest, sending_permit)` in `trade.py` makes the `live_orders_authorized` call, logs and raises. Both composers use it.
- `_compose_no_longshot_d12` is about 20 lines.
- `trade.py` is recorded as oversize at 1274 lines; AUT-5 owns it.

**AST guard: narrow + one reviewed site.**
- The permitted sites are exactly {(trade.py, `_compose_forecast_quantile_ladder`), (trade.py, `_compose_no_longshot_d12`)}, keyed by function name via AST, with an exact count.
- In each function, `live_orders` is bound exactly once, by an `Assign` from a call to `_live_orders_gate_preamble` or `live_orders_authorized`. Any re-binding is rejected.
- **(S3)** A new AST pin, `test_gate_preamble_binds_from_live_orders_authorized`, asserts that `_live_orders_gate_preamble` returns a value bound from a direct `live_orders_authorized(` call and does not construct `LiveOrdersDecision` itself. Its positive control is `test_preamble_constructing_decision_directly_flagged`.
- `test_the_permitted_expression_actually_appears_in_trade_py` requires both sites.
- Further positive controls: wrong function name, binding from a non-gate call, re-binding, and a third site.
- Security sign-off is required.

**Dispatch tests:**
- `test_compose_family_dispatches_nolong`
- `test_fq_still_dispatches_to_fq_composer`
- `test_unknown_kind_refuses_with_specific_settings_error_and_log_line`
- `test_gate_refusal_raises_settings_error_and_logs_reason`
- `test_nolong_loss_stop_path_distinct_from_fq`
- `test_draft_manifest_refuses_boot`

**Focused gate:** the exec-pin and firewall guards, the operator-control scan, `test_node_composition_contract`, `test_native_order_cap_wiring`, all `test_autonomy_*`, the import gates, the citation map, and `lint-imports`.

### WP-3 Manifest and allowlist (0.5 d)

- `/home/jon/breezy/deploy/families/pm_us_nolong_d12_v1.json`:
  - `DRAFT_NOT_REGISTERED`
  - kind `no_longshot_d12`
  - the pinned stations
  - fee coefficient "0.0695"
  - `terminal_climate_day` "2027-02-28"
  - sentinel artefacts
  - no ruling field
- **RED tests:**
  - `test_nolong_manifest_draft_refused_without_allow_draft`
  - `test_live_orders_allowlist_is_exactly_fq_v1_row`, an exact-equality pin. At activation it is **replaced** by an exact-equality pin of the two-row set, never deleted.

### WP-4 Per-kind schedule record (item 8, 6 d). Built early on a branch, merged late.

**Timing ruling (S1, reconciled):**
- WP-4 is **built early (11-09..11-27) on a branch** as a **default-identical** diff.
- It is **NOT merged before the late phase.** The late merge requires all three of:
  - (i) a full gate pass, GATE_EXIT=0;
  - (ii) a **security re-review** of the final diff;
  - (iii) sequencing against **AUT-5a**, which owns these files and has not merged: WP-4 rebases onto AUT-5a if AUT-5a lands first, otherwise the coordinator orders the two.
- **The early phase therefore makes no live-surface change.** The supervisor unit and code on the primary tree are untouched until the late merge.

**B3 re-open ruling.** Drafted early, peer-reviewed by security-reviewer, and committed as a document, with no live effect, before the WP-4 merge. It restates:
- the clustering argument of RULING_permit_daily_coverage §4;
- the per-kind daily reset of `first_boot_permit_expires_at_ns` at the STOP_PRIOR rollover;
- **(A3)** that `validate_ii.py:378-386` (the `SCHEDULE_LAUNCH_WINDOW_END_UTC` / 16:50 anchor for registry pair void semantics), `pins.py:121-125`, `fold_pairs.py:120` and `wal_snapshot.py:553` **stay fixed**, and that **this is valid only while `no_longshot_d12` is not registry-routed**. If WP-0(b) forces routing, the ruling is re-opened and those sites follow the per-kind schedule (5–6 d).

**Code.** A frozen `KindSchedule` record and a code-literal `SCHEDULE_BY_KIND` in `/home/jon/breezy/src/breezy/runtime/trade_supervisor_core.py`. The default row equals today's values, and the module constants remain as aliases of it.

| Field | Default | `no_longshot_d12` |
|---|---|---|
| STOP_PRIOR | 16:40 | 11:20 |
| LAUNCH | 16:50 | 11:30 |
| RELAUNCH_CUTOFF = LAUNCH_WINDOW_END | 17:00 | 11:40 |
| SELF_CHECK | 17:05 | 11:45 |
| SELF_CHECK_WINDOW_END = B1_WINDOW_OPEN | 17:10 | 11:50 |
| `midday_watch_window_end` | 01:00 on trading day + 1 | 13:00 on trading day |
| Trading-day rollover | 16:40 | 11:20 |
| Nominal permit | 16:50–02:50 | 11:30–21:30 |

**Consumers outside the supervisor:**
- The nbp analyses stay on the default alias.
- The registry sites stay fixed per A3.
- `breezy-family-tally@.timer` stays at 17:20Z.
- Comment and log-fixture sites need no action.

**RED tests:**
- `test_default_kind_schedule_identical_to_all_constants_and_consumers`
- `test_nolong_permit_covers_12_13Z`
- `test_nolong_union_permit_coverage_bounded_over_all_relaunch_paths`: the union is ≤ 10 h 10 min and lies inside [11:30, 21:40]
- `test_first_boot_expiry_resets_at_kind_stop_prior`
- `test_kind_switch_midday_waits_for_next_stop_prior`
- `test_schedule_not_env_overridable`
- `test_single_mint_per_day_nolong`
- `test_validate_ii_launch_window_anchor_unchanged` (A3)

### WP-5 Hold, loss stop, demotion/kill, node-stop read-back (3.5 d)

**Hold.** Positions are held to settlement; `KINDS_WITH_EXIT_PATH` is unchanged; reconciliation applies the NO-leg sign.

**Producer.** A new `breezy-nolong-loss-stop` oneshot timer. It replays `step_clock` with the §B boundary over this family's settled fills and FINAL truth, and writes `loss_stop/v1` to `$DATA/derived/nolong-loss-stop/latest.json`.

**n=0 ruling (S5), endorsed by the architect:**
- **There is no seeded PASS.**
- The first PASS is an **evaluated digest over a verified-empty ledger**: the ledger exists, is readable, and verifiably holds zero settled fills for this family, and the digest is recomputable from `c2_hwm`=0 and the truth sha.
- A **missing or unreadable ledger** gives no artefact, so the verdict is **UNKNOWN, and UNKNOWN vetoes**, consistent with `LossStopProbe`.

**Producer RED tests:**
- `test_producer_empty_ledger_passes_missing_ledger_unknown`
- `test_producer_never_writes_seeded_pass`
- `test_producer_digest_recomputable`
- `test_producer_refuses_other_family_fills`
- `test_missing_artefact_vetoes`
- `test_fail_sets_family_halt_set_only`

**Guard reshape** (security-reviewed narrowing) in `/home/jon/breezy/tests/contract/test_fq_loss_stop_writer_allowlist.py`:
- tokens become (`fq-loss-stop`, `nolong-loss-stop`);
- unit prefixes become (`breezy-fq-loss-stop.`, `breezy-nolong-loss-stop.`);
- amendment files are per-family, each with a reachable check;
- one nolong writer row is added, valid only while the nolong floor is reachable.

Positive controls:
- `test_planted_nolong_token_writer_flagged`
- `test_planted_nolong_unit_flagged`
- `test_nolong_writer_row_refused_when_floor_unreachable`
- `test_fq_scan_unchanged`

The guard reshape may merge early, since it is a test-only narrowing. The writer row lands late.

**Node-stop read-back (S2).** If WP-0(g) finds no existing helper, add `/home/jon/breezy/scripts/ops/node_pid_readback.py`. It is read-only: it reports the PID-verified intent-lock holder and its cmdline, and whether the lock is free. RED tests: `test_readback_reports_lock_holder_pid` and `test_readback_never_signals`.

**Demotion and kill rules.** All act through the set-only family halt, and none re-arms. K3–K6 are computed by `/home/jon/breezy/scripts/analysis/decision_funnel_daily_digest.py`, which pages; the coordinator applies the halt the same day. **All thresholds come from the frozen §B prereg (A.3(l)).**
- **K1.** Loss-stop FAIL. Terminal.
- **K2.** Fee-drift mismatch. Halt.
- **K3.** Execution, on resolved outcomes. Once attempted ≥ 30:
  - halt if filled / attempted < 0.50;
  - halt if latch_dropped / candidates > **τ_drop** (A.2.7). The threshold sits above the drop share the latch produces by itself, as estimated from pre-window data (A1/M4).

  Price improvement means `fill_px < limit`. A fill worse than the limit is an immediate halt and an evidence report.
- **K4.** The formula in A.2.6. **K4b**, the share of live takes on station-days the screen would have excluded, is reported; above 0.20 it raises a review flag.
- **K5 (M3).**
  - **Test.** A two-sample, day-clustered test of the candidate ask-bin composition ([0.90, 0.92], [0.93, 0.95], [0.96, 0.99]). It compares the live days in each 14-day block against the Stage −1 pre-window days, using a day-block permutation test with B = 10,000 and a pinned seed.
  - **Default action.** A **review flag**.
  - **Halt** only if both hold:
    - p < 0.001 with n ≥ 60 candidates;
    - the live share of candidates in bins with **be above the screen's realised hit rate** rises by ≥ 15 percentage points.
  - **Which bins count.** The read report's per-bin net EV, if it reports one, decides which bins have be above the hit rate (negative-EV bins). If it does not, the **[0.96, 0.99]** bin is designated now, before the read, as the negative-EV-risk bin.
- **K6.** Any AMBIGUOUS still OPEN at the end of the 60 s bound that remains unresolved at 13:00Z triggers a halt, pending venue evidence.
- **K7.** `terminal_climate_day` 2027-02-28.

**Threshold tests:**
- `test_k3_thresholds_from_frozen_prereg`
- `test_k3_drop_threshold_formula_tau_drop`
- `test_k4_nb_block_alpha_over_14_with_phi_and_band`
- `test_k4_not_tripped_by_cap_truncation`
- `test_k5_day_clustered_flag_vs_halt`
- `test_k6_unresolved_ambiguous_halts`

### WP-6 Merge order with AUT-5a (1.5 d; 5–6 d more if routing is forced)

- **If AUT-5a has merged:** rebase WP-2 and WP-4 onto it, adopt its manifest signature, and add a bootstrap row or `entry_veto` slot if required.
- **If it has not:** the coordinator sequences the merges. WP-4 never merges ahead of a conflicting AUT-5a without re-review.
- **In both cases:** run the full gate after every merge and read GATE_EXIT before any push.

### C.7 Effort and schedule

| WP | Phase | Build | Review | Merges |
|---|---|---|---|---|
| WP-A | early | 3.5 d | 1 d | 2 |
| WP-0 (a, b, c-early, e, f, g, h) | early | 1.5 d | — | — |
| WP-0 (c-late, d) | late | 0.5 d | — | — |
| WP-1 `decision.py` + parity/fee tests | early (inert module) | 1 d | 0.5 d | 1 |
| WP-1 strategy | late | 2.5 d | 0.5 d | 1 |
| WP-4 ruling + branch build | early, **branch only, no merge** | 5 d | 1 d | 0 |
| WP-4 merge | late (gate + security re-review + AUT-5a) | 1 d | 0.5 d | 1 |
| WP-5 guard reshape | early (test-only narrowing) | 1 d | 0.5 d | 1 |
| WP-5 producer, K-rules, read-back | late | 2.5 d | 0.5 d | 1 |
| WP-2 | late | 3 d | 1 d | 2 |
| WP-3 | late | 0.5 d | — | 1 |
| WP-6 | late | 1.5 d (+5–6 d if routing) | 0.5 d | 2 |

**Totals:** about 25 agent-days, plus about 6 h of serial gate time at 23–25 min per merge.

**Early phase (11-09..11-27), all read-safe:**
- WP-A;
- WP-0 (a), (b) by 11-12, (c-early), (e), (f), (g), (h);
- WP-1 `decision.py`;
- WP-4 on a **branch only**, plus its ruling document;
- the WP-5 guard reshape.

None of it is a live-surface change.

**Late phase (11-28..12-06), only after the floor PASS:**
- WP-0 (c-late) and (d);
- the WP-1 strategy;
- WP-2 and WP-3;
- the WP-4 merge;
- the WP-5 producer;
- WP-6.

The critical chain is WP-1 strategy → WP-2 → WP-6, about 7 d of build plus about 2 d of review. That is **feasible only with ≥ 3 parallel worktrees and no AUT-5a conflict**.

**Nominal activation:** read on 12-07, ratify on 12-08, shadow day 12-09/10, orders about 12-10/11.

**If WP-0(b) forces routing (decided by 11-12):** the 9-day late window is **infeasible**. The routing work (5–6 d) sits on the late critical chain, because it touches AUT-5-owned and registry files that only merge late. The build then ends about 12-12, and **activation is about 12-16..12-18**. That is still before the 01-20 shelve deadline. The early phase may build the routing changes on a branch as well, but under the same no-merge rule.

### C.8 Live-surface statement

Before the late phase, nothing changes on the primary tree's supervisor unit, `trade_supervisor*.py`, `trade.py`, the live-orders allowlist or any deployed family. Early merges are limited to:
- analysis scripts (WP-A);
- an inert pure module (`decision.py`);
- a test-only guard narrowing (WP-5);
- documents.

### C.9 Slip policy (P3)

**The dependency chain:**
1. WP-0(b) decision (11-12)
2. NYC decision and Stage −1 (by 11-20)
3. §B freeze (11-20)
4. Binding run (11-21..11-27)
5. Floor result committed
6. Late build (11-28..)
7. Read (on or after 12-07)
8. Ratification
9. Shadow day
10. Orders

**Slip rules:**
- **The read never precedes the committed floor result.** If the floor slips, the read is delayed; PREREG's "on or after" permits that, and truth completeness only improves.
- **A late §B freeze** must still precede the binding run, and the K-thresholds come only from pre-window Stage −1. If the freeze cannot happen before the read, the family is shelved.
- **An unresolved NYC decision by 11-20** means the four-station default applies.
- **WP-0 STOP** outcomes ((c), (d), M5 (c)) mean shelve.
- **Any late WP slip** moves activation day for day. If activation would fall after **2027-01-20**, the family is shelved.
- **Never compressed or skipped:**
  - the full gate after every merge, with GATE_EXIT read before any push;
  - every review, including WP-4's security re-review and the WP-2 guard sign-off;
  - the B3 re-open ruling;
  - the shadow-only boot day;
  - the halt and node-stop read-backs;
  - the dry run of the changed unit.

## D. Activation runbook (item 7), on CONFIRM only

### D.1 Day 0: read

1. Run the frozen tool once, with no `--as-of`, and only after the §B result is committed.
2. Commit the report.
3. If the verdict is not WINNER, apply §A.5.

### D.2 Day 0–1: ratify

1. Finalise the §A text with the report, §B and WP-4 shas.
2. Apply the M5 case (b) check if it applies.
3. Run the peer loop.
4. Compute the ruling sha256 **after** the final text. Commit the evidence copy and a byte-identical `/home/jon/breezy/deploy/families/rulings/` copy.
5. In one reviewed commit:
   - add the allowlist row;
   - **replace** the WP-3 pin with an exact two-row equality pin;
   - set the manifest to `REGISTERED`, with `live_orders_ruling` and `d0_climate_day`.
6. Run the full gate. Read GATE_EXIT before any merge or push.

### D.3 Day 1–2: shadow-only boot, with the drop-in still present

1. Commit `BREEZY_SENDING_FAMILY_ID=pm_us_nolong_d12_v1` to `/home/jon/breezy/deploy/systemd/breezy-trade-supervisor.service` **on a branch**. The file is symlinked live. Merge only at GATE_EXIT=0.
2. Dry-run the unit: `systemd-analyze --user verify`, and `systemctl --user cat` to confirm the drop-in still sets `BREEZY_ORDERS_ENABLED=0`.
3. **Quiet window:**
   - under the outgoing schedule: 01:00–16:40Z;
   - under the nolong schedule: **13:15Z–11:10Z**, which avoids STOP_PRIOR (11:20) through the mid-day watch end (13:00) and the B1 window opening at 11:50.

   Restart only inside the window for the schedule active at that moment. The switch day waits for the next 11:20Z STOP_PRIOR.
4. At 11:30Z on the shadow day, verify:
   - the live-trading permit expiry is ≥ 13:00Z (nominal 21:30Z);
   - the order-submission permit is absent because orders were not requested (`PASS_ORDERS_NOT_REQUESTED`);
   - `boot_family id=pm_us_nolong_d12_v1`;
   - the live-orders line shows `enabled=False reason=permit_absent ruling_sha256=<pinned>`;
   - shadow decisions appear in [12, 13)Z;
   - the loss-stop artefact is an evaluated empty-ledger PASS, not UNKNOWN.

### D.4 Day 2–3: orders on

1. Remove `/home/jon/.config/systemd/user/breezy-trade-supervisor.service.d/fq-v1-halt-orders-off.conf` as a reviewed act: an evidence note, a one-line heads-up, and a scratchpad snapshot of the file first.
2. Run daemon-reload and restart inside the quiet window.
3. **Operator items: none.** The two caps are already set.
4. First trading day, from node log files (never journald):
   - the boot-time order-submission permit line;
   - `enabled=True reason=ok`;
   - SELF_CHECK at 11:45Z returns PASS;
   - candidate, attempt, fill and drop counts, plus the ask-bin composition of attempted vs dropped;
   - every AMBIGUOUS resolved within 60 s, or K6 applied;
   - D+1 reconciliation with the leg sign;
   - K3–K5 fields populated;
   - liveness = process + log mtime + permit unexpired + tape advancing.

### D.5 Rollback, in order (S2)

1. **Halt.** Run the family-halt CLI with an absolute `--families-dir`. **Read back** the halt: the halt status read path shows the row present, and the digest shows the family halted. The halt CLI already failed once, on 10-05, because of a cwd bug.
2. **Stop the supervisor first**, so it cannot relaunch the node (mid-day relaunch): `systemctl --user stop breezy-trade-supervisor.service`. Because of `KillMode=process`, the node keeps running.
3. **Stop the node** through the real path. There is no node unit. Take the node PID as the **PID-verified intent-lock flock holder** from `/home/jon/breezy/scripts/ops/node_pid_readback.py`, or the procedure WP-0(g) finds. That is the same source STOP_PRIOR uses (`find_node_pid`). Verify its cmdline is `breezy-trade`, then send **SIGTERM only** (`kill -TERM <pid>`). Never pgrep and never SIGKILL.
4. **Read back the stop:**
   - the intent lock is free (no FLOCK holder);
   - `kill -0 <pid>` fails;
   - the node log shows its shutdown line.
   If the process is still alive after the STOP_PRIOR poll budget, re-run the read-back and alert. Do not escalate the signal.
5. Restore the drop-in from the snapshot, run daemon-reload, and start the supervisor inside the quiet window.
6. Verify that orders are not requested at the next boot.

## E. Risks

| # | Risk | Sev. | Mitigation |
|---|---|---|---|
| R1 | P(WINNER) ≈ 3%. This is the dominant risk. | Dominant | Option value. The late build is gated on the floor result. Early work is reusable and changes no live surface. |
| R2 | P(edge given WINNER) is only about 0.2–0.4. | High | Qty 1 and K1–K7. |
| R3 | Selection bias and transport: a single window chosen after M1; an Oct–Nov sample (about 40 day-clusters) vs Dec–Feb trading; MNAR exclusions. | High | §A.3, A.6, K4/K4b/K5, winter epochs. |
| R4 | The permit gap, which needs the WP-4 refactor in AUT-5-owned files. | High | Branch-only early build; late merge only with the gate, security re-review and AUT-5a sequencing. |
| R5 | Serial-latch drops at the 12:00Z burst. | High | Stage −1 d̂(L), τ_drop, L = 60 s, the A.6 disclosure, attempted vs dropped reporting. |
| R6 | Recorder-vs-node first-row disparity. | High | WP-0(d) STOP rule. |
| R7 | Cap truncation. | Med | K4 uses candidates. Caps are never changed. |
| R8 | A peer rejects the 09-29 reconciliation. | Med | §A.5. |
| R9 | The venue fee is above the screen fee. | Med | M5 rule, decided before the freeze. |
| R10 | Routing is forced. | Med | Decision by 11-12; activation about 12-16..12-18. |
| R11 | Window contamination. | High | Date filters before any read, RED tests, latency/fee-only reads of pre-10-07 logs, WP-0(d) restricted to post-11-28 data. |
| R12 | Drift between 0 and −4¢ per take is unprotected. | Med | Disclosed; K5. |
| R13 | Excluding be ≥ 1 legs is not conservative for G1. | Med | 5% cap; clipped-be sensitivity reported. |

## F. Expected value

**Probabilities.** P(edge | W) = π·P(W | edge) / (π·P(W | edge) + (1 − π)·P(W | null)).
- **Null WINNER rate.** At a true mean of −0.3¢ and SE ≈ 0.8¢, WINNER needs the estimate to exceed 1.645·0.8 = 1.32¢. So P(W | null) = P(Z > 2.02) ≈ **2%**.
- **WINNER rate under a +1¢ edge.** P(W | +1¢) = P(Z > 0.40) ≈ **34%**.
- **Posterior.** π = 3% gives ≈ **35%**; π = 2% gives ≈ 26%. **P(edge | WINNER) ≈ 0.2–0.4.**
- **Overall P(WINNER)** ≈ **3%**.

**Payoff.** At qty 1 with about 9 takes a day, less latch drops, a +1–2¢ edge is worth about $0.10–0.20 a day. Expected direct P&L is cents.

**Option value.** A ratified sender with a passing floor is the only route before 2027 that un-gates the live stages of AUTONOMY rows 7b and 8–12, and that produces real fills.

**Cost.**
- About 25 agent-days in total.
- About 13 of those are early and reusable: the floor tooling, the per-kind schedule on a branch, the guard narrowing, and the pure decision module.
- About 12 are late and spent only after a floor PASS.

**Recommendation.** Run the read-safe early phase. Build the late phase only after the floor PASS. Treat a CONFIRM as roughly a one-in-three chance of a real edge that buys a deployed sender.

## §R3 changelog

| ID | Section(s) changed |
|---|---|
| WP-4 timing ruling | §C.WP-4, §C.7, §C.8, §E R4 |
| S1 | §C.7 early list, §C.WP-4, §C.8 |
| S2 | §0 V13, §C.WP-0(g), §C.WP-5 read-back, §D.5 |
| S3 | §C.WP-2 |
| S4 | §C.WP-0(f), §C.WP-1 merge preconditions |
| S5 | §C.WP-5 n=0 ruling and test |
| P1 | §0 V14, §B.3 |
| P2 | §B.1 be ≥ 1 threshold row |
| P3 | §C.9 |
| A1 + M4 | §A.2.7, §A.6, §B.1 Stage −1, §C.WP-5 K3, §E R5 |
| A2 | §C.WP-0 latch bound, §C.WP-1, §C.WP-5 K6 |
| A3 | §0 V15, §C.WP-4 ruling and test |
| A4 | §C.WP-0(c-early)/(c-late), §C.7 |
| A5 | §C.WP-0(b), §C.WP-6, §C.7 |
| M0 | §B.1 exclusion row, §E R13 |
| M1 | §B.1 H1 feasibility row |
| M2 | §A.2.6 |
| M3 | §C.WP-5 K5 |
| M5 | §A.2.8, §C.WP-0(h), §E R9 |
| M6 | §A.3(l), §C.WP-5 |
| M7 | §B.1 sensitivities, §B.2 |

**Not satisfied, or deviating:**
- **(1) The file was not written.** This agent is read-only and has no Write tool. The coordinator saves this text.
- **(2) P2's "~0.985" is superseded.** The exact threshold is 0.98926 (derivation in §B.1); only the 0.99 ask is excluded on the grid.
- **(3) A4's early latency evidence is conditional.** It depends on whether node logs from before 10-07 contain GET-resolution timings. If not, L* is set only in WP-0(c-late).
- **(4) A5's activation date is an estimate.** About 12-16..12-18 depends on when AUT-5a merges, which is unknown.
