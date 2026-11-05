# Probabilistic-Forecast Family (NBM NBP): plan from reopening ruling to arming and learning

- **Date:** 2026-09-29
- **Status:** DRAFT Rev 1, for the mandatory adversarial peer review
- **Owner:** coordinator (Breezy main session). Plan author: planner (blind)
- **Proposed path:** `docs/plans/FORECAST_NBP_PROBABILISTIC_FAMILY_Rev1_2026-09-29.md`
- **Evidence labels:** [VER] means read in the repo this session, with file:line. [BRIEF] means a coordinator-verified fact. [MEM] means project memory. [INF] means an inference, to be tested in peer review.

---

## 0. Summary

We build a probabilistic daily-max model from the NOAA NBM **NBP** percentile bulletin. We calibrate it against **NWS CLI** truth using only weather history, and score it against the closed model and an NBS+XND normal baseline. Only then do we compare it with Polymarket.us prices.

The stages that decide forecast skill (S1–S2) touch no venue data. They spend no α and no firewalled tape. The market comparison is split in two:
- a SEARCH run on pre-freeze tape (S3a);
- one registered confirmatory look (S3b).

Arming follows the RULING_A1 §7 path. Every gate has a named next action.

**Honest headline [INF, arithmetic in §5]:** the ledger's pinned per-take EV test can confirm only an edge of about **0.09–0.11 per take** before the 2027-01-25 KILL backstop. Taker variants at plausible edges of 0.03–0.04 will almost surely come back `UNDERPOWERED_NOT_REGISTERED`. The plan still pays off:
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
| Lead / cycle | "no lead or cycle-age partition", D0 only | D0 (07Z) and D+1 (12/13Z onward) as registered variants |
| Hours | Windows 09–12, 12–17, 10–11 LST | All venue hours (HUNT-1) |
| Execution | Taker at ask only | Taker **and** maker/resting-bid |
| Cluster | Date primary (:143) | Station-day primary (L-40); date-clustered reported as sensitivity |

**S0 ruling obligations:**
1. Argue distinctness on each row of the table above.
2. Pre-declare that a model which does not improve *resolution* over the closed model is **not** a distinct hypothesis. This is the §4 S2 gate G2.3.
3. Fix per-variant plausibility bounds **before** any tape is scored.
4. Fix the NBS+XND fallback rule of §2.2.
5. Answer the firewall questions Q5 and Q9 (§9).

### 1.2 RULING_A1 §7 re-arm criteria, mapped [VER `RULING_A1_pm_us_crh_v4_disposition_2026-09-21.md:402-440`]

| §7 item | Requirement | Where this plan meets it |
|---|---|---|
| 1 (:404-406) | Edge estimate on real venue ladders, station-day-clustered 95% CI excludes 0 | S3b confirmatory look on post-freeze forward tape (real ladders) |
| 2 (:407-408) | No dependence on the `P_HOLD_*` collider cells | By construction: the family never imports `decision.py`'s exclusion filter or the P_HOLD density half. A contract test pins this (SL-12) |
| 3 (:409-414) | A0 fee-drift evidence pack | External dependency (RA-1 A0 clock). Also required to learn the maker fee (Q8) |
| 4 (:415-417) | Fresh manifest per POST_FORECAST §A-9 item 2, n reset to 0 | SL-13 manifest, `DRAFT_NOT_REGISTERED` until S5 |
| 5 (:423-437) | HUNT-1: all hours | The trigger is every quote update in all venue hours (§3.3). D+1 variants hunt D−1 around the clock without needing observations |
| 6 (:438-440) | New A1-class ruling | S5 |

### 1.3 Interaction with the programme clocks

- **RA-13 KILL backstop 2027-01-25** [VER `RULING_RA-13_programme_kill_2026-09-27.md:45-48`]. Trigger R4 is "a new estimand that clears its power check at intake" [VER :53]. This family is an **R4 candidate**:
  - REGISTERED at S3b → the KILL is pre-empted.
  - `UNDERPOWERED_NOT_REGISTERED` → R4 is not met, and the KILL clock keeps running.
  - The date is firm; capture holes do not extend it [VER :46].
- **R3V-b on 2026-10-01** [VER PROGRESS.md:58]: if R3 is ruled not viable, "programme KILL decision forward + K-2". S0–S2 touch no tape and run in parallel, so R3V-b does not gate them.
  - If the KILL fires before S3b registers, the PM.us leg (S3b–S5) ends.
  - S1, S2 and L (the learning loop) are handed to K-2 as exchange-portable assets (CLAUDE.md priority 5).
  - The coordinator should cite this plan as a pending R4 candidate in any KILL ruling.
