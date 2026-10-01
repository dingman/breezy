# Trading-reliability peer review of PLAN_Rev1 (refactor)  -- read-only, blind

Verdict: **APPROVE-WITH-CHANGES** (Phase 0, Phase 2 minus R2.2, R1.3/R1.4/R1.5 may proceed; the LIVE
steps R1.1, R1.2, R3.1, R3.2, R3.4, R3.5 are NOT approved as written; see E).
Tags: CONFIRMED = I read the code/test; HYPOTHESIS = inferred. Cap values never read or named.

Context facts (CONFIRMED): the unit sends `pm_us_crh_fq_v1` (deploy/systemd/breezy-trade-supervisor.service,
`Environment=BREEZY_SENDING_FAMILY_ID=pm_us_crh_fq_v1`); manifest d0 = 2026-10-02
(deploy/families/pm_us_crh_fq_v1.json). FQ is at its first live day, under an operator ruling that
overrode the shadow-parity period (docs/evidence/RULING_operator_fq_live_real_orders_2026-10-01.md). Every
code change merged now changes the code of the only live family at the next spawn, before its live proof
(FQ_GO_LIVE_PLAN_2026-10-01.md section 5 "Live proof") has had a chance to complete.

## (A) Per-LIVE-step risk table

Schedule facts (CONFIRMED, runtime/trade_supervisor_core.py:34-47,1077-1081): STOP_PRIOR 16:40Z,
LAUNCH 16:50Z, SELF_CHECK 17:05Z (window to 17:10Z), boot-retry 8x15 min after launch, MIDDAY_WATCH
(relaunch 3x/5 min) closes 01:00Z. The node is a 24 h process; after 01:00Z nothing respawns it until
16:50Z except a human. Timers read src from the primary tree the moment a merge lands
(deploy/systemd/*.timer: 01:20 triage, 02:05 nbp-learning, 09:00 rotate, 09:20/09:25, 11:10 fee-evidence,
13:30 asos, 14:15 score-live-trials, 14:30 live-tally, 15:00..15:50 reports/replay, 17:20 family-tally@,
17:40 portfolio-roi, quote-tape-ingest-frequent every 15 min).

| Step | What the node/supervisor loads | Worst credible failure on regression | Detectable before 16:50Z? | Verdict |
|---|---|---|---|---|
| R0.1 comments (client.py, trade.py, operator_controls.py, signing, write_transport) | all of them at spawn | Practically nil at runtime. Only real risk: a text-scanning pin (L-54) or a census (L-39) trips on an edited comment in `operator_controls.py` (the one module allowed to name the reserved controls) | Yes, gate | OK. Keep out of any commit that also moves code. "LIVE" label is correct but harmless |
| R1.1 StateStore protocol | `runtime/submit_intent.py` (the order gate latch), ingest gate/gaps/product_index, loaded by node, `clear_submit_intent_cli`, `set_family_halt_cli` | **Placement is wrong as specified** (finding B1): the proposed leaf `breezy/persistence/state_store.py` executes `persistence/__init__.py`, which imports `persistence.catalog` -> `nautilus_trader` + `domain` `register_arrow` side effects (catalog.py:198-204; persistence/__init__.py:8-30). The four docstrings exist to prevent exactly this. Consequence: import-order change on the node; heavier import chain in the operator kill-switch/clear CLIs (HYPOTHESIS: new failure surface for the halt tool) | Yes (import tests) but the harm is structural, not a test failure | **NOT approved as specified**; drop or re-place (see E3) |
| R1.2 timer bridge | `NbmQuantileActor` (feeds FQ; app/trade.py instantiates it), `NwsObservationActor`, optionally `fee_drift_probe` | Forecast feed never fires or inflight miscounted -> FQ refuses `forecast_unavailable` (fail-closed, silent no-trade for a day; NBM_NBP_STALE_CYCLE alert exists). Worse variant: fee_drift_probe loses its supervision and `is_fee_verified` stays stale-true after a death -> trades at a drifted theta (HYPOTHESIS, the fix is to leave the probe out) | **No**: the old-code node cannot show a regression in code it never loaded. Only tests can | **MAJOR changes** (B3, E4) |
| R1.3 Node protocol | trade_cli/cli/quote_tape_cli | ImportError at node boot -> no node (loud, caught by any import test; `Restart` + boot-retry + SELF_CHECK page) | Yes | OK, typing only; fold into an off-hours batch with R1.4 |
| R2.4 `decision.py` public aliases | `current_rung_hold/decision.py` (CRH; not the sending family) | Nil if pure alias; trips AST guards if a module-level name is added to a pinned module | Yes | Drop (YAGNI; R0.6 suffices, plan already allows this) |
| R3.1 `app/trade.py:run` split | node boot path of the sending family | **Silent loss of the only FQ stop**: if the shared halt-latch preamble is parametrised with the wrong key prefix/latch type, the per-family halt veto reads the wrong namespace and a halted family trades (fail-open). Also: omitted `required_fee_coefficient` kwarg silently falls to a stale default (CRH config.py:233 `Decimal("0.06")`; composition.py:476) -> drift probe DISAGREE -> self-inflicted halt. Boot lines/permit line/exit codes also parsed by supervisor | Partially: only if a through-`run()` FQ halt test exists. **It does not** (B2) | **BLOCKER until CT-12 exists** |
| R3.2 supervisor split | `trade_supervisor.py` is the daemon; **`app/trade.py:145` lazily imports `trade_supervisor_core.PERMIT_EXPIRY_CEILING_NS_ENV_VAR` inside the node**, so core is also node-loaded (CONFIRMED) | (1) Supervisor crash-restarts into the new code at any time (Restart=always, StartLimitBurst=5/h) -> no 16:50 launch -> silent no-trade day. (2) Old supervisor + new node-loaded core = mixed versions across the spawn boundary. (3) Pure/IO split reorders "spawn then persist state": `_do_midday_watch` returns `record_midday_relaunch_attempt(state, now)` only AFTER spawn (trade_supervisor.py ~2016), so budget accounting is order-sensitive. Double node is contained by the flock (FAIL_MULTIPLE_FLOCK_HOLDERS), so the failure is "no node", not "two nodes" | Only via import smoke + restart | **MAJOR changes** (E6) |
| R3.4 continuous_strategy split | module-scope imported by `app/trade.py` for every boot, including the FQ boot that does not use it | ImportError/NameError in new siblings kills the FQ node boot. Log markers keyed on class names (`"ContinuousRungHoldStrategy subscribed"` etc., core:161-166) break self-check if a class is renamed/moved with a different component name. v4 is A1-halted, so decision-logic regressions are not live-money; the import path is | Yes via import + `test_forecast_quantile_ladder_boot` (runs real `run()`) | Acceptable late; require marker-name pin (E7) |
| R3.5 resolver extraction | the AMBIGUOUS resolver = the doubled-position guard (L-36) | Resolver retires intent with wrong evidence -> either permanent OPEN-intent deadlock (L-48) or retires a real fill as zero-fill -> **duplicate position**. Also: allowlist callees are keyed on `self.` receivers (`self._latch.current_open`, `self._store_get`, test_execution_egress_firewall_guard.py ~2118-2135), so moving to free functions rewrites dozens of strings, not "one reviewed row" | Tests are the only line (118 private asserts in the 6,989-line file) | **Reject for this cycle** (defer, only as a mixin if ever) |

Unmarked-but-should-be-LIVE: R1.2's fee_drift_probe leg; R2.2 (not order path, but the KILL/SURVIVE verdict
path, consumers fire 14:15/14:30/17:20); R3.3 (timer fires within 15 min); R1.4/R1.5/R3.6 (long-running
`breezy-nws-ingest`/quote-tape services take them at any OOM/restart, not at a scheduled time).

Merge-window rule (plan lines 233-236) assessment:
- 01:15Z-14:00Z fits the supervisor schedule (CONFIRMED: midday watch ends 01:00Z, STOP_PRIOR 16:40Z).
- But the safety argument "revert + 25 min gate fits before 16:40Z" assumes a regression is observable
  before 16:40Z. For node-loaded code it is not: the running node holds the old code (apart from the lazy
  runtime imports below). Detection must be a pre-spawn boot smoke of the composed FQ node on the integration
  tree (scratch store/catalog, orders not requested), not the clock. MAJOR (E2).
- Lazy imports (CONFIRMED, /usr/bin/grep): 83 indented `from breezy` imports in src; non-TYPE_CHECKING
  ones run in a live node after merge, e.g. `app/trade.py:144-145,998`, `node_config.py:119,534,689,878,907`,
  `ingest/nws_actor.py:2218` (`persistence.catalog`), `ingest/routing.py:814`. A mid-day merge that moves a
  symbol without a re-export breaks an already-running process on first call (an L-16 silent discard on a
  timer thread). "Loads at spawn" is therefore not strictly true. Rule: any move in this set must keep
  re-exports until the next spawn has proven out.
- Supervisor restart "inside 01:00-16:40Z" is not an optional follow-up: after a merge touching
  `trade_supervisor*`, a supervisor crash at any hour restarts into unreviewed code. Restart + observed
  heartbeat must complete the same day, early (<= 14:00Z, not 16:30Z).
- Timer-fed code (R2.2/R2.3/R3.3) goes live immediately; 14:00Z leaves 15 min to the 14:15 scorer. Use an
  earlier cut-off (suggest 10:00Z) for scripts/ and analysis steps, plus one manual consumer run vs baseline.
- Merge-then-gate (L-43) puts unverified code in the primary tree for ~25 min. Require the pre-merge gate to
  run on the rebased tip (agent worktrees start stale; memory) and fast-forward only, so the post-merge gate
  is confirmatory.

## (B) State integrity and recovery findings

B1 [CONFIRMED] R1.1 premise fails its own check. `persistence/__init__.py` imports `persistence.catalog`
(imports `nautilus_trader` and `breezy.domain.*`, whose `__init__` imports register_arrow types). `domain`
also imports Nautilus; `registry`/`settlement` have thin inits but sit in the wrong layers for a persistence
protocol, and `exhaustive = true` layers (pyproject.toml:73-96) forbid a new top-level package without a
layer entry. Benefit is ~30 LOC; cost is touching the order-gate latch and the halt CLIs. Drop, or define the
Protocol once in `runtime/submit_intent.py`-independent stdlib module only if a layer-legal import-free home
is proven by an import-graph test.

B2 [CONFIRMED] The single live FQ stop has no through-`run()` test. `tests/unit/test_app_trade_family_halt_binding.py`
tests are cont/v4 only (zero hits for `forecast_quantile`/`pm_us_crh_fq`); `test_forecast_quantile_ladder_boot.py`
drives the real `run()` for FQ but never mentions halt. `test_operator_caps_through_the_live_composition.py:_compose`
**re-implements** the wiring ("mirrors app/trade.py 730-734, 743, 744"), so it will stay green when R3.1
changes the real one (an L-55 shape: a parallel reimplementation). Needed before R3.1: CT-12, boot the FQ
manifest through `run()` with the FQ halt row written by the real writer (`record_policy_halt` / set-family-halt
CLI path, L-42), assert the composed `submit_veto` refuses, and the unhalted twin permits. Behavioural.

B3 [CONFIRMED] The "identical" timer-bridge copies are not identical. `nws_observation_actor.py:_on_probe_done`
calls `_settle()` at entry, again on the success path, and `_record_task_death` settles again (inflight goes
negative by one per poll); `nbm_quantile_actor.py:_on_poll_done` settles exactly once per path;
`fee_drift_probe.py:_on_probe_done` has no `_settle` at all and logs ERROR with no fail-closed hook. A helper
that "owns `_settle`" will change observable `inflight` for the observation actor and its `on_stop` quiescence
(HYPOTHESIS on consumer impact). Pin current `inflight` sequences per actor before unifying; the
`_rebuild_trusted=False` hook is the only fail-closed side effect and needs its own death test.
`tests/contract/test_live_timer_thread_affinity.py` (the plan's first acceptance item) pins Nautilus
behaviour only (module docstring); it does not exercise any Breezy bridge. CT-4 (nws_actor `ts_init`
nudge) is the wrong characterisation for R1.2.

B4 Durable intent/latch semantics. R1.1 changes imports only; semantic protection is
`tests/unit/test_submit_intent_latch.py` (873 lines, includes `reconcile_at_startup` crash-between-two-sets
cases per submit_intent.py history-key ordering) and `test_polymarket_us_submit_order_chain.py`. These are
behavioural at the latch API (HYPOTHESIS on fixture store type; confirm they use the real
`SqliteStateStore` per L-42). The R1.1 change cannot alter them unless an import side effect does, which is B1.

B5 AMBIGUOUS-on-boot / OPEN-intent deny. Protected by `test_current_rung_hold_ambiguous_resolver.py`
(6,989 lines, 118 private-attribute asserts, implementation-coupled per S3) and `test_fq_caps_and_ambiguous_2026_10_01.py`
(behavioural: `test_fq_order_resolved_ambiguous_then_the_next_take_is_latch_refused`). CT-1 (public-port,
no second POST) is the right new test and is a hard precondition for any R3.5-like step; it must also assert the
retirement reason literal and that the AMBIGUOUS spend is NOT lost within the process (C9 gap is existing
behaviour; do not "fix" inside a refactor).

B6 PASS_ADOPTED_LOG_UNKNOWN. The decision is already a pure function in core (core:636-677, `log_available=False`
branch); `test_trade_supervisor.py:971,985` and `test_trade_supervisor_core.py:83` are behavioural. R3.2 moves
the I/O shells, not this function, so the risk is the shell: adopted-pid with unknown log must not trigger a
spawn (`test_adopted_unknown_log_node_dies_transient_and_owned_is_false_so_nothing_spawns`, :5021, behavioural).
Keep all four `os.fork()` tests (:2554,2735,2748,2762) through R3.2 and one full post-R3.2 daily cycle;
BC-13 (replace 3 of 4 with a process double) must come AFTER, not alongside, because only the forks exercise
real flock-holder counting.

B7 Permit TTL / A-1 ceiling. `PERMIT_EXPIRY_CEILING_NS_ENV_VAR` is defined in core:128 and consumed lazily
by the node (`app/trade.py:144-145`): a rename/move in R3.2 breaks the node, not the supervisor. Existing
coverage: `test_runtime_order_guard_permit_expiry.py`, supervisor tests asserting adopted-permit replay
(:6244,6282,6304). Add to CT-8: the env-var literal and its injection by `_do_midday_watch` to the child env
(spawn_node env/argv byte-stable; hand launcher mirrors it, C6).

B8 Per-family halt literals. The cleared-marker/prefix literals appear only in core and are pinned by
`test_trade_supervisor_cont_self_check.py` (CONFIRMED: sole test reference). Pins against the strategy-side
copy (`trial_day_latch.py`) are in `test_edge3_per_family_halt.py` (HYPOTHESIS: byte comparison; confirm both
sides are asserted against each other, not each against its own literal). A L-48 clearing-path test for
FQ (set -> self-check FAIL -> clear -> PASS) should be in CT-8.

B9 Ledger `seed_spent`. Seeded once per process from durable fills in `exec/client.py:2268` (`_connect`);
`max()` with in-memory, once-flag (`operator_controls.py:307-334`). No listed step edits it directly, but
R3.1 (single construction site `factories.py:862`) and any state-store move feed it. Coverage:
`test_operator_reserved_controls.py` and `test_operator_caps_through_the_live_composition.py` (the latter
partly mirrored wiring, B2). CT-3 is appropriate; add a restart-reseed case through `run()` composition
(not a mirror) after a midday relaunch.

B10 Crash-recovery ordering in R3.2. Add a failure-injection characterisation (CT-13): record call order
(spawn vs state persist) in `_do_midday_watch`/boot-retry shells, and assert a crash between spawn and persist
re-adopts rather than re-spawns. Today the order is "spawn, then return new state for the caller to
persist" (HYPOTHESIS that a crash window exists; contained by flock either way).

## (C) Market-mechanics findings

C-1 [CONFIRMED] The plan never folds fee functions, book walks, or `margin`/`scoring.margin` (BC-9 "not
recommended"; section 3.1 row for FQ/ladder_ev). Concur. R2.4's `_fee` alias keeps Decimal HALF_EVEN; the
alias must be assignment-only. Concur it should be dropped.

C-2 [CONFIRMED, correction to C10] The plan's C10 path is imprecise. `family_tally_v2.py` imports only
`ASK_BANDS, classify_ask_band` from `mb_current_rung_edge_study` (family_tally_v2.py:85) and computes cost
from real fill fees (`cost=t.fill_px + t.fee`, :566). The stale `FEE_THETA = 0.06`
(mb_current_rung_edge_study.py:195) reaches `break_even`, consumed by `live_family_tally.py`,
`structural_dead_stop.py` (docstring :4), `k1_*`, `band_decider_stage0b_screen.py`, and the separate literal
`DRIFT_FEE_THETA = 0.06` at `crh_group_sequential_boundaries.py:109`. Also stale defaults live in src:
`strategy/current_rung_hold/config.py:233` (`Decimal("0.06")`), `ladder_ev/config.py:154`,
`composition.py:476`. FQ is safe (`forecast_quantile_ladder/config.py:73` defaults 0.0695 and the composition
only overrides when a manifest value is passed). Restate C10 precisely and keep "byte-for-byte" for the named
literals, not for family_tally_v2's pnl path.

C-3 [CONFIRMED] R2.2 vs PREREG outputs. The moved cores (`_admit_fill`: qty==1 refusal, `fill_below_ask`,
`fee_unverified`; `compute_residual`: `qty*(fill_px+fee)`; `read_filled_trials_state_db`: positive control
BLOCK-1.2) define what counts toward the KILL. A wrong move silently changes admission. Required: golden
baseline per plan, PLUS (i) a test that the reader still opens `mode=ro` and cannot write (fill_time_count.py:94
`?mode=ro` uri; single-writer discipline vs the node), (ii) the 21 docs that cite `score_live_trials.py:<line>`
(e.g. docs/evidence/RULING_replay_evidence_citability_and_promotion_criteria_2026-09-21.md:96) get a citation
map old->new, or the originals stay in place with thin re-exports. This contradicts the plan's own R2.1
rationale ("rulings cite scripts by path and line, so do not edit"); R2.2 edits exactly such a script.

C-4 [CONFIRMED] C12 answered. `strategy/forecast_quantile_ladder/composition.py:233-241` builds
`ForecastQuantileLadderConfig` with stations/artefact/strategy_id/order_id_tag/shadow_only only; no
`external_order_claims` (CRH sets it: current_rung_hold/composition.py:425-502,715). OMS is NETTING
(`exec/client.py:1670`). Effect: FQ fills reconcile at the next boot under `StrategyId("EXTERNAL")` (the
mechanism documented at current_rung_hold/composition.py:428-431); FQ plan R11 already records this as LOW.
Not a refactor blocker, but R3.1 must not "helpfully" add claims (a double claim raises at
`ExecEngine`, composition `_assert_disjoint_claims`) and the builder extraction must preserve the absence.
Reliability note: any code keyed on strategy ownership of a FQ position after a restart (exit seam,
position monitor) sees EXTERNAL; exit seam is unarmed (P-11) so no live impact today.

C-5 [CONFIRMED] NO leg: FQ orders are LIMIT/IOC/BUY qty 1 per FQ plan D8; venue nets NO as short YES
(memory; D-11). The refactor touches none of `exec/reports.py` leg sign handling; no objection.

## (D) Verification of the out-of-scope HIGH finding

CONFIRMED. `deploy/families/pm_us_crh_fq_v1.json` is `status: REGISTERED`, `boundary_artefact_path`
= `artefacts/not_applicable_boundary.json`, whose content is `{"schema":"breezy_boundary_artefact_sentinel_v1",
"applicable": false, ...}` and "deliberately does not satisfy `load_boundary_artefact`'s required-key schema ...
so any accidental family_tally_v2 run refuses closed" (FQ plan D4, line 64: no ledger write, no bypass code).
Statistical stop machinery (`LOSS_STOP`, group-sequential boundary) exists only in
`settlement/current_rung_hold_v2.py` and `scripts/analysis/family_tally_v2.py` (offline tally verdicts, not a
live halt) and is refused for FQ by construction. grep of `src/breezy/strategy/forecast_quantile_ladder` and
`app/trade.py` finds no loss/drawdown halt for FQ; the only `record_policy_halt` caller is the fee-drift
DISAGREE path (`app/trade.py:462`).
L-38 applies (docs/core/LESSONS.md:1354): a stop that cannot fire is reported MISSING in the same class as
a missing permit, and the effective stops restated without it. Effective stops that DO exist (CONFIRMED in
code/plan): operator caps at the exec chokepoint (maximum daily budget via `DailySpendLedger`, maximum per
position; qty always 1), 10 h permit TTL with the A-1 daily ceiling (core:122-128), fee-drift DISAGREE halt,
manual per-family halt tool (`breezy-set-family-halt`), OPEN/AMBIGUOUS intent deny, NO-SEND/`allow_short=False`
floors, and the supervisor A1 machinery for v4 (not FQ). The FQ plan risk R3 records "no demonstrated edge"
as HIGH (accepted) by operator ruling, so severity: HIGH, accepted-by-ruling, but L-38 still requires it to be
reported as a missing stop in readiness readouts. Relevance to this plan: the per-family halt veto
and the fee-drift halt are therefore the ONLY automated containment, which raises the severity of R3.1 and
R1.2 (fee_drift_probe leg) regressions. I propose no stop rule.

## (E) Required revisions

BLOCKER
1. (R3.1) Do not schedule R3.1 until CT-12 (through-`run()` FQ halt-veto binding, real writer, halted and
   unhalted twins; plus an FQ fee-coefficient-propagation assertion) is merged and shown red on a mutated
   key prefix. `test_operator_caps_through_the_live_composition._compose` is a mirror and does not count (B2).
2. (R3.2 + all node-loaded steps) Replace "revert before 16:40Z" as the safety net with a pre-spawn boot
   smoke on the integration tree: real FQ manifest through `app.trade.run` with a scratch store/catalog and
   `RecordingNode` (exists: test_forecast_quantile_ladder_boot) PLUS `python -c "import breezy.runtime.trade_supervisor,
   breezy.app.trade"` from the primary tree interpreter, run by the coordinator after merge. A supervisor
   restart with an observed heartbeat is mandatory the same day, completed by 14:00Z, for any step touching
   `trade_supervisor*` or `trade_supervisor_core` (core is also node-imported, app/trade.py:145).

MAJOR
3. (R1.1) Fix or drop: the stated leaf location imports Nautilus through `persistence/__init__.py` (B1). Write
   the layer-legal, import-free home and an import-graph test, or remove R1.1 (benefit ~30 LOC).
4. (R1.2) Exclude `fee_drift_probe` (not a copy; no supervision hook; it gates `is_fee_verified`). Add per-actor
   death/inflight characterisation (current negative-inflight behaviour of nws_observation_actor) before
   unifying; replace CT-4 as the prerequisite; drop `test_live_timer_thread_affinity` as an acceptance item
   (it tests Nautilus, not the helper).
5. (Freeze) Hold all node-loaded LIVE steps (R1.1, R1.2, R3.1, R3.2, R3.4, R1.3) until FQ's live proof
   (FQ plan section 5 items 1-12: permit line, family line, forecast feed publishing, subscribed, fee probe AGREE,
   self-check PASS) is recorded and at least one full trading day with reconciled fills has completed without
   an AMBIGUOUS/halt. Phase 0 and non-node Phase 2 proceed now. Each merged node-code change otherwise resets
   the evidence baseline of a family with no stop (D).
6. (R3.2) Add CT-13 (call order spawn vs persist; crash between them re-adopts), keep all 4 `os.fork()` tests
   until after one post-R3.2 daily cycle (B6, BC-13 later), and byte-pin `spawn_node` env/argv including the A-1
   ceiling env var literal (B7). Split in two merges: (a) core pure functions with the I/O shells untouched,
   (b) shells, with a restart between.
7. (R2.2) Reconcile with R2.1's citation rationale (C-3): citation map or leave originals as re-exporting
   shims; add read-only-open test; merge by 10:00Z and run each consumer (score-live, live-tally, family-tally@)
   once against the frozen baseline before 14:15Z. Correct C10 per C-2.
8. (Gate procedure) Pre-merge gate must run on the rebased tip with fast-forward-only merge; post-merge gate
   confirmatory (L-43, agent-worktrees-start-stale). Never two refactor merges inside one gate cycle.

MINOR
9. (R3.5) Defer for this cycle (agree with the plan's default). If ever done: mixin keeping `self.` receivers
   so the callee allowlist strings stay valid, scanner positive control proving the new module is inside the
   scan (exact-set module list at test_execution_egress_firewall_guard.py ~1600 forces this for the file list,
   but the by-name resolver scan must be shown to cover it), CT-1 first. "One reviewed row" is not credible
   (dozens of callee strings).
10. (R3.4) Pin the supervisor subscribe-marker class names (core:161-166) in CT-8 and forbid class
    renames/moves that change the Nautilus component name; v4 is A1-halted so the exposure is the import path.
11. (R0.1) Keep comment-only edits in their own commit; grep text-scanning pins (L-54) for client.py, trade.py
    and operator_controls.py before editing; do not name reserved controls in prose (L-39).
12. (R2.4) Drop. (R1.3) bundle with R1.4/R1.5 as an off-node batch.
13. (Sequencing) Order as written places R1.1 and R1.2 before their characterisation (CT-4 is irrelevant to
    R1.2; no CT protects R1.1 beyond existing latch tests). Required: CT-12, CT-13, an actor inflight/death
    characterisation, and the CT-1 public-port test BEFORE any LIVE step; CT-8 must include the env-var
    literal, marker class names and an FQ halt clearing path.
14. (Paper-replay parity) Re-run the SL-13p2 parity on the same 1-day window
    (docs/evidence/SL13P2_parity_pm_us_crh_fq_v1_2026-10-01.json: 0 mismatches / 720597) after R1.2 and R3.1 and
    require identical decision keys, since SL-13p2 replays production decision code. It does not cover the
    timer bridge (feed arrives from tape), so R1.2 still needs the real-actor test
    (`test_the_real_nbm_actor_feeds_the_composed_quantile_actor`). The CRH SFO 09-01 byte-identical replay
    (R3.4) remains valid for CRH only; replay cannot measure slippage or AMBIGUOUS behaviour (memory), so
    it is not a substitute for CT-1/CT-12.
15. (C10 text) Restate per C-2; add the stale CRH/ladder_ev src defaults to the "do not touch" list.

Coverage gaps I could not close: the actual runtime state of the node today (hand-launched vs
supervisor-owned, C6) was not inspected (read-only, no systemd); confirm before relying on any "next spawn"
timing. Test-fixture store types in test_submit_intent_latch.py and the `test_edge3_per_family_halt.py` byte
comparison were not read line-by-line (HYPOTHESIS items B4, B8).
