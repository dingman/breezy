# Implementation Plan: FQ-R8-2-UNDER-VETO_plan_r1

<!-- planner, 2026-10-08. Plan only; no MC was run for this document and nothing here is evidence. Operator-reserved controls are named only by description (L-39) and are never assigned. No frozen PREREG (F5_prereg_v2_design.json @072ab026, A0 @43cc3e0f, A1 once frozen) is edited. allow_short stays False. No safety, settlement or contract test is weakened or deleted, except the Phase-1 contract test this plan creates, which may later be retired only by the reviewed commit named in Phase 4. -->

## Overview
The F5 A1 loss-stop floor is landing as `floor_mode: unreachable_veto`. Per E-2 (seed 20261008, 10k replicates), G3(−0.16) in M-yes is 0.210, below 2.5 × 0.10 = 0.25. The binding rerun file is pending. Under that mode the F6 probe reads UNKNOWN and vetoes every FQ v2 entry. The only exit, the §R8-2 retirement, needs live fills that the veto prevents. So FQ v2 can never trade, and the documents point at the wrong owner (AUT-6).

This plan breaks the deadlock with a decision tree that ends in exactly one of two goal states:
- **G-A.** FQ v2 trades under a pre-registered loss stop that is guaranteed to fire. It either FAILs at a look or forces a veto when the test ends.
- **G-B.** A filed, evidence-cited ruling that FQ v2 does not trade, with named re-open triggers.

There is no third, open-ended state.

## Requirements
- R1. Reach G-A or G-B, with a bounded number of steps and no open-ended "until X" (L-3).
- R2. Any stop cited as active must be able to fire, shown by a positive control. A stop that cannot fire is reported as MISSING (L-38).
- R3. No frozen PREREG is edited. Every new statistical design gets its own additive amendment and its own Monte Carlo before any v2 fill.
- R4. Operator-reserved controls (the daily budget cap and the per-position cap) are never assigned, derived from or named by env-var name.
- R5. Nautilus is untouched. The F6 probe (`loss_stop_probe.py`) and its RC-7 composition in `app/trade.py` are not edited.
- R6. F6b is cancelled, with an exact PROGRESS row and a contract test.
- R7. The text attributing bridge retirement to AUT-6 is corrected.
- R8. The plan states where it sits relative to AUTONOMY QUEUE rows 6 (AUT-6) and 7 (AUT-5a).

## Facts this plan rests on (all read 2026-10-08)
| # | Fact | Source |
|---|---|---|
| F-1 | Missing artefact → UNKNOWN → immediate `REASON_UNKNOWN` veto (no 26/36 h window) | `src/breezy/strategy/forecast_quantile_ladder/loss_stop_probe.py:286-291, :327-332`; path `:118-119` |
| F-2 | Under `unreachable_veto`, the producer never writes PASS | `F5-pin-request_r3.md:71, :208, :217, :222` |
| F-3 | §R8-2 retirement needs (a) N=5 consecutive EVALUATED PASS days with `drawdown_control_active`, (b) ≥ 10 live fills, (c) a fresh producer verdict, (d) a hand commit, (e) the H1 pre-flight. Nothing auto-retires | `F1-errata-and-deltas_r3.md:618-634` |
| F-4 | The drawdown H0 rate is measured from the lineage's real-money fills. Fewer than 14 complete days or fewer than 30 fills → `halt_inert=true`, `rate_undersampled` | `AUT-5-promotion-demotion_plan_r7.md:766-768` |
| F-5 | `HALT_INERT` is never control evidence; `drawdown_control_active` is false for it | `AUT-5 r7:752-753` |
| F-6 | AUT-6 r15 has no drawdown or loss detector; it owns drift and health only | `AUT-6-drift-health_plan_r15.md` (no `drawdown`/loss detector rows); README `:155-172` |
| F-7 | KILL cannot fire before 2027-01-25 (about 24 takes, first look at 20) | `F5-pin-request_r1-review-merge.md:106` |
| F-8 | Pre-January loss controls are only the F6 floor and the two caps. Every arming record states worst case = daily budget × days armed | `F5-pin-request_r1-review-merge.md:107` |
| F-9 | E-2 numbers: c ≈ 2.05; G1 passes in every cell; G3(−0.16) = 0.579 for M-pool, 0.434 for M-no, 0.210 for M-yes. Escalating on G3 is forbidden | `F5-pin-request_r3-errata-E2.md:12-16` (worktree a1mc-1008); `F5-pin-request_r3.md:209` |
| F-10 | Row-7 WP10 (stage S, L1, L2) waits behind F8, F6, the resume bar and RC-5, and so behind F9-B | `F1-errata-and-deltas_r3.md:681-684`; `PROGRESS.md:71` |
| F-11 | The misattribution "until AUT-6 retires the bridge" | `F5-pin-request_r3.md:222`, `:428-429` |

