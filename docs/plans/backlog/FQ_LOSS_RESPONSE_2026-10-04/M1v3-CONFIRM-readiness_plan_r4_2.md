# M1v3-CONFIRM-readiness plan r4.1 (draft, 2026-10-09)

**Status:** READY r4.2 (2026-10-09). Final scores: security 96, python 96, architect 96, market-math 95. r4.2. It applies the round-5 amendments R42-1..R42-4 (coordinator-authored) to r4.1, committed at a0a2e687. Round-5 scores on r4.1: security 96 READY, market-math 95 READY, architect 94, python 94; both 94s ask only for the amendments applied here. r4.1 applied R41-1..R41-5 to r4 (bdb4f552).

Round-4 scores:
- security 95, READY
- architect 95, READY
- python 91, REVISE
- market-math 94, REVISE

Target: ≥ 95 from every reviewer. r4 rulings stand unless changed here. §R4.1 maps every change.

**Plan of record:** `/home/jon/breezy/docs/evidence/DECISION_ROI_ROUTE_TO_TRADING_2026-10-09.md`, item 2.

**Governing rulings:**
- `/home/jon/breezy/docs/evidence/RULING_FQ-v2-NO-TRADE_2026-10-08.md`
- `/home/jon/breezy/docs/evidence/RULING_B3_permit_window_posture_2026-09-25.md`
- `/home/jon/breezy/docs/evidence/RULING_permit_daily_coverage_2026-09-25.md`
- the operator directive of 09-29
- the two operator caps (already set; never assigned here)

**Hard rules, for every work package and every brief:**
- Never open tape, settlement or truth data for climate days **2026-10-07..2026-11-28** before the single read on or after 2026-12-07.
- Node logs and evidence dated before 2026-10-07T00:00Z may be read only through the allowlisted log reader. It returns latency, AMBIGUOUS/resolution timestamps and fee fields only (R41-5A).
- Never edit `/home/jon/breezy/docs/evidence/m1v3/PREREG.json`.
- Nautilus Trader is immutable.
- `allow_short` stays False.
- No operator cap is assigned.
- Never weaken a safety, contract or NO-SEND test. Any guard whose shape changes is narrowed and security-reviewed.
- Every brief states the exact interpreter path and PYTHONPATH, says "format only your files", forbids `uv sync`, and sets `--basetemp` under `~/.cache`.

## 0. Verified facts

**V1–V19 are carried from r4.**

| # | Fact | Location |
|---|---|---|
| V1 | Frozen M1-v3 pins | — |
| V2 | M1V3-R1 conflict | — |
| V3 | Closed-set mirrors | `/home/jon/breezy/src/breezy/persistence/family_manifest.py:116-121`; `/home/jon/breezy/src/breezy/runtime/trade_supervisor_core.py:164`; `/home/jon/breezy/src/breezy/strategy/autonomy/node_plugins.py:13`; `/home/jon/breezy/src/breezy/analysis/autonomy/offline_plugins.py`; `/home/jon/breezy/src/breezy/persistence/autonomy/paths.py:28-29`; `/home/jon/breezy/src/breezy/strategy/current_rung_hold/family_id_arg.py:20`; `/home/jon/breezy/src/breezy/persistence/autonomy/pins.py:28`; `/home/jon/breezy/src/breezy/persistence/autonomy/resolver.py:462` |
| V4 | Allowlist | — |
| V5 | AST guard; `trade.py` is 1274 lines | — |
| V6 | Permit gap | `trade_supervisor_core.py:37-39`, `:40`, `:139`, `:1082`, `:1188-1197`, `:1205`, `:1395-1404` |
| V7 | Schedule consumers | — |
| V8 | Singleton submit intent | `/home/jon/breezy/src/breezy/runtime/submit_intent.py:386-422` |
| V9 | Floor MC constants | — |
| V10 | No producer; FQ-scoped guard | — |
| V11 | Stations; connection sharding | — |
| V12 | AUT-5 file ownership | — |
| V13 | Node stop path | `/home/jon/breezy/deploy/systemd/breezy-trade-supervisor.service:150-165`; `/home/jon/breezy/src/breezy/runtime/trade_supervisor.py:1230-1290` |
| V14 | e2 epoch_grid | `fq_loss_floor_mc_e2.py:13,231` |
| V15 | validate_ii 16:50 anchor | `validate_ii.py:146-149,378-386` |
| V16 | `epoch_grid` has no epochs parameter | `fq_loss_floor_mc_gate.py:151-153` |
| V17 | np_bound guards and `_world` | `fq_loss_floor_np_bound.py:145-151` |
| V18 | Engine keys on `config.freeze` | `fq_loss_floor_mc_engine.py:231-234` |
| V19 | Report keys on `config.freeze` | `fq_loss_floor_mc_report.py:199,202,249` |

**V20–V22 are new in r4.1, read directly at `/home/jon/breezy/scripts/analysis/fq_loss_floor_np_bound.py:140-354`.**

**V20. `_prepare` (`:146-170`).**
- The `_MIXSET` guard is at `:147-148` and the `DEFAULT_FREEZE` guard at `:149-150`.
- `_world(args)` is called at `:151`.
- `pooled` is built over all of `MIXES` at `:153`.
- An empty-mix `RuntimeError` is raised at `:154-156`.
- `n_long = inclusive_days(DEFAULT_FREEZE, HORIZON)` at `:169`.

**V21. `_run` (`:261-333`).**
- `_diagnostics(_EVIDENCE)` at `:263`. `_EVIDENCE` is FQ's `docs/evidence/f5/fq_loss_floor_mc_seed20261008.json` (`:85`).
- `_load_pins()` at `:264`, imported from `fq_loss_floor_mc.py:113`.
- Mix loops at `:267`, `:271`, `:274` and `:289`.
- `epoch_grid(DEFAULT_FREEZE)` and `HORIZON` at `:283-284`.
- `d1_decision(..., e_proj=E_PROJ)` at `:305-306`.
- The document carries FQ provenance: `a0_sha`, `a1_frozen_sha`, `evidence_sha256`, `MIXSET` (`:313-316`).
- `_benchmark` (`:336-354`) loops over `MIXES` at `:343` and `:346`.

