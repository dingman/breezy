Commit: e4848c39a979bac5a91b8f6b3887f75c497c1be8
# Scope stop, ops serialization, and the v3 launch decision (2026-09-12) — Rev 1

**L-1.** (a) **GENUINELY-ABSENT** — host-level job scheduling, mutual exclusion, and memory
containment for *separate processes*. Installed-source negative over
`.venv/lib/python3.13/site-packages/nautilus_trader/` (`grep -rl` via Bash, `*.py|*.pyx|*.pyi`):
`systemd` 0 files, `OnCalendar` 0, `cgroup` 0, `MemoryMax` 0, `subprocess.Popen` 0, `os.kill` 0.
**Positive control:** `class TradingNode` → 3 files (`live/node.py:39`, `live/node_builder.py:34`,
`live/config.py:284`), so the grep reaches the tree. (b) **NATIVE-sufficient but inapplicable** —
`Clock.set_timer` (`common/component.pyx:419`) schedules callbacks *inside one running node
process*; every unit in scope is a separate OS process, and the goal is to NOT run them beside the
node. Nothing here extends, patches, or reimplements Nautilus: the whole plan is systemd unit text,
two shell wrappers, one CLI exit-code fix, and docs.

**Constraints.** Nautilus immutable. `allow_short` stays False. No safety/settlement/contract test
weakened or deleted. No operator-reserved value (max daily budget, max per position) assigned,
read, echoed or logged. Live-trading enablement and the NO-SEND execution-egress firewall are not
touched. PREREG v3 is BINDING — nothing here changes §3, §5 or §9. Gate:
`scripts/ci/run_tests_no_egress.sh` (addopts already has `-q`; never add `-q`), then `lint-imports`
and `mypy` after every slice. **No process or unit is signalled or restarted by the build side; the
only restart in this plan is the operator's own §8 D-1 procedure.**

## 1. Goal state (falsifiable)

For 30 days from 2026-09-13: **(G1)** every enabled `breezy-*` timer is load-bearing for
`pm_us_crh_cont`'s verdict or for the tape the verdict reads, each non-load-bearing one disabled
with its settling-evidence citation recorded in the repo; **(G2)** no unit with a >1 GB observed
peak starts inside the protected window **P = [15:45Z, 00:15Z)**, and at most one heavy study runs
at a time host-wide; **(G3)** a per-type ingest conversion failure makes its unit fail; **(G4)**
the v3 launch state is whatever the operator chose, by a written reversible procedure, with the
choice and its timestamp recorded.

Falsifier for each: **G1** `systemctl --user list-timers` lists only the keep-set;
**G2** `journalctl --user` over 30 days shows no `Starting breezy-{k1,offer-gate,mb}-daily` inside P
and no two heavy `Consumed …` intervals overlapping; **G3** one journal line
`breezy-quote-tape-ingest.service: Failed with result 'exit-code'` on a run that logs
`conversion of … failed`; **G4** `docs/core/PROGRESS.md` carries the decision line.

**Happy walk (today).** 16:40Z `STOP_PRIOR` SIGTERMs the tracked node
(`trade_supervisor_core.py:31-34`, unit `breezy-trade-supervisor.service:7-13`) → 16:50Z `LAUNCH`
spawns today's node with the supervisor's own env (`trade_supervisor.py:512` `env=dict(env)`, spawn
sites `:808,:874`) → 17:05Z `SELF_CHECK` runs the three continuous-family checks
(`trade_supervisor_core.py:207-283`) → 17:15Z `breezy-pm-crh-v2-tally` (0.4 GB / 4 s) →
00:15Z onward the heavy studies, one at a time, none inside P.

**Failure walks.** (i) Heavy study inside P → host swaps → observed 2026-09-11 22:32:08
`breezy-k1-daily.service: Main process exited, code=killed, status=15/TERM`, `17.6G memory peak,
663.2M memory swap peak`. (ii) Ingest hits a republished interval → `ValueError` is logged per type
(`quote_tape_ingest_cli.py:790-800`) but `ingest_instance` returns `outcome="converted"`
unconditionally (`:803-805`) → `run` sees no `"failed"` instance (`:1341-1344`) → exit 0 → unit
reports `Finished` (journal 2026-09-12 12:31:33 / 15:15:31) → the gap is invisible. (iii) Supervisor
unit restarted while a node holds a position → `KillMode=process` (`:144`) leaves it alive; systemd
logs `Found left-over process 3196952 (breezy-trade) in control group … Ignoring` (09-12 01:24:03,
01:37:20).

