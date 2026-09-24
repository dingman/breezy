# AUD-13 — Fill the two Nautilus report generators so a boot rebuilds its book from Breezy's durable records, and make a failed reconciliation announce itself

## 1. ID and actionable title

**AUD-13** — Implement `generate_order_status_reports` / `generate_fill_reports` on the
Polymarket.us execution client so `LiveExecutionEngine` reconciliation rebuilds the node's
order/position book from Breezy's own durable fill records, instead of returning `[]` and
letting Nautilus infer an `EXTERNAL` position — **and make the one reconciliation outcome that
stops the node booting (a `False` return) reach the operator as a CRITICAL alert.**

**This item UPDATES existing PROGRESS item `SP-3` (B1/B2 half) — it does not duplicate it.**
Plan of record stays `docs/plans/RECONCILIATION_NATIVE_REPORTS_2026-09-12.md` (Rev 1 + the
Rev 2.1 execution dispositions appended at `:144-166`). AUD-13 adds one increment (13d, the
boot-halt alert) to that design, re-verifies the rest against HEAD, states what has drifted,
and specifies the ruling-unblock path so the item can actually execute.

## 2. Source finding and class

- **Gap:** G-10 (`docs/evidence/AUTONOMY_ROI_AUDIT_2026-09-21.md:78-81`). Verdict **FALSE**
  (coordinator-verified for the stubs, agent-reported for the 09-11 fill narrative).
- **Evidence refs:** `src/breezy/adapters/polymarket_us/exec/client.py:2500-2548`;
  `docs/core/PROGRESS.md:54` (SP-3 row), `:70-71` (rulings R-1/R-2);
  `docs/plans/RECONCILIATION_NATIVE_REPORTS_2026-09-12.md` §1-§9.
- **Class:** **integration failure** (the generators), plus an **autonomous-operation failure**
  (the boot-halt path is a bare log line). The native extension point exists, is called, and is
  wired; Breezy's two coroutine bodies are empty. Nothing is missing from Nautilus.

**Re-verified at HEAD on 2026-09-21 (measured this session, round 2):**

| Claim | Status at HEAD |
|---|---|
| Installed Nautilus is 1.231.0 | TRUE — `.venv/lib/python3.13/site-packages/nautilus_trader-1.231.0.dist-info` |
| `generate_mass_status` gathers the three generators | TRUE — `live/execution_client.py:440`, gather at `:500-502` |
| Engine consumes the mass status | TRUE — `live/execution_engine.py:1670` `reconcile_execution_state`, `:1857` `_reconcile_execution_mass_status`, `:3038` `_reconcile_order_report`, `:3109` `_resolve_client_order_id`, `:3321` `_reconcile_fill_report`, `:3400` `_check_and_skip_duplicate_fill` |
| Breezy's two bodies still `return []` | TRUE — `exec/client.py:2500` and `:2530` (the 09-12 plan cited `:1946`/`:1961`; **the anchors have moved ~554 lines — every file:line in the 09-12 plan must be re-derived before editing**) |
| `_has_durable_fill_record` still a stub | TRUE — now at `exec/client.py:1436` (09-12 plan cited `:1128-1131`) |
| **A `False` reconciliation halts the boot before the trader starts** | **TRUE — `NautilusKernel.start_async()`, `.venv/lib/python3.13/site-packages/nautilus_trader/system/kernel.py:1026-1029`: `if self.exec_engine.reconciliation: / if not await self._await_execution_reconciliation(): / return` — the `return` (`:1029`) is ten lines ABOVE `self._trader.start()` at `:1039` — **`start_async()`, not the sync `start()`**: the sync variant (`:989-1001`) has NO guards at all and runs `_emulator.start()`/`_initialize_portfolio()`/`_trader.start()` unconditionally. Breezy only ever reaches the guarded variant, via `TradingNode.run()` (`live/node.py:283`) awaiting `self.kernel.start_async()` (`live/node.py:349`) — verified from installed source this revision. `_await_execution_reconciliation` (`:1335-1348`) calls `reconcile_execution_state`, and on a falsy return emits `self._log.error("Execution state could not be reconciled")` and returns `False`. That ERROR line is the ONLY signal.** |
| `LiveExecEngineConfig` anchor in Breezy | **CORRECTED — `runtime/node_config.py:882` (`LiveExecEngineConfig(inflight_check_interval_ms=0)`). The round-1 text said `:821`; that was stale by 61 lines.** |

## 3. Current behaviour, required behaviour, concrete gap

**Current.** At every boot `LiveExecutionEngine.reconcile_execution_state` asks the client for
a mass status. Breezy returns zero order reports and zero fill reports; only the position
report path produces anything. The engine therefore cannot resolve a client order id
(`_resolve_client_order_id` synthesises a `ClientOrderId(UUID4().value)`), attributes the
position to `StrategyId("EXTERNAL")`, and generates an *inferred* `OrderFilled` priced from
whatever the positions page says. Our own durable evidence — client order id, cumulative qty,
cumulative cost, trade id, order qty, fee and fee-reconciliation flag — is on disk and unused.
**And if reconciliation ever returns `False`, the kernel returns out of `start_async()` before the
trader starts: the process is up, the unit is `active (running)`, and nothing trades. The only
trace is one Nautilus ERROR line in a log file.**

**Required.**
1. After any boot that inherits an open venue position, the book is built from Breezy's durable
   records: ≥1 order report and ≥1 fill report in the mass status, zero
   `Generated inferred OrderFilled` lines, the real `client_order_id` on the resulting order,
   and exactly one `Position` per instrument. The six falsifiable goal-state assertions are
   already written at `RECONCILIATION_NATIVE_REPORTS_2026-09-12.md:20-28`; AUD-13 adopts them
   verbatim.
2. **A boot that dies in reconciliation emits a CRITICAL alert through the existing sink** —
   not a log line. This repo has already paid for the difference: a detector without delivery
   is not a control (`READINESS_AUDIT_2026-09-12.md`; alerts-reach-nobody cost 3 days + 11 h of
   silent halt before `f97c26f` on 09-20).
3. The 09-11 order-2 shape — a fill that existed as a durable record before any reconciling
   boot — reconciles on the **first** boot, not the second.

**Concrete gap.** Two empty coroutine bodies; one missing boot-completion alert; two
strategy-lead rulings that gate one expression inside the bodies (`commission=`) and one
config field.

## 4. Priority, rationale, dependencies, execution order

**Priority: 13d = P1; 13a/13b/13c = P2.**

