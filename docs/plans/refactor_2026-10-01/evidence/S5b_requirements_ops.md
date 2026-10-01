I couldn't create `REPORT.md` or its directory. In this session the Write tool can only create `openspec/specs/<capability>/spec.md`, which your brief rules out, and Bash is read-only (no `mkdir`). The full report follows inline instead, under 300 lines. Nothing in the repo was changed and no unit was touched.

---

# S5b REPORT: Breezy operations, engineering constraints and venue portability (HEAD 60290e9d, mined 2026-10-01)

**Legend.** Status is A = ACTIVE, S = SUPERSEDED, AMB = AMBIGUOUS. Evidence is C = CONFIRMED (I read the source doc, the enforcement and the test) or H = HYPOTHESIS. Line numbers are at HEAD.

**Live context observed (read-only):**
- The primary tree `/home/jon/breezy` is on branch **`feat/data-capture-and-risk` @60290e9d**, not `main`.
- All 40+ user units are symlinks into that tree.
- A hand-launched node, `breezy-trade-hand-151202.service`, is running a launcher script that lives in a `/tmp/claude-1000/.../scratchpad/`.
- `breezy-trade-supervisor.service` is active.
- Currently failed units: `breezy-fee-evidence-pull`, `breezy-replay-daily`, `breezy-replay-backfill-0929`, `breezy-parity-mem-{1d,7d}`.

## A. Requirements

### (d) Operations

