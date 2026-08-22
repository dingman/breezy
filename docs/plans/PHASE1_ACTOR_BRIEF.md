# Phase 1 — NWS Ingest Actor: Implementation Brief

**Status:** ready to implement. Supersedes nothing; extends `WEATHER_INGESTION_PROPOSAL.md` (v6) §5–§8 with the rulings from three adversarial reviews of the Actor blueprint (architect, python-reviewer, security-reviewer).

**Read this first, then the proposal.** Every ruling below was derived by executing against the installed NautilusTrader 1.231.0, not by reading its documentation. Where this brief and the docs disagree, the brief was tested. Do not re-litigate a ruling without re-running the experiment that produced it.

---

## 1. Scope

Build `src/breezy/ingest/nws_actor.py` and the supporting modules named below. One Actor instance per `(venue, city)`. Five instances in production.

**In scope:** timer-driven polling, conditional GET, structural allowlist → parse → record construction, catalog persistence with write verification, gate transitions on every outcome, publication, warm-start recovery, restart state.

**Out of scope for Phase 1:** Open-Meteo (Phase 3), METAR/ACIS advisory paths (Phase 2), the hash-chained provenance ledger (§4.5, still needs its null-hypothesis test), any trading logic.

**Already built and not to be modified by the implementer:** `normalize/` (pure), `registry/sites.py`, `domain/`, `ingest/http.py`, `ingest/gate.py`, `persistence/catalog.py`. Consume their public APIs. If one of them is genuinely wrong, report it rather than working around it — a workaround in the Actor for a defect in a leaf module is how the seam rot starts.

---

## 2. Framework findings — verified by execution

**F1 — `catalog.custom_data(...)` silently drops `metadata`.** It is used only on the `as_nautilus=True` branch and never forwarded to `query` (`catalog/base.py:202-218`). A warm-start response therefore publishes on the **metadata-less** topic `historical.data.NwsClimateDay*`, which a metadata-bearing subscription cannot match.

**F2 — `Actor.run_in_executor` discards the callable's return value in both modes.** It returns a `TaskId` — a plain UUID with no `add_done_callback` and no result channel. With no executor registered it runs inline and throws the value away just the same. It is fire-and-forget only, and **cannot** host a parse that must return a record.

**F3 — `DataEngine._query_catalog` breaks on the first registered catalog that returns rows.** With one catalog root per station, registering all N means stations 2..N silently warm-start from **station 1's records**. This is not a missing feature; it is confidently wrong data.

**F4 — `ingest/http.py` raises only for 3xx (except 304), 403, 429 and 5xx.** A 400 or 404 returns a normal `FetchResult` with `status_code` set. The Actor must branch on `status_code`; assuming "no exception means success" is a live defect.

---

## 3. Architecture rulings

### 3.1 The blocking work is catalog I/O, not the parse.

F2 killed `Actor.run_in_executor` as a host for the parse, and §2.5 removed the reason that host existed (pyIEM). The parse itself is microseconds and bounded — 128 KiB transport cap, structural allowlist ahead of every regex, a 250 ms fuzz ceiling against a measured worst case of 0.33 ms. **Parse inline. That part is settled and safe.**

Earlier versions of this brief named the fuzz ceiling as the load-bearing control for event-loop safety. **That was wrong, and it named the smaller risk.** The same `_poll` coroutine also performs, synchronously and inline:

- `os.open` + `fcntl.flock` on the station root;
- two pyarrow read-backs plus `catalog.write_data` inside `write_records`;
- at warm start, `read_climate_days(...)` over the **entire** station catalog, unbounded;
- `read_current_climate_day`, which the catalog module's own docstring says reads "the station's whole catalog into memory per lookup, with no bound".

That work is unbounded, **grows monotonically with retention**, and freezes the identical event loop — every venue heartbeat and every execution path in the process. The parse has a ceiling test; the thing that will actually stall the loop does not.

