I'll gather read-only evidence only: suite inventory, gate logs, and the risk pins. No file edits and no full-suite run.Collection without the egress sandbox is refused by the N2 barrier. I'll collect inside the CI network namespace and scan the gate logs for outcome counts.# Test-architecture evidence (read-only)

HEAD `60290e9d` on `emdash/refactor-y4qj4`. No files changed. Codegraph failed (`attempt to write a readonly database`); navigation is grep/read. **Collection and targeted pytest did not run.** Unsandboxed `pytest --collect-only` exited 2 at barrier N2 (`tests/conftest.py:379`). The CI wrapper exited 3: `bwrap` and `unshare -r -n` both return EPERM in this agent (`kernel.unprivileged_userns_clone = 1` is not sufficient). N3 refuses a bare `BREEZY_TEST_OS_EGRESS_BLOCK=1`. pytest 9.1.1; `pytest_randomly` imports [CONFIRMED].

Operator wall-clock 22.7–25.4 min / RSS 1.8–2.3 GB is **cited, not re-measured**.

## (A) Measured inventory

| Quantity | Value | Tag |
|---|---|---|
| `src/breezy` | 270 files, **114,076** LOC | MEASURED |
| `tests/**/*.py` | 626 files, **300,560** LOC | MEASURED |
| `tests/unit` | 522 / **273,256** | MEASURED |
| `tests/contract` | 39 / **12,964** | MEASURED |
| `tests/integration` | 17 / **5,146** | MEASURED |
| `tests/strategy` | 31 / **6,340** | MEASURED |
| `tests/live` | 5 / **619** | MEASURED |
| `tests/support` | 9 / **1,703** | MEASURED |
| `tests/fixtures/**/*.py` | **0** (data dirs only: `nws`, `nbm`, `venue`, `kalshi`, `iem`, …) | MEASURED |
| Test LOC / src LOC | **2.63** (unit alone **2.40**) | MEASURED |
| AST `def test_*` | **11,249** | MEASURED |
| Literal `@parametrize` product | **12,670** | MEASURED expansion |
| Non-literal parametrize decorators | **139** (not expanded) | MEASURED |
| Collected items | **unknown** | BLOCKED |
| Files >1,500 LOC | **34** (>1,000: 57) | MEASURED |

**Ten largest** [MEASURED]: `test_trade_supervisor.py` 7026, `test_current_rung_hold_ambiguous_resolver.py` 6989, `test_portfolio_roi_report.py` 5381, `test_polymarket_us_exec_client.py` 5180, `test_execution_egress_firewall_guard.py` 4311, `test_polymarket_us_submit_order_chain.py` 3147, `test_current_rung_hold_paper_replay.py` 2845, `test_polymarket_us_readonly_guard.py` 2565, `test_continuous_rung_hold_fill_wiring.py` 2382, `test_current_rung_hold_trial_day_latch.py` 2373.

**Markers** are decorator/module-`pytestmark` counts on test functions, not collected items [MEASURED]:

| Marker | Test funcs | Notes |
|---|---|---|
| `contract` | 268 | Includes a few `tests/unit` marks. **10 modules under `tests/contract/` have no mark** (below). |
| `allow_socket` | 73 | |
| `live` | 5 | Deselected by `addopts`. |
| `venue_live` | 3 | |
| `memory` | 3 | `test_extend_dedupe_filtered.py` |
| `slow` | 1 | `test_census_column_scan_memory.py:224`. Not deselected by `addopts`. |
| `replay` | **0** | Declared in `pyproject.toml`; no use. |
| `real_money` | 0 seen | |

**Mocks** [MEASURED, single-line AST]. 932 test functions mention `monkeypatch` / `unittest.mock` / `MagicMock`. Import-resolved `setattr`/`patch`:

| Bucket | Tests |
|---|---|
| Breezy-internal only | 182 |
| Boundary only (`nautilus*`, `socket`/`os`/`time`/…) | 36 |
| Both | 4 |
| Instance / unresolved name | 195 |
| Mock used, no single-line setattr matched (`setenv`, multiline, bare `MagicMock`) | 502 |

Sites: 172 internal setattr, 42 `"breezy.*"` strings, 57 of those patch a `_private` attr, 91 private attrs on unresolved instances, 55 boundary setattrs. **Not a precise internal-vs-boundary ratio** — most patches hit a local object [CONFIRMED].