| ID | Requirement | Source | Enforcement (file:line) | Pinning test | St | Ev |
|---|---|---|---|---|---|---|
| OPS-01 | Fixed daily schedule: 16:40Z stop prior node, 16:50Z launch, relaunch cutoff 17:00Z, 17:05Z self-check (closes 17:10Z). Boot relaunch at most 2 tries, at least 3 min apart | `breezy-trade-supervisor.service:6-12`; `TRADE_NODE_DAILY_RELAUNCH_2026-09-04.md` | `trade_supervisor_core.py:34-50` | `test_trade_supervisor.py:656-695` | A | C |
| OPS-02 | Mid-day relaunch: at most 3 tries, at least 5 min apart, transient cause only, window 17:10Z to 01:00Z next day, no readiness gate | `MIDDAY_RELAUNCH_2026-09-15.md:22,58-62` | `core.py:55-56, 1078-1081, 1360-1383` | `test_trade_supervisor.py` (midday_* tests), `test_trade_supervisor_core.py:698` | A | C |
| OPS-03 | Boot retry: 8 tries, at least 15 min apart, 15 min readiness timeout, closes at 01:00Z | not read | `core.py:65-69`; `trade_supervisor.py:1863` | `test_trade_supervisor.py:4879, 5223, 5306` | A | H |
| OPS-04 | `KillMode=process`, SIGTERM only, `TimeoutStopSec=120`, never SIGKILL the node or supervisor | unit `:146-162`; `deploy/systemd/README.md:1345-1372`; L-26 | unit only | **none** | A | H |
| OPS-05 | Supervisor unit carries no `MemoryHigh`/`MemoryMax` (a cgroup OOM would SIGKILL a node holding a position) | unit `:63-74`; R8 §10 standing note | unit | `test_analysis_units_memory_capped.py:169` | A | C |
| OPS-06 | `Restart=always`, `RestartPreventExitStatus=2` (config error), `StartLimitBurst=5/3600` | unit `:52-53, 141-147` | unit; exit codes `core.py:249-251` | none on the directives | A | H |
| OPS-07 | Exactly one supervisor: argv token `breezy-trade-supervisor-daily` plus an exclusive flock. Anchored pgrep `breezy-trade$` | L-26 how-to; unit `:131-137` | `core.py:74-79`; `trade_supervisor.py:261-284` | `test_trade_supervisor.py:94, 1896` | A | C |
| OPS-08 | A node that outlives its supervisor is expected; it is re-adopted through the PID-verified flock holder. `PASS_ADOPTED_LOG_UNKNOWN` is distinct from `PASS` | README `:1345-1372` | `core.py:622-689` | `test_trade_supervisor_cont_self_check.py:79-120` | A | C |
| OPS-09 | Supervisor restart or activation only inside 01:00–16:40Z (code and env load once per supervisor lifetime) | `FQ_GO_LIVE_PLAN_2026-10-01.md:375`; unit `:49-51` | **none** (procedural) | none | A | H |
| OPS-10 | Self-check returns exactly one result; every FAIL maps to an alert detail | `RULING_permit_daily_coverage_2026-09-25.md` §5 | `core.py:381, 622-689` | `test_trade_supervisor_cont_self_check.py` | A | C |
| OPS-11 | Liveness = process alive + log mtime advancing + permit unexpired + tape advancing | **operator memory only**; no repo doc | Partial: `self_check` covers child, flock, permit and subscription (`core.py:668-689`); permit heartbeat `core.py:140`. Log mtime and tape advance are not checked by the supervisor | none | AMB | H |
| OPS-12 | Permit TTL 10 h. Daily cumulative-coverage ceiling (A-1) is injected only on mid-day relaunch; the 16:50Z boot and hand launches carry none | `RULING_permit_daily_coverage…:30, 66, 95-113` | `core.py:128, 1259-1273` | cited `test_polymarket_us_permit_issuance.py` (not read) | A | H |
| OPS-13 | The node's boot permit line is the only proof of order capability; it must be emitted through its own handler (L-30) | L-30; unit `:170-176` | `core.py:91, 692-703`; `app/trade.py` boot logger | not read | A | H |
| OPS-14 | Evidence lives in log files `~/.local/share/breezy/logs/breezy-trade-supervisor.log` and `breezy-trade-<ts>Z.log`. journald is only the decision journal | unit `:164-176` | `trade_supervisor.py:807-832, 1008-1028` | L-27 HOME-redirect tests (not read) | A | H |
| OPS-15 | Anything that must outlive the session is launched with `systemd-run --user` and verified in `app.slice`; `setsid` alone is insufficient (sharpened 09-24) | L-26 | **none** | none | A | H |
| OPS-16 | Hand relaunch recipe: copy env from `/proc`, SIGTERM, wait for DISPOSED, mirror `spawn_node()`. Gets no A-1 ceiling and bypasses the stop-intent marker | `R8_OPERATOR_RUNBOOK.md:558-586` | none; the live launcher is an unversioned `/tmp` script | none | AMB | C (observed) |
| OPS-17 | Alert egress: one key, `BREEZY_ALERT_WEBHOOK_URL`, in `~/.config/breezy/alerts.env`. https only, no userinfo. `breezy-check-alerts` exits 2 if not configured, 3 if not delivered. "A detector without delivery is not a control" (L-52) | AUD-15 amendment (unit `:76-88`); L-52 | `health.py:117, 447-456, 579-626`; `check_alerts_cli.py:51-53, 115-150` | `test_alerts_env_deploy.py:92-103`; `test_study_failure_alert.py:107-176`; `test_alert_egress.py` | A | C |
| OPS-18 | Every timer-driven unit declares `OnFailure=breezy-study-failed@%n.service`. The notifier exits 0 and sends a fixed-enum detail | AUD-15 | units; `runtime/study_failure_notifier.py` | `test_study_failure_alert.py:77-239` | A | C |
| OPS-19 | Long-running units (recorder, NWS ingest, supervisor) declare no `OnFailure`. `breezy-nws-ingest.service` loads only `breezy.env`, which has no webhook key, so NWS in-process alerts resolve to a log-only sink (`composition.py:283-379`) | no doc | n/a | none | AMB | H |
| OPS-20 | Memory caps: every nightly study has `MemoryHigh` < `MemoryMax`; studies run in `breezy-studies.slice` (12G/16G); recorder 2G/3G; scorer 4G/5G. A cap is containment, not a fix (L-29) | L-29, L-49, L-53 | unit files | `test_analysis_units_memory_capped.py:121-216`; `test_quote_tape_service_memory_ceiling.py:43-68` | A | C |
| OPS-21 | Host-only TEMPORARY drop-ins override the repo caps: ingest 12G/14G (repo 4G/6G), replay-daily 10G/12G (repo 3G/4G). Also host-only: tmux scope 12G. Removal was owed after the 09-29 memory-peak proof | `PROGRESS.md:51` | `~/.config/systemd/user/*.service.d/zz-memory-containment-TEMPORARY.conf` | none | AMB | C (observed) |
| OPS-22 | Catalog pipeline: recorder rotates at 09:00Z (`try-restart`). Ingest runs every 15 min plus at 00/06/12/18:15, with `--deadline-seconds 600` and `TimeoutStartSec=1800`. Instruments are written before depths (L-49) | L-49; README | `quote-tape-rotate.timer:25`, `.service:55`; `quote-tape-ingest.service:87-92`; `ingest-frequent.timer:21` | `test_deploy_timer_hours.py:138` | A | C |
| OPS-23 | No two timers share an HH:MM tick (same-unit siblings exempt). 09:20 digest, 14:15 scorer, 15:50 replay, 16:52 discovery, 17:20 tally are each owned by exactly one timer | AUD-03/05; README | `*.timer` | `test_deploy_timer_hours.py:86-217` | A | C |
| OPS-24 | Protected window P = [16:45Z, 01:15Z), no-start rule [16:35Z, 01:15Z), derived from the CRH `_WINDOW_*_HOUR_LST` constants. Heavy studies are serialized by a flock | README "Protected window" | constants imported by `continuous_strategy` | `test_analysis_units_serialized.py` | AMB | H |
| OPS-25 | After the fq switch, downstream timers must be composition-aware (finding F9). Tally refuses on fq through a sentinel boundary artefact. Tally timers are enabled only for v2/v4 | `FQ_GO_LIVE_PLAN:25, 280-309` | `deploy/families/artefacts/not_applicable_boundary.json` | S7 tests (not read) | A | H |
| OPS-26 | Nightly studies peak at 10–24 GB: stop the study, never the node; run one heavy job at a time | memory; L-53 | studies slice 16G; study flock | not read | A | H |
| OPS-27 | One node per trading day. The supervisor forwards `os.environ` to the child via `env=`, never argv. The two operator caps (maximum daily budget, maximum per position) enter only by reference through `operator.env` | unit `:18-31, 104-113`; R8 §6 | `trade_supervisor.py` `spawn_node` | `test_trade_supervisor_phase1_unit.py:94`; `test_operator_control_assignment_scan.py` | A | C |
| OPS-28 | The sending family is one id resolved against `deploy/families/<id>.json`. Promoting a family is a unit edit, never a source edit | unit `:119-128` | unit plus settings resolver | `test_trade_supervisor_phase1_unit.py:49-68` | A | C |