**Ruling: catalog I/O runs off the loop.** Use the stdlib `loop.run_in_executor(...)` with a real `ThreadPoolExecutor` — this is the asyncio loop method and is **unaffected by F2**, which is about `Actor.run_in_executor`. Keep the parse inline. Add a wall-clock ceiling test on the catalog path as well, and state the retention assumption it rests on.

### 3.2 Warm start### 3.2 Warm start reads the Actor's own catalog directly.

**Register zero catalogs with the `DataEngine`. Do not call `request_data`.** F1 and F3 both break it, and F3 breaks it *silently*.

Each Actor warm-starts by reading its own `ParquetDataCatalog` through the existing `persistence/catalog.read_climate_days(...)`, then republishes through the **same shared `DataType` factory** the live path uses. Consequence: `on_historical_data` is never called. Do not implement it as dead code.

### 3.3 Crash recovery — and the durability trap in `on_save`

The poll sequence persists, verifies, records success, then publishes. A crash in that window leaves a durably-written record no subscriber ever saw.

**`on_save` is the wrong home for the resume cursor, and this was measured.** `save_state`/`load_state` are **`NautilusKernelConfig`** fields, not `ActorConfig` fields, and `Trader.save()` is called **only** from `kernel.stop()` / `stop_async()`. On `SIGKILL`, OOM, or host loss, `on_save` never runs. A cursor kept there is frozen at the last *graceful* shutdown — possibly never written at all.

`Cache.add` is different: it is write-through per mutation. So:

**Persist the resume cursor through `Cache.add`, alongside the gate — not through `on_save`.** Warm start then republishes everything past it.

**The cursor is not a bare `ts_init`.** `NwsClimateDay` and `NwsRawProduct` from one fetch share `retrieved_at_ns`, and a poll that ingests a preliminary *and* a final after downtime may stamp them identically. With a strict `>` comparison, a crash after publishing the first and before the second loses the second **permanently** — precisely the loss this section exists to prevent. With `>=`, every warm start re-publishes the last record. Make the cursor `(ts_init, tie-breaker)` — the dedupe key or a monotonic per-Actor publish sequence — state the comparison operator explicitly, and pin the equal-`ts_init` interleaving in a test.

**The exit test must assert durability at the moment of the kill**, and fail if the cursor was never written. A test that kills and then observes over-publication passes whether or not the cursor was durable, which is passing for the wrong reason.

### 3.4 Dedupe by uuid; the integrity index is a tripwire behind it

Two distinct jobs were previously collapsed into one step, which made one of them unreachable.

**Job 1 — ordinary dedupe, and it is mandatory.** Nothing previously specified "I have already ingested this product; stop." Without it the discovery list returns the same id every poll, each re-fetch gets a fresh `retrieved_at_ns` and therefore a fresh `ts_init`, and the write **succeeds** — appending a duplicate `NwsRawProduct`, verbatim `raw_text` and all, every cycle. The catalog module explicitly budgets *~2 records per climate day* and reads the whole station catalog per lookup; unbounded duplicates invalidate that. The alternative branch is worse: an exact `ts_init`-range collision makes `write_records` report `skipped`, which §5 routes to `record_write_integrity_violation` — **CRIT, hard-block**. So an ungraceful crash right after a successful write would hard-block the site on the next poll.

**Dedupe at discovery, before the product fetch, keyed by `product_uuid`.** `ProductIntegrityIndex.known_digest(uuid)` already answers this: a non-`None` return means we have ingested it — skip the fetch entirely. This is cheap, requires no body, and is the step that prevents both failure modes above.

**Job 2 — the integrity tripwire.** `observe(uuid, sha256)` can only fire when we *do* fetch a uuid we have seen, which after Job 1 means a deliberate re-fetch: backfill, replay repair, or a future revalidation policy. Given NWS assigns a fresh uuid to every re-issue and `/products/{id}` bodies are immutable by id, **this tripwire should never fire in steady state.** That is the point. It is a cheap invariant guard on an assumption we do not control, and its value is precisely that it costs nothing until the assumption breaks. Document it as such so nobody deletes it as dead code — and do **not** infer from "it should never fire" that it can be skipped.

