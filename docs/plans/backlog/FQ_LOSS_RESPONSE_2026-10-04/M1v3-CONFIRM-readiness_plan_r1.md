# M1v3-CONFIRM-readiness plan r1 (draft, 2026-10-09)

**Status:** DRAFT r1. Needs peer review before any work package runs. It is new-feature scope, so the planning gate applies: trading-bot-architect, prediction-market-reviewer, python-reviewer, and security-reviewer (permit, live-orders gate and AST guard are touched).
**Plan of record:** `docs/evidence/DECISION_ROI_ROUTE_TO_TRADING_2026-10-09.md` ranking item 2, "M1-v3 readiness, as optionality".
**Governing rulings:**
- `RULING_FQ-v2-NO-TRADE_2026-10-08` (T1/T2/T3; a CONFIRM starts a new plan and never arms trading by itself)
- `RULING_B3_permit_window_posture_2026-09-25`
- `RULING_permit_daily_coverage_2026-09-25`
- operator 09-29 directive (prediction from US weather; venues as execution cost)
- operator caps: exactly two, already set in `operator.env`, never assigned here

**Hard rules for every work package in this plan:**
- No tape, settlement or truth outcome for climate days 2026-10-07..2026-11-28 is read before the frozen tool's single read on or after 2026-12-07.
- `docs/evidence/m1v3/PREREG.json` is never edited.
- Nautilus Trader is immutable.
- `allow_short` stays `False`.
- No safety, settlement, contract or firewall test is weakened. Where a guard changes shape, it is narrowed, and that change is reviewed.
- No operator-reserved control is read, assigned or named by value.

## 0. Scope, verified facts, and one correction to the readiness review

### Verified facts (read 2026-10-09)

| # | Fact | Evidence |
|---|---|---|
| V1 | The frozen M1-v3 pins a single window. `frozen_sha` is adb1cd8b, committed 2026-10-06T10:50:42Z, so `first_forward_day` = 2026-10-07, `last_forward_day` = 2026-11-28 and `read_date` = 2026-12-07. A verdict needs FINAL truth for every station-day, or `as_of` ≥ 12-21 (the truth deadline, first+75d). The pinned rule: window D_12Z, first Depth10 row in [12:00, 13:00) UTC; NO ask = 1 − best YES bid; ask ≥ 0.90 inclusive; cost = max(rounded fee, θ·a·(1−a)) + 1¢, θ = 0.0695. | `PREREG.json` |
| V2 | `PREREG.lane` says "A WINNER nominates only an execution-side admissibility filter on top of a weather-sourced NO decision, never a standalone signal" (M1V3-R1). The family proposed here contradicts that sentence, so the ruling in §A must override it explicitly. | `PREREG.json:34`; plan M1V3-R1 |
| V3 | `_compose_family` dispatches on `composition_kind` (`src/breezy/app/trade.py:906-955`). An unknown kind raises `SettingsError`. `CompositionKind` / `_COMPOSITION_KINDS` is a closed literal (`family_manifest.py:116-121`). It is mirrored in `persistence/autonomy/paths.py:28` and `analysis/autonomy/offline_plugins.py` ("exactly the four composition kinds"), and is test-pinned in `tests/unit/test_forecast_quantile_ladder_manifest_and_markers.py:41-46` and `tests/unit/test_autonomy_paths.py:139-142`. | codegraph / source |
| V4 | `_LIVE_ORDERS_ALLOWLIST` is a code literal of `(family_id, ruling_id, ruling_sha256)`. The ruling's live copy lives under `deploy/families/rulings/` and must be byte-identical to the `docs/evidence` copy. Any edit to the ruling fails the gate closed. | `src/breezy/persistence/live_orders_gate.py` |
| V5 | The AST guard permits exactly one non-`True` `shadow_only` expression, `not live_orders.enabled`. The check is path-scoped to `src/breezy/app/trade.py` and textually exact. Today it occurs once, at `trade.py:848`, inside `_compose_forecast_quantile_ladder`. | `tests/unit/test_shadow_only_false_is_only_the_gate_output.py` |
| V6 | **The permit does not cover 12Z.** The supervisor schedule is `STOP_PRIOR_UTC` 16:40, `LAUNCH_UTC` 16:50, `SELF_CHECK_UTC` 17:05 (`trade_supervisor_core.py:37-40`). The permit TTL is 10 h, giving a single mint covering 16:50Z → 02:50Z. RULING_B3 accepted the 02:50Z → 16:40Z gap only because no live decision window fell inside it. RULING_B3 §6 says a future family whose windows fall in the gap must re-open option (a′) at its own registration. D_12Z is [12:00, 13:00)Z, inside the gap. The cumulative-coverage cap forbids a second daily 10 h mint. | RULING_B3 §3–§6; RULING_permit_daily_coverage |
| V7 | The loss-floor MC hard-codes its design as module constants: `DELTAS` (−0.16, −0.08, −0.04), `_EPOCH_FIXED` {11-01, 11-15, 12-01}, `DEFAULT_FREEZE` 10-08, `HORIZON` 2027-01-25 (`fq_loss_floor_mc_gate.py:55-63`), and `MIXES` (M-pool, M-yes, M-no) (`fq_loss_floor_mc_engine.py:56`). The engine, report and NP-bound scripts import these constants directly. The α ladder (0.10, 0.20, 0.30), the G3 multiplier 2.5 and `T_MIN_GRID` are core constants (`breezy/analysis/fq_loss_stop_core.py:47-51`). Its template pool is the Kalshi pre-holdout tape run through the FQ model take rule (`fq_mc_livedata`). Under H1 the win probability is `be − |δ|` (`fq_loss_floor_mc_rows.py:310`). | source |
| V8 | The F6 loss-stop **producer was never built**. `LossStopProbe` reads `derived/fq-loss-stop/latest.json`; while that file is absent the verdict is UNKNOWN, which vetoes. The probe takes its path as a constructor argument. `_WRITERS` is empty, and a writer row may be added only while `reachable_floor` is true for a frozen amendment. | `loss_stop_probe.py:1-50,118`; `tests/contract/test_fq_loss_stop_writer_allowlist.py` |
| V9 | The node's `SUPPORTED_STATIONS` is (LAX, MDW, MIA, SFO). The PM.us HIGH surface has five cities, the fifth being NYC. M1-v3 pools every tape station. | `current_rung_hold/config.py:76`; memory polymarket-us-surface |
| V10 | `app/trade.py`, `settings.py` and `trade_supervisor*.py` belong to AUT-5 (AUT-5 r7 :979). AUT-5a (row 7a, WP1–WP9) adds a registry boot path and a required `entry_veto` slot on the FQ strategy. | AUT-5 r7 :410-414, :891, :979; PROGRESS row 7 |
| V11 | The venue shards subscriptions across connections because of its 10-per-connection cap (`PolymarketUSMarketsWebSocketPool`), so 30–40 D0 rungs are feasible. | `adapters/polymarket_us/factories.py:658-680` |

