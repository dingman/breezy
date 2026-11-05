# Implementation Plan: NWS CLI Collection Runtime

**Status:** proposed, not started — **peer-reviewed and revised** (architecture, Python/TDD, data-integrity, security)
**Revision:** v2. Five blocking findings from adversarial review are folded in; each is marked **[PR-n]** at the point it applies.
**Owner:** next implementation session (assume no memory of the session that authored this)
**Scope class:** new-feature / composition-root architecture

---

## 0. Read this first — sandbox facts

These are verified properties of this working environment. Getting them wrong wastes a session.

- The test command is `.venv/bin/python -m pytest -q`. Bare `python` does **not** exist here.
- `timeout(1)` does **not** exist here. Do not write test helpers or runbook steps that shell out to it.
- Current baseline: **1 failed, 1358 passed**. The single failure is addressed by WI-1 and is a test-harness bug, not a production defect.
- **The ~7-day `api.weather.gov` retention figure is an ASSUMPTION, not a verified fact** [PR-D4]. It is asserted at `WEATHER_INGESTION_PROPOSAL.md:344,412` with no authoritative citation in-repo, and it drives criterion 5 and the whole WI-10 severity ladder. Per-product eviction timing within the window is not guaranteed uniform. Treat thresholds conservatively (see WI-10) and cite a real source when one is obtained.
- Corrected citations (the first draft drifted): the blocking flock acquisition is `state_store.py:350` (`:314` is the `__init__` signature); `ActorFactory.create` ends at `nautilus_trader/common/config.py:614`; the duplicate-actor `RuntimeError` is `trader.py:336-340`.
- Hard boundary (repo CLAUDE.md): build-time only. Nothing in this plan authenticates to a trading venue, places an order, or reads wallet material. The only network the runtime touches is read-only public `https://api.weather.gov`. Even that must not be exercised from a test.

---

## 1. Objective

Breezy must **consistently and reliably collect NWS CLI climate products, unattended, for months.**

That sentence is the deliverable, so it is defined precisely here. "Consistently collecting" means all six of the following hold simultaneously and continuously:

1. **A process exists.** A single long-lived OS process hosts the ingest actors, starts on boot, and is restarted automatically by a supervisor if it dies. Today no such process exists at all.
2. **Every configured site is polled on schedule.** Each `(venue, city)` polls at its configured interval, staggered, with its own timer, and a missed timer is visible rather than silent.
3. **Every issued CLI product for a configured site is durably persisted exactly once.** Both the preliminary and the final for each climate day, deduped by product uuid and `raw_sha256`.
4. **A restart loses nothing and duplicates nothing.** The durable cursor and product index survive process death; warm start republishes anything persisted-but-unpublished.
5. **Any day that was NOT collected is detected, recorded, and recoverable-or-alarmed within the ~7-day `api.weather.gov` retention window.** After ~7 days the product is gone from the API forever. Silent loss is the dominant risk in this system.
6. **A human is told when 1-5 stop holding.** Specifically: UA-trap latch set, a site blocked longer than a threshold, a final overdue past its deadline, the process not running, or a gap approaching the retention edge.
7. **Every revision to an already-resolved climate day is detected, persisted, and alerted** [PR-D1]. Collection is not only about presence — a day can be collected and later become *wrong*. `NwsClimateDay` already carries `correction_flag`, `revision_seq`, `is_superseded` (`src/breezy/domain/nws_climate_day.py:141-150`), and the proposal specifies auto-adoption with a `PostSettlementRevision` alert (`WEATHER_INGESTION_PROPOSAL.md:260`, `:358`). A correction that changes a settled value must never pass silently. This criterion was missing from the first draft and is the most important addition in v2: without it, the gap ledger marks a day "observed" once and never looks at it again.

Anything that does not move one of those seven forward is out of scope for this plan.

### What already exists (do not rebuild it)

- `src/breezy/ingest/nws_actor.py` — the full ingest Actor (~2000 lines). Complete, unit-tested, and **wired into nothing.** It has never run inside a real process.
- `src/breezy/ingest/gate.py` — settlement gate, UA-trap latch, freshness watchdog, final-overdue.
- `src/breezy/ingest/product_index.py` — integrity/dedupe index (`:260-406`); idempotent across restart, cannot raise `NonMonotonicWriteError` on re-poll.
- `src/breezy/ingest/shared_state.py` — `SharedIngestState`, the process-wide container (`__init__` at `:330`, `dispose` at `:561`, single-process slot claim at `:604-617`).
- `src/breezy/persistence/state_store.py` — `FileStateStore`, fsync'd, flock-guarded (`:314`).
- `src/breezy/settings.py` — `BreezySettings`, env-driven (`BREEZY_SITES`, `BREEZY_CATALOG_BASE`, `BREEZY_STATE_PATH`, `BREEZY_POLL_INTERVAL_S`, `BREEZY_POLL_STAGGER_S`; `:208-212`).
- `src/breezy/registry/sites.toml` — all five sites, `registry_version 1.0.0`: NYC/KNYC/KOKX, SFO/KSFO/KMTR, MIA/KMIA/KMFL, MDW/KMDW/KLOT, LAX/KLAX/KLOX.

The missing piece is a **composition root**: the thing that builds the container, builds five configs, builds a `TradingNode`, attaches the actors, installs logging, and runs until signalled.

---

## 2. Scope

### In scope

| Area | Why |
|---|---|
| `src/breezy/runtime/` composition root (logging bridge, container, actor configs, node, main) | Definition items 1-2. Nothing runs without it. |
| Entrypoint repoint (`pyproject.toml:80-81` -> `breezy.runtime.main:main`) | The console script currently runs a `print("Hello from breezy!")` stub. |
| Contract tests pinning BLOCKER 1 and BLOCKER 2 | Both are silent-at-deploy-time failures. |
| Test-harness clock fix for the one red test | It is a listed Phase 1 exit criterion currently failing. |
| Clock-agreement invariant between container clock and Nautilus clock | Latent silent-disarm of the final-overdue watchdog. |
| Bounded drain of in-flight executor work on stop | Definition item 4; makes restart tests deterministic. |
| Restart/resume proven against a real process lifecycle | Mechanism is built but never exercised end to end. |
| Gap ledger: expected-vs-observed climate days, durable, per site | Definition item 5. Argued in section 3. |
| In-retention-window catch-up: verify the existing discovery+dedupe path actually re-fetches missed days, repair if it does not | Definition item 5. |
| Health snapshot + pluggable alert sink (default: log sink) | Definition item 6. Argued in section 3. |
| Operator runbook: supervision unit, UA-trap manual clear, gap triage | Definition items 1 and 6. |

