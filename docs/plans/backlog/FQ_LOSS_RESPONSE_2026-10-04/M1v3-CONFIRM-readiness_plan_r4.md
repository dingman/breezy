# M1v3-CONFIRM-readiness plan r4 (draft, 2026-10-09)

**Status:** DRAFT r4. It applies the round-3 coordinator rulings R4-1..R4-17 to r3, which was committed at f05d2bc9 as `/home/jon/breezy/docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04/M1v3-CONFIRM-readiness_plan_r3.md`.

Round-3 scores, all REVISE: security 94, python 93, architect 94, market-math 94. The target is ≥ 95 from each.

r3 rulings stand unless they are changed here. §R4 maps every change.

**Plan of record:** `/home/jon/breezy/docs/evidence/DECISION_ROI_ROUTE_TO_TRADING_2026-10-09.md`, item 2.

**Governing rulings:**
- `/home/jon/breezy/docs/evidence/RULING_FQ-v2-NO-TRADE_2026-10-08.md`
- `/home/jon/breezy/docs/evidence/RULING_B3_permit_window_posture_2026-09-25.md`
- `/home/jon/breezy/docs/evidence/RULING_permit_daily_coverage_2026-09-25.md`
- the operator directive of 09-29 (weather sources for prediction; venue prices for cost only)
- the two operator caps, already in `operator.env` and never assigned here

**Hard rules for every WP and every brief:**
- Never open tape, settlement or truth for climate days **2026-10-07..2026-11-28** before the single read on or after 2026-12-07.
- Node logs and evidence dated before 2026-10-07T00:00Z may be read for **latency, AMBIGUOUS-count and fee fields only**. Never read prices-as-outcomes or settlements from them.
- Never edit `/home/jon/breezy/docs/evidence/m1v3/PREREG.json`.
- Nautilus Trader is immutable.
- `allow_short` stays False.
- No operator cap is assigned.
- Never weaken a safety, contract or NO-SEND test. Any guard whose shape changes is narrowed, and security-reviewed.
- Briefs state the exact interpreter path and PYTHONPATH.
- Agents format only their own files.
- Never run `uv sync`.
- Pass `--basetemp` under `~/.cache`.

## 0. Verified facts

**Carried from r3:**

| ID | Fact | Where |
|---|---|---|
| V1 | The frozen M1-v3 pins | `PREREG.json` |
| V2 | The M1V3-R1 conflict | — |
| V3 | Closed-set mirrors | `/home/jon/breezy/src/breezy/persistence/family_manifest.py:116-121`<br>`/home/jon/breezy/src/breezy/runtime/trade_supervisor_core.py:164`<br>`/home/jon/breezy/src/breezy/strategy/autonomy/node_plugins.py:13`<br>`/home/jon/breezy/src/breezy/analysis/autonomy/offline_plugins.py`<br>`/home/jon/breezy/src/breezy/persistence/autonomy/paths.py:28-29`<br>`/home/jon/breezy/src/breezy/strategy/current_rung_hold/family_id_arg.py:20`<br>`/home/jon/breezy/src/breezy/persistence/autonomy/pins.py:28` + `/home/jon/breezy/src/breezy/persistence/autonomy/resolver.py:462` |
| V4 | The live-orders allowlist | — |
| V5 | The AST guard. `trade.py` is 1274 lines | — |
| V6 | The permit gap | `trade_supervisor_core.py:37-39`, `:40`, `:139`, `:1082`, `:1188-1197`, `:1205`, `:1395-1404` |
| V7 | Consumers of the 16:50Z schedule | — |
| V8 | The singleton submit intent | `/home/jon/breezy/src/breezy/runtime/submit_intent.py:386-422` |
| V9 | Hard-coded floor MC constants | — |
| V10 | No loss-stop producer exists; the guard is FQ-scoped | — |
| V11 | Station set; connection sharding | — |
| V12 | AUT-5 owns `trade.py`, `settings.py` and `trade_supervisor*.py` | — |
| V13 | There is no node unit. `KillMode=process`. STOP_PRIOR stops the node by SIGTERM-ing the PID-verified lock holder, then polls `intent_lock_free` | `/home/jon/breezy/deploy/systemd/breezy-trade-supervisor.service:150-165`<br>`/home/jon/breezy/src/breezy/runtime/trade_supervisor.py:1230-1290` |
| V14 | `fq_loss_floor_mc_e2.py` calls `epoch_grid(freeze)` | `:13,231` |
| V15 | `validate_ii.py` anchors on 16:50 | `:146-149,378-386` |

**Added in r4 (verified):**

| ID | Fact | Evidence |
|---|---|---|
| V16 | `epoch_grid(freeze)` returns `{freeze} ∪ _EPOCH_FIXED`. **There is no epochs parameter.** | `/home/jon/breezy/scripts/analysis/fq_loss_floor_mc_gate.py:151-153` |
| V17 | `fq_loss_floor_np_bound._prepare` raises `RuntimeError` unless `MIXES == _MIXSET` and `DEFAULT_FREEZE == date(2026, 10, 8)`. It then builds its world through `fq_loss_floor_mc._world(args)`, which loads FQ's Kalshi pool and its own `HORIZON`. `DEFAULT_FREEZE` is used again at `:169`, and `epoch_grid(DEFAULT_FREEZE)` / `HORIZON` at `:283-284`. | `/home/jon/breezy/scripts/analysis/fq_loss_floor_np_bound.py:145-151` |
| V18 | The engine keys on `config.freeze`. | `/home/jon/breezy/scripts/analysis/fq_loss_floor_mc_engine.py:231-234` |
| V19 | The report keys on `config.freeze` too. | `/home/jon/breezy/scripts/analysis/fq_loss_floor_mc_report.py:199,202,249` |

The critical path is items 1–7 plus item 8 (WP-4, the permit window). Trading D-1_18Z instead is prohibited by §A.3(a).

## A. DRAFT ruling (item 1): `RULING_M1v3-CONFIRM-T2-SENDER_<ratification-date>`. Draft; not in force.

**Ratification requires all of:**
1. a WINNER read under A.1;
2. the §B floor frozen, with its binding PASS committed **before the read is opened** (§C.9);
3. the §B Stage −1 viability check passing (R4-2);
4. the WP-4 B3 re-open ruling committed;
5. converged review from trading-bot-architect, prediction-market-reviewer and security-reviewer.

A draft has no force. It is never cited by an allowlist row or a manifest.

### A.1 Condition

The report of `/home/jon/breezy/scripts/analysis/no_longshot_pooled_test.py` qualifies only if all of these hold:
- it is committed under `/home/jon/breezy/docs/evidence/m1v3/`;
- it was run at a HEAD descended from adb1cd8b;
- its status is READ;
- `verdict == "WINNER"`;
- `bca_failed` is not true.

Its sha256 is pinned. **"CONFIRM" means exactly this.**

### A.2 Ruled, on CONFIRM

1. **The family.** `pm_us_nolong_d12_v1`, composition kind `no_longshot_d12`, is a permitted T2 sender. §B is its floor prereg.

2. **M1V3-R1** (filter on a weather-sourced decision) is superseded for this family's sender eligibility only. AS-R6 stays.

3. **The 09-29 directive.**
   - The outcome term is the NWS CLI FINAL, a US weather source. The venue price is cost only, so the directive's circularity concern does not apply.
   - The letter of the directive is still breached, because the price level selects the take. This is accepted as a narrow exception for this family, decided by the peer loop.
   - If any peer rejects this reconciliation, §A.5 applies.