**V22. Hard-coded likelihood-ratio shift and decision date.**
- `_family` (`:201`) and `_score_row` (`:227-228`) use `DELTA_H1`.
- `d1_decision` uses `E_PROJ`.
- Both come from `/home/jon/breezy/scripts/analysis/fq_loss_floor_np_stat.py:77-78`: `E_PROJ = "2026-11-01"` and `DELTA_H1 = -0.16`.
- So the NP shift and the decision date are hard-wired to FQ's values.
- `log_lr_totals` and `d1_decision` already accept `delta=` and `e_proj=` as keyword arguments. The design path can therefore inject them without editing `fq_loss_floor_np_stat.py`.

The critical path is items 1–7 plus item 8 (WP-4). Trading D-1_18Z is prohibited by §A.3(a).

## A. DRAFT ruling (item 1): `RULING_M1v3-CONFIRM-T2-SENDER_<ratification-date>`. Draft, not in force.

**Ratification requires all of the following:**
1. A WINNER read under A.1.
2. The §B floor frozen, with a binding PASS committed **before the read is opened**.
3. Stage −1 viability PASS (§B.1).
4. The WP-4 B3 re-open ruling committed.
5. Converged review from trading-bot-architect, prediction-market-reviewer and security-reviewer.

A draft is never cited by an allowlist row or by a manifest.

### A.1 Condition

The report from `/home/jon/breezy/scripts/analysis/no_longshot_pooled_test.py` must meet all of these:
- it is committed under `/home/jon/breezy/docs/evidence/m1v3/`;
- its HEAD descends from adb1cd8b;
- it is READ, with `verdict == "WINNER"`;
- `bca_failed` is not true.

The report's sha256 is pinned. **"CONFIRM" means exactly this.**

### A.2 What is ruled on CONFIRM

1. **Sender.** `pm_us_nolong_d12_v1` (kind `no_longshot_d12`) is a permitted T2 sender. §B is its floor prereg.
2. **M1V3-R1 is superseded for this family's sender eligibility only.** AS-R6 stays in force.
3. **The 09-29 directive.**
   - The outcome term is NWS CLI FINAL; the price enters only as cost. So the circularity objection does not apply.
   - The letter of the directive is breached, because price selects the take. That breach is accepted as a narrow exception for this one family, decided by the peer loop.
   - If any peer rejects this, §A.5 applies.
4. **Population**, frozen with §B by 11-20:
   - D0 only: the first Depth10 update the node receives with `ts_event` in [12:00, 13:00)Z, per YES rung.
   - NO ask = 1 − best YES bid (size ≥ 1).
   - Take iff NO ask ≥ 0.90, inclusive, across all of [0.90, 0.99]. **0.99 asks are taken**, because a sub-band is banned by A.3(b).
   - BUY NO, qty 1, IOC, limit = the ask.
   - One evaluation per (station, D, rung); hold to settlement.
   - Stations: LAX, MDW, MIA and SFO. Add NYC only if WP-0(a) shows support by 11-20. The default is these four.
   - Parity is disclosed in A.6.
5. **Gates:**
   - the permit;
   - the live-orders gate, with an exact allowlist row;
   - the family halt;
   - the fee-drift probe;
   - the loss stop;
   - the submit-intent latch;
   - K1–K7;
   - both operator caps, unchanged.
6. **K4 (pinned).**
   - C_d = node-evaluated rungs on day d whose first in-window NO ask is ≥ 0.90. Counted from the funnel, independent of fills, the latch and caps.
   - Day model: NB(μ, α), with var = μ + αμ², fitted on pre-window days 08-30..10-06. Fall back to Poisson if α̂ ≤ 0.
   - 14-day block: μ_b = 14μ, var_b = μ_b + (α/14)μ_b².
   - Inflation: φ = 1 + 2·Σ_{k=1..3} max(0, ρ_k)·(1 − k/14).
   - Back to NB: α′ = max(0, (φ·var_b − μ_b)/μ_b²). If α′ = 0, use Poisson.
   - Tail: p = min(1, 2·min(F(S), 1 − F(S−1))).
   - **Trip iff p < 0.01 AND S/μ_b ∉ [0.5, 2.0].**
   - Implemented with pure `math.lgamma`, no scipy.
7. **Latch drop model, viability and K3 (R41-2, R41-3).**

   **Hold model.** Two states. Each order holds the singleton latch for:
   - **non-AMBIGUOUS** (on this venue, a fill): **h_post** = the pre-window p95 POST round-trip.
   - **AMBIGUOUS** (every IOC miss is AMBIGUOUS on this venue, because strict ZERO_FILL is unreachable): the hold is drawn from the **empirical pre-window resolution-time distribution**, quantised **up** to the GET offset schedule {2, 7, 15, 30, 60} s and capped at 60 s. This replaces a fixed L*.

   **p_amb** = the upper 95% Wilson bound of the AMBIGUOUS rate. Because every IOC miss is AMBIGUOUS, p_amb is in effect the IOC miss rate.

   **Minimum history.** Measured p_amb, h_post and the resolution distribution are used only if the pre-10-07 live order history contains **n ≥ 30 orders**. Below that:
   - viability is evaluated at the **fallback constants** (p_amb = 0.5, ambiguous hold = 60 s, h_post = 2 s), **and**
   - at the **Wilson point estimate** of whatever history exists.
   - If the STOP trips only under the fallback, it is recorded as **STOP-UNMEASURED**. It still shelves (A.5), but it is never presented as a population finding.
   - **The fallback is in effect a STOP.** Its mean hold is 0.5·60 + 0.5·2 = 31 s. Against the 12:00Z burst, that almost surely yields d̂_p90 > 0.30.

   **AMBIGUOUS-shape minimum (R42-4).** Even with n ≥ 30 orders, the empirical resolution-time distribution is used only if the history contains **n_amb ≥ 10 AMBIGUOUS orders**. Otherwise the AMBIGUOUS state uses the fallback hold of 60 s, while the measured p_amb (Wilson upper) and h_post are still used. n_amb and this threshold are frozen in §B.

   Stage −1 reports which inputs were used (measured or fallback) and reports p_amb by ask band where the history allows.

   **Replay.** Candidate arrival order is the recorder `ts_event`. For each pre-window day, the replay runs **1,000 seeded draws** of the hold mixture; **day-level d̂ = the mean over those draws**. p50 and p90 are then taken **across days**, along with the day-clustered SE.

   **Viability STOP.** STOP iff **d̂_mix_p90 > 0.30**. This intentionally uses p90: it tests for a bad-day population mismatch, where the live population is not the screened one.

   **τ_drop** (typical-day monitoring) = **min(0.40, d̂_mix_p50 + max(0.10, 2·SE_day))**. K3's drop test is cumulative since activation, evaluated only once there are ≥ 60 candidates.

   All inputs, the procedure and the thresholds are frozen in §B.