- **Firewall.** RA-13 binds that "any statistic on post-2026-09-25 tape forfeits H-ARCHIVE-RECAL CONFIRM days" [VER RA-13:5]. The corpus rule is freeze-date separation [VER PREREG_WP7:48-63; RULING_H-ARCHIVE-RECAL:57]. Therefore:
  - S3a SEARCH uses tape **≤ 2026-09-25** only, enforced by a code guard (SL-9).
  - No dev or replay run happens on post-freeze tape before registration [VER RA-13:35].
  - Whether a *registered* single look forfeits sibling days is open question Q5.

---

## 2. Hypotheses (pre-registered at S0; frozen at S3b)

### 2.1 Legs

- **H-FC-NBP-SKILL (S2, weather only, no α from the programme ledger):** the calibrated NBP rung probabilities beat (a) the closed model M0 and (b) the NBS TXN+XND normal M1. Metrics are rung-event Brier and Murphy resolution against CLI on the v5.0 holdout. This is a **necessary-condition screen** on data disjoint from any venue corpus. It prunes variants, but it never claims edge.
- **H-FC-NBP-MKT-SEARCH (S3a, SEARCH corpus, no α):** on pre-freeze tape, model rung probabilities are not strictly worse than the market on resolution (WP7b shape).
- **H-FC-NBP-EV (S3b, confirmatory, programme ledger):** `MEAN_EXCESS_PER_TAKE > 0` after θ = 0.0695 at executable prices, per variant, SINGLE_LOOK [VER `hypothesis_ledger.py:197,202,269-271`].

### 2.2 Models (comparators, not α variants)

| Id | Model | Role |
|---|---|---|
| M0 | NBS TXN + frozen 0b bias/sigma (the closed model) | Reproduces the 09-20 numbers as a positive control |
| M1 | NBS TXN mean + XND sd, normal, 0.5 °F continuity (IEM MOS on disk) | Zero-plumbing baseline |
| M2 | NBP percentiles → CDF (method chosen in S2 from §9 Q1) → affine recalibration | Candidate |

**Pre-declared fallback:** if M2 does not beat M1 at G2.2 but M1 passes G2.1–G2.3, M1 becomes the family model. S0 must state whether M1 alone is distinct under §1.1; the day-varying XND spread is the only difference from M0. If S0 rules M1 not distinct, the fallback is void.

### 2.3 Trading variants (k ≤ 4; cap at `hypothesis_ledger.py:181`)

| V | Lead | Execution | Cycle feed (latest available ≤ decision) |
|---|---|---|---|
| V1 | D+1 | Taker at ask, qty 1 | 12/13Z, 19Z, 00/01Z targeting D+1 |
| V2 | D+1 | Maker: resting bid, qty 1 | same |
| V3 | D0 | Taker at ask, qty 1, obs-truncated (Q12) | 07Z (plus any cycle whose first max column is D0, verified in SL-2) |
| V4 | D0 | Maker, obs-truncated | same |

Every variant counts toward k. S2 and S3a may **drop** variants before S3b; they never add one (the WP7 rule (i) analogue [VER PREREG_WP7:30-33]). The side is YES plus the native NO instrument (`allow_short=False`); see Q4.

### 2.4 α budget [VER `hypothesis_ledger.py:156,175,179,1118-1119`]

- Re-arm gating requires programme α ≤ 0.025. `allocated = 0.025/4 = 0.00625` per hypothesis, and `per_variant = 0.00625/k`.
- All four programme slots are free today: the four existing rows are all zero-look [VER ledger.jsonl:1-4; `programme_budget_remaining` :813-822]. This hypothesis takes one slot (the "maker reserve" slot named at :176-178, or any free slot).
- **Mechanical blockers today:** a schema-v3 (re-arm-gating) REGISTERED write is refused while `HORIZON_TOLLING_LANDED` (:164) and `PATH_B_SOURCE_GATE_LANDED` (:172) are False. The UNDERPOWERED path is unaffected [VER :942-943]. Both flags are **external dependencies of S3b**.
- `_STRATUM_AXES` has no lead axis [VER :367]; see Q10 and SL-10.
- `RULED_HORIZON_DAYS ∈ {120,180}` [VER :151].

