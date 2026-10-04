# AUT-1 — Data capture: area plan, round 12 (r11 + the r11 review: items 1–7 of `reviews/AUT-1-r11-merged.md`; on frozen ARCH Rev 9.2)

## 0. Header

| Field | Value |
|---|---|
| ID | AUT-1, delivered as **AUT-1a** (Wave 1: offline units, the custom data types, the recorder watchdog) and **AUT-1b** (after AUT-5a merges: strategy hooks, guard, the composition hunk, node-local detectors), per ARCH Rev 9.2 §5.1 (P1-7) |
| Title | Data capture: every decision, order, fill, mark and settlement for every family, joinable on one `decision_id`, persisted through Nautilus's own streaming writer, reconciled daily against independent sources, with native process-level stall detection and self-heal |
| Round | **r12 (2026-10-03).** r1–r11 are unchanged (r11: `docs/plans/backlog/AUTONOMY_2026-10-03/AUT-1-data-capture_plan_r11.md`, sha256 `b1953f8be5fb04a8…`). Input: the merged r11 review (`reviews/AUT-1-r11-merged.md`, sha256 `afd4f2a03fd619ff…`; trading-bot-architect 95, silent-failure-hunter 93, 0 CRIT/HIGH; items 1–7). r12 edits are tagged **(r12, item N)**; §R12 maps every item to where it lands and re-checks every r9–r11 closure. The review's "already verified" list (rotate arithmetic 4500/4680, the single-constant derivation, per-write checks under concurrency and rotation, GM3's `config.json` boot source, the ~38 h blind window) is kept unchanged. Round history: **r11 (2026-10-03).** r1–r10 are unchanged (r10: `docs/plans/backlog/AUTONOMY_2026-10-03/AUT-1-data-capture_plan_r10.md`, sha256 `bb014030da638511…`). Inputs: the merged r10 review (`reviews/AUT-1-r10-merged.md`, sha256 `431b2b67dd89a37a…`: GH1, GM1–GM5, GL1, the ER-7 and ER-9 amendments), AUT-6 r15-final binding build item 7 (`reviews/AUT-6-r15-final.md`, sha256 `8763ac637515a085…`), and erratum E-11 as adopted (`reviews/ARCH-ERRATA-rev9_2.md`). r11 edits are tagged **(r11, <item>)**; §R11 maps every item to where it lands and re-checks every r9 and r10 closure. Round history: **r10 (2026-10-03).** r1–r9 are unchanged (r9: `docs/plans/backlog/AUTONOMY_2026-10-03/AUT-1-data-capture_plan_r9.md`, sha256 `284832516c95418a…`). Inputs: the merged r9 review (`reviews/AUT-1-r9-merged.md`, sha256 `3db71f5bdbb8fc70…`: rulings R-A, R-B, R-C; EH1–EH4, EM1–EM7, EL1, EL2; the errata verdicts) and the cross-plan rulings X-1..X-7 as defined in full in `reviews/AUT-6-r14-merged.md` (sha256 `f7c43d286558ead8…`), which bind AUT-6 r15 under the same text. r10 keeps the AUT-1/AUT-6 ownership split exactly as that file writes it (§3.10.0). r10 edits are tagged **(r10, <item>)**; §R10 maps every item to where it lands. The r8 closures (`reviews/AUT-1-r8-final.md`, `reviews/AUT-1-native-pressure-test.md`) are re-checked in §R10. Round history: **r9 (2026-10-03).** r1–r8 are unchanged. Inputs: r8 (`docs/plans/backlog/AUTONOMY_2026-10-03/AUT-1-data-capture_plan_r8.md`, sha256 `bd7f4d8c8929eb0e…`), the r8 final review (`docs/plans/backlog/AUTONOMY_2026-10-03/reviews/AUT-1-r8-final.md`), and the **Nautilus-native pressure test** (`docs/plans/backlog/AUTONOMY_2026-10-03/reviews/AUT-1-native-pressure-test.md`, sha256 `ffba3f2e258c54b8…`). Its disposition table is a **coordinator ruling**: r9 follows it row by row (§R9). r8's §R3–§R8 history is not repeated; r8 stays the record of those rounds. |
| ARCH consumed | **FROZEN Rev 9.2**: `docs/plans/backlog/AUTONOMY_2026-10-03/reviews/snapshots/ARCH_rev9_2.md`, sha256 `1b288d0e0172b233b791d875845e8002824a52d4a2e7819685ec0f2057572f42` (re-hashed 2026-10-03). Binding errata: `docs/plans/backlog/AUTONOMY_2026-10-03/reviews/ARCH-ERRATA-rev9_2.md` (re-read at the end of drafting: sha256 `148ab3eb00691a55…`), E-1…E-10, E-7a, **E-7b, E-7c** (both adopted while r9 was being written), E-8a. **(r11)** **E-11 is ADOPTED** (SELF_HEAL realised natively by systemd; `ARCH-ERRATA-rev9_2.md` re-read 2026-10-03, sha256 `210593da7c93006f…`), so it binds this plan as adopted text, no longer as a pending dependency. Where a native substitution conflicts with the frozen C1 text, r9 does **not** reinterpret ARCH: it files the exact replacement text in §ERRATA-REQUEST and blocks the affected WPs on adoption (§4 gate G-ERR). Per E-3, Rev 9.2 change tags are written `R9.2-Z1…Z9`. |
| Code baseline | `feat/data-capture-and-risk` @ `f45f5a65` (**r11**: re-checked; HEAD unchanged; **r12**: re-checked 2026-10-03, HEAD unchanged; `NT/persistence/writer.py:240-261` and the quote-tape ingest/retention units re-read for items 1, 4 and 5). Breezy citations were read through codegraph (`projectPath=/home/jon/breezy`) or `sed` on the named file. Nautilus citations are `nautilus_trader 1.231.0` under `/home/jon/breezy/.venv/lib/python3.13/site-packages/nautilus_trader/`, read with `/usr/bin/grep -rn` after a positive control (`live/node.py:39 class TradingNode` found; memory note `grep-tool-is-blind-under-venv`). Below, `NT/` abbreviates that directory. |
| Paths | Repo-root-relative for code, tests and deploy files (repo `/home/jon/breezy`). Runtime paths written `derived/…`, `evidence/…`, `health/…` are under `/home/jon/.local/share/breezy/` (ext4, `findmnt` 2026-10-03). `<capture_root>` is `/home/jon/.local/share/breezy/derived/capture_stream/polymarket_us/`, the trade node's **own** streaming root; its one stream directory per boot is `<capture_root>/live/<instance_id>/`, written by the capture actor's own `StreamingFeatherWriter`, where `<instance_id>` is the trade node's explicit kernel `instance_id` (**r10, R-A, EM5, ER-1**). It is never under the quote-tape root `/home/jon/.local/share/breezy/catalog/quote_tape/polymarket_us/`. `<decisions_dir>` is `/home/jon/.local/share/breezy/catalog/quote_tape/decisions/` (`src/breezy/app/trade.py:774`, unchanged; AUT-1 now writes only `settlement_*.jsonl` there). |
| Current score | 2 |
| Target | 3 |
| Upstream | ARCH-0 (`src/breezy/persistence/autonomy/` schemas, C4 writer, C6 Protocols, `NODE_PLUGINS`, `RefusingPlugin`, `VetoReason`, `pins.py`, `test_autonomy_files_have_one_writer`); AUT-5a (`ResolvedFamily`, `RegistryWatchActor.drill_active`, the `entry_veto` slot, sole owner of `src/breezy/app/trade.py` in Wave 1); AUT-6 (`deliver_with_proof`, the node `AlertOutbox` (claim order per E-1), unit health, the node-liveness detector, the shared bwrap wrapper `deploy/systemd/breezy-autonomy-bwrap` and `AUTONOMY_BWRAP_TABLE` (E-7a); **(r10)** the SELF_HEAL contract and its config/contract tests, the per-kill page through `OnFailure=breezy-autonomy-failed@%n.service` (X-4), storm escalation (X-6) and the deferral WARN (X-7), and erratum E-11; **(r11, GM4)** r15-final build item 7, AUT-6's unit-health and liveness checks treating the recorder's `activating/start` as healthy within the extended start budget); AUT-5 (the E-8 snapshot helper with the E-8a API); AUT-2 (canary producer) |
| Downstream | AUT-2, AUT-3, AUT-4 and AUT-6 consume C1 through the r9 reader projection (§3.9). **Four READY plans cite r8 internals that r9 removes**; §5.3 lists each citation and the brief amendment it needs. |

---

## 1. Goal state

### 1.1 README `AUT-1` score-3 criterion (verbatim; the plan's own scope)

> **Score-3 criterion.**
> - What must be captured, durably, for every family: every decision (including refusals and their reasons), intent, order, fill, cancel, position mark, settlement, the depth snapshot at decision time, and the forecast or model inputs with artefact sha.
> - Every record is schema-versioned and joinable on one decision id.
> - A daily completeness audit runs automatically and alerts on any gap.
> - A recorder hang or an empty feed is detected and self-healed with no human action.
>
> **Live proof:** 7 consecutive UTC days with 100% join completeness for every live fill, from decision to settlement, plus at least one detected and self-healed recorder or feed stall (an injected one is acceptable if no natural stall occurs).

The README live-proof window rule binds it (verbatim):

> A day counts toward any N-day live-proof window only if it has at least one real fill, or a clearly tagged synthetic canary fill that traverses the production path. Zero-fill days do not count, and the window extends. Every window also needs at least 5 real fills, and canary fills never count toward that or any statistic.

**r9's reading of "durably" (coordinator ruling, pressure-test row "fsync durability").** A record is durable once Nautilus's `StreamingFeatherWriter` has flushed it. The writer:
- flushes at most every `flush_interval_ms` (default 1000, `NT/persistence/writer.py:159`);
- flushes only when a later write arrives (`check_flush` is called from `write`, `:278`, `:578-586`);
- never fsyncs (`flush` calls `stream.flush()` only, `:588-594`).

r9 accepts this, and r10 keeps it with two tightenings:
- **(r10, EM4)** Take-path records are flushed synchronously (`writer.flush()`) before `super().submit_order`, so a process crash after a submit cannot lose them; only a host crash can (no fsync).
- **(r10, EL1)** for everything else, a node crash can lose the unflushed tail. The loss is **bounded**: the 60 s tick writes a heartbeat and then calls `writer.flush()`, so the tail is at most about 61 s (§3.4.4), and the audit enforces that bound instead of assuming it. It is also **counted**: the daily audit checks it against an independent denominator, the node log's `SHADOW_DECISION` lines (§3.11, leg R5). A lost Take-path record still fails its fill's join, so the live-proof criterion is never relaxed. Only the mechanism that makes the loss visible changes.

### 1.2 ARCH Rev 9.2 §10 "Area plan obligations", AUT-1 (verbatim)

> **AUT-1:** the `CaptureAdapter` call sites per composable kind; measured C1 volume per day; the `EntryVeto` record writer; the node-local observations behind `feed_stale`, `recorder_stale`, `capture_gap` (source, period, clear condition); the recorder and feed stall observations, naming each unit AUT-6 may restart; the daily join audit with offline intent linkage (P1-3); the payload store and volume (P1-4); the settlement writer (P1-6); `capture_epoch_start`; with AUT-4, the live-vs-batch parity take divergence (38 vs 35); the `Exit` id function and record (P1-8); the `capture_untagged` refusal (P1-9); restarts only via AUT-6 (P1-10, P1-12); `quote_ref` payloads and `wall_ns` (U8, U9).

| Obligation | r9 section | Slice | Errata |
|---|---|---|---|
| `CaptureAdapter` call sites per kind | §3.5 | 1a (adapter), 1b (hooks) | — |
| Measured C1 volume | §3.2 | 1a WP0 | — |
| `EntryVeto` writer | §3.5.3 CS-2, §3.6 | 1b | — |
| `feed_stale`, `recorder_stale`, `capture_gap` | §3.7 | 1b | — |
| Stall observations; units AUT-6 may restart | §3.10 | 1a | ER-8 |
| Daily join audit with offline intent linkage | §3.11 (leg I) | 1a | — |
| Payload store and volume (P1-4) | **replaced** by frame and forecast references plus the Take-path frame copy (§3.3) | 1a | ER-3, ER-10 |
| Settlement writer | §3.12 | 1a | — |
| `capture_epoch_start` | §3.4.5 | 1a library, 1b write | — |
| 38-vs-35 parity divergence (with AUT-4) | §3.14 | 1a WP6 | — |
| `Exit` id function and record (P1-8) | §3.4.1, §3.6.2 | 1a, 1b | — |
| `capture_untagged` refusal (P1-9) | §3.6.2 | 1a, 1b | — |
| Restarts only via AUT-6 (P1-10, P1-12) | §3.10: AUT-1 calls no restart; the recorder's process-level heal is systemd's own `Restart=` on a native watchdog | 1a | ER-8 (reduced, r10), AUT-6 E-11 |
| `quote_ref` payloads and `wall_ns` (U8, U9) | §3.3 (quote frame reference), §3.4.1 (`wall_ns`) | 1a, 1b | ER-4 |

### 1.3 Facts

r8 §1.3 holds unchanged at `f45f5a65`, and r9 relies on these of its rows:
- quote is published before depth for one frame, with a shared `ts_event` (`src/breezy/adapters/polymarket_us/data.py:1590`, `:1599`);
- FQ evaluates on both triggers and drops `source` (`src/breezy/strategy/forecast_quantile_ladder/strategy.py:740-757`);
- `evaluate` latches before any capture code (`decision.py:357`);
- one handler call evaluates exactly one decision;
- the four exit tags (`src/breezy/persistence/exit_tags.py:42-45`);
- `intent_fingerprint` is a pure sha256 over `str()` of six order attributes (`src/breezy/adapters/polymarket_us/exec/submit_chain.py:242-253`);
- the funnel flushes every 15 min (`decision_funnel.py:47`);
- the `submit_order` call sites;
- the `extend_dedupe:` formats;
- the 38-vs-35 divergence;
- the AUT-6 restart rules of ARCH §4.5.

New in r9 (read 2026-10-03):

| Fact | Evidence | Used in |
|---|---|---|
| `Refuse`, `NotExecutable` and `NotDPlus1` carry only `reason`. `Take` carries `p_hat`, `p_lower`, `p_upper` and `ev_net`. The margin is `forecast_margin(h_hours, cfg)`, computed inside `evaluate`. | `src/breezy/strategy/forecast_quantile_ladder/decision.py:129-172`, `:353-355` | §3.5.2 (numeric inputs on refusals) |
| Each evaluation emits exactly one decision-class `SHADOW_DECISION` line (`NotExecutable`, `NotDPlus1`, `Refuse` or `Take`), with no capture dependency. A Take adds exactly one `kind="TrySubmit"` line, and only when `shadow_only=False` (WP0-R7 b). So evaluations = total lines − TrySubmit lines. | `strategy.py:564-581`, `:630-701` | independent denominator (§3.11 R1, R2, R3, R5) |
| The trade node config sets no `streaming`, no `instance_id` and no `DataEngineConfig`. Its exec-client config holds a lambda (`state_store_opener`) and runtime objects (`submit_intent_latch`, `live_trading_permit`, `submit_veto`). | `src/breezy/runtime/node_config.py:945-972` | §3.4.2 (V-2) |
| The recorder already streams natively, with `include_types` (`QuoteTick`, `OrderBookDepth10`, `TradeTick`, …) and daily `SCHEDULED_DATES` rotation. | `src/breezy/runtime/node_config.py:282-295`, `:400-403`, `:606-614` | frame references (§3.3) |
| The recorder samples feed health on the event loop every `_feed_watch_interval_secs`. | `src/breezy/adapters/polymarket_us/data.py:1947-1960` (`_watch_feed` → `sample_feed_health`) | §3.10 (ping site) |
| The NBP actor already logs `NBM_NBP_STALE_CYCLE` on **every** poll past a cycle's deadline, on its existing timer. | `src/breezy/ingest/nbm_quantile_actor.py:142`, `:336-338`, `:415`, `:425-449` | §3.7.2 |
| The recorder unit is `Type=simple`, `Restart=always`, `NotifyAccess=none`, `WatchdogUSec=0`. ExecStart runs python directly, so the main PID is the interpreter. | `systemctl --user show breezy-quote-tape.service` (2026-10-03) | §3.10 |
| The shared venv has no sd_notify library. | `ls .venv/lib/python3.13/site-packages` (no `systemd`, no `sdnotify`) | §3.10 (stdlib datagram; L-51 forbids installs) |
| Venue credentials in the trade config are env-var **names** only. | `src/breezy/adapters/polymarket_us/credentials.py:34-44` | §3.4.2 (config-dump hygiene) |
| On this host, a `Restart=always` crash is journaled as `98e32220…` (process exit), `d9b373ed…` (unit failed) and `5eb03494…` (scheduled restart), all under the invocation id. `Result` describes only the current invocation. | AUT-6 r13 §0 facts (journal JSON, 7 days) | §3.10.3 (heal confirmation from the journal) |

New in r10 (read 2026-10-03, codegraph `projectPath=/home/jon/breezy` and `/usr/bin/grep` under `NT/`):

| Fact | Evidence | Used in |
|---|---|---|
| `_watch_feed` is created at the **end** of `_connect`, after `_initialize_instruments_for_connect()`, which retries `EmptyClimateListingError` for `empty_discovery_retry_secs` of wall time; the recorder sets that to 3600 s. | `src/breezy/adapters/polymarket_us/data.py:1101-1121`, `:1082-1099`; `src/breezy/runtime/node_config.py:349` | §3.10.1 (EH1) |
| `_watch_feed` is a bare `while True` with no try/except; an exception in `sample_feed_health` ends the task. It is created with `self._loop.create_task`, so nothing observes its death. | `data.py:1947-1958`, `:1118-1121` | §3.10.1 (EM2) |
| The data client has `_quotes_published`, `_trades_published` and `_safe_mode`, but **no** phase, no discovered-slug count accessor and no depth counter: a Depth10 is handed to the engine at `:1599` without a count. | `data.py:780`, `:800`, `:868`, `:949`, `:1590-1600`, `:1329` (`_provider_active_slugs`), `:825-826` (`_quote_subscribed_slugs`, `_depth_subscribed_slugs`) | §3.10.1 (EM6) |
| systemd arms `WatchdogSec` only when start-up completes: "The watchdog is activated when the start-up is completed" (systemd.service(5), host systemd 259.5). Under `Type=notify`, start-up completes at `READY=1`; before it, only `TimeoutStartSec` applies. | `man systemd.service`, `WatchdogSec=` | §3.10.1 (EH1 under X-2) |
| The recorder unit today: `Type=simple`, `NotifyAccess=none`, `WatchdogUSec=0`, `TimeoutStartUSec=1min 30s`, `TimeoutStopUSec=2min`, `StartLimitIntervalUSec=0`, `Restart=always`, `RestartPreventExitStatus=2`, no `OnFailure=`. ExecStart is `python3 …/breezy-quote-tape` (python is the main PID). | `systemctl --user show breezy-quote-tape.service`; `deploy/systemd/breezy-quote-tape.service:45-153` | §3.10.2 |
| The 09:00Z rotate runs a **blocking** `systemctl --user try-restart breezy-quote-tape.service` with `TimeoutStartSec=180`. Under `Type=notify` that job completes only at `READY=1`. | `deploy/systemd/breezy-quote-tape-rotate.service` (ExecStart, TimeoutStartSec) | §3.10.2 (rotate bound) |
| The trade node sets no `instance_id`; the recorder sets one explicitly and threads it to its data client. | `node_config.py:957-972` vs `:536-550`, `:587` | §3.4.2 (EM5) |
| `ForecastPoint` is a `Data` subclass registered with `register_arrow` at import; it has no `instrument_id`; `ts_event = cycle_runtime_ns`, `ts_init = available_at_ns`. | `src/breezy/domain/forecast_point.py:248`, `:391-398`, `:675-680` | §3.3.1 (R-B) |
| `NbmQuantileActor._publish` publishes each point with `publish_data(nbm_forecast_point_data_type(), point)` and persists nothing. FQ's quantile vector is built **only** from those bus points (`on_data` → `ForecastQuantileState.push`), and the vector's vintage is the max of its 7 variables' `available_at_ns`. | `src/breezy/ingest/nbm_quantile_actor.py:505-541`; `src/breezy/strategy/ladder_ev/forecast_subscriber.py:190-210`; `src/breezy/strategy/ladder_ev/forecast_state.py:277-294` | §3.3.1 (R-B) |
| The offline NBP derived store dedupes per `(station, cycle_runtime, variable, valid window)` by `max(LastModified, raw_sha256)` and derives `available_at_ns` from HTTP `Last-Modified`, not from the live actor's measured lag. So its vintages differ from what FQ held live, and r9's V-12 premise was false. | `src/breezy/persistence/nbp_derived_store.py:137-142`, `:190-197` | R-B, §R10 (EH2) |
| The writer creates a regular `custom_<snake>` writer for a non-Nautilus class without `instrument_id` (`class_to_filename`, `NT/persistence/funcs.py:39-53`; `writer.py:240-249`). It dedupes by event `id` over its last 10,000 ids (`writer.py:197-204`), and `flush()` is public and flushes every open stream (`:588-594`). | `NT/persistence/writer.py`, `NT/persistence/funcs.py` | §3.4.2–§3.4.4 |
| `Trader._start` starts every actor before any strategy, and `Trader._stop` stops every actor before any strategy. | `NT/trading/trader.py:251-290` | §3.6.3 (writer opened in `on_start`, closed in `on_dispose`) |
| The recorder's truncated tape is already salvaged by the ingest. | `src/breezy/runtime/quote_tape_salvage.py:508` (`salvage_truncated_instance`); `src/breezy/persistence/feather_preflight.py:472-490` (`inspect_feather_file`, `salvage_feather_file`) | §3.9, §8 (EL1) |

New in r11 (read 2026-10-03; `/usr/bin/grep -n` and `sed -n` under `NT/persistence/`, codegraph `projectPath=/home/jon/breezy`, and the unit files):

| Fact | Evidence | Used in |
|---|---|---|
| The writer bumps a table's size **only after** `write_table` succeeds: `self._file_sizes[size_key] += serialized.nbytes` sits inside the `try`, after `writer.write_table(serialized)`. The include filter, the event-id dedupe, a missing writer and an empty serialisation all `return` before it, and an exception is caught and logged without it. | `NT/persistence/writer.py:193-195`, `:197-204`, `:250-255`, `:259-262`, `:264-277`, `:285-288` | §3.4.2 (GM2) |
| `get_current_file_info()` is public and returns `{"size", "creation_time"}` per table key (a plain table-name `str` for regular tables). | `writer.py:613-637` | §3.4.2 (GM2) |
| Rotation is checked **after** the write, inside the same call. `_rotate_regular_file` resets the size to 0 and sets a new `creation_time`; `_create_writer` does the same for a new file. So a sparse table whose previous file was rotated can return from a successful write with size 0, equal to its size before; only `creation_time` tells it apart. | `writer.py:280-284`, `:385-406`, `:466-473` | §3.4.2 (GM2) |
| A connect-time discovery attempt is one `await self._instrument_provider.initialize()`. Between empty attempts the client sleeps `DISCOVERY_RELOAD_FLOOR_SECS = 60`. Nothing inside the client bounds one attempt's wall time. | `src/breezy/adapters/polymarket_us/data.py:1082-1099`, `:287` | §3.10.1 (GM1) |
| An attempt is the `_discover_markets` page loop, which parses instruments from the discovery payload and does no per-slug fetch on this path. It is capped at `MAX_DISCOVERY_PAGES = 50`, and each request has `http_timeout_secs = 10` under a `discovery_requests_per_minute = 6` quota. The real universe is one or two pages. | `src/breezy/adapters/polymarket_us/provider.py:101-113`, `:485-545`, `:668-690`; `config.py:274`, `:277` | §3.10.1 (GM1) |
| Every recorder process start creates one `catalog/quote_tape/polymarket_us/live/<instance_id>/` directory, and the native kernel writes `config.json` into it at writer setup. So the `config.json` mtime is the boot time. On 2026-10-03 there were 72 directories; the three newest `config.json` mtimes were 10-01 09:00:34Z, 10-02 09:00:14Z and 10-03 09:00:17Z (the rotates). | `NT/system/kernel.py:587-611`; `stat` 2026-10-03 | §3.7.4 (GM3) |
| `breezy-station-candidate-register.service` has no timer and no `[Install]` section; only the rotate's `OnSuccess=` starts it. It is `Type=oneshot` with `TimeoutStartSec=600` (live: `TimeoutStartUSec=10min`, `TriggeredBy=` empty). Its run script takes the studies lock with `flock -n`: under contention it runs `--check-staleness` and exits 0, and its `last_folded_day` watermark re-folds any missed day. It alerts when the watermark is more than 2 days old. | `deploy/systemd/breezy-station-candidate-register.service`; `deploy/systemd/station-candidate-register-run.sh`; `deploy/systemd/breezy-quote-tape-rotate.service` (`OnSuccess=`); `systemctl --user show` 2026-10-03 | §3.10.2 (GM5) |
| The rotate unit today has `TimeoutStartSec=180`, `OnFailure=breezy-study-failed@%n.service` and `OnSuccess=breezy-station-candidate-register.service`. Its timer is `09:00:00 UTC`, `Persistent=true`, `AccuracySec=1min`. Other timers in 09:00–10:30Z: `breezy-decision-funnel-digest` (09:20, `flock -n`, 180 s) and `breezy-decisions-retention` (09:25, 300 s). | `deploy/systemd/breezy-quote-tape-rotate.{service,timer}`; `deploy/systemd/*.timer`; `decision-funnel-digest-run.sh:40` | §3.10.2 (GM5) |

---

## 2. L-1 null hypothesis and reuse (every remaining custom component, with Nautilus 1.231.0 evidence)

"Native" means a Nautilus class or extension point used as shipped. "V-n" marks a verify-first premise that WP0 pins with mutation evidence (L-33) before any slice relies on it (L-47).

### 2.1 What Nautilus already provides, and r9 reuses

| Need | Nautilus capability (file:line) | Verdict |
|---|---|---|
| Durable per-decision record | `@customdataclass` (`NT/model/custom.py:31-163`). It builds `to_dict`/`from_dict`/`to_arrow`/`from_arrow` and **registers** the type with `register_serializable_type` and `register_arrow` at decoration time (`:160-161`). Field types are limited to `str`, `bool`, `float`, `int`, `bytes`, `ndarray`, `dict` and `InstrumentId` (`:244-276`); anything else raises `TypeError` at decoration. | **Reuse.** Five record types (§3.4.1). No `Optional` field: null is the empty string for `str` and 0 for `int` (§3.4.1 encoding rule). |
| Publishing a record | `Actor.publish_data(data_type, data)` publishes on the custom-data topic (`NT/common/actor.pyx:2813-2830`). | **(r10, R-A) Not used for AUT-1's custom records.** `CapturePublisher` calls the wrapper directly, so no custom record crosses the bus and no bus handler can raise into a publisher. The bus is still the source for `ForecastPoint`, which `NbmQuantileActor` already publishes (`nbm_quantile_actor.py:540`). |
| Persisting it | `StreamingConfig` (`NT/persistence/config.py:28-73`). `NautilusKernel._setup_streaming` builds a `StreamingFeatherWriter` at `{catalog_path}/{environment}/{instance_id}` and subscribes it to `"*"` (`NT/system/kernel.py:508-509`, `:587-604`). `include_types` filters before any work (`NT/persistence/writer.py:193-195`). A custom type without `instrument_id` gets one regular `custom_<snake>_<ts>.feather` file (`:240-249`, `:457-471`). | **(r10, R-A) Reuse the writer class, not `StreamingConfig`.** The capture actor owns one `StreamingFeatherWriter` on `<capture_root>/live/<instance_id>/` behind a catch-all wrapper (§3.4.2). `StreamingConfig` (option A) is dropped: its kernel `"*"` subscription and its boot-time `config.json` dump (`kernel.py:604-611`) are the two hazards r9 found. |
| Order intent and the `decision_id` carrier | `Order.tags` (`NT/model/orders/base.pyx:218`); `OrderFactory.limit(..., tags=...)` (`NT/common/factories.pyx:246-309`). `OrderInitialized` has a registered Arrow schema carrying `tags`, `client_order_id`, `instrument_id`, `order_side`, `quantity`, `price` and `time_in_force` (`NT/serialization/arrow/schema.py:192-229`; registration `NT/serialization/arrow/serializer.py:468-473`). | **Reuse native.** The streamed `OrderInitialized` replaces r8's `OrderLink`. It is both the link (tag → `client_order_id`) and the intent (the `intent_fingerprint` inputs). V-6 pins the `str()` forms. |
| Fills | `OrderFilled` has a registered Arrow schema (`serializer.py:476-481`). `DurableFillRecord` stays the authoritative fill census (`src/breezy/adapters/polymarket_us/exec/client.py:949-976`). | **Reuse native**, streamed. The exec store stays the independent census. |
| Position marks | Every `PositionEvent` subclass is registered (`serializer.py:508-514`). | **Reuse native.** The reader projects C1 `PositionMark` with the venue leg sign (L-44; §3.9). |
| Per-instrument freshness | `Cache.quote_tick(instrument_id)` (`NT/cache/cache.pyx:3204`). `DataEngine._handle_quote_tick` adds the tick to the cache (`NT/data/engine.pyx:2716`) **before** it publishes (`:2725-2728`). | **Reuse.** Replaces r8's `FrameClock` stamp. V-7 covers the gap: Depth10 is published without a cache write (`:2691-2696`), and the trade node does not set `emit_quotes_from_book_depths` (`NT/data/config.py:71`, default `False`). So a one-sided book that yields no `QuoteTick` leaves the cache stale (§3.7.1). |
| Forecast inputs **(r10, R-B)** | `ForecastPoint` is registered with `register_arrow` at import (`src/breezy/domain/forecast_point.py:675`) and has no `instrument_id`, so the writer gives it one regular `custom_forecast_point_*` file (`writer.py:240-249`). `NbmQuantileActor._publish` already publishes every point on the bus (`nbm_quantile_actor.py:505-541`), and FQ builds its vector only from those points (`forecast_subscriber.py:190-210`). | **Reuse native.** Stream `ForecastPoint`; forecast references resolve inside the boot's own stream (§3.3.1). Replaces r9's `derived/nbp` premise (V-12) and the `FrameCopy.forecast_body` fallback. |
| Order and position event delivery to a capture actor | the `events.order.*` wildcard (the RiskEngine subscribes the same pattern, `NT/risk/engine.pyx:189`); `Actor.msgbus.subscribe` | **Reuse native.** |
| Config encoding for the stream's `config.json` | `register_config_encoding(type_, encoder)` (`NT/common/config.py:223-225`). `msgspec_encoding_hook` consults it (`:172-174`) before raising `TypeError` (`:176`). | **(r10, R-A) Dropped** with option A. There is no config dump, so there is no global `register_config_encoding` call. |
| Process liveness and restart of the recorder | systemd `WatchdogSec=` + `sd_notify("WATCHDOG=1")` + `Restart=` (host systemd 259). The recorder unit already has `Restart=always`. **(r10, X-1, X-2, X-5)** `Type=notify` with `NotifyAccess=all`; `READY=1` once the feed is connected and subscribed; the watchdog is armed at start-up completion (§1.3); `EXTEND_TIMEOUT_USEC=` (sd_notify(3)) carries a legitimately long discovery through the start phase; `OnFailure=` reaches AUT-6's notifier (X-4). | **Reuse native** (pressure-test row "recorder alive but not capturing"). Replaces r8's heartbeat file, `breezy-capture-watch` and `breezy-capture-watchdog`. V-8..V-10. |
| Funnel counts and refusal reasons | `SHADOW_DECISION` lines (`strategy.py:564-581`); `FqDecisionFunnelActor` (`decision_funnel.py`, `app/trade.py:773`) | **Reuse**, read-only, as the independent denominator. |
| Fill and order census, intent linkage | `DurableFillRecord`; `FILL_*`, `VENUE_ORDER_ID_KEY_PREFIX`, `RESOLVER_CONTEXT_KEY_PREFIX` (`client.py:404-454`); `intent_fingerprint` | **Reuse**, read-only, through the E-8 snapshot helper with `take_flock=False` (E-7a rule 3, E-8a). |
| Settlement truth | `read_climate_day_including_corrections` (`src/breezy/persistence/catalog.py:637`) | **Reuse**, inside the settlement unit. |
| Alerts and delivery proof | AUT-6 `deliver_with_proof`; the node `AlertOutbox` | **Consume.** |

### 2.2 Custom components that remain (one L-1 row each)

