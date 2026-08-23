# Phase C/D design: collection durability (WI-8, WI-9, WI-10, WI-12)

**Status:** design artifact only — no production code, no tests written here.
**Authority:** `NWS_COLLECTION_RUNTIME_PLAN_ADDENDUM.md` overrides
`NWS_COLLECTION_RUNTIME_PLAN.md`. This document overrides both where it cites code the addendum did not examine.
Every `path:line` below was opened this session.

---

## 0. Two findings that reshape Phases C and D

### 0a. The resume cursor is not durable, and never has been

- `_save_cursor` writes via `self.cache.add(...)` (`src/breezy/ingest/nws_actor.py:1108`); `_load_cursor` reads
  `self.cache.get(...)` (`:1078`). `self.cache` is the Nautilus `Cache`, **not** `SqliteStateStore`.
- `Cache.add` sets `self._general[key] = value` and forwards to a database only if one exists
  (`.venv/.../nautilus_trader/cache/cache.pyx:1704-1708`); `Cache.get` returns `self._general.get(key)`
  (`:2853`) — an in-memory dict.
- Breezy configures `CacheConfig(database=None, ...)` (`src/breezy/runtime/node_config.py:150`); the kernel maps
  that to `cache_db = None` (`nautilus_trader/system/kernel.py:310-311`), and `Cache.cache_general` then sets
  `self._general = {}` (`cache/cache.pyx:298`).
- `sqlite_store.py:1-15` documents rejecting `Cache` for durable state on exactly these grounds. The cursor was
  left on the rejected mechanism.

Consequences: (1) `warm_start` (`nws_actor.py:1039-1065`) republishes the **entire** station catalog on every
restart since `resume_cursor` is always `None` — safe for subscribers (`:1085-1088`) but not "resume", and it
grows with retention against a read the actor itself calls unbounded (`:94-101`); (2) conditional-GET validators
are equally volatile (`:1153`), so every restart re-fetches unconditionally — extra load under one User-Agent,
the documented path into the UA trap; (3) WI-8's justification collapses (§1); (4) WI-9 must be written to FAIL
today (§2). That is the point.

### 0b. A permanent-loss window between observe and persist

`poll_once` observes every prepared product into the durable index at `nws_actor.py:708-710` —
`product_index.observe` writes through `store.set` (`product_index.py:517`), committed before return
(`sqlite_store.py:119-120`) — and only then persists (`:714`). A process death in that window leaves the uuid
durably "known", so the next poll's `_undeduped` filter drops it (`:775-779`) and **the product is never fetched
again**. Nothing in the repo detects this. It is the strongest argument for the gap ledger being the priority
item of the four.

---

## 1. WI-8 — bounded drain of in-flight work on stop

### Verdict: DO NOT BUILD IT. CUT.

**Substrate.** There is no `_inflight`. `_submit` (`nws_actor.py:527-537`) calls
`run_coroutine_threadsafe` and attaches only `_on_poll_done`; the future is dropped. `on_stop` (`:452`) cancels
timers; `on_dispose` (`:455`) calls `shutdown_executor()` → `shutdown(wait=False, cancel_futures=True)`
(`:458-460`). Any drain must first build future tracking that does not exist. The plan's `[PR-P2]` is right that
a synchronous wait in `on_stop` would block the loop thread — but its cited `_inflight` mechanism is fiction
here.

**Null hypothesis.** Nautilus offers no per-actor in-flight registry; `Actor.run_in_executor` is already ruled
out with evidence (`nws_actor.py:45-49`) — its `TaskId` has no result channel. A drain is genuinely net-new: a
cost, not yet a reason. **Why it should still not be built:**

1. **It cannot buy what the plan says it buys.** The justification is "the fsync'd cursor plus idempotent
   product index make abandonment safe". The cursor is in-memory (§0a). Letting a poll finish still writes that
   cursor into a dict that dies at exit. A drain cannot make a non-durable cursor durable.
