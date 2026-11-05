# Data capture and risk — implementation plan

**Status:** REVISION 2. **PARTIALLY EXECUTED — do not re-implement landed work.** P0 (`scripts/archive/backup_irreplaceable_data.py`), P1 (`runtime/quote_tape_disk_monitor.py`, `quote_tape_preflight_cli.py`), P2 (both probes — `docs/evidence/open_meteo_*`, `iem_afos_forecast_pil_probe_*`) and P5 (`docs/evidence/no_side_instrument_probe_2026-08-31.md`) have landed. P3 is superseded by `docs/plans/forecast_ingest_2026-09-01.md`. P4/P6/P7 remain open. This plan underpins LESSONS L-2 and L-3 — re-verify citations before resuming. Revision 1 was reviewed adversarially by four independent reviewers and **blocked**. This revision resolves every blocking finding, or records why a finding was rejected.

**What changed from revision 1.** Two independent null-hypothesis audits against installed `nautilus-trader==1.231.0` struck six proposals (three were already native, three shrank). Four adversarial reviews then found that revision 1 had introduced a **new critical defect while simplifying** — it silently changed the unit every risk cap is measured in — and that its kill-switch, its budget accounting, its enumeration, and its systemd exit-code contract were each unsound. §0.4 records all of it, including two claims I made that the source contradicts.

**Companion:** `docs/plans/archive/FORECAST_INGESTION_PLAN.md` (revision 2, separately peer-reviewed). **This plan does not restate or re-plan it.** §4.P3 states only the delta and the sequencing constraint.

---

## 0. Evidence status

### 0.1 Classes of claim

| Class | Method | Status |
|---|---|---|
| Repo behaviour | Direct read of source | VERIFIED, cited `file:line` |
| Installed `nautilus_trader` 1.231.0 | Direct read, plus an independent citation audit | VERIFIED where cited; line numbers corrected in §0.4 |
| Prior repo findings / evidence docs | Direct read of the committed document | VERIFIED as *what the repo asserts*, cited |
| Filesystem state (archive size, measured byte rates) | Reported, not re-measured here | `[REPORTED]` — re-measured as step 0 of the increment depending on it |
| Live endpoint behaviour (Open-Meteo, IEM AFOS, Polymarket.us book-per-side) | — | **NOT VERIFIED — no network access.** Gated behind the P2/P5 probes |

### 0.2 Findings A–H, re-verified

| Finding | Status | Design consequence |
|---|---|---|
| **A** — price history forward-only | CONFIRMED: *"Is there a public trade tape? **No.**"* (`docs/evidence/venue/polymarket_us/docs_snapshots/trader-guide_market-data_2026-08-25.md:48-52`); *"Every uncaptured day is permanently lost"* (`GO_LIVE_PLAN.md:106-116`) | Fixes P1's priority; kills one framing of P2 (§4.P2.4) |
| **C1** — degraded feed never exits | CONFIRMED: `websocket.py:678-684`; `data.py:1312-1324`; `data.py:1280-1283`; `quote_tape_cli.py:141-177` has no health path | P1 |
| **C3** — pool never observed carrying a live quote | CONFIRMED, but see §0.4-R3: the *cause* is an auth failure, not a structural defect in the smoke | P1.3 shrinks |
| **D** — cross-strategy risk hole | CONFIRMED: `risk.py:95-97`, `:116-131`; each strategy passes only its own contracts (`forecast_revision/strategy.py:168`). Already-correct and **not to be touched**: `exclusive_conflict` (`risk.py:141-154`), `WeatherBucketFacts.contains` (`weather_bucket_facts.py:64-73`) | P4 |
| **E** — SHORT_YES has no legal expression | CONFIRMED for the order path. **Promoted in revision 2** — see §0.4-R4: Nautilus has no naked-short denial, so Breezy's guard is *the* control, and it is defective | P5, now on the critical path |
| **F** — limits incoherent | CONFIRMED: `risk.py:48-51` absolute; only `:52` scales; no total cap; no time dimension | P4 |
| **G** — preliminary-settlement hazard | CONFIRMED. `GUARD_BANDS` (`settlement_bucket_guard_band.py:63`) measures **METAR-vs-CLI** (`:70-78`), a different comparison from prelim-vs-final CLI revision. Mechanism transfers; the calibrated band does not | P6 |
| **H** — archive single unbacked copy | CONFIRMED as to risk (`ARCHIVE_RELOCATION_2026-08-27.md:13-15`, `:18-20`, `:10-11`). One sub-claim stale: all four scripts now default via `settlement_alignment_cache.py:8-10` and fail closed at `:24-31` | P0 shrinks |

### 0.3 Null-hypothesis audit — what is native, verified twice

Two audits against `.venv/lib/python3.13/site-packages/nautilus_trader/`, then an independent citation audit of both. **Line numbers below are the corrected ones.**

| Capability | Verdict | Anchor |
|---|---|---|
| Connection-status tracking | **NATIVE** | `DataClient.is_connected` (`data/client.pyx:124-134`); `DataEngine.check_connected()` (`data/engine.pyx:324-339`). Breezy already emits it: `data.py:1316` calls `_set_connected(False)` |
| Shutdown request | **NATIVE** | `Component.shutdown_system(reason)` (`common/component.pyx:2163`, publish at `:2183`); kernel subscribes `system/kernel.py:585`, handles `:613-639`. `DataClient` is a `Component` (`data/client.pyx:73`) |
| **Periodic** health evaluation after startup | **ABSENT** | `check_connected()` reached only via `_await_engines_connected` (`kernel.py:1301`) ← `start_async:1024`, which plain-`return`s on failure after `_is_running = True` (`:1018`). `node.py:338-379` awaits only the 8 queue tasks |
| Process exit code on degradation | **ABSENT** | `node.py:283-303` `run(raise_exception=False)`; `:475-481` logs and swallows |
| Conversion integrity check | **ABSENT** | `parquet.py:2788-2800` → `None`; `:2644-2646` `continue`s. **`raise_on_failed_deserialize` does NOT help**: the skip at `:2579-2580` precedes the guarded block at `:2586-2595`. No logger in the class — 8 bare `print()` calls |
| Batch-level salvage | **ABSENT** | `read_all()` (`:2798`) is all-or-nothing |
| Parquet compaction / range deletion | **NATIVE — but ungated**, see §0.4-R5 | `consolidate_data` (`:656`), `_by_period` (`:891`), `delete_data_range` (`:1383`) |
| Feather deletion after conversion | **ABSENT** | `convert_stream_to_data` (`:2604-2654`) never removes its source |
| Per-**order** notional cap | **NATIVE — CONFIGURE** | `risk/config.py:33-35, 44`; `engine.pyx:192-196`; enforced `:912-917`, `NOTIONAL_EXCEEDS_MAX_PER_ORDER` |
| Account-wide exposure **view** | **NATIVE** | `PortfolioFacade.net_exposures` (`portfolio/base.pyx:59`), `equity` (`:67`), `net_exposure` (`:87`), `net_position` (`:91`). Account scope confirmed: `portfolio.pyx:1047-1053`, `:1428-1433` pass `strategy_id=None`; `cache.pyx:4220-4245` intersects only on non-`None` |
| Pending-order exposure | **NATIVE, separate call** | `net_exposure` counts **positions only**. Complement: `Cache.orders_open(..., strategy_id=None)` (`cache.pyx:4710-4717`), as the engine itself does (`engine.pyx:717-724`) |
| Aggregate exposure **ceiling** | **ABSENT** (data native, policy absent) | Nothing compares `net_exposures()` to a limit |
| Any **time-windowed** notional limit | **ABSENT** — credible negative, tested hard | `RiskEngineConfig` has exactly five fields (`risk/config.py:41-45`). `max_order_submit_rate` probed live returns `RateLimit { limit: 100, interval_ns: 1e9 }` — a **count**, not a value. Package-wide sweep hits only `analysis/` metrics and `pyo3.pyi:10763 MaxDrawdown`, a statistic |
| Kill-switch | **NATIVE — with a sharp limit**, see §0.4-R1 | `set_trading_state` (`engine.pyx:228`), `TradingStateChanged` → `events.risk` (`:248-258`), enforced `_execution_gateway:1133` |
| Naked-short denial | **ABSENT** — see §0.4-R4 | `engine.pyx:974-985`: `is_position_reducing_sell` merely `continue`s. A position-*opening* sell is denied only by `CUM_NOTIONAL_EXCEEDS_FREE_BALANCE` |
| Free-balance guard | **NATIVE, conditionally** | `NOTIONAL_EXCEEDS_FREE_BALANCE` (`:948-954`), `CUM_...` (`:968-973`, `:998-1005`, `:1023-1030`). **All gated by `not allow_borrowing`** (`:694, 949, 968`); margin accounts skipped (`:691-692`) |
| Forecast actor timer/stagger | **NATIVE — already reused** | `FORECAST_INGESTION_PLAN.md:155-157`; `ingest/nws_actor.py:594-756` |
| Hardened HTTP for probes | **NATIVE-INSUFFICIENT** | `nautilus_pyo3.HttpClient` has no redirect control, no body cap, no TLS pinning, hides response headers. This is why `ingest/http.py` exists |
| Archive backup; guard band | **ABSENT** | No backup facility; nothing models NWS bucket-boundary revision |

### 0.4 Adversarial review — blocking findings and their disposition

Four reviewers, running blind. **Revision 1 was blocked.** Every finding below is either fixed in this revision or rejected with a reason. Findings marked **[verified by me]** were checked against source directly rather than accepted.

#### R1 — The exposure UNIT collision. CRITICAL. Found independently by two reviewers. **[verified by me]**

Revision 1 §4.P4.2 said: *"read position exposure from `self.portfolio.net_exposure(...)` rather than summing `qty × contract_size`."* That is a **unit change disguised as a simplification**.

`MispricingContract.contract_size` is documented *"Payout dollars per contract at YES. Binary options here always pay 1.0."* (`bucket_contract.py:47-48`), and `event_notional`/`location_notional` sum `qty × contract_size` (`risk.py:116-131`). **Today's caps are in max-payout units.** `PortfolioFacade.net_exposure` is mark-to-market. At a 0.05 bucket price the substitution is a **20× loosening** of every cap. Revision 1's own characterisation test ("every decision unchanged at equity 10,000") could not have passed. The daily budget introduced a third unit (premium paid).

**Disposition: FIXED, and elevated to its own section.** See **§2.3 — the exposure unit**, which now precedes every cap design. One unit is declared for the whole system: **premium at risk**. Rationale in §2.3; it is additive, it equals worst-case loss for a long-only binary book, and it makes the operator's control mean what the operator thinks it means.

#### R2 — `TradingState.REDUCING` does not do what revision 1 claimed. CRITICAL. Found by three reviewers independently.

Revision 1 §0.4 called REDUCING *"precisely the semantics a budget breach wants."* Source: `_execution_gateway` denies a BUY only `if order.is_buy_c() and self._portfolio.is_net_long(instrument.id)`. **On an instrument the node is flat in, a BUY passes.** A long-only bot spread across bucket instruments keeps opening brand-new positions straight through a breach. (Modify gating is also not "identical": REDUCING rejects only a quantity *increase*.)

Independently: with measured top-of-book bid depth ~0.3 contracts against ask 46–171, there is nothing to reduce into — REDUCING would make crossing a near-empty bid the only permitted action.

**Disposition: FIXED. OQ-8 closes as `HALTED`.** Stated plainly in §4.P4.5: on this venue a budget breach is a **stop-opening control with no unwind**. The revision-1 test row ("REDUCING permits a reducing order and denies an opening one") is deleted — it passes only on an already-long instrument and gives exactly the false assurance.

#### R3 — I mis-diagnosed the auth smoke. HIGH. **[verified by me]**

