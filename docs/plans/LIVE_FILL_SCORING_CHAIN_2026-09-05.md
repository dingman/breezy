# Live fill -> scored-trial chain (2026-09-05) -- **Rev 4**

Plan artifact only. v1 `trial_scorer.score_trial`, the 17-column `ScoredTrial`/store and `live_family_tally.py` SOURCE are BINDING and untouched; the v1 WRAPPER `deploy/systemd/live-tally-run.sh`
may gain flags -- a wrapper change, not a v1 module change. Rev 4 applies round-3 peer review (dispositions, section 6); round 3's symmetric fee rule is KEPT as patched. Citations re-verified 2026-09-05 against the working tree;
what could not be is marked UNVERIFIED.

## 1. Goal state and the walks

**Goal (falsifiable).** For every real Polymarket.us fill from `CurrentRungHoldStrategy` on the live node:
1. a durable fill record exists in the exec `SqliteStateStore` **before any other consequence of the fill**, carrying venue_order_id, client_order_id, instrument_id, ts_event, ORDER-level
  cumulative qty/cost and the **venue-reported** cumulative fee plus its reconciliation flag (station / climate_day / entry_ask arrive by join -- I2);
2. once that station-day's NWS CLI is FINAL, a scored row for `current_rung_hold/trial/{station}/{climate_day}` exists in the scored-trials store (plus `provenance.json` + `fill_order.jsonl`)
  **at the FIRST 14:15 UTC run after the FINAL lands** -- a lag of <= 1 day when the FINAL issues after 14:15 UTC on D+1 -- ahead of that run day's 14:30 v1 and 15:30 v2 tallies; no manual step,
  idempotent, q != 1 excluded before scoring (ruling Q1, `score_live_trials.py:238-252`). The scorer is idempotent and the tallies cumulative, so the lag costs only latency. *Measured
  (`docs/evidence/nws_cli_final_issuance_vs_1415utc_2026-09-05.md`, product-header `issuance_time_ns`, 2026-08-16..09-03): every station's FINAL lands 5.3-8.0 h
  BEFORE 14:15 UTC D+1 (medians NYC -7.8 h, MDW -7.7 h, LAX -5.9 h, MIA -5.8 h, SFO -5.7 h); 90/90 routine finals early, the single late one a go-live backfill correction.*
3. the v1 structural-dead stop is actually EVALUATED over the CORRECT window: `live-tally-run.sh` passes BOTH `--fill-source` and `--covered-listed-station-days` (`live_family_tally.py:454-465`)
  with numerator and denominator sharing ONE window start -- else it silently never fires (O1) or fires falsely (A3).

**Happy walk (fill 20:31 UTC, day D).** (1) `_evaluate` latches `current_rung_hold/trial/{station}/{D}` at DECISION time with `instrument_id` + `ask` (`trial_day_latch.py:113-114`;
`strategy.py:438`); that key's `station` segment is the registry **city** key (`strategy.py:166-171`), NOT by definition the CLI location -- see I2. (2) `_maybe_submit` -> `_submit_order`
(`exec/client.py:1511`) -> `post_order`; `classify_create_order_outcome` -> `KIND_ACCEPT_FILL` (`submit_chain.py:478-493`), which **[I1a]** now also carries order-level
`cumulative_qty`/`cumulative_cost`/`cumulative_fee` and `fee_reconciled`. (3) **[I1b]** `record_fill` is the FIRST action of that branch (`client.py:1585-1613`), before `true_up_booking` (:1591),
`_retire` (:1594), `_generate_submitted` (:1595), `generate_order_filled` (:1597); it writes `exec/polymarket_us/fill/{venue_order_id}` + index (:1315-1340) and `SqliteStateStore.set` COMMITs
before returning (`runtime/sqlite_store.py:123-124,168`), so evidence lands before any other effect of the fill. (4) `generate_order_filled` publishes natively; `breezy-nws-ingest.service` lands
the FINAL CLI when NWS issues it. (5) **[I3]** 14:15 UTC, `breezy-score-live-trials.service` runs `score_live_trials.py` once per city, resolving the exec state-DB path itself (R8, I2); **[I2]** the reader pairs each
fill to its latch by `instrument_id` -> `trial_id`/`station`/`climate_day` from the latch KEY and `entry_ask` from `TrialDayRecord.ask`; `_admit_fill` gates q != 1, `fill_below_ask` and
`fee_unverified`; `score_trial` scores against `read_climate_day_including_corrections`; `write_scored_trials` appends `score_seq`; sidecars written; exclusions appended. (6) 14:30
`live-tally-run.sh` (both stop flags + the shared window start), 15:30 `family-tally-v2-run.sh pm_us_crh_v2`; both assert the scorer's dated success marker first (I3).

**Failure walks.**
- *Dies between POST and response.* `except` at `client.py:1572-1577` -> `_refuse(AMBIGUOUS_REASON)`, intent stays OPEN, no record, nothing scored. I1b runs only on a classified
  `KIND_ACCEPT_FILL`, so it changes nothing here.
- *`record_fill` raises on a real fill.* Exact control flow in I1b: ERROR + the full serialized record (the seven fields at `client.py:413-419` plus I1b's two are ids, a side, Decimals, a bool
  and a ts -- no secret, verified), `_refuse` latching `_trading_refusals` so every later submit is denied (`_submit_order` :1515-1517) and `degrade()` (:1766-1767) raises exactly one CRITICAL
  alert, the intent left OPEN (`probe_open_intent` :297; `reconcile_at_startup` `submit_intent.py:397-433` leaves it OPEN because the fill probe is a constant-`False` stub, `client.py:695-698`),
  and `OrderSubmitted` + `OrderFilled` still published so Nautilus books the position.
- *Fee cannot be reconciled to the legs.* Record written in full with `fee_reconciled=False`; `_refuse` (second fixed reason) halts later submits; retire/publish proceed -- **the fill is real,
  only the fee is untrusted**. I2 then excludes it as `fee_unverified`, so it is never scored.
- *Venue returns qty 0.37, or below the entry ask.* Recorded in full by I1b (the record is evidence, not a filter); `_admit_fill` returns `FillExclusion("partial_fill")` / `fill_below_ask`, so it
  never reaches `score_trial`, never enters Wilson n/k or sum(PnL), and lands in `excluded_fills.jsonl` and the v2 coverage table (I3c) -- loud, never silently dropped.
