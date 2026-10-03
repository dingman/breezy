# ARCH Rev 9.2 errata (binding on every area plan; the frozen ARCH text is not edited)

Freeze: Rev 9.2, sha 1b288d0e0172b233b791d875845e8002824a52d4a2e7819685ec0f2057572f42.
Scores: architect 97, trading-bot-architect 96, security-reviewer 96. Lowest is 96; zero CRITICAL and zero HIGH.

- **E-1 (architect, MEDIUM): outbox claim order.** First `os.utime` stamps the claim time on the entry. Then an atomic rename into `outbox/claimed/<drainer>/` claims it; the losing renamer gets ENOENT. Never rename then utime. AUT-6 implements this with a concurrency test.
- **E-2 (security, LOW)**: A halt mirror written before the 16:45Z pass starts (for example by the 16:41Z reconcile) is stale by construction for the ROOT_ADMIT check.
- **E-3 (architect, LOW)**: The Rev 9.2 change tags Z1–Z9 are read as `R9.2-Z1…Z9`. Earlier Z labels keep their original meaning.
- **E-4 (security, LOW)**: The failed-canary text belongs under §4.6.

- **E-5 (coordinator, from the AUT-7 r4 architect review H-1; peer-reviewed in the AUT-7 r5 review): restorative RESUME after a failed drill close.**
  - **Trigger:** the drill's closing ROLLBACK fails, leaving the incumbent root HALTED with `ROLLBACK_FAILED` and `trigger_cause_class=DRILL`.
  - **Action:** the 16:45Z pass may write a **restorative RESUME** of that incumbent root, `cause=drill_close_restore`.
  - **Conditions:**
    - The incumbent's artefact and manifest shas re-verify byte-identical.
    - No accepted non-DRILL cause and no exec-store halt names it since the drill's DRILL_PROMOTE.
    - §4.4 preconditions hold.
    - At most one per venue per day, enforced by the store (`drill_close_restores`).
  - **Budgets:** it is charged to NO drill counter and to no production resume budget.
  - **Never:** it never applies to the drill child and never applies after a genuine fault.
  - **Rationale:** the closing step is restorative. A budget must not strand the production incumbent; the venue would otherwise have no sender for ~28 days.

- **E-6 (coordinator, from the AUT-5 r3 reviews R-1 and trading D4; peer-reviewed in the AUT-5 r4 review): the one-time L1 bootstrap.**
  - **What runs:** the single BOOTSTRAP write at the L1 cut-over runs in the STOP→LAUNCH gap as a transient unit, `systemd-run --user --on-calendar='<D> 16:40:05 UTC'`, with `flock -w 10` on the engine lock and `TimeoutStartSec=60`. It never runs as a hand-timed command.
  - **Launch-window table:** it is listed as a one-time row, ending ≤16:41:15Z, before the 16:42:30 intraday pass.
  - **Recurrence:** it never recurs, and the store refuses a second BOOTSTRAP per venue.

## E-7: user-unit mount sandboxing is not enforced on this host

Status: ADOPTED 2026-10-03. Peer-reviewed by security-reviewer (ENDORSE-WITH-AMENDMENTS) and architect (ENDORSE-WITH-AMENDMENTS). Draft and evidence: `E-7-DRAFT.md`.

**Evidence**
- `systemd-run --user -p ReadOnlyPaths=` does not enforce: `touch` succeeds inside the unit.
- `kernel.apparmor_restrict_unprivileged_userns=1`.
- `bwrap --ro-bind` does enforce; the write fails with EROFS.
- `/proc/<pid>/root` escape attempts under bwrap are denied.

**Rules**
1. **Directives are configuration, not controls.** `ReadOnlyPaths`, `ReadWritePaths`, `ProtectHome`, `ProtectSystem`, `PrivateTmp` and `InaccessiblePaths` are configuration only.
   - No plan counts them as enforcement.
   - Tests that parse them are named `*_config_*`.
   - The claim that `ProtectHome` is also a no-op is probable but unverified.
2. **Every unit ARCH grants `ReadWritePaths` runs under bwrap.** This covers two units:
   - The AUT-5 engine binds `registry/`, `evidence/` (including `evidence/alerts`, and `registry/drill/` for AUT-7) and its E-8 cache dir.
   - The AUT-6 `DEMAND_WRITER_PRODUCER_IDS` producers bind only `registry/demand/` and `evidence/alerts`.

   The bwrap invocation is the same for both:
   - Mounts: `--ro-bind / /`, the `--bind` set above, `--dev /dev`, `--proc /proc`.
   - Isolation: `--unshare-pid`, `--new-session`, `--die-with-parent`.
   - Credentials: `--tmpfs ~/.config`, then re-`--ro-bind` only the non-credential files the unit needs. `~/.config/breezy` venue credentials are never visible.
   - Network stays on for outbox delivery. The unit has no import path to the venue adapters, enforced by an import-closure test. NO-SEND is unchanged.

   At start, a self-probe checks both directions:
   - `O_WRONLY|O_CREAT` under `state/` must FAIL.
   - The same open under its own bind (positive control) must SUCCEED.
   
   Otherwise the unit exits INTEGRITY with a delivered CRITICAL.

   Operator CLIs remain a stated residual.
3. **Code-level read-only applies to every other autonomy reader.**
   - SQLite readers use `file:…?mode=ro` with `PRAGMA query_only=ON`. The exception is the engine's exec-store read, which uses E-8.
   - Files are opened `O_RDONLY`.
   - The node's `ReadOnlyPaths` on `registry/` becomes configuration only. The node is never wrapped, and its watch-actor closure is under the AST test.
   - The AST closure test fails on any of these outside the unit's one-writer rows:
     - write-mode `open`
     - `sqlite3.connect` without `mode=ro`
     - `SqliteStateStore(`
     - `subprocess`, `os.system`, `ctypes`, `importlib`

     Every write-authority unit is listed in one table.
4. **What enforces the one-writer property.** bwrap confines only the wrapped units. Against all other same-uid units, the one-writer property rests on the AST closure test plus ARCH's stated residual, and is never described as enforced.

## E-8: engine read of the exec store at 16:45Z

Status: ADOPTED 2026-10-03, peer-reviewed as above. Experiments E1–E3 pass under bwrap.