8. **Fee (M5).** WP-0(h) classifies the venue fee at qty 1 on 0.90..0.99, from evidence before 10-07.
   - **(a)** Venue fee ≤ screen primary: no adjustment.
   - **(b)** Exceeds by ≤ 1¢: ratification also requires the read report's slippage = 2¢ row to have LB > 0. If that row has no LB, STOP.
   - **(c)** Exceeds by > 1¢: STOP.

   The case is recorded in §B and determines the excluded ask set.

### A.3 What the M1-v3 result may NOT be used for

- **(a)** Any other window.
- **(b)** A sensitivity cell: an ask sub-band (including skipping 0.99), slippage, or fee.
- **(c)** Any unscreened filter: depth, time, weather, or a station chosen after the read.
- **(d)** Evidence for FQ v2, any forecast family, any model variant, AUT-S, or `screen.py`.
- **(e)** An edge size. Only the lower bound is cited.
- **(f)** Re-reading, re-running or extending the screen, or relabelling its result.
- **(g)** Any change to qty or caps.
- **(h)** Any side other than BUY NO.
- **(i)** Any venue other than Polymarket.us.
- **(j)** Choosing epochs, horizon or activation after the read. Activation after 01-20 = shelve.
- **(k)** Bypassing a FAIL, an unrun §B, or a non-viable §B.
- **(l)** Changing any K1–K7 threshold or formula, any latch input, the drop procedure, or any §B parameter after the read.

### A.4 Relationships

- RULING_FQ-v2-NO-TRADE stays for FQ v2.
- B3 (a′) is decided by WP-4.

### A.5 Any other outcome = shelve

This covers:
- NO-EDGE, UNDERPOWERED or INVALID;
- PENDING_TRUTH past 12-21;
- a §B FAIL;
- a Stage −1 viability STOP, **including STOP-UNMEASURED** (recorded as such, never as a population finding);
- an unratified WP-4;
- any WP-0 or M5 STOP;
- a peer rejection.

**Effects:**
- the manifest stays DRAFT or is removed by review;
- no allowlist row is added;
- the code is inert and the branches stay unmerged;
- the drop-in stays;
- nothing goes live;
- PROGRESS records the outcome;
- any re-test needs a new prereg and plan.

### A.6 Screen/live parity (disclosed)

| Dimension | Screen | Live | Disclosure |
|---|---|---|---|
| Window and selector | First tape row in [12, 13)Z | First node update in [12, 13)Z | WP-0(d): first-row parity ≥ 95% and arrival-order rank correlation ≥ 0.9, else STOP. |
| Incomplete station-day | Excluded whole (MNAR) | Takes per rung | K4b. |
| Truth | FINAL required | Unknown at decision | Reported at settlement. |
| Empty YES bid | No take, counted | Same | Parity. |
| Take-all vs serial latch | Takes every qualifying rung-day | Drop-not-queue | d̂_mix p50/p90, post-drop takes/day, and the inputs used (measured/fallback) are entered at the §B freeze. Viability STOP at p90 > 0.30. |
| **Latch-input representativeness (R41-3)** | — | p_amb (≈ the IOC miss rate), h_post and resolution times come from pre-10-07 FQ v1 and earlier orders. Those orders had different asks and sides (mostly D+1, not NO ≥ 0.90). | The rates may not represent NO at ask ≥ 0.90. p_amb is reported by ask band where possible. |
| Execution | Blind | IOC misses, AMBIGUOUS, cap truncation | K3, K6. |
| 0.99 asks | Included | Included | Digest reports the attempted share at ask ≥ 0.99 (≥ 0.98 under M5 case b). These legs are excluded from the floor MC. |
| Stations | All on tape | Pinned set | NYC decided by 11-20. |
| Fee | Screen primary | Venue fee | M5; fee probe. |

**Analysis population.**
- The screen covers all qualifying candidates. Live trading takes a time-ordered subset of them, before cap truncation.
- If arrival order within the burst correlates with ask or outcome, the subset's EV differs, and the CONFIRM does not cover that difference.
- K1 is computed on attempted orders. K3 and K4 are computed on candidates.
- The digest reports the bins of attempted vs dropped candidates.
- Queueing is rejected: a queued order would face a later book, which is a different population.

## B. Loss-floor MC/NP design for `pm_us_nolong_d12_v1` (item 4)

**Prereg:** `/home/jon/breezy/docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04/NOLONG_D12_floor_prereg.json`.

**Schedule:**
- Frozen by a gated dedicated commit **on or before 2026-11-20**, after Stage −1 is committed.
- Binding run 11-21..11-27, with a memory cap, `RuntimeMaxSec` and a stall watch; one heavy job at a time.
- The result is committed before the read.
- The verdict binds.

### B.1 Pre-declared design

**Pool and costs**

| Element | Value |
|---|---|
| Mix | `design.mixes = ("M-no",)`. The pool holds only NO legs with ask ≥ 0.90 at the D_12Z first row, pinned stations. NYC pool is informational. |
| Data | PM.us Depth10 tape for **2026-08-30..2026-10-06**, filtered at the directory index before any read. Days ≥ 10-07 are refused (exit 3). Truth for days ≤ 10-06 is read only if `rho_hat` requires it. |
| be | be = a + max(rounded_fee(a), θ·a(1−a)) + 0.01, θ = 0.0695. The venue fee enters only via M5. Exclusion rule: be ≥ 1. |
| a* | Solve 0.0695x² + 0.9305x − 0.01 = 0 with x = 1 − a: x = (−0.9305 + √0.86861025)/0.139 = 0.0107381, so **a\* ≈ 0.98926**. |
| Excluded ask set | Case (a): {0.99}. Case (b): {0.98, 0.99}. Case (c): STOP before any run. |
| Exclusion cap | > 5% of legs excluded under the classified fee = FAIL. A clipped-be = 0.995 sensitivity is informational. Exclusion is not conservative for G1. Excluded asks are still traded live. |
| Feasibility | H0: Σq ≤ 1; > 5% infeasible station-days = FAIL. H1 at δ = −0.04: Σ(q + \|δ\|) ≤ 1; infeasible station-days are excluded from the bar's H1 draws; > 5% = FAIL. δ = −0.08 and −0.16 use the existing fallback and are informational. |

**Statistical design**

