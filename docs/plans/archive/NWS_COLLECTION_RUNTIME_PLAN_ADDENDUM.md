# Addendum: NWS Collection Runtime Plan — drift correction

**Status:** authored at the start of the execution session, from evidence.
**Read this BEFORE the plan.** The plan (`NWS_COLLECTION_RUNTIME_PLAN.md`) was
authored against commit `bf916b3`. Seven commits landed after it. Many of the
plan's file:line citations, module names, and stated facts no longer describe
this repository. The plan's *intent* survives intact; its *citations* largely
do not.

Nothing here changes the seven-point definition of "consistently collecting"
in plan section 1. That definition is still the deliverable.

---

## 1. Corrected environment facts

| Plan claims | Verified reality |
|---|---|
| Baseline `1 failed, 1358 passed` | **`1375 passed, 0 failed`, exit 0.** The suite is fully green. |
| `.venv/bin/python` is the interpreter | True, but **no `.venv` existed** — created this session via `uv sync --extra backfill`. |
| A red exit criterion is outstanding (WI-1) | **No such failing test exists.** See §3. |

Also verified clean at baseline: `ruff check .` and `mypy` over the seven
configured source packages.

## 2. Rename / relocation table

The plan proposes modules that were, in the meantime, built under other names.

| Plan name | Reality |
|---|---|
| `runtime/container.py` | `runtime/composition.py` — `ingest_runtime()`, a `@contextmanager` over `ExitStack`, not a class |
| `runtime/actor_configs.py` | No standalone module: `node_config.py::actor_component_id` + `composition.py::build_ingest_actors` |
| `runtime/node.py` | `composition.py::build_ingest_node` + `node_config.py::build_node_config` |
| `runtime/main.py` | `runtime/cli.py`, with `breezy/__init__.py::main` forwarding one hop |
| `persistence/state_store.py` / `FileStateStore` (fsync + blocking flock) | `runtime/sqlite_store.py` / `SqliteStateStore` (SQLite, WAL + `synchronous=FULL`). **Not a rename — a different mechanism.** Key-value `get`/`set` over `bytes` only; no delete, no scan; thread-confined. |
| "the container" (object) | The `SharedIngestState` instance, bound as `shared` |
| — | `runtime/bootstrap_witness.py` (`enforce_bootstrap_witness`) exists with **no counterpart in the plan** |

Consequence: every plan instruction phrased as "add X to `container.py`" means
`composition.py`, and every durable-state design premised on flock semantics
must be re-derived against SQLite instead.

## 3. Work items whose premises are stale

### WI-1 — moot, not done-as-prescribed
The target test `test_a_backtest_performs_no_network_io` **does not exist** in
this repo, nor does `arm_final_overdue`, nor `TestComponentStubs.clock()`. The
hazard was designed away rather than patched: `nws_actor.py:420-439` `on_start()`
wraps `asyncio.get_running_loop()` in `try/except RuntimeError`, and on failure
sets `self._loop = None` and returns **without arming any timer**. No loop, no
timer, no network. Nothing to fix.

### WI-5 — two of its three concerns do not apply here
- **ns→s unit conversion (risk R1, "the most likely silent defect in the plan")
  does not exist in this codebase.** Settings are already stored as
  `poll_interval_seconds` / `parse_timeout_ms` (`runtime/settings.py:154-159`).
  There is no nanosecond→second translation anywhere to get wrong, and
  therefore no non-whole-second rejection rule to write.
- **`component_id` as `str` vs `ComponentId` ([PR-A1], risk R17) is inert.**
  `actor_component_id` returns a `str`, but Nautilus's `Actor.__init__`
  (`common/actor.pyx:154-157`) coerces `str` → `ComponentId` at construction,
  so `actor.id` is a genuine `ComponentId` regardless of the construction path.
  The `.parse()`-vs-hand-construct rule the plan makes blocking is therefore a
  robustness preference here, not a correctness defect. It is still worth
  *pinning* the coercion, so a future Nautilus change surfaces as a test
  failure instead of a deploy-time collision.
- **What IS a real gap:** `stagger_index` does not exist anywhere. Plan
  objective item 2 requires each site to poll "staggered, with its own timer".
  All five sites currently share one `poll_interval_seconds` with no offset, so
  they poll simultaneously — five concurrent bursts to `api.weather.gov` under
  one User-Agent, which is the documented path into the UA trap.

### WI-11 — two of four premises are factually wrong
Verified by direct grep over `src/`:
- `max_products_per_poll` — **zero occurrences.** No cap exists. `poll_once`
  (`nws_actor.py:691`) iterates `sorted(pending, key=lambda e: e.issuance_time_ns)`
  uncapped: oldest-first, no ceiling, so the starvation the plan fears cannot
  occur.
