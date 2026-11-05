# RULING_MAKER-S1_SEARCH_amendment_addendum_2026-10-15_s2v-20261015T161506Z

Status: **FINAL**. Dated addendum under `docs/evidence/RULING_MAKER-S1_SEARCH_declaration_amendment_2026-10-13.md` §3 (non-result void re-run rule). Second addendum of 2026-10-15; the first (`RULING_MAKER-S1_SEARCH_amendment_addendum_2026-10-15.md`) covered the OOM void `s2v-20261015T073314Z` and was consumed by the ledger claim of the run voided here. Decision owner per Pre-Auth; no operator cap involved.
Amendment sha (unchanged): `cf9a4dad826f61016b2616d32fbc1ca82f73b339b7da8e74fb6a9f25f4c818d0`. Engineering delta: `docs/plans/backlog/MAKER_2026-10-12/S2_stage0_replay_plan_r4_delta_s7_estimator.md` (peer-reviewed twice: prediction-market-reviewer, architect, python-reviewer; round 2 on the diff: APPROVE/APPROVE).

## Voided run

voided_run_id: s2v-20261015T161506Z

- Launched 2026-10-15 16:15:06Z (unit `breezy-maker-s2-verdict`, RuntimeMaxSec 21600, MemoryMax 4G, `--addendum` = the first 10-15 addendum). Ledger start entry carries `code_sha ae7801c1`'s successor `e6184e5dd5de7f7c76beacc2f81018afdc63cf59` and `addendum_sha 792532f69cd9307f12ebc5701619a555430edafc85e1f4ca9dfbb6824370d8f4`.
- Cause: **S-7 pre-pass** at 18:26Z, before any scoring: `DeltaBoundExceeded: clock offset 789814434155 ns exceeds 600000000000 ns`. Driver exit 3; the run directory was renamed `.void` by the driver and the ledger void entry written (`tree_sha256 fafd10c1ce0d7fd89cbd27f2c4b37aa4245c3a25a7c7a317ac9068ecbb1253c6`, files: `wp0_agreement.json` only).
- Classification: non-result void (amendment §3; r4 delta (c)). No `scored_episodes.csv`, `s3_inputs.json`, `verdict.*`, `station_days.csv` or `episodes.jsonl` was produced.

## Attestation

No fill, rate, label or scoring output of the voided run was read: none exists. The only artefact, `wp0_agreement.json`, was read for its clock-offset fields (`delta_instance_days`, `delta_distribution`, `coverage`, `direction`), which are produced before scoring. The diagnosis and the estimator below were derived solely from `VenueClockOffset` samples, recorder journal lines, and code.

## Diagnosis (what tripped)

- The recorder's `offset_ns` is `ts_init − quote.ts_event` for ONE quote frame in every 200 (`src/breezy/adapters/polymarket_us/data.py:2060-2083`); `ts_event` is the venue `transactTime`. The 789.8 s value (instance 68c935ce, 2026-10-12 02:19:19Z) is a single sample whose neighbours (43 s before, 40 s after) read 0.165 s and 0.193 s; its `transactTime` is 13 min older than the previous sample's. The same shape produced the 381.0 s row (aa380326, 09-29 19:39:53Z, neighbours 0.1 s) and a 6404.6 s sample outside every window. No recorder restart, reconnect or tape gap lies within ±1 h; the host is NTP-synchronised (chrony 0.27 ms). Reading (UNVERIFIED against venue documentation; inferred from the data shape): on some frames the venue `transactTime` is the market's last-transaction time, not the message time; such frames are one-signed (+).
- Under the old estimator every station-day's Δ was inflated by these artefacts: block Δ p50 89.2 s, p95 364 s, max 789.8 s.

## Estimand change (paste from the round-2 domain review)

This addendum changes the estimand of Δ from r4 (i)3 / §222, "max |offset_ns| over the process-live window", to the maximum, over the window, of a neighbour-clamped magnitude f_t = min(|o_t|, max(|o_{t-1}|, |o_{t+1}|) + 10 s). The clamp applies only where both adjacent samples of the same recorder instance lie within 5 min; otherwise f_t = |o_t|. Always f ≤ |o|, and the clamp runs over the full instance sequence before windowing. The S-7 bound (600 s) and `assert_delta_within_bound` are unchanged but now evaluate the filtered Δ. The old value is reported as `raw_delta_ns` / `raw_max`. The change was made after run s2v-20261015T161506Z voided on S-7, with no scoring output read; the constants were chosen from an offsets-only, verdict-blind simulation and frozen in code (`scripts/analysis/maker_stage0_clock_offset.py`: `SPIKE_TOLERANCE_NS = 10 s`, `MAX_NEIGHBOUR_GAP_NS = 5 min`) and pinned by test (`tests/unit/test_maker_stage0_clock_offset.py::test_constants_are_pinned`).