Only the 16:45 pre-launch pass takes the intent flock. Steps:
1. Open `exec_polymarket_us.sqlite.intent.lock` with `O_RDONLY|O_CLOEXEC`.
2. Take `flock(LOCK_EX|LOCK_NB)`. Never block; retry up to 3 times, 5 s apart.
3. Fingerprint the db, `-wal` and `-journal` as (inode, size, mtime_ns).
4. Copy the db, `-wal` and `-journal` into the 0700 cache dir. Never copy `-shm`.
5. Re-fingerprint. On any change, retry.
6. Release the flock by 16:48:00 at the latest; otherwise record a read failure. A deadline test covers this, and it keeps the 16:50 `_do_launch` intent-lock check clear.
7. Open the copy read-write and run `quick_check`.
8. Read the halt keys and `exec/polymarket_us/intent/current` from the one copy. Decode with the shared `SubmitIntent` decode extracted from `probe_open_intent`.
9. Delete the copy.

Fail-closed rules:
- These count as a read failure, which fails closed: lock held after retries, lock file missing, fingerprint unstable, or `quick_check` failing.
- **Blocking states:** OPEN or `SubmitIntentCorrupt`. `SubmitIntentState` has no AMBIGUOUS member. An absent record does not block.

Other readers and residuals:
- Readers that are not wrapped, such as AUT-2 at 16:41, keep the G6 URI.
- Node-up reads inside bwrap (the advisory 15:30 read) are advisory only and never count toward H.
- The unlocked supervisor write at `trade_supervisor.py:2418` (17:05Z) falls outside the window, and the re-fingerprint guards against it.
- `intent_lock_is_free` is NOT changed (YAGNI; the supervisor is not wrapped, and adoption requires `node_pid == holder`).

This supersedes the AUT-5 r4 `immutable=1` workaround.

Tests:
- `test_exec_snapshot_recovers_stale_wal_after_sigkill`
- `test_exec_snapshot_never_copies_shm`
- `test_exec_snapshot_holds_intent_flock_readonly_fd`
- `test_exec_snapshot_fingerprint_change_retries_then_read_failure`
- `test_exec_snapshot_halt_and_intent_from_one_copy`
- `test_exec_snapshot_missing_lock_file_fails_closed`
- `test_exec_snapshot_releases_by_164800`

## E-7/E-8 consumption by plan

| Plan | E-7 | E-8 |
|---|---|---|
| AUT-3 r6 | Build item: AST read-only test | — |
| AUT-4 r6 | Build item: AST test; rename sandbox-parse tests to `*_config_*` | — |
| AUT-7 r5 | Build item: inherits the engine bwrap; `registry/drill/` in its bind set | Build item: the 16:45 open-intent read uses the E-8 copy, never `probe_open_intent`'s read-write store |
| AUT-2 r7 | Build item: AST read-only test | Keeps the G6 URI and never takes the intent flock |
| AUT-1 | AST test (r8) | — |
| AUT-5 | Owns bwrap and the self-probe (r5) | Owns E-8 (r5) |
| AUT-6 | Demand producers under bwrap; remove the `ReadOnlyPaths` control claims (r8) | — |

## E-9: `TimeoutStartSec` re-arms for each `ExecStart=` command
- **Status:** ADOPTED 2026-10-03.
- **Evidence:** measured by the AUT-6 r9 planner with scratch units on systemd 259.
  - Two `sleep 4` lines under `TimeoutStartSec=5` passed in 8.05 s.
  - With lines of 4 s and 7 s, the unit timed out 5.19 s into the second line.
- **Rule:**
  - A oneshot's worst-case end is the sum of the per-command bounds, plus `ExecStartPre`, plus `TimeoutStopSec`. It is not `TimeoutStartSec`.
  - Every unit with more than one start command must do both of the following:
    - Bound each command with an external `timeout -k`.
    - Compute its worst case from those bounds.
  - Every AUT plan's slot arithmetic uses this rule.
- **Applies to:** a binding build item for every plan. The READY plans (AUT-1, AUT-2, AUT-3, AUT-4, AUT-7) state no multi-command oneshot. Their WP briefs must re-check any `ExecStartPre` or extra `ExecStart` that is added at build time.

## E-10 (coordinator, 2026-10-03; from AUT-5 r7 reviews): two timing readings
- **(a) E-6's `TimeoutStartSec=60`.** The unit sets the literal 60. The wrapper's `timeout -k` (46 s) is the real per-command bound under E-9. Lower per-command bounds inside the 60 s budget comply.
- **(b) The 16:47:30 intraday pass.** When it times out waiting on the lock, it may end at 16:48:01. ARCH's 16:47:50 is replaced by 16:48:01, which is still before the 16:49:00 pre-launch end and the 16:50 LAUNCH. Its worst case is ≤16:49:50.

## E-7a — bwrap every autonomy unit; the AST closure test becomes a lint
Adopted 2026-10-03. Peer-reviewed by architect and security-reviewer, both ENDORSE-WITH-AMENDMENTS; the amendments are merged below. Draft: `E-7a-DRAFT.md`.

### Rule 1: bwrap every autonomy-owned unit
Every autonomy-owned unit runs under one shared wrapper, `deploy/systemd/breezy-autonomy-bwrap`. This includes notifiers and every `OnFailure=` target.
- **Write scope.** Each unit gets `--ro-bind / /`, plus `--bind` on exactly the output dirs listed for it in one table, `AUTONOMY_BWRAP_TABLE`. It also gets the E-7 credentials tmpfs and a self-probe whose negative paths are derived from the table.
- **Wrapper hardening.** The wrapper:
  - resolves its row by unit name and fails closed on an unknown name, with no default row;
  - validates every bind as absolute, existing and free of `..`;
  - runs `exec bwrap --die-with-parent` with no shell interpolation;
  - is a read-only file outside every bind.
- **Tests:**
  - every `breezy-autonomy-*` ExecStart and every `OnFailure=` target goes through the wrapper;
  - an EXDEV positive control.
- **Same-bind rule.** A unit's temp file and final name sit in the same bind.
- **Lock order.** `timeout -k` → `flock -w` → wrapper, or the lock file is pre-created and opened `O_RDONLY`.
- **Notifier fallback.** If bwrap fails to start, the notifier still delivers. Wrapper exit 126/127 is surfaced to the alert path.

### Rule 2: exceptions, kept in the table
- **AUT-2 `reconcile-poststop`.** It keeps GET-only egress and its `EnvironmentFile`. It is exempt only for `venue_positions_read` from the venue-adapter import-closure rule.
- **AUT-3 refit and `reproduce-pm`** (`Type=notify` + `WatchdogSec`). These need `NotifyAccess=all`.
- **`/proc/locks` and `/proc/<pid>` consumers.** These are `aut6.health` and the AUT-6 evaluate stage. They drop `--unshare-pid`, and the table names the exception. A test fails if a wrapped unit's code references `/proc/locks` while its row has `unshare_pid=true`.