---

## 3. Data and leakage controls

### 3.1 Sources (binding principle: US weather only)

- **Predictors:** NBP `blend_nbptx.tHHz`, primary on AWS `noaa-nbm-grib2-pds`, NOMADS as fallback [BRIEF]. Also IEM MOS NBS 2021–2026 on disk (M0, M1) [BRIEF].
- **Labels:** the NWS CLI settlement-truth parquet [BRIEF].
  - **Correction [VER `settlement_truth_dataset.py:259-279`]:** coverage is the 2021–2025 station-years plus **2026-08-16/17..2026-08-23 only**. The docstring (:276-278) records a hole from 2026-01-01 to 2026-08-15.
  - So the v5.0 holdout (from 2026-05-04) currently has about **one week of labels**, and the v4.3 tail (Jan–May 2026) is missing. Extending the labels (SL-5) is a hard prerequisite of S2.
- **Venue:** the Depth10 forward tape since 2026-08-30, used **only** for cost (ask + fee; bid and fill model for the maker variants).

### 3.2 Leakage controls (each one enforced by a test)

1. **Availability, not cycle.** Every model probability carries `available_at_ns`. For archive records, `available_at = max(S3 LastModified, cycle + floor)`. For live records it is the measured ingest time. `ForecastPoint` already separates `ts_event = cycle_runtime_ns` from `ts_init = available_at_ns` [VER `forecast_point.py:380-381`].
   - The new comparison guard raises unless `available_at_ns < price_ts_ns`. The WP7b guard checks cycle issuance vs decision [VER `wp7b_market_as_forecaster.py:288-304`], so it is **replaced**, not reused.
   - Assert `ref.ts < take.ts` on every row [MEM implausible-result-is-a-leak].
2. **Publication-lag floor.** Add `"NBM_NBP"` to `FORECAST_MODELS` (:146) and `MINIMUM_PUBLICATION_LAG_NS` (:159-162). The floor value comes from the SL-3 lag census (the minimum observed LastModified − cycle, rounded down to 5 min). It is never guessed.
3. **Climate day in LST.** CLI day = local standard time midnight to midnight, no DST. Lead hours are computed in LST. The WP7b UTC-boundary index at `wp7b…py:262-281` is **not** inherited.
4. **Windows scoped by date AND hour** for all tape work. For S3a, a hard refusal of any tape day > 2026-09-25.
5. **Version strata.** A constant `NBM_VERSION_BREAKS` holds 2020-09-29, 2023-01-17, 2024-05-15, 2025-05-27 and 2026-05-04 [BRIEF]. Every row is tagged. Fits include version offsets. The holdout is v5.0 only.
6. **Time-ordered splits.** Train 2021-01-01..2024-12-31; validate 2025-01-01..2026-05-03; holdout 2026-05-04..last CLI. A split whose train max ≥ validate min raises. The holdout is opened **once**: a marker file makes a second run refuse, mirroring SINGLE_LOOK.
7. **Integer rounding.** Both the CLI value and the NBP percentiles are integer °F. The integer label is treated as latent in [x−0.5, x+0.5). Rung probability = F(hi + 0.5) − F(lo − 0.5) over a **complete partition**, asserted with `assert_complete_partition` [VER `wp7b…py:184` per BRIEF].
8. **Definitional mismatch [INF, Q7].** NBM TXN may be a daytime-window maximum, while CLI is the calendar-day maximum. Calibration absorbs the mismatch on average. S2 reports the residual by season.
9. **Artefact isolation.** Live code sees calibration only through the sha-pinned manifest artefact [VER `family_manifest.py:179-185,211-219` per BRIEF; `pyproject.toml:131-147,149-157`].

### 3.3 Trial trigger (L-34, pinned at S3b)

- Evaluation runs on **every** quote or depth update in all venue hours.
- The trial is the **first executable snapshot** per (station-day, rung, side, variant) that satisfies `ev_net > margin` under the latest available cycle. One latch; qty 1 [VER `hypothesis_ledger.py:200`].
- A new cycle never re-opens a latched rung.
- Sizing never reads `kelly_stake_fraction`, and no operator-reserved value is read or assigned.

---

## 4. Stages