Revision 1 §4.P1.2 claimed the smoke is *"structurally incapable of proving what P1.3 needs proved"* and budgeted a rewrite. False. `scripts/venue/polymarket_us_auth_smoke.py:1588-1637` already builds a real `TradingNode`, registers `PolymarketUSLiveDataClientFactory`, adds a `QuoteWitness(Actor)` counting `on_quote_tick` **per slug** downstream of the DataEngine and MessageBus, and reads `client.frame_diagnostics`. The reported zeros trace to one step failing authentication (finding E1), not to the harness.

**Disposition: FIXED.** P1.3 shrinks from a rewrite to **the auth path plus the teardown**. R-1's severity is unchanged (the evidence gap is real) but its *cause* is correctly stated.

#### R4 — Nautilus has NO naked-short denial, so Breezy's guard is the control — and it is defective. CRITICAL. Two reviewers, converging from opposite directions.

Citation audit: `engine.pyx:974-985` — `is_position_reducing_sell` merely `continue`s past the balance check; a position-*opening* sell falls through and is denied only by `CUM_NOTIONAL_EXCEEDS_FREE_BALANCE` (itself conditional on `not allow_borrowing`). **There is no naked-short-specific denial.**

Domain review: Breezy's guard tests `portfolio.net_qty(...) + delta < 0` (`risk.py:176-181`), and `net_qty = position_qty + pending_qty` (`:80-81`) where `pending_qty` is signed and **includes pending buys**. Close-only must be tested against **settled position only**. Today the hole is masked by a `cache.orders_open` skip in `_maybe_submit`; **revision 1's §4.P4.2 widening would have removed the mask.**

**Disposition: FIXED and PROMOTED.** P5 moves onto the critical path (§3, §5). The guard is corrected to test settled position, and P5's success criterion — *"no naked short constructible from any default configuration"* — is now provable rather than asserted.

#### R5 — The kill-switch fails OPEN three ways; and `bypass` defeats the whole layer. CRITICAL.

1. `RiskEngine.__init__` sets `trading_state = ACTIVE` (`engine.pyx:132`) and `RiskEngineConfig` has no initial-state field. Between node start and the guard's first evaluation — and forever if it never evaluates — trading is unbounded.
2. `Actor.handle_event` catches every exception from `on_event` and **does not re-raise** (`common/actor.pyx:4789-4793`). A `BudgetGuard` that throws is silently dead; one log line is the whole trace.
3. `handle_event` dispatches only at `ComponentState.RUNNING`. A guard added but not started, or a composition path skipping `Trader.add_actor`, is silently absent.
4. Separately: `RiskEngineConfig.bypass=True` returns via `_send_to_execution` **before** `_execution_gateway` (`engine.pyx:414-418, 455-459, 494-498`), defeating HALTED, `max_notional_per_order` and both free-balance guards with one boolean.

**Disposition: FIXED by inverting the polarity.** §4.P4.5: HALT at composition immediately after `build()`; the guard **promotes** to ACTIVE only after it reads a configured budget and completes one clean evaluation, and re-HALTs on staleness. Plus a config test asserting `bypass is False` on every shipped node config. A control that must run to be safe is not a control.

#### R6 — P4.2's enumeration cannot be written as specified. HIGH. **[verified by me]**

`is_weather_market` **raises** `WeatherFactsUnavailableError` on missing or malformed status (`weather_bucket_facts.py:128-141`, `_require_present:153-159`) — deliberately, *"so older instruments cannot silently disappear from a strategy pre-filter."* So `cache.instruments(venue)` filtered by it raises on the first non-weather instrument. The only way to make it not raise is a `try/except` treating the raise as "not weather", which **silently drops instruments from exposure aggregation and reopens Finding D through a different door** — invisible to the flagship test.

**Disposition: FIXED.** §4.P4.2 partitions into KNOWN / UNKNOWN / UNDECIDABLE, counts UNDECIDABLE as **in scope** (fail closed), and alerts. Tested with an instrument whose `info` lacks the key.

#### R7 — Reserve/reconcile is inoperative for the order type actually used. CRITICAL.

All three strategies send IOC (`forecast_revision/strategy.py:354`), and an IOC order is **never in `orders_open`**. So revision 1's stated mitigation — *"reconcile from `cache.orders_open` every evaluation"* — cannot distinguish cancelled-unfilled from filled. On a **partial** fill (`PartiallyFilled` → `Canceled`, the normal IOC outcome in a thin book) a release-on-cancel rule releases a reservation that was really spent. The `use_limit_orders=False` MARKET path has no bounded price, so any reservation at the last quote under-reserves by the full slippage.

**Disposition: FIXED.** §4.P4.5 reserves keyed on `client_order_id` at the **limit price** (or $1.00/contract for market orders) and reconciles from terminal `OrderFilled`/`OrderCanceled`/`OrderExpired` events, idempotently. One ledger, not two.

#### R8 — §2.2's central claim is false. CRITICAL.

*"Premium paid is worst-case loss, so a daily spend cap is exactly a daily loss cap, with no modelling."* Three counterexamples:
- **Fees sit outside premium, on both legs.** `fees.py:186` charges `θ·C·p(1−p)` on every fill and again on the closing fill. At θ=0.06, $1,000 premium at p≈0.5 is ~$30 entry + $60 round-trip. The fee model's own docstring (`fees.py:126-133`) states it computes `sum(bankers(per_fill))` where the venue computes `bankers(sum(exact))`, and that **no blanket never-understates claim holds.**
- **The counter charges turnover, not risk.** Buy → flatten → re-enter spends 2× budget for 1× exposure. All three strategies flatten on `observation_received`, `settlement_halt` and z-exit.
- **"No naked short exists" was not guaranteed** — R4.

**Disposition: FIXED.** §2.3 replaces the identity. The operator's loss control maps to **peak open premium at risk**, not cumulative spend; fees are reserved explicitly; turnover is tracked separately or not at all.

#### R9 — `max_event_notional` is structurally dominated and can never fire. HIGH.

`exclusive_conflict` permits at most **one** long-YES per `event_key` (`risk.py:141-154`). With `max_position_contracts=250` and `contract_size=1.0`, event notional caps at 250 against a 1,000 ceiling. Revision 1 wrote a mutation test for a dominated `max_total_notional` but never applied it to the cap the operator was told is theirs-not-ours. Further: for mutually exclusive buckets, **summing payout notional is the wrong aggregation** — at most one bucket can pay, so max payout is `max(payouts)`; only **premium** is genuinely additive.

**Disposition: FIXED.** Reinforces §2.3's unit choice. `describe_binding_order` runs against the **actual** defaults, and any cap it shows unreachable is deleted or re-scaled rather than shipped.

#### R10 — `RestartPreventExitStatus=2` converts a transient IO error into permanent data loss. CRITICAL. **[verified by me]**

`quote_tape_cli.py:111-116` puts **`OSError` in `_CONFIG_ERRORS`** — commented as being for the credential key file, but `prepare_quote_tape_root` raises it too, so a full disk, an NFS blip or a transiently unmounted catalog root returns exit 2. Revision 1 asserted *"exit 2 never fixes itself by restarting"* and set `RestartPreventExitStatus=2`, which would latch the recorder off at 3 a.m. for exactly the fault class §4.P1.6 argues must never latch.

**Disposition: FIXED.** Exit 2 splits: **2 = validation/settings**, **4 = IO/environment**. `RestartPreventExitStatus=2` only.

#### R11 — A signed recorder can log at DEBUG. HIGH. **[verified by me]**

The smoke refuses under `BREEZY_LOG_LEVEL=DEBUG`/`TRACE` (`auth_smoke.py:36-38, 152`) and hardcodes `LoggingConfig(log_level="INFO")` (`:1620`). The recorder does not: `_parse_log_level` (`settings.py:237-245`) accepts DEBUG/TRACE and it flows to `LoggingConfig(log_level=settings.log_level)` (`node_config.py:198, 454`). Finding E1 makes the markets WS **authenticated**, so the recorder now signs — unattended, under systemd, logging to journald. Aggravating: committed evidence records a −120 s stale timestamp **ACCEPTED — "window not enforced"** (`READONLY_AUTH_SMOKE_...155317:38`), so a leaked signature is long-lived.

**Disposition: FIXED.** §4.P1.6: refuse DEBUG/TRACE whenever a signer is present, asserted in the unit-file test.

#### R12 — `instrument_id` on `WeatherForecastDay`: REJECTED. **[verified by me]** — resolving a direct contradiction between two of my own agents.

The Nautilus audit found that `delete_data_range(identifier=None)` no-ops for identifier-less custom data (`parquet.py:1421-1442`) and recommended adding `instrument_id` to the forecast record so native pruning works. The architecture review called it a category error. **I checked, and struck it:**
- A forecast row is keyed `(station, target_day, source)`; weather markets are one `BinaryOption` per bucket, so one station-day maps to **N** instruments. The field forces duplicate rows or a synthetic id.
- **`NwsClimateDay` and `NwsRawProduct` both ship today with no `instrument_id`** and are already written to the live catalog. "Can never be pruned natively" is therefore **already true of two production records and tolerated** — a condition, not a justification for an irreversible schema field.
- Forecast volume is a handful of rows per city per day.

The audit's *fact* is correct; its *recommendation* is not. **R-14 is struck from the schema freeze.** Forecast pruning uses whatever answer already serves the two settlement records (`delete_catalog_range`, or direct file removal under a disjoint base).

#### R13 — The P2 gate is anchored one step too early. HIGH.

Revision 1: *"P2 must complete before I-1 merges."* But `FORECAST_INGESTION_PLAN.md:374-375` says the field set is irreversible *"the moment I-4 writes its first row."* The door closes at first **write**, not at merge. I-1/I-2/I-3 can merge, be tested and be reviewed while P2 runs.

**Disposition: FIXED.** The gate moves to **I-4's deploy**. The self-declared "single hardest ordering constraint" was partly self-imposed. (The reviewer's further suggestion of a raw-payload capture as P3a-0 is **accepted as OQ-9**, not adopted — it is a real idea that belongs to the forecast plan, not this one.)

#### R14 — Native destructive paths inherit none of this plan's gates. HIGH.

`consolidate_catalog(start=None, end=None)` walks **every** leaf directory and removes originals (`parquet.py:601-654`) with no dry-run, no post-hoc row-count verification, and no lock against a running recorder or converter. `ensure_contiguous_files=True` checks overlapping timestamps, not merged-output correctness. Revision 1's §1.2 said "configure, don't author" and thereby exempted the most destructive operation in the plan from every safety gate it applied to its own.

**Disposition: FIXED.** §4.P1.4: **never call `consolidate_catalog`.** Use `consolidate_data` narrowed to one data class and a closed range strictly older than the open `instance_id`, wrapped in census → consolidate → re-count, keeping originals on shortfall, with the same open-instance exclusion the Breezy prune uses.

#### R15 — The probes sit outside the existing read-only guard. HIGH.

`tests/unit/test_polymarket_us_readonly_guard.py` classifies venue-touching code by adapter package, `scripts/venue/` path, host literal, or adapter/SDK import. A probe under `scripts/probes/` taking its base URL from `config_from_env` and importing only `breezy.ingest.http` matches **none**, so the write-verb and `/v\d+/orders` assertions never apply. "Cannot place an order" would be convention, not enforcement. Relatedly, revision 1 mandated a request counter but never named `breezy.ingest.http.HttpClient` — the only thing supplying host allowlisting (`http.py:622`), `follow_redirects=False` (`:630`), 3xx-as-alarm (`:857`) and a body cap (`:930`). A counter bolted onto raw `httpx` reproduces the exact defect class that caused the 2026-08-29 over-spend.

**Disposition: FIXED.** All probes live under `scripts/venue/` so the path classifier binds; `scripts/probes/` is added to the classifier regardless; both probes bind to `ingest/http.py` with per-probe `allowed_hosts` and per-instance `max_body_bytes`, AST-asserted.

#### R16 — Accepted, smaller

