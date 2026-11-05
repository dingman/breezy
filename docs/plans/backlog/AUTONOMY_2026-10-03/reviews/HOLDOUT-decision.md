# Coordinator decision: one holdout ruling for AUT-3 and AUT-4 (2026-10-03)

**Conflict.** The sealed NBP holdout grows forward from 2026-07-01 with no end, which blocks both
rolling refits (AUT-3, P3-1) and forward evaluation (AUT-4, P4-1). The two planners proposed
different fixes (a freeze versus R-A).

**Decision (to be drafted as a ruling under `docs/evidence/` and peer-reviewed; not an operator decision):**
1. The archive holdout is FROZEN at **[2026-07-01, 2026-10-02)** and stays sealed for one final
   confirmatory use only.
2. Days on or after **2026-10-02** are forward data:
   - AUT-3 trains only on days before each forward evaluation window.
   - AUT-4 evaluates on a **rolling forward holdout** of post-training days, under the AUT-4 α-spend.
3. Contamination disclosure (from the AUT-4 PM review): the September tape studies (WP-7b, AUD-02,
   the 09-20 terminal finding) already touched [07-01, 10-01). The ruling discloses this, and S2 on
   that window is descriptive evidence only.
4. ARCH owns the ruling text (C3/C4). AUT-3 and AUT-4 consume it by its name,
   `RULING_holdout_freeze_and_forward_window_2026-10-03`, and must not restate a different version.