| Stage | Entry | Work / artefacts | Exit (pass) | Terminal negative → next action | Owner (agent types) |
|---|---|---|---|---|---|
| **S0** Reopening ruling + registration plan | This plan peer-reviewed to convergence | `docs/evidence/RULING_forecast_nbp_reopen_<date>.md`: §1.1 distinctness, §2 variants, plausibility bounds, fallback rule, firewall answers, horizon choice (120/180), schema-axis decision | Two blind peers APPROVE (AUD-18:1148-1154 pattern) | Ruled "not distinct" → no build; record why; programme stays on the RA-13 path (R3 / KILL → K-2) | Author: trading-bot-architect. Adversarial: prediction-market-reviewer. mle-reviewer for the stats sections |
| **S1** NBP backfill + CLI labels | S0 signed | SL-1..SL-5; `derived/nbp/nbp_quantiles.parquet`; extended `settlement_truth.parquet` through yesterday; lag-census evidence note | ≥95% station-cycle-day coverage per version stratum; the label gap 2026-01-01..08-15 is closed or itemised (never interpolated [VER :276-278]) | Archive gap > 5% in the v5.0 stratum → re-source via NOMADS for recent months; else S2 runs on what exists, with the gap declared | Implementer per CLAUDE.md order (Grok → Codex → tdd-guide); python-reviewer; security-reviewer (new egress) |
| **S2** Weather-only calibration and skill | S1 exit | SL-6..SL-8; `docs/evidence/NBP_SKILL_<date>.md`; calibration artefact (json + sha256) | G2.1–G2.3 below, per lead | See §6 node 2 | Implementer; mle-reviewer + prediction-market-reviewer on the evidence |
| **S3a** SEARCH vs market, pre-freeze tape | S2 pass for ≥1 lead | SL-9; WP7b-shaped report on 2026-08-30..09-25: paired Brier, D_res vs mid/ask, EV at ask, maker fill-EV (descriptive) | Per variant: not futile (rule below) | All variants futile → close with evidence; §6 node 3 | Implementer; prediction-market-reviewer |
| **S3b** Registration (single look) | S3a leaves ≥1 variant; ledger flags landed (§2.4) or UNDERPOWERED path | `hypothesis_register.py` intake with k = surviving variants, `re_arm_gating=True`, override 0.025, freeze commit | REGISTERED (power check clears) → R4 fires | `UNDERPOWERED_NOT_REGISTERED` → §6 node 4 | Coordinator runs the register; peers co-sign |
| **S4** Live ingest + shadow | REGISTERED | SL-11..SL-13; node composes the family with orders refused (phase-0 permit guard); nightly replay supplies the look's draws (needs PATH-B-SOURCE-GATE) | ≥14 consecutive days of shadow/replay decision parity (same take set ±0), actor liveness, no deny-chain change | Parity failure → fix under TDD; parity can never be waived | tdd-guide; python-reviewer; trading-bot-architect |
| **S5** Arming | Single look CONFIRMED + pooled-P&L veto passes [VER :207] | Evidence pack: look record, A0 pack, manifest A-9, HUNT-1 hour-coverage table, P_HOLD independence proof, parity report → NEW A1-class ruling | Ruling signed → **operator-only** enablement and A1-halt clear | REJECTED look → §6 node 5 | Author: trading-bot-architect. Reviewers: prediction-market-reviewer, security-reviewer |
| **L** Learning loop | S1 exit (runs whatever the other outcomes) | SL-15 nightly timer (see §4.3) | Runs nightly, and its drift detector fires on an injected positive control (L-38) | — | Implementer; python-reviewer |

### 4.1 S2 gates (pre-declared; holdout = v5.0; cluster = station-day; 95% bootstrap with 2,000 draws, seeded)

- **G2.1 Calibration:** |observed − predicted| ≤ 0.05 in every populated reliability bucket with n ≥ 30 (reuses `RELIABILITY_EPSILON` [VER `forecast_conditional_scoring.py:73`]).
- **G2.2 Skill vs M1:** paired rung-Brier difference (M2 − M1) CI upper < 0, **or** D_res(M2 − M1) CI lower > 0.
- **G2.3 Materiality vs M0:** point estimate of D_res(M2 − M0) ≥ 0.0152, the 09-20 market-minus-forecast resolution gap [VER ruling :45], on events matched to D0 at 09:00 LST.
  - [INF] This is a heuristic floor, because the event sets differ; see Q14.
  - Below the floor, the **taker** variants V1 and V3 are dropped pre-registration. Maker variants may continue only if G2.1 and G2.2 pass (Q8).
