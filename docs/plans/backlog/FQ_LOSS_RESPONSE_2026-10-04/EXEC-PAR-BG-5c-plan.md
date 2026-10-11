# EXEC-PAR BG-5c: wiring the stage-evaluator ports into the node (plan r1)

**Status:** PROPOSED, awaiting peer review.

**Base.** The BG-5b blueprint (code-architect, 2026-10-11) over BG-5b `de47430a`. BG-5b is still in its review-fix round. That round adds:
- the K>1 unwired guard, which forces K=1 and raises `EXEC_PAR_STAGE_EVAL_UNWIRED`;
- the `settled_pnl_seq` trigger port.

**Spec.** D-PREREG r4 + r4.1–r4.5, plus `EXEC-PAR-BG-integration-notes.md`.

**Scope.** Supply every `stage_eval_ports` member from existing durable sources, at configured K>1 only. K=1 must stay byte-identical: nothing below is constructed or read at K=1.

## Rulings

### R1. Day attribution uses one convention

This addresses blueprint gap 4, which is the highest K>1 risk.

1. **Entry day.** Every entry is attributed to `climate_day_for_instant(station_of(entry), arm_ns)`, the per-station climate day of its arm time. The same function is used in all four places:
   - BG-1b ingest;
   - BG-1d reconcile;
   - the BG-5b snapshot;
   - the settled-P&L driver.
   The single-argument `day_of_ns` is **removed from attribution paths**.
2. **`today`.** `today` is the earliest still-open climate day across the governed stations. This is the same notion as the BG-5b daily trigger.
3. **Floor day.** For a reset at `ts`, the floor day is the earliest open governed day at `ts`.
4. **One implementation.** `runtime/exec_par_governed_days.py` is the single implementation. A test pins all four call sites to it.

### R2. AMBIGUOUS count source

- **Source.** The count comes from the BG-1b ever-ambiguous mark rows (`ambiguous/<day>/<intent_id>`, with acks). That is the source already ruled for BG-1b.
- **Rejected source.** It never comes from the resolver context or the retirement reason. The 10-10 BG-1b review found that the resolver context does not discriminate AMBIGUOUS, and a with-id resolve can complete in under 5 s.

### R3. Ledger spend for reconcile

- **Source.** Spend is the sum of entry `cumulative_cost` over the day's durable fill records. The in-memory `DailySpendLedger` is UTC-day-only and not durable.
- **Known limitation.** This figure is not independent of the fill count. The reconcile spend check is therefore a consistency check (counter versus durable records), not an independent audit. This is recorded in the integration notes.

### R4. Serial baseline (§7 parity)

- **In the node.** The node reports `parity_unavailable` (`serial_baseline = None`), and §7 parity becomes a look blocker that is computed **offline** by BG-10(f).
- **Why this is allowed.** The node never promotes (r4.5 O5), and parity is only a promotion input.
- **Consequence.** BG-10(f) scope gains the §7 serial-parity computation, from the pre-window K=1 fills plus the decision asks in the existing analysis join. That join is legal offline and banned on the live path.

### R5. Ledger handle

- **At K>1 only.** `app/trade.py` constructs the single `DailySpendLedger` and injects it into the exec-client factory, using an optional config field. This avoids a second ledger instance.
- **At K=1.** The field is `None`, so the factory builds exactly as it does today.
- **What uses this handle.** The predicates (§15), the ambiguous-mark recording and the ingest all use it.

### R6. Mass-status gate

- **Readiness probe.** `exec_engine.reconciliation is True and watcher.is_running`. Nautilus starts actors only after execution reconciliation returns True (`kernel.py:1027-1040`), so this is the native signal.
- **No custom wait.** `await_ready` is `None`.

### R7. Gap marking

`compute_gap_spans` gets a caller in the K>1 boot path. Two inputs feed it:
- **Prior boot without a `stop_ts`** (BG-2 epoch row). The span from that boot's last heartbeat to now is gappy-marked, which is case (b).
- **Heartbeat lapses** over the spec bound, which is case (a).

### R8. Settled-P&L driver

- **Inputs.** Outcomes come from the catalog's settled truth (`persistence/catalog.py`). NO legs use the flipped sibling, following the integration notes on entry/exit discrimination.
- **Caching.** Final outcomes are cached per (station, day), so catalog reads stay off the hot loop. A read is triggered only by `settled_pnl_seq` or the daily pass.
- **Persistence.** Results are written through `persist_settled_pnl`, the monotonic BG-1c row.

## Work packages

| WP | Files | Depends on |
|---|---|---|
| A: ledger injection | `adapters/polymarket_us/factories.py` and a config field | — |
| B: durable sources | new `runtime/exec_par_durable_sources.py` (entry fill count, slot counts per R2, spend per R3, `counters_expected` from epochs) | — |
| C: governed days | new `runtime/exec_par_governed_days.py`, plus the R1 call-site migration in ingest, reconcile and snapshot | — |
| D: settled-P&L driver | new `runtime/exec_par_settled_pnl_driver.py` | B, C |
| E: integration | `app/trade.py` `_build_stage_eval_ports` (K>1 branch only), the R6 probe, the R7 caller, and `build_exec_watcher` forwarding `counters` and `ambiguous_marks` | A–D |

- **Parallelism.** A, B and C are built in parallel. Then D, then E.
- **Testing.** Each package follows TDD, a review, the full gate, then merge.
- **Merge.** E is the only package that changes boot. It merges after the BG-5b fixes and before BG-6.

## Risks

- **K=1 inertness.** A test boots at K=1 and asserts zero new reads and no ledger or mark changes.
- **Loop blocking.** Catalog reads are cached. The `stage_eval_slow` span covers the whole synchronous pass (BG-5b fix item 7).
- **Thread confinement.** All reads go through the latch's own store connection.
- **Exec import pin.** New tests that import `DurableFillRecord` need a WIDENED x1 row.
- **Activation ordering.** BG-6 must land before any K>1 operation.