Distinguish in the gate routing between *skipped because already ingested* (routine, not an alarm) and *skipped because the catalog silently discarded a write* (integrity violation). These are the same `WriteOutcome` shape and must not be the same verdict.

### 3.5 Split the record builder.### 3.5 Split the record builder.

Do not write one `record_builder` returning both types. Write `build_raw_product(...)` and `build_climate_day(...)`. They have different inputs, different failure modes, and only the second can fail on parse — a combined function forces every caller through a union return it does not want.

### 3.6 A fifth module owns process-wide shared state

Two mechanisms require state no single Actor can own, and neither had a home.

- **`cross_site_burst_detected`.** One Actor owns one `(venue, city)` and cannot see the other four. A burst of 403s *across cities* is the evidence, so something process-scoped must aggregate it.
- **The `SettlementGate` instance itself.** `_load_global` caches the global entry on first read. If each Actor constructs its own gate over a shared store, Actor A latching `ua_trap_blocked` leaves B–E serving a stale cached global — so the UA trap fails to block the other four sites, which is the entire reason the latch is global. (The gate is being fixed to read the global through on every access; the shared-instance rule stands regardless, because two mechanisms guarding one invariant is correct here.)

Name a module that owns: the single `SettlementGate`, the single `StateStore`, the cross-site 403 window, and the `ProductIntegrityIndex`. Make "all five Actors hold the same gate object" an **asserted startup invariant**, not a convention — a convention that is silent when violated is not a safeguard.

---

## 4. Async and typing rulings

### 4.1 `on_timer` is sync; the poll is async — but VERIFY THE THREAD FIRST

`run_in_executor` cannot be used (F2) and the timer callback is unconditionally sync. The intended bridge is `asyncio.create_task(self._poll(...))` from the timer callback, with `add_done_callback` attached to that real `asyncio.Task`. That callback is the supervision path: an unhandled exception in `_poll` must transition the gate to BLOCKED with a CRIT log, because a poll task that dies silently is a gate left OPEN over stale data.

**This is the one ruling in this brief with no execution behind it, and two independent reviewers flagged it.** `LiveClock` timers are driven from **Rust**, and the callback re-enters Python through a pyo3 conversion wrapper. If it lands on a tokio thread rather than the asyncio loop thread, `asyncio.create_task` raises `RuntimeError: no running event loop` and the entire supervision story never exists. `TestClock` fires inline on the caller's thread, so a backtest proves nothing about this.

**Measure it before building on it.** Assert `threading.get_ident()` inside a live timer callback against the loop thread. If they differ, the primitive is `asyncio.run_coroutine_threadsafe(coro, loop)` and the loop reference must be plumbed explicitly — base `Actor` exposes none, so say where it comes from. Do not proceed on the assumption; this determines whether polling works at all.

This path is **live-only**. Guard it so a backtest never schedules a real fetch.

### 4.2 mypy strict### 4.2 mypy strict

`NwsActor(Actor)` subclasses a compiled Cython class that erases to `Any`, so `mypy --strict` fails on the subclass. Add an override scoped to **exactly** `module = ["breezy.ingest.nws_actor"]` — not a package-wide waiver, and not a global one.

Import `ActorConfig` from `nautilus_trader.common.config` (a typed `.py`), **not** from `nautilus_trader.common.actor` (compiled — erases to `Any` and silently defeats config typing).

### 4.3 `FetchResult` — one rule in two clauses

```python
text: str | None            # document: present iff status != 304
sha256: str | None          # document: present iff status != 304
status_code: int
headers: httpx.Headers
url: str
retrieved_at_ns: int        # event: ALWAYS present, unconditional
retry_after: str | None = None
```