## 2. Evidence vs code today

| # | Piece | Code/state today (file:line, journal) | Gap |
|---|---|---|---|
| A | K1 cheap-open settled DEAD | `grok_no_edge_verdict_2026-09-02.md:35,88` (Kalshi exhaustive ≤0.05 n=2317 k=35, all 5 stations DEAD; our tape n=0); `ladder_ev_peer_review_2026-09-07.md:24` B1 "DO NOT REDESIGN" | `breezy-k1-daily.timer` still enabled, 22:30Z, 12–17.6 GB |
| B | CLI-basis candidate #2 "thin, not a GO" | `cli_basis_offer_gate_settlement_2026-09-02T053500Z.md`; `cli_basis_setup_win_rate_corrected_2026-09-02T061722Z.md`; audit §1.3 | `breezy-offer-gate-daily.timer` enabled, 22:45Z, 12–15.3 GB |
| C | M_A/M_B descriptive only | `grok_armed_validation_2026-09-03.md:57` ("M_B is a descriptive join, not a Nautilus backtest"); audit ground truth: `mb_current_rung_edge_2026-09-11.md` both verdicts UNDERPOWERED | `breezy-mb-daily.timer` enabled, 13:30Z, 36 min, 3.2–11.6 GB. Its *outputs* have no binding consumer; `family_tally_v2.py:86` imports the study **module** (`ASK_BANDS`, `classify_ask_band`), never its nightly artifact |
| D | v1 6d tally off the v2/v3 statistic | `PREREG_v2…:23-25` ("Sequential score, `I_k`, remaining-α and `mean(BE_i)` stay off `live_family_tally.py`"); `PREREG_v3…:165` pins `v1 byte-identical` — a **code** pin, not a run requirement | `breezy-live-tally.timer` enabled 14:30Z; 0.18 GB / 1.7 s; outside P. Whether v1's stop rule still binds is a RULING (§8 R-1) |
| E | 6-hourly ingest timer redundant | `breezy-quote-tape-ingest-frequent.timer` `OnCalendar=*:0/15` fires :00/:15/:30/:45 of every hour, `Unit=breezy-quote-tape-ingest.service` — strictly covers the 6-hourly `00,06,12,18:15:00 UTC`; both carry `Persistent` | 6-hourly timer still enabled; its 18:15Z tick lands inside P |
| F | In-window load is the *frequent ingest*, not k1↔offer-gate | k1 22:30Z (≤7 min) and offer-gate 22:45Z do not overlap at nominal runtimes; the */15 ingest reached **4.0 G = exactly its `MemoryHigh=4G`** at 13:46/14:01/14:16Z today, i.e. already throttling, every 15 min, inside P | no `Slice=`, no nice/ionice, no window awareness |
| G | `After=`/`Conflicts=` cannot serialize timer jobs | `man systemd.unit` (host, systemd 259): `Before=,After=` order units only "**if both units are being started**" — independent timer activations are separate transactions; `Conflicts=` "starting it will **stop** all of them" — it would SIGTERM an in-flight study, reproducing the 09-11 shape | no mechanism in place; `Conflicts=` is the wrong one |
| H | Ingest failure never fails the unit | `ingest_instance` `:803-805` hardcodes `outcome="converted"`; the per-file path `:1102-1114` correctly maps `any_failure → "failed"`; `run` `:1341-1344` keys the exit code off the instance outcome only | journal: `instance 213d84f7-…: ingested quote_tick=failed order_book_depths=failed … custom_venue_settlement_snapshot=failed custom_depth_truncation=failed` then `Finished` (exit 0) |
| I | Orphan node on unit restart is BY DESIGN | `breezy-trade-supervisor.service:131-144` ("THE MOST IMPORTANT LINE IN THIS FILE"); `SupervisorPorts.find_node_pid`/`resolve_intent_lock_holder` (`trade_supervisor.py:700-737`) re-adopt by argv + PID-verified flock | systemd's `Found left-over process` line reads like a defect; nothing in the repo says it is expected |
| J | **v3 has no nightly measurement producer** | `score-live-trials-run.sh:26` hardcodes `deploy/families/pm_us_crh_v2.json`; `breezy-pm-crh-v2-tally.service:46` passes `pm_us_crh_v2`. v2's manifest prefix is `current_rung_hold/trial/`, v3's is `continuous_rung_hold/trial/`; `score_live_trials.main` filters fills by `manifest.trial_id_prefix` + `d0_climate_day` (`score_live_trials.py:1584-1586`) | a v3 fill is filtered OUT of the only scorer that runs; `family_tally_v2.py` *does* support v3 (`_CONTINUOUS_TRIAL_ID_PREFIX:154`, `v3_residual_from_fill_source:1051`) and `family-tally-v2-run.sh` is already family-parameterized (`:27,:61`, `pm_us_crh_cont` is a valid id) — only the **unit wiring** is missing |
| K | Repo is deployed truth — with one hole | all 20 breezy units in `~/.config/systemd/user/` are symlinks into `deploy/systemd/` **except** `breezy-nws-ingest.service`, a real file (Aug 24) with no repo copy | out of scope here; named so it is not mistaken for coverage |

