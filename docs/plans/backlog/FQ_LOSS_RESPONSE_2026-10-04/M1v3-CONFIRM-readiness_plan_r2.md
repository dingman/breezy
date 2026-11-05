# M1v3-CONFIRM-readiness plan r2 (draft, 2026-10-09)

**Status:** DRAFT r2. It applies all 21 merged amendments from round 1. In round 1 the architect scored 84, security 78, python 78 and market-math 78, all REVISE. Round 2 goes back to the same four reviewers.
**Plan of record:** `/home/jon/breezy/docs/evidence/DECISION_ROI_ROUTE_TO_TRADING_2026-10-09.md`, ranking item 2.
**Governing rulings:**
- `/home/jon/breezy/docs/evidence/RULING_FQ-v2-NO-TRADE_2026-10-08.md` (T1/T2/T3)
- `/home/jon/breezy/docs/evidence/RULING_B3_permit_window_posture_2026-09-25.md`
- `/home/jon/breezy/docs/evidence/RULING_permit_daily_coverage_2026-09-25.md`
- operator directive of 2026-09-29: prediction comes from US weather; venue prices are execution cost only
- the two operator caps, already set in `operator.env` and never assigned here

**Hard rules for every work package and every brief:**
- No tape, settlement or truth outcome for climate days **2026-10-07..2026-11-28** is read before the frozen tool's single read on or after 2026-12-07.
- `/home/jon/breezy/docs/evidence/m1v3/PREREG.json` is never edited.
- Nautilus Trader is immutable.
- `allow_short` stays False.
- No safety, settlement, contract or firewall test is weakened. A guard whose shape changes is narrowed and security-reviewed.
- No operator-reserved control is read, assigned or named by value.
- Briefs give the exact interpreter path and PYTHONPATH, and say "format only your files". `uv sync` is never run.

## 0. Verified facts and the corrected critical path

| # | Fact | Evidence (full paths) |
|---|---|---|
| V1 | The prereg froze at `frozen_sha` adb1cd8b, committed 2026-10-06T10:50:42Z. That fixes `first_forward_day` 10-07, `last_forward_day` 11-28, `read_date` 12-07 and the truth deadline 12-21. Window D_12Z: the first Depth10 row in [12:00, 13:00)Z; NO ask = 1 − best YES bid; take iff ask ≥ 0.90, inclusive. Cost = max(rounded fee, θ·a·(1−a)) + 1¢, θ = 0.0695. Incomplete station-days are excluded whole. | `/home/jon/breezy/docs/evidence/m1v3/PREREG.json` |
| V2 | `PREREG.lane` (M1V3-R1) allows a WINNER only as a filter on top of a weather-sourced NO decision, so §A must override it. | same file, `lane` field |
| V3 | **The closed set of composition kinds has mirrors in many places.** Every one must widen by exactly one row: | |
| | (a) `CompositionKind` / `_COMPOSITION_KINDS` | `/home/jon/breezy/src/breezy/persistence/family_manifest.py:116-121` |
| | (b) `COMPOSITION_KIND_SUBSCRIBED_MARKERS`, pinned in `/home/jon/breezy/tests/unit/test_app_trade_boot_family_log.py:217` and `/home/jon/breezy/tests/unit/test_forecast_quantile_ladder_manifest_and_markers.py:64` | `/home/jon/breezy/src/breezy/runtime/trade_supervisor_core.py:164` |
| | (c) `NODE_PLUGINS`; `/home/jon/breezy/tests/unit/test_autonomy_plugins.py:198` requires it to equal `OFFLINE_PLUGINS` and `_COMPOSITION_KINDS` | `/home/jon/breezy/src/breezy/strategy/autonomy/node_plugins.py:13` |
| | (d) `OFFLINE_PLUGINS` ("exactly the four composition kinds") | `/home/jon/breezy/src/breezy/analysis/autonomy/offline_plugins.py` |
| | (e) the set kept equal to `_COMPOSITION_KINDS`; `MODEL_CLASS_RE` at `:29` is a regex, not a set, so it needs only a match check | `/home/jon/breezy/src/breezy/persistence/autonomy/paths.py:28` |
| | (f) `HALTABLE_COMPOSITION_KINDS` | `/home/jon/breezy/src/breezy/strategy/current_rung_hold/family_id_arg.py:20` |
| | (g) `LIVE_GATE_ROUTED_KINDS`, consumed by `_is_routed` ("Only a kind in LIVE_GATE_ROUTED_KINDS can send") at `/home/jon/breezy/src/breezy/persistence/autonomy/resolver.py:462`; pinned in `/home/jon/breezy/tests/unit/test_autonomy_pins.py:117` and `/home/jon/breezy/tests/unit/test_detector_catalog.py:85` | `/home/jon/breezy/src/breezy/persistence/autonomy/pins.py:28` |
| | (h) the existing pin tests | `/home/jon/breezy/tests/unit/test_forecast_quantile_ladder_manifest_and_markers.py:41-46`, `/home/jon/breezy/tests/unit/test_autonomy_paths.py:139-142` |
| V4 | `_LIVE_ORDERS_ALLOWLIST` is a code literal of 3-tuples. The ruling copy lives under `/home/jon/breezy/deploy/families/rulings/`, byte-identical to the evidence copy, and is sha-pinned. | `/home/jon/breezy/src/breezy/persistence/live_orders_gate.py` |
| V5 | The AST guard permits one non-True `shadow_only` expression, `not live_orders.enabled`. It is path-scoped to `/home/jon/breezy/src/breezy/app/trade.py`, where it appears once, at `:848` in `_compose_forecast_quantile_ladder` (`:676`), with the gate call at `:740`. Dispatch is at `:906-955`. `trade.py` is 1274 lines, which is oversize (> 800). | `/home/jon/breezy/tests/unit/test_shadow_only_false_is_only_the_gate_output.py` |
| V6 | **The permit gap.** The schedule constants are STOP_PRIOR 16:40, LAUNCH 16:50 and SELF_CHECK 17:05 (`trade_supervisor_core.py:37-39`), plus RELAUNCH_CUTOFF 17:00 (`:40`). `B1_WINDOW_OPEN_UTC` equals `SELF_CHECK_WINDOW_END_UTC` (`:139`). The first-boot permit-expiry latch is at `:1082`/`:1395-1404`. The trading-day rollover at STOP_PRIOR is `_trading_day` (`:1188-1197`), and `midday_watch_window_end` is at `:1205`. The permit TTL is 10 h, so a single mint covers 16:50Z–02:50Z. D_12Z falls inside the gap, and RULING_B3 §6 requires (a′) to be re-opened at registration. | `/home/jon/breezy/src/breezy/runtime/trade_supervisor_core.py` |
| V7 | **Outside the supervisor, these consume the 16:50Z schedule:** | |
| | `SCHEDULE_STOP_UTC`, `SCHEDULE_LAUNCH_UTC` and `SCHEDULE_LAUNCH_WINDOW_END_UTC`, kept test-equal to the core constants | `/home/jon/breezy/src/breezy/persistence/autonomy/pins.py:121-125` |
| | users of those strings | `/home/jon/breezy/src/breezy/persistence/autonomy/fold_pairs.py:120`; `/home/jon/breezy/src/breezy/persistence/autonomy/validate_ii.py:149` (and the 16:50 cancel semantics at `:378-380`; the amendment cites `:488`, which WP-0(e) re-verifies); `/home/jon/breezy/src/breezy/runtime/autonomy_sandbox/wal_snapshot.py:553` |
| | FQ analyses | `/home/jon/breezy/scripts/analysis/nbp_shadow_parity_pure.py:45,153` (imports `LAUNCH_UTC`); `/home/jon/breezy/scripts/analysis/nbp_market_comparison.py:321` |
| | the tally timer | `/home/jon/breezy/deploy/systemd/breezy-family-tally@.timer:29` (`OnCalendar 17:20 UTC`) |
| | comments or log fixtures only, no action | `/home/jon/breezy/src/breezy/strategy/current_rung_hold/continuous_strategy.py:1029`, `/home/jon/breezy/src/breezy/strategy/current_rung_hold/continuous_helpers.py:138`, `/home/jon/breezy/src/breezy/runtime/quote_tape_ingest_cli.py:183`, `/home/jon/breezy/scripts/analysis/discovery_set_equality.py:75,130` |
| V8 | **Submit-intent latch.** There is a single intent. `arm` refuses while any intent is OPEN, and a corrupt ledger counts as latched. | `/home/jon/breezy/src/breezy/runtime/submit_intent.py:386-422` |
| V9 | **The loss-floor MC hard-codes its design.** `DELTAS`, `_EPOCH_FIXED`, `DEFAULT_FREEZE` and `HORIZON` are constants in `/home/jon/breezy/scripts/analysis/fq_loss_floor_mc_gate.py:55-63`. `MIXES` is defined in `/home/jon/breezy/scripts/analysis/fq_loss_floor_mc_engine.py:56` and imported by `fq_loss_floor_mc.py`, `fq_loss_floor_mc_report.py`, `fq_loss_floor_np_bound.py` and `fq_loss_floor_mc_outer.py`. `apply_mix` rejects any mix name it does not know (`/home/jon/breezy/scripts/analysis/fq_loss_floor_mc_rows.py:249-256`). For a NO leg, `cell_q = 1 − be` (`:144-150`), and `make_leg` requires 0 < be < 1 (`:86`). Under H1 the win probability is `be − |δ|` (`:310`). The α ladder, the 2.5 multiplier and `T_MIN_GRID` are at `/home/jon/breezy/src/breezy/analysis/fq_loss_stop_core.py:47-51`. | source |
| V10 | **The F6 loss stop has no producer.** While the artefact is absent the probe reads UNKNOWN, which vetoes; the path is a constructor argument (`/home/jon/breezy/src/breezy/strategy/forecast_quantile_ladder/loss_stop_probe.py:118`). The writer guard scans only `fq-loss-stop` and the `breezy-fq-loss-stop.` prefix, and loads only FQ's A1 amendment (`/home/jon/breezy/tests/contract/test_fq_loss_stop_writer_allowlist.py:35-59`). | source |
| V11 | The node's stations are LAX, MDW, MIA and SFO (`/home/jon/breezy/src/breezy/strategy/current_rung_hold/config.py:76`). The PM.us surface has five cities, the fifth being NYC. Subscriptions are sharded across connections (`/home/jon/breezy/src/breezy/adapters/polymarket_us/factories.py:658-680`). | source; memory |
| V12 | AUT-5 owns `trade.py`, `settings.py` and `trade_supervisor*.py`. AUT-5a adds the registry boot path and the FQ `entry_veto` slot. | `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/AUT-5-promotion-demotion_plan_r7.md:410-414,891,979` |

