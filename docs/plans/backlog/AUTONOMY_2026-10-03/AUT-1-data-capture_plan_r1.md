# AUT-1 — Data capture: area plan, round 1

## 0. Header

| Field | Value |
|---|---|
| ID | AUT-1 |
| Title | Data capture: every decision, order, fill, mark and settlement for every family, joined on one `decision_id`, audited daily, with stall self-heal |
| Round | r1 (2026-10-03) |
| ARCH consumed | `AUTONOMY_ARCHITECTURE.md` Rev 3, sha256 `66002f49ca33515e3515102d9dbb4134935e0573f85a98a5c41f1352f91361af` (byte-identical to the scratchpad `ARCH_rev3.md`), **plus the pending Rev 4 deltas** `reviews/ARCH-r3-merged.md` Z1–Z20, treated as applied. The deltas that touch AUT-1 are Z2, Z4, Z6, Z11, Z13, Z14, Z15 and Z16. |
| Code baseline | `feat/data-capture-and-risk` @ `4b8347a6`. Every `file:line` below was read at that sha. |
| Current score | 2 |
| Target | 3 |
| Upstream | ARCH-0 (Wave 0: `persistence/autonomy/` schemas, C4 writer, C6 Protocols, `VetoReason`, `pins.py`); AUT-5a (`ResolvedFamily`, `RegistryWatchActor`, the `entry_veto` slot in `try_submit`, sole owner of `app/trade.py` in Wave 1); AUT-6 (`deliver_with_proof`, the self-heal restart call site, the detector catalogue, the intraday producer) |
| Downstream | AUT-2 (C1 records, the blob store, the join reader, `SettlementRecord`, the canary store); AUT-4 (per-decision depth and forecast preimages, `CAPTURE_INCOMPLETE` admissibility); AUT-6 (`DetectorEvent` records, NODE_LOCAL detectors, HEALTH verdicts); AUT-5 (HEALTH verdicts and the proposed policy-map rows) |

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

It is bound by the README scale 3(a)–(f) and the live-proof window rule (ARCH §5.3). A day counts only with at least one real fill or a tagged canary fill. Zero-fill days extend the window. The window needs at least 5 real fills, and canary and drill fills never count toward that.

### 1.2 ARCH §10 "Area plan obligations", AUT-1 (verbatim)

> **AUT-1:** the `CaptureAdapter` call sites per composable kind; measured C1 volume per day; the `EntryVeto` record writer; the node-local observations behind `feed_stale`, `recorder_stale`, `capture_gap` (source, period, clear condition); the recorder and feed self-heal restart, naming each unit it adds to `SELF_HEAL_RESTARTABLE_UNITS`; the daily join audit.

Where each obligation is met:

| Obligation | Section |
|---|---|
| `CaptureAdapter` call sites | §3.3 |
| Measured C1 volume | §3.2 |
| `EntryVeto` writer | §3.3.4 |
| `feed_stale`, `recorder_stale`, `capture_gap` | §3.5 |
| Self-heal and units | §3.6 |
| Daily join audit | §3.7 |

### 1.3 Known facts this plan must address (from the brief), with the code check

| Fact | Verified state at `4b8347a6` | Where addressed |
|---|---|---|
| The recorder can sit "active" while capturing nothing. | **Partly fixed, still open.** GL-12 widened the connect fail-fast to all of `_connect` (`data.py:1101-1147`), and the empty-discovery retry exists (`data.py:1082-1099`). Open classes remain: a wedged event loop, a writer that is alive but stalled, a non-fatal reconnect loop, and MemoryHigh thrash (L-49). Nothing outside the process checks that bytes are landing. | §3.6 (heartbeat plus external watch plus restart) |
| The NBP feed has no positive log line. | **Stale.** FQ-S6 added `NBM_NBP_PUBLISHED` (`nbm_quantile_actor.py:545-551`) and `FQ_VECTOR_COMPLETE` (`forecast_subscriber.py:213-221`). Both appear in the live log `breezy-trade-20261002T205521Z.log`: 2 and 8 lines. **The real gap is absence detection.** `_check_stale_cycle` only logs (`nbm_quantile_actor.py:425-449`), no alert is delivered and no entry is vetoed. A hung fetch leaves `_poll_in_flight` true forever (`:407-423`), so every later poll counts as `poll_overlapped`. | §3.5.2, WP4 |
| The exit study reports `no_taken_latch` for FQ. | Confirmed. `prereg_admission.py:476-499` joins fills to **CRH** taken-latch keys under a family prefix. FQ's latch is kind-scoped (`forecast_quantile_ladder/trial/`, G28) with another shape, so every FQ fill becomes `no_taken_latch`. | The C1 join (§3.4) replaces latch-based attribution; the AUT-2 scorers consume it. |
| No single `decision_id` join covers every family. | Confirmed. The FQ funnel holds counts only (`decision_funnel.py:52-96`). FQ submits with no tags (`strategy.py:680-688`). | §3.3, §3.4 |
| The WS cap is 10 subscriptions per connection, shared across MARKET_DATA and TRADE (L-45). | Confirmed (memory `venue-ws-subscription-cap-is-shared`). | **AUT-1 adds no venue subscription.** The node-side capture uses passive message-bus topic subscriptions only, pinned by test (§3.3.5). A recorder restart is stop-then-start under systemd, so the recorder's 6 connections plus the node's 3 never overlap into 15. |
| Nautilus closes an idle socket after 60 s with no data frame. | **The mechanism is right, the number is stale.** Nautilus `idle_timeout_ms` fires on no Text/Binary frame, and pings do not reset it. Breezy's configured value is now **600 s** (`adapters/polymarket_us/config.py:293`, `85faa02`), and quiet shards still cycle every 10 min. | Every silence horizon is derived from the configured `ws_idle_timeout_secs`, never hardcoded: `MD_SILENCE_S = max(900, ws_idle_timeout_secs + 300)` (§3.5.1). |

---

## 2. L-1 null hypothesis and reuse

Every new component is listed with the native or existing capability checked and the verdict. "WP0" marks a premise that the WP0 characterisation test must pin **before** the slice relying on it starts (L-47: no blanket "verified").

| New component | Capability checked (file:line) | Verdict |
|---|---|---|
| Per-decision capture record | Nautilus `StreamingConfig` (rejected by ARCH C1 for the order process); FQ funnel counts (`decision_funnel.py:52-181`); CRH `OfferTape` JSONL plus byte cap (`crh/offer_tape.py:335-439`) | **Extend.** A new writer copies the `OfferTape` shape (best-effort append, unbounded counters, byte cap) and adds fsync on order-path records plus a loud cap. The funnel stays as it is. |
| `decision_id` carrier on orders | Native `Order.tags` (`model/orders/base.pyx:218`); exit prefixes (`persistence/exit_tags.py:37-48`); the exec client's tag loop compares exit prefixes only and ignores other tags (`exec/client.py:5375-5391`) | **Reuse native.** Add `DECISION_ID_TAG_PREFIX = "breezy:decision_id="` to `exit_tags.py`. The exec client is **not edited**; it is byte-pinned by `test_exec_client_is_byte_identical_to_its_pre_sl13_sha256`. WP0: the tag is absent from the wire body (`submit_chain.request_fingerprint` covers body bytes only, `submit_chain.py:259-278`). |
| Order lifecycle capture | `ExecutionEngine` publishes `events.order.{strategy_id}`, `events.position.{strategy_id}` and `events.fills.{instrument_id}` (`execution/engine.pyx:910-926`, nautilus 1.231.0); `Actor.msgbus.subscribe` | **Reuse native.** One `Actor` subscribes `events.order.*` and `events.position.*`, which is family-agnostic by construction. WP0: wildcard delivery. L-16: `MessageBus.publish_c` has no try/except, so a handler raise unwinds into the **execution engine**. Every handler is therefore catch-all. |
| Submit-time refusal for untagged or unlinked orders (fail-closed for every kind) | Nautilus `RiskEngine` (immutable; `TradingState.REDUCING` insufficient, ARCH §2); exec client deny chain (byte-pinned); the strategy's own `submit_order` | **Extend natively by subclassing.** `CaptureGuardedStrategy(Strategy)` overrides `submit_order` and calls `super()`. WP0: a Python override of the `cpdef submit_order` is dispatched for Python callers (FQ calls `self.submit_order(order)` from Python, `strategy.py:688`). |
| Depth snapshot at decision time | Recorder Depth10 tape (a separate process with gaps; L-20 catalog lag); the node's own `OrderBookDepth10` with `ts_event` = venue `transactTime` (`parsing.py:851-895`) | **New, minimal.** A content-addressed preimage of the node's own Depth10 row, written at decision time. The recorder tape is a cross-check only, never a join dependency, so a recorder blip cannot break the 100% join. |
| Forecast inputs per decision | `ForecastQuantileState.value_at` returns the exact vector used (`forecast_state.py:306-315`); no durable forecast store exists in the node | **New, minimal.** A content-addressed preimage of the `ForecastQuantileVector` per distinct vector, about 12 per day. |
| Market-data freshness in the node | The data client counters `quotes_published` and `tape_gaps` (`data.py:865-1038`) are reachable only from the adapter object; Nautilus data topics `data.book.depth.*` / `data.quotes.*` | **Reuse native.** A passive topic subscription in the lifecycle actor (no `subscribe_*` command, so no venue slot) updates one `last_frame_ns`. WP0: the topic names. |
| NBP freshness and hang recovery | `_check_stale_cycle` (`nbm_quantile_actor.py:425-449`), `latest_available_cycle_ns` (`:382-400`), `_poll_in_flight` (`:407-423`) | **Extend.** A detector reads `ForecastQuantileState`; the actor gains a poll-hang reset. No new transport. |
| Recorder liveness | systemd `Restart=always` (blind to a zombie); `QuoteTapeDiskMonitor` (disk only, `quote_tape_disk_monitor.py:51-179`); `QuoteTapeGap` records (data, not liveness) | **New: a heartbeat file written by the data client (opt-in) plus an external watch unit.** Neither systemd nor Nautilus offers a "bytes are landing" probe. |
| Restarting units | `breezy-quote-tape-rotate.service` already uses `systemctl --user try-restart` (unit file); the AUT-6 restart call site plus `SELF_HEAL_RESTARTABLE_UNITS` (ARCH §4.5) | **Consume AUT-6.** AUT-1 writes no subprocess restart code. It only names units and calls the AUT-6 API. |
| Fill source for the join | Durable `DurableFillRecord` with `client_order_id` (`exec/client.py:949-976`); `FILL_BY_DAY_KEY_PREFIX` (`:429`); read-only `SELECT key, value FROM state` over a `mode=ro` URI (`prereg_admission.py:326`, `fill_time_count.py:123`) | **Reuse.** No exec-store write and no new key. |
| Settlement | `read_climate_day_including_corrections` (`persistence/catalog.py:637`), as used by `score_live_trials.py:901-903` | **Reuse.** The audit writes `SettlementRecord` from it. |
| Build identity | `resolve_build_revision` (`runtime/build_sha.py:147-190`); Nautilus kernel `instance_id` | **Reuse** for `build_sha` and `node_boot_id`. |
| Retention | `scripts/ops/decisions_retention.py:77-80` regex allowlist | **Extend by one alternation** (L-12 widening). |
| Alerts with delivery proof | AUT-6 `deliver_with_proof` (ARCH §4.6); `emit_alert` swallows failures (G25) | **Consume AUT-6** for every CRITICAL (Z13). |

