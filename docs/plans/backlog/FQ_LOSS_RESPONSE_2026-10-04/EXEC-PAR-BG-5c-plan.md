# EXEC-PAR BG-5c: wiring the stage-evaluator ports into the node (plan r2)

**Status:** READY r2.1 (r2 confirm reviews: architecture 88, failure-mode 86, market/stats 84; all findings adopted as A1–A7).

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

## r2.1 amendments (binding)

These come from the r2 confirm reviews: architecture 88 READY-with-amendments, failure-mode 86, market/stats 84. Where an amendment conflicts with the r2 text above, the amendment wins.

### A1. R5 is replaced: inject the ledger through the factory

The exec client (`client.py`) is byte-pinned, so a new property on it is rejected. Instead:
- `app/trade.py` constructs the ledger at K>1 only, through a now-public `spend_ledger_for(...)`. This is the factory's existing constructor, with the same arguments, so it cannot diverge from the admitting ledger.
- The ledger is injected through an optional factory config field, following the `submit_intent_latch` precedent.
- At K=1 the field is `None` and the factory builds exactly as it does today. A test asserts the K=1 factory output is unchanged.
- The watcher receives a read-only `SpendLedgerView` protocol (`spent_today_usd`, `cost_budget_bucket`, the predicate methods), never the mutable ledger.
- Mark recording writes through the latch, never through the ledger.
- A stale or non-identical ledger instance gives FAIL `ledger_unavailable`. The check is an identity comparison against the injected instance.

### A2. `spend_unaudited` defers a look; it never fails it

This amends R3.2.
- **Coverage rule.** The Nautilus cache audit is full when `day_start ≥ boot_ts − reconciliation_lookback`. Otherwise it covers only the post-boot span.
- **Restart days.** A restart day is `spend_unaudited` by design.
- **Effect on looks.** `spend_unaudited` **defers** the look: no look is taken, it is not a failed look, and it never counts toward demotion. It clears when the audit covers the day.
- **Unresolved days.** A day still unaudited past `SETTLEMENT_DEADLINE_DAYS` becomes `day_excluded` (§10a), never PASS.

### A3. AMBIGUOUS full-cost term, precisely

This amends R2.3.
- An AMBIGUOUS intent leaves the full-cost term **only when its fill's settled row is persisted**.
- Between fill confirmation and settlement it counts at that fill's `cumulative_cost + fee`.
- An unresolved or zero-fill intent counts at armed notional.
- "Resolved" comes from a venue-evidenced resolution record, not from the mark.
- WP-B verifies BG-1c `_contribution` against these rules and fixes it if they do not hold.

### A4. The floor stub is per station

This amends R1.4.
- For each station, the stub applies to `entry_day(station, floor.ts)`, filtered by `arm_ns ≥ floor.ts`.
- Whole-day counters apply only to station-days that start at or after `floor.ts`.
- **Missing `arm_ns`.** A floor-day row with no `arm_ns` counts as pre-floor-unknown. That makes the station's floor day non-PASS; such a row is never silently included or excluded.
- **BG-5a change.** BG-5a's "strictly after the floor day" becomes "per station: the stub on that station's floor day, then the days after it".

### A5. Open days are evaluated immediately by the halt rules

This amends R1.5.
- These halts evaluate open days immediately: §15 single-day, §15 cumulative, §9, and the §5 intraday halts.
- Only the look minima, the trailing windows and the cap wait for a day to close.
- Open data is re-attributed on every pass.
- An entry whose day is more than 2 days after `today()` gives `counter_missing`.

### A6. The R8 sign rule, unambiguous

This amends R8.2.
- The **held side comes from the instrument or intent** (the NO sibling), never from `order_side` and never from a stored leg sign.
- `payoff = |qty| · outcome(held) − cost_held − fee`.
- For a NO buy recorded by the venue as SELL YES at price y: `cost_held = |qty| · (1 − y)`. Apply exactly one flip.
- Tests pin the sign:
  - against `fq_scorer.py:424`;
  - against one recorded live NO fill;
  - for YES and NO, each settling both ways.