- **Leftovers from revision 1's in-place edit** (deleted `feed_health.py` still in a file list, tests for a deleted callback, "Layer A" referenced after Layer A was removed, `Node` Protocol gaining `stop` for a deleted design, two incompatible P1 numbering schemes, a self-contradicting §1.3 count). **Fixed by rewriting rather than patching a third time.**
- **"~15 lines" for the exit-3 mapping was wrong**: `_run_node` receives a `Node` Protocol exposing only `add_data_client_factory/build/run/dispose` (`quote_tape_cli.py:119-128`); observing a `ShutdownSystem` needs `node.kernel.msgbus`, on neither. Estimate corrected in §4.P1.5.
- **P0 backs up the wrong half.** The irreplaceability argument applies verbatim to `<catalog_root>/live/`, which §4.P1.4's prune *deletes*. **Fixed:** §4.P0 covers the tape too.
- **§5's mergeability claim was false** — P4, P5f and P6b all edit `risk.py` and the same three `config.py`. **Fixed** in §5.
- **No observability increment**: exit 3, `TradingStateChanged`, denials and budget refusals reached no sink. **Fixed:** §4.P7, new.
- **No rollback, and no pre-capital validation.** §2 establishes a working 36-run backtest harness that no increment re-runs after P4/P5/P6 change the risk surface. **Fixed:** §4.P7 and §6 item 5.
- **`min_liquidity_contracts=25` vs the bid side -- RESTATED 2026-08-31, the earlier framing overstated it.** `quote_tradable` (`risk.py:177`) uses `min(bid_size, ask_size)`, so it gates on depth a long-only entry will never consume — and only `forecast_mispricing` calls it. **Tuning caps above a gate that rejects the book is measuring the wrong thing.** Depth belongs on the **executable** side for the intended direction. Recorded as **OQ-10**, and §4.P4 must measure it before tuning anything.

  **PROVISIONAL measurement (2026-08-31), against the 675-quote tape --
  NOT yet reproduced by a committed script, so it does not close OQ-10.**
  `min(bid,ask) >= 25` passes 20.7% of quotes (9.6% with the spread gate);
  `ask_size >= 25` alone passes 77.3% (66.2% with spread). Switching the entry
  test to the executable side widens the tradable universe ~6.9x. The bid is
  bimodal, not uniformly thin: `miahigh-gte89lt90f` has bid median 143 and
  `nychigh-gte84lt85f` 1431, while three instruments sit at exactly 0.30 -- the
  "median 0.3" figure was an artifact of averaging two populations, and this
  plan repeated it. Ask-size percentiles: p10 6.3, p25 25.0, p50 43.1, p75
  155.7 contracts.

  **The `min(both)` test is wrong for entry but is accidentally doing a second
  job: proxying EXIT liquidity.** Among entry-feasible quotes the bid supports
  >=25 contracts only 26.8% of the time, median exit depth 0.30, median spread
  16% of ask. So `min(...)` -> `ask_size` is correct ONLY if hold-to-settlement
  is simultaneously declared the exit. Binary options settle at 0 or 1, so
  settlement IS the exit -- we always get out, we just cannot stop out.
  Loosening the gate without the budget guard in place converts an accidental
  brake into unmanaged inventory. **P4 must land the guard first, then the gate,
  and must re-derive these numbers from a committed script rather than citing
  this paragraph.**

  **SELECTION BIAS -- ADDED 2026-08-31. Every percentage above is computed on a
  sample that structurally excludes the cases it is trying to measure.**
  `parse_book_top` (`parsing.py:582`) calls `_best_level` on BOTH sides
  unconditionally, and the depth path indexes `bids[0][0]` (`:574`), so a frame
  whose `bids` array is empty raises `VenuePayloadError` and yields **no
  `quote_tick` and no `order_book_depths` row at all** -- not a row with a zero
  bid. Live confirmation, one recorder session: the 5 slugs whose
  `bestBidQuote` was `None` at discovery produced **247 parse errors and zero
  rows**, while 5 two-sided slugs produced 675 of each. The 675-quote tape is
  therefore CONDITIONED ON A TWO-SIDED BOOK, and half the sampled ladder never
  entered it.

  Three consequences, in increasing order of severity:

  1. `min(bid,ask) >= 25` passing 20.7% is an **overestimate** of bid-side
     availability across the real ladder: every excluded slug would have failed
     it. The true figure is lower by an unmeasured amount.
  2. `ask_size >= 25` passing 77.3% is biased in an **unknown direction**. The
     excluded slugs' ask sizes were never recorded, and a market nobody bids
     may be either thinly offered or heavily offered. The ~6.9x widening claim
     is not safe to rely on until re-measured on an unconditioned sample.
  3. **The severe one, which is not a statistics problem at all: the bot is
     BLIND to those markets.** Zero quotes means no signal, no valuation, no
     entry -- on precisely the cheap deep-out-of-the-money strikes a weather
     model with a confident tail forecast would most want to buy. A gate we
     chose is not rejecting them; the parser is dropping them before any gate
     runs. That is silent universe truncation, and nothing in either plan
     currently detects it.

  **This does not close OQ-10 and it does not reopen the direction of the fix**
  (`min(both)` -> executable side is still right). It adds a prerequisite: the
  committed script that re-derives these numbers must first be able to SEE
  one-sided books, so a one-sided frame must yield a row carrying an explicit
  empty/zero bid rather than raising. Recorded as **OQ-13**; it blocks P4's
  measurement, and P4 must not tune against the conditioned tape.
- **`transaction_cost_prob = 0.015`** is a flat probability-unit stand-in for a fee that is genuinely `θ·p(1−p)`: correct at p=0.5, ~3× over-charged at p=0.9 — biasing against exactly the confident-tail trades the model is best at. Folded into §4.P6, which already edits that comparison.
- **L: `websocket.py:991-1001`** interpolates full `{error}` text on the shard-close path, violating the module's own type-name-only rule honoured at `:499` and `:626`. One-line fix, folded into P1.

#### R17 — Rejected, with reasons

- **"Fail-closed budget blocks the backtest harness."** Real hazard, wrong fix. Rejecting the reviewer's proposal to scope fail-closed to the live gate *only*: that makes the safe default depend on a second flag. **Instead**: the budget is unset-and-refusing **only when a signer is present** (the same predicate as R11), so backtest and paper runs are unaffected while any node that can reach the venue fails closed. One predicate, two uses.
- **"Long-only mean reversion via a sibling-bucket basket"** (§4.P5, H4). Genuinely interesting: buckets tile closed-closed, so `P(¬A) = Σ P(B)` over siblings, purchasable on the **deep** ask side, and fees favour the basket. But `exclusive_conflict` currently forbids more than one long YES per `event_key`, so it needs a guard change the plan has no evidence to justify. **Recorded as OQ-11 and explicitly out of scope**; P5.3's flag flip is correct under both answers.

---

## 1. Null hypothesis

### 1.1 REUSED AS-IS

Streaming capture (`node_config.py:465-473`); feather→parquet conversion; native signal handling (`quote_tape_cli.py:24-26`); systemd supervision (the sibling `breezy-nws-ingest.service`); the periodic-monitor shape (`quote_tape_disk_monitor.py:51-106`, transition-dedupe `:187-201`); node-wide position truth derived fresh per decision (`risk.py:67-74` — *"can never drift"*); the mutually-exclusive bucket guard (`risk.py:141-154`); closed-closed tiling and `distance_f` (`weather_bucket_facts.py:64-84`); the namespaced single-writer state store; read-only probe discipline; the `live`/`venue_live`/`real_money` markers (`pyproject.toml:43-49`); fail-closed tape-root preparation (`node_config.py:325-378`); **and the existing auth smoke's `TradingNode` + `QuoteWitness` harness (`auth_smoke.py:1588-1637`) — see R3**.

### 1.2 DO NOT BUILD

1. A price-history backfill from any vendor. Finding A is settled.
2. A second exposure ledger — bus broadcast, shared mutable dict, or a risk "service". `risk.py:67-74` says why: a derived-fresh snapshot cannot drift; a ledger can.
3. A patch, fork or vendored copy of any Nautilus code.
4. A supervisor process, watchdog daemon, or exit shim — `shutdown_system()` is inherited.
5. A cross-strategy exposure aggregator that tracks its own fills, positions or PnL — read `PortfolioFacade`.
6. A per-order notional cap — `max_notional_per_order` is native and enforced.
7. A Breezy kill-switch or order-blocking layer — `set_trading_state` exists. (But see R5: it must be *inverted*, not merely called.)
8. Free-balance overdraw protection — native for CASH accounts without `allow_borrowing`.
9. Automatic pruning wired into `QuoteTapeDiskMonitor`. Alert-only by design (`:86-102`), and that design is correct.
10. Any `max_body_bytes` global lever, or any widening of `DEFAULT_ALLOWED_HOSTS`.
11. A rewrite of `exclusive_conflict`, `WeatherBucketFacts.contains`, or `PortfolioSnapshot`.
12. A second `register_arrow`, or any post-deployment forecast field addition.
13. Anything that re-fetches the settlement-alignment archive — a re-fetch returns a later IEM revision and silently breaks three published documents.
14. **`consolidate_catalog`** — native, and ungated. See R14.
15. **`instrument_id` on `WeatherForecastDay`** — see R12.

### 1.3 GENUINELY ABSENT — author these, and only these

1. An off-host copy of the settlement-alignment archive **and of the quote tape**.
2. A liveness oracle that makes the recorder **exit non-zero**, and the exit-code mapping.
3. A systemd unit for `breezy-quote-tape`.
4. Integrity verification between a written feather run and its converted parquet, plus batch-level salvage.
5. Convert-then-prune of `<catalog_root>/live/`, and a gated wrapper around native `consolidate_data`.
6. Authenticated end-to-end evidence through the real pool (the *harness* exists; the *evidence* does not).
7. Evidence on Open-Meteo `/v1/previous-runs` and IEM AFOS forecast PILs.
8. A weather-instrument enumeration that fails closed on undecidable instruments.
9. An aggregate exposure ceiling, and **any time dimension at all**.
10. Premium-at-risk accounting with a correct IOC reserve/reconcile.
11. An inverted-polarity budget guard that must prove itself before trading is enabled.
12. A corrected close-only guard tested against settled position.
13. A boundary-distance term in the edge/sizing path.
14. Observability for every one of the above.

---

## 2. Problem statement

Three weather strategies ran through the real `run_backtest` harness: 36 runs against the only real tape that exists (6 minutes, 2026-08-30, 5 instruments, settled on real preliminary NWS observations). One traded; 4 fills; −$5.41. That is not a strategy finding — it is a measurement of the input.

The binding constraints, in order:

1. **Data that cannot be recovered is not being reliably captured**, and one 299 MB irreplaceable archive has no second copy.
2. **The capture process cannot fail loudly.** It can lose the feed and keep running; it can lose 24 h of one instrument to a silent conversion failure.
3. **Risk is accounted per strategy, in the wrong unit, with no time dimension** — so the operator's two reserved controls have nowhere to live, and running three strategies together triples the intended per-event cap invisibly.

### 2.1 The operator control contract (binding)

| Control | Status | Where it lives today |
|---|---|---|
| Maximum **daily** budget | Value not supplied | **Nowhere.** No time dimension exists in `RiskLimits` or in Nautilus |
| Maximum per **position** (explicitly *not* per weather market) | Value not supplied | Partially: `max_position_contracts` (`risk.py:48`) is a contract **count**, not a dollar ceiling |

Everything else is ours. This plan designs the mechanism for both and refuses to invent the values. §4.P4.5 states how a missing value behaves.

### 2.2 What the daily budget actually bounds — corrected

Revision 1 claimed premium paid is worst-case loss, so a spend cap is a loss cap "with no modelling". **That is false** (R8): fees sit outside premium on both legs and the fee model can understate; and a spend counter charges turnover, not risk — a buy → flatten → re-enter cycle spends 2× budget for 1× exposure.

**The corrected statement.** The operator's loss ceiling maps to **peak open premium at risk**, plus a modelled fee reserve:

> `at_risk = Σ_open (qty × entry_price) + entry_fee_reserve + exit_fee_reserve`

