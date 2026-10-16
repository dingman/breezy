# Round-3 Python review: MAKER-S2 second-look plan r3

**Verdict: REQUEST_CHANGES.** There is one blocking item (B1), and a second item that contradicts the plan's own claim and should be fixed in the same pass (N1).

## Scores (1–10)

| Axis | Score |
|---|---|
| Correctness vs governing texts | 8 |
| Architecture and idiom fit | 7 |
| Test coverage (happy, failure, edge) | 7 |
| Risk mitigation | 8 |
| Scope minimality | 7 |
| Feasibility | 5 |

**Overall confidence: MEDIUM.** Most r3 mechanisms check out in code. C6b's transport claim is false as written.

## BLOCKING

### B1. C6b "uses the paced `IemCliTransport`" cannot fetch a zip; the fake-transport tests would pass while the live fetch fails
- **Plan claim (C6b):** `window-zip` fetches `afos_url(..., limit=3000)`, whose URL has `fmt=zip` (`settlement_alignment_study.py:430`), through `IemCliTransport`. It then writes the zip and a digest line.
- **What the transport actually does:**
  - `IemCliTransport.fetch_cli_text` returns `FetchedText(status_code, text=result.text or "")` (`iem_cli_fetch.py:255-260`).
  - Its docstring at :207 says "the transport is text-only". The Accept header is `text/plain` (:161).
  - The shared `HttpTransport._fetch` strictly decodes the body: `body.decode("utf-8", errors="strict")`, raising `DecodeError` (`src/breezy/ingest/http.py:831-836`).
  - `FetchResult` carries only `text` and `sha256`, never the raw bytes (`http.py:465-471`).
- **Consequence:** a ZIP body (`PK\x03\x04…`, binary) is not valid UTF-8. The live request would raise `DecodeError`.
- **Why the tests don't catch it:** every C6b test uses a fake transport. A fake that returns bytes passes, and the real transport does not. The plan itself says the live fetch is unproven (U-3), but it also makes "C6b merged, gate green" the proof that the producer exists (Doc A preconditions for FINAL). That precondition is therefore vacuous.
- **Why this blocks:** under the plan's own rule Doc A cannot reach FINAL, so the whole block is stuck.
- **Required fix** (any one of these):
  1. Add a bytes-returning fetch beside `fetch_cli_text`:
     - Do it in the `IemCliTransport` subclass, or in a thin hardened sibling of `_fetch`.
     - Return the raw body and its sha256 with no decode.
     - Set Accept to `application/zip`.
     - State that `src/breezy/ingest/http.py` is not edited. It has 29 callers.
  2. Switch the s2b cross-check to the text format.
     - Fetch with `afos_cli_text_url`, which rewrites `fmt` to `text` (:206-210). The existing `fetch` path already handles that.
     - Add a text-reading path to the dataset instead of the zip reader.
     - This changes C6b (b) substantially.
  3. State explicitly that zip is infeasible, and STOP Doc A at the named peer ruling.
- **Test to add either way:** one test that drives the real `IemCliTransport._fetch` against an `httpx.MockTransport` (or equivalent) serving real zip bytes. It must assert the file written is byte-identical to the body served and that its sha256 matches the sidecar line. A fake `CliTextFetcher` cannot prove this.

## Required fixes that are not blocking (fold in at implementation)

### N1. C2b breaks existing tests; the plan's "unchanged" claim covers only the driver tests
- **Placement problem:** C2b loads the amendment in `maker_stage0_replay.main` before `drv.run`.
- **Tests that break:** `tests/unit/test_maker_stage0_replay.py` calls `cli.main(REQUIRED)` with `--amendment a.md` (a nonexistent file) and `--amendment-sha abab…` (:18-19). It monkeypatches `drv.run`.
  - `test_main_maps_refusals_to_exit_two…` (:65)
  - `test_main_maps_a_void_abort…` (:77)
  - `test_main_prints_the_summary…` (:88)
  - `test_main_returns_zero_for_a_reported_s4_stop` (:100)
  - the parametrised pre-claim and post-claim exit-code tests (:111-133)
  - `test_a_failed_void_still_exits_three…` (:136)
- **What would happen:** an early `load_amendment` would raise `FrozenSetRefused` ("amendment unreadable") and return exit 2 before `drv.run` is reached.
- **What to change:** put the pin behind an injectable seam, for example `main(argv, *, pin_check=_v1_sha_pin)`. Alternatively, defer to the driver when the amendment is unreadable and only refuse on a readable v1 block with the wrong sha. Then say in the plan which replay tests change, or that none do.
- **Size limits:** `replay.py` is 185 lines against `LINE_CEILING = 250` (:21), so there is room.

