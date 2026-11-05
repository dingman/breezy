# GAP-4 review status (2026-11-01)
- plan_r1.md — prediction-market-reviewer: APPROVE (3 LOW notes); architect: APPROVE (3 LOW notes). Peer review CLOSED at r1.
- LOW notes accepted as binding build notes (no re-review needed):
  1. §3 C1 override built as `dataclasses.replace(LadderEvConfig(), margin_m0=x, margin_m24=x)`, never a fresh constructor.
  2. §5 PREREG states that a KILL at D_c, or at n_max with information fraction t < 1, is a declared terminal look (`truncate_at`) spending the remaining alpha; the S0 power dry-run uses the cell's actual break-even mix (`--pi`).
  3. §9 item 1: if the CRH generator output cannot be loaded as an FQ `boundary_artefact_path`, S0 stops BLOCKED-NEEDS-PLAN; no new generator is written (10-21 ruling).