| Element | Value |
|---|---|
| α ladder | `ALPHA_FLOOR_GRID`. Escalate on G1 only. A G3 miss vetoes. |
| δ grid | Design-only: (−0.16, −0.08, −0.04, −0.02). FQ's default `DELTAS` is unchanged. **Bar δ = −0.04, which is also the NP-bound H1 shift `design.np_delta` (V22).** Drift between 0 and −4¢ is unprotected. |
| Epochs and horizon | Epochs {2026-12-23, 2027-01-06, 2027-01-20}; horizon 2027-02-28, the terminal date. freeze = epochs[0]. **`design.e_proj = "2027-01-20"` (V22).** Activation after 01-20 = shelve. |
| G-gate | G1 holds, and G3(−0.04) ≥ 2.5·α at every epoch. |
| D1-analogue | NP upper bound on G3(−0.04) at α_eff ≥ 0.30 at every epoch. No switch to nominal α. |
| Seeds | Floor run 20261121; Stage 0 20261122; 10k replicates each. Stage −1 replay 20261120. **Drop-thinning 20261123.** |
| **Drop thinning (R41-4)** | Stage 0 and the binding floor runs thin each pool day's takes to the post-drop population. Each pool day keeps the candidates retained by **one seeded draw (20261123) of that day's mixture replay**, i.e. time-order-faithful thinning. The day's expected keep fraction equals 1 − d̂_day. `lambda_pool` and the take-rate inputs are recomputed on the thinned pool. **Informational sensitivity:** uniform thinning to keep probability 1 − d̂_mix_p90. |
| Sensitivities | ±50% take rate at every epoch, including 01-20. NYC pool. Clipped-be pool. p90 thinning. All informational. |

**Stage −1 and viability**

**Stage −1** uses pre-window data only and is committed before the freeze. It reports:
- path ticks per epoch, and S (station-days with takes per day);
- the K4 inputs;
- the K5 reference shares;
- legs per station-day;
- exclusion and feasibility counts;
- recorder-`ts_event` arrival order and gaps, plus the share of candidates at 12:00:00–05Z;
- the latch inputs per A.2.7, including n_orders, whether each was measured or a fallback, and p_amb by ask band;
- d̂_mix p50/p90 and SE_day;
- τ_drop;
- **measured λ₄** (the four-station candidate rate) and post-drop takes per day, λ₄·(1 − d̂_mix_p50).

**Viability**
- **STOP iff d̂_mix_p90 > 0.30.** If it trips only under the fallback constants, the outcome is **STOP-UNMEASURED** (A.2.7).
- **Condition 2 (R41-4).** Take the measured post-drop takes over the 40 days from 01-20 to 02-28, i.e. 40·λ₄·(1 − d̂_mix_p50). Compare it with the takes-needed figure Stage 0 emits at δ = −0.04. **The existing Stage 0 emits no takes-needed figure** (no such field in `fq_loss_floor_np_bound.py` or `fq_loss_floor_np_stat.py`). So **condition 2 is informational**: it is reported, never a STOP. The 156 literal is dropped. **The floor run is the binding authority.**

**Other**

| Element | Value |
|---|---|
| Freeze check | `check_frozen_blob` plus introduced-blob check (`/home/jon/breezy/scripts/analysis/prereg_precommit_check.py`). |
| Amendment | Readable by `/home/jon/breezy/scripts/analysis/prereg_amendment_check.py`. Otherwise WP-5's per-family loader, which fails closed. |

### B.2 Path argument (a hypothesis, tested in Stage −1 and Stage 0)

**FQ v2 for comparison.**
- M-yes: median ≈ 7 ticks; α_eff 0.0187; NP 0.1186; `bound_upper_min` 0.125 vs a 0.30 bar; A1 G3 0.2104.
- M-no: 0.4927 at 11-01, but G3 0.2334 at 12-01.

**This family**, from 01-20 to 02-28 (**40 days**):
- **Ticks** = 40·S·(1 − d̂_mix_p50), using the Stage −1 S.
- **Takes** = 40·λ₄·(1 − d̂_mix_p50), using the **measured λ₄**. M1's ≈ 9.4/day is a prior only.
- If λ₄ ≈ 9.4, takes ≈ 376(1 − d̂). At −50%, takes ≈ 188(1 − d̂), which is marginal; it is reported, never a STOP.
- Whether these suffice at δ = −0.04 is decided by the thinned Stage 0 and floor runs, not by this arithmetic.

**Counter-hypotheses:**
- fat single losses near ask ≈ 0.97;
- winter ask-mix drift (K5);
- exclusions and drops reduce ticks.

### B.3 Tooling (WP-A; scripts only; 11-09..11-19)

**Golden files first.** A separate earlier commit adds `/home/jon/breezy/tests/fixtures/fq_floor_golden/`, holding A1, Stage-0 and E2 subset outputs at the current HEAD.

**McDesign (R4-14 and R41-1).** A frozen dataclass in `fq_loss_floor_mc_gate.py`:

```
McDesign(epochs, horizon, deltas, mixes, np_delta, e_proj)
```

- `freeze` is a property equal to `epochs[0]`.
- `DEFAULT_DESIGN` is `(epoch_grid(DEFAULT_FREEZE), HORIZON, DELTAS, MIXES, DELTA_H1, E_PROJ)`.
- `DELTA_H1` and `E_PROJ` are imported from `fq_loss_floor_np_stat.py`, which is **not edited**.
- The nolong design is `((12-23, 01-06, 01-20), 02-28, (−0.16, −0.08, −0.04, −0.02), ("M-no",), −0.04, "2027-01-20")`.

**Changes per file.**

- **`fq_loss_floor_mc_gate.py:151-153`.**
  - `epoch_grid` is unchanged.
  - Add `design_epoch_grid(design) -> design.epochs`.
- **`fq_loss_floor_mc_engine.py:231-234` and `fq_loss_floor_mc_report.py:199,202,249`.**
  - Take `design=DEFAULT_DESIGN` (keyword-only).
  - Key on `design.freeze` / `design.epochs`, and loop over `design.mixes`.
  - Assert `config.freeze == design.freeze`.
- **`fq_loss_floor_mc_e2.py:231`.**
  - Use `design.epochs[0]`.
