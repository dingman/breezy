# Intra-day Position Monitoring & Loss-Prevention — pm_us_crh_cont (SHADOW-ONLY) — Rev 2

Status: Rev 2 (plan author: trading-bot-architect; coordinator decisions D1–D8 binding). Rev 1 peer-reviewed blind by architect (REJECT), prediction-market-reviewer (REJECT), python-reviewer (APPROVE-WITH-FIXES), security-reviewer (REJECT); every finding dispositioned below. Worktree: `~/breezy-ilp`, branch `backlog/intraday-monitor-2026-09-15`.
Investigation record: six blind seams merged 2026-09-15 (strategy, execution/safety, edge-hunting/persistence, binding docs, Nautilus L-1 audit, test-harness inventory). Delegation route: Grok 402 (balance exhausted) → Codex read-only inventory → Claude specialists.

## Coordinator decisions (binding)
- D1 Invariants: Nautilus immutable; `allow_short` stays False; exact-set barriers widened never relaxed (L-12); no new operator control, no env var named; enablement and NO-SEND firewall untouched; PREREG v3 §3/§5/§9 unchanged for `pm_us_crh_cont`.
- D2 Shadow-only on `pm_us_crh_cont` (PREREG v3:277 `held==(pnl>0)` refuses the tally on an early exit; hold-to-settlement is the registered action). Real exit execution gated on a family manifest that declares an exit rule; `pm_us_crh_cont` provably never reaches a SELL. Goal state carried to the end (L-3) with blockers named.
- D3 Monitoring read-only w.r.t. trial selection (L-34): never alters the snapshot that becomes the trial, the latch, IN_FLIGHT, or admission.
- D4 Marks from Depth10 only; explicit one-sided-book policy; depth walk for the held qty; recoverable value = walk VWAP − exit fee 0.06·p·(1−p) at the exit price; EXIT with no executable bid = MISSING-stop (L-38).
- D5 Thesis evidence reuses the entry machinery (running max vs rung geometry, same archive P_HOLD table and hour, staleness bounds, fee coefficient).
- D6 Persistence per repo convention; feedback to edge hunting is informational (tally side table) and a Gate-0 evidence artefact for a future exit family; never enters LD-OBF.
- D7 Evaluation via the v3 backtest subclass / paper replay under TestClock, no look-ahead; plus a hypothetical-hold corpus over the archived tape.
- D8 Failure containment: monitor exceptions caught at the handler boundary, counted, operator-visible; stale → UNKNOWN never EXIT; broken monitor degrades to no monitor.

## 0. Goal state & what "effective" means

`ContinuousRungHoldStrategy` (`src/breezy/strategy/current_rung_hold/continuous_strategy.py:296`, extends Nautilus `Strategy` directly, not the sibling v2 class) gains a shadow-only monitor that, on every observation and Depth10 update for an instrument it currently holds, recomputes the entry thesis with the same machinery entry used (`evaluate_decision`, `RunningExtremeAccumulator`, the archive `P_HOLD` table), classifies the position's thesis (ALIVE / THREATENED / DEAD_BY_OBSERVATION / LOCKED_BY_OBSERVATION / UNKNOWN), and records a verdict (HOLD / REDUCE_RECOMMENDED / EXIT_RECOMMENDED / MISSING_STOP / UNKNOWN) — never submitting an order for `pm_us_crh_cont`. Null hypothesis: the shadow verdict trail is uninformative — EXIT/THREATENED correlate with eventual loss no better than staying ALIVE throughout. "Effective" = (a) EXIT verdicts concentrate on trials that go on to lose (DEAD precision = P(settled loss | DEAD fired)), (b) the premature-exit rate is low, (c) recoverable-value-at-signal (a true `ts_init`-bounded Depth10 walk, never a post-hoc bid — L-18) exceeds the eventual realized loss net of fees/slippage. Single-arm counterfactual design; Wilson CI for description only, never merged into the LD-OBF statistic (PREREG v3:277, D6). INC-8 (archived-tape hypothetical-hold corpus) is the primary evaluation vehicle: hysteresis constants and every headline number are PROVISIONAL until that corpus exists.