**The critical path is items 1–7 plus item 8, the permit window (WP-4).** Moving the decision to D-1_18Z to escape the gap is prohibited (§A.3(a)).

## A. DRAFT ruling (item 1): `RULING_M1v3-CONFIRM-T2-SENDER_<ratification-date>`. Draft only; not in force.

**Ratification requires all four of:**
- (i) a WINNER read, as defined in A.1;
- (ii) the §B floor frozen, with a binding PASS before 12-07;
- (iii) the WP-4 B3 re-open ruling committed;
- (iv) peer convergence from trading-bot-architect, prediction-market-reviewer and security-reviewer.

A draft has no force. It is never cited by an allowlist row or by a manifest's `live_orders_ruling` field.

### A.1 Condition

All of these must hold:
- the report of `/home/jon/breezy/scripts/analysis/no_longshot_pooled_test.py`, run at a HEAD descended from adb1cd8b, is committed under `/home/jon/breezy/docs/evidence/m1v3/`;
- its status is READ;
- `verdict == "WINNER"`;
- `bca_failed` is not true.

The ratified text pins that report's sha256. **CONFIRM means exactly this, and nothing else.**

### A.2 Ruled, on CONFIRM

1. **The sender.** `pm_us_nolong_d12_v1`, composition kind `no_longshot_d12`, is a permitted T2 sender under RULING_FQ-v2-NO-TRADE T2, with §B as its own floor prereg.
2. **M1V3-R1 is superseded for this family only.** Its "filter on a weather-sourced decision" sentence no longer limits sender eligibility for `pm_us_nolong_d12_v1`. The AS-R6 part of M1V3-R1 remains in force.
3. **Reconciling the operator directive of 09-29.** That directive is about circularity: both edge terms coming from venue prices.
   - In M1-v3, the outcome term is the NWS CLI FINAL value and the venue price enters only as cost, so the circularity objection does not apply.
   - The *letter* of the directive is still breached, because the price level selects the take. That breach is accepted as a narrow exception for this one family, adjudicated by the peer loop and not escalated.
   - **If any peer rejects this reconciliation, §A.5 applies.**
