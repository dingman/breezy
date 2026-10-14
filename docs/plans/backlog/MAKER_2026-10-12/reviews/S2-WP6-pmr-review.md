# S2 WP6 PMR review (driver, end-to-end semantics, leakage, licence, forking paths)

Worktree `.claude/worktrees/maker-s2-wp6` @2bbcdc1f. Blind review. Paths below are under `scripts/analysis/` unless noted.
Tests were not run; this review is by code read plus an AST import-closure walk.

**VERDICT: REQUEST_CHANGES** (3 HIGH, 7 MEDIUM). Order of operations, progress fields, ledger placement, sidecar sealing and streaming verify clean.

## Verified clean
- Order: `_preflight` (driver:216) -> `claim_verdict_run` (driver `_run_verdict`) -> `_wp0` probe (S-2 sidecar written before `require_clean`) -> S-7 -> `_simulate_all` -> `report.score` (the only `load_truth` call, `_finish`) -> CSVs/sidecars/pins/report. Truth is hashed, never parsed, before scoring. `progress.jsonl` is allow-listed (`runio.PROGRESS_FIELDS`, `ProgressLog.write` raises on extras).
- Delta is not double-applied: WP4 shifts releases/cuts; the adapter shifts only the store lookup (`now - |D|`, age `now - (avail + |D|)`). Equivalent, strict-before holds.
- Sidecars (overlay, plus60, poll_lag, delta0) are written before `seal_sidecars`; `SIDECAR_NAMES` adds delta0; `code_sha` is in the manifest and `s3_inputs`.
- Hindsight is write-only: `n_no_book_wants` is consumed only by the (r)1 denominator, never by the selector.

## HIGH
**H1 Listing-time abstention never applied.** driver `_wp0` (:281) keeps only `delta_ns` from `probed.coverage`; `StationDayCoverage.listing_abstain` (probe_core:355) has no consumer outside WP0. Authority: spec §3 "Abstention ... S not listed by D-1 12:00Z"; r3 L113, L144, L280 (WP2/WP3 brief); `rule.listed_in_time` exists and is called by nothing. Failure: a late-listed ladder is bid, becomes bid-bearing and enters n_sd, though live abstains. Fix: carry `listing_abstain` from `_wp0` into `LoopContext`; use `_no_selector` for those keys; count them in `station_days.csv` (not bid-bearing). Add a RED test.

**H2 Caller-choosable controls defeat the one-shot ledger and code freeze.** replay.py:94 `--ledger` (any path) and :98 `--repo-root`. A fresh ledger path allows a second scoring pass (amendment §3; r4 (c) says the ledger path is fixed and pinned). `assert_clean_tree` and `git_commit` read `--repo-root`, not the tree the imported modules came from. Project memory "Worktree needs PYTHONPATH" shows this mismatch happens in practice. Fix: in a verdict run refuse any ledger other than `DEFAULT_LEDGER`; assert `Path(drv.__file__).resolve()` lies under `repo_root` and that `repo_root` is the git toplevel.

**H3 `--tail-only` reads unlicensed stations.** modes:275 builds `parity = dict(cfg.parity)` and reads NBP and truth for every station given; `--parity NYC:0` is accepted. Amendment §1: stations LAX/MDW/MIA/SFO, never NYC; item 5 is 2026-07-01..09-17 only (range is fixed, good). Fix: refuse unless the station set equals `fs.stations`; derive parity from the ladder, not from the flag (a wrong parity silently yields wrong bands).

## MEDIUM
**M1 Truth-isolation test roots at the wrong module.** test_maker_stage0_driver.py:658 walks `events_build`. The real loop (`station_loop` -> `runio` -> `inputs`) puts `inputs` in the closure, and `inputs.load_truth` is at inputs:323; `modes` imports `report`. The test's own forbidden list names `inputs`, so the same assertion on `station_loop` would fail. Isolation is by call order only (`test_driver_scores_only_after_simulation_completes`). Authority: r4 (i)7. Fix: move `load_truth` and `TruthTable` to a truth-only module; root the closure at `station_loop` and `modes.simulate`.

**M2 Avoidable post-claim voids (each burns the one-shot).** Preflight checks only the truth sha. Missing before the claim: the cross-check parquet (fails inside `score`), `nbp_root/_manifest.json`, `spec`, and `uv.lock` (fail in `pin_inputs`). `verify_set_matches_rule` runs post-simulation inside `score`. `_scan_logs` (driver:211) returns `[]` for a missing `--node-log-dir`, so every day is silently `NODE_LOG_ABSENT` (no outage exclusions) and the ledger is spent. Fix: pre-claim existence and readability of every pinned input; refuse a verdict run when the node-log dir is missing or empty. Pin the node-log directory choice, because it decides OUTAGE and so the denominator.