## 1. L-1 table (native vs authored)

| Capability | Native? | Cite | Breezy authors |
|---|---|---|---|
| Position state/PnL | native | `Position.unrealized_pnl/total_pnl/avg_px_open/ts_opened/peak_qty`; `Cache.positions_open(instrument_id=)` | nothing extra — read fresh each eval |
| Position lifecycle hooks | native; v2 sibling overrides `on_position_opened` (strategy.py:604); v3 overrides none | 2 new handlers on `ContinuousRungHoldStrategy` only (B1) |
| Depth10 mark pricing | partial | `Portfolio.unrealized_pnl` marks off `Cache.price(BID)` from `QuoteTick` only | leg-aware depth-walk VWAP (B4) |
| Leg price inversion | native pattern | `wire_price_for_leg`/`instrument_price_for_leg` (`adapters/polymarket_us/leg_prices.py:56-96`: YES identity, NO = 1 − x); `_evaluate_no_side` (decision.py:406-430) | NO-leg mark mirrors this exact inversion, never reimplemented |
| Custom high-freq record + catalog | native | hand-written `Data` + `register_arrow` + `ParquetDataCatalog`; precedent `tape_records.py:55`, `quote_tape_gaps.py` | `PositionMarkRecord` |
| Bounded buffer + JSONL sidecar | native pattern | `OfferTape` (`offer_tape.py:78-124`: `deque(maxlen)`, best-effort JSONL append, disk error caught + logged) | `monitor_store.py` buffer, same shape |
| Batched catalog write | native pattern | `breezy.persistence.catalog.write_records` (`persistence/catalog.py:422`) | flush calls this, not raw `write_data` |
| Per-position-day summary persistence | repo convention | `scored_trial_store.py:79-121` append-only parquet, dedup by `score_seq` | `PositionMonitorSummary` + store, `monitor_seq` dedup key |
| Portfolio stats | native | `PortfolioAnalyzer.register_statistic`; pyo3 `MaxDrawdown/Expectancy/ProfitFactor/WinRate` | nightly/report wiring only, n-gated |
| MAE/MFE, DEAD precision | gap | — | pure functions |
| Venue-acceptable closing order shape | gap | `unmappable_order_reason` (submit_chain.py:277-318) refuses every SELL | design only — §5, BLOCKED |
| Archive table hour coverage | native, bounded | `mb_current_rung_edge_study.py:168` hours 12–16; `N_MIN=90` :172 | `p_hold_undefined` reason code |
| Family-manifest exit-rule gate | none | `FamilyManifest` closed-required-key frozen dataclass (`persistence/family_manifest.py:53-64,95-113`) | optional key + persistence-layer gate (B2) |

## 2. Architecture

Every strategy edit lands on `ContinuousRungHoldStrategy` (continuous_strategy.py:296, `__init__` :299-399). `strategy.py` (v2 `CurrentRungHoldStrategy`, an independent `Strategy` subclass) is not touched.

New modules, ≤400 lines each:

- **`strategy/current_rung_hold/monitor_evidence.py`** (~160 ln, pure). `MonitorEvidence` frozen dataclass: `ts_ns, instrument_id, station, climate_day, leg, cell_key, p_hold_at_entry, p_hold_at_t (None → p_hold_undefined), fill_px, held_qty, mark_vwap|None, mark_source ("depth_walk"|"missing"), spread|None, depth_sufficient, staleness_ns, book_staleness_ns, running_max_lower, running_max_upper, rung_low, rung_high, exit_fee_at_mark|None, unrealized_pnl|None, recoverable_value|None`. `build_monitor_evidence(...)` reuses `width_and_m`/`instrument_rung_is_current` (tick_eval.py), `RunningExtremeAccumulator.value_at/staleness_ns` (running_extreme.py:265,307), and `P_HOLD_LOWER/UPPER[key]` exactly as `evaluate_decision` (decision.py:341,421). B4 leg-aware mark: YES walks `depth.bids` for the exit VWAP; NO walks `depth.asks` and returns `1 − ask_walk_vwap` (mirrors `wire_price_for_leg` NO branch and `_evaluate_no_side`); every mark tagged with its leg. Exit fee = `0.06·p·(1−p)·qty` with **p := mark_vwap** (the exit price), never `fill_px` (B5). Decimal fields constructed `Decimal(str(...))`, never from the float `PositionOpened.avg_px_open` (M8).
- **`strategy/current_rung_hold/monitor_decision.py`** (~220 ln, pure). `ThesisState`, `Verdict`, `MonitorDecision` (frozen: state, verdict, reason_codes tuple, confirmations, ts_ns), `MonitorHistory` (immutable: last decision, consecutive candidate count, last confirming observed_at_ns tuple). `evaluate_monitor(evidence, history) -> tuple[MonitorDecision, MonitorHistory]`. §3.
- **`strategy/current_rung_hold/monitor_records.py`** (~150 ln). `PositionMarkRecord` (hand-written `Data` + one `register_arrow`; schema §4), `PositionMonitorSummary` (frozen + explicit `to_dict`).
- **`strategy/current_rung_hold/monitor_store.py`** (~250 ln). M2: `deque(maxlen=2048)` of pending mark records, `monitor_marks_dropped` counter; flush = one batched `write_records` call at 256 buffered rows and unconditionally in `on_stop`; per-emit best-effort JSONL sidecar (OfferTape shape; disk error never propagates); dedicated catalog root (never the quote-tape root; the trader writes no tape, node_config.py:748-750). Also `write_monitor_summaries`/`read_monitor_summaries` mirroring `scored_trial_store.py:79-121` (atomic tempfile + `os.replace`, dedup `(trial_id, max monitor_seq)`).
- **`strategy/current_rung_hold/position_monitor.py`** (~300 ln). `PositionMonitor` orchestrator: `on_position_opened(position)`, `on_observation(station, observed_at_ns, now_ns)`, `on_depth(depth, now_ns)`, `on_stop()`, `errors`/`counters` properties. Internal `_ensure_registered(iid)` (B3). No `finalize`/`on_position_closed` (CUT). Every public method try/except-wrapped, `monitor_errors` counter, reported via the existing alerter (D8).
- **`persistence/exit_gate.py`** (B2 location; importlinter layers strategy > runtime > adapters > … > persistence, exhaustive). `_EXIT_RULE_REGISTERED_FAMILIES: Final[frozenset[str]] = frozenset()` + `family_declares_exit_rule(manifest) -> bool` requiring BOTH membership AND `manifest.exit_rule is not None`.

**Strategy diff** (continuous_strategy.py only):
1. `__init__` gains `position_monitor: PositionMonitor | None = None` (None ⇒ every hook no-ops), mirroring the permit's None-is-shadow convention.
2. M1 dual triggers: `on_data` (StationObservation → accumulators) gains one forwarding line to `on_observation`; `on_order_book_depth` (:828) gains one line AFTER `_hunt_tick`: `on_depth(depth)`. Monitor caches the last `OrderBookDepth10` per instrument (bounded: one per subscribed instrument) and tracks `book_staleness_ns` separately from observation `staleness_ns`; observation-driven DEAD against a stale book → MISSING_STOP/UNKNOWN. No `Clock` timer (L-16).
3. NEW `on_position_opened(event)`: `super().on_position_opened(event)` then `monitor.on_position_opened(self.cache.position(event.position_id))`, tagged `entry_context="live"`.
4. B3 lazy registration: `_ensure_registered` on every evaluation reads `cache.positions_open(instrument_id=iid)`; an untracked open position is registered with entry context recovered from the durable `TrialDayRecord` (trial_day_latch.py:389: ask, venue_order_id, fee) via the latch's read-only `record(...)`, tagged `entry_context="reconciled"`. RED test seeds a real `Position` before `on_start` (fill_wiring.py:1018 pattern).
5. M5: held qty read fresh from the cache on every evaluation; no `on_position_changed`.
6. `on_stop` gains `monitor.on_stop()` (flush).