### Rule 3: WAL readers
A wrapped unit never opens a live WAL-mode db read-only in place. Under bwrap the result depends on whether sidecars exist: verified, `mode=ro` fails when sidecars are absent, and `immutable=1` loses committed WAL rows.
- **How to read.** Every WAL read under bwrap uses the shared E-8 snapshot helper: copy the db and `-wal` (never `-shm`) into the unit's private cache, under a fingerprint-stable retry, then open the copy.
- **Locking.** The intent-flock step applies only to the exec store.
- **Tests:** "sidecars present" and "sidecars absent", both under bwrap.
- **Rollback-journal stores** (the C5 registry) are unaffected.

### Rule 4: the AST closure test is a lint
The test becomes a defence-in-depth lint with three requirements:
- non-vacuous, with a minimum number of judged call sites per entry point;
- positive controls;
- green at build.

Its completeness is not a READY criterion once the Rule 1 wrapper test passes.

### Rule 5: residual and timing
- **Residual.** These are out of scope and stated as residual:
  - the node, including the in-node AUT-1 capture writers and watch actor;
  - the supervisor, recorder, ingest and operator CLIs;
  - `/proc/<pid>` visibility between same-uid units that lack `--unshare-pid`.
- **E-9 timing.** The wrapper is an ExecStart prefix that adds about 10–50 ms of setup. Timeout sums are re-checked, not re-derived.

### Not part of E-7a: O_TMPFILE
O_TMPFILE is a separate item. The primary data root is on ext4 (`findmnt -no FSTYPE -T ~/.local/share/breezy` → ext4), and O_TMPFILE works there. Plans keep their fallback until WP verify-first repeats the check on the production tree.

### Consumption
| Plan | How E-7a is consumed |
|---|---|
| AUT-1 r8, AUT-2 r7, AUT-3 r6, AUT-4 r6, AUT-7 r5 | Binding build item, with the Rule 2 exceptions already in this erratum. |
| AUT-5 r7 | Binding build item. Coordinator ruling: the engine's bwrap invocation and self-probe are already specified under E-7, so moving them into the shared table is mechanical. The architect recommended a revision; I overrode that because no plan-level decision changes. |
| AUT-6 | Revision r11. |

## E-8a: the shared snapshot helper's API, and node-up exec-store reads
Coordinator ruling, 2026-10-03, from the AUT-6 r11 review.

- **API.** The E-8 helper takes three parameters: `cache_dir`, `take_flock: bool`, and `lock_path`.
  - `take_flock=True` is allowed only for the AUT-5 16:45 pre-launch pass.
  - Every other reader passes `take_flock=False`. That covers every node-up read, including AUT-6's.
  - Those readers rely on the fingerprint-stable retry alone. Their results are **advisory**, consistent with E-8's "node-up reads are advisory": a result never counts toward H and never authorises a widening.
  - E-7a rule 3's "intent-flock step applies to the exec store" means the AUT-5 pre-launch pass only.
- **AUT-5 r7.** Binding build item: add the parameters and a test for each mode.

## E-7b: venue-adapter import closure for offline replay children (coordinator ruling, 2026-10-03, AUT-4 r7 O-1)

AUT-4's `eval-offline` replay children run `run_live_parity`, which imports `breezy.adapters.polymarket_us.symbology`.

**(a) Required first:** WP1 measures the replay closure. Pure symbology and slug helpers move into an adapter-free module, with delegating shims, following the AUT-6 AF1 precedent. The closure test then passes with no exception.

**(b) Permitted only if the WP1 measurement shows the replay needs non-exec adapter modules** (for example, instrument definitions consumed by the native `BacktestEngine`):
- grant a named E-7a rule-2 exception on the `eval-offline` row only;
- scope it to the measured non-exec modules;
- guard it with `test_eval_offline_closure_has_no_adapter_exec_module` (no `breezy.adapters.polymarket_us.exec*` module, no exec client and no HTTP or WS client in the closure).

**Rejected:** narrowing the E-7 rule generally. This is consistent with the AUT-6 AF1 ruling.

## E-7c: scratch space under the shared bwrap wrapper (coordinator, 2026-10-03, from the AUT-4 r7 MLE review)

- The rule-1 invocation `--ro-bind / /` leaves `/tmp` read-only. Nautilus, pyarrow and `tempfile` scratch writes therefore fail.
- The shared wrapper always adds `--tmpfs /tmp` and sets `TMPDIR=/tmp` for every row. This scratch space is private, discarded at exit, and never a write path for durable state.
- Test: `test_bwrap_wrapper_provides_private_tmp` must confirm all of the following:
  - a write under `/tmp` succeeds;
  - the file is not visible on the host;
  - the state paths still return EROFS.
- Applies to every plan as a binding build item.

## E-11: SELF_HEAL is realised natively by systemd (coordinator, 2026-10-03, from AUT-6 r14/r15)

- **Adopted text.** The exact replacement text is the eight items ER-1..ER-8 in `AUT-6-drift-health_plan_r15.md` §ERRATA-REQUEST, as amended in r15 (ER-1, ER-5, plus the consequential ER-2, ER-3, ER-7, ER-8). Both blind reviewers voted ADOPT: TBA 96 and SFH 95.
- **Substance.**
  - SELF_HEAL is systemd's own `Type=notify` + `WatchdogSec` + `Restart=` on watchdog + `StartLimit*` + `OnFailure=`.
  - A member sends `WATCHDOG=1` only while its liveness counter advances.
  - No autonomy module issues a `systemctl` restart, start or stop.
  - The AUT-6 notifier pages any state it cannot prove is a pending restart.
  - The recorder's incident-backed `StartLimitIntervalSec=0` is a recorded exception. It is bounded by restart backoff, gets a per-kill page via `OnFailure=`, and gets one storm page after 3 kills in a trading day.
  - The launch-window deferral is journaled and alerts WARN once per deferred stall.
- **Dedupe.** E-11 is the single vehicle for the ARCH §4.5/§4.6 SELF_HEAL wording. AUT-1's ER-8 is reduced to recorder-unit-only text.
- **Consumption.** AUT-6 r15, and AUT-1 r10 (recorder side: X-1..X-7 in `reviews/AUT-6-r14-merged.md`).

## E-12: AUT-1 native-first capture (coordinator, 2026-10-03, from AUT-1 r9–r12)

- **Adopted text.** ER-1..ER-10 of `AUT-1-data-capture_plan_r12.md` §ERRATA-REQUEST, exactly as written there. Verdicts:
  - ER-1..ER-7 and ER-10: ADOPT, or AMEND with the amendment already applied.
  - ER-7 includes the per-type and per-write size-delta checks.
  - ER-8 is REDUCED to recorder-unit-only text. The ping source runs from process start; there is a journal cross-check (leg W); E-11 is the vehicle for SELF_HEAL.
  - ER-9 is AMENDED. Its final clause reads: "…recorder and feed stall observations (the recorder's process-level heal is systemd's own watchdog, per §4.6 as amended by E-11; AUT-6 pages and does not restart)".