4. **The population.** It is frozen with §B by 2026-11-20:
   - D0 only.
   - The rung's first Depth10 update the node receives with `ts_event` in [12:00, 13:00)Z, per YES rung.
   - NO ask = 1 − best YES bid (size ≥ 1).
   - Take iff the NO ask is ≥ 0.90, inclusive, across all of [0.90, 0.99]. **0.99 asks are taken** (R4-17): skipping them would be a sub-band, which A.3(b) bans.
   - BUY NO, qty 1, IOC, limit = that ask.
   - One evaluation per (station, D, rung); hold to settlement.
   - Stations: LAX, MDW, MIA, SFO, plus NYC only if WP-0(a) shows support by 11-20. The default is the four stations.
   - A.6 lists the parity gaps.

5. **Gates:**
   - the permit;
   - the live-orders gate, with an exact allowlist row;
   - the family halt;
   - the fee-drift probe;
   - the loss stop (WP-5);
   - the submit-intent latch, under the WP-1 policy;
   - K1–K7;
   - both operator caps, unchanged.

6. **K4 formula (pinned; M2, R4-12).**
   - **C_d** = the number of node-evaluated rungs on trading day d whose first in-window NO ask is ≥ 0.90. It comes from the decision funnel and is independent of fills, the latch and caps.
   - **Day model:** NB with mean μ and var = μ + αμ². μ and α are fitted on pre-window days 08-30..10-06 for the pinned stations. If α̂ ≤ 0 the model **falls back to Poisson** (α = 0).
   - **14-day block sums:** μ_b = 14μ and var_b = μ_b + (α/14)·μ_b².
   - **Autocorrelation inflation:** φ = 1 + 2·Σ_{k=1..3} max(0, ρ_k)·(1 − k/14).
   - **Inflated model mapped back to NB:** α′ = max(0, (φ·var_b − μ_b)/μ_b²). If α′ = 0, use Poisson(μ_b).
   - **Two-sided tail:** p = min(1, 2·min(F(S), 1 − F(S − 1))), where F is the NB(μ_b, α′) CDF.
   - **K4 trips** iff p < 0.01 **and** S/μ_b lies outside **[0.5, 2.0]**.
   - It is implemented in pure Python with `math.lgamma`. No scipy (mypy-strict; no Any/cast/ignore).

7. **K3 drop threshold (pinned; R4-1).**
   - **Two-state latch-hold mixture.** Each order holds the singleton latch for:
     - **h_post** (the pre-window p95 POST round-trip) if it is non-AMBIGUOUS;
     - **L*** (the pre-window p95 AMBIGUOUS-to-resolution time, capped at 60 s) if it is AMBIGUOUS.
   - **p_amb** = the upper 95% Wilson bound of the AMBIGUOUS rate across all live orders in node logs dated before 10-07 (FQ v1 and earlier).
   - **Fallbacks (R4-4)**, used if that history is unusable: p_amb = 0.5, L* = 60 s, h_post = 2 s.
   - **d̂_mix** comes from replaying each pre-window day's candidate arrival order. Arrival order is recorder `ts_event` (R4-3). Each order's hold is drawn from the mixture, with a pinned seed and 1,000 draws per day.
   - Report d̂_mix p50 and p90 across days, and the day-clustered SE.
   - **τ_drop = d̂_mix_p50 + max(0.10, 2·SE_day).**
   - K3's drop test is evaluated **cumulatively over live days since activation**, and only once candidates ≥ 60.
   - Every input is frozen in §B.

8. **Fee (M5).**
   - WP-0(h) classifies the venue-charged per-contract fee at qty 1, on the grid 0.90..0.99, using evidence from before 10-07.
   - **(a)** Venue fee ≤ the screen primary fee everywhere: no adjustment.
   - **(b)** It exceeds the screen primary somewhere by ≤ 1¢: ratification also requires the read report's slippage = 2¢ row to have a one-sided LB > 0. If that row has no LB, STOP.
   - **(c)** It exceeds by > 1¢ anywhere: STOP.
   - The case is recorded in the §B prereg and determines the excluded ask set (§B.1).

### A.3 What the M1-v3 result may NOT be used for

- **(a)** Trading any other window.
- **(b)** Trading a sensitivity cell: an ask sub-band (including skipping 0.99 asks), slippage, or fee variants.
- **(c)** Adding unscreened filters: depth, time, weather, or a post-read station choice.
- **(d)** Serving as evidence for FQ v2, any forecast family, any model variant, AUT-S, or `screen.py`.
- **(e)** Claiming an edge size; only the LB is cited.
- **(f)** Re-reading, re-running or extending the screen, or relabelling UNDERPOWERED or PENDING_TRUTH.
- **(g)** Changing qty or either cap.
- **(h)** Trading any side other than BUY NO.
- **(i)** Trading any venue other than Polymarket.us.
- **(j)** Choosing epochs, horizon or activation after the read. Activation after 2027-01-20 means shelve.
- **(k)** Bypassing a FAIL, unrun or non-viable §B.
- **(l)** Changing any K1–K7 threshold or formula, L* / h_post / p_amb, the d̂_mix procedure, or any §B parameter after the read. All of them live in the frozen §B prereg.

### A.4 Relationships

- RULING_FQ-v2-NO-TRADE stays in force for FQ v2.
- B3 (a′) is decided by the WP-4 ruling.

### A.5 Any other outcome means shelve

This covers:
- NO-EDGE, UNDERPOWERED or INVALID;
- PENDING_TRUTH past 12-21;
- a §B FAIL;
- a Stage −1 viability STOP;
- an unratified WP-4;
- any WP-0 STOP or M5 STOP;
- a peer rejection.

On shelve:
- The manifest stays DRAFT, or is removed by a reviewed commit.
- No allowlist row is added.
- The code stays inert, and the branches stay unmerged.
- The drop-in stays.
- Nothing goes live.
- PROGRESS records it (M1V3-R11).
- Any re-test needs a new prereg and a new plan.

### A.6 Parity between the screen and the live family (disclosed)

| Dimension | Screen | Live | Disclosure |
|---|---|---|---|
| Window and selector | First tape row in [12, 13)Z | First node update in [12, 13)Z | WP-0(d): first-row parity ≥ 95% **and** within-window arrival-order rank correlation ≥ 0.9, else STOP (R4-3). |
| Incomplete station-day | Excluded whole (MNAR) | Takes per rung | K4b. |
| Truth | FINAL required | Unknown at decision time | Reported at settlement. |
| Empty YES bid | Counted, no take | Same | Parity. |
| **Take-all vs serial latch** | Every qualifying rung-day | Drop-not-queue under the singleton latch | d̂_mix p50/p90 and post-drop takes per day are entered here at the §B freeze (R4-1, R4-2). Viability STOP if d̂_mix_p90 > 0.30. |
| Execution | Blind | IOC misses, AMBIGUOUS, cap truncation | K3 and K6. |
| 0.99 asks (R4-17) | Included | Included | The digest reports the share of attempted takes at ask ≥ 0.99, or ≥ 0.98 under M5 case (b): legs that are excluded from the floor MC but traded live. |
| Stations | All on tape | Pinned set | NYC decision by 11-20. |
| Fee | Screen primary | Venue | M5 rule; the fee probe is the tiebreaker. |

