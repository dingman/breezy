# P2-DEL impact check r1 (2026-10-22) — RULING: keep FQ v1 dormant behind the orders-off drop-in; no deletion

Author: Grok Build (read-only), coordinator-accepted. Trigger: P2 FAIL (`docs/evidence/P2_NBP_VS_ASK_MURPHY_2026-10-22.md`); r2.1 item 3 requires a FAIL to get its own reviewed impact check. This is that check.

## Recommendation

Do not delete `pm_us_crh_fq_v1`. Leave the taker dormant behind the orders-off drop-in that is already installed. Deletion is the larger change and it breaks the supervisor's stop and self-check. The pre-registered FAIL already owes a reviewed impact check, and this check is that change: no source edit, no manifest edit, no pin edit, no restart.

P2 failed on its own rule and deleted nothing. YES taker P&L was 150 takes, sum −7.92 USD, mean −0.0528 per take, wider 95% interval [−0.09066, −0.00768] (`docs/evidence/P2_NBP_VS_ASK_MURPHY_2026-10-22.md:66–94`). The live audit falsified the same taker: 34 fills, 4 wins, −2.63 (`docs/evidence/AUDIT_independent_2026-10-22.md:16–17`). r2.1 dropped the candidate delete list and said a FAIL is its own reviewed change (`docs/plans/backlog/AUDIT_PATH_2026-10-22/P2_plan_r2.md:117–120`). `docs/core/PROGRESS.md:54` records that debt. The binding floor is the simplest change (`PROGRESS.md:46–49`).

## GOAL STATE

The live node still boots family `pm_us_crh_fq_v1`, still subscribes, still holds the intent lock, and still cannot send, because `fq-v1-halt-orders-off.conf` forces `BREEZY_ORDERS_ENABLED=0`. Maker keepers, the calibration JSON, the FQ manifest, Nautilus, `allow_short`, the operator caps, the permit, and the enablement allowlist are unchanged.

## WALK

Checked against HEAD `b1d4ea02` on `feat/data-capture-and-risk`. `arm/integration` `c614fb0b` is not an ancestor of HEAD (`PROGRESS.md:36` says the same).

1. The unit requests orders and names this one family: `BREEZY_ORDERS_ENABLED=1` and `BREEZY_SENDING_FAMILY_ID=pm_us_crh_fq_v1` (`deploy/systemd/breezy-trade-supervisor.service:121`, `:128`). Cardinality is one. There is no second configured family to fall back to.
2. The installed drop-in overrides only the orders bit. On disk it is comments plus `[Service]` / `Environment=BREEZY_ORDERS_ENABLED=0` (`~/.config/systemd/user/breezy-trade-supervisor.service.d/fq-v1-halt-orders-off.conf:6–7`). It does not clear the family id. Its allowlist row permits exactly those two directives (`src/breezy/runtime/health_dropins.py:46–57`). A blank `Environment=BREEZY_SENDING_FAMILY_ID=` is not an unset: a blank value is `SettingsError` (`src/breezy/runtime/settings.py:348–350`). `UnsetEnvironment=` would be a new directive and would fail that allowlist.
3. With the family still set, boot loads `deploy/families/pm_us_crh_fq_v1.json` (status `REGISTERED`, `terminal_climate_day` `2026-10-05`, density artefact sha `9c0b6d6e…`, `:6–19`) and dispatches `forecast_quantile_ladder` (`src/breezy/app/trade.py:956–963`). That path opens the submit-intent latch (`trade.py:1134–1136` → `_open_exec_latch` `:981–994` → `open_submit_intent_latch`). The lock file is `<store>.intent.lock` (`src/breezy/runtime/trade_supervisor.py:351–354`, `src/breezy/runtime/submit_intent.py:1339–1341`).
4. Because orders are not requested, `main` logs `order submission permit not minted: orders not requested` and does not mint (`trade.py:1391–1397`). That string is `PERMIT_NOT_REQUESTED_MARKER` (`trade_supervisor_core.py:155`). `derive_self_check_facts` latches it (`:2097`, `:2110–2111`, `:2141`). `self_check` returns `PASS_ORDERS_NOT_REQUESTED` only after the child is alive, the tracked pid holds the flock, and the strategy subscribed (`:752–761`, then `:780–781` via `orders_expected_off` `:785–791`). The subscribe marker is `ForecastQuantileLadderStrategy subscribed` (`:164–168`).
5. At 16:40Z `decide_stop_prior_action` SIGTERMs only when the discovered pid equals the lock holder (`trade_supervisor_core.py:37`, `:569–583`). The current node can be that holder. Launch is 16:50Z, self-check 17:05Z, launch window ends 17:00Z (`:38–44`).
6. Quote tape, NWS ingest, quote-tape ingest, and `us-source-collector@` do not name this family (no match in those four unit files). Tape `ExecStart` is `breezy-quote-tape` (`deploy/systemd/breezy-quote-tape.service:114`). NWS `ExecStart` is `breezy` (`breezy-nws-ingest.service:14`). `settings.py:105` says the tape recorder never reads `BREEZY_SENDING_FAMILY_ID`. Removing the trade family would not stop them. It is the trade node that breaks, which is why this walk does not remove it.
7. P4's imports keep resolving. No file in this walk is deleted. No restart. The 16:40Z stop and 16:50Z launch are left on the schedule they already have.

### Why the three deletion-shaped alternatives lose

**Unset the family and leave the code.** Unset (not blank) is a legal no-family boot: `settings.py:345–347` returns `None`, and `trade.py:1075–1087` logs `boot_family id=none …` and calls `trade_cli.run` with no strategies and no latch. The latch open at `:1136` is not reached, so this node does not hold `.intent.lock`. `decide_stop_prior_action` then cannot SIGTERM a discovered pid that is not the lock holder (`:579–583`): 16:40Z becomes `REFUSE_ALERT` or `NOOP`, not a stop. `self_check` returns `FAIL_NODE_NOT_READY` at `:756–757` (flock) or `:760–761` (no subscribe marker) and never reaches `PASS_ORDERS_NOT_REQUESTED`. The none-family log line is not the FQ subscribe marker (`:164–168`). Quote tape and the collectors keep running. The node is the thing that becomes unstoppable by the supervisor and red at 17:05Z.

**Delete the manifest and leave the unit's family id.** Settings load fails closed (`settings.py:366–388`). With the drop-in, `BREEZY_ORDERS_ENABLED` is not `1`, so `main` logs the "not minted" line and falls through (`trade.py:1361–1364`); `run` hits the same `SettingsError` and returns `EXIT_CONFIG_ERROR` (`:1071–1073`). A dead child is `FAIL_CHILD_EXITED` (`trade_supervisor_core.py:752–753`). If the drop-in were absent, the unit's `ORDERS=1` makes that failure exit 1 with `order submission permit not issued` (`trade.py:1342–1356`), which `classify_exit1_cause` treats as `DETERMINISTIC` (`trade_supervisor_core.py:647–648`). Either way the node is down, reconciliation of an open position stops, and `scripts/analysis/maker_stage0_model.py:33` plus `load_model` `:98–120` can no longer open the manifest. FQ has no exit seam (`KINDS_WITH_EXIT_PATH` is only `continuous_rung_hold`; the halt pin is cited below), so the venue still settles, but this is a daily boot failure rather than a deletion.

**Delete the r2 module list.** r2.1 withdrew that list (`P2_plan_r2.md:117–120`). Checked anyway, it is unsafe: `loss_stop_probe.py` and the manifest are maker inputs, and `forecast_quantile_ladder/__init__.py:10–33` imports the taker modules at package import, so deleting them breaks `from breezy.strategy.forecast_quantile_ladder.calibration_artefact import …` even if that file stays. The exact-set pins below would all have to move in a separately reviewed re-pin. Orders are already off, so the deletion removes no live send.

## Acceptance criteria

- No diff under `src/`, `tests/`, `deploy/families/`, or `deploy/systemd/`.
- The unit still has `Environment=BREEZY_SENDING_FAMILY_ID=pm_us_crh_fq_v1` (`breezy-trade-supervisor.service:128`) and `BREEZY_ORDERS_ENABLED=1` (`:121`).
- The drop-in file is still the two directives above, and `DROPIN_ALLOWLIST` is still the one row at `health_dropins.py:46–55` (sha `5ff0d6a1…`, ruling `RULING_FQ-v2-NO-TRADE_2026-10-08`, expiry `2026-12-31`). The sha of the live file was not recomputed in this pass.
- `operator.env` is not read or written. Caps stay the two operator controls (`PROGRESS.md:19–24`).
- The next 16:40Z stop still has a lock-holding node to SIGTERM, and the next 17:05Z self-check still has a subscribe marker to read. This plan does not itself restart anything, so those are properties of the running node, not of a new deploy.
- `arm/integration` (`c614fb0b`) still imports `calibration_artefact`, `loss_stop_probe`, and `persistent_latch`, because those files are untouched.

## File-by-file

Recommended change: none.

The r2 list (`P2_plan_r2.md:75–79`) was re-checked with codegraph on `projectPath=/home/jon/breezy`, grep over `src/`, `scripts/`, `tests/`, and `deploy/`, and `git grep` of `c614fb0b` plus maker-design `8de5ebd4`. Do not treat it as a delete set.

| Path | Verdict | Why it is not safe to delete |
|---|---|---|
| `src/breezy/strategy/forecast_quantile_ladder/calibration_artefact.py` | KEEP | HEAD `no_ladder_maker/pno_store.py:29–32`. On `c614fb0b`: `no_ladder_maker/composition.py:30`, `live_feed.py:30`, `pno_store.py:29`, `strategy.py:96`. Maker-design scripts `maker_design_nobid.py:53`, `maker_stage0_driver.py:44`, `maker_stage0_modes.py:26`, `maker_stage0_pno_store.py:34`, `maker_stage0_report.py:20`, `maker_stage0_station_loop.py:22`. |
| `persistent_latch.py` | KEEP | `analysis/labeling/attribution.py:44–46` on HEAD, on `c614fb0b`, and on maker-design. Constant `FORECAST_QUANTILE_TRIAL_KEY_PREFIX`, not the class. |
| `loss_stop_probe.py` | KEEP | r2 listed it. HEAD production importer is only `trade.py:791`. `c614fb0b` maker imports it: `no_ladder_maker/composition.py:31` (`FqComposedVeto`, `LossStopProbe`) and `harm_stop_artefact.py:20`. P4 is that branch (`PROGRESS.md:36`, `:56`). |
| `deploy/families/artefacts/nbp_calibration_pm_us_crh_fq_v1_2026-09-30.json` | KEEP | Manifest `:10–11` pins it. `c614fb0b:deploy/families/pm_us_no_maker_sharp_v1.json:9` points at the same file. Stage-0 and parity tests read it (`tests/strategy/no_ladder_maker/test_parity_vs_design_driver.py:79`). |
| `deploy/families/pm_us_crh_fq_v1.json` | KEEP | r2 listed it. `maker_stage0_model.py:33` and `load_model` `:98–120` open it and check the sha. The live unit names this id (`service:128`). Deleting it is the boot failure above. |
| `deploy/families/artefacts/not_applicable_boundary.json` | KEEP | Manifest `:7`. Not taker-only. |
| `__init__.py` | KEEP as-is | `:10–33` imports bounds, calibration, config, decision, latch, margin, strategy. Any later taker deletion has to rewrite this first or the keeper import dies at package init. |
| `decision.py`, `strategy.py`, `composition.py`, `plugin.py`, `capture_adapter.py`, `decision_funnel.py`, `latch.py`, `margin.py`, `config.py`, `bounds.py`, `artefact_bounds.py` | Dormant, not deleted | No `no_ladder_maker` import of these on `c614fb0b`. They are still imported by `trade.py:114–129`, by the package `__init__`, by each other, and by analysis scripts on maker-design (`fq_mc_livedata.py`, `fq_mc_type1.py`, `fq_resume_n_mc.py`, `fq_evaluate_shim.py`, `fq_loss_taxonomy_reconstruct.py`, `blend_veto_descriptive.py`, `nbp_shadow_parity.py`, `nbp_shadow_parity_pure.py`). `strategy.py:308` lazily imports `composition`. Deleting them is a script break plus the pin rewrite below, for no send reduction. |
| `src/breezy/app/trade.py` FQ wiring (`:114–129`, `:791`, `:956–963`) | KEEP | This is the live composition branch. The arm maker does not depend on it; the running node does. |
| `~/.config/systemd/user/.../fq-v1-halt-orders-off.conf` | DO NOT TOUCH | Removing it restores `BREEZY_ORDERS_ENABLED=1` from the unit (`service:121`). `PROGRESS.md:62` forbids hand-editing it. |
| `operator.env`, Nautilus, `allow_short`, permit mint, `live_orders_gate` allowlist | DO NOT TOUCH | Operator caps and enablement (`PROGRESS.md:19–24`, `:46–48`). |

