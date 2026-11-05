# P1 plan r1 — maker replay reconcile, latency, adverse selection (2026-10-22; author planner)


**Goal.** Decide whether the sharp maker rule's in-sample edge survives three things: a correct fill count, a realistic delay before the order is visible, and an adverse-selection test. The answer is PASS (go to P4) or FAIL (the maker programme ends).

## Inputs (checked on disk 2026-10-22)

- **Code.** Worktree `/home/jon/breezy-maker-design` (the outputs were produced at `code_sha` eac99bd6). Files: `scripts/analysis/maker_design_{nobid,config,score}.py` and the simulator `maker_stage0_fill_pass.py`, which is not edited. Every command runs with `PYTHONPATH=/home/jon/breezy-maker-design`.
- **Existing outputs.**
  - `~/.local/share/breezy/derived/replay/design/maker_nobid_full/summary.json`: control has 8 fills, 8 wins, `sum_x` 1.68, `differences: []`.
  - `.../maker_nobid_sharp/{summary.json, sharp/positions.csv, sharp/episodes.jsonl}`: sharp has 17 fills, 17 wins, `sum_x` 1.96.
- **Run inputs.** Config inputs as recorded in `sharp/summary.json` (plan cache `~/.cache/breezy/maker_design_work/plans/full_plan.json`, census, truth, calibration with its sha256, θ (0.0695, 0.08), slip (0.01, 0.02)). Days 09-18 to 10-13, excluding the sealed day 10-01.
- **The 17-vs-20 discrepancy is already explained by the code.**
  - `maker_design_score.arm_stats` counts a fill only when it passes the stress rule (queue doubled) and has a truth row (`stress_pass and win is not None`).
  - `positions.csv` has 20 positions filled under the base rule. 17 also fill under stress. 3 fill only under base: MIA 09-27 `gte91f`, MDW 10-06 `gte76lt77f`, LAX 10-11 `gte78f`. All 3 are `win=True`.
  - `PositionFold` keeps one row per rung, and the 20 episodes with `filled_ns_base` match the 20 base-filled positions.
  - So the gap is base vs stress fills. It is not a counting bug, and it is not abstention (sharp has `abstain=False`). Counting the 3 base-only fills would add no loser. Step 1 only re-confirms this mechanically.

## Decisions (fixed before anything is run)

- **Latency goes in the driver, not the simulator.** Editing `maker_stage0_fill_pass.py` would break both the Stage 0 positive control and the C3 parity of the ported core. The driver gets a `latency_override(latency_ns)` context manager, built the same way as the existing `rule_override`. It wraps `fill_pass.Pass._on_print` for one replay and always restores it. A print on a live episode with `ts <= ep.t0_ns + L` is ignored: it only updates `self.instance` and returns. The queue snapshot taken at t0 is kept.
- **Latency values: L = 1 s (primary) and 5 s (stress). Both must pass.**
  - 1 s is about 8× the measured live decision→ack time (~113–120 ms). It covers the time for the venue to insert the order into the book, plus the skew between the book and trade data feeds. The 0.054 s fill looks like one sweep seen on both feeds.
  - 5 s bounds the venue-visible time of a resting order, which is unknown, and the node's own decision compute.
  - Keeping the t0 queue is not strictly conservative if the queue grows during L. The gate therefore counts only fills that pass the stress rule.