**Derived (the deadlock, made explicit).** F-2 → zero v2 fills. Then:
- F-3(b) is unreachable;
- F-4 makes the v2 drawdown block inert;
- F-5 then makes F-3(a) unreachable as well.

So the bridge cannot retire under any reading, and no control from AUT-5a or AUT-6 can be calibrated without v2 fills. Any route to G-A needs a loss stop calibrated from pre-live data, which is what A1 was.

## Options evaluated

| | (a) Retire on drawdown producer landing plus entry_veto, no fill requirement | (b′) A1b: an amended floor statistic, single shot, after a power kill-screen | (c) Do not trade "until AUT-5a/AUT-6 provide another control" | (c′) Explicit ruling: FQ v2 does not trade | (d1) Trade on the caps alone for a bounded calibration window | (d2) Restrict v2's mix (for example NO-heavy, where G3 passes) |
|---|---|---|---|---|---|---|
| **Unblocks** | FQ v2 entries right away | G-A, if the screen and MC pass. Fills follow, which in turn let AUT-5a's drawdown calibrate and §R8-2 become reachable later | Nothing. AUT-6 has no loss control (F-6); AUT-5a's needs v2 fills (F-4) | G-B now. Unblocks planning: rows depending on FQ v2 get a definite status | FQ v2 entries, plus the fills the drawdown H0 needs | Possibly G-A for a different trade population |
| **Risk** | **Unacceptable.** The drawdown is `HALT_INERT` with zero fills (F-4), and retiring on it violates AD3 (F-5). The family trades with no cumulative stop under a "controlled" label, so the stop is MISSING (L-38) | Medium. A forking path (the √t result is known), mitigated by a pre-stated finite menu, one run and an unchanged gate. The reach cutoff shrinks with every week of delay | Not a plan (L-3): it never reaches a goal state | Low for capital. Cost: the FQ v2 opportunity, and a possible block on row-7 WP10 (Phase 3b) | High. No responsive cumulative stop for ≥ 14 days, after the very losses that started the FQ LOSS RESPONSE. No evidenced edge (F5 MC STARVED; PROGRESS `:66`). Contradicts r3 §4.7, "a dead stop is not acceptable" | High. It changes the family's trade population, which the frozen v2 PREREG describes. It needs a new family and a new prereg |
| **Changes a frozen PREREG?** | No, but it bypasses A1's outcome | No: a new additive amendment `F5_prereg_v2_amendment_A1b.json`. A1, A0 and the parent stay as they are | No | No | No, but it overrides A1's outcome by ruling | Yes for v2. Admissible only as a new family (v3) with its own prereg, so it is out of scope here |
| **Operator controls involved** | Both caps become the only loss control | None assigned. The arming record states worst case = daily budget × days armed (F-8); the stop forces a veto at its last look | None | None | Both caps become the only control. The worst-case statement covers ≥ 14 days | None here |
| **Effort** | Small (doc plus one commit), but rejected | About 0.5 day (screen) + 3–5 days (A1b design, checker, MC, peer review, freeze) + 5–8 days (F6c producer) | 0 | About 0.5 day (ruling plus PROGRESS) | About 1 day of rulings, plus the risk | Weeks (new family, prereg, MC, shadow) |
| **Verdict** | REJECT | **RECOMMENDED (primary path)** | REJECT as worded; replaced by (c′) | **RECOMMENDED terminal fallback** (pre-declared) | REJECT now. Re-open only through the (c′) triggers | Listed as a (c′) re-open trigger, not built here |

**Recommendation: (b′), with (c′) as its pre-declared terminal fallback.** It is the only option that can reach G-A while satisfying L-38, R3 and AD3, and the fallback guarantees a goal state if (b′) fails. Phase 1 is independent of both and lands now.

