# AUT-1 — Data capture: area plan, round 6 (residual MEDIUM/LOW fixes on frozen ARCH Rev 9.2)

## 0. Header

| Field | Value |
|---|---|
| ID | AUT-1, delivered as **AUT-1a** (Wave 1, offline and out-of-node) and **AUT-1b** (after AUT-5a merges: strategy hooks, guard, `src/breezy/app/trade.py` hunk, node-local detectors), per ARCH Rev 9.2 §5.1 (P1-7) |
| Title | Data capture: every decision, order, fill, mark and settlement for every family, joined on one `decision_id`, reconciled daily against independent sources, with recorder and feed stall observation and self-heal |
| Round | r6 (2026-10-03). r1–r5 are unchanged. Inputs: r5 (`docs/plans/backlog/AUTONOMY_2026-10-03/AUT-1-data-capture_plan_r5.md`) and the merged review `docs/plans/backlog/AUTONOMY_2026-10-03/reviews/AUT-1-r5-merged.md` (trading-bot-architect 95, silent-failure-hunter 93; zero CRITICAL or HIGH; items T1–T4 and L1–L4, with the coordinator ruling in T3). Every r5→r6 change is disposed in §R6; §R3–§R5 stay as history. r5's own round note follows. r5 (2026-10-03) was the final polish of r4. Inputs: r4 (`docs/plans/backlog/AUTONOMY_2026-10-03/AUT-1-data-capture_plan_r4.md`) and the merged final-round review `docs/plans/backlog/AUTONOMY_2026-10-03/reviews/AUT-1-r4-merged.md` (trading-bot-architect 92, silent-failure-hunter 89; zero CRITICAL or HIGH; items H1–H11). The frozen ARCH, its errata, `PLAN_TEMPLATE.md` and the coordinator decisions are consumed as in r4. Every r4→r5 change is disposed in §R5; §R3 and §R4 stay as history. |
| ARCH consumed | **FROZEN Rev 9.2**: `docs/plans/backlog/AUTONOMY_2026-10-03/reviews/snapshots/ARCH_rev9_2.md`, sha256 `1b288d0e0172b233b791d875845e8002824a52d4a2e7819685ec0f2057572f42` (re-hashed 2026-10-03; the `README.md` Items table names this revision), plus the binding errata `docs/plans/backlog/AUTONOMY_2026-10-03/reviews/ARCH-ERRATA-rev9_2.md` (E-1…E-4). ARCH is not reopened: every residual tension is resolved in this plan by conforming to ARCH (§11). Section and tag citations are to Rev 9.2. Per E-3, Rev 9.2 change tags are written `R9.2-Z1…Z9`, and a bare `Z<n>` keeps its pre-9.2 meaning. |
| Code baseline | `feat/data-capture-and-risk` @ `4b8347a6`. Every `file:line` was read at that sha through codegraph (`projectPath=/home/jon/breezy`) or `/usr/bin/grep`/`sed` on the named file. |
| Paths | Every code, test, deploy and doc path is repo-root-relative (repo `/home/jon/breezy`). Runtime store paths written `evidence/…`, `derived/…`, `health/…` or `registry/…` are under the absolute root `/home/jon/.local/share/breezy/` (ARCH §3 common rules). `<decisions_dir>` is the absolute `/home/jon/.local/share/breezy/catalog/quote_tape/decisions/`, the sibling of the quote-tape catalog root (`src/breezy/app/trade.py:774`; checked 2026-10-03: `fq_funnel_2026-10-02.jsonl` and `offer_tape_*.jsonl.gz` live there). A bare `:NNN` line citation refers to the file cited just before it. |
| Current score | 2 |
| Target | 3 |
| Upstream | ARCH-0 (Wave 0: `src/breezy/persistence/autonomy/` schemas, C4 writer, C6 Protocols, `NODE_PLUGINS`, `RefusingPlugin`, `VetoReason`, `src/breezy/persistence/autonomy/pins.py`, `test_autonomy_files_have_one_writer`); AUT-5a (`ResolvedFamily`, `RegistryWatchActor.drill_active`, the required `entry_veto` slot (W10), sole owner of `src/breezy/app/trade.py` in Wave 1); AUT-6 (`deliver_with_proof`, the node `AlertOutbox` (W9; claim order per errata E-1), the SELF_HEAL executor `breezy-autonomy-health` and its restart site with argv `["systemctl","--user","try-restart","--no-block",unit]` and write-once `evidence/selfheal/<trading_date>/` records (ARCH §4.5, W11, P1-12), the migrated `study_failure_notifier`); AUT-5b (the policy ruling that takes the health unit out of ALERT_ONLY, ARCH §4.6); AUT-2 (the canary producer) |
| Downstream | AUT-2 (C1 capture files, `settlement_<date>.jsonl`, the payload store, the pure join reader, `capture_epoch_start`); AUT-4 (payloads, `CAPTURE_INCOMPLETE`, `capture_tape_ingest`, the 38-vs-35 attribution record); AUT-6 (`DetectorEvent`s, NODE_LOCAL detectors, the `capture_watch/v1` restart requests); AUT-5 (HEALTH verdicts, proposed policy rows) |

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

The README live-proof window rule binds it (verbatim):

> A day counts toward any N-day live-proof window only if it has at least one real fill, or a clearly tagged synthetic canary fill that traverses the production path. Zero-fill days do not count, and the window extends. Every window also needs at least 5 real fills, and canary fills never count toward that or any statistic.

### 1.2 ARCH Rev 9.2 §10 "Area plan obligations", AUT-1 (verbatim)

> **AUT-1:** the `CaptureAdapter` call sites per composable kind; measured C1 volume per day; the `EntryVeto` record writer; the node-local observations behind `feed_stale`, `recorder_stale`, `capture_gap` (source, period, clear condition); the recorder and feed stall observations, naming each unit AUT-6 may restart; the daily join audit with offline intent linkage (P1-3); the payload store and volume (P1-4); the settlement writer (P1-6); `capture_epoch_start`; with AUT-4, the live-vs-batch parity take divergence (38 vs 35); the `Exit` id function and record (P1-8); the `capture_untagged` refusal (P1-9); restarts only via AUT-6 (P1-10, P1-12); `quote_ref` payloads and `wall_ns` (U8, U9).

| Obligation | Section | Slice |
|---|---|---|
| `CaptureAdapter` call sites per kind | §3.4 | 1a (adapter), 1b (hooks) |
| Measured C1 volume | §3.2 | 1a WP0 |
| `EntryVeto` writer | §3.4 CS-2, §3.5 | 1b |
| `feed_stale`, `recorder_stale`, `capture_gap` | §3.7 | 1b |
| Stall observations, units AUT-6 may restart | §3.8 | 1a |
| Daily join audit with offline intent linkage | §3.10 (leg I) | 1a |
| Payload store and volume | §3.3.2, §3.2 | 1a |
| Settlement writer | §3.9 | 1a |
| `capture_epoch_start` | §3.3.5 | 1a (library, audit), 1b (node write) |
| 38-vs-35 parity divergence (with AUT-4) | §3.12 | 1a WP6 |
| `Exit` id function and record (P1-8) | §3.3.1, §3.5.2 | 1a (id), 1b (guard in FQ) |
| `capture_untagged` refusal (P1-9) | §3.5.2 | 1a (library), 1b |
| Restarts only via AUT-6 (P1-10, P1-12) | §3.8.3 | 1a |
| `quote_ref` payloads and `wall_ns` (U8, U9) | §3.3.1, §3.3.2, §3.4.1, §3.4.2 | 1a (store, ids), 1b (hooks) |

### 1.3 Known facts, with the code check at `4b8347a6`

Facts carried from r2 are still true and are not repeated: recorder zombie classes, the 600 s idle timeout (G31), the funnel being per boot and cumulative, the node-log formats, the `extend_dedupe:` format, the notifier swallowing failures, and oneshot semantics (G32). New in r3, and in r4 where marked:

| Fact | Evidence | Used in |
|---|---|---|
| A market-data frame publishes its `QuoteTick` **before** its `OrderBookDepth10`. Both share `transactTime` as `ts_event`, and the depth top equals the quote. | `src/breezy/adapters/polymarket_us/data.py:1584-1600` (quote `_handle_data` at `:1590`, depth at `:1599`); `src/breezy/adapters/polymarket_us/parsing.py:790-801`; `tests/unit/test_polymarket_us_depth_parsing.py:132` `test_the_top_of_the_depth_record_equals_the_quote_tick` | D2 (§3.4.2) |
| FQ evaluates on both triggers. `_safe_evaluate` receives `source ∈ {"depth","quote_tick"}` and drops it. | `src/breezy/strategy/forecast_quantile_ladder/strategy.py:713-738`, `:740-757` (`:753` drops `source`) | D2, D5 |
| A quote-triggered evaluation reaches `latch.latch` inside `evaluate` **before** any capture or guard code runs. Refusing a quote Take at the guard would therefore consume the rung-day latch. | `src/breezy/strategy/forecast_quantile_ladder/decision.py:357`; `src/breezy/strategy/forecast_quantile_ladder/strategy.py:818-819` | D2 (why "refuse at the guard" is rejected) |
| Take and evaluator lines use `now_ns = ts_event` (venue time). The TrySubmit line uses `self.clock.timestamp_ns()` (wall time). | `src/breezy/strategy/forecast_quantile_ladder/strategy.py:805-806` → `:564-567`; `:700-701` | D5; the C1 `eval_ns`/`wall_ns` mapping (§3.4.1) |
| FQ has exactly **two** trigger paths into `try_submit`: `on_order_book_depth` and `on_quote_tick`. The only clock timer, `:426`, is the D+1 readiness subscribe poll. | `src/breezy/strategy/forecast_quantile_ladder/strategy.py:410-453`, `:666`, `:713-738`, `:819` | D14 |
| **(r4)** Each handler call evaluates **exactly one** decision. `_evaluate_instrument_update` makes one `evaluate_snapshot` call (`:805`) and resolves `(station, climate_day, rung_id, side)` from `self._instrument_context[iid]` (`:779-786`). **(r5, H2)** That does **not** make `eval_seq` always 0: one frame reaches FQ as two handler calls, the quote and then the depth (first row), with the same `(instrument_id, ts_event)`. A per-call ordinal would give both `eval_seq=0` and therefore the same `decision_id`, because kind and reason are not id inputs. r5 counts the ordinal per `(instrument_id, ts_event)` across handler calls (§3.3.1). | `src/breezy/strategy/forecast_quantile_ladder/strategy.py:759-819`; `src/breezy/adapters/polymarket_us/data.py:1590`, `:1599` | §3.3.1, §3.4.1 |
| **(r4)** The four native exit tags are `exit_rule=`, `exit_position_id=`, `exit_family_id=` and `exit_client_order_id=`. | `src/breezy/persistence/exit_tags.py:42-45` | §3.3.1 (`Exit` id) |
| `Take` carries `ev_net`, `p_hat`, `p_lower` and `p_upper`. It has no `p_hat_raw` and no ask. The live calibration refuses any `recalibration` other than `none`. | `src/breezy/strategy/forecast_quantile_ladder/decision.py:155-172`, `:331`; G11 (`src/breezy/strategy/forecast_quantile_ladder/calibration_artefact.py:281-295`) | §3.4.1 field map |
| `intent_fingerprint(order)` is a pure, duck-typed sha256 over `str()` of `instrument_id`, `side`, `quantity`, `price`, `time_in_force` and `client_order_id`. Fills are indexed by `fill_by_fingerprint/<day>:<fp>`. | `src/breezy/adapters/polymarket_us/exec/submit_chain.py:242-253`; `src/breezy/adapters/polymarket_us/exec/client.py:447`, `:2123`, `:4679` | leg I |
| The funnel flushes every 15 min. | `src/breezy/strategy/forecast_quantile_ladder/decision_funnel.py:47` `DEFAULT_FLUSH_INTERVAL_SECONDS = 15 * 60` | D13 |
| `submit_order` call sites under `src/breezy/strategy/` | FQ `src/breezy/strategy/forecast_quantile_ladder/strategy.py:688`; CRH `src/breezy/strategy/current_rung_hold/strategy.py:764`; `src/breezy/strategy/current_rung_hold/continuous_strategy.py:2954`; `src/breezy/strategy/current_rung_hold/exit_wiring.py:311` (its only importer is `src/breezy/strategy/current_rung_hold/continuous_strategy.py:56`); `src/breezy/strategy/current_rung_hold/backtest_only.py:127`; `src/breezy/strategy/harness_probe.py:208`. There are **no** `submit_order_list` call sites. | D4 |
| The ingest prints many `extend_dedupe:` lines with `chunks=0`. Over the last 10 days: 417 lines `chunks=0 … flat_root=none`, 124 legacy lines with no `flat_root` field (pre-ING-2-AMEND2), and 3 lines with chunks > 0. The type name is `custom_depth_truncation` (`class_to_filename(DepthTruncation)`, `src/breezy/runtime/quote_tape_salvage.py:275`). | `journalctl --user -u breezy-quote-tape-ingest` (10 d); `src/breezy/runtime/quote_tape_salvage.py:296-302` | D15, leg T |
| **The 38-vs-35 divergence.** `~/.cache/breezy-gate/parity-mem-7d.json` (2026-09-01..07): `n_live_yes_Take=38`, `n_batch_yes_Take=35`, `n_numeric_mismatches=9`, `n_live_yes_NotExecutable=0` vs `n_batch_yes_NotExecutable=493796`. The 1-day run gives 5 vs 5. Both `breezy-parity-mem-{1d,7d}.service` runs are `failed` (exit 1) after writing the JSON. | the file and `systemctl --user list-units 'breezy-*parity*'` | §3.12 |
| **(r4)** ARCH Rev 9.2 lets AUT-6's executor `try-restart --no-block` an **active** allowlisted recorder classified HUNG (§4.5 `SELF_HEAL_RESTARTABLE_UNITS`, U11), with a `subprocess` timeout ≤ 30 s and at most 3 restarts per unit per trading day [16:45Z, next 16:45Z), counted from `evidence/selfheal/<trading_date>/`. `aut6.health` fires `*:01/10`; inside [16:30Z, 17:10Z) its restarts are deferred to 17:10Z and journaled (§5.2 table, V7). Until the policy ruling is filed, the health unit is alert-only (§4.6). | ARCH Rev 9.2 §4.5, §4.6, §5.2 | §3.8.3 |

---

## 2. L-1 null hypothesis and reuse

"WP0" marks a premise that WP0 pins with mutation evidence (L-33) before the slice relying on it starts (L-47).

| New component | Capability checked (file:line) | Verdict |
|---|---|---|
| Per-decision capture record | Nautilus `StreamingConfig` (rejected by C1); FQ funnel counts (`src/breezy/strategy/forecast_quantile_ladder/decision_funnel.py:52-181`); CRH `OfferTape` (`src/breezy/strategy/current_rung_hold/offer_tape.py:335-439`) | **Extend.** A new writer on the `OfferTape` shape, adding fsync on order-path records, short-write recovery and a loud cap. The funnel stays unedited as an independent cross-check. |
| `decision_id` carrier | Native `Order.tags` (G9); `src/breezy/persistence/exit_tags.py:37-48` | **Reuse native.** `DECISION_ID_TAG_PREFIX` in `src/breezy/persistence/exit_tags.py`; exec client unedited (G33). WP0: the tag is absent from the wire body. |
| Payload store | C1 Rev 9.2 defines it (`derived/capture_payloads/{depth10,quote,forecast_input}/<sha256>.json`, `mkstemp` + `os.link`, 0444, `payload/v1`) | **Implement the contract.** Nothing to reuse; the content address replaces a database. |
| Quote preimage | C1 Rev 9.2 `quote` sub-store (`ask`, `bid`, `ts_event`; U8, from P1-13) | **Implement the contract** (§3.4.2). r3's fallback is deleted. |
| Order lifecycle capture | `events.order.{strategy_id}`, `events.position.{strategy_id}` (nautilus 1.231.0); `Actor.msgbus.subscribe` | **Reuse native.** WP0: wildcard delivery; handlers are catch-all (L-16). |
| Submit-time refusal | `RiskEngine` (immutable); exec client deny chain (byte-pinned); `Strategy.submit_order`, `submit_order_list` | **Extend by subclassing.** `CaptureGuardedStrategy` overrides both and calls `super()`. WP0 gates WP7 on override dispatch. |
| Offline intent linkage | `intent_fingerprint` (`src/breezy/adapters/polymarket_us/exec/submit_chain.py:242-253`), pure; `FILL_BY_FINGERPRINT_KEY_PREFIX` (`src/breezy/adapters/polymarket_us/exec/client.py:447`); `SubmitIntent` (`src/breezy/runtime/submit_intent.py:37,391-411`); resolver contexts (`src/breezy/adapters/polymarket_us/exec/client.py:449-454`) | **Reuse.** The audit (`analysis`, above `adapters`) imports `intent_fingerprint` and the key constants. The node stores the six `str()` forms in `OrderLink`; WP0 pins their equality with a real order's fingerprint. |
| Settlement writer | `read_climate_day_including_corrections` (`src/breezy/persistence/catalog.py:637`) | **Reuse** inside a new oneshot with its own lock (C1: "offline settlement unit (own file)"). |
| `capture_epoch_start` | None in Nautilus; supervisor boot records hold no capture identity | **New, minimal:** one write-once file per family (§3.3.5). |
| Per-instrument freshness | Data-client counters (adapter-only); passive topics | **Reuse the strategy's own handlers** (CS-4 stamps a frame clock before evaluating). This **replaces** r2's passive actor subscription, whose delivery order relative to the strategy is not guaranteed (D14). |
| NBP absence and hang | `_check_stale_cycle` (`src/breezy/ingest/nbm_quantile_actor.py:425-449`), `_submit` (`:340-353`) | **Extend** (retain the `Future`, reset on hang). |
| Recorder liveness and writer stall | systemd `Restart=always` (blind to a zombie); `QuoteTapeDiskMonitor` (disk only); 10 s feather flush (`src/breezy/runtime/node_config.py:308`) | **New:** recorder heartbeat and an external watch. Neither systemd nor Nautilus offers a "bytes are landing" probe. |
| Restart | AUT-6 `breezy-autonomy-health`, the **only** autonomy caller of the restart site (ARCH §4.6) | **Consume.** AUT-1 has no restart call site. It publishes restart requests in `capture_watch/v1`. |
| Fill and order census | `DurableFillRecord` (`src/breezy/adapters/polymarket_us/exec/client.py:949-976`); `FILL_KEY_PREFIX` (`:408`), `FILL_BY_DAY_KEY_PREFIX` (`:429`), `VENUE_ORDER_ID_KEY_PREFIX` (`:404`), `RESOLVER_CONTEXT_KEY_PREFIX` (`:454`); `mode=ro` (G6) | **Reuse, read-only.** |
| Independent denominators | Node log `SHADOW_DECISION`, `OrderSubmitted`, `OrderFilled`, `NBM_NBP_PUBLISHED`, `FQ_VECTOR_COMPLETE`; funnel JSONL; recorder tape | **Reuse, read-only, streaming.** |
| Build identity, retention, alerts | `resolve_build_revision` (`src/breezy/runtime/build_sha.py:147-190`); `scripts/ops/decisions_retention.py:77-80`; AUT-6 `deliver_with_proof` and outbox | **Reuse / consume.** |

---
## 3. Design

### 3.0 Slices (ARCH Rev 9.2 §5.1; D1)

| Slice | Contents | Starts | Depends on |
|---|---|---|---|
| **AUT-1a** | WP0 premises; WP1 capture core (`src/breezy/persistence/autonomy/`); WP2 `FqCaptureAdapter`, `src/breezy/strategy/forecast_quantile_ladder/plugin.py` and `CaptureGuardedStrategy` as a **library** (not yet FQ's base class); WP3 recorder heartbeat, capture watch, watchdog; WP4 NBP hang reset (ingest; built and reviewed in Wave 1, **merged with WP8**, r6 T2); WP5 settlement writer, audit, node-log parser, live-proof roll-up, retention; WP6 parity attribution | Wave 1, against ARCH-0 stubs | ARCH-0; AUT-6 for unit activation (notifier) |
| **AUT-1b** | WP7 strategy hooks CS-1..CS-6, FQ re-based on the guard, submit-site AST test, full-path benchmark; WP8 lifecycle actor, node-local detectors, epoch write, the single `src/breezy/app/trade.py` hunk; WP9 weekly stall drill | After AUT-5a merges | AUT-5a (slot, `src/breezy/app/trade.py`), AUT-6 (outbox, and the node-liveness detector WP7 depends on, r6 T3); WP4's merge rides with WP8 (r6 T2); WP9 also needs AUT-5b's ruling |

### 3.1 Module map (layering: app > analysis > strategy > runtime > adapters > ingest > persistence|registry|normalize > settlement > domain)

| Module | Layer | New/edit | Purpose | Slice |
|---|---|---|---|---|
| `src/breezy/persistence/autonomy/capture_ids.py` | persistence | new | `compute_decision_id`, `compute_exit_decision_id`, `compute_orphan_decision_id`, `depth_ref_of`, `quote_ref_of`, `forecast_input_sha256_of` | 1a |
| `src/breezy/persistence/autonomy/capture_on_change.py` | persistence | new | `OnChangeFilter`, pure and deterministic, shared by the writer and audit leg R2 (D9) | 1a |
| `src/breezy/persistence/autonomy/capture_writer.py` | persistence | new | `CaptureWriter`, `CaptureIdentity`, `CaptureWriterHealth`, `CaptureWriteFailure` | 1a |
| `src/breezy/persistence/autonomy/capture_payloads.py` | persistence | new | `PayloadStore` (C1 payload store); `AsyncPayloadWriter`, the bounded writer thread for refusal-record payload puts (r6 T3, §3.3.2) | 1a |
| `src/breezy/persistence/autonomy/capture_alerts.py` | persistence | new | `CAPTURE_ALERT_EVENTS` (the closed tuple of every §3.13 event string), `CAPTURE_EVENT_RE = ^[A-Z0-9_]{1,96}$`, `heal_alert_event(observation_sha256)` (r6 T4) | 1a |
| `src/breezy/persistence/autonomy/capture_epoch.py` | persistence | new | `write_epoch_once`, `read_epoch` | 1a |
| `src/breezy/persistence/autonomy/capture_reader.py` | persistence | new | `read_capture_day`, `join_fills_to_decisions` (fills as plain values, W6) | 1a |
| `src/breezy/persistence/autonomy/capture_watch_state.py` | persistence | new | `capture_watch/v1`, `recorder_heartbeat/v1`, `capture_watchdog/v1`, `RestartRequest`; single-read loader | 1a |
| `src/breezy/persistence/autonomy/capture_schedule.py` | persistence | new | `LAUNCH_WINDOW_UTC = ((16, 30), (17, 10))`; `launch_window_guard(now_ns, flock_wait_s, timeout_start_s) -> bool`; `seconds_outside_launch_window(start_ns, end_ns) -> int`. Pure (§3.11). If ARCH-0 ships an equivalent in `src/breezy/persistence/autonomy/pins.py`, AUT-1 imports that instead (L-1). | 1a |
| `src/breezy/persistence/exit_tags.py` | persistence | edit | `DECISION_ID_TAG_PREFIX` (L-12 widening of `__all__`) | 1a |
| `src/breezy/strategy/autonomy_capture/guarded_strategy.py` | strategy | new | `CaptureGuardedStrategy(Strategy)` | 1a (library) |
| `src/breezy/strategy/autonomy_capture/frame_clock.py` | strategy | new | `FrameClock`: per-instrument last-frame time, written by the strategy handlers (CS-4); `next_eval_seq(instrument_id, ts_event)`, the bounded per-frame ordinal counter (§3.3.1, r5 H2) | 1a |
| `src/breezy/strategy/autonomy_capture/lifecycle_actor.py` | strategy | new | `CaptureLifecycleActor(Actor)`: order and position events, positive-control timer, epoch write | 1b |
| `src/breezy/strategy/autonomy_capture/node_observations.py` | strategy | new | NODE_LOCAL detectors `capture_writer_health`, `md_feed_freshness`, `recorder_liveness` | 1b |
| `src/breezy/strategy/forecast_quantile_ladder/capture_adapter.py` | strategy | new | `FqCaptureAdapter` (C6 `decision_record`, `order_tags`), `CaptureContext`, NODE_LOCAL `nbp_feed_freshness` | 1a (class), 1b (wiring) |
| `src/breezy/strategy/forecast_quantile_ladder/plugin.py` | strategy | new | FQ entry in `NODE_PLUGINS` with `capture_adapter`; AUT-6 adds its `drift_detectors` tuple | 1a |
| `src/breezy/strategy/forecast_quantile_ladder/strategy.py` | strategy | edit | base class `CaptureGuardedStrategy`; `_safe_evaluate`, `_evaluate_instrument_update`, new `_evaluate_with_capture`, `evaluate_snapshot` (thin wrapper, same signature), `_maybe_submit`, `_emit_decision_outcome`, `on_order_book_depth`, `on_quote_tick`. The `entry_veto` slot inside `try_submit` is AUT-5a's. | 1b |
| `src/breezy/ingest/nbm_quantile_actor.py` | ingest | edit | retain the `Future`; poll-hang reset; write-once heal record carrying `observation_sha256` and its `CAPTURE_HEALED_<sha>` outbox alert (§3.14); keyword-only `heal_alert_offer: Callable[[str, str], bool] \| None = None` (event, severity), a duck-typed callable so ingest never imports the runtime outbox (layering); absent at heal time → CRITICAL log and `alert="undeliverable"` (r6 T2) | 1a (built), merged with WP8 |
| `src/breezy/ingest/records.py` | ingest | edit | public alias `climate_day_end_ns` of the existing `_climate_day_end_ns` (`:363`), L-12 widening, for leg S (r5 H11) | 1a |
| `src/breezy/adapters/polymarket_us/{config,data}.py`, `src/breezy/runtime/node_config.py` | adapters/runtime | edit | opt-in recorder `heartbeat_path` | 1a |
| `src/breezy/runtime/capture_watch.py`, `src/breezy/runtime/capture_watch_cli.py` | runtime | new | recorder and NWS-ingest classification, restart requests, heal confirmation | 1a |
| `src/breezy/runtime/capture_watchdog.py`, `src/breezy/runtime/capture_watchdog_cli.py` | runtime | new | watch of the watch; audit dead-man | 1a |
| `src/breezy/runtime/capture_stall_drill_cli.py` | runtime | new | weekly injected recorder stall | 1b (WP9) |
| `src/breezy/analysis/capture_settlement.py`, `src/breezy/analysis/capture_settlement_cli.py` | analysis | new | `SettlementRecord` writer | 1a |
| `src/breezy/analysis/capture_audit.py`, `src/breezy/analysis/capture_audit_cli.py`, `src/breezy/analysis/capture_node_log.py` | analysis | new | daily audit, streaming node-log parser | 1a |
| `src/breezy/analysis/capture_live_proof.py`, `src/breezy/analysis/capture_live_proof_cli.py` | analysis | new | 7-day roll-up | 1a |
| `src/breezy/analysis/capture_parity_attribution.py` | analysis | new | per-key diff for the 38-vs-35 divergence (§3.12) | 1a |
| `src/breezy/app/trade.py` | app | one hunk, after AUT-5a | construct identity, writer, payload store, frame clock, adapter and actor in `_compose_forecast_quantile_ladder` (`:676-850`); append the actor to `extra_actors`; pass the node `AlertOutbox.offer` into `NbmQuantileActor` as `heal_alert_offer` (r6 T2) | 1b |
| `deploy/systemd/breezy-capture-{watch,watchdog,settlement,audit,live-proof,stall-drill,stall-drill-guard}.{service,timer}` | deploy | new | §3.11 (r5: the live-proof unit gains a fallback timer, H11) | 1a/1b |
| `scripts/ops/decisions_retention.py` | scripts | edit | widen to `(capture|settlement)_[a-z0-9_]+` (L-12) | 1a |

Entry points: `/home/jon/breezy/.venv/bin/python3 -m <module>`. There is no console script, because adding one needs a reinstall into the shared venv (L-51).

### 3.2 C1 and payload volume (obligations 2 and "payload volume")

- **Measured** (`breezy-trade-20261002T205521Z.log`, 20:55Z 10-02 to 03:57Z 10-03): 973,921 FQ evaluations over 24 `(station, climate_day, rung_id, side)` keys; the on-change rule gives 59 records. UTC day 10-01 funnel: 3,288,397 evaluations, 2 Take, 2 TrySubmit.
- **Projection, for sizing only:**

  | Item | Per day |
  |---|---|
  | On-change records | ≈ 250 |
  | Order records | ≈ 8 per order × 2–5 orders |
  | DetectorEvents (transitions) | < 50 |
  | Total | < 400 records, ≈ 0.4 MB |
  | Depth payloads (written only with a citing record) | ≤ 250 × ≈ 2 KiB ≈ 0.5 MB |
  | Forecast payloads (one per distinct vector) | ≈ 12 |
  | Quote payloads | ≤ number of Takes |
  | `settlement_<date>.jsonl` | 5 stations × ≤ 2 records (correction) |

- **Cap.** `CAPTURE_MAX_BYTES_PER_FAMILY_DAY = 64 MiB` (> 100× projection). WP0 re-measures a full UTC day; above 5,000 records the cap is revisited in a reviewed commit before WP7.
- **Availability cost of a cap hit.** `health.ok=False` refuses entries (`capture_gap`) until the next UTC-day file. At the measured cadence that forfeits at most one day's ≤ 3 takes. Exits are never refused.

### 3.3 Capture core (`src/breezy/persistence/autonomy/`, AUT-1a)

#### 3.3.1 Ids (`src/breezy/persistence/autonomy/capture_ids.py`)

- `compute_decision_id(family_id, manifest_sha256, artefact_sha256, station, climate_day, rung_id, side, eval_ns, eval_seq) -> str`: the first 32 hex characters of sha256 over `"|".join(...)` in exact C1 order (ARCH Rev 9.2 C1, R9.2-Z9).
  - `eval_ns` is the triggering event's `ts_event` (the handler's own event).
  - **`eval_seq` (r5, H2)** is the 0-based ordinal of the decision among all decisions evaluated for the same `(instrument_id, ts_event)`, counted **across handler calls** in arrival order, so it is deterministic by arrival. For one FQ frame the quote-triggered decision gets 0 and the depth-triggered decision gets 1 (§1.3). It is counted for **every** evaluation, admitted by the on-change filter or not, so audit leg R2 can recompute it from the log (§3.10).
  - The counter is `FrameClock.next_eval_seq(instrument_id, ts_event)`. It retains the last 4 `ts_event`s per instrument with their counts, so it is O(subscribed instruments). A `ts_event` that is not retained and is older than the newest retained one is non-monotone: its ordinals start at `EVAL_SEQ_REORDER_BASE = 1_000_000` plus a per-instrument count of such frames, so no ordinal can repeat, and `CAPTURE_EVAL_SEQ_NONMONOTONE instrument_id=<i>` is logged at most hourly per instrument. WP0 item 12 measures the rate (expected 0).
  - ARCH says "among those evaluated in that handler call"; r5 reads the handler call as the frame's delivery, both handlers included, which is the only reading under which `test_decision_id_unique_per_take` holds for FQ (§11 R-10). Tests `test_same_frame_quote_and_depth_get_distinct_ids`, `test_eval_seq_counts_unadmitted_evaluations`, `test_eval_seq_counter_is_bounded_per_instrument`, `test_nonmonotone_ts_event_never_repeats_an_ordinal`.
  - Both are recorded. Recomputation uses the record's own fields and never re-derives them (`test_decision_id_recomputes_from_stored_record`; ARCH `test_decision_id_unique_per_take`).
  - **Downstream readers (r6, L1).** AUT-2 (the join reader and labels) and AUT-4 (payload consumers, parity) read `eval_ns` and `eval_seq` from the stored record and never re-derive them from logs, frames or the counter rule; ARCH C1 makes the recorded value authoritative. Only AUT-1's audit leg R2 recomputes `eval_seq`, and only to cross-check the writer (§3.10). `join_fills_to_decisions` exposes the stored values unchanged (`test_join_exposes_stored_eval_seq_never_recomputed`). This is stated as a consumer contract in §5.2.
  - Every id-bearing record of one decision carries the same `eval_ns` and `eval_seq`, so each one recomputes to its id. These are the Take or refusal, and its `TrySubmit`, `EntryVeto` or `Refuse(instrument_vanished_after_trysubmit)`.
