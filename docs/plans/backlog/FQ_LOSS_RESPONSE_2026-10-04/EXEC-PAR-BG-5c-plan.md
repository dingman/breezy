# EXEC-PAR BG-5c: wiring the stage-evaluator ports into the node (plan r2)

**Status:** PROPOSED r2. Awaiting confirmation review.

**Inputs**
- r1 (3930f19e) peer reviews, all NOT-READY:
  - architecture: 71
  - failure-mode: 72
  - market/stats: 78
- Every HIGH finding is adopted below. The table at the end lists the dispositions.

**Spec:** D-PREREG r4 + r4.1–r4.5, plus `EXEC-PAR-BG-integration-notes.md`.

**Scope:** supply every `stage_eval_ports` member from durable sources, at configured K>1 only.

**K=1 must stay byte-identical:**
- no new module is imported on the K=1 path;
- nothing is constructed, read or opened (no files, no DB connections) at K=1.

## R1. Day attribution: one convention, one atomic migration

1. **One module.** `runtime/exec_par_governed_days.py` exports:
   - `entry_day(station, arm_ns) -> str`: the per-station climate day under the station's **standard-time** offset (`domain/climate_day.py`, `std_utc_offset_hours`; never the DST wall clock).
   - `open_days_at(ts_ns) -> frozenset[str]`: every governed station's open climate day at `ts`.
   - `today(ts_ns) = min(open_days_at(ts_ns))`.
2. **Entries carry their station.** `FillRecord` and `EntryRow`, and any row the evaluator reads, carry `station`. Attribution always goes through `entry_day`.
3. **Every station-less day function is retyped. No `Callable[[int], str]` remains on an attribution path.** Sites to change:
   - `exec_par_counter_ingest`;
   - `exec_par_reconcile.gappy_days` and `entry_counts_by_day`;
   - `stage_day_labels` and `_first_k_gt1_day`;
   - `StageSnapshotInputs.day_of_ns` (`exec_par_stage_types.py:226`);
   - `StageEvalPorts.day_of_ns` (runner);
   - `exec_par_stage_eval.py:164`;
   - `exec_par_stage_snapshot.py:137`;
   - `settled_pnl_by_day`.

   **Instant-only callers** (boot, floor, gap span) use `open_days_at`.
4. **Floor membership** follows the spec, §1: `arm_ns ≥ floor.ts`.
   - **Floor day:** the snapshot builds it from per-entry rows filtered by `arm_ns`. This is the "floor-day stub". If a counter row lacks `arm_ns`, WP-C adds it.
   - **Other days:** every other stage day uses whole-day counters.
   - **Amends BG-5a:** "stage = days strictly after the floor day" becomes "post-floor stub + days after". The stub obeys the same rules, so a pre-floor loss can never re-trip a stop.
5. **Mixed-offset nights.** An entry whose `entry_day > today()` is open data:
   - it enters §15 cumulative and the intraday rules;
   - it never enters closed-day trailing windows, look minima, the cap, or the daily trigger until its day closes.
6. **Atomic migration.**
   - Ingest, reconcile, snapshot, evaluator and driver migrate in one merge (WP-C).
   - A property test over boundary instants pins all of them to `entry_day`: midnight per station, std versus DST, earliest and latest station.
   - A grep test forbids `day_of_ns` in `runtime/exec_par_*`.
   - No persisted rows need re-keying: K>1 counters have never been written in production.
   - The first K>1 boot writes `exec_par/day_convention = {v:2}`.
   - A boot that finds `v` ≠ 2 refuses K>1: force K=1 and raise a CRITICAL alert.

## R2. AMBIGUOUS orders

1. **Source.** The BG-1b ever-ambiguous mark rows are the source. Marks are entry-only. The resolver context and retirement reasons are never used.
2. **Attribution.**
   - §5 numerator and §5 burst use the mark's stored **arm_ns**, never the write time or the ack time.
   - §5 denominator = posted entries under the same R1 attribution and stage-window filter.
3. **§15 full-cost term**, owned by BG-1c `_contribution` (`exec_par_settled_pnl.py:181-183`):
   - each unresolved AMBIGUOUS entry counts at its **armed notional**;
   - an intent whose fill already appears in the settled accumulator is dropped from the full-cost term, so nothing is double-counted;
   - a zero-fill AMBIGUOUS entry counts at armed notional until it is resolved.
   - WP-B verifies this behaviour with a test, and fixes it if it is not true.

## R3. Spend reconciliation

1. **Spend** = Σ over entry orders of the cost on the order's **terminal** durable fill record (the one with max `cumulative_qty`), keyed by `entry_day`. Never Σ `cumulative_cost` across partial fills.
2. **Independent audit.** Spend is compared against the Nautilus cache's order-fill events, the independent source.
   - If that source is unavailable, or covers the day only partly, the day reports `spend_unaudited`. That status is never green, and it is a look blocker.
   - A mismatch is a reconcile mismatch, handled through the BG-1d rebuild/exclusion path.
3. **What this does not catch.** The counter-versus-durable check alone cannot detect a fill that is missing from both. The cache audit exists to cover that case.

## R4. §7 serial parity

1. §7 parity has no halt role. It is "≤ 0.005 when ≥20 K=1 fills, otherwise report-only".
2. The node reports `parity_unavailable` as **report-only**. It is **never** in `look_blockers`, because blockers record failed looks and two FAILs demote.
3. BG-10(f) is the sole parity gate before any promotion. It computes parity offline from pre-window K=1 fills and decision asks, using the analysis join, which is legal offline only.
4. **Spec-delta item:** this goes into the D-PREREG fold as r4.6, with the BG-10(f) scope added.

