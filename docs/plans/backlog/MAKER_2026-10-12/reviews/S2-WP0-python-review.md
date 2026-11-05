# S2 WP0 python review (blind) -- worktree maker-s2-wp0 @ e1b048c9

Verdict: APPROVE (0 CRITICAL, 0 HIGH; 4 MEDIUM, 4 LOW -- MEDIUMs are WP6 carry-ins or small hardening)

Evidence
- mypy (3 files: probe, probe_core, test): "Success: no issues found in 3 source files" -> 0 errors.
- Gate: `19 passed in 0.41s` / `41 passed in 2.69s` / `[breezy] gate: phase1 rc=0 phase2 rc=0` (basetemp removed).
- `ParquetDataCatalog.query(self, data_cls, identifiers=None, start=None, end=None, where=None, files=None, **kw)`
  (nautilus_trader/persistence/catalog/parquet.py:1648). `data_cls=` and `identifiers=[rung]` are correct; `start`/`end` exist
  (relevant to M1).
- Function length: all < 50 (longest `_read_instance` 191-231 = 41; `probe` 356-398 = 43 incl. docstring).

Structure
- Registry: `tests/unit/test_runtime_import_isolation.py:141` appends one row, same pattern as S1 line 140
  (`"scripts.analysis.maker_tape_census"`, commit 41db9cbd). Minimal: one module. The core is reached transitively
  (probe imports it at :49), so it is not hidden from the transitive-import test, and none is needed for it.
- No cycle: probe -> core -> breezy.analysis.maker_tape_census only. Re-export via `__all__` is complete (core public names all listed).
- Note: probe imports `scripts.analysis.cli_basis_offer_gate_scan` package-style (:48) whereas S1 uses a sys.path
  insert + bare import; works (tests pass), but is a different convention; keep consistent in WP1+.

Findings
[MEDIUM] M1 Memory/scale -- maker_stage0_probe.py:290,235-238. `default_convert` converts every stream for the WHOLE
  instance, and `_read_frames` materialises every OrderBookDepth10 of every in-scope rung (no start/end) into a list, then
  keeps a `Frame` per row in `ledger.frames` for all instances. Day count is bounded only after the fact. Scale risk for
  multi-week capture: scratch disk = full Depth10 per instance; RAM ~ O(all depth frames). Minimal WP6 mitigation: pass
  `start=`/`end=` (D-1 12:00Z .. D+1 window end, ns) to `work.query` for Depth10/TradeTick, and drop `_mid`-less frames or
  keep only (ts, mid) tuples; stronger: convert only the days' time slice. Also process rungs lazily (already per-rung).
[MEDIUM] M2 Silent skip -- :281-284. `PreflightError` and non-CLEAN verdicts `continue` with no record. A malformed
  instance dir vanishes from the report, so a silent coverage loss is indistinguishable from "none existed". Fix: collect
  `skipped: dict[instance_id, reason]` and surface it in `ProbeReport.to_dict()` (plus a test with one malformed dir).
[MEDIUM] M3 Scratch deletion scope -- :285-293. `mkdir(exist_ok=True)` then `rmtree(work_dir)` in `finally`: a pre-existing
  `work_root/<instance_id>` (stale or foreign) is adopted AND deleted; `_check_work_root` only guards work-inside-catalog,
  not catalog-inside-work_root. Fix: `mkdir(exist_ok=False)` (or refuse a non-empty dir) and also assert
  `work_dir.resolve()` is neither a parent of nor equal to `catalog_root.resolve()`.
[MEDIUM] M4 Pure rules in the I/O module -- :184-188 `_mid`, :311-327 `_coverage` (listing_abstain rule), :330-348
  `_ladder_parity`/`_distribution`, :166 `_key`. They are pure (no catalog access) but untested in isolation (only via the
  synthetic-capture tests). Move `_mid`/`_distribution`/`_ladder_parity`/abstain predicate to the core to hit the plan's
  "pure core" intent and shrink the I/O file below ~300 lines. Not a blocker.
[LOW] L1 Dedup order -- :377-378. `probe` dedups first-wins in `ledger.prints` insertion order; `count_census` uses
  sorted-instance order. If `list_instance_ids` is unsorted the two "first" copies can differ (only matters if a duplicate
  across instances differs in price/side, which the census would flag). Fix: iterate `sorted(ledger.prints)` in probe.
[LOW] L2 `_check_work_root` is robust to symlinks/relative paths (both `.resolve()`d; non-strict so a missing work_root is
  fine) but no test covers a symlink into the catalog; add one (`tmp_path/"link" -> capture/"x"`). The before/after
  file-tree test (:437-444) compares size+mtime_ns of every path -- adequate; it does not assert work_root is left empty
  after the run (scratch cleanup is correct in code, untested): add `assert not any(work_root.iterdir())`.
[LOW] L3 Empty print stream: `first_print_instant` returns None; `probe(first_print_ns=None)` handles it
  (`first_replayable_day=None`, :386-388). Callers not in this commit; WP6 driver must treat None as a STOP/abstain, not 0.
[LOW] L4 Missing docstrings on public core fns (`classify_direction`, `enforce_direction`, `count_census`,
  `reassert_census`, `instance_day_deltas`, `station_day_delta`, `StationDayCoverage` fields).

Error handling / contracts
- `StopS2.result` carries the DirectionResult (core:32-35); `require_clean` runs census first then direction, and the
  sidecar-before-raise ordering is documented. `CensusViolation` carries `asdict(counts)` in its message only (no attribute);
  acceptable, but add `.counts` if the driver needs to write it (L-level).
- direction logic: strictly-prior frame via `bisect_left - 1`, undefined mid counted separately, INSUFFICIENT precedes
  INVERTED/FIXED, 0.9 boundary exact (180/200 == 0.9). Correct.

Tests (19): AAA-style, failure paths present (insufficient n, mixed sides, inverted, duplicate id, no-aggressor, opposite
twin, cross-instance non-duplicate, open-gap superseded, work-root refusal, JSON-pinned report, file-tree unchanged).
Gaps: no malformed-instance test (M2), no explicit determinism test (run probe twice, compare `to_dict()`), no symlink test (L2).