M7 D3 pin: `PositionMonitor` holds no reference to the latch's mutating surface (only the read-only `record` accessor is injected as a callable), never calls `_hunt_tick`/`_maybe_submit`, never reads or pops `_decision_ask_by_station_day` (:384, popped-on-read). Accumulator access limited to `value_at`, `staleness_ns` — asserted by a unit test with a recording stub that fails on any other attribute. Plus the attached-vs-None identical `TrialDayRecord`/latch-state test.

Family-manifest gate (INC-1): `_OPTIONAL_KEYS: Final[frozenset[str]] = frozenset({"exit_rule"})`, `unknown = keys - _REQUIRED_KEYS - _OPTIONAL_KEYS`, `FamilyManifest.exit_rule: str | None = None` (kw_only, so appendable), loader `payload.get("exit_rule")`. Full existing `test_family_manifest.py` suite stays green (L-12).

No new `CurrentRungHoldConfig` field, no env var. Hysteresis thresholds are `Final` module constants in `monitor_decision.py`, PROVISIONAL until INC-8.

## 3. Decision logic spec

`evaluate_monitor(evidence, history)`:
- Stale observation (shared `stale_observation_minutes` bound, decision.py:316-322) → state UNKNOWN, verdict UNKNOWN, reason `stale_observation`. Stale book (book_staleness_ns > `_BOOK_STALE_NS`, PROVISIONAL 180 s, same order as `_REARM_EVIDENCE_MAX_AGE_NS`) → mark_source missing.
- B5 DEAD is a classifier: `DEAD_BY_OBSERVATION` requires (i) `running_max_lower > rung_high` AND (ii) ≥2 consecutive observations with distinct `observed_at_ns` confirming; same-instant re-push never counts. Until confirmed: state stays previous, reason `dead_candidate`.
- Same-cell `p_hold_at_t` re-lookup: drop ≥ `_P_HOLD_DROP_MARGIN` (PROVISIONAL 0.10) vs `p_hold_at_entry` → candidate; `THREATENED` after `_THREATENED_CONFIRMATIONS` (PROVISIONAL 3) consecutive candidates spanning ≥ `_THREATENED_MIN_SPAN_NS` (PROVISIONAL 10 min). Recovery (drop below margin for the same span) returns to ALIVE (hysteresis both ways).
- M6 archive coverage: lookup outside hours 12–16 or below N_MIN → `p_hold_at_t=None`, reason `p_hold_undefined` (distinct from `stale_observation`); state decided from cell membership only.
- `LOCKED_BY_OBSERVATION` (informational): running-max interval fully inside `[rung_low, rung_high]` AND `hour_lst ≥ _LOCKED_HOUR_LST` (PROVISIONAL 18).
- Verdict mapping: ALIVE/LOCKED → HOLD. THREATENED → REDUCE_RECOMMENDED (informational at qty 1). DEAD (confirmed) → executable-exit test: leg-aware Depth10 walk for the full held qty at a fresh book; fillable → EXIT_RECOMMENDED with `recoverable_value = walk_vwap·qty − fee`; not fillable / stale book / one-sided → MISSING_STOP (L-38). UNKNOWN never maps to EXIT.
- Σq/opportunity cost: reporting-only; never touches `station_day_admission` (trial_day_latch.py:1192).

## 4. Instrumentation