**M3 Frozen-set census completeness.** driver `_requested` (:189-200) never checks that each frozen (station, date) has a census row; duplicates are last-wins. Only an entirely absent date is caught, and only post-sim (frozen:216). A missing row shrinks the denominator silently. Fix: refuse pre-claim on missing or duplicate keys (amendment §1: "every census day in the frozen set").

**M4 Bench licence and S-5 screen.** modes:223 weights every planned census key, including non-COVERED and OUTAGE days that `run_station_day` skips instantly, so the heaviest pick can measure nothing and `n_replayable_station_days` is inflated. `variants=("primary",)` (modes:221) runs 1 of 5 variants, so `projected_total_s` is about 5x low (r4 (i)9). `--bench N` is unbounded; the licence is 4 then 8. Fix: weight only `_replays` keys; bench all five variants (or scale); refuse N not in {4, 8}.

**M5 D3 hand-over keyed on first in-window event, not instance start.** events_build:178 `_first_ts` takes the first frame (prints only if no frames), so the driver docstring ("frame or print") and the module doc disagree with the code. Two overlapping instances are ordered by first in-window event, so an older quiet instance can cut off a younger busy one. Fix: use instance start from the WP0 ledger or the directory name; align the docs.

**M6 K1 and displacement by no-book rungs.** adapter:`_price_rungs` prices a rung with `ctx.books.get == None` via `decide_bid(.., None, None)` at b_max, so it competes in `select_rungs` (MAX 2) and can become `k1_rung` (fill_pass `_decide`: `next(iter(want))`) without any attempt; it can also push a bookable rung out of the top 2. r4 (e): K1 is first-ranked at the first attempt. Fix: define K1 on the first rung that produces an attempt, or make no-book rungs ineligible in ranking and count them only in `n_no_book_wants`. State the choice in the report.

**M7 Provenance gaps.** `--tail-csv` (driver:330) is re-serialised, so neither the source file nor its tail-only `code_sha` is pinned. `tail_reliability.csv` and `episodes.jsonl` are not in `CANONICAL_SIDECARS`. Fix: pin the tail source sha and `episodes.jsonl`.

## LOW
- L1 Unknown delta defaults to 0 (driver:281, matches `station_day_delta_ns`); report `n_unknown` next to the delta0 table.
- L2 `forecast_valid` persists between decisions, so `forecast_valid_h` can overcount (report-only).
- L3 `_catalog` converts whole instances, so out-of-set bytes (NYC, 10-01) reach scratch though never queried or hashed; state this in the licence note.
- L4 `first_print_instant` is restricted to frozen days, so the `first_replayable_day` cross-check is partly circular; it still catches a late first print.

## Rulings D1-D8
- **D1 ACCEPT.** Matches r3 L154 and spec §3 (release, book update, clock alert). The cite "r4 (d)/(i)1" is wrong; cite r3 L154. A print cannot change the displayed book; only the next frame does (print priority 2 < depth 3, so the frame already reflects it). Omission is leak-safe. First placement waits for the next event, which is conservative. No stale-cutoff alert is needed: the schedule never lets STALE_H (8 h) bind in the window.
- **D2 ACCEPT with disclosure.** Stale and day-mismatch map to their own reasons (CANCEL_STALE, CANCEL_DAYMISMATCH). Only NO_VECTOR, UNKNOWN_ERA and NONFINITE_P_YES share NOT_YET_AVAILABLE, and no summary count keys on `end_reason`, so counts are not conflated. The report must give the three abstain counts separately, because `episodes.jsonl` merges them.
- **D3 ACCEPT the behaviour (single current instance), fix M5 and the docstring.**
- **D4 ACCEPT; conservative in both directions.** Depth ceil lengthens Q0 and A_eq. Ceil on A_gt raises r and g equally, so the residual `r - g = A_eq + 1` is not understated. Print floor credits fewer. The bias runs toward fewer fills, i.e. toward NO-GO, so it is anti-strategy, not neutral. Report per hypothesis the BUYER prints floored to 0 and the share of depth levels raised by ceil (neither is counted today).
- **D5 ACCEPT.** The report must state: the truth is CLI FINAL as a proxy for venue resolution; there is no VOID or UNRESOLVED handling, and days 09-18..09-30 are already past D+14 at run time; days with no FINAL are excluded and counted at any age; band edges are inclusive via `bucket_facts_from_instrument_id`.
- **D6 ACCEPT** (r4 (r)1 ruling; conservative; hindsight but report-only). See M6 for the K1 interaction.
- **D7 ACCEPT.** Disclose: ledger entry consumed, no label, n_sd = 0, all other S3 keys null, and a re-run needs a new declaration (a STOP run holds `scored_episodes.csv`, so an addendum re-run is refused).
- **D8 ACCEPT.** Right pin site (`taker_fee_coefficient_as_of`) and instant (D 00:00Z, inside the 16:50Z D-1..02:50Z D window); the range check runs before the claim. State that θ is constant per day and that fees.py names this function for eligibility, so its use here is a documented exception. No intra-day drift is detectable.
