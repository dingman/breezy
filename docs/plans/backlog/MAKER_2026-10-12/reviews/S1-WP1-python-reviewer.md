# S1-WP1 blind review — python-reviewer — 2026-10-12

Scope: worktree maker-s1-wp1 (5915c152 over 6068a00e); 3 files, +1753, zero unrelated changes (`git diff --stat`).

## Evidence
- Focused gate: `[breezy] gate: phase1 rc=0 phase2 rc=0`, `41 passed in 2.68s`, `EXIT=0`; basetemp removed.
- mypy (3 files): no issues. ruff check + format --check: clean. `lint-imports`: 13 kept, 0 broken.
- bwrap wrapper `scripts/ci/run_tests_no_egress.sh` is 0775 in the worktree (executable; noted, not chmod-ed).
- Plan's 22 WP1 test names: all 22 present (18 unit + first-RED + live + parse-failure + work-catalog). 6 extras present (e2e covered row, main output/stop lines, NYC-in-script, sha-pin-matches-file, mismatched-declaration exit 2, zero-covered underpowered).

## Scores
1 Plan compliance 9 | 2 Test completeness 9 | 3 Pythonic/types 9 | 4 Safety 9 | 5 Performance/memory 8 | 6 Scope 10

## Verdict: APPROVE (no CRITICAL, no HIGH)

## Verified against the plan
- Constants match (STALE_H 8, LAST_CYCLE 1, NBP_LAG 2, CANCEL_LST 9, 0.90/60, RHO 0.5, floor 30, 0.05/0.10, buckets). Window `[D-1 12:00Z, min(D 01Z+10h, 09:00 LST))`, integer ns.
- sha pin is the whole check (core:175); mismatch/None refuses every post-09-25 day in `_plan_rows` BEFORE any tape read (script:213). NYC refused at clearance and `admit_print`; rejected prints discarded before any count/log.
- Dedupe on `trade_id` is safe: parsing.py:984 derives the id from slug|time|price|size|side, so it is unique per rung.
- n_eff_ub = sum m/(1+(m-1)*0.5) per climate date (core:598); S-1 on n_eff<30, S-5 on C<0.05, KILL-LIKELY flag in [0.05,0.10); rho labelled assumed in docstring and report.
- Liveness = alive span clipped to window minus that instance's gaps; unresolved gap runs to window end but is clipped by its own instance span (`covered_intervals(window, spans)` refinement is a faithful, better-factored reading of the plan signature). PRE_TRADE_CAPTURE decided from the window alone; the tape is not touched when no day needs reading (script:243).
- LIVE/EMPTY/CORRUPT instances are counted and never converted (spy test). TradeTick conversion failure -> `TRADE_PARSE_FAILURE` for every admitted day the instance touches. Work catalog removed in `finally`; capture tree compared incl. mtimes; `--work-root` inside capture refused.
- Pure module imports stdlib only (no Nautilus, no pyarrow). Scratch default `~/.cache/breezy/maker-s1-work`.

## Judgement on implementer notes
- CORRUPT_ONLY never emitted: a correct reading, not a silent mislabel. An unread corrupt instance cannot be attributed to a station-day (that needs a BinaryOption read), so NO_CLEAN_INSTANCE is the only honest label, and both are excluded from all denominators. But `CORRUPT_ONLY` in `REASONS` and `instances_corrupt` (always 0) are dead; see M1.
- `tail_span_only`: diagnostic only, never changes a verdict; documented as an upper bound. See L3.
- `MakerWindow` NamedTuple and the `sys.path.insert` shim (same precedent as replay_sufficiency_census.py:81): fine.

## Findings
[MEDIUM] M1 instances_corrupt is a constant 0 column
File: scripts/analysis/maker_tape_census.py:293; core:397-407
Issue: Rows say `instances_corrupt: 0` for every day, which reads as "no corrupt instance touched this day". It is really "not attributable".
Fix: Keep CORRUPT_ONLY/column for plan/schema parity but state in the evidence doc and provenance that corrupt/live counts are global only (they are in `instances`). Optionally make the field `int | None` = None.

[MEDIUM] M2 OSError reported as REFUSED (exit 2)
File: scripts/analysis/maker_tape_census.py:387
Issue: Disk full, permission or read errors during the run are labelled REFUSED and get the governance exit code; the stall watch cannot tell them from firewall refusals.
Fix: catch `(core.FirewallRefused, ValueError)` for exit 2; let OSError fall to the FAILED branch (exit 3).

[LOW] L1 Non-atomic output write — core:631. `path.write_text` can leave a partial file on crash despite the "never a partial output" comment (script:390). Write to `path.with_suffix(".tmp")` then `os.replace`.
[LOW] L2 Work-dir symlink edge — script:261. A pre-existing EMPTY `work_root/<id>` symlink pointing inside the capture root would pass the emptiness check and be converted into. Add `_check_work_root(work_dir.resolve(), catalog_root)` before mkdir. (rmtree on a symlink only warns, so nothing is deleted; contrived.)
[LOW] L3 `tail_span_only` also fires when the trailing hole is an unresolved gap (core:290-313). Documented as an upper bound; label it so in the evidence doc.
[LOW] L4 `created_root` rmdir runs outside `finally` (script:272); an exception leaves an empty work root. Move into a `finally`.
[LOW] L5 `PreflightError` -> "EMPTY" (script:252) merges scan failures with truly empty instances in provenance. Count as "UNSCANNABLE" or add a stderr line (it prints the verdict, so only the label is imprecise).
[LOW] L6 Memory (L-49): no `read_all()` in new code; conversion is the audited `default_convert` coalesced read, then `work.query` materialises all TradeTick/VenueClockOffset objects of ONE instance (small streams; includes NYC/D+1 ticks) and admitted prints accumulate in the ledger once per overlapping instance before dedupe. Benchmark 459 MB peak on a 3 GB instance is consistent; keep the MemoryMax=4G unit. Optional: stream `VenueClockOffset` min/max instead of building a list (script:130).
[LOW] L7 Derived trade ids collapse identical same-timestamp/price/size/side prints, so bucket counts are a lower bound by design. C (>=1 qualifying print) is unaffected; mention in the evidence doc.
[LOW] L8 `Any` in `_unwrap` (script:116) and stderr `print` are acceptable for a script; consider `object` + `cast`.