**Engines** [MEASURED, token presence, not runtime weight]: files — `TestClock` 68, `test_kit` 55, `BacktestEngine` 24, `TradingNode` 22, `BacktestNode` 3; union **119** files (unit 80, contract 19, strategy 9, integration 8). Test functions whose own body names one of these: **116**. Fixtures hide more [HYPOTHESIS].

**Hypothesis library** imports in **8** files; **9** `@given` tests [MEASURED]. No hypothesis block in `[tool.pytest.ini_options]` [CONFIRMED].

| Test | max_examples | deadline |
|---|---|---|
| `test_polymarket_us_shape_capture.py` report | 200 | unset |
| `test_normalize_cli_parse_fuzz.py` | 200 | `None` |
| `test_quote_tape_ingest_deadline.py` | 200 | `None` |
| `test_current_rung_hold_monitor_decision.py` (2) | 100 | unset |
| `test_lst_margin_horizon.py` | 60 | unset |
| `test_polymarket_us_signing.py` SDK oracle | 40 | `None` |
| `test_polymarket_us_discovery.py`, `test_current_rung_hold_trial_day_latch.py` | unset | unset |

Unset `deadline` uses Hypothesis’s default (200 ms) [HYPOTHESIS, library default, not observed failing].

## (B) Framework-duplication

`tests/contract/` is the pin set. Docstrings that say “failure means Nautilus moved” are valuable. A directory name is not a mark.

**Valuable pins (keep, run on a Nautilus bump)** [CONFIRMED from module docs]:

| File | What goes red |
|---|---|
| `test_catalog_nws_records.py` | Custom-data Parquet round-trip + Breezy strict decode. Not a retest of Nautilus types alone. |
| `test_catalog_write_interval_contract.py` | `ts_init` interval `_persist_batch` depends on. |
| `test_backtest_instrument_registration.py` | `add_data` registers only `data[0]`’s instrument. |
| `test_risk_engine_ordering_enforcement.py` | Caps are inert until `AccountState` (`engine.pyx` early `return True`). |
| `test_nautilus_cache_durability_contract.py` | Cache is memory-only without Redis; justifies `sqlite_store`. **Unmarked.** |
| `test_native_live_expiry_path_absence.py` | No live instrument-expiry path. |
| `test_persistence_pyo3_catalog_decline.py` | Decision not to use the pyo3 catalog. |
| `test_persistence_streaming_replay.py`, `test_quote_tape_streaming_contract.py`, `test_quote_tape_ingest_native_pin.py` | Streaming/chunk/mirror facts that fail silently on a bump. |
| `test_live_timer_thread_affinity.py` | Where a `LiveClock` callback runs. |
| `test_reconciliation_settlement_price_hazard.py` | What Nautilus books when a settled position is reported flat. |
| `test_native_order_cap_wiring.py` | Breezy `RiskEngineConfig` actually caps a real engine. |

**Breezy behaviour hosted on a real engine (keep, but they are the slow tier)** [CONFIRMED by docstring]: `test_account_presence_halt_contract.py`, `test_exec_client_reconciliation_contract.py`, `test_exec_client_wiring_contract.py`, `test_trade_node_lifecycle_contract.py`, `test_node_composition_contract.py`, `test_backtest_harness_stop_gate.py`, `test_multi_instrument_weather_strategy.py`. These are not redundant framework tests. They are heavy.

**Unmarked `tests/contract/` modules** — missed by `-m contract` [CONFIRMED]: `test_nautilus_cache_durability_contract.py`, `test_current_rung_hold_wiring_contract.py`, `test_forecast_source_liveness_contract.py`, `test_ingest_backlog_drain.py`, `test_instrument_leg_layer_agreement_contract.py`, `test_mechanism_test_ineligibility.py`, `test_no_leg_settlement_sign_contract.py`, `test_no_side_scorer_tally_leg_contract.py`, `test_position_monitor_trial_id_join_contract.py`, `test_rung_hold_families_mutual_exclusion_contract.py`.

No unit file was found that re-implements the Nautilus order-status machine [CONFIRMED search limit]. `MessageBus` / `ParquetDataCatalog` / `TestClock` in unit tests are mostly hosts for Breezy objects (`test_polymarket_us_startup_evidence.py`, `test_current_rung_hold_study_replay_equivalence.py`). Treating all 119 engine files as duplicate framework coverage would drop real pins [HYPOTHESIS].

## (C) Implementation-detail assertions