2. **Wrong half of the failure space.** A drain runs only on graceful stop. The failures that cost days —
   supervisor SIGKILL after a stop timeout, OOM, host loss — bypass it entirely, and `_save_cursor`'s own
   docstring already makes this argument about `on_save` (`nws_actor.py:1099-1105`). §0b's window is reachable
   by all of them.
3. **WI-10 covers all of it.** A gap ledger detects a missing climate day regardless of how the process died. A
   drain in addition is a second, weaker mechanism for a subset of the same problem — parallel architecture,
   which repo `CLAUDE.md` forbids.
4. **The plan grades it "correctness-adjacent, not correctness"** (plan `:245`). Under YAGNI that is a cut.
5. **Its one real benefit — deterministic restart tests — is free.** See below.

### What WI-9 does instead to stay deterministic

Determinism comes from never having in-flight work at stop, not from draining it:

- **Drive `poll_once` directly, awaited.** It is a plain coroutine (`nws_actor.py:611`). Nothing goes through
  `_submit`, so nothing can be in flight.
- **Never arm timers.** `on_start` returns without arming when there is no running loop (`:430-439`), so
  registering outside a loop gives a timer-free actor by construction — the property `poll_timer_armed` (`:392`)
  already exposes for assertion.
- **Assert the absence.** After `on_stop`, `poll_timer_armed is False`; after `on_dispose`, the executor is shut
  down. Both already hold.

**If overruled**, the shape: a `set[concurrent.futures.Future]` added in `_submit`
(`:537`) and discarded in `_on_poll_done` (`:539`); `async def drain(timeout_s)` using
`concurrent.futures.wait(fs, timeout=...)` then `shutdown(wait=False, cancel_futures=True)` regardless of
outcome, WARN with the abandoned count on expiry; invoked from `runtime/cli.py:_run_node`
(`src/breezy/runtime/cli.py:114-136`) **between** `node.run()` returning and `node.dispose()` — the only point
with a live loop and stopped timers, and never the synchronous `on_stop`/`on_dispose`. (`Executor.shutdown` has
no `timeout` parameter; the plan is right to flag that at `:241`.)

**Files to create: none. Files to modify: none.**

## 2. WI-9 — restart/resume across a real start/stop/start cycle

**File:** `tests/integration/test_runtime_restart_resume.py` (new) — the file
`tests/integration/test_runtime_lifecycle_smoke.py`'s docstring already names as its follow-on.

**Architecture.** Reuse the smoke test's seams rather than inventing new ones: `RecordingNode` / `RecordingTrader` / `local_probe`
(`tests/integration/test_runtime_lifecycle_smoke.py:38-78`), `tmp_path` for `state_db_path` and `catalog_base`,
an injected monotonic counter through `ingest_runtime(clock=...)` (`src/breezy/runtime/composition.py:103`), and
a fixture transport substituted onto `shared.transport`. Zero network: the double answers `fetch_discovery_list`
/ `fetch_product` from `tests/fixtures/nws`; no `httpx.AsyncClient` is ever constructed.

**Cycle.** `with ingest_runtime(settings, clock=fake, probe=local_probe) as rt:` →
`build_ingest_node(rt, node_factory=RecordingNode)` → swap in the fixture transport, register the actor against
a `TestClock`, `await actor.poll_once()` → capture `actor.resume_cursor`, catalog contents,
`rt.shared.gate.status(venue, city)`, and the raw bytes at `f"{CURSOR_KEY_PREFIX}{venue}:{city}"`
(`nws_actor.py:200`, `:1075`) read **from `rt.store`** → exit the context, where `ExitStack` runs `shared.dispose` then
`store.close` (`composition.py:129,158`), releasing the process slot and the sqlite handle → rebuild over the
**same** `tmp_path`, asserting no `DuplicateSharedIngestStateError` → assert against the fresh runtime.