- `compute_exit_decision_id(exit_rule, exit_position_id, exit_family_id, exit_client_order_id)`: the first 32 hex of sha256 over `"exit/v1|" + "|".join(...)` of **the four native exit tag values only** (`src/breezy/persistence/exit_tags.py:42-45`), in that pinned order. This follows C1 P1-8: "a pure sha256 over those values (AUT-1 pins it)". No non-tag value enters (`test_exit_decision_id_uses_only_the_four_exit_tag_values`).
- `compute_orphan_decision_id(family_id, client_order_id)`: `"orphan/v1|"…`. Used **only** for an untagged SELL's `OrderLink` (D12). No `DecisionRecord` ever carries it, so the audit can recognise it by recomputation and fails the fill (`untagged_order`).
- **Refs are payload-store names.** `depth_ref_of(depth)`, `quote_ref_of(quote)` and `forecast_input_sha256_of(vector, station)` each build the canonical `payload/v1` bytes that `PayloadStore.put` writes (§3.3.2) and return their sha256, with no I/O. So a record's ref always equals its payload's file name (`test_ref_equals_payload_store_name`). r3 hashed a separate `"depth10/v1|…"` string, which the store never wrote. Bodies:
  - `depth10`: `{instrument_id, ts_event, bids, asks}`, levels with size > 0 only. `ts_init` is excluded, so node and recorder rows hash equal (`test_depth_ref_excludes_ts_init_and_size_zero_pads`).
  - `quote`: exactly `{ask, bid, ts_event}`, prices as string decimals (C1, U8). The instrument is carried by the citing record's `instrument_id`. Two instruments with an identical quote therefore share one payload, which is harmless for a content address (`test_quote_payload_body_is_exactly_ask_bid_ts_event`).
  - `forecast_input`: canonical JSON of the `ForecastQuantileVector` fields (`src/breezy/strategy/ladder_ev/forecast_state.py:282-294`) plus `station`.

#### 3.3.2 Payload store (`src/breezy/persistence/autonomy/capture_payloads.py`; C1 "Payload store")

- Root `/home/jon/.local/share/breezy/derived/capture_payloads/{depth10,quote,forecast_input}/<sha256>.json` (C1, U8). Directories 0700, files 0444, schema `payload/v1` = `{schema, payload_kind, body}` with `payload_kind ∈ {depth10, quote, forecast_input}`. A record whose cited payload is missing is `capture_gap` (C1).
- `PayloadStore.put(kind, body) -> PutResult(sha256, created: bool)`:
  1. canonical bytes, then sha256;
  2. `mkstemp` in the target directory, write, `fsync`;
  3. `os.link(tmp, final)`;
  4. on `FileExistsError`, single-read (`O_NOFOLLOW`) the existing file and require `sha256(bytes) == name`, otherwise CRITICAL `CAPTURE_PAYLOAD_COLLISION` and `health.ok=False`;
  5. `unlink(tmp)`;
  6. on `created`, `fsync` the directory.

  An existing name is never replaced (`test_payload_put_never_replaces_existing_name`).
- **Write-on-change (C1, L-29).** The node calls `put` only for a record that cites the payload, after the on-change test passes (CS-1).
- **Refusal payloads are written off the event loop (r6 T3, coordinator ruling: option (b)).**
  - **Take path, unchanged.** For a `Take` (and its `TrySubmit`, `EntryVeto` or `Refuse`), every cited payload is put synchronously before the record is fsynced and before `super().submit_order`, and the WP7 budget `CAPTURE_TAKE_TO_SUBMIT_P99_BUDGET_MS` (≤ 150 ms) binds it unchanged.
  - **Refusal path.** For an on-change `Refuse`, `NotExecutable` or `NotDPlus1` record, the event loop computes the refs (canonical bytes and sha256, no I/O, §3.3.1), writes the flush-only record, and hands the payload bodies to `AsyncPayloadWriter.submit(kind, body) -> bool`. That method is non-blocking (`queue.put_nowait` on a queue bounded at `CAPTURE_REFUSAL_PAYLOAD_QUEUE_MAX = 1024`). One daemon thread drains the queue through the same `PayloadStore.put` (fsync, link, directory fsync).
  - **The refusal path never blocks on disk.** Its on-loop work has no `fsync`, no `os.link` and no directory fsync. Its p99, measured in WP7 with the writer thread's `fsync` held blocked, must stay under `CAPTURE_REFUSAL_PATH_P99_BUDGET_MS = 5` (`test_refusal_path_never_blocks_on_stalled_payload_disk`).
  - **A full queue is loud and still non-blocking.** `submit` returns False and increments `refusal_payload_drops`. The record still cites its ref, so the payload is missing: C1 makes that `capture_gap`, and leg B fails the day. The writer writes `DetectorEvent(capture_writer_health, DISAGREE)` with `obs.cause=refusal_payload_queue_full` and the deduplicated CRITICAL `CAPTURE_WRITE_FAILED cause=refusal_payload_queue_full` (§3.3.3 failure dedupe). It does **not** set `health.ok=False`, because the Take path's own synchronous puts still prove the disk.
  - A put error on the thread follows the §3.3.3 failure path, catch-all, and never raises.
  - `on_stop` drains the queue for at most 5 s. Leftovers are counted and logged as `CAPTURE_REFUSAL_PAYLOADS_UNDRAINED n=<k>`; their records then cite missing payloads, and leg B fails loudly.
  - **Concurrency.** A Take's synchronous put and the thread's put of the same content address converge: `os.link` is atomic, the loser takes the `FileExistsError` branch, and it verifies a file that was fsynced before it was linked (`test_async_and_sync_put_of_same_payload_converge`).
  - **Crash.** A payload lost from the queue in a crash is a missing cited payload. C1 makes it `capture_gap`, and leg B fails the day, which is the r5 (b) semantics.
  - Tests: `test_refusal_payload_put_runs_off_event_loop`, `test_refusal_payload_queue_full_is_loud_and_never_blocks`, `test_take_payload_puts_stay_synchronous_before_submit`.
- **Retention.** Payloads are archived with the daily file and never dropped while a C3 lineage cites them. AUT-1 adds the payload root to `scripts/ops/decisions_retention.py` as archive-only (no delete path), pinned by `test_payload_retention_never_deletes`.

#### 3.3.3 Writer (`src/breezy/persistence/autonomy/capture_writer.py`)

