# Readiness audit — merged report, 2026-09-12 (HEAD e4848c3)

**Question.** Why does the build keep growing; what stops the system using its own capabilities end to end (ingress → backtest → validation → live execution); which gaps are true blockers; what exists but is disconnected; what is the minimum work before responsible live trading.

**Method.** Ten read-only seams on Claude specialists (Grok Build returned `402 Payment Required` on a 2-word probe at 12:21Z; the operator directed Claude-only for the session), each with file:line / log / store evidence; coordinator verification of every finding that changed a classification. Full gate run at HEAD: `scripts/ci/run_tests_no_egress.sh` → 8765 passed, 1 failed, 1 skipped, 4 deselected, 3 xfailed, 196 s. The failure is `tests/unit/test_app_trade_main_permit_logging.py:115` (bare substring "100" matched inside the epoch-ns timestamp; clock-dependent, not a defect).

**Ground truth measured today.** 8 days "LIVE"; 2 orders ever; 1 fill (09-11 SFO @0.22, via AMBIGUOUS→GET resolver → `feeReconciled: false`, residual by PREREG v3 §5); admissible n = 0 (`derived/family_tally_v2_pm_us_crh_v2_2026-09-11.md` row count 0); covered station-days 0/15 for 09-05..09-11 (`derived/covered_listed_station_days_2026-09-11.json`); demonstrated edge NONE (`derived/mb_current_rung_edge_2026-09-11.md` archive and live verdicts both UNDERPOWERED). Node pid 8453 (v2, hand-launched 02:26Z, tmux scope) runs beside supervisor pid 4061490 (unit; env `BREEZY_CONTINUOUS_RUNG_HOLD=1`, `BREEZY_CRH_CONT_PHASE0_SHADOW=0`); first v3 launch 16:50Z today.

## 1. Why the build keeps growing (ranked)

