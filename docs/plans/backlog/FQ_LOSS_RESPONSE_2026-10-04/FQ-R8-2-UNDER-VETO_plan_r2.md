# r2 — supersedes r1

# Implementation Plan: FQ-R8-2-UNDER-VETO_plan_r2

<!-- planner, 2026-10-08. r2 of FQ-R8-2-UNDER-VETO_plan_r1.md. It applies every item in FQ-R8-2-UNDER-VETO_plan_r1-review-merge.md (D-1..D-18 and the Stage −1 ruling) and re-opens none of them. This is a plan only. No MC was run for it, and nothing here is evidence. Operator-reserved controls are referred to only by description and are never assigned. No frozen PREREG or frozen amendment is edited (F5_prereg_v2_design.json @072ab026, A0 @43cc3e0f, A1 once frozen). allow_short stays False. Nautilus is untouched. No safety, settlement, contract or firewall test is weakened or deleted. Every closed set this plan touches widens by exactly one reviewed row. -->

> **Coordinator note (2026-10-08).** F-14 and the step-8 line numbers were read from the main tree. The A1 R5 checker branch (`_check_floor`, provenance rule; branch `backlog/f5-a1r5-2026-10-08`) is built but not yet merged. After it merges, the step-8 edits keep their meaning, but their `:line` anchors move. Re-anchor them at implementation time.

## Change log (r1 → r2)

| Item | r2 change | Section |
|---|---|---|
| D-1 | Phase 1 split. **1a** (now): E-3, §R8-2(f), the plan and evidence rows in PROGRESS, and contract tests T2–T4. **1b** (after the A1 freeze): test T1 and the F6b CANCELLED row | Phase 1a, Phase 1b |
| D-2 | Exact checker edits to `_PAYLOADS`, `_AMENDMENT_FILENAME`, `_EARLIER` and `_check_payload`, one reviewed row each. `a1b_`-prefixed child keys. A disjointness test. A1 r4 recorded as a rejected alternative | Step 8; Options |
| D-3 | Calendar backstop: the terminal veto fires at the earlier of t_K and climate day 2027-01-25. The producer enforces it, and it is tested with an injected clock | Step 7 (terminal rule); Phase 4 |
| D-4 | The NP bound is evaluated on the information set the candidates use: ticks ≤ min(t_K, realised N) | Step 6 |
| D-5 | Stage 0 passes only if the bound is ≥ 0.30. A bound in [0.25, 0.30) counts as FAIL → (c′) | Step 6, node D1 |
| D-6 | The pass test and `np_reach_cutoff_e` both use the minimum over the same mix set | Step 6, node D1 |
| D-7 | Validity rationale replaced; "S4/S5 only lower power" removed | Step 6 |
| D-8 | Station-day Z_d units. Looks are Lan–DeMets information fractions of null variance. Type-I is checked at realised counts | Steps 6, 7, 8 |
| D-9 | Stage 0 precondition answered from code: G3 is measured at the realised tick count N over the epoch's calendar days, not at T_low. Cited file:line | Facts F-12; Step 6 |
| D-10 | α ≤ 0.10 as a point estimate in every binding cell, with the one-sided 95 % upper limit reported. Fresh-seed confirmation run; FAIL → (c′) | Steps 7, 8 |
| D-11 | G1/G3 count only boundary FAILs. The forced terminal veto is excluded, and a test pins this | Steps 7, 8 |
| D-12 | G-A restated as a bounded pilot. The post-t_K outcome is named | Overview; Phase 4 |
| D-13 | (c′) has a review date | Step 9 |
| D-14 | The deadlock claim is scoped to the current AUT-5 pins. Fill-free alternatives are listed with reasons | Deadlock; Options |
| D-15 | Under G-B, the row-7 L1 proof is stated to be a zero-fill proof | Step 10 |
| D-16 | Menu reduced to OBF/Pocock K ∈ {2, 3} plus truncated SPRT. The √t reference row and K = 4 are dropped. Planning figures labelled as Gaussian | Step 7; Options |
| D-17 | The AUT-5a-owned drawdown test is removed from this plan and handed to the row-7 WP | Step 4; Placement |
| D-18 | One-line PROGRESS note recording the E-2 calibration figures | Step 3 |
| Stage −1 | New Stage −1: check whether the frozen v2 design structurally excludes the M-yes mix, written down before Stage 0 runs | Phase 2, step 5 |

## Overview
The F5 A1 loss-stop floor is landing as `floor_mode: unreachable_veto`. Under E-2 (seed 20261008, 10k replicates), G3(−0.16) in the M-yes mix is 0.2104, below the floor of 0.25. With that mode, the F6 probe reads UNKNOWN and vetoes every FQ v2 entry. §R8-2 retirement needs live fills, so it cannot happen. This plan ends in exactly one goal state:

- **G-A, a bounded pilot.** FQ v2 trades for at most t_K ticks, and in any case only until climate day 2027-01-25, under a pre-registered A1b stop. The stop either FAILs at a look or forces a terminal veto. **The test does not bound the loss. The operator-reserved exposure controls bound it.** After t_K or the backstop, FQ v2 is vetoed. There is no bridge retirement by PASS, and any re-test needs a new prereg.
- **G-B.** A filed ruling, backed by evidence, that FQ v2 does not trade. It carries re-open triggers and a review date.

No third, open-ended state exists.