- **Substance.**
  - C1 is realised by a native `StreamingFeatherWriter` owned by the capture actor (option B), behind a catch-all wrapper.
  - The record types are `@customdataclass` types. No record type has an `instrument_id` field.
  - `ForecastPoint` is streamed natively, and records reference it by `(station, cycle_ns, available_at_ns)`.
  - Frames are referenced in the recorder tape. A Take-path record copies its frame.
  - The payload store, the JSONL writer, FrameClock and the custom watch/watchdog are removed.
  - Loss is bounded at about 61 s (60 s heartbeat plus 1 s flush) and is counted against `SHADOW_DECISION`.
- **Consumption.** AUT-1 r12. AUT-6 r15 build item 7 is consistent.

## E-13: E-7c tmpfs size and the E-7b(a) symbology waiver (coordinator, 2026-10-03, from AUT-4 r9–r11)

- **Adopted text.** ER-1 and ER-2 from `AUT-4-evaluation_plan_r11.md`. Both reviewers voted ADOPT.
- **ER-1 (E-7c).** The shared wrapper passes `--size` before `--tmpfs /tmp`.
  - A row that sets an explicit per-row `tmpfs_size_bytes` gets that size; AUT-4's rows set it explicitly.
  - Any other row gets the wrapper's default cap, so other plans' rows never break.
  - A malformed value fails closed, and a named test covers it.
- **ER-2 (E-7b(a)).** The symbology move is waived when the WP1 measurement shows it buys nothing, because the closure still reaches symbology via `fees`, `parsing` and `symbology`. The waiver:
  - applies to the eval-offline row only;
  - requires the WP1 measurement and the (b) guard tests to be green;
  - never reaches `order_enablement` or `exec*`;
  - does not waive (b)'s "needs" condition.


## E-7d (coordinator, 2026-10-03, from ARCH-0 seam B r5): the gate runs real-namespace tests in an un-nested second phase.
- **Evidence.** Nested bwrap inside the gate fails ("No permissions to create a new namespace", apparmor `bwrap-userns-restrict`), while one level works. On pytest 9.1.1:
  - a `-p` plugin's `pytest_load_initial_conftests` runs before any conftest import and can exit rc 2;
  - `pytest_ignore_collect` keeps non-registry conftests and modules unimported;
  - a `-p` plugin also named in `pytest_plugins` loads once;
  - `PYTEST_PLUGINS` imports its module before the early hook;
  - `-p no:<plugin>` blocks a `-p` plugin.

  With the blocker and four conftest edits, the phase-2 parent loaded no `nautilus_trader*` or `breezy.adapters*` module.
- **Rule 1: one gate, two phases.** `scripts/ci/run_tests_no_egress.sh` remains the gate.
  - Phase 1 is the existing egress-blocked pytest, run with `-p tests.support.bwrap_host_phase`, selected by one `if bwrap / elif unshare / else exit 3` chain and run exactly once.
  - Phase 2 then runs un-nested. The gate prints both exit codes and exits with the first non-zero.
  - Phase 2 is omitted only when an exact argument token is `--collect-only`, `--co` or `--collectonly` **and** the mode-0600 confirm file that the script created with `mktemp` under the gate dir reads exactly `collect-only`. Phase 1's plugin writes that file from pytest's parsed `collectonly` option.
  - A missing, empty or `run` confirm file runs phase 2, so disabling the plugin by any means (`--noconftest`, `-p no:…`, `PYTEST_ADDOPTS`) cannot skip phase 2. A token claim while pytest is not in collect-only mode exits rc 2.
  - On a host where only `unshare` works, phase 1 runs and phase 2 refuses with rc 3, so the gate is red there by design.
  - Phase 2's basetemp is a fresh `mktemp -d` under the gate dir; it and the confirm file are removed on exit.
- **Rule 2: what phase 2 runs.**
  - Exactly `tests.support.bwrap_host_phase.BWRAP_HOST_TEST_FILES` with `-m bwrap_host`. The set is exact and equals the AST-derived set of marker users.
  - The passed count must equal the mutation-pinned literal `BWRAP_HOST_EXPECTED_TESTS`. A plan adding a real-namespace test widens both in the same commit (L-12).
  - Phase 1 skips `bwrap_host` items with a reason naming phase 2. In phase 2, any skip, any item outside the set, or a count mismatch fails the session.
  - The first merge ships a self-contained witness file as the only member.
- **Rule 3: prevention in the parent.**
  - Phase 2 runs with `BREEZY_BWRAP_HOST_PHASE=1` and `-p tests.support.bwrap_host_phase`, under `env -u` of `BREEZY_TEST_OS_EGRESS_BLOCK`, `BREEZY_GATE_COLLECT_ONLY_CLAIM`, `BREEZY_GATE_COLLECT_ONLY_CONFIRM_FILE`, `PYTEST_PLUGINS` and `PYTEST_ADDOPTS`. User arguments are never forwarded.
  - The plugin puts a meta-path blocker at `sys.meta_path[0]` before any conftest loads. The blocker refuses `nautilus_trader*`, `breezy.adapters*` and the module of every `find_execution_egress_modules()` hit.
- **Rule 4: N2, widened as an exact set.** `execution_egress_abort_reason` gains one keyword-only input; when it is absent, the rule is unchanged. An unattested session is admitted only if:
  - (1) the variable is exactly `"1"`;
  - (2) the attestation is absent;
  - (3) the blocker (exact class) is at `meta_path[0]`;
  - (4) every egress hit maps to a refused module;
  - (5) no refused module is loaded;
  - (6) the plugin was loaded with `-p`, and before any conftest import it found every positional argument inside the registry, no option that widens collection (`--rootdir` other than the repo, `--confcutdir`, `--noconftest`, `--pyargs`, `-c`/`--config-file`, a non-default `--import-mode`, or any `-p` beyond the plugin, `no:randomly` and `no:cacheprovider`), and neither `PYTEST_PLUGINS` nor `PYTEST_ADDOPTS` in the environment;
  - (7) `pytest_ignore_collect` excludes every non-registry file and every directory that is not an ancestor of one.

  Anything else aborts with rc 2. A variable set to any other value, including `""`, `"true"` or `"1 "`, aborts with rc 2; this differs from today only when the variable is set. Attested plus the phase variable aborts with rc 2. The credential gate runs first and is unchanged. The session end re-checks `sys.modules`. No canary is sent in phase 2.