### (e) Engineering constraints

| ID | Requirement | Source | Enforcement | Test | St | Ev |
|---|---|---|---|---|---|---|
| ENG-01 | Layer contract, exhaustive: app > analysis > strategy > runtime > adapters > ingest > persistence\|registry\|normalize > features\|settlement > domain. **Exactly 4 `ignore_imports` debt rows**: `adapters.polymarket_us.{config,factories}->runtime.settings`, `ingest.nws_actor->runtime.health`, `persistence.quote_tape_gaps->adapters.polymarket_us.tape_records` | pyproject `:73-108` | lint-imports | `test_test_safety_tooling_config.py:49-90` (set equality) | A | C |
| ENG-02 | Never import Nautilus's Polymarket .com adapter; allow-list empty forever | `AGENT_ARCHITECTURE.md:13-14`; pyproject `:110-128` | lint-imports | `test_test_safety_tooling_config.py:111-120`; `test_nautilus_native_import_gate.py:157` | A | C |
| ENG-03 | Live path never imports `breezy.analysis`; analysis never imports nautilus directly; settlement/strategy never reach archive or `nbp_derived_store`; hypothesis ledger isolated in both directions | pyproject `:130-212` | lint-imports | `test_test_safety_tooling_config.py:122-145`; `test_archive_import_contract.py` | A | C (ledger contracts H) |
| ENG-04 | `nautilus-trader==1.231.0` exact; `~=` forbidden; Nautilus itself immutable | CLAUDE.md; pyproject `:11` | pin | `test_test_safety_tooling_config.py:36-40` | A | C |
| ENG-05 | `pynacl==1.6.2` and `scipy==1.18.1` are core, exact pins (signing barrier B2; R-9 bootstrap) | pyproject `:13-26` | pin | not read | A | H |
| ENG-06 | mypy strict over `src/breezy/*`, `scripts/{venue,analysis,archive}`, `tests`. Waivers: `disallow_subclassing_any` only, for named modules plus a `strategy.*` wildcard | pyproject `:234-340` | mypy | `test_strategy_module_gate.py:105-131` | A | C |
| ENG-07 | In-gate mypy ratchet: CLEAN paths must have 0 errors; CEILINGS are exact (a count above **or below** its ceiling fails); new files must be clean; mypy 2.3.1. CI mypy is advisory until Wave 7. W2 is not merged (`4b0b4f6` staged) | CF-12 Rev2 `:43-55, 84, 115-121` | `test_mypy_ratchet.py:282-348`; `tests.yml` `continue-on-error` | same | A | C |
| ENG-08 | ruff: line length 100, py313, E501 on; `archive_table.py` excluded from formatting because its bytes are frozen. Ruff runs in CI only, not in the local gate | pyproject `:214-232` | CI `uv run ruff check .` | archive regeneration tests (bytes) | A | H |
| ENG-09 | Egress-blocked gate: `scripts/ci/run_tests_no_egress.sh` tries bwrap, then unshare, else exits 3. conftest aborts the session if exec-egress modules exist and the block is not both attested and proven by a real native connect (N3). N1 = in-process block | script header; conftest | `conftest.py:82-90, 300-330, 359` | `test_execution_egress_firewall_guard.py` | A | C |
| ENG-10 | Default deselection is the literal `-m 'not live and not venue_live and not real_money'`. `venue_live` needs 3 locks; `slow` is opt-in via `BREEZY_RUN_SLOW` skipif in each test; `memory` runs by default | pyproject `:46-58`; L-54 | `conftest.py:45-59, 213-217, 411` | `test_probe_containment.py:585` | A | C |
| ENG-11 | No `git stash` in any form (list/show allowed) | L-51; memory | `.claude/hooks/no-git-stash.sh`, PreToolUse(Bash) | **none** | A | H |
| ENG-12 | PROGRESS.md at most 250 lines / 12 KB, open state only (now 95 lines) | `PROGRESS.md:7-13`; L-5 | `.claude/hooks/progress-size-gate.sh`, PostToolUse | **none** | A | H |
| ENG-13 | Run the full no-egress gate on the integration branch after **every** merge; a worktree gate is not integration evidence | L-43 plus amendment; `PROGRESS.md:44` | none (procedural) | n/a | A | H |
| ENG-14 | Never run `uv` / `pip` / `uv run` from a worktree; use `/home/jon/breezy/.venv/bin/python` with `PYTHONPATH=<wt>/src`. Child processes derive `src` from `breezy.__file__` | L-51; L-43 amendment | `tests/support/host_python.py` (`resolve_sibling_entrypoint`) | partial | A | H |
| ENG-15 | Units execute from the primary tree; a commit there is one daemon-reload (or next spawn) from live | memory; README `:1-12` | `~/.config/systemd/user` symlinks | n/a | A | C (observed) |
| ENG-16 | Exact-set barriers are widened in the same commit, never relaxed or obfuscated; a contract test outranks a plan | L-12, L-46 | barrier tests | `test_execution_egress_firewall_guard.py`; `test_cage_rule_constants_are_pinned.py:958-1240` | A | C |
| ENG-17 | Before editing shared config (pyproject, conftest, gate script), grep tests for literal pins | L-54 | pins | `test_test_safety_tooling_config.py`; `test_probe_containment.py:585` | A | C |
| ENG-18 | Tests that touch HOME-derived paths redirect `Path.home` | L-27 | autouse fixtures (not read) | not read | A | H |
| ENG-19 | Docs layout: core/{PROGRESS, LESSONS, archive, findings}, evidence/RULING_*, plans/(+backlog), specs (PREREG), reference (vendored), prompts, strategies. `src` never reads `docs/evidence` | global CLAUDE §7 | none written down in the repo | `test_probe_containment.py:550` | AMB | H |
| ENG-20 | Undocumented: gate tests **write into the real `src` tree** (`test_archive_import_contract.py:49-56` rewrites `persistence/catalog.py` and restores it in `finally`; the strategy/native import gates plant modules on disk) | none | tests | self | A | C |