Worst-case loss for a long-only binary book is exactly this: every open contract can settle at 0, and both fee legs are charged regardless. Turnover is *not* charged against the ceiling. If turnover itself needs bounding, that is a separate control with a separate number — not this one wearing a disguise.

This holds only while no naked short exists, which §4.P5 is what makes true. A test pins the equality and **fails if `allow_short` is ever defaulted back to `True`**, so the premise cannot silently become false.

### 2.3 THE EXPOSURE UNIT — declared once, for the whole system

R1 and R9. Revision 1 mixed four units in one hierarchy: max payout (`qty × contract_size`), mark-to-market (`net_exposures()`), premium paid (the budget), and a contract count (`max_position_contracts`).

> **Every ceiling in this system is expressed in PREMIUM AT RISK, in USD.**

Why this unit and not the others:

- **It is additive.** For mutually exclusive buckets, summing *payout* is wrong — at most one bucket can pay, so max payout is `max(payouts)`, not the sum. Premium is genuinely additive across any set of positions.
- **It equals worst-case loss** for a long-only binary book (§2.2), so the operator's control means what the operator thinks it means.
- **It does not distort by price.** Payout units make 1,000 contracts at p=0.05 consume the same ceiling as 1,000 at p=0.95, though one risks $50 and the other $950 — systematically starving the cheap-tail buckets a weather model is best at (R9).
- **Mark-to-market is wrong for a ceiling** because it moves with the market: a position that doubles in value would consume more ceiling while its *risk* fell.

**Consequences, all mandatory:**
- `event_notional` / `location_notional` change from `qty × contract_size` to `qty × entry_price`. This is a **behaviour change**, so the characterisation test is written against the *new* intended semantics, not against today's numbers, and the change is called out as such rather than smuggled in as a refactor.
- `net_exposures()` is used **only** where a mark-to-market number is genuinely wanted — currently nowhere in the ceiling path. It remains the right read for reporting.
- `max_position_contracts` stays as a **venue/liquidity** bound, explicitly not a risk ceiling.
- Native `max_notional_per_order` is configured in the venue's own notional terms and treated as a **third-party backstop**, not part of the hierarchy.
- `describe_binding_order(equity)` is logged at `on_start` and run against the **actual** defaults; any cap shown unreachable is deleted or re-scaled before shipping (R9).

---

## 3. Ordering

Ordered by **reversibility and cost-of-being-wrong**, not by value or size.

| Tier | Rule | Items |
|---|---|---|
| **T0** | Loss unrecoverable, fix costs minutes | P0 |
| **T1** | Loss unrecoverable and accruing per hour; the process can lose data while looking healthy | P1, P3a |
| **T2** | Cheap, read-only, can invalidate an irreversible decision downstream | P2, P5-probe |
| **T3** | Correctness blockers — reversible, but they gate concurrency and capital | **P5-fix**, P4 |
| **T4** | Capability build, now constrained by T2's evidence | P3b, P6, P7 |

**Execution order: `P0 → P1 → (P2 ∥ P5-probe) → P5-fix → P4 → P3a → P3b → P6 → P7`.**

Two changes from revision 1:

- **P5-fix moves ahead of P4** (R4). The close-only guard is the *only* naked-short control, it is defective, and P4's enumeration widening degrades it further. Fixing P4 first would ship the degradation.
- **P3a moves after P4** (R13). The schema door closes at I-4's first **write**, not at I-1's merge, so P3a's early increments proceed in parallel and only its deploy waits on P2. P3a is no longer competing with the risk work for the critical path.

**Critical path: `P2 → P3a-deploy`**, for the Arrow schema freeze — now with one field fewer (R12) and one gate later (R13).

---

## 4. Design, per increment

### P0 — Off-host backup of both irreplaceable datasets · T0

**Goal.** One verified copy, on a device that is not the primary's, of (a) `~/.local/share/breezy/archive/settlement-alignment-cache` and (b) `<catalog_root>/live/` — verified against digests, with a proven restore.

**Why (b) was added (R16).** P0's whole argument — cannot be honestly re-fetched, one copy on one device — applies verbatim to the quote tape, which §4.P1.4's prune *deletes*. Revision 1 rated that HIGH and mitigated it with a retention record and no second copy.

**Why now.** The only T0 item, and already on a clock: `ARCHIVE_RELOCATION_2026-08-27.md:10-11` puts the `/tmp` sweep around **2026-09-04**, and that `/tmp` copy was believed to be the only redundancy. **Corrected 2026-08-31:** `/mnt/storage/breezy-backup/` already held an unverified, never-restored rsync copy from 2026-08-30; P0 wrote to a disjoint directory and left it untouched.

**Steps.** (1) Re-measure — file count, `du -sb`, `/tmp` copy presence. (2) **Verify the primary against the git-tracked manifest first** (`:28-31`), so backing up a corrupt primary is impossible. (3) Copy as `.tar.zst` + detached `.sha256` + the unchanged per-file manifest. (4) **Prove the restore**: extract to scratch and verify *that extraction*. (5) Do not delete the `/tmp` copy. (6) Correct the stale "Still open" (`:43-49`) — all four scripts now default via `settlement_alignment_cache.py:8-10`, fail-closed at `:24-31`. (7) **Commit the untracked P6 dependencies** (`scripts/analysis/settlement_truth_dataset.py`, `price_conditional_settlement_analysis.py` and their tests) — an uncommitted dependency of a T0-backed study is the same losable-artifact problem.

**Destination.** A truly off-host target needs a credential the repo does not have, and provisioning costs money — an operator ceiling. This plan does the largest correct thing available: a second **device**, asserted by `st_dev` inequality, plus a tracked follow-up. Success is written against `st_dev`, so "I copied it next to itself" cannot pass. If no second device exists, **P0 cannot complete and that fact is the deliverable** — reported as an unmitigated T0 risk.

**Tests (RED→GREEN).** Wrong digest → raises, writes nothing. Same-`st_dev` destination refused. Restore-verify compares the **extracted** tree. Dry-run unless `--apply`; dry-run writes zero bytes. AST-assert the script imports no HTTP client (no re-fetch path, ever).

---

### P1 — Quote tape: prove, then fail loudly, then supervise · T1

**Goal.** The recorder either records, or **exits non-zero within a bounded time**. Nothing captured is lost to a conversion that returns `None`.

**Internal order is load-bearing:** prove it works attended → make it fail loudly → only then let a supervisor run it unattended.

#### P1.1 — Commit `websocket.py`/`factories.py` first

It is the most losable artifact in the repo, a commit is reversible where data loss is not, and the change set (implementation + its two test files) is a coherent unit. Conditions: full unit suite + `ruff` + `mypy` + `lint-imports` green; the commit message and the class docstring both state that the pool has **never been observed carrying a live QuoteTick**, removable only by P1.2's evidence. Fold in the R16 one-liner: `websocket.py:991-1001` must log `type(error).__name__`, not the full error text, matching `:499` and `:626`.

#### P1.2 — Attended end-to-end evidence (the gate)

**The harness already exists** (R3): `auth_smoke.py:1588-1637` builds a real `TradingNode`, registers the production factory, and counts `on_quote_tick` per slug via a `QuoteWitness` Actor. The work is **the auth path and the teardown**, not a rewrite.

- Fix the WS step to connect **signed** via `config_from_env` — finding E1 (`/v1/ws/markets` requires auth) is why the run reported 0 frames.
- Fix the teardown so a clean stop reports `teardown health: OK`; today `RuntimeError: Event loop stopped before Future completed` fires always, so it cannot distinguish a clean stop from a hung one — the exact signal `TimeoutStopSec` depends on.
- Report `subscription_errors` (`websocket.py:430-440`) and **`silent_subscriptions`** (`:442-453`) positively. `confirmation_window_secs` defaults on (`:288-294`), and the module records that a slug past the per-connection cap draws **no error frame at all** (`:713-724`). "No errors" without "every slug confirmed" reproduces exactly that failure.
- Extend the leak scan (R16): `write_evidence`/`find_secret_leak_offsets` (`:298-330`, `:702-735`) is the load-bearing control and is correctly fail-closed; pass the WS handshake header values and key id into `secrets` too, since P1.2 adds venue-controlled text to a committed document.

**Pass bar, pre-registered:** ≥1 QuoteTick to the `DataEngine` **for every subscribed slug**, zero `subscription_errors`, zero `silent_subscriptions`, `is_degraded` False throughout, teardown OK, and at least one `.feather` read back as `QuoteTick`s with bid/ask intact. Anything less is a FAIL and P1.6 does not proceed.

#### P1.3 — Conversion integrity + salvage

`pa.ipc.open_stream(...).read_all()` is all-or-nothing; `parquet.py:2788-2800` returns `None`; `convert_stream_to_data` `continue`s (`:2644-2646`). `raise_on_failed_deserialize` does **not** help (§0.3). Rotation is daily, so an unclean shutdown can silently zero up to 24 h of one instrument.

Nautilus is immutable, so **wrap**, in `breezy/persistence/quote_tape_convert.py` + a `breezy-tape-convert` console script, running **outside** the recorder process.

1. **`inspect_run`** — per `*.feather`, pull batches incrementally via `read_next_batch()` until `StopIteration`/`ArrowInvalid`; record `complete_batches`, `rows`, truncated-tail flag. *(This is the one remaining `[VERIFY]`: that `RecordBatchStreamReader` yields complete batches before raising on a truncated tail. Proved by the first unit test, against a byte-truncated fixture.)*
2. **`salvage`** — truncated files only; rewrite the complete prefix into a **separate** directory. Never in place. The source is the only copy of those bytes and stays untouched forever.
3. **`convert_and_verify`** — call Nautilus, re-query the catalog, compare row counts to step 1's census per instrument. **Any shortfall raises; the CLI exits non-zero.**

**Retention, in two parts.**
- **Feather prune (ours):** `--apply` required, dry-run default; deletes a run's feather only when it is not the open `instance_id`, `convert_and_verify` returned zero shortfall, a read-back sample matches the census, and a retention record is written **before** the delete. Converted parquet measured ~19× smaller (`[REPORTED]`: 4,925,597 → 178,151 bytes).
- **Parquet compaction (native, gated — R14):** **never `consolidate_catalog`.** Use `consolidate_data` narrowed to one data class and a closed range strictly older than the open `instance_id`, wrapped census → consolidate → re-count, keeping originals on shortfall, with the same open-instance exclusion. Catalog maintenance is **serialized** — no lock exists natively, and the in-source interrupted-consolidation guard (`:990-1008`) shows interruption is a known hazard.

Per §1.2 item 9, prune is **never** triggered by the disk monitor.

#### P1.4 — Feed liveness

**Two of three parts are native** (§0.3). The design is:

1. **One adapter line.** Inside the existing safe-mode branch (`data.py:1312-1324`, after `_set_connected(False)`): `self.shutdown_system(reason="markets feed lost and not recoverable")`. Inherited, no new import, no new `ignore_imports` entry.
2. **The CLI maps cause to exit code.** `_run_node` observes a `ShutdownSystem` not originating from the signal handler and returns **exit 3**. **Estimate corrected (R16):** this is *not* ~15 lines — the `Node` Protocol exposes only `add_data_client_factory/build/run/dispose` (`quote_tape_cli.py:119-128`), and observing the message needs `node.kernel.msgbus`, which is on neither. The Protocol gains a `kernel` accessor; budget accordingly.
3. **Artifact-liveness watchdog — OPTIONAL, and I am cutting it.** Revision 1 invited reviewers to cut it; the architecture review took the invitation, correctly. Its only unique catch is "socket connected but writer stalled", it ships alert-only until a threshold is measured that does not exist yet, and it was the sole justification for the "tape stalled" half of the exit-3 contract. **Deferred to P7**, where it can be built against measured overnight gaps and an actual alert sink. Exit 3 now has exactly one cause: feed degraded.
4. **`graceful_shutdown_on_exception=True`** on the recorder's `LiveDataEngineConfig`. Its default `False` branch is `os._exit(1)` (`live/data_engine.py:366`) — an immediate crash that skips the writer's flush. For a process holding the only copy of unflushed quotes that default is wrong. One field, with the reason in a comment and a config test.