**Analysis population (honest statement).**
- The screen measures *all qualifying candidates*.
- The live family trades a *time-ordered subset*: candidates that arrive while no intent is OPEN, before cap truncation. If arrival order within the 12:00Z burst correlates with ask level or outcome, the subset's EV differs from the screen's, and the CONFIRM does not cover that difference.
- K1 runs on attempted takes, the capital at risk.
- K3 and K4 run on candidates, the screen-equivalent population.
- The digest reports the attempted-vs-dropped ask-bin composition daily.
- Queueing is rejected: a queued order executes against a later book, which is a different population.

## B. Loss-floor MC/NP design for `pm_us_nolong_d12_v1` (item 4)

**Schedule:**
- Prereg: `/home/jon/breezy/docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04/NOLONG_D12_floor_prereg.json`, frozen by a gated, dedicated commit **on or before 2026-11-20**, after Stage −1 is committed.
- Binding run: 11-21..11-27, memory-capped, with RuntimeMaxSec and a stall watch, one heavy job at a time.
- The result is committed before the read is opened.
- The verdict binds.

### B.1 Pre-declared design

| Element | Value |
|---|---|
| Mix | `M-no`, the existing name. The pool holds only NO legs with ask ≥ 0.90 at the D_12Z first row, for the pinned stations. `MIXES` is unchanged, so `fq_loss_floor_np_bound`'s `_MIXSET` guard holds. NYC-inclusive pool: informational only. |
| Data | PM.us Depth10 tape for climate days **2026-08-30..2026-10-06**, filtered at the directory index before any read. Any day ≥ 10-07 is refused (exit 3, nothing written). Truth for days ≤ 10-06 is read only if `rho_hat` needs it. |
| **be (R4-10)** | Screen primary cost: **be = a + max(rounded_fee(a), θ·a·(1−a)) + 0.01**, θ = 0.0695. The venue fee enters **only** through the M5 rule. Exclusion rule: **be ≥ 1**. |
| a* | Unrounded boundary, from 0.0695x² + 0.9305x − 0.01 = 0 with x = 1 − a: x = (−0.9305 + √0.86861025)/0.139 = 0.0107381, so **a\* ≈ 0.98926**. (0.98926 vs 0.98927 is a rounding difference only.) |
| Excluded ask set by M5 case | On the 1¢ grid under the screen primary: 0.98 gives 0.99136 (kept); 0.99 gives 1.000688 (excluded). **The excluded set follows the recorded M5 case:**<br>(a) **{0.99}**;<br>(b) **{0.98, 0.99}**: the classified venue fee of 1¢ at 0.98 gives be = 1.00, so the floor's exclusion check uses the classified fee;<br>(c) is a STOP before any run. |
| Exclusion cap (M0) | Excluded legs under the classified case making up **> 5% of legs means FAIL**. Informational **clipped-be = 0.995** sensitivity. Exclusion is **not conservative for G1**: G1 binds on the primary run, and the clipped run reports the direction of the effect. Live, the excluded asks are still traded (A.6). |
| H0 feasibility | For NO legs q = 1 − be ≤ 0.10, so Σq ≤ 1 when there are ≤ 10 legs. Counted. > 5% of station-days infeasible means FAIL. |
| H1 feasibility (M1) | At the bar δ = −0.04: Σ(q + \|δ\|) ≤ 1 is required. Infeasible station-days are counted and excluded from the bar's H1 draws. > 5% of station-days means FAIL. For δ = −0.08 and −0.16, the existing `_h1_masses`/`h1_fallback` (`/home/jon/breezy/scripts/analysis/fq_loss_floor_mc_draw.py:61-69,216`) runs unchanged; its fallback share is reported, informational only. |
| α ladder | `ALPHA_FLOOR_GRID` (0.10, 0.20, 0.30), imported. Escalation is on G1 only. A G3 miss is a veto. |
| δ grid | **Design-only** (−0.16, −0.08, −0.04, −0.02); the FQ default `DELTAS` is unchanged. **Bar δ = −0.04.** This is a different bar from FQ's, not a stricter one. **Drift between 0 and −4¢ per take is not protected by the stop**; only the CONFIRM LB, K5 and the horizon cover it. |
| Epochs and horizon | Epochs {**2026-12-23, 2027-01-06, 2027-01-20**}, horizon **2027-02-28** = `terminal_climate_day`. Design freeze = epochs[0]. Activation after 01-20 means shelve. |
| G-gate | G1 holds, and G3(−0.04) ≥ 2.5·α at the selected α, at every epoch. |
| D1-analogue | The NP upper bound on G3(−0.04) at α_eff is ≥ 0.30 at every epoch; `e_proj` = 2027-01-20. No nominal-α switch. |
| Seeds | Floor run 20261121; Stage 0 20261122; 10k replicates each. Stage −1 d̂_mix replay seed 20261120. |
| Sensitivities (M7) | ±50% take rate at every epoch including 01-20. NYC pool. Clipped-be pool. All informational. |
| **Stage −1 (R4-1..R4-4, R4-11, R4-13)** | Pre-window only, committed before the freeze; no verdict except the viability STOP below. Reports:<br>• path-tick distribution per epoch, and station-days with takes per day (S);<br>• K4 inputs: μ, α (with Poisson fallback), ρ₁..₃ floored at 0, φ, α′;<br>• **K5 reference**: pre-window day-level shares of the three ask bins;<br>• legs per station-day; exclusion and feasibility counts;<br>• **arrival model**: per-day candidate arrival order and gaps from **recorder ts_event**, plus the share arriving 12:00:00–12:00:05Z;<br>• **latch inputs** from node logs dated before 10-07 (latency and AMBIGUOUS fields only): h_post (p95 POST round-trip), L* (p95 AMBIGUOUS-to-resolution, capped at 60 s), p_amb (Wilson upper 95%). Fallbacks p_amb = 0.5, L* = 60 s, h_post = 2 s if absent;<br>• **d̂_mix** p50 and p90, SE_day, τ_drop;<br>• **post-drop takes per day** = λ₄·(1 − d̂_mix_p50), used in B.2. |
| **Viability STOP (R4-2)** | **If d̂_mix_p90 > 0.30, STOP (shelve)**: the live population would not be the screened one. Also STOP if post-drop takes over the 40 days from 01-20 to 02-28 fall below the 156 needed at the bar's nominal rate (B.2). |
| Freeze check | `check_frozen_blob` plus introduced-blob, via `/home/jon/breezy/scripts/analysis/prereg_precommit_check.py`. |
| Amendment shape | Readable by `/home/jon/breezy/scripts/analysis/prereg_amendment_check.py`. Otherwise WP-5 adds a per-family loader that fails closed. |

### B.2 Path argument: a hypothesis, to be tested in Stage −1 and Stage 0 (R4-16)

**What failed for FQ v2.** Its D1 failure came from short paths:
- M-yes median path of about 7 ticks;
- α_eff 0.0187, NP bound 0.1186;
- `bound_upper_min` 0.125, against a bar of 0.30;
- A1 G3(−0.16) M-yes 0.2104, against 0.25;
- M-no NP 0.4927 on 11-01, but G3 0.2334 at 12-01.

