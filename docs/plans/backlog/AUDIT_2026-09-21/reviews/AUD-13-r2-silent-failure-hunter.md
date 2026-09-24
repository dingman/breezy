# AUD-13 review (round 2)

**Plan file sha256:** 84befd657aa2ca1fbc4e6d377a00c8a01ea1f18d20ea3fd094447e367a647928
**Round:** 2
**Reviewer:** silent-failure-hunter (independent, blind)

## Round-1 defect verification (both my own R1 record and §13's disposition table)

1. **"No CRITICAL alert on the boot-stopping reconcile-False case"** — FIXED, verified against
   source, not just claimed. `NautilusKernel.start()` (`.venv/.../system/kernel.py:1026-1029`)
   confirmed independently this session: `if self.exec_engine.reconciliation: if not await
   self._await_execution_reconciliation(): return` — the `return` sits 9 lines above
   `self._trader.start()` at `:1038` (read verbatim). `_await_execution_reconciliation`
   (`:1335-1348`) logs `"Execution state could not be reconciled"` at ERROR and returns `False`
   — exactly as §2's table claims. New AUD-13d wires a CRITICAL through the existing
   `COMPONENT_STATE_TOPIC` bus (`component_health_watch.py:95`, confirmed: `topic=f"events.system.
   {self.id}"` is published by `Component._trigger_fsm` per `.venv/.../common/component.pyx:2223`,
   so the "trader never published RUNNING" latch is a real, native observable, not invented) plus
   the `node.run()` return at `trade_cli.py:438` (confirmed: `install_component_degraded_alert`
   wired at `:421`, matching the plan's citation). The alert shape matches `app/trade.py:399-407`
   verbatim (confirmed by reading both). **Genuinely fixed.**
2. **"No replay of the 09-11 order-2 shape"** — FIXED. §7 13b step 4 names
   `test_the_2026_09_11_order_2_fill_reconciles_on_the_first_boot`, constructing the exact
   observed shape and asserting first-boot adoption plus second-reconciliation idempotence
   against `_check_and_skip_duplicate_fill` (`live/execution_engine.py:3400`, a real citation).
   §8 item 4 makes it acceptance. **Genuinely fixed**, though the test body itself is not written
   here (RED-first is scoped, not shown) — appropriate for a plan document.

## Claims verified this session (fresh read of the whole revised plan)

- `exec/client.py:2500` / `:2530` — CONFIRMED verbatim: both `generate_order_status_reports` and
  `generate_fill_reports` still `return []` with the exact docstring language quoted.
- `runtime/node_config.py:882` — CONFIRMED: `LiveExecEngineConfig(inflight_check_interval_ms=0)`
  is on that exact line; the plan's own correction of its round-1 `:821` citation is accurate.
- `trade_cli.py:413-434,438` — CONFIRMED: `install_component_degraded_alert` at `:421`,
  `node.run()` at `:438`, matching the plan's "watch install beside the existing ones" claim.
- Fail-closed semantics (§6): read failure, partial parse, disagreement — each returns `[]`
  **with** a latched reason code and a WARN, never a bare, unlabelled `[]`. This directly answers
  the brief's question and is a real, well-reasoned design, not assumed.
- Regression detector (§6, "closes the round-1 self-scored autonomy gap"): the counts line
  (`order_reports=<n> fill_reports=<n> records_considered=<n> gated_out=<n> refusals=<n>`)
  distinguishes a future silent regression to `[]` (`order_reports=0 records_considered=N>0`)
  from a legitimate empty store (`records_considered=0`) — **not trivially true**, because
  `records_considered` is populated from an independent read (the durable record store) rather
  than derived from what gets emitted; a regression that zeroes only the emission path would
  still show `records_considered=N`, which is the exact distinguishing shape the test targets.

## Defects

**MINOR — the detail-enum resolution for the two non-reconciliation early-return causes is
under-specified relative to the reconciliation case.** §6 states the boot-halt alert "must fire
for any trader-never-started boot, not only a reconciliation failure — the kernel has three other
early returns on the same path (engines-not-connected, portfolio-not-initialised)," and that
"distinguishing them is the detail enum's job, resolved from which latches were set." But §7's RED
tests only scope a generic "run that ends without the trader ever running" case and a
reconciliation-specific case; no test exercises the engines-not-connected or
portfolio-not-initialised paths, and no second (or third) latch is named for them the way the
component-state-bus latch is named for the trader. This does not weaken the core F5 fix — any of
the three causes still trips the generic "trader never ran" alert — but the enum's ability to
*name* the other two causes correctly is asserted in prose, not tested. **Fix:** either scope a
RED test per early-return cause (naming its own latch/observable), or narrow §6's claim to "the
detail enum best-effort names the cause where a latch exists; unattributed causes fall to a
generic detail value" and say so explicitly.

No MATERIAL defect found. Both round-1 material defects (F5 alert, 09-11 replay) are genuinely
fixed with source-verified evidence, not merely asserted in §13.

## Per-criterion points

| Criterion | Cap | Points |
|---|---|---|
| Fidelity to audit gap and completeness | 20 | 20 |
| Technical correctness and evidence grounding | 20 | 20 |
| Implementation specificity and feasibility | 15 | 14 |
| Acceptance criteria and validation quality | 20 | 19 |
| Autonomous operation, failure handling and recovery | 15 | 15 |
| Portfolio objective alignment, scope and dependencies | 10 | 10 |
| **Total** | **100** | **98** |

## Required changes to reach 100

1. Scope a RED test (or explicitly narrow the claim) for the detail-enum's ability to distinguish
   the engines-not-connected and portfolio-not-initialised early-return causes from the
   reconciliation-False cause, not just the generic "trader never ran" signal.

## Blockers

R-1 and R-2 (strategy-lead rulings) remain genuine BLOCKERs on 13b/13c, correctly named and not
waivable by review.

## Review record path
docs/plans/backlog/AUDIT_2026-09-21/reviews/AUD-13-r2-silent-failure-hunter.md