#### P1.5 — `breezy-quote-tape.service`

**It must not copy the NWS unit.** NWS data is re-fetchable, so latching into `failed` costs attention. Tape data is not: a unit latching after three restarts in five minutes converts a 30-second venue blip into indefinite total data loss, silently, at 3 a.m.

| Directive | Value | Why |
|---|---|---|
| `Restart` | `always` | — |
| `RestartSec` | `10` | Longer than NWS's 5 s: the pool has its own 2 s→30 s backoff (`websocket.py:337-340`); a fast systemd loop would race it against a rate-limited venue |
| `StartLimitIntervalSec`/`Burst` | `600`/`30` | **Not 300/3.** Generous enough that no realistic blip latches; bounded enough that a genuine crash loop stops within ten minutes |
| `RestartPreventExitStatus` | `2` | **Only after the R10 split**: exit **2 = validation/settings**, exit **4 = IO/environment**. `OSError` is currently in `_CONFIG_ERRORS` (`quote_tape_cli.py:111-116`) and `prepare_quote_tape_root` raises it, so without the split this directive latches the recorder off on a full disk. Exit 3 deliberately **does** restart |
| `TimeoutStopSec` | `120` | Direct mitigation for a SIGKILL mid-flush truncating a feather. P1.2 measures the real graceful-stop time; a slower stop means a **longer** timeout, never a kill |
| `UMask` | `0077` | Matches NWS and `QUOTE_TAPE_ROOT_MODE` (`node_config.py:347`) |
| `Environment` | `BREEZY_LOG_LEVEL=INFO` | **R11.** The recorder now signs, and `settings.py:237-245` accepts DEBUG/TRACE straight into `LoggingConfig` (`node_config.py:198, 454`), unattended, to journald. Committed evidence shows the venue accepted a −120 s stale timestamp (*"window not enforced"*), so a leaked signature is long-lived |

**Additionally (R11): the recorder refuses to start at DEBUG/TRACE whenever a signer is present** — the same predicate the smoke already uses (`auth_smoke.py:152`). The unit-file Environment line is defence in depth, not the control.

**Considered and deferred:** `Type=notify` + `WatchdogSec`. Native and preferable in principle, but it needs an sd_notify dependency, replaces "exit non-zero" with "stop pinging" (harder to test in-process), and still needs our own liveness check to decide whether to ping. Revisit with P7.

**Files.** `scripts/venue/polymarket_us_auth_smoke.py` (auth + teardown + leak-scan); `breezy/adapters/polymarket_us/data.py` (one line) and `websocket.py` (R16 one-liner); `breezy/runtime/quote_tape_cli.py` (exit-code split, exit 3, `kernel` on the Protocol); `breezy/runtime/settings.py` (signer/DEBUG refusal); `breezy/persistence/quote_tape_convert.py` (new); `pyproject.toml` (console script); `deploy/systemd/breezy-quote-tape.service` (new, **in-repo**); `docs/core/RUNBOOK_QUOTE_TAPE.md` (new).

**Tests (RED→GREEN).** Degradation returns exit **3**, not 0/1. An `OSError` from tape-root prep returns **4**, not 2 (kills R10). A settings error still returns 2. A signer present + DEBUG → refuses to start. Truncated feather yields `complete_batches > 0` and an exact row count. Post-conversion shortfall **raises** and exits non-zero. Salvage never writes into the source dir and never modifies a source file (byte-compare). Prune refuses the open `instance_id`, refuses without a verified conversion, refuses without `--apply`, and writes its record **before** the delete. `consolidate_catalog` is never called (AST assertion). Parsed-unit test asserts `RestartPreventExitStatus=2`, `StartLimitBurst != 3`, and `BREEZY_LOG_LEVEL=INFO`, each with a comment naming the data-loss or leak reason.

**Risks.** R-P1-1 committing unproven code — green suite + docstring disclaimer + `git revert`. R-P1-2 the smoke passes on 5 slugs while the real recorder truncates at the per-connection cap — pass bar requires every slug confirmed via `silent_subscriptions`. R-P1-3 salvage output subtly wrong and trusted — it is converted and row-count-verified like anything else; the source is never touched. R-P1-4 exit 3 + `Restart=always` loops against an outage — `RestartSec=10`, `600/30`, plus the pool's own backoff.

---

### P2 — Two read-only probes · T2

**Goal.** Decide on evidence whether a historical forecast archive exists, because that decision changes an irreversible Arrow schema.

Both probes are on hosts that are **not** `api.weather.gov` — zero UA-trap exposure against the settlement host.

**Transport and containment (R15), binding:**
- Both probes live under **`scripts/venue/`** so the existing read-only guard's path classifier binds (`tests/unit/test_polymarket_us_readonly_guard.py`), and `scripts/probes/` is added to the classifier regardless.
- Both bind to **`breezy.ingest.http.HttpClient`** — the only transport supplying host allowlisting (`http.py:622`), `follow_redirects=False` (`:630`), 3xx-as-integrity-alarm (`:857`) and a body cap (`:930`) — with per-probe `allowed_hosts` and per-instance `max_body_bytes`. AST-assert no other HTTP client is imported. The 2026-08-29 over-spend happened *because* a hand-rolled client bypassed exactly these; a request counter bolted onto raw `httpx` reproduces the defect class.
- A hard request counter raises and aborts on the (N+1)th request, unit-tested.
- Evidence discipline per `forecast_endpoint_probe_2026-08-29.md`: **EVIDENCE ONLY — NEVER INGEST** header, `request_manifest.tsv`, `.probe.json` payload suffixes no production loader reads, honest over-spend accounting.

**Probe A — Open-Meteo `/v1/previous-runs` (ranked first).** Answer, with captured payloads: does it answer un-keyed and on which host; variable naming and real max `N`; how far back the archive reaches; **valid-time or run-time anchored** (the whole lookahead question — `WEATHER_INGESTION_PROPOSAL.md:159` asserts an answer, the probe must confirm it); observable publication lag; whether values are ever **restated** for a fixed `(model, init_time, valid_time, variable)`; which `models=` identifiers are accepted; **the licence/terms text verbatim**; and response sizes to set a per-instance body cap.

Two caveats carried into the decision: Open-Meteo carries a stated 1–3 °C systematic Tmax bias, and it is on the **banned-substitute list for settlement**. This use is feature/forecast-error only; the structural wall already exists (`settlement_eligible = false`; `sites.py:298-301`).

**Probe B — IEM AFOS forecast PILs (second, high bar).** The repo already retrieves CLI products through this path, so transport and courtesy discipline exist. Unprobed: whether it serves *forecast* PILs. **Pre-registered bar:** PASS only if, over ≥50 products spanning ≥2 sites, a deterministic parser extracts a numeric daily high at ≥90%, **and** issuance time is recoverable from the WMO header, **and** the product is attributable to a zone containing the settlement station. Anything less is a documented NO and we stop — writing a forecast-text parser is a research project masquerading as an ingestion increment.

**The decision rule, and the false dichotomy it removes.** The framing "historical backtesting vs forward collection" is wrong:

> **A forecast archive cannot produce a backtest, because a backtest also needs prices, and prices are forward-only and permanently unrecoverable** (Finding A). What a forecast archive produces is a **forecast-error / calibration dataset** — historical (forecast, settled observation) pairs. Settlement truth *is* retroactively available (~1,800 city-days per site), so the pairs are completable today.

That is valuable — it is the input to `ForecastErrorModel`/`HorizonSigmaParams`, to `sigma`, to `min_model_edge`, and to P6's guard band. It is **not** a backtest, and any document claiming otherwise is wrong. This sentence is carried verbatim into every artifact Branch H produces.

### EXECUTED 2026-08-31 — the branch decision, settled on evidence

Probe A ran three times (the first two are preserved as negative findings). Evidence:
`docs/evidence/open_meteo_previous_runs_probe_2026-08-31T005848Z/` and
`docs/evidence/open_meteo_coverage_bisect_probe_2026-08-31T011135Z/`.

**Two corrections to this plan's own text.** (i) The class is `HttpTransport`, not
`HttpClient`. (ii) **`/v1/previous-runs` does not exist.** That path came from
`WEATHER_INGESTION_PROPOSAL.md:152` and was never verified; it returns
`{"error":true,"reason":"Not Found"}`. The real surface is
**`https://previous-runs-api.open-meteo.com/v1/forecast`, hourly only**,
`temperature_2m_previous_dayN`. Note the trap: `api.open-meteo.com/v1/forecast`
returns **HTTP 200 with every previous-run value null** — a named variable is not a
served variable, and only a "2xx AND it yielded the datum" rule separates them.

| Q | Answer |
|---|---|
| 1 un-keyed / host | YES, free tier, `previous-runs-api.open-meteo.com` |
| 2 naming / max N | `temperature_2m_previous_dayN`; real **max N = 7** (`day8` → 200 with 0/168) |
| 3 archive depth | **`archive_reaches_2024_01` REFUTED** — see below |
| 4 valid-time or run-time | **VALID-TIME anchored**, corroborated: identical values across window shapes rules out *request-window* anchoring only, so the populated 2022 window is the second leg (no run made "1 day before now" can forecast 2022) |
| 5 publication lag | partial; needs a second execution on a later day |
| 6 restatement | **unanswerable in one run** by construction; baseline digests captured for a later diff |
| 7 model identifiers | all five accepted |
| 8 licence text | the API origin serves **none**; absence is the finding. Moot — operator closed the gate |
| 9 response sizes | largest realistic payload 10,666 B vs a 512 KiB cap |

**Coverage is a function of BOTH date and model** (`temperature_2m_previous_day1`, NYC, 7-day hourly windows, all HTTP 200):

| date | best_match | ecmwf_ifs025 | gfs_seamless | icon_seamless |
|---|---|---|---|---|
| 2022-01-01 | **168/168** | 0/168 | **168/168** | 0/168 |
| 2024-01-01 | 0/168 | 0/168 | 0/168 | 0/168 |

**Positive control, which is what makes this conclusive:** at 2024-01-01 the *base*
`temperature_2m` series is **168/168** while the previous-run layer is **0/168** for
every model. The previous-run LAYER stops; the model does not. A malformed request is
ruled out. Boundary bisected to **2023-12-09 … 2024-01-01** (23 days); interior samples
at 2022-06-26, 2022-12-19, 2023-06-13 all 168/168, so the block is contiguous.

**`best_match` is an opaque alias.** At 2022 it is byte-identical to `gfs_seamless`
(same grid point 40.78858/-73.9661, same values) while ecmwf/icon resolve to a
different grid point (40.75/-74.0) and are empty. It silently changes which model you
got, by era and by location.

> **DECISION — Branch H PARTIAL.** A per-model historical harvest is worth building,
> but **only for ~2022-01 → 2023-12**, and it **must request explicit `models=`, never
> `best_match`**. A backfill spanning 2024 silently returns nulls. The deep archive and
> the live forward capture are **two disjoint datasets with a hole between them** — they
> must never be concatenated into one series without an explicit gap marker.
>
> **SCHEMA — `model`, `init_time_ns` and `previous_run_index` ARE required, and this is
> now evidence-based rather than speculative.** Coverage is per-model on both axes and
> `best_match` resolves differently by era and location without saying so. A record
> omitting `model` would mix GFS and ICON rows under one identity, and a forecast-error
> calibration computed across that mixture is not a per-model skill estimate — it is an
> average over an unrecorded, time-varying model selection. `init_time_ns` and
> `previous_run_index` follow: `previous_dayN` is the only way runs are addressed, and N
> is meaningless without knowing which run it counted back from. Under
> `make_strict_decoder` + one `register_arrow` these are unaddable after the first row.
>
> **`instrument_id` remains STRUCK** (R12) — unchanged by this evidence.

