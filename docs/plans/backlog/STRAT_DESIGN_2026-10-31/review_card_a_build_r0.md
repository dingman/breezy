# Card A build r0 (d8f3e8b9) — merged blind review (python-reviewer + prediction-market-reviewer, 2026-10-31 ~15:40Z)

Evidence (python-reviewer, bwrap no-net): `11 passed in 0.28s`; wrong sha → rc=2 `prereg sha256 mismatch`, no writes; `POLYMARKET_US_EXEC_STATE_DB` unset → rc=2; with the store set, correct-sha `--dry-run` → **rc=2 `own-order set cannot be built: 141 slug-less intent(s) never filled`**, NO_WRITES. Store census: 165 intents, **0 with a slug**, 25 `fill_by_fingerprint` entries, 141 unresolved, 154 created in 2026-10. ruff/format/mypy clean on the new files; `lint-imports` 13 kept 0 broken; the 4 contract tests scanning `scripts/analysis` pass. Both VERDICT = REVISE.

## Blockers
- **P1 (prereg, not code).** Prereg D5 as frozen refuses on the live store (rule implemented correctly at `wp7b_census.py:422-425`). `SubmitIntent` has no other instrument field. The one look cannot run under sha 4abc0915. → architect ruling on the amendment (see below); new sha + new freeze; thresholds untouched. The dry-run refused BEFORE reading the catalog, so no outcome data was seen (not a look).
- **C1 (pm).** `_slack_at_q` (`wp7b_census.py:265-273`) adds a per-contract price to the whole-fill fee `rounded_fill_fee(price, q)` and compares against per-contract `100−2n` → q>1 counts understated by ≈q. Required: leg 1 `q·Σask¢ + Σfee_q¢ ≤ q·(100−2n)`, leg 2 `q·Σbid¢ − Σfee_q¢ ≥ q·(100+2n)`. Add boundary tests for `_slack_at_q` / `_prize_lines`.

## Should
- C2 (pm) unit line can be satisfied by a zero pad (`:737-742`, `:833-838`): use the first nonzero `ask_size`; `unit_ok=False` if none; test `unit_ok=False` → INCONCLUSIVE at `:521`; the per-record leg "clear" strings at `:829-830` must not be written when `unit_ok` is False.
- C3 (pm) `_label` (`:520-525`) untested: add 29 vs 30 station-days, 6 vs 7 dates, zero clears → KILL, under-floor with a clearing frame → INCONCLUSIVE (never KILL, never PASS).
- C4 (py) `_ro` (`:329`) builds the sqlite URI without percent-quoting → use `Path.as_uri()`/`urllib.parse.quote`.
- C5 (py) two `os.replace` calls (`:495-496`): write the parquet first, the markdown LAST, and make `_carries_sha` treat a lone parquet carrying the sha as a prior look.
- C6 (py) print the real slug-less count at `:924`; `ts_event_ns=1` magic at `:241`; `_walk_dirs` `low-` substring match at `:644` → anchor the pattern.
- C7 (pm) assert prices sit on the tick (half-even rounding at `:227-229` would hide an off-tick quote); test `bid == ask` crossed (`>=` at `:191`), 60 s vs 60.001 s, stale-only rung, exact 60-min boundary, size-0 on a present side, `intent.slug` branch.

## Notes
- N1 Leg inequalities (`:249-262`), fee routing (`:235-246`, no maker branch), frame selector (`:180-222`), one-sided/crossed (`:289-298`), own-order normalization (`:302-309`), constants (`:138-159`), atomic emit + same-sha refusal (`:487`, `:968`): CONFORMANT.
- N2 G1 BUYER counts omitted: RULED legitimate (H3) — `CatalogSession.read` → `_catalog` mkdirs + converts a scratch catalog (`maker_stage0_catalog_read.py:145-179`); artefact states counts not taken.
- N3 Builder's F2/F3 remark is correct: legs are decided alone; a 2-rung uncrossed book cannot clear both.

---
# P1 ruling (architect, 2026-10-31 ~16:05Z) — own-order resolution amendment → prereg r2

Root cause: `arm_slot` stores `slug=None` whenever K=1 (`submit_intent.py:1005,1013`) and production `EXEC_PAR_MAX_CONCURRENT_INTENTS = 1` (`exec_par_constants.py:15`) → NO intent ever carries a slug (r1.1's "older records" premise was wrong). No other store key family maps a never-filled intent to an instrument (`venue_id/*` = client order id only; `resting/*` only bound maker rests since 10-25; `resolver/*` only AMBIGUOUS).
Options rejected: (b) drop days with unresolved intents = the L-65 date cut and misses D+1 markets; (c) prefix over-exclusion = denominator ≈ 0; (a) by intent id = no log line carries it.
**RULING = (d):** rebuild `intent_fingerprint` (`exec_intent.py:38-49`: instrument_id, side, quantity, price, TIF, client_order_id) from the node-log `[Risk] SubmitOrder(...)` lines and match the sha256; positive control = the 25 fill-resolved intents must also resolve by logs to the same base slug; any residual unresolved / double-matched / unreadable → exit 2. Thresholds, window, B and F untouched → new sha + new freeze after review.
Coverage CORRECTION (coordinator measurement 16:10Z; the architect's "first log 10-14" was a listing artefact): `~/.local/share/breezy/logs/breezy-trade-*.log` = 95 files since 2026-09-04, all 40 window dates present, 2411 SubmitOrder lines (09-21..09-23: 4; 10-01..10-05: 32; 10-24..10-30: 2411 total incl.); the journal carries 0 SubmitOrder lines (files only).
