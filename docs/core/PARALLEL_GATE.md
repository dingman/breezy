# Parallel full gate

**The serial gate stays the reference.** `scripts/ci/run_tests_no_egress.sh` with no
sharding is the gate whose green result gates merges and activation. The parallel gate
(`scripts/ci/run_tests_parallel.sh`) is an accelerator for the edit-test loop; a parallel
green is strong evidence, never a substitute. Nothing in the parallel path changes how the
serial gate, `run_tier.sh`, `run_t1_lanes.sh` or `tier_lanes.py` behave (byte-identical to
the commit before this one; pinned by a test).

## Use

```
cd <tree> && PYTHONPATH=<tree>/src:<tree> \
  scripts/ci/run_tests_parallel.sh --run-dir <tree>/.pytest-tmp/<name> [--shards N]
```

- `--run-dir` must be a NEW directory directly under `<tree>/.pytest-tmp/`, name of at most
  16 characters (`[A-Za-z0-9_-]`), so AF_UNIX paths under it fit in 107 bytes. Anything else
  exits 2.
- Gate dirs live OUTSIDE the tree, at `$HOME/.cache/breezy-gate/par/<run-name>/<job>` (mode 0700;
  the serial wrapper's own default gate-dir root). Phase 2 puts its basetemp under the gate dir
  and the sandbox binds the repo read-only, so a gate dir inside the tree breaks every
  `bwrap_host` test (`bwrap: Can't remount readonly ... Invalid argument`). The driver refuses
  to start (exit 2) if the root resolves inside the repo tree (HOME under the tree, or `par` a
  symlink into it) or already exists (a concurrent run with the same name, or a leftover of a
  SIGKILLed run: remove it by hand). The root is removed when the run ends, on green, red,
  refusal and signal alike; the removal (`gate_shards.py rm-gate-root`) deletes only a real
  directory that is a direct child of `par/` and refuses anything else. Phase-1 basetemp and
  `TMPDIR` stay under `<run>/bt` and `<run>/tmp`.
- Shard count: `N = clamp(min(--shards or 10, floor((MemAvailable_GB - 4) / PER_SHARD_GB)), 1, 10)`,
  printed with the reason; also capped by `os.cpu_count()`, and `--shards` must be at least 1.
  `PER_SHARD_GB = 1.5` is a MEAN-based budget, not a peak bound: Phase 0 measured per-shard peak
  summed RSS of 1.0 to 1.9 GB (tail 1.90 GB), and the whole-run dip in `MemAvailable` for 7
  shards was 4.5 GB, about 0.65 GB per shard. The 4 GB reserve absorbs the peaks.
- Exit code: the first nonzero among the shards (in order), the serial tail, the execution
  proof (4), then the phase-2 proof (4). `2` means refused before any test ran (bad run dir, empty or failed
  collection, partition error).
- Scratch (`bt/`, `tmp/`) is deleted on green and kept on red (gate dirs are always removed); `logs/`, `junit/` and
  `plan/` are always kept. SIGINT/SIGTERM send TERM to every job's process group (the whole-suite
  collect job included), wait 10 s, send KILL to the survivors, reap them, and exit 130. The
  group kill cannot reach a descendant that started its own session (`setsid`, a daemonised
  helper): such a process can outlive the run, so check for strays after an interrupted run.

## How it works

1. One whole-suite `--collect-only -p no:randomly` through the unchanged wrapper (also writes
   `collect.xml`, the source of collection-time skips).
2. `gate_shards.py partition` cuts the node ids into N weighted shards (LPT via
   `tier_lanes.split_lanes`) plus a serial tail of whole files. Weights are integer
   milliseconds from `scripts/ci/gate_durations.json`.
3. Four heavy files are split at function granularity (`SPLIT_FILES`); the consumers of the
   expensive module fixtures (`e2e`, `canonical_cal_b_dir`) stay together. Parametrisations
   of one function are never separated. A drift guard fails if a split file gains a wider
   autouse fixture, `usefixtures`/`getfixturevalue`, teardown after a non-function
   `yield`, a mutated module-level accumulator, or uses a wide-scope conftest fixture.