**Protected window derivation.** Decision window is `[12:00, 17:00)` LST
(`structural_dead_stop.py:17,176`). September offsets: MIA (EDT −4) 16:00–21:00Z; MDW (CDT −5)
17:00–22:00Z; LAX/SFO (PDT −7) 19:00–00:00Z. Union **[16:00Z, 00:00Z)**, and the supervisor's
16:40/16:50/17:05Z hops sit inside it. With 15 min margin: **P = [15:45Z, 00:15Z)**. The brief's
`[17:00Z, 01:00Z)` is **corrected** — it starts an hour late (MIA/MDW) and ends an hour late.

## 3. Design

**Where.** `deploy/systemd/*.timer|*.service` (text), `deploy/systemd/{k1-daily,mb-daily}-run.sh`
and the offer-gate ExecStart (flock wrapper), one new `deploy/systemd/breezy-studies.slice`,
`src/breezy/runtime/quote_tape_ingest_cli.py` (one function), `deploy/systemd/README.md`.

**Mechanisms chosen, and why.** (1) *Stop* = `systemctl --user disable --now <timer>` — reversible
by `enable --now`, leaves the unit file installed. (2) *Window* = move `OnCalendar` out of P;
no `Conflicts=` (evidence G: it stops the running job). (3) *Mutual exclusion* = a blocking-free
`flock` taken **inside each wrapper** (`exec 9>"$LOCK"; flock -n 9 || { say "SKIPPED — another
study holds the studies lock"; exit 0; }`) — shell-only, no systemd semantics risk, skip-not-kill.
(4) *Aggregate ceiling* = `Slice=breezy-studies.slice` on the heavy units, the slice carrying its
own `MemoryHigh=`/`MemoryMax=`; per-unit ceilings stay (pinned by
`test_analysis_units_memory_capped.py`). (5) *Light-job exemption*: ≤1 GB observed peak **and**
≤60 s wall may stay inside P — covers `pm-crh-v2-tally` (0.4 GB/4 s), `score-live-trials`
(0.85 GB/9 s), `live-tally` (0.18 GB/1.7 s).

**Disable-do-not-delete (repo stays truth).** A disabled timer's **file must stay in the repo**:
`test_deploy_timer_hours.py::_is_periodic` exempts `breezy-quote-tape-ingest-frequent.timer` from
the HH:MM collision scan **only** because a sibling timer shares its `Unit=`; deleting
`breezy-quote-tape-ingest.timer` removes that sibling and turns the frequent timer into an
unparseable orphan → `test_no_two_timers_share_an_hour_minute_tick` goes RED. The repo therefore
records *state*, not absence: a `# DISABLED <UTC date> — <verdict> — evidence: <doc:line> —
re-enable: systemctl --user enable --now <timer>` header block in each disabled `.timer`, plus one
table in `deploy/systemd/README.md`, held consistent by a new test.