## Requirements
- R1. Reach G-A or G-B in a bounded number of steps (L-3).
- R2. Every stop cited as active must be able to fire, shown by a positive control (L-38). The A1b stop fires by construction, either as a FAIL or as the terminal veto.
- R3. No frozen PREREG or amendment is edited. A1b is a new additive amendment with its own MC and a fresh-seed confirmation run.
- R4. Operator-reserved controls are never assigned, never derived from, and never named by env-var name.
- R5. Nautilus is untouched. `loss_stop_probe.py` and its RC-7 composition in `app/trade.py` are not edited.
- R6. F6b is cancelled and replaced by contract tests. The contract tests are never deleted later; they carry closed allowlists that widen by one reviewed row.
- R7. The AUT-6 misattribution is corrected (E-3).
- R8. The plan's position relative to AUTONOMY QUEUE rows 6 and 7 is stated.

## Facts (read 2026-10-08)
| # | Fact | Source |
|---|---|---|
| F-1 | A missing artefact reads as UNKNOWN, which gives an immediate `REASON_UNKNOWN` veto | `src/breezy/strategy/forecast_quantile_ladder/loss_stop_probe.py:286-291, :327-332`; path `:118-119` |
| F-2 | Under `unreachable_veto`, the producer never writes PASS | `F5-pin-request_r3.md:71, :208, :217, :222` |
| F-3 | §R8-2 retirement needs (a) N = 5 EVALUATED PASS days with `drawdown_control_active`, (b) ≥ 10 live fills, (c) a fresh verdict, (d) a hand commit, (e) the H1 pre-flight | `F1-errata-and-deltas_r3.md:618-634` |
| F-4 | The drawdown H0 rate comes from the lineage's own real-money fills. Fewer than 14 days or fewer than 30 fills gives `halt_inert` | `AUT-5-promotion-demotion_plan_r7.md:766-768` |
| F-5 | `HALT_INERT` is never control evidence | AUT-5 r7 `:752-753` |
| F-6 | AUT-6 r15 owns drift and health only, with no loss detector | `AUT-6-drift-health_plan_r15.md`; README `:155-172` |
| F-7 | KILL cannot fire before 2027-01-25 | `F5-pin-request_r1-review-merge.md:106` |
| F-8 | Before January, the only loss controls are the F6 floor and the two operator caps. Worst case = daily budget × days armed | `F5-pin-request_r1-review-merge.md:107` |
| F-9 | E-2 rerun: c ≈ 2.05. G1 passes in every cell. G3(−0.16) = 0.579 (M-pool), 0.434 (M-no), 0.210 (M-yes). G3 never drives escalation | `F5-pin-request_r3-errata-E2.md:12-16` (worktree a1mc-1008); r3 `:209` |
| F-10 | Row-7 WP10 (stage S, L1, L2) waits on F8, F6, the resume bar and RC-5 (F9-B) | `F1 r3:681-684`; `PROGRESS.md:71` |
| F-11 | The misattribution "until AUT-6 retires the bridge" | `F5-pin-request_r3.md:222, :428-429` |
| F-12 | **G3 horizon (D-9).** See below this table | worktree a1mc-1008 HEAD; re-verify at the binding run's `script_git_sha` before Stage 0 |
| F-13 | The checker's `_PAYLOADS` (`:46-50`), `_AMENDMENT_FILENAME` (`:51-55`) and `_EARLIER` (`:56-63`) are closed maps. `_occupied` checks top-level keys plus one nested level (`:135-144`). `_check_additive` refuses any overlap with the parent or an `_EARLIER` file (`:219-241`). A missing earlier file is `EARLIER_AMENDMENT_MISSING` (`:205-211`) | `scripts/analysis/prereg_amendment_check.py` |
| F-14 | `_check_payload` still returns `PAYLOAD_NOT_YET_DEFINED` for A1 and A2 (`:311-322`) in both the main tree and the worktree. r3 §4.9's A1 R5 branch is unbuilt, and it is part of the A1 freeze. *(Superseded: see the coordinator note.)* | same file; r3 `:288-302` |
| F-15 | E-1 and E-2 exist only in worktree a1mc-1008. The binding E-2 rerun file is not on disk; only `…_run1_pre_E2.json` is | worktree `docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04/`, `docs/evidence/f5/` |
| F-16 | The frozen v2 design has no side key. Its only price rule is `ask_floor` 0.05 | `F5_prereg_v2_design.json:1-37` |

**F-12 detail (D-9).** All references are in worktree a1mc-1008.
- Per-epoch G3 is `power(delta, mix, n_days, t_star, solved)`, where `n_days = inclusive_days(e, horizon)` (`fq_loss_floor_mc_report.py:209, :223-226`; `fq_loss_floor_mc_engine.py:270-272`).
- `power` is `crossing_rate(crit(gate_sims[(delta, mix)], n_days, t_min), solved)` (`engine.py:316-317`).
- `_criticals` truncates each simulated path at `cuts[min(n_days, len(cuts)) - 1]`, which is a calendar-day cut (`engine.py:108-116`).
- The H1 paths are thinned at `p_gate` (`engine.py:292-302`).
- So G3 is measured at the **realised** tick count N within the epoch's calendar days. `T_low` (`report.py:210`; `fq_loss_floor_mc_gate.py:122-128`) feeds G1 only (`report.py:216-220`).
- The freeze-date G3 uses `lengths[freeze_key]` (`report.py:199-205`).

**The deadlock, scoped to the current AUT-5 pins (D-14).** F-2 means zero v2 fills. That makes F-3(b) unreachable. Under AUT-5 r7's pins (drawdown H0 from the lineage's own fills; ≥ 30 fills and ≥ 14 days), the v2 drawdown block is inert (F-4), so F-3(a) is unreachable too (F-5). **Under those pins**, no drawdown control can be calibrated without v2 fills.

Fill-free alternatives were considered:

| Alternative | Chosen? | Reason |
|---|---|---|
| Conservative-rate drawdown (calibrate the H0 rate from a pinned conservative rate, not from lineage fills) | No | It changes AUT-5 r7's frozen design pins, which belong to row 7 (AUT-5a). It would be a post-result redesign of another plan. It also still yields no stop with evidenced power on v2's mix. It can be raised to the row-7 owner as a separate proposal; it is not this plan's lever |
| Bounded-exposure pilot with no responsive stop (d1) | No | It has no cumulative stop after the losses that started FQ LOSS RESPONSE, which contradicts r3 §4.7. A1b (G-A) is the same bounded pilot **with** a stop that fires by construction |
| Shadow-tick rate pinning | No | It pins a take rate, not a loss distribution. The binding failure is G3 power, not rate: A1 already uses the frozen `take_rate_lower`, and E-2 set `rate_cal` = `rate_gate` = 0.25. Shadow also never feeds a verdict (PREREG v2 sequential ruling) |
| A pre-registered floor calibrated on pre-live data (A1b) | **Yes** | This is what A1 was. It needs no live fills |

## Options

| | (a) Retire on drawdown landing + entry_veto, no fills | (b′) A1b after Stage −1/0 | (c) Wait for AUT-5a/AUT-6 | (c′) Ruling: FQ v2 does not trade | (d1) Caps-only window | (d2) Restrict the mix | (r4) A1 r4 before freeze |
|---|---|---|---|---|---|---|---|
| Verdict | REJECT: the drawdown is `HALT_INERT` (F-4/F-5); the stop is MISSING (L-38) | **PRIMARY** | REJECT (L-3; F-6) | **Pre-declared terminal fallback** | REJECT (see D-14 table) | (c′) trigger T2 only: needs a new family and prereg | **REJECT (D-2).** A1 freezes as `unreachable_veto` on evidence already run. r4 would be a redesign after the result |
| Frozen PREREG edited? | No | No (a new additive A1b) | No | No | No | Yes for v2, so out of scope | No, but a post-result redesign |

**Planning figures (Gaussian approximation, not evidence).** O'Brien–Fleming-type K = 2 or 3 might reach about 0.35–0.40 at δ = −0.16 in M-yes. Pocock-type is lower; K = 4 is marginal at about 0.28 and is dropped. Stage 0 measures this; nothing assumes it.

## Architecture changes
- `F5-pin-request_r3-errata-E3.md`: NEW, filed beside E-1 and E-2 (Phase 1a).
- `F1-errata-and-deltas_r3-addendum-R8-2f.md`: NEW, doc only (Phase 1a).
- `tests/contract/test_fq_loss_stop_writer_allowlist.py`: NEW. T2–T4 in Phase 1a, T1 in Phase 1b.
- `docs/core/PROGRESS.md`: rows in FQ LOSS RESPONSE (Phases 1a, 1b, 3b).
- `docs/evidence/f5/fq_r8_2_stage_minus1_mix.md`: NEW (Stage −1).
- `scripts/analysis/fq_loss_floor_np_bound.py`: NEW, read-only, imports the MC's pure functions (Stage 0).
- `F5_prereg_v2_amendment_A1b.json`: NEW additive amendment (Phase 3a).
- `scripts/analysis/prereg_amendment_check.py`: four one-row closed-map edits plus one `_check_payload` branch (Phase 3a, step 8).
- `scripts/analysis/fq_loss_floor_mc*.py`: ADD a group-sequential/SPRT boundary family. The √t path stays byte-identical (Phase 3a).
- `docs/evidence/RULING_FQ-v2-NO-TRADE_<date>.md`: NEW (Phase 3b).
- F6c producer: under its own new plan (Phase 4).

## Implementation steps

### Phase 1a: record and veto guard (mergeable now)

1. **Contract tests T2–T4** (File: `tests/contract/test_fq_loss_stop_writer_allowlist.py`, NEW; tdd-guide; record RED→GREEN)
   - **T2 `test_artefact_writer_allowlist_is_empty_without_a_frozen_reachable_floor`.**
     - Scans `src/`, `scripts/` and `deploy/` for any writer of the `fq-loss-stop` artefact: the literal outside `loss_stop_probe.py`, a `breezy-fq-loss-stop.*` unit, or a pyproject console script.
     - The allowlist `_WRITERS` is a closed frozenset and starts **empty**.
     - The test also asserts that a non-empty `_WRITERS` is legal only if some amendment that loads through `load_verified_amendment` has a reachable floor mode.
     - So F6c widens the allowlist by one reviewed row instead of deleting the test.
     - RED: a fixture writer module in a temp tree.
   - **T3 `test_loss_stop_artefact_path_callers_in_closed_allowlist`.** An AST walk. Callers of `loss_stop_artefact_path` must be in the closed set {the probe module, the `app/trade.py` FQ composition, `tests/`}. Widening is one reviewed row, under the same frozen-reachable-floor precondition.
   - **T4 `test_missing_artefact_vetoes_with_reason_unknown`.** The L-38 positive control: a temp path with no file gives `veto_reason() == REASON_UNKNOWN` after `probe_once()`. `test_loss_stop_input_missing_refuses_after_halt_branch` (F6) stays byte-unchanged.
   - Risk: Low. The scan excludes `tests/` and `docs/`. Add T2–T4 to every focused gate (lesson: focused gates miss contract tests).