### Out of scope — with the reason

- **Settlement resolver (`src/breezy/settlement/`).** It is a *use-time consumer* downstream of collection (`WEATHER_INGESTION_PROPOSAL.md:266`, `PHASE1_ACTOR_BRIEF.md:305`). Collection does not depend on it.
- **Features (`src/breezy/features/`), edge computation, sizing, risk gates, any trading logic.** No order path is touched. No exec client is configured.
- **Open-Meteo or any second data source.** Not needed for CLI collection.
- **IEM AFOS backfill (`persistence/backfill.py`).** Deferred to Phase 2 by `WEATHER_INGESTION_PROPOSAL.md:412`. It recovers days *outside* the 7-day window; this plan's job is to stop days falling out of the window in the first place, and to make it loudly visible when one does. **However**, the gap ledger built here is deliberately the input artifact a Phase 2 backfill will consume: record the gap now, recover it later.
- **Data clients / instruments / venue config.** Verified unnecessary: `data_clients` and `exec_clients` both default empty (`live/config.py:312-313`), and startup connectivity, reconciliation, and portfolio-initialisation waits are all vacuous with zero clients (`system/kernel.py:1301-1367`, `live/execution_engine.py:1670-1695`).
- **Metrics/Prometheus/dashboards.** The health snapshot file is the seam; wiring a scraper is an operator decision.

---

## 3. Two decisions this plan makes, with justification

### Decision A — deploy **all five cities from day one**, in one process

The two source documents disagree. `WEATHER_INGESTION_PROPOSAL.md:405` says "NYC only" for Phase 1; `PHASE1_ACTOR_BRIEF.md:19` says "Five instances in production". The registry already ships all five with complete settlement metadata. The brief is the later and more specific artifact, and the registry is the strongest evidence of settled intent.

**Decision: build, test, and deploy all five.** Reasons:

1. **NYC-first does not de-risk the risky part.** The genuinely dangerous thing is the *five-actor composition* — the `component_id` collision (BLOCKER 2), the shared-container registration checks (`nws_actor.py:459-467`, `:782-788`), the cross-site burst policy derived from the full site set (`shared_state.py:375-377`), and timer stagger. An NYC-only soak exercises **none** of it.
2. **The five-actor composition is fully provable offline.** The contract tests in WI-6 pin both blockers with a fixture-backed transport and no network.
3. **The cost of waiting is permanent.** Every day the other four cities are not collected leaves `api.weather.gov` retention after ~7 days and never returns. A 2-week NYC-first soak permanently forfeits ~14 climate days x 4 cities.
4. **The retreat path is free.** `BREEZY_SITES` (`settings.py:208`) already selects the site set at runtime. If the five-site deployment misbehaves, the operator shrinks to NYC by editing one environment variable and restarting.

**Corollary — one process, five actors, and this is mandatory, not stylistic.** Two processes cannot work: `SharedIngestState._claim_process_slot` raises `DuplicateSharedIngestStateError` on a second construction (`shared_state.py:604-617`), and `FileStateStore.__init__` takes a **blocking** flock (`state_store.py:314`) so a second process against the same state path hangs forever with no diagnostic.

**Corollary — never run a second Breezy process against live `api.weather.gov`.** A staging process with a different `BREEZY_STATE_PATH` *would* start. It would also double the request rate under the same User-Agent while the cross-site burst policy — which is per-process — sees only half the traffic. That is a direct path to the UA trap, which halts all five sites and clears only by manual operator action (`gate.py:1013-1017`).

### Decision B — gap detection and alerting are **in scope for this plan**

- **Gap detection is in scope.** `check_freshness` (`gate.py:1245-1302`) measures elapsed time only. It has no memory of *which climate days* were missed, and the gate silently reopens on the next successful poll. A 48-hour outage produces a gate that is green again minutes after recovery, with no record that two days are missing. If those days also fell outside retention, the loss is permanent **and invisible**.
- **Alerting is in scope, but only the seam and a safe default.** No pagerduty / webhook / slack / smtp / sentry exists anywhere in the repo. Combined with a UA trap whose recovery is *deliberately* manual, the current design can halt all five sites indefinitely with nobody informed.

  > **OPERATOR-ONLY DECISION:** the alert channel, its endpoint, and its credentials. Implement `WebhookAlertSink` as a generic POST-to-configured-URL sink guarded behind an env var that is **unset by default**; never hardcode an endpoint, never commit a token.

---

## 4. Architecture changes

New package `src/breezy/runtime/` — the composition root.

| File | Responsibility |
|---|---|
| `src/breezy/runtime/logging_bridge.py` | A `logging.Handler` forwarding stdlib records into the Nautilus `Logger`. **Required, not optional:** `nws_actor.py:92-96` states the composition root installs it, and the Nautilus `Logger` silently discards records when logging is uninitialized. Without this, every `logger.critical` in the actor goes nowhere. |
| `src/breezy/runtime/container.py` | `BreezySettings` -> `FileStateStore` -> `SharedIngestState(..., clock=LiveClock().timestamp_ns)`, via a context manager with **ordered teardown** (container `dispose` at `shared_state.py:561` before store `close` at `state_store.py:565`). |
| `src/breezy/runtime/actor_configs.py` | One `NwsIngestActorConfig` per site. Owns (a) **unit translation** — settings are nanoseconds (`settings.py:291-295`), the actor config is **seconds** (`nws_actor.py:373-389`); (b) **`component_id` assignment** — `NWS-INGEST-{venue}-{city}`. Every config produced through `build_actor_config` (`nws_actor.py:398`) so msgspec validates. |
| `src/breezy/runtime/node.py` | Builds `TradingNodeConfig(environment=LIVE, trader_id="BREEZY-001", logging=..., exec_engine=LiveExecEngineConfig(reconciliation=False))`, constructs five actors, `node.trader.add_actor(instance)` x5, `build()`. |
| `src/breezy/runtime/health.py` | Per-cycle atomic-write JSON health snapshot (mode **`0o600`**) + `AlertSink` protocol + `LoggingAlertSink`. Stays in `runtime/` — it reports composed state and owns no domain rules. |
| `src/breezy/ingest/gaps.py` | **Relocated from `runtime/` on review** [PR-A3]. The gap ledger encodes *domain* knowledge — climate-day boundaries, ET settlement times, supersession — identical in kind to `gate.py`'s freshness logic, not composition. It also reconciles once per poll cycle, and the poll lives in `nws_actor.py`; leaving it in `runtime/` would force `ingest` to import `runtime` and invert the layering (risking an import cycle with `runtime/node.py`). `runtime/` wires the sink only. |
| `src/breezy/runtime/main.py` | `main()`: settings, logging bridge, container context, node, `run()`, **three-step ordered teardown**, exit code. **Installs no signal handlers** — Nautilus already does [PR-P1]. |
| `pyproject.toml:81` | `breezy = "breezy.runtime.main:main"` (was `breezy:main`). |
| `src/breezy/__init__.py` | Remove the `print("Hello from breezy!")` stub body. |