### Correction to the critical path

The readiness review's critical path is items 1–7. **Item 8 is added: the permit window (V6).** Without it, a ratified family boots at 16:50Z and is structurally unable to order at 12Z, and the "2–3 days" target cannot be met. Moving the decision to the D-1_18Z window, which the 16:50Z permit does cover, is **prohibited**. D-1_18Z is a labelled sensitivity, and trading it on the strength of a D_12Z CONFIRM is a forking path (§A.3).

## A. DRAFT ruling (item 1) — `RULING_M1v3-CONFIRM-T2-SENDER_<ratification-date>` (DRAFT, not in force)

**Type:** coordinator ruling under operator pre-authorization. The operator reserves only the two budget caps, and this ruling assigns, derives and names neither.
**Ratification requires all of:**
1. the frozen M1-v3 tool's single read returns **verdict WINNER**;
2. peer review converges: trading-bot-architect, prediction-market-reviewer, security-reviewer;
3. the family's own loss-floor prereg (§B) is frozen and its binding run returned **PASS** before 2026-12-07.

Until all three hold, this text is a draft. A draft has no force: no allowlist row may cite it, and no manifest may name it in `live_orders_ruling`.

### A.1 Condition

This ruling takes effect only if the report written by `scripts/analysis/no_longshot_pooled_test.py` meets all four conditions:
- it ran at a HEAD descended from `frozen_sha` adb1cd8b4ff2edec4130a5f2f055f2b93152b8bb;
- its status is READ, with `verdict == "WINNER"`;
- `bca_failed` is not true;
- it is committed under `docs/evidence/m1v3/`.

The ratified text pins that report's sha256. "CONFIRM" in this ruling means exactly this verdict, and nothing else.

### A.2 What is ruled (on CONFIRM)

1. **The T2 sender exists.** `pm_us_nolong_d12_v1`, composition kind `no_longshot_d12`, is a permitted T2 sender family under RULING_FQ-v2-NO-TRADE T2. That ruling requires the family's own prereg floor to pass the §4.6 gate for its own mix, and §B is that prereg.
2. **M1V3-R1's admissibility-filter sentence is superseded.** It is superseded only for the sender eligibility of the family below. The rest of M1V3-R1 stays, including AS-R6: Lane E output never enters model-variant evidence, and never enters `screen.py` or the AUT-S K=48 ledger.
3. **Reconciliation with the operator 09-29 directive.** The directive is "prediction inputs from US weather; venue prices enter only as execution cost". It was issued against a *circular* study, in which both edge terms came from venue prices.
   - In M1-v3 the outcome term is the NWS CLI FINAL settlement, a US weather source. The venue price enters as the cost term `ask + fee + slippage`. So the circularity objection does not apply.
   - The *letter* of the directive is still breached, because the price level selects the take. That breach is accepted here as a narrow exception for this one family. It is decided by the coordinator and adjudicated by the peer loop, not escalated.
   - **If any peer rejects this reconciliation, the ruling is not ratified and §A.5 applies.**