**Why (b′) has a real chance (planning arithmetic, not evidence).**
- The √t boundary pays for continuous monitoring with c ≈ 2.05.
- A test that looks only a few times needs critical values much closer to the fixed-sample 1.28 at α = 0.10.
- Back-solving the E-2 result (G3 = 0.21 at c = 2.05) suggests that a fixed-sample test at the same tick count could roughly double power in M-yes.
- Stage 0 measures this before anything is designed. It never assumes it.

## Architecture changes
- `docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04/F5-pin-request_r3-errata-E3.md` — NEW. Corrects F-11.
- `docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04/F1-errata-and-deltas_r3-addendum-R8-2f.md` — NEW, or appended per the area's errata convention. Adds §R8-2(f); (a)–(e) are byte-unchanged.
- `tests/contract/test_fq_loss_stop_no_writer_under_unreachable_veto.py` — NEW. Replaces F6b.
- `tests/unit/test_drawdown_producer.py` — ADD one test (AUT-5a-owned file, row-7 owner reviews).
- `docs/core/PROGRESS.md` — rows in FQ LOSS RESPONSE; a note at AUTONOMY QUEUE row 7.
- (Phase 2) `scripts/analysis/fq_loss_floor_np_bound.py` — NEW, read-only analysis. Imports the floor MC's production pure functions (L-40 amendment (ii)); never retypes them.
- (Phase 3a) `docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04/F5_prereg_v2_amendment_A1b.json` — NEW additive amendment.
- (Phase 3a) `scripts/analysis/prereg_amendment_check.py` — extend the R5-style rule set for A1b keys (ADD rules only).
- (Phase 3a) `scripts/analysis/fq_loss_floor_mc.py` — ADD a boundary-family parameter. The √t path stays byte-identical, pinned by a test.
- (Phase 3b) `docs/evidence/RULING_FQ-v2-NO-TRADE_<date>.md` — NEW, coordinator ruling.
- (Phase 4, conditional) The F6c producer, under its own new plan.

## Implementation steps

### Phase 1 — Clear the record and guard the veto (independent; merge now)

1. **Freeze A1 per r3 as soon as the E-2 binding rerun lands** (File: per the r3 §6 Phase 2 freeze step; existing work)
   - Action: freeze A1 exactly as the gate dictates (`unreachable_veto`, `c: null`, `power_class: "none"`), with the E-2 rerun as the binding evidence. Nothing in this plan alters it.
   - Why: A1b (Phase 3a) is defined relative to a frozen A1, and the contract test reads it.
   - Dependencies: the E-2 rerun file `docs/evidence/f5/fq_loss_floor_mc_seed20261008.json` (not yet on disk; only `…_run1_pre_E2.json` exists).
   - Risk: Low.
   - STOP: if the rerun does NOT give `unreachable_veto` (for example, G3(M-yes) ≥ 0.25 after all), this plan is moot. F6b is then re-planned under r3 as written, and steps 2–3 are withdrawn before merge.

2. **Cancel F6b and replace it with a contract test** (File: `tests/contract/test_fq_loss_stop_no_writer_under_unreachable_veto.py`, NEW)
   - Action: ADD these tests (RED first where a RED is constructible; record RED→GREEN):
     - `test_a1_floor_mode_is_unreachable_veto`. Loads A1 through `load_verified_amendment` (`scripts/analysis/prereg_amendment_check.py:358-377`). Asserts `floor_mode == "unreachable_veto"` and `c is None`. This is the test's precondition, read from the frozen file and never hard-coded.
     - `test_no_module_writes_fq_loss_stop_artefact`. Scans `src/`, `scripts/` and `deploy/`. The literal `fq-loss-stop` appears only in `loss_stop_probe.py` (the reader, `:119`). `src/breezy/analysis/fq_loss_stop.py` does not exist. No `deploy/systemd/breezy-fq-loss-stop.*` unit exists. `pyproject.toml` declares no fq-loss-stop console script.
     - `test_loss_stop_artefact_path_has_only_reader_callers`. An AST walk: every call of `loss_stop_artefact_path` is in the probe module, the `app/trade.py` FQ composition, or `tests/`.
     - `test_missing_artefact_vetoes_with_reason_unknown`. Positive control (L-38): a probe built on a temp path with no file gives `veto_reason() == REASON_UNKNOWN` after `probe_once()`. This complements, and does not replace, `test_loss_stop_input_missing_refuses_after_halt_branch` (F6, byte-unchanged).
   - Why: the probe already vetoes on a missing file (F-1), and under F-2 any F6b producer would only ever take the refusal path. The test turns "nothing writes PASS" from an assumption into a guard.
   - Dependencies: step 1.
   - Risk: Low. The scan must exclude `tests/` and the docs tree, so that the plan files do not trip it. Include it in every focused gate (lesson: focused gates miss contract tests).