- **`fq_loss_floor_np_bound.py`**, against the V20–V22 lines.
  - **`_prepare(args)`, the default path.** Unchanged: the `_MIXSET` / `DEFAULT_FREEZE` guards (`:147-150`), `_world` (`:151`), the all-MIXES pool (`:153`) and its empty check (`:154-156`). It builds `_Prepared` via `_prepare_from(config, gate_groups, DEFAULT_DESIGN)` after those guards.
  - **New `_prepare_from(config, groups, design)`.**
    - Builds `pooled` **only over `design.mixes`**.
    - Raises the empty-mix RuntimeError **only within `design.mixes`**.
    - Sets `n_long = inclusive_days(design.freeze, design.horizon)`.
    - Never calls `_world`.
  - **New `_run_design(prepared, design, evidence, *, seed, replicates)`.**
    - The mix loops (`:267`, `:271`, `:274`, `:289`) iterate `design.mixes`.
    - The epoch loop (`:283-284`) uses `design.epochs` and `design.horizon`.
    - `_family` and `_score_row` take `delta=design.np_delta` (replacing `DELTA_H1` at `:201` and `:227-228`).
    - `d1_decision` and `d1_point_decision` take `e_proj=design.e_proj` (`:305-306`).
    - `c_binding`, `t_min` and the provenance fields come from the injected `evidence` object, never from `_diagnostics(_EVIDENCE)` or `_load_pins()`.
  - **`_run(args)`.** Becomes `_run_design(_prepare(args), DEFAULT_DESIGN, FqEvidence(_EVIDENCE, _load_pins(), _A1), ...)`. The document is identical to today's **except for `git_head` and `script_blob_sha`**, which change with any commit or refactor and are masked in the golden comparison (R42-2). It keeps `a0_sha`, `a1_frozen_sha`, `evidence_sha256` and `"MIXSET": list(MIXES)` (`:313-316`).
  - **Document fields read from the design (R42-1).** In `_run_design`, `"MIXSET"` (`:316`) is `list(design.mixes)` and `"e_proj"` (`:317`) is `design.e_proj`. A nolong result document therefore records `("M-no",)` and `2027-01-20`, never FQ's `MIXES` or `2026-11-01`.
  - **Provenance blobs (R42-2, R42-3).** `script_blob_sha` keeps hashing `fq_loss_floor_np_bound.py` (the entry module). If `_run_design` moves to `fq_loss_floor_np_design.py` under the line-budget rule, the document adds `design_blob_sha` for that module. `stat_blob_sha` stays the `fq_loss_floor_np_stat.py` blob, so it agrees with `test_fq_loss_floor_np_stat_py_blob_unchanged`.
  - **`_benchmark` (`:336-354`).** Default-path only; the nolong driver never calls it.
  - **The `Evidence` protocol** exposes:
    - `c_binding`;
    - `t_min`;
    - `provenance() -> dict` (FQ: the four existing fields; nolong: `design_mixes`, `nolong_prereg_frozen_sha`, `nolong_floor_result_sha256`).
  - **Line budget.** np_bound is 413 lines today. If the refactor takes it past 480, move `_prepare_from`, `_run_design` and `Evidence` into `/home/jon/breezy/scripts/analysis/fq_loss_floor_np_design.py` (≤ 250 lines). This is pre-declared.
- **`/home/jon/breezy/scripts/analysis/fq_loss_floor_mc.py`: not edited** (its blob is pinned in F5).

**New `/home/jon/breezy/scripts/analysis/nolong_d12_floor_config.py` (≤ 200 lines, R41-1).**
- Builds `FloorConfig` and gate groups from the thinned Stage −1 pool and the **frozen NOLONG_D12 prereg**.
- Replaces `_world` / `plan_floor_rates` for this family:
  - `lambda_pool`, `take_rate_lower`, `r_sd`, `lambda_sd`, `half_spread`, `pool_exit_fraction`, `rho_hat` and θ come from Stage −1 and prereg values;
  - `freeze` and `horizon` come from the design.
- Provides `NolongEvidence`. Its c_binding and t_min come from the binding nolong floor run's committed result, which is pinned in the prereg's result field.
- **Never reads FQ evidence or FQ pins.**

**RED tests: shared modules.**
- `test_fq_design_default_matches_golden_a1_subset`
- `test_np_bound_default_matches_golden_stage0_subset`
- `test_default_run_unchanged_golden` (R41-1, R42-2): `_run` document equal to the golden with `git_head` and `script_blob_sha` masked; every other field byte-identical
- `test_e2_default_matches_golden`
- `test_np_bound_injected_nondefault_freeze_and_epochs`
- `test_design_epoch_grid_never_returns_epoch_fixed_for_injected_design`
- `test_deltas_default_unchanged_minus_002_only_via_design`
- `test_np_delta_and_e_proj_injected_not_module_constants` (V22, R42-1): also asserts the emitted document's `e_proj == design.e_proj` and `MIXSET == list(design.mixes)`
- `test_provenance_blob_fields_name_their_modules` (R42-2, R42-3)
- `test_fq_loss_floor_mc_py_blob_unchanged`
- `test_fq_loss_floor_np_stat_py_blob_unchanged`

**RED tests: `nolong_d12_floor_config.py`.**
- `test_floor_config_from_prereg_no_fq_pins`
- `test_prepare_from_no_only_m_no_pool_does_not_raise`
- `test_run_design_iterates_design_mixes_only`
- `test_run_design_uses_injected_evidence_and_pins`
- `test_drop_thinning_seeded_time_order_faithful`
- `test_lambda_pool_recomputed_on_thinned_pool`

**`/home/jon/breezy/scripts/analysis/nolong_d12_mc_templates.py` (≤ 300 lines). RED tests:**
- `test_refuses_climate_day_on_or_after_2026_10_07`
- `test_date_filter_precedes_any_tape_read`
- `test_be_uses_screen_primary_cost`
- `test_be_threshold_excluded_set_matches_m5_case`
- `test_excluded_leg_share_over_5pct_fails_under_classified_fee`
- `test_clipped_be_sensitivity_never_binding`
- `test_pool_all_legs_side_no_ask_ge_090`
- `test_h0_sum_q_feasibility_counted`
- `test_h1_feasibility_counted_and_excluded_at_bar`
- `test_d12_first_row_only`
- `test_no_ask_none_counted_not_synthesised`

**`/home/jon/breezy/scripts/analysis/nolong_d12_stage_minus1.py` (≤ 300 lines; fully typed; `math.lgamma`; no scipy).**

Pre-declared split: if the first commit exceeds 300 lines, the log reader and the Wilson bound move to `/home/jon/breezy/scripts/analysis/nolong_d12_latch_inputs.py` (≤ 200 lines).

