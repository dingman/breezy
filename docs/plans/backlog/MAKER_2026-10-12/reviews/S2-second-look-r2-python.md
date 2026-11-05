**Verdict: REQUEST_CHANGES.** There are five blocking items. Most of the r2 plan checks out against the code, but C6's cross-check producer cannot cover the block-2 days, and C2b(i) breaks an existing test.

Scores (1-10):

| Axis | Score |
|---|---|
| Correctness vs governing texts | 7 |
| Architecture/idiom fit | 7 |
| Test coverage | 6 |
| Risk mitigation | 6 |
| Scope minimality | 7 |
| Feasibility | 4 |

Overall confidence in the plan as written: **MEDIUM-LOW**. After the five fixes below it would be MEDIUM-HIGH.

## Verify-first results

All seven items below were checked against the code.

1. **Ledger.** A new amendment sha is a fresh claim with no code change. `_refusal` matches only on `amendment_sha` (`scripts/analysis/maker_stage0_ledger.py:203-205`). Start entries carry no dates (`:243-251`), so there is no date-overlap guard.
2. **Frozen set.** `LAST_ALLOWED_DAY` is 2026-10-13 (`maker_stage0_frozen.py:36`). `_check_dates` refuses any later day (`:126-127`) and `parse_frozen_block` refuses any other first day (`:149-150`). Every date from 10-14 is refused today.
3. **Driver.** The claim is at `maker_stage0_driver.py:177`. The first-replayable equality check is inside `_wp0` (`:225-229`), reached via `_execute` at `:190`. A mismatch raises `InputRefused`, and `:191-196` converts it to `RunVoided`. It would void a block-2 run, so r2's report-only change for v2 is correct.
4. **Census firewall.** There is one pinned range and sha (`src/breezy/analysis/maker_tape_census.py:71-78`). `require_firewall_clearance` is at `:178-200`.
5. **Tail path.** `run_tail` (`maker_stage0_report.py:181-212`) never calls `tail_table`. In verdict mode, though, the annotation is reachable (see FALSE claim 2).
6. **Block-1 literals.** `render.py:86` is the D5 literal. `HOLDOUT_LINE` is at `:41-47`. `TAIL_RANGE` is at `driver.py:113`.
7. **Shrink arithmetic.** I recomputed it from `docs/evidence/maker/stage0_2026-10-16/station_days.csv` and `wp0_agreement.json`.
   - The CSV has 96 rows: 88 COVERED, 4 LONG_HOLE, 4 LOW_COVERAGE.
   - `listing_abstain` is true on 44 rows: 40 COVERED plus the 4 LOW_COVERAGE.
   - COVERED and early-listed is 48, which is 12 dates of 4 stations each.
   - The proxy n_eff is 19.2000 and the realised `n_eff_gov` is 18.7333, so the shrink is 0.976 and 30/0.976 is 30.7.
   - The arithmetic is correct. The 4 non-bid-bearing rows are the plan's named exceptions.

## BLOCKING

**B1. C6 and A6: the named cross-check producer cannot cover [10-14, 11-15].**
- `scripts/analysis/settlement_truth_dataset.py:276-282` hard-codes `_EXTENSION_WINDOW_END = 2026-09-28`.
- Its comment says the cache is "fetched once and read-only forever after". `:13-14` says a cache miss is a refusal.
- The on-disk `settlement_truth.parquet` is dated Sep 29.
- Re-running the script therefore reproduces coverage up to 09-28. `load_truth` (`maker_stage0_inputs.py:357-360`) would then refuse the block-2 keys as vacuous, which is a certain void.
- The plan's U-3 ("unverified") is already answered NO by the code.
- Required fix: name a producer that can actually emit [S, E] rows. Options are an independent source, or an explicit new fetch-and-pin unit with its own tests. If that needs new data or network access, say so against the "recorder tape is the only new data" constraint. If no such producer exists, make this a Doc A precondition now, not a calendar-time discovery. The vacuous guard must not be relaxed.

**B2. C2b(i): the v1 sha pin breaks existing tests, and the "fixture-only" claim is false.**
- `tests/unit/test_maker_stage0_driver.py:365-373` (`test_frozen_set_missing_a_rule_day_is_refused`) runs a valid v1 amendment, `short.md`, in verdict mode.
  - `short.md` has a different sha from the world's amendment.
  - The test expects `RunVoided` after the claim.
  - A pin in `_run_verdict` before `:177` would refuse it earlier with a different exception. That test cannot stay byte-unchanged.
