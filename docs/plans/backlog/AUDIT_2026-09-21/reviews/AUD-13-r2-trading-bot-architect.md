# AUD-13 review — round 2

Plan: AUD-13-native-venue-reconciliation-from-durable-records.md
sha256: 84befd657aa2ca1fbc4e6d377a00c8a01ea1f18d20ea3fd094447e367a647928
Round: 2
Reviewer: trading-bot-architect (execution/portfolio-risk/autonomy lens)

## Round-1 disposition audit

Both round-1 records (this reviewer 85/100, silent-failure-hunter 77/100) are logged in §13
with per-defect dispositions. Verified against the artefact, not the table's own claims:

- Defect 1 (architect, MINOR, stale `:821` anchor) — CONFIRMED FIXED. `/usr/bin/grep -n
  LiveExecEngineConfig src/breezy/runtime/node_config.py` → `:882`, matching §5's corrected text.
- Defect 2 (architect, MINOR, durable-record-as-venue-source under-explained) — CONFIRMED FIXED.
  §6 now carries the self-contained paragraph, citing `exec/client.py:2519-2525` for the
  no-client-order-id-field claim; independently re-read, the docstring language matches.
- Defect 3 (hunter, MATERIAL, no alert on the boot-halting F5 case) — CONFIRMED FIXED, and this
  is the load-bearing change in this revision (new increment AUD-13d). Independently re-verified
  the entire causal chain from Nautilus source this session (see below) — it holds exactly as
  claimed.
- Defect 4 (hunter, MATERIAL, no 09-11 incident regression test) — CONFIRMED FIXED. §7 13b step 4
  adds `test_the_2026_09_11_order_2_fill_reconciles_on_the_first_boot`, §8 item 4 makes it
  acceptance.
- Defect 5 (hunter, MINOR, design delegated) — PARTIALLY fixed as disposed; reasonable (avoids a
  second, divergent spec).
- Defects 6-7 (self-raised / brief) — CONFIRMED FIXED (counts line; fail-closed semantics for
  read failure / partial parse / disagreement, each independently readable in §6).

No rejected defect in either record; none warranted rejection on independent re-check.

## Claims verified this session (fresh, not carried from round 1)

- **The central new claim — a `False` reconciliation halts the boot before the trader starts —
  independently reproduced from the INSTALLED Nautilus source, not taken from the plan's
  quotation:**
  `.venv/lib/python3.13/site-packages/nautilus_trader/system/kernel.py:1024-1039`:
  ```
  1024  if not await self._await_engines_connected():
  1025      return
  1027  if self.exec_engine.reconciliation:
  1028      if not await self._await_execution_reconciliation():
  1029          return
  1033  self._emulator.start()
  1036  if not await self._await_portfolio_initialization():
  1037      return
  1039  self._trader.start()
  ```
  `_await_execution_reconciliation` (`:1335-1347`) calls `reconcile_execution_state` and on a
  falsy return logs `self._log.error("Execution state could not be reconciled")` and returns
  `False`. CONFIRMED exactly. One trivial drift: the plan states `self._trader.start()` is at
  `:1038`; it is at `:1039` (the `return` is 10 lines above it, not 11). Immaterial — the
  substance (return precedes trader.start(), ERROR-only signal) is exact.
- **The 13d design's core mechanism — that `Trader.start()` publishes a native, observable
  `ComponentStateChanged` on `events.system.*` when it transitions to RUNNING — independently
  verified from Cython source, which the plan does NOT cite explicitly and which I checked as
  the load-bearing assumption behind the whole 13d design:**
  `nautilus_trader/trading/trader.py:54`: `class Trader(Component)`. `Component.start()`
  (`common/component.pyx:1941-1966`) triggers the FSM to `RUNNING` via `_trigger_fsm`, which
  (`:2211-2228`) publishes `ComponentStateChanged(component_id=self.id, state=self._fsm.state,
  ...)` on `topic=f"events.system.{self.id}"` — a glob match for `COMPONENT_STATE_TOPIC =
  "events.system.*"` (`component_health_watch.py:95`, confirmed). This means the 13d design (a
  sibling installer on the same already-subscribed topic, latching whether the trader ever
  published RUNNING) is a genuine native observable, not an invented one. This is the single
  biggest technical-correctness risk in the plan and it holds.
