# S2 Stage-0 replay — r4 delta: robust Δ (clock-offset) estimator for the S-7 pre-pass

Status: **PROPOSED** (2026-10-15). Verdict-blind engineering delta to `S2_stage0_replay_plan_r4_delta.md` (i)3 / §221-224. Written after run `s2v-20261015T161506Z` voided on S-7 **before any scoring** (no fill, rate or label output exists; the void dir holds only `wp0_agreement.json`). The S-7 rule itself is unchanged.

## 1. What tripped, and what Δ currently measures

- `offset_ns` is produced by the recorder (`src/breezy/adapters/polymarket_us/data.py:2060-2083`) as `ts_init − quote.ts_event` for ONE frame, every 200th timestamped quote frame. `ts_event` is the venue `transactTime`. No averaging.
- The probe (`scripts/analysis/maker_stage0_probe.py:208-221`, `maker_stage0_probe_core.py:273-288`) assigns the instance's whole sample sequence to every station-day it holds rungs for, selects the process-live window `[D-1 16:50Z, D 02:50Z)` and takes Δ = max |offset_ns|. `assert_delta_within_bound` (bound 600 s) runs in `_wp0` over every instance-day row (`maker_stage0_driver.py:230`).
- Observed (instance 68c935ce, 10-11 09:00Z → 10-12 09:00Z, 10,863 samples, median |offset| 0.090 s): the 789.8 s value at 10-12 02:19:19Z is one isolated sample (neighbours 0.165 s / 0.193 s at 30–67 s spacing) whose `ts_event` (02:06:09) is older than the previous sample's; `ts_event` goes backwards 16 times in the instance. No recorder restart, reconnect or tape gap within ±1 h; host NTP-synced. The same shape explains the 381.0 s row (aa380326, 09-29 19:39:53Z, neighbours 0.1 s) and a 6404.6 s sample outside every window.
- Interpretation: on some frames the venue `transactTime` is the market's last-transaction time, not the message time. Single-frame offsets therefore carry venue-staleness outliers; a real host-vs-venue skew persists across consecutive samples. Under the current estimator the block's Δ (24 days × 4 stations) is p50 84.8 s, p95 381 s, max 789.8 s — every station-day's pessimistic shift is inflated by minutes of artefact, not only the row that tripped.

## 2. Change (estimator only)

Neighbour clamp, over the instance's **full** sorted sample sequence, **before** the window is applied:

```
a_t = |o_t|
f_t = min(a_t, max(a_{t-1}, a_{t+1}) + SPIKE_TOLERANCE_NS)   if both raw neighbours exist within MAX_NEIGHBOUR_GAP_NS
f_t = a_t                                                     otherwise (unconfirmable: kept raw, counted)
Δ(instance-day) = max f_t over in-window samples;  raw_delta_ns = max a_t (old estimator, reported only)
```

- `SPIKE_TOLERANCE_NS = 10 s` (two orders above the 0.09 s median jitter, far below minute-scale artefacts); `MAX_NEIGHBOUR_GAP_NS = 5 min` (≈4.5× the largest observed spacing, 67 s).
- Properties: `f ≤ a` (never above raw); `f ≥` the larger neighbour (never below a persistent level); a skew present in ≥ 2 consecutive samples is kept exactly; two consecutive stale frames are kept (fail-safe: a larger shift or an S-7 void, as today); edge samples and n < 3 keep raw values; pure integer arithmetic on sorted input using RAW neighbours (order-independent, byte-reproducible).
- Filter-then-window, not window-then-filter: neighbours just outside the window are readings of the same two clocks; windowing first would make every window-boundary sample unconfirmable and the answer cut-dependent.
- Rejected: median-of-3 (shrinks legitimate values, sign mixing, breaks existing pins); ts_event-monotonicity drop (misses staleness below the sample spacing, hides a real backwards clock step); p99 (hides real skew in proportion to n); min-of-3 (drops a real 2-sample skew).

## 3. Blueprint

