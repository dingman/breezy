# AUD-13a — reconciliation evidence pack (durable-record census, R-1 O4 fee buckets, citation re-derivation)

Status: VERIFICATION ONLY — no code changed. Backlog item AUD-13a of
`docs/plans/backlog/AUDIT_2026-09-21/AUD-13-native-venue-reconciliation-from-durable-records.md`
(§5, §7 "AUD-13a" steps 1-3c, §7 13b step 0 table, §8 item 12). Binding ruling:
`docs/evidence/RULING_venue_reconciliation_R1_R2_2026-09-21.md` (Revision 3; R-1 = O4,
R-2 = R2-B conditional). 13d is merged (`364ef86`) with its endorsed amendment
`AUD-13d-AMENDMENT-2026-09-24.md`; nothing here touches 13d.

Tree: `c527439` (worktree `backlog/aud-13a-reconciliation-evidence-2026-09-24`).
Installed Nautilus: `nautilus_trader-1.231.0.dist-info` (unchanged from the 09-12 plan).

**Method, and what was NOT done.**
- Store: `~/.local/share/breezy/state/exec_polymarket_us.sqlite`, opened `mode=ro` only
  (table `state`, 91 keys at read time, 2026-09-24 ~23:15Z). Every fill record was decoded
  through the tree's own `DurableFillRecord.from_bytes` (`exec/client.py:725`) under
  `systemd-run --user --scope -p MemoryMax=4G`, `PYTHONPATH=<worktree>/src`. Nothing was written.
- Logs: `~/.local/share/breezy/logs/breezy-trade-*.log` and `journalctl` (read-only).
- **No venue call was made.** Every "venue" fact below is either a durably recorded venue
  read (the store's `startup_evidence` key, a names-only key tree) or a node log line. Items
  that need a fresh venue read are listed as gaps (§8).
- Venue order ids are shown through the module's own redaction form (`_redact_order_id`,
  `exec/client.py:415-417`, 4-char prefix + `…`); client order ids are truncated. No credential
  was read.

---

## 1. Durable fill-record census (plan §7 13a steps 2, 3b, 3c)

9 records under `exec/polymarket_us/fill/*`, 9 matching `fill_index/*` entries (one id each),
all 9 decode cleanly through `DurableFillRecord.from_bytes`. O4 columns apply the ruling's §4
text literally: `fee_reconciled is True` AND `venue_fee_raw` present ⇒ `RECORDED`; else θ as of
`ts_event` from the dated schedule (`< 2026-09-17T00:00Z` ⇒ 0.06; `>= 2026-09-17T17:00Z` ⇒
0.0695; `[00:00Z, 17:00Z)` on 09-17 ⇒ REFUSE), banker's-rounded to the cent exactly as
`polymarket_us_fee` / `_round_bankers` (`fees.py:277-316`, `:467-475`).

| venue id | client id (trunc) | instrument (`.POLYMARKET_US` elided) | side | qty | orderQty | cost = px | cumFee | feeRec | venueFeeRaw | tradeId | ts_event (UTC) | fee bucket | O4 feeSource | O4 commission | model@0.06 | model@0.0695 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| CEBP… | O-20260911-202029… | sfohigh-2026-09-11-gte70lt71f | BUY | 1 | **absent** | 0.22 | 0 | false | null | **absent** | 2026-09-12T02:23:50Z | PRE | MODELLED_AT_FILL_TIME | 0.01 | 0.01 | 0.01 |
| CFJ4… | O-20260913-170346… | miahigh-2026-09-13-gte91lt92f | BUY | 1 | 1 | 0.70 | 0 | false | null | GET-synthetic | 2026-09-13T17:03:49Z | PRE | MODELLED_AT_FILL_TIME | 0.01 | 0.01 | 0.01 |
| CGW2… | O-20260915-180004… | mdwhigh-2026-09-15-gte80lt81f | BUY | 1 | 1 | 0.11 | 0.0100 | true | "0.0100" | venue | 2026-09-15T18:00:04Z | PRE | RECORDED | 0.0100 | 0.01 | 0.01 |
| CGW8… | O-20260915-181219… | miahigh-2026-09-15-gte92lt93f**^no** | BUY | 1 | 1 | 0.09 | 0.0000 | true | "0.0000" | venue | 2026-09-15T18:12:19Z | PRE | RECORDED | 0.0000 | **0.00** | **0.01** |
| CGWD… | O-20260915-182333… | mdwhigh-2026-09-15-gte82lt83f | BUY | 1 | 1 | 0.24 | 0.0100 | true | "0.0100" | venue | 2026-09-15T18:23:33Z | PRE | RECORDED | 0.0100 | 0.01 | 0.01 |
| CGY0… | O-20260915-201206… | sfohigh-2026-09-15-gte71lt72f | BUY | 1 | 1 | 0.44 | 0.0100 | true | "0.0100" | venue | 2026-09-15T20:12:06Z | PRE | RECORDED | 0.0100 | **0.01** | **0.02** |
| CMRS… | O-20260921-191836… | miahigh-2026-09-21-gte88lt89f**^no** | BUY | 1 | 1 | 0.12 | 0.0100 | true | "0.0100" | venue | 2026-09-21T19:18:36Z | POST | RECORDED | 0.0100 | 0.01 | 0.01 |
| CMSN… | O-20260921-202135… | sfohigh-2026-09-21-gte66lt67f | BUY | 1 | 1 | 0.35 | 0.0200 | true | "0.0200" | venue | 2026-09-21T20:21:35Z | POST | RECORDED | 0.0200 | **0.01** | **0.02** |
| CNC3… | O-20260922-180001… | mdwhigh-2026-09-22-gte62lt63f**^no** | BUY | 1 | 1 | 0.12 | 0.0100 | true | "0.0100" | venue | 2026-09-22T18:00:01Z | POST | RECORDED | 0.0100 | 0.01 | 0.01 |