- `CaptureIdentity` (frozen): `family_id`, `manifest_sha256`, `artefact_sha256`, `node_boot_id` (kernel `instance_id`), `build_sha`, `registry_seq` (from `ResolvedFamily`, else 0; once AUT-5a's resolver is live the audit fails any 0).
- `drill` is read per record from `RegistryWatchActor.drill_active(now_ns)`; `source ∈ {live, canary}` is fixed at construction (Z14). Canary path: `<decisions_dir>/canary/`.
- **Records (exact C1 Rev 9.2 fields).** Common: `schema`, `decision_id`, `family_id`, `ts_ns` (writer wall clock), `node_boot_id`, `build_sha`, `registry_seq`, `drill`, `source` (`live` | `canary`).
  - `DecisionRecord`: `kind` (`Take` | `Refuse` | `NotExecutable` | `NotDPlus1` | `TrySubmit` | `EntryVeto` | `Exit`), `reason`, `eval_ns`, `eval_seq`, `wall_ns`, `station`, `climate_day`, `rung_id`, `side`, `instrument_id`, `ask_px`, `depth_ref`, `quote_ref`, `p_hat`, `p_hat_raw`, `p_lower`, `p_upper`, `ev_net`, `forecast_input_sha256`, `artefact_sha256`, `manifest_sha256`.
    - **Exactly one** of `depth_ref` and `quote_ref` is non-null for every kind except `Exit`, where both are null. C1 says "every other kind requires `depth_ref` or `quote_ref`" (`test_exactly_one_frame_ref_except_exit`).
    - `eval_seq` is recorded because C1 makes it an id input.
  - `OrderLink`: `client_order_id`, `venue_order_id_sha256`, `instrument_id`, `side`, `qty`, `px`, `time_in_force`. There is **no `intent_id`**. The last five are stored as the exact `str()` forms `intent_fingerprint` consumes (`src/breezy/adapters/polymarket_us/exec/submit_chain.py:244-251`).
  - `LifecycleEvent`: `event` (`SUBMITTED` … `AMBIGUOUS`), `client_order_id`, `trade_id`, `qty`, `px`, `fee`.
  - `PositionMark`: `instrument_id`, `leg`, `net_qty` (signed, venue convention), `mark_px`, `reconciliation_source="node_belief"` (U5). C1 lists `source` both as a common field and in this row. AUT-1 reads it as the one common field (`live` | `canary`), so the writer identity lives in `reconciliation_source` (§11 R-2).
  - `DetectorEvent`: exactly `detector`, `observation_sha256` and `state`. There is **no `detail` field** (r3 used one).
    - The detector's observation is canonical JSON whose sha256 is `observation_sha256`, for example `{cause: "fsync_slow", p99_ms: …}`.
    - Its preimage is logged once through the Nautilus logger as `CAPTURE_OBSERVATION detector=<id> sha256=<h> body=<json>`, with no paths and no venue ids.
    - Below, "`obs.cause=<c>`" names the `cause` key of that observation (`test_detector_event_exact_fields_and_logged_preimage`).
- **Path.** `<decisions_dir>/capture_<family_id>_<UTC date of ts_ns>.jsonl`, with `decisions_dir = catalog_root.parent / "decisions"` (`src/breezy/app/trade.py:774`). The only writer is the node, serialised under the submit-intent flock (G6). Settlements are never written here (§3.9).
- **One write path, short-write recovery (C4, D11).**
  - Each record is `json.dumps(sort_keys=True) + "\n"`, encoded once, written with one `os.write` to an `O_APPEND|O_WRONLY|O_CREAT` 0600 descriptor.
  - **Open-time tail check (r5, H1).** Every open of an existing non-empty file (boot or UTC rollover) first reads its last byte through a separate `O_RDONLY|O_NOFOLLOW` descriptor (`os.pread(fd, 1, size − 1)`). If it is not `b"\n"`, `_needs_newline = True`, so the new boot's first record starts on its own line and the previous boot's torn fragment stays a lone line. A failed tail read is treated as "not `\n`" (the conservative choice) and counted in `tail_check_errors` (`test_new_boot_after_torn_tail_prefixes_newline`).
  - If `self._needs_newline` is set, the buffer is prefixed with `b"\n"` and the flag is cleared only after a full write.
  - A short write (`0 < n < len(buf)`) or an `OSError` after `open` increments `short_writes` or `write_errors` and sets `_needs_newline = True`. When the outcome is unknown this is the conservative choice, because an extra blank line is harmless.
  - The partial fragment stays on disk as a lone non-JSON line. The reader counts it as `partial_line`, which fails the day on leg R4. A non-empty **unterminated last line** of a file (a lone partial tail, for example from a boot that died mid-write with no later boot to prefix a newline) is classified `torn_tail` and also fails the day on R4 (r5, H1). The reader skips an empty line and counts it as `blank_line`, INFO.
  - Tests: `test_short_write_sets_needs_newline_and_next_record_parses`, `test_reader_counts_partial_line_and_blank_line_separately`, `test_reader_classifies_unterminated_last_line_as_torn_tail`.
- **Durability.** `os.fsync` on Take, TrySubmit, EntryVeto, Exit, OrderLink, LifecycleEvent, PositionMark. Flush only on on-change refusals and DetectorEvents.
- **On-change (C1; D9).** `OnChangeFilter.admit(key, kind, reason, eval_ns) -> bool` with `key = (station, climate_day, rung_id, side)`. It is pure. Each insert evicts keys whose `climate_day < utc_date(eval_ns) − 1`, so its output depends only on the input sequence. One filter per boot, **never reset at UTC rollover**, so the audit can replay a boot exactly (§3.10 R2). `Take` and `TrySubmit` always pass (C1).
- **Fsync latency.** A ring of the last 256 durations. A p99 over `CAPTURE_FSYNC_P99_BUDGET_MS` (WP0) gives `DetectorEvent(capture_writer_health, DISAGREE)` with `obs.cause=fsync_slow`, plus a WARNING, and never a veto.
- **Stuck-disk guard, out of process (r6 T3).** The fsyncs that stay on the event loop (the Take path, order-path records, and the 60 s positive control while `health.ok=False`) can still block the loop on a hung filesystem. A blocked fsync never returns, so no in-process detector can report it. The runtime guard is therefore AUT-6's node-liveness detector, an existing ARCH member (Rev 9.2 AUT-6 ownership row: "liveness"). It watches the node log mtime together with tape advance: the log stops while the recorder tape still advances, and AUT-6 alerts through `deliver_with_proof` from outside the node. AUT-1 adds no second detector. It asserts the dependency with `tests/unit/autonomy/test_capture_dependencies.py::test_aut6_node_liveness_detector_covers_log_mtime_and_tape_advance`, which imports AUT-6's detector catalogue and requires a node-liveness entry whose observation includes both inputs. The test is RED until AUT-6 lands, and WP7 does not merge while it is RED (§4 WP7, §5.1).
- **UTC rollover.** The next file opens at the first write after 00:00Z. An open failure is a write failure.
- **Failure path (C4).** On a write error, short write, open failure, payload collision or byte cap:
  1. increment the counter and set `health.ok=False`;
  2. log `CAPTURE_WRITE_FAILED family=<id> kind=<k> cause=<c>` through the Nautilus logger;
  3. `AlertOutbox.offer(CRITICAL)`. **If it returns False (D11)**, increment `alert_drops`, and the step-4 journal row carries `alert_enqueued=false`. AUT-6's outbox writes its own `delivered=false, status_class=outbox_overflow` record (ARCH §4.6);
  4. write the marker `<decisions_dir>/capture_<family_id>_<date>.INCOMPLETE` and append `{family_id, date, cause, first_ns, alert_enqueued}` to `evidence/capture/incomplete/<date>/<ts_ns>_node.json`, write-once per event (one-writer rule);
  5. never raise into a Nautilus handler (L-16).

  The day fails on audit leg R1 even if steps 2–4 all fail (`test_marker_write_failure_still_fails_day`).
- **Failure dedupe (r5, H8).** Steps 2–4 are deduplicated per `cause` per `CAPTURE_FAILURE_DEDUPE_S = 300` s. The first failure of a cause in a window logs, offers the CRITICAL and journals. Later failures of that cause inside the window only increment `suppressed[cause]`. When the window ends (checked on the next write attempt and on the 60 s tick), a non-zero count logs `CAPTURE_WRITE_FAILED_SUPPRESSED family=<id> cause=<c> count=<n> window_s=300` and writes the write-once journal row `evidence/capture/incomplete/<date>/<ts_ns>_node_suppressed.json` (`{family_id, date, cause, window_start_ns, suppressed_count}`). Step 1 (the counter and `health.ok=False`) and the day's `.INCOMPLETE` marker are never deduplicated, so the veto and leg R4 are unchanged (`test_write_failure_critical_deduped_per_cause_per_300s_with_counts_journaled`).
- **Positive control.** At `on_start` and on each 60 s tick while `health.ok=False`, append and fsync `DetectorEvent(capture_writer_health, AGREE)`. Only that success clears `health.ok`.

#### 3.3.4 Reader (`src/breezy/persistence/autonomy/capture_reader.py`)

`read_capture_day(path) -> CaptureDay(records, partial_lines, torn_tail, blank_lines, unknown_schema)` (r5: `torn_tail` is true for a non-empty unterminated last line, H1) reads gzip or plain files through a single read and refuses symlinks. `join_fills_to_decisions(capture_days, fills) -> tuple[JoinedFill | JoinGap, ...]` is pure; AUT-2 consumes it.

#### 3.3.5 `capture_epoch_start` (`src/breezy/persistence/autonomy/capture_epoch.py`; C1 invariants (ii)–(iii))

- **Writer.** `CaptureLifecycleActor.on_start` calls `write_epoch_once(evidence_dir, identity, now_ns)`, which writes `evidence/capture/epoch/<family_id>.json` with `O_CREAT|O_EXCL|O_NOFOLLOW`, 0444: `{schema:"capture_epoch/v1", family_id, epoch_start_ns, node_boot_id, build_sha}`. It writes only on the first boot of a build in which this family is composed with capture, and logs `CAPTURE_EPOCH_START family=<id> epoch_ns=<n>`. If the file already exists, it single-reads and verifies it; an unreadable file gives a CRITICAL and **no veto** (the epoch matters only to the audit).
- **Audit use.**
  - Fills with `ts_event < epoch_start_ns` are `unattributed` (C2 term) and outside invariants (ii)–(iii).
  - UTC days before the epoch day are `PRE_CAPTURE`. The epoch day is `PARTIAL_EPOCH`. Neither ever qualifies for the live proof.
  - **Tamper and rewrite checks (fail-loud):** a missing epoch file while any capture file for the family exists → `ERROR epoch_missing`; `epoch_start_ns` greater than the earliest capture record's `ts_ns` → `ERROR epoch_rewritten`; a retained log of `node_boot_id` lacking the `CAPTURE_EPOCH_START` line → `ERROR epoch_unlogged` (skipped with INFO once that log has aged out of retention).
- This replaces r2's hand-set `CAPTURE_LIVE_FROM_UTC_DAY` literal.

### 3.4 `CaptureAdapter` per composable kind (obligation 1)

**Kinds.** Only `forecast_quantile_ladder` has full plug-ins. `current_rung_hold`, `continuous_rung_hold` and `forecast_ladder` carry `RefusingPlugin` (C6), and `_compose_family` refuses them at boot (C6 runtime rule; ARCH-0). So the CRH kinds, including the armed exit seam reachable only through `src/breezy/strategy/current_rung_hold/continuous_strategy.py:56` → `src/breezy/strategy/current_rung_hold/exit_wiring.py:311`, are **declared unreachable for sending** (D4, §3.5.3). A future kind gets its adapter in the change that admits it.

#### 3.4.1 `FqCaptureAdapter` (C6 signature) and field map

- `decision_record(decision, ctx: CaptureContext) -> DecisionRecord`. Pure: no I/O, no hashing beyond the refs passed in through `ctx`.
- `order_tags(decision_id) -> tuple[str, ...]` returns `(f"{DECISION_ID_TAG_PREFIX}{decision_id}",)`.
- `CaptureContext` (frozen): `eval_ns` (the handler's event `ts_event`), `eval_seq` (from `FrameClock.next_eval_seq`, §3.3.1), `wall_ns` (one `clock.timestamp_ns()` read by the caller), `trigger ∈ {"depth","quote_tick"}`, `depth: OrderBookDepth10 | None`, `quote: QuoteTick | None`, `vector: ForecastQuantileVector | None` (the object `evaluate` used, read once), `ask_px: Decimal`. `trigger` is named so it cannot collide with C1's `source` field (live/canary).

| C1 field | Take | Refuse / NotExecutable / NotDPlus1 | TrySubmit / EntryVeto |
|---|---|---|---|
| `kind`, `reason` | `Take`, `"take"` | class name, `decision.reason` | `TrySubmit`/`EntryVeto`, refusal or `"submitted"` |
| `eval_ns` | the handler's frame `ts_event` (= the line's `now_ns`, `:805-806`) | same | **the Take's** `eval_ns` (same handler event; C1) |
| `eval_seq` | `ctx.eval_seq`, the ordinal per `(instrument_id, ts_event)` (§3.3.1): 0 for a quote trigger, 1 for the same frame's depth trigger | `ctx.eval_seq` | the Take's |
| `wall_ns` | `ctx.wall_ns` | same | the single `clock.timestamp_ns()` that `_emit_decision_outcome` also puts in its line as `now_ns` (`:701`) |
| `decision_id` | computed from this record | computed from this record | **the Take's id**. It recomputes from this record's own fields, which equal the Take's. |
| `ask_px` | `str(limit_price)` | `str(ask_price)` | the Take's |
| `depth_ref` / `quote_ref` | depth trigger: `depth_ref` of this frame, `quote_ref` null. Quote trigger: `quote_ref` of this quote, `depth_ref` null (§3.4.2). | the same rule for the triggering frame | the Take's |
| `p_hat`, `p_lower`, `p_upper`, `ev_net` | from `Take` | null | null |
| `p_hat_raw` | `= p_hat` while the bound calibration has `recalibration == "none"` (G11); the adapter asserts that condition, and a non-`none` artefact raises at construction (`test_p_hat_raw_equals_p_hat_only_while_recalibration_none`) | null | null |
| `forecast_input_sha256` | the vector's | the vector's, or null when it is None | the Take's |

When AUT-3 widens G11, the same change must give `Take` a raw field. The construction assert makes that unavoidable.

#### 3.4.2 Quote-triggered decisions (D2; C1 U8, adopted)

The frame order is quote then depth (`src/breezy/adapters/polymarket_us/data.py:1590`, `:1599`), and `evaluate` latches before capture runs (`src/breezy/strategy/forecast_quantile_ladder/decision.py:357`). So a quote-triggered decision cannot cite its own frame's Depth10, and refusing it after the fact would burn the rung-day latch. ARCH Rev 9.2 resolves this (P1-13 → U8).

- **The record.** For `trigger="quote_tick"` the adapter cites a `quote` payload `{ask, bid, ts_event}` (§3.3.1) as `quote_ref` and sets `depth_ref` to null.
  - This applies to the Take and to any on-change refusal record that the quote triggered.
  - The payload is put only with the citing record (write-on-change).
- **Completeness.** A quote-triggered record with `quote_ref` and null `depth_ref` is complete; it is **not** `capture_gap`.
- **No fallback.** FQ's trigger set is unchanged. r3's fallback (`FQ_SKIP reason=capture_quote_unpreimaged`) is deleted.
- **Audit leg B, tape corroboration.** Independently of the node, the audit looks for a recorder-tape Depth10 with the record's `instrument_id` and the payload's `ts_event`, whose top equals the payload's `bid`/`ask`.
  - WP0 item 9 measures how often the tape has such a row, and its evidence file records the rate.
  - At ≥ 99.9%, a miss fails leg B (`quote_tape_mismatch`).
  - Below 99.9%, a miss is reported as INFO corroboration, and leg B rests on the payload re-hash (`test_leg_b_quote_tape_check_strictness_follows_wp0_rate`).
- Tests: `test_quote_triggered_take_stores_quote_payload_and_ref`, `test_quote_triggered_record_has_null_depth_ref`, `test_quote_take_without_prior_depth_is_not_capture_gap`, `test_leg_b_quote_take_matches_tape_depth_same_ts_event`.

#### 3.4.3 Call sites in `forecast_quantile_ladder/strategy.py` (AUT-1b; D5 plumbing)

| # | Site | Change |
|---|---|---|
| CS-4 | `on_order_book_depth` (`:713-729`), `on_quote_tick` (`:731-738`) | First stamp `self._frame_clock.stamp(instrument_id, self.clock.timestamp_ns())`. (r5, H11: r4's `_last_depth` map is deleted; nothing read it.) Then call `_safe_evaluate(..., source=…, depth=depth \| None, quote=tick \| None)`. |
| CS-0 | `_safe_evaluate` (`:740-757`) | Pass `trigger=source`, `depth` and `quote` into `_evaluate_instrument_update` (today `source` is dropped at `:753`). |
| CS-1 | `_evaluate_instrument_update` (`:759-819`) → new `_evaluate_with_capture(..., trigger, depth, quote) -> tuple[Decision, str \| None]` | Reads the vector once (today's `:529-531`), calls `evaluate`, emits the shadow line as today, then `self._capture_decision(decision, ctx)`, with `ctx.eval_ns` = the handler's `ts_event`, `ctx.eval_seq = self._frame_clock.next_eval_seq(instrument_id, ts_event)`, taken for every evaluation before the on-change check (§3.3.1, r5 H2) and `ctx.wall_ns` = one `clock.timestamp_ns()`. **Order of work (C6):** (1) `OnChangeFilter.admit` (a dict lookup); (2) only when it is True, hash the payloads, compute `decision_id` and write the record. A Take puts its payloads synchronously first. A refusal hands them to `AsyncPayloadWriter` (§3.3.2, r6 T3). It returns `(decision, decision_id)`. `evaluate_snapshot` (public, signature unchanged) becomes `return self._evaluate_with_capture(..., capture_ctx=None)[0]`. **Production never takes that branch** (`test_production_trigger_paths_pass_capture_ctx`, both triggers). |
| CS-2 | `_maybe_submit(take, *, limit_price, decision_id: str \| None)` (`:646-688`), `_emit_decision_outcome(take, refusal, *, decision_id, now_ns)` (`:690-709`) | `decision_id is None` (capture failed for this Take) gives refusal `capture_gap` before `try_submit`. `_emit_decision_outcome` takes `now_ns = self.clock.timestamp_ns()` **once**, and puts it in the line and in the record's `wall_ns`; the record's `eval_ns` and `eval_seq` are the Take's. It writes `TrySubmit` (always, fsynced) or, for a refusal in the closed `VetoReason` set, `EntryVeto` (**the `EntryVeto` writer**, on-change per key; any other refusal string is written as `TrySubmit` with that reason). The instrument-vanished path (`:677-679`) writes `DecisionRecord(kind="Refuse", reason="instrument_vanished_after_trysubmit")` with the Take's id (D6). |
| CS-3 | `order_factory.limit(...)` (`:680-688`) | `tags=list(self._capture_adapter.order_tags(decision_id))`; then `self.submit_order(order)`, intercepted by the guard. |
| CS-5 | `shadow_only=True` (`:659-665`) | CS-1 already captured the Take; no order. |
| CS-6 | `self.submit_order_list` | Not called by FQ (0 sites). Guarded anyway (§3.5). |

**Pinned timestamps (D5; C1 U9 and R9.2-Z9, adopted).** Every record's `eval_ns` is the handler's frame `ts_event`. A TrySubmit, or a post-Take `EntryVeto` or `Refuse`, copies the Take's `eval_ns` and `eval_seq` and carries its own `wall_ns`, which equals the `now_ns` in its shadow line (`:701`): `test_eval_ns_is_handler_ts_event_and_trysubmit_wall_ns_matches_line_now_ns`. Audit leg R1 therefore matches Take and refusal lines on `eval_ns`, and TrySubmit lines on `wall_ns` (§3.10).

### 3.5 Guard (`CaptureGuardedStrategy`, library in 1a, FQ's base class in 1b)

#### 3.5.1 Construction (C8)

`__init__(self, config, *, capture_writer: CaptureWriter, alert_outbox: AlertOutbox, …)`: both are keyword-only, non-Optional, and type-checked (`TypeError`), inside `_compose_forecast_quantile_ladder` before `node.run()`. The boot fails closed.

Two hooks serve the guard's records. `_capture_key_of(instrument_id) -> tuple[station, climate_day, rung_id, side] | None` is implemented by FQ from `self._instrument_context` (`src/breezy/strategy/forecast_quantile_ladder/strategy.py:779`); the base returns None. The writer keeps a bounded map `decision_id → DecisionRecord` of this boot's Takes (O(takes per day)).

#### 3.5.2 `submit_order(order, position_id=None, client_id=None, params=None)`

1. **Exit (C1 P1-8).** If any tag starts with `EXIT_RULE_TAG_PREFIX` and all four exit tags are present, write a `DecisionRecord(kind="Exit")` and an `OrderLink`, both fsynced, then call `super()`.
   - The `Exit` record: `decision_id=compute_exit_decision_id(<the four tag values>)`; `depth_ref` and `quote_ref` null; `eval_ns` = the order's `ts_init` (the guard sees no triggering event, and the exit id does not use `eval_ns`); `eval_seq` = 0; `wall_ns` = `clock.timestamp_ns()`; `ask_px` = the order price; the key fields from `_capture_key_of` (null when unknown); null probabilities.
   - If a tag is missing or a write fails, call `super()` anyway, write `DetectorEvent(capture_writer_health, DISAGREE)` with `obs.cause=exit_capture_gap`, and raise a CRITICAL. A legitimate exit raises no CRITICAL.
   - FQ has no exit (G17) and the CRH exit seam is unreachable (§3.5.3), so this branch is defensive today. ARCH `test_every_exit_fill_joins` pins it.
2. **Untagged SELL (D12).** `order.side == SELL` with no exit tag: write `OrderLink(decision_id=compute_orphan_decision_id(...))` and `DetectorEvent(capture_writer_health, DISAGREE)` with `obs.cause=untagged_sell`, raise a CRITICAL, then call `super()`. SELLs reduce risk (G24: every entry is a BUY). The fill then fails audit leg L as `untagged_order`, so the defect cannot pass silently.
3. **BUY tag check (C1 P1-9; `capture_untagged` is a C5 `VetoReason`).** A BUY needs exactly one `breezy:decision_id=` tag of 32 lowercase hex characters.
   - Otherwise refuse with `capture_untagged`: no `super()` (so the order never reaches the cache), log `CAPTURE_REFUSED reason=capture_untagged client_order_id=<id>`, and raise a CRITICAL.
   - **The record, when a Take is known.** If a tag parses to the id of a Take written this boot, write `EntryVeto` with that id, the Take's key fields, `eval_ns`, `eval_seq` and frame ref, and its own `wall_ns`.
   - **The record, when no Take is known.** There is then no decision context from which C1 can form a valid id or frame ref. The guard writes `DetectorEvent(capture_writer_health, DISAGREE)` with `obs.cause=untagged_buy` instead of inventing an id (§11 R-4).
   - Tests: `test_untagged_buy_refused_capture_untagged`, `test_untagged_buy_without_known_take_writes_detector_event_not_decision_record`.
4. `health.ok` False → refuse with `capture_gap` (same logging and record).
5. `write_order_link(OrderLink(...G33 str() forms...), fsync=True)` returns False → refuse with `capture_gap`.
6. `super().submit_order(...)`.

`submit_order_list(order_list, …)` runs steps 1–5 for every order first. If any BUY fails, the **whole list** is refused: a `DetectorEvent` with `obs.cause=capture_order_list_refused` is written, and each BUY gets its step-3, 4 or 5 record; otherwise `super().submit_order_list(...)`. Tests: `test_submit_order_list_with_untagged_buy_refuses_whole_list`, `test_submit_order_list_of_tagged_orders_links_each`.

#### 3.5.3 Every send path is guarded or unreachable (D4)

`tests/unit/autonomy/test_capture_submit_sites.py::test_every_strategy_submit_site_is_guarded_or_unreachable` (AST). It finds every `Call` whose attribute is `submit_order` or `submit_order_list` under `src/breezy/strategy/**`. A site passes only if:
- **(a)** its enclosing class subclasses `CaptureGuardedStrategy` (static base walk), or
- **(b)** its module is in the literal table `_UNREACHABLE_SEND_SITES = {module: reason}`, and the reason is proven by a companion test:

  | Module | Reason | Companion test |
  |---|---|---|
  | `src/breezy/strategy/harness_probe.py`, `src/breezy/strategy/current_rung_hold/backtest_only.py` | not imported transitively by `breezy.app.trade` | `test_unreachable_modules_not_in_trade_import_closure` (import graph walk) |
  | `src/breezy/strategy/current_rung_hold/strategy.py`, `src/breezy/strategy/current_rung_hold/continuous_strategy.py`, `src/breezy/strategy/current_rung_hold/exit_wiring.py` | kind is `RefusingPlugin`; `_compose_family` refuses it | `test_refusing_plugin_kinds_cannot_compose` (one case per kind, through `_compose_family`) |

Any new site fails the test until it is classified. A CRH kind admitted later must re-base on the guard in the same change (C6 rule).

**Indirect send helpers (r5, H11).** Nautilus `Strategy.close_position`, `close_all_positions`, `market_exit` and `_send_risk_command` build or route orders inside the Cython base, where dispatch to a Python `submit_order` override is not proven. `tests/unit/autonomy/test_capture_submit_sites.py::test_no_indirect_send_helper_under_strategy` (AST) fails on any call to these four names under `src/breezy/strategy/**`. There are 0 such calls at `4b8347a6` (checked with `/usr/bin/grep` over `src/breezy/strategy`). WP0's `::test_close_position_dispatch_through_python_submit_order_override_is_recorded` records whether they dispatch through the override; the ban may be replaced by that proof only in a reviewed commit that adds a per-helper dispatch test.

**Hot path (C6, W9).** No network call; CRITICAL is an outbox enqueue. `test_guarded_submit_latency_independent_of_webhook` blocks the webhook for 30 s.

### 3.6 Lifecycle, marks and epoch (`CaptureLifecycleActor`, AUT-1b)

- `on_start`: `write_epoch_once` (§3.3.5); `msgbus.subscribe("events.order.*")`, `("events.position.*")` (WP0); `clock.set_timer("aut1-capture-health", 60 s)`. **No `subscribe_*` command and no data-topic subscription** (`test_capture_actor_issues_no_venue_subscription`, L-45). r2's passive data subscription is removed (D14).
- `_on_order_event` (catch-all, L-16):
  - `OrderAccepted` → a second `OrderLink` carrying `venue_order_id_sha256`.
  - Every event → `LifecycleEvent` with string decimals.
  - `decision_id` comes from the order's tags: the entry tag, the exit id or the orphan id.
- `_on_position_event` → `PositionMark(reconciliation_source="node_belief")` (U5), with the venue sign (L-44). The common `source` is `live`, or `canary` for the canary writer.
- 60 s timer: positive control, detector evaluation, DetectorEvents on transitions. The body is catch-all, and every detector also checks its own age at call time.
- The node touches no exec-store key (`test_capture_modules_never_import_exec_store`).

### 3.7 Node-local observations (obligation 4; AUT-1b)

All are C6 `Detector(kind=NODE_LOCAL)` with action `ENTRY_VETO`, called by AUT-5a's `entry_veto(instrument_id)` slot, listed in AUT-6's catalogue (#1–#3). Each auto-clears; when it refuses through the slot, CS-2 writes the `EntryVeto` record (r5: CS-2 is the sole writer of slot-refusal `EntryVeto`s, and the detector writes none, so R1 sees exactly one record per admitted veto line); each writes a `DetectorEvent` per transition, and touches no registry row or budget. Each starts in veto until its first good observation, and vetoes at call time when its last evaluation is older than `WATCH_TICK_STALE_S` (180 s).

**Trigger paths that reach the veto (D14).** `entry_veto(i)` is called only from `try_submit` ← `_maybe_submit` (`:666`) ← `_evaluate_instrument_update` (`:819`) ← `_safe_evaluate` (`:753`) ← `on_order_book_depth` (`:724`) or `on_quote_tick` (`:733`). Every veto query is therefore made **while handling a fresh frame for the same instrument**. Pinned by `test_try_submit_reachable_only_from_frame_handlers` (AST call graph inside the class; it fails if a timer or other caller of `_maybe_submit` appears).

#### 3.7.1 `feed_stale`

| Detector | Source | Period | Trigger | Clear |
|---|---|---|---|---|
| `md_feed_freshness` | `FrameClock` stamped by CS-4 **before** evaluation | call time; 60 s tick for the observation | **Per instrument, veto:** `now − frame_clock[i] > MD_SILENCE_S`, `MD_SILENCE_S = max(900, ws_idle_timeout_secs + 300)` inside `ACTIVE_HOURS_UTC`, × `QUIET_HOURS_MULTIPLIER` outside (both from WP0, §3.8.2). On the two frame paths this cannot fire, because CS-4 has just stamped `i` (`test_frame_triggered_evaluation_never_vetoes_feed_stale`). It stays as defence for any future non-frame trigger. **Venue-wide: observation only.** A silent fraction > `MD_SILENT_FRACTION_MAX = 0.5` (quiet-hours horizon applied) writes `DetectorEvent(md_feed_freshness, DISAGREE)` with `obs.cause=venue_silent` and a WARNING `CAPTURE_VENUE_SILENT` through the outbox (`deliver_with_proof`; ARCH §4.6 V3; alert row in §3.13, r5 H11), and **no veto** (§R3 D14 explains the reversal of r2's venue-wide veto). | next frame on `i`; the observation clears at or below the limit |
| `nbp_feed_freshness` | `ForecastQuantileState.value_at(now)` per traded station; `latest_available_cycle_ns(now)` | 60 s tick, call time | `missed` = configured cycles (`(1, 13, 19)`, `src/breezy/ingest/nbm_quantile_actor.py:122`) after the newest complete cycle whose `cycle_ns + 3 h` (`:137`) has passed. `missed ≥ 1` → CRITICAL `NBP_CYCLE_MISSED`, no veto. `missed ≥ 2`, or no complete vector for a subscribed station → veto. Bulletin drift counts as missed. | a newer complete cycle |

#### 3.7.2 NBP in-node hang reset (AUT-1a, ingest)

- `_submit` retains the `Future` from `run_coroutine_threadsafe` (`:348`).
- In `on_cycle_timer`, a future not done after `NBP_POLL_HANG_S` (≥ 2 × the `BulletinFetcher` timeout pinned in WP0; default 600) is cancelled; then `counters["poll_hang_reset"] += 1`, the log line `NBM_NBP_POLL_RESET cycle_ns=<n>`, and a fresh `poll_once()`.
- A reset followed by `FQ_VECTOR_COMPLETE` for that cycle writes the write-once heal record `evidence/capture/heal/<date>/<ts_ns>_node_nbm_quantile_actor.json` (`{unit:"in-node:nbm_quantile_actor", cause:"poll_hang", detected_ns, action:"poll_reset", healed_ns, injected:false, decided_by:"nbm_quantile_actor", alert, observation_sha256}`) and then offers the INFO alert `CAPTURE_HEALED_<observation_sha256>` to the outbox (§3.14, r5 H6).
- **Outbox wiring (r6 T2).** The outbox reaches the actor as `heal_alert_offer`, which the WP8 composition hunk passes in (§3.1), and WP4 merges with WP8 (§4 WP4). `alert` is `"offered"` when the callable is present. If it is absent at heal time (a defect: WP8 always wires it), the actor logs CRITICAL `NBM_NBP_HEAL_ALERT_UNDELIVERABLE observation_sha256=<h>` through the Nautilus logger and writes the record with `alert="undeliverable"`. If `offer` returns False, it logs the same line, but the record is already written. Either way the record lacks a matching delivered record, so the watch re-sends it (§3.14, r6 T1). Test `test_nbp_heal_with_absent_outbox_logs_critical_and_writes_undeliverable_heal_record`.
- This is an in-process retry, not the ARCH restart site, so it does not wait for the policy ruling.

#### 3.7.3 `capture_gap`

| Source | Period | Trigger | Clear |
|---|---|---|---|
| `CaptureWriter.health` (`write_errors`, `short_writes`, `capped_rows`, `payload_collisions`, `last_fsync_ok_ns`) | every write; 60 s tick; call time | any failed durable write since the last positive control | the next fsynced `DetectorEvent(AGREE)`; a cap holds until the next UTC-day file |

#### 3.7.4 `recorder_stale`

| Source | Period | Trigger | Clear |
|---|---|---|---|
| `health/capture_watch-polymarket_us.json` (`capture_watch/v1`), single read (`O_NOFOLLOW`, 4 KiB, exact set) | 60 s | `recorder.state ∈ {UNHEALED, INACTIVE}`; `written_at_ns` older than `WATCH_FILE_MAX_AGE_S = 900`; or missing or unparseable. **Launch-window allowance (r4):** the watch does not fire in [16:30Z, 17:10Z) (§3.11), so a file written at or after 16:25Z counts as fresh until 17:20Z. Outside that, the 900 s rule applies (`test_recorder_stale_tolerates_launch_window_gap_until_1720`). `AWAITING_HEARTBEAT` does **not** veto (§3.8.2). | a verified read with `state ∈ {OK, HEALING, AWAITING_HEARTBEAT}` and a fresh `written_at_ns` |

### 3.8 Recorder and feed stall observations (obligation 5; AUT-1a)

#### 3.8.1 Recorder heartbeat (opt-in, in the recorder process)

- `PolymarketUSDataClientConfig.heartbeat_path: str | None = None`. Only `build_quote_tape_node_config` (`src/breezy/runtime/node_config.py:485-622`) sets it, to `/home/jon/.local/share/breezy/health/recorder-polymarket_us.json` (`test_trade_node_config_has_no_heartbeat_path`).
- `_write_heartbeat(phase)` writes `recorder_heartbeat/v1` atomically, 0600, at most every 30 s, in O(1): `{schema, instance_id, pid, phase ∈ {DISCOVERING, STREAMING, SAFE_MODE}, written_at_ns, discovered_slugs, subscribed, quotes_published, depths_published, trades_published, tape_gaps, is_tape_gap_open, safe_mode}`.
- It is called from the empty-discovery retry (`src/breezy/adapters/polymarket_us/data.py:1082-1099`) and from `sample_feed_health` (`:1960-2003`). A failure is counted and logged once, never raised.

#### 3.8.2 `breezy-capture-watch` (oneshot, every 5 min outside [16:30Z, 17:10Z), own lock): classification

`capture_watch.classify_recorder(hb, unit, disk, now, prev) -> RecorderState`. Every threshold is a literal in `src/breezy/runtime/capture_watch.py`, and each WP0-derived one names its evidence file.

| State | Rule |
|---|---|
| `AWAITING_HEARTBEAT` (D3) | No heartbeat file has ever been read **and** the recorder's `ActiveEnterTimestamp` (`systemctl --user show -p ActiveEnterTimestampMonotonic`, read-only argv) is not later than the watch's first-run `activated_at_ns` + 600 s grace. In other words, the recorder still runs pre-heartbeat code. INFO only. **Never a restart request, never a veto.** After 26 h in this state, CRITICAL `RECORDER_HEARTBEAT_NEVER_SEEN` through `deliver_with_proof`, repeated at most hourly, and still no restart. It leaves the state at the first heartbeat, or once a recorder started after `activated_at_ns` has had 600 s to write one; from then on the normal rules apply. **Bytes-only stale check (r5, H11).** While AWAITING, the watch still sums the byte total (rules below) of the most recently modified `<catalog_root>/live/<instance>/` directory. If the unit is active and that total is unchanged across probes spanning `STREAM_SILENCE_S(h)`, it raises CRITICAL `RECORDER_BYTES_STALE_AWAITING_HEARTBEAT` through `deliver_with_proof`, at most hourly (delivery-keyed, §3.13), with **no restart request and no veto**: without a heartbeat the watch cannot separate a hang from a quiet listing. Tests `test_awaiting_heartbeat_is_info_only_never_restart_or_veto`, `test_awaiting_heartbeat_over_26h_raises_critical_without_restart`, `test_first_rotate_after_activation_ends_awaiting_state`, `test_awaiting_heartbeat_flat_bytes_raises_critical_without_restart`. |
| `INACTIVE` | Unit not active (`is-active`, read-only). Never requested for restart. CRITICAL. |
| `HUNG` | Unit active, outside AWAITING, and the heartbeat is missing or older than `HB_STALE_S = 180`; or `DISCOVERING` > `empty_discovery_retry_secs + 300`; or `SAFE_MODE` > 300 s. Not hour-gated. |
| `STALLED` | `STREAMING`, `discovered_slugs > 0`, counters and the on-disk byte total both unchanged across probes spanning `STREAM_SILENCE_S(h)`. `STREAM_SILENCE_S(h) = max(900, ws_idle_timeout_secs + 300)` for `h ∈ ACTIVE_HOURS_UTC`, else × `QUIET_HOURS_MULTIPLIER`. **Both are derived in WP0 (D8)** from 14 tape days of 5-min frame bins: `ACTIVE_HOURS_UTC` = hours in which ≥ 99% of bins have ≥ 1 frame; `QUIET_HOURS_MULTIPLIER = ceil(1.5 × p99.9(quiet-hour silence run) / STREAM_SILENCE_S_active)`, minimum 1. |
| `WRITER_STALL` (D8) | `STREAMING` and, for probes `j < m < k` with `t_k − t_j ≥ WRITER_STALL_S` and `t_k − t_m ≥ FLUSH_MARGIN_S` (= 3 × the 10 s flush): `events(m) − events(j) ≥ 1` **and** `bytes(k) == bytes(j)`. A single event that should have flushed but did not is a stall, so the r2 floor of 50 (the 1–49 gap) is gone. `WRITER_STALL_S = max(120, 6 × p99.9)` of the WP0-measured inter-growth interval **conditioned on ≥ 1 published event**. Not hour-gated, because the precondition proves data flowed. |
| `OK` | Otherwise. A legitimate empty listing is OK. |
| `HEALING` / `UNHEALED` | §3.8.3. |

- **Byte total.** The sum of `st_size` over regular non-empty files under `<catalog_root>/live/<hb.instance_id>/` (`lstat`, symlinks skipped, epoch `stat`). The 00:00Z file rotation stays monotonic.
- **Rotation grace.** An `instance_id` younger than 600 s never produces a restart request.
- **NWS ingest.** `HUNG` if `breezy-nws-ingest.service` is active and the newest `snapshot_at_ns` in `health-polymarket_us.<CITY>.json` is older than 900 s. This raises a CRITICAL and a `HEALTH` FAIL, and **no restart request** (r4). ARCH §4.5 permits `try-restart` of an *active* unit only for a recorder classified HUNG (U11), so an active-but-stale ingest is not restarted (§11 R-9). `gate_state != OPEN` for more than 2 h → CRITICAL only.

#### 3.8.3 Self-heal through AUT-6 (ARCH §4.6: AUT-6 is the only restart caller)

1. **Restart request (recorder only).** Recorder `HUNG`, `STALLED` or `WRITER_STALL` on two consecutive probes at least 5 min apart sets a `restart_request` in `capture_watch/v1`.
   - Its fields: `{unit, classification: "HUNG", cause ∈ {heartbeat_stale, discovering_overrun, safe_mode_overrun, stream_stalled, writer_stall}, requested_at_ns, observation_sha256}`.
   - All five causes are conditions of an **active** unit, which ARCH §4.5 lets AUT-6 `try-restart` under the HUNG classification (U11). AUT-1's finer states are causes, not new classes (§11 R-5; `test_restart_request_classification_is_hung_with_substate_cause`).
   - The state file is the watch's own and is rewritten atomically (one writer). AUT-1 runs **no** restart (`test_watch_never_calls_systemctl_restart`).
2. **AUT-6 consumes it** in `breezy-autonomy-health` (`*:01/10`). AUT-1 asks AUT-6 (§5.1) for a detector `aut1.recorder_stall`: `VERDICT HEALTH`, action class SELF_HEAL, cause class INFRA. The executor, as ARCH §4.5 fixes it (P1-10, P1-12, V8, W11):
   - reads `restart_request` through `capture_watch_state.load()`;
   - counts the unit's write-once records in `evidence/selfheal/<trading_date>/` against `SELF_HEAL_MAX_RESTARTS_PER_UNIT_PER_DAY` (≤ 3 per trading day [16:45Z, next 16:45Z));
   - writes its own record before restarting;
   - runs the argv `["systemctl","--user","try-restart","--no-block",unit]` with a `subprocess` timeout ≤ 30 s.

   Inside [16:30Z, 17:10Z) the restart is deferred to 17:10Z and journaled (§5.2, V7). Until AUT-5b files the policy ruling, the health unit is alert-only (ARCH §4.6), so a confirmed stall raises a CRITICAL and no restart.
3. **Heal confirmation (AUT-1).** After a selfheal record for the unit appears with `ts_ns > requested_at_ns`, the watch enters `HEALING`. It reads the current and the previous `evidence/selfheal/<trading_date>/` directories, so a request near 16:45Z is not missed (`test_heal_confirmation_reads_current_and_previous_trading_date_dirs`). It confirms within 2 probes: a new `instance_id`, `STREAMING` (or legitimate `DISCOVERING`), counters rising **and** bytes growing. On success it writes the write-once `evidence/capture/heal/<date>/<ts_ns>_watch_<unit>.json` (`{unit, cause, requested_at_ns, selfheal_record, healed_ns, injected, decided_by:"capture_watch", observation_sha256}`), a C4 `HEALTH recorder_self_heal` PASS, and the INFO alert `CAPTURE_HEALED_<observation_sha256>` through `deliver_with_proof` (§3.14, r5 H6). If that delivery fails, the next probe re-sends it (§3.14, r6 T1). It clears `restart_request`.
4. **Failure.** The watch makes a further request while the trading-day count is below the ceiling. It goes `UNHEALED` in either case below; that means a CRITICAL, a `HEALTH` FAIL, and a node veto with `recorder_stale`.
   - AUT-6 reports the cap exhausted.
   - No selfheal record appears within `SELFHEAL_RESPONSE_TIMEOUT_S = 1800` s, **counted outside [16:30Z, 17:10Z)** by `seconds_outside_launch_window`, because AUT-6 defers restarts there (`test_selfheal_response_timeout_excludes_launch_window`).
5. **Never for an inactive unit.** The watch never requests a restart for an `INACTIVE` unit; `try-restart` is a no-op on a stopped unit anyway (G40).

- **Units AUT-6 may restart (obligation):** `breezy-quote-tape.service` (active and HUNG, on AUT-1's request, or failed) and `breezy-nws-ingest.service` (failed only, through AUT-6's own unit-health path; never on an AUT-1 request). Neither is the supervisor, the trade node or the engine. They are added to `SELF_HEAL_RESTARTABLE_UNITS` in `src/breezy/persistence/autonomy/pins.py` in one reviewed commit.
- **Watchdog stamp.** The watch raises CRITICAL `CAPTURE_WATCHDOG_STALE` when `health/capture_watchdog.json` is older than `WATCHDOG_STAMP_MAX_AGE_S = 4500` (75 min). The watchdog's longest gap is 60 min, across the launch-window blackout (§3.11), so r3's 45 min would false-alarm daily at 17:10Z (`test_watchdog_stamp_threshold_covers_launch_window_gap`).
- **SIGSTOP and clean stop.** WP0 pins that systemd 259 sends SIGCONT after SIGTERM to a stopped main process. The fallback is a reviewed `ExecStop=/bin/kill -CONT $MAINPID`; the bot never edits unit files.

#### 3.8.4 Activation without a hand restart

The recorder loads the heartbeat at the next daily 09:00Z rotate (`try-restart`). The watch starts in `AWAITING_HEARTBEAT` (D3), so its activation never causes a restart or a veto.

#### 3.8.5 `breezy-capture-watchdog` (`:07/:22/:37/:52` outside [16:30Z, 17:10Z), own lock)

| Check | Fails when |
|---|---|
| Watch freshness | `capture_watch-polymarket_us.json` missing, unparseable or older than 900 s; or `breezy-capture-watch.timer` not `active` |
| Audit dead-man (C2) | no `capture_join_completeness` verdict for the family with `produced_at_ns` in the last 26 h |
| Missing audit file | a UTC day D whose audit was due (now ≥ D+1 14:30Z) within the last 8 days has no `evidence/capture/audit/<family>/<D>.json`. A `NO_INPUT` day writes one too. |
| Stuck INCONCLUSIVE (D15) | any day still `INCONCLUSIVE` 8 days after it ended → CRITICAL `CAPTURE_AUDIT_STUCK_INCONCLUSIVE` |
| Settlement | no `settlement_<D>.jsonl` record for a traded station-day older than 48 h |
| Live-proof roll-up | older than 26 h |

It writes `health/capture_watchdog.json` after every run. The watch and watchdog check each other.

**Check isolation, delivery-keyed rate limit, exit status (r5, H7).**
- Each row above runs in its own `try` block. A check that raises is recorded as `{check, error_type}` (no message, no path), raises CRITICAL `CAPTURE_WATCHDOG_CHECK_ERROR check=<id>` through `deliver_with_proof`, and the run still evaluates every other check.
- The stamp (`capture_watchdog/v1`) then carries `status="degraded"` and the failed check ids; otherwise `status="ok"`. The watch counts a degraded stamp as fresh for `CAPTURE_WATCHDOG_STALE` and raises WARNING `CAPTURE_WATCHDOG_DEGRADED` through `deliver_with_proof`.
- **Rate limit keyed on delivery.** A repeat of an alert `event` is suppressed for the hour only when the newest delivery record for that `event` within the last 3600 s (today's and the previous `evidence/alerts/<date>/` directory) has `delivered=true`. A `delivered=false` record never suppresses the retry.
- **Exit status.** If any `deliver_with_proof` call in the run returns a failed proof, the CLI still writes its stamp, then exits 1, so `OnFailure=` fires. r6 (L2) extends the same rule to the watch, settlement, drill and drill-guard CLIs (§3.13).
- Tests `test_raising_check_is_isolated_and_raises_check_error_with_degraded_stamp`, `test_watchdog_rate_limit_keyed_on_delivered_true`, `test_watchdog_failed_delivery_exits_nonzero`, `test_watch_treats_degraded_stamp_as_fresh_and_warns`. If both are dead, AUT-6's off-host canary absence rule pages.

### 3.9 Settlement writer (obligation; C1 P1-6)

- `breezy-capture-settlement.service`, a oneshot at 13:35Z, **without** `Persistent=true`, because a catch-up firing after downtime could land in [16:30Z, 17:10Z). A missed day is covered by the next run, which scans the trailing 7 climate days. It holds its own lock `health/capture-settlement.lock`, so it is not a study.
- For every `(station, climate_day)` with `climate_day ∈ [today−7, today−1]` in the venue's station set, it calls `read_climate_day_including_corrections` (`src/breezy/persistence/catalog.py:637`). When the CLI exists, it appends `SettlementRecord{station, climate_day, settlement_tmax_f, basis, raw_sha256}` to `decisions/settlement_<climate_day>.jsonl`, but only if `(station, climate_day, raw_sha256)` is not already there (the file is read once).
- A correction appends a new record; readers take the greatest `ts_ns`. `basis` comes from the venue (`NWS_CLI` for Polymarket.us), so a Kalshi family can carry its own basis (memory: Kalshi settles on The Weather Company).
- It is the only writer of `settlement_*` (`test_autonomy_files_have_one_writer` row). The node never writes it.
- **Failure (r6, L2).** A `read_climate_day_including_corrections` error or a write error for any station-day raises CRITICAL `CAPTURE_SETTLEMENT_ERROR station=<s> climate_day=<d> cause=<error_type>` through `deliver_with_proof`. The run goes on to the other station-days, then exits 1. A failed delivery also exits 1 (§3.13). The watchdog's 48 h settlement check stays the backstop.
- Tests: `test_settlement_appends_once_per_raw_sha`, `test_settlement_correction_appends_new_record`, `test_settlement_basis_is_venue_owned`, `test_settlement_writer_is_sole_writer`.

### 3.10 Daily completeness audit (obligation 6; AUT-1a)

- `breezy-capture-audit.service` runs `/home/jon/breezy/.venv/bin/python3 -m breezy.analysis.capture_audit_cli --venue polymarket_us --day <D>` at 13:50Z for D = yesterday, without `Persistent=true` (the §3.9 reason).
  - It also audits every day in the last 8 that has no audit file, as a backfill after downtime (`test_audit_backfills_days_without_audit_file_within_8`).
  - It re-audits every day in the last 8 still `INCONCLUSIVE`; one still INCONCLUSIVE after 8 days becomes a CRITICAL (D15, §3.8.5).
- **Families by construction:** the union of capture-file family ids, epoch files, durable-fill attributions and exec-store order ids. An orphan is a FAIL.
- **Inputs (read-only):**
  - capture files for D−1..D+1, for per-boot replay;
  - `settlement_*.jsonl`; payloads; epoch files;
  - the exec store through `mode=ro` (`SELECT key, value FROM state`);
  - node logs overlapping D, each identified by its `TradingNode: instance_id:` line;
  - funnel files;
  - the ingest journal (literal argv `journalctl --user -u breezy-quote-tape-ingest -o cat --since … --until …`, 30 s timeout);
  - the recorder catalog.
- **Fail-loud (C2; D15).** Any of the following makes the day `ERROR`, never `NO_INPUT`:
  - an exec-store open, `sqlite3.Error` or decode failure;
  - an unknown key prefix (key-schema drift);
  - an unreadable node log for a boot overlapping D;
  - a boot in the boot census (below) with no readable log: **`ERROR node_log_missing`** (r5, H5);
  - a node log whose `TradingNode: instance_id:` line, or any line carrying a parsed marker token (`SHADOW_DECISION`, `OrderSubmitted`, `OrderDenied`, `OrderFilled`, `NBM_NBP_PUBLISHED`, `FQ_VECTOR_COMPLETE`, `CAPTURE_REFUSED`, `CAPTURE_EPOCH_START`), fails its strict regex: **`ERROR node_log_unparseable`** (r5, H11);
  - the supervisor `journalctl` (boot census) exiting non-zero or timing out;
  - **`journalctl` exiting non-zero, timing out, or returning no output while `breezy-quote-tape-ingest.service` has `ExecMainExitTimestamp` later than D's rotation**;
  - an epoch error (§3.3.5);
  - a node-log or funnel positive-control failure (D13, below).

  The audit then writes the audit file with `day_status=ERROR` and the cause, writes the verdict `outcome=ERROR`, sends CRITICAL `CAPTURE_AUDIT_ERROR cause=<c>` through `deliver_with_proof` and exits 1. The live-proof roll-up still runs from its fallback timer (§3.11, r5 H11).

**Boot census (r5, H5).** The set of boots overlapping D is the union of:
- every `TradingNode: instance_id:` line in the node logs;
- every distinct `node_boot_id` in the capture files for D−1..D+1;
- every node spawn on D. The node has no systemd unit of its own; it is the supervisor's `Popen` child (`src/breezy/runtime/trade_supervisor.py:866`), so its activations are the supervisor's `launched pid=<n>` lines (`:1300`, `log_decision("launched", pid=proc.pid)`, rendered by `logger.info("%s %s", event, rendered)` at `:926` under the formatter `%(asctime)sZ %(levelname)s %(name)s %(message)s` at `:1035`; the other spawn sites `:1379` and `:1631`, whose `:1633` line is `boot_retry_launched pid=<n>`, are pinned in WP0 item 11). **Pinned by test (r6, L4):** `tests/unit/test_capture_node_log.py::test_supervisor_launched_pid_line_matches_trade_supervisor_1300` runs the real `log_decision("launched", pid=…)` and `log_decision("boot_retry_launched", pid=…)` through a handler carrying the supervisor's own formatter. It asserts that the audit's spawn regex matches both lines and extracts the pid. An AST check asserts that the call at `src/breezy/runtime/trade_supervisor.py:1300` is still `log_decision("launched", pid=...)`, so a rename fails the gate rather than blinding the census. read with the literal argv `journalctl --user -u breezy-trade-supervisor.service -o cat --since … --until …` (30 s timeout). A spawn is matched to the log file it opened (`node_log_path(log_dir, now)`, `:1287`; matching rule pinned in WP0 item 11).

A boot in the union without a readable log (a capture `node_boot_id` with no instance-id line, or a spawn with no matched log) makes the day `ERROR node_log_missing`, never `NO_INPUT`. Tests `test_capture_records_without_node_log_is_error_not_no_input`, `test_supervisor_spawn_without_log_is_error_node_log_missing`, `test_supervisor_journal_failure_is_error`.

**Boot ended (D6, testable).** Boot B is *ended* at audit time iff (a) a later log file carries a different `TradingNode: instance_id:` line whose timestamp is later than every B record, or (b) B's log contains the Nautilus disposal line (exact text pinned in WP0 from a retained log; memory `hand-relaunch-mechanics`: "key on the DISPOSED line"). Otherwise B is *running*. With STOP at 16:40Z and LAUNCH at 16:50Z, (a) holds daily. r2's "the log stops before the next event" is removed.

**Legs per fill** (`audit_fill`; only fills with `ts_event ≥ epoch_start_ns`; earlier fills are `unattributed`):

| Leg | Pass condition |
|---|---|
| L | Exactly one `decision_id` across the OrderLinks for `client_order_id`. A conflict is `link_conflict`; an orphan id is `untagged_order` FAIL (D12). |
| D | Entry: a `Take` and a `TrySubmit(submitted)` with that id, and the id recomputes from the Take. Exit: an `Exit` record whose id recomputes from the four exit tag values (C1 P1-8; ARCH `test_every_exit_fill_joins`). |
| B | Payloads exist and re-hash; `artefact_sha256` resolves; each forecast payload matches a node-log `FQ_VECTOR_COMPLETE (station, cycle_ns)`; every record has exactly one frame ref, and an `Exit` none; a quote Take's `quote` payload matches a tape Depth10 at the record's `instrument_id` and the payload's `ts_event` with an equal top, with strictness set by WP0 item 9 (§3.4.2). |
| I | **Offline intent linkage (P1-3).** `fp = intent_fingerprint(SimpleNamespace(**link_fields))` from the pre-submit OrderLink. `fill_by_fingerprint/<day>:<fp>` exists, and its venue order ids equal those of the `fill/` records naming `client_order_id`. `<day>` is derived exactly as `src/breezy/adapters/polymarket_us/exec/client.py:2101-2123` does (WP0). A mismatch is `intent_link_mismatch`. |
| E | `LifecycleEvent(FILLED)` with the same `trade_id`, or a resolver context names the `client_order_id`. |
| P | A node `PositionMark` with `ts_ns ≥ fill.ts_event`, or a tape mark (below), or `fill_via_resolver`. |
| S | A `SettlementRecord` from `settlement_<climate_day>.jsonl`. **"Ended" is pinned (r5, H11)** to the end of the climate day: midnight local standard time at the start of the next date, `climate_day_end_ns(climate_day, std_utc_offset_hours)` (`src/breezy/ingest/records.py:363`, public alias) with the offset from the sites registry's `climate_day_window(venue, city)` (`src/breezy/registry/sites.py:400`), never DST-aware. Ended < 36 h before the audit run → `PENDING`; later → `settlement_missing` FAIL (`test_leg_s_ended_is_end_of_climate_day_in_local_standard_time`). |

**Reconciliation legs per day** (independent of AUT-1's writer):

| Leg | Pass condition |
|---|---|
| R1 | For each boot: a **bijection** on `(station, rung_id, side, kind, reason, t)` between node-log `SHADOW_DECISION` lines of kind ∈ {Take, TrySubmit} with `now_ns` in D and capture records of that boot. `t` is the line's `now_ns`; on the record it is `eval_ns` for a Take and `wall_ns` for a TrySubmit or `EntryVeto` (C1 U9, §3.4.3). (Take lines map to `reason="take"`; the parser handles the `datetime.date(...)` repr in the line.) **Veto lines (r5, H3).** A TrySubmit line whose reason is in the closed `VetoReason` set maps to an `EntryVeto` record, because CS-2 writes it so. `EntryVeto` is on-change (C1), so these lines go through the boot's `OnChangeFilter` replay (R2) as `(key, EntryVeto, reason, eval_ns)`, with `eval_ns` taken from the preceding Take line of the same key in the same boot log. Only admitted lines need a record; a suppressed repeat is not `capture_missing`. A veto line with no preceding Take line is `veto_line_unanchored` FAIL. Guard `EntryVeto` records (those whose id also has a `TrySubmit(submitted)` record, §3.5.2) are excluded here and matched one-to-one with `CAPTURE_REFUSED` lines instead. A missing record is `capture_missing`; an extra one is `capture_unexplained`. |
| R2 (D9) | For each boot: feed **all** of that boot's `SHADOW_DECISION` lines, in log order, through the same `OnChangeFilter`, with veto TrySubmit lines entered as `EntryVeto` (R1, r5 H3) and `eval_seq` recomputed per `(key, now_ns)` in log order by the same rule as `FrameClock.next_eval_seq` (r5 H2; WP0 item 12 pins one line per evaluation). **Identical replay (r6, L3).** R2 does not reimplement the rule. It instantiates the same pure counter class that `FrameClock` uses (`EvalSeqCounter` in `src/breezy/strategy/autonomy_capture/frame_clock.py`, importable by `analysis`, which sits above `strategy`), with the same 4-entry retention window and the same `EVAL_SEQ_REORDER_BASE = 1_000_000` disjoint range. The key is 1:1 with `instrument_id` through `_instrument_context`. `test_r2_replays_reorder_ordinal_range_and_four_entry_window_identically` feeds one sequence through the node counter and through R2. That sequence includes a fifth distinct `ts_event` that evicts the oldest one, and then a late frame older than every retained entry. The test requires identical ordinals, including at least one ordinal ≥ 1,000,000. The output sequence of `(station, climate_day, rung_id, side, kind, reason, eval_ns, eval_seq)` must **equal** the boot's on-change capture records in file order across D−1..D+1, guard `EntryVeto` records excluded. Any insertion, deletion or reordering fails. This replaces r2's key-coverage test. |
| R3 | Funnel, segmented by boot: at the last flush `T` with no capture Take or TrySubmit within ±2 s of `T`, funnel `Take` and `TrySubmit` counts per reason equal the capture counts with `eval_ns ≤ T`. |
| R4 | Markers, the `incomplete/` journal, `CAPTURE_WRITE_FAILED`/`CAPTURE_BYTE_CAP` log lines, and any `partial_line` → FAIL. Their absence proves nothing (L-30). |
| O | Order census and **TrySubmit classification (D6).** Every `venue_id/` row with a D-dated `client_order_id`, every `resolver/` context created on D, and every node-log `OrderSubmitted`/`OrderDenied` line on D names an OrderLink. Each `TrySubmit(submitted)` is exactly one of: `linked` (an OrderLink with its id); `refused_after_trysubmit` (an `EntryVeto` with the same id and a guard reason, or `Refuse(instrument_vanished_after_trysubmit)`); `never_submitted` (linked, but no venue, resolver, lifecycle or log evidence, and the boot has ended; INFO). Anything else is `trysubmit_unlinked`: FAIL once the boot has ended, `order_pending` (INCONCLUSIVE) while it runs. |
| F | `set(fill_by_day filtered by ts_event) == set(fill/ scan in D)`; node-log fills ⊆ exec fills; any extra exec fill has a resolver context. |
| T (C14, D15) | Ingest journal lines after D's rotation, audited only for D ≥ the epoch day (r5, H10). For an earlier D (a manual or backfill run) the leg runs in INFO mode: legacy pre-ING-2-AMEND2 lines and other findings are reported as INFO and never fail it (`test_leg_t_pre_epoch_legacy_line_is_info`). Each `extend_dedupe:` line must match the strict regex `^extend_dedupe: chunks=\d+ filtered=\d+ unfiltered=\d+ by_type=(\S*) flat_root=(\S+)$`. A non-matching line, including the legacy line without `flat_root`, is `tape_line_unparseable` and fails the leg. `flat_root != none` → `tape_flat_root`. `custom_depth_truncation:<f>/<u>` with u > 0 → `tape_unfiltered`. **Positive control (r5, H10):** no matching line after the rotation, or **any instrument with ≥ 1 tape QuoteTick row for D** in the recorder catalog but zero Depth10 rows for D → `tape_ingest_missing` (`test_instrument_with_tape_quotes_and_no_depth_rows_is_tape_ingest_missing`). This replaces r4's "instrument subscribed on D", which the audit cannot observe. Lines with `chunks=0` are valid but prove nothing alone. |
| N | For each configured cycle whose `C + 3 h` fell inside a node-up interval on D: one `NBM_NBP_PUBLISHED cycle_ns=C` and one `FQ_VECTOR_COMPLETE` per configured station. |

**Node-log and funnel positive control (D13; L-52).** For each boot overlapping D by ≥ 20 min (the 15 min flush plus margin), where the recorder catalog holds ≥ 1 Depth10 row for an instrument that boot subscribed during the overlap (a node-independent trigger), the audit requires both:
- ≥ 1 `SHADOW_DECISION` line in that boot's log inside D;
- the file `fq_funnel_<boot day>.jsonl` present, with ≥ 1 row inside the boot's interval.

If either is missing, the day is **`ERROR node_log_blind` / `ERROR funnel_missing`**. Boots that overlap less, or that had no tape frames for their instruments, are exempt from this check but still face R1–R3. A missing funnel file is therefore never silently "no data". Tests in WP5.

- **Tape marks.** For every base slug with a non-zero net position (exec fills, leg sign, L-44), the audit reads the catalog Depth10 at each whole UTC hour of D and records `{instrument_id, hour, best_ask, net_qty}` in its own evidence file (`tape_marks`). These are corroboration for leg P and **not** C1 records, because C1 names only the node or position monitor as `PositionMark` writers.
- **Day status.**
  - `PASS`: every fill leg and R1–R4, O, F pass.
  - `INCONCLUSIVE`: while `PENDING` or `order_pending`.
  - `NO_INPUT`: no fills, orders or Take lines; the file and verdict are still written (D10).
  - `PRE_CAPTURE` / `PARTIAL_EPOCH`: §3.3.5.
  - `ERROR`: as above.
  - `FAIL`: otherwise.
- **Verdicts** (C4, ARCH-0 writer, `valid_until_ns = produced_at_ns + 26 h`, `producer_code_sha` pinned as `aut1_capture_audit`, `subject_artefact_sha256` = the bound artefact):
  - `capture_join_completeness`. Legs and R/O/F/I give `n = fills_total` with the `n_min` reason `"census: every fill is checked"`. **For a `NO_INPUT` day it is written with `outcome=INCONCLUSIVE`, `metrics.day_status="NO_INPUT"`, `n=0` (D10). This is the form C4 Invariants sanction (U10, from P1-15).** INCONCLUSIVE never acts and still satisfies the dead-man.
  - C4 accepts pre-registered metric names only. So the names AUT-1 writes are a closed literal tuple in `src/breezy/analysis/capture_audit.py`: `day_status`, `fills_total`, `fills_joined`, and one `leg_<id>_pass` per leg. They are proposed to AUT-5 for pre-registration with the policy rows (§5.2).
  - `capture_tape_ingest` (leg T; AUT-4 admissibility). `capture_nbp_census` (leg N).
  - Not proposed for `attest_required_verdict_kinds`.
- **Canary and drill.** The canary section has the same fill legs, and the live legs never open `canary/`. Drill fills are joined and marked `drill=true`.
- **Outputs.** `evidence/capture/audit/<family>/<D>.json` (write-once per run, named with `<ts_ns>` when re-audited; the newest wins; 0444; `capture_audit/v1`; venue ids only as sha256; no paths). The verdicts. CRITICAL `CAPTURE_JOIN_GAP`, `CAPTURE_TAPE_INGEST`, `CAPTURE_NBP_CENSUS` through `deliver_with_proof`. `OnSuccess=breezy-capture-live-proof.service`.

### 3.11 Units, timers, memory and locks

Two programme rules apply (PLAN_TEMPLATE; ARCH §5.2, G32):
- Every oneshot is bounded by `TimeoutStartSec` and never sets `RuntimeMaxSec`.
- No unit's [start, start + `flock -w` + `TimeoutStartSec`] meets [16:30Z, 17:10Z) for any firing.

r3's `*:0/5` watch and `*:7/15` watchdog breached the second rule, and r3 did not see it. r4 removes their window firings from the calendar and adds a code guard.

| Unit | `OnCalendar` (UTC) | Lock, `flock -w` | Memory | `TimeoutStartSec` | Latest end before the window |
|---|---|---|---|---|---|
| `breezy-capture-watch` | `*-*-* 00..15:00/5:00`; `*-*-* 16:00,05,10,15,20,25:00`; `*-*-* 17:10,15,20,25,30,35,40,45,50,55:00`; `*-*-* 18..23:00/5:00`; `AccuracySec=10s` | own, 30 s | `MemoryHigh=192M`, `MemoryMax=256M` | 120 | 16:25 + 150 s = 16:27:30 |
| `breezy-capture-watchdog` | `*-*-* 00..15:07,22,37,52:00`; `*-*-* 16:07,22:00`; `*-*-* 17:22,37,52:00`; `*-*-* 18..23:07,22,37,52:00` | own, 10 s | `MemoryMax=128M` | 60 | 16:22 + 70 s = 16:23:10 |
| `breezy-capture-settlement` | `*-*-* 13:35:00`, no `Persistent` | own, 30 s | `MemoryMax=256M` | 300 | 13:40:30 |
| `breezy-capture-audit` | `*-*-* 13:50:00`, no `Persistent` | `breezy-studies.lock`, 600 s, `breezy-studies.slice` | `MemoryHigh=768M`, `MemoryMax=1G` | 1500 | 14:25. WP5 measures the runtime over two 1.2 GB logs and returns to review above 15 min. |
| `breezy-capture-live-proof` | `OnSuccess=` of the audit, **and** (r5, H11) a fallback timer `*-*-* 14:35:00`, no `Persistent`, because the audit exits 1 on `ERROR` and `OnSuccess=` then never fires; the own lock serialises the two triggers and the roll-up is idempotent (newest file wins) | own `health/capture-live-proof.lock`, 30 s. r3 used the studies flock, whose 600 s wait could expire behind AUT-2's 14:15Z label job. | `MemoryMax=256M` | 300 | 14:25 + 330 s = 14:30:30; timer 14:35 + 330 s = 14:40:30 |
| `breezy-capture-stall-drill` | `Sun *-*-* 12:30:00` (WP0 confirms) | capture-watch lock, 30 s | `MemoryMax=64M` | 60 | 12:31:30 |
| `breezy-capture-stall-drill-guard` | `Sun *-*-* 13:15:00` | none | `MemoryMax=64M` | 30 | 13:15:30 |

- **Calendar tests** in `tests/unit/test_capture_units.py`:
  - `::test_no_unit_overlaps_launch_window` (the ARCH §4.7 name) expands each AUT-1 timer over 48 h and fails if any [start, start + W + T] meets [16:30Z, 17:10Z).
  - `::test_oneshot_units_use_timeout_start_sec_not_runtime_max_sec` (ARCH §4.7) fails if any `deploy/systemd/breezy-capture-*.service` sets `RuntimeMaxSec` or lacks `TimeoutStartSec`. This is the template's required deploy test.
  - `::test_no_capture_timer_is_persistent` pins the removal of `Persistent=true`.
- **Code guard.** Every AUT-1 CLI first calls `launch_window_guard(now_ns, flock_wait_s, timeout_start_s)`. If its run could meet [16:30Z, 17:10Z), for example after a manual start or a clock jump, it logs `CAPTURE_DEFERRED_LAUNCH_WINDOW unit=<n>` and exits 0 with no other effect (`test_cli_defers_inside_launch_window`, one case per CLI).
- **Blackout effects, each handled:**
  - the node's `recorder_stale` allowance (§3.7.4);
  - the watchdog-stamp threshold (§3.8.3);
  - the self-heal response timer (§3.8.3).

  A recorder stall that starts after 16:25Z is detected from 17:10Z. AUT-6 would defer its restart to 17:10Z in any case (§5.2).
- **Common unit settings:**
  - `OnFailure=breezy-study-failed@%n.service`, activated only after AUT-6's `test_study_failure_notifier_uses_deliver_with_proof` is green;
  - `EnvironmentFile=-%h/.config/breezy/alerts.env`, `WorkingDirectory=/home/jon/breezy`, `UMask=0077`;
  - the explicit interpreter `/home/jon/breezy/.venv/bin/python3`, and no venue credential.
- **Memory.** AUT-1's own-lock units add ≤ 1.0G (256M + 128M + 256M + 256M + 64M + 64M) to the ≤ 4G own-lock budget (ARCH §5.2, V14), and nothing inside the trade node. Each unit's measured peak is recorded before its timer is enabled (ARCH §5.2, U6).
- The 14:15Z AUT-2 label job waits on the studies flock behind the audit (≤ 14:25Z).

### 3.12 The 38-vs-35 live-vs-batch take divergence (with AUT-4; WP6)

- **Observed:** the facts table in §1.3. 3 or more Take keys differ, plus 9 numeric mismatches; the 1-day window agrees (5 vs 5).
- **AUT-1's share:**
  - per-key attribution: `src/breezy/analysis/capture_parity_attribution.py` reruns `scripts/analysis/nbp_shadow_parity.py` read-only, as **seven 1-day windows**, one at a time, each under `MemoryMax=4G` in the studies slice outside 01:00–04:30Z (the 7-day unit failed);
  - extracts the per-key `(station, climate_day, rung_id, side, now_ns)` Take sets for live and batch, and the 9 numeric mismatches;
  - classifies each difference as one of: `trigger_order` (quote-before-depth, §1.3), `permit_window` (live 0 vs batch 493,796 `NotExecutable`), `latch_state`, `numeric` (float tolerance), or `other`.
- **Hypotheses only (L-18).** No cause is asserted until the classification runs. The trigger-order mechanism (a quote Take latching before the depth evaluation that batch would see) is the leading hypothesis, because it is the one with a known mechanism.
- **Output:** `docs/evidence/AUT1_parity_take_divergence_<date>.md`, with every differing key listed and its class.
- **Ownership of fixes:** AUT-4 owns any fix to the batch evaluator or the moved statistics (G36). AUT-1 owns any fix on the live capture path. A `trigger_order` finding is handed to AUT-4 for the batch evaluator. Live capture already records quote-triggered Takes with `quote_ref` (§3.4.2), so the finding changes nothing on the live path.

### 3.13 Alert catalogue (r5, H11)

Every row goes through `deliver_with_proof` (ARCH §4.6, V3): node rows through `AlertOutbox.offer`, unit rows directly. AUT-1's rows are added to ARCH `test_detector_and_failure_mode_alerts_use_delivery_proof` (L-12). "Delivery-keyed" means a repeat is suppressed only behind a `delivered=true` record for the same `event` in the window (§3.8.5).

**Event strings (r6 T4).**
- The `event` passed to `deliver_with_proof` or `AlertOutbox.offer` is the bare token in the Event column. Qualifiers such as `reason=`, `cause=`, `consecutive=` and the detector state go in the payload `detail`, never in `event`.
- r6 names the rows that r5 described only by state: `CAPTURE_EPOCH_UNREADABLE`; `RECORDER_HUNG`, `RECORDER_STALLED`, `RECORDER_WRITER_STALL` (restart requested), `RECORDER_UNHEALED`, `RECORDER_INACTIVE`; `NWS_INGEST_HUNG`, `NWS_GATE_NOT_OPEN`; and the watchdog's `CAPTURE_WATCH_STALE`, `CAPTURE_AUDIT_DEADMAN`, `CAPTURE_AUDIT_FILE_MISSING`, `CAPTURE_SETTLEMENT_MISSING` and `CAPTURE_LIVE_PROOF_STALE`. r6 also adds `CAPTURE_SETTLEMENT_ERROR` (§3.9).
- Every event is in the closed tuple `CAPTURE_ALERT_EVENTS`. `CAPTURE_HEALED_<sha>` is matched as the prefix `CAPTURE_HEALED_` plus 64 lowercase hex, so it is 79 characters. Every event matches `CAPTURE_EVENT_RE = ^[A-Z0-9_]{1,96}$` after the hex is upper-cased for the regex check only; the sent string keeps lowercase hex. That makes each one safe in ARCH's outbox file name `evidence/alerts/outbox/<ts_ns>_<event>.json`: no `/`, no `.`, no whitespace, no NUL, and well under `NAME_MAX` (`test_capture_alert_events_are_closed_and_filename_safe`).
- **Contract test against the real AUT-6 code.** `tests/unit/autonomy/test_capture_alert_contract.py::test_capture_events_pass_verbatim_through_real_deliver_with_proof` runs once per event, plus one `CAPTURE_HEALED_<sha>` instance. It calls the real `breezy.runtime.alert_delivery.deliver_with_proof` with a recording in-process sink at the webhook branch (no network; NO-SEND untouched) and a temporary evidence root. It asserts that the written per-attempt record's `event` equals the input byte for byte. A companion case does the same through the real `AlertOutbox.offer`: the outbox file name ends in `_<event>.json`, and the drained record's `event` is verbatim. Both are RED until AUT-6's API lands; WP3 and WP8 do not activate while they are RED.

**Exit status on a failed delivery (r6, L2).** The watch, settlement, drill and drill-guard CLIs follow the watchdog's rule (§3.8.5). Each first completes its own durable work: the watch writes its state file, settlement its records, the drill its evidence, and the guard its **unconditional SIGCONT**, which always runs before any exit decision. Then each exits 1 if any `deliver_with_proof` call in the run returned a failed proof, so `OnFailure=` fires. Tests: `test_watch_failed_delivery_exits_nonzero`, `test_settlement_failed_delivery_exits_nonzero`, `test_drill_failed_delivery_exits_nonzero`, `test_drill_guard_failed_delivery_exits_nonzero_after_sigcont`.

| Event | Severity | Sender | Repeat rule |
|---|---|---|---|
| `CAPTURE_WRITE_FAILED`, `CAPTURE_BYTE_CAP`, `CAPTURE_PAYLOAD_COLLISION` | CRITICAL | node writer | first per cause per 300 s; suppressed counts journaled (§3.3.3, H8) |
| `CAPTURE_REFUSED` (`capture_untagged`, `capture_gap`); guard `obs.cause` ∈ {`exit_capture_gap`, `untagged_sell`, `untagged_buy`, `capture_order_list_refused`} | CRITICAL | guard | per event (order path, rare) |
| `CAPTURE_VENUE_SILENT` (`venue_silent`) | WARNING | node `md_feed_freshness` | on the transition to DISAGREE, then delivery-keyed hourly while it holds |
| `NBP_CYCLE_MISSED` | CRITICAL | node `nbp_feed_freshness` | per missed cycle |
| `CAPTURE_EPOCH_UNREADABLE` (unreadable epoch file) | CRITICAL | lifecycle actor | once per boot |
| `CAPTURE_HEALED_<observation_sha256>` | INFO | watch; node NBP actor | once per heal record, re-sent by the watch each probe until a `delivered=true` record exists (§3.14, r6 T1) |
| `RECORDER_HUNG`, `RECORDER_STALLED`, `RECORDER_WRITER_STALL` (restart request), `RECORDER_UNHEALED`, `RECORDER_INACTIVE`; `NWS_INGEST_HUNG`, `NWS_GATE_NOT_OPEN`; `CAPTURE_WATCHDOG_STALE` | CRITICAL | watch | delivery-keyed hourly; a failed delivery exits 1 (r6 L2) |
| `RECORDER_HEARTBEAT_NEVER_SEEN`, `RECORDER_BYTES_STALE_AWAITING_HEARTBEAT` | CRITICAL | watch | delivery-keyed hourly; never a restart |
| `CAPTURE_WATCHDOG_DEGRADED` | WARNING | watch | delivery-keyed hourly |
| `CAPTURE_WATCHDOG_CHECK_ERROR`, `CAPTURE_AUDIT_STUCK_INCONCLUSIVE`, `CAPTURE_WATCH_STALE`, `CAPTURE_AUDIT_DEADMAN`, `CAPTURE_AUDIT_FILE_MISSING`, `CAPTURE_SETTLEMENT_MISSING`, `CAPTURE_LIVE_PROOF_STALE` | CRITICAL | watchdog | delivery-keyed hourly; a failed delivery exits 1 |
| `CAPTURE_SETTLEMENT_ERROR` (r6) | CRITICAL | settlement | per failing station-day per run; a failed delivery exits 1 |
| `CAPTURE_JOIN_GAP`, `CAPTURE_TAPE_INGEST`, `CAPTURE_NBP_CENSUS`, `CAPTURE_AUDIT_ERROR` | CRITICAL | audit | per audited day |
| `CAPTURE_DRILL_NOT_HEALED`, `CAPTURE_DRILL_SKIPPED` | CRITICAL | drill guard; drill CLI | per drill slot; a failed delivery exits 1 (the guard after SIGCONT; r6 L2) |

### 3.14 Heal-alert linkage (r5, H6)

- Every heal record (watch §3.8.3, node NBP §3.7.2) carries `observation_sha256`: the sha256 of the canonical JSON of its other fields, computed before the write.
- Its alert is sent after the record is written, with `event = "CAPTURE_HEALED_" + observation_sha256`. ARCH §4.6 fixes the delivery record's fields (`event`, `ts_ns`, `delivered`, `status_class`, `severity`, `attempt_kind`, `drill`), so the linkage rides in `event` and no field is added (§11 R-11).
- The live-proof roll-up accepts a heal only when a `delivered=true` record in `evidence/alerts/<date>/` or the next day's (W13) has exactly that `event` (`test_delivery_record_must_reference_heal_record`). An unrelated delivered alert on the same day no longer satisfies artefact 3 (§6). r6 widens the search window to cover retries (below).
- **Heal-alert retry (r6 T1).**
  - On every probe, the watch lists the heal records of the last `HEAL_ALERT_RETRY_DAYS = 8` dates under `evidence/capture/heal/`: its own, and the node NBP actor's, including those with `alert="undeliverable"`.
  - A record has a match when a `delivered=true` delivery record with exactly `CAPTURE_HEALED_<observation_sha256>` exists in any `evidence/alerts/<date>/` from the heal's date to today.
  - The watch re-sends every record without a match through `deliver_with_proof` with that same `event` and `attempt_kind="retry"`. A node record is re-sent only once it is older than `HEAL_ALERT_RESEND_MIN_AGE_S = 600`, so an in-flight outbox entry is not doubled. Delivery is at-least-once (U3).
  - If any re-send still fails, the watch writes its state file and exits 1 (§3.13, L2).
  - The watch does not re-send inside [16:30Z, 17:10Z), because it does not run there.
- **Roll-up reports it explicitly.** `live_proof_<family>_<asof>.json` carries `heal_alert_undelivered: [{heal_record, event, age_s}]`, listing every heal record in the window without a match, and the integer `heal_alert_undelivered_count`. A heal in that list never satisfies artefact 3. The roll-up accepts a matching delivered record from any date between the heal's date and the heal's date + `HEAL_ALERT_RETRY_DAYS`. That is a superset of the next-day rule (W13), so `test_delivery_record_found_in_next_day_directory` still holds unchanged.
- Tests: `test_undelivered_heal_alert_is_resent_next_probe`, `test_watch_resends_undeliverable_node_heal_record`, `test_resend_failure_exits_nonzero_after_state_write`, `test_rollup_reports_heal_alert_undelivered`, `test_retried_delivery_within_retry_days_satisfies_artefact_3`.

---
## 4. Work packages

**Gate for every WP:**

```
scripts/ci/run_tests_no_egress.sh; echo EXIT=$?          # full gate, exact interpreter; read EXIT (L-43)
cd <tree root> && lint-imports                            # console script; must print "N kept, 0 broken"
scripts/ci/run_tests_no_egress.sh tests/unit/test_mypy_ratchet.py
```

- In a worktree, set `PYTHONPATH=<worktree>/src`. Never `uv`, `pip`, `uv run` or `git stash`. Unit-launched gates use `-p LimitNOFILE=524288`.
- Must stay green **unedited**: `test_exec_client_is_byte_identical_to_its_pre_sl13_sha256`, `test_execution_egress_firewall_guard`, `test_operator_control_assignment_scan`, `test_shadow_only_false_is_only_the_gate_output`, `test_live_orders_ruling_deploy_copy_matches_evidence`, `test_native_order_cap_wiring`, `test_risk_engine_ordering_enforcement`, `tests/unit/test_probe_containment.py::test_pyproject_addopts_deselect_the_probe_markers` (L-54), and every existing `tests/strategy/forecast_quantile_ladder/*` test.
- Grep the contract tests for each module's package before placing it (L-46).

### AUT-1a

#### AUT-1.WP0: premises and measurements (characterisation; mutation evidence per L-33)

- **Measured** as one studies-flock job outside 01:00–04:30Z under `MemoryMax=4G`:
  1. full-UTC-day C1 volume and payload volume;
  2. per-instrument silence p99.9 in active and quiet hours, `ACTIVE_HOURS_UTC`, and the derived `QUIET_HOURS_MULTIPLIER` (D8; 14 tape days);
  3. inter-growth intervals of a streaming `live/<instance>/` conditioned on ≥ 1 published event, giving `WRITER_STALL_S`;
  4. the `BulletinFetcher` HTTP timeout;
  5. systemd 259 SIGCONT after SIGTERM, on a throwaway `systemd-run --user` sleep unit;
  6. fsync p50/p99/p99.9 (10,000 × 1 KiB) on the decisions filesystem, plus `os.link` + directory-fsync latency on the payload filesystem, giving `CAPTURE_FSYNC_P99_BUDGET_MS` and `CAPTURE_TAKE_TO_SUBMIT_P99_BUDGET_MS` (D7, §4 WP7); `CAPTURE_REFUSAL_PATH_P99_BUDGET_MS = 5` is a literal ceiling, not WP0-derived (r6 T3);
  7. the drill window: the hourly take distribution over the 63 retained logs, and recorder instance age;
  8. the exact Nautilus disposal-line text in a retained trade log (D6);
  9. the fraction of tape `QuoteTick`s having a Depth10 with equal `(instrument_id, ts_event)` and equal top, which sets leg B's tape-check strictness (§3.4.2);
  10. the `fill_by_fingerprint` `<day>` derivation (`src/breezy/adapters/polymarket_us/exec/client.py:2101-2123`);
  11. (r5, H5) the supervisor's spawn lines at every `spawn_node` call site (`src/breezy/runtime/trade_supervisor.py:1300`, `:1379`, `:1631`), their exact journal text, and the rule matching a spawn to its `node_log_path` file;
  12. (r5, H2) that every `evaluate` call emits exactly one `SHADOW_DECISION` line, and the per-instrument rate of non-monotone `ts_event` over 14 tape days.
- **Files.** `tests/unit/test_aut1_l1_nautilus_premises.py` (new), `docs/evidence/AUT1_WP0_premises_<date>.md` (new).
- **Characterisation tests**, each failing against a recorded mutation:
  - `::test_order_events_publish_on_events_order_strategy_topic`
  - `::test_actor_wildcard_msgbus_subscription_receives_order_and_position_events`
  - `::test_msgbus_handler_exception_unwinds_into_publisher`
  - `::test_python_submit_order_override_is_dispatched_from_python_caller` (gates WP7)
  - `::test_python_submit_order_list_override_is_dispatched`
  - `::test_refused_submit_before_super_never_adds_order_to_cache`
  - `::test_order_tags_absent_from_wire_body`
  - `::test_depth10_ts_event_is_venue_transact_time`
  - `::test_quote_published_before_depth_for_one_frame` (D2)
  - `::test_order_link_str_forms_recompute_intent_fingerprint` (leg I, against a real `LimitOrder`)
  - `::test_client_order_id_embeds_utc_date`
  - `::test_class_to_filename_of_depth_truncation_is_custom_depth_truncation` (D15)
  - `::test_close_position_dispatch_through_python_submit_order_override_is_recorded` (r5, H11; records the outcome for the §3.5.3 ban)
  - `::test_every_evaluation_emits_one_shadow_decision_line` (r5, H2; R2's `eval_seq` replay)
- **GREEN.** All pass on 1.231.0, and the evidence file states every constant.
- **Activation.** None.

#### AUT-1.WP1: capture core

- **Files.** `src/breezy/persistence/autonomy/capture_ids.py`, `src/breezy/persistence/autonomy/capture_on_change.py`, `src/breezy/persistence/autonomy/capture_writer.py`, `src/breezy/persistence/autonomy/capture_payloads.py`, `src/breezy/persistence/autonomy/capture_alerts.py` (r6), `src/breezy/persistence/autonomy/capture_epoch.py`, `src/breezy/persistence/autonomy/capture_reader.py`, `src/breezy/persistence/autonomy/capture_watch_state.py`, `src/breezy/persistence/autonomy/capture_schedule.py` (new); `src/breezy/persistence/exit_tags.py` (edit).
- **RED first** (`tests/unit/autonomy/`):
  - `tests/unit/autonomy/test_capture_ids.py`: `::test_decision_id_recomputes_from_stored_record`, `::test_decision_id_field_order_is_pinned`, `::test_decision_id_includes_eval_seq`, `::test_decision_id_unique_per_take` (ARCH §4.7), `::test_exit_decision_id_is_deterministic_from_exit_tags`, `::test_exit_decision_id_uses_only_the_four_exit_tag_values`, `::test_orphan_decision_id_never_equals_a_decision_id_domain`, `::test_depth_ref_excludes_ts_init_and_size_zero_pads`, `::test_quote_ref_is_canonical`, `::test_quote_payload_body_is_exactly_ask_bid_ts_event`, `::test_ref_equals_payload_store_name`, `::test_forecast_input_sha_is_canonical`
  - `tests/unit/autonomy/test_capture_on_change.py`: `::test_on_change_admits_take_and_trysubmit_always`, `::test_on_change_is_pure_and_replayable`, `::test_on_change_eviction_depends_only_on_eval_ns`, `::test_on_change_never_resets_at_utc_rollover`
  - `tests/unit/autonomy/test_capture_writer.py`: `::test_records_match_c1_rev9_2_exact_field_sets` (OrderLink has no `intent_id`; DecisionRecord has `ask_px`, `p_hat_raw`, `eval_seq`, `wall_ns`, `quote_ref`; PositionMark has `reconciliation_source`; DetectorEvent has no `detail`), `::test_exactly_one_frame_ref_except_exit`, `::test_detector_event_exact_fields_and_logged_preimage`, `::test_take_trysubmit_link_lifecycle_are_fsynced`, `::test_short_write_sets_needs_newline_and_next_record_parses` (D11), `::test_write_failure_is_critical_logged_and_journaled_write_once`, `::test_outbox_offer_false_counts_drop_and_journals_alert_enqueued_false` (D11), `::test_marker_write_failure_leaves_health_not_ok`, `::test_byte_cap_is_loud_not_silent`, `::test_utc_rollover_open_failure_is_loud`, `::test_reason_is_closed_enum`, `::test_fsync_p99_over_budget_reports_disagree_without_veto`, `::test_canary_records_land_only_in_canary_store`, `::test_writer_never_raises`, `::test_drill_flag_read_per_record_not_frozen`, `::test_settlement_record_is_never_written_to_capture_file`, `::test_new_boot_after_torn_tail_prefixes_newline` (r5 H1), `::test_write_failure_critical_deduped_per_cause_per_300s_with_counts_journaled` (r5 H8)
  - `tests/unit/autonomy/test_capture_payloads.py`: `::test_payload_put_uses_os_link_and_never_replaces_existing_name`, `::test_payload_collision_is_critical`, `::test_payload_store_refuses_symlinks`, `::test_payload_retention_never_deletes`, `::test_refusal_payload_put_runs_off_event_loop`, `::test_refusal_payload_queue_full_is_loud_and_never_blocks`, `::test_async_and_sync_put_of_same_payload_converge` (r6 T3)
  - `tests/unit/autonomy/test_capture_alerts.py` (r6 T4): `::test_capture_alert_events_are_closed_and_filename_safe`, `::test_heal_alert_event_is_prefix_plus_64_lowercase_hex`
  - `tests/unit/autonomy/test_capture_epoch.py`: `::test_epoch_written_once_with_o_excl`, `::test_existing_epoch_is_verified_not_rewritten`, `::test_unreadable_epoch_alerts_without_veto`
  - `tests/unit/autonomy/test_capture_reader.py`: `::test_join_exposes_stored_eval_seq_never_recomputed` (r6 L1), `::test_join_fills_to_decisions_by_client_order_id`, `::test_join_reports_orphan_fill_as_gap`, `::test_reader_counts_partial_line_and_blank_line_separately`, `::test_reader_classifies_unterminated_last_line_as_torn_tail` (r5 H1), `::test_reader_takes_fills_as_values_never_imports_exec_client`
  - `tests/unit/autonomy/test_capture_watch_state.py`: `::test_watch_state_single_read_refuses_symlink_oversize_unknown_keys`, `::test_restart_request_schema_exact`
  - `tests/unit/autonomy/test_capture_schedule.py`: `::test_launch_window_guard_boundaries`, `::test_seconds_outside_launch_window_spanning_window`
  - `test_autonomy_payload_hygiene_scan` and `test_autonomy_files_have_one_writer` widened with AUT-1's rows (L-12).
- **GREEN.** All pass; `lint-imports` clean; no Nautilus import in `capture_ids`, `capture_on_change`, `capture_writer`.
- **Activation.** Library only.

#### AUT-1.WP2: FQ adapter, plugin entry, guard library

- **Files.** `src/breezy/strategy/forecast_quantile_ladder/capture_adapter.py`, `src/breezy/strategy/forecast_quantile_ladder/plugin.py`, `src/breezy/strategy/autonomy_capture/guarded_strategy.py`, `src/breezy/strategy/autonomy_capture/frame_clock.py` (new). FQ's base class is **not** changed here.
- **RED first:**
  - `tests/strategy/forecast_quantile_ladder/test_aut1_capture_adapter.py`: `::test_decision_record_field_map_take`, `::test_decision_record_field_map_refusals_null_probabilities`, `::test_p_hat_raw_equals_p_hat_only_while_recalibration_none`, `::test_quote_triggered_take_stores_quote_payload_and_ref`, `::test_quote_triggered_record_has_null_depth_ref`, `::test_quote_take_without_prior_depth_is_not_capture_gap`, `::test_order_tags_single_decision_tag`, `::test_no_leg_take_records_side_no`
  - `tests/unit/autonomy/test_capture_guard.py`: `::test_capture_guarded_strategy_without_writer_refuses_construction`, `::test_capture_guarded_strategy_without_outbox_refuses_construction`, `::test_untagged_buy_refused_capture_untagged`, `::test_duplicate_or_malformed_tag_refused`, `::test_refused_order_never_reaches_cache`, `::test_untagged_sell_links_orphan_id_alerts_and_submits` (D12), `::test_exit_tagged_order_is_never_refused`, `::test_legitimate_exit_raises_no_critical`, `::test_exit_with_missing_tag_still_submits_and_alerts`, `::test_link_write_failure_refuses_buy_capture_gap`, `::test_submit_order_list_with_untagged_buy_refuses_whole_list`, `::test_submit_order_list_of_tagged_orders_links_each`, `::test_guarded_submit_latency_independent_of_webhook`, `::test_capture_untagged_is_a_veto_reason` (ARCH §4.7), `::test_untagged_buy_without_known_take_writes_detector_event_not_decision_record`, `::test_exit_record_id_recomputes_from_four_exit_tags_and_has_no_frame_ref`
  - `tests/unit/autonomy/test_capture_guard_family_agnostic.py`: `::test_every_full_plugin_kind_strategy_subclasses_capture_guard` (RED until WP7), `::test_decision_id_tag_prefix_never_collides_with_exit_prefixes`
  - `tests/unit/autonomy/test_capture_frame_clock.py` (r5, H2): `::test_same_frame_quote_and_depth_get_distinct_ids`, `::test_eval_seq_counts_unadmitted_evaluations`, `::test_eval_seq_counter_is_bounded_per_instrument`, `::test_nonmonotone_ts_event_never_repeats_an_ordinal`
- Fixtures write through the real `CaptureWriter` (L-42); one test runs the production default factory (L-55).
- **GREEN.** All pass except the subclass test, which is marked RED-pending-WP7 in the WP's evidence (not `xfail`-weakened; it lands with WP7 in AUT-1b).
- **Activation.** Library only.

#### AUT-1.WP3: recorder heartbeat, capture watch, watchdog

- **Files.** `src/breezy/adapters/polymarket_us/config.py`, `src/breezy/adapters/polymarket_us/data.py`, `src/breezy/runtime/node_config.py` (edit); `src/breezy/runtime/capture_watch.py`, `src/breezy/runtime/capture_watch_cli.py`, `src/breezy/runtime/capture_watchdog.py`, `src/breezy/runtime/capture_watchdog_cli.py` (new); `deploy/systemd/breezy-capture-watch.*`, `breezy-capture-watchdog.*` (new); `src/breezy/persistence/autonomy/pins.py` (the two units in `SELF_HEAL_RESTARTABLE_UNITS`; producer pins `aut1_capture_watch`).
- **RED first:**
  - `tests/unit/test_recorder_heartbeat.py`: `::test_heartbeat_is_atomic_rate_limited_and_o1`, `::test_heartbeat_written_during_empty_discovery_retry`, `::test_trade_node_config_has_no_heartbeat_path`, `::test_heartbeat_failure_never_raises`
  - `tests/unit/test_capture_watch.py`:
    - D3 (heartbeat activation): `::test_awaiting_heartbeat_is_info_only_never_restart_or_veto`, `::test_awaiting_heartbeat_over_26h_raises_critical_without_restart`, `::test_first_rotate_after_activation_ends_awaiting_state`, `::test_awaiting_heartbeat_flat_bytes_raises_critical_without_restart` (r5 H11)
    - hang and stall: `::test_stale_heartbeat_with_active_unit_is_hung`, `::test_hung_detection_not_gated_by_hours`, `::test_streaming_with_frozen_counters_and_bytes_is_stalled`, `::test_stalled_quiet_hours_horizon_uses_wp0_derived_multiplier` (D8)
    - writer stall: `::test_one_event_with_flat_bytes_over_stall_span_is_writer_stall` (D8, the 1–49 gap), `::test_event_inside_flush_margin_is_not_writer_stall` (D8), `::test_healthy_quiet_trickle_never_writer_stall` (D8 positive control: 1 event, bytes grow after 10 s), `::test_frozen_writer_fixture_triggers_restart_request`, `::test_midnight_file_rotation_is_not_writer_stall`
    - guards against false restarts: `::test_empty_listing_within_budget_is_ok`, `::test_rotation_grace_suppresses_restart_request`, `::test_inactive_unit_never_requested`
    - self-heal handshake: `::test_two_consecutive_bad_probes_write_restart_request`, `::test_watch_never_calls_systemctl_restart` (AST), `::test_heal_confirmed_after_aut6_selfheal_record_writes_write_once_heal_record`, `::test_no_selfheal_record_within_30min_is_unhealed_critical`, `::test_restart_request_classification_is_hung_with_substate_cause`, `::test_heal_confirmation_reads_current_and_previous_trading_date_dirs`, `::test_selfheal_response_timeout_excludes_launch_window`, `::test_heal_record_carries_observation_sha256_and_alert_event_names_it` (r5 H6), `::test_undelivered_heal_alert_is_resent_next_probe`, `::test_watch_resends_undeliverable_node_heal_record`, `::test_resend_failure_exits_nonzero_after_state_write` (r6 T1), `::test_watch_failed_delivery_exits_nonzero` (r6 L2)
    - other: `::test_nws_ingest_snapshot_stale_alerts_without_restart_request`, `::test_gate_closed_alerts_only`, `::test_watch_state_file_is_atomic_and_schema_exact`, `::test_watch_raises_when_watchdog_stamp_stale`, `::test_watchdog_stamp_threshold_covers_launch_window_gap`
  - `tests/unit/test_capture_watchdog.py`: `::test_watchdog_raises_when_watch_state_stale`, `::test_watchdog_raises_when_watch_timer_inactive`, `::test_no_verdict_within_26h_raises_critical_via_deliver_with_proof`, `::test_missing_audit_file_for_elapsed_day_is_critical`, `::test_inconclusive_older_than_8_days_raises_critical` (D15), `::test_missing_settlement_for_traded_station_day_is_critical`, `::test_watchdog_alert_rate_limited_hourly`, `::test_raising_check_is_isolated_and_raises_check_error_with_degraded_stamp`, `::test_watchdog_rate_limit_keyed_on_delivered_true`, `::test_watchdog_failed_delivery_exits_nonzero` (r5 H7); and in `tests/unit/test_capture_watch.py`, `::test_watch_treats_degraded_stamp_as_fresh_and_warns`
  - `tests/unit/test_capture_units.py`: `::test_oneshot_units_use_timeout_start_sec_not_runtime_max_sec` (ARCH §4.7), `::test_no_unit_overlaps_launch_window` (ARCH §4.7), `::test_no_capture_timer_is_persistent`, `::test_cli_defers_inside_launch_window`, `::test_watch_and_watchdog_own_lock_no_studies_flock`, `::test_live_proof_unit_uses_own_lock`, `::test_capture_units_onfailure_target_proven_notifier`
  - `tests/unit/autonomy/test_capture_alert_contract.py` (r6 T4): `::test_capture_events_pass_verbatim_through_real_deliver_with_proof`, `::test_capture_events_pass_verbatim_through_real_alert_outbox_offer` (RED until AUT-6's API lands; activation waits on GREEN)
- **GREEN.** All pass; ARCH `test_self_heal_unit_allowlist_is_literal_and_excludes_trade` passes with the two units.
- **Activation.** Immediately on merge, after AUT-6's notifier test and the r6 T4 contract tests are green: `systemctl --user link` both units and `enable --now` both timers, outside [16:27Z, 17:10Z) (the CLIs self-defer there). The watch starts in `AWAITING_HEARTBEAT` (no restart, no veto). The recorder loads the heartbeat at the next 09:00Z rotate. Then confirm fresh `recorder-polymarket_us.json`, `recorder.state=OK`, and a passing `capture_watchdog.json`.

#### AUT-1.WP4: NBP in-node hang reset

- **Files.** `src/breezy/ingest/nbm_quantile_actor.py`.
- **RED first:** `tests/unit/test_nbm_quantile_actor.py::test_submit_retains_future`, `::test_poll_hang_is_cancelled_and_reset_after_threshold`, `::test_poll_reset_followed_by_vector_complete_writes_write_once_heal_record`, `::test_heal_record_name_carries_writer_id`, `::test_nbp_heal_record_carries_observation_sha256_and_offers_named_alert` (r5 H6), `::test_nbp_heal_with_absent_outbox_logs_critical_and_writes_undeliverable_heal_record` (r6 T2), `::test_heal_alert_offer_returning_false_logs_critical_record_already_written` (r6 T2), `::test_actor_without_heal_alert_offer_constructs_unchanged` (existing call sites keep working).
- **GREEN.** All pass; existing actor tests unedited.
- **Merge and activation (r6 T2).** Built and reviewed in Wave 1, but **merged only in the same merge train as WP8**, never earlier. It then activates at WP8's supervisor STOP/LAUNCH, with the outbox wired by the WP8 hunk. Technical reason: the trade node loads the actor at boot, so a lone earlier merge would go live at the next LAUNCH with no outbox. AUT-1 never hand-relaunches the node. The undeliverable fallback (§3.7.2) plus the watch's re-send (§3.14) cover any residual window.

#### AUT-1.WP5: settlement writer, audit, node-log parser, live-proof roll-up, retention

- **Files.** `src/breezy/analysis/capture_settlement.py`, `src/breezy/analysis/capture_settlement_cli.py`, `src/breezy/analysis/capture_audit.py`, `src/breezy/analysis/capture_audit_cli.py`, `src/breezy/analysis/capture_node_log.py`, `src/breezy/analysis/capture_live_proof.py`, `src/breezy/analysis/capture_live_proof_cli.py` (new); units `breezy-capture-settlement.*`, `breezy-capture-audit.*`, `deploy/systemd/breezy-capture-live-proof.service` (new); `scripts/ops/decisions_retention.py`, `src/breezy/persistence/autonomy/pins.py` (edit).
- **RED first** (`tests/unit/test_capture_audit.py` unless named):
  - settlement: `tests/unit/test_capture_settlement.py::test_settlement_appends_once_per_raw_sha`, `::test_settlement_correction_appends_new_record`, `::test_settlement_basis_is_venue_owned`, `::test_settlement_writer_is_sole_writer`, `::test_settlement_read_error_sends_critical_and_exits_nonzero`, `::test_settlement_failed_delivery_exits_nonzero` (r6 L2)
  - join: `::test_complete_day_passes_final`, `::test_orphan_fill_without_link_fails`, `::test_untagged_order_orphan_id_fails_leg_l`, `::test_link_conflict_fails`, `::test_settlement_pending_is_inconclusive_overdue_fails`, `::test_leg_s_ended_is_end_of_climate_day_in_local_standard_time` (r5 H11), `::test_payload_rehash_mismatch_fails`, `::test_forecast_payload_without_vector_complete_line_fails`, `::test_leg_b_quote_take_matches_tape_depth_same_ts_event`, `::test_registry_seq_zero_after_resolver_live_fails`, `::test_resolver_fill_without_node_filled_event_passes_e_and_p`, `::test_tape_mark_satisfies_leg_p_without_node`, `::test_every_exit_fill_joins` (ARCH §4.7), `::test_leg_b_quote_tape_check_strictness_follows_wp0_rate`, `::test_audit_backfills_days_without_audit_file_within_8`
  - intent linkage: `::test_leg_i_recomputed_fingerprint_matches_fill_by_fingerprint`, `::test_leg_i_mismatch_fails_intent_link_mismatch`
  - epoch: `::test_fill_before_epoch_is_unattributed`, `::test_days_before_epoch_are_pre_capture_and_epoch_day_partial`, `::test_missing_epoch_with_capture_files_is_error`, `::test_epoch_later_than_first_record_is_error_rewritten`
  - reconciliation:
    - R1: `::test_node_log_take_line_without_capture_record_fails`, `::test_capture_record_without_node_log_line_fails`, `::test_eval_ns_is_handler_ts_event_and_trysubmit_wall_ns_matches_line_now_ns` (D5, R1 pin), `::test_r1_matches_trysubmit_on_wall_ns_and_take_on_eval_ns`, `::test_r1_maps_veto_trysubmit_lines_to_entryveto_records_through_on_change_filter`, `::test_r1_suppressed_repeat_veto_line_is_not_capture_missing`, `::test_r1_veto_line_without_preceding_take_fails`, `::test_r1_guard_entryveto_matched_to_capture_refused_line` (r5 H3)
    - R2 (D9): `::test_r2_replay_sequence_equals_capture_sequence`, `::test_r2_deleted_refusal_record_fails`, `::test_r2_reordered_refusal_records_fail`, `::test_r2_replay_spans_utc_rollover_within_boot`, `::test_r2_recomputes_eval_seq_per_key_and_now_ns` (r5 H2), `::test_r2_replays_reorder_ordinal_range_and_four_entry_window_identically` (r6 L3)
    - R3: `::test_funnel_vs_capture_count_mismatch_fails`, `::test_funnel_rows_segmented_by_boot`
    - R4: `::test_marker_write_failure_still_fails_day`, `::test_partial_line_fails_r4`
  - positive control (D13): `::test_boot_with_tape_frames_and_no_shadow_decision_is_error_node_log_blind`, `::test_boot_with_tape_frames_and_missing_funnel_file_is_error_funnel_missing`, `::test_short_boot_exempt_from_positive_control`, `::test_boot_without_tape_frames_exempt_from_positive_control`
  - orders (D6): `::test_trysubmit_linked`, `::test_trysubmit_refused_after_trysubmit_by_guard_entryveto`, `::test_trysubmit_instrument_vanished_is_refused_after_trysubmit`, `::test_trysubmit_unlinked_pending_while_boot_running`, `::test_trysubmit_unlinked_fails_after_boot_ended`, `::test_boot_ended_by_later_instance_id_line`, `::test_boot_ended_by_disposal_line`, `::test_crash_between_link_and_submit_classified_never_submitted`, `::test_every_exec_store_order_record_has_order_link`
  - census and fail-loud: `::test_fill_by_day_positive_control_matches_fill_keys`, `::test_exec_store_open_error_is_error_never_no_input`, `::test_undecodable_fill_record_is_error`, `::test_unknown_exec_key_prefix_is_error`, `::test_unreadable_node_log_is_error`, `::test_journalctl_nonzero_timeout_or_empty_is_error` (D15), `::test_capture_records_without_node_log_is_error_not_no_input`, `::test_supervisor_spawn_without_log_is_error_node_log_missing`, `::test_supervisor_journal_failure_is_error` (r5 H5), `::test_unparseable_marker_line_is_error_node_log_unparseable` (r5 H11), `::test_error_sends_capture_audit_error_through_deliver_with_proof`, `::test_error_writes_audit_file_and_verdict_before_exit_1`
  - D10: `::test_no_input_day_writes_file_and_inconclusive_verdict_with_day_status_no_input`
  - tape (D15): `::test_extend_dedupe_flat_root_fails_tape`, `::test_extend_dedupe_unfiltered_depth_truncation_fails_tape`, `::test_extend_dedupe_unparseable_line_fails_tape`, `::test_extend_dedupe_legacy_line_without_flat_root_is_unparseable`, `::test_chunks_zero_lines_alone_do_not_prove_ingest`, `::test_no_catalog_rows_for_day_is_tape_ingest_missing`, `::test_filtered_depth_truncation_count_is_healthy`, `::test_leg_t_audits_only_days_at_or_after_epoch_day`, `::test_leg_t_pre_epoch_legacy_line_is_info`, `::test_instrument_with_tape_quotes_and_no_depth_rows_is_tape_ingest_missing` (r5 H10)
  - NBP: `::test_nbp_cycle_census_missing_cycle_fails`, `::test_nbp_cycle_with_deadline_in_node_down_interval_not_expected`
  - canary, drill, families: `::test_canary_fills_reported_separately_never_in_live_legs`, `::test_drill_fills_joined_and_marked`, `::test_unknown_family_fill_is_enumerated_by_construction`
  - provenance: `::test_exec_store_fixture_written_through_real_record_fill` (L-42), `::test_verdict_schema_valid_bound_artefact_sha_and_pinned_producer`, `::test_fail_sends_critical_through_deliver_with_proof`, `::test_audit_evidence_has_no_absolute_paths`
  - `tests/unit/test_capture_node_log.py`: `::test_parses_shadow_decision_take_and_trysubmit_lines_with_date_repr`, `::test_parses_orderfilled_client_and_venue_ids`, `::test_reads_instance_id_line`, `::test_unparseable_marker_line_is_counted_never_skipped_silently`, `::test_streaming_parser_memory_is_o_matches`, `::test_supervisor_launched_pid_line_matches_trade_supervisor_1300` (r6 L4)
  - `tests/unit/test_capture_live_proof.py`: `::test_zero_fill_days_extend_not_break`, `::test_fail_day_breaks_window`, `::test_requires_five_real_fills_excluding_canary_and_drill`, `::test_canary_only_day_qualifies_day_but_not_real_fill_count`, `::test_real_fill_day_cannot_be_rescued_by_canary`, `::test_pre_capture_and_partial_epoch_days_never_count`, `::test_requires_one_heal_record_with_delivery_record`, `::test_delivery_record_found_in_next_day_directory` (W13), `::test_delivery_record_must_reference_heal_record` (r5 H6), `::test_rollup_reports_heal_alert_undelivered`, `::test_retried_delivery_within_retry_days_satisfies_artefact_3` (r6 T1), `::test_fallback_timer_rolls_up_after_audit_error_exit`, `::test_proven_only_with_seven_qualifying_days`
  - `tests/unit/test_decisions_retention.py::test_capture_and_settlement_files_are_gzip_candidates`
  - `tests/unit/test_capture_units.py::test_live_proof_fallback_timer_is_outside_launch_window_and_not_persistent` (r5 H11)
- **Runtime evidence.** One run against two real retained logs (≈ 2.4 GB) under `MemoryMax=1G`, with wall time recorded; above 15 min the WP returns to review.
- **GREEN.** All pass; full gate.
- **Activation.** Immediately on merge, subject to the notifier: link and `enable --now` the settlement and audit timers, then one `systemctl --user start breezy-capture-settlement.service breezy-capture-audit.service` outside [15:55Z, 17:10Z), so the audit's 600 s wait plus 1500 s timeout cannot reach the window (the CLIs also self-defer). Until the epoch file exists, days are `PRE_CAPTURE` by rule, not by a literal.

#### AUT-1.WP6: 38-vs-35 attribution (with AUT-4)

- **Scope.** §3.12. Read-only; no edit to `scripts/analysis/nbp_shadow_parity.py`.
- **Files.** `src/breezy/analysis/capture_parity_attribution.py` (new), `docs/evidence/AUT1_parity_take_divergence_<date>.md` (new).
- **RED first:** `tests/unit/test_capture_parity_attribution.py::test_classifies_each_differing_take_key`, `::test_unclassified_difference_is_other_never_dropped`, `::test_totals_reconcile_to_parity_json_counts`.
- **GREEN.** Every differing key is classified and the totals equal 38/35 and 9.
- **Activation.** None (evidence). The record is handed to AUT-4.

### AUT-1b (after AUT-5a merges)

#### AUT-1.WP7: FQ hooks, re-base on the guard, submit-site test, full-path benchmark (gated on WP0 dispatch)

- **Files.** `src/breezy/strategy/forecast_quantile_ladder/strategy.py` (CS-0..CS-6; base class).
- **RED first:**
  - `tests/strategy/forecast_quantile_ladder/test_aut1_capture_hooks.py`:
    - plumbing (D5): `::test_production_trigger_paths_pass_capture_ctx` (D2, D5: depth and quote), `::test_safe_evaluate_forwards_trigger_source`, `::test_evaluate_snapshot_signature_unchanged`
    - Take capture: `::test_every_fq_order_carries_exactly_one_decision_id_tag`, `::test_take_record_carries_depth_ref_forecast_sha_and_artefact_sha`, `::test_blob_and_sha_work_only_after_on_change_check` (0 hash calls over 1,000 unchanged evaluations)
    - outcome records: `::test_trysubmit_carries_take_decision_id_eval_ns_eval_seq_and_own_wall_ns`, `::test_trysubmit_record_wall_ns_equals_shadow_line_now_ns`, `::test_entry_veto_reason_is_written_as_entryveto_record`, `::test_capture_failure_for_take_refuses_capture_gap_before_try_submit`, `::test_instrument_vanished_after_trysubmit_writes_refuse_record`
    - other: `::test_shadow_only_take_is_captured_without_order`, `::test_frame_clock_stamped_before_evaluation`, `::test_quote_trigger_set_unchanged_by_capture`, `::test_quote_then_depth_same_frame_records_have_distinct_decision_ids` (r5 H2), `::test_strategy_has_no_last_depth_map` (r5 H11)
  - `tests/unit/autonomy/test_capture_submit_sites.py`: `::test_every_strategy_submit_site_is_guarded_or_unreachable` (D4), `::test_no_indirect_send_helper_under_strategy` (r5 H11), `::test_unreachable_modules_not_in_trade_import_closure`, `::test_refusing_plugin_kinds_cannot_compose`, `::test_try_submit_reachable_only_from_frame_handlers` (D14)
  - `tests/unit/autonomy/test_capture_guard_family_agnostic.py::test_every_full_plugin_kind_strategy_subclasses_capture_guard` turns GREEN.
- **Full-path benchmark (D7).** `docs/evidence/AUT1_WP7_take_to_submit_<date>.md` measures p50/p99/p99.9 over 1,000 synthetic Takes on the host disk:
  - **the full path** from `_evaluate_with_capture` entry to the `super().submit_order` call: on-change check, depth payload put (fsync + link + directory fsync), forecast payload put (usually a no-op), quote payload put (quote trigger), Take fsync, TrySubmit fsync, guard OrderLink fsync — up to 3 payload fsyncs, 2 directory fsyncs and 3 record fsyncs;
  - the non-Take on-change refusal path (flush only);
  - the guard steps alone.

  The budget is `CAPTURE_TAKE_TO_SUBMIT_P99_BUDGET_MS = min(max(25, 1.5 × (3 × link_p99 + 3 × fsync_p99 + 2 × dirfsync_p99)), 150)` from WP0 item 6. **150 ms is an absolute ceiling (r5, H4)**, so a slow disk cannot lift the budget past it. A measured p99 above the budget blocks the merge. The only remedies are a reviewed restructure, re-benchmarked against the same budget, which is never raised:
  - (a) batched payload puts: every payload of one Take written, then a single directory fsync; or
  - (b) async payload puts on a bounded writer thread off the submit path, with the Take, TrySubmit and OrderLink records still fsynced before `super().submit_order`. Under (b) a payload lost to a crash is a missing cited payload, which C1 makes `capture_gap` and leg B fails loudly.
  Test `test_take_to_submit_budget_is_capped_at_150_ms` pins the formula.
- **Refusal path (r6 T3, coordinator ruling).** Refusal-record payload puts are always asynchronous (§3.3.2). This is not a remedy that waits for a budget breach. The benchmark's "non-Take on-change refusal path" row measures the on-loop work with the writer thread's `fsync` held blocked. Its p99 must stay under `CAPTURE_REFUSAL_PATH_P99_BUDGET_MS = 5`, which is never raised; above it the merge is blocked. Tests `tests/strategy/forecast_quantile_ladder/test_aut1_capture_hooks.py::test_refusal_path_never_blocks_on_stalled_payload_disk`, `::test_take_payload_puts_stay_synchronous_before_submit`.
- **Stuck-disk dependency (r6 T3).** `tests/unit/autonomy/test_capture_dependencies.py::test_aut6_node_liveness_detector_covers_log_mtime_and_tape_advance` must be GREEN before WP7 merges (§3.3.3).
- **GREEN.** All pass, plus every existing FQ test and `tests/unit/test_forecast_quantile_ladder_boot.py`, unedited.
- **Activation.** Through WP8's LAUNCH.

#### AUT-1.WP8: lifecycle actor, node-local detectors, epoch, composition hunk

- **Files.** `src/breezy/strategy/autonomy_capture/lifecycle_actor.py`, `src/breezy/strategy/autonomy_capture/node_observations.py` (new); `src/breezy/strategy/forecast_quantile_ladder/composition.py` (edit); `src/breezy/app/trade.py` (one hunk, rebased after AUT-5a).
- **RED first** (`tests/unit/autonomy/test_capture_lifecycle_actor.py`):
  - lifecycle: `::test_actor_writes_order_link_with_venue_sha_on_accept`, `::test_actor_writes_lifecycle_for_each_terminal_event`, `::test_position_mark_signs_no_leg_as_short_yes_with_node_belief`, `::test_handler_never_raises_into_publisher`, `::test_capture_actor_issues_no_venue_or_data_subscription`, `::test_epoch_written_at_first_capture_boot_and_logged`
  - capture_gap: `::test_capture_gap_vetoes_at_boot_until_positive_control`, `::test_observation_older_than_3_ticks_vetoes_at_call_time`
  - feed_stale (D14): `::test_frame_triggered_evaluation_never_vetoes_feed_stale`, `::test_per_instrument_silence_vetoes_non_frame_query`, `::test_venue_silent_fraction_is_observation_only_no_veto`, `::test_venue_silent_offers_warning_through_outbox` (r5 H11), `::test_slot_refusal_entryveto_written_once_by_cs2_not_by_detector` (r5 H3), `::test_md_silence_horizon_uses_quiet_hours_multiplier`
  - nbp_feed_freshness: `tests/strategy/forecast_quantile_ladder/test_aut1_nbp_freshness.py::test_one_missed_cycle_alerts_no_veto`, `::test_two_missed_cycles_veto_feed_stale`, `::test_no_complete_vector_for_subscribed_station_vetoes`, `::test_bulletin_drift_counts_as_missed_cycle`, `::test_veto_clears_on_newer_complete_vector`
  - recorder_stale: `::test_recorder_stale_vetoes_on_unhealed_inactive_or_stale_file`, `::test_awaiting_heartbeat_does_not_veto`, `::test_unparseable_watch_file_vetoes`, `::test_recorder_stale_tolerates_launch_window_gap_until_1720`
  - other: `::test_transient_capture_veto_writes_no_transition`, `::test_detectors_count_drill_records`, `::test_capture_modules_never_import_exec_store`
  - `tests/unit/test_forecast_quantile_ladder_boot.py::test_fq_composition_registers_capture_actor_and_detectors`, `::test_fq_compose_without_capture_writer_fails_boot` (production default factory, L-55), `::test_fq_composition_wires_heal_alert_offer_into_nbm_quantile_actor` (r6 T2)
  - `tests/unit/autonomy/test_capture_alert_contract.py::test_capture_events_pass_verbatim_through_real_alert_outbox_offer` GREEN (r6 T4)
- **GREEN.** All pass; `test_shadow_only_false_is_only_the_gate_output` unedited.
- **Activation.** The next supervisor STOP/LAUNCH (16:40/16:50Z). Technical reason: the hunk changes the order path, LAUNCH re-runs every boot gate, and a hand relaunch is refused after AUT-5a (the pre-9.2 Z7, per errata E-3). Preconditions: WP3 active ≥ 10 min with `recorder.state ∈ {OK}` (not AWAITING), and WP5 active. WP4 is merged in the same train (r6 T2). The first LAUNCH writes `capture_epoch_start`.

#### AUT-1.WP9: weekly injected recorder stall drill

- **Scope.**
  - `capture_stall_drill_cli` refuses unless all hold: `capture_watch` is `OK`, phase `STREAMING`, instance older than 1 h, within 10 min of the WP0 slot (default Sunday 12:30Z), and **AUT-6's health heartbeat reports SELF_HEAL enabled** (requested field `self_heal_mode`, §5.1; ALERT_ONLY refuses, because a drill without a healer is an outage).
  - It writes `evidence/capture/drill/<date>.json` (`injected=true`) and runs the literal argv `["systemctl","--user","kill","--signal=SIGSTOP","breezy-quote-tape.service"]`.
  - The guard at 13:15Z runs the literal SIGCONT argv unconditionally. If no heal record with `injected=true` exists for the drill, it raises CRITICAL `CAPTURE_DRILL_NOT_HEALED`.
  - Timeline: stop 12:30; heartbeat stale 12:33; two bad probes by 12:40 (request); AUT-6 pass at 12:41 or 12:51 (restart); heal confirmed by ≈ 13:00.
  - **Skipped-drill alarm (r5, H9).** Every refusal is recorded in the drill CLI's own state file `health/capture-stall-drill.json` (`{consecutive_refusals, last_reason, last_slot_date}`; atomic; one writer, added to `test_autonomy_files_have_one_writer`). A refusal while AUT-6 reports SELF_HEAL enabled increments the count; an ALERT_ONLY refusal neither increments nor resets it; a drill that runs resets it to 0. At 3 consecutive refusals, CRITICAL `CAPTURE_DRILL_SKIPPED consecutive=<n> last_reason=<r>` through `deliver_with_proof`, repeated on each further refused slot.
- **Files.** `src/breezy/runtime/capture_stall_drill_cli.py`; the drill and guard units.
- **RED first:** `tests/unit/test_capture_stall_drill.py::test_drill_refuses_when_recorder_not_ok_or_outside_window`, `::test_drill_refuses_while_aut6_self_heal_alert_only`, `::test_drill_window_is_not_in_rotate_hole_or_launch`, `::test_drill_argv_is_literal_sigstop_on_recorder_only`, `::test_guard_argv_is_literal_sigcont_on_recorder_only`, `::test_drill_marks_heal_record_injected`, `::test_three_consecutive_refusals_with_self_heal_enabled_raise_drill_skipped`, `::test_alert_only_refusal_does_not_count_toward_drill_skipped`, `::test_drill_run_resets_refusal_count` (r5 H9), `::test_drill_failed_delivery_exits_nonzero`, `::test_drill_guard_failed_delivery_exits_nonzero_after_sigcont` (r6 L2); plus an AST test that `src/breezy/runtime/capture_*` and `src/breezy/analysis/capture_*` call `subprocess` only through the two drill argvs, the read-only `is-active`/`show` argvs and the two `journalctl` argvs (ingest; r5 adds the supervisor one, H5).
- **GREEN.** All pass.
- **Activation.** Link and enable on merge. The drill self-refuses until AUT-6 leaves ALERT_ONLY (AUT-5b ruling).

---
## 5. Association

### 5.1 Consumed

| From | Contract | Exact interface |
|---|---|---|
| ARCH-0 | C1 | record dataclasses and schema strings (Rev 9.2 field sets: the `Exit` kind (P1-8), `eval_seq`, `wall_ns`, `quote_ref`, `reconciliation_source`), and `payload/v1` with the `depth10`, `quote` and `forecast_input` kinds (U8) |
| ARCH-0 | C4 | verdict dataclass and writer |
| ARCH-0 | C5, C6 | `CaptureAdapter`/`Detector` Protocols, `NODE_PLUGINS`, `RefusingPlugin`, `_compose_family` refusal; `VetoReason` with `capture_gap`, `feed_stale`, `recorder_stale` and `capture_untagged` (P1-9) |
| ARCH-0 | §3 common, §4.5 | `test_autonomy_files_have_one_writer` table; `src/breezy/persistence/autonomy/pins.py` (`SELF_HEAL_RESTARTABLE_UNITS`, `SELF_HEAL_MAX_RESTARTS_PER_UNIT_PER_DAY`, `PRODUCER_SOURCE_SHA256`, `MAX_VERDICT_VALIDITY_H`, `WATCH_TICK_STALE_S`) |
| AUT-5a | C5 | `ResolvedFamily`, `drill_active`, the `entry_veto` slot and composer, ownership of `try_submit` and `src/breezy/app/trade.py` until merged |
| AUT-5b | §4.6 | the policy ruling that maps `aut1.recorder_stall` to SELF_HEAL and ends ALERT_ONLY; proposed rows in §5.2 |
| AUT-6 | §4.6, C6 | `deliver_with_proof`; `AlertOutbox.offer -> bool`. `breezy-autonomy-health` consuming `capture_watch/v1` `restart_request` as detector `aut1.recorder_stall` (VERDICT HEALTH, SELF_HEAL, INFRA), with its restart site writing `evidence/selfheal/<trading_date>/<ts_ns>_<unit>.json` (W11). Fixed by ARCH §4.5 and §5.2, and consumed as written: `try-restart --no-block` with a ≤ 30 s `subprocess` timeout; the trading-day window and the ≤ 3 cap; `try-restart` of an active HUNG recorder (U11); deferral to 17:10Z inside the launch window. Requested from AUT-6 as area detail, not as ARCH changes: a `self_heal_mode` field in its health heartbeat (WP9), and that AUT-6's own tape-mtime liveness check does not raise a second restart for the recorder (one decision source). Also the migrated notifier and the catalogue rows #1–#3. (r5) Consumed as ARCH fixes it, no request: the delivery record's `event` is the caller's event string, so `CAPTURE_HEALED_<observation_sha256>` links a heal to its delivery (§3.14). (r6 T4) Asserted, not assumed: the contract tests in §3.13 run the real `deliver_with_proof` and `AlertOutbox.offer` and require the `event` verbatim and filename-safe. (r6 T3) Dependency: AUT-6's node-liveness detector (node log mtime plus tape advance; an existing ARCH member) is the out-of-process stuck-disk guard for the fsyncs that stay on the event loop; AUT-1 asserts its presence in a test that gates WP7 (§3.3.3). |
| AUT-2 | §5.3, Z14 | the canary producer driving AUT-1's production adapter and `CaptureWriter(source="canary")` |
| AUT-4 | §10 | joint owner of the 38-vs-35 fixes on the batch side (§3.12) |

### 5.2 Provided

| To | Contract | Interface |
|---|---|---|
| AUT-2 | C1 | capture files, `settlement_<date>.jsonl`, payload store, `join_fills_to_decisions`, epoch files (C2 `unattributed` boundary), exit ids. Contract (r6 L1): AUT-2 reads `eval_ns` and `eval_seq` from the stored record and never re-derives them. Tape marks are no longer C1 records (r2's `.offline.jsonl` is removed); they are in the audit evidence. |
| AUT-4 | C1, C4 | payloads; `.INCOMPLETE` markers; `capture_tape_ingest` verdicts; `docs/evidence/AUT1_parity_take_divergence_<date>.md`. Contract (r6 L1): AUT-4 reads `eval_ns` and `eval_seq` from the stored record and never re-derives them. |
| AUT-6 | C1, C6 | `DetectorEvent`s; NODE_LOCAL detectors; `capture_watch/v1` (states; `restart_request` with `classification="HUNG"` and a sub-state `cause`), `capture_watchdog/v1`; `recorder_self_heal` HEALTH verdicts |
| AUT-5 | C4 | HEALTH `capture_join_completeness`, `recorder_self_heal`, `capture_tape_ingest`, `capture_nbp_census`. Proposed rows: `capture_join_completeness FAIL → DEMOTE` (RECOVERABLE_INFRA); `aut1.recorder_stall → SELF_HEAL` (INFRA); the others → ALERT. |

### 5.3 Execution order

```
ARCH-0 ─► WP0 ─┬─► WP1 ─► WP2 (library) ───────────────┐
               ├─► WP3 (needs AUT-6 notifier to activate)│
               ├─► WP4 (built; merges with WP8, r6 T2)   ├─► [AUT-5a merged] ─► WP7 ─► WP8 (+WP4) ─► LAUNCH (epoch)
               ├─► WP5 (needs WP1; notifier to activate) │
               └─► WP6 (evidence; independent)          ┘
AUT-6 health + AUT-5b ruling (SELF_HEAL enabled) ─► WP9 drill live
```

- **Parallel in Wave 1:** WP0 with AUT-5a and AUT-6; after WP0, WP1, WP3, WP4, WP5's pure core and WP6.
- **Serial:** WP2 needs WP1; WP7 needs WP2, AUT-5a and AUT-6's node-liveness detector (r6 T3); WP8 needs WP7; WP4 merges with WP8 (r6 T2); WP9 needs AUT-6 out of ALERT_ONLY.
- **File ownership:** AUT-1 owns `_safe_evaluate`, `_evaluate_instrument_update`, `_evaluate_with_capture`, `evaluate_snapshot`, `_maybe_submit`, `_emit_decision_outcome`, `on_order_book_depth` and `on_quote_tick`. AUT-5a owns `try_submit` and `src/breezy/app/trade.py` until merged. Full gate after every merge; per-agent scratchpads.

---

## 6. Live-proof protocol

- **Artefacts:**
  1. `evidence/capture/audit/<family>/<D>.json` and the `capture_join_completeness` verdict per day;
  2. ≥ 1 heal record under `evidence/capture/heal/<date>/`. For a recorder heal it is paired with its AUT-6 `evidence/selfheal/<trading_date>/` restart record. A node NBP poll-reset record needs no AUT-6 record;
  3. a `delivered=true` per-attempt record in `evidence/alerts/<date>/` or the next day's (ARCH §4.6, W13), or in a later directory up to `HEAL_ALERT_RETRY_DAYS` for a re-sent alert (r6 T1), whose `event` is `CAPTURE_HEALED_<observation_sha256>` of that heal record (r5, H6; §3.14). The roll-up lists every heal still lacking one in `heal_alert_undelivered`;
  4. `evidence/capture/live_proof_<family_id>_<asof>.json` with `status=PROVEN`.
- **NBP forecast ingest is a feed (r5, H11).** The README's "recorder or feed stall" includes the NBP bulletin feed that FQ trades on. An in-node NBP poll-hang reset (§3.7.2) followed by `FQ_VECTOR_COMPLETE` for that cycle is a detected and self-healed feed stall and satisfies the stall leg; its heal record carries `decided_by="nbm_quantile_actor"`.
- **Roll-up trigger (r5, H11).** The roll-up runs on the audit's `OnSuccess=` and on its 14:35Z fallback timer, so an audit `ERROR` (exit 1) still produces a roll-up that records the broken run.
- **Qualifying days** (README rule, §1.1):
  - A day with ≥ 1 real fill (not canary, not drill) qualifies iff its live audit is `PASS`.
  - A day with no real fill qualifies iff a `source=canary` fill traversed the production capture code and the canary section passes; it adds 0 to the real-fill count.
  - A day with neither extends the window.
  - `FAIL`, `ERROR`, or `INCONCLUSIVE` past 8 days breaks the run.
  - `PRE_CAPTURE` and `PARTIAL_EPOCH` never count.
  - The window needs 7 qualifying days **and** ≥ 5 real fills.
- **Accrual ETA.**
  - **Join leg.** At the measured cadence of 2–3 takes a day, assuming AUT-1a merges by about 10-10 and AUT-5a by about 10-13, WP8 activates at the 10-14 LAUNCH and the epoch day is 10-14. The first qualifying day is 10-15, FINAL about 10-17 13:50Z. The earliest join-complete window is about **10-23**; the planning ETA is **10-30**, allowing 7 zero-fill or halted days.
  - **Stall leg.** A natural NBP poll-reset heal can satisfy it any time after WP4 activates, which is WP8's LAUNCH from r6 on (T2; the same date as the epoch), with no ruling dependency. A recorder heal, natural or injected, needs AUT-5b's ruling to take AUT-6 out of ALERT_ONLY (ARCH §4.6; Wave 3). Its date is AUT-5's to set and is not known here.
  - **So PROVEN = max(join window, first heal).** If neither natural heal occurs, the date is the first Sunday drill after the ruling is filed.
  - This leaves about 12 weeks before the 2027-01-25 KILL if the ruling lands by early December. Later than that, the stall leg is the binding risk (§8).
- **Evidence class.** "Machinery proven, edge unproven." It is a census, not a statistical test.
- If FQ is halted, real fills stop and the window pauses. Canary days alone cannot reach PROVEN.

---

## 7. Score-3 verification checklist (independent scorer)

| Criterion | Exact check |
|---|---|
| (a) Unattended | `systemctl --user list-timers 'breezy-capture-*'` lists watch, watchdog, settlement, audit, live-proof (r5 fallback timer), drill and guard. `git -C /home/jon/breezy log --since=<start> --until=<end> -- src/breezy/persistence/autonomy/ src/breezy/strategy/autonomy_capture/ src/breezy/runtime/capture_* src/breezy/analysis/capture_* deploy/systemd/breezy-capture-*` is empty. Every heal record's `decided_by` ∈ {`capture_watch`, `nbm_quantile_actor`}, and each recorder heal names an AUT-6 selfheal record. `scripts/ci/run_tests_no_egress.sh tests/unit/test_capture_units.py` passes, including `test_no_unit_overlaps_launch_window`. |
| (b) Family-agnostic | `scripts/ci/run_tests_no_egress.sh tests/unit/autonomy/test_capture_guard_family_agnostic.py tests/unit/autonomy/test_capture_submit_sites.py tests/unit/test_capture_audit.py::test_unknown_family_fill_is_enumerated_by_construction` passes; ARCH-0 `test_family_plugin_exact_set` passes. |
| (c) Fails closed | `test_untagged_buy_refused_capture_untagged`, `test_refused_order_never_reaches_cache`, `test_link_write_failure_refuses_buy_capture_gap`, `test_capture_guarded_strategy_without_writer_refuses_construction`, `test_unparseable_watch_file_vetoes`, `test_exec_store_open_error_is_error_never_no_input`, `test_journalctl_nonzero_timeout_or_empty_is_error`, `test_boot_with_tape_frames_and_missing_funnel_file_is_error_funnel_missing`, `test_marker_write_failure_still_fails_day` pass. In the node log, every `CAPTURE_REFUSED reason=` line has an `EntryVeto` record. |
| (d) Detected and alerted with delivery | For each failure mode (`CAPTURE_WRITE_FAILED`, `CAPTURE_BYTE_CAP`, `CAPTURE_PAYLOAD_COLLISION`, `CAPTURE_JOIN_GAP`, `CAPTURE_TAPE_INGEST`, `CAPTURE_NBP_CENSUS`, `NBP_CYCLE_MISSED`, recorder `HUNG`/`STALLED`/`WRITER_STALL`/`UNHEALED`/`INACTIVE`, `RECORDER_HEARTBEAT_NEVER_SEEN`, NWS `HUNG`, `CAPTURE_WATCHDOG_STALE`, `CAPTURE_AUDIT_STUCK_INCONCLUSIVE`, `CAPTURE_DRILL_NOT_HEALED`; r5 adds `CAPTURE_VENUE_SILENT` (`venue_silent`), `CAPTURE_WATCHDOG_CHECK_ERROR`, `CAPTURE_WATCHDOG_DEGRADED`, `CAPTURE_DRILL_SKIPPED`, `RECORDER_BYTES_STALE_AWAITING_HEARTBEAT`, `CAPTURE_AUDIT_ERROR` and `CAPTURE_HEALED_<sha>`; the full list is §3.13), a gate test asserts the outbox or `deliver_with_proof` is called. Live: `ls /home/jon/.local/share/breezy/evidence/alerts/<date>/` shows a `*_d.json` record with `"delivered": true` whose `event` equals `CAPTURE_HEALED_` + the heal record's `observation_sha256`. |
| (e) RED→GREEN | Per WP: the RED output naming §4's tests, the GREEN output and the merge SHA; `scripts/ci/run_tests_no_egress.sh; echo EXIT=$?` gives `EXIT=0`; `lint-imports` prints "N kept, 0 broken". |
| (f) Live proof | `jq .status /home/jon/.local/share/breezy/evidence/capture/live_proof_pm_us_crh_fq_v1_<asof>.json` is `"PROVEN"`. For each listed date, the newest `evidence/capture/audit/pm_us_crh_fq_v1/<date>*.json` gives `day_status=="PASS"` and `legs.R1.pass`, `legs.R2.pass`, `legs.O.pass`, `legs.F.pass`, `legs.I.pass` all true, with `fills_total == fills_joined`. The verdict under `derived/verdicts/pm_us_crh_fq_v1/<date>/` has `detector=capture_join_completeness, outcome=PASS`. `ls evidence/capture/heal/*/` has ≥ 1 file, and the roll-up's `heal_alert_undelivered` does not list the heal it counts (r6 T1). |
| Spot check, independent of AUT-1's code | For 3 random window fills: `sqlite3 'file:/home/jon/.local/share/breezy/state/exec_polymarket_us.sqlite?mode=ro' "select value from state where key='exec/polymarket_us/fill/<voi>'"` gives a `clientOrderId`. `/usr/bin/zgrep -h '"client_order_id": "<id>"' …/decisions/capture_pm_us_crh_fq_v1_*` finds the OrderLink, whose `decision_id` greps to a Take. That Take's `eval_ns` appears as `'now_ns': <eval_ns>` in a `SHADOW_DECISION … 'kind': 'Take'` log line. Its `depth_ref` payload under `derived/capture_payloads/depth10/`, or its `quote_ref` payload under `derived/capture_payloads/quote/`, has a `sha256sum` equal to its name. `python3 -c` over `intent_fingerprint` with the OrderLink's fields matches a `fill_by_fingerprint/` key. |

---

## 8. Risks and failure modes

| Risk | Mitigation |
|---|---|
| A capture handler raise unwinds into the engine (L-16) | Catch-all handlers; the writer never raises; `test_handler_never_raises_into_publisher`. |
| A timer raise is silently discarded | Call-time staleness veto; positive control. |
| The Take-to-IOC path gets slower (D7) | Up to 8 fsyncs measured end to end in WP7 against a WP0-derived budget capped at 150 ms (r5 H4); the merge is blocked above it, and the only remedies are batched or async payload puts. |
| Two decisions of one frame share a `decision_id` (r5 H2) | `eval_seq` counted per `(instrument_id, ts_event)` across handler calls; non-monotone frames use a disjoint ordinal range; R2 recomputes it. |
| A stuck filesystem blocks the event loop inside an fsync (r6 T3) | Refusal payload puts run off the loop and never block (`CAPTURE_REFUSAL_PATH_P99_BUDGET_MS`); the Take path keeps its ≤ 150 ms budget; a hung fsync is caught out of process by AUT-6's node-liveness detector (log mtime plus tape advance), asserted by a test that gates WP7. |
| A heal alert is lost and the heal never counts (r6 T1, T2) | The watch re-sends every heal record without a delivered match each probe and exits 1 on failure; the roll-up lists `heal_alert_undelivered`; WP4 merges with WP8 so the outbox is wired, and an absent outbox writes `alert=undeliverable` for the re-send. |
| A write-failure storm floods the outbox (r5 H8) | Per-cause 300 s dedupe with journaled counts; the veto and R4 are never deduplicated. |
| A watchdog check raises and silences the rest (r5 H7) | Per-check isolation, `CAPTURE_WATCHDOG_CHECK_ERROR`, degraded stamp, delivery-keyed rate limit, non-zero exit on failed delivery. |
| The drill silently never runs (r5 H9) | `CAPTURE_DRILL_SKIPPED` after 3 consecutive refusals while SELF_HEAL is enabled. |
| A boot leaves no log and hides its decisions (r5 H5) | Boot census unions log ids, capture `node_boot_id`s and supervisor spawns; a boot without a log is `ERROR node_log_missing`. |
| A quote Take cannot cite its depth (D2) | The C1 `quote` payload and `quote_ref` (U8); leg B's tape corroboration, with strictness set by WP0 item 9. |
| Capture blocks trading | Node-local vetoes auto-clear. `recorder_stale` fires only after self-heal fails. The venue-wide market-data rule is observation-only. Exits are never refused. |
| The independent sources share a call site | The log and funnel come from the same `_emit_shadow_decision` call as CS-1, so they are independent of the writer, not of the call site. Bypass is closed by the guard, the submit-site AST test, and order and fill census legs O, F and I. |
| Node-log format drift | Strict regexes; an unparseable marker or `extend_dedupe:` line fails the day; the D13 positive control makes a blind parser `ERROR`. |
| An epoch file is deleted and rewritten later, hiding gaps | `epoch_rewritten` and `epoch_unlogged` checks (§3.3.5). |
| The stall leg is blocked on the policy ruling (ARCH §4.6, a dependency) | The natural NBP heal path has no ruling dependency. Otherwise the ETA is stated as AUT-5b-dependent. |
| Two restart deciders for the recorder (AUT-6 tape-mtime vs AUT-1 watch) | One decision source requested (§5.1); AUT-6's cap and records bound any duplicate. |
| Restart loop in the 09:00–09:45Z listing hole | Legitimate `DISCOVERING` is OK; 600 s grace; ARCH cap ≤ 3 per unit per trading day; INACTIVE never requested; AWAITING never requests. |
| SIGKILL truncates a feather file | SIGCONT premise (WP0) with the reviewed `ExecStop` fallback; the guard always SIGCONTs. |
| A drill becomes an outage | Only from `OK`; only while SELF_HEAL is enabled; low-take slot; 13:15Z guard; CRITICAL if not healed. |
| Memory (the 30 GiB host, ARCH G29, which the template calls the 31 GB host; L-29, L-49, L-53) | Node structures O(subscribed instruments); unit caps per §3.11; WP0 and WP6 run one heavy job at a time outside 01:00–04:30Z. |
| Shared venv (L-51) | No dependency or console-script change; exact interpreter. |
| Concurrent agents (L-43, L-50) | Disjoint ownership; one writer per file (write-once event files); full gate per merge. |
| Statistical capacity | Census; ≥ 5 real fills per window. |
| KILL 2027-01-25 | If TERMINAL fires first, there is no sender and AUT-1 stays "machinery proven, window paused". |
| Launch-window blackout (r4) | No watch or watchdog run in [16:30Z, 17:10Z). A stall that starts after 16:25Z is seen from 17:10Z, when AUT-6's deferred restarts resume anyway. The three blackout effects are handled (§3.11). |
| Coordinator decisions misapplied | AUT-1 produces only HEALTH census verdicts. They involve no α, no nomination and no holdout read (HOLDOUT, ALPHA), and no `cause_code` (ROLLBACK-FAILURE). |

---

## 9. Binding-constraint compliance

- **Nautilus immutability:** only native extension (`Order.tags`, a `Strategy` subclass calling `super()`, `Actor` msgbus subscriptions, `clock.set_timer`). Nothing under `nautilus_trader` is touched.
- **Operator caps:** never read, assigned, defaulted or logged; `test_autonomy_never_reads_or_writes_operator_controls` is extended to AUT-1's paths; no cap env var is named (L-39).
- **`allow_short`:** untouched. Every entry stays a BUY; an untagged SELL is captured, never blocked or created.
- **NO-SEND firewall:** the exec client is unedited and byte-pinned; no new egress; alerts use `alerts.env` only; capture units hold no venue credential.
- **Master enablement and permit:** AUT-1 only adds refusals. It never mints, reads or touches permit authority; `test_autonomy_never_touches_enablement_permit_or_firewall` is widened to AUT-1's packages.
- **PREREG via ruling:** no statistical semantics change. Census verdicts; action mapping via AUT-5's ruling.
- **Coordinator decisions** (`docs/plans/backlog/AUTONOMY_2026-10-03/reviews/{HOLDOUT,ALPHA,ROLLBACK-FAILURE}-decision.md`):
  - HOLDOUT: AUT-1 never reads or writes the frozen holdout [2026-07-01, 2026-10-02) or AUT-4's forward window. Capture of days after 10-02 is input, not evaluation.
  - ALPHA: AUT-1's verdicts are HEALTH censuses. They charge no α, carry null `k_life`, `alpha_k`, `n_min_eff` and `n_cap`, and never nominate.
  - ROLLBACK-FAILURE: AUT-1 introduces no `cause_code` and writes no HALT. Its proposed policy rows use existing classes (RECOVERABLE_INFRA, INFRA).
- **ARCH errata:** E-1 (the outbox claim does `os.utime` first, then the rename) is implemented by AUT-6; AUT-1 only calls `AlertOutbox.offer` and never claims. E-2 and E-4 do not touch AUT-1. E-3 governs how tags are read (§0).
- **Launch window:** no AUT-1 unit runs in [16:30Z, 17:10Z) (§3.11).
- **Safety tests never weakened:** every §4 test stays green unedited; widenings follow L-12; nothing is deleted, relaxed or `xfail`-ed.

---

## 10. Self-score

**r6 (current).** The r5 round scored 93 (trading-bot-architect 95, silent-failure-hunter 93), with zero CRITICAL or HIGH. r6 applies T1–T4 and L1–L4 (§R6), follows the T3 coordinator ruling as written, and claims **94**: Fidelity 18, Correctness 19 (+1: the off-loop refusal path and the stuck-disk guard close the fsync-on-loop gap), Specificity 14, Acceptance 18 (+1: the heal re-send and `heal_alert_undelivered` make artefact 3 recoverable and visible; every event string is pinned against the real AUT-6 API), Autonomy-safety 15 (+1: failed deliveries now exit 1 in every alerting CLI; the WP4 outbox gate), Reuse 10 (+1: R2 reuses the node's own counter class, and the census pins the supervisor's own log text). The claim is discounted for the earlier over-claims.

**r5 (history).** r4 claimed 86 and the final round scored it 89 (trading-bot-architect 92, silent-failure-hunter 89), with zero CRITICAL or HIGH. r5 applies all of H1–H11 (§R5) and claims **90**: Fidelity 18, Correctness 18 (+1: the same-frame `decision_id` collision, the torn-tail gap and the unlogged-boot gap are closed), Specificity 14, Acceptance 17 (+1: the heal-to-delivery link and the live-proof fallback trigger make check (d) and (f) exact), Autonomy-safety 14 (+1: alert dedupe, watchdog isolation, the skipped-drill alarm and the indirect-send ban), Reuse 9 (+1: `_climate_day_end_ns` and the supervisor's own spawn log are reused). The table below is r4's, kept as history.

History: r1 claimed 90 and scored 76; r2 claimed 85 and scored 81; r3 claimed 81 and was not reviewed before this rebase. r4 removes every open ARCH item by adopting the frozen text. It also fixes four defects the rebase exposed, none of which a reviewer had flagged:
- refs that could differ from payload names (§3.3.1);
- `DetectorEvent.detail`, which is not a C1 field (§3.3.3);
- the watch and watchdog firing inside [16:30Z, 17:10Z) (§3.11);
- `Persistent=true` catch-ups that could land there (§3.9–§3.11).

The claim stays discounted for the earlier over-claims.

| Axis | Max | Score | Note |
|---|---|---|---|
| Fidelity | 20 | 18 | Consumes frozen Rev 9.2 (sha cited) and its errata. Adopts P1-8, P1-9, P1-12, U8, U9, U10, U11 and R9.2-Z9 as written, with no open contradiction. −2: nine residual readings are resolved in-plan by conforming (§11); R-2 and R-4 are interpretations a reviewer may read differently. |
| Correctness | 20 | 17 | New facts are anchored at `4b8347a6`: one decision per handler call, the exit tag names, the decisions directory. Ten premises remain WP0-deferred. The blackout tolerances are reasoned from the calendar, not measured. |
| Specificity | 15 | 14 | Calendars, locks, end times, fields and test names are exact. Several thresholds still take their value from WP0. |
| Acceptance | 20 | 16 | Every criterion maps to a command or path. The stall leg still depends on AUT-5b's filing date (ARCH §4.6). |
| Autonomy-safety | 15 | 13 | Restrictive-only; no restart site; exits never blocked; the launch window is respected by calendar and by code guard. The drill deliberately loses about 30 min of tape. |
| Reuse | 10 | 8 | Native tags, events and timers; the existing fingerprint, keys, logs, funnel and settlement reader. New: payload store, epoch, watch and watchdog, settlement unit. |
| **Total** | 100 | **86** | |

---

## 11. Contradictions and gaps against frozen ARCH Rev 9.2

**Open contradictions: none.** ARCH Rev 9.2 is frozen and is not reopened.

**Resolved by Rev 9.2, adopted in the body, and deleted from this section** (§R4 lists where each landed):
- N1: the `Exit` kind (P1-8).
- N2: `capture_untagged` in `VetoReason` (P1-9).
- N3: `try-restart --no-block` (P1-10, V8).
- N5: the trading-day restart window (P1-12).
- N7: the quote payload store, with `quote_ref` or `depth_ref` (P1-13 → U8).
- N8: `eval_ns` = the handler's event time, a separate `wall_ns`, and `eval_seq` in `decision_id` (P1-14 → U9, R9.2-Z9).
- N9: `INCONCLUSIVE` with `metrics.day_status=NO_INPUT` (P1-15 → U10).
- N10: `try-restart` of an active HUNG recorder (P1-16 → U11).

The alert-only period until the policy ruling is filed (§4.6) remains a **dependency** (§5.1, §6, §8), not a contradiction.

**Residual readings, resolved in this plan by conforming to ARCH:**
- **R-1 (r3 N11).** C1 names "CRH `_maybe_submit`" as a tag site, while C6 makes the CRH kinds `RefusingPlugin`. Both hold. The site gets the tag in the change that admits a CRH kind (C6: "full plug-ins in the same change"); today it is unreachable and classified so (§3.5.3).
- **R-2.** C1 lists `source` both as a common field and in the `PositionMark` row. The plan reads one field, the common `live` | `canary`, and puts the writer identity in `reconciliation_source=node_belief` (U5) (§3.3.3, §3.6).
- **R-3.** C1's `DetectorEvent` is exactly `detector`, `observation_sha256` and `state`. r3's `detail=` is removed; the observation preimage is hashed and logged (§3.3.3).
- **R-4.** C5 says a node-local veto writes a C1 `EntryVeto`. C1 says every non-`Exit` record needs a frame ref and an id built from decision fields. An untagged BUY with no known Take has neither, so the plan writes a `DetectorEvent` for it, and an `EntryVeto` whenever a Take is known (§3.5.2). In FQ production the case is unreachable, because CS-3 always tags.
- **R-5.** ARCH permits `try-restart` of an active recorder "classified HUNG". AUT-1's `STALLED` and `WRITER_STALL` are active-unit stalls. A restart request always carries `classification="HUNG"`, with the sub-state as its `cause`, so no new class reaches AUT-6 (§3.8.3).
- **R-6.** C1 writes `depth_ref` "or" `quote_ref`. The plan makes it exactly one, with both null for `Exit` (§3.3.3).
- **R-7.** C1's quote payload is `ask`, `bid`, `ts_event`. The plan uses exactly those; r3's `instrument_id` and sizes are dropped, and the citing record carries `instrument_id` (§3.3.1).
- **R-8.** The ARCH §4.6 text describes the outbox claim as a rename followed by `os.utime`; errata E-1 reverses the order. AUT-1 never claims outbox entries and depends on AUT-6 implementing E-1 (§9).
- **R-9.** ARCH §4.5 permits `try-restart` of an *active* unit only for "an active allowlisted recorder classified HUNG". r3 also requested restarts for an active but stale `breezy-nws-ingest.service`. r4 confines restart requests to the recorder. The ingest stays allowlisted for AUT-6's failed-unit path, and an active stale ingest only alerts (§3.8.2).
- **R-10 (r5, H2).** C1 defines `eval_seq` as the ordinal "among those evaluated in that handler call". For FQ one frame arrives as two handler calls with one `ts_event`, so a literal per-call ordinal gives two decisions of one key the same id and breaks ARCH's own `test_decision_id_unique_per_take`. The plan reads "handler call" as the frame's delivery and counts per `(instrument_id, ts_event)` across calls. Within a single call the ordinal is still 0, 1, … in evaluation order, so the reading is a strict refinement (§3.3.1).
- **R-11 (r5, H6).** ARCH §4.6 fixes the delivery record's fields and has no `observation_sha256`. The plan carries the heal record's `observation_sha256` in the `event` string (`CAPTURE_HEALED_<sha>`), which ARCH leaves to the caller, so no field is added (§3.14).

---

## §R3 Disposition (review `docs/plans/backlog/AUTONOMY_2026-10-03/reviews/AUT-1-r2-merged.md`)

*Historical: r3's disposition of review r2, kept verbatim. Where it cites N1–N10, Rev 6 or r3 test names, §R4 supersedes it.*

**D1–D16: 16 FIXED, 0 REJECTED.** In D10 the literal `outcome=NO_INPUT` is adapted to C4's closed enum (N9); the substance is fixed. In D1, "Delete N6" is read as r2 §11 item 6 (`.offline.jsonl`), because r2 has no N6.

| D | Disposition | Where / evidence |
|---|---|---|
| D1 | FIXED | Rebased on Rev 6 (sha `81c3c79f…af04e`). The sub-items: (1) `OrderLink(client_order_id, venue_order_id_sha256, instrument_id, side, qty, px, time_in_force)` with no `intent_id`, joined on `client_order_id`, plus offline leg I via `intent_fingerprint` (§3.3.3, §3.10; `submit_chain.py:242-253`). (2) Payload store `derived/capture_payloads/{depth10,forecast_input}/<sha>.json` written with `os.link` (§3.3.2). (3) Settlements in `decisions/settlement_<date>.jsonl` from a dedicated unit (§3.9); `.offline.jsonl` deleted (§11 item 6). (4) `DecisionRecord` carries `ask_px`, `p_hat`, `p_hat_raw`, `p_lower`, `p_upper`, `ev_net` (§3.4.1). (5) Invariants bind from `capture_epoch_start` (§3.3.5). (6) AUT-1a/AUT-1b split (§3.0, §4). (7) The self-heal counter is AUT-6's write-once `evidence/selfheal/<date>/` records, and AUT-1 writes write-once heal records (§3.8.3). (8) `TimeoutStartSec` everywhere (§3.11). Also: AUT-6 is the sole restart caller (§4.6) and AUT-1 has none. |
| D2 | FIXED | `source` is forwarded as `trigger` in `CaptureContext` (CS-0, CS-1; `strategy.py:753` drops it today). A quote Take stores a quote preimage and `quote_ref` (N7), with a latch-safe named-reason fallback `capture_quote_unpreimaged` before `evaluate` (§3.4.2). Refusal after `evaluate` is rejected with evidence: it would burn the rung-day latch (`decision.py:357`). Tests `test_quote_triggered_take_stores_quote_preimage_and_ref`, `test_leg_b_quote_take_matches_tape_depth_same_ts_event`, `test_fallback_quote_skip_happens_before_evaluate_and_never_latches`, `test_production_trigger_paths_pass_capture_ctx`. |
| D3 | FIXED | `AWAITING_HEARTBEAT` state: INFO only, never a restart request or veto, CRITICAL after 26 h, ends at the first heartbeat or once a recorder started after activation has had its grace (§3.8.2). Tests `test_awaiting_heartbeat_is_info_only_never_restart_or_veto`, `test_awaiting_heartbeat_over_26h_raises_critical_without_restart`, `test_first_rotate_after_activation_ends_awaiting_state`, `test_awaiting_heartbeat_does_not_veto`. |
| D4 | FIXED | AST `test_every_strategy_submit_site_is_guarded_or_unreachable`, with the literal unreachable table proven by `test_unreachable_modules_not_in_trade_import_closure` and `test_refusing_plugin_kinds_cannot_compose` (§3.5.3). The six current sites are classified (§1.3). Armed CRH exits are declared unreachable: the CRH kinds are `RefusingPlugin`, and `exit_wiring` is imported only by `continuous_strategy.py:56`. `submit_order_list` is guarded (§3.5.2). |
| D5 | FIXED | `decision_id` is plumbed `_safe_evaluate` → `_evaluate_instrument_update` → `_evaluate_with_capture` (which also serves `evaluate_snapshot`) → `_maybe_submit(decision_id=)` → `_emit_decision_outcome` (CS-0..CS-3). Take `eval_ns = ts_event` (`:805-806`) and TrySubmit `eval_ns` = wall clock (`:701`), pinned by `test_take_eval_ns_is_venue_ts_event_trysubmit_eval_ns_is_wall_clock` (R1) and `test_trysubmit_carries_take_decision_id_and_own_eval_ns`; ARCH wording raised as N8. |
| D6 | FIXED | Leg O classification: `linked` / `refused_after_trysubmit` (same-id guard `EntryVeto`, or `Refuse(instrument_vanished_after_trysubmit)` for `:677-679`) / `never_submitted` / `trysubmit_unlinked`. The boot-ended condition is a later `instance_id` line or the WP0-pinned disposal line (§3.10). Tests `test_trysubmit_*`, `test_boot_ended_by_*`. |
| D7 | FIXED | The full Take-to-IOC path (3 payload puts, 3 record fsyncs, directory fsyncs, guard link) is budgeted from WP0 item 6 and benchmarked in WP7; over budget blocks the merge (§4 WP7). |
| D8 | FIXED | WP0 item 2 measures quiet-hour silence and derives `QUIET_HOURS_MULTIPLIER`. `WRITER_STALL` fires on ≥ 1 event with flat bytes over `WRITER_STALL_S` beyond a flush margin, removing the 1–49 gap. Positive-control tests `test_healthy_quiet_trickle_never_writer_stall`, `test_one_event_with_flat_bytes_over_stall_span_is_writer_stall`, `test_event_inside_flush_margin_is_not_writer_stall` (§3.8.2). |
| D9 | FIXED | R2 replays each boot's log lines through the same pure `OnChangeFilter` (never reset at rollover, eviction by `eval_ns`) and requires sequence equality (§3.10). Tests `test_r2_replay_sequence_equals_capture_sequence`, `test_r2_reordered_refusal_records_fail`, `test_r2_replay_spans_utc_rollover_within_boot`. |
| D10 | FIXED (literal adapted) | A NO_INPUT day writes the audit file and a `capture_join_completeness` verdict with `outcome=INCONCLUSIVE`, `metrics.day_status="NO_INPUT"`, `n=0`. The C4 outcome enum is closed (Rev 6 `:275`), so `outcome=NO_INPUT` would be refused by the schema (N9). Test `test_no_input_day_writes_file_and_inconclusive_verdict_with_day_status_no_input`. |
| D11 | FIXED | `_needs_newline` prefixes `"\n"` after a short or unknown write; the reader separates `partial_line` (FAIL) from `blank_line` (INFO). `AlertOutbox.offer() == False` increments `alert_drops`, and the journal row carries `alert_enqueued=false` (§3.3.3). Tests in WP1. |
| D12 | FIXED | Only a BUY is refused. An untagged SELL gets an `OrderLink` under an orphan id, a `DetectorEvent` and a CRITICAL, then is submitted; its fill fails leg L as `untagged_order` (§3.5.2, §3.10). Test `test_untagged_sell_links_orphan_id_alerts_and_submits`. |
| D13 | FIXED | A boot overlapping D by ≥ 20 min with node-independent tape frames for its instruments must have ≥ 1 `SHADOW_DECISION` line and a present funnel file with a row in its interval, otherwise `ERROR node_log_blind` / `ERROR funnel_missing` (§3.10, L-52). Tests listed in WP5. |
| D14 | FIXED | The only paths to the veto are `on_order_book_depth` and `on_quote_tick` (`:724`, `:733` → `:753` → `:819` → `:666`), pinned by `test_try_submit_reachable_only_from_frame_handlers`. Freshness is stamped by the strategy before evaluating (`FrameClock`), replacing r2's passive actor subscription with its unguaranteed ordering. The per-instrument veto is kept; quiet hours use the WP0 multiplier. **r2's venue-wide veto (r1 C13) becomes observation-only:** on the frame paths it could only veto a take priced on a just-received frame because *other* instruments were quiet, and a dead connection produces no frames and therefore no takes (§3.7.1). |
| D15 | FIXED | `journalctl` failure → ERROR (`test_journalctl_nonzero_timeout_or_empty_is_error`). Unparseable and legacy `extend_dedupe:` lines are tested. The `custom_depth_truncation` name is pinned via `class_to_filename` in WP0. INCONCLUSIVE days are re-audited for 8 days, then CRITICAL `CAPTURE_AUDIT_STUCK_INCONCLUSIVE`. `chunks=0` lines (417 of 544 in 10 days) no longer count as ingest proof (catalog-row positive control). |
| D16 | FIXED | §10 re-scored 81 (down from r2's 85 claim), with r1/r2 over-claims named and r2's own one-writer breach disclosed. |

**r2 C-ids:** C1–C19 of `reviews/AUT-1-r1-merged.md` stay as disposed in r2's §R2 (`AUT-1-data-capture_plan_r2.md`). The exception is C13's venue-wide veto, superseded by D14 above.

---

## §R4 Rebase disposition (r3 → r4: frozen ARCH Rev 9.2 sha `1b288d0e…`, errata, PLAN_TEMPLATE, coordinator decisions)

**45 changes.** Every one conforms the plan to frozen ARCH or to a binding programme rule; none reopens ARCH. No README criterion, cap, enablement, permit, NO-SEND, exec-client or `allow_short` surface is touched, and no test is weakened.

| # | Section | Change | Basis |
|---|---|---|---|
| R4-01 | §0 | Round r4; consumes frozen Rev 9.2, sha `1b288d0e0172b233b791d875845e8002824a52d4a2e7819685ec0f2057572f42`, plus errata E-1…E-4; tags read per E-3; the Rev 6 and Rev 7 citations are removed. | Template ARCH-basis rule; task |
| R4-02 | §0, whole body | New Paths row. Every code, test and deploy path is now repo-root-relative (about 165 short citations expanded). Store paths sit under the absolute `/home/jon/.local/share/breezy/`, and `<decisions_dir>` is verified on disk. | Template Paths rule |
| R4-03 | §0 Upstream | AUT-6 restart site: argv `try-restart --no-block`; records under `evidence/selfheal/<trading_date>/`; outbox claim order per E-1. | ARCH §4.5, E-1 |
| R4-04 | §1.2 | Quotes the Rev 9.2 §10 AUT-1 obligation verbatim. Adds four obligation rows: the `Exit` id, `capture_untagged`, restarts only via AUT-6, and `quote_ref`/`wall_ns`. | ARCH §10 |
| R4-05 | §1.3 | Two new code facts: one decision per handler call (so `eval_seq` = 0), and the four exit tag names. The AUT-6 fact is restated from ARCH §4.5/§4.6/§5.2. The N8/N10 cross-references are removed. | Code at `4b8347a6`; ARCH |
| R4-06 | §2 | Payload-store and quote-preimage rows now implement the C1 contract (`quote` sub-store). The N7 fallback verdict is deleted. | C1 U8 |
| R4-07 | §3.0 | AUT-1b no longer waits on "ARCH acceptance of N7". | C1 U8 |
| R4-08 | §3.1 | New `src/breezy/persistence/autonomy/capture_schedule.py` (launch-window guard and blackout-aware elapsed time). All module paths are `src/breezy/…`. | Template [16:30Z, 17:10Z) rule |
| R4-09 | §3.3.1 | `compute_decision_id` gains `eval_seq`. Every id-bearing record of one decision shares `eval_ns`/`eval_seq`. ARCH test `test_decision_id_unique_per_take` added. | C1, R9.2-Z9 |
| R4-10 | §3.3.1 | The `Exit` id is a pure sha256 over the four exit tag values only (r3 also fed in a `family_id` argument). | C1 P1-8 |
| R4-11 | §3.3.1 | Every ref equals its payload-store name (sha256 of the canonical `payload/v1` bytes). Fixes r3, which hashed a separate string. | C1 payload store |
| R4-12 | §3.3.1, §3.3.2 | Quote payload kind `quote` with body exactly `{ask, bid, ts_event}`. A missing payload is `capture_gap`. | C1 U8 |
| R4-13 | §3.3.3 | `DecisionRecord` carries the Rev 9.2 field set (`eval_seq`, `wall_ns`, `quote_ref`, `Exit`), with exactly one frame ref except for `Exit`. | C1 U8, U9, P1-8 |
| R4-14 | §3.3.3, §3.6 | `PositionMark` uses `reconciliation_source="node_belief"`; `source` is the common field, `live` or `canary` (R-2). | C1 U5 |
| R4-15 | §3.3.3, §3.5.2, §3.7.1 | `DetectorEvent` has exact C1 fields. r3's `detail=` becomes a hashed observation with a logged preimage (`obs.cause`) (R-3). | C1 |
| R4-16 | §3.4.1 | Field map: `eval_ns` is the handler's `ts_event` for every kind. New `eval_seq` and `wall_ns` rows. TrySubmit copies the Take's `eval_ns`/`eval_seq`. | C1 U9 |
| R4-17 | §3.4.2 | Adopts the quote payload. r3's latch-safe fallback and its test are deleted, so FQ's trigger set is unchanged. Leg B tape strictness is set by WP0 item 9. | C1 U8 (P1-13) |
| R4-18 | §3.4.3 | CS-1/CS-2 populate `eval_seq` and `wall_ns`. "Pinned timestamps" restated to C1. Test renamed to `test_eval_ns_is_handler_ts_event_and_trysubmit_wall_ns_matches_line_now_ns`. | C1 U9 (P1-14) |
| R4-19 | §3.5.1, §3.5.2 | The Exit branch writes the `Exit` record ("pending N1" removed). Hooks `_capture_key_of` and the boot's Take map added. | C1 P1-8 |
| R4-20 | §3.5.2 | `capture_untagged` is a C5 `VetoReason` ("pending N2" removed). An untagged BUY with no known Take writes a `DetectorEvent`, not an invented id (R-4). | C1/C5 P1-9 |
| R4-21 | §3.7.4 | `recorder_stale`: a watch file written at or after 16:25Z stays fresh until 17:20Z, to cover the blackout. | Template window rule |
| R4-22 | §3.8.3 | Restart request carries `classification="HUNG"` plus a sub-state `cause` (R-5). | ARCH §4.5 U11 (P1-16) |
| R4-23 | §3.8.3 | AUT-6 executor as ARCH fixes it: argv `try-restart --no-block`, ≤ 30 s timeout, ≤ 3 per unit per trading day, `<trading_date>` directories, deferral to 17:10Z. The N3/N5 requests are deleted. | ARCH §4.5, §5.2 (P1-10, P1-12) |
| R4-24 | §3.8.3 | Heal confirmation reads the current and previous `<trading_date>` directories. | ARCH §4.5 |
| R4-25 | §3.8.3 | The self-heal response timeout counts time outside [16:30Z, 17:10Z) only. | ARCH §5.2 deferral |
| R4-26 | §3.8.3 | Watchdog-stamp threshold raised from 45 to 75 min (the blackout gap is 60 min). | Template window rule |
| R4-27 | §3.9 | Settlement timer drops `Persistent=true`; the trailing 7-day scan covers a missed run. | Template window rule |
| R4-28 | §3.10 | Audit timer drops `Persistent=true`, backfills days lacking an audit file within 8 days, and uses the explicit interpreter. | Template window rule |
| R4-29 | §3.10 | Leg D: an exit joins (no `PENDING_CONTRACT`). Leg B: exactly one ref plus the quote tape check. R1 matches TrySubmit on `wall_ns` and Take on `eval_ns`. | C1 P1-8, U8, U9 |
| R4-30 | §3.10 | The NO_INPUT verdict form is cited as sanctioned (U10). Metric names become a closed tuple proposed for pre-registration. | C4 Invariants, C4 metrics rule |
| R4-31 | §3.11 | Explicit `OnCalendar` lines that skip [16:30Z, 17:10Z) for the watch and watchdog; every `flock -w` and end time stated; ARCH test names; the template's `RuntimeMaxSec` deploy test. | Template systemd rules; ARCH §5.2, §4.7 |
| R4-32 | §3.11 | The live-proof unit moves from the studies flock to its own lock (the 600 s wait could expire behind the 14:15Z label job). Own-lock total ≤ 1.0G. | ARCH §5.2 locks |
| R4-33 | §3.11 | Code guard: every AUT-1 CLI self-defers if its run could meet the window. | Template window rule |
| R4-34 | §3.12 | A `trigger_order` finding goes to AUT-4, not to "the N7 decision". | C1 U8 |
| R4-35 | §4 WP0 | Item 9 now sets leg B's strictness rather than fallback admissibility. | C1 U8 |
| R4-36 | §4 WP1–WP3, WP5, WP7, WP8 | Tests added: eval_seq/unique id, exit-tag-only id, quote body, ref-equals-name, exact field sets, frame-ref rule, DetectorEvent fields, schedule, untagged-BUY record, exit record, HUNG classification, trading-date directories, blackout timers, persistent and overlap tests, backfill, R1 timestamps, leg-B strictness, node-belief mark, recorder-stale allowance, live-proof lock. Tests renamed: field sets (rev9_2), quote payload, TrySubmit wall_ns (two), `test_every_exit_fill_joins`, `test_no_unit_overlaps_launch_window`. Removed: the N7 fallback test; "pending N2"; `…_or_pending_contract`. | C1, ARCH §4.7, template |
| R4-37 | §4 WP3, WP5, WP8 | Activation steps avoid the window. WP8's Z7 read as pre-9.2 per E-3. | Template; E-3 |
| R4-38 | §5.1–§5.3 | Consumed rows cite Rev 9.2 fields, `capture_untagged`, the restart cap and the ARCH-fixed AUT-6 behaviour. The `restart_request` classification is provided. The N7 dependency is removed from the order. | ARCH C1, C5, §4.5 |
| R4-39 | §6, §7 | `<trading_date>` selfheal paths; the spot check names the `depth10`/`quote` sub-stores; check (a) runs the window test. | ARCH §4.5; C1 U8 |
| R4-40 | §8 | Quote, stall-leg and cap rows restated. The "ARCH widening refused" row is replaced by blackout and coordinator-decision rows. | ARCH; decisions |
| R4-41 | §9 | Compliance lines for HOLDOUT, ALPHA and ROLLBACK-FAILURE, the errata, and the launch window. | Decisions; errata; template |
| R4-42 | §10 | Re-scored 86, with history and the four rebase-found defects named. | Template §10 |
| R4-43 | §11 | Resolved items N1, N2, N3, N5, N7, N8, N9 and N10 deleted. Residual readings R-1…R-9 resolved in-plan by conforming. No open contradiction. | Task; frozen ARCH |
| R4-44 | §R3 | Marked historical, superseded by §R4 where it cites N-items, Rev 6 or r3 test names. | Traceability |
| R4-45 | §3.8.2, §3.8.3, §4 WP3 | Restart requests are confined to the recorder. An active but stale NWS ingest raises a CRITICAL and a `HEALTH` FAIL with no request; the ingest stays allowlisted for AUT-6's failed-unit path only (R-9). Test renamed to `test_nws_ingest_snapshot_stale_alerts_without_restart_request`. | ARCH §4.5 U11 |

---

## §R5 Disposition (review `docs/plans/backlog/AUTONOMY_2026-10-03/reviews/AUT-1-r4-merged.md`)

**H1–H11 (18 items, H11 counted as its 8 sub-items): 18 FIXED, 0 REJECTED.** No ARCH text is reopened. Two readings are recorded in §11 (R-10, R-11). No README criterion, operator cap, enablement, permit, NO-SEND, exec-client (byte-pinned, unedited) or `allow_short` surface is touched, and no test is weakened, renamed away or `xfail`-ed: every r4 test is kept and r5 only adds tests.

| Item | Disposition | Where / evidence |
|---|---|---|
| H1 | FIXED | §3.3.3 "Open-time tail check": every open reads the file's last byte through a separate `O_RDONLY|O_NOFOLLOW` descriptor and sets `_needs_newline` when it is not `\n` (a failed read counts as not `\n`). §3.3.3/§3.3.4: a lone unterminated last line is `torn_tail` and fails R4. Tests `test_new_boot_after_torn_tail_prefixes_newline`, `test_reader_classifies_unterminated_last_line_as_torn_tail` (WP1). |
| H2 | FIXED | §1.3 corrected (the "always 0" inference was wrong: the quote and depth handlers of one frame share `ts_event`). §3.3.1: `eval_seq` is the 0-based ordinal per `(instrument_id, ts_event)` across handler calls, by arrival, counted for every evaluation; bounded `FrameClock.next_eval_seq`; a disjoint range for non-monotone frames. §3.4.1, CS-1, R2 updated; WP0 item 12. ARCH reading R-10. Tests `test_same_frame_quote_and_depth_get_distinct_ids` (WP2) and `test_quote_then_depth_same_frame_records_have_distinct_decision_ids` (WP7), plus counter and R2 tests. |
| H3 | FIXED | §3.10 R1: TrySubmit lines with a closed-set `VetoReason` map to `EntryVeto` records and pass through the boot's `OnChangeFilter` replay; `eval_ns` comes from the preceding Take line; guard `EntryVeto`s are matched to `CAPTURE_REFUSED` lines. R2 enters veto lines as `EntryVeto`. §3.7: CS-2 is the sole slot-refusal `EntryVeto` writer. Tests in WP5 (four R1 tests) and WP8 (`test_slot_refusal_entryveto_written_once_by_cs2_not_by_detector`). |
| H4 | FIXED | WP7: budget `min(max(25, 1.5 × (…)), 150)` ms, an absolute 150 ms ceiling; a p99 above it blocks the merge; remedies are batched or async payload puts only, re-benchmarked, budget never raised. §8 row updated. Test `test_take_to_submit_budget_is_capped_at_150_ms`. |
| H5 | FIXED | §3.10 "Boot census": union of log instance ids, capture `node_boot_id`s and node spawns. The node has no unit of its own (it is the supervisor's `Popen` child, `src/breezy/runtime/trade_supervisor.py:866`), so the review's "`breezy-trade` unit activations" are read as the supervisor's `launched pid=` lines (`:1300`; other spawn sites pinned by WP0 item 11), read through a literal 30 s `journalctl` argv. A boot without a readable log is `ERROR node_log_missing`. Tests `test_capture_records_without_node_log_is_error_not_no_input`, `test_supervisor_spawn_without_log_is_error_node_log_missing`, `test_supervisor_journal_failure_is_error`. WP9's subprocess AST allowlist gains the argv. |
| H6 | FIXED | §3.14 (new), §3.7.2, §3.8.3: heal records carry `observation_sha256`; heal alerts go through `deliver_with_proof` (watch directly, node through the outbox) with `event = CAPTURE_HEALED_<observation_sha256>`; the roll-up accepts a heal only with a matching `delivered=true` record. §6 artefact 3 and §7(d) tightened. ARCH reading R-11 (the record's fields are fixed, so the link rides in `event`). Test `test_delivery_record_must_reference_heal_record` (WP5), plus WP3/WP4 record tests. |
| H7 | FIXED | §3.8.5: per-check `try`; a raised check is CRITICAL `CAPTURE_WATCHDOG_CHECK_ERROR` and the stamp is `status="degraded"`; the rate limit is keyed on a `delivered=true` record; a failed delivery exits 1 after the stamp is written. Tests `test_raising_check_is_isolated_and_raises_check_error_with_degraded_stamp`, `test_watchdog_rate_limit_keyed_on_delivered_true`, `test_watchdog_failed_delivery_exits_nonzero`, `test_watch_treats_degraded_stamp_as_fresh_and_warns`. |
| H8 | FIXED | §3.3.3 "Failure dedupe": per cause per 300 s; suppressed counts logged (`CAPTURE_WRITE_FAILED_SUPPRESSED`) and journaled write-once; the counter, `health.ok=False` and the `.INCOMPLETE` marker are never deduplicated. Test `test_write_failure_critical_deduped_per_cause_per_300s_with_counts_journaled`. |
| H9 | FIXED | WP9 "Skipped-drill alarm": the drill CLI's own state file counts consecutive refusals while SELF_HEAL is enabled; at 3, CRITICAL `CAPTURE_DRILL_SKIPPED`. Three tests in WP9. |
| H10 | FIXED | §3.10 leg T: audited only for days at or after the epoch day; an earlier day runs in INFO mode (legacy pre-AMEND2 lines are INFO). Positive control: every instrument with ≥ 1 tape QuoteTick row for D must have Depth10 rows. Three tests in WP5. |
| H11a `node_log_unparseable` | FIXED | §3.10 fail-loud list: `ERROR node_log_unparseable` for an instance-id or marker line failing its strict regex. Test `test_unparseable_marker_line_is_error_node_log_unparseable`. |
| H11b AWAITING bytes-only stale | FIXED | §3.8.2: CRITICAL `RECORDER_BYTES_STALE_AWAITING_HEARTBEAT`, delivery-keyed hourly, no restart, no veto. Test `test_awaiting_heartbeat_flat_bytes_raises_critical_without_restart`. |
| H11c live-proof fallback trigger | FIXED | §3.11: fallback timer 14:35Z (ends by 14:40:30, outside the window, not `Persistent`), sharing the own lock with `OnSuccess=`; §6 roll-up trigger; §7(a). Tests `test_live_proof_fallback_timer_is_outside_launch_window_and_not_persistent`, `test_fallback_timer_rolls_up_after_audit_error_exit`. |
| H11d `venue_silent` alert row and §7(d) | FIXED | §3.7.1 WARNING `CAPTURE_VENUE_SILENT` through the outbox; §3.13 (new alert catalogue) row; §7(d) list. Test `test_venue_silent_offers_warning_through_outbox`. |
| H11e delete `_last_depth` | FIXED | §3.4.3 CS-4 no longer stores it. Test `test_strategy_has_no_last_depth_map`. |
| H11f indirect send helpers | FIXED | §3.5.3: AST ban on `close_position`, `close_all_positions`, `market_exit`, `_send_risk_command` under `src/breezy/strategy/**` (0 call sites today), plus a WP0 characterisation test recording dispatch; the ban is lifted only with per-helper dispatch proof. Test `test_no_indirect_send_helper_under_strategy`. |
| H11g leg S "ended" | FIXED | §3.10 leg S: the end of the climate day in local standard time, via the existing `_climate_day_end_ns` (`src/breezy/ingest/records.py:363`, public alias, L-12) and the sites registry offset. Test `test_leg_s_ended_is_end_of_climate_day_in_local_standard_time`. |
| H11h NBP counts as a feed | FIXED | §6: the NBP in-node poll-hang reset is a feed stall heal for the stall leg. |

**Other r4→r5 changes, all consequences of the above:** §0 Round row; §3.1 rows (`frame_clock.py` purpose, `nbm_quantile_actor.py` heal record, new `src/breezy/ingest/records.py` alias, live-proof timer); §3.10 `CAPTURE_AUDIT_ERROR` named; §3.13 alert catalogue (new); §5.1 AUT-6 row (event-string linkage, no new request); §8 five new risk rows; §10 re-scored 90; §11 R-10 and R-11.

**Counts.** 18 review items fixed; 42 test names added (0 removed or weakened); 2 new plan sections (§3.13, §3.14); 2 ARCH readings added (R-10, R-11); 0 ARCH changes requested.

---

## §R6 Disposition (review `docs/plans/backlog/AUTONOMY_2026-10-03/reviews/AUT-1-r5-merged.md`)

**Summary.**
- T1–T4 and L1–L4 (8 items): **8 FIXED, 0 REJECTED.** T3 follows the coordinator ruling exactly.
- No ARCH text is reopened and no new ARCH reading is needed. R-1…R-11 stand.
- Untouched: every README criterion, operator cap, master enablement, the permit, NO-SEND, the exec client (byte-pinned, unedited) and `allow_short`. The new contract test uses an in-process recording sink, never the network.
- No test is weakened, renamed away or `xfail`-ed. Every r5 test is kept and r6 only adds tests. The H6 next-day test still holds, because the r6 retry window is a superset of it.
- H1–H11 are not regressed. The H4 budget and ceiling are unchanged. H6 keeps its exact `event` linkage, and T1 only adds retries of the same event. H7's watchdog exit rule is extended to more CLIs (L2), not altered.

| Item | Disposition | Where / evidence |
|---|---|---|
| T1 | FIXED | §3.14 "Heal-alert retry": each probe re-sends every heal record (last 8 dates, own and node) with no matching `delivered=true` record, using the same `CAPTURE_HEALED_<sha>` event and `attempt_kind=retry`. Node records are re-sent after 600 s. A still-failed re-send exits 1 after the state write. The roll-up reports `heal_alert_undelivered` and its count, and accepts retried deliveries up to `HEAL_ALERT_RETRY_DAYS`. §6 artefact 3, §7(f), §3.13 row, §8 row. Tests `test_undelivered_heal_alert_is_resent_next_probe`, `test_rollup_reports_heal_alert_undelivered`, plus `test_watch_resends_undeliverable_node_heal_record`, `test_resend_failure_exits_nonzero_after_state_write`, `test_retried_delivery_within_retry_days_satisfies_artefact_3`. |
| T2 | FIXED | WP4 merges only with WP8 and activates at WP8's LAUNCH (§3.0, §4 WP4, §5.3, §6 ETA). The outbox is injected as the duck-typed `heal_alert_offer` callable, so ingest never imports runtime (`lint-imports`), and the WP8 hunk wires it (§3.1). If the outbox is absent at heal time, the actor logs CRITICAL `NBM_NBP_HEAL_ALERT_UNDELIVERABLE` and writes the heal record with `alert="undeliverable"`, which T1 re-sends (§3.7.2). Tests `test_nbp_heal_with_absent_outbox_logs_critical_and_writes_undeliverable_heal_record`, `test_heal_alert_offer_returning_false_logs_critical_record_already_written`, `test_actor_without_heal_alert_offer_constructs_unchanged` (WP4), `test_fq_composition_wires_heal_alert_offer_into_nbm_quantile_actor` (WP8). |
| T3 | FIXED (coordinator ruling applied) | Refusal-record payload puts move to option (b): the bounded `AsyncPayloadWriter` thread with a non-blocking `submit`. A full queue is loud (DetectorEvent plus deduplicated CRITICAL) and fails leg B through the missing payload (§3.3.2, §3.4.3 CS-1). The Take path keeps synchronous puts and its ≤ 150 ms benchmark budget, unchanged (WP7). Both options are taken: `CAPTURE_REFUSAL_PATH_P99_BUDGET_MS = 5` is added, **and** the plan documents that refusal puts never block (measured with the writer's fsync held blocked). The runtime out-of-process guard is AUT-6's node-liveness detector (log mtime plus tape advance), named as the stuck-disk signal; AUT-1 asserts it in `test_aut6_node_liveness_detector_covers_log_mtime_and_tape_advance`, which gates WP7 (§3.3.3, §5.1, §5.3, §8). Tests `test_refusal_payload_put_runs_off_event_loop`, `test_refusal_payload_queue_full_is_loud_and_never_blocks`, `test_async_and_sync_put_of_same_payload_converge` (WP1); `test_refusal_path_never_blocks_on_stalled_payload_disk`, `test_take_payload_puts_stay_synchronous_before_submit` (WP7). |
| T4 | FIXED | §3.13 "Event strings": `event` is the bare token, and qualifiers go in `detail`. r5's unnamed rows get names. The closed `CAPTURE_ALERT_EVENTS` tuple and `CAPTURE_EVENT_RE` live in the new `capture_alerts.py`. Contract tests run the real AUT-6 `deliver_with_proof` and the real `AlertOutbox.offer` and assert `event` is verbatim and filename-safe for the outbox name `<ts_ns>_<event>.json`. WP3 and WP8 activation wait on them. Tests `test_capture_events_pass_verbatim_through_real_deliver_with_proof`, `test_capture_events_pass_verbatim_through_real_alert_outbox_offer`, `test_capture_alert_events_are_closed_and_filename_safe`, `test_heal_alert_event_is_prefix_plus_64_lowercase_hex`. |
| L1 | FIXED | §3.3.1 "Downstream readers" and §5.2 AUT-2/AUT-4 rows: `eval_seq` (and `eval_ns`) are read from the stored record and never re-derived. Only R2 recomputes, as a cross-check. Test `test_join_exposes_stored_eval_seq_never_recomputed`. |
| L2 | FIXED | §3.13 "Exit status on a failed delivery": the watch, settlement, drill and drill-guard CLIs exit 1 after their durable work. The guard always SIGCONTs first. Settlement gains its failure alert `CAPTURE_SETTLEMENT_ERROR` (§3.9), so the rule has something to act on. Tests `test_watch_failed_delivery_exits_nonzero`, `test_settlement_failed_delivery_exits_nonzero`, `test_settlement_read_error_sends_critical_and_exits_nonzero`, `test_drill_failed_delivery_exits_nonzero`, `test_drill_guard_failed_delivery_exits_nonzero_after_sigcont`. |
| L3 | FIXED | §3.10 R2 "Identical replay": R2 instantiates the node's own `EvalSeqCounter` (same 4-entry window, same `EVAL_SEQ_REORDER_BASE = 1_000_000`). Test `test_r2_replays_reorder_ordinal_range_and_four_entry_window_identically`, with an eviction and a late frame, requires identical ordinals including one ≥ 1,000,000. |
| L4 | FIXED | §3.10 boot census: the text is pinned to `log_decision("launched", pid=proc.pid)` at `src/breezy/runtime/trade_supervisor.py:1300`, rendered at `:926` under the formatter at `:1035` (read through codegraph at `4b8347a6`); `boot_retry_launched` at `:1633` is covered too. Test `test_supervisor_launched_pid_line_matches_trade_supervisor_1300` drives the real `log_decision` through the supervisor formatter, plus an AST check of the `:1300` call. |

**Other r5→r6 changes, all consequences of the above.** §0 title and Round row; §3.1 rows (`capture_payloads.py`, the new `capture_alerts.py`, `nbm_quantile_actor.py`, the `trade.py` hunk); §3.8.3 re-send pointer; §3.8.5 exit-rule pointer; WP0 item 6 note; WP1 file list; §10 re-scored 94.

**Counts.**
- Review items: 8 fixed.
- Test names: 27 added (distinct names, counted against r5), 0 removed or weakened.
- New modules: 1 (`capture_alerts.py`); 1 new class (`AsyncPayloadWriter`).
- New constants: 5 (`CAPTURE_REFUSAL_PATH_P99_BUDGET_MS`, `CAPTURE_REFUSAL_PAYLOAD_QUEUE_MAX`, `HEAL_ALERT_RETRY_DAYS`, `HEAL_ALERT_RESEND_MIN_AGE_S`, `CAPTURE_EVENT_RE`).
- Alert events: 13 named and 1 added.
- ARCH: 0 readings added, 0 changes requested.