`not_yet_calibrated_forecast_density.json` is a leftover sentinel. No py/json/sh filename citation turned up in the import pass. Leave it. It is not the density pin.

## Pins and contract tests

Recommended plan: no re-pin. Every row stays an equality.

If a later reviewed change deletes taker modules anyway, re-pin by replacing the exact set with the exact set minus the FQ element, in its own reviewed commit. Never turn `==` into `<=`, never skip a missing file, never delete the test to go green. Regen `closure_manifest.py` with `scripts/ci/regen_closure_manifest`; do not hand-edit it. Lines below are from the tests/ enumeration pass over each deleted-module path and the family id.

| Pin | Where | Re-pin only if deletion is forced |
|---|---|---|
| `_COMPOSITION_KINDS` | `test_composition_kind_exact_set_is_widened_by_exactly_one_row` `:47` | Drop `forecast_quantile_ladder` only. |
| `COMPOSITION_KIND_SUBSCRIBED_MARKERS` | `test_marker_map_is_widened_by_exactly_one_row` `:70`; `test_the_family_line_is_not_a_supervisor_readiness_marker` `:217`; `test_subscribe_marker_class_names` `:209` | Drop the one FQ key. `test_subscribe_marker_is_parsed_from_the_real_fq_strategy_log_line` `:219` imports `strategy.py` and fails collection; do not weaken the other three markers to avoid it. |
| `HALTABLE_COMPOSITION_KINDS` | `test_the_accepted_composition_kinds_are_pinned_exactly` `:188` | Drop FQ. Remainder `{continuous_rung_hold}`. |
| `KINDS_WITH_EXIT_PATH` | `test_kinds_with_exit_path_is_pinned_exactly_and_within_the_haltable_kinds` `:239` | Do not touch. It is `{continuous_rung_hold}` and does not name FQ. |
| `MODEL_CLASS_RE` | `test_model_class_kind_set_equals_composition_kinds` `:138` | Drop the FQ alternative in the same commit as `_COMPOSITION_KINDS`. The test only checks acceptance, so a leftover alternative stays green. Do not widen it. |
| `NODE_PLUGINS` / `OFFLINE_PLUGINS` | `test_family_plugin_exact_set` `:196` | Drop the FQ key on both. Do not delete `evaluators/forecast_quantile_ladder.py` (not in the r2 set; it is the offline evaluator). Do not swap `FqEvaluator` for `RefusingPlugin` as a shortcut. |
| `LIVE_GATE_ROUTED_KINDS` | `test_literal_identity_pins` `:119`; `test_every_live_kind_covers_required_detector_classes` `:85` | Would become empty. That is a registry edit, not a side effect of deleting `strategy.py`. Leave it under dormancy. |
| `BOOTSTRAP_SEED` | `test_literal_identity_pins` `:122`; `test_bootstrap_seed_is_one_champion_and_unique_ids` `:146` | The seed is `(pm_us_crh_fq_v1, CHAMPION)` plus three retired ids. Removing the pair with no new champion fails the one-champion test. Do not rewrite it as part of a code deletion. |
| `CLOSURE_MODULES["breezy.analysis.labeling.label_run"]` | `test_closure_manifest_equals_grimp_closure` `:689`; regen round-trip `:747` | Includes the package plus `artefact_bounds`, `bounds`, `calibration_artefact`, `composition`, `config`, `decision`, `decision_funnel`, `latch`, `margin`, `persistent_latch`, `strategy` (`closure_manifest.py:224–235`). Not `plugin`, `capture_adapter`, or `loss_stop_probe`. Rewrite `__init__.py` first, regen, drop only deleted names, keep the two keepers. |
| `PRODUCER_SOURCE_SHA256` | `test_code_identity_pins_cover_import_closure` `:599`; `test_aut2_label_is_pinned_to_its_own_closure` `:15` | Re-pin both hashes after a real regen. `closure_manifest.py` sits in the health closure too, so the health hash moves even though that tuple has no FQ module. |
| Closure component keys | `test_manifest_holds_only_the_reviewed_components_and_refuses_the_rest` `:90` | Do not touch. Keys are the health CLI and `label_run`. |
| `SEAM_ALLOWLIST` | `test_every_exemption_and_allowlist_row_is_reasoned_literal_and_live` `:66` / `:369` | One row is `forecast_quantile_ladder/composition.py` `_resolve`. Remove that row only when the file is gone. Keep the `promotion_criteria.py` row. `POLICY_BAN_EXEMPTIONS == ()` stays empty. |
| Loss-stop writer allowlist | `test_loss_stop_artefact_path_callers_in_closed_allowlist` `:48` / `:251` | Grandfathers `loss_stop_probe.py` and `app/trade.py`. Do not widen `_NEW_CALLERS` or `_WRITERS`. The arm maker adds callers; that is a P4 pin, not a deletion shortcut. |
| Autonomy unit carve-outs | `test_every_carve_out_is_live_and_documented` `:67` / `:245` | Two rows match `composition_kind=forecast_quantile_ladder` in `replay-daily-run.sh` and `score-live-trials-run.sh`. Leave the shell lines and the rows. |
| Replay / score / tally skip tests | `test_replay_daily_wrapper.py:148`; `test_score_live_trials_deploy.py:795`; `test_family_tally_v2_deploy.py:340` | Assert the FQ skip text for this family id. They fail if the manifest or the shell branch goes. |
| `_FQ_S5_NEW_MODULES` | `test_fq_live_orders_gate_touches_no_operator_control` `:800` | Four paths must have zero operator-control assignments, including `composition.py`. The same module imports `persistent_latch` (`:99`). Do not drop `trade.py` from the scan. |
| `_LIVE_ORDERS_ALLOWLIST` | `live_orders_gate.py` one tuple for `pm_us_crh_fq_v1` / `RULING_operator_fq_live_real_orders_2026-10-01`; sha pin test `:80` | Enablement. Strategy deletion does not fail it. Do not empty it under this plan. |
| Manifest registration tests | `test_fq_s8_registration_artefacts.py:81`; `test_pm_us_crh_fq_v1_is_registered_with_the_operator_ruling` / `test_pm_us_crh_fq_v1_loads_and_names_the_right_composition_kind` (`test_forecast_quantile_ladder_manifest_and_markers.py:95`, `:104`); `test_the_installed_unit_names_a_REGISTERED_family` (`test_trade_supervisor_phase1_unit.py:49`, `:68`); `test_v1_manifest_terminal_day_parses` (`test_set_family_halt_cli.py:1424`) | All require the json to exist and be `REGISTERED`. The artefact sha equality in the s8 file (`:48`) stays with the JSON. |
| Exec-client byte pin in that same manifest file | `test_exec_client_is_byte_identical_to_its_pre_sl13_sha256` `:117` | Global NO-SEND pin. Do not delete it with an FQ test. |
| `DROPIN_ALLOWLIST` | `test_the_shipped_row_is_pinned_to_the_ruling_and_its_expiry` `:116`. `test_unit_health.py:1464–1497` is a fixture copy. | Do not remove the row. Cardinality is one. |
| Exec import pin | `test_exec_import_pin_x1_is_superset_of_recorded_baseline` (`tests/contract/test_us_source_ingest_egress_guard.py:627`) and `BANNED_EXEC_TRANSPORT_MODULES` (`test_cage_rule_constants_are_pinned.py:386`) | Enumeration found no FQ module in that set. Do not touch. The difference assertion stays `==`. |
| `allow_short` | FQ-local `tests/strategy/forecast_quantile_ladder/test_config.py:43`. Global copies do not name this family. | Deleting the FQ test with `config.py` must not be paired with editing the global short ban. `allow_short` stays `False` (`PROGRESS.md:46`). |
| No-exit scan | `test_fq_has_no_exit_order_path` (`test_fq_loss_stop_probe.py:395`) | `offenders == []`. Do not weaken. It imports `loss_stop_probe`, which stays. |
| Forbidden-import scan | `test_forbidden_imports.py:27` | Scans every module in the package. It is the import pin on the keepers. Do not delete it with the taker suite. |
| `_EXIT_RULE_REGISTERED_FAMILIES` | exit-gate equality, `frozenset({"pm_us_crh_exit_v4"})` | Does not include this family. Do not add it and do not relax it. |
| `test_r2_2_citation_map.py` | `:34` | No FQ row. Nothing to re-pin. Import-linter contracts do not name this package. |
| `test_shadow_only_false_is_only_the_gate_output.py:201` | Incidental | Permitted path is `src/breezy/app/trade.py`. Does not fail if FQ `config.py` is deleted. Do not weaken the guard. |

`_REQUIRED_KINDS` in `src/breezy/analysis/labeling/unit_factory_default.py:135` includes `forecast_quantile_ladder` and has no equality test, so a stale element would stay green. Under this plan it stays, which is correct: labeling still attributes this family.

Keeper tests that must not be swept up with `tests/strategy/forecast_quantile_ladder/`: `test_calibration_artefact.py`, `test_persistent_latch.py`, `test_forbidden_imports.py`, `test_parity_vs_design_driver.py:48`, `test_aut2_attribution.py:46`, `test_te1_label_wiring.py:87`, `tests/support/te1_fixtures.py:37`, `test_family_halt_cli_fq.py:36`, `test_set_family_halt_cli.py:1436`, `test_operator_caps_through_the_live_composition.py:99`. `test_ct12_fq_halt_through_run.py:37` also imports `decision` and `strategy`; it is a halt-through-`run` test, not an exact-set pin, and it stays while those modules stay.

## Deployment and activation

No restart. No `daemon-reload`. No drop-in edit. The node that is up keeps running. The supervisor's next 16:40Z `STOP_PRIOR` and 16:50Z `LAUNCH` are unchanged (`trade_supervisor_core.py:37–38`).

