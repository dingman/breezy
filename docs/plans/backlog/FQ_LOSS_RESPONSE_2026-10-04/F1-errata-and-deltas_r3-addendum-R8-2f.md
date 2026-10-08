# F1 errata and deltas r3, §R8-2 addendum (f) (2026-10-08)

This is a doc-only addendum. §R8-2 (a)–(e) are byte-unchanged and none of them is relaxed. Source: FQ-R8-2-UNDER-VETO_plan_r2, step 4. The row-7 (AUT-5a) owner reviews it.

> (f) Under A1 `floor_mode: unreachable_veto` (frozen d6a339ce, frozen_sha 8756dcc4), (a) and (b) cannot be met by construction. No v2 drawdown block can be non-inert (AUT-5 r7 `:768`, AD3 `:752`). Retirement is therefore not an available exit. The FQ v2 disposition follows FQ-R8-2-UNDER-VETO_plan_r2. No retirement may cite a `HALT_INERT` verdict. No part of (a)–(e) is relaxed.

**Hand-off (r2 D-17).** `test_bridge_retirement_refused_when_drawdown_verdicts_are_halt_inert` is a brief input to the row-7 WP that owns the §R8-2 tests. In that test, five `HALT_INERT` PASS days with ≥ 10 fills must give a false retirement predicate. It is not built here.