---

## 3. Design

### 3.1 Module map (layering checked against `pyproject.toml:74-101`)

| Module | Layer | New or edit | Purpose |
|---|---|---|---|
| `src/breezy/persistence/autonomy/capture_ids.py` | persistence | new | `compute_decision_id`, `depth_ref_of`, `forecast_input_sha256_of`; canonical forms; no Nautilus import (the depth canonicaliser takes plain tuples) |
| `src/breezy/persistence/autonomy/capture_writer.py` | persistence | new | `CaptureWriter`, `CaptureIdentity`, `CaptureWriterHealth`, `mark_capture_incomplete` |
| `src/breezy/persistence/autonomy/capture_blobs.py` | persistence | new | `BlobStore` (content-addressed preimages) |
| `src/breezy/persistence/autonomy/capture_reader.py` | persistence | new | `read_capture_day`, `join_fills_to_decisions`; the API AUT-2 consumes |
| `src/breezy/persistence/autonomy/capture_watch_state.py` | persistence | new | `capture_watch/v1` and `recorder_heartbeat/v1` schemas plus the single-read loader |
| `src/breezy/persistence/exit_tags.py` | persistence | edit | add `DECISION_ID_TAG_PREFIX` (an L-12 widening of `__all__`) |
| `src/breezy/strategy/autonomy_capture/guarded_strategy.py` | strategy | new | `CaptureGuardedStrategy(Strategy)` |
| `src/breezy/strategy/autonomy_capture/lifecycle_actor.py` | strategy | new | `CaptureLifecycleActor(Actor)`: order, position and data topics, the 60 s health timer |
| `src/breezy/strategy/autonomy_capture/node_observations.py` | strategy | new | NODE_LOCAL detectors `capture_writer_health`, `md_feed_freshness`, `recorder_liveness` (C6 `Detector`) |
| `src/breezy/strategy/forecast_quantile_ladder/capture_adapter.py` | strategy | new | `FqCaptureAdapter` (C6 `CaptureAdapter`) plus the NODE_LOCAL detector `nbp_feed_freshness` |
| `src/breezy/strategy/forecast_quantile_ladder/strategy.py` | strategy | edit | base class becomes `CaptureGuardedStrategy`; edits in `_emit_shadow_decision`, `_emit_decision_outcome`, `_maybe_submit` and `on_order_book_depth` only. **`try_submit` belongs to AUT-5a.** |
| `src/breezy/ingest/nbm_quantile_actor.py` | ingest | edit | poll-hang reset (WP4) |
| `src/breezy/adapters/polymarket_us/data.py` and `config.py` | adapters | edit | opt-in `heartbeat_path` on the data-client config; `_write_heartbeat` (WP5) |
| `src/breezy/runtime/node_config.py` | runtime | edit | `build_quote_tape_node_config` sets `heartbeat_path`; the trade-node config never does |
| `src/breezy/runtime/capture_watch.py` and `capture_watch_cli.py` | runtime | new | recorder and NWS-ingest probe, classification, self-heal through AUT-6, state file, journal |
| `src/breezy/runtime/capture_stall_drill_cli.py` | runtime | new | weekly injected recorder stall (WP7) |
| `src/breezy/analysis/capture_audit.py` and `capture_audit_cli.py` | analysis | new | daily join audit, `SettlementRecord` writer, HEALTH verdict, evidence |
| `src/breezy/analysis/capture_live_proof.py` and `capture_live_proof_cli.py` | analysis | new | 7-day window roll-up (WP7) |
| `src/breezy/app/trade.py` | app | edit, **one hunk, Wave 1b, after AUT-5a merges** | construct `CaptureIdentity`, `CaptureWriter`, `FqCaptureAdapter` and `CaptureLifecycleActor` inside `_compose_forecast_quantile_ladder` (`:676-850`); append the actor to `extra_actors` (`:823`) |
| `deploy/systemd/breezy-capture-watch.{service,timer}`, `breezy-capture-audit.{service,timer}`, `breezy-capture-live-proof.service`, `breezy-capture-stall-drill.{service,timer}`, `breezy-capture-stall-drill-guard.{service,timer}` | deploy | new | units (§3.8) |
| `scripts/ops/decisions_retention.py` | scripts | edit | widen the regex to `capture_[a-z0-9_]+(\.offline)?` |

**Entry points.** Every new process is started as `/home/jon/breezy/.venv/bin/python3 -m <module>`. No `[project.scripts]` entry is added, because a new console script needs a reinstall into the shared venv, which is forbidden (L-51; memory `never-uv-sync-the-shared-venv`).

### 3.2 C1 volume (measured, obligation 2)

- **Measured** from the live node log `~/.local/share/breezy/logs/breezy-trade-20261002T205521Z.log` (20:55Z 10-02 to 03:57Z 10-03, about 7 h, a streaming parse of `SHADOW_DECISION` lines).
  - 973,921 FQ evaluations across 24 `(station, climate_day, rung_id, side)` keys.
  - Applying the C1 rule (a `Refuse`/`NotExecutable`/`NotDPlus1` is written only when `(key, kind, reason)` changes, L-29) gives **59 records**.
  - The funnel for the full UTC day 10-01 shows 3,288,397 evaluations, 2 `Take` and 2 `TrySubmit` (`fq_funnel_2026-10-01.jsonl`, final row).
- **Projection (upper bound for the cap, not a measurement):**
  - about 250 on-change `DecisionRecord`s per day;
  - plus, per order: 1 Take, 1 TrySubmit, 2 OrderLink, 2–3 LifecycleEvent and 1–2 PositionMark, which is about 8 records per order at 2–5 orders a day;
  - plus `DetectorEvent`s on state transitions only, fewer than 50 a day;
  - **under 400 records a day, about 0.4 MB a day** at ~1 KB per line.
- **Blobs:** fewer than 300 depth preimages (~1.5 KB each) and about 12 forecast preimages a day, **under 0.5 MB a day**.
- **Cap:** `CAPTURE_MAX_BYTES_PER_FAMILY_DAY = 64 MiB`, more than 150× the projection. Hitting it is loud (§3.3.3).
- WP0 re-measures one **full** UTC day and records it in the WP0 evidence file. If the full-day count exceeds 5,000 records, the cap is revisited in a reviewed commit before WP2 merges.

### 3.3 Capture core, `CaptureAdapter` call sites, the guard

#### 3.3.1 Identity and ids (`capture_ids.py`)

- `compute_decision_id(family_id, manifest_sha256, artefact_sha256, station, climate_day, rung_id, side, eval_ns) -> str`. It returns the first 32 hex characters of the sha256 of `"|".join([...])`, with `climate_day.isoformat()` and `str(eval_ns)`, in **exactly** the C1 field order.
  - `eval_ns` is the `now_ns` that `evaluate_snapshot` receives (`strategy.py:502-575`), i.e. the Nautilus `clock.timestamp_ns()`, and it is recorded in the record.
  - Recomputation always uses the stored fields.
- `depth_ref_of(instrument_id, ts_event, bids, asks) -> str`.
  - It is the sha256 of `"depth10/v1|" + instrument_id + "|" + str(ts_event) + "|B|" + ";".join(f"{px}:{sz}") + "|A|" + ...`, using only levels with size > 0. That skips the Depth10 size-0 Arrow pad exactly as `best_order` does.
  - `ts_init` is excluded, so the node's row and the recorder's row for the same venue frame (both `ts_event = transactTime`) hash equal.
- `forecast_input_sha256_of(vector, station) -> str`. It is the sha256 of the canonical JSON (`sort_keys=True`, `separators=(",", ":")`) of `{"schema":"fq_forecast_input/v1","station","q10","q25","q50","q75","q90","mean","sd","available_at_ns","cycle_runtime_ns","climate_day","model_version"}` (the fields of `ForecastQuantileVector`, `forecast_state.py:282-294`).

#### 3.3.2 Blob store (`capture_blobs.py`)

- Root: `~/.local/share/breezy/derived/capture/blobs/{depth,forecast_input}/<sha[:2]>/<sha>.json`.
- Directories are 0700 and files 0444.
- Writes are `mkstemp` plus `os.replace`; an existing sha is a no-op (idempotent).
- Reads follow the single-read rule: `O_NOFOLLOW` on every path component, one descriptor, hash and parse the same bytes.
- **Why this exists (ARCH gap, §11 item 4):** C1 names `depth_ref` and `forecast_input_sha256`, but nothing stores their preimages, so a sha alone would be unjoinable.

#### 3.3.3 Writer (`capture_writer.py`)

- `CaptureIdentity` (frozen) holds:
  - `family_id`, `manifest_sha256`, `artefact_sha256`;
  - `node_boot_id` (the Nautilus kernel `instance_id`);
  - `build_sha` (`resolve_build_revision()`);
  - `registry_seq`: from AUT-5a's `ResolvedFamily`, or `0` when `BREEZY_FAMILY_SOURCE` is not `registry`. After cutover the audit flags any `0` as a gap.
- The `drill` flag is **not** frozen. It is read per record from the AUT-5a watch actor's `drill_active(now_ns)`, the Z2 fold: true from DRILL_PROMOTE through its closing ROLLBACK, **including fills after a drill RESUME**.
- `CaptureWriter(identity, decisions_dir, blob_store, *, source: Literal["live","canary"], clock_ns)`.
  - Path for `source="live"`: `<decisions_dir>/capture_<family_id>_<UTC-date>.jsonl`, where `decisions_dir = catalog_root.parent / "decisions"`, the same directory as `trade.py:774` and `crh/composition.py:568-602`, as C1 requires.
  - Path for `source="canary"`: `<decisions_dir>/canary/capture_<family_id>_<UTC-date>.jsonl` (Z14). Reconciliation, `entry_guard` and the live audit leg never open `canary/`.
- Methods, each returning `bool` (written durably):
  - `write_decision(rec)`: on-change for non-Take kinds, always for `Take`/`TrySubmit`/`EntryVeto`.
  - `write_order_link(rec, *, fsync=True)`
  - `write_lifecycle(rec)`
  - `write_position_mark(rec)`
  - `write_detector_event(rec)`
  - `put_blob(kind, payload) -> sha`