- `_poll_once_guarded` and `may_poll` — **zero occurrences.** The plan's claim
  that a BLOCKED gate disables catch-up entirely is wrong. `poll_once` gates
  only on `network_allowed()` (`nws_actor.py:568-607,639`), which refuses
  network **only** for the global `UA_TRAP_403` latch and a self-set backoff
  window. A site BLOCKED for any other reason still polls, and one clean poll
  reopens it — already test-proven at `tests/unit/test_ingest_nws_actor.py:553`.
  Only `UA_TRAP_403` (manual clear) and `ACIS_DISAGREEMENT` suspend drain.
- The 304 short-circuit is confirmed as described (`nws_actor.py:654-661`), but
  is the healthy steady state, not a drain defeat.
- Ordering is enforced (`catalog.py:884-890`, `NonMonotonicWriteError`) and is
  naturally satisfied, because `ts_init` is `retrieved_at_ns` (fetch time) and
  backlog fetches are sequential awaits in issuance order.

**The one genuinely undetermined mechanism** — and the reason WI-11 still earns
its place — is the **same-clock-tick `ts_init` collision**: two products fetched
within one clock tick get an *identical* `retrieved_at_ns`, which passes the
non-decreasing check but produces an exact `ts_init`-range rewrite that the
catalog silently discards and routes to `record_write_integrity_violation`
(CRIT hard-block). A fast drain of a large backlog is precisely the condition
that triggers it, and nothing tests it.

## 4. Work items confirmed still valid and still missing

WI-2 (clock agreement), WI-3 (logging bridge — **zero** `logging.Handler` in
`src/`, so Breezy's stdlib records genuinely do not reach the Nautilus log
stream), WI-7b (lifecycle smoke), WI-8 (async drain), WI-9 (restart/resume),
WI-10 (gap ledger), WI-12 (health + alert sink), WI-13 (runbook), WI-14 (soak).

WI-4, WI-6 and WI-7 are **built but under-asserted**: the three-step teardown
order (`node.dispose` → `shared.dispose` → `store.close`) is correct by
construction yet asserted nowhere as a single sequence, and none of WI-6's three
BLOCKER pins exist as tests.

## 5. Substrate corrections for Phases C-D

- **No atomic-file-write helper exists anywhere in `src/breezy`.** WI-12's
  health snapshot must implement temp-write + `os.replace` + `0o600` itself;
  there is nothing to reuse. The catalog's durability is flock + read-back
  verification, not temp-then-rename.
- **The state store cannot scan or delete.** `SqliteStateStore` exposes only
  `get`/`set`/`close` over `bytes`. A gap ledger must encode its own structure
  under a namespaced key prefix (the gate uses `gate:`, the product index uses
  `productidx:`), and cannot enumerate keys.
- **The per-poll reconciliation seam is the TOP of `poll_once`**
  (`nws_actor.py:611`, beside `check_staleness()` at :638) — the only line that
  runs on every timer fire. Attaching after the terminal publish would miss the
  304, no-new-products, and network-disallowed early returns, which are exactly
  the polls a gap ledger must observe.
- **A webhook sink must duplicate, not subclass, the HTTP hardening** in
  `ingest/http.py:577-587` (`verify=<TLS1.2+ ctx>`, `follow_redirects=False`,
  `trust_env=False`, bounded timeouts). `HttpTransport` is a single concrete
  NWS-specific class with no reusable base.

## 6. Late correction: the catalog is NOT idempotent

Measured while closing the observe-before-persist race. Recorded because the
opposite was assumed in a dispatch brief and is easy to assume again.

| Component | Idempotent on re-write? |
|---|---|
| `ProductIntegrityIndex.observe` (`ingest/product_index.py`) | **Yes.** First-write-wins; a second `(uuid, digest)` returns `MATCH` read-only and rewrites nothing. |
| `catalog.write_records` (`persistence/catalog.py:422`) | **No.** Append-only by design: groups by type, calls `write_data`, verifies by read-back. There is no `product_uuid` key in it, and `NwsClimateDay` has no such field (only `NwsRawProduct` does, `domain/nws_raw_product.py:162`). A re-persist APPENDS A DUPLICATE. |

Consequence for anyone reordering the ingest path: re-persisting is safe only
because `_persist_batch` nudges `retrieved_at_ns` strictly past the catalog's
current max `ts_init` (the WI-11 guard). That turns a re-persist into a later
revision of identical content instead of an exact `ts_init`-range rewrite —
and an exact-range rewrite is precisely what `write_records` reports as
`skipped`, routing to `record_write_integrity_violation` (CRIT hard-block).
Supersession then resolves on `(is_final, ts_init, revision_seq)` to the same
readings, so settlement is unaffected; the cost is one redundant revision row.

Do not "simplify" that nudge away on the belief that the catalog dedupes.