**For this family**, from the last epoch 01-20 to the horizon 02-28 is **40 days inclusive**:
- Ticks = 40 × S × (1 − d̂_mix_p50), where S = station-days with takes per day, measured in Stage −1 (≤ 4). The r3 figure of 135 used 39 days and an assumed S = 3.5; this formula replaces it. At S = 3.5 with no drops it would be 140.
- **Takes at the nominal rate:** 40 × 9.4 × (1 − d̂) = 376(1 − d̂). That meets the about 156 takes needed at δ = −0.04 iff d̂ ≤ 0.585. The viability STOP (d̂_p90 ≤ 0.30) guarantees it.
- **Takes at −50% (informational, M7):** 188(1 − d̂). That meets 156 only if d̂ ≤ 0.17, so it is **marginal**, and is reported as such, never a STOP.
- Mutual exclusivity bounds the per-station-day variance.

**Counter-hypotheses:**
- Fat single losses near a ≈ 0.97; the NP bound measures this.
- Winter ask-mix drift (K5).
- Exclusions and drops reduce the tick count.

### B.3 Tooling (WP-A, scripts only, 11-09..11-19)

**Golden files first, in a separate earlier commit.** The A1, Stage-0 and E2 subset outputs at the current HEAD go into `/home/jon/breezy/tests/fixtures/fq_floor_golden/`.

**McDesign (R4-14, the real coupling).** A frozen dataclass `McDesign(epochs: tuple[date, ...], horizon: date, deltas: tuple[float, ...])` in `fq_loss_floor_mc_gate.py`:
- `freeze` is the property `epochs[0]`.
- `DEFAULT_DESIGN` reproduces today's values: epochs = `epoch_grid(DEFAULT_FREEZE)`, horizon = `HORIZON`, deltas = `DELTAS`.

Changes by file:
- **`gate.py:151-153`:** `epoch_grid` keeps its signature for the default. A new `design_epoch_grid(design)` returns `design.epochs` explicitly; for the new family it never returns the hard-coded `_EPOCH_FIXED`.
- **`engine.py:231-234`** and **`report.py:199,202,249`:** take `design=DEFAULT_DESIGN` as keyword-only. They key lengths and the freeze row on `design.freeze` and `design.epochs`. `config.freeze` is asserted equal to `design.freeze`.
- **`fq_loss_floor_np_bound.py`:**
  - Split `_prepare` into `_prepare(args)`, the default path, which keeps the `_MIXSET` and `DEFAULT_FREEZE` RuntimeError guards at `:145-151` and still calls `_world`.
  - Add `_prepare_from(config, groups, design)`, which has no `_world` call.
  - `:169` (`n_long`) and `:283-284` (epoch loop, `HORIZON`) read from `design`.
- **`fq_loss_floor_mc_e2.py:231`:** reads `design.epochs[0]`.
- **`/home/jon/breezy/scripts/analysis/fq_loss_floor_mc.py` is not edited** (its blob is pinned in F5).

**RED tests for the shared modules:**
- `test_fq_design_default_matches_golden_a1_subset`
- `test_np_bound_default_matches_golden_stage0_subset`
- `test_e2_default_matches_golden`
- `test_np_bound_injected_nondefault_freeze_and_epochs` (R4-14)
- `test_design_epoch_grid_never_returns_epoch_fixed_for_injected_design`
- `test_deltas_default_unchanged_minus_002_only_via_design`
- `test_fq_loss_floor_mc_py_blob_unchanged`

**`/home/jon/breezy/scripts/analysis/nolong_d12_mc_templates.py`** (≤ 300 lines). RED tests:
- `test_refuses_climate_day_on_or_after_2026_10_07`
- `test_date_filter_precedes_any_tape_read`
- `test_be_uses_screen_primary_cost`
- `test_be_threshold_excluded_set_matches_m5_case` (R4-10)
- `test_excluded_leg_share_over_5pct_fails_under_classified_fee`
- `test_clipped_be_sensitivity_never_binding`
- `test_pool_all_legs_side_no_ask_ge_090`
- `test_h0_sum_q_feasibility_counted`
- `test_h1_feasibility_counted_and_excluded_at_bar`
- `test_d12_first_row_only`
- `test_no_ask_none_counted_not_synthesised`

**`/home/jon/breezy/scripts/analysis/nolong_d12_stage_minus1.py` (new, ≤ 300 lines, R4-13).** It computes the NB μ/α fit with Poisson fallback, ρ₁..₃ floored at 0, φ, α′, the K5 reference shares, the latch inputs and fallbacks from pre-10-07 logs, the d̂_mix replay, τ_drop, post-drop takes and the viability verdict. It is fully typed, uses `math.lgamma`, and imports no scipy. RED tests:
- `test_nb_fit_moments`
- `test_nb_poisson_fallback_when_alpha_le_0`
- `test_rho_floored_at_zero`
- `test_alpha_prime_mapping`
- `test_nb_two_sided_tail_min_cdf_sf`
- `test_dmix_replay_two_state_hold_seeded`
- `test_p_amb_wilson_upper_and_fallback_0_5`
- `test_latch_inputs_fallback_60s_2s`
- `test_tau_drop_formula`
- `test_viability_stop_when_dmix_p90_gt_030`
- `test_refuses_any_input_on_or_after_2026_10_07`
- `test_log_reader_reads_latency_and_ambiguous_fields_only`

**`/home/jon/breezy/scripts/analysis/nolong_d12_floor.py`** (≤ 200 lines; the driver uses `_prepare_from`). RED tests:
- `test_refuses_unfrozen_prereg`
- `test_no_nominal_alpha_path_after_result`
- `test_epoch_holds_required_at_every_epoch`
- `test_h0_h1_at_most_one_losing_leg_per_station_day`
- `test_sensitivity_takes_rate_pm50_reported_at_every_epoch_including_01_20`

**Gate:** focused tests, mypy-strict ratchet (scripts/analysis included), and `lint-imports` from the tree root ("N kept, 0 broken"), then the full gate.

**Effort:** 4.5 d build + 1 d review.

## C. Code work packages

### WP-0 Verify-first (read-only)

**Early phase, 11-09..11-19:**
- **(a)** NYC support. The decision goes into §B by 11-20; the default is four stations.
- **(b)** Is AUT-5a registry routing mandatory? **Decision by 11-12.**
  - If yes: widen `LIVE_GATE_ROUTED_KINDS`, and make pins / `fold_pairs.py:120` / `validate_ii.py:146-149,378-386` / `wal_snapshot.py:553` follow the kind schedule. That costs **5–6 d** (§C.7).
  - If no: boot from env.
- **(c)** Latch mechanics, from code: read `/home/jon/breezy/src/breezy/runtime/submit_intent.py:386-422` and the AMBIG-LATCH B resolver path. Locate the pre-10-07 node log files that hold order POST, AMBIGUOUS and resolution timestamps (FQ v1 10-02..10-05 and earlier) for Stage −1. **Shadow mode sends no orders, so live latency is never measured in shadow (R4-4).**
- **(e)** Mirror grep for `forecast_quantile_ladder` / `forecast_ladder` across `/home/jon/breezy/src` and `/home/jon/breezy/tests`. Re-verify `validate_ii.py:488`.
- **(f)** Resolve the exec-import/firewall pin file and row for `src/breezy/strategy/no_longshot_d12/strategy.py`; the candidate is `/home/jon/breezy/tests/contract/test_us_source_ingest_egress_guard.py:608`. Confirm the NO-buy path reuses FQ's SELL/BUY_SHORT venue translation. **This is a precondition for the WP-1 strategy merge.**
- **(g)** Find the existing node-stop procedure. If none, WP-5 adds the read-only PID read-back helper.
- **(h)** Classify the venue fee at qty 1 on 0.90..0.99 (M5) and record it in §B.
- **(i) (R4-15)** Before the early `decision.py` merge: confirm no strategy-package enumeration test (registries of `strategy/*` packages, citation map, autonomy plugin enumeration) and no import-linter contract breaks on the new `strategy/no_longshot_d12/` package. `lint-imports` must report "N kept, 0 broken".