4. **The family's population must equal the screened population.** Every item below is fixed now, before the read:
   - Climate day D, D0 only.
   - Decision at the first Depth10 update the node receives with `ts_event` in [12:00, 13:00) UTC for each YES rung, with the NO ask computed as `1 − best YES bid` (size ≥ 1).
   - Take iff NO ask ≥ 0.90, inclusive, across the whole [0.90, 1.00] range with no sub-band.
   - BUY NO, qty 1, IOC, limit = that NO ask.
   - One evaluation per (station, D, rung); hold to settlement.
   - Stations: `SUPPORTED_STATIONS` ∩ the stations on the screen tape, i.e. LAX, MDW, MIA, SFO. NYC is excluded unless WP-0 shows it is node-supported, and that decision is recorded **before 12-07**.
5. **Live operation needs every native and Breezy gate.** These are the permit; the live-orders gate with a fresh allowlist row; the family halt latch; the fee-drift probe; the family loss stop from §B; the AMBIGUOUS-intent latch; and both operator caps, unchanged and enforced natively. The two caps are the only operator controls, and they are untouched.

### A.3 What the M1-v3 result may NOT be used for (no forking path)

The result may not be used:
- **(a) to change the window or the cost path.** No trading of D-1_18Z or D_17Z. No ask band [0.90, 0.97] or any other sub-band. No slippage 0 / 2 ¢ variant. No rounded-only or unrounded-only fee variant. These are labelled sensitivities in the prereg. A sensitivity that looks better is never a reason to trade it.
- **(b) to add filters that were not screened.** No depth threshold, no time-of-day rule beyond the window, no weather feature, no per-station selection after the read.
- **(c) as evidence for anything else.** Not for FQ v2, any NBM/forecast family, any model variant, or the AUT-S ledger (AS-R6). Not to re-open RULING_forecast_edge_programme_closes.
- **(d) as an edge-magnitude claim for sizing.** Size stays qty 1, and the expected value cited anywhere is the one-sided 95% lower bound, never the point estimate.
- **(e) to re-read, re-run or extend.** No second look, no extension of `sample_days`, no relabelling of UNDERPOWERED or PENDING_TRUTH as CONFIRM, no recomputation with different parameters (prereg `one_look`, M1V3-R23).
- **(f) to bypass the floor.** A CONFIRM with a §B floor that fails or is unrun does not authorize live orders.

### A.4 Relationship to existing rulings

- RULING_FQ-v2-NO-TRADE stays in force for FQ v2.
- This ruling uses its T2 route and does not re-open T1 for any other family.
- RULING_B3 option (a′) is re-opened by the **separate**, security-countersigned ruling in WP-4. This ruling depends on it and does not decide it.

### A.5 Outcomes other than CONFIRM

This section applies on NO-EDGE, UNDERPOWERED, INVALID, PENDING_TRUTH still unresolved at the 12-21 truth deadline, a §B floor FAIL, or a peer rejection of §A.2.3.
- The build is **shelved**.
- `deploy/families/pm_us_nolong_d12_v1.json` stays `DRAFT_NOT_REGISTERED`, or is deleted by a reviewed commit.
- No `_LIVE_ORDERS_ALLOWLIST` row is ever added.
- The composition kind may remain in code. It is inert: it cannot boot without a REGISTERED manifest, and it cannot send without an allowlist row.
- The branch is parked, nothing goes live, and the drop-in `fq-v1-halt-orders-off.conf` stays.
- The verdict is recorded in PROGRESS as the closure of the 09-14 NO-side-hunting question for this cell (M1V3-R11).
- Re-testing a related hypothesis needs a new prereg and a new plan. That is a new trigger, never a continuation of this one.

## B. Loss-floor MC/NP design for `pm_us_nolong_d12_v1` (item 4)

**Prereg artefact:** `docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04/NOLONG_D12_floor_prereg.json`.
**Freeze:** a dedicated commit on or before **2026-11-20**.
**Binding run:** 2026-11-21..11-27, one heavy job at a time, under a memory cap, with a stall watch.
**Result:** committed before **2026-12-06**.

Freeze, run and result all happen **before the M1-v3 read**, so the floor cannot be tuned to the read. The verdict binds either way: if the floor FAILs, the WP-1..WP-5 build is cancelled.

### B.1 Pre-declared design