Definitions: sort key is the total tuple `(ts_init, offset_ns)`; neighbours are adjacent sorted samples of one instance; the gap rule is inclusive; a sample with only one neighbour inside the gap is unconfirmable and kept raw; raw neighbours are used, never filtered ones; `min_offset_ns`/`max_offset_ns` stay raw signed; `n_despiked` (f < |o|) and `n_unconfirmable` count in-window samples only. Where the clamp fired, f equals the larger raw neighbour + 10 s (never below a persistent level); a persistent skew present in two or more consecutive samples is kept exactly; two consecutive stale frames are kept (fail-safe: a larger shift or an S-7 void). Pessimism check: a persistent −300 s skew with an interleaved +789 s stale frame yields 310 s (bounded over-estimate, never under).

**The constants may not be re-tuned after the new run's results.** Selection rule (verdict-blind): the tolerance is two orders of magnitude above the block median |offset| (0.09 s) and below the smallest artefact (96 s); the gap is ≈4.5× the largest observed in-window spacing (67.5 s on the tripping instance; 204.6 s block-wide, still below 5 min). Sensitivity grid over the 24 block instance-days (filtered Δ, seconds):

| TOL / GAP | p50 | p95 | max | rows > 60 s | rows > 600 s |
|---|---|---|---|---|---|
| 10 s / 5 min (frozen) | 10.142 | 89.024 | 123.057 | 2 | 0 |
| 10 s / 10 min | 10.142 | 89.024 | 123.057 | 2 | 0 |
| 30 s / 5 min | 30.121 | 101.713 | 123.057 | 2 | 0 |
| 30 s / 10 min | 30.121 | 101.713 | 123.057 | 2 | 0 |
| 60 s / 5 min | 60.089 | 106.213 | 123.057 | 14 | 0 |
| 60 s / 10 min | 60.089 | 106.213 | 123.057 | 14 | 0 |

The gap constant changes no row (no in-window spacing exceeds 5 min); the tolerance sets the floor of a despiked row (neighbour ≈ 0.1 s + TOL).

## Raw vs filtered Δ, all 24 block instance-days (= all 96 station-day rows; Δ is per instance-day and identical across the four stations)

| instance | climate day | n in window | spacing p50/p95/max (s) | Δ raw (s) | Δ filtered (s) | n_despiked | n_unconfirmable |
|---|---|---|---|---|---|---|---|
| f2ed92ab | 2026-09-18 | 1646 | 14.5 / 67.9 / 198.3 | 94.770 | 10.138 | 3 | 0 |
| f84bd270 | 2026-09-19 | 1048 | 29.0 / 74.0 / 145.0 | 52.222 | 10.109 | 2 | 0 |
| 78a124b8 | 2026-09-20 | 1927 | 12.1 / 57.8 / 134.1 | 96.642 | 10.736 | 2 | 0 |
| a10b9ccc | 2026-09-21 | 1191 | 26.6 / 59.2 / 151.3 | 123.057 | 123.057 | 3 | 0 |
| 0d243113 | 2026-09-22 | 1713 | 16.8 / 46.7 / 106.3 | 9.903 | 9.903 | 0 | 0 |
| 6d9a2001 | 2026-09-23 | 1693 | 16.0 / 55.4 / 116.6 | 74.529 | 10.113 | 3 | 0 |
| a6abd60e | 2026-09-24 | 2807 | 9.4 / 35.1 / 53.1 | 105.488 | 10.137 | 1 | 0 |
| 591ab80b | 2026-09-25 | 3010 | 8.2 / 35.2 / 118.8 | 114.238 | 102.827 | 6 | 0 |
| 194ce1a5 | 2026-09-26 | 2837 | 11.0 / 28.6 / 58.4 | 6.976 | 6.976 | 0 | 0 |
| ea485c90 | 2026-09-27 | 3440 | 8.8 / 21.8 / 204.6 | 5.324 | 5.324 | 0 | 0 |
| 449f752d | 2026-09-28 | 3113 | 8.3 / 28.6 / 62.4 | 84.793 | 10.136 | 1 | 0 |
| cab9b5db | 2026-09-29 | 3092 | 9.4 / 27.5 / 121.9 | 180.963 | 10.159 | 8 | 0 |
| aa380326 | 2026-09-30 | 4480 | 6.4 / 18.9 / 44.9 | 381.029 | 10.802 | 11 | 0 |
| 34b85bad | 2026-10-02 | 5164 | 5.7 / 15.2 / 88.7 | 14.023 | 10.077 | 1 | 0 |
| 71161bd1 | 2026-10-03 | 6596 | 4.6 / 11.4 / 42.1 | 28.587 | 10.216 | 4 | 0 |
| dddc963b | 2026-10-04 | 7484 | 4.1 / 9.7 / 39.0 | 270.047 | 10.151 | 13 | 0 |
| bf538566 | 2026-10-05 | 5839 | 4.7 / 15.5 / 62.8 | 32.572 | 10.124 | 6 | 0 |
| 9e5a5f61 | 2026-10-06 | 5144 | 5.6 / 15.8 / 54.0 | 43.805 | 10.146 | 3 | 0 |
| 1ee5be22 | 2026-10-07 | 5090 | 5.4 / 17.4 / 62.3 | 35.174 | 10.274 | 5 | 0 |
| f90a3a0c | 2026-10-08 | 6475 | 3.5 / 18.6 / 58.4 | 95.807 | 10.159 | 4 | 0 |
| 690b15b6 | 2026-10-09 | 4965 | 5.0 / 21.4 / 76.2 | 93.597 | 10.103 | 1 | 0 |
| 2bb7b0d5 | 2026-10-10 | 5749 | 3.8 / 18.7 / 55.8 | 15.897 | 10.119 | 1 | 0 |
| 6dd51625 | 2026-10-11 | 4028 | 6.0 / 26.0 / 52.4 | 118.625 | 10.237 | 3 | 0 |
| 68c935ce | 2026-10-12 | 4670 | 5.2 / 24.4 / 67.5 | 789.814 | 10.193 | 5 | 0 |