- Serialisation is explicit `to_dict` (no `dataclasses.asdict`).
  - Each line is `json.dumps(sort_keys=True)` plus `"\n"`, written in one `os.write` to an `O_APPEND|O_WRONLY|O_CREAT` descriptor opened with mode 0600.
  - `os.fsync` runs on Take, TrySubmit, EntryVeto, OrderLink, LifecycleEvent and PositionMark. On-change refusals and DetectorEvents get flush only.
  - The node is the **only** writer of the live file (L-50). A mid-day relaunch is sequential, never concurrent, because the supervisor waits for exit.
- The on-change map is `dict[(station, climate_day, rung_id, side), (kind, reason)]`.
  - The 60 s health tick evicts keys with `climate_day < today_utc - 1`, so memory is O(subscribed keys) (L-29).
  - `test_on_change_map_is_bounded` pins it.
- **No silent cap.** A write error or the byte cap:
  - increments `write_errors` or `capped_rows` (unbounded ints);
  - sets `health.ok=False`;
  - raises a CRITICAL `CAPTURE_WRITE_FAILED` or `CAPTURE_BYTE_CAP` through `deliver_with_proof`;
  - writes `<decisions_dir>/capture_<family_id>_<date>.INCOMPLETE` (0444, JSON `{reasons:[...], first_ns}`) via `mark_capture_incomplete`, best effort;
  - makes the day `CAPTURE_INCOMPLETE`, so the audit FAILs it and AUT-4 treats it as inadmissible.
  - The writer never raises into a Nautilus handler (L-16).
- **Positive control.** At `on_start`, and at each 60 s tick while `health.ok=False`, the writer appends and fsyncs a `DetectorEvent(detector="capture_writer_health", state=AGREE)`. Only that success clears `health.ok` (§3.5.3).

#### 3.3.4 `CaptureAdapter` call sites per composable kind (obligation 1)

**Composable kinds today.** C6 gives full plug-ins only to kinds in `LIVE_GATE_ROUTED_KINDS = {forecast_quantile_ladder}`. `current_rung_hold`, `continuous_rung_hold` and `forecast_ladder` carry `RefusingPlugin`, so they never compose. **AUT-1 therefore wires exactly one kind.** A future kind gets its `CaptureAdapter` in the same change that admits it (C6 YAGNI rule), and the gate test below makes that unavoidable.

`FqCaptureAdapter` (C6 `CaptureAdapter`) has these call sites in `forecast_quantile_ladder/strategy.py`:

| # | Call site (current line) | What changes |
|---|---|---|
| CS-1 | `evaluate_snapshot` → `_emit_shadow_decision(self._shadow_log_line(...))` (`:564-581`) | `_emit_shadow_decision` additionally calls `self._capture.on_decision(decision, ctx)`. `ctx` = `(eval_ns=now_ns, station, climate_day, rung_id, side, instrument_id, ask_px)` plus the strategy's `self._last_depth[instrument_id]` and the vector returned by `self._quantile_actor.state_for(actor_station).value_at(now_ns)`. That is the same object the decision used: it is captured once inside `evaluate_snapshot` and passed through, never re-read. The adapter computes `decision_id`, puts the depth and forecast blobs, and writes a `DecisionRecord` (`kind` = the type name; `reason`; `p_hat`/`p_lower`/`p_upper`/`ev_net` on Take only, else null; `artefact_sha256` and `manifest_sha256` from the identity). It returns the `decision_id`. |
| CS-2 | `_emit_decision_outcome(take, refusal)` (`:690-709`) | It now takes `decision_id`. If `refusal` is in the closed `VetoReason` set (ARCH-0), the adapter writes `DecisionRecord(kind="EntryVeto", reason=refusal)`, on-change per key. **This is the `EntryVeto` writer.** Otherwise it writes `kind="TrySubmit"` with `reason=refusal or "submitted"`, always and fsynced. The funnel call is unchanged. |
| CS-3 | `_maybe_submit(take, *, limit_price)` → `order_factory.limit(...)` (`:680-688`) | It gains the keyword `decision_id`, passes `tags=[f"{DECISION_ID_TAG_PREFIX}{decision_id}"]` to `order_factory.limit`, and then calls `self.submit_order(order)`, which the guard intercepts. `_evaluate_instrument_update` threads the id from CS-1 to here. |
| CS-4 | `on_order_book_depth(depth)` (`:713-729`) | Before `_safe_evaluate`, `self._last_depth[depth.instrument_id] = depth`, a dict bounded by subscribed instruments. A `Take` reached from `on_quote_tick` with no `_last_depth` entry is refused at CS-2 as `capture_gap` (an existing `VetoReason`) and recorded. Depth is FQ's **required** trigger (`:714`), so this path is rare. |
| CS-5 | `shadow_only=True` branch (`:659-665`) | CS-1 has already captured the Take, and no order exists. Nothing else changes. |

#### 3.3.5 Guard: family-agnostic fail-closed submit (`guarded_strategy.py`)

`class CaptureGuardedStrategy(Strategy)`, `submit_order(self, order, position_id=None, client_id=None, params=None)`:

1. **Exit orders are never refused by capture.** If any tag starts with `EXIT_RULE_TAG_PREFIX`, the guard writes the OrderLink if a `decision_id` tag is present. Otherwise it emits a `DetectorEvent(capture_writer_health, DISAGREE)` with the detail `untagged_exit`, raises a CRITICAL, and then calls `super().submit_order(...)` in every case. Exits reduce risk and stay live (README binding constraints).
2. It parses the tags. **Exactly one** `breezy:decision_id=` tag with 32 lowercase hex characters is required. Otherwise the guard refuses: no `super()` call, nothing reaches the cache, log `CAPTURE_REFUSED reason=capture_untagged`, CRITICAL, and a DetectorEvent.
3. If `self._capture_writer.health.ok` is False, it refuses with `capture_gap`.
4. `write_order_link(OrderLink(client_order_id, venue_order_id_sha256=None, intent_id=None), fsync=True)`. If that returns False, it refuses with `capture_gap`.
5. `super().submit_order(...)`.

`test_every_full_plugin_kind_strategy_subclasses_capture_guard` walks `NODE_PLUGINS` (ARCH-0). For every kind whose plug-in is not `RefusingPlugin`, the strategy class the composer builds must be a subclass of `CaptureGuardedStrategy`. **So no family can send without capture, by construction** (README 3(b)).

`intent_id` is null at submit. The exec client arms the intent internally (`runtime/submit_intent.py:236-266`, a singleton with no `client_order_id`), and it cannot be edited (byte pin). See §11 item 3.

#### 3.3.6 Lifecycle and marks (`lifecycle_actor.py`)

`CaptureLifecycleActor(Actor)`:

- `on_start` runs `self.msgbus.subscribe("events.order.*", self._on_order_event)`, `self.msgbus.subscribe("events.position.*", self._on_position_event)`, and the passive data topics (§3.5.1). Then `clock.set_timer("aut1-capture-health", 60 s, ...)`.
  - **It issues no `subscribe_*` data command.** `test_capture_actor_issues_no_venue_subscription` asserts zero `SubscribeData`/`SubscribeOrderBook`/`SubscribeQuoteTicks` commands from this actor, which protects the shared 10-per-connection cap.
- `_on_order_event`, catch-all (L-16, publisher unwinding):
  - `OrderAccepted` → a second `OrderLink` with `venue_order_id_sha256 = sha256(venue_order_id)` (payload hygiene: never the raw id).
  - `OrderSubmitted`/`OrderAccepted`/`OrderFilled`/`OrderCanceled`/`OrderExpired`/`OrderRejected`/`OrderDenied` → `LifecycleEvent(event=…, client_order_id, trade_id, qty, px, fee)` with str-decimals.
  - `decision_id` is resolved from `self.cache.order(event.client_order_id).tags`. Orders without the tag (only exits, see the guard) record an empty `decision_id` plus a DetectorEvent.
- `_on_position_event`: `PositionOpened`/`Changed`/`Closed` → `PositionMark(instrument_id, leg, net_qty, mark_px, source="node")`.
  - `leg` = `leg_of(instrument_id)`, `net_qty` is signed **in venue convention**: a NO-leg holding is written as a negative quantity on the base slug (L-44; `parsing.py:277-279`; memory `venue-nets-no-holding-as-short-yes`).
  - `mark_px` = the last ask of that instrument's latest Depth10, else null with `source="node_no_mark"`.
- The 60 s timer evicts on-change keys, runs the positive control, evaluates the three NODE_LOCAL detectors (§3.5) and writes a DetectorEvent on any state **transition** only.
- **The node touches no exec-store key** (Z16: the HWM mirror ignores `autonomy/` keys and AUT-1 adds none). `test_capture_modules_never_import_exec_store` is an AST check for no import of `runtime.sqlite_store`, `trial_day_latch` or `exec.client` from `strategy/autonomy_capture/*` or `persistence/autonomy/capture_*`.

### 3.4 The join (C1 invariants (i)–(iii))

Join keys:

```
DecisionRecord(kind=Take) ──decision_id──► DecisionRecord(kind=TrySubmit, reason=submitted)
        └─decision_id──► OrderLink(pre-submit, client_order_id) ──client_order_id──►
           DurableFillRecord (exec store FILL_<venue_order_id>, .client_order_id)  ◄── authoritative fill
           LifecycleEvent(FILLED|EXPIRED|CANCELED|REJECTED|DENIED, client_order_id)
           PositionMark(instrument_id, ts ≥ fill.ts_event)
        └─(station, climate_day)──► SettlementRecord
        └─depth_ref──► blob depth/<sha>   └─forecast_input_sha256──► blob forecast_input/<sha>
        └─artefact_sha256──► deploy/families/<density_artefact_path> bytes or derived/artefacts/*/<sha>/artefact.json
```

- **The fill side is the exec store, not the node event.** A resolver fill recorded later, or by another process (AMBIGUOUS, L-36), still carries `client_order_id` (`exec/client.py:950`) and therefore still joins.
- `capture_reader.join_fills_to_decisions(capture_days, fills) -> tuple[JoinedFill | JoinGap, ...]` is pure. AUT-2 consumes it instead of the CRH latch walk that produces `no_taken_latch`.

### 3.5 Node-local observations (obligation 4)

All three are C6 `Detector(kind=NODE_LOCAL)` objects, action fixed in code as `ENTRY_VETO` (C6). AUT-5a's `entry_veto(instrument_id)` composes them. AUT-6 lists them in its catalogue. Every veto auto-clears, writes a C1 `EntryVeto` record when it refuses a take (CS-2) and a `DetectorEvent` on each transition, writes **no** registry row and spends no budget (ARCH Y1, `test_transient_capture_veto_writes_no_transition`).

**Z6 analogue for all three.** Each starts in the veto state at boot until its first good observation. It is also re-evaluated **at call time**: if its last evaluation is older than `CAPTURE_OBS_MAX_AGE_S = 180` (3× the 60 s tick), it vetoes.

#### 3.5.1 `feed_stale`, two sources

