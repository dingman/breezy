# GAP-2 FORWARD-P-EMITTER: plan r1
Status: r1, for re-review by architect + python-reviewer. This is new evaluator logic. It runs only if the operator grants the §8 exception, which is unchanged in kind from r0.

## Finding → resolution
| # | Sev | Resolution |
|---|---|---|
| A-1 | HIGH | Window enum = GAP-3's `WINDOWS` (`D-1_18Z`, `D_12Z`, `D_17Z`), imported from `market_calibration_scan` (`:151-156`). p = `chain.at(window_bounds_ns(day, w)[0])` (`:260-263`). The GAP-3 join rule is pinned in §3 and T5. D-window staleness: the vector is the newest *pinned* cycle (`pno_store._pinned` `:144-147` = 13Z/19Z D−1, 01Z D). Every row records it; widening the cycle set needs a new grant. |
| A-2 | HIGH | `[10-02, T)` is filtered at listing, and excluded directories are counted per reason in the sidecar. `ForwardRowRefused` stays as a second check after the filter. T2/T3 test both the filter and the raise. |
| P-1 | HIGH | Emit mode never calls `_station_day` (it reads the tape at `:726-748`) or `_drop_reason` (it needs truth and book, `:906-933`). It re-implements about 40 lines: `read_pinned → build_state → build_chain → chain.at → ladder_p_yes`. Drop enum = `no_vector`, `vector_day_mismatch`, `unknown_era`, `nonfinite`. `no_book`, `no_truth` and `duplicate_rung` do not exist in emit mode; GAP-3 counts its own `no_depth`. |
| P-2 | HIGH | The branch sits in `main()` (`:1306`) before `_run` (`_run` loads truth at `:358` and imports wp7 at `:370`). `_list_rungs` gains the keyword `score_end: dt.date \| None = _SCORE_END`; `None` means no cap. The forward date filter lives in the emit code, so the default path stays byte-identical. |
| A-3 | MED | Accepted. The `_list_rungs` keyword is listed in the exception boundary and covered by T1b. The dependency on GAP-3's script is stated in §2: `classify_directory` (`:663`), `WINDOWS` and `window_bounds_ns`. |
| A-4 | MED | Accepted (same fix as P-2). T6 asserts that `_load_truth`, `_run` and `read_rung_tape` are never called. |
| A-5 | MED | Accepted. One row per `instrument_id` × window; duplicates share the ladder p and carry `dup_of`. **Conflict with P-9 resolved for A-5:** emit mode reads no tape, so p depends only on rung bounds (`:750-753`), and GAP-3 iterates per directory name (`_scan_day` `:421-428`). Dropping duplicates would cause join misses. P-9's per-directory drop accounting therefore does not apply. |
| A-6 | MED | Accepted. `nbp_revision_latency_io.py:34` imports `_NbpSource` *from* p2, so it is downstream and cannot be the home without an import cycle. Its estimand is revision-to-book latency, with guards 1–11 over book rows and a CONFIRM/SEARCH corpus (`revision_latency.py:141-301`). p2 stays the home. |
| A-7 | MED | The label alternative is taken. Every row and the sidecar carry `fit_range_status="asserted_cl1_unproven"`, and GAP-3/GAP-4 must carry it through. S4b (pre-S5) runs a provenance lookup and records it in the sidecar. Commit-date refusal declined: the artefact is dated 09-30, so the refusal would always fire and add no information. Changing the label needs a plan delta that cites a fit record. |
| A-8 | LOW | Accepted. The c10 citation is removed. The pin constant is at `:34`; the load and check are at `:348-356`. |
| A-9 | LOW | Accepted. Partition provenance comes from `PinnedRead.consumed` (`pno_store.py:180-212`) plus `missing`. No new hash. |
| P-3 | MED | Accepted. T6 also asserts that `forecast_cheap_screen_wp7` is not in `sys.modules` after an emit run. |
| P-4 | MED | Accepted. T1b: the output of `_list_rungs(root)` with default arguments equals a frozen golden on a fixture tree. |
| P-5 | MED | Accepted. A new `ForwardRowRefused(ValueError)` with `reason ∈ {pre_forward, sealed_holdout, at_or_after_T}` is defined in the sibling module. One class, not several. |
| P-6 | MED | Accepted. The new code and tests are strict-mypy clean, with typed parameters and no `kw: Any` dict. The only `# type: ignore` is the existing `[import-not-found]` pattern on bare script imports. |
| P-7 | MED | Accepted now: the pure guards, filter, row builder and writer go into a sibling module `scripts/analysis/p2_forward_p_emit.py`. p2 gains about 15 lines. The test gets its own `gate_durations.json` entry. Line count corrected to 1,320. |
| P-8 | LOW | Noted; nothing to change. |
| P-9 | LOW | Superseded by A-5 (see the A-5 row). |