**Not changed (byte-unchanged pins).** `deploy/systemd/breezy-trade-supervisor.service` — pinned by
`tests/unit/test_trade_supervisor_phase1_unit.py::test_installed_unit_runs_the_continuous_family_not_v2`
and `::test_installed_unit_pins_the_phase0_shadow_flag_off_after_operator_env` (that module reads the
**repo** path, `:20-21`). Per-unit `MemoryHigh=`/`MemoryMax=` values — pinned by
`test_analysis_units_memory_capped.py`. The 14:15Z and 17:15Z ticks — pinned by
`test_deploy_timer_hours.py::test_1415_utc_is_owned_by_exactly_one_timer` and
`::test_1715_utc_is_owned_by_exactly_one_timer`. Per-type `"failed"` marking in ingest — pinned by
`test_quote_tape_ingest_cli.py::test_a_native_value_error_still_marks_that_type_failed:705`.
Scoring/tally semantics, PREREG v3 §3/§5/§9, `KillMode=process`.

## 4. Increments

| id | size | RED test(s) FIRST (path::name) | minimal change | observable that proves it | verification |
|---|---|---|---|---|---|
| **I1 stop-doing** | S | `tests/unit/test_deploy_disabled_timers.py::test_every_disabled_timer_file_carries_a_marker_with_an_evidence_citation`; `::test_the_readme_disabled_table_and_the_timer_markers_agree`; `::test_no_disabled_timer_file_was_deleted_from_the_repo` | add the `# DISABLED …` header to `breezy-k1-daily.timer`, `breezy-offer-gate-daily.timer`, `breezy-mb-daily.timer`, `breezy-quote-tape-ingest.timer`; add the README table | `systemctl --user list-timers --all` no longer lists the four | `scripts/ci/run_tests_no_egress.sh tests/unit/test_deploy_disabled_timers.py tests/unit/test_deploy_timer_hours.py`; then `systemctl --user disable --now breezy-k1-daily.timer breezy-offer-gate-daily.timer breezy-mb-daily.timer breezy-quote-tape-ingest.timer`; `systemctl --user list-timers --all --no-pager` |
| **I2 serialize survivors** | M | `tests/unit/test_analysis_units_serialized.py::test_no_enabled_heavy_unit_timer_fires_inside_the_protected_window`; `::test_every_heavy_study_unit_declares_the_shared_studies_slice`; `::test_the_studies_slice_declares_its_own_memory_ceiling`; `::test_every_heavy_study_wrapper_takes_the_studies_flock_and_skips_when_held` | new `deploy/systemd/breezy-studies.slice`; `Slice=breezy-studies.slice` on the heavy `.service` files; flock guard in `k1-daily-run.sh`, `mb-daily-run.sh`, the offer-gate wrapper; `Nice=10` + `IOSchedulingClass=idle` on `breezy-quote-tape-ingest.service`; lower its `MemoryHigh=4G`→`2G` (`MemoryMax=6G` unchanged) | a second heavy job started by hand logs `SKIPPED — another study holds the studies lock` and exits 0; `systemctl --user show <unit> -p Slice` = `breezy-studies.slice` | `scripts/ci/run_tests_no_egress.sh tests/unit/test_analysis_units_serialized.py tests/unit/test_analysis_units_memory_capped.py tests/unit/test_deploy_timer_hours.py`; `systemd-analyze verify --user deploy/systemd/breezy-studies.slice` |
| **I3 ingest failure surfacing** | S | `tests/unit/test_quote_tape_ingest_failure_surfacing.py::test_a_whole_instance_run_with_one_failed_type_reports_outcome_failed`; `::test_run_returns_exit_conversion_failed_when_a_whole_instance_type_failed`; `::test_a_republished_overlapping_interval_reproduces_the_non_disjoint_refusal` (reproducer from instance `213d84f7-248c-4070-91fe-fa445b8c4327`, `QuoteTick` file `2026-09-11T00-00-04-539130527Z_2026-09-11T09-00-20-353565962Z.parquet`, interval `(1789084804539130527, 1789117220353565962)` against existing `(1789084804539130527, 1789085738149459762)`) | `ingest_instance` (`quote_tape_ingest_cli.py:803-805`) returns `outcome="failed"` when any `TypeConversionResult` satisfies the existing `_outcome_has_failure` (`:826-833`) — reuse it, do not re-derive | unit run over the affected instance ends `Failed with result 'exit-code'`, `status=3` | `scripts/ci/run_tests_no_egress.sh tests/unit/test_quote_tape_ingest_failure_surfacing.py tests/unit/test_quote_tape_ingest_cli.py`; `lint-imports`; `mypy src/breezy/runtime/quote_tape_ingest_cli.py` |
| **I4 orphan node** | S | **characterisation only (L-33)** — no RED test. Mutation evidence: the two journal lines (09-12 01:24:03, 01:37:20) are the *designed* outcome of `KillMode=process` (`breezy-trade-supervisor.service:131-144`); flipping that line to `control-group` is exactly the mutation the design forbids, and `[B2]` adoption (`trade_supervisor.py:700-737`) is what makes the survivor safe | `deploy/systemd/README.md`: record "`Found left-over process … (breezy-trade) … Ignoring` is EXPECTED after a supervisor restart; it is the node surviving by design (L-26). Never `SIGKILL` it; the only legitimate stops are the 16:40Z `STOP_PRIOR` hop and an explicit operator SIGTERM." | the README section exists and names the journal string verbatim | `scripts/ci/run_tests_no_egress.sh tests/unit/test_trade_supervisor_phase1_unit.py` (unchanged, must stay green) |
| **I5 v3 measurement wiring** | S | `tests/unit/test_score_live_trials_deploy.py::test_every_registered_family_manifest_has_a_scorer_wrapper_that_names_it`; `tests/unit/test_family_tally_v2_deploy.py::test_every_registered_family_manifest_has_a_tally_unit`; `tests/unit/test_deploy_timer_hours.py` (unchanged) must stay green for the new tick | parameterize `score-live-trials-run.sh`'s `FAMILY_MANIFEST` by `${1:-…pm_us_crh_v2.json}` (default byte-identical to today); add `breezy-pm-crh-cont-tally.{service,timer}` calling the **existing** `family-tally-v2-run.sh pm_us_crh_cont`, `MemoryHigh=1G`/`MemoryMax=2G`, `OnCalendar` at a free HH:MM inside P **only if** the light-job exemption holds, else 01:45Z | a `family_tally_v2_pm_us_crh_cont_<date>.md` artifact appears in `~/.local/share/breezy/derived/` | `scripts/ci/run_tests_no_egress.sh tests/unit/test_score_live_trials_deploy.py tests/unit/test_family_tally_v2_deploy.py tests/unit/test_deploy_timer_hours.py` |
| **I6 parking** | S | characterisation only (L-33): the parked artifacts are already inert — `deploy/families/kalshi_crh_v1.json` is `DRAFT_NOT_REGISTERED` and `load_family_manifest` refuses it without `allow_draft=True` (`family_manifest.py:158-161`); `family-tally-v2-run.sh:73` attaches the structural pin to `pm_us_crh_v2` only ("never attached to kalshi_crh_v1") | `docs/core/PROGRESS.md` parking entry (see §5) — text only | the parking definition and re-open trigger are written down | no test change |