**Still open:** the block's older edge (2019 is null), and the far side of the
post-2024 hole. Neither changes the schema decision, so neither gates I-4.

### Probe B — EXECUTED 2026-08-31. **VERDICT: FAIL.** Registered outcome: stop.

Evidence: `docs/evidence/iem_afos_forecast_pil_probe_2026-08-31T013909Z/`. 4 of 12
budgeted requests; all HTTP 200 `text/plain`. The anticipated `fmt=text` refusal did
**not** occur.

| clause | measured | state |
|---|---|---|
| ≥50 products | 240 | PASS |
| ≥2 sites | 2 (NYC/KOKX, MDW/KLOT) | PASS |
| ≥90% numeric daily high | **0.5125** (123/240) | **FAIL** |
| issuance time from WMO header | 238/240 | FAIL |
| office attribution | 238/240 | FAIL |

Probe B carried all four of Probe A's report defects **plus one of its own**: it counted
`sites` by *step label*, so AFD+ZFP for a single city scored `sites=2` and would have
silently satisfied the ≥2-sites clause with one site. All fixed; a non-2xx, or a 2xx
whose non-empty body carries no WMO-headed product, now aborts. An *empty* 2xx does not
— that is a fact about one PIL, and aborting on it would let one quiet PIL suppress the
second site the bar needs.

The two WMO-header misses are `CCA` **corrected** products (`FXUS63 KLOT 100021 CCA`);
the BBB group after DDHHMM breaks the header regex's end anchor. Real, small, and not
worth fixing unless Probe B is ever revived.

> **DECISION (plan owner). Probe B is CLOSED as FAIL. Do not re-scope it now.**
> The post-hoc observation that **ZFP alone parses 120/120** (highs, WMO time and office
> attribution all clean) while AFD manages 3/120 is recorded as **OQ-12**, NOT acted on.
> Narrowing the product set after seeing the data and re-running on the same data is
> re-registering the bar around the result — precisely what the pre-registration
> discipline exists to forbid. If a second historical source is ever wanted, the correct
> move is a **newly pre-registered ZFP-only probe on fresh dates and sites**, judged
> out-of-sample. Probe B is not on the critical path and the branch decision is already
> settled, so that is not scheduled.
>
> **Latent hazard found in passing:** `zfp_mdw` returned 4,102,198 B against a 4,194,304 B
> per-instance body cap — **97.8%**. `limit=60` was binding on all four steps. Any future
> ZFP probe must lower `limit` or raise its own instance cap; today it is one busy
> forecast day from truncation.

Forward NWS collection (P3a) starts **regardless** of both outcomes.

**Licence gate — CLOSED by the operator, 2026-08-31.** *"open mateo doesn't require a license, we're using the freely accessible API."* Branch H proceeds on the free tier for both research and production use; no paid key, no spend decision, no operator ceiling in play. The probe still **captures the licence/terms text verbatim** as evidence — that is a record of what the endpoint said on the day we relied on it, not a gate. If the captured text contradicts the free-tier assumption, that is a finding to report, not a reason to stop.

**Schema consequence.** Under Branch H, `WeatherForecastDay` needs `model`, `init_time_ns` (run initialisation — *not* `issuance_time_ns`) and `previous_run_index`. **`instrument_id` is NOT added** (R12). Under D10 these cannot be added after the first write — so **P2 must complete before I-4 deploys** (R13), not before I-1 merges.

**Tests.** Budget counter raises on request N+1. Redirects not followed; a 3xx recorded as a finding. Payloads written `.probe.json`; AST/import assertion that no `src/` module reads `docs/evidence/` — **repo-wide, not scoped to P2** (R16 M2). Probe B reports its parse **rate**; <90% is a documented FAIL. Both probes classify as venue-touching under the read-only guard. Both marked `live`/`venue_live`, deselected by default.

---

### P5 — Close-only: fix the control, then confirm the venue · fix is T3, probe is T2

**Promoted to the critical path (R4).** Revision 1 treated this as cleanup. It is not: Nautilus has **no naked-short denial** (`engine.pyx:974-985` — `is_position_reducing_sell` merely `continue`s; a position-opening sell is denied only by `CUM_NOTIONAL_EXCEEDS_FREE_BALANCE`, itself gated on `not allow_borrowing`). **Breezy's guard is the control**, and it is defective.

#### P5.1 — The defect

`risk.py:176-181` tests `portfolio.net_qty(...) + delta < 0`, and `net_qty = position_qty + pending_qty` (`:80-81`) where `pending_qty` is **signed and includes pending buys**. A pending buy inflates `net_qty`, so a sell that would open a short can pass. Today the hole is masked by a `cache.orders_open(instrument_id=...)` skip in `_maybe_submit` — and **P4.2's widening would have removed the mask.** This is why P5 now precedes P4.

**Fix:** close-only is tested against **settled position only** (`portfolio.position_qty`), never against `net_qty`. Pending buys are irrelevant to whether a sell opens a short.

#### P5.2 — The default

`risk.py:176-181` already implements close-only correctly *given the right input*. The remaining defect is `allow_short: bool = True` (`risk.py:61`) plus the three configs passing it through. Flip all four; make `allow_short=True` unreachable without an explicit operator act.

**The second half matters more.** `calibration_mean_reversion` was SHORT_YES-only in the tested window, so under `allow_short=False` it can execute **no signal at all**. That must not look like "no opportunities". A `shorts_disabled` reason counter surfaces through the existing alert path (`health.py:584-660`, `:495`). A strategy producing zero trades because it is disabled and one producing zero trades because the market is efficient are the same observation and completely different facts.

Delete nothing from `_submit_delta`: `OrderSide.SELL` on a negative delta is correct for **closing** and remains needed.

#### P5.3 — The read-only probe (batched with P2)

Zero write requests, cannot construct an order, under `scripts/venue/`, bound to `ingest/http.py`. Record `marketSides` in full for a live weather slug; attempt a book/BBO read keyed on a **side id** rather than the slug (a 404/400 is the expected answer and a positive finding); capture order-side semantics from openapi/trader-guide text; record whether any weather market has a sibling instrument for the complementary outcome.

Existing evidence raises the prior for one book per market: `parsing.py:1069-1073` requires **every** `marketSides[i].identifier` to equal the market **slug**, `:1081-1085` requires exactly one `long: true`, and the SDK keys `MarketBook`/`MarketBBO` on `marketSlug` with no per-side book type.

**What the probe cannot answer read-only:** whether the venue *accepts* a SELL from flat. That needs a real order — operator-gated, and **not proposed here**. P5's fix is correct under both answers. Recorded as OQ-4, and it must not be *asserted* as answered.

**If a real second book exists**, NO-side support becomes a genuine feature with its own plan. Out of scope. The default flip is still correct in the interim.

**Tests.** From flat, a SHORT_YES decision refused with `shorts_disabled`. **From a long with a pending buy outstanding, a sell that would open a short is still refused** (kills the R4 defect). From a long, a delta that **closes** is allowed; one crossing to net-short refused **at the boundary** — turning close-only into refuse-all would strand every open position. `allow_short=True` unreachable from any default path, asserted on a bare `RiskLimits()` as well as the three configs (R16 M1). A `shorts_disabled` refusal reaches the alert sink. The probe issues zero write requests and cannot construct an order.

---

### P4 — Risk correctness · T3

**Goal.** One coherent system in which three concurrent strategies cannot triple a cap, an aggregate ceiling exists, caps shrink with equity but never exceed an absolute ceiling, and the operator's two controls have a real home that fails closed.

**Read §2.3 first.** Every cap below is in **premium at risk**.

#### P4.1 — Native, configured, not authored

`max_notional_per_order` is native and enforced. **But it is per ORDER**, so a sequence accumulates past it; Breezy's residual job is the *cumulative* per-instrument ceiling. The account-wide free-balance guard exists but is **conditional on `not allow_borrowing`** — do not state it unconditionally, and do not duplicate it.

#### P4.2 — Finding D closes by reading the native portfolio, enumerated fail-closed

`PortfolioFacade` is account-wide (`portfolio.pyx:1047-1053`, `:1428-1433` pass `strategy_id=None`; `cache.pyx:4220-4245` intersects only on non-`None`). Finding D's defect is **enumeration**, not measurement.

**Enumeration, corrected (R6).** `is_weather_market` **raises** on missing/malformed status, by design. So:

```
KNOWN       → in scope
UNKNOWN     → out of scope
UNDECIDABLE → IN SCOPE (fail closed) + alert
```

A `try/except` treating the raise as "not weather" silently drops instruments from aggregation and **reopens Finding D through a different door**. Tested with an instrument whose `info` lacks the key.

**Measurement.** Position exposure and **pending-order exposure are two separate native reads** — `net_exposure` counts positions only; `Cache.orders_open(..., strategy_id=None)` is the complement, as the engine itself does (`engine.pyx:717-724`). Both are converted to **premium at risk** (§2.3) before entering any ceiling. Pending-order premium comes from the **same reserve ledger** P4.5 maintains, not from an independent second read — revision 1 maintained two representations of one pending order.

**Deleted from the design:** `WeatherExposureView`. There is no injected object; `Cache.instruments()` enumerates and `PortfolioFacade` measures.

**Still ours, and thin:** the instrument → `event_key` mapping. It maps and sums native numbers. **If it grows its own state, the null hypothesis was abandoned** — a test asserts it holds no quantity-typed field and no mutator.

**`_equity()` -- WITHDRAWN as a removal. It is a LESSONS L-2 unit change, not duplication.**
Revision 2 originally said `_equity()` (`forecast_revision/strategy.py`, and the same
method in the other two strategies) hand-loops `account.balance_total(...)` and merely
duplicates native `PortfolioFacade.equity(venue)`. **That instruction is withdrawn.**

The two are NOT the same number. Native `equity()` is
`balance.total + SUM(mark_value of open positions)` (`portfolio/portfolio.pyx:1180-1181`);
Breezy's `_equity()` returns **`balance_total` only**. Swapping them changes what every
equity-scaled cap is a fraction OF, inflating the caps by the mark-to-market value of
open positions -- largest exactly when the book is most exposed.

Either keep the local definition and document why it is deliberately not native
`equity()`, or adopt native and re-derive every fraction against the new base behind a
characterisation test, declared as a behaviour change. This is the SECOND "just use the
native one" instruction in this plan that was really a unit change (the first:
`net_exposure` vs `qty x contract_size`, section 2.3). **The pattern is now the
expectation, not the surprise: before ANY native substitution in P4, state both units
and prove they match.**

#### P4.3 — Aggregate ceiling

`RiskLimits` gains `max_total_premium`; `evaluate_order` compares it against the summed premium at risk from P4.2. Checked after the location check so failure-reason ordering stays legible. **Run `describe_binding_order` against the actual defaults first** — R9 shows `max_event_notional` is currently dominated by `max_position_contracts` and can never fire. Any cap shown unreachable is deleted or re-scaled before shipping, not shipped as decoration.

#### P4.4 — Equity scaling

`effective = min(absolute, fraction × equity)` — monotone-safe in both directions, where a bare fraction would *ratchet up* after a winning streak and a bare absolute would never shrink after a drawdown. **Because §2.3 changes the unit, the characterisation test is written against the new intended semantics, not against today's numbers** — this is a deliberate behaviour change, called out as such. Per R16 M2, do not ship equity-fraction fields for caps that R9 shows never bind; scale what actually binds.

#### P4.5 — The daily budget, and the inverted kill-switch

**Accounting (R7).** Reserve keyed on `client_order_id` at the **limit price** (or $1.00/contract for a market order, which has no bounded price); reconcile from terminal `OrderFilled` / `OrderCanceled` / `OrderExpired` events, **idempotently**. Not from `orders_open` — an IOC order is never in it, so the revision-1 scheme could not distinguish cancelled-unfilled from filled, and on the normal partial-fill outcome would release a reservation that was really spent. Partial fills convert the filled portion and release the remainder.