**Late phase, 11-28..:**
- **(d)** Using a post-11-28 recorder sample against a scratch shadow node:
  - **first-row parity ≥ 95%**, and
  - **within-window arrival-order Spearman rank correlation ≥ 0.9** per day, at the median (R4-3).

  Otherwise STOP. Shadow measures arrival order only, never order latency.

**Latch bound.** L = 60 s is the ceiling everywhere. GET-resolve runs at +2, +7, +15, +30 and +60 s; still unresolved at 60 s means the intent stays OPEN and K6 applies. Justification: 60 s is 1/60 of the window, past it an OPEN latch blocks a growing share of candidates, and it is the cap used for L* and in the Stage −1 fallback.

### WP-1 Strategy: `/home/jon/breezy/src/breezy/strategy/no_longshot_d12/` (3.5 d)

**Files:**
- `config.py` (`shadow_only: bool = True`);
- `decision.py` (pure; early; merge precondition WP-0(i));
- `strategy.py` (native depth subscriptions and IOC limit `submit_order`, persistent latch, own key prefix);
- `composition.py`.

**Latch policy:**
- Orders are serial: arm → POST → retire.
- A candidate that arrives while an intent is OPEN is **dropped and counted**, never queued.
- GET-retire follows the WP-0 schedule.
- The digest carries: candidates, attempted, filled, zero_fill, latch_dropped, ambiguous_resolved, ambiguous_open, attempted-vs-dropped ask-bin composition, and the **share of attempted takes at ask ≥ 0.99**, or ≥ 0.98 under M5 case (b) (R4-17).

**RED tests:**
- `test_decision_parity_with_m1_selector_on_fixtures` (≥ 30 pre-window fixtures, asserted non-empty)
- `test_ask_090_inclusive_no_upper_subband_099_taken`
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
- `test_fee_grid_matches_m5_case` (R4-10): pins the screen primary on 0.90..0.99 (for example a = 0.95: rounded 0.00, unrounded 0.0033) and the classified venue fee per the recorded M5 case
- the WIDENED exec-pin row

**Replay** (not RED): pre-window only; ≥ 99% match against m1's takes.

**Branch timing (R4-5).** The strategy is built on a branch from **11-20**, after the §B freeze. It is inert and unmerged; merging happens only in the late phase, after a floor PASS and with WP-0(f).

### WP-2 Composition kind, dispatch and guards (3 d; branch from 11-20, merged late — R4-5)

**Mirrors.** Each V3 site widens by one row. RED tests:
- `test_composition_kinds_widened_by_exactly_nolong`
- `test_subscribed_marker_map_has_nolong` (updates `/home/jon/breezy/tests/unit/test_app_trade_boot_family_log.py:217` and `/home/jon/breezy/tests/unit/test_forecast_quantile_ladder_manifest_and_markers.py:64`)
- `test_node_plugins_equal_offline_plugins_equal_kinds`
- `test_autonomy_paths_kinds_mirror_and_model_class_re_matches`
- `test_haltable_kinds_include_nolong_exit_kinds_unchanged`
- `test_live_gate_routed_kinds_unchanged` (or `…_widened`, per WP-0(b))

**`trade.py` keeps only the gate site.**
- New module `/home/jon/breezy/src/breezy/app/compose_no_longshot.py` holds the non-gate logic.
- New shared helper `_live_orders_gate_preamble(manifest, sending_permit)` in `trade.py`.
- `_compose_no_longshot_d12` is about 20 lines.
- `trade.py` is oversize (1274 lines) and owned by AUT-5.

**AST guard: narrow, plus one reviewed site.**
- The permitted sites are exactly {(trade.py, `_compose_forecast_quantile_ladder`), (trade.py, `_compose_no_longshot_d12`)}, keyed by AST function name, with an exact count.
- `live_orders` is bound exactly once per site, from `_live_orders_gate_preamble(` or `live_orders_authorized(`. Any re-binding is rejected.
- `test_gate_preamble_binds_from_live_orders_authorized`, with positive control `test_preamble_constructing_decision_directly_flagged`.
- The "both sites appear" test.
- Positive controls: wrong function name, non-gate binding, re-binding, a third site.
- Security sign-off.

**Dispatch tests:**
- `test_compose_family_dispatches_nolong`
- `test_fq_still_dispatches_to_fq_composer`
- `test_unknown_kind_refuses_with_specific_settings_error_and_log_line`
- `test_gate_refusal_raises_settings_error_and_logs_reason`
- `test_nolong_loss_stop_path_distinct_from_fq`
- `test_draft_manifest_refuses_boot`

**Focused gate:** exec-pin/firewall, the operator-control scan, `test_node_composition_contract`, `test_native_order_cap_wiring`, all `test_autonomy_*`, import gates, the citation map, `lint-imports`.

### WP-3 Manifest and allowlist (0.5 d, late)

- DRAFT manifest at `/home/jon/breezy/deploy/families/pm_us_nolong_d12_v1.json`:
  - kind `no_longshot_d12`;
  - pinned stations;
  - fee "0.0695";
  - terminal "2027-02-28";
  - sentinels;
  - no ruling.
- RED tests:
  - `test_nolong_manifest_draft_refused_without_allow_draft`;
  - `test_live_orders_allowlist_is_exactly_fq_v1_row`. At activation this is **replaced** by an exact two-row equality pin, never deleted.

### WP-4 Per-kind schedule record (item 8, 6 d; built early on a branch, merged late)

**Timing.**
- Built 11-09..11-27 on a branch, as a default-identical diff.
- **Not merged before the late phase.** The late merge needs:
  1. a full gate with GATE_EXIT = 0;
  2. a security re-review;
  3. sequencing against AUT-5a.
- Before the late phase there is no live-surface change.

**The B3 re-open ruling.**
- It is drafted early, peer-reviewed by security, and committed as a document with no live effect before the merge.
- It restates the RULING_permit_daily_coverage §4 clustering argument and the per-kind reset of `first_boot_permit_expires_at_ns` at STOP_PRIOR.
- **(A3)** `validate_ii.py:378-386`, `pins.py:121-125`, `fold_pairs.py:120` and `wal_snapshot.py:553` stay fixed. This holds **only while the family is not registry-routed**; forced routing re-opens the ruling.

**Code.** A `KindSchedule` record and the `SCHEDULE_BY_KIND` literal in `/home/jon/breezy/src/breezy/runtime/trade_supervisor_core.py`. The default row equals today's values, and the existing constants become aliases.

| Field | Default | `no_longshot_d12` |
|---|---|---|
| STOP_PRIOR | 16:40 | 11:20 |
| LAUNCH | 16:50 | 11:30 |
| RELAUNCH_CUTOFF = LAUNCH_WINDOW_END | 17:00 | 11:40 |
| SELF_CHECK | 17:05 | 11:45 |
| SELF_CHECK_WINDOW_END = B1_WINDOW_OPEN | 17:10 | 11:50 |
| Mid-day watch end | 01:00 on day + 1 | 13:00 |
| Rollover | 16:40 | 11:20 |
| Permit | 16:50–02:50 | 11:30–21:30 |