| Component | Null hypothesis tested | Evidence that the gap is real | Verdict |
|---|---|---|---|
| **`DecisionRecord` numeric inputs on refusals**: `p_hat`, `p_lower`, `p_upper`, `ev_net`, `margin`, `ask_px`, the forecast reference, `artefact_sha256` | "The decision object or the shadow line already carries them." | `Refuse`, `NotExecutable` and `NotDPlus1` carry only `reason` (`decision.py:129-150`). The shadow line is built from `decision_log_fields(decision)` (`decision.py:178`). Nautilus has no notion of a strategy decision. | **Extend minimally.** Additive keyword fields on `Refuse`, set where `evaluate` already computed them (§3.5.2). The record is a `@customdataclass`. |
| **Record of cancel, deny, reject, expire, submit and accept** (`OrderEventRecord`) | "The native stream writes every order event." | Only `OrderInitialized` and `OrderFilled` are registered with `register_arrow` (`serializer.py:468-481`). `OrderDenied` has a schema in `NAUTILUS_ARROW_SCHEMA` (`schema.py:242-252`) but is never registered, so the writer hits `Can't find writer for cls` and returns (`writer.py:250-253`). | **Small msgbus subscriber.** It republishes exactly the event classes **absent from `list_schemas()`** as one `@customdataclass` (§3.6.3). The set is computed at boot from `list_schemas()`, so it holds by construction and never double-writes. |
| **Settlement record** | "A live node sees settlement." | The node has no settlement event for venue weather markets; settlement truth is the NWS CLI, read offline. | **Custom offline unit** reusing `read_climate_day_including_corrections`, unchanged from r8 (§3.12). |
| **NBP silent-feed check and hang reset** | "The NBP actor's timer already detects absence." | `_check_stale_cycle` logs `NBM_NBP_STALE_CYCLE` (`nbm_quantile_actor.py:425-449`), but it raises no delivered alert and exposes no veto input. `_submit` drops the `Future` (`:348-353`), so a hung poll is never reset. | **Extend the existing timer** (§3.7.2): no new timer, no new actor. |
| **Completeness audit** | "Nautilus or an existing Breezy job reconciles capture against an independent source." | No such job exists; the funnel counts are aggregates. | **Custom daily unit**, with `SHADOW_DECISION` as the independent denominator (§3.11). |
| **`decision_id` and `eval_seq`** (`compute_decision_id`, `EvalSeqCounter`) | "Nautilus provides a decision identity." | C1 defines the id; Nautilus has none. | **Pure functions** (§3.4.1). r8's `FrameClock` is deleted; only its pure `EvalSeqCounter` survives, moved into `capture_ids.py`. |
| **`CaptureGuardedStrategy`** (the `capture_untagged` refusal, P1-9) | "The RiskEngine can refuse an untagged order." | The RiskEngine is immutable and checks no tags; Breezy cannot configure a tag rule into it. | **Extend by subclassing**: a `Strategy.submit_order` override that calls `super()`, the same purpose as r8. Its `OrderLink` fsync is removed (§3.6.2). |
| **`capture_epoch_start`** | "Kernel or supervisor records hold the first capture boot." | They hold no capture identity. | **New, minimal** (§3.4.5), unchanged from r8. |
| **Take-path frame copy** (`FrameCopy`) | "The recorder tape always holds the decision's frame." | The recorder is a separate process with its own WebSocket connections and its own gaps (`QuoteTapeGap`, `node_config.py:289-295`). The node cannot observe the tape at decision time, and a Take-path frame missing from the tape cannot be recovered later. | **Copy only on the Take path** (§3.3.2), at most about 10 a day. Refusal records carry references only. r9 flagged this reading; **coordinator ruling R-C adopted it unchanged** (`reviews/AUT-1-r9-merged.md`). |
| **Recorder watchdog gate**: a pure classifier plus stdlib `sd_notify` | "systemd alone detects a live-but-not-capturing recorder." | `Restart=always` sees only a process exit; a zombie with a live loop keeps running (memory note `recorder-hangs-disconnected`). The gate decides **whether to ping**; systemd decides when to kill and restart. | **Minimal** (§3.10.1). **(r10)** It also sends `READY=1` (X-2, X-5) and `EXTEND_TIMEOUT_USEC` during discovery (EH1), applies the launch-window deferral (X-3), and samples exception-safely (EM2). |
| **Recorder stop hook** (`ExecStopPost=`), **evidence only (r10, X-4)** | "The journal and AUT-6's `OnFailure=` notifier already record and page a watchdog kill." | They do page it: under X-4 AUT-6's notifier pages each kill, so the hook loses that duty. But the node-local `recorder_stale` veto runs inside the trade node every 60 s, and the node closure may run no `journalctl` argv and read no other owner's alert records (§3.15). Only a process that runs at the kill can leave a node-readable kill count. The hook is also the one place that sees `SERVICE_RESULT=watchdog` and `$INVOCATION_ID` together at the kill, which keys the stall record to the notifier's `(unit, InvocationID)` page. | **Kept, evidence only** (§3.10.2): it writes the stall record and `recorder_watchdog/v1`, sends nothing, holds no alert credential, and runs `-`-prefixed so it can never change the unit's result. |
| **Adapter-free `intent_fingerprint` and exec-store key prefixes** (`src/breezy/domain/exec_intent.py`) | "The wrapped audit can import them from the adapter." | E-7a makes every AUT-1 unit wrapped, and wrapped units have no import path to the venue adapters (E-7 rule 2; E-7b rejects narrowing it). `intent_fingerprint` lives in `exec/submit_chain.py:242-253`. The key prefixes live in `exec/client.py:404-454`, which is byte-pinned by `test_exec_client_is_byte_identical_to_its_pre_sl13_sha256`. | **Move, AF1/E-7b(a) precedent.** `intent_fingerprint` moves byte-identically into the domain module, and `submit_chain.py` re-exports it as a delegating shim (V-15 first proves that `submit_chain.py` is not byte-pinned). The key prefixes are restated in the domain module, and `tests/unit/autonomy/test_exec_intent_parity.py::test_exec_key_prefixes_equal_client_constants` (a test-only import of `client.py`) pins them equal. `client.py` stays byte-identical. |

---

## §R9 Disposition (`reviews/AUT-1-native-pressure-test.md`, coordinator ruling)

**(r10)** This section is r9's record and is left as written. Where r10 changes an r9 outcome (option A, the stop hook's paging, the forecast reference, `on_stop`), §R10 says so and names the section that now governs.

| # | r8 component | Pressure-test disposition | r9 outcome | Where |
|---|---|---|---|---|
| 1 | Refusal reason per decision | Reuse `SHADOW_DECISION` and the funnel | **Reused** as the audit's independent denominator (R1, R2, R3, R5). The `DecisionRecord` still carries `reason` (C1). | §3.11 |
| 2 | Custom JSONL `CaptureWriter`: fsync, short-write recovery, tail check, byte cap, failure journal, `.INCOMPLETE` markers | `@customdataclass DecisionRecord` via `publish_data`, plus `StreamingConfig` on the trade node's own root | **Removed.** Replaced by five `@customdataclass` types (§3.4.1), one publish wrapper (§3.4.3) and `StreamingConfig(catalog_path=<capture_root>)` (§3.4.2). Gone with it: `capture_writer.py`, the tail check, the `partial_line`/`torn_tail` classes (replaced by Arrow stream truncation), the 64 MiB cap, the `incomplete/` journal and the markers. | §3.4 |
| 3 | Payload store: `derived/capture_payloads/…`, `PayloadStore`, the `AsyncPayloadWriter` thread, the pending map, `payload_status`, collision handling | References: `(instrument_id, ts_event)` into the recorder's `order_book_depths`, and `(station, cycle_ns)` for forecasts. Copy only when the tape lacks the frame. | **Removed.** Records carry `frame_kind`, `instrument`, `frame_ts_event`, `forecast_station` and `forecast_cycle_ns`. **Copy rule:** the node cannot see the tape at decision time (§2.2). It therefore copies the frame (`FrameCopy`) for **Take-path records only**, where a miss would break a fill's join irrecoverably. Refusals never copy; an unresolved refusal reference is counted (leg R6). **Flagged:** this narrows "only when the tape lacks it". The coordinator may rule instead that Takes never copy either, which would make the live-proof join depend on recorder coverage (WP0 V-11 measures that coverage). | §3.3 |
| 4 | Custom `OrderLink`, `LifecycleEvent` and `PositionMark` writers; the lifecycle actor's per-event records | Native streaming plus `Order.tags` | **Removed.** `OrderInitialized`, `OrderFilled` and every `PositionEvent` are streamed natively through `include_types`. The C1 logical records are reader projections (§3.9). | §3.4.2, §3.9 |
| 5 | Cancel/deny | Small msgbus subscriber | **Kept**, generalised by construction to every order-event class absent from `list_schemas()`. | §3.6.3 |
| 6 | Settlement writer | Custom record reusing the corrections reader | **Kept** unchanged (r8 §3.9). | §3.12 |
| 7 | Recorder heartbeat file, `breezy-capture-watch`, `breezy-capture-watchdog`, `capture_watch/v1`, `restart_request`, the heal handshake through AUT-6 | systemd `WatchdogSec` + `sd_notify`, sent only while the counters advance, with `Restart=on-watchdog` | **Removed.** The recorder pings only while its own counters and on-disk bytes advance (§3.10.1). `WatchdogSec=600` triggers the kill, and the existing `Restart=always` (a superset of `on-watchdog`) restarts it. A stop hook delivers the CRITICAL and writes the stall record (§3.10.2). The audit confirms the heal and sends `CAPTURE_HEALED_<sha>` (§3.11.6). The watchdog's other duties move into the audit and live-proof units, which check each other daily, plus AUT-6's unit health (§3.11.5). Needs ER-8. | §3.10 |
| 8 | NBP feed silent | A check on the existing actor timer | **Kept and moved** onto `NbmQuantileActor.on_cycle_timer`, beside the hang reset. | §3.7.2 |
| 9 | `FrameClock` | `Cache.quote_tick(iid).ts_init`; verify that the cache is populated before the handler runs | **Removed.** Freshness reads the cache. Its pure `EvalSeqCounter` stays in `capture_ids.py`, because C1's `eval_seq` needs it. V-7 covers the quote path and records the depth-only gap. | §3.7.1 |
| 10 | fsync on Take-path records | Accept the ~1 s flush with no fsync; count the loss in the audit | **Accepted.** A 60 s heartbeat bounds the unflushed tail; leg R5 counts every lost record against `SHADOW_DECISION`. | §1.1, §3.4.4, §3.11 |

Components the pressure test does not name are kept, minus their r8 coupling to the removed writer:
- the guard (§3.6.2);
- the on-change rule (C1, L-29);
- `decision_id` and `eval_seq`;
- the epoch;
- the 38-vs-35 attribution;
- the heal-alert linkage, now carried by the audit;
- the weekly drill, now with no AUT-5b dependency (§3.10.4).

**r8-final binding items, re-applied to r9:**

| Item | r9 status |
|---|---|
| MEDIUM §3.15 AST closure boundary: AUT-1 path globs only; cross-unit write modules imported only through named read-only functions; a non-literal `open` mode or `os.open` flags fail closed; reason values are constants; state whether a `capture_gap` refusal cites payloads | **Applies** to the smaller module set (§3.15). On the last point: a `capture_gap` refusal record cites the triggering frame **by reference** and never carries a `FrameCopy`. It is not a Take-path record that reached the order path (§3.3.2). |
| LOW heal age-out (`heal_alert_unabandoned_count`; a loud line for unmarked heals older than `today−30`) | **Applies**, now in the audit (§3.11.6). |
| LOW `on_stop` fact drain | **Moot**: the payload thread and its fact queue are removed. It is replaced by a binding item with a test: the capture actor's `on_stop` publishes its final heartbeat inside `try/except` before the writer closes (§3.6.3). |
| LOW stale wording; align `recorder_liveness` with `recorder_stale` | **Applies**: the only detector name is `recorder_stale` (§3.7.4). WP briefs re-grep for "r8" and "r7". |
| LOW `test_payload_collision_is_critical` on the caller side | **Moot**: there is no payload store. |
| LOW the watch-actor closure belongs to AUT-5; `node_observations.py` is AUT-1's node-side non-writer | **Applies** (§3.15). |
| E-9 multi-command oneshots | **Applies**: no AUT-1 oneshot has more than one start command. The recorder unit gains `ExecStopPost=`, bounded by `timeout -k` within `TimeoutStopSec` (§3.10.2). |
| The AST check is an allowlist, not a denylist (AUT-6 r9 AC6 ruling) | **Applies** (§3.15). |
| E-7a universal bwrap; WAL reads via the snapshot helper; the AST check is a lint | **Applies** (§3.13, §3.15). |
| E-7c (added to `reviews/AUT-1-r8-final.md` during r9): the shared wrapper provides a private `--tmpfs /tmp` with `TMPDIR` | **Applies.** pyarrow and the reader's scratch writes use it (§3.13). |
| **New in r9 (not raised by any reviewer): the venue-adapter import-closure rule under E-7a/E-7b** | r8's audit imported `intent_fingerprint` from `src/breezy/adapters/polymarket_us/exec/submit_chain.py` and the key prefixes from the byte-pinned `exec/client.py`. r8's WP6 reruns `scripts/analysis/nbp_shadow_parity.py`, which imports `breezy.adapters.polymarket_us.symbology`; per AUT-6 r13 §0 fact (20), that pulls in 33 adapter modules. Once every AUT-1 unit is wrapped, both break the closure rule. r9's fix: `src/breezy/domain/exec_intent.py` (§2.2, §3.1, WP0 V-15, WP5) and the E-7b(a) dependency for WP6 (§3.14). |

---

## 3. Design

### 3.0 Slices (ARCH §5.1)

| Slice | Contents | Starts | Depends on |
|---|---|---|---|
| **AUT-1a** | WP0 premises; WP1 record types, ids, stream reader and projection; WP2 FQ adapter and guard library; WP3 recorder watchdog gate, stop hook and unit edits; WP4 NBP timer check and hang reset (built in Wave 1, **merged with WP8**); WP5 settlement, audit and live-proof; WP6 parity attribution | Wave 1, against ARCH-0 stubs | ARCH-0; AUT-6 (`deliver_with_proof`, the wrapper; **r10:** the `OnFailure=` notifier and E-11 before WP3 step 2); errata adoption for WP1 and WP5 (G-ERR) |
| **AUT-1b** | WP7 FQ hooks and the re-base on the guard; WP8 capture actor, node-local detectors, epoch, `StreamingConfig` wiring and the composition hunk; WP9 weekly drill | After AUT-5a merges | AUT-5a; AUT-6 (outbox, node-liveness detector) |

### 3.1 Module map (layering: app > analysis > strategy > runtime > adapters > ingest > persistence|registry|normalize > settlement > domain)