Counts, per 13a's acceptance questions:

| Question | Answer |
|---|---|
| `tradeId` present | 8/9 (7 venue `Execution.tradeId`, 1 `GET-<vid>` synthetic); **absent on CEBP…** ⇒ 13b's `GET-<venue_order_id>` fallback (09-12 §3) is exercised by exactly this record |
| `orderQty` present | 8/9; **absent on CEBP…** ⇒ `quantity = cumulative_qty` (L-2 unit declaration, terminal filled portion) |
| `venueFeeRaw` present | 7/9 (all create-path). **O3 is reachable** for 7 records, not unreachable as the 09-12 plan assumed from its one record |
| `feeReconciled` true | 7/9 (the same 7) |
| O4 `RECORDED` / `MODELLED_AT_FILL_TIME` / REFUSE | **7 / 2 / 0** |
| Records inside `[2026-09-17T00:00Z, 17:00Z)` | **0** — the `fee_coefficient_ambiguous` refusal fires on no record in today's store |
| `order_side == SELL` | **0** — the order-side fix (ruling finding 8) has a live blast radius of zero records today; it is a pre-emptive fix for R-8/R-9 exits, which have never filled |
| NO-leg (`^no`) records | **3/9** (CGW8…, CMRS…, CNC3…), all `orderSide=BUY` on the `^no` instrument — see finding F5 |
| `fee_coefficient_at_fill` / `feeSource` fields on disk | 0/9 — not yet built (grep: no occurrence in `src/` or `tests/`) |

## 2. Findings

**F1 — Venue-attested fees independently corroborate the dated θ schedule.** Three RECORDED
fees discriminate between the two coefficients (bold above): CGW8… (p=0.09) and CGY0…
(p=0.44) on 2026-09-15 match 0.06 and contradict 0.0695; CMSN… (p=0.35) on 2026-09-21 matches
0.0695 and contradicts 0.06. The other four RECORDED fees are consistent with their bucket.
This is venue evidence the ruling did not have (it cited the offer-tape pin only) and it agrees
with `FEE_SCHEDULE_PIN_2026-09-18.md` on both sides of the drift. It says nothing about the
AMBIGUOUS window (no fill falls in it).

**F2 — The ruling's θ-at-fill-time fix changes no number in today's store.** Both legacy
records model to 0.01 under EITHER coefficient (p=0.22: 0.010296 / 0.011926; p=0.70: 0.0126 /
0.014595). The mechanism stays mandatory (ruling §4), but the 13b RED test
`test_a_pre_drift_fill_reconciled_on_a_post_drift_boot_books_the_fill_time_coefficient` must use
a **constructed** price where the coefficients diverge at the cent — e.g. p=0.44 (0.01 vs 0.02)
or p=0.09 (0.00 vs 0.01), both of which have real venue-attested counterparts in F1. A test
built on CEBP…'s own p=0.22 would pass under the defect it exists to catch.