- **`PositionMarkRecord`** — explicit `pa.schema`: `ts_event int64 nn, ts_init int64 nn, instrument_id string nn, station string nn, climate_day string nn, leg string nn, entry_context string nn, thesis_state string nn (.value), verdict string nn (.value), mark_vwap string nullable, mark_source string nn, unrealized_pnl string nullable, recoverable_value string nullable, running_max_lower string nullable, running_max_upper string nullable, staleness_ns int64 nn, book_staleness_ns int64 nn, held_qty string nn, reason_codes string nn (comma-joined)`. Emission policy (M2): MAE/MFE/hysteresis state updated in memory every evaluation; a record is emitted only on state/verdict change or a 60 s per-instrument heartbeat. Round-trip contract test (construct → write_records → query → unwrap); schema-drift test asserts the decoder raises on a wrong-typed row.
- **`PositionMonitorSummary`** — `trial_id, instrument_id, station, climate_day, leg, entry_context, monitor_seq, fill_px, held_qty, mae, mfe, first_signal_ts_ns|None, first_signal_hour_lst|None, first_signal_state|None, verdict_at_signal|None, recoverable_value_at_signal|None, held_duration_ns, total_frames, mark_missing_frames, monitor_intervened (constant False), settled_pnl|None, settled_held|None`. Written from the in-memory `_MonitoredPosition` on flush/on_stop (upsert with incremented `monitor_seq`); `settled_*` populated only by the nightly join on `trial_id` against `read_scored_trials` (scored_trial_store.py:104).
- **M4 trial_id**: derived at registration by the same function the scorer uses (`TrialDayRecord` key (station, climate_day, instrument_id), prefix `FamilyManifest.trial_id_prefix`; locate in `score_live_trials.py`/`trial_scorer.py` and import, never re-derive). Contract test beside `tests/contract/test_live_fill_scoring_chain_contract.py` proves a summary row joins to the `ScoredTrial` the same fill produces.
- **Nightly report** (`scripts/analysis/position_monitor_nightly_report.py`): joins the two stores by `trial_id`; always-valid set: raw counts, shadow-verdict × settled-outcome contingency table, premature-exit rate with Wilson CI, avoided-loss sum (realizable marks only), DEAD precision, one-sided-book rate (`mark_missing_frames/total_frames`), exit-timing distribution. M9 n-gate: expectancy / profit factor / drawdown / risk-adjusted labelled `INSUFFICIENT_N` below `N_MIN=90` (mb_current_rung_edge_study.py:172); computed via `PortfolioAnalyzer` statistics only above it. Isolation: never imports `settlement/current_rung_hold_v2.py` or `live_family_tally.py`; the tally may later *read* the report file as informational lines, never the reverse.
- Look-ahead control: evidence built only inside `on_observation`/`on_depth` from already-`ts_init`-ordered callbacks; no catalog queries from the monitor.

## 5. Execution seam (gated) — one merged BLOCKED increment

5a+5b merged, BLOCKED (B2): widening `unmappable_order_reason` (submit_chain.py:277-318) to admit a gated SELL is specified for the same increment as the REDUCE_ONLY_BYPASS/R6A remediation. Until then these stay byte-identical: the pinned refusal string (`tests/unit/test_no_side_submit_chain_2026_09_14.py:188-190`), the callee frozenset (`test_cage_rule_constants_are_pinned.py:500-570`), X3/E0 in `test_execution_egress_firewall_guard.py`. When 5a/5b land, all widen together, narrowly, with explanation (L-12). Shape when built: SELL admitted only if LIMIT+IOC, `quantity ≤ attributed net long − working sells` (BacktestOrderGuard semantics), position attributed to a Breezy order id, `family_declares_exit_rule(manifest)` True, and the fill accounting side (`_RECORD_SIGNS`) already understands SELL.
- 5c AMBIGUOUS-sell resolution via `_resolve_ambiguous_intents` (client.py:681-770) — test-only later; no production change now.
- 5d fee/BE with exit-price fee — built in `monitor_evidence.py`.
- 5e runbook line — BUILD-NOW docs edit (R8:213: shadow monitor never submits; any observed SELL is a defect).
- 5f residual-containment template (PREREG v4, prospective, first-of-kind residual) and 5g venue SELL semantics (`polymarket-us-discovery`) — BLOCKED.

## 6. Increments in build order

