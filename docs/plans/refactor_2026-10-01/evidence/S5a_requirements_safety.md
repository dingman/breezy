I couldn't create the REPORT.md file. My tool rules here only allow writing `openspec/specs/<capability>/spec.md` and keep Bash read-only, so `mkdir` and a scratchpad write were both blocked. The full report is below; save it to `.../scratchpad/S5a/REPORT.md` if you want it on disk. Nothing in the repo was changed.

# S5a REPORT — Breezy safety, programme and settlement requirements (HEAD 60290e9d, read-only)

CONFIRMED means I read the source doc, the code, and a named pinning test (at least by signature). HYPOTHESIS means at least one of those three is unread. Operator-reserved controls are named only, never valued.

## A. Requirements

### (a) Safety barriers
| ID | Requirement | Source | Enforcing code | Pinning tests | Status | Conf |
|---|---|---|---|---|---|---|
| S-01 | The pytest session aborts before collection if any execution-egress module exists and the OS firewall is not both attested and proven by a real blocked canary connect (barrier N2) | L-12; PROGRESS backlog binding | `tests/conftest.py:292-380` (`execution_egress_abort_reason`, `pytest_sessionstart`) | `test_execution_egress_firewall_guard.py:567-1053` | ACTIVE | CONFIRMED |
| S-02 | pyo3 Http/WebSocket/Socket clients are blocked in every ordinary test, including the `network` submodule slot, and socket `connect`/`connect_ex` are blocked (N1) | conftest docstrings; L-12 | `conftest.py:105-132,163,509-532` | `…firewall_guard.py:315-358` | ACTIVE | CONFIRMED |
| S-03 | A claimed OS egress block must actually block (N3/N5). The launcher tries bwrap, then unshare, else exits 3 | `scripts/ci/run_tests_no_egress.sh` header | same script; `conftest.py:90-99` | `…firewall_guard.py:493-511,1078-1121` | ACTIVE | CONFIRMED |
| S-04 | A pytest run with venue credentials is refused unless all 3 unlocks are present (two env vars plus the CLI flag) | conftest only | `conftest.py:383-408` | not located | ACTIVE | HYPOTHESIS |
| S-05 | N2, X3 and E0-INERT are exact-set equalities. A new `exec/` module widens the set in the same commit; never relax to subset/`in` | L-12, L-14 | test-side sets | `…firewall_guard.py:710`, `:1578-1584` | ACTIVE | CONFIRMED |
| S-06 | The default pytest marker filter excludes live, venue_live and real_money tests; it is pinned and only a safety-reviewed item may change it | L-54 | `pyproject.toml:49` | `test_probe_containment.py::test_pyproject_addopts_deselect_the_probe_markers` (unread) | ACTIVE | HYPOTHESIS |
| S-07 | B2: the read signer signs GET only. The write path is a separate POST-only signer | signing/write_transport module docs; L-14 | `signing.py:83,244-261`; `write_transport.py:52-54,111-122` | `test_polymarket_us_signing.py:268-275`; `test_polymarket_us_write_transport.py`; `test_cage_rule_constants_are_pinned.py:58` | ACTIVE | CONFIRMED |
| S-08 | Two-cap gate. Both caps are read before either is applied; an absent or blank cap refuses. Cost above the per-position cap refuses. A UTC-day total above the daily budget refuses. A clock moving backwards refuses. Every message names the control, never a value | PROGRESS "Operator control contract" | `adapters/polymarket_us/operator_controls.py:348-427` | `test_operator_reserved_controls.py:72-104`; `test_fq_caps_and_ambiguous_2026_10_01.py:96-143` | ACTIVE | CONFIRMED |
| S-09 | Ledger seeding: once per process, prior durable-fill spend is booked into the ledger; it never lowers a higher in-memory total | none in core docs (S0, plan rev 3) | `operator_controls.py:307-333`; `exec/client.py:2268` | `test_live_trading_budget_restore.py` (unread) | ACTIVE vs doc (see B-2) | HYPOTHESIS |
| S-10 | Only the definition module and `operator.env*` may name a reserved control. The census covers untracked files too | L-39 | the census test itself | `test_operator_control_assignment_scan.py:381-485` | ACTIVE | CONFIRMED |
| S-11 | `LiveTradingPermit` exists only via `issue_live_trading_permit` (authenticity tag) with a 10 h TTL. Derived ceilings: per-order = per-position cap; session notional = daily budget; order count = floor(budget/position), minimum 1 | PROGRESS (cites `safety.py:552-608`) | `safety.py:150-172,384-431,569-606,673-730` | `test_polymarket_us_permit_issuance.py:194-256` | ACTIVE | CONFIRMED |
| S-12 | `OrderSubmissionPermit.issue` preconditions: orders requested; genuine and unexpired live permit; write canonical string verified; both caps present; sending family set; live observations enabled | memory "the real order gate is the permit"; L-22 | `runtime/order_enablement.py:153-224` | `test_runtime_order_guard_permit_expiry.py` (unread) | ACTIVE | HYPOTHESIS |
| S-13 | `BacktestOrderGuard` refuses an expired permit (strict `>`, same boundary as the mint), post_only, and a naked short (SELL above net long, counting working orders and the shim). Refusals are counted. The live install requires an `on_refusal` handler | PROGRESS binding "never weaken" | `runtime/backtest_order_guard.py:279-297,301-451,527-580` | `test_runtime_backtest_order_guard.py:169-190`; `test_runtime_live_order_guard.py` | ACTIVE | CONFIRMED |
| S-14 | `allow_short=True` is refused at config construction; `RiskLimits` defaults to False | PROGRESS binding; FQ ruling floors | `current_rung_hold/config.py:267-270`; `ladder_ev/config.py:171-188`; `weather_common/risk.py:224` | `test_current_rung_hold_config.py`; `tests/strategy/{ladder_ev,forecast_quantile_ladder}/test_config.py`; `test_weather_common_risk.py:874-885` | ACTIVE | CONFIRMED |
| S-15 | crh `order_quantity` must be exactly 1 (Increment A, qty≡1) | RULING_multi_position (Incr A) | `current_rung_hold/config.py:264-266` | not located | ACTIVE | HYPOTHESIS |
| S-16 | Submit chokepoint order with no `await` between steps: OPEN-intent wait, then family-halt veto, then body build, then permit assert, then `authorize_order_cost`, then latch arm | FQ plan D8; L-22 | `exec/client.py:5327,5418-5500` | `test_current_rung_hold_pre_arm_race.py`; `test_fq_caps_and_ambiguous…:163` | ACTIVE | HYPOTHESIS |
| S-17 | The supervisor refuses to launch while the intent flock is held or an OPEN intent exists; a corrupt intent counts as OPEN. The probe is pre-launch only | L-48; memory | `trade_supervisor_core.py:529-539`; `trade_supervisor.py:392-410` | `test_trade_supervisor.py` (unread) | ACTIVE | HYPOTHESIS |
| S-18 | A create response of 200 + id + empty executions stays AMBIGUOUS, and `classify_create_order_outcome` stays byte-unchanged. A later GET is new evidence; every GET failure is fail-closed; `clear_submit_intent` is the only no-id path | L-36 | `exec/submit_chain.py:1200` (L-36 cites `:818-855`) | `test_polymarket_us_submit_order_chain.py["200-id-no-exec"]` | ACTIVE | HYPOTHESIS |
| S-19 | The submit-intent latch is unforgeable: `open_submit_intent_latch` is the only constructor and holds the flock for its lifetime | L-22 | `runtime/submit_intent.py:316,556,584` | `test_submit_intent_latch.py:126-169` | ACTIVE | HYPOTHESIS |
| S-20 | Venue-shape drift is declared per surface: execution / order / balance / position / market-metadata allowlists. Any other unknown key is refused with a names-only key tree | L-37 (+09-14 addendum) | `exec/reports.py:233,291,333-341,376,418,1295` | `test_polymarket_us_exec_reports.py:271-325` | ACTIVE | CONFIRMED |
| S-21 | Per-family halt. The legacy A1 halt applies only to `pm_us_crh_v4`. Clearing overwrites a cleared marker because the store has no delete. Any halt source other than "none" blocks | RULING_A1; FQ plan §37 | `trade_supervisor_core.py:209-238,466-482`; `trial_day_latch.py:292-354` | `test_trade_supervisor_cont_self_check.py`; `test_edge3_per_family_halt.py`; `test_set_family_halt_cli.py` | ACTIVE (SET on v4) | CONFIRMED |
| S-22 | Fee θ. Each order checks venue θ against the family manifest's `taker_fee_coefficient`. Probe DISAGREE always halts the family; UNKNOWN alerts but never halts; 24 h dedupe applies to alerts only. The documented 0.06 constant is never edited. Changing a registered θ is class C | RULING_fee_drift_probe_target; memory (class C) | `fees.py:93,111`; `current_rung_hold/fee_drift_probe.py`; `app/trade.py` `_build_fee_drift_probe` | not located | ACTIVE | HYPOTHESIS |
| S-23 | A permit is never extended or re-minted in-process: one process per trading day | `backtest_order_guard.py:322-335`; RULING_B3 | same | `test_runtime_order_guard_permit_expiry.py` | ACTIVE | HYPOTHESIS |
| S-24 | NO-side first-order containment: while the first-order key exists without the captured key, further NO arms are refused. Only the operator CLI may write the captured key | PREREG v3 NO amendment §8 | `exec/no_side_keys.py:38-82` | `test_no_side_keys.py`; `test_no_side_first_order_pending_2026_09_14.py` | ACTIVE (window closed 09-16) | CONFIRMED |