2. **Errata E-3** (File: `F5-pin-request_r3-errata-E3.md`, NEW)
   - Dependency: E-1 and E-2 are merged from worktree a1mc-1008 into the feature branch first (F-15).
   - Replacement for r3 `:222`:
     > "**`unreachable_veto`.** The producer never writes PASS and always refuses, so FQ v2 entries are vetoed for the epoch. Bridge retirement belongs to the AUT-5a row owner (the coordinator) under F1 r3 §R8-2. Under this mode §R8-2(a)/(b) cannot be met (§R8-2(f)). AUT-6 owns no loss control and no part of retirement. The FQ v2 disposition is decided by FQ-R8-2-UNDER-VETO_plan_r2. This is a goal-state blocker (r2 §4.5)."
   - For r3 `:428-429`:
     - "until AUT-6" becomes "until FQ-R8-2-UNDER-VETO_plan_r2 reaches G-A or G-B";
     - "planned through AUT-6" becomes "planned in FQ-R8-2-UNDER-VETO_plan_r2".
   - Note: `F6-F7b-F13B0-open-items_2026-10-06.md:8` (F4 labels / AUT-6 activation) was an F6b input. It lapses with F6b, and F6c must re-verify it.

3. **PROGRESS, Phase 1a rows** (File: `docs/core/PROGRESS.md`, FQ LOSS RESPONSE table)
   - Replace `:67` with:
     `| F6 bridge | veto merged; A1 gate outcome unreachable_veto (E-2; freeze pending) ⇒ permanent UNKNOWN veto on FQ v2; §R8-2 retirement unreachable (needs fills); disposition per FQ-R8-2-UNDER-VETO_plan_r2 |`
   - ADD:
     `| FQ-R8-2-UNDER-VETO | plan r2; 1a (E-3, R8-2f, writer-allowlist tests) → 1b after A1 freeze → Stage −1 mix check → Stage 0 NP screen → A1b single shot or RULING_FQ-v2-NO-TRADE |`
   - ADD note line (D-18):
     `A1 floor MC E-2 (peer rerun; binding file pending): c ≈ 2.05; M-yes G3(−0.16) = 0.2104; seed 20261008; 10k replicates ⇒ unreachable_veto.`

4. **§R8-2(f) addendum, doc only; (a)–(e) byte-unchanged** (File: `F1-errata-and-deltas_r3-addendum-R8-2f.md`, NEW; reviewed by the row-7 owner)
   > "(f) Under A1 `floor_mode: unreachable_veto`, (a) and (b) cannot be met by construction, and no v2 drawdown block can be non-inert (AUT-5 r7 `:768`, AD3 `:752`). Retirement is not an available exit. The FQ v2 disposition follows FQ-R8-2-UNDER-VETO_plan_r2. No retirement may cite a `HALT_INERT` verdict. No part of (a)–(e) is relaxed."
   - **D-17 hand-off.** `test_bridge_retirement_refused_when_drawdown_verdicts_are_halt_inert` (five `HALT_INERT` PASS days with ≥ 10 fills give a false retirement predicate) is **not built here**. It goes on the row-7 WP that owns the §R8-2 tests, as a brief input.

### Phase 1b: after A1 freezes (r3 Phase 2 step 8, including its A1 R5 branch, F-14)
- **STOP.** If the frozen A1 is `sqrt_boundary`, this plan is moot. F6b is re-planned under r3, its producer widens T2/T3 by one reviewed row each, and nothing is deleted.
- **T1 `test_a1_floor_mode_is_unreachable_veto`.** Loads A1 through `load_verified_amendment(path, "F5_prereg_v2_A1_floor")` (`prereg_amendment_check.py:358-377`) and asserts `floor_mode == "unreachable_veto"` and `c is None`.
- **PROGRESS ADD:**
  `| F6b producer | CANCELLED <date> (FQ-R8-2-UNDER-VETO_plan_r2): A1 frozen <sha> = unreachable_veto, so a producer could only refuse; the probe already vetoes on a missing artefact (loss_stop_probe.py:290-291). Guarded by tests/contract/test_fq_loss_stop_writer_allowlist.py. Any revival is F6c, scoped to a frozen reachable A1b |`
  Update the F6 bridge row to replace "freeze pending" with "A1 frozen <sha>".

### Phase 2: Stage −1 and Stage 0 (read-only)

5. **Stage −1: pin the mix** (File: `docs/evidence/f5/fq_r8_2_stage_minus1_mix.md`; the domain reviewer runs it, read-only)
   - Inputs are **only** the frozen `F5_prereg_v2_design.json` @072ab026 and the A1 r3 spec. The tape and decision logs are corroboration and never a pin.
   - M-yes may be dropped **only** if a side or price rule in the frozen design makes the YES-heavy mix unreachable. The rule must be cited by file and sha, and A1b repeats the citation.
   - Otherwise, record "no structural exclusion", and min-over-{M-pool, M-yes, M-no} stands. F-16 suggests this outcome, but Stage −1 decides it.
   - The output is committed before Stage 0 runs. The set it fixes, `MIXSET`, is used by Stage 0, A1b and step 8.