- At least these files call `drv.run` on a verdict run built from `rw.build_world` or `drv_fx._fresh`: `test_maker_stage0_isolate.py`, `test_maker_stage0_isolate_followups.py`, `test_maker_stage0_release.py`, `test_maker_stage0_driver.py` (48 `drv.run(` calls) and `two_parity_world.py`.
  - A patch inside `replay_world.build_world` cannot apply a pytest monkeypatch. Reaching all of them needs a conftest-level autouse, not a fixture-only edit.
- Required fix, which leaves every existing test untouched: enforce the pin in the production CLI layer, `maker_stage0_replay.py` (the sha arrives from the CLI at `:95-97`), before `drv.run`. Keep the ledger `block_first_day` guard in the driver.
- If the pin must stay in the driver, say plainly that `test_frozen_set_missing_a_rule_day_is_refused` is amended and why.

**B3. C2: the fence fields have no storage and no consumer, so A6 and A9 are unenforced.**
- The `FROZEN_DATE_SET_V2` fence lists `cross_check_path`, `cross_check_sha256`, `trigger_day` and `trigger_rows_sha256`.
- The new `FrozenDateSet` fields cover only `block`, `trigger_day` and `trigger_rows_sha256`.
- Nothing compares `cfg.truth_cross_check` with the fence's `cross_check_sha256`. `preflight` (`maker_stage0_preflight.py:146,161`) checks only the truth csv sha. `TruthTable.cross_check_sha256` is computed from whatever file was passed (`inputs.py:371`).
- A wrong or stale cross-check file is silently accepted.
- Nothing recomputes E from the rows behind `trigger_rows_sha256`.
- Required fix:
  - Add the two cross-check fields to the dataclass.
  - Add a pre-claim preflight check that the cross-check file's sha equals the fence value, with a named test.
  - Either carry `trigger_rows_path` and verify its sha and E in `verify_set_matches_rule`, or state that the pin is audit-only.

**B4. C2b(ii): the ledger change is under-specified in ways that can break the one-shot guard.**
- `_KEYS_BY_KIND` is a `Mapping[str, frozenset]` and `_read_entries` tests `set(entry) != expected` (`ledger.py:66-69,149`). It must become a set of accepted key sets. This is a type change, not just a row.
- `claim_verdict_run` must omit `block_first_day` entirely when it is `None`. Writing a null seven-key entry breaks the legacy six-key shape.
- `_refusal` must match `block_first_day` only when the claim's value is not `None`. Otherwise `None == None` makes every legacy entry "mine".
- Add RED tests for both: a v1 claim writes exactly six keys, and a v1 claim never matches on `block_first_day`.

**B5. C4 under-specified, and acceptance criterion 4 ("no known post-claim void remains") is false as written.**
- **Census cost.** `run_census` runs `classify_instance(scan_instance(...))` for every instance on every invocation (`scripts/analysis/maker_tape_census.py:285-296`). Probe uses the memoized scan; the census does not.
  - One run per day therefore costs a full instance scan, roughly the W1 preamble order of magnitude.
  - A six-day catch-up on 10-21 may not fit `RuntimeMaxSec` 1800.
  - Required fix: measure one single-day run before Doc A FINAL. Have `check` batch catch-up days in one multi-day invocation, since per-station-day rows do not depend on the range.
- **Reads past E.** In a catch-up, `check` must stop reading at the first crossing day. Add `test_catch_up_stops_reading_after_first_crossing`. Without it, the A5 "never read > E" guarantee is only a cadence assumption.
- **Counts-only flag.** `--output` is `required=True` (`maker_tape_census.py:474`), and `main` writes full `CensusedDay` rows, including `buyer_by_bucket` and `n_prints`, before any report (`:507`).
  - Specify that `--counts-only` writes no full rows, with `--output` optional or ignored.
  - Specify that it returns 0 and skips the `_EXIT_UNSCREENED` mapping at `:520`.
  - The current test for "exactly four fields" must cover the on-disk file, not just stdout.
- **Post-claim voids still present.**
  - `TruthConflict` (`inputs.py:361-363`) and `verify_set_matches_rule` (`frozen.py:197-216`: last-final mismatch, absent census dates) run only in `score()`, after the claim (`report.py:117-122`).
  - The C6 shared helper should run the full agreement check pre-claim, not just the overlap. Otherwise restate criterion 4 honestly.
