# RULING_MAKER-S2_second_look_C7_scope_2026-10-20

Status: **FINAL**. Dated ruling under `docs/evidence/RULING_MAKER-S2_second_look_SEARCH_declaration_2026-10-16.md` (Doc A) §8 and the coordinator delta `docs/plans/backlog/MAKER_2026-10-12/S2_second_look_plan_r3_delta_coordinator.md` row 2.21 (C7 scope D-1, scope guard §2.17). Committed on the integration branch no later than the C7 merge commit, which cites it. Doc A is not amended (its sha is unchanged). Decision owner per Pre-Auth; no operator cap involved.

Verdict-blind throughout: no fill, rate, label or scoring output was read by any party to this ruling. Data touched: file listings and `stat()` results, instrument-definition tables (only the `id` column consumed), per-rung stream directory and file NAMES, and the counts-only trigger rows' `first_seen_ns` for the premise-P check.

## What C7 is

A verdict-blind instance pre-filter on the probe preamble of the block-2 verdict run, decided YES on 2026-10-20 (`docs/evidence/maker/MAKER-S2_W1_bytes_2026-10-20.md`: PROJ@E_max 19,019 s > 17,280 s). An instance is SKIPPED only when ALL hold: its newest feather mtime is before the cutoff (`prefilter_cutoff_ns`, `scripts/analysis/maker_stage0_probe.py:133`: D-1 12:00Z of the first block day minus one day = 2026-10-12T12:00:00Z, epoch 1791806400); it holds no per-rung stream directory, and no flat per-rung stream file, whose name passes `licensed_rung_filter`; it holds no readable licensed YES definition row for a licensed station-day. Any `OSError` or read/parse failure KEEPS the instance (fail-open on the skip, fail-closed on the verdict population) and is counted as `kept_by_fail_open`; a pre-cutoff instance kept by content is counted as `kept_by_content` (expected 0 under premise P; a non-zero count is the empirical P-violation signal). The same predicates the consuming passes use (`licensed_rung_filter`, `station_day_key`) decide the keep, so a skip means the consumer would have found nothing. The wording "stat-only" in delta row 2.21 and the scope summary is read as amended to "verdict-blind: file stat plus definitions-id and rung-name checks"; W1's "stat-only" describes its measurement procedure and stands; plan r3 :344 and :506 are read as amended (row 2.21 says plan r3 is not edited).

## File set (the point of this ruling)

Doc A §8 licensed "`probe.py` and its split module"; delta row 2.21 widened that to three files. The build needed a fourth.

| File | Role | Pre-FINAL EXEMPT | Post-FINAL (Doc B) EXEMPT |
|---|---|---|---|
| `scripts/analysis/maker_stage0_probe.py` | callers; `prefilter_cutoff_ns` + `_ONE_DAY_NS` (the only cutoff source) | yes | yes |
| `scripts/analysis/maker_stage0_probe_report.py` | W2(a) split (ProbeReport/CLOCKS, byte-identical move) | yes | yes |
| `scripts/analysis/maker_stage0_catalog_read.py` | D-1 plan pass through the same filter; calls the probe helper | yes | no (frozen by pin) |
| `scripts/analysis/maker_stage0_prefilter.py` | `_prefilter_reason`, `_holds_licensed_data`, `log_prefilter` | yes | no (frozen by pin) |

Ruling: the four-file set is licensed for the C7 merge (L-12: widened by one reviewed row, never relaxed). At Doc B FINAL the scope guard is re-pinned in ONE reviewed commit that (a) narrows EXEMPT to {`maker_stage0_probe.py`, `maker_stage0_probe_report.py`}, (b) refreshes the JSON digests of `catalog_read` and `prefilter` (their pre-FINAL digests are stale by design; the JSON gained the `prefilter` key at c5f7d3a2, one line, digest 9d62f284… stale against HEAD), and (c) records the CODE_SHA. The Doc A §8 exception merge (PROJ > 21,600 s after bench) may touch only the two post-FINAL files; that lever can retune the cutoff only (moving it by a day frees at most about one instance, ~14 GB, of the 320–510 GB kept; `probe.py` has 9 lines of headroom under its 400-line cap at 307c8328), so at PROJ > 21,600 s the real contingency is a dated peer ruling, not the exception merge.

The widening of EXEMPT from three to four files happened in the same commit as the code that needed it (c5f7d3a2). That is the pattern L-12 exists to stop; it is accepted here only because this dated ruling now carries the widening, two blind diff reviews read the EXEMPT edit in full, and the test docstring records it ("four pre-FINAL, two post-FINAL"). Future re-pins: the JSON and the EXEMPT set change only in a reviewed re-pin commit, never in a code commit.

## Corrections to standing docs (L-4 sweep)