| Detector id | Source | Period | Trigger | Clear |
|---|---|---|---|---|
| `md_feed_freshness` | Passive `msgbus` subscriptions to `data.book.depth.*` and `data.quotes.*` (WP0 pins the 1.231.0 topic strings). The handler stores `last_frame_ns = clock.timestamp_ns()`: one int, O(1). | Evaluated on the 60 s tick and at call time | `now − last_frame_ns > MD_SILENCE_S`, where `MD_SILENCE_S = max(900, ws_idle_timeout_secs + 300)`, i.e. 900 s at the configured 600 s idle timeout (`config.py:293`). WP0 checks it against the measured p99.9 of all-instrument silence in 16:50Z–01:00Z on the last 14 tape days and raises the floor if that p99.9 × 1.5 is larger. | The next frame on any subscribed instrument |
| `nbp_feed_freshness` (in `FqCaptureAdapter`; FQ-specific because the kind declares `required_feeds = {MARKET_DATA, NBP}`) | `ForecastQuantileState.value_at(now)` per traded station (`forecast_state.py:306`) and the actor's `latest_available_cycle_ns(now)` (`nbm_quantile_actor.py:382-400`) | 60 s tick | `missed` = the number of configured cycles (13Z/19Z/01Z) after the newest **complete visible** cycle whose `cycle_ns + stale_deadline_seconds` has passed. `missed ≥ 1` → CRITICAL alert `NBP_CYCLE_MISSED` through `deliver_with_proof`, no veto. `missed ≥ 2`, or no complete vector for a station with subscribed instruments → veto `feed_stale`. A bulletin-drift latch (`:510-531`) counts as a missed cycle. | A newer cycle becomes complete (the `FQ_VECTOR_COMPLETE` path) |

#### 3.5.2 NBP self-heal (in node; the trade node is never restarted)

- In `NbmQuantileActor.on_cycle_timer`, if `_poll_in_flight` has been true for more than `NBP_POLL_HANG_S = 600`, the actor:
  - cancels the stored `concurrent.futures.Future` from `run_coroutine_threadsafe` (newly retained in `_submit`);
  - resets `_poll_in_flight`;
  - increments `counters["poll_hang_reset"]`;
  - logs `NBM_NBP_POLL_RESET cycle_ns=<n>`;
  - submits a fresh `poll_once()`.
- WP0 pins the `BulletinFetcher` HTTP timeout, and `NBP_POLL_HANG_S` must be at least twice that.
- A reset that is followed by `FQ_VECTOR_COMPLETE` for the missed cycle is a **self-healed feed stall**. It is journaled to `evidence/capture/self_heal_<date>.jsonl` with `{unit:"in-node:nbm_quantile_actor", detected_ns, action:"poll_reset", healed_ns}` and counts toward the live proof.

#### 3.5.3 `capture_gap`

| Source | Period | Trigger | Clear |
|---|---|---|---|
| `CaptureWriter.health` (`write_errors`, `capped_rows`, `last_fsync_ok_ns`) | Every write; 60 s tick; call time | Any failed durable write since the last positive control, or the byte cap hit | The next successful fsynced positive-control `DetectorEvent(capture_writer_health, AGREE)`. While capped, the cap holds until UTC midnight, when a new file starts and the day stays INCOMPLETE. |

#### 3.5.4 `recorder_stale`

| Source | Period | Trigger | Clear |
|---|---|---|---|
| The capture-watch state file `~/.local/share/breezy/health/capture_watch-polymarket_us.json` (`capture_watch/v1`), read on the 60 s tick under the single-read rule: `O_NOFOLLOW`, 4 KiB cap, strict exact-set schema. Added to the Z16 single-read list. | 60 s | `recorder.state ∈ {UNHEALED, INACTIVE}`; or `written_at_ns` older than 900 s (3 watch periods); or the file is missing, oversize or unparseable. Each case is fail-closed. | A verified read with `state ∈ {OK, HEALING}` and fresh `written_at_ns` |

**Why the recorder vetoes entries at all.** It vetoes only once self-heal has failed. Live depth capture does not depend on the recorder (§3.3.2). AUT-4's slippage and market-baseline evaluation, however, needs recorder tape around live fills (ARCH C4, Y12), so a day traded without tape is a day the live evidence cannot be evaluated. Transient stalls that heal within ~15 min never veto (state `HEALING`).

`permit_lapsed` is **not** AUT-1's. AUT-6 owns liveness.

### 3.6 Recorder and feed self-heal (obligation 5)

#### 3.6.1 Recorder heartbeat (in the recorder process, opt-in)

- `PolymarketUSDataClientConfig.heartbeat_path: str | None = None`. Only `build_quote_tape_node_config` sets it, to `~/.local/share/breezy/health/recorder-polymarket_us.json`. `test_trade_node_config_has_no_heartbeat_path` keeps the node byte-for-byte on the old behaviour.
- `_write_heartbeat(phase)` writes atomically (`mkstemp` plus `os.replace`, 0600) the `recorder_heartbeat/v1` record:
  - `{schema, instance_id (the native recorder instance_id, data.py's _recorder_instance_id), pid, phase ∈ {DISCOVERING, STREAMING, SAFE_MODE}, written_at_ns, discovered_slugs, subscribed, quotes_published, depths_published, trades_published, tape_gaps, is_tape_gap_open, safe_mode}`.
  - It is rate-limited to once per 30 s, O(1).
- Call sites:
  - every empty-discovery retry iteration (`data.py:1090-1099`, phase `DISCOVERING`);
  - every `sample_feed_health` (`:1960-2003`, phase `STREAMING`, or `SAFE_MODE` when `_safe_mode`).
- `depths_published` is added as a counter beside `quotes_published` if WP5's read finds none.
- A heartbeat write failure is counted and logged once, never raised.

#### 3.6.2 `breezy-capture-watch` (oneshot, every 5 min, own lock)

`capture_watch.classify_recorder(hb, unit_active, now, prev) -> RecorderState`. Every threshold is a literal in `capture_watch.py`.

| State | Rule |
|---|---|
| `INACTIVE` | The unit is not active (`systemctl --user is-active` via an argv list, read-only). **Never started by the watch.** `try-restart` semantics respect a deliberate operator stop, as `breezy-quote-tape-rotate.service` documents. CRITICAL. |
| `HUNG` | The unit is active and the heartbeat is missing or older than `HB_STALE_S = 180`. This is the zombie and wedged-loop signature (memory `recorder-hangs-disconnected`). Also: phase `DISCOVERING` for longer than `empty_discovery_retry_secs + 300`, or phase `SAFE_MODE` for more than 300 s. |
| `STALLED` | Phase `STREAMING`, `discovered_slugs > 0`, and `quotes_published + depths_published + trades_published` unchanged across probes spanning at least `STREAM_SILENCE_S = max(900, ws_idle_timeout_secs + 300)`, **and** the byte total of non-empty files under `live/<hb.instance_id>/` unchanged over the same span. Epoch mtimes and sizes are used, never `find -newermt` (memory `measure-catalog-freshness-with-epoch`). Zero-byte stubs count as no data. |
| `OK` | Otherwise. A legitimately empty listing (phase `DISCOVERING` within budget, or `discovered_slugs == 0`) is `OK`, which avoids restart loops in the 09:00–09:45Z listing hole. |
| `HEALING` / `UNHEALED` | Self-heal states (below). |

- **Rotation grace.** If `hb.instance_id` changed and the new instance is younger than 600 s, which covers the rotate timer's 09:00Z `try-restart` and systemd restarts, the watch never heals.
- **Self-heal.** For `HUNG` or `STALLED` on two consecutive probes (≥ 5 min apart):
  1. Call AUT-6 `restart_unit("breezy-quote-tape.service", cause=<state>)`, which issues `systemctl --user try-restart` (argv list, never `shell=True`), enforces `SELF_HEAL_MAX_RESTARTS_PER_UNIT_PER_DAY` (Z15), and journals the attempt.
  2. Set the state to `HEALING`, then confirm across at most 2 probes: a new `instance_id`, phase `STREAMING` or legitimately `DISCOVERING`, and counters rising.
  3. On success, append `HEALED` to `evidence/capture/self_heal_<date>.jsonl` (`{unit, cause, detected_ns, restarted_ns, healed_ns, injected:bool}`), write a C4 `HEALTH` verdict `recorder_self_heal` PASS, and send an INFO alert through `deliver_with_proof`.
  4. On failure, a second restart is allowed if the cap remains. At the cap: state `UNHEALED`, CRITICAL, `HEALTH` FAIL, and the node-local `recorder_stale` veto applies.
- **SIGSTOP and clean stop.** WP0 pins that systemd 259 sends `SIGCONT` right after `KillSignal=SIGTERM`, so that a stopped (SIGSTOP) recorder handles SIGTERM cleanly and closes its feather file with the end-of-stream marker. Never SIGKILL: a SIGKILL truncates the file and the day reads as zero rows (`quote_tape_cli` and the unit comments).
  - **Fallback if WP0 refutes it:** a reviewed unit-file commit adds `ExecStop=/bin/kill -CONT $MAINPID` to `breezy-quote-tape.service` (ExecStop runs before KillSignal). The bot never edits unit files (ARCH §4.1 item 8).
- **NWS ingest (the settlement-truth source of the join).**
  - Read `~/.local/share/breezy/health/health-polymarket_us.<CITY>.json`. These are existing files with `snapshot_at_ns` and `last_successful_poll_ns`, schema_version 2.
  - `HUNG` if `breezy-nws-ingest.service` is active and the newest `snapshot_at_ns` across cities is older than 900 s → restart via AUT-6, with the same confirm and journal steps.
  - `gate_state != OPEN` for more than 2 h → CRITICAL alert only, because an upstream NWS outage is not fixed by a restart.
- **State file.** After every probe, `capture_watch-polymarket_us.json` is written atomically (0600) as `capture_watch/v1`: `{schema, written_at_ns, recorder:{state, since_ns, instance_id, restarts_today}, nws_ingest:{state, since_ns, restarts_today}}`.
- **Units added to `SELF_HEAL_RESTARTABLE_UNITS`** (a literal tuple in `pins.py`, reviewed commit): `breezy-quote-tape.service` and `breezy-nws-ingest.service`.
  - Neither is the supervisor, the trade node or the engine, so ARCH §4.5 and `test_self_heal_unit_allowlist_is_literal_and_excludes_trade` hold.
  - AUT-1 proposes `SELF_HEAL_MAX_RESTARTS_PER_UNIT_PER_DAY = 4`. AUT-6 and the pins review own the value.

### 3.7 Daily completeness audit (obligation 6)

- `breezy-capture-audit.service` (oneshot) runs `python3 -m breezy.analysis.capture_audit_cli --venue polymarket_us` at **13:50Z** daily, `Persistent=true`.
  - That is after the 12:15Z tape ingest and the overnight CLI publication, before `score-live-trials` at 14:15Z, and it ends before 16:30Z (§3.8).