### (b) Trading-programme rules
| ID | Requirement | Source | Enforcing code | Tests | Status | Conf |
|---|---|---|---|---|---|---|
| P-01 | v3 sequential rule: `S_k`, `I_max=40`, `n_max=160`, a look every 10 fills, LD-OBF at one-sided α=0.025 each side. SURVIVE needs S≥b_eff, total_pnl>0 and no dead cell; otherwise KILL. A terminal look never returns CONTINUE | PREREG v3 §3, §8 | `settlement/current_rung_hold_v2.py:433-501`; `persistence/gs_boundary_artefact.py:78-82,183,416-451`; `scripts/analysis/family_tally_v2.py:658-692` | `test_current_rung_hold_v2_verdict.py`; `test_gs_boundary_artefact.py`; `test_family_tally_v2_look_loop_golden.py` | ACTIVE (`pm_us_crh_cont`) | CONFIRMED |
| P-02 | `LOSS_STOP`: total_pnl ≤ −60 contract-units means KILL. The residual is an unsigned loss and only moves toward KILL. The threshold is never configurable | v3 §5, §7 | `family_tally_v2.py:181,677` | `test_family_tally_v2_truncation.py`; `test_family_tally_v2_residual_sidecar.py` | ACTIVE | CONFIRMED |
| P-03 | The trial unit is the station-day: `X=Σqty(held−BE)` with the exact mutual-exclusivity covariance. Admission requires Σq≤1. A same-rung YES+NO pair, a mixed day missing rung keys, or an empty day is refused | L-40, L-41; RULING_multi_position | `current_rung_hold_v2.py:296-345` | `test_current_rung_hold_v2_score.py:175-268`; `test_multi_position_validation_2026_09_14.py` (strict xfail for qty>1) | ACTIVE | CONFIRMED |
| P-04 | Mixed-side day variance can reach 1.0, not 1/4. Any re-validation must replay the live look loop and stop at `I_max` | L-40 amendment 09-25 | sign-aware term in `combine_station_day` | `test_family_tally_v2_mixed_side_disclosure_2026_09_25.py`; look-loop golden | ACTIVE | HYPOTHESIS |
| P-05 | R-10: one open position per instrument-day; a station carries as many positions as it has current rungs, bounded only by the two caps; qty≡1 in Increment A | RULING_multi_position_per_station_2026-09-14 | `combine_station_day`; S-15 | as P-03 | ACTIVE (Incr B gated) | CONFIRMED |
| P-06 | NO-1: NO-side hunting is a requirement (supersedes BL-6). Current-rung NO only; the first NO fill is residual | PROGRESS; NO amendment §1, §8 | `tick_eval`/`decision` NO paths; `leg_prices.py` | `test_current_rung_hold_{decision,tick_eval}_no_side_2026_09_14.py` | ACTIVE | HYPOTHESIS |
| P-07 | Resting bid (`pm_us_crh_rest_v5`) is a class-C new family, DRAFT_NOT_REGISTERED and shadow-only; live orders must stay byte-identical | PREREG v5 DRAFT; memory | `resting_decider.py`; `shadow_rest_store.py` | `test_resting_decider_wiring_byte_identical_orders.py`; `test_resting_decider_shadow.py` | ACTIVE (shadow) | HYPOTHESIS |
| P-08 | The evaluation trigger is part of the frozen rule; a re-look or timer is class C | L-34 | first-snapshot latch in `continuous_strategy` | not located | ACTIVE | HYPOTHESIS |
| P-09 | Family tally / KILL clock: a nightly per-family tally; the structural-dead counter must be able to increment (L-38) | v3 §9; L-38 | `deploy/systemd/breezy-family-tally@.*`, `family-tally-v2-run.sh`; `scripts/analysis/structural_dead_stop.py` | `test_structural_dead_stop*.py`; `test_family_tally_v2_deploy.py` | ACTIVE | HYPOTHESIS |
| P-10 | FQ activation: `pm_us_crh_fq_v1` REGISTERED with `live_orders_ruling`, d0 2026-10-02 and a sha-pinned density artefact. Its boundary is a not-applicable sentinel that refuses any group-sequential tally. Exactly one sending family. The v4 A1 halt is untouched | RULING_operator_fq_live_real_orders_2026-10-01; FQ_GO_LIVE_PLAN D4/D6–D8 | `deploy/families/pm_us_crh_fq_v1.json`; `app/trade.py:722-745` | `test_fq_s8_registration_artefacts.py`; `test_fq_caps_and_ambiguous_2026_10_01.py` | ACTIVE (live) | CONFIRMED |
| P-11 | Identified-loser exit seam stays UNARMED: it gates true only for a code-registered family (`pm_us_crh_exit_v4`) whose manifest declares `exit_rule`; that manifest is DRAFT_NOT_REGISTERED | memory 09-16 ruling; EXIT_SEAM_VERIFICATION_STATE | `persistence/exit_gate.py:55-66` | `test_persistence_exit_gate.py:80-139` | ACTIVE (unarmed) | CONFIRMED |
| P-12 | Programme KILL horizon 2027-01-25, then Kalshi K-2; R3V-b kill-screen | RULING_RA-13 §3; PROGRESS | `scripts/analysis/r3_viability.py` (screen only) | none | AMBIGUOUS (see B-9) | HYPOTHESIS |
| P-13 | PREREG semantics change only by a ruling under `docs/evidence/` | PROGRESS binding | byte/sha pins: boundary `inputs_sha256`, `CORPUS_SHA256` in crh config | `test_prereg_v1_is_byte_unmodified.py` | ACTIVE | HYPOTHESIS |