4. Every shard runs through `run_tests_no_egress.sh` with a private `BREEZY_GATE_DIR`
   (outside the tree, see above), and a private `TMPDIR` and `--basetemp` under the run dir, in
   its own session. The wrapper's phase 2 (the `bwrap_host` registry, about 3 s) runs exactly
   ONCE per run, in the serial tail, never in a shard: concurrent phase-2 copies take flocks
   that moved the host `/proc/locks` count one of its tests compares against. Shards and the
   load-flake rerun set `BREEZY_GATE_PHASE2=defer` and write a 0600 `.parallel-shard` token in
   their gate dir; the wrapper accepts `defer` only for a real (non-symlink, user-owned)
   gate dir exactly two levels under `$HOME/.cache/breezy-gate/par/` holding that token, else
   it prints `phase-2 defer refused: not a parallel shard` and exits 2 (any other value
   exits 2 too; the variable is unset before pytest). A deferred job prints
   `[breezy] gate: phase1 rc=X phase2 DEFERRED (parallel shard; NOT a gate run)` and exits
   with phase 1's rc, or with `DEFERRED_PASS_RC` (10) when phase 1 passed: a deferred run never
   exits 0. Only the driver maps 10 back to 0, and only for a job it launched with defer
   (shard or load-flake rerun) whose log holds exactly one anchored `phase1 rc=0 ... DEFERRED`
   line (`gate_verify.deferred_job_rc`); the tail's rc 10, or any 10 without that line, stays a
   failure. The guard catches accidents and is not a security boundary (whoever can write the
   token can defer), and a defer run is never gate evidence. An empty `BREEZY_GATE_PHASE2` is
   refused with rc 2 like any other non-`defer` value. The tail never defers; its phase-2 return code propagates. An empty
   tail is red (4, "phase 2 never ran"): a stand-in selection would run a test twice.
   Unset, the wrapper behaves exactly as before.
5. After every shard exits and whole-host CPU idle, sampled from `/proc/stat` over a 3 s window
   (`gate_shards.py cpu-idle`), reaches 90 % (wait bounded to 120 s; the measured value is
   printed; the 1-minute loadavg lags too far behind to use), the tail runs: `tier_lanes.SERIAL_FILES`, real-clock-budget files and
   files that write shared fixed paths (`scripts/ci/gate_reviewed.json`, `serial_tail`).
6. **Phase-2 proof** (`gate_shards.py phase2-proof`, logic in `gate_verify.phase2_proof`), from
   the job logs, exit 4 unless: every shard (and flake-rerun) log has exactly one `DEFERRED`
   line and no `phase2 rc=` line, and the tail log has exactly one `phase1 rc=N phase2 rc=0`
   line (no other `phase2 rc=`, no `DEFERRED`). Only wrapper verdict lines (those starting
   `[breezy] gate: phase1 rc=`) are counted, so pytest output that quotes the words cannot move a count. The wrapper's own phase-2 verdict (exactly 41
   passed, no skips) already makes a bad phase 2 nonzero. A load-flake rerun is skipped while
   this proof fails, so a rerun can never supersede a phase-2 fault.
   **Execution proof** (`gate_shards.py verify`), from JUnit:
   - every collected node id appears exactly once (missing, extra or duplicated key: exit 4);
   - any failure, error or strict xpass: exit 4;
   - skips and xfails must be listed in `scripts/ci/gate_reference.json` (`non_pass`, one set
     per `BREEZY_RUN_SLOW` value) or match an `ENV_SKIPS` entry (host-dependent skip,
     exact key or function prefix, anchored message regex, `static`/`resource` tag; a
     `resource` skip inside a shard exits 4). Passing tests are never listed.
   - Skip/xfail divergence is authoritative only on the primary tree (the directory is itself the
     top level of its repository, `--show-toplevel`, and `git rev-parse --git-dir` equals
     `--git-common-dir`; a linked worktree, or a directory merely inside a repository, is not) with a
     reference set for the current `run_slow` and no test seam active; otherwise the proof
     summary says `OUTCOME CHECK ADVISORY` and the final shell line reads
     `GATE GREEN (OUTCOME CHECK ADVISORY)`. An advisory pass is never printed as plain green.
   - Test seams (`BREEZY_GATE_TOOL_PYTHON`, `BREEZY_GATE_DURATIONS`, `BREEZY_GATE_REFERENCE`,
     `BREEZY_GATE_TAIL_MAX_WAIT_S`): any that is set is printed and forces ADVISORY. An
     explicit `BREEZY_GATE_REFERENCE` that is missing or unreadable exits 4.