- **Families are enumerated by construction, not by registry lookup.** The audit takes the union of `capture_*_<date>.jsonl[.gz]` family ids and the **attribution of every durable fill** in the window. An orphan fill with no OrderLink is a FAIL that no family can escape, which covers any future family (README 3(b)).
- **Inputs, all read-only:**
  - capture files for the last 8 UTC days (an order created on day X may fill on day X+k through the resolver);
  - durable fills via `fill_by_day/<D>` for the audited days, then `FILL_<venue_order_id>`, read through the `mode=ro` URI with `SELECT key, value FROM state` (the `prereg_admission.py:326` pattern);
  - resolver contexts (`RESOLVER_CONTEXT_KEY_PREFIX`, `exec/client.py:454`) for AMBIGUOUS orders;
  - `read_climate_day_including_corrections` for settlement;
  - the blob store and manifest artefacts.
- **`SettlementRecord` writer.** For each `(station, climate_day)` referenced by a fill, the audit appends `SettlementRecord(station, climate_day, settlement_tmax_f, basis="NWS_CLI", raw_sha256)` to `decisions/capture_<family_id>_<UTC-date>.offline.jsonl`. This is a separate file from the node's (L-50: one writer per file, §11 item 6). Polymarket.us settles on NWS; Kalshi on The Weather Company (memory `both-venues-settle-on-nws`, corrected). A Kalshi family's adapter would declare its basis.
- **Per fill, legs** (`analysis/capture_audit.py::audit_fill`):

| Leg | Pass condition |
|---|---|
| L | Exactly one `decision_id` across OrderLinks for `client_order_id`. Conflicting ids → `link_conflict`. |
| D | A `Take` and a `TrySubmit(submitted)` with that id exist, and the recomputed id from the Take's stored fields equals it. |
| B | The depth and forecast blobs exist and re-hash to their names, and `artefact_sha256` resolves to bytes hashing to it. |
| E | A node `LifecycleEvent(FILLED)` with the same `trade_id`, **or** a resolver context exists for the `client_order_id` (`fill_via_resolver`). |
| P | A `PositionMark` for the instrument with `ts_ns ≥ fill.ts_event`, or `fill_via_resolver`. |
| S | A `SettlementRecord` exists. If the climate day ended less than 36 h ago with no CLI, the leg is `PENDING`. Past 36 h it is a FAIL, `settlement_missing`. |

- **Order-level legs:**
  - every `TrySubmit(submitted)` has an OrderLink;
  - every linked order reaches a terminal LifecycleEvent (FILLED, EXPIRED, CANCELED, REJECTED or DENIED) or has a resolver context, which captures the cancels; otherwise `order_unterminated`;
  - an `.INCOMPLETE` marker on any audited day → FAIL;
  - after registry cutover, `registry_seq == 0` → FAIL.
- **Day status:**
  - `FINAL` when no leg is `PENDING`;
  - `PASS` iff FINAL and every leg passes;
  - `INCONCLUSIVE` while any leg is pending, never `ERROR`;
  - a day with no fills: `NO_INPUT`, exit 0 (C2 rule: no expected non-zero exit).
- Canary fills (from the `canary/` store) are audited in a separate `canary` section and never count. Drill fills are audited like live fills, marked `drill=true`, and never qualify a day toward the ≥ 5 real fills.
- **Outputs:**
  1. `~/.local/share/breezy/evidence/capture/audit_<family_id>_<YYYY-MM-DD>.json` (0444, `capture_audit/v1`): per-fill legs, with venue order ids only as sha256.
  2. A C4 verdict through the ARCH-0 writer at `derived/verdicts/<family_id>/<date>/<verdict_id>.json`:
     - `kind=HEALTH`, `detector=capture_join_completeness`, `outcome`, `metrics={fills_total, fills_joined, legs_failed_by_name}`, `n=fills_total`;
     - `n_min` with the literal reason `"census: every fill is checked; no sampling"`;
     - `subject_artefact_sha256` = the family's **bound** artefact sha (Z1: from its BOOTSTRAP or MINT row via the AUT-5 read-only resolver; before the registry exists, the manifest's `density_artefact_sha256`);
     - `valid_until_ns = produced_at_ns + 26 h`, which is at most `MAX_VERDICT_VALIDITY_H` (Z4);
     - `producer_code_sha` pinned in `PRODUCER_SOURCE_SHA256["aut1_capture_audit"]`.
  3. On FAIL, a CRITICAL `CAPTURE_JOIN_GAP` through `deliver_with_proof`. On success the unit triggers `breezy-capture-live-proof.service` (`OnSuccess=`).

### 3.8 Units, timers, memory and locks

| Unit | Schedule | Lock | Memory | Runtime | Failure |
|---|---|---|---|---|---|
| `breezy-capture-watch.service` | `OnCalendar=*:0/5`, `AccuracySec=10s`, `Persistent=false` | own: `flock -w 30 ~/.local/share/breezy/health/capture-watch.lock`; **never** the studies flock, so a study can never delay a heal (§5.2) | `MemoryHigh=192M`, `MemoryMax=256M` (in the ≤ 4G own-lock budget) | `RuntimeMaxSec=120` | `OnFailure=breezy-study-failed@%n.service`; `EnvironmentFile=-%h/.config/breezy/alerts.env` |
| `breezy-capture-audit.service` | 13:50Z daily, `Persistent=true` | `breezy-studies.lock`, `flock -w 600`, `Slice=breezy-studies.slice` | `MemoryHigh=768M`, `MemoryMax=1G` | `RuntimeMaxSec=1200`: 13:50 + 10 min wait + 20 min ends by 14:20Z, well before 16:30Z | `OnFailure=` the same; alerts.env |
| `breezy-capture-live-proof.service` | `OnSuccess=` of the audit | the studies lock, `-w 600` | `MemoryMax=256M` | `RuntimeMaxSec=300` | `OnFailure=` the same |
| `breezy-capture-stall-drill.service` and `.timer` | `OnCalendar=Sun *-*-* 09:15:00 UTC` | own lock (the capture-watch lock) | `MemoryMax=64M` | 60 s | `OnFailure=` the same |
| `breezy-capture-stall-drill-guard.service` and `.timer` | `OnCalendar=Sun *-*-* 09:40:00 UTC` | none | `MemoryMax=64M` | 30 s | `OnFailure=` the same |

All units use `WorkingDirectory=/home/jon/breezy`, `UMask=0077`, the explicit interpreter `/home/jon/breezy/.venv/bin/python3 -m ...`, no venue credential (no `polymarket.env`) and no network beyond the existing alert webhook. Peak added load on the 30 GiB host is under 1.4G, none of it inside the trade node.

---

## 4. Work packages

**Gate for every WP:**

```
scripts/ci/run_tests_no_egress.sh                         # full gate, exact interpreter; read the EXIT code (L-43; memory pytest-q-doubles-into-qq)
cd <tree root> && lint-imports                            # must print "N kept, 0 broken" (memory python-m-importlinter-is-a-noop)
scripts/ci/run_tests_no_egress.sh tests/unit/test_mypy_ratchet.py
```

- In a worktree, `PYTHONPATH=<worktree>/src` (memory `worktree-needs-pythonpath`).
- Never `uv`, `pip` or `uv run`. Never `git stash`.
- Unit-launched gates use `-p LimitNOFILE=524288` (memory `systemd-run-soft-nofile-1024`).
- Unchanged safety tests that **must stay green unedited**: `test_exec_client_is_byte_identical_to_its_pre_sl13_sha256`, `test_execution_egress_firewall_guard`, `test_operator_control_assignment_scan`, `test_shadow_only_false_is_only_the_gate_output`, `test_live_orders_ruling_deploy_copy_matches_evidence`, `test_native_order_cap_wiring`, `test_risk_engine_ordering_enforcement`, `test_probe_containment.py::test_pyproject_addopts_deselect_the_probe_markers` (L-54).
- Before placing any module, grep the contract tests for its package and path (L-46).

### AUT-1.WP0: L-1 premises and measurements (characterisation; mutation evidence per L-33)

- **Scope.** Pin every WP0-marked premise in §2. Measure the full-day C1 volume, the live-window all-instrument silence p99.9 (14 tape days, `MemoryMax=4G`, run as one studies-flock job outside 01:00–04:30Z), the `BulletinFetcher` HTTP timeout, and the systemd 259 SIGCONT-after-KillSignal behaviour (`man systemd.kill` on the host plus a throwaway `systemd-run --user` sleep unit).
- **Files.** `tests/unit/test_aut1_l1_nautilus_premises.py` (new); `docs/evidence/AUT1_WP0_premises_<date>.md` (new).
- **Tests.** These are characterisation tests: each must **fail against a mutated premise**, and the mutation is recorded in the evidence file.
  - `test_order_events_publish_on_events_order_strategy_topic`
  - `test_actor_wildcard_msgbus_subscription_receives_order_and_position_events`
  - `test_msgbus_handler_exception_unwinds_into_publisher`
  - `test_python_submit_order_override_is_dispatched_from_python_caller`
  - `test_order_tags_absent_from_wire_body`
  - `test_depth10_ts_event_is_venue_transact_time`
  - `test_passive_data_topic_subscription_issues_no_subscribe_command`
- **GREEN.** All pass on 1.231.0. The evidence file states the measured `MD_SILENCE_S`, `NBP_POLL_HANG_S` and the full-day volume, plus the SIGCONT verdict.
- **Activation.** None (tests only).

### AUT-1.WP1: capture core in `persistence/autonomy/`

- **Scope.** §3.3.1–3.3.3, `capture_reader`, `capture_watch_state` schemas, and the `DECISION_ID_TAG_PREFIX` constant.
- **Files.** `capture_ids.py`, `capture_writer.py`, `capture_blobs.py`, `capture_reader.py`, `capture_watch_state.py` (new); `persistence/exit_tags.py` (edit).
- **RED tests first** (`tests/unit/autonomy/`):
  - `test_capture_ids.py::test_decision_id_recomputes_from_stored_record`
  - `::test_decision_id_field_order_is_pinned`
  - `::test_depth_ref_excludes_ts_init_and_size_zero_pads`
  - `::test_forecast_input_sha_is_canonical`
  - `test_capture_writer.py::test_lines_are_schema_versioned_exact_set`
  - `::test_refusal_written_only_on_key_kind_reason_change`
  - `::test_take_trysubmit_link_lifecycle_are_fsynced`
  - `::test_write_failure_is_critical_and_marks_incomplete`
  - `::test_byte_cap_is_loud_not_silent`
  - `::test_on_change_map_is_bounded`
  - `::test_canary_records_land_only_in_canary_store` (Z14)
  - `::test_writer_never_raises`
  - `::test_drill_flag_read_per_record_not_frozen` (Z2)
  - `test_capture_blobs.py::test_blob_store_is_content_addressed_and_idempotent`
  - `::test_blob_store_refuses_symlinks`
  - `test_capture_reader.py::test_join_fills_to_decisions_by_client_order_id`
  - `::test_join_reports_orphan_fill_as_gap`
  - `test_capture_watch_state.py::test_watch_state_single_read_refuses_symlink_oversize_unknown_keys` (Z11, Z16)
  - `test_autonomy_payload_hygiene_scan` (ARCH-0) is **widened** to the new writers.