741 `assert` lines touch `._attr` (101 files); 82 lines mention `caplog` (34 files); `assert_has_calls` = 0; `assert_called*` = 10 sites / 4 files [MEASURED]. Worst 15 [CONFIRMED]:

| # | Site | Asserts now | Should assert |
|---|---|---|---|
| 1 | `test_current_rung_hold_ambiguous_resolver.py:300` | `client._latch.is_latched()` after calling `_submit_order` | Intent stays OPEN and no second order is submitted. |
| 2 | same file `:296` | Test writes `client._cache.add_order` to imitate `execution/engine.pyx:1122` | One submit through the public command port; ambiguous result; no resubmit. |
| 3 | `test_continuous_rung_hold_fill_wiring.py:579` | `strategy._decision_ask_by_station_day[...]` | Persisted trial stores decision ask, not fill price. |
| 4 | same file `:2277` | `strategy._recorded_fee_for(...)` | Public fill row fee = cumulative fee / qty. |
| 5 | `test_polymarket_us_exec_client.py:1081` | `client._trading_refusals == []` | A later order is accepted once the refusal condition clears. |
| 6 | `test_polymarket_us_startup_evidence.py:480` | `_position_lag_pending == {}` | One position event emitted; a repeat read does not emit again. |
| 7 | same file `:481` | `_position_lag_last_long == frozenset(...)` | The emitted long set equals the confirming read. |
| 8 | `test_continuous_rung_hold_strategy.py:476` | `diagnostics.count(_DIAG_FEE_UNVERIFIED)` | Hunt tick submits nothing while the fee is unverified. |
| 9 | `test_current_rung_hold_composition.py:282` | `strategy._config.stations == ("SFO",)` | Only SFO is subscribed / ordered. |
| 10 | same file `:800` | `monitor._exit_family_id` | Exit decision follows that family’s rule, checked on the order. |
| 11 | same file `:1367` | Exact log sentence `composed stations LAX,MDW,MIA,SFO...` | Node received that station set. |
| 12 | `test_app_trade_fee_drift_probe_wiring.py:142` | `actor._documented == Decimal("0.0695")` | Wire read 0.0695 agrees: no alert, no halt (the next test already does this). |
| 13 | `test_archive_cache.py:151` | `cache._fetch_calls == []` after the test calls `.clear()` | A second `get_or_fetch` does not call the injected fetch. |
| 14 | `test_polymarket_us_submit_order_chain.py:1933` | `"branch=exact" in caplog.text` | Drop it. `:1930–1932` already pin kind, `fee_reconciled`, fee. |
| 15 | `test_sl13c_d_plus_1_resolution.py:257` | `strategy._instrument_ids == ()` (comment: white-box) | Strategy subscribes and submits nothing until resolution. |

`submit_order.assert_called_once()` in `test_sl13_wiring.py` is a boundary check, not one of the worst [CONFIRMED].

## (D) Slow / flaky / burden

Gate logs under `/home/jon/.cache/breezy-gate/` have **no durations and no collected-count line**. Warning paths are `/home/jon/breezy/...`, and `fqw6.log` is `/home/jon/breezy/.claude/worktrees/fq-release/...`. **Not shown to be this worktree** [CONFIRMED].

Strict progress-character recount (dots split by embedded Nautilus log lines, so dot totals are a lower bound) [MEASURED]:

| Log | `.` | `s` | `x` | `X` | `F` | `E` | GATE_EXIT |
|---|---|---|---|---|---|---|---|
| combo1 | 14668 | 11 | 7 | 3 | 0 | 0 | 0 |
| combo2 | 352 | 0 | 0 | 0 | 0 | 0 | **absent** |
| combo3–8, fqw1, fqw3–6 | 14654–14910 | 11–12 | 7 | 3 | 0 | 0 | 0 |
| **fqw2** | 14751 | 12 | 7 | 3 | **2** | **2** | **1** |

`x`/`X` are stable. **No outcome flake on the green logs** [CONFIRMED]. `fqw2` failed two source-scan tests:

- `test_x1_the_live_scan_actually_reaches_a_test_that_imports_the_exec_package` — extra files `test_fq_caps_and_ambiguous_2026_10_01.py`, `test_fq_no_leg_reconciliation_parity.py`.
- `test_no_module_under_src_reads_docs_evidence` — `live_orders_gate.py:71`.

On **this** HEAD those two files are in the allowlist (`test_execution_egress_firewall_guard.py:3695`) and `live_orders_gate.py:71` is a comment, not a `docs/evidence` runtime string [CONFIRMED]. **HYPOTHESIS: tree drift during the day, not a random flake.** `combo2` is a ~352-test run, not a full gate [CONFIRMED].

