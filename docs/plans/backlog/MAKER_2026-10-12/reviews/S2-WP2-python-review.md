# S2 WP2 python review - maker_stage0_pno.py @ e64e33b4

Verdict: REQUEST_CHANGES (2 HIGH, both small; no CRITICAL). Everything else is MED/LOW.
mypy (both files, worktree PYTHONPATH): Success, 0 issues in 2 files.
Gate: `15 passed in 0.45s` / `41 passed in 3.86s` / `[breezy] gate: phase1 rc=0 phase2 rc=0`. basetemp removed.

## p_yes reuse - VERIFIED
decision.py:307-331 calls `calibration.resolve(era, latitude_deg, climate_day)` and passes `resolved.draws`
to the BoundsProvider; `ArtefactBoundsProvider.__call__` (artefact_bounds.py:58-60) returns
`rung_probability_interval(pct, cdf_method, draws, ladder)[rung_id]` and `p_hat` = point = fmean of per-draw
rung probabilities. WP2 does the same with the same resolve args (vector.model_version, site lat, vector.climate_day).
`resolve().point` is correctly NOT used. Same estimator, same trading quantity. Test 1 recomputes it independently.

## HIGH
1. Abstention reason is a Counter side-effect only. pno.py:303-315 (load_p_no), :236. WP4 needs the reason per call,
   and the Counter is not keyed by stress, so none/plus60/poll_lag counts mix. Minimal fix: add
   `def classify_p_no(store, station, day, ts, *, stress) -> PNoAtInstant | str` (str = reason) holding the current
   body; `load_p_no` becomes a 3-line wrapper that increments `store.abstentions[(stress, reason)]` and returns None.
   Keep `load_p_no` signature so tests stay green; change the Counter key to `(Stress, str)`.
2. NaN/inf p_yes passes silently. pno.py:195-219. `rung_probabilities` asserts `abs(total-1) > 1e-12`, which is False
   for NaN, so a NaN percentile/sd row yields NaN p_no and flows to WP3 (cf. WP3 NaN HIGH). Fix: in the loader,
   `if not all(math.isfinite(p.point) ...)` -> abstain "nonfinite_p_yes". Add a test with a NaN TXN_SD row.

## MED
3. Module is at 399/400. Split NOW: move verify-first (pno.py:326-399 + _EXPECTED_AGE_MIN/_TOLERANCE_MIN/VERIFY_FIRST_DAY,
   ~80 lines) to `maker_stage0_s6_verify.py`, importing `_read_pinned/_build_state/_site` (rename them public or
   re-export). Makes the no-fill/no-p_no isolation structural (simulator cannot import it by accident), leaves ~320 lines.
4. STALE_H duplicated (pno.py:60,66; maker_stage0_rule.py:25,139 in wp3/int worktrees). Single owner: WP2
   (`maker_stage0_pno.STALE_H`); WP3 imports it. Rule layer depends on loader, not the reverse. Also make both use the
   same comparator (both are strict `>`; keep 8 h inclusive), and delete the duplicate stale check in one of them or
   state which is authoritative (loader abstains first, so WP3's check is dead for live rows).
5. Broad `except ValueError` in ladder_p_yes (pno.py:212) also swallows empty-draws, bad `level`, and the
   sum!=1 assert, then silently recomputes via complement ladders. Fix: pre-check partition with the module's own
   `_assert_complete_partition` / dedicated predicate, or catch only the partition error and re-raise otherwise;
   test that a gapped ladder falls back and a zero-draw calibration raises.
6. Raw KeyError/tracebacks: `store.state` indexes `self._rows[(station, day)]` (pno.py:267) and `self._ladders[...]`
   (:277) for a station-day not passed to from_root; a corrupt parquet in `read_partition` (:170) propagates unwrapped.
   Fix: raise `LookupError(f"station-day not loaded: ...")` in load_p_no; wrap read_partition failures with the
   offending path (`raise PNoStoreReadError(path) from exc`). Add one test each.
7. `_site()` rebuilds `default_registry()` and 3 lookups on every call, up to 3x per load_p_no (:306, :266, :278).
   Hot path in the simulator. Cache per station (`functools.cache` on `_site`, or store sites in PNoStore).

## LOW
8. pno.py:309-310: `if vector is None or reason is not None` + `reason or "no_vector"` is redundant (`_abstain_reason`
   already returns "no_vector"); only the type narrowing needs `vector is None`. Simplify while doing item 1.
9. :132 `_first_max_column` relies on dict-last-wins over a desc sort to pick the EARLIEST valid_start; correct
   (test_only_first_max_column) but add a one-line comment; equal valid_start duplicates are order-dependent.
10. :361 literal `model="NBM_NBP"`; import `NBP_QUANTILE_MODEL` from forecast_state.
11. `PYes` has no docstring; `p_yes()` returns a mutable cached dict (callers could corrupt the cache) - return
    `MappingProxyType` or copy.
12. Missing pinned partition files are skipped silently (:166); surface a `missing_cycles` set for the run manifest.

## Checked and OK
- Boundary: `value_at(t-1)` uses `<=` on integer ns, so visible iff available_at < t. Correct; tested at
  avail (None) and avail+1 (visible) (test_available_at_must_precede...), and for poll_lag (+lag, +lag+1).
- Three-cycle restriction: spy on module-level `read_partition` asserts exactly 13Z/19Z D-1, 01Z D, with 07Z and
  stray 13Z D / 01Z D-1 partitions on disk. 07Z with same date/hour filter also excluded by `_cycle_key`.
- poll_lag uses imported DEFAULT_NBM_QUANTILE_TIMER_INTERVAL_SECONDS (:32,:65); plus60 is a named constant, floor-governed
  detection is by equality to cycle+PUBLICATION_LAG_FLOOR_NS (imported); both tested.
- Purity: only filesystem under nbp_root via partition_path; no network, no truth import; egress gate green.
- verify_first_s6: refuses any day != 2026-06-30 (ValueError, tested); report fields limited to
  climate_day/alignment/vintage_age; test scans field names for fill/bid/p_no/p_yes/truth.
- Function lengths all < 50 (max ~27). Immutability: frozen slotted dataclasses.
- Stale boundary exactly 8 h: fresh at limit, None at limit+1 (tested). Decision-instant boundary tested.

## Test gaps
No tests for: NaN row, corrupt/missing store, unloaded station-day, ladder_p_yes ValueError masking, stale boundary
under poll_lag/plus60, abstention keyed by stress. Tests are AAA-ish; some pack Arrange+Act in one expression - fine.