| # | Files | RED tests | Completion | Status |
|---|---|---|---|---|
| INC-1 | `persistence/family_manifest.py`, `persistence/exit_gate.py` | `test_family_manifest.py` (+exit_rule accepted; unknown key still refused); new `test_persistence_exit_gate.py` enumerating every manifest file in the repo → gate False for each; frozenset Final and empty | full suite + lint-imports green | BUILD-NOW |
| INC-2 | `monitor_evidence.py` | new `test_current_rung_hold_monitor_evidence.py`: one-sided book, insufficient depth, NO-leg mark (1 − ask walk), cell-key parity with `evaluate_decision`, fee off `mark_vwap` with `fill_px ≠ mark_vwap`, p_hold_undefined outside hours | pure, full branch coverage | BUILD-NOW |
| INC-3 | `monitor_decision.py` | new `test_current_rung_hold_monitor_decision.py`: single noisy reading no-op, 2-distinct-time DEAD gate, THREATENED confirmations + span, recovery to ALIVE, `p_hold_undefined` vs `stale_observation`, stale book → MISSING_STOP, UNKNOWN never EXIT | pure state machine | BUILD-NOW |
| INC-4 | `monitor_records.py`, `monitor_store.py` | new `test_current_rung_hold_monitor_records.py` (catalog round-trip, schema-drift raises), `test_current_rung_hold_monitor_store.py` (256-row batch flush, on_stop flush, dropped counter, sidecar disk-error swallowed+counted, summary dedup) | green | BUILD-NOW |
| INC-5 | `position_monitor.py`, `continuous_strategy.py` (+~6 ln) | `test_continuous_rung_hold_strategy.py` + `test_continuous_rung_hold_fill_wiring.py`: no-op when None; registers on `PositionOpened`; B3 real Position seeded before on_start registers as reconciled; M7 accumulator allowlist stub; raising monitor never reaches hunt path; attached-vs-None identical TrialDayRecord/latch | D3 pin green | BUILD-NOW |
| INC-6 | `scripts/analysis/position_monitor_nightly_report.py` | new `test_position_monitor_nightly_report.py`: join, MAE/MFE, contingency table, INSUFFICIENT_N labelling, isolation import assertion | report table produced | BUILD-NOW |
| INC-7 | installer inside `scripts/analysis/current_rung_hold_paper_replay.py` (one-importer pin, continuous_backtest_only.py:41-45; update docstring :47-51) | extend `test_continuous_rung_hold_backtest_only.py` / paper-replay tests with real `BacktestEngine` + synthetic tape | ts_init-monotonic marks, ≥1 summary row | monitor-alone BUILD-NOW; v3 fill→monitor replay BLOCKED on SP-4 |
| INC-8 | `scripts/analysis/current_rung_hold_monitor_hypothetical_hold.py` | new: no-look-ahead ordering pin, settlement-truth join, selection parity with the reused study code | outputs DEAD precision, THREATENED base rate per afternoon (L-13), MISSING_STOP rate, recoverable-value distribution, implied firing rates of the PROVISIONAL constants; reuses `mb_current_rung_edge_study` selection, never reimplements; bounded by tape coverage (SFO 2026-09-01 clean; ING-1 caveat); quiet-window run under the studies slice cap | BUILD-NOW |
| INC-9 | §5 execution seam (5a+5b) | — | — | BLOCKED |

## 7. Safeguards checklist

| Concern | Mechanism |
|---|---|
| Duplicate exits | N/A shadow; INC-9 reuses the account-wide `SubmitIntent` latch (L-36) |
| Stale data | observation and book staleness gated separately → UNKNOWN / MISSING_STOP, never EXIT |
| Conflicting signals | hysteresis both ways; a confirmed cell change overrides a stale ALIVE |
| Repeated submission | N/A shadow; INC-9 reuses exact-set refusal + intent latch |
| Invalid position state | fresh `positions_open` read every evaluation; lazy `_ensure_registered` handles boot-inherited positions |
| Unavailable data | one-sided/stale book → MISSING_STOP; missing TrialDayRecord → registered with `entry_context="reconciled_no_record"`, p_hold_at_entry None |
| Subsystem failure | every entry point try/except-wrapped, counted, alerted; pinned by INC-5 |