7. **Load-flake rerun.** If the only failures are keys listed in `gate_reviewed.json`
   `load_flakes` (initially the persistence import budget; at most 3 keys; every nonzero job rc
   must be pytest's 1 and be explained by such a failing testcase), the listed file or node is
   rerun ONCE, serially, after a quiet wait, into `<run>/junit/flake-rerun.xml` (a name `record`
   refuses to read). The proof then swaps each flaked case for its single passing rerun; any
   other failure, or a failing rerun, stays red. The final line reads
   `GATE GREEN (N load-flake rerun(s): <keys>)`. The persistence entry reruns the whole file
   so the 60 s budget is asserted again. The serial gate stays authoritative.

## Keeping the data honest

- Reference refresh reads SERIAL output only:
  `run_tests_no_egress.sh ... --junitxml <run>/junit/serial.xml`, then
  `python3 scripts/ci/gate_shards.py record --from-junit <run>/junit/serial.xml --reason "<why>"`.
  `record` also takes `--ids <run>/plan/whole.ids` (the collected ids): the serial JUnit must
  cover them exactly, so a partial serial run cannot prune entries, and the modules of those ids
  are the "existing" modules. Whenever the reference file exists (even empty), every new or
  changed skip/xfail in an existing module needs its own `--reason-for KEY=TEXT`; the blanket
  `--reason` covers only collection-time skips of modules that are not in the run and the very
  first seed (no reference file). A `--reason-for` key that matches no key of the serial run or
  rerun is refused, naming it. A serial run that failed only because of load (for example the 60 s import
  budget) is accepted only with a serial rerun: `--rerun-junit <run>/junit/serial-rerun-<name>.xml`;
  each substituted key must have failed in the serial run, appear exactly once in the rerun
  as a PASS (a skip or xfail is refused), and carry its own `--reason-for`. To record a load-flake rerun, rerun ONLY the failed node ids
  (`run_tests_no_egress.sh <failed node id>... --junitxml <run>/junit/serial-rerun-<name>.xml`),
  never the whole file: a whole-file rerun holds passing keys that did not fail and is refused
  ("did not fail"). A malformed `--reason-for` is refused naming the argument. The diff is printed; nothing is committed.
- Durations: a green parallel run writes `<run>/durations.suggested.json`; adopt it with
  `gate_shards.py durations --from-junit ... --out scripts/ci/gate_durations.json`.
- A file that flakes in a parallel run moves to `serial_tail`. Every file matching the timing
  scan (`perf_counter`, `monotonic`, `time.time()`, `deadline`, `wait_for`, `timeout_s`) or the
  fixed-path scan (`/tmp/`, `/dev/shm`, `AF_UNIX`, `~/.cache`, `$HOME`, `Path.home()`,
  `expanduser`, `_gate_generated`: a test planting a module into `src/`) must be in `serial_tail` or in `groups` (with a reason): enforced by
  `tests/unit/test_gate_shards.py`. Known limit: clocks and literals inside `src/` helpers are
  invisible to the scan.
- Path-scan classification is a real read, not a signal match: every hit line of every
  parallel-OK path-scan file was read (2026-10-26). A file that WRITES a shared fixed path goes
  to the tail (`test_trade_cli`: stop-intent marker beside a fixed `/tmp` db path;
  `test_asos_recent_refresh`: a cache file in a fixed `/tmp` dir); the rest are dummy
  arguments, absence or refusal assertions, path-shape strings, read-only `Path.home()`
  lookups or `tmp_path` users. An `ENV_SKIPS` pattern that accepts any text (`[\s\S]*`) is
  `resource`, so its file runs in the tail and a skip is never silently accepted in a shard.
- Known limit, by construction: cross-file state pollution that only appears when many files
  share one process (a leaked module global, a patched attribute, an fd or thread from an
  earlier file) is caught ONLY by the serial gate. Shards run different file mixes, so a
  parallel green does not rule it out.
- `gate_shards.py` is the CLI; `gate_verify.py` (JUnit, proof, record, flake plan),
  `gate_fixtures.py` (AST affinity and drift), `gate_classify.py` (reviewed data, scans) and
  `gate_host.py` (sizing, CPU idle, primary tree) are its stdlib-only siblings. The reviewed
  JSON loads lazily, so bad JSON is a clear error at use, never an import crash.

## Phase 0 measurements (2026-10-26, base 6af68cd3, 16 cores)

| Item | Value |
|---|---|
| Serial reference | 29,400 tests: 29,168 passed, 158 xfailed, 73 skipped (41 of them `bwrap_host`, counted as skipped in phase 1); about 100 min of wall under concurrent measurement load |
| Peak summed RSS per shard (7 shards) | 1.03, 1.11, 1.11, 1.13, 1.05, 1.53, 1.79 GB; tail 1.90 GB; largest single process 1.18 GB |
| Timing scan / fixed-path scan | 212 / 69 files (14 in both); 44 tail files after the F5/F9 review: 7 path-scan only, 31 timing-scan only, 6 both, 0 neither |
| Tail | 40 whole files, about 267 s of serial test time, 274 s measured |
| Largest indivisible unit | `test_maker_stage0_isolate::test_isolated_run_equals_the_in_process_run_in_every_output` (3 params, about 718 s) |

## Measured wall time (worktree, host load average about 4 from the live node and services)

| Run | Shards | Collect + partition | Shards (longest) | Tail | Total |
|---|---|---|---|---|---|
| par1 | 7 (memory-limited at `PER_SHARD_GB = 2.0`) | 14 s | 1,084 s | 274 s (+50 s quiet wait) | 23.7 min |
| par2 | 10 (`PER_SHARD_GB = 1.5`) | 13 s | 952 s | 276 s (+95 s quiet wait) | 22.3 min |

The serial gate took about 100 min on the same host. Shard time is about 1.6x the serial test
time at N=10 (CPU contention on 16 logical cores), and the 718 s indivisible unit sets the floor.
The committed ceiling is 25 min at N=10 on a host with load below 5; the 20 min estimate in the
plan was not met. Expect the first run on the primary tree to need a reference review (the seed
was recorded in a worktree): run `gate_shards.py record --dry-run` against a serial junit and
read the diff before adopting anything.

Known flakes seen while measuring, all present in the serial gate too: the 60 s persistence
import budget (`test_persistence_import_free`, fails at load above 4; it is in the serial tail
for that reason) and an order-dependent fd-count assertion in
`test_autonomy_bind_integrity::test_a_refusal_closes_the_binds_opened_before_it` (the failure
showed fd `41` in the BEFORE listing and gone from the AFTER one: a stale fd held by garbage
from an earlier test was closed by a collector pass inside the window; the test now collects
before the baseline and disables the collector inside the window, with the same equality
assertion). The 36 phase-2 `bwrap_host` failures
seen in worktree runs came from the gate dir sitting inside the (read-only bound) tree, not from the
worktree: with the gate dir outside the tree phase 2 passes (41 tests) in a worktree too.
