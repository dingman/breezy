# AUT-6 — Drift and health monitoring: area plan, round 2

## 0. Header

| Field | Value |
|---|---|
| ID | AUT-6 |
| Title | Drift and health monitoring (detectors, actions, delivery proof, unit health, self-heal, monitor-the-monitors) |
| Round | r2 (2026-10-03). r1 is kept unchanged at `AUT-6-drift-health_plan_r1.md`; r1 merged review `reviews/AUT-6-r1-merged.md` scored 82, NOT READY (H1–H17). §R2 disposes every H-id. |
| ARCH consumed | `AUTONOMY_ARCHITECTURE.md` **Rev 4**, sha256 `175310117eec39b22fc8229788a7d6182c6395438db23ec65ceb78b964dd508e` (byte-identical to `reviews/snapshots/ARCH_rev4.md`), **plus the pending Rev 5 deltas of `reviews/ARCH-r4-merged.md`, treated as applied**: W1, W9, W11, W12, W13 are implemented here; W2 (DRILL cause class), W5 (halt clears on a CHAMPION fold) and W15 (INTEGRITY freeze cleared by build-side incident handling) are consumed. The ARCH-r4 note "`RuntimeMaxSec` does nothing on oneshot; use `TimeoutStartSec`; your C-2 is accepted" is applied (§3.10). |
| Code baseline | `4b8347a6` (branch `feat/data-capture-and-risk`). Every `file:line` below was checked at that sha. Live facts were read on 2026-10-03 between 03:47Z and 04:20Z, read-only (`systemctl --user show/list-timers/list-units`, `journalctl --user -o json`, node logs, `stat`, `free -b`). |
| Current score | 2 |
| Target | 3 |
| Upstream | AUT-1 (C1 `DetectorEvent`/`EntryVeto` writer; the `feed_stale`/`recorder_stale`/`capture_gap` observations), AUT-2 (C2 labels), AUT-5 (C5 resolver and fold, the policy ruling's `detector_action_map`, the restrictive-only intraday engine, ATTEST, `RegistryWatchActor`, the dead-man, `pins.py`), ARCH-0 (`persistence/autonomy/`, C6 Protocols) |
| Downstream | AUT-5 (consumes C4 `DRIFT`/`HEALTH`, the health heartbeat, the intraday schedule row for `test_attest_cadence_has_no_expiry_gap`), AUT-7 (`DRILL_INJECT`), AUT-1 (`restart_unit`, `deliver_with_proof`), every area (`deliver_with_proof`, the journaling branch) |

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

### 1.2 ARCH Rev 4 §10 obligation (verbatim) and where each part is met

> **AUT-6:** the detector catalogue per kind, split `NODE_LOCAL` / `VERDICT`, each with horizon, policy action class and escalation path; the intraday producer; `deliver_with_proof`, its journal and the RED test proving G26; the migration of every CRITICAL site to it and the `alerts_undeliverable` observation; the canary, the receiver's absence rule and its live proof; the five failing units; `RuntimeMaxSec` for every study unit (G29); `SELF_HEAL_RESTARTABLE_UNITS` membership, the per-unit restart cap and the argv-only restart call site.

| Obligation part | Where met |
|---|---|
| Detector catalogue per kind, NODE_LOCAL/VERDICT, horizon, action class, severity, escalation | §3.2, WP5 |
| Intraday producer | §3.4, WP6 |
| `deliver_with_proof`, journal, G26 RED test | §3.6, WP1 |
| Migration of every CRITICAL site; node-side delivery off the event loop (W9) | §3.6.3–§3.6.4, WP1, WP1b |
| `alerts_undeliverable` observation (W13 rule) | §3.7, WP2 |
| Canary, absence rule, live proof | §3.7, WP2 |
| The five (six, plus two transient) failing units | §3.8, WP3 |
| `RuntimeMaxSec` for every study (G29) | §3.10 rules R-a..R-d (`TimeoutStartSec` for `Type=oneshot`; C-2, accepted by ARCH-r4) |
| `SELF_HEAL_RESTARTABLE_UNITS` membership, persisted per-unit cap (W11), argv-only call site | §3.5, WP4 |
| Mandate items: node-local auto-clearing vetoes, action map, delivery-proof alerts, dead-man inputs, slot table, monitor-the-monitors | §3.3, §3.2, §3.6, §3.11, §3.10 |

---

## 2. L-1 null hypothesis and reuse

"Reuse" means the component is extended or called, never rebuilt. Rows new in r2 are marked **(r2)**.

| New component | Checked capability (file:line) | Verdict |
|---|---|---|
| `deliver_with_proof` | `WebhookAlertSink.emit` posts then `raise_for_status()` (`runtime/health.py:297-299`); the client is built with `follow_redirects=False, trust_env=False` (`:251-257`); `TeeAlertSink.emit` routes every branch through `emit_alert` (`:366-369`), which swallows `BaseException` (`:479-510`); `TeeAlertSink.sinks` is read-only (`:361-364`); `resolve_alert_sink` returns the tee when configured (`:419-423`). Nautilus has no alert delivery. | **Build, small.** Nothing existing can report a webhook failure from a configured process. Reuse the webhook branch, `AlertPayload` (`registry/health_model.py:216-248`), the withheld-message discipline and the `loopback_https_receiver` fixture (`tests/integration/test_alert_webhook_delivery.py`). |
| 3xx semantics **(r2, H17)** | httpx 0.28.1 (`.venv/.../httpx-0.28.1.dist-info`): `Response.raise_for_status` returns only `if self.is_success` and raises `HTTPStatusError` otherwise, including redirects (`httpx/_models.py:794-829`). With `follow_redirects=False` a 3xx therefore raises. | **Reuse.** Map to `status_class="3xx"`, `delivered=False`; pin with a RED test (WP1). |
| Journaling webhook branch | 48 analysis call sites plus the node use `emit_alert` (codegraph blast radius of `registry/health_model.py:322`); `resolve_alert_sink` has 17 callers. | **Extend by composition at one construction site** (§3.6.3). |
| Node off-loop delivery **(r2, W9)** | `nws_actor.py` already runs blocking I/O off the Nautilus loop through a bounded stdlib `ThreadPoolExecutor` via `loop.run_in_executor` (`ingest/nws_actor.py:23,92,129,297`). Node sinks are built at `app/trade.py:474,533,1148` and `runtime/node_config.py:475`; today the webhook POST (5 s timeout) runs synchronously on the calling thread. | **Reuse the bounded-executor pattern** in `OffLoopAlertSink`; no new Nautilus component. |
| Outbox redelivery unit | Oneshots have no "next tick"; `replay_daily_runner.record_skip` retries only its own alert (`scripts/analysis/replay_daily_runner.py:733-762`). | **Build, small.** One oneshot timer drains a file outbox. |
| Canary and off-host absence | `breezy-check-alerts` is a manual one-shot (`check_alerts_cli.py:1-31`). | **Build** a timer around the fixed check path; receiver absence support is INFERRED and verified first (WP2). |
| Node-local detectors `permit_lapsed`, `alerts_undeliverable` | `RegistryWatchActor` 60 s tick (ARCH C5); B1 supervisor permit watch `[17:10Z, 01:00Z)` (`trade_supervisor_core.py:139,1545-1550`); `TradingState.REDUCING` cannot express a per-family veto (ARCH §2). | **Reuse the watch actor's tick**: pure `observe(now_ns)` objects, no new actor or timer. |
| `aut6.node_liveness` | `parse_permit_expiry_ns`, `permit_expiry_valid` (`trade_supervisor_core.py:695-712`); schedule constants `STOP_PRIOR_UTC=16:40`, `LAUNCH_UTC=16:50`, `SELF_CHECK_UTC=17:05`, `SELF_CHECK_WINDOW_END_UTC=17:10` (`:37-50`); node-log name regex (`trade_supervisor.py:798`); recorder live root `catalog_root/"live"` (`quote_tape_disk_monitor.py:168`); writer flush every 10 s (`QUOTE_TAPE_FLUSH_INTERVAL_MS`, `node_config.py:292`, cited at `deploy/systemd/breezy-quote-tape.service:147-148`). | **Reuse the pure parsers and constants read-only** (analysis may import runtime). `trade_supervisor*.py` stays AUT-5a-owned and unedited. |
| Halted-by-design read **(r2, H2)** | `read_family_halt_rows_readonly` + `decode_family_halt_state` (`strategy/current_rung_hold/trial_day_latch.py:333,354`) are the documented lock-free read path for a reader without the exec flock (docstring `:1221-1229`); `record_policy_halt` (A1 CLI) writes the same key (`:1155-1191`). | **Reuse** them read-only (G6 `mode=ro` URI) plus the C5 fold. |
| Forecast and calibration drift | `check_drift`, `check_freshness` and constants (`scripts/analysis/nbp_learning_nightly.py:141-151,286-398`), outside the pinned `breezy.*` closure (ARCH §4.3). | **Move the pure predicates** into `src/breezy/analysis/nbp_drift.py`; the nightly imports them back unchanged. |
| Live calibration leg | `evaluate_calibration_leg` (`forecast_conditional_scoring.py:392`). | **Reuse** on C2 admissible labels. |
| Train/serve parity | `scripts/analysis/nbp_shadow_parity.py:925-946`. | **Reuse** its pure comparison, moved into `breezy.analysis`. |
| Fee drift | `FeeDriftProbeActor` wired for FQ (`app/trade.py:828-844`) and live (`FeeDriftProbeActor: RUNNING`, node log 2026-10-02T20:55:26Z); writes `record_policy_halt` (`trial_day_latch.py:1155-1191`). | **Reuse unchanged**; AUT-6 adds a probe-health verdict only (C-1). |
| Shape drift | Reconciliation-refusal latch plus alert (`component_health_watch.py:401-460`). | **Reuse** read-only. |
| Decision starvation | `HaltDetector.observe` / `all_refused_halt_reason` (`weather_common/halt_detector.py:264-345`); FQ funnel `FqDecisionCounts` + `FqDecisionFunnelActor` (`app/trade.py:772-776`). | **Reuse the predicate** over the funnel files. |
| Unit failure source **(r2, H5)** | systemd 259 writes a structured "unit failed" journal entry `MESSAGE_ID=d9b373ed55a64feb8242e02dbe79a49c` carrying `UNIT_RESULT`, `USER_INVOCATION_ID`, `USER_UNIT` (measured: discovery-pull, 2026-10-02 17:22Z, `UNIT_RESULT=timeout`, invocation `4c04dfc3…`). `study_failure_notifier._default_cause_reader`/`_parse_cause` read `Result`/`ExecMainStatus` (`runtime/study_failure_notifier.py:134-209`). | **Reuse both**: the journal entry (cursor-based) is the failure source of truth; the `show` reader classifies. No new mechanism. |
| Memory-pressure signal **(r2, H13)** | `systemctl --user show` keeps `MemorySwapPeak` and `MemoryPeak` after exit (measured on the failed discovery-pull: `MemorySwapPeak=4301479936`, `MemoryPeak=169615360`, `MemoryHigh=134217728`), but `ControlGroup=` is empty after exit, so cgroup PSI (`memory.pressure`) is readable only while the unit runs. | **Reuse** the persisted properties for post-hoc classification; PSI only enriches the live `STALLED_ACTIVATING` check. |
| Timer liveness **(r2, H5)** | `systemctl --user show <timer> -p LastTriggerUSec,NextElapseUSecRealtime,TimersCalendar,ActiveState` (measured on `breezy-discovery-pull.timer`). 18 timers in `deploy/systemd/`. | **Reuse** the property read; one literal max-interval table. |
| Self-heal restart | None; ARCH §4.5 requires one literal call site. | **Build, one function**, AST-pinned. |
| Detector→action map | ARCH §4.2: the map lives in the AUT-5 ruling's `autonomy-policy/v1` block. | **Consume.** AUT-6 provides the literal catalogue proposal (gate test). |
| Restrictive-demand file **(r2, H12)** | ARCH C5 `demand/v1` files at `registry/demand/<venue>/<family_id>_<ts_ns>.json`: "a demand can only stop entries, so it needs no authentication"; the watch actor honours them; the engine unlinks after a later HALTED/RETIRED/not-CHAMPION row (ARCH Rev 4 lines 389-396). | **Reuse the existing node-side veto file** as the INTEGRITY floor (needs ARCH delta C-12: a second, narrowly scoped writer). |

---

## 3. Design

### 3.1 Placement (import-linter layers, `pyproject.toml:74-101`)

Layers: `app > analysis > strategy > runtime > adapters > ingest > persistence|registry|normalize > settlement > domain`; live packages never import `breezy.analysis`.

| Module | Layer | Contents |
|---|---|---|
| `src/breezy/persistence/autonomy/detector_catalog.py` | persistence | `DetectorSpec` (frozen: `id`, `detector_class`, `kind` `NODE_LOCAL`\|`VERDICT`\|`IN_NODE_EXEC_HALT`, `cause_class`, `proposed_action_class`, **`floor_action_class`** (r2), **`severity`** `CRITICAL`\|`WARN` (r2), **`halt_exempt`** bool (r2), `horizon_s`, `escalates_to`, `producer_id`, **`unknown_streak_max`** (r2)); `CATALOG` (literal only); `REQUIRED_DETECTOR_CLASSES`. |
| `src/breezy/runtime/alert_delivery.py` | runtime | `DeliveryProof`, `deliver_with_proof`, `JournalingWebhookAlertSink`, `OffLoopAlertSink` (r2), `resolve_node_alert_sink` (r2), `DeliveryJournal`, `AlertOutbox`, `drain_outbox`. |
| `src/breezy/runtime/autonomy_node_detectors.py` | runtime | `PermitLapsedDetector`, `AlertsUndeliverableDetector`. |
| `src/breezy/runtime/unit_health.py` | runtime | `UnitObservation`, `UnitFailureClass`, `observe_units`, `read_failed_invocations` (journal cursor, r2), `classify`, `TIMER_MAX_INTERVAL_S` (r2), `UnitHealthJournal`. |
| `src/breezy/runtime/monitor_watch.py` (r2) | runtime | Meta-detectors #26–#28 (producer-stale, verdict-absent, timer liveness) and the heartbeat reader/writer. |
| `src/breezy/runtime/self_heal.py` | runtime | `restart_unit`, `restarts_today` (persisted counter, W11), `SELF_HEAL_DEFERRAL_EXEMPT`. |
| `src/breezy/runtime/autonomy_health_cli.py` | runtime | `breezy-autonomy-health`: unit health, meta-detectors, SELF_HEAL executor, heartbeat, daily rollup. C4 producer `aut6.health` (r2). |
| `src/breezy/runtime/autonomy_canary_cli.py`, `alert_redeliver_cli.py`, `self_heal_probe_cli.py` | runtime | Canary, outbox drain, drill probe. |
| `src/breezy/analysis/nbp_drift.py` | analysis | Moved pure predicates. |
| `src/breezy/analysis/autonomy/drift_fq.py` | analysis | FQ `VERDICT` detectors. |
| `src/breezy/analysis/autonomy/producer_intraday.py`, `producer_daily.py` | analysis | C4 producers `aut6.intraday`, `aut6.daily`. |
| `src/breezy/analysis/autonomy/integrity_floor.py` (r2) | analysis | Writes the INTEGRITY `demand/v1` file (§3.3.3); imports only the C5 demand schema from `persistence/autonomy`. |
| `src/breezy/strategy/forecast_quantile_ladder/plugin.py` (AUT-1 creates; AUT-6 adds one tuple) | strategy | `NODE_PLUGINS[forecast_quantile_ladder].drift_detectors`. |

Before placing any module, grep the containment tests (L-46, L-54): `tests/unit/test_*containment*`, `test_alerts_env_deploy.py`, `test_alert_egress.py`.

### 3.2 Detector catalogue: kind `forecast_quantile_ladder` (the only `LIVE_GATE_ROUTED_KINDS` member)

Every other kind carries `RefusingPlugin` (ARCH C6). A new kind is admitted only with a full catalogue (`test_every_live_kind_covers_required_detector_classes`). The **proposed action** is AUT-6's proposal for the ruling's `detector_action_map`; the runtime class always comes from the ruling (§3.3). **Sev** is the delivery severity (H7). **HX** = halted-by-design exemption (§3.13): `Y` means the detector reports `PASS reason=family_halted|family_not_champion` while the subject family is halted or not CHAMPION.

| # | Detector id | Required class | Kind | Source and rule | Horizon / period | Proposed action | Floor | Sev | HX | Cause | Escalation | Owner |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `feed_stale` | freshness (NBP, obs) | NODE_LOCAL | AUT-1 | AUT-1 | ENTRY_VETO (code-fixed) | — | WARN | n/a | INFRA | → #7 | AUT-1 |
| 2 | `recorder_stale` | freshness (tape) | NODE_LOCAL | AUT-1 | AUT-1 | ENTRY_VETO | — | WARN | n/a | INFRA | → #7 | AUT-1 |
| 3 | `capture_gap` | freshness (capture) | NODE_LOCAL | AUT-1 | AUT-1 | ENTRY_VETO | — | WARN | n/a | INFRA | → #7 | AUT-1 |
| 4 | `permit_lapsed` | permit liveness | NODE_LOCAL | `now_ns > permit.expires_at_ns` (an integer handed in at composition). `None` permit ⇒ `AGREE detail=no_permit`: a node without a genuine permit cannot send (`OrderSubmissionPermit.issue` refuses, `order_enablement.py:198-204`). A read error is UNKNOWN (§3.3.2). | 60 s | ENTRY_VETO. Transition alert only inside `[17:10Z, 01:00Z)`; the daily expiry (≈ 02:50Z, §6) gets a C1 record and no page. | — | CRITICAL in window | n/a | INFRA | → #6 | AUT-6 |
| 5 | `alerts_undeliverable` | unit health (delivery) | NODE_LOCAL | **W13/H3:** the newest `delivered=true`, `drill=false` journal row of **any** `attempt_kind` (`inline`, `redeliver`, `canary`, `check`) in today's and yesterday's `evidence/alerts/delivery/<date>/` is older than `ALERT_CANARY_MAX_AGE_H` (26 h); an absent or unreadable journal vetoes (ARCH C5). Listing cached 600 s. Armed after the first `delivered=true` row ever (ARCH §5.1). | 60 s | ENTRY_VETO | — | CRITICAL | n/a | INFRA | → #23 | AUT-6 |
| 6 | `aut6.node_liveness` | permit, process and log liveness | VERDICT `HEALTH`, intraday | §3.4.3 (four conjuncts, boot grace from 17:05Z, relaunch grace, recorder live-root source, thresholds) | FAIL on 2 consecutive passes (10 min) | ALERT | — | CRITICAL | Y | INFRA | none (a dead node cannot send) | AUT-6 |
| 7 | `aut6.transient_veto_persistent` | freshness | VERDICT `HEALTH`, intraday | a C1 `DetectorEvent` for #1–#3 in `DISAGREE` continuously > 5400 s inside the decision window | 5 min | ALERT | — | CRITICAL | Y | INFRA (never charges the model resume budget, Z10) | none | AUT-6 |
| 8 | `DRILL_INJECT` | (drill) | VERDICT `DRIFT`, intraday | marker present ⇒ FAIL; absent ⇒ PASS (Z2) | 5 min | DEMOTE only under the active drill clause | — | WARN | N | DRILL (W2: charges only `drill_resumes`) | none | AUT-6 / AUT-5/7 |
| 9 | `aut6.forecast_drift` | forecast drift | VERDICT `DRIFT`, daily | `drift_flags` mean-residual shift > 2.5 °F, trailing 14 FINAL CLI days | daily | ALERT | — | WARN | N | MODEL | → #10 | AUT-6 |
| 10 | `aut6.forecast_drift_persistent` | forecast drift | VERDICT `DRIFT`, daily | #9 FAIL on ≥ 2 of the last 3 runs | daily | DEMOTE | — | CRITICAL | N | MODEL | — | AUT-6 |
| 11 | `aut6.feature_drift` | feature distribution | VERDICT `DRIFT`, daily | PSI > 0.25 on per-station NBP `q90−q10` and on the decision `p_hat` histogram, trailing 7 d vs 8–67 d; 10 fixed bins, ε = 1e-4; `n_min` 5 stations × 7 d × 2 cycles | daily | ALERT | — | WARN | N | MODEL | → #11p (≥ 3 of 5, DEMOTE, CRITICAL) | AUT-6 |
| 12 | `aut6.calibration_drift_offline` | calibration (external truth) | VERDICT `DRIFT`, daily | `drift_flags` CRPS delta > 0.75 °F, champion artefact vs raw NBP, trailing 14 FINAL days | daily | ALERT | — | WARN | N | MODEL | → #12p (≥ 2 of 3, DEMOTE, CRITICAL) | AUT-6 |
| 13 | `aut6.calibration_drift_live` | calibration on live labels | VERDICT `DRIFT`, daily | `evaluate_calibration_leg` on C2 `admissible=true` rows (no canary, **no drill**: a demotion statistic, ARCH §5.3; C-11), clustered by `(station, climate_day)`; `n_min` from the ruling (proposal 30 clusters) | daily | DEMOTE (FAIL only) | — | CRITICAL | N | MODEL | — | AUT-6 |
| 14 | `aut6.fill_slippage_drift` | fill rate and slippage | VERDICT `DRIFT`, daily | fill rate = fills / C1 `TrySubmit`, 7 d vs 30 d (two-proportion Wilson, α = 0.01); slippage median shift > 0.02. **Includes `drill=true` fills (W12)**, never canary (they never reach the exec store, ARCH §5.3). `n_min` 20 TrySubmits | daily | ALERT | — | WARN | Y (no TrySubmits while halted ⇒ UNDERPOWERED by construction, reported as `family_halted`) | MARKET | none | AUT-6 |
| 15 | `aut6.fill_better_than_ask` | fill rate and slippage (integrity) | VERDICT `HEALTH`, daily | any C2 entry with `fill_px < entry_ask − 0.001` (L-25 signature), **drill fills included (W12)** | daily | HALT | **HALT** (§3.3.3) | CRITICAL | N | INTEGRITY | — | AUT-6 |
| 16 | `aut6.shadow_parity` | forecast drift (train/serve skew) | VERDICT `HEALTH`, daily | Take-set equality plus Take numeric mismatches on D-1 | daily | ALERT | — | CRITICAL (a Take-set divergence changes orders) | N | MODEL | — | AUT-6 |
| 17 | `fee_drift_probe` | venue fee drift | IN_NODE_EXEC_HALT (unchanged) | `FeeDriftProbeActor` DISAGREE ⇒ `record_policy_halt(fee_schedule_drift)` | probe interval | HALT (TERMINAL via the mirror) | — | CRITICAL | n/a | TERMINAL | — | existing |
| 18 | `aut6.fee_probe_health` | venue fee drift | VERDICT `HEALTH`, intraday | in the decision window, no `FeeDriftProbeActor: RUNNING` line in the current node log, or `fee_drift_probe_unknown` persisting > 3600 s | 5 min | ALERT | — | CRITICAL | Y | INFRA | — | AUT-6 |
| 19 | `aut6.shape_drift` | venue shape drift | VERDICT `HEALTH`, intraday | a new latched reconciliation refusal (exec store `mode=ro`, G6) or an `_EXECUTION_DRIFT_ALLOWED_KEYS` refusal line | 5 min | ALERT | — | CRITICAL | N | INFRA | — | AUT-6 |
| 20 | `aut6.decision_starvation` | (HaltDetector) | VERDICT `HEALTH`, daily | `all_refused_halt_reason` on the closed decision window: Take = 0 and one reason ≥ 95 %; **drill-episode decisions included (W12)** | daily | ALERT | — | CRITICAL | Y | MARKET | — | AUT-6 |
| 21 | `aut6.unit_health` | unit health | VERDICT `HEALTH`, health pass | failed unit in `SELF_HEAL_RESTARTABLE_UNITS`, class ∈ {TIMEOUT, EXIT_CODE, SIGNAL}, under the persisted cap, slot-safe (§3.5) | 10 min | SELF_HEAL | — | WARN | N | INFRA | → #22 | AUT-6 |
| 22 | `aut6.unit_health_unhealable` | unit health | VERDICT `HEALTH`, health pass | any other failed in-scope invocation, or a failed restart | 10 min | ALERT | — | CRITICAL for data-path units, else WARN | N | INFRA | — | AUT-6 |
| 23 | `aut6.alert_delivery` | unit health (delivery) | VERDICT `HEALTH`, health pass | any of: a canary slot with no `delivered=true` row after its hourly retries (§3.7); an outbox entry older than 24 h (`abandoned`); an `outbox_write_failed` journal row or stdout counter > 0 (H14) | 10 min | ALERT | — | CRITICAL | N | INFRA | → #5 | AUT-6 |
| 24 | `aut6.unit_config_drift` | unit health | VERDICT `HEALTH`, health pass, daily | an installed `breezy-*` unit (symlink target or drop-in) differs from `deploy/systemd/`; today the two `zz-memory-containment-TEMPORARY.conf` drop-ins | daily | ALERT | — | WARN; **CRITICAL from 2026-10-16** (H15 deadline) | N | INFRA | — | AUT-6 |
| 25 | `aut6.detector_blind` (r2, H4) | unit health (meta) | VERDICT `HEALTH`, every producer pass | any VERDICT detector whose inputs were unreadable for `unknown_streak_max` consecutive passes (2 intraday, 1 daily, 2 health) | per pass | ALERT | — | CRITICAL | N | INFRA | — | AUT-6 |
| 26 | `aut6.producer_stale` (r2, H6) | permit, process and log liveness (meta) | VERDICT `HEALTH`, health pass | intraday producer heartbeat older than 900 s; or, inside `[17:05Z, 01:00Z)`, any (subject, intraday detector) with no verdict whose `valid_until_ns > now` | 10 min | ALERT | — | CRITICAL | N | INFRA | — | AUT-6 |
| 27 | `aut6.daily_verdict_absent` (r2, H9) | unit health (meta) | VERDICT `HEALTH`, health pass | for any subject, the newest verdict of any daily detector was produced > 30 h ago | 10 min | ALERT | — | CRITICAL | N | INFRA | — | AUT-6 |
| 28 | `aut6.timer_liveness` (r2, H5) | unit health | VERDICT `HEALTH`, health pass | an enabled `breezy-*.timer` is not `active`, has no future `NextElapseUSecRealtime`, or `LastTriggerUSec` is older than `TIMER_MAX_INTERVAL_S[timer] + 900 s` | 10 min | ALERT | — | CRITICAL | N | INFRA | — | AUT-6 |

**Required-class coverage (C6):** freshness {1, 2, 3, 7}; forecast and feature drift {9, 10, 11, 16}; calibration {12, 13}; fill rate and slippage {14, 15}; fee and shape {17, 18, 19}; permit, process and log liveness {4, 6, 26}; unit health {5, 21–25, 27, 28}.

**Action-class coverage:** ENTRY_VETO {1–5}; ALERT {6, 7, 9, 11, 12, 14, 16, 18–20, 22–28}; SELF_HEAL {21}; DEMOTE {8, 10, 11p, 12p, 13}; HALT {15, 17}.

### 3.3 Detector → action map, UNKNOWN handling, INTEGRITY floor

#### 3.3.1 Consumption contract (unchanged from r1 except where marked)

- `CATALOG` is the code proposal. The ruling's `detector_action_map` lists **exactly** the VERDICT ids of `CATALOG` (`test_policy_detector_map_covers_catalog_exactly`, deploy copy). The H16 skip rule is in WP5.
- Producers stamp `declared_action_class` from the ruling's map via AUT-5's single-read loader. If the ruling is absent, unreadable or sha-mismatched, the producer writes `declared_action_class = max(floor_action_class, ALERT)` with `assumptions:["policy_unavailable"]`, sends the alert through §3.6, and the engine treats the verdict as `ERROR`. **r2 (H12):** for INTEGRITY rows the declared class is the HALT floor, and §3.3.3 protects the venue independently of the engine.
- NODE_LOCAL ids are code-fixed `ENTRY_VETO` and never appear in the map. `IN_NODE_EXEC_HALT` (#17) is mirrored by the engine's fixed table.
- **Executors:** ENTRY_VETO = `RegistryWatchActor` (AUT-5) polling #1–#5. DEMOTE/HALT = the restrictive-only intraday engine (AUT-5). SELF_HEAL = `breezy-autonomy-health` (§3.5), only once the ruling maps #21. ALERT = the producer through the journaling sink and outbox (§3.6). Before the ruling (AUT-5b), the health unit runs `ALERT_ONLY`.
- Z10: every verdict carries `metrics.cause_class`; INFRA never charges `MAX_RECOVERABLE_RESUMES_PER_LINEAGE_14D`; DRILL charges only `drill_resumes` (W2).

#### 3.3.2 UNKNOWN fails closed (H4)

- **NODE_LOCAL (#4, #5).** Any observation error ⇒ `UNKNOWN`. While UNKNOWN for at most `WATCH_TICK_STALE_S` (180 s, three ticks; ARCH §4.5) the detector vetoes nothing. Past that, it **returns its own veto reason** (fail closed), AUT-1's writer records `DetectorEvent(state=UNKNOWN, detail=persistent)`, and the transition sends a CRITICAL `aut6_detector_unknown_persistent`. It clears on the next good observation. `permit_lapsed` with `None` permit is `AGREE detail=no_permit`, not UNKNOWN (§3.2 #4).
- **VERDICT detectors.** C4 has no UNKNOWN outcome. An unreadable input gives `outcome=INCONCLUSIVE`, `assumptions:["input_unreadable"]` and `metrics.unknown_streak=k`. INCONCLUSIVE never counts as PASS, so ATTEST cannot cite it; a persistent blind HEALTH detector therefore ends in `registry_attest_expired` node-side (ARCH C5). When `k ≥ unknown_streak_max`:
  1. the producer writes #25 `aut6.detector_blind` FAIL naming the detector id in `metrics.blind_detector`, and sends a CRITICAL through §3.6 (queued on failure);
  2. for the intraday liveness detectors #6, #7 and #18 the detector **itself** reports FAIL `reason=blind`, so it never reads as healthy.
- **Unit-health reads.** A non-zero exit, timeout or D-Bus error from `systemctl`/`journalctl` makes the pass `UNKNOWN`, never "zero failures" (§3.9), and feeds the same streak rule into #25.

#### 3.3.3 INTEGRITY floor (H12)

- `floor_action_class=HALT` for every `cause_class=INTEGRITY` row (today #15). It is a code literal and does not depend on the policy file being readable.
- **Engine-independent protection.** On an INTEGRITY FAIL, `integrity_floor.write_demand` writes, **in addition to** the verdict, one `demand/v1` restrictive-demand file `registry/demand/<venue>/<family_id>_<ts_ns>.json`. It uses the exact ARCH C5 schema, atomic, 0444, under `DEMAND_FILE_MAX_BYTES`, with `reason=integrity_floor` and `verdict_id`. The watch actor already honours it as `registry_restrictive_pending`, so entries for that family stop within one 60 s tick, whatever the engine decides.
- **Clearing.**
  - The engine unlinks the file once the chain shows the family HALTED, RETIRED or not CHAMPION at a later row (ARCH C5).
  - If the engine marked the verdict `ERROR`, for example because the policy is unreadable, the file persists and the veto holds. It is cleared by build-side incident handling (ARCH W15 actor), never by an operator decision and never automatically.
  - A defect-signature fill is exactly the case that warrants stopping and investigating.
- **Caps.** The writer refuses if the venue already holds ≥ `DEMAND_FILES_MAX − 1` files, so it never trips the venue-wide bad-file veto by count. Refusing still sends the CRITICAL.
- This needs ARCH delta **C-12**: a second, restrictive-only writer of `demand/v1`. If ARCH rejects C-12, the fallback is the CRITICAL with proof only, stated as a residual (§8 R-13).

### 3.4 Producers (C4 writers)

#### 3.4.1 Common rules

- Output `derived/verdicts/<family_id>/<YYYY-MM-DD>/<verdict_id>.json` (0600 file, 0700 dir), `verdict/v1`, `mkstemp` + `os.replace`.
- `producer_code_sha` must be in `pins.PRODUCER_SOURCE_SHA256[producer_id]` for `aut6.intraday`, `aut6.daily` and **`aut6.health`** (r2: the health unit writes #21–#28 verdicts, so it is a C4 producer and needs a pin).
- Subjects: every family the fold names CHAMPION, HALTED or CHALLENGER per venue. Host-wide detectors (#6, #18, #19, #21–#28) take the venue champion as subject. With no champion they write `derived/verdicts/_host/`, which the engine ignores.
- **Validity (W1, Z4):**
  - Intraday verdicts set `valid_until_ns = produced_at_ns + 8 h` (`INTRADAY_VALIDITY_S = 28800`); health-pass verdicts do the same.
  - Daily verdicts use `+ 26 h`.
  - Each is ≤ `MAX_VERDICT_VALIDITY_H` (26 h), and the producer refuses to write above it.
- **Refresh and volume (W1):** write when the outcome changes, or when the newest verdict for `(subject, detector)` is older than `INTRADAY_REFRESH_S = 3600`. That is ≤ 24 files per detector per day plus changes.
- **ATTEST invariant (handed to AUT-5, W1).** AUT-5's intraday engine issues ATTEST at most every 6 h, citing intraday HEALTH verdicts. AUT-6 guarantees that at every instant the newest PASS per (subject, intraday HEALTH detector) has ≥ `INTRADAY_VALIDITY_S − INTRADAY_REFRESH_S − PRODUCER_PERIOD_S` = 28800 − 3600 − 300 = **24900 s ≥ ATTEST period 21600 s + ATTEST lag 300 s (= 21900 s)**, with a margin of 3000 s. Pinned by `test_intraday_refresh_keeps_attest_gap_free` (AUT-6), and the schedule row is supplied to AUT-5's `test_attest_cadence_has_no_expiry_gap`.
- `#6` reports `PASS window=closed` outside its window and `PASS reason=family_halted` while halted (§3.13), so the HEALTH kind ATTEST needs is never starved by design states.
- No paths, env values or ids in verdicts (payload hygiene scan).

#### 3.4.2 `breezy-autonomy-producer-intraday` (`aut6.intraday`)

- Inputs (read-only): C1 capture files for today and yesterday; the newest `breezy-trade-*.log` (tail ≤ 4 MiB); the exec store via the `mode=ro` URI; the recorder live root (stat only); the drill marker; the C5 fold; the health heartbeat (§3.11).
- Detectors: #6, #7, #8, #18, #19, and #25 for its own detectors.
- Lock `derived/verdicts/.aut6-intraday.lock`, `flock -n`. On contention it prints `PRODUCER_INTRADAY SKIPPED lock_held`, exits 0 and counts a skip; 3 consecutive skips send a WARN through §3.6. It never takes the studies flock.
- After every run it rewrites `derived/verdicts/.aut6-intraday.heartbeat` (single writer, under its own lock, `os.replace`; L-50-safe) with `{ts_ns, invocation_id, wrote, skipped}`.
- **Reciprocal watch (H6):** if `evidence/unit_health/heartbeat.json` is older than 1800 s, it sends a CRITICAL `aut6_health_stale` (deduped hourly).

#### 3.4.3 `aut6.node_liveness` (#6) in full (H1, H2, H8)

- **Window and boot grace (H1).** The detector is evaluated in `[SELF_CHECK_UTC, 01:00Z)` = `[17:05Z, 01:00Z)`, with `SELF_CHECK_UTC` imported read-only from `trade_supervisor_core.py:39`. Before 17:05Z it reports `PASS metrics.window=boot_grace` (16:40Z–17:05Z) or `PASS window=closed`.
  - *Correction of the review premise, with evidence:* the permit line is written about 1 s after boot, not at about 17:10Z. It appeared at `16:50:15` (09-30), `16:50:12` (10-01) and `16:50:40` (10-02) in the respective `breezy-trade-*T165*Z.log` files. The real exposure is STOP at 16:40Z, LAUNCH at 16:50Z and the relaunch latency up to `LAUNCH_WINDOW_END_UTC`. Starting the window at the supervisor's own self-check time removes it, and the 2-consecutive-FAIL rule pushes the earliest possible page to 17:10Z.
- **Mid-day relaunch grace.** If the newest node log's name timestamp (`_NODE_LOG_NAME_RE`, `trade_supervisor.py:798`) is < 900 s old, the pass is `PASS reason=relaunch_grace`. The grace is **void** when ≥ 3 node logs were created in the last 3600 s; that reports `FAIL reason=relaunch_loop`, so a crash loop cannot hide inside the grace.
- **Conjuncts** (all required; each is recorded in `metrics`):
  1. **Process:** exactly one intent-flock holder (`count_intent_lock_holders` port, `trade_supervisor.py:2341`).
  2. **Log:** the newest node log's mtime age ≤ `LOG_MTIME_MAX_S = 1500`. Justification: the measured maximum inter-line gap is **3 s** across the whole of both 2026-10-02 node logs (16:50Z and 20:55Z), and the FQ funnel flush is 900 s. 1500 s = 900 + 600 s margin, and a "quiet feed" cannot silence the log for 25 min while the node is alive.
  3. **Permit:** the newest log contains a permit line with `expires_at_ns > now`. Relaunched children re-emit it, clamped to the first-boot ceiling (10-02 20:55Z log: same `expires_at_ns` as the 16:50Z boot).
  4. **Tape:** the newest file mtime under the **recorder live root** `<BREEZY_TRADE_CATALOG_ROOT>/live` (`quote_tape_disk_monitor.py:168`) is ≤ `TAPE_MTIME_MAX_S` old. The writer flushes every 10 s. The **ingest output (`data/`) is explicitly not the source**: on a healthy host at 04:14Z it measured 1769 s old, because its cadence is 15 min and it may skip a slice. That is AUT-1's `capture_gap`, not liveness.
     - `TAPE_MTIME_MAX_S = max(1500, 2 × observed max gap)`. The observed gap is measured in WP6's verify-first step from consecutive `ts_init` values across all `quote_tick` files over the last 7 in-window periods, and recorded in the WP6 evidence file. 1500 is the floor (≥ cadence + margin, H8).
- **Halted-by-design (H2):** §3.13. An unreadable halt state or fold is UNKNOWN (§3.3.2), never PASS.
- **FAIL** only on 2 consecutive failing passes (10 min). A single failing pass between two PASSes never alerts (flapping test).

#### 3.4.4 `breezy-autonomy-producer-daily` (`aut6.daily`)

- Inputs: the NBP derived store, settlement truth, C2 labels (drill fills included for #14, #15 and #20; excluded for #13), C1 decisions, the FQ funnel files and the champion artefact.
- Detectors: #9–#16, #20 (and #25 for its own).
- Studies flock, `flock -w 300`.
- **Two slots (H9):** 05:30Z and 13:00Z. The 13:00Z run is a no-op (`PRODUCER_DAILY SKIPPED already_produced`, exit 0) when every (subject, daily detector) already has a verdict produced that UTC day. Otherwise it retries what is missing. A miss in both slots trips #27 at 30 h.

#### 3.4.5 Z12 SLO (unchanged)

The producer runs at `*:00/5` and AUT-5's intraday engine at `*:02/5` (150 s offset per ARCH). No `.path` unit (C-8). Worst case `DetectorEvent → entry veto` ≤ 11 min, inside 15 min (`test_demotion_latency_slo`, producer half).

### 3.5 Self-heal

- **Call site, the only one:** `runtime/self_heal.py::restart_unit(unit, *, run=subprocess.run) -> RestartOutcome`.
  - Raises `ValueError` unless `unit in pins.SELF_HEAL_RESTARTABLE_UNITS`.
  - Runs `run(["systemctl", "--user", "--no-block", "restart", unit], check=False, timeout=30, capture_output=True)`, an argv list, never `shell=True`.
  - It never targets `breezy-trade*`, `breezy-autonomy-engine*` or the supervisor, and never writes under `~/.config/systemd` or `~/.config/breezy` (ARCH AST test, extended).
- **Persisted cap (W11).**
  - Each restart attempt writes one file `evidence/selfheal/<YYYY-MM-DD>/<ts_ns>_<unit>.json` (0444, L-50: one file per action, no rewrite) **before** calling `run`.
  - `restarts_today(unit)` counts those files.
  - `SELF_HEAL_MAX_RESTARTS_PER_UNIT_PER_DAY = 2` (ceiling ≤ 3). The count survives any process or unit restart because it is re-derived from disk each pass.
  - An unreadable directory means **no restart** (fail closed) plus #25.
- **Slot safety.** A restart is attempted only if `now + TimeoutStartSec(unit)` does not intersect `[16:30Z, 17:10Z)`; otherwise it is deferred to 17:10Z and journaled.
  - **Exemption (H6):** `SELF_HEAL_DEFERRAL_EXEMPT = ("breezy-autonomy-producer-intraday.service",)`. It is 512M, holds its own lock and sits on the demotion path, so it is restarted inside the window too.
- **Membership:**
  - `breezy-discovery-pull`, `breezy-fee-evidence-pull`, `breezy-capital-flow-pull`, `breezy-asos-refresh`;
  - `breezy-autonomy-producer-intraday`, `breezy-autonomy-alert-redeliver`, `breezy-autonomy-canary`;
  - `breezy-autonomy-selfheal-probe` (drill target).
  - Studies over 1G are excluded. AUT-1 adds the recorder and feed units through the same tuple.
- **Classification before restart (L-49, H13):**
  - `MEMORY_CEILING_SUSPECT` requires **both** CPU/wall < 0.3 (`CPUUsageNSec` over the `ExecMainStart`/`ExitTimestampMonotonic` delta) **and** a memory-pressure signal: `MemorySwapPeak > 0`, or `MemoryPeak ≥ 0.9 × MemoryHigh` when `MemoryHigh` is finite.
    - Both properties persist after exit (measured). cgroup PSI is unavailable post-exit (`ControlGroup=` empty, measured) and is read only by the live `STALLED_ACTIVATING` check (`memory.pressure` `some avg60`).
    - The 10-02 discovery-pull meets both: CPU/wall 13.86 s / 1800 s = 0.008; swap peak 4.30 GB; peak 169.6 MB ≥ 0.9 × 128 MiB.
  - Low CPU/wall **without** a memory signal is `TIMEOUT`, which is restartable (for example a network stall).
  - `MEMORY_CEILING_SUSPECT` and `OOM` are never restarted; they go to #22 with the L-49 triage line. `NOFILE_EXHAUSTED` goes to ALERT.
- **Verification:** the next pass waits until `ActiveState ∉ {active, activating}`, then requires `Result=success` for an invocation newer than the restart row. A failure means #22.
- **Drill probe:** unchanged from r1 (weekly, Mon 10:00Z; ARMED → exit 1 → restart → HEALED → exit 0; `drill=true`).

### 3.6 Delivery proof (G25, G26, Z13, W9)

#### 3.6.1 API

```python
@dataclass(frozen=True, slots=True)
class DeliveryProof:
    delivered: bool
    status_class: Literal["2xx", "3xx", "4xx", "5xx", "transport", "not_configured", "backpressure"]
    event: str
    ts_ns: int
    journaled: bool

def deliver_with_proof(sink: AlertSink, payload: AlertPayload, *, journal: DeliveryJournal,
                       attempt_kind: Literal["inline", "redeliver", "canary", "check"],
                       queue_on_failure: bool = False, outbox: AlertOutbox | None = None,
                       drill: bool = False,
                       now_ns: Callable[[], int] = time.time_ns) -> DeliveryProof: ...
```

- **Branch selection** is unchanged from r1: the webhook branch of a tee, with every other branch receiving the payload through `emit_alert` first.
- Exceptions: `httpx.HTTPStatusError` maps to `status_code // 100`, which **includes 3xx** (H17: `follow_redirects=False`, `health.py:254`; httpx 0.28.1 raises for any non-success, `_models.py:805-829`). Other `httpx`/`ssl`/`OSError` errors map to `transport`. Only the exception type is logged.

#### 3.6.2 Journal and outbox

- **Journal:** one file per attempt `evidence/alerts/delivery/<YYYY-MM-DD>/<ts_ns>_<pid>_<sha8>.json`, `alert_delivery/v1`, 0444 files in 0700 dirs. Fields `{event, severity, site, ts_ns, delivered, status_class, attempt_kind, payload_sha256, component, drill}`. No URL, message or detail. A journal write failure never blocks delivery: it logs `alert_delivery_journal_unwritable` and returns `journaled=False`.
- **Outbox scope (H7):** `evidence/alerts/outbox/<ts_ns>_<sha8>.json` (0400) holds:
  - (a) every undelivered **CRITICAL** from any site, via the journaling branch;
  - (b) every undelivered **ALERT-class payload of any severity** (WARN included) emitted by an AUT-6 unit, because AUT-6 producers call `deliver_with_proof(..., queue_on_failure=True)`.
  - WARN and INFO from the other 48 legacy sites are journaled, not queued.
- **Write-on-change is not consumed by a failed send (H7).**
  - A producer's transition alert is "sent" only when its proof is `delivered=true`.
  - On failure the payload is in the outbox and redelivery retries it every 5 min until 2xx, or until 24 h, when it becomes an `abandoned` row and #23 FAIL.
  - The producer also keeps `metrics.alert_pending=true` on its next verdict, so the next pass re-emits if the outbox entry itself was not written.
- **Outbox write failure (H14):**
  - logs `alert_outbox_unwritable` at ERROR (type only);
  - writes a journal row with `outbox_write_failed=true` when the journal is writable;
  - increments a process counter printed in the unit's summary line `outbox_write_failures=<n>`.
  - The health pass reads both, and either one makes #23 FAIL (CRITICAL, itself delivered with proof). Tested.

#### 3.6.3 Every CRITICAL through proof without touching 48 call sites (Z13)

- `resolve_alert_sink` builds `TeeAlertSink(LoggingAlertSink(), JournalingWebhookAlertSink(url, journal=…, outbox=…))`.
- `JournalingWebhookAlertSink(WebhookAlertSink).emit`:
  - runs `deliver_with_proof` on the parent branch;
  - queues an undelivered CRITICAL;
  - **re-raises** `AlertNotDeliveredError`, so `emit_alert` contains it and logs exactly as today.
- Existing tee-containment tests stay green unedited, and `isinstance(branch, WebhookAlertSink)` still holds.

#### 3.6.4 Node delivery off the event loop (W9)

- **`OffLoopAlertSink(inner_webhook, *, max_pending=64, close_deadline_s=10.0)`** is built by `resolve_node_alert_sink()`.
  - The **local log branch stays inline**, so the forensic line is written synchronously, as the `TeeAlertSink` rationale requires.
  - The **webhook branch** is submitted to a dedicated single-worker `ThreadPoolExecutor` (the bounded pattern of `nws_actor.py:129,297`).
  - `emit` returns after one `submit`.
  - When `pending ≥ max_pending`, the payload is not submitted. It is journaled `status_class="backpressure", delivered=false` and, if CRITICAL, written to the outbox. This is file I/O only, with no network on the loop thread.
  - The per-attempt hard deadline is the client's 5 s timeout.
  - `close()` drains with `close_deadline_s`, then outboxes whatever remains.
- **Wiring:** AUT-5a swaps the four node construction sites (`app/trade.py:474,533,1148`, `runtime/node_config.py:475`; `app/trade.py` is AUT-5a-only in Wave 1) to `resolve_node_alert_sink()`. Oneshots keep the synchronous sink, because they must prove delivery before they exit.
- **Tests:**
  - `test_offloop_emit_returns_before_webhook_completes`: the receiver stalls 4 s, and `emit` returns within 50 ms.
  - `test_offloop_backpressure_journals_and_outboxes_critical`.
  - `test_offloop_close_drains_then_outboxes`.
  - AUT-5a owns the integration test `test_try_submit_latency_independent_of_webhook_latency`; AUT-6 supplies the stalling-receiver fixture.

#### 3.6.5 Redelivery, G26 fix, egress, sandboxing

- **Redelivery:** `breezy-autonomy-alert-redeliver`, every 5 min, own lock, oldest first, at most 20 per run. On 2xx the entry moves to `outbox/delivered/`; after 24 h it becomes `abandoned` and #23 FAILs.
- **G26:** `check_alerts_cli.check_alerts` uses `deliver_with_proof(attempt_kind="check")` and exits `EXIT_DELIVERY_FAILED` iff not delivered.
- **Egress unchanged:** the only URL source is `BREEZY_ALERT_WEBHOOK_URL` (G27). `test_autonomy_alert_egress_not_widened` and the AST scan pin it.
- **Sandboxed units:** every unit that loads `alerts.env` and declares `ProtectHome=` or `ProtectSystem=strict` also declares `ReadWritePaths=%h/.local/share/breezy/evidence/alerts`. This is pinned by a test.

### 3.7 Canary and off-host absence (H3, W13)

- **`breezy-autonomy-canary`** (oneshot, own lock, `MemoryMax=128M`, `TimeoutStartSec=60`):
  - `OnCalendar=*-*-* *:45:00 UTC` plus `*-*-* 16:30:00 UTC`, `Persistent=false`.
  - **Slot runs:** at 15:45Z (primary, ahead of the receiver's 16:15Z absence check) and 16:30Z (the second slot, which proves delivery just before LAUNCH), the CLI always sends `AlertPayload(severity="INFO", event="autonomy_canary", site="global", detail="canary_ok")` through `deliver_with_proof(attempt_kind="canary")`.
  - **Hourly retry:** on every other :45 run it sends **only if** the newest canary attempt failed and no `delivered=true` row exists since that attempt. Otherwise it prints `AUTONOMY_CANARY skipped=not_due` and exits 0.
  - It prints `AUTONOMY_CANARY delivered=<0|1> status_class=<c> slot=<15:45|16:30|retry>` and exits 0 either way.
  - A failure queues CRITICAL `autonomy_canary_undelivered` and is reported by #23 at the next health pass.
- **Veto rule (#5):** any `delivered=true`, `drill=false` row counts (W13), so the veto needs 26 h with **no** delivered alert of any kind. One failed canary therefore cannot veto the next trading window. The previous day's 15:45Z or 16:30Z success, any inline or redeliver success, or an hourly retry all reset the clock. RED test `test_one_failed_canary_does_not_veto_next_window`.
- **Receiver absence rule (INFERRED; WP2 verify-first STOP):** unchanged from r1. Path A configures the rule receiver-side. Path B adds one host-pinned `BREEZY_ALERT_HEARTBEAT_URL` read only by the canary CLI, re-pinning the egress tests in the same reviewed commit and widening nothing else.
- **Suppression drill and its veto cost (H3):**
  - `--suppress-drill` is honoured only on dates in the literal `CANARY_SUPPRESSION_DRILL_DATES`, and **only for the 15:45Z slot**. It journals `attempt_kind=canary, delivered=false, status_class=not_configured, drill=true` and sends nothing.
  - The 16:30Z slot runs normally.
  - **Declared veto cost: zero trading minutes.** The drill suppresses one slot; the veto needs 26 h without a delivered row; and the 16:30Z slot plus hourly retries deliver before LAUNCH.
  - Worst case: if the 16:30Z slot also fails for an unrelated reason, the veto still needs the newest delivered row to age past 26 h. That is ≥ 15:45Z the next day, with at least 23 hourly retries in between.
  - Evidence: the receiver's absence-page timestamp (a text attestation and a C4 `HEALTH` input hash), and no 15:45Z `delivered=true` canary row that day.

### 3.8 The failing units (evidence 2026-10-03, read-only)

`systemctl --user list-units --failed` at about 04:15Z lists the units below. The facts, root causes and fixes are as in r1 §3.8, re-verified:

| Unit | Fact | Root cause | Fix (WP3) |
|---|---|---|---|
| `breezy-portfolio-roi.service` | exit 1, `PORTFOLIO ROI SKIPPED -- no score-live-trials success marker` (`portfolio-roi-run.sh:93-98`) | `score-live-trials` SKIPs FQ by design (`score-live-trials-run.sh:177-179`) and writes no marker | sibling skip marker `<success-marker>.skipped` (`composition_kind_has_no_scorer`); portfolio-roi prints `PORTFOLIO ROI NO_INPUT -- upstream skipped: <reason>` and exits 0; a truly missing marker stays exit 1 |
| `breezy-discovery-pull.service` | `Result=timeout`, CPU 13.86 s over 30 min, `MemoryPeak` 169.6 MB, `MemorySwapPeak` 4.30 GB, `MemoryHigh=128M`/`MemoryMax=256M` | L-49 signature (§3.5 classifier); INFERRED until the WP3 ΔRSS measurement | ceilings sized to 1.5×/2× measured ΔRSS (provisional 384M/512M), `TimeoutStartSec=900`, timer 16:52Z → **17:12Z**, self-heal member |
| `breezy-parity-mem-1d`, `breezy-parity-mem-7d` (transient) | exit 1 = parity mismatch (`nbp_shadow_parity.py:946`); Takes 5/5 (1 d), 35 vs 38 (7 d) | agent benchmarks; a real signal | disposition file; one-time `reset-failed` at WP3 activation; #16 tracks the signal |
| `run-p814078-i21773018.service` (transient) | exit 2, `INVALIDARGUMENT` | agent ad-hoc run | same |
| `breezy-replay-backfill-0929.service` (transient) | exit 1 after 2 h 08 m, 10G | one-time backfill, superseded | same |

`jetbrains-remote-dev.service` and the `pressure-*` units are foreign (§3.9 ownership rule).

**No expected failures, structurally:** `test_every_wrapper_skip_path_exits_success` covers every `deploy/systemd/*-run.sh` skip branch. `EXPECTED_FAILURE_SUSPECT` (the same `(Result, ExecMainStatus)` on two **distinct** `USER_INVOCATION_ID`s on consecutive days) is never explained.

### 3.9 Unit health: sources, scope, ownership, "unexplained" (H5)

- **Failure source of truth: the journal.** Each pass reads `journalctl --user -o json --after-cursor=<cursor> MESSAGE_ID=d9b373ed55a64feb8242e02dbe79a49c` (argv list) and takes `USER_UNIT`, `USER_INVOCATION_ID` and `UNIT_RESULT` from each entry.
  - The cursor lives in `evidence/unit_health/cursor.json`, rewritten with `os.replace` by the single health writer under its `flock -n` (L-50: one writer holding a lock).
  - A unit that fails and then succeeds between two passes is still counted, because the failure entry stays in the journal.
  - A missing cursor (first run, or a journal rotation past it) falls back to `--since=<last rollup day start>` and journals `cursor_reset=true`.
- **Last-seen InvocationID** per unit is persisted in `evidence/unit_health/seen/<unit>.json`, one file per unit with a single writer. A `show` snapshot whose `InvocationID` equals the last-seen failed invocation is never re-counted. A lingering failed transient is therefore counted once, not every day.
- **Errors are UNKNOWN.** A non-zero exit, timeout or `Failed to connect to bus` from `systemctl` or `journalctl` makes the pass `UNKNOWN`. The rollup's `passes_unknown` increments, and the pass never reports zero failures. The §3.3.2 streak rule raises #25.
- **Scope and ownership.**
  - **In scope:** `^breezy-[a-z0-9@._-]+\.service$`, plus any `run-*.service` whose `Description` or `ExecStart` references the shared interpreter `/home/jon/breezy/.venv/`. Every Breezy job, worktree runs included, must use that interpreter (memory note `never-uv-sync-the-shared-venv`).
  - **Automated sweep:** every pass lists **all** failed `run-*.service` units, not only those matching the regex.
  - **Foreign units:** the rest (for example `jetbrains-remote-dev`, `pressure-*`, other projects' transients) are recorded as `foreign_failed` (count and names) in the rollup and never enter `unexplained_failed_units`. A literal `FOREIGN_UNIT_PREFIXES` covers the known non-`run-*` names.
  - **Breezy-owned transients** (`Transient=yes`, including the `breezy-parity-mem-*` names) classify `TRANSIENT_ADHOC`.
- **Timer liveness (#28).** `TIMER_MAX_INTERVAL_S` is a literal table with one entry per `deploy/systemd/*.timer` (18 today). `test_timer_interval_table_covers_every_deployed_timer` asserts the exact set. Each pass reads `ActiveState`, `NextElapseUSecRealtime` and `LastTriggerUSec` for every enabled timer.
- **Classes:** `TIMEOUT`, `MEMORY_CEILING_SUSPECT`, `OOM`, `NOFILE_EXHAUSTED`, `EXIT_CODE`, `SIGNAL`, `TRANSIENT_ADHOC`, `EXPECTED_FAILURE_SUSPECT`, `STALLED_ACTIVATING`.
- **Journal:** `evidence/unit_health/<YYYY-MM-DD>/<ts_ns>_<unit>_<invocation8>.json`, one file per classification or action.
- **Daily rollup** `evidence/unit_health/day_<YYYY-MM-DD>.json` is written by the first pass after 00:00Z. Fields: `unexplained_failed_units` (int plus names), `foreign_failed`, `passes_completed`, `passes_unknown`, `produced_at_ns`, and `cursor_reset`.
- **Explained** means that, for each failed `(unit, USER_INVOCATION_ID)` that day, the journal holds a classification row and an action row with proof: a SELF_HEAL restart followed by `Result=success`, or an ALERT with `delivered=true`. `TRANSIENT_ADHOC` is explained by its classification plus one delivered WARN. `EXPECTED_FAILURE_SUSPECT` is never explained.

### 3.10 Slot table and runtime bounds (C-2 accepted)

The rules R-a..R-d are unchanged from r1:
- **R-a:** every `Type=oneshot` unit declares `TimeoutStartSec` ≤ its slot.
- **R-b:** a non-daemon `simple`/`exec` unit declares `RuntimeMaxSec`.
- **R-c:** the daemon allowlist is exempt.
- **R-d:** no study window intersects `[16:30Z, 17:10Z)`, with data-path units exempt.

They are pinned by `test_every_unit_has_an_effective_runtime_bound` and `test_no_study_window_intersects_stop_launch`.

| Unit | Type | Schedule (UTC) | Lock / W | Bound | MemoryMax | Notes |
|---|---|---|---|---|---|---|
| `breezy-autonomy-producer-daily` | oneshot | **05:30, 13:00** | studies, `-w 300` | `TimeoutStartSec=1500` | 3G | ends ≤ 06:00 / ≤ 13:30; `OnFailure=breezy-study-failed@%n`; `LimitNOFILE=524288` |
| `breezy-autonomy-producer-intraday` | oneshot | `*:00/5` | own, `-n` | 240 s | 512M | deferral-exempt self-heal member |
| `breezy-autonomy-health` | oneshot | `*:01/10` | own, `-n` | 120 s | 256M | C4 producer `aut6.health`; heartbeat |
| `breezy-autonomy-alert-redeliver` | oneshot | `*:03/5` | own, `-n` | 120 s | 128M | outbox drain |
| `breezy-autonomy-canary` | oneshot | `*:45` + 16:30 | own, `-n` | 60 s | 128M | slots plus hourly retry |
| `breezy-autonomy-selfheal-probe` | oneshot | Mon 10:00 | none | 30 s | 64M | drill target |
| `breezy-discovery-pull` (changed) | oneshot | **17:12** | none | 900 s | 512M (provisional) | §3.8 |

Own-lock autonomy units: 512M + 256M + 128M + 128M + 64M = 1.09G, inside ARCH's 4G budget together with AUT-5's units.

### 3.11 Monitor the monitors (H6) and the dead-man (C-5)

The dead-man stays AUT-5's (ARCH Rev 4 §4.6, §5 table, §10 AUT-5). AUT-6 supplies the following.

1. **The health heartbeat.**
   - Each `breezy-autonomy-health` pass, including an UNKNOWN pass, rewrites `evidence/unit_health/heartbeat.json` (0444, `os.replace`, single writer under its lock) with `{ts_ns, invocation_id, pass_result, passes_unknown_streak}`.
   - **Requirement handed to AUT-5:** the dead-man reads it and raises CRITICAL past `HEALTH_HEARTBEAT_STALE_S = 1800` (3 passes). That is one more file read in the existing dead-man unit.
2. **Producer-stale meta-detector #26**, run by the health unit. It is a different unit, lock and process from the producer, so it is independent of it. It covers the intraday producer heartbeat, and the in-window absence of a valid intraday verdict per (subject, detector). **A missing intraday verdict is an alert, never silence.**
3. **Daily-verdict absence #27** (> 30 h).
4. **Reciprocal watch:** the intraday producer alerts on a stale health heartbeat (§3.4.2). Each of the three watchers (health, intraday producer, AUT-5 dead-man) is watched by at least one other. The off-host canary covers whole-host death.
5. **Unit-health coverage** of `breezy-autonomy-deadman.service` and every AUT-6 unit (#22, #28).
6. **`deliver_with_proof`** for the dead-man's CRITICAL.

### 3.12 Contract use (C1–C6)

- **C1:** consumes `DetectorEvent`, `EntryVeto`, `DecisionRecord` (`TrySubmit`, `p_hat`), `source` and `drill`. Canary records are excluded everywhere. Drill records are included in #14, #15 and #20 (W12) and excluded from #13. Provides the #4 and #5 producer objects.
- **C2:** consumes `admissible`, `excluded_reason`, `slippage`, `fill_px`, `entry_ask`, `p_at_decision`, `settled_outcome` and `drill`.
- **C3:** reads the champion artefact for #12.
- **C4:** produces `DRIFT`/`HEALTH` for every VERDICT id, from three pinned producers.
- **C5:** consumes the fold, the bound sha, the drill marker and the halt-relevant state. Writes only `demand/v1` INTEGRITY files (C-12). Never writes the chain.
- **C6:** provides `DriftDetectors` for `forecast_quantile_ladder` and the required-class gate test.

### 3.13 Halted-by-design is not a failure (H2)

- **Rule.** Before evaluating a detector with `halt_exempt=True` (#6, #7, #14, #18, #20), the producer reads two things for the subject's venue:
  - (a) the C5 fold;
  - (b) the champion's exec-store family halt, through `read_family_halt_rows_readonly` + `decode_family_halt_state` (`trial_day_latch.py:333,354`) over the `mode=ro` URI.
- **Outcomes:**
  - If the fold names no CHAMPION on the venue, the outcome is `PASS reason=family_not_champion`.
  - If the champion is HALTED in the fold, or its exec-store halt is set (A1 `policy_halt`, `duplicate_fill`, `ambiguous_exit`), the outcome is `PASS reason=family_halted`, with `metrics.halt_detail` taken from the closed enum.
  - In both cases the conjunct values stay in `metrics` for observability.
  - An unreadable fold or halt state is UNKNOWN (§3.3.2), never PASS.
- **Why this is safe:**
  - A halted family cannot send: the exec-store halt vetoes at `family_halt_submit_veto` (`trial_day_latch.py:1166-1171` docstring).
  - A node that dies while halted is still caught by unit health (#22), by B1 (supervisor) and by AUT-1's capture detectors.
  - The halt itself was already alerted by its writer.
- **The rule clears on the first verified fold naming the family CHAMPION** with no exec-store halt, which is consistent with W5.
- **Tests:** `test_node_liveness_pass_family_halted`, `test_node_liveness_pass_family_not_champion`, `test_halt_state_unreadable_is_unknown_not_pass`, and `test_decision_starvation_pass_family_halted`.

---

## 4. Work packages

**Gate commands, every WP, in the WP's own worktree:**
1. `PYTHONPATH=<tree>/src scripts/ci/run_tests_no_egress.sh`, run with the exact interpreter `/home/jon/breezy/.venv/bin/python` and never `uv` or `pip` (L-51). Unit-launched gates take `-p LimitNOFILE=524288`, with basetemp on `~/.cache`.
2. `cd <tree> && lint-imports`, demanding "N kept, 0 broken".
3. The mypy ratchet (`tests/unit/test_mypy_ratchet.py`).
4. Read the gate EXIT before any push.
5. The full gate after **every** merge (L-43).

Every injectable seam gets one production-default test (L-55). Every operator-visible line is asserted, then checked in the journal after the first live run (L-52). **Activation:** immediately on merge unless stated (memory note `activate-code-immediately`). A unit-file change means `daemon-reload` plus `enable --now <timer>` by the implementer. Node code takes effect at the next 16:50Z LAUNCH.

### AUT-6.WP1 — Delivery proof, outbox, 3xx, outbox failure. Wave 1, first

- **Files:** `src/breezy/runtime/alert_delivery.py`; `runtime/health.py` (the `resolve_alert_sink` construction only); `runtime/check_alerts_cli.py`; `runtime/alert_redeliver_cli.py`; `deploy/systemd/breezy-autonomy-alert-redeliver.{service,timer}`; `deploy/systemd/breezy-discovery-pull.service` (`ReadWritePaths`); `pyproject.toml`; `tests/unit/test_alerts_env_deploy.py` (an additive list entry, L-12).
- **RED tests first:**
  - `tests/unit/test_alert_delivery.py::test_check_alerts_reports_not_delivered_through_the_production_tee` (G26; no `sink_factory`; loopback 500 → exit 3)
  - `::test_deliver_with_proof_reports_non_2xx_through_tee` (500 → `5xx`; 204 → delivered)
  - `::test_deliver_with_proof_treats_3xx_as_not_delivered` (H17: loopback 302 with a `Location`; `delivered=False, status_class="3xx"`; the receiver sees exactly one request and no follow)
  - `::test_deliver_with_proof_reports_transport_failure_without_the_url`
  - `::test_deliver_with_proof_keeps_the_local_log_line`
  - `::test_journal_is_one_file_per_attempt_and_hygienic`
  - `::test_journal_write_failure_never_blocks_delivery`
  - `::test_resolve_alert_sink_webhook_branch_journals_and_queues_criticals`
  - `::test_aut6_warn_alert_is_queued_when_queue_on_failure` (H7)
  - `::test_legacy_noncritical_failure_is_journaled_not_queued`
  - `::test_outbox_write_failure_is_logged_counted_and_journaled` (H14)
  - `::test_tee_containment_unchanged_with_journaling_branch`
  - `tests/unit/test_alert_redeliver.py::test_outbox_drains_on_2xx_and_abandons_after_24h`
  - `::test_write_on_change_alert_resent_after_failed_delivery` (H7: a transition alert fails, the outbox is redelivered on the next run, and the journal shows `redeliver delivered=true`)
  - `::test_redeliver_runs_the_production_default_once`
  - `tests/unit/test_systemd_unit_contracts.py::test_every_alerting_sandboxed_unit_can_write_the_delivery_journal`
  - `tests/unit/test_autonomy_envelope.py::test_autonomy_alert_egress_not_widened`
- **GREEN:** all pass; the existing `test_alert_egress.py`, `test_runtime_health.py` and `test_alert_webhook_delivery.py` pass **unedited**.
- **Activation:** enable the redeliver timer, run `breezy-check-alerts` once, and confirm the journal shows `attempt_kind=check delivered=true`.

### AUT-6.WP1b — Node off-loop delivery (W9). Wave 1, after WP1

- **Files:** `alert_delivery.py` (`OffLoopAlertSink`, `resolve_node_alert_sink`). AUT-5a swaps the four node sites (§5).
- **RED tests first:**
  - `tests/unit/test_alert_delivery_offloop.py::test_offloop_emit_returns_before_webhook_completes`
  - `::test_offloop_local_log_line_is_synchronous`
  - `::test_offloop_backpressure_journals_and_outboxes_critical`
  - `::test_offloop_close_drains_then_outboxes`
  - `::test_offloop_worker_never_raises_into_caller`
  - `::test_resolve_node_alert_sink_runs_production_default_once`
- **Activation:** effective at the first LAUNCH after AUT-5a's swap. Node log check: `breezy alert` lines are still present, and the journal holds `inline` rows from `component=node`.

### AUT-6.WP2 — Canary, absence rule, `alerts_undeliverable`. Wave 1, after WP1

- **Verify-first STOP:** receiver absence-rule support (yes/no plus evidence class) → Path A or B, written down before code.
- **RED tests first:**
  - `tests/unit/test_autonomy_canary.py::test_canary_delivers_through_proof_and_prints_status`
  - `::test_canary_slots_are_1545_and_1630`
  - `::test_canary_hourly_retry_only_after_failure` (H3)
  - `::test_canary_failure_queues_critical_and_exits_0`
  - `::test_suppress_drill_only_on_preregistered_dates_and_only_1545_slot`
  - `::test_canary_runs_the_production_sink_default_once`
  - `tests/unit/test_autonomy_node_detectors.py::test_alerts_undeliverable_counts_any_delivered_row_kind` (W13/H3)
  - `::test_alerts_undeliverable_ignores_drill_rows`
  - `::test_alerts_undeliverable_reads_today_and_yesterday`
  - `::test_one_failed_canary_does_not_veto_next_window` (H3)
  - `::test_alerts_undeliverable_unarmed_before_first_delivery`
  - `::test_alerts_undeliverable_clears_on_next_2xx`
  - `::test_node_local_unknown_vetoes_after_watch_tick_stale` (H4)
  - `::test_detector_never_raises` (L-16)
- **Activation:** enable the canary timer. The first 15:45Z and 16:30Z runs show `AUTONOMY_CANARY delivered=1`.

### AUT-6.WP3 — Unit health, failing units, timers, slot rules. Wave 1, parallel with WP2

- **Files:**
  - `runtime/unit_health.py`, `runtime/monitor_watch.py`, `runtime/autonomy_health_cli.py`;
  - `deploy/systemd/breezy-autonomy-health.{service,timer}`;
  - `score-live-trials-run.sh`, `portfolio-roi-run.sh`;
  - `breezy-discovery-pull.{service,timer}`;
  - the exit-75 disposition in `replay-daily-run.sh` or its unit;
  - `docs/evidence/unit_health/DISPOSITION_failed_units_2026-10-03.md`;
  - `tests/unit/test_systemd_unit_contracts.py`;
  - `pins.py` (`"aut6.health"`).
- **Verify-first STOP:** discovery-pull ΔRSS per L-49.
- **RED tests first:**
  - `tests/unit/test_unit_health.py::test_classifies_low_cpu_wall_with_swap_peak_as_memory_ceiling_suspect` (the 10-02 fixture)
  - `::test_low_cpu_wall_without_memory_signal_is_timeout_not_memory` (H13)
  - `::test_memory_peak_near_memory_high_counts_as_memory_signal`
  - `::test_fail_then_succeed_between_passes_is_counted_via_journal_cursor` (H5)
  - `::test_cursor_reset_falls_back_to_day_start_and_is_journaled`
  - `::test_last_seen_invocation_not_recounted`
  - `::test_systemctl_error_is_unknown_never_zero_failures` (H5)
  - `::test_bus_error_increments_passes_unknown`
  - `::test_run_sweep_classifies_breezy_owned_transient_by_shared_interpreter`
  - `::test_foreign_transient_excluded_from_unexplained` (H5)
  - `::test_classifies_portfolio_roi_repeat_exit1_on_distinct_invocations_as_expected_failure_suspect`
  - `::test_oneshot_activating_is_not_failed_and_stall_warns_at_80pct`
  - `::test_expected_failure_suspect_is_never_explained`
  - `::test_explained_requires_classification_and_proven_action`
  - `::test_rollup_counts_unexplained_and_passes`
  - `::test_observe_units_runs_the_production_reader_once` (a fake `systemctl`/`journalctl` on PATH)
  - `::test_unit_config_drift_detects_uncommitted_dropin_and_escalates_after_deadline` (H15)
  - `tests/unit/test_monitor_watch.py::test_timer_interval_table_covers_every_deployed_timer`
  - `::test_timer_liveness_fails_on_stale_last_trigger` (H5)
  - `::test_producer_stale_on_old_heartbeat` (H6)
  - `::test_missing_intraday_verdict_in_window_alerts` (H6)
  - `::test_daily_verdict_absent_after_30h` (H9)
  - `::test_health_heartbeat_written_every_pass_including_unknown` (H6)
  - `tests/unit/test_portfolio_roi_run_no_input.py::test_skip_marker_gives_no_input_exit_0`
  - `::test_absent_markers_still_exit_1`
  - `tests/unit/test_score_live_trials_skip_marker.py::test_fq_skip_writes_skip_marker_with_closed_reason`
  - `tests/unit/test_systemd_unit_contracts.py::test_every_unit_has_an_effective_runtime_bound`
  - `::test_no_study_window_intersects_stop_launch` (RED today on 16:52Z)
  - `::test_every_wrapper_skip_path_exits_success`
- **Activation:**
  1. Install and enable the health timer, then `daemon-reload`.
  2. One-time `reset-failed` of the four transient names, journaled.
  3. The 17:40Z portfolio-roi run prints `NO_INPUT` and exits 0.
  4. The first `day_<date>.json` shows `unexplained_failed_units=0` and `foreign_failed` lists `jetbrains-remote-dev.service`.

### AUT-6.WP4 — Self-heal executor and drill probe. Wave 1, after WP3

- **RED tests first:**
  - `tests/unit/test_self_heal.py::test_restart_refuses_non_allowlisted_unit`
  - `::test_restart_uses_argv_list_no_shell`
  - `::test_restart_call_site_is_unique_and_argv_only`
  - `::test_per_unit_daily_cap`
  - `::test_restart_cap_survives_process_restart` (W11: writes two rows, re-imports the module in a fresh subprocess, and the third restart is refused)
  - `::test_restart_row_written_before_run`
  - `::test_unreadable_selfheal_dir_refuses_restart`
  - `::test_memory_ceiling_and_oom_never_restarted`
  - `::test_restart_deferred_when_it_would_intersect_stop_launch`
  - `::test_intraday_producer_exempt_from_deferral` (H6)
  - `::test_verify_waits_out_activating_then_requires_success`
  - `::test_alert_only_mode_without_policy_map`
  - `::test_restart_runs_the_production_default_once`
  - `tests/unit/test_self_heal_probe.py::test_probe_arms_fails_then_heals_once_per_week`
  - plus the extended ARCH `test_self_heal_unit_allowlist_is_literal_and_excludes_trade`.
- **Activation:** enable the probe timer. The unit runs `ALERT_ONLY` until the ruling maps #21.

### AUT-6.WP5 — Catalogue, C6 plug-ins, `permit_lapsed`, UNKNOWN rules, INTEGRITY floor. Wave 1, after the ARCH-0 stubs

- **Files:** `detector_catalog.py`; `autonomy_node_detectors.py` (`PermitLapsedDetector`); the FQ `drift_detectors` entries; `analysis/nbp_drift.py`; `scripts/analysis/nbp_learning_nightly.py` (import back); `analysis/autonomy/integrity_floor.py`.
- **H16 expected-skip rule:**
  - `test_policy_detector_map_covers_catalog_exactly` skips **only** with the exact reason `AUT6_EXPECTED_SKIP:policy_map_pending_AUT-5b`, and only while `deploy/families/rulings/` holds no `autonomy-policy/v1` block.
  - The same module declares the literal `AUT6_EXPECTED_SKIPS: Final = ("policy_map_pending_AUT-5b",)`.
  - `test_aut6_expected_skips_are_exact_and_bounded` AST-scans `tests/` and asserts two things: the set of `AUT6_EXPECTED_SKIP:` reasons equals `AUT6_EXPECTED_SKIPS` (exactly 1), and the tuple must be empty once the ruling exists. Merging the ruling without removing the entry therefore fails the gate.
  - The gate is run with `-rs` so the named skip appears in the summary.
- **RED tests first:**
  - `tests/unit/test_detector_catalog.py::test_catalog_is_literal_only`
  - `::test_every_live_kind_covers_required_detector_classes`
  - `::test_node_local_ids_are_entry_veto_only`
  - `::test_policy_detector_map_covers_catalog_exactly`
  - `::test_aut6_expected_skips_are_exact_and_bounded` (H16)
  - `::test_every_action_class_has_at_least_one_detector`
  - `::test_every_detector_has_a_severity` (H7)
  - `::test_integrity_rows_have_halt_floor` (H12)
  - `::test_policy_unavailable_integrity_verdict_declares_halt_floor` (H12)
  - `tests/unit/test_integrity_floor.py::test_integrity_fail_writes_demand_file_in_c5_schema`
  - `::test_demand_writer_refuses_at_demand_files_max_minus_one_and_still_alerts`
  - `::test_demand_file_written_even_when_policy_unreadable` (H12)
  - `tests/unit/test_autonomy_node_detectors.py::test_permit_lapsed_vetoes_after_expiry_and_alerts_only_in_b1_window`
  - `::test_permit_none_is_agree_no_permit`
  - `::test_permit_lapsed_read_error_unknown_then_vetoes_after_180s` (H4)
  - `::test_permit_lapsed_reads_value_never_the_permit_object_authority`
  - `tests/unit/test_nbp_drift_move.py::test_nightly_behaviour_identical_after_move`
  - ARCH `test_family_plugin_exact_set` stays green.
- **Activation:** none on its own (AUT-5a wires the watch actor).

### AUT-6.WP6 — Intraday producer. Wave 1, after WP5 and AUT-5a's resolver stub

- **Verify-first STOP:** measure the recorder live-root max `ts_init` gap over 7 in-window periods. Set `TAPE_MTIME_MAX_S` and record it in `docs/evidence/aut6/WP6_tape_gap_<date>.md`.
- **RED tests first:**
  - `tests/unit/test_producer_intraday.py::test_node_liveness_requires_all_four_conjuncts`
  - `::test_node_liveness_all_good_positive_control` (H8)
  - `::test_node_liveness_flapping_conjunct_needs_two_consecutive_fails` (H8)
  - `::test_node_liveness_boot_grace_until_1705` (H1: 16:50Z with no node is PASS `boot_grace`; 17:05Z and 17:10Z both failing is FAIL)
  - `::test_node_liveness_transition_1705_with_healthy_new_boot_passes` (H1)
  - `::test_relaunch_grace_and_relaunch_loop_void` (H1)
  - `::test_node_liveness_pass_family_halted` (H2)
  - `::test_node_liveness_pass_family_not_champion` (H2)
  - `::test_halt_state_unreadable_is_unknown_not_pass` (H2/H4)
  - `::test_tape_source_is_recorder_live_root_not_ingest_output` (H8)
  - `::test_log_threshold_1500s` (H8)
  - `::test_inconclusive_streak_writes_detector_blind_and_critical` (H4)
  - `::test_blind_liveness_detector_reports_fail_not_pass` (H4)
  - `::test_transient_veto_persistent_after_5400s`
  - `::test_drill_inject_fail_on_marker_pass_on_absent`
  - `::test_fee_probe_health_fails_without_running_line`
  - `::test_shape_drift_reads_exec_store_readonly`
  - `::test_subject_artefact_is_bound_sha_not_newest_row`
  - `::test_intraday_validity_is_8h_and_bounded` (W1)
  - `::test_intraday_refresh_keeps_attest_gap_free` (W1)
  - `::test_write_on_change_or_hourly_refresh_only`
  - `::test_policy_unavailable_writes_alert_with_assumption`
  - `::test_never_takes_studies_flock`
  - `::test_heartbeat_rewritten_every_run`
  - `::test_alerts_on_stale_health_heartbeat` (H6)
  - `::test_producer_refuses_when_unpinned`
  - `::test_producer_runs_production_readers_once`
  - `::test_payload_hygiene`
  - plus the producer half of `test_demotion_latency_slo` and the schedule row for `test_attest_cadence_has_no_expiry_gap`.
- **Activation:** enable the timer. The journal shows `PRODUCER_INTRADAY wrote=<n> skipped=<m>` every 5 min, and the first pass at or after 17:05Z writes a `node_liveness` PASS.

### AUT-6.WP7 — Daily producer. Wave 2 (#13–#15 need C2 labels)

- **RED tests first:**
  - `tests/unit/test_producer_daily.py::test_forecast_drift_reuses_moved_predicate`
  - `::test_persistent_escalation_2_of_3`
  - `::test_feature_drift_psi_and_underpowered`
  - `::test_calibration_live_excludes_canary_drill_and_inadmissible`
  - `::test_fill_detectors_include_drill_fills` (W12: #14, #15, #20)
  - `::test_calibration_live_underpowered_never_fails`
  - `::test_station_day_clustering`
  - `::test_fill_better_than_ask_is_halt_integrity_and_writes_demand`
  - `::test_fill_slippage_underpowered_below_n_min`
  - `::test_shadow_parity_judges_take_set_only`
  - `::test_decision_starvation_uses_all_refused_predicate`
  - `::test_decision_starvation_pass_family_halted` (H2)
  - `::test_retry_slot_1300_noop_when_produced_and_retries_missing` (H9)
  - `::test_daily_ends_before_refit_slot`
  - `::test_producer_daily_runs_production_readers_once`
- **Activation:** enable the timer. The 05:30Z journal shows `PRODUCER_DAILY wrote=<n>`, and the 13:00Z journal shows `SKIPPED already_produced`.

### AUT-6.WP8 — CRH-semantics wrappers resolve the champion. Wave 2

This is unchanged from r1. `score-live-trials-run.sh`, `replay-daily-run.sh`, `decision-funnel-digest-run.sh` and `family-tally-v2-run.sh` switch to `breezy-registry-champion --venue polymarket_us`. A resolver failure prints `SKIPPED -- registry_unavailable`, exits 0 and is caught by #22. RED tests: `::test_wrapper_keys_off_registry_champion_not_unit_env` and `::test_registry_unavailable_skips_exit_0` in each wrapper test.

### AUT-6.WP9 — Live-proof report. Wave 1, after WP3

- **Behaviour:** as in r1, plus the H10 rules (§6).
- **RED tests first:**
  - `tests/unit/test_aut6_live_proof_report.py::test_zero_fill_day_extends_window`
  - `::test_window_requires_5_real_fills_canary_and_drill_excluded`
  - `::test_each_action_class_needs_a_live_path_event`
  - `::test_drill_events_tagged_and_counted_only_for_their_class`
  - `::test_window_starts_after_aut5b_ruling_date` (H10)
  - `::test_missing_or_stale_rollup_fails_the_day` (H10)
  - `::test_day_with_passes_unknown_over_threshold_fails` (H10)
  - `::test_permit_lapsed_event_matched_to_expires_at_ns` (H10)

---

## 5. Association

| Contract / interface | Direction | Exact item |
|---|---|---|
| C1 (AUT-1) | consume | `DetectorEvent`, `EntryVeto`, `DecisionRecord.kind ∈ {TrySubmit, Take}`, `p_hat`, `ask_px`, `source`, `drill`; `decisions/capture_<family_id>_<date>.jsonl` |
| C1 (AUT-1) | provide | #4 and #5 emit `DetectorEvent(AGREE/DISAGREE/UNKNOWN)` through AUT-1's writer; persistent UNKNOWN carries `detail=persistent` |
| C2 (AUT-2) | consume | `admissible`, `excluded_reason`, `slippage`, `fill_px`, `entry_ask`, `p_at_decision`, `settled_outcome`, `role`, `drill` |
| C2 (AUT-2) | boundary | AUT-6 owns portfolio-roi's exit semantics; AUT-2 owns the FQ scorer (C-9) |
| C4 (AUT-5) | provide | `DRIFT`/`HEALTH` for every VERDICT id from `aut6.intraday`, `aut6.daily`, `aut6.health`; `metrics.cause_class`; intraday validity 8 h with hourly refresh (W1) |
| ATTEST (AUT-5) | provide | the intraday schedule row and the invariant of §3.4.1 for `test_attest_cadence_has_no_expiry_gap` |
| C5 (AUT-5) | consume | fold (subjects, bound sha, CHAMPION/HALTED); drill marker; resolver CLI (WP8) |
| C5 (AUT-5) | provide (C-12) | INTEGRITY `demand/v1` files, restrictive only |
| Policy (AUT-5b) | consume | `detector_action_map` covering `CATALOG` exactly (28 detectors, minus the NODE_LOCAL and IN_NODE ids, plus #11p and #12p); `n_min` for #13; horizons |
| Watch actor (AUT-5a) | provide | the NODE_LOCAL detector objects; AUT-5a wires them, and swaps the four node sink sites to `resolve_node_alert_sink()` (W9) |
| Dead-man (AUT-5) | require | it reads `evidence/unit_health/heartbeat.json` and pages past 1800 s (H6) |
| Engine (AUT-5) | require | intraday engine 150 s after the producer; restrictive-only; ignores `_host/`; honours the INTEGRITY demand file through the watch actor |
| `pins.py` | provide | `PRODUCER_SOURCE_SHA256["aut6.intraday"\|"aut6.daily"\|"aut6.health"]`; `SELF_HEAL_RESTARTABLE_UNITS` members |
| ING-2-AMEND2 (build-side) | require | drop-in removal by 2026-10-16 (H15, §8 R-2) |
| ARCH Rev 5 | require (blocking for HALT) | C-4 drill-HALT delta, owned by ARCH (H11); C-11; C-12 |
| AUT-1 | provide | `restart_unit`; `deliver_with_proof` |
| AUT-7 | provide | `DRILL_INJECT` in the live producer path |

**Order:**
1. **Wave 1:** WP1 → (WP1b ∥ WP2 ∥ WP3) → WP4; WP9 after WP3; WP5 after the ARCH-0 stubs; WP6 after WP5 and AUT-5a's resolver stub.
2. **Wave 2:** WP7, WP8.
3. **Live proof:** DEMOTE and HALT need AUT-5b and AUT-7b (Wave 3), and HALT also needs ARCH C-4.

{WP1b, WP2, WP3, WP5} touch disjoint files.

---

## 6. Live-proof protocol

- **Artefact:** `~/.local/share/breezy/evidence/aut6/live_proof_<from>_<to>.json` (WP9). It cites the rollups, the delivery journal, C1, the C4 ids, the C5 export and node-log lines.
- **Window (H10):** 7 consecutive qualifying days (ARCH §5.3), with ≥ 5 real fills in the window.
  - **Start:** the window starts no earlier than the day after the AUT-5b policy ruling is filed. Before the ruling, actions are not "mapped" and the health unit is `ALERT_ONLY`.
  - **A day fails** if its rollup `day_<date>.json` is missing; if it was produced before the day ended; if `passes_completed < 130` of the 144 expected; if `passes_unknown > 6`; or if `unexplained_failed_units > 0`.
- **Per action class, one live-path event:**

| Class | Event (named precisely) | Natural or injected | Expected cadence |
|---|---|---|---|
| ENTRY_VETO | **`permit_lapsed` at the daily permit expiry.** The permit is issued at boot with `ttl_s=36000` (10-02: issued 16:50:40Z, `expires_at_ns` = 10-03 02:50:40Z; relaunched children keep the first-boot ceiling). Proof: a C1 `EntryVeto(reason=permit_lapsed)` with `ts_ns` within 120 s after the permit line's `expires_at_ns` in the same boot's log, and its clear in the next boot. | natural | daily, about 02:50Z (outside the B1 page window by design) |
| ALERT | the 15:45Z or 16:30Z canary `delivered=true`, plus any detector ALERT with a journal proof row | natural | twice a day |
| SELF_HEAL | Monday probe ARMED → restart → HEALED, `drill=true` | injected, live path | weekly, after AUT-5b maps #21 |
| DEMOTE | AUT-7b `DRILL_INJECT` → verdict → engine DEMOTE → watch-actor veto | injected, live path | once (AUT-7b ≥ 4 trading days) |
| HALT | see below | conditional | — |

- **HALT (H11, contradiction C-4): a blocking dependency owned by ARCH.**
  - **D-HALT:** ARCH Rev 5 must state whether `DRILL_INJECT` may carry `declared_action_class=HALT` under the drill clause as a RECOVERABLE drill HALT: no freeze, drill budget only, RESUME next. P6-4 has been passed to the ARCH revision.
  - **Deadline:** the ARCH Rev 5 review close, **2026-10-10**.
  - **If accepted:** AUT-7b exercises DEMOTE and HALT in two injections, and the HALT proof is the drill HALT row plus the watch-actor veto.
  - **Fallback if rejected or not decided by 10-10:** HALT is "gate-proven (RED→GREEN) plus natural event only".
    - The natural events are `fee_drift_probe` DISAGREE (TERMINAL) and `aut6.fill_better_than_ask` (INTEGRITY).
    - **Probability estimate:** one fee-schedule drift (θ 0.06→0.0695, 2026-09-17) in about 30 days of live operation gives λ ≈ 1/30 d. Over the 10-17 → 2027-01-25 horizon (about 100 days), P(≥ 1) ≈ 1 − e^(−100/30) ≈ 0.96. The 95 % interval on λ from n = 1 is about [0.0008, 0.19] per day, so P lies in about [0.08, 1.0].
    - Such an event retires the lineage (TERMINAL), so it proves the action at the cost of the champion. It is evidence, not a plan.
    - **Under the fallback AUT-6 does not claim 3:** it reports 2 with "HALT gate-proven only" until a natural event lands, and records that in PROGRESS.
- **Evidence class:** "machinery proven, edge unproven".
- **ETA** (about 5 fills a day; zero-fill days extend):
  - ARCH-0 ≈ 10-08.
  - AUT-6 Wave 1 merged ≈ 10-16.
  - The H15 drop-in deadline is 10-16.
  - AUT-5b ruling ≈ 10-28, so the window starts ≥ 10-29.
  - The first SELF_HEAL drill ≈ 11-02.
  - DEMOTE (and HALT, if D-HALT is accepted) via AUT-7b ≈ 11-03 → 11-06.
  - **Full live proof ≈ 2026-11-05 to 11-10.** That leaves about 11 weeks of margin before the 2027-01-25 KILL.

---

## 7. Score-3 verification checklist (independent scorer)

| Criterion | Check |
|---|---|
| (a) unattended | `git log --since=<window start> -- deploy/ src/breezy/runtime/alert_delivery.py src/breezy/persistence/autonomy/` shows no commit inside the window; every action row carries a unit `component`; C5 DEMOTE rows carry `decided_by=engine` |
| (b) family-agnostic | `test_every_live_kind_covers_required_detector_classes`, ARCH `test_family_plugin_exact_set`, `test_subject_artefact_is_bound_sha_not_newest_row` green at the window sha |
| (c) fails closed | `test_node_local_unknown_vetoes_after_watch_tick_stale`, `test_inconclusive_streak_writes_detector_blind_and_critical`, `test_systemctl_error_is_unknown_never_zero_failures`, `test_halt_state_unreadable_is_unknown_not_pass`, `test_demand_file_written_even_when_policy_unreadable`, `test_unreadable_selfheal_dir_refuses_restart`, `test_registry_unavailable_skips_exit_0` |
| (d) delivery proven | every window day has an `autonomy_canary` `delivered=true` row in `evidence/alerts/delivery/<date>/`; `test_check_alerts_reports_not_delivered_through_the_production_tee` and `test_deliver_with_proof_treats_3xx_as_not_delivered` green; no unexplained `abandoned` or `outbox_write_failed` row in the window |
| (e) RED→GREEN | each WP merge sha, its RED log (failing names), a GREEN gate log ending EXIT=0, `lint-imports` "N kept, 0 broken", and the `-rs` summary showing only `AUT6_EXPECTED_SKIP:policy_map_pending_AUT-5b` before AUT-5b and none after |
| (f) live | `live_proof_<from>_<to>.json`: window start > AUT-5b ruling date; 7 qualifying days, each rollup present and fresh with `unexplained_failed_units=0`; ≥ 5 real fills; ENTRY_VETO (`permit_lapsed` within 120 s of `expires_at_ns`), ALERT (canary row), SELF_HEAL (ARMED → restart row → HEALED), DEMOTE (C5 DEMOTE citing a `DRILL_INJECT` verdict id plus node-log `entry_veto reason=registry_not_champion`), HALT (drill HALT row if D-HALT is accepted; otherwise not claimed) |
| Monitors watched | `evidence/unit_health/heartbeat.json` age < 1800 s at audit time; the AUT-5 dead-man unit reads it (its test); #26/#27/#28 verdicts present |
| No expected failures | `systemctl --user list-units --failed 'breezy-*'` empty or explained; `test_every_wrapper_skip_path_exits_success`; journal `PORTFOLIO ROI NO_INPUT` |
| Runtime bounds | both unit-contract tests green; `systemctl --user show breezy-discovery-pull.timer -p TimersCalendar` shows 17:12 |

---

## 8. Risks and failure modes

- **R-1 Alert storm.** Write-on-change plus hourly refresh, per-detector dedupe, at most 20 redeliveries per run, and abandonment at 24 h. Queueing WARN-class AUT-6 alerts (H7) adds at most about 30 entries a day in a bad week.
- **R-2 Memory and the 31 GB (30.67 GiB) host, plus the H15 owner and deadline.**
  - **Facts:** own-lock units total 1.09G; the daily producer is capped at 3G.
  - The uncommitted drop-in `zz-memory-containment-TEMPORARY.conf` sets quote-tape-ingest `MemoryMax=14G` (measured `MemoryMax=15032385536`). Together with a 16G study holder that is about 30G, which breaks ARCH §5.2.
  - **Owner:** **ING-2-AMEND2** (`docs/core/PROGRESS.md:52`). Its own removal criterion is a post-rotation ingest with cgroup `memory.peak ≤ 2G`; the current `MemoryPeak` is 2.21 GB, measured 2026-10-03, so it is not yet met.
  - **Deadline:** **2026-10-16**, before the first AUT-6 live-proof window can open. On that date #24 escalates from WARN to CRITICAL (`test_unit_config_drift_detects_uncommitted_dropin_and_escalates_after_deadline`).
  - The decision belongs to build-side incident handling, never to the operator: either the criterion is met and the drop-in is removed, or ING-2's structural fix is re-opened and the drop-in is lowered to a measured 1.5 × peak.
  - Until then the nightly study stops for the node, never the reverse.
- **R-3 Shared venv and concurrent agents.** Exact interpreter, no `uv`, no `git stash`, per-agent scratchpads, `PYTHONPATH` per worktree, and worktrees fast-forwarded first. Tests use a fake `systemctl`/`journalctl` on PATH. The run-* ownership rule keeps other agents' transients out of the metric unless they use the Breezy interpreter. If they do, they are Breezy jobs and are classified `TRANSIENT_ADHOC` (explained by one delivered WARN), which is the intended pressure toward `systemd-run --collect`.
- **R-4 Self-heal harm.** The allowlist, the memory/OOM never-restart rule (now requiring a real memory signal), the persisted cap, the slot rule with one justified exemption, `--no-block`, and `ALERT_ONLY` before the ruling.
- **R-5 False DEMOTE.** Persistent variants only; UNDERPOWERED never acts; INFRA never charges the model budget; Z20 is an accepted cost.
- **R-6 Dirty shadow-parity baseline.** #16 pages now (CRITICAL). It is a finding for AUT-4/AUT-2, not a silenced detector.
- **R-7 Statistical capacity.** #13 and #14 stay UNDERPOWERED for weeks; the live proof does not depend on them.
- **R-8 No receiver absence rule.** Path B, one pinned egress.
- **R-9 Journal on sandboxed units.** `ReadWritePaths` gate test.
- **R-10 Off-loop worker (W9).** A wedged worker thread could hold up to `max_pending` payloads. Mitigation: the 5 s client timeout bounds each attempt, overflow goes to the outbox, and `close()` drains with a deadline. A hung `httpx` call past its timeout is the residual, and the canary plus `alerts_undeliverable` catch it.
- **R-11 KILL 2027-01-25.** If TERMINAL: no sender; #6 reports `family_not_champion`; unit health and the canary continue.
- **R-12 Log-line dependence.** The permit line (`breezy.app.trade.boot`, L-30) and `FeeDriftProbeActor: RUNNING` are verified in 10-02 logs. The BREEZY-NWS subscribe error is whitelisted.
- **R-13 C-12 rejected.** The INTEGRITY floor degrades to a CRITICAL with proof. A defect-signature fill could then repeat until the engine's HALT lands (≤ 11 min when the policy is readable). If the policy is unreadable, nothing stops entries automatically; that is stated as a residual.
- **R-14 Journal cursor loss.** Journal vacuum past the cursor triggers the day-start fallback with `cursor_reset=true`. A failure older than the retained journal can be missed; the user journal retention covers ≥ 7 days today (entries from 10-02 read on 10-03).

---

## 9. Binding-constraint compliance

- **Nautilus immutability:** nothing in Nautilus is touched. The off-loop sink is a stdlib thread pool outside Nautilus, the same pattern as `nws_actor.py`.
- **Caps:** no AUT-6 module reads or writes the operator-reserved controls (ARCH `test_autonomy_never_reads_or_writes_operator_controls`). No value is assigned.
- **allow_short:** untouched (stays `False`); detectors only veto, report or write restrictive demands.
- **NO-SEND:** `test_execution_egress_firewall_guard` is unchanged. Alert egress stays the single `alerts.env` key (`test_autonomy_alert_egress_not_widened`). Path B, if needed, is one allowlisted, host-pinned key that widens nothing else.
- **Master enablement and permit:** `permit_lapsed` and #6 read an expiry integer or log line only (AST test). No AUT-6 code imports the permit issuer, the enablement env or the live-orders gate.
- **PREREG via ruling:** action classes and `n_min` come from the AUT-5 ruling. The catalogue is a proposal, and the INTEGRITY floor is restrictive only.
- **Safety tests never weakened:** existing alert, egress, firewall, settlement and contract tests pass unedited. `test_alerts_env_deploy.py` gets an additive entry only. The one named expected skip is bounded and self-expiring (H16).

---

## 10. Self-score (author's estimate; an independent reviewer scores)

Calibration note: r1 self-scored 88 and was reviewed at 82, so this estimate is likely high by about 5.

| Axis | Max | Score | Note |
|---|---|---|---|
| Fidelity | 20 | 18 | Consumes Rev 4 plus W1/W9/W11/W12/W13. Raises two new ARCH deltas (C-11, C-12) instead of silently redesigning. |
| Correctness | 20 | 18 | New premises measured: permit-line timing, log gaps, live-root vs ingest freshness, the journal failure entry, persisted memory properties, the httpx 3xx path, the ingest peak. Still INFERRED: the discovery-pull cause, receiver support and the tape-gap threshold, each behind a verify-first STOP. |
| Specificity | 15 | 14 | Paths, ids, thresholds, schedules and test names. |
| Acceptance | 20 | 16 | Every class has a live path except HALT, which is a dated ARCH-owned blocker with a stated fallback that does not claim 3. |
| Autonomy-safety | 15 | 14 | UNKNOWN fails closed, INTEGRITY floor, monitor-the-monitors, off-loop delivery, egress unchanged. |
| Reuse | 10 | 9 | journald failure entries, bounded executor, read-only halt readers, existing demand files. |
| **Total** | **100** | **89** | |

## 11. Contradictions with ARCH / README (for ARCH Rev 5)

- **C-1** (fee probe wired for FQ), **C-3**, **C-5**, **C-6**, **C-7**, **C-8**, **C-9**: as in r1 and passed as P6-1..P6-9.
- **C-2:** accepted by ARCH-r4 (`TimeoutStartSec` for oneshot).
- **C-4 → D-HALT:** now an explicit blocking dependency owned by ARCH, deadline 2026-10-10 (§6).
- **C-10 → H15:** the owner is ING-2-AMEND2, with a 10-16 deadline (§8 R-2).
- **C-11 (new):** W12 ("detectors and the drawdown limit DO include `drill=true` fills") conflicts with ARCH §5.3 ("canary and drill fills never count toward that or any statistic"). Resolution applied here: restrictive safety detectors (#14, #15, #20) include drill fills; the demotion statistic #13 excludes them. ARCH should state the split.
- **C-12 (new):** the INTEGRITY floor needs a second writer of `demand/v1` (AUT-6 producers, INTEGRITY FAIL only, restrictive only). ARCH C5 names only the engine.
- **C-13 (new, minor):** the health unit is a C4 producer (`aut6.health`) and needs a `PRODUCER_SOURCE_SHA256` pin, and the dead-man must read the AUT-6 health heartbeat. ARCH §4.6 and §10 AUT-5 should list both.

---

## §R2 Disposition (review `reviews/AUT-6-r1-merged.md`)

**H1–H17: 17 FIXED, 0 REJECTED.** The ARCH deltas are absorbed: W1, W9, W11, W12, W13, plus the systemd note.

| H | Disposition | Where / evidence |
|---|---|---|
| H1 boot grace | FIXED | §3.4.3: window `[17:05Z, 01:00Z)` keyed to `SELF_CHECK_UTC` (`trade_supervisor_core.py:39`); relaunch grace from the new log's creation, voided by a relaunch loop; WP6 transition tests. **Premise corrected:** the permit line is written about 1 s after boot (09-30 16:50:15, 10-01 16:50:12, 10-02 16:50:40 logs), not at about 17:10Z. The fix stands because of STOP/LAUNCH and relaunch latency. |
| H2 halted-by-design | FIXED | §3.13 (fold plus `read_family_halt_rows_readonly`/`decode_family_halt_state`, `trial_day_latch.py:333,354`); `halt_exempt` column §3.2; tests in WP6/WP7 |
| H3 canary | FIXED | §3.2 #5 (any `delivered=true` row); §3.7 (16:30Z second slot, hourly retry, drill limited to the 15:45Z slot, declared veto cost zero); `test_one_failed_canary_does_not_veto_next_window` |
| H4 UNKNOWN fails closed | FIXED | §3.3.2 (NODE_LOCAL veto after 180 s; INCONCLUSIVE streak → #25 plus CRITICAL; blind liveness detectors FAIL); WP2/WP5/WP6 tests |
| H5 unit health | FIXED | §3.9: journal `MESSAGE_ID=d9b373ed…` cursor (fields measured), persisted InvocationID, systemctl/bus error = UNKNOWN, #28 timer liveness, run-* sweep with a shared-interpreter ownership rule and foreign exclusion; WP3 tests |
| H6 monitor the monitors | FIXED | §3.11 (health heartbeat for the AUT-5 dead-man; #26 independent producer-stale; missing intraday verdict alerts; reciprocal watch); §3.5 deferral exemption |
| H7 ALERT-class delivery | FIXED | §3.2 Sev column for every detector (#9, #11, #12, #14, #24 WARN; #16, #20 CRITICAL); §3.6.2 outbox for all AUT-6 ALERT-class alerts; write-on-change resend; WP1 tests |
| H8 liveness thresholds | FIXED | §3.4.3: tape = recorder live root (ingest output measured at 1769 s on a healthy host, so it is rejected as the source); thresholds ≥ 1500 s; log gap measured at a 3 s maximum; flapping and positive-control tests |
| H9 daily absence and retry | FIXED | #27 (> 30 h); §3.4.4 13:00Z retry slot; WP7 test |
| H10 live proof | FIXED | §6: `permit_lapsed` at `expires_at_ns` (ttl 36000 s, about 02:50Z, measured); window after the AUT-5b ruling; missing or stale rollup fails the day; WP9 tests |
| H11 HALT class | FIXED | §6 D-HALT: an ARCH-owned blocking dependency with a 2026-10-10 deadline; fallback with a probability estimate (≈ 0.96, wide interval; TERMINAL cost); no claim of 3 under the fallback |
| H12 INTEGRITY floor | FIXED | §3.3.3: code HALT floor survives an unreadable policy; a `demand/v1` file protects the venue when the engine marks ERROR (C-12); R-13 residual |
| H13 memory signal | FIXED | §3.5 classifier needs `MemorySwapPeak > 0` or `MemoryPeak ≥ 0.9 × MemoryHigh` (persisted after exit, measured); PSI only while running (`ControlGroup=` empty after exit, measured) |
| H14 outbox write failure | FIXED | §3.6.2 (log, journal row, stdout counter → #23); `test_outbox_write_failure_is_logged_counted_and_journaled` |
| H15 14G drop-in | FIXED | §8 R-2: owner ING-2-AMEND2 (`PROGRESS.md:52`), deadline 2026-10-16, #24 escalates to CRITICAL; current ingest peak 2.21 GB measured |
| H16 expected skip | FIXED | WP5: a single named reason `AUT6_EXPECTED_SKIP:policy_map_pending_AUT-5b`, an exact-set AST test that self-expires when the ruling lands, `-rs` summary |
| H17 3xx | FIXED | §2 and §3.6.1 (`follow_redirects=False`, `health.py:254`; httpx 0.28.1 raises on non-success, `_models.py:805-829`); `test_deliver_with_proof_treats_3xx_as_not_delivered` |
| ARCH W1 | ABSORBED | §3.4.1: 8 h validity, hourly refresh, invariant 24900 s ≥ 21900 s; tests |
| ARCH W9 | ABSORBED | §3.6.4 `OffLoopAlertSink`, WP1b |
| ARCH W11 | ABSORBED | §3.5 persisted counter in `evidence/selfheal/<date>/`; `test_restart_cap_survives_process_restart` |
| ARCH W12 | ABSORBED | §3.2 #14, #15, #20 include drill fills; #13 excludes them (C-11) |
| ARCH W13 | ABSORBED | §3.2 #5; §3.7 |
| systemd note | ABSORBED | §3.10 (C-2 accepted) |
