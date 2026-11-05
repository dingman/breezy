Commit: e4848c39a979bac5a91b8f6b3887f75c497c1be8
# Coverage / Kill-Clock: Measure Under Shard-Local Accounting, Then Rule (2026-09-12) — Rev 1

**L-1.** Verified fresh today (positive control + negative check, both run against the INSTALLED tree):
`grep -n "class BacktestEngine" .venv/lib/python3.13/site-packages/nautilus_trader/backtest/engine.pyx:217` -> found (control proves the search methodology works). `grep -rniE "structural.dead|covered.listed|station.day" .venv/lib/python3.13/site-packages/nautilus_trader/` -> **0 matches**. Verdict: **GENUINELY-ABSENT** — Nautilus Trader 1.231.0 has no station-day coverage, no structural-dead/kill-clock concept, nothing to reuse or extend for this measurement. The one native surface already in use and correctly reused is custom `Data`: `QuoteTapeGap` (`src/breezy/adapters/polymarket_us/tape_records.py:51`, a `nautilus_trader.core.data.Data` subclass, published via `_publish_custom`/catalogued by `ParquetDataCatalog`) — **NATIVE-sufficient** as a transport, nothing to build there.

**Constraints.** Nautilus immutable (nothing here touches it). `allow_short` untouched. No operator-reserved value assigned. No live-enablement/NO-SEND touch. **This plan does not change the registered wording of PREREG v3 §9 / STRUCTURAL_DEAD_RULE_2026-09-05.md in code** — increments 4.A/4.B/4.D are measurement, diagnostics, and non-semantic observability only; increment "ruling package" (§8) is decision material for the strategy lead, not a patch. Gate: `scripts/ci/run_tests_no_egress.sh`; `lint-imports`; `mypy` after every slice. Adapters never import runtime; runtime never imports strategy (unaffected — this plan touches `scripts/analysis/` only, outside the layer contract's `src/breezy` tree).

## 1. Goal state (falsifiable)

**Goal.** `covered_listed_station_days` (`scripts/analysis/structural_dead_stop.py:163`) reflects capture reality: a station-day whose afternoon `[12:00,17:00)` LST Depth10 tape is continuous except for sub-minute shard reconnects counts as covered; a station-day with a real outage does not. The `breezy-score-live-trials.timer` 14:15Z run (`deploy/systemd/score-live-trials-run.sh:67`) writes `count>0` on the first such clean afternoon. **Falsifiable test:** run the manual dry-run (Increment A) against tonight's completed afternoon for LAX/MDW/MIA/SFO; the goal is met iff at least one station-day shows zero afternoon-overlapping resolved gaps AND its Depth10 instant span is measured `>=30 min`, OR the strategy lead has issued a tolerance ruling under which the day counts covered. Absent either, the goal is **not yet reached** — this plan does not claim it is.

**Happy walk (file:line hops).** Recorder samples feed health -> `_sample_tape_gaps` (`data.py:1975`) -> per-shard reconnect `<10s` -> `_sample_one_shard`/`_close_shard_gap` (`data.py:2036,2075`) closes WITHOUT fanning to other shards' instruments (d3f6c47, live in the running recorder since 09-12 09:00Z) -> `_publish_gap_records` writes one `QuoteTapeGap` row per AFFECTED instrument only (`data.py:2113`) -> `breezy-quote-tape-ingest-frequent.timer` (`*:0/15`) lands it under `data/custom_quote_tape_gap/<instrument>/` -> 14:15Z `structural_dead_stop.main()` -> `_resolved_gaps_from_catalog` (`:253`) -> `resolved_gaps_by_seq` (`tape_records.py:513`) collapses to one row per `(recorder_instance_id, instrument_id, gap_seq)` -> `covered_listed_station_days` (`:163`) finds no afternoon overlap for that station-day, loads Depth10 instants (`load_depth`, reads `data/order_book_depths` — **confirmed today**: `count_covered_listed_station_days_from_catalog:233` sets `depth_root = catalog_root/"data"/"order_book_depths"`, i.e. it already reads Depth10, not QuoteTicks — L-35's concern does not apply here, no code change needed) -> `afternoon_coverage_minutes>=30` -> counted -> six-key JSON written with `count>0`.