1. New `scripts/analysis/maker_stage0_clock_offset.py` (~70 lines, stdlib only): `SPIKE_TOLERANCE_NS`, `MAX_NEIGHBOUR_GAP_NS`, `despike_abs_offsets(samples) -> tuple[(ts, raw, filtered, confirmable), ...]`, and `InstanceDayDelta` / `instance_day_deltas` / `station_day_delta` moved from `maker_stage0_probe_core.py` (which is at 398 lines). `InstanceDayDelta` gains `raw_delta_ns`, `n_despiked`, `n_unconfirmable` (defaults 0). `instance_day_deltas` signature unchanged; still no entry for a window with no sample (unknown, never 0).
2. `maker_stage0_probe_core.py`: delete the clock-offset section (:259-293) and the `_Samples` alias.
3. `maker_stage0_probe.py`: import the three names from the new module (`__all__` unchanged, `p.*` re-exports keep working); `delta_distribution` gains `raw_max` and `n_despiked`. `_coverage` unchanged.
4. `wp0_agreement.json`: rows gain `raw_delta_ns`, `n_despiked`, `n_unconfirmable` via `flat_fields`; `delta_distribution` gains `raw_max`, `n_despiked`. `report.md`'s Δ block (rendered from `station_days.csv` `delta_ns`) reports the Δ actually applied; `STATION_DAY_COLUMNS` unchanged.
5. NOT changed: `maker_stage0_fill_events.py` (`assert_delta_within_bound`, `DeltaBoundExceeded`, `S7_DELTA_BOUND_NS`, its own `instance_day_deltas`/`station_day_delta_ns` — a DRY follow-up, not on the driver path), `maker_stage0_driver.py`, `maker_stage0_fill.py`, the recorder, `pyproject.toml`.

## 4. Tests (RED first, `tests/unit/test_maker_stage0_clock_offset.py`)

1 isolated spike (0.165 / 789.8 / 0.193 s at 45 s) → 10.193 s, `n_despiked == 1`, `raw_delta_ns == 789.8 s`; 2 two-sample skew (0.1 / 300 / 300 / 0.1) → exactly 300 s; 3 sustained 420 s → 420 s; 4 monotone drift → last value; 5 n = 1, 2 → raw, `n_unconfirmable == n`; empty window → no entry; 6 gap rule (> 5 min from both neighbours → raw); 7 window-edge spike clamped by out-of-window neighbours (paired assertion that window-first would leave it raw); 8 two consecutive 700 s stale frames → 700 s and `assert_delta_within_bound` raises; 9 persistent 601 s at 45 s spacing trips `DeltaBoundExceeded`, 600 s passes; 10 determinism (shuffled input identical; input not mutated; `flat_fields` bytes equal); 11 invariants over a parametrised grid (`delta_ns ≤ raw_delta_ns`; `delta_ns ≥` larger neighbour where the clamp fired); 12 `raw_delta_ns == max |raw|` in window; probe-level pin of `delta_distribution["raw_max"]` and the row fields.

Existing pins that must stay unchanged and pass as-is: `test_maker_stage0_probe.py` (:199 per-instance-day max; :400-404 5 s pins; :432 to_dict key set; :497-524 bidlive-window Δ screen tests with a 660 s sample 30 min from neighbours), `test_maker_stage0_driver.py::test_delta_over_10min_aborts_before_scoring_and_voids_run` (:430, S-7 screen — never edited), :175/:229/:458/:888, `test_maker_stage0_fill.py:412-427, :740`. No S-* screen test is weakened.

## 5. Gates and re-run path

Focused gate (new file + probe/driver/fill/reader_scope + `test_runtime_import_isolation.py` + asdict scan + citation/contract guards + fee-θ pin + mypy ratchet as the ratchet runs it) → full gate (`scripts/ci/run_tests_no_egress.sh`, basetemp under `~/.cache`) → `lint-imports` from the repo root ("N kept, 0 broken") → merge → push → new CODE_SHA → verify-first → bench 4 / bench 8 (S-5) → a NEW dated addendum naming `s2v-20261015T161506Z`, cause S-7 (estimator artefact), old `e6184e5d` → new code_sha, attestation → relaunch.

## 6. Risks

- Changing the estimator after S-7 tripped is defensible only because no scoring happened; the constants (10 s, 5 min) are judgement calls recorded here and in the addendum. Peer review must endorse them.
- Δ shrinks (intended: the old Δ was artefact-inflated); `raw_delta_ns` / `raw_max` keep the old value visible.
- Consecutive stale frames still inflate Δ or void the run (fail-safe direction).
- Two estimators coexist (`maker_stage0_fill_events.instance_day_deltas`, not on the driver path) — DRY follow-up, logged, not changed here.

## 7. Peer review round 1 (2026-10-15, blind: prediction-market-reviewer, architect, python-reviewer) — merged resolutions

All three: estimator sound, no S-* screen test edited, constants 10 s / 5 min endorsed by PMR; REQUEST_CHANGES on spec precision and evidence. Binding resolutions:

1. **Definitions (spec):** sort key is the total tuple `(ts_init, offset_ns)`; "neighbour" = adjacent element in that sorted sequence, within ONE recorder instance (instances never confirm each other); gap rule inclusive (`≤ MAX_NEIGHBOUR_GAP_NS`); a sample with only one neighbour inside the gap is unconfirmable (raw). Property reworded: `f ≤ a` always; **where the clamp fired**, `f ≥` the larger raw neighbour. `min_offset_ns`/`max_offset_ns` stay RAW SIGNED in-window values; `n_despiked` (f < a) and `n_unconfirmable` count in-window samples only; `n_despiked + n_unconfirmable ≤ samples`. `raw_delta_ns` is REQUIRED (no default; the only constructor is `instance_day_deltas`); only the two counts default to 0. Despiked values use RAW neighbours (never previously filtered ones). Units in every constant's docstring (ns).
2. **Sign (PMR 1):** stale-transactTime artefacts are one-signed (+). Δ remains a magnitude; a persistent negative skew (host behind venue) is the leak-relevant case and must be kept exactly: tests for −300 s persistent with an interleaved +stale frame, −420 s sustained, and a +300/−300 sign flip.
3. **Stale `ts_event` on depth/print frames (PMR 2):** the implementer FIRST reports (verify-first, before GREEN) which timestamp the probe/simulator orders depth frames and prints by (`read_depth_frames`, `FrameSpill`, `_read_prints`) and whether a stale `transactTime` frame can be dated before its receipt. The fix adds a REPORT-ONLY per-station-day count `n_backwards_ts_event` (depth frames whose `ts_event` is below the previous frame's, per rung, summed) to the coverage row / `wp0_agreement.json`; no frame is refused or re-ordered by this change. The addendum states the treatment and the counts.
4. **Evidence before constants freeze (architect, lessons "simulate the change" / "extremum across cadences"):** an offsets-only, verdict-blind simulation over the whole frozen block (every in-block instance's `VenueClockOffset` samples; never fill/rate/label) reports: in-window sample-spacing distribution per instance-day (p50/p95/max), raw vs filtered Δ (p50/p95/max) at tolerance 10/30/60 s × gap 5/10 min, `n_unconfirmable`, the number of consecutive backwards-`ts_event` pairs, and whether any instance-day would still exceed 600 s under the chosen constants. Constants are frozen in the addendum only after this.
5. **Tests added (python + architect):** duplicate `ts_init` with different offsets, shuffled; unsorted input (min/max/samples too); negative spike (−789 s, +0.1 s neighbours); n = 3 minimal; gap exactly 5 min (inclusive) and 5 min + 1 ns (raw); spike exactly neighbour + 10 s (f = a, not despiked); one neighbour inside / one outside the gap → raw; real-scale uint64 `ts_init` (~1.7e18); empty window with out-of-window neighbours → no entry; in-window sample next to an out-of-window 6404 s spike → raw, never raised; two interleaved instances, one despiked one not; a probe-level test with DENSE samples (≤ 5 min apart) written through the real writer path (`_write_instance`); a paired driver test: isolated 700 s spike with 45 s neighbours no longer voids, two consecutive 700 s samples still void; a test pinning both constants (so a retune fails there, not in the S-7 screen test).
6. **Pins (verified by hand by two reviewers):** `test_maker_stage0_probe.py:199` (inst-a 150 clamped to 2 s; Δ 5 s; signed min/max −5/2), :400-404, :432 (top-level keys only — grep for any sub-pin on `delta_distribution`/row keys before building and update in the same change if one exists), :507 (660 s sample 90 min from its only neighbour — correct the "30 min" wording), :516-524, driver :175/:431 (`replay_world.py:100-106`, 30 min spacing) all stay unchanged. `wp0_agreement.json` is sealed by a run-time sha with no schema test; `STATION_DAY_COLUMNS` unchanged; nothing re-pins.
7. **Lines:** `probe.py` is at 391 — put the `raw_max`/`n_despiked` aggregation in the new module as a helper; update the `probe_core` docstring (:4-5) that says the clock-offset delta lives there; `_Samples` alias: delete from core, keep probe.py's own.
8. **Docs:** quote r4 (i)3 / §222 ("max |offset_ns|") and call this a change to the ESTIMAND of Δ (verdict-blind); mark "transactTime = last-transaction time" as UNVERIFIED (inferred from data shape); note the Nautilus null hypothesis (VenueClockOffset is a Breezy type; no native estimator). Addendum filename must carry the run_id (the 10-15 addendum for the OOM void already exists and is burned by the ledger; it is committed for provenance). Addendum fields (PMR 4): old/new formulas; constants + derivation; raw vs filtered Δ for all 96 rows; `n_despiked`/`n_unconfirmable`/`n_backwards_ts_event`; statement that no scoring output was read; void-dir tree sha; constants-frozen statement; the lost host-vs-NOAA margin (Δ p50 85 s → ~10 s; recorder NTP offset; 1 s Last-Modified granularity); smaller Δ shifts cancels less, so no rate from the void run is comparable; listing instants are host-clock and unshifted (irrelevant at 10 s).

Status after round 1: **READY for implementation** (round-2 review on the diff: python-reviewer + prediction-market-reviewer, blind).