**Increment order.** I1 → I2 (I2's window test must see the post-I1 keep-set) → I3, I5 (independent
of each other and of I1/I2) → I4, I6 (docs). Every slice ends with `lint-imports` and `mypy`.

## 5. Acceptance

The next session must show: **(1)** `systemctl --user list-timers --all --no-pager` with the four
stopped timers absent and the keep-set present; **(2)** the four `.timer` files still present in
`git ls-files deploy/systemd`, each carrying its `# DISABLED` marker with an evidence citation, and
the README table matching; **(3)** `systemctl --user show <each heavy unit> -p Slice -p MemoryMax`
= `breezy-studies.slice` + its ceiling, and one log line proving the flock skip path; **(4)** RED→
GREEN output for `test_quote_tape_ingest_failure_surfacing.py` plus one real unit run ending
`Failed with result 'exit-code'`/`status=3` on the affected instance; **(5)** the v3 tally artifact
filename; **(6)** the two README paragraphs (orphan node, parking); **(7)** a full
`scripts/ci/run_tests_no_egress.sh` run — the known clock-dependent failure
`tests/unit/test_app_trade_main_permit_logging.py:115` is the *only* acceptable failure and must be
reported, not fixed here; **(8)** `lint-imports` and `mypy` clean for the touched modules.