The nbp analyses use the default alias. The tally timer stays at 17:20Z.

**RED tests:**
- `test_default_kind_schedule_identical_to_all_constants_and_consumers`
- `test_nolong_permit_covers_12_13Z`
- `test_nolong_union_permit_coverage_bounded_over_all_relaunch_paths` (≤ 10h10m, within [11:30, 21:40])
- `test_first_boot_expiry_resets_at_kind_stop_prior`
- `test_kind_switch_midday_waits_for_next_stop_prior`
- `test_schedule_not_env_overridable`
- `test_single_mint_per_day_nolong`
- `test_validate_ii_launch_window_anchor_unchanged`

### WP-5 Hold, loss stop, kill rules, node-stop read-back (4 d)

**Hold.** Hold to settlement; `KINDS_WITH_EXIT_PATH` is unchanged; reconciliation uses the NO-leg sign.

**Producer.** `breezy-nolong-loss-stop` oneshot + timer. It replays `step_clock` with the §B boundary and writes `loss_stop/v1` to `$DATA/derived/nolong-loss-stop/latest.json`.

**The n = 0 ruling (S5, R4-7).**
- There is no seeded PASS. The first PASS is an evaluated digest over a **verifiably empty ledger**.
- **"Verifiably empty"** means the ledger file is at the **pinned path**, has a **readable header and sha**, its **family id matches** `pm_us_nolong_d12_v1`, and it holds zero settled fills.
- A **truncated, rotated, wrong-path or headerless** file means no artefact, so the probe reads **UNKNOWN**.
- The artefact carries `as_of`. It is **stale after 1 trading day**, and stale means **UNKNOWN**. **UNKNOWN vetoes**, consistent with `LossStopProbe`.
- RED tests:
  - `test_producer_empty_ledger_passes_missing_ledger_unknown`
  - `test_stale_artefact_unknown`
  - `test_empty_file_without_header_unknown`
  - `test_truncated_or_wrong_family_ledger_unknown`
  - `test_producer_never_writes_seeded_pass`
  - `test_producer_digest_recomputable`
  - `test_producer_refuses_other_family_fills`
  - `test_missing_artefact_vetoes`
  - `test_fail_sets_family_halt_set_only`

**Early guard reshape (R4-8).** In `/home/jon/breezy/tests/contract/test_fq_loss_stop_writer_allowlist.py`:
- The change is **additive tuple widening only**: tokens become (`fq-loss-stop`, `nolong-loss-stop`), and unit prefixes become (`breezy-fq-loss-stop.`, `breezy-nolong-loss-stop.`).
- Amendment files are per-family, with a reachable check. **A missing per-family amendment file fails CLOSED.**
- **The nolong writer row is absent in the early merge.** It lands late, valid only while the floor is reachable.
- FQ scan behaviour stays **byte-identical**.
- RED tests:
  - `test_fq_scan_unchanged`
  - `test_planted_nolong_token_writer_flagged`
  - `test_planted_nolong_unit_flagged`
  - `test_nolong_writer_row_refused_when_floor_unreachable`
  - `test_missing_family_amendment_file_fails_closed`
  - `test_no_nolong_writer_row_in_early_merge`
- **Security-reviewer sign-off is required before the early merge.**

**Node-stop read-back.** If WP-0(g) finds no existing helper, add `/home/jon/breezy/scripts/ops/node_pid_readback.py`. It is read-only and reports:
- the PID-verified intent-lock holder, its cmdline and start time;
- whether the lock is free;
- the submit-intent state.

RED tests: `test_readback_reports_lock_holder_pid_and_starttime`, `test_readback_reports_intent_state`, `test_readback_never_signals`.

**Digest module (R4-13).** New module `/home/jon/breezy/scripts/analysis/nolong_d12_digest_rules.py` (≤ 300 lines, fully typed, no scipy). It holds the K3–K5 computations and the R4-17 shares, and is imported by `/home/jon/breezy/scripts/analysis/decision_funnel_daily_digest.py` with a single call site. All thresholds are loaded from the frozen §B prereg.

**Kill rules.** All act through the set-only family halt; nothing re-arms. The digest pages, and the coordinator halts the same day.
- **K1.** Loss-stop FAIL. Terminal.
- **K2.** Fee-drift mismatch: halt.
- **K3.** On resolved outcomes, once attempted ≥ 30: halt if filled/attempted < 0.50. **Drop test (R4-1):** cumulative since activation, evaluated only once candidates ≥ 60; halt if cumulative latch_dropped/candidates > τ_drop. Price improvement means fill_px < limit; a fill worse than the limit is an immediate halt plus evidence.
- **K4.** The A.2.6 formula. **K4b**, the share of live takes on screen-excluded station-days, is reported; > 0.20 raises a review flag.
- **K5 (R4-11).**
  - The **[0.96, 0.99]** bin is designated **now** as the negative-EV-risk bin. Nothing depends on the read report.
  - Statistic: a **chi-square** on the three bin shares (live block vs pre-window reference), with a **whole-day permutation** null (B = 10,000, pinned seed).
  - Default action: review flag.
  - **Halt** iff p < 0.001, n ≥ 60 candidates, and the [0.96, 0.99] share rises by ≥ 15 pp over the **Stage −1 pre-window share**.
- **K6.** An AMBIGUOUS still OPEN at 13:00Z, after the 60 s bound: halt.
- **K7.** Terminal day 2027-02-28.

**Threshold tests:**
- `test_k3_drop_cumulative_min_60_candidates_tau_from_prereg`
- `test_k3_fill_rate_min_30_attempted`
- `test_k4_nb_block_alpha_prime_lgamma_tail_band`
- `test_k4_not_tripped_by_cap_truncation`
- `test_k5_chisq_day_permutation_and_096_099_rule`
- `test_k6_unresolved_ambiguous_halts`
- `test_share_attempted_at_ask_ge_099_reported`

### WP-6 Merge order with AUT-5a (1.5 d; + 5–6 d if routing is forced)

- **AUT-5a merged first:** rebase WP-2 and WP-4 onto it; add a bootstrap row or `entry_veto` if required.
- **Otherwise:** the coordinator sequences the merges, and WP-4 never merges ahead of a conflicting AUT-5a without re-review.
- **Always:** full gate after every merge; read GATE_EXIT before any push.

### C.7 Effort and schedule

| WP | Phase | Build | Review | Merges |
|---|---|---|---|---|
| WP-A (incl. Stage −1 module) | early | 4.5 d | 1 d | 2 |
| WP-0 (a, b, c, e, f, g, h, i) | early | 1.5 d | — | — |
| WP-0 (d) | late | 0.5 d | — | — |
| WP-1 `decision.py` + parity/fee tests | early (inert; WP-0(i) first) | 1 d | 0.5 d | 1 |
| WP-4 ruling + branch | early, **branch only** | 5 d | 1 d | 0 |
| WP-5 guard reshape | early (security sign-off first) | 1 d | 0.5 d | 1 |
| **WP-1 strategy** | **branch from 11-20, inert, unmerged (R4-5)** | 2.5 d | 0.5 d | 0 early |
| **WP-2** | **branch from 11-20, inert, unmerged (R4-5)** | 3 d | 1 d | 0 early |
| WP-5 producer, digest module, read-back | branch from 11-20 / late | 3 d | 0.5 d | 0 early |
| WP-3 | late | 0.5 d | — | 1 |
| Late merges: WP-1, WP-2, WP-4, WP-5 producer, WP-6 | late | 2 d (rebase/fixups) | 1.5 d (incl. WP-4 security re-review) | 6 |