| # | Assertion | Today |
|---|---|---|
| A1 | `store.get(cursor_key)` is not `None` after the first poll | **RED** — nothing writes it |
| A2 | Fresh actor's `resume_cursor` equals the pre-restart cursor | **RED** |
| A3 | Warm start republishes only records past the cursor | **RED** — republishes everything |
| A4 | Re-poll yields no duplicate and no `record_write_integrity_violation` | expect GREEN |
| A5 | Gate state (incl. UA-trap latch) survives | expect GREEN (`gate.py:813,831`) |
| A6 | Product index survives and still dedupes | expect GREEN (`product_index.py:517`) |

A1–A3 are the RED that justifies the item. Do not soften them.

### Kill between persist and publish

`_persist_batch` returns at `nws_actor.py:1000`; `_publish_records` runs at `:732` and saves the cursor per
record at `:1030`. The kill point is between them, injected by substituting `actor.write_records` — an
explicitly documented injectable seam (`nws_actor.py:370-372`) — with a wrapper that performs the real write and
then raises a sentinel. The poll aborts after a durable catalog write and before any publish.

**Proving durability AT the kill, and failing if the write never happened:**

1. **Read the store, not the actor.** After the kill and *before* teardown, assert `rt.store.get(cursor_key)` is
   not `None` and decodes — the durable medium, so an in-memory-only write cannot satisfy it. (Today this is the
   failing assertion.)
2. **Positive control.** With the kill removed, `store.get(cursor_key)` must transition `None` → non-`None`
   across the poll. A test that only ever observed `None` proves nothing.
3. **Second-connection read-back.** Re-read through a *fresh* `SqliteStateStore` on the same path — the
   technique `composition.py:145-146` already uses for the durability probe. A value visible only through the
   writing connection is not durable; this is what makes the assertion about fsync rather than about a dict.
4. **Negative control.** A variant skipping `_save_cursor` must make assertion 1 fail; state this in the
   docstring as the test's falsifiability condition.

### The production change WI-9 forces

A1–A3 cannot go green without moving the cursor and validators off `Cache` onto the injected `StateStore`,
already reachable as `self._shared.store` (`shared_state.py:452-454`). Local change: `_load_cursor` /
`_save_cursor` / `reset_cursor` / `_load_validators` / `_store_validators` (`nws_actor.py:1067-1153`) swap
`self.cache.get/add` for `self._shared.store.get/set`. Prefixes `breezy:nws:cursor:` / `breezy:nws:validators:`
(`:200-201`) already namespace correctly beside `gate:` (`gate.py:92`) and `productidx:`
(`product_index.py:81`). `reset_cursor`'s `b""` sentinel keeps working — `_load_cursor` treats falsy bytes as
absent (`:1079`). Thread note: the store is thread-confined (`sqlite_store.py:72-79`); all five call sites run
on the event-loop thread, the same thread the gate and index already use from those paths.

**Build order:** RED integration test → move cursor/validators onto `StateStore` (update
unit tests asserting `Cache`) → GREEN → A4–A6 as regression.

---

## 3. WI-10 — the gap ledger (`src/breezy/ingest/gaps.py`)

Location per `[PR-A3]` confirmed correct: it encodes climate-day and settlement-clock rules exactly like
`gate.py`, and `runtime` already imports `ingest` (`composition.py:37-40`), so the reverse would cycle.

**Null hypothesis.** Nautilus models nothing like "a climate day that should exist and does not". `check_freshness` (`gate.py:1298`)
measures elapsed time only and reopens on one successful poll (`:906`); `record_final_overdue` (`:1357`) is
keyed to one climate day and cleared by `record_final_received` (`:1399`) for that same day — neither remembers a *set* of missed days. **The pattern to copy is in-repo:** `ProductIntegrityIndex`'s
durable manifest key (`product_index.py:83-113`) is the existing, reviewed answer to "this store cannot
enumerate keys". Do not invent a second answer.

### The store compromise, stated plainly

