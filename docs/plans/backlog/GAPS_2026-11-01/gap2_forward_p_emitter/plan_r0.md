# GAP-2 FORWARD-P-EMITTER: plan r0
Status: r0. Peer review pending (architect + python-reviewer). This is NEW EVALUATOR logic and runs only if the operator grants the exception in §8.

## 1 Objective
- Gap: nothing emits per-rung forecast p_yes for the forward tape window [2026-10-02, T). Because of that, GAP-3 cannot bin forecast edge against ask on days the forecast has never seen, and no family (GAP-4) can be chosen on evidence.
- What this delivers: ONE immutable parquet per run with frozen-model p_yes per (station, climate_day, rung, window, source, horizon), plus provenance that proves no look-ahead and no use of the sealed window. It moves no money and scores nothing. It is the input that lets "realised win rate > price + fee" be tested on forward days.

## 2 Preconditions / dependencies
- GAP-1 names the source(s). r0 supports ONE source, `nbp_fq_v1`. It is the only frozen artefact with a sha pin that already flows into `ladder_p_yes`: `deploy/families/artefacts/nbp_calibration_pm_us_crh_fq_v1_2026-09-30.json`, sha `9c0b6d6e…3a5e` (`p2_nbp_ask_murphy.py:34, :348-356`). Its fit range comes from the constants `_FIT_START`/`_FIT_END` = 2021-01-01..2026-06-30 (`:30-31`), and the JSON itself has no fit-date keys (`:1162-1163`). The fit range is therefore asserted by the plan, not proven by the artefact. That gets disclosed in every output sidecar.
- Rejected homes (for r0):
  - FQ bootstrap EMOS / blend `result.json`: `multisource_blend_skill` writes only OOF rows and its feature build ends 06-30, so it has no forward feature path.
  - `nbp_skill_study` drops days ≥ holdout start (`:760, :1906-1914`).
  - Any source GAP-1 adds later needs its own frozen artefact and sha pin, and comes as an r1 delta. It is NOT covered by this exception.
- `artefact_bounds.ArtefactBoundsProvider` is reused as it is (`:378`). It supplies the p_lower/p_upper interval from the same artefact.
- Needs NBP derived partitions under `~/.local/share/breezy/derived/nbp` for cycles ≥ 10-01. The F13-C1 collector has been live since 10-06; coverage for 10-01..10-05 is unverified (§9).
- GAP-3 consumes the file through `--forecast-p PATH`. The join keys are pinned here (§6 T5), so GAP-3 builds against this schema.

## 3 Scope
**Home: a `--emit-forward-p OUT` flag on `scripts/analysis/p2_nbp_ask_murphy.py`. No new module.**
- Why this script: it already holds every part of the chain.
  - It loads the pinned calibration (`:352`).
  - It builds the per-station-day forecast chain (`read_pinned` → `build_state` → `build_chain`, `:755-757`).
  - It takes the vector at the gate instant (`gate_instant_ns`, 16:50Z D−1, `:120`, `chain.at(gate)` `:758`).
  - It calls `ladder_p_yes` grouped by `available_at_ns` (`:782-796`).
  - It lists the rung ladders from the tape directory names (`_list_rungs` `:661`).
- Today its only output is markdown (`:605-608`) and it is capped at `_SCORE_END=10-13` (`:29, :680`).
- Why it is evaluator logic regardless: it turns a frozen model into a probability on days it has never been scored on, and it hands those probabilities to a scoring consumer. That is a new estimand input, not a read. It also lifts the `_SCORE_END` cap in emit mode only. The same reasoning made Card D's one-flag route a new evaluator (`card_d_g0_amendment_r1.md` §6).

**Exception boundary (exactly this, nothing more):**
1. The flag `--emit-forward-p OUT`, plus `--through YYYY-MM-DD` (exclusive end T; default today UTC; refuse T > today). In emit mode `--smoke` is refused.
2. One function, `_emit_forward_rows(...)`, and one writer, `_write_forward_p(...)`, both inside the same script.
3. Emit mode reads ONLY:
   - rung directory names (no Depth10 rows);
   - the NBP derived partitions;
   - the pinned artefact.