### (c) Settlement and data rules
| ID | Requirement | Source | Enforcing code | Tests | Status | Conf |
|---|---|---|---|---|---|---|
| D-01 | Settlement-grade means FINAL, not superseded, and tmax not a sentinel. A PRELIMINARY (carries the "VALID TODAY AS OF … LOCAL TIME" line) never settles | nws-cli-settlement skill §18-19 | `normalize/classify.py:78-89`; `settlement/settlement_truth.py:30-44` | `test_normalize_classify.py:28-54` | ACTIVE | CONFIRMED |
| D-02 | Corrections are detected by BBB `CC[A-Z]` plus free text (CCA/CCB/CORRECTED/CORRECTION). The two signals must use the same letter range | skill §59-66 | `domain/wmo.py:25-45`; `classify.has_correction_evidence:92` | `test_normalize_correction_signal_agreement.py` | ACTIVE | CONFIRMED |
| D-03 | `revision_seq` is monotonic per (station, climate_day), starts at 1, counts across catalog and batch, and has no default | skill §82 | `ingest/nws_actor.py:1397-1462` | `test_ingest_nws_actor.py` (unread) | ACTIVE | HYPOTHESIS |
| D-04 | Selection picks max (is_final, ts_init, revision_seq) per station-day, with is_final first. There are two accessors (as-of-bounded and current); selection never consults `is_superseded` | catalog docstring; PHASE1 brief | `persistence/catalog.py:148-165,676-690`; `domain/selection.py` | not read | ACTIVE | HYPOTHESIS |
| D-05 | Live ingest always writes `is_superseded=False` (records are never rewritten) | code only | `nws_actor.py:1462-1465` | — | CONFLICT (B-6) | HYPOTHESIS |
| D-06 | The product-uuid to raw_sha256 index is first-write-wins and durable; the same uuid with different bytes is an integrity event | `ingest/product_index.py:1-30` | same | `test_ingest_product_index.py` | ACTIVE | HYPOTHESIS |
| D-07 | Identical product text dedupes to one record; a corrected text becomes a new revision | skill §78-79 | `nws_actor._undeduped:1098` | not read | ACTIVE | HYPOTHESIS |
| D-08 | Climate day uses local STANDARD time as a fixed offset all year; a naive datetime is rejected | skill §52 | `domain/climate_day.py:30-41` | `test_normalize_climate_day.py:22-78` | ACTIVE | CONFIRMED |
| D-09 | Tape vs catalog: any "missing data" verdict must name the layer it read; check the `live/` streams and run ingest first | L-20 | `quote_tape_ingest_cli.py`, preflight (process) | none | ACTIVE | HYPOTHESIS |
| D-10 | Replay sufficiency: key (station, climate_day); the winner is the CLEAN instance with the longest Depth10 span; overlap refuses; coverage is judged on depth. Only SUFFICIENT with `window_complete` and WHOLE coverage is citable | AUD-09a/b; memory (census rows) | `analysis/replay_sufficiency.py:1-40,677`; `promotion_criteria.py:429` | `test_replay_sufficiency.py:228`; `test_replay_sufficiency_census.py` | ACTIVE | CONFIRMED |
| D-11 | The venue nets a NO holding as short YES. A No outcome with net<0 maps to LONG on `<slug>^no`. Contradictions fail closed. Reconcile only after applying the leg sign. avgPx is not complemented | RULING_no_side_position_shape §3 | `exec/reports.py:1405-1452` | `test_polymarket_us_exec_positions.py:151,197` | ACTIVE | CONFIRMED |
| D-12 | A NO buy echoes as SELL/BUY_SHORT; the NO close echo (BUY, SELL_SHORT) is pinned | RULING_x3 (two files) | `adapters/polymarket_us/leg_prices.py:17-176`; `parsing.py:277` | not located | ACTIVE | HYPOTHESIS |
| D-13 | Durable keys use the dotted `str(InstrumentId)`; composite ids use `^`, never `~` | L-42; memory | `trial_day_latch.py:249-270,453-490` | real-writer fixtures (L-42) | ACTIVE | HYPOTHESIS |
| D-14 | tmax is fail-closed; tmin/tavg fall back to an UNREADABLE sentinel; a sibling-station PIL is routine, not a failure | CF-5 (cli_parse docs) | `normalize/cli_parse.py:202-218,400-425,496-506,627-629` | `test_normalize_cli_parse*.py` | ACTIVE | HYPOTHESIS |