| Element | Value | Rationale |
|---|---|---|
| Family / mix | One mix, **M-no90-D12**. Every leg is side `no`, built from pre-window D_12Z first rows with NO ask ≥ 0.90, for the stations of §A.2.4. A sensitivity mix M-no90-D12+NYC is reported, never selected. | It mirrors the screened population exactly. There is one mix, so there is no mix to choose between afterwards. |
| Data source | The PM.us Depth10 quote-tape catalog, climate days **2026-08-30..2026-10-06**, strictly before `first_forward_day`. The tool filters on the directory index **before** any tape read, and refuses (exit 3, nothing written) if any climate day ≥ 2026-10-07 reaches the reader. If truth is needed (only for `rho_hat`), it is read for climate days ≤ 2026-10-06 only. | Pre-window history only. The H0 and H1 draws need break-even values from asks, not outcomes. The 07-01 holdout seal applies to model scoring; this family is market-only (PREREG holdout_statement). |
| Leg break-even | `be = ask + max(venue_fee(ask), θ·ask·(1−ask)) + 0.01`, θ = 0.0695, using the screen's primary cost. | The same cost basis as the read. |
| α ladder | `ALPHA_FLOOR_GRID` = (0.10, 0.20, 0.30), imported. Escalation looks only at G1. A G3 miss at the selected α is a veto, never a reason to try a larger α (`fq_loss_floor_mc_gate.py` docstring, carried). | No new knob. |
| δ grid | (−0.16, −0.08, −0.04, −0.02), as absolute shifts of win probability (`h1_win_probability`). **The bar uses δ = −0.04.** −0.16 and −0.08 are reported for comparison with FQ; −0.02 (the MDE scale) is informational. | The payoff ceiling is 1 − ask ≤ 10 ¢. FQ's −0.16 bar is a 16 ¢-per-take collapse and is not the relevant failure for this family. −0.04 is the smallest shift that the arithmetic in B.2 makes detectable within the horizon. This choice is **stricter** than FQ's bar. |
| Epochs and horizon | Epochs are the candidate activation dates **{2026-12-09, 2026-12-16, 2026-12-23}**. Horizon is **2027-02-28**, which is also the family's `terminal_climate_day` unless a new prereg extends it. Activation after 12-23 is not permitted under this prereg. | The pass must hold at **every** epoch (as `epoch_holds` already requires), so an activation slip within two weeks cannot be gamed. |
| Bar (G-gate) | At the selected α, **G1 holds**, and **G3(−0.04) ≥ 2.5·α** at every epoch. | The existing §4.6 gate with this family's δ. |
| Bar (D1 analogue, Stage 0) | The NP upper bound on G3(−0.04) at the boundary's **effective** α (`α_eff`) is **≥ 0.30** at every epoch, with `e_proj` = 2026-12-23 pinned in the prereg. Switching to the nominal α after the result is **prohibited** (r2.1 C-7, carried verbatim). | This is the gate that killed FQ v2. It is re-run honestly here. |
| Seeds and replicates | A1-analogue seed 20261121, Stage-0 seed 20261122, 10k replicates each, pinned in the prereg. | Fixed before the run. |
| Stage −1 (descriptive, before Stage 0) | Report the distribution of station-day path length (ticks before the horizon) per epoch, takes/day (λ), legs per station-day, and the ask-bin mix. Committed before the Stage-0 run. **No verdict comes from Stage −1.** | It tests the hypothesis in B.2 before the binding run. |
| Refusals | The run refuses unless the prereg blob is frozen, `frozen_sha` is an ancestor of HEAD and introduced the blob (reuse `prereg_precommit_check.check_frozen_blob`, the M1V3-R26 pattern), and every climate day < 2026-10-07. | Tamper-evident freeze. |

### B.2 Why this family's paths should differ from FQ v2 — HYPOTHESIS, tested by Stage −1 and Stage 0

FQ v2 failed D1 because of path length.

| FQ v2 figure | Value |
|---|---|
| M-yes station-day path, median ticks before the horizon | about 7 |
| M-yes `α_eff` | 0.0187 |
| M-yes NP bound | 0.1186 |
| `bound_upper_min` at 11-01 | 0.125, against the 0.30 bar |
| A1 G3(−0.16) in M-yes at 10-08 | 0.2104, below 0.25 |
| M-no NP at `α_eff`, 11-01 | 0.4927 (passes) |
| M-no G3 at 12-01 | 0.2334, below 0.25: the late epoch left 56 days of horizon |

The hypothesis rests on three points:
- **Take density.** M1's D_12Z cell had about 11.7 NO≥0.90 takes per climate day (292 over 25 days). With 4 of 5 stations that is about 9.4 per day, or roughly 3 legs on each of about 3–4 station-days per climate day. From the last epoch (12-23) to the horizon (02-28) there are 68 days, so a path should have about 200–270 station-day ticks. That is 30–40× FQ's M-yes median of about 7, and should give a null rejection rate near nominal α rather than near 0.02.
- **Detectability.** The per-take SD is about 0.20 (PREREG `power_arithmetic`). A δ = −0.04 shift moves the mean by −4 ¢ per take. Reaching z ≈ 2.5 needs n ≈ (2.5·0.20/0.04)² ≈ 156 takes, about 17 days at 9.4 takes/day, well inside 68 days. δ = −0.02 needs about 625 takes, about 66 days, which is marginal; that is why −0.02 is informational only.
- **Mutual exclusivity.** Rungs within a ladder are mutually exclusive, so at most one NO leg per station-day loses. Variance is then bundle-bounded (exact H0 variance; operator ruling 09-14), not additive.