3. **PROGRESS row for F6b** (File: `docs/core/PROGRESS.md`, FQ LOSS RESPONSE table, inserted after the `F6 bridge` row)
   - Exact row:
     `| F6b producer | CANCELLED 2026-10-08 (FQ-R8-2-UNDER-VETO_plan_r1): A1 = unreachable_veto, so a producer could only refuse; the probe already vetoes on a missing artefact (loss_stop_probe.py:290-291). Replaced by tests/contract/test_fq_loss_stop_no_writer_under_unreachable_veto.py. Any revival is F6c, scoped to a frozen reachable A1b only |`
   - Replace the `F6 bridge` row with:
     `| F6 bridge | veto merged; A1 unreachable_veto ⇒ permanent UNKNOWN veto on FQ v2; §R8-2 retirement unreachable (needs fills); disposition per FQ-R8-2-UNDER-VETO_plan_r1 (A1b screen → A1b or RULING no-trade) |`
   - ADD row:
     `| FQ-R8-2-UNDER-VETO | plan r1; Phase 1 (E-3, R8-2f, F6b cancel) → Stage 0 NP screen → A1b single shot or RULING_FQ-v2-NO-TRADE |`
   - Dependencies: step 2 merged in the same commit or earlier.
   - Risk: Low.

4. **Errata E-3: correct the AUT-6 misattribution** (File: `F5-pin-request_r3-errata-E3.md`, NEW, beside E-1 and E-2)
   - Action. Replacement text for `F5-pin-request_r3.md:222`:
     > "**`unreachable_veto`.** The producer never writes PASS and always takes the refusal path, so FQ v2 entries are vetoed for the whole epoch. Retiring the bridge is owned by the AUT-5a row owner (the coordinator) under F1-errata-and-deltas_r3 §R8-2. Under this mode, §R8-2(a) and (b) cannot be met because the veto admits no fills, so the bridge does not retire (§R8-2(f)). AUT-6 (drift and health) owns no loss control and no part of the retirement. The disposition of FQ v2 is decided by FQ-R8-2-UNDER-VETO_plan_r1. This is reported as a goal-state blocker (r2 §4.5)."
   - For `:428-429` (risk row), replace "until AUT-6" with "until FQ-R8-2-UNDER-VETO_plan_r1 reaches G-A (A1b) or G-B (no-trade ruling)". Replace "the trading path is planned through AUT-6" with "the trading path is planned in FQ-R8-2-UNDER-VETO_plan_r1".
   - Also note that `F6-F7b-F13B0-open-items_2026-10-06.md:8` ("F4 labels running (AUT-6 activation)") was an F6b input dependency. It lapses with F6b, and F6c must re-verify it.
   - Why: R7. The errata pattern keeps r3 auditable. r3 is a plan, not a PREREG, but in-place edits would break the E-1/E-2 chain.
   - Risk: Low.

5. **§R8-2(f) addendum; (a)–(e) byte-unchanged** (File: the F1 r3 errata or delta, AUT-5 r8 delta lineage)
   - Text:
     > "(f) **Under A1 `floor_mode: unreachable_veto`**, (a) and (b) are unreachable by construction, because the veto admits no fills. No v2 drawdown block can be non-inert either (AUT-5 r7 `:768`, AD3 `:752`). Retirement is therefore not an available exit. The bridge stays the FQ v2 entry veto for the epoch, and the FQ v2 disposition follows FQ-R8-2-UNDER-VETO_plan_r1. No retirement may cite a `HALT_INERT` verdict. No criterion in (a)–(e) is relaxed, and N and the minimum fill count stay design values, not caps."
   - Test (ADD, AUT-5a-owned file): `tests/unit/test_drawdown_producer.py::test_bridge_retirement_refused_when_drawdown_verdicts_are_halt_inert`. Five consecutive `HALT_INERT` PASS days with ≥ 10 fills means the retirement predicate is false.
   - Why: pins the F-4/F-5 linkage, so that option (a) cannot be re-introduced silently.
   - Dependencies: none (doc). The test lands with the other §R8-2 tests in the row-7 WP that owns them.
   - Risk: Low.