- **Rule 5: children and imports.** Every bwrap child a phase-2 test spawns goes through `tests/support/bwrap_harness.py`, which adds `--unshare-net` and an explicit environment. An AST lint covers the registry files and every `tests.support` module they import:
  - denied imports: `socket`, `http*`, `urllib*`, `requests`, `httpx`, `aiohttp`, `websockets`, `ctypes`, `runpy`, `nautilus_trader*`, `breezy.adapters*`, `breezy.strategy*`, and `subprocess` except in the harness;
  - denied calls: `os.exec*`, `os.spawn*`, `os.system`, `os.popen`, `os.fork`, `importlib.util.spec_from_file_location` and `SourceFileLoader`.
- **Consumer obligation.**
  - Nautilus work in a phase-2 test runs only inside a bwrap child.
  - Phase-2 files live outside `tests/unit/` and `tests/contract/`.
  - A receiver a child must reach runs inside that child's namespace.
  - A phase-1 test may start bwrap through `systemd-run --user`; such a unit runs outside the gate's network namespace, so its argv is literal, stdlib-only and imports no `breezy` module.
- **Residual.** The phase-2 parent has host network for native non-Nautilus code. Python sockets stay blocked by the conftest fixture. File-path module loading is covered by the Rule 5 lint. A `PYTEST_PLUGINS` module set by a caller who bypasses the script imports before any check; the script's scrub is the control. Phase 2 runs `python -m pytest` without `-I` because worktrees need `PYTHONPATH`; a caller-controlled `PYTHON*` variable or `sitecustomize` imports before the blocker. This is operator-controlled environment, the same exposure as phase 1.
- **Supersedes** B-R1's "Phase 2 collects `-m bwrap_host tests/`" and AUT-5 r7 l.287's verify-first branch. **Security sign-off:** ARCH-0 seam B r3 security review, YES-WITH-CONDITIONS, with C-1 and C-2 folded in above; seam B r4 security and architect reviews, ADOPT, with the r4 security N2 residual sentence added above. **Filed before** WP-B2a merges.

## E-7e (coordinator, 2026-10-03, from ARCH-0 seam B r5): ARCH-0 owns the shared wrapper, table, self-probe, bus snapshot handoff and E-8 helper.
- **Ownership.** ARCH-0 seam B owns `deploy/systemd/breezy-autonomy-bwrap`, `AUTONOMY_BWRAP_TABLE` and its validation, the self-probe, the bus snapshot handoff, the E-8 helper (`wal_snapshot`, `exec_snapshot`) and the E-7a rule-1 unit lint. They live in `src/breezy/runtime/autonomy_sandbox/`, under the forbidden contract `breezy.runtime.autonomy_sandbox ↛ nautilus_trader, breezy.adapters, breezy.strategy` (`allow_indirect_imports=false`). This is a stated deviation from ARCH §3's "types live in persistence/autonomy". AUT-5 keeps the halt and intent decode, the 16:48:00 value, the E-8 test names and its rows. In the E-7/E-8 consumption table, the AUT-5 "owns" entries move to ARCH-0.
- **(a) Write-authority allowlists.** AUT-5 r7 l.292's `exec_snapshot.py` and `sandbox_probe.py` rows are replaced by `SHARED_WRITE_SITES`, admitted only when every snapshot call passes `cache_dir=` a module-level `Final` constant of the caller.
- **(b) E-8 amendment.**
  - Fingerprint: (inode, size, `mtime_ns`) plus sha256 of db bytes 0–99, `-wal` bytes 0–31 and its last 4096, `-journal` bytes 0–511; a 20 ms quiescence wait.
  - Copy order db, `-wal`, `-journal`, fd-relative, into `snap.*` under an `O_RDONLY|O_DIRECTORY` cache-dir flock; contention gives `cache_busy`.
  - Non-advisory only if the intent flock was held throughout.
  - `take_flock=True` only in the AUT-5 16:45 pass, after the day's STOP_PRIOR decision line, with a deadline before 16:50. A STOP_PRIOR that starts during the hold refuses with one false CRITICAL and no signal (residual).
- **(c) Mount-set amendment to E-7 rule 2 and E-7a rules 1, 2 and 5.** Every row runs:
  - `--unshare-user --disable-userns --assert-userns-disabled --unshare-pid`;
  - `--ro-bind / /`, `--tmpfs /run`, `--dev /dev`;
  - `--proc /proc` except on `E7A_R2_PROC` rows, which keep `--unshare-pid` and see the host procfs read-only through the root bind (locks, status and cmdline readable; environ and root EACCES; signals to host pids ESRCH);
  - `--size N --tmpfs /tmp`;
  - `--tmpfs ~` with ro re-binds of exactly the repo, the data root, the interpreter prefix and, on `E7_FIXTURE_ROOT` rows, the alternate base;
  - the exact per-row `/run` re-binds: resolv target (`resolves_dns`), `NOTIFY_SOCKET` (`E7A_R2_NOTIFY`), `/run/user/<uid>/breezy-studies.lock` (`E7_STUDIES_LOCK`) and `$CREDENTIALS_DIRECTORY` (`E7A_R2_RECONCILE`), then `--remount-ro /run`;
  - `--bind-fd` binds after a nofollow walk, distinct from `state/` and its ancestors; `--ro-bind-fd` config; `~/.config/systemd/user` only under `E7_CONFIG_DIR`;
  - `--remount-ro ~`;
  - `--setenv TMPDIR /tmp --setenv XDG_CACHE_HOME /tmp/.cache`, `--unsetenv BREEZY_AUTONOMY_SANDBOX_DEGRADED`, and on `E7A_R2_RECONCILE` rows `--setenv <VAR> $CREDENTIALS_DIRECTORY/<name>` for each `credential_env` item. `credential_env` keys must additionally not be `PATH`, `HOME`, `TMPDIR`, `XDG_*`, `LD_*`, `PYTHON*` or `BREEZY_AUTONOMY_*`; `validate_table` rejects them.

  This replaces E-7a rule 2's "drop `--unshare-pid`". **E-7a rule 2's test sentence becomes:** "A test fails if a wrapped unit's code references `/proc/locks` or `/proc/<pid>` while its row lacks `host_proc`." **Rule:** on `E7A_R2_PROC` rows, never index `/proc` by a namespace pid (`os.getpid()`, `Popen.pid`); those name other host processes. Rule 5's `/proc/<pid>` residual narrows to read-only status and cmdline visibility. No row exposes `/run/user/<uid>/bus`, `/run/user/<uid>/systemd/private`, docker, snapd, lxd or the system bus. The unit check is integrity against misconfiguration, not an authorisation boundary. The wrapper never creates a bind source, including the studies lock.