## 6. Non-goals

No change to PREREG v3 §3/§5/§9, to scoring/tally **semantics**, or to any settlement math. No fix
for the non-disjoint-interval condition itself (I3 ships the reproducer and makes it loud; the fix
needs the republish root cause and is a separate item). No coverage/`structural_dead_stop` change.
No exec, reconciliation, alert-sink, or drift-allowlist work. No deletion of any unit file, study
script, `ladder_ev` module, or the Kalshi branch. No `ExecStopPost` reaper (rejected, §7). No
`Conflicts=`. No edit to `breezy-trade-supervisor.service`. No touch to `breezy-nws-ingest.service`.
No restart, reload, or signal of any running unit by the build side. No backtest/replay work.

## 7. Risks, blast radius, rollback

| Risk | Blast radius | Mitigation / rollback |
|---|---|---|
| Deleting a disabled timer file breaks the collision gate | `test_deploy_timer_hours.py` (all `deploy/systemd/*.timer`) | disable-never-delete is a plan rule and is pinned by `test_no_disabled_timer_file_was_deleted_from_the_repo`; rollback = `git checkout deploy/systemd` |
| A stopped study is later wanted | none at rest | `systemctl --user enable --now <timer>`; the file, the wrapper, and the script are untouched |
| `Slice=` typo silently drops the ceiling | all heavy units | `systemd-analyze verify --user` + `systemctl --user show -p Slice` in acceptance |
| I3 turns a tolerated state into a failing unit | `ingest_instance` → `run_ingest:1137` → `run:1305` (3 prod symbols, one file) + **40 tests** in `tests/unit/test_quote_tape_ingest_cli.py` (codegraph impact, depth 2) | per-type `"failed"` marking is unchanged (`:705` pin); only the instance outcome and exit code move. Expect the unit to go red **on the already-broken instance** — that is the point (G3), not a regression. Rollback = revert the one return statement |
| I5's new timer collides on HH:MM | `test_deploy_timer_hours.py` | the RED test runs first; pick a free tick |
| Flock file location | wrappers only | `$XDG_RUNTIME_DIR`, falling back to `$HOME/.local/share/breezy/`; a missing lock dir must **skip**, never run unguarded |
| `ExecStopPost` reaper (considered, **rejected**) | would SIGTERM a node holding a live position on every supervisor stop, contradicting `KillMode=process` and L-26 ("a coordinator session is not a supervisor; a live process launched inside it dies with it", `LESSONS.md:1121`) — the node is *designed* to outlive its supervisor | recommendation: **accept and document (I4)** |

## 8. Rulings / operator items

| id | item | owner | options | evidence needed |
|---|---|---|---|---|
| **D-1** | **v3 launch state for today (TIME-CRITICAL: 16:40Z STOP_PRIOR / 16:50Z LAUNCH)** | **OPERATOR** | (a) shadow first afternoon; (b) live as-is | procedure below; **this plan does not decide it** |
| R-1 | Is PREREG v1's 60/150 stop still in force for any REGISTERED family — i.e. is `breezy-live-tally`'s nightly run still evidence? | strategy-lead ruling | keep running as evidence / keep running as a drift guard only / disable | `PREREG_v1…§6:130,§7:137-150`; `PREREG_v2…:23-25`; `PREREG_v3…:165`; L-32 search of `docs/evidence/` for a prior v1-retirement ruling before proposing one |
| R-2 | A v3 tally invoked as `family-tally-v2-run.sh pm_us_crh_cont` **skips** the structural-dead population args — the `PM_FAMILY="pm_us_crh_v2"` gate (`:73,:85`) confines them to v2. Does PREREG v3 §9 require them for v3, and with which `--covered-listed-station-days` source? | strategy-lead ruling (PREREG v3 §9 meaning) | extend the gate to v3 / run v3 without the structural args / block I5 until ruled | `family-tally-v2-run.sh:73-148`; `family_tally_v2.py:158` and its L-28 note; PREREG v3 §9 |
| R-3 | Does the operator still want any stopped study re-run on demand (K1, offer-gate, M_A/M_B)? | OPERATOR | keep the timers disabled and run by hand / re-enable one | the §2 A/B/C citations |

