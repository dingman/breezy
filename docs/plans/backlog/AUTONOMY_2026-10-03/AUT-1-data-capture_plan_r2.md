# AUT-1 — Data capture: area plan, round 2

## 0. Header

| Field | Value |
|---|---|
| ID | AUT-1 |
| Title | Data capture: every decision, order, fill, mark and settlement for every family, joined on one `decision_id`, reconciled daily against independent sources, with recorder and feed stall self-heal |
| Round | r2 (2026-10-03). r1 (`AUT-1-data-capture_plan_r1.md`) is unchanged. Review consumed: `reviews/AUT-1-r1-merged.md` (C1–C19, final 76, NOT READY). |
| ARCH consumed | `reviews/snapshots/ARCH_rev4.md`, sha256 `175310117eec39b22fc8229788a7d6182c6395438db23ec65ceb78b964dd508e` (the sha scored in `reviews/ARCH-r4-merged.md`), **plus the W1–W16 deltas** of `reviews/ARCH-r4-merged.md`, treated as applied. The W-deltas that touch AUT-1 are W6, W9, W10, W11, W12 and W13. Names introduced by the on-disk Rev 5 (`AUTONOMY_ARCHITECTURE.md`, sha256 `5d2b75fa77e2c0abaaa478bd38d32e7e06ac98c8057ce50a5045f0dd0eff8403`) for W9 (`ALERT_OUTBOX_MAX`, `ALERT_DELIVERY_TIMEOUT_S`, the outbox worker) and W11 (`evidence/selfheal/<date>.json`) are adopted verbatim so the two documents do not diverge. Rev 5 was otherwise not re-scored here. |
| Code baseline | `feat/data-capture-and-risk` @ `4b8347a6`. Every `file:line` below was read at that sha, either through codegraph (`projectPath=/home/jon/breezy`) or by `/usr/bin/grep`/`sed` on the named file. |
| Current score | 2 |
| Target | 3 |
| Upstream | ARCH-0 (Wave 0: `persistence/autonomy/` schemas, the C4 writer, the C6 Protocols, `VetoReason`, `pins.py`); AUT-5a (`ResolvedFamily`, `RegistryWatchActor.drill_active`, the required `entry_veto` slot in `try_submit` (W10), sole owner of `app/trade.py` in Wave 1); AUT-6 (`deliver_with_proof`, the node alert outbox (W9), `restart_unit` with its durable counter (W11), the migration of `study_failure_notifier` to delivery proof, the detector catalogue, the intraday producer); AUT-2 (the canary producer and the `derived/canary/` store) |
| Downstream | AUT-2 (C1 records, the blob store, the pure join reader, `SettlementRecord`, tape marks); AUT-4 (depth and forecast preimages, `CAPTURE_INCOMPLETE` and tape-ingest admissibility); AUT-6 (`DetectorEvent` records, NODE_LOCAL detectors, HEALTH verdicts); AUT-5 (HEALTH verdicts and proposed policy-map rows) |

---

## 1. Goal state

### 1.1 README `AUT-1` score-3 criterion (verbatim)

> **Score-3 criterion.**
> - What must be captured, durably, for every family: every decision (including refusals and their reasons), intent, order, fill, cancel, position mark, settlement, the depth snapshot at decision time, and the forecast or model inputs with artefact sha.
> - Every record is schema-versioned and joinable on one decision id.
> - A daily completeness audit runs automatically and alerts on any gap.
> - A recorder hang or an empty feed is detected and self-healed with no human action.
>
> **Live proof:** 7 consecutive UTC days with 100% join completeness for every live fill, from decision to settlement, plus at least one detected and self-healed recorder or feed stall (an injected one is acceptable if no natural stall occurs).

It is bound by the README scale 3(a)–(f) and by the README live-proof window rule, quoted verbatim because C11 turns on it:

> A day counts toward any N-day live-proof window only if it has at least one real fill, or a clearly tagged synthetic canary fill that traverses the production path. Zero-fill days do not count, and the window extends. Every window also needs at least 5 real fills, and canary fills never count toward that or any statistic.

### 1.2 ARCH §10 "Area plan obligations", AUT-1 (verbatim, Rev 4 and Rev 5 identical)

> **AUT-1:** the `CaptureAdapter` call sites per composable kind; measured C1 volume per day; the `EntryVeto` record writer; the node-local observations behind `feed_stale`, `recorder_stale`, `capture_gap` (source, period, clear condition); the recorder and feed self-heal restart, naming each unit it adds to `SELF_HEAL_RESTARTABLE_UNITS`; the daily join audit.

| Obligation | Section |
|---|---|
| `CaptureAdapter` call sites | §3.3.4 |
| Measured C1 volume | §3.2 |
| `EntryVeto` writer | §3.3.4 (CS-2) |
| `feed_stale`, `recorder_stale`, `capture_gap` | §3.5 |
| Self-heal and units | §3.6 |
| Daily join audit | §3.7 |

### 1.3 Known facts, with the code check at `4b8347a6`

| Fact | Verified state | Where addressed |
|---|---|---|
| The recorder can sit "active" while capturing nothing. | **Partly fixed, still open.** GL-12 widened the connect fail-fast (`data.py:1101-1147`) and the empty-discovery retry exists (`data.py:1071-1099`). Open classes: a wedged loop, a writer alive but stalled, a non-fatal reconnect loop, MemoryHigh thrash (L-49). Nothing outside the process checks that bytes land. The feather writer flushes every `QUOTE_TAPE_FLUSH_INTERVAL_MS = 10_000` (`node_config.py:308`), so a healthy streaming instance grows on disk at that cadence. | §3.6 (heartbeat, `WRITER_STALL`, external watch, restart) |
| The NBP feed has no positive log line. | **Stale.** `NBM_NBP_PUBLISHED` and `FQ_VECTOR_COMPLETE` exist and appear in `breezy-trade-20261002T205521Z.log` (2 and 8 lines). The real gap is **absence detection**: `_check_stale_cycle` only logs (`nbm_quantile_actor.py:425-449`). `_submit` (`:340-353`) does not retain the `Future`, so a hung fetch cannot be cancelled. | §3.5.1, §3.5.2, §3.7 leg N |
| The exit study reports `no_taken_latch` for FQ. | Confirmed (`prereg_admission.py:476-499`, CRH latch keys only). | §3.4 join replaces latch attribution |
| No single `decision_id` join covers every family. | Confirmed. The FQ funnel holds counts only (`decision_funnel.py:52-96`); FQ submits with no tags (`strategy.py:680-688`). | §3.3, §3.4 |
| The FQ funnel is **per boot, cumulative, and keyed by boot day, not UTC day.** | New in r2. `FqDecisionFunnelActor.output_path` is `fq_funnel_<boot day>.jsonl` (`decision_funnel.py:143-147`); each row is a cumulative snapshot since this process started (`:170-180`); a second boot on the same day appends to the same file with a reset counter. The node relaunched three times on 10-02 (`breezy-trade-20261002T165039Z`, `…T200526Z`, `…T205521Z`). | §3.7 leg R segments funnel rows by boot |
| The node log carries per-record evidence. | New in r2. Each `SHADOW_DECISION` line carries `now_ns`, station, rung, side, instrument, kind and reason (`strategy.py:577-581`, `:700-709`; e.g. `'kind': 'TrySubmit', 'reason': 'submitted'` at 21:01:16Z 10-02). `OrderFilled` lines carry `client_order_id`, `venue_order_id` and `trade_id`. Line 46 of each log carries `TradingNode: instance_id: <uuid>`. In the 7 h log: 3 Take, 3 TrySubmit, 3 `OrderSubmitted`, 3 `OrderFilled`. The log is ~362 MB per 7 h, so ~1.2 GB a day; 63 trade logs are retained. | §3.7 legs R, F |
| The WS cap is 10 subscriptions per connection, shared (L-45). | Confirmed. | AUT-1 adds no venue subscription (§3.3.6) |
| Nautilus closes an idle socket after `idle_timeout_ms`. | Breezy configures **600 s** (`adapters/polymarket_us/config.py:293`). | Every silence horizon derives from the configured value (§3.5.1) |
| Study-unit `OnFailure` delivery is unproven. | New in r2. `study_failure_notifier.py:274` calls `emit_alert` (which swallows every failure, `health.py:479-504`) and returns 0 at `:277` whatever happened. | §3.6.4, §5.1 (AUT-6 dependency), §3.8 |
| `RuntimeMaxSec` does nothing on a oneshot. | New in r2. `man systemd.service` on the host (systemd 259): "this setting does not have any effect on Type=oneshot services … use TimeoutStartSec=". r1 set `RuntimeMaxSec` on oneshots. | §3.8 uses `TimeoutStartSec` |
| The ingest prints `extend_dedupe:` to stdout, into the `breezy-quote-tape-ingest` journal. | New in r2. `quote_tape_ingest_core.py:2228` prints `extend_dedupe_counters.summary_line()` (`quote_tape_salvage.py:296-302`): `chunks= filtered= unfiltered= by_type=<type>:<filtered>/<unfiltered>,… flat_root=<types or none>`. Observed at 04:15:40Z 10-03. `DepthTruncation` records are **expected** on thin markets (`data.py:1817-1821`, "depth capture is unaffected"). | §3.7 leg T |

---

## 2. L-1 null hypothesis and reuse

"WP0" marks a premise the WP0 characterisation test pins, with mutation evidence (L-33), **before** the slice relying on it starts (L-47).

| New component | Capability checked (file:line) | Verdict |
|---|---|---|
| Per-decision capture record | Nautilus `StreamingConfig` (rejected by ARCH C1 for the order process); FQ funnel counts (`decision_funnel.py:52-181`); CRH `OfferTape` (`crh/offer_tape.py:335-439`) | **Extend.** New writer on the `OfferTape` shape, adding fsync on order-path records, short-write detection and a loud cap. The funnel stays unedited and becomes an independent cross-check. |
| `decision_id` carrier on orders | Native `Order.tags`; exit prefixes (`persistence/exit_tags.py:37-48`); exec client tag loop compares exit prefixes only (`exec/client.py:746-749`, `:5375-5391`) | **Reuse native.** Add `DECISION_ID_TAG_PREFIX = "breezy:decision_id="` to `exit_tags.py`. The exec client is **not edited** (byte pin). WP0: the tag is absent from the wire body. |
| Exit decision ids (C7) | The four exit tags `exit_rule=`, `exit_position_id=`, `exit_family_id=`, `exit_client_order_id=` (`exit_tags.py`); `EXIT_RULE_TAG_PREFIX` on any tag is the sole "is exit" test | **Reuse native tags.** The exit id is a pure function of the four tag values (§3.3.1). No new carrier. |
| Order lifecycle capture | `ExecutionEngine` publishes `events.order.{strategy_id}` and `events.position.{strategy_id}` (nautilus 1.231.0); `Actor.msgbus.subscribe` | **Reuse native.** WP0: wildcard delivery. L-16: `publish_c` has no try/except, so every handler is catch-all. |
| Submit-time refusal for untagged or unlinked orders | Nautilus `RiskEngine` (immutable); exec client deny chain (byte-pinned); `Strategy.submit_order` | **Extend natively by subclassing.** `CaptureGuardedStrategy(Strategy)` overrides `submit_order` and calls `super()`. WP0 gates WP2 (C16): a Python override of the `cpdef` is dispatched for Python callers (`strategy.py:688`). |
| Depth snapshot at decision time | The node's own `OrderBookDepth10` (`parsing.py:851-895`); the recorder tape (separate process, L-20) | **New, minimal.** Content-addressed preimage of the node's Depth10 row, hashed **only when a record is written** (C6). |
| Forecast inputs per decision | `ForecastQuantileState.value_at` (`forecast_state.py:306-315`) | **New, minimal.** Content-addressed preimage per distinct vector, about 12 a day. |
| Per-instrument market-data freshness (C13) | Data-client counters (`data.py:865-1038`), adapter-only; Nautilus `data.book.depth.*` / `data.quotes.*` topics | **Reuse native.** Passive topic subscription, one `last_frame_ns` per subscribed instrument. WP0: topic strings. |
| NBP freshness and hang recovery | `_check_stale_cycle` (`:425-449`), `latest_available_cycle_ns` (`:382-400`), `_submit` (`:340-353`) | **Extend.** Detector reads state; the actor retains the `Future` and gains a hang reset. |
| Recorder liveness and writer stall | systemd `Restart=always` (blind to a zombie); `QuoteTapeDiskMonitor` (disk only); feather flush cadence 10 s (`node_config.py:308`) | **New:** a heartbeat file from the data client (opt-in) plus an external watch that compares counters with on-disk bytes. Neither systemd nor Nautilus offers a "bytes are landing" probe. |
| Watch liveness (C18) | `breezy-autonomy-deadman` (AUT-5; engine heartbeat only); the AUT-6 off-host canary (daily) | **New, minimal:** a second timer that watches the watch, and the watch watches it back (§3.6.4). The off-host canary remains the backstop for a dead user manager. |
| Restarting units | `breezy-quote-tape-rotate.service:55` uses `systemctl --user try-restart`; AUT-6 `restart_unit` plus `SELF_HEAL_RESTARTABLE_UNITS` | **Consume AUT-6.** AUT-1 writes no restart code. |
| Fill and order census for the audit | `DurableFillRecord` with `client_order_id` (`exec/client.py:949-976`); `FILL_KEY_PREFIX` (`:408`), `FILL_BY_DAY_KEY_PREFIX` (`:429`, a candidate set; `ts_event` is the authority), `VENUE_ORDER_ID_KEY_PREFIX` (`:404`, venue id to `client_order_id`, written on accept, `:4570-4585`), `RESOLVER_CONTEXT_KEY_PREFIX` (`:454`); read-only `SELECT key, value FROM state` over `mode=ro` (`fill_time_count.py:94,122`) | **Reuse.** No exec-store write and no new key. `analysis` sits above `adapters` in the layer contract (`pyproject.toml` `[tool.importlinter]`), so the audit may import these constants. `persistence/autonomy/capture_reader.py` never does (W6): it takes fills as plain values. |
| Independent denominators (C1) | Node log `SHADOW_DECISION`, `OrderSubmitted`, `OrderFilled`, `FQ_VECTOR_COMPLETE`, `NBM_NBP_PUBLISHED` lines; the funnel JSONL | **Reuse, read-only.** A streaming fixed-string filter, O(matches) memory. |
| Node-independent marks (C1) | Recorder tape catalog Depth10 after the 12:15Z ingest; exec-store fills for net position | **Reuse.** The audit writes `PositionMark(source="tape")`. |
| Settlement | `read_climate_day_including_corrections` (`persistence/catalog.py:637`) | **Reuse.** |
| Build identity | `resolve_build_revision` (`runtime/build_sha.py:147-190`); kernel `instance_id` | **Reuse.** |
| Retention | `scripts/ops/decisions_retention.py:77-80` | **Extend by one alternation** (L-12). |
| Alerts with delivery proof | AUT-6 `deliver_with_proof`; node outbox (W9; Rev 5 `ALERT_OUTBOX_MAX`); `emit_alert` swallows (G25) | **Consume AUT-6** for every CRITICAL. Node code only enqueues. |

