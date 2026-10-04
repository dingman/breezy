# AUT-1 build-time rulings (coordinator)

Rulings made while building AUT-1a against plan r12. Binding in every later AUT-1 brief.

## WP0 part (c): scratch systemd experiments (2026-10-04, 07:48–07:51Z)
Method deviation, ruled up front: transient `systemd-run --user --unit=claude-aut1wp0-*` units with every property set by `-p`. No unit files and no `daemon-reload`, because the repo's unit files are symlinked into systemd and a reload could activate unmerged edits. All units were cleaned up, and the experiments ran from `scratchpad/aut1wp0c/`.

- **PASS:**
  - V-8 (a)–(f): extend-timeout keeps `activating` and ends in `timeout`; no watchdog before READY; `watchdog` + `Restart=always`; the hook sees `SERVICE_RESULT` and `INVOCATION_ID`; a failed or killed hook leaves `watchdog`; no `NOTIFY_SOCKET` under `Type=simple`/`none`.
  - V-9(a): the `NotifyAccess=all` datagram is accepted across bwrap; the `=main` negative control times out.
  - V-10.
  - V-18.
- **WP0-R1 (V-9(b) FAIL, superseded, no return to review).** `systemctl --user show` inside `--unshare-pid` bwrap fails with ENODATA (the peer cannot be resolved across the PID namespace); `journalctl --user` works.
  - This is exactly the case the ARCH-0 seam B handoff replaces: seam B plan r5:426 and errata §E-7e (ARCH-ERRATA l.351, "l.1045: V-9(b) becomes the handoff").
  - The handoff was proven on the real host: seam B V17 and V21 PASS.
  - The audit reads the bus snapshot. The drill and guard are unwrapped residuals (seam B r5:425).
  - Not adopted: dropping `--unshare-pid`, or `gdbus`/`busctl` in-row.
- **WP0-R2 (V-21 scratch half STOPPED, correctly).** `quote_tape_cli.py` requires `POLYMARKET_US_*` venue env and would open a venue connection, so it is never run in a scratch unit.
  - The premise "a try-restart writes a new `config.json`" is instead decided from the 14-day journal ↔ `config.json` match (part (b)): a journal restart matched by its own new `config.json` satisfies it.
  - If part (b) finds no restart in 14 days, the premise is CANNOT-MEASURE, and §3.7.4 keeps the hook file as the primary boot evidence.
- **Observations carried to WP3/AUT-6:**
  - The default `WatchdogSignal` is SIGABRT and dumps core. WP3 sets `WatchdogSignal=` explicitly per plan §3.10.2.
  - A unit that keeps sending `EXTEND_TIMEOUT_USEC` while ignoring SIGTERM sat in `stop-sigterm` for more than 3 min. WP3's pinger must stop extending once the stop begins, and this needs a test.
  - `OnFailure=` fired on every failure, but a real notifier target was not exercised; that is AUT-6's `breezy-autonomy-failed@` (X-4).