- The method choice (§9 Q1) and the recalibration form are chosen on the **validation** split. The holdout is opened once.

### 4.2 S3a futility (SEARCH; spends no α)

- **Taker variant:** drop if D_res(model − market ask) CI upper < 0 (strictly worse, as on 09-20).
- **Maker variant:** drop if the conservative trade-through fill-EV point estimate is ≤ 0.
- Every variant's table is written out, including failures (the WP7 (iv) analogue [VER PREREG_WP7:44-47]).

### 4.3 Learning loop L (weather-only, so it costs no firewall days)

Nightly:
1. Ingest the new NBP cycles.
2. Extend the CLI labels.
3. Compute rolling v5.0 reliability and BSS vs M1.
4. Run a drift alarm against the frozen artefact, delivered through the existing alerts.env egress convention [MEM].
5. Produce a monthly candidate artefact with a new sha.

Guardrails:
- **A candidate is never auto-swapped.** Swapping the artefact of a registered or live family is class (C) under L-34, so it needs a ruling plus a new manifest.
- A new NBM version appearing in the bulletin header raises a CRITICAL alert and triggers a re-validation run.

---

## 5. Power and statistics

**Confirmatory metric:** `MEAN_EXCESS_PER_TAKE`, one value per station-day. Zero-take days are excluded. Variance bound 1/4. Single look. Formula `MDE = (z(1−α_v) + z(0.8))·0.5/√n` [VER `hypothesis_ledger.py:190,194,861-874`].

| k (α_v) | MDE n=100 | n=150 | n=300 | n=450 | n=600 | n for MDE 0.04 |
|---|---|---|---|---|---|---|
| 1 (0.00625) | 0.167 | 0.136 | 0.096 | 0.079 | 0.068 | ≈1,742 |
| 2 (0.003125) | 0.179 | 0.146 | 0.103 | 0.084 | 0.073 | ≈1,998 |
| 4 (0.0015625) | 0.190 | 0.155 | 0.110 | 0.090 | 0.078 | ≈2,252 |

[INF arithmetic] Sanity check: the k=1 figure of 1,742 matches RA-9's "n≈1743" [VER RA-13:10].

**Accrual [INF]:**
- 152 station-days since 2026-08-30 is about 4.9 per day including NYC [BRIEF]. That is ≈3.6–4 per day for the 4 stations, after about 9% venue-skipped days [MEM].
- Pre-freeze SEARCH corpus (08-30..09-25): ≈100 station-days (≈600 rung events).
- Post-freeze from a likely registration date of about 2026-10-20 to 2027-01-25: ≈97 days, so **≤ ~350 listed station-days**. Take-days are fewer still.
- The MDE at the backstop is therefore ≥ ~0.09 (k=1) to ~0.10 (k=4).
- Sibling plausibility bounds were 0.03–0.04 [VER ledger.jsonl:1,3,4].

**Verdict:** 152 station-days is **not sufficient** for the confirmatory EV test, and neither is any horizon before the KILL, unless S0 fixes an outcome-free plausibility bound of about 0.09 or more.
- That is implausible for takers against a 29% overround.
- It is conceivable only for the maker variants, and only if adverse selection is small. That is a peer judgement, fixed at S0 (Q8).

**What to do about it, and how it stays honest:**
1. Keep k small: S2 and S3a pruning is legitimate because it runs on disjoint data.
2. Treat the S3a resolution comparison as the decisive **go/no-go**. It has far more information per station-day (all rungs, no selection): 64 clusters gave a D half-width of about ±0.014 [VER ruling :45], so 100 clusters give about ±0.011 [INF].
3. If the power check fails, write the zero-look UNDERPOWERED record (no slot, no α). Then either take the revival route the H-ARCHIVE-RECAL precedent uses (an outcome-blind count trigger, subject to RA-13 Q1), or carry the model to K-2, where 24 cities multiply n [VER RA-13:59].
4. An optional Var-bound tightening for ask-capped variants needs an outcome-free justification [VER :293-295]. The gain is small (≤ 8%) [INF].

**S2 statistics:**
- Rung-event Brier, Murphy decomposition `Brier = rel − res + unc`, with an exact-reconstruction check. On six-rung ladders, unc = 5/36 [VER ruling :36-38].
- **No Murphy implementation exists in the repo** [VER: grep `murphy` over `*.py` = 0 hits; `forecast_conditional_scoring.py:117` has reliability buckets only]. It is built in SL-7.
- The holdout is ≈148 days × 4 ≈ 590 station-days. Expected paired-Brier CI half-width is ≤ ±0.009 [INF, from the WP7b cluster SD; model-vs-model pairs are more correlated, so the true width should be tighter].
- Station-day is the primary cluster. The date cluster is reported as sensitivity (Q13).

