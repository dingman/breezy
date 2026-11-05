# RULING_FQ-v2-NO-TRADE_2026-10-08

**Type:** coordinator ruling, peer-reviewed (trading-bot-architect REVISE → applied 2026-10-08; domain D1 sign-off), not escalated (operator pre-authorization; the only operator-reserved items are the two budget caps, and this ruling assigns neither).
**Source plan:** `docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04/FQ-R8-2-UNDER-VETO_plan_r2.md` (r2 plus r2.1, converged), Phase 3b, steps 9 and 10.
**Goal state reached:** G-B.

## Current state (verified 2026-10-08 ~11:00Z)

- **The trade node is running** under the supervisor with `boot_family id=pm_us_crh_fq_v1`, booted 2026-10-07 16:50Z.
- **No real orders are being placed.** The supervisor drop-in `fq-v1-halt-orders-off.conf` sets `BREEZY_ORDERS_ENABLED=0` (10-06 backstop), and the permit capability is `absent`.
- **No family currently trades real money.** FQ v1 is halted (FQ LOSS RESPONSE). FQ v2 was the planned successor sender.
- **This ruling supersedes, for v2, the 2026-10-01 operator ruling "FQ live real orders ASAP".** Its precondition, a v2 that can be armed under the build gates, cannot be met. That ruling itself said build gates still bind.
- **Cheapest re-open path:** wait for the M1-v3 read on or after 2026-12-07 (T1). It starts a new plan and needs no code change now.

## Ruling

1. **FQ v2 (`pm_us_crh_fq_v2`) does not trade.** The F6 composed veto stays in place and refuses every FQ v2 entry, both for the champion and for drill children (`trade.py:763-809`, `:933-940`; `loss_stop_probe.py:286-291`).
2. **F9-A and F9-B are not executed with v2 as the sender.**
3. **No replacement loss floor (A1b) is designed.** The plan's single-shot A1b path is closed by D1 FAIL (below). No A1c exists.
4. **No operator cap is assigned, derived or named.** `allow_short` stays False. No safety, settlement, contract or firewall test is changed.

## Evidence chain

| Step | Result | Artefact |
|---|---|---|
| A1 floor MC, binding run under errata E-1/E-2 (seed 20261008, 10k replicates) | `unreachable_veto`. G1 passes at α 0.10 in every cell. G3(−0.16) in M-yes is 0.2104, below the 2.5·α floor of 0.25. Domain peer: FREEZE-OK | `docs/evidence/f5/fq_loss_floor_mc_seed20261008.json` (sha256 61ddfad8…) |
| A1 frozen | `floor_mode: unreachable_veto`, `power_class: none` | `F5_prereg_v2_amendment_A1.json`, frozen_sha 8756dcc4, stamp d6a339ce |
| Stage −1 | No structural exclusion. MIXSET = {M-pool, M-yes, M-no} | `docs/evidence/f5/fq_r8_2_stage_minus1_mix.md` (d3d1d64b, committed before Stage 0) |
| Stage 0 NP bound (seed 20261009, 10k replicates; `e_proj` = 2026-11-01, pinned in code at fe741c9d before the run) | **D1 FAIL.** `bound_upper_min` at 11-01 is 0.125, against the 0.30 bar. M-yes binds at every epoch (α_eff 0.0187, NP bound 0.1186). `np_reach_cutoff_e` = null | `docs/evidence/f5/fq_loss_floor_np_bound_seed20261009.json` (sha256 231c4643…, commit 2bf47892) |
| Domain sign-off on D1 | **SIGN-OFF D1 FAIL (rule stands)** | this record, §Disclosures |

Mechanism, in one line: in the M-yes mix a station-day path has a median of about 7 ticks before the horizon. So any boundary scaled on the binding-max cell has an M-yes null rejection rate of about 0.02–0.03. At that α, even the Neyman–Pearson optimum reaches only about 0.12–0.19 power against δ = −0.16. Without a responsive stop that can fire, FQ v2 cannot be armed (r3 §4.7, L-38).

## Disclosures (forking-path and evidence notes)