- **Exact-set widening.** If C4 ships a repo systemd unit, `tests/support/entry_points.py:26-50` derives `ExecStart -m` or script modules. That forces one reviewed row in `STAGE0_ENTRY_MODULES` (`tests/unit/test_runtime_import_isolation.py:140`) and a matching row in `test_persistence_import_free.py`. Say whether the timer is a repo unit (widening needed) or a transient `systemd-run` (none).

## Claims found FALSE or overstated

1. **C2b(i) "fixture-only change, no assertion changes"** is false. See B2.
2. **§5 "the annotation was unreachable; W6 is the fix"** is partly false.
   - The verdict path already supports `--tail-csv` (`maker_stage0_replay.py:117`, `run_types.py:99`).
   - `finish._write_tables` reads it with `read_tail_csv` (`finish.py:67`), and `tables_from_csvs` does the same (`tables.py:328-337`).
   - `render_verdict` then emits TAIL-MISCALIBRATED (`tables.py:127-128`).
   - It was unreachable only because run 1 passed no tail csv (`verdict_run_tail_reliability_empty.csv`).
   - A block-2 verdict can embed the committed block-1 sidecar via `--tail-csv`, which the pin machinery already records (`finish.py:80-86`).
   - W6 is therefore likely unnecessary. Doc B item 5 should license `--tail-csv <sidecar sha 6749a921…>` and add no code. This also drops one new function.
3. **C5 sweep allowlist is incomplete.** "Any other 2026-xx literal is a defect" would false-fail on:
   - `maker_stage0_model.py:34` (`NBP_S2_VALIDATE_RESULT_2026-09-30.md`);
   - `maker_stage0_replay.py:40`, `rule.py:4` and `stats.py:5` (spec filename `…2026-10-12.md`);
   - the plan-path docstrings in `fill.py:3`, `fill_events.py:3`, `fill_pass.py:4` and similar.
   - The sweep is not a named test. Make it a test with a regex that exempts doc-path filenames, or drop the "defect" wording.
4. **C5 plumbing.** `HOLDOUT_LINE` is consumed in `render_report` (`render.py:256`) and `render_stop_report` (`:285`).
   - Neither takes `FrozenDateSet`. The block must be threaded in from `finish`, which already holds `pre.frozen` (`finish.py:97`). U-2 is thus answerable now.
   - Add the parameter as optional with a v1 default so the existing render tests stay unchanged.

Claims that verified as true: the line numbers cited for ledger, frozen, driver, census, probe, probe_core, inputs, report and preflight; the 400-line problem for `probe.py` (398); `scripts` outside the import-linter graph (`pyproject.toml:71`); the `trade_quantity_unit_crosscheck.py:121-128` blast radius; and that `asdict` appears nowhere in the touched maker modules.

## Per-unit assessment

- **C1.** Feasible and RED-first. The existing tests at `test_maker_tape_census.py:112-126` stay byte-unchanged and green, since the registry still refuses 10-14 under the first sha.
  - Specify that `SearchDeclared` moves into the new module. The registry must not import the census, or it creates a cycle with `MAKER_STATIONS` (`census:62`).
  - Narrowing row 1 after the evidence commit edits the two ceiling tests. Say so.
- **C1b.** The guard is feasible. `main` is about 40 lines and the added guard, ledger append and flag would push it past 50, so extract helpers into the new module.
  - The ledger path must be injectable, not only the clock. Otherwise tests write to `~`.
  - Appending before the firewall check over-counts a refused run. That is conservative and should be documented.
  - Existing census tests use `--to` up to 2026-10-02, and the real clock is 10-16, so they stay green.