### D-1 — exact reversible procedures (owner OPERATOR; run before **16:30Z** for margin)

**Option (a) — shadow the first afternoon.** Mechanism is a **drop-in**, never an edit of the repo
unit (an edit turns `test_trade_supervisor_phase1_unit.py::test_installed_unit_pins_the_phase0_shadow_flag_off_after_operator_env`
RED, because that module reads `deploy/systemd/breezy-trade-supervisor.service`, `:20-21`):

1. `mkdir -p ~/.config/systemd/user/breezy-trade-supervisor.service.d`
2. `printf '[Service]\nEnvironment=BREEZY_CRH_CONT_PHASE0_SHADOW=1\n' > ~/.config/systemd/user/breezy-trade-supervisor.service.d/10-phase0-shadow.conf`
3. `systemctl --user daemon-reload`
4. **verify (leaks nothing):** `systemctl --user show breezy-trade-supervisor.service -p Environment | tr ' ' '\n' | grep -c '^BREEZY_CRH_CONT_PHASE0_SHADOW=1$'` → expect `1`. (Verified today that this command prints **no** operator-reserved value: the two caps arrive via `EnvironmentFile=` and the same probe for them returns `0`.)
5. `systemctl --user restart breezy-trade-supervisor.service` — **the supervisor's env is fixed for its lifetime** (unit `:48-52`), so a restart is the only way to apply it. `KillMode=process` (`:144`) means this does **not** kill node pid 8453; the `Found left-over process … Ignoring` line is the expected confirmation.
6. **verify the node survived:** `ps -o pid=,etimes= -p 8453` still returns a row.
7. **after 16:50Z:** `NEW=$(pgrep -f '/breezy-trade$' | grep -vx 8453)`; `grep -ac 'BREEZY_CRH_CONT_PHASE0_SHADOW=1' /proc/$NEW/environ` → expect `1`.
8. **expected node behaviour:** with only `BREEZY_CONTINUOUS_RUNG_HOLD=1` set, `phase1_family_permits(current_rung_hold=False, continuous_rung_hold=True, permit=P, phase0_shadow=True)` returns `(None, None)` (`composition.py:243-256`) → v3 holds **no** permit → `phase0_permit_guard=v3_permit is None` is True with `permit=None` (`app/trade.py:238`), so `Phase0PermitForbiddenError` (`continuous_strategy.py:191-192`) does **not** raise. Node log: hunts, zero submits, **no** `Phase0PermitForbiddenError`.
9. **17:05Z self-check:** (a) `phase0_clean` PASSes (no marker). (b) `startup_evidence_valid` is written by the **exec client** startup path (`exec/client.py:371` `STARTUP_EVIDENCE_KEY`), which shadow does not disable — EXPECTED PASS, **UNVERIFIED by observation**. (c) `family_not_halted` unaffected.
10. **rollback:** `rm ~/.config/systemd/user/breezy-trade-supervisor.service.d/10-phase0-shadow.conf && rmdir ~/.config/systemd/user/breezy-trade-supervisor.service.d && systemctl --user daemon-reload && systemctl --user restart breezy-trade-supervisor.service`. **Granularity is one trading day:** reverting *after* 16:50Z does not change today's node (its env is fixed at spawn) — it takes effect at tomorrow's 16:50Z launch. Repo diff: **none**; the phase-1 unit tests stay green either way.

