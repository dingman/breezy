# S2 WP1 MLE review (commit 78906397, worktree maker-s2-wp1)

Verdict: REQUEST_CHANGES (3 HIGH, all small). Tests: `run_tests_no_egress.sh` over the 4 maker_stage0 test files, EXIT=0
(99 + 41 passed, gate rc=0/0, BREEZY_PYTHON=main venv). `load_model(repo)` on the real repo returns fit_window_end 2026-06-30.
Real truth CSV parses (1138 FINAL keys, last 2026-10-12). No network; only `git` subprocess; no truth read outside `load_truth`
(but see H3 for what load_truth reads).

## Checks 1-8 (short)
1. n_eff_gov: imports `RHO_ASSUMED`/`N_EFF_FLOOR` only (inputs.py:29-34); equality vs `summarise(rows).n_eff_ub` tested (test_inputs:109). OK.
   LOW: the no-private-helper test reads a cwd-relative path (test_inputs:128-132).
2. Frozen parser: refuses placeholder, 10-01, >10-13, NYC, outside-rule, bad sha, DRAFT, dup/unsorted; accepts both inline and
   next-line `dates:`. Matches the amendment fence (```FROZEN_DATE_SET, six keys). Gaps: M1.
3. Ledger: see H1, H2. tree_digest is deterministic (sorted rel paths, size, content sha; unopened = name+size).
4. Pins: no key missing vs (g)/r3 (diff below). load_model asserts bullet == JSON-block sha == artefact sha == manifest sha, v5.0
   v5_fit_slice end == DEFAULT_SPLITS == 2026-06-30, no era later. Clean-tree scope = 5 paths incl. pyproject, uv.lock, tests/fixtures. M5, M6.
5. Four readings: rulings below.
6. Fixture: `census_row` asserts the default-dict key set == `dataclasses.fields(CensusedDay)` and `to_dict` keys; rows reach disk only via
   S1 `write_censused_days`; round-trip (test_inputs:43) and drift tests (:70) present. Derived by name set, not by type/values (LOW).
7. Taker mapping BUYER -> yes_price, SELLER -> 1 - yes_price matches S1 (`trade_quantity_unit.py:222-226` NO leg <-> SELLER print at 1-cost;
   `:256` TAKER predicted size = fill_cost). Correct IF WP0 does not report an inverted direction; `to_contracts` has no direction input (L1).
8. See H3.

## Findings (ranked)
[HIGH] H1 Ledger check and append are not atomic. `ledger_refuses` (ledger.py:149) and `append_ledger_entry` (:79-105) are separate;
  two invocations (retry of a hung run, a watcher relaunch) both pass the check. The amendment's one-pass control is this ledger.
  Fix: one `claim_verdict_run(...)` taking the flock across read-check-append (open "a+", LOCK_EX, check, write); the driver calls only
  that, after preflight and before S-7. Test: two claims in threads, exactly one succeeds.
[HIGH] H2 A finished run can re-run. `_addendum_refusal` (ledger.py:132-146) checks only a `.void` dir name and absence of three file
  names; anyone can rename a finished run, delete `scored_episodes.csv`/`s3_inputs.json`/`verdict.*`, and supply an addendum. The
  `tree_digest` that `void_run_dir` computes (:182-191) is returned, never persisted or compared; the ledger file itself is unpinned.
  Fix: `void_run_dir` appends a `kind=void` ledger record {run_id, tree_sha256, file list}; the addendum is accepted only if that
  record exists, `tree_digest(void_dir)` still equals it, and the record's file list holds none of the result globs. Widen
  FORBIDDEN_RESULT_GLOBS to also cover `station_days.csv`, `overlay_station_days.csv`, `stress_*`, `report*` (carries
  `rung_trials_filled_*`, `nogo_driving`); this is stricter than amendment s3, so pin it in the plan. Record the ledger's sha in pins/report.
[HIGH] H3 `load_truth` reads outside the licence. inputs.py:230-257,260-269,285-297 parse and hold every row: 2026-10-01 (sealed,
  "excluded from every read", amendment s2), days > 10-13, and the whole cross-check parquet; a conflict message prints tmax values
  (:294-297). Amendment s1 item 1 licenses the frozen set only. Fix: `load_truth(..., days: frozenset[date])` filters on
  (station, climate_day) before `int()`/compare; messages carry key and sha, never values. Hash the full CSV bytes (unavoidable) but never parse them.
[MED] M1 frozen.py:49,169: DRAFT is refused, but a file with no Status line passes; require a positive `^Status:\s*\*{0,2}FINAL`.
  Also `load_amendment` reads the working tree; check bytes equal `git show HEAD:<path>` ("FINAL committed bytes", amendment header).
[MED] M2 nodelog.py:106-115 asctime is host-local (`logging` default converter). Host is UTC today (`date` = UTC; fixture 16:50:40,787 vs
  issued_at_ns agree) but nothing checks it. Fix: in `scan_node_log` assert the first asctime stamp is within 120 s of the UTC stamp in
  the filename `breezy-trade-YYYYMMDDTHHMMSSZ.log` (real logs: 165027Z vs 16:50:28,913), else refuse.
[MED] M3 OUTAGE false positives. Real node logs since 2026-10-08 hold boot lines and NO permit lines (orders off), so the permit clause
  is inert and OUTAGE rests on boot lines alone. (a) LOG_START_GRACE (nodelog.py:72,169) admits a file whose first line is a non-boot line
  at <= 17:00Z: up to 10 min unobserved, no boot, no permit -> OUTAGE (day dropped from numerator and denominator). (b) A hand boot before 16:50Z
  has no in-window boot -> OUTAGE. Fix: grace only when the file's first stamped line is the boot line; a boot before the window start in a file
  whose span covers the window counts as up (LIVE).
[MED] M4 schedule.py:106-113 every `boot_family_declared` is a relaunch cut, including boots that die before the permit (trade.py:1316
  precedes the permit mint :1385). Overlay-only, so it cannot move the label; count "boots without a following permit/tick" and print them.
[MED] M5 pins.py:124-128 `git status --porcelain` obeys `status.showUntrackedFiles` and hides gitignored files. Add `--untracked-files=all`
  (and `-c status.showUntrackedFiles=all`); optionally fail on `git ls-files -v` flags h/S under the five paths.
[MED] M6 pins.py:338-373 does not assert pinned truth copy sha == frozen-block sha, does not require the canonical sidecar set
  (`overlay_station_days.csv`, `process_schedule_overlay.json`, `wp0_agreement.json`, `stress_plus60_station_days.csv`,
  `stress_poll_lag_station_days.csv`, `progress.jsonl`), and pins the amendment without re-parsing it. Add the three assertions.
[LOW] L1 `UnitHypothesis.to_contracts` (inputs.py:148) takes the raw aggressor; if WP0 returns inverted (<= 0.1) the BUYER/SELLER roles flip.
  Pin that callers pass the WP0-corrected side, or add a `direction` argument. L2 `_read_entries` ignores `kind` values. L3 installed
  package set is recorded, not compared with `uv.lock`.

## Rulings on the four UNVERIFIED readings (delta (d))
1. Permit line "inside the window" read as validity [issued, expires) meeting the window: CLARIFICATION that delta (d) itself requires (its
   fixture sentence "booted before 16:50Z: no in-window boot line, permit line present" cannot hold under the literal reading). Pin the exact
   rule in the plan before the run, with the M3(b) rule for orders-off logs.
2. Boot asctime as UTC: EXTENSION (the delta is silent). Pin "asctime is UTC, verified against the filename stamp" (M2) before the run.
3. 10-min launch-window grace (LAUNCH_WINDOW_END - LAUNCH, imported): EXTENSION, weaker than "span fully covers". Pin it, restricted per M3(a).
4. First in-window boot = launch, later = relaunch (unless an earlier-issued valid permit shows the node up): EXTENSION. Pin it; overlay-only,
   so it cannot set the label (delta (d) report-only second pass).
None of the four touches PRIMARY, but #1-#3 decide which days leave numerator and denominator (OUTAGE), which does move the label.

## Pin-key diff (REQUIRED_PIN_KEYS vs delta (g) + r3 L125)
Missing: none. Present for every item: census, trade_unit, truth_csv(copy), truth_cross_check, artefact, deploy_manifest, evidence_doc, uv_lock,
spec, git_commit, nbp_manifest, nbp_consumed, process_schedule, catalog_slice_manifest, clean_tree, installed_package_set_sha256, argv, node_logs,
ledger_path, sidecars, theta_pin_site, truth_csv_sha256_frozen_block, amendment_final(+_sha256), model. Not a key but required: the
overlay schedule pin (carry it in `sidecars`, M6) and the S-3 `code_sha` (= git_commit).