**Failure walk 1 (PROVEN LIVE, measured today).** A routine idle-timer shard reconnect (<60s, harmless to a market's own tradability) is still `>0` duration and the any-overlap rule (`_gap_overlaps_afternoon:158`) disqualifies the day regardless of duration. Measured 09-08..09-11 (script below): 60-450 such sub-60s overlaps per station-day; this is the dominant volume and is what B1/S3#1 names.

**Failure walk 2 (NEW, measured today, not named in prior evidence).** A recorder crash/restart that opens a gap (`_open_tape_gap`/`_open_shard_gap`) and dies before writing the `resolved=True` closing row leaves a row with `resolved=False` PERMANENTLY in the catalog for that `(recorder_instance_id, instrument_id, gap_seq)` key — `resolved_gaps_by_seq` never merges it with a later instance's fresh counter (by design, per `tape_records.py:104-109`: cross-restart collision would be unsafe). `QuoteTapeGap.covers()` (`tape_records.py:158`) then returns `True` for **all time after `started_ns`, forever**, for that specific station-day's instruments — this disqualifies that ONE station-day's own afternoon window permanently, independent of and NOT fixed by d3f6c47 (which only prevents one HEALTHY shard's reconnect from fanning to OTHER stations/instruments; it does not, and by its own PR description was never meant to, retroactively close an already-dead process's open row). Measured: LAX/MDW/MIA/SFO 09-08 each carry exactly 2 never-resolved `(instance_id, gap_seq)` incidents system-wide (verified: `1aa5c292…:137`, `e2e277df…:359`, fanned across all 6 rung-bucket instrument dirs for that city-day per the intentional "one row per affected instrument" contract), one of which lands inside the afternoon window (6 `OPEN` entries per city in the per-day count below). The SAME shape recurs 09-10 and 09-11. **09-12 (today, post-d3f6c47) shows zero afternoon overlaps of any kind so far** (see table) — the earliest evidence the fix plus a crash-free day could work, contingent on no crash occurring before 17:00 LST at each city today.

**Failure walk 3 (DEBT, PROVEN LIVE, S6).** `quote-tape-ingest` fails every run on non-disjoint intervals (journal `2026-09-12T12:31:33 quote_tick=failed order_book_depths=failed`, no alert) — if ingest itself is failing, fresh partitions may not land regardless of the accounting fix; the measurement procedure (Increment A) must check ingest freshness BEFORE trusting a `count=0` or `count>0` reading.

**Failure walk 4 (DEBT, PROVEN LIVE, S3#6).** 13 TRUNCATED files repo-wide (SFO 09-08 x3) reduce captured-instant span invisibly — could flip a real `>=30min` day under the 30-min floor with no diagnostic trace today.

## 2. Spec / evidence vs code

| Piece | Code today (file:line) | Gap |
|---|---|---|
| Registered wording (do not amend) | `docs/plans/STRUCTURAL_DEAD_RULE_2026-09-05.md:7` (verbatim, quoted below); PREREG v3 §9 (`docs/specs/PREREG_v3_continuous_rung_hold_DRAFT_2026-09-10.md:150-153`, "unchanged from v2") | None — this plan does not touch it. |
| Any-overlap disqualification | `_gap_overlaps_afternoon` (`structural_dead_stop.py:158-160`); half-open, boundary-correct (codex review F3 fix landed) | By design per registration; not a bug. Whether "any" should stay literal is the ruling. |
| Shard-local gap fan-out | `data.py:1975-2081` (d3f6c47, live in recorder since 09-12 09:00Z) | Fixes healthy-shard-blip fan-out; does **not** address Failure walk 2 (dead process, never-closed row). |
| Fail-closed on unreadable gap partition | `_resolved_gaps_from_catalog` (`:253-269`), raises `QuoteTapeGapDataUnavailable` (codex F1 fix landed) | None. |
| Six-key `--output` JSON | `_write_output_json` (`:296-320`); pinned `test_output_json_has_exactly_six_sorted_keys_indent_2` | Must stay six keys — truncation visibility (Inc. D) must NOT grow this contract. |
| Depth source for instant-span | `count_covered_listed_station_days_from_catalog:233` reads `data/order_book_depths` (Depth10) | **None** — L-35's QuoteTicks-empty-bid concern does not apply; already Depth10. |
| Never-resolved gap permanence | `tape_records.py:158-164` (`covers()`), `:104-109` (per-instance key rationale) | No code gap — this is documented, intentional "loud, not convenient" behaviour. The gap is **diagnostic**: nothing today distinguishes "still-open blip mid-measurement" from "permanently-dead incident from a killed process" in the reporting surface. |
| Truncation visibility | `custom_depth_truncation` catalog partition exists (`ls data/`); `DepthTruncation` (`tape_records.py`, imported `data.py:110`) | Never read by `covered_listed_station_days` or any report — S3#6's "invisible to coverage" stands. |
| Node-vs-recorder gap scope | `docs/evidence/codex_prereg_v2_rulings_2026-09-06.md:10-13` (Question A, RULED): recorder/catalog coverage alone is the registered definition; trade-node liveness must **not** be added to "covered" for `pm_us_crh_v2`/`_cont` | Confirms the brief's "covered means recorder capture only" is the standing ruling, not an open question. |

**Registered wording (verbatim, do not amend in code)** — `docs/plans/STRUCTURAL_DEAD_RULE_2026-09-05.md:7`:
> window `[12:00,17:00)` LST; **afternoon-covered** = span of distinct captured Depth10/quote instants in that window `>= 30` min (`0-1` instant => 0); **listed** = venue listed that station-day (skip-days out of the denominator, ~9%); **denominator** = covered listed station-days of `{LAX,MDW,MIA,SFO}`; fire at count `>= 15`; **~0** = filled Takes `= 0` on those days — one fill defeats the stop (no epsilon).

And the same doc's "Covered listed station-day (target definition)": "...covered iff listed and afternoon span >=30 min and `[12:00,17:00)` LST does **not** overlap a resolved `QuoteTapeGap` interval. Recorder-down => not covered." PREREG v3 §9 (`:150-153`): "unchanged from v2."

## 3. Design

**Where.** No change to `structural_dead_stop.py`'s counting logic, its CLI, or the six-key JSON. Two NEW, read-only, non-authoritative artefacts, both outside `src/breezy` (no layer-contract exposure): (1) a documented manual-dry-run command (no new code) — Increment A; (2) `scripts/analysis/coverage_gap_diagnostic.py`, a characterisation report over the SAME catalog data, feeding nothing back into the KILL rule — Increments B/D.

**Inputs.** Same catalog root (`~/.local/share/breezy/catalog/quote_tape/polymarket_us`), same `resolved_gaps_by_seq`, same afternoon-window arithmetic (duplicated as ~10 pure lines with a pinned parity test against `structural_dead_stop.py`'s private helpers on shared fixtures — never imported cross-module, so the diagnostic survives whatever the eventual ruling changes in the registered module). Adds `custom_depth_truncation` (`DepthTruncation`, `tape_records.py`) as a new read source, for the diagnostic only.

**Outputs.** Stdout / a non-dated markdown under `derived/coverage_gap_diagnostic_<run-timestamp>.md` (never `derived/covered_listed_station_days_<date>.json`, which stays the sole authoritative artefact the 14:15Z job writes). Per-station-day: `RECONNECT_BLIP` count (resolved, duration `< RECONNECT_BLIP_THRESHOLD_S`, default 60s — a diagnostic constant, not a rule threshold), `OUTAGE` count (resolved, `>=` threshold), `UNRESOLVED_PERMANENT` count (never-resolved rows — Failure walk 2), `TRUNCATED_FILES` count (from `custom_depth_truncation`), and a verdict label `WOULD_BE_COVERED_UNDER_ANY_OVERLAP` / `WOULD_BE_COVERED_UNDER_60S_TOLERANCE` / `BLOCKED_BY_UNRESOLVED_OR_OUTAGE` — purely descriptive, never fed to `structural_dead`.

**Not changed (byte-unchanged pins by test name).** `test_15_covered_days_0_fills_is_dead`, `test_14_covered_days_0_fills_is_not_dead`, `test_output_json_has_exactly_six_sorted_keys_indent_2`, `test_gap_overlapping_afternoon_by_one_ns_is_not_covered`, `test_unreadable_gap_partition_refuses_and_writes_no_output` — all in `tests/unit/test_structural_dead_stop*.py`, all stay green untouched.

## 4. Increments

| id | size | RED test(s) first | minimal change | observable | verify |
|---|---|---|---|---|---|
| A | XS | none — L-33: no new production behaviour, a documented procedure over existing code | No code. Document exact commands in this plan (below) | Stdout printing per-city "not covered (afternoon overlapped...)" lines and a covered count, no dated artefact written | `.venv/bin/python scripts/analysis/structural_dead_stop.py --family-manifest deploy/families/pm_us_crh_cont.json` (no `--output`) run AFTER tonight's 17:00 LST latest city (MIA, UTC-5, i.e. after 22:00 UTC) and AFTER the `*:0/15` ingest has landed a post-window partition; confirm no file appears under `derived/covered_listed_station_days_*.json` from this invocation |
| B | M | `tests/unit/test_coverage_gap_diagnostic.py::test_a_resolved_35s_gap_classifies_as_reconnect_blip`, `::test_a_resolved_120s_gap_classifies_as_outage`, `::test_a_never_resolved_row_classifies_as_unresolved_permanent`, `::test_afternoon_window_arithmetic_matches_structural_dead_stop_on_shared_fixtures` (parity pin) | New pure module `scripts/analysis/coverage_gap_diagnostic.py`: `classify_gap()`, `station_day_diagnostic()`, `render_report()`; no import from `structural_dead_stop` (duplication + parity test per §3) | Report shows, for 09-08..09-12 real catalog data, the split table in §"Measured evidence" below | `scripts/ci/run_tests_no_egress.sh tests/unit/test_coverage_gap_diagnostic.py`; manual: `.venv/bin/python scripts/analysis/coverage_gap_diagnostic.py --catalog-root ~/.local/share/breezy/catalog/quote_tape/polymarket_us --since 2026-09-08 --until 2026-09-12` |
| C | — | n/a — decision, not code | Ruling package, §8 | Strategy-lead written verdict lands in `docs/evidence/` | n/a |
| D | S | `tests/unit/test_coverage_gap_diagnostic.py::test_truncated_files_are_a_named_reason_not_a_silent_instant_loss`, `::test_zero_truncated_files_is_reported_not_omitted` | Extend `station_day_diagnostic()` to read `custom_depth_truncation` and add a `truncated_file_count` field to its report row; NEVER touches `structural_dead_stop.py`'s six-key `--output` | Report row carries `truncated_file_count` for SFO 09-08 `== 3`, all other measured station-days `== 0` | Same command as B; `grep truncated_file_count` on the rendered report |
| E | — | folded into B/D above (RED-first per row) | — | — | — |

## 5. Acceptance

- Increment A: an operator/agent can run the dry-run and see, for a given city, a printed reason for non-coverage (or silence + a coverage count) with **no** side-effect on `derived/covered_listed_station_days_*.json`.
- Increment B: `coverage_gap_diagnostic.py` run against the real catalog for 09-08..09-12 reproduces (up to that day's own further ingest) the "Measured evidence" table below; unit tests green; `lint-imports`/`mypy` clean; parity test proves the diagnostic's window arithmetic matches `structural_dead_stop.py`'s private helpers bit-for-bit on shared fixtures.
- Increment D: the same report additionally names SFO 09-08's 3 truncated files; a station-day with zero truncation shows `0`, never an absent key.
- Increment C: a strategy-lead ruling document lands under `docs/evidence/` selecting one of §8's options (or a documented "insufficient evidence, defer") — this plan's goal state is reached only once that ruling exists AND (per §1) a station-day is observed to satisfy it.

## 6. Non-goals

- Changing `_gap_overlaps_afternoon`, `covered_listed_station_days`, the six-key JSON shape, or `MIN_STRUCTURAL_DEAD_STATION_DAYS` in code before the ruling.
- Touching the recorder process, `data.py`, or `websocket.py` (d3f6c47 is already in and unmodified here).
- The trade node's own gap accounting (its overnight-observed 10 gaps are a separate, node-local phenomenon per the "covered means recorder capture only" ruling — out of scope here by that ruling, not by this plan's choice).
- Retroactively "closing" a never-resolved historical row (would be a tape mutation — the tape is append-only and the docstring is explicit this is deliberate).
- Wiring the structural KILL into `family_tally_v2.py`'s decision path (already landed per `docs/plans/STRUCTURAL_DEAD_RULE_2026-09-05.md`'s build order; not this plan's scope).

## 7. Risks, blast radius, rollback

- **Blast radius:** `covered_listed_station_days` has 2 callers (both in `structural_dead_stop.py`), no covering tests found by codegraph on the function itself (tests exist at module level, e.g. `test_15_covered_days_0_fills_is_dead`, but codegraph's dependency scan on the bare symbol shows none — verify via the pinned test names in §3, not the blast-radius summary alone). The new diagnostic module has zero callers anywhere in production code (by design — read-only, opt-in CLI) so its blast radius is nil.
- **Risk: diagnostic drifts from the registered module's semantics** if `structural_dead_stop.py` is later amended by the ruling and the duplicated arithmetic is not updated. Mitigation: the parity test (Increment B) fails loudly the moment the two disagree, on every gate run — never silent drift.
- **Risk: someone reads a diagnostic `WOULD_BE_COVERED_UNDER_60S_TOLERANCE` label as if it were an authoritative count.** Mitigation: the report's own header states "non-authoritative, feeds no KILL decision" and the module publishes no `derived/covered_listed_station_days_*.json`-shaped artefact — different filename, different directory convention, checked by `test_a_populated_work_catalog_...`-style path-shape tests if reused from existing fixtures.
- **Rollback:** delete `scripts/analysis/coverage_gap_diagnostic.py` and its test file; zero production surface touched, nothing to revert elsewhere.

## 8. Rulings / operator items

**Prior rulings found (L-32).** `docs/evidence/codex_prereg_v2_rulings_2026-09-06.md` Question A (RULED): recorder/catalog coverage alone is the registered definition for `pm_us_crh_v2`; adding trade-node liveness to "covered" would be a **new post-registration denominator screen**, not a reinterpretation — REFUSED for this family. No prior ruling addresses duration-tolerance or the never-resolved-row permanence found today.

**Amendment/re-registration consequence (answering the brief's question, v3 §16 + v2 ratification read).** `docs/evidence/grok_prereg_v2_ratification_2026-09-04.md:81`: "any change to a **parameter, the table, or a threshold** requires a **NEW** pre-registration document … the family **restarts** — `n` resets to 0 … Amending v1 in place is prohibited." This clause is written in the context of the sequential/efficacy apparatus (BE, Wilson z, 60/150, BCa) explicitly frozen at `:129`; it is **ambiguous whether §9's `>=15`/any-overlap coverage threshold — a safety stop, not the efficacy statistic — falls under the same restart trigger**, and no prior ruling resolves that ambiguity. **This ambiguity itself is a ruling item.** Mitigating fact: `pm_us_crh_cont` admissible `n=0` today (no fills), so a restart costs nothing in practice if triggered — but the strategy lead should still rule on it explicitly rather than let a future higher-n family hit an unplanned restart.

**Options (one line each; full evidence above):**
- **(i) Keep any-overlap.** No code change. Accept the counter cannot fire until reconnects reach zero; measured today, that has not happened once in 5 days even post-85faa02 (idle-timeout fix) and will not happen post-d3f6c47 either on any day with even one dead-process incident (Failure walk 2) — expected time-to-15 is **effectively unbounded** under current crash frequency (2 incidents/~4 days observed), not merely "slow."
- **(ii) Tolerance by duration (gaps `<X`s ignored).** Measured data supports `X=60` cleanly separating "shard blip" (5-35s, dozens per day) from the only two longer classes seen: a repeating ~105s event (6/day on 09-08, cause not yet diagnosed — Increment B's job) and the never-resolved rows (undefined/infinite duration by construction — **duration tolerance cannot rescue these**, see below). `X` must be fixed from this evidence BEFORE it is used to score any live day, per the brief's own caution (not p-hacked post-hoc against fill outcomes) — the counter is a safety stop, not the efficacy statistic, and no fills exist yet to hack toward regardless.
- **(iii) Coverage = distinct Depth10 instant span `>=30` min with no gap `>=Y` min.** Closest to the registered wording's OWN "instant span" framing (already the code's mechanism for the depth-instant part); `Y` faces the identical never-resolved-row problem as (ii).
- **(iv) NOT in the brief — required by today's measurement.** How to treat a `resolved=False` row whose `recorder_instance_id` is no longer the currently-running instance (i.e., a genuinely dead process, distinguishable via the systemd journal / instance-id lifecycle, not from the row alone): options are (iv-a) leave it open forever (current behavior, correctly conservative, but silently makes the day permanently uncoverable under (i)-(iii) alike unless explicitly carved out), or (iv-b) treat it as closed-at-last-observation for coverage purposes ONLY (never mutate the tape; a report-time inference, auditable, with the inferred close time logged) once a documented "instance is dead" signal is available. This determines whether options (ii)/(iii) are even reachable in practice.

**Operator items:** none — measurement is build-side per the brief; enablement/budget/live-trading caps untouched.

## 9. Citations

Verified against the working tree today (2026-09-12) via codegraph_explore (`projectPath=/home/jon/breezy`) unless marked UNVERIFIED:
- `scripts/analysis/structural_dead_stop.py:82-320` (verbatim read).
- `src/breezy/adapters/polymarket_us/tape_records.py:51-221,513-549` (verbatim read).
- `src/breezy/adapters/polymarket_us/data.py:59-114,1975-2156` and the full `d3f6c47` diff (`git show d3f6c47 --stat` + hunks, read verbatim).
- `docs/plans/STRUCTURAL_DEAD_RULE_2026-09-05.md` (registered wording quoted verbatim, read in full).
- `docs/specs/PREREG_v3_continuous_rung_hold_DRAFT_2026-09-10.md:150-153,253-268` (read).
- `docs/evidence/codex_prereg_v2_rulings_2026-09-06.md:7-17` (read, Question A/B).
- `docs/evidence/codex_structural_dead_diff_review_2026-09-05.md` (read; confirms fail-closed + half-open fixes landed).
- `docs/evidence/grok_prereg_v2_ratification_2026-09-04.md:79-129` (read; restart-on-threshold-change clause).
- `docs/evidence/READINESS_AUDIT_2026-09-12.md` §§1-3, appendix S2/S3/S6 (read in full).
- `docs/core/LESSONS.md` L-8, L-20, L-23, L-35 (read; L-35 concern confirmed N/A — coverage already reads Depth10).
- Measured today, read-only, via `.venv/bin/python` + `pyarrow.parquet` directly against `~/.local/share/breezy/catalog/quote_tape/polymarket_us/data/{custom_quote_tape_gap,order_book_depths}` (script kept at `/tmp/.../scratchpad/measure_gaps.py`, not committed) — **Measured evidence** (afternoon-overlap counts after `resolved_gaps_by_seq` collapse, per city, `[12:00,17:00)` LST, all four DENSE_STATIONS):

  | City/Day | overlaps | short&lt;60s | mid 60-900s | still-OPEN (never resolved) |
  |---|---|---|---|---|
  | LAX 09-08 | 72 | 60 | 6 (105s x6) | 6 |
  | LAX 09-09 | 96 | 84 | 0 | 12 |
  | LAX 09-10 | 450 | 438 | 0 | 12 |
  | LAX 09-11 | 30 | 24 | 0 | 6 |
  | LAX 09-12 | 0 | 0 | 0 | 0 |
  | MDW/MIA/SFO | same shape as LAX per day (MIA 09-08: 72/60/6/6; SFO 09-10: 450/438/0/12; all cities 09-12: 0/0/0/0) | | | |

  UNVERIFIED: whether the repeating ~105s event (6/day, 09-08 only, all four cities) is a shared root cause (e.g. one specific slug/shard with a slower reconnect) — flagged as Increment B's first diagnostic question, not resolved by this plan. UNVERIFIED: whether today's (09-12) zero-overlap reading survives past each city's own `17:00` LST close, since this measurement was taken before that window closed for at least MIA/MDW/LAX (afternoon in progress at measurement time). UNVERIFIED: root cause of the two never-resolved incidents (crash vs. deliberate shutdown without a health-sample sync) — journal correlation not attempted in this plan (out of scope: "do not touch processes").