- *Fill source unreadable.* `_open_readonly` returns `None` for an absent or `mode=ro`-refusing DB (`fill_time_count.py:84-98`; a WAL DB whose `-shm` is missing after an unclean exit can fail to
  open read-only). The scorer exits NON-ZERO and writes NO dated marker, so BOTH tally wrappers fail loudly: a silent zero-fill run must be indistinguishable from nothing, never from a real
  no-fill day (A5).
- *CLI never FINAL.* `score_trial` refuses `no_record`/`preliminary_only`. The venue fallback needs `venue_settlement_tmax_f`, which this source can never supply (O3), so the trial stays refused
  indefinitely and loudly -- never silently scored, never silently dropped.
- *Scorer runs twice.* `_already_fallback_scored`/`_unchanged_since_last_score` (:376-399) skip an unchanged settlement; `_append_fill_order_entries` de-dupes on `(trial_id, score_seq)`;
  `_write_or_assert_live_provenance_sidecar` asserts, never rewrites. A real CORRECTION appends `score_seq + 1`.

## 2. Null-hypothesis verdicts (L-1; installed nautilus_trader 1.231.0)

- **Native `CacheDatabase`/`MessageBus` persistence -- RULED OUT.** `Cache.add*` forwards to a database only `if self._database is not None` (`cache/cache.pyx:1704-1708`); the kernel accepts one backing store, `"redis"` else `raise
  ValueError` (`system/kernel.py:310-329`). Breezy sets `CacheConfig(database=None)` for every node role (`runtime/node_config.py:217,499,759`) and deploys no Redis -> memory only, answers nothing after exit. Same verdict
  `fill_time_count.py:11-23` pins.
- **Native `ExecutionEngine` reconciliation -- REAL, fed nothing.** It reconciles from `generate_order_status_reports` (`live/execution_engine.py:1557`) and `generate_fill_reports` (:1191); Breezy returns `[]` from both
  (`exec/client.py:987-1013`). By-id `generate_order_status_report` (:938-985) and `generate_position_status_reports` (:1015-1055) are REAL -- the latter maps live venue positions, which is why deferring I4 loses no exposure
  visibility.
- **Native `Strategy.on_order_filled` -- REAL, deliberately NOT used.** `trading/strategy.pyx:723`, dispatched :1971. Fires AFTER publication, in the strategy process: it cannot satisfy goal (1) and cannot be read offline.
  **Verdict: the durable write belongs in the exec client (I1b); no strategy hook.**