4. **The population.** It is pinned now, and frozen by **2026-11-20**: the station set goes into the §B prereg and into this text at the same commit. It is D0 only, at the first Depth10 update the node receives with `ts_event` in [12:00, 13:00)Z for each YES rung. The NO ask is `1 − best YES bid` (size ≥ 1). The family takes iff NO ask ≥ 0.90 inclusive, over the full [0.90, 1.00] range: BUY NO, qty 1, IOC, limit = that NO ask. Each (station, D, rung) is evaluated once and held to settlement. Stations are LAX, MDW, MIA and SFO, plus NYC only if WP-0(a) shows NYC is node-supported by 11-20. A6 lists the residual differences from the screen.
5. **Gates.** All of these apply:
   - the permit;
   - the live-orders gate, with an exact allowlist row;
   - the family halt latch;
   - the fee-drift probe;
   - the family loss stop (§B, WP-5);
   - the submit-intent latch, under the policy in WP-1;
   - kill rules K1–K6;
   - both operator caps, unchanged and enforced natively.
6. **K4 formula, pinned here.** Let C_d be the number of node-evaluated rungs on trading day d whose first in-window NO ask is ≥ 0.90, counted from the decision funnel. C_d does not depend on fills, the latch or caps. Let λ₄ and the dispersion k be the pre-window mean and the negative-binomial dispersion of the same per-day count, computed on climate days 08-30..10-06 for the pinned stations and pinned in the §B prereg. Over each completed block of 14 trading days, compute S = ΣC_d. **K4 trips** iff both of these hold:
   - the two-sided NB(14·λ₄, k) tail probability of S is < 0.01;
   - S / (14·λ₄) lies outside [0.5, 2.0], a band that absorbs seasonal level shifts.

### A.3 What the M1-v3 result may NOT be used for

- **(a)** Trading any other window: D-1_18Z, D_17Z or any other.
- **(b)** Trading a sensitivity cell instead of the primary: an ask sub-band, slippage 0 or 2¢, or a rounded-only or unrounded-only fee.
- **(c)** Adding unscreened filters: depth, time of day, weather, or a station choice made after the read.
- **(d)** Serving as evidence for FQ v2, any forecast family, any model variant, the AUT-S ledger or `screen.py`.
- **(e)** Claiming an edge size. The only figure cited is the one-sided lower bound, never the point estimate.
- **(f)** Re-reading, re-running or extending the screen, or relabelling UNDERPOWERED or PENDING_TRUTH.
- **(g)** Changing qty or either operator cap.
- **(h)** Trading any side other than BUY NO.
- **(i)** Trading any venue other than Polymarket.us.
- **(j)** Choosing the floor epochs, horizon or activation date after the read. Activation after 2027-01-20 means shelve.
- **(k)** Bypassing a FAIL or unrun §B floor.

### A.4 Relationships

- RULING_FQ-v2-NO-TRADE stays in force for FQ v2.
- B3 (a′) is decided by the separate WP-4 ruling, not by this one.

### A.5 Any outcome other than CONFIRM

This covers NO-EDGE, UNDERPOWERED, INVALID, PENDING_TRUTH still open past 12-21, a §B FAIL, an unratified WP-4 ruling, and a peer rejection of A.2.3. In every such case **the build is shelved**:
- the manifest stays `DRAFT_NOT_REGISTERED`, or is removed by a reviewed commit;
- no allowlist row is added;
- the code is inert, with no REGISTERED manifest and no row;
- the drop-in `fq-v1-halt-orders-off.conf` stays;
- nothing goes live.

The verdict is recorded in PROGRESS (M1V3-R11). Any re-test needs a new prereg and a new plan.

### A.6 Parity between the screen (PREREG) and the live family (disclosed)

| Dimension | Screen | Live family | Disclosure |
|---|---|---|---|
| Window and selector | First tape Depth10 row in [12, 13)Z | First Depth10 update the node receives in [12, 13)Z | WP-0(d) is a hard precondition, with recorder-vs-node parity measured. |
| Incomplete station-day | Excluded whole if any listed rung lacks Depth10 (MNAR) | Takes per rung regardless | K4b reports the share of live takes on station-days the screen would exclude. |
| Truth availability | Excludes station-days without FINAL truth | Not knowable at decision time | Reported at settlement. |
| Empty YES bid side | Counted, no take | Same: no NO ask, no take | Parity. |
| Execution | Blind: fill at the ask assumed | IOC at the ask; misses, latch drops and AMBIGUOUS outcomes | K3 fields; the live population is a time-ordered subset (WP-1 latch policy) and cap-truncated. |
| Stations | All stations on the tape | The pinned set | NYC decision by 11-20. |
| Fee | max(rounded, unrounded) | Venue-charged | WP-1 fee-grid pin; the fee probe is the tiebreaker. |

## B. Loss-floor MC/NP design for `pm_us_nolong_d12_v1` (item 4)

**Schedule:**
- The prereg is `/home/jon/breezy/docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04/NOLONG_D12_floor_prereg.json`, frozen by a dedicated commit **on or before 2026-11-20**.
- The binding run is 11-21..11-27: one heavy job at a time, under a memory cap, with RuntimeMaxSec and a no-progress watch.
- The result is committed before 12-06.
- The verdict binds either way. A FAIL cancels the 11-28 build.

### B.1 Pre-declared design