---
## 3. Design

### 3.1 Module map (layering checked against `pyproject.toml` `[tool.importlinter]`: app > analysis > strategy > runtime > adapters > ingest > persistence|registry|normalize > settlement > domain)

| Module | Layer | New or edit | Purpose |
|---|---|---|---|
| `src/breezy/persistence/autonomy/capture_ids.py` | persistence | new | `compute_decision_id`, `compute_exit_decision_id`, `depth_ref_of`, `forecast_input_sha256_of`; no Nautilus import |
| `src/breezy/persistence/autonomy/capture_writer.py` | persistence | new | `CaptureWriter`, `CaptureIdentity`, `CaptureWriterHealth`, `mark_capture_incomplete`, `CaptureWriteFailure` |
| `src/breezy/persistence/autonomy/capture_blobs.py` | persistence | new | `BlobStore` |
| `src/breezy/persistence/autonomy/capture_reader.py` | persistence | new | `read_capture_day`, `join_fills_to_decisions` (pure; fills passed in as plain values, W6) |
| `src/breezy/persistence/autonomy/capture_watch_state.py` | persistence | new | `capture_watch/v1`, `recorder_heartbeat/v1`, `capture_watchdog/v1` schemas and the single-read loader |
| `src/breezy/persistence/exit_tags.py` | persistence | edit | add `DECISION_ID_TAG_PREFIX` (L-12 widening of `__all__`) |
| `src/breezy/strategy/autonomy_capture/guarded_strategy.py` | strategy | new | `CaptureGuardedStrategy(Strategy)` |
| `src/breezy/strategy/autonomy_capture/lifecycle_actor.py` | strategy | new | `CaptureLifecycleActor(Actor)` |
| `src/breezy/strategy/autonomy_capture/node_observations.py` | strategy | new | NODE_LOCAL detectors `capture_writer_health`, `md_feed_freshness`, `recorder_liveness` |
| `src/breezy/strategy/forecast_quantile_ladder/capture_adapter.py` | strategy | new | `FqCaptureAdapter` plus the NODE_LOCAL detector `nbp_feed_freshness` |
| `src/breezy/strategy/forecast_quantile_ladder/strategy.py` | strategy | edit | base class becomes `CaptureGuardedStrategy`; edits in `_emit_shadow_decision`, `_emit_decision_outcome`, `_maybe_submit`, `on_order_book_depth` only. **`try_submit` belongs to AUT-5a.** |
| `src/breezy/ingest/nbm_quantile_actor.py` | ingest | edit | retain the `Future` in `_submit`; poll-hang reset |
| `src/breezy/adapters/polymarket_us/data.py`, `config.py` | adapters | edit | opt-in `heartbeat_path`; `_write_heartbeat`; `depths_published` counter if absent |
| `src/breezy/runtime/node_config.py` | runtime | edit | `build_quote_tape_node_config` sets `heartbeat_path`; the trade-node config never does |
| `src/breezy/runtime/capture_watch.py`, `capture_watch_cli.py` | runtime | new | recorder and NWS-ingest probe, classification, self-heal through AUT-6, state file |
| `src/breezy/runtime/capture_watchdog.py`, `capture_watchdog_cli.py` | runtime | new | watch-of-the-watch and audit dead-man (C2, C18) |
| `src/breezy/runtime/capture_stall_drill_cli.py` | runtime | new | weekly injected recorder stall |
| `src/breezy/analysis/capture_audit.py`, `capture_audit_cli.py` | analysis | new | daily audit: join, reconciliation, census, tape and NBP legs, `SettlementRecord` and tape-mark writer, HEALTH verdicts |
| `src/breezy/analysis/capture_node_log.py` | analysis | new | streaming parser of node log marker lines (fixed-string prefilter, strict regex per marker) |
| `src/breezy/analysis/capture_live_proof.py`, `_cli.py` | analysis | new | 7-day window roll-up |
| `src/breezy/app/trade.py` | app | one hunk, Wave 1b, after AUT-5a merges | construct identity, writer, adapter and actor in `_compose_forecast_quantile_ladder` (`:676-850`); append the actor to `extra_actors` (`:823`) |
| `deploy/systemd/breezy-capture-{watch,watchdog,audit,stall-drill,stall-drill-guard}.{service,timer}`, `breezy-capture-live-proof.service` | deploy | new | units (§3.8) |
| `scripts/ops/decisions_retention.py` | scripts | edit | widen the regex to `capture_[a-z0-9_]+(\.offline)?` |

**Entry points.** `/home/jon/breezy/.venv/bin/python3 -m <module>`. No `[project.scripts]` entry: a console script needs a reinstall into the shared venv, which is forbidden (L-51).

### 3.2 C1 volume (measured, obligation 2)

- **Measured** from `breezy-trade-20261002T205521Z.log` (20:55Z 10-02 to 03:57Z 10-03, streaming parse of `SHADOW_DECISION`): 973,921 FQ evaluations across 24 `(station, climate_day, rung_id, side)` keys; the on-change rule gives **59 records**. Funnel for UTC day 10-01: 3,288,397 evaluations, 2 Take, 2 TrySubmit.
- **Projection (cap sizing only):** about 250 on-change records a day; about 8 records per order at 2–5 orders a day; DetectorEvents on transitions only (< 50); about 50 tape marks; **under 450 records, about 0.45 MB a day**. Blobs under 0.5 MB a day.
- **Cap:** `CAPTURE_MAX_BYTES_PER_FAMILY_DAY = 64 MiB` (> 140× projection). WP0 re-measures a full UTC day; above 5,000 records the cap is revisited in a reviewed commit before WP2.
- **Availability cost of a cap hit (C15).** `health.ok=False` refuses every entry of that family until the next UTC-day file opens at 00:00Z. At the measured cadence that forfeits at most the remaining entries of one UTC day (≤ 3 takes). Exits are never refused. Only a runaway writer bug can reach 64 MiB; the refusal is the intended fail-closed outcome.

### 3.3 Capture core, call sites, guard

#### 3.3.1 Identity and ids (`capture_ids.py`)

- `compute_decision_id(family_id, manifest_sha256, artefact_sha256, station, climate_day, rung_id, side, eval_ns) -> str`: first 32 hex of sha256 of `"|".join([...])`, exactly the C1 field order. Recomputed only from stored fields.
- `compute_exit_decision_id(family_id, exit_rule, exit_position_id, exit_client_order_id) -> str` (C7): first 32 hex of sha256 of `"exit/v1|" + "|".join([...])`, the four values read from the order's exit tags. Deterministic, so an exit order resubmitted by the exit seam after a restart maps to the same id, and recomputation needs only the tags.
- `depth_ref_of(instrument_id, ts_event, bids, asks)`: sha256 of `"depth10/v1|…"` over size > 0 levels; `ts_init` excluded so node and recorder rows hash equal.
- `forecast_input_sha256_of(vector, station)`: sha256 of canonical JSON of the `ForecastQuantileVector` fields (`forecast_state.py:282-294`).

#### 3.3.2 Blob store (`capture_blobs.py`)

Root `~/.local/share/breezy/derived/capture/blobs/{depth,forecast_input}/<sha[:2]>/<sha>.json`; dirs 0700, files 0444; `mkstemp` + `os.replace`; existing sha is a no-op; single-read rule on reads. **Why:** C1 names `depth_ref` and `forecast_input_sha256` with no preimage store (§11 item 4).

#### 3.3.3 Writer (`capture_writer.py`)

- `CaptureIdentity` (frozen): `family_id`, `manifest_sha256`, `artefact_sha256`, `node_boot_id` (kernel `instance_id`), `build_sha`, `registry_seq` (from `ResolvedFamily`, else 0; after cutover the audit fails any 0).
- `drill` is read per record from `RegistryWatchActor.drill_active(now_ns)` (Z2 fold). W12: drill records are written, audited and joined exactly like live ones.
- `CaptureWriter(identity, decisions_dir, blob_store, *, source: Literal["live","canary"], clock_ns, evidence_dir, node_log)`. `node_log` is the Nautilus `Logger` of the owning component; the writer never configures a stdlib logger (L-27, L-30).
  - Live path `<decisions_dir>/capture_<family_id>_<UTC-date>.jsonl`, `decisions_dir = catalog_root.parent / "decisions"` (`trade.py:774`). Canary path `<decisions_dir>/canary/…` (Z14).
- Methods return `bool` (written durably): `would_write_decision(key, kind, reason) -> bool` (the cheap on-change test, C6), `write_decision`, `write_order_link(rec, *, fsync=True)`, `write_lifecycle`, `write_position_mark`, `write_detector_event`, `put_blob`.
- **One write path.** `json.dumps(sort_keys=True) + "\n"`, encoded once, one `os.write` to an `O_APPEND|O_WRONLY|O_CREAT` 0600 descriptor. **A short write (`n != len(buf)`) is a failure (C4)**: counted, never retried in place (a partial line is already on disk; the reader refuses it and the audit counts it).
- `os.fsync` on Take, TrySubmit, EntryVeto, Exit, OrderLink, LifecycleEvent and PositionMark; flush only on on-change refusals and DetectorEvents.
- **Fsync latency (C6).** A fixed ring of the last 256 fsync durations. If its p99 exceeds `CAPTURE_FSYNC_P99_BUDGET_MS` (a literal set in WP0 at max(10 ms, 3 × the measured host p99), WP2 benchmark), `capture_writer_health` emits `DISAGREE` with detail `fsync_slow` and a WARNING. Latency alone never vetoes: a slow disk delays an IOC by milliseconds and is not a capture gap.
- **UTC rollover (C15).** At the first write after 00:00Z the writer opens the next day's file. An open failure is a write failure (below), never a silent fallback to the old file.
- The node is the only writer of the live file (L-50); relaunches are sequential.
- On-change map `dict[(station, climate_day, rung_id, side), (kind, reason)]`, evicted on the 60 s tick for `climate_day < today_utc − 1` (`test_on_change_map_is_bounded`).
- **Failure path (C4, not best-effort).** On a write error, short write, open failure or byte cap:
  1. increment `write_errors`, `short_writes` or `capped_rows` (unbounded ints); set `health.ok=False`;
  2. log `CAPTURE_WRITE_FAILED family=<id> kind=<k> cause=<c>` (or `CAPTURE_BYTE_CAP`) through the Nautilus logger, which is the handler the node log always has;
  3. enqueue a CRITICAL to the node alert outbox (W9; never blocks);
  4. write the marker `<decisions_dir>/capture_<family_id>_<date>.INCOMPLETE` **and** append `{family_id, date, cause, first_ns}` to `~/.local/share/breezy/evidence/capture/incomplete_<date>.jsonl` (a second filesystem location, so one failing directory does not hide the other);
  5. the writer never raises into a Nautilus handler (L-16).
  - **The audit does not depend on any of 2–4 succeeding.** The day fails on the independent reconciliation in §3.7 (leg R: a node-log Take or TrySubmit line with no capture record), so a writer that cannot write anything, including its markers, still fails the day (`test_marker_write_failure_still_fails_day`). Markers and the log line are corroboration, and their absence proves nothing (L-30).
- **Positive control.** At `on_start` and at each 60 s tick while `health.ok=False`, append and fsync `DetectorEvent(capture_writer_health, AGREE)`. Only that success clears `health.ok`.

#### 3.3.4 `CaptureAdapter` call sites per composable kind (obligation 1)

**Composable kinds today.** Only `forecast_quantile_ladder` has full plug-ins (`LIVE_GATE_ROUTED_KINDS`); `current_rung_hold`, `continuous_rung_hold`, `forecast_ladder` carry `RefusingPlugin`. AUT-1 wires one kind; a future kind gets its adapter in the change that admits it, and the gate test in §3.3.5 makes that unavoidable.

`FqCaptureAdapter` call sites in `forecast_quantile_ladder/strategy.py`:

| # | Call site | Change |
|---|---|---|
| CS-1 | `evaluate_snapshot` → `_emit_shadow_decision(...)` (`:564-581`) | `_emit_shadow_decision` calls `self._capture.on_decision(decision, ctx)` after the existing sink and log line. **Order of work (C6):** (1) build the key and call `writer.would_write_decision(key, kind, reason)`, a dict lookup; (2) only if it returns True (any `Take`, or a changed non-Take), compute `decision_id`, hash the depth row and the forecast vector, put both blobs and write the record. The ~39 evaluations a second that change nothing cost one dict lookup each. `ctx` carries `eval_ns = now_ns`, the strategy's `_last_depth[instrument_id]` and the vector already used by the decision (captured once, never re-read). Returns the `decision_id` or None. |
| CS-2 | `_emit_decision_outcome(take, refusal)` (`:690-709`) | Gains `decision_id`. The `now_ns` placed in the shadow line (`:701`) is passed to the adapter and stored as the record's `eval_ns`, so the node-log line and the capture record join exactly (§3.7 leg R). A refusal in the closed `VetoReason` set writes `DecisionRecord(kind="EntryVeto")`, on-change per key — **the `EntryVeto` writer**. Otherwise `kind="TrySubmit"`, always, fsynced. |
| CS-3 | `_maybe_submit` → `order_factory.limit(...)` (`:680-688`) | Gains keyword `decision_id`; passes `tags=[f"{DECISION_ID_TAG_PREFIX}{decision_id}"]`; then `self.submit_order(order)`, intercepted by the guard. |
| CS-4 | `on_order_book_depth` (`:713-729`) | Stores `self._last_depth[depth.instrument_id] = depth` before `_safe_evaluate` (bounded by subscribed instruments). A `Take` with no depth entry is refused at CS-2 as `capture_gap`. |
| CS-5 | `shadow_only=True` branch (`:659-665`) | CS-1 already captured the Take; no order. |