### (f) Venue coupling outside `adapters/` (Polymarket.us today; Kalshi parked)

| ID | Coupled symbol | file:line |
|---|---|---|
| V-01 | Fee formula θ·p·(1−p) restated in 4 places | `strategy/current_rung_hold/decision.py:320` `_fee` (cent, HALF_EVEN); `monitor_evidence.py:213` `exit_fee`; `strategy/weather_common/costs.py:155` `venue_fee_prob`; `resting_decider.py:63, 146` (delegates to `adapters/.../fees.py:161`) |
| V-02 | θ constants and fee-drift probe (venue HTTP from the strategy layer) | `analysis/hypothesis_ledger.py:202` `EVIDENCED_FEE_THETA`; `persistence/family_manifest.py:181`; `strategy/current_rung_hold/fee_drift_probe.py:148-188` (wire key `feeCoefficient` `:166`, `MARKET_BY_SLUG_PATH`, `QUOTA_KEY_DISCOVERY`); `app/trade.py:269-339`; `costs.py:116, 356` |
| V-03 | NO bought as SELL/BUY_SHORT; venue nets a NO holding as short YES | `strategy/current_rung_hold/set_family_halt_cli.py:260`; `weather_common/risk.py:217, 289`; `ladder_ev/scoring.py:75`; `calibration_mean_reversion/decision.py:206` |
| V-04 | Slug and instrument grammar (`^` separator, `no` suffix) | `domain/instrument_leg.py` (`INSTRUMENT_SEPARATOR`, `NO_LEG_SUFFIX`; the adapter delegates here); `runtime/node_config.py:692`; `app/trade.py:40`; `current_rung_hold/composition.py:31`; `monitor_wiring.py:66`; `continuous_strategy.py:45`; `forecast_quantile_ladder/strategy.py:57`; `trial_day_latch.py:75-76, 246` (`POLYMARKET_US_VENUE`) |
| V-05 | Tick and minimum size | `resting_decider.py:84` `TICK=0.01`; `decision.py:167` `_CENT`; `weather_common/bucket_contract.py:49-52`; `cli_settlement_print_lock/strategy.py:181, 292` |
| V-06 | Market surface | `current_rung_hold/config.py:76` `SUPPORTED_STATIONS` (LAX, MDW, MIA, SFO = 4); `registry/sites.toml:117-306` `[sites.polymarket_us.<5 cities>]` (keyed by venue on purpose); venue settlement clock America/New_York at `registry/settlement_clock.py:16`, `sites.py:156` |
| V-07 | Venue-neutral controls housed in the adapter | `adapters/polymarket_us/operator_controls.py` (`DailySpendLedger`, `utc_day_for_ns`), `safety.py` (permit). Imported by `runtime/order_enablement.py:48-53`, `continuous_strategy.py:43`, `scripts/operator/print_operator_controls.py` |
| V-08 | Strategy calls the venue execution chain directly | `exit_wiring.py:28`; `continuous_strategy.py:31-45`; `set_family_halt_cli.py:101-103, 323-324` (builds `PolymarketUSExecutionClient`); `runtime/mark_no_side_position_captured_cli.py:27` |
| V-09 | Composition root and runtime | `app/trade.py:34-41, 144, 998`; `runtime/trade_cli.py:84-123, 592-593`; `node_config.py:88, 119, 534, 689, 878`; `quote_tape_cli.py:74-79`; `backtest_harness.py:153-154, 712`; `exec_state_db_path.py:40`; `quote_tape_salvage.py:71` |
| V-10 | Persistence debt row | `persistence/quote_tape_gaps.py:19` |
| V-11 | Fee-schedule guard | `current_rung_hold/strategy.py:107-108`; `continuous_strategy.py:44` |
| V-12 | Kalshi status | `wip/kalshi-s4-registry` @58280b6f: 1 commit, merge-base **1208 commits** behind HEAD. Planned forward-compat seam: `sign(bytes)` with venue-specific canonical strings (`AGENT_ARCHITECTURE.md:163`) |

