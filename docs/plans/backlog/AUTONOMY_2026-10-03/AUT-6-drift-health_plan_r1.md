# AUT-6 — Drift and health monitoring: area plan, round 1

## 0. Header

| Field | Value |
|---|---|
| ID | AUT-6 |
| Title | Drift and health monitoring (detectors, actions, delivery proof, unit health, self-heal) |
| Round | r1 (2026-10-03) |
| ARCH consumed | `AUTONOMY_ARCHITECTURE.md` Rev 3, sha256 `66002f49ca33515e3515102d9dbb4134935e0573f85a98a5c41f1352f91361af` (byte-identical to the scratchpad snapshot `ARCH_rev3.md`), **plus the pending Rev 4 deltas Z1–Z20 of `reviews/ARCH-r3-merged.md`, treated as applied**. Z4, Z6, Z10, Z12, Z13 and Z15 are dispositioned here (§3.9). |
| Code baseline | `4b8347a6` (branch `feat/data-capture-and-risk`); every `file:line` below was checked at that sha. Live facts were read on 2026-10-03 at about 03:47Z, read-only (`systemctl --user show/list-units`, `journalctl`, node log). |
| Current score | 2 |
| Target | 3 |
| Upstream | AUT-1 (C1 `DetectorEvent`/`EntryVeto` writer and the `feed_stale`/`recorder_stale`/`capture_gap` observations), AUT-2 (C2 labels), AUT-5 (C5 resolver, the policy ruling's `detector → action_class` map, the engine's restrictive-only intraday pass, `RegistryWatchActor`, `pins.py`), ARCH-0 (the `persistence/autonomy/` package, the C6 Protocols) |
| Downstream | AUT-5 (consumes C4 `DRIFT`/`HEALTH`), AUT-7 (triggers), AUT-1 (uses the self-heal call site and `deliver_with_proof`), every area (uses `deliver_with_proof` for CRITICALs) |

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

### 1.2 ARCH §10 obligations (verbatim) and where each is met

> **AUT-6:** the detector catalogue per kind, split `NODE_LOCAL` / `VERDICT`, each with horizon, policy action class and escalation path; the intraday producer; `deliver_with_proof`, its journal and the RED test proving G26; the canary, the receiver's absence rule and its live proof; the five failing units; `RuntimeMaxSec` for every study unit (G29); `SELF_HEAL_RESTARTABLE_UNITS` membership and the restart call site.

| Obligation | Where met |
|---|---|
| Detector catalogue per kind, NODE_LOCAL/VERDICT, horizon, action class, escalation | §3.2 (table), WP5 |
| Intraday producer | §3.4, WP6 |
| `deliver_with_proof`, journal, RED test proving G26 | §3.6, WP1 |
| Canary, receiver absence rule, live proof | §3.7, WP2 |
| The five failing units | §3.8, WP3 |
| `RuntimeMaxSec` for every study (G29) | §3.10, WP3. **Contradiction C-2:** `RuntimeMaxSec` has no effect on `Type=oneshot`, so the obligation is met by an effective runtime bound instead. |
| `SELF_HEAL_RESTARTABLE_UNITS` membership and restart call site | §3.5, WP4 |
| Mandate items from the brief: node-local auto-clearing vetoes, the action map, delivery-proof alerts, dead-man, slot table | §3.3, §3.2, §3.6, §3.11 (dead-man: **C-5**), §3.10 |

---

## 2. L-1 null hypothesis and reuse

Each new component, the capability checked and the verdict. "Reuse" means the component is extended or called, never rebuilt.

| New component | Checked capability (file:line) | Verdict |
|---|---|---|
| `deliver_with_proof` (delivery proof) | `WebhookAlertSink.emit` raises on non-2xx (`runtime/health.py:297-299`); `TeeAlertSink.emit` routes every branch through `emit_alert` (`:366-369`), which swallows `BaseException` (`:479-510`); `TeeAlertSink.sinks` exposes the branches read-only (`:361-364`); `check_alerts_cli` calls `sink.emit` directly but on the resolved **tee** (`check_alerts_cli.py:123,141`; `health.py:419-423`). Nautilus has no alert delivery. | **Build, small.** No existing path can report a webhook failure from a configured process. Reuse the webhook branch, `AlertPayload` (`registry/health_model.py:217-248`), the withheld-message discipline and the `loopback_https_receiver` test fixture (`tests/integration/test_alert_webhook_delivery.py`). |
| Journaling webhook branch (routes every CRITICAL through proof, Z13) | `resolve_alert_sink` builds `TeeAlertSink(LoggingAlertSink(), WebhookAlertSink(url))` (`health.py:419-423`); 48 analysis call sites plus the node use `emit_alert` (codegraph blast radius). | **Extend by composition at one construction site.** A `WebhookAlertSink` subclass journals each attempt and queues an undelivered CRITICAL. No call site changes, and `isinstance(..., WebhookAlertSink)` assertions in `tests/unit/test_alert_egress.py` keep holding. |
| CRITICAL outbox redelivery unit | Per-emitter "retry next tick" (ARCH §4.6) does not exist for oneshots, which have no next tick. `replay_daily_runner.record_skip` retries only its own alert on the next run (`scripts/analysis/replay_daily_runner.py:733-762`). | **Build, small.** One oneshot timer drains a file outbox through `deliver_with_proof`. |
| Canary and off-host absence | `breezy-check-alerts` is a manual one-shot (`check_alerts_cli.py:1-31`); there is no scheduled heartbeat. | **Build:** a timer around the fixed `check_alerts` path. The receiver-side absence rule is **INFERRED** (ARCH §4.6) and is verified first in WP2. |
| Node-local detectors `permit_lapsed`, `alerts_undeliverable` | Native `Actor` + `clock.set_timer` (G16; `fee_drift_probe.py:342-350`); `RegistryWatchActor` 60 s tick (ARCH C5, AUT-5); B1 supervisor permit-lapse watch, 17:10Z–01:00Z, CRITICAL hourly (`trade_supervisor_core.py:133-149,313,1659`). Nautilus `TradingState.REDUCING` cannot express a per-family entry veto (ARCH §2 L-1, `risk/engine.pyx:1150-1163`). | **Reuse the watch actor's tick.** The detectors are pure `observe(now_ns)` objects polled by AUT-5's actor, with no new actor and no timer. B1 stays the supervisor-side page; the node-local veto adds the C1 `EntryVeto` record that makes "why no trades" answerable. |
| `aut6.node_liveness` (process, log, permit, tape) | Supervisor self-check facts: flock holder, `PERMIT_ISSUED_MARKER`, `parse_permit_expiry_ns` (`trade_supervisor_core.py:1925-1985`); `count_intent_lock_holders`, `resolve_intent_lock_holder` ports (`trade_supervisor.py:2341-2342`); node-log name regex (`trade_supervisor.py:798`); tape live root (`quote_tape_disk_monitor.py:168`). | **Reuse the pure parsers** (`parse_permit_expiry_ns`, `permit_expiry_valid`, `_NODE_LOG_NAME_RE`) read-only from a separate oneshot. `trade_supervisor*.py` stays AUT-5a-owned and unedited. |
| Forecast and calibration drift | `check_drift` (mean-residual shift > 2.5 °F; CRPS delta > 0.75 °F) and `check_freshness` (`scripts/analysis/nbp_learning_nightly.py:286-398`; constants `:141-151`). They live in `scripts/`, outside the pinned `breezy.*` import closure (ARCH §4.3). | **Move the pure predicates, don't duplicate them.** Move them into `src/breezy/analysis/nbp_drift.py` and have the nightly import them back with alarm emission unchanged (`tests/unit/test_nbp_learning_nightly.py` stays green unedited). |
| Live calibration leg | `evaluate_calibration_leg` (`forecast_conditional_scoring.py:392`). | **Reuse** on C2 admissible labels. |
| Train/serve parity | `scripts/analysis/nbp_shadow_parity.py:925-946` (exit 1 iff `n_mismatches`; exit 2 on input error). | **Reuse** its report payload. Promote its pure comparison into `breezy.analysis` the same way as the drift predicates. |
| Fee drift | `FeeDriftProbeActor` is **already wired for FQ** (`app/trade.py:828-844`, S6), and is live: node log `breezy-trade-20261002T205521Z.log` shows `FeeDriftProbeActor: RUNNING` at 20:55:26Z. It writes `record_policy_halt` (`trial_day_latch.py:1155-1191`). | **Reuse unchanged.** AUT-6 adds only a probe-health VERDICT (probe UNKNOWN or absent). Contradiction **C-1**. |
| Shape drift | Reconciliation-refusal latch plus alert (`component_health_watch.py:401-460`). | **Reuse:** read the latched refusals read-only. |
| Decision starvation (HaltDetector) | `HaltDetector.observe` closes a decision window and alerts on all-refused (`weather_common/halt_detector.py:264-345`); CRH only (`current_rung_hold/composition.py`). FQ keeps `FqDecisionCounts` flushed every 15 min (`app/trade.py:772-776`). | **Reuse the predicate** `all_refused_halt_reason` over the FQ funnel files. HaltDetector itself is unchanged. |
| Unit health | `study_failure_notifier._default_cause_reader` and `_parse_cause` read `systemctl --user show` `Result`/`ExecMainStatus` (`runtime/study_failure_notifier.py:134-209`); `OnFailure=breezy-study-failed@%n` WARN via `emit_alert` (`:212-277`). | **Reuse the reader and parser; extend** with classification, action and proof. `breezy-study-failed@` stays as the instantaneous WARN. |
| Self-heal restart | None. ARCH §4.5 requires one literal call site. | **Build, one function**, AST-pinned. |
| Detector→action map | ARCH §4.2: the map lives in the AUT-5 policy ruling's `autonomy-policy/v1` block. | **Consume.** AUT-6 provides a literal **catalogue** (proposal) that the ruling must cover exactly (gate test). It never decides an action at runtime. |

---

## 3. Design

### 3.1 Placement (import-linter layers, `pyproject.toml:74-101`)

The layers run `app > analysis > strategy > runtime > adapters > ingest > persistence|registry|normalize > settlement > domain`, and live packages never import `breezy.analysis`.