`__post_init__` states **one rule in two clauses**: the *instant* clause is unconditional and does not branch on status; the *document* clause is the `!= 304` iff. A `FetchResult` describes an **exchange**, which always happened at a time, and carried a **document** only when the status says a body was sent.

**A 304 carries a timestamp.** This is load-bearing, not tidiness: a 304 routes as a freshness-satisfied success, and the gate's `last_successful_poll_ns` watchdog measures liveness in nanoseconds — a stampless 304 would force the caller to re-stamp from its own clock, reintroducing a second source of truth on exactly the status where the staleness alarm most depends on it.

`retrieved_at_ns` is named identically to the domain field it becomes (`NwsRawProduct.retrieved_at_ns` → `ts_init`), so the boundary is a straight assignment with no translation step to hide a bug in. Zero, negative and `bool` are rejected — "silently omitted" and "stamped 0" are the same defect, and `bool` is an `int` subclass that would otherwise sail through as 1 ns.

**Constructor and fetch:**
```python
HttpTransport(*, allowed_hosts: frozenset[str], clock: Callable[[], int], ...)
async def fetch(self, url: str, *, if_none_match: str | None = None,
                if_modified_since: str | None = None) -> FetchResult
```
The clock is **required**, matching `SettlementGate.__init__` — a defaulted module-level clock would be a second clock that can silently diverge from the one the freshness watchdog reads.

Conditional-GET validators are typed **values**, never a header dict, so nothing per-call can displace `User-Agent`/`Accept-Encoding`. They are charset- and length-checked before any socket opens; a malformed one raises `InvalidCacheValidatorError` (routed as an integrity alarm, §5).

Narrow `text`/`sha256` before use. A 304 must never flow into a provenance record — do not `assert` or `# type: ignore` past the invariant.


---

## 5. Error routing — every branch explicit

Build this as a table in code, not as a chain of `except` clauses appended over time. **Every `TransportError` subclass must have an explicit route or a proven deliberate propagation.** The security review found four unmapped; unmapped means "falls through to generic task-death supervision", which loses the distinction between a network hiccup and an integrity alarm.

| Condition | Route |
|---|---|
| `RedirectError` (3xx except 304) | integrity alarm — CRIT, hard-block |
| `ContentEncodingError` | integrity alarm — CRIT, hard-block (digest would attest to decompressed bytes) |
| `DisallowedHostError` | integrity alarm — CRIT, hard-block. Reachable **only** via a config/URL-construction error: redirects are never followed, and `_validate_url` checks the URL string's host, never the resolved address, so DNS rebinding does not produce this |
| `OversizeBodyError` | `record_oversize_or_parse_timeout` — CRIT, hard-block. **Ruling:** use the dedicated recorder, not the generic transport alarm. Both derive BLOCKED+CRIT so safety is identical; the reason code is the operator's diagnostic at 07:30, and a gate that already has an exact recorder should not be told something vaguer |
| `ProxyEnvironmentError` | integrity alarm — CRIT, hard-block. Re-checked on **every** fetch, deliberately, so it can arise mid-session — not merely at startup |
| `DecodeError` | data-quality — block the site; the body is not a CLI product |
| `ForbiddenError` (403) | UA-trap detection path, per gate rules |
| `RateLimitedError` (429) | back off, honour `retry_after`, transient counter |
| `ServerError` (5xx) | transient counter |
| `TransportTimeoutError` | transient counter |
| 304 | no-op success — freshness satisfied, **no** record written, **no** digest recorded |
| 400 / 404 (no exception — F4) | data-quality; a 404 on a CLI location is a binding error, not a transient |
| Structural rejection — sibling-station PIL, CLM monthly (**not** our product) | routine: ignore the product, continue. **Never** a block |
| Malformed/hostile body shape (line count, line length, WMO heading) | data-quality — block the site |
| Parse failure (own station, structure passed) | `record_parser_failure` — CRIT |
| `ClassificationError` (`normalize/classify.py`) | `record_ambiguous_headline` — CRIT. Classification is the highest-consequence parsing rule in the system |
| Sanity-bound violation | `record_sanity_violation` — CRIT |
| Oversize body / parse-time ceiling breach | `record_oversize_or_parse_timeout` — CRIT (**not** the generic transport alarm; distinct reason code) |
| **bare `TransportError`** (base class, `http.py:357` — generic connection refused/reset/DNS) | transient counter |
| **any unrecognised type** | fail closed — integrity-grade block, never transient |
| `ConcurrentWriterError` (catalog) | block the site — one Actor per station by design, so a second writer is a deployment defect |
| `WriterLockError` (catalog: EROFS/ENOSPC/EACCES/EISDIR/ENOTDIR) | block the site — **not** transient; a full disk does not heal by retrying |
| `CatalogPathError` (catalog: ELOOP/EMLINK, symlink refusal) | integrity alarm — CRIT, hard-block; something is interposing on the settlement data path |
| `WriteOutcome` skipped or partial | `record_write_integrity_violation` — CRIT, hard-block |