### A7. Mechanics of the R8 executor

- Single-flight per (station, day).
- A read timeout. On timeout the day is `pending`.
- Results are posted back to the loop with `call_soon_threadsafe`.
- The executor shuts down on dispose.
- WP-D confirms that the F2 truth-store format is SQLite before using `mode=ro`. If it is not SQLite, WP-D states the read-only mode it uses instead.

### Status

**READY** for build once the A1–A7 amendments are folded in. A further review round is not required unless a build contradicts this text, in which case the builder STOPs and reports.

## r2.2 build-time notes (from the WP-C reviews; binding)

- **N-A. WP-D: write stub settled-P&L rows.** WP-D writes a settled-P&L row for each per-station floor stub, covering post-floor entries only, alongside the whole-day rows.
  - Until that lands, the evaluator FAILs `settled_pnl_missing` on any floor stub that has post-floor fills or AMBIGUOUS orders. This is fail-closed and intended.
  - The s15 day and stage checks skip floor labels. They may only skip a label once its stub row exists.
- **N-B. WP-E: call the day-convention check at boot.** At K>1, WP-E calls `enforce_day_convention_at_boot` on the boot path and adds a test showing that a K>1 boot calls it.
- **N-C. A5 deviation: intraday halts stay with BG-6.** The §5 Clopper-Pearson, §5 burst and §9 intraday halts stay with BG-6, per the spec's BUILD-GAP table. The daily evaluator feeds open days only into the s7 and s15 checks.
  - BG-6 must evaluate open days immediately.
  - BG-4's `--dry-eval` recomputes the intraday rules (L1) through BG-6's pure predicates.
- **N-D. Name mapping.** The plan's `entry_counts_by_day` and `EntryRow` correspond to `entry_fills_by_day` and `EntryInput`/`OrderAnchor` in the code.

## r2.3 WP-E obligations (from the WP-A/WP-B reviews; binding)

- **E-1. Ledger construction.** Construct the injected ledger with `spend_ledger_for(config)`, using the exact factory arguments. Add a test that the injected ledger's admission/breaker fractions equal the factory's (WP-A review LOW).
- **E-2. Final lapse before stop.** Wire `record_final_lapse_before_stop` into `_close_epoch` before `stop_ts` is written. If the lapse write fails:
  - gappy-mark the affected days directly, or retry;
  - only then write `stop_ts`;
  - log at ERROR.
  A clean `stop_ts` must never hide an unrecorded gap. Also fix the helper's docstring (WP-B confirm MEDIUM).
- **E-3. Spend-audit gating.** The evaluator/runner must honour `SpendAudit.blocks_pass`. Add a test that a non-FULL_MATCH status cannot yield PASS (WP-B confirm LOW).
- **E-4. Durable sources.** Construct `DurableSources` with:
  - `monitor=SpendAuditMonitor(alert_sink=…)`;
  - the latch `anchors` port;
  - a `GovernedDays` that exposes `std_offsets`.
  Map `SourceReadError` to FAIL `stage_eval_fail:source_read:<name>`.
- **E-5. Heartbeat lapses.** Call `record_lapse_if_any(last_hb_ns=…)` before every heartbeat write. The first beat uses the epoch's `boot_ts`.
- **E-6. Day convention.** Covered by N-B: `enforce_day_convention_at_boot` at K>1.
- **E-7. Persist the per-day spend-audit status.** Each pass, write `SpendAudit` status per day to `exec_par/spend_audit/<label>`, recording `{status, ts_ns}`. Status is FULL_MATCH, UNAUDITED, MISMATCH or DURABLE_UNREADABLE. This lets BG-7's read-only report show the deferrals, which it cannot do from the in-memory Nautilus cache (BG-7 review).
- **E-8. BG-8 note.** At K>1 with a live node, an unreadable watcher record pages `WATCHER_DEAD` immediately, with no debounce. This is a coordinator ruling: a false page is preferable to a delayed safety alert.