- **(d) Self-probe amendment to E-7 rule 2.**
  - The env-row check runs before any open.
  - Negatives come from the table only, with an owned-directory precondition and exactly EROFS on `O_TMPFILE|O_WRONLY`; no named file is created under `state/`, the data root or the repo.
  - Positives are `tmpfile`/`subdir`.
  - Credential paths give ENOENT, and the home listing is ⊆ the re-binds.
  - Host and bus sockets give ENOENT; `/run` is allowlisted and read-only.
  - pid namespace: `/proc/1/comm == "bwrap"`, or on `E7A_R2_PROC` rows `/proc/self` ≠ `getpid()`. This is an integrity check, not a boundary.
  - Vocabulary: AUT-6's codes plus `env_row`, `degraded_forged`, `credentials_visible`, `user_bus_visible`, `host_socket_visible`, `run_not_private`, `run_not_readonly`, `tmp_not_private`, `pid_ns`, `negative_unverifiable`.
- **(e) Labels.** `KNOWN_EXCEPTIONS = {E7A_R2_PROC, E7A_R2_NOTIFY, E7A_R2_RECONCILE, E7B_EVAL_OFFLINE_ADAPTER_MODULES, E7_CONFIG_DIR, E7_STUDIES_LOCK, E7_FIXTURE_ROOT}`. There is no user-bus label and no bus-action label.
- **(f) Consumer changes (binding build items).**
  - **Every plan:**
    - an owned unit's `OnFailure=` names `breezy-autonomy-failed@%n.service`, never `breezy-study-failed@`. This supersedes ARCH §5.2 l.1066's `OnFailure=breezy-study-failed@` for autonomy-owned studies (E-7a rule 1); AUT-2 l.1199 is amended accordingly;
    - `resolves_dns=True` on every row that can deliver an alert, each with a test;
    - E-9 sums count every pre line at `T + K` (`TimeoutStartSec` re-arms per command), and each pre line's bound is below the unit's `TimeoutStartSec`. In the AC-5 form-1 shape (`timeout -k 1 4`, AUT-5 r7 l.259) an `install -d` line counts 5 s; the `touch` line counts 5 s; a bus-snapshot line counts `B + 5`.
  - **AUT-1 r12:**
    - l.770/939: the audit's `systemctl --user show` becomes a bus read (budget 10, a `cache/` bind; a missing snapshot is never a pass); l.768-769: journalctl in-sandbox;
    - l.731/733/741/883-884/941: the drill and guard run **unwrapped**, listed in `UNWRAPPED_RESIDUAL_UNITS` as an E-7a rule-5 residual, with no socket bind. Re-wrapping re-files with `--kill-whom=main`, the bus-snapshot directory discipline, SIGCONT on every exit path and a target set with plan:line;
    - l.875 is amended accordingly; l.1045: V-9(b) becomes the handoff;
    - l.905-906: `OnFailure=breezy-autonomy-failed@%n.service`, and the `alerts.env` re-bind is removed;
    - l.881: `flock -w %t/breezy-studies.lock`;
    - the stop-hook unit is linted on its wrapper line only; l.125/886 rotate is unchanged;
    - E-9: audit latest end 13:50 + 60 s + 15 s + 1500 s + 5 s = 14:16:20 (plus `T + K` of any `install -d` pre line, ≤ 5 s: ≤ 14:16:25) ≤ 14:25. The `flock -w 600` runs inside ExecStart's `timeout` (≤ 1500), so it is not added; AUT-1 l.881 is restated on this basis.
  - **AUT-2 r7:**
    - l.180/468: reconcile is `E7A_R2_RECONCILE` with `LoadCredential=`, `credential_names=("polymarket_us_secret_key",)` and `credential_env={"POLYMARKET_US_SECRET_KEY_FILE": "polymarket_us_secret_key"}`, and the caller passes the existing `require_key_file_mode=0o400` (`env.py:98`). The inline-key variable is absent (otherwise the loader fails closed). No `env.py` or firewall-test change is permitted. Reconcile stays GET-only (consumer test). `resolves_dns=True`.
    - l.408/953: label unit `OnFailure=breezy-autonomy-failed@%n.service`; l.1199's "The label unit keeps `OnFailure=breezy-study-failed@` (the §5.2 studies rule)" is amended to `breezy-autonomy-failed@%n.service` per "Every plan"; l.423/463/1188: the `breezy-score-live-trials` slot-guard path is unchanged (not owned).
    - l.470/485/1054: `breezy-aut2-recon-failed@` joins `NOTIFIER_FALLBACK_ROWS`.
    - l.467: `%t/breezy-studies.lock`; wrapped G6 reads use `exec_snapshot(take_flock=False)`.
  - **AUT-3 r6:**
    - l.267: `NotifyAccess=all` and `OnFailure=breezy-autonomy-failed@%n.service` on refit and both repro units;
    - l.279-283/292: `E7_STUDIES_LOCK` with `ExecStartPre=-/usr/bin/timeout -k 1 4 /usr/bin/touch %t/breezy-studies.lock` (+5 s; reproduce-am `TimeoutStartSec` 4139 → **4134**, so 09:35:00 + 1 + 5 + 4134 + 60 = 10:45:00Z, and the AM eligibility threshold becomes `runtime_s × 1.2 + 600 ≤ 4134`, i.e. `runtime_s ≤ 2945`; AUT-4's K8 test sums pre lines.)
    - l.296: the repro extract moves to `cache/refit-repro/`;
    - l.190/282-283: wrapped transients pass `--unit=<row unit>` and use the literal lock path.
  - **AUT-4 r11:**
    - l.661/1228/1401: `E7_FIXTURE_ROOT`;
    - l.848/871/888/892/898: both integration files join the registry;
    - l.875-884: `WRAPPER_CODE_FILES` and `build_bwrap_argv`;
    - l.634-635/664: `%t/breezy-studies.lock` via `flock -w` (no pre-create);
    - l.642 (K8): `test_pre_offline_studies_units_end_by_1045z` sums every pre line at `T + K`;
    - l.637/848/1311: unchanged;
    - E-13 tests are delivered by ARCH-0 at AUT-4's paths.
  - **AUT-5 r7:**
    - l.278-282: wrapper rows `breezy-autonomy-engine@<mode>` with exact instance names, the bootstrap `derived/artefacts`, and the stage-S rows;
    - l.202/286: `require_sandbox`;
    - l.277: `OnFailure=breezy-autonomy-failed@%n.service`;
    - l.284: the table-derived config test;
    - l.285/405/879-880: registry;
    - l.292: `SHARED_WRITE_SITES`;
    - l.386-388: `exec_snapshot(False)`;
    - E-8: the STOP_PRIOR-line precondition;
    - l.259/279/273-275: unchanged.
  - **AUT-6 r15:**
    - l.203-207/802/958/966: `systemctl` reads become `--bus-snapshot` with `--` before units, on new `cache/aut6_health_bus` and `cache/aut6_failed_bus` binds plus daily's `cache/aut6_daily_exec_snapshot`; budgets health 15, failed@ 10, daily 15. The health `show -p <fixed set> -- 'breezy-*'` result also lists timers and slices, so the consumer filters on `Id` ending `.service` (with a consumer test).
    - l.961-962: failed `run-*` transients through `RUN_TRANSIENT_SHOW_ARGV`.
    - Mapping: `bus_snapshot_missing`/`_stale` → health UNKNOWN (`passes_unknown_streak` increments); failed@ and daily page CRITICAL. A per-read failure keeps l.488/l.957. Tests `test_health_bus_snapshot_missing_is_unknown`, `test_failed_notifier_pages_when_bus_snapshot_missing`, `test_daily_pages_when_bus_snapshot_missing`.
    - E-9:
      - health ≤ start + `T+K`(install) + 20 + 115 + 5 s (≤ start + 145 s); **this erratum amends ARCH §5.2 l.1089 `aut6.health` to '≤ 145 s | start + 145 s'**. The 16:31/16:41/16:51/17:01 passes end ≤ +146 s from the slot, before the next slot, and the pass is read-only. `HEALTH_PASS_BUDGET_S=90` is unchanged. (ARCH l.1089 today reads "≤ 120 s | start + 120 s". AUT-6 l.1037 and l.1061 are restated to slot + 146 s, and l.1064 to 05:55:36Z / 13:25:36Z, e.g. the 16:41 pass ends ≤ 16:43:26.)
      - failed@ runs `T+K`(install) 5 s + snapshot (`timeout -k 2 13`) 15 s = ≤ 20 s before its page; AUT-6 l.1053's 'ends ≤ start + 61 s' becomes '≤ start + 81 s' (the AUT-6 owner re-derives it from the unit file via `start_phase_bound_s`).
      - daily ends ≤ 05:30:00 + 1 (accuracy) + 5 (install) + 5 (touch) + 20 (snapshot, `timeout -k 2 18`) + 1500 (ExecStart; the 300 s lock deadline is inside it) + 5 (`TimeoutStopSec`) = 05:55:36Z, and likewise ≤ 13:25:36Z, inside "ends ≤ 06:00Z and ≤ 13:30Z".
    - l.1174: V-6 expects in-row `systemctl` to fail and the snapshot to equal the outside reads.
    - l.247/250: `E7A_R2_PROC`.
    - l.249/671: `E7_STUDIES_LOCK` on `/run/user/<uid>/breezy-studies.lock` with the `touch` line and a path test; l.1071: `IN_PROCESS_STUDIES_LOCK_UNITS` derived from the table rows with `studies_lock=True`.
    - l.249/1444: `E7_CONFIG_DIR`; l.241-243/1334: home-allowlist and `/run`-set assertions; l.260-262: `O_TMPFILE` negatives.
    - l.1335-1338/1349/1356-1357/1375-1376: move to `tests/integration/test_integrity_floor_bwrap_namespace.py` (registry), with the l.1357 receiver in the child; l.1150/1228/1400: registry; l.1377/1292/2290: phase 1.
    - l.276/1046: producer-daily `OnFailure=breezy-autonomy-failed@%n.service`; l.1027: recount the multi-command units (health 2 pre lines, failed@ 2, daily 3) via `start_phase_bound_s`.
    - `breezy-autonomy-failed@` joins `NOTIFIER_FALLBACK_ROWS`.
- **(g) Notifier fallback.** Only rows in `NOTIFIER_FALLBACK_ROWS` may fall back, only after every configuration check, with a 2 s preflight. `degraded_write_target` refuses `state/` and anything outside the binds, and the consumers' closure tests enforce its use. Degraded mode exposes `~/.config/breezy` (residual).
- **(h) Bus snapshot handoff.**
  - **No bus inside any sandbox, and no state-changing bus call anywhere in ARCH-0.**
  - A row's literal `systemctl --user show|list-units|list-timers` argvs, which must follow the grammar (`-p` + one `^[A-Za-z,]+$` token; `--` before unit tokens; unit tokens `^breezy-[a-z0-9@._*-]+$` or a re-validated `{instance}`; `run-*` only as the exact `RUN_TRANSIENT_SHOW_ARGV`), run unsandboxed through `ExecStartPre=-/usr/bin/timeout -k 2 <B+3> …/breezy-autonomy-bwrap --bus-snapshot <row>` as the last pre line, with `B + 5 < TimeoutStartSec`. They run only after every wrapper configuration check.
  - A monotonic budget `B ∈ [1, 25]` bounds all reads; each read runs in its own session and is process-group killed on timeout; unstarted reads are recorded `skipped`; the file is always written.
  - The file is created through a validated `O_DIRECTORY|O_NOFOLLOW` fd on `.bus_snapshot` inside a `cache/` bind (owner, mode, device and forbidden-inode checks). It is keyed by `$INVOCATION_ID`, read and unlinked by the sandboxed step, and swept after 24 h only for regular files named `^[0-9a-f]{32}\.json$`.
  - A failed pre step never skips the main step (`-` prefix), and the main step maps a missing or stale snapshot per (f).
- **(i) Residuals.**
  - Same-uid hostile processes are out of scope.
  - `E7A_R2_PROC` rows read other same-uid processes' `/proc/<pid>/status` and `cmdline`, at parity with unwrapped (no `hidepid`).
  - Abstract unix sockets and loopback are shared, because the network namespace is shared; DNS rows reach the `127.0.0.53:53` stub.
  - The ro-bound repo exposes git-ignored repo-root files, including the operator caps file (no credential, never read).
  - `E7A_R2_RECONCILE` rows see their own loaded credential copy.
  - AUT-1's drill and guard run unwrapped (`UNWRAPPED_RESIDUAL_UNITS`).
  - The studies-lock `touch` line updates the lock's mtime; nothing depends on it.
- **Sign-off:** ARCH-0 seam B r3 security rulings (a)–(c) and (e)–(g) accepted, (d) applied by removal; architect r3 AMEND items applied; seam B r4 security and architect reviews ADOPT-WITH-AMENDMENT, with the amendments applied above (architect B-1 and B-2 verbatim, the ARCH l.1066 supersede clause, the security N1 key denylist). **Filed before** WP-B2b-1 merges.

## E-14 (coordinator, 2026-10-03; from ARCH-0 seam A r1–r5 and the r1–r4 architect and security reviews): per-family root records.
- **Defect.** ARCH C3 "Bootstrap roots" (line 261) writes one `root.json` per `derived/artefacts/<model_class>/<sha>/`. `pm_us_crh_v4` and `pm_us_crh_cont` are both `continuous_rung_hold` with `density_artefact_sha256 = 247f636350685b38966251703c47d10531913367fbcca175b086a2c298421a65` (the `not_applicable_density.json` placeholder) and both are RETIRED seeds (line 738). Their `root/v1` bodies differ in `family_id` and `manifest_sha256`, so the second write-once returns EXISTS_DIFFERENT and the genesis BOOTSTRAP cannot complete. Separately, ARCH lines 263-264 expect the committed root file to change after bootstrap, which, once the resolver binds a root to its committed bytes, leaves the venue without a sender at the next LAUNCH.
- **Rule.**
  1. A root copy is written to `derived/artefacts/<model_class>/<sha>/artefact.json` (0444) and `derived/artefacts/<model_class>/<sha>/roots/<family_id>.json` (0444, `root/v1`, fields unchanged). This replaces `<sha>/root.json` in ARCH C3 line 261, AUT-5 r7 §3.2 lines 172 and 180, and AUT-7 r5 line 41 and `test_rollback_to_root_reads_content_addressed_copy` (line 569).
  2. A root copy's model class is `f"{composition_kind}:{ROOT_ARTEFACT_COMPONENT}"` with `pins.ROOT_ARTEFACT_COMPONENT = "density_table"`; a root's artefact is its manifest's density artefact.
  3. **Scope: families whose introducing row is BOOTSTRAP or ROOT_ADMIT with `lineage_root_family_id == family_id` ("roots"), whatever the authorising kind (BOOTSTRAP, ROOT_ADMIT, ROLLBACK, RESUME).** A family introduced by any other kind, or a BOOTSTRAP/ROOT_ADMIT row with `lineage_root_family_id != family_id`, invalidates the chain. For a root the resolver (a) reads the manifest only from `deploy/families/<family_id>.json` in the repo (never a registry copy) and refuses `manifest_sha_mismatch` unless its sha256 equals `row.manifest_sha256`; (b) reads `roots/<row.family_id>.json` and refuses `root_record_mismatch` unless `record.family_id == row.family_id`, `record.manifest_sha256 == row.manifest_sha256`, `record.artefact_sha256 == row.artefact_sha256`, and `record.committed_path == "deploy/families/" + family_id + ".json"` exactly. Children are out of scope: a Y2 no-new-lineage child resolves `artefact.json` in the existing `<sha>/` directory and has no `roots/` record; a new-lineage child is bound by its C3 `lineage.json`.
  4. A second root sharing a `<sha>` directory writes `artefact.json` as an EXISTS_EQUAL no-op. EXISTS_DIFFERENT on `artefact.json` or on a `roots/<family_id>.json` is INTEGRITY.
  5. The `<sha>/` and `roots/` directories become 0500 after the genesis transaction's last copy. This is hygiene, not a control (same-uid residual). A new file in a 0500 directory is refused by mode bit (`DIR_NOT_WRITABLE`), so AUT-3 refits write `artefact.json` and `lineage.json` into a fresh `<sha>/` only, never into a root's directory.
  6. **Order and idempotence.** Every copy is written before the genesis BOOTSTRAP COMMIT. A crash and rerun is idempotent: an existing file with equal bytes is EXISTS_EQUAL, decided by reading it before any temp file is created, so a rerun succeeds even after the rule-5 chmod.
  7. **Frozen committed root bytes.** Once a root is bootstrapped or root-admitted on any registry root (production or shadow), its `deploy/families/<family_id>.json` bytes are frozen. `pins.BOOTSTRAPPED_ROOT_MANIFEST_SHA256` (a `MappingProxyType` of `family_id → sha256`, empty until the reviewed pins commit that precedes the first bootstrap, which lists every `BOOTSTRAP_SEED` id; a ROOT_ADMIT adds its row in the same commit as its allowlist triple) pins them. Rows are append-only. `test_bootstrapped_root_manifests_unchanged` fails CI on any edit, so the failure lands at merge rather than at LAUNCH. Superseding a bootstrapped root, including setting `terminal_climate_day`, is done in the registry (RETIRE) or by a new root (a new `family_id` through ROOT_ADMIT), never by editing the committed file. **Clearing path (L-48)** if an edit reaches a running tree anyway (resolver `manifest_sha_mismatch`, no sender, entries vetoed): a reviewed revert restoring the pinned bytes, or ROOT_ADMIT of a new root. ARCH lines 263-264 ("even if the repo file changes") are refined accordingly: ROLLBACK to a root still reads the store artefact, but the root's committed manifest bytes must equal the row. **[r5]** Until ROOT_ADMIT is enabled (it is not at L1), the reviewed revert is the only clearing path, and from the stage-S bootstrap onward the live `forecast_quantile_ladder` root manifest is frozen; the CI pin test is hygiene, and the runtime anchor is the resolver's `manifest_sha_mismatch`.
- **Consumption.** ARCH-0 seam A (`paths.root_record`, `family_bytes.write_root_copy`, the resolver, `pins.BOOTSTRAPPED_ROOT_MANIFEST_SHA256`, `single_read` `DIR_NOT_WRITABLE`); AUT-5a bootstrap and the pre-bootstrap pins commit; AUT-7 r5 root reads; AUT-3 refit destinations. Fail-closed until filed: BOOTSTRAP refuses and nothing goes live.

**Plan amendments recorded with E-14.** The complete list of ARCH and consumer-plan text that ARCH-0 seam A amends is `ARCH-0-seamA_plan_r5.md` §ERRATA-REQUEST (b) items 1–46, as modified by that plan's "Coordinator amendments to r5" (A6-R1, A6-R2). Consumer plans read those items as binding alongside this erratum.

## E-15 (coordinator, 2026-10-03; from the ARCH-0 seam B WP-B2b-2 security review): per-row network namespace
- **Finding.** The autonomy bwrap argv shares the host net namespace on every row. That leaves abstract AF_UNIX sockets (dbus, X), which `/run` masking cannot hide, and all egress reachable from every wrapped unit.
- **Ruling.** ARCH-0 seam B adds `--unshare-ipc/-uts/-cgroup-try` (B6-R8) but does not decide network policy. Each consumer plan that adds a row (AUT-1, AUT-2, AUT-5a, AUT-6) must state, per row, whether it needs network egress. Rows that need none get `--unshare-net` through a new required row field. AF_UNIX path sockets such as NOTIFY_SOCKET stay reachable through their binds. The field and its argv emission land in the first consumer WP that adds a non-egress row.
- **Fail-closed reading.** Until a row declares the field, a reviewer treats a missing declaration as a review blocker for that row.