### N2. C6 `truth_keys(stations, dates)` versus score keys
- `score` builds its keys from the simulated rows: `{(r.station, date) for r in sd_rows}` (`report.py:118`).
- A helper taking only `stations` and `dates` yields all 4 × days, which is a superset.
- That is stricter than score, so it cannot cause a post-claim void. But `test_preflight_and_score_truth_keys_are_equal` may fail honestly on the v2 world if some station-days produce no `sd_rows`.
- Decide up front whether the test asserts equality or superset.

### N3. v2 `verify_set_matches_rule` comparator
- At `frozen.py:202-204`, `last_final` is `max(day for _, day in truth.finals)`. That mapping holds only the licensed keys, so it tops out at E.
- Both sides are capped by the `LAST_ALLOWED_DAY` constant (10-13) at :202-204, :208 and :71.
- The v2 branch must replace that constant with `trigger_day`.
- If it does not, it is refused pre-claim whenever `last_final_day > E`, which is the normal case given the plan's own ≈ 2-day lag.
- Add a test for this: `last_final_day = E + 2` must be accepted.

### N4. C6b dataset run needs `--city` for the four maker stations
- `archive_windows` without a city filter emits NYC windows too (`settlement_truth_dataset.py:303-307`).
- The s2b window would then expect an NYC zip that `window-zip` never fetches ("per maker station").
- `window_zip_path` raises `ArchiveCoverageError` on a missing zip (:343-351).
- Either pass `--city` four times in the Doc B recipe and a test, or fetch NYC too (non-maker, parse only).

### N5. C1b function size and where the logic lives
- `run_census` is already 68 lines (`scripts/analysis/maker_tape_census.py:260-327`), over the 50-line guideline.
- The plan puts the guard, ledger append and mode checks inside it.
- Extract `_second_look_guard(plan, ...)` and call it from `run_census`.
- Keep `main` under 50 lines. It is about 40 today (:481-520), and counts-only branching will push it over.
- Existing census tests call `run_census(**options)` (`tests/unit/test_maker_tape_census.py:534`) and `main` with `--output` (:593, 702, 885…). Optional keyword arguments are fine. `--output` becomes optional only for counts-only.

### N6. C5 `_refusal` addendum path
- `_addendum_refusal(entries, mine, …)` uses `mine[-1]["run_id"]` and `e["addendum_sha"]` (`ledger.py:186-197`).
- If `mine` is widened to "same `block_first_day`", the "latest run" logic must cover the union of sha-matched and block-matched entries.
- The plan names only the exact-key-set tests. Add a test: a voided v2 run plus an addendum on a copied amendment (different sha, same block).

### N7. C4 size and import hygiene
- A new module under 150 lines must hold the lock, a batched in-process census call, the CROSSED row, chain hash, `close` (including the D13 re-verify), the repo copy and the CLI.
- It is also imported by `preflight` for `first_crossing`, so it drags in the census scripts.
- Put `first_crossing` and the `listed_in_time` wiring in a tiny pure module. The tool then imports it from there.
- Entry rows: `scripts.analysis.maker_stage0_trigger` is auto-derived from `ExecStart` (`tests/support/entry_points.py:26-50`). One widening in `STAGE0_ENTRY_MODULES` (`test_runtime_import_isolation.py:68`) and the derived-set test is plausible.

### N8. Timing risk on day c−2 (unmeasured)
- The trigger runs at 10:05Z with `day_to ≤ c−2`, and the 09:00Z rotation makes those instances CLEAN.
- If a late instance is still LIVE, its station-day is read as `live_unread`, not COVERED. That gives a later disagreement that is disclosed only.
- The plan accepts this. U-8 (single-day wall time) should also record how often the c−2 day is unread at check time.

## Existing tests and limits touched

- **Must change or be given a seam:** the replay `main` tests in `tests/unit/test_maker_stage0_replay.py` (N1).
- **Stay byte-unchanged (verified):**
  - `test_maker_stage0_driver.py` (the :365-373 case): unaffected, since the C2b pin is at the CLI layer.
  - `test_maker_tape_census.py` :107-126 (row 0 untouched).
  - `FrozenDateSet(` is constructed only inside `parse_frozen_block` (`frozen.py:153`). The defaulted fields are safe.