**Counter-hypotheses, also stated:**
- Fat-tailed single-loss days at a ≈ 0.97 (each loss costs about 0.97 against a win of about 0.03) may make the step clock's normal approximation poorly calibrated. Stage 0's NP bound measures this directly.
- The ask-bin mix in December–February may differ from autumn's.
- `step_clock`'s overround/YES-first shrink was built for FQ legs. An all-NO bundle with Σq ≤ 1 should be "feasible", but this is unverified. Stage −1 reports the share of feasible station-days, and if more than 5% are refused the run reports it and the floor is FAIL (pre-declared).

### B.3 Tooling reuse (WP-A, scripts only, before the freeze)

- **Design injection (smallest change).** Add a frozen dataclass `McDesign(deltas, epochs, freeze, horizon, mixes)` in `scripts/analysis/fq_loss_floor_mc_gate.py`, defaulting to today's constants. Thread it through `run_floor`, `prepare_mix_groups`, `fq_loss_floor_mc_report` and `fq_loss_floor_np_bound` as a keyword-only argument whose default reproduces the current values.
  - RED test `test_fq_design_default_reproduces_seed20261008_subset`: a byte-identical JSON on a fixed small subset/seed against the pre-change output.
  - RED test `test_np_bound_default_reproduces_seed20261009_subset`: the same check for the NP bound.
- **New template source:** `scripts/analysis/nolong_d12_mc_templates.py`, under 300 lines. It builds `StationDay`/`Leg` via `fq_loss_floor_mc_rows.make_station_day`/`make_leg` from the screen's own helpers (`market_calibration_scan._first_row`, `no_ask`, `venue_fee`, imported unchanged).
  - RED tests: `test_refuses_any_climate_day_on_or_after_first_forward_day`, `test_filter_applied_before_tape_read`, `test_be_uses_screen_primary_cost`, `test_single_window_D_12Z_first_row`, `test_no_ask_none_counted_not_synthesised`, `test_all_legs_side_no`.
- **Driver:** `scripts/analysis/nolong_d12_floor.py`, under 200 lines. It loads the frozen prereg, checks the freeze, and calls the A1 and Stage-0 entry points with `McDesign`.
  - RED tests: `test_refuses_unfrozen_prereg`, `test_refuses_alpha_switch_after_result` (no nominal-α path exists), `test_epoch_holds_required_at_every_epoch`.
- **Effort:** 2 agent-days to build plus about 1 day of review; the run itself is wall-clock. **Gate:** focused tests, mypy ratchet, `lint-imports` from the tree root ("N kept, 0 broken"), then the full gate via `scripts/ci/run_tests_no_egress.sh` with `--basetemp` under `~/.cache`.

## C. Code work packages (items 2, 3, 5, 6, plus 8)

**Schedule:** build **2026-11-28..12-06**; WP-A runs earlier per §B. Every package runs in its own worktree, fast-forwarded onto `feat/data-capture-and-risk` first, with PYTHONPATH set and the exact interpreter path in the brief (never `uv sync`). The manifest stays `DRAFT_NOT_REGISTERED`, and the allowlist row stays **absent** until §A is ratified. Implementation goes to tdd-guide seeded with the python skills; review goes to python-reviewer and prediction-market-reviewer, plus security-reviewer for WP-2 and WP-4.

**WP-0 Verify-first (read-only, 0.5 d, 11-28).** Each answer changes the build. Each must be confirmed against code or artefacts, never assumed:
- (a) Is NYC node-supported (registry settlement site, climate-day window, truth feed)? If not, the four-station set is recorded in the prereg of §B before its freeze; it must be decided by 11-20.
- (b) The AUT-5a merge state and its boot path: registry resolution, the `entry_veto` slot, and whether a registry CHAMPION event is needed for a new family.
- (c) The AMBIG-LATCH B activation state. An IOC miss is AMBIGUOUS and blocks further orders until it is retired, which matters for about 10 takes inside one hour.
- (d) The recorder's Depth10 emission rule, snapshot vs change-only, for parity of "first row".

**WP-1 Strategy, `src/breezy/strategy/no_longshot_d12/` (2.5 d).**
- Files: `config.py`, `decision.py` (pure: first-row selection, NO ask, take rule, latch key), `strategy.py` (a Nautilus `Strategy` subclass using native `subscribe_order_book_depth`, `order_factory.limit` IOC and `submit_order`; it reuses `PersistentQuantileLadderLatch`/`open_trial_day_latch` with its own key prefix), `composition.py`.
- `shadow_only: bool = True` is the config default, as the AST guard requires.
- RED tests:
  - `test_decision_parity_with_m1_selector_on_fixtures`: identical (station, day, rung, ask) to `market_calibration_scan._first_row` and `no_ask` on shared Depth10 fixtures.
  - `test_ask_090_inclusive_and_no_upper_subband`
  - `test_first_row_only_later_rows_ignored`
  - `test_outside_12_13Z_never_evaluated`
  - `test_d0_only`
  - `test_one_take_per_rung_day_latched_across_restart`
  - `test_buys_no_leg_only_never_yes`
  - `test_qty_is_one`
  - `test_empty_yes_bid_side_counted_no_take`
  - `test_try_submit_order_permit_then_veto_then_fee_verified`
  - `test_no_order_when_shadow_only`