## 1 Objective
- Gap: nothing emits per-rung forecast p_yes for the forward tape window [2026-10-02, T). Without it, GAP-3 cannot bin forecast edge against ask on days the forecast has never seen, and GAP-4 cannot pick a family on evidence.
- Delivers: ONE immutable parquet per run with frozen-model p_yes per (instrument_id, window), using the same windows the GAP-3 scan prices. Provenance proves there is no look-ahead and no use of the sealed window. The emitter moves no money and scores nothing.

## 2 Preconditions / dependencies
- Source: `nbp_fq_v1` only. Artefact `deploy/families/artefacts/nbp_calibration_pm_us_crh_fq_v1_2026-09-30.json`, sha pin `_CALIBRATION_SHA` (`p2_nbp_ask_murphy.py:34`). The fit range is asserted by `_FIT_START`/`_FIT_END` (`:30-31`); the JSON has no fit keys (`:1162-1163`). Handled via A-7.
- Rejected homes:
  - blend / `multisource_blend_skill`: OOF rows only; features end 06-30.
  - `nbp_skill_study`: drops days on or after the holdout start.
  - `nbp_revision_latency_*`: see A-6.
  - Any GAP-1 source needs its own frozen artefact and a new grant.
- Depends on `market_calibration_scan.py` (GAP-3's script) for `classify_directory`, `WINDOWS` and `window_bounds_ns`. GAP-3's default output must stay byte-identical, so `WINDOWS` is stable; T5 pins the labels.
- Needs NBP derived partitions under `~/.local/share/breezy/derived/nbp` for cycles from 09-30 13Z onward. Missing partitions show up as `PinnedRead.missing` and become `no_vector` drops.
- Stations: `_STATIONS` (`:33`). NYC is absent because `site()` refuses NYC (`pno_store.py:343`).

## 3 Scope
**Home:** the flag `--emit-forward-p OUT_DIR` on `scripts/analysis/p2_nbp_ask_murphy.py`. The logic lives in the sibling `scripts/analysis/p2_forward_p_emit.py`, which is reached only from this flag.

**Exception boundary (exactly this):**
1. Flags `--emit-forward-p OUT_DIR` and `--through YYYY-MM-DD` (exclusive end T; default today UTC). Refused when T > today or T ≤ 10-02. `--smoke` is refused together with emit.
2. `main()` branches to `p2_forward_p_emit.run_emit(...)` before `_run`. `_list_rungs` gains the `score_end` keyword (default `_SCORE_END`, so default behaviour is unchanged).
3. In the sibling module: `filter_forward_dirs`, `assert_forward_day`, `emit_station_day`, `write_forward_p`, `ForwardRowRefused`. All typed and pure except the writer.
4. Reads ONLY rung directory names, NBP partitions and the pinned artefact. No truth, no tape rows, no ask/bid; p is independent of price and outcome.
5. No Murphy decomposition, takes, `evaluate`, bootstrap or markdown.
6. Source enum {`nbp_fq_v1`}. Window enum = `tuple(w.label for w in WINDOWS)`. The r0 `horizon` column is removed because the window encodes it.

**GAP-3 join contract (binding on GAP-3; pinned by T5):**
- Join on (`instrument_id`, `window`). The key is unique in the file; a duplicate key is refused.
- GAP-3 refuses (LookAheadError) any joined row whose ask `ts_event < available_at_ns`.
- An unmatched scan row is counted as `no_forecast_p` and never imputed.
- `fit_range_status` is copied into GAP-3's sidecar.

**Not in scope:** scoring/binning/PASS-KILL (GAP-3/4); other sources, windows, cycles or refits; `src/` changes; Nautilus; `allow_short`; execution paths.

## 4 Steps
| # | Step | Output | Who | Est |
|---|---|---|---|---|
| S0 | Operator grants the §8 exception | ruling line in PROGRESS and the sidecar | operator | — |
| S1 | RED tests T1–T7 in `tests/unit/test_p2_forward_p_emit.py` | failing run log | tdd-guide (Grok→Codex→Claude route) | 1 h |
| S2 | Flag + branch + `score_end` keyword + sibling module | diff | same | 2 h |
| S3 | `scripts/ci/run_tests_no_egress.sh` on the primary tree, plus `lint-imports` from the tree root; read EXIT before push | EXIT=0 tail | coordinator delegation | 25 min |
| S4 | Review | verdicts | architect + python-reviewer | 1 h |
| S4b | Fit-range provenance lookup (`git log --diff-filter=A` on the artefact; search docs/evidence for a fit record), read-only | sidecar note | sub-agent | 15 min |
| S5 | One emit, T = run date | `~/.local/share/breezy/derived/forward_p/<run_id>.parquet` + `.meta.json` | harness (the script) | < 30 min |

- S5 is not a look: there is no outcome or price join.
- `run_id = <utc_ts>_<git_sha7>`. The writer refuses an existing path (L-75).

**Columns:**
- Key: `station, climate_day, window, rung_id, instrument_id, source`.
- Values: `p_yes, p_lower, p_upper` (from `PYes`; `ArtefactBoundsProvider` is not used).
- Provenance: `dup_of` (nullable), `ladder_complete`, `window_start_ns, available_at_ns, cycle_runtime_ns, model_version` (all fields of `ForecastQuantileVector`, `forecast_state.py:215-225`), `calibration_sha256, fit_range_status, git_sha, emitted_at_ns`.

**Sidecar meta:**
- argv and T;
- `listed_total`, `listed_in_range`, `excluded{pre_forward, sealed_holdout, at_or_after_T}`;
- drops per reason;
- `consumed` as (cycle_runtime_ns, raw_sha256) pairs, and `missing` partitions;
- the S4b provenance result;
- the exception ruling reference.

## 5 Acceptance (frozen before S5)
- PASS requires all of:
  - every row has `2026-10-02 ≤ climate_day < T`;
  - every row has `available_at_ns ≤ window_start_ns` and `vector.climate_day == climate_day`;
  - `calibration_sha256` equals the pin;
  - `listed_total = listed_in_range + Σexcluded`;
  - `listed_in_range × 3 = rows + Σdrops`;
  - (`instrument_id`, `window`) is unique;
  - default-mode tests are unchanged and green.
- KILL (no file written; exit ≠ 0) on any of:
  - `ForwardRowRefused` after the filter;
  - a look-ahead or day-mismatch row that was not dropped;
  - a pin mismatch;
  - a census mismatch;
  - an existing output path;
  - any `ladder_p_yes` exception other than `unknown_era`, including its own sum-to-1 failure (`pno_store.py:239-264`).
- Lesson: an hour-of-day window over a D−1..D+1 tape produced a fake +0.55/take (memory `implausible-result-is-a-leak.md`). Here p is taken at the window *start*. GAP-3's ask lies in [start, start+1h) (`_scan_day` `:428-432`), and `VectorChain.at` is `bisect_right` (`pno_store.py:286-288`). The guard runs per row.

## 6 Tests (RED first) and gate
New file `tests/unit/test_p2_forward_p_emit.py`. Synthetic partitions and directory names; basetemp `<tree>/.pytest-tmp/`.
- **T1 `test_default_mode_output_byte_identical`:** `main([])` routes to `_run(smoke=False)`. `tests/unit/test_p2_nbp_ask_murphy.py` passes unmodified.
- **T1b `test_list_rungs_default_unchanged`:** `_list_rungs(root)` equals a frozen golden, including the 10-13 cap. `score_end=None` lifts only the cap.
- **T2 `test_forward_filter_and_refusal`:** the filter excludes 10-01 and day ≥ T and counts them; `assert_forward_day` raises on 10-01 (`pre_forward`… see T3 for the sealed range) and accepts 10-02.
- **T3 `test_sealed_holdout_refused`:** 07-01, 09-15 and 10-01 raise `ForwardRowRefused(reason="sealed_holdout")`; 06-30 raises `reason="pre_forward"`.
- **T4 `test_lookahead_vector_refused`:** `available_at_ns = window_start_ns + 1` raises. A `vector.climate_day` mismatch becomes a `vector_day_mismatch` drop.
- **T5 `test_forward_p_schema_and_join_key_pinned`:** column names, order and Arrow dtypes equal a frozen tuple; window labels equal `("D-1_18Z","D_12Z","D_17Z")`; the key is unique; duplicate directories each emit a row with `dup_of` set.
- **T6 `test_emit_mode_reads_no_truth_no_tape`:** spies on `_load_truth`, `_run` and `read_rung_tape` are never called, and `forecast_cheap_screen_wp7` is not in `sys.modules`.
- **T7 `test_existing_output_refused`.**

Gate:
- The primary-tree run is binding; a worktree run is ADVISORY.
- Read EXIT before any push, then delete the basetemp.
- Add an entry to `scripts/ci/gate_durations.json`.

## 7 Pins / isolation / risks
- `test_nbp_revision_latency_cli.py:622-630` pins `_NbpSource` and `cash_taker_fee_usd` in p2. Both stay unchanged and in place.
- x1 exec-import set-equality: the tests import nothing from `breezy.adapters.polymarket_us.exec`.
- Typing: `scripts/analysis` is under strict mypy (`pyproject.toml:396, :440`).
- Import cycle: the sibling imports p2 names lazily inside functions, and p2 imports the sibling only inside `main()`.
- Risk: missing early partitions. Mitigation: `no_vector` drops, counted, never imputed.
- Risk: D windows use the 01Z D vector (pinned set), which may be stale relative to the market. Mitigation: disclosed per row via `cycle_runtime_ns`.
- Risk: unproven fit range. Mitigation: A-7 label plus S4b.
- Binding constraints:
  - Nautilus is immutable; `allow_short` stays False.
  - No safety, settlement, contract, pin or NO-SEND test is weakened or deleted.
  - No operator-reserved control is set; live enablement and the egress firewall are untouched.
  - `iem_cli_fetch.fetch` is never called; credentials are never printed; no order ids.
  - Holdout ruling: cl.1 fit < 07-01 (asserted, labelled); cl.2 [07-01, 10-02) is refused outright, so no confirmatory use is spent; cl.3 n/a; cl.4 rows ≥ 10-02 only. L-75 immutability.

## 8 Operator decisions
- **EXCEPTION REQUEST (narrow):** lift the 10-21 "existing harness only" ruling for exactly the §3 boundary items 1–6:
  - one flag pair;
  - a `main()` branch;
  - the `_list_rungs` keyword;
  - one sibling module;
  - source `nbp_fq_v1`;
  - GAP-3's three windows;
  - p output only.
- Anything else needs a new grant: a new source, window or cycle set, a refit, or reading truth or ask in emit mode. No budget or size values are requested.

## 9 Citations
- **Verified (codegraph/grep, 11-01):**
  - `market_calibration_scan.py`: `:151-156`, `:260-263`, `:421-434`, `:191-205`.
  - `p2_nbp_ask_murphy.py`: `:29-34`, `:348-373`, `:661-694`, `:709-796`, `:906-933`, `:1306-1316`.
  - `pno_store.py`: `:144-147`, `:180-212`, `:239-264`, `:286-288`, `:343`.
  - `forecast_state.py:215-225`; `nbp_revision_latency_io.py:34`; `test_nbp_revision_latency_cli.py:622-630`; `gate_durations.json:765`; `pyproject.toml:396, :440`.
- **Not verified:**
  - the artefact's true fit range;
  - NBP coverage for cycles 09-30..10-05;
  - *why* `site()` refuses NYC;
  - the `nbp_skill_study` and `multisource_blend_skill` line refs;
  - strict mypy over `tests/` (the reviewer cited `:447`).

---
Still unverified:
- FQ v1 fit range: only the script constants `:30-31` exist; the JSON has no fit keys. S4b checks this.
- NBP partition coverage on disk for 09-30 13Z through 10-05 has not been checked.
- Why `pno_store.site()` refuses NYC (only the fact that it does, `pno_store.py:343`).
- `nbp_skill_study :760, :1906-1914` and `multisource_blend_skill :714-727` come from the shared context and were not re-read.
- `pyproject.toml:447` (strict mypy over `tests/`) is the python-reviewer's citation; I confirmed only `:396` and `:440`.