**Option (b) — go live as-is.** Take **no action**: the unit already pins
`BREEZY_CRH_CONT_PHASE0_SHADOW=0` (`:112`) and `BREEZY_CONTINUOUS_RUNG_HOLD=1` (`:109`). Today's
bound on exposure: at most **4 stations × 1 position × the per-position cap** (value
operator-reserved, never printed here), enforced by the native `RiskEngine.max_notional_per_order`
per slug with `bypass=False` (`node_config.py:565-622`) and the 8-gate `_submit_order` chokepoint
(`exec/client.py:2647-2716`); the **trial-day latch is durable** and halts the family on the 2nd
genuine fill with a no-await veto (`trial_day_latch.py:469-527`; `exec/client.py:2679-2691`); the
**spend ledger is process-local but re-seeded at boot from durable fills**
(`operator_controls.py:307-333`; `exec/client.py:2214-2268`), while AMBIGUOUS/no-fill spend remains
process-local. Carried risks: audit **B3**
(v3 has never been fill-replayed), **B2** (the next fill is likely residual again), **B4** (no alert
reaches a human; `health.py:495-511` resolves every CRITICAL to the logging sink). **Rollback after
a fill: none** — a fill is not reversible; the family halt is the only stop.

**Recording (either option).** One line in `docs/core/PROGRESS.md`: option chosen, UTC timestamp,
who decided, and the verification output from step 4/7 (or, for (b), the 16:50Z node log's permit
line). Not written by this plan.

## 9. Citations — verified against the working tree / live host today (2026-09-12)

VERIFIED by direct read or command: every `deploy/systemd/*` line cited; `systemctl --user
list-timers/list-units/list-unit-files/show` output; the symlink map of `~/.config/systemd/user`;
`journalctl --user` lines for k1 (09-11 22:32:08), ingest (09-12 12:31:33, 15:15:11–15:15:32,
`Finished` at every tick 11:31→15:01), and `Found left-over process 3196952` (09-12 01:24:03,
01:37:20); `quote_tape_ingest_cli.py:766-805, 826-833, 1005-1133, 1305-1348`;
`trade_supervisor.py:344-392, 696-737`; `trade_supervisor_core.py:78-83, 205-292`;
`order_enablement.py:154-243`; `composition.py:225-257, 426-443`; `app/trade.py:185-200, 238`;
`settings.py:119, 327-328, 765-772, 813-856`; `family_manifest.py:53-194`;
`family_tally_v2.py:72-116, 144-158, 187-225`; `score_live_trials.py:326-465, 1544-1626`;
`deploy/families/{pm_us_crh_v2,pm_us_crh_cont}.json`; `structural_dead_stop.py:17,176`;
`tests/unit/{test_deploy_timer_hours,test_analysis_units_memory_capped,test_trade_supervisor_phase1_unit}.py`;
`man systemd.unit` `Conflicts=` and `Before=,After=` on this host (systemd 259); Nautilus greps with
the `class TradingNode` positive control; `MemTotal 32163492 kB`, `SwapTotal 8388604 kB`;
`systemd-oomd` **inactive**; node pid 8453 and supervisor pid 4061490 both alive at 15:20Z.

UNVERIFIED / assumption, marked as such: **(U1)** the sender of the 09-11 22:32:08 `SIGTERM` to
`breezy-k1-daily` — `systemd-oomd` is inactive and a cgroup OOM would be `SIGKILL`, so it was an
external `SIGTERM` (hand or agent); the *memory pressure* is measured, the *sender* is not.
**(U2)** whether a shadow-mode node still writes a valid startup-evidence record (D-1 step 9b) —
reasoned from `exec/client.py:371` being on the exec-client path, not observed. **(U3)** the
non-disjoint-interval **root cause** (republished/overlapping recorder output vs catalog state) —
only the refusal and its exact intervals are measured. **(U4)** that a `Environment=` drop-in
overrides the main unit's same-variable assignment — asserted from systemd semantics and made safe
by the step-4 `grep -c` verification *before* the restart. **(U5)** `mb-daily`'s 11.6 GB (09-11) vs
3.2 GB (09-12) spread — cause not investigated; the serialization design assumes the larger.
**(U6)** audit line "quote-tape-ingest fails every run" — **corrected**: the *unit* succeeds on
every run (exit 0); it is the per-type conversion that fails and is swallowed (§2 H).
