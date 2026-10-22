# P1 r2 verification — Grok

I'll review P1 r2 against the five required changes from the r1 review, and check whether G0 can actually be reproduced from commit `0d6b4c59`.The r1 review and r2 plan are in hand. Next I’ll check whether commit `0d6b4c59` actually contains the sharp arm and the recorded run config.**VERDICT = APPROVE-WITH-CHANGES**

The five r1 changes are in the plan. The wrapper test pins sizes: a size-10 print inside L leaves `r` and `g` unchanged; a later size 3 leaves `r=2` and no fill; size 2 fills. G2 is gone. G4 is gone, and the markout is report-only with no p-value. Control arms, the reconcile script, and the sign-flip harness are under "Not doing". P4 starts only on G0 and G1. L=5s and the markout do not gate. Nothing left is over-built.

G0 is feasible from a clean worktree HEAD `0d6b4c59`. `maker_design_config.py:83` is `Arm("sharp", 0.89, 2, False, p_min=0.97, e_min=0.04, b_floor=0.75)`. `delta_ns` defaults to 0, and `maker_design_nobid.py` passes that where the sharp commit passed a literal 0, so the sharp replay matches `1713c8bf`. Dates and the grid are not in that file. `summary.json` has `day_from` 2026-09-18, `day_to` 2026-10-13 (the fence in `maker_stage0_frozen.py`), θ `(0.0695, 0.08)`, and slip `(0.01, 0.02)`. Plan-cache version 1 is on disk.

G1 is a sound, fixed gate once the rows are named. "10" must use the same filter as the 17 (`maker_design_score.py:191`: `stress_pass` and `win is not None`). A loser is `win is False` on any filled L=1s row, base or stress. Falling under 10 is a conservative stop: prints during L do not consume the queue, so this model under-fills when the book trades.

1. The sharp artifact's `code_sha` is `eac99bd6`, not `206d89ae`. Both commits lack `Arm("sharp")`. Cite `eac99bd6`.
2. `sum_x` 1.96 is only the slip-0.01 cells (`x_t0.0695_s0.01` and `x_t0.08_s0.01`). Slip 0.02 is 1.79. Name the base cell, or a 1.79 cell false-stops the programme.
3. Write the G1 row filter and `win is False` into the gate. Do not add another statistic.

Confidence: 88.