1. **Live before the fill chain was exercised.** Each real order exposed a new venue shape: 09-05 sub-cent fee + AMBIGUOUS classification (GL-1/GL-2); 09-11 four undeclared fields swallowed for five hours (L-37). The next surface, the execution object's key set, still has no drift allowlist (`src/breezy/adapters/polymarket_us/exec/reports.py:283-297`), and `fill_generation` still returns `None` silently when it cannot derive a cost (`exec/submit_chain.py:664-666`). Each incident produced a reactive batch (GL-1..GL-12).
2. **No forcing function.** The structural-dead KILL counter has read 0 for every station-day since D0, so no stop rule can fire and nothing forces a verdict.
3. **Scope beside the path.** Nine strategy modules are dead and unimported (forecast and lock families, built 08-28→09-01, 20 commits); Kalshi and LADDER_EV opened at n=0; five nightly timers run studies on settled-negative hypotheses (K1 dead ≥2c; candidate #2 "thin, not a GO").
4. **Ops surface.** 7 console processes, 10 units; ~35 manual interventions in 9 days; only 09-10 and 09-11 ran unattended end to end.
5. **Docs churn.** 267 of 584 commits since 08-20 are docs; several state documents contradict the code (§5).

## 2. Where the end-to-end chain breaks

| Hop | State | Evidence |
|---|---|---|
| Data ingress | Works (32 GB tape, recorder under systemd, NWS gate OPEN) but the coverage rule disqualifies a day on ANY gap overlap, and pre-d3f6c47 accounting wrote one gap row per subscribed instrument per reconnect | `structural_dead_stop.py:163-216`; byte-identical `started_ns` across LAX/MDW/MIA/SFO gap rows 09-10; 09-11 still 24–30 overlaps/station after 85faa02 |
| Backtest | Real tape→BacktestEngine→shipped v2 subclass→simulated IOC fill→ScoredTrial loop exists and ran (7e44abd: 12/12 CLEAN, 6/14 takes, 13 BLOCKED, NO VERDICT); v3 has no backtest-submitting subclass | `current_rung_hold_paper_replay.py:479`; `settlement/trial_scorer.py:150`, `roi_bound.py:100,190` |
| Strategy validation | Admissible n=0; both live fills arrived via the resolver path pinned residual by v3 §5 | tally reports; sqlite `exec/polymarket_us/fill/CEBPX0EVTTMX` |
| Live execution | Create-path `KIND_ACCEPT_FILL` (`submit_chain.py:838-851`) never fired on a real order; native reconciliation fed empty reports so the fill is re-inferred as `StrategyId("EXTERNAL")` each boot | `exec/client.py:1946-1973` (`return []` ×2); node log 2026-09-12T02:26:12.479Z inferred OrderFilled |

## 3. Classification

**BLOCKED** (prevents a verdict, or responsible unattended trading):

| # | Blocker | Evidence | Unlock observable |
|---|---|---|---|
| B1 | KILL clock cannot fire: any-overlap rule + feed-wide gap fan-out; shard-local fix (d3f6c47) in the running recorder since 09-12 09:00Z, unproven | `structural_dead_stop.py:163-216`; `score_live_trials.log` 20× "not covered" | count>0 for one station-day, or a tolerance ruling |
| B2 | Admissible n cannot grow on the observed fill path; the next fill is likely residual again via undeclared execution keys or the silent cost branch | `reports.py:283-297`; `submit_chain.py:664-666` | one create-path accept-fill; tally row count 1 |
| B3 | v3 hunt launches 16:50Z today with zero fill replay against tape | only `CurrentRungHoldBacktestStrategy` exists | one replay day producing v3 filled trials, or shadow first |
| B4 | Nothing reaches a human; the 09-11 lockout ran five hours unseen; 2/9 days unattended | `health.py:495-511` (`LoggingAlertSink`); env names of pid 4061490 | one delivered alert outside the log |

**NON-BLOCKING** (fix in order, or stop doing): reconciliation phantom + fee-unit disagreement (`record_venue_order_id` has zero production callers, `exec/client.py:346-348, 2253-2267`; durable fee "0" vs inferred commission 0.01); `DailySpendLedger` in-memory by documented design (`operator_controls.py:252-265`, durable per-day bound = trial-day latch × per-position cap); exec-store single-path discipline; `BREEZY_ORDERS_ENABLED` read once at boot; nightly 16G units unserialized (k1 SIGTERMed at 17.6 GB 09-11 22:32Z inside the Pacific window); park Kalshi, LADDER_EV, forecast ingest, whole-tape tooling, G-16/G-17; debt (flaky permit test; `ruff format --check` 268 files and mypy 433/41 files in tests+scripts vs PROGRESS 31/313; stale docstrings; `deploy/systemd/README.md` "NOT ACTIVATED"; GO_LIVE_BLOCKERS lists GL-1/GL-4 open). The three session ceilings absent from the supervisor env are BY DESIGN (`safety.py:552-608, 685-691`).

**READY** (proven live unless noted): venue auth, exec connect, native reconciliation, permit mint; eight-gate `_submit_order` chokepoint (`exec/client.py:2647-2716`), ledger, native RiskEngine cap (`node_config.py:565-622`), intent latch, family halt, GET-only read signer; resolver backoff (`exec/client.py:1241-1259`); GL-3 refuse-without-consume (`strategy.py:534-540`); supervisor daily cycle (PASS 09-10, 09-11); recorder with memory ceilings; NWS ingest; scorer/tally/boundary artefact; gate green on money-path modules (zero mypy errors under adapters/runtime/strategy).

## 4. Built but disconnected / unvalidated / misconfigured

`record_venue_order_id` (zero prod callers); `generate_fill_reports`/`generate_order_status_reports` return `[]`; `WebhookAlertSink` never constructed; v2 backtest-only subclass pattern not applied to v3; expectancy pipeline exists while PROGRAMME_PATH says ROI unobtainable (the limit is power); `_has_durable_fill_record` stub; `PositionReportingLag` no producer; `exit_guard.py` no actor; `never_substitute`, `is_record` no consumers; native `max_order_submit_rate` default; truncation records advisory only; `QuoteTapeDiskMonitor`/gap paths never reach the shared alert sink.

## 5. Doc-vs-reality contradictions

PROGRESS "at 4 covered/day the 15th lands 09-11" vs count 0; PROGRESS CF-11/CF-12 counts; `deploy/systemd/README.md:5-6` "PREPARED, NOT ACTIVATED" vs 20 active units; PROGRAMME_PATH "R-5R venue-gated" vs exec spine landed; GO_LIVE_BLOCKERS GL-1/GL-4 shown open; BLIND_RISK_VIEWS "strategies=[]" and "permit unwired" (false at HEAD); `native_reuse_audit_2026-09-01.md` §5/§6 stale (fixed); docstrings in `exec/client.py:1966-1972`, `position_reporting_lag.py:8-16`, `operator_controls.py` "ZERO PRODUCTION CALL SITES"; R8 runbook :532 "CRITICAL alert fires" (log-only).

## 6. Shortest path (the backlog replacement, `docs/core/PROGRESS.md` 2026-09-12)

1. Stop adding scope: disable/serialize settled-negative timers; park Kalshi, LADDER_EV. 2. Launch decision for v3 (shadow flag exists). 3. Exec hardening (execution-key allowlist; silent cost branch). 4. Reconciliation (venue-id map; durable fill reports; fee-unit ruling under v3 §5.3). 5. v3 backtest-only subclass + one clean-day replay. 6. Coverage observation under shard-local recorder; tolerance ruling if still 0. 7. Alert sink. 8. Free hygiene. Then accumulate: at the observed take rate the first look (n=10) is weeks away, a verdict (n=60..160) months away.

## Appendix — per-seam findings (verbatim tables from the ten investigators)

### S1 Execution spine (trading-bot-architect)
Verdict: PROVEN LIVE only up to a fee-unreconciled residual fill via AMBIGUOUS→resolver→GET; the create-path `KIND_ACCEPT_FILL` branch (submit_chain.py:838-851) has never fired on a real order. `_EXECUTION_KEYS` (reports.py:283-297) has no drift allowlist unlike `_ORDER_KEYS`/`_USER_POSITION_KEYS`/`_MARKET_METADATA_KEYS`. `record_fill` PROVEN LIVE (sqlite fill + index keys). `score_live_trials`→parquet never on a counted fill (store holds only provenance.json + one 09-05 unresolved take). `_has_durable_fill_record` stub `return False` (client.py:1128-1131). Permit expiry enforced (safety.py:70,474,918; app/trade.py:311-382); only mint site is boot. No blanket `except Exception` in submit_chain/reports/signing.
Minimum: (1) `_EXECUTION_DRIFT_ALLOWED_KEYS` mirroring `_ORDER_DRIFT_ALLOWED_KEYS`; (2) drive one create-path accept-fill through record_fill→score_live_trials (parquet row, tally n≥1); (3) real fill-store probe or documented GET-only design.

### S1b Silent failures (silent-failure-hunter)
| # | Finding | Class | Status | Evidence |
|---|---|---|---|---|
| 1 | `fill_generation` returns None silently when `_filled_cost_from_execution` can't derive a cost; no append to `errors` | BLOCKER | UNIT-ONLY guard, branch untested | submit_chain.py:664-666 |
| 2 | No `BREEZY_ALERT_WEBHOOK_URL` anywhere; every CRITICAL resolves to the logging sink | BLOCKER (unattended) | PROVEN LIVE | health.py:503 gates `WebhookAlertSink` |
| 3 | `_has_durable_fill_record` hardcoded False; `STARTUP_FILL_RECORD_MATCH` self-heal dead | DEBT (fails safe) | STUB | client.py:1128-1131; submit_intent.py:438-474 |
| 4 | `QuoteTapeDiskMonitor` and `_open_tape_gap`/`_close_tape_gap` never call `emit_alert` | DEBT | design | quote_tape_disk_monitor.py:93-100; data.py:2084-2094 |
| 5 | Resolver "GET vs positions disagree" stays AMBIGUOUS with WARN only; escalation is the 15-min stale CRITICAL (log-only) | DEBT | PROVEN LIVE | client.py:1472-1478; component_health_watch.py:198-230 |
| 6 | Resolver retry storm fixed: 5→300 s backoff; pre-fix 4,044 tight retries | fixed | PROVEN LIVE | client.py:1241-1259 |

### S2 Strategy and edge (prediction-market-reviewer)
| # | Finding | Class | Status | Evidence |
|---|---|---|---|---|
| 1 | Admissible n=0 despite a real fill: resolver-path fills `fee_unreconciled` by construction | BLOCKER | PROVEN LIVE | v3 §5; tallies 09-11 |
| 2 | Structural-dead counter 0 for a week; only clock/dollar halt bound the family | BLOCKER | PROVEN LIVE | covered_listed_station_days_2026-09-11.json; structural_dead_stop.py:158-216 |
| 3 | No prior positive-expectancy evidence; archive and live verdicts UNDERPOWERED | BLOCKER for any edge claim | descriptive join | mb_current_rung_edge_2026-09-11.md:475-489 |
| 4 | 09-11 node: 3 observation_ambiguous, 2 edge_below_break_even, 1 illegal_cell, 0 clean takes in ~10 h | informational | PROVEN LIVE | node log grep |
| 5 | GL-3 fix present and predates the 09-11 node | conformance | PROVEN LIVE | strategy.py:534-540; commit 14d27fb |
| 6 | Only `current_rung_hold` imported by production | DEAD (others) | import graph | trade.py:42-52; composition.py:42-52,158-200 |
| 7 | v3 §12: items 1,3,4,5,6,8 named GREEN-shaped tests; 2,7,10 dedicated files; item 11 (re-arm gate evidence-based) no dedicated test found | DEBT | UNIT-ONLY | test names |
| 8 | Kalshi manifest DRAFT, d0 2099, zero sha — inert | stub | by design | deploy/families/kalshi_crh_v1.json |
Fee coefficient 0.06 at config.py:226; BE = ask + fee in settlement/current_rung_hold_v2.py:71-79. demonstrated edge: NONE.

### S3 Data ingress (mle-reviewer)
| # | Finding | Class | Status | Evidence |
|---|---|---|---|---|
| 1 | `covered_listed_station_days` requires zero resolved-gap overlap in [12:00,17:00) LST; count=0 for 7 days | BLOCKER | PROVEN LIVE | structural_dead_stop.py:163-216; score_live_trials.log |
| 2 | Pre-d3f6c47 feed-wide fan-out: identical-timestamped gap rows across all instruments | BLOCKER (root cause) | PROVEN LIVE | parquet: `seq=2 started_ns=1789071381126175558` identical across LAX/MDW/MIA/SFO 09-10 |
| 3 | Overlap counts (instance,instrument,seq collapsed): 09-08 72/90/72/72; 09-09 96/12/12/96; 09-10 450/198/126/450; 09-11 30/30/24/30 (post-85faa02) | measurement | PROVEN LIVE | custom_quote_tape_gap parquet |
| 4 | d3f6c47 in the RUNNING recorder (commit 03:31:53Z < start 09:00:38Z; editable install) | resolves #2 forward | PROVEN LIVE | git log; systemctl show |
| 5 | Even after both fixes, 09-11 overlap >0 everywhere; no covered afternoon yet observed | BLOCKER (unresolved) | UNVERIFIED | derived from #3 |
| 6 | SFO 09-08 has 3 TRUNCATED files; truncation invisible to coverage | DEBT | PROVEN LIVE | mb report :11 |
| 7 | `data/order_book_depths` ingest ~62 min behind live | ok | PROVEN LIVE | epoch mtimes |
NWS final delivery per station NOT verified.

### S4 Backtest/replay (code-explorer)
| # | Finding | Class | Status | Evidence |
|---|---|---|---|---|
| 1 | v3 `ContinuousRungHoldStrategy` has no backtest-submitting subclass; only one in-engine unit test | BLOCKER | STUB | current_rung_hold_paper_replay.py:479; tests/unit/test_current_rung_hold_paper_replay.py:356 |
| 2 | v2 whole-tape replay underpowered (13 BLOCKED, 6/14 takes; `MIN_NON_EXCLUDED_N=30`) | BLOCKER for a verdict | PROVEN LIVE | PROGRESS:114; roi_bound.py:100,190 |
| 3 | 09-01..09-10 tape mostly unusable for per-tick replay (60 s idle timeout; fixed 85faa02) | DEBT | PROVEN LIVE | PROGRESS:71 |
| 4 | naive/realistic conditions are forecast-family machinery, unused by any live decision | OVERENGINEERING | UNIT-ONLY | run_weather_strategy_backtests.py:380-388 |
| 5 | `BacktestOrderGuard` real, wired, mechanics-only | ENHANCEMENT | PROVEN LIVE | backtest_order_guard.py:130,396; backtest_harness.py:1005 |
Contradiction: PROGRAMME_PATH "unsatisfiable by backtest" is unscoped; for CRH a taker-IOC-on-Depth10 expectancy pipeline exists (trial_scorer.py:150; roi_bound.py:173); the limit is power.

### S5 Risk controls (security-reviewer)
| # | Finding | Class | Status | Evidence |
|---|---|---|---|---|
| 1 | Ledger/latch/flock all key off `store_path`; a second process on a different path spends an independent budget | hardening | UNIT-ONLY | operator_controls.py:252-373; submit_intent.py:534-558 |
| 2 | Ledger restart persistence — VERIFIED by coordinator: in-memory by documented design | note | — | operator_controls.py:252-265 |
| 3 | Settlement-as-exit bypass documented, no actor | DEBT | DEAD | settlement/exit_guard.py:1-30 |
| 4 | NO-SEND firewall test-only (`unshare -r -n`); production egress is code discipline | DEBT | UNIT-ONLY | tests/conftest.py:83,90 |
| 5 | `_submit_order` 8-gate chokepoint then ledger→arm→sign→POST | ENFORCED | PROVEN LIVE | exec/client.py:2647-2716 |
| 6 | Native `RiskEngine.max_notional_per_order` configured `bypass=False`, per slug, derived from position cap | ENFORCED | TESTED | node_config.py:565-622; test_native_order_cap_wiring.py |
| 7 | Native caps inert until AccountState cached; ordering pinned | ENFORCED | TESTED | test_risk_engine_ordering_enforcement.py |
| 8 | Read/write signers disjoint `{GET}`/`{POST}` | ENFORCED | TESTED | signing.py:84; write_transport.py:54,119-124 |
| 9 | Family halt on 2nd genuine fill, no-await veto | ENFORCED | TESTED | trial_day_latch.py:469-527; exec/client.py:2679-2691 |
| 10 | `BREEZY_ORDERS_ENABLED` read once at boot | ENHANCEMENT | boot-only | order_enablement.py:197-201 |
| 12 | Single-entry hold-to-settlement by design; no exit/flatten path | DEBT (policy) | DEAD | strategy.py; exit_guard.py |

### S6 Operations (Explore)
Day table 09-04..09-12 and findings: 2/9 unattended (09-10, 09-11); ~35 interventions; `BREEZY_ALERT_WEBHOOK_URL` absent (health.py:495-511); no `Conflicts=` between mb-daily 13:30Z / k1 22:30Z / offer-gate 22:45Z at `MemoryMax=16G`; k1 SIGTERMed at 17.6 GB 09-11 22:32Z + 2 hand reruns; `KillMode=process` orphans ("left-over process 3196952" ×2 on 09-12); supervisor log carries unit-test output (lines 1–168, fixed b417d68); duplicated supervisor 09-06; quote-tape-ingest fails every run on non-disjoint intervals (journal 2026-09-12T12:31:33 `quote_tick=failed order_book_depths=failed`), no alert; STOP_PRIOR will correctly SIGTERM the hand-launched pid 8453 (flock holder verified). S6's "missing three cap vars" finding is NOT a gap — derived by design (safety.py:552-608, 685-691).

### S7 Tests and gates (pr-test-analyzer)
Gate summary above. Money-path coverage map: permit mint / intent / ledger / submit classify / resolver / record_fill / on_order_filled / latch / scorer / tally all pinned by SYNTHETIC fixtures; CAPTURED provenance only for signer (write-signing probe) and fill-parse drift allowlist (exec shape evidence). GL-9 resolved by `tests/contract/test_live_fill_scoring_chain_contract.py` (schema-shaped body). No integration test composes the real trade node with an exec client (`test_trade_node_lifecycle_contract.py:139,211` registers zero exec clients). Static: ruff 24 errors; `ruff format --check` 268 files; mypy 433 errors / 41 files, all in tests/ and scripts/analysis. 4 `venue_live` tests deselected by addopts; last real run date unknown.

### S8 Scope (trading-bot-architect)
Classification: BLOCKER = tape coverage accounting, v3 first-hunt verification; landed-watch = GL-1/2/3/9 + L-37; ENHANCEMENT = CF-5b, CF-8, CF-13, R-7 residue, T-9; DEBT = CF-1, CF-4, CF-6, CF-7, CF-11, CF-12, PF-1, T-6, `max_simultaneous_positions`; OVERENGINEERING = CF-2 (`sites.py:213-227`, zero consumers), G-16/G-17, PREREG v2 residue; UNNECESSARY now = Kalshi sibling, LADDER_EV. Dead inventory: 9 strategy modules with zero imports from app/runtime; `ladder_ev` stage-1 only; `kalshi_crh_v1.json` DRAFT; K1 and 5 `cli_basis_*` scripts still on active timers. Minimum-scope: daily launch (done); ≥15 covered station-days with shard-local accounting (open); create-order outcomes without silent swallows (landed, unproven vs a 3rd drift); a real fill persisting to a scoreable trial (landed, unexercised on an admissible fill); tally applying the v3 stop rule (landed).

### S9 Nautilus native reuse (code-architect)
| # | Finding | Class | Status | Evidence |
|---|---|---|---|---|
| 1 | Native reconciliation fed empty order/fill reports; the live fill re-inferred as EXTERNAL each boot | fix before trusting books | PROVEN LIVE | exec/client.py:1946-1973; log 2026-09-12T02:26:12.478Z "0 orders, 0 fills" → :12.479Z inferred OrderFilled |
| 2 | `record_venue_order_id` zero production callers; no `venue_id/*` rows | fix before trusting books | DEAD | exec/client.py:346-348,2253-2267 |
| 3 | Fee disagreement: durable `cumulativeFee "0"` vs inferred `commission=0.01` | L-2 unit change | PROVEN LIVE | sqlite; log |
| 4 | Stale docstrings: client.py:1966-1972; position_reporting_lag.py:8-16; operator_controls.py "ZERO PRODUCTION CALL SITES" | DEBT | — | vs factories.py:777 |
| 5 | `PositionReportingLag` zero producers | OVERENGINEERING | DEAD | position_reporting_lag.py:41 |
| 6 | Native `max_notional_per_order` covers declared slugs only | DEBT | PROVEN LIVE | node_config.py:584-592,619-621 |
| 7 | `max_order_submit_rate` default 100/s | ENHANCEMENT | STUB | risk/config.py:42-43 |
Genuinely absent natives (verified with positive controls): supervisor restart hook, `BacktestOrderGuard` on CASH, time-dimensioned budget, fee-exclusive trial scoring, signed-header reconnect. Native `open_check_interval_secs`/`position_check_interval_secs` deliberately None (contract-pinned) ⇒ no continuous position-drift detection between boots. Prior audit §5/§6 findings fixed at HEAD.
