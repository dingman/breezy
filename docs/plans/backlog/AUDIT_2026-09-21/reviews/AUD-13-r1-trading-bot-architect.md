# AUD-13 review — round 1

Plan: AUD-13-native-venue-reconciliation-from-durable-records.md
sha256: 59d267fc42d14fc5813e8c07275d57477b1a462497a173a9c4248cd6bcdde6a9
Round: 1
Reviewer: trading-bot-architect (execution/portfolio-risk/autonomy lens)

## Claims verified

- `generate_order_status_reports`/`generate_fill_reports` are the two abstract
  Nautilus coroutines, gathered by `generate_mass_status` and consumed by
  `LiveExecutionEngine.reconcile_execution_state` — CONFIRMED via codegraph read
  of `exec/client.py:2500-2548`. Both currently `return []`, each docstring
  correctly states the R-1 gate on `FillReport.commission` and the
  ordering dependency (`live/execution_engine.py:1880-1881`, fill looked up by
  venue order id named on an order report). This is the intended native
  extension point, not a parallel mechanism — CONFIRMED.
- `position_check_interval_secs` prohibition — CONFIRMED as recorded: the
  operator memory index carries "never enable Nautilus
  position_check_interval_secs" verbatim, and
  `tests/contract/test_exec_client_reconciliation_contract.py:184-188` pins
  `position_check_interval_secs is None`. Real, binding, correctly scoped out.
- R-1/R-2 kept as BLOCKERS, not decided — CONFIRMED: §12 states "the 09-12
  plan's recommendations... are input to the ruler, not a decision this plan
  may make," and no code increment (13b/13c) executes without the ruling.
- "Durable fill records" as the source for a VENUE reconciliation — this is
  NOT the bot reconciling against itself: the §3 gating rule (adopted from the
  09-12 plan, `:60-70`) reports a durable record only *iff a fresh venue
  positions read* currently shows an open position for that instrument. The
  venue GET is the ground truth that gates emission; the durable record only
  supplies fields (client_order_id, trade_id) the venue's own order-read API
  cannot attribute to Breezy (`exec/client.py:2519-2525`: "the venue `Order`
  carries no client-order-id field"). This is a legitimate, already-documented
  design compromise forced by a venue API gap, not an invented shortcut — but
  AUD-13 states it terse and relies entirely on the reader opening the 09-12
  plan to see the justification; a reader of AUD-13 alone cannot verify this
  point without a second file. Author's own §13 already names this cost.
- **Citation drift found, NOT caught by the plan's own re-verification.**
  §5 states: "Any change that touches `LiveExecEngineConfig` in
  `runtime/node_config.py:821` is out of scope for AUD-13." At HEAD,
  `LiveExecEngineConfig(inflight_check_interval_ms=0)` is at
  `node_config.py:882`, not `:821` (61 lines drifted). The plan's own §2
  table re-verifies four *other* anchors at HEAD but this one — despite being
  load-bearing for a scope exclusion — was not in that table and is stale.
  MINOR: the exclusion itself is correctly stated in substance (no explicit
  `position_check_interval_secs=` assignment exists anywhere in `src/`,
  confirmed by grep — it remains an honored Nautilus default), so no
  incorrect behavior follows from the wrong line number, but it is exactly
  the class of defect the brief asks reviewers to catch: "a citation that
  does not say what the plan claims."

## Defects

1. **MINOR** — `runtime/node_config.py:821` citation (§5) is stale; the real
   anchor is `:882`. Required change: re-derive and correct before an
   implementing session copies it forward (the plan already warns generally
   that Breezy anchors have drifted, but this specific one slipped past its
   own re-verification pass).
2. **MINOR** — the "durable record sources a VENUE reconciliation" design
   tension is real but under-explained for a reader of AUD-13 alone; a
   two-sentence restatement of the venue-attribution gap (already present
   almost verbatim in the docstrings at `exec/client.py:2519-2525`) would
   make this plan self-contained on its most conceptually unusual point.

No MATERIAL defects found. The native-mechanism claim, the blocker discipline
on R-1/R-2, and the prohibition on `position_check_interval_secs` all hold up
against independent verification (grep, codegraph, LESSONS/memory, contract
test).

## Per-criterion points

- Fidelity to the audit gap and completeness: 17/20 — matches author baseline;
  correctly scoped as an update to SP-3, not a duplicate.
- Technical correctness and evidence grounding: 17/20 — one uncaught citation
  drift (§5, `:821` vs `:882`) found independently; otherwise every
  re-verified claim in §2 reproduces exactly at HEAD.
- Implementation specificity and feasibility: 12/15 — RED test order specified,
  bodies deferred to the 09-12 plan by design.
- Acceptance criteria and validation quality: 18/20 — six falsifiable
  goal-state assertions plus F1-F6; live-proof item lands a day after merge.
- Autonomous operation, failure handling, recovery: 12/15 — fail-closed
  behavior is well specified; no detector for a future regression to `[]`.
- Portfolio objective alignment, scope, dependencies: 9/10 — honest zero-ROI
  framing; P2 rationale is arguable but stated, not hidden.

**Total: 85/100**

## Required changes for full marks

- Correct the `node_config.py:821` → `:882` citation (and re-scan §5/§6 for
  any other uncorrected anchor outside the §2 re-verification table).
- Add a two-sentence self-contained justification for sourcing venue
  reconciliation reports from durable records, so AUD-13 does not require
  opening the 09-12 plan to evaluate its most load-bearing design choice.

## Blockers

- R-1 (fee unit on a reconciled `FillReport`) and R-2 (may a reconciled
  `OrderFilled` reach `on_order_filled`) are strategy-lead rulings, correctly
  named as blockers by the plan itself — not waivable by this review.