6. **Stage 0: Neyman–Pearson upper bound** (File: `scripts/analysis/fq_loss_floor_np_bound.py`, NEW; evidence `docs/evidence/f5/fq_loss_floor_np_bound_seed<S>.json`)
   - **Precondition (D-9), answered by F-12.** G3 is measured at the realised tick count N over `inclusive_days(e, 2027-01-25)`. The bound therefore uses the same H1 and H0 simulations: the same `gate_pooled`, `p_gate` thinning and day cuts (`engine.py:108-116, :292-302`).
     - Open check: re-verify those lines at the binding E-2 run's `script_git_sha`. If they differ, STOP and re-derive the horizon before running.
   - **Information set (D-4, D-8).** Ticks ≤ min(t_K, N_e), with t_K = ⌊0.8 · T_low(e_freeze)⌋. All D-16 menu candidates share t_K, so this is both "each candidate's t_K" and "the smallest t_K". The units are r3 station-day Z_d (§4.1 step 8), never legs and never calendar-day sums.
   - **Statistic.** The log-LR of each station-day's categorical outcome under H1 (δ = −0.16, the gate's `row="H1"`) against H0 (the §4.2 joint), summed over the information set.
     - Per-day masses come from the MC engine's pure functions (`prepare_day`, `engine.py:103`), imported and never retyped (L-40 amendment (ii)).
     - The critical value is the H0-replicate (1 − 0.10) quantile.
     - Thinning does not depend on the outcome (`gate.py:115-119`), so N has the same law under H0 and H1. This makes the unconditional LR test on the truncated path the NP-optimal test.
     - Open check: if H1 is not a likelihood model with computable per-day masses, STOP and refer to the peer loop.
   - **Validity (D-7).** "H0 is one element of the composite null. An α-level rule for the composite null is α-level at H0, so the LR bound at H0 is valid."
   - **Grid and replicates.** e ∈ the `epoch_grid` dates ≥ today; mixes ∈ MIXSET; ≥ 10,000 replicates; the coordinator sets the seed.
     - Before the run, write `e_proj` into the evidence file: the first grid e on or after the projected A1b + F6c + F9-B arming date.
   - **Decision node D1 (D-5, D-6).**
     - `bound_min(e)` = the minimum over MIXSET.
     - `np_reach_cutoff_e` = the latest e with `bound_min(e) ≥ 0.30`.
     - **PASS** iff `np_reach_cutoff_e` exists and is ≥ `e_proj`. Then go to Phase 3a, carrying `np_reach_cutoff_e`.
     - **Otherwise go to Phase 3b.** That includes any bound in [0.25, 0.30).
   - Run hygiene: one heavy job at a time, under a memory cap, outside 01:00–04:30Z, with the exact interpreter path and never `uv`. Arm a stall watch and a Monitor in the launch turn.

### Phase 3a: A1b single shot (only if D1 passes)

7. **A1b design and adversarial peer review** (File: `F5_prereg_v2_amendment_A1b.json` plus a design note)
   - **Reused unchanged from A1:**
     - S_t, Z_d, D1–D6, E-1 and E-2;
     - the epoch, anchor and durable FAIL latch;
     - the refusal channel (r3 §4.4);
     - the `loss_stop/v1` contract.

     The probe is not edited. Only the boundary changes.
   - **Fixed menu (D-16; nothing added after the run).**
     - (i) Lan–DeMets one-sided spending on S_t, O'Brien–Fleming-type and Pocock-type, K ∈ {2, 3}.
       - Looks at information fractions {1/2, 1} or {1/3, 2/3, 1} of I_max (D-8).
       - I(t) = Var_H0(S_t) under the pinned null, which equals the tick count on Z_d units.
       - I_max = I(t_K).
       - At the realised fractions, α is spent on the spending function.
     - (ii) A truncated one-sided SPRT on the station-day log-LR at δ_h, truncated at t_K.
   - **Terminal rule (D-3, D-12).**
     - The terminal event τ_term is the first producer run after **either** the look-K evaluation at t_K, **or** climate day `a1b_backstop_climate_day` = 2027-01-25, whichever comes first.
     - If the backstop comes first, a final look is taken at the realised information with the remaining α, and then the terminal veto follows.
     - At τ_term without a FAIL, the producer refuses with reason `test_concluded_no_reject`. The **producer** enforces this, not a reviewer.
     - Max days armed = the days from arming to the backstop. This is a design value, not an operator cap.
     - Re-arming needs a new epoch, a new ruling and a new prereg (M11).
   - **Gate:** r3 §4.6 unchanged, over MIXSET.
     - G1 with margin.
     - G3(−0.16) ≥ 2.5·α_floor (0.25 at α 0.10). **G1/G3 count only boundary FAILs strictly before τ_term. The forced terminal veto never counts (D-11).**
     - S6 acceptance.
     - Binding set {H0, S4, S5(ρ_bind)}.
     - α_floor = 0.10. Escalation is driven by G1 only.
   - **α criterion (D-10).**
     - In every binding cell, the point estimate of α is ≤ 0.10.
     - The one-sided 95 % Wilson upper limit is reported in the evidence and in A1b.
     - This replaces r1's "+3·SE".
     - Type-I is checked at the realised-count distributions at `rate_cal` (0.25), at λ_pool as a sensitivity, and in an under-rate case where the backstop arrives before t_K (D-8).
   - **Selection.** Choose the candidate that maximises the min-over-MIXSET G3(−0.16), subject to the α criterion. Ties go to the earliest first look, then to fewer looks.
   - **Confirmation (D-10).** Re-run only the selected candidate on a **fresh** coordinator seed under the same gate. FAIL → Phase 3b. No reselection. There is no A1c.
   - **Disclosure** in A1b:
     - the √t MC result was seen;
     - Stage −1 and Stage 0 evidence were seen;
     - no v2 live data exists.
   - **Precedence** is stated as a payload rule, `a1b_supersedes_rule`: "effective iff A1.floor_mode == unreachable_veto and A1b is frozen with a reachable mode". R5 checks it. The peers confirm the semantics.
   - Peers: trading-bot-architect, prediction-market-reviewer and python-reviewer. security-reviewer joins only if the latch or file semantics change.
   - Abort to Phase 3b if the projected arming date passes `np_reach_cutoff_e`.

