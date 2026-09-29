# Probabilistic-Forecast Family (NBM NBP): plan from reopening ruling to arming and learning

- **Date:** 2026-09-29
- **Status:** CONVERGED Rev 3 (2026-09-29). Round 3: trading-bot-architect 92 APPROVE, mle-reviewer 91 APPROVE. Round 2: prediction-market-reviewer 89 APPROVE, python-reviewer 89 APPROVE. No CRITICAL/HIGH open. Next: S0 reopening ruling.
- **Owner:** coordinator (Breezy main session). Plan author: planner (blind)
- **Proposed path:** `docs/plans/FORECAST_NBP_PROBABILISTIC_FAMILY_Rev3_2026-09-29.md` (supersedes Rev 2)
- **Evidence labels:** [VER] means read in the repo this session, with file:line. [BRIEF] means a coordinator-verified fact. [MEM] means project memory. [INF] means an inference, to be tested in peer review.

---

## Rev 3 change log

| Finding | Severity (source) | Resolution | § changed |
|---|---|---|---|
| R3-01 | HIGH (architect) | S3a's decisive go/no-go is scored on **permit-covered hours** only. These are the nominal window [LAUNCH_UTC, LAUNCH_UTC + PERMIT_TTL_NS), pre-declared at S0 and read from code at run time. An all-hours comparison is descriptive only | §1.1, §1.2, §3.3, §4.2, §5, §7 SL-9, §9 Q15 |
| R3-02 | MEDIUM (architect + python) | Conditional SL-13b: second kind, marker row, manifest and trade.py branch. One hypothesis id spans both manifests; the veto is computed over the union; one S5 ruling covers both. The cardinality-1 registry is raised as Q17 | §2.3, §4, §7 SL-13b, §9 Q17 |
| R3-03 | LOW (architect) | Critical path redrawn: L branches at S1 exit (after SL-4 and SL-5) | §4 |
| R3-04 | HIGH (mle) | v5.0 fit slice (05-04..06-30) plus v5.0 holdout (07-01..). a_v and γ_v are fitted hierarchically, with shrinkage chosen by LOVO CRPS. Two sensitivities are reported. n_min comes from the G2.2 power target, and S2 waits for it | §0, §2.2, §3.1, §3.2 items 5–6, §4, §4.1, §5, §7 SL-8, §9 Q3 |
| R3-05 | HIGH (mle) | C-1's holdout minimum = n_min. G2.0 tests only months with ≥ N final station-days; untested months are flagged and go to L. C-1 moves S3b past the KILL, so it routes to §6 node 4 | §4.1, §4.3, §6 node 4, §9 |
| R3-06 | MEDIUM (mle) | Under C-1, G2.0–G2.3 re-evaluate **as a set** on the fresh holdout | §4.1, §7 SL-8 |
| R3-07 | MEDIUM (mle) | G2.0 correction forms are a closed set {none, per-calendar-month offset, linear in LST day-length}, chosen on validation only | §4.1, §7 SL-8 |
| R3-08 | LOW-MEDIUM (mle) | SL-4's dedupe ordering branches on whether a BBB correction indicator is verified in real NBP headers; a RED test for each branch | §7 SL-2, SL-4 |
| R3-09 | LOW ×3 (PM) | "about 7%" becomes 6.6%. The fee is quadratic θ·qty·p·(1−p). The S0 obligation reconciles the θ 0.0695 ceiling with the documented maker rebate. Verified citations: the formula is `fees.py:455` (return line of `expected_fee_for` :418-455) and `taker_fee_at_fill` :560-594 (formula :593). `MAKER_FEE_COEFFICIENT` is defined at `fees.py:82` and documented as not wire-observed at `errors.py:325-341` | §1.1, §2.5, §4.2, §7 SL-9 |
| R3-10 | LOW (python) | Citation widened to `forecast_point.py:380-391` | §3.2 item 1 |

## Rev 2 change log

| Finding | Severity (source) | Resolution | § changed |
|---|---|---|---|
| R2-01 | CRITICAL (architect) | S4 split into S4-infra (parallel, unscored, no α, no firewall days) and S4-gate (REGISTERED check, S5 entry only); critical path redrawn | §1.3, §4, §4.4, §7 |
| R2-02 | HIGH (architect) | Confirmatory estimand stated as CLOSED, not S0-changeable | §1.1, §2.1 |
| R2-03 | MEDIUM (PM + architect) | D0 variants V3/V4 dropped; k=2; per_variant α=0.003125; permit-window rule; Q12 resolved | §1.1, §1.2, §2.3, §2.4, §3.3, §5, §9 |
| R2-04 | MEDIUM (PM) | Pooling V1+V2 evaluated against the STATION_DAY_STATISTIC rule | §2.5 |
| R2-05 | HIGH (PM) | G2.1 → Holm-corrected per-bucket z-test; the ε miss count becomes reporting only | §4.1 |
| R2-06 | HIGH + MEDIUM (PM) | Pessimistic maker fee = θ 0.0695; adverse-selection haircut; maker UNDERPOWERED-by-construction without A0 | §4.2, §5, §9 Q8 |
| R2-07 | CRITICAL (mle) | Rolling-refit branch becomes pre-registered contingency C-1 that consumes the look | §4.1, §9 Q3 |
| R2-08 | HIGH (mle) | Version-aware EMOS-style spread recalibration is the default (completed by R3-04) | §2.2, §4.1 |
| R2-09 | HIGH (mle) | Q7 promoted to hard sub-gate G2.0; SL-2 records the TXN window from a primary source | §3.2 item 8, §4.1, §7 SL-2 |
| R2-10 | MEDIUM (mle) | §3.2 item 10: final, latest-revision CLI rows only | §3.2, §7 SL-5 |
| R2-11 | MEDIUM (mle) | Isotonic declared as a fallback alongside affine | §2.2, §4.1 |
| R2-12 | Q14 (PM + reviewers) | G2.3 = matched-event D_res CI lower > 0 AND point ≥ 0.0152; ratio rejected | §4.1, §9 Q14 |
| R2-13 | LOW (mle) | SL-4 deterministic NBP retransmission dedupe | §7 SL-4 |
| R2-14 | LOW (mle) | L adds an ingest/label freshness heartbeat with a positive control | §4.3, §7 SL-15 |
| R2-15 | HIGH (python) | SL-1 split into SL-1a (RED) / SL-1b (GREEN, gated on the SL-3 census) | §7 |
| R2-16 | HIGH (python) | Lead axis unnecessary; SL-10 DROPPED; widening scope named if revived | §2.4, §7 SL-10 |
| R2-17 | MEDIUM (python) | Per-slice mypy-ratchet edit column | §7 |
| R2-18 | MEDIUM (python) | Exact forbidden symbols for the SL-12 contract test | §1.2, §7 SL-12 |
| R2-19 | LOW (python) | Citations fixed: trade.py :536-637 / :638-648; supervisor dict :161 | §7 SL-13, §7 composition note |
| R2-20 | note (python) | `forecast_ladder` is already in CompositionKind but refused at boot; new kind kept | §7 composition note |

---

## 0. Summary

We build a probabilistic daily-max model from the NOAA NBM **NBP** percentile bulletin. We calibrate it against **NWS CLI** truth using only weather history, and score it against the closed model and an NBS+XND normal baseline. Only then do we compare it with Polymarket.us prices.

The stages that decide forecast skill (S1–S2) touch no venue data. They spend no α and no firewalled tape. The market comparison is split in two:
- a SEARCH run on pre-freeze tape (S3a), whose go/no-go is scored on permit-covered hours only;
- one registered confirmatory look (S3b).

The live build (S4-infra) runs **in parallel** with S2/S3a. It is unscored, so it spends no α and no firewall days. Only a short REGISTERED re-check (S4-gate) sits before S5. Arming follows the RULING_A1 §7 path. Every gate has a named next action.

**Honest headline [INF, arithmetic in §5]:** with k=2 (D+1 only), the pinned per-take EV test can confirm only an edge of about **0.096–0.10 per take** at the ≈320–350 listed station-days reachable before the 2027-01-25 KILL backstop. It is ≈0.089–0.093 if S0 elects to pool (§2.5).
- The range reflects the v5.0 holdout wait (§4.1). S2 cannot open before the holdout reaches n_min, about 2026-10-17.
- Taker edges of 0.03–0.04 will almost surely come back `UNDERPOWERED_NOT_REGISTERED`.

The plan still pays off:
- S1–S2 settle the forecast-skill question cheaply and for good.
- The weather assets (ingest, calibration, learning loop) carry over to Kalshi K-2 if the PM.us programme is killed.

---

## 1. Governance position

### 1.1 What is closed, and why this is a distinct hypothesis (S0 ruling content)

- **Closed:** the NBS deterministic TXN plus a fitted bias and a **frozen** sigma, scored at 09:00 LST on 64 ask clusters. Market resolution was 1.98× the forecast's (D = −0.01518, CI [−0.03229, −0.00373]) [VER `RULING_forecast_edge_programme_closes_2026-09-20.md:45-50`]. The ruling limits its own scope: "this model, this venue, this contract" [VER :109-111].
- **Recorded as data:** the class is REJECTED with k=12 [VER `derived/hypothesis/hypothesis_ledger.jsonl:2`]. AUD-18 excludes re-running the forecast-taker hunt "under any circumstance" [VER AUD-18:126-128]. So S0 does **not** amend AUD-18 and does **not** reuse the `H-FORECAST-TAKER-*` id.
- **The route back:** a CONFIRMED hypothesis, then a NEW A1-class ruling, then a NEW registration, then operator-only enablement [VER `POST_FORECAST_PHASE_2026-09-20.md:450-455`].
- **The closed registration anticipated a new model:** its own text says a sigma re-fit "is a new registration, not a knob" [VER `PREREG_WP7_MULTIPLICITY_RULE_2026-09-20.md:142`].