Rationale, stated honestly: the reconciliation defect is real and it has already produced one
observed wrong outcome (order 2's 09-11 fill surfaced only after the 09-12 relaunch). But the
bot has not placed an order since 2026-09-15T20:12:06Z and 100% of decisions die upstream of
pricing (G-01). A reconciliation fix changes nothing about whether the bot trades. It is
**correctness debt on the execution spine that must be paid before n grows**, not a path to
ROI — and it is on the critical path for any future item that reads a `Position` or a
realized-PnL figure (AUD-16's live-count verification, and any portfolio-ROI measurement).

**13d is P1 and is separated for exactly that reason:** it is valuable *today*, against
today's `return []` behaviour, because the boot-halt path already exists and is already
silent. It needs no ruling, touches neither generator, and must not wait behind R-1/R-2.

**Dependencies:**
- **13d: none.** No ruling, no other AUD id. It depends only on the alert egress shipped in
  `f97c26f` (already merged) — re-verify delivery at execution time (§7).
- **13b: R-1 is RULED — no longer blocked.** `docs/evidence/RULING_venue_reconciliation_R1_R2_2026-09-21.md`
  (Revision 3, peer-ENDORSED with no required change —
  `docs/evidence/reviews/RULING_R1_R2_review_2026-09-21.md:164`) rules **O4**: recorded venue fee
  where present, else a modelled fee whose θ is resolved **as of `record.ts_event`**. 13b now
  carries the B0 field and schedule work that ruling requires (§5, §6, §7).
- **13c: R-2 is RULED — no longer blocked, but gains a harder condition.** The same artefact rules
  **R2-B conditional on three items** (§4 of the ruling), not the one the 09-12 plan named: the
  increment-C characterisation test green; the `order_side` design defect closed; and `feeSource`
  threaded first.
- AUD-16 consumes AUD-13's output but does not block it. AUD-14b's day-2 self-check escalation
  would *eventually* surface a node that never subscribes, but only after up to a day — 13d
  exists so the boot-halt is not routed through that latency.

**Execution order:** 13d (ship first, independently) → 13a (now a *verification* package, not a
ruling package — the ruling exists) → 13b (B1, in the ruling-mandated build order below) → 13c (B2).

**Required build order inside 13b/13c, set by the ruling and not reorderable:**
1. **B0 field + `feeSource`** — `fee_coefficient_at_fill: Decimal | None` on `DurableFillRecord`,
   written at both fill sites, plus the `feeSource` field. Ruling §4, §6.
2. **Order-side fix** — reports take `order_side` from `record.order_side`
   (`exec/client.py:670`), never a hardcoded `BUY`. Ruling finding 8.
3. **Increment C characterisation test green** — R-2 condition 1.
4. **13b (B1)**, then **13c (B2)**. 13c may not ship until items 1-3 are all done and green.

## 5. Scope and explicit exclusions

**In scope (split a/b/c/d):**

- **AUD-13d** — CRITICAL alert on a reconciliation that halts the boot. No ruling, no generator
  change. Independently actionable today.
- **AUD-13a** — the R-1/R-2 package. **The ruling has since been issued and ENDORSED**
  (`docs/evidence/RULING_venue_reconciliation_R1_R2_2026-09-21.md`), so 13a is no longer a
  ruling-submission step: what remains of it is the read-only verification work the ruling
  still depends on (the store read, the 09-12 citation table, the UNVERIFIED-item re-derivation).
  Read-only + one note under `docs/evidence/`. Independently actionable, no code.
- **AUD-13b** — increment B1 of the 09-12 plan: both generators, over a memoised positions
  read, under the §3 gating rule. **Now also carries the two pieces the ruling made
  prerequisites:** the B0 `fee_coefficient_at_fill` field plus `feeSource`, and the
  `order_side`-from-record fix. R-1 is RULED (O4).
- **AUD-13c** — increment B2: `external_order_claims` on the composition. R-2 is RULED (R2-B)
  **conditional** on increment C green, the order-side fix landed and green, and `feeSource`
  threaded — all three, not just C.

**Explicitly excluded:**

- Enabling `open_check_interval_secs` or **`position_check_interval_secs`**. This prohibition
  is **VERIFIED as recorded**, not assumed: `RECONCILIATION_NATIVE_REPORTS_2026-09-12.md:97`
  names it a non-goal because those pollers re-arm the settlement-zero FLAT landmine via
  `_create_flat_position_report`, and it is contract-pinned by
  `tests/contract/test_exec_client_reconciliation_contract.py:184-188`
  (`test_the_settlement_landmine_stays_disarmed_only_while_the_position_check_is_off`, pinning
  `position_check_interval_secs is None`). The memory index also carries it ("never enable
  Nautilus `position_check_interval_secs`"). **Any change that touches `LiveExecEngineConfig`
  at `runtime/node_config.py:882` is out of scope for AUD-13** — note the anchor: `:882`, not
  the `:821` this plan carried in round 1.
- Enabling the in-flight poller (`inflight_check_interval_ms=0`, L-36).
- `_has_durable_fill_record` (`exec/client.py:1436`) — still a stub, still out of scope.
- Any change to PREREG v3 §3/§5/§9 semantics, to `classify_create_order_outcome`, or to
  `submit_chain.py`.
- **Auto-recovery from a failed reconciliation.** 13d *reports*; it never retries, never
  disables reconciliation to get the node up, and never mutates a durable record to make a
  reconciliation pass. A node that cannot reconcile must stay down and loud.
- Pruning old fill records; the alert sink itself; any exit/flatten path.

## 6. Proposed changes grounded in inspected code

**Native mechanism reused (null hypothesis verdict: NATIVE-SUFFICIENT, build nothing).**
`ExecutionClient.generate_order_status_reports` / `generate_fill_reports` /
`generate_position_status_reports` are the three abstract coroutines
(`live/execution_client.py:371,394,417`, each raising `NotImplementedError` in the base) that
`generate_mass_status` (`:440`) gathers at `:500-502` into an `ExecutionMassStatus`.
`LiveExecutionEngine.reconcile_execution_state` (`:1670`) consumes it. Breezy implements the
third and stubs the first two. **This is the intended extension point; nothing is patched,
forked or reimplemented.**

**Why a DURABLE LOCAL record is a legitimate source for a VENUE reconciliation — stated here so
this plan is evaluable without opening the 09-12 plan.** The venue's own order-read API cannot
attribute an order to Breezy: the Polymarket.us `Order` object carries **no client-order-id
field** (`exec/client.py:2519-2525`, quoting `reports.py`'s module docstring item 2), so an
order enumerated from the venue alone can only be reported with `client_order_id=None`, which
makes native reconciliation adopt it as `EXTERNAL` — the very outcome this item exists to
remove. Breezy's durable fill record is therefore the only place the client-order-id ↔ venue-id
binding exists. **It is not, however, the authority on whether the position is still open.**
The §3 gating rule makes the *venue* that authority: a durable record is reported **iff a fresh
venue positions GET currently shows an open position for its instrument**. The venue decides
*whether*; the local record supplies *which order and at what price*. That is why this is not
the bot reconciling against itself — it is a venue-gated reconciliation enriched with the one
field the venue API cannot return.

**Files touched (13d):** `src/breezy/runtime/trade_cli.py` only (one watch install beside the
existing ones at `:413-434`, and one post-`node.run()` check at `:438`).
**Files touched (13b):** `src/breezy/adapters/polymarket_us/exec/client.py` only — the two
coroutine bodies at `:2500` and `:2530`, plus one memoised positions-read helper.
**Files touched (13c):** one `external_order_claims` field on
`src/breezy/strategy/current_rung_hold/composition.py` (claims register at
`nautilus_trader/trading/trader.py:435`, before `build()`/`run()`).

**13d — how the boot-halt is observed without touching Nautilus.** Breezy cannot intercept
`kernel.start_async()`'s early `return` (kernel.py:1026-1029) and must not try. Two native
observables already exist and 13d uses both:
1. **The component-state bus.** `COMPONENT_STATE_TOPIC = "events.system.*"`
   (`runtime/component_health_watch.py:95`) is a `MessageBus` glob already subscribed by
   `install_component_degraded_alert`, wired at `trade_cli.py:421` immediately after
   `node.build()`. A new sibling installer latches whether the **trader** component ever
   published a `RUNNING` transition.
2. **`node.run()` returning.** `trade_cli.run` already calls `node.run()` at `:438` and then
   `_exit_code_for_completed_run(stderr)`. If `run()` returns with the latch never set, the
   trader never started — the boot died in `start_async()`.
On that condition 13d emits **one** CRITICAL through the existing sink, in exactly the shape
`app/trade.py:399-407` already uses for a refused live-trading permit:
`emit_alert(resolve_alert_sink(), AlertPayload(severity="CRITICAL", event=<new fixed event>,
site="global", detail=<fixed enum string>))`. Binding constraints:
- `detail` is a **fixed enum string**, never exception text, never a value-bearing string
  (`TRADE_NODE_DAILY_RELAUNCH_2026-09-04.md:151-153`).
- The alert must fire for **any** trader-never-started boot, not only a reconciliation failure.
  `NautilusKernel.start_async()` has **three** early returns before `self._trader.start()`, read
  verbatim from the installed source this session
  (`.venv/lib/python3.13/site-packages/nautilus_trader/system/kernel.py:1024-1039`): `:1025`
  (engines not connected), `:1029` (reconciliation returned `False`, guarded by
  `if self.exec_engine.reconciliation:` at `:1027`), `:1037` (portfolio not initialised), with
  `self._trader.start()` at **`:1039`** — the plan's earlier `:1038` was one line off and is
  corrected here. **The guards are in `start_async()` only.** The sync `NautilusKernel.start()` (`:989-1001`) has no early return at all — a reader who greps `def start(` in isolation finds the unguarded method and would wrongly conclude 13d's premise is false. Breezy reaches the guarded variant through `TradingNode.run()` (`live/node.py:283`), which awaits `self.kernel.start_async()` (`live/node.py:349`); `trade_cli.run` calls `node.run()` at `:438`.
- **The detail-enum resolution is SPECIFIED, not asserted — an ordered ladder over three native
  probes, evaluated after `node.run()` returns, never by parsing Nautilus log text.** The three
  probes are the ones the kernel itself uses in its own timeout diagnostics, so no new observable
  is invented:
  1. `data_engine.check_connected()` / `exec_engine.check_connected()` (`cpdef bint`,
     `data/engine.pyx:324`, `execution/engine.pyx:276`; the kernel reads exactly these two at
     `kernel.py:1313-1314`). Either false ⇒ `BOOT_HALT_ENGINES_NOT_CONNECTED` (`:1025`).
  2. Otherwise, **did `OrderEmulator` ever publish `RUNNING`?** `_emulator.start()` sits at
     `:1033`, *between* the reconciliation return and the portfolio return.
     `OrderEmulator(Actor)` (`execution/emulator.pyx:81`) and `Actor(Component)`
     (`common/actor.pyx:128`), so its `start()` publishes `ComponentStateChanged` on
     `events.system.OrderEmulator` — already matched by the `events.system.*` glob the 13d
     installer subscribes (`component_health_watch.py:95`). Never RUNNING ⇒ the boot died at
     `:1029` ⇒ `BOOT_HALT_RECONCILIATION_FAILED`. **This latch is what makes the reconciliation
     cause separable at all**: a failed reconciliation also leaves `portfolio.initialized`
     `False`, because `_initialize_portfolio()` at `:1034` is never reached — so the portfolio
     probe alone cannot distinguish the two, and the emulator latch is load-bearing, not
     decorative.
  3. Otherwise, `portfolio.initialized` (`cdef readonly bint`, `portfolio/base.pxd:29-30`; the
     kernel reads it at `kernel.py:1362`) false ⇒ `BOOT_HALT_PORTFOLIO_NOT_INITIALISED`
     (`:1037`).
  4. None of the above, trader never RUNNING ⇒ `BOOT_HALT_TRADER_NEVER_STARTED`, the generic
     value. It is a real member of the enum, not a failure of the ladder: an unattributed
     boot-halt must still alert, and must not borrow a cause it did not observe.
  Each of the four is a **separate RED test** (§7 13d steps 3b/3c) — the resolution is proven,
  not claimed.
- `emit_alert` contains every sink failure by contract (`health.py:668-689`), so the new call
  site adds no new raise and cannot change the process exit code.

**Design for 13a/13b/13c is already fully specified** at
`RECONCILIATION_NATIVE_REPORTS_2026-09-12.md` §3 (`:60-70`): the gating rule above, the exact
`OrderStatusReport` / `FillReport` field maps, the `quantity` unit declaration (L-2), and the
load-bearing ordering fact that a `FillReport` is only reachable *through* an order report
(`live/execution_engine.py:1880-1881` has no fill-only loop), so both generators must land in
the same increment. **AUD-13 makes no design change to any of it — but the R-1/R-2 ruling does,
in two places, and those supersede the 09-12 text where they conflict (see the ruling block
below).** The executing session
re-derives every Breezy `file:line` anchor (they have moved) and treats the §1 happy-walk and
the F1-F6 failure-walk table as the specification.

**Fail-closed semantics, stated explicitly here because round 1 left them to the 09-12 plan.**
In all three cases below the generators return an **empty list AND record a latched, counted,
logged refusal with a reason code** — emptiness is never allowed to be indistinguishable from
"nothing to report", and no new name may be invented for `[]`:
- **Venue positions GET fails or times out** → report nothing, latch
  `positions_read_failed`, emit a WARN alert, and let the engine fall back to today's
  behaviour. Never substitute a cached or stale positions read.
- **Positions payload is only partially parseable** → the read is treated as **wholly failed**.
  Partial gating is forbidden: a dropped unparseable row would silently convert "the venue says
  we hold this" into "the venue does not", which is the fail-OPEN direction.
- **Venue and local disagree** — the venue holds an open position for an instrument with no
  durable record, or the record's `cumulative_qty` does not match the venue quantity — →
  report nothing **for that instrument**, latch `record_venue_disagreement` with the instrument
  id, emit a WARN alert, and leave that instrument to the existing EXTERNAL inference. Other
  instruments are unaffected. A disagreement is a finding for AUD-16/AUD-13a, never a number
  to reconcile by choosing a side.

**Ruled design, superseding the 09-12 plan text (`RULING_venue_reconciliation_R1_R2_2026-09-21.md`,
Revision 3, peer-ENDORSED).** Two of the 09-12 plan's §3 outputs are now fixed by ruling rather
than open, and one of them is a defect the ruling found in that plan:

- **`commission=` — R-1 ruled O4.** `fee_reconciled is True` (and `venue_fee_raw` present) ⇒
  `commission = Money(record.cumulative_fee, USD)`, `feeSource = "RECORDED"`. Otherwise
  `commission` is the modelled taker fee banker's-rounded exactly as `polymarket_us_fee`
  (`src/breezy/adapters/polymarket_us/fees.py:277`) does, **but with θ resolved AS OF
  `record.ts_event`, never off the reconciliation-time `Instrument`** — `polymarket_us_fee` reads
  θ via `_fee_coefficient(instrument)` (`fees.py:422`) at CALL time and has no notion of fill-time,
  which is the defect the ruling's peer review raised as HIGH. `feeSource = "MODELLED_AT_FILL_TIME"`.
  Two mechanisms, both required, not either/or:
  1. **New writes:** B0 gains one more optional-on-read `DurableFillRecord` field,
     `fee_coefficient_at_fill: Decimal | None`, populated at both fill write sites from the
     `Instrument` in hand at fill time. `feeSource` is a second new optional-on-read field, same
     pattern as `trade_id`/`order_qty` (`exec/client.py:670` neighbourhood).
  2. **Legacy rows** (no `fee_coefficient_at_fill`): a dated, evidence-pinned coefficient schedule
     keyed on `ts_event`, **owned by `src/breezy/adapters/polymarket_us/fees.py` and by nothing
     else** — that module is already the single source of truth for this venue's fee numbers, with
     `MAKER_FEE_COEFFICIENT` (`fees.py:77`) and `DOCUMENTED_TAKER_FEE_COEFFICIENT` (`:86`, in
     `__all__` at `:54`) both module-level constants pinned from a dated evidence document. The
     schedule constant and its as-of-`ts_event` resolver (a new
     `_fee_coefficient_as_of(ts_event) -> Decimal | None`, returning `None` for the AMBIGUOUS
     window and every unpinned gap) therefore live in `fees.py` beside `_fee_coefficient`
     (`fees.py:422`), and `exec/client.py`'s generator bodies **call** it. Defining a second
     lookup table next to `DurableFillRecord` in `exec/client.py` is forbidden: it would fork the
     one module whose charter is to be that source. `polymarket_us_fee` (`fees.py:277`) itself is
     **not forked and not modified** — it keeps reading θ from the `Instrument` at call time for
     the live pricing path; the as-of resolver is an addition beside it, used only by
     reconciliation. Schedule content sourced from
     `docs/evidence/venue/polymarket_us/FEE_SCHEDULE_PIN_2026-09-18.md` — `ts_event <
     2026-09-17T00:00:00Z` ⇒ `0.06`; `ts_event >= 2026-09-17T17:00:00Z` ⇒ `0.0695`. The interval
     `[2026-09-17T00:00:00Z, 2026-09-17T17:00:00Z)` is a **named AMBIGUOUS window** — the pin
     document itself calls that gap open and out of scope — and a legacy record landing in it,
     before the earliest pinned date, or in any future unpinned gap, **REFUSES**: no order report
     and no fill report for that record, latched, counted and alerted, exactly like the three
     fail-closed walks above. It is never defaulted to either coefficient.
     **This fourth refusal is NAMED, because §6's binding rule forbids an anonymous one**
     (no refusal may be indistinguishable from another, and no new name may be invented for
     `[]`). Following the two latches above (`positions_read_failed`, `record_venue_disagreement`
     with the instrument id attached): latch key and reason code **`fee_coefficient_ambiguous`**,
     carrying the record's `venue_order_id` (`exec/client.py:667`) **through
     `_redact_order_id` (`exec/client.py:414-416`)** exactly as every other venue-order-id log
     site in this module does, plus the record's `ts_event` (`:675`) bucket. Its WARN alert is
     `event="reconciliation_refusal"`, `detail="FEE_COEFFICIENT_AMBIGUOUS"` — a **fixed enum
     string**, never the id and never the date (the §6 13d detail rule applies here too), and a
     **different member** from the ones the `positions_read_failed` and
     `record_venue_disagreement` walks emit. A fee-schedule gap is not a venue/local quantity
     disagreement: reusing `record_venue_disagreement` for it would satisfy the refusal's shape
     while telling a future reader the wrong thing about what happened, and is forbidden.
     **Encoding (binding -- the schedule is N scalar constants, never a table).** The no-fork pin
     in §7 13b step 1d reuses the existing AST census, whose value extractor `_literal_decimal`
     (`tests/unit/test_polymarket_us_fee_schedule_pin.py:156-172`) parses **only** a bare
     `Decimal("...")` call, a numeric literal, or a unary-negated one; it returns `None` for a
     tuple/dict/set, and `_module_level_bindings` (`:175-188`) then drops that binding entirely.
     A composite dated table would therefore be **invisible to the very pin meant to see it**.
     The schedule is consequently encoded as individually-named module-level scalars in `fees.py`:
     - **Post-drift coefficient** -- one new literal,
       `_POST_DRIFT_TAKER_FEE_COEFFICIENT: Decimal = Decimal("0.0695")`. The name MUST end in
       `theta` or `taker_fee_coefficient`: the census's name filter `_THETA_NAME` (`:128`) is
       `(?i)(theta|taker_fee_coefficient)$` -- **end-anchored** -- so a dated suffix
       (`..._FROM_20260917`) would silently fail to match and the pin would pass while seeing
       nothing.
     - **Pre-drift coefficient** -- **no new constant and no second `0.06` literal**: the
       resolver's pre-drift branch returns the existing `DOCUMENTED_TAKER_FEE_COEFFICIENT`
       (`fees.py:86`, already `Decimal("0.06")`, already `__all__`-public at `:54`) directly.
       Re-declaring `0.06` under a second name would be exactly the duplicate source of truth
       this step exists to forbid. (An alias binding would in any case stay invisible to the
       census: `_literal_decimal` does not resolve an `ast.Name`.)
     - **Window boundaries** -- separately named `int` nanosecond constants, e.g.
       `_FEE_DRIFT_AMBIGUOUS_START_NS` / `_FEE_DRIFT_AMBIGUOUS_END_NS`, whose names deliberately
       do **not** match `_THETA_NAME`, so the census cannot mistake an epoch for a coefficient.
     `_fee_coefficient_as_of(ts_event)` selects between the two coefficients on those boundaries
     and returns `None` inside the AMBIGUOUS window and every unpinned gap, exactly as above.
     `MAKER_FEE_COEFFICIENT` (`fees.py:77`) remains invisible to the census by construction --
     it does not match the end-anchored *taker* pattern -- so this encoding cannot fuse the
     maker rebate into the taker census.
  `feeSource` is never read by `_recorded_fee_for`/trial scoring (which already ignores
  `event.commission`), so this introduces no PREREG contamination path. Its only consumers are
  diagnostics and any future `exit_guard`/settlement-actor wiring, which the ruling now requires
  to check `feeSource == "RECORDED"` before treating `Position.realized_pnl` as fee-accurate.
- **`order_side=` — a design defect in the 09-12 plan, fixed here.** That plan's "Outputs per
  record" (`RECONCILIATION_NATIVE_REPORTS_2026-09-12.md:66`) hardcodes `order_side=BUY` for
  **every** reported record. But `fill_records_for` (`exec/client.py:2905`) returns every durable
  record for an instrument, and `DurableFillRecord.order_side` (`exec/client.py:670`, docstring
  `:663`) deliberately "keeps its sign" so a SELL record nets against the longs on an R-8/R-9
  partial exit. **Both reports MUST take `order_side` from `record.order_side`.** The failure if
  they do not is not cosmetic: `on_order_filled` branches on
  `event.order_side is OrderSide.SELL` at `src/breezy/strategy/current_rung_hold/continuous_strategy.py:2271`
  and routes to `_on_exit_order_filled` (`:2277`); a SELL exit mis-tagged BUY falls through into
  the entry `consume_if_absent`/duplicate-fill machinery instead — a phantom entry, double-counted
  size, and exit provenance/kill-rule bookkeeping never run. This hazard exists under R2-A as well
  as R2-B (a mis-sided EXTERNAL position is still a wrong position), so the fix is scoped to 13b,
  ahead of 13c.

**Safety facts that constrain both, verified in the ruling and restated here as binding
constraints, not open questions:**
- `DailySpendLedger.authorize_order_cost`/`release_booking`/`true_up_booking` are called ONLY from
  the exec client's own submit/resolver paths — **never** from `on_order_filled` or anywhere in
  `src/breezy/strategy/`. A reconciled `OrderFilled` reaching the strategy therefore cannot
  re-authorize or double-book spend. Nothing in 13b/13c may introduce such a call site.
- Idempotency for a replayed reconciled fill is keyed on `venue_order_id` under a process-wide
  flocked read-check-write: `consume_if_absent`
  (`src/breezy/strategy/current_rung_hold/trial_day_latch.py:780`) plus the
  `existing.venue_order_id == venue_order_id` silent no-op in `continuous_strategy.py`. Never
  re-key it on wall clock or boot count.
- **Reconciled and resolver fills stay RESIDUAL by PREREG — they never grow `n`.** `n` grows only
  via the create path. 13b/13c change nothing about this.
- Nautilus `position_check_interval_secs` stays off (§5).

**Regression detector (closes the round-1 self-scored autonomy gap).** Both generators log one
fixed-shape INFO line per reconciliation carrying `order_reports=<n> fill_reports=<n>
records_considered=<n> gated_out=<n> refusals=<n>`, **with `refusals=<n>` broken out by cause on
the same line — `refusals_positions_read_failed=<n> refusals_record_venue_disagreement=<n>
refusals_fee_coefficient_ambiguous=<n>` — so an undifferentiated total can never hide WHICH
fail-closed path fired** (one field per named latch; the total is their sum). A future refactor that silently returns to
`[]` shows as `order_reports=0 records_considered=N`, which is a distinct and greppable shape
from a legitimate `records_considered=0`. The contract test pins the line's presence and its
counts.

**Prerequisites already shipped** (do not re-do): A1/A2 venue-id map, B0 `trade_id`/`order_qty`
on `DurableFillRecord`, C-a replay-idempotence assertion, E docstrings — all landed 09-12
(commits `c792ec6`, `aa30b6f`, `33795e2`, `de3e48a`; dispositions AM-1..AM-13).

## 7. Ordered steps

**AUD-13d — boot-halt alert (RED first; no ruling, ship first).**
1. Re-verify alert delivery as a **recorded step, not an assumption**: confirm
   `BREEZY_ALERT_WEBHOOK_URL` is configured and a CRITICAL is delivered end to end via the
   existing `tests/integration/test_alert_webhook_delivery.py` path, and paste the evidence
   line. If delivery has regressed, 13d ships a detector with no destination and must stop.
2. RED: `tests/unit/test_trade_cli.py` ::
   `test_a_run_that_ends_without_the_trader_ever_running_alerts_at_critical`,
   `test_a_normal_run_that_reaches_trader_running_emits_no_boot_halt_alert`,
   `test_the_boot_halt_alert_detail_is_a_fixed_enum_and_carries_no_value`,
   `test_a_failing_alert_sink_does_not_change_the_process_exit_code`.
3. RED (the reconciliation-specific case, driven through a REAL `LiveExecutionEngine` whose
   `reconcile_execution_state` returns `False`):
   `test_a_false_reconciliation_halts_the_boot_and_emits_a_critical_alert` — asserts the
   kernel's `start_async()` returned before `trader.start()` (the trader never published `RUNNING`)
   AND that exactly one CRITICAL payload reached the sink, **AND that the payload's `detail` is
   `BOOT_HALT_RECONCILIATION_FAILED`, not the generic value**.
3b. RED — **the two non-reconciliation early-return causes, tested rather than asserted** (the
   round-2 required change). One test per cause, each driving the real kernel to the real early
   return and asserting the resolved `detail`:
   `test_engines_that_never_connect_halt_the_boot_with_the_engines_not_connected_detail` — a data
   or exec client whose `check_connected()` stays false past `timeout_connection`, exercising the
   `:1025` return;
   `test_a_portfolio_that_never_initialises_halts_the_boot_with_the_portfolio_detail` —
   reconciliation succeeds (so `OrderEmulator` reaches `RUNNING`) but `portfolio.initialized`
   stays false past `timeout_portfolio`, exercising the `:1037` return.
   **The discrimination assertion both tests must carry:** the portfolio case must resolve to
   `BOOT_HALT_PORTFOLIO_NOT_INITIALISED` and **not** to `BOOT_HALT_RECONCILIATION_FAILED`, and
   the reconciliation case must resolve the other way — even though `portfolio.initialized` is
   `False` in *both*. That pair is the actual test of the emulator latch; either test alone would
   pass under a broken ladder.
3b-fixtures. **The fixture shape for 3b — specified, because "drive the real kernel without
   patching Nautilus" is the hardest mechanic in this item (the round-3 MINOR).** Nothing in
   `nautilus_trader` is monkeypatched: every lever below is either a `TradingNodeConfig` field or
   a Breezy-owned client subclass registered through the documented factory seam.
   - **Precedent and positive control.** `tests/contract/test_trade_node_lifecycle_contract.py`
     already drives a REAL `TradingNode` from `build_trade_node_config` through
     `build() -> run_async() -> RUNNING -> stop_async() -> dispose()` with a Breezy-owned
     `_SilentDataClient(LiveMarketDataClient)` / `_SilentDataClientFactory(LiveDataClientFactory)`
     (file `:79-110`) registered via `node.add_data_client_factory(POLYMARKET_US_CLIENT_NAME, ...)`
     (`:153`) and **zero** registered exec clients. That test reaching `trader.is_running` today
     is the positive control: it proves this wiring reaches `:1039`, so each 3b test is that same
     harness perturbed by **exactly one** fact. A 3b test that fails for any reason other than the
     perturbed fact is a fixture defect, and the control test's own green run is the discriminator.
   - **Engines never connect (`:1024` return).** Register a second Breezy-owned subclass,
     `_NeverConnectingDataClient(LiveMarketDataClient)`, identical to `_SilentDataClient` except
     that `_connect` awaits an `asyncio.Event()` that is never set — so the client never reaches
     connected and `data_engine.check_connected()` stays `False`. Build the node config with
     `timeout_connection` (`nautilus_trader/system/config.py:127`, `PositiveFloat`, default 60.0)
     at `0.5` (valid by definition, not an open question: `PositiveFloat = Annotated[float,
     Meta(gt=0.0)]`, `nautilus_trader/common/config.py:57`, so any value `> 0.0` is accepted) so
     `_check_engines_connected`
     (`kernel.py:1377-1391`, a poll loop on `self.clock.utc_now() >= timeout`) returns `False` in
     under a second. Assert `BOOT_HALT_ENGINES_NOT_CONNECTED`, and that the `OrderEmulator` RUNNING
     latch was **never** set (`:1033` is unreachable from `:1024`).
   - **Portfolio never initialises (`:1037` return).** Keep the connecting `_SilentDataClient`, so
     `:1024` passes, and keep zero exec clients, so reconciliation is satisfied without a venue
     (`reconcile_execution_state`, `live/execution_engine.py:1670`, iterates an empty client set;
     with `reconciliation` off the kernel instead logs at `:1031` and skips) — either way `:1033`
     runs and the emulator publishes RUNNING, which the test must ASSERT rather than assume, since
     that latch is probe 2. Then, after `node.build()` and before `run_async()`, add one OPEN order
     to the kernel's cache through the native `Cache.add_order` (`cache/cache.pyx:2155-2161`) for an
     `InstrumentId` that has **no** instrument in the cache: `Portfolio.initialize_orders`
     (`portfolio/portfolio.pyx:236-300`) hits `instrument is None`, logs `"no instrument found for
     …"`, sets `initialized = False` (`:258-266`, stored at `:300`), and nothing re-initialises it —
     so `_check_portfolio_initialized` (`kernel.py:1423-1434`) times out at `timeout_portfolio`
     (`system/config.py:129`, default 10.0, likewise set to `0.5`) and the kernel returns at
     `:1037`. Assert `BOOT_HALT_PORTFOLIO_NOT_INITIALISED` **and not** `BOOT_HALT_RECONCILIATION_
     FAILED`, with the emulator latch set — the pair that makes probe 2 load-bearing.
   - Both tests carry `pytestmark = pytest.mark.contract` and live beside the existing lifecycle
     contract test, because they drive a real node rather than a double. Neither reads a venue
     socket, and neither touches `timeout_reconciliation`.
3c. RED: `test_a_boot_halt_with_no_attributable_cause_alerts_with_the_generic_detail` — the
   ladder falls through, one CRITICAL still goes out, and the `detail` is
   `BOOT_HALT_TRADER_NEVER_STARTED`. This pins that an unattributed cause is still delivered,
   never swallowed and never mislabelled as one of the three named causes.
4. GREEN: the watch installer + the post-`node.run()` check.
5. `lint-imports` + `mypy`; full gate `scripts/ci/run_tests_no_egress.sh` (addopts already
   carries `-q`; never add `-q`).

**AUD-13a — verification package (no code). R-1/R-2 are RULED
(`docs/evidence/RULING_venue_reconciliation_R1_R2_2026-09-21.md`), so steps 2-3 below are now
evidence the ruling's implementation depends on, and step 4 is DONE.**
1. Re-derive the four UNVERIFIED items at `RECONCILIATION_NATIVE_REPORTS_2026-09-12.md:137-143`
   against today's state; mark each still-unverified or now-settled.
2. Read the store read-only and report, per record: presence of `tradeId`, `orderQty`,
   `venueFeeRaw`, `feeReconciled`. This is what distinguishes R-1 options O1/O3/O4 empirically
   (O3 is unreachable if no record carries a raw venue fee).
3. Grep-prove (or disprove) the O1 evidence requirement: that no Breezy artefact or decision
   reads `Position.realized_pnl` or `OrderFilled.commission`.
3b. **NEW — read each record's `ts_event` against the dated fee schedule** and record which
   bucket it lands in (`< 2026-09-17T00:00:00Z`, the AMBIGUOUS window, or
   `>= 2026-09-17T17:00:00Z`). Any record inside the window is a record 13b will REFUSE, and that
   must be known before B1's acceptance numbers (`N ≥ 1`) are computed.
3c. **NEW — report each record's `order_side`.** Any SELL-side record for an instrument the venue
   still reports open is the exact shape ruling finding 8 describes, and its presence or absence
   sizes the order-side fix's live blast radius.
4. **DONE — the ruling artefact exists:** `docs/evidence/RULING_venue_reconciliation_R1_R2_2026-09-21.md`
   (Revision 3), peer-ENDORSED with no required change
   (`docs/evidence/reviews/RULING_R1_R2_review_2026-09-21.md:164`). R-1 = O4; R-2 = R2-B
   conditional on three items. This step is retained as the audit trail, not as work to do.

**AUD-13b — increment B1 (RED first).** Test file
`tests/contract/test_reconciliation_durable_reports_contract.py`, the six named tests at
`RECONCILIATION_NATIVE_REPORTS_2026-09-12.md:78` plus four added by this revision. Order:

0. **GATED PRE-STEP — re-derive the 09-12 plan's citations before writing any generator body.**
   This is a checklist to complete and record, **not** the general "anchors have drifted" warning
   in §6, which an implementer can read and skip. 13b may not proceed to step 1 until the
   recorded output of this step exists. The 09-12 plan carries roughly **40** `file:line`
   citations beyond the one this item already corrected (`node_config.py:821` → `:882`); its §3
   field maps are the specification an implementer will copy from, so a stale anchor there is
   copied into code, not merely into prose. Produce a table — written into the AUD-13a evidence
   note, or a sibling note if 13a is still ruling-blocked — with one row per citation:

   | 09-12 citation | Symbol it names | Anchor at HEAD | Status |
   |---|---|---|---|

   Rules, all four binding:
   (a) Enumerate **every** `<path>:<line>` occurrence in
       `docs/plans/RECONCILIATION_NATIVE_REPORTS_2026-09-12.md` mechanically (a grep over the
       file), then partition into **Breezy-side** (`src/`, `tests/`, `deploy/`) and
       **Nautilus-side** (`.venv/.../nautilus_trader/`) — both are re-derived; the Nautilus ones
       matter because a version bump moves them too, and the two `[]` bodies alone moved ~554
       lines (§2).
   (b) Re-derive each anchor by locating the **named symbol** (codegraph, or `/usr/bin/grep` for
       non-code), never by trusting the old number; record `UNCHANGED`, `MOVED → :<n>`, or
       **`SYMBOL GONE`**.
   (c) **`SYMBOL GONE` is a stop, not a row.** A field map whose referent no longer exists is a
       design change, not a citation fix; it is reported to the strategy lead alongside R-1/R-2
       rather than silently re-pointed at whatever looks closest.
   (d) The recorded table is an acceptance artefact (§8 item 12), and the §3 field maps must be
       re-read **from the corrected anchors** before either generator body is written.
   (e) **`RECONCILIATION_NATIVE_REPORTS_2026-09-12.md:66` is known-defective and must NOT be
       copied as written** (ruling finding 8): its `order_side=BUY` is unconditional and the
       report must instead take `record.order_side` (`exec/client.py:670`). Record this line in
       the table as a **CORRECTED-BY-RULING** row rather than `UNCHANGED`, so an implementer
       copying the field map cannot reintroduce the hardcode. This is a design correction carried
       by the ruling, not a citation fix.

0b. **GATED PRE-STEP 2 — the ruling's build order (§4) is a sequence, not a set.** In order, each
   landing green before the next starts: (i) the B0 `fee_coefficient_at_fill` field and the
   `feeSource` field, written at both fill sites, optional-on-read for legacy rows; (ii) the
   order-side fix; (iii) increment C's characterisation test green. 13c may not ship until all
   three are done. Neither (i) nor (ii) may be deferred "into B1" as part of the generator bodies:
   both change `DurableFillRecord`/report construction and each carries its own RED test below.

1. RED, refusal walks first so fail-closed is pinned before any report is ever emitted:
   `test_a_failed_positions_read_yields_empty_reports_and_a_latched_refusal`,
   `test_a_partially_parseable_positions_payload_fails_the_whole_read`,
   `test_a_client_order_id_disagreement_emits_nothing`,
   `test_a_quantity_disagreement_emits_nothing_for_that_instrument_only`.
1b. RED — **the three ruling-mandated tests, all required before B1 ships:**
   `test_a_sell_side_durable_record_reconciles_to_a_sell_report_never_a_buy` — a partial-exit SELL
   record for an instrument the venue still reports open produces `order_side=SELL` on BOTH
   reports, and the resulting `OrderFilled` routes to `_on_exit_order_filled`
   (`continuous_strategy.py:2271-2277`), never into the entry `consume_if_absent` path
   (ruling finding 8; the one test that would have caught the 09-12 plan's hardcode);
   `test_a_pre_drift_fill_reconciled_on_a_post_drift_boot_books_the_fill_time_coefficient` — a
   legacy record with `ts_event` before 2026-09-17 reconciled on a boot whose current
   `Instrument` carries `0.0695` books the `0.06`-basis commission, not the `0.0695`-basis one,
   and `feeSource == "MODELLED_AT_FILL_TIME"` (ruling Revision 2's HIGH-item regression test);
   `test_a_legacy_record_inside_the_ambiguous_fee_window_is_refused_not_defaulted` — a legacy
   record whose `ts_event` falls in `[2026-09-17T00:00:00Z, 2026-09-17T17:00:00Z)` yields NO
   report and a latched, counted, alerted refusal — never `0.06` and never `0.0695`
   (ruling Revision 3);
   `test_the_ambiguous_fee_window_refusal_is_observably_distinct_from_the_other_latches` — ONE
   reconciliation that trips all three named refusals at once (a failed positions read, a
   quantity disagreement, and an ambiguous-window record) asserts three DIFFERENT latch keys
   (`positions_read_failed`, `record_venue_disagreement`, `fee_coefficient_ambiguous`), three
   different alert `detail` enum members, and three separately-incremented per-cause fields on
   the counts line — not merely that a refusal is present. Reusing another walk's latch key or
   detail for the fee case FAILS this test.
1c. RED: `test_a_recorded_fee_reports_the_recorded_commission_and_feesource_recorded` — the O4
   upper branch: `fee_reconciled is True` with `venue_fee_raw` present books
   `Money(record.cumulative_fee, USD)` and `feeSource == "RECORDED"`; and
   `test_feesource_is_never_recorded_without_a_raw_venue_fee`.
1d. RED (**the no-fork pin — REUSE the existing census SCANNER, do not add a second one**). The
   scanner to reuse is `study_theta_sites_from_source`
   (`tests/unit/test_polymarket_us_fee_schedule_pin.py:195-209`): it `ast.parse`s a file's TEXT
   and returns a `frozenset[tuple[venue, module_stem, name, Decimal]]` of that file's
   module-level theta declarations **without importing it** — the property that makes it legal
   to point at `src/`. Its sibling `study_theta_sites_from_analysis_scripts` (`:212-220`) globs
   `scripts/analysis/*.py` ONLY and so cannot reach `src/`; the new test therefore calls
   `study_theta_sites_from_source` directly on the two `src/` files with its own src-scoped
   expected set. `STUDY_THETA_BY_VENUE` (`:86-123`) and
   `test_every_in_scope_theta_site_agrees_with_its_venue_constant` (`:240-252`) are **untouched**:
   no `==` is relaxed, and the two `== DOCUMENTED_TAKER_FEE_COEFFICIENT` checks (`:251-252`) stay
   pinned at `0.06`. New test `test_the_dated_fee_schedule_is_declared_only_in_fees_py`:
   - `study_theta_sites_from_source(fees_src, module_stem="fees")` `==`
     `frozenset({("polymarket_us", "fees", "DOCUMENTED_TAKER_FEE_COEFFICIENT", Decimal("0.06")),
     ("polymarket_us", "fees", "_POST_DRIFT_TAKER_FEE_COEFFICIENT", Decimal("0.0695"))})`
     — `_venue_for_module` (`:191-192`) yields `polymarket_us` for both stems.
   - `study_theta_sites_from_source(client_src, module_stem="client") == frozenset()` —
     `exec/client.py` declares **no** fee-coefficient literal at all.
   It is RED today because `fees.py` declares only the first member, so the first `==` fails with
   the second tuple in its `missing=` set. The `0.0695` tuple is an **enumerated, dated
   exception** carrying its evidence citation
   `docs/evidence/venue/polymarket_us/FEE_SCHEDULE_PIN_2026-09-18.md` in a comment beside it —
   the identical mechanism, and the identical comment discipline, the existing expected set
   already uses for its own post-drift member (`:108-120`,
   `hourly_ask_relative_edge`/`TAKER_FEE_COEFFICIENT`/`Decimal("0.0695")`). That is the file's own
   stated CORPUS REFRESH POLICY (`:16-24`, `:85`): **widen the expected set, never relax `==`** —
   this member is added to an expected set, so no assertion operator changes anywhere.
   The encoding this test depends on (scalar constants, end-anchored names, no duplicate `0.06`)
   is fixed by §6's binding Encoding rule; a composite table would make this test unbuildable.
2. RED: `test_a_record_for_an_instrument_the_venue_no_longer_holds_is_not_reported` — the
   gating rule.
3. RED (regression detector):
   `test_the_reconciliation_counts_line_distinguishes_zero_records_from_zero_reports`.
4. RED (**the 09-11 incident replay — the acceptance test for G-10's own evidence**):
   `test_the_2026_09_11_order_2_fill_reconciles_on_the_first_boot` — construct the exact
   observed shape: a create-order classified AMBIGUOUS, a durable fill record written for it
   before any reconciling boot, and a venue positions GET that reports the instrument open.
   Drive ONE reconciliation through a real `LiveExecutionEngine` and assert the fill is adopted
   with Breezy's `client_order_id` on the **first** reconciliation — no second boot required,
   and assert the second reconciliation of the same fill is a no-op (`_check_and_skip_duplicate
   _fill`, `live/execution_engine.py:3400`).
5. RED: the three engine-driven goal-state assertions
   (`…reconciles_to_our_client_order_id_not_external`, `…no_inferred_fill_is_generated…`,
   `…exactly_one_position_exists…`).
6. GREEN: implement both bodies together; `commission=` takes the **ruled O4** value
   (recorded, else modelled at fill-time θ, else REFUSE) and `order_side=` takes
   `record.order_side`.
7. `lint-imports` + `mypy` (adapters must not import `breezy.runtime`); full gate.

**AUD-13c — increment B2 (R2-B is RULED, conditional).** Do not start until all three R-2
conditions hold and are evidenced: increment C's two characterisation tests green; the order-side
fix merged with `test_a_sell_side_durable_record_reconciles_to_a_sell_report_never_a_buy` green;
and `feeSource` threaded. Then RED
`test_a_claimed_instrument_reconciles_under_the_breezy_strategy_id`, then the one config field,
then the C-b engine-driven pair deferred by disposition AM-8.

## 8. Acceptance criteria and required evidence

1. RED→GREEN transcripts for every test above (real output, not a claim).
2. **13d:** a recorded delivery re-verification line (§7 step 1), and a CRITICAL alert payload
   captured in the test for a `False` reconciliation. A log line is **not** acceptance.
3. **13d:** proof that a normal boot emits **zero** boot-halt alerts (the false-positive guard),
   and that a failing sink leaves the exit code unchanged.
4. `test_the_2026_09_11_order_2_fill_reconciles_on_the_first_boot` green, with the constructed
   record shape quoted in the transcript.
5. The six §1 goal-state assertions hold in the contract test: `N ≥ 1` order reports and
   `N ≥ 1` fill reports; zero `Generated inferred OrderFilled`; `client_order_id` is the
   durable record's, never a UUID4; exactly one `Position` per instrument;
   `Position.quantity == record.cumulative_qty` and
   `avg_px_open == cumulative_cost / cumulative_qty`; `continuous_rung_hold/halt` absent after
   three consecutive reconciliations of the same fill.
6. Each of the three fail-closed walks (read failure, partial parse, disagreement) shows an
   empty report list **and** its latched reason code **and** its WARN payload — never a bare `[]`.
7. Full gate green, with no new failure beyond the known clock-dependent flake at
   `tests/unit/test_app_trade_main_permit_logging.py:115`.
8. `lint-imports` clean; `mypy` clean under `adapters`, `runtime`, `strategy`.
9. The 17 existing callers in `tests/unit/test_polymarket_us_exec_client.py` (blast radius,
   09-12 plan `:107`) stay green — in particular
   `test_the_report_generators_never_raise_into_the_native_handler`, which now has real work.
10. Live proof on the next boot: the four §1 log assertions plus the counts line, quoted from
    `~/.local/share/breezy/logs/breezy-trade-<ts>.log`.
11. A statement of which R-1 option was ruled — **O4**, per
    `docs/evidence/RULING_venue_reconciliation_R1_R2_2026-09-21.md` — the `feeSource` the first
    reconciled fill carried, and the `commission` value it actually booked.
12. **The §7 13b step 0 citation table exists and is recorded**, covering every `file:line` in
    the 09-12 plan, each marked `UNCHANGED` / `MOVED` / `SYMBOL GONE` / `CORRECTED-BY-RULING`,
    with any `SYMBOL GONE` row escalated rather than re-pointed, and
    `RECONCILIATION_NATIVE_REPORTS_2026-09-12.md:66` carrying the `CORRECTED-BY-RULING` mark.
    Absent this artefact, 13b is not accepted even if its tests are green — the round-2
    reviewer's point is that a warning in prose is not a step.
13. **A durable SELL-side record for an instrument the venue still reports open reconciles to a
    SELL report, never a BUY** (ruling finding 8), and the resulting fill is observed reaching
    `_on_exit_order_filled` rather than the entry path.
14. **A pre-drift fill reconciled on a post-drift boot books the fill-time coefficient**, with the
    booked `commission` and the resolved θ both quoted in the transcript, and
    `feeSource == "MODELLED_AT_FILL_TIME"`.
15. **A legacy durable record whose `ts_event` falls in
    `[2026-09-17T00:00:00Z, 2026-09-17T17:00:00Z)` yields no report and a latched, counted
    refusal, never a defaulted coefficient** (ruling Revision 3).
16. **No new `DailySpendLedger` call site** appears in `src/breezy/strategy/` or on the
    `on_order_filled` path, and the reconciled fill is still classified RESIDUAL under PREREG —
    `n` is unchanged by any reconciliation. Both are stated as diffs/greps in the evidence.
17. **The ambiguous-fee-window refusal is observably distinct**: in one reconciliation that
    trips all three named refusals, the transcript shows `fee_coefficient_ambiguous` as its own
    latch key, its own `FEE_COEFFICIENT_AMBIGUOUS` alert detail, and its own per-cause field on
    the counts line — never sharing `positions_read_failed` or `record_venue_disagreement`. The
    latched entry carries the record's redacted `venue_order_id`; the alert `detail` carries no
    value.
18. **One fee-coefficient source of truth**: the new src-side theta-site pin
    `test_the_dated_fee_schedule_is_declared_only_in_fees_py` (§7 13b step 1d, over the existing
    `study_theta_sites_from_source`, `tests/unit/test_polymarket_us_fee_schedule_pin.py:195`) is
    green, showing **exactly two** theta declarations in
    `src/breezy/adapters/polymarket_us/fees.py` — `DOCUMENTED_TAKER_FEE_COEFFICIENT` at `0.06`
    (unchanged, and not duplicated under a second name) and `_POST_DRIFT_TAKER_FEE_COEFFICIENT`
    at `0.0695` — and **zero** fee-coefficient literals in `exec/client.py`, with
    `polymarket_us_fee` (`fees.py:277`) unmodified in the diff. `_fee_coefficient_as_of` selects
    between those two named scalars and is likewise declared only in `fees.py`. The pre-existing
    `test_every_in_scope_theta_site_agrees_with_its_venue_constant` (`:240`) is green and
    **unedited** in the diff — evidence that the study-script census was neither widened nor
    relaxed by this item.

## 9. Validation

**Failure cases.** Every one of F1-F6 (09-12 plan `:33-40`) is re-asserted by a test, and the
three walks named in §6 are added to them. The binding rule: **every failure walk falls CLOSED
to today's behaviour (empty reports + the existing EXTERNAL inference) with a latched reason
and an alert, never to a guessed book and never to a silent `[]`.** F5 is the one that can stop
the node booting (overfill reject → `reconcile_execution_state` returns `False`); B0 already
persists `trade_id` so the report is byte-equal, and the contract test must drive a resolver
fill AND a reconciliation inside one engine to prove it.

**Integration behaviour.** The pyo3 adjuster
(`nautilus_pyo3.process_mass_status_for_reconciliation`, reached via
`live/reconciliation.py`) is Rust and unreadable in the install. The contract test asserting
`1 orders, 1 fills` **is** the measurement. A mismatch is a design input, never a test to relax.

**Autonomous operation. (Corrected — round 1 overstated this.)**
- F1-F4 and F6 fall closed to today's already-broken-but-running behaviour: the node **still
  boots and still hunts**, now with a latched reason and a WARN instead of silence.
- **F5 is the exception, and it is not "still boots, still hunts".** A `False` return from
  `reconcile_execution_state` makes `NautilusKernel.start_async()` `return` at `kernel.py:1029`,
  **ten lines before `self._trader.start()` at `:1039`**. The process stays up and the systemd
  unit stays `active (running)` while no strategy is subscribed and no order can ever be
  placed. That is precisely the shape recorded as *"a healthy node can still be unable to
  trade"*. Without 13d the only trace is `self._log.error("Execution state could not be
  reconciled")` (`kernel.py:1345`) — a detector with no delivery. **13d is the control; it is
  scoped, tested and accepted above, and it ships before 13b.**
- A reconciliation that fails OPEN (a phantom LONG asserted after settlement) would let the
  strategy believe it holds a position it does not; the §3 gating rule exists solely to make
  that unreachable, and
  `test_a_record_for_an_instrument_the_venue_no_longer_holds_is_not_reported` is its guard.
- 13d deliberately adds **no** self-healing: no retry, no reconciliation bypass. A node that
  cannot reconcile must stay down and loud, because the alternative is booting with a book the
  system knows it cannot trust.

## 10. Deployment, observability, rollback

- No unit-file change, no deploy change, no env change. The behaviour ships with the next
  ordinary node boot (supervisor LAUNCH 16:50Z).
- **Observability:** Nautilus already logs `Final order_reports contains N orders, fill_reports
  contains N fills` and `Generated inferred OrderFilled`; both lines move from the bad shape to
  the good shape. 13b adds the counts line (§6). 13d adds one alert event name. No new sink,
  no new log stream.
- **Rollback:** each increment is additive and independently revertable. Reverting 13d removes
  one watch and one alert; reverting 13b restores `return []` and today's EXTERNAL inference
  exactly. B0's record fields are optional-on-read (disposition AM-7), so a revert leaves every
  store row decodable.

## 11. Relationship to portfolio-level ROI

**Demonstrated:** none. This item does not change whether the bot trades, what it trades, or at
what price. Claiming an ROI benefit here would be invention.

**Plausible, and separated as such:** every realized-PnL or portfolio figure the programme will
eventually need is read off positions and fills. While reconciliation is stubbed, a restart
silently re-bases the book onto an inferred fill at an inferred price with a modelled
commission — so any equity curve built on top of it is untrustworthy by construction. AUD-13
is a **precondition for measuring ROI honestly**, not a contributor to it. 13d's benefit is
loss-avoidance of the same measured class as the 09-20 permit lapse (10.9 h of a node that
looked perfect and could not trade): it shortens detection-to-attention on a silent boot halt
from "never" to "immediately". No figure is attached to that here.

**How it will be evaluated:** by the eighteen acceptance items in §8 — none of which is a
profitability claim.

## 12. Assumptions, unresolved questions, blockers

**RULINGS — R-1 and R-2 are RULED and peer-ENDORSED; neither is a blocker any longer.**
Artefact: `docs/evidence/RULING_venue_reconciliation_R1_R2_2026-09-21.md` (Revision 3). Review
trail: `docs/evidence/reviews/RULING_R1_R2_review_2026-09-21.md` (verdict ENDORSE, no required
change, `:164`).
- **R-1 — RULED O4.** Recorded venue fee where present (`feeSource = "RECORDED"`), else a modelled
  fee with θ resolved as of `record.ts_event` (`feeSource = "MODELLED_AT_FILL_TIME"`), else — in
  the AMBIGUOUS window or any unpinned gap — REFUSE. Mechanism and tests: §6, §7 13b steps 1b/1c,
  §8 items 14-15.
- **R-2 — RULED R2-B, CONDITIONAL on three items** (not the single "C green" the 09-12 plan
  named): increment C's characterisation test green; the `order_side`-from-record fix landed and
  its contract test green; `feeSource` threaded first. §7 13b step 0b carries the order.
- **13d and 13a were never ruling-blocked and are unchanged.**

**REMAINING BLOCKERS: none.** Every increment of AUD-13 is now buildable. What remains is
**sequenced work, not permission**: 13c is gated on the three R-2 conditions above, which are
items inside this plan rather than external decisions. This is a statement about blockers only —
it is not a readiness claim, and the plan has not been peer-reviewed in this revision.

**Assumptions to re-verify before editing:**
- Every Breezy `file:line` in the 09-12 plan has drifted (~554 lines at the generators). Anchors
  must be re-derived; do not copy them. This revision fixed one such anchor in this plan
  (`node_config.py:821` → `:882`) and re-scanned §5/§6 for others.
- The store's contents have changed since 09-12 (more records). The plan's "one record"
  narrative is stale; the gating rule handles N records without modification, but the
  acceptance numbers (`N ≥ 1`) must be recomputed from the store, not assumed.
- Whether the venue populates `commissionNotionalTotalCollected` on the GET order response is
  still UNVERIFIED and is R-1 option O3's precondition.
- `BREEZY_ALERT_WEBHOOK_URL` delivery (`f97c26f`) — 13d's §7 step 1 turns this from an
  assumption into a recorded step.

**Explicitly NOT a blocker:** the `position_check_interval_secs` prohibition. It is a scope
exclusion (§5), already contract-pinned, and requires no ruling.

**New open question raised by the ruling, carried not decided:** the dated fee schedule pins two
intervals from the evidence available on 2026-09-18. A THIRD, unpinned θ drift after that date
would make the legacy fallback confidently wrong rather than honestly degraded — the
`MODELLED_AT_FILL_TIME` marker cannot detect that on its own (ruling §7). The mitigation already
in scope is that the refusal branch covers "any future unpinned gap"; the residual risk is a drift
that lands *inside* an already-pinned open-ended interval. This is a known limit of the ruling,
not a defect introduced here, and it does not block 13b.

## 13. Review history

**Baseline self-score (2026-09-21, author): 86/100.** Named weaknesses: design delegated to the
09-12 plan; Breezy anchors not exhaustively re-derived; no detector for a future regression to
`[]`; live proof lands a day after merge.

### Round 1 — peer review

| Reviewer | Score |
|---|---|
| trading-bot-architect (`AUD-13-r1-trading-bot-architect.md`) | 85/100 |
| silent-failure-hunter (`AUD-13-r1-silent-failure-hunter.md`) | 77/100 |

**Dispositions — every defect, both reviewers:**

| # | Reviewer | Defect | Disposition |
|---|---|---|---|
| 1 | architect | MINOR — `runtime/node_config.py:821` is stale; real anchor `:882` | **ACCEPTED.** Verified independently this session (`/usr/bin/grep -n LiveExecEngineConfig src/breezy/runtime/node_config.py` → `:882`). Corrected in §5 and added as a row in §2's re-verification table, with the correction called out so an implementer cannot copy the old anchor forward. §5/§6 re-scanned; no other anchor outside the §2 table remains uncorrected. |
| 2 | architect | MINOR — durable-record-sources-a-venue-reconciliation is under-explained for a reader of AUD-13 alone | **ACCEPTED.** §6 now carries a self-contained paragraph ("Why a DURABLE LOCAL record is a legitimate source…"): the venue `Order` carries no client-order-id field (`exec/client.py:2519-2525`), so venue-only enumeration can only produce `EXTERNAL`; the venue positions GET is the authority on *whether*, the local record supplies *which order at what price*. |
| 3 | hunter | **MATERIAL** — no alert specified for the one failure mode that halts the node (F5); §9's "still boots, still hunts" is false for F5 | **ACCEPTED, and it became a new P1 increment.** Verified independently at HEAD: `kernel.py:1026-1029` returns out of `start_async()` at `:1029`, ten lines before `self._trader.start()` at `:1039` (this citation carried a wrong method name and a stray `:1038` until revision 4 — see the round-3 dispositions below); `_await_execution_reconciliation` (`:1335-1348`) logs `"Execution state could not be reconciled"` at ERROR and returns `False`. Added **AUD-13d** (§5, §6, §7, §8 items 2-3, §9) — a CRITICAL through the existing `breezy.runtime.health` sink, observed via the already-wired `COMPONENT_STATE_TOPIC` bus (`component_health_watch.py:95`, installed at `trade_cli.py:421`) plus the `node.run()` return at `trade_cli.py:438`, in the alert shape `app/trade.py:399-407` already uses. §9's autonomous-operation paragraph rewritten to exempt F5 explicitly. 13d takes **no** R-1/R-2 dependency and ships first. |
| 4 | hunter | **MATERIAL** — no regression test replays the 09-11 order-2 incident the gap is anchored to | **ACCEPTED.** §7 (13b) step 4 adds `test_the_2026_09_11_order_2_fill_reconciles_on_the_first_boot`, constructing the exact shape (create-order AMBIGUOUS → durable fill record written before any reconciling boot → venue positions GET shows the instrument open) and asserting first-boot adoption plus second-reconciliation idempotence. §8 item 4 makes it acceptance. |
| 5 | hunter | MINOR — design fully delegated to a separate document | **PARTIALLY ACCEPTED.** The load-bearing design choice is now restated in-plan (disposition 2), as are the fail-closed semantics (§6). The field maps stay in the 09-12 plan: duplicating them would create two divergent specifications for one code change, which the no-duplication constraint exists to prevent. |
| 6 | (author, round 1 §13) | No detector if reconciliation silently regresses to `[]` | **ACCEPTED (self-raised, now closed).** §6 adds the per-reconciliation counts line distinguishing `order_reports=0 records_considered=N` from `records_considered=0`, pinned by a contract test (§7 13b step 3). |
| 7 | (brief, round 2) | Behaviour on venue/local disagreement, venue call failure, partially parseable reports undefined | **ACCEPTED.** §6 "Fail-closed semantics" defines all three: read failure → whole-read failure + latched reason + WARN; partial parse → treated as wholly failed, partial gating forbidden (it is the fail-OPEN direction); disagreement → nothing emitted for that instrument only, latched with the instrument id + WARN. Each returns `[]` **with** a reason code and an alert — never a bare `[]` under a new name. Four RED tests added (§7 13b step 1), acceptance item 6. |

**Rejections:** none. Every defect from both records was verified against the artefact and
incorporated.

**Revision 2 self-score (honest, post-revision):**

| Criterion | Max | Score | Remaining weakness |
|---|---|---|---|
| Fidelity to the audit gap and completeness | 20 | 19 | G-10 fully covered plus the boot-halt path the gap implies but does not name. The field maps still live in the 09-12 plan by design. |
| Technical correctness and evidence grounding | 20 | 19 | Kernel halt path, both generators, the contract pin and the corrected `:882` anchor all re-verified from source this session. The 09-12 plan's remaining ~40 citations are still flagged-not-fixed. |
| Implementation specificity and feasibility | 15 | 14 | 13d is fully specified down to the observation seam and the alert shape; 13b's test order, fail-closed walks and counts line are named; test bodies for the six original assertions remain in the 09-12 plan. |
| Acceptance criteria and validation quality | 20 | 19 | Eleven falsifiable items, including the incident replay, the false-positive guard, and "an empty list must carry a reason code". Live proof still lands a day after merge. |
| Autonomous operation, failure handling, recovery | 15 | 14 | The boot-halt is now a delivered CRITICAL, the three ambiguous walks fail closed with reasons, and a silent regression to `[]` is detectable. Deliberately no self-healing — stated as a scope exclusion, not an omission. |
| Portfolio objective alignment, scope, dependencies | 10 | 9 | Honest about zero demonstrated ROI. The 13d split makes the P-rating defensible (P1 for the control, P2 for the correctness debt). |
| **Total** | **100** | **94** | |

### Round 2 — peer review

| Reviewer | Score | Material defects |
|---|---|---|
| silent-failure-hunter (`AUD-13-r2-silent-failure-hunter.md`) | **98/100** | None. Both round-1 MATERIAL defects verified genuinely fixed against source. 1 MINOR. |
| trading-bot-architect (`AUD-13-r2-trading-bot-architect.md`) | **97/100** | None. Independently reproduced the kernel early-return chain and the `ComponentStateChanged` publication from Cython source. 1 MINOR. |

**Dispositions — every defect and every required change, both reviewers:**

| # | Reviewer | Item | Disposition |
|---|---|---|---|
| 1 | hunter | **MINOR** — the detail-enum resolution for the two non-reconciliation early-return causes (engines-not-connected, portfolio-not-initialised) is asserted in prose, not tested; no latch named for either | **ACCEPTED IN FULL, and specified rather than narrowed** (the reviewer offered narrowing the claim as the cheaper option; it was declined). §6 now carries an **ordered four-step ladder** over three probes read from installed source this session: `data_engine.check_connected()`/`exec_engine.check_connected()` (`data/engine.pyx:324`, `execution/engine.pyx:276` — the same two the kernel prints at `kernel.py:1313-1314`), the `OrderEmulator` RUNNING latch, and `portfolio.initialized` (`portfolio/base.pxd:29-30`, read by the kernel at `:1362`), falling through to a generic `BOOT_HALT_TRADER_NEVER_STARTED`. **The load-bearing finding this work surfaced:** a failed reconciliation *also* leaves `portfolio.initialized` false, because `_initialize_portfolio()` (`kernel.py:1034`) is never reached — so the portfolio probe alone cannot separate the two causes. `_emulator.start()` at `:1033` sits between them, and `OrderEmulator(Actor)` (`execution/emulator.pyx:81`) → `Actor(Component)` (`common/actor.pyx:128`) publishes on `events.system.OrderEmulator`, already inside the `events.system.*` glob 13d subscribes (`component_health_watch.py:95`) — so the discriminator is native and free. §7 13d gains steps **3b** (one test per cause, each with the **cross-assertion** that the portfolio case must NOT resolve to the reconciliation detail and vice versa — either test alone would pass under a broken ladder) and **3c** (the generic-detail fall-through still alerts). |
| 2 | architect | **MINOR** — the ~40 stale citations in `RECONCILIATION_NATIVE_REPORTS_2026-09-12.md` are warned about generically but re-derivation is not a gated step an implementer must complete | **ACCEPTED, and made a gate rather than the one line requested.** §7 13b gains **step 0**, which 13b may not proceed past: a recorded per-citation table (`09-12 citation / symbol / anchor at HEAD / status`), enumerated mechanically over the whole file, partitioned Breezy-side vs Nautilus-side (**both** re-derived — a version bump moves the Nautilus anchors too), re-derived by **symbol** never by number, with `SYMBOL GONE` defined as a **stop and an escalation** rather than a row to re-point. §8 gains item 12 making the table an acceptance artefact: 13b is not accepted without it even if its tests are green. |
| 3 | architect | Citation drift — the plan says `self._trader.start()` is at `:1038`; it is at `:1039` | **ACCEPTED and corrected** in §6, verified this session against `kernel.py:1024-1039`. |
| 4 | both | Round-1 fixes (F5 boot-halt alert; 09-11 replay; `:882` anchor; durable-record-as-venue-source) confirmed genuinely fixed | **NOTED**, no change required. |
| 5 | architect | 1 point withheld on portfolio alignment because the P2 rationale is an argued priority call, not one derived from a measured cost | **ACCEPTED as correct and NOT closed.** There is no measured cost to derive it from — the bot has not traded since 09-15 — and inventing one would violate the brief. Carried as a permanent, named deduction rather than argued away. |

**Rejections:** none.

**Revision 3 self-score (conservative):**

| Criterion | Max | Score | Remaining weakness |
|---|---|---|---|
| Fidelity to the audit gap and completeness | 20 | 19 | Unchanged: G-10 covered plus the boot-halt path the gap implies but does not name; the field maps still live in the 09-12 plan by design, now behind a gated re-derivation. |
| Technical correctness and evidence grounding | 20 | 19 | The whole kernel ladder, both engine probes, the emulator's `Component` ancestry and `portfolio.initialized` were read from installed Nautilus source this session; the `:1038`→`:1039` drift is fixed. Still 19, not 20: the ~40 citations are now *gated* but not yet *re-derived* — the debt is scheduled, not paid. |
| Implementation specificity and feasibility | 15 | 14 | The detail ladder is now literal down to the probe and the ordering; step 0 is a completable checklist with a stop condition. Deducted 1: driving a real kernel to the engines-not-connected and portfolio-not-initialised timeouts in a unit test is the most fragile work in this item and its fixture shape is not specified. |
| Acceptance criteria and validation quality | 20 | 19 | Twelve items; the cross-assertion in 13d step 3b makes the ladder falsifiable rather than merely exercised. Live proof still lands a day after merge. |
| Autonomous operation, failure handling, recovery | 15 | 15 | An unattributable boot-halt still alerts with a generic detail — the ladder can degrade without ever swallowing the signal, which is the property that matters here. |
| Portfolio objective alignment, scope, dependencies | 10 | 9 | Unchanged, with the architect's deduction accepted as permanent (§ disposition 5). |
| **Total** | **100** | **95** | |

### Round 3 — peer review

| Reviewer | Score | Material defects |
|---|---|---|
| silent-failure-hunter (`AUD-13-r3-silent-failure-hunter.md`) | **95/100** | **None MATERIAL.** One MINOR, already self-disclosed: the fixture shape for the two non-reconciliation timeout tests (§7 13d step 3b). |
| trading-bot-architect (`AUD-13-r3-trading-bot-architect.md`) | **95/100** | **None MATERIAL.** Two MINOR citation defects (wrong method name; a correction applied in §6 but not to the duplicate figure in §2). |

**Readiness is the LOWER of the two: 95.** Both reviewers independently re-derived the kernel
ladder from installed source and both reproduced it correctly; the two scores agree for the
first time in this item's history, and neither withheld a point without naming the change.

**Dispositions — every defect and every required change, both reviewers:**

| # | Reviewer | Item | Disposition |
|---|---|---|---|
| 1 | architect | **MINOR** — §2 and §3 attribute the guarded early returns to `NautilusKernel.start()`; they live in `start_async()`. The sync `start()` has no guards | **ACCEPTED IN FULL, verified from installed source this revision before editing.** `/usr/bin/grep -n` on `.venv/lib/python3.13/site-packages/nautilus_trader/system/kernel.py`: `def start(self)` at **`:989`**, whose body runs `self._emulator.start()` (`:999`), `self._initialize_portfolio()` (`:1000`), `self._trader.start()` (`:1001`) with **no** early return; `async def start_async(self)` at **`:1003`**, with the three guards at `:1024`, `:1028` (guarded by `if self.exec_engine.reconciliation:` at `:1026`, `else: self._log.warning("Reconciliation deactivated")` at `:1031`), and `:1036`, then `self._emulator.start()` at `:1033`, `self._initialize_portfolio()` at `:1034`, `self._trader.start()` at `:1039`. Reachability re-confirmed: `TradingNode.run()` (`live/node.py:283`) awaits `self.kernel.start_async()` (`live/node.py:349`). The method name is corrected in §2, §3, §6 (four sites), §11 and in the round-2 disposition that carried it, each with the sync-variant caveat the reviewer's rationale asked for (a reader grepping `def start(` must not conclude the premise is false). |
| 2 | architect | **MINOR** — §6 states the `:1038`→`:1039` correction but §2 still reads `:1038`, so the document contains both the wrong number and the claim it was fixed | **ACCEPTED IN FULL.** §2, §11 and the round-2 disposition now read `:1039`, and the arithmetic is corrected with it: the `return` is at `:1029`, which is **ten** lines above `:1039`, not eleven. The stale "11 lines" figure was a second, unreported casualty of the same drift. |
| 3 | hunter | **MINOR** (also the architect's round-2 residual) — the fixture shape for driving the two non-reconciliation kernel timeouts without mocking the kernel is unspecified | **ACCEPTED IN FULL and specified to the seam, not narrowed.** §7 13d gains **step 3b-fixtures**. Nothing in `nautilus_trader` is patched: the levers are `TradingNodeConfig.timeout_connection`/`timeout_portfolio` (`system/config.py:127,129`, `PositiveFloat`) and Breezy-owned client subclasses registered through `add_data_client_factory`, mirroring the existing `_SilentDataClient`/`_SilentDataClientFactory` at `tests/contract/test_trade_node_lifecycle_contract.py:79-110` (registered at `:153`). The engines case uses a `_NeverConnectingDataClient` whose `_connect` awaits an `asyncio.Event` never set, so `check_connected()` stays false past `_check_engines_connected`'s poll loop (`kernel.py:1377-1391`). The portfolio case adds one open order to the cache via the native `Cache.add_order` (`cache/cache.pyx:2155-2161`) for an `InstrumentId` with no cached instrument, so `Portfolio.initialize_orders` (`portfolio/portfolio.pyx:236-300`) takes its `instrument is None` branch at `:258-266` and leaves `initialized` false at `:300`, timing out `_check_portfolio_initialized` (`kernel.py:1423-1434`). **The existing lifecycle contract test is named as the positive control** — it reaches `trader.is_running` on this same wiring today, so each new test is that harness perturbed by exactly one fact and a failure for any other reason is a fixture defect. |
| 4 | hunter | Confirmed the `SYMBOL GONE = stop` gate, the fail-closed walks and the regression detector hold on an independent second read | **NOTED**, no change required. |
| 5 | architect | Portfolio-alignment point withheld permanently (no measured cost exists to derive the P2 rating from) | **CARRIED, unchanged** — re-affirmed as permanent rather than re-litigated. |

**Rejections:** none. Both citation defects were real and reproduced from source before editing.

**Revision 4 self-score (conservative — two citation defects in a load-bearing evidence table
survived a baseline and three review rounds, so technical correctness is not scored as clean):**

| Criterion | Max | Score | Remaining weakness |
|---|---|---|---|
| Fidelity to the audit gap and completeness | 20 | 19 | Unchanged: G-10 covered plus the boot-halt path the gap implies but does not name; the field maps still live in the 09-12 plan by design, behind a gated re-derivation. |
| Technical correctness and evidence grounding | 20 | **18** | Every kernel anchor was re-derived by `grep -n` on installed source this revision (`:989`, `:999-1001`, `:1003`, `:1024`, `:1026`, `:1028`, `:1031`, `:1033-1034`, `:1036`, `:1039`) and the method name and `:1038`/"11 lines" drift are fixed throughout. Deducted 2, not 1: a wrong method name in the §2 evidence table survived three rounds, which is evidence about this plan's citation self-checking, and the ~40 09-12 citations are still gated rather than paid. |
| Implementation specificity and feasibility | 15 | 14 | The detail ladder is literal; step 0 is a completable checklist with a stop condition; the 3b fixture shape is now specified to the class, the config field and the cache call, with a named positive control. Deducted 1: the tests have not been executed, and the smallest accepted `PositiveFloat` timeout is the implementer's to confirm at model-validation time. |
| Acceptance criteria and validation quality | 20 | 19 | Twelve items; the cross-assertion in 13d step 3b makes the ladder falsifiable rather than merely exercised; the fixture spec adds an emulator-latch assertion on the portfolio case. Live proof still lands after merge. |
| Autonomous operation, failure handling, recovery | 15 | 15 | An unattributable boot-halt still alerts with a generic detail — the ladder can degrade without ever swallowing the signal. |
| Portfolio objective alignment, scope, dependencies | 10 | 9 | Unchanged, with the architect's deduction accepted as permanent (round-2 disposition 5, round-3 disposition 5). |
| **Total** | **100** | **94** | |

**Latest score:** 94 (revision 4 self-score). Round-3 peer scores **95** (hunter) and **95**
(architect); readiness is the lower, **95**. Round-2 peer scores 98 and 97.
**Readiness: NOT READY — round 4 peer review pending.**
**Blockers carried forward: R-1 and R-2 (strategy-lead rulings) remain blockers on 13b/13c.
They are not waivable by a review and are not relaxed by this revision.** 13d remains
independently actionable with no blocker.

### Round 4 reconciliation and Revision 5 (coordinator edit, 2026-09-21)

Round 4 scores: trading-bot-architect 99 → **100** after reconciliation (the withheld point was
unavailable evidence — no measured cost exists because the bot has not traded since 09-15 — now a
note, not a deduction); silent-failure-hunter 95 → **99** after reconciliation (four points awarded
as not fixable by any plan change; one REAL defect named: §7 13d step 3b framed the minimum accepted
`timeout_connection` as something to discover, although `PositiveFloat = Annotated[float,
Meta(gt=0.0)]` at `nautilus_trader/common/config.py:57` already settles it).

Revision 5 is a one-sentence edit to §7 13d step 3b citing that definition and fixing the value at
`0.5`. No other text changed. Readiness stays the LOWER reviewer score until both reviewers confirm
this revision. Blockers unchanged: R-1 and R-2 (strategy-lead rulings) on 13b/13c; 13a/13d have none.


### Round 6 — ruling-application revision (2026-09-21)

Not a peer-review round: no reviewer scored this revision. It applies one external artefact —
`docs/evidence/RULING_venue_reconciliation_R1_R2_2026-09-21.md` (Revision 3), peer-ENDORSED with
no required change (`docs/evidence/reviews/RULING_R1_R2_review_2026-09-21.md:164`) — to the
sections that were written while R-1 and R-2 were still open.

| # | Source | Change made | Sections |
|---|---|---|---|
| 1 | Ruling §4 (R-1 = O4) | Recorded-else-modelled-at-fill-time fee, `feeSource` ∈ `RECORDED` / `MODELLED_AT_FILL_TIME`, θ resolved as of `record.ts_event` via a new B0 field `fee_coefficient_at_fill` (new writes) or the dated `FEE_SCHEDULE_PIN_2026-09-18.md` schedule (legacy rows), with `[2026-09-17T00:00:00Z, 2026-09-17T17:00:00Z)` named AMBIGUOUS and REFUSED rather than defaulted | §6 (new ruled-design block), §7 13b 1b/1c, §8 14-15 |
| 2 | Ruling finding 8 (R-2 condition 2) | The 09-12 plan's `order_side=BUY` hardcode (`RECONCILIATION_NATIVE_REPORTS_2026-09-12.md:66`) is recorded as a design defect to FIX, not a field map to copy: both reports take `record.order_side` (`exec/client.py:670`, docstring `:663`; records returned by `fill_records_for`, `:2905`). Failure mechanism stated from source: `continuous_strategy.py:2271-2277` routes SELL to `_on_exit_order_filled`, so a mis-tagged BUY becomes a phantom entry. New RED test; step-0 rule (e) marks the line `CORRECTED-BY-RULING` | §6, §7 13b step 0(e)/1b, §8 13 |
| 3 | Ruling §4 (R-2 = R2-B conditional) | R-2's condition set widened from one item to three (C green + order-side fix + `feeSource` threaded), and the required build order written down as a non-reorderable sequence | §4, §5, §7 13b step 0b, §7 13c |
| 4 | Ruling findings 6, 7; PREREG | The verified safety facts restated as binding constraints rather than assumptions: `DailySpendLedger` is never booked from `on_order_filled`; idempotency is keyed on `venue_order_id` (`trial_day_latch.py:780`); reconciled/resolver fills stay residual and never grow `n`; `position_check_interval_secs` stays off | §6, §8 16 |
| 5 | Ruling §6 consequences | R-1/R-2 recorded as RULED with the artefact path; 13a demoted from ruling-submission to verification, with two new read-only steps (fee-window bucket and `order_side` per record); §12 blockers section rewritten | §4, §5, §7 13a, §12 |
| 6 | Ruling §7 | The one limit the ruling names for itself — a THIRD unpinned θ drift would make the legacy fallback confidently wrong — carried forward as a named open question rather than absorbed silently | §12 |

**Blockers after this revision: none.** R-1 and R-2 were the only two, and both are RULED. 13c's
three conditions are sequenced work inside this plan, not external permission. **No readiness
claim is made here:** this revision has not been peer-reviewed, and readiness remains whatever the
next review round establishes. Scope, exclusions, deployment and rollback are unchanged — every
edit above is additive to an existing increment; no increment was added, removed or renumbered.

### Round 7 — review-application revision (2026-09-21)

Applies the two required changes from the round-6 records
(`reviews/AUD-13-r6-silent-failure-hunter.md`, `reviews/AUD-13-r6-trading-bot-architect.md`).
Not a peer-review round: no reviewer has scored this revision, and no readiness claim is made.

| # | Source | Change made | Sections |
|---|---|---|---|
| 1 | hunter (MATERIAL-leaning) — the fee-ambiguous-window refusal was anonymous, contradicting §6's own "no refusal may be indistinguishable" rule | Named it in the pattern of the existing latches: latch key / reason code `fee_coefficient_ambiguous`, WARN alert `event="reconciliation_refusal"` with the fixed enum `detail="FEE_COEFFICIENT_AMBIGUOUS"`, carrying the record's `venue_order_id` (`exec/client.py:667`) redacted through `_redact_order_id` (`:414-416`); reusing `record_venue_disagreement` for it is forbidden explicitly. The counts line now breaks `refusals=<n>` out per cause. New RED test `test_the_ambiguous_fee_window_refusal_is_observably_distinct_from_the_other_latches` drives all three refusals in ONE reconciliation and asserts three different keys, details and counters. New acceptance item 17 | §6 (ruled-design block, regression detector), §7 13b step 1b, §8 17 |
| 2 | architect (MINOR-to-moderate) — module ownership of the dated schedule and the as-of-`ts_event` resolver was unspecified, permitting a silent fork into `exec/client.py` | Pinned to `src/breezy/adapters/polymarket_us/fees.py`, beside `MAKER_FEE_COEFFICIENT` (`:77`) and `DOCUMENTED_TAKER_FEE_COEFFICIENT` (`:86`, `__all__` at `:54`) and `_fee_coefficient` (`:422`); a second lookup table in `exec/client.py` is forbidden and `polymarket_us_fee` (`:277`) is explicitly not forked or modified. The no-fork pin **reuses the census that already exists** — `test_every_in_scope_theta_site_agrees_with_its_venue_constant` (`tests/unit/test_polymarket_us_fee_schedule_pin.py:240`) over `study_theta_sites_from_source` (`:195`) — widened to cover `fees.py` and `exec/client.py` rather than adding a second pin, with `0.06` never relaxed. New step 1d and acceptance item 18 | §6 (ruled-design block), §7 13b step 1d, §8 18 |

**Blockers after this revision: none** — unchanged from round 6; both changes above are
specification detail inside existing increments. No increment was added, removed or renumbered;
scope, exclusions, deployment and rollback are untouched.

### Round 8 — review-application revision (2026-09-21)

Applies the single required change from `reviews/AUD-13-r7-trading-bot-architect.md` (round 7,
93/100, no blockers). Not a peer-review round: no reviewer has scored this revision, and no
readiness claim is made.

| # | Source | Change made | Sections |
|---|---|---|---|
| 1 | architect (technical/evidence-grounding) — the round-7 no-fork pin asked the existing AST census to see a composite dated schedule, which its extractor cannot parse, so step 1d's RED test and item 18's acceptance were not buildable against the scanner that exists | Took the reviewer's recommended (cheaper) option: the schedule is encoded as individually-named scalar `Decimal` constants in `fees.py` — one new literal `_POST_DRIFT_TAKER_FEE_COEFFICIENT` = `0.0695`, the pre-drift branch reusing the existing `DOCUMENTED_TAKER_FEE_COEFFICIENT` (`fees.py:86`) with **no duplicate `0.06` literal**, and separately-named `_NS` boundary constants that deliberately do not match the name filter — so the census sees both coefficients with **no parser change** to `_literal_decimal` (`:156-172`) / `_module_level_bindings` (`:175-188`). Two corrections to the review's own sketch, verified in source: `_THETA_NAME` (`:128`) is **end-anchored**, so the suggested `..._BEFORE_20260917`/`..._FROM_20260917` names would NOT match; and `study_theta_sites_from_analysis_scripts` (`:212-220`) globs `scripts/analysis/*.py` only, so the src-side pin calls `study_theta_sites_from_source` directly rather than widening `STUDY_THETA_BY_VENUE`, leaving that exact-set and its test (`:240-252`) untouched. Step 1d's RED test is now concrete against the real API (function, arguments, returned 4-tuple shape, both asserted frozensets, and why it is RED today); the `0.0695` member is an enumerated dated exception citing `docs/evidence/venue/polymarket_us/FEE_SCHEDULE_PIN_2026-09-18.md`, admitted under the file's own "widen the expected set, never relax `==`" policy (`:16-24`, `:85`) and mirroring its existing post-drift member (`:108-120`) | §6 (ruled-design block, new binding Encoding rule), §7 13b step 1d, §8 18 |

**Blockers after this revision: none** — unchanged from round 7. The change is specification
detail inside an existing increment; no increment was added, removed or renumbered, and scope,
exclusions, deployment and rollback are untouched.

<!-- COORDINATOR FINAL STATUS — appended after review; everything above this line is the reviewed revision -->

## Coordinator final status (2026-09-22) — authoritative

This block supersedes any score or readiness wording in §13 above, which plan revisers wrote
before review closed.

- **Reviewed revision sha256** (file content above the marker line): `7cc2d01e0e0dee1fe4778dcf72175af49e6c5fc2854fb94b71c6b7c2bd6b827e`
- **Baseline self-score:** 86/100
- **Final score (lowest reviewer, never averaged):** 100/100
  - `silent-failure-hunter` round 8: 100/100 — `reviews/AUD-13-r8-silent-failure-hunter.md`
  - `trading-bot-architect` round 8: 100/100 — `reviews/AUD-13-r8-trading-bot-architect.md`
- **Readiness:** **READY**
- **Unresolved blockers / notes:**
  - None. R-1 and R-2 are RULED and peer-ENDORSED (`docs/evidence/RULING_venue_reconciliation_R1_R2_2026-09-21.md`). Build order is fixed: fee-at-fill field + `feeSource` → order-side fix → characterisation test → 13b/13c.
- **Full review history:** 16 records, `reviews/AUD-13-r*-*.md`
- Planning only. Nothing in this plan has been implemented.