**Totals:** about 27 agent-days, plus about 6 h of serial gate time (≈ 25 min × 14 merges).

**Trade-off (R4-5).** Building WP-1, WP-2 and WP-5 on branches from 11-20 wastes about **6 agent-days if the floor FAILs on 11-27**. It is accepted because the late phase then contains **only merges, gates and reviews**: about 3.5 d of serial work, which fits 11-28..12-06 with slack.

**Nominal activation:**

| Date | Step |
|---|---|
| 12-07 | Read |
| 12-08 | Ratify |
| 12-09/10 | Shadow day + committed read-back |
| ≈ 12-10/11 | Orders |

**If WP-0(b) forces routing (decided by 11-12):** the 5–6 d of routing work touches AUT-5-owned and registry files. It can be built on a branch early, but merges only late, and its security review sits on the late chain. **The late window is then infeasible as scheduled, and activation moves to ≈ 12-16..12-18** — still before the 01-20 shelve deadline.

### C.8 Live-surface statement

Before the late phase, nothing changes on the primary tree's supervisor unit, `trade_supervisor*.py`, `trade.py`, the allowlist or any deployed family. Early merges are limited to:
- analysis scripts;
- the inert `decision.py`;
- the security-signed, additive guard reshape (with no nolong writer row);
- documents.

Everything else is branch-only.

### C.9 Slip policy

**Dependency chain:**
1. WP-0(b), 11-12
2. NYC decision and Stage −1, by 11-20
3. §B freeze, 11-20
4. Binding run, 11-21..27
5. Floor result committed
6. Late merges, 11-28..
7. Read (≥ 12-07)
8. Ratification
9. Shadow day and committed read-back
10. Orders

**Rules:**
- **The read never precedes the committed floor result.** If the floor slips, the read is delayed; PREREG's "on or after" allows this.
- **A Stage −1 viability STOP or a floor FAIL** shelves the family before any late merge.
- **If no NYC decision by 11-20,** use four stations.
- **WP-0 STOP outcomes** ((d), M5 (c), the viability STOP) shelve.
- **A late slip moves activation day-for-day.** Activation after 2027-01-20 means shelve.
- **Never compressed:**
  - the full gate after every merge, with GATE_EXIT read before push;
  - every review, including WP-4's security re-review and the guard sign-offs;
  - the B3 ruling;
  - the shadow day and its committed read-back;
  - the halt, node-stop and intent read-backs;
  - the unit dry-run.

## D. Activation runbook (item 7), on CONFIRM only

### D.1 Day 0: read

1. Run the frozen tool once, with no `--as-of`, after the §B result is committed.
2. Commit the report.
3. If the verdict is not WINNER, apply §A.5.

### D.2 Day 0–1: ratify

1. Finalise §A with the report, §B and WP-4 shas, plus the M5 (b) check if that case applies.
2. Run the peer loop.
3. Compute the ruling sha256 **after** the final text. Commit the evidence copy and a byte-identical copy under `/home/jon/breezy/deploy/families/rulings/`.
4. In one reviewed commit:
   - add the allowlist row;
   - **replace** the WP-3 pin with an exact two-row equality pin;
   - set the manifest to REGISTERED, with the ruling and `d0_climate_day`.
5. Run the full gate, and read GATE_EXIT.

### D.3 Day 1–2: shadow-only boot, with the drop-in present

1. Commit `BREEZY_SENDING_FAMILY_ID=pm_us_nolong_d12_v1` to `/home/jon/breezy/deploy/systemd/breezy-trade-supervisor.service` **on a branch**. The unit is symlinked live, so merge only at GATE_EXIT = 0.
2. Dry-run the unit: `systemd-analyze --user verify`, and `systemctl --user cat` to confirm `BREEZY_ORDERS_ENABLED=0` is still in effect from the drop-in.
3. **Before any restart, the intent precondition (R4-6) must hold:**
   - read the submit-intent state via the read-back helper;
   - if it is OPEN or AMBIGUOUS, retire it **only** via the reviewed resolver path, with venue evidence;
   - **never restart the supervisor with a non-terminal intent** (the 09-24 deadlock).
4. **Quiet window:**
   - outgoing schedule: 01:00–16:40Z;
   - nolong schedule: **13:15Z–11:10Z**, which avoids STOP_PRIOR 11:20 through the mid-day watch end at 13:00, and the B1 window opening at 11:50.

   On the switch day, wait for the next 11:20Z STOP_PRIOR.
5. **Shadow-day read-back (11:30–13:00Z).** Check that:
   - the live-trading permit expires at or after 13:00Z (nominally 21:30Z);
   - `PASS_ORDERS_NOT_REQUESTED` appears;
   - `boot_family id=pm_us_nolong_d12_v1` appears;
   - `enabled=False reason=permit_absent ruling_sha256=<pinned>` appears;
   - shadow decisions appear in [12, 13)Z;
   - the loss-stop artefact is an evaluated empty-ledger PASS that is not stale.

   **Commit this evidence** as `/home/jon/breezy/docs/evidence/m1v3/NOLONG_SHADOW_READBACK_<date>.md`.

### D.4 Day 2–3: orders on

1. **Hard precondition (R4-9):** the D.3 shadow read-back evidence is committed. Without it, the drop-in is not removed.
2. Remove `/home/jon/.config/systemd/user/breezy-trade-supervisor.service.d/fq-v1-halt-orders-off.conf` as a reviewed act: evidence note, one-line heads-up, and a scratchpad snapshot first.
3. Confirm the intent precondition in D.3 step 3, run daemon-reload, and restart in the quiet window.
4. **Operator items:** none. The caps are already set.
5. **First trading day**, from the log files:
   - the boot-time order-submission permit line;
   - `enabled=True reason=ok`;
   - SELF_CHECK PASS at 11:45Z;
   - candidate, attempt, fill and drop counts; attempted-vs-dropped bins; the ≥ 0.99 share;
   - every AMBIGUOUS resolved within 60 s, or K6;
   - D+1 reconciliation with the leg sign;
   - the K3–K5 fields;
   - liveness = process + log mtime + permit unexpired + tape advancing.

### D.5 Rollback, in order

1. **Halt.** Run the family-halt CLI with an absolute `--families-dir`. **Read back** the halt row and the digest status. (This CLI failed once before, on 10-05.)
2. **Stop the supervisor** with `systemctl --user stop breezy-trade-supervisor.service`. `KillMode=process` leaves the node running.
3. **Stop the node.**
   - Run the read-back helper to get the PID-verified intent-lock holder, its cmdline `breezy-trade`, and its start time.
   - **Immediately before signalling, re-read the holder** and require the same PID **and** start time (TOCTOU / PID-reuse guard, R4-6).
   - Then send `kill -TERM <pid>` only. Never pgrep; never SIGKILL.
4. **Read back the stop:**
   - the lock is free (no FLOCK holder);
   - `kill -0` fails;
   - the node log shows its shutdown line.

   If the node is still alive after the poll budget, alert. Never escalate the signal.
5. **Intent state.**
   - Read it.
   - If it is OPEN or AMBIGUOUS, retire it only through the reviewed resolver path with venue evidence, **before** any supervisor restart.