Totals: 51 rows (24 safety, 13 programme, 14 settlement/data). 22 CONFIRMED, 29 HYPOTHESIS. 49 ACTIVE (including P-07 shadow-only and P-11 unarmed), 1 AMBIGUOUS (P-12), 1 CONFLICT (D-05). None SUPERSEDED in full, but BL-6 and v3 §13/§16 are superseded by NO-1 and R-10.

## B. Conflicts
| # | Conflict | Evidence |
|---|---|---|
| B-1 | PROGRESS cites `operator_controls.py:301` and `:252-265`, and the brief says `runtime/`. The real file is `adapters/polymarket_us/operator_controls.py`, with `authorize_order_cost` at `:348` | line drift and wrong path |
| B-2 | PROGRESS and the ledger docstring say "in-memory per process BY DESIGN; a restart forgets the day's spending". `seed_spent` (S0, `client.py:2268`) re-seeds from durable fills on each boot. Spend booked for orders with no durable fill (AMBIGUOUS) is still lost on restart | `operator_controls.py:264-276` vs `:307-333` |
| B-3 | PREREG v3 §7 gives the per-position cap "per-station-day notional" scope. The code caps each ORDER's cost (`:387`), and R-10 allows several positions per station-day. The R-10 ruling struck §13/§16/§12 but not §7 | v3 `:177-184` |
| B-4 | v3 §3 says "two one-sided α=0.025"; §10 says "two-sided α=0.025". The code has `ALPHA_ONE_SIDED=0.025`. "LD-OBF on Wilson" is not accurate: LD-OBF applies to `S_k`; the Wilson bounds are terminal-only and never sequentialized (§10) | v3 `:45,208-209` |
| B-5 | "Exactly two operator variables; session ceilings derived" vs `safety.py:147-155`, which says an explicit session-ceiling env var wins when present, so extra knobs exist. Mitigated because the ledger re-reads the raw caps on every submit | v3 §7; PROGRESS |
| B-6 | The skill (§83) says to mark the prior record superseded when a correction arrives. Live ingest always writes `is_superseded=False`, and selection ignores the flag. So the "not superseded" leg of `is_settlement_grade` is vacuous for live records: calling it on a non-selected, corrected-away FINAL returns True | `nws_actor.py:1462-1465`; `settlement_truth.py:30` |
| B-7 | The skill lists CCA/CCB; the code uses the wider CC[A-Z] (the code is right, the doc is stale) | `wmo.py:30` |
| B-8 | L-36 pins `classify_create_order_outcome` at `submit_chain.py:818-855`; it now sits at `:1200`. "Byte-unchanged" can only be policed by the parametrized test | L-36 |
| B-9 | RA-13 (09-27) says "the bot is already not armed". The 10-01 operator FQ ruling arms real orders and overrides node 4. RA-13's operational premise is outdated, and its KILL horizon is unscoped relative to FQ | RA-13 `:20`; FQ ruling |
| B-10 | Stale docstrings: `signing.py` says "a write path must add a method to `PERMITTED_METHODS`" (the actual write path is a separate POST signer); `write_transport.py:6` says "zero send call sites" | module docstrings |
| B-11 | The guard says one process per trading day (permit TTL), but memory records a mid-day relaunch running 3× per 5 min. HYPOTHESIS: whether a relaunch mints a fresh permit within the same day | `backtest_order_guard.py:329-331` |
| B-12 | The FQ plan arms a native `clock.set_timer` (D1 readiness). That runs into the L-16 hazard (raises swallowed) and L-34's "LiveClock timers DECLINED". It is not a trial trigger, but it needs an explicit L-16 disposition. HYPOTHESIS | FQ plan `:248` |
| B-13 | `trade_supervisor_core` duplicates the halt prefix and cleared-marker literals from `trial_day_latch`, pinned byte-for-byte by test. This is a refactor trap, not a bug | `trade_supervisor_core.py:209,247` |