- Offline replay check (not RED): a BacktestEngine replay over **pre-window** days 08-30..10-06 must reproduce ≥ 99% of the m1 take set, with mismatches listed.

**WP-2 Composition kind and dispatch, item 2 (1.5 d).**
- Files:
  - `persistence/family_manifest.py`: the `CompositionKind` literal and `_COMPOSITION_KINDS` gain `no_longshot_d12`.
  - `persistence/autonomy/paths.py`: the mirrored set.
  - `analysis/autonomy/offline_plugins.py`: a refusing plugin, as other kinds have.
  - `strategy/current_rung_hold/family_id_arg.py`: `HALTABLE_COMPOSITION_KINDS` gains the kind; `KINDS_WITH_EXIT_PATH` is unchanged.
  - `app/trade.py`: a `_compose_family` branch plus `_compose_no_longshot_d12`. It mirrors the FQ branch: halt-latch preamble, a `live_orders_authorized` call, the composed veto with `LossStopProbe(path=<nolong path>)` and parity `None`, the fee-drift probe, and `shadow_only=not live_orders.enabled`.
  - `tests/unit/test_shadow_only_false_is_only_the_gate_output.py`: **narrowed**. `_PERMITTED_PATH` becomes an exact set of (path, enclosing function) sites, `{(trade.py, _compose_forecast_quantile_ladder), (trade.py, _compose_no_longshot_d12)}`. The count must be exact, and each site must bind `live_orders` from a `live_orders_authorized(` call in the same function. This change needs security-reviewer sign-off.
  - The existing manifest/marker and autonomy-paths pin tests are widened by exactly one row (the L-12 pattern).
- RED tests:
  - `test_compose_family_dispatches_no_longshot_d12`
  - `test_unknown_kind_still_refuses`
  - `test_shadow_only_site_outside_named_functions_is_flagged`
  - `test_shadow_only_site_count_is_exact`
  - `test_nolong_composed_veto_order_halt_then_loss_stop`
  - `test_nolong_loss_stop_path_is_not_fq_path`
  - `test_draft_manifest_refuses_boot`
- **Focused gate must include:** the exec import-pin and firewall guards, the operator-control assignment scan, `test_node_composition_contract`, `test_native_order_cap_wiring`, all `test_autonomy_*`, and `lint-imports` (memories: focused gates miss the exec import pin and contract tests).

**WP-3 Manifest and allowlist (item 3, 0.5 d; the allowlist row is added at activation only).**
- `deploy/families/pm_us_nolong_d12_v1.json`: `status: DRAFT_NOT_REGISTERED`; `composition_kind: no_longshot_d12`; stations per §A.2.4; `taker_fee_coefficient: "0.0695"`; `d0_climate_day` set at activation; `terminal_climate_day: "2027-02-28"`; sentinel boundary and density artefacts (`not_applicable_*.json`); **no** `live_orders_ruling` key.
- RED tests: `test_nolong_manifest_is_draft_and_refused_without_allow_draft` and `test_nolong_family_absent_from_live_orders_allowlist` (a pin that is removed in the activation commit by the same reviewed diff that adds the row).
- `_LIVE_ORDERS_ALLOWLIST` is **unchanged** in the build.

**WP-4 Permit window, per-kind launch schedule (item 8, 2.5 d; ruling first).**
- First, a ruling: a re-open of B3 (a′), "per-kind single daily mint", countersigned by security-reviewer.
  - One mint per day, TTL unchanged at 10 h, no second process.
  - For `no_longshot_d12`: STOP_PRIOR 11:20Z, LAUNCH 11:30Z, SELF_CHECK 11:45Z; the permit covers 11:30Z → 21:30Z, which spans [12:00, 13:00)Z.
  - The mid-day relaunch window and the cumulative-coverage cap are re-derived for this schedule.
- Code:
  - `trade_supervisor_core.py`: a code-literal table `SCHEDULE_BY_KIND` whose default row equals today's constants, selected by the sending manifest's `composition_kind`. It is never read from env or data.
  - `trade_supervisor.py`: the call sites.
- RED tests:
  - `test_default_kind_schedule_byte_identical_to_constants`
  - `test_nolong_permit_covers_12_13Z`
  - `test_single_mint_per_day_under_nolong_schedule`
  - `test_cumulative_coverage_cap_holds_for_nolong_schedule`
  - `test_schedule_not_env_overridable`