#### 3.3.5 Guard (`guarded_strategy.py`)

`class CaptureGuardedStrategy(Strategy)`:

- **Construction (C8, mirrors W10).** `__init__(self, config, *, capture_writer: CaptureWriter, alert_outbox: AlertOutbox, …)`: both keyword-only and non-Optional. `None` or a wrong type raises `TypeError` in `__init__`, which runs inside `_compose_forecast_quantile_ladder` before `node.run()`, so the boot fails closed with a non-zero exit. The FQ composer has no default for either.
- `submit_order(self, order, position_id=None, client_id=None, params=None)`:
  1. **Exits (C7).** If any tag starts with `EXIT_RULE_TAG_PREFIX`: read the four exit tags. If all four are present, compute `compute_exit_decision_id(...)`, write `DecisionRecord(kind="Exit", reason=<exit_rule>, instrument_id, station/climate_day/rung_id/side from the instrument, depth_ref of the last depth or null)` and `OrderLink(client_order_id)` (both fsynced), then `super().submit_order(...)`. **A legitimate exit raises no CRITICAL and no DetectorEvent.** If an exit tag is missing or a capture write fails, the exit still goes out (exits reduce risk), and the guard writes `DetectorEvent(capture_writer_health, DISAGREE, detail=exit_capture_gap)` and enqueues a CRITICAL. The `Exit` kind is an L-12 widening of C1 (§11 N1); FQ has no exit today (G17), so the live proof does not wait on it.
  2. Exactly one `breezy:decision_id=` tag with 32 lowercase hex characters is required. Zero, two or more, uppercase or wrong length → refuse `capture_untagged`: no `super()` call, so the order never reaches the cache (`Strategy.submit_order` is what adds it); log `CAPTURE_REFUSED reason=capture_untagged client_order_id=<id>`; write `DecisionRecord(kind="EntryVeto", reason="capture_untagged")` for the tag's id if parseable, else for a derived id `compute_decision_id(…, eval_ns=now)` from the instrument; enqueue CRITICAL.
  3. `self._capture_writer.health.ok` False → refuse `capture_gap` (same logging and record).
  4. `write_order_link(OrderLink(client_order_id, venue_order_id_sha256=None, intent_id=None), fsync=True)`; False → refuse `capture_gap`.
  5. `super().submit_order(...)`.
- **Hot-path budget (C6, W9).** Steps 1–4 do one tag scan, at most two fsynced appends and no network call. CRITICAL delivery is an outbox enqueue (`AlertOutbox.offer(payload) -> bool`, non-blocking; AUT-6 owns the worker and `ALERT_DELIVERY_TIMEOUT_S`). `test_guarded_submit_latency_independent_of_webhook` stubs the webhook to block 30 s and asserts the refusal path returns within the fsync budget.
- `test_every_full_plugin_kind_strategy_subclasses_capture_guard` walks `NODE_PLUGINS`: every non-`RefusingPlugin` kind's strategy class subclasses `CaptureGuardedStrategy`, so **no family can send without capture, by construction** (README 3(b)).
- `capture_untagged` must be a member of the closed `VetoReason` enum. C1 names it; the C5 enum (ARCH Rev 4 :476) omits it (§11 N2). `test_capture_untagged_is_a_veto_reason` pins it.
- `intent_id` stays null at submit (byte-pinned exec client; §11 item 3).

#### 3.3.6 Lifecycle, marks and per-instrument freshness (`lifecycle_actor.py`)