- **The bound at α = 0.10 would pass.** The only *guaranteed* NP upper bound is the one at α = 0.10. For M-yes at 11-01 it is 0.3645. The pre-declared rule (r2.1 C-7) uses the boundary's effective α instead.
  - The domain reviewer ruled that the rule stands. M-yes's low null rate comes from the mix (short paths), not from the boundary shape. Group-sequential candidates have fewer crossing chances than √t. A1's own run shows the same M-yes/M-pool null ratio of about 0.35.
  - Switching to α = 0.10 after seeing FAIL, in the direction that unblocks trading, would be a post-result gate change.
  - A remedy that could be pre-declared (each menu shape's M-yes null α at its own binding-max scale) was named but not required. It can only be pursued under a new prereg (trigger T2).
- **The information set differs from A1's.** Stage 0 truncates each path at t_K(e) = ⌊0.8·T_low(e)⌋, while A1 monitors the full horizon. That is why at 10-08 A1's G3 (0.2104) exceeds NP(α_eff) at t_K (0.1921). The difference is consistent with the information set and is not a bound violation.
- **The SE is understated.** `np_bound_alpha_eff_se` is conditional on the H0 critical value and on γ. Noise in α_eff adds about ±0.004 at 11-01. The 0.175 gap between 0.125 and 0.30 makes this immaterial.
- **The identity figures are pooled.** The information identity (C-6) held, with figures pooled across mixes. The M-no γ at 10-08 (1.1e-13) is floating-point noise.

## Re-open triggers

Each trigger starts a new plan. None re-opens anything automatically.

- **T1.** A CONFIRM edge from a pre-registered read. The AUT-4 route needs a live-trading family, so it cannot fire until T2 supplies one. **M1-v3 is the only live T1 route**, read once on or after 2026-12-07.
- **T2.** A new family with its own prereg whose floor passes the §4.6 gate for its own mix. This covers a restricted-mix family (d2) and the per-shape α remedy above. A new family as the env sender is also the route that un-gates AUTONOMY QUEUE rows 7–12.
- **T3.** A new US weather source that changes the take rate in a pre-registered way (F13).

## Review date (D-13, C-4)

The review date is **2027-01-25**, or the start of the next F5 epoch, whichever comes first. On that date the coordinator re-reads T1–T3 and records whether the ruling stands. **If the date passes with no recorded review, the ruling stays in force** (fail-closed).

## Row-7 impact (step 10; read-only trace, verified by the coordinator)

| Question | Answer |
|---|---|
| (i) What do WP10 S/L1/L2 require? | Registry-resolved family equal to the env sender, plus ATTEST/heartbeat artefacts. No sent or filled order is required (`F1-errata-and-deltas_r3.md:687-689`; `AUT-5-promotion-demotion_plan_r7.md:936-938, :987-993`). **But an L1 session counts only if it starts after the recorded F9-B read-back** (`F1 r3:687-688`), and this ruling does not execute F9-B. |
| (ii) Does the F6 veto refuse drill children (`<champion>_r0001`)? | **Yes.** Every `forecast_quantile_ladder` manifest gets the composed veto. The loss-stop artefact is scoped to the catalog, not the family (`trade.py:763-809`, `:933-940`; `loss_stop_probe.py:118-119, :286-291`). |
| (iii) Can WP10 complete under G-B? | **No.** Any L1 proof would be a **zero-fill proof** that shows wiring and veto behaviour only, never live loss behaviour. |

**Consequence (scope narrowed per architecture review).** Row 7 splits into two parts:
- **7a (WP1–WP9, inert) stays OPEN** and may merge, per FQ-R48.
- **7b (WP10 stage S/L1/L2) is GATED** by this ruling.

Rows 8–12 are **not** gated wholesale. Their Needs on row 7 mean 7a DONE; row 8's dependency, for example, is the `trade.py` merge order (AUT-1 r2 `:119`, `:729`). Only their live or proof stages that need a registry-resolved sender with real fills are GATED:
- AUT-1b live activation;
- AUT-4 live-sequential;
- AUT-5b;
- AUT-7b.

Offline and inert build stages proceed. Each row's exact live-stage boundary is confirmed against its own plan when that row is dispatched. T2 (a new sender family) is the structural un-gate.

**PROGRESS consequences (step 9):**
- set FQ-R8-2-UNDER-VETO to `DONE <sha>: G-B`;
- set the F6 bridge to `permanent veto by RULING_FQ-v2-NO-TRADE`;
- split row 7 into 7a OPEN / 7b GATED, and note the gated live stages of rows 8–12.

**Plan facts cited (step 9):** F-2 (no PASS under the veto), F-3 to F-5 (§R8-2 retirement unreachable; drawdown `halt_inert`), F-7 (KILL cannot fire before 2027-01-25), F-9 (the E-2 G3 figures) and F-12 (G3 is measured at realised N), all from plan r2 §Facts. Stage −1 and Stage 0 evidence are cited above.

## Not built under this ruling

- **F5 A2 (the calibration guard, r3 §5) is not built.** It only gates FQ v2's PASS path and its forward-shadow registration, and this ruling forecloses both. If a trigger re-opens FQ v2 or a successor, any guard is planned under that family's own prereg.

## What stays in force

- The F6 composed veto and the F6 contract tests.
- `tests/contract/test_fq_loss_stop_writer_allowlist.py`: the `_WRITERS` allowlist stays empty, and `reachable_floor()` is False for the frozen A1.
- The A0 KILL constants.
- M1-v3 (frozen, single read on or after 2026-12-07).
- The F13 US-source collectors.