RED tests:
- `test_nb_fit_moments`
- `test_nb_poisson_fallback_when_alpha_le_0`
- `test_rho_floored_at_zero`
- `test_alpha_prime_mapping`
- `test_nb_two_sided_tail_min_cdf_sf`
- `test_dmix_day_mean_over_1000_seeded_draws_p50_p90_across_days` (R41-2)
- `test_ambiguous_hold_empirical_quantised_to_get_offsets_capped_60` (R41-3)
- `test_ambiguous_shape_needs_n_amb_ge_10_else_60s_hold_with_measured_p_amb` (R42-4)
- `test_p_amb_wilson_upper`
- `test_min_history_30_else_fallback_and_point_estimate_both_run` (R41-3)
- `test_stop_unmeasured_label_when_only_fallback_trips` (R41-3)
- `test_tau_drop_formula_capped_at_040` (R41-2)
- `test_viability_stop_when_dmix_p90_gt_030`
- `test_viability_condition2_informational_when_no_takes_needed_field` (R41-4)
- `test_p_amb_by_ask_band_reported`
- `test_refuses_any_input_on_or_after_2026_10_07`
- **`test_log_reads_pre_1007_field_allowlist_and_date_filter` (R41-5A).** The reader emits only allowlisted fields: latency, AMBIGUOUS/resolution timestamps and fee. It refuses any file or line at or after 2026-10-07T00:00Z with exit 3, and never returns price or settlement fields.

**`/home/jon/breezy/scripts/analysis/nolong_d12_floor.py` (≤ 200 lines).** Drives `nolong_d12_floor_config` → `_prepare_from` → the engine and `_run_design`. RED tests:
- `test_refuses_unfrozen_prereg`
- `test_no_nominal_alpha_path_after_result`
- `test_epoch_holds_required_at_every_epoch`
- `test_h0_h1_at_most_one_losing_leg_per_station_day`
- `test_sensitivity_takes_rate_pm50_reported_at_every_epoch_including_01_20`
- `test_p90_thinning_sensitivity_informational`
- `test_never_calls_benchmark_or_world`

**Gate:**
- focused tests;
- the mypy-strict ratchet;
- `lint-imports` from the tree root (must report "N kept, 0 broken");
- then the full gate.

**Effort (R41-1): 6.5 d build, 1.5 d review.**

## C. Code work packages

### WP-0: verify first (read-only)

**Early phase (starts at plan READY, R42-5; ends 11-19)**

**(c0) Order-history count, first (R42-5).** In the first 1–2 days, count the pre-10-07 orders (n) and AMBIGUOUS orders (n_amb) through the allowlisted log reader. If n < 30, the fallback applies and Stage −1 will almost surely give STOP-UNMEASURED. In that case, run Stage −1 viability **before** any other early spend, and shelve if it STOPs.

**(a) NYC.** Support decided by 11-20. Default: four stations.

**(b) Routing.** Decision by 11-12.
- If routing is forced, it costs 5–6 d.
- Otherwise the node boots from env.

**(c) Latch mechanics.**
- Read `/home/jon/breezy/src/breezy/runtime/submit_intent.py:386-422` and the AMBIG-LATCH B resolver.
- Locate the pre-10-07 node log files that hold order POST, AMBIGUOUS and resolution timestamps, and count the orders against the n ≥ 30 rule.
- Shadow mode never measures order latency.

**(e) Mirror grep.** Grep for further mirrors and re-verify `validate_ii.py:488`.

**(f) Exec-pin row.** Resolve the exec-pin file/row for `src/breezy/strategy/no_longshot_d12/strategy.py`. The candidate is `/home/jon/breezy/tests/contract/test_us_source_ingest_egress_guard.py:608`. Confirm the SELL/BUY_SHORT translation is reused. This is a **WP-1 strategy merge precondition**.

**(g) Node-stop procedure.** Find the existing procedure, or add the read-back helper in WP-5.

**(h) M5 fee classification.**

**(i) Package registration.** Strategy-package enumeration tests and import-linter contracts must stay green for `strategy/no_longshot_d12/` before the early `decision.py` merge.

**Late phase (11-28 onward)**

**(d) Shadow-node parity.** Using the post-11-28 recorder against a scratch shadow node:
- first-row parity ≥ 95%;
- median per-day arrival-order Spearman correlation ≥ 0.9.

Otherwise STOP.

**Latch ceiling.** L = 60 s everywhere. GET-resolve runs at +2, +7, +15, +30 and +60 s. Still unresolved at 60 s means the intent stays OPEN and K6 applies.

### WP-1: strategy, `/home/jon/breezy/src/breezy/strategy/no_longshot_d12/` (3.5 d)

**Files:**
- `config.py` (`shadow_only=True`)
- `decision.py` (early; precondition WP-0(i))
- `strategy.py`
- `composition.py`

**Latch policy:**
- Serial arm → POST → retire.
- A candidate that arrives while an intent is OPEN is dropped and counted.
- GET-retire follows the schedule above.

**Digest fields:**
- candidates, attempted, filled, zero_fill, latch_dropped;
- ambiguous_resolved, ambiguous_open;
- attempted vs dropped bins;
- the attempted share at ask ≥ 0.99 (≥ 0.98 under case b).

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
- `test_fee_grid_matches_m5_case`
- the WIDENED exec-pin row

**Replay** (not a RED test): pre-window data only; ≥ 99% match.

**Branch.** From 11-20; inert and unmerged until the late phase.

### WP-2: composition, dispatch and guards (3 d; branch from 11-20; merged late)

Unchanged from r4:
- Mirror widening, with tests for each V3 site.
- `/home/jon/breezy/src/breezy/app/compose_no_longshot.py`.
- The `_live_orders_gate_preamble` helper.
- `trade.py` stays oversize; AUT-5 owns it.
- The AST guard is narrowed, with one reviewed site, and `test_gate_preamble_binds_from_live_orders_authorized` plus positive controls.
- Dispatch tests, including the FQ negative control and the specific SettingsError plus log line.
- The focused gate list.

### WP-3: manifest and allowlist (0.5 d; late)

Unchanged from r4:
- The DRAFT manifest.
- `test_live_orders_allowlist_is_exactly_fq_v1_row`. At activation it is replaced by an exact two-row pin.

### WP-4: per-kind schedule (6 d; early on a branch; merged late)

Unchanged from r4:
- Branch-only early.
- The late merge needs GATE_EXIT=0, a security re-review and AUT-5a sequencing.
- The B3 re-open ruling, which includes the A3 fixed sites (valid only while the family is not registry-routed).
- The `KindSchedule` table.
- The RED tests.

### WP-5: hold, loss stop, kill rules, read-back (4 d)

