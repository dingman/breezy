# RULING — AUD-07 M1c: eps_k switch or global-pin override, as a pre-registered decision rule (2026-09-26)

**Authority.** This ruling decides EXEC-REV2 §5 :309 ("If f > 10%: switch to a per-depth `eps_k` table…"). Segment A (code-S 0369e12) passed CAL with a valid global pin, EPS=0.6948 and DT_MIN=6.5e-05, but CAL-c gave refine fractions f = {0: 0.191, 15: 0.2115, 46: 0.2075}, all above 0.10. The glue therefore stopped before 20k.

**Ruled by:**
- `architect` (blind)
- `prediction-market-reviewer` (blind)
- the coordinator, who merged the two

Both reviewers agreed on every point below. The plan is `docs/plans/backlog/AUDIT_2026-09-21/AUD-07-M1c-eps_k-switch-plan_r1_2026-09-26.md`.

**This rule is committed BEFORE any counterfactual number exists.** Only the global-pin f is known.

## Findings, agreed by both
- **f is performance-only.** `classify_cell`, `final_class` and `branch` (the §6 M2 gate) use only `ALPHA`, `V_THRESHOLD`, `V_CONF` and `I_CONF`. f appears only in the §2.4 cost model and in the §6 method disclosure. The global pin is already validated: CAL-a ≡ CAL-c, 0 audit disagreements, EPS ≥ 3× the census max. Running 20k on the global pin is statistically equivalent to running it under eps_k. Only compute cost differs.
- **DT_MIN never triggers.** The CAL-c refine reasons are dt = 0 in every cell. The cause is the eps band alone.
- **The census max looks like a terminal or t-cap point.** The value 0.16852808884208237 is bit-identical across cells 21, 25, 29, 33, 37 and 41, which implies an identical t-history. If the dominant Δb sits at the terminal look, a per-ordinal eps_k may not reduce f.

## Rulings
- **PR-1 (ADOPT, amended).** eps_k is indexed by look ordinal, plus an **authoritative** `eps_terminal`.
  - Terminal classification keys strictly on the sim's own stop rule (`LookRecord.terminal`, i.e. the first look with t ≥ 1 or N_MAX), never on ordinal position and never on the census's `look_n >= N_MAX`.
  - `eps_terminal` passes the same validation as eps_k: floor ≥ 0.02 and ≥ 3× the terminal census max.
  - A depth with no observations falls back to the global eps, never to the floor.
  - The pin refuses a table whose length ≠ N_MAX/LOOK_STEP, and refuses a scalar `eps` ≠ max(eps_k, eps_terminal).
- **PR-2 (ADOPT).** DT_MIN stays one global scalar and is unaffected by eps_k. No per-depth DT_MIN exists.
- **PR-3 (ADOPT).** Whichever pin is used for 20k is terminal for this study. The glue then runs with `F_GATE_MAX=1.0`. This is legitimate because f never touches the V/I/INDETERMINATE test, and it is set before any eps_k f is known.
- **PR-4 (decided by the rule below).** This ruling is the amendment for either branch. The override branch changes execution mechanics only; the statistic, boundary and population are unchanged.

## Pre-registered decision rule
1. **Counterfactual.** Run a read-only scratch counterfactual against the frozen code-S snapshot. No new sha, no pin written, nothing gated. Constraints: P ≤ 3, MemoryMax 6G, one heavy job at a time.
   - (a) A per-depth plus terminal census at 400 reps on cells 0, 15, 46, 17, 21 and 45. Record each look's (depth, terminal).
   - (b) Coarse-only replicates of cells 0, 15 and 46 on the CAL-c seeds at 2000 reps. Record each look's (depth, terminal, s−b_eff, s−b_fut).
   - (c) Compute the predicted f(eps_table) for eps_k and `eps_terminal` derived from (a) under the PR-1 rules. f is a pure function of those margins.
2. **Decision.**
   - If the **maximum predicted f across cells 0, 15 and 46 is ≤ 0.10**, build eps_k: TDD code S′ per the plan, amended by PR-1 and PR-2 and by the architect's code notes (normalise a legacy scalar to a constant table; `to_json` omits `eps_by_depth` when None; test 17 excludes the new key). Then rerun CAL at S′ in the next A-window, then run 20k.
   - **Otherwise, override.** Run 20k on the existing validated global pin (code-S 0369e12) with `F_GATE_MAX=1.0`, and skip the CAL rerun.
3. **Record.** Write the counterfactual numbers and the branch taken into `docs/evidence/AUD07_M1c_eps_k_counterfactual_<date>.md` before any 20k starts.

## Also ruled
- **Superseding the old run dir.** Place a `SUPERSEDED` marker and a reason file in `runs/0369e1218a85/` only if the eps_k branch is taken, and make the glue refuse a marked dir. Never rename the dir, because renaming breaks the absolute paths in the M2 evidence. Under the override branch the dir stays live.
- **Glue citation.** "amendment §5" is corrected to "EXEC-REV2 §5".
- **Seg C (14:05–14:50Z) is dropped.** It is unrealistic under L-43 plus the AUD-09b C2 window.