- **GREEN.** All pass; `lint-imports` clean; no Nautilus import in `capture_ids` or `capture_writer`.
- **Activation.** Library only; it goes live with WP2 and WP3.

### AUT-1.WP2: FQ `CaptureAdapter`, the guard, the tag, the `EntryVeto` writer

- **Scope.** §3.3.4 CS-1 to CS-5 and §3.3.5; registration of `FqCaptureAdapter` in `NODE_PLUGINS` (ARCH-0 registry).
- **Files.** `strategy/autonomy_capture/guarded_strategy.py` and `strategy/forecast_quantile_ladder/capture_adapter.py` (new); `strategy/forecast_quantile_ladder/strategy.py` (edit: base class, CS-1 to CS-4; **`try_submit` untouched**, it belongs to AUT-5a).
- **RED tests first:**
  - `tests/strategy/forecast_quantile_ladder/test_aut1_capture_adapter.py`:
    - `::test_every_fq_order_carries_exactly_one_decision_id_tag`
    - `::test_untagged_entry_is_refused_capture_untagged`
    - `::test_order_link_is_fsynced_before_submit_order`
    - `::test_link_write_failure_refuses_entry_capture_gap`
    - `::test_exit_tagged_order_is_never_refused_by_capture`
    - `::test_entry_veto_reason_is_written_as_entryveto_record`
    - `::test_take_record_carries_depth_ref_forecast_sha_and_artefact_sha`
    - `::test_take_without_depth_is_refused_capture_gap`
    - `::test_no_leg_take_records_side_no` (L-44)
    - `::test_shadow_only_take_is_captured_without_order`
    - `::test_capture_drill_flag_persists_after_drill_resume` (Z2)
  - `tests/unit/autonomy/test_capture_guard_family_agnostic.py`:
    - `::test_every_full_plugin_kind_strategy_subclasses_capture_guard`
    - `::test_decision_id_tag_prefix_never_collides_with_exit_prefixes`
  - The fixtures write through the real `CaptureWriter` (L-42), and one test runs the production-default writer factory (L-55).
- **GREEN.** All pass, plus the existing `tests/strategy/forecast_quantile_ladder/*` and `test_forecast_quantile_ladder_boot.py` unedited.
- **Activation.** Through WP3's composition hunk.

### AUT-1.WP3: lifecycle actor, node observations, composition hunk (Wave 1b)

- **Scope.** §3.3.6, §3.5.1 `md_feed_freshness`, §3.5.3, §3.5.4. The single `app/trade.py` hunk in `_compose_forecast_quantile_ladder` constructs `CaptureIdentity(family_id=manifest.family_id, manifest_sha256=<AUT-5a ResolvedFamily or load_family_manifest sha>, artefact_sha256=manifest.density_artefact_sha256, ...)`, the writer (`decisions_dir = catalog_root.parent / "decisions"`), the adapter (passed to `build_forecast_quantile_ladder_strategies`) and the actor (appended at `:823`). It registers the NODE_LOCAL detectors with AUT-5a's `entry_veto` composer.
- **Files.** `strategy/autonomy_capture/lifecycle_actor.py` and `node_observations.py` (new); `strategy/forecast_quantile_ladder/composition.py` (edit: thread `capture_adapter`); `app/trade.py` (one hunk, **rebased after AUT-5a merges**).
- **RED tests first** (`tests/unit/autonomy/test_capture_lifecycle_actor.py`):
  - `::test_actor_writes_order_link_with_venue_sha_on_accept`
  - `::test_actor_writes_lifecycle_for_each_terminal_event`
  - `::test_position_mark_signs_no_leg_as_short_yes` (L-44)
  - `::test_handler_never_raises_into_publisher` (L-16)
  - `::test_capture_actor_issues_no_venue_subscription` (L-45)
  - `::test_capture_gap_vetoes_at_boot_until_positive_control` (Z6 analogue)
  - `::test_observation_older_than_3_ticks_vetoes_at_call_time` (Z6 analogue)
  - `::test_md_feed_stale_after_silence_and_clears_on_next_frame`
  - `::test_md_silence_horizon_tracks_configured_idle_timeout`
  - `::test_recorder_stale_vetoes_only_on_unhealed_inactive_or_stale_file`
  - `::test_unparseable_watch_file_vetoes`
  - `::test_transient_capture_veto_writes_no_transition`
  - `::test_capture_modules_never_import_exec_store` (Z16)
  - `tests/unit/test_forecast_quantile_ladder_boot.py::test_fq_composition_registers_capture_actor_and_detectors`, run with the production default factory (L-55)
- **GREEN.** All pass, plus the full gate and `test_shadow_only_false_is_only_the_gate_output` unedited (the hunk adds no `shadow_only` expression).
- **Activation.** The **next supervisor STOP/LAUNCH** (16:40/16:50Z). Technical reason: the hunk changes the order path, and LAUNCH is the only path that re-runs every boot gate (permit, intent probe, live-orders gate) without a hand relaunch. After AUT-5a, a hand relaunch is refused (ARCH Y7, Z7). **Precondition:** WP5's watch unit is active at least 10 min before that LAUNCH, otherwise `recorder_stale` would veto from boot.

### AUT-1.WP4: NBP freshness detector and in-node poll-hang self-heal

- **Scope.** §3.5.1 `nbp_feed_freshness` and §3.5.2.
- **Files.** `strategy/forecast_quantile_ladder/capture_adapter.py` (detector); `ingest/nbm_quantile_actor.py` (retain the future in `_submit`, add the hang reset in `on_cycle_timer`).
- **RED tests first:**
  - `tests/unit/test_nbm_quantile_actor.py::test_poll_hang_is_reset_after_threshold`
  - `::test_poll_reset_followed_by_vector_complete_journals_self_heal`
  - `tests/strategy/forecast_quantile_ladder/test_aut1_nbp_freshness.py`:
    - `::test_one_missed_cycle_alerts_with_delivery_proof_no_veto`
    - `::test_two_missed_cycles_veto_feed_stale`
    - `::test_no_complete_vector_for_subscribed_station_vetoes`
    - `::test_bulletin_drift_counts_as_missed_cycle`
    - `::test_veto_clears_on_newer_complete_vector`
- **GREEN.** All pass; the existing `test_nbm_quantile_actor.py` is unedited except for the added tests.
- **Activation.** Next supervisor LAUNCH (same reason as WP3).

### AUT-1.WP5: recorder heartbeat, `breezy-capture-watch`, unit self-heal

- **Scope.** §3.6 in full. Add the two units to `SELF_HEAL_RESTARTABLE_UNITS` and add `PRODUCER_SOURCE_SHA256["aut1_capture_watch"]` in `pins.py` (one reviewed commit; closure pin per §4.3).
- **Files.** `adapters/polymarket_us/config.py`, `adapters/polymarket_us/data.py` and `runtime/node_config.py` (edit); `runtime/capture_watch.py` and `runtime/capture_watch_cli.py` (new); `deploy/systemd/breezy-capture-watch.{service,timer}` (new); `persistence/autonomy/pins.py` (edit).
- **Depends on** AUT-6's `restart_unit` and `deliver_with_proof`. WP5 does not merge before they exist (no stub that restarts).
- **RED tests first:**
  - `tests/unit/test_recorder_heartbeat.py`:
    - `::test_heartbeat_is_atomic_rate_limited_and_o1`
    - `::test_heartbeat_written_during_empty_discovery_retry`
    - `::test_trade_node_config_has_no_heartbeat_path`
    - `::test_heartbeat_failure_never_raises`
  - `tests/unit/test_capture_watch.py`:
    - `::test_stale_heartbeat_with_active_unit_is_hung`
    - `::test_streaming_with_frozen_counters_and_bytes_is_stalled`
    - `::test_zero_byte_stubs_count_as_no_data`
    - `::test_empty_listing_within_budget_is_ok`
    - `::test_rotation_grace_suppresses_heal`
    - `::test_inactive_unit_is_never_started`
    - `::test_two_consecutive_bad_probes_trigger_restart_via_aut6_api`
    - `::test_restart_cap_exhausted_sets_unhealed_critical_and_health_fail` (Z15)
    - `::test_heal_confirmed_journals_and_writes_health_pass`
    - `::test_nws_ingest_snapshot_stale_restarts_gate_closed_alerts_only`
    - `::test_watch_state_file_is_atomic_and_schema_exact`
  - `tests/unit/test_capture_watch_unit.py::test_unit_has_own_lock_memory_cap_runtime_cap_onfailure_and_no_studies_flock`
  - The `test_self_heal_unit_allowlist_is_literal_and_excludes_trade` (ARCH) extension passes with the two units.
- **GREEN.** All pass; full gate.
- **Activation.** Immediately on merge:
  - `systemctl --user link` the two unit files;
  - `systemctl --user enable --now breezy-capture-watch.timer`;
  - restart the recorder once, 09:00–09:45Z only (the listing hole), via the existing rotate path (`systemctl --user start breezy-quote-tape-rotate.service`), so the recorder loads the heartbeat code;
  - confirm a fresh `recorder-polymarket_us.json` and `capture_watch-polymarket_us.json` with `recorder.state=OK`.

### AUT-1.WP6: daily completeness audit, `SettlementRecord`, retention

- **Scope.** §3.7; the retention regex widening; `PRODUCER_SOURCE_SHA256["aut1_capture_audit"]`.
- **Files.** `analysis/capture_audit.py` and `analysis/capture_audit_cli.py` (new); `deploy/systemd/breezy-capture-audit.{service,timer}` (new); `scripts/ops/decisions_retention.py` (edit); `persistence/autonomy/pins.py` (edit).
- **RED tests first:**
  - `tests/unit/test_capture_audit.py`:
    - `::test_complete_day_passes_final`
    - `::test_orphan_fill_without_link_fails`
    - `::test_link_conflict_fails`
    - `::test_trysubmit_without_terminal_lifecycle_fails_order_unterminated`
    - `::test_settlement_pending_is_inconclusive_overdue_fails`
    - `::test_blob_rehash_mismatch_fails`
    - `::test_incomplete_marker_fails_day`
    - `::test_registry_seq_zero_after_cutover_fails`
    - `::test_no_fills_exits_zero_no_input`
    - `::test_resolver_fill_without_node_filled_event_passes_e_and_p`
    - `::test_canary_fills_reported_separately_never_counted`
    - `::test_drill_fills_joined_but_not_qualifying`
    - `::test_unknown_family_fill_is_enumerated_by_construction`
    - `::test_reads_gzipped_capture_files`
    - `::test_exec_store_fixture_written_through_real_record_fill` (L-42)
    - `::test_settlement_record_basis_is_nws_cli_for_polymarket_us`
    - `::test_verdict_schema_valid_bound_artefact_sha_and_pinned_producer` (Z1, Z4)
    - `::test_fail_sends_critical_through_deliver_with_proof` (Z13)
    - `::test_offline_writer_never_appends_node_file` (L-50)
  - `tests/unit/test_decisions_retention.py::test_capture_files_are_gzip_candidates`
