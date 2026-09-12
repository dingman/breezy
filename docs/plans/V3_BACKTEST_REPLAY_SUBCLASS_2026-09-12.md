Commit: e4848c39a979bac5a91b8f6b3887f75c497c1be8

# V3 backtest-only subclass and one-day fill replay — `pm_us_crh_cont` (2026-09-12) — Rev 1

**L-1.** Four verdicts against the INSTALLED `nautilus_trader` 1.231.0 at `.venv/lib/python3.13/site-packages/nautilus_trader/`.

| # | Question | Verdict | Installed-source evidence + positive control |
|---|---|---|---|
| 1 | Replay a `Strategy` over recorded Depth10 in-engine | **NATIVE — sufficient** | `backtest/engine.pyx` `BacktestEngine`; already wrapped by `runtime/backtest_harness.py:663` (`build_backtest_engine`), `:957` (`run_backtest`), `:1005` (`install_order_guard`), `:1027` (`backtest`). Build nothing. |
| 2 | A per-strategy "submit in backtest, refuse in live" gate | **GENUINELY ABSENT** | Positive control: `grep -c submit_order .venv/.../trading/strategy.pyx` → **4** (file + symbol found). Negative: `grep -c "orders_enabled\|submit_enabled\|backtest_only"` → **0**; `grep -c permit` → **0**. In-repo precedent is Breezy's own v2 subclass (`strategy/current_rung_hold/backtest_only.py:71`). |
| 3 | Arm v3 in a backtest with a real `OrderSubmissionPermit` | **GENUINELY UNAVAILABLE — and must stay so** | `runtime/order_enablement.py:177-242` `issue()` requires `orders_enabled_requested is True`, a genuine `LiveTradingPermit`, `WRITE_CANONICAL_STRING_VERIFIED`, BOTH operator caps, and `live_observations`; `@final` + `_SEAL` `__post_init__` (`:154,166-175`) refuse forgery; the B11 pin (`tests/.../test_polymarket_us_readonly_guard.py`) scans for the single literal `OrderSubmissionPermit(` site. ⇒ the replay NEVER mints one. |
| 4 | IOC fill mechanics on a recorded L2 book | **NATIVE — configure** | `docs/specs/BACKTEST_VENUE_CONFIG.md` §1/§3/§4/§5, already IMPLEMENTED at `backtest_harness.py:713-714`. |

**Constraints.** Nautilus Trader is IMMUTABLE — never patch, fork, bypass or reimplement it. `allow_short` stays `False`. Never weaken or delete a safety, settlement or contract test to go green. Never assign an operator-reserved value (max daily budget, max per position). Never touch live-trading enablement or the NO-SEND execution-egress firewall. PREREG v3 is BINDING: nothing here changes §3, §5 or §9. Tests via `scripts/ci/run_tests_no_egress.sh` (addopts already carries `-q`; never add `-q`); `lint-imports` + `mypy` after every slice (adapters never import `breezy.runtime`).