**Warnings** (per-file headers, stable on green logs) [MEASURED]: paper replay **38**, `test_backtest_run_refusals.py` **35**, `test_backtest_harness_stop_gate.py` **22**, `test_multi_instrument_weather_strategy.py` **20**, `test_nbp_shadow_parity_live.py` **14** (22 only on fq-release `fqw6`), backtest-only / settlement-print-lock **12** each, resting ladder and `test_runtime_backtest_feed.py` **10**. Header sums **181–205**. Repeated sources: `Timestamp.utcnow` (`backtest_harness.py:1008`, Nautilus `backtest/node.py:668`), fee-model maker-sign `UserWarning`, secret-from-env `UserWarning`, scipy invalid divide. **Fork** [CONFIRMED]: `test_trade_supervisor.py:2554,2735,2748,2762` `os.fork()`, and the logs emit the multi-thread fork `DeprecationWarning`.

Burden sites, not timings [MEASURED]: `time.sleep` 16/10 files, `asyncio.sleep` 71/22, subprocess/multiprocessing 124/54, `parquet` token 615/83 (not “large file” proofs). Real binders: `tests/support/loopback_https.py` (185), `loopback_ws.py` (180).

**Fixture cost** [CONFIRMED]: `tests/conftest.py` is 532 lines and **imports** `tests.unit.test_execution_egress_firewall_guard` to enforce N2 (`:341`). Support: synthetic tapes 287+300, forecast fixtures 430, `nautilus_log_capture.py` 121 (session-global Rust logger, `conftest.py:276`). Duplicate fixture names: `store_path` 18 files, `interior_instrument` 12, `tally_mod` 10, `_operator_order_ceiling` 8 [MEASURED].

Slowest files: **not measured**. Candidates by size, engine use, warnings, and fork [HYPOTHESIS]: the ten largest, plus `test_backtest_harness_stop_gate.py`, `test_multi_instrument_weather_strategy.py`, `test_backtest_run_refusals.py`, `test_trade_supervisor.py`.

## (E) Regression-protection map

| Risk | Pin | Rating |
|---|---|---|
| N1 pyo3 block | `test_execution_egress_firewall_guard.py:315–358`; `conftest.py:275` | **Strong** |
| N3 attested block must actually refuse | same file `:493`, `:989`; launcher `:1086` | **Strong**. N5 depends on a namespace this agent does not have. |
| N2 abort before collection | `conftest.py:359–380`; tests `:969–1053` | **Strong**, and it blocked this audit’s collect. |
| Signer B2 GET-only | `test_polymarket_us_signing.py:266` raises `MethodNotPermittedError` for non-GET; `:274` `PERMITTED_METHODS == {GET}` | **Strong** (raise). The frozenset line is weaker. |
| `BacktestOrderGuard` | `test_runtime_backtest_order_guard.py` — post-only refused, sell `>` net long refused, `==` allowed, joint working sells refused (`:169–341`) | **Strong** on the refusal table. `:421` “topic is the one strategies publish” and `:428` installer subscription are **weak**. |
| `allow_short=False` | `test_config.py:43` `AllowShortNotPermittedError`; `test_weather_common_risk.py:874` default flag | **Strong** for ladder-config construction. Flag-default asserts are **weak** unless the guard tests stay. Naked-short coverage is the guard file, not the flag. |
| Permit / caps | `test_native_order_cap_wiring.py`, `test_risk_engine_ordering_enforcement.py`, `test_polymarket_us_permit_issuance.py`, `test_order_submission_permit.py`, `test_runtime_order_guard_permit_expiry.py`, `test_operator_caps_through_the_live_composition.py`, `test_fq_caps_and_ambiguous_2026_10_01.py` | **Strong** where a real engine or the guard refuses. Not each test was opened. |
| Drift refusal | `test_fee_drift_probe.py`, `test_app_trade_fee_drift_probe_wiring.py` (behaviour test after `:145`), `test_polymarket_us_exec_snapshot_drift.py`, `test_domain_strict_arrow.py` `SchemaDriftError` | **Mixed**. Probe wiring’s `actor._documented` is **weak**; schema-drift raise is **strong**. |
| Settlement-grade | `test_normalize_classify.py:28` PRELIMINARY vs FINAL on real NWS fixtures; `test_settlement_truth_dataset.py` `settlement_grade_*` flags | **Strong** |
| PREREG / H0 variance | `test_multi_position_validation_2026_09_14.py:302` `Var_H0` closed form; `test_station_day_mixed_side_2026_09_14.py`; `test_aud05_side_aware_stratum.py:433`; `test_prereg_v1_is_byte_unmodified.py` | **Strong** on the closed form. Monte-Carlo cells (`n_reps=500`) are heavier and only bounded [CONFIRMED `:294`]. |
| Intent AMBIGUOUS | `test_current_rung_hold_ambiguous_resolver.py` (6989 LOC, 118 private asserts), `test_fq_caps_and_ambiguous_2026_10_01.py`, `test_edge2_ambiguous_order_probe.py` | **Weak-to-mixed**. Names describe the right behaviour; the harness calls `_submit_order` and reads `_latch`. |
| Supervisor restart | `test_trade_supervisor.py` adopt/restart cases (`:3939`, `:6803`) and `test_runtime_restart_resume.py` | **Mixed**. Scheduling/adopt tests look behavioural; four `os.fork()` tests are the burden. File is 7026 LOC. |