Unchanged from r4:
- The producer.
- The n=0 ruling: verifiably-empty ledger and the stale-1-day rule, with its tests.
- The early additive guard reshape, signed off by security, with no nolong writer row and fail-closed amendments.
- The digest module `/home/jon/breezy/scripts/analysis/nolong_d12_digest_rules.py`.
- K1–K7.
- The threshold tests. K3 now uses τ_drop as defined in A.2.7, including the 0.40 cap.

**Read-back helper (R41-5B).** `/home/jon/breezy/scripts/ops/node_pid_readback.py` is read-only and reports:
- the lock holder's PID, cmdline and start time;
- whether the lock is free;
- the submit-intent state.

**An unreadable or corrupt intent file is reported as non-terminal, which blocks restart.**

RED tests:
- `test_readback_reports_lock_holder_pid_and_starttime`
- `test_readback_reports_intent_state`
- **`test_readback_unreadable_intent_treated_non_terminal`**
- `test_readback_never_signals`

### WP-6: merge order with AUT-5a (1.5 d; + 5–6 d if routed)

Unchanged from r4.

### C.7 Effort and schedule

| WP | Phase | Build | Review | Merges |
|---|---|---|---|---|
| WP-A (np_bound refactor, floor_config, Stage −1, templates, driver) | early | **6.5 d** | **1.5 d** | 3 |
| WP-0 (a–c, e–i) | early | 1.5 d | — | — |
| WP-0 (d) | late | 0.5 d | — | — |
| WP-1 `decision.py` | early (inert) | 1 d | 0.5 d | 1 |
| WP-4 (ruling + branch) | early, branch only | 5 d | 1 d | 0 |
| WP-5 guard reshape | early (security sign-off) | 1 d | 0.5 d | 1 |
| WP-1 strategy | branch from 11-20 | 2.5 d | 0.5 d | 0 early |
| WP-2 | branch from 11-20 | 3 d | 1 d | 0 early |
| WP-5 producer, digest, read-back | branch from 11-20 | 3 d | 0.5 d | 0 early |
| WP-3 | late | 0.5 d | — | 1 |
| Late merges (WP-1, WP-2, WP-4, WP-5, WP-6) | late | 2 d | 1.5 d | 6 |

**Totals:** about 30 agent-days, plus about 6.3 h of serial gate time (≈ 25 min × 15 merges).

**Feasibility (R42-5).** WP-A and WP-0 start as soon as this plan is READY, not on 11-09. Both are read-safe: analysis tooling on pre-10-07 data, plus code reading. WP-0(c0) runs first. The 11-20 freeze stays the deadline. About 15 agent-days of early work then spread over about 5 weeks, which removes the zero-slack 11-09 start. WP-4's branch build and the WP-1/WP-2 branch builds keep their own timing (WP-4 early on a branch; WP-1/WP-2 from 11-20). Early starts never move a merge earlier, and C.8 still holds.

**Trade-off (R4-5).** About 6 agent-days are wasted on a floor FAIL. In exchange, the late phase is merges, gates and reviews only: about 3.5 d of serial work.

**Nominal activation:**
- read 12-07;
- ratify 12-08;
- shadow day 12-09/10;
- orders around 12-10/11.

**If routing is forced:** activation ≈ 12-16..12-18. That is before 01-20, but still an estimate, because it depends on when AUT-5a merges.

### C.8 Live-surface statement

Unchanged from r4.
- Early merges are limited to:
  - analysis scripts;
  - the inert `decision.py`;
  - the security-signed additive guard reshape (no nolong writer row);
  - documents.
- Everything else is branch-only until the late phase.

### C.9 Slip policy

Unchanged from r4, with two additions:
- **STOP-UNMEASURED shelves**, exactly like any viability STOP.
- **If WP-A overruns 11-19, the freeze moves**, but it must still precede the binding run and the read. The read waits for the committed floor result. No review is compressed to hold the date. If the freeze cannot precede the read, the plan shelves.

**Never compressed:**
- the full gate after each merge, with GATE_EXIT read before any push;
- all reviews, including WP-4's security re-review and the guard sign-offs;
- the B3 ruling;
- the shadow day and its committed read-back;
- the halt, node-stop and intent read-backs;
- the unit dry-run.

## D. Activation runbook (item 7)

Unchanged from r4.

- **D.1 Read** — once, after the §B result is committed.
- **D.2 Ratify** — ruling sha computed after the final text; one reviewed commit adds the allowlist row and replaces the pin with an exact two-row pin; then the full gate.
- **D.3 Shadow boot** — unit commit on a branch; dry-run; the intent precondition (OPEN, AMBIGUOUS or **unreadable** blocks the restart); the quiet windows (01:00–16:40Z outgoing, 13:15Z–11:10Z nolong); then a read-back, committed as `/home/jon/breezy/docs/evidence/m1v3/NOLONG_SHADOW_READBACK_<date>.md`.
- **D.4 Orders on** — hard precondition: the committed D.3 read-back. Drop-in removal is a reviewed act. Operator items: none. Then the first-day checks.
- **D.5 Rollback, in order:**
  1. Halt, with read-back.
  2. Stop the supervisor.
  3. Re-read the PID-verified lock holder (PID + start time) immediately before `kill -TERM`. SIGTERM only.
  4. Read back the stop.
  5. Check the intent is terminal. An unreadable intent counts as non-terminal and blocks the restart.
  6. Restore the drop-in, daemon-reload, and restart in the quiet window.
  7. Confirm orders are not requested.

## E. Risks

**R1–R13 and R15 are unchanged from r4.**