**Fill assumption (stated explicitly, per brief).** An IOC BUY at `limit = decision ask` is matched against the **recorded Depth10 book** under `book_type=L2_MBP`, `liquidity_consumption=True`, `FillModel()` defaults (`prob_fill_on_limit=1.0`; `prob_slippage` inert at L2), `fee_model=PolymarketUSFeeModel` (taker), `latency_model=None`, `queue_position=False`, settlement from `settlement_prices` only. **Conservative on:** price (a real level walk, never `BestPriceFillModel`'s synthetic 1e6-at-touch book — `BACKTEST_VENUE_CONFIG.md:174-180`) and size (Depth10 truncation understates real depth — `:246`). **NOT conservative on:** latency (zero; `:57` labels `latency_model=None` "a known overstatement"), queue position, and the fact that at L2_MBP the **QuoteTick tape is inert for execution** — the book is driven ENTIRELY by Depth10 (`:144-150`), so depth coverage, not quote coverage, bounds validity. Net: optimistic on reaction speed and queue, honest on price and size. Every number this plan produces is a MECHANISM claim; none is an edge claim.

## 1. Goal state (falsifiable) — and the walks

**Goal.** `ContinuousRungHoldStrategy`'s Depth10 hunt path runs **byte-inherited** inside a Nautilus `BacktestEngine` over at least one CLEAN recorded afternoon, taking the **same ARMED branch the live node takes** (`app/trade.py:189,238` routes a non-None v3 permit via `phase1_family_permits`; supervisor env `BREEZY_CRH_CONT_PHASE0_SHADOW=0`), and produces `FilledTrial`s through the same latch, re-arm gate, IN_FLIGHT and family-halt semantics — only the submit SINK differs (`SimulatedExchange`, never `PolymarketUSExecutionClient`). Falsifier: any of the eleven methods in §3's "byte-inherited" list appears in the subclass, or the replay takes a `self._submission_armed() is False` branch.

**Happy walk.** `main(--strategy continuous_rung_hold)` `scripts/analysis/current_rung_hold_paper_replay.py:662` → `_convert_live_capture` → `_select_capture_instruments` → depth-basis coverage gate (`:230`, increment D) → `run_one_precision_arm` `:470` → `build_paper_replay_config` `runtime/paper_replay.py:271` → `backtest()` `backtest_harness.py:1027` → `ContinuousRungHoldBacktestStrategy.on_start` (TestClock assert → `super().on_start()` → `_run_never_arm_walk` `continuous_strategy.py:310` on injected flat evidence → `subscribe_order_book_depth` `:288`) → `on_order_book_depth` `:507` → `_hunt_tick` `:526` → `set_inflight` `:730` + `record_attempt` `:732` → inherited `_maybe_submit` `:933` → `submit_order` `:959` → `SimulatedExchange` IOC fill → `on_order_filled` `:790` → `_consume_or_flag_duplicate` `:842` writes `TrialDayRecord(reason="taken")` → `_entry_contexts_from_latch` `current_rung_hold_paper_replay.py:339` → `filled_trials_from_engine` `paper_replay.py:300` → `score_trials` → `write_scored_trials` under `derived/paper_replay/`.

**Failure walks (each must be observable, not silent).**

| Walk | Hop | Expected refusal |
|---|---|---|
| Live clock | `ContinuousRungHoldBacktestStrategy.on_start` | `ContinuousNotABacktestClockError` before `super().on_start()` |
| Startup evidence absent | `_run_never_arm_walk` `continuous_strategy.py:328-341` | `startup_evidence_permits_arm(None) is False` (`trial_day_latch.py:684-690`) → `position_events["startup_evidence_missing"]` → `self.stop()` |
| Second filled instrument on one station-day | `_entry_contexts_from_latch:369` | `EntryAskFromLatchMissingError` — never a silently dropped trial |
| Duplicate genuine fill | `_consume_or_flag_duplicate:886` | `record_duplicate_fill` → family halt → `_DIAG_FAMILY_HALT` |
| Fill better than the decision ask | `filled_trials_from_engine:341` | `ImpossibleFillPriceError` (L-25) |
| No in-window depth | increment D gate | `NoDecisionWindowCoverageError`, never a silent zero-fill |
| Latch store under the live state root | increment E guard | refuse before any engine is built |

## 2. Spec / evidence vs code

| Piece | Code today (file:line) | Gap |
|---|---|---|
| v3 submit-capable subclass | only v2's `CurrentRungHoldBacktestStrategy` (`backtest_only.py:71`) | **ABSENT** (audit S4 #1, §3 B3) |
| v3 permit-gated branches | 5 behavioural reads of `self._order_submission_permit`: `continuous_strategy.py:302,579,731,734,935` (`:941` is log text only) | No seam a subclass can flip; a permit-None subclass would replay the **shadow** branch, not the live one |
| Driver `strategy_cls` | `run_one_precision_arm(..., strategy_cls=CurrentRungHoldBacktestStrategy)` `:470-479`, annotated `type[CurrentRungHoldBacktestStrategy] \| type` | Constructs with 2 kwargs only; v3 also needs `position_evidence_reader` |
| Never-arm walk in a replay | `_run_never_arm_walk` `:310`; fresh store → `read_startup_evidence` `trial_day_latch.py:579-590` returns `None` → refuse | Driver must inject synthetic flat evidence through the EXISTING ctor kwarg `position_evidence_reader` (`continuous_strategy.py:178,205`) |
| Coverage gate basis | `assert_decision_window_has_coverage` counts **QuoteTicks** (`current_rung_hold_paper_replay.py:230-256`); whole-tape `assert_station_window_coverage` likewise (`whole_tape_paper_replay.py:221-244`) | v3 hunts Depth10 (L-35) and at L2_MBP the book is depth-only (`BACKTEST_VENUE_CONFIG.md:144-150`) — a depth-only day is wrongly refused, a quote-only day runs against a frozen book |
| Entry-ask join | `_entry_contexts_from_latch:339-385` needs ONE `reason=="taken"` record per station-day | v3 writes it in `on_order_filled` (`:842-866`) not at decision — **compatible**, and richer (carries `venue_order_id`) |
| Latch-store containment | `assert_paper_write_path_is_not_live` guards the OUTPUT dir only | v3 additionally READS `is_intent_open` `:605` / `is_family_halted` `:534` from the latch store — a live path would read live state and could write trial rows into it |
| Paper provenance | `PAPER_TRIAL_ID_PREFIX="paper_replay/current_rung_hold/trial"` (`paper_replay.py:92,347`); `assert_paper_only` (`live_family_tally.py:168-180`) | v2-named; v3 rows would share it — see §8 ruling R1 |
| Power | `MIN_NON_EXCLUDED_N=30` (`roi_bound.py:100,190`) | one day is n≤1 ⇒ UNDERPOWERED **by design**, never a verdict |
| Precedent run | v2 whole-tape 7e44abd: 12/12 CLEAN, 14 station-days replayed, **6 produced trials=1 at both lags**, 13 BLOCKED (`~/.local/share/breezy/derived/paper_replay/WHOLE_TAPE_PAPER_REPLAY_REPORT.md`) | SFO 2026-09-01 is a proven-fillable day for v2 ⇒ the acceptance day |

## 3. Design

**Where.** ADD `src/breezy/strategy/current_rung_hold/continuous_backtest_only.py` (`ContinuousRungHoldBacktestStrategy`, `ContinuousNotABacktestClockError`). EDIT `continuous_strategy.py` (one extracted predicate), `scripts/analysis/current_rung_hold_paper_replay.py` (strategy selection, evidence injection, coverage basis, store guard). No new store, no new CLI, no adapter or runtime change.

**Parent seam (the ONLY live-file edit).** Add `def _submission_armed(self) -> bool: return self._order_submission_permit is not None` to `ContinuousRungHoldStrategy` and call it at `:302,579,731,734,935` (`:734` becomes `if not self._submission_armed():`). `:941`'s log text keeps reading the field — it describes the permit honestly. **L-2 unit line:** `unit before = bool(self._order_submission_permit is not None) at 5 sites; unit after = bool(self._submission_armed()) whose base body IS that expression; EQUAL for every non-subclass instance.` Characterisation, not a behaviour change — L-33 mutation evidence required (increment A).

**Subclass overrides — exactly three, each with its L-2 line.**

| Override | Purpose | L-2 unit line |
|---|---|---|
| `__init__` | forwards **every** parent kwarg unchanged (`trial_day_latch_factory`, `offer_tape`, `offer_tape_path`, `position_evidence_reader`), pins `order_submission_permit=None` and `phase0_permit_guard=True`, sets `self._backtest_submit_enabled: bool = True` once | unit before = ctor args; unit after = identical ctor args + one private bool. **EQUAL** — no new capability; `Phase0PermitForbiddenError` (`:156,191`) stays reachable and untouched |
| `on_start` | `isinstance(self.clock, TestClock)` else raise `ContinuousNotABacktestClockError`; then `super().on_start()` | unit before = any clock admitted; unit after = `TestClock` only. **STRICTLY NARROWER**, never looser |
| `_submission_armed` | `return self._backtest_submit_enabled` | unit before (parent) = presence of a sealed `OrderSubmissionPermit` ⇒ authority to reach `PolymarketUSExecutionClient._submit_order`. unit after (subclass) = authority to reach `SimulatedExchange`. **NOT EQUAL — declared a deliberate, subclass-scoped behaviour change, not a refactor.** Barriers: the TestClock assert; the one-importer AST pin; and the exec client's own independent deny `submit_chain.permit_is_missing(self._permit)` → `PERMIT_ABSENT_REASON` (`adapters/polymarket_us/exec/client.py:2665`), which no strategy-side override can reach |

**Byte-inherited (the goal-state claim; any of these appearing in the subclass FAILS the plan):** `on_order_book_depth`, `on_quote_tick`, `on_data`, `_hunt_tick`, `_maybe_submit`, `_rearm_permitted`, `on_order_denied`, `on_order_filled`, `_consume_or_flag_duplicate`, `_run_never_arm_walk`, `_join_fill_to_station_day`, `on_stop`.

**Byte-unchanged pins (by test name).** `tests/unit/test_continuous_rung_hold_strategy.py` (all); `test_continuous_rung_hold_fill_wiring.py` (all); `test_current_rung_hold_composition.py` (all); `test_current_rung_hold_backtest_only.py::test_the_backtest_only_strategy_subclass_has_exactly_one_importer`; `test_current_rung_hold_paper_replay.py::test_a_one_sided_depth_only_replay_delivers_on_order_book_depth_to_continuous_strategy`; `test_polymarket_us_readonly_guard.py` (B11 — **no new `OrderSubmissionPermit(` call site**); `test_order_submission_permit.py`; `test_order_submission_permit_issuance.py`; `test_paper_rows_never_pool_into_the_live_tally`; `test_live_family_tally_structural_dead.py`.

## 4. Increments (RED first)

| id | size | RED test(s) — file :: name | Minimal change | Observable that proves it | Verify |
|---|---|---|---|---|---|
| **A** | S | **CHARACTERISATION — no RED (L-33).** Mutation evidence instead: perturb the new base body to `return False`, then to `return True`; EACH perturbation must fail ≥1 existing test; restore GREEN. If a perturbation passes everything, that is a coverage hole — close it in A with a named assertion in `tests/unit/test_continuous_rung_hold_strategy.py` | `continuous_strategy.py`: `+_submission_armed`; 5 call-site edits (`:302,579,731,734,935`) | `MUTATION_RED_EVIDENCE` block: 2 perturbations, each with its failing test id, then the restored GREEN line | `scripts/ci/run_tests_no_egress.sh tests/unit/test_continuous_rung_hold_strategy.py tests/unit/test_continuous_rung_hold_fill_wiring.py tests/unit/test_current_rung_hold_composition.py`; `lint-imports`; `mypy src/breezy` |
| **B** | M | `tests/unit/test_continuous_rung_hold_backtest_only.py` :: `test_the_continuous_backtest_only_subclass_has_exactly_one_importer`; `test_on_start_refuses_a_non_testclock`; `test_on_start_succeeds_against_a_real_testclock_with_flat_startup_evidence`; `test_on_start_still_stops_when_startup_evidence_is_absent` (**L-24 negative fixture**); `test_the_armed_subclass_reaches_submit_order_where_the_parent_only_logs`; `test_the_subclass_never_holds_an_order_submission_permit`; `test_one_station_day_submits_at_most_one_order_across_many_eligible_depth_frames` | NEW `src/breezy/strategy/current_rung_hold/continuous_backtest_only.py` — the three overrides of §3, nothing else | 7 RED → GREEN; AST importer scan returns exactly `["scripts/analysis/current_rung_hold_paper_replay.py"]` | `run_tests_no_egress.sh tests/unit/test_continuous_rung_hold_backtest_only.py tests/unit/test_current_rung_hold_backtest_only.py`; `lint-imports`; `mypy` |
| **C** | S | `tests/unit/test_current_rung_hold_paper_replay.py` :: `test_the_strategy_flag_selects_the_continuous_backtest_subclass`; `test_the_default_strategy_is_still_the_v2_backtest_subclass` (golden); `test_the_continuous_arm_injects_flat_position_evidence_for_every_candidate_slug`; `test_the_result_carries_the_position_event_counts` | `current_rung_hold_paper_replay.py`: widen `strategy_cls` annotation; explicit `if strategy_cls is ContinuousRungHoldBacktestStrategy:` construction branch (never `getattr` duck-typing); `_flat_startup_evidence(instruments)` helper returning `{"v":1,"position_read_refused":False,"eof_complete":True,"fill_walk_complete":True,"positions":[{"slug":…,"net_position":"0"} …]}` for EVERY candidate slug (an absent slug is UNKNOWN ⇒ halt, `trial_day_latch.py:700-728`); `PrecisionArmResult += strategy_position_events`; `main()` `--strategy {current_rung_hold,continuous_rung_hold}` default `current_rung_hold` | 4 RED → GREEN; v2 default path byte-unchanged | as above + `run_tests_no_egress.sh tests/unit/test_whole_tape_paper_replay.py` |
| **D** | S | same file :: `test_a_depth_only_window_is_covered_for_the_continuous_arm`; `test_a_quote_only_window_with_no_in_window_depth_is_refused_for_the_continuous_arm`; `test_the_v2_arm_coverage_gate_is_unchanged` (golden) | `assert_decision_window_has_coverage(..., source: Literal["quote","depth"]="quote")`; the v3 arm passes `"depth"` | a depth-only fixture day runs; a depth-less day raises `NoDecisionWindowCoverageError` | as above |
| **E** | S | same file :: `test_a_latch_store_path_under_the_live_state_root_is_refused` | `assert_replay_latch_store_is_not_live(path)` mirroring `assert_paper_write_path_is_not_live`; called before any engine build | refusal names the path, no engine constructed | as above |
| **F** | L | **not a test — the real-artefact run (L-24 "one real run before calling it done")** | none | see §5 | see §5 |

**Increment F — the acceptance replay.** Day: **SFO 2026-09-01** (the whole-tape CLEAN winner that produced a v2 trial at both lags). The winner instance must be **re-derived by longest in-window DEPTH span**, never hand-picked: the whole-tape v2 winner work dir is `…/derived/paper_replay/work/attempts/SFO/2026-09-01/lag_30/3dd59abf-7656-4831-a5ab-3dee4e7928ab-1788632470693358575`, while the 09-04 evidence names `5a111bca-c349-49d7-94bc-948649485ac8` as the all-station 09-01 instance — both exist under `~/.local/share/breezy/catalog/quote_tape/polymarket_us/live/` (47 instances). Record which one the depth-basis selection picks and why.

```
systemd-run --user --scope -p MemoryMax=4G -p MemoryHigh=3G -- \
  .venv/bin/python scripts/analysis/current_rung_hold_paper_replay.py \
    --strategy continuous_rung_hold --station SFO --climate-day 2026-09-01 \
    --tape-instance-id <winner> --lag-minutes 30 \
    --quote-catalog ~/.local/share/breezy/catalog/quote_tape/polymarket_us \
    --work-catalog <FRESH EMPTY tmp dir> \
    --weather-catalog-root /home/jon/.local/share/breezy/catalog \
    --asos-cache-csv <see §9 UNVERIFIED> \
    --output-dir ~/.local/share/breezy/derived/paper_replay/scored_trials/v3/SFO/2026-09-01/lag_30
# no user D-Bus (bridge/headless): bash -c 'ulimit -v 6291456; exec .venv/bin/python …'
```

**Envelope (L-31).** `main()` calls `_select_capture_instruments` ONCE — the per-definition-row reselect trap lives in the whole-tape loader, already fixed and pinned by `tests/unit/test_whole_tape_paper_replay.py:948`. Budget from the post-fix note: **n=1 ≈ 80 s / ~674 MB** (UNVERIFIED against a fresh run — measure and record actual peak RSS + wall). Hard cap 4 GB as above. **Window:** never 16:40–17:10Z (v3 launch 16:50Z); avoid 13:30Z `mb-daily`, 22:30Z `k1-daily`, 22:45Z `offer-gate-daily` (each `MemoryMax=16G`, unserialised); ONE heavy job at a time; never signal, stop or restart the node or the recorder.

## 5. Acceptance — what the executing session must SHOW

1. `MUTATION_RED_EVIDENCE` for increment A: two perturbations, two failing test ids, one restored GREEN line.
2. RED→GREEN transcript for the 16 named tests in B–E (RED first, with the pre-change failure output).
3. Full gate: `scripts/ci/run_tests_no_egress.sh` — pass count ≥ the 8765 baseline; the only tolerated failure is the known clock-flaky `tests/unit/test_app_trade_main_permit_logging.py:115`. `lint-imports` clean; `mypy` no new errors under `src/breezy`.
4. Every §3 byte-unchanged pin still passing, unmodified (show `git diff --stat` proving no test file in that list changed).
5. `git grep -n "OrderSubmissionPermit(" src scripts` shows the SAME single construction site as at HEAD.
6. Subclass audit: `git grep -n "    def " src/breezy/strategy/current_rung_hold/continuous_backtest_only.py` lists exactly `__init__`, `on_start`, `_submission_armed` — no method from the byte-inherited list.
7. Increment F artefacts: the output dir; `provenance.json` with provenance **paper**; **either** `FilledTrial` count > 0 with per-trial `entry_ask / fill_px / fee / slippage` and the `trial_id` prefix line, **or** a documented zero carrying the full `strategy refusals`, `strategy diagnostics` and `strategy position events` histograms plus the depth-frame count in window; measured wall-clock and peak RSS; the chosen winner instance id and its in-window depth span.
8. A line stating the result is **MECHANISM TEST — NO VERDICT**, n < `MIN_NON_EXCLUDED_N` (30), and that no row entered `derived/scored_trials` or any live tally (`assert_live_only` still refuses the paper prefix).

## 6. Non-goals (scope guard)

No verdict, ROI inference, Wilson/BCa claim or PREREG citation from replay output — n≤1 is UNDERPOWERED by design. No amendment to PREREG v3 §3/§5/§9. No change to `CurrentRungHoldBacktestStrategy`, to the v2 driver default, or to the v2 quote-basis coverage gate. No minting of an `OrderSubmissionPermit` anywhere. No touch to live enablement, operator caps, the NO-SEND firewall, `allow_short`, the exec client, the adapters layer, or `runtime/node_config.py`. No whole-tape sweep (`whole_tape_paper_replay.py` stays v2-only this rev). No fee reconciliation, no resolver work. No new store, catalog or systemd unit. Nothing is executed in the planning session; no process is signalled, stopped or restarted.

## 7. Risks, blast radius, rollback

| Risk | Blast radius (codegraph) | Containment |
|---|---|---|
| Parent extraction changes live v3 behaviour | `ContinuousRungHoldStrategy` — 11 callers in `composition.py`, plus `app/trade.py` and 4 test modules | Pure predicate extraction; L-33 mutation evidence; §3 byte-unchanged pins; a live node is running v3 from 16:50Z — land A+B only after the day's session, or with the node restarted by the supervisor, never by hand |
| A subclass override leaks into a live node | one-importer AST pin + TestClock assert + exec-client `PERMIT_ABSENT_REASON` deny | three independent barriers; RED tests 1–2 and 6 of increment B |
| Replay touches the live latch/intent store | v3 reads `is_intent_open`/`is_family_halted` | increment E refuses a live-rooted store path before any engine is built; fresh empty work catalog per run |
| Synthetic flat evidence is a fixture that always satisfies the invariant (L-24) | `_run_never_arm_walk` | paired NEGATIVE test (`…still_stops_when_startup_evidence_is_absent`) and an explicit statement in the run artefact that positions are synthetic |
| Driver `strategy_cls` widening breaks the whole-tape caller | `run_one_precision_arm` — 3 callers (`whole_tape_paper_replay.py:510`, own `main`) | default stays `CurrentRungHoldBacktestStrategy`; golden test in increment C |
| Replay run starves the live node | 31 GB host, node + recorder + nightly 16G units | 4 GB cap, quiet window, one heavy job at a time |
| **Rollback** | — | revert the new module + the ≤6-line extraction + the driver diff; the extraction is the only live-file touch and is behaviour-identical for every non-subclass instance |

## 8. Rulings / operator items

| id | Item | Who decides | Options | Evidence needed |
|---|---|---|---|---|
| **R1** | v3 paper rows would use the v2-named `PAPER_TRIAL_ID_PREFIX` `paper_replay/current_rung_hold/trial` (`paper_replay.py:92`) | strategy lead | (a) keep the shared paper prefix — disjointness from live is already unforgeable via `assert_live_only`/`assert_paper_only` (`live_family_tally.py:148-180`); (b) add a family-distinct paper prefix for `pm_us_crh_cont` | Whether any consumer joins paper rows BY FAMILY. **L-32 prior rulings found and cited:** `docs/plans/WHOLE_TAPE_PAPER_REPLAY_2026-09-05.md:5,35,45` ("Zero paper rows in `derived/scored_trials` or PREREG v2"; never mint live ids; `assert_live_only` unmodified) and PREREG v3 §5 (residual classification). **No new ruling is required to BUILD this plan** — (a) is the default and is already enforced |
| **R2** | Confirmation that replay fills never enter live `n` | none needed — already binding | — | `assert_live_only` refuses a paper `trial_id`; `structural_dead`'s `filled_takes` is a live fill-store count, never `len(rows)` (`live_family_tally.py:254-268`). The run artefact must restate it verbatim; no PREREG statement is to be written or cited |
| **OP1** | None. No operator input is required: no budget, cap, enablement or live-trading gate is touched | — | — | — |

## 9. Citations (verified against the working tree today, 2026-09-12, HEAD e4848c3)

VERIFIED: `continuous_strategy.py:166,178,191,199,205,238,288,302,310,328,507,526,534,579,605,730,731,734,790,842,933,959`; `backtest_only.py:71,98,108,120-128`; `tests/unit/test_current_rung_hold_backtest_only.py:55,61,80,173,181,195`; `tests/unit/test_current_rung_hold_paper_replay.py:356`; `current_rung_hold_paper_replay.py:230-256,298-318,339-385,470-479,554-595,662-754`; `whole_tape_paper_replay.py:148-176,179-195,221-244,483-541,857-873`; `runtime/paper_replay.py:92,271-297,300-365`; `runtime/backtest_harness.py:663,957,1005,1027`; `runtime/order_enablement.py:154,166-175,177-242`; `strategy/current_rung_hold/trial_day_latch.py:337,513,579,641,667,684-698,700-728`; `adapters/polymarket_us/exec/client.py:2647-2716` (`:2665` `PERMIT_ABSENT_REASON`); `strategy/current_rung_hold/strategy.py:732-758`; `composition.py:205-251`; `app/trade.py:189,227-238`; `settlement/roi_bound.py:100,190`; `live_family_tally.py:148-180,254-268`; `docs/specs/BACKTEST_VENUE_CONFIG.md:3,57,144-150,174-180,246`; `docs/evidence/READINESS_AUDIT_2026-09-12.md` §2, §3 B3, S3 #3, S4 #1-#5; LESSONS L-2 (`:67`), L-22 (`:1017`), L-24 (`:1069`), L-31 (`:1248`), L-33 (`:1276`), L-35 (`:1304`); `~/.local/share/breezy/derived/paper_replay/WHOLE_TAPE_PAPER_REPLAY_REPORT.md`; installed-Nautilus controls in the L-1 table.

**UNVERIFIED — the executing session must resolve before increment F:**
1. `--asos-cache-csv`: no producer script exists under `scripts/` and no matching CSV was found under `~/.local/share/breezy` (searched to depth 4). `read_asos_rows` (`:290-293`) needs `station,valid,metar` columns. Locate or regenerate it; a missing file makes F unrunnable.
2. Which 09-01 instance the DEPTH-basis winner selection picks (`3dd59abf-…` vs `5a111bca-…`) — both are on disk; the v2 winner was quote-basis.
3. Whether SFO 2026-09-01 remains CLEAN under the depth-basis gate; and whether any post-2026-09-11T09:00Z day is CLEAN yet (audit S3 #5 records overlap > 0 everywhere at 09-11 and is itself marked UNVERIFIED).
4. The `n=1 ≈ 80 s / 674 MB` envelope is a carried-forward note, not a measurement at this HEAD.
5. Whether each increment-A perturbation actually fails an existing test — audit S2 #7 records no dedicated test for the evidence-based re-arm gate, so the armed branch may be partly uncovered.
6. Nautilus's intra-step ordering of `SimulatedExchange.process` vs the next data event (i.e. whether a fill is delivered before the following depth frame). Increment B's `…at_most_one_order_across_many_eligible_depth_frames` test is what settles it; do not assume it.