**Dispatch on the exact type, never an `isinstance` chain.** Because the base class now has a transient route, an `isinstance`-ordered chain would make every future unrouted subclass silently inherit "transient" — an integrity-class error quietly retried as a network blip, with the enumeration test still passing because a route "exists" by inheritance. Look up `type(exc)` in the table; an exact-type miss fails closed. "I do not recognise this error" is not evidence that it is benign.

Add a contract test that **enumerates `TransportError.__subclasses__()`** and asserts each has an explicit route. Note the parametrization trap the reviewer hit: `RedirectError`, `RateLimitedError` and `ServerError` take required kwargs, so a naive `cls()` construction crashes. Use a per-class construction table, and have the test fail loudly when a *new* subclass is added without a route — that is the test's actual job.

---

## 5b. Consumed API surfaces — final as of this brief

These landed after the blueprint was written. Do not code against the blueprint's older shapes.

**`normalize.cli_parse.parse_cli_product(text, *, cli_location, body_header_regex)`** — `cli_location` is now **required**. It is the bare `NYC`/`SFO`/`MIA`/`MDW`/`LAX`, and the allowlist asserts the product's AWIPS PIL equals `CLI{cli_location}` *before any regex runs*. This is also the sibling-station guard: one WFO issues several cities' CLIs, and `CLIJFK` arriving on the NYC poll is now rejected structurally rather than parsed and caught downstream. Do **not** confuse `cli_location` with the `/products/types/CLI/locations/{loc}` path segment — they coincide in value but are different identifiers, and conflating them has already been a live defect in this project.

**`registry`** now exposes three separate accessors. Use the right one; they are distinct types specifically so this cannot be gotten wrong by autocomplete:
- `settlement_site(venue, city)` → identity only (`icao`, `cli_location`, `issuing_office`, `body_header_regex`, never-substitute lists). No clock fields.
- `climate_day_window(venue, city)` → `std_utc_offset_hours`. **Fixed standard-time offset, never DST.** Used for the climate-day window and nothing else.
- `settlement_deadline(venue, city)` → the DST-following venue clock (ET for all five cities, including the three that are not in ET).

**Gate recorders** — every poll outcome routes to exactly one:
`record_successful_poll`, `record_forbidden_403`, `record_transient_failure`, `record_parser_failure`, `record_sanity_violation`, `record_task_death`, `record_redirect_integrity_alarm`, `record_client_error_defect`, `record_write_integrity_violation`, `record_transport_integrity_alarm`, `record_final_overdue` / `record_final_received`, `check_freshness`.

Two of these need Actor-side work rather than a bare call:

- **`record_forbidden_403(...)` no longer takes `is_ua_trap`.** The gate classifies it itself from persisted global state (`any_site_ever_succeeded`, a durable cross-restart latch) **or** a caller-supplied `cross_site_burst_detected` signal. The Actor must therefore maintain cross-site 403 counting/timing and pass that signal — following the existing `final_window_elapsed` / `conflict_window_elapsed` precedent, where the gate owns the decision and the caller owns the clock. Get this wrong in the safe direction: an unnecessary global halt costs trading time, a missed UA trap costs us API access entirely.
- **`record_final_overdue(venue, city, climate_day, deadline_ns)`** is a *data-completeness* clock, not a liveness one, and it is keyed by `climate_day`. A successful poll deliberately does **not** clear it — only `record_final_received` for that **exact** climate day does. So the Actor needs a per-climate-day deadline timer distinct from its poll timer. A final for yesterday must not clear today's block.

**`GateStatus.reason` is the most recent transition *event*, not the current root cause.** A successful poll on a site still blocked by `ACIS_DISAGREEMENT` sets `reason=SUCCESSFUL_POLL` while `state` correctly stays `BLOCKED`. Branch on **`state`** — never on `reason` — for any control-flow decision. The derived `blocking_causes(venue, city) -> tuple[GateReason, ...]` accessor already exists and returns **all** active causes, most severe first. It is for logs and humans; it is not a trading-safety input.

**`ingest.product_index.ProductIntegrityIndex(store=, clock=)`** — constructor kwargs mirror the gate exactly, so the Actor passes the **same store object** to both; key namespaces (`productidx:` vs `gate:`) do not collide. `observe(product_uuid, raw_sha256) -> ProductIntegrityResult` with a three-way `outcome`:
- `FIRST_SEEN` — records the digest. **This is the only path that writes.**
- `MATCH` — ordinary re-poll. Not an alarm. Read-only.
- `MISMATCH` — CRIT integrity alarm. Read-only, so the first-seen digest is never overwritten *by mechanism*, not merely by policy.

Corrupt persisted state resolves to `MISMATCH` rather than a fourth enum member, so no caller can forget to branch on it; `first_seen_sha256 is None` distinguishes that case for logging. A `store.get` that **raises** (cache DB unreachable) deliberately **propagates** instead of becoming a `MISMATCH` — this is confirmed correct: it is still fail-closed, because no outcome is returned at all, the poll aborts into task supervision, and the site blocks. Folding it into `MISMATCH` would cry wolf on the most serious alarm we have and latch a sticky CRIT for a transient blip. Undecodable *bytes* are a different thing and do resolve to `MISMATCH`. Let it propagate; do not catch it to "helpfully" convert it.

The index is **deliberately unbounded** — one entry per product forever, ~600 KB/yr, ~6 MB/decade. Do not add eviction. Every eviction policy reintroduces the exact hole this module closes: a pruned uuid re-observed with mutated bytes reads as `FIRST_SEEN`.

**`ingest.routing`** — pure decision functions; imports neither `gate` nor `nautilus_trader`. `route_transport_error`, `route_fetch_result`, `route_parse_failure`, `route_write_outcome`, `route_catalog_error`, `route_unhandled_exception`, each returning a frozen `RouteDecision`.

`GateAction.value` is the **literal recorder name**, so the Actor dispatches `getattr(gate, decision.action.value)(venue, city, detail=decision.detail)`; a test asserts every value resolves to a real `SettlementGate` callable. Two flags must not be conflated:
- `action_is_deferred=True` (only on `FETCHED`) — do **not** call `record_successful_poll` yet. That is step 11, gated behind `WriteOutcome.is_complete`; `route_write_outcome` redeems it.
- `writes_record=False` on a 304 — no catalog record **and** no `product_uuid → raw_sha256` entry.

The **catalog write path raises six** exception types, not three: `ConcurrentWriterError`, `WriterLockError`, `CatalogPathError`, `NonMonotonicWriteError`, `CatalogWriteError`, `WriterLockFilesystemError`. All route to `record_write_integrity_violation`, CRIT, hard-block, with distinct `PollOutcome`s so diagnosis survives. They share no common root, so enumeration scans the module rather than `__subclasses__()`.