| Dimension | Closed class (WP7, 12 variants) [VER PREREG_WP7:69-73,135-143] | This family |
|---|---|---|
| Information set | TXN point + fitted, frozen sigma | Day-varying ensemble spread (TXNSD) + 5 percentiles (shape/skew) |
| Uncertainty | Climatological, same every day | Flow-dependent, varies by day (a possible new source of *resolution*) |
| Lead / cycle | "no lead or cycle-age partition", D0 only | **D+1 only** (12/13Z onward), inside a live permit window (§3.3) |
| Hours | Windows 09–12, 12–17, 10–11 LST | Permit-covered venue hours (§3.3; HUNT-1 in Q15) |
| Execution | Taker at ask only | Taker **and** maker/resting-bid |
| Cluster | Date primary (:143) | Station-day primary (L-40); date-clustered reported as sensitivity |

**CLOSED question (R2-02), not an S0 dial:** the confirmatory estimand is per-take `MEAN_EXCESS_PER_TAKE`, station-day clustered, as fixed by A1 §7.1 and pinned in the ledger as "the ONE admitted station-day observation" [VER `hypothesis_ledger.py:195-197`]. S0 cannot change it. Changing it would need a full new A1-class cycle (ruling, then ledger change, then re-review). This plan does not propose one.

**S0 ruling obligations:**
1. Argue distinctness on each row of the table above.
2. Pre-declare that a model which does not improve *resolution* over the closed model on matched events is **not** a distinct hypothesis. This is gate G2.3 in §4.1.
3. Fix per-variant plausibility bounds **before** any tape is scored. For the maker variant, use the pessimistic-fee and haircut rules of §4.2.
4. Fix, before any tape or holdout is read:
   - the NBS+XND fallback rule of §2.2;
   - contingency C-1 (§4.1);
   - the maker haircut window W (§4.2);
   - the pooling decision (§2.5);
   - the **permit-covered-hours window definition** (§3.3, R3-01);
   - the G2.2 power target, σ_d and the resulting **n_min** (§4.1, R3-04);
   - the G2.0 month threshold **N** and the closed G2.0 correction set (§4.1, R3-05/R3-07).
5. Answer the firewall questions Q5 and Q9 (§9), including the S4-infra shadow-log rule (§4.4).
6. **Fee reconciliation (R3-09).** Record why the maker fee ceiling is θ = 0.0695, the post-drift taker coefficient [VER `fees.py:111`].
   - The venue documents a maker **rebate**, `MAKER_FEE_COEFFICIENT = Decimal("-0.0125")` [VER `fees.py:82`]. It is flagged DOCUMENTED-NOT-WIRE-OBSERVED, with no captured payload or fill confirming it [VER `errors.py:325-341`].
   - The ceiling is deliberately conservative until A0 confirms the maker fee on the wire. It is never relaxed toward the documented rebate before then.

### 1.2 RULING_A1 §7 re-arm criteria, mapped [VER `RULING_A1_pm_us_crh_v4_disposition_2026-09-21.md:402-440`]

| §7 item | Requirement | Where this plan meets it |
|---|---|---|
| 1 (:404-406) | Edge estimate on real venue ladders, station-day-clustered 95% CI excludes 0 | S3b confirmatory look on post-freeze forward tape (real ladders) |
| 2 (:407-408) | No dependence on the `P_HOLD_*` collider cells | By construction. The SL-12 contract test forbids the exact symbols listed in §7 SL-12 |
| 3 (:409-414) | A0 fee-drift evidence pack | External dependency (RA-1 A0 clock). It also measures the maker fee; until then the pessimistic ceiling applies (§1.1 item 6, §4.2) |
| 4 (:415-417) | Fresh manifest per POST_FORECAST §A-9 item 2, n reset to 0 | SL-13 manifest (and SL-13b if V2 survives), `DRAFT_NOT_REGISTERED` until S4-gate |
| 5 (:423-437) | HUNT-1: all hours | The trigger is every quote update. Decisions outside a live permit are NOT_EXECUTABLE (§3.3). S3a's decisive statistic uses permit-covered hours only; all-hours is descriptive (§4.2). The conflict is open as Q15 |
| 6 (:438-440) | New A1-class ruling | S5 |

### 1.3 Interaction with the programme clocks

- **RA-13 KILL backstop 2027-01-25** [VER `RULING_RA-13_programme_kill_2026-09-27.md:45-48`]. Trigger R4 is "a new estimand that clears its power check at intake" [VER :53]. This family is an **R4 candidate**:
  - REGISTERED at S3b → the KILL is pre-empted.
  - `UNDERPOWERED_NOT_REGISTERED` → R4 is not met, and the KILL clock keeps running.
  - The date is firm; capture holes do not extend it [VER :46].
- **R3V-b on 2026-10-01** [VER PROGRESS.md:58]: if R3 is ruled not viable, "programme KILL decision forward + K-2". S0–S2, and S4-infra under §4.4, touch no scored tape and run in parallel, so R3V-b does not gate them.
  - If the KILL fires before S3b registers, the PM.us leg (S3b, S4-gate, S5) ends.
  - S1, S2 and L are handed to K-2 as exchange-portable assets (CLAUDE.md priority 5).
  - The coordinator should cite this plan as a pending R4 candidate in any KILL ruling.
- **Firewall.** RA-13 binds that "any statistic on post-2026-09-25 tape forfeits H-ARCHIVE-RECAL CONFIRM days" [VER RA-13:5]. The corpus rule is freeze-date separation [VER PREREG_WP7:48-63; RULING_H-ARCHIVE-RECAL:57]. Therefore:
  - S3a SEARCH uses tape **≤ 2026-09-25** only, enforced by a code guard (SL-9).
  - No dev or replay run on post-freeze tape is *scored* before registration [VER RA-13:35]. S4-infra's post-freeze shadow logs follow the no-scoring rule in §4.4.
  - Whether a *registered* single look forfeits sibling days is open question Q5.

---

## 2. Hypotheses (pre-registered at S0; frozen at S3b)

### 2.1 Legs

- **H-FC-NBP-SKILL (S2, weather only, no α from the programme ledger):** the calibrated NBP rung probabilities beat (a) the closed model M0 on matched events and (b) the NBS TXN+XND normal M1. Metrics are rung-event Brier and Murphy resolution against CLI on the v5.0 holdout (§3.2 item 6). This is a **necessary-condition screen** on data disjoint from any venue corpus. It prunes variants, but it never claims edge.
- **H-FC-NBP-MKT-SEARCH (S3a, SEARCH corpus, no α):** on pre-freeze tape, restricted to permit-covered hours, model rung probabilities are not strictly worse than the market on resolution (WP7b shape).
- **H-FC-NBP-EV (S3b, confirmatory, programme ledger):** `MEAN_EXCESS_PER_TAKE > 0` after θ = 0.0695 at executable prices, per variant, SINGLE_LOOK [VER `hypothesis_ledger.py:197,202,269-271`]. The estimand is CLOSED (§1.1). One hypothesis id covers both variants and, if SL-13b is built, both manifests (§7 SL-13b).

### 2.2 Models (comparators, not α variants)

| Id | Model | Role |
|---|---|---|
| M0 | NBS TXN + frozen 0b bias/sigma (the closed model) | (i) Reproduces the 09-20 numbers on their own event set, as a positive control. (ii) Scored on the **same** D+1 events as M2 for G2.3 |
| M1 | NBS TXN mean + XND sd, normal, 0.5 °F continuity (IEM MOS on disk) | Zero-plumbing baseline |
| M2 | NBP percentiles → CDF (method from §9 Q1) → **hierarchical version-aware EMOS-style spread recalibration** (default) → optional affine/isotonic probability recalibration | Candidate |

**M2 recalibration (R2-08, R2-11, R3-04). No choice reads the v5.0 holdout.**
- **EMOS form:** a location-scale transform of the percentile CDF.
  - Location: μ = TXN50 + a_v.
  - Scale: log s = γ_v + δ·log TXNSD. The coefficient δ is shared across versions and fitted by minimum CRPS on train.
- **Hierarchical version parameters (R3-04).** Train and validation contain no v5.0 rows, so an unpooled v5.0 fit would extrapolate.
  - (a_v, γ_v) are fitted with **partial pooling across versions**: each version is shrunk toward the pooled mean with strength τ.
  - Each version's parameters are fitted on its own pre-holdout rows: train for the 2020–2024 versions, validation for v4.2 (rows before 2025-05-27) and v4.3, and the **v5.0 fit slice** (2026-05-04..06-30) for v5.0.
- **Choosing τ (outcome-free for the holdout):** leave-one-version-out (LOVO) CRPS over the versions present in validation plus the v5.0 fit slice.
  - For each such version v, estimate the pooled mean **without** v.
  - Fit v on the first half of its rows (time-ordered), shrunk toward that mean with strength τ.
  - Score CRPS on the second half.
  - τ minimises the mean CRPS across versions. The grid is pinned at S0.
- **Sensitivities (reported, never gating):**
  - (i) **v4.3-transfer:** v5.0 uses v4.3's (a, γ) with no v5.0 fit.
  - (ii) **v5.0-anchored:** τ = 0, meaning the v5.0 fit-slice estimates are used unshrunk.
  - Both are scored on the holdout beside the primary. If a sensitivity disagrees in sign with the primary on G2.2 or G2.3, the evidence note flags it and mle-reviewer co-signs. The gate outcome does not change.