## R5. Ledger handle

1. Add a public read-only `spend_ledger` property on the exec client. Today the ledger is `self._ledger`.
2. The watcher reads it lazily through the existing `exec_client_getter` (`breaker_watcher.py:751`).
3. No factory or config change. K=1 is untouched.
4. This one ledger serves the §15 predicates, mark recording and ingest. It is the same instance the client admits against.

## R6. Readiness probe

1. Ready = all three of:
   - `exec_engine.reconciliation is True`;
   - `watcher.is_running`;
   - **no reconciliation refusal latched** on the client, read through the existing `_exec_client_reconciliation_refusal_reader` (`trade_cli.py:460`).
2. Why the refusal check: `generate_mass_status` (`client.py:5047`) returns an empty status and latches a refusal on error, so the kernel's "reconciled" alone is not evidence.
3. Not ready past `T_ready` = 300 s after boot raises a CRITICAL alert, and every K>1 pass stays blocked. Readiness never defaults to ready.
4. Test: `generate_mass_status` raises, and the probe stays not-ready.

## R7. Gap marking

1. **Two triggers.** Marking runs at **boot** (any prior epoch without `stop_ts` marks its span) **and** on **each reconcile pass**, which covers in-run heartbeat lapses over the bound.
2. **Gap spans.** Each span marks **every governed open day it overlaps** (`open_days_at` at both ends and every day between).
3. **Heartbeat history.** It must be an append-only durable series. WP-B verifies this. If it is a single overwritten row, WP-B adds an append-only lapse record, written by the watcher tick when `now − last_tick` exceeds the bound.
4. **Idempotent and ordered.** Marking is idempotent, and it runs before the first counter ingest at boot.
5. **Failure handling.**
   - A marking write failure at boot refuses K>1: force K=1 and raise a CRITICAL alert.
   - A marking write failure in-run withholds the heartbeat, and the affected days stay non-PASS until the mark lands.

## R8. Settled-P&L driver

1. **Truth source.** Final outcomes come only from the NWS CLI-sourced durable truth: the F2 truth store written by the live timers is preferred over the raw catalog.
   - A void, cancelled, missing or non-final outcome gives `pending`, or `overdue` past `SETTLEMENT_DEADLINE_DAYS`. Never zero.
   - A revised CLI value invalidates the cache entry.
2. **Payoff** = `qty · outcome_of_held_side − cost − fee`.
   - For a NO holding the venue records as SELL/BUY_SHORT of YES, the held-side outcome is `1 − outcome_YES`. Apply the leg sign first, per the venue netting a NO holding as short YES.
   - A test pins the sign for a YES entry and a NO entry, each settling both ways.
3. **Execution.**
   - Truth reads run via `loop.run_in_executor` with their **own read-only connection** (sqlite `mode=ro` via `Path.as_uri()`), posting results back to the loop.
   - Only final outcomes are cached.
   - Triggers: `settled_pnl_seq` and the daily pass.
   - Persistence goes through `persist_settled_pnl`.

## Port failure contract

| Port | Raises / times out | Returns None | Stale |
|---|---|---|---|
| Durable-source scan | `counter_missing` → FAIL; look blocked. Never zero. | FAIL `counter_missing` | n/a (read per pass) |
| Empty scan | Distinguished from failure: the empty result carries `ok=True` | — | — |
| Truth read | Day `pending` / `overdue`; settled row unwritten | Same | Re-read on trigger; overdue past deadline |
| Readiness probe | Not ready | Not ready | CRITICAL at `T_ready`; passes blocked |
| Gap marking | Boot: force K=1 + CRITICAL. In-run: heartbeat withheld. | Same as raise | n/a |
| Ledger handle | FAIL `ledger_unavailable` | FAIL | n/a |
| Cache audit (R3) | `spend_unaudited` → look blocker | Same | Same |

Every row also obeys BG-5b's last-resort FAIL.

## Work packages and order

| WP | Content | Depends on |
|---|---|---|
| C: governed days + atomic R1 migration | Includes the floor-day stub and the convention row | Merged BG-5b fixes (C rebases onto them) |
| A: ledger property (R5) | — | — |
| B: durable sources | R2, R3 with cache audit, R7 lapse record, `counters_expected` from epochs | C |
| D: settled-P&L driver | R8 | B, C |
| E: integration | `app/trade.py` `_build_stage_eval_ports` in the K>1 branch only, with lazy imports; R6; R7 caller; `build_exec_watcher` forwards `counters` and `ambiguous_marks` | A–D |

**E's obligations:**
- Keep BG-5b's unwired guard **per member**: if any single port is None at K>1, force K=1 and raise `EXEC_PAR_STAGE_EVAL_UNWIRED`. Test it.
- Add a K=1 test asserting that no new `exec_par_*` module is imported and that no files or DB connections are opened.

**Activation:** BG-6 must be merged before any K>1 operation.

## r1 review dispositions

| Review | Findings | Disposition |
|---|---|---|
| Architecture | F1 R6 → R6.1–4; F2 R1 → R1.1–3; F3 R5 → R5 (smaller property route chosen); F4 R8 → R8.3; F5 dependencies → WP table; F6 → R4.4 | All adopted |
| Failure-mode | F1 R7 → R7; F2 → port contract table; F3 → R1.6; F4 → E obligations; F5 → R3.2–3; F6 → E obligations; F7 → R4.2 | All adopted |
| Market/stats | R3 → R3.1–2; R2 → R2.2–3; R1 → R1.1, 4, 5; R4 → R4.2; R8 → R8.1–2 | All adopted |