## (F) Strategy and tiered gates

**Retain:** N1/N2/N3 and the conftest abort; B2 non-GET raise; `BacktestOrderGuard` refusal table; `allow_short=True` construction refusal; native cap + risk-engine ordering contracts; PRELIMINARY/FINAL classify; H0 closed form; catalog/cache/expiry/streaming pins in section B.

**Consolidate:** add `pytestmark = pytest.mark.contract` to the 10 unmarked contract modules (the cache-durability pin is the one a version bump must not skip). Collapse `store_path` / `interior_instrument` into `tests/support`. Split `test_trade_supervisor.py` and the ambiguous-resolver file on public outcomes, then delete the private-attr twins.

**Replace:** rows 1–15 in section C. Keep one fork test or a process double; do not keep four `os.fork()` calls.

**Do not remove** engine-hosted contract files until a sandboxed `--durations=20` run shows they are pure framework retests. None was shown to be that [CONFIRMED gap].

**Marker hole** [CONFIRMED]: `slow` marks one test, `replay` marks none, so a fast tier **cannot** be selected with existing markers. A CLI `-m` replaces `addopts` `-m`; repeat the live exclusions [HYPOTHESIS: standard pytest, not re-run here].

| Tier | Expression that works today | What it does not do |
|---|---|---|
| Fast unit | `pytest -p no:randomly -m "not live and not venue_live and not real_money and not contract and not slow" tests/unit tests/strategy` | Still runs unmarked backtests, supervisor forks, ambiguous-resolver. **No measured runtime.** PROJECTED goal ≤5 min after a `heavy` mark exists. |
| Contract | `pytest -p no:randomly tests/contract` **and** `pytest -p no:randomly -m "contract and not live and not venue_live and not real_money"` | First misses unit files that carry the mark. Second misses the 10 unmarked contract modules. Run both until marks are fixed. |
| Deterministic e2e | `pytest -p no:randomly tests/integration` | `addopts` already drops live/venue_live/real_money. |
| Full gate | `scripts/ci/run_tests_no_egress.sh` | Only honest full run. Do not export the attestation without the namespace. |

**Characterization still missing or only present in private form** [HYPOTHESIS]:

- AMBIGUOUS: one test that submits once, gets a with-id ambiguous body, and asserts no second order and an OPEN intent, without `_latch` / `_submit_order`.
- Supervisor: one adopt-not-double-spawn test that does not `os.fork()`.
- Fee drift: keep the agree/no-halt test; drop `actor._documented`.
- Cache durability: mark it `contract` so the bump tier sees it.

## (G) Open questions

1. Collected count and per-marker item counts need one `--collect-only` **on a host where `bwrap --unshare-net` works**. This agent cannot create a user namespace.
2. Slowest files are unknown until one full gate adds `--durations=20`. Do not start a second full run while one is in progress.
3. Which git SHA produced `fqw*.log` / `combo*.log`? Paths are `/home/jon/breezy` and `fq-release`, not this worktree. `fqw2`’s two failures do not match this HEAD.
4. What was `combo2.log` (352 dots, no `GATE_EXIT`)?
5. 502 mock-using tests were not classified (multiline / `setenv` / bare mocks).
6. 139 parametrize decorators were not expanded; `pytest_generate_tests` was not counted.
7. Whether the 116 engine-mentioning tests dominate the cited ~23 min is unverified.