- **Declared fallbacks,** applied after EMOS to rung probabilities and chosen on validation by rung Brier: (a) affine; (b) isotonic (monotone, fitted on train, with the rung partition re-normalised and re-asserted complete). "None" is also a candidate. No other form may be introduced after S0.

**Pre-declared M1 fallback:** if M2 does not beat M1 at G2.2 but M1 passes G2.0–G2.3, M1 becomes the family model. S0 must state whether M1 alone is distinct under §1.1; the day-varying XND spread is the only difference from M0. If S0 rules M1 not distinct, the fallback is void.

### 2.3 Trading variants (k = 2; cap at `hypothesis_ledger.py:181`)

| V | Lead | Execution | Cycle feed (latest available ≤ decision) | composition_kind / manifest |
|---|---|---|---|---|
| V1 | D+1 | Taker at ask, qty 1 | 12/13Z, 19Z, 00/01Z targeting D+1 | `forecast_quantile_ladder` / `pm_us_crh_fq_v1.json` (SL-13) |
| V2 | D+1 | Maker: resting bid, qty 1 | same | `forecast_quantile_ladder_rest` / `pm_us_crh_fq_rest_v1.json` (SL-13b, **only if V2 survives S3a**) |

**D0 variants dropped (R2-03).** Three reasons:
- METAR integer-°C truncation never decides a band [MEM].
- The hunt window opens after repricing [MEM].
- The node's order permit does not cover the 07Z cycle, which lands around 08:30Z. The permit is issued at the 16:50Z launch (`LAUNCH_UTC` [VER `trade_supervisor_core.py:35`]) with a 10 h TTL (`PERMIT_TTL_NS` [VER `safety.py:172`]), so it expires about 02:50Z.

S2 and S3a may **drop** a variant before S3b; they never add one (the WP7 rule (i) analogue [VER PREREG_WP7:30-33]). The side is YES plus the native NO instrument (`allow_short=False`); see Q4.

### 2.4 α budget [VER `hypothesis_ledger.py:156,175,179,184,1118-1119`]

- Re-arm gating requires programme α ≤ 0.025. `allocated = 0.025/4 = 0.00625` per hypothesis, and `per_variant = 0.00625/2 = 0.003125`. This equals the pinned floor `MIN_PER_VARIANT_ALPHA` [VER :184], so k=2 is the ceiling for this slot at that floor.
- All four programme slots are free today: the four existing rows are all zero-look [VER ledger.jsonl:1-4; `programme_budget_remaining` :813-822]. This hypothesis takes one slot.
- **Mechanical blockers today:** a schema-v3 (re-arm-gating) REGISTERED write is refused while `HORIZON_TOLLING_LANDED` (:164) and `PATH_B_SOURCE_GATE_LANDED` (:172) are False. The UNDERPOWERED path is unaffected [VER :942-943]. Both flags are **external dependencies of S3b**.
- **Strata:** `_STRATUM_AXES = (station, hour_lst, side, composition_kind)` [VER :367].
  - With D+1 only, no lead axis is needed.
  - V1 and V2 are separated by `composition_kind` (§2.3). SL-10 is therefore DROPPED (§7).
- `RULED_HORIZON_DAYS ∈ {120,180}` [VER :151].

### 2.5 Pooling V1+V2 (R2-04; S0 candidate, default NOT pooled)

- **Legal.** The ledger admits exactly one station-day observation, `MEAN_EXCESS_PER_TAKE`, and says "The station-day SUM is NOT admitted" [VER `hypothesis_ledger.py:195-197`]. A pooled variant's station-day X_d is the *mean* excess over all of that day's takes, taker and maker alike, so it stays inside the rule. A sum, or a per-execution-mode sub-mean that is then added, would breach it. The zero-take rule (:203-205) and the leg-share cap `MAX_SINGLE_DAY_LEG_SHARE = 0.20` (:210) apply unchanged.
- **What it buys.** k=1 gives per_variant α = 0.00625, so the MDE drops **6.6%** (0.0956 → 0.0893 at n=350; §5). It may add a few take-days where only one mode trades.
- **What it costs:**
  - The estimand becomes a mixture, which dilutes a mode-specific edge.
  - The maker leg's pessimistic fee and haircut (§4.2) and its possible UNDERPOWERED-by-construction status would bind the taker's fate.
  - The pooled series needs one `composition_kind` and so one composed strategy running both modes (that is, SL-10 revived).
  - A same-rung latch collision needs a pre-declared rule: the first of taker or maker wins.
- **Default:** keep V1 and V2 separate. S0 may elect pooling only if A0 lands the maker fee before S3b. "Taker-leg pooling" is moot: only V1 is a taker leg, and it already spans both sides.

---

## 3. Data and leakage controls

### 3.1 Sources (binding principle: prediction data only from US weather sources; venue prices only for execution cost)

- **Predictors:** NBP `blend_nbptx.tHHz`, primary on AWS `noaa-nbm-grib2-pds`, NOMADS as fallback [BRIEF]. Also IEM MOS NBS 2021–2026 on disk (M0, M1) [BRIEF].
- **Labels:** the NWS CLI settlement-truth parquet [BRIEF].
  - **Coverage [VER `settlement_truth_dataset.py:259-279`]:** the 2021–2025 station-years plus **2026-08-16/17..2026-08-23 only**. The docstring (:276-278) records a hole from 2026-01-01 to 2026-08-15.
  - So the v5.0 fit slice (05-04..06-30) has **no labels** today, and the v5.0 holdout (from 07-01) has about one week. The v4.3 tail (Jan–May 2026) is also missing. Extending the labels (SL-5) is a hard prerequisite of S2.
- **Venue:** the Depth10 forward tape since 2026-08-30, used **only** for cost (ask + fee; bid, fill model and haircut for the maker variant).

### 3.2 Leakage controls (each one enforced by a test)

1. **Availability, not cycle.** Every model probability carries `available_at_ns`. For archive records, `available_at = max(S3 LastModified, cycle + floor)`. For live records it is the measured ingest time. `ForecastPoint` already separates `ts_event = cycle_runtime_ns` from `ts_init = available_at_ns` [VER `forecast_point.py:380-391`].
   - The new comparison guard raises unless `available_at_ns < price_ts_ns`. The WP7b guard checks cycle issuance vs decision [VER `wp7b_market_as_forecaster.py:288-304`], so it is **replaced**, not reused.
   - Assert `ref.ts < take.ts` on every row [MEM implausible-result-is-a-leak].
2. **Publication-lag floor.** Add `"NBM_NBP"` to `FORECAST_MODELS` [VER `forecast_point.py:146`] and to `MINIMUM_PUBLICATION_LAG_NS` [VER :159-162]. The two sets are required to match [VER :156-158]. The floor value comes from the SL-3 lag census (the minimum observed LastModified − cycle, rounded down to 5 min). It is never guessed (SL-1b).
3. **Climate day in LST.** CLI day = local standard time midnight to midnight, no DST. Lead hours are computed in LST. The WP7b UTC-boundary index at `wp7b…py:262-281` is **not** inherited.
4. **Windows scoped by date AND hour** for all tape work. For S3a, a hard refusal of any tape day > 2026-09-25.
5. **Version strata.** A constant `NBM_VERSION_BREAKS` holds 2020-09-29, 2023-01-17, 2024-05-15, 2025-05-27 and 2026-05-04 [BRIEF]. Every row is tagged. Version parameters are fitted hierarchically (§2.2). The holdout is v5.0 only, and it excludes the v5.0 fit slice.
6. **Time-ordered splits (R3-04).**

   | Split | Dates |
   |---|---|
   | Train | 2021-01-01..2024-12-31 |
   | Validate | 2025-01-01..2026-05-03 |
   | v5.0 fit slice | 2026-05-04..2026-06-30 |
   | v5.0 holdout | 2026-07-01..last final CLI, growing forward as labels accrue |

   - Any split whose max ≥ the next split's min raises.
   - The holdout is **not opened before the S2 run**. S2 refuses to open it until its final station-day count reaches **n_min** (§4.1).
   - It is then opened **once**: a marker file makes a second run refuse, mirroring SINGLE_LOOK. The only sanctioned exception is contingency C-1 (§4.1).