- **GREEN.** All pass; full gate.
- **Activation.** Immediately on merge: link and `enable --now breezy-capture-audit.timer`. Then run one `systemctl --user start breezy-capture-audit.service` and check for `audit_*.json` and the verdict file.

### AUT-1.WP7: weekly injected stall drill and live-proof roll-up

- **Scope.**
  - `capture_stall_drill_cli`:
    - refuse unless `capture_watch` state is `OK`, the recorder phase is `STREAMING`, the instance is older than 1 h and the time is 09:10–09:20Z Sunday;
    - write `evidence/capture/drill_<date>.json` (`injected=true`);
    - run the literal argv `["systemctl","--user","kill","--signal=SIGSTOP","breezy-quote-tape.service"]`.
  - Guard unit at 09:40Z: the literal argv `["systemctl","--user","kill","--signal=SIGCONT","breezy-quote-tape.service"]`, unconditional (a no-op on a running process). If the drill did not reach `HEALED` by then, it sends a CRITICAL `CAPTURE_DRILL_NOT_HEALED`.
  - `capture_live_proof`:
    - reads `audit_*.json` and `self_heal_*.jsonl`;
    - computes the current run of consecutive qualifying UTC days (zero-fill days skip, a FAIL or INCONCLUSIVE-past-36 h day breaks the run);
    - real-fill count (excluding canary and drill);
    - healed stalls (natural or injected) with a matching `delivered=true` row in `evidence/alerts/delivery_<date>.jsonl`;
    - writes `evidence/capture/live_proof_<family_id>_<asof>.json` (`capture_live_proof/v1`, `status ∈ {ACCRUING, PROVEN}`).
- **Files.** `runtime/capture_stall_drill_cli.py` and `analysis/capture_live_proof.py` + `_cli.py` (new); the drill, guard and live-proof units (new).
- **RED tests first:**
  - `tests/unit/test_capture_stall_drill.py`:
    - `::test_drill_refuses_when_recorder_not_ok_or_outside_window`
    - `::test_drill_argv_is_literal_sigstop_on_recorder_only`
    - `::test_guard_argv_is_literal_sigcont_on_recorder_only`
    - `::test_drill_marks_self_heal_entry_injected`
  - `tests/unit/test_capture_live_proof.py`:
    - `::test_zero_fill_days_extend_not_break`
    - `::test_fail_day_breaks_window`
    - `::test_requires_five_real_fills_excluding_canary_and_drill`
    - `::test_requires_one_healed_stall_with_delivery_proof`
    - `::test_proven_only_with_seven_final_pass_days`
  - An AST test confirms that no module under `runtime/capture_*` calls `subprocess` except via the AUT-6 API or the two literal drill argvs.
- **GREEN.** All pass; full gate.
- **Activation.** Immediately on merge: link and enable both drill timers. The first drill is the next Sunday 09:15Z.

---

## 5. Association

### 5.1 Consumed (by contract)