| Element | Value |
|---|---|
| Mix | Reuse **`M-no`**, over a pool built only from NO legs with ask ≥ 0.90 at the D_12Z first row, for the pinned stations. No new mix name, and `MIXES` is unchanged. The NYC-inclusive pool is an informational sensitivity, never selected. |
| Data source | PM.us Depth10 tape for climate days **2026-08-30..2026-10-06**, filtered on the directory index before any read. The tool refuses (exit 3, nothing written) if any day ≥ 10-07 reaches a reader. Truth is read only for days ≤ 10-06, and only if `rho_hat` needs it. |
| Leg break-even | `be = ask + max(venue_fee(ask), θ·a·(1−a)) + 0.01`, θ = 0.0695, the same as the screen. **A leg with be ≥ 1** (asks of about 0.98–0.99) cannot be represented by `make_leg`. Such legs are excluded from the MC and counted, which removes ticks and so understates power. Live, those legs are still taken (A.2.4). |
| Feasibility | For NO legs, `cell_q = 1 − be ≤ 0.10`, so Σq ≤ 1 for any station-day with at most 10 legs. That makes the pool feasible under `s6_station_days` by construction. Station-days with more than 10 legs, or Σq > 1, are counted. If they exceed 5% of station-days, the verdict is FAIL (pre-declared). |
| α ladder | `ALPHA_FLOOR_GRID` = (0.10, 0.20, 0.30), imported. Escalation looks at G1 only. A G3 miss is a veto, never a reason to escalate. |
| δ grid | (−0.16, −0.08, −0.04, −0.02). **The bar is at δ = −0.04.** This is a **different** bar from FQ's −0.16, not a stricter one: it is sized to a payoff of at most 10¢. **Drift between 0 and −4¢ per take is not protected by the stop.** Protection there rests on the CONFIRM lower bound, K5 and the horizon. −0.02 is informational. |
| Epochs and horizon | Epochs {**2026-12-23, 2027-01-06, 2027-01-20**}; horizon **2027-02-28**, which is also `terminal_climate_day`. The floor must hold at every epoch. No epoch precedes the read; PENDING_TRUTH may run to 12-21. An activation before 12-23 sees a longer horizon than the 12-23 epoch, so the 12-23 result is conservative. Activation after 01-20 means shelve. |
| G-gate bar | G1 holds, and G3(−0.04) ≥ 2.5·α at the selected α, at every epoch. |
| D1-analogue bar | The NP upper bound on G3(−0.04), at the boundary's effective α, is ≥ 0.30 at every epoch, with `e_proj` = 2027-01-20. Switching to nominal α is prohibited (r2.1 C-7). |
| Seeds | Floor (A1 analogue) seed 20261121; Stage 0 seed 20261122; 10k replicates each. |
| Sensitivities | Informational only: takes/day scaled to ±50% (thinning or duplication of pool days, pre-declared); the NYC-inclusive pool. |
| Stage −1 | Descriptive and committed before Stage 0: path-tick distribution per epoch, λ₄ and k (for K4), legs per station-day, ask-bin composition (for K5), the be ≥ 1 exclusion count and the Σq count. No verdict comes from Stage −1. |
| Freeze check | `check_frozen_blob`, plus the M1V3-R26-style rule that `frozen_sha` must be the commit that introduced the blob, from `/home/jon/breezy/scripts/analysis/prereg_precommit_check.py`. |
| Amendment shape | The result is serialised in the schema read by `/home/jon/breezy/scripts/analysis/prereg_amendment_check.py` (`load_verified_amendment`, `reachable_floor`), so WP-5's guard can test reachability. If that loader is FQ-specific, WP-5 adds a per-family loader. |

### B.2 Path argument: a hypothesis, to be tested by Stage −1 and Stage 0

FQ v2 failed D1 on short paths:
- the M-yes median was about 7 ticks;
- α_eff was 0.0187 and the NP bound 0.1186;
- `bound_upper_min` was 0.125 against a bar of 0.30;
- A1's G3(−0.16) in M-yes was 0.2104 against 0.25;
- M-no passed NP at 0.4927 on 11-01, but its G3 at 12-01 was 0.2334 because only 56 days of horizon remained.

For this family:
- M1 D_12Z showed about 11.7 takes per day over 5 stations, or about 9.4 per day over 4.
- From the last epoch (01-20) to the horizon (02-28) there are 39 days. At about 3.5 station-days with takes per day, that is about 135 ticks, roughly 20× FQ's M-yes.
- Detection: with per-take SD ≈ 0.20, δ = −0.04 needs n ≈ (2.5·0.20/0.04)² ≈ 156 takes, about 17 days, which fits inside 39.
- Mutual exclusivity bounds the variance per station-day.

**Counter-hypotheses:**
- A single loss at a ≈ 0.97 costs about 0.97, so the normal approximation may be poor. The NP bound measures this directly.
- The winter ask mix may differ from the pre-window mix (see K5).
- Excluding be ≥ 1 legs lowers the number of ticks.

### B.3 Tooling (WP-A, scripts only). Built 11-09..11-19, before the freeze.

- **Golden files first.** Commit `/home/jon/breezy/tests/fixtures/fq_floor_golden/` with seed-20261008 A1 and seed-20261009 Stage-0 subset outputs, produced at the current HEAD **before** any refactor. Commit them in a separate commit so the tests below compare against something real.
- **`McDesign` injection** (deltas, epochs, freeze, horizon). Added as keyword-only arguments, with defaults equal to today's constants, in `fq_loss_floor_mc_gate.py`, `fq_loss_floor_mc_engine.py`, `fq_loss_floor_mc_report.py` and `fq_loss_floor_np_bound.py`. **`/home/jon/breezy/scripts/analysis/fq_loss_floor_mc.py` is not edited**, because its blob hash is recorded in the F5 evidence. The new driver calls the engine directly. Mixes are not part of `McDesign`.
- **RED tests:**
  - `test_fq_design_default_matches_golden_a1_subset`
  - `test_np_bound_default_matches_golden_stage0_subset`
  - `test_fq_loss_floor_mc_py_blob_unchanged`
- **New `/home/jon/breezy/scripts/analysis/nolong_d12_mc_templates.py`** (under 300 lines). It builds `StationDay`/`Leg` (side `no`) from the screen's helpers (`_first_row`, `no_ask`, `venue_fee`), which are imported and not modified. **RED tests:**
  - `test_refuses_climate_day_on_or_after_2026_10_07`
  - `test_date_filter_precedes_any_tape_read`
  - `test_be_uses_screen_primary_cost`
  - `test_be_ge_one_excluded_and_counted`
  - `test_pool_all_legs_side_no_ask_ge_090`
  - `test_pool_feasible_sum_cell_q_le_one`
  - `test_d12_first_row_only`
  - `test_no_ask_none_counted_not_synthesised`
- **New `/home/jon/breezy/scripts/analysis/nolong_d12_floor.py`** (under 200 lines), the driver. **RED tests:**
  - `test_refuses_unfrozen_prereg`
  - `test_no_nominal_alpha_path_after_result`
  - `test_epoch_holds_required_at_every_epoch`
  - `test_h0_h1_at_most_one_losing_leg_per_station_day`: each replicate is a single multinomial draw over k+1 outcomes.
  - `test_sensitivity_takes_rate_pm50_informational_only`