7. **Integer rounding.** Both the CLI value and the NBP percentiles are integer °F. The integer label is treated as latent in [x−0.5, x+0.5). Rung probability = F(hi + 0.5) − F(lo − 0.5) over a **complete partition**, asserted with `assert_complete_partition` [VER `wp7b…py:184` per BRIEF].
8. **Definitional mismatch → hard gate G2.0 (R2-09).** NBM TXN may be a daytime-window maximum, while CLI is the LST calendar-day maximum. SL-2 records the TXN window definition from NOAA NBM documentation or from the bulletin header/columns, citing the primary source. If it cannot be verified from a primary source, S2 treats it as **unknown** and relies on G2.0 (§4.1).
9. **Artefact isolation.** Live code sees calibration only through the sha-pinned manifest artefact [VER `persistence/family_manifest.py:179-185`; `pyproject.toml:131-147,149-157`].
10. **Final CLI only (R2-10).** Every split-bearing computation (fits, the S2 gates, n_min counting, S3a, and L's reliability/BSS) uses only CLI rows with `is_final=True`, after supersession to the latest revision.
    - The fields `is_final`, `correction_flag`, `is_correction_bbb` and `revision_seq` are in the archived schema [VER `archived_climate_day.py:343-346`].
    - Selection reuses `latest_by_archived_climate_day`, which orders by `(is_final, ts_init, revision_seq)` [VER `archived_selection.py:9-12,30-32`].
    - Provisional labels written by L's nightly extension are excluded from every gate. A test asserts that a preliminary row, or a superseded final, never reaches a gate input.

### 3.3 Trial trigger (L-34, pinned at S3b) and permit-covered hours

- Evaluation runs on **every** quote or depth update in all venue hours.
- The trial is the **first executable snapshot** per (station-day, rung, side, variant) that satisfies `ev_net > margin` under the latest available cycle. One latch; qty 1 [VER `hypothesis_ledger.py:200`].
- **Permit window (R2-03):** every D+1 decision must fall inside a live order-permit window.
  - A decision outside one is recorded as `NOT_EXECUTABLE`, never latched and never counted as a trial.
  - Live, the permit is read from the node's own boot-time permit line [MEM]. In replay, the permit windows are reconstructed from the node log files, never assumed.
  - This plan does not propose changing the permit TTL or the launch timing (Q16).
- **Permit-covered hours for S3a (R3-01), pre-declared at S0.** These are the **nominal schedule window [LAUNCH_UTC, LAUNCH_UTC + PERMIT_TTL_NS)** on each UTC day. Today that is 16:50Z–02:50Z:
  - `LAUNCH_UTC = dt.time(16, 50)` [VER `trade_supervisor_core.py:35`];
  - `PERMIT_TTL_NS` = 10 h [VER `safety.py:172`], applied at `issue_live_trading_permit` [VER `safety.py:673-758`, expiry :730-732].
  - Mid-day relaunches are clamped to the first boot's expiry, never "one fresh 10 h window per relaunch" [VER :689-692], so the nominal window is the daily ceiling.
  - SL-9 **reads both constants from code at run time**; neither is hard-coded.
  - The window is nominal rather than reconstructed from node logs. It is outcome-free, it is defined on pre-freeze days when the node may not have run, and it matches what a registered look can execute.
- A new cycle never re-opens a latched rung.
- Sizing never reads `kelly_stake_fraction`, and no operator-reserved value is read or assigned.

---

## 4. Stages

| Stage | Entry | Work / artefacts | Exit (pass) | Terminal negative → next action | Owner (agent types) |
|---|---|---|---|---|---|
| **S0** Reopening ruling + registration plan | This plan peer-reviewed to convergence | `docs/evidence/RULING_forecast_nbp_reopen_<date>.md`: every obligation in §1.1, including the permit window, n_min, N, the G2.0 set and the fee reconciliation; horizon (120/180) | Two blind peers APPROVE (AUD-18:1148-1154 pattern) | "Not distinct" → no build; record why; programme stays on RA-13 (R3 / KILL → K-2) | Author: trading-bot-architect. Adversarial: prediction-market-reviewer; mle-reviewer for stats |
| **S1** NBP backfill + CLI labels | S0 signed | SL-1a, SL-2, SL-3 → SL-1b → SL-4, SL-5; `derived/nbp/nbp_quantiles.parquet`; extended final-CLI labels; lag-census note; TXN-window + BBB note | ≥95% station-cycle-day coverage per version stratum; the label gap 2026-01-01..08-15 closed or itemised (never interpolated [VER :276-278]) | v5.0 archive gap > 5% → re-source via NOMADS; else S2 runs with the gap declared | Grok → Codex → tdd-guide; python-reviewer; security-reviewer (new egress) |
| **S2** Weather-only calibration and skill | S1 exit **and** final holdout n ≥ n_min (§4.1). Waiting is weather-only and costs no α | SL-6..SL-8; `docs/evidence/NBP_SKILL_<date>.md`; artefact (json + sha256) | G2.0–G2.3 (§4.1) | §6 node 2; C-1 only if pre-registered conditions hold (routes to §6 node 4) | Implementer; mle-reviewer + prediction-market-reviewer |
| **S3a** SEARCH vs market, pre-freeze tape | S2 pass | SL-9; WP7b-shaped report on 2026-08-30..09-25; decisive statistic on permit-covered hours; all-hours descriptive annex | Per variant: not futile (§4.2) | All futile → close with evidence; §6 node 3 | Implementer; prediction-market-reviewer |
| **S3b** Registration (single look) | S3a leaves ≥1 variant; ledger flags landed (§2.4) or UNDERPOWERED path | `hypothesis_register.py` intake with k = surviving variants, `re_arm_gating=True`, override 0.025, freeze commit | REGISTERED (power check clears) → R4 fires; look accrual starts | `UNDERPOWERED_NOT_REGISTERED` → §6 node 4 | Coordinator runs the register; peers co-sign |
| **S4-infra** Live ingest + shadow build (**parallel**) | SL-1b, SL-2, SL-3, SL-6 merged | SL-11..13 (plus SL-13b after S3a if V2 survives); phase-0 permit guard refuses all orders; provisional artefact fitted on the **train split only**, marked NON-REGISTRABLE; parity under §4.4 | Per manifest: ≥14 consecutive days of shadow/replay decision parity (same decision-key set, ±0), actor liveness, deny chain byte-unchanged. **Target: SL-13 done by S3b**, so accrual starts on registration day | Parity failure → fix under TDD; never waived | tdd-guide; python-reviewer; trading-bot-architect |
| **S4-gate** REGISTERED check | REGISTERED **and** S4-infra exit; needed only at S5 entry | **Every surviving manifest** re-pinned to the registered artefact sha, status REGISTERED, citing the **same hypothesis id**; nightly replay produces the look's draws (needs PATH-B-SOURCE-GATE) | For each manifest: ≥7 consecutive days of parity under the registered sha; replay code sha = live code sha | Parity failure → fix; that manifest's draws since the failure are quarantined until parity is re-established | tdd-guide; python-reviewer |
| **S5** Arming | Single look CONFIRMED + pooled-P&L veto passes [VER :207], computed over the **union** of all surviving variants' station-day P&L + S4-gate | Evidence pack: look record, A0 pack, manifest(s) A-9, HUNT-1 hour/permit table, P_HOLD independence proof, parity report → **ONE** NEW A1-class ruling covering every surviving manifest | Ruling signed → **operator-only** enablement and A1-halt clear | REJECTED look → §6 node 5 | Author: trading-bot-architect. Reviewers: prediction-market-reviewer, security-reviewer |
| **L** Learning loop | S1 exit (runs whatever the other outcomes) | SL-15 nightly timer (§4.3) | Runs nightly; drift alarm **and** freshness heartbeat each fire on an injected positive control (L-38) | — | Implementer; python-reviewer |

**Critical path (R2-01, R3-03):**

    S0 ─► SL-1a,SL-2,SL-3 ─► SL-1b ─┬─► SL-4,SL-5 ═ S1 exit ─┬─► [wait: final holdout n ≥ n_min] ─► S2 ─► S3a ─► S3b ─► [look accrues] ─► S4-gate ─► S5
                                    │                        └─► L (from S1 exit)                         │                                 ▲
                                    │                                                                    └─► SL-13b (only if V2 survives) ─┤
                                    └─► SL-6 ─► S4-infra (SL-11..13, 14-day parity; must finish by S3b) ─────────────────────────────────┘

- **S4-infra** is off the critical path provided it finishes by S3b. Each day it overruns delays accrual, because the look's draws need its replay machinery. S4-gate overlaps accrual and gates only S5.
- **SL-13b** starts at S3a and may overrun S3b. V2's draws are replayed from captured tape but are quarantined until SL-13b parity holds, which is the S4-gate rule.
- **The n_min wait** binds only if S1 exits before the holdout reaches n_min (§4.1).

### 4.1 S2 gates (pre-declared; holdout = v5.0 from 2026-07-01; 95% seeded bootstrap with 2,000 draws; D+1 lead only)

**Holdout minimum n_min (R3-04), fixed at S0:**
- **Power target:** 80% power, two-sided α = 0.05, for G2.2's paired rung-Brier difference (M2 − M1). The target difference is **X = 0.0152**, the 09-20 resolution gap [VER ruling :45]. An M2 whose Brier gain over M1 is smaller than that cannot plausibly close the resolution deficit that closed the prior class, so detecting less is not decision-relevant. The same number anchors G2.3.
- **Formula:** n_min = ⌈((z(0.975) + z(0.8))·σ_d / X)²⌉, where σ_d is the SD of the per-station-day mean paired Brier difference.
- **Planning value:** σ_d ≈ 0.11, which is the σ_d implied by Rev 2's ±0.009 bound at 590 station-days. That gives n_min ≈ (2.802·0.11/0.0152)² ≈ **412 final station-days**, about 103 days × 4 stations [INF].
- **S0 replaces σ_d with its validation-split estimate.** This is outcome-free for the holdout. The date-clustered design effect is reported as sensitivity (Q13).
- **If the final holdout count is < n_min at S2 run time, S2 waits.** The wait is weather-only and costs no α. Calendar impact is in §5.

- **G2.0 Window mismatch (hard sub-gate, R2-09, R3-05, R3-07):**
  - The residual r = CLI tmax − calibrated M2 median is reported **by calendar month and by day-length tercile** (LST daylight hours, tercile edges fixed on train).
  - "Flat" means that no tested month's and no tercile's mean residual differs from 0 under a Holm-corrected two-sided test at family α = 0.05.
  - Clustering is by **date**. One residual per station-day makes station-day clustering degenerate, which `assert_nondegenerate_clustering` refuses [VER `forecast_conditional_scoring.py:278-300`].
  - **Month threshold N (fixed at S0):** only months with ≥ **N = 60 final station-days spanning ≥ 15 distinct dates** are tested. Fewer months are reported and flagged `UNTESTED`, and L's residual-by-month report monitors them post hoc (§4.3).
    - Justification [INF]: with residual SD ≈ 3 °F and worst-case full date correlation, the effective n is 15 dates. That gives SE ≈ 0.77 °F and 80% power for a month bias of ≈ 2.2 °F, about one 2 °F rung. That is the smallest bias that moves a whole rung.
    - The same N applies to the primary holdout and to a C-1 holdout.
  - **Closed correction set (R3-07):** {none, one offset per calendar month, linear in LST day-length}.
    - It is evaluated first on the validation split, where it spans all 12 months. The form is chosen there only. No other form may be introduced after S0.
    - It is then re-reported on the holdout. **A non-flat holdout result blocks G2.3.**
- **G2.1 Calibration (R2-05):**
  - For each populated reliability bucket with n ≥ 30: z = (observed − predicted)/SE, where SE is the station-day cluster-bootstrap SE (rung events share a station-day).
  - FAIL only if Holm at family α = 0.05 rejects in at least one bucket.
  - The ε = 0.05 miss count (`RELIABILITY_EPSILON` [VER `forecast_conditional_scoring.py:73`]) is **reporting only**. The evaluator itself notes that roughly half a miss is expected under perfect calibration [VER :382-388, :392-400].
- **G2.2 Skill vs M1:** paired rung-Brier difference (M2 − M1) CI upper < 0, **or** D_res(M2 − M1) CI lower > 0. The power target is X above.
- **G2.3 Materiality vs M0 (R2-12):** M0 is reproduced on the **same** holdout D+1 rung events at the same cycles as M2. It uses the NBS TXN of that cycle plus the frozen 0b bias/sigma.
  - Require **D_res(M2 − M0) station-day-clustered CI lower > 0 AND point estimate ≥ 0.0152**. The 0.0152 is the 09-20 market-minus-forecast resolution gap [VER ruling :45], used as a pinned materiality anchor.
  - Rationale: the CI term makes the improvement real on matched events. The floor makes it large enough to matter against the gap that closed the prior class.
  - A ratio (≥ 1.98× M0's resolution) is rejected, because M0's resolution is small and the ratio is unstable near 0.
  - The 09-20 reproduction on its own event set stays a separate positive control.
  - Failing G2.3 → taker variant V1 is dropped pre-registration. V2 may continue only if G2.0–G2.2 pass (Q8).
- **Contingency C-1 (pre-registered, R2-07, R3-05, R3-06):** triggered if and only if G2.1 fails on the v5.0 holdout while passing on the validation split.
  - It is the **only** permitted re-fit: a v5.0-only rolling refit.
  - Taking it **consumes the holdout look.** A fresh holdout opens forward from the declaration date. Its minimum is **the same n_min** (≈412 final station-days), not a round number of days.
  - **All four S2 gates (G2.0, G2.1, G2.2, G2.3) re-evaluate as a set on the fresh C-1 holdout.** None may reference, pool with, or be conditioned on the once-peeked holdout.
  - A full annual cycle cannot accrue before the KILL. So G2.0 on a C-1 holdout tests only months with ≥ N final station-days; the others are flagged `UNTESTED` and monitored by L.
  - It requires a documented protocol deviation in the evidence note, co-signed by mle-reviewer.
  - It is never a silent default and cannot be taken twice.
  - **Consequence, stated plainly:** declared at S2 (≈ late October 2026), a fresh ≈103-day holdout ends ≈ February 2027, after the 2027-01-25 KILL. **Taking C-1 almost surely moves S3b past the KILL**, which routes to §6 node 4 (hand-off to K-2).
- The method (§9 Q1) and all recalibration choices (§2.2) are made on the **validation** split. The exception is τ and the v5.0 parameters, which use validation plus the v5.0 fit slice (§2.2). The holdout is opened once, except via C-1.

### 4.2 S3a futility (SEARCH; spends no α)

- **Decisive statistic (R3-01):** every drop/keep decision below is computed **only on market snapshots whose price_ts falls in the permit-covered hours** (§3.3), read from `LAUNCH_UTC` and `PERMIT_TTL_NS` at run time.
  - S3a may also report an **all-hours** resolution comparison, labelled **"descriptive forecast-skill only"**.
  - It has no drop/keep output and is never used for any decision.
- **Fee (R3-09):** every fee is the venue's **quadratic** fee θ·qty·price·(1−price), never a flat per-contract fee.
  - Formula at [VER `fees.py:455`] (`expected_fee_for` :418-455) and in `taker_fee_at_fill` [VER `fees.py:560-594`, formula :593].
  - It is banker's-rounded per fill, as in `taker_fee_at_fill`.
- **Taker V1:** drop if D_res(model − market ask) CI upper < 0 (strictly worse, as on 09-20).
- **Maker V2 (R2-06):**
  - Fill model: conservative trade-through.
  - Fee: a **pessimistic ceiling of maker θ = taker θ 0.0695** in the same quadratic form, until the A0 pack measures the maker fee on the wire. It is never zero, never a placeholder, and never the documented rebate −0.0125 (§1.1 item 6).
  - **Adverse-selection haircut:** each simulated fill is marked against the worst executable opposite price in a fixed post-fill window W: h = max(0, fill_px − min best-bid of the same leg over (t_fill, t_fill + W]). W is fixed at S0; the proposal is 5 min. Maker EV = settlement EV − fee − h.
  - Drop if the point estimate is ≤ 0.
  - The **maker plausibility bound** uses the same fee ceiling and haircut.
  - If A0 has not landed by S3b, V2 is reported as **UNDERPOWERED-by-construction**.
- Every variant's table is written out, including failures (the WP7 (iv) analogue [VER PREREG_WP7:44-47]).

### 4.3 Learning loop L (weather-only, so it costs no firewall days)

Nightly:
1. Ingest the new NBP cycles.
2. Extend the CLI labels (provisional rows are marked and excluded from every gate, per §3.2 item 10).
3. Compute rolling v5.0 reliability and BSS vs M1 on final rows.
4. **Residual-by-month report (R3-05):** CLI − M2 median by calendar month on final rows. Months flagged `UNTESTED` at G2.0 are tracked here until they reach N, and are reported against the frozen artefact.
5. Run a drift alarm against the frozen artefact.
6. **Freshness heartbeat (R2-14), distinct from drift:** alert when the newest NBP cycle, or the newest final CLI label, is older than a threshold fixed in SL-15. The heartbeat has its own injected positive control.
7. Produce a monthly candidate artefact with a new sha.

Both alarms are delivered through the alerts.env egress convention [MEM].

Guardrails:
- **A candidate is never auto-swapped.** Swapping the artefact of a registered or live family is class (C) under L-34, so it needs a ruling plus a new manifest.
- A new NBM version appearing in the bulletin header raises a CRITICAL alert and triggers a re-validation run.

### 4.4 S4-infra firewall rule (RA-13:5; R2-01)

Shadow decisions on post-freeze tape are **not scored** before registration:
1. The shadow log carries decision keys and decision inputs only.
2. The parity tool compares the live shadow log with a replay of the same tape for decision-key set equality. It emits mismatch counts only.
3. A contract test pins that the parity tool imports no settlement, CLI-label or P&L module.
4. No aggregate of ev_net or of outcomes is computed or reported.
5. Logs are sha-sealed. Every analysis script refuses to read them pre-registration: the SL-9 date guard is extended to shadow logs.

If S0 (Q5) cannot certify that post-freeze logs stay unscored, S4-infra parity is **restricted to replay on pre-freeze tape (≤ 2026-09-25) plus live liveness** (actor publishes, strategy subscribes, decisions not persisted). S4-gate then carries the first post-freeze parity.

---

## 5. Power and statistics

**Confirmatory metric (CLOSED, §1.1):** `MEAN_EXCESS_PER_TAKE`, one value per station-day. Zero-take days are excluded. Variance bound 1/4. Single look. Formula `MDE = (z(1−α_v) + z(0.8))·0.5/√n` [VER `hypothesis_ledger.py:190,194,861-874`].

| k (α_v) | MDE n=100 | n=150 | n=300 | n=320 | n=350 | n=450 | n=600 | n for MDE 0.04 |
|---|---|---|---|---|---|---|---|---|
| 1, pooled §2.5 (0.00625) | 0.167 | 0.136 | 0.096 | 0.093 | 0.089 | 0.079 | 0.068 | ≈1,742 |
| **2, default (0.003125)** | 0.179 | 0.146 | 0.103 | 0.100 | 0.096 | 0.084 | 0.073 | ≈1,998 |

[INF arithmetic] For k=2: z(0.996875) = 2.734, and (2.734 + 0.842)·0.5 = 1.788. For k=1 the value is 1.670, which matches RA-9's "n≈1743" [VER RA-13:10]. Pooling lowers the MDE by 6.6% at any n.

**Accrual [INF]:**
- 152 station-days since 2026-08-30 is about 4.9 per day including NYC [BRIEF]. That is ≈3.6–4 per day for the 4 stations, after about 9% venue-skipped days [MEM].
- Pre-freeze SEARCH corpus (08-30..09-25): ≈100 station-days (≈600 rung events).
- **Registration date:** Rev 2 assumed about 2026-10-20. With the n_min wait (S2 no earlier than ≈2026-10-17) plus S3a and S3b, it is now **≈2026-10-24..10-31**.
- Post-freeze from then to 2027-01-25 is ≈86–93 days, so **≈320–350 listed station-days**.
- Take-days are fewer still, because trials must fall inside the ≈10 h permit window (§3.3).
- So the MDE at the backstop is ≥ ~0.096–0.10 (k=2), or ~0.089–0.093 if pooled.
- Sibling plausibility bounds were 0.03–0.04 [VER ledger.jsonl:1,3,4].

**Verdict:** 152 station-days is **not sufficient** for the confirmatory EV test, and neither is any horizon before the KILL, unless S0 fixes an outcome-free plausibility bound of about 0.09–0.10 or more.
- That is implausible for takers against a 29% overround.
- For the maker, the bound must now survive the pessimistic quadratic fee ceiling and the haircut (§4.2), which makes it harder still.

**What to do about it, and how it stays honest:**
1. Keep k small: S2 and S3a pruning is legitimate because it runs on disjoint data. The D0 variants are already gone.
2. **Treat the S3a resolution comparison, restricted to permit-covered hours (§3.3, R3-01), as the decisive go/no-go.**
   - It carries far more information per station-day (all rungs, no selection): 64 clusters gave a D half-width of about ±0.014 [VER ruling :45]. About 100 station-day clusters give about ±0.011 [INF]. The permit restriction thins snapshots per cluster but keeps the D+1 station-day count, because every listed D+1 station-day has permit hours on the prior UTC evening.
   - The all-hours comparison is **descriptive forecast-skill only** and never drives a drop or keep.
3. If the power check fails, write the zero-look UNDERPOWERED record (no slot, no α). Then either take the H-ARCHIVE-RECAL revival route (an outcome-blind count trigger, subject to RA-13 Q1), or carry the model to K-2, where 24 cities multiply n [VER RA-13:59].
4. An optional Var-bound tightening for ask-capped variants needs an outcome-free justification [VER :293-295]. The gain is small (≤ 8%) [INF].

**S2 statistics (R3-04):**
- Rung-event Brier, Murphy decomposition `Brier = rel − res + unc`, with an exact-reconstruction check. On six-rung ladders, unc = 5/36 [VER ruling :36-38].
- **No Murphy implementation exists in the repo** [VER: grep `murphy` over `*.py` = 0 hits; `forecast_conditional_scoring.py:139-162` has reliability buckets only]. It is built in SL-7.
- **Holdout size.**
  - The v5.0 holdout (07-01..) holds ≈90 days × 4 ≈ **360 station-days** to 2026-09-28, before label gaps. The expected paired-Brier CI half-width is ≈ 1.96·0.11/√360 ≈ **±0.011** [INF].
  - At n_min ≈ 412 it is ≈ ±0.0106, and the 80%-power MDE equals X = 0.0152 by construction.
  - The v5.0 fit slice adds ≈58 days × 4 ≈ 230 station-days for the hierarchical fit only.
- **Calendar impact of the wait [INF].**
  - n_min is reached at ≈ 2026-10-12, or ≈ 2026-10-17 allowing ≈5% label gaps and final-CLI lag.
  - If S1 exits later (the backfill is 50–100 GB), the wait costs nothing.
  - Otherwise each day of wait delays registration one day and forfeits ≈3.6–4 post-freeze station-days. A two-week wait moves the MDE from ≈0.096 to ≈0.100 (k=2).
  - It does not change the verdict above.
- Station-day is the primary cluster for rung-event metrics. The date cluster is reported as sensitivity (Q13) and is primary for the one-per-station-day G2.0 residuals.

---

## 6. Decision tree to the goal state (no bare STOP)

The goal state is forecast-driven trading plus a running learning loop.

1. **S0 "not distinct"** → nothing is built. Evidence goes to `docs/evidence/`. The programme continues on RA-13 (R3 EDGE-4 count; KILL → K-2). Weather ingest is offered to K-2 planning.
2. **S2 fails (G2.0–G2.3) for M2 and for M1, with C-1 not triggered** → forecast skill on NWS CLI is refuted for NBM-derived distributions. Record the evidence note and close this hypothesis id as CLOSED (zero-look).
   - Next: optionally, GEFS + EMOS as the one remaining independent-information lever, only through a new S0-class ruling.
   - Otherwise follow the programme RA-13 path. L keeps running if K-2 needs the calibration.
3. **S3a: all variants futile** (on permit-covered hours) → the market holds more resolution than the model: a successful, informative null. CLOSED record. Next: the same as node 2, second bullet.
4. **S3b UNDERPOWERED, or C-1 taken (R3-05)** → a zero-look record with a revival count trigger (outcome-blind, if Q5/Q1 allow it).
   - C-1's fresh holdout outlives the KILL. So the C-1 gate set is evaluated for **K-2's** benefit, and the PM.us leg is not expected to register.
   - Keep L running, and finish S4-infra as a K-2 asset.
   - At a programme KILL, hand the model, artefact, ingest and actor to K-2, which needs a per-station TWC-vs-CLI reconciliation first [VER RA-13:60].
5. **Look REJECTED** → the slot stays occupied (no recycling [VER :816-819]). CLOSED. Next: the same as the node 4 hand-off.
6. **Look CONFIRMED + S4-gate** → one S5 ruling → operator enablement → live family (or families, under one hypothesis id) under its own PREREG tally (Q9), with L as the ongoing learning. **This is the goal state.**

---

## 7. Build slices (TDD: every slice is RED → GREEN with output kept)

**Every slice:**
- Focused `pytest` with `PYTHONPATH=<wt>/src` on the shared venv interpreter, invoked by its exact path. Never `uv` or `pip` from a worktree.
- `lint-imports`.
- The mypy ratchet `tests/unit/test_mypy_ratchet.py`, with the per-slice edit in the table.
  - `CLEAN` [VER :282-299] only ever grows. `CEILINGS` [VER :303-313] must never rise, and falling below a ceiling forces lowering it.
  - `src/breezy/app` is in neither set [VER :282-313]. SL-13 must confirm in its RED step how the ratchet treats that path, and must add zero errors.
- The full `scripts/ci/run_tests_no_egress.sh` after **every** merge, with the EXIT code read before any push [MEM].
- No `git stash`. Commits by explicit path. Briefs carry the §8 invariants verbatim.

| SL | Stage (order) | Files | RED tests (examples) | Contracts touched | mypy ratchet edit (R2-17) |
|---|---|---|---|---|---|
| 1a | S1 (1st) | `tests/unit/test_domain_forecast_point.py` only | `NBM_NBP` refused today; model set == floor-key set; `TXN_Q10..Q90`, `TXN_MEAN`, `TXN_SD` round-trip through Arrow; a sub-floor lag is refused. **All RED; no src change** | domain only | None. `tests/unit` ceiling 1466 must not rise |
| 2 | S1 (1st, ∥1a) | `src/breezy/ingest/nbm_quantile_parse.py` (pure, **no nautilus import**) + fixtures `tests/fixtures/nbm/nbptx_t13z_excerpt.txt`, `…t19z…`, `…t01z…` (real captures with provenance header, L-17/L-36) | 13Z first max column → D+1 (LST); missing codes; unknown layout **refuses and names the header key tree** (L-37); version-header capture; **TXN window recorded from a primary source or flagged UNKNOWN** (§3.2 item 8). **R3-08:** from these real fixtures, record whether a BBB-style correction indicator exists in the NBP header. Parse it if present; if absent, a test pins its absence on every fixture. The verified answer is written into the SL-2 note | ingest ↛ strategy/runtime [VER pyproject:77-98] | None (`src/breezy/ingest` is CLEAN) |
| 3 | S1 (1st, ∥1a) | `src/breezy/ingest/nbm_quantile_transport.py` + lag-census note | Streaming 4-station filter holds bounded memory (L-53); AWS→NOMADS fallback; Last-Modified captured; fake transport **plus one production-default construction** (L-55); no egress in the gate | Egress hosts reviewed by security-reviewer | None (CLEAN) |
| 1b | S1 (after 3) | `src/breezy/domain/forecast_point.py:146,159-162` | SL-1a turns GREEN; the floor equals the SL-3 census minimum rounded down to 5 min, with the census note sha cited in a comment | domain; the model/floor sets match [VER :156-158] | None (`src/breezy/domain` is CLEAN) |
| 4 | S1 (after 1b) | `scripts/analysis/nbp_backfill.py` → `~/.local/share/breezy/derived/nbp/` | Resumable per-file checkpoint; **dedupe (R2-13, R3-08)** per (station, cycle_runtime, variable, valid window), deterministic, with the ordering **branching on the SL-2 note**: (a) BBB verified present → keep max(BBB rank, LastModified, raw_sha256); (b) BBB absent → ordering degrades **explicitly** to max(LastModified, raw_sha256), logged once per run. A RED test covers each branch. Identical-sha duplicates collapse; tests for a retransmission, a correction and a tie; version tag; `available_at = max(LastModified, cycle+floor)`; `systemd-run --user` with memory caps [MEM] | New archive store added to the forbidden list at pyproject:139-146 (widen by one row, L-12) | Add the file to CLEAN if the ratchet accepts a clean file inside a ceilinged package (verify in RED); else none, and the `scripts/analysis` ceiling 364 must not rise |
| 5 | S1 (∥4) | `scripts/analysis/settlement_truth_dataset.py:259-279`; fetch reused from `settlement_alignment_study.py:359-405` | Windows cover 2026-01-01..yesterday; absent days reported, never interpolated; **gate inputs are final, latest-revision only** (§3.2 item 10); existing settlement tests byte-unchanged | Settlement tests untouched | `scripts/analysis` ceiling 364 not raised; lowered if errors are fixed |
| 6 | S2 (can start at S1) | `src/breezy/strategy/ladder_ev/quantile_density.py` (pure) | Complete partition sums to 1 (±1e-12); monotone CDF; tied integer percentiles; tails from mean/sd; the three §9 Q1 methods behind one closed enum; EMOS location-scale transform | strategy ↛ archive modules [VER pyproject:131-147] | None (`src/breezy/strategy` is CLEAN) |
| 7 | S2 | `src/breezy/analysis/brier_decomposition.py` | rel − res + unc reconstructs Brier to 1e-12; six-rung unc = 5/36 | analysis ↛ nautilus [VER :159-171] | Add the file to CLEAN; `src/breezy/analysis` ceiling 13 unchanged |
| 8 | S2 | `src/breezy/analysis/nbp_calibration.py`, `scripts/analysis/nbp_skill_study.py` | Split-order violation raises, **four splits** (§3.2 item 6); **holdout refuses to open while final n < n_min** (wait path, no marker written); holdout marker refuses a second run **except a C-1 run carrying a deviation record**; **hierarchical (a_v, γ_v) with τ chosen by LOVO CRPS: a poisoned holdout leaves τ and every parameter byte-identical**; both sensitivities emitted and flagged report-only; G2.0 Holm residual test; **G2.0 correction form outside {none, month offset, linear day-length} raises; months below N are emitted `UNTESTED`, never tested**; G2.1 Holm per-bucket z; G2.3 matched-event M0; **a C-1 run re-evaluates G2.0–G2.3 as a set and raises if any input row lies in the primary holdout**; EMOS + affine/isotonic chosen on validation only; seeded bootstrap → artefact (json + sha256) emitting `p_lower`/`p_upper` | analysis layer | Add the new analysis module to CLEAN; scripts as in SL-4 |
| 9 | S3a | `scripts/analysis/nbp_market_comparison.py` reusing wp7b `paired_brier` :467, bootstrap :475, hurdle :491, `sum_ask_row` :537, `select_reading` :591, `assert_complete_partition` :184 [BRIEF] | `AvailabilityLookAheadError` when `available_at_ns ≥ price_ts`; **refuses any tape day > 2026-09-25 and any S4 shadow log pre-registration**; date+hour scoping; NO legs priced only from the captured NO book; **fee is quadratic θ·qty·p·(1−p) (a test pins parity with `taker_fee_at_fill` [VER `fees.py:560-594`] and rejects a flat per-contract fee)**; maker θ ceiling 0.0695 + haircut W; NOT_EXECUTABLE outside the permit. **R3-01:** (a) snapshots outside [LAUNCH_UTC, LAUNCH_UTC + PERMIT_TTL_NS) are excluded from the decisive statistic; (b) the window is read from `trade_supervisor_core.LAUNCH_UTC` and `safety.PERMIT_TTL_NS`, and a monkeypatched constant moves the window, which proves nothing is hard-coded; (c) the all-hours output carries the label "descriptive forecast-skill only" and has no drop/keep field; (d) the drop/keep result is byte-identical when out-of-window snapshots are perturbed. Verify in RED that lint-imports allows these two constant imports from `scripts/analysis` | — | As SL-4 |
| 10 | **DROPPED** (R2-16) | — (a lead axis is unneeded for D+1 only; V1/V2 are separated by `composition_kind`) | **If revived** (S0 elects one composition_kind for both variants): widen `_STRATUM_AXES` [VER `hypothesis_ledger.py:367`], the `StratumFilter` fields [VER :375-388], `parse_stratum_filter` [VER :435-475] and the `StratumFilterCountMismatchError` guard [VER :334-336, :545-555] under a schema V4. RED: V2/V3 records round-trip byte-identical; V4 without the `execution` axis → `MissingStratumAxisError`; V4 count mismatch still raises | AUD-18 D6(i) contracts [VER pyproject:173-206] unchanged | (if revived) `src/breezy/analysis` ceiling 13 not raised |
| 11 | S4-infra | `src/breezy/ingest/nbm_quantile_actor.py` (mirrors `nbm_forecast_actor.py`, injectable transport :157 [BRIEF]) | Publishes ForecastPoints with measured `available_at`; stale-cycle alert; L-16 (no raise inside timer callbacks) | ingest layer | None (CLEAN) |
| 12 | S4-infra | `ladder_ev/forecast_subscriber.py`, `forecast_state.py` (scalar → quantile vector; the `value_at` visibility gate is kept [VER `forecast_state.py:97-102`]); new `forecast_quantile_ladder` strategy (the `_rest` strategy is SL-13b) | Decision uses `scoring.py` (`ev_net`, `ev_net_no`, margin, `rank_rows`); first-snapshot latch + permit rule per §3.3; qty ≡ 1. **Contract test (R2-18) forbids importing:** `breezy.strategy.ladder_ev.decision.exclusion_filter` [VER `decision.py:77-128`] and `ExclusionInputs` [VER :36-60], including the re-export `breezy.strategy.ladder_ev.exclusion_filter` [VER `ladder_ev/__init__.py:12-15,71`]; and `breezy.strategy.current_rung_hold.archive_table` `P_HOLD_LOWER` [VER `archive_table.py:40`] / `P_HOLD_UPPER` [VER :287], imported today by `current_rung_hold/decision.py:108` and `monitor_evidence.py:50`. (That filter's `dplus1_entry` refusal [VER `decision.py:123-124`] would also veto every D+1 trial.) | Live graph ↛ `breezy.analysis` [VER :149-157] | None (`src/breezy/strategy` is CLEAN) |
| 13 | S4-infra (manifest re-pin at S4-gate) | `app/trade.py`: a new branch beside the `continuous_rung_hold` branch [VER `trade.py:536-637`] (trial latch, `family_halt_submit_veto`, fee-drift probe, `required_fee_coefficient`, phase-0 permit guard, `exit_manifest`, `extra_actors`); the `forecast_ladder` refusal [VER :638-648] kept raising; `CompositionKind`/`_COMPOSITION_KINDS` +1 row [VER `persistence/family_manifest.py:109-112`]; `src/breezy/runtime/trade_supervisor_core.py` `COMPOSITION_KIND_SUBSCRIBED_MARKERS` +1 row [VER :161-165]; `deploy/families/pm_us_crh_fq_v1.json` (`DRAFT_NOT_REGISTERED`, density sha pinned, hypothesis id cited) | DRAFT refused without `allow_draft`; unpinned density refused [VER `persistence/family_manifest.py:179-185`]; halt veto honoured; exec deny chain `client.py:5327-5510` byte-unchanged; `forecast_ladder` boot still raises | Marker-map and CompositionKind exact sets widened by one reviewed row (L-12) | Zero new errors in `src/breezy/app` (unlisted; confirm the rule in RED); `runtime` and `persistence` stay CLEAN |
| **13b** | **Conditional (R3-02): built only if V2 survives S3a**; after S3a, before or overlapping S4-gate | A **second** `CompositionKind`/`_COMPOSITION_KINDS` row `forecast_quantile_ladder_rest` [VER `persistence/family_manifest.py:109-112`]; a **second** `COMPOSITION_KIND_SUBSCRIBED_MARKERS` row [VER `trade_supervisor_core.py:161-165`]; a second `trade.py` branch beside SL-13's; the `forecast_quantile_ladder_rest` strategy (resting bid, qty 1, same latch/permit rules); `deploy/families/pm_us_crh_fq_rest_v1.json` (`DRAFT_NOT_REGISTERED`, **same hypothesis id and density sha as SL-13**) | Exact-set tests widened by one reviewed row each, with SL-13's row unchanged. Both manifests cite the same hypothesis id; a mismatch refuses. The ledger stratum `composition_kind` separates V1/V2 draws. **The pooled-P&L veto input is the union of both manifests' station-day P&L**, and a test pins that a single-manifest input is refused while both are REGISTERED. Replay prices V2 fills at the taker θ through the default `PolymarketUSFeeModel` path (the pessimistic ceiling); `allow_maker` (rebate) stays off until A0, and a post-only order under the default path raises `MakerRebateUnmodelledError` [VER `fees.py:282-304`; `errors.py:305-322`]. **Q17:** confirm in RED how the active-family registry ("cardinality-1" [VER `trade_supervisor_core.py:154`]) treats two manifests. No widening is proposed here | Marker-map and CompositionKind exact sets +1 reviewed row each (L-12); SL-12's forbidden-import contract extended to the `_rest` strategy | As SL-13: zero new errors in `src/breezy/app`; `runtime`, `persistence`, `strategy` stay CLEAN |
| 14 | S4-gate / S3b | (external) PATH-B-SOURCE-GATE: triage replay sources scoped by `composition_kind` [VER `hypothesis_ledger.py:165-172`] | — | Owned by that item; consumed only | — |
| 15 | L | `scripts/analysis/nbp_learning_nightly.py` + a user timer | Drift detector fires on an injected positive control; **freshness heartbeat fires on an injected stale-cycle / stale-label control (R2-14)**; residual-by-month report covers `UNTESTED` months (R3-05); alert delivered via alerts.env; provisional labels never reach a gate; a candidate artefact is never written to the manifest | — | As SL-4 |

**One hypothesis, two manifests (R3-02).** When SL-13b is built:
- **S4-gate** re-pins **both** manifests to the registered artefact sha under the **same hypothesis id**. Each needs its own ≥7-day parity. A parity failure quarantines only that manifest's draws.
- **Ledger:** one registered row with k = 2, where V1 and V2 are strata by `composition_kind`. Each variant is tested at per_variant α = 0.003125.
- **Veto:** the pooled-P&L veto [VER `hypothesis_ledger.py:207`] is computed over the **union** of both variants' station-day P&L.
- **S5:** **one** A1-class ruling covers both manifests; neither arms on a separate ruling.
- **If V2 is dropped at S3a,** SL-13b is never built and all of the above collapses to V1 alone.

**Composition kind decision (recommended: new kind `forecast_quantile_ladder`; R2-19, R2-20):**
- **Fact:** `CompositionKind` already contains `"forecast_ladder"` [VER `persistence/family_manifest.py:109-112`], and the supervisor marker map already carries a row for it [VER `trade_supervisor_core.py:161-165`]. But `trade.py` refuses it at boot with a `SettingsError` [VER `trade.py:638-648`].
- **Reuse `forecast_ladder`:** zero manifest or supervisor edits. But it deletes that pinned refusal, re-opens the seam of the closed pm_us_crh_fc_v1 design, and blurs the ledger's `composition_kind` stratum [VER `hypothesis_ledger.py:367`] between the REJECTED class and this one.
- **New kind:** costs one reviewed row in `CompositionKind`, one in the marker map (L-12), and one branch. It keeps the closed seam raising, keeps the ledger strata clean, and lets V2 take a second kind (`_rest`, SL-13b) without a ledger schema change (SL-10 dropped).

---

## 8. Invariants restated for every brief

- Nautilus Trader is immutable (native extension only).
- `allow_short` stays False; NO exposure only via the native NO instrument.
- Never weaken or delete a safety, settlement, contract or NO-SEND test (widen exact sets by one reviewed row).
- Never name, assign or read an operator-reserved control. Plan prose says "the per-position cap" and "the daily budget" (L-39).
- Live enablement and clearing the A1 halt are operator-only.
- Full gate after every merge; lint-imports after every slice.
- No uv or pip from a worktree; no git stash.
- Investigation briefs to write-default CLIs must say read-only explicitly.

---

## 9. Risks and open questions (for peer review)

**Q1 Percentiles → probability.** Three methods are pre-declared, and S2 chooses among them on validation data only:
- (a) normal(TXNMN, TXNSD);
- (b) monotone PCHIP through the 5 percentiles with normal tails;
- (c) skew-normal fitted to the percentiles plus mean/sd by interval-censored least squares.

(b) degenerates when integer percentiles tie, which is common when SD < 2 °F [INF]. The hierarchical EMOS spread layer (§2.2) applies on top of whichever is chosen.

**Q2 Integer °F against 2 °F rungs.** The ±0.5 interval-censoring treatment is in §3.2 item 7. Does it bias the tail-rung probabilities, which carry the mispricing in the 09-20 worst bins [VER ruling :55-57]?

**Q3 v5.0 identifiability and holdout size (R3-04).** Train and validation hold no v5.0 rows.
- **Answer:**
  - a v5.0 fit slice (05-04..06-30);
  - hierarchical (a_v, γ_v) with LOVO-CRPS shrinkage;
  - two report-only sensitivities (v4.3-transfer; v5.0-anchored);
  - a holdout from 07-01 that S2 opens only at n ≥ n_min ≈ 412.
- **Open for review:** the planning σ_d = 0.11 and the choice X = 0.0152. The v5.0 refit remains **contingency C-1** (§4.1): pre-registered, it consumes the look, re-evaluates all gates, and routes to §6 node 4.

**Q4 NO side.** Native NO depth capture is limited (H-NO-SIDE ruling), and the venue nets a NO holding as short YES [MEM]. Should the variants be YES-only until NO depth coverage is measured?

**Q5 Firewall (RA-13:5).** Two questions:
- (a) Does a registered SINGLE_LOOK of a different hypothesis forfeit H-ARCHIVE-RECAL CONFIRM days? [INF] The Bonferroni split (:1118-1119) is the designed mechanism for a shared confirm corpus.
- (b) Does the §4.4 no-scoring rule suffice for S4-infra's post-freeze shadow logs? If not, the pre-freeze-only fallback in §4.4 applies.

**Q6 KNYC.** L-13 concerns observed-extremum cadence and plausibly does not bind the observation-free D+1 variants. Including NYC would add about 25% to n [INF] and would shorten the n_min wait. The default is excluded, per the brief.

**Q7 TXN definition.** Promoted to SL-2 (primary-source record) and gate G2.0. RESOLVED as a question; open only as data.

**Q8 Maker variant.**
- Is a conservative trade-through fill on Depth10 "non-synthetic" under A1 §7.1?
- Is W = 5 min the right haircut window?
- Is any maker plausibility bound ≥ 0.09 defensible under the quadratic θ 0.0695 fee ceiling and the haircut?
- The replay cannot measure queue position or slippage [MEM].

**Q9 Look policy.** A1 §7.4 cites "fresh LD-OBF α", but the ledger has withdrawn LD_OBF [VER :269-271]. Proposed reading: the confirmatory look is SINGLE_LOOK, and the post-enablement live tally is governed by the family's own PREREG. This needs a ruling.

**Q10 Ledger shape.** RESOLVED (R2-16): one hypothesis, k=2, existing axes, and SL-10 dropped. It is revived only if S0 puts V1 and V2 on one composition_kind.

**Q11 Composition kind:** see §7 (the new kind is recommended; SL-13b adds the `_rest` kind conditionally).

**Q12 D0 observation truncation.** RESOLVED (R2-03): the D0 variants are dropped.

**Q13 Cluster choice.** WP7 used date-primary clustering [VER :143]; L-40 and the ledger use station-day. Synoptic correlation across 4 stations on the same date may widen the CIs. This is reported as sensitivity, including the design effect on n_min; date is primary for G2.0.

**Q14 The G2.3 floor.** RESOLVED (R2-12): matched events, CI lower > 0 AND point ≥ 0.0152; the ratio is rejected.

**Q15 HUNT-1 vs the permit window (R3-01).**
- **Decided for S3a:** the decisive go/no-go is scored only on the permit-covered hours [LAUNCH_UTC, LAUNCH_UTC + PERMIT_TTL_NS), read from code at run time. All-hours results are descriptive forecast-skill only.
- **Still open for the S0 and S5 rulings:** A1 §7 item 5 requires all hours. Does a permit-bounded hour-coverage table satisfy HUNT-1?

**Q16 Permit TTL and launch timing.** These are outside this plan and adjacent to operator enablement. The plan does **not** propose changing them; the question is listed so the S5 ruling can see what the permit window costs in take-days.

**Q17 — RESOLVED round 3 (architect): option (b).** One node arms exactly ONE sending family. Evidence: `SENDING_FAMILY_ID_VAR` refuses more than one id (settings.py:356); `sending_family_id` is a single slot (settings.py:816-820); trade.py:429-435 resolves the ONE sending family; single submit-intent flock (submit_intent.py:556). The registered look covers both V1 and V2 through offline replay, which never reads `sending_family_id`. The S5 ruling arms one manifest; swapping is a manifest + env act. Options (a) (widening) and (c) (pooling) are rejected. V2 is not deferred: only its live arming is sequenced. Original question follows.

**Q17 Two manifests vs the cardinality-1 registry (R3-02).** The supervisor describes an "active-family registry, cardinality-1" [VER `trade_supervisor_core.py:154`]. If only one family can be active per node, V1 and V2 cannot both run live.
- SL-13b's RED step must establish the fact.
- If it holds, the options are:
  - (a) a separately planned, reviewed widening, which is out of scope here;
  - (b) the S5 ruling arms one manifest, while the look still covers both variants' draws via replay;
  - (c) pooling via SL-10.
- This is for S0 and the architect.

**Operational risks:**
- The 50–100 GB streamed backfill hits memory limits (L-49/L-53). Mitigation: per-file caps and resume.
- AFOS CLI gaps in 2026, and late finals. Mitigation: declare them, never interpolate; final-only gating; missing finals lengthen the n_min wait.
- The bulletin format changes across versions. Mitigation: refuse loudly (L-37).
- Concurrent agents in one tree [MEM]. Mitigation: a worktree per slice, each with its own scratchpad.
- The KILL pre-empts S3b. It almost surely does if C-1 fires (§4.1 → §6 node 4).
- S4-infra overruns S3b, which loses accrual days (§4). An SL-13b overrun quarantines V2 draws until parity.
- `LAUNCH_UTC` or `PERMIT_TTL_NS` changes between S0 and S3a. Mitigation: S0 records the values; SL-9 reads them live and refuses if they differ from the S0 record without a ruling.

---

## 10. Documentation tasks

1. **PROGRESS.md:30 is stale** [VER]. It still says "arming displaces `pm_us_crh_cont`". Replace it with: the Rev5 `pm_us_crh_fc_v1` path was closed 09-20 (`RULING_forecast_edge_programme_closes_2026-09-20.md` §4.3-4.4), and `pm_us_crh_cont` is **not** displaced. Add one backlog row linking this plan. Stay within the 250-line / 12 KB budget [VER PROGRESS.md:9].
2. Evidence notes as named in §4, plus the SL-2 TXN-window + BBB note and the SL-3 lag-census note. This plan is saved under `docs/plans/`. Before the gate runs, confirm this doc contains zero env-var names of the reserved controls (L-39).
3. Add a LESSONS.md entry only if a peer finds a plan defect (dedupe first). Candidates:
   - "A gate that fails on one ε-bucket miss contradicts its own evaluator's multiplicity note" (R2-05).
   - "A holdout drawn entirely from a version absent from train/validate makes the version parameters extrapolated; fit a slice or shrink" (R3-04).