---

## 6. Decision tree to the goal state (no bare STOP)

The goal state is forecast-driven trading plus a running learning loop.

1. **S0 "not distinct"** → nothing is built. Evidence goes to `docs/evidence/`. The programme continues on RA-13 (R3 EDGE-4 count; KILL → K-2). Weather ingest is offered to K-2 planning.
2. **S2 fails for M2 and for M1 on both leads** → forecast skill on NWS CLI is refuted for NBM-derived distributions. Record the evidence note and close this hypothesis id as CLOSED (zero-look).
   - Next: optionally, GEFS + EMOS as the one remaining independent-information lever, only through a new S0-class ruling.
   - Otherwise follow the programme RA-13 path. The learning loop keeps running if K-2 needs the calibration.
3. **S3a: all variants futile** → the market holds more resolution than the model: a successful, informative null. CLOSED record. Next: the same as node 2, second bullet.
4. **S3b UNDERPOWERED** → zero-look record with a revival count trigger (outcome-blind, if Q5/Q1 allow it). Keep L running. At a programme KILL, hand the model, artefact and ingest to K-2, which needs a per-station TWC-vs-CLI reconciliation first [VER RA-13:60].
5. **Look REJECTED** → the slot stays occupied (no recycling [VER :816-819]). CLOSED. Next: the same as node 4 hand-off.
6. **Look CONFIRMED** → S5 ruling → operator enablement → live family under its own PREREG tally (Q9), with L as the ongoing learning. **This is the goal state.**

---

## 7. Build slices (TDD: every slice is RED → GREEN with output kept)

**Every slice:**
- Focused `pytest` with `PYTHONPATH=<wt>/src` on the shared venv interpreter, invoked by its exact path. Never `uv` or `pip` from a worktree.
- `lint-imports`.
- The mypy ratchet `tests/unit/test_mypy_ratchet.py`: new modules must be clean.
- The full `scripts/ci/run_tests_no_egress.sh` after **every** merge, with the EXIT code read before any push [MEM].
- No `git stash`. Commits by explicit path. Briefs carry the §8 invariants verbatim.