**What it counts (§2.2, §2.3): peak open premium at risk, plus modelled entry and exit fee reserves.** Not cumulative spend — that charges turnover, not risk.

**Day boundary: UTC.** Five cities, four time zones; any local choice privileges one and creates a per-instrument boundary. A budget is a property of the operator's capital, not of a market's calendar. Persisted so it is auditable. Raised as OQ-3.

**Persistence:** a `budget:` namespace in a `SqliteStateStore` **owned by the trading process**, and a **different file** from the ingest process's store — `SqliteStateStore` is single-writer by construction, and two processes on one file is a last-write-wins hazard.

**The actuator: `HALTED`, not `REDUCING` (R2, OQ-8 closed).** REDUCING denies a BUY only when already `is_net_long` **on that instrument**, so a long-only bot spread across bucket instruments keeps opening new positions straight through a breach; and with bid depth ~0.3 contracts there is nothing to reduce into anyway. **On this venue a budget breach is a stop-opening control with no unwind, and the plan says so plainly.**

**The polarity is INVERTED (R5).** A control that must run in order to be safe is not a control. `RiskEngine` starts ACTIVE (`engine.pyx:132`) with no initial-state config; `Actor.handle_event` swallows every exception without re-raising (`common/actor.pyx:4789-4793`); and dispatch happens only at `ComponentState.RUNNING`. So:

1. Call `node.kernel.risk_engine.set_trading_state(HALTED)` at composition, immediately after `build()`.
2. The `BudgetGuard` actor **promotes** to ACTIVE only after it reads a configured budget and completes one clean evaluation.
3. It writes `budget:last_eval_ns`; a separate check **re-HALTs** when that goes stale (>2 intervals).
4. A config test asserts **`bypass is False`** on every shipped node config — `bypass=True` returns before `_execution_gateway` (`engine.pyx:414-418, 455-459, 494-498`) and defeats HALTED, the per-order cap and both free-balance guards with one boolean.

**A missing value fails CLOSED — scoped correctly (R17).** With no operator-supplied daily budget, the guard never promotes and the node stays HALTED. **This applies when a signer is present** — the same predicate as P1.5's DEBUG refusal — so backtest and paper runs are unaffected while any node that can reach the venue fails closed. Rejecting the alternative of scoping it to the live-trading gate: that makes the safe default depend on a second flag. And per R16 M1, the refusal **alerts at startup**, not once per refused order at 3 a.m.

**The per-position control.** The dollar cap is native configuration (`max_notional_per_order`), mapped from the operator's single figure at composition. Breezy adds only the **cumulative** per-instrument ceiling in premium terms. `max_position_contracts` stays a venue/liquidity bound. The operator's explicit "**not** per weather market" is honoured by leaving `max_event_premium` (station+climate-day) as *our* parameter, distinct from theirs.

**Before tuning anything, measure OQ-10.** `quote_tradable` requires `min_liquidity_contracts = 25` against `min(bid_size, ask_size)` (`risk.py:177`), and the bid side is BIMODAL, not uniformly thin, and only `forecast_mispricing` calls it. Tuning caps above a gate that rejects the book is measuring the wrong thing. Depth belongs on the **executable side** for the intended direction, not `min(both)`.

**Tests.** Flagship: three `RiskManager`s over one event sum to **one** event premium; a third order exceeding it is refused — must fail against today's code. An UNDECIDABLE instrument is counted in scope, not dropped. A pending unfilled order contributes to the cap. N concurrent submits totalling > budget: the last refused **before** any fill. A partially-filled IOC converts the filled portion and releases only the remainder. Reconcile is idempotent under a duplicate terminal event, and correct under a **dropped** one. Counter survives restart; a new UTC day resets; the same day does not. **No configured value + signer present ⇒ node stays HALTED and alerts at startup.** No configured value + no signer ⇒ backtest runs normally. `bypass is False` on every shipped config. **Contract test (R13-class):** `set_trading_state(HALTED)` on a live test node causes a subsequent `SubmitOrder` to be **denied**, asserted on the `OrderDenied` event — not merely that the state field changed. Contract test: a `max_notional_per_order` breach produces `NOTIONAL_EXCEEDS_MAX_PER_ORDER`. A `BudgetGuard` whose `on_event` raises leaves the node **HALTED**, not ACTIVE. `describe_binding_order` names the binding cap at the configured equity. `exclusive_conflict` behaviour byte-identical before and after.

**Risks.** R-P4-1 enumerating all weather instruments slows per-tick evaluation — measured; the static id set cached, derived quantities never. R-P4-2 the event-grouping mapping grows into an aggregator — **HIGH**; no quantity-typed field, no mutator, asserted. R-P4-3 reserve/reconcile leaks on a dropped terminal event — **HIGH**; periodic reconciliation against `cache.orders_open` ∪ position state as a *repair* pass, with the ledger authoritative. R-P4-4 UTC boundary wrong for the operator's mental model — LOW, persisted and auditable.

---

### P3 — Forecast ingestion · P3a T1, P3b T4

`FORECAST_INGESTION_PLAN.md` revision 2 stands. Deltas only:

1. **The split.** `P3a = I-1 + I-3 + I-2 + I-4 + I-5` (the increment that writes the first row, and so starts the forward clock); `P3b = I-6 + I-7 (+ I-8)`.
2. **The gate moves (R13).** P2 gates **I-4's deploy**, not I-1's merge. I-1/I-2/I-3 merge, test and review while P2 runs.
3. **Field set:** `model`, `init_time_ns`, `previous_run_index` iff Branch H. **No `instrument_id`** (R12).
4. **Null-hypothesis reminders.** The as-of bound is **native** (`parquet.py:2150-2156`, `:2103-2109`); `domain/forecast_selection.py` must not exist. `SiteRegistry.enrichment_coordinates()` is pre-built and dead — call it. The Actor's timer/stagger machinery is native and already reused; author a record type, a URL builder, a parser and a reader — never a scheduler, a timer, a retry loop or a catalog bound.
5. **R-11 stays a live gate:** *"An already-open position is never flattened when the forecast disappears."* P4's caps do not close it, and a daily budget does **not** substitute — a budget bounds new spend; it does not flatten an existing position. **And per R2, neither does HALTED.**

---

### P6 — Preliminary-settlement guard band · T4

**Goal.** Make the decision boundary-aware: a trade whose bucket outcome a ±1 °F preliminary→final revision would flip must be treated as riskier than one it would not.

**Deferred last, honestly:** its input does not exist yet, and P4's caps plus P5's close-only bound the exposure this hazard can create meanwhile.

**The correction that shapes it.** `GUARD_BANDS` (`settlement_bucket_guard_band.py:63`) compares `cli_bucket` against `metar_bucket` (`:73-82`) — **METAR-vs-CLI**, measurement-source aliasing (different instrument, rounding, observation window), roughly **distance-independent** above ~1 °F. Finding G's hazard is **prelim-vs-final CLI** QC revision — strongly distance-**dependent** and concentrated at ±1 °F. Importing the METAR band gives a curve too flat and too wide: it taxes mid-bucket trades carrying no hazard and under-taxes the ±0.5 °F cases carrying all of it. **The mechanism transfers; the fitted band does not.** The study must publish **both hazard curves side by side**, so non-transferability is demonstrated rather than asserted.

**P6a — the study, pre-registered before it runs.** Using the P0-backed archive and `scripts/analysis/settlement_truth_dataset.py` (committed in P0), estimate `P(bucket flips | distance from nearest bucket edge)` for preliminary→final CLI revisions, stratified by city and distance. Pre-register hypothesis, bands and accept/reject rule **before** looking at the outcome.

**P6b — the wiring, and the locus is corrected.** Revision 1 added a penalty to the edge *threshold*. That is the wrong locus: revision hazard is a property of the **outcome distribution**, not the decision threshold. The additive form charges the same penalty at p=0.10 and p=0.90 though a flip costs `|1−p|` versus `p`, and it leaves **size** untouched — so boundary trades that clear the raised bar are still full-size on the highest-variance outcomes, the opposite of what added variance calls for.

**Correct treatment:** fold the hazard into the probability estimate —

```
h      = P(flip | distance)          # from P6a, monotone non-increasing
p_eff  = (1 − h)·p_model + h·p_flipped
```

`p_eff` then flows automatically into **both** edge and size. `WeatherBucketFacts.distance_f` (`weather_bucket_facts.py:75-84`) is the distance primitive — use it, do not reimplement it.

**Fix the adjacent unit error in the same pass (R16).** `transaction_cost_prob = 0.015` is a flat probability-unit stand-in for a fee that is genuinely `θ·p(1−p)`: coincidentally right at p=0.5, ~3× over-charged at p=0.9 — biasing against exactly the confident-tail trades the model is best at. P6b already edits that comparison.

**Tests.** With `h ≡ 0`, every current decision reproduces exactly. At distance 0, `p_eff` is pulled toward 0.5 more than at distance 3. `h` is monotone non-increasing in distance. **Size responds to `h`, not just the accept/reject decision.** The estimate's provenance (study path + date) is asserted present in the module — no constants without a traceable origin. `distance_f` is used, not reimplemented. The fee term is `θ·p(1−p)`, not a constant.

**Risks.** The study run post-hoc to rescue a threshold — closed by pre-registration. The METAR band imported by mistake — closed by the provenance assertion and the side-by-side curves. The guard makes the strategies untradeable — measurable, and reportable as a **finding about the venue**, never a reason to lower the guard.

---

### P7 — Observability and pre-capital validation · T4 · NEW (R16)

**Goal.** Every control this plan adds is *observed*, and the whole risk surface is re-validated before capital exists.

Revision 1 shipped exit 3, `TradingStateChanged`, `OrderDenied` reasons, budget refusals and `shorts_disabled` — and **none of them reached a sink**. `quote_tape_cli.py` constructs no `AlertState` and no alert sink (only `QuoteTapeDiskMonitor`), so "the recorder gave up on purpose" is visible only via `systemctl status`. No §10 criterion required any new control to be *seen*.

1. **An alert sink in the recorder**, via the existing `resolve_alert_sink` (`health.py:495`) — exit 3, conversion shortfalls, prune refusals.
2. **Subscribe to `events.risk`** so a `TradingStateChanged` (the halt) is recorded with its reason.
3. **Surface denial reasons** — `NOTIONAL_EXCEEDS_MAX_PER_ORDER`, `CUM_NOTIONAL_EXCEEDS_FREE_BALANCE`, `shorts_disabled`, budget refusals — through the same sink, with counters.
4. **The artifact-liveness watchdog**, deferred from P1.4, built here against **measured** overnight inter-write gaps and an actual sink. Alert-only until the threshold is measured; promotion to exit-causing is a separate gated change.
5. **Re-run the 36-run backtest sweep** after P4/P5/P6 change the risk surface. §2 establishes this harness and no other increment re-runs it — it is the only cheap validation available before capital exists, and it will show directly whether the new caps let anything trade at all.
6. **A rollback note per increment.** Only P1.1 has one today. Each of: a deployed recorder config, a partial prune, the `allow_short` flip, a `TradingState` halt.

---

## 5. Build order

```
P0   backups (archive + tape) + commit P6 deps   [T0]  hours
P1   commit -> attended smoke -> convert gate     [T1]  ~1 week
     -> shutdown_system/exit codes -> unit
P2   probes (Open-Meteo, IEM AFOS)                [T2]  ~2 days  -- parallel with P1
P5p  market-sides probe                           [T2]  hours    -- batched with P2
P5f  close-only fix + default + counter           [T3]  ~1 day   -- BEFORE P4
P4   risk correctness                             [T3]  ~4 days
P3a  forecast I-1..I-5 (deploy gated on P2)       [T1]  ~1 week
P3b  consumer + Open-Meteo                        [T4]  ~1 week
P6   guard band: study -> wiring                  [T4]  ~1 week
P7   observability + backtest re-validation       [T4]  ~3 days
```