`SqliteStateStore` exposes only `get`/`set`/`close` (`sqlite_store.py:99-126`). **No scan, no delete.**
Therefore: enumeration is impossible, so the ledger carries its own manifest; deletion is impossible, so
**nothing is ever removed** — resolution and acknowledgement are state transitions written into the entry value.
The keyspace grows monotonically, at most one entry per `(site, climate_day)`: ~1,825/year across five sites,
~200 bytes each, ~0.4 MB/year. Accepted on the same reasoning `product_index.py:71-80` accepts its own unbounded
growth. A manifest rewritten per append is O(n) per write; at this rate it stays small for a decade, and if it
ever does not the fix is a manifest sharded by year, never a delete.

### Key schema (prefix `gaps:`)

| Key | Value |
|---|---|
| `gaps:__manifest__` | sorted JSON array of ids `"<venue>\|<city>\|<YYYY-MM-DD>"` |
| `gaps:<venue>:<city>:<YYYY-MM-DD>` | one JSON `GapEntry` |
| `gaps:hw:<venue>:<city>` | `{"expected_through": "YYYY-MM-DD"}` high-water mark |

UTF-8 JSON throughout, matching `gate.py` and `product_index.py`. No uuid or free-form text ever appears in a
key. Manifest written **first**, entry second — same safe ordering and same reason as
`product_index.py:101-106`.

**`GapEntry`:** `venue`, `city`, `climate_day` (ISO), `state`
(`OPEN|RESOLVED|ACKNOWLEDGED_LOST`), `first_detected_ns`, `last_reconciled_ns`, `resolved_at_ns|None`,
`observed_revision_seq` (0 while OPEN), `observed_is_final`, `correction_flag`, `is_superseded`,
`acknowledged_by|_at_ns|_reason`.

### Expected set — local climate days, never UTC

The actor owns the correct derivation and it must be **reused, not re-implemented**:
`_most_recent_completed_climate_day` (`nws_actor.py:1205-1217`) converts `now_ns` through
`standard_time_zone(window.std_utc_offset_hours)` — the fixed standard-time offset from `ClimateDayWindow`
(`registry/sites.py:117-131`), never DST-following. Extract it as a pure function in `gaps.py`; the actor calls
that, so there is exactly one copy.

Day `d` becomes **expected** only once `now_ns >= review_extension_end_ns(d)`:

- `settlement_deadline_ns(d)` = 08:00 on `d+1` in `settlement_timezone` (`America/New_York` for all five sites)
  — the existing computation at `nws_actor.py:1219-1235`, reading `settlement_time_local` (`"08:00"`,
  `registry/sites.toml:129`).
- `review_extension_end_ns(d)` = same construction using `settlement_delay_time_local` (`"11:00"`,
  `sites.toml:134`) and `settlement_delay_timezone`.

**This is the 08:00→11:00 ET METAR-review answer.** A final arriving at 09:30 ET is
inside the review window, so the day is not yet expected and no entry is ever created — the false positive is
designed out rather than suppressed after the fact. `record_final_overdue` still fires at 08:00 from
`check_final_deadline` (`nws_actor.py:1174-1203`); that is the venue's deadline, a different question from "is
this day permanently lost". The two must not be merged.

Candidate range: from `gaps:hw:` (on a cold store, the earliest day still inside retention) through
`most_recent_completed_climate_day(now)`. Bounding it this way keeps reconciliation O(1) per poll.

### Observed set

Per site, `read_climate_days(catalog)` (`persistence/catalog.py:511`), filtered to `record.station ==
site.cli_location`, reduced to the latest record per `climate_day` by `(is_final, ts_init, revision_seq)`. The
same read `warm_start` and `_persist_batch` already perform (`nws_actor.py:940`, `:1056`), and it must run on
the executor via `_run_off_loop` (`:1407`) — never inline on the loop. Reading the catalog rather than a
ledger-private "seen" set mirrors `_have_final_for`'s reasoning (`:1237-1243`): only the durable artifact
answers whether a day was actually collected, and it survives §0b's observe/persist window, which an
index-derived answer would not.

### Append-and-resolve; idempotent reconciliation

`reconcile(now_ns) -> ReconcileResult`, at most one write per changed entry:

- expected ∧ ¬observed ∧ no entry → write `OPEN`, `first_detected_ns=now_ns`.
- expected ∧ ¬observed ∧ `OPEN` → update `last_reconciled_ns` only.
- observed ∧ `OPEN` → `RESOLVED`, stamp `resolved_at_ns` and `observed_revision_seq`. **Never delete the key.**
- `ACKNOWLEDGED_LOST` → never transitions back; `last_reconciled_ns` still updates so the entry stays visibly
  alive in the snapshot.
- Two runs with the same `now_ns` and catalog produce byte-identical store contents — that is the idempotence
  test.

### Revision tracking

An entry is `RESOLVED`, never "closed". Each reconcile compares the stored `observed_revision_seq` against the
catalog's current latest for that `(station, climate_day)`. A **revision event** fires when the seq increases,
or when `correction_flag` or `is_superseded` flips true (`NwsClimateDay`, documented at
`src/breezy/domain/nws_climate_day.py:141-150`); the entry updates in place and a `PostSettlementRevision` alert
goes out through WI-12. `revision_seq` is monotonic per `(station, climate_day)` and assigned by
`_persist_batch` (`nws_actor.py:948-952,982`), so an increase is unambiguous. This closes plan criterion 7.

### `ACKNOWLEDGED_LOST` without a delete

The operator sets it by **writing a new entry value**, never removing a key. Surface: a `breezy gaps acknowledge
--venue --city --day --reason` subcommand in `runtime/cli.py`, run against a **stopped** process (the store is
thread-confined and single-writer; a second live process is already forbidden). It opens its own
`SqliteStateStore`, reads the entry, refuses unless the state is `OPEN`, writes the transition with
`acknowledged_by` / `_at_ns` / `_reason`, exits. The entry stays in the manifest and in the health snapshot
forever; only re-notify is muted.

### Severity ladder (conservative, `[PR-D4]`)

`days_until_retention_loss = 7 - age_in_days(climate_day)`. The **~7-day `api.weather.gov` retention figure is
an ASSUMPTION, not a cited fact** — repeat that in the module docstring beside the threshold constants.
`no_data_fallback_days = 7` (`sites.toml:136`) is a venue settlement rule, **not** an API retention guarantee;
do not conflate them.

INFO at > 5 days remaining · **WARN at ≤ 5** · **CRITICAL at ≤ 2** · aged out (< 0) is CRITICAL and is the only
state an operator may acknowledge.

### Attachment point

`reconcile` is called from the **top** of `poll_once`, beside `self.check_staleness()` (`nws_actor.py:638`) and
**before** the `network_allowed()` early return at `:639`. That is the only line reached on every timer fire:
the 304 branch (`:654`), the no-new-products branch (`:674`) and the network-disallowed branch all return early,
and those are exactly the polls a gap ledger exists to observe. Attaching after the terminal publish at `:732`
would miss all of them. The call is failure-isolated: a ledger error is logged and swallowed, never blocking a
poll — losing reconciliation for one cycle is recoverable, losing the poll is not.

### RED tests (`tests/unit/test_ingest_gaps.py`, frozen fake clock)

Complete history → no gaps · one missing day → one `OPEN` entry with the exact `first_detected_ns` · a day whose
review extension has **not** elapsed is not a gap (assert the instant before 11:00 ET and the instant after) ·
reconciling twice writes identical bytes · a filled gap becomes `RESOLVED` and stops alarming · severity ladder
parameterised · ledger survives a real `SqliteStateStore` round-trip read through a second connection · a UTC/ET
disagreement day is attributed to the ET climate day · `revision_seq` increase on a `RESOLVED` day emits a
revision event · `correction_flag` and `is_superseded` each independently emit one · `ACKNOWLEDGED_LOST` mutes
re-notify but stays in the snapshot · an entry key missing while present in the manifest reads as tampering, not
"no gap" (mirroring `product_index.py:94-99`) · reconcile runs on the 304 path and on the network-disallowed
path.