Block: raw p50 89.195 / p95 364.382 / max 789.814 s → filtered p50 10.142 / p95 89.024 / max 123.057 s; `n_despiked` 86; `n_unconfirmable` 0; 93,201 in-window samples; zero negative offsets in the block. Two rows keep ~100–123 s (a10b9ccc, 591ab80b) because adjacent samples both exceed 60 s; that is the fail-safe direction. Adjacent pairs both > 600 s exist in three instances (f84bd270 1, 34b85bad 3, 690b15b6 1) but none inside a process-live window. Backwards `ts_event` steps per instance (full sequence, clock-offset samples): f2ed92ab 3, f84bd270 2, 78a124b8 3, a10b9ccc 2, 0d243113 1, 6d9a2001 1, a6abd60e 2, 591ab80b 7, 194ce1a5 0, ea485c90 1, 449f752d 2, cab9b5db 8, aa380326 27, 34b85bad 10, 71161bd1 28, dddc963b 31, bf538566 28, 9e5a5f61 19, 1ee5be22 14, f90a3a0c 11, 690b15b6 12, 2bb7b0d5 21, 6dd51625 18, 68c935ce 16. Under the frozen constants no block instance-day exceeds 600 s.

## Stale ts_event treatment (paste from the round-2 domain review)

Depth frames are ordered and dated by venue `transactTime` and prints by `tradeTime`. A depth frame whose `transactTime` is stale is therefore dated before its receipt; the simulator neither detects nor corrects this, and `assert_leak_free`'s `depth_ts_used <= t0` test uses the same stamp. Δ shifts forecast releases and cancels only and has never bounded this channel. This change refuses, drops and re-orders no frame. It adds the report-only `n_backwards_ts_event` per station-day (depth frames whose `ts_event` is below the previous frame's in receipt order; a lower bound, counted over the read bounds before gap filtering, per instance, with chunk-skipped regions treated as adjacent; prints are not counted). The counts are reported in `wp0_agreement.json` and are not used in any gate or verdict.

## Margin loss (paste from the round-2 domain review)

The change removes the pessimistic shift that single stale frames previously induced: block Δ p50 89.2 s → 10.1 s, p95 364 s → 89.0 s, max 789.8 s → 123.1 s. The remaining host-vs-NOAA margin is now about 10 s, plus the recorder NTP offset (chrony 0.27 ms at diagnosis time) and the 1 s Last-Modified granularity. A real skew lasting one sample (shorter than the 5 min neighbour gap) is clamped to the neighbouring level plus 10 s and is not caught by S-7. Two or more consecutive samples still void the run. Rates from the voided run are not comparable with rates produced under this estimator (none exist: the void preceded scoring). Smaller Δ shifts time-triggered cancels less, so rests live up to ~75 s longer than they would have under the old estimator; this is the corrected behaviour. Listing instants (`BinaryOption.ts_init`, host clock) are unshifted by Δ; irrelevant at 10 s.

## code_sha

- Old (voided run): `e6184e5dd5de7f7c76beacc2f81018afdc63cf59`.
- New (re-run): `2380042f` = feat/data-capture-and-risk after commits `2d87316c` (fix(maker-s2): robust Δ clock-offset estimator) and `2380042f` (test-only hardening). Full 40-char sha recorded in the run's `run_manifest.json` and in `STAGE0_REPLAY` evidence. Benches (S-5) and verify-first are re-run on the new sha before relaunch; their numbers are recorded in the evidence document, not here.

## Relaunch

`--addendum docs/evidence/RULING_MAKER-S1_SEARCH_amendment_addendum_2026-10-15_s2v-20261015T161506Z.md --addendum-sha <sha256 of this file>`, same `AMEND_SHA`, same truth and NBP pins, same frozen date set. This file is committed verbatim with the step-10 evidence and never edited afterwards.