### Phase 2 — Stage 0: the power kill-screen for (b′) (read-only; about 0.5 day)

6. **Neyman–Pearson upper bound on achievable power** (File: `scripts/analysis/fq_loss_floor_np_bound.py`, NEW; evidence `docs/evidence/f5/fq_loss_floor_np_bound_seed<S>.json`)
   - Action. Using the E-2 binding MC's templates, mixes (M-pool, M-yes, M-no), the E-1 residual-mass joint, the D1 netting shift and the E-2 rates (`rate_cal = rate_gate = take_rate_lower` 0.25), all imported and never retyped:
     - compute, per mix and per e in {A1 freeze date, 2026-11-01, 2026-11-15, 2026-12-01}, the power of the fixed-sample likelihood-ratio test of H0 (the §4.2 null, H0 row) against H1 (δ = −0.16, as defined in r2/r3 G3) at n = T_low(e) ticks, at α_floor = 0.10;
     - ≥ 10,000 replicates, with a coordinator-set seed and run hygiene as in r3 §4.5.
   - Why: by the NP lemma, no α-level test that uses only ticks ≤ T_low(e), sequential or not, can beat this bound. It is evaluated on the H0 row only, because S4/S5 only lower achievable power. So "bound < floor" kills (b′) on evidence, while "bound ≥ floor" is necessary but not sufficient.
   - Decision node D1 (pre-stated):
     - If the bound in M-yes is < 0.25 at every e ≥ the projected A1b + F6c + F9-B date (the projection is written into the evidence file before the run), go to **Phase 3b**.
     - Otherwise, go to **Phase 3a**, carrying `np_reach_cutoff_e` = the latest e at which the bound is ≥ 0.25 in every mix.
   - Dependencies: step 1 (binding E-2 evidence).
   - Risk: Low. Run it under a memory cap as a single heavy job, outside 01:00–04:30Z, never through `uv`, with the exact interpreter path.

### Phase 3a — A1b: one pre-registered alternative floor (only if D1 passes)

7. **A1b design (planner) and adversarial peer review** (File: `F5_prereg_v2_amendment_A1b.json` plus a design note)
   - Pinned invariants. Everything below is reused from A1 unchanged:
     - S_t, Z_d, ticks, D1–D6, E-1, E-2;
     - the epoch, anchor and durable FAIL latch;
     - the refusal channel (r3 §4.4);
     - the `loss_stop/v1` artefact contract.
     The probe is not edited. Only the boundary changes.
   - Pre-declared finite menu (no additions after the run):
     - (i) group-sequential one-sided boundaries on S_t with K ∈ {2, 3, 4} looks at fixed tick counts, equally spaced up to t_K = ⌊0.8·T_low(e_freeze)⌋, with α spent by O'Brien–Fleming-type and by Pocock-type spending;
     - (ii) a truncated one-sided SPRT on the per-tick log-LR at δ_h, truncated at t_K;
     - (iii) the A1 √t boundary, as a reference row only.
   - **Terminal rule (L-38 by construction).** If no FAIL has occurred by look K, the producer takes the refusal path with reason `test_concluded_no_reject`, so FQ v2 is vetoed after t_K. Re-arming needs a new epoch and a new ruling (existing M11 rule). The stop therefore always fires: either as FAIL at a look, or as the concluded veto.
   - Gate: r3 §4.6 unchanged. G1 (with margin) per e; **G3(−0.16) ≥ 2.5·α_floor in every mix including M-yes**; S6 acceptance; binding set {H0, S4, S5(ρ_bind)} × mixes; α_floor = 0.10 first and escalation driven by G1 only, as in r3.
   - Selection rule: the candidate that maximises min-over-mixes G3(−0.16), subject to α ≤ α_floor + 3·SE in every binding cell. Ties go to the earliest first look, then to fewer looks.
   - Type-I: the looks are at fixed tick counts, so Type-I does not depend on rate in principle. It is still verified at `rate_cal` (0.25) and as a sensitivity at λ_pool.
   - Single shot: one seed and one run. If no candidate passes, go to **Phase 3b**. There is no A1c.
   - **Open ruling for the peer loop (blocking).** Does "A1b effective iff A1.floor_mode == unreachable_veto and A1b is frozen with a reachable mode" satisfy the amendment envelope's additive and overlap rule (`prereg_amendment_check.py`), given that no A1 key is re-keyed? If the reviewers rule no, go to **Phase 3b**.
   - Forking-path disclosure: written into A1b. The only information seen is the √t MC result on the synthetic pool. No v2 live data exists, and the gate is unchanged.
   - Peers: trading-bot-architect, prediction-market-reviewer (domain math), python-reviewer (checker and MC code). security-reviewer joins only if F6c's file and latch semantics change (they should not).
   - Dependencies: D1 passed.
   - Risk: Medium. The calendar is the main risk: freeze slippage shrinks T_low. Abort to 3b if the projected arming date passes `np_reach_cutoff_e`.