### The one architectural decision that needs explicit justification

**`Trader.add_actor(instance)` instead of `TradingNodeConfig(actors=[ImportableActorConfig(...)])`.**

`NwsIngestActor.__init__(self, config, *, container)` (`nws_actor.py:653`) requires a keyword-only `container`. `ActorFactory.create` ends with `return actor_cls(config)` (`nautilus_trader/common/config.py:613`) — no injection seam. The declarative path **cannot** construct this actor, and would fail at deploy time with a `TypeError`, not at test time.

`Trader.add_actor` (`trading/trader.py:312`) is the native Nautilus API for attaching an already-constructed actor, performing the same wiring via `register_base` (`trader.py:345-351`), with a per-actor Clock (`trader.py:342`).

Per repo CLAUDE.md, Nautilus is immutable and must not be bypassed. **This is not a bypass.** It is one of two first-class construction paths Nautilus provides.

**Honest justification, corrected on review** [PR-A2]. The first draft claimed the declarative path is "structurally incapable of dependency injection". That overstates it: it is incapable of *constructor-parameter* injection. A **third option exists** and must be recorded as considered-and-rejected, because `nws_actor.py:357-359` shows the actor was designed with the re-encode/decode round-trip in mind: since `SharedIngestState` is already a process-wide enforced singleton (`shared_state.py:604-617`), a module-level `current_shared_state()` accessor plus `container: IngestContainer | None = None` would make `ImportableActorConfig` work with no new abstraction.

**It is rejected anyway, and `add_actor` is kept**, because explicit constructor injection beats a service-locator lookup: the singleton accessor makes the dependency invisible at the call site and in tests, and turns a compile-time-ish wiring error into a runtime one. Record *this* reasoning — including the rejected option — in `runtime/node.py`'s module docstring, so the next reader does not rediscover the accessor and think it was overlooked.

**Additional silent-failure trap** [PR-A2]: `Trader.add_actor` **logs an error and returns** — it does not raise — if the trader is already running (`trader.py:332-334`). A five-actor attach loop that begins after start would silently drop actors. WI-6 must test this.

**Ordering constraint (hard), construction:** `NwsIngestActor.__init__` reads the durable cursor at `nws_actor.py:693`. The store and container must be fully constructed **before** the first actor is constructed. The container context manager must make this ordering impossible to get wrong.

**Ordering constraint (hard), teardown — three steps, not two** [PR-A6]: `node.dispose()` -> `container.dispose()` -> `store.close()`. The first draft pinned only the last two. Actors are owned by the trader (`Trader._dispose`, `trader.py:304-308`) and write *through* the store; disposing the container while actors are still live risks a write against a disposed collaborator. WI-7 asserts all three in order.

---

## 5. Work items

Ordered smallest-risk-first. Each phase is independently mergeable and leaves the repo green.

TDD is mandatory. Every work item states its RED test first. The coverage bar is **100% line + branch** on `nws_actor.py` and supporting ingest modules (`PHASE1_ACTOR_BRIEF.md:336-352`); hold `src/breezy/runtime/**` to the same bar.

### Phase A — unblock the red exit criterion (no production code risk)

#### WI-1 — Fix the hard-coded-date time bomb in the backtest-no-network test

- **File:** `tests/unit/test_ingest_nws_actor.py` (the test at `:629-654`).
- **Symptom:** `test_a_backtest_performs_no_network_io` fails — `arm_final_overdue` (`nws_actor.py:1811`) -> `LiveClock.set_time_alert_ns` -> `ValueError: alert time 2026-08-23T12:00:00 was in the past`.
- **Root cause — test-harness bug, not a production defect.** The test hand-rolls registration with `TestComponentStubs.clock()` at `:643`, which returns a **real `LiveClock`**, while `container.clock` is a `FakeClock` frozen at 2026-08-22. It began failing on 2026-08-23 for that reason and no other.
- **The repo already contains the fix.** The shared `actor` fixture (`:366-386`) pins a `TestClock()` to the injected fake clock value at `:384-385`, and its docstring (`:378-382`) names this exact hazard.
- **Action:** apply the same pinning. If the test genuinely needs its own instance (it constructs the actor itself to assert `event_loop is None`), factor the clock-pinning into a small shared helper used by both.
- **RED:** already red for the right reason. Capture the failing output verbatim as the RED artifact.
- **GREEN:** `.venv/bin/python -m pytest -q` -> 1359 passed, 0 failed.
- **Guard against recurrence:** assert that the Nautilus clock and container clock report the same instant at registration time.
- **Must NOT happen:** no change to `nws_actor.py`. No weakening of the four passing clock/timer contract tests.
- **Risk:** Low.

#### WI-2 — Make the two-clock agreement invariant enforced, not assumed

- **Files:** `src/breezy/ingest/nws_actor.py` (registration/start path only).
- **Why:** the actor reads two clocks by design — `self._wall_clock()` (container clock, source of the settlement deadline) and `self.clock` (Nautilus clock owning timers, enforcing `allow_past=False`). Nothing asserts they agree. In production both are real-time so they do; if they diverge, `arm_final_overdue` either raises or — worse — silently arms a deadline that never fires, **disarming the final-overdue watchdog with no log line.** That watchdog is the only orthogonal defence against a perpetual-304 staleness attack (`PHASE1_ACTOR_BRIEF.md:301`).
- **Action:** at start/registration, compare the two clocks; if they differ beyond a small named-constant tolerance, raise.
- **RED:** a test registering with deliberately skewed clocks asserting loud failure; a second asserting the in-tolerance case is silent.
- **Dependencies:** WI-1. **Risk:** Low-Medium.

### Phase B — the composition root

#### WI-3 — `runtime/logging_bridge.py`

- **Design:** `logging.Handler` subclass mapping stdlib levels to Nautilus levels; `install(...)` attaching to the `breezy` namespace (not root); matching uninstall for test isolation. Idempotent install.
- **RED tests (`tests/unit/test_runtime_logging_bridge.py`):** record reaches a fake Nautilus logger with mapped level; each level maps correctly (table-driven); double-install produces one record; uninstall detaches; a record logged before install does not crash (assert the documented behaviour).
- **Risk:** Low.