**Neutral today:** `ingest/`, `normalize/`, `settlement/` (leg via `domain`), `domain/` (apart from the grammar in V-04), `analysis/` (apart from V-02), and the registry's structure.
**Coupled:** `strategy/current_rung_hold` (heavily), `runtime`, `app`. `forecast_quantile_ladder` touches only symbology.

## B. Conflicts

1. **`PROGRESS.md:86` is stale against HEAD.** It says "activation (S9) still pending", but HEAD 60290e9d *is* the S9 activation. The installed unit names `pm_us_crh_fq_v1` and shows no changed-on-disk warning.
2. **R8 §(viii) contradicts L-26.** The runbook (`:558-582`) says `start_new_session=True` "ensures clean shutdown on session end"; L-26 (sharpened 09-24) says a new session is not enough and `systemd-run --user` is required. The recipe's code also calls `os.fcopen`, which does not exist.
3. **Who owns hand relaunches.** `RULING_permit_daily_coverage:95-103` and R8 treat hand relaunches as "operator-attended, the operator's own call". Operator memory says only the two caps belong to the operator. In practice agents hand-launch from scratchpad scripts, and those nodes carry no A-1 ceiling.
4. **`deploy/systemd/README.md:9-10` names the wrong drop-in.** It names `breezy-replay-daily.service.d/zz-c2-time-v-TEMPORARY.conf`; the host has `zz-memory-containment-TEMPORARY.conf` (10G/12G). The repo unit says 3G/4G.
5. **Ingest drop-in outlived its removal condition.** `PROGRESS.md:51` says to remove it after the 09-29 proof (peak ≤2G); the 12G/14G drop-in is still present 10-01. Meanwhile the repo unit's 4G is the value L-49 documents as the cause of the thrash.
6. **`RUNBOOK_NWS_COLLECTION.md` §2 vs the real unit.** The runbook prescribes a hardened system-scope unit (`User=_breezy`, `ProtectHome`, `/var/lib`). The actual `breezy-nws-ingest.service` is user-scope, unhardened, with no alerts.env and no OnFailure.
7. **`AGENT_ARCHITECTURE.md:43, 172` still says pin `~=1.231`.** pyproject has `==1.231.0` and a test forbids `~=` (doc superseded).
8. **Missing credential pre-commit guard.** `AGENT_ARCHITECTURE.md:173` lists a pre-commit guard against credential-shaped strings in `.claude/` as a "mandatory control". None exists; the only git hook is a post-merge codegraph reindex, and it fires only on `main`, which is not the production branch.
9. **`STRATEGY_QUICKSTART.md:383` says strategy "is in the top layer".** The contract puts `app` and `analysis` above it.
10. **Memory rule vs debt rows.** The memory rule "adapters never import `breezy.runtime`" conflicts with 2 waived ignore rows (`adapters.polymarket_us.{config,factories} -> runtime.settings`).
11. **Stale line anchors in unit comments.** Examples: `pyproject.toml:271` (now `:404`), `trade_supervisor_core.py:31-34`, `:52`, `:80-82` (now `:34-37`, `:74`, `:249-251`), and `trade_supervisor.py:700-737`.
12. **README tally references vs tests.** README cites `breezy-pm-crh-cont-tally` at 17:25Z, but `test_deploy_timer_hours.py:157` says 17:15 and 17:25 are unowned after the WP-11b merge. `breezy-live-tally.timer` exists in the repo but is not installed on the host.
13. **Protected window derived from the wrong family.** P is derived from CRH LST constants while the sending family is now fq_v1. Light timers (16:52, 17:20, 17:30, 17:40) also start inside P.
14. **LESSONS numbering.** The brief scopes L-1..L-43, but `LESSONS.md` runs to **L-55**. L-44 to L-55 bind (worktree, venv, latch, memory and test-default rules).
15. **Station surface mismatch.** `SUPPORTED_STATIONS` has 4 cities (`config.py:76`), while the registry and PROGRESS say the surface is 5 cities × HIGH. NYC is excluded from CRH with no doc explaining it (AMB).

