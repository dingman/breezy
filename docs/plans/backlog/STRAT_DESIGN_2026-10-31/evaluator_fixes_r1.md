# card_e_cli_vs_twc.py — merged review fixes (2026-10-31 ~05:40Z), BINDING before the single real run

Verified green: focused tests via `scripts/ci/run_tests_no_egress.sh` EXIT=0 (13 tests), ruff/mypy clean, dry-run makes no network
connections. Statistics recomputed CORRECT (T1 gate k ≥ 55 at N=4080; Holm first step 6/6/5/5 at n 90/71/65/63; CP upper bound;
exhaustive verdict). Mismatch/parse/transport logic conforms to prereg_r2_1.md. Fixes below from python-reviewer (P) and
silent-failure-hunter (S), blind to each other.

## BLOCKERS (must land; all with tests)
B1 (P1) `--prereg` (Path) + `--prereg-sha` (str), both required; at the top of `execute`, before `assert_one_look`, compute
   `file_sha256(prereg)` and refuse on mismatch or if the file still contains "PENDING". Frozen value: 4f490f4b255ab34b214251f19500f66ed487bb68a4e780a7e8c3108c09d34070.
B2 (P2) Per-side label: a side is KILL iff not a side PASS AND the CARD is KILL (prereg §6); compute the card-level kill first, drop the
   per-side Clopper–Pearson "killed".
B3 (P3) Freeze the constants as module constants and REMOVE the flags: P0=0.01, ALPHA_T1=ALPHA_T2=0.025, SAME_SIGN_SHARE=0.80,
   KILL_UCB=0.02, SIDES=(high, low); keep `--start/--end` but assert they equal the frozen window from prereg §3; assert the Holm
   family size == 48 in `side_statistics`.
B4 (P4, S9) Remove `--cli-pull-ts`; stamp `datetime.now(UTC)` immediately before the first IEM request and before the first Kalshi
   request; write both timestamps, the stations-file sha256, the prereg sha and the verdict into the parquet schema metadata AND the markdown.
B5 (P5, S7) Dry-run must not consume the look: refuse `--dry-run` unless `--out-dir` differs from the default evidence dir; no default
   out-dir (require it explicitly).
B6 (S1) Fetch failure aborts BEFORE any write: after both pulls, if `kalshi_errors > 0` or `iem_errors > 0` (or any side "blocked")
   raise SystemExit(2) with a per-side error table on stderr; never emit outputs on a partial pull.
B7 (S2) `_PULL_ERRORS` = retryable transport errors only (`OSError`, the transport's error type, HTTP 429/5xx); programming errors
   (AttributeError/KeyError/TypeError/RuntimeError) propagate.
B8 (S3) IEM retry: 429/5xx and non-200 with exponential backoff (cap 5 attempts, ≤ 1 req/s), then abort per B6.
B9 (S4) IEM empty/truncated body guard: require ≥ 1 parsed CLI product per city per side over the window (frozen minimum) else treat
   the city as fetch-failed (B6); record the raw body sha256 per city in the markdown.
B10 (S8, P10) Atomic outputs: write parquet and markdown to temp files in out-dir and `os.replace` both only after both succeed.

## SHOULD (cheap, irrecoverable after the look)
S5 separate `kalshi_reason` / `cli_reason` columns in parquet + exclusion tables. S6 report overlap/conflict counts between the
historical and live Kalshi copies and confirm historical rows carry status "finalized" (fixture test); note the client cutoff is
2026-07-04. P6 half-split = first ⌊n/2⌋ matched days per side (or document the calendar split as a deviation). P7 abort if the paired
total < 50% of the per-side cap (status-string drift guard) and print the status Counter. S10 keep the last FINAL CLI product, count
overwrites. S12 log HTTP code on fetch errors.

## NON-BLOCKING
P8 tests for half_for, half_statistics, tally_buckets, split_iem_products, _whole_degrees, rejection_threshold, parse_sides,
assert_one_look, render_report. P9 size: optional split into card_e_stats.py / card_e_parse.py — DO NOT do it now (post-freeze churn).