`TRANSPORT_CONTRACT_VIOLATION` is the **F4 drift detector**: a status `http.py` promises to raise on, arriving instead as a plain `FetchResult`, fails closed rather than being routed as an ordinary status.

**`persistence.catalog.write_records(...) -> WriteOutcome`** — check `is_complete`. A non-empty `skipped`, including the partial case, is an integrity violation.

---

## 6. Poll sequence — two stages, not one

The previous version of this section described **one** fetch yielding product text. The real poll is two stages, and the missing one is where `product_uuid` comes from — the identifier the dedupe and integrity steps key on. It also declared its ordering "non-negotiable" while omitting classification and sanity validation entirely. Both are fixed here.

**Step 0 — startup, once per station root, before any polling.**
`assert_writer_lock_filesystem_supported(probe_filesystem(station_catalog_path(base, venue, city)))` and `assert_cache_persistence_configured(...)`. Both are deployment preconditions that are unenforceable at runtime and silent when violated. Neither may be an import-time side effect.

`cache_persistence_config_from(kernel_config, cache_config, exec_engine_config)` now takes **three** config objects — the old single-`actor_config` signature read `save_state`/`load_state` off an object that never has them. There are **five** conditions, all required, because missing any one of the last two silently loses the global UA-trap latch across a restart while per-site state still fails safe:

1. `NautilusKernelConfig.save_state = True`
2. `NautilusKernelConfig.load_state = True`
3. `CacheConfig.database` set (not `None`)
4. `ExecEngineConfig.load_cache = True`
5. `CacheConfig.flush_on_start = False`

**All five Actors must share one `SettlementGate` instance** (§3.6). The gate now reads its global entry through to the store on every access rather than caching it, so a sibling instance can no longer serve a stale `ua_trap_blocked`; the shared-instance rule still stands, because two mechanisms guarding this invariant is correct.

**Step 1 — may we perform network I/O?**

> **This is NOT `require_open`, and getting it wrong bricks the system.** The settlement gate is a **use-time** gate, consumed by the settlement resolver. It is **not** a poll gate. It defaults to BLOCKED until a successful poll, and `record_successful_poll` is only reachable *from* a poll — so "a blocked site does not poll" deadlocks on first boot and never recovers. Every per-site block (`parser_failure`, `sanity_violation`, `transient_blocked`, `task_dead`, `write_integrity_violation`, `stale_blocked`, …) is cleared **only** by a successful poll, so the same rule turns one transient hiccup into a permanent outage requiring a database edit.

Check only what genuinely forbids network I/O: the **global** `ua_trap_blocked` latch, and an active backoff window. A narrow predicate — not `require_open`.

**Stage A — discovery.**

2. **Conditional GET** of `/products/types/CLI/locations/{loc}`, sending the stored `ETag`/`Last-Modified`.
   - **304 → terminal branch.** Not step 9. Call `record_successful_poll` directly (freshness is satisfied), persist the returned validators, publish nothing, touch no cursor. A 304 produces no `WriteOutcome`, so it must not pass through any step gated on `is_complete`.
3. Parse the JSON list under explicit **size and depth caps**. Extract candidate `product_uuid`s.
4. **Dedupe (§3.4).** Drop every uuid `known_digest(uuid)` already knows. This step is what prevents unbounded duplicate accumulation and the crash-induced CRIT hard-block. If nothing remains, record a successful poll and stop.
   - The list may yield **several** unfetched ids — after downtime, or a preliminary and a final since the last poll. Handle the batch explicitly, and note `write_records` requires **non-decreasing `ts_init`** within a batch.

**Stage B — per product.**