- **Gate:** focused tests; the mypy ratchet; `lint-imports` run from the tree root, which must print "N kept, 0 broken"; then the full gate via `/home/jon/breezy/scripts/ci/run_tests_no_egress.sh` with `--basetemp` under `~/.cache`.
- **Effort:** 3 d of build, 1 d of review, and about 1 h of gate time.

## C. Code work packages

### WP-0 Verify-first (read-only, 1 d)

**Hard blockers:** (b), (c) and (d).

- **(a) NYC support.** Check the registry settlement site, climate-day window and truth feed. The decision goes into the §B prereg **by 11-20**.
- **(b) AUT-5a state.** Find out whether the registry boot path is mandatory.
  - If it is, the family must be added to `LIVE_GATE_ROUTED_KINDS` (V3g), and `pins.SCHEDULE_*` plus `fold_pairs.py`, `validate_ii.py` and `wal_snapshot.py` must follow the per-family schedule. That adds +3 d to WP-6.
  - If the env family source remains, `LIVE_GATE_ROUTED_KINDS` stays unwidened and the family boots from env (the default assumed below).
- **(c) Submit-intent latch.** Confirm the resolve and retire mechanics behind `/home/jon/breezy/src/breezy/runtime/submit_intent.py:386-422`, the AMBIG-LATCH B activation state, and the GET-resolution latency. If retirement cannot be bounded at or below 60 s, the family's take share collapses: **STOP and report**.
- **(d) First-row parity.** Measure the recorder's Depth10 emission rule (snapshot or change-only) against the node's first in-window update, using a **post-2026-11-28** recorder sample and a node run in a scratch shadow. Parity must hold for ≥ 95% of rung-days, or **STOP**.
- **(e) Other mirrors.** Grep `forecast_quantile_ladder` and `forecast_ladder` across `/home/jon/breezy/src` and `/home/jon/breezy/tests` for any closed-set mirror not in V3, and re-verify `validate_ii.py:488`.
- **(f) Venue translation.** Confirm the NO-leg order path reuses the FQ venue translation (a NO buy is sent as SELL/BUY_SHORT of YES). Identify which firewall/exec-import pin needs a WIDENED row for the new strategy module; the candidate is `/home/jon/breezy/tests/contract/test_us_source_ingest_egress_guard.py:608`.

### WP-1 Strategy: `/home/jon/breezy/src/breezy/strategy/no_longshot_d12/` (3.5 d)

**Files:**
- `config.py`, with `shadow_only: bool = True`;
- `decision.py`, which is pure: first-row selection, NO ask, the take rule and the latch key;
- `strategy.py`, using native Nautilus `subscribe_order_book_depth`, an IOC `order_factory.limit` and `submit_order`, and reusing `PersistentQuantileLadderLatch` and `open_trial_day_latch` with its own key prefix;
- `composition.py`.

**Latch policy, pre-declared:**
- Orders go out one at a time: arm, then POST, then retire.
- A candidate evaluated while an intent is OPEN is **dropped and counted** (`latch_dropped`). It is never queued, because a later book is a different population.
- After an AMBIGUOUS response, GET-resolve at 2, 5, 10, 20 and 30 s, a 67 s ceiling.
- The digest carries `candidates`, `attempted`, `filled`, `zero_fill`, `latch_dropped`, `ambiguous_resolved` and `ambiguous_open`.

**RED tests:**
- `test_decision_parity_with_m1_selector_on_fixtures`: equality with `market_calibration_scan._first_row` and `no_ask`, with fixture count ≥ 30 asserted non-empty, using pre-window fixtures only.
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
- `test_ambiguous_get_retire_bounded`
- `test_try_submit_order_permit_veto_fee`
- `test_no_order_when_shadow_only`
- `test_fee_grid_live_vs_screen` on asks {0.90, 0.91, …, 0.99}. Expected values come from `venue_fee` and the unrounded formula. For example, at a = 0.95 the half-even rounded fee is 0.00 and the unrounded fee is 0.0033, so the screen uses 0.0033. The test pins which fee the live accounting and the WP-5 producer use (the screen primary, which is conservative). The fee-drift probe is the tiebreaker.
- The WIDENED exec-pin row for `src/breezy/strategy/no_longshot_d12/strategy.py`.

**Replay check (not RED):** a BacktestEngine run over **pre-window** days 08-30..10-06 must reproduce ≥ 99% of the m1 take set, with mismatches listed.

### WP-2 Composition kind, dispatch and guards (item 2, 3 d)

**Mirrors.** Widen every V3 site by one row, with one RED test per site:
- `test_composition_kinds_widened_by_exactly_nolong`
- `test_subscribed_marker_map_has_nolong`, which updates both pins
- `test_node_plugins_equal_offline_plugins_equal_kinds`
- `test_autonomy_paths_kinds_mirror_and_model_class_re_matches`
- `test_haltable_kinds_include_nolong_exit_kinds_unchanged`
- `test_live_gate_routed_kinds_unchanged`, or `…_widened` if WP-0(b) requires it.

**`trade.py` keeps only the gate site.**
- New `/home/jon/breezy/src/breezy/app/compose_no_longshot.py` holds all the non-gate logic: the halt-latch preamble call, `LossStopProbe(path=<nolong path>)`, the composed veto (halt, then loss stop; parity None), the fee probe, the funnel actor, and a builder that takes `shadow_only`.
- A new shared helper in `trade.py`, `_live_orders_gate_preamble(manifest, sending_permit)`, makes the `live_orders_authorized` call, logs the line and raises `SettingsError`. Both composers use it.
- `_compose_no_longshot_d12` in `trade.py` is about 20 lines: helper, then builder, then `shadow_only=not live_orders.enabled`.
- `trade.py` is recorded as oversize at 1274 lines. It is not refactored here, because AUT-5 owns it.

**AST guard: narrow + one reviewed site.** Changes to `/home/jon/breezy/tests/unit/test_shadow_only_false_is_only_the_gate_output.py`:
- The permitted sites become the exact set {(trade.py, `_compose_forecast_quantile_ladder`), (trade.py, `_compose_no_longshot_d12`)}, keyed by the enclosing `FunctionDef.name` via AST, with an exact count.
- In each function, `live_orders` must be bound exactly once, by an `Assign` from a call to `_live_orders_gate_preamble` or `live_orders_authorized`. Any re-binding is rejected: `Assign`, `AugAssign`, `AnnAssign`, walrus, a for/with target, or `del`.
- `test_the_permitted_expression_actually_appears_in_trade_py` now requires both sites.
- Positive controls: `test_expression_in_wrong_function_flagged`, `test_live_orders_bound_from_non_gate_call_flagged`, `test_live_orders_rebound_flagged`, `test_third_site_flagged`.
- Security sign-off is required.