**Build order:** pure date/time helpers → `GapEntry`/`GapState` codec → manifest +
tampering → `reconcile` (idempotence, severity, revisions) → attach at `:638` with failure isolation → CLI
acknowledge subcommand.

---

## 4. WI-12 — health snapshot + alert sink (`src/breezy/runtime/health.py`)

**Null hypothesis.** No atomic-write helper exists anywhere in `src/breezy` — the catalog's durability is flock plus read-back, and
`SqliteStateStore` is a database, not a file writer. Nautilus's `LoggingConfig` gives log output, not a
machine-readable state file. Both must be authored. HTTP hardening must be **duplicated, not subclassed**:
`HttpTransport._build_client` (`src/breezy/ingest/http.py:577-587`) is concrete and NWS-specific, with a host
allowlist (`:572-575`) a webhook must not inherit.

**Atomic write.** `tempfile.mkstemp(dir=<target's own directory>)` — same directory so `os.replace` is a same-filesystem, atomic
rename — then `os.fchmod(fd, 0o600)`, write, `os.fsync(fd)`, close, `os.chmod(tmp, 0o600)`, `os.replace(tmp,
target)`, `os.chmod(target, 0o600)`; `finally`-unlink the temp on failure. **Mode `0o600` on BOTH temp and
final**: `mkstemp`'s mode is umask-dependent, and a partial snapshot must never be observable at the final path.

**Snapshot fields:** `schema_version`, `process_started_at_ns`, `snapshot_at_ns`, `trader_id`, `sites: [{venue, city, gate_state,
gate_reason, blocking_causes, last_successful_poll_ns, cursor, open_gaps: [{climate_day, state, severity,
days_until_retention_loss}], acknowledged_lost_count}]`, `ua_trap_latched`, `alerts_emitted_this_cycle`.

Sourced from `gate.status(venue, city)` (`gate.py:843`), `gate.blocking_causes(...)` (`:880`), the ledger, and
`actor.resume_cursor` (`nws_actor.py:396`).

**Never serialize `BreezyRuntimeSettings`.** `user_agent_contact` must not reach the
snapshot; the field list is an explicit allowlist, not `asdict` of anything. No absolute filesystem paths —
state-db and catalog paths are omitted entirely. A stale file is itself the "process is dead" signal, so
`snapshot_at_ns` is mandatory.

**`AlertSink`.** `class AlertSink(Protocol): def emit(self, payload: AlertPayload) -> None: ...`

`AlertPayload` is a frozen dataclass with exactly four fields — `severity: str`, `event: str`, `site: str`
(`"<venue>/<city>"` or `"global"`), `detail: str` (bounded, e.g. 200 chars, truncated) — plus an `ALLOWED_KEYS`
constant. Forbidden in `detail`: full state dumps, absolute filesystem paths, raw upstream bodies or headers,
and `user_agent_contact`. Contract test: `set(payload.to_dict()) <= ALLOWED_KEYS`, so a future contributor
cannot widen it by passing a snapshot dict into `emit`.

- **`LoggingAlertSink`** — the default. Logs through the `breezy` namespace, which
  `src/breezy/runtime/logging_bridge.py` forwards into the Nautilus log stream.
- **`WebhookAlertSink`** — constructed **only** when `BREEZY_ALERT_WEBHOOK_URL` is set. Unset by default; when
  unset the class is never instantiated and no client is built. No endpoint and no token in source. Client
  mirrors `http.py:577-587`: TLS 1.2+ context, `verify` on, `follow_redirects=False`, `trust_env=False`, bounded
  timeout, HTTPS-only, no userinfo in the URL.

**Failure containment.** `emit` is always called through a wrapper catching
`BaseException` — specifically including `ssl.SSLError`, `httpx.TimeoutException`, `httpx.TransportError` —
which logs at ERROR and returns. **A sink failure must never propagate into the poll path**, the same stance
`_on_poll_done` takes toward supervision errors (`nws_actor.py:539-558`). This is the single most important test
in the module.

