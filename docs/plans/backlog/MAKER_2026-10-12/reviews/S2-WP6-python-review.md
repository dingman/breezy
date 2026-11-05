# S2 WP6 python review (worktree maker-s2-wp6, HEAD 2bbcdc1f)

Verdict: REQUEST_CHANGES (3 HIGH, 6 MEDIUM, 2 LOW)
mypy (10 WP6 modules, from the worktree): Success, 0 errors.
Gate (4 WP6 test files, run_tests_no_egress.sh): 87 passed + 41 passed; `[breezy] gate: phase1 rc=0 phase2 rc=0`.
Function length: all < 50 lines (longest: run_bench 45). No asdict, no theta literal. Registry row: one line, catalog_read only.

## HIGH
1. Exit-code contract broken for unlisted failures. scripts/analysis/maker_stage0_replay.py:46-62,155-167.
   REFUSALS/VOIDS omit EventError, EventBuildError, LeakageError, LocalDayViolation, PNoStoreReadError,
   StationRefusedError, VerdictRefused, CsvCellError/CsvColumnError, FirewallRefused, OSError and the
   bare ValueErrors (station_loop.py:126, report.py:100). After the ledger claim, driver.py:256-259
   voids the dir (rename + ledger entry) and re-raises, so these surface as a raw traceback with exit 1,
   while the CLI documents "3 = voided". Pre-claim they are exit 1, not 2. Worse: if void_run_dir raises
   LedgerRefused (driver.py:258) it replaces the real cause and main returns 2 ("refused before any
   claim") for a post-claim failure. Fix: in _run_verdict wrap post-claim failures in a typed
   RunVoided(cause) (void first, then raise from the original; guard void failure so it chains, not
   masks); main catches RunVoided->3, and a final `except (OSError, ValueError, RuntimeError)` ->
   2 pre-claim with context. Add tests: LeakageError mid-run -> exit 3 + .void dir; OSError on catalog
   read -> typed message, no traceback. No test exists for any unlisted type.
2. No full-run determinism test. tests/unit/test_maker_stage0_driver.py (none). The brief and (g) require
   same world twice -> identical s3_inputs.json and report bytes (timestamps excepted).
   test_stats_rerun_on_scored_csv_reproduces_tables (:258) only re-derives tables from one run's CSVs.
   Fix: run the e2e fixture twice (distinct out-dir names/work roots) and compare s3_inputs.json,
   station_days.csv, scored_episodes.csv and report.md after normalising run_id.
3. catalog_slice_manifest is neither reproducible nor a capture hash. catalog_read.py:184-189 +
   pins.py:176-191. It hashes the SCRATCH conversion (work_root/replay/<instance>/data/..), recording
   str(path) (contains work_root = DEFAULT_WORK/<run_id>) and the fresh files' mtime_ns. Consequences:
   (a) the manifest sha, pinned in pins.json and printed in the report, differs run to run, so the
   pinned-input claim is unfalsifiable; (b) an instance evicted by the keep=3 LRU and later reconverted
   gets a new mtime, so CatalogSliceManifest.add raises "changed between reads" (pins.py:189) and
   the run is voided mid-way. Fix: key entries by capture-relative path and hash the capture parquet
   the query touched (or hash scratch content only, dropping path root + mtime, and dedupe by content
   digest). Add a test that a re-converted instance re-adds without raising and that two runs with
   different work roots give byte-identical manifests. Unverified empirically; by inspection of the code.

## MEDIUM
4. CatalogSession LRU eviction is untested (no test constructs keep<instances or asserts
   eviction/rmtree/close). catalog_read.py:136-142. Memory/disk bound is real by code (scratch
   removed on pop, close() drains) but unproven; add a unit test with keep=1 over 2 instances.
5. RSS watch is coarse. modes.py:180,197 samples once per station-day AFTER the day, and
   read_rss_bytes (runio.py:65) is current RSS, so a mid-day spike is missed. Sample ru_maxrss
   (peak_rss_bytes) for the abort decision, or also check per variant/hypothesis. Single thread, so no
   thread-safety issue. Abort->void path is tested (test_rss_over_four_gib...).
6. Non-atomic writes. driver.py:367,372,328-333,384 write s3_inputs.json, report.md and CSVs via
   Path.write_text; write_text_atomic exists (inputs.py:96). run_manifest.json/pins.json/stop
   s3_inputs use atomic paths. Use write_text_atomic for s3_inputs.json and report.md (and CSVs).
7. Non-verdict modes leak on failure. modes.py:216,272,310 mkdir out_dir with no cleanup; run_tail
   rmtree of work_root (modes.py:297) is not in a finally, so tail_truth scratch persists on error and
   the next run is refused (RunDirExists). Wrap in try/finally.
8. "Streaming" is per-station-day only. station_loop.py:223 iterates replay.result.episodes, a list
   already built by WP4; the test (driver tests :596) proves write-before-next-pull in the driver, not
   that nothing is held. Reword the claim (module docs + test name), or leave WP4 as-is and state the
   bound (one station-day x variants of episodes). out.seeds/out.rows grow per run (small).
9. Modes not an argparse mutually-exclusive group (replay.py:105-106,104); enforced in
   driver._mode (SubsetRefused->exit 2). Behaviour OK and tested, but add_mutually_exclusive_group
   gives the standard usage line and removes a path where parse succeeds with a bad combination.

## LOW
10. DEVIATIONS D3 vs code: _first_ts (events_build.py:176) uses first FRAME if any frame exists, else
    first print; docstring says "first event (frame or print)". Test named "first event" only covers
    frames. Align wording or use min(frames+prints).
11. `assert cfg.bench is not None` / `assert cfg.parity is not None` (modes.py:215,271) vanish under -O;
    parse_args uses `ns.x or Path()` sentinels (replay.py:128-134) that hide absent required paths.

## Verified OK
CLI exit constants/doc; no sys.exit outside main/argparse; refusals pre-ledger tested (dirty tree,
low disk, subset, theta, frozen set, amendment sha); void tests (S-7, S-2, RSS, late first print,
re-run needs addendum); S-4 reported stop (exit 0) tested; bench/tail-only/verify-first tested;
progress schema enforced at write (runio.py:135) and test enumerates forbidden substrings; D2
mapping (adapter.py:73-75,164) matches DEVIATIONS and is unit-tested; adapter pure; no runtime
import outside catalog_read; scratch under work_root, capture read-only, cleaned in finally.
