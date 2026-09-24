# AUD-13 — Round 3 review (silent-failure-hunter)

**Plan file:** AUD-13-native-venue-reconciliation-from-durable-records.md
**SHA256:** 01e9c2290bf0c2f89923fe48f5b2ef405e97f0423afe34df6ea22540001371de
**Round:** 3
**Reviewer:** silent-failure-hunter (independent, blind)

## Claims verified against source (this session)

| Claim | Status |
|---|---|
| `NautilusKernel.start()` (`.venv/.../system/kernel.py:1024-1039`) — three early `return`s at `:1025`, `:1029` (reconciliation, guarded by `:1027`), `:1037`, `self._trader.start()` at `:1039` | CONFIRMED verbatim, exact lines, including the `:1038`→`:1039` correction |
| `self._emulator.start()` (`:1033`) and `self._initialize_portfolio()` (`:1034`) sit strictly between the reconciliation-return and the portfolio-return | CONFIRMED — a failed reconciliation means neither line is ever reached, which is the load-bearing fact the detail-ladder's discrimination (probe 2, `OrderEmulator` RUNNING) depends on |
| `data_engine.check_connected()`/`exec_engine.check_connected()` are the two probes the kernel itself reads at its own timeout diagnostics (`kernel.py:1313-1314`) | CONFIRMED |
| `portfolio.initialized` read at `kernel.py:1362` inside `_await_portfolio_initialization` | CONFIRMED region (`:1353-1362`) |
| §8 item 8's "six-symbol negative `git diff`" (`self_check`, `DaySchedulerState`, `initial_scheduler_state`, `_for_day`, `_trading_day`, `mark_phase_fired`) matches — not applicable here (that's AUD-14); AUD-13's own six-symbol claim is not present — n/a | n/a, no false citation found |
| `self_check` ladder at `trade_supervisor_core.py:499-553` | CONFIRMED — cited only incidentally (shared module), matches |

The kernel-halt discrimination logic is genuinely sound: since `_emulator.start()`/`_initialize_portfolio()` are unreachable on a reconciliation failure but reachable (and thus the emulator RUNNING event observable) on a portfolio-timeout failure, the two causes are separable by the stated ladder, and this was independently verified from installed Nautilus source this session, not merely re-asserted from the plan's own prior citations.

## Attack per brief: is "SYMBOL GONE = stop" observable or silent?

§7 13b step 0 requires a recorded per-citation table (`09-12 citation / symbol / anchor at HEAD / status`), with `SYMBOL GONE` defined as "a stop, not a row" — escalated to the strategy lead alongside R-1/R-2, never silently re-pointed. §8 item 12 makes the table itself an acceptance artefact ("13b is not accepted even if its tests are green" without it). This is a documentation/process gate, not a runtime detector, and is evaluated on that basis: the escalation is a written artefact under `docs/evidence/` plus an acceptance-blocking check, not a silent skip. That is an adequate, observable stop for a build-time gate — no defect found here. (This was the specific round-2 architect defect; the fix — turning a prose warning into a gated, acceptance-pinned step — holds up under a second, independent reading.)

## Other checks

- The detail-enum ladder's fall-through (`BOOT_HALT_TRADER_NEVER_STARTED`) is explicitly tested (§7 step 3c) as "still delivered, never swallowed and never mislabelled" — this is exactly the anti-pattern (an unattributable cause going unalerted) this review lens hunts for, and it is closed.
- The three fail-closed walks (positions-read failure, partial-parse, venue/local disagreement) all specify "report nothing **and** a latched reason code **and** a WARN" — none collapses to a bare `[]`. Verified as stated in §6/§9, consistent with the codebase's `emit_alert`/`AlertPayload` pattern already used elsewhere (`health.py:668-689`).
- The regression detector (`order_reports=<n> ... records_considered=<n>`) is a real, non-trivial distinguishing signal for a future silent regression to `[]` — not a trivially-true check, since `records_considered=0` and `order_reports=0 records_considered=N` are genuinely different observable shapes.

## Defects found this round

None MATERIAL. One MINOR, already self-identified and not contested:

- **MINOR** — the round-3 self-score's own deduction that driving a real kernel to the `check_connected()`-never-true and `portfolio.initialized`-never-true timeouts inside a unit test (§7 13d steps 3b) is the most fragile fixture work in this item, and its exact fixture shape (how the test forces those two conditions without simply mocking the kernel, which would undercut "driving the real kernel") is left to the implementer. This is a real, nameable specificity gap but not one that blocks the plan's correctness — it is a test-authoring risk, not a design gap, and the plan already flags it rather than hiding it.

No new MATERIAL defect was found on a second independent read of the kernel-halt ladder, the fail-closed semantics, or the citation-drift gate.

## Per-criterion points

| Criterion | Cap | Points | Reason |
|---|---|---|---|
| Fidelity to the audit gap and completeness | 20 | 19 | G-10 fully covered plus the boot-halt path it implies; field maps deliberately left in the 09-12 plan, now behind a gated re-derivation. |
| Technical correctness and evidence grounding | 20 | 19 | Every kernel line, probe and ordering fact re-verified from installed source this session and matches exactly, including the corrected `:1039`. ~40 09-12-plan citations remain gated-not-yet-paid, matching the plan's own honest accounting. |
| Implementation specificity and feasibility | 15 | 14 | Fully literal detail ladder and store/alert shapes; the one open item (fixture shape for the two non-reconciliation timeout tests) is self-named. |
| Acceptance criteria and validation quality | 20 | 19 | Twelve items, including the cross-assertion pinning the emulator-latch discrimination and the citation-table gate. Live proof still lands post-merge (unavoidable for a boot-time artefact). |
| Autonomous operation, failure handling, recovery | 15 | 15 | Cause-agnostic ladder, generic fallback still alerts, no self-healing (reasoned), fail-closed on all three ambiguous walks. |
| Portfolio objective alignment, scope, dependencies | 10 | 9 | Honest zero-ROI framing; the 1-point deduction is the architect's round-2 point (no measured cost to derive the P2 rating from) and is correctly carried forward as permanent rather than re-litigated. |
| **Total** | **100** | **95** | |

## Required changes

- None MATERIAL. Optionally (MINOR, not blocking): name the intended fixture mechanism for driving the two non-reconciliation kernel timeouts in §7 13d step 3b (e.g. a fake clock/port that fails `check_connected()`/`portfolio.initialized` for real rather than by mock, so the "real kernel" claim is fully load-bearing).

## Blockers

R-1 and R-2 (strategy-lead rulings) remain BLOCKERs on 13b/13c, as stated by the plan itself. 13d and 13a remain independently actionable. No new blocker found.