**Cold start.** `AlertState` seeds every tracked condition as **ALL-CLEAR at process
start**, never from persisted state, so a UA-trap latch, a BLOCKED gate or an open gap already true at boot
reads as a false→true transition on cycle 1 and fires. Computing transitions against persisted prior state would
make exactly those persistent, silent conditions never alert. RED test:
`test_alert_fires_on_first_cycle_when_condition_already_true_at_startup`.

**Dedupe.** Emit on transition (clear→set), then re-notify no more often than
`renotify_after_ns` (default 24h) while it holds; clear→set again emits immediately. `ACKNOWLEDGED_LOST` gaps
are excluded from re-notify but stay in the snapshot. Conditions: `UaTrapLatched`, `SiteBlocked` (beyond a
threshold), `FinalOverdue`, `GapInRetentionWarningBand`, `PollStale`, `PostSettlementRevision`.

**Attachment.** Same seam as the ledger — top of `poll_once`, after `reconcile`, before
`network_allowed()` (`nws_actor.py:638-639`), wrapped so nothing propagates.

### RED tests (`tests/unit/test_runtime_health.py`)

Snapshot carries every declared field · mode is `0o600` on the final path **and** the temp file · a partial
write is never observable at the target (patch `os.replace` to raise; assert the old file intact and no temp
left) · snapshot JSON does not contain the configured `user_agent_contact` substring · snapshot contains no
absolute state-db or catalog path · payload keys ⊆ `ALLOWED_KEYS` · each condition fires once on transition and
not again inside the window · a condition already true at startup fires on cycle 1 · clear-then-re-fire emits
twice · `WebhookAlertSink` is not constructed when the env var is unset · a sink raising `RuntimeError`,
`ssl.SSLError`, and a timeout each leave `poll_once` unaffected.

**Build order:** atomic writer + mode tests → `AlertPayload`/`ALLOWED_KEYS`/`AlertSink`/
`LoggingAlertSink` → `AlertState` (cold start, transition, re-notify) → snapshot builder (redaction tests) →
`WebhookAlertSink` behind the env var → attach at `:638`.

---

## 5. What I am NOT building, and why

| Not built | Why |
|---|---|
| **WI-8 bounded drain (CUT)** | Its benefit rests on a durable cursor that does not exist (§0a); it covers only graceful stop while the real loss modes are SIGKILL/OOM; WI-10 covers all of them. Net-new future tracking for something the plan itself grades "correctness-adjacent". §1 records the shape if overruled. |
| `StateStore.delete` / `.scan` | Would change a reviewed, thread-confined durability primitive to serve one consumer. The manifest pattern (`product_index.py:83-113`) already solves it in-repo. |
| A generic atomic-file-write utility module | One consumer. YAGNI — private to `health.py` until a second caller exists. |
| A base class shared by `HttpTransport` and `WebhookAlertSink` | `HttpTransport` carries an NWS host allowlist (`http.py:572-575`) a webhook must not inherit. Duplicate ~6 lines and say so, as `product_index.py:49-51` does. |
| A ledger-private "seen days" set | Only the catalog survives §0b's observe/persist window. |
| Backfill / recovery of a detected gap | Phase 2 (plan §2). The ledger is the input artifact it will consume. |
| Alert channel, endpoint, credentials | Operator-only decision (plan §9). |
| Persisted alert dedupe state | Would defeat cold-start all-clear seeding (`[PR-D2]`). In-memory is correct, not a limitation. |
| Gap-ledger eviction / pruning | No delete, and pruning reintroduces the hole. ~0.4 MB/year accepted. |

## 6. Recommended sequence

1. **WI-9 RED first** — cheapest proof of the largest defect (§0a).
2. **Cursor + validators onto `StateStore`** — GREEN for WI-9.
3. **WI-10 gap ledger** — the only mechanism covering §0b.
4. **WI-12 health + alerts** — consumes the ledger.
5. **WI-8 — not built.**