## C. Gaps
**Requirements with no enforcing code:**
- **P-10 / L-38 [HIGH]:** the active live family `pm_us_crh_fq_v1` has no registered statistical stop. The boundary sentinel refuses every tally by design and there is no PREREG doc. The only stops are the two caps, the fee-drift halt and the manual halt tool. Under L-38 that counts as a MISSING stop.
- **P-12:** the programme KILL on 2027-01-25 is a coordinator act with no timer or check.
- **D-09 (L-20)** and **P-08 (L-34 trigger pin):** process rules only; I found no test.
- **L-38 positive control** ("a day that should count, counts"): not automated.
- **B-6:** the superseded-marking requirement has no producer.

**Behaviour enforced only by code/tests with no core doc** (candidates for characterization tests before any refactor):
- `conftest` credentialed-session refusal (S-04).
- Ledger: clock-rewind refusal, release/true-up at most once, prior-day pruning, seed `max()` (S-09).
- Permit cannot be laundered via `replace` or pickle.
- Guard refusal counting.
- Supervisor: corrupt intent counts as OPEN; probe never runs while a node PID is live.
- `nws_actor` `ts_init` nudge past the catalog max (WI-11).
- `cli_parse` tolerant tmin/tavg and routine sibling PIL (D-14).
- product_index first-write-wins (D-06).
- `combine_station_day` same-rung fold and `rung=None` exemption.
- Replay overlap tolerance and FRAGMENT coverage.
- Continuous-strategy snapshot dedupe key `(ts_event, ask, size)` (`continuous_strategy.py:1935-1942`).

