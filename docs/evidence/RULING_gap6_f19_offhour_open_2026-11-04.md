# RULING — GAP-6 S0 F-19 halt on off-hour market opens (2026-11-04)

Backlog #1 (GAP-6 Kalshi S0 kill screen). Peer loop convened under prereg F-19 ("Mismatch found at S3b ⇒ HALT to peer
loop, no verdict"). Ruled OUTCOME-BLIND, before any `verdict`: no reviewer read any `result`, settlement, expiration or
price value; the one look (F-13) is unspent (`.S0.look` absent, no `S0_*.json/md`).

Prereg: `docs/plans/backlog/GAPS_2026-11-01/gap6_sample_and_size/prereg_r1.md` — UNCHANGED (sha 2073860f…, enforced by
`FROZEN_PREREG_SHA`). Prior ruling: `docs/evidence/RULING_gap6_b8_d2_2026-11-02.md`.

## Facts (timestamps only)
- S3 fetch sealed 48/48 series + MANIFEST.sha256 at `/mnt/storage/breezy/kalshi_depth/s0_raw/` under code a983da4f
  (units breezy-kalshi-s0-fetch 06:23–06:38Z and -r1 06:56–09:54Z 2026-11-04; resume skipped the 2 series sealed first).
- `s0 audit --date 2026-11-04` exited 2: `SemanticsHalt: HALT: F-19 bucket ends are not whole hours after open`.
- 42,542 rows; every candle `end_period_ts % 3600 == 0` (clock-aligned, no exceptions). 41,930 markets open exactly on
  the hour; 612 (1.44 %, 40/48 series, mostly 2025-11/12, 2026-01/02/04) open off the hour (e.g. 06:24:29Z); their first
  end is the next clock hour (546 partial first buckets) or later (66 gaps).
- `_check_first_hour` (`scripts/analysis/kalshi_s0.py:448-455`, reached only via `selections()` in audit/verdict, never at
  fetch) halts if `min(ends) < open+3600` or any `(end−open) % 3600 ≠ 0` — a premise valid only for on-hour opens, taken
  from the single on-hour P-0 probe market (also stated in the module docstring ~:17).
- F-10 already anticipates off-hour opens ("first whole LST hour starting ≥ open_time … ref_end = hour start + 1 h") and
  `reference_hours` implements it. All 1,752 references for the 612 rows lie on the clock grid (1,251 hit a candle end,
  501 are F-11 misses). 36 references fall on a partial first bucket (KXLOWT D-1 18:00 LST pre-cell, 2025-12-13/15, MIA,
  NYC, PHIL ×6; market opened 21–46 min before ref_end).

## Rulings
1. **Implementation correction, not a rule change (APPROVE-CORRECTION ×2).** F-19 defines what `end_period_ts` means
   (bucket END of (end−1 h, end]); it does not require on-hour opens. The corrected check, one rule for all opens:
   `expected = (open // 3600 + 1) * 3600`; HALT iff any `end % 3600 ≠ 0` or `min(ends) < expected`; count a
   `first_hour_gap` iff `min(ends) > expected`. For on-hour opens this is identical to the old rule. No successor prereg.
2. **The 36 partial-bucket references are KEPT**, exactly as F-11 is written (the candle with `end == ref_end`; no
   carry-forward, no exclusion). The statistic reads only `yes_bid.close` (`no_ask`), the bid at the instant `end` — the
   same observable whatever the bucket length. MISS/EXCLUDE would add a rule not in the prereg. Bias direction cannot be
   argued without outcomes; at most +6 station-days to the LOW 18:00 pre cell.
3. **Sealed raw stays valid; no re-fetch.** `load_sealed` binds the prereg sha, the MANIFEST and each payload's
   `prereg_sha`, not the script version.
4. **Re-running `audit` after the fix is not a second look** (`audit_projection` drops `result`; `*_audit.md` is not a
   look). Order: fix (TDD) → reviews → gate → merge → `audit` on the same sealed raw → audit review → `verdict` (one look).
5. Code obligations: fix the module docstring premise; replace the hard-coded audit `"F19": "consistent (empty series
   untested)"` with real counts (off-hour opens; partial-bucket references per cell; gaps); do not touch
   `reference_hours` or `exact_candle`. Pinning tests: keep `test_m2_first_candle_before_open_plus_hour_halts`,
   `test_m2_misaligned_bucket_offset_halts`, `test_m2_first_candle_gap_is_counted_not_halted` unedited and green; add
   `test_m2_on_hour_check_equivalent_to_prior_rule` (parametrized old-vs-new equivalence for on-hour opens) and
   `test_m2_off_hour_open_partial_first_bucket_accepted` (also asserts `selections()` unchanged for an on-hour row).
6. Audit-time checking is sufficient for S0 (the raw is sealed); if row #6 capture/census reuses the fetch path it must
   call the same function.
7. No with/without sensitivity on the 36 references or the 612 markets will be run (that would be a second look).

## Signatures
- prediction-market-reviewer: APPROVE-CORRECTION (Q2 KEEP; field `yes_bid.close`).
- architect: APPROVE-CORRECTION (path (a); pinning tests above).
- Coordinator: rulings 1–7 adopted; the two reviewers' halt formulations (`min(ends) ≤ open` vs `min(ends) < expected`)
  are equivalent under clock alignment; the architect's form is adopted.