The 10 minutes between 16:40Z and 16:50Z are not a safe supervisor-restart window. The documented window is [01:00Z, 16:40Z), at or after 01:00:00Z and strictly before 16:40:00Z (`deploy/systemd/README.md:1389–1395`). `KillMode=process` (`breezy-trade-supervisor.service:163`) means a supervisor restart does not SIGTERM the node. An `ExecStopPost` reaper was rejected for that reason (`README.md:1379–1385`). Scheduler state is in memory, so a restart at or after 16:40Z can re-fire launch while a node still holds the lock.

If someone later lands a real code change despite this recommendation: restart the supervisor only inside [01:00Z, 16:40Z), leave the current node up through that restart, let 16:40Z SIGTERM the lock holder, and let 16:50Z spawn the new code. Do not remove the drop-in in that same window. Collector timers are their own calendars and are not stopped by a trade-family edit.

`deploy/systemd/README.md:1404–1409` still says the 17:05Z check reports `FAIL_SHADOW_MODE_NO_PERMIT` because `derive_self_check_facts` ignores `orders_not_requested_seen`, and it calls that expected. The source on this tree does latch the marker and can return `PASS_ORDERS_NOT_REQUESTED` (`trade_supervisor_core.py:2097–2141`, `:780–781`). The README paragraph is stale relative to that source. This plan does not "fix" the README, because no doc edit was asked and a doc-only correction would still be a commit. A live journal was not read, so this plan does not claim what the running process printed at the last 17:05Z.

## Test strategy

This plan has no diff, so `scripts/ci/run_tests_no_egress.sh` is not run and is not evidence for the no-change decision. The evidence is the import graph and the boot/stop lines above.

If a later change deletes or re-pins anything, the evidence is that script on the primary tree, not a worktree, and it is necessary but not sufficient. Also required before that commit:

- The re-pin is a separate reviewed commit from the deletion, equalities preserved as in the table.
- Collection of the keeper tests listed above still passes. A deleted `tests/strategy/forecast_quantile_ladder/` tree must not take `test_calibration_artefact.py`, `test_persistent_latch.py`, or `test_forbidden_imports.py` with it.
- No test is weakened to green. A red exact-set pin means the re-pin commit has not landed, not that the assertion should become a subset.
- Nautilus, `allow_short`, `operator.env`, the drop-in bytes, and the exec-client sha pin are absent from the diff.

## Risk register

| Risk | What happens | Why dormancy is the control |
|---|---|---|
| 16:40Z cannot stop the node | Zero-family boot never takes `.intent.lock` (`trade.py:1075–1087` returns before `:1136`). Stop requires pid equality (`trade_supervisor_core.py:569–583`). | The live FQ node still takes the lock. |
| 17:05Z pages `FAIL_NODE_NOT_READY` | No flock or no subscribe marker fails before the orders-off pass (`:756–761` vs `:780`). | Subscribed + orders off can reach `PASS_ORDERS_NOT_REQUESTED`. |
| Orders come back on | Deleting or hand-editing the drop-in restores unit `ORDERS=1` (`service:121`). Allowlist expiry `2026-12-31` is already a calendar item (`PROGRESS.md:62`, `health_dropins.py:53`). | Drop-in bytes stay. Renewal stays a separate reviewed row. |
| P4 cannot import calibration or the loss-stop probe | `__init__.py:10–33` plus `c614fb0b` `composition.py:30–31`. | Those files stay. |
| Stage-0 model refuses | `maker_stage0_model.py:98–120` needs the manifest and the sha. | Both stay. |
| Blank family id looks like "no family" | `Environment=VAR=` is empty, and empty is `SettingsError` (`settings.py:348–350`), and it is not an allowlisted directive (`health_dropins.py:57`). | The variable stays set to `pm_us_crh_fq_v1`. |
| Settings failure while orders are really 1 | Exit 1, deterministic, no relaunch that day (`trade.py:1342–1356`, `trade_supervisor_core.py:647–648`). | The drop-in keeps the process environment at 0, so this branch is not taken. |
| Open position stops being reconciled | A manifest deletion exits the node (`trade.py:1071–1073`). FQ has no exit path, so the process was never the settlement engine. | The node stays up. |
| Quote tape or collectors stop | They would not. No family id in those units. Called out so a later plan does not add a fake dependency. | Untouched. |
| README and code disagree on 17:05Z | Stale paragraph at `README.md:1404–1409`. | No operational change. Do not "repair" self-check behavior while orders are off. |

## Confidence

High that dormancy is the simplest correct close of P2-DEL. The send is already off, the stop contract needs the subscribed lock-holding node, and the maker branch imports files the r2 list would delete. That is enough to refuse the deletion without a remaining product choice.

Explicit unknowns:

- The running process was not inspected. HEAD is `b1d4ea02`; whether the live interpreter is that commit was not checked. The drop-in file was read this turn; its sha was not recomputed against `health_dropins.py:51`.
- No live journal line was read. Source can return `PASS_ORDERS_NOT_REQUESTED`. `README.md:1404–1409` says the opposite. Which string the last 17:05Z printed is unverified.
- `terminal_climate_day` `2026-10-05` (`pm_us_crh_fq_v1.json:6`) was not traced through strategy subscribe. Do not treat it as a send-stop. The drop-in is the send-stop.
- How the supervisor fills `discovered_node_pid` for a child that never took the lock was not re-read. The stop function itself cannot SIGTERM unless that pid equals the lock holder (`:569–583`). The zero-family path never becomes the lock holder.
- Supervisor handling of a child exit 2, beyond `FAIL_CHILD_EXITED` when the child is dead (`:752–753`), was not re-traced. The deterministic no-relaunch claim is for exit 1 plus `PERMIT_NOT_ISSUED_MARKER` (`:647–648`).
- `trade_cli.run`'s empty-strategy default was not re-read this turn. The cited fact is only the early return at `trade.py:1075–1087`, which passes no strategies and does not open the latch.
- The pin table's test line numbers come from one enumeration pass over `tests/`. The runtime lines in the walk were re-read. A line number inside a test file that this turn did not open can be off by a few lines; the test names and the exact sets are the part to trust.
- Maker-design codegraph could not be queried (readonly database). Its import list is `git grep` at `8de5ebd4`, not a graph. The arm result is `git grep` of commit `c614fb0b`, not a dirty worktree.
- `not_yet_calibrated_forecast_density.json` had no filename consumer in the searches that were run. A dynamic path build could still open it. Nothing in this plan removes it.

No files were written, no commit was made, and no service was restarted.


---

## Evidence gathered (verbatim)

The deletion plan has to be evidence-backed, so I am checking the repo state and splitting the work into three independent read-only passes: what the maker programme still imports, what the node does if that family is the only one configured, and which exact-set test pins name it. Nothing will be written or started.Repo is `feat/data-capture-and-risk` at `b1d4ea02`, and the P2 failure is already recorded. Next I am tracing the keeper imports, the boot path, and the test pins in parallel — still read-only.I'll trace what the supervisor and trading node do when `pm_us_crh_fq_v1` is the only configured family and is removed. Codegraph first, then the deploy files those hits point at.I'll verify external importers of the forecast-quantile-ladder taker path with codegraph first, then grep and the maker commit. Nothing will be written.I'll enumerate every pin that would break if `pm_us_crh_fq_v1` were deleted, starting from the P2 candidate set and codegraph, then verifying each hit in tests.Codegraph is available. Next I’ll query both graphs for callers of the ladder symbols, and pull the P2 candidate list plus literal import hits.Codegraph hit the autonomy registry and health I/O, not the FQ pins. I'll pull the P2 deletion list and search tests for each candidate path.Codegraph hit the wrong symbols on the first pass. I'll re-query the composition and supervisor entry points by name, then grep the family id and drop-ins.Main-repo codegraph returned a partial blast radius. The maker-worktree query failed; I’ll retry it once and tighten searches to external importers and the P2 deletion list.The first codegraph hits missed the composition branch. I'll grep the supervisor, `trade.py`, and the unit files for the empty-family and schedule paths.The drop-in allowlist names `fq-v1-halt-orders-off.conf`. Next I’ll regex-search tests and source for every candidate path and exact-set pin.Source pins name the family in closed sets. I’ll read those constants and the tests that assert them by equality.The r2 file list is still in the plan body, and a node with no family id does boot — but only if orders are not requested. I am checking that gate, the drop-in allowlist, and every importer outside the taker package.`arm/integration` is `c614fb0b` and is already checked out in another worktree. I’ll search that tree and the commit object without checking anything out.## Evidence: removing the only sending family (`pm_us_crh_fq_v1`)

There is no family list and no `BREEZY_FAMILIES`. One slot: `BREEZY_SENDING_FAMILY_ID`. Codegraph’s first passes missed this branch (they bound `missing` / `empty` elsewhere). The quotes below are from the files those later searches hit. Running systemd was not queried.

### 1. Node composition (`src/breezy/app/trade.py` + `settings.py`)

Unset → **run the node with no strategies** (not an immediate exit). Blank, multi-id, unknown id, or missing file → **`SettingsError`**, and `run()` returns **exit 2**. `main()` upgrades that to **exit 1** when orders were requested.

Unset is legal:

```335:347:src/breezy/runtime/settings.py
def _parse_sending_family_id(env: Mapping[str, str]) -> str | None:
    """Parse :data:`SENDING_FAMILY_ID_VAR`; ``None`` when unset (no sending
    family -- a legitimate shadow/tape-recorder/ingest-role boot).
    ...
    raw = env.get(SENDING_FAMILY_ID_VAR)
    if raw is None:
        return None
```

Blank is not the unset path. It raises:

```348:362:src/breezy/runtime/settings.py
    if not raw.strip():
        raise SettingsError(
            f"{SENDING_FAMILY_ID_VAR} must not be blank; unset it entirely for no sending family"
        )
    ...
    if "," in raw or any(ch.isspace() for ch in raw):
        raise SettingsError(
            f"{SENDING_FAMILY_ID_VAR} must name exactly ONE family id (cardinality-1); "
            f"was {raw!r}, which looks like more than one id"
        )
```

Unknown id, missing file, or `DRAFT_NOT_REGISTERED` refuse at settings load (exit 2 from `run()`, not a later crash):

```366:388:src/breezy/runtime/settings.py
    """Fail-closed manifest validation at settings-LOAD time (WP-11b):
    unknown id, missing file, or ``DRAFT_NOT_REGISTERED`` all refuse here
    (``SettingsError``, exit 2) ...
    manifest_path = _FAMILIES_DIR / f"{sending_family_id}.json"
    try:
        load_family_manifest(manifest_path)
    except FamilyManifestError as exc:
        raise SettingsError(...)
    except OSError as exc:
        raise SettingsError(
            f"{SENDING_FAMILY_ID_VAR}={sending_family_id!r}: manifest at "
            f"{manifest_path} could not be read: {exc}"
        ) from exc
```

`load_family_manifest` reads the file (`family_manifest.py:296` `path.read_bytes()`). A deleted `pm_us_crh_fq_v1.json` is that `OSError`. A `composition_kind` outside the four literals is `FamilyManifestValidationError` at `family_manifest.py:354-358`, which is a `FamilyManifestError`, so the same `SettingsError`. `forecast_ladder` is a legal kind but still refuses later:

```965:977:src/breezy/app/trade.py
    if manifest.composition_kind == "forecast_ladder":
        raise SettingsError(
            f"composition_kind=forecast_ladder ({settings.sending_family_id}) "
            "cannot boot yet: ForecastLadderStrategy is not implemented"
        )
    raise SettingsError(
        f"{settings.sending_family_id}: unknown composition_kind {manifest.composition_kind!r}"
    )
```

That second `raise` is unreachable for a file `load_family_manifest` already accepted. Both are caught and become exit 2:

```1237:1264:src/breezy/app/trade.py
    except (
        SettingsError,
        OSError,
        ...
        FamilyManifestError,
        ...
    ) as exc:
        _report(out, "configuration error", exc, expected=True)
        return EXIT_CONFIG_ERROR
```

`EXIT_CONFIG_ERROR = 2`, `EXIT_RUNTIME_ERROR = 1` (`trade_cli.py:130-132`).

Orders-on with no family also raises at load, before any node:

```879:890:src/breezy/runtime/settings.py
    if orders_enabled_requested and not (has_sending_family and live_observations):
        raise SettingsError(
            f"{ORDERS_ENABLED_VAR}=1 requires {LIVE_OBSERVATIONS_VAR}=1 and "
            f"{SENDING_FAMILY_ID_VAR} to be set: ..."
        )
```

`main()` then **returns 1 and never calls `run()`** if `BREEZY_ORDERS_ENABLED=1`:

```1338:1356:src/breezy/app/trade.py
    try:
        settings = load_trade_settings()
    except SettingsError as exc:
        settings = None
        if os.environ.get(ORDERS_ENABLED_VAR) == "1":
            _boot_logger.error(
                "order submission permit not issued: settings load failed (%s)",
                type(exc).__name__,
            )
            return EXIT_RUNTIME_ERROR
```

That log line contains `PERMIT_NOT_ISSUED_MARKER` (`"order submission permit not issued"`, `trade_supervisor_core.py:95`). If orders are not `1`, `main()` logs `"order submission permit not minted: settings load failed"` (`trade.py:1361-1363`) and falls through to `run()`, which returns **2**.

Zero-family branch (env unset, orders not requested): log the sentinel and call `trade_cli.run` with the default `strategies=()`:

```1075:1087:src/breezy/app/trade.py
    if settings.sending_family_id is None:
        _boot_logger.info(
            "boot_family id=none composition_kind=none status=none manifest_sha256=none"
        )
        return trade_cli.run(
            env=env,
            node_factory=node_factory,
            ...
            settings=settings,
        )
```

`trade_cli.run` still builds a node and calls `node.run()` (`trade_cli.py:712`). It does not refuse an empty strategy tuple (`trade_cli.py:656-658` only adds what it was given). `build_trade_node_config` always sets `strategies=[]` in the Nautilus config; strategies are added natively afterward (`trade_cli.py:576-581`). If `BREEZY_LIVE_OBSERVATIONS=1`, observation actors are still registered even with no family (`trade_cli.py:829-837`).

Tested: absent id → `None` (`tests/unit/test_runtime_settings.py:735-736`); comma → `SettingsError` (`tests/unit/test_wp11b_active_family_registry.py:56-63`); unknown id → `SettingsError` (`:71-80`); no-family boot logs the sentinel and `RecordingNode` returns `EXIT_OK` (`tests/unit/test_app_trade_boot_family_log.py:122-134`). No test hit for the blank-string sentence. The `EXIT_OK` test uses `RecordingNode`, not `TradingNode`.

### 2. Supervisor (`trade_supervisor_core.py` / `trade_supervisor.py`)

It does **not** look at family count. It does **not** refuse to start, and it does **not** restart-loop a config-failed node. It launches, the child dies, relaunch is declined, and the supervisor process stays up.

`main()` exits 2 only for a bad argv token, a missing exec-state DB, or the supervisor lock (`trade_supervisor.py:3099-3105`, `3115-3119`, `3156-3167`). No family check. The loop starts from an in-memory `initial_scheduler_state` (`trade_supervisor.py:3415`).

Launch decision is lock + open intent only:

```586:609:src/breezy/runtime/trade_supervisor_core.py
def decide_launch_action(...) -> LaunchAction:
    """[R6/B1] Launch only when the intent flock is free and no OPEN intent
    blocks ``arm`` ...
    if not lock_free:
        return LaunchAction.REFUSE_LOCK_HELD
    if open_intent_detected:
        ...
        return LaunchAction.REFUSE_INTENT_OPEN
    return LaunchAction.LAUNCH
```

Spawn forwards the supervisor environment unchanged (`trade_supervisor.py:1751-1753`, `spawn_node` at `1116-1135` `env=dict(env)`).

After the child exits, relaunch requires a **transient** cause (`trade_supervisor_core.py:683-684`). `"order submission permit not issued"` is **deterministic** (`:647-648`), so no relaunch. Exit 2 with only `"not minted: settings load failed"` matches none of the markers → `UNKNOWN` (`:659`) → also no relaunch (`trade_supervisor.py:1838-1847` `relaunch_declined`). While the child is still alive, relaunch does not fire (`:1835-1836`).

`sending_family_active()` is only “env is non-blank” (`trade_supervisor.py:772-782`). It arms the continuous-family **self-check** read (`:2975-2985`). It does not gate launch. With the id unset, that block is skipped.

A live zero-strategy node fails the 17:05 check **before** the orders-off pass, because nothing subscribed:

```760:761:src/breezy/runtime/trade_supervisor_core.py
    if not strategy_subscribed:
        return SelfCheckResult.FAIL_NODE_NOT_READY
```

`PASS_ORDERS_NOT_REQUESTED` is only reached after that (`:780-781`). Readiness also requires a subscribe marker (`:630-637`).

### 3. `deploy/families/` — what is configured

`pm_us_crh_fq_v1` is one JSON file, not yaml/conf: `deploy/families/pm_us_crh_fq_v1.json`.

```1:20:deploy/families/pm_us_crh_fq_v1.json
  "family_id": "pm_us_crh_fq_v1",
  ...
  "composition_kind": "forecast_quantile_ladder",
  ...
  "status": "REGISTERED",
```

Also on disk, not named by the live unit: `gs_boundary_pm_us_crh_v2.json`, `kalshi_crh_v1.json`, `pm_us_crh_cont.json`, `pm_us_crh_exit_v4.json`, `pm_us_crh_v2.json`, `pm_us_crh_v4.json`, plus `artefacts/` and `rulings/`. The unit enables exactly one id:

```120:131:deploy/systemd/breezy-trade-supervisor.service
Environment=BREEZY_TRADING_ENABLED=1
Environment=BREEZY_ORDERS_ENABLED=1
...
Environment=BREEZY_SENDING_FAMILY_ID=pm_us_crh_fq_v1
Environment=BREEZY_LIVE_OBSERVATIONS=1
```

`family_manifest.py:110-113` still says this manifest “stays `DRAFT_NOT_REGISTERED`”. The JSON says `REGISTERED`. The comment is stale.

### 4. Drop-ins

No `fq-v1-halt-orders-off.conf` under `deploy/systemd/`. The live file is `~/.config/systemd/user/breezy-trade-supervisor.service.d/fq-v1-halt-orders-off.conf` (read, not `systemctl`-shown):

```
[Service]
Environment=BREEZY_ORDERS_ENABLED=0
```

Allowlist pins that name and that directive only (`src/breezy/runtime/health_dropins.py:47-57`). It does not clear `BREEZY_SENDING_FAMILY_ID`.

Unit `ExecStart` (unchanged by the drop-in):

```139:139:deploy/systemd/breezy-trade-supervisor.service
ExecStart=/home/jon/breezy/.venv/bin/breezy-trade-supervisor breezy-trade-supervisor-daily
```

If the drop-in **and** `pm_us_crh_fq_v1.json` are removed, the unit still has `BREEZY_SENDING_FAMILY_ID=pm_us_crh_fq_v1` and `BREEZY_ORDERS_ENABLED=1`. The node then hits the missing-manifest `SettingsError` with orders requested → **`main()` returns 1** (`trade.py:1342-1356`). Supervisor classifies that log as deterministic and does not relaunch that day. Next trading day it will spawn once more (in-memory state resets). Not a tight loop: `Restart=always` is on the supervisor unit (`breezy-trade-supervisor.service:141`), with `RestartPreventExitStatus=2` (`:147`), and the node is not its own unit.

### 5. Quote tape and collectors — separate units

Not started by `breezy-trade-supervisor.service`.

| Unit | ExecStart | Tied to this family? |
|---|---|---|
| `deploy/systemd/breezy-quote-tape.service:114` | `.../breezy-quote-tape` | No. Own catalog env at `:93`. Comment at `:103` only notes the shared `polymarket.env`. |
| `deploy/systemd/breezy-quote-tape-ingest.service:87` | `breezy-quote-tape-ingest` | No family id. |
| `deploy/systemd/breezy-nws-ingest.service:14` | `.../breezy` | Separate ingest unit. |
| `deploy/systemd/us-source-collector@.service:37-38` | `flock` + `bwrap` around the collector | No trade-supervisor dependency in the unit header. |

`settings.py:105` says the tape recorder never reads `BREEZY_SENDING_FAMILY_ID`. Deleting the family file or the orders-off drop-in does not stop these units. `score-live-trials-run.sh:164-173` and `family-tally-v2-run.sh:71-80` only **skip** if that env var is absent on the supervisor unit; they are not the recorder.

### 6. What “boot with zero families” does

| Config | Process | Tested? |
|---|---|---|
| Env unset, orders not `1` | Logs `boot_family id=none ...`, builds the node, `node.run()` blocks until the node stops (`trade_cli.py:712`). Fake `RecordingNode` → exit 0. Not a raise. | Yes, against `RecordingNode` only (`test_app_trade_boot_family_log.py:122-134`). Real `TradingNode` stay-up is the `node.run()` call, not a separate test. |
| Env blank, or comma, or unknown/missing file | `SettingsError`. Exit **1** if `BREEZY_ORDERS_ENABLED=1`, else exit **2**. | Unknown id and comma: yes. Blank string: no test found. Missing-file exit code is the same `OSError` branch; not a dedicated “delete the live json” test. |
| Supervisor with that child | Spawns anyway. Does not relaunch a deterministic or unknown exit. Supervisor process keeps looping. | Relaunch rule is unit-tested as pure logic; no test found that deletes `pm_us_crh_fq_v1.json` and asserts the supervisor. |

Not a hang and not a supervisor restart-loop. A real zero-strategy node that stays up fails 17:05 as `FAIL_NODE_NOT_READY`.

### 7. 16:40Z stop and 16:50Z launch

Not a systemd timer and not cron. In-process UTC constants:

```37:44:src/breezy/runtime/trade_supervisor_core.py
STOP_PRIOR_UTC: Final[dt.time] = dt.time(16, 40)
LAUNCH_UTC: Final[dt.time] = dt.time(16, 50)
SELF_CHECK_UTC: Final[dt.time] = dt.time(17, 5)
RELAUNCH_CUTOFF_UTC: Final[dt.time] = dt.time(17, 0)
LAUNCH_WINDOW_END_UTC: Final[dt.time] = RELAUNCH_CUTOFF_UTC
```

Due-now branches: `trade_supervisor_core.py:1227-1231`. The unit comment repeats the same times (`breezy-trade-supervisor.service:6-11`). `STOP_PRIOR` SIGTERMs only a PID that matches the intent-lock holder; otherwise it no-ops or refuses (`trade_supervisor_core.py:569-583`).