- **S-* screen tests / NO-SEND pins:** none touched by any unit as written.
- **`dataclasses.asdict`:** none in `scripts/analysis/maker_stage0_*.py` or the census script, so the closed allowlist is not at risk. C6b's `_field_mapping` explicitly avoids it (`settlement_truth_dataset.py:1144-1153`).
- **Module-size limits:**
  - `probe.py` is 398 of 400. The W2(a) split before C7 is correctly planned.
  - `verdict.py` is 397 and `tables.py` is 340. Neither is touched (`test_maker_stage0_verdict.py:828-830` limit is under 400).
  - `inputs.py` is 373. A shared `truth_keys` fits, but place it so it stays under 400.
  - `run_census` is 68 lines (N5).

## Verified-in-code claims (all hold)

- **Ledger:**
  - `_KEYS_BY_KIND` and the `set(entry) != expected` check are at `ledger.py:66-69, 149`.
  - `_refusal` is keyed on `amendment_sha` only (:203).
  - A fresh sha is a fresh claim (:204-205).
- **Frozen constants:**
  - `LAST_ALLOWED_DAY` and `FIRST_REPLAYABLE_CHOICES` are at `frozen.py:36-37`.
  - The v2 fence prefix problem is real: `_OPEN_FENCE` at :47, `count` at :139.
- **Census firewall:** `require_firewall_clearance` is at `src/breezy/analysis/maker_tape_census.py:178-200`.
- **Driver:** the first-replayable equality runs after the claim (`driver.py:225-229`).
- **Census CLI:** `--output` is `required=True` (:474), and `_EXIT_UNSCREENED` is returned at :520.
- **Preflight:** it checks only the truth csv sha (:161-162).
- **`listed_in_time`:** inclusive, and `None` gives `False` (`rule.py:250-255`).

## False claims in the plan

1. **C6b:** "uses the paced `IemCliTransport` ... writes the zip" is false (B1). The transport is text-only and strictly UTF-8 decoded (`http.py:831-836`; `iem_cli_fetch.py:207, 255-260`).
2. **C2b:** "every existing driver test stays byte-unchanged" is true, but the plan implies no existing test needs to move. The replay CLI tests do (N1).
3. **Round-3 table, C1:** "storage verified as different, so a fetch is needed (same single writer)" is correct. The step "same transport" is not (B1).

## Non-blocking suggestions

- **Pin the E recompute inputs:** state that `first_crossing` takes `(station, climate_day, reason, first_seen_ns)` rows only, so the counts-only file and the committed rows have one schema.
- **C1b ledger record:** write `from`, `to` and `mode` as ISO strings and sort keys. Test that a record written then re-read round-trips under the chain hash.
- **Trigger test for batching:** keep `test_check_stops_at_first_crossing_inside_a_catch_up_batch`. Add a variant where the crossing is on the first day of the batch, and one where it is on the last day.
- **S-1 STOP:** consider stating in Doc A, now, the exact named next action. It is already "dated peer ruling", which is fine. Say that no second full census is possible without an addendum.

## Answers to the planner's earlier questions (unchanged from r2 stance)

- **P-1:** disjoint blocks, never pooled. Amendment :71-77 forbids a second scoring pass on the set, and L-56 bars counting motivating data toward n.
- **P-2:** realised forfeiture is read from the ledger, with the 132 ceiling disclosed. This is sound given D4 and the narrowing commit.
- **P-3:** keep the ledger date-overlap guard. C5's `block_first_day` match is the correct per-block form.

## Files referenced

- `/home/jon/breezy/scripts/archive/iem_cli_fetch.py`
- `/home/jon/breezy/src/breezy/ingest/http.py`
- `/home/jon/breezy/scripts/analysis/settlement_truth_dataset.py`
- `/home/jon/breezy/scripts/analysis/settlement_alignment_study.py`
- `/home/jon/breezy/scripts/analysis/maker_stage0_replay.py`
- `/home/jon/breezy/tests/unit/test_maker_stage0_replay.py`
- `/home/jon/breezy/scripts/analysis/maker_stage0_frozen.py`
- `/home/jon/breezy/scripts/analysis/maker_stage0_ledger.py`
- `/home/jon/breezy/scripts/analysis/maker_tape_census.py`
- `/home/jon/breezy/scripts/analysis/maker_stage0_report.py`