**Dispatch tests:**
- `test_compose_family_dispatches_nolong`
- `test_fq_still_dispatches_to_fq_composer` (negative control)
- `test_unknown_kind_refuses_with_specific_settings_error_and_log_line`
- `test_gate_refusal_raises_settings_error_and_logs_reason`
- `test_nolong_loss_stop_path_distinct_from_fq`
- `test_draft_manifest_refuses_boot`

**Focused gate:** add the exec-pin and firewall guards, the operator-control scan, `test_node_composition_contract`, `test_native_order_cap_wiring`, all `test_autonomy_*`, the import gates, the citation map and `lint-imports`.

### WP-3 Manifest and allowlist (item 3, 0.5 d)

**Manifest.** `/home/jon/breezy/deploy/families/pm_us_nolong_d12_v1.json`:
- `DRAFT_NOT_REGISTERED`
- kind `no_longshot_d12`
- the pinned stations
- `taker_fee_coefficient` "0.0695"
- `terminal_climate_day` "2027-02-28"
- sentinel artefacts
- no `live_orders_ruling`

**RED tests:**
- `test_nolong_manifest_draft_refused_without_allow_draft`
- `test_live_orders_allowlist_is_exactly_fq_v1_row`: an exact-equality pin of the current one-row set. At activation (D.2) this is **replaced**, never deleted, by an exact-equality pin of the two-row set.

### WP-4 Per-kind schedule record (item 8, 6 d). The B3 re-open ruling must be committed before any code lands.

**The ruling** is a re-open of B3 (a′) as a per-kind single daily mint, countersigned by security-reviewer. It restates the clustering argument of RULING_permit_daily_coverage §4 and the daily reset of `first_boot_permit_expires_at_ns` at the per-kind STOP_PRIOR rollover.

**The code** is a frozen `KindSchedule` record and a code-literal table `SCHEDULE_BY_KIND` in `/home/jon/breezy/src/breezy/runtime/trade_supervisor_core.py`, selected by the sending manifest's `composition_kind`. It is never read from env or data. The default row equals today's values exactly, and the existing module constants remain as aliases of the default row.

| Field | Default (all existing kinds) | `no_longshot_d12` |
|---|---|---|
| STOP_PRIOR | 16:40 | 11:20 |
| LAUNCH | 16:50 | 11:30 |
| RELAUNCH_CUTOFF = LAUNCH_WINDOW_END (launch + 10 min) | 17:00 | 11:40 |
| SELF_CHECK | 17:05 | 11:45 |
| SELF_CHECK_WINDOW_END = B1_WINDOW_OPEN | 17:10 | 11:50 |
| `midday_watch_window_end` | 01:00 on trading day + 1 | 13:00 on trading day (end of the decision window) |
| `_trading_day` rollover | 16:40 | 11:20 |
| Nominal permit | 16:50–02:50 | 11:30–21:30 |

**Consumers outside the supervisor (V7):**

| Consumer | Decision | Reason |
|---|---|---|
| `nbp_shadow_parity_pure.py`, `nbp_market_comparison.py` | Stay fixed: they use the default alias | They are FQ-only analyses of FQ's permit window. |
| `pins.py:121-125`, `fold_pairs.py:120`, `validate_ii.py:149,378-380`, `wal_snapshot.py:553` | Stay fixed under the env family source; follow the per-kind schedule only if WP-0(b) forces registry routing (then +3 d, WP-6) | Their launch-dated registry semantics are anchored to 16:50, and the family is not registry-routed by default. |
| `breezy-family-tally@.timer` (17:20Z) | Stays fixed | It runs after the previous day's settlement for any schedule. A nolong instance timer is created only if the tally-scope ruling requires one. |
| Comment and log-fixture sites | No change | Not consumers. |

**RED tests:**
- `test_default_kind_schedule_identical_to_all_constants_and_consumers`: every default field, every alias, `pins.SCHEDULE_*` and both nbp imports unchanged.
- `test_nolong_permit_covers_12_13Z`
- `test_nolong_union_permit_coverage_bounded_over_all_relaunch_paths`: the union over the first boot, boot-window relaunches (≤ 2, gap 3 min, before 11:40) and mid-day relaunches (≤ 3, capped by the first-boot expiry) is ≤ 10 h 10 min and lies inside [11:30, 21:40].
- `test_first_boot_expiry_resets_at_kind_stop_prior`
- `test_kind_switch_midday_waits_for_next_stop_prior`
- `test_schedule_not_env_overridable`
- `test_single_mint_per_day_nolong`

**Ownership:** AUT-5 owns this file (WP-6).

### WP-5 Hold, loss stop, and demotion/kill (item 5, 3.5 d)

**Hold.** Positions are held to settlement; `KINDS_WITH_EXIT_PATH` is unchanged. Reconciliation applies the NO-leg sign (the venue nets a NO holding as short YES).

**Producer.** A new oneshot `breezy-nolong-loss-stop` service and timer. It replays `fq_loss_stop_core.step_clock` with the §B-selected boundary over this family's settled fills and FINAL truth, and writes `loss_stop/v1` to `$DATA/derived/nolong-loss-stop/latest.json`.
- **No default PASS, ever.** Until the producer's first evaluated run, the artefact is absent, so the probe reads UNKNOWN and vetoes.
- At n = 0, the first PASS must be computed: a digest over the verified-empty fill ledger plus the truth sha.
- **Flagged contradiction for round 2.** The amendment "seed UNKNOWN at n=0" taken literally means the family can never place its first order, because UNKNOWN vetoes. r2 interprets it as "no seeded PASS; an evaluated-empty PASS is allowed". Security-reviewer must confirm that reading or name an alternative.

**Guard reshape** (security-reviewed: the scan is widened and permissions narrowed) in `/home/jon/breezy/tests/contract/test_fq_loss_stop_writer_allowlist.py`:
- tokens become (`fq-loss-stop`, `nolong-loss-stop`);
- unit prefixes become (`breezy-fq-loss-stop.`, `breezy-nolong-loss-stop.`);
- `_AMENDMENT_FILES` becomes per-family and is loaded with a reachable check per family;
- exactly one nolong writer row is added, valid only while the nolong amendment reports `reachable_floor` True.