8. **Checker, MC, run** (Files: `prereg_amendment_check.py`, `fq_loss_floor_mc*.py`, `tests/unit/test_prereg_amendment_check.py`; tdd-guide)
   - **Checker edits (D-2).** One reviewed row each (L-12). Existing rows and tests stay byte-unchanged.

     | # | Location | Edit |
     |---|---|---|
     | a | `_PAYLOADS` (`:46-50`) | ADD `"F5_prereg_v2_A1b_floor": frozenset({"loss_stop_floor_a1b"})` |
     | b | `_AMENDMENT_FILENAME` (`:51-55`) | ADD `"F5_prereg_v2_A1b_floor": "F5_prereg_v2_amendment_A1b.json"`. Update the docstrings at `:2` and `:326` to `{A0\|A1\|A1b\|A2}` |
     | c | `_EARLIER` (`:56-63`) | ADD `"F5_prereg_v2_A1b_floor": ("F5_prereg_v2_amendment_A0.json", "F5_prereg_v2_amendment_A1.json")`. Append A2's file name only if A2 is already frozen at A1b design time; this is pinned then and never left conditional at runtime |
     | d | `_EARLIER["F5_prereg_v2_A2_guard"]` (`:59-62`) | Append `"F5_prereg_v2_amendment_A1b.json"`. **This lands in the same commit that adds the A1b file.** Earlier, A2's `load_verified_amendment` would refuse with `EARLIER_AMENDMENT_MISSING` (`:205-211`) and break the r3 §5.4 6b registration load. Under G-B this edit never lands |
     | e | `_check_payload` (`:311-322`) | ADD an A1b branch, `_check_floor_a1b`, before the placeholder branch. It checks: the exact key set; `a1b_boundary_family` in the closed menu set; `a1b_K` ∈ {2, 3}; `a1b_backstop_climate_day` ≤ 2027-01-25; a terminal rule present; G3 ≥ 2.5·α_floor; α point ≤ α_floor; the `a1b_supersedes_rule` text; `PENDING_*` refused |

   - **Every A1b child key is `a1b_`-prefixed,** so none collides with A1's `loss_stop_floor` children (r3 `:252-282`). `_check_additive` enforces this through edit (c).
   - **Tests (ADD):**
     - `test_a1b_keys_disjoint_from_a1_keys` (a planted overlap gives `KEY_OVERLAP`)
     - `test_a2_earlier_includes_a1b_only_with_a1b_file`
     - `test_a1b_filename_enforced`
     - `test_a1b_floor_mode_in_closed_set`
     - `test_a1b_terminal_and_backstop_present`
     - `test_a1b_g3_floor_enforced_every_mix`
     - `test_forced_terminal_veto_excluded_from_g1_g3` (D-11)
     - `test_sqrt_boundary_path_byte_identical` (the A1 cells reproduce the binding E-2 file at its seed)
     - `test_group_sequential_type_i_at_realised_counts` (rate_cal, λ_pool, under-rate)
     - `test_np_bound_upper_bounds_every_candidate_power`
   - **Gate:**
     - run `scripts/ci/run_tests_no_egress.sh` in full after every merge, and read EXIT before any push;
     - run `lint-imports` from the tree root and require "N kept, 0 broken";
     - put the firewall and exec-import pins in every focused gate.
   - **Node D2:** A1b freezes reachable, with the confirmation run passing → Phase 4. Anything else → Phase 3b.

### Phase 3b: (c′) no-trade ruling (if D1 or D2 fails, or step 7 aborts)

9. **RULING_FQ-v2-NO-TRADE_<date>** (File: `docs/evidence/RULING_FQ-v2-NO-TRADE_<date>.md`; a coordinator ruling, peer-reviewed, not escalated)
   - It cites F-2 to F-5, F-7, F-9, F-12, Stage −1, Stage 0 and any A1b evidence.
   - It rules that FQ v2 does not trade. F9-A and F9-B are not executed for v2 as a sender. F6 stays. No cap is assigned or named.
   - **Re-open triggers** (each starts a new plan; none is automatic):
     - T1: a CONFIRM edge from a pre-registered read (M1-v3 at or after 12-07, or AUT-4);
     - T2: a new family with its own prereg whose floor passes the §4.6 gate for its mix (this covers d2);
     - T3: a new US weather source that changes the take rate in a pre-registered way (F13).
   - **Review date (D-13):** the earlier of 2027-01-25 and the start of the next F5 epoch. On that date, the coordinator re-reads the triggers and records whether the ruling stands.
   - PROGRESS: set FQ-R8-2-UNDER-VETO to `DONE <sha>: G-B` and the F6 bridge to `permanent veto by RULING_FQ-v2-NO-TRADE`.

10. **Row-7 WP10 impact** (verify first; AUT-5a row owner)
    - Read-only checks:
      - (i) Do the WP10 stage S, L1 and L2 criteria need orders actually sent, or only a registry-resolved sender equal to the env sender (`F1 r3:686-693`)?
      - (ii) Does the F6 composed veto also refuse drill-child entries (`<champion>_r0001`)?
    - **Under G-B, any L1 proof is a zero-fill proof (D-15).** It proves wiring and veto behaviour, never live loss behaviour, and it must say so.
    - If WP10 cannot complete, mark row 7 and every row whose Needs chain reaches it (8 through 12) as GATED by RULING_FQ-v2-NO-TRADE, with the same triggers.

### Phase 4: G-A bounded pilot (only if A1b freezes reachable)