| Module | Layer | Contents |
|---|---|---|
| `src/breezy/persistence/autonomy/detector_catalog.py` | persistence | `DetectorSpec` (frozen: `id`, `detector_class`, `kind` `NODE_LOCAL`\|`VERDICT`\|`IN_NODE_EXEC_HALT`, `cause_class` `INFRASTRUCTURE`\|`MODEL`\|`MARKET`\|`INTEGRITY`\|`TERMINAL`\|`DRILL`, `proposed_action_class`, `horizon_s`, `escalates_to`, `producer_id`); `CATALOG: Final[tuple[DetectorSpec, ...]]` (literal only); `REQUIRED_DETECTOR_CLASSES`. |
| `src/breezy/runtime/alert_delivery.py` | runtime | `DeliveryProof`, `deliver_with_proof`, `JournalingWebhookAlertSink`, `DeliveryJournal`, `AlertOutbox`, `drain_outbox`. |
| `src/breezy/runtime/autonomy_node_detectors.py` | runtime | `PermitLapsedDetector`, `AlertsUndeliverableDetector` (both implement the C6 `Detector` Protocol with `kind=NODE_LOCAL`). |
| `src/breezy/runtime/unit_health.py` | runtime | `UnitObservation`, `UnitFailureClass`, `observe_units`, `classify`, `UnitHealthJournal`. |
| `src/breezy/runtime/self_heal.py` | runtime | `restart_unit(unit: str, *, run=subprocess.run)`, the single restart call site. |
| `src/breezy/runtime/autonomy_health_cli.py` | runtime | `breezy-autonomy-health` entry: unit-health pass, SELF_HEAL executor, daily rollup. |
| `src/breezy/runtime/autonomy_canary_cli.py`, `alert_redeliver_cli.py`, `self_heal_probe_cli.py` | runtime | Canary, outbox drain, self-heal drill probe. |
| `src/breezy/analysis/nbp_drift.py` | analysis | Moved pure predicates from `nbp_learning_nightly.py` (`freshness_flags`, `drift_flags`, the constants). |
| `src/breezy/analysis/autonomy/drift_fq.py` | analysis | FQ `VERDICT` detectors (daily and intraday), registered in `OFFLINE_PLUGINS[forecast_quantile_ladder].drift_detectors`. |
| `src/breezy/analysis/autonomy/producer_intraday.py`, `producer_daily.py` | analysis | C4 producers (`producer_id` `aut6.intraday`, `aut6.daily`). |
| `src/breezy/strategy/forecast_quantile_ladder/plugin.py` (AUT-1 creates; AUT-6 adds one tuple) | strategy | `NODE_PLUGINS[forecast_quantile_ladder].drift_detectors` = AUT-1's three observations plus AUT-6's two. |

Before placing any module, grep the containment tests (L-46; L-54): `tests/unit/test_*containment*`, `test_alerts_env_deploy.py` (its unit list), `test_alert_egress.py`.

### 3.2 Detector catalogue: kind `forecast_quantile_ladder` (the only `LIVE_GATE_ROUTED_KINDS` member)

Every other kind carries `RefusingPlugin` (ARCH C6), so this catalogue covers every family that can send. A future kind is admitted only with a full catalogue: the gate test `test_every_live_kind_covers_required_detector_classes` fails otherwise.

The **proposed action** column is AUT-6's proposal for the AUT-5 ruling's `detector_action_map`. The runtime class always comes from the ruling (§3.3).

| # | Detector id | Required class | Kind | Source and rule | Horizon / period | Proposed action | Cause | Escalation | Owner |
|---|---|---|---|---|---|---|---|---|---|
| 1 | `feed_stale` | freshness (NBP, obs) | NODE_LOCAL | AUT-1 in-node observation | AUT-1 | ENTRY_VETO (code-fixed) | INFRA | → #7 | AUT-1 |
| 2 | `recorder_stale` | freshness (tape) | NODE_LOCAL | AUT-1 | AUT-1 | ENTRY_VETO | INFRA | → #7 | AUT-1 |
| 3 | `capture_gap` | freshness (capture) | NODE_LOCAL | AUT-1 | AUT-1 | ENTRY_VETO | INFRA | → #7 | AUT-1 |
| 4 | `permit_lapsed` | permit liveness | NODE_LOCAL | `now_ns > permit.expires_at_ns` (read-only value handed in at composition; `None` permit ⇒ detector reports `UNKNOWN` and vetoes nothing, since shadow mode is not a lapse) | 60 s (watch tick) | ENTRY_VETO. Alert on the transition only inside the B1 window `[17:10Z, 01:00Z)`; after-window expiry is the designed daily end and gets a C1 record, no page. | INFRA | → #6 | AUT-6 |
| 5 | `alerts_undeliverable` | unit health (delivery) | NODE_LOCAL | No `autonomy_canary` journal record with `delivered=true` in the last 26 h (Z13). Reads `evidence/alerts/delivery/<date>/` for today and yesterday read-only; directory listing cached 600 s. Armed only after the first canary 2xx ever journaled (mirrors Z5 bootstrap). | 60 s | ENTRY_VETO | INFRA | → #23 | AUT-6 |
| 6 | `aut6.node_liveness` | permit, process and log liveness | VERDICT `HEALTH`, intraday | All of: exactly one intent-flock holder; newest `breezy-trade-*.log` mtime age ≤ 1200 s (the FQ funnel flushes every 900 s); inside `[17:10Z, 01:00Z)` a permit line whose `expires_at_ns > now`; tape live-root newest epoch mtime age ≤ 900 s (memory note `measure-catalog-freshness-with-epoch`). Evaluated only `[16:50Z, 01:00Z)`; otherwise `PASS` with `metrics.window=closed`. | FAIL on 2 consecutive passes (10 min) | ALERT (CRITICAL) | INFRA | none: a dead node already cannot send, and DEMOTE would cost a trading day per outage | AUT-6 |
| 7 | `aut6.transient_veto_persistent` | freshness | VERDICT `HEALTH`, intraday | A `DetectorEvent` for #1–#3 in `DISAGREE` continuously > 5400 s inside the decision window | 5 min | ALERT (CRITICAL) | INFRA (Z10: never charges the resume budget) | none | AUT-6 |
| 8 | `DRILL_INJECT` | (drill) | VERDICT `DRIFT`, intraday | `registry/drill/marker.json` present (single-read, `O_NOFOLLOW`, size cap, strict schema) ⇒ FAIL; absent ⇒ PASS (Z2) | 5 min | DEMOTE only under the active drill clause; otherwise the engine treats it as `ERROR` | DRILL | none | AUT-6 (detector), AUT-5/7 (marker) |
| 9 | `aut6.forecast_drift` | forecast drift | VERDICT `DRIFT`, daily | `drift_flags` mean-residual shift > 2.5 °F, trailing 14 FINAL CLI days, all stations | daily | ALERT | MODEL | → #10 | AUT-6 |
| 10 | `aut6.forecast_drift_persistent` | forecast drift | VERDICT `DRIFT`, daily | #9 FAIL on ≥ 2 of the last 3 daily runs | daily | DEMOTE | MODEL | — | AUT-6 |
| 11 | `aut6.feature_drift` | feature distribution | VERDICT `DRIFT`, daily | PSI > 0.25 on the per-station NBP spread `q90−q10` and on the decision `p_hat` histogram (C1 `DecisionRecord`), trailing 7 d against trailing 8–67 d; 10 fixed bins, ε = 1e-4 | daily; `n_min` = 5 stations × 7 days × 2 cycles of NBP, else UNDERPOWERED | ALERT | MODEL | → #11p (`aut6.feature_drift_persistent`, ≥ 3 of 5 days, DEMOTE) | AUT-6 |
| 12 | `aut6.calibration_drift_offline` | calibration (external truth) | VERDICT `DRIFT`, daily | `drift_flags` CRPS delta > 0.75 °F of the **champion's** artefact (resolved from C5) vs raw NBP, trailing 14 FINAL days | daily | ALERT | MODEL | → #12p (≥ 2 of 3, DEMOTE) | AUT-6 |
| 13 | `aut6.calibration_drift_live` | calibration on live labels | VERDICT `DRIFT`, daily | `evaluate_calibration_leg` on C2 rows with `admissible=true` (no canary, no drill), traded rung, clustered by `(station, climate_day)` | daily; `n_min` in station-day clusters taken from the ruling (proposal 30), else UNDERPOWERED, which never acts | DEMOTE (FAIL only) | MODEL | — | AUT-6 |
| 14 | `aut6.fill_slippage_drift` | fill rate and slippage | VERDICT `DRIFT`, daily | fill rate = fills / C1 `TrySubmit`, trailing 7 d vs trailing 30 d (two-proportion Wilson, α = 0.01); slippage = C2 `slippage` median shift > 0.02 | daily; `n_min` 20 TrySubmits per window, else UNDERPOWERED | ALERT | MARKET | none | AUT-6 |
| 15 | `aut6.fill_better_than_ask` | fill rate and slippage (integrity) | VERDICT `HEALTH`, daily | any C2 entry with `fill_px < entry_ask − 0.001` (L-25 defect signature) | daily | HALT | INTEGRITY | — | AUT-6 |
| 16 | `aut6.shadow_parity` | forecast drift (train/serve skew) | VERDICT `HEALTH`, daily | Shadow-parity comparison on D-1: **Take-set** equality plus Take numeric mismatches. Kind-label differences (`NotExecutable` vs `Refuse`) are reported, not judged, until dispositioned (§8 R-6). | daily | ALERT (proposed DEMOTE only after 7 clean days; that is a ruling change, not a runtime choice) | MODEL | — | AUT-6 |
| 17 | `fee_drift_probe` | venue fee drift | IN_NODE_EXEC_HALT (legacy, unchanged) | `FeeDriftProbeActor` DISAGREE ⇒ `record_policy_halt(fee_schedule_drift)` | probe interval | HALT (TERMINAL via the AUT-5 mirror) | TERMINAL | — | existing |
| 18 | `aut6.fee_probe_health` | venue fee drift | VERDICT `HEALTH`, intraday | In the decision window: no `FeeDriftProbeActor: RUNNING` line in the current node log, or a `fee_drift_probe_unknown` event persisting > 3600 s | 5 min | ALERT (CRITICAL) | INFRA | — | AUT-6 |
| 19 | `aut6.shape_drift` | venue shape drift | VERDICT `HEALTH`, intraday | a new latched reconciliation refusal (read-only exec store `mode=ro`, G6) or an `_EXECUTION_DRIFT_ALLOWED_KEYS` refusal line | 5 min | ALERT (the refusal already refuses) | INFRA | — | AUT-6 |
| 20 | `aut6.decision_starvation` | (HaltDetector, family-agnostic) | VERDICT `HEALTH`, daily | `all_refused_halt_reason` on the closed decision window from the FQ funnel files: Take = 0 and one reason ≥ 95 % | daily | ALERT | MARKET | — | AUT-6 |
| 21 | `aut6.unit_health` | unit health | VERDICT `HEALTH`, health pass | A failed unit in `SELF_HEAL_RESTARTABLE_UNITS`, class ∈ {TIMEOUT, EXIT_CODE, SIGNAL}, under the per-day cap, slot-safe (§3.5) | 10 min | SELF_HEAL | INFRA | → #22 | AUT-6 |
| 22 | `aut6.unit_health_unhealable` | unit health | VERDICT `HEALTH`, health pass | any other failed in-scope unit, or a failed restart | 10 min | ALERT (CRITICAL for data-path units) | INFRA | — | AUT-6 |
| 23 | `aut6.alert_delivery` | unit health (delivery) | VERDICT `HEALTH`, canary / redeliver | canary `DeliveryProof.delivered=false`, or an outbox entry older than 24 h | per run | ALERT (local log plus outbox) | INFRA | → #5 | AUT-6 |
| 24 | `aut6.unit_config_drift` | unit health | VERDICT `HEALTH`, health pass, daily | an installed `breezy-*` unit (symlink target or drop-in) differs from `deploy/systemd/`; today that means the two `zz-memory-containment-TEMPORARY.conf` drop-ins | daily | ALERT | INFRA | — | AUT-6 |

