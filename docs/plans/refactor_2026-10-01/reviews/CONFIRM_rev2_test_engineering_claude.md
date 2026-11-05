**Rev 2 confirmation, test-engineering review (11 required revisions)**

1. **ADDRESSED.** The incidental-cost fixes are R0.8(a) and (b), placed before the heavy marks in the recommended order (line 478). R0.8(a) injects `sleep=sleeps.append` and asserts `[5.0, 15.0, 45.0]`. R0.8(b) shares one real-writer census fixture and does not stub `run_census_cell`. Both carry a mutation-red acceptance (R0.8, lines 302-312).
2. **ADDRESSED.** §4.6 holds the filled slow-tail table. §4.4 sets T1 at "≤10 min serial, ≤3 min sharded" and withdraws the 5-minute target. The serial floor is shown.
3. **ADDRESSED.** §4.3 gives the per-site verdicts as I asked.
   - Keep: sites 1-2, 8, 9 (`orders_enabled`), 12, 15.
   - Two-sided: site 5.
   - Dropped: site 13.
   - Replacement lands only after it is shown mutation-red (the §4.3 rule).
   - The "-15" metric is restated as "up to 8 sites changed, each justified".
4. **ADDRESSED.** BC-13 now uses a real `subprocess.Popen` zombie from one shared module fixture, with the `_wait_for_zombie` deadline raised to about 5 s (line 529). The "process double" is withdrawn. Forks stay until BC-13 is approved (line 592).
5. **ADDRESSED.** §4.3 "Fixtures" moves only `store_path`, into `tests/unit/conftest.py`. `tally_mod` is explicitly not consolidated, and `interior_instrument` and `_operator_order_ceiling` are left alone.
6. **ADDRESSED.** R0.A items 6 and 7 add the heavy-allowlist meta-test (with a never-list of guard pins plus `test_mypy_ratchet.py`) and the partition meta-check. R0.9 requires T1 to pass under 3 fixed, logged randomly seeds; §4.1 repeats this.
7. **ADDRESSED.** R0.5 is pruned: CT-3, CT-5, CT-6, CT-10 and CT-11 are dropped with citations. Each remaining CT names an entry point and a red mutation. CT-9 is optional and non-gating. CT-2 now uses a real `Popen` child. CT-12 and CT-13 were added, and CT-12 is a hard prerequisite for R3.1.
8. **ADDRESSED.** §4.4 now carries the 37 modules / 319 items count and the ~326 `-m contract` projection. It also explains the 3 XPASS as the non-strict report-only studies (`test_no_side_ldobf_validation_2026_09_14.py:673,714`) and notes the archive-regeneration skips.
9. **ADDRESSED.** `EXCL` lives once in `scripts/ci/run_tier.sh`, and a unit test asserts all three exclusions (R0.A item 5). `addopts` is untouched. T3 no longer repeats the engine contract hosts that run in T2.
10. **ADDRESSED.** §4.1 says "CI runs T4 only", marks bubblewrap on `ubuntu-latest` as HYPOTHESIS, and says tiers never replace the post-merge full gate.
11. **PARTIAL.** The five roughly 5-second tests appear as a HYPOTHESIS row in §4.6 ("open before marking; inject clocks where the wait is real"). No R-step owns it. This is acceptable as a follow-up.

**New material objections from Rev 2:** none. Three minor notes:
- **Partition formula:** the R0.A item 7 formula should define `heavy ∖ contract` as excluding `tests/integration`, so the terms stay disjoint and are not double-counted against `integration ∖ contract`.
- **Meta-check cost:** the meta-check needs nested collect-only subprocesses inside T1, like `test_probe_containment.py:3.2 s`. Expect about 15-20 s added to T1 (PROJECTED), which is still inside the ≤10 min budget.
- **Census tests (§4.6 rows 6-8):** if they are tagged "fast", T1 pays the shared fixture cost of about 55-60 s at first use. Re-measure after R0.8(b) and keep the file `heavy` unless the fixture is cheap.

**Verdict for Rev 2: APPROVE**