| From | Contract | Exact interface |
|---|---|---|
| ARCH-0 | C1 | `persistence/autonomy` record dataclasses (`DecisionRecord`, `OrderLink`, `LifecycleEvent`, `PositionMark`, `DetectorEvent`, `SettlementRecord`), their `to_dict`/`from_dict`, the schema-version allowlist (AUT-1 assumes `"capture/v1"`; ARCH-0's literal wins) |
| ARCH-0 | C4 | the verdict dataclass and append-only writer under `derived/verdicts/` |
| ARCH-0 | C6 | the `CaptureAdapter` and `Detector` Protocols, `NODE_PLUGINS`, `RefusingPlugin`, the `VetoReason` closed enum (`capture_gap`, `feed_stale`, `recorder_stale`) |
| ARCH-0 | §4.3, §4.5 | `pins.py`: `SELF_HEAL_RESTARTABLE_UNITS`, `PRODUCER_SOURCE_SHA256`, `SELF_HEAL_MAX_RESTARTS_PER_UNIT_PER_DAY` (Z15), `MAX_VERDICT_VALIDITY_H` (Z4) |
| AUT-5a | C5 | `ResolvedFamily` (`family_id`, `registry_seq`, `manifest_sha256`, `artefact_sha256`); `RegistryWatchActor.drill_active(now_ns)` (Z2 fold); the `entry_veto(instrument_id)` composer that calls AUT-1's NODE_LOCAL detectors; the bound artefact sha (Z1) for verdict subjects; ownership of `try_submit` and of `app/trade.py` in Wave 1 |
| AUT-6 | §4.6, C6 | `deliver_with_proof(sink, payload) -> DeliveryProof` and its journal `evidence/alerts/delivery_<date>.jsonl`; `restart_unit(unit, *, cause) -> RestartOutcome` (literal-tuple check, Z15 cap, argv list); catalogue registration of AUT-1's detectors; the intraday producer turning `DetectorEvent`s into C4 |

### 5.2 Provided

| To | Contract | Interface |
|---|---|---|
| AUT-2 | C1 | the live and canary capture files; `.offline.jsonl` `SettlementRecord`s; `capture_reader.join_fills_to_decisions` (replaces the CRH-latch attribution behind `no_taken_latch`); the blob store (`p_at_decision` = the Take's `p_hat`) |
| AUT-4 | C1 | depth and forecast preimages per decision (slippage against the same Depth10 rows, Y12); `.INCOMPLETE` markers for admissibility |
| AUT-6 | C1, C6 | `DetectorEvent` records; the NODE_LOCAL detectors `capture_writer_health`, `md_feed_freshness`, `nbp_feed_freshness`, `recorder_liveness`; HEALTH verdicts `recorder_self_heal`; the `capture_watch/v1` state file |
| AUT-5 | C4 | HEALTH verdicts `capture_join_completeness` and `recorder_self_heal`. Proposed policy-map rows for the policy ruling: `capture_join_completeness FAIL → DEMOTE` (RECOVERABLE, infrastructure class per Z10, so it never escalates to TERMINAL); `recorder_self_heal FAIL → ALERT` (the node-local veto already acts). The policy ruling's peer review decides. |

### 5.3 Execution order

```
ARCH-0 ─► WP0 ─┬─► WP1 ─► WP2 ─────────────┐
               │                           ├─► WP3 (after AUT-5a merges; needs WP5 active) ─► LAUNCH
               └─► WP4 (needs WP1, WP2) ───┘
AUT-6 (deliver_with_proof, restart_unit) ─► WP5 ─► WP6 ─► WP7
```

- **Parallel:** WP0 with AUT-5a and AUT-6 Wave-1 work. WP1, WP5's heartbeat half, and WP6's pure audit core can proceed in parallel after WP0.
- **Serial:** WP2 → WP3; WP3 after AUT-5a merges (app/trade.py and the `try_submit` slot); WP5's self-heal half after AUT-6's API merges.
- **File ownership** for concurrent agents:
  - AUT-1 owns `_emit_shadow_decision`, `_emit_decision_outcome`, `_maybe_submit` and `on_order_book_depth` in `fq/strategy.py`; AUT-5a owns `try_submit`.
  - AUT-1's `app/trade.py` hunk lands only after AUT-5a's merge, and the full gate is re-run after each merge (L-43).
  - Each implementer gets its own scratchpad (memory `give-each-agent-its-own-scratchpad`).

---

## 6. Live-proof protocol

- **Artefacts.**
  1. Daily `evidence/capture/audit_<family_id>_<date>.json` and the matching C4 HEALTH verdict.
  2. `evidence/capture/self_heal_<date>.jsonl` with at least one `HEALED` row: natural, from the watch or the NBP reset, or injected from the WP7 drill (`injected=true`, allowed by the README).
  3. The matching `delivered=true` alert rows in `evidence/alerts/delivery_<date>.jsonl`.
  4. The roll-up `evidence/capture/live_proof_pm_us_crh_fq_v1_<asof>.json` with `status=PROVEN`.
- **Window.** 7 qualifying UTC days. Each day is `FINAL` and `PASS` with at least 1 real (non-canary, non-drill) fill. Zero-fill days extend the window. At least 5 real fills in total.
- **Accrual ETA.**
  - Measured FQ cadence: 2 takes on 10-01, 3 on 10-02. The README planning figure is about 5 fills a day, so most days qualify.
  - Settlement lag: a fill on UTC day X trades a D+1 market and is FINAL by about X+2, 13:50Z.
  - Build: WP0–WP6 is about 6–8 working days after ARCH-0 and AUT-6's delivery API merge. Assuming that by 2026-10-07, activation at the 2026-10-14 LAUNCH.
  - Earliest PROVEN: **2026-10-22**, from 7 fill days 10-14 to 10-20 plus 2 days of settlement lag. The stall requirement is met by the first Sunday drill, 2026-10-18, if no natural stall occurs first.
  - **Planning ETA: 2026-10-29**, allowing up to 7 zero-fill or halted days.
  - Margin against the 2027-01-25 KILL is about 13 weeks.
- **Evidence class.** "Machinery proven, edge unproven." AUT-1 makes no edge claim, and its proof is a census, not a statistical test.
- **Canary use.** Canary fills (Z14) can qualify a **day** only per ARCH §5.3, never the ≥ 5. If FQ is halted (A1, AUT-5 DEMOTE or KILL), real fills stop and the window pauses. Canary days alone can never produce PROVEN.

---

## 7. Score-3 verification checklist (for an independent scorer)

| Criterion | Exact check |
|---|---|
| (a) Unattended | `systemctl --user list-timers 'breezy-capture-*'` shows watch, audit and drill timers active. `git -C /home/jon/breezy log --since=<window start> --until=<window end> --format='%H %s' -- src/breezy/persistence/autonomy/ src/breezy/strategy/autonomy_capture/ src/breezy/runtime/capture_watch.py deploy/systemd/` is empty: no human or agent commit sits in the loop during the window. Every `audit_*.json` in the window has `"produced_by":"breezy-capture-audit.service"`. Every `HEALED` row has `"decided_by":"capture_watch"` or `"nbm_quantile_actor"`. The journal for the window shows no manual `systemctl ... breezy-quote-tape` outside the rotate, watch and drill units (`journalctl --user -u breezy-quote-tape --since <window>` start and stop lines correlate one-for-one with `breezy-quote-tape-rotate`, `breezy-capture-watch` or the drill). |
| (b) Family-agnostic | `scripts/ci/run_tests_no_egress.sh tests/unit/autonomy/test_capture_guard_family_agnostic.py tests/unit/test_capture_audit.py::test_unknown_family_fill_is_enumerated_by_construction` passes. ARCH-0 `test_family_plugin_exact_set` passes. |
| (c) Fails closed | `tests/strategy/forecast_quantile_ladder/test_aut1_capture_adapter.py::test_untagged_entry_is_refused_capture_untagged`, `::test_link_write_failure_refuses_entry_capture_gap`, and `tests/unit/autonomy/test_capture_lifecycle_actor.py::test_unparseable_watch_file_vetoes` pass. Node log line `CAPTURE_REFUSED reason=` appears only with a matching `EntryVeto` record. |
| (d) Detected and alerted with delivery | For each failure mode (`CAPTURE_WRITE_FAILED`, `CAPTURE_BYTE_CAP`, `CAPTURE_JOIN_GAP`, `NBP_CYCLE_MISSED`, recorder `HUNG`/`STALLED`/`UNHEALED`/`INACTIVE`, NWS ingest `HUNG`): a gate test exists and asserts `deliver_with_proof` is called. For the live HEALED event: `jq 'select(.event|test("CAPTURE_SELF_HEAL"))' ~/.local/share/breezy/evidence/alerts/delivery_<date>.jsonl` shows `"delivered":true`. |
| (e) RED→GREEN in the gate | For each WP, the implementer's RED output (the failing test names listed in §4) and GREEN output, plus the merge commit SHA. `scripts/ci/run_tests_no_egress.sh; echo EXIT=$?` gives `EXIT=0` on the merge commit. `lint-imports` prints "N kept, 0 broken". |
| (f) Live proof | `jq '.status' ~/.local/share/breezy/evidence/capture/live_proof_pm_us_crh_fq_v1_<asof>.json` is `"PROVEN"`. For each of the 7 dates it lists: `jq '.day_status, .fills_total == .fills_joined' ~/.local/share/breezy/evidence/capture/audit_pm_us_crh_fq_v1_<date>.json` gives `"PASS"` and `true`; the verdict file `~/.local/share/breezy/derived/verdicts/pm_us_crh_fq_v1/<date>/*.json` has `kind=HEALTH`, `detector=capture_join_completeness`, `outcome=PASS`; `jq -s 'map(select(.status=="HEALED"))|length' ~/.local/share/breezy/evidence/capture/self_heal_*.jsonl` is at least 1. |
| Spot check, independent of AUT-1's own audit | For 3 random window fills, `sqlite3 'file:~/.local/share/breezy/state/exec_polymarket_us.sqlite?mode=ro' "select value from state where key='exec/polymarket_us/fill/<id>'"` gives a `clientOrderId`. `/usr/bin/grep -h '"client_order_id": "<that id>"' ~/.local/share/breezy/catalog/quote_tape/decisions/capture_pm_us_crh_fq_v1_*.jsonl*` finds the OrderLink, whose `decision_id` greps to a `Take` record. That Take's `depth_ref` file exists under `derived/capture/blobs/depth/` and `sha256sum` of it matches the name. |

---

## 8. Risks and failure modes

| Risk | Mitigation |
|---|---|
| A capture handler raise unwinds into the execution engine (L-16, message-bus row) | All handlers are catch-all and the writer never raises; `test_handler_never_raises_into_publisher`. |
| Capture blocks trading (fail-closed costs fills, and node-down afternoons feed the KILL; memory `covered-means-recorder-capture-only`) | Vetoes are transient and auto-clear. `recorder_stale` fires only after self-heal fails. Exits are never refused. Every veto is alerted with delivery. |
| A restart loop in the 09:00–09:45Z empty-listing hole | Phase `DISCOVERING` within budget is OK; 600 s rotation grace; Z15 daily cap; `try-restart` never starts an operator-stopped unit. |
| SIGKILL truncates a feather file (zero-row day) | The SIGCONT-after-SIGTERM premise is pinned in WP0, with the reviewed `ExecStop` fallback; `TimeoutStopSec=120` unchanged; the drill runs in the dead window and the guard SIGCONTs at 09:40Z. |
| Memory (31 GB / 30 GiB host; L-29, L-49, L-53) | In-node structures are O(subscribed instruments). Watch 256M, audit 1G, proof 256M, drill 64M. The audit reads no tape. WP0's 14-day measurement runs once under `MemoryMax=4G` outside 01:00–04:30Z. One heavy job at a time (memory `background-sleeps-die-under-memory-pressure`). |
| Shared venv (L-51) | No dependency or console-script changes; `python3 -m` entry points; the exact interpreter in every brief; never `uv`/`pip`/`uv run`. |
| Concurrent agents (L-43, L-50; memory `one-tree-many-agents-fakes-test-failures`) | Disjoint file ownership (§5.3); the trade.py hunk after AUT-5a; the full gate after every merge; one writer per capture file; per-agent scratchpads; no `git stash` (hook-blocked). |
| Statistical capacity | AUT-1's proof is a census and needs only ≥ 1 real fill per qualifying day and ≥ 5 per window. FQ shows 2–3 takes a day. Halts pause the window, and canary days cannot complete it. |
| KILL 2027-01-25 | Planning ETA 2026-10-29 leaves about 13 weeks. If the KILL fires TERMINAL first, the venue has no sender (ARCH §5.3), and AUT-1 can at most stay "machinery proven, window paused". This is stated, not hidden. |
| AUT-5a or AUT-6 slips (an upstream dependency) | WP0, WP1, WP2, WP4 and WP6's core do not depend on them. WP3 waits for AUT-5a and WP5 for AUT-6; neither ships a stub that restarts or vetoes outside the contracts. |
| The trade node's fill events miss resolver fills | The join's fill side is the exec store; leg E/P accept `fill_via_resolver`. |
| A drill becomes a real outage | It runs only from a healthy state, in the Sunday 09:15Z dead window. The 09:40Z guard always resumes the process. A failed heal is CRITICAL. |
| A future second venue (Kalshi) | Paths are venue-scoped (`capture_watch-<venue>.json`, `--venue`). A kind's adapter declares its settlement basis (TWC for Kalshi). |

---

## 9. Binding-constraint compliance

- **Nautilus immutability:** only native extension: `Order.tags`, a `Strategy` subclass override that calls `super()`, `Actor` message-bus subscriptions and `clock.set_timer`. Nothing under `nautilus_trader` is touched.
- **Operator caps:** never read, assigned, defaulted or logged. Capture code is covered by `test_autonomy_never_reads_or_writes_operator_controls` (the scan is extended to AUT-1's paths, never narrowed). L-39: plan and code prose never names the caps' env vars.
- **`allow_short`:** untouched. Every entry stays a BUY (G24); capture only observes.
- **NO-SEND firewall:** the exec client is unedited and byte-pinned. No new egress host; alerts use the existing `alerts.env` key (`test_autonomy_alert_egress_not_widened`). Capture units hold no venue credential.
- **Master enablement and permit:** AUT-1 only adds refusals (restrictive). It never constructs, mints or reads permit authority. It is covered by `test_autonomy_never_touches_enablement_permit_or_firewall`, whose path list is widened to include `strategy/autonomy_capture/` and `runtime/capture_*`.
- **PREREG via ruling:** AUT-1 changes no statistical semantics. Its verdicts are HEALTH census results, and the action mapping is left to the AUT-5 policy ruling.
- **Safety tests never weakened:** every test in §4's list stays green unedited; new contract widenings follow L-12; no test is deleted or relaxed.

---

## 10. Self-score

| Axis | Max | Score | Note |
|---|---|---|---|
| Fidelity (to README, ARCH §10 and the Z deltas) | 20 | 18 | Every obligation is mapped (§1.2). Z2, Z4, Z6, Z11, Z13, Z14, Z15 and Z16 are applied. Four ARCH gaps are surfaced rather than silently redefined (§11). |
| Correctness | 20 | 17 | Premises are code-checked at `4b8347a6`. Seven are deferred to WP0 characterisation: msgbus wildcard, `submit_order` override dispatch, wire body, data topics, SIGCONT, HTTP timeout, silence p99.9. |
| Specificity | 15 | 14 | Exact modules, call sites, keys, thresholds, units and test names. The detector constants take their final values from WP0 measurements. |
| Acceptance | 20 | 18 | Each criterion maps to a command or path. The live proof has its own roll-up artefact. The spot check is independent of AUT-1's audit. |
| Autonomy-safety | 15 | 14 | Restrictive-only; exits never blocked; no unit-file or env edits by the bot; the drill is guarded. The `recorder_stale` veto policy is a judgement call. |
| Reuse | 10 | 9 | Native tags, events, actors and timers; existing exec store, settlement reader, retention, alert and restart paths. Two minimal new stores (blobs, heartbeat), each justified in §2. |
| **Total** | 100 | **90** | |

---

## 11. Contradictions and gaps found against ARCH Rev 3 (to dispose in Rev 4)

1. **The README "no NBP positive log line" is stale.** `NBM_NBP_PUBLISHED` (`nbm_quantile_actor.py:545-551`) and `FQ_VECTOR_COMPLETE` (`forecast_subscriber.py:217-221`) exist and appear in the live log. The open gap is *absence detection and alert delivery*, which AUT-1 closes (§3.5.1).
2. **Idle timeout.** The brief's "60 s" is the Nautilus mechanism; Breezy configures 600 s (`config.py:293`). Horizons are derived from the configured value.
3. **C1 `OrderLink.intent_id` cannot be populated by the node.** The intent is armed inside the byte-pinned exec client, and the `SubmitIntent` singleton (`submit_intent.py:37,236-266`) has no `client_order_id` and no history. AUT-1 writes `null`. The audit takes AMBIGUOUS linkage from durable resolver contexts (`exec/client.py:454,1085-1124`). The join does not need `intent_id`, because `client_order_id` is in `DurableFillRecord`. Rev 4 should mark `intent_id` nullable with this reason.
4. **C1 names `depth_ref` and `forecast_input_sha256` with no preimage store.** AUT-1 adds the content-addressed `derived/capture/blobs/` (§3.3.2). Rev 4 should list it under C1 storage.
5. **C1 storage path versus the common rule.** C1 puts capture under `decisions/` (`catalog/quote_tape/decisions`), while the common rules require `{state,derived,registry,evidence}`. AUT-1 follows C1's explicit, more specific path. Rev 4 should state the exception.
6. **C1 "a daily file" with both node and offline writers would breach L-50.** AUT-1 splits off `capture_<family>_<date>.offline.jsonl` for `SettlementRecord`.
7. **Sequencing.** ARCH §5.1 places AUT-1 in Wave 1, but `app/trade.py` is AUT-5a-only in Wave 1, and the FQ `try_submit` slot is AUT-5's. AUT-1's composition hunk (WP3) is therefore Wave 1b, after AUT-5a.
8. **The ownership boundary between AUT-1 and AUT-6** (§5 table versus §10) is resolved this way: AUT-1 implements the three capture and feed NODE_LOCAL detectors and the unit membership; AUT-6 owns the restart call site, the catalogue and the intraday producer. `permit_lapsed` stays with AUT-6.
