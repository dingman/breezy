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
  exits 2. The default `~/.cache/breezy-gate` is never used.
- Shard count: `N = clamp(min(--shards or 10, floor((MemAvailable_GB - 4) / PER_SHARD_GB)), 1, 10)`,
  printed with the reason. `PER_SHARD_GB = 1.5` (Phase 0: per-shard peak summed RSS 1.0 to 1.9 GB;
  the whole-run dip in `MemAvailable` for 7 shards was 4.5 GB, about 0.65 GB per shard).
- Exit code: the first nonzero among the shards (in order), the serial tail, then the
  execution proof (4). `2` means refused before any test ran (bad run dir, empty or failed
  collection, partition error).
- Scratch (`bt/`, `tmp/`, `gate/`) is deleted on green and kept on red; `logs/`, `junit/` and
  `plan/` are always kept. SIGINT/SIGTERM kill every job's process group.

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
4. Every shard runs through `run_tests_no_egress.sh` with a private `BREEZY_GATE_DIR`,
   `TMPDIR` and `--basetemp` under the run dir, in its own session. Phase 2 (about 3 s) runs
   once per job; its return code propagates.
5. After every shard exits and the 1-minute load average drops below `0.25 x nproc` (wait
   bounded to 120 s), the tail runs: `tier_lanes.SERIAL_FILES`, real-clock-budget files and
   files that write shared fixed paths (`scripts/ci/gate_reviewed.json`, `serial_tail`).
6. **Execution proof** (`gate_shards.py verify`), from JUnit:
   - every collected node id appears exactly once (missing, extra or duplicated key: exit 4);
   - any failure, error or strict xpass: exit 4;
   - skips and xfails must be listed in `scripts/ci/gate_reference.json` (`non_pass`, one set
     per `BREEZY_RUN_SLOW` value) or match an `ENV_SKIPS` entry (host-dependent skip,
     exact key or function prefix, anchored message regex, `static`/`resource` tag; a
     `resource` skip inside a shard exits 4). Passing tests are never listed.
   - Skip/xfail divergence is authoritative only on the primary tree (`.git` is a
     directory) with a reference set for the current `run_slow`; elsewhere the summary says
     `OUTCOME CHECK ADVISORY`.

## Keeping the data honest

- Reference refresh reads SERIAL output only:
  `run_tests_no_egress.sh ... --junitxml <run>/junit/serial.xml`, then
  `python3 scripts/ci/gate_shards.py record --from-junit <run>/junit/serial.xml --reason "<why>"`.
  A key that changes outcome needs `--reason-for KEY=TEXT`. A serial run that failed only
  because of load (for example the 60 s import budget) is accepted only with a serial rerun of
  that file: `--rerun-junit <run>/junit/serial-rerun-<name>.xml`. The diff is printed; nothing
  is committed.
- Durations: a green parallel run writes `<run>/durations.suggested.json`; adopt it with
  `gate_shards.py durations --from-junit ... --out scripts/ci/gate_durations.json`.
- A file that flakes in a parallel run moves to `serial_tail`. Every file matching the timing
  scan (`perf_counter`, `monotonic`, `time.time()`, `deadline`, `wait_for`, `timeout_s`) or the
  fixed-path scan (`/tmp/`, `/dev/shm`, `AF_UNIX`, `~/.cache`, `$HOME`, `Path.home()`,
  `expanduser`) must be in `serial_tail` or in `groups` (with a reason): enforced by
  `tests/unit/test_gate_shards.py`. Known limit: clocks and literals inside `src/` helpers are
  invisible to the scan.

## Phase 0 measurements (2026-10-26, base 6af68cd3, 16 cores)

| Item | Value |
|---|---|
| Serial reference | 29,400 tests: 29,168 passed, 158 xfailed, 73 skipped (41 of them `bwrap_host`, counted as skipped in phase 1); about 100 min of wall under concurrent measurement load |
| Peak summed RSS per shard (7 shards) | 1.03, 1.11, 1.11, 1.13, 1.05, 1.53, 1.79 GB; tail 1.90 GB; largest single process 1.18 GB |
| Timing scan / fixed-path scan | 212 / 69 files (14 in both); 40 tail files, 227 reviewed-parallel-OK |
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
`test_autonomy_bind_integrity::test_a_refusal_closes_the_binds_opened_before_it` (a garbage
collected file from an earlier test closes an fd between its two `/proc/self/fd` listings; it
passed on a straight rerun of the same tail). The `bwrap_host` phase-2 tests fail in a git
worktree for a host-mount reason, not because of sharding; the serial gate shows the same 36.