8. **Checker and MC extension, then the run** (Files: `prereg_amendment_check.py`, `fq_loss_floor_mc.py`)
   - Tests (ADD):
     - `test_a1b_keys_disjoint_from_a1_a0_parent`
     - `test_a1b_floor_mode_in_closed_set`
     - `test_a1b_terminal_rule_present`
     - `test_a1b_g3_floor_enforced_every_mix`
     - `test_sqrt_boundary_path_byte_identical` (MC regression: the A1 cells reproduce the E-2 binding file at its seed)
     - `test_group_sequential_type_i_at_rate_cal_and_pool`
     - `test_np_bound_upper_bounds_every_candidate_power` (a sanity invariant across the evidence files)
   - Gate: run `scripts/ci/run_tests_no_egress.sh` in full after the merge, reading its EXIT before any push. Run `lint-imports` from the tree root and require "N kept, 0 broken".
   - Decision node D2: A1b freezes with a reachable mode → Phase 4. Otherwise → Phase 3b.

### Phase 3b — (c′) explicit no-trade decision (if D1 or D2 fails, or the peer ruling in step 7 is no)

9. **RULING_FQ-v2-NO-TRADE_<date>** (File: `docs/evidence/RULING_FQ-v2-NO-TRADE_<date>.md`; coordinator ruling under the standing grant; peer-reviewed; not escalated)
   - Content:
     - Cites F-2, F-3, F-4, F-5, F-7, F-9 and the Stage 0 / A1b evidence.
     - Rules that FQ v2 does not trade.
     - F9-A and F9-B are not executed for v2 as a sender. F6 stays.
     - No cap is assigned or referenced by name.
   - Re-open triggers (any one; each starts a new plan, never automatic):
     - (T1) a CONFIRM edge from a pre-registered read (for example M1-v3 at or after 12-07, or AUT-4 live or offline);
     - (T2) a new family with its own prereg whose floor passes the r3 §4.6 gate for its own mix (this covers d2);
     - (T3) a new US weather source that changes the take rate in a pre-registered way (F13).
   - PROGRESS: set FQ-R8-2-UNDER-VETO to `DONE <sha>: G-B` and F6 bridge to `permanent veto by RULING_FQ-v2-NO-TRADE`.

10. **Row-7 WP10 impact (verify first, then rule)** (owner: AUT-5a row owner)
    - Verify, read-only, with evidence:
      - (i) do the WP10 stage S, L1 and L2 criteria require orders actually sent, or only a registry-resolved sender equal to the env sender (`F1 r3:686-693`)?
      - (ii) does the F6 composed veto also refuse drill-child entries (`<champion>_r0001`)?
    - If WP10 can complete with v2 armed but vetoed, record that, together with the L-38 note that FQ v2 has no live loss evidence.
    - If it cannot, mark AUTONOMY QUEUE row 7 (and rows 8, 11 and 12, which depend on it through "row 7 merged = last WP merged") as GATED by RULING_FQ-v2-NO-TRADE, with the same re-open triggers. This is the honest goal-state statement that L-3 requires.

### Phase 4 — G-A path (only if A1b freezes reachable)

11. **F6c producer plan** (NEW plan; planner, then peer review; TDD build)
    - Scope: r3 §4.4 and §4.8 inputs, the epoch, latch and refusal channel, and the G2 positive control. Boundary = A1b. Plus the terminal `test_concluded_no_reject` refusal. Carry the F6b brief items from `F6-F7b-F13B0-open-items_2026-10-06.md:9-18` (directory modes, monotonic `as_of`, interface values) and re-verify the F4-labels/AUT-6 input dependency.
    - In F6c's reviewed commit, and only there, delete `test_fq_loss_stop_no_writer_under_unreachable_veto.py`. Its precondition (A1 the only floor) no longer holds, and the commit cites the A1b freeze sha.
    - Arming record: states worst case = daily budget × days armed (F-8), with days armed bounded by t_K and by 2027-01-25. No value is assigned.
    - Then the existing F9 sequence (`F1 r3 §R8-4`), unchanged. §R8-2 retirement stays exactly as written. It becomes reachable once v2 fills let the weekly drawdown H0 rerun file a feasible pair (F-4), and otherwise the A1b terminal veto ends v2 trading at t_K.