#### WI-4 — `runtime/container.py`

- **Design:** context manager taking `BreezySettings`, yielding a built `SharedIngestState`. Constructs `FileStateStore`, one `LiveClock`, then `SharedIngestState(...)` matching the verified signature at `shared_state.py:330-345`. On exit: `container.dispose()` **then** `store.close()`, both running even if the body raised.
- **Why the ordering matters:** the container holds gate, index and transport that write through the store. Closing the store first would make dispose's final writes fail.
- **RED tests (`tests/unit/test_runtime_container.py`), `tmp_path`, no network:** yielded object matches settings sites; dispose-then-close order asserted; an exception inside the `with` still runs both teardown steps in order and re-raises the original; a failure during construction releases the process slot so a second attempt succeeds (`shared_state.py:346-351`); the container clock is a single shared callable.
- **Dependencies:** WI-3. **Risk:** Medium.

#### WI-5 — `runtime/actor_configs.py`

> **[PR-A1] BLOCKING finding from review — the first draft of this work item was unsatisfiable.** It required *both* "every config produced through `build_actor_config`" *and* "`component_id` is a real `ComponentId`, not a `str`". Those cannot both hold. `build_actor_config` is `msgspec.convert(dict(raw), type=..., strict=True)` with **no `dec_hook`** (`nws_actor.py:407`), while `component_id: ComponentId | None` (`nautilus_trader/common/config.py:559`) is a Cython type reachable only through `msgspec_decoding_hook`'s `issubclass(obj_type, Identifier)` branch (`config.py:186-187`), which only `NautilusConfig.parse` supplies (`config.py:303`). **The repo already pins this exact trap**: `tests/contract/test_actor_timer_and_retry_contract.py:142-187` proves only `parse()` yields a real `ComponentId` and that a hand-built config holds a `str`. Read that test before writing a line of this module.

- **Design:** `build_site_configs(settings) -> tuple[NwsIngestActorConfig, ...]`, deterministic order, assigning `component_id`, `stagger_index=i`, and all seconds-valued fields converted from ns settings.
- **Construction path — pick ONE and pin it in a test:**
  - **(a) preferred:** `NwsIngestActorConfig.parse(msgspec.json.encode(mapping, enc_hook=msgspec_encoding_hook))`, which routes through the decoding hook and yields a genuine `ComponentId`; or
  - **(b)** extend `build_actor_config` to accept `dec_hook=msgspec_decoding_hook`, which is a change to `nws_actor.py` and therefore needs its own RED test.
  Do **not** hand-construct: direct construction accepts wrong types in silence (`nws_actor.py:362-364`).
- **This module is the only place unit translation may live.** A duplicated ns->s conversion is the seed of a 10^9 error presenting as "never polls" or "hammers the API". State that in the docstring.
- **Non-integral conversions: the rule is REJECT** [PR-P4]. The first draft said "handled by a stated tested rule" without stating it, which invites the implementer to pick a behaviour and then write a test validating their own choice — a decorative test. The rule: a `poll_interval_ns` / `poll_stagger_ns` / freshness-field value that is not a whole number of seconds is **rejected with a named error at config-build time**, because the actor's units are integer seconds and silent truncation is exactly the 10^9-class bug R1 guards against.
- **Enumerate the FULL settings->config mapping in the tests, not just the ns subset** [PR-P5] — including `parse_timeout_s` -> `parse_ceiling_seconds`.
- **RED tests (`tests/unit/test_runtime_actor_configs.py`):** five configs with exact expected component ids; ids pairwise distinct; `stagger_index` 0..4 no repeats/gaps; **exact unit conversion** parameterised over every mapped field; a non-whole-second value raises the named error; msgspec round-trip; **`component_id` is a real `ComponentId`, not a `str`** — this test fails against the naive path and is the whole point of the finding above.
- **Risk:** Medium — the most likely silent defect in the plan.

#### WI-6 — `runtime/node.py` + composition contract tests

- **Design:** `build_node(settings, container) -> TradingNode` per section 4. Module docstring carries the `add_actor` justification.
- **RED contract tests (`tests/contract/test_node_composition_contract.py`):**
  - **BLOCKER 1 pin.** `ActorFactory.create` (or equivalent `actor_cls(config)`) raises `TypeError` for the missing keyword-only `container`. Pin the Nautilus version in the docstring — this test should start failing the day Nautilus grows an injection seam.
  - **BLOCKER 2 pin.** Five configs without explicit `component_id` all resolve to `ComponentId("NwsIngestActor")` and `add_actor` raises `RuntimeError` on the second (`trader.py:335-339`); WI-5 configs do not collide and all five attach.
  - A built node exposes exactly five actors with the five expected ids.
  - Each actor got its **own** Clock instance (`trader.py:342`) — pairwise distinct objects.
  - Each actor registered against the **container's own** gate and index — a foreign container is rejected (`nws_actor.py:459-467`, `:782-788`).
  - Building performs **zero** network I/O.
  - **`add_actor` on an already-running trader logs and returns rather than raising** (`trader.py:332-334`) [PR-A2] — assert the actor count did not increase, so a future refactor that attaches actors after start fails loudly here instead of silently collecting from three cities.
- **Dependencies:** WI-4, WI-5. **Risk:** Medium-High — this is the piece that has never run.

#### WI-7 — `runtime/main.py`, ordered teardown, entrypoint repoint

> **[PR-P1] BLOCKING finding from review — do NOT hand-roll signal handling.** Nautilus already implements exactly what the first draft proposed to build. `TradingNode.__init__` wires `loop_sig_callback=self._loop_sig_handler` (`live/node.py:75`); `NautilusKernel._setup_loop` calls `loop.add_signal_handler` for SIGTERM/SIGINT/SIGABRT (`system/kernel.py:566-570`); `_loop_sig_handler` (`kernel.py:574-582`) removes the SIGTERM handler and no-ops a second SIGINT — the double-signal guard — then invokes the callback, which logs and calls `self.stop()` (`node.py:491-493`). Writing our own is a null-hypothesis violation under CLAUDE.md, and actively harmful: `asyncio.add_signal_handler` **replaces** rather than stacks, so a `main.py`-side handler installed after `build_node()` would silently clobber Nautilus's double-signal guard.