- **Native order FSM -- SUBMITTED must precede FILLED (justifies I1b's unconditional `_generate_submitted`).** `_ORDER_STATE_TABLE` (`model/orders/base.pyx:94-157`) has NO `(INITIALIZED, FILLED)` entry; FILLED is reachable only from
  SUBMITTED/ACCEPTED/CANCELED/PENDING_UPDATE/PENDING_CANCEL/TRIGGERED/PARTIALLY_FILLED (:116,124,126,136,143,150,156), and an illegal trigger raises `InvalidStateTrigger` (`core/fsm.pyx:127`, via `Order.apply` :1029). Skipping
  `OrderSubmitted` on the failure path would make the `OrderFilled` unbookable -- the exact outcome that path exists to prevent.

## 3. Increments, in build order

### 3.0 -- Stage-0 shared contracts (frozen before the fan-out)
I2 and I3 are built in parallel, so these four surfaces are frozen HERE and neither increment may redefine them:
- **(a) Scorer CLI.** `--fill-source <path>` XOR `--fills <jsonl>` (exactly-one-of; `--fill-source` may also be OMITTED -- R8), plus `--city <CITY>`, ONE city per invocation, plus `--since-climate-day <YYYY-MM-DD>` = the family's `d0_climate_day` read by the wrapper from the registered v2 manifest -- the SAME string it passes to the v1 stop's `--fill-since-climate-day` and `--fetch-start` (strategy-lead Q4, `docs/evidence/grok_admission_exclusions_ack_2026-09-05.md`: "Scorer `since_climate_day=d0` so pre-D0 live rows are never written"); three consumers, one string. An unreadable/absent fill source -> **non-zero exit, NO marker** (A5).
- **(b) Success marker.** `score_live_trials_ok_$STAMP`, `STAMP=$(date -u +%Y-%m-%d)` -- the stamp both shipped wrappers already compute (`live-tally-run.sh:22`, `family-tally-v2-run.sh:70`) -- under `$BREEZY_LIVE_TALLY_OUTPUT_DIR` (default `$HOME/.local/share/breezy/derived`, `live-tally-run.sh:13`). Written by the I3 wrapper ONLY after EVERY city succeeded: a per-city write would let a partial run satisfy both tallies.
- **(c) Excluded-fills line: exactly 8 keys** -- `trial_id, station, climate_day, venue_order_id, qty, reason, filled_at_ns, scored_run_utc`; idempotent on `(venue_order_id, reason)`.
- **(d) Record JSON names:** `cumulativeFee` / `feeReconciled` (I1a/I1b), consumed BY NAME in I2's reader and I5's fixture.
**I3 does not depend on I2 being built:** its wrapper tests stub the scorer with a shell `python` (the shipped `BREEZY_FAMILY_TALLY_V2_PYTHON` idiom, `tests/unit/test_family_tally_v2_deploy.py:41-47,95-99,127-133`), so argv, marker and failure propagation are pinned against a stub, never a real scorer.

### I1a -- order-level totals on the classified outcome (REQUIRED; `exec/submit_chain.py` only)
- **Which struct: `CreateOrderOutcome` (:118-128), NOT `FillGeneration` (:104-116).** `FillGeneration` is documented as "Native arguments for `generate_order_filled`" and its fields map 1:1 onto
  the native call (`client.py:1597-1612`); order-level totals are not native call arguments. `CreateOrderOutcome` already carries the order-level `venue_order_id` and `filled_cost_usd`, so the
  remaining totals belong beside them. New fields: `cumulative_qty: Decimal | None`, `cumulative_cost: Decimal | None`, `cumulative_fee: Decimal | None`, `fee_reconciled: bool`.
- **Qty and cost are sourced TOGETHER, from the order object, or together from one leg -- never mixed.** `cumulative_qty` is `_cum_quantity(payload)` (:347-364, already reading `cumQuantity` off
  `payload` or `payload["order"]`); `cumulative_cost` is `avgPx * cumQuantity` -- exactly the preference `_filled_cost_from_execution` (:383-402) already applies. If the order object lacks
  `avgPx`/`cumQuantity`, BOTH fall back to the same single execution's `lastShares` / `lastPx*lastShares` pair. Pairing a one-leg qty with a whole-order cost (or the reverse) is the defect this
  rule forbids.
- **Fee, fill-type legs only.** Filter `executions` to `type in {EXECUTION_TYPE_FILL, EXECUTION_TYPE_PARTIAL_FILL}` (`sdk_snapshot/polymarket_us_0.1.2/types/orders.py:34-43`, verified).
  `cumulative_fee` = order-level `commissionNotionalTotalCollected` when present (`types/orders.py:90`; OpenAPI snapshot `docs_snapshots/api-reference_orders_create-order_2026-08-25.md:333-335`,
  "Total notional value of all commissions collected on this order"), else the sum of per-leg fill-type `commissionNotionalCollected` (`types/orders.py:108`; OpenAPI :270-272, "in this
  execution"). A CANCELED/REJECTED/EXPIRED/NEW/REPLACE/DONE_FOR_DAY row carrying a commission is never summed.
- **`fee_reconciled`** = (sum of fill-type `lastShares` == `cumQuantity`) AND (order total absent, OR order total == the per-leg fill-type sum). The quantity identity alone detects a
  missing fill leg (a dropped leg makes the sum fall short of `cumQuantity`), so the absent-total branch needs no extra single-leg condition -- round-3 domain review: a q=1 order filled as
  0.5 + 0.5 with no echoed total is correctly costed and must be scored, not routed to `fee_unverified` (silent power loss). `Execution` is `total=False` (`types/orders.py:95-108`), so a leg with NO `type` is not fill-type: it fails the qty identity and lands `fee_reconciled=False`. Fail closed,
  never guess. `client.py` consumes these fields and never re-parses `response.body`. `_durable_execution` (:361-383) is NOT changed -- the leg chosen for `FillGeneration` keeps its selection
  rule; I1a only adds order-level totals alongside it.
- **RED tests** (existing `tests/unit/test_polymarket_us_submit_order_chain.py`): multi-leg fixture asserts qty AND cost AND fee are ORDER-level; non-fill rows carrying a commission are ignored;
  order total != leg sum -> `fee_reconciled=False`; two fill-type legs 0.5 + 0.5, no order total -> reconciled with `cumulative_fee` = the leg sum; a leg with no `type` -> not reconciled.
- **Barriers.** `submit_chain.py` is already inside `exec/` and its test module is ALREADY in X1's exact set (`test_execution_egress_firewall_guard.py: 2673-2689`), so **X1 widening for I1a is
  zero**. E0-TRANSPORT: the module stays pure (no I/O, no import beyond the already-imported `Decimal` :19). B6/B9 (`test_polymarket_us_readonly_guard.py`): no new write verb, host literal or SDK
  import.

### I1b -- call `record_fill` FIRST in the `KIND_ACCEPT_FILL` branch (REQUIRED; `exec/client.py` only)
- **Primary justification is not scoring -- the client self-denies without it.** `_map_position` (:1089) -> `_entry_price` (:1183) -> `_entry_price_from_records` (:1217): with no durable record
  for an instrument the venue still reports, `_refuse` fires (:1231-1236), and the venue-cost-basis fallback refuses too (:1200-1213); a latched refusal denies every later submit (`_submit_order`
  :1515-1517). **Verified: today, one fill followed by ANY restart before that market expires makes the client refuse to trade for the rest of the run.**
- **Interface -- exactly TWO new fields on `DurableFillRecord` (:386-419):** `cumulative_fee: Decimal` (JSON `cumulativeFee`, string) and `fee_reconciled: bool` (JSON `feeReconciled`), both taken
  from I1a's outcome -- honest by construction, never re-derived from a fee schedule (A13). No station/climate_day/entry_ask: those are durable in the latch record and recovered by joining on
  `instrument_id` (`fill_time_count.py:51-58,129-158` already ships and tests that join); copying them here would put strategy vocabulary in the venue layer and create a second truth for
  `entry_ask`. Read-time: `fill_px = cumulative_cost/cumulative_qty`, `fee = cumulative_fee/cumulative_qty` (per contract, v1 §4), `qty = cumulative_qty`, `filled_at_ns = ts_event`.
- **Exact control flow (the branch at :1585-1613, which has NO try/except today):**
  ```
  try:
      self.record_fill(record)                     # FIRST statement of the branch
  except Exception as exc:                         # noqa: BLE001 -- deliberately broad, see below
      self._log.error(f"{_FILL_WRITE_FAILED}: {type(exc).__name__}: {exc}; record={record.to_bytes().decode()}")
      self._refuse(_FILL_WRITE_FAILED)             # ONE fixed module-level reason string
  else:
      self._ledger.true_up_booking(booking, filled_cost_usd=outcome.filled_cost_usd, now_ns=now_ns)
      self._retire(intent.intent_id, retire_name, now_ns)
  self._generate_submitted(order, now_ns)          # UNCONDITIONAL
  self.generate_order_filled(...)                  # UNCONDITIONAL
  return
  ```
- **Why `except Exception` is deliberately broad:** it guards ONE evidence write, and ANY failure of it must halt trading rather than lose the event. Known raisers: `PolymarketUSError` from an
  unreadable index (:1331-1336), `sqlite3.Error` surfaced by `_store_set` (:1392), encode/serialize errors from `to_bytes` (:421-433). Narrowing to those three would let an unlisted exception
  escape into the `LiveExecutionClient` task handler, which swallows it (`exec_fault.py`) -- silently losing both the record and the refusal. Nothing is re-raised out of the branch and the event
  is never suppressed.
- **One fixed reason string, not a formatted message:** `_refuse` dedupes on the reason (:1759-1760), so a per-exception message would defeat the latch and re-`degrade()` on every occurrence. The
  exception detail goes in the ERROR log line, not in the reason.
- **On `fee_reconciled == False`:** the record is STILL written, `_refuse(_FEE_UNRECONCILED)` (second fixed reason) latches, and retire/publish proceed. The fill is real; only the fee is
  untrusted -- I2 keeps it out of scoring.
- **No alert import inside `exec/`:** `breezy.runtime.health` is forbidden there by barrier E0-TRANSPORT (`test_execution_egress_firewall_guard.py:1737,2341, 2353`; `client.py:1725-1727`); the
  `_refuse` -> `degrade()` -> `component_health_watch` -> `emit_alert` path already emits the CRITICAL alert exactly once. **Also in this file:** fix the stale `generate_order_status_reports`
  docstring (:987-999, "Breezy has also submitted no order").
- **Decode compatibility.** `from_bytes` requires every field (:435-481). Safe by construction: `record_fill` has ZERO production callers today, so no on-disk record exists. Measured
  (coordinator, read-only `mode=ro`, 2026-09-05 ~00:55 UTC, live exec store `state` table): 4 rows -- 3 `current_rung_hold/trial/*` latches, 1 `durability:probe`, **0
  `exec/polymarket_us/fill/%`**. Runbook: a one-line read-only pre-deploy re-check of that count, not code.
- **RED tests** (extend `tests/unit/test_polymarket_us_exec_client.py`): (a) ordering probe -- store write BEFORE `true_up_booking`/`_retire`/`OrderFilled`; (b) record decodes with fee + flag;
  (c) **failure path -- `record_fill` raises, no record, intent OPEN, refusal latched, component degraded, `OrderSubmitted` AND `OrderFilled` STILL published, nothing escapes**; (d)
  `fee_reconciled=False` -> record written, refusal latched, publish proceeds; (e) zero-fill and reject write no record; (f) `to_bytes`/`from_bytes` round-trip. Fixtures are stated schema-shaped
  from the SDK/OpenAPI snapshots -- NOT a recorded response.
- **Barriers.** `DurableFillRecord(` is constructed in FOUR test modules -- the COMPLETE set, verified 2026-09-05 -- and every one must gain the two new fields:
  `tests/contract/test_exec_client_reconciliation_contract.py` (:623, :728), `tests/unit/test_polymarket_us_exec_client.py` (:319, :1483), `tests/unit/test_fill_time_count.py` (:66),
  `tests/unit/test_live_family_tally_fill_source_cli.py` (:64). Both client test modules are already in X1's set, so no widening here either. Verify B6/B9 in
  `test_polymarket_us_readonly_guard.py` (intra-module call, no new import or chokepoint site).

### I2 -- state-DB fill reader in `score_live_trials.py` (REQUIRED)
- **File:** `scripts/analysis/score_live_trials.py`: add `read_filled_trials_state_db` + `--fill-source`; the JSONL reader is **augmented, not deleted** (`--fills` stays for fixtures/replay) and exactly one of the two is required.
  **Interface:** `read_filled_trials_state_db(path, *, family_prefix, city, cli_location, since_climate_day) -> tuple[tuple[FilledTrial, ...], tuple[ScoreRefusal, ...], tuple[FillExclusion, ...], Mapping[str, bool]]` -- the last
  member is `trial_id -> fee_reconciled`. It **imports `_open_readonly` from `fill_time_count.py:84-98`** (or that helper is promoted to a shared module both import) -- never a second read-only-connect implementation. No flock; safe
  while the node runs. **`None` from `_open_readonly` -> exit NON-ZERO, no marker** (A5).
- **station != city.** The latch key segment is the registry city key (`strategy.py:166-171`); the catalog needs the CLI location (`catalog.py:642-647`). I2 filters fills to the run's city and emits `registry.settlement_site(venue,
  city).cli_location` as `FilledTrial.station` (`registry/sites.py:371`, field :113). Verified: for all five PM.us sites the two strings are IDENTICAL today (`sites.toml:117-306`) -- the mandated accessor and the Kalshi-portable
  one.
- **Join:** map `instrument_id -> (station, climate_day, ask)` from every `family_prefix` latch with `reason == "taken"`, then look up each `FILL_KEY_PREFIX` record. No taken latch, an instrument mapping to >1 latch, or **>1 fill
  record joining ONE latch** -> refuse `malformed_input` naming both venue_order_ids. That last is not hypothetical: `_next_score_seq` is evaluated per row inside the generator at `score_live_trials.py:496`, before
  `write_scored_trials`, so two rows for one `trial_id` take the SAME `score_seq` and double-count n. Fail closed, never guess.
- **Exclusion layering -- BOTH sources guarded by ONE gate (A6).** `fill_below_ask` and `fee_unverified` join `partial_fill`/`multi_fill` inside `_admit_fill` (:238-252), whose signature becomes `_admit_fill(trial, *,
  fee_reconciled: bool = True, tick: Decimal = _TICK)`. The keyword-with-default is forced by an invariant: `FilledTrial` (`trial_scorer.py:70-115`) is v1-BINDING in the AST-pure `settlement` package and gains NO field, so the flag
  arrives as a parameter; the JSONL fixture path (no venue fee attestation) keeps today's behaviour by defaulting to `True`. `FillExclusion`/`FillExclusionReason` are **driver-local** (:202-220), so widening that closed set old ->
  new (`{"partial_fill","multi_fill"}` -> `+ {"fill_below_ask","fee_unverified"}`) touches no v1 module.
- **Re-admission of a `fee_unverified` fill (strategy-lead Q2, `grok_admission_exclusions_ack_2026-09-05.md`):** only via a venue-sourced `record_fill` cumulative UPDATE for the same
  `venue_order_id` that independently satisfies both fee identities; the scorer and the operator never patch `feeReconciled`. **No such update path exists today** (`record_fill`
  writes once per `venue_order_id`) -- I4 territory, NOT built here; until then the fill stays excluded and visible in the artefact and the coverage table.
- **Post-registration amendment disclosure (R6).** Widening that closed set AFTER PREREG v1 was registered carries the SAME non-retroactivity argument as the D0 pin: **zero fills exist** (measured, 0 `exec/polymarket_us/fill/%`
  rows), so no already-admitted trial is reclassified; and both new reasons are DEFECT signatures (L-25 fill-below-ask) or fee-attestation failures -- properties of the EXECUTION, never of the outcome -- i.e. the same class ruling
  Q1 already registered for `partial_fill`/`multi_fill` (`docs/evidence/grok_v2_registration_ack_2026-09-05.md` C3: excluded BEFORE `score_trial`, `dn = dk = dI = dS = 0`), and every exclusion is reported in the I3c coverage table
  rather than dropped. **Disclosed to the strategy lead for acknowledgement** before the family's first fill -- the same disclosure route the fill-order sidecar took (PREREG v2 §13:277-281).
- **State-DB path resolution (R8).** `--fill-source` is OPTIONAL. When omitted the scorer resolves the live exec state-DB path with the NODE's OWN resolver, `resolve_store_path(os.environ)` -- **verified at
  `runtime/trade_supervisor.py:929-933`** (NOT `submit_intent.py`/`node_config.py`, where round 3 guessed it), the same function the supervisor's `main` uses at :979 -- and fails loudly if the result is not a file (the resolver
  itself raises `ExecStateDbNotConfiguredError` when its env var is unset). ONE truth for the path; the value is a non-secret filesystem path, never echoed into an artefact; the I3 unit passes no path and forwards no credential env.
- **Fill-vs-ask guard (L-25).** `fill_px < entry_ask - tick` is a defect signature. `tick` is the venue's `orderPriceMinTickSize` -> `Instrument.price_increment` (`parsing.py:1274,1330`); UNVERIFIED that any artefact this offline
  reader opens carries it, so the builder declares one module constant `Decimal("0.01")` citing the evidence DIRECTORY `docs/evidence/venue/polymarket_us/`, where all 23 files naming `orderPriceMinTickSize` carry `0.01` in every
  observed market payload (the `0.005` in the API doc is an illustrative example, never an observed PM.us value). **The one-tick tolerance deliberately differs from paper replay's ZERO tolerance** (`paper_replay.py:131-143`,
  `ImpossibleFillPriceError`): replay crosses the SAME book the decision priced, where improvement is impossible, whereas a LIVE IOC can legitimately improve between decision and execution.
- **`scheduled_release_at_ns`:** derive from the registry settlement clock, not midnight UTC -- midnight UTC of `climate_day+1` precedes the venue's 08:00 America/New_York close by up to 8h (LAX/SFO).
  `registry.settlement_deadline(venue, city)` (`sites.py:416-421`) carries `settlement_time_local`/ `settlement_timezone` (:170-171) and `nws_actor._settlement_deadline_ns` (:2148-2153) already computes `climate_day+1` at that
  wall-clock in that zone; it is PRIVATE, so promote its five-line body to one shared pure helper both call, never a second copy. **NOTE:** that deadline is the VENUE's DST-following civil deadline (`sites.py:419-420`), used here as
  a PROXY for the NWS release clock the field name denotes. It is inert in v1 -- it gates only the >= +7d venue fallback, unreachable from this source (O3) -- so the proxy costs nothing today, but a real NWS release clock is
  required before that fallback is enabled.
- **Excluded-fills artefact.** `<store_dir>/excluded_fills.jsonl`, append-only, one JSON object per exclusion with keys `trial_id, station, climate_day, venue_order_id, qty, reason, filled_at_ns, scored_run_utc`; idempotent on
  `(venue_order_id, reason)`; credential-free by construction. **ONE write site**, after `score_live_trials()` returns, unioning the reader's refusals/exclusions with `_admit_fill`'s -- never two appenders. Idempotence otherwise
  unchanged: the three existing guards key on `(trial_id, revision_seq/raw_sha256, score_seq)`.
- **RED tests** (new `tests/unit/test_score_live_trials_state_db_source.py`): seeded DB yields one `FilledTrial` with the latch's `entry_ask`, the record's per-contract fee and the CLI-location station; no taken latch refuses; TWO
  fill records on one latch refuse `malformed_input` naming both ids; q=0.37, `fill_below_ask` and `fee_unverified` excluded and appended; artefact idempotent across runs; two runs write one scored row; a `paper_replay/` latch key
  never matches; an open writer does not block the read; **an unreadable/absent DB exits non-zero and writes no marker**.

### I3 -- scheduling and the two stop denominators (REQUIRED)
- **ONE scoring unit at 14:15 UTC**, not a step inside each wrapper: `deploy/systemd/breezy-score-live-trials.{service,timer}` + `score-live-trials-run.sh`. 14:15 is free (occupied: 09:00, 13:30, 14:30, 15:30, 22:30, 22:45,
  00/06/12/18:15). **Why:** (a) single writer -- a step in both wrappers can run concurrently if 14:30 is retried while 15:30 starts, and idempotence protects content, not concurrent appends; (b) repo convention is one unit per job;
  (c) the excluded-fills artefact gets an owner. Build-completion criterion: no `EnvironmentFile=`, no venue-credential env (same posture as `breezy-live-tally.service`), outputs carrying only
  trial_id/station/climate_day/venue_order_id/qty/reason. Give the unit an explicit `TimeoutStartSec` -- the station-day counter below calls `load_depth` per station-day and grows with the archive.
- **Ordering: a dated success marker, not `After=`.** `After=` does not order units started by SEPARATE timers, so the Rev 1 proposal was inert. The scorer writes `score_live_trials_ok_$STAMP` under the shared
  `BREEZY_LIVE_TALLY_OUTPUT_DIR`; BOTH tally wrappers assert today's marker and exit non-zero with a value-free log line otherwise. `OnSuccess=` rejected: it makes the scorer START the tallies, replacing two independently retryable
  timers with a chain whose cadence no longer reads off the timer files. **The wrapper loops over CITIES** -- `score_live_trials` takes one `--city` and opens one catalog (:419-420); other cities' fills would emit spurious
  `instrument_unavailable`. I2's city filter is the other half.
- **O1 inside I3 -- both stop flags, ONE window (A3).** `live-tally-run.sh` currently passes neither (:23-26). The literal invocation it must make -- **all three flags VERIFIED pre-existing** on `live_family_tally.py:454-471`, so
  this is a wrapper change only:
  ```
  live_family_tally.py "$STORE_DIR" --output "$OUT/live_family_tally_$STAMP.md" --as-of "$STAMP" \
      --fill-source "$STATE_DB" --fill-since-climate-day "$D0" --covered-listed-station-days "$COUNT"
  ```
  Without them `filled_takes=None` or a `None` denominator leaves the stop unevaluated (`structural_dead_stop.py:95-116`). The count comes from the shipped
  `count_covered_listed_station_days_from_catalog` (:165-195) -- **but its `fetch_start` defaults to `ASOS_FETCH_START` = 2026-08-30 (`ma_prelock_winner_ask_study.py:184`)**, the pre-live
  ARCHIVE window: called unchanged it returns >= the floor 15 (`structural_dead_stop.py:73`) against ZERO live fills and fires `structural_dead` on the very first evaluation -- **a manufactured
  KILL.** Therefore:
  - the wrapper passes `fetch_start` = the family's D0 and **the SAME string** to `--fill-since-climate-day`; numerator and denominator share one window by construction;
  - `structural_dead_stop.py` gains `--fetch-start` (and `--fetch-end`) on `_parse_args` (:198-206, `--catalog-root` only today), defaults unchanged so the M_A study path is untouched, **and `main()` (:209-215) must FORWARD them**
    -- verified: `main` today passes ONLY `catalog_root`, so the flag alone would be INERT and the wrapper would silently keep the archive window. Adding a flag to an analysis script is not a v1-module change;
  - **the ONE source of that date: the REGISTERED v2 manifest `deploy/families/pm_us_crh_v2.json` (`:5`, `d0_climate_day = "2026-09-05"`, `status: "REGISTERED"`), read by the shipped strict loader `load_family_manifest`
    (`persistence/family_manifest.py:115-193`). NO `pm_us_crh_v1.json` is authored** -- three verified reasons: (i) the loader REQUIRES `boundary_artefact_path` + a 64-hex non-placeholder `boundary_inputs_sha256` (:53-64,163-172),
    and v1 is a Wilson rule with no group-sequential boundary artefact, so any value there would be FABRICATED provenance; (ii) any `deploy/families/*.json` whose `family_id` equals its stem becomes a VALID argument to the v2 tally
    wrapper (`family-tally-v2-run.sh:42-51,58-64`), silently offering a v1 id to a v2 boundary solver; (iii) a v1 manifest would be byte-identical to v2 in `(trial_id_prefix, d0_climate_day, stations)` -- exactly the pair
    `family_barrier.py:15-22` states the discriminant CANNOT separate. **Semantics, stated so no reader mistakes a v2 fact for a v1 one:** v2 §8:175 registers v2 as a NEW family whose membership test is `climate_day >= d0_utc_day`,
    pre-D0 fills being v1-only (:196-197); v1's earliest D0 is the SAME date (PREREG v1 §6:130, "earliest D0 = 2026-09-05") and there are ZERO fills to date, so the two row sets COINCIDE and that manifest is the only REGISTERED
    machine-readable pin of the date. The wrapper refuses (non-zero) if the manifest is absent, unreadable or not `REGISTERED`, and never falls back to `ASOS_FETCH_START`;
  - **`fetch_end` and day one (R3).** The denominator's upper bound defaults to `ASOS_FETCH_END = default_asos_fetch_end()` = `date.today()`, frozen at IMPORT time (`ma_prelock_winner_ask_study.py:168-185`); the numerator has no
    upper bound, so a fill on a day not yet counted only DELAYS a KILL -- conservative. **Inverted day-one range (`fetch_start > fetch_end`): verified from source** -- `discover_station_days`
    (`ma_prelock_winner_ask_study.py:547-560`) iterates `while day <= fetch_end`, so an inverted range never enters the loop and returns `()` -> count 0, no exception; it does call `depth_root.iterdir()` FIRST, so an absent depth
    root still raises and the wrapper guards that;
  - **the count is cached to a FILE, never a stdout scrape (R9).** `structural_dead_stop.py` gains `--output <path>` writing JSON `{"count": int, "fetch_start": str, "fetch_end": str, "stations": [...]}` under the shared output dir;
    the wrapper reads `count` from that file, so a retry does not re-walk the catalog and nothing parses the human print at :214;
  - the counter's caveat (:136-151) carries over -- an outage day is indistinguishable from a never-listed day, under-counting and DELAYING a KILL (conservative, never manufacturing one), which is only true once the window itself is
    right.
- **Tests:** extend `tests/unit/test_deploy_timer_hours.py` (14:15 owned by one timer); new wrapper test shaped like `test_family_tally_v2_deploy.py` (invalid/missing city fails loudly; failing python exits 1; artefacts under the
  shared output dir; missing marker => non-zero from BOTH tally wrappers). **RED tests:** (i) the date passed to `--fetch-start` is byte-identical to the one passed to `--fill-since-climate-day` AND equal to the v2 manifest's
  `d0_climate_day`; (ii) an absent/unregistered manifest exits non-zero; (iii) `main()` FORWARDS `--fetch-start` to the counter (a silent no-op fails); (iv) an inverted range counts 0 and does not raise; (v) **census identity
  `set(DENSE_STATIONS) == set(load_family_manifest(pm_us_crh_v2.json).stations)`**, so the denominator's census IS the family census (R2). Verified: NO test module references `live-tally-run.sh` today, so the v1 wrapper's assertions
  need a new module.

### I3c -- v2 coverage table reads the excluded-fills artefact (REQUIRED, small)
The v2 registration ack commits to a "coverage table" (`docs/evidence/grok_v2_registration_ack_2026-09-05.md:18`, C3) with `dn = dk = dI = dS = 0`. **Verified: `family_tally_v2.py` contains no
coverage-table implementation today**, so this consumer is new work, not a wiring change. It reads `<store>/excluded_fills.jsonl` and renders counts by reason/station/climate_day, changing no statistic and no v2
boundary; `live_family_tally.py` untouched (BINDING). **Count rule (strategy-lead Q2: "append-only jsonl is evidence, not the count"):** ONE entry per `venue_order_id`, the latest
line by `scored_run_utc` wins, and an exclusion whose `trial_id` has a scored row in the store (any `score_seq`) is DROPPED from the count -- a later attested trial leaves the
table automatically, nothing is edited. RED tests both sides: the artefact's shape; the table from a seeded artefact; two lines for one `venue_order_id` count once (latest reason);
an exclusion whose `trial_id` is scored is not counted.

### I5 -- end-to-end contract test (REQUIRED; was O6)
One test under `tests/contract/test_live_fill_scoring_chain_contract.py` driving the REAL submit chain with a schema-shaped 200 create-order fixture through `record_fill` -> state DB ->
`read_filled_trials_state_db` -> `score_trial` -> a scored row and a tally denominator; otherwise each increment is green in isolation and the chain is unproven. **X1 widening, old -> new:** the
exact set at `test_execution_egress_firewall_guard.py:2673-2689` gains `tests/contract/test_live_fill_scoring_chain_contract.py` and `tests/unit/test_score_live_trials_state_db_source.py` (the
latter only if it imports `DurableFillRecord` to seed the DB, which it should -- seeding from a hand-written JSON blob would test a second, drifting copy of the encoding). The comparison stays
`==`; widened, never relaxed (L-12).

### I4 -- real `generate_fill_reports` -- DEFERRED, not required for the goal
The synchronous IOC path (`submit_chain.py:478-493`) means every fill Breezy can have is in hand at `_submit_order`, and I1b captures it; the POSITION is already reported by the real
`generate_position_status_reports` (:1015-1055), so deferring costs no exposure visibility. Native reconciliation adds value only for a latch-armed-but-unretired order (the AMBIGUOUS walk), where
by-id `generate_order_status_report` (:938-985) is already the mechanism. Deferred with the exact-set B6/B9 analysis it needs.

## 4. Omission hunt -- what is missing and would block the goal

- **O1 [blocks the v1 stop]. `live-tally-run.sh` passes NEITHER stop flag** (:23-26). Fixed in I3, together with the window defect (A3) that would otherwise turn the fix into a false KILL.
- **O2. Nothing schedules `score_live_trials.py`** -- both tallies read a store no automated job writes; without I3, I1a+I1b+I2 are inert.
- **O3. The venue last-fair-price fallback is unreachable from this source.** The reader always yields `venue_settlement_tmax_f=None`, so `_resolve_settlement_basis` (`trial_scorer.py:211-242`) can never take that branch. Acceptable
  and honest (a permanently-refused trial is visible), but stated, not discovered later.
- **O4. No fee on `DurableFillRecord`.** Without I1a/I1b the scorer must re-derive the fee from the schedule -- a computed number wearing the grammar of a venue report (A13).
- **O5. Corrections accessor: a documented v1 property, not a defect.** `read_climate_day_including_corrections` warns "never call this from a settlement, reconciliation or retry path" (`catalog.py:633-635`) -- i.e. never replicate
  the venue's payout. PREREG v1 §4 (frozen, `docs/specs/PREREG_v1_current_rung_hold_2026-09-04.md:76-93`) deliberately measures NWS truth: FINAL print only, superseded refused, "a re-scored trial counts once, at max `score_seq`", so
  the driver's existing call (`score_live_trials.py:472-474`) IS the v1 rule. **Consequence:** on a corrected station-day the scored P&L may differ from the venue payout -- a blocker-register NOTE for operator reporting, no ruling
  and no code change.
- **O6 -- CLOSED, promoted to increment I5.**

## 5. Risks and operator-visible behaviour

- **[HIGH] Silent exclusion.** `main()` prints the excluded-fills table (`score_live_trials.py:554-560`) but `live-tally-run.sh` sends stdout to `/dev/null` (:26). I2's artefact plus I3c's table are the fix -- a partial fill absent
  from both the scored store and the log is an unrecorded real trade.
- **[HIGH] Fill without evidence.** If `record_fill` raises (unreadable index -> `PolymarketUSError`, `client.py:1331-1336`) the order has already filled at the venue. I1b's control flow handles it: refuse, degrade, intent stays
  OPEN, still publish BOTH events.
- **[HIGH] Manufactured KILL.** Passing `--covered-listed-station-days` computed over the default archive window would fire the v1 structural-dead stop on day one with zero live fills. Fixed in I3 (A3), pinned by a window-equality
  RED test.
- **[MED] New reachable state: record exists + intent OPEN.** A crash between the fill write and `_retire` leaves durable evidence and an armed intent. `probe_open_intent` (`trade_supervisor.py:297`) surfaces it pre-launch and the
  pinned `clear_submit_intent_cli` is the single clearing caller, so the cost is bounded at ONE trading day -- no double-submit, because a latched OPEN intent denies. The fill probe stays the constant-`False` stub
  (`client.py:695-698`): it is keyed by intent fingerprint, and `DurableFillRecord` carries no fingerprint, so making the probe real needs a NEW fingerprint index -- legitimately I4.
- **[MED] Census asymmetry, numerator vs denominator (R2).** The denominator counts only `DENSE_STATIONS` (`structural_dead_stop.py:168`; = registry cities minus contaminated ones, `cli_basis_setup_win_rate_study.py:126-128`), while
  the numerator `count_filled_takes` (`fill_time_count.py:101-158`) has NO station parameter and counts every taken trial under the prefix. **Direction: a fill outside the census can only DELAY a KILL, never manufacture one** -- it
  adds to the numerator and never to the denominator. No v1-adjacent code change; the I3 census-identity RED test pins the two sets equal. **Verified unreachable today:** the live composition builds one strategy per
  `SUPPORTED_STATIONS = ("LAX","MDW","MIA","SFO")` (`strategy/current_rung_hold/config.py:74-76`; `composition.py:220-229`, `stations=(station,)`) -- NYC/KNYC is excluded by construction, so the live node subscribes no station
  outside the census (the v2 ack records the same census, C2).
- **[NOTE] Different bounds, different sources (R3, N3).** The denominator's upper bound is `date.today()` at import (`ma_prelock_winner_ask_study.py:168-185`) while the numerator is unbounded above -- conservative in the same
  direction. The two counts also read DIFFERENT stores: the denominator the quote-tape Parquet catalog, the numerator the exec-state SQLite, so a recorder-outage day carrying a real fill is numerator-only -- again a delay, never a
  manufactured KILL.
- **[MED] Concurrent reader at 14:15.** The scorer reads the live node's state DB; read-only URI + no flock is the shipped idiom, REUSED from `fill_time_count._open_readonly`. Safe by WAL + `synchronous=FULL`
  (`runtime/sqlite_store.py:123-124`) and the latch has no prune path (`trial_day_latch.py:197-239`); the "open writer does not block the read" test stays.
- **[NOTE] `fill_px` is not an independent check.** `cumulative_cost/cumulative_qty` reconstructs the venue's own `avgPx` BY CONSTRUCTION (I1a sources cost as `avgPx*cumQuantity`). It is a faithful re-expression, never a second
  opinion on the venue's price.
- **[NOTE] Event loop.** `_store_set` is a synchronous WAL commit already performed twice in this coroutine (`_latch.arm` :1556, `_retire` :1594). I1b adds a third; no executor -- offloading would break the very ordering this
  increment exists to guarantee.
- **Unchanged invariants (honoured by this Rev 4):** `allow_short=False`; no new `ScoredTrial` column; `trial_scorer.score_trial`, `live_family_tally.py` SOURCE and the 17-column store untouched (PREREG v1 BINDING) -- only the v1
  WRAPPER `live-tally-run.sh` gains flags; no safety/settlement/contract test weakened or deleted, exact-set barriers widened old -> new only (L-12); no operator-reserved control (budget, per-position cap, enablement) set or read;
  NO-SEND execution-egress firewall untouched; no secret and no enablement value in any file this plan creates.

## 6. Rev 4 -- round-3 peer-review dispositions

| # | Round-3 finding | Disposition | Where |
|---|---|---|---|
| B1+B2+B3 | A `pm_us_crh_v1.json` manifest would fabricate provenance, become a valid v2-wrapper argument, and be inseparable from v2 | APPLIED, no v1 manifest anywhere: `load_family_manifest` (`family_manifest.py:115-193`) requires `boundary_artefact_path` + a non-placeholder 64-hex sha (:53-64,163-172), which a Wilson rule has none of; stem-matched `family_id` makes any `deploy/families/*.json` a valid v2 arg (`family-tally-v2-run.sh:42-51,58-64`); byte-identical `(prefix, d0, stations)` is the `family_barrier.py:15-22` failure mode. The v1 wrapper sources `d0_climate_day` from the REGISTERED v2 manifest (`pm_us_crh_v2.json:5` = 2026-09-05) via the shipped strict loader. **Deviation argued (report):** the plan does NOT claim v1/v2 are "one family" -- v2 §8:175,196-197 registers v2 as a NEW family; what is true and cited is that D0 coincides (PREREG v1 §6:130) and zero fills exist, so the row sets coincide and this is the only registered pin | I3 manifest sub-bullet; I3 RED (i)/(ii); §5 unchanged |
| R1 | `--fetch-start` inert unless `main()` forwards it | APPLIED: verified `main()` (:209-215) passes ONLY `catalog_root`; I3 names `main()` explicitly and adds the silent-no-op RED test | I3 second sub-bullet, I3 RED (iii) |
| R2 | Numerator/denominator census asymmetry | APPLIED as stated, no v1-adjacent code change: denominator `DENSE_STATIONS` (:168) vs `count_filled_takes` (`fill_time_count.py:101-158`, verified NO station parameter); direction stated (delays a KILL, never manufactures one); census-identity RED test added. **Verified unreachable today**: `SUPPORTED_STATIONS = ("LAX","MDW","MIA","SFO")` (`config.py:74-76`) and `composition.py:220-229` builds one strategy per station -- the live node never subscribes NYC | §5 [MED] census asymmetry; I3 RED (v) |
| R3 | `fetch_end` default and the inverted day-one range | APPLIED: `ASOS_FETCH_END = default_asos_fetch_end()` = `date.today()` frozen at import (`ma_prelock_winner_ask_study.py:168-185`), numerator unbounded -- conservative. **Inverted range verified from source, not deferred**: `discover_station_days` (:547-560) loops `while day <= fetch_end` -> returns `()`, count 0, no raise; `depth_root.iterdir()` at :551 still raises on an absent root, which the wrapper guards. RED test kept | I3 `fetch_end` sub-bullet, I3 RED (iv); §5 [NOTE] |
| R4 | Literal invocation | APPLIED verbatim as a fenced line; all three flags VERIFIED pre-existing (`live_family_tally.py:454-471`) | I3 O1 bullet |
| R5 | I1b blast radius + FSM citation | APPLIED, the only two I1b/§2 edits: all FOUR `DurableFillRecord(` modules listed with line numbers (contract :623,:728; exec-client :319,:1483; fill-time-count :66; tally-CLI :64 -- verified complete); `_ORDER_STATE_TABLE` corrected to `base.pyx:94-157` with the FILLED rows at :116,124,126,136,143,150,156 | I1b Barriers bullet; §2 FSM verdict |
| R6 | Post-registration amendment disclosure | APPLIED beside the exclusion bullet: zero fills measured, both reasons are execution-property DEFECT/attestation signatures in ruling Q1's class (ack C3, `dn = dk = dI = dS = 0`), reported in the coverage table, disclosed to the strategy lead for acknowledgement | I2 "Post-registration amendment disclosure" |
| R7 | Stage-0 shared contracts | APPLIED as a new section: (a) CLI exactly-one-of + `--city` + non-zero/no-marker; (b) marker `score_live_trials_ok_$STAMP`, `date -u +%Y-%m-%d`, wrapper-written after ALL cities; (c) the 8-key line + `(venue_order_id, reason)` idempotence; (d) `cumulativeFee`/`feeReconciled`. I3 tests stub the scorer via the shipped `BREEZY_FAMILY_TALLY_V2_PYTHON` idiom, so I3 never waits on I2 | §3.0 |
| R8 | State-DB path resolution | APPLIED with a corrected citation: the resolver is `resolve_store_path` at **`runtime/trade_supervisor.py:929-933`** (used by its own `main` :979), NOT `submit_intent.py`/`node_config.py`. `--fill-source` OPTIONAL; omitted -> resolve there, fail loudly if not a file; wrapper passes no path, unit forwards no secret | I2 "State-DB path resolution"; §1 walk (5); §3.0 (a) |
| R9 | Count cache owner | APPLIED: `--output <path>` on `structural_dead_stop.py` writing `{count, fetch_start, fetch_end, stations}`; the wrapper reads the file, never the `:214` print | I3 count-cache sub-bullet |
| N3 | Denominator and numerator read different stores | APPLIED in one sentence: Parquet quote-tape catalog vs exec-state SQLite; a recorder-outage day with a fill is numerator-only (conservative) | §5 [NOTE] different bounds/sources |
| -- | Rev 3 body approved by the security and domain rounds | KEPT UNCHANGED, including the symmetric fee rule (I1a `fee_reconciled`: qty identity AND order-total agreement, 0.5+0.5 with no echoed total scored, not `fee_unverified`) and every Rev 3 disposition A1-A8; I1a and I1b are otherwise untouched by Rev 4 (a builder is implementing I1a against that text) | I1a, I1b, §1, §2, §4 |

**Build order:** **I1a -> I1b -> {I2 || I3 || I3c} -> I5.** I1b consumes I1a's fields; I2/I3/I3c are mutually independent once the record shape is fixed and may be built in parallel; I5 binds the
finished chain and is last.