| SL | Stage | Files | RED tests (examples) | Contracts touched |
|---|---|---|---|---|
| 1 | S1 | `src/breezy/domain/forecast_point.py:146,159-162` | `NBM_NBP` refused today; model set == floor-key set; `TXN_Q10..Q90`, `TXN_MEAN`, `TXN_SD` round-trip through Arrow; a sub-floor lag is refused. `tests/unit/test_domain_forecast_point.py` | domain layer only. Depends on the SL-3 lag census |
| 2 | S1 | `src/breezy/ingest/nbm_quantile_parse.py` (pure, **no nautilus import**, so `analysis` can reuse it) + fixtures `tests/fixtures/nbm/nbptx_t07z_excerpt.txt`, `…t13z…` (real captures with a provenance header, L-17/L-36) | 07Z first max column maps to D0 and 13Z to D+1 (LST); missing codes; an unknown column layout **refuses and names the header key tree** (L-37); version-header capture. `tests/unit/test_nbm_quantile_parse.py` | ingest ↛ strategy/runtime [VER pyproject:77-98] |
| 3 | S1 | `src/breezy/ingest/nbm_quantile_transport.py` | Streaming 4-station filter holds bounded memory (L-53); AWS→NOMADS fallback; Last-Modified captured; fake transport, **plus one production-default construction** (L-55). No egress in the gate | Egress hosts reviewed by security-reviewer |
| 4 | S1 | `scripts/analysis/nbp_backfill.py`, output `~/.local/share/breezy/derived/nbp/` | Resumable per-file checkpoint; dedupe; version tag from `NBM_VERSION_BREAKS`; `available_at = max(LastModified, cycle+floor)`. Runs as `systemd-run --user` with memory caps, one heavy job at a time [MEM] | New archive store added to the forbidden list at pyproject:139-146 (widen by one row, L-12) |
| 5 | S1 | `scripts/analysis/settlement_truth_dataset.py:259-279`, fetch reused from `settlement_alignment_study.py:359-405` | Windows now cover 2026-01-01..yesterday; absent days reported, never interpolated; existing settlement tests byte-unchanged | Settlement tests untouched |
| 6 | S2 | `src/breezy/strategy/ladder_ev/quantile_density.py` (pure) | Complete partition sums to 1 (±1e-12); monotone CDF; tied integer percentiles; tails from mean/sd; the three §9 Q1 methods behind one closed enum | strategy ↛ archive modules [VER pyproject:131-147] |
| 7 | S2 | `src/breezy/analysis/brier_decomposition.py` | rel − res + unc reconstructs Brier to 1e-12; six-rung unc = 5/36 | analysis ↛ nautilus [VER :159-171] |
| 8 | S2 | `src/breezy/analysis/nbp_calibration.py`, `scripts/analysis/nbp_skill_study.py` | Split-order violation raises; holdout-opened marker refuses a second run; LST lead; version offsets; seeded bootstrap parameter replicates → artefact (json + sha256) that emits `p_lower`/`p_upper` for `ladder_ev/scoring.py` | analysis layer |
| 9 | S3a | `scripts/analysis/nbp_market_comparison.py` reusing wp7b `paired_brier` :467, bootstrap :475, hurdle :491, `sum_ask_row` :537, `select_reading` :591, `assert_complete_partition` :184 [BRIEF] | `AvailabilityLookAheadError` when `available_at_ns ≥ price_ts`; **refuses any tape day > 2026-09-25**; date+hour scoping; NO legs priced only from the captured NO book | — |
| 10 | S3b (conditional on S0 Q10) | `src/breezy/analysis/hypothesis_ledger.py:367` add a `lead_days` axis, schema V4 | V1–V3 rows still round-trip byte-identically; V4 requires the axis | AUD-18 D6(i) contracts [VER pyproject:173-206] unchanged |
| 11 | S4 | `src/breezy/ingest/nbm_quantile_actor.py` (mirrors `nbm_forecast_actor.py`, injectable transport :157 [BRIEF]) | Publishes ForecastPoints with measured `available_at`; stale-cycle alert; L-16 (no raise inside timer callbacks) | ingest layer |
| 12 | S4 | `ladder_ev/forecast_subscriber.py`, `forecast_state.py` (scalar → quantile vector); `density_table.py` forecast half replaced (RUNG_IDS, Wilson, `partition_check`, sha-pinned load kept); new `forecast_quantile_ladder` strategy | Decision uses `scoring.py` (`ev_net`, `ev_net_no`, margin, `rank_rows`); **no import of `decision.py`'s exclusion filter or the P_HOLD cells**; first-snapshot latch per §3.3; qty ≡ 1 | Live graph ↛ `breezy.analysis` [VER :149-157] |
| 13 | S4 | `app/trade.py` new branch mirroring :536-636 (trial latch, `family_halt_submit_veto`, fee-drift probe, manifest `required_fee_coefficient`, phase-0 permit guard, `exit_manifest`, `extra_actors`); `trade_supervisor_core.py:158-165` +1 row; `deploy/families/pm_us_crh_fq_v1.json` (`DRAFT_NOT_REGISTERED`, density sha pinned) | DRAFT refused without `allow_draft`; unpinned density refused [VER `family_manifest.py:179-185`]; halt veto honoured; exec deny chain `client.py:5327-5510` byte-unchanged | — |
| 14 | S4 | (external) PATH-B-SOURCE-GATE: triage replay sources scoped by `composition_kind` [VER `hypothesis_ledger.py:165-172`] | — | Owned by that item; this plan only consumes it |
| 15 | L | `scripts/analysis/nbp_learning_nightly.py` + a user timer | The drift detector fires on an injected positive control; alert delivered; a candidate artefact is never written to the manifest | — |

**Composition kind decision (recommended: new kind `forecast_quantile_ladder`):**
- **Reuse `forecast_ladder`:** zero supervisor edits (the marker is already wired [VER `trade_supervisor_core.py:157-164`]). But it re-opens the seam of the closed pm_us_crh_fc_v1 design, deletes the pinned raise at `trade.py:637-647`, and blurs the ledger's `composition_kind` stratum [VER `hypothesis_ledger.py:367`] between the REJECTED class and this one.
- **New kind:** costs one reviewed marker-map row (L-12) and one branch. It keeps the closed seam raising and keeps the ledger strata clean.

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