- `on_start`: `msgbus.subscribe("events.order.*", …)`, `msgbus.subscribe("events.position.*", …)`, the passive data topics (§3.5.1), and `clock.set_timer("aut1-capture-health", 60 s)`. **No `subscribe_*` command** (`test_capture_actor_issues_no_venue_subscription`, L-45).
- `_on_order_event`, catch-all (L-16): `OrderAccepted` → second `OrderLink` with `venue_order_id_sha256`; every order event → `LifecycleEvent` with str-decimals; `decision_id` from the cached order's tags (entry tag, or the exit id recomputed from the exit tags). An order with neither (not reachable through the guard, so only a non-guarded strategy) records an empty id plus a DetectorEvent and a CRITICAL.
- `_on_position_event` → `PositionMark(source="node")`, venue sign convention (L-44: a NO holding is negative on the base slug).
- Data-topic handler: `self._last_frame_ns[instrument_id] = clock.timestamp_ns()`; the dict is keyed only by instruments the strategies subscribed (read from the strategies' `_instrument_context`), so a stray topic message for another instrument is ignored, and size is bounded.
- The 60 s timer: evict, positive control, evaluate the NODE_LOCAL detectors, write DetectorEvents on transitions. A raise in a `LiveClock` callback is silently discarded (L-16), so the timer body is catch-all **and** every detector also checks staleness at call time (§3.5).
- The node touches no exec-store key (`test_capture_modules_never_import_exec_store`, AST, Z16).

### 3.4 The join (C1 invariants (i)–(iii))

```
DecisionRecord(Take) ─decision_id─► DecisionRecord(TrySubmit, submitted)
     └─decision_id─► OrderLink(pre-submit, client_order_id) ─client_order_id─►
          exec store fill/<voi> (DurableFillRecord.client_order_id)  ◄─ authoritative fill
          exec store venue_id/<voi> → client_order_id               ◄─ authoritative "venue accepted"
          exec store resolver/<intent_id> (context.client_order_id)  ◄─ AMBIGUOUS path
          LifecycleEvent(terminal, client_order_id); node-log OrderSubmitted/OrderFilled lines
          PositionMark(node | tape)
     └─(station, climate_day)─► SettlementRecord
     └─depth_ref ─► blob     └─forecast_input_sha256 ─► blob     └─artefact_sha256 ─► artefact bytes
DecisionRecord(Exit) ─decision_id = exit id─► OrderLink ─► (same order legs)
```

- The fill side is the exec store, so a resolver fill recorded later or by another process still joins.
- **Order classifications** (C10): `filled`; `terminal_unfilled` (EXPIRED, CANCELED, REJECTED, DENIED); `resolver` (a resolver context names the `client_order_id`); **`never_submitted`**: an OrderLink exists, but no `venue_id` row, no resolver context, no LifecycleEvent and no node-log order line names that `client_order_id`, **and** its `node_boot_id` boot has ended (a later boot's `instance_id` line exists, or the log stops before the next event). This is the crash between the fsynced link (§3.3.5 step 4) and `super().submit_order`. It is INFO, never a FAIL, because nothing reached the venue. While the boot is still running, the order is `order_pending`, which keeps the day INCONCLUSIVE rather than FAIL.
- `capture_reader.join_fills_to_decisions(capture_days, fills) -> tuple[JoinedFill | JoinGap, ...]` is pure; AUT-2 consumes it.

### 3.5 Node-local observations (obligation 4)

All are C6 `Detector(kind=NODE_LOCAL)`, action fixed as `ENTRY_VETO`, composed by AUT-5a's required `entry_veto(instrument_id)` slot (W10), listed in AUT-6's catalogue. Every veto auto-clears, writes a C1 `EntryVeto` record when it refuses a take, a `DetectorEvent` on each transition, no registry row and no budget (`test_transient_capture_veto_writes_no_transition`). W12: detectors count drill fills and records like live ones.

**Fail-closed start and staleness (Z6 analogue).** Each starts in veto until its first good observation, and vetoes at call time if its last evaluation is older than `CAPTURE_OBS_MAX_AGE_S = 180` (= `WATCH_TICK_STALE_S`).

#### 3.5.1 `feed_stale`

| Detector | Source | Period | Trigger | Clear |
|---|---|---|---|---|
| `md_feed_freshness` (C13) | Passive `msgbus` subscriptions to the Depth10 and quote topics (WP0 pins the 1.231.0 topic strings); `_last_frame_ns[instrument]` | 60 s tick and call time | **Per instrument:** `entry_veto(i)` returns `feed_stale` when `now − _last_frame_ns[i] > MD_SILENCE_S`, `MD_SILENCE_S = max(900, ws_idle_timeout_secs + 300)` (900 s at the configured 600 s), raised by WP0 if the measured per-instrument active-hours p99.9 × 1.5 is larger. **Venue-wide:** if the fraction of subscribed instruments past `MD_SILENCE_S` exceeds `MD_SILENT_FRACTION_MAX = 0.5` (a literal), every instrument vetoes, because a mostly silent feed means the connection, not the market, is the problem. An instrument never seen since subscription counts as silent. | The next frame on that instrument; the venue-wide veto clears when the silent fraction is at or below the limit |
| `nbp_feed_freshness` (FQ adapter) | `ForecastQuantileState.value_at(now)` per traded station; `latest_available_cycle_ns(now)` | 60 s tick | `missed` = configured cycles (`DEFAULT_NBM_QUANTILE_CYCLE_HOURS = (1, 13, 19)`, `nbm_quantile_actor.py:122`) after the newest complete visible cycle whose `cycle_ns + stale_deadline_seconds` (3 h, `:137`) has passed. `missed ≥ 1` → CRITICAL `NBP_CYCLE_MISSED`, no veto. `missed ≥ 2`, or no complete vector for a station with subscribed instruments → veto. A bulletin-drift latch counts as missed. | A newer complete cycle |

#### 3.5.2 NBP self-heal (in node; the trade node is never restarted)

- `_submit` retains the `concurrent.futures.Future` from `run_coroutine_threadsafe` (`:348`) as `self._poll_future`, with its submit time.
- In `on_cycle_timer`, if the retained future is not done after `NBP_POLL_HANG_S` (≥ 2 × the `BulletinFetcher` HTTP timeout pinned in WP0; default 600): `future.cancel()`, increment `counters["poll_hang_reset"]`, log `NBM_NBP_POLL_RESET cycle_ns=<n>`, submit a fresh `poll_once()`.
- A reset followed by `FQ_VECTOR_COMPLETE` for the missed cycle is a **self-healed feed stall**, journaled to `evidence/capture/self_heal_<date>.jsonl` (`{unit:"in-node:nbm_quantile_actor", detected_ns, action:"poll_reset", healed_ns, injected:false}`) and alerted INFO.

#### 3.5.3 `capture_gap`

| Source | Period | Trigger | Clear |
|---|---|---|---|
| `CaptureWriter.health` (`write_errors`, `short_writes`, `capped_rows`, `last_fsync_ok_ns`) | Every write; 60 s tick; call time | Any failed or short durable write, open failure or byte cap since the last positive control | The next fsynced positive-control `DetectorEvent(AGREE)`. A cap holds until the next UTC-day file; the day stays INCOMPLETE. |

#### 3.5.4 `recorder_stale`

| Source | Period | Trigger | Clear |
|---|---|---|---|
| `~/.local/share/breezy/health/capture_watch-polymarket_us.json` (`capture_watch/v1`), single-read (`O_NOFOLLOW`, 4 KiB cap, exact-set schema), on the Z16 single-read list | 60 s | `recorder.state ∈ {UNHEALED, INACTIVE}`; or `written_at_ns` older than 900 s; or missing, oversize or unparseable | A verified read with `state ∈ {OK, HEALING}` and fresh `written_at_ns` |

The recorder vetoes entries only once self-heal has failed: AUT-4 needs recorder tape around live fills (ARCH C4, Y12). Stalls that heal within about 15 min never veto. `permit_lapsed` is AUT-6's.

### 3.6 Recorder and feed self-heal (obligation 5)

#### 3.6.1 Recorder heartbeat (in the recorder process, opt-in)

- `PolymarketUSDataClientConfig.heartbeat_path: str | None = None`; only `build_quote_tape_node_config` (`node_config.py:485-622`) sets it, to `~/.local/share/breezy/health/recorder-polymarket_us.json`. `test_trade_node_config_has_no_heartbeat_path`.
- `_write_heartbeat(phase)`: atomic (`mkstemp` + `os.replace`, 0600) `recorder_heartbeat/v1` = `{schema, instance_id (data.py _recorder_instance_id, :777), pid, phase ∈ {DISCOVERING, STREAMING, SAFE_MODE}, written_at_ns, discovered_slugs, subscribed, quotes_published, depths_published, trades_published, tape_gaps, is_tape_gap_open, safe_mode}`, rate-limited to once per 30 s, O(1).
- Call sites: each empty-discovery retry iteration (`data.py:1082-1099`, `DISCOVERING`); each `sample_feed_health` (`:1960-2003`, `STREAMING` or `SAFE_MODE`).
- A heartbeat write failure is counted and logged once, never raised.

#### 3.6.2 `breezy-capture-watch` (oneshot, every 5 min, own lock)

`capture_watch.classify_recorder(hb, unit_active, disk, now, prev) -> RecorderState`. Every threshold is a literal in `capture_watch.py`; the WP0-measured ones carry their evidence file in a comment.

| State | Rule |
|---|---|
| `INACTIVE` | Unit not active (`systemctl --user is-active`, argv list, read-only). Never started by the watch. CRITICAL. |
| `HUNG` | Unit active and heartbeat missing or older than `HB_STALE_S = 180`; or phase `DISCOVERING` longer than `empty_discovery_retry_secs + 300`; or `SAFE_MODE` longer than 300 s. **Not gated by hour**: the heartbeat is written whether or not the market is active. |
| `STALLED` | Phase `STREAMING`, `discovered_slugs > 0`, and `quotes + depths + trades` unchanged across probes spanning `STREAM_SILENCE_S`, **and** the on-disk byte total unchanged over the same span. `STREAM_SILENCE_S = max(900, ws_idle_timeout_secs + 300)` inside `ACTIVE_HOURS_UTC`, and `QUIET_HOURS_MULTIPLIER = 4` times that outside them (C9). `ACTIVE_HOURS_UTC` is a literal tuple from WP0: the UTC hours in which at least 99% of 5-minute bins over the last 14 tape days carried at least one frame. |
| `WRITER_STALL` (C3) | Phase `STREAMING`, counters rose by at least `WRITER_STALL_MIN_EVENTS = 50` across probes spanning `WRITER_STALL_S`, **and** the on-disk byte total did not grow over the same span. `WRITER_STALL_S = max(120, 6 × the measured p99.9 inter-growth interval)`; WP0 measures the growth cadence of `live/<instance>/` under the 10 s flush (`node_config.py:308`). Not gated by hour: the precondition (counters rising) already proves data is flowing. |
| `OK` | Otherwise. A legitimately empty listing (phase `DISCOVERING` within budget, or `discovered_slugs == 0`) is OK, which avoids restart loops in the 09:00–09:45Z listing hole. |
| `HEALING` / `UNHEALED` | Self-heal states. |

- **On-disk byte total.** The sum of `st_size` over regular, non-empty files under `<catalog_root>/live/<hb.instance_id>/` (epoch `stat`, never `find -newermt`; `lstat`, symlinks skipped). The 00:00Z `SCHEDULED_DATES` file rotation (`node_config.py:400-403`) opens a new file in the same directory, so the total stays monotonic across it (`test_midnight_file_rotation_is_not_writer_stall`).
- **Rotation grace.** A changed `instance_id` younger than 600 s never heals (covers the 09:00Z rotate and systemd restarts).
- **Self-heal.** `HUNG`, `STALLED` or `WRITER_STALL` on two consecutive probes at least 5 min apart:
  1. AUT-6 `restart_unit("breezy-quote-tape.service", cause=<state>)`. It enforces the allowlist and `SELF_HEAL_MAX_RESTARTS_PER_UNIT_PER_DAY` with the **durable** counter `evidence/selfheal/<date>.json` (W11), so a watch process restart cannot reset the cap (C12).
  2. `HEALING`; confirm within 2 probes: new `instance_id`, phase `STREAMING` (or legitimately `DISCOVERING`), counters rising **and** bytes growing.
  3. Success: append `HEALED` to `evidence/capture/self_heal_<date>.jsonl` (`{unit, cause, detected_ns, restarted_ns, healed_ns, injected, decided_by:"capture_watch"}`), C4 `HEALTH` `recorder_self_heal` PASS, INFO through `deliver_with_proof`.
  4. Failure: a second restart while the cap allows. At the cap: `UNHEALED`, CRITICAL, `HEALTH` FAIL, node `recorder_stale` veto.
- **Restart cap and the trading day (C9).** `SELF_HEAL_MAX_RESTARTS_PER_UNIT_PER_DAY` is at most 3 (ARCH §4.5; r1's proposed 4 exceeded the ceiling and is corrected to **3**). AUT-1 requires the durable counter's `<date>` to be the **trading day** `[16:45Z, next 16:45Z)`, so an overnight exhaustion resets at 16:45Z, before the 16:50Z LAUNCH. The count per rolling 24 h stays ≤ 3. This is a parameter of AUT-6's `restart_unit` (§5.1, §11 N5).
- **Restart verb.** ARCH §4.5 pins the argv `["systemctl","--user","restart",unit]`. AUT-1 never calls it on an `INACTIVE` unit, but a stop issued between the probe and the call would be undone by `restart`. AUT-1 asks for `try-restart`, as `breezy-quote-tape-rotate.service:55` already uses (§11 N3). Until ARCH answers, AUT-1 re-checks `is-active` immediately before calling `restart_unit` and skips if inactive; the race left is under a second.
- **SIGSTOP and clean stop.** WP0 pins that systemd 259 sends `SIGCONT` after `KillSignal=SIGTERM` (`breezy-quote-tape.service:145`), so a stopped recorder closes its feather file cleanly. Never SIGKILL. **Fallback if refuted:** a reviewed unit-file commit adds `ExecStop=/bin/kill -CONT $MAINPID`. The bot never edits unit files.
- **NWS ingest.** Read `health-polymarket_us.<CITY>.json` (`snapshot_at_ns`, schema 2). `HUNG` if `breezy-nws-ingest.service` is active and the newest `snapshot_at_ns` is older than 900 s → same restart, confirm and journal steps. `gate_state != OPEN` for more than 2 h → CRITICAL only.
- **Watchdog stamp.** The watch reads `health/capture_watchdog.json` (§3.6.4); older than 45 min or missing → CRITICAL `CAPTURE_WATCHDOG_STALE` through `deliver_with_proof`.
- **State file.** `capture_watch-polymarket_us.json` (`capture_watch/v1`): `{schema, written_at_ns, recorder:{state, cause, since_ns, instance_id, restarts_today}, nws_ingest:{state, since_ns, restarts_today}}`, atomic 0600. `restarts_today` is read from AUT-6's durable counter, never kept in memory.
- **Units added to `SELF_HEAL_RESTARTABLE_UNITS`**: `breezy-quote-tape.service`, `breezy-nws-ingest.service`. Neither is the supervisor, the trade node or the engine.

#### 3.6.3 Activation without a hand restart

The recorder loads the heartbeat code at the **next daily 09:00Z rotate** (`breezy-quote-tape-rotate.timer`, `try-restart`). No agent restarts it. r1's manual restart inside the listing hole is withdrawn, because that hole is exactly where the zombie occurs (memory `recorder-hangs-disconnected`).

#### 3.6.4 `breezy-capture-watchdog` (C2 dead-man, C18 watch liveness)

A oneshot every 15 min, own lock `health/capture-watchdog.lock`, no node dependency. Checks, each a CRITICAL through `deliver_with_proof` on failure:

| Check | Fails when |
|---|---|
| Watch freshness | `capture_watch-polymarket_us.json` missing, unparseable or `written_at_ns` older than 900 s; or `systemctl --user is-active breezy-capture-watch.timer` is not `active` |
| Audit dead-man (C2) | No `capture_join_completeness` verdict for the family with `produced_at_ns` in the last 26 h (= `MAX_VERDICT_VALIDITY_H`) |
| Missing audit file (C2) | For any UTC day D whose audit was due (now ≥ D+1 14:30Z) in the last 8 days, `evidence/capture/audit_<family>_<D>.json` is missing. A `NO_INPUT` day writes a file too, so a missing file is always a fault. |
| Live-proof roll-up | The roll-up is older than 26 h |

It writes `health/capture_watchdog.json` (`capture_watchdog/v1`, `{schema, written_at_ns, checks:{…}}`) after every run. **The watch and the watchdog watch each other.** Both failing together means the user systemd manager or the host is down, which AUT-6's off-host canary absence rule pages (ARCH §4.6). Alert repeats are rate-limited to once per hour per check.

### 3.7 Daily completeness audit (obligation 6)

- `breezy-capture-audit.service` (oneshot) runs `python3 -m breezy.analysis.capture_audit_cli --venue polymarket_us --day <D>` at **13:50Z** for D = yesterday, plus a re-audit of every day in the last 8 still `INCONCLUSIVE`. It runs after the 12:15Z tape ingest and the overnight CLI publication.
- **Families by construction.** The union of capture-file family ids, every durable fill's attribution and every exec-store order record's `client_order_id`. An orphan fill or order is a FAIL no family can escape.
- **Inputs, all read-only:** capture files for the last 8 days; the exec store through the `mode=ro` URI with `SELECT key, value FROM state` (`fill_time_count.py:94,122`); `read_climate_day_including_corrections`; the blob store and artefacts; **node logs** `~/.local/share/breezy/logs/breezy-trade-*.log` overlapping D, each identified by its `TradingNode: instance_id:` line (line 46 today); the funnel files `fq_funnel_<boot day>.jsonl`; the `breezy-quote-tape-ingest` journal (`journalctl --user -u breezy-quote-tape-ingest -o cat --since <D+1 09:00Z> --until <now>`, a literal argv); the recorder tape catalog (for marks).
- **Fail-loud input rules (C2).** An exec-store open error, a `sqlite3.Error`, a `DurableFillRecord.from_bytes` failure, a key under `exec/polymarket_us/` whose prefix is not one of the module-level `…KEY_PREFIX`/`…_KEY` constants of `exec/client.py` (key-schema drift), or an unreadable node log for a boot overlapping D makes the day **`ERROR`**, never `NO_INPUT`. The audit writes `audit_<family>_<D>.json` with `day_status=ERROR` and the cause **first**, writes a HEALTH verdict `outcome=ERROR`, sends a CRITICAL, then exits 1 (an unexpected condition, so the non-zero exit is not "expected behaviour" under C2's rule).

**Legs per fill** (`audit_fill`):

| Leg | Pass condition |
|---|---|
| L | Exactly one `decision_id` across OrderLinks for `client_order_id`; conflict → `link_conflict` |
| D | Entry: a `Take` and a `TrySubmit(submitted)` with that id, and the id recomputes from the Take's stored fields. Exit (C7): an `Exit` record whose id recomputes from the exit tag values. |
| B | Depth and forecast blobs exist and re-hash; `artefact_sha256` resolves to bytes that hash to it; each forecast blob's `(station, cycle_runtime_ns)` matches a node-log `FQ_VECTOR_COMPLETE` line (ICAO mapped through the station registry) |
| E | A `LifecycleEvent(FILLED)` with the same `trade_id`, or a resolver context names the `client_order_id` |
| P | A `PositionMark` for the instrument with `ts_ns ≥ fill.ts_event`, from the node **or** the tape (below), or `fill_via_resolver` |
| S | A `SettlementRecord`. Climate day ended < 36 h ago with no CLI → `PENDING`; later → FAIL `settlement_missing` |

**Reconciliation legs per day (C1, C2, C4)**. These do not trust AUT-1's own records.

| Leg | Source | Pass condition |
|---|---|---|
| R1 node log, per record | Each node log overlapping D, `SHADOW_DECISION` lines with `kind` ∈ {`Take`, `TrySubmit`} and `now_ns` in D, parsed by `capture_node_log.py` | **Bijection** on `(station, rung_id, side, kind, reason, now_ns)` with capture records of that boot (`node_boot_id` = the log's `instance_id`). A log line with no capture record → `capture_missing` FAIL; a capture record with no log line → `capture_unexplained` FAIL. Deleting one capture record therefore fails the day. |
| R2 node log, refusals | Same lines, other kinds | Every `(station, side, kind, reason)` key seen in the log for that boot has at least one capture record of that boot (on-change writes cannot match counts, so coverage is the test) |
| R3 funnel | `fq_funnel_<boot day>.jsonl`, rows segmented to boots by the boots' `instance_id` line timestamps (several boots can share one boot-day file) | For each boot, at the last flush row `T` with no capture Take or TrySubmit within ±2 s of `T`: funnel count of `Take` and of `TrySubmit` per reason equals the capture count with `eval_ns ≤ T`; refusal keys covered as in R2 |
| R4 marker and log | `.INCOMPLETE` markers, `evidence/capture/incomplete_<D>.jsonl`, node-log `CAPTURE_WRITE_FAILED`/`CAPTURE_BYTE_CAP` lines | Any present → FAIL. Their absence is not evidence (L-30); R1–R3 carry the proof. |
| O order census | Every exec-store `venue_id/<voi>` row whose `client_order_id` carries a D date (Nautilus `ClientOrderIdGenerator` embeds `O-YYYYMMDD-HHMMSS-…`; WP0 pins the format), every `resolver/<id>` context created on D, every node-log `OrderSubmitted`/`OrderDenied` line on D | Each names a `client_order_id` with an OrderLink and a `decision_id`. Conversely, each pre-submit OrderLink is classified (§3.4); `order_unterminated` FAILs only once the boot has ended. |
| F fill census, positive control | `fill_by_day/<D>` ids filtered by `ts_event`; a full scan of `fill/` keys with `ts_event` in D; node-log `OrderFilled` lines on D | `set(fill_by_day filtered) == set(fill/ scan in D)`; node-log fills ⊆ exec fills; exec fills not in the node log each have a resolver context. Any mismatch → `fill_census_mismatch` FAIL. The `fills_total` the join reports equals this census, so a reader that silently drops a fill cannot pass. |
| T tape ingest (C14) | The `extend_dedupe:` lines in the ingest journal for runs after D's instance rotated | `flat_root != none` → FAIL `tape_flat_root`; an **unfiltered** count > 0 for `custom_depth_truncation` (`by_type=custom_depth_truncation:<f>/<u>`, u > 0) → FAIL `tape_unfiltered`; no `extend_dedupe:` line after D's rotation → FAIL `tape_ingest_missing`. A non-zero **filtered** count is healthy (`DepthTruncation` is expected on thin markets, `data.py:1817-1821`; PROGRESS ING-2-AMEND2 names `custom_depth_truncation:<n>/0` + `flat_root=none` as the pass state). |
| N NBP census (C17) | Node-log `NBM_NBP_PUBLISHED cycle_ns=` and `FQ_VECTOR_COMPLETE station= cycle_ns=` lines | For each configured cycle C (1, 13, 19Z) whose `C + stale_deadline_seconds` fell inside a node-up interval on D: at least one `NBM_NBP_PUBLISHED` with `cycle_ns = C` and one `FQ_VECTOR_COMPLETE` per configured station. Missing → `nbp_cycle_missing`. |

- **Tape marks (C1).** For every base slug with a non-zero net position from exec-store fills (leg sign applied, L-44), the audit reads the recorder catalog Depth10 at each whole UTC hour of D and appends `PositionMark(source="tape", mark_px=best ask, net_qty)` to `decisions/capture_<family>_<D>.offline.jsonl`. No node is involved, so marks exist even on a node-down day. Hours with no tape row write `mark_px=null, source="tape_no_row"`.
- **`SettlementRecord` writer.** One per `(station, climate_day)` referenced by a fill, to the same `.offline.jsonl` (L-50: the node never writes it). Polymarket.us basis `NWS_CLI`.
- **Day status.** `PASS` iff FINAL and every fill leg, R1–R4, O, F pass. `INCONCLUSIVE` while any leg is `PENDING` or `order_pending`. `NO_INPUT` when D has no fills, no orders and no Take lines (still writes the file; exit 0). `ERROR` as above. `FAIL` otherwise.
- **Verdicts** (C4, through the ARCH-0 writer, `valid_until_ns = produced_at_ns + 26 h`, `producer_code_sha` pinned in `PRODUCER_SOURCE_SHA256["aut1_capture_audit"]`, `subject_artefact_sha256` = the bound artefact (Z1)):
  - `capture_join_completeness`: join and legs R, O, F; `n = fills_total`, `n_min` reason `"census: every fill is checked; no sampling"`.
  - `capture_tape_ingest`: leg T. It does not decide the AUT-1 live proof (the README criterion is the join), but AUT-4 reads it for admissibility.
  - `capture_nbp_census`: leg N.
  - Daily verdicts are not proposed for `attest_required_verdict_kinds`: under the W1 invariant a once-a-day verdict cannot back a 6-hourly ATTEST. If AUT-5 wants a capture input for ATTEST, AUT-6's intraday producer converts the `capture_writer_health` DetectorEvents into an 8 h HEALTH verdict.
- **Canary and drill.** One rule (C11), §6. Canary fills from `derived/canary/` get their own `canary` section with the same fill legs; the live legs R, O and F never open `canary/`. Drill fills are joined like live fills and marked `drill=true` (W12).
- **Outputs.** `evidence/capture/audit_<family>_<D>.json` (0444, `capture_audit/v1`, venue order ids only as sha256, inputs as `{path_role, sha256, bytes_read}`, no paths); the verdicts; CRITICAL `CAPTURE_JOIN_GAP`, `CAPTURE_TAPE_INGEST` or `CAPTURE_NBP_CENSUS` through `deliver_with_proof` on FAIL; `OnSuccess=breezy-capture-live-proof.service`.

### 3.8 Units, timers, memory and locks

All oneshot units bound their run with **`TimeoutStartSec`** (C-ARCH note: `RuntimeMaxSec` has no effect on `Type=oneshot`).

| Unit | Schedule | Lock | Memory | Bound | Failure |
|---|---|---|---|---|---|
| `breezy-capture-watch` | `OnCalendar=*:0/5`, `AccuracySec=10s` | own `health/capture-watch.lock`, `flock -w 30`; never the studies flock | `MemoryHigh=192M`, `MemoryMax=256M` | `TimeoutStartSec=120` | `OnFailure=breezy-study-failed@%n.service` (proven notifier, below); `EnvironmentFile=-%h/.config/breezy/alerts.env` |
| `breezy-capture-watchdog` | `OnCalendar=*:7/15` | own `health/capture-watchdog.lock` | `MemoryMax=128M` | `TimeoutStartSec=60` | same |
| `breezy-capture-audit` | `13:50Z`, `Persistent=true` | `breezy-studies.lock`, `flock -w 600`, `Slice=breezy-studies.slice` | `MemoryHigh=768M`, `MemoryMax=1G` | `TimeoutStartSec=1500`: 13:50 + 10 min wait + 25 min ends by 14:25Z, before 16:30Z. WP6 measures the runtime over two 1.2 GB logs and fails review above 15 min. | same |
| `breezy-capture-live-proof` | `OnSuccess=` of the audit | studies lock, `-w 600` | `MemoryMax=256M` | `TimeoutStartSec=300` | same |
| `breezy-capture-stall-drill` | `OnCalendar=Sun *-*-* 12:30:00 UTC` (C5; WP0 confirms) | capture-watch lock | `MemoryMax=64M` | `TimeoutStartSec=60` | same |
| `breezy-capture-stall-drill-guard` | `OnCalendar=Sun *-*-* 13:00:00 UTC` | none | `MemoryMax=64M` | `TimeoutStartSec=30` | same |

- **`OnFailure` delivery is proven (C2).** Today `breezy-study-failed@` swallows failures (`study_failure_notifier.py:274-277`). AUT-6 migrates it to `deliver_with_proof` (ARCH §10 AUT-6, "every CRITICAL site"). AUT-1's units are not activated until `test_study_failure_notifier_uses_deliver_with_proof` (AUT-6) is green; AUT-1's `test_capture_units_onfailure_target_proven_notifier` pins the target name. The watchdog's missing-file and dead-man checks are a second, independent path.
- All units: `WorkingDirectory=/home/jon/breezy`, `UMask=0077`, the explicit interpreter, no venue credential, no egress beyond the existing alert webhook. Peak added load under 1.5G, none inside the trade node.

---
## 4. Work packages

**Gate for every WP:**

```
scripts/ci/run_tests_no_egress.sh; echo EXIT=$?          # full gate, exact interpreter; read EXIT (L-43; pytest -q doubles)
cd <tree root> && lint-imports                            # console script; must print "N kept, 0 broken"
scripts/ci/run_tests_no_egress.sh tests/unit/test_mypy_ratchet.py
```

- In a worktree, `PYTHONPATH=<worktree>/src`. Never `uv`, `pip`, `uv run` or `git stash`. Unit-launched gates use `-p LimitNOFILE=524288`.
- Must stay green **unedited**: `test_exec_client_is_byte_identical_to_its_pre_sl13_sha256`, `test_execution_egress_firewall_guard`, `test_operator_control_assignment_scan`, `test_shadow_only_false_is_only_the_gate_output`, `test_live_orders_ruling_deploy_copy_matches_evidence`, `test_native_order_cap_wiring`, `test_risk_engine_ordering_enforcement`, `test_probe_containment.py::test_pyproject_addopts_deselect_the_probe_markers` (L-54).
- Grep the contract tests for a module's package and path before placing it (L-46).

### AUT-1.WP0: premises and measurements (characterisation, mutation evidence per L-33)

- **Scope.** Pin every WP0 premise; measure, as one studies-flock job outside 01:00–04:30Z under `MemoryMax=4G`:
  1. full-UTC-day C1 volume;
  2. per-instrument and all-instrument market-data silence p99.9 in active hours, and `ACTIVE_HOURS_UTC` (14 tape days);
  3. the on-disk growth cadence of a streaming `live/<instance>/` (p50, p99.9 of inter-growth intervals) for `WRITER_STALL_S`, and the recorder-side silence p99.9 (C3);
  4. the `BulletinFetcher` HTTP timeout;
  5. systemd 259 SIGCONT-after-SIGTERM on a throwaway `systemd-run --user` sleep unit;
  6. fsync latency on the decisions filesystem (10,000 × 1 KiB appends): p50, p99, p99.9 → `CAPTURE_FSYNC_P99_BUDGET_MS`;
  7. **the drill window (C5):** the hourly distribution of `Take` lines over the retained node logs (63 files) and of recorder instance age; confirm Sunday 12:30Z is ≥ 1 h after the 09:00Z rotate, outside 09:00–09:45Z, outside 16:30–17:00Z, and in the lowest-take quartile. Otherwise pick the lowest-take hour meeting those rules and record it.
- **Files.** `tests/unit/test_aut1_l1_nautilus_premises.py` (new); `docs/evidence/AUT1_WP0_premises_<date>.md` (new).
- **RED/characterisation tests** (each fails against a recorded mutation):
  - `::test_order_events_publish_on_events_order_strategy_topic`
  - `::test_actor_wildcard_msgbus_subscription_receives_order_and_position_events`
  - `::test_msgbus_handler_exception_unwinds_into_publisher`
  - `::test_python_submit_order_override_is_dispatched_from_python_caller` (**gates WP2**, C16)
  - `::test_refused_submit_before_super_never_adds_order_to_cache`
  - `::test_order_tags_absent_from_wire_body`
  - `::test_depth10_ts_event_is_venue_transact_time`
  - `::test_passive_data_topic_subscription_issues_no_subscribe_command`
  - `::test_client_order_id_embeds_utc_date`
- **GREEN.** All pass on 1.231.0; the evidence file states every measured constant and the drill window.
- **If `test_python_submit_order_override_is_dispatched_from_python_caller` fails,** WP2 stops. The fallback design (guard checks inside each kind's single submit call site, plus an AST test that every `submit_order` call in `strategy/` is preceded by the guard) is planned in a reviewed r3 before any code.
- **Activation.** None.

### AUT-1.WP1: capture core (`persistence/autonomy/`)

- **Scope.** §3.3.1–3.3.3, `capture_reader`, `capture_watch_state`, `DECISION_ID_TAG_PREFIX`.
- **Files.** `capture_ids.py`, `capture_writer.py`, `capture_blobs.py`, `capture_reader.py`, `capture_watch_state.py` (new); `persistence/exit_tags.py` (edit).
- **RED tests first** (`tests/unit/autonomy/`):
  - `test_capture_ids.py::test_decision_id_recomputes_from_stored_record`, `::test_decision_id_field_order_is_pinned`, `::test_exit_decision_id_is_deterministic_from_exit_tags` (C7), `::test_depth_ref_excludes_ts_init_and_size_zero_pads`, `::test_forecast_input_sha_is_canonical`
  - `test_capture_writer.py::test_lines_are_schema_versioned_exact_set`, `::test_refusal_written_only_on_key_kind_reason_change`, `::test_would_write_decision_is_pure_lookup`, `::test_take_trysubmit_link_lifecycle_are_fsynced`, `::test_short_write_is_failure` (C4), `::test_write_failure_is_critical_logged_and_double_journaled` (C4), `::test_marker_write_failure_leaves_health_not_ok` (C4), `::test_byte_cap_is_loud_not_silent`, `::test_utc_rollover_open_failure_is_loud` (C15), `::test_reason_is_closed_enum` (C15: `kind` and EntryVeto `reason` refuse anything outside the closed sets), `::test_fsync_p99_over_budget_reports_disagree_without_veto` (C6), `::test_on_change_map_is_bounded`, `::test_canary_records_land_only_in_canary_store`, `::test_writer_never_raises`, `::test_drill_flag_read_per_record_not_frozen`
  - `test_capture_blobs.py::test_blob_store_is_content_addressed_and_idempotent`, `::test_blob_store_refuses_symlinks`
  - `test_capture_reader.py::test_join_fills_to_decisions_by_client_order_id`, `::test_join_reports_orphan_fill_as_gap`, `::test_reader_refuses_partial_line`, `::test_reader_takes_fills_as_values_never_imports_exec_client` (W6)
  - `test_capture_watch_state.py::test_watch_state_single_read_refuses_symlink_oversize_unknown_keys`
  - `test_autonomy_payload_hygiene_scan` widened to the new writers.
- **GREEN.** All pass; `lint-imports` clean; no Nautilus import in `capture_ids`/`capture_writer`.
- **Activation.** Library only; live with WP3.

### AUT-1.WP2: FQ adapter, guard, tag, `EntryVeto` and `Exit` writers (gated on WP0, C16)

- **Scope.** §3.3.4, §3.3.5; registration of `FqCaptureAdapter` in `NODE_PLUGINS`.
- **Files.** `strategy/autonomy_capture/guarded_strategy.py`, `strategy/forecast_quantile_ladder/capture_adapter.py` (new); `strategy/forecast_quantile_ladder/strategy.py` (edit, CS-1 to CS-4; `try_submit` untouched).
- **RED tests first:**
  - `tests/strategy/forecast_quantile_ladder/test_aut1_capture_adapter.py`: `::test_every_fq_order_carries_exactly_one_decision_id_tag`, `::test_untagged_entry_is_refused_capture_untagged`, `::test_duplicate_or_malformed_tag_refused` (C16), `::test_refused_order_never_reaches_cache` (C16), `::test_capture_refused_log_has_entryveto_record` (C16), `::test_order_link_is_fsynced_before_submit_order`, `::test_link_write_failure_refuses_entry_capture_gap`, `::test_entry_veto_reason_is_written_as_entryveto_record`, `::test_trysubmit_record_eval_ns_equals_shadow_line_now_ns` (leg R1), `::test_blob_and_sha_work_only_after_on_change_check` (C6: counts hash calls over 1,000 unchanged evaluations = 0), `::test_take_record_carries_depth_ref_forecast_sha_and_artefact_sha`, `::test_take_without_depth_is_refused_capture_gap`, `::test_no_leg_take_records_side_no`, `::test_shadow_only_take_is_captured_without_order`, `::test_capture_drill_flag_persists_after_drill_resume`
  - `tests/unit/autonomy/test_capture_guard.py`: `::test_capture_guarded_strategy_without_writer_refuses_construction` (C8), `::test_capture_guarded_strategy_without_outbox_refuses_construction` (C8), `::test_exit_tagged_order_is_never_refused_by_capture`, `::test_legitimate_exit_raises_no_critical` (C7), `::test_exit_writes_exit_record_and_link_with_recomputable_id` (C7), `::test_exit_with_missing_tag_still_submits_and_alerts`, `::test_guarded_submit_latency_independent_of_webhook` (C6, W9), `::test_capture_untagged_is_a_veto_reason` (C8)
  - `tests/unit/autonomy/test_capture_guard_family_agnostic.py`: `::test_every_full_plugin_kind_strategy_subclasses_capture_guard`, `::test_decision_id_tag_prefix_never_collides_with_exit_prefixes`
  - Fixtures write through the real `CaptureWriter` (L-42); one test runs the production default writer factory (L-55).
- **Benchmark (C6).** `docs/evidence/AUT1_WP2_hotpath_<date>.md`: p50/p99 of `CaptureGuardedStrategy.submit_order` steps 1–4 over 1,000 synthetic orders on the host disk, against `CAPTURE_FSYNC_P99_BUDGET_MS`. A p99 over budget blocks the merge.
- **GREEN.** All pass, plus the existing `tests/strategy/forecast_quantile_ladder/*` and `test_forecast_quantile_ladder_boot.py` unedited.
- **Activation.** Through WP3. The `Exit` record path merges only after ARCH-0 accepts the C1 `Exit` kind (§11 N1); until then the guard's exit branch writes the OrderLink and submits, and the audit's leg D for exits is `PENDING_CONTRACT`. No FQ exit exists (G17), so nothing live depends on it.

### AUT-1.WP3: lifecycle actor, node observations, composition hunk (Wave 1b)

- **Scope.** §3.3.6, §3.5.1 `md_feed_freshness`, §3.5.3, §3.5.4; the single `app/trade.py` hunk constructing identity, writer, outbox handle (from AUT-6), adapter and actor, registering the NODE_LOCAL detectors with AUT-5a's composer.
- **Files.** `strategy/autonomy_capture/lifecycle_actor.py`, `node_observations.py` (new); `strategy/forecast_quantile_ladder/composition.py` (edit); `app/trade.py` (one hunk, rebased after AUT-5a merges).
- **RED tests first** (`tests/unit/autonomy/test_capture_lifecycle_actor.py`): `::test_actor_writes_order_link_with_venue_sha_on_accept`, `::test_actor_writes_lifecycle_for_each_terminal_event`, `::test_position_mark_signs_no_leg_as_short_yes`, `::test_handler_never_raises_into_publisher`, `::test_capture_actor_issues_no_venue_subscription`, `::test_capture_gap_vetoes_at_boot_until_positive_control`, `::test_observation_older_than_3_ticks_vetoes_at_call_time`, `::test_per_instrument_silence_vetoes_that_instrument_only` (C13), `::test_silent_fraction_above_limit_vetoes_venue` (C13), `::test_silent_fraction_at_limit_does_not_veto` (C13 boundary), `::test_never_seen_instrument_counts_as_silent` (C13), `::test_md_silence_horizon_tracks_configured_idle_timeout`, `::test_recorder_stale_vetoes_only_on_unhealed_inactive_or_stale_file`, `::test_unparseable_watch_file_vetoes`, `::test_transient_capture_veto_writes_no_transition`, `::test_detectors_count_drill_records` (W12), `::test_capture_modules_never_import_exec_store`; `tests/unit/test_forecast_quantile_ladder_boot.py::test_fq_composition_registers_capture_actor_and_detectors` and `::test_fq_compose_without_capture_writer_fails_boot` (C8), both with the production default factory (L-55).
- **GREEN.** All pass; `test_shadow_only_false_is_only_the_gate_output` unedited.
- **Activation.** The next supervisor STOP/LAUNCH (16:40/16:50Z). Technical reason: the hunk changes the order path, and LAUNCH re-runs every boot gate; a hand relaunch is refused after AUT-5a (Z7). Precondition: WP5's watch and watchdog have been active at least 10 min before that LAUNCH, and the recorder has passed one 09:00Z rotate with the heartbeat code, otherwise `recorder_stale` vetoes from boot.

### AUT-1.WP4: NBP freshness detector and in-node poll-hang self-heal

- **Scope.** §3.5.1 `nbp_feed_freshness`, §3.5.2.
- **Files.** `strategy/forecast_quantile_ladder/capture_adapter.py`; `ingest/nbm_quantile_actor.py`.
- **RED tests first:** `tests/unit/test_nbm_quantile_actor.py::test_submit_retains_future`, `::test_poll_hang_is_cancelled_and_reset_after_threshold`, `::test_poll_reset_followed_by_vector_complete_journals_self_heal`; `tests/strategy/forecast_quantile_ladder/test_aut1_nbp_freshness.py::test_one_missed_cycle_alerts_with_delivery_proof_no_veto`, `::test_two_missed_cycles_veto_feed_stale`, `::test_no_complete_vector_for_subscribed_station_vetoes`, `::test_bulletin_drift_counts_as_missed_cycle`, `::test_veto_clears_on_newer_complete_vector`.
- **GREEN.** All pass; existing actor tests unedited.
- **Activation.** Next supervisor LAUNCH (same reason as WP3).

### AUT-1.WP5: heartbeat, watch, watchdog, unit self-heal

- **Scope.** §3.6 in full. In `pins.py` (one reviewed commit): the two units in `SELF_HEAL_RESTARTABLE_UNITS`; `PRODUCER_SOURCE_SHA256["aut1_capture_watch"]` and `["aut1_capture_watchdog"]`.
- **Files.** `adapters/polymarket_us/config.py`, `data.py`, `runtime/node_config.py` (edit); `runtime/capture_watch.py`, `capture_watch_cli.py`, `capture_watchdog.py`, `capture_watchdog_cli.py` (new); `deploy/systemd/breezy-capture-watch.{service,timer}`, `breezy-capture-watchdog.{service,timer}` (new); `persistence/autonomy/pins.py` (edit).
- **Depends on** AUT-6's `restart_unit` (durable trading-day counter), `deliver_with_proof`, and the migrated `study_failure_notifier`. No stub that restarts.
- **RED tests first:**
  - `tests/unit/test_recorder_heartbeat.py`: `::test_heartbeat_is_atomic_rate_limited_and_o1`, `::test_heartbeat_written_during_empty_discovery_retry`, `::test_trade_node_config_has_no_heartbeat_path`, `::test_heartbeat_failure_never_raises`
  - `tests/unit/test_capture_watch.py`: `::test_stale_heartbeat_with_active_unit_is_hung`, `::test_hung_detection_not_gated_by_hours` (C9), `::test_streaming_with_frozen_counters_and_bytes_is_stalled`, `::test_stalled_uses_quiet_hours_multiplier` (C9), `::test_counters_rising_bytes_flat_is_writer_stall` (C3), `::test_healthy_fixture_never_writer_stall` (C3 positive control), `::test_frozen_writer_fixture_triggers_writer_stall_and_restart` (C3), `::test_midnight_file_rotation_is_not_writer_stall`, `::test_zero_byte_stubs_count_as_no_data`, `::test_empty_listing_within_budget_is_ok`, `::test_rotation_grace_suppresses_heal`, `::test_inactive_unit_is_never_started`, `::test_is_active_rechecked_immediately_before_restart`, `::test_two_consecutive_bad_probes_trigger_restart_via_aut6_api`, `::test_restart_cap_survives_watch_process_restart` (C12, W11), `::test_restart_window_resets_before_launch` (C9), `::test_restart_cap_exhausted_sets_unhealed_critical_and_health_fail`, `::test_heal_confirmed_journals_and_writes_health_pass`, `::test_nws_ingest_snapshot_stale_restarts_gate_closed_alerts_only`, `::test_watch_state_file_is_atomic_and_schema_exact`, `::test_watch_raises_when_watchdog_stamp_stale` (C18)
  - `tests/unit/test_capture_watchdog.py`: `::test_watchdog_raises_when_watch_state_stale` (C18), `::test_watchdog_raises_when_watch_timer_inactive` (C18), `::test_no_verdict_within_26h_raises_critical_via_deliver_with_proof` (C2), `::test_missing_audit_file_for_elapsed_day_is_critical` (C2), `::test_watchdog_alert_rate_limited_hourly`
  - `tests/unit/test_capture_units.py::test_oneshot_units_use_timeout_start_sec_not_runtime_max_sec`, `::test_units_have_own_lock_memory_cap_and_no_studies_flock` (watch, watchdog), `::test_capture_units_onfailure_target_proven_notifier` (C2)
  - The ARCH `test_self_heal_unit_allowlist_is_literal_and_excludes_trade` passes with the two units.
- **GREEN.** All pass; full gate.
- **Activation.** Immediately on merge, once AUT-6's notifier test is green: `systemctl --user link` the four unit files; `enable --now` both timers; the recorder picks up the heartbeat at the next 09:00Z rotate (§3.6.3); after it, confirm a fresh `recorder-polymarket_us.json`, `capture_watch-polymarket_us.json` with `recorder.state=OK`, and `capture_watchdog.json` with every check passing.

### AUT-1.WP6: daily audit, node-log parser, `SettlementRecord`, tape marks, retention

- **Scope.** §3.7; retention widening; `PRODUCER_SOURCE_SHA256["aut1_capture_audit"]`.
- **Files.** `analysis/capture_audit.py`, `capture_audit_cli.py`, `capture_node_log.py` (new); `deploy/systemd/breezy-capture-audit.{service,timer}` (new); `scripts/ops/decisions_retention.py`, `persistence/autonomy/pins.py` (edit).
- **RED tests first** (`tests/unit/test_capture_audit.py` unless named):
  - join: `::test_complete_day_passes_final`, `::test_orphan_fill_without_link_fails`, `::test_link_conflict_fails`, `::test_settlement_pending_is_inconclusive_overdue_fails`, `::test_blob_rehash_mismatch_fails`, `::test_forecast_blob_without_vector_complete_line_fails`, `::test_registry_seq_zero_after_cutover_fails`, `::test_resolver_fill_without_node_filled_event_passes_e_and_p`, `::test_tape_mark_satisfies_leg_p_without_node` (C1), `::test_tape_marks_written_for_open_positions_without_node` (C1), `::test_every_exit_fill_joins` (C7)
  - reconciliation (C1, C4): `::test_node_log_take_line_without_capture_record_fails`, `::test_deleted_capture_record_fails_day`, `::test_capture_record_without_node_log_line_fails`, `::test_funnel_vs_capture_count_mismatch_fails`, `::test_funnel_rows_segmented_by_boot_in_shared_boot_day_file`, `::test_refusal_key_in_log_missing_from_capture_fails`, `::test_marker_write_failure_still_fails_day` (C4: writer fails, no marker, no log line; R1 still fails the day), `::test_incomplete_marker_or_evidence_journal_fails_day`
  - orders (C1, C10): `::test_every_exec_store_order_record_has_order_link`, `::test_resolver_context_without_order_link_fails`, `::test_crash_between_link_and_submit_classified_never_submitted`, `::test_linked_order_without_terminal_event_pending_while_boot_runs`, `::test_linked_order_without_terminal_event_fails_after_boot_ends`
  - census and fail-loud (C2): `::test_fill_by_day_positive_control_matches_fill_keys`, `::test_fill_census_disagrees_with_node_orderfilled_lines_fails`, `::test_exec_store_open_error_is_error_never_no_input`, `::test_undecodable_fill_record_is_error`, `::test_unknown_exec_key_prefix_is_error`, `::test_unreadable_node_log_is_error`, `::test_error_writes_audit_file_and_verdict_before_exit_1`, `::test_no_fills_exits_zero_no_input_and_writes_file`
  - tape and NBP (C14, C17): `::test_extend_dedupe_flat_root_is_tape_critical`, `::test_extend_dedupe_unfiltered_depth_truncation_is_tape_critical`, `::test_extend_dedupe_line_missing_is_tape_incomplete`, `::test_filtered_depth_truncation_count_is_healthy`, `::test_nbp_cycle_census_missing_cycle_fails_census_leg`, `::test_nbp_census_counts_vector_complete_per_station`, `::test_nbp_cycle_with_deadline_in_node_down_interval_not_expected`
  - canary, drill, families: `::test_canary_fills_reported_separately_never_in_live_legs` (C11), `::test_drill_fills_joined_and_marked` (W12), `::test_unknown_family_fill_is_enumerated_by_construction`, `::test_reads_gzipped_capture_files`
  - provenance: `::test_exec_store_fixture_written_through_real_record_fill` (L-42), `::test_settlement_record_basis_is_nws_cli_for_polymarket_us`, `::test_verdict_schema_valid_bound_artefact_sha_and_pinned_producer`, `::test_fail_sends_critical_through_deliver_with_proof`, `::test_offline_writer_never_appends_node_file` (L-50), `::test_audit_evidence_has_no_absolute_paths`
  - `tests/unit/test_capture_node_log.py`: `::test_parses_shadow_decision_take_and_trysubmit_lines`, `::test_parses_orderfilled_client_and_venue_ids`, `::test_reads_instance_id_line`, `::test_unparseable_marker_line_is_counted_never_skipped_silently`, `::test_streaming_parser_memory_is_o_matches`
  - `tests/unit/test_decisions_retention.py::test_capture_files_are_gzip_candidates`
- **Runtime evidence.** One run against two real retained logs (≈ 2.4 GB) under the unit's `MemoryMax=1G`, wall time recorded; above 15 min the WP returns to review.
- **GREEN.** All pass; full gate.
- **Activation.** Immediately on merge (subject to the notifier dependency): link and `enable --now breezy-capture-audit.timer`; one `systemctl --user start breezy-capture-audit.service`; check `audit_*.json` and the three verdict files. Before WP3 is live, days have no capture records, so R1 would fail them. Those days get `day_status=PRE_CAPTURE` only when D is strictly before `CAPTURE_LIVE_FROM_UTC_DAY`, a literal date in `capture_audit.py` set in WP3's reviewed merge commit to the first full UTC day after its LAUNCH. From that day on there is no exemption, so a writer that never writes cannot hide behind it (`::test_pre_capture_exemption_ends_at_literal_date`). `PRE_CAPTURE` days never qualify for the live proof.

### AUT-1.WP7: weekly injected stall drill and live-proof roll-up

- **Scope.**
  - `capture_stall_drill_cli`: refuse unless `capture_watch` is `OK`, phase `STREAMING`, instance older than 1 h, and the time is within 10 min of the WP0-confirmed slot (default Sunday 12:30Z, C5); write `evidence/capture/drill_<date>.json` (`injected=true`); run the literal argv `["systemctl","--user","kill","--signal=SIGSTOP","breezy-quote-tape.service"]`.
  - Guard at 13:00Z: literal argv `[…,"--signal=SIGCONT",…]`, unconditional; if no `HEALED` row with `injected=true` exists for today's drill, CRITICAL `CAPTURE_DRILL_NOT_HEALED`. Timeline: stop 12:30, heartbeat stale 12:33, two bad probes by 12:40, restart, heal confirmed by about 12:50.
  - `capture_live_proof`: reads `audit_*.json`, `self_heal_*.jsonl` and the delivery journals for the heal day and the next day (W13: two days, so a heal near midnight finds its row); computes the qualifying-day run per §6; writes `evidence/capture/live_proof_<family_id>_<asof>.json` (`capture_live_proof/v1`, `status ∈ {ACCRUING, PROVEN}`).
- **Files.** `runtime/capture_stall_drill_cli.py`, `analysis/capture_live_proof.py`, `_cli.py` (new); the drill, guard and live-proof units.
- **RED tests first:** `tests/unit/test_capture_stall_drill.py::test_drill_refuses_when_recorder_not_ok_or_outside_window`, `::test_drill_window_is_not_in_rotate_hole_or_launch`, `::test_drill_argv_is_literal_sigstop_on_recorder_only`, `::test_guard_argv_is_literal_sigcont_on_recorder_only`, `::test_drill_marks_self_heal_entry_injected`; `tests/unit/test_capture_live_proof.py::test_zero_fill_days_extend_not_break`, `::test_fail_day_breaks_window`, `::test_requires_five_real_fills_excluding_canary_and_drill`, `::test_canary_only_day_qualifies_day_but_not_real_fill_count` (C11), `::test_real_fill_day_cannot_be_rescued_by_canary` (C11), `::test_requires_one_healed_stall_with_delivery_proof`, `::test_delivery_row_found_on_next_day_journal` (W13), `::test_proven_only_with_seven_qualifying_days`; an AST test that `runtime/capture_*` and `analysis/capture_*` call `subprocess` only through the AUT-6 API, the two drill argvs, the read-only `is-active` argv and the `journalctl` argv.
- **GREEN.** All pass; full gate.
- **Activation.** Immediately on merge: link and enable both drill timers; the first drill is the next Sunday slot.

---
## 5. Association

### 5.1 Consumed (by contract)

| From | Contract | Exact interface |
|---|---|---|
| ARCH-0 | C1 | record dataclasses, `to_dict`/`from_dict`, schema allowlist; **requested widenings:** `DecisionRecord.kind += "Exit"` with `depth_ref` nullable for `Exit` only (§11 N1) |
| ARCH-0 | C4 | verdict dataclass and append-only writer |
| ARCH-0 | C5, C6 | `CaptureAdapter`/`Detector` Protocols, `NODE_PLUGINS`, `RefusingPlugin`; `VetoReason` closed enum with `capture_gap`, `feed_stale`, `recorder_stale` **and `capture_untagged`** (§11 N2) |
| ARCH-0 | §4.3, §4.5 | `pins.py`: `SELF_HEAL_RESTARTABLE_UNITS`, `PRODUCER_SOURCE_SHA256`, `SELF_HEAL_MAX_RESTARTS_PER_UNIT_PER_DAY` (≤ 3), `MAX_VERDICT_VALIDITY_H`, `WATCH_TICK_STALE_S` |
| AUT-5a | C5 | `ResolvedFamily`; `RegistryWatchActor.drill_active(now_ns)`; the required `entry_veto(instrument_id)` slot and composer (W10) that calls AUT-1's NODE_LOCAL detectors; the bound artefact sha; ownership of `try_submit` and `app/trade.py` in Wave 1 |
| AUT-6 | §4.6, C6 | `deliver_with_proof`; the node `AlertOutbox.offer(payload) -> bool` with its worker, `ALERT_OUTBOX_MAX` and `ALERT_DELIVERY_TIMEOUT_S` (W9); `restart_unit(unit, *, cause) -> RestartOutcome` with the durable counter `evidence/selfheal/<date>.json` (W11), **`<date>` keyed on the trading day `[16:45Z, +24 h)`** (C9; §11 N5) and, if ARCH agrees, the `try-restart` verb (§11 N3); `study_failure_notifier` migrated to `deliver_with_proof` with `test_study_failure_notifier_uses_deliver_with_proof`; catalogue registration of AUT-1's detectors; the intraday producer; the off-host canary absence rule (backstop for the watch pair) |
| AUT-2 | §5.3, Z14 | **the canary producer** (unit name owned by AUT-2) that drives AUT-1's production `FqCaptureAdapter` and `CaptureWriter(source="canary")` code with a synthetic decision and writes the synthetic fill to `derived/canary/`; AUT-6 delivers any alert it raises |

### 5.2 Provided

| To | Contract | Interface |
|---|---|---|
| AUT-2 | C1 | live and canary capture files; `.offline.jsonl` (`SettlementRecord`, tape `PositionMark`s); `join_fills_to_decisions`; the blob store; exit ids for `role=exit` labels |
| AUT-4 | C1, C4 | depth and forecast preimages; `.INCOMPLETE` markers; `capture_tape_ingest` verdicts for tape-day admissibility |
| AUT-6 | C1, C6 | `DetectorEvent`s; the NODE_LOCAL detectors `capture_writer_health`, `md_feed_freshness`, `nbp_feed_freshness`, `recorder_liveness`; the `capture_watch/v1` and `capture_watchdog/v1` state files; `recorder_self_heal` HEALTH verdicts |
| AUT-5 | C4 | HEALTH verdicts `capture_join_completeness`, `recorder_self_heal`, `capture_tape_ingest`, `capture_nbp_census`. Proposed policy rows: `capture_join_completeness FAIL → DEMOTE` (`RECOVERABLE_INFRA`, never TERMINAL); `recorder_self_heal FAIL → ALERT`; `capture_tape_ingest FAIL → ALERT`; `capture_nbp_census FAIL → ALERT`. None proposed for `attest_required_verdict_kinds` (§3.7). |

### 5.3 Execution order

```
ARCH-0 ─► WP0 ─┬─► WP1 ─► WP2 (gated on WP0 dispatch premise) ─┐
               │                                               ├─► WP3 (after AUT-5a; WP5 active; one 09:00Z rotate) ─► LAUNCH
               └─► WP4 (needs WP1, WP2) ───────────────────────┘
AUT-6 (deliver_with_proof, outbox, restart_unit, notifier) ─► WP5 ─► WP6 ─► WP7
AUT-2 canary producer ─► (canary section of WP6; never blocks the live proof)
```

- **Parallel:** WP0 with AUT-5a and AUT-6; after WP0, WP1, WP5's heartbeat half and WP6's pure core (join, reconciliation, census parsers).
- **Serial:** WP2 → WP3; WP3 after AUT-5a; WP5's self-heal half and every unit activation after AUT-6's API and notifier.
- **File ownership:** AUT-1 owns `_emit_shadow_decision`, `_emit_decision_outcome`, `_maybe_submit`, `on_order_book_depth`; AUT-5a owns `try_submit` and `app/trade.py` until merged. Full gate after every merge (L-43); per-agent scratchpads.

---

## 6. Live-proof protocol

- **Artefacts.** (1) daily `audit_<family>_<D>.json` and the `capture_join_completeness` verdict; (2) `self_heal_<date>.jsonl` with at least one `HEALED` row (natural recorder or NBP heal, or the injected drill); (3) its `delivered=true` row in `evidence/alerts/delivery_<date>.jsonl` or the next day's; (4) `live_proof_pm_us_crh_fq_v1_<asof>.json` with `status=PROVEN`.
- **One qualifying-day rule (C11), from the README rule quoted in §1.1:**
  - A day with **≥ 1 real fill** (not canary, not drill) qualifies iff its live audit is `PASS`. Canary fills on that day cannot rescue a FAIL.
  - A day with **no real fill** qualifies iff at least one `source=canary` fill traversed AUT-1's production capture code and the audit's canary section passes every fill leg. It counts as one window day and contributes 0 to the real-fill count.
  - A day with neither does not count, and the window extends. `FAIL`, `ERROR` or `INCONCLUSIVE` past 36 h breaks the run. `PRE_CAPTURE` days never count.
  - The window needs 7 qualifying days **and** ≥ 5 real fills. Canary and drill fills never count toward the 5 or any statistic.
  - Producer of canary fills: AUT-2. Delivery of its alerts: AUT-6. AUT-1 audits them.
- **Accrual ETA.** Measured cadence: 2 takes on 10-01, 3 on 10-02. A fill on day X trades D+1 and is FINAL about X+2 13:50Z. Build WP0–WP6 is about 6–8 working days after ARCH-0, AUT-5a and AUT-6's delivery API merge; assuming that by 2026-10-07, activation at the 2026-10-14 LAUNCH. Earliest PROVEN **2026-10-22**; the stall requirement is met by the first Sunday drill, 2026-10-18 12:30Z, if no natural stall occurs first. **Planning ETA 2026-10-29**, allowing 7 zero-fill or halted days. About 13 weeks of margin before the 2027-01-25 KILL.
- **Evidence class.** "Machinery proven, edge unproven." A census, not a statistical test.
- If FQ is halted, real fills stop and the window pauses; canary days alone cannot produce PROVEN because of the 5-real-fill floor.

---

## 7. Score-3 verification checklist (independent scorer)

| Criterion | Exact check |
|---|---|
| (a) Unattended | `systemctl --user list-timers 'breezy-capture-*'` shows watch, watchdog, audit, drill and guard timers. `git -C /home/jon/breezy log --since=<window start> --until=<window end> --format='%H %s' -- src/breezy/persistence/autonomy/ src/breezy/strategy/autonomy_capture/ src/breezy/runtime/capture_watch.py src/breezy/runtime/capture_watchdog.py src/breezy/analysis/capture_audit.py deploy/systemd/` is empty. Every `audit_*.json` has `"produced_by":"breezy-capture-audit.service"`; every `HEALED` row has `"decided_by"` ∈ {`capture_watch`, `nbm_quantile_actor`}. `journalctl --user -u breezy-quote-tape --since <window>` start and stop lines correlate one-for-one with the rotate, watch or drill units. |
| (b) Family-agnostic | `scripts/ci/run_tests_no_egress.sh tests/unit/autonomy/test_capture_guard_family_agnostic.py tests/unit/test_capture_audit.py::test_unknown_family_fill_is_enumerated_by_construction tests/unit/test_capture_audit.py::test_every_exec_store_order_record_has_order_link` passes; ARCH-0 `test_family_plugin_exact_set` passes. |
| (c) Fails closed | `test_untagged_entry_is_refused_capture_untagged`, `test_refused_order_never_reaches_cache`, `test_link_write_failure_refuses_entry_capture_gap`, `test_capture_guarded_strategy_without_writer_refuses_construction`, `test_unparseable_watch_file_vetoes`, `test_exec_store_open_error_is_error_never_no_input`, `test_marker_write_failure_still_fails_day` pass. In the node log, every `CAPTURE_REFUSED reason=` line has a matching `EntryVeto` record. |
| (d) Detected and alerted with delivery | For each failure mode (`CAPTURE_WRITE_FAILED`, `CAPTURE_BYTE_CAP`, `CAPTURE_JOIN_GAP`, `CAPTURE_TAPE_INGEST`, `CAPTURE_NBP_CENSUS`, `NBP_CYCLE_MISSED`, recorder `HUNG`/`STALLED`/`WRITER_STALL`/`UNHEALED`/`INACTIVE`, NWS ingest `HUNG`, `CAPTURE_WATCHDOG_STALE`, watch stale, audit dead-man, missing audit file): a gate test asserts the outbox or `deliver_with_proof` is called. Live: `jq 'select(.event|test("CAPTURE_SELF_HEAL"))' ~/.local/share/breezy/evidence/alerts/delivery_<date>.jsonl` shows `"delivered":true`. |
| (e) RED→GREEN | Per WP: the implementer's RED output naming the §4 tests, the GREEN output, the merge SHA; `scripts/ci/run_tests_no_egress.sh; echo EXIT=$?` gives `EXIT=0` on the merge commit; `lint-imports` prints "N kept, 0 broken". |
| (f) Live proof | `jq '.status' ~/.local/share/breezy/evidence/capture/live_proof_pm_us_crh_fq_v1_<asof>.json` is `"PROVEN"`. For each listed date: `jq '.day_status, .fills_total == .fills_joined, .legs.R1.pass, .legs.F.pass, .legs.O.pass' …/audit_pm_us_crh_fq_v1_<date>.json` gives `"PASS"` and four `true`; the verdict under `derived/verdicts/pm_us_crh_fq_v1/<date>/` has `detector=capture_join_completeness`, `outcome=PASS`; `jq -s 'map(select(.status=="HEALED"))|length' …/self_heal_*.jsonl` ≥ 1. |
| Spot check, independent of AUT-1's code | For 3 random window fills: `sqlite3 'file:/home/jon/.local/share/breezy/state/exec_polymarket_us.sqlite?mode=ro' "select value from state where key='exec/polymarket_us/fill/<voi>'"` gives a `clientOrderId`; `/usr/bin/grep -c 'OrderFilled(.*client_order_id=<id>' ~/.local/share/breezy/logs/breezy-trade-*.log` ≥ 1, or a resolver context exists; `/usr/bin/zgrep -h '"client_order_id": "<id>"' ~/.local/share/breezy/catalog/quote_tape/decisions/capture_pm_us_crh_fq_v1_*` finds the OrderLink, whose `decision_id` greps to a `Take`; that Take's `eval_ns` appears as `'now_ns': <eval_ns>` in a node-log `SHADOW_DECISION … 'kind': 'Take'` line; its `depth_ref` blob's `sha256sum` matches its name. |

---

## 8. Risks and failure modes

| Risk | Mitigation |
|---|---|
| A capture handler raise unwinds into the execution engine (L-16) | Catch-all handlers; writer never raises; `test_handler_never_raises_into_publisher`. |
| A raise in the 60 s timer is silently discarded (L-16), freezing detectors | Call-time staleness veto after 180 s; positive control. |
| Capture blocks trading (node-down afternoons feed the KILL) | Vetoes auto-clear; `recorder_stale` only after self-heal fails; exits never refused; fsync budget benchmarked; CRITICALs off-loop (W9). |
| The independent sources are not fully independent | The node log and funnel are emitted from the same `_emit_shadow_decision` call as CS-1, so they are independent of the **writer and storage**, not of the call site. Call-site bypass is closed separately: no order can be sent without an OrderLink (guard), and every exec-store order and fill must join (legs O, F). Stated, not hidden. |
| Node-log format drift breaks leg R | Strict per-marker regexes; an unparseable marker line is counted and fails the day (`test_unparseable_marker_line_is_counted_never_skipped_silently`), never skipped. |
| Node logs are ~1.2 GB a day | Streaming fixed-string prefilter, O(matches) memory, `MemoryMax=1G`; WP6 runtime evidence. Retention of node logs is not changed by AUT-1; 63 are retained today. |
| Restart loop in the 09:00–09:45Z listing hole | Legitimate `DISCOVERING` is OK; 600 s rotation grace; ≤ 3 restarts per trading day; INACTIVE never started. |
| Cap exhausted overnight blocks the next trading day | Trading-day counter window resets at 16:45Z (C9); requested from AUT-6 (§11 N5). |
| SIGKILL truncates a feather file | SIGCONT premise pinned in WP0 with the reviewed `ExecStop` fallback; drill guard always SIGCONTs. |
| A drill becomes a real outage | Only from `OK`, in the WP0-chosen low-take slot ≥ 1 h after rotate; 13:00Z guard; failed heal CRITICAL. |
| Both watchers die | Mutual watch; then the off-host canary absence rule (AUT-6). |
| Memory (30 GiB host; L-29, L-49, L-53) | Node structures O(subscribed instruments); watch 256M, watchdog 128M, audit 1G, proof 256M, drill 64M; WP0 measurement once under 4G outside 01:00–04:30Z; one heavy job at a time. |
| Shared venv (L-51) | No dependency or console-script change; `python3 -m`; exact interpreter in every brief. |
| Concurrent agents (L-43, L-50) | Disjoint file ownership; trade.py hunk after AUT-5a; full gate after each merge; one writer per capture file; per-agent scratchpads. |
| Statistical capacity | Census; ≥ 1 real fill per real day and ≥ 5 per window; 2–3 takes a day measured. |
| KILL 2027-01-25 | Planning ETA leaves about 13 weeks. If TERMINAL fires first, there is no sender and AUT-1 stays "machinery proven, window paused". |
| Upstream slips (ARCH-0, AUT-5a, AUT-6, AUT-2) | WP0, WP1, WP2, WP4, WP6's core do not depend on AUT-5a/AUT-6. No stub restarts, vetoes or alerts outside the contracts. The canary section is optional for the proof. |
| An ARCH widening is refused (N1–N5) | N1: exit capture stays OrderLink-only, leg D for exits `PENDING_CONTRACT`; no FQ exits exist. N2: the guard still refuses, logging `capture_gap` with detail `untagged`. N3: the `is-active` re-check bounds the race. N5: an overnight exhaustion leaves `recorder_stale` vetoing until 00:00Z, an accepted availability cost, stated in the policy ruling. |

---

## 9. Binding-constraint compliance

- **Nautilus immutability:** only native extension (`Order.tags`, a `Strategy` subclass calling `super()`, `Actor` msgbus subscriptions, `clock.set_timer`). Nothing under `nautilus_trader` is touched.
- **Operator caps:** never read, assigned, defaulted or logged; `test_autonomy_never_reads_or_writes_operator_controls` is extended to AUT-1's paths. Prose names no cap env var (L-39).
- **`allow_short`:** untouched; every entry stays a BUY; capture observes.
- **NO-SEND firewall:** exec client unedited and byte-pinned; no new egress host; alerts use the existing `alerts.env` key; capture units hold no venue credential.
- **Master enablement and permit:** AUT-1 only adds refusals. It never constructs, mints or reads permit authority; `test_autonomy_never_touches_enablement_permit_or_firewall` is widened to `strategy/autonomy_capture/` and `runtime/capture_*`.
- **PREREG via ruling:** no statistical semantics change; HEALTH census verdicts; action mapping left to the AUT-5 policy ruling.
- **Safety tests never weakened:** every §4 test stays green unedited; widenings follow L-12; nothing deleted or relaxed.

---

## 10. Self-score

r1 claimed 90; the reviewers scored it 76. The gap was real: r1 trusted its own writer for its own audit, had no independent denominators, put OnFailure on a path that swallows failures, used `RuntimeMaxSec` on oneshots, proposed a restart cap above the ceiling, and scheduled the drill in the rotate hole. r2 is scored against that record.

| Axis | Max | Score | Note |
|---|---|---|---|
| Fidelity | 20 | 17 | Every obligation mapped; W6, W9–W13 absorbed; ARCH ceilings respected (cap corrected to 3). Five ARCH contradictions stay open (§11 N1–N5), and two of them (N1, N2) are C1/C5 widenings AUT-1 depends on. |
| Correctness | 20 | 16 | The new legs are anchored in code read at `4b8347a6`: funnel per-boot semantics, node-log line formats, exec-store prefixes, the `extend_dedupe:` format, the notifier swallow, systemd oneshot semantics. Nine premises remain WP0-deferred: msgbus wildcard, override dispatch, wire body, data topics, SIGCONT, HTTP timeout, silence and growth cadences, the `client_order_id` date format, the drill window. |
| Specificity | 15 | 14 | Exact modules, call sites, keys, legs, states, thresholds, units and test names. Several thresholds take their final value from WP0. |
| Acceptance | 20 | 17 | Every criterion maps to a command or path, with a spot check that uses the node log and the exec store independently of AUT-1's code. The live proof still depends on AUT-6's delivery journal, which AUT-1 cannot prove alone. |
| Autonomy-safety | 15 | 13 | Restrictive-only; exits never blocked; no unit-file or env edits by the bot; mutual watch; durable caps. The `recorder_stale` veto and the drill's deliberate tape loss are judgement calls, and N5 has an availability cost if refused. |
| Reuse | 10 | 8 | Native tags, events, actors and timers; existing exec store, logs, funnel, settlement reader, retention, alert and restart paths. r2 adds more new parts than r1 (watchdog, node-log parser, tape marks), each justified in §2. |
| **Total** | 100 | **85** | |

---

## 11. Contradictions and gaps against ARCH (r1 items 1–8 carried; N1–N5 new in r2)

1. The README "no NBP positive log line" is stale; the gap is absence detection (§3.5.1).
2. Idle timeout: Breezy configures 600 s; horizons derive from it.
3. C1 `OrderLink.intent_id` cannot be populated by the node (byte-pinned exec client); AUT-1 writes null and the audit uses resolver contexts. Rev 5 should mark it nullable.
4. C1 names `depth_ref` and `forecast_input_sha256` with no preimage store; AUT-1 adds `derived/capture/blobs/`.
5. C1's `decisions/` path is an exception to the `{state,derived,registry,evidence}` rule; AUT-1 follows C1.
6. One daily file with node and offline writers would breach L-50; AUT-1 adds `.offline.jsonl`.
7. Sequencing: AUT-1's composition hunk is Wave 1b, after AUT-5a.
8. AUT-1 implements the capture and feed NODE_LOCAL detectors and the unit membership; AUT-6 owns the restart call site, catalogue and intraday producer.
- **N1. C1 has no exit decision kind.** C1's `DecisionRecord.kind` enum is `Take | Refuse | NotExecutable | NotDPlus1 | TrySubmit | EntryVeto`, and invariant (ii) requires every durable fill to join to a `DecisionRecord`. An exit fill (a CRH-style exit seam, `exit_tags.py`) cannot satisfy it. Requested L-12 widening: `kind += "Exit"`, `depth_ref` nullable for `Exit` only, id per §3.3.1.
- **N2. `capture_untagged` is missing from the C5 `VetoReason` enum.** C1's failure rule names `capture_untagged`; the closed enum in C5 (Rev 4 :476; Rev 5 :484) lists only `feed_stale`, `recorder_stale`, `permit_lapsed`, `capture_gap` among node-local reasons.
- **N3. Restart verb.** ARCH §4.5 pins `["systemctl","--user","restart",unit]`; the repo's own rotate unit uses `try-restart` to respect a deliberate stop (`breezy-quote-tape-rotate.service:55`). AUT-1 asks ARCH to pin `try-restart`.
- **N4. `RuntimeMaxSec` on oneshot study units.** ARCH §5.2 (Rev 4 :793; Rev 5 :833), §10 AUT-3 and AUT-6 and the Rev 5 post-STOP slot (:679) require `RuntimeMaxSec` to bound oneshot studies. systemd 259's `man systemd.service` states it has no effect on `Type=oneshot` and names `TimeoutStartSec=`. Every area's runtime bound is currently unenforced as written.
- **N5. The self-heal "day".** ARCH §4.5 and W11 count restarts per `<date>` without defining the day. A UTC-date window lets an overnight exhaustion persist through the 16:50Z LAUNCH (C9). AUT-1 asks for the trading day `[16:45Z, +24 h)`.

---

## §R2 Disposition (review `reviews/AUT-1-r1-merged.md`)

**C1–C19: 19 FIXED, 0 REJECTED.** C14 is fixed with one sub-clause rejected on code evidence (below). ARCH-delta items and two self-found defects follow the table.

| C | Disposition | Where / evidence |
|---|---|---|
| C1 | FIXED | §3.7 legs R1 (per-record bijection with node-log `SHADOW_DECISION` Take/TrySubmit lines on `now_ns`), R2, R3 (funnel, segmented by boot because `fq_funnel_<boot day>.jsonl` is per boot and cumulative, `decision_funnel.py:143-180`), O (every `venue_id/`, `resolver/` record and node-log order line, not only fills), tape marks (node-independent `PositionMark(source="tape")`); CS-2 stores the shadow line's `now_ns`. Tests `test_funnel_vs_capture_count_mismatch_fails`, `test_deleted_capture_record_fails_day`, `test_every_exec_store_order_record_has_order_link`, `test_tape_marks_written_for_open_positions_without_node` (WP6). §8 states the limit of independence. |
| C2 | FIXED | §3.7 leg F (`fill_by_day` == `fill/` scan == node-log `OrderFilled` ∪ resolver); fail-loud input rules (open error, decode error, key-schema drift, unreadable log → `ERROR`, never `NO_INPUT`); §3.6.4 watchdog (26 h dead-man, missing audit file for an elapsed day); §3.8 OnFailure gated on AUT-6 migrating `study_failure_notifier` (`:274-277` swallows today). Tests in WP5, WP6. |
| C3 | FIXED | §3.6.2 `WRITER_STALL` state (counters rising, bytes flat), byte total rules, midnight rotation; WP0 items 2 and 3 measure growth cadence and recorder silence p99.9; tests `test_counters_rising_bytes_flat_is_writer_stall`, `test_healthy_fixture_never_writer_stall`, `test_frozen_writer_fixture_triggers_writer_stall_and_restart`. |
| C4 | FIXED | §3.3.3 failure path: short-write check, Nautilus-logger `CAPTURE_WRITE_FAILED`, second journal `evidence/capture/incomplete_<date>.jsonl`; the day fails on leg R1 regardless of markers; `test_marker_write_failure_still_fails_day`, `test_short_write_is_failure`. |
| C5 | FIXED | Drill at Sunday 12:30Z, guard 13:00Z (§3.8, WP7), ≥ 1 h after rotate, outside 09:00–09:45Z and 16:30–17:00Z; WP0 item 7 confirms with the take-hour distribution and instance age; `test_drill_window_is_not_in_rotate_hole_or_launch`. |
| C6 | FIXED | CS-1 work order (on-change lookup before any sha or blob); CRITICALs via the W9 outbox; `CAPTURE_FSYNC_P99_BUDGET_MS` from WP0 item 6 and the WP2 benchmark; `test_blob_and_sha_work_only_after_on_change_check`, `test_guarded_submit_latency_independent_of_webhook`. |
| C7 | FIXED | §3.3.1 `compute_exit_decision_id` from the four exit tags; §3.3.5 step 1 writes `Exit` + OrderLink, no CRITICAL on a legitimate exit; leg D exit branch; tests `test_legitimate_exit_raises_no_critical`, `test_every_exit_fill_joins`. Requires C1 widening N1. |
| C8 | FIXED | §3.3.5 construction: writer and outbox required keyword-only, `TypeError` at compose → boot fails closed; `capture_untagged` in `VetoReason` (N2); tests `test_capture_guarded_strategy_without_writer_refuses_construction`, `test_fq_compose_without_capture_writer_fails_boot`, `test_capture_untagged_is_a_veto_reason`. |
| C9 | FIXED | §3.6.2 `STALLED` uses `ACTIVE_HOURS_UTC` and `QUIET_HOURS_MULTIPLIER = 4`; `HUNG` and `WRITER_STALL` not hour-gated (with reasons); trading-day counter window resets at 16:45Z before LAUNCH (N5); tests `test_stalled_uses_quiet_hours_multiplier`, `test_restart_window_resets_before_launch`. |
| C10 | FIXED | §3.4 `never_submitted` classification (link present, no venue/resolver/lifecycle/log evidence, boot ended) and `order_pending` while the boot runs; `test_crash_between_link_and_submit_classified_never_submitted`. |
| C11 | FIXED | §6 one qualifying-day rule matching the README text quoted in §1.1 (canary-only day counts as a day, never toward the 5; a canary cannot rescue a real-fill FAIL); producer AUT-2, delivery AUT-6 (§5.1); tests `test_canary_only_day_qualifies_day_but_not_real_fill_count`, `test_real_fill_day_cannot_be_rescued_by_canary`. |
| C12 | FIXED | §3.6.2 step 1: durable counter `evidence/selfheal/<date>.json` via AUT-6 (W11); `restarts_today` read from it; `test_restart_cap_survives_watch_process_restart`. |
| C13 | FIXED | §3.5.1 per-instrument `_last_frame_ns` veto and venue-wide `MD_SILENT_FRACTION_MAX = 0.5`; tests for per-instrument, above, at-limit and never-seen. |
| C14 | FIXED (one sub-clause REJECTED) | §3.7 leg T reads `extend_dedupe:`; `flat_root != none`, an **unfiltered** `custom_depth_truncation` count > 0, or a missing line → tape CRITICAL and `capture_tape_ingest` FAIL; tests in WP6. **Rejected:** treating any non-zero `custom_depth_truncation` count as tape-incomplete. Evidence: `DepthTruncation` records are emitted whenever a venue snapshot exceeds 10 levels and "depth capture is unaffected" (`data.py:1817-1821`, `:1824-1845`); PROGRESS ING-2-AMEND2 (`docs/core/PROGRESS.md:52`) defines the healthy state as `custom_depth_truncation:<n>/0` with `flat_root=none`. A filtered count > 0 is the normal state, so alerting on it would page daily on healthy tape. `test_filtered_depth_truncation_count_is_healthy` pins this. |
| C15 | FIXED | `test_reason_is_closed_enum`, `test_utc_rollover_open_failure_is_loud` (WP1); availability cost stated in §3.2. |
| C16 | FIXED | WP2 tests `test_refused_order_never_reaches_cache`, `test_duplicate_or_malformed_tag_refused`, `test_capture_refused_log_has_entryveto_record`; WP2 explicitly gated on WP0's dispatch premise, with the fallback planned in a reviewed r3 if refuted. |
| C17 | FIXED | §3.7 leg N (per configured cycle: `NBM_NBP_PUBLISHED` and per-station `FQ_VECTOR_COMPLETE`), `capture_nbp_census` verdict; leg B ties forecast blobs to `FQ_VECTOR_COMPLETE`; tests in WP6. |
| C18 | FIXED | §3.6.4 `breezy-capture-watchdog` and the mutual stamp check in the watch; off-host canary as the backstop; tests `test_watchdog_raises_when_watch_state_stale`, `test_watch_raises_when_watchdog_stamp_stale`. |
| C19 | FIXED | §10 re-scored 85, with r1's overstatement named and each axis's residual stated. |

**ARCH deltas absorbed** (`reviews/ARCH-r4-merged.md`):

| Item | Disposition | Where |
|---|---|---|
| W6 | APPLIED | `capture_reader` takes fills as values and never imports `exec/client.py` (`test_reader_takes_fills_as_values_never_imports_exec_client`); the audit, in `analysis` above `adapters`, imports the key constants. AUT-1 adds nothing to `entry_guard`. |
| W9 | APPLIED | Node CRITICALs only enqueue (§3.3.3, §3.3.5); `test_guarded_submit_latency_independent_of_webhook`. |
| W10 | APPLIED | Detectors register with the required `entry_veto` slot; the guard's writer and outbox are required the same way (C8). |
| W11 | APPLIED | C12. |
| W12 | APPLIED | Drill records and fills are captured, joined and counted by detectors (`test_detectors_count_drill_records`, `test_drill_fills_joined_and_marked`). |
| W13 | APPLIED | Live proof reads two days of delivery journals (`test_delivery_row_found_on_next_day_journal`). |
| Systemd note | APPLIED | Every oneshot uses `TimeoutStartSec` (§3.8, `test_oneshot_units_use_timeout_start_sec_not_runtime_max_sec`); ARCH-side contradiction raised as N4. |

**Self-found defects fixed in r2:** r1's proposed `SELF_HEAL_MAX_RESTARTS_PER_UNIT_PER_DAY = 4` exceeded the ARCH ceiling of 3, so it is now 3 (§3.6.2). r1's WP5 activation hand-restarted the recorder inside the listing hole; it is replaced by the next scheduled rotate (§3.6.3).