- **C2.** The exact-fence regexes are cosmetic. A v2-only doc already fails the v1 parser, because `_BLOCK_RE` needs the fence to end at whitespace. The tests are still worthwhile, and `test_v1_parse_of_committed_amendment_is_unchanged` is the right guard. `load_amendment` needs a stated fence dispatch, since `preflight` calls it (`preflight.py:154`).
- **C3.** Correct. `_wp0` should extract a pure `check_first_replayable(probed, frozen)` for direct testing. A full v2 e2e world, with dates 10-14 and later, does not exist: `replay_world.py` is hard-bound to 09-18..10-13. That fixture is a real cost, so budget it.
- **C6.** Blocked by B1. The mechanism claims (`inputs.py:357-360`, `report.py:117-122`) are correct, and the 96 `sd_rows` keys equal the frozen keys.
- **C7.** Correct and conditional. `_for_each_clean_instance` classifies every instance (`probe.py:261-281`), and the `skipped` dict will change for pre-filtered instances. The "licensed output identical" test must exclude `skipped`, or assert it is disclosed.
- **Size limits.** `ledger.py` 320 plus about 25 is fine. `frozen.py` 216 to about 330 is fine. `render.py` 287 plus builders is fine. `inputs.py` 373 plus a helper is tight at about 395. `verdict.py` (397) and the other `rows`/`scored`/`stats`/`tables` modules are not touched, so the `test_wp5_module_line_counts_under_ceiling` ceiling holds.
- **Contracts untouched.** No S-* screen test, NO-SEND pin, `BacktestOrderGuard`, `AS_MARGIN`, or `asdict` scan is modified. `lint-imports` is unaffected provided the new module lives in `breezy.analysis` and does not import `scripts`.

## Round-2 resolution table check

- **A1:** confirmed.
- **A2:** confirmed, but C5's call-site plumbing is unspecified.
- **A3:** confirmed.
- **A4:** partly. The counts-only output file and the per-run scan cost are open (B5).
- **A5:** partly. Catch-up read-past-E is untested.
- **A6:** not borne out. The cited producer cannot yield November rows (B1), and the sha pin is unenforced (B3).
- **A7:** partly. The v1 pin breaks existing tests (B2), and the ledger spec has gaps (B4).
- **A8:** W3 dropped as stated. W6 is redundant (FALSE claim 2).
- **A9:** the pin is unverifiable in code (B3).
- **A10, A11, B1-B10:** acceptable as stated.

## Non-blocking suggestions

- Put the "known post-claim voids" list in Doc B as an explicit residual: `ProbeReport.require_clean` (S-2, outcome-dependent), the S-7 clamp, and RSS or memory aborts.
- Have `close` re-verify its own forfeiture line against the read-ledger, with a test.
- The trigger tool should use a lock file, since the census work root is single-writer.
- The `listed_in_time` agreement test (`test_listed_in_time_agrees_with_probe_listing_abstain`) is good. Add a boundary case at exactly D-1 12:00Z.

## Answers to the planner's open questions

- **P-1 (disjoint blocks vs pooling): disjoint, with a standalone V0.** Amendment `:71` ("a second verdict scoring pass on this set is forbidden") and `:77` (more days need a new dated declaration with its own frozen set) rule out a pooled re-score of block 1. S3 `:149` attaches to a different state. L-56 supports not counting the motivating data.
- **P-2 (realised vs full-range SEARCH forfeiture): realised accrual, with the 132 ceiling disclosed.** This holds only if the read-ledger and the census range guard are the sole way to read these days. B5 must close the catch-up gap so the realised figure is trustworthy. Keep the 132-up-front fallback.
- **P-3 (ledger date-overlap guard): the `block_first_day` key is sufficient.** C2 pins `block_first_day == 2026-10-14` in the v2 parser, so every legitimate v2 document carries the same key and a second v2 claim collides. A full date-range overlap guard would add nothing. The v1 side needs the sha pin, but enforce it at the CLI (B2).

## Relevant files

- `/home/jon/breezy/scripts/analysis/maker_stage0_ledger.py`
- `/home/jon/breezy/scripts/analysis/maker_stage0_frozen.py`
- `/home/jon/breezy/scripts/analysis/maker_stage0_driver.py`
- `/home/jon/breezy/scripts/analysis/maker_stage0_preflight.py`
- `/home/jon/breezy/scripts/analysis/maker_stage0_inputs.py`
- `/home/jon/breezy/scripts/analysis/maker_stage0_finish.py`
- `/home/jon/breezy/scripts/analysis/maker_stage0_render.py`
- `/home/jon/breezy/scripts/analysis/maker_stage0_replay.py`
- `/home/jon/breezy/scripts/analysis/maker_tape_census.py`
- `/home/jon/breezy/src/breezy/analysis/maker_tape_census.py`
- `/home/jon/breezy/scripts/analysis/settlement_truth_dataset.py`
- `/home/jon/breezy/tests/unit/test_maker_stage0_driver.py`
- `/home/jon/breezy/tests/unit/test_runtime_import_isolation.py`
- `/home/jon/breezy/tests/support/entry_points.py`
- `/home/jon/breezy/tests/fixtures/maker_stage0/replay_world.py`