## D. Constraints on restructuring these areas
| Rule | Effect on a refactor |
|---|---|
| L-12, L-14, L-46 | Barrier sets are only ever widened, by one reviewed row. Derive the barrier list by asking "what would refuse this?" (run the suite against a broken variant). Never hide a literal from a scanner. Any new or moved `exec/` module widens N2/X3/E0-INERT in the same commit |
| PROGRESS backlog binding | Never `allow_short=True`. Never weaken the guard or any safety, settlement, contract or NO-SEND test. Never touch live enablement. PREREG changes only by ruling. Full gate after every merge. No uv/pip from a worktree; no git stash (hook-blocked); worktrees need `PYTHONPATH` set |
| L-22 | The permit, OrderSubmissionPermit and latch must each keep a single unforgeable constructor; B11 pins one construction site. Moving it trips the pins |
| L-34 | Any refactor of the hunt or tick path in a registered family that could change which snapshot becomes the trial is class C and needs a new family or ruling |
| L-36, L-37 | `classify_create_order_outcome` stays byte-unchanged. Drift allowlists are declared per surface, never relaxed |
| L-42, L-55 | Tests of store readers write their fixtures through the real writer. Every injected seam gets one test that runs the production default |
| L-43, L-54 | Gate the integration branch after every slice. Do not edit `pyproject` addopts, the import-linter config or `conftest` without first grepping `tests/` for pins. Layers contract: adapters never import runtime; the live path never imports `breezy.analysis` (lint-imports after each slice) |
| L-39 | Refactor docs must name the reserved controls only as "the per-position cap" and "the daily budget" |
| L-48 | Every latch touched must show a clearing path that works while the latch is closed and across a day boundary |
| Pins | Manifest/artefact shas (`boundary_inputs_sha256`, `density_artefact_sha256`, `CORPUS_SHA256`) and `test_prereg_v1_is_byte_unmodified`. `BacktestOrderGuard` is used by name in tests, so a rename is out of scope |
| Ops | The supervisor unit is symlinked into the repo, so an activation commit goes live on the next daemon-reload. Supervisor restarts only in the 01:00–16:40Z window. PROGRESS size gate: 250 lines / 12 KB |