- **Rules.**
  - All of control, sharp, and the latency arms are re-scored in one run.
  - **The gate binds on sharp only**, because P4 r2 runs sharp unchanged and has dropped control (8 fills in 23 days cannot reach P4's fill floor).
  - Control is reported as the pre-registered comparator and does not gate.
  - No new rule variants and no threshold changes.
- **Same tape, and the holdout.**
  - Unseen tape does exist. The quote tape for 10-14 to 10-22 is in the catalog (spot-checked on LAX depth files), and CLI finals for all four stations run to 10-21.
  - It is not replay-ready, though:
    - The derived NBP files stop at the `nbp_20261012_*` cycles.
    - The S1 census has no rows after 10-13.
    - `parse_config` refuses any `to` date after `LAST_ALLOWED_DAY` (10-13).
    - Censusing that block goes through the archived S2 second-look guard, which needs a search declaration and a read-ledger.
    - The 10-18 and 10-19 recordings were truncated by a reboot.
  - It would yield about 4–6 sharp fills, which is not enough to confirm anything.
  - **Decision:** P1 is an in-sample falsification screen only, and a PASS never claims an edge. P4 (live, up to 40 fills) is the out-of-sample test. The 10-14 to 11-15 block stays unread, so it can serve as a clean replay holdout if P4 comes back inconclusive.

## Steps

1. **Reconcile.** New script `scripts/analysis/maker_p1_audit.py` (one file for reconcile, gate evaluation and the adverse-selection test). The `reconcile` subcommand reads the existing sharp and control outputs and writes:
   - fill counts under base, under stress, and base-only, with each fill's `win`;
   - the list of fills where `filled_ns − t0_ns < 10 s`, which must show 4 with a minimum of 0.054 s.
2. **Latency arms.**
   - Edit `scripts/analysis/maker_design_config.py`: add `Arm.latency_ns: int = 0` and four arms, `control_l1`, `control_l5`, `sharp_l1` and `sharp_l5`. Their parameters are identical to `control` and `sharp` except for latency.
   - Edit `scripts/analysis/maker_design_nobid.py`: add `latency_override`, and in `_replay_arm` wrap `replay_station_day` in it next to `rule_override`.
3. **Tests.** Edit `tests/unit/test_maker_design_nobid.py`:
   - a synthetic `Pass` with one live episode and prints at t0+0.5 s and t0+2 s. With L=1 s it fills at 2 s; with L=0 the behaviour is unchanged;
   - the override is restored after an exception;
   - the arm-table pins and the NO<0.90 ceiling still hold.

   Then run `pytest tests/unit/test_maker_design_nobid.py tests/unit/test_maker_stage0_*.py`, then `lint-imports` (run from the worktree directory), then `ruff check`/`ruff format` on the changed files only.
4. **Run.** One invocation with arms `[control, sharp, control_l1, control_l5, sharp_l1, sharp_l5]`, the config at `~/.cache/breezy/maker_design_work/configs/p1.json`, and a fresh out-dir `.../design/p1_latency/`.
   - Command: `systemd-run --user -p MemoryMax=8G -p RuntimeMaxSec=21600 -p LimitNOFILE=524288 … maker_design_nobid --config … --out-dir …` with `workers=2`.
   - Stall watch: flag if `progress.jsonl` is unchanged for more than 30 min.
   - Only one heavy job may run at a time, so check that no nightly study is running first.
5. **Adverse selection** (`maker_p1_audit.py as`).
   - **Fills.** The stress-pass fills of `sharp_l1`. Also report `sharp_l5`, `control_l1` and `control_l5`.
   - **Price.** YES mid = (best YES bid + best YES ask)/2, taken from the last Depth10 frame at or before t. Frames are read with native `ParquetDataCatalog.order_book_depth10` on the config's `catalog_root`.
   - **Move per fill.** Δ_i = mid(t_f+600 s) − mid(t_f−1 ns), in cents. A positive Δ is adverse to the NO holder.
   - **Matched controls.** Rungs the same arm posted on the same climate day (any station) that never filled under base, with Δ measured over the same instants. d_i = Δ_i − mean(Δ_controls).
   - **Test.** Sum d by day, D_k = Σd_i. One-sided sign-flip on the D_k: exact when there are 20 days or fewer, otherwise 200,000 random flips with seed 20261022.
   - **Report.** The mean of d in cents next to the mean X (~10–11 ¢).
   - **Test file.** New `tests/unit/test_maker_p1_audit.py` as a positive control: synthetic fills followed by +5 ¢ moves against flat controls must give p < 0.05, and the mirrored case must give p > 0.5.
6. **Record.** Write the results as one short evidence note, `docs/evidence/P1_maker_reconcile_latency_AS_<date>.md`, and update the P1 row in `docs/core/PROGRESS.md`. Commit only these files, by explicit path.

## PASS / FAIL / STOP (sharp; both L = 1 s and L = 5 s unless stated)

- **G0 validity.** In the same run at L=0, `control` must give `differences == []`, 8 fills and `sum_x` 1.68, and `sharp` must give 17 fills and `sum_x` 1.96. Otherwise the run is INVALID: **STOP** and fix the driver.
- **G1 fills.** Stress-pass fills of `sharp_l1` must be at least 10. Otherwise **FAIL**: the fills were latency artefacts, and P4 would hit its "<10 fills in 21 days" stop.
- **G2 net.** `mean_x` > 0 in all four θ×slip cells, at both latencies. Zero fills at L=5 s also counts as **FAIL**.
- **G3 no added loser.** Zero base-pass fills with `win=False` at either latency. The L=0 baseline has zero.
- **G4 adverse selection.** **FAIL** if p < 0.05 (adverse). The test is untestable if more than 25% of gate fills lack a Δ or a control. That is a **STOP**, treated as not-PASS, and P4 does not start.
- **PASS** = G0–G4 all pass. Then P4 runs sharp unchanged. **Any FAIL** ends the maker programme.

## Effort and wall-clock

$0. About 3 h of code and tests, 2–4 h for the run (the earlier 2-arm run took 75 min), and about 2 h for the adverse-selection test and the note. About 1 day in total.

## Risks

1. **The override is not strictly conservative if the queue grows during L.** Mitigation: gate on stress-pass fills (queue doubled) and on L=5 s.
2. **Gaps in Depth frames or an empty YES bid side could make the adverse-selection test untestable.** Mitigation: the pre-set STOP at 25%, with no fallback price.
3. **Low power.** n≈15 fills over about 11 days means "not adverse" is weak evidence. Mitigation: report the effect size. A PASS licenses P4 only, never a scale-up.

## What we deliberately do NOT do

- No edit to any `maker_stage0_*` simulator file and no `src/` change, so the full gate is not required.
- No new rule variants, no tuning of thresholds or latency after reading results, and no maker-rebate modelling (the maker fee stays at the taker θ).
- No holdout replay: no NBP backfill, no second-look census, and no relaxing of the fence.
- No PREREG, ruling, ledger, unit or timer. This plan is the pre-registration.