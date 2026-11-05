**Verdict: APPROVE.** Nothing in r3 would void the single verdict run, break a hard constraint, or make the pre-registration non-blind. One C6b defect is HIGH, though, and has to be fixed when C6b is implemented, before Doc A FINAL (N-1 below). If it isn't, the C1 failure mode comes back: the cross-check source turns out to be infeasible at E+2 instead of before FINAL.

**Scores (1–10):** correctness vs governing texts 8 · architecture/idiom fit 8 · test coverage 7 · risk mitigation 8 · scope minimality 7 · feasibility 7.

## Checked in code

| Plan claim | Result | Evidence |
|---|---|---|
| C6b: the truth fetch and the dataset use different storage | TRUE | `settlement_truth_dataset.py:343-351` (`window_zip_path` = `cache_path_for_url(cache_dir, url, ".zip")`, refuses on a miss); `:354-405` (sidecar is `cache_dir.with_suffix(".sha256")`, digest verified before reading members); `:279-280` window ends 2026-09-28; `:11-14` no network I/O. `iem_cli_fetch.py:24-27` stores text revisions under `<LOC>/…`. `fetch_bytes_cached` calls `_refuse_afos_cli_write`. A fetch is genuinely needed. |
| C6b: `window-zip` "uses the paced `IemCliTransport`" | **FALSE as written (N-1)** | `scripts/archive/iem_cli_fetch.py:161` `ACCEPT = "text/plain"`, `:207` "the transport is text-only", `:255-260` returns `FetchedText(text=…)`. The base transport always decodes: `src/breezy/ingest/http.py:831-836` runs `body.decode("utf-8", errors="strict")` and raises `DecodeError`. `afos_url` uses `fmt=zip` (`settlement_alignment_study.py:428`), so a real zip body fails on the live path. A fake transport handing back bytes would let the planned tests pass anyway. |
| C6b: launch window, cache lock, subcommand site | TRUE, with a path fix | `iem_cli_fetch.py:638-650` (subparsers), `:661-662`, `:742-744` (the launch-window check is in `main`, so a new subcommand inherits it), `:687-692`. The file is `scripts/archive/iem_cli_fetch.py`, not `scripts/analysis/` as the review brief says. |
| C6b(b): opt-in window, `--output-dir` | TRUE | `:1252-1264` `--include-extension` pattern; `:1226-1239` `validate_output_dir`; `:1275-1278` opt-in branch. |
| Cross-check format | Compatible | `maker_stage0_inputs.py:299-320` reads parquet columns `station, climate_day(date), status, tmax_f` and keeps FINAL rows only, so window days after E with no product drop out silently. |
| C2: preflight runs before the claim | TRUE | `driver.py:147-148` runs `_preflight` before `_run_verdict` / `claim_verdict_run` (`:177-187`). `preflight.py:146` checks only that the cross-check parquet exists; `:161` checks only the truth sha. Placing the new hashes and the E recompute in `preflight` is correct. |
| C2b: CLI layer | TRUE | `maker_stage0_replay.py:97` (sha), `:151` (RunConfig), `:172` (`drv.run`). Mode flags are mutually exclusive at `:112-115`, so "verdict mode" can be derived. The driver is untouched. |
| C4 / C1b: census cost and batching | TRUE | `scripts/analysis/maker_tape_census.py:281-296` scans and classifies every instance on every invocation; `:307-317` converts every CLEAN instance in full. Batching is justified. |
| C4: trigger is outcome-blind | TRUE | `src/…/maker_tape_census.py:634-660`: `COVERED` depends only on spans and coverage, never on prints. Counting `COVERED ∧ listed_in_time` leaks no outcome. |
| C1b: what `main` does today | TRUE | `:474` `required=True`, `:507` full rows written, `:518-519` provenance/report printed, `:520` `_EXIT_UNSCREENED`. |
| C5: ledger key sets | TRUE | `ledger.py:66-69`, `:148-149` (`set(entry) != expected`), `:200-211` (`mine` filtered by sha only), `:224-253`. |
| §6: timers | TRUE | ingest-frequent `:27-30`, rotate 09:00, truth fetch 11:40, truth dataset 12:40, ingest 00/06/12/18:15, nbp 02:05. Nothing else owns 10:05Z, so `test_deploy_timer_hours.py:113` passes. |

## BLOCKING issues

None, under the round-3 definition.

## Non-blocking items to fold in during implementation (ranked)