| # | Risk | Sev. | Mitigation |
|---|---|---|---|
| R1 | P(WINNER) ≈ 3.1% (dominant) | Dominant | Option value: branch builds; merges only after a PASS. |
| R2 | P(edge \| WINNER) ≈ 0.25–0.33 | High | Qty 1; K1–K7. |
| R3 | Selection bias and transport | High | §A.3, A.6, K4/K4b/K5. |
| R4 | Permit gap and AUT-5 file ownership | High | Branch-only early; gated, re-reviewed late merge. |
| R5 | Burst drops | High | d̂_mix mixture; viability STOP; τ_drop with a 0.40 cap. |
| R6 | First-row or arrival-order disparity | High | WP-0(d). |
| R7 | Cap truncation | Med | K4 counts candidates. |
| R8 | A peer rejects the 09-29 reconciliation | Med | §A.5. |
| R9 | Venue fee above the screen fee | Med | M5. |
| R10 | Routing is forced | Med | Decision by 11-12. |
| R11 | Window contamination | High | Date filters; allowlisted log reader (R41-5A). |
| R12 | Drift between 0 and −4¢ is unprotected | Med | Disclosed; K5. |
| R13 | be exclusion is not conservative for G1 | Med | 5% cap; clipped sensitivity. |
| **R14** | **Latch-input history (R41-3).** Fewer than 30 pre-10-07 orders forces the fallback. The fallback is **in effect a STOP**: mean hold ≈ 31 s against the 12:00Z burst gives d̂_p90 > 0.30 almost surely. That is labelled STOP-UNMEASURED if only the fallback trips it. Even when n ≥ 30, the FQ v1 and earlier orders had different asks and sides, so p_amb (≈ the IOC miss rate), h_post and the resolution times may not represent NO ≥ 0.90. h_post cannot be validated before live trading. | **High** | Disclosed in A.6; p_amb reported by ask band; Stage −1 records whether inputs were measured or fallback; never presented as a population finding. |
| R15 | ≈ 6 agent-days wasted on a floor FAIL | Low | Accepted for late slack. |
| **R16** | **Stage 0 emits no takes-needed figure, so viability condition 2 is informational only.** | Low | The thinned binding floor run is the authority (R41-4). |

## F. Expected value

Unchanged from r4.

- **Rates.**
  - P(W | null) ≈ 2.15%.
  - P(W | +1¢) ≈ 34%.
- **Posterior P(edge | WINNER).**
  - ≈ 33% at a 3% prior.
  - ≈ 25% at a 2% prior.
- **P(WINNER)** ≈ 3.1%.
- **Direct P&L:** a few cents.
- **Option value:** the only pre-2027 route to a sender that un-gates the live stages of AUTONOMY rows 7b and 8–12.
- **Cost:** about 30 agent-days. About 15 are early, of which about 13 are reusable regardless of outcome; about 6 are branch builds lost on a FAIL; the rest are late merges, gates and reviews.
- **Additional caveat (R14).** If the latch history is thin, the most likely path is STOP-UNMEASURED at Stage −1, before any late spend.

## §R3 and §R4 changelogs

Retained from r4 unchanged: §R3 rows WP-4 timing/S1–S5, P1–P3, A1–A5 and M0–M7; §R4 rows R4-1 through R4-17.

## §R4.2 changelog

| ID | Source | Section(s) changed |
|---|---|---|
| R42-1 | python | §B.3 `_run_design` document fields `MIXSET`/`e_proj` from the design; test assertion |
| R42-2 | python | §B.3 golden masks `git_head` and `script_blob_sha`; `design_blob_sha` if the design module is split out; provenance test |
| R42-3 | python | §B.3 `stat_blob_sha` stays the np_stat blob |
| R42-4 | market-math | §A.2.7 n_amb ≥ 10 for the empirical AMBIGUOUS shape; §B.3 test |
| R42-5 | architect | §C WP-0 early start at plan READY, with (c0) order count first; §C.7 feasibility; §C.9 slip wording |

## §R4.1 changelog

| ID | Section(s) changed |
|---|---|
| R41-1 (McDesign `mixes`) | §B.3 McDesign definition and `DEFAULT_DESIGN` / nolong design |
| R41-1 (`_prepare_from`) | §0 V20; §B.3 np_bound bullets; test `test_prepare_from_no_only_m_no_pool_does_not_raise` |
| R41-1 (`_run_design`) | §0 V21; §B.3; test `test_run_design_iterates_design_mixes_only` |
| R41-1 (`_benchmark` / MIXSET) | §B.3 (default path only; the driver never calls it; `test_never_calls_benchmark_or_world`) |
| R41-1 (evidence and pins) | §B.3 `Evidence` protocol, `FqEvidence` / `NolongEvidence`; `test_run_design_uses_injected_evidence_and_pins`; `test_floor_config_from_prereg_no_fq_pins` |
| R41-1 (`nolong_d12_floor_config.py`) | §B.3 new module (≤ 200 lines), its scope and tests |
| R41-1 (`_run` golden) | §B.3 `test_default_run_unchanged_golden` |
| R41-1 (size check) | §B.3 split rules for `nolong_d12_latch_inputs.py` and `fq_loss_floor_np_design.py` |
| R41-1 (effort) | §B.3 (6.5 d + 1.5 d); §C.7 table and totals |
| R41-1 (found while verifying) | §0 V22; §B.1 `np_delta` and `e_proj`; §B.3 test `test_np_delta_and_e_proj_injected_not_module_constants` and the np_stat blob test |
| R41-2 | §A.2.7 (p90 vs p50 rationale; day mean over 1,000 draws, percentiles across days; τ_drop capped at 0.40); §B.3 tests; §C.WP-5 K3 |
| R41-3 | §A.2.7 (n ≥ 30 minimum; empirical hold quantised to GET offsets and capped at 60 s; fallback plus point estimate; STOP-UNMEASURED; fallback is in effect a STOP; IOC miss = AMBIGUOUS); §A.5; §A.6 representativeness row; §B.1 Stage −1; §B.3 tests; §E R14; §F; §C.9 |
| R41-4 | §B.1 drop-thinning row and seed; viability condition 2 (informational; measured λ₄; 156 literal dropped); §B.2; §B.3 tests; §E R16 |
| R41-5A | Hard rules; §B.3 `test_log_reads_pre_1007_field_allowlist_and_date_filter`; §E R11 |
| R41-5B | §C.WP-5 read-back helper and `test_readback_unreadable_intent_treated_non_terminal`; §D.3 / §D.5 intent precondition |

**Items not satisfied, or deviating from the ruling:**
1. **No file written.** There is no Write tool; the coordinator saves this text.
2. **R41-4: condition 2 is informational.** Neither `fq_loss_floor_np_bound.py` nor `fq_loss_floor_np_stat.py` emits a takes-needed figure. Per the ruling's own fallback, condition 2 never STOPs and the 156 literal is dropped.
3. **R41-3: STOP-UNMEASURED depends on some history existing.** If the history before 10-07 has zero usable orders, there is no Wilson point estimate to compare against, and any viability STOP is recorded as STOP-UNMEASURED by definition. It still shelves.
4. **V22 was found while verifying R41-1.** The NP shift and the decision date (`DELTA_H1`, `E_PROJ`) are module constants in `fq_loss_floor_np_stat.py`. They are injected through `McDesign` without editing that file. Without this, Stage 0 would have tested δ = −0.16 against FQ's 11-01 decision date.