5. **Unconditional GET** of `/products/{id}`. Bodies are immutable by id, so never revalidate them.
6. **Structural allowlist**, run alone and ahead of the parser. A *not-our-product* rejection (sibling-station PIL, CLM monthly) is **routine**: skip that product and continue. It is not a block.
7. **Parse**, then **classify** (`classify_issuance`, `has_correction_evidence`), then **sanity-bound validation**. Three distinct failure modes with three distinct CRIT reason codes — see §5. Classification is the highest-consequence parsing rule in the system and does not get folded into "parse".
8. `observe(uuid, sha256)` — the integrity tripwire (§3.4). A `MISMATCH` is CRIT and hard-blocks.
9. **Persist** both records via `write_records`, **off the event loop** (§3.1).
10. **Verify the write.** A non-empty `skipped` is an integrity violation — distinguish it from "already ingested", which step 4 should have prevented from reaching here at all.
11. `record_successful_poll(...)`, gated behind `WriteOutcome.is_complete`.
12. **Publish**, then advance the resume cursor (§3.3).

> **Publish the raw record, not a `CustomData` wrapper.** `Actor.publish_data(data_type, data)` enforces `Condition.type(data, data_type.type, ...)`, and a `CustomData` wrapper is not an `NwsClimateDay` — passing one raises `TypeError`. The `CustomData` wrapping requirement governs data submitted to the `DataEngine`, **not** data an Actor publishes itself. Use `self.publish_data(NWS_CLIMATE_DAY_TYPE(...), rec)` with the raw record, still via the shared `DataType` factory.

Steps 9→12 are the crash window §3.3 recovers.

**A note on a red herring:** `Actor.subscribe_data` subscribes to the msgbus *then* logs an error and returns when both `client_id` and `instrument_id` are `None`. Phase 1 has neither. The subscription works correctly; the log line is noise. Do not "fix" it by inventing a `client_id`.

---

## 7. Exit criteria

- `uv run pytest -q` green repo-wide; ruff and mypy clean.
- 100% line+branch coverage on `nws_actor.py` and its supporting modules.
- The `TransportError` enumeration contract test (§5) passes, and **fails** when a route is removed. Dispatch is exact-type; an ad-hoc subclass declared inside the test must fail closed, not inherit "transient".
- **A site in every BLOCKED state reachable in Phase 1 still polls, and a clean poll reopens it.** This is the regression test for the deadlock in §6 step 1 — the single most important test in this phase.
- **Thread-affinity measurement (§4.1)** recorded as a test, not an assumption.
- Live-path guard proven: a backtest performs no network I/O.
- Warm-start republish proven by a test that kills between persist and publish — asserting the cursor was **durable at the moment of the kill**, and failing if it was never written.
- A wall-clock ceiling on the catalog path (§3.1), with its retention assumption stated.
- Re-polling an already-ingested product produces **no** duplicate record and **no** integrity violation.

**The Phase 1 exit test** (proposal §8) is a **divergence** test, not a round-trip. Deriving the expected sequence from the same write Run A produced only proves the catalog reads back what it wrote — it passes even when live and replay share an identical fault. Compare the **full `to_dict()`** of each record (not a hand-picked tuple, which cannot see a field the projection omits), **include `ts_event`**, and pin additionally against a **hand-verified golden** fixture authored independently of Run A.

**Correction to a premise stated in earlier revisions:** `ts_event` is **not** the replay-ordering key in 1.231.0. `ts_init` is the sort key everywhere (`backtest/engine.pyx:903`, `:2610`) and `ts_event` is never read in the replay path. A wrong `ts_event` corrupts settlement semantics and joins — which is serious — but it does not reorder a backtest. Include it in the comparison for that reason, not for an ordering reason.

**On the fuzz and catalog ceilings:** wall-clock assertions are genuinely noisy on shared CI. State the methodology — fixed iteration count, percentile, or a machine-normalized budget — or the instruction to treat a breach as production-blocking will be ignored after the third false alarm.

---

## 8. Standing constraints

NautilusTrader is immutable — no monkeypatching, no vendored source, no writes into site-packages. Path components derive only from the registry object and a typed date, never from parsed product text. The User-Agent is the role mailbox `breezy-data@gmail.com`, never a personal address. TLS is never disabled. No commits.
