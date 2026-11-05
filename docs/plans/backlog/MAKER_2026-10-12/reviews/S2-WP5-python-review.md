# S2 WP5 python review (worktree maker-s2-wp5, HEAD 12ee12ba)

Verdict: REQUEST_CHANGES (2 HIGH, 5 MEDIUM, 3 LOW)
mypy: 0 errors, "Success: no issues found in 7 source files" (5 modules + 2 test files)
Gate: `[breezy] gate: phase1 rc=0 phase2 rc=0` (63 + 41 = 104 passed; brief said 76, count is higher than briefed)
Sizes: stats 363, verdict 399, tables 324, rows 195, scored 86 lines (all < 400, verdict has 1 line of headroom).
Longest function: analyse_hypothesis 42 lines (< 50). No asdict, no network, no open(); only tables_from_csvs does I/O (Path.read_text).

## HIGH

1. CSV trust boundary raises untyped, un-located errors.
   File: scripts/analysis/maker_stage0_rows.py:124-153 (_coerce / _from_csv)
   Issue: `int("1.5")`, `float("x")` surface as bare ValueError with no row number or column. Blank non-null
   cell raises "blank cell in a non-null column" without naming either. Missing-column error is the only
   located one. No test exercises any malformed cell (pytest.raises absent from both files except NoBidBearingDays).
   Fix: define `class CsvCellError(ValueError)`; wrap the per-row dict build in try/except (ValueError, TypeError)
   and re-raise `CsvCellError(f"row {n} column {k!r}: {raw!r} ...")` from the cause; add parametrized failure tests
   (bad int, bad float, bad bool "True", blank non-null, short row).

2. Short/ragged rows are silently mis-parsed.
   File: rows.py:127-135, 153
   Issue: csv.DictReader fills missing trailing cells with None (restval). `_coerce(None, str)` returns
   `str(None)` == "None" (silent corruption of station/unit_hypothesis/truth_final); int/float raise TypeError (not
   ValueError). A truncated file therefore yields garbage rows rather than a refusal. Extra cells land under key
   None and are ignored.
   Fix: build the reader with `restkey`/`restval` sentinel or check `None in row.values()` / `None in row` and raise
   CsvCellError("row n has wrong cell count"). Test with a truncated final line.

## MEDIUM

3. No property-style round-trip. test_csv_column_contract_and_roundtrip (verdict test :694) is one example.
   Fix: parametrize/hypothesis over floats (0.1+0.2, 1/9, 1e-300, -0.0, inf), bools, None, strings with comma/quote/newline.
   Known lossy case to pin or fix: `str | None` field (census_reason) with value "" is written blank and read back
   as None (rows.py:127-129). `nan` is accepted by float() and silently flows into p_yes (no range check on p_yes in [0,1]).
4. `__all__` is misleading. verdict.py:32-45 lists only re-exports and omits its own public API (decide, analyse_all,
   Decision, HypAnalysis, UNDERPOWERED...); tables.py:31-39 omits render_tables/tables_from_csvs/REPRODUCIBLE_BLOCKS.
   Under `import *` the module's own surface vanishes. Re-exports themselves are all intended (CSV API; SdRow/PosRow/
   Section69/BidStats/section_69/bid_stats/days_to_200). `nz` and `in_denominator` are helper-grade but needed by tables;
   acceptable. Fix: use explicit `from x import a as a` re-export form (drop __all__) or list the full public surface.
   stats/rows/scored have no __all__ (fine, but `_SHARED`-style privates are correctly underscored).
5. expectancy treats a missing p_yes as certainty: verdict.py:148 `1.0 - (r.p_yes_point_live or 0)` gives p_no = 1.0.
   section_69 only raises on None for non-VOID rows, so a VOID filled row with None p_yes inflates mean_p_no.
   Fix: skip VOID in expectancy scoring explicitly or raise on None like section_69.
6. Power line has no hand-computed expected value (stats test :72-86: monotonicity and a >0.05 bound only), though the
   brief/plan asks for hand values for Test A/B/power/median/IQR. Add e.g. ps=[0.2,0.4]: crit and P(FAIL|k=2) by hand.
7. Edge tests missing: lower_median/inverted_cdf_iqr with n=1 (code is correct: returns (v,v)); anova_icc with NaN input
   (max(0.0, nan) returns 0.0, so NaN becomes rho=0.0 silently, stats.py:288); an empty groups mapping.
   binomtest in rate_ratio_test_b raises a raw scipy ValueError if l_f > l_f + l_u cannot occur, but n_f/l_f inconsistent
   inputs (l_f > n_f) are not validated.

## LOW

8. tables.py:318 docstring cites `maker_stage0_stats --scored`; no such CLI exists in stats.py (WP7 driver?). Fix wording.
9. Test fragility: verdict test :708 `split(",")[11]` positional; write_text/read_text without encoding (tests :743-745).
10. verdict.py:366 `_lcb(...) or 0.0` conflates a genuine 0.0 LCB with "not estimable"; behaviour is safe today
   (guarded by `None in lcbs.values()` at :377) but the intent is obscured.

## Checked and fine
- Bootstrap: seed 20260919 x 2000 are defaults in breezy.analysis.stats.scoring_core (BOOTSTRAP_SEED/ITERATIONS); stats.py
  passes no override and touches no global RNG; one-sided bound = percentile_interval(alpha=0.10)[1]; test_seeded_... covers reuse.
- anova_icc: n0<2, n_sd==n0, all-equal/denominator<=1e-12 all return rho None (never NaN); truncation to [0,1] tested.
- lower_median n=0 -> None, n=1 -> value; inverted_cdf_iqr n=0 -> None, n=1 -> (v, v).
- Float bytes: `_f` uses fixed-precision format (locale-independent); CSV uses repr; s3 uses json sort_keys; hypothesis names
  sorted; strata/bins fixed tuples. byte-compare test (verdict test :733) encodes and compares all 12 REPRODUCIBLE_BLOCKS
  and asserts the label on the 6 run-time-only blocks (RUNTIME_ONLY_BLOCKS).
- AAA/naming adequate; Test A/B (0.18, 0.72, 1/9), ICC, lower median, IQR have hand-computed expectations.