(b) degenerates when integer percentiles tie, which is common when SD < 2 °F [INF]. Is the candidate set right, and should (c) be the default?

**Q2 Integer °F against 2 °F rungs.** The ±0.5 interval-censoring treatment is in §3.2 item 7. Does it bias the tail-rung probabilities, which carry the mispricing in the 09-20 worst bins [VER ruling :55-57]?

**Q3 Only ~5 months of v5.0.** Is a ≈590-station-day holdout enough to certify transfer across a version break? If G2.1 fails only on v5.0, the default is a v5.0-only refit with a rolling window, and the holdout moves forward in time. That delays S3b past the KILL.

**Q4 NO side.** Native NO depth capture is limited (H-NO-SIDE ruling), and the venue nets a NO holding as short YES [MEM]. Should the variants be YES-only until NO depth coverage is measured?

**Q5 Firewall (RA-13:5).** Does a registered SINGLE_LOOK of a different hypothesis, or a shadow decision log computed on post-freeze tape, forfeit H-ARCHIVE-RECAL CONFIRM days?
- [INF] The Bonferroni split (:1118-1119) is the designed mechanism for a shared confirm corpus, so the ruling-level prohibition targets SEARCH/dev runs. S0 must still say so explicitly.

**Q6 KNYC.** L-13 concerns observed-extremum cadence. Does it bind the observation-free D+1 variants? Including NYC would add about 25% to n [INF]. The default is excluded, per the brief.

**Q7 TXN definition.** Is NBM TXN a daytime-window maximum rather than a calendar-day maximum [INF]? This must be verified from NOAA NBM documentation in SL-2.

**Q8 Maker variants.**
- Is a conservative trade-through fill rule on Depth10 "non-synthetic" under A1 §7.1?
- The maker fee is unknown until the A0 pack exists. The replay cannot measure queue position or slippage [MEM].
- Is a maker plausibility bound of 0.09 or more defensible without outcome data?

**Q9 Look policy.** A1 §7.4 cites "fresh LD-OBF α", but the ledger has withdrawn LD_OBF [VER :269-271]. Proposed reading: the confirmatory look is SINGLE_LOOK, and the post-enablement live tally is governed by the family's own PREREG. This needs a ruling.

**Q10 Ledger shape.** One hypothesis with k=4 and a new `lead_days` axis (SL-10, schema V4), versus two hypotheses (D0 and D+1) with k=2 each. The second doubles per-variant α to 0.003125 but uses two of four slots. The recommended default is one hypothesis.

**Q11 Composition kind:** see §7 (the new kind is recommended).

**Q12 D0 observation truncation.** Proposed: condition on the conservative lower bound of the ASOS running maximum. Integer-°C METAR gives 1–2 °F bands [MEM], so the truncation never decides a band. Are D0 variants worth their k-cost, given that the hunt window opens after repricing [MEM]?

**Q13 Cluster choice.** WP7 used date-primary clustering [VER :143]; L-40 and the ledger use station-day. Synoptic correlation across 4 stations on the same date may widen the CIs. This is reported as sensitivity.

**Q14 The G2.3 floor of 0.0152.** It was derived from a different event set. Should it be a ratio instead (M2 resolution / M0 resolution ≥ 1.98)?

**Operational risks:**
- The 50–100 GB streamed backfill hits memory limits (L-49/L-53). Mitigation: per-file caps and resume.
- AFOS CLI gaps in 2026. Mitigation: declare them, never interpolate.
- The bulletin format changes across versions. Mitigation: refuse loudly (L-37).
- Concurrent agents in one tree [MEM]. Mitigation: a worktree per slice, each with its own scratchpad.
- The KILL pre-empts S3b (§1.3).

---

## 10. Documentation tasks

1. **PROGRESS.md:30 is stale** [VER]. It still says "arming displaces `pm_us_crh_cont`". Replace it with: the Rev5 `pm_us_crh_fc_v1` path was closed 09-20 (`RULING_forecast_edge_programme_closes_2026-09-20.md` §4.3-4.4), and `pm_us_crh_cont` is **not** displaced. Add one backlog row linking this plan. Stay within the 250-line / 12 KB budget [VER PROGRESS.md:9].
2. Evidence notes as named in §4. This plan is saved under `docs/plans/`. Before the gate runs, confirm this doc contains zero env-var names of the reserved controls (L-39).
3. Add a LESSONS.md entry only if a peer finds a plan defect (dedupe first).