**Critical path: `P2 → P3a-deploy`** (Arrow schema freeze).

**Serialization, corrected (R16).** Revision 1 claimed P4, P5f and P6b are independently mergeable. **They are not** — all three edit `risk.py` and the same three `config.py`, and P4 and P6b both touch `evaluate_order`. They merge **in the order P5f → P4 → P6b**, and P5f must be first for the R4 reason. P1's sub-increments are **gated**, not independent: nothing runs unattended until P1.2 passes.

Genuinely independent: P0, P2, P5p, P7 items 1–3.

---

## 6. Test doctrine

1. **A characterisation test precedes any behaviour-preserving refactor** and must pass unmodified after. Where a change is *not* behaviour-preserving — §2.3's unit change — say so explicitly and write the test against the new intended semantics.
2. **Every "loud failure" claim is proved by asserting a non-zero exit or a raised exception**, never a log line. C1 and C2 are both failures of things that logged and continued.
3. **Every "NATIVE — configure" verdict gets a contract test that executes the native path and asserts the outcome**, so a version bump fails RED. No verdict rests on a docstring. This plan moved four increments from build to configure; each now depends on compiled Cython behaviour rather than code we test.
4. **Every probe** is `live`/`venue_live`-marked, deselected by default, issues zero write requests, carries a hard request budget, binds to `ingest/http.py`, and classifies as venue-touching under the read-only guard.
5. **Every fail-closed claim is tested from the failing side** — not that the control works when configured, but that the system refuses when it is absent, dead, or throwing.
6. **No safety or contract test is weakened to go green.** Where a new cap makes an old test fail, it is re-expressed against the new intended behaviour with the change documented — never deleted.

---

## 7. Non-goals

1. Any recovery of pre-capture Polymarket.us price history. Impossible (Finding A).
2. Any live-trading enablement or real-money order.
3. Supplying values for the two operator controls. Mechanism only.
4. NO-side instrument support, and the sibling-bucket basket (OQ-11).
5. Re-planning forecast ingestion.
6. Any change to settlement behaviour — **except** I-4's mandatory `SettlementGate.ua_trap_latched()`, which P3a inherits from the forecast plan and which is therefore in scope by inheritance, not by this plan's choice.
7. Fixing R-11 (no flatten on forecast disappearance) or R-12 (settlement UA-trap fail-open). Both tracked there; both still gate live use.
8. Strategy alpha work beyond removing an illegal order path (P5) and correcting the decision's treatment of boundary risk and fees (P6).
9. Any patch to `nautilus_trader`.
10. Off-host backup provisioning that costs money — surfaced as an operator spend decision with evidence attached. (The Open-Meteo licence question is CLOSED — free tier, operator-confirmed 2026-08-31.)

---

## 8. Cross-cutting risks

| ID | Risk | Sev | Mitigation |
|---|---|---|---|
| **R-1** | P1 ships and the recorder still records nothing — the pool has never been observed carrying a live QuoteTick | **HIGH** | The harness already exists (R3); fix auth + teardown, then a pre-registered per-slug pass bar. **No unattended run until it passes** |
| **R-2** | P2 slips and I-4 deploys without it, foreclosing Branch H | **HIGH** | The gate is at I-4's **deploy** (R13). I-4 waits, unconditionally |
| **R-3** | A native control is assumed sufficient and silently is not | **HIGH** | Test doctrine item 3, without exception. The audits were right about the mechanisms and wrong about the *degree* twice (REDUCING, the free-balance guard) — degree is where this fails |
| **R-4** | The kill-switch fails open — guard absent, not RUNNING, or throwing | **HIGH** | Inverted polarity (§4.P4.5): HALT at composition, promote on proof, re-HALT on staleness. Tested from the failing side |
| **R-5** | A unit mismatch re-enters the cap hierarchy | **HIGH** | §2.3 declares one unit for the whole system; every ceiling is premium at risk; `net_exposures()` is reporting-only |
| **R-6** | Reserve/reconcile leaks on a dropped terminal event | **HIGH** | Periodic repair pass against native state, ledger authoritative; tested with a dropped fill |
| **R-7** | Salvage or prune destroys the only copy | **HIGH** | Salvage never writes into the source; prune requires verified conversion + record-before-delete + `--apply` + open-instance refusal; **and P0 now backs the tape up** |
| **R-8** | Native `consolidate_*` destroys data with none of our gates | **HIGH** | Never `consolidate_catalog`; narrowed `consolidate_data` behind census→re-count, originals kept on shortfall, maintenance serialized |
| **R-9** | A signed recorder logs at DEBUG and leaks a long-lived signature | **HIGH** | Refuse DEBUG/TRACE when a signer is present; unit-file `Environment` as defence in depth; evidence leak-scan extended |
| **R-10** | The systemd start-limit or `RestartPreventExitStatus` latches the recorder off overnight | **HIGH** | 600/30 not 300/3; exit-code split so `RestartPreventExitStatus=2` cannot catch an IO fault |
| ~~R-11~~ | ~~Open-Meteo's non-commercial tier makes Branch H unusable~~ | **CLOSED** | Operator confirmed 2026-08-31: free API, no licence required. Text still captured as evidence; forward NWS proceeds regardless |
| R-12 | The event-grouping mapping grows into an aggregator | MED | No quantity-typed field, no mutator, asserted by test |
| R-13 | Caps are tuned above a liquidity gate that rejects the whole book | MED | OQ-10 measured **before** P4 tunes anything |
| R-14 | Probes fall outside the read-only guard's classifier | MED | Under `scripts/venue/`; `scripts/probes/` added to the classifier; classification asserted |
| R-15 | Three concurrent agents in one tree produce unreproducible failures | MED | Commit by explicit path, never `git add -A` |
| R-16 | Silent universe truncation: one-sided books never reach the tape, so deep-OTM strikes are invisible to signal and to measurement alike | **HIGH** | OQ-13 answered before P4 measures; the re-derivation script must run on an unconditioned sample |

---

## 9. Open questions

**OQ-1 (blocking P7 item 4).** The real overnight inter-write gap for a 5-instrument weather tape. Guessing it is a data-loss bug wearing a safety costume; the watchdog stays alert-only until measured.

**OQ-2 — CLOSED 2026-08-31.** Yes un-keyed, and **valid-time anchored** — but at `previous-runs-api.open-meteo.com/v1/forecast`, hourly only; `/v1/previous-runs` does not exist. Branch H PARTIAL (2022-01 → 2023-12, explicit `models=`). `model`/`init_time_ns`/`previous_run_index` are required. See §4.P2.

**OQ-3 (non-blocking, P4).** UTC or per-instrument climate day for the budget boundary? UTC chosen and argued; persisted so a later change is auditable.

**OQ-4 (P5, unanswerable read-only).** Does the venue reject a SELL from flat? Needs a real order — operator-gated, not proposed. P5's fix is correct under both answers, so this is a documentation question that must not be *asserted* as answered.

**OQ-5 (P0, open).** Is there any off-host destination on this operator's infrastructure? Provisioning costs money.

**OQ-6 (P1, open).** Does the recorder's graceful stop complete inside 120 s under load? P1.2 measures it; a slower stop means a longer timeout, never a SIGKILL.

**OQ-7 — CLOSED.** Does Nautilus deny a position-opening sell? **No** (`engine.pyx:974-985`). Breezy's guard is the control. Drove P5's promotion.

**OQ-8 — CLOSED.** `HALTED`, not `REDUCING` (R2).

**OQ-9 (NEW, deferred to the forecast plan).** Should a schema-stable **raw forecast payload** record (the `NwsRawProduct` pattern — `raw_text` + digests, no derived fields) start the forward clock on day 0, reducing P2 to a decision about the *derived* record only? A good idea that belongs to `FORECAST_INGESTION_PLAN.md`, not here.

**OQ-10 (NEW, blocking P4's tuning).** `min_liquidity_contracts = 25` against `min(bid_size, ask_size)` versus a measured median top-of-book bid of ~0.3 contracts. Does the gate reject essentially every weather quote before any cap is consulted? If so, depth belongs on the **executable** side for the intended direction, and cap tuning is measuring the wrong thing.

**OQ-13 (NEW, blocking OQ-10's measurement).** The quote tape cannot see a one-sided book. `parse_book_top` (`parsing.py:582`) requires a best level on both sides and the depth path indexes `bids[0][0]` (`:574`), so an empty `bids` array raises `VenuePayloadError` and the frame produces **no row of any kind**. Measured live: 5 slugs with `bestBidQuote = None` yielded 247 errors and zero rows against 675 each for 5 two-sided slugs. Two questions, in order: (a) what SHOULD a one-sided frame emit — a `QuoteTick` with an explicit zero/absent bid, a depth row only, or a distinct record type — given that a `QuoteTick` with a zero bid is a lie about a book that has no bid at all? (b) How many weather instruments are currently invisible to the bot for this reason across a full ladder, not a 10-slug sample? Until (a) is answered, every bid-side statistic in this plan is conditioned on a two-sided book, and the deep-OTM strikes a confident tail forecast would target are exactly the ones missing.

**OQ-12 (NEW, deliberately not acted on).** ZFP-only parses 120/120 where the registered AFD+ZFP mix parsed 123/240. Acting on that against the same data would be re-registering the bar around the result. A fresh pre-registration judged out-of-sample is the only legitimate route, and it is not scheduled.

**OQ-11 (NEW, out of scope).** Is a sibling-bucket long-only basket a legitimate expression of the mean-reversion signal? `P(¬A) = Σ P(B)` over siblings, purchasable on the deep ask side, and fees favour the basket — but `exclusive_conflict` currently forbids more than one long YES per `event_key`, and cost is `Σ ask_i` versus `1 − bid_A`. An evidence question, not a default.

---

## 10. Success criteria

- [ ] The settlement-alignment archive **and the quote tape** exist on a second device (`st_dev` asserted), verified from a **restored extraction** against a git-tracked manifest.
- [ ] The recorder **exits non-zero** within a bounded time of losing its feed; a systemd unit restarts it without latching on a transient blip or an IO fault.
- [ ] A conversion that would have silently produced zero rows now **fails loudly**, and a truncated feather's complete prefix is salvaged without touching the original.
- [ ] `consolidate_catalog` is never called; the narrowed native path is census-verified.
- [ ] Attended evidence shows a real QuoteTick reaching the `DataEngine` through the production pool for **every** subscribed slug.
- [ ] The recorder **refuses to start** at DEBUG/TRACE when a signer is present.
- [ ] Both P2 probes are committed as EVIDENCE-ONLY documents with honest request accounting, bound to `ingest/http.py`, classified venue-touching; a branch decision predates I-4's deploy.
- [ ] **No naked short is constructible from any default configuration**, proven from a long **with a pending buy outstanding** — the R4 defect.
- [ ] A structurally-disabled strategy says so through the alert sink.
- [ ] Three strategies over one event cannot exceed one event ceiling, proven by a test that fails against today's code; an **undecidable** instrument is counted in scope, not dropped.
- [ ] **Every ceiling is expressed in premium at risk**, and no cap ships that `describe_binding_order` shows can never fire.
- [ ] A persisted daily budget survives restart, resets on UTC, reconciles correctly across partial IOC fills and a dropped terminal event, and — with a signer present and no value set — **leaves the node HALTED and alerts at startup**.
- [ ] `bypass is False` on every shipped node config; a `BudgetGuard` that throws leaves the node HALTED.
- [ ] Every "NATIVE — configure" verdict has a contract test that **executes** the native path — including HALTED actually denying a submitted order.
- [ ] The guard band is wired from a pre-registered prelim-vs-final study, publishes both hazard curves, enters through `p_eff` so **size** responds, and is behaviour-identical to today at `h ≡ 0`.
- [ ] Every new control reaches an alert sink, and the 36-run backtest sweep is re-run after the risk surface changes.
- [ ] `lint-imports` green with **zero** new `ignore_imports` entries — verified by running it.
- [ ] No document produced by this work claims that any forecast archive enables a price backtest.