- **N-1 (HIGH) — C6b transport cannot carry a zip.**
  - Problem: the hardened transport decodes every body as strict UTF-8 (`http.py:831-836`; `iem_cli_fetch.py:161,207,255-260`), so `window-zip` as specified fails on a real `fmt=zip` response.
  - Fix, chosen and stated in the C6b brief — one of:
    - (a) a bytes-returning `fetch_afos_cli_zip` on a `PacedIemTransport` subclass that skips the decode. This touches `src/breezy/ingest/http.py`, so security-reviewer signs off.
    - (b) fetch `fmt=text` and give `settlement_truth_dataset` a text-window reader. The splitter already exists: `split_iem_afos_products`, `settlement_alignment_study.py:466-480`.
  - Add `test_window_zip_fake_transport_mirrors_real_bytes_contract`: the fake must go through the real decode seam, or the test is vacuous.
  - Add a Doc A FINAL precondition: one live positive-control fetch of a small, already-final window (one station, e.g. 10-01..10-03) into a scratch cache, parsed end-to-end by `read_window_issuances`. This proves feasibility before any block-2 byte is read, as the r3 brief's C1 required. It also closes U-3.
- **N-2 — the `--include-maker-s2b-window` run must restrict cities.** `archive_windows` iterates every PM.us registry pair, NYC included (`settlement_truth_dataset.py:303-308`). No NYC s2b zip will exist, so `window_zip_path` raises `ArchiveCoverageError` (`:346-350`). Either pass `--city LAX --city MDW --city MIA --city SFO` in §6 step 2, or emit the s2b window only for maker stations. Add the test.
- **N-3 — `window-zip`'s refuse-overwrite conflicts with R9's "retry next day".** The URL is fixed, so the zip filename (a hash of the URL) is fixed too. A 200 response with partial content (max climate day < E) would be committed and could never be replaced. Validate before committing: parseable, and max FINAL day ≥ E. Otherwise write nothing and leave the sidecar alone. Append the sidecar line atomically under the same lock.
- **N-4 — v2 branch of `verify_set_matches_rule`.** `last_final` is taken from `max(day for _, day in truth.finals)` (`frozen.py:201`), and `truth.finals` holds only the licensed keys, so it can be at most E. The v2 comparison must be `min(last_final, trigger_day)` on both sides, mirroring v1's use of `LAST_ALLOWED_DAY`. Otherwise any pin with `last_final_day > E` is refused. It is refused before the claim (C6), so this costs a day, not a void. Add the test.
- **N-5 — the C1b/C4 chain hash is ordered wrongly.** The C1b line is appended before any tape is read (`run_census` ≤ `:285`), so it cannot hash this invocation's rows. Specify that it carries the chain over previously committed rows, plus a second post-read line (or the `close` line) for the current rows.
- **N-6 — the trigger unit's `RuntimeMaxSec=3600` is a guess.** Every invocation converts every CLEAN instance (`:307-317`) and cost grows with tape. Derive it from the U-8 measurement with W1-style byte scaling, and keep the worst-case end before 15:10Z. A killed check still counts toward forfeiture, so repeated kills stall E. Add a no-progress alert per LESSONS ("long runs need a stall watch").
- **N-7 — §6 step 3 is squeezed.** The full Stage A starts after the ~13:00Z cross-check pin and "must end before 15:10Z". Allow step 3 to run on the next day's 10:05Z slot. Nothing scored depends on it running the same day.
- **N-8 — C5 `_refusal` union.** When matching on `block_first_day`, build `mine` from sha matches *or* block matches, so that `_addendum_refusal` (`:186-197`, which uses `mine[-1]`) checks against the latest run of that block, not the latest run of that sha.
- **N-9 — verdict launch time.** The nbp nightly (02:05Z) peaks at 10–24 GB. "After 02:05Z" should be "after the nbp-nightly unit is inactive" (check `ActiveState`, not `is-active`), to stay within the MEMMAX/RSS rules.
- **N-10 — U-8 timing read.** Re-reading 10-12 under the 10-12 sha prints the full `_report` (C and the S-1/S-5 lines) to stdout. Send stdout to a sealed file nobody reads, and say so in Doc A.
- **N-11 — path hygiene.** Cite `scripts/archive/iem_cli_fetch.py` explicitly in C6b and in Doc A §1.

## Answers to P-1 / P-2 / P-3

- **P-1 (disjoint blocks vs pooling): disjoint.** Amendment :71 forbids a second scoring pass on the set and :77 requires a new dated declaration with its own frozen set. L-56 forbids counting the motivating sample toward n. Pooling would re-score block 1.
- **P-2 (realised vs full-range forfeiture): realised, from the read-ledger, with 132 as the fallback.** Defensible because every invocation is ledgered before any tape is touched, with a chain hash, and days > E are refused in code (C1b). Fall back to the full 132 if peers reject narrowing (U-6).
- **P-3 (ledger date-overlap guard): yes, scoped to `block_first_day`.** `_refusal` keys on sha alone (`ledger.py:203`), so a copied Doc B with a fresh sha would be a fresh claim. C5's per-block guard plus the C2b v1 sha pin closes that hole without touching v1 behaviour.

## Claims found FALSE

- §3 C6b "uses the paced `IemCliTransport`" for a `fmt=zip` URL (N-1). That transport is text-only by construction (`iem_cli_fetch.py:207`; `http.py:831-836`).

Every other r3 citation I re-checked held.