- `install_component_degraded_alert` wiring at `trade_cli.py:421`, `node.run()` at `:438`,
  `_exit_code_for_completed_run` at `:439` — all confirmed exact via codegraph read.
- `operator_controls.py`/contract-pin exclusion on `position_check_interval_secs` — re-confirmed
  present and unchanged from round 1's verification.

## Defects

No MATERIAL defects found this round. One residual, already self-disclosed by the author and
independently confirmed real (not closed by this revision):

1. **MINOR (self-disclosed, independently confirmed, not fully closed)** — the 09-12 plan
   (`RECONCILIATION_NATIVE_REPORTS_2026-09-12.md`) carries roughly 40 additional `file:line`
   citations beyond the one AUD-13 corrected (`:821`→`:882`); the plan states these are
   "flagged-not-fixed" (§13 revision-2 self-score row for technical correctness). AUD-13 warns
   the executing session generically ("every Breezy file:line... has drifted... anchors must be
   re-derived; do not copy them") but does not make citation re-derivation an explicit, gated
   step of AUD-13a/13b. **Required change:** add one line to §7 13b step 6 ("re-derive every
   Breezy-side citation in the 09-12 plan's §3 field maps before implementing the generator
   bodies, and record the corrected set") so the warning becomes a checked step rather than
   prose the implementer could skip under time pressure.

## Per-criterion points (cap: 20/20/15/20/15/10)

- Fidelity to the audit gap and completeness: 20/20 — G-10 fully covered; 13d closes the
  boot-halt gap the source finding implies but does not name, independently re-verified as real
  and correctly scoped as P1/independent of the ruling-blocked increments.
- Technical correctness and evidence grounding: 19/20 — every re-checked claim reproduces exactly
  at HEAD, including the one claim (native `ComponentStateChanged` publication) this review
  verified from Cython source that the plan itself does not cite to that depth. Withheld 1 point
  for the named, still-open ~40-citation residual above (a concrete required change is named).
- Implementation specificity and feasibility: 14/15 — 13d is fully specified down to the
  observation seam and alert shape; 13b/13c's test order and fail-closed walks are named. Withheld
  1 point for the same residual (the field maps an implementer will actually copy from still
  carry unverified anchors).
- Acceptance criteria and validation quality: 20/20 — eleven falsifiable items including the
  incident replay, the false-positive guard (zero boot-halt alerts on a normal boot), and "an
  empty list must carry a reason code, never an unlabeled `[]`."
- Autonomous operation, failure handling, recovery: 15/15 — F1-F6 fall closed with latched
  reasons and alerts; F5 (the boot-halting case) is now a delivered CRITICAL with a real-engine
  test, independently confirmed against Nautilus's actual early-return structure; a silent
  regression to `[]` is now detectable by a contract-pinned counts line; no unwarranted
  self-healing is added.
- Portfolio objective alignment, scope, dependencies: 9/10 — honestly framed as zero demonstrated
  ROI / a precondition for honest measurement; the P1(13d)/P2(13a-c) split is well-reasoned and
  matches the evidence (bot hasn't traded since 09-15, so correctness debt is the right framing);
  1 point withheld only because the P2 rationale, while stated, remains an argued priority call
  rather than one derived from a measured cost, matching this reviewer's round-1 assessment.

**Total: 97/100**

## Required changes for full marks

- Make the ~40-citation re-derivation in the 09-12 plan an explicit, checked step inside AUD-13's
  own §7 (not merely a generic warning), so the residual named in the author's own §13 self-score
  is closed rather than carried forward again.

## Blockers

- R-1 (fee unit on a reconciled `FillReport`) and R-2 (may a reconciled `OrderFilled` reach
  `on_order_filled`) remain correctly named, undecided strategy-lead rulings blocking 13b/13c
  only. Not waivable by this review. 13d has no blocker and is independently actionable.