Positive controls:
- `test_planted_nolong_token_writer_flagged`
- `test_planted_nolong_unit_flagged`
- `test_nolong_writer_row_refused_when_floor_unreachable`
- `test_fq_scan_unchanged`

Producer tests:
- `test_producer_digest_recomputable`
- `test_producer_never_writes_default_pass`
- `test_producer_refuses_other_family_fills`
- `test_missing_artefact_vetoes`
- `test_fail_sets_family_halt_set_only`

**Pre-declared demotion and kill rules.** All act through the set-only family halt, and none re-arms; re-arming needs a new plan. K3–K6 are computed by `/home/jon/breezy/scripts/analysis/decision_funnel_daily_digest.py`, which pages; the coordinator applies the halt the same day. Each threshold has its own test: `test_k3_thresholds`, `test_k4_formula_nb_block`, `test_k4_not_tripped_by_cap_truncation`, `test_k5_ask_bin_drift`, `test_k6_unresolved_ambiguous_halts`.

- **K1.** Loss-stop FAIL. Terminal.
- **K2.** Fee-drift mismatch. Halt, as today.
- **K3. Execution, on resolved outcomes only.** The denominators are `attempted` (armed), with `filled`, `zero_fill` and `ambiguous_resolved` as the outcomes, and `candidates` (WP-1). Price improvement means `fill_px < limit`. An IOC limit can only fill at or better than the limit, so a fill at a worse price is a venue defect: an immediate halt plus an evidence report. Once attempted ≥ 30, halt if either holds:
  - filled / attempted < 0.50;
  - latch_dropped / candidates > 0.30.
- **K4. Population.** The formula in A.2.6. **K4b** is a reported field: the share of live takes on station-days the screen would have excluded. A review flag is raised above 0.20; it is not a halt.
- **K5. Ask-bin drift.** Over 14-day blocks, a χ² test of the live candidate ask-bin composition ([0.90, 0.92], [0.93, 0.95], [0.96, 1.00]) against the pre-window composition from Stage −1. Halt if p < 0.001 and n ≥ 60.
- **K6.** Any AMBIGUOUS still OPEN at 13:00Z, the window close, triggers a halt. Retirement needs venue evidence.
- **K7.** `terminal_climate_day` 2027-02-28.

### WP-6 Merge order with AUT-5a (item 6; 1.5 d, or 4.5 d if WP-0(b) forces registry routing)

- **If AUT-5a has merged:** rebase WP-2 and WP-4 onto it, adopt its manifest-object signature, add a registry bootstrap row if it is needed, and add an `entry_veto`-equivalent slot if AUT-5a makes one mandatory for every kind.
- **If it has not:** WP-2 and WP-4 land first as small diffs, and the coordinator sequences AUT-5a's rebase.
- **In both cases:** run the full gate after every merge, read `GATE_EXIT` before any push, and use worktrees fast-forwarded first with PYTHONPATH set.

### C.7 Effort and schedule (realistic)

| WP | Build | Review cycles | Gate time (25 min per merge) |
|---|---|---|---|
| WP-A | 3 d | 1 d | 1 merge |
| WP-0 | 1 d | — | — |
| WP-1 | 3.5 d | 1 d | 2 merges |
| WP-2 | 3 d | 1 d (incl. security) | 2 merges |
| WP-3 | 0.5 d | — | 1 merge |
| WP-4 | 6 d (incl. the ruling) | 1.5 d (incl. security) | 2 merges |
| WP-5 | 3.5 d | 1 d (incl. security) | 2 merges |
| WP-6 | 1.5 d (+3 d) | 0.5 d | 2 merges |

**Totals:** about 22 d of build plus about 7 d of review, about 24 agent-days with parallel review, plus about 6 h of serial gate time. The critical chain is WP-1 → WP-2 → WP-6, about 9 d.

**The 11-28..12-06 window (9 days) is infeasible as scheduled.**

**Proposal (coordinator decision):**
- **Early phase, 11-09..11-27.** Only packages that never read window data:
  - WP-A, which is required before 11-20 anyway;
  - WP-0(a), (b), (e), (f);
  - the WP-4 ruling and the default-identical refactor, which are reusable whatever the outcome;
  - WP-1 `decision.py` and its parity and fee tests on pre-window fixtures;
  - the WP-5 guard reshape.
- **Late phase, after the floor PASS on 11-27 (11-28..12-06):**
  - WP-0(c) and (d), using post-11-28 recorder data;
  - the WP-1 strategy;
  - WP-2, WP-3, the WP-5 producer, and WP-6.
- **If the floor FAILs on 11-27:** the early-phase work that is lost is mostly reusable (the WP-4 refactor, the floor tooling, the guard reshape).

## D. Activation runbook (item 7), on CONFIRM only

### D.1 Day 0: read

1. Run the frozen tool once, with no `--as-of`.
2. Commit the report.
3. If the verdict is not WINNER, apply §A.5 and stop.

### D.2 Day 0–1: ratify

4. Finalise the §A text, including the report sha and the §B and WP-4 ruling shas.
5. Run the peer loop.
6. Compute the ruling sha256 **after** the final text. Commit the evidence copy and a byte-identical `/home/jon/breezy/deploy/families/rulings/` copy.
7. In one reviewed commit:
   - add the allowlist row;
   - **replace** the WP-3 pin with an exact-equality pin of the two-row set;
   - set the manifest to `REGISTERED`, add `live_orders_ruling`, set `d0_climate_day`.
8. Run the full gate. Read `GATE_EXIT` before any merge or push.

### D.3 Day 1–2: shadow-only boot, with the drop-in still present

9. Commit `BREEZY_SENDING_FAMILY_ID=pm_us_nolong_d12_v1` to `/home/jon/breezy/deploy/systemd/breezy-trade-supervisor.service` **on a branch**. The file is symlinked live, so a commit on the primary tree is one daemon-reload from production. Merge only at `GATE_EXIT=0`.
10. Dry-run the changed unit: `systemd-analyze --user verify`, and `systemctl --user cat` to confirm the drop-in still overrides `BREEZY_ORDERS_ENABLED=0`.
11. Re-derived quiet window for supervisor restarts:
    - under the outgoing FQ schedule: 01:00–16:40Z, avoiding the 17:20Z tally overlap concern;
    - under the nolong schedule: **13:15Z–11:10Z**, which avoids STOP_PRIOR (11:20) through the mid-day watch end (13:00) and the B1 window that opens at 11:50.

    Restart within the window for the schedule that is active at that moment. `KillMode=process` keeps the node running. On the switch day the supervisor waits for the next 11:20Z STOP_PRIOR (`test_kind_switch_midday_waits_for_next_stop_prior`).