11. **F6c producer plan** (NEW plan; planner, then peer review, then TDD)
    - **Scope:**
      - r3 §4.4 and §4.8 inputs: epoch, latch and refusal channel;
      - the G2 positive control, with boundary = A1b;
      - the terminal `test_concluded_no_reject` refusal at τ_term;
      - `test_terminal_veto_fires_at_calendar_backstop_with_ticks_below_t_K`, using an injected clock (D-3);
      - the F6b brief items from `F6-F7b-F13B0-open-items_2026-10-06.md:9-18`;
      - a re-verified F4-labels input.
    - **Contract tests are widened, never deleted.** F6c's reviewed commit adds one row to `_WRITERS` (T2) and one to the T3 caller allowlist, citing the A1b freeze sha.
    - **The arming record states:**
      - "FQ v2 under A1b is a bounded pilot of ≤ t_K ticks and ≤ climate day 2027-01-25. Loss is bounded by the operator-reserved exposure controls, not by the test."
      - Worst case = daily budget × days armed. No value is assigned.
    - **After t_K or the backstop:** a terminal veto. There is no bridge retirement by PASS, and any re-test is a new prereg (D-12). The F9 sequence (`F1 r3 §R8-4`) and §R8-2 stay unchanged.

## Placement relative to the AUTONOMY QUEUE
- **Row 6 (AUT-6).** No dependency in either direction (F-6). E-3 removes the false link.
- **Row 7 (AUT-5a).** It owns §R8-2 retirement, the drawdown producer, `app/trade.py`, and the deferred test (D-17).
  - This plan edits no row-7 code. Its only row-7 touches are the §R8-2(f) doc (reviewed by the row-7 owner) and the step-10 coupling.
  - F6c adds analysis and systemd files only, so the RC-7/WP5 ordering is unaffected.
- This plan sits in FQ LOSS RESPONSE and is not a queue row.

## Testing strategy
- **Contract:** T1–T4 with recorded RED→GREEN, T4 being the positive control. They are in every focused gate.
- **Checker and MC:** the step-8 list. The √t path stays byte-identical. Every existing `test_prereg_amendment_check.py` assertion stays byte-unchanged.
- **Regression:** F6's tests stay byte-unchanged (`test_loss_stop_input_missing_refuses_after_halt_branch`, `test_composed_veto_*`, `test_f6_trade_py_changes_only_compose_fq`).
- **Full gate** after every merge, with EXIT read before any push. `lint-imports` must show "N kept, 0 broken".
- **Evidence:** the Stage −1 doc, plus Stage 0 and A1b JSONs carrying the script sha, parent sha, A0 sha, A1 sha, seed and `e_proj`. Domain review signs off before D1 and D2 are acted on.

## Risks and mitigations
- **The binding E-2 file or the A1 freeze overturns `unreachable_veto`.** Phase 1b STOP. F6b widens the allowlists, and nothing is deleted.
- **A1b is a forking path.** A fixed menu, a pre-stated selection rule, α as a point estimate ≤ 0.10, a fresh-seed confirmation, the unchanged §4.6 gate, disclosure in A1b, and no live data.
- **The realised rate is below `rate_cal`.** The calendar backstop guarantees the terminal veto (D-3). Type-I is checked in the under-rate case.
- **The reach cutoff erodes as the calendar slips.** `np_reach_cutoff_e` aborts to Phase 3b.
- **The A2 `_EARLIER` edit lands early and breaks A2 loading.** It lands only in the commit that adds the A1b file. A test pins this.
- **The terminal veto inflates power.** It is excluded from G1/G3 by rule and by test.
- **G-B blocks the row-7 live proof.** Step 10 verifies first, states the zero-fill proof explicitly, and marks GATED rows.
- **Option (a) creeps back.** The §R8-2(f) text plus the row-7-owned `HALT_INERT` test (D-17).

## Success criteria
- [ ] Phase 1a merged: E-3, §R8-2(f), T2–T4 green with RED→GREEN, the PROGRESS rows and the D-18 note.
- [ ] Phase 1b: A1 frozen `unreachable_veto`, T1 green, F6b CANCELLED row present. No frozen file edited.
- [ ] Stage −1 output committed before Stage 0. Stage 0 evidence domain-reviewed and D1 recorded at the 0.30 bar.
- [ ] Exactly one holds:
  - A1b frozen reachable, confirmation run passed, F6c plan READY, bounded-pilot statement in the arming record; or
  - RULING_FQ-v2-NO-TRADE filed with triggers, review date and row-7 impact recorded.
- [ ] No operator cap assigned or named. `allow_short` False. No safety, settlement, contract or firewall test weakened or deleted. Every closed set widened by one reviewed row only.

---

## Merge-record items applied with interpretation (planner notes)

1. **D-11, "strictly before t_K".** Taken literally, this would discard real boundary rejections at look K, which sits at t_K, and the K-th look would be pointless. Applied as "strictly before τ_term". τ_term is the terminal event that follows the look-K evaluation (or the backstop). Look-K rejections count, and the forced veto never counts. The convergence check should confirm this reading.
2. **D-8, "daily Z_d units".** Applied as r3's station-day Z_d (§4.1 step 8). r3 D4 rejected a calendar-day tick, and the merge record does not re-open that. Information is defined as the null variance of S_t, so the S5 correlation enters through Type-I checks, not through the information clock.
3. **D-2, A2 `_EARLIER` gains A1b.** Applied, with a timing constraint the merge record did not state. It must land in the same commit as the A1b file, because otherwise A2's loader refuses (`prereg_amendment_check.py:205-211`). A1b's own `_EARLIER` includes A2 only if A2 is frozen first; this is pinned at design time.
4. **D-3, "max days armed".** Pinned as the days from arming to the 2027-01-25 backstop, a design value. Choosing an earlier backstop would be a post-result option, so none is offered.
5. **D-9.** Answered from code (F-12), but from the worktree a1mc-1008 HEAD, not from a committed binding run. Re-verifying at the binding run's `script_git_sha` stays as an open Stage 0 check.
6. **D-18.** The figures come from the domain peer's rerun (E-2 text; `cal025_full.json` is not in the repo). The PROGRESS note labels them "binding file pending" rather than citing a committed evidence file.
7. **The r1 "open ruling" on the additive rule** is not carried as a blocking item. D-2's mechanical edits settle the additive question. Only the precedence semantics (`a1b_supersedes_rule`) remain as a peer-confirmation item.

