# S2 WP6 python RE-CHECK (worktree maker-s2-wp6, fix commit 83f47531 on 2bbcdc1f)

Verdict: APPROVE (0 CRITICAL, 0 HIGH; 2 LOW notes below).

## Disposition of the prior review
- H1 exit codes: RESOLVED. replay.py:48-53 REFUSALS=(OSError,ValueError,RuntimeError,FirewallRefused); main
  catches RunVoided first (replay.py:169, before REFUSALS since RunVoided is a RuntimeError) -> 3.
  driver.py:370-377 wraps every post-claim Exception: rmtree scratch, `_void` (returns, never raises, the
  void failure: driver.py:380-386), then `raise RunVoided(exc, void_failure=...) from exc`. Interrupts
  (non-Exception) are voided but re-raised unwrapped. run_types.py:524-533 puts BOTH causes in the message.
- H2 determinism: RESOLVED. test_full_run_is_deterministic (driver tests :939): two runs, distinct roots;
  byte-compares station_days.csv, scored_episodes.csv, catalog_slice_manifest.json; s3_inputs equal minus
  key `code_sha` only; report equal line-by-line.
- H3 manifest: RESOLVED. catalog_read.py:197-204 hashes the CAPTURE files (stream x rung) via
  pins.py:194-213 add_capture_file: entry = {path (capture-relative), size, sha256}; no mtime, no abs path.
  Tests: manifest-by-relative-path vs capture bytes; LRU keep=1 over 2 instances (reconvert, no "changed" error).
- M4 LRU eviction test: RESOLVED (test_lru_eviction..., scratch dir contents asserted, close() drains).
- M5 RSS: RESOLVED. modes.py:111-119 peak_watch (ru_maxrss, checked in-day via ctx.watch) + modes.py:171-187
  per-day rss_peak_delta_bytes and post-day check; test peak_rss_is_checked_inside_the_day + progress delta test.
- M6 atomic writes: RESOLVED. finish.py:65-70,127,133,146 write_text_atomic; report.py:210; write_json atomic.
  Spy tests assert s3_inputs/report/CSVs/tail csv go through write_text_atomic.
- M7 cleanup: RESOLVED. driver.py:330-335 removes out_dir + work_root on any BaseException in report-only
  modes; parametrised bench/tail/verify test asserts neither exists. run_bench/run_tail also rmtree scratch.
- M8 streaming wording: RESOLVED (station_loop.py:1-10 states the real bound: one station-day x one variant).
- M9 argparse group: RESOLVED (replay.py:109-112; test_modes_are_a_mutually_exclusive_argparse_group);
  mode_of() still rejects the combination for programmatic RunConfig.
- L10 _first_ts: RESOLVED (events_build.py:197-205 min over frames, prints, gaps, truncations; two tests).
- L11 asserts/sentinels: RESOLVED. No `assert cfg.x` left; RunConfig.need() (run_types.py:564-569) raises
  InputRefused; paths are `Path | None` (no `or Path()`), need() used in modes/finish/preflight/report.

## Specific checks
1. RunVoided: chaining present (`from exc`, driver.py:377). ERRORS list (14) used for pre-claim exit 2 AND
   post-claim exit 3 (test_maker_stage0_replay.py:111-135) and for typed-void: EventError, LeakageError,
   LocalDayViolation, PNoStoreReadError, VerdictRefused, CsvCellError, CsvColumnError, OSError, ValueError,
   RuntimeError, StationRefusedError, InputRefused, DeltaBoundExceeded, MemoryAbort. Catch-clause types
   NOT in the list: FirewallRefused (a bare Exception subclass, so it relies on the explicit tuple member).
   Failed-void test (driver :901, replay :136) asserts cause + both messages.
2. Mask is minimal: 4 report line prefixes (title run_id, code_sha row, ledger path row, progress.jsonl
   sidecar-sha row) + s3 key `code_sha`. pins.json is not compared (not claimed). Not over-broad.
3. add_capture_file is additive (new `_stamps` dict in __init__, new method; add() untouched). WP1
   test_maker_stage0_pins.py passes (41).
4. render/finish/preflight: 168/196/287 lines; acyclic (render imports only verdict+tables; preflight->modes;
   finish->modes,render,report). TYPE_CHECKING moves (run_types, catalog_read) are annotation-only under
   `from __future__ import annotations`. import_closure (runio.py:383-407) skips only `if TYPE_CHECKING:`
   bodies; only report.py imports load_truth at runtime (grep over scripts/ and src/); closure test bans
   report/driver/verify_first/render/preflight/finish/pins and scans every reachable module for
   TRUTH_NAMES imports; non-vacuous (helper-catches-truth and TYPE_CHECKING-skip unit tests).
5. See dispositions above (atomic, cleanup, RSS, argparse, need()).

## New findings
- [LOW] driver.py:369 `cfg.out_dir.mkdir(parents=True)` sits after the ledger claim but outside the try, so
  an OSError there exits 2 ("refused before any claim") although the entry is consumed. Fix: move mkdir inside
  the try (void then renames nothing: guard void_run_dir for a missing dir) or claim after mkdir.
- [LOW] No test covers FirewallRefused through main (the only catch-clause type outside ERRORS), and
  catalog_read does not hash instrument-definition parquet used by plan() (only 4 data streams). Add
  FirewallRefused to ERRORS; note the definitions gap in the manifest docstring.

## Static / gate
mypy (14 WP6 source files, from worktree): Success, no issues found in 14 source files.
tests/unit/test_mypy_ratchet.py: 16 passed (tests/unit ceiling 1257 = test_mypy_ratchet.py:413).
Gate: WP6 driver/replay/adapter/events_build + pins tests: 217 passed + 41 passed;
`[breezy] gate: phase1 rc=0 phase2 rc=0`. Ratchet run: same gate line rc=0/rc=0. Basetemps removed.