| Module | Layer | New/edit | Purpose | Slice |
|---|---|---|---|---|
| `src/breezy/persistence/autonomy/capture_records.py` | persistence | new | the five `@customdataclass` types (§3.4.1), `NULL_STR = ""`, `capture_data_types()` | 1a |
| `src/breezy/persistence/autonomy/capture_ids.py` | persistence | new | `compute_decision_id`, `compute_exit_decision_id`, `compute_orphan_decision_id`, `EvalSeqCounter` (pure; moved from r8's `frame_clock.py`), `frame_ref_of`, `forecast_ref_of` | 1a |
| `src/breezy/persistence/autonomy/capture_on_change.py` | persistence | new | `OnChangeFilter` (pure, shared by the node and audit R2), unchanged from r8 | 1a |
| `src/breezy/persistence/autonomy/capture_publish.py` | persistence | new | `CapturePublisher`: writes the custom records **directly** through the stream wrapper (no `publish_data`; R-A), the Take-path flush (EM4), the per-type flat check (EH4) and `health` (§3.4.3) | 1a |
| `src/breezy/persistence/autonomy/capture_stream.py` | persistence | new | **(r10, R-A)** `CaptureStreamWriter`, the catch-all wrapper around one native `StreamingFeatherWriter` (`open(cache, clock)`, `write(obj) -> bool`, `flush() -> bool`, `close()`, `table_bytes() -> dict[str, int]`, per-table counters); `CAPTURE_INCLUDE_TYPES` (now with `ForecastPoint`); `open_canary_writer(root, cache, clock)` (§5.2). r9's `capture_streaming_config` is deleted. | 1a |
| `src/breezy/persistence/autonomy/capture_reader.py` | persistence | new | `read_capture_stream(boot_dir)`; `project_c1(...)` (views of `DecisionRecord`, `OrderLink`, `LifecycleEvent`, `PositionMark`, `DetectorEvent`); `join_fills_to_decisions`; `resolve_frame_ref` (§3.9). **(r10)** Torn-tail classification reuses `breezy.persistence.feather_preflight.inspect_feather_file`. | 1a |
| `src/breezy/analysis/capture_forecast_ref.py` | analysis | new | **(r10, R-B)** `resolve_forecast_ref(stream, station, cycle_ns, available_at_ns)`: rebuilds the vector from the boot's streamed `ForecastPoint`s through FQ's own `ForecastQuantileState` push rule. It lives in analysis because analysis may import strategy and persistence may not. | 1a |
| `src/breezy/persistence/autonomy/capture_alerts.py` | persistence | new | `CAPTURE_ALERT_EVENTS`, `CAPTURE_EVENT_RE`, `heal_alert_event(sha)`, `abandoned_alert_event(sha)` (the r8 §3.13 rules) | 1a |
| `src/breezy/persistence/autonomy/capture_epoch.py` | persistence | new | `write_epoch_once`, `read_epoch` (unchanged from r8) | 1a |
| `src/breezy/persistence/autonomy/capture_schedule.py` | persistence | new | `LAUNCH_WINDOW_UTC`, `launch_window_guard` (unchanged from r8; ARCH-0's equivalent wins if one exists) | 1a |
| `src/breezy/persistence/exit_tags.py` | persistence | edit | `DECISION_ID_TAG_PREFIX` (L-12) | 1a |
| `src/breezy/strategy/autonomy_capture/guarded_strategy.py` | strategy | new | `CaptureGuardedStrategy(Strategy)` | 1a (library) |
| `src/breezy/strategy/autonomy_capture/capture_actor.py` | strategy | new | `CaptureActor(Actor)` **(r10)**: opens the `CaptureStreamWriter` in `on_start`; subscribes the wrapper to `events.order.*`, `events.position.*` and the `ForecastPoint` topic; counts native events per type (EM3); runs the 60 s tick (heartbeat, `flush`, per-type check); runs the detectors; writes the epoch; writes the final heartbeat and closes the writer in `on_dispose` | 1b |
| `src/breezy/strategy/autonomy_capture/node_observations.py` | strategy | new | NODE_LOCAL detectors `capture_writer_health` and `recorder_stale` (vetoing) and `md_feed_freshness` (**observation only, r10 EM7**); non-writer | 1b |
| `src/breezy/strategy/forecast_quantile_ladder/capture_adapter.py`, `plugin.py` | strategy | new | `FqCaptureAdapter` (C6), `CaptureContext`; FQ's `NODE_PLUGINS` entry | 1a |
| `src/breezy/strategy/forecast_quantile_ladder/decision.py` | strategy | edit | additive keyword fields on `Refuse` (§3.5.2); `decision_log_fields` output byte-identical | 1b (WP7) |
| `src/breezy/strategy/forecast_quantile_ladder/strategy.py` | strategy | edit | the base class; CS-0..CS-5 (§3.5.3) | 1b |
| `src/breezy/domain/exec_intent.py` | domain | new | `intent_fingerprint` (moved byte-identically) and the exec-store key prefixes the audit reads; no adapter import | 1a (WP5) |
| `src/breezy/adapters/polymarket_us/exec/submit_chain.py` | adapters | edit | `intent_fingerprint` becomes a re-export of `breezy.domain.exec_intent.intent_fingerprint` (delegating shim; `client.py` is untouched) | 1a (WP5) |
| `src/breezy/ingest/nbm_quantile_actor.py` | ingest | edit | retain the `Future`; the hang reset; `missed_cycles(now_ns)`; the stale-cycle alert offer; the heal record (§3.7.2). **(r10, R-B)** `_publish` is unchanged and persists nothing; streaming the points is the capture actor's job. | 1a (built), merged with WP8 |
| `src/breezy/ingest/records.py` | ingest | edit | the public alias `climate_day_end_ns` (r8, for leg S) | 1a |
| `src/breezy/adapters/polymarket_us/recorder_watchdog.py` | adapters | new | `RecorderSample`; `classify_recorder_sample(...)` (pure, including the launch-window deferral, X-3); `sd_notify(message) -> bool` (stdlib `AF_UNIX` datagram); **(r10)** `RecorderWatchdogPinger` (the ping task: `EXTEND_TIMEOUT_USEC` while starting, `READY=1` once, `WATCHDOG=1` while OK; exception-safe sampling, EM2); the marker constants `RECORDER_WATCHDOG_DEFERRED`, `RECORDER_SAMPLE_FAILED`, `RECORDER_WATCHDOG_WITHHELD`; the timing constants pinned to the unit file. **(r11, GH1)** The bound constants `DISCOVERING_GRACE_S = 300`, `CONNECT_BUDGET_S = 300`, `START_EXTEND_S = 120`, `STOP_HOOK_BOUND_S = 12`, `ROTATE_MARGIN_S = 30` and **(r11, GM1)** `DISCOVERY_ATTEMPT_BUDGET_S = 180`, plus the pure functions `recorder_max_start_s(...)` and `rotate_timeout_start_s(...)` (§3.10.2) | 1a |
| `src/breezy/adapters/polymarket_us/{config,data}.py` | adapters | edit | opt-in `watchdog_notify: bool = False` on the data-client config. **(r10, EH1, EM6)** The pinger task is created at the **top** of `_connect`, and `READY=1` is requested right after the initial subscription reconcile. New read-only accessors: `phase`, `phase_started_ns`, `discovered_slugs`, `subscribed_count`, `depths_published` (a new counter at `data.py:1599`), `last_discovery_reload_ns`, `last_scheduled_reload_delay_secs`, `feed_watch_alive`, and **(r11, GM1)** `discovery_attempt_inflight_since_ns`. **(r11, GL1)** The pinger task is held in `self._watchdog_pinger_task`, and `_connect` creates one only if none is running. `sample_feed_health` is not changed. | 1a |
| `src/breezy/runtime/node_config.py` | runtime | edit | `build_quote_tape_node_config` sets `watchdog_notify=True`. **(r11, GH1)** It defines the one rotate-bound constant, `QUOTE_TAPE_ROTATE_TIMEOUT_START_SECS = rotate_timeout_start_s(QUOTE_TAPE_MAX_START_SECS)`, and `QUOTE_TAPE_MAX_START_SECS = recorder_max_start_s(QUOTE_TAPE_EMPTY_DISCOVERY_RETRY_SECS)` (runtime may import adapters; §3.10.2). **(r10, R-A, EM5)** `build_trade_node_config(..., instance_id: UUID4 \| None = None)` sets the kernel `instance_id` when one is given; the default `None` leaves every existing caller's config unchanged. There is no `StreamingConfig`. | 1a (recorder), 1b (trade) |
| `src/breezy/runtime/capture_recorder_hook_cli.py` | runtime | new | the evidence-only `ExecStopPost=` hook (§3.10.2; X-4) | 1a |
| `src/breezy/runtime/capture_stall_drill_cli.py` | runtime | new | the weekly SIGSTOP drill and its guard (§3.10.4) | 1b (WP9) |
| `src/breezy/analysis/capture_settlement{,_cli}.py` | analysis | new | the settlement writer (r8 §3.9) | 1a |
| `src/breezy/analysis/capture_audit{,_cli}.py`, `capture_node_log.py`, `capture_heal.py` | analysis | new | the daily audit, the streaming node-log parser, heal confirmation and heal-alert retries | 1a |
| `src/breezy/analysis/capture_live_proof{,_cli}.py` | analysis | new | the 7-day roll-up | 1a |
| `src/breezy/analysis/capture_parity_attribution.py` | analysis | new | the 38-vs-35 attribution (r8 §3.12) | 1a |
| `src/breezy/app/trade.py` | app | one hunk, after AUT-5a | **(r10, EM5)** generate the trade node's `instance_id` once and pass it to `build_trade_node_config` and to `CaptureActor`; construct the identity, publisher, adapter and `CaptureActor` in `_compose_forecast_quantile_ladder`; pass the outbox offer into `NbmQuantileActor` | 1b |
| `deploy/systemd/breezy-quote-tape.service` | deploy | edit | **(r10, X-1, X-2, X-4, EH1)** `Type=notify`, `NotifyAccess=all`, `WatchdogSec=600`, `WatchdogSignal=SIGTERM`, `TimeoutStartSec` per AUT-6's rule, `OnFailure=breezy-autonomy-failed@%n.service`, `ExecStopPost=-…` (§3.10.2). **WP3 step 2 only.** | 1a |
| `deploy/systemd/breezy-quote-tape-rotate.service` | deploy | edit | **(r11, GH1)** `TimeoutStartSec=` the literal value of `QUOTE_TAPE_ROTATE_TIMEOUT_START_SECS` (**4680** at the recorder's base `TimeoutStartSec=180`), so the blocking `try-restart` survives a listing-hole start that reaches `READY=1` late (§3.10.2). r10's "4200" in this row was wrong; no number is now written anywhere except as derived from that constant. WP3 step 2 only. | 1a |
| `deploy/systemd/breezy-capture-{settlement,audit,live-proof,stall-drill,stall-drill-guard}.{service,timer}` | deploy | new | §3.13 | 1a/1b |

**Deleted from r8's map (never built):**
- modules: `capture_writer.py`, `capture_payloads.py`, `capture_watch_state.py`, `frame_clock.py` (its counter moves to `capture_ids.py`), `lifecycle_actor.py` (replaced by `capture_actor.py`), `src/breezy/runtime/capture_watch{,_cli}.py`, `src/breezy/runtime/capture_watchdog{,_cli}.py`;
- units: `breezy-capture-watch` and `breezy-capture-watchdog`.

Entry points are `/home/jon/breezy/.venv/bin/python3 -m <module>`. There is no console script, because adding one needs a reinstall into the shared venv (L-51).

### 3.2 Volume (obligation "measured C1 volume")

r8's measurements stand: 973,921 FQ evaluations over 7 h on 10-02/03 gave 59 on-change records, and UTC day 10-01 had 3,288,397 evaluations, 2 Takes and 2 TrySubmits.

| Stream table (`<capture_root>/live/<instance_id>/`) | Rows per day (projection) |
|---|---|
| `custom_decision_record_*` | ≈ 250 on-change, plus every Take and TrySubmit |
| `custom_frame_copy_*` | ≤ the Take-path records, ≈ 3–10 |
| `custom_order_event_record_*` | ≈ 5 per order × 2–5 orders |
| `custom_detector_event_*` | < 50 (transitions) |
| `custom_capture_heartbeat_*` | 1,440 (one per 60 s), plus one at `on_dispose` |
| `custom_forecast_point_*` (**r10, R-B**) | ≈ subscribed stations × 7 variables × polled cycles; WP0 measures it (expected < 500) |
| `order_initialized_*`, `order_filled_*`, `position_*` (native) | ≈ 20 |

That is under 2,000 rows and 2 MB a day. WP0 re-measures one full UTC day. There is no byte cap: the native writer has none, and adding one would create a second failure mode. Above 20,000 rows a day, the volume is revisited in a reviewed commit before WP8 activates.

**Bus cost (r10, R-A).** There is no `"*"` subscription. The wrapper is subscribed only to `events.order.*`, `events.position.*` and the `ForecastPoint` topic, which carry tens of messages a day; market-data frames never reach it. r9's V-4 (per-message overhead) is dropped with option A. **Retention (r10, EL2):** none is required at this volume (under 3 MB a day, about 1 GB a year); stream files are never deleted (ER-2). Above 20,000 rows a day, the volume and a retention owner are revisited in a reviewed commit.

### 3.3 Frame and forecast references (replaces the payload store; ER-3, ER-4)

#### 3.3.1 References

- **Frame reference:** `frame_kind ∈ {"depth10", "quote", ""}`, `instrument` (str) and `frame_ts_event` (int).
  - A depth-triggered decision cites `("depth10", iid, depth.ts_event)`.
  - A quote-triggered decision cites `("quote", iid, tick.ts_event)`. U8's reason stands: the quote arrives before its depth (`data.py:1590`, `:1599`).
  - `Exit` cites `("", instrument, 0)`.
- **Resolution** (`capture_reader.resolve_frame_ref`) tries these in order:
  1. a `FrameCopy` in the same boot's stream with the same `decision_id`;
  2. the recorder catalog: the `order_book_depths` row (or the `quote_tick` row) for `instrument` with `ts_event == frame_ts_event` (`node_config.py:289-295` streams both, and the ingest converts them);
  3. otherwise, `UNRESOLVED`.
- **Forecast reference (r10, R-B):** `forecast_station` (str), `forecast_cycle_ns` (int) and `forecast_available_at_ns` (int): the `(station, cycle_ns, available_at_ns)` of the `ForecastQuantileVector` that `evaluate` used (`src/breezy/strategy/ladder_ev/forecast_state.py:277-294`; the vector's `available_at_ns` is the max of its 7 variables' vintages).
  - **The inputs are streamed natively.** `ForecastPoint` is in `CAPTURE_INCLUDE_TYPES`, and the capture actor's wrapper is subscribed to the topic `NbmQuantileActor._publish` already publishes on. Each boot's stream therefore holds every point FQ pushed in that boot (§1.3: FQ builds its vector only from bus points). `NbmQuantileActor` itself is unchanged and persists nothing.
  - **Resolution inside the stream.** `resolve_forecast_ref` (`src/breezy/analysis/capture_forecast_ref.py`) takes the same boot's `ForecastPoint` rows for `station` with `cycle_runtime_ns == cycle_ns` and `available_at_ns ≤ forecast_available_at_ns`, replays them in stream order through a fresh `ForecastQuantileState` (FQ's own push rule, so a reissue overwrites exactly as it did live), and requires the complete vector's `available_at_ns` to equal `forecast_available_at_ns`. Otherwise the result is `UNRESOLVED`.
  - **Why not the derived NBP store.** It dedupes differently, by `max(LastModified, raw_sha256)` per key, and derives `available_at_ns` from `Last-Modified` (`src/breezy/persistence/nbp_derived_store.py:137-142`, `:190-197`), so its vintages are not the ones FQ held. r9's V-12 premise and the `FrameCopy.forecast_body` fallback are removed.
  - **Ordering premise.** The capture actor subscribes in `on_start`, actors start before strategies (`NT/trading/trader.py:251-271`), and `NbmQuantileActor`'s first poll is an asynchronous task that publishes only after its fetch completes (`nbm_quantile_actor.py:286-300`). So no point FQ consumes is published before the subscription exists. WP0 V-12 pins this (§4).
- **Artefact:** `artefact_sha256` and `manifest_sha256`, unchanged from C1.

#### 3.3.2 The Take-path copy (`FrameCopy`)

- **When.** It is written for `Take`, `TrySubmit`, `EntryVeto` and `Exit`, the records whose loss breaks a fill's join. There is one `FrameCopy` per distinct `decision_id`, published **before** the Take's `DecisionRecord`. A reader that sees the Take therefore sees its copy, subject to the shared flush.
- **Body.** `frame_body` (dict → Arrow string) is the canonical JSON of the triggering frame: the Depth10 levels with size > 0 (`ts_init` excluded), or `{ask, bid, ts_event}` for a quote (C1 U8's quote content).
- **Refusals never copy.** A refusal with an unresolved reference is counted per day (leg R6); it is not a fill-join failure. A `capture_gap` refusal (§3.6.2) is a guard record on an order that never reached the venue. It is not a Take-path record, so it cites by reference.
- **Tape corroboration (leg B).** When the tape also holds the frame, the audit requires the copy to equal it: top of book for a quote, all levels for depth. A mismatch is `frame_copy_mismatch` FAIL. WP0 V-11 measures the tape's coverage of node frames over 14 days, and that sets how a tape miss on a copied Take is reported: INFO if coverage is below 99.9%, WARNING otherwise.

### 3.4 Records and persistence

#### 3.4.1 Record types (`capture_records.py`)

All five types are `@customdataclass` (`NT/model/custom.py:31`). `ts_event` and `ts_init` are the decorator's own fields. `ts_init` is the wall clock at publish, which is C1's `ts_ns` (ER-4).

**Encoding rule:**
- `str` for decimals and nullable strings, with `NULL_STR = ""` meaning null;
- `int` for nanoseconds and counters, with 0 meaning null only where stated;
- `bool` for `drill`.

No field is named `instrument_id`. A field with that name makes the writer route the type to a per-instrument file and **silently drop** it whenever `cache.instrument(...)` returns None (`writer.py:210-239`). The field is called `instrument`, and the reader projects it to C1's `instrument_id` (ER-4).

| Type | Fields (besides `ts_event`, `ts_init`) | `ts_event` |
|---|---|---|
| `DecisionRecord` | `schema`, `decision_id`, `family_id`, `node_boot_id`, `build_sha`, `registry_seq: int`, `drill: bool`, `source` (`live`\|`canary`), `kind` (`Take`\|`Refuse`\|`NotExecutable`\|`NotDPlus1`\|`TrySubmit`\|`EntryVeto`\|`Exit`), `reason`, `eval_ns: int`, `eval_seq: int`, `wall_ns: int`, `station`, `climate_day` (ISO), `rung_id`, `side`, `instrument`, `ask_px`, `frame_kind`, `frame_ts_event: int`, `p_hat`, `p_hat_raw`, `p_lower`, `p_upper`, `ev_net`, `margin`, `forecast_station`, `forecast_cycle_ns: int`, `forecast_available_at_ns: int` (**r10, R-B**), `artefact_sha256`, `manifest_sha256` | `eval_ns` |
| `FrameCopy` | `schema`, `decision_id`, `frame_kind`, `instrument`, `frame_ts_event: int`, `frame_body: dict` (**r10, R-B:** `forecast_body` removed) | `frame_ts_event` |
| `OrderEventRecord` | `schema`, `decision_id` (from the order's tags; otherwise the exit or orphan id), `event_type` (class name), `client_order_id`, `venue_order_id_sha256`, `reason`, `node_boot_id`, `drill: bool`, `source` | the event's `ts_event` |
| `DetectorEvent` | `schema`, `detector`, `observation_sha256`, `state` (`AGREE`\|`DISAGREE`\|`UNKNOWN`), `node_boot_id`, `drill: bool`, `source` | publish time |
| `CaptureHeartbeat` | `schema`, `node_boot_id` (= the kernel `instance_id`, EM5), `seq: int` (monotone per boot), `final: bool` (true only for the `on_dispose` heartbeat), `records_written: int` (cumulative per boot, all types), **(r10, EM3, EH4)** `written_by_type: dict` (cumulative per boot, keyed by table name, covering the custom types, `ForecastPoint` and the native `OrderInitialized`, `OrderFilled` and `Position*` tables; **(r11, GL1)** a snapshot taken immediately **before** this heartbeat's own write, so it **excludes** the heartbeat carrying it: `written_by_type["custom_capture_heartbeat"]` counts only the earlier heartbeats of the boot), `write_failures: int`, **(r11, GM2)** `write_drops: int` (cumulative per boot), `health_ok: bool`, `health_cause` | write time |

- **Schema values:** `capture_decision/v2`, `capture_frame_copy/v1`, `capture_order_event/v1`, `capture_detector_event/v2`, `capture_heartbeat/v1`. The v2 bumps mark the storage change from r8's JSONL `v1` design, which was never shipped. r10 amends field sets of never-shipped versions, so no version moves. The exact-set rule (ARCH §3 common rules) is pinned by `test_capture_record_field_sets_are_exact`.
- **Ids.** `decision_id`, `eval_seq` and the id-bearing rules for TrySubmit, EntryVeto and Refuse are r8 §3.3.1, unchanged:
  - `compute_decision_id(family_id, manifest_sha256, artefact_sha256, station, climate_day, rung_id, side, eval_ns, eval_seq)`;
  - `EvalSeqCounter.next(instrument_id, ts_event)` counts per frame across the quote and depth handler calls (R-10), with r8's 4-entry retention and `EVAL_SEQ_REORDER_BASE = 1_000_000`;
  - `compute_exit_decision_id` hashes the four exit tag values only (P1-8).
- **Payload hygiene (ARCH §3).** No custom record carries an absolute path, an env value, an account id or a raw venue order id; it carries `venue_order_id_sha256` only. The native `OrderFilled` rows do carry a raw `venue_order_id`; ER-6 states that exemption.

#### 3.4.2 The stream writer (r10, R-A: option B is the design)

**Ruling R-A.** Option B ships: an actor-owned native `StreamingFeatherWriter` behind a catch-all wrapper, with `CapturePublisher` calling the wrapper directly for the custom records. Option A (`StreamingConfig` on the trade node) is dropped, and with it V-2 (the config-dump `TypeError`), V-4 (the `"*"` bus overhead) and the global `register_config_encoding`. L-1 still holds: the writer class, its Arrow schemas, its rotation and its file format are Nautilus's own, used as shipped.

**`CaptureStreamWriter` (`capture_stream.py`).**
- **Construction.** It is built at composition time with `root=<capture_root>`, `instance_id` (EM5) and `include_types=CAPTURE_INCLUDE_TYPES`. `open(cache, clock)` is called in `CaptureActor.on_start` and constructs `StreamingFeatherWriter(path=<capture_root>/live/<instance_id>, cache=cache, clock=clock, include_types=CAPTURE_INCLUDE_TYPES, rotation_mode=RotationMode.SCHEDULED_DATES, rotation_interval=1 day, rotation_time=00:00, rotation_timezone="UTC")`, with the recorder's rotation constants (`node_config.py:400-403`). Actors start before strategies (§1.3), so the writer is open before the first strategy handler. A `write` before `open` returns False and counts as a failure (`health.ok=False`); the guard then refuses BUYs with `capture_gap`.
- **`write(obj) -> bool`** wraps `StreamingFeatherWriter.write(obj)` in `try/except Exception`. That covers `serialize_batch`, which sits outside the writer's own try block (`writer.py:259`). It never raises into a caller or a bus handler (L-16). On success it increments `written_by_type[class_to_filename(type)]`; on an exception it increments `write_failures` and sets `health.ok=False` with `cause=write_exception:<table>`. Native events are counted once per event `id`, using the same bounded window as the writer's own dedupe (`writer.py:197-204`), so a count matches the rows the writer can emit (EM3; V-17).
- **Per-write landing check (r11, GM2).** The writer swallows its own write errors and drops silently in three places (§1.3, r11 facts), so a returned call proves nothing. Around each judged call, the wrapper reads the native public `get_current_file_info()` (`writer.py:613-637`) for the object's table key before and after `StreamingFeatherWriter.write(obj)`.
  - **Success** means the table's `(size, creation_time)` pair changed. The writer bumps `size` only after `write_table` succeeds (`writer.py:264-277`). A rotation inside the call resets `size` to 0 but always sets a new `creation_time` (`:385-406`, `:466-473`), so a rotation counts as success even when the size returns to its earlier value. That case is real for a sparse table rotated on an earlier day.
  - **(r12, item 1) First write to a lazily created table.** For a `custom_` table with no writer yet, the native `write` creates the writer **before** serialising (`writer.py:240-245` calls `_create_writer`, which sets `_file_sizes[table]=0` and a fresh `_file_creation_times[table]`, `:463-473`), and only then runs `serialize_batch` (`:259`) and `write_table` (`:264`). An empty serialisation (`:261-262`) or a swallowed `write_table` exception (`:285-288`) on that first call therefore still changes the pair from *absent* to `(0, t)`, which the rule above would read as success. So: **if the table key was absent before the call, success additionally requires `size > 0` after it.** An absent-before key with `size == 0` after is a drop. Residual, fail-closed: a first write whose call also crosses a `SCHEDULED_DATES` boundary (rotation resets `size` to 0, `:405-406`) is counted as a drop although the row landed in the closed file; that needs the first write of a table in a boot to coincide with 00:00Z, it only refuses a Take (never an exit), and `write_drops` names it in R5.
  - **A drop** means the pair is unchanged, or the table key is absent both before and after (the missing-writer path, `:250-255`), or **(r12, item 1)** the key was absent before and the size is 0 after. The wrapper increments `write_drops` and `write_drops_since_submit_flush`, sets `health.ok=False` with `cause=write_dropped:<table>`, and returns **False**. A drop is counted, never retried.
  - **Not judged**, so never a drop: a class outside `CAPTURE_INCLUDE_TYPES` (the writer's include filter returns first, `:193-195`), and a native event whose `id` is already in the wrapper's mirror of the writer's dedupe window. The wrapper is the writer's only caller, and it inserts into its mirror on exactly the writer's condition (a `UUID4` `id`) with the same 10,000-id `OrderedDict` bound, so the mirror is exact (`:197-204`). Neither case increments `written_by_type`.
  - **Key shape.** Every `CAPTURE_INCLUDE_TYPES` table is a regular table whose key is the plain table-name string: no field is named `instrument_id` (§3.4.1), and no included native table is in `_per_instrument_writers` (`writer.py:136-146`). V-19 pins this.
  - **Cost.** Two dict builds over at most about 14 writers per judged write, inside `CAPTURE_PATH_P99_BUDGET_MS` (WP7 measures it). No `lstat` is involved.
- **`flush() -> bool`** wraps the native `flush()` (`writer.py:588-594`). An exception gives False and `health.ok=False` (`cause=flush_exception`).
- **`table_bytes() -> dict[str, int]`** sums `lstat().st_size` over the regular files `<table>_*.feather` in its own directory, per table, refusing symlinks. It is one `scandir` over at most about 14 files. **(r11, GM2)** Because it sums **every** file of a table, closed and open, the 00:00Z `SCHEDULED_DATES` rotation (a new file beside the closed one) never reads as flat (`test_midnight_rotation_is_not_type_bytes_flat`).
- **`close()`** flushes and closes, inside try/except.
- **Subscriptions** (made by `CaptureActor.on_start`, all to the **same** wrapper handler): `events.order.*`, `events.position.*`, and the `ForecastPoint` custom-data topic, whose exact string WP0 V-12 pins from a publish-and-receive probe. There is no `"*"` subscription, no data command and no venue subscription (L-45).
- **The custom records never cross the bus.** `CapturePublisher.write(record)` calls `CaptureStreamWriter.write(record)` directly (§3.4.3).

`CAPTURE_INCLUDE_TYPES = [DecisionRecord, FrameCopy, OrderEventRecord, DetectorEvent, CaptureHeartbeat, ForecastPoint, OrderInitialized, OrderFilled, *PositionEvent.__subclasses__()]`.

**Why V-1 still holds by construction.**
- The list references the classes, so importing `capture_stream.py` imports `capture_records.py` and `domain/forecast_point.py`.
- Those imports run `@customdataclass` and the module-scope `register_arrow` (`forecast_point.py:675`), which register each schema **before the writer exists**.
- `list_schemas()` returns the live global dict (`serializer.py:85-86`), and the writer captures that dict at construction (`writer.py:129`). WP0 pins this with a test.

**Root.**
- `<capture_root>` is a new 0700 directory under `derived/`, and the stream directory is `<capture_root>/live/<instance_id>/`, the same layout the kernel would have used (`kernel.py:589`). AUT-2's canary uses `<capture_root>/canary/<instance>/`.
- It is never under `/home/jon/.local/share/breezy/catalog/quote_tape/`. So the quote-tape ingest, the recorder's disk monitor and its retention never see it (`test_capture_root_is_disjoint_from_quote_tape_root`).
- No `config.json` is written (that was the kernel's option-A dump), so ER-6's config clause is dropped.

**V-3 (kept, re-targeted).** `test_streamed_native_event_serialisation_never_raises` serialises every included native type, and `ForecastPoint`, from recorded FQ events (tags, NO-leg instruments, resolver fills). Under option B a failure no longer unwinds into execution, because the wrapper catches it. But a type that can never serialise would latch `capture_gap` permanently, so WP0 must know before WP8. `test_msgbus_handler_exception_unwinds_into_publisher` (`component.pyx:2832-2834`) stays as the characterisation that justifies the catch-all wrapper. r9's handler-order test is dropped: there is no kernel writer.

#### 3.4.3 The publisher (`CapturePublisher`)

- `write(record) -> bool` calls `CaptureStreamWriter.write(record)` (R-A). It never raises (L-16).
- **On False:**
  - `health.ok = False`;
  - log `CAPTURE_PUBLISH_FAILED family=<id> type=<t> cause=<exc class>`;
  - offer CRITICAL `CAPTURE_PUBLISH_FAILED` through the outbox, deduplicated per cause per 300 s with the suppressed counts logged (the r8 H8 rule);
  - return False.
- **`flush_for_submit() -> bool` (r10, EM4).** It calls `CaptureStreamWriter.flush()` synchronously. The guard calls it after the Take-path records are written and before `super().submit_order` (§3.6.2 step 5). Its cost is inside `CAPTURE_PATH_P99_BUDGET_MS` (WP7 measures it). **(r11, GM2)** It also returns False when `write_drops_since_submit_flush > 0`, that is, when any judged write of any table dropped since the previous `flush_for_submit`, and then resets that counter. So a dropped Take-path record refuses the Take even if the drop happened in the same handler call as the guard. (Step 4's `health.ok` check catches it too; this makes the guarantee local to the flush.)
- **Positive control.** `health.ok` is cleared only on a 60 s tick where the `CaptureHeartbeat` was written, `flush()` returned True, and the per-type check (§3.4.4) passed.

#### 3.4.4 Bounded loss, made visible

- **Forced flush.** On each 60 s tick the actor writes the `CaptureHeartbeat` and then calls `flush()`. Every record counted in that heartbeat is therefore flushed by the time the tick ends, and the unflushed tail at a crash is at most about 61 s. Take-path records are flushed before their order is submitted (EM4), so they are never in that tail.
- **Per-type landing check (r10, EH4; replaces r9's bytes-total check).**
  - On each tick, after the flush, the actor reads `table_bytes()`.
  - For every table, it compares `written_by_type[table]` and the table's bytes against their values `TYPE_FLAT_WINDOW_S = 180` s earlier.
  - Any table whose count rose while its bytes did not grow sets `health.ok=False` with `cause=type_bytes_flat:<table>`, which raises `capture_gap`. It publishes `DetectorEvent(capture_writer_health, DISAGREE)` with `obs.cause=type_bytes_flat`, `obs.table=<table>`, and offers CRITICAL `CAPTURE_STREAM_TYPE_FLAT` once per table per boot.
  - Why per type: the heartbeat's own writes keep the byte total growing, so r9's total hid a single table's loss. The writer drops records silently in three places: the swallowed write error (`writer.py:284-288`), an empty serialisation (`:261`) and a missing writer (`:250-253`). Each leaves its table's count rising and its file flat.
  - A table with no records in the window is not judged. The heartbeat table judges itself.
  - **(r11, GM2)** The per-write landing check (§3.4.2) catches a drop on the write that suffers it. This window-level check stays as the independent second detector: it catches bytes that never reach the file even though the writer's bookkeeping advanced, for example a buffered stream that never flushes.
  - A hung filesystem that blocks the `lstat` is the r8 §3.3.3 case. AUT-6's node-liveness detector (log mtime plus tape advance) catches it from outside, and `test_aut6_node_liveness_detector_covers_log_mtime_and_tape_advance` gates WP8.
- **Counted loss (audit leg R5, r10 per type).**
  - **A boot with a `final=true` heartbeat** (clean `on_dispose`): for every table, the rows present must equal that heartbeat's `written_by_type[table]` exactly, except the heartbeat table, whose rows equal its count **+ 1** (the final heartbeat itself; **r11, GL1**).
  - **A boot without one** (a crash): for every table, the rows present must be at least the last flushed heartbeat's `written_by_type[table]`, and the heartbeat table at least that count + 1. A shortfall is `stream_record_lost` FAIL.
  - **(r11, GM2)** Per-write drops are already counted in the boot (`write_drops`). R5 reports the last heartbeat's `write_drops`, and any non-zero value FAILs the day as `stream_write_dropped`, even when the row counts reconcile. A dropped record never entered `written_by_type`, so R5's arithmetic alone cannot see it.
  - **The tail (r10, EL1).** Records missing from the stream that appear as `SHADOW_DECISION` lines after the last heartbeat count as `lost_in_flush_window` only if (a) the boot has ended without its disposal line (a crash), and (b) the line's `now_ns` is at most `FLUSH_WINDOW_S = 61` s older than the boot's last node-log line. Anything older is `stream_record_lost` FAIL, because the tick's flush should have landed it. Counted tail records are reported in `records_lost_in_flush_window` at INFO.
  - They still fail leg D if they were a filled order's Take-path records.

#### 3.4.5 `capture_epoch_start`

Unchanged from r8 §3.3.5:
- the file is `evidence/capture/epoch/<family_id>.json`, opened `O_CREAT|O_EXCL|O_NOFOLLOW`, mode 0444;
- `CaptureActor.on_start` writes it on the first boot of a build that composes the family with capture;
- the audit runs the `epoch_missing`, `epoch_rewritten` and `epoch_unlogged` checks.

### 3.5 `CaptureAdapter` and the FQ call sites (obligation 1)

#### 3.5.1 Kinds

Unchanged from r8 §3.4. Only `forecast_quantile_ladder` has full plug-ins. The CRH kinds carry `RefusingPlugin` and are refused at `_compose_family`, so their send sites are declared unreachable (§3.6.5).

#### 3.5.2 Numeric decision inputs on refusals

- **New fields.** WP7 adds **keyword-only fields with `None` defaults** to `Refuse` in `decision.py`: `p_hat`, `p_lower`, `p_upper`, `ev_net` and `margin`.
  - `evaluate` sets each one at every refusal site that comes after its computation. For example, at `below_margin` (`:353-355`), `forecast_margin` and the probabilities are already in hand.
  - `NotExecutable` and `NotDPlus1` return before any of them is computed, so their records carry `NULL_STR`.
- **The shadow line stays byte-identical.** `decision_log_fields` is not changed, so the R1/R2 parsers and the funnel are unaffected. `test_shadow_line_bytes_unchanged_by_refuse_input_fields` checks this over a fixture of every refusal reason.
- `test_refuse_input_fields_equal_the_values_evaluate_compared` asserts that, for `below_margin`, the recorded `ev_net` and `margin` reproduce the refusal (`ev_net ≤ margin`).
- Every existing `tests/strategy/forecast_quantile_ladder/*` test stays green unedited.

#### 3.5.3 FQ call sites (AUT-1b)

| # | Site | Change |
|---|---|---|
| CS-0 | `_safe_evaluate` (`strategy.py:740-757`) | pass `trigger=source`, `depth` and `quote` into `_evaluate_instrument_update` |
| CS-1 | `_evaluate_instrument_update` (`:759-819`) → `_evaluate_with_capture(...)` | Read the vector once and run `evaluate`. Emit the shadow line as today. Then take `eval_seq = counter.next(instrument_id, ts_event)` for **every** evaluation, and call `OnChangeFilter.admit(key, kind, reason, eval_ns)`. Only if it is admitted, build and write the `DecisionRecord` (a Take writes its `FrameCopy` first). **(r10, R-B)** The record carries `forecast_station`, `forecast_cycle_ns` and `forecast_available_at_ns` from the vector `evaluate` used, or `NULL_STR`/0 when no vector was read. Return `(decision, decision_id)`. `evaluate_snapshot` keeps its signature, and production never takes its `capture_ctx=None` branch (`test_production_trigger_paths_pass_capture_ctx`). |
| CS-2 | `_maybe_submit`, `_emit_decision_outcome` (`:646-709`) | If `decision_id is None` (the Take's publish failed), refuse with `capture_gap` before `try_submit`. `_emit_decision_outcome` takes `now_ns` once, for both the line and the record's `wall_ns`. It publishes one of: `TrySubmit`; `EntryVeto` for a refusal in the closed `VetoReason` set (**the `EntryVeto` writer**, on-change per key); or `Refuse(instrument_vanished_after_trysubmit)` with the Take's id. |
| CS-3 | `order_factory.limit(...)` (`:680-688`) | `tags=list(self._capture_adapter.order_tags(decision_id))`; `self.submit_order(order)` goes through the guard |
| CS-4 | `on_order_book_depth`, `on_quote_tick` (`:713-738`) | pass the frame through to `_safe_evaluate`. **No stamp**: r8's `FrameClock` is deleted, and freshness comes from the cache (§3.7.1). |
| CS-5 | `shadow_only=True` (`:659-665`) | CS-1 already captured the Take; no order |

**Pinned timestamps** (C1 U9, R9.2-Z9, unchanged):
- Every record's `eval_ns` is the handler's frame `ts_event`.
- A TrySubmit, a post-Take `EntryVeto` or a `Refuse` copies the Take's `eval_ns` and `eval_seq`, and carries its own `wall_ns`, equal to its shadow line's `now_ns` (`:701`).

### 3.6 Node-side order path

#### 3.6.1 Construction (C8)

`CaptureGuardedStrategy.__init__(self, config, *, capture_publisher: CapturePublisher, alert_outbox: AlertOutbox, …)`. Both arguments are keyword-only, non-Optional and type-checked, so the boot fails closed (`test_capture_guarded_strategy_without_publisher_refuses_construction`).

#### 3.6.2 `submit_order` (P1-8, P1-9)

1. **Exit.** If all four exit tags are present, write `DecisionRecord(kind="Exit")` and its `FrameCopy`, flush (step 5's call, which never refuses an exit), then call `super()`.
   - The `Exit` id comes from the four tags; `frame_kind=""` and `frame_ts_event=0`. The `FrameCopy` holds the order's price only.
   - If a tag is missing or a publish fails, still call `super()`, publish `DetectorEvent(… exit_capture_gap)` and raise a CRITICAL.
2. **Untagged SELL.** Publish `DetectorEvent(… untagged_sell)`, raise a CRITICAL, then call `super()`. The reader assigns the orphan id (`compute_orphan_decision_id`) to the native `OrderInitialized` that has no tag, so the audit fails the fill as `untagged_order` (D12).
3. **BUY tag check.** A BUY needs exactly one `breezy:decision_id=` tag of 32 lowercase hex characters. Otherwise:
   - refuse with `capture_untagged` and do not call `super()`, so the order never reaches the cache;
   - log `CAPTURE_REFUSED reason=capture_untagged` and raise a CRITICAL;
   - publish `EntryVeto` if the tag names a Take of this boot, else `DetectorEvent(… untagged_buy)` (r8 R-4).
4. **Health.** If `capture_publisher.health.ok` is False, refuse with `capture_gap` (same logging and record).
5. **Flush (r10, EM4).** Call `capture_publisher.flush_for_submit()`. For a BUY, False refuses with `capture_gap` (same logging and record) and `super()` is not called. For an `Exit`, False raises a CRITICAL and `super()` is still called: exits are never refused. **(r11, GM2)** False covers both a failed flush and any per-write drop since the previous submit flush (§3.4.3).
   - **Checked against the live-proof rules.** This is fail-closed capture. A refused Take places no order, so it creates no fill and no fill-join gap. It is logged `CAPTURE_REFUSED reason=capture_gap` and recorded as a guard `EntryVeto`, which R1 matches. A refusal never relaxes the 7-day join criterion or the ≥ 5-real-fill rule; it can only delay accrual. The one way it could starve the window is a drop rule with false positives. So V-19 (§4) proves zero drops on the four non-drop paths (dedupe, include filter, rotation reset, first write of a lazily created custom table) and one drop on each of the three silent paths. Any persistent drop latches `capture_gap`, and `CAPTURE_PUBLISH_FAILED` pages it.
6. Call `super().submit_order(...)`. r8's fsynced `OrderLink` is gone: Nautilus publishes `OrderInitialized` itself, and the capture actor's wrapper streams it.

`submit_order_list` runs steps 1–4 for each order, refuses the whole list if any BUY fails, then flushes once (step 5) before `super()`. r8's tests are unchanged.

#### 3.6.3 `CaptureActor` (replaces r8's lifecycle actor; r10, R-A)

- **Config.** `CaptureActorConfig` carries `node_boot_id`, which is the trade node's kernel `instance_id` value (EM5). `trade.py` generates that `UUID4` once and passes it to `build_trade_node_config(..., instance_id=...)` and to this config, as the recorder already does (`node_config.py:536-550`). `test_capture_node_boot_id_equals_kernel_instance_id` asserts `node.kernel.instance_id.value == node_boot_id` on the production composition (L-55).
- **`on_start`:**
  - call `CaptureStreamWriter.open(self.cache, self.clock)`, inside try/except (a failure leaves `health.ok=False`);
  - call `write_epoch_once`;
  - compute `UNSTREAMED_ORDER_EVENTS = {cls for cls in OrderEvent subclasses if cls not in list_schemas()}` once (`test_unstreamed_set_is_computed_from_list_schemas`). On 1.231.0 it contains `OrderDenied`, `OrderCanceled`, `OrderRejected`, `OrderExpired`, `OrderSubmitted`, `OrderAccepted` and the rest, and never `OrderInitialized` or `OrderFilled`;
  - `msgbus.subscribe` the one handler `_on_bus_message` to `events.order.*`, `events.position.*` and the `ForecastPoint` topic;
  - `clock.set_timer("aut1-capture-tick", 60 s)`.

  There is no `subscribe_*` command and no venue subscription (L-45).
- **`_on_bus_message`** (catch-all; never raises):
  - Every message goes to `CaptureStreamWriter.write`. The writer's `include_types` drops the classes it does not stream, and the wrapper counts the ones it does (EM3: `OrderInitialized`, `OrderFilled`, `Position*`, `ForecastPoint`).
  - If `type(event) in UNSTREAMED_ORDER_EVENTS`, it also writes an `OrderEventRecord`. Its `decision_id` comes from `self.cache.order(event.client_order_id).tags`: the entry tag, the exit id or the orphan id. `OrderAccepted` supplies `venue_order_id_sha256`. A streamed type never gets an `OrderEventRecord` (`test_order_event_record_never_duplicates_a_streamed_type`).
- **The 60 s tick** (catch-all): write a `CaptureHeartbeat` (with `written_by_type`), call `flush()`, run the per-type check (§3.4.4), evaluate the detectors, and write `DetectorEvent`s on transitions.
- **`on_stop`:** `flush()` only, inside try/except. Actors stop before strategies (`NT/trading/trader.py:273-290`), so closing the writer here would drop the strategies' stop-time records and cancels.
- **`on_dispose`** (runs after every strategy has stopped): write the `final=true` `CaptureHeartbeat`, then `flush()`, then `close()`, each inside its own try/except. The final heartbeat is always written before the writer closes. This is the r8-final LOW (drain before close, exception-safe), re-targeted: `test_capture_actor_on_dispose_writes_final_heartbeat_before_close_exception_safe` and `test_capture_actor_on_stop_flushes_without_closing`.
#### 3.6.4 Hot path (C6, W9)

- There is no fsync on the event loop.
- CS-1's admitted path costs a dict lookup, one sha256 and one or two direct wrapper writes (an Arrow serialisation and a buffered file write). A Take adds one `FrameCopy`, and the guard adds one synchronous `flush()` before `super().submit_order` (**r10, EM4**).
- r8's `CAPTURE_TAKE_TO_SUBMIT_P99_BUDGET_MS` and `CAPTURE_REFUSAL_PATH_P99_BUDGET_MS` become one budget, `CAPTURE_PATH_P99_BUDGET_MS = 5`. WP7 measures it over 1,000 synthetic Takes (**including the flush**) and 10,000 refusals, against a real `CaptureStreamWriter` on a scratch ext4 directory. A result above it blocks the merge; the budget is never raised.
- `test_guarded_submit_latency_independent_of_webhook` is unchanged.

#### 3.6.5 Every send path is guarded or unreachable (D4)

Unchanged from r8 §3.5.3: `test_every_strategy_submit_site_is_guarded_or_unreachable`, `_UNREACHABLE_SEND_SITES` with its companion tests, and `test_no_indirect_send_helper_under_strategy`.

### 3.7 Node-local observations (obligation 4; AUT-1b)

Every **vetoing** observation here is a C6 `Detector(kind=NODE_LOCAL)` with action `ENTRY_VETO`, called by AUT-5a's `entry_veto(instrument_id)` slot. **(r10, EM7)** `md_feed_freshness` is the exception: it is observation-only and never vetoes (§3.7.1). Each vetoing one:
- auto-clears;
- publishes a `DetectorEvent` per transition (CS-2 is the sole writer of slot-refusal `EntryVeto`s);
- starts in veto until its first good observation;
- vetoes at call time when its last evaluation is older than `WATCH_TICK_STALE_S` (180 s).

`test_try_submit_reachable_only_from_frame_handlers` (r8 D14) still pins that every veto query happens while a fresh frame is being handled.

#### 3.7.1 Market-data freshness (`md_feed_freshness`): observation only (r10, EM7)

**Why it never vetoes.** Every veto query happens while a fresh frame for that instrument is being handled (D14, `test_try_submit_reachable_only_from_frame_handlers`), and the quote is cached before the handler runs (V-7). So a per-instrument staleness veto could never fire on a frame path. A depth-only instrument has no cached quote at all (V-7). r9's per-instrument veto was therefore vacuous, and r10 keeps the per-instrument reading as an observation only. `feed_stale` vetoes come from the NBP check (§3.7.2).


| Source | Period | Trigger | Clear |
|---|---|---|---|
| `self.cache.quote_tick(i).ts_init` (`cache.pyx:3204`) | 60 s tick | **Per instrument (observation only):** the count of instruments whose cached quote is older than `MD_SILENCE_S` (the r8 WP0-derived formula) goes into the observation as `quotes_stale`. **Venue-wide (observation only):** among instruments with a cached quote, if the stale fraction exceeds `MD_SILENT_FRACTION_MAX = 0.5`, publish `DetectorEvent(md_feed_freshness, DISAGREE)` with `obs.cause=venue_silent` and offer WARNING `CAPTURE_VENUE_SILENT`. Instruments with no cached quote are counted as `quote_absent` in the observation. | a newer quote; the fraction back at or under the limit |

#### 3.7.2 `feed_stale` from NBP: the silent-feed check on the existing timer (AUT-1a, ingest)

All of this runs inside `NbmQuantileActor.on_cycle_timer` (`nbm_quantile_actor.py:336-338`). There is no new timer.

- **Hang reset.**
  - `_submit` keeps the `Future` it gets back (`:348`).
  - On the timer, a future still not done after `NBP_POLL_HANG_S` is cancelled. The threshold is at least 2 × the `BulletinFetcher` timeout pinned in WP0, default 600 s.
  - The actor then sets `counters["poll_hang_reset"] += 1`, logs `NBM_NBP_POLL_RESET cycle_ns=<n>`, and submits a fresh `poll_once()`.
- **Silent-feed check.**
  - `missed_cycles(now_ns)` counts the configured cycles (`(1, 13, 19)`, `:122`) after the newest complete cycle whose `cycle_ns + stale_deadline` has passed.
  - This is the same deadline `_check_stale_cycle` already logs as `NBM_NBP_STALE_CYCLE` (`:142`, `:425-449`).
  - On the first timer fire past a cycle's deadline, the actor offers CRITICAL `NBP_CYCLE_MISSED` through `alert_offer`, once per cycle.
  - `alert_offer` is keyword-only, `Callable[[str, str, str], bool] | None = None`. It is duck-typed, so ingest never imports the runtime outbox.
- **Veto.** FQ's NODE_LOCAL `nbp_feed_freshness` reads `missed_cycles(now)` at call time.
  - `≥ 2` missed cycles, or no complete vector for a subscribed station, gives the `feed_stale` veto.
  - Exactly 1 gives an alert only.
  - It clears on a newer complete cycle.
- **Heal record.** A reset followed by `FQ_VECTOR_COMPLETE` for that cycle:
  - writes the write-once record `evidence/capture/heal/<date>/<ts_ns>_node_nbm_quantile_actor.json` (`decided_by:"nbm_quantile_actor"`, `observation_sha256`, `alert`);
  - then offers INFO `CAPTURE_HEALED_<observation_sha256>`.

  If `alert_offer` is absent or returns False, the actor logs CRITICAL `NBM_NBP_HEAL_ALERT_UNDELIVERABLE` and writes `alert="undeliverable"`. The audit re-sends it (§3.11.6).
- **Merge** with WP8 only. The r8 r6-T2 rationale stands: the outbox wiring rides in the same composition hunk.

#### 3.7.3 `capture_gap`

| Source | Period | Trigger | Clear |
|---|---|---|---|
| `CapturePublisher.health` | each write; each Take-path flush; 60 s tick; call time | **(r10)** any write exception, a failed flush, a write before `open`, or `type_bytes_flat:<table>` (§3.4.4, EH4); **(r11, GM2)** or a per-write drop `write_dropped:<table>` (§3.4.2), since the last positive control | the next tick whose heartbeat was written, whose `flush()` returned True and whose per-type check passed |

#### 3.7.4 `recorder_stale`

| Source | Period | Trigger | Clear |
|---|---|---|---|
| (1) `health/recorder_watchdog/polymarket_us.json` (`recorder_watchdog/v1`; only the stop hook writes it, §3.10.2), single read (`O_NOFOLLOW`, 4 KiB, exact key set). **(r11, GM3)** (2) The recorder's native boot markers: one `scandir` of `/home/jon/.local/share/breezy/catalog/quote_tape/polymarket_us/live/`, then one `lstat` (`follow_symlinks=False`) of `<dir>/config.json` for each directory whose own mtime is at or after the trading-day start. **(r12, item 4)** The directory mtime is a **pre-filter only**, never the count: a boot is counted when its **`config.json` mtime** is inside the trading day, and the newest boot marker is the newest such `config.json` mtime. The pre-filter is a safe superset: creating `config.json` sets the directory's mtime at least that late, and later entry changes only move it later. The 15-minute quote-tape ingest does exactly that to old directories, creating and unlinking dotfile markers inside `live/<instance_id>/` (`src/breezy/runtime/quote_tape_ingest_core.py:304-305`, `:407-437`, `:485-502`), so a directory mtime inside the day does **not** mean a boot. Nautilus's kernel writes `config.json` once per recorder process start (§1.3, r11 facts). Read-only; no new writer, no `systemctl` and no `journalctl` from the node. | 60 s tick | `max(watchdog_kills_trading_day, recorder_boots − RECORDER_ROTATE_BOOTS_EXCUSED) ≥ RECORDER_WATCHDOG_STORM_KILLS = 3`, **and** the newer of `last_watchdog_kill_ns` and the newest boot marker is younger than `RECORDER_STALE_CLEAR_S = 1800`; or the hook file exists but is unparseable. **(r12, item 3)** `recorder_boots` = the number of `config.json` boot markers in the trading day. It counts **every** recorder process start, whatever its cause: the 09:00Z rotate, watchdog kills, crashes, exits during a venue outage, and manual restarts. `RECORDER_ROTATE_BOOTS_EXCUSED = 1` subtracts the one rotate. (r11 called this `recorder_restarts_unexplained`; the name implied a cause filter that does not exist, so r12 renames it.) | 1800 s with no further watchdog kill. That is longer than one full gate horizon (the maximum `STREAM_SILENCE_S`) plus `WatchdogSec`, so a recorder that was still broken would have been killed again inside the window. A missing file means no kill has ever happened, so it does not veto. |

**(r11, GM3) Why a second source.** A hook that fails, or that `timeout -k` kills, leaves **no stall record and no count** for that kill (§3.10.2). Without another source, `recorder_stale` would stay blind to that kill until the next day's leg W FAILs it. The boot-marker count closes the intraday half of that window from evidence the recorder's own unmodified Nautilus kernel already writes. It is restrictive only. **(r12, item 3)** `recorder_boots` counts **all** restarts, not only watchdog kills: a crash loop, a manual restart, and a recorder that exits and restarts repeatedly during a venue outage. A crash loop is a stall too. A manual restart can at worst add a 30-minute veto. A venue outage that cycles the recorder vetoes BUYs while it lasts plus `RECORDER_STALE_CLEAR_S`; that is the intended direction (no tape, no Take), and it never refuses an exit. `test_recorder_boots_counts_venue_outage_restarts_and_vetoes` pins it with a fixture of four boot markers inside one trading day from a venue-outage restart loop, with **no** stall records: `recorder_boots == 4`, `cause=boot_count`, veto set, exits allowed. **(r12, item 4)** `test_boot_count_uses_config_json_mtime_not_dir_mtime`: an old directory whose mtime an ingest marker write moved into the day, with an old `config.json`, is not counted. **(r12, item 5)** If WP0 V-23 finds a unit that moves or compresses `live/<instance_id>/` directories, the boot count can only **under**count (a moved boot is missed); that is the safe direction for a restrictive veto because the hook file remains the primary source, and V-23 records it. The observation records `cause ∈ {hook_count, boot_count}`, both numbers, and a `scan_error` flag; a scan error never clears a veto that the hook file sets. `test_recorder_stale_counts_boots_when_hook_record_missing` (renamed in r12 from `…_counts_unexplained_boots_…`; never built) and `test_rotate_boot_is_excused_once` pin it.

**(r10, X-4, X-6)** The file's only writer is the evidence-only stop hook (§3.10.2). The veto threshold `RECORDER_WATCHDOG_STORM_KILLS = 3` per trading day [16:45Z, next 16:45Z) equals AUT-6's `WATCHDOG_STORM_KILLS = 3` (`detector_catalog.py`). AUT-6's `test_watchdog_storm_threshold_matches_aut1_recorder_storm_kills` pins the two equal; AUT-1 adds no duplicate test. The veto is AUT-1's node-local observation; the storm **page** is AUT-6's (X-6).

An **inactive** recorder (a crash loop that systemd has given up on) is handled by AUT-6's failed-unit path, which alerts and runs its `try-restart` of a failed allowlisted unit. It is not a node veto, because Take-path capture does not depend on the tape (§3.3.2).

### 3.8 Numbering note

r8's §3.8 (recorder and feed stall observations) is replaced by §3.10. The number is kept free so that r8 cross-references do not silently point at new content.

### 3.9 Reader and the C1 projection (`capture_reader.py`)

**`read_capture_stream(boot_dir) -> CaptureStream`**
- Opens each `*.feather` file under `<capture_root>/live/<instance_id>/` with `pyarrow.ipc.open_stream`, under the `O_NOFOLLOW` single-read rule.
- Decodes through the registered `from_arrow` decoders. The table name and the file name's `ts` identify the type.
- A truncated final batch is `stream_torn_tail`: INFO while the boot is running, counted by R5 once the boot has ended.

**`project_c1(stream) -> C1View`** yields the **C1 logical records**, so downstream readers keep C1's names:
- `DecisionRecord`:
  - `instrument` becomes `instrument_id`, and `ts_init` becomes `ts_ns`;
  - the frame reference is exposed as the `depth_ref`/`quote_ref` **strings** `"depth10:<instrument_id>@<ts_event>"` / `"quote:<instrument_id>@<ts_event>"`;
  - the forecast reference is exposed as `forecast_input_ref = "nbp:<station>@<cycle_ns>@<available_at_ns>"` (ER-4; **r10, R-B**).
- `OrderLink`, from each native `OrderInitialized`:
  - the tag's `decision_id`, `client_order_id`, and the five `str()` fingerprint fields;
  - `venue_order_id_sha256` from the `OrderEventRecord(OrderAccepted)`, or the sha256 of `OrderFilled.venue_order_id`.
- `LifecycleEvent`, from `OrderFilled` and the `OrderEventRecord`s.
- `PositionMark`, from the native `PositionEvent`s:
  - with the venue leg sign applied (a NO holding counts as short YES; L-44, memory `venue-nets-no-holding-as-short-yes`);
  - with `reconciliation_source="node_belief"`.
- `DetectorEvent`, as stored.

**Joins and resolvers.**
- `join_fills_to_decisions(c1_views, fills)` is pure; AUT-2 consumes it.
- `resolve_frame_ref` (here) and `resolve_forecast_ref` (`src/breezy/analysis/capture_forecast_ref.py`, **r10**) are described in §3.3.1.
- **(r10)** A truncated final batch is classified with the existing `breezy.persistence.feather_preflight.inspect_feather_file` (`feather_preflight.py:472`), not a new scanner.
- Readers read `eval_ns` and `eval_seq` as stored and never re-derive them (the r8 L1 contract).

**Compatibility for AUT-3, AUT-4 and AUT-6.** Code that read a payload by its content address must call `resolve_frame_ref` or `resolve_forecast_ref` instead (§5.3).

### 3.10 Recorder and feed stall: native watchdog (obligation 5; AUT-1a; ER-8 reduced; AUT-6 E-11)

#### 3.10.0 Ownership split with AUT-6 (r10; exactly as `reviews/AUT-6-r14-merged.md` and AUT-6 r14 §3.5 write it)

| AUT-1 owns (writes and tests) | AUT-6 owns (writes and tests) |
|---|---|
| The gate `classify_recorder_sample` and the stdlib sender `sd_notify` (`recorder_watchdog.py`), and their call site in the recorder process | `WATCHDOG_DAEMON_UNITS`, the directive rules, and the config test that checks AUT-1's unit lines |
| The `READY=1` sender (X-5: "AUT-1 owns the sender") | The SELF_HEAL contract, and the contract test on AUT-1's pure classifier, which states X-5 and includes the quiet-feed start test |
| The recorder unit's lines: `Type=notify` (X-2), `NotifyAccess=all` (X-1), `WatchdogSec`, `WatchdogSignal`, `TimeoutStartSec`, the `OnFailure=breezy-autonomy-failed@%n.service` line (X-4; AUT-6 r15 requires it on every member), and `ExecStopPost=` | The `OnFailure=breezy-autonomy-failed@%n.service` notifier, which pages each kill keyed `(unit, InvocationID)` with delivery proof (X-4) |
| The launch-window deferral inside `classify_recorder_sample`, and journaling it once per stall (X-3; X-7's journal half) | Delivering the deferral WARN (X-7) |
| The evidence-only stop hook: the stall record and `recorder_watchdog/v1` | Storm escalation: the one deduplicated CRITICAL `watchdog_restart_storm` on the 3rd kill in a trading day, with per-kill pages dropping to WARN after it (X-6, #21) |
| The rotate unit file (`breezy-quote-tape-rotate.service`), whose bound AUT-6's V-W4 checks | #21 (the HEALTH verdict and its fallback page, simplified to match X-4), `watchdog_disarmed`, and E-11 (the single vehicle for the ARCH §4.5/§4.6 SELF_HEAL wording) |

AUT-1 sends no page for a kill, a storm or a deferral, and builds no notifier. AUT-6 builds no gate, no sender and no hook.

**AUT-6 r15 contract tests that AUT-1's code must pass (coordinator relay, 2026-10-03; AUT-6 r15 §3.5, WP4):** `test_watchdog_unit_config_declares_notify_watchdog_restart_startlimit_and_notifyaccess_all` (with `OnFailure=` on every member), `test_member_has_single_start_command`, `test_rotate_bound_covers_member_stop_stoppost_and_ready`, `test_ready_sent_on_connect_and_subscribe_not_gated_on_counters`, `test_deferral_journals_recorder_watchdog_deferred_once_per_stall`, `test_no_recorder_stop_hook_pages_watchdog_kill` and `test_watchdog_storm_threshold_matches_aut1_recorder_storm_kills`; **(r11, GM4)** and, from AUT-6 r15-final binding build item 7 (added 2026-10-03), `test_unit_health_tolerates_activating_within_member_start_budget`. AUT-6's unit-health and liveness checks (#21, #22, `watchdog_disarmed`, the gate cross-check) treat the recorder's `ActiveState=activating`/`SubState=start` as healthy until the extended start budget runs out, and page once it has. AUT-1 supplies that budget as the constant `QUOTE_TAPE_MAX_START_SECS` (§3.10.2; 4500 s at base `TimeoutStartSec=180`). AUT-6 reads the constant and never re-derives it. Item 7's prose says "4200 s … inside a rotate bound of 4500 s"; r11's derivation (R-16) gives a 4500 s start budget inside a 4680 s rotate bound, which is relayed to the coordinator (§R11). AUT-1 gates WP3 step 2 on it through its own dependency test, `tests/unit/autonomy/test_capture_dependencies.py::test_aut6_unit_health_tolerates_activating_within_start_budget` (§4 WP3). AUT-1 supplies what they read: the unit files, the pure classifier, the `RECORDER_WATCHDOG_DEFERRED` text plus a fixture (`tests/fixtures/recorder_watchdog/deferred_journal_line.json`, one journal-JSON entry), the hook module, and `RECORDER_WATCHDOG_STORM_KILLS`. **AUT-1 restarts nothing:** the only restarter is the user manager acting on the unit's own directives.

#### 3.10.1 The ping gate (recorder process)

- **Opt-in.** `PolymarketUSDataClientConfig.watchdog_notify: bool = False`. Only `build_quote_tape_node_config` sets it to True (`test_trade_node_config_never_sets_watchdog_notify`).
- **The ping source runs from the start of `_connect`, through discovery (r10, EH1).** r9 sampled inside `_watch_feed`, which `_connect` creates only after `initialize()` returns (`data.py:1101-1121`). On a 09:00Z rotate inside the listing hole, that wait is up to `empty_discovery_retry_secs` = 3600 s (`node_config.py:349`). r10 creates a dedicated `RecorderWatchdogPinger` task as the **first** statement of `_connect` when `watchdog_notify` is set. It runs on the node's event loop (one thread, AUT-6's contract), wakes every `PING_INTERVAL_S = _feed_watch_interval_secs` (5 s), and is independent of `_watch_feed`. **(r11, GL1)** The client holds a strong reference, `self._watchdog_pinger_task`, so the event loop's weak task set can never let it be collected mid-run. `_connect` is idempotent against a second pinger: it creates a task only when that attribute is `None` or `.done()`. A re-entered `_connect` reuses the running pinger and resets `phase` to `DISCOVERING`. `READY=1` stays once per process, because `mark_ready()` latches. `_disconnect` cancels the task and clears the attribute; the resulting `CancelledError` is the only normal ending (`test_second_connect_does_not_start_a_second_pinger`, `test_pinger_task_strongly_referenced_and_cleared_on_disconnect`). `_connect` is the first await of the data client after process start; process start up to `_connect` is covered by the unit's base `TimeoutStartSec`.
- **What X-2 changes about EH1.** Under `Type=notify`, systemd arms `WatchdogSec` only when start-up completes, that is at `READY=1` (§1.3, systemd.service(5)). So before READY a missing ping cannot trigger a watchdog kill. The EH1 hazard becomes the **start timeout**: a recorder that is legitimately still discovering at 09:00Z+90 s would fail its start with `Result=timeout`. r10 closes both readings:
  - **Before READY**, on each tick whose classification is `OK`, the pinger sends `EXTEND_TIMEOUT_USEC=<START_EXTEND_S × 10^6>` with `START_EXTEND_S = 120` (sd_notify(3): the manager extends the start timeout to at least that far from now). A start that is still legitimately discovering therefore never times out. A frozen loop, or a discovery past its budget, stops extending, and `TimeoutStartSec` ends the start as before; AUT-6's notifier then pages it CRITICAL `member_start_timeout` (AUT-6 r15 §3.5). Without the extension, every 09:00Z rotate in the listing hole would end in `member_start_timeout`, a restart and a CRITICAL page for a healthy recorder. This is stated to AUT-6 as reading R-13 (§11); it changes no AUT-6 rule, because `TimeoutStartSec` still bounds every start that stops extending.
  - **`READY=1` (X-5).** `_connect` calls `pinger.mark_ready()` once, right after `self._feed.connect()` and the initial `_reconcile_discovered_subscriptions(cycle="initial")` have returned. That is "the feed is connected and subscribed to the current listing" (AUT-6 r15 §3.5). On this client an empty listing at boot does not complete discovery: `initialize()` keeps retrying `EmptyClimateListingError` (`data.py:1082-1099`), so READY follows the first non-empty discovery, or the start ends on the fatal path once the budget is spent. It sends `READY=1` at once and is **not** gated on counters, so a quiet feed with zero frames still completes its start (`test_quiet_feed_start_sends_ready_without_any_counter_advance`; WP0 V-18 runs the same thing on real systemd). A `_connect` failure never sends READY: it takes the existing fatal-shutdown path, the process exits, and `Restart=always` restarts it.
  - **After READY**, on `OK` the pinger sends `WATCHDOG=1`. On anything else it sends nothing, and logs `RECORDER_WATCHDOG_WITHHELD cause=<c>` at most hourly per cause. Only `WATCHDOG=1` is gated on advancing counters (X-5).
- **Exception-safe sampling (r10, EM2).** Each tick's body (building the `RecorderSample`, the `lstat`s, `classify_recorder_sample`, the send) runs inside `try/except Exception`. On an exception the pinger:
  - logs ERROR `RECORDER_SAMPLE_FAILED cause=<exc class> failures=<n>` (the first, then every 60th);
  - increments `sample_failures`;
  - records the tick as non-OK `sample_error`, so no `WATCHDOG=1` or `EXTEND` is sent;
  - keeps looping. Only `CancelledError` at shutdown ends the task.

  The task's done-callback logs ERROR `RECORDER_PINGER_DIED` for any other ending. A dead pinger sends nothing, so systemd kills the recorder within `WatchdogSec`, and AUT-6's notifier pages that kill: it is never silent. A dead `_watch_feed` is visible through the `feed_watch_alive` accessor, and the gate classifies it as `feed_watch_dead`, so it never stops pings without a reason being logged.
- **`RecorderSample` (r10, EM6).** `{now_ns, phase, phase_started_ns, discovered_slugs, subscribed_count, quotes_published, depths_published, trades_published, is_tape_gap_open, safe_mode, feed_watch_alive, last_discovery_reload_ns, last_scheduled_reload_delay_secs, discovery_attempt_inflight_since_ns, stream_bytes}` (**r11, GM1**: `discovery_attempt_inflight_since_ns` added). Every field is read through a read-only accessor on `PolymarketUSDataClient`; WP3 adds the ones that do not exist today:
  - `phase` ∈ {`DISCOVERING`, `CONNECTING`, `STREAMING`, `SAFE_MODE`}, with `phase_started_ns`. It is set at the top of `_connect` (DISCOVERING), after `initialize()` returns (CONNECTING), at `mark_ready()` (STREAMING), and when `_safe_mode` is set (SAFE_MODE);
  - `discovered_slugs = len(self._provider_active_slugs())` (`data.py:1329`);
  - `subscribed_count = len(self._quote_subscribed_slugs | self._depth_subscribed_slugs)` (`:825-826`);
  - `depths_published`, a new counter incremented beside `self._handle_data(depth)` (`:1599`), the twin of `_quotes_published`;
  - `last_discovery_reload_ns` and `last_scheduled_reload_delay_secs`, set in `_update_instruments`;
  - `feed_watch_alive = self._feed_watchdog is not None and not self._feed_watchdog.done()`;
  - **(r11, GM1)** `discovery_attempt_inflight_since_ns`: `_initialize_instruments_for_connect` sets it to `self._clock.timestamp_ns()` immediately before each `await self._instrument_provider.initialize()` (`data.py:1088`) and resets it to 0 in a `finally` around that await. So it is non-zero only while an attempt is in flight, and 0 during the `asyncio.sleep(DISCOVERY_RELOAD_FLOOR_SECS)` between attempts (`:1099`). The retry loop's control flow is unchanged.

  `stream_bytes` is the `lstat` byte total under the recorder's own `<catalog_root>/live/<recorder_instance_id>/`. `sample_feed_health` and every existing recorder test are unchanged.
- **`classify_recorder_sample(history, now_ns)`** is pure. It returns `OK`, `OK_DEFERRED` or a withhold cause:

  | Cause | Rule |
  |---|---|
  | `discovering_overrun` | `DISCOVERING` for longer than `empty_discovery_retry_secs + DISCOVERING_GRACE_S` (300; EH1) |
  | `discovery_attempt_hung` (**r11, GM1**) | `DISCOVERING` with `discovery_attempt_inflight_since_ns ≠ 0` and `now − inflight_since > DISCOVERY_ATTEMPT_BUDGET_S = 180`. The retry sleep between attempts has `inflight_since = 0`, so it stays `OK`. |
  | `connecting_overrun` | `CONNECTING` for longer than `CONNECT_BUDGET_S = 300` |
  | `safe_mode_overrun` | `SAFE_MODE` for longer than 300 s |
  | `stream_stalled` | `STREAMING` with `subscribed_count > 0`, and counters and bytes both unchanged across `STREAM_SILENCE_S(h)` |
  | `writer_stall` | ≥ 1 event published and bytes flat across `WRITER_STALL_S`, outside `FLUSH_MARGIN_S` |
  | `discovery_reload_overdue` | `STREAMING` with `discovered_slugs == 0` (a legitimately empty listing) and `now − last_discovery_reload_ns > 2 × last_scheduled_reload_delay_secs`. On the recorder the delay is the unit's fixed `POLYMARKET_US_DISCOVERY_RELOAD_INTERVAL_MINS=15` override (`data.py` `_next_reload_delay_secs`; unit line 108), so this is AUT-6's "2 × 15 min" rule. |
  | `feed_watch_dead` | `STREAMING` and not `feed_watch_alive` |
  | `sample_error` | set by the pinger, never by the classifier (EM2) |

  The thresholds keep r8's WP0 derivations (D8). A legitimately empty listing whose reloads are fresh is `OK`.

  **`DISCOVERY_ATTEMPT_BUDGET_S = 180` (r11, GM1), derived.** One discovery request costs at most `http_timeout_secs` (10 s, `config.py:274`) plus one discovery-quota interval, 60 / `discovery_requests_per_minute` = 10 s (`config.py:277`), so 20 s. The real universe is one or two pages (`provider.py:101-113`). 180 s therefore covers 9 pages, at least 4.5 times a legitimate attempt. An attempt that runs to the 50-page cap (`MAX_DISCOVERY_PAGES`) takes about 1,000 s. It can only come from a payload that is already wrong (provider docstring), so classifying it non-OK is correct. WP0 V-20 measures attempt durations and page counts from 14 days of recorder logs. If the p99 attempt exceeds `DISCOVERY_ATTEMPT_BUDGET_S / 2`, the plan returns to review; the budget is never silently raised. **Effect:** a hung attempt stops `EXTEND_TIMEOUT_USEC` at most 180 s + one 5 s tick after it began. The start then ends at the last extension's deadline (≤ 120 s later) with `Result=timeout`, which AUT-6 pages as `member_start_timeout`, and `Restart=always` restarts the recorder. Worst detection is about 305 s, against r10's up to 3,900 s of extension. **Scope:** connect-time attempts only. A reload hang while `STREAMING` is left to `discovery_reload_overdue` and the stream counters, because a recorder that is still receiving frames is still capturing and must not be killed.
- **Launch-window deferral (r10, X-3).** If the result would be a withhold cause, and `[now, now + H]` meets `[16:30Z, 17:10Z)` with `H = UNIT_WATCHDOG_SEC + UNIT_TIMEOUT_STOP_SEC + UNIT_TIMEOUT_START_SEC`, the classifier returns `OK_DEFERRED`: the pinger keeps pinging. **(r12, item 2)** This applies **after READY only**. Before READY there is no deferral: a withhold cause stops `EXTEND_TIMEOUT_USEC` exactly as outside the window (§3.10.2, "Deferral and the start budget"). The first `OK_DEFERRED` of a stall logs one WARNING line, `RECORDER_WATCHDOG_DEFERRED stall_id=<ns of the stall's first non-OK sample> stall_started_ns=<same ns> cause=<c> until=17:10Z`. A stall is the run of non-OK samples that begins after an `OK` one, so the line is written exactly once per stall. From 17:10Z the deferral ends, and the same stall withholds. That line in the recorder's journal is the contract AUT-6 reads to deliver X-7's WARN; `RECORDER_WATCHDOG_DEFERRED` is a module constant AUT-6 imports read-only. The three `UNIT_*` constants are pinned to the unit file by `test_classifier_timing_constants_equal_unit_file`. **(r11, GL1)** That test runs in **both** steps. In step 1 it reads the pending step-2 unit text, a committed fixture `tests/fixtures/recorder_watchdog/pending_recorder_unit.service` (a test fixture, so no `daemon-reload` can make it live). In step 2 it reads `deploy/systemd/breezy-quote-tape.service`, and `test_pending_recorder_unit_fixture_equals_deployed_unit_lines` asserts that every watchdog, timeout and `OnFailure`/`ExecStopPost` line of the deployed unit equals the fixture's. So the constants can never ship against an unpinned value. **Limit:** a hung event loop sends nothing, in or out of the window, so systemd restarts it at once, exactly as it restarts a crash today (AUT-6's stated limit).
- **`sd_notify`** is stdlib only: `socket(AF_UNIX, SOCK_DGRAM)` and `sendto($NOTIFY_SOCKET)`, handling the abstract-namespace `@` prefix. It returns False when `NOTIFY_SOCKET` is unset, logs a send error, and never raises (`test_sd_notify_without_socket_is_false_never_raises`). At boot the pinger logs `RECORDER_WATCHDOG_GATE notify_socket_present=<bool>` (a boolean only, never the environment).

#### 3.10.2 Unit settings, the rotate bound and the evidence-only stop hook

**Unit settings (r10).** These land in **WP3 step 2 only**, together with `test_recorder_unit_watchdog_config_exact` (EH1). `deploy/systemd/breezy-quote-tape.service` is symlinked into the user manager, so a step-1 unit edit would go live at the next `daemon-reload`. The unit gains:

| Setting | Why |
|---|---|
| `Type=notify` | X-2. Start-up completes at `READY=1`, so the watchdog is armed only once the feed is connected and subscribed (X-5). |
| `NotifyAccess=all` | X-1, measured by AUT-6 (§0.1 (27)): with `main`, any later prefix (`timeout`, a wrapper) would silently disarm the watchdog. |
| `WatchdogSec=600` | r8's "two bad probes ≥ 5 min apart"; inside AUT-6's [120 s, 600 s]. |
| `WatchdogSignal=SIGTERM` | Nautilus stops cleanly and flushes the tape. A frozen process escalates to SIGKILL after `TimeoutStopSec=120`. This meets AUT-6's rule (SIGTERM, or SIGABRT with `LimitCORE=0`). |
| `TimeoutStartSec=max(180, AUT-6's V-W3 value)` | AUT-6 r15's rule (DH1): at least max(90 s, 2 × p99 start-to-connected-and-subscribed). The listing hole is carried by `EXTEND_TIMEOUT_USEC` (§3.10.1), not by this base value. The unit keeps exactly one `ExecStart=` and no `ExecStartPre=`/`ExecStartPost=` (`test_member_has_single_start_command`). |
| `OnFailure=breezy-autonomy-failed@%n.service` (in `[Unit]`) | X-4. The per-kill page is AUT-6's notifier, which pages on `SubState=auto-restart` + `Result=watchdog` for this start-limit-disabled member. |
| the existing `Restart=always`, `StartLimitIntervalSec=0`, `RestartSteps=4`, `RestartMaxDelaySec=480`, `RestartPreventExitStatus=2` | unchanged (AUT-6 O-8, the 2026-09-09 incident) |
| `ExecStopPost=-/usr/bin/timeout -k 2 10 /home/jon/breezy/deploy/systemd/breezy-autonomy-bwrap breezy-quote-tape.stop-hook /home/jon/breezy/.venv/bin/python3 -m breezy.runtime.capture_recorder_hook_cli` | The evidence-only hook, below. The `-` prefix means no hook outcome (an error, a timeout kill) can change the unit's `Result` or its restart. |
| no `RuntimeMaxSec` | AUT-6's R-c |

**The rotate bound (r10, DH1; coordinator relay item 5; r11, GH1: one constant).** `breezy-quote-tape-rotate.service` runs a blocking `try-restart` (§1.3). AUT-6 measured that under `Type=notify` the call returns only at `READY=1` (AUT-6 r15 §0.1 (36)). Today's `TimeoutStartSec=180` is below even AUT-6's plain worst case of 120 + 27 + 90 = 237 s. With the extension, the listing hole can hold READY back for more than an hour after 09:00Z.

**(r11, GH1) Every number is derived from one constant.** r10 wrote 4200 in the file table, 4500 in §3.10.2, §3.13 and R5, and a rule of 120 + 12 + 4200 + 30 = 4362. The review found the inconsistency. Re-deriving every term found a second error: that rule left out two terms, so the right value is neither 4200 nor 4500. Each term of the start comes from a constant:

| Term | Constant (module) | Value | Source |
|---|---|---|---|
| Base start, process start to `_connect` | `UNIT_TIMEOUT_START_SEC` (`recorder_watchdog.py`, pinned to the unit) | max(180, AUT-6 V-W3) | No extension can be sent before the pinger exists, so the time to `_connect` is bounded only by the base `TimeoutStartSec`. Any start that is still pending when the pinger begins has used less than it. |
| Discovering, connect-time | `QUOTE_TAPE_EMPTY_DISCOVERY_RETRY_SECS` + `DISCOVERING_GRACE_S` | 3600 + 300 | `node_config.py:349`; `discovering_overrun` |
| Connecting | `CONNECT_BUDGET_S` | 300 | `connecting_overrun` |
| The last extension's tail | `START_EXTEND_S` | 120 | sd_notify(3): the manager extends the start to at least now + the value, so the last `OK` tick still grants 120 s |
| **Max start** | `QUOTE_TAPE_MAX_START_SECS = recorder_max_start_s(...)` (`node_config.py`) | **4500** at base 180 | the sum of the four rows above |
| Member stop | `UNIT_TIMEOUT_STOP_SEC` (pinned to the unit) | 120 | recorder `TimeoutStopSec` |
| Stop hook | `STOP_HOOK_BOUND_S` (pinned to the `timeout -k 2 10` argv) | 12 | §3.10.2 |
| Margin | `ROTATE_MARGIN_S` | 30 | AUT-6's rule |
| **Rotate bound** | `QUOTE_TAPE_ROTATE_TIMEOUT_START_SECS = rotate_timeout_start_s(QUOTE_TAPE_MAX_START_SECS)` (`node_config.py`) | **4680** = ⌈(120 + 12 + 4500 + 30) / 60⌉ × 60 = ⌈4662⌉₆₀ | the one constant |

- The unit file carries the literal `TimeoutStartSec=4680`. `test_rotate_bound_covers_recorder_stop_and_max_start` (WP3 step 2) asserts three things: that literal **equals** `QUOTE_TAPE_ROTATE_TIMEOUT_START_SECS`; that constant is at least the sum recomputed from the recorder unit file's own `TimeoutStopSec`, `TimeoutStartSec` and `ExecStopPost=` argv; and the base `UNIT_TIMEOUT_START_SEC` equals the unit's value. If AUT-6's V-W3 raises the base, the constants move, the test fails, and both unit files must follow in one reviewed commit. That failure is closed and loud, never a drift.
- **AUT-6's rule** (≥ member `TimeoutStopSec` + hook + member `TimeoutStartSec` + 30) uses the base `TimeoutStartSec`, so it is met with 4338 s to spare. AUT-6's `test_rotate_bound_covers_member_stop_stoppost_and_ready` parses both files unchanged.
- **AUT-6 r15 item 7's start budget** is `QUOTE_TAPE_MAX_START_SECS` (4500), not 4200 (§3.10.0).
- **Latest end** is 09:00Z + 4680 s = **10:18Z**, outside [16:30Z, 17:10Z). The semantics are unchanged: success still means the recorder came back up. E-9 holds (one command).
- The X-3 deferral horizon `H` still uses the base `UNIT_TIMEOUT_START_SEC`, as r10 did. A deferred stall exists only after READY, so no extension follows it.

**Deferral and the start budget (r12, item 2; choice stated).** r10's R-14 also applied the launch-window deferral **before READY**, to the start extension. That let a start that met [16:30Z, 17:10Z) keep extending past `QUOTE_TAPE_MAX_START_SECS`, up to 17:10Z, outside the budget AUT-6's activating tolerance reads (r15-final item 7), so AUT-6 would page a start AUT-1 was still deliberately extending. **Choice: the review's recommended option. The pre-READY deferral is removed** (R-14 retired, §11). Before READY, `classify_recorder_sample` never returns `OK_DEFERRED`: a withhold cause (`discovering_overrun`, `connecting_overrun`, `discovery_attempt_hung`, `safe_mode_overrun`) stops the extension, the start ends at the last extension's deadline with `Result=timeout`, AUT-6 pages `member_start_timeout`, and `Restart=always` restarts the recorder normally. So **no start ever extends past `QUOTE_TAPE_MAX_START_SECS`**, in or out of the window, and AUT-6's tolerance needs no deferral state. **Consequence, accepted:** such a restart can land inside [16:30Z, 17:10Z). That is safe: a recorder that has not sent READY is not yet subscribed, so the restart loses no capture (the reason X-3 defers a post-READY kill), the recorder is a separate process from the trade node, and the trade node's Take-path capture does not depend on the tape (§3.3.2). X-3 is unchanged: it governs the post-READY watchdog deferral, as AUT-6 r15 §3.5 writes it ("It pings while …"). Tests (WP3 step 1): `::test_pre_ready_withhold_is_never_deferred` (replaces r10's planned `::test_pre_ready_deferral_keeps_extending_in_window`, which was never built) and `::test_extension_deadline_never_exceeds_max_start_budget` (a property test over generated sample sequences, including starts that meet the launch window: the last extension's deadline is never later than process start + `QUOTE_TAPE_MAX_START_SECS`).

**(r12, item 6) Cross-plan note: AUT-6's rotate-bound test.** AUT-6's `test_rotate_bound_covers_member_stop_stoppost_and_ready` computes its bound from the two unit files (member `TimeoutStopSec`, the `ExecStopPost=` `timeout -k` bound, member `TimeoutStartSec`, + 30) and, where it needs the extended start, from the constant `QUOTE_TAPE_MAX_START_SECS` / `QUOTE_TAPE_ROTATE_TIMEOUT_START_SECS` imported read-only from `node_config.py`; it never carries a literal (4200, 4362, 4500 or 4680). AUT-6 r15-final item 7 already states 4500 s inside 4680 s via the constant (`reviews/AUT-6-r15-final.md:24`), so r11's R-16 relay is discharged and no AUT-6 rule changes. Precision for that prose: the activating tolerance reads `QUOTE_TAPE_MAX_START_SECS`; `QUOTE_TAPE_ROTATE_TIMEOUT_START_SECS` is derived from it. AUT-1 pins the no-literal property on its side with `tests/unit/autonomy/test_capture_dependencies.py::test_aut6_rotate_bound_test_reads_constants_not_literals` (an AST scan of AUT-6's test for any integer literal in {4200, 4362, 4500, 4662, 4680}; positive control: a planted literal fails). It gates WP3 step 2 with `test_aut6_unit_health_tolerates_activating_within_start_budget`; it stays RED until AUT-6 WP4 lands and is never `xfail`ed.

**Rotate's `OnSuccess=` timing (r11, GM5).** The rotate's only dependent is `OnSuccess=breezy-station-candidate-register.service` (rotate unit, `[Unit]`). Read 2026-10-03 (§1.3, r11 facts), the register:
- has **no timer**, no `[Install]` and no `OnCalendar`; only the rotate's `OnSuccess=` starts it (`systemctl --user show`: `TriggeredBy=` empty);
- has `Type=oneshot` and `TimeoutStartSec=600`;
- takes the studies lock with `flock -n`, so it **never waits**: under contention it runs `--check-staleness` and exits 0;
- re-folds every missed day from its `last_folded_day` watermark, and alerts if the watermark is more than 2 days old.

It therefore has **no deadline inside 09:00–10:18Z**. A late rotate (the listing hole) only moves its start to at most 10:18Z and its end to at most 10:28Z, which is still outside the launch window. It meets no other 09:00–10:30Z timer: the 09:20Z digest and the 09:25Z retention take the same lock with `flock -n` and have finished long before. A rotate that ends in a start timeout fails, so `OnSuccess=` does not fire. That day is caught up by the watermark, and the rotate's `OnFailure=` pages, which is today's behaviour. WP0 check V-22 re-reads the register unit, its run script and `systemctl --user show -p TriggeredBy,TimeoutStartUSec` before WP3 step 2, and `tests/unit/test_capture_units.py::test_station_candidate_register_has_no_deadline_in_rotate_window` pins it: no `.timer` names it, it has no `[Install]`, it has `flock -n`, and `rotate latest end + its TimeoutStartSec` is outside [16:30Z, 17:10Z).

**The stop hook (`capture_recorder_hook_cli`), evidence only (r10, X-4).**
- **Decision.** Kept, as evidence only, rather than deleted. The justification is §2.2's row: the node-local `recorder_stale` veto needs an intraday, node-readable kill count, and the node closure may not run `journalctl` or read AUT-6's alert records. The hook is also the one process that sees `SERVICE_RESULT=watchdog` and `$INVOCATION_ID` together at the kill, so its record carries the same `(unit, InvocationID)` key as AUT-6's page. Deleting it would move the stall record to the next day's audit and leave `recorder_stale` with no source.
- **On `SERVICE_RESULT=watchdog`** it:
  1. writes the write-once stall record `evidence/capture/stall/<date>/<ts_ns>_<invocation_id>_recorder_watchdog.json` (`{unit, cause:"watchdog", result, invocation_id, exit_code, exit_status, detected_ns, observation_sha256}`);
  2. counts the trading day's records (trading day [16:45Z, next 16:45Z), ARCH §4.5) and atomically rewrites `health/recorder_watchdog/polymarket_us.json` (`{schema:"recorder_watchdog/v1", watchdog_kills_trading_day, last_watchdog_kill_ns, last_invocation_id, trading_date}`) under its own flock, `health/recorder_watchdog/hook.lock`.

  It sends **no** alert: no `deliver_with_proof`, no `emit_alert`, no `RECORDER_WATCHDOG_KILL`, no `RECORDER_WATCHDOG_STORM` (X-4, X-6). The module imports neither, so AUT-6's AST test `test_no_recorder_stop_hook_pages_watchdog_kill` holds, and AUT-1's own `test_hook_module_imports_no_alert_sender` mirrors it.
- **On any other result** it exits 0 and does nothing. That includes the 09:00Z rotate's clean `try-restart` (`Result=success`).
- **Failure paths (r10, EM1).** A missing `$SERVICE_RESULT` or `$INVOCATION_ID`, a flock that is not acquired within 5 s, or a write error each log ERROR `RECORDER_HOOK_FAILED cause=<c> invocation_id=<id or "unknown">` to the recorder's journal and exit 0. A timeout kill leaves no record. In every case the daily audit's leg W (§3.10.3) finds the missing stall record against the journal and FAILs the day.
- **The blind window, stated (r11, GM3).** A hook that fails, or that `timeout -k` kills, leaves **no stall record and no `recorder_watchdog/v1` count** for that kill. Until the next day's 13:50Z audit runs leg W, nothing in AUT-1 records that kill: the window is up to about 38 h (a kill at 00:00Z on day D is first audited at 13:50Z on D+1). The kill itself is still **paged** at once by AUT-6's `OnFailure=` notifier (X-4); only AUT-1's evidence lags. Intraday, the node's `recorder_stale` check narrows the window: it also counts recorder boots (`recorder_boots`, every restart, less the excused rotate; r12, item 3) from the recorder's native boot marker (`live/<instance_id>/config.json`, §3.7.4). So a storm of kills whose hooks all failed still vetoes. The node never runs `systemctl` or `journalctl`.
- **Bound.** `timeout -k 2 10`, inside the stop phase: the hook delays a restart by at most 12 s. No network is involved.
- **Sandbox.** The hook runs through the E-7a shared wrapper under its own table row, `breezy-quote-tape.stop-hook`, which binds only `evidence/capture/stall/` and `health/recorder_watchdog/`. With no alert to send, r9's `evidence/alerts/` bind and `alerts.env` are removed. The recorder's own `ExecStart` is not wrapped (the E-7a rule 5 residual).

#### 3.10.3 Heal confirmation and the journal cross-check

The audit confirms heals (§3.11.6); there is no polling watch. A watchdog kill at time `t` counts as **healed** when all three hold:
- the journal shows a new invocation of `breezy-quote-tape.service` started after `t`;
- that invocation's `live/<instance>/` directory grew for at least 15 min;
- no further watchdog kill came within 30 min of the restart.

These checks use the journal fields AUT-6 already parses (`USER_INVOCATION_ID`, `UNIT_RESULT`; AUT-6 r13 §0 facts). On a confirmed heal, the audit:
- writes `evidence/capture/heal/<date>/<ts_ns>_audit_breezy-quote-tape.json` (`decided_by:"systemd_watchdog"`, with the stall record's `observation_sha256` and `invocation_id`);
- sends INFO `CAPTURE_HEALED_<observation_sha256>`.

**Leg W, the journal cross-check (r10, EM1, reconciled with X-4).** For every journal entry of `breezy-quote-tape.service` with `UNIT_RESULT=watchdog` in day D, keyed by its `InvocationID`, the audit requires both of:
1. **a stall record** with that `invocation_id` (the hook's evidence);
2. **a delivered proof of the per-kill page**: AUT-6's notifier marker `evidence/alerts/notify/<date>/<unit>__<InvocationID>.delivered.json` (AUT-6 r15 §3.1.1, §3.5), or, failing that, the delivered record of #21's fallback page for the same `(unit, InvocationID)`. Under X-4 the page is AUT-6's, so the audit matches AUT-6's own key and marker family and never an AUT-1 event name. It reads them single-read, `O_NOFOLLOW`, without writing (`test_leg_w_reads_aut6_notifier_marker_by_invocation_id`).

If either is missing, leg W FAILs the day (`watchdog_evidence_gap`, naming the invocation and the missing part), and the audit sends CRITICAL `CAPTURE_WATCHDOG_EVIDENCE_GAP` through `deliver_with_proof`. It **re-sends** that alert on each daily run while the gap stands, for `HEAL_ALERT_RETRY_DAYS = 8` days, and then follows §3.11.6's abandon order (the marker is written only after a `delivered=true` proof). This is r10's reading of EM1's "re-sends" under X-4: the audit re-sends its own gap alert, not AUT-6's per-kill page, because per-kill paging authority is AUT-6's alone (X-4, and #21's fallback page). An undelivered page fails the day toward the operator's attention, and only one owner ever sends a kill page.

#### 3.10.4 Weekly injected stall drill (WP9)

1. **Drill.** `breezy-capture-stall-drill` runs Sundays at 12:30Z (WP0 confirms the slot has few takes; it is outside the deferral horizon). It refuses unless the recorder is active with an instance older than 1 h, there has been no watchdog kill in the last 24 h, and it is within 10 min of the slot. It then:
   - writes `evidence/capture/drill/<date>.json` (`injected=true`);
   - runs the literal argv `["systemctl","--user","kill","--signal=SIGSTOP","breezy-quote-tape.service"]`.
2. **Expected chain (r10).**
   - The recorder's loop freezes, so the pinger stops (the watchdog was armed at READY).
   - systemd's watchdog fires at about 12:40 and sends SIGTERM plus SIGCONT (V-10).
   - The evidence-only hook writes the stall record and the health file.
   - AUT-6's `OnFailure=` notifier pages the kill (X-4).
   - `Restart=always` brings up a new instance, which sends `READY=1` once it is connected and subscribed.
   - The next audit confirms the heal, passes leg W, and marks the heal `injected=true` from the drill file.
3. **Guard.** `breezy-capture-stall-drill-guard` runs at 13:15Z. It runs the literal SIGCONT argv unconditionally. If no watchdog stall record exists after the drill timestamp, it raises CRITICAL `CAPTURE_DRILL_NOT_HEALED`.
4. **Skipped-drill alarm** (r8 H9, kept). Three consecutive refusals raise CRITICAL `CAPTURE_DRILL_SKIPPED`.

r9 removed r8's AUT-6 SELF_HEAL precondition for the drill, because the healer is systemd, not AUT-6 (ER-8). AUT-6 cites this drill as the natural SELF_HEAL live proof (AUT-6 r15 DL2, O-9); AUT-1 changes nothing for that.

#### 3.10.5 Restarts (obligation)

- **AUT-1 restarts nothing,** and requests no restart.
- AUT-6 r14 deleted its restart executor and `SELF_HEAL_RESTARTABLE_UNITS`. SELF_HEAL is now the user manager acting on each `WATCHDOG_DAEMON_UNITS` member's own directives (AUT-6 §3.5, E-11), and the recorder is AUT-6's only member.
- r9's request that "AUT-6 does not `try-restart` an active recorder" is therefore met by construction and withdrawn (§5.1).
- NWS-ingest freshness belongs to AUT-6's observation-feed detector (README AUT-6). `breezy-nws-ingest` is not a watchdog member.

### 3.11 Daily completeness audit (obligation 6; AUT-1a)

#### 3.11.1 Unit and inputs

**Schedule.** `breezy-capture-audit` runs at 13:50Z for D = yesterday, without `Persistent`. On each run it also:
- backfills any of the last 8 days that has no audit file;
- re-audits any of the last 8 days that is still `INCONCLUSIVE` (both r8 rules).

It runs under the E-7a wrapper.

**Inputs**, all read-only:
- the capture stream for every boot overlapping D−1..D+1;
- `settlement_*.jsonl`;
- the epoch files;
- the exec store, read through the **E-8 snapshot helper with `take_flock=False`** (E-7a rule 3, E-8a). The result is advisory and never counts toward H;
- the node logs, the funnel files, the ingest and supervisor journals (r8's literal `journalctl` argvs) and the recorder catalog;
- the recorder unit's journal (`journalctl --user -u breezy-quote-tape.service -o json --since … --until …`, 30 s timeout);
- `systemctl --user show -p WatchdogUSec -p NotifyAccess -p Type breezy-quote-tape.service` (**r10**: `-p Type` added);
- **(r10, EM1)** AUT-6's notifier markers `evidence/alerts/notify/<date>/<unit>__<InvocationID>.delivered.json` for leg W (read-only; §3.10.3).

**Import closure.** The audit, settlement, live-proof, hook and drill entry points import no `breezy.adapters.*` module. Leg I uses `breezy.domain.exec_intent` (§2.2). This is pinned by `tests/unit/autonomy/test_capture_unit_closures_have_no_venue_adapter_module`, which uses AUT-6 r12's static module-level walk with its positive control.

**Fail-loud** (C2, D15). Any of the following makes the day `ERROR`, never `NO_INPUT`:
- every item on r8's list:
  - an exec-store snapshot failure;
  - an unknown key prefix;
  - an unreadable or unparseable node log;
  - a boot without a log;
  - a journal failure;
  - an epoch error;
  - a positive-control failure;
- `stream_unreadable`: a feather file that fails to open;
- `recorder_watchdog_unarmed` (**r10, X-1, X-2**): `WatchdogUSec=0`, `Type` other than `notify`, or `NotifyAccess` other than `all`.

r8's boot census (H5) and boot-ended rule (D6) are unchanged, with one addition: every `<capture_root>/live/<instance_id>/` directory overlapping D is a census member.

#### 3.11.2 Legs per fill

Only fills with `ts_event ≥ epoch_start_ns` are audited.

| Leg | Pass condition |
|---|---|
| L | Exactly one `decision_id` tag across the native `OrderInitialized` rows for `client_order_id`. A conflict is `link_conflict`. A SELL with no tag gets the orphan id → `untagged_order` FAIL. |
| D | Entry: a `Take` and a `TrySubmit(submitted)` with that id, and the id recomputes from the Take. Exit: an `Exit` whose id recomputes from the four tag values (`test_every_exit_fill_joins`). |
| B | All of: the Take-path `FrameCopy` exists; it equals the tape frame whenever the tape holds one (otherwise `frame_copy_mismatch` FAIL); the forecast reference resolves inside the boot's own `ForecastPoint` stream (R-B, V-12); `artefact_sha256` resolves; every non-`Exit` record has a non-empty `frame_kind`. |
| I | `intent_fingerprint`, recomputed from the projected `OrderLink` (the `OrderInitialized` fields), matches `fill_by_fingerprint/<day>:<fp>`, using the r8 `<day>` derivation (V-6). |
| E | A native `OrderFilled` with the same `trade_id`, or a resolver context naming the `client_order_id`. |
| P | A projected `PositionMark` with `ts ≥ fill.ts_event`, or a tape mark, or `fill_via_resolver`. |
| S | A `SettlementRecord`. This is r8's leg S unchanged, including its definition of "ended" as the end of the climate day in local standard time. |

#### 3.11.3 Reconciliation legs per day

| Leg | Pass condition |
|---|---|
| R1 | r8 R1, unchanged: a bijection between the `SHADOW_DECISION` Take/TrySubmit lines and the records; veto lines checked through the on-change replay; guard `EntryVeto`s matched to `CAPTURE_REFUSED` lines. **One exception:** lines inside a boot's `lost_in_flush_window` (§3.4.4) are counted, not FAIL. |
| R2 | r8 R2, unchanged: replay every `SHADOW_DECISION` line through the same `OnChangeFilter` and `EvalSeqCounter`, and require equality with the boot's on-change `DecisionRecord` sequence. The same flush-window exception applies to the tail. |
| R3 | r8 R3, unchanged (funnel counts). |
| R4 | Writer failure markers in the node log: `Failed to serialize`, `Can't find writer for cls` or `CAPTURE_PUBLISH_FAILED` → FAIL. Their absence proves nothing (L-30). |
| **R5** | **Counted stream loss, per type (r10, EM3, EH4, EL1)** (§3.4.4). Per boot and per table, including the native `OrderInitialized`, `OrderFilled`, `Position*` and `ForecastPoint` tables: with a `final=true` heartbeat, rows present equal its `written_by_type[table]`; without one, rows present are at least the last heartbeat's count. A shortfall is `stream_record_lost` FAIL. The `lost_in_flush_window` count is reported, and only `SHADOW_DECISION` lines at most 61 s older than the boot's last log line qualify for it. |
| **R6** | **Reference resolution.** Reports `refusal_frame_ref_resolved_frac`, the fraction of on-change refusal frame references that resolve against the tape. Below the WP0-measured baseline minus 1 percentage point, it raises CRITICAL `CAPTURE_REFUSAL_REFS_UNRESOLVED` but does not FAIL the day, because refusals do not enter a fill's join (§R9 row 3). |
| **W** | **(r10, EM1, X-4) Watchdog evidence.** Every journal `UNIT_RESULT=watchdog` entry of the recorder in D has a stall record with its `InvocationID` and a `delivered=true` per-kill page from AUT-6's notifier under the same key (§3.10.3). Otherwise `watchdog_evidence_gap` FAIL, plus `CAPTURE_WATCHDOG_EVIDENCE_GAP`, re-sent daily. |
| **R7** | **Stream continuity.** For each boot overlapping D, no gap longer than `STREAM_GAP_FAIL_S = 180` between consecutive `CaptureHeartbeat`s while the boot ran; otherwise `stream_gap` FAIL. This is the positive control for the writer as a whole. |
| O | r8's order census, reading `OrderInitialized` in place of `OrderLink`. Every exec-store order, resolver context and `OrderSubmitted`/`OrderDenied` log line names a streamed `OrderInitialized`. Each `TrySubmit(submitted)` is `linked`, `refused_after_trysubmit` or `never_submitted`; anything else is `trysubmit_unlinked`. |
| F | r8's fill census, unchanged. |
| T | r8's tape-ingest leg, unchanged. Frame references depend on the tape, so the tape's own health stays audited. |
| N | r8's NBP census, plus a check that each `NBP_CYCLE_MISSED` offer in the log has a delivery record. |

The node-log and funnel positive control (D13) is unchanged.

#### 3.11.4 Day status, verdicts and outputs

- **Day status** (`PASS`, `INCONCLUSIVE`, `NO_INPUT`, `PRE_CAPTURE`/`PARTIAL_EPOCH`, `ERROR`, `FAIL`) and the **C4 verdicts** (`capture_join_completeness`, `capture_tape_ingest`, `capture_nbp_census`) are unchanged from r8 §3.10.
- **New metrics:** the metric tuple gains `records_lost_in_flush_window`, `refusal_frame_ref_resolved_frac`, `leg_R5_pass`, `leg_R6_pass`, `leg_R7_pass`, and (**r10**) `leg_W_pass` and `watchdog_kills_unproven`. They are proposed to AUT-5 for pre-registration (§5.2).
- **Outputs:**
  - `evidence/capture/audit/<family>/<D>.json` (write-once per run, mode 0444, schema `capture_audit/v2`);
  - the verdicts;
  - CRITICAL `CAPTURE_JOIN_GAP`, `CAPTURE_TAPE_INGEST`, `CAPTURE_NBP_CENSUS` and `CAPTURE_AUDIT_ERROR`, through `deliver_with_proof`;
  - `OnSuccess=breezy-capture-live-proof.service`.

#### 3.11.5 Duties moved from r8's watchdog

The audit and the live-proof unit now check each other daily.

| Unit | Checks on each run | Alert on failure |
|---|---|---|
| Audit | a settlement record exists for every traded station-day older than 48 h | `CAPTURE_SETTLEMENT_MISSING` |
| Audit | no day is still `INCONCLUSIVE` 8 days after it ended | `CAPTURE_AUDIT_STUCK_INCONCLUSIVE` |
| Audit | the newest live-proof roll-up is younger than 26 h | `CAPTURE_LIVE_PROOF_STALE` |
| Live-proof | an audit verdict younger than 26 h exists | `CAPTURE_AUDIT_DEADMAN` |
| Live-proof | an audit file exists for every elapsed day in the last 8 | `CAPTURE_AUDIT_FILE_MISSING` |

Each check runs in its own `try` (r8 H7 isolation). If both units are dead, AUT-6's unit health (inactive timers, failed units) and its off-host canary page (§5.1).

#### 3.11.6 Heal confirmation and heal-alert delivery

These are r8 §3.14's rules, now carried by the audit.

- **Confirm.** The audit confirms recorder watchdog heals (§3.10.3).
- **Re-send.** The audit lists every heal record from the last `HEAL_ALERT_RETRY_DAYS = 8` dates: its own and the NBP actor's, including `alert="undeliverable"`. For each one without a `delivered=true` match, it re-sends `CAPTURE_HEALED_<sha>` through `deliver_with_proof` with `attempt_kind="retry"`. A node record is re-sent only once it is older than 600 s.
- **Abandon.** Daily, for heal dates in `[today−30, today−8]`, the audit follows r8 X1's order:
  1. if a delivered record exists, write the marker;
  2. otherwise send CRITICAL `CAPTURE_HEAL_ALERT_ABANDONED_<sha>`;
  3. write the marker only after a `delivered=true` proof.
- **Age-out** (r8-final LOW). An unmarked heal older than `today−30` produces a loud `CAPTURE_HEAL_UNABANDONED heal=<sha>` log line and the roll-up field `heal_alert_unabandoned_count`.
- **Cadence.** Retries are daily now, down from r8's per-probe and hourly cadence. Only the evidentiary `HEALED` alert waits. **(r10, X-4)** The per-kill page is sent at the kill by AUT-6's `OnFailure=` notifier, not by AUT-1. The same retry and abandon rules govern `CAPTURE_WATCHDOG_EVIDENCE_GAP` (§3.10.3).
- **Exit status.** Any failed delivery makes the audit exit 1 after its writes (r8 L2), so `OnFailure=` fires.

### 3.12 Settlement writer (C1 P1-6)

Unchanged from r8 §3.9:
- `breezy-capture-settlement` runs at 13:35Z, without `Persistent`, under its own lock;
- it scans `[today−7, today−1]`;
- it appends `SettlementRecord{station, climate_day, settlement_tmax_f, basis, raw_sha256}` to `<decisions_dir>/settlement_<climate_day>.jsonl`, once per `raw_sha256`, with a venue-owned `basis`;
- an error raises `CAPTURE_SETTLEMENT_ERROR`, and a failed delivery exits 1.

New in r9: it runs under the E-7a wrapper, with its bind set to `<decisions_dir>` and `evidence/alerts/`. Under the same-bind rule, its temp file sits in `<decisions_dir>`.

### 3.13 Units, timers, memory and locks

**Programme rules:**
- Every oneshot uses `TimeoutStartSec`, never `RuntimeMaxSec`.
- No unit's [start, start + `flock -w` + `TimeoutStartSec`] meets [16:30Z, 17:10Z) (ARCH §5.2).
- Every AUT-1 unit, including each `OnFailure=` target, runs through `deploy/systemd/breezy-autonomy-bwrap` with an `AUTONOMY_BWRAP_TABLE` row (E-7a rule 1).
- Lock order: `timeout -k` → `flock -w` → wrapper.

| Unit | `OnCalendar` (UTC) | Lock, `flock -w` | Memory | `TimeoutStartSec` | Latest end | bwrap binds |
|---|---|---|---|---|---|---|
| `breezy-capture-settlement` | `*-*-* 13:35:00` | own, 30 s | `MemoryMax=256M` | 300 | 13:40:30 | `<decisions_dir>`, `evidence/alerts/` |
| `breezy-capture-audit` | `*-*-* 13:50:00` | `breezy-studies.lock`, 600 s, `breezy-studies.slice` | `MemoryHigh=768M`, `MemoryMax=1G` | 1500 | 14:25 | `evidence/capture/audit/`, `evidence/capture/heal/`, `evidence/capture/heal_alert_abandoned/`, `derived/verdicts/`, `evidence/alerts/`, its E-8 cache dir |
| `breezy-capture-live-proof` | `OnSuccess=` of the audit, plus a fallback timer `*-*-* 14:35:00` | own, 30 s | `MemoryMax=256M` | 300 | 14:40:30 | `evidence/capture/live_proof/`, `evidence/alerts/` |
| `breezy-capture-stall-drill` | `Sun *-*-* 12:30:00` | own, 30 s | `MemoryMax=64M` | 60 | 12:31:30 | `evidence/capture/drill/`, `health/capture-stall-drill/`, `evidence/alerts/` (plus the user-bus socket if V-9 requires it) |
| `breezy-capture-stall-drill-guard` | `Sun *-*-* 13:15:00` | none | `MemoryMax=64M` | 30 | 13:15:30 | `evidence/alerts/` (plus the user-bus socket if V-9 requires it) |
| Recorder stop hook (evidence only, **r10**) | `ExecStopPost=-` of `breezy-quote-tape.service` (event-driven) | own `health/recorder_watchdog/hook.lock`, 5 s | inherits the recorder's | bounded by `timeout -k 2 10`, inside `TimeoutStopSec` | — | `evidence/capture/stall/`, `health/recorder_watchdog/` |
| `breezy-quote-tape-rotate` (AUT-1-owned file; **r10** bound only) | existing timer, 09:00Z | none | unchanged | **`QUOTE_TAPE_ROTATE_TIMEOUT_START_SECS` = 4680** (**r11, GH1**; §3.10.2) | 10:18Z | unchanged (not an AUT-1 autonomy unit; not wrapped) |
| `breezy-station-candidate-register` (not AUT-1's; read only, **r11, GM5**) | none: only the rotate's `OnSuccess=` | studies lock, `flock -n` (never waits) | unchanged | 600 (unchanged) | 10:28Z at the latest | unchanged |

- **Launch window (r10, X-3).** A watchdog kill whose restart would meet [16:30Z, 17:10Z) is deferred by the gate itself (§3.10.1), so a stall-driven kill does not land in the window; a hung loop or a crash still restarts at once, as today. The stop hook is event-driven and evidence-only, so it runs wherever a kill lands, sends nothing and takes at most 12 s.
- **Calendar tests** (`tests/unit/test_capture_units.py`):
  - `::test_no_unit_overlaps_launch_window`
  - `::test_oneshot_units_use_timeout_start_sec_not_runtime_max_sec`
  - `::test_no_capture_timer_is_persistent`
  - `::test_cli_defers_inside_launch_window` (one case per timer CLI)
  - `::test_every_capture_unit_and_onfailure_target_runs_through_bwrap_wrapper` (E-7a)
  - `::test_recorder_unit_watchdog_config_exact` (**r10: lands in WP3 step 2 only, with the unit edit; EH1**): `Type=notify`, `NotifyAccess=all`, `WatchdogSec=600`, `WatchdogSignal=SIGTERM`, `Restart=always`, `StartLimitIntervalSec=0`, `OnFailure=breezy-autonomy-failed@%n.service`, a `TimeoutStartSec` of at least 180, no `RuntimeMaxSec`, and exactly one `ExecStopPost=-` through the wrapper with `timeout -k 2 10`.
  - `::test_rotate_bound_covers_recorder_stop_and_max_start` (**r10**, WP3 step 2; **r11, GH1**: asserts the unit literal equals `QUOTE_TAPE_ROTATE_TIMEOUT_START_SECS` and that the constant covers the sum recomputed from both unit files).
  - `::test_bound_constants_single_source` (**r11, GH1**, WP3 step 1): `recorder_max_start_s` and `rotate_timeout_start_s` are pure, and the four plan numbers (4500, 4662, 4680, 10:18Z) recompute from them. In `deploy/systemd/breezy-quote-tape*.service`, `recorder_watchdog.py` and `node_config.py`, no other literal `4200`, `4362`, `4500` or `4680` appears as a start or rotate bound.
  - `::test_station_candidate_register_has_no_deadline_in_rotate_window` (**r11, GM5**, WP3 step 2).
- **Memory.**
  - The own-lock units add ≤ 640M (256 + 256 + 64 + 64) to the ≤ 4G own-lock budget (ARCH §5.2, V14). r8's watch and watchdog (384M) are gone.
  - **(r10, R-A)** Inside the trade node, the capture actor's writer holds one Arrow stream per included table: about 14 small buffers, flushed each second and on each tick.
  - V-4 is dropped with option A. WP8's post-launch check records the node's `MemoryCurrent` at 1 h after LAUNCH against the previous day's at the same offset. Above +50 MB, the volume is revisited.
- **Common unit settings:**
  - `OnFailure=breezy-study-failed@%n.service` (AUT-6's migrated notifier);
  - `EnvironmentFile=-%h/.config/breezy/alerts.env`, re-bound read-only inside the wrapper's `--tmpfs ~/.config`. Under the E-7 credential rule, the `~/.config/breezy` venue credentials are never visible;
  - `UMask=0077`;
  - the exact interpreter;
  - E-7c: the wrapper's private `--tmpfs /tmp` and `TMPDIR=/tmp` cover pyarrow and `tempfile` scratch writes. No durable AUT-1 state is ever written under `/tmp`.

### 3.14 The 38-vs-35 divergence (with AUT-4; WP6)

Unchanged from r8 §3.12, except that its rerun runs under the E-7a wrapper. **E-7b dependency:** `scripts/analysis/nbp_shadow_parity.py` imports `breezy.adapters.polymarket_us.symbology`. WP6 therefore runs only after AUT-4's E-7b(a) move of the pure symbology helpers into an adapter-free module, and WP6's closure test (`test_parity_attribution_closure_has_no_venue_adapter_module`) must pass. If E-7b(a) is not delivered, WP6 needs its own coordinator ruling: E-7b(b) is scoped to AUT-4's `eval-offline` row only, and r9 does not stretch it.

### 3.15 Read-only closures and the one-writer property (E-7, E-7a, r8-final MEDIUM)

**Wrapper first** (E-7a rule 1). Every AUT-1 unit and the stop hook run under the shared wrapper, and their write scope is their table row (§3.13). Two things are never wrapped (the E-7a rule 5 residual): the node, and the recorder's `ExecStart`.

**AST lint** (E-7a rule 4: a lint, not a READY criterion). `tests/unit/autonomy/test_capture_read_only_closure.py::test_aut1_closures_follow_write_authority_allowlist` walks **only** the AUT-1 globs:
- `src/breezy/persistence/autonomy/capture_*`
- `src/breezy/strategy/autonomy_capture/`
- `src/breezy/strategy/forecast_quantile_ladder/{capture_adapter,plugin}.py`
- `src/breezy/adapters/polymarket_us/recorder_watchdog.py`
- `src/breezy/runtime/capture_*`
- `src/breezy/analysis/capture_*`

Other owners' modules are judged under their own tables. The lint's rules:
- It is an **allowlist** (the AUT-6 r9 AC6 ruling). `AUT1_WRITE_AUTHORITY` lists each module's permitted write sites, subprocess argvs and SQLite opens. Any call not on its row fails. That includes a write-mode `open`/`os.open`, a **non-literal** mode or flags (which fail closed), `sqlite3.connect`, `subprocess`, `os.system`, `ctypes` and `importlib`.
- A non-writer may import a cross-unit write module **only through named read-only functions** listed in the table.
- Every `reason=` passed to a capture record or a refusal must be a module-level constant; a non-constant fails.
- It is non-vacuous, with a minimum number of judged call sites per entry point, and has positive controls: a planted write in a scratch module must fail.

| Unit / closure | Modules | Write rows | Allowed argv | SQLite |
|---|---|---|---|---|
| Trade node capture | `capture_publish.py`, `capture_stream.py`, `capture_epoch.py`, `capture_actor.py`, `guarded_strategy.py` | the stream under `<capture_root>/live/<instance_id>/` (through the native writer only, owned by `CaptureStreamWriter`); `evidence/capture/epoch/` | none | none |
| Recorder process | `recorder_watchdog.py` | none (datagrams to `$NOTIFY_SOCKET`: `READY=1`, `EXTEND_TIMEOUT_USEC`, `WATCHDOG=1`) | none | none |
| Recorder stop hook | `capture_recorder_hook_cli.py` | `evidence/capture/stall/`; `health/recorder_watchdog/` | none | none |
| `breezy-capture-settlement` | `capture_settlement{,_cli}.py` | `<decisions_dir>/settlement_*.jsonl` | none | none |
| `breezy-capture-audit` | `capture_audit{,_cli}.py`, `capture_heal.py`, `capture_forecast_ref.py` (non-writer) | `evidence/capture/audit/`; `evidence/capture/heal/` (audit records); `evidence/capture/heal_alert_abandoned/`; its verdicts | the literal `journalctl` argvs (ingest, supervisor, recorder) and the read-only `systemctl --user show` argv | the E-8 snapshot copy only (`take_flock=False`) |
| `breezy-capture-live-proof` | `capture_live_proof{,_cli}.py` | `evidence/capture/live_proof/` | none | none |
| Drill and guard | `capture_stall_drill_cli.py` | `evidence/capture/drill/`; `health/capture-stall-drill/` | the two literal SIGSTOP/SIGCONT argvs | none |
| Parity attribution | `capture_parity_attribution.py` | its record | the literal rerun argv | none |

**Non-writers:**
- `capture_records.py`, `capture_ids.py`, `capture_on_change.py`, `capture_alerts.py`, `capture_reader.py`, `capture_schedule.py`;
- `node_observations.py`, the node-side watch closure (the registry watch actor's closure is AUT-5's);
- `capture_adapter.py`, `plugin.py`, `capture_node_log.py`.

**One writer** (E-7 rule 4). Each stream directory has exactly one writer: the `StreamingFeatherWriter` of the boot named by `<instance_id>`, owned by the capture actor's `CaptureStreamWriter` (R-A). Each `instance_id` is fresh per boot, so no two processes share a file. ER-6 replaces C1's "serialised by the submit-intent flock" with this rule. `test_autonomy_files_have_one_writer` gains AUT-1's rows.

### 3.16 Alert catalogue

Every row goes through `deliver_with_proof`; node rows go through `AlertOutbox.offer`. The event-string rules are r8 §3.13's:
- bare tokens, with qualifiers in `detail`;
- a closed tuple;
- `CAPTURE_EVENT_RE = ^[A-Z0-9_]{1,96}$`, checked after upper-casing any hex;
- `<sha>` suffixes of 64 lowercase hex characters.

| Event | Severity | Sender | Repeat rule |
|---|---|---|---|
| `CAPTURE_PUBLISH_FAILED` | CRITICAL | node publisher | first per cause per 300 s; suppressed counts logged |
| `CAPTURE_REFUSED` (`capture_untagged`, `capture_gap`); guard causes `exit_capture_gap`, `untagged_sell`, `untagged_buy`, `capture_order_list_refused` | CRITICAL | guard | per event |
| `CAPTURE_VENUE_SILENT` | WARNING | node `md_feed_freshness` | on the transition, then hourly while it holds |
| `NBP_CYCLE_MISSED` | CRITICAL | NBP actor | once per cycle |
| `CAPTURE_EPOCH_UNREADABLE` | CRITICAL | capture actor | once per boot |
| `CAPTURE_HEALED_<sha>` | INFO | NBP actor; audit | once per heal; the audit re-sends daily until delivered |
| `CAPTURE_HEAL_ALERT_ABANDONED_<sha>` | CRITICAL | audit | per heal still unmatched after 8 days, until delivered; the marker is written after proof |
| `CAPTURE_STREAM_TYPE_FLAT` (**r10, EH4**) | CRITICAL | capture actor | once per table per boot |
| `CAPTURE_WATCHDOG_EVIDENCE_GAP` (**r10, EM1**) | CRITICAL | audit | per unproven watchdog invocation; re-sent daily for 8 days, then the abandon order (§3.10.3) |
| `CAPTURE_JOIN_GAP`, `CAPTURE_TAPE_INGEST`, `CAPTURE_NBP_CENSUS`, `CAPTURE_AUDIT_ERROR`, `CAPTURE_REFUSAL_REFS_UNRESOLVED`, `CAPTURE_SETTLEMENT_MISSING`, `CAPTURE_AUDIT_STUCK_INCONCLUSIVE`, `CAPTURE_LIVE_PROOF_STALE` | CRITICAL | audit | per audited day; a failed delivery exits 1 |
| `CAPTURE_AUDIT_DEADMAN`, `CAPTURE_AUDIT_FILE_MISSING` | CRITICAL | live-proof | per run; a failed delivery exits 1 |
| `CAPTURE_SETTLEMENT_ERROR` | CRITICAL | settlement | per failing station-day |
| `CAPTURE_DRILL_NOT_HEALED`, `CAPTURE_DRILL_SKIPPED` | CRITICAL | drill guard; drill | per drill slot; the guard exits 1 after SIGCONT if a delivery fails |

**Not AUT-1's (r10, X-4, X-6, X-7):** the per-kill page, the storm page (`watchdog_restart_storm`) and the deferral WARN (`watchdog_restart_deferred`) are AUT-6's. r9's `RECORDER_WATCHDOG_KILL` and `RECORDER_WATCHDOG_STORM` are removed from `CAPTURE_ALERT_EVENTS`. The recorder's own log markers (`RECORDER_WATCHDOG_WITHHELD`, `RECORDER_WATCHDOG_DEFERRED`, `RECORDER_SAMPLE_FAILED`, `RECORDER_PINGER_DIED`, `RECORDER_HOOK_FAILED`) are journal lines, not alerts.

**Removed with r8's watch and watchdog:**
- `RECORDER_HUNG`, `RECORDER_STALLED`, `RECORDER_WRITER_STALL`, `RECORDER_UNHEALED` and `RECORDER_INACTIVE`. These are replaced by the watchdog kill, or by AUT-6's failed-unit alert.
- `RECORDER_HEARTBEAT_NEVER_SEEN` and `RECORDER_BYTES_STALE_AWAITING_HEARTBEAT`.
- `NWS_INGEST_HUNG` and `NWS_GATE_NOT_OPEN`, now covered by AUT-6's feed freshness.
- `CAPTURE_WATCHDOG_*`, `CAPTURE_WATCH_STALE`, `CAPTURE_WRITE_FAILED`, `CAPTURE_BYTE_CAP` and `CAPTURE_PAYLOAD_COLLISION`.

---

## 4. Work packages

**Gate for every WP:**

```
scripts/ci/run_tests_no_egress.sh; echo EXIT=$?          # full gate, exact interpreter; read EXIT (L-43)
cd <tree root> && lint-imports                            # console script; must print "N kept, 0 broken"
scripts/ci/run_tests_no_egress.sh tests/unit/test_mypy_ratchet.py
```

**Environment rules:**
- In a worktree, set `PYTHONPATH=<worktree>/src`.
- Never run `uv`, `pip`, `uv run` or `git stash`.
- Unit-launched gates use `-p LimitNOFILE=524288`.

**Tests that must stay green unedited:**
(**r10, EL2:** paths pinned, checked 2026-10-03)
- `tests/unit/test_forecast_quantile_ladder_manifest_and_markers.py::test_exec_client_is_byte_identical_to_its_pre_sl13_sha256`
- `tests/unit/test_execution_egress_firewall_guard.py`
- `tests/unit/test_operator_control_assignment_scan.py`
- `tests/unit/test_shadow_only_false_is_only_the_gate_output.py`
- `tests/unit/test_live_orders_ruling_deploy_copy_matches_evidence.py`
- `tests/contract/test_native_order_cap_wiring.py`
- `tests/contract/test_risk_engine_ordering_enforcement.py`
- `tests/unit/test_probe_containment.py::test_pyproject_addopts_deselect_the_probe_markers`
- every existing `tests/strategy/forecast_quantile_ladder/*` test
- `tests/unit/test_quote_tape_recorder.py` and `tests/unit/test_quote_tape_storage_hygiene.py`

**G-ERR (errata gate):**
- WP1, WP5 and WP8 do not merge until the coordinator adopts ER-1…ER-7 and ER-10, or rules otherwise.
- WP3's watchdog activation (step 2) waits on ER-8 (reduced), AUT-6's E-11, and AUT-6's `breezy-autonomy-failed@` notifier being merged and linked (X-4: the unit's `OnFailure=` must reach a real notifier).
- WP0, WP2, WP4 and WP6 are unaffected.

**Binding in every WP brief:**
- `reviews/AUT-1-r8-final.md`'s items, as re-applied in §R9;
- ARCH errata E-1…E-10, E-7a, E-7b, E-7c and E-8a;
- the final items of any r10 review, and AUT-6 r15's cross-plan contract tests (§3.10.0).

### AUT-1a

#### AUT-1.WP0: premises and measurements (characterisation; mutation evidence per L-33)

**Files.**
- `tests/unit/test_aut1_l1_nautilus_premises.py` (new)
- `docs/evidence/AUT1_WP0_premises_<date>.md` (new)
- Scratch systemd units only, named `claude-aut1wp0-*` under `~/.config/systemd/user/`, then removed and `daemon-reload`ed afterwards (the AUT-6 r9 precedent). No `breezy-*` unit is touched.

**Verify-first premises.** Each one is a characterisation test that fails against a recorded mutation.

| # | Premise | Test / measurement | If it fails |
|---|---|---|---|
| V-1 | **Every `@customdataclass` schema is registered before the first write.** | `::test_capture_types_registered_before_kernel_writer_exists`: build `CAPTURE_INCLUDE_TYPES` in a fresh interpreter and assert that each class is in `list_schemas()` before any `StreamingFeatherWriter` is built. Mutation: define a type after the writer is constructed, and show the `KeyError` at `writer.py:460` propagating into the publisher. | Reorder the imports; the test stays as the guard. |
| V-1b | The decorator rejects `Optional` and `Decimal` fields. | `::test_customdataclass_rejects_optional_and_decimal_fields` (`custom.py:259-265`) | None (it pins the §3.4.1 encoding rule). |
| ~~V-2~~ | **Dropped (r10, R-A)** with option A: no config dump. | — | — |
| V-3 | No included native type, and no `ForecastPoint`, fails to serialise (**r10**: re-targeted to option B). | `::test_streamed_native_event_serialisation_never_raises` over recorded FQ `OrderInitialized`/`OrderFilled`/`Position*` events and recorded `ForecastPoint`s; `::test_msgbus_handler_exception_unwinds_into_publisher` (`component.pyx:2832-2834`) as the wrapper's rationale. The handler-order test is dropped. | A failing type returns to review before WP8 (it would latch `capture_gap`). |
| ~~V-4~~ | **Dropped (r10, R-A)** with option A: no `"*"` subscription. RSS is checked after LAUNCH (§3.13). | — | — |
| V-5 | A custom type with no `instrument_id` writes one regular file and is never silently dropped. | `::test_custom_type_without_instrument_id_writes_regular_file`. Mutation: add `instrument_id: InstrumentId`, with the instrument absent from the cache → zero rows (`writer.py:230-239`). | — |
| V-6 | The streamed `OrderInitialized` string forms recompute `intent_fingerprint`. | `::test_order_initialized_stream_fields_recompute_intent_fingerprint`, against a real `LimitOrder` (YES and NO leg) | The reader maps the enum strings, and the evidence file names the map. |
| V-7 | **The cache is populated before the strategy handler runs.** | `::test_quote_tick_cached_before_on_quote_tick` (`engine.pyx:2716` < `:2728`); `::test_depth_frame_is_not_cached_before_on_order_book_depth` (`:2691-2696`). Measurement: over 14 tape days, the fraction of FQ depth-triggered evaluations whose instrument has no cached quote. | The depth-only fraction is recorded, and §3.7.1's "missing never vetoes" rule stands. |
| V-8 | **(r10, X-1, X-2, X-5, EH1)** On a scratch `Type=notify`, `NotifyAccess=all` python unit (`claude-aut1wp0-*`) with `WatchdogSec=20`, `TimeoutStartSec=15`, `OnFailure=` a scratch target and `ExecStopPost=-` a scratch hook: (a) `EXTEND_TIMEOUT_USEC=30000000` sent every 5 s keeps the unit `activating` past 60 s with no `Result=timeout`, and stopping it gives `Result=timeout` within ~30 s; (b) no watchdog fires before `READY=1`; (c) after READY, withheld pings give `Result=watchdog`, and `Restart=always` restarts; (d) the hook sees `SERVICE_RESULT=watchdog` and a non-empty `$INVOCATION_ID` equal to the journal's; (e) a hook that exits 1 or is killed by `timeout` leaves `Result=watchdog` unchanged; (f) `NOTIFY_SOCKET` is absent under `Type=simple`, `NotifyAccess=none` (step-1 posture). | The plan returns to review. If (a) fails, the fallback is a base `TimeoutStartSec` ≥ `QUOTE_TAPE_MAX_START_SECS`, with the rotate constant recomputed from it (**r11, GH1**: no hand-written number). |
| V-9 | **`sd_notify` and user-bus clients work under the E-7a bwrap wrapper.** | The same scratch unit, with `ExecStart` running through `bwrap --ro-bind / / --dev /dev --proc /proc --unshare-pid --new-session --die-with-parent`: (a) a datagram `sendto($NOTIFY_SOCKET)` across the read-only bind is accepted with `NotifyAccess=all` (negative control: with `=main` the main PID is bwrap's, so the datagram must be refused); (b) `systemctl --user show` and `journalctl --user` (the audit and drill argvs) work across the read-only bind; (c) if `AF_UNIX` connect fails with `EROFS`, retry with a `--bind` of the socket inode only. | The recorder stays unwrapped (it already is). The audit and drill rows gain the socket bind, and the evidence file states which. |
| V-10 | systemd 259 sends SIGCONT after the watchdog signal to a SIGSTOPped main process. | A scratch unit, SIGSTOPped, with `WatchdogSec=20` and `WatchdogSignal=SIGTERM` | The drill guard sends SIGCONT at +90 s instead of at 13:15Z. |
| V-11 | Tape coverage of node frames. | Over 14 days, the fraction of logged Take and on-change refusal `(instrument_id, ts_event)` pairs that are present in the recorder catalog | Sets the strictness of legs B and R6. |
| V-12 | **(r10, R-B; replaces r9's derived-store premise)** The `ForecastPoint` stream reproduces FQ's vector. | `::test_forecast_point_topic_pinned_by_publish_probe` (the exact topic `NbmQuantileActor._publish` uses reaches the capture actor's handler); `::test_capture_actor_subscribed_before_first_forecast_publish` (actor order plus the asynchronous first poll); `::test_forecast_point_streams_to_regular_custom_file` (no `instrument_id`); and a replay of one recorded FQ day showing `resolve_forecast_ref` equals the vector FQ held at every Take and at a 1% sample of refusals, including one reissue. | The plan returns to review. |
| V-13 | `_watch_feed`'s cadence; `sample_feed_health` runs on the event loop. | Read `_feed_watch_interval_secs`; `::test_sample_feed_health_runs_on_loop_thread` | Adjust the ping period. |
| V-14 | The `fill_by_fingerprint` `<day>` derivation; the supervisor spawn lines; one `SHADOW_DECISION` per evaluation; the Nautilus disposal-line text. | r8 WP0 items 8, 10, 11 and 12, unchanged | As r8. |
| V-16 | **(r10, EM3)** Each streamed native event reaches the wrapper's handler, and is counted, once per event `id`. | `::test_native_event_counted_once_per_event_id` over a recorded FQ order lifecycle | The wrapper counts distinct ids only (already the rule). |
| V-17 | **(r10, EH4)** Each of the writer's three silent drops leaves its table's count rising with its bytes flat. | `::test_each_silent_writer_drop_is_seen_by_the_per_type_check`, by mutation: a raising `write_table`, an empty serialisation, an unregistered class | The plan returns to review. |
| V-18 | **(r10, X-5)** A quiet feed starts. | The V-8 scratch unit, sending `READY=1` with frozen counters: active for ≥ 60 s with no `Result=timeout`, and no watchdog before the counters' silence budget | The plan returns to review. |
| V-15 | Every wrapped AUT-1 entry point's closure is free of venue-adapter modules; `submit_chain.py` is not byte-pinned. | Use AUT-6 r12's static module-level walk (with its positive control) over the planned post-move imports of the audit (now including `capture_forecast_ref.py` → `strategy.ladder_ev.forecast_state`), settlement, live-proof, hook and drill. Grep `tests/` for any sha pin on `exec/submit_chain.py`. | If `submit_chain.py` is pinned, `intent_fingerprint` is re-implemented in `exec_intent.py`, and a parity test over 1,000 random orders pins it equal to the adapter's; the pin is never edited. |
| V-19 | **(r11, GM2)** The per-write `(size, creation_time)` delta from `get_current_file_info()` sees every silent drop and has no false positive. | `::test_per_write_delta_flags_each_silent_drop` by mutation: a raising `write_table` (`writer.py:285-288`), an empty serialisation (`:261`), and an unregistered class (`:250-255`) each give exactly one drop; **(r12, item 1)** so do an empty serialisation and a raising `write_table` on the **first** write of a lazily created `custom_` table (key absent before, `(0, t)` after; `::test_first_write_to_lazily_created_table_with_zero_size_is_a_drop`). `::test_per_write_delta_has_no_false_positive` gives zero drops for an id already in the dedupe window, a class outside `include_types`, a `SCHEDULED_DATES` rotation inside the call (including a sparse table whose size returns to 0), and the successful first write of a lazily created custom table (absent before, `size > 0` after). `::test_capture_include_types_use_plain_str_size_keys` checks the key shape. All run against a real `StreamingFeatherWriter` on a scratch directory, with a `TestClock` crossing 00:00Z. | The plan returns to review (the detector would starve fills). |
| V-20 | **(r11, GM1)** `DISCOVERY_ATTEMPT_BUDGET_S = 180` covers a legitimate connect-time attempt, and there is no transport-level retry inside one request. | Over 14 days of recorder journals: the duration of every `initialize()` attempt, from the `Initializing instruments...` and `empty-discovery retry` lines, and the pages per attempt. Read `http.py`/`transport.py` for any retry loop. | If p99 > 90 s, or a transport retry exists, the plan returns to review with the budget re-derived. The budget is never raised silently. |
| V-21 | **(r11, GM3)** Each recorder process start writes exactly one `live/<instance_id>/config.json`, with mtime within 60 s of the journal's start time for that invocation, and a `try-restart` writes a new one. | Over 14 days, match `config.json` mtimes against the recorder's journal `Started` entries; on a scratch `claude-aut1wp0-*` copy of the recorder ExecStart pointed at a scratch catalog root, two starts give two directories. **(r12, item 4)** The count is by `config.json` mtime, never directory mtime: assert that over the 14 days every journal start matches exactly one `config.json` mtime, and that at least one old directory has a directory mtime inside a later trading day (an ingest marker write, `quote_tape_ingest_core.py:407-437`) while its `config.json` mtime is not, so a directory-mtime count would overcount. `::test_boot_count_uses_config_json_mtime_not_dir_mtime` is the unit-level pin. | The boot-count source is dropped, `recorder_stale` keeps only the hook file, and the blind window stands as stated (§3.10.2). |
| V-22 | **(r11, GM5)** `breezy-station-candidate-register` has no deadline inside the rotate window. | Re-read the unit, its run script and the rotate unit; run `systemctl --user show breezy-station-candidate-register.service -p TriggeredBy -p TimeoutStartUSec`; grep `deploy/systemd/*.timer` for it. Expected: no timer, `flock -n`, 600 s, `OnSuccess=` only. | If a timer or a blocking lock appears, the rotate bound returns to review before WP3 step 2. |
| V-23 | **(r12, item 5)** No unit moves, renames, compresses or deletes `catalog/quote_tape/polymarket_us/live/<instance_id>/` directories or their `config.json`. | Re-read every `deploy/systemd/*.service` and every script or module its `ExecStart` runs that names the quote-tape root; record each operation on `live/<instance_id>/`. Planning-time reading, 2026-10-03 @ `f45f5a65`: `breezy-quote-tape-ingest` (`*:0/15`) only creates/unlinks dotfile markers inside instance directories (`quote_tape_ingest_core.py:304-305`, `:407-437`, `:485-502`) and writes the parquet catalog elsewhere; `quote_tape_salvage.py` only touches markers (`:146`, `:167`) and never the source; the recorder's disk monitor only reads (`quote_tape_disk_monitor.py:167-179`); `breezy-decisions-retention` gzips only `catalog/quote_tape/decisions/` (`decisions-retention-run.sh:19`); the replay, score, position-monitor and station-register scripts only read the root. No mover or compressor exists. | Recorded in the evidence file either way. A mover means the boot count can only undercount (safe for a restrictive veto; the hook file stays primary); §3.7.4 states it and the plan does **not** return to review. |

**Measured**, as one studies-flock job outside 01:00–04:30Z under `MemoryMax=4G`:
- the full-UTC-day stream volume (§3.2);
- r8's D8 silence and writer-stall statistics, for the gate thresholds;
- the drill slot;
- V-7 and V-11;
- **(r10)** the `ForecastPoint` rows per day.

**GREEN.** All pass on 1.231.0. The evidence file states every constant. **(r10, R-A)** There is no option A/B decision: option B is ruled.

**Activation.** None.

#### AUT-1.WP1: record types, ids, publisher, stream config, reader

**Files.**
- `src/breezy/persistence/autonomy/capture_{records,ids,on_change,publish,stream,reader,alerts,epoch,schedule}.py` (new)
- `src/breezy/persistence/exit_tags.py` (edit)

**RED first** (`tests/unit/autonomy/`):
- `test_capture_records.py`: `::test_capture_record_field_sets_are_exact`, `::test_no_capture_record_field_is_named_instrument_id`, `::test_null_encoding_is_empty_string_and_zero`, `::test_records_round_trip_through_registered_arrow`, `::test_schema_strings_are_versioned`
- `test_capture_ids.py`: r8's id tests (`::test_decision_id_recomputes_from_stored_record`, `::test_decision_id_unique_per_take`, `::test_exit_decision_id_uses_only_the_four_exit_tag_values`, …), plus `::test_same_frame_quote_and_depth_get_distinct_ids`, `::test_eval_seq_counter_is_bounded_per_instrument`, `::test_nonmonotone_ts_event_never_repeats_an_ordinal`
- `test_capture_on_change.py`: r8's four tests
- `test_capture_publish.py`: `::test_write_exception_never_raises_and_sets_health_not_ok`, `::test_publish_failure_offers_critical_deduped_per_cause_per_300s`, `::test_health_clears_only_on_heartbeat_flush_and_per_type_pass`, `::test_custom_records_never_cross_the_msgbus` (R-A), `::test_flush_for_submit_failure_returns_false`, **(r11, GM2)** `::test_flush_for_submit_false_after_any_drop_since_previous_submit_flush`, `::test_heartbeat_written_by_type_excludes_itself` (GL1)
- `test_capture_stream.py`: `::test_capture_root_is_disjoint_from_quote_tape_root`, `::test_include_types_exact` (with `ForecastPoint`), `::test_rotation_matches_recorder_constants`, `::test_canary_writer_root_is_capture_root_canary`, `::test_wrapper_catches_serialize_batch_outside_writer_try`, `::test_write_before_open_returns_false`, `::test_table_bytes_refuses_symlinks`, `::test_no_config_json_is_written`; **(r11, GM2)** `::test_unchanged_size_and_creation_time_is_a_drop_sets_health_not_ok`, `::test_rotation_reset_counts_as_success`, `::test_dedupe_and_excluded_class_are_not_judged`, `::test_midnight_rotation_is_not_type_bytes_flat`, `::test_drop_is_counted_and_never_retried`, **(r12, item 1)** `::test_first_write_to_lazily_created_table_with_zero_size_is_a_drop`, `::test_first_write_to_lazily_created_table_with_rows_is_success`
- `test_capture_reader.py`: `::test_projection_yields_c1_record_names_and_fields`, `::test_order_link_projected_from_order_initialized_tags`, `::test_position_mark_projection_applies_no_leg_sign`, `::test_frame_ref_resolution_order_copy_then_tape`, `::test_forecast_input_ref_carries_available_at_ns`, `::test_truncated_final_batch_is_stream_torn_tail`, `::test_join_exposes_stored_eval_seq_never_recomputed`, `::test_reader_refuses_symlinks`
- `test_capture_alerts.py`, `test_capture_epoch.py`, `test_capture_schedule.py`: r8's tests
- **(r10, R-B)** `tests/unit/test_capture_forecast_ref.py`: `::test_forecast_ref_resolves_to_vector_equal_to_strategy_state`, `::test_reissue_replays_as_fq_pushed_it`, `::test_vintage_mismatch_is_unresolved`, `::test_absent_value_points_are_skipped_as_fq_skips_them`
- `test_capture_read_only_closure.py`: `::test_aut1_closures_follow_write_authority_allowlist`, `::test_non_literal_open_mode_fails_closed`, `::test_reason_values_are_constants`, `::test_lint_has_positive_control`
- `test_autonomy_payload_hygiene_scan` and `test_autonomy_files_have_one_writer`, widened with AUT-1's rows (L-12)

**GREEN.** All pass, `lint-imports` is clean, and neither `capture_ids` nor `capture_on_change` imports Nautilus.

**Activation.** Library only.

#### AUT-1.WP2: FQ adapter, plugin entry, guard library

**Files.** `src/breezy/strategy/forecast_quantile_ladder/{capture_adapter,plugin}.py` and `src/breezy/strategy/autonomy_capture/guarded_strategy.py` (new).

**RED first:**
- r8's adapter and guard tests, re-targeted to the publisher;
- `::test_link_write_failure_refuses_buy_capture_gap` becomes `::test_publisher_health_not_ok_refuses_buy_capture_gap`;
- new: `::test_take_publishes_frame_copy_before_decision_record`, `::test_refusal_never_publishes_frame_copy`, `::test_capture_gap_refusal_cites_frame_by_reference_only` (the r8-final MEDIUM question);
- `::test_every_full_plugin_kind_strategy_subclasses_capture_guard` stays RED-pending-WP7. This is recorded in the WP's evidence; the test is not `xfail`ed.

**GREEN / Activation.** As r8 WP2: library only.

#### AUT-1.WP3: recorder watchdog gate, pinger, evidence-only stop hook, unit edits (r10)

**Files, step 1 (code only).**
- `src/breezy/adapters/polymarket_us/recorder_watchdog.py` (new)
- `src/breezy/adapters/polymarket_us/{config,data}.py` (edit: the opt-in flag; the pinger at the top of `_connect`; `mark_ready()` after the initial subscribe; the EM6 accessors and the `depths_published` counter)
- `src/breezy/runtime/node_config.py` (edit: `watchdog_notify=True` on the recorder only)
- `src/breezy/runtime/capture_recorder_hook_cli.py` (new) and its `AUTONOMY_BWRAP_TABLE` row `breezy-quote-tape.stop-hook`
- `tests/fixtures/recorder_watchdog/deferred_journal_line.json` (new; the X-7 fixture AUT-6 reads)
- **(r11, GL1)** `tests/fixtures/recorder_watchdog/pending_recorder_unit.service` (new): the step-2 recorder unit text, read by `test_classifier_timing_constants_equal_unit_file` in step 1. It is a test fixture, never linked into the user manager.
- **(r11, GH1)** `src/breezy/runtime/node_config.py` also gains `QUOTE_TAPE_MAX_START_SECS` and `QUOTE_TAPE_ROTATE_TIMEOUT_START_SECS`, and `tests/unit/test_capture_units.py::test_bound_constants_single_source` lands in step 1.

**Files, step 2 (units only; EH1).** `deploy/systemd/breezy-quote-tape.service` and `deploy/systemd/breezy-quote-tape-rotate.service` (edit), with `tests/unit/test_capture_units.py::test_recorder_unit_watchdog_config_exact`, `::test_rotate_bound_covers_recorder_stop_and_max_start`, `::test_station_candidate_register_has_no_deadline_in_rotate_window` (**r11, GM5**), `tests/unit/test_recorder_watchdog.py::test_pending_recorder_unit_fixture_equals_deployed_unit_lines` (**r11, GL1**), and the deployed-unit case of `::test_classifier_timing_constants_equal_unit_file`, whose fixture case already ran in step 1 (**r11, GL1**). No unit edit lands in step 1: the unit is symlinked into the user manager.

**Step-2 gate (r11, GM4).** `tests/unit/autonomy/test_capture_dependencies.py::test_aut6_unit_health_tolerates_activating_within_start_budget` must be GREEN before step 2 merges, in the same way `test_aut6_node_liveness_detector_covers_log_mtime_and_tape_advance` gates WP8. It cites AUT-6 r15-final binding build item 7. It drives AUT-6's real unit-health and liveness classifiers (#21, #22, `watchdog_disarmed`, the gate cross-check) with a recorder `ActiveState=activating`/`SubState=start` at `QUOTE_TAPE_MAX_START_SECS − 60` and asserts healthy. Its positive control is the same state at `QUOTE_TAPE_MAX_START_SECS + 60`, which must page. It stays RED until AUT-6 WP4 lands; it is never `xfail`ed. **(r12, item 6)** `tests/unit/autonomy/test_capture_dependencies.py::test_aut6_rotate_bound_test_reads_constants_not_literals` gates step 2 the same way (§3.10.2).

**RED first (step 1):**
- `tests/unit/test_recorder_watchdog.py`: `::test_ok_streaming_pings`, `::test_empty_listing_with_fresh_reload_pings`, `::test_empty_listing_with_reload_older_than_twice_delay_withholds`, `::test_discovering_within_budget_extends_start_timeout`, `::test_discovering_overrun_stops_extending`, `::test_connecting_overrun_stops_extending`, `::test_safe_mode_overrun_withholds`, `::test_frozen_counters_and_bytes_withhold_after_stream_silence`, `::test_one_event_flat_bytes_over_writer_stall_withholds`, `::test_event_inside_flush_margin_still_pings`, `::test_quiet_hours_use_wp0_multiplier`, `::test_midnight_rotation_is_not_writer_stall`, `::test_dead_feed_watch_withholds_feed_watch_dead`, `::test_launch_window_defers_and_journals_once_per_stall`, `::test_deferral_ends_at_1710z_and_withholds`, **(r12, item 2)** `::test_pre_ready_withhold_is_never_deferred`, `::test_extension_deadline_never_exceeds_max_start_budget`, `::test_sd_notify_without_socket_is_false_never_raises`, `::test_sd_notify_abstract_namespace_socket`, `::test_withheld_line_logged_at_most_hourly`, `::test_trade_node_config_never_sets_watchdog_notify`, `::test_deferred_fixture_matches_logged_line`; **(r11)** `::test_discovery_attempt_inflight_over_budget_stops_extending` (GM1), `::test_retry_sleep_between_attempts_stays_ok` (GM1), `::test_classifier_timing_constants_equal_unit_file` (fixture case, GL1)
- `tests/unit/test_recorder_watchdog_pinger.py` (EH1, EM2, X-5): `::test_pinger_task_created_first_in_connect`, `::test_pinger_runs_while_initialize_retries_empty_listing`, `::test_quiet_feed_start_sends_ready_without_any_counter_advance`, `::test_ready_not_sent_before_subscribe_and_sent_once`, `::test_connect_failure_never_sends_ready`, `::test_watchdog_sent_only_after_ready`, `::test_sample_exception_logs_recorder_sample_failed_counts_and_withholds`, `::test_sample_exception_never_ends_the_pinger`, `::test_pinger_death_logs_recorder_pinger_died`, `::test_pinger_runs_on_the_loop_thread`; **(r11, GL1)** `::test_second_connect_does_not_start_a_second_pinger`, `::test_pinger_task_strongly_referenced_and_cleared_on_disconnect`, `::test_ready_sent_once_across_reconnects`
- `tests/unit/test_polymarket_us_recorder_accessors.py` (EM6): `::test_phase_transitions_discovering_connecting_streaming_safe_mode`, `::test_depths_published_counts_handed_depths`, `::test_discovered_slugs_and_subscribed_count_read_only`, `::test_reload_accessors_set_by_update_instruments`, **(r11, GM1)** `::test_discovery_attempt_inflight_since_set_around_initialize_and_cleared_in_finally`
- `tests/unit/test_capture_recorder_hook.py` (X-4, EM1): `::test_watchdog_result_writes_stall_record_with_invocation_id_and_state`, `::test_success_result_is_a_no_op` (the 09:00Z rotate), `::test_trading_day_boundary_is_1645z`, `::test_hook_takes_its_own_lock`, `::test_lock_timeout_logs_recorder_hook_failed_and_exits_zero`, `::test_missing_invocation_id_logs_recorder_hook_failed_and_exits_zero`, `::test_write_error_logs_recorder_hook_failed_and_exits_zero`, `::test_hook_module_imports_no_alert_sender`
- `tests/unit/autonomy/test_capture_alert_contract.py`: r8's verbatim-event tests, with `CAPTURE_STREAM_TYPE_FLAT` and `CAPTURE_WATCHDOG_EVIDENCE_GAP` added and `RECORDER_WATCHDOG_KILL`/`STORM` removed

**GREEN.** All pass; `tests/unit/test_quote_tape_recorder.py`, `tests/unit/test_quote_tape_storage_hygiene.py` and every existing `tests/unit/test_polymarket_us_*` test are unedited; AUT-6's `test_aut6_watchdog_contract.py` passes against the classifier and pinger once AUT-6 WP4 lands.

**Activation: two steps.** The technical reason: a `Type=notify` unit whose code cannot send `READY=1` fails every start (AUT-6 R-40), and a watchdog with no pinger kills a healthy recorder.
1. **Code on merge.** The code goes live at the next 09:00Z rotate. Under today's `Type=simple`/`NotifyAccess=none`, `NOTIFY_SOCKET` is unset (V-8 (f)), so every send is a no-op returning False, and the hook is not yet in the unit. Check the boot line `RECORDER_WATCHDOG_GATE notify_socket_present=False` and the gate's hourly withheld/OK summary for one full day: zero withheld classifications outside the 09:00–10:30Z listing hole, and READY requested exactly once per boot.
2. **Units after G-ERR (ER-8, E-11) and AUT-6's notifier.** One reviewed commit edits both unit files and their tests; then `daemon-reload`. The change takes effect at the next 09:00Z rotate. Then confirm `systemctl --user show -p Type,NotifyAccess,WatchdogUSec,TimeoutStartUSec,OnFailure breezy-quote-tape.service`, that the rotate ended `Result=success` (its blocking `try-restart` returned at READY), and that the hook was a no-op on that rotate. AUT-1 restarts nothing to activate: the rotate is the existing timer.

#### AUT-1.WP4: NBP silent-feed check and hang reset (on the existing timer)

**Files.** `src/breezy/ingest/nbm_quantile_actor.py`.

**RED first:**
- `tests/unit/test_nbm_quantile_actor.py`: `::test_submit_retains_future`, `::test_poll_hang_is_cancelled_and_reset_after_threshold`, `::test_missed_cycles_counts_from_stale_deadline`, `::test_first_fire_past_deadline_offers_nbp_cycle_missed_once_per_cycle`, `::test_check_runs_on_existing_cycle_timer_no_new_timer`, `::test_poll_reset_followed_by_vector_complete_writes_write_once_heal_record`, `::test_nbp_heal_with_absent_alert_offer_logs_critical_and_writes_undeliverable`, `::test_actor_without_alert_offer_constructs_unchanged`
- FQ side: `tests/strategy/forecast_quantile_ladder/test_aut1_nbp_freshness.py`, r8's five tests, now reading `missed_cycles`

**GREEN.** All pass, and the existing actor tests are unedited.

**Merge and activation.** Merged only in WP8's train (r8 r6-T2), so it activates at WP8's LAUNCH.

#### AUT-1.WP5: settlement, audit, node-log parser, heal, live-proof

**Files.**
- `src/breezy/analysis/capture_{settlement,settlement_cli,audit,audit_cli,node_log,heal,live_proof,live_proof_cli}.py` (new)
- `src/breezy/domain/exec_intent.py` (new); `src/breezy/adapters/polymarket_us/exec/submit_chain.py` (re-export shim, per V-15)
- the three units and the live-proof fallback timer
- their `AUTONOMY_BWRAP_TABLE` rows

**RED first.** r8 WP5's tests carry over, re-targeted to the stream reader: settlement, join, intent linkage, epoch, R1–R4, positive control, orders, census, fail-loud, D10, tape, NBP, canary/drill/family and provenance. Where r9 removed a test's subject (the payload store, the `.INCOMPLETE` marker, `partial_line`), its r9 counterpart replaces it: `::test_failed_to_serialize_log_line_fails_r4` and `::test_stream_torn_tail_after_boot_end_is_counted`. New tests:
- **R5 (r10, per type):** `::test_records_short_of_last_heartbeat_count_fail_stream_record_lost`, `::test_native_table_short_of_heartbeat_count_fails`, `::test_final_heartbeat_requires_exact_equality_per_table`, `::test_tail_after_last_heartbeat_of_crashed_boot_is_lost_in_flush_window_counted`, `::test_missing_record_older_than_61s_before_last_log_line_is_stream_record_lost` (EL1), `::test_lost_take_path_record_still_fails_leg_d`; **(r11)** `::test_heartbeat_table_rows_equal_count_plus_one` (GL1), `::test_nonzero_write_drops_fails_stream_write_dropped` (GM2)
- **W (r10, EM1):** `::test_watchdog_journal_entry_without_stall_record_fails_leg_w`, `::test_watchdog_journal_entry_without_delivered_notifier_marker_fails_leg_w`, `::test_fallback_page_delivery_satisfies_leg_w`, `::test_leg_w_reads_aut6_notifier_marker_by_invocation_id`, `::test_evidence_gap_alert_resent_daily_until_delivered`
- **R6:** `::test_refusal_ref_resolution_fraction_reported_and_alerted_below_baseline`
- **R7:** `::test_heartbeat_gap_over_180s_fails_stream_gap`
- **B:** `::test_frame_copy_mismatch_with_tape_fails`, `::test_forecast_ref_resolves_inside_the_boot_stream` (R-B)
- **closure (E-7/E-7a/E-7b):** `tests/unit/autonomy/test_capture_unit_closures_have_no_venue_adapter_module`; `tests/unit/autonomy/test_exec_intent_parity.py::test_exec_key_prefixes_equal_client_constants`, `::test_intent_fingerprint_shim_is_the_domain_function`; and `test_exec_client_is_byte_identical_to_its_pre_sl13_sha256`, unedited
- **fail-loud:** `::test_recorder_watchdog_unarmed_is_error` (Type, NotifyAccess=all, WatchdogUSec), `::test_unreadable_stream_file_is_error`, `::test_exec_store_read_uses_snapshot_helper_without_flock` (E-8a)
- **heal:** `::test_watchdog_kill_followed_by_streaming_instance_is_healed`, `::test_kill_followed_by_second_kill_within_30min_is_not_healed`, `::test_drill_heal_marked_injected`, `::test_heal_alert_resent_daily_until_delivered`, `::test_abandoned_marker_written_only_after_delivered_true_proof`, `::test_unmarked_heal_older_than_30_days_counts_unabandoned`
- **moved watchdog duties:** `::test_audit_alerts_settlement_missing_after_48h`, `::test_audit_alerts_stuck_inconclusive_after_8_days`, `::test_audit_alerts_live_proof_stale`, `::test_live_proof_alerts_audit_deadman_and_missing_files`, `::test_each_moved_check_isolated`
- **live-proof:** r8's roll-up tests, plus `::test_watchdog_heal_with_delivered_alert_satisfies_stall_leg`

**Runtime evidence.** One run against two real retained logs (about 2.4 GB) under `MemoryMax=1G`. If it takes longer than 15 min, the WP returns to review.

**Activation.** On merge, after G-ERR and AUT-6's notifier test:
1. Link and `enable --now` the settlement and audit timers. (Enabling a timer starts nothing until its calendar fires; AUT-1 restarts no unit.)
2. Start each unit once by hand, outside [15:55Z, 17:10Z).

Days before the epoch are `PRE_CAPTURE` by rule.

#### AUT-1.WP6: 38-vs-35 attribution (with AUT-4)

As r8 WP6, run under the E-7a wrapper.

### AUT-1b (after AUT-5a merges)

#### AUT-1.WP7: FQ hooks, `Refuse` input fields, re-base on the guard, path benchmark

**Files.**
- `src/breezy/strategy/forecast_quantile_ladder/strategy.py` (CS-0..CS-5; the base class)
- `src/breezy/strategy/forecast_quantile_ladder/decision.py` (the additive `Refuse` fields)

**RED first:**
- `tests/strategy/forecast_quantile_ladder/test_aut1_capture_hooks.py`: r8's plumbing, Take-capture and outcome-record tests, re-targeted to the publisher, minus `::test_frame_clock_stamped_before_evaluation`. New: `::test_refuse_carries_p_hat_margin_and_ev_net_when_computed`, `::test_not_executable_and_not_dplus1_carry_null_inputs`, `::test_shadow_line_bytes_unchanged_by_refuse_input_fields`, `::test_refuse_input_fields_equal_the_values_evaluate_compared`, `::test_decision_record_carries_frame_and_forecast_refs` (with `forecast_available_at_ns`, R-B).
- `tests/unit/autonomy/test_capture_submit_sites.py`: r8's five tests.
- `::test_every_full_plugin_kind_strategy_subclasses_capture_guard` turns GREEN.

**Benchmark.** `docs/evidence/AUT1_WP7_capture_path_<date>.md` records p50/p99/p99.9 from CS-1 to `super().submit_order`, over 1,000 Takes (each including the synchronous `flush()`, EM4) and 10,000 refusals, against a real `CaptureStreamWriter`. The budget is `CAPTURE_PATH_P99_BUDGET_MS = 5`, which is never raised; a result above it blocks the merge.

**GREEN.** All pass, plus every existing FQ test and `tests/unit/test_forecast_quantile_ladder_boot.py`, unedited.

**Activation.** Through WP8's LAUNCH.

#### AUT-1.WP8: capture actor, detectors, epoch, streaming wiring, composition hunk

**Files.**
- `src/breezy/strategy/autonomy_capture/{capture_actor,node_observations}.py` (new)
- `src/breezy/runtime/node_config.py` (**r10, EM5**: the optional `instance_id` parameter; no `StreamingConfig`, no `register_config_encoding`)
- `src/breezy/strategy/forecast_quantile_ladder/composition.py` (edit)
- `src/breezy/app/trade.py` (one hunk, rebased after AUT-5a)

**RED first** (`tests/unit/autonomy/test_capture_actor.py` unless named):
- **order events:** `::test_unstreamed_set_is_computed_from_list_schemas`, `::test_order_denied_and_canceled_published_as_order_event_record`, `::test_order_event_record_never_duplicates_a_streamed_type`, `::test_order_event_decision_id_from_cache_order_tags`, `::test_handler_never_raises_into_publisher`
- **stream (r10):** `::test_heartbeat_then_flush_every_60s`, `::test_type_bytes_flat_sets_capture_gap` (EH4), `::test_heartbeat_type_flat_does_not_mask_another_table`, `::test_native_events_counted_per_type_in_heartbeat` (EM3), `::test_forecast_points_streamed_and_counted` (R-B), `::test_capture_actor_on_stop_flushes_without_closing`, `::test_capture_actor_on_dispose_writes_final_heartbeat_before_close_exception_safe`, `::test_capture_actor_issues_no_venue_or_data_subscription`, `::test_capture_actor_has_no_star_subscription`, `::test_epoch_written_at_first_capture_boot_and_logged`
- **guard flush (r10, EM4):** `tests/unit/autonomy/test_capture_guard.py::test_buy_flushes_before_super_submit`, `::test_flush_failure_refuses_buy_capture_gap`, `::test_flush_failure_never_refuses_exit`, **(r11, GM2)** `::test_take_path_write_drop_refuses_buy_capture_gap`, `::test_write_drop_never_refuses_exit`
- **detectors:** `::test_capture_gap_vetoes_at_boot_until_positive_control`, `::test_observation_older_than_3_ticks_vetoes_at_call_time`, `::test_md_feed_freshness_never_vetoes_observation_only` (EM7), `::test_venue_silent_counts_quote_absent_separately_no_veto`, `::test_recorder_stale_vetoes_on_storm_until_1800s_quiet`, `::test_missing_recorder_watchdog_file_never_vetoes`, `::test_unparseable_recorder_watchdog_file_vetoes`, `::test_slot_refusal_entryveto_written_once_by_cs2_not_by_detector`; **(r11, GM3)** `::test_recorder_stale_counts_boots_when_hook_record_missing` (r12 rename), `::test_rotate_boot_is_excused_once`, **(r12, items 3, 4)** `::test_recorder_boots_counts_venue_outage_restarts_and_vetoes`, `::test_boot_count_uses_config_json_mtime_not_dir_mtime`, `::test_boot_marker_scan_refuses_symlinks_and_never_runs_systemctl`, `::test_boot_scan_error_never_clears_hook_veto`
- `tests/unit/test_forecast_quantile_ladder_boot.py`: `::test_fq_composition_registers_capture_actor_and_detectors`, `::test_fq_compose_without_capture_publisher_fails_boot` (production default factory, L-55), `::test_fq_composition_wires_alert_offer_into_nbm_quantile_actor`, `::test_capture_actor_owns_native_writer_on_capture_root` (R-A), `::test_capture_node_boot_id_equals_kernel_instance_id` (EM5), and `tests/unit/test_runtime_trade_node_config.py::test_trade_config_without_instance_id_is_unchanged`
- `tests/unit/autonomy/test_capture_dependencies.py::test_aut6_node_liveness_detector_covers_log_mtime_and_tape_advance` (r8; must be GREEN before merge)

**GREEN.** All pass, and `test_shadow_only_false_is_only_the_gate_output` is unedited.

**Activation.** At the next supervisor STOP/LAUNCH (16:40/16:50Z).
- **Technical reason:** the hunk changes the boot and order path, LAUNCH re-runs every boot gate, and a hand relaunch is refused after AUT-5a.
- **Preconditions:** WP3 step 1 is live, WP5 is active, and WP4 is in the same train.
- The first LAUNCH writes `capture_epoch_start`.
- **Post-launch check:** `<capture_root>/live/<instance_id>/custom_capture_heartbeat_*.feather` is growing within 2 min of `TradingNode ... RUNNING`, the directory name equals the node log's kernel `instance_id`, `custom_forecast_point_*` exists after the first NBP poll, and the node's `MemoryCurrent` 1 h after LAUNCH is within +50 MB of the previous day's (§3.13).

#### AUT-1.WP9: weekly injected recorder stall drill

**Files.** `src/breezy/runtime/capture_stall_drill_cli.py`; the drill and guard units; their table rows.

**RED first** (`tests/unit/test_capture_stall_drill.py`): `::test_drill_refuses_when_recorder_not_active_or_young_or_outside_window`, `::test_drill_refuses_after_recent_watchdog_kill`, `::test_drill_argv_is_literal_sigstop_on_recorder_only`, `::test_guard_argv_is_literal_sigcont_on_recorder_only`, `::test_guard_alerts_not_healed_without_stall_record_after_drill`, `::test_three_consecutive_refusals_raise_drill_skipped`, `::test_drill_run_resets_refusal_count`, `::test_drill_failed_delivery_exits_nonzero`, `::test_drill_guard_failed_delivery_exits_nonzero_after_sigcont`, `::test_drill_has_no_aut6_self_heal_precondition`, `::test_drill_slot_is_outside_the_deferral_horizon` (r10, X-3).

**Activation.** Link and enable on merge, once WP3 step 2 is live.

---

## 5. Association

### 5.1 Consumed

| From | Contract | Interface |
|---|---|---|
| ARCH-0 | C1 (as amended by §ERRATA-REQUEST), C4, C5, C6, §3, §4.5 | Schemas; the verdict writer; the `CaptureAdapter`/`Detector` Protocols; `NODE_PLUGINS`; `RefusingPlugin`; `VetoReason` (`capture_gap`, `feed_stale`, `recorder_stale`, `capture_untagged`); `pins.py` (`WATCH_TICK_STALE_S`, `SELF_HEAL_RESTARTABLE_UNITS`); `test_autonomy_files_have_one_writer` |
| AUT-5a | C5 | `ResolvedFamily`, `drill_active` and the `entry_veto` slot; ownership of `try_submit` and `src/breezy/app/trade.py` until merged |
| AUT-5 | E-8, E-8a | The snapshot helper, with `take_flock=False` for the audit |
| AUT-6 | §4.6, C6, E-7a | **Consumed as is:** `deliver_with_proof`; `AlertOutbox.offer`; the shared wrapper and table; the node-liveness detector (gates WP8); unit health for the AUT-1 timers and the recorder (inactive/failed); the observation-feed freshness detector (NWS ingest). **(r10) Also consumed:** the `OnFailure=breezy-autonomy-failed@%n.service` notifier and its markers `evidence/alerts/notify/<date>/<unit>__<InvocationID>.delivered.json` (X-4; leg W), the storm page (X-6), the deferral WARN (X-7), E-11, and the r15 contract tests (§3.10.0). **Withdrawn:** r9's request that AUT-6 not `try-restart` an active recorder (AUT-6 r14 deleted its executor, so it is met by construction), and the r8 detector `aut1.recorder_stall` and its `capture_watch/v1` input. |
| AUT-2 | §5.3, Z14 | The canary producer. It now publishes the same `@customdataclass` records through `open_canary_writer` (§5.2). |
| AUT-4 | §10 | Joint owner of the 38-vs-35 fixes on the batch side |

### 5.2 Provided

| To | Contract | Interface |
|---|---|---|
| AUT-2 | C1 | **Records:** the `project_c1` views (`DecisionRecord`, `OrderLink`, `LifecycleEvent`, `PositionMark`), `join_fills_to_decisions`, `settlement_<date>.jsonl`, the epoch files and the exit ids. **Canary:** `open_canary_writer(root, cache, clock)` returns a native `StreamingFeatherWriter` on `<capture_root>/canary/<instance>/` with `CAPTURE_INCLUDE_TYPES`. **Contract:** read `eval_ns` and `eval_seq` as stored. |
| AUT-3 | C1 | `DecisionRecord` views; `resolve_forecast_ref` (**r10, R-B:** `src/breezy/analysis/capture_forecast_ref.py`, key `(station, cycle_ns, available_at_ns)`, resolved inside the boot's `ForecastPoint` stream) |
| AUT-4 | C1, C4 | `DecisionRecord` views, with `depth_ref`/`quote_ref` as **reference strings**; `resolve_frame_ref`; the `capture_tape_ingest` verdicts; the parity record |
| AUT-6 | C1, C6 | `DetectorEvent` views; the NODE_LOCAL detectors; `recorder_watchdog/v1` and the stall records (read-only); **(r10)** the gate, pinger and sender, `READY=1` (X-5), the deferral journal line `RECORDER_WATCHDOG_DEFERRED` and its fixture (X-3, X-7), `RECORDER_WATCHDOG_STORM_KILLS`, and the recorder and rotate unit lines (X-1, X-2, X-4, DH1); the HEALTH verdicts. r9's `RECORDER_WATCHDOG_KILL`/`STORM` alerts are withdrawn (X-4, X-6). |
| AUT-5 | C4 | HEALTH `capture_join_completeness`, `capture_tape_ingest` and `capture_nbp_census`. Proposed rows: `capture_join_completeness FAIL → DEMOTE` (RECOVERABLE_INFRA); the others → ALERT. r8's proposed `aut1.recorder_stall → SELF_HEAL` is **withdrawn**. |

### 5.3 Downstream impact (READY plans that cite r8 internals; grep 2026-10-03)

| Plan | Citation | r9 replacement | Action |
|---|---|---|---|
| AUT-2 r7 | `OrderLink` (13), `capture_epoch_start` (16), `PositionMark` (1) | `project_c1` keeps all three names and their fields; the epoch is unchanged | None beyond reading through `project_c1`. The canary producer uses `open_canary_writer` (brief amendment). |
| AUT-3 r6 | `derived/capture_payloads/forecast_input/<sha256>.json` (`AUT-3-retraining_plan_r6.md:68`), `forecast_input_sha256` | `forecast_input_ref` and `resolve_forecast_ref` | **Brief amendment** to AUT-3's forecast-by-digest row |
| AUT-4 r6 | `depth_ref` (6), `quote_ref` (5), `LifecycleEvent` (4), `forecast_input_sha256` (3) | Reference strings and the resolvers; `LifecycleEvent` via `project_c1` | **Brief amendment:** payload reads go through the resolvers |
| AUT-6 r13 (r15 is current) | `derived/capture_payloads/depth10/` and `capture_<family_id>_<date>.jsonl` (`AUT-6-drift-health_plan_r13.md:454`); `OrderLink`/`LifecycleEvent`/`depth_ref` (`:1249`) | `read_capture_stream` + `project_c1`; `resolve_frame_ref` | **Brief amendment.** **(r10)** AUT-6 r15 already carries X-1..X-7; r10 matches it (§3.10.0). |
| AUT-5 r7 | `capture_join*`, `capture_untagged`, `capture_gap`, `CAPTURE_INCOMPLETE` | Names unchanged | None |

The coordinator decides whether these amendments are brief-level or need plan revisions. r9 keeps every C1 **logical** name so that they can stay brief-level.

### 5.4 Execution order

```
ARCH-0 ─► WP0 ─┬─► WP1 (G-ERR) ─► WP2 (library) ─────────┐
               ├─► WP3 step 1 ─► [ER-8 + E-11 + AUT-6 notifier] ─► WP3 step 2 ─┤
               ├─► WP4 (built; merges with WP8)          ├─► [AUT-5a merged] ─► WP7 ─► WP8 (+WP4) ─► LAUNCH (epoch)
               ├─► WP5 (needs WP1; G-ERR) ───────────────┤
               └─► WP6 (evidence)                        ┘
WP3 step 2 ─► WP9 drill live (no AUT-5b dependency)
```

- **Parallel in Wave 1:** WP0 alongside AUT-5a and AUT-6. After WP0: WP1, WP3, WP4, WP6 and WP5's pure core.
- **File ownership:** as r8, minus `on_order_book_depth`'s stamp. AUT-1 also owns the additive `Refuse` fields in `decision.py`.

---

## 6. Live-proof protocol

**Artefacts:**
1. `evidence/capture/audit/<family>/<D>.json`, plus a `capture_join_completeness` verdict per day.
2. At least one heal record under `evidence/capture/heal/<date>/`, of either kind:
   - a **recorder watchdog heal** (`decided_by:"systemd_watchdog"`), paired with its stall record under `evidence/capture/stall/`, the journal's `UNIT_RESULT=watchdog` entry with the same `InvocationID`, and AUT-6's delivered per-kill notifier marker for it (**r10**, leg W);
   - an **NBP poll-reset heal** (`decided_by:"nbm_quantile_actor"`).
3. A `delivered=true` record whose `event` is `CAPTURE_HEALED_<observation_sha256>` for that heal, dated between the heal's date and the heal's date + `HEAL_ALERT_RETRY_DAYS`.
4. `evidence/capture/live_proof/live_proof_<family_id>_<asof>.json` with `status=PROVEN`.

**Qualifying days** (r8 §6, unchanged):
- A day with ≥ 1 real fill qualifies if its live audit is `PASS`.
- A canary-only day qualifies but adds 0 real fills.
- FAIL, ERROR or a stale INCONCLUSIVE breaks the run.
- PRE_CAPTURE and PARTIAL_EPOCH days never count.
- The window needs 7 qualifying days and ≥ 5 real fills.

A day with `lost_in_flush_window > 0` still qualifies if every fill's legs pass, because the loss is counted and visible (§1.1).

**Accrual ETA:**
- **Join leg:** as r8. If AUT-1a merges by about 10-10 and AUT-5a by about 10-13, WP8 activates at the 10-14 LAUNCH. The earliest window closes about 10-23; the planning ETA is 10-30.
- **Stall leg:** **no longer depends on AUT-5b.** It is met by the first Sunday drill after WP3 step 2 (ER-8 and E-11 adoption, AUT-6's notifier, plus one 09:00Z rotate), or by any natural watchdog or NBP heal that comes first.
- **PROVEN** = max(join window, first confirmed heal with a delivered alert). With ER-8 adopted by about 10-10, that is about **10-30**, well before the 2027-01-25 KILL.

**Evidence class:** "machinery proven, edge unproven". This is a census, not a statistical test.

---

## 7. Score-3 verification checklist (independent scorer)

| Criterion | Exact check |
|---|---|
| (a) Unattended | 1. `systemctl --user list-timers 'breezy-capture-*'` lists settlement, audit, live-proof (fallback), drill and guard. 2. `systemctl --user show breezy-quote-tape.service -p Type -p WatchdogUSec -p NotifyAccess -p Restart -p OnFailure -p ExecStopPost` shows `notify`, `10min`, `all`, `always`, `breezy-autonomy-failed@breezy-quote-tape.service` and the hook (**r10**); `systemctl --user show breezy-quote-tape-rotate.service -p TimeoutStartUSec` shows `1h 18min` (`QUOTE_TAPE_ROTATE_TIMEOUT_START_SECS` = 4680 at base 180; **r11, GH1**). 3. `git -C /home/jon/breezy log --since=<start> --until=<end> -- src/breezy/persistence/autonomy/capture_* src/breezy/strategy/autonomy_capture/ src/breezy/runtime/capture_* src/breezy/analysis/capture_* src/breezy/adapters/polymarket_us/recorder_watchdog.py deploy/systemd/breezy-capture-* deploy/systemd/breezy-quote-tape.service` is empty. 4. `scripts/ci/run_tests_no_egress.sh tests/unit/test_capture_units.py` passes. |
| (b) Family-agnostic | `scripts/ci/run_tests_no_egress.sh tests/unit/autonomy/test_capture_guard_family_agnostic.py tests/unit/autonomy/test_capture_submit_sites.py tests/unit/test_capture_audit.py::test_unknown_family_fill_is_enumerated_by_construction tests/unit/autonomy/test_capture_actor.py::test_unstreamed_set_is_computed_from_list_schemas` passes, and ARCH-0's `test_family_plugin_exact_set` passes. |
| (c) Fails closed | These pass: `test_untagged_buy_refused_capture_untagged`, `test_refused_order_never_reaches_cache`, `test_publisher_health_not_ok_refuses_buy_capture_gap`, `test_type_bytes_flat_sets_capture_gap`, `test_flush_failure_refuses_buy_capture_gap`, `test_watchdog_journal_entry_without_stall_record_fails_leg_w`, `test_capture_guarded_strategy_without_publisher_refuses_construction`, `test_unparseable_recorder_watchdog_file_vetoes`, `test_recorder_watchdog_unarmed_is_error`, `test_heartbeat_gap_over_180s_fails_stream_gap`, `test_records_short_of_last_heartbeat_count_fail_stream_record_lost`, **(r11)** `test_take_path_write_drop_refuses_buy_capture_gap`, `test_discovery_attempt_inflight_over_budget_stops_extending`, `test_aut6_unit_health_tolerates_activating_within_start_budget`; **(r12)** `test_first_write_to_lazily_created_table_with_zero_size_is_a_drop`, `test_extension_deadline_never_exceeds_max_start_budget`, `test_recorder_boots_counts_venue_outage_restarts_and_vetoes`. |
| (d) Detected and alerted with delivery | **Gate:** every event in `CAPTURE_ALERT_EVENTS` (§3.16) has a test asserting the outbox or `deliver_with_proof` call, and passes verbatim through the real AUT-6 API (`test_capture_alert_contract.py`). **Live (r10, X-4):** for the drill's `InvocationID`, AUT-6's marker `evidence/alerts/notify/<date>/breezy-quote-tape.service__<InvocationID>.delivered.json` exists, and `evidence/alerts/<date>/*_d.json` holds a `"delivered": true` record whose `event` is `CAPTURE_HEALED_<sha>` for the counted heal. |
| (e) RED→GREEN | Per WP: the RED output naming §4's tests, the GREEN output and the merge SHA. `scripts/ci/run_tests_no_egress.sh; echo EXIT=$?` gives `EXIT=0`, and `lint-imports` prints "N kept, 0 broken". |
| (f) Live proof | 1. `jq .status /home/jon/.local/share/breezy/evidence/capture/live_proof/live_proof_pm_us_crh_fq_v1_<asof>.json` is `"PROVEN"`. 2. For each listed date, the newest audit file has `day_status=="PASS"`, `legs.R1/R2/R5/R7/W/O/F/I.pass` true and `fills_total == fills_joined`. 3. The verdict is `capture_join_completeness, outcome=PASS`. 4. `ls evidence/capture/heal/*/` shows ≥ 1 file that is not in `heal_alert_undelivered`. |
| Spot check, independent of AUT-1's code | For 3 random fills in the window: 1. `sqlite3 'file:/home/jon/.local/share/breezy/state/exec_polymarket_us.sqlite?mode=ro' "select value from state where key='exec/polymarket_us/fill/<voi>'"` gives a `clientOrderId`. 2. Reading `<capture_root>/live/*/order_initialized_*.feather` with `pyarrow.ipc` finds that `client_order_id` with a `breezy:decision_id=<id>` tag. 3. `custom_decision_record_*.feather` has a `Take` with that id, whose `eval_ns` appears as `'now_ns': <eval_ns>` in a `SHADOW_DECISION … 'kind': 'Take'` node-log line. 4. Its `FrameCopy` top equals the recorder catalog's Depth10 or quote at `(instrument, frame_ts_event)`. 5. `intent_fingerprint` over the `OrderInitialized` fields matches a `fill_by_fingerprint/` key. |

---

## 8. Risks and failure modes

| Risk | Mitigation |
|---|---|
| **Option A crashes the trade node at boot** through the `config.json` dump (`kernel.py:606-611`, `config.py:176`) | **Removed (r10, R-A):** option A is dropped; there is no `StreamingConfig` and no dump (`test_no_config_json_is_written`). |
| **A writer serialisation error unwinds into the exec engine** (`component.pyx:2832-2834`, `writer.py:259`) | **(r10, R-A)** The only bus handler is the catch-all wrapper; custom records never cross the bus. V-3 still proves every included type serialises, because a type that never does would latch `capture_gap`. |
| The writer silently drops a custom type through per-instrument routing (`writer.py:230-239`) | No field is named `instrument_id`, pinned by `test_no_capture_record_field_is_named_instrument_id` and V-5. |
| The writer drops records silently (`writer.py:284-288`, `:261`, `:250-253`) | **(r10, EH4)** The per-type landing check sets `capture_gap` for the affected table (V-17); R4 fails the day on the log marker; R5 counts per type against the heartbeat; R7 catches a dead stream. |
| Records lost at a crash (no fsync) | Accepted by ruling. Take-path records are flushed before submit (EM4). Other loss is bounded at about 61 s by the tick flush, enforced by the audit (EL1), and counted by R5 against `SHADOW_DECISION`. A lost Take-path record still fails its fill, so the window breaks honestly. |
| A Take's frame is absent from the tape | The Take-path `FrameCopy` (§3.3.2). Refusal references are counted (R6). |
| A depth-only instrument looks stale to `Cache.quote_tick` (V-7) | **(r10, EM7)** `md_feed_freshness` never vetoes; `quote_absent` and `quotes_stale` are observations. |
| **systemd restarts the recorder without a start limit** | **(r10)** AUT-6's O-8 (the 2026-09-09 incident) keeps `StartLimitIntervalSec=0`; the bound is the existing backoff. Every kill is paged by AUT-6's notifier (X-4), the 3rd in a trading day pages the storm (X-6), the gate defers stall kills out of the launch window (X-3), and the hook's count sets `recorder_stale` (§3.7.4). |
| False watchdog kills or start timeouts (quiet listings, the 09:00–10:30Z hole) | **(r10)** The watchdog is not armed before READY (§1.3). The pinger runs from the top of `_connect` and extends the start through legitimate discovery (EH1), READY is not gated on counters (X-5, V-18), and empty listings ping while reloads are fresh. Activation step 1 runs a full day with the unit unchanged. |
| **`Type=notify` without a READY sender loops on start timeouts** (AUT-6 R-40) | Step 1 ships the sender first; step 2's unit edit follows only after step 1's day of evidence; AUT-6's `test_watchdog_member_execstart_reaches_a_notify_sender` refuses `Type=notify` otherwise. |
| **The 09:00Z rotate times out while the recorder waits for READY** (DH1) | **(r11, GH1)** Rotate `TimeoutStartSec` = `QUOTE_TAPE_ROTATE_TIMEOUT_START_SECS` (4680), derived from one constant that includes the base start and the last extension's tail. The unit literal is pinned equal to it by AUT-1's bound test, and AUT-6's rule is met (§3.10.2). |
| **A hung connect-time discovery request keeps the start extended for an hour** (GM1) | **(r11)** `discovery_attempt_hung` after `DISCOVERY_ATTEMPT_BUDGET_S = 180` stops the extension, so the start times out, AUT-6 pages it, and systemd restarts the recorder. Worst detection is about 305 s (§3.10.1). |
| **The per-write drop check refuses Takes on a false positive** (GM2) | **(r11)** V-19 proves zero drops on the four non-drop paths. A drop latches `capture_gap` and pages `CAPTURE_PUBLISH_FAILED`, so a false positive would be loud and never silent. Exits are never refused. |
| **A failed or killed stop hook hides a kill from `recorder_stale`** (GM3) | **(r11)** The blind window is stated (§3.10.2). The kill is still paged at once by AUT-6. The node also counts unexplained boots from the recorder's native `config.json` boot marker (§3.7.4). Leg W FAILs the day. |
| A frozen recorder loses its unflushed tape at the kill | `WatchdogSignal=SIGTERM` lets Nautilus close cleanly once SIGCONT arrives (V-10). A truly hung loop is SIGKILLed after `TimeoutStopSec` and loses at most its unflushed tail. **(r10, EL1)** The truncated file's recoverable prefix is landed by the existing ingest salvage, `salvage_truncated_instance` (`src/breezy/runtime/quote_tape_salvage.py:508`). |
| `sd_notify` is blocked under bwrap (a read-only bind on the socket inode) | The recorder is unwrapped (E-7a rule 5). V-9 tests the wrapped form, for any future wrapped notifier and for the audit's and drill's user-bus clients. |
| The stop hook hangs, fails, or delays the restart | **(r10, EM1)** `timeout -k 2 10` and the `-` prefix: it delays a restart by at most 12 s and can never change the unit's result. Any failure is logged `RECORDER_HOOK_FAILED` and caught by leg W the next day. |
| Downstream READY plans read removed paths | §5.3 lists every citation, `project_c1` preserves the C1 logical names, and the coordinator schedules the brief amendments. |
| Two restart deciders for the recorder | **(r10)** None: AUT-6 r14 has no restart executor, and AUT-1 restarts nothing. The user manager is the only restarter. |
| Two pagers for one kill | **(r10, X-4)** The hook sends nothing (`test_no_recorder_stop_hook_pages_watchdog_kill`); the audit's leg W alert is a separate evidence-gap event and never re-pages the kill. |
| Memory on the 30 GiB host (G29, L-29, L-49, L-53) | The node holds only O(subscribed instruments) for `EvalSeqCounter`. V-4 measures the writer. Unit caps follow §3.13, and heavy jobs run one at a time outside 01:00–04:30Z. |
| The shared venv (L-51) | No new dependency (`sd_notify` is stdlib), no console script, the exact interpreter. |
| Concurrent agents (L-43, L-50) | Disjoint ownership, one writer per file, a full gate per merge, and per-agent scratchpads. |
| Statistical capacity | This is a census; each window needs ≥ 5 real fills. |
| The KILL date, 2027-01-25 | The stall leg no longer waits on AUT-5b. If TERMINAL fires first there is no sender, and AUT-1 stays at "machinery proven, window paused". |
| A wrapped AUT-1 unit imports a venue adapter (E-7 rule 2) | `breezy.domain.exec_intent` plus the closure test (V-15, WP5); WP6 waits on E-7b(a). |
| The ARCH errata are not adopted | G-ERR blocks WP1, WP5 and WP8, and ER-8 plus E-11 block WP3 step 2. r10 never ships against the unamended C1 text. |

---

## 9. Binding-constraint compliance

- **Nautilus immutability:** only native extension points are used:
  - `@customdataclass`, and `register_arrow` as already used by `ForecastPoint`;
  - a `StreamingFeatherWriter` instance owned by the capture actor (R-A; no `StreamingConfig`, no `register_config_encoding`);
  - `Order.tags`;
  - a `Strategy` subclass that calls `super()`;
  - `Actor` msgbus subscriptions and timers;
  - `Cache` reads.

  Nothing under `nautilus_trader` is touched.
- **Operator caps:** never read, assigned, defaulted or logged. `test_autonomy_never_reads_or_writes_operator_controls` is extended to AUT-1's paths (L-39).
- **`allow_short`:** untouched; every entry stays a BUY.
- **NO-SEND firewall:**
  - the exec client is unedited and byte-pinned;
  - no new egress: alerts use `alerts.env` only;
  - no AUT-1 unit holds a venue credential (the E-7 `--tmpfs ~/.config`);
  - the trade-config dump carries env-var names only (the V-2 scan).
- **Master enablement and permit:** AUT-1 only adds refusals and never touches permit authority. `test_autonomy_never_touches_enablement_permit_or_firewall` is widened to AUT-1's packages.
- **PREREG via ruling:** no statistical semantics change; AUT-1 produces census verdicts only.
- **Coordinator decisions** (as r8 §9):
  - HOLDOUT: AUT-1 never reads the holdout or the forward window;
  - ALPHA: HEALTH censuses charge no α;
  - ROLLBACK-FAILURE: no `cause_code`, no HALT write.
- **ARCH errata:**
  - E-1: AUT-6 implements the claim order; AUT-1 only offers.
  - E-2, E-4, E-5, E-6 and E-10: do not touch AUT-1.
  - E-3: governs tag reading.
  - E-7: no directive counts as a control; the node is never wrapped; the one-writer property rests on the wrapper, the lint and the stated residual.
  - E-7a: every AUT-1 unit and the stop hook are wrapped (§3.13); exec-store WAL reads use the snapshot helper; the AST check is a lint.
  - E-7b: no AUT-1 unit is a replay child. WP6's parity rerun depends on E-7b(a) and does not borrow E-7b(b) (§3.14). The audit's adapter imports are removed through `breezy.domain.exec_intent` (§2.2).
  - E-7c: the wrapper's private `/tmp`; a binding build item (§3.13).
  - E-8 and E-8a: the audit uses the helper with `take_flock=False`, and its result is advisory and never counts toward H.
  - E-9: no AUT-1 oneshot has more than one start command; the stop hook is bounded by `timeout -k`.
- **Launch window:** no AUT-1 timer fires in [16:30Z, 17:10Z). The gate defers post-READY stall kills out of it (X-3); **(r12, item 2)** a pre-READY start is never deferred, so a hung start may time out and restart inside the window, which loses no capture (§3.10.2). The evidence-only hook is event-driven and sends nothing.
- **(r12) Hard invariants restated, unchanged by r12:** Nautilus Trader is **unmodified**; r12 adds only reads of the writer's public `get_current_file_info()` (now also the absent-before case) and of `config.json` mtimes. `allow_short` stays **False**. No safety, settlement or contract test is weakened, deleted or `xfail`ed; the two renamed/replaced tests (`…counts_boots…`, `…pre_ready_withhold_is_never_deferred`) were planned and never built, and the new dependency test stays RED until AUT-6 lands. The operator caps (max daily budget, max per position) are **never assigned**. Live-trading enablement and the NO-SEND execution-egress firewall are **untouched**. **AUT-1 restarts nothing**: removing the pre-READY deferral adds no restart path; systemd's own `Restart=always` acts on a start timeout, as it already does outside the window. No `uv`/`pip`; no unit touched by planning; WP0 uses scratch `claude-aut1wp0-*` units only.
- **(r11) Hard invariants restated, unchanged by r11:** Nautilus Trader is **unmodified**. r11 adds only reads of the writer's public `get_current_file_info()` and of the recorder kernel's own `config.json`. `allow_short` stays **False**. No safety, settlement or contract test is weakened, deleted or `xfail`ed; the new dependency test stays RED until AUT-6 lands. The operator caps (max daily budget, max per position) are **never assigned**. Live-trading enablement and the NO-SEND execution-egress firewall are **untouched**. **AUT-1 restarts nothing**: the rotate bound and its `OnSuccess=` timing change no restart path, and the node's boot-marker read runs no `systemctl`. No `uv`/`pip`. No `breezy-*` unit is touched by planning or by WP0 (scratch `claude-aut1wp0-*` units only); the two unit files change only in WP3 step 2's reviewed commit.
- **(r10) Hard invariants restated:** Nautilus Trader is unmodified; `allow_short` stays False; no safety, settlement or contract test is weakened, deleted or `xfail`ed; the operator caps (max daily budget, max per position) are never assigned; live-trading enablement and the NO-SEND execution-egress firewall are untouched; **AUT-1 restarts nothing** (activation rides the existing 09:00Z rotate and the supervisor's LAUNCH); no `uv`/`pip`; no `breezy-*` unit is touched by WP0 (scratch `claude-aut1wp0-*` units only).
- **Safety tests never weakened:**
  - every §4 "unedited" test stays green;
  - widenings follow L-12;
  - nothing is deleted, relaxed or `xfail`ed;
  - r8 tests whose subject r9 removes are simply never built (r8 was never implemented), and §4 names their r9 counterparts.

---

## 10. Self-score

**r12 claims 97.** (r11 claimed 96; the r11 review scored 95 and 93.) r12 changes: Fidelity 19 → 20 (all seven r11 items closed where asked; the R-16 relay is discharged by AUT-6 r15-final item 7), Correctness stays 19 (−1: V-19, V-20, V-21 and V-23 are still to run), Autonomy-safety stays 15 (the start budget is now absolute; the venue-outage veto is tested). Total 20 + 19 + 15 + 19 + 15 + 9 = **97**. The r11 table below is kept as the r11 record.

**r11 claims 96.** (r10 claimed 94; the r10 review scored 93 and 88.)

| Axis | Max | Score | Note |
|---|---|---|---|
| Fidelity | 20 | 19 | Every r10-review item (GH1, GM1–GM5, GL1, ER-7, ER-9) is closed where the review asked (§R11). r9 and r10 closures are re-checked with no regression. −1: R-16 corrects the review's own rule (4362 → 4662, rotate 4680). That is a stated, arithmetic-backed divergence from the number the review called correct, and it is relayed for AUT-6 item 7's prose. |
| Correctness | 20 | 19 | The writer's size bookkeeping, rotation reset and `creation_time` (`writer.py:264-277`, `:385-406`, `:613-637`), the discovery attempt shape (`data.py:1082-1099`, `provider.py:101-113`), the register unit and the native boot marker were read at `f45f5a65` and on the host. −1: V-19 (no false-positive drops) and V-20 (attempt budget) are load-bearing premises still to run. |
| Specificity | 15 | 15 | Every bound is one named constant with its module, every new test is named, and the rotate number appears only as derived. |
| Acceptance | 20 | 19 | The §7 checks are updated (`1h 18min`, the new fail-closed tests). −1: AUT-2/3/4 still need brief amendments (§5.3). |
| Autonomy-safety | 15 | 15 | GM2 is fail-closed on Takes and never refuses exits. GM1 shortens a hung start from about 65 min to about 5 min. GM3 closes the intraday blind window from native evidence, with no `systemctl` from the node. AUT-1 restarts nothing. |
| Reuse | 10 | 9 | GM2 uses the writer's public `get_current_file_info()`; GM3 uses Nautilus's own `config.json`; GM5 changes nothing. Still custom: the wrapper, publisher, guard, epoch, gate, pinger, hook, audit and `FrameCopy`. |
| **Total** | 100 | **96** | |

---

## 11. Contradictions and residual readings against frozen ARCH Rev 9.2

**Open contradictions:** the ten items in §ERRATA-REQUEST. r9 does not reinterpret ARCH; the affected WPs wait (G-ERR).

**Residual readings carried from r8, unchanged:**
- R-1: the CRH `_maybe_submit` tag site is unreachable today.
- R-2: one common `source` field, plus `reconciliation_source=node_belief`.
- R-3: `DetectorEvent` has exactly its C1 fields.
- R-4: an untagged BUY with no known Take produces a `DetectorEvent`.
- R-5: `classification="HUNG"` with a sub-state cause. Now moot: AUT-1 sends no restart request.
- R-7: the quote frame's content is `ask`, `bid`, `ts_event`.
- R-8: the E-1 claim order.
- R-9: no restart request for an active but stale ingest.
- R-10: `eval_seq` is counted per frame, across both handler calls.
- R-11: the heal sha rides in `event`.

**New readings in r10:**
- **R-13 (`EXTEND_TIMEOUT_USEC`).** X-5 fixes when `READY=1` is sent. On this client, the 09:00Z listing hole delays "connected and subscribed" by up to `empty_discovery_retry_secs` (`data.py:1082-1099`, `node_config.py:349`). r10 keeps `TimeoutStartSec` at AUT-6's size and carries the hole with sd_notify's `EXTEND_TIMEOUT_USEC`, sent only while the gate classifies the start `OK`. Without it, every rotate in the hole would end in AUT-6's `member_start_timeout` page. If V-8 (a) fails, the fallback is a base `TimeoutStartSec` ≥ `QUOTE_TAPE_MAX_START_SECS` (§4 WP0; **r11**: was "≥ 4200"). Stated to AUT-6 for its DH1 text; no AUT-6 rule changes.
- ~~**R-14 (deferral before READY).**~~ **Retired in r12 (item 2).** r10 applied X-3's window to the start extension. That let a start extend past `QUOTE_TAPE_MAX_START_SECS`; r12 removes it, so the start budget is absolute and a pre-READY start timeout restarts normally, possibly inside the window (§3.10.2, "Deferral and the start budget").
- **R-15 (EM1 under X-4).** EM1 says the audit "FAILs and re-sends". Under X-4 only AUT-6 pages a kill, so the audit re-sends its own `CAPTURE_WATCHDOG_EVIDENCE_GAP`, never the per-kill page (#21's fallback is AUT-6's re-page).

**New readings in r11:**
- **R-16 (the rotate bound, GH1).** The review set the rule 120 + 12 + 4200 + 30 = 4362 and called 4500 correct. r11 derives every term from constants (§3.10.2) and finds two omitted terms. (a) The last `EXTEND_TIMEOUT_USEC` still grants `START_EXTEND_S` = 120 s after the last `OK` tick. (b) Process start to `_connect` is bounded only by the base `TimeoutStartSec` (180), because nothing can extend before the pinger exists. So the max start is 180 + 3900 + 300 + 120 = **4500**, and the rotate bound is 120 + 12 + 4500 + 30 = 4662, set to **4680** (`1h 18min`, latest end 10:18Z). The 4500 the review approved is the max **start**, not the rotate bound. Relayed to the coordinator for AUT-6 r15-final item 7's prose ("4200 … inside 4500"): AUT-6's test reads `QUOTE_TAPE_MAX_START_SECS`, so no AUT-6 rule changes.
- **R-17 (GM3 boot count).** "Recorder invocation changes it can observe locally" is read as Nautilus's own per-boot `config.json` in the recorder's stream directory. It is evidence the unmodified recorder kernel already writes, so AUT-1 adds no writer to the recorder process. One boot per trading day is excused for the 09:00Z rotate. Manual restarts count, which is restrictive only.
- **R-18 (GM2 fail-closed and live proof).** A per-write drop refuses the Take (`capture_gap`) and never refuses an exit. A refused Take produces no fill, so it can delay the live-proof window but can never fake a pass or hide a join gap. A non-zero `write_drops` also FAILs the day in R5 as `stream_write_dropped`.

**Retired:**
- R-6: subsumed by `frame_kind`, which always holds exactly one value.
- R-12: there are no asynchronous payloads, so there is no `payload_pending`.

---

## §ERRATA-REQUEST (exact replacement text for the frozen ARCH Rev 9.2; filed for the coordinator, not self-adopted)

**(r12)** No erratum text changes in r12. ER-9's verbatim match to the architect's text is re-checked (item 7). Items 1–6 change only AUT-1-internal design and fall inside the adopted/filed ER-7, ER-8 and E-11 wording (ER-7's "per-write size delta" already covers the first-write rule; ER-8's "defers a stall restart" is the post-READY deferral, unchanged).

**(r11)** Amended per the r10 errata verdicts (`reviews/AUT-1-r10-merged.md`): ER-7 AMENDED (adds "and per-write size delta"); ER-9 AMENDED (the stale final clause replaced with the review's text, and the coordinator note removed); ER-1–ER-6 and ER-10 stand as adopted or AMEND-applied; ER-8 stands as REDUCED (adopt), with one consequential clause for GM1. E-11 is ADOPTED, so the ER-8 text is appended to adopted E-11 text.

**(r10)** Amended per the r9 errata verdicts (`reviews/AUT-1-r9-merged.md`): ER-1, ER-2, ER-3, ER-4, ER-6, ER-7 and ER-10 AMENDED; ER-8 REDUCED; ER-5 and ER-9 ADOPTED unchanged. Each amended item gives its full r10 text.

Each item quotes the frozen text from `reviews/snapshots/ARCH_rev9_2.md` and gives its replacement. The rationale is the cited Nautilus evidence and the coordinator ruling in `reviews/AUT-1-native-pressure-test.md`.

### ER-1. C1, "Rejected" bullet (`ARCH_rev9_2.md:166`)

**Frozen:**
> **Rejected:** `StreamingConfig` on the trade node (memory and flush risk); reopened only by L-1 proof.

**Replace with:**
> **Adopted (L-1 proof: `reviews/AUT-1-native-pressure-test.md`; AUT-1 r10 §2; ruling R-A):** C1 records are `@customdataclass` types persisted by Nautilus's own `StreamingFeatherWriter`, as **one writer instance owned by the node's capture actor** behind a catch-all wrapper that never raises into a caller or a message-bus handler. The capture publisher writes C1 records through that wrapper directly; they do not cross the message bus. `StreamingConfig` on the trade node stays rejected (its `"*"` subscription and boot-time config dump). The stream directory is `derived/capture_stream/<venue>/live/<instance_id>/`, where `<instance_id>` is the trade node's explicit kernel `instance_id`; it is never under the quote-tape root. `include_types` is restricted to the C1 types, `ForecastPoint`, `OrderInitialized`, `OrderFilled` and every `PositionEvent`. The writer flushes about every 1 s and on a 60 s heartbeat tick, with no fsync; Take-path records are flushed synchronously before their order is submitted. A per-type check (each type's written count against its own file growth) sets `capture_gap` when a type's records stop landing. Residual loss is bounded at about 61 s and counted by the daily audit, per type, against the heartbeat counts and the node log's `SHADOW_DECISION` lines.

### ER-2. C1, "Storage" paragraph (`ARCH_rev9_2.md:147-149`)

**Frozen:**
> A daily file `decisions/capture_<family_id>_<YYYY-MM-DD>.jsonl`, following the `OfferTape` and `FqDecisionFunnelActor` convention (`crh/composition.py:568-602`; `app/trade.py:763-775`); the existing retention unit compresses it. Its only writer is the node, serialised by the submit-intent flock (G6).

**Replace with:**
> Native Arrow stream files under `derived/capture_stream/<venue>/live/<instance_id>/`, one table per record type, rotated daily at 00:00 UTC (`SCHEDULED_DATES`, the recorder's constants). Each directory has exactly one writer, the capture actor's `StreamingFeatherWriter` for the boot named by `<instance_id>`, which is fresh per boot; no flock is needed or taken. **Retention:** none is required at the measured volume (about 2–3 MB a day); stream files are never deleted, and a retention owner is named in a reviewed change before the volume exceeds 20,000 rows a day. C2–C6 consumers read C1 through AUT-1's reader projection, which keeps the C1 record names and fields below.

### ER-3. C1, "Payload store (P1-4)" bullet (`ARCH_rev9_2.md:152-156`)

**Frozen:**
> `depth_ref`, `quote_ref` and `forecast_input_sha256` name write-once, content-addressed payloads at `derived/capture_payloads/{depth10,quote,forecast_input}/<sha256>.json` (quote: `ask`, `bid`, `ts_event`; U8) (0444, schema `payload/v1`, `mkstemp` + `os.link`, so an existing name is never replaced). The node writes a payload only with the C1 record citing it (write-on-change, L-29); a missing payload marks the record `capture_gap`. AUT-1 measures the volume; retention archives payloads with the daily file and never drops one a C3 lineage cites.

**Replace with:**
> **Frame and forecast references (P1-4, amended).** A `DecisionRecord` references its triggering frame as `(frame_kind ∈ {depth10, quote}, instrument_id, ts_event)`, resolved against the recorder catalog's `order_book_depths` or `quote_tick` rows, and its forecast as `(station, cycle_ns, available_at_ns)`, resolved inside the same boot's C1 stream, which carries every `ForecastPoint` the node consumed, by replaying them through the strategy's own vector rule. For `Take`, `TrySubmit`, `EntryVeto` and `Exit` records the node also streams a `FrameCopy` of the frame (quote: `ask`, `bid`, `ts_event`; U8), because the node cannot observe the tape at decision time and a Take-path frame cannot be recovered later. A Take-path record whose frame reference resolves to neither its copy nor the tape, or whose forecast reference does not resolve in its stream, is `capture_gap`. A refusal reference that does not resolve is counted by the daily audit and alerted below the measured baseline. Retention never drops a stream file or a tape partition that a C3 lineage cites.

### ER-4. C1, `DecisionRecord` row (`ARCH_rev9_2.md:135`)

**Frozen** (the fields after `side`):
> `instrument_id`; `ask_px`; `depth_ref` (sha256 of the Depth10 payload, L-35) or `quote_ref` (sha256 of the quote payload; U8); `p_hat`, `p_hat_raw` (pre-recalibration, P3-3), `p_lower`, `p_upper` (the kind's YES-leg values, as FQ computes them, `fq/decision.py:331,349`), `ev_net`; `forecast_input_sha256`; `artefact_sha256`; `manifest_sha256`

**Replace with:**
> `instrument_id` (stored as `instrument`, because a stored `instrument_id` field makes the native writer route by instrument and drop rows for uncached instruments); `ask_px`; `depth_ref` or `quote_ref` (the reference string `<kind>:<instrument_id>@<ts_event>`; U8); `p_hat`, `p_hat_raw` (pre-recalibration, P3-3), `p_lower`, `p_upper` (the kind's YES-leg values, as FQ computes them), `ev_net` and `margin`, recorded on refusals wherever the kind computed them before refusing; `forecast_input_ref` (`nbp:<station>@<cycle_ns>@<available_at_ns>`, stored as `forecast_station`, `forecast_cycle_ns` and `forecast_available_at_ns`, the vintage of the vector the decision used); `artefact_sha256`; `manifest_sha256`. The common `ts_ns` is the record's native `ts_init`. Nullable values are the empty string (str) or 0 (int), because `@customdataclass` admits no `Optional` field.

### ER-5. C1, `OrderLink`, `LifecycleEvent` and `PositionMark` rows (`ARCH_rev9_2.md:136-138`) — ADOPTED, text unchanged

**Frozen Writer column:** "node `on_order_*`" / "node" / "node or position monitor".

**Replace the Writer column with:**
- **`OrderLink`:** projected by AUT-1's reader from the natively streamed `OrderInitialized`. Its `tags` carry the `decision_id`, and its fields are the G33 fingerprint inputs. `venue_order_id_sha256` comes from `OrderAccepted`/`OrderFilled`.
- **`LifecycleEvent`:** projected from the natively streamed `OrderFilled`, and from AUT-1's `OrderEventRecord`, which the capture actor publishes for exactly the order-event classes that have no registered Arrow schema.
- **`PositionMark`:** projected from the natively streamed `PositionEvent`s with the venue leg sign applied, or written by the position monitor.

### ER-6. §3 common rules: atomic writes and payload hygiene (`ARCH_rev9_2.md:93-95`, `:109-111`)

**Add** after "Writes are atomic (`mkstemp` + `os.replace`; `runtime/health.py:322,330`), append-only, named by content hash or `now_ns`.":
> Exception: C1 stream files are written by Nautilus's `StreamingFeatherWriter` (append-only Arrow IPC, flushed, not fsynced); readers treat a truncated final batch as a torn tail and the audit counts it.

**Add** after "venue order ids appear only as `sha256`.":
> Exception: natively streamed Nautilus event tables (`OrderFilled`) in the 0700 C1 stream root carry Nautilus's own fields, including the raw `venue_order_id`. They are never alerts or verdicts and are never copied into one; AUT-1's custom records carry only `venue_order_id_sha256`.

### ER-7. C1, "No silent cap" and "Failure behaviour" (`ARCH_rev9_2.md:162-163`, `:174-175`) — **AMENDED in r11** (per-write size delta)

**Frozen:**
> A write failure or byte cap increments a counter, raises a CRITICAL alert and marks the day `CAPTURE_INCOMPLETE`.

> A write error raises a CRITICAL alert and makes the day inadmissible for AUT-4.

**Replace with:**
> A publish or flush exception increments a counter, sets the node-local `capture_gap` veto and raises a CRITICAL alert through the node outbox. A write error inside the native writer, which logs and does not raise, is detected in the node **by per-type stream bytes and per-write size delta**. Per write: the writer's own per-table size and file creation time are read before and after each write, and an unchanged pair is a dropped record. The drop is counted, sets `capture_gap`, and refuses the Take whose record dropped; an exit is never refused. Per type, over a window: any record type whose written count rose while its own stream files did not grow sets `capture_gap`. The next day the audit detects it again (the writer's failure log line, the per-type heartbeat-count reconciliation, the counted per-write drops and the heartbeat continuity check), raises a CRITICAL and marks the day `CAPTURE_INCOMPLETE`, inadmissible for AUT-4. There is no byte cap.

### ER-8. Recorder unit (AUT-1-only text; **REDUCED in r10**)

**Scope (r10, errata dedupe).** AUT-6's E-11 is the single vehicle for the ARCH §4.5/§4.6 SELF_HEAL wording, the per-kill page, the storm and the deferral WARN. r9's §4.6/§4.5/§5.2 replacement text is withdrawn. ER-8 now adds only this AUT-1-specific text, appended to E-11's SELF_HEAL member rules:

> **The quote-tape recorder (AUT-1).** `breezy-quote-tape.service` is the SELF_HEAL member whose liveness source is AUT-1's watchdog gate. The ping source runs from process start, through discovery: it starts as the first step of the data client's connect, sends `EXTEND_TIMEOUT_USEC` while a legitimate discovery is within its budget and no single discovery attempt has overrun its request budget, sends `READY=1` once the feed is connected and subscribed (never gated on counters), and sends `WATCHDOG=1` only while its counters and on-disk bytes advance. The gate defers a stall restart that would meet [16:30Z, 17:10Z) and journals `RECORDER_WATCHDOG_DEFERRED` once per stall. The unit's `ExecStopPost=` hook is evidence only: it writes the stall record and `recorder_watchdog/v1`, which feeds the node-local `recorder_stale` veto, and pages nothing. The daily capture audit cross-checks every journal `UNIT_RESULT=watchdog` entry of the recorder against a stall record and a delivered per-kill page for the same `InvocationID`, and fails the day otherwise. AUT-1 issues no restart.

### ER-9. §5 area table, AUT-1 "Owns" (`ARCH_rev9_2.md:1032`) — **AMENDED in r11** (stale final clause replaced)

**(r12, item 7)** The replacement below carries the architect's ER-9 AMEND text from `reviews/AUT-1-r10-merged.md:41` **verbatim**: the clause `recorder and feed stall observations (the recorder's process-level heal is systemd's own watchdog, per §4.6 as amended by E-11; AUT-6 pages and does not restart)` is byte-identical to the review's quoted text (string match re-run 2026-10-03 against the review line: it occurs verbatim in the replacement block below, and in this note). The review's leading `…` stands for the unchanged list items before that clause, which the block reproduces. No other ER-9 wording changed.

**(r11)** r10 flagged the final clause "AUT-6 restarts failed units" as stale: AUT-6 r14 deleted AUT-6's restart executor, and E-11 is now adopted. The r10 review's AMEND verdict replaces that clause with its own text, below. r10's coordinator note is withdrawn.

**Frozen:**
> `CaptureAdapter` per kind, the `decision_id` tag, link and lifecycle writers, `DetectorEvent`, the payload store, the settlement writer, the completeness audit, recorder and feed stall observations (AUT-6 restarts)

**Replace with:**
> `CaptureAdapter` per kind, the `decision_id` tag, the C1 custom data types, stream configuration and reader projection (link, lifecycle and mark records are native events projected by the reader), `DetectorEvent`, the Take-path frame copy, the settlement writer, the completeness audit, recorder and feed stall observations (the recorder's process-level heal is systemd's own watchdog, per §4.6 as amended by E-11; AUT-6 pages and does not restart)

### ER-10. §10 obligations, AUT-1 (`ARCH_rev9_2.md:1201-1203`)

**Frozen** (the parts that change):
> … the payload store and volume (P1-4); … restarts only via AUT-6 (P1-10, P1-12); `quote_ref` payloads and `wall_ns` (U8, U9).

**Replace with:**
> … frame and forecast references (the forecast inputs streamed natively as `ForecastPoint`), the Take-path frame copy and stream volume (P1-4 as amended); … no AUT-1 restart call site (P1-10, P1-12); the recorder's watchdog gate, `READY` sender and evidence-only stop hook under E-11's SELF_HEAL rules; `quote_ref` frame references and `wall_ns` (U8, U9).

### C1 text left unchanged

- the `decision_id` definition;
- the `eval_ns`, `eval_seq` and `wall_ns` semantics;
- the `breezy:decision_id=` tag;
- exit ids (P1-8);
- `SettlementRecord` and its own file (P1-6);
- the on-change rule (L-29);
- invariants (i)–(iii);
- `capture_untagged` (P1-9);
- the offline intent linkage (P1-3), with the `OrderLink` fields now taken from `OrderInitialized`.

**Verdict ledger (r11):** ER-1–ER-6 ADOPT / AMEND-applied (unchanged in r11) · ER-7 **AMEND applied** (per-write size delta) · ER-8 REDUCED, adopt (one consequential GM1 clause: "no single discovery attempt has overrun its request budget") · ER-9 **AMEND applied** (the review's replacement clause; r10's note withdrawn) · ER-10 ADOPT. E-11: ADOPTED (`ARCH-ERRATA-rev9_2.md`).

**Verdict ledger (r10):** ER-1 AMEND (option B named; ~1 s plus tick and Take-path flush; per-type check; `<capture_root>` naming fixed to `derived/capture_stream/<venue>/live/<instance_id>/`) · ER-2 AMEND (retention: none required, never deleted) · ER-3 AMEND (`ForecastPoint` stream) · ER-4 AMEND (`forecast_available_at_ns`) · ER-5 ADOPT · ER-6 AMEND (config.json clause dropped) · ER-7 AMEND (per-type) · ER-8 REDUCE (recorder-unit-only; ping from process start through discovery; journal cross-check) · ER-9 ADOPT (stale clause flagged) · ER-10 ADOPT plus the `ForecastPoint` stream.

---

## §R10 Disposition (`reviews/AUT-1-r9-merged.md`; X-1..X-7 per `reviews/AUT-6-r14-merged.md`; coordinator relay of AUT-6 r15)

**(r11)** This section is r10's record and is left as written. Row R5's numbers ("4500 s … any start ≤ 4338 s") are superseded by §3.10.2's single constant (R-16, §R11 row GH1).

| # | Item | Disposition | Where |
|---|---|---|---|
| 1 | **R-A** option B primary | **Applied.** The actor owns a native `StreamingFeatherWriter` behind the catch-all `CaptureStreamWriter`; `CapturePublisher` writes custom records directly; option A, V-2, V-4 and `register_config_encoding` are dropped. L-1 holds: the writer is native. | §2.1, §3.1, §3.4.2–§3.4.3, §3.6.3, WP0, WP8, ER-1, ER-6 |
| 2 | **R-B** forecast references native | **Applied.** `ForecastPoint` is in `CAPTURE_INCLUDE_TYPES` (registered at `forecast_point.py:675`, no `instrument_id`). `DecisionRecord.forecast_available_at_ns` is added. The key is `(station, cycle_ns, available_at_ns)`, resolved inside the stream. V-12's derived-store premise and `FrameCopy.forecast_body` are removed. `NbmQuantileActor._publish` persists nothing; `nbp_derived_store` dedupes differently (cited). | §1.3, §2.1, §3.3.1, §3.4.1, §3.9, WP0 V-12, WP1, ER-3, ER-4, ER-10 |
| 3 | **R-C** Take-path frame copy | **Adopted unchanged**; the "flagged" wording is replaced by the ruling. | §2.2 |
| 4 | **X-1** `NotifyAccess=all` | **Applied** (step 2 unit line; the audit's fail-loud check). | §3.10.2, §3.11.1, §7 |
| 5 | **X-2** `Type=notify` | **Applied.** The consequence is stated: the watchdog is armed only at READY. | §1.3, §3.10.1–§3.10.2 |
| 6 | **X-3** deferral in `classify_recorder_sample` | **Applied.** `OK_DEFERRED`; one journal line per stall; withholds from 17:10Z. The `UNIT_*` constants are pinned to the unit file. R-14 extends the window to the start extension. | §3.10.1, WP3, §11 |
| 7 | **X-4** per-kill page is AUT-6's `OnFailure=` | **Applied.** `OnFailure=breezy-autonomy-failed@%n.service` is on the recorder unit. **The hook is kept, as evidence only**: the node-local `recorder_stale` veto needs an intraday kill count that the node closure cannot get from the journal or from AUT-6's records, and the hook alone sees `SERVICE_RESULT` with `$INVOCATION_ID`. It sends nothing, has no alert bind, and is `-`-prefixed. | §2.2, §3.10.0, §3.10.2, §3.16, §5 |
| 8 | **X-5** READY not counter-gated | **Applied.** READY is sent after `feed.connect()` and the initial subscribe; WATCHDOG only on OK. Quiet-feed start tests: `test_quiet_feed_start_sends_ready_without_any_counter_advance` (unit) and V-18 (real systemd). | §3.10.1, WP0, WP3 |
| 9 | **X-6** storm owned by AUT-6 | **Applied.** `RECORDER_WATCHDOG_STORM` is removed; `RECORDER_WATCHDOG_STORM_KILLS = 3` equals AUT-6's `WATCHDOG_STORM_KILLS`, pinned by AUT-6's test. | §3.7.4, §3.16 |
| 10 | **X-7** deferral WARN delivered by AUT-6 | **Applied.** AUT-1 journals `RECORDER_WATCHDOG_DEFERRED` (with `stall_started_ns`) and supplies a fixture; AUT-6 delivers the WARN. | §3.10.1, §3.10.0, WP3 |
| 11 | **EH1** ping site absent in discovery | **Closed.** The pinger is created first in `_connect`; DISCOVERING is OK to `empty_discovery_retry_secs + 300`. Under X-2 the hazard is the start timeout, carried by `EXTEND_TIMEOUT_USEC` (V-8 (a), with a fallback). The unit edit and `test_recorder_unit_watchdog_config_exact` land in step 2 only. | §3.10.1, §3.13, WP3 |
| 12 | **EH2** forecast premise false | **Closed** by R-B. | row 2 |
| 13 | **EH3** native serialisation unwind | **Closed** by R-A. The only bus handler is the catch-all wrapper; V-3 is kept as a serialisability premise. | §3.4.2, §8 |
| 14 | **EH4** bytes-flat blind per type | **Closed.** `written_by_type` against per-table `lstat` over 180 s; `type_bytes_flat:<table>` gives `capture_gap`; V-17 mutates the three silent drops. ER-7 reads "per-type stream bytes". | §3.4.4, §3.7.3, WP0, WP8, ER-7 |
| 15 | **EM1** stop-hook failure paths and audit proof | **Closed.** The hook's failure paths log `RECORDER_HOOK_FAILED` and exit 0. Leg W requires a stall record plus AUT-6's delivered notifier marker per `InvocationID`; otherwise FAIL and `CAPTURE_WATCHDOG_EVIDENCE_GAP`, re-sent daily (reading R-15 reconciles this with X-4). | §3.10.2–§3.10.3, §3.11.3, WP5 |
| 16 | **EM2** sampling exceptions | **Closed.** Per-tick try/except; `RECORDER_SAMPLE_FAILED`, a counter, non-OK `sample_error`; the pinger never exits on Exception; `RECORDER_PINGER_DIED`; `feed_watch_dead`. | §3.10.1, WP3 |
| 17 | **EM3** R5 counts native events | **Closed.** The wrapper counts `OrderInitialized`, `OrderFilled`, `Position*` and `ForecastPoint` once per event id; the heartbeat carries `written_by_type`; R5 runs per type. | §3.4.1, §3.4.4, §3.11.3, V-16 |
| 18 | **EM4** Take-path flush | **Closed.** `flush_for_submit()` before `super().submit_order`; a BUY is refused `capture_gap` on failure, exits never; measured in `CAPTURE_PATH_P99_BUDGET_MS`. | §1.1, §3.4.3, §3.6.2, WP7, WP8 |
| 19 | **EM5** `node_boot_id` = kernel `instance_id` | **Closed.** `build_trade_node_config(instance_id=...)` (default unchanged); one `UUID4` in `trade.py`; `test_capture_node_boot_id_equals_kernel_instance_id`. | §3.1, §3.6.3, WP8 |
| 20 | **EM6** missing `RecorderSample` fields | **Closed.** Accessors `phase`, `discovered_slugs`, `subscribed_count`, `depths_published` (new counter at `data.py:1599`) and the reload and watch fields are in WP3's file list and tests. | §3.10.1, WP3 |
| 21 | **EM7** vacuous per-instrument veto | **Closed.** `md_feed_freshness` is observation only. | §3.7, §3.7.1, WP8, §8 |
| 22 | **EL1** flush-window bound; salvage cite | **Closed.** `lost_in_flush_window` only within 61 s of the boot's last log line; the risk row cites `salvage_truncated_instance` (`quote_tape_salvage.py:508`). | §3.4.4, §3.11.3, §8 |
| 23 | **EL2** retention owner; pinned paths | **Closed.** "None required (~2–3 MB/day), never deleted" in ER-2 and §3.2; the unedited-test list is path-pinned. | §3.2, §4, ER-2 |
| 24 | Errata verdicts ER-1..ER-10 | **Applied** as ruled; ER-9's stale clause is flagged for the coordinator. | §ERRATA-REQUEST ledger |
| 25 | Errata dedupe (E-11 is the vehicle) | **Applied.** ER-8 is recorder-unit-only and includes "the ping source runs from process start, through discovery" and the journal cross-check. | ER-8 |
| R1 | Relay 1: `OnFailure=` on the recorder | **Applied** (step 2). | §3.10.2 |
| R2 | Relay 2: READY once connected and subscribed, never counter-gated | **Applied**; AUT-6's `test_ready_sent_on_connect_and_subscribe_not_gated_on_counters` is consumed. An empty boot listing does not complete discovery on this client (stated). | §3.10.1 |
| R3 | Relay 3: `RECORDER_WATCHDOG_DEFERRED` once per deferral | **Applied**, with a fixture for AUT-6's `test_deferral_journals_recorder_watchdog_deferred_once_per_stall`. | §3.10.1, WP3 |
| R4 | Relay 4: stop hook deleted or evidence only | **Evidence only**, justified (row 7); `test_no_recorder_stop_hook_pages_watchdog_kill` holds, mirrored by `test_hook_module_imports_no_alert_sender`. | §3.10.2 |
| R5 | Relay 5: rotate `TimeoutStartSec` ≥ stop + hook + start + 30 | **Applied:** 4500 s ≥ 120 + 12 + member `TimeoutStartSec` + 30 for any start ≤ 4338 s, and it also covers the extended listing-hole start. The hook bound is cut from 27 s to 12 s. Gated by AUT-6's and AUT-1's bound tests. | §3.10.2, §3.13, WP3 |
| R6 | Relay 6: `NotifyAccess=all`, `Type=notify`, deferral in the classifier | **Applied** (rows 4–6). AUT-6's host facts are adopted: no watchdog before READY, `try-restart` blocks to READY, and a missing READY loops on start timeouts (hence step 1 before step 2, and R-13). | §1.3, §3.10 |

**r8 closures, re-checked (no regression):**
- **§3.15 AST boundary (MEDIUM).** Unchanged: AUT-1 globs only, the allowlist, non-literal modes fail closed, constant reasons. `capture_gap` still cites by reference (`test_capture_gap_refusal_cites_frame_by_reference_only`). The hook's row shrinks to two write roots.
- **Heal age-out.** Unchanged (§3.11.6).
- **Drain before close, exception-safe.** Re-targeted to `on_dispose` (final heartbeat, then flush, then close), because actors stop before strategies (`trader.py:273-290`). Tests: `test_capture_actor_on_dispose_writes_final_heartbeat_before_close_exception_safe` and `test_capture_actor_on_stop_flushes_without_closing`.
- **Stale wording, watch-actor closure, E-9, E-7a, E-7c and the allowlist.** Unchanged. E-9: the hook stays one bounded command, and the rotate stays one command.
- **Pressure-test rows.** Every "Reuse" verdict stands. Row "Forecast inputs (reference `(station, cycle_ns)`)" is strengthened to a native stream with the vintage (R-B). Row "Recorder alive but not capturing" now uses `Type=notify` + `WatchdogSec` + `Restart` + `OnFailure`, so it is more native, not less. Row "fsync durability" is accepted, with the Take path flushed earlier.

---

## §R11 Disposition (`reviews/AUT-1-r10-merged.md`; AUT-6 r15-final build item 7; E-11 adopted)

| # | Item | Disposition | Where |
|---|---|---|---|
| GH1 | **[HIGH]** Inconsistent rotate bound (4200 in the file table vs 4500 elsewhere); derive from one constant | **Closed.** The file-table row is fixed. Every number derives from `QUOTE_TAPE_ROTATE_TIMEOUT_START_SECS = rotate_timeout_start_s(QUOTE_TAPE_MAX_START_SECS)` (`node_config.py`), built from the named terms in `recorder_watchdog.py`. `test_rotate_bound_covers_recorder_stop_and_max_start` asserts the unit literal **equals** that constant and covers the sum recomputed from both unit files; `test_bound_constants_single_source` forbids stray literals. **The derivation corrects the review's rule** (R-16): it adds the last extension's 120 s tail and the 180 s base pre-connect, giving max start 4500 and rotate 4662 → **4680** (`1h 18min`, latest end 10:18Z). | §3.1, §3.10.2, §3.13, §7, §8, §11 R-16, WP3 |
| GM1 | Hung discovery attempt | **Closed.** `RecorderSample.discovery_attempt_inflight_since_ns`, set around each `initialize()` await and cleared in `finally`. `discovery_attempt_hung` when an attempt has been in flight longer than `DISCOVERY_ATTEMPT_BUDGET_S = 180`, derived from (10 s HTTP timeout + 10 s quota interval) × 9 pages against a real universe of 1–2 pages. It stops the extension; the retry sleep stays OK. V-20 measures the budget. | §1.3, §3.10.1, §8, V-20, WP3, ER-8 clause |
| GM2 | Per-write loss detection | **Closed.** The wrapper reads `get_current_file_info()[table]` before and after each judged write. An unchanged `(size, creation_time)` pair is a counted drop that sets `health.ok=False`. A size change or a rotation reset (new `creation_time`) is success. The dedupe and include-filter paths are not judged. On the Take path, `flush_for_submit` returns False after any drop and the Take is refused; exits never are. This was checked against the live-proof rules (§3.6.2, R-18), and R5 FAILs a non-zero `write_drops`. `table_bytes()` sums every file of a table, so 00:00Z is never flat. ER-7 is amended. | §1.3, §3.4.1–§3.4.4, §3.6.2, §3.7.3, V-19, WP1, WP5, WP8, ER-7 |
| GM3 | Stop-hook blind window | **Closed.** It is stated explicitly: a failed or `timeout -k`-killed hook leaves no stall record until the next day's leg W, up to about 38 h. The kill is still paged at once by AUT-6. `recorder_stale` also counts unexplained recorder boots from the recorder kernel's native `live/<instance_id>/config.json`; the 09:00Z rotate is excused once. Read-only, with no `systemctl` or `journalctl` from the node. V-21 pins the marker. | §1.3, §3.7.4, §3.10.2, §8, V-21, WP8, R-17 |
| GM4 | Activating tolerance | **Closed.** WP3 step-2 gate `test_aut6_unit_health_tolerates_activating_within_start_budget`, citing AUT-6 r15-final build item 7, with the budget `QUOTE_TAPE_MAX_START_SECS` and a must-page positive control past it. AUT-6's `test_unit_health_tolerates_activating_within_member_start_budget` is added to the consumed contract list. | §0, §3.10.0, WP3, §7 |
| GM5 | Rotate's `OnSuccess=` timing | **Closed.** Read now: `breezy-station-candidate-register` has no timer, no `[Install]`, `TimeoutStartSec=600`, `flock -n` (never waits) and a watermark catch-up, and `TriggeredBy=` is empty. It has no deadline in 09:00–10:18Z, and its latest end is 10:28Z. WP0 V-22 re-checks it, and `test_station_candidate_register_has_no_deadline_in_rotate_window` pins it. | §1.3, §3.10.2, §3.13, V-22, WP3 |
| GL1a | Timing-constants test also in step 1 | **Closed.** It runs against the committed pending-unit fixture in step 1, and against the deployed unit in step 2 with a fixture-equality test. | §3.10.1, WP3 |
| GL1b | Does `written_by_type` include the heartbeat being written? | **Defined: no.** It is a snapshot taken before the write. R5 expects heartbeat-table rows = count + 1. | §3.4.1, §3.4.4, WP1, WP5 |
| GL1c | Pinger strong reference; idempotent `_connect` | **Closed.** `self._watchdog_pinger_task`; a task is created only if `None` or done; READY latches once per process; `_disconnect` cancels and clears. | §3.1, §3.10.1, WP3 |
| ER-7 | AMEND: per-write size delta | **Applied.** | §ERRATA-REQUEST |
| ER-9 | AMEND: the review's replacement clause | **Applied** verbatim; r10's coordinator note is withdrawn. | §ERRATA-REQUEST |
| ER-1–6, 8, 10 | Stand | **Unchanged**, except one consequential GM1 clause in ER-8. | ledger |

**r9 and r10 closures re-checked (no regression):**
- **R-A** (option B, no `"*"` subscription, custom records never on the bus). Unchanged. GM2 reads a public writer method and adds no bus path.
- **R-B** (`ForecastPoint` streamed as a regular `custom_` table, resolved inside the stream). Unchanged. Its table is judged per write like every other.
- **R-C** (the Take-path copy). Unchanged.
- **EH1** (pinger first in `_connect`; subscribe-before-poll; READY after the initial subscribe). Unchanged. GL1c makes the pinger single and strongly held, and GM1 only shortens a hung extension.
- **EH4** (the per-type window check). Kept as the second detector beside GM2.
- **EM1** (hook failure paths, leg W). Unchanged; GM3 adds an intraday source, not a pager.
- **EM2** (per-tick try/except, done-callback). Unchanged.
- **EM3** (per-id native counts). Unchanged; GM2's not-judged rule uses the same mirror.
- **EM4** (the Take-path flush). Strengthened by GM2.
- **EM5–EM7, EL1, EL2.** Unchanged.
- **X-1..X-7.** Unchanged. `EXTEND_TIMEOUT_USEC` stays native. The stop hook stays evidence only, with no alert import. The deferral horizon is unchanged.
- **Rulings held by both reviewers:** `TimeoutStartSec` on the rotate stays a native bound, now 4680 (R-16); leg W is unchanged.
- **E-11.** Treated as adopted. ER-8 stays recorder-only text appended to it.
- **AUT-6 r14 X rulings.** Ownership split unchanged (§3.10.0).
- **r8-final items** (§3.15 allowlist, heal age-out, drain before close, E-7a/E-7c/E-9). Unchanged. The node closure gains one read-only scan of the recorder's `live/` directory (`node_observations.py`, non-writer).

**Hard invariants (r11):** Nautilus is unmodified; `allow_short` stays False; no safety, settlement or contract test is weakened; the operator caps are never assigned; live enablement and the NO-SEND firewall are untouched; AUT-1 restarts nothing (§9).

## §R12 Disposition (`reviews/AUT-1-r11-merged.md`)

| # | Item | Disposition | Where |
|---|---|---|---|
| 1 | **[MED, SFH]** First write to a lazily created custom table looks like success | **Closed.** Read `writer.py:240-261`: `_create_writer` runs before `serialize_batch` (`:259`), so an empty serialisation or swallowed `write_table` error moves the key from absent to `(0, t)`. Rule added: absent before ⇒ success needs `size > 0` after; otherwise a counted drop. Fail-closed residual (first write coinciding with 00:00Z rotation) stated. Added to V-19's mutation set and WP1. | §3.4.2, V-19, WP1, §7 (c) |
| 2 | **[LOW, SFH]** Pre-READY deferral can outrun `QUOTE_TAPE_MAX_START_SECS` | **Closed, recommended option.** The pre-READY deferral is removed; R-14 retired. A hung start times out and restarts normally, even inside the window (no capture lost before READY). The start budget is absolute, so AUT-6's tolerance needs no deferral state. Choice stated in §3.10.2. Tests: `::test_pre_ready_withhold_is_never_deferred`, `::test_extension_deadline_never_exceeds_max_start_budget`. X-3 (post-READY) unchanged. | §3.10.1, §3.10.2, §9, §11 R-14, WP3, §7 (c) |
| 3 | **[LOW, SFH]** Rename/test the restart counter | **Closed.** `recorder_restarts_unexplained` → `recorder_boots` (all restarts, any cause) minus `RECORDER_ROTATE_BOOTS_EXCUSED = 1`. Stated that it counts every restart. `test_recorder_boots_counts_venue_outage_restarts_and_vetoes` uses a venue-outage fixture. | §3.7.4, §3.10.2, WP8, §7 (c) |
| 4 | **[LOW, TBA]** Count by `config.json` mtime | **Closed.** The count and the newest marker use `config.json` mtimes; the directory mtime is a superset pre-filter only (the ingest's marker writes bump old directory mtimes, `quote_tape_ingest_core.py:407-437`). V-21 asserts it; `test_boot_count_uses_config_json_mtime_not_dir_mtime` pins it. | §3.7.4, V-21, WP8 |
| 5 | **[LOW, TBA]** Units touching `live/<instance_id>` | **Closed.** New WP0 row V-23, with the planning-time reading: no unit moves, compresses or deletes instance directories (ingest and salvage write markers only; disk monitor reads; decisions retention is `decisions/` only). A future mover can only undercount (safe), and is recorded. | V-23, §3.7.4 |
| 6 | **[LOW, TBA]** Cross-plan note on AUT-6's rotate-bound test | **Closed.** Note added: AUT-6's test computes from the unit files and the constant, never a literal; AUT-6 r15-final item 7 already reads 4500/4680 via the constant, so R-16's relay is discharged. AUT-1 adds `test_aut6_rotate_bound_test_reads_constants_not_literals` as a WP3 step-2 dependency gate. | §3.10.2, WP3 |
| 7 | ER-9 text verbatim | **Verified.** The architect's clause (`reviews/AUT-1-r10-merged.md:41`) appears byte-identical, once, in ER-9's replacement block. An explicit verbatim-provenance note is added. | §ERRATA-REQUEST ER-9 |

**r9–r11 closures re-checked (no regression):**
- **R-A, R-B, R-C** unchanged. Item 1 tightens the wrapper's success rule only; there is still no bus path and no `"*"` subscription.
- **GM2 (r11)** strengthened by item 1; its no-false-positive set keeps the successful first write (now `size > 0`), dedupe, excluded class and rotation.
- **GH1 (r11)**: 4500/4680 and the single-constant derivation are unchanged; item 2 makes the max start an absolute bound instead of a bound with a window exception.
- **GM1, GM4, GM5, GL1a–c (r11)** unchanged. GM4's gate test is unchanged and is now joined by item 6's dependency test.
- **GM3 (r11)**: the second source stays; items 3–5 define its count precisely. The ~38 h blind window stands as the review accepted it.
- **X-1..X-7** unchanged. X-3 is the post-READY watchdog deferral, which AUT-6 r15 §3.5 defines; only AUT-1's own extension R-14 is retired.
- **EH1–EH4, EM1–EM7, EL1, EL2** unchanged.
- **ER-1–ER-10**: no text changes; ER-9 verbatim re-verified.
- **r8-final items, E-7a/E-7c/E-9, E-11** unchanged.

**Hard invariants (r12):** Nautilus Trader is unmodified; `allow_short` stays False; no safety, settlement or contract test is weakened, deleted or `xfail`ed; the operator caps are never assigned; live-trading enablement and the NO-SEND firewall are untouched; AUT-1 restarts nothing (§9).