- **Design:** `main() -> int`. Settings -> logging bridge -> container context -> `build_node` -> `node.run()` (which blocks until `stop()` completes) -> **three-step ordered teardown** (`node.dispose()` -> `container.dispose()` -> `store.close()`, per section 4) -> exit code. Settings failures produce one actionable log line naming the offending env var, exiting non-zero without a traceback wall. **No signal handlers are installed here.**
- **Files:** `src/breezy/runtime/main.py` (new); `pyproject.toml:81` -> `breezy.runtime.main:main`; `src/breezy/__init__.py` — delete the `print("Hello from breezy!")` stub body.
- **RED tests (`tests/unit/test_runtime_main.py`):** invalid env var exits non-zero naming the variable; **the three teardown steps run in the documented order** (call-order assertion) and still run when the body raises, re-raising the original error; `main` returns 0 on clean stop; **importing `breezy` prints nothing**; the console-script target resolves to a callable.
- **Test seam:** a fake node whose `run()` synchronously invokes a captured `stop` callback — **not** simulated OS signals, and never a real event loop with real network.
- **Coverage note** [PR-P6]: removing the hand-rolled signal plumbing shrinks `main.py`'s branch surface substantially, which is most of what made the 100% bar look unrealistic here.
- **Dependencies:** WI-6. **Risk:** Low-Medium (reduced from Medium by deleting the custom handlers).

#### WI-7b — Minimal start/stop/start smoke [PR-A5]

- **Why:** WI-8's bounded-drain design is justified *by* restart determinism, yet the first draft scheduled the restart proof (WI-9) after it. A lifecycle defect found in WI-9 could invalidate WI-8's design. Insert a cheap smoke test **before** WI-8.
- **Design:** fixture transport, `tmp_path`, no network. Build -> start -> stop -> release slot and flock -> build again over the same paths -> assert clean start. No assertions about record content; that is WI-9's job.
- **Dependencies:** WI-7. **Risk:** Low. High information per unit effort.

### Phase C — survive months, not minutes

#### WI-8 — Bounded drain of in-flight work on stop

> **[PR-P2] BLOCKING finding from review — the drain must be ASYNC and must NOT live in `on_stop`.** `_inflight` holds `asyncio.run_coroutine_threadsafe` futures (`nws_actor.py:685`, `:1015`, `:1024`); completing or cancelling them requires the **event-loop thread** to run scheduled callbacks. `on_stop` runs synchronously *on that same thread*, and its own docstring (`:852-857`) says so and explains it therefore cannot block on these futures. A synchronous bounded wait placed there blocks the one thread needed to service `call_soon_threadsafe`, so it would run out the full timeout on **every** stop while draining nothing — converting a clean shutdown into a guaranteed worst-case delay.
>
> Second correction: **`concurrent.futures.Executor.shutdown()` has no `timeout` parameter.** A literal "bounded drain via `shutdown(wait=True, timeout=...)`" does not exist in the stdlib.

- **The repo already contains the correct pattern:** `drain_for_test` (`nws_actor.py:1073-1080`) is `async` and yields via `asyncio.sleep`, running cooperatively *on* the loop rather than blocking it. Model the production drain on it.
- **Action:** implement the drain as an async coroutine invoked from the **async** stop path (`main.py` teardown, or a `TradingNode.stop_async`/kernel shutdown hook) — never from the synchronous `on_stop`/`on_dispose` Cython handlers. Track futures and use `concurrent.futures.wait(fs, timeout=...)`, then `shutdown(wait=False, cancel_futures=True)` regardless of outcome. On deadline expiry, WARN naming the abandoned-task count and proceed — never block indefinitely, since a supervisor SIGKILL is strictly worse.
- **Why correctness-adjacent, not correctness:** the fsync'd cursor plus idempotent index make abandonment **safe** — nothing corrupts, the product is re-fetched after restart. The real cost is non-deterministic restart tests, which makes WI-9 unreliable.
- **RED tests:** a slow in-flight task is awaited to completion; a task past the deadline proceeds with the WARN and the correct count; **the drain does not deadlock when the loop thread is the caller** — assert it completes well inside the timeout rather than burning it, which is the specific failure the finding above describes.
- **Dependencies:** WI-7b. **Risk:** Medium — deadlock is the failure mode; the async placement is what avoids it.

#### WI-9 — Prove restart/resume against a real process lifecycle

- **File:** `tests/integration/test_runtime_restart_resume.py`.
- **Why:** the resume mechanism is fully built but **never exercised against a real start/stop/start cycle.** "Built and unit-tested" and "survives a restart" are different claims.
- **Design (fixture transport, zero network, `tmp_path`):** build+start node, drive one poll persisting and publishing; stop cleanly, tear down, release slot and flock; build a *fresh* container and node over the *same* paths; assert the cursor was read at construction (`nws_actor.py:693`), warm start republished exactly the persisted-but-unpublished records and nothing else, and re-polling produces **no** duplicate and **no** integrity violation (`PHASE1_ACTOR_BRIEF.md:346`).
- **Second scenario:** kill **between persist and publish** (`PHASE1_ACTOR_BRIEF.md:330`); assert the cursor was durable at the moment of the kill, and **fail if it was never written** — a passing test that never exercised the write is worse than no test.
- **Dependencies:** WI-8. **Risk:** High — budget time for defects discovered here; any fix gets its own RED unit test.

### Phase D — do not lose days silently

#### WI-10 — Gap ledger: expected vs observed climate days, and revision tracking

