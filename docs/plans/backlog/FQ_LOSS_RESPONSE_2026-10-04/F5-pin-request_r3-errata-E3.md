# F5 pin request r3, errata E-3 (2026-10-08): AUT-6 does not retire the F6 bridge

**Finding** (FQ-R8-2-UNDER-VETO plan r1, confirmed by the architecture peer review). r3 says FQ v2 entries are vetoed "until AUT-6 retires the bridge". That attribution is wrong. AUT-6 r15 owns drift and health only and has no loss detector. Bridge retirement belongs to the AUT-5a row owner under F1 r3 §R8-2.

**Correction.** The text of r3 is unchanged, and this errata governs where they conflict.

- r3 `:222` reads as:
  > "**`unreachable_veto`.** The producer never writes PASS and always refuses, so FQ v2 entries are vetoed for the epoch. Bridge retirement belongs to the AUT-5a row owner (the coordinator) under F1 r3 §R8-2. Under this mode §R8-2(a)/(b) cannot be met (§R8-2(f)). AUT-6 owns no loss control and no part of retirement. The FQ v2 disposition is decided by FQ-R8-2-UNDER-VETO_plan_r2. This is a goal-state blocker (r2 §4.5)."
- r3 `:428-429`:
  - "until AUT-6" reads as "until FQ-R8-2-UNDER-VETO_plan_r2 reaches G-A or G-B";
  - "planned through AUT-6" reads as "planned in FQ-R8-2-UNDER-VETO_plan_r2".

**Status.** A1 froze as `unreachable_veto` at d6a339ce (frozen_sha 8756dcc4). So this branch of r3 is the one in force.

**Lapsed input.** `F6-F7b-F13B0-open-items_2026-10-06.md:8` (F4 labels / AUT-6 activation) was an F6b input. It lapses with F6b, and any F6c must re-verify it.