**F3 — Resolver-path `ts_event` is discovery time, not fill time.** `_resolve_accept_fill`
stamps `ts_event=now_ns` (`exec/client.py:2229-2244`, comment "the RESOLVER's own wall-clock
discovery time … never a venue-reported execution time"); the create path stamps the venue
execution time (`ts_event=fill.ts_event`, `exec/client.py:3774`). For the two legacy
(resolver) records the true fill lies in `[intent created_ns, ts_event]`:
CEBP… `[2026-09-11T20:20:29Z, 2026-09-12T02:23:50Z]`, CFJ4… `[2026-09-13T17:03:46Z, 17:03:49Z]`
(intent history `5af9eba3…`, `428709da…`) — both wholly PRE, so their bucket is certain.
**Consequence for 13b (not decided here, carried to the implementer):** (a) a future resolver
record whose `[created_ns, ts_event]` interval straddles a schedule boundary or touches the
AMBIGUOUS window cannot be bucketed from `ts_event` alone; the ruling's "θ AS OF `ts_event`"
is exact only for create-path records. (b) The B0 `fee_coefficient_at_fill` written at the
**resolver** site is the θ of the `Instrument` at discovery time, which has the same
upper-bound property. Neither affects any record in the store today.

**F4 — The gating rule admits ZERO of the 9 records today.** The store's durably recorded venue
positions read (`exec/polymarket_us/startup_evidence`, `ts_ns` = 2026-09-24T23:10:29Z,
`eof_complete=true`, `position_read_refused=false`) carries `positions: []`, and every record's
instrument is a settled climate day (09-11 … 09-22). So 13b's §8 items 5/10/11 ("`N ≥ 1` order
and fill reports", "live proof on the next boot", "the `feeSource` the first reconciled fill
carried") are **not obtainable from the current store**: they need a new fill that is still open
at a reconciling boot. `continuous_rung_hold/halt` currently holds
`reason=policy_halt` ("Ruling A1 2026-09-21: pm_us_crh_v4 may not SEND orders"), so no new fill
can occur while that halt stands. All engine-driven acceptance evidence for 13b (incl. the 09-11
order-2 replay, 13b step 4) must be a **constructed fixture**; the CEBP… record can seed the
fixture's shape but can never be reconciled live again.

**F5 — DESIGN INPUT (escalated, not a citation fix): the 09-12 §3 input path misses every NO-leg
record.** 09-12 §3 "Inputs" routes `slug → _find_instrument → fill_records_for`.
`_find_instrument(slug, *, leg="yes")` (`exec/client.py:2843`) defaults to the YES leg, while 3
of 9 records are indexed under `^no` instruments. `_map_position` (`exec/client.py:2742`) already
resolves a NO-leg venue position to the `^no` instrument (`leg == "no"` branch → `_find_instrument
(slug, leg="no")`) and filters settled positions. 13b must gate on the **leg-resolved instrument
id that `_map_position` produces**, not a YES-leg re-lookup of the slug, or every NO-side holding
silently falls back to EXTERNAL inference. NO-side trading post-dates the 09-12 plan
(`no_side/position_shape_captured`, ruling `RULING_no_side_position_shape_2026-09-16.md`).

**F6 — "halt absent" in the 09-12 goal state (item 6) and AUD-13 §8 item 5 needs a sharper
observable.** The halt key is present today for a non-reconciliation reason (F4). The live
check must be "no `continuous_rung_hold/duplicate_fill/*` key written and the halt record's
`reason` is unchanged", not "the halt key is absent". Today: 0 `duplicate_fill/*` keys.

**F7 — `venue_id/*` rows and fill records are different sets (expected).** 9 `venue_id/*` rows:
CEBP… has none (pre-A1 record); CP05… (intent `5e50e0d9…`, MIA 09-23) has a row but no fill —
its intent retired `STATUS_REPORT_ZERO_FILL_TERMINAL`. The 09-12 "0 of 25 keys" statement is
stale (now 9 of 91). A 13b F3 guard (`client_order_id_for(vid)` vs `record.client_order_id`)
must treat a missing map row as "no disagreement", or CEBP… would be refused; all 8 present
rows agree with their records.

**F8 — The prior-day-instrument assumption is FALSE at least once.** 09-12 UNVERIFIED item 4
("a prior-day instrument is in the cache at every boot") is contradicted on 2026-09-24:
`breezy-trade-20260924T185902Z.log:195,559-562` (`miahigh-2026-09-23…` "not in the cache;
retrying") and `breezy-trade-20260924T201520Z.log:319` ("not in the cache and could not be
loaded"). Native reconciliation skips a report whose instrument is absent
(`live/execution_engine.py:3056-3062`, returns `True`) and `_map_position` refuses the position,
so an absent instrument degrades to "no report, no position" — fail-closed, but a 13b counts line
should expose it (it would otherwise read as `gated_out`).

## 3. O1 evidence requirement — who reads `Position.realized_pnl` / `OrderFilled.commission` (13a step 3)

`/usr/bin/grep -rn` over `src/` and `scripts/` at `c527439`. **The O1 premise ("no Breezy artefact
reads them") remains FALSE, exactly as ruling finding 4 found**; nothing new reads them since.

| Site | Reads | Live? |
|---|---|---|
| `settlement/exit_guard.py:94-97,148` | `TradeReturnInput.realized_pnl`, specified as Nautilus `Position.realized_pnl` (fee-inclusive, seeded from `-fill.commission`) | No actor: `compute_trade_returns` has no `src/` caller (`roi_bound.py:76` imports only `EXCLUSION_FRACTION_CEILING`; `tape_records.py:44` only `settlement_price_for_leg`) |
| `strategy/current_rung_hold/exit_wiring.py:219` | `event.commission` → `latch.record_exit(... fee)` on an EXIT fill | Wired, exit seam UNARMED |
| `strategy/current_rung_hold/continuous_strategy.py:2434` | `event.commission` in the duplicate-fill diagnostic | Live |
| `continuous_strategy.py:342-364`, `:2343-2375` (`_per_contract_reconciled_fee`, `_recorded_fee_for`) | the DURABLE record, "Deliberately NEVER `event.commission`" (`:358`, `:2359`) | Live — scoring is immune |
| `resting_ladder.py:303`, `harness_probe.py:245`, `strike_ladder.py:273`, `forecast_edge.py:191` | `event.commission` in a log string only | Legacy strategies |
| `scripts/analysis/run_weather_strategy_backtests.py:593,996-997` | `Position.realized_pnl` | Backtest only |
| `settlement/trial_scorer.py:10-15` | documents that it does NOT use `realized_pnl` | — |

## 4. The four (five) UNVERIFIED items of `RECONCILIATION_NATIVE_REPORTS_2026-09-12.md:137-142`

| # | Item | Status at `c527439` | Evidence |
|---|---|---|---|
| 1 | pyo3 `process_mass_status_for_reconciliation` behaviour | **STILL UNVERIFIED** | Rust; stub `core/nautilus_pyo3.pyi:10597`, called at `live/reconciliation.py:668`. Only 13b's engine-driven contract test settles it |
| 2 | Was the 09-12T02:23:50Z resolver `OrderFilled` applied or dropped? | **SETTLED — DROPPED** | `breezy-trade-20260912T022344Z.log:403-404`: `Order with ClientOrderId('O-20260911-202029…') not found in the cache` then `[ERROR] … Cannot apply event to any order … VenueOrderId('CEBP…') not found in the cache` (`execution/engine.pyx:1282-1287`). The same boot had already reconciled `0 orders, 0 fills` and generated an inferred fill (`:277`, `:282`). F6 of the 09-12 plan is observed, not hypothesised |
| 3 | Does the venue populate `commissionNotionalTotalCollected` on the **GET** order response? | **STILL UNVERIFIED (GET); present on CREATE** | Names-only key trees in the store (`resolver/428709da…`, `resolver/5e50e0d9…` `createDetail`) and logs (`breezy-trade-20260913T165011Z.log:528,533`, `…20260923T165046Z.log:938,943`) show the key under `executions[].order` of the **create** response; no GET key tree was ever logged. 7 create-path records carry a venue fee (§1). Settling the GET form needs a live venue read — gap G1. Per ruling §6 this no longer gates 13b |
| 4 | Is a prior-day instrument in the cache at every boot? | **FALSIFIED (once)** | F8 |
| 5 | PREREG halt-key naming divergence | **STILL DIVERGENT, not re-ruled** | PREREG v3 `:93` names `continuous_rung_hold/family_halt/duplicate_fill`; code `trial_day_latch.py:290-291` (`DUPLICATE_FILL_KEY_PREFIX`, `FAMILY_HALT_KEY = "continuous_rung_hold/halt"`) |

## 5. Nautilus report fields 13b must fill (installed 1.231.0, verbatim signatures)

`OrderStatusReport.__init__` — `execution/reports.py:181-214`; guards `quantity > 0`,
`filled_qty >= 0` (`:216-217`). `FillReport.__init__` — `execution/reports.py:667-683`; guard
`last_qty > 0` (`:685`); `commission` is a required `Money` ("If no commission then use a zero
`Money`", `:639-641`). `FillReport.__eq__` keys on `account_id, instrument_id, venue_order_id,
trade_id, ts_event` (`:705-716`) — so `trade_id` AND `ts_event` must be byte-stable across boots.

| Field (required unless marked) | Source per durable record (09-12 §3 as corrected by ruling + this pack) | Available in store? |
|---|---|---|
| OSR `account_id` | client's account id | n/a (runtime) |
| OSR/FR `instrument_id` | `record.instrument_id` (leg-resolved; F5) | 9/9 |
| OSR/FR `venue_order_id` | `record.venue_order_id` | 9/9 |
| OSR/FR `order_side` | **`record.order_side`** (CORRECTED-BY-RULING, finding 8) | 9/9 (all BUY) |
| OSR `order_type` / `time_in_force` / `order_status` | `LIMIT` / `IOC` / `FILLED` (09-12 §3) | constant |
| OSR `quantity` | `record.order_qty`, else `cumulative_qty` (L-2) | 8/9 order_qty; CEBP… falls back |
| OSR `filled_qty`; FR `last_qty` | `record.cumulative_qty` | 9/9 (all 1) |
| OSR `report_id`, `ts_init`; FR `report_id`, `ts_init` | fresh `UUID4`, clock | runtime |
| OSR `ts_accepted`, `ts_last`; FR `ts_event` | `record.ts_event` (F3: discovery time on resolver records) | 9/9 |
| OSR `client_order_id` (opt.) / FR `client_order_id` (opt.) | `record.client_order_id` — the whole point; never `None` | 9/9 |
| OSR `price`, `avg_px` (opt.); FR `last_px`, `avg_px` (opt.) | `cumulative_cost / cumulative_qty` | 9/9 |
| FR `trade_id` | `record.trade_id`, else `GET-<venue_order_id>` | 8/9; CEBP… falls back |
| FR `commission` | **O4**: RECORDED ⇒ `Money(cumulative_fee, USD)`; else modelled at fill-time θ; AMBIGUOUS/unpinned ⇒ REFUSE | 7 RECORDED / 2 MODELLED / 0 REFUSE |
| FR `liquidity_side` | `TAKER` (09-12 §3) | constant |
| OSR/FR `venue_position_id` (opt.) | `None` (NETTING) | — |

## 6. Citation table — every `file:line` in `docs/plans/RECONCILIATION_NATIVE_REPORTS_2026-09-12.md` (13b step 0, §8 item 12)

Enumerated mechanically (`/usr/bin/grep -noP` over the file: 135 backtick occurrences), de-duplicated
to one row per distinct anchor; "Plan lines" lists every line it occurs on. Each re-derived by
locating the named symbol at `c527439` / installed 1.231.0. Status vocabulary per AUD-13 §7 13b
step 0: `UNCHANGED` / `MOVED → :n` / `SYMBOL GONE` / `CORRECTED-BY-RULING`; `UNCHANGED*` = same
code, original citation off by 1-3 lines. **`SYMBOL GONE`: none.** One design row is escalated
(F5).

### 6a. Nautilus-side (installed 1.231.0 — version unchanged)

| 09-12 citation | Plan lines | Symbol | Anchor at HEAD | Status |
|---|---|---|---|---|
| `live/execution_client.py:439-511`, `:439` | 9, 29, 133 | `generate_mass_status` (gathers at `:500-502`) | `:440-511` | UNCHANGED* |
| `live/execution_engine.py:1670`, `1670-1800` | 9, 29, 133 | `reconcile_execution_state` | `:1670` | UNCHANGED |
| `:1857`, `1857-1947` | 9, 29, 133 | `_reconcile_execution_mass_status` | `:1857` | UNCHANGED |
| `:1880-1881` | 68 | order-report loop `for venue_order_id, order_report in mass_status.order_reports.items()` | `:1880` | UNCHANGED |
| `:1950-2005` | 29, 133 | `_adjust_mass_status_fills` | `:1951` | UNCHANGED* |
| `:3038`, `3038-3107` | 9, 29, 133 | `_reconcile_order_report` | `:3038` | UNCHANGED |
| `:3053-3060` | 38 | instrument-absent skip in `_reconcile_order_report` | `:3056-3062` | UNCHANGED* |
| `:3109-3140`, `:3109` | 10, 29, 133 | `_resolve_client_order_id` | `:3109` | UNCHANGED |
| `:3133-3134` | 10 | `ClientOrderId(UUID4().value)` synthesis | `:3134-3136` | UNCHANGED* |
| `:3321`, `3321-3400` | 9, 29, 133 | `_reconcile_fill_report` | `:3321` | UNCHANGED |
| `:3336-3345` | 12, 39 | overfill reject → `return False` | `:3334-3341` | UNCHANGED |
| `:3402-3482` | 12, 133 | `_check_and_skip_duplicate_fill` | `:3400` | UNCHANGED* |
| `:3485-3506` | 133 | `_generate_inferred_fill` | `:3485` | UNCHANGED |
| `:3512-3566` | 29, 133 | `_generate_order` | `:3512` | UNCHANGED |
| `:3551-3566` | 11 | `get_external_order_claim` → `EXTERNAL` | `:3551` | UNCHANGED |
| `:2466-2560` | 29, 133 | `_reconcile_position_report_netting` | `:2466` | UNCHANGED |
| `:2472-2477` | 38 | instrument-absent skip (netting) | `:2472-2477` | UNCHANGED |
| `:1022` | 97, 133 | `_create_flat_position_report` | `:1022` | UNCHANGED |
| `:187` | 133 | `reconciliation_lookback_mins` | `:187` | UNCHANGED |
| `live/reconciliation.py:424` | 14, 133 | `commission=report.commission` | `:424` | UNCHANGED |
| `live/reconciliation.py:434-540 (506-508)` | 14, 133 | `create_inferred_order_filled_event`; `client.calculate_commission` | `:434`; `:506` | UNCHANGED |
| `live/reconciliation.py:611-700` | 104, 133 | `adjust_fills_for_partial_window` / pyo3 call | `:612`; `:668` | UNCHANGED* |
| `live/config.py:97-121` | 56, 133 | `LiveExecEngineConfig` docstring (defaults) | docstring `:97-121`; fields `reconciliation :177`, `generate_missing_orders :183`, `inflight_check_interval_ms :184`, `open_check_interval_secs :188`, `position_check_interval_secs :195` | UNCHANGED |
| `execution/reports.py:95-120` | 133 | `OrderStatusReport` | `:95` (init `:181`) | UNCHANGED |
| `execution/reports.py:619-704`, `639-641,676,700` | 14, 133 | `FillReport`, `commission` | `:619`, `:639-641`, `:676`, `:700` | UNCHANGED |
| `execution/engine.pyx:532-564` | 11, 133 | `register_external_order_claims` | `:532` | UNCHANGED |
| `execution/engine.pyx:1245-1315` | 133 | `_handle_event` | `:1245` | UNCHANGED |
| `execution/engine.pyx:1281-1286` | 40, 139 | "Cannot apply event to any order" | `:1282-1287` | UNCHANGED* |
| `execution/engine.pyx:1452-1562`, `:1562` | 11, 29, 133 | `_determine_position_id`; `PositionId(f"{instrument_id}-{strategy_id}")` | `:1452`; `:1562` | UNCHANGED |
| `execution/client.pyx:165-193` | 14, 133 | `calculate_commission` | `:165` | UNCHANGED |
| `system/kernel.py:310-329` | 13, 133 | cache DB redis-only | `:310-329` (`:312`, `:327`) | UNCHANGED |
| `trading/config.py:91` | 11, 133 | `external_order_claims` | `:91` | UNCHANGED |
| `trading/trader.py:435` | 11, 29, 79, 133 | `register_external_order_claims(strategy)` | `:435` | UNCHANGED |
| `core/nautilus_pyo3.pyi:10597` | 138 | `process_mass_status_for_reconciliation` | `:10597` | UNCHANGED |

### 6b. Breezy-side (`src/`, `tests/`, docs, logs)

| 09-12 citation | Plan lines | Symbol | Anchor at HEAD | Status |
|---|---|---|---|---|
| **`:66` §3 "Outputs per record" `order_side=BUY`, `commission=<RULING R1>`** | 66 | report field map | `record.order_side`; O4 commission (§5) | **CORRECTED-BY-RULING** (finding 8 + R-1 O4) — do not copy as written |
| §3 "Inputs" `slug → _find_instrument → fill_records_for` (`:62`) | 62, 29 | input path | use `_map_position`'s leg-resolved id (`exec/client.py:2742`) | **ESCALATED DESIGN INPUT (F5)** |
| `exec/client.py:1946`, `1946-1959` | 29, 46, 132 | `generate_order_status_reports` | `:2606-2634` | MOVED → :2606 |
| `exec/client.py:1961`, `1961-1973` | 29, 47, 132 | `generate_fill_reports` | `:2636-2654` | MOVED → :2636 |
| `exec/client.py:1950-1972` (E docstrings) | 82 | both stub docstrings | `:2610-2653`; stale phrase "there are no fills, because there are no orders" absent (0 hits in `src/`) | MOVED → :2610 (E done) |
| `exec/client.py:1975-2014`, `1986-2004` (F1) | 35, 132 | `generate_position_status_reports`; positions-read refusal | `:2656-2696`; refusal `:2667-2687` | MOVED → :2656 / :2667 |
| `exec/client.py:1818` | 107 | `generate_mass_status` override | `:2478` | MOVED → :2478 |
| `exec/client.py:2131` | 29 | `_find_instrument` | `:2843` | MOVED → :2843 |
| `exec/client.py:2302-2329`, `2312-2328` (F2), `2275-2350` | 29, 36, 132 | `record_fill` / `fill_records_for` / `_read_fill_index` | `:2996` / `:3023-3050` (refusals `:3040-3049`) / `:3052-3071` | MOVED → :3023 |
| `exec/client.py:2331-2350` | 62 | "no prefix scan" | module docstring `:99`; `:3007`; `:3140`; `_store_get :3104` | MOVED |
| `exec/client.py:347-350` | 48, 132 | venue-id map key prefix | `VENUE_ORDER_ID_KEY_PREFIX :381` (fill prefixes `:385`, `:389`) | MOVED → :381 |
| `exec/client.py:2253-2267`, `2269-2273`, `2253-2273` | 48, 132 | `record_venue_order_id`, `client_order_id_for` | `:2974`, `:2990` | MOVED → :2974 / :2990 |
| `exec/client.py:2909`, `2909-2918` | 76, 132 | create-outcome `record_venue_order_id` call | `:3720` (resolver terminals `:2112`, `:2271`) | MOVED → :3720 |
| `exec/client.py:478-586` | 49, 77, 132 | `DurableFillRecord` | `:659-783` (`order_side :688`, `ts_event :693`, `trade_id :699`, `order_qty :703`, `from_bytes :725`) | MOVED → :659 |
| `exec/client.py:1551-1656`, `:1620` | 50, 40, 132 | resolver fill write site; `record_fill` | `_resolve_accept_fill :2158-2320`; record `:2215-2247`; `record_fill :2250` | MOVED → :2158 / :2250 |
| `exec/client.py:1607-1618`, `:1607` | 52, 77 | resolver `cumulative_fee=ZERO, fee_reconciled=False` | `:2227-2228` | MOVED → :2227 |
| `exec/client.py:2769-2853`, `:2805`, `:2793` | 50, 77, 132 | create-path fill write; `record_fill`; record construction | `DurableFillRecord(` `:3759`; `record_fill :3779` (block `:3733-3790`) | MOVED → :3759 / :3779 |
| `exec/client.py:2513-2570` | 70, 132 | `calculate_commission` | `:3343` | MOVED → :3343 |
| `exec/client.py:2647-2716` | 70 | `_submit_order` gates | `:3493-3902` | MOVED → :3493 |
| `exec/client.py:1128-1131` | 97, 132 | `_has_durable_fill_record` | `:1483` | MOVED → :1483 |
| `exec/submit_chain.py:583-630`, `823-851` | 51, 132 | two-equality fee reconciliation | `_cumulative_fee_and_reconciliation :826-872`; `_commission_raw_audit :808` | MOVED → :826 |
| `exec/reports.py:233-240`, `:237` | 53, 132, 140 | `commissionNotionalTotalCollected` in `_ORDER_KEYS` | `:250` | MOVED → :250 |
| `exec/reports.py:278-297` | 132 | `_ORDER_DRIFT_ALLOWED_KEYS` / `_EXECUTION_KEYS` | `:290-300` | MOVED → :290 |
| `fees.py:200-239` | 52, 132 | `polymarket_us_fee` | `:277-316` (`_fee_coefficient :422`, `_round_bankers :467`) | MOVED → :277 |
| `runtime/node_config.py:821` | 56, 132 | `LiveExecEngineConfig(inflight_check_interval_ms=0)` | `:936` | MOVED → :936 |
| `node_config.py:718-721, 813` | 13 | `CacheConfig(database=None, …)` | `:206-220`, `:555-556`, `:811`, `:928` | MOVED |
| `runtime/trade_cli.py:397`, `:398`, `:422`, `397-398,422` | 29, 79, 132 | `add_strategy` / `build()` / `run()` | `:502` / `:503` / `:529` | MOVED → :502-503 / :529 |
| `app/trade.py:185-250` | 29, 132 | `run` composition | `run :191-391` (continuous compose `:305`) | MOVED → :191 |
| `continuous_strategy.py:790`, `790-841` | 29, 132 | `on_order_filled` | `:2237` (SELL branch `:2271`, `_on_exit_order_filled :2311`) | MOVED → :2237 |
| `continuous_strategy.py:842`, `842-899` | 29, 54, 132 | `_consume_or_flag_duplicate` | `:2376-2449` | MOVED → :2376 |
| `continuous_strategy.py:883` | 12, 29, 54, 80, 127, 132 | same-`venue_order_id` silent return | `:2432` | MOVED → :2432 |
| `continuous_strategy.py:872-882` | 55, 127 | legacy `venueOrderId: null` branch | `:2421-2431` | MOVED → :2421 |
| `continuous_strategy.py:392-420` | 132 | (no symbol named in 09-12) — fee-provenance helpers per ruling finding 3 | `_per_contract_reconciled_fee :342-364`; `_recorded_fee_for :2343` | MOVED (by ruling's reading) |
| `trial_day_latch.py:95`, `:97` | 55, 132 | trial key prefixes | `DEFAULT_TRIAL_KEY_PREFIX :117`, `CONTINUOUS_TRIAL_KEY_PREFIX :119` | MOVED → :117 / :119 |
| `trial_day_latch.py:131-132` | 132, 142 | duplicate-fill prefix / halt key | `:290-291` | MOVED → :290 |
| `trial_day_latch.py:469-511`, `:490`, `409-449` | 54, 132 | `consume_if_absent`; bucket guard; `TrialDayRecord` | `:780-826`; `TrialDayRecord :432` | MOVED → :780 / :432 |
| `composition.py:465-470`, `399-408` | 79, 132 | `CurrentRungHoldConfig(...)` construction (13c claim site) | `_station_config :387-420` (`CurrentRungHoldConfig(` `:409`, `:415`); used by both current and continuous builders (continuous `:488`, `_station_config` call `:574`) | MOVED → :387 |
| `settlement/exit_guard.py:1-30` | 97, 132 | module docstring, "no actor" | `:1-30`; still no actor (§3) | UNCHANGED |
| `position_reporting_lag.py:8-16` | 82 | E docstring | `:8-19` (already corrected by SP-3) | UNCHANGED* |
| `factories.py:777` | 82, 152 | `DailySpendLedger()` | `adapters/polymarket_us/factories.py:800` | MOVED → :800 |
| `operator_controls.py:85-92` | 152 | corrected docstring | `:85-92` | UNCHANGED |
| `tests/contract/test_exec_client_reconciliation_contract.py:89`, `167-190`, `167-230`, "786 lines" | 97, 132 | `test_pinned_nautilus_version`; `test_the_settlement_landmine_stays_disarmed_only_while_the_position_check_is_off` | `:89`; `:167-188` (pins `:184`, `:188`); 786 lines | UNCHANGED |
| `tests/unit/test_app_trade_main_permit_logging.py:115` | 89 | known clock-dependent flake | inside `test_main_logs_live_trading_permit_issued_when_both_permits_are_minted` (`:69`), assertion `:110-111` | MOVED → :110 |
| `test_polymarket_us_exec_client.py:519,…,1506` (17), `:688` | 107 | depth-2 callers via `generate_mass_status`; `never_raise` test | 23 `generate_mass_status` call lines (`:604 … :1875`); `test_the_report_generators_never_raise_into_the_native_handler :769`; **also** `test_generate_order_status_reports_still_returns_empty_when_an_order_rests :4793` (pins `[]` for a RESTING order — must stay green: a resting order has no durable fill record) | MOVED |
| `docs/evidence/grok_admission_exclusions_ack_2026-09-05.md:21-27,59` | 114 | Q2 | `:21-27`, `:59` (0 commits since 09-12) | UNCHANGED |
| `docs/evidence/GO_LIVE_BLOCKERS_2026-09-06.md:19` | 114 | GL-2 | `:19` | UNCHANGED |
| PREREG v3 `:74-78`, `:80-105` | 114 | §4a; §5 | §4a `:74`; §5 `:80` — §5.1 Amendment A1 (2026-09-20) now at `:104` | UNCHANGED (§5 extended by A1) |
| log `breezy-trade-20260912T022609Z.log:270-280` (`:273`, `:278`) | 22, 23, 135 | `0 orders, 0 fills`; inferred fill | `:273`, `:278` | UNCHANGED |

## 7. What 13b must use (inputs, fixed by this pack)

1. **Field map:** §5 above — `order_side=record.order_side`, O4 commission, `trade_id` fallback
   `GET-<vid>`, `quantity` fallback `cumulative_qty`; never the 09-12 `:66` text.
2. **Anchors:** §6b "Anchor at HEAD" column (stubs `:2606`/`:2636`; write sites `:2215`/`:3759`;
   `DurableFillRecord :659`; `polymarket_us_fee :277`, `_fee_coefficient :422`; claim site
   `composition.py:409/415`; `LiveExecEngineConfig :936` stays out of scope).
3. **Gating:** on `_map_position`'s leg-resolved `instrument_id` (F5); a missing `venue_id` row is
   not a disagreement (F7); instrument-absent must be counted distinctly (F8).
4. **Fixtures, not the live store,** for every `N ≥ 1` assertion (F4). The fee RED test uses a
   price where 0.06 and 0.0695 differ at the cent (F2).
5. **Expected live counts on today's store** if 13b shipped now: `records_considered=0`
   (venue positions empty), `refusals_fee_coefficient_ambiguous=0`, `order_reports=0`.

## 8. Gaps

- **G1** GET-response `commissionNotionalTotalCollected` population (item 3) — needs a live
  venue GET; not done (no network in this pack). Does not gate 13b (ruling §6).
- **G2** pyo3 adjuster behaviour (item 1) — only 13b's contract test can settle it.
- **G3** Current venue positions were NOT re-read; F4 relies on the store's
  2026-09-24T23:10:29Z recorded read.
- **G4** Live acceptance (AUD-13 §8 items 10, 11) is unobtainable while `policy_halt` stands and
  no position is open (F4).
- **G5** F3's resolver-path bucketing limit and F5's NO-leg gating are design inputs the
  ruling/plan do not yet state; carried to the 13b implementer and plan owner, not decided here.