## Placement relative to the AUTONOMY QUEUE
- **Row 6, AUT-6 (OPEN, r15 READY).** No dependency in either direction. AUT-6 owns no loss control (F-6). The E-3 correction removes the false link. Row 6 proceeds untouched, and nothing here jumps the queue.
- **Row 7, AUT-5a (OPEN, Needs 4, 6).**
  - It owns §R8-2 retirement (coordinator), the drawdown producer and H0 (AUT-5 r7 WP3/WP11), and `app/trade.py`.
  - This plan edits no `app/trade.py` and no row-7 code. It adds one test to a row-7 test file (step 5) and a doc addendum, both reviewed by the row-7 owner.
  - F6c, if built, adds only new analysis and systemd files, so the RC-7/WP5 ordering is unaffected.
  - The one coupling is step 10: under G-B, row-7 WP10 may be blocked. Record that at the row-7 note in PROGRESS (`:71`).
- This plan lives in the FQ LOSS RESPONSE table. It is coordinator and planner work (Phases 1–3) and is not an AUTONOMY QUEUE row.

## Testing strategy
- Unit/contract: the step-2 contract tests (including the positive control), the step-5 drawdown-retirement test, and the step-8 checker and MC tests.
- Regression: F6's tests stay byte-unchanged and green, including `test_loss_stop_input_missing_refuses_after_halt_branch`, `test_composed_veto_*` and `test_f6_trade_py_changes_only_compose_fq`. The √t MC path is byte-identical (step 8).
- Full gate: `scripts/ci/run_tests_no_egress.sh` after every merge, EXIT read before any push. `lint-imports` from the tree root. The firewall and exec-import pins go in every focused gate.
- Evidence: the Stage 0 and A1b MC JSONs carry the script sha, parent sha, A0 sha, A1 sha and seed. Domain review checks them before D1 and D2 are acted on.

## Risks and mitigations
- **The E-2 rerun overturns `unreachable_veto`.** Mitigation: the STOP in step 1. Revert to r3 F6b.
- **A1b is a forking path.** Mitigation: a finite pre-declared menu, a pre-stated selection rule, a single shot, the unchanged §4.6 gate (G3 floor in M-yes), disclosure in A1b, and no live data used.
- **Reach-cutoff erosion through calendar slip.** Mitigation: Stage 0 reports `np_reach_cutoff_e`, and Phase 3a aborts to 3b if the projected arming date passes it.
- **The additive-rule ruling goes against A1b.** Mitigation: go to Phase 3b; there is no workaround that edits A1.
- **G-B blocks the row-7 live proof.** Mitigation: the step-10 verify-first and an explicit GATED status, so it is never left as a silent stall.
- **Option (a) creeps back as "drawdown landed".** Mitigation: the §R8-2(f) text and `test_bridge_retirement_refused_when_drawdown_verdicts_are_halt_inert`.
- **A contract-test scan that is too broad trips on the docs.** Mitigation: the scan is limited to `src/`, `scripts/` and `deploy/`, and the step-2 RED is shown on a fixture writer.

## Success criteria
- [ ] A1 frozen as `unreachable_veto` on the binding E-2 evidence. No frozen PREREG edited.
- [ ] F6b CANCELLED row, updated F6 row and plan row in PROGRESS. The contract test is green, with a recorded RED→GREEN and a positive control.
- [ ] E-3 filed. No document still attributes bridge retirement to AUT-6.
- [ ] §R8-2(f) filed and its test added. (a)–(e) are byte-unchanged.
- [ ] The Stage 0 NP-bound evidence is domain-reviewed and D1 recorded.
- [ ] Exactly one of these holds: A1b frozen reachable (G-A path) with the F6c plan READY, or RULING_FQ-v2-NO-TRADE filed (G-B) with re-open triggers and the row-7 WP10 impact recorded.
- [ ] No operator cap assigned or named by env var. `allow_short` False. No safety or contract test weakened.
