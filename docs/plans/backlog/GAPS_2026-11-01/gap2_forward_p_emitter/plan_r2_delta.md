# GAP-2 plan r2 — delta over r1 (architect re-review 2026-11-01: REVISE on the GAP-3 p-file contract; python re-review: APPROVE, 3 LOW folded)

Applies on top of `plan_r1.md`; where they differ the delta wins. Status: r2 — architect confirmation pending. The contract below is the one GAP-3 r1 §3 reads; GAP-3 is the consumer and its text is authoritative.

## R2-1 (HIGH) file format = CSV
The writer emits `~/.local/share/breezy/derived/forward_p/<run_id>.csv` (not parquet), header in the §4 column order, ints as decimal strings, `p_yes`/`p_lower`/`p_upper` as `repr(float)`, null `dup_of` as an empty field. Sidecar stays `<run_id>.meta.json`. T5 pins the exact header string instead of Arrow dtypes; T7 and L-75 apply to the `.csv` path.

## R2-2 (HIGH) column name `source_id`
`source` is renamed `source_id` (value `nbp_fq_v1`) in the key columns, §3 item 6 and T5. GAP-3 refuses the whole file without it.

## R2-3 (MED) look-ahead boundary strict
p is taken from `chain.at(window_start_ns − 1)`. Per-row guard and §5 PASS become `available_at_ns < window_start_ns`. §3 join contract restated: GAP-3 refuses the whole file when any matched row has `ref_ts_ns <= available_at_ns`. T4: `available_at_ns = window_start_ns` must raise.

## R2-4 (MED) `instrument_id` form and p range
§3 states `instrument_id` is the full depth-directory name including `.POLYMARKET_US`, exactly as `_list_rungs :690` returns it. T5 asserts `classify_directory(instrument_id)` gives kind `rung` and `removesuffix(".POLYMARKET_US")` equals the directory stem. §5 PASS adds: every `p_yes` finite and in [0, 1] (nonfinite rows are already drops; out-of-range is KILL).

## R2-5 (LOW ×2) T2/T3 wording and census identity
T2 asserts `reason="sealed_holdout"` for 10-01 (`pre_forward` is < 07-01 only). §5 states drops are counted per rung × window so `listed_in_range × 3 = rows + Σdrops` holds.

## R2-6 (python LOW 2–3) sidecar notes
S4b's `git log --diff-filter=A` dates the artefact's addition, not its fit range; the `asserted_cl1_unproven` label stands unless a fit record is found. The sidecar states that GAP-3's NO-leg and NYC scan rows count as `no_forecast_p` (`_list_rungs` filters to `_STATIONS` and skips NO legs).