## C. Gaps

**Requirement with no enforcement or test:**
- OPS-04 `KillMode=process`. The unit calls it "THE MOST IMPORTANT LINE" and no test pins it; `RestartPreventExitStatus=2` and `TimeoutStopSec` are also unpinned.
- OPS-09: no guard on the 01:00–16:40Z supervisor-restart window.
- OPS-11: the 4-part liveness definition exists only in operator memory. The supervisor does not check log mtime or tape advance.
- OPS-15 / ENG-13 / ENG-14 are procedural only: `systemd-run`, full gate after every merge, no installers from a worktree.
- ENG-11 / ENG-12: neither hook has a test.
- No credential pre-commit guard (conflict 8).
- OPS-19: no delivery path for NWS-ingest alerts, and no OnFailure on the recorder, NWS ingest or supervisor. This contradicts L-52.

**Enforcement with no documented requirement (characterization-test candidates):**
- Boot retry 8 tries / 15 min (`core.py:65-69`).
- `PERMIT_ALERT_HEARTBEAT` 60 min and `PERMIT_DEFERRED_MAX` 20 min (`core.py:140, 146`).
- `SELF_CHECK_GAP_ALERT_THRESHOLD_HOURS` 26 (`core.py:854`) and `MIDDAY_READINESS_RECHECK_TIMEOUT` 2 min (`:60`).
- Supervisor log-marker strings parsed as an API (`core.py:91-190`).
- `UMask=0077`; ingest `Nice`/IO class; `StartLimitBurst` values.
- The host-only drop-ins and tmux-scope cap.
- The ratchet's "a count below its ceiling fails" rule.
- Tests that mutate `src` (ENG-20).