---

## r2.1 — convergence amendments (binding; override the text above where they conflict)

Both convergence checks were run blind on 2026-10-08. Architecture: NOT-CONVERGED with 4 text fixes. Domain: NOT-CONVERGED with 4 MED and 2 LOW text fixes. Neither found a redesign-level defect, and both accept planner notes 1–7 (note 1 with the sharper wording in C-8). Every fix is applied here.

| # | Src | Fix (binding) |
|---|---|---|
| C-1 | arch | **Step 8(e): the key set depends on the family.** For the OBF and Pocock families, `a1b_K` is required and must be in {2, 3}. For the truncated SPRT, `a1b_K` must be **absent** and `a1b_sprt_delta_h` is required. The branch receives `draft=` so it can decide `PENDING_*`. Add one test per family. |
| C-2 | arch | **One reachability predicate.** Add a reviewed pure function to the checker, `reachable_floor(plan_dir) -> bool`. It is True only if A1 loads frozen with a reachable `floor_mode`, or if A1 is `unreachable_veto` and A1b loads frozen with a reachable family under `a1b_supersedes_rule`. Any `Refusal`, absent file, draft or load error → False. T2 and F6c both call this function, and neither one re-derives the rule. |
| C-3 | arch | **T2 rows bind a freeze.** Each `_WRITERS` row is `(path, amendment_id, frozen_sha)`. T2 hard-codes the amendment paths and asserts that `frozen_sha` equals the loaded amendment's. T3's widening precondition applies only to **new** callers. The existing `app/trade.py` FQ composition is grandfathered by name. Add a test that `_EARLIER["F5_prereg_v2_A2_guard"]` does not name A1b while the A1b file is absent. |
| C-4 | arch | **D-13 fails closed.** If the review date passes with no recorded review, RULING_FQ-v2-NO-TRADE stays in force. **D-17 is tracked.** Step 3 adds the PROGRESS line `row-7 WP input: test_bridge_retirement_refused_when_drawdown_verdicts_are_halt_inert (handed off by FQ-R8-2-UNDER-VETO r2 D-17)`. |
| C-5 | domain | **Stage 0 (closes the "is H1 a likelihood?" open check).** H1 is a likelihood model: `_h1_masses` in `fq_loss_floor_mc_draw.py` gives categorical per-day masses. Thinning is outcome-independent (`fq_loss_floor_mc_sim.py:91`), so the LR on (N, path) reduces to the conditional LR given N, and the NP claim holds. The LR uses the engine's **actual** law, which includes the Bernoulli fallback where H1 masses are `None` (`h1_fallback_uses`). An H0 mass of 0 against a positive H1 mass gives LR = ∞, which counts as reject. The critical value comes from **independent** H0 replicates. Ties make the bound slightly conservative, and the bound says so. |
| C-6 | domain | **Information.** I(t) = Σ_k Var_H0(z_k \| past). Stage 0 asserts, on every prepared day under the H0 production masses with carry and shift (`step_clock`), that Σm·z = 0 and Σm·z² = 1. Only if that assertion passes does I(t) equal the tick count. If it fails, the information fraction uses the computed conditional-variance sum. The identity is not claimed under S4/S5. |
| C-7 | domain | **Scale and S5.** Every A1b candidate carries a scale solved on the binding-max cell, as A1 solved `c`. The α criterion is applied at that scale. Stage 0 reports the NP bound both at α 0.10 and at the effective H0-cell α implied by the binding-max scale (≤ 0.10). **D1 uses the effective-α bound.** |
| C-8 | domain | **The terminal veto and look K.** A rejection at look K, or at the backstop's final look, is a real boundary FAIL and counts in G1, G3 and α. The forced terminal veto is defined as *a refusal issued at τ_term with no rejection*, and it never counts. Replace "strictly before τ_term" with that wording. The test must cover a final-look rejection that is counted. |
| C-9 | domain | **t_K is per epoch.** t_K(e) = ⌊0.8·T_low(e)⌋, the same epoch indexing G1 uses. The look fractions are information fractions of I(t_K(e)). Stage 0's information set is ticks ≤ min(t_K(e), N_e). |
| C-10 | domain | **The SPRT δ_h is pinned before any run:** δ_h = −0.16, the r3 §4.6 G3 design alternative, recorded in the menu now. It is not tunable after Stage 0. |
| C-11 | domain | **F-12 and step 6 anchors (worktree a1mc-1008):** `_criticals` `engine.py:111-119`; `crit` `engine.py:270-276`; `power` `engine.py:278-279`; thinning `sim.py:91`, fed by `p_gate` at `engine.py:254-267`; T_low `gate.py:136-142`; `rate_cal` `gate.py:115-119`. These replace the anchors above. Re-verify them at the binding run's `script_git_sha`. |
| C-12 | domain | **D-14, shadow-tick row.** Change the reason to: `take_rate_lower` is frozen in the prereg; shadow never feeds a verdict; changing the rate after the result is a gate change. (G3 depends on realised N, so the rate does matter.) |
| C-13 | domain | **Stage −1.** "YES-heavy" means the `apply_mix` definition of M-yes in the floor MC. "Structurally unreachable" means a frozen design rule under which no admissible take set reproduces M-yes's side shares. |

**Status:** CONVERGED by coordinator merge. Every remaining defect was a text fix, and each is applied verbatim above. Neither reviewer raised a design-level objection, so no third round is required (§2 peer loop: converge to high confidence). The plan is **READY** for Phase 1a. Phase 1b waits for the A1 freeze.