- Owner conflict: AUT-5 owns this file (see WP-6).

**WP-5 Exit/hold, loss stop, demotion/kill (item 5, 2 d).**
- **Hold:** hold to settlement. There is no exit seam (`KINDS_WITH_EXIT_PATH` is unchanged). Reconciliation applies the leg sign, because the venue nets a NO holding as short YES.
- **Loss-stop producer:** a new `breezy-nolong-loss-stop` oneshot timer. It reads this family's settled fills and FINAL truth, replays `fq_loss_stop_core.step_clock` with the boundary selected by the §B run, and writes `loss_stop/v1` to `$DATA/derived/nolong-loss-stop/latest.json`. The contract test's `_WRITERS`/`_AMENDMENT_FILES` gain exactly one row each, tied to the frozen §B amendment while `reachable_floor` is true. That is the test's own designed widening path.
- RED tests: `test_producer_digest_recomputable`, `test_producer_refuses_other_family_fills`, `test_missing_artefact_vetoes`, `test_fail_sets_family_halt_set_only`.
- **Pre-declared demotion and kill rules.** Every one acts through the existing set-only family halt. None re-arms automatically; re-arming needs a new plan.
  - (K1) Loss-stop FAIL: terminal.
  - (K2) Fee-drift probe mismatch: halt, per existing behaviour.
  - (K3) Execution parity. Over the first 20 live takes, more than 20% of fills with price ≠ the decision NO ask (beyond one tick), or more than 30% IOC misses or AMBIGUOUS, triggers a halt and a parity report.
  - (K4) Population drift. Live takes over any 10 consecutive trading days below 50% of the M1-v3 report's forward take rate triggers a halt, as a mismatch with the screened population.
  - (K5) The horizon `terminal_climate_day` 2027-02-28.
  - (K3) and (K4) are computed by the daily digest (`decision_funnel_daily_digest`), which pages; the coordinator applies the halt via the halt CLI the same day.

**WP-6 Merge order with AUT-5a (item 6, 0.5–1 d).**
- If AUT-5a has merged by 11-28: WP-2 and WP-4 rebase onto it. `_compose_no_longshot_d12` takes AUT-5a's manifest-object signature and registry boot. If AUT-5a's registry source needs a CHAMPION event for a new family, a bootstrap row is added to WP-3.
- If AUT-5a has not merged: WP-2 and WP-4 land first as one small diff (about 150 lines in `trade.py`, about 80 in the supervisor). AUT-5a's next rebase absorbs them, coordinated by the coordinator, never by a sibling agent.
- In both cases: run the full gate after every merge, and run `test_shadow_only_*` and the import pins at each step.

**Effort total:** about 12 agent-days for WP-0..6, plus about 3 for WP-A. That is tight for a 9-day window, so it is parallelised. The independent packages WP-1, WP-4 and WP-5 run in parallel worktrees. WP-2 follows WP-1, WP-3 is trivial, and WP-6 comes last. A WP-A floor FAIL on 11-27 cancels all of them.

## D. Activation runbook (item 7), on CONFIRM only

**Day 0 (on or after 12-07, single read):**
1. Run the frozen tool once, with no `--as-of` override.
2. Commit the report.
3. If the verdict is not WINNER, apply §A.5 and stop.

**Day 0–1 (ratify):**
4. Finalise §A with the report sha256, plus the §B result and the WP-4 ruling shas. Run the peer loop on that text.
5. Commit the ruling to `docs/evidence/` and a byte-identical copy to `deploy/families/rulings/`.
6. In one reviewed commit:
   - flip the manifest to `REGISTERED`, add `live_orders_ruling`, set `d0_climate_day`;
   - add the `_LIVE_ORDERS_ALLOWLIST` row with the pinned sha;
   - swap the WP-3 pin test.
7. Run the full gate (23–25 min). Read `GATE_EXIT` **before** any merge or push.

**Day 1–2 (deploy):**
8. Edit `deploy/systemd/breezy-trade-supervisor.service`, which is symlinked live, so this is one daemon-reload away from production: `BREEZY_SENDING_FAMILY_ID=pm_us_nolong_d12_v1`. Commit it, gated.
9. Remove `~/.config/systemd/user/breezy-trade-supervisor.service.d/fq-v1-halt-orders-off.conf` as a **reviewed act**: an evidence note citing the ruling, plus a one-line heads-up. Snapshot the file to the scratchpad first.
10. `systemctl --user daemon-reload`, then restart the supervisor **inside the window that is quiet under the active schedule**. Under the current FQ schedule that is 01:00–16:40Z. Under the WP-4 schedule, avoid [11:20Z, 13:15Z]. `KillMode=process` keeps any running node.
11. **Operator items:** none to act on. The two caps are already set in `operator.env`; nothing here reads, assigns or names them.