## 8. Risks / limitations + docs
- No `on_position_closed`; nightly join is the sole finalizer; a never-scored position never gets `settled_*`.
- Shadow counterfactuals cannot prove causal savings (L-18); marks walked at the signal instant only.
- Archive coverage hours 12–16: much of the window runs on `p_hold_undefined`, cell-membership logic; INC-8 quantifies.
- All hysteresis/LOCKED constants PROVISIONAL until INC-8.
- Docs: `TRADING_SYSTEM_ARCHITECTURE.md` near :1568-1590; R8 runbook :213 (5e).
- INC-1 touches an exact-set safety file and adds a persistence-layer module; lint-imports must pass.

## 9. Dissent (plan author)
D2's detail on 5f/5g may be invalidated by venue discovery; binding regardless. Sequencing INC-8 before the constants it calibrates is accepted as the only way to get firing-rate evidence without a live population.

## Rev 2 dispositions
| Item | Disposition | Landed |
|---|---|---|
| B1 target class (architect/python BLOCK) | ACCEPTED | §2 |
| B2 layering + 5a not built now (architect/security BLOCK) | ACCEPTED | §2, §5, INC-1 |
| B3 boot-inherited positions (architect BLOCK) | ACCEPTED | §2 item 4 |
| B4 NO-leg marks (architect MUST, domain BLOCK) | ACCEPTED | §2 evidence, INC-2 |
| B5 DEAD classifier + fee at exit price (domain BLOCK/MUST) | ACCEPTED | §3, §2 |
| M1 dual triggers / book staleness / no timer | ACCEPTED | §2 item 2 |
| M2 emission + bounded buffer + batched flush + sidecar | ACCEPTED | §2 store, §4 |
| M3 INC-7 installer location | ACCEPTED | INC-7 |
| M4 trial_id derivation + contract test | ACCEPTED | §4 |
| M5 per-evaluation qty | ACCEPTED | §2 item 5 |
| M6 archive hour bound / p_hold_undefined / mechanistic LOCKED | ACCEPTED | §3 |
| M7 D3 pin strengthened | ACCEPTED | §2 |
| M8 pinned schemas, Decimal(str), monitor_seq, extra summary fields | ACCEPTED | §4 |
| M9 metrics n-gate | ACCEPTED | §4 |
| INC-8 hypothetical-hold corpus | ACCEPTED BUILD-NOW | INC-8 |
| CUT on_position_closed / monitor_intervened logic | ACCEPTED | §2, §4 |
| Security: gate test enumerates all manifests; pinned-set list for 5a/5b | ACCEPTED | INC-1, §5 |

## Rev 2.1 addendum — convergence-round fixes (architect + prediction-market reviewer, both APPROVE-WITH-FIXES)
- A1 trial_id: if no single shared derivation function exists in the scorer path, EXTRACT one and make both the scorer and the monitor call it (INC-4/INC-5 completion criterion).
- A2 `write_records` cost: monitor catalog root is per climate-day (`open_monitor_catalog(root, climate_day)`) so the read-back verify stays bounded; every writer exception class (`WriterLockError`, `CatalogWriteError`, `ValueError`) is caught at the monitor boundary and counted; INC-4 test pins root partitioning.
- A3 Negative `TrialDayRecord` lookups cached per `(instrument_id, climate_day)` for the process lifetime (pattern `_no_refuse_notice`, continuous_strategy.py:399) so `_ensure_registered` never re-hits SQLite per frame.
- A4 INC-8 reports its usable station-day count; below a stated floor the nightly report labels constants UNCALIBRATED instead of publishing firing rates.
- P5 INC-8 THREATENED/DEAD rates denominated by archive-covered evaluation count (hours 12–16), never wall-clock hold duration (L-13).
- P6 Add `_DEAD_MIN_CONFIRM_SPAN_NS` (PROVISIONAL 5 min) symmetric with THREATENED's span guard; INC-8 reports observed inter-confirmation spans.
- P7 Residual gap named: hour_lst 17 has neither p_hold logic nor mechanistic LOCKED; cell-membership only.
- NO-leg rule, unambiguous: to mark/exit a held NO position walk the YES book's ASK side (`depth.asks`) for the held qty → `ask_walk_vwap`; NO exit price = `1 − ask_walk_vwap`. Never walk `depth.bids` for a NO leg. YES positions walk `depth.bids`.