**Required-class coverage (C6):** freshness {1, 2, 3, 7}; forecast and feature drift {9, 10, 11, 16}; calibration {12, 13}; fill rate and slippage {14, 15}; fee and shape {17, 18, 19}; permit, process and log liveness {4, 6}; unit health {5, 21, 22, 23, 24}.

**Action-class coverage:** ENTRY_VETO {1–5}; ALERT {6, 7, 9, 11, 12, 14, 16, 18–20, 22–24}; SELF_HEAL {21}; DEMOTE {8, 10, 11p, 12p, 13}; HALT {15, 17}.

### 3.3 Detector → action map: the consumption contract

- `detector_catalog.CATALOG` is the code proposal. AUT-5's policy block key `detector_action_map` must list **exactly** the VERDICT ids of `CATALOG`, each with an action class in the ARCH C4 enum. `test_policy_detector_map_covers_catalog_exactly` parses the deploy copy, so a missing or extra id fails the gate.
- The producers stamp `declared_action_class` from the **ruling's** map, read through AUT-5's single-read policy loader. If the ruling is absent, unreadable or sha-mismatched, the producer still writes the verdict with `declared_action_class=ALERT` and `assumptions:["policy_unavailable"]`. The engine then rejects it as `ERROR` (ARCH C4 acceptance), so nothing restrictive is lost silently: an ALERT is still sent through §3.6.
- NODE_LOCAL ids are code-fixed `ENTRY_VETO` (ARCH C6) and never appear in the map. `IN_NODE_EXEC_HALT` (#17) is mirrored by the engine's fixed table (ARCH C5), not mapped.
- **Executors of each class:** ENTRY_VETO is `RegistryWatchActor` (AUT-5) polling #1–#5. DEMOTE and HALT are the engine's restrictive-only intraday pass (AUT-5). SELF_HEAL is `breezy-autonomy-health` (§3.5), only if the ruling maps #21 to SELF_HEAL. ALERT is the producer itself through the journaling sink (§3.6). **Before the ruling is filed (AUT-5b, Wave 3), the health unit runs `ALERT_ONLY`:** no restarts, and every failure is alerted with proof. Stated consequence: the SELF_HEAL live clock starts at the ruling's filing.
- Z10: every verdict carries `metrics.cause_class` from `CATALOG`. The engine (AUT-5) must not charge `MAX_RECOVERABLE_RESUMES_PER_LINEAGE_14D` for `INFRASTRUCTURE`, and caps it at HALTED/INTEGRITY with an alert, never RETIRE.

### 3.4 Producers (C4 writers)

**Common to both.**
- Output is `derived/verdicts/<family_id>/<YYYY-MM-DD>/<verdict_id>.json` (0600 in a 0700 dir), schema `verdict/v1`, written via `mkstemp` + `os.replace`.
- `producer_code_sha` is the import-closure hash; the producer refuses to run if it is not in `pins.PRODUCER_SOURCE_SHA256[producer_id]` (ARCH §4.3).
- `subject_family_id` and `subject_artefact_sha256` are taken from the resolver fold: the family's **bound** artefact sha from its BOOTSTRAP/MINT row (Z1).
- The subjects are every family the fold names CHAMPION, HALTED or CHALLENGER on each venue (family-agnostic by construction). Host-wide detectors (#6, #18, #19, #21–#24) take the venue champion as subject; with no champion they write to `derived/verdicts/_host/`, which the engine ignores.
- **Validity (Z4):** intraday verdicts set `valid_until_ns = produced_at_ns + 1800 s`; daily verdicts `+ 26 h`. Both are ≤ `MAX_VERDICT_VALIDITY_H` (24 h + slack), and the producer refuses to write above it.
- **Volume control:** write when the outcome changes, or when the newest verdict for `(subject, detector)` has < 600 s of validity left. At most about 48 files per detector per day.
- No paths, env values or ids in verdicts (payload hygiene scan, ARCH §3).

**`breezy-autonomy-producer-intraday` (`aut6.intraday`).**
- Inputs: C1 capture files (`DetectorEvent`, `EntryVeto`) for today and yesterday, read-only; the node log (newest `breezy-trade-*.log`, read-only, tail-read ≤ 4 MiB); the exec store `mode=ro` URI; the tape live root (stat only); the drill marker.
- Detectors: #6, #7, #8, #18, #19.
- Lock `~/.local/share/breezy/derived/verdicts/.aut6-intraday.lock`, `flock -n`. Contention prints `PRODUCER_INTRADAY SKIPPED lock_held`, exits 0, and counts a skip; 3 consecutive skips raise a WARN alert. It never takes the studies flock (ARCH §5.2).

**`breezy-autonomy-producer-daily` (`aut6.daily`).**
- Inputs: NBP derived store, settlement truth, C2 labels, C1 decisions, the FQ funnel files, the champion artefact (single-read).
- Detectors: #9–#16, #20.
- Runs under the studies flock (§3.10).

**Z12 SLO.**
- Producer timer `OnCalendar=*:00/5`. AUT-5's intraday engine timer must sit at `*:02/5` (the stagger is a requirement handed to AUT-5).
- **No `.path` unit:** `PathChanged=` on `derived/verdicts/` does not fire for files created in nested `<family>/<date>/` leaf directories, and watching a dated leaf needs a unit rewrite every day.
- Worst case `DetectorEvent → entry veto` = 5 min (producer period) + 2 min (stagger) + engine runtime (≤ 2 min, AUT-5 bound) + 60 s (watch tick) + 1 min margin = **≤ 11 min, inside the 15-min SLO**. Pinned in `test_demotion_latency_slo` (AUT-5 owns the harness; AUT-6 supplies the producer under a fake clock).

### 3.5 Self-heal

- **Call site, the only one in the repo:** `runtime/self_heal.py::restart_unit(unit: str, *, run=subprocess.run) -> RestartOutcome`.
  - Raises `ValueError` unless `unit in pins.SELF_HEAL_RESTARTABLE_UNITS`.
  - Runs `run(["systemctl", "--user", "--no-block", "restart", unit], check=False, timeout=30, capture_output=True)`: an argv list, never `shell=True` (Z15).
  - Never targets a `breezy-trade*`, `breezy-autonomy-engine*` or supervisor unit, and never writes under `~/.config/systemd` or `~/.config/breezy`. Both are pinned by ARCH's `test_self_heal_unit_allowlist_is_literal_and_excludes_trade` (AST). AUT-6 extends it with `test_restart_call_site_is_unique_and_argv_only`.
- **Ceilings** (Z15; constants in `pins.py`, owned by ARCH-0/AUT-5):
  - `SELF_HEAL_MAX_RESTARTS_PER_UNIT_PER_DAY = 2` (code ceiling ≤ 3);
  - a restart is attempted only if `now + TimeoutStartSec(unit)` does not intersect `[16:30Z, 17:10Z)` (§3.10). Otherwise it is deferred to 17:10Z and journaled.
- **AUT-6 membership** (AUT-1 adds its recorder and feed units through the same tuple):
  - `breezy-discovery-pull.service`, `breezy-fee-evidence-pull.service`, `breezy-capital-flow-pull.service`, `breezy-asos-refresh.service` (light, ≤ 1G, idempotent pulls);
  - `breezy-autonomy-producer-intraday.service`, `breezy-autonomy-alert-redeliver.service`, `breezy-autonomy-canary.service`;
  - `breezy-autonomy-selfheal-probe.service` (the drill target).
  - Studies over 1G are **excluded**: restarting them breaks the one-flock-holder memory rule.
- **Classification before restart (L-49):**
  - `MEMORY_CEILING_SUSPECT` (CPU/wall < 0.3 from `CPUUsageNSec` and the `ExecMainStart/ExitTimestampMonotonic` delta, or `MemorySwapPeak > 0`) and `OOM` (`Result=oom-kill`) are **never** restarted. Restarting into the same ceiling thrashes. They go to #22 ALERT with the triage line.
  - `NOFILE_EXHAUSTED` (journal `Too many open files` in the failed invocation) goes to ALERT.
- **Verification:** the next health pass reads `ActiveState`. A oneshot sits in `activating` while running (memory note `oneshot-units-are-activating-not-active`), so the pass waits until `ActiveState ∉ {active, activating}` and then requires `Result=success`. A failed restart ⇒ #22.
- **Drill target:** `breezy-autonomy-selfheal-probe` (Type=oneshot, timer weekly `Mon *-*-* 10:00:00 UTC`) runs `self_heal_probe_cli`.
  - If neither `evidence/self_heal/drill/<isoweek>.armed` nor `.consumed` exists: create `.armed`, print `SELF_HEAL_PROBE ARMED drill=true`, exit 1.
  - If `.armed` exists: rename it to `.consumed`, print `SELF_HEAL_PROBE HEALED drill=true`, exit 0.
  - Otherwise exit 0.
  - The probe touches nothing else, and its journal rows carry `drill=true`.

### 3.6 Delivery proof (G25, G26, Z13)

```python
@dataclass(frozen=True, slots=True)
class DeliveryProof:
    delivered: bool
    status_class: Literal["2xx", "3xx", "4xx", "5xx", "transport", "not_configured"]
    event: str
    ts_ns: int
    journaled: bool

def deliver_with_proof(sink: AlertSink, payload: AlertPayload, *, journal: DeliveryJournal,
                       attempt_kind: Literal["inline", "redeliver", "canary", "check"],
                       now_ns: Callable[[], int] = time.time_ns) -> DeliveryProof: ...
```

- **Branch selection:** if `sink` is a `WebhookAlertSink`, use it. If it is a `TeeAlertSink`, use the unique `WebhookAlertSink` in `sink.sinks`; every other branch receives the payload through `emit_alert` first, so the forensic log line is kept (the `TeeAlertSink` docstring rationale, `health.py:321-331`). Otherwise the result is `not_configured`, `delivered=False`.
- It calls `branch.emit(payload)` **directly**, never `emit_alert`, never the tee. It catches `Exception` only: `httpx.HTTPStatusError` maps to `status_code // 100`, other `httpx`/`ssl`/`OSError` errors to `transport`. Only the exception **type** is logged; messages embed the URL (`health.py:492-499`).
- **Journal (L-50 over ARCH §4.6's single jsonl file, contradiction C-6):** one file per attempt, `evidence/alerts/delivery/<YYYY-MM-DD>/<ts_ns>_<pid>_<sha8(payload)>.json`, schema `alert_delivery/v1`, files 0444, dirs 0700. Fields `{event, severity, site, ts_ns, delivered, status_class, attempt_kind, payload_sha256, component}`; no URL, no message, no detail text. A journal write failure never blocks delivery: it logs `alert_delivery_journal_unwritable` at ERROR with `journaled=False`.
- **Z13: route every CRITICAL through proof without touching 48 call sites.** `resolve_alert_sink` builds `TeeAlertSink(LoggingAlertSink(), JournalingWebhookAlertSink(url, journal=..., outbox=...))`. `JournalingWebhookAlertSink(WebhookAlertSink)` overrides `emit`:
  - it runs `deliver_with_proof(super-branch, ...)`;
  - on failure with `severity == "CRITICAL"` it writes the payload's four allowlisted fields to `evidence/alerts/outbox/<ts_ns>_<sha8>.json` (0400);
  - it then **re-raises** `AlertNotDeliveredError`, so `emit_alert` still contains it and logs exactly as today.
  - Every existing test of the tee's containment stays green unedited. `isinstance(branch, WebhookAlertSink)` holds.
- **Redelivery:** `breezy-autonomy-alert-redeliver` (every 5 min, own lock) drains the outbox oldest first through `deliver_with_proof(attempt_kind="redeliver")`. On 2xx it renames the entry into `outbox/delivered/`. An entry older than 24 h becomes an `abandoned` journal row plus #23 FAIL.
- **G26 fix:** `check_alerts_cli.check_alerts` replaces `sink.emit(payload)` (`:141`) with `deliver_with_proof(..., attempt_kind="check")` and returns `EXIT_DELIVERY_FAILED` iff `not proof.delivered`. The exit contract text (`:10-17`) becomes true.
- **Egress unchanged:** the only URL source stays `BREEZY_ALERT_WEBHOOK_URL` from `alerts.env` (G27). `test_autonomy_alert_egress_not_widened` (ARCH §4.7) pins it, plus an AST scan proving `alert_delivery.py` builds no client other than via `WebhookAlertSink`.
- **Sandboxed units:** `breezy-discovery-pull.service` has `ProtectHome=read-only`. Every unit that loads `alerts.env` and declares `ProtectHome=` or `ProtectSystem=strict` must also declare `ReadWritePaths=%h/.local/share/breezy/evidence/alerts`. Pinned by `test_every_alerting_sandboxed_unit_can_write_the_delivery_journal`.

### 3.7 Canary and off-host absence

- `breezy-autonomy-canary.service` (oneshot, `OnCalendar=*-*-* 15:45:00 UTC`, `Persistent=false`, own lock, `MemoryMax=128M`, `TimeoutStartSec=60`) sends `AlertPayload(severity="INFO", event="autonomy_canary", site="global", detail="canary_ok")` through `deliver_with_proof(attempt_kind="canary")`. It prints `AUTONOMY_CANARY delivered=<0|1> status_class=<c>` to stdout (journal; L-52 amendment) and exits 0 either way. Failure raises #23 and queues the payload in the outbox as CRITICAL `autonomy_canary_undelivered`.
- **Receiver absence rule (INFERRED; WP2 verify-first STOP).** A receiver-side rule must page when no `autonomy_canary` arrives by 16:15Z. WP2 step 1 records the receiver's capability as a yes/no plus the evidence class only, never the URL or host, in `docs/evidence/AUT6_RECEIVER_ABSENCE_RULE_<date>.md`.
  - **Path A (supported):** configure the rule receiver-side (no repo egress change), then prove it by the suppression drill below.
  - **Path B (unsupported):** add one dedicated heartbeat egress. One new key `BREEZY_ALERT_HEARTBEAT_URL` in the same 0600 `alerts.env`, read **only** by `autonomy_canary_cli` (AST scan), HTTPS-only with `_validate_webhook_url`, host pinned in a literal `HEARTBEAT_HOST_ALLOWLIST`. Re-pin `test_autonomy_alert_egress_not_widened`, `test_alerts_env_deploy.py` and `migrate-alerts-env.sh` in the same reviewed commit. Nothing else widens.
- **Suppression drill (live proof):** `autonomy_canary_cli --suppress-drill` is honoured only on dates listed in the literal tuple `CANARY_SUPPRESSION_DRILL_DATES` in `alert_delivery.py`, which is pre-registered in the reviewed commit. That run journals `attempt_kind=canary, delivered=false, status_class=not_configured, drill=true` and sends nothing. Evidence: the receiver's absence page timestamp, recorded as a C4 `HEALTH` verdict input hash plus a screenshot-free text attestation, and the absence of any canary row with `delivered=true` that day.

### 3.8 The five failing units (evidence 2026-10-03, read-only)

| Unit | Fact | Root cause | Fix (WP3) |
|---|---|---|---|
| `breezy-portfolio-roi.service` | `exit-code 1`, journal `PORTFOLIO ROI SKIPPED -- no score-live-trials success marker for 2026-10-02` (`portfolio-roi-run.sh:93-98`) | `score-live-trials` SKIPs by design for FQ (`score-live-trials-run.sh:177-179`, exit 0, writes no marker), so portfolio-roi fails every day: an expected failure. | `score-live-trials-run.sh` writes a sibling **skip marker** `<success-marker>.skipped` carrying the closed reason `composition_kind_has_no_scorer`. `portfolio-roi-run.sh` prints `PORTFOLIO ROI NO_INPUT -- upstream skipped: <reason>` and exits 0 when the skip marker exists; a genuinely missing marker stays exit 1 (a real upstream failure, then explained by #22). AUT-2 later supplies the FQ scorer (association, §5). |
| `breezy-discovery-pull.service` | `Result=timeout`; "13.858 s CPU over 30 min, 161.7M memory peak, 4G memory swap peak"; `MemoryHigh=128M`/`MemoryMax=256M`; clean on 09-27..10-01 | **L-49 signature** (CPU/wall = 0.008 < 0.3, swap peak > 0): reclaim throttling above `MemoryHigh`. **INFERRED** until WP3's verify-first step measures ΔRSS (L-49 amendment: fresh child, `ru_maxrss` over a post-import baseline) on a real run. | Size `MemoryHigh` to 1.5× the measured ΔRSS peak (provisional 384M) and `MemoryMax` to 2× (provisional 512M); `TimeoutStartSec=900`; move the timer 16:52Z → **17:12Z** to clear `[16:30Z, 17:10Z)` (§3.10); add to the self-heal allowlist (§3.5). |
| `breezy-parity-mem-1d.service`, `breezy-parity-mem-7d.service` | Transient (`/run/user/1000/systemd/transient/`), exit 1; reports in `~/.cache/breezy-gate/parity-mem-*.json`: `n_mismatches` 109,532 / 994,499; Takes batch 5 vs live 5 (1 d), **35 vs 38 (7 d)**; numeric mismatches 4 / 9 | Agent memory benchmarks (R3.1). Exit 1 means parity mismatch (`nbp_shadow_parity.py:946`), not a crash. The 7-d Take divergence is a **real signal**, so it becomes detector #16 rather than being dismissed. | Disposition in `docs/evidence/unit_health/DISPOSITION_failed_units_2026-10-03.md` (classification, cause, the parity numbers). One-time `systemctl --user reset-failed` of the four transient names at WP3 activation, logged. #16 tracks the signal. |
| `run-p814078-i21773018.service` (sixth, transient, not in README) | exit 2, `INVALIDARGUMENT`, 1.3 s | Agent ad-hoc parity run with bad arguments | Same disposition plus `reset-failed`. |
| `breezy-replay-backfill-0929.service` | Transient, exit 1 after 2 h 08 m, 10G peak (RuntimeMaxSec 3 h 15 m was effective: it ran as Type=simple) | One-time R3V-a backfill, superseded by "RESOLUTION 09-28" | Same disposition plus `reset-failed`. |

`jetbrains-remote-dev.service` and the `pressure-*` units belong to other projects and are out of scope (§3.9 scope rule).

**No unit fails as expected behaviour, structurally:**
- `test_every_wrapper_skip_path_exits_success` runs each `deploy/systemd/*-run.sh` skip branch under its existing wrapper-test harness and asserts exit 0, or a status listed in that unit's `SuccessExitStatus=` (the `replay-daily-run.sh` `exit 75` paths need `SuccessExitStatus=75` or exit 0; WP3 decides by reading the unit).
- At runtime the classifier marks any unit failing on 2 consecutive days with the same `(Result, ExecMainStatus)` as `EXPECTED_FAILURE_SUSPECT`. That is **unexplained by definition**, so a daily alert can never launder a structural failure.

### 3.9 Unit health: scope, classification, "unexplained"

- **Scope.** User units matching `^breezy-[a-z0-9@._-]+\.service$`, from `systemctl --user list-units --all --plain --no-legend --type=service` (argv list), plus transient `run-*.service` whose `Description` contains `/home/jon/breezy/` (the systemd-run default description is the command line). Read with `systemctl --user show <names> -p Id,LoadState,ActiveState,SubState,Result,ExecMainStatus,Transient,FragmentPath,InvocationID,NRestarts,CPUUsageNSec,MemoryPeak,MemorySwapPeak,ExecMainStartTimestampMonotonic,ExecMainExitTimestampMonotonic,TimeoutStartUSec`. This reuses `_default_cause_reader`'s subprocess convention.
- **Classes (`UnitFailureClass`):** `TIMEOUT`, `MEMORY_CEILING_SUSPECT`, `OOM`, `NOFILE_EXHAUSTED`, `EXIT_CODE`, `SIGNAL`, `TRANSIENT_ADHOC`, `EXPECTED_FAILURE_SUSPECT`, `STALLED_ACTIVATING`.
  - `STALLED_ACTIVATING`: a oneshot `activating` longer than 0.8 × `TimeoutStartUSec`. It is an early warning with no failure yet (memory note `long-runs-need-a-stall-watch`).
- **Journal.** `evidence/unit_health/<YYYY-MM-DD>/<ts_ns>_<unit>_<invocation8>.json`, one file per classification or action (L-50). Daily rollup `evidence/unit_health/day_<YYYY-MM-DD>.json` written by the first pass after 00:00Z.
- **Explained** means: for each failed `(unit, InvocationID)` seen that day, the journal holds (i) a classification row and (ii) an action row with proof. The proof is either a SELF_HEAL restart whose follow-up `Result=success` is journaled, or an ALERT whose `DeliveryProof.delivered=true` (inline or redeliver) is journaled. `TRANSIENT_ADHOC` is explained by (i) plus one delivered WARN. `EXPECTED_FAILURE_SUSPECT` is **never** explained.
- **The rollup field `unexplained_failed_units`** (int, plus a list of unit names) is the live-proof metric.

### 3.10 Slot table and runtime bounds

**Correction to ARCH §5.2, G29 and §10 (contradiction C-2).** systemd 259 `man systemd.service`: *"RuntimeMaxSec= … does not have any effect on Type=oneshot services … (use TimeoutStartSec= to limit their activation)"*. Every study and every timer-driven unit here is `Type=oneshot`, and all 19 already set `TimeoutStartSec` (effective values read live: 3–30 min). The binding rule therefore becomes:
- **R-a.** Every `Type=oneshot` unit declares `TimeoutStartSec` ≤ its slot.
- **R-b.** Every non-daemon `Type=simple|exec` unit, including transient `systemd-run` jobs, declares `RuntimeMaxSec`.
- **R-c.** Long-running daemons (`breezy-trade-supervisor`, `breezy-quote-tape`, `breezy-nws-ingest`) are exempt by a literal allowlist.
- **R-d.** No unit in `breezy-studies.slice` or holding the studies flock may have `[start, start + W + TimeoutStartSec)` intersect `[16:30Z, 17:10Z)`.
  - The original "ends before 16:30Z" cannot be met by the post-LAUNCH timers (family-tally 17:20Z, capital-flow 17:30Z, portfolio-roi 17:40Z), whose windows never touch STOP/LAUNCH (contradiction C-3).
  - Data-path units (quote-tape ingest every 15 min, which the node needs fresh at 16:50Z; AUT-1 territory) are exempt by literal allowlist.

These rules are pinned by `test_every_unit_has_an_effective_runtime_bound` and `test_no_study_window_intersects_stop_launch`, both parsing `deploy/systemd/*.service|*.timer`.

| Unit | Type | Schedule (UTC) | Lock / W | Bound | MemoryMax | Notes |
|---|---|---|---|---|---|---|
| `breezy-autonomy-producer-daily` (new) | oneshot | 05:30 | studies flock, `-w 300` | `TimeoutStartSec=1500` (ends ≤ 06:00, before the refit slot) | 3G (1-d parity peak 2G) | `breezy-studies.slice`, `OnFailure=breezy-study-failed@%n`, `LimitNOFILE=524288` (catalog reads) |
| `breezy-autonomy-producer-intraday` (new) | oneshot | `*:00/5` | own, `-n` | 240 s | 512M | through the launch window; own-lock autonomy unit |
| `breezy-autonomy-health` (new) | oneshot | `*:01/10` | own, `-n` | 120 s | 256M | SELF_HEAL executor and daily rollup |
| `breezy-autonomy-alert-redeliver` (new) | oneshot | `*:03/5` | own, `-n` | 120 s | 128M | outbox drain |
| `breezy-autonomy-canary` (new) | oneshot | 15:45 | own, `-n` | 60 s | 128M | off-host heartbeat |
| `breezy-autonomy-selfheal-probe` (new) | oneshot | Mon 10:00 | none | 30 s | 64M | drill target |
| `breezy-discovery-pull` (changed) | oneshot | **17:12** (was 16:52) | none | 900 s | 512M (provisional) | §3.8 |
| all other existing units | — | unchanged | unchanged | unchanged `TimeoutStartSec` | unchanged | verified against R-a..R-d by the new tests; only discovery-pull violates R-d today |

- **Own-lock autonomy units:** 512M + 256M + 128M + 128M + 64M = 1.09G, inside ARCH's 4G autonomy budget together with AUT-5's engine and dead-man.
- **Memory hazard (contradiction C-10):** the uncommitted `zz-memory-containment-TEMPORARY.conf` drop-ins set quote-tape-ingest `MemoryMax=14G`. With a 16G study holder that is 30G on a 30 GiB host with the node running, which breaks §5.2. Detector #24 alerts on it, and the disposition is AUT-1's (ingest ownership).

### 3.11 Dead-man (contradiction C-5)

ARCH §5 and §10 give `breezy-autonomy-deadman.timer` to AUT-5, while the brief lists it as AUT-6 mandate. AUT-6 does not build a second one (DRY). It provides:
1. the `deliver_with_proof` API the dead-man must use for its CRITICAL;
2. unit-health coverage of `breezy-autonomy-deadman.service`;
3. the off-host canary, which covers the case where the host itself is dead, something no on-host dead-man can see.

If AUT-5's plan omits the dead-man, AUT-6 r2 adopts it verbatim from ARCH §4.6.

### 3.12 Contract use (C1–C6)

- **C1:** consumes `DetectorEvent`, `EntryVeto`, `DecisionRecord` (`TrySubmit`, `p_hat`) and `source`/`drill` (canary and drill excluded from #13 and #14). Provides the `DetectorEvent` *producer objects* #4 and #5; AUT-1's writer serialises them.
- **C2:** consumes `admissible`, `slippage`, `fill_px`, `entry_ask`, `p_at_decision`, `settled_outcome` for #13–#15.
- **C3:** none, beyond reading the champion artefact (single-read) for #12.
- **C4:** produces `DRIFT` and `HEALTH` for every VERDICT id in §3.2.
- **C5:** consumes the resolver fold (subjects, bound artefact sha) and `registry/drill/marker.json`. Never writes.
- **C6:** provides `DriftDetectors` for `forecast_quantile_ladder` in both registries and the required-class gate test.

---

## 4. Work packages

**Gate commands, every WP, in the WP's own worktree:**
1. `PYTHONPATH=<tree>/src scripts/ci/run_tests_no_egress.sh` with the exact interpreter `/home/jon/breezy/.venv/bin/python`. Never `uv`/`pip` (L-51; memory note `worktree-needs-pythonpath`). Unit-launched gates pass `-p LimitNOFILE=524288` with basetemp on `~/.cache`.
2. `cd <tree> && lint-imports`, demanding the line "N kept, 0 broken" (memory note `python-m-importlinter-is-a-noop`).
3. The mypy ratchet `tests/unit/test_mypy_ratchet.py` inside the gate.
4. Read the gate EXIT before any push (memory note `read-gate-exit-before-push`).
5. Full gate after **every** merge (L-43).

Every new injectable seam gets one test that runs the production default (L-55). Every operator-visible line is asserted on stdout/journal, then checked in the journal after the first live run (L-52 amendment).

**Activation:** immediately on merge (memory note `activate-code-immediately`), unless stated. A unit-file change is `systemctl --user daemon-reload` plus `enable --now <timer>`, done by the implementer at activation. A supervisor-process code change needs a supervisor restart inside 01:00–16:40Z (memory note `supervisor-changes-need-a-supervisor-restart`). A node code change takes effect at the next 16:50Z LAUNCH.

### AUT-6.WP1 — Delivery proof (G25/G26/Z13). Wave 1, first

- **Scope:** §3.6.
- **Files:** `src/breezy/runtime/alert_delivery.py` (new); `src/breezy/runtime/health.py` (`resolve_alert_sink` construction only); `src/breezy/runtime/check_alerts_cli.py` (`:141` path); `src/breezy/runtime/alert_redeliver_cli.py` (new); `deploy/systemd/breezy-autonomy-alert-redeliver.{service,timer}` (new); `deploy/systemd/breezy-discovery-pull.service` (`ReadWritePaths` add); `pyproject.toml` (console scripts); `tests/unit/test_alerts_env_deploy.py` (add the new unit to its in-process-alerting list, an additive L-12 widening).
- **RED tests first:**
  - `tests/unit/test_alert_delivery.py::test_check_alerts_reports_not_delivered_through_the_production_tee`. **This is the G26 proof.** It calls `check_alerts` with **no** `sink_factory` (L-55), `env={BREEZY_ALERT_WEBHOOK_URL: <loopback https returning 500>}`, and asserts exit 3. It is RED today: the tee swallows the failure and the CLI exits 0.
  - `tests/unit/test_alert_delivery.py::test_deliver_with_proof_reports_non_2xx_through_tee` (ARCH §4.7 name): 500 → `delivered=False, status_class="5xx"`; 204 → `delivered=True`.
  - `::test_deliver_with_proof_reports_transport_failure_without_the_url` (the message is never logged or journaled).
  - `::test_deliver_with_proof_keeps_the_local_log_line`.
  - `::test_journal_is_one_file_per_attempt_and_hygienic` (no URL, no detail; 0444).
  - `::test_journal_write_failure_never_blocks_delivery`.
  - `::test_resolve_alert_sink_webhook_branch_journals_and_queues_criticals`.
  - `::test_noncritical_failure_is_journaled_not_queued`.
  - `::test_tee_containment_unchanged_with_journaling_branch` (runs the existing `test_alert_egress.py` scenarios against the new branch).
  - `tests/unit/test_alert_redeliver.py::test_outbox_drains_on_2xx_and_abandons_after_24h`.
  - `::test_redeliver_runs_the_production_default_once` (L-55).
  - `tests/unit/test_systemd_unit_contracts.py::test_every_alerting_sandboxed_unit_can_write_the_delivery_journal`.
  - `tests/unit/test_autonomy_envelope.py::test_autonomy_alert_egress_not_widened` (ARCH name; AUT-6 supplies the alert half).
- **GREEN:** all of the above pass; every existing `test_alert_egress.py`, `test_runtime_health.py` and `test_alert_webhook_delivery.py` test passes **unedited**.
- **Activation:** merge, then enable the redeliver timer. The node picks up the journaling branch at the next LAUNCH; the oneshots pick it up on their next run. Then run `breezy-check-alerts` once by hand-free invocation from the implementer's session; the journal shows an `attempt_kind=check` row with `delivered=true`.

### AUT-6.WP2 — Canary, absence rule, `alerts_undeliverable`. Wave 1, after WP1

- **Scope:** §3.7; detector #5; #23.
- **Files:** `src/breezy/runtime/autonomy_canary_cli.py`, `src/breezy/runtime/autonomy_node_detectors.py` (`AlertsUndeliverableDetector`), `deploy/systemd/breezy-autonomy-canary.{service,timer}`, and `docs/evidence/AUT6_RECEIVER_ABSENCE_RULE_<date>.md` (the verify-first record; Path B alone also touches `alerts.env` handling and its tests, §3.7).
- **Verify-first STOP:** step 1 establishes receiver absence-rule support (yes/no plus the evidence class). Path A or B is chosen on that evidence alone and written down before any code.
- **RED tests first:**
  - `tests/unit/test_autonomy_canary.py::test_canary_delivers_through_proof_and_prints_status`;
  - `::test_canary_failure_queues_critical_and_exits_0`;
  - `::test_suppress_drill_only_on_preregistered_dates`;
  - `::test_canary_runs_the_production_sink_default_once`;
  - `tests/unit/test_autonomy_node_detectors.py::test_alerts_undeliverable_vetoes_after_26h_without_canary_2xx`;
  - `::test_alerts_undeliverable_unarmed_before_first_canary`;
  - `::test_alerts_undeliverable_clears_on_next_2xx`;
  - `::test_detector_never_raises_and_reports_unknown_on_read_error` (L-16).
- **GREEN:** tests pass. The detector object is exported for AUT-5a wiring (§5).
- **Activation:** enable the canary timer. The first 15:45Z run shows `AUTONOMY_CANARY delivered=1` in the journal.

### AUT-6.WP3 — Unit health, the failing units, slot rules. Wave 1, parallel with WP2

- **Scope:** §3.8–§3.10, detectors #21, #22, #24 (classification and journal; restart in WP4).
- **Files:**
  - `src/breezy/runtime/unit_health.py`, `src/breezy/runtime/autonomy_health_cli.py`;
  - `deploy/systemd/breezy-autonomy-health.{service,timer}`;
  - `deploy/systemd/score-live-trials-run.sh` (skip marker), `deploy/systemd/portfolio-roi-run.sh` (NO_INPUT);
  - `deploy/systemd/breezy-discovery-pull.{service,timer}` (ceiling after measurement, 17:12Z, `TimeoutStartSec=900`);
  - `deploy/systemd/replay-daily-run.sh` or `breezy-replay-daily.service` (exit-75 disposition);
  - `docs/evidence/unit_health/DISPOSITION_failed_units_2026-10-03.md`;
  - `tests/unit/test_systemd_unit_contracts.py`.
- **Verify-first STOP:** measure discovery-pull ΔRSS per L-49 (fresh child, `ru_maxrss` over a post-import baseline, one real run under a memcapped `systemd-run --collect -p LimitNOFILE=524288`). If the peak does not explain the 10-02 stall, record the real cause before choosing ceilings.
- **RED tests first:**
  - `tests/unit/test_unit_health.py::test_classifies_low_cpu_wall_timeout_as_memory_ceiling_suspect` (fixture = the 10-02 discovery-pull `show` values);
  - `::test_classifies_portfolio_roi_repeat_exit1_as_expected_failure_suspect`;
  - `::test_transient_adhoc_scope_by_description`;
  - `::test_oneshot_activating_is_not_failed_and_stall_warns_at_80pct`;
  - `::test_expected_failure_suspect_is_never_explained`;
  - `::test_explained_requires_classification_and_proven_action`;
  - `::test_rollup_counts_unexplained`;
  - `::test_observe_units_runs_the_production_reader_once` (L-55, a fake `systemctl` on PATH);
  - `::test_unit_config_drift_detects_uncommitted_dropin`;
  - `tests/unit/test_portfolio_roi_run_no_input.py::test_skip_marker_gives_no_input_exit_0`;
  - `::test_absent_markers_still_exit_1`;
  - `tests/unit/test_score_live_trials_skip_marker.py::test_fq_skip_writes_skip_marker_with_closed_reason`;
  - `tests/unit/test_systemd_unit_contracts.py::test_every_unit_has_an_effective_runtime_bound`;
  - `::test_no_study_window_intersects_stop_launch` (RED today on discovery-pull 16:52Z);
  - `::test_every_wrapper_skip_path_exits_success`.
- **GREEN:** tests pass; the full gate stays green.
- **Activation:**
  1. Install and enable the health timer.
  2. `daemon-reload`.
  3. One-time `systemctl --user reset-failed breezy-parity-mem-1d.service breezy-parity-mem-7d.service breezy-replay-backfill-0929.service run-p814078-i21773018.service`, journaled in the disposition file.
  4. The next portfolio-roi run (17:40Z) prints `PORTFOLIO ROI NO_INPUT` and exits 0.
  5. The first `day_<date>.json` rollup shows `unexplained_failed_units=0`, or names what remains.

### AUT-6.WP4 — Self-heal executor and drill probe. Wave 1, after WP3

- **Scope:** §3.5, detector #21.
- **Files:** `src/breezy/runtime/self_heal.py`, `src/breezy/runtime/self_heal_probe_cli.py`, `autonomy_health_cli.py` (executor), `deploy/systemd/breezy-autonomy-selfheal-probe.{service,timer}`, and `src/breezy/persistence/autonomy/pins.py` (the membership tuple; ceilings stay ARCH-0's).
- **RED tests first:**
  - `tests/unit/test_self_heal.py::test_restart_refuses_non_allowlisted_unit`;
  - `::test_restart_uses_argv_list_no_shell` (Z15; AST);
  - `::test_restart_call_site_is_unique_and_argv_only` (AST over `src/`);
  - `::test_per_unit_daily_cap`;
  - `::test_memory_ceiling_and_oom_never_restarted`;
  - `::test_restart_deferred_when_it_would_intersect_stop_launch`;
  - `::test_verify_waits_out_activating_then_requires_success`;
  - `::test_alert_only_mode_without_policy_map`;
  - `::test_restart_runs_the_production_default_once` (a fake `systemctl` on PATH);
  - `tests/unit/test_self_heal_probe.py::test_probe_arms_fails_then_heals_once_per_week`;
  - extend ARCH's `test_self_heal_unit_allowlist_is_literal_and_excludes_trade`.
- **GREEN:** tests pass.
- **Activation:** enable the probe timer. The executor runs `ALERT_ONLY` until the AUT-5b ruling maps #21 to SELF_HEAL, after which the next Monday drill shows `SELF_HEAL_PROBE ARMED` → health restart → `SELF_HEAL_PROBE HEALED` within 10 min.

### AUT-6.WP5 — Detector catalogue, C6 plug-ins, node-local `permit_lapsed`. Wave 1, after ARCH-0 stubs

- **Scope:** §3.2, §3.3; detector #4.
- **Files:** `src/breezy/persistence/autonomy/detector_catalog.py`; `src/breezy/runtime/autonomy_node_detectors.py` (`PermitLapsedDetector`); FQ `drift_detectors` entries in `NODE_PLUGINS`/`OFFLINE_PLUGINS`; `src/breezy/analysis/nbp_drift.py` (moved predicates); `scripts/analysis/nbp_learning_nightly.py` (import the moved predicates, behaviour identical).
- **RED tests first:**
  - `tests/unit/test_detector_catalog.py::test_catalog_is_literal_only`;
  - `::test_every_live_kind_covers_required_detector_classes`;
  - `::test_node_local_ids_are_entry_veto_only`;
  - `::test_policy_detector_map_covers_catalog_exactly` (skips with a named reason until the ruling exists, then binds; the skip itself is asserted to be unreachable once `deploy/families/rulings/` holds an `autonomy-policy/v1` block);
  - `::test_every_action_class_has_at_least_one_detector`;
  - `tests/unit/test_autonomy_node_detectors.py::test_permit_lapsed_vetoes_after_expiry_and_alerts_only_in_b1_window`;
  - `::test_permit_none_is_unknown_not_lapsed`;
  - `::test_permit_lapsed_reads_value_never_the_permit_object_authority` (AST: no import of the permit issuer);
  - `tests/unit/test_nbp_drift_move.py::test_nightly_behaviour_identical_after_move`;
  - ARCH's `test_family_plugin_exact_set` stays green.
- **GREEN:** tests pass; `lint-imports` "N kept, 0 broken".
- **Activation:** none on its own; the detectors activate when AUT-5a wires the watch actor (§5).

### AUT-6.WP6 — Intraday producer. Wave 1, after WP5 and AUT-5a's resolver stub

- **Scope:** §3.4 (intraday); detectors #6, #7, #8, #18, #19.
- **Files:** `src/breezy/analysis/autonomy/producer_intraday.py`, `src/breezy/analysis/autonomy/drift_fq.py` (intraday half), `deploy/systemd/breezy-autonomy-producer-intraday.{service,timer}`, and `pins.py` (`PRODUCER_SOURCE_SHA256["aut6.intraday"]`).
- **RED tests first:**
  - `tests/unit/test_producer_intraday.py::test_node_liveness_requires_all_four_conjuncts` (process, log mtime, permit unexpired in window, tape advancing; each conjunct alone fails it);
  - `::test_node_liveness_window_closed_is_pass_with_metric`;
  - `::test_transient_veto_persistent_after_5400s`;
  - `::test_drill_inject_fail_on_marker_pass_on_absent` (Z2);
  - `::test_fee_probe_health_fails_without_running_line`;
  - `::test_shape_drift_reads_exec_store_readonly`;
  - `::test_subject_artefact_is_bound_sha_not_newest_row` (Z1);
  - `::test_validity_bounded_by_max_verdict_validity` (Z4);
  - `::test_write_on_change_or_near_expiry_only`;
  - `::test_policy_unavailable_writes_alert_with_assumption`;
  - `::test_never_takes_studies_flock`;
  - `::test_producer_refuses_when_unpinned`;
  - `::test_producer_runs_production_readers_once` (L-55);
  - `::test_payload_hygiene`;
  - supplies the producer half of `test_demotion_latency_slo`.
- **GREEN:** tests pass.
- **Activation:** enable the timer. The journal shows `PRODUCER_INTRADAY wrote=<n> skipped=<m>` every 5 min. The first in-window run writes a `aut6.node_liveness` PASS verdict.

### AUT-6.WP7 — Daily producer. Wave 2 (needs C2 labels for #13–#15)

- **Scope:** §3.4 (daily); detectors #9–#16, #20. #9–#12, #16 and #20 can merge in Wave 1; #13–#15 bind once AUT-2b labels exist.
- **Files:** `src/breezy/analysis/autonomy/producer_daily.py`, the rest of `drift_fq.py`, `src/breezy/analysis/shadow_parity_compare.py` (pure comparison moved from `nbp_shadow_parity.py`, which then imports it back), `deploy/systemd/breezy-autonomy-producer-daily.{service,timer}`, and `pins.py` (`"aut6.daily"`).
- **RED tests first:**
  - `tests/unit/test_producer_daily.py::test_forecast_drift_reuses_moved_predicate`;
  - `::test_persistent_escalation_2_of_3`;
  - `::test_feature_drift_psi_and_underpowered`;
  - `::test_calibration_live_excludes_canary_drill_and_inadmissible`;
  - `::test_calibration_live_underpowered_never_fails`;
  - `::test_station_day_clustering`;
  - `::test_fill_better_than_ask_is_halt_integrity`;
  - `::test_fill_slippage_underpowered_below_n_min`;
  - `::test_shadow_parity_judges_take_set_only`;
  - `::test_decision_starvation_uses_all_refused_predicate`;
  - `::test_daily_ends_before_refit_slot` (W + bound);
  - `::test_producer_daily_runs_production_readers_once`.
- **GREEN:** tests pass.
- **Activation:** enable the timer. The 05:30Z journal shows `PRODUCER_DAILY wrote=<n>` and ends before 06:00Z.

### AUT-6.WP8 — CRH-semantics wrappers resolve the champion (F9 residual). Wave 2, after AUT-5a's resolver

- **Scope:** `score-live-trials-run.sh:153-171`, `replay-daily-run.sh:127-146`, `decision-funnel-digest-run.sh:45-58` and `family-tally-v2-run.sh` read `BREEZY_SENDING_FAMILY_ID` from the static unit file. Under `BREEZY_FAMILY_SOURCE=registry` (AUT-5) the sender can be a child (`pm_us_crh_fq_v1_r0001` during AUT-7b), so they would key off the wrong family. They switch to AUT-5's read-only resolver CLI (`breezy-registry-champion --venue polymarket_us`, provided by AUT-5a). A resolver failure prints `<UNIT> SKIPPED -- registry_unavailable`, exits 0 and alerts via #22.
- **RED tests first:** in each existing wrapper test, `::test_wrapper_keys_off_registry_champion_not_unit_env`, plus `::test_registry_unavailable_skips_exit_0`.
- **Activation:** on merge (timers pick it up on their next run).

### AUT-6.WP9 — Live-proof report. Wave 1, after WP3

- **Files:** `scripts/analysis/aut6_live_proof_report.py`.
- **Behaviour:** reads `evidence/unit_health/day_*.json`, `evidence/alerts/delivery/`, C1 `EntryVeto` records, C4 verdicts and the C5 export (read-only). It writes `evidence/aut6/live_proof_<from>_<to>.json`: per day the qualifying flag (≥ 1 real fill or canary fill, ARCH §5.3), real fills, `unexplained_failed_units`, and per action class the first event with its artefact path hashes and log line.
- **RED tests first:** `tests/unit/test_aut6_live_proof_report.py::test_zero_fill_day_extends_window`, `::test_window_requires_5_real_fills_canary_excluded`, `::test_each_action_class_needs_a_live_path_event`, `::test_drill_events_tagged_and_counted_only_for_their_class`.
- **Activation:** none (it is a report).

---

## 5. Association

| Contract / interface | Direction | Exact item |
|---|---|---|
| C1 (AUT-1) | consume | `DetectorEvent`, `EntryVeto`, `DecisionRecord.kind ∈ {TrySubmit, Take}`, `p_hat`, `ask_px`, `source`, `drill`; capture file path convention `decisions/capture_<family_id>_<date>.jsonl` |
| C1 (AUT-1) | provide | `PermitLapsedDetector` and `AlertsUndeliverableDetector` emit `DetectorEvent(state=AGREE/DISAGREE/UNKNOWN)` through AUT-1's writer |
| C2 (AUT-2) | consume | `admissible`, `excluded_reason`, `slippage`, `fill_px`, `entry_ask`, `p_at_decision`, `settled_outcome`, `role` |
| C2 (AUT-2) | boundary | AUT-6 owns portfolio-roi's **exit semantics** (WP3); AUT-2 owns the FQ scorer that gives it input (contradiction C-9) |
| C4 (AUT-5) | provide | `DRIFT`/`HEALTH` verdicts for every VERDICT id; `metrics.cause_class` (Z10) |
| C5 (AUT-5) | consume | resolver fold (subjects, bound sha, Z1); `registry/drill/marker.json`; the resolver CLI (WP8) |
| Policy (AUT-5b) | consume | `detector_action_map` covering `CATALOG` exactly; `n_min` for #13; horizons |
| Watch actor (AUT-5a) | provide | the NODE_LOCAL detector objects; AUT-5a wires them into `RegistryWatchActor` and the per-kind `entry_veto` slot, since `app/trade.py` is AUT-5a-only in Wave 1 |
| Engine (AUT-5) | require | intraday engine timer at `*:02/5` (Z12 stagger); no `.path` unit; restrictive-only; ignores `_host/` verdicts |
| `pins.py` (ARCH-0/AUT-5) | provide | `PRODUCER_SOURCE_SHA256["aut6.intraday"|"aut6.daily"]`; `SELF_HEAL_RESTARTABLE_UNITS` members (§3.5); ceilings unchanged |
| AUT-1 | provide | `runtime/self_heal.restart_unit`, the one call site for AUT-1's recorder and feed self-heal |
| All areas | provide | `deliver_with_proof`; every autonomy CRITICAL goes through `resolve_alert_sink`'s journaling branch automatically |
| AUT-7 | provide | `DRILL_INJECT` detector in the live producer path (the AUT-7b DEMOTE step) |

**Order:**
1. **Wave 1:** WP1 → (WP2 ∥ WP3) → WP4; WP9 after WP3; WP5 after the ARCH-0 stubs; WP6 after WP5 and AUT-5a's resolver stub.
2. **Wave 2:** WP7 (label-bound detectors) and WP8.
3. **Live proof:** the DEMOTE and HALT classes need AUT-5b (ruling) and AUT-7b (drill), Wave 3.

**Parallel-safe sets:** {WP2, WP3, WP5} touch disjoint files. WP1 must merge first because every later WP's alert path depends on it.

---

## 6. Live-proof protocol

- **Artefact:** `~/.local/share/breezy/evidence/aut6/live_proof_<from>_<to>.json` (WP9), citing `evidence/unit_health/day_<date>.json`, `evidence/alerts/delivery/<date>/…`, C1 capture files, C4 verdict ids, the C5 export `evidence/registry/registry_polymarket_us_<date>.jsonl`, and node-log lines.
- **Window:** 7 consecutive **qualifying** days (ARCH §5.3: ≥ 1 real fill or a `source=canary` fill traversing production; zero-fill days extend the window), each with `unexplained_failed_units == 0`, with ≥ 5 real fills in the window.
- **Per action class, one live-path event:**

| Class | Event | Natural or injected | Expected cadence |
|---|---|---|---|
| ENTRY_VETO | `permit_lapsed` at permit expiry: C1 `EntryVeto(reason=permit_lapsed)`, cleared in the next boot; also AUT-1's `feed_stale` on a Nautilus 60 s idle close (memory note `nautilus-idle-timeout-trips-on-quiet-feed`) | natural | daily |
| ALERT | the 15:45Z canary with `delivered=true`, plus any detector ALERT with a journal proof row | natural | daily |
| SELF_HEAL | the Monday probe ARMED → restart → HEALED, `drill=true` (live executor, live systemd) | injected, live path | weekly, after AUT-5b maps #21 |
| DEMOTE | AUT-7b `DRILL_INJECT` → producer verdict → engine DEMOTE row → watch-actor veto (export plus node log) | injected, live path | once, AUT-7b clock ≥ 4 trading days |
| HALT | `fee_drift_probe` DISAGREE or `aut6.fill_better_than_ask` | **natural only** (see below) | unpredictable |

- **HALT honesty (contradiction C-4).** Both HALT detectors are TERMINAL or INTEGRITY. Injecting either on the live lineage would `terminal_frozen` it, or freeze the venue until an operator CLI clear, which is not an unattended action. So HALT has no schedulable live injection under Rev 3+Z.
  - **Proposed ARCH delta:** allow `DRILL_INJECT` to carry `declared_action_class=HALT` under the drill clause, treated by the engine as a RECOVERABLE drill HALT (no freeze, drill budget, RESUME next). AUT-7b would then exercise DEMOTE and HALT in two injections.
  - Until ARCH accepts this, HALT is "gate-proven (RED→GREEN), live by natural event only". **The area cannot claim 3 without either the delta or a natural HALT.**
- **Evidence class:** "machinery proven, edge unproven". No AUT-6 claim rests on an edge verdict.
- **ETA (given about 5 fills a day; zero-fill days extend):**
  - ARCH-0 ≈ 2026-10-08.
  - AUT-6 Wave 1 WPs merged ≈ 2026-10-16.
  - First unit-health / ENTRY_VETO / ALERT window ≈ 2026-10-17 → 10-23.
  - SELF_HEAL counts only after the AUT-5b ruling (≈ 2026-10-28), at the first Monday drill after it (≈ 2026-11-02).
  - DEMOTE via AUT-7b ≈ 2026-11-03 → 11-06.
  - **Full live proof ETA ≈ 2026-11-09**, provided the HALT delta is accepted. That leaves 11 weeks of margin before the 2027-01-25 KILL.

---

## 7. Score-3 verification checklist (independent scorer)

| Criterion | Check |
|---|---|
| (a) unattended | `git log --since=<window start> -- deploy/ src/breezy/runtime/alert_delivery.py src/breezy/persistence/autonomy/` shows no commit inside the window; every action row in `evidence/unit_health/` and `evidence/alerts/delivery/` carries `component` from a unit, not a CLI; the C5 export rows for DEMOTE carry `decided_by=engine` |
| (b) family-agnostic | `tests/unit/test_detector_catalog.py::test_every_live_kind_covers_required_detector_classes` and ARCH `test_family_plugin_exact_set` green at the window's sha; producers' subject loop reads the fold (`test_subject_artefact_is_bound_sha_not_newest_row`) |
| (c) fails closed | `test_detector_never_raises_and_reports_unknown_on_read_error`, `test_policy_unavailable_writes_alert_with_assumption`, `test_alerts_undeliverable_vetoes_after_26h_without_canary_2xx`, `test_memory_ceiling_and_oom_never_restarted`, `test_registry_unavailable_skips_exit_0` |
| (d) detected and alerted, delivery proven | for each day, `evidence/alerts/delivery/<date>/` holds an `autonomy_canary` row with `delivered=true`; `breezy-check-alerts` against a deliberately failing endpoint exits 3 (`test_check_alerts_reports_not_delivered_through_the_production_tee`); the outbox has no `abandoned` row in the window, or each is explained in the rollup |
| (e) RED→GREEN | each WP's merge commit plus its RED run log (failing test names) and GREEN gate log, cited by sha; the gate log ends in a pass with EXIT=0; `lint-imports` "N kept, 0 broken" |
| (f) live | `evidence/aut6/live_proof_<from>_<to>.json`: 7 qualifying days, `unexplained_failed_units=0` each day, ≥ 5 real fills; per class: ENTRY_VETO (C1 `EntryVeto reason=permit_lapsed`), ALERT (canary journal row), SELF_HEAL (journal `SELF_HEAL_PROBE ARMED` → restart row → `SELF_HEAL_PROBE HEALED`), DEMOTE (C5 export DEMOTE row citing a `DRILL_INJECT` verdict id, plus node-log `entry_veto reason=registry_not_champion`), HALT (natural event or, with the accepted delta, the drill HALT row) |
| No expected failures | `systemctl --user list-units --failed 'breezy-*'` empty at window end or each listed unit explained; `test_every_wrapper_skip_path_exits_success` green; journal `PORTFOLIO ROI NO_INPUT` on FQ days |
| Runtime bounds | `test_every_unit_has_an_effective_runtime_bound` and `test_no_study_window_intersects_stop_launch` green; `systemctl --user show breezy-discovery-pull.timer -p TimersCalendar` shows 17:12 |

---

## 8. Risks and failure modes

- **R-1 Alert storm or outbox growth.** Write-on-change verdicts and per-detector dedupe keep volume down. The outbox holds CRITICALs only and abandons them after 24 h; redelivery sends at most 20 per run.
- **R-2 Memory and the 30 GiB host.** Own-lock units total 1.09G; the daily producer is capped at 3G inside the studies flock. **C-10:** the TEMPORARY 14G ingest drop-in plus a 16G study exceeds the host. #24 alerts on it, and the disposition belongs to AUT-1. The nightly study must stop for the node, never the reverse (memory note `nightly-studies-run-at-10-24gb`).
- **R-3 Shared venv and concurrent agents.** Exact interpreter, no `uv` (L-51), no `git stash` (hook-blocked), per-agent scratchpads, `PYTHONPATH` per worktree, and worktrees fast-forwarded first (memory note `agent-worktrees-start-stale`). Unit tests use a fake `systemctl` on `PATH`, never the real one.
- **R-4 Self-heal causing harm.** Allowlist only light idempotent units; memory and OOM classes are never restarted; daily cap; the STOP/LAUNCH exclusion; `--no-block`; `ALERT_ONLY` until the ruling maps #21.
- **R-5 False DEMOTE from drift detectors.** Persistent variants only (2 of 3, 3 of 5); UNDERPOWERED never acts; an infrastructure cause never charges the resume budget (Z10). A false-positive DEMOTE that exhausts budget is an accepted, stated cost (Z20).
- **R-6 Shadow-parity baseline is dirty.** Live and batch disagree on 109,532 rows (1 d) and on Takes, 35 vs 38 over 7 d. #16 judges Take sets only and stays ALERT until 7 clean days, so it would page now. That is the right outcome (memory note `archive-table-train-serve-skew`), but the operator-free disposition goes to AUT-4/AUT-2 as a finding, not a silenced detector.
- **R-7 Statistical capacity.** About 5 fills a day and admissible n = 0 make #13 and #14 UNDERPOWERED for weeks. They exist and are wired, but they will not produce live events inside the window, and the live proof does not depend on them.
- **R-8 Receiver cannot do an absence rule.** Path B adds one pinned heartbeat egress as a reviewed change. This is the only way AUT-6 touches egress.
- **R-9 Journal on sandboxed units.** If `ReadWritePaths` is missing, the journal write fails while delivery still happens, and the gate test catches the unit before merge.
- **R-10 Supervisor restart window.** AUT-6 edits no supervisor code. Node-side changes land at LAUNCH.
- **R-11 KILL 2027-01-25.** If KILL fires TERMINAL, the venue has no sender (ARCH §5.3). Liveness #6 then reports `window=closed` and no subject, unit health and the canary continue, and fill-dependent windows pause.
- **R-12 Log-line dependence.** #6 and #18 parse node-log lines whose emitters and handlers are verified (permit line via the `breezy.app.trade.boot` handler, L-30; `FeeDriftProbeActor: RUNNING` via the Nautilus logger, present in the 10-02 log). The BREEZY-NWS subscribe error is whitelisted as cosmetic (memory note `breezy-nws-subscribe-error-is-cosmetic`).

---

## 9. Binding-constraint compliance

- **Nautilus immutability:** no Nautilus file or behaviour is touched. Node-local detectors are polled by a native `Actor` timer (AUT-5).
- **Caps:** no autonomy module reads or writes the operator-reserved controls (ARCH `test_autonomy_never_reads_or_writes_operator_controls` covers every AUT-6 module).
- **allow_short:** untouched; detectors only veto or report.
- **NO-SEND:** `test_execution_egress_firewall_guard` unchanged. Alert egress stays the single `alerts.env` key, pinned by `test_autonomy_alert_egress_not_widened`. The only conditional new egress (Path B) is allowlisted, host-pinned and reviewed, and widens nothing else.
- **Master enablement and permit:** `permit_lapsed` reads an expiry integer only (AST test). No AUT-6 code imports the permit issuer, the enablement env or the live-orders gate.
- **PREREG via ruling:** every action class comes from the AUT-5 policy ruling. `n_min` for #13 comes from the ruling, and the catalogue is a proposal.
- **Safety tests never weakened:** existing alert, egress, firewall, settlement and contract tests pass unedited. `test_alerts_env_deploy.py` gets an additive list entry only (L-12).

---

## 10. Self-score (author's estimate; an independent reviewer scores)

| Axis | Max | Score | Note |
|---|---|---|---|
| Fidelity | 20 | 18 | Consumes C1–C6 and Z1/Z2/Z4/Z10/Z12/Z13/Z15 unchanged. Ten contradictions stated (§11) rather than silently redesigned. |
| Correctness | 20 | 17 | Live facts verified: failing units, the systemd 259 `RuntimeMaxSec` semantics, the FQ fee probe running, G26. Still INFERRED: the discovery-pull cause and receiver support, each behind a verify-first STOP. |
| Specificity | 15 | 14 | Paths, ids, schedules, ceilings and test names given. |
| Acceptance | 20 | 16 | Every class has a live-path event except HALT, which depends on an ARCH delta (C-4). |
| Autonomy-safety | 15 | 14 | Restrictive-only, fail-closed, egress unchanged, self-heal bounded. |
| Reuse | 10 | 9 | Moves, never duplicates. |
| **Total** | **100** | **88** | |

## 11. Contradictions with ARCH / README (for the ARCH Rev 4+ merge)

- **C-1.** README AUT-6 says "the fee probe is not wired for FQ". This is stale. S6 wired it (`app/trade.py:828-844`), and it is live (`FeeDriftProbeActor: RUNNING`, 2026-10-02T20:55:26Z). F9's skip landed as `b58bb4c8`. The residual F9 risk is that the wrappers key off the static unit env, which is wrong under registry sourcing (WP8).
- **C-2.** ARCH §5.2, G29 and §10 say "`RuntimeMaxSec` on every study". This is a no-op for `Type=oneshot` (systemd 259 man), and every study is a oneshot already bounded by `TimeoutStartSec`. Replaced by rules R-a..R-d.
- **C-3.** "Ends before 16:30Z" cannot be met by the post-LAUNCH timers. Restated as "no intersection with `[16:30Z, 17:10Z)`", with data-path units exempt.
- **C-4.** HALT has no schedulable live injection (TERMINAL/INTEGRITY freeze). Proposed delta: a drill HALT via `DRILL_INJECT`.
- **C-5.** The dead-man is AUT-5's in ARCH §5/§10 but listed for AUT-6 in the brief. AUT-6 supplies delivery and watching only.
- **C-6.** The single `delivery_<date>.jsonl` with many writers conflicts with L-50. Replaced by per-attempt files.
- **C-7.** ARCH names no executor for verdict-mapped SELF_HEAL and ALERT. AUT-6's health unit and the producers execute them, `ALERT_ONLY` before the ruling.
- **C-8.** Z12: the `.path` unit does not see nested leaf writes. Dropped in favour of the timer stagger.
- **C-9.** README lists portfolio-roi under both AUT-2 and AUT-6. AUT-6 owns the exit semantics and AUT-2 the scorer.
- **C-10.** The uncommitted TEMPORARY drop-ins break the §5.2 memory budget.