12. Next day at 11:30Z, verify:
    - the live-trading permit line shows an expiry ≥ 13:00Z (nominal 21:30Z);
    - the order-submission permit is absent with reason orders-not-requested, which SELF-CHECK-ORDERS-OFF classifies as `PASS_ORDERS_NOT_REQUESTED`;
    - `boot_family id=pm_us_nolong_d12_v1`;
    - the live-orders line shows `enabled=False reason=permit_absent ruling_sha256=<pinned>`;
    - shadow decisions logged in [12, 13)Z;
    - the loss-stop probe reads an evaluated artefact.

### D.4 Day 2–3: orders on

13. Remove `/home/jon/.config/systemd/user/breezy-trade-supervisor.service.d/fq-v1-halt-orders-off.conf` as a **reviewed act**: an evidence note citing the ruling, a one-line heads-up, and a scratchpad snapshot of the file first. Run `systemctl --user daemon-reload` and restart inside the quiet window.
14. **Operator items: none.** The two caps are already in `operator.env`; nothing reads, assigns or names them.
15. First trading day, using the bot's own evidence. Node evidence comes from its log files, never journald:
    - the boot-time order-submission permit line;
    - `enabled=True reason=ok`;
    - SELF_CHECK at 11:45Z returns PASS;
    - candidate, attempt, fill and drop counts;
    - every AMBIGUOUS resolved by 13:00Z (K6);
    - D+1 reconciliation with the leg sign;
    - digest K3–K5 fields populated;
    - liveness = process + log mtime + permit unexpired + tape advancing.

### D.5 Rollback, in order

1. Run the family-halt CLI with an absolute `--families-dir`.
2. **Read back** the halt: the halt row is present via the halt status read path, and the digest shows the family halted. The halt CLI already failed once, on 10-05, because of a cwd bug.
3. Stop the node explicitly via its systemd unit (`systemctl --user stop <node unit>`; never pgrep or SIGKILL).
4. Restore the drop-in from the snapshot, run daemon-reload, and restart the supervisor inside the quiet window.
5. Verify orders are not requested at the next boot.

## E. Risks

| # | Risk | Sev. | Mitigation |
|---|---|---|---|
| R1 | P(WINNER) is about 3% (§F). This is the dominant risk. | Dominant | Option value only. The build can be cancelled after the floor result on 11-27, and the early-phase work is reusable. |
| R2 | P(edge given WINNER) is only about 0.2–0.4. | High | Qty 1, K1–K7, the horizon. |
| R3 | **Selection bias and transport from a single window.** D_12Z, the 0.90 threshold and the NO side were all chosen after M1, with K=1 declared. D_12Z was M1's worst cell, which biases toward NO-EDGE. The forward window is Oct–Nov with about 40 day-clusters; live trading is Dec–Feb. The whole-station-day exclusion is MNAR. | High | §A.3 bans, the A.6 disclosures, K4/K4b/K5, winter-dated epochs. |
| R4 | The permit gap requires the WP-4 ruling and a supervisor refactor owned by AUT-5. | High | Ruling first; RED tests that the default schedule is identical. |
| R5 | Submit-intent latch: about 10 takes in one hour, one order at a time, so the live population is a time-ordered subset. | High | WP-0(c) hard blocker, the drop counter, K3/K6. |
| R6 | Recorder-vs-node first-row disparity. | High | WP-0(d) hard precondition. |
| R7 | Caps truncate the take sequence. | Med | Disclosed. K4 uses candidates, not fills. Caps are never changed. |
| R8 | A peer rejects the reconciliation with the 09-29 directive. | Med | §A.5. |
| R9 | The n=0 loss-stop contradiction stays unresolved, so the family cannot trade at all. | Med | Flagged for round 2. |
| R10 | WP-0(b) forces registry routing (+3 d). | Med | Early WP-0(b). |
| R11 | Window contamination by an agent. | High | Date filters before any read, RED tests, the restated ban in every brief, and WP-0(d) restricted to post-11-28 data. |
| R12 | Drift between 0 and −4¢ per take is unprotected by the stop. | Med | Disclosed; K5; horizon. |

## F. Expected value

**Probabilities.** By Bayes,

P(edge | W) = π·P(W | edge) / (π·P(W | edge) + (1 − π)·P(W | null))

The inputs:
- **Null WINNER rate.** With a true mean of −0.3¢ and SE ≈ 0.8¢, WINNER needs the estimate to exceed 1.645·0.8 = 1.32¢. So P(W | null) = P(Z > (1.32 + 0.3)/0.8 = 2.02) ≈ **2%**.
- **WINNER rate under a +1¢ edge.** P(W | +1¢) = P(Z > (1.32 − 1)/0.8 = 0.40) ≈ **34%**.
- **Posterior.** A prior of π = 3% gives 0.0102 / (0.0102 + 0.0194) ≈ **35%**. A prior of π = 2% gives about 26%. **P(edge | WINNER) ≈ 0.2–0.4.**
- **Overall P(WINNER)** ≈ 0.03·0.34 + 0.97·0.02 ≈ **3%**.

**Payoff.** At qty 1 with about 9 takes a day, a true +1–2¢ edge is worth about $0.10–0.20 a day, or $3–6 a month. Expected direct P&L is cents.

**Option value.** A ratified sender with a passing floor is the only route identified before 2027 that un-gates the live stages of AUTONOMY rows 7b and 8–12, and that produces real fills.

**Cost:**
- about 4 agent-days for WP-A, which leaves reusable floor tooling;
- about 20 more agent-days for WP-0..6, plus about 6 h of gate time, mostly spent only if the floor passes on 11-27;
- the WP-4 schedule record, the loss-stop producer pattern and the narrowed guards are reusable by any future sender.

**Recommendation.**
- Run WP-A and the read-safe early phase.
- Build the rest only after the floor PASS.
- Treat a CONFIRM as weak evidence, roughly a one-in-three chance of a real edge, that buys a deployed sender, not a demonstrated edge.