6. **Restore.**
   - Restore the drop-in from the snapshot.
   - Run daemon-reload.
   - Start the supervisor in the quiet window, once the intent is terminal.
   - Verify that orders are not requested at the next boot.

## E. Risks

| # | Risk | Sev. | Mitigation |
|---|---|---|---|
| R1 | P(WINNER) ≈ 3%. This is the dominant risk. | Dominant | Option value: branch-only builds, merges only after a PASS. |
| R2 | P(edge \| WINNER) ≈ 0.25–0.33. | High | Qty 1; K1–K7. |
| R3 | Selection bias from a single window; Oct–Nov sample vs Dec–Feb trading; MNAR. | High | §A.3, A.6, K4/K4b/K5, winter epochs. |
| R4 | Permit gap; refactor in AUT-5-owned files. | High | Branch only; gated, security-re-reviewed late merge. |
| R5 | Latch drops in the 12:00Z burst. | High | d̂_mix mixture; viability STOP at p90 > 0.30; cumulative τ_drop; disclosures. |
| R6 | Recorder-vs-node first-row and arrival-order disparity. | High | WP-0(d) STOP rules. |
| R7 | Cap truncation. | Med | K4 uses candidates. |
| R8 | A peer rejects the 09-29 reconciliation. | Med | §A.5. |
| R9 | Venue fee above the screen's. | Med | M5 rule; excluded-set conditional. |
| R10 | Routing is forced. | Med | Decided 11-12; activation ≈ 12-16..18. |
| R11 | Window contamination. | High | Date filters before reads; field-restricted pre-10-07 log reads; post-11-28-only WP-0(d). |
| R12 | Drift between 0 and −4¢ is unprotected. | Med | Disclosed; K5. |
| R13 | be-exclusion is not conservative for G1. | Med | 5% cap; clipped sensitivity. |
| R14 | Pre-10-07 order history is too thin for h_post/L*/p_amb. | Med | Pinned fallbacks (p_amb 0.5, L* 60 s, h_post 2 s), with viability evaluated at them. h_post = 2 s cannot be validated before the late phase; disclosed. |
| R15 | ≈ 6 agent-days wasted on a floor FAIL. | Low | Accepted for late-phase slack (R4-5). |

## F. Expected value (R4-16)

**Formula.** P(edge | W) = π·P(W|edge) / (π·P(W|edge) + (1−π)·P(W|null)).

**WINNER rates.** WINNER needs an estimate above 1.645 × 0.8 = 1.316¢.
- **P(W|null)**, at a true mean of −0.3¢ with SE ≈ 0.8¢: P(Z > 2.02) ≈ **2.15%** (2.17% unrounded).
- **P(W|+1¢):** P(Z > 0.395) ≈ **34%**.

**Posterior:**
- **π = 3%:** 0.0102 / (0.0102 + 0.0209) ≈ **33%**.
- **π = 2%:** 0.0068 / (0.0068 + 0.0211) ≈ **25%**.

Within 0.2–0.4. **P(WINNER)** ≈ 0.03 × 0.34 + 0.97 × 0.0215 ≈ **3.1%**.

**Value.** At qty 1 and about 9.4 × (1 − d̂) takes per day, a +1–2¢ edge is worth about $0.07–0.19 a day. Expected direct P&L is in cents.

**Option value.** This is the only pre-2027 route to a ratified sender that un-gates the live stages of AUTONOMY rows 7b and 8–12, and that produces real fills.

**Cost.** About 27 agent-days:
- about 13 are early and reusable;
- about 6 are branch builds lost on a floor FAIL;
- the rest are late merges, gates and reviews.

**Recommendation.**
- Run the read-safe early phase.
- Branch-build from 11-20.
- Merge only after a floor PASS and Stage −1 viability.
- Treat a CONFIRM as roughly a one-in-three-to-four chance of a real edge that buys a deployed sender.

## §R3 changelog (retained)

| ID | Section |
|---|---|
| WP-4 timing / S1 | §C.WP-4, §C.7, §C.8 |
| S2 | V13, WP-0(g), WP-5, D.5 |
| S3 | WP-2 |
| S4 | WP-0(f), WP-1 |
| S5 | WP-5 |
| P1 | B.3 |
| P2 | B.1 |
| P3 | C.9 |
| A1 + M4 | A.2.7, A.6, B.1, K3 |
| A2 | WP-0, WP-1, K6 |
| A3 | WP-4 |
| A4 | WP-0(c) |
| A5 | WP-0(b), WP-6, C.7 |
| M0 | B.1 |
| M1 | B.1 |
| M2 | A.2.6 |
| M3 | K5 |
| M5 | A.2.8, WP-0(h) |
| M6 | A.3(l) |
| M7 | B.1, B.2 |

## §R4 changelog

| ID | Section(s) changed |
|---|---|
| R4-1 | §A.2.7 (two-state mixture; p_amb Wilson/fallback; τ_drop = p50 + max(0.10, 2·SE_day); cumulative, ≥ 60 candidates); §B.1 Stage −1; §C.WP-5 K3; §A.3(l) |
| R4-2 | §B.1 viability STOP row; Stage −1 post-drop takes; §B.2; §A.5; §A.6 |
| R4-3 | §A.2.7 arrival source (recorder ts_event); §C.WP-0(d) (rank correlation ≥ 0.9); §A.6 |
| R4-4 | §A.2.7; §B.1 Stage −1 latch inputs; §C.WP-0(c) (no shadow latency claim); §E R14 |
| R4-5 | §C.WP-1 and WP-2 branch timing; §C.7 table and trade-off; §E R15; §F cost |
| R4-6 | §D.3 step 3; §D.4 step 3; §D.5 steps 3 and 5; §C.WP-5 read-back helper (start time, intent state) |
| R4-7 | §C.WP-5 n = 0 ruling and tests |
| R4-8 | §C.WP-5 early guard reshape |
| R4-9 | §D.3 committed read-back; §D.4 step 1 |
| R4-10 | §B.1 be / a* / excluded-set rows; §B.3 tests; §C.WP-1 `test_fee_grid_matches_m5_case` |
| R4-11 | §C.WP-5 K5 |
| R4-12 | §A.2.6 |
| R4-13 | §B.3 `nolong_d12_stage_minus1.py`; §C.WP-5 `nolong_d12_digest_rules.py` |
| R4-14 | §0 V16–V19; §B.3 McDesign coupling and tests |
| R4-15 | §C.WP-0(i); §C.WP-1 merge precondition |
| R4-16 | §B.2 (40 days; tick formula; take arithmetic); §F (2.15%; 33% / 25%) |
| R4-17 | §A.2.4; §A.3(b); §A.6 row; §C.WP-1 digest field and test; §C.WP-5 test |

**Items not satisfied, or deviating:**
1. **No file written.** There is no Write tool; the coordinator saves this text.
2. **R4-14 needed an extra split.** `fq_loss_floor_np_bound._prepare` reaches `fq_loss_floor_mc._world`, which loads FQ's own pool and `HORIZON`. Since `fq_loss_floor_mc.py` may not be edited, r4 splits `_prepare` into a guarded default path and a design-driven `_prepare_from`; the default behaviour is unchanged.
3. **R4-4 fallback cannot be validated early.** h_post = 2 s cannot be checked before the late phase; this is disclosed as R14.
4. **A5 activation estimate.** The forced-routing activation date (≈ 12-16..12-18) depends on when AUT-5a merges, which is unknown.