**Day 2–3 (first trading day, positive controls on the bot's own evidence):**

| Time | Check |
|---|---|
| 11:30Z | Launch. The boot-time permit line is present and unexpired. |
| — | `boot_family id=pm_us_nolong_d12_v1`; the live-orders line shows `enabled=True reason=ok ruling_sha256=<pinned>`. |
| 11:45Z | Self-check result PASS. |
| [12:00, 13:00)Z | Take lines and IOC outcomes. Every AMBIGUOUS is resolved by GET. |
| — | The loss-stop probe reads the producer artefact, not UNKNOWN (the producer seeds PASS at n = 0 per its schema). |
| — | Liveness = process + log mtime + permit unexpired + tape advancing. |
| D+1 | Settlement reconciliation with the leg sign applied. |
| D+1 | The digest's K3/K4 fields are populated. |

Evidence goes to the node's log files, not journald.

**Rollback:** set the family halt via the CLI (immediate), then restore the drop-in and restart within the quiet window.

## E. Risks

| # | Risk | Severity | Mitigation |
|---|---|---|---|
| R1 | **P(WINNER) ≈ 0 (dominant).** The prereg's own prior: the D_12Z cell CI upper bound is +0.79 ¢ before slippage, so a +2 ¢ edge is essentially excluded. Expected verdict: NO-EDGE or UNDERPOWERED. | Dominant | The whole plan is option value. WP-A runs first and cheaply; the build is cancellable at 11-27. |
| R2 | **A WINNER is weak evidence.** At α = 0.05 under a prior P(edge) of only a few %, P(edge \| WINNER) is roughly 50%. | High | Qty 1, the §B loss stop at δ = −0.04, K3/K4, and the horizon. |
| R3 | **Selection bias and transport from a single window.** D_12Z, the 0.90 threshold and the NO side were all chosen after M1. D_12Z was the *worst* M1 cell, which biases toward NO-EDGE; but the hypothesis family itself came from M1's three cells, with K=1 declared. The window is Oct–Nov, about 40 day-clusters; live trading is Dec–Feb, a different season with different tail behaviour. Whole-station-day exclusion is MNAR. | High | §A.3 bans every fork. K4 detects population drift. The §B epochs are Dec-dated. Seasonality is disclosed in the ruling. |
| R4 | **Permit gap (V6).** It is unfixable without a security-countersigned schedule change touching AUT-5-owned files. | High | WP-4 ruling first; the default schedule stays byte-identical. |
| R5 | **Reconciling with the operator 09-29 directive may be rejected by a peer.** | Med | §A.5 shelves cleanly. |
| R6 | **Execution parity.** The screen is execution-blind: IOC at the ask is assumed filled. In practice an IOC miss → AMBIGUOUS → the latch may block the rest of the hour. "First row" may differ between recorder and node. | High | WP-0(c)/(d), the WP-1 replay, K3. |
| R7 | **Operator caps may truncate the take sequence** (about 10 takes × about $0.95 per day). The live population would then be a time-ordered subset. | Med | Disclosed and reported in the digest. Caps are never changed or requested. |
| R8 | **Fee drift.** θ has drifted before. | Med | Fee-drift probe halts; the cost basis is pinned in the manifest. |
| R9 | **Calendar.** Truth lag can push the read to PENDING_TRUTH (up to the 12-21 deadline). The build window competes with AUT-5a. The new loss-stop producer is unbuilt code. | Med | §B epochs to 12-23. WP-6. Producer tests. |
| R10 | **Contamination.** Accidentally reading window tape during WP-A or WP-1 replays. | High | Hard date filters before any read, RED tests, and briefs restating the 10-07..11-28 ban. |

## F. Expected value (honest)

**Direct trading value is about zero.**
- P(WINNER) is small; the prereg says "close to zero". A working figure of 1–3% is not computed here.
- Even given a WINNER, P(true edge > 0) is about one half.
- At qty 1 with about 9–12 takes a day, a true edge of +1–2 ¢ a take is worth about $0.10–0.25 a day, or $4–8 a month, before any loss-stop false alarm.
- **Expected direct P&L is cents.**

**The real payoff is structural option value.**
- A ratified, floor-passing T2 sender is the only route identified before 2027 that un-gates the live stages of AUTONOMY rows 7b and 8–12 (AUT-1b live, AUT-4 live-sequential, AUT-5b, AUT-7b). It also produces real fills for the learning loop.

**Cost:**
- About 3 agent-days for WP-A, which also yields a reusable, design-parameterised floor tool.
- About 12 agent-days for WP-0..6, spent only if the floor passes.
- Reviewer cycles on top of both.
- Most of the build (the per-kind supervisor schedule, the loss-stop producer, the narrowed AST guard) is reusable by any future sender. That lowers the net cost of a likely NO-EDGE outcome.

**Recommendation:** run WP-A on schedule. Build only if the §B floor passes by 11-27. Treat CONFIRM as a coin-flip signal that buys a deployed sender, not as evidence of an edge.