| Site | Was | Now |
|---|---|---|
| delta row 2.21 | "stat-only"; "three files"; cutoff = `min(window start − 1 d, earliest licensed first_seen_ns)` | verdict-blind stat + name checks; four files pre-FINAL; cutoff = window start − 1 d, the listing term enforced by the content checks (`earliest_licensed_ns` removed); "`prefilter_cutoff_ns` lives in `probe.py`" CONFIRMED |
| delta row 2.21 / scope summary :17 / W1 :107 | "C2 must refuse any pinned licensed row with first_seen < cutoff" (summary in the present tense) | NOT built and not a C7 deliverable. `maker_stage0_preflight_v2.py` is in the pinned verdict closure, so a refusal there is a pinned-file change that could land only in the Doc B FINAL re-pin commit. Both re-reviews found no verdict benefit: the content checks keep any instance holding a licensed listing regardless of P, so a violated P costs cache efficiency only. DOWNGRADED to a counts-only disclosure in the Doc B FINAL runbook: the count of pinned licensed trigger rows with `first_seen_ns < prefilter_cutoff_ns(...)` (expected 0) and the `kept_by_content` total from the verdict preamble (expected 0). No pinned file is edited. |
| delta :47 | "W1 measurement (10-21) → C7 decision (10-24)" | both done 10-20 |
| delta row 2.21 | "≈ 16,800 s / ≈ 22,600 s" | not reproduced by the W1 formula (W1 :122); W1 governs; re-measure at Doc B FINAL |
| W1 formula | KEPT = newest mtime ≥ cutoff | KEPT = every instance not skipped with a `prefilter:` reason: mtime keeps, content keeps (rung directory, flat per-rung file, or definition), fail-open keeps, and no-feather directories. The per-pass summary line `prefilter: skipped K of N instances (kept_by_fail_open F, kept_by_content C)` is emitted at WARNING when F or C is non-zero (no maker_stage0 script configures logging, so INFO is invisible); the probe sidecar's `skipped_instances` carries the skip partition. The FINAL re-measure attributes cost by these counts. |

## Reviews and evidence

- Blind diff reviews on c5f7d3a2: python-reviewer REQUEST_CHANGES (B1 closure test walked the primary tree's in-tree `.venv`; B2 mypy ratchet +4 `attr-defined`; B3 vacuous stat-boundary tests, L-33; B4 fourth file / helper placement); prediction-market-reviewer REQUEST_CHANGES (same governance item; a drop path for licensed per-rung directories without readable definitions could move `first_print_instant`). Focused gate on c5f7d3a2: EXIT=1 — `test_mypy_ratchet` (B2) plus one phase-2 worktree artifact (`interpreter_link` from the `.venv` symlink; not branch-caused).
- Fix round f165c9c4 + 71a2fc62 (cutoff helper back in `probe.py`; rung-directory check before the definitions read; unlicensed fixtures with real scope, keyword-only `days`/`stations`; closure test restricted to repo modules; mypy-clean test imports; single summary line; cutoff computed before `FrameSpill`): mutants M1 (`>=`→`>`), M2 (max→min), M4 (mtime comparison deleted), M5 (rung check removed), M6 (definitions check removed) each killed by named tests. Blind re-reviews: python-reviewer APPROVE (8.7), prediction-market-reviewer APPROVE (8.5). Trigger census path NOT touched (static import walk over the trigger, census, guard, io and rule entry points, runtime `sys.modules` agreement, positive control on `maker_stage0_replay`), so no L-34 class-C change to the frozen trigger.
- Follow-up 307c8328 (reviewer-prescribed, prefilter.py freezes at FINAL): docstring "four pre-FINAL / two post-FINAL"; closure filter excludes `.venv/` only (fail-closed, exact equality kept); ordering pin test; WARNING-level summary; `kept_by_content`; flat per-rung file keep (closes the declared residual). Focused set on 307c8328: phase 1 301 passed (mypy ratchet included); phase 2 only the worktree `interpreter_link` artifact; ruff, format and lint-imports clean; pins JSON untouched (sha256 6ac66c36…).
- Full gate on the integration branch after the merge and its EXIT are recorded in PROGRESS row 2 and the push.

## Known limits (not changed here)

- The pin spans 262 files including packages unrelated to the verdict, so unrelated merges turn the guard red and force reviewed re-pins; the guard asserts source bytes, not a runtime closure equality on the real catalog.
- mtime trust: a backdated restore looks older than it is; mitigated by the content checks (a licensed listing keeps regardless of mtime).
- Flat per-rung layout: the Nautilus 1.231.0 `StreamingFeatherWriter` writes `trade_tick`, `order_book_depths`, `quote_tick` and custom types with an `instrument_id` per instrument (`writer.py:137-147`, `:451`), and salvage/ingest write only marker files, so flat per-rung files do not occur on recorder-written instances; the follow-up keeps them anyway, names-only.
- `read_all()` on a definitions table materialises every column (IPC stream format cannot project); only `id` is consumed.

## Downstream obligations

1. Doc B FINAL re-pin commit: EXEMPT → two files; refresh `catalog_read`/`prefilter` digests; CODE_SHA; the counts-only C2 disclosure in the runbook; W1 re-measure on KEPT bytes.
2. Pace note (not C7): the 2026-10-19 02:34Z host reboot truncated instance 70261a13 (CORRUPT), costing 10-18 and 10-19 to the trigger; E ≈ 2026-11-06 if coverage is full from 10-20; cap 11-15 holds 9 days of slack. Before any planned reboot: `systemctl --user stop breezy-quote-tape.service` and wait for the `Stopped` line (`deploy/systemd/README.md:89-102`).