Restart rule, from the deploy README, not from a timer:

```1389:1390:deploy/systemd/README.md
**Restriction unchanged: restart `breezy-trade-supervisor` only in
[01:00Z, 16:40Z) (at or after 01:00:00Z, strictly before 16:40:00Z).**
```

`KillMode=process` (`breezy-trade-supervisor.service:163`) means a supervisor restart does not SIGTERM the node. Scheduler state is in memory (`trade_supervisor.py:3415`), so a restart inside `[16:50Z, 17:00Z)` can fire `LAUNCH` again; if the node still holds the lock, launch adopts or refuses (`trade_supervisor.py:1686-1693`) rather than double-spawning. The documented safe window is still `[01:00Z, 16:40Z)`. Collector timers that skip 16:40 (`us-source-collector@*.timer.d/schedule.conf`) are their own calendars, not this schedule.

`deploy/systemd/README.md:1405-1409` still says the 17:05 check reports `FAIL_SHADOW_MODE_NO_PERMIT` while orders are off. The code now has `PASS_ORDERS_NOT_REQUESTED` (`trade_supervisor_core.py:740-781`). That README paragraph is stale relative to the code.## Evidence memo: forecast-quantile-ladder files imported outside the taker path

Read-only. No files written. Classification is evidence only, not a deletion plan.

### Method

- Codegraph `codegraph_explore` with `projectPath=/home/jon/breezy` succeeded (calibration / persistent-latch / package queries). It returned blast radius and partial caller names, then truncated. It did not list every importer. Grep plus file reads are the line evidence.
- Maker-design codegraph failed twice, same error both times: `Failed to call codegraph_explore: Error: Tool execution failed: attempt to write a readonly database. This is an internal codegraph error — retry the call once; if it persists, continue without codegraph for this task.` Fell back to ripgrep on that worktree.
- No shell tool was available, so `git grep`, `git show`, and `git branch -a --contains` were not run. Substitute: ref file `refs/heads/arm/integration` is exactly `c614fb0b98d5de301537208e40a58d9cbf57e594`. That branch is checked out at `/home/jon/breezy-arm-int` (`HEAD` = `ref: refs/heads/arm/integration`). Ripgrep was on that working tree. Dirty state was not checked. `design/maker-nobid-2026-10-21` (maker-design worktree) is a different commit: `8de5ebd42aecc1a46a1e7f4da761b19afaf02b24`.

"External" below means outside `src/breezy/strategy/forecast_quantile_ladder/`. Taker boot is `src/breezy/app/trade.py`. Maker production is `src/breezy/strategy/no_ladder_maker/`.

### P2 candidate list (verbatim from r2 body)

`docs/plans/backlog/AUDIT_PATH_2026-10-22/P2_plan_r2.md` lines 75–79:

- In `src/breezy/strategy/forecast_quantile_ladder/`: `decision.py`, `strategy.py`, `composition.py`, `plugin.py`, `capture_adapter.py`, `decision_funnel.py`, `latch.py`, `margin.py`, `loss_stop_probe.py`, `config.py`, `bounds.py`, `artefact_bounds.py`.
- **Keep** `calibration_artefact.py` (the maker's `pno_store.py` imports it) and `persistent_latch.py` (`analysis/labeling/attribution.py` imports it).
- The FQ wiring in `src/breezy/app/trade.py` (L114–129, L791, the `forecast_quantile_ladder` composition branch).
- `deploy/families/pm_us_crh_fq_v1.json`. Keep the artefact JSON, which the maker uses.
- The taker-only tests under `tests/strategy/forecast_quantile_ladder/`.

r2.1 (same file, lines 102–120) says those amendments override r2 on conflict, and item 3 drops "the deletion file list." The list above is the r2 text only. It is not an active mandate in r2.1.

### Claims checked

| Claim | Result |
|---|---|
| `calibration_artefact.py` imported by `pno_store.py` | True on current tree and on `c614fb0b` worktree. False as a path in maker-design: `src/breezy/strategy/no_ladder_maker/` does not exist there. |
| `persistent_latch.py` imported by `analysis/labeling/attribution.py` | True. The import is the constant `FORECAST_QUANTILE_TRIAL_KEY_PREFIX`, not the class. Codegraph's `PersistentQuantileLadderLatch` blast radius did not name this file. |
| Calibration artefact JSON must stay | Maker code reads `deploy/families/artefacts/nbp_calibration_pm_us_crh_fq_v1_2026-09-30.json` via the FQ manifest and via a test constant. |

Current `pno_store.py`:

```29:32:src/breezy/strategy/no_ladder_maker/pno_store.py
from breezy.strategy.forecast_quantile_ladder.calibration_artefact import (
    CalibrationArtefactUnknownVersionError,
    LiveCalibration,
)
```

Current `attribution.py` (same import on maker-design lines 44–46 and on the arm worktree lines 44–46; used at `fq_trial_id` line 210):

```44:46:src/breezy/analysis/labeling/attribution.py
from breezy.strategy.forecast_quantile_ladder.persistent_latch import (
    FORECAST_QUANTILE_TRIAL_KEY_PREFIX,
)
```

`calibration_artefact.py` does not import any sibling in this package. Its imports are `ladder_ev.location_correction` and `ladder_ev.quantile_density`. `loss_stop_probe.py` has no `forecast_quantile_ladder.` reference. `persistent_latch.py` imports `current_rung_hold.trial_day_latch`, not other FQ modules.

### Per-module external importers (current `/home/jon/breezy`)

Production `src` imports outside the package, from a complete ripgrep of `from breezy.strategy.forecast_quantile_ladder` / `import breezy.strategy.forecast_quantile_ladder` under `src` (37 lines, not truncated):

| Module | Outside the package | Maker or non-taker production |
|---|---|---|
| `calibration_artefact.py` | `no_ladder_maker/pno_store.py:29`; `app/trade.py:114` (`CalibrationArtefactPinMismatchError`); maker scripts and `tests/strategy/no_ladder_maker/test_parity_vs_design_driver.py:48`; `tests/unit/test_maker_stage0_pno.py:27` | Yes. Maker. |
| `persistent_latch.py` | `analysis/labeling/attribution.py:44`; `app/trade.py:125` (`FORECAST_QUANTILE_TRIAL_KEY_PREFIX`, `PersistentQuantileLadderLatch`) | Yes. Labeling, not maker. |
| `loss_stop_probe.py` | `app/trade.py:791` only in production src (`from breezy.strategy.forecast_quantile_ladder import loss_stop_probe as fq_bridge`). Also `tests/contract/test_fq_loss_stop_writer_allowlist.py:28`, `tests/support/fq_loss_stop_artefact.py:14`, `tests/unit/test_fq_loss_stop_probe.py:29`, `tests/unit/test_app_trade_fq_loss_stop_wiring.py:27` | No maker import on this tree. |
| `composition.py` | `app/trade.py:117` only in production src | No. |
| `decision_funnel.py` | `app/trade.py:121` only in production src. `scripts/analysis/decision_funnel_daily_digest.py` has no import (string/comment only). | No. |
| `strategy.py` | `app/trade.py:129` only in production src | No. |
| `decision.py`, `latch.py`, `margin.py`, `bounds.py`, `config.py`, `artefact_bounds.py` | No production src outside the package. Script and test imports only (below). | No. |
| `plugin.py`, `capture_adapter.py` | No production src outside the package. Tests only. | No. |
| `__init__.py` | Not imported by maker. `trade.py:791` imports the package to load `loss_stop_probe`. | No direct maker import. |

`__init__.py` lines 10–33 import `bounds`, `calibration_artefact`, `config`, `decision`, `latch`, `margin`, and `strategy` at package import time. Any `from breezy.strategy.forecast_quantile_ladder.<submodule> import ...` runs that. `strategy.py:308` has a function-local `from breezy.strategy.forecast_quantile_ladder.composition import _d_plus_1_climate_days`. `composition.py:38–43` then imports `artefact_bounds`, `calibration_artefact`, `config`, `decision_funnel`, `persistent_latch`, and `strategy`.

Codegraph (current tree): `load_live_calibration` callers include `scripts/analysis/nbp_shadow_parity.py`, `composition.py`, `scripts/analysis/fq_loss_taxonomy_reconstruct.py`, `scripts/analysis/maker_stage0_driver.py`. `LiveCalibration` callers include those plus `decision.py`, `strategy.py`, `scripts/analysis/maker_stage0_pno_store.py`. `PersistentQuantileLadderLatch`: `app/trade.py` and tests. `SupportsQuantileLatch`: `composition.py` and `strategy.py` only.

Maker scripts on the current tree import only `calibration_artefact` (quoted lines):

- `scripts/analysis/maker_design_nobid.py:53` `load_live_calibration`
- `scripts/analysis/maker_parity_fixture_extract.py:36` `LiveCalibration`, `load_live_calibration`
- `scripts/analysis/maker_stage0_modes.py:26` `LiveCalibration`
- `scripts/analysis/maker_stage0_driver.py:44` `LiveCalibration`, `load_live_calibration`
- `scripts/analysis/maker_stage0_pno_store.py:34` `CalibrationArtefactUnknownVersionError`, `LiveCalibration`
- `scripts/analysis/maker_stage0_report.py:20` `LiveCalibration`
- `scripts/analysis/maker_stage0_station_loop.py:22` `LiveCalibration`

FQ analysis scripts (not maker) import other modules: `fq_mc_livedata.py:30–35`, `fq_mc_type1.py:25–26`, `fq_resume_n_mc.py:57–58`, `fq_evaluate_shim.py:19–22`, `fq_loss_taxonomy_reconstruct.py:42,124–125,254–261`, `blend_veto_descriptive.py:47–48`, `p2_nbp_ask_murphy.py:283–297`, `nbp_shadow_parity.py:69–78` (`bounds`, `artefact_bounds`, `calibration_artefact`, `config`, `latch`, `strategy`), `nbp_shadow_parity_pure.py:46–47` (`bounds`, `latch`).

Non-package tests that import FQ modules but are not under `tests/strategy/forecast_quantile_ladder/` include labeling/halt/capture/boot tests (`test_aut2_attribution.py:46`, `test_te1_label_wiring.py:87`, `tests/support/te1_fixtures.py:37`, `test_family_halt_cli_fq.py:36`, `test_set_family_halt_cli.py:1436`, `test_ct12_fq_halt_through_run.py:36`, `test_operator_caps_through_the_live_composition.py:99`, `tests/support/capture_audit_recon_fixtures.py:40`, `test_capture_audit_recon_legs.py:41`, `test_autonomy_node_detectors.py:198`, `tests/unit/autonomy/pending_wp7_capture_guard_subclass.py:15`, `tests/support/te2_cli_fixtures.py:22`). Those are FQ or labeling tests, not `no_ladder_maker` production.

`closure_manifest.py` is a generated string list, key `breezy.analysis.labeling.label_run` (line 11). Lines 224–235 name the package plus `artefact_bounds`, `bounds`, `calibration_artefact`, `composition`, `config`, `decision`, `decision_funnel`, `latch`, `margin`, `persistent_latch`, `strategy`. They do not name `plugin`, `capture_adapter`, or `loss_stop_probe`. That matches package-`__init__` plus `strategy`'s lazy `composition` import being in `label_run`'s static closure via `attribution` → `persistent_latch`.

`live_orders_gate.py:83` is the string `"pm_us_crh_fq_v1"`, not a module import. `deploy/systemd/breezy-trade-supervisor.service:128` sets `BREEZY_SENDING_FAMILY_ID=pm_us_crh_fq_v1`.

### Maker-design worktree (`8de5ebd`, not `c614fb0b`)

- `src/breezy/strategy/no_ladder_maker/` is absent. No `pno_store.py` there.
- Same maker scripts import `calibration_artefact` at the same lines as current (`maker_design_nobid.py:53`, `maker_stage0_driver.py:44`, `maker_stage0_pno_store.py:34`, and the other `maker_stage0_*` lines above).
- `attribution.py:44–46` imports `FORECAST_QUANTILE_TRIAL_KEY_PREFIX`.
- `app/trade.py:114–129` and `:791` match the current taker wiring. No `no_ladder_maker` import of `loss_stop_probe`.
- FQ analysis scripts still import `decision`, `latch`, `margin`, `bounds`, `artefact_bounds`, `config`, `strategy` (same files as current).

### `c614fb0b` / `arm/integration` worktree `/home/jon/breezy-arm-int`

Not a `git grep` of the commit object. Working-tree ripgrep. Branch tip equals that commit.

Maker production imports that are not on the current tree:

```30:31:/home/jon/breezy-arm-int/src/breezy/strategy/no_ladder_maker/composition.py
from breezy.strategy.forecast_quantile_ladder.calibration_artefact import load_live_calibration
from breezy.strategy.forecast_quantile_ladder.loss_stop_probe import FqComposedVeto, LossStopProbe
```

```20:20:/home/jon/breezy-arm-int/src/breezy/strategy/no_ladder_maker/harm_stop_artefact.py
from breezy.strategy.forecast_quantile_ladder.loss_stop_probe import SCHEMA, compute_digest
```

```30:30:/home/jon/breezy-arm-int/src/breezy/strategy/no_ladder_maker/live_feed.py
from breezy.strategy.forecast_quantile_ladder.calibration_artefact import LiveCalibration
```

```29:32:/home/jon/breezy-arm-int/src/breezy/strategy/no_ladder_maker/pno_store.py
from breezy.strategy.forecast_quantile_ladder.calibration_artefact import (
    CalibrationArtefactUnknownVersionError,
    LiveCalibration,
)
```

```96:96:/home/jon/breezy-arm-int/src/breezy/strategy/no_ladder_maker/strategy.py
from breezy.strategy.forecast_quantile_ladder.calibration_artefact import LiveCalibration
```

Also `app/trade.py:125` `from breezy.strategy.forecast_quantile_ladder.loss_stop_probe import LossStopProbeActor` (current tree does not have this top-level import) and `:801` the lazy `loss_stop_probe` import. `attribution.py:44` still imports `FORECAST_QUANTILE_TRIAL_KEY_PREFIX`.

Maker tests on that tree: `tests/strategy/no_ladder_maker/test_composition.py:14` and `:17`, `test_harm_stop_producer.py:28`, `maker_strategy_support.py:54`, `test_strategy_parity.py:35`, `test_parity_vs_design_driver.py:48`, `tests/unit/test_app_trade_no_ladder_maker.py:31`. Those import `calibration_artefact` and/or `loss_stop_probe` only.

No `no_ladder_maker` file on that tree imports `decision`, `strategy`, `composition` (the FQ one), `plugin`, `capture_adapter`, `decision_funnel`, `latch`, `margin`, `config`, `bounds`, `artefact_bounds`, or `persistent_latch`.

### Artefact JSON

- `deploy/families/pm_us_crh_fq_v1.json:10` `density_artefact_path` = `deploy/families/artefacts/nbp_calibration_pm_us_crh_fq_v1_2026-09-30.json`. Line 7 pins `deploy/families/artefacts/not_applicable_boundary.json`.
- `scripts/analysis/maker_stage0_model.py:33` `DEPLOY_MANIFEST_REL = "deploy/families/pm_us_crh_fq_v1.json"`. `load_model` (lines 98–118) reads that manifest and opens `density_artefact_path`, then checks `density_artefact_sha256`.
- `tests/strategy/no_ladder_maker/test_parity_vs_design_driver.py:78–81` sets `CALIBRATION` to that same artefact file and sha `9c0b6d6e66a587c1b4e14e5f95ff5cedb3c7195f62f8ad4238191fdd75923a5e`.
- `docs/evidence/maker/stage0_2026-10-16/pins.json:36` records that path.
- Filename `not_yet_calibrated_forecast_density.json`: no matches in `*.py`, `*.json`, `*.md`, `*.sh`. The file is on disk; its body mentions `forecast_quantile_ladder`. Nothing found cites the filename.

### KEEP vs DELETE-CANDIDATE

Rule used: KEEP if maker production, maker stage0 scripts, or non-taker production (`attribution.py`, `maker_stage0_model.load_model`) imports or opens it. `app/trade.py` FQ wiring and `tests/strategy/forecast_quantile_ladder/` do not force KEEP. `c614fb0b` counts because the question includes that ref.

| P2 item | Mark | Why |
|---|---|---|
| `calibration_artefact.py` | KEEP | P2 keep-claim holds. `pno_store.py:29` current and arm. Arm also `composition.py:30`, `live_feed.py:30`, `strategy.py:96`. Maker scripts above. |
| `persistent_latch.py` | KEEP | P2 keep-claim holds. `attribution.py:44` current, maker-design, and arm. Not imported by `no_ladder_maker`. |
| `loss_stop_probe.py` | KEEP | P2 lists it for deletion. On current HEAD the only production importer is taker `trade.py:791`. On `c614fb0b` maker imports it (`composition.py:31`, `harm_stop_artefact.py:20`). It does not import other FQ modules. |
| `decision.py` | DELETE-CANDIDATE | No maker or labeling import. External users are FQ scripts, FQ tests, capture-audit tests, and package `__init__.py` / `strategy.py`. |
| `strategy.py` | DELETE-CANDIDATE | Same. Production outside the package: `trade.py:129` and `nbp_shadow_parity.py:78` only. Loaded anyway if `__init__.py` stays as it is. |
| `composition.py` | DELETE-CANDIDATE | Production outside the package: `trade.py:117` only. Pulled into `label_run` static closure by `strategy.py:308`. |
| `plugin.py` | DELETE-CANDIDATE | No production importer outside the package. Tests: `test_autonomy_node_detectors.py:198`, `pending_wp7_capture_guard_subclass.py:15`, `test_aut1_capture_adapter.py`. Not in the `label_run` closure list. |
| `capture_adapter.py` | DELETE-CANDIDATE | No production importer outside the package. Tests/fixtures only. Not in the closure list. |
| `decision_funnel.py` | DELETE-CANDIDATE | Production outside the package: `trade.py:121` only. In the `label_run` closure via `composition`. |
| `latch.py` | DELETE-CANDIDATE | No maker or labeling import. FQ scripts/tests and `__init__.py`. |
| `margin.py` | DELETE-CANDIDATE | Same. |
| `config.py` | DELETE-CANDIDATE | Same, plus `nbp_shadow_parity.py:76`. |
| `bounds.py` | DELETE-CANDIDATE | Same, plus parity scripts. |
| `artefact_bounds.py` | DELETE-CANDIDATE | No maker import. `nbp_shadow_parity.py:70`, `fq_loss_taxonomy_reconstruct.py`, `p2_nbp_ask_murphy.py:283`, `tests/support/te2_cli_fixtures.py:22`. |
| `app/trade.py` L114–129, L791, FQ branch | DELETE-CANDIDATE as taker wiring | Not a package file. Arm adds `trade.py:125` `LossStopProbeActor`. Maker on the arm does not depend on that line; it imports `loss_stop_probe` itself. |
| `deploy/families/pm_us_crh_fq_v1.json` | KEEP as a file maker opens | P2 lists it for deletion. `maker_stage0_model.py:33` and `:105–109` default to it and read `density_artefact_path` / sha. Callers can pass another `manifest_rel`. |
| Artefact JSON `nbp_calibration_pm_us_crh_fq_v1_2026-09-30.json` | KEEP | P2 keep-claim holds. Manifest path plus `test_parity_vs_design_driver.py:78–81` and stage0 pins. |
| `tests/strategy/forecast_quantile_ladder/` | DELETE-CANDIDATE relative to maker | Taker tests. They are not why a module must stay. Maker tests under `tests/strategy/no_ladder_maker/` are separate and only import `calibration_artefact` (current) or `calibration_artefact` + `loss_stop_probe` (arm). |

Also not in the P2 delete list, but coupled: `__init__.py`. It is not imported by maker by name. Leaving it unchanged means importing `calibration_artefact` or `persistent_latch` still loads `bounds`, `config`, `decision`, `latch`, `margin`, and `strategy`.

### Ambiguous

- `loss_stop_probe.py` is taker-only on the current checkout and maker-imported on `c614fb0b`. Those trees disagree. The arm worktree was not proven clean against the commit object.
- `decision.py`, `strategy.py`, `config.py`, `bounds.py`, `latch.py`, `margin.py` have no direct maker import, but they load today through `__init__.py` when maker or labeling imports a sibling. `composition.py`, `artefact_bounds.py`, and `decision_funnel.py` are in `label_run`'s generated closure for the same reason (`strategy.py:308`), not because labeling calls them.
- `pm_us_crh_fq_v1.json` is the stage0 default manifest, not a Python import. The supervisor also sends that family id.
- `not_applicable_boundary.json` is the FQ manifest's boundary pin. This pass did not find a `no_ladder_maker` Python import of it. Maker plans cite it; that is docs, not an import.
- `not_yet_calibrated_forecast_density.json` has no filename references in the globs searched.
- Codegraph on `/home/jon/breezy` did not enumerate every public symbol's callers. The import ripgrep is the complete `src`/`scripts` import list used here. `tests/strategy/forecast_quantile_ladder/` imports were not all pasted; they are taker-local.
- `git branch -a --contains c614fb0b` was not run. Only the branch tip `arm/integration` was shown to be that commit.## Exploration: `pm_us_crh_fq_v1` deletion pins

r2 candidate delete set (r2.1 dropped the list as a mandate, not a replacement): `decision.py`, `strategy.py`, `composition.py`, `plugin.py`, `capture_adapter.py`, `decision_funnel.py`, `latch.py`, `margin.py`, `loss_stop_probe.py`, `config.py`, `bounds.py`, `artefact_bounds.py`, the `trade.py` FQ branch, `deploy/families/pm_us_crh_fq_v1.json`, and `tests/strategy/forecast_quantile_ladder/`. Keep `calibration_artefact.py`, `persistent_latch.py`, and the calibration artefact JSON. The plan omits `__init__.py`, which imports the deleted modules plus `calibration_artefact`. That package import is why those modules are in the `label_run` grimp closure. `capture_adapter`, `plugin`, and `loss_stop_probe` are not in that closure. Citation map `tests/unit/test_r2_2_citation_map.py` has no FQ hit. Import-linter contracts do not name this package. Codegraph did not fail; the first query resolved the autonomy registry, not these pins.

| File | Test / constant | Line | Class | Exact expected set | Correct re-pin vs illegal relaxation |
|---|---|---|---|---|---|
| `src/breezy/persistence/family_manifest.py` `_COMPOSITION_KINDS` / `CompositionKind` | `test_composition_kind_exact_set_is_widened_by_exactly_one_row` | 47 | MUST-REPIN | `frozenset({"current_rung_hold", "continuous_rung_hold", "forecast_ladder", "forecast_quantile_ladder"})` | Remove `forecast_quantile_ladder` only. Illegal: `==` to `<=` / subset, or deleting the test. |
| `src/breezy/runtime/trade_supervisor_core.py` `COMPOSITION_KIND_SUBSCRIBED_MARKERS` | `test_marker_map_is_widened_by_exactly_one_row` | 70 | MUST-REPIN | 4-key dict; FQ value `"ForecastQuantileLadderStrategy subscribed"` | Remove that one key. Illegal: subset or dropping the equality. |
| same dict | `test_the_family_line_is_not_a_supervisor_readiness_marker` | 217 | MUST-REPIN | same 4-key dict | Same. The `boot_family` absence check stays. |
| same dict | `test_subscribe_marker_class_names` | 209 | MUST-REPIN | same 4-key dict | Same. `test_subscribe_marker_is_parsed_from_the_real_fq_strategy_log_line` (219) imports the strategy and fails collection if `strategy.py` is deleted; do not weaken the other three markers. |
| `src/breezy/strategy/current_rung_hold/family_id_arg.py` `HALTABLE_COMPOSITION_KINDS` | `test_the_accepted_composition_kinds_are_pinned_exactly` | 188 | MUST-REPIN | `frozenset({"continuous_rung_hold", "forecast_quantile_ladder"})` | Remove the FQ element; remainder is `{continuous_rung_hold}`. Illegal: `==` to `<=`. |
| same module `KINDS_WITH_EXIT_PATH` | `test_kinds_with_exit_path_is_pinned_exactly_and_within_the_haltable_kinds` | 239 | SAFETY-DO-NOT-TOUCH | `frozenset({"continuous_rung_hold"})` and `<= HALTABLE` | Global exit-path pin. Does not name a deleted module. Do not add FQ and do not turn `==` into a subset. Stays true after the haltable re-pin. |
| `src/breezy/persistence/autonomy/paths.py` `MODEL_CLASS_RE` | `test_model_class_kind_set_equals_composition_kinds` | 138 | MUST-REPIN | regex alternation `current_rung_hold\|continuous_rung_hold\|forecast_ladder\|forecast_quantile_ladder` | Remove the FQ alternative in the same commit as `_COMPOSITION_KINDS`. The test only checks that every remaining kind is accepted, so a stale FQ alternative does not go red. Illegal: widening the regex. |
| `src/breezy/analysis/labeling/unit_factory_default.py` `_REQUIRED_KINDS` | (no test re-asserts the literal) | 135 | MUST-REPIN | `frozenset({"forecast_quantile_ladder", "current_rung_hold", "continuous_rung_hold"})` | Remove only the FQ element. Illegal: emptying the set (hides CRH manifest-load failures). Unclassified coupling: no equality test. |
| `src/breezy/strategy/autonomy/node_plugins.py` `NODE_PLUGINS` | `test_family_plugin_exact_set` | 196 | MUST-REPIN | keys `== _COMPOSITION_KINDS`; `len == 4`; every value `type is RefusingPlugin`; source literal keys match | Drop the one FQ key on both registries together. Illegal: `len <= 4`, subset, or a non-`RefusingPlugin` node value. |
| `src/breezy/analysis/autonomy/offline_plugins.py` `OFFLINE_PLUGINS` | same test; `ARCH_C6_KINDS` 137; `EXPECTED_OFFLINE_TYPES` 152 | 196 | MUST-REPIN | FQ key maps to `FqEvaluator`; other keys `CurrentRungHoldOfflinePlugin`, `ContinuousRungHoldOfflinePlugin`, `RefusingPlugin` | Drop the FQ key only. Do not delete `evaluators/forecast_quantile_ladder.py` (not in the candidate set). Illegal: subset, or swapping `FqEvaluator` for `RefusingPlugin` without a reviewed registry edit. |
| `src/breezy/persistence/autonomy/pins.py` `LIVE_GATE_ROUTED_KINDS` | `test_literal_identity_pins` | 119 | MUST-REPIN | `frozenset({"forecast_quantile_ladder"})` | Remove the one element (result empty) in a reviewed pin commit. Deleting strategy files alone does not fail this. Illegal: `==` to `<=`, or adding a kind. |
| same constant | `test_every_live_kind_covers_required_detector_classes` | 85 | MUST-REPIN | same one-element frozenset | Same. The detector-class coverage assertions below it are not family-specific. |
| same module `BOOTSTRAP_SEED` | `test_literal_identity_pins` | 122 | MUST-REPIN | `(("pm_us_crh_fq_v1","CHAMPION"), ("pm_us_crh_v4","RETIRED"), ("pm_us_crh_cont","RETIRED"), ("pm_us_crh_v2","RETIRED"))` | Strategy deletion alone does not fail this. Removing the FQ pair without naming a new champion fails `test_bootstrap_seed_is_one_champion_and_unique_ids` (146: exactly one `CHAMPION`, states `== {"CHAMPION","RETIRED"}`). Illegal: subset, zero champions, or `HALTED`. |
| `src/breezy/persistence/autonomy/closure_manifest.py` `CLOSURE_MODULES["breezy.analysis.labeling.label_run"]` | `test_closure_manifest_equals_grimp_closure` | 689 | MUST-REPIN | exact tuple includes `forecast_quantile_ladder` plus `artefact_bounds`, `bounds`, `calibration_artefact`, `composition`, `config`, `decision`, `decision_funnel`, `latch`, `margin`, `persistent_latch`, `strategy` (224–235). Not included: `capture_adapter`, `plugin`, `loss_stop_probe` | Stop `__init__.py` importing deleted modules, regen the manifest, drop only the deleted names. Keep `calibration_artefact` and `persistent_latch`. Illegal: `drift == []` to a subset, or hand-editing past grimp. `test_regen_output_is_literal_and_reproducible` (747) requires the committed file to match the renderer. |
| `pins.PRODUCER_SOURCE_SHA256` | `test_code_identity_pins_cover_import_closure` | 599 | MUST-REPIN | keys exactly `{"aut6.health","aut2.label"}`; values are closure sha256s (`aut2.label` = `db374704e225d89c1a532c48553774c1d2c36c889d09a836c681008df1e27b2c`) | Re-pin both hashes. `closure_manifest.py` is in both closures, so the health hash changes even though the health tuple has no FQ module. `test_aut2_label_is_pinned_to_its_own_closure` (15) is the label equality. Illegal: hashing a subset of modules, or deleting the coverage test. |
| `src/breezy/persistence/autonomy/closure_manifest.py` key set | `test_manifest_holds_only_the_reviewed_components_and_refuses_the_rest` | 90 | SAFETY-DO-NOT-TOUCH | `{"breezy.runtime.autonomy_health_cli", "breezy.analysis.labeling.label_run"}` | Not family-specific. Do not add or drop a component key as part of this deletion. |
| `tests/unit/test_autonomy_policy_ban.py` `SEAM_ALLOWLIST` | `test_every_exemption_and_allowlist_row_is_reasoned_literal_and_live` | 66 / 369 | MUST-REPIN | two `AllowRow`s; one is `("src/breezy/strategy/forecast_quantile_ladder/composition.py", "_resolve", ...)` | Remove that one row when `composition.py` is deleted (the liveness test reads the file). Keep the `promotion_criteria.py` row. `POLICY_BAN_EXEMPTIONS == ()` (616) stays empty. Illegal: catching a missing file, or deleting the liveness test. `test_autonomy_policy_not_mutable_from_src` (387) is `findings == []` over all of `src` — do not weaken. |
| `tests/contract/test_fq_loss_stop_writer_allowlist.py` | `test_loss_stop_artefact_path_callers_in_closed_allowlist` | 48 / 251 | MUST-REPIN | `_GRANDFATHERED_CALLERS = {loss_stop_probe.py, app/trade.py}`; `_WRITERS` empty; `_NEW_CALLERS` empty. Assertion is already `callers <= grandfathered \| new` plus `"src/breezy/app/trade.py" in callers` | Module import of `loss_stop_probe` fails collection if the probe is deleted. Reviewed edit: drop the probe path and the required `trade.py` member only if both call sites are gone. Illegal: widening `_NEW_CALLERS` or `_WRITERS`, or deleting this contract so new writers are unscanned. |
| `tests/contract/test_autonomy_units_programme.py` `_CARVE_OUTS` | `test_every_carve_out_is_live_and_documented` | 67 / 245 | MUST-REPIN | 3-tuple; two rows match `composition_kind=forecast_quantile_ladder` (`replay-daily-run.sh` return 3, `score-live-trials-run.sh` return 2); third is `asos-refresh-run.sh` `SKIPPED-LOCK` | Does not fail while those shell lines remain. If the skip lines are removed, drop those two rows in the same commit. Illegal: deleting the liveness test, or broadening the regex. |
| `tests/unit/test_replay_daily_wrapper.py` | `test_a_forecast_quantile_ladder_sending_family_skips_without_replay_tooling` | 148 | MUST-REPIN | expected substring `REPLAY DAILY SKIPPED -- composition_kind=forecast_quantile_ladder has no replay_daily_runner` for family `pm_us_crh_fq_v1` | Fails if the manifest json is deleted or the shell branch is removed. Update with the shell carve-out. Illegal: accepting any skip text. |
| `tests/unit/test_score_live_trials_deploy.py` | (skip assertion) | 795 | MUST-REPIN | `SCORE LIVE TRIALS SKIPPED -- composition_kind=forecast_quantile_ladder ` | Same. |
| `tests/unit/test_family_tally_v2_deploy.py` | `test_wrapper_skips_without_marker_when_sending_family_is_forecast_quantile_ladder` | 340 | MUST-REPIN | log must contain `FAMILY TALLY V2 (pm_us_crh_v2) SKIPPED -- sending family pm_us_crh_fq_v1 is forecast_quantile_ladder; no score-live-trials run by design` | Same. Not a set equality. |
| `tests/unit/test_operator_caps_through_the_live_composition.py` `_FQ_S5_NEW_MODULES` | `test_fq_live_orders_gate_touches_no_operator_control` | 800 | SAFETY-DO-NOT-TOUCH | exact 4-path tuple: `live_orders_gate.py`, `family_manifest.py`, `trade.py`, `composition.py`. Each must have zero operator-control assignments | Remove only the `composition.py` path if that file is deleted. Keep scanning the other three. Illegal: skipping a missing file, or dropping `trade.py`. The file also imports `persistent_latch` (99) — keeper import; do not delete the module. |
| `src/breezy/persistence/live_orders_gate.py` `_LIVE_ORDERS_ALLOWLIST` | `test_both_copies_sha256_equal_the_gates_allowlisted_pin` / `_allowlisted_sha256` | 80 / 31 | SAFETY-DO-NOT-TOUCH | one 3-tuple `("pm_us_crh_fq_v1", "RULING_operator_fq_live_real_orders_2026-10-01", "11c69d132a70d8e328d3720314336aa6f2cf176d52fd25d5f2e20a7189711c1f")`. Unpack requires exactly one row for that ruling | Enablement pin, family-specific. Strategy deletion does not fail the ruling-byte tests. A retirement re-pin removes that one tuple (set empty) in a reviewed commit. Illegal: a second family, a shorter sha, or deleting the test while the gate can still enable the id. |
| `tests/unit/test_fq_live_orders_gate.py` | (module) | 36 | SAFETY-DO-NOT-TOUCH | imports `composition` and `latch` (both deletion candidates) | Collection fails if those modules go. The gate refusals are the enablement invariant. Do not delete the gate tests to go green; split the composition import out. |
| `tests/unit/test_fq_s8_registration_artefacts.py` | `test_calibration_artefact_byte_copy_matches_the_pinned_sha256` | 48 / 59 | KEEPER-TEST | artefact sha `9c0b6d6e66a587c1b4e14e5f95ff5cedb3c7195f62f8ad4238191fdd75923a5e` | Artefact JSON stays. Do not drop the sha equality. |
| same file | `test_the_registered_manifest_loads_without_allow_draft` | 81 | MUST-REPIN | loads `pm_us_crh_fq_v1.json`: `REGISTERED`, kind `forecast_quantile_ladder`, stations `("LAX","MDW","MIA","SFO")`, fee `Decimal("0.0695")`, ruling id above, `exit_rule is None` | Fails if the manifest json is deleted. That file is the candidate delete. Do not weaken `exit_rule is None` or `REGISTERED`. |
| `tests/unit/test_forecast_quantile_ladder_manifest_and_markers.py` | `test_pm_us_crh_fq_v1_is_registered_with_the_operator_ruling` / `test_pm_us_crh_fq_v1_loads_and_names_the_right_composition_kind` | 95 / 104 | MUST-REPIN | manifest exists, `REGISTERED`, ruling id, kind `forecast_quantile_ladder`, family id | Same manifest-file dependency. Not a license to delete the composition-kind equality test in this file. |
| same file | `test_exec_client_is_byte_identical_to_its_pre_sl13_sha256` | 117 | SAFETY-DO-NOT-TOUCH | sha256 of `adapters/polymarket_us/exec/client.py` `a4cbd8cbbf29524a6de3c18dc4e2b565ce25e1f1b91ca54f0c2483f671b64410` | Global NO-SEND byte pin. Does not mention the family in the assertion. Do not delete this test with the FQ file. Illegal: updating the sha without a reviewed exec-client change. |
| `tests/unit/test_trade_supervisor_phase1_unit.py` | `test_installed_unit_runs_the_registered_sending_family_by_id` / `test_the_installed_unit_names_a_REGISTERED_family` | 37 / 49 / 68 | SAFETY-DO-NOT-TOUCH | exactly one line `Environment=BREEZY_SENDING_FAMILY_ID=pm_us_crh_fq_v1`; manifest for that id must exist and be `REGISTERED` | Sending-family enablement. Deleting the json fails the second test while the unit still names this id. Illegal: dropping the `REGISTERED` check or the single-line count. Changing the id is a reviewed promotion, not a deletion side effect. |
| `src/breezy/runtime/health_dropins.py` `DROPIN_ALLOWLIST` | `test_the_shipped_row_is_pinned_to_the_ruling_and_its_expiry` | 47 / 116 | SAFETY-DO-NOT-TOUCH | exact one row: unit `breezy-trade-supervisor.service`, drop-in `fq-v1-halt-orders-off.conf`, sha `5ff0d6a1b157aa730cd9c87c4060e3016bed744777674b71af874c95c485e09d`, ruling `RULING_FQ-v2-NO-TRADE_2026-10-08`, expires `2026-12-31`. Directives only `[Service]` and `Environment=BREEZY_ORDERS_ENABLED=0` | Orders-off allowlist. Strategy deletion must not remove this row. `(row,) = DROPIN_ALLOWLIST` is cardinality 1. Illegal: a second row, a weaker directive set, or changing the unpack to a subset. `tests/unit/test_unit_health.py` 1464–1497 is a fixture copy of the same name, not a second source pin. |
| `tests/unit/test_cage_rule_constants_are_pinned.py` `RulePin` `BANNED_EXEC_TRANSPORT_MODULES` | cage equality; `test_exec_import_pin_x1_is_superset_of_recorded_baseline` | 386 / 627 | SAFETY-DO-NOT-TOUCH | 11 modules: polymarket data/http/websocket, ingest http, mdl_lamp_transport, four nws observation modules, probe_transport, `breezy.runtime.health`. X1 baseline is that set minus `mdl_lamp_transport`, and the difference must `== {"breezy.ingest.mdl_lamp_transport"}` | Global exec import pin. No FQ module. Deletion does not fail it. Illegal: removing a member, or turning the cage equality / the difference `==` into a subset. |
| `tests/strategy/forecast_quantile_ladder/test_config.py` | `test_allow_short_true_is_refused` | 43 | SAFETY-DO-NOT-TOUCH | `allow_short is False`; `True` raises | Family-specific copy of the global short ban, inside the candidate-deleted test tree. Deleting this file must not be paired with relaxing `weather_common` / `ladder_ev` / exec `allow_short` pins (those do not name this family). |
| `tests/unit/test_fq_loss_stop_probe.py` | `test_fq_has_no_exit_order_path` | 395 | SAFETY-DO-NOT-TOUCH | `offenders == []` for `submit_exit\|exit_wiring\|ExitOrder\|exit_manifest` under the package | Family-scoped no-exit scan. The module imports `loss_stop_probe`, so collection fails if the probe is deleted. Illegal: `== []` to a subset. Move the scan if the package survives; do not weaken it. |
| `tests/strategy/forecast_quantile_ladder/test_forbidden_imports.py` | `test_no_module_in_the_package_imports_a_forbidden_module` | 27 | KEEPER-TEST | scans every `*.py` in the package; forbids `archive_table` and `exclusion_filter` / `ExclusionInputs` / `P_HOLD_*` | Does not fail when taker modules disappear. Do not delete it with the taker suite: it is the import pin on the keepers. Not an exact module-set equality. |
| `tests/strategy/forecast_quantile_ladder/test_calibration_artefact.py` | (module tests) | 24 | KEEPER-TEST | imports `calibration_artefact` | Do not delete with the taker-only suite. |
| `tests/strategy/no_ladder_maker/test_parity_vs_design_driver.py` | import | 48 | KEEPER-TEST | imports `calibration_artefact`; reads the artefact JSON (79) | Keeper. Do not delete. |
| `tests/unit/test_fq_live_analysis_point_cdf_parity.py` | import | 55 | KEEPER-TEST | `load_live_calibration` | Keeper. |
| `tests/unit/test_nbp_shadow_parity_live.py` | import | 42 | KEEPER-TEST | `LiveCalibration`; also loads `pm_us_crh_fq_v1.json` at 776 | Keeper import. Manifest load fails if that json is deleted — re-point the manifest read, do not drop the calibration import. |
| `tests/unit/test_nbp_shadow_parity_no_side_synthetic.py` | import | 41 | KEEPER-TEST | `LiveCalibration` | Keeper. |
| `tests/unit/test_aut1_wp0_log_line_premises.py` | import | 126 | KEEPER-TEST | `LiveCalibration` | Keeper. |
| `tests/unit/test_maker_stage0_pno.py` | import | 27 | KEEPER-TEST | `LiveCalibration` | Keeper. |
| `tests/support/te2_cli_fixtures.py` | import | 22 | KEEPER-TEST | `load_live_calibration` and also `ArtefactBoundsProvider` (22) | Mixed: calibration stays; `artefact_bounds.py` is a deletion candidate, so this fixture fails if that module is deleted. Fix the bounds import; do not drop the calibration import. |
| `tests/strategy/forecast_quantile_ladder/test_persistent_latch.py` | (module tests) | 19 | KEEPER-TEST | imports `persistent_latch` | Do not delete with the taker suite. |
| `tests/unit/test_aut2_attribution.py` | import | 46 | KEEPER-TEST | `persistent_latch` | Keeper. Many `pm_us_crh_fq_v1` literals are labeling fixtures, not set pins. |
| `tests/unit/test_te1_label_wiring.py` | import | 87 | KEEPER-TEST | `persistent_latch` | Keeper. |
| `tests/support/te1_fixtures.py` | import | 37 | KEEPER-TEST | `persistent_latch` | Keeper. |
| `tests/unit/test_set_family_halt_cli.py` | `test_fq_family_halt_key_matches_trade_preamble` | 1436 | SAFETY-DO-NOT-TOUCH | imports `FORECAST_QUANTILE_TRIAL_KEY_PREFIX` from `persistent_latch`; also `test_v1_manifest_terminal_day_parses` (1424) requires `pm_us_crh_fq_v1.json` and `terminal_climate_day == "2026-10-05"` | Halt-key invariant. Keeper module stays. Manifest assertion fails if the json is deleted. Illegal: weakening the halt-key match. |
| `tests/unit/test_family_halt_cli_fq.py` | import | 36 | SAFETY-DO-NOT-TOUCH | imports `persistent_latch`; also owns the haltable exact-set test above | Do not delete the file to drop the exact-set pin. |
| `tests/unit/test_ct12_fq_halt_through_run.py` | import | 37 | SAFETY-DO-NOT-TOUCH | imports `persistent_latch`, `decision.Take`, and `strategy` | Halt-through-`trade.run` test. Collection fails if `decision.py` / `strategy.py` go. Do not delete it to avoid the halt check; it is not an exact-set pin. |
| `tests/strategy/forecast_quantile_ladder/test_sl13_wiring.py`, `test_opposite_side_latched.py` | imports | 35 / 35 | KEEPER-TEST | import `persistent_latch` and also deleted modules (`strategy`, `decision`, `latch`) | Taker tests. Deleting them is consistent with the candidate test dir, but do not treat that as permission to delete `test_persistent_latch.py`. |
| `src/breezy/persistence/exit_gate.py` `_EXIT_RULE_REGISTERED_FAMILIES` | `test_persistence_exit_gate` equality | 55 / 82 | SAFETY-DO-NOT-TOUCH | `frozenset({"pm_us_crh_exit_v4"})` | Does not include `pm_us_crh_fq_v1`. Do not add this family and do not relax the equality. A comment in `test_persistence_exit_gate.py` mentions the FQ json; the assertion does not. |
| `tests/unit/test_app_trade_fq_loss_stop_wiring.py` `_ALLOWED_DIFF` | `test_f6_diff_name_only_is_within_scope` | 236 | INCIDENTAL | subset cap including `loss_stop_probe.py`; skips once that path exists at the merge base | Will not fail on deletion while the skip condition holds. Not a live exact-set pin. |
| `tests/unit/test_shadow_only_false_is_only_the_gate_output.py` | `test_a_changed_config_default_is_flagged` | 201 | INCIDENTAL | path string `.../config.py` is a synthetic argument, not a live file read | Permitted path is only `src/breezy/app/trade.py`. Does not fail if `config.py` is deleted. |
| `tests/unit/test_r2_2_citation_map.py` | `test_r2_2_citation_map_symbols_resolve` | 34 | INCIDENTAL | map has no `forecast_quantile_ladder` / `pm_us_crh_fq_v1` / `fq-v1` row | Will not fail. |

Unclassified: `_REQUIRED_KINDS` has no equality test, so a stale FQ element stays green. `MODEL_CLASS_RE` is only checked in the accepting direction, so a leftover alternative stays green.
