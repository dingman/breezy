# S2 second look — plan r3 coordinator delta (r3.1), 2026-10-16

Status: **READY** (plan r3 + this delta). Decision owner per Pre-Auth; no operator cap involved. Round-3 blind reviews: architect APPROVE (one HIGH note), prediction-market APPROVE, python REQUEST_CHANGES (one blocking item, identical to the architect's HIGH note). Review history: `reviews/S2-second-look-r{1,2,3}-{architect,pmr,python}.md`. The round cap (3) was reached; this delta adopts the reviewers' concrete fixes verbatim in substance and closes the only blocking item. It amends `S2_second_look_plan_r3.md`; where the two differ, this delta governs.

## 1. Blocking item closed: C6b transport (architect N-1, python B1)

**Defect.** r3's `window-zip` subcommand "uses the paced `IemCliTransport`" to fetch `afos_url(..., fmt=zip)`. That transport is text-only (`scripts/archive/iem_cli_fetch.py:161` `ACCEPT = "text/plain"`, `:207`, `:255-260` returns `FetchedText`), and the hardened base transport decodes every body as strict UTF-8 (`src/breezy/ingest/http.py:831-836`, raising `DecodeError`). A real zip body fails on the live path while a fake-transport test would pass, so r3's Doc A precondition "C6b merged = producer proven" was vacuous.

**Ruling: option (b), text format.** C6b fetches `fmt=text` through the existing text path (`afos_cli_text_url`, `settlement_alignment_study.py:206-210`, rewrites `fmt` to `text`) and `settlement_truth_dataset.py` gains a **text-window reader** beside the zip reader, built on the existing splitter `split_iem_afos_products` (`settlement_alignment_study.py:466-480`). Rationale: no edit to `src/breezy/ingest/http.py` (29 callers; would need a security sign-off), no new byte-decoding seam, and the single writer / cache lock / launch window / paced transport are all reused as-is. The s2b window is therefore a **text window**, cached as a URL-hashed `.txt` with the same digest-sidecar discipline (`:354-381`), never overwriting.

**C6b, amended unit list (all tests RED first):**
- `iem_cli_fetch.py window-text` subcommand (replaces `window-zip`): per maker station, URL `afos_cli_text_url(afos_url(loc, 2026-09-29, 2026-11-15, limit=3000))`; takes the cache lock; honours `_in_launch_window` (`:661-662`, inherited in `main` `:742-744`); writes `cache_path_for_url(cache_dir, url, ".txt")` + sidecar line atomically under the lock. **Validate before committing (architect N-3):** parse with `split_iem_afos_products`; require max FINAL climate day ≥ the requested `--min-final-day` (= E at run time); on failure write nothing and leave the sidecar alone (so R9's next-day retry is possible with the same URL).
- `settlement_truth_dataset.py`: `_MAKER_S2B_WINDOW_START/END` (2026-09-29 / 2026-11-15) behind `--include-maker-s2b-window`; `read_window_issuances` dispatches on the cached file suffix (`.zip` existing path untouched; `.txt` → the text reader); `--output-dir …/maker_stage0_inputs/cross_check_s2b/` under `validate_output_dir` (`:1226-1239`). **Cities restricted (architect N-2, python N4):** the s2b window is emitted only for maker stations (never NYC; `archive_windows` iterates every registry pair, `:303-308`), and the Doc B recipe passes `--city LAX --city MDW --city MIA --city SFO`; test that an s2b run without a maker-only filter is refused.
- Tests: `test_window_text_writes_url_hashed_txt_and_sidecar_under_lock`, `test_window_text_refuses_overwrite`, `test_window_text_respects_launch_window`, `test_window_text_rejects_short_window_and_writes_nothing`, `test_window_text_fake_transport_mirrors_real_text_contract` (the fake goes through the real `FetchedText` seam, python B1's "not vacuous" requirement), `test_maker_s2b_window_is_opt_in_maker_only_and_defaults_unchanged`, `test_dataset_text_window_emits_rows_for_block_days`, `test_zip_reader_path_byte_identical`.
- **Doc A FINAL precondition (architect N-1, PMR 3):** one live positive-control `window-text` fetch of a small already-FINAL window (one station, e.g. 2026-10-01..2026-10-03) into a scratch cache, parsed end-to-end by `read_window_issuances`, with max FINAL day asserted. This proves feasibility before any block-2 byte is read and closes U-3. Its stdout is sealed.
- Independence verdict unchanged: parsing-only; Doc A §1 adds "a shared upstream revision error is invisible to the agreement check; the cross-check never validates truth" (PMR 4).
- Path hygiene: the fetch script is `scripts/archive/iem_cli_fetch.py` (architect N-11, PMR).

## 2. Required implementation-time amendments (adopted)

| # | Source | Amendment |
|---|---|---|
| 2.1 | python N1 | C2b's CLI-layer pin goes behind an injectable seam `main(argv, *, pin_check=_v1_sha_pin)`; it refuses only a **readable** v1 block with the wrong sha and defers unreadable amendments to the driver, so `tests/unit/test_maker_stage0_replay.py` (`cli.main(REQUIRED)` with a nonexistent `--amendment a.md`, :18-19, :65-136) stays byte-unchanged. `replay.py` 185/250 lines. |
| 2.2 | python N3, architect N-4 | C2's v2 branch of `verify_set_matches_rule` compares `min(last_final, trigger_day)` on both sides (today both sides are capped by `LAST_ALLOWED_DAY`, `frozen.py:202-204,208`; `truth.finals` holds only licensed keys so `last_final` ≤ E). Test: `last_final_day = E + 2` is accepted. Without this every normal pin is refused pre-claim. |
| 2.3 | python N2 | C6 `truth_keys` test asserts **superset** (preflight keys = stations × dates ⊇ score keys from `sd_rows`, `report.py:118`); stricter pre-claim can never void post-claim. |
| 2.4 | python N5 | C1b logic is extracted into `_second_look_guard(plan, …)` called from `run_census` (already 68 lines, `:260-327`); `main` stays < 50 lines; `--output` optional only in counts-only mode; existing `run_census(**options)` / `main --output` tests unchanged. |
| 2.5 | python N6, architect N-8 | C5 `_refusal` builds `mine` as the union of sha-matched and `block_first_day`-matched start entries so `_addendum_refusal` (`ledger.py:186-197`, `mine[-1]`) checks the latest run of that block. Test: voided v2 run + addendum on a copied amendment (different sha, same block). |
| 2.6 | python N7 | `first_crossing` and the `listed_in_time` wiring live in a tiny pure module (`scripts/analysis/maker_stage0_trigger_rule.py`, < 80 lines) imported by both preflight and the trigger tool, so preflight does not import the census scripts; rows schema pinned to `(station, climate_day, reason, first_seen_ns)`. |
| 2.7 | architect N-5 | Chain-hash ordering: the pre-read C1b line carries the chain over previously committed rows; a second post-read line (or the `close` line) commits the current invocation's rows. |
| 2.8 | architect N-6 | Trigger unit `RuntimeMaxSec` derived from the U-8 single-day measurement with W1 byte scaling, worst case ending before 15:10Z; no-progress stall watch per LESSONS; a killed check counts toward forfeiture and is disclosed. |
| 2.9 | architect N-7 | §6 step 3 (full Stage A over [S, E]) may run in the next day's 10:05Z slot; nothing scored depends on same-day execution. |
| 2.10 | architect N-9 | Verdict launch condition: `breezy-nbp-learning-nightly` `ActiveState` ∉ {active, activating} (not merely "after 02:05Z"). |
| 2.11 | architect N-10, PMR | The U-8 timing read of 10-12 under the 10-12 sha, and every non-final census run, send stdout to a sealed 0400 file nobody reads; Doc A says so. |
| 2.12 | PMR 1 | Doc A §5: reads in (E, max-invoked] from the crossing batch are a **disclosed expected overshoot** of at most the check lag (≈ 2 days), counted in forfeiture; not an error condition. |
| 2.13 | PMR 2 | S5 `holdout_start_date ≥ max census-invoked day + 2` is tied to the read-ledger by a test, not only prose. |
| 2.14 | PMR 5 | Test: a station-day whose instance is LIVE at check time is `live_unread`, not counted, and a later COVERED re-read never moves E (`test_live_unread_day_never_moves_e`). |
| 2.15 | PMR 6 | §6 step 5 self-check fails closed (refuses Doc B FINAL) when rows on days ≤ E disagree on `reason == COVERED`; other disagreements are disclosed only. |
| 2.16 | PMR 8 | Sweep allowlist is an exact set of (file, line-pattern) pairs. |
| 2.17 | PMR 9 | The pre-declared C7 bench exception records pre/post `CODE_SHA` and bench numbers on the ledger line; a test/CI check asserts the C7 merge touches only `probe.py` and its split module. |
| 2.18 | PMR 10 | Truth timer stuck ≥ 3 days with no advance → dated peer ruling (named next action; folds into R9/R10). |
| 2.19 | python N8 | U-8 also records how often the c−2 day is unread at check time. |
| 2.20 | PMR 7, python | Pure-function tests first (`first_crossing`, `check_first_replayable`, ledger key sets); the v2 world (D11) is budgeted at 1–2 days. |

## 3. Freeze scope and order (restated)

C6b (text) → live positive-control fetch → Doc A FINAL + Doc B DRAFT → C1 → C1b → C4 (+ unit, 2 L-12 entry rows) → C2 → C2b → C3 → C5 → C5r → C6 → D4 → W1 measurement (10-21) → C7 decision (10-24). Everything else after the evidence commit. Nothing in this delta changes a frozen constant, an S-* screen, the NO-SEND firewall, or any FINAL document.