- **File:** `src/breezy/ingest/gaps.py` (relocated per [PR-A3]), durable via `StateStore` (`state_store.py:481`, `:494`).
- **Design:** expected set derived from registry `settlement_time_local`/`settlement_delay` and wall clock (a day becomes expected only after its settlement delay passes); observed set from durably-persisted finals; per-site entry `{missing_days, first_detected_ns, last_reconciled_ns, days_until_retention_loss}`. Reconciliation runs once per poll cycle, **pure and idempotent**. **Append-and-resolve, not overwrite.**
- **[PR-D1] Supersession is part of "observed", not a separate concern.** A day marked observed is **not** final for ledger purposes. Track `revision_seq` per `(venue, city, climate_day)`; an increase, or a record with `correction_flag`/`is_superseded` set (`domain/nws_climate_day.py:141-150`), is a **revision event** that updates the ledger entry and raises the `PostSettlementRevision` alert of WI-12. Without this, a correction that changes a settled value passes in total silence — the first draft's single worst defect.
- **[PR-D5] Terminal `ACKNOWLEDGED_LOST` state.** A day that ages out of retention is unrecoverable, and under append-and-resolve plus slow re-notify it would alert forever — the exact alert-fatigue failure R11 claims to close. Add a terminal state settable **only by explicit operator action**, which mutes re-notify for that one `(venue, city, climate_day)` while still showing it in the health snapshot.
- **[PR-D4] Conservative severity ladder**, because retention is assumed rather than verified: informational at 5+ days remaining, **WARN at 5 days, CRITICAL at 2** (the first draft used <=1, which assumed the full window is safely usable).
- **RED tests (`tests/unit/test_runtime_gaps.py`), frozen fake clock:** no gaps when complete; a single missing day with correct `first_detected_ns`; a day whose settlement delay has **not** passed is not a gap (test the instant before and after); reconciling twice is idempotent; a filled gap resolves and stops alarming; severity escalation parameterised; ledger survives a store round-trip; **timezone** — settlement times are local ET and days are climate days, not UTC calendar days; test a day where UTC and ET disagree; **a `revision_seq` increase on an already-observed day produces a revision event**; **`ACKNOWLEDGED_LOST` mutes re-notify but stays visible in the snapshot**; **[PR-D6] a final arriving inside the 08:00->11:00 ET METAR-review extension** (`WEATHER_INGESTION_PROPOSAL.md:89`, `:343`) **is not a false-positive gap**.
- **Dependencies:** WI-11 (inverted from the first draft, per [PR-A4] — WI-11's answer determines whether escalation is needed at all). **Risk:** Medium.

#### WI-11 — Verify (and repair if needed) in-window automatic catch-up

- **Files:** test-first in `tests/contract/`; production change in `nws_actor.py` **only if the test proves one is needed.**
- **The open question.** Discovery reads `/products/types/CLI/locations/{loc}` (retained ~7 days) and step 4 drops known uuids (`PHASE1_ACTOR_BRIEF.md:314`), which *suggests* a 48-hour outage self-heals. Three things could defeat it, **none currently tested**:
  1. `max_products_per_poll: 8` (`nws_actor.py:390`) caps a poll's batch. Does a multi-day backlog drain, or do the same 8 retry while the oldest starve?
  2. The discovery GET is **conditional**. A still-valid ETag yields a 304 terminal branch fetching nothing (`PHASE1_ACTOR_BRIEF.md:312`) — and a 304 counts as a successful poll, satisfying the freshness watchdog.
  3. `write_records` requires **non-decreasing `ts_init` within a batch** (`PHASE1_ACTOR_BRIEF.md:315`). A backlog spanning days must be ordered correctly or the write fails.
  4. **[PR-D3] A BLOCKED gate disables automatic drain entirely — and this is the most consequential of the four.** `_poll_once_guarded` returns before any discovery fetch when `may_poll()` is false (`nws_actor.py:1220-1225`). For a UA-trap, recovery is *deliberately manual* (`gate.py:1013-1017`). So the in-window catch-up this work item tests **cannot run at all while blocked**: retention keeps burning while nothing looks stuck. The runbook (WI-13) must state that delaying a UA-trap clear directly costs permanently-lost days.
- **RED tests (fixture transport):** 48-hour backlog fully fetched across successive polls, `ts_init` non-decreasing per batch, oldest-first across batches; 7-day backlog (>8 products) strictly shrinks poll over poll with no starvation; a 304 during an open gap does not mark the site healthy while the ledger still escalates; a product aged out of discovery is never fetched and is recorded as permanently lost at CRITICAL.
- **If red against current behaviour**, repair minimally and locally — ordering and/or cap handling. Do not redesign the poll.
- **[PR-A4] Resequenced earlier.** These are fixture-transport poll tests against the *existing* actor — buildable today, in parallel with Phase B, depending on nothing in Phase C. And the answer determines WI-10's design (whether escalation is needed at all), so it must precede the ledger rather than follow it.
- **Dependencies:** none beyond the existing actor; run in parallel with Phase B. **Risk:** Medium — may reveal a real defect; if it does, this is the most valuable item in the plan.

#### WI-12 — Health snapshot and alert sink

- **File:** `src/breezy/runtime/health.py`.
- **Snapshot:** atomically-written JSON (write-temp-then-rename), refreshed per poll cycle: process start, snapshot time, per-site gate state and reason, per-site last successful poll, per-site cursor, open gaps, UA-trap latch. A stale file is itself the "process is dead" signal.
  - **[PR-S1] Mode `0o600` on BOTH the temp file and the final path**, matching `FileStateStore._persist` (`state_store.py:526-530`). The default `tempfile`/`os.open` mode is umask-dependent and typically world- or group-readable. Gap-ledger contents reveal exactly when and how collection is degraded — reconnaissance value for timing an attack against the UA-trap or freshness watchdog — and path disclosure aids a local attacker chaining a traversal bug. Docstring the reason, as `state_store.py` does. **RED test: snapshot file mode is 0600.**
  - **[PR-S4] Never serialize `BreezySettings` directly.** `user_agent_contact` is PII-adjacent by its own docstring's admission and must not reach a disk artifact or an alert payload. **RED test: the snapshot JSON does not contain the configured `user_agent_contact` substring.**
- **Alert sinks:** `AlertSink` protocol with `emit(severity, event, detail)`; `LoggingAlertSink` default; `WebhookAlertSink` POSTing to an env-var URL that is **unset by default** and never constructed when unset.
  - **[PR-S2] The payload is an explicit allowlist, not "whatever the snapshot holds".** Define a bounded `AlertPayload` — severity, event name, site id, and a short human `detail` string — and forbid full state dumps, absolute filesystem paths, and raw upstream HTTP bodies/headers from reaching `detail`. The threat is not classic SSRF (the URL is operator-supplied) but **payload over-collection**: a typo'd or compromised webhook endpoint discloses internal topology and operational cadence. **RED test: `set(payload.keys()) <= ALLOWED_KEYS`**, so a future contributor cannot silently widen it by passing the whole snapshot dict into `emit`.
  - **[PR-S3] Mirror `http.py`'s outbound hardening** — TLS verify on, `follow_redirects=False`, bounded timeout, `trust_env=False`. Not a bare `requests.post` or a default client. A POST failure is caught and logged, never raised into the poll path.
- **Alert conditions:** UA-trap latch set; site blocked beyond threshold; final overdue; gap within the retention warning band; last successful poll exceeding a multiple of the interval; **[PR-D1] `PostSettlementRevision`** — a `revision_seq` increase on an already-resolved day (`WEATHER_INGESTION_PROPOSAL.md:358`). The first draft omitted this last one entirely.
- **[PR-D2] BLOCKING — cold-start semantics must be specified.** Conditions that are already true at boot (persisted UA-trap latch, a BLOCKED gate, an open gap — all survive restart, `gate.py:790-816`) would **never fire** if "transition" is computed against empty in-memory prior state on cycle 1. That is precisely the silent-persistent-failure class this plan exists to prevent. **Design rule: seed prior-state as all-clear at process start**, so any condition true on the first cycle emits. **RED test: `test_alert_fires_on_first_cycle_when_condition_already_true_at_startup`.**
- **Dedupe/suppression:** emit on transition plus a slow re-notify — months of running turns an un-deduped alert into a mail bomb, which trains the operator to ignore it. `ACKNOWLEDGED_LOST` gaps (WI-10) are muted from re-notify.
- **RED tests (`tests/unit/test_runtime_health.py`):** snapshot contains every declared field; the write is atomic (temp-then-rename, partial never observable); **file mode is 0600**; **snapshot excludes `user_agent_contact`**; each condition fires once on transition and not again within the re-notify window; **a condition already true at startup fires on cycle 1**; clearing and re-firing produces a second alert; **payload keys are within the allowlist**; `WebhookAlertSink` not constructed when the env var is unset; **a sink that raises — including on TLS failure and on timeout — does not propagate into the poll path** — the single most important test in the module.
- **Dependencies:** WI-10. **Risk:** Medium.

### Phase E — operability (documentation, no source code)

#### WI-13 — Operator runbook

- **File:** `docs/core/RUNBOOK_NWS_COLLECTION.md`.
- **Contents:** required env vars; supervision (`Restart=always`, backoff, unprivileged user, durable state/catalog paths); **"never start a second process"** with both failure mechanisms (`shared_state.py:604-617`; the blocking flock at `state_store.py:314` which hangs with no diagnostic); **never run staging against live api.weather.gov**; **UA-trap manual clear procedure** (`gate.py:1013-1017`) — how to see the latch, what to verify before clearing, the clear step, what to watch after; **gap triage** and what `days_until_retention_loss` means; **availability posture** — corrupt persisted state is fail-closed by design (`PHASE1_ACTOR_BRIEF.md:356-362`), operator acknowledges in writing; shrink-to-NYC retreat path.
- **Added on security review:**
  - **[PR-S5] SIGKILL is safe and self-heals.** The kernel releases the `flock` unconditionally on process death (`filelock.py`, `state_store.py`), so killing a wedged supervisor is safe and the next start recovers. State this positively — and state the corollary: **never manually delete or `touch` the `.lock` file.** Deleting it while a live flock is held does not release it, and replacing it with a symlink could confuse the `O_NOFOLLOW` check.
  - **[PR-S7] Directory permissions.** `BREEZY_STATE_PATH` and `BREEZY_CATALOG_BASE` parents must be owner-only; a world-writable parent defeats the symlink defenses already in code.
  - **[PR-S7] systemd hardening**, since no `0o600` in code survives a permissive process umask: `NoNewPrivileges=yes`, `ProtectSystem=strict` (or equivalent), and an explicit `umask`.
  - **[PR-S7] `Environment=BREEZY_USER_AGENT=...` is world-readable** via `systemctl cat` and `/proc/<pid>/environ`. That value is not a secret, so this is acceptable — say so explicitly, so a future operator does not assume env-file secrecy applies here and put something genuinely sensitive in the same unit.
  - **[PR-D3] Delaying a UA-trap clear burns retention days.** While blocked, automatic catch-up cannot run at all (`nws_actor.py:1220-1225`) — nothing looks stuck, and days are being permanently lost.
  - **[PR-A8] Log rotation and retention policy.** R14's "disk growth: none" was verified for *catalog data only*. A months-long LIVE Nautilus `LoggingConfig` with fileout and no rotation is the larger volume by far.
- **Risk:** Low.

#### WI-14 — Fixture-backed soak and go-live checklist

- Fixture-transport soak exercising >= one simulated week including an induced outage and restart, pass criteria being WI-9 through WI-12 assertions holding continuously; then the go-live checklist.
- **Risk:** Low.

---

## 6. Sequencing and dependencies

```
WI-1 --> WI-2                     Phase A  (green suite; red exit criterion closed)
WI-11 ...............             Phase A/B, PARALLEL  [PR-A4]  (does backlog self-heal?)

WI-3 --+
       +--> WI-4 --+
WI-5 --+           +--> WI-6 --> WI-7 --> WI-7b   Phase B  (a process exists, and restarts)
WI-5 --------------+

WI-7b --> WI-8 --> WI-9           Phase C  (it survives restarts, provably)

WI-11 --> WI-10 --+               Phase D  (it does not lose days or revisions silently)
                  +--> WI-12

WI-12 --> WI-13 --> WI-14         Phase E  (a human can run it)
```

- WI-3 and WI-5 are independent; build them in parallel.
- **[PR-A4] WI-11 moved earlier and now precedes WI-10** — it needs only the existing actor and a fixture transport, and its answer determines whether the ledger needs an escalation ladder at all.
- **[PR-A5] WI-7b (start/stop/start smoke) precedes WI-8**, so lifecycle defects surface before the drain is designed around them.
- Every phase boundary leaves the repo green and is independently mergeable.
- **Phase B is the minimum shippable increment.** After WI-7, Breezy collects. Phases C-E make that collection trustworthy for months, which is the actual objective — do not stop at B.

---

## 7. Risk register

| # | Risk | Severity | Mitigation |
|---|---|---|---|
| R1 | ns->s unit conversion error in `actor_configs.py` — a 10^9 mistake either never polls or hammers the API into the UA trap | **High** | WI-5 parameterises conversion over every field; conversion lives in exactly one module |
| R2 | `component_id` collision at deploy time (`trader.py:335-339`) | High | WI-6 contract test asserts both collision and non-collision |
| R3 | Someone "fixes" `add_actor` back to `ImportableActorConfig`; fails only at deploy | High | WI-6 BLOCKER-1 test plus the justification in `node.py`'s docstring |
| R4 | Latent lifecycle bug surfaces only in WI-9 and blows the schedule | High | WI-9 scheduled before gap/alerting work; budget slack |
| R5 | Multi-day backlog does not drain because of `max_products_per_poll` starvation | High | WI-11 tests it explicitly rather than assuming self-healing |
| R6 | UA trap halts all five sites with nobody notified | High | WI-12 alerting + WI-13 clear procedure + never-two-processes |
| R7 | Permanent data loss at the 7-day retention edge | **High, irreversible** | WI-10 ledger with escalating severity; CRITICAL at <=1 day; Phase 2 backfill consumes the ledger |
| R8 | Shutdown drain deadlocks and the supervisor SIGKILLs mid-write | Medium | Bounded deadline; explicit deadlock test including same-thread case |
| R9 | Clock skew silently disarms the final-overdue watchdog | Medium | WI-2 enforces the invariant loudly |
| R10 | Alert sink failure takes down collection | Medium | WI-12 test: a raising sink never propagates |
| R11 | Alert storm over months trains the operator to ignore alerts | Medium | Transition-only emission plus slow re-notify, tested |
| R12 | Teardown ordering loses the last writes before shutdown | Medium | WI-4 pins dispose-before-close with a call-order assertion |
| R13 | Another hard-coded-date time bomb elsewhere in the suite | Medium | During WI-1, sweep the suite for hard-coded absolute dates and note any others |
| R14 | Disk growth (catalog data) | **None** | Verified low single-digit MB/year across all five cities |
| R15 | **[PR-D1] A correction silently changes a settled value** — collected but wrong is worse than absent, because downstream calibration trusts it | **High, silent** | Criterion 7; WI-10 revision tracking on `revision_seq`/`correction_flag`/`is_superseded`; WI-12 `PostSettlementRevision` alert |
| R16 | **[PR-D2] A condition already true at boot never alerts** (persisted UA-trap, BLOCKED gate, open gap) | **High, silent** | WI-12 seeds prior-state all-clear at start; dedicated first-cycle RED test |
| R17 | **[PR-A1] `component_id` silently remains a `str`** because `build_actor_config` has no `dec_hook`, so the collision guard appears to work but does not | High | WI-5 uses `parse()`; RED test asserts a real `ComponentId`; existing pin at `test_actor_timer_and_retry_contract.py:142-187` |
| R18 | **[PR-P2] Bounded drain placed in `on_stop` blocks the loop thread** and burns the full timeout on every stop while draining nothing | High | WI-8 drain is async, modelled on `drain_for_test` (`nws_actor.py:1073-1080`), invoked from the async stop path |
| R19 | **[PR-P1] Hand-rolled signal handlers clobber Nautilus's double-signal guard** (`add_signal_handler` replaces, not stacks) | High | WI-7 installs none; relies on `kernel.py:566-582` / `node.py:491-493` |
| R20 | **[PR-D5] Permanently-lost days re-notify forever**, causing the alert fatigue R11 claims to prevent | Medium | `ACKNOWLEDGED_LOST` terminal state, operator-set, muted from re-notify but still in the snapshot |
| R21 | **[PR-S2] Webhook payload over-collection** leaks internal topology and cadence to a typo'd or compromised endpoint | Medium | Allowlisted `AlertPayload`; contract test bounding payload keys |
| R22 | **[PR-A8] Log volume growth** over a months-long run with no rotation policy | Medium | WI-13 states the rotation/retention policy |

---

## 8. Definition of done

**Repo state**

- [ ] `.venv/bin/python -m pytest -q` fully green (0 failed).
- [ ] ruff and mypy clean.
- [ ] 100% line + branch coverage on `nws_actor.py`, supporting ingest modules, and every new `src/breezy/runtime/**` module.

**Phase 1 exit criteria** (`PHASE1_ACTOR_BRIEF.md:336-352`)

- [ ] **A backtest performs no network I/O** — currently red; closed by WI-1.
- [ ] A site in every Phase-1-reachable BLOCKED state still polls, and a clean poll reopens it.
- [ ] Warm-start republish proven by a test that kills between persist and publish, asserting the cursor was durable **at the moment of the kill** and failing if it was never written — WI-9.
- [ ] Re-polling an already-ingested product produces no duplicate and no integrity violation — WI-9.
- [ ] The `TransportError` enumeration contract test still passes and still fails when a route is removed.
- [ ] Thread-affinity measurement still recorded as a test.
- [ ] Wall-clock ceiling on the catalog path still asserted.

**This plan's own criteria**

- [ ] `breezy` console script resolves to `breezy.runtime.main:main`; `import breezy` prints nothing.
- [ ] Both blockers pinned by contract tests that fail when their guard is removed.
- [ ] A node builds with five actors, five distinct component ids, five distinct clocks, zero network I/O during build.
- [ ] Clean stop drains in-flight work within a bounded deadline or logs the abandonment count.
- [ ] Restart/resume proven across a real start/stop/start cycle against a fixture transport.
- [ ] The gap ledger detects a missing climate day, escalates as retention approaches, is idempotent, and survives a store round-trip.
- [ ] In-window backlog drain proven for a 48-hour and a 7-day simulated outage.
- [ ] Health snapshot written atomically each cycle; alerts fire on transition; a failing sink cannot take down collection.
- [ ] Runbook covers supervision, never-two-processes, never-staging-against-live, UA-trap clear, gap triage, shrink-to-NYC, fail-closed posture.
- [ ] Fixture-backed soak covering >= one simulated week with an induced outage and restart passes.
- [ ] A `revision_seq` increase on an already-resolved day is detected, persisted, and alerted [PR-D1].
- [ ] A condition already true at process start alerts on the first cycle [PR-D2].
- [ ] Configs carry a real `ComponentId`, not a `str` [PR-A1].
- [ ] Teardown runs `node.dispose()` -> `container.dispose()` -> `store.close()`, asserted by call order [PR-A6].
- [ ] No signal handler is installed by Breezy code [PR-P1].
- [ ] The shutdown drain is async and provably does not burn its timeout on a clean stop [PR-P2].
- [ ] Health snapshot is mode 0600 and contains no `user_agent_contact` [PR-S1, PR-S4].
- [ ] Webhook payload keys are within the declared allowlist [PR-S2].

**Explicitly NOT part of done:** no order was placed, no venue was authenticated, no live-venue gate was opened, no P&L moved.

---

## 8b. Small corrections carried from review

- **[PR-A7] `settings.catalog_io_workers` is dead config.** Both executors are hardcoded `max_workers=1` with a documented requirement that they stay 1 (`nws_actor.py:806-815`), yet settings expose a `PositiveInt` knob defaulting to 2 (`settings.py:297`). WI-5 has no home for it. Either delete the setting or assert it equals 1 — do not silently ignore it, which is how a future reader concludes the knob works.

---

## 9. Operator-only decisions

1. **Alert channel and endpoint**, and its credentials. Default until decided: `LoggingAlertSink` plus the health-snapshot file.
2. **Sign-off on the fail-closed availability posture** (`PHASE1_ACTOR_BRIEF.md:356-362`) — corrupt state permanently halts a station or all stations with no auto-recovery. The bot silently *not* trading is a real cost even though it is the safe direction.
3. **Confirmation of the five-site launch** (section 3 Decision A). This plan proceeds on five; the `BREEZY_SITES` retreat to NYC-only requires no code change.
4. **Where state and catalog live on disk**, and their backup policy.
5. **Any live-venue enablement.** Out of scope entirely.