## WP0 part (a): characterisation tests (8a72a5fd on `backlog/aut1a-2026-10-04`)
- **Result.** 31 tests: 30 pass, plus 1 strict xfail. Every one goes red against its mutation. lint-imports 11/0.
- **Nautilus line drift** is at most ±2 on every citation; table in the agent return.
- **WP0-R3 (V-1, plan text corrected, premise holds).** A type defined after the writer is built is still picked up, because the writer holds the live schema dict. The real failure is a never-registered class: `KeyError` at `writer.py:460` (`_create_writer`), raised before the writer's own try. The test pins that, and the "registered before writer" assertion stands.
- **WP0-R4 (V-6, the plan's fail-branch applies).**
  - Streamed `OrderInitialized` carries enum NAMES (`BUY`, `IOC`). `intent_fingerprint` hashes `str(enum)`, which on 1.231.0 is `'1'`/`'2'`. The price is only in the `options` JSON, and the `price` column is null.
  - The WP1 reader maps names via `order_side_from_str` / `time_in_force_from_str`, then `str()`, and reads the price from `options`. The map is named in the evidence file.
  - Proven on YES and NO legs.
- **OPEN, pending adjudication with part (b):**
  - V-15: `strategy.ladder_ev.forecast_state` pulls in 33 venue-adapter modules via `current_rung_hold/__init__` → `trial_day_latch` → `adapters.polymarket_us.symbology`. The test is a strict xfail.
  - V-14: spawn sites are 4, not 3. Two of them (`:1379`, `:1982`) log no pid.
  - V-14: a Take emits two SHADOW_DECISION lines (`_emit_decision_outcome` adds `TrySubmit`).
  - The 1,858-line test file is over the 800 limit.

## WP0 part (b): measurements (2026-10-04, heavy job 07:57–08:01Z, studies flock, MemoryMax=4G, peak 2.8G; scripts in `scratchpad/aut1wp0b/`)
- **V-20 PASS.**
  - Connect-time attempts: n=17, p99 10.0 s against the 90 s review trigger. Pages 0–1.
  - No transport retry is visible. The `HttpClient` stub exposes no retry knob; Rust internals are unreadable.
  - `DISCOVERY_ATTEMPT_BUDGET_S=180` holds.
- **V-21 PASS** with the WP0-R5 caveat below. 16 starts, 16 `config.json` files at 0.7–2.4 s after start. The dir-mtime overcount is confirmed: day 09-26 shows 7 dirs vs 1 boot.
- **V-22 PASS. V-23 PASS:** no mover. Since `f45f5a65`, only the ingest timer changed (O-1).
- **"Measured" list.**
  - Stream volume: about 1.7k rows per full UTC day, against the 20k threshold.
  - D8: the maximum venue-wide silence over 14 days is 461 s (0 runs ≥ 900 s). Per-instrument gaps ≥ 900 s occur 2,051 times, so the gate stays venue-wide.
  - Writer-stall growth interval p99.9 5.0 s, from a 40-minute sample (weak tail).
  - Drill slot 12:00–13:30Z: 0 Takes/orders in all retained logs.
  - `ForecastPoint` rows per day: 112–140.
- **Constants for the evidence file:**
  - `STREAM_SILENCE_S`=900;
  - `QUIET_HOURS_MULTIPLIER`=1;
  - `WRITER_STALL_S`=120 (floor binds);
  - `FLUSH_MARGIN_S`=30;
  - `DISCOVERY_ATTEMPT_BUDGET_S`=180.
- **WP0-R5 (V-21 matching).** Boot evidence matches journal starts to `config.json` by `instance_id`, never by a 60 s window. Two 09-29 starts were 41.2 s apart.
- **OPEN, pending architect adjudication:**
  - V-12 is CANNOT-MEASURE: there is no persisted held vector, and FQ has been live only since 10-01.
  - V-7 and V-11 were measured over 3 FQ days, not 14. V-7: a true missing quote is about 4e-6. V-11: node frames are 93.3% catalog-corroborated (Takes 13/14), so leg B is INFO.

## WP0 adjudication (architect, 2026-10-04): no return to review; all items are amendments
- **WP0-R6 (V-15).** Strip the package facade (option b).
  - `strategy/ladder_ev/__init__.py` becomes its docstring plus `__all__: list[str] = []`, mirroring `strategy/__init__.py:7-18`.
  - Today the facade eagerly imports `ladder_ev.decision` → `current_rung_hold.decision` → `current_rung_hold/__init__` → `trial_day_latch` → venue adapters.
  - Nothing imports a name from the facade. `test_forecast_catalog.py:27` imports a submodule and still works. No pin covers the facade.
  - Owner: WP1's first commit. WP1 may start now but cannot merge without it.
  - The WP0 strict-xfail at `:1535-1551` flips, so its marker is removed in the same commit.
  - Add `test_ladder_ev_package_init_has_no_imports`.
  - The AST walk remains the lint, because grimp has no edge for a package's implicit `__init__`.
  - Amend r12 V-15's "if it fails" column.
  - The node picks it up at the next boot; it is import-order only.
- **WP0-R7 (V-14).** Owner WP5. No `trade_supervisor.py` edit; plan text and tests only.
  - **(a) Spawn events.** There are exactly four:
    - `launched pid=` at `:1300`;
    - `boot_retry_launched pid=` at `:1633`;
    - `relaunching attempt=` at `:1377`, logged before the spawn;
    - `midday_relaunching phase=midday_watch attempt=` at `:1972`, logged before the spawn.
    - `launch_spawn_failed` at `:1296` is a no-spawn event.
  - **Matching events to logs.** Each event matches 1:1, in time order, to the next unmatched `breezy-trade-<stamp>.log`. The pid is never the join key. An event with no log is `ERROR node_log_missing`.
  - **Tests.** Extend `test_supervisor_launched_pid_line_matches_trade_supervisor_1300` to cover all four. Add an AST pin: exactly four `ports.spawn(` calls, each paired with its event.
  - **(b) Decision lines.** Each evaluation emits exactly one decision-class line. A Take adds exactly one `kind="TrySubmit"` line, and only when `shadow_only=False`.
    - R1 pairs each TrySubmit with the preceding Take on the same `(instrument_id, rung_id, side)`.
    - R2 drops TrySubmit before the OnChange/EvalSeq replay.
    - R3 computes evaluations = total − TrySubmit.
    - The WP5 parser classifies lines by `kind`.
    - Fix the premise text at r12:86.
    - Rename the WP0 test at `:1279`.
- **WP0-R8 (V-12).** Deferred to WP8 acceptance; this is not a return to review, because the input is what AUT-1 builds.
  - WP1 keeps its unit checks: `test_forecast_ref_resolves_to_vector_equal_to_strategy_state` and `test_reissue_replays_as_fq_pushed_it`.
  - WP8 acceptance runs on the first full capture day:
    - every Take's forecast key resolves in the boot's stream;
    - FQ's own functions on the resolved vector reproduce the logged `p_hat`, `p_lower`, `p_upper` and `ev_net` exactly;
    - a 1% sample of refusals agrees on visibility;
    - reissue is checked on its first occurrence.
  - A mismatch then triggers the original review branch and marks the day `forecast_ref_unverified`.
- **WP0-R9 (measurement windows).**
  - **V-7** is satisfied by the ordering test. No re-measure is needed.
  - **V-11** is provisional.
    - The R6 baseline is 93.3% − 1 pp.
    - Leg B splits into `tape_frame_absent` (INFO) and frame-present-but-unequal (FAIL).
    - Re-measure over 14 FQ days on or after 2026-10-15. Owner WP5; this blocks WP5 activation only.
  - **V-21:** WP0-R5 is endorsed. `config.json` mtime is an ordering sanity check only. Add `test_boot_count_matches_by_instance_id_not_time_window` (WP5).
- **WP0-R10 (file size).**
  - Split the 1,858-line WP0 file before the WP0 merge. Helpers and the closure walk go to `tests/unit/aut1_premises_support.py`. The tests go into five files:
    - `test_aut1_wp0_writer_premises.py`
    - `test_aut1_wp0_order_cache_premises.py`
    - `test_aut1_wp0_forecast_feed_premises.py`
    - `test_aut1_wp0_log_line_premises.py`
    - `test_aut1_wp0_closure_premises.py`
  - Collection must show the same 31 ids before and after.

## Sequencing (2026-10-04, about 09:00Z)
- **G-ERR is satisfied.** ER-1..ER-10 were adopted (ARCH-ERRATA-rev9_2.md:241), so WP1, WP5 and WP8 are not errata-blocked.
  - WP3 step 2 still waits on AUT-6 WP4 (`test_aut6_unit_health_tolerates_activating_within_start_budget`) and on AUT-6's `breezy-autonomy-failed@` notifier.
- **Order of work.**
  - WP1 runs after the WP0 close-out, in `breezy-aut1a`. It needs the WP0-R6 facade commit.
  - WP2 runs after WP1.
  - WP3 step 1 and WP4 run in parallel now, in `breezy-aut1-wp3` and `breezy-aut1-wp4`.
  - WP4 merges only in WP8's train.
  - WP6 waits on AUT-4.
- **Worktree cap (coordinator call).** Six non-`.claude` worktrees, one over the skill's cap of 5:
  - `breezy-gate-a` is a detached snapshot used only for gating;
  - `breezy-arch0-a` frees after 8c/8d merge tonight.

## WP4 (a77a8f85 on `backlog/aut1-wp4-2026-10-04`; built and gated, merges in WP8's train)
- **Result.**
  - RED: 13 new tests failed.
  - GREEN: the new tests plus the 34 existing tests pass. No existing test body was edited.
  - 7 mutations, all killed.
  - Focused gate: `phase1 rc=0 phase2 rc=0`.
- **WP4-R1 (FQ side, partial).** The `feed_stale` veto and the "no complete vector for a subscribed station" cases need the `nbp_feed_freshness` detector, which is WP7 (AUT-1b). They are carried to WP7. WP4 pins only the `missed_cycles` count the detector reads.
- **WP4-R2 (accepted design choices).**
  - Optional constructor kwarg `evidence_root`.
  - "Vector complete" means a successful publish of the reset cycle or a newer one. `FQ_VECTOR_COMPLETE` is FQ-side and the actor cannot see it.
  - Heal records:
    - `alert_offer` returns False → the record says `alert="offered"`, and the actor logs CRITICAL `NBM_NBP_HEAL_ALERT_UNDELIVERABLE`;
    - no `alert_offer` at all → `alert="undeliverable"` (r12 test name).
  - `alert_offer(event, severity, detail)`. AUT-6's outbox signature must match it; check this at WP8.
  - `NBP_POLL_HANG_S=600` is a module constant (> 2 × the 60 s read timeout).
  - The retained future is the oldest unfinished poll.
  - Before any complete cycle exists, the baseline is the cycle current at boot.
- **Review.** A python-reviewer review runs before WP8's train merges it.

## WP1 part A (45a54321 on `backlog/aut1a-2026-10-04`)
- **Result.**
  - 8 modules, all ≤273 lines.
  - 101 tests. RED was 8 collection errors; GREEN passes the focused gate with `phase1 rc=0 phase2 rc=0`.
  - 9 mutations, all killed. The id-recompute test gained an independent-hash assertion, so the `eval_seq` mutation now fails.
  - Contracts (b) and (c) are append-only (diffed).
- **WP1-R1 (deviations, accepted).**
  - r8's payload-ref id tests are retired. ER-3 removed the payload store, and r12 §3.4.1 lists only the three id functions plus the counter.
  - `EvalSeqCounter` lives in `capture_ids`, with an `on_nonmonotone` callback. The caller rate-limits the log line.
  - On-change: Take and TrySubmit always pass and also become the key's last state. Eviction runs before insert.
  - Epoch: published through `single_read.write_once`. The alert seam is `offer(event, severity, detail)`, the same shape as WP4-R2; AUT-6's outbox must match it.
  - `capture_records`, `capture_stream` and `capture_publish` join `NAUTILUS_PERMITTED`. The no-Nautilus contract still holds for `capture_ids` and `capture_on_change`.
  - `launch_window_guard` uses the half-open window [16:30Z, 17:10Z).
  - Native tables exist at size 0 from `open()`. The per-type check skips tables with no records in the window.

## WP3 step 1 (1fa1909f on `backlog/aut1-wp3-2026-10-04`; under SEC + python review)
- **Result.**
  - RED: 6 collection errors at the base.
  - GREEN: the focused gate passes, `phase1 rc=0 phase2 rc=0`.
  - 10 mutations, all killed.
  - No `deploy/systemd` edit. The existing recorder and polymarket tests are unedited.
- **WP3-R1 (alert contract test placement).** `test_capture_alert_contract.py` moves to the WP that defines the capture-actor events `CAPTURE_STREAM_TYPE_FLAT` and `CAPTURE_WATCHDOG_EVIDENCE_GAP`, which is WP8. It is NOT built in step 1.
- **WP3-R2 (step-2 gate tests absent, not xfailed).** The following stay uncreated until step 2 / AUT-6 WP4:
  - `test_aut6_unit_health_tolerates_activating_within_start_budget`;
  - `test_aut6_rotate_bound_test_reads_constants_not_literals`;
  - the deployed-unit cases.
  Step 2 must create them, and they must be RED before AUT-6 lands.
- **OPEN for step 2 (pending SEC advice).** The plan's `ExecStopPost=-…` hook line fails the B6-R7 `exec_prefix` lint.
  - Evidence: V-8e shows a hook without `-` that exits 1 leaves `Result=watchdog` unchanged.
  - Untested: a clean stop (the 09:00Z rotate, `Result=success`) followed by the hook being killed by `timeout`.
- **Step-2 obligations.**
  - Before the unit edit, provision `evidence/capture/stall` and `health/recorder_watchdog` under the data root at 0700. The wrapper never creates bind dirs.
  - AUT-6 must decode the X-7 fixture's real journal shape: `MESSAGE` as a byte array with ANSI escapes.
- **WP3-R3 (SEC + python reviews of 1fa1909f, both REQUEST_CHANGES; the sandbox change was judged not weakening).** All findings are adopted for step 1.
  - **(SEC M1)** `_ensure_watchdog_pinger()` in `_connect` is wrapped in `try/except Exception`, logging `RECORDER_PINGER_DIED`. The watchdog can never fail connect, because Nautilus swallows connect errors and that would leave a zombie recorder. Test: a raising pinger constructor still connects.
  - **(SEC L2 = py M1)** `_connect` resets `_disconnecting = False`. Test: a reconnect after a disconnect still extends before READY.
  - **(py M2)** Config `__post_init__` rejects `watchdog_notify=True` without a non-empty `str` `watchdog_stream_dir`. Add a test.
  - **(SEC L3)** The stall record is written atomically: write a temp file, `os.link` it to the final name (EEXIST means it already exists), then unlink the temp. Fsync the directory after the health rename (L6).
  - **(SEC L4)** Failure logs print `invocation_id` only when it fullmatches `[0-9a-f]{32}`; otherwise they print `invalid`.
  - **(SEC L5)** The day directory is created with `os.mkdir(day, dir_fd=root_fd)` plus a nofollow open.
  - **(SEC L8)** `sd_notify` requires `NOTIFY_SOCKET` to start with `/` or `@`.
  - **(py L1)** Add flush-margin boundary tests at exactly 30 s and at 29 s. This kills the surviving `>=`→`>` mutant.
  - **(py L2)** Per-entry `stat` errors (`FileNotFoundError`) skip that entry and do not zero the whole directory.
  - **(py L3)** `tests/support/recorder_watchdog.py`:
    - poll for the deadline instead of `time.sleep`;
    - move `SLUG` and `ControllableFeed` into support, so support never imports test modules;
    - drop `drain()`.
  - **(py L4)** Client-level pinger tests await a condition or tick count, not fixed sleeps.
  - **Deferred.** `data.py` is 2,538 lines, an existing debt. Moving the watchdog glue out is backlog, not WP3.
- **WP3-R4 (step-2 `-` prefix: SEC advice adopted).**
  - Keep `ExecStopPost=-/usr/bin/timeout …`. Without `-`, a non-zero or timed-out hook after a clean 09:00Z rotate (`Result=success`) would flip the unit to failed and fire AUT-6's `OnFailure=` pager.
  - Step 2 adds a narrowly scoped lint allowance: for line-only units only, exactly one leading `-` on `ExecStopPost`, immediately before `/usr/bin/timeout`. `exec_prefix` stays for every other case, and a test pins the exact form.
  - Before step 2 merges, run a transient-unit experiment with a clean stop, a hook running `false`, and a hook killed by `timeout`, each with and without `-`. Record `Result`, the failed state and whether `OnFailure=` fires.

## WP1 part B (7645ddbf)
**Result.**
- Reader, forecast-ref and closure lint are in.
- RED came from collection errors; GREEN passes the focused gate.
- 7 planned mutations and 3 extra mutations were all killed.
- Coverage: reader 98%, forecast_ref 100%, ids 100%.

**WP1-R2 (deviations accepted).**
- **Unknown enum names.** On 1.231.0, `order_side_from_str` / `time_in_force_from_str` PANIC (abort, rc=134) on an unknown name. The reader checks `OrderSide.__members__` / `TimeInForce.__members__` first and raises `CaptureProjectionError`.
  - Binding for every future caller on stream data: guard before calling these functions.
- **Hygiene row.** `(capture_reader.py, "/proc/self/fd")` is added, following the `single_read`/`wal_snapshot` precedent and pinned to that file. The reader uses `open_root` plus fd reads, because `salvage_feather_file` needs a path. A symlink under any name is refused.
- **Ref helpers** live in `capture_ids` (§3.1).
- **`resolve_forecast_ref`** mirrors the actor's point filter rather than instantiating the actor, and takes a required kwarg `std_utc_offset_hours`. Its tests use the real actor as the oracle, which guards against drift.
  - The python review must check this duplication.
- **Tape lookup** is an injected `TapeLookup` callable.
- **The `reason=` constant rule** is scoped to the sinks.
- **L-12 widening.** `AUTONOMY_FILE_WRITERS` goes from 8 to 10. `capture_reader` joins `NAUTILUS_PERMITTED`.
- **`AUT1_WRITE_AUTHORITY`** has rows only for existing modules. A module with no row is itself a finding.

**Flake noted.** `test_selftest_cli_proc_checks_report_host_view` (V18-type: `/proc/locks` must be within ±5 of the host) failed once: |165−185|. It is host-load dependent. Watch for it; do not widen the tolerance without a ruling.

## WP1-R3: python and SEC reviews of 3c44087d..685bb433. Both REQUEST_CHANGES, no blocker; all findings adopted.
- **Silent-failure and capture-guard fixes**
  - **(py H1)** `capture_epoch._offer` must never be silent. Log ERROR with the cause, count `alert_drops`, and expose `delivered` on `EpochOutcome`.
  - **(SEC M1)** `flush_for_submit` returns `flushed and drops == 0 and stream.health.ok`. `consume_drops_since_submit_flush()` moves inside the try. Test: a non-Take drop followed by a later Take refuses until `positive_control` clears health.
  - **(SEC M2)** Publisher `write`: when `stream.write` returns False, call `health.mark_failed(cause or fallback)`. Test with a fake `StreamLike` that returns False without marking.
  - **(SEC M3)** Stream `open`: the instance dir must be newly created, or existing, empty and 0700. Anything else refuses with health `open_failed`. The docstring states that same-uid is the trust boundary.
- **Forecast-ref drift**
  - **(py H2 + M3/M4)** Keep the mirror: no edit to the live FQ actor. Import `NBP_QUANTILE_MODEL` from `forecast_subscriber`. Add `test_foreign_model_and_foreign_variable_points_are_skipped_as_fq_skips_them`, with the real actor as oracle and three cases: foreign model, foreign variable, unserved station. Mutation M5 (model-filter delete) must die.
- **Publisher logging and dedupe**
  - **(py M5)** `CAPTURE_PUBLISH_FAILED` logs only when a window opens. `_close_window` logs the suppressed count.
  - **(py M6)** A flush failure dedupes under its own cause (`flush`), never under a stale `health.cause`.
- **Reader exceptions**
  - **(py M7 + SEC L4)** The reader has one failure type. Decoder, schema-drift, `AttributeError`, `IndexError` and `InvalidOperation` all wrap to `CaptureProjectionError`. Test each with a crafted row.
- **Low-severity fixes**
  - **(SEC L5)** Set `repr=False` on `CaptureStream.order_filled`.
  - **(SEC L7)** Closure lint forbids `eval`, `exec`, `compile`, `sys.modules`, the builtin-`open` alias and the `builtins.open` reference. Each gets a planted case.
  - **(SEC L8)** `test_autonomy_contracts` keeps the `breezy.domain` and pyarrow assertions for `NAUTILUS_PERMITTED` modules and skips only the nautilus-free assertion.
  - **(py L9, L10)** Add a comment on dedupe-before-write. Note "Linux-only `/proc/self/fd`" in the reader docstring.
- **Noted, no action**
  - **(SEC L9)** X1 was red at base `3c44087d` (the gate WP0 failure). This is already recorded.
  - **(py L8)** Split `capture_reader` views and joins before the next growth (currently 737 lines).

## WP2 (062dad8f) and the WP1+WP3 integration
- **Integration failures.** Gate WP1 on 26571a46 (WP1 rebased onto the merged WP3 step 1) ended `phase1 rc=1`. Six tests failed, all from WP3 modules meeting WP1's scans for the first time:
  - two closure-lint tests;
  - `test_every_envelope_node_id_collected_and_unskipped`;
  - `test_static_walk_positive_and_negative_controls`;
  - two `test_autonomy_files_one_writer` tests.
- **WP2-R1 (pending-WP7 test).** Accepted: `tests/unit/autonomy/pending_wp7_capture_guard_subclass.py` is not collected by default, and run by path it fails. There is no xfail and no skip.
  - WP7 obligation: rename it into the collected file, and it must turn GREEN in WP7's own merge.
  - The evidence file records it.
- **WP2-R2 (`reason=` lint workaround REJECTED).** Routing a copied reason through a field dict to dodge the constant rule is laundering.
  - Fix: narrow the lint. A `reason=` keyword whose value is an attribute read (`<name>.reason`) from a value typed as a capture decision/refusal object is accepted only at enumerated (file, function) sites. Each site has a test, with planted controls showing that an arbitrary expression is still flagged.
  - Then pass `reason=` directly.
- **WP2-R3 (accepted).**
  - `CaptureIdentity` lives in `guarded_strategy.py`.
  - The adapter has `capture` and `follow_up` and publishes, per CS-1.
  - `FqNodePlugin` is not in `NODE_PLUGINS`; registering it is WP7/WP8.
  - The exit exemption is SELL-only.
  - Each refused order list produces one detector event.
  - Guard CRITICALs use event `CAPTURE_REFUSED` with the cause in `detail` (§3.16).
  - Forecast station is `ctx.station`.
- **WP2-R4 (frame body shape is now binding for WP5 leg B).**
  - Depth: `{ts_event, bids:[[px,sz]], asks:[[px,sz]]}`, with zero-size pad levels dropped.
  - Quote: `{ask, bid, ts_event}`.
- **WP2-R5 (WP3 rows in `AUT1_WRITE_AUTHORITY`).** The `capture_recorder_hook_cli` scopes `_open_child_dir`, `_write_once`, `_atomic_replace` and `_acquire_lock` are confirmed against WP3-R3. Those are the hook's only write sites, and they are reviewed.
- **WP2-R6: SEC and python review of 26571a46..232d06bc. APPROVE; all mediums and lows adopted before merge.**
  - **(M1) Exits are never refused.** The exit and untagged-SELL branch of `_admit` is wrapped in `try/except Exception`. On failure it counts, logs a constant cause, and admits the order. BUY stays fail-closed. Test: a raising `make_record` or `canonical_json` on an exit still submits.
  - **(M2) §3.6.5 send-path test.** Calling `close_position` / `close_all_positions` on an untagged BUY that closes a short must be refused by the guard. This pins the Nautilus 1.231.0 `cpdef` dispatch at `strategy.pyx:1416`. `modify_order` is covered as well.
  - **(L3)** `FollowUp.__post_init__` validates `reason` against the closed set: `VetoReason` values plus the `REASON_*` constants.
  - **(L4)** `REASON_COPY_SITES` pins the receiver name too (`decision`, `outcome`), not only the function. A planted control uses another name at the same site.
  - **WP7 note:** test the linkage between a tag and the Take record it refers to. Today the guard checks tag format only, per §3.6.2.