4. Emit mode reads NO truth CSV and NO ask/bid. p is therefore independent of price and outcome by construction.
5. Emit mode does no Murphy work, no takes, no `evaluate`, no bootstrap, and writes no evidence markdown.
6. Source enum = {`nbp_fq_v1`}. Window enum = {`gate_1650Z_Dm1`}. Horizon = `D+1`.

**Not in scope:**
- scoring, binning or the PASS/KILL test (GAP-3/GAP-4);
- any other source, window or refit;
- the forward feature build for the blend;
- live/runtime code, `src/` changes, Nautilus, `allow_short`, execution paths.

## 4 Steps
| # | Step | Output | Who | Est |
|---|---|---|---|---|
| S0 | Operator grants the §8 exception (text recorded in PROGRESS + this plan's sidecar) | ruling line | operator | — |
| S1 | RED tests T1–T6 (§6) in `tests/unit/test_p2_forward_p_emit.py` | failing run log | tdd-guide (Grok/Codex per route) | 1 h |
| S2 | Implement flag + `_emit_forward_rows` + `_write_forward_p`; default path untouched | diff | same | 2 h |
| S3 | Gate: `scripts/ci/run_tests_no_egress.sh` on the primary tree; read EXIT before push | EXIT=0 tail | coordinator delegation | 25 min |
| S4 | Review | verdicts | architect + python-reviewer | 1 h |
| S5 | One production emit, T = run date | `~/.local/share/breezy/derived/forward_p/<run_id>.parquet` + `<run_id>.meta.json` | harness (the script) | < 30 min |

- S5 is NOT a look. It emits p only, with no outcome or price join. The look belongs to GAP-3/GAP-4 under their PREREG.
- Output is immutable. `run_id = <utc_ts>_<git_sha7>`. The writer refuses an existing path (L-75).

**Row key and columns:**
- Key: `station, climate_day, rung_id, window, source, horizon`, plus `instrument_id` for the GAP-3 join.
- Values: `p_yes, p_lower, p_upper` (from `PYes`).
- Provenance: `available_at_ns, gate_ns, cycle_runtime_ns, model_version, calibration_sha256, git_sha, nbp_partition_sha256` (hash of the consumed partition files), `emitted_at_ns`.

**Sidecar meta:**
- argv, T, census;
- per-reason drops: `unknown_era`, `nonfinite`, `no_vector`, `duplicate_rung`;
- the disclosed fit-range caveat;
- the exception ruling reference.

**Station set:** the existing `_STATIONS` (LAX, MDW, MIA, SFO). NYC is excluded exactly as P2 excluded it. The reason for that exclusion is unverified (§9). Widening to NYC is an r1 delta and is never done silently.

## 5 Acceptance (frozen before S5)
- PASS:
  - every emitted row has `2026-10-02 ≤ climate_day < T`;
  - every row has `available_at_ns ≤ gate_ns`;
  - `calibration_sha256` equals the pin;
  - census adds up: rows + drops = rungs listed in [10-02, T) for `_STATIONS`;
  - `sum(p_yes)` over each complete-partition ladder is within the `ladder_p_yes` sum-to-1 tolerance;
  - default-mode tests are unchanged and green.
- KILL (no file is written; exit ≠ 0) on any of:
  - any refused-range row;
  - any look-ahead row;
  - a pin mismatch;
  - a census mismatch;
  - an existing output path.
- Lesson cited: "+0.55/take at 77% was an hour-of-day window over a D-1..D+1 tape" (memory `implausible-result-is-a-leak.md`). Its consequence here: the vector is taken at `chain.at(gate_ns)` for the climate day's own D−1 16:50Z, never at a tape snapshot time. The guard re-checks `available_at_ns` on every row, not just once per day.

## 6 Tests (RED first) and gate
New file `tests/unit/test_p2_forward_p_emit.py`, using synthetic partitions and directory names, with basetemp inside the worktree:
- **T1 `test_default_mode_output_byte_identical`**
  - Without the flag, `_station_day` on a fixture returns events/drops/takes equal to a frozen golden.
  - `main([])` routes to `_run(smoke=False)`.
  - The existing `tests/unit/test_p2_nbp_ask_murphy.py` passes unmodified.
- **T2 `test_refuses_climate_day_before_forward_start`**: a 10-01 row raises; a 10-02 row is emitted.
- **T3 `test_refuses_holdout_window_rows`**: 07-01, 09-15 and 10-01 each raise a distinct `HoldoutRowRefused`; 06-30 raises the pre-forward refusal.
- **T4 `test_lookahead_vector_refused`**: a vector with `available_at_ns = gate_ns + 1` raises.
- **T5 `test_forward_p_schema_pinned`**: column names, order and Arrow dtypes equal a frozen tuple.
- **T6 `test_emit_mode_reads_no_truth_no_tape_rows`**: the truth/tape readers are spies that must never be called.
- **T7 `test_existing_output_refused`**.

Gate route:
- Gate: `scripts/ci/run_tests_no_egress.sh` on the primary tree (a worktree run is ADVISORY only). Read EXIT before any push.
- Run `lint-imports` from the tree root.
- Delete the basetemp after reading EXIT.

## 7 Pins / isolation / risks
- `tests/unit/test_nbp_revision_latency_cli.py:622-630` imports `_NbpSource` and `cash_taker_fee_usd` from this script. Both names must stay unchanged.
- x1 exec-import set-equality: the new tests must import nothing from `breezy.adapters.polymarket_us.exec`. They import only the script and `pno_store`.
- Import-linter contracts in `pyproject.toml` name only `scripts.analysis.discovery_set_equality`, so no contract covers this script. c10 membership is unverified (§9).
- Add the new test to `scripts/ci/gate_durations.json` (the existing entry is at `:765`).
- Risk, file size: the script is already 1,321 lines, over the 800 soft ceiling.
  - Mitigation: if python-reviewer rules it, move the pure guards and writer into a sibling helper reached only from this flag. That is still the same exception.
- Risk, missing NBP partitions for early forward days.
  - Mitigation: these become `no_vector` drops, counted in the census. Never imputed.
- Risk, unproven fit range of the FQ v1 artefact.
  - Mitigation: disclosed in the sidecar. An architect ruling on whether "plan range = fit range" is enough is required in review S4.
- Binding constraints:
  - Nautilus is immutable; `allow_short` stays False.
  - No safety, settlement, contract, pin or NO-SEND test is weakened or deleted.
  - No operator-reserved control is set; live enablement and the egress firewall are not touched.
  - `iem_cli_fetch.fetch` is never called; credentials are never printed; no order ids.
  - The holdout ruling applies:
    - cl.1: fit < 07-01;
    - cl.2: [07-01, 10-02) sealed, and this emitter refuses it outright, so no confirmatory use is spent;
    - cl.3: n/a;
    - cl.4: rows ≥ 10-02 only.

## 8 Operator decisions
- **EXCEPTION REQUEST (narrow):** allow the 10-21 "existing harness only" ruling to be lifted for exactly the §3 boundary items 1–6:
  - one flag and two functions in `p2_nbp_ask_murphy.py`;
  - source `nbp_fq_v1` only;
  - output p only, no scoring.
- Anything else needs a new grant: a new source, a window, a refit, or reading truth or ask in emit mode.
- No budget or size values are requested.

## 9 Citations not verified
- The FQ v1 artefact's true fit range (the JSON has no fit-date keys, `:1163`).
- NBP partition coverage for cycles 10-01..10-05.
- Why NYC is absent from `_STATIONS`.
- What c10 covers, and whether this script sits in it.
- Whether GAP-3's window labels match `gate_1650Z_Dm1`.

---
Unverified citations:
- FQ v1 fit range 2021-01-01..2026-06-30 comes from the script's constants, not the artefact (`p2_nbp_ask_murphy.py:30-31, :1162-1163`).
- NBP derived-store coverage for 10-01..10-05 was not checked on disk.
- The reason NYC is excluded from `_STATIONS` (`:33`) was not traced.
- c10 pin membership was not located. Only the x1 exec-import pin and the `test_nbp_revision_latency_cli.py:622-630` import pins were confirmed.
- The `nbp_skill_study :760, :1906-1914` and `multisource_blend_skill :714-727` line refs come from the shared context and were not re-read.