## D. Rulings, lessons and hooks that constrain restructuring

- **Never weaken safety, contract, settlement or NO-SEND firewall tests, or `BacktestOrderGuard`; never set `allow_short=True`** (`PROGRESS.md:39-42`). PREREG semantics change only via a ruling. Exact sets are widened in the same commit (L-12) and never disguised (L-46). The cage pins (`test_cage_rule_constants_are_pinned.py`: "exactly four exemptions", P1 rebinding scan over `src`, `scripts` and `tests`) break on any move or rename of a pinned constant.
- **Moving packages touches pinned config.** The layer list and the exact 4 ignore rows are pinned by set equality, so paying off or moving any debt edits `test_test_safety_tooling_config.py`. Under L-54 that is a safety-reviewed item. The addopts literal is pinned too.
- **Moving files shifts mypy ratchet counts.** CLEAN/CEILINGS are exact, so a move between groups needs a re-baseline in its own commit. CF-12 W2 is staged (`4b0b4f6`) and W3 (314 import-not-found errors) needs a design pass.
- **Byte-frozen and layer-pinned files.** `strategy/current_rung_hold/archive_table.py` must not be reformatted. CLIs that touch `TrialDayLatch` must live in `strategy`, because runtime cannot import strategy (pyproject `:385-389`).
- **Runtime contracts that renames would break.** Console-script names and argv anchors (`breezy-trade$`, `breezy-trade-supervisor-daily$`), log marker text, and permit-line format are all parsed by the supervisor. The env var names `BREEZY_SENDING_FAMILY_ID` and `BREEZY_ALERT_WEBHOOK_URL` are pinned by unit tests.
- **Live-tree hazards:**
  - Units execute from `/home/jon/breezy`, which is on `feat/data-capture-and-risk`, not `main`.
  - Supervisor code loads once: restart only inside 01:00–16:40Z, never SIGKILL, keep `KillMode=process`.
  - Gate tests transiently rewrite `src` files (ENG-20). Never run the gate in the primary tree or alongside another gate in the same tree.
- **Worktree and shared-state rules.**
  - Shared venv: no `uv`, `uv run` or `pip` from a worktree (L-51).
  - `PYTHONPATH=<wt>/src` is required, and child processes derive `src` from `breezy.__file__`.
  - `git stash` is banned and hook-blocked.
  - Agent worktrees may start stale.
  - Serialize writers of read-modify-write stores (L-50).
  - Full gate after every merge (L-43).
- **Operator controls.**
  - Prose must not name an operator-reserved control by its env var name (L-39).
  - The two caps stay by-reference in `operator.env` and are never written by the build side.
- **Before planning any extraction (L-1/L-11): Nautilus is immutable.** First prove that no native capability already provides it.

---

**Summary:** 28 ops rows, 20 engineering rows, 12 venue-coupling rows. Of the 48 requirement rows, 26 are CONFIRMED and 22 HYPOTHESIS. There are 15 conflicts, 9 enforcement gaps, 10 undocumented-enforcement candidates and 9 restructuring constraints.

Top 5 conflicts and gaps:
1. `KillMode=process` (the guard that keeps a node holding a position alive through supervisor restarts) has no test pinning it.
2. The gate's tests rewrite `src/breezy/persistence/catalog.py` in place, and every systemd unit executes from that same primary tree.
3. The R8 hand-relaunch recipe contradicts L-26, and the live hand-launched node's launcher is an unversioned `/tmp` scratchpad script with no A-1 permit ceiling.
4. The host-only TEMPORARY memory drop-ins (12G/14G and 10G/12G) override the repo caps (4G/3G), have outlived their removal condition, and the README names the wrong file.
5. NWS ingest has no alert delivery (no alerts.env, no OnFailure), and the 4-part liveness definition exists only in operator memory.

Also note:
- `PROGRESS.md` says S9 is pending although HEAD is the S9 activation.
- Production runs on `feat/data-capture-and-risk`, not `main`.