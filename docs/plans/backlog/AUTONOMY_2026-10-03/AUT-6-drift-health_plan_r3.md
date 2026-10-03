# AUT-6 — Drift and health monitoring: area plan, round 3

## 0. Header

| Field | Value |
|---|---|
| ID | AUT-6 |
| Title | Drift and health monitoring (detectors, actions, delivery proof, unit health, self-heal, monitor-the-monitors) |
| Round | r3 (2026-10-03). r1 and r2 are kept unchanged (`AUT-6-drift-health_plan_r1.md`, `AUT-6-drift-health_plan_r2.md`). The r2 merged review `reviews/AUT-6-r2-merged.md` scored 86, NOT READY (G1–G14). §R3 disposes every G-id. |
| ARCH consumed | `AUTONOMY_ARCHITECTURE.md` **Rev 6**, sha256 `81c3c79fab2217af1e17714424c701d424552d9d73089d763c7cd73df67af04e`, byte-identical to `reviews/snapshots/ARCH_rev6.md` (both hashed 2026-10-03). Rev 6 deltas absorbed: `DRILL_INJECT_HALT` (C6, P6-4) as the HALT class's live proof, with exec-store halts gate-proven only; AUT-6 as the **only** SELF_HEAL caller and owner of the ALERT executor (§4.6, §5, P6-7); the dead-man in AUT-5 (P6-5); per-attempt delivery records at the ARCH path (§4.6, P6-6); `alerts_undeliverable` counts **canary or CRITICAL** records only (C5); demand files archived by rename, never unlinked (W16); the effective-`MemoryMax` check (P6-10); six failing units (§10). |
| C-12 assumption | The second, restrictive-only `demand/v1` writer (INTEGRITY floor, C-12) is **not** in Rev 6; it goes to the Rev 7 or Rev 8 decision. **This plan assumes C-12 is NOT accepted until ARCH says so.** The writer is built only in WP5b, which is held until ARCH ratifies C-12 (technical reason: it would be a second writer of a C5 file, a contract change, ARCH header). Score 3 does not depend on it (§3.3.3, §8 R-13). |
| Code baseline | `4b8347a6` (branch `feat/data-capture-and-risk`). Every `file:line` was checked at that sha. Live facts were read on 2026-10-03, read-only (`systemctl --user show/list-timers/list-unit-files`, `journalctl --user -o json`, `stat`, `du`). r2's live measurements (03:47Z–04:20Z) are kept and cited where reused. |
| Current score | 2 |
| Target | 3 |
| Upstream | AUT-1 (C1 records incl. `OrderLink.time_in_force`, `LifecycleEvent`, `depth_ref`; the `feed_stale`/`recorder_stale`/`capture_gap` observations; recorder and feed unit names for self-heal), AUT-2 (C2 labels), AUT-5 (C5 resolver, fold, drill marker, the policy ruling's `detector_action_map`, the restrictive-only intraday engine, ATTEST, `RegistryWatchActor`, the dead-man, `pins.py`, the demand directory and its archive), ARCH-0 (`persistence/autonomy/`, C6 Protocols) |
| Downstream | AUT-5 (C4 `DRIFT`/`HEALTH`, the health heartbeat with `passes_unknown_streak`, the intraday schedule row for `test_attest_cadence_has_no_expiry_gap`), AUT-7 (`DRILL_INJECT`, `DRILL_INJECT_HALT` in the live producer path), every area (`deliver_with_proof` and the ALERT executor library) |

---

## 1. Goal state

### 1.1 Score-3 criterion (README, verbatim)

> **Score-3 criterion.**
> - Detectors cover every live family for:
>   - data freshness (tape, NBP and observation feeds)
>   - forecast and feature distribution drift
>   - calibration drift on live labels
>   - fill-rate and slippage drift
>   - venue fee and shape drift
>   - permit, process and log liveness
>   - unit health
> - Every detector maps to an action — node-local entry veto (transient conditions, auto-clearing; ARCH C5), halt, demote (through AUT-5), self-heal or alert — with delivery proven.
> - No unit fails as a matter of expected behaviour.
>
> **Live proof:** 7 consecutive days with zero unexplained failed units, plus at least one real or injected drift event per action class that produces its mapped action through the live path.

### 1.2 ARCH Rev 6 §10 obligation (verbatim) and where each part is met

> **AUT-6:** the detector catalogue per kind, split `NODE_LOCAL` / `VERDICT`, each with horizon, policy action class and escalation path; the intraday producer and its HEALTH verdicts cited by ATTEST; `deliver_with_proof`, its per-attempt records (P6-6), the node outbox worker and deadline (W9), and the RED test proving G26; the migration of every CRITICAL site to it and the two-day `alerts_undeliverable` read (W13); the canary, its retry cadence, the receiver's absence rule and its live proof; the six failing units (adding `run-p814078`); `TimeoutStartSec` for every oneshot study (G32); the effective-`MemoryMax` check (P6-10); the SELF_HEAL executor (P6-7); `SELF_HEAL_RESTARTABLE_UNITS` membership, the persisted per-unit restart cap (W11) and the argv-only restart call site.

| Obligation part | Where met |
|---|---|
| Detector catalogue per kind, NODE_LOCAL/VERDICT, horizon, action class, severity, escalation | §3.2, WP5 |
| Intraday producer and the HEALTH verdicts ATTEST cites | §3.4.1–§3.4.3, §3.4.6, WP6 |
| `deliver_with_proof`, per-attempt records at the ARCH path, G26 RED test | §3.6.1–§3.6.2, WP1 |
| Node outbox worker and deadline (W9) | §3.6.4, WP1b |
| Migration of every CRITICAL site | §3.6.3, WP1, WP1b |
| Two-day `alerts_undeliverable` read, canary-or-CRITICAL (W13, C5) | §3.2 #5, §3.7, WP2 |
| Canary, retry cadence, absence rule, live proof | §3.7, WP2, §6 |
| The six failing units | §3.8, WP3, WP3b |
| `TimeoutStartSec` for every oneshot study (G32) | §3.10 rules R-a..R-d |
| Effective-`MemoryMax` check (P6-10) | §3.2 #31, WP3 |
| SELF_HEAL executor, membership, persisted cap, argv-only call site | §3.5, WP4 |
| Monitor-the-monitors, dead-man inputs (P6-5) | §3.11 |

---

## 2. L-1 null hypothesis and reuse

"Reuse" means the component is extended or called, never rebuilt. Rows new in r3 are marked **(r3)**; r2 rows are kept where still true.

| New component | Checked capability (file:line) | Verdict |
|---|---|---|
| `deliver_with_proof` | `WebhookAlertSink.emit` posts then `raise_for_status()` (`runtime/health.py:297-299`); client built with `follow_redirects=False, trust_env=False` (`:251-257`); `TeeAlertSink.emit` routes every branch through `emit_alert` (`:366-369`), which swallows `BaseException` (`:479-510`); `TeeAlertSink.sinks` read-only (`:361-364`); `resolve_alert_sink` returns the tee (`:419-423`). Nautilus has no alert delivery. | **Build, small.** Reuse the webhook branch, `AlertPayload` (`registry/health_model.py:216-248`), the withheld-message discipline and the `loopback_https_receiver` fixture. |
| 3xx semantics | httpx 0.28.1: `raise_for_status` raises for any non-success incl. redirects (`httpx/_models.py:794-829`); `follow_redirects=False`. | **Reuse**; `status_class="3xx"`, `delivered=False`, RED test. |
| Node off-loop delivery (W9) | `nws_actor.py` runs blocking I/O off the loop through a bounded `ThreadPoolExecutor` (`ingest/nws_actor.py:23,92,129,297`). Node sinks built at `app/trade.py:474,533,1148`, `runtime/node_config.py:475`. | **Reuse the bounded-executor pattern** in `OffLoopAlertSink`. |
| Outbox redelivery | Oneshots have no next tick; `replay_daily_runner.record_skip` retries only its own alert (`scripts/analysis/replay_daily_runner.py:733-762`). | **Build, small**: one oneshot timer drains a file outbox. |
| Canary, off-host absence | `breezy-check-alerts` is a manual one-shot (`check_alerts_cli.py:1-31`). | **Build** a timer around the fixed check path; receiver support INFERRED, verify-first (WP2). |
| `permit_lapsed`, `alerts_undeliverable` | `RegistryWatchActor` 60 s tick (ARCH C5); B1 permit watch `[17:10Z, 01:00Z)` (`trade_supervisor_core.py:139,1545-1550`). | **Reuse the watch actor's tick** via pure `observe(now_ns)` objects. |
| `aut6.node_liveness` | `parse_permit_expiry_ns`, `permit_expiry_valid` (`trade_supervisor_core.py:695-712`); schedule constants (`:37-50`); node-log regex (`trade_supervisor.py:798`); recorder live root (`quote_tape_disk_monitor.py:168`); flush 10 s (`node_config.py:292`). | **Reuse read-only.** `trade_supervisor*.py` stays AUT-5a-owned. |
| Intent-flock holder count via `/proc/locks` **(r3, G14)** | `count_intent_lock_holders` reads `DEFAULT_PROC_LOCKS_PATH = /proc/locks` and `/proc/<pid>/stat` (`trade_supervisor.py:201-204,337-390,615-621`). systemd's `ProcSubset=pid` mounts procfs with `subset=pid`, which hides `/proc/locks` (systemd.exec documentation; INFERRED for this host, verified by WP6's unit check). | **Reuse the port**; the producer unit declares `ProcSubset=all`, `ProtectProc=default`; an unreadable `/proc/locks` is UNKNOWN, never "zero holders". |
| Halted-by-design read | `read_family_halt_rows_readonly` + `decode_family_halt_state` (`trial_day_latch.py:333,354`), lock-free reader path (docstring `:1221-1229`). | **Reuse** read-only (G6 `mode=ro` URI) plus the C5 fold. |
| Forecast and calibration drift | `check_drift`, `check_freshness` (`scripts/analysis/nbp_learning_nightly.py:141-151,286-398`). | **Move the pure predicates** into `src/breezy/analysis/nbp_drift.py`. |
| Live calibration leg | `evaluate_calibration_leg` (`forecast_conditional_scoring.py:392`). | **Reuse** on C2 admissible labels. |
| Train/serve parity | `scripts/analysis/nbp_shadow_parity.py:925-946`. | **Reuse** its pure comparison, moved. |
| Fee drift | `FeeDriftProbeActor` wired (`app/trade.py:828-844`); writes `record_policy_halt` (`trial_day_latch.py:1155-1191`). | **Reuse unchanged**; probe-health verdict only. |
| Shape drift | Reconciliation-refusal latch (`component_health_watch.py:401-460`). | **Reuse** read-only. |
| Decision starvation | `all_refused_halt_reason` (`weather_common/halt_detector.py:264-345`); FQ funnel (`app/trade.py:772-776`). | **Reuse the predicate.** |
| Leg normalisation for #15 **(r3, G3)** | `leg_prices.py:29-96`: `VENUE_SIDE_FOR_LEG = {yes: ORDER_SIDE_BUY, no: ORDER_SIDE_SELL}`, `VENUE_INTENT_FOR_LEG = {yes: BUY_LONG, no: BUY_SHORT}`, `instrument_price_for_leg(leg, wire_price)` (`no` → `1 − wire`); `assert_echo_matches_leg` (`:129-148`). Every entry body is `tif: IOC` (`exec/submit_chain.py:360-387`). | **Reuse** the table and the inverse; no second leg-sign implementation. |
| Book at fill time for #15 **(r3, G3)** | Nautilus `BaseDataCatalog.order_book_depth10(instrument_ids, start, end)` (`.venv/.../nautilus_trader/persistence/catalog/base.py:158`); the ingest converts Depth10 (`runtime/quote_tape_ingest_core.py`); ingest runs every 15 min (`breezy-quote-tape-ingest-frequent.timer`, measured LAST 04:30:23Z, NEXT 04:45Z). L-35: depth questions are answered from Depth10, never QuoteTicks. | **Reuse the native catalog query**; no new reader. |
| Unit failure source | systemd 259 "unit failed" entry `MESSAGE_ID=d9b373ed55a64feb8242e02dbe79a49c` with `UNIT_RESULT`, `USER_INVOCATION_ID`, `USER_UNIT`. **(r3, G5) measured since 09-28:** `exit-code` 23, `oom-kill` 2 (`breezy-parity-fq`, 10-01), `signal` 1 (`breezy-exit-window-study`, 09-28), `timeout` 1 (`breezy-discovery-pull`, 10-02 17:22Z). `study_failure_notifier._parse_cause` reads `Result`/`ExecMainStatus` (`runtime/study_failure_notifier.py:134-209`). | **Reuse both**; the four measured results become fixtures. |
| Memory-pressure signal | `MemorySwapPeak`, `MemoryPeak` persist after exit; `ControlGroup=` empty after exit (r2, measured). | **Reuse** persisted properties. |
| Timer liveness **(r3, G6)** | 18 `deploy/systemd/*.timer` files, one a template (`breezy-family-tally@.timer`, live instances `@pm_us_crh_v2`, `@pm_us_crh_v4` enabled); `breezy-live-tally.timer` RETIRED 2026-09-24 (`RULING_R5_prereg_v1_tally_2026-09-24`, file header) and `LoadState=not-found` live. No deploy timer uses a monotonic trigger (grep for `OnUnitActiveSec\|OnBootSec\|OnActiveSec`: none); `breezy-discovery-pull.timer` shows `NextElapseUSecMonotonic=0`. | **Reuse** the property read; literal tables with template and retired handling. |
| Discovery-pull memory **(r3, G12)** | `poll_node_logs_once` globs every `breezy-trade-[0-9]*T*Z.log` (`discovery_set_equality.py:87`) and, on the first poll, reads each file whole from byte 0 (`fh.read()`) and keeps every parsed record (`scripts/analysis/discovery_venue_pull.py:146-197`). Measured: 63 files, 1.7 GB, the largest 1.16 GB (`breezy-trade-20261001T165011Z.log`). | **Redesign the read (stream, scope to today's spawn)**; never raise the ceiling (WP3b). |
| Self-heal restart | None; ARCH §4.5 requires one literal call site. | **Build, one function**, AST-pinned. |
| Detector→action map | ARCH §4.2: in the AUT-5 ruling's `autonomy-policy/v1` block. | **Consume.** |
| Restrictive-demand file | ARCH C5 `demand/v1`: engine-written, honoured by the watch actor, **archived by atomic rename to `evidence/demand/<venue>/`, never unlinked** (W16, `test_retired_demand_file_archived`). | **Reuse** for the INTEGRITY floor only if ARCH ratifies C-12 (WP5b, held). |

---

## 3. Design

### 3.1 Placement (import-linter layers, `pyproject.toml:74-101`)

Layers: `app > analysis > strategy > runtime > adapters > ingest > persistence|registry|normalize > settlement > domain`; live packages never import `breezy.analysis`.

| Module | Layer | Contents |
|---|---|---|
| `src/breezy/persistence/autonomy/detector_catalog.py` | persistence | `DetectorSpec` (frozen: `id`, `detector_class`, `kind` `NODE_LOCAL`\|`VERDICT`\|`IN_NODE_EXEC_HALT`, `cause_class`, `proposed_action_class`, `floor_action_class`, `severity` `CRITICAL`\|`WARN`, `halt_exempt`, `horizon_s`, `escalates_to`, `producer_id`, `unknown_streak_max`, **`live_proof_class`** (r3: `natural`\|`drill`\|`gate_only`)); `CATALOG` (literal only); `REQUIRED_DETECTOR_CLASSES`. |
| `src/breezy/runtime/alert_delivery.py` | runtime | `DeliveryProof`, `deliver_with_proof`, `JournalingWebhookAlertSink`, `OffLoopAlertSink`, `resolve_node_alert_sink`, `DeliveryRecordWriter`, `AlertOutbox`, `drain_outbox`. |
| `src/breezy/runtime/autonomy_node_detectors.py` | runtime | `PermitLapsedDetector`, `AlertsUndeliverableDetector`. |
| `src/breezy/runtime/unit_health.py` | runtime | `UnitObservation`, `UnitFailureClass`, `observe_units`, `read_failed_invocations`, `classify`, `UNIT_RESULT_CLASS` (r3), `UnitHealthJournal`. |
| `src/breezy/runtime/monitor_watch.py` | runtime | Meta-detectors #26–#28, `TIMER_MAX_INTERVAL_S`, `TIMER_RETIRED_BY_RULING` (r3), the heartbeat reader/writer. |
| `src/breezy/runtime/self_heal.py` | runtime | `restart_unit`, `restarts_today`, `SELF_HEAL_DEFERRAL_EXEMPT`. |
| `src/breezy/runtime/autonomy_health_cli.py` | runtime | `breezy-autonomy-health`: unit health, meta-detectors, the **only** SELF_HEAL caller, heartbeat, daily rollup. C4 producer `aut6.health`. |
| `src/breezy/runtime/autonomy_canary_cli.py`, `alert_redeliver_cli.py`, `self_heal_probe_cli.py` | runtime | Canary, outbox drain, drill probe. |
| `src/breezy/analysis/nbp_drift.py` | analysis | Moved pure predicates. |
| `src/breezy/analysis/autonomy/drift_fq.py` | analysis | FQ `VERDICT` detectors. |
| `src/breezy/analysis/autonomy/fill_integrity.py` (r3, G3) | analysis | #15: taker-IOC fill selection, leg normalisation through `leg_prices`, book-at-fill read through `order_book_depth10`. Imports `breezy.adapters.polymarket_us.leg_prices` (analysis may import adapters). |
| `src/breezy/analysis/autonomy/producer_intraday.py`, `producer_daily.py` | analysis | C4 producers `aut6.intraday`, `aut6.daily`. |
| `src/breezy/analysis/autonomy/integrity_floor.py` (WP5b, **held on C-12**) | analysis | Writes the INTEGRITY `demand/v1` file (§3.3.3). Not created unless ARCH ratifies C-12. |
| `src/breezy/strategy/forecast_quantile_ladder/plugin.py` (AUT-1 creates; AUT-6 adds one tuple) | strategy | `NODE_PLUGINS[forecast_quantile_ladder].drift_detectors`. |

Before placing any module, grep the containment tests (L-46, L-54): `tests/unit/test_*containment*`, `test_alerts_env_deploy.py`, `test_alert_egress.py`.

### 3.2 Detector catalogue: kind `forecast_quantile_ladder` (the only `LIVE_GATE_ROUTED_KINDS` member)

Every other kind carries `RefusingPlugin` (ARCH C6). **Proposed action** is AUT-6's proposal for the ruling's `detector_action_map`; the runtime class always comes from the ruling (§3.3). **Sev** is the delivery severity. **HX** = halted-by-design exemption (§3.13). **LP** = live-proof class: `N` natural, `D` drill (AUT-7b), `G` gate-proven only (ARCH C6: exec-store and INTEGRITY halts would freeze the lineage or venue).

| # | Detector id | Required class | Kind | Source and rule | Horizon / period | Proposed action | Floor | Sev | HX | Cause | Escalation | Owner |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `feed_stale` | freshness (NBP, obs) | NODE_LOCAL | AUT-1 | AUT-1 | ENTRY_VETO (code-fixed) | — | WARN | n/a | INFRA | → #7 | AUT-1 |
| 2 | `recorder_stale` | freshness (tape) | NODE_LOCAL | AUT-1 | AUT-1 | ENTRY_VETO | — | WARN | n/a | INFRA | → #7 | AUT-1 |
| 3 | `capture_gap` | freshness (capture) | NODE_LOCAL | AUT-1 | AUT-1 | ENTRY_VETO | — | WARN | n/a | INFRA | → #7 | AUT-1 |
| 4 | `permit_lapsed` | permit liveness | NODE_LOCAL | `now_ns > permit.expires_at_ns` (an integer handed in at composition). `None` permit ⇒ `AGREE detail=no_permit` (`OrderSubmissionPermit.issue` refuses without one, `order_enablement.py:198-204`). Read error ⇒ UNKNOWN (§3.3.2). | 60 s | ENTRY_VETO. Transition page only inside `[17:10Z, 01:00Z)`; the daily expiry (≈ 02:50Z) gets a C1 record and no page. | — | CRITICAL in window | n/a | INFRA | → #6 | AUT-6 |
| 5 | `alerts_undeliverable` | unit health (delivery) | NODE_LOCAL | **ARCH Rev 6 C5:** vetoes unless the newest `delivered=true`, `drill=false` record that is **a canary (`attempt_kind=canary`) or a CRITICAL (`severity=CRITICAL`, any `attempt_kind`)** in today's and yesterday's `evidence/alerts/<date>/` is younger than `ALERT_CANARY_MAX_AGE_H` (26 h). Both directories absent or unreadable ⇒ veto. WARN and INFO records never reset the clock. Listing cached 600 s. Armed after the first canary `delivered=true` record ever (ARCH §5.1). | 60 s | ENTRY_VETO | — | CRITICAL | n/a | INFRA | → #23 | AUT-6 |
| 6 | `aut6.node_liveness` | permit, process and log liveness | VERDICT `HEALTH`, intraday | §3.4.3 | FAIL on 2 consecutive passes | ALERT | — | CRITICAL | Y | INFRA | none | AUT-6 |
| 7 | `aut6.transient_veto_persistent` | freshness | VERDICT `HEALTH`, intraday | a C1 `DetectorEvent` for #1–#3 in `DISAGREE` continuously > 5400 s inside the decision window | 5 min | ALERT | — | CRITICAL | Y | INFRA | none | AUT-6 |
| 8 | `DRILL_INJECT` | (drill) | VERDICT `DRIFT`, intraday | drill marker present with `detector: DRILL_INJECT` ⇒ FAIL; absent or naming the other id ⇒ PASS (Z2) | 5 min | DEMOTE only under the drill clause | — | WARN | N | DRILL | none | AUT-6 / AUT-5/7 |
| 8h | `DRILL_INJECT_HALT` (r3, ARCH Rev 6 C6) | (drill) | VERDICT `DRIFT`, intraday | same marker, `detector: DRILL_INJECT_HALT` ⇒ FAIL; otherwise PASS. Never writes the exec store, never sets a freeze (ARCH `test_drill_halt_never_freezes_or_writes_exec_store`) | 5 min | HALT only under the drill clause | — | WARN | N | DRILL | none | AUT-6 / AUT-5/7 |
| 9 | `aut6.forecast_drift` | forecast drift | VERDICT `DRIFT`, daily | `drift_flags` mean-residual shift > 2.5 °F, trailing 14 FINAL CLI days | daily | ALERT | — | WARN | N | MODEL | → #10 | AUT-6 |
| 10 | `aut6.forecast_drift_persistent` | forecast drift | VERDICT `DRIFT`, daily | #9 FAIL on ≥ 2 of the last 3 runs | daily | DEMOTE | — | CRITICAL | N | MODEL | — | AUT-6 |
| 11 | `aut6.feature_drift` | feature distribution | VERDICT `DRIFT`, daily | PSI > 0.25 on per-station NBP `q90−q10` and on the decision `p_hat` histogram, 7 d vs 8–67 d; 10 fixed bins, ε = 1e-4; `n_min` 5 stations × 7 d × 2 cycles | daily | ALERT | — | WARN | N | MODEL | → #11p (≥ 3 of 5, DEMOTE, CRITICAL) | AUT-6 |
| 12 | `aut6.calibration_drift_offline` | calibration (external truth) | VERDICT `DRIFT`, daily | `drift_flags` CRPS delta > 0.75 °F, champion artefact vs raw NBP, trailing 14 FINAL days | daily | ALERT | — | WARN | N | MODEL | → #12p (≥ 2 of 3, DEMOTE, CRITICAL) | AUT-6 |
| 13 | `aut6.calibration_drift_live` | calibration on live labels | VERDICT `DRIFT`, daily | `evaluate_calibration_leg` on C2 `admissible=true` rows (no canary, no drill, no voided pair), clustered by `(station, climate_day)`; `n_min` from the ruling | daily | DEMOTE (FAIL only) | — | CRITICAL | N | MODEL | — | AUT-6 |
| 14 | `aut6.fill_slippage_drift` | fill rate and slippage | VERDICT `DRIFT`, daily | fill rate = fills / C1 `TrySubmit`, 7 d vs 30 d (two-proportion Wilson, α = 0.01); slippage median shift > 0.02. Drill and voided-pair fills included (W12), canary never. `n_min` 20 | daily | ALERT | — | WARN | Y | MARKET | none | AUT-6 |
| 15 | `aut6.fill_better_than_ask` (r3, G3/G9) | fill rate and slippage (integrity) | VERDICT `HEALTH`, **intraday** | §3.4.6: taker IOC entry fills only; leg-normalised `fill_px` < the **lowest bought-leg ask displayed between decision and fill** (decision `depth_ref` payload plus catalog Depth10 up to the fill timestamp) − 0.001. Missing book ⇒ INCONCLUSIVE, never FAIL. Drill fills included (W12) | 5 min, lookback 36 h | HALT | **HALT** (§3.3.3) | CRITICAL | N | INTEGRITY | — | AUT-6 |
| 16 | `aut6.shadow_parity` | forecast drift (train/serve skew) | VERDICT `HEALTH`, daily | Take-set equality plus Take numeric mismatches on D-1 | daily | ALERT | — | CRITICAL | N | MODEL | — | AUT-6 |
| 17 | `fee_drift_probe` | venue fee drift | IN_NODE_EXEC_HALT (unchanged) | `FeeDriftProbeActor` DISAGREE ⇒ `record_policy_halt(fee_schedule_drift)` | probe interval | HALT (TERMINAL via the mirror) | — | CRITICAL | n/a | TERMINAL | — | existing |
| 18 | `aut6.fee_probe_health` | venue fee drift | VERDICT `HEALTH`, intraday | in the decision window, no `FeeDriftProbeActor: RUNNING` line in the current node log, or `fee_drift_probe_unknown` persisting > 3600 s | 5 min | ALERT | — | CRITICAL | Y | INFRA | — | AUT-6 |
| 19 | `aut6.shape_drift` | venue shape drift | VERDICT `HEALTH`, intraday | a new latched reconciliation refusal (exec store `mode=ro`) or an `_EXECUTION_DRIFT_ALLOWED_KEYS` refusal line | 5 min | ALERT | — | CRITICAL | N | INFRA | — | AUT-6 |
| 20 | `aut6.decision_starvation` | (HaltDetector) | VERDICT `HEALTH`, daily | `all_refused_halt_reason` on the closed decision window; drill-episode decisions included | daily | ALERT | — | CRITICAL | Y | MARKET | — | AUT-6 |
| 21 | `aut6.unit_health` | unit health | VERDICT `HEALTH`, health pass | failed unit in `SELF_HEAL_RESTARTABLE_UNITS`, class ∈ {TIMEOUT, EXIT_CODE, SIGNAL}, under the persisted cap, slot-safe, not already acted on for that `USER_INVOCATION_ID` (§3.5, §3.9) | 10 min | SELF_HEAL | — | WARN | N | INFRA | → #22 | AUT-6 |
| 22 | `aut6.unit_health_unhealable` | unit health | VERDICT `HEALTH`, health pass | any other failed in-scope invocation, or a failed restart | 10 min | ALERT | — | CRITICAL for data-path units, else WARN | N | INFRA | — | AUT-6 |
| 23 | `aut6.alert_delivery` | unit health (delivery) | VERDICT `HEALTH`, health pass | any of (G10 adds the last two): a canary slot with no `delivered=true` record after its hourly retries; an outbox entry older than 24 h (`abandoned`); an `outbox_write_failed` record or `outbox_write_failures>0` summary counter; **`journal_write_failures>0` in any AUT-6 unit's summary line or an `alert_delivery_journal_unwritable` line in the node log tail since the last pass**; **the delivery-record root failing `os.access(W_OK)` or holding < 64 MiB free (`statvfs`)** | 10 min | ALERT | — | CRITICAL | N | INFRA | → #5 | AUT-6 |
| 24 | `aut6.unit_config_drift` | unit health | VERDICT `HEALTH`, daily | an installed `breezy-*` unit (symlink target or drop-in) differs from `deploy/systemd/`; today the two `zz-memory-containment-TEMPORARY.conf` drop-ins | daily | ALERT | — | WARN; CRITICAL from 2026-10-16 | N | INFRA | — | AUT-6 |
| 25 | `aut6.detector_blind` | unit health (meta) | VERDICT `HEALTH`, every producer pass | any VERDICT detector whose inputs were unreadable for `unknown_streak_max` consecutive passes (2 intraday, 1 daily, 2 health; #15: 72 passes = 6 h, §3.4.6) | per pass | ALERT | — | CRITICAL | N | INFRA | — | AUT-6 |
| 26 | `aut6.producer_stale` (r3, G2) | permit, process and log liveness (meta) | VERDICT `HEALTH`, health pass | intraday producer heartbeat older than 900 s; **or the heartbeat's `fold_ok=false`**; or, inside `[17:05Z, 01:00Z)`, any (subject, intraday detector) with no verdict whose `valid_until_ns > now` | 10 min | ALERT | — | CRITICAL | N | INFRA | — | AUT-6 |
| 27 | `aut6.daily_verdict_absent` (r3, G11) | unit health (meta) | VERDICT `HEALTH`, health pass | for any subject, the newest daily verdict was produced > 30 h ago; `metrics.last_skip_reason` and `metrics.skips_since_last_verdict` from the daily skip records (§3.4.4) | 10 min | ALERT | — | CRITICAL | N | INFRA | — | AUT-6 |
| 28 | `aut6.timer_liveness` (r3, G6) | unit health | VERDICT `HEALTH`, health pass | §3.9 timer rules: every key of `TIMER_MAX_INTERVAL_S` (templates expanded to enabled instances) must be enabled and `active`, have a future next elapse, and a last trigger within its interval + 900 s; `LastTriggerUSec` empty or 0 after grace ⇒ FAIL; a retired timer found enabled ⇒ FAIL | 10 min | ALERT | — | CRITICAL | N | INFRA | — | AUT-6 |
| 29 | `aut6.health_monitor_stale` (r3, G1) | permit, process and log liveness (meta) | VERDICT `HEALTH`, intraday | the health heartbeat is older than 1800 s **or** its `passes_unknown_streak ≥ 3` (30 min of UNKNOWN passes) | 5 min | ALERT | — | CRITICAL | N | INFRA | — | AUT-6 |
| 30 | `aut6.halted_too_long` (r3, G7) | permit, process and log liveness | VERDICT `HEALTH`, intraday | the venue champion has been HALTED (fold) or exec-store halted for > 86400 s; `metrics.halted_age_s`, `metrics.halt_detail`; re-pages every 24 h while it persists | 5 min | ALERT | — | CRITICAL | **N** (it measures the halt) | INFRA | — | AUT-6 |
| 31 | `aut6.memory_budget` (r3, ARCH Rev 6 P6-10) | unit health | VERDICT `HEALTH`, daily | effective `MemoryMax` (`systemctl --user show -p MemoryMax`, drop-ins included) violates ARCH §5.2: any studies-flock holder > 16G; own-lock autonomy units together > 4G; or 30.67 GiB − (largest studies holder + own-lock total + node + recorder + ingest effective limits) < 10G | daily | ALERT | — | CRITICAL | N | INFRA | — | AUT-6 |

**Required-class coverage (C6):** freshness {1, 2, 3, 7}; forecast and feature drift {9, 10, 11, 16}; calibration {12, 13}; fill rate and slippage {14, 15}; fee and shape {17, 18, 19}; permit, process and log liveness {4, 6, 26, 29, 30}; unit health {5, 21–25, 27, 28, 31}.

**Action-class coverage:** ENTRY_VETO {1–5}; ALERT {6, 7, 9, 11, 12, 14, 16, 18–20, 22–31}; SELF_HEAL {21}; DEMOTE {8, 10, 11p, 12p, 13}; HALT {8h, 15, 17}.

**Live-proof class (r3):** HALT is proven live by #8h only (drill); #15 and #17 are gate-proven (RED→GREEN), as ARCH Rev 6 C6 declares for exec-store and INTEGRITY halts. DEMOTE by #8 (drill). ENTRY_VETO, ALERT, SELF_HEAL natural or injected-live (§6).

### 3.3 Detector → action map, UNKNOWN handling, INTEGRITY floor

#### 3.3.1 Consumption contract and executors (ARCH Rev 6 §4.6, P6-7)

- `CATALOG` is the code proposal. The ruling's `detector_action_map` lists **exactly** the VERDICT ids of `CATALOG`, including `DRILL_INJECT` and `DRILL_INJECT_HALT` (`test_policy_detector_map_covers_catalog_exactly`, deploy copy). The H16 skip rule is in WP5.
- Producers stamp `declared_action_class` from the ruling's map via AUT-5's single-read loader. If the ruling is absent, unreadable or sha-mismatched, the producer writes `declared_action_class = max(floor_action_class, ALERT)` with `assumptions:["policy_unavailable"]`, sends the alert through §3.6, and the engine treats the verdict as `ERROR`. INTEGRITY rows declare the HALT floor.
- NODE_LOCAL ids are code-fixed `ENTRY_VETO` and never appear in the map. `IN_NODE_EXEC_HALT` (#17) is mirrored by the engine's fixed table.
- **Executors (ARCH Rev 6):**
  - ENTRY_VETO: `RegistryWatchActor` (AUT-5) polling #1–#5.
  - DEMOTE, HALT: the restrictive-only intraday engine pass (AUT-5).
  - **SELF_HEAL: `breezy-autonomy-health` only.** It is the single autonomy caller of `restart_unit`. AUT-1 supplies recorder and feed observations and names their units for the tuple; it never calls the restart site (`test_restart_call_site_is_unique_and_argv_only` asserts one caller module).
  - **ALERT: the producing unit, through AUT-6's executor library** (`deliver_with_proof` + outbox + redeliver). AUT-6 owns the library; AUT-2 and AUT-4 producers raising ALERT-mapped verdicts call it too.
  - Before the ruling (AUT-5b) the health unit runs `ALERT_ONLY`, so SELF_HEAL live clocks start at filing (ARCH §4.6).
- Z10/W2: every verdict carries `metrics.cause_class`; INFRA never charges `MAX_RECOVERABLE_RESUMES_PER_LINEAGE_14D`; DRILL (#8, #8h) charges only the drill budget.

#### 3.3.2 UNKNOWN fails closed

- **NODE_LOCAL (#4, #5).** Any observation error ⇒ `UNKNOWN`. For at most `WATCH_TICK_STALE_S` (180 s) it vetoes nothing; past that it returns its own veto reason, AUT-1's writer records `DetectorEvent(state=UNKNOWN, detail=persistent)`, and the transition sends a CRITICAL `aut6_detector_unknown_persistent`. It clears on the next good observation.
- **VERDICT detectors.** An unreadable input gives `outcome=INCONCLUSIVE`, `assumptions:["input_unreadable"]`, `metrics.unknown_streak=k`. INCONCLUSIVE never counts as PASS. At `k ≥ unknown_streak_max` the producer writes #25 FAIL naming the detector and sends a CRITICAL; the liveness detectors #6, #7, #18, #29 and #30 themselves report FAIL `reason=blind`.
- **Unit-health reads.** A non-zero exit, timeout or D-Bus error from `systemctl`/`journalctl` makes the pass `UNKNOWN`, never "zero failures", increments `passes_unknown_streak` in the heartbeat, and feeds #25. **G1:** a streak ≥ 3 is FAIL for two independent watchers, #29 (intraday producer) and the AUT-5 dead-man (§3.11), so a persistently UNKNOWN health unit can never read as healthy.
- **Fold (G2).** An unreadable fold (resolver raises, chain verify fails, export prefix mismatch) or an **empty fold** (the venue chain holds zero rows, which is impossible after AUT-5a's bootstrap) is never "no subjects". The producer writes a CRITICAL `fold_unreadable` through §3.6, writes `fold_ok=false, fold_reason=<unreadable|empty>` into its heartbeat, and writes no subject verdicts; #26 FAILs on `fold_ok=false` at the next health pass. A non-empty fold with no CHAMPION/HALTED/CHALLENGER (all RETIRED, e.g. after the KILL) is the legitimate `_host/` case, with `fold_ok=true`.

#### 3.3.3 INTEGRITY floor (C-12 held; G4, G9)

- `floor_action_class=HALT` for every `cause_class=INTEGRITY` row (today #15). It is a code literal and does not depend on the policy file being readable.
- **Path that exists under Rev 6 (no C-12):** an INTEGRITY FAIL is a C4 verdict declaring HALT; the intraday engine writes the registry HALT (INTEGRITY cause, venue frozen per C5) within one engine pass (≤ 150 s after the producer) and the watch actor vetoes on its next tick. The CRITICAL goes out with proof at the same pass. Worst-case detection latency is in §3.4.6.
- **Engine-independent path, held on C-12 (WP5b).** If and only if ARCH Rev 7/8 ratifies C-12, `integrity_floor.write_demand` writes, in addition to the verdict, one `demand/v1` file `registry/demand/<venue>/<family_id>_<ts_ns>.json` in the exact C5 schema (atomic, 0444, ≤ `DEMAND_FILE_MAX_BYTES`, `reason=integrity_floor`, `verdict_id`). The watch actor already honours it as `registry_restrictive_pending`.
  - **Clearing (W16, corrected from r2):** the engine moves the file by atomic rename to `evidence/demand/<venue>/` once the chain shows the family HALTED, RETIRED or not CHAMPION at a later row; it is **archived, never unlinked**. If the engine marked the verdict `ERROR` (e.g. policy unreadable), the file stays and the veto holds until build-side incident handling (W15) evidences the root cause under `docs/incident-reports/`, has it peer-reviewed and clears through the C5 API; never an operator decision, never automatic.
  - **Slot reservation (G9):** C-12 includes `DEMAND_FILES_RESERVED_FOR_INTEGRITY = 1`: the engine's demand writer refuses its own write when the venue already holds `DEMAND_FILES_MAX − 1` files (it then relies on its per-pass retry and CRITICAL), so one slot is always free for INTEGRITY. The INTEGRITY writer **never refuses on count**; if a defect left the directory full, its write crosses `DEMAND_FILES_MAX` and trips the venue-wide veto, which is the more restrictive outcome (one sender per venue).
- **If C-12 is rejected:** the Rev 6 path above is the design; residual R-13 (§8).
- A defect-signature fill is exactly the case that warrants stopping and investigating (L-25).

### 3.4 Producers (C4 writers)

#### 3.4.1 Common rules

- Output `derived/verdicts/<family_id>/<YYYY-MM-DD>/<verdict_id>.json` (0600 file, 0700 dir), `verdict/v1`, `mkstemp` + `os.replace`, `verdict_id` = sha256 of the canonical body (write-once).
- `producer_code_sha` ∈ `pins.PRODUCER_SOURCE_SHA256[producer_id]` for `aut6.intraday`, `aut6.daily`, `aut6.health`.
- Subjects: every family the fold names CHAMPION, HALTED or CHALLENGER per venue. Host-wide detectors (#6, #18, #19, #21–#31) take the venue champion as subject; with none (non-empty fold), they write `derived/verdicts/_host/`, which the engine ignores.
- **Validity (W1, Z4):** intraday and health verdicts `valid_until_ns = produced_at_ns + 8 h` (`INTRADAY_VALIDITY_S = 28800` = `ATTEST_VERDICT_VALIDITY_H`); daily `+ 26 h`; the producer refuses above `MAX_VERDICT_VALIDITY_H`.
- **Refresh:** write on outcome change, or when the newest verdict for `(subject, detector)` is older than `INTRADAY_REFRESH_S = 3600` (= `INTRADAY_ATTEST_VERDICT_PERIOD_MIN` 60).
- **ATTEST invariant (ARCH §4.5 W1, restated in ARCH's names):** `ATTEST_PERIOD_H + L_max + ATTEST_MARGIN_H ≤ ATTEST_VERDICT_VALIDITY_H` with `L_max` = 60 min + 150 s ⇒ 6 + 1.04 + 0.5 ≤ 8. AUT-6's side: at every instant the newest PASS per (subject, intraday HEALTH detector) has ≥ 28800 − 3600 − 300 = 24900 s of validity ≥ 21600 + 300 s. Pinned by `test_intraday_refresh_keeps_attest_gap_free`; the schedule row goes to AUT-5's `test_attest_cadence_has_no_expiry_gap`.
- `#6` reports `PASS window=closed` outside its window and `PASS reason=family_halted` while halted (§3.13).
- No paths, env values or ids in verdicts (payload hygiene scan).

#### 3.4.2 `breezy-autonomy-producer-intraday` (`aut6.intraday`)

- Inputs (read-only): C1 files for today and yesterday (`DecisionRecord`, `OrderLink`, `LifecycleEvent`, `DetectorEvent`); the C1 payload store `derived/capture_payloads/depth10/`; the ingested catalog through `order_book_depth10` (#15 only); the newest `breezy-trade-*.log` (tail ≤ 4 MiB); the exec store via the `mode=ro` URI; the recorder live root (stat only); `/proc/locks`; the drill marker; the C5 fold; the health heartbeat.
- Detectors: #6, #7, #8, #8h, #15, #18, #19, #29, #30, and #25 for its own detectors.
- Lock `derived/verdicts/.aut6-intraday.lock`, `flock -n`; on contention `PRODUCER_INTRADAY SKIPPED lock_held`, exit 0, 3 consecutive skips ⇒ WARN. Never the studies flock.
- **Heartbeat (G2):** after every run, including a failed fold read, it rewrites `derived/verdicts/.aut6-intraday.heartbeat` (single writer, under its lock, `os.replace`) with `{ts_ns, invocation_id, wrote, skipped, fold_ok, fold_reason}`.
- **Reciprocal watch (G1):** #29 reads `evidence/unit_health/heartbeat.json` and FAILs on age > 1800 s or `passes_unknown_streak ≥ 3`. It is a verdict (and CRITICAL with proof), not only a log line.
- **Unit sandbox (G14):** the unit declares `ProcSubset=all` and `ProtectProc=default` so `/proc/locks` and `/proc/<pid>/stat` are visible; `ReadOnlyPaths=` on the exec store, registry and catalog; `ReadWritePaths=` only on `derived/verdicts` and `evidence/alerts`. An unreadable `/proc/locks` makes the process conjunct UNKNOWN (never "0 holders").

#### 3.4.3 `aut6.node_liveness` (#6) (unchanged from r2 except where marked)

- **Window and boot grace.** Evaluated in `[SELF_CHECK_UTC, 01:00Z)` = `[17:05Z, 01:00Z)` (`trade_supervisor_core.py:39`); before that `PASS window=boot_grace` (16:40Z–17:05Z) or `PASS window=closed`. Permit lines measured about 1 s after boot (16:50:15, 16:50:12, 16:50:40 on 09-30, 10-01, 10-02).
- **Relaunch grace.** Newest node log's name timestamp < 900 s old ⇒ `PASS reason=relaunch_grace`; void when ≥ 3 node logs were created in 3600 s ⇒ `FAIL reason=relaunch_loop`.
- **Conjuncts** (all required, each in `metrics`):
  1. **Process:** exactly one intent-flock holder (`count_intent_lock_holders` port). `/proc/locks` unreadable ⇒ UNKNOWN (r3, G14).
  2. **Log:** newest node-log mtime age ≤ `LOG_MTIME_MAX_S = 1500` (measured max inter-line gap 3 s; FQ funnel flush 900 s).
  3. **Permit:** the newest log holds a permit line with `expires_at_ns > now`.
  4. **Tape:** newest file mtime under the recorder live root `<BREEZY_TRADE_CATALOG_ROOT>/live` ≤ `TAPE_MTIME_MAX_S = max(1500, 2 × observed max gap)` (WP6 verify-first). Ingest output is not the source.
- **Halted-by-design:** §3.13. Unreadable halt state or fold ⇒ UNKNOWN.
- **FAIL** only on 2 consecutive failing passes.

#### 3.4.4 `breezy-autonomy-producer-daily` (`aut6.daily`) (G11)

- Inputs: NBP derived store, settlement truth, C2 labels (drill and voided-pair fills included for #14 and #20; excluded for #13), C1 decisions, FQ funnel files, the champion artefact, `systemctl --user show` (for #24, #31).
- Detectors: #9–#14, #16, #20, #24, #31 (and #25 for its own). **#15 moved to intraday (G9).**
- **Studies lock taken by the CLI, not by `flock(1)` (G11).** `ExecStart` runs the Python CLI directly; the CLI opens `~/.local/share/breezy/breezy-studies.lock` and polls `fcntl.flock(LOCK_EX | LOCK_NB)` until a 300 s deadline. On timeout it prints `PRODUCER_DAILY SKIPPED lock_timeout waited_s=300 slot=<05:30|13:00>`, writes one write-once skip record `derived/verdicts/_aut6_daily_skips/<YYYY-MM-DD>_<slot>.json` `{ts_ns, slot, reason}` (single writer: this unit), and **exits 0**. A `flock -w` wrapper would exit 1 on timeout and make the unit fail as expected behaviour, which the score-3 criterion forbids.
- The health pass's #27 reads the skip records: `metrics.skips_since_last_verdict`, `metrics.last_skip_reason`. The first skip of a day sends a WARN; two skipped slots age the newest daily verdict past 30 h (prior 05:30Z + 31.5 h at the 13:00Z skip), so #27 FAILs CRITICAL with the reason attached.
- An unreadable or empty fold (§3.3.2) also writes a skip record with `reason=fold_unreadable` plus the CRITICAL.
- **Two slots:** 05:30Z and 13:00Z; the 13:00Z run is `PRODUCER_DAILY SKIPPED already_produced` (exit 0, no skip record) when every (subject, daily detector) has a verdict produced that UTC day.

#### 3.4.5 Z12 SLO (unchanged)

The producer runs at `*:00/5` and AUT-5's intraday engine at `*:02/5` (150 s offset). No `.path` unit. Worst case `DetectorEvent → entry veto` ≤ 11 min (`test_demotion_latency_slo`, producer half).

#### 3.4.6 `aut6.fill_better_than_ask` (#15) in full (G3, G9)

- **Population.** Every C1 `LifecycleEvent(event=FILLED)` in the 36 h lookback whose `client_order_id` joins (C1 invariant ii) to an `OrderLink` with `time_in_force == IOC` and to an entry `DecisionRecord(kind=TrySubmit)`. **Excluded:** resting orders (`time_in_force ∈ {GTC, GTD, DAY}` or anything ≠ IOC: a resting bid legitimately fills below the current ask), exit orders (client ids carrying an `exit_tags.py` prefix), `source=canary`. Drill and voided-pair fills are included (W12). An unjoinable fill is not judged here; it is AUT-1's join-gap `HEALTH` FAIL.
- **Leg normalisation.** The leg comes from the instrument id (`leg_of`, composite NO-leg ids, G24). The C1 fill `px` is the Nautilus instrument price (the exec client books NO fills via `instrument_price_for_leg`). If a record instead carries the venue's representation of a NO buy, `(ORDER_SIDE_SELL, ORDER_INTENT_BUY_SHORT)` per `VENUE_SIDE_FOR_LEG`/`VENUE_INTENT_FOR_LEG`, its wire price is converted with `instrument_price_for_leg("no", px)`. If the price space cannot be decided from the record (memory note `venue-represents-no-buy-as-sell-buy-short`), the fill is `INCONCLUSIVE reason=leg_price_space_undecidable`, never FAIL.
- **Book at the fill, not the decision ask.** `ref_ask = min(decision ask from the C1 `depth_ref` Depth10 payload, every bought-leg best ask in catalog Depth10 frames with ts in [eval_ns, fill ts_ns])`, read with one native `order_book_depth10(instrument_ids=[id], start=eval_ns − 60 s, end=fill_ts + 5 s)` call. For a NO leg without its own depth rows, the NO ask is `1 − best YES bid` of the paired YES instrument via `instrument_price_for_leg` (WP6 verify-first records which form the catalog holds). Same-timestamp book updates are applied before the quote derived from them (L-25 rule).
- **Rule.** `FAIL` iff `fill_px < ref_ask − 0.001`. A legitimate ask drop between decision and fill lowers `ref_ask`, so the fill matches a displayed level and PASSes, with `metrics.ask_drop_between_decision_and_fill=true`.
- **Missing book.** No Depth10 frame covering `[eval_ns, fill_ts]` (ingest lag or gap) ⇒ that fill is `pending_depth`; the verdict is INCONCLUSIVE only if a pending fill is older than 6 h (`unknown_streak_max = 72` passes), then #25 CRITICAL. Pending fills are re-evaluated every pass inside the 36 h lookback.
- **Latency (G9).** Fill → depth in the catalog (ingest every 15 min; measured catalog staleness up to 1769 s on a healthy host, r2) → next producer pass (≤ 5 min) → engine HALT (≤ 150 s) → watch-actor tick (≤ 60 s): **≈ 39 min worst case on a healthy ingest**, vs r2's daily ≈ 12 h. A stalled ingest extends it until #25 fires at 6 h; the repeated-defect exposure in that time is bounded by `rung_net_position_held`, the per-position cap and the venue daily budget (unchanged, operator-owned values never read).
- **Remaining false-positive risk, stated.** (i) A venue fill at a price inside the spread that never appeared in a Depth10 frame (hidden or very short-lived liquidity between two 10-level snapshots) would FAIL; no such case is known on this venue, and the action is a HALT on an INTEGRITY freeze, which fails closed. (ii) A recorder-vs-node clock skew > 5 s could exclude the matching frame; the window pads −60 s/+5 s and records `metrics.max_frame_gap_ns`. (iii) A mis-joined `client_order_id` is impossible by C1 invariant (ii) but would surface as AUT-1's join gap first. **Clearing:** the INTEGRITY HALT freezes the venue; it clears only through build-side incident handling (ARCH W15): root cause evidenced under `docs/incident-reports/`, peer-reviewed, then cleared through the halt CLI and the registry CLI on the C5 API. Never an operator decision, never automatic.
- **Memory.** ≤ 5 fills a day, one bounded single-instrument query each; WP6 verify-first measures the ΔRSS of one query on the largest instrument-day in a fresh child (L-49 amendment) and requires it inside the 512M unit cap with 2× margin.

### 3.5 Self-heal (ARCH Rev 6 §4.6: `breezy-autonomy-health` is the only caller)

- **Call site, the only one:** `runtime/self_heal.py::restart_unit(unit, *, invocation_id, run=subprocess.run) -> RestartOutcome`, called only from `autonomy_health_cli.py`.
  - Raises `ValueError` unless `unit in pins.SELF_HEAL_RESTARTABLE_UNITS`.
  - Runs `run(["systemctl", "--user", "--no-block", "restart", unit], check=False, timeout=30, capture_output=True)`; argv list, never `shell=True` (`--no-block`: C-17 in §11).
  - Never targets `breezy-trade*`, `breezy-autonomy-engine*`, the supervisor or the dead-man; never writes under `~/.config/systemd` or `~/.config/breezy`.
- **Persisted cap (W11):** one write-once record `evidence/selfheal/<YYYY-MM-DD>/<ts_ns>_<unit>.json` (0444) **before** `run`, carrying `invocation_id` of the failed run; `restarts_today(unit)` counts the files; `SELF_HEAL_MAX_RESTARTS_PER_UNIT_PER_DAY = 2` (ceiling ≤ 3); unreadable directory ⇒ no restart plus #25.
- **Per-invocation idempotency (G5):** before restarting, the executor looks for a selfheal record whose `invocation_id` equals the failed `USER_INVOCATION_ID`; if one exists, it never restarts again for that invocation (a crash-and-replay cannot double-restart).
- **Slot safety:** a restart only if `now + TimeoutStartSec(unit)` misses `[16:30Z, 17:10Z)`; otherwise deferred to 17:10Z and journaled. Exemption `SELF_HEAL_DEFERRAL_EXEMPT = ("breezy-autonomy-producer-intraday.service",)`.
- **Membership and idempotency evidence (G14):**

| Unit | Why a repeat run is safe (evidence) | Verdict |
|---|---|---|
| `breezy-discovery-pull` | Writes `<out-dir>/<day>.json` and `<day>_pages.json` by day key, last write wins (`scripts/analysis/discovery_venue_pull.py:398-401`); public read client only. Non-atomic `write_text` is fixed to `mkstemp` + `os.replace` in WP3b. | member after WP3b |
| `breezy-fee-evidence-pull` | Skips a day that already has `slugs.json` + `summary.json` (`_has_real_pull_record`, `scripts/venue/fee_drift_evidence_pull.py:550-556`); replaces via tmp + rename (`:546`). | member |
| `breezy-capital-flow-pull` | `write_snapshot` is `O_EXCL` per `pulled_at_ns` (`persistence/external_capital_flows.py:243-271`): a repeat adds one independent write-once snapshot, no read-modify-write. | member |
| `breezy-asos-refresh` | Takes the studies lock with `flock -n` (`deploy/systemd/asos-refresh-run.sh:34`); output idempotency of the fetch is **INFERRED**; its `SKIPPED-INFRA` paths `exit 75` (`:26,31,32`) and the unit has no `SuccessExitStatus=75` (RED for `test_every_wrapper_skip_path_exits_success`). | member only if WP4's verify-first shows the fetch replaces by key; else removed from the tuple |
| `breezy-autonomy-producer-intraday` | Content-hash verdict ids, write-on-change, heartbeat under its lock. | member, deferral-exempt |
| `breezy-autonomy-alert-redeliver` | Outbox entries move by rename on 2xx; ENOENT means already delivered; at-least-once pages (a duplicate page is possible, never a lost one). | member |
| `breezy-autonomy-canary` | The retry gate (§3.7) decides from the records; a restart sends at most one extra INFO canary. | member |
| `breezy-autonomy-selfheal-probe` | ARMED → HELD → HEALED state file, once per ISO week. | member (drill target) |

  Studies over 1G are excluded. AUT-1 adds recorder and feed units through the same tuple, each with the same evidence row.
- **Classification before restart (L-49):** `MEMORY_CEILING_SUSPECT` needs both CPU/wall < 0.3 and `MemorySwapPeak > 0` or `MemoryPeak ≥ 0.9 × MemoryHigh`; low CPU/wall without a memory signal is `TIMEOUT` (restartable). `MEMORY_CEILING_SUSPECT` and `OOM` are never restarted (→ #22, L-49 triage line); `NOFILE_EXHAUSTED` → ALERT.
- **Verification:** the next pass waits until `ActiveState ∉ {active, activating}`, then requires `Result=success` for an invocation newer than the restart record; failure ⇒ #22.
- **Drill probe:** weekly, Mon 10:00Z; ARMED → exit 1 → restart → HEALED → exit 0; `drill=true`.

### 3.6 Delivery proof and the ALERT executor (G25, G26, Z13, W9, P6-6)

#### 3.6.1 API

```python
@dataclass(frozen=True, slots=True)
class DeliveryProof:
    delivered: bool
    status_class: Literal["2xx", "3xx", "4xx", "5xx", "transport", "not_configured", "outbox_overflow"]
    event: str
    ts_ns: int
    recorded: bool

def deliver_with_proof(sink: AlertSink, payload: AlertPayload, *, writer: str,
                       records: DeliveryRecordWriter,
                       attempt_kind: Literal["inline", "redeliver", "canary", "check"],
                       outbox: AlertOutbox | None = None, drill: bool = False,
                       now_ns: Callable[[], int] = time.time_ns) -> DeliveryProof: ...
```

- Calls `emit` directly on the webhook branch (via `TeeAlertSink.sinks`); every other branch receives the payload through `emit_alert` first. `httpx.HTTPStatusError` maps to `status_code // 100` (includes 3xx); other `httpx`/`ssl`/`OSError` errors map to `transport`. Only the exception type is logged. Per-attempt hard timeout `ALERT_DELIVERY_TIMEOUT_S = 5` (ceiling ≤ 10).
- `status_class="outbox_overflow"` replaces r2's `backpressure` (ARCH §4.6 name).

#### 3.6.2 Per-attempt records and outbox (rebased on ARCH §4.6; G8, G10)

- **Records (ARCH path):** one write-once file per attempt `evidence/alerts/<YYYY-MM-DD>/<ts_ns>_<writer>_<d|f>.json` (`d` delivered, `f` failed), 0444 in 0700 dirs, created `O_CREAT|O_EXCL` (a same-ns collision retries at `ts_ns + 1`). Writer ids: `node`, `intraday`, `daily`, `health`, `redeliver`, `canary`, `check`, `deadman`, `engine`, and `legacy-<component>` for the migrated sites; no two writer types share a file (L-50, P6-6). Fields: ARCH's `event`, `ts_ns`, `delivered`, `status_class`, plus `severity`, `attempt_kind`, `drill`, `site`, `payload_sha256`, `outbox_entry` (needed by the C5 canary-or-CRITICAL rule; C-14). No URL, message or detail.
- **Record write failure (G10):** never blocks delivery; logs `alert_delivery_journal_unwritable` at ERROR (type only), increments the process counter printed in the unit summary line as `journal_write_failures=<n>`, and returns `recorded=False`. #23 reads both (table row 23). Because #5 counts only records, an unwritable record root also ends in the node veto after 26 h: fail closed.
- **Outbox scope:** every **CRITICAL** from any site, and every ALERT-class payload of any severity emitted by an AUT-6 unit.
- **Outbox written at submit time (G8):** for an in-scope payload the caller writes `evidence/alerts/outbox/<writer>/<ts_ns>_<sha8>.json` (0400, `mkstemp` + `os.replace`) **before** the HTTP attempt. On 2xx the same process moves it by atomic rename into `evidence/alerts/outbox/delivered/` (never unlinked). A SIGKILL between submit and 2xx leaves the entry pending, so the redeliver unit sends it: delivery is at-least-once (a duplicate page is possible, a lost CRITICAL is not).
  - Both the originating process and the redeliver unit only *create* (originator) or *rename* (either) a write-once file; neither rewrites it, and ENOENT on rename means "already delivered". `test_autonomy_files_have_one_writer` gets the row `outbox/<writer>/* → create: <writer>; rename: <writer> | redeliver`.
  - The redeliver unit ignores entries younger than `OUTBOX_MIN_AGE_S = 2 × ALERT_DELIVERY_TIMEOUT_S + 30 = 40 s`, so it never races an in-flight inline attempt.
  - Count bound: `ALERT_OUTBOX_MAX = 64` pending entries per writer (ceiling ≤ 256); beyond it the payload is recorded `outbox_overflow` and #23 FAILs.
- **Write-on-change is not consumed by a failed send:** a producer's transition alert counts as sent only on `delivered=true`; otherwise the outbox entry carries it and the next verdict keeps `metrics.alert_pending=true`.
- **Outbox write failure:** logs `alert_outbox_unwritable`, writes a record with `outbox_write_failed=true` when records are writable, increments `outbox_write_failures=<n>`; #23 FAILs.

#### 3.6.3 Every CRITICAL through proof without touching 48 call sites (Z13)

- `resolve_alert_sink` builds `TeeAlertSink(LoggingAlertSink(), JournalingWebhookAlertSink(url, records=…, outbox=…))`.
- `JournalingWebhookAlertSink(WebhookAlertSink).emit` writes the outbox entry first for a CRITICAL, runs `deliver_with_proof` on the parent branch, and **re-raises** `AlertNotDeliveredError` so `emit_alert` contains it and logs as today. Existing tee-containment tests stay green unedited.
- WARN and INFO from the 48 legacy sites keep `emit_alert` semantics (recorded, not queued), as ARCH §4.6 says.

#### 3.6.4 Node delivery off the event loop (W9)

- `OffLoopAlertSink(inner_webhook, *, max_pending=ALERT_OUTBOX_MAX, close_deadline_s=10.0)`, built by `resolve_node_alert_sink()`.
  - The local log branch stays inline.
  - For a CRITICAL, the calling thread writes the outbox entry (one small local file, no network, no fsync) and then submits to a dedicated single-worker `ThreadPoolExecutor` that touches no exec-store state. `emit` returns after the submit.
  - When `pending ≥ max_pending` nothing is submitted; the record `outbox_overflow, delivered=false` is written and the outbox entry already exists for redelivery.
  - Each attempt is bounded by `ALERT_DELIVERY_TIMEOUT_S`; `close()` drains within `close_deadline_s`, then leaves the rest in the outbox.
- **Wiring:** AUT-5a swaps the four node sites (`app/trade.py:474,533,1148`, `runtime/node_config.py:475`) to `resolve_node_alert_sink()`. Oneshots keep the synchronous sink.

#### 3.6.5 Redelivery, G26 fix, egress, sandboxing

- `breezy-autonomy-alert-redeliver`: every 5 min, own lock, oldest first, ≤ 20 per run, entries ≥ 40 s old; 2xx ⇒ rename into `delivered/`; > 24 h ⇒ `abandoned` record and #23 FAIL.
- **G26:** `check_alerts_cli.check_alerts` uses `deliver_with_proof(attempt_kind="check")` and exits `EXIT_DELIVERY_FAILED` iff not delivered.
- **Egress unchanged:** the only URL source is `BREEZY_ALERT_WEBHOOK_URL` (G27); `test_autonomy_alert_egress_not_widened` and the AST scan pin it.
- **Sandboxed units:** every unit that loads `alerts.env` and declares `ProtectHome=` or `ProtectSystem=strict` also declares `ReadWritePaths=%h/.local/share/breezy/evidence/alerts` (pinned by a test).

### 3.7 Canary and off-host absence (W13, G13, G14)

- **`breezy-autonomy-canary`** (oneshot, own lock, `MemoryMax=128M`, `TimeoutStartSec=60`), `OnCalendar=*-*-* *:45:00 UTC` plus `*-*-* 16:30:00 UTC`, `Persistent=false`.
  - **Slots:** 15:45Z (primary, ahead of the receiver's 16:15Z absence check) and 16:30Z always send `AlertPayload(severity="INFO", event="autonomy_canary", site="global", detail="canary_ok")` via `deliver_with_proof(attempt_kind="canary")`.
  - **Hourly retry gate (G13):** every other :45 run sends iff (a) the newest canary attempt failed and no canary `delivered=true` record exists since it, **or (b) today's or yesterday's record directory is absent or unreadable** (the gate fails toward sending; it never skips on missing evidence). Otherwise `AUTONOMY_CANARY skipped=not_due`, exit 0. Period = `CANARY_RETRY_PERIOD_MIN` 60 (ceiling ≤ 60).
  - Prints `AUTONOMY_CANARY delivered=<0|1> status_class=<c> slot=<15:45|16:30|retry>`, exits 0 either way; a failure queues CRITICAL `autonomy_canary_undelivered` and #23 reports it.
- **Veto rule (#5, ARCH Rev 6 C5):** only canary or CRITICAL `delivered=true`, `drill=false` records reset the 26 h clock.
- **Receiver absence rule (INFERRED; WP2 verify-first STOP):** Path A configures it receiver-side; Path B adds one host-pinned `BREEZY_ALERT_HEARTBEAT_URL` read only by the canary CLI, re-pinning the egress tests in the same reviewed commit.
- **Suppression drill and its veto arithmetic (G14, corrected from r2):**
  - `--suppress-drill` is honoured only on dates in the literal `CANARY_SUPPRESSION_DRILL_DATES`, only for the 15:45Z slot, and **only if the previous day's 16:30Z canary was delivered** (else it journals `drill_skipped precondition` and sends normally). It records `attempt_kind=canary, delivered=false, status_class=not_configured, drill=true` and sends nothing. The 16:30Z slot runs normally.
  - **Arithmetic.** The veto lands at `last_delivered_canary_or_critical + 26 h`. If the 16:30Z slot on drill day D delivers, the clock resets and the drill costs **zero trading minutes**. If D's 16:30Z slot and every hourly retry also fail (an unrelated broken alert path), the newest delivered record is D−1 16:30Z and the veto lands at **D 18:30Z**; had D−1's 16:30Z also failed, it would be D−1 15:45Z + 26 h = **D 17:45Z**. Both are **inside D's trading window** `[17:10Z, 01:00Z)`. r2's "≥ 15:45Z the next day" understated this.
  - That veto is not a cost of the drill: it fires only after 26 h with no delivered canary or CRITICAL, which is the fail-closed outcome the veto exists for. The precondition guarantees the drill never shortens the clock below D 18:30Z.
  - Evidence: the receiver's absence-page timestamp (a text attestation and a C4 `HEALTH` input hash) and no 15:45Z `delivered=true` canary that day.

### 3.8 The six failing units (ARCH §10) and wrapper exits

`systemctl --user list-units --failed` at about 04:15Z (r2, re-verified for the ARCH list):

| Unit | Fact | Root cause | Fix |
|---|---|---|---|
| `breezy-portfolio-roi.service` | exit 1, `PORTFOLIO ROI SKIPPED -- no score-live-trials success marker` (`portfolio-roi-run.sh:93-98`) | `score-live-trials` SKIPs FQ by design (`score-live-trials-run.sh:177-179`) and writes no marker | sibling skip marker `<success-marker>.skipped` (`composition_kind_has_no_scorer`); portfolio-roi prints `PORTFOLIO ROI NO_INPUT -- upstream skipped: <reason>`, exit 0; a missing marker stays exit 1 (WP3) |
| `breezy-discovery-pull.service` | `Result=timeout`; CPU 13.86 s / 1800 s = 0.008; `MemoryPeak` 169.6 MB; `MemorySwapPeak` 4.30 GB; `MemoryHigh=128M`/`MemoryMax=256M` | **Working set ≈ 4.47 GB (RSS + swap) > 1 GB (G12).** Code cause: the first poll reads all 63 node logs (1.7 GB, largest 1.16 GB) whole and keeps every record (`discovery_venue_pull.py:146-197`). L-49 signature, L-53 largest-item rule. | **Redesign, never raise the ceiling (WP3b, §3.8.1)** |
| `breezy-parity-mem-1d`, `breezy-parity-mem-7d` (transient) | exit 1 = parity mismatch (`nbp_shadow_parity.py:946`) | agent benchmarks; real signal | disposition file; one-time `reset-failed` at WP3 activation; #16 tracks the signal |
| `run-p814078-i21773018.service` (transient) | exit 2, `INVALIDARGUMENT` | agent ad-hoc run | same |
| `breezy-replay-backfill-0929.service` (transient) | exit 1 after 2 h 08 m, 10G | one-time backfill, superseded | same |

Wrapper exits that would fail as expected behaviour (RED cases for `test_every_wrapper_skip_path_exits_success`): `asos-refresh-run.sh` `SKIPPED-INFRA ... exit 75` (`:26,31,32`) with no `SuccessExitStatus=75`; the `replay-daily-run.sh` exit-75 disposition (r2). Each becomes exit 0 with its SKIPPED line, or the unit declares `SuccessExitStatus=75` with a test. `jetbrains-remote-dev.service` and `pressure-*` are foreign (§3.9).

#### 3.8.1 Discovery-pull redesign (G12)

1. **Verify-first (L-49 amendment, L-53):** measure the current job's working set as `MemoryPeak + MemorySwapPeak` of the 10-02 run (4.47 GB, already measured) and the largest single work item (`du` of today's node log). Working set > 1 GB ⇒ redesign branch (taken).
2. **Scope the read to today's spawn:** glob only node logs whose filename stamp is ≥ `_today_window_ns` start minus one launch; seed any older file's cursor at its current size (it is never read). The pull needs only today's initial discovery summary (`find_initial_trigger(since_ns)`).
3. **Stream, do not slurp:** replace `fh.read()` with bounded 1 MiB chunk reads split on newlines, and keep only records whose component ends with `DataClient-POLYMARKET_US` (the only consumer filter, `discovery_venue_pull.py:211`). The trigger-file replay `_replay_node_active_slugs` re-reads that file whole through `iter_node_log_records` (`discovery_set_equality.py:149-164`, `read_text`); that function is changed to iterate lines from the open file, same signature and return type, so the offline analysis keeps one parser (the module's own rule).
4. **Atomic outputs:** `<day>.json` and `<day>_pages.json` via `mkstemp` + `os.replace`.
5. **Size from the new working set:** re-measure ΔRSS over a post-import baseline in a fresh child (`ru_maxrss`) plus `MemorySwapPeak` of one capped run; set `MemoryHigh` = 1.5× and `MemoryMax` = 2× that working set. If the redesigned working set still exceeds 1 GB, chunk further; never raise the ceiling past 512M.
6. `TimeoutStartSec=900`; timer 16:52Z → **17:12Z** (out of `[16:30Z, 17:10Z)`); self-heal member once green.

### 3.9 Unit health: sources, ordering, scope, ownership, timers, "unexplained"

- **Failure source of truth: the journal.** Each pass reads `journalctl --user -o json --after-cursor=<cursor> MESSAGE_ID=d9b373ed55a64feb8242e02dbe79a49c` (argv list) and takes `USER_UNIT`, `USER_INVOCATION_ID`, `UNIT_RESULT`, `__REALTIME_TIMESTAMP` and `__CURSOR`.
- **Result map (G5):** `UNIT_RESULT_CLASS = {"exit-code": EXIT_CODE, "signal": SIGNAL, "core-dump": SIGNAL, "watchdog": SIGNAL, "timeout": TIMEOUT (then the §3.5 memory classifier), "oom-kill": OOM, "start-limit-hit": UNHEALABLE, "resources": UNHEALABLE}`; any other value is `UNHEALABLE` plus a WARN naming it. Fixtures are built from the four results measured since 09-28 (exit-code from `breezy-portfolio-roi`, signal from `breezy-exit-window-study` 09-28, oom-kill from `breezy-parity-fq` 10-01, timeout from `breezy-discovery-pull` 10-02), with ids replaced.
- **Commit order (G5).** For each entry, in journal order:
  1. **Classification record** `evidence/unit_health/<YYYY-MM-DD>/<unit>__<USER_INVOCATION_ID>__class.json`, created `O_CREAT|O_EXCL` (0444). If it exists, it is reused: dedupe is on `USER_INVOCATION_ID`, never on time.
  2. **Action**, unless `<unit>__<USER_INVOCATION_ID>__action.json` already exists: SELF_HEAL through §3.5 (which itself refuses a second restart for the same invocation), or ALERT through §3.6.
  3. **Action record** `…__action.json` (`O_CREAT|O_EXCL`) citing the selfheal record or the delivery record.
  4. Only after every entry of the batch has both records: rewrite `evidence/unit_health/seen/<unit>.json` (one file per unit, single writer under the health lock), then the cursor `evidence/unit_health/cursor.json` (`os.replace`), **cursor last**.
  - A crash anywhere before step 4 replays the same entries next pass with no double count, no double alert, no double restart. A crash after a restart but before its action record is caught by the selfheal record's `invocation_id`.
  - A missing cursor (first run or journal rotation) falls back to `--since=<last rollup day start>` and records `cursor_reset=true`.
- **Errors are UNKNOWN.** A non-zero exit, timeout or `Failed to connect to bus` from `systemctl` or `journalctl` makes the pass `UNKNOWN`: `passes_unknown` and `passes_unknown_streak` increment, the cursor is not advanced, and the pass never reports zero failures.
- **Scope and ownership (G13).**
  - In scope: `^breezy-[a-z0-9@._-]+\.service$`, plus any `run-*.service` whose `Description` or `ExecStart` contains the **repo path prefix `/home/jon/breezy/`** (this covers the shared interpreter `/home/jon/breezy/.venv/`) or the path of any worktree listed by `git -C /home/jon/breezy worktree list --porcelain` (read-only).
  - Every pass lists **all** failed `run-*.service` units, not only regex matches.
  - Foreign units (e.g. `jetbrains-remote-dev`, `pressure-*`, other projects' transients) are recorded as `foreign_failed` and never enter `unexplained_failed_units`; `FOREIGN_UNIT_PREFIXES` is literal.
  - Breezy-owned transients (`Transient=yes`) classify `TRANSIENT_ADHOC`.
- **Timer liveness #28 (G6).**
  - `TIMER_MAX_INTERVAL_S` has one key per `deploy/systemd/*.timer` file; a **template** key (`breezy-family-tally@.timer`) is expanded each pass to its enabled instances from `systemctl --user list-units --all --type=timer --plain 'breezy-family-tally@*'` (today `@pm_us_crh_v2`, `@pm_us_crh_v4`). `TIMER_RETIRED_BY_RULING = {"breezy-live-tally.timer": "RULING_R5_prereg_v1_tally_2026-09-24"}`.
  - `test_timer_interval_table_covers_every_deployed_timer` asserts `set(deploy timers) == keys(TIMER_MAX_INTERVAL_S) ∪ keys(TIMER_RETIRED_BY_RULING)`, disjoint, and that each retired file starts with a `# RETIRED` header naming an existing ruling file under `docs/evidence/`.
  - Each pass reads, for every key (and expanded instance), `UnitFileState`, `ActiveState`, `ActiveEnterTimestamp`, `TimersCalendar`, `TimersMonotonic`, `LastTriggerUSec`, `NextElapseUSecRealtime`, `NextElapseUSecMonotonic`. FAIL if: not `enabled`; not `active`; no future next elapse (the **monotonic** field for a timer with a non-empty `TimersMonotonic`, e.g. `OnUnitActiveSec`; the realtime field otherwise; today every deploy timer is calendar-only); `LastTriggerUSec` empty or 0 once `ActiveEnterTimestamp + interval + 900 s` has passed (grace); `LastTriggerUSec` older than `interval + 900 s`; a template with zero enabled instances; a retired timer that is loaded and enabled.
- **Classes:** `TIMEOUT`, `MEMORY_CEILING_SUSPECT`, `OOM`, `NOFILE_EXHAUSTED`, `EXIT_CODE`, `SIGNAL`, `UNHEALABLE`, `TRANSIENT_ADHOC`, `EXPECTED_FAILURE_SUSPECT`, `STALLED_ACTIVATING`.
- **Daily rollup** `evidence/unit_health/day_<YYYY-MM-DD>.json`, by the first pass after 00:00Z: `unexplained_failed_units` (count and names), `foreign_failed`, `passes_completed`, `passes_unknown`, `max_passes_unknown_streak`, `produced_at_ns`, `cursor_reset`.
- **Explained** means each failed `(unit, USER_INVOCATION_ID)` that day has a classification record and an action record with proof (restart followed by `Result=success`, or an ALERT `delivered=true`). `TRANSIENT_ADHOC` is explained by its classification plus one delivered WARN. `EXPECTED_FAILURE_SUSPECT` (same `(Result, ExecMainStatus)` on two distinct invocations on consecutive days) is never explained.

### 3.10 Slot table and runtime bounds

Rules (unchanged): **R-a** every `Type=oneshot` unit declares `TimeoutStartSec` ≤ its slot (G32); **R-b** a non-daemon `simple`/`exec` unit declares `RuntimeMaxSec`; **R-c** the daemon allowlist is exempt; **R-d** no study window `[start, start + W + TimeoutStartSec]` intersects `[16:30Z, 17:10Z)`, data-path units exempt. Pinned by `test_every_unit_has_an_effective_runtime_bound` and `test_no_study_window_intersects_stop_launch`.

| Unit | Type | Schedule (UTC) | Lock / W | Bound | MemoryMax | Notes |
|---|---|---|---|---|---|---|
| `breezy-autonomy-producer-daily` | oneshot | 05:30, 13:00 | studies, CLI-acquired, 300 s deadline | `TimeoutStartSec=1500` | 3G | lock timeout ⇒ SKIPPED, exit 0 (G11); `OnFailure=breezy-study-failed@%n`; `LimitNOFILE=524288` |
| `breezy-autonomy-producer-intraday` | oneshot | `*:00/5` | own, `-n` | 240 s | 512M | `ProcSubset=all`, `ProtectProc=default` (G14); deferral-exempt |
| `breezy-autonomy-health` | oneshot | `*:01/10` | own, `-n` | 120 s | 256M | only SELF_HEAL caller; heartbeat |
| `breezy-autonomy-alert-redeliver` | oneshot | `*:03/5` | own, `-n` | 120 s | 128M | min entry age 40 s |
| `breezy-autonomy-canary` | oneshot | `*:45` + 16:30 | own, `-n` | 60 s | 128M | slots plus retry gate |
| `breezy-autonomy-selfheal-probe` | oneshot | Mon 10:00 | none | 30 s | 64M | drill target |
| `breezy-discovery-pull` (changed) | oneshot | 17:12 | none | 900 s | 2× measured working set after WP3b, ≤ 512M | §3.8.1 |

Own-lock AUT-6 units: 512M + 256M + 128M + 128M + 64M = 1.09G, inside ARCH's 4G together with AUT-5's units; #31 checks the effective sum daily.

### 3.11 Monitor the monitors and the dead-man (ARCH Rev 6 P6-5)

The dead-man is AUT-5's (`breezy-autonomy-deadman`, every 30 min). AUT-6 builds no second dead-man and supplies:

1. **The health heartbeat** `evidence/unit_health/heartbeat.json` (0444, `os.replace`, single writer under the health lock), rewritten by every pass including an UNKNOWN pass: `{ts_ns, invocation_id, pass_result, passes_unknown_streak}`.
   - **Requirement handed to AUT-5 (G1):** the dead-man raises CRITICAL (through `deliver_with_proof`) when the heartbeat is older than `HEALTH_HEARTBEAT_STALE_S = 1800` **or** `passes_unknown_streak ≥ 3`. AUT-5 owns `test_deadman_pages_on_health_heartbeat_stale_or_unknown_streak`; AUT-6 supplies the heartbeat fixture.
2. **#29 `aut6.health_monitor_stale`** in the intraday producer: the same two conditions, as a C4 verdict and CRITICAL. A health unit that runs but cannot read systemd therefore fails two independent watchers within 30 min.
3. **#26 `aut6.producer_stale`** in the health unit: intraday heartbeat age, `fold_ok=false` (G2), and in-window absence of a valid intraday verdict.
4. **#27 daily-verdict absence**, with skip reasons (G11).
5. **Unit-health coverage** of `breezy-autonomy-deadman.service` and every AUT-6 unit (#22, #28).
6. `deliver_with_proof` for the dead-man's CRITICAL. Each watcher (health, intraday producer, dead-man) is watched by at least one other; the off-host canary covers whole-host death.

### 3.12 Contract use (C1–C6)

- **C1:** consumes `DetectorEvent`, `DecisionRecord` (`TrySubmit`, `ask_px`, `depth_ref`, `eval_ns`, `p_hat`), `OrderLink` (`client_order_id`, `time_in_force`, `side`, `instrument_id`), `LifecycleEvent` (`FILLED`, `px`, `ts_ns`), the Depth10 payload store, `source`, `drill`. Canary records are excluded everywhere. Provides the #4 and #5 observation objects.
- **C2:** consumes `admissible`, `excluded_reason`, `slippage`, `fill_px`, `entry_ask`, `p_at_decision`, `settled_outcome`, `drill` (#13, #14). #15 no longer waits for C2.
- **C3:** the champion artefact for #12.
- **C4:** produces `DRIFT`/`HEALTH` for every VERDICT id from three pinned producers, including `DRILL_INJECT` and `DRILL_INJECT_HALT`.
- **C5:** consumes the fold, bound sha, drill marker and halt-relevant state. Writes nothing in C5 under Rev 6; the INTEGRITY `demand/v1` writer exists only if C-12 is ratified (WP5b).
- **C6:** provides `DriftDetectors` for `forecast_quantile_ladder` and the required-class gate test.

### 3.13 Halted-by-design is not a failure

- Before evaluating a `halt_exempt=True` detector (#6, #7, #14, #18, #20) the producer reads the C5 fold and the champion's exec-store family halt (`read_family_halt_rows_readonly` + `decode_family_halt_state`, `trial_day_latch.py:333,354`, `mode=ro`).
- No CHAMPION on the venue ⇒ `PASS reason=family_not_champion`. Champion HALTED in the fold or exec-store halted ⇒ `PASS reason=family_halted`, `metrics.halt_detail` from the closed enum. Unreadable ⇒ UNKNOWN, never PASS.
- **#30 is deliberately not exempt (G7):** a halt that nobody clears for 24 h is itself the finding (a RECOVERABLE halt with no RESUME, or an INTEGRITY freeze awaiting build-side incident handling). `halted_since_ns` is the `ts_ns` of the fold row that made the family HALTED; for an exec-store halt not yet mirrored, the halt row's own timestamp if `decode_family_halt_state` exposes one (WP6 verify-first), else `metrics.halted_first_observed_ns` carried from the previous #30 verdict.
- Safe because a halted family cannot send (`family_halt_submit_veto`), a dead node while halted is still caught by #22, B1 and AUT-1's capture detectors, and the halt was alerted by its writer.
- Clears on the first verified fold naming the family CHAMPION with no exec-store halt (W5).

---

## 4. Work packages

**Gate commands, every WP, in the WP's own worktree:**
1. `PYTHONPATH=<tree>/src scripts/ci/run_tests_no_egress.sh` with the exact interpreter `/home/jon/breezy/.venv/bin/python`; never `uv` or `pip` (L-51). Unit-launched gates take `-p LimitNOFILE=524288`, basetemp on `~/.cache`.
2. `cd <tree> && lint-imports`, demanding "N kept, 0 broken".
3. The mypy ratchet (`tests/unit/test_mypy_ratchet.py`).
4. Read the gate EXIT before any push; the full gate after **every** merge (L-43).

Every injectable seam gets one production-default test (L-55). Every operator-visible line is asserted, then checked in the journal after the first live run (L-52). **Activation:** immediately on merge unless stated. A unit-file change means `daemon-reload` plus `enable --now <timer>` by the implementer; node code takes effect at the next 16:50Z LAUNCH. New or renamed tests in r3 are marked **(r3, G-id)**.

### AUT-6.WP1 — Delivery proof, records, outbox. Wave 1, first

- **Files:** `src/breezy/runtime/alert_delivery.py`; `runtime/health.py` (the `resolve_alert_sink` construction only); `runtime/check_alerts_cli.py`; `runtime/alert_redeliver_cli.py`; `deploy/systemd/breezy-autonomy-alert-redeliver.{service,timer}`; `deploy/systemd/breezy-discovery-pull.service` (`ReadWritePaths`); `pyproject.toml`; `tests/unit/test_alerts_env_deploy.py` (additive list entry, L-12).
- **RED tests first:**
  - `tests/unit/test_alert_delivery.py::test_check_alerts_reports_not_delivered_through_the_production_tee` (G26)
  - `::test_deliver_with_proof_reports_non_2xx_through_tee`
  - `::test_deliver_with_proof_treats_3xx_as_not_delivered`
  - `::test_deliver_with_proof_reports_transport_failure_without_the_url`
  - `::test_deliver_with_proof_keeps_the_local_log_line`
  - `::test_record_path_matches_arch_and_one_writer_per_file` **(r3, G4)**: `evidence/alerts/<date>/<ts_ns>_<writer>_<d|f>.json`, `O_EXCL`, collision bumps ns
  - `::test_record_carries_severity_attempt_kind_and_drill` **(r3, G4/C-14)**
  - `::test_record_write_failure_never_blocks_delivery_and_counts_journal_write_failures` **(r3, G10)**
  - `::test_critical_outbox_entry_written_before_http_attempt` **(r3, G8)**: a receiver that never answers plus a simulated kill after submit leaves the entry pending
  - `::test_outbox_entry_renamed_to_delivered_on_2xx_never_unlinked` **(r3, G8)**
  - `::test_resolve_alert_sink_webhook_branch_records_and_queues_criticals`
  - `::test_aut6_warn_alert_is_queued`
  - `::test_legacy_noncritical_failure_is_recorded_not_queued`
  - `::test_outbox_write_failure_is_logged_counted_and_recorded`
  - `::test_tee_containment_unchanged_with_journaling_branch`
  - `tests/unit/test_alert_redeliver.py::test_outbox_drains_on_2xx_and_abandons_after_24h`
  - `::test_redeliver_skips_entries_younger_than_min_age` **(r3, G8)**
  - `::test_redeliver_rename_enoent_is_already_delivered` **(r3, G8)**
  - `::test_sigkill_mid_send_is_redelivered_at_least_once` **(r3, G8)**: subprocess killed with SIGKILL during a stalled POST; the next redeliver run delivers it
  - `::test_write_on_change_alert_resent_after_failed_delivery`
  - `::test_redeliver_runs_the_production_default_once`
  - `tests/unit/test_systemd_unit_contracts.py::test_every_alerting_sandboxed_unit_can_write_the_delivery_journal`
  - `tests/unit/test_autonomy_envelope.py::test_autonomy_alert_egress_not_widened`
- **GREEN:** all pass; `test_alert_egress.py`, `test_runtime_health.py`, `test_alert_webhook_delivery.py` pass **unedited**.
- **Activation:** enable the redeliver timer, run `breezy-check-alerts` once, confirm a `*_check_d.json` record.

### AUT-6.WP1b — Node outbox worker (W9). Wave 1, after WP1

- **Files:** `alert_delivery.py` (`OffLoopAlertSink`, `resolve_node_alert_sink`). AUT-5a swaps the four node sites.
- **RED tests first:** `tests/unit/test_alert_delivery_offloop.py::test_offloop_emit_returns_before_webhook_completes` (receiver stalls 4 s, `emit` < 50 ms including the outbox write); `::test_offloop_local_log_line_is_synchronous`; `::test_offloop_overflow_records_outbox_overflow_and_entry_exists` **(r3, G4/G8)**; `::test_offloop_critical_outbox_written_on_calling_thread_before_submit` **(r3, G8)**; `::test_offloop_close_drains_then_leaves_rest_in_outbox`; `::test_offloop_worker_never_raises_into_caller`; `::test_offloop_worker_touches_no_exec_store`; `::test_resolve_node_alert_sink_runs_production_default_once`.
- **Activation:** first LAUNCH after AUT-5a's swap; node log `breezy alert` lines present; `*_node_*.json` records exist.

### AUT-6.WP2 — Canary, absence rule, `alerts_undeliverable`. Wave 1, after WP1

- **Verify-first STOP:** receiver absence-rule support (yes/no plus evidence class) → Path A or B, written down before code.
- **RED tests first:**
  - `tests/unit/test_autonomy_canary.py::test_canary_delivers_through_proof_and_prints_status`; `::test_canary_slots_are_1545_and_1630`; `::test_canary_hourly_retry_only_after_failure`; `::test_canary_retry_gate_sends_when_records_unreadable` **(r3, G13)**; `::test_canary_failure_queues_critical_and_exits_0`; `::test_suppress_drill_only_on_preregistered_dates_and_only_1545_slot`; `::test_suppress_drill_requires_previous_1630_delivered` **(r3, G14)**; `::test_canary_runs_the_production_sink_default_once`
  - `tests/unit/test_autonomy_node_detectors.py::test_alerts_undeliverable_counts_canary_or_critical_only` **(r3, G4; replaces r2's any-kind test)**; `::test_alerts_undeliverable_ignores_warn_and_info_records` **(r3)**; `::test_alerts_undeliverable_ignores_drill_rows`; `::test_alerts_undeliverable_reads_today_and_yesterday`; `::test_one_failed_canary_does_not_veto_next_window`; `::test_veto_arithmetic_worst_case_lands_1830z_inside_window` **(r3, G14)**: last delivered D−1 16:30Z, all later attempts fail ⇒ veto at D 18:30Z; `::test_alerts_undeliverable_unarmed_before_first_delivery`; `::test_alerts_undeliverable_clears_on_next_2xx`; `::test_node_local_unknown_vetoes_after_watch_tick_stale`; `::test_detector_never_raises` (L-16)
- **Activation:** enable the canary timer; the first 15:45Z and 16:30Z runs show `AUTONOMY_CANARY delivered=1`.

### AUT-6.WP3 — Unit health, failing units, timers, slot rules, memory budget. Wave 1, parallel with WP2

- **Files:** `runtime/unit_health.py`, `runtime/monitor_watch.py`, `runtime/autonomy_health_cli.py`; `deploy/systemd/breezy-autonomy-health.{service,timer}`; `score-live-trials-run.sh`, `portfolio-roi-run.sh`, `asos-refresh-run.sh` (or its unit's `SuccessExitStatus`), the `replay-daily-run.sh` exit-75 disposition; `docs/evidence/unit_health/DISPOSITION_failed_units_2026-10-03.md`; `tests/unit/test_systemd_unit_contracts.py`; `pins.py` (`"aut6.health"`).
- **RED tests first:**
  - `tests/unit/test_unit_health.py::test_classifies_low_cpu_wall_with_swap_peak_as_memory_ceiling_suspect`; `::test_low_cpu_wall_without_memory_signal_is_timeout_not_memory`; `::test_memory_peak_near_memory_high_counts_as_memory_signal`
  - `::test_unit_result_map_exit_code_fixture` **(r3, G5)**; `::test_unit_result_map_signal_fixture` **(r3, G5)**; `::test_unit_result_map_oom_kill_fixture` **(r3)**; `::test_unknown_unit_result_is_unhealable_and_warns` **(r3)**
  - `::test_fail_then_succeed_between_passes_is_counted_via_journal_cursor`; `::test_cursor_reset_falls_back_to_day_start_and_is_journaled`
  - `::test_cursor_and_seen_committed_only_after_class_and_action_records` **(r3, G5)**
  - `::test_crash_between_records_and_cursor_commit_replays_without_double_action` **(r3, G5)**: faults injected after the class record, after the restart before the action record, and after the action record before the cursor; each replay yields one class record, one action record, at most one restart
  - `::test_dedupe_on_user_invocation_id_not_time` **(r3, G5)**
  - `::test_systemctl_error_is_unknown_never_zero_failures`; `::test_bus_error_increments_passes_unknown_and_streak` **(r3, G1)**
  - `::test_run_sweep_owns_transient_by_repo_path_or_worktree_path` **(r3, G13)**; `::test_foreign_transient_excluded_from_unexplained`
  - `::test_classifies_portfolio_roi_repeat_exit1_on_distinct_invocations_as_expected_failure_suspect`; `::test_oneshot_activating_is_not_failed_and_stall_warns_at_80pct`; `::test_expected_failure_suspect_is_never_explained`; `::test_explained_requires_classification_and_proven_action`; `::test_rollup_counts_unexplained_passes_and_max_unknown_streak`; `::test_observe_units_runs_the_production_reader_once`
  - `::test_unit_config_drift_detects_uncommitted_dropin_and_escalates_after_deadline`
  - `::test_memory_budget_uses_effective_memorymax_including_dropins` **(r3, P6-10)**; `::test_memory_budget_fails_on_14g_dropin_arithmetic` **(r3)**
  - `tests/unit/test_monitor_watch.py::test_timer_interval_table_covers_every_deployed_timer` **(r3, G6: template plus retired)**; `::test_template_timer_expanded_to_enabled_instances` **(r3, G6)**; `::test_template_with_zero_enabled_instances_fails` **(r3, G6)**; `::test_timer_not_enabled_is_fail` **(r3, G6)**; `::test_last_trigger_zero_after_grace_is_fail` **(r3, G6)**; `::test_monotonic_timer_uses_next_elapse_monotonic` **(r3, G6)**; `::test_retired_timer_enabled_is_fail` **(r3, G6)**; `::test_timer_liveness_fails_on_stale_last_trigger`
  - `::test_producer_stale_on_old_heartbeat`; `::test_producer_stale_fails_on_fold_not_ok` **(r3, G2)**; `::test_missing_intraday_verdict_in_window_alerts`; `::test_daily_verdict_absent_after_30h`; `::test_daily_verdict_absent_reports_lock_timeout_skips` **(r3, G11)**; `::test_health_heartbeat_written_every_pass_including_unknown_with_streak` **(r3, G1)**
  - `::test_alert_delivery_fails_on_journal_write_failures_counter` **(r3, G10)**; `::test_alert_delivery_fails_on_unwritable_or_full_record_root` **(r3, G10)**
  - `tests/unit/test_portfolio_roi_run_no_input.py::test_skip_marker_gives_no_input_exit_0`; `::test_absent_markers_still_exit_1`
  - `tests/unit/test_score_live_trials_skip_marker.py::test_fq_skip_writes_skip_marker_with_closed_reason`
  - `tests/unit/test_systemd_unit_contracts.py::test_every_unit_has_an_effective_runtime_bound`; `::test_no_study_window_intersects_stop_launch` (RED today on 16:52Z); `::test_every_wrapper_skip_path_exits_success` (RED today on `asos-refresh-run.sh` exit 75)
- **Activation:** install and enable the health timer, `daemon-reload`; one-time `reset-failed` of the four transient names, journaled; 17:40Z portfolio-roi prints `NO_INPUT`, exit 0; the first `day_<date>.json` shows `unexplained_failed_units=0` and `foreign_failed` lists `jetbrains-remote-dev.service`.

### AUT-6.WP3b — Discovery-pull bounded-memory redesign (G12). Wave 1, parallel with WP3

- **Files:** `scripts/analysis/discovery_venue_pull.py`; `scripts/analysis/discovery_set_equality.py` (`iter_node_log_records` reads line by line; signature and return type unchanged); `deploy/systemd/breezy-discovery-pull.{service,timer}`; `docs/evidence/aut6/WP3b_discovery_pull_memory_<date>.md`.
- **Verify-first STOP:** record the 10-02 working set (4.47 GB) and the largest node log; after the change, measure ΔRSS in a fresh child plus one capped run's `MemorySwapPeak`; the redesign is accepted only if the working set ≤ 1 GB (target ≤ 256 MiB).
- **RED tests first:** `tests/unit/test_discovery_venue_pull_memory.py::test_first_poll_skips_logs_older_than_today_window` ; `::test_poll_reads_in_bounded_chunks_not_whole_file` (a 64 MiB synthetic log; peak ΔRSS < 32 MiB in a child); `::test_only_polymarket_data_client_records_kept`; `::test_outputs_written_atomically`; `::test_initial_trigger_found_unchanged_on_replayed_10_02_fixture` (behaviour identical on a trimmed real fixture); `tests/unit/test_systemd_unit_contracts.py::test_discovery_pull_ceiling_matches_measured_working_set`.
- **GREEN:** existing discovery tests pass unedited; ceilings set from the measurement, ≤ 512M.
- **Activation:** `daemon-reload`; the 17:12Z run prints its summary, `Result=success`, `MemorySwapPeak=0`.

### AUT-6.WP4 — Self-heal executor and drill probe. Wave 1, after WP3

- **Verify-first STOP:** for `breezy-asos-refresh`, show from code that a repeat fetch replaces by key; if not shown, drop it from the tuple in this WP.
- **RED tests first:** `tests/unit/test_self_heal.py::test_restart_refuses_non_allowlisted_unit`; `::test_restart_uses_argv_list_no_shell`; `::test_restart_call_site_is_unique_and_called_only_from_health_cli` **(r3, P6-7)**; `::test_per_unit_daily_cap`; `::test_restart_cap_survives_process_restart`; `::test_restart_row_written_before_run_with_invocation_id` **(r3, G5)**; `::test_no_second_restart_for_same_invocation` **(r3, G5)**; `::test_unreadable_selfheal_dir_refuses_restart`; `::test_memory_ceiling_and_oom_never_restarted`; `::test_restart_deferred_when_it_would_intersect_stop_launch`; `::test_intraday_producer_exempt_from_deferral`; `::test_verify_waits_out_activating_then_requires_success`; `::test_alert_only_mode_without_policy_map`; `::test_every_member_has_an_idempotency_evidence_row` **(r3, G14)**: a literal table keyed by the tuple; `::test_restart_runs_the_production_default_once`; `tests/unit/test_self_heal_probe.py::test_probe_arms_fails_then_heals_once_per_week`; plus the extended ARCH `test_self_heal_unit_allowlist_is_literal_and_excludes_trade`.
- **Activation:** enable the probe timer; `ALERT_ONLY` until the ruling maps #21.

### AUT-6.WP5 — Catalogue, C6 plug-ins, `permit_lapsed`, UNKNOWN rules. Wave 1, after the ARCH-0 stubs

- **Files:** `detector_catalog.py`; `autonomy_node_detectors.py` (`PermitLapsedDetector`); the FQ `drift_detectors` entries; `analysis/nbp_drift.py`; `scripts/analysis/nbp_learning_nightly.py` (import back).
- **H16 expected-skip rule (unchanged):** `test_policy_detector_map_covers_catalog_exactly` skips only with `AUT6_EXPECTED_SKIP:policy_map_pending_AUT-5b` while no `autonomy-policy/v1` block exists; `AUT6_EXPECTED_SKIPS: Final = ("policy_map_pending_AUT-5b",)`; `test_aut6_expected_skips_are_exact_and_bounded` self-expires when the ruling lands; gate runs with `-rs`.
- **RED tests first:** `tests/unit/test_detector_catalog.py::test_catalog_is_literal_only`; `::test_every_live_kind_covers_required_detector_classes`; `::test_node_local_ids_are_entry_veto_only`; `::test_policy_detector_map_covers_catalog_exactly`; `::test_aut6_expected_skips_are_exact_and_bounded`; `::test_every_action_class_has_at_least_one_detector`; `::test_every_detector_has_a_severity`; `::test_integrity_rows_have_halt_floor`; `::test_policy_unavailable_integrity_verdict_declares_halt_floor`; `::test_catalog_contains_drill_inject_and_drill_inject_halt` **(r3, G4)**; `::test_halt_live_proof_class_is_drill_only` **(r3, G4)**: #8h `drill`, #15 and #17 `gate_only`; `tests/unit/test_autonomy_node_detectors.py::test_permit_lapsed_vetoes_after_expiry_and_alerts_only_in_b1_window`; `::test_permit_none_is_agree_no_permit`; `::test_permit_lapsed_read_error_unknown_then_vetoes_after_180s`; `::test_permit_lapsed_reads_value_never_the_permit_object_authority`; `tests/unit/test_nbp_drift_move.py::test_nightly_behaviour_identical_after_move`; ARCH `test_family_plugin_exact_set` stays green.
- **Activation:** none on its own (AUT-5a wires the watch actor).

### AUT-6.WP5b — INTEGRITY floor writer. **Held until ARCH ratifies C-12** (technical reason: a second writer of a C5 file is a contract change)

- **Files:** `analysis/autonomy/integrity_floor.py`; one row in `test_autonomy_files_have_one_writer`.
- **RED tests first:** `tests/unit/test_integrity_floor.py::test_integrity_fail_writes_demand_file_in_c5_schema`; `::test_integrity_writer_never_refuses_on_count` **(r3, G9)**; `::test_demand_file_written_even_when_policy_unreadable`; `::test_integrity_demand_archived_by_rename_never_unlinked` **(r3, G4/W16)**; the engine half `test_engine_demand_writer_reserves_one_slot_for_integrity` goes to AUT-5 with C-12.
- **Activation:** on merge, after the ARCH revision that ratifies C-12. If C-12 is rejected, WP5b is closed as not built.

### AUT-6.WP6 — Intraday producer. Wave 1, after WP5 and AUT-5a's resolver stub and bootstrap rows

- **Verify-first STOP:** (1) recorder live-root max `ts_init` gap over 7 in-window periods → `TAPE_MTIME_MAX_S`; (2) which instrument ids carry Depth10 for NO legs (own rows or YES-bid complement); (3) ΔRSS of one `order_book_depth10` single-instrument query on the largest instrument-day, fresh child; (4) whether `decode_family_halt_state` exposes a halt timestamp; (5) `/proc/locks` visible from a unit with `ProcSubset=all`. Results in `docs/evidence/aut6/WP6_verify_first_<date>.md`.
- **RED tests first:**
  - `tests/unit/test_producer_intraday.py::test_node_liveness_requires_all_four_conjuncts`; `::test_node_liveness_all_good_positive_control`; `::test_node_liveness_flapping_conjunct_needs_two_consecutive_fails`; `::test_node_liveness_boot_grace_until_1705`; `::test_node_liveness_transition_1705_with_healthy_new_boot_passes`; `::test_relaunch_grace_and_relaunch_loop_void`; `::test_node_liveness_pass_family_halted`; `::test_node_liveness_pass_family_not_champion`; `::test_halt_state_unreadable_is_unknown_not_pass`; `::test_tape_source_is_recorder_live_root_not_ingest_output`; `::test_log_threshold_1500s`
  - `::test_proc_locks_unreadable_is_unknown_not_zero_holders` **(r3, G14)**; `tests/unit/test_systemd_unit_contracts.py::test_intraday_producer_unit_declares_procsubset_all` **(r3, G14)**
  - `::test_unreadable_fold_writes_critical_and_heartbeat_fold_ok_false` **(r3, G2)**; `::test_empty_fold_is_fold_not_ok` **(r3, G2)**; `::test_all_retired_fold_is_host_subject_fold_ok_true` **(r3, G2)**
  - `::test_health_monitor_stale_fails_on_age_1800s` **(r3, G1)**; `::test_health_monitor_stale_fails_on_unknown_streak_3_with_fresh_heartbeat` **(r3, G1)**
  - `::test_halted_too_long_after_24h_reports_halted_age_s` **(r3, G7)**; `::test_halted_too_long_repages_every_24h` **(r3, G7)**; `::test_halted_too_long_not_halt_exempt` **(r3, G7)**
  - `tests/unit/test_fill_integrity.py::test_legit_ask_drop_and_resting_fill_do_not_trip_integrity` **(r3, G3)**; `::test_fill_below_every_displayed_ask_between_decision_and_fill_fails` **(r3, G3)**; `::test_only_taker_ioc_entry_fills_judged` **(r3, G3)**; `::test_exit_and_canary_fills_excluded` **(r3, G3)**; `::test_no_buy_reported_as_sell_buy_short_normalised_via_leg_prices` **(r3, G3)**; `::test_undecidable_price_space_is_inconclusive_not_fail` **(r3, G3)**; `::test_missing_depth_is_pending_then_blind_after_6h` **(r3, G3/G9)**; `::test_same_timestamp_book_update_applied_before_quote` **(r3, L-25)**; `::test_no_leg_ask_from_yes_bid_complement` **(r3, G3)**; `::test_fill_integrity_fail_declares_halt_floor_integrity` **(r3)**; `::test_fill_integrity_runs_production_catalog_reader_once` **(r3, L-55)**
  - `::test_inconclusive_streak_writes_detector_blind_and_critical`; `::test_blind_liveness_detector_reports_fail_not_pass`; `::test_transient_veto_persistent_after_5400s`
  - `::test_drill_inject_fail_on_marker_pass_on_absent`; `::test_drill_inject_halt_fail_only_when_marker_names_it` **(r3, G4)**; `::test_drill_inject_halt_writes_no_exec_store_key` **(r3, G4)**
  - `::test_fee_probe_health_fails_without_running_line`; `::test_shape_drift_reads_exec_store_readonly`; `::test_subject_artefact_is_bound_sha_not_newest_row`; `::test_intraday_validity_is_8h_and_bounded`; `::test_intraday_refresh_keeps_attest_gap_free`; `::test_write_on_change_or_hourly_refresh_only`; `::test_policy_unavailable_writes_alert_with_assumption`; `::test_never_takes_studies_flock`; `::test_heartbeat_rewritten_every_run_with_fold_ok` **(r3, G2)**; `::test_producer_refuses_when_unpinned`; `::test_producer_runs_production_readers_once`; `::test_payload_hygiene`
  - plus the producer half of `test_demotion_latency_slo` and the schedule row for `test_attest_cadence_has_no_expiry_gap`.
- **Activation:** enable the timer **after AUT-5a's bootstrap rows exist** (an empty fold is `fold_ok=false` by design). The journal shows `PRODUCER_INTRADAY wrote=<n> skipped=<m>` every 5 min; the first pass at or after 17:05Z writes a `node_liveness` PASS.

### AUT-6.WP7 — Daily producer. Wave 2 (#13, #14 need C2 labels)

- **RED tests first:** `tests/unit/test_producer_daily.py::test_forecast_drift_reuses_moved_predicate`; `::test_persistent_escalation_2_of_3`; `::test_feature_drift_psi_and_underpowered`; `::test_calibration_live_excludes_canary_drill_voided_and_inadmissible`; `::test_fill_detectors_include_drill_fills` (#14, #20); `::test_calibration_live_underpowered_never_fails`; `::test_station_day_clustering`; `::test_fill_slippage_underpowered_below_n_min`; `::test_shadow_parity_judges_take_set_only`; `::test_decision_starvation_uses_all_refused_predicate`; `::test_decision_starvation_pass_family_halted`; `::test_retry_slot_1300_noop_when_produced_and_retries_missing`; `::test_daily_lock_timeout_prints_skipped_exits_0_and_writes_skip_record` **(r3, G11)**; `::test_daily_lock_acquired_by_cli_not_flock_wrapper` **(r3, G11)**; `::test_daily_unreadable_fold_writes_skip_record_and_critical` **(r3, G2)**; `::test_daily_ends_before_refit_slot`; `::test_producer_daily_runs_production_readers_once`.
- **Activation:** enable the timer; 05:30Z `PRODUCER_DAILY wrote=<n>`, 13:00Z `SKIPPED already_produced`.

### AUT-6.WP8 — CRH-semantics wrappers resolve the champion. Wave 2

Unchanged from r2: `score-live-trials-run.sh`, `replay-daily-run.sh`, `decision-funnel-digest-run.sh`, `family-tally-v2-run.sh` switch to `breezy-registry-champion --venue polymarket_us`; a resolver failure prints `SKIPPED -- registry_unavailable`, exit 0, caught by #22. RED: `::test_wrapper_keys_off_registry_champion_not_unit_env`, `::test_registry_unavailable_skips_exit_0` per wrapper.

### AUT-6.WP9 — Live-proof report. Wave 1, after WP3

- **RED tests first:** `tests/unit/test_aut6_live_proof_report.py::test_zero_fill_day_extends_window`; `::test_window_requires_5_real_fills_canary_and_drill_excluded`; `::test_each_action_class_needs_a_live_path_event`; `::test_halt_class_satisfied_by_drill_inject_halt_row_only` **(r3, G4)**; `::test_drill_events_tagged_and_counted_only_for_their_class`; `::test_window_starts_after_aut5b_ruling_date`; `::test_missing_or_stale_rollup_fails_the_day`; `::test_day_with_passes_unknown_over_threshold_fails`; `::test_day_with_unknown_streak_ge_3_needs_delivered_page` **(r3, G1)**; `::test_permit_lapsed_event_matched_to_expires_at_ns`.

---

## 5. Association

| Contract / interface | Direction | Exact item |
|---|---|---|
| C1 (AUT-1) | consume | `DetectorEvent`; `DecisionRecord.kind ∈ {TrySubmit, Take}`, `ask_px`, `depth_ref`, `eval_ns`, `p_hat`; `OrderLink.time_in_force`, `side`, `instrument_id`, `client_order_id`; `LifecycleEvent(FILLED)` `px`, `ts_ns`; Depth10 payload store; `source`, `drill`; `decisions/capture_<family_id>_<date>.jsonl` |
| C1 (AUT-1) | provide | #4 and #5 emit `DetectorEvent(AGREE/DISAGREE/UNKNOWN)` through AUT-1's writer |
| AUT-1 | consume | recorder and feed unit names plus an idempotency row each, for `SELF_HEAL_RESTARTABLE_UNITS`; AUT-1 never calls `restart_unit` |
| C2 (AUT-2) | consume | `admissible`, `excluded_reason`, `slippage`, `fill_px`, `entry_ask`, `p_at_decision`, `settled_outcome`, `role`, `drill` (#13, #14) |
| C2 (AUT-2) | boundary | AUT-6 owns portfolio-roi's exit semantics; AUT-2 owns the scorer (P6-9) |
| C4 (AUT-5) | provide | `DRIFT`/`HEALTH` for every VERDICT id from `aut6.intraday`, `aut6.daily`, `aut6.health`; `metrics.cause_class`; 8 h intraday validity, hourly refresh |
| ATTEST (AUT-5) | provide | the intraday schedule row and the §3.4.1 invariant |
| C5 (AUT-5) | consume | fold (subjects, bound sha, CHAMPION/HALTED, HALTED row `ts_ns`); drill marker incl. its `detector` field (`DRILL_INJECT` \| `DRILL_INJECT_HALT`); resolver CLI (WP8) |
| C5 (AUT-5) | provide, **only if C-12** | INTEGRITY `demand/v1` files, restrictive only; requires the engine to reserve one slot |
| Policy (AUT-5b) | consume | `detector_action_map` covering `CATALOG` exactly (VERDICT ids incl. #8, #8h, #29–#31, plus #11p, #12p); `n_min` for #13; horizons |
| Watch actor (AUT-5a) | provide | the NODE_LOCAL detector objects; AUT-5a swaps the four node sink sites to `resolve_node_alert_sink()` |
| Dead-man (AUT-5) | require | reads `evidence/unit_health/heartbeat.json`; CRITICAL past 1800 s **or** `passes_unknown_streak ≥ 3` (G1) |
| Engine (AUT-5) | require | intraday pass 150 s after the producer; restrictive-only; ignores `_host/`; maps `DRILL_INJECT_HALT → HALT` (DRILL) only under the drill clause |
| `pins.py` | provide | `PRODUCER_SOURCE_SHA256[...]` for the three producers; `SELF_HEAL_RESTARTABLE_UNITS` members |
| ING-2-AMEND2 (build-side) | require | drop-in removal by 2026-10-16 (#24, #31; §8 R-2) |
| ARCH Rev 7/8 | require (non-blocking for score 3) | C-12 (with the slot reservation), C-14, C-15, C-17 |
| Every area | provide | `deliver_with_proof`, outbox and redeliver as the ALERT executor library |
| AUT-7 | provide | `DRILL_INJECT` and `DRILL_INJECT_HALT` in the live producer path |

**Order:**
1. **Wave 1:** WP1 → (WP1b ∥ WP2 ∥ WP3 ∥ WP3b) → WP4; WP9 after WP3; WP5 after the ARCH-0 stubs; WP6 after WP5 and AUT-5a's resolver stub and bootstrap rows.
2. **Wave 2:** WP7, WP8.
3. **Held:** WP5b until ARCH ratifies C-12.
4. **Live proof:** DEMOTE and HALT need AUT-5b and AUT-7b (Wave 3).

{WP1b, WP2, WP3, WP3b, WP5} touch disjoint files.

---

## 6. Live-proof protocol

- **Artefact:** `~/.local/share/breezy/evidence/aut6/live_proof_<from>_<to>.json` (WP9), citing the rollups, delivery records, C1, the C4 ids, the C5 export and node-log lines.
- **Window:** 7 consecutive qualifying days (ARCH §5.3), ≥ 5 real fills.
  - Starts no earlier than the day after the AUT-5b ruling is filed.
  - **A day fails** if its rollup is missing or produced before the day ended; `passes_completed < 130` of 144; `passes_unknown > 6`; `max_passes_unknown_streak ≥ 3` without a delivered #29 CRITICAL record that day (G1); or `unexplained_failed_units > 0`.
- **Per action class, one live-path event:**

| Class | Event | Natural or injected | Cadence |
|---|---|---|---|
| ENTRY_VETO | `permit_lapsed` at the daily permit expiry (permit `ttl_s=36000`; 10-02: issued 16:50:40Z, expires 10-03 02:50:40Z). Proof: a C1 `EntryVeto(reason=permit_lapsed)` within 120 s after the boot log's `expires_at_ns`, and its clear in the next boot. | natural | daily ≈ 02:50Z |
| ALERT | the 15:45Z or 16:30Z canary `*_canary_d.json`, plus any detector ALERT with its `d` record | natural | twice a day |
| SELF_HEAL | Monday probe ARMED → restart → HEALED, `drill=true` | injected, live path | weekly, after AUT-5b maps #21 |
| DEMOTE | AUT-7b marker naming `DRILL_INJECT` → `aut6.intraday` FAIL verdict → engine DEMOTE (DRILL) → watch-actor `registry_not_champion` veto | injected, live path | once (AUT-7b) |
| HALT | **AUT-7b marker naming `DRILL_INJECT_HALT` → `aut6.intraday` FAIL verdict → engine registry HALT (DRILL; no exec-store write, no freeze) → watch-actor `registry_halted` veto** (ARCH Rev 6 C6, §5.3) | injected, live path | once (same AUT-7b run) |

- **HALT (G4, decided by ARCH Rev 6; r2's D-HALT fallback is withdrawn).** One AUT-7b run (DRILL_PROMOTE → DEMOTE → RESUME → HALT → ROLLBACK) gives AUT-5 and AUT-6 their HALT proofs. The exec-store HALT writers (#17 fee probe, `duplicate_fill`, `ambiguous_exit`) and the INTEGRITY HALT of #15 are **declared gate-proven only** (RED→GREEN), because a live injection would freeze the lineage or the venue. AUT-6 claims 3 on the drill HALT plus those gate proofs.
- **Evidence class:** "machinery proven, edge unproven".
- **ETA** (about 5 fills a day; zero-fill days extend): ARCH-0 ≈ 10-08; AUT-6 Wave 1 merged ≈ 10-16 (H15 drop-in deadline 10-16); AUT-5b ruling ≈ 10-28, window from ≥ 10-29; first SELF_HEAL drill ≈ 11-02; AUT-7b DEMOTE and HALT ≈ 11-03 → 11-06 (≥ 4 trading days). **Full live proof ≈ 2026-11-05 to 11-10**, about 11 weeks before the 2027-01-25 KILL.

---

## 7. Score-3 verification checklist (independent scorer)

| Criterion | Check |
|---|---|
| (a) unattended | `git log --since=<window start> -- deploy/ src/breezy/runtime/alert_delivery.py src/breezy/persistence/autonomy/` shows no commit in the window; every action record carries a unit writer id; C5 DEMOTE/HALT rows carry `decided_by=engine` |
| (b) family-agnostic | `test_every_live_kind_covers_required_detector_classes`, ARCH `test_family_plugin_exact_set`, `test_subject_artefact_is_bound_sha_not_newest_row` green at the window sha |
| (c) fails closed | `test_node_local_unknown_vetoes_after_watch_tick_stale`, `test_inconclusive_streak_writes_detector_blind_and_critical`, `test_systemctl_error_is_unknown_never_zero_failures`, `test_health_monitor_stale_fails_on_unknown_streak_3_with_fresh_heartbeat`, `test_unreadable_fold_writes_critical_and_heartbeat_fold_ok_false`, `test_producer_stale_fails_on_fold_not_ok`, `test_halt_state_unreadable_is_unknown_not_pass`, `test_proc_locks_unreadable_is_unknown_not_zero_holders`, `test_undecidable_price_space_is_inconclusive_not_fail`, `test_unreadable_selfheal_dir_refuses_restart`, `test_canary_retry_gate_sends_when_records_unreadable`, `test_registry_unavailable_skips_exit_0` |
| (d) delivery proven | every window day has a `*_canary_d.json` in `evidence/alerts/<date>/`; `test_check_alerts_reports_not_delivered_through_the_production_tee`, `test_deliver_with_proof_treats_3xx_as_not_delivered`, `test_sigkill_mid_send_is_redelivered_at_least_once` green; no unexplained `abandoned`, `outbox_overflow` or `outbox_write_failed` record, and every AUT-6 summary line in the window shows `journal_write_failures=0` |
| (e) RED→GREEN | each WP merge sha, its RED log, a GREEN gate log ending EXIT=0, `lint-imports` "N kept, 0 broken", the `-rs` summary showing only `AUT6_EXPECTED_SKIP:policy_map_pending_AUT-5b` before AUT-5b and none after; gate-proven HALTs: `test_fill_integrity_fail_declares_halt_floor_integrity`, ARCH `test_halt_reason_class_map_is_exact`, `test_terminal_halt_freezes_lineage` |
| (f) live | `live_proof_<from>_<to>.json`: window start > AUT-5b ruling date; 7 qualifying days; ≥ 5 real fills; ENTRY_VETO (`permit_lapsed` within 120 s of `expires_at_ns`), ALERT (canary record), SELF_HEAL (ARMED → selfheal record → HEALED), DEMOTE (C5 DEMOTE citing a `DRILL_INJECT` verdict id plus node-log `entry_veto reason=registry_not_champion`), HALT (C5 HALT row, cause DRILL, citing a `DRILL_INJECT_HALT` verdict id produced by `aut6.intraday`, plus node-log `entry_veto reason=registry_halted`, and no new exec-store halt key) |
| Monitors watched | `evidence/unit_health/heartbeat.json` age < 1800 s and `passes_unknown_streak < 3` at audit time; AUT-5's dead-man test covers both conditions; #26–#29 verdicts present |
| No expected failures | `systemctl --user list-units --failed 'breezy-*'` empty or explained; `test_every_wrapper_skip_path_exits_success`; journal shows `PORTFOLIO ROI NO_INPUT`; `PRODUCER_DAILY SKIPPED lock_timeout` lines (if any) with `Result=success` |
| Runtime and memory bounds | both unit-contract tests green; `systemctl --user show breezy-discovery-pull.timer -p TimersCalendar` shows 17:12; `systemctl --user show breezy-discovery-pull.service -p MemorySwapPeak` = 0 after WP3b; #31 PASS |
| Timers | #28 PASS; `test_timer_interval_table_covers_every_deployed_timer` green, including `breezy-live-tally.timer` under `TIMER_RETIRED_BY_RULING` |

---

## 8. Risks and failure modes

- **R-1 Alert storm.** Write-on-change plus hourly refresh, per-detector dedupe, ≤ 20 redeliveries per run, 24 h abandonment. At-least-once delivery (G8) can duplicate a page after a SIGKILL mid-send; accepted over losing one.
- **R-2 Memory, the 31 GB (30.67 GiB) host, and the H15 deadline.** Own-lock AUT-6 units total 1.09G; daily producer 3G. The uncommitted drop-in `zz-memory-containment-TEMPORARY.conf` sets quote-tape-ingest `MemoryMax=14G` (measured); with a 16G study holder that is about 30G, which breaks ARCH §5.2. #31 now fails that arithmetic daily (P6-10). Owner ING-2-AMEND2 (`docs/core/PROGRESS.md:52`); deadline 2026-10-16, when #24 escalates to CRITICAL. Decision is build-side incident handling, never the operator. The nightly study stops for the node, never the reverse.
- **R-3 Shared venv and concurrent agents.** Exact interpreter, no `uv`, no `git stash`, per-agent scratchpads, `PYTHONPATH` per worktree, worktrees fast-forwarded first. Tests use a fake `systemctl`/`journalctl` on PATH. Other agents' `run-*` transients are counted only if they reference the repo or a registered worktree path (G13); then they are Breezy jobs (`TRANSIENT_ADHOC`).
- **R-4 Self-heal harm.** Allowlist with an idempotency evidence row per member (G14), memory/OOM never restarted, persisted cap, per-invocation dedupe (G5), slot rule with one exemption, `--no-block`, `ALERT_ONLY` before the ruling, single caller.
- **R-5 False DEMOTE.** Persistent variants only; UNDERPOWERED never acts; INFRA never charges the model budget; Z20 accepted.
- **R-6 Dirty shadow-parity baseline.** #16 pages now (CRITICAL); a finding for AUT-4/AUT-2.
- **R-7 Statistical capacity.** #13 and #14 stay UNDERPOWERED for weeks; the live proof does not depend on them.
- **R-8 No receiver absence rule.** Path B, one pinned egress.
- **R-9 Records on sandboxed units.** `ReadWritePaths` gate test; #23 catches an unwritable or full record root (G10).
- **R-10 Off-loop worker.** A wedged worker holds ≤ `ALERT_OUTBOX_MAX` payloads; each attempt is bounded; CRITICAL entries are already on disk at submit (G8), so a wedged or killed worker loses nothing; the canary and #5 catch a dead path.
- **R-11 KILL 2027-01-25.** If TERMINAL: no sender; #6 reports `family_not_champion`; the fold is non-empty, so `fold_ok=true` and verdicts go to `_host/`; unit health and the canary continue.
- **R-12 Log-line dependence.** The permit line and `FeeDriftProbeActor: RUNNING` verified in 10-02 logs; BREEZY-NWS subscribe error whitelisted.
- **R-13 C-12 not ratified (the planning assumption).** No engine-independent INTEGRITY stop. With a readable policy, the engine HALTs ≤ 150 s after the #15 verdict (≈ 39 min after the fill on a healthy ingest, §3.4.6). With an unreadable policy the verdict is `ERROR` and nothing stops entries automatically beyond the CRITICAL; the exposure is bounded by `rung_net_position_held`, the per-position cap and the venue daily budget. Stated as a residual.
- **R-14 Journal cursor loss.** Vacuum past the cursor ⇒ day-start fallback with `cursor_reset=true`; retention covers ≥ 7 days today. The cursor never advances on an UNKNOWN pass or before records are written (G5).
- **R-15 Node log volume (r3).** One node log reached 1.16 GB (10-01). AUT-6 bounds its own reads (4 MiB tail, WP3b streaming); the volume itself is a finding for AUT-1/AUT-5a (L-29), not silenced.
- **R-16 #15 false positives (r3, G3).** Hidden or sub-snapshot liquidity and clock skew are the residual causes (§3.4.6); each would HALT with an INTEGRITY freeze cleared only by build-side incident handling (W15). Fail-closed over availability, consistent with ARCH §7 Z20.
- **R-17 Ingest stall blinds #15 (r3, G9).** Pending fills become #25 CRITICAL at 6 h; AUT-1's `capture_gap` and #7 page earlier.

---

## 9. Binding-constraint compliance

- **Nautilus immutability:** nothing in Nautilus is touched; #15 calls the native `order_book_depth10` query; the off-loop sink is a stdlib thread pool, the `nws_actor.py` pattern.
- **Caps:** no AUT-6 module reads or writes the operator-reserved controls (ARCH `test_autonomy_never_reads_or_writes_operator_controls`). No value is assigned.
- **allow_short:** untouched (stays `False`); #15 uses `leg_prices` read-only, which itself encodes "every order is a BUY of one leg".
- **NO-SEND:** `test_execution_egress_firewall_guard` unchanged; alert egress stays the single `alerts.env` key (`test_autonomy_alert_egress_not_widened`); Path B, if needed, is one allowlisted host-pinned key that widens nothing else.
- **Master enablement and permit:** `permit_lapsed` and #6 read an expiry integer or log line only (AST test); no AUT-6 code imports the permit issuer, the enablement env or the live-orders gate.
- **PREREG via ruling:** action classes and `n_min` come from the AUT-5 ruling; the catalogue is a proposal; the INTEGRITY floor writer is held on ARCH (C-12) and restrictive only.
- **Safety tests never weakened:** existing alert, egress, firewall, settlement and contract tests pass unedited; `test_alerts_env_deploy.py` gets an additive entry only; the one named expected skip is bounded and self-expiring; `discovery_set_equality.py` keeps its API and its tests unedited.

---

## 10. Self-score (author's estimate; an independent reviewer scores)

Calibration: r1 self-scored 88 and was reviewed at 82; r2 self-scored 89 and was reviewed at 86. This estimate is likely high by about 3.

| Axis | Max | Score | Note |
|---|---|---|---|
| Fidelity | 20 | 19 | Rebased on Rev 6 by sha; `DRILL_INJECT_HALT`, single SELF_HEAL caller, ALERT executor, dead-man in AUT-5, ARCH record path, canary-or-CRITICAL veto, W16 rename, P6-10. C-12 assumption stated and isolated in a held WP. |
| Correctness | 20 | 18 | New premises measured: unit-result counts, timer enablement (live-tally retired, template instances), the discovery-pull read path and log sizes, writer idempotency per self-heal member. Still INFERRED, each behind a verify-first STOP: receiver absence support, tape gap, NO-leg depth form, asos-refresh idempotency, `/proc/locks` under `ProcSubset=all`. |
| Specificity | 15 | 14 | Paths, ids, thresholds, schedules, commit order, test names. |
| Acceptance | 20 | 18 | Every action class has a live path, HALT through the Rev 6 drill; gate-proven HALTs declared as ARCH requires. |
| Autonomy-safety | 15 | 14 | UNKNOWN and empty-fold fail closed, two independent watchers on a blind health unit, outbox at submit, intraday #15 with stated latency. Residual R-13 while C-12 is open. |
| Reuse | 10 | 9 | journald failure entries, native Depth10 query, `leg_prices`, bounded executor, read-only halt readers. |
| **Total** | **100** | **92** | |

## 11. Contradictions with ARCH / README (for ARCH Rev 7)

- **C-1, C-3, C-5..C-9:** as in r1/r2 (passed as P6-1..P6-9; Rev 6 disposed them).
- **C-2:** accepted (`TimeoutStartSec` for oneshot).
- **C-4 / D-HALT:** **closed by Rev 6** (`DRILL_INJECT_HALT`).
- **C-10 / H15:** owner ING-2-AMEND2, 10-16 deadline; now also checked by #31.
- **C-11:** closed by Rev 6 (C2 invariant: drill and voided-pair fills feed DRIFT detectors and the drawdown limit, never any n).
- **C-12 (open, Rev 7/8):** a second, restrictive-only `demand/v1` writer (INTEGRITY FAIL only), **plus `DEMAND_FILES_RESERVED_FOR_INTEGRITY = 1`** on the engine's writer (G9). Assumed not accepted until ARCH decides (§0).
- **C-13:** closed by Rev 6 (`aut6.health` pin implied by §4.3; the dead-man reads AUT-6 monitoring per §4.6). AUT-6 asks Rev 7 to name `passes_unknown_streak ≥ 3` as a dead-man condition (G1).
- **C-14 (new, minor):** ARCH §4.6 lists the delivery-record fields as `event`, `ts_ns`, `delivered`, `status_class`, but C5's `alerts_undeliverable` rule needs to tell a canary or CRITICAL from WARN/INFO and drill rows. Records must also carry `severity`, `attempt_kind` and `drill` (adopted here).
- **C-15 (new, minor):** ARCH §4.6 says WARNING and INFO keep `emit_alert`; the README requires every mapped action "with delivery proven". AUT-6 uses `deliver_with_proof` (recorded and queued) for its own ALERT-class verdicts of any severity, and keeps `emit_alert` semantics for the legacy WARN/INFO sites. ARCH should say "every CRITICAL and every ALERT-mapped verdict action".
- **C-16 (new, minor):** ARCH §4.6 describes the node outbox as in-memory and bounded; G8 needs CRITICAL entries on disk at submit to survive SIGKILL. The file write on the calling thread is local I/O, no network. ARCH should say the bounded outbox is file-backed for CRITICAL.
- **C-17 (new, minor):** ARCH §4.5's AST test text shows the argv `["systemctl", "--user", "restart", unit]`; this plan uses `--no-block` so a long oneshot restart never consumes the health unit's 120 s bound, with success verified at the next pass. ARCH should allow `--no-block` in the pinned argv.

---

## §R3 Disposition (review `reviews/AUT-6-r2-merged.md`)

**G1–G14: 14 FIXED, 0 REJECTED.** ARCH Rev 6 absorbed (G4). C-12 assumption: not accepted until ARCH Rev 7/8 decides; the writer is held in WP5b.

| G | Disposition | Where / evidence |
|---|---|---|
| G1 UNKNOWN streak | FIXED | §3.3.2, §3.11: #29 (intraday producer) and the AUT-5 dead-man both FAIL on `passes_unknown_streak ≥ 3` as well as age; heartbeat carries the streak; tests `test_health_monitor_stale_fails_on_unknown_streak_3_with_fresh_heartbeat`, `test_bus_error_increments_passes_unknown_and_streak`, AUT-5's `test_deadman_pages_on_health_heartbeat_stale_or_unknown_streak`; live-proof day rule (§6) |
| G2 unreadable/empty fold | FIXED | §3.3.2, §3.4.2: CRITICAL `fold_unreadable`, heartbeat `fold_ok=false`, #26 FAILs; empty = zero chain rows, distinct from the all-RETIRED `_host/` case; tests `test_unreadable_fold_writes_critical_and_heartbeat_fold_ok_false`, `test_empty_fold_is_fold_not_ok`, `test_producer_stale_fails_on_fold_not_ok`; daily skip record |
| G3 #15 | FIXED | §3.4.6: taker IOC entry fills only (`OrderLink.time_in_force`; every entry body is `tif: IOC`, `submit_chain.py:360-387`), resting/exit/canary excluded; leg normalised through `leg_prices.py:39-96` (NO buy = SELL/BUY_SHORT); `ref_ask` = lowest displayed ask from `depth_ref` through catalog Depth10 to the fill timestamp (native `order_book_depth10`, `catalog/base.py:158`); `test_legit_ask_drop_and_resting_fill_do_not_trip_integrity`; false-positive residual stated; INTEGRITY cleared only by build-side incident handling (W15) |
| G4 rebase | FIXED | §0 sha `81c3c79f…`; `DRILL_INJECT_HALT` #8h; HALT live proof via AUT-7b, exec-store and INTEGRITY halts gate-proven (§6); single SELF_HEAL caller and ALERT executor (§3.3.1, §3.5); dead-man AUT-5 (§3.11); ARCH record path and canary-or-CRITICAL veto (§3.2 #5, §3.6.2); demand files archived by rename (§3.3.3); P6-10 #31; C-12 assumption stated |
| G5 commit order | FIXED | §3.9: class → action → action record → seen → cursor last; dedupe on `USER_INVOCATION_ID` via `O_EXCL` names; selfheal record carries `invocation_id` (§3.5); crash-between-steps test; fixtures from measured `exit-code` (23) and `signal` (1) entries, plus `oom-kill`, `timeout` |
| G6 timer scan | FIXED | §3.9: every key incl. template expansion (`@pm_us_crh_v2`, `@pm_us_crh_v4` measured); not enabled or `LastTriggerUSec=0` after grace ⇒ FAIL; monotonic field for monotonic timers (none today, measured); `breezy-live-tally.timer` under `TIMER_RETIRED_BY_RULING` (header and `LoadState=not-found` measured) |
| G7 halted too long | FIXED | #30 `aut6.halted_too_long`, > 24 h, `metrics.halted_age_s`, re-page every 24 h, not halt-exempt (§3.13); tests in WP6 |
| G8 outbox at submit | FIXED | §3.6.2, §3.6.4: entry written before the HTTP attempt, renamed into `delivered/` on 2xx (never unlinked); redeliver min age 40 s; `test_sigkill_mid_send_is_redelivered_at_least_once` |
| G9 #15 latency, slot | FIXED | #15 moved to the intraday producer; latency ≈ 39 min on a healthy ingest, 6 h blind bound (§3.4.6); one demand slot reserved for INTEGRITY as part of C-12 (§3.3.3) |
| G10 journal unwritable | FIXED | #23 inputs add `journal_write_failures>0`, the node-log `alert_delivery_journal_unwritable` line, and record-root writability and free space (§3.2, §3.6.2); tests in WP1, WP3 |
| G11 daily lock timeout | FIXED | §3.4.4: lock acquired in the CLI with a 300 s deadline; `PRODUCER_DAILY SKIPPED lock_timeout`, exit 0, write-once skip record read by #27; `test_daily_lock_timeout_prints_skipped_exits_0_and_writes_skip_record` |
| G12 discovery-pull sizing | FIXED | §3.8.1, WP3b: working set 169.6 MB + 4.30 GB swap ≈ 4.47 GB > 1 GB ⇒ redesign: scope to today's spawn, stream in 1 MiB chunks, keep only the consumer's records; code cause `discovery_venue_pull.py:146-197` slurping 63 logs (1.7 GB, largest 1.16 GB); ceilings from the new measured working set, never raised past 512M |
| G13 retry gate, ownership | FIXED | §3.7: unreadable or absent records ⇒ the retry gate sends; §3.9: `run-*` ownership by the repo path prefix `/home/jon/breezy/` or a registered worktree path |
| G14 veto arithmetic, idempotency, `/proc` | FIXED | §3.7: worst case D 18:30Z (or D 17:45Z), inside the trading window, only after 26 h of failed delivery; drill precondition; §3.5 per-unit idempotency table with file:line evidence (asos-refresh conditional on a verify-first); §3.4.2 `ProcSubset=all`, `ProtectProc=default`, unreadable `/proc/locks` ⇒ UNKNOWN |

**r2 H-ids:** H1–H17 and the ARCH Rev 4/5 absorptions are disposed in `AUT-6-drift-health_plan_r2.md` §R2 (17 FIXED); they stand in r3 except where a G-id above supersedes them (H3 by G14 and the Rev 6 veto rule, H11 by Rev 6 `DRILL_INJECT_HALT`, H12 by the C-12 assumption).