---

**Summary**

1. 51 requirements mined (24 safety, 13 programme, 14 settlement/data): 22 CONFIRMED, 29 HYPOTHESIS.
2. Top 5 conflicts and gaps:
   - **No statistical stop on the live family [HIGH].** `pm_us_crh_fq_v1` is live and has no registered stop rule: its boundary is a sentinel that refuses any tally. Only the caps and the fee/manual halts can stop it (L-38 says this is a MISSING stop).
   - **The daily-budget ledger is no longer purely in-memory.** PROGRESS and the docstring say so, but each boot re-seeds it from durable fills (`client.py:2268`). Spend on AMBIGUOUS orders with no recorded fill is still forgotten on restart.
   - **PREREG v3 §7 is stale on the per-position cap.** It scopes the cap per station-day; the code caps each order's cost and R-10 allows several positions per day. §7 was never struck. §3 and §10 of the same doc also disagree on one- vs two-sided α.
   - **The "not superseded" check is vacuous for live records.** Live ingest always writes `is_superseded=False`, while the skill requires marking superseded records. A corrected-away FINAL still passes `is_settlement_grade`.
   - **Stale citations and extra knobs.** The contract pins point at wrong lines or paths (PROGRESS `operator_controls.py:301` is really `adapters/…:348`; L-36's `submit_chain:818` is now `:1200`). Session-ceiling env overrides contradict "exactly two operator variables", though the ledger still re-reads the raw caps on every order.
3. Restructuring is fenced by L-12/14/22/34/36/37/42/43/46/54/55, the PROGRESS binding rules, and the sha/byte pins listed in section D.
4. Path for the report, if you write it yourself: `/tmp/claude-1000/-home-jon-emdash-worktrees-breezy-6ba07ea4-emdash-refactor-y4qj4/91bfb437-f89e-497c-a458-e7b6a8ace0cf/scratchpad/S5a/REPORT.md`