# MAKER-S2 Stage 0 replay — evidence (run `s2v-20261016T020707Z`, 2026-10-16)

Status: **FINAL evidence record** for S2 Step 8–10 (`S2_RUN_PROCEDURE_2026-10-14.md`). Label: **UNDERPOWERED-WAIT** (V0: `n_eff_gov` 18.73 < 30). Disposition per Step 8: no build; S3's binding run refuses this label (allowlist {NOT-KILLED, NOT-KILLED-UNSCREENED}); S4/S5 do not start. Per `docs/core/PROGRESS.md` row 2, UNDERPOWERED-WAIT is not a programme STOP. EXPLORATORY: never promotion evidence; Stage 0 never emits a go verdict.

Decision owner per Pre-Auth; no operator cap involved. Sidecars: `docs/evidence/maker/stage0_2026-10-16/`.

## 1. Provenance header

| item | value |
|---|---|
| RUN_ID | `s2v-20261016T020707Z` |
| unit | `breezy-maker-s2-verdict` (invocation `82e187c6905e4401a41a9c5a3c1da52f`), launched 2026-10-16 02:07:07Z, `PRE-OK 2026-10-16T02:07:07Z disk=80G mem=12G RTMAX=21600 MEMMAX=4294967296` |
| EXIT line (`maker_stage0_logs/s2v-20261016T020707Z.log`) | `verdict run done label=UNDERPOWERED-WAIT code_sha=2380042fb66fe2ca4264ce0cc83e21e6e9b3e40c -> …/maker_stage0/s2v-20261016T020707Z` then `EXIT=0` (log sha256 `5647c9d85cbdacf6b60681ea3a77650543ed0d5d6501f4b6840986382c94ee92`) |
| CODE_SHA | `2380042fb66fe2ca4264ce0cc83e21e6e9b3e40c` (`run_manifest.json` `code_sha` equal; branch `feat/data-capture-and-risk`, pushed 2026-10-15 21:49Z) |
| AMEND_SHA | `cf9a4dad826f61016b2616d32fbc1ca82f73b339b7da8e74fb6a9f25f4c818d0` (`RULING_MAKER-S1_SEARCH_declaration_amendment_2026-10-13.md`) |
| addendum (re-run licence) | `RULING_MAKER-S1_SEARCH_amendment_addendum_2026-10-15_s2v-20261015T161506Z.md`, sha256 `6fc033d3ced165e496aaec51ca10e311c37a091fa046f5504a0d69896219f11b` |
| ledger start entry | `{"addendum_sha":"6fc033d3…","amendment_sha":"cf9a4dad…","code_sha":"2380042f…","kind":"verdict_run_start","run_id":"s2v-20261016T020707Z","ts":"2026-10-16T02:08:53.033239+00:00"}` |
| TRUTH_SHA | `947b244a87b192bce8f6f7b772f3447a85398e3a67abbb06c8b41a97202100f8` (`maker_stage0_inputs/truth_cli_finals_2026-10-14.csv`; the run's copy has the same sha; not committed — sealed rows) |
| NBP_MANIFEST_SHA (Step 4 = Step 8) | `9b6f304e9883eddd7b6928f4a75ee9dd05f3c5000a2babaf3e347fbc70379de8` (unchanged between the P2 backfill and the verdict run; `pins.json`) |
| T_FP (Step 2 first-print instant) | 1398 s |
| report.md sha256 | `1ef31ed3f59669e4e6fb067a4655aae6c2b8b1de6ce1b70ac7d4a327ac9bc595` (reproduced verbatim in §6) |
| wall | preamble 02:07Z → ≈04:17Z (alphabetical catalog instance walk, ≈2h10m); scoring 96 station-days 04:17Z → ≈06:20Z; total ≈4h13m of RTMAX 21,600 s |
| memory | cgroup anon ≤ 2.75 GB (file cache filled the 4 GiB cap; `oom_kill 0`); progress rows `peak_rss_bytes` 2.31 GB |

### Entry criteria (quoted)

- S1 Stage A `census_run.log`: `EXIT=0`; no `S-1` STOP line; no S-5 `NO-GO pre-screen` line.
- S1 Stage B `tqu_run.log`: `EXIT=0`; `trade_quantity_unit.json` `verdict: CONTRACTS`, `surviving: ["CONTRACTS"]`, `s2_stop: false`.
- Host at launch: disk 80 GiB free (≥ 10), `free -g` available 12 (≥ 6), no study/census/scorer/replay/gate/backfill/bench/feat-full/persist unit, studies lock free, `breezy-quote-tape` active.
- Tree: `feat/data-capture-and-risk` at `2380042f` (after the S2 merge 520b233c); `git status --porcelain -- scripts/analysis src tests pyproject.toml uv.lock` empty (the two uncommitted addenda are under `docs/evidence/`, outside the scoped check; committed with this record).
- Clock: launched after 02:05Z; hard end 08:07Z < 15:10Z.

### Step 1 S1 values (verbatim)

- `census_summary: {"C": 0.9895833333333334, "C_030": 0.9895833333333334, "D_cov": 24, "N_cov": 96, "n_eff_ub": 38.4, … "reasons": {"COVERED": 96, "LONG_HOLE": 4, "LOW_COVERAGE": 4, "PRE_TRADE_CAPTURE": 76}, "rho": "0.5 (assumed, not measured…"`
- `INFO bidlive: {"C_bidlive": 0.9711538461538461, "D_cov_bidlive": 26, "N_cov_bidlive": 104, "gates_no_stop": true, "n_eff_ub_bidlive": 41.6, …}`
- No STOP lines. `n_eff_ub` 38.4 ≥ 30, so V0 was **not** the recorded expectation at Step 1.

### Steps 2–7 (this code_sha)

| step | result |
|---|---|
| 2 first print | T_FP 1398 s (unchanged) |
| 5 verify-first (2026-06-30) | `vf-20261015T214902Z` EXIT=0 on `2380042f`; 12/12 `matches_climate_day_for_txn` true, 12/12 vintage-age `within_tolerance` true (`verify_first.json`) |
| 6 WP0 direction | `direction.verdict FIXED` (buyer agreement 0.9983 on 106,809 defined; seller 0.9981 on 119,141); SFO positive control `FIXED` (buyer 0.9974 / 21,166; seller 0.9962 / 27,043); `first_replayable_day 2026-09-18`; ladder parity uniform 6 rungs/day at all four stations; `ladder_lower_parity {LAX:0, MDW:1, MIA:0, SFO:0}` |
| 7 bench 4 | unit `breezy-maker-s2-bench4`, dir `bench4-20261015T221958Z`, EXIT=0, wall 2,911 s; `s5_exceeded false`, `by_count_exceeds_cap false`, `projected_peak_rss_bytes 2,550,972,388`, `projected_total_s 6,874.6`, leak fit 1.14 MB/row (`bench4.json`). A first attempt at a 1,800 s cap (`bench4-20261015T214923Z`, no `bench.json`) was killed by RuntimeMaxSec — a cap error (bench 4 wall on e6184e5d was 3,072 s), not S-5. |
| 7 bench 8 | unit `breezy-maker-s2-bench8`, dir `bench8-20261015T230829Z`, EXIT=0; `s5_exceeded false`, `by_count_exceeds_cap false`, `projected_peak_rss_bytes 3,717,529,552` (< 4 GiB, thin margin), `projected_total_s 8,768.2`, `projected_total_s_by_count 19,391` (cap not exceeded), leak fit 14.9 MB/row, 9 rows, max `elapsed_s` 334.8, max `peak_rss+parent_rss` 3,159,588,864 (`bench8.json`) |
| derived caps | PROJ = 8,768 + 2×1,398 = 11,564 → RTMAX = min(21600, 3×PROJ) = 21,600; MEMMAX = min(2×3.16 GB, 4 GiB) = 4,294,967,296; T_STALL = max(600, 3×334.8) = 1,004 s |

## 2. Voided runs and refused attempt (amendment §3; both addenda committed verbatim with this record)

| run | code_sha | cause | classification | ledger |
|---|---|---|---|---|
| `s2v-20261015T073314Z` | `ae7801c1` | OOM at the 4 GiB cgroup cap during the preamble (probe frame ledger + whole-instance `DepthTruncation` query); no station-day scored | non-result void | start 07:33Z (addendum_sha null, first claim); void by hand 08:12:18Z, `files []`, empty-tree sha |
| 16:11Z attempt | `e6184e5d` | launcher REFUSED at the ledger (EXIT=2): "a dated addendum naming a voided run is required"; no claim burned | not a run | none |
| `s2v-20261015T161506Z` | `e6184e5d` | S-7 `DeltaBoundExceeded` before scoring: per-instance max single-frame offset 789.8 s (instance 68c935ce, 10-12 02:19:19Z) — one isolated stale venue `transactTime` sample, not clock skew (neighbours 0.165/0.193 s; host chrony 0.27 ms; no recorder restart/gap) | non-result void (S-7) | start 16:16:50Z with addendum `792532f6…` (`RULING_MAKER-S1_SEARCH_amendment_addendum_2026-10-15.md`, burned by that claim); driver void 18:26:29Z, `files [wp0_agreement.json]`, tree sha `fafd10c1…` |

No fill, rate or label output of either voided run was read (none was produced; the S-7 void's only file is `wp0_agreement.json`).

Remedy for the S-7 artefact (verdict-blind, peer-approved ×5, plan delta `S2_stage0_replay_plan_r4_delta_s7_estimator.md`): neighbour-clamp Δ estimator `f_t = min(|o_t|, max(|o_{t-1}|,|o_{t+1}|) + 10 s)` when both neighbours of the same instance are within 5 min, else raw; S-7 rule text and bound untouched; constants frozen in `maker_stage0_clock_offset.py` and pinned by test; raw max still reported. Merged as 2d87316c + 2380042f (full gate GREEN, 27,165 passed).

## 3. Δ raw vs filtered on the frozen block (offsets-only simulation before the run; run values agree)

Simulation (`s7sim_block_delta.csv`, 24 instance-days): raw per-instance max Δ p50 89.2 s / p95 364 s / max 789.8 s → filtered p50 10.14 s / p95 89.0 s / max 123.06 s (a10b9ccc, 09-21; 591ab80b 09-25 at 102.8 s); n_despiked 86 (whole instances); n_unconfirmable 0; max in-window sample spacing 204.6 s; no row > 600 s under any of six (clamp, neighbour-window) grid pairs.

Run (`wp0_agreement.json` `delta_distribution`, 96 station-days): min 5.32 s, p50 10.14 s, p95 102.83 s, max 123.06 s, `raw_max` 789.81 s, `n_despiked` 344 (in-window), `n_unknown` 0. Report Δ table (44 replayed): median |Δ| 10.2 s, max |Δ| 10.8 s. Δ = 0 re-run: 0 days changed vs primary.

`n_backwards_ts_event` (report-only, depth frames with ts_event below the previous in receipt order): total 12 across 96 station-days, max 5 on one station-day.

## 4. Verdict readout (`s3_inputs.json`, `report.md`)

| field | value |
|---|---|
| verdict | `UNDERPOWERED-WAIT` |
| unit_hypothesis | CONTRACTS (only surviving hypothesis) |
| n_sd (covered bid-bearing station-days) / n0 (climate dates) / n_eff_gov | 44 / 12 / 18.73 (floor 30 → V0 fires) |
| bid_bearing_share_of_covered_listed | 0.50 (`listing_abstained: 40` station-days; report §Disclosures) |
| fitted ICC (report-only) | `fill_icc_station_day` 0.0981, deff 1.26, `n_eff_hat` 34.65 → banner **FITTED-ICC DISAGREES ON THE FLOOR** (report-only; V0 is decided by `n_eff_gov` with RHO_ASSUMED 0.5, never by the fit) |
| r_lo / r_lo_lcb_cluster_boot / r_lo_se | 0.1364 / 0.0244 / 0.0579 (station-day, k 6 / n 44, 12 clusters) |
| r_lo_k1 / lcb | 0.0682 / 0.0 |
| r_lo_position (base = stressed) | 0.0814 (k 7 / n 86) |
| fill_icc_rung_trial / k1 | 0.0962 / 0.0 |
| b (realised bid median) | 0.80 (IQR 0.74–0.80) |
| max_rungs_hypothesis | 2 |
| n_stressed_fills | 7; two_fill_share 0.1667 |
| V1–V5 (descriptive only under V0) | V1 base position 0.0814 < 0.10; V2 §6.9 UNSCREENED; V3 stressed 0.0814 < 0.10; V4 UNSCREENED; V5 not met |
| §6.9 | UNSCREENED (n filled 7, expected losses 0.149; Test A p 1.0, Test B p 1.0; pooled fills needed for E ≥ 10: 469) |
| net expectancy | 7 fills, win rate 1.0, mean p_NO 0.979, net per fill 0.2122 (cluster bootstrap not estimable, < 5 clusters) — descriptive, never a kill or a pass |
| coverage | 96 census station-days; 88 with ≥ 1 depth frame; non-COVERED LONG_HOLE 4, LOW_COVERAGE 4; unknown-Δ 0 |
| report-only variants | overlay 0 days changed; +60 min 0; poll-lag 1 (day rate 0.1136); Δ = 0 0 — all UNDERPOWERED-WAIT |

Reading: S1's `n_eff_ub` 38.4 counted all 96 COVERED station-days on 24 dates; the pre-registered V0 estimator counts only covered **bid-bearing** station-days (44 on 12 dates), and at RHO_ASSUMED 0.5 that is 18.73 < 30. The WAIT is therefore a sample-size fact fixed before any fill was scored (n_sd is outcome-independent). The descriptive V1/V3 comparisons (0.0814 < 0.10) are not labels.

## 5. Step 9 `--tail-only` (report-only; same CODE_SHA)

Run after the verdict run on the same CODE_SHA; result in §5a.

## 5a. Tail result

Unit `breezy-maker-s2-tail` (invocation `1473497bc0c54d7697b56dcad620a1de`), launched 06:26:22Z with MEMMAX 4,294,967,296 and RuntimeMaxSec 3,600, flags as the bench plus `--tail-only --parity LAX:0,MDW:1,MIA:0,SFO:0`, `--out-dir …/maker_stage0/tail/tail-20261016T062622Z`. EXIT line: `tail-only run done code_sha=2380042fb66fe2ca4264ce0cc83e21e6e9b3e40c -> …/tail/tail-20261016T062622Z` then `EXIT=0` (wall ≈ 2 min). Output: `tail_reliability.csv` only (50,944 rows; sha256 `6749a92133e54a89bd3c21c1ffb079ea335704eb9ccbba30978d5bd16f2be35d`; sidecar copy plus `tail_run_manifest.json`). No `TAIL-MISCALIBRATED` annotation was emitted by the driver (log and CSV grep 0).

Descriptive counts read from the CSV (coordinator, no inference; the driver's own exact p is disclosed as anti-conservative because bands of one vector are correlated):

| bin (p_yes) | n rows | dates | mean p | expected YES | observed YES |
|---|---|---|---|---|---|
| [0, .02) | 49,894 | 79 | 0.00031 | 15.4 | 72 |
| [.02, .04) | 655 | 78 | 0.0299 | 19.6 | 37 |
| [.04, .06) | 395 | 78 | 0.0494 | 19.5 | 28 |
| pooled | 50,944 | 79 | — | 54.4 | 137 |

Rows cover 4 stations × 79 climate days × vectors {01Z, 13Z, 19Z}. Observed tail YES settlements exceed the NBP-implied expectation in every bin (report-only; never sets a label). The verdict report's own tail table is empty by construction (parity is known only after the verdict run; procedure open note 2), so this CSV is the tail evidence.

## 6. `report.md` verbatim

```markdown
# MAKER-S2 Stage 0 replay: s2v-20261016T020707Z

EXPLORATORY: never promotion evidence; Stage 0 never emits a go verdict.

## Verdict

Verdict: UNDERPOWERED-WAIT
EXPLORATORY: never promotion evidence; Stage 0 never emits a go verdict.
governing hypothesis: CONTRACTS
V1-V5 below: descriptive, not a label (V0 fired; no build starts)
- V1: base 0.0814 < 0.10
- V2: section 6.9 state UNSCREENED (trigger FAIL)
- V3: stressed 0.0814 < 0.10
- V4: section 6.9 state UNSCREENED (trigger UNSCREENED)
- V5: base and stressed >= 0.10 and state PASS
base rate (stricter unit) 0.0814; stressed 0.0814

## V0 and fitted ICC

V0 (decided by n_eff_gov, never by fill outcomes)
| hypothesis | n_sd | n0 | n_eff_gov | floor 30 | V0 |
|---|---|---|---|---|---|
| CONTRACTS | 44 | 12 | 18.73 | 30 | fires |

Fitted ICC (report-only)
| hypothesis | fill_icc_station_day | deff_hat | n_eff_hat | MSB | MSW | m0 |
|---|---|---|---|---|---|---|
| CONTRACTS | 0.0981 | 1.2607 | 34.65 | 0.1529 | 0.1094 | 3.6570 |
FITTED-ICC DISAGREES ON THE FLOOR (CONTRACTS; report-only)

## Fill rates

| hypothesis | unit | rule | k | n | point | Wilson (sidecar) | cluster bootstrap (interval is n_eff-adjusted) | clusters |
|---|---|---|---|---|---|---|---|---|
| CONTRACTS | station-day | base | 6 | 44 | 0.1364 | [0.0640, 0.2671] | [0.0244, 0.2500] | 12 |
| CONTRACTS | station-day | stressed | 6 | 44 | 0.1364 | [0.0640, 0.2671] | [0.0244, 0.2500] | 12 |
| CONTRACTS | position | base | 7 | 86 | 0.0814 | [0.0400, 0.1586] | [0.0215, 0.1538] | 12 |
| CONTRACTS | position | stressed | 7 | 86 | 0.0814 | [0.0400, 0.1586] | [0.0215, 0.1538] | 12 |
| CONTRACTS | K1 station-day | base | 3 | 44 | 0.0682 | [0.0235, 0.1823] | [0.0000, 0.1364] | 12 |
| CONTRACTS | K1 station-day | stressed | 3 | 44 | 0.0682 | [0.0235, 0.1823] | [0.0000, 0.1364] | 12 |

Implied days to 200 positions (MAX_RUNGS 2 / 1)
| hypothesis | k2_base | k2_stress | k1_base | k1_stress |
|---|---|---|---|---|
| CONTRACTS | 628.6 | 628.6 | 1466.7 | 1466.7 |

## Bid-live hours

| hypothesis | station | n_sd | process_live_h | forecast_valid_h | gap_h | gap share | refused share | process-cut share |
|---|---|---|---|---|---|---|---|---|
| CONTRACTS | LAX | 10 | 99.94 | 99.94 | 0.03 | 0.0003 | 0.0203 | 0.1379 |
| CONTRACTS | MDW | 12 | 119.93 | 119.92 | 0.04 | 0.0004 | 0.0000 | 0.0217 |
| CONTRACTS | MIA | 12 | 119.93 | 119.91 | 0.05 | 0.0004 | 0.4946 | 0.5106 |
| CONTRACTS | SFO | 10 | 99.94 | 99.94 | 0.04 | 0.0004 | 0.0008 | 0.0167 |

## Section 6.9

#### CONTRACTS
state: UNSCREENED (pooled; strata never set it)
Tests A and B are each run at alpha 0.05, uncorrected: the combined false-FAIL rate can reach about 0.10.
n filled 7, n unfilled 79, expected losses 0.1493, observed losses filled 0 unfilled 1
| test | p-value | climate-date clusters | FAIL if |
|---|---|---|---|
| Test A (model; p is p_yes_point_live, 1.5 margin) | 1.000000 | 4 | < 0.05 |
| Test B Poisson-conditional rate-ratio test (approximation, valid at p <= 0.06) | 1.000000 | 12 | < 0.05 |

stratum-mix-adjusted rate ratio (descriptive): 0.0000

Power line (analytic; critical count 2; pooled fills needed for E >= 10: 469)
| k | P(Test A FAIL | k) |
|---|---|
| 1.5 | 0.0171 |
| 2.0 | 0.0297 |
| 3.0 | 0.0633 |

| stratum (p_NO, descriptive only) | n_f | n_u | L_f | L_u | E | p_A | p_B |
|---|---|---|---|---|---|---|---|
| [0.94,0.96) | 1 | 9 | 0 | 0 | 0.0589 | 1.000000 | 1.000000 |
| [0.96,0.98) | 3 | 15 | 0 | 1 | 0.0837 | 1.000000 | 1.000000 |
| [0.98,1] | 3 | 49 | 0 | 0 | 0.0068 | 1.000000 | 1.000000 |
| <0.94 | 0 | 6 | 0 | 0 | 0.0000 | 1.000000 | 1.000000 |

excluded for lacking CLI FINAL: 0 filled, 0 unfilled rows on 0 station-days; void excluded: 0
UNSCREENED-TERMINAL (spec :300-302) is not a Stage 0 object.

#### CONTRACTS STRESSED fills (report-only; never a label)
state: UNSCREENED (pooled; strata never set it)
Tests A and B are each run at alpha 0.05, uncorrected: the combined false-FAIL rate can reach about 0.10.
n filled 7, n unfilled 79, expected losses 0.1493, observed losses filled 0 unfilled 1
| test | p-value | climate-date clusters | FAIL if |
|---|---|---|---|
| Test A (model; p is p_yes_point_live, 1.5 margin) | 1.000000 | 4 | < 0.05 |
| Test B Poisson-conditional rate-ratio test (approximation, valid at p <= 0.06) | 1.000000 | 12 | < 0.05 |

stratum-mix-adjusted rate ratio (descriptive): 0.0000

Power line (analytic; critical count 2; pooled fills needed for E >= 10: 469)
| k | P(Test A FAIL | k) |
|---|---|
| 1.5 | 0.0171 |
| 2.0 | 0.0297 |
| 3.0 | 0.0633 |

| stratum (p_NO, descriptive only) | n_f | n_u | L_f | L_u | E | p_A | p_B |
|---|---|---|---|---|---|---|---|
| [0.94,0.96) | 1 | 9 | 0 | 0 | 0.0589 | 1.000000 | 1.000000 |
| [0.96,0.98) | 3 | 15 | 0 | 1 | 0.0837 | 1.000000 | 1.000000 |
| [0.98,1] | 3 | 49 | 0 | 0 | 0.0068 | 1.000000 | 1.000000 |
| <0.94 | 0 | 6 | 0 | 0 | 0.0000 | 1.000000 | 1.000000 |

excluded for lacking CLI FINAL: 0 filled, 0 unfilled rows on 0 station-days; void excluded: 0
UNSCREENED-TERMINAL (spec :300-302) is not a Stage 0 object.


## Net expectancy

| hypothesis | fills | win rate | mean p_NO | win-rate cluster bootstrap | clusters | Clopper-Pearson (sidecar) | net per fill | one-sided 95% upper bound | no CLI FINAL |
|---|---|---|---|---|---|---|---|---|---|
| CONTRACTS | 7 | 1.0000 | 0.9787 | not estimable | <5 | [0.5904, 1.0000] | 0.2122 | not estimable | 0 |
A negative net expectancy is reported, never a kill.

## Realised bids

| hypothesis | bid (cents) | fills (base) | all posted |
|---|---|---|---|
| CONTRACTS | 74 | 2 | 2 |
| CONTRACTS | 75 | 1 | 1 |
| CONTRACTS | 79 | 0 | 1 |
| CONTRACTS | 80 | 4 | 82 |

## Tail reliability

| bin | n | dates | mean p | observed | Clopper-Pearson |
|---|---|---|---|---|---|
| [0,.02) | 0 | 0 | n/a | n/a | n/a |
| [.02,.04) | 0 | 0 | n/a | n/a | n/a |
| [.04,.06) | 0 | 0 | n/a | n/a | n/a |
pooled n 0, expected 0.0000, observed 0, two-sided exact p n/a
Anti-conservative: bands of one vector are correlated, so the exact p is too small (report-only; never sets a label).

## Clock offset (Delta)

| hypothesis | replayed | nonzero | median |delta| s | max |delta| s |
|---|---|---|---|---|
| CONTRACTS | 44 | 44 | 10.2 | 10.8 |

## Coverage sensitivity

Coverage sensitivity (report-only; never changes the label)
| hypothesis | n_sd | n_sd with covered_live_h >= 0.5 x process_live_h | base day | stressed day | base position | stressed position | nogo_driving days | of which gap_share > 0.5 | share |
|---|---|---|---|---|---|---|---|---|---|
| CONTRACTS | 44 | 44 | 0.1364 | 0.1364 | 0.0814 | 0.0814 | 38 | 0 | 0.0000 |

## Non-COVERED days

| non-COVERED reason | station-days |
|---|---|
| LONG_HOLE | 4 |
| LOW_COVERAGE | 4 |
census station-days 96; with >= 1 depth frame 88 (0.9167; report-only)

## S3 inputs

```json
{
  "b": 0.8,
  "base_k1": 0.06818181818181818,
  "base_station_day_rate": 0.13636363636363635,
  "base_station_day_rate_ci_cluster_boot": [
    0.024390243902439025,
    0.25
  ],
  "bid_bearing_share_of_covered_listed": 0.5,
  "code_sha": "2380042fb66fe2ca4264ce0cc83e21e6e9b3e40c",
  "fill_icc_rung_trial": 0.09620492458387014,
  "fill_icc_rung_trial_k1": 0.0,
  "fill_icc_station_day": 0.09812199737953127,
  "max_rungs_hypothesis": 2,
  "n0_climate_dates": 12,
  "n_eff_gov": 18.733333333333334,
  "n_stressed_fills": 7,
  "r_lo": 0.13636363636363635,
  "r_lo_by_hypothesis": {
    "CONTRACTS": 0.13636363636363635
  },
  "r_lo_k1": 0.06818181818181818,
  "r_lo_k1_lcb_cluster_boot": 0.0,
  "r_lo_lcb_by_hypothesis": {
    "CONTRACTS": 0.024390243902439025
  },
  "r_lo_lcb_cluster_boot": 0.024390243902439025,
  "r_lo_position": 0.08139534883720931,
  "r_lo_se_cluster_boot": 0.05792425718297517,
  "r_lo_station_day": 0.13636363636363635,
  "realised_bid_iqr": [
    0.74,
    0.8
  ],
  "realised_bid_median_base": 0.8,
  "two_fill_share": 0.16666666666666666,
  "unit_hypothesis": "CONTRACTS",
  "verdict": "UNDERPOWERED-WAIT"
}
```

## Report-only variants

### Overlay schedule (report-only)
run-time only, sha-pinned: overlay_station_days.csv (never sets the label)

| hypothesis | n_sd | base day rate | stressed day rate | days changed vs primary |
|---|---|---|---|---|
| CONTRACTS | 44 | 0.1364 | 0.1364 | 0 |

rate-rows V-row outcome: UNDERPOWERED-WAIT (primary: UNDERPOWERED-WAIT); overlay

### +60 min availability stress (report-only)
run-time only, sha-pinned: stress_plus60_station_days.csv (never sets the label)

| hypothesis | n_sd | base day rate | stressed day rate | days changed vs primary |
|---|---|---|---|---|
| CONTRACTS | 44 | 0.1364 | 0.1364 | 0 |

rate-rows V-row outcome: UNDERPOWERED-WAIT (primary: UNDERPOWERED-WAIT); plus60

### Poll-lag stress (report-only)
run-time only, sha-pinned: stress_poll_lag_station_days.csv (never sets the label)

| hypothesis | n_sd | base day rate | stressed day rate | days changed vs primary |
|---|---|---|---|---|
| CONTRACTS | 44 | 0.1136 | 0.1136 | 1 |

rate-rows V-row outcome: UNDERPOWERED-WAIT (primary: UNDERPOWERED-WAIT); poll_lag

### Delta = 0 re-run (report-only)
run-time only, sha-pinned: delta0_station_days.csv (never sets the label)

| hypothesis | n_sd | base day rate | stressed day rate | days changed vs primary |
|---|---|---|---|---|
| CONTRACTS | 44 | 0.1364 | 0.1364 | 0 |

rate-rows V-row outcome: UNDERPOWERED-WAIT (primary: UNDERPOWERED-WAIT); delta0

## Stress variants (report-only)

See the +60 min, poll-lag and Delta = 0 blocks above.

## Run-time only blocks

run-time only, sha-pinned: overlay_station_days.csv

run-time only, sha-pinned: wp0_agreement.json

run-time only, sha-pinned: stress_plus60_station_days.csv

run-time only, sha-pinned: stress_poll_lag_station_days.csv

run-time only, sha-pinned: progress.jsonl

run-time only, sha-pinned: bench output

## Disclosures

- D1 decision instants are depth frames, forecast releases and schedule cuts (r3 L154), not a wall-clock grid; a print never changes the displayed book, only the next frame does.
- D2 forecast abstentions at primary decision instants, by reason, each counted separately (`episodes.jsonl` merges them):
  - abstain NONFINITE_P_YES: 0
  - abstain NO_VECTOR: 0
  - abstain UNKNOWN_ERA: 0
- D3 a later recorder instance takes over at its start, its first in-window event of any kind (frame, print, gap or truncation row).
- D4 depth sizes round UP and print sizes DOWN to whole contracts (conservative: fewer fills, i.e. toward NO-GO, so anti-strategy rather than neutral):
  - buyer prints floored to 0 (CONTRACTS): 3742 of 34073
  - depth levels raised by ceil (CONTRACTS): 16233528 of 179415859
- D5 the truth is the CLI FINAL as a proxy for venue resolution; there is no VOID or UNRESOLVED handling (days 2026-09-18..2026-09-30 are already past D+14 at run time); band edges are inclusive (`bucket_facts_from_instrument_id`).
  - no-FINAL station-days excluded: 0
- D6/M6 no-book rungs are not priced, ranked or K1 and get no attempt; they are counted in `n_no_book_wants` only.
- D8 theta is constant per climate day (read at D 00:00Z via `taker_fee_coefficient_as_of`); `fees.py` names that function for eligibility, so its use here is a documented exception; no intra-day drift is detectable.
- listing_abstained: 40 (LAX 2026-09-18, LAX 2026-09-19, LAX 2026-09-20, LAX 2026-09-21, LAX 2026-09-22, LAX 2026-09-23, LAX 2026-09-24, LAX 2026-09-25, LAX 2026-09-26, LAX 2026-09-27, MDW 2026-09-18, MDW 2026-09-19, MDW 2026-09-20, MDW 2026-09-21, MDW 2026-09-22, MDW 2026-09-23, MDW 2026-09-24, MDW 2026-09-25, MDW 2026-09-26, MDW 2026-09-27, MIA 2026-09-18, MIA 2026-09-19, MIA 2026-09-20, MIA 2026-09-21, MIA 2026-09-22, MIA 2026-09-23, MIA 2026-09-24, MIA 2026-09-25, MIA 2026-09-26, MIA 2026-09-27, SFO 2026-09-18, SFO 2026-09-19, SFO 2026-09-20, SFO 2026-09-21, SFO 2026-09-22, SFO 2026-09-23, SFO 2026-09-24, SFO 2026-09-25, SFO 2026-09-26, SFO 2026-09-27) (listed after D-1 12:00Z: covered, never bid-bearing)
- unknown-delta station-days: 0 (Delta taken as 0)

## Pins

| input | sha256 / value |
|---|---|
| code_sha (git_commit) | `2380042fb66fe2ca4264ce0cc83e21e6e9b3e40c` |
| amendment FINAL sha256 | `cf9a4dad826f61016b2616d32fbc1ca82f73b339b7da8e74fb6a9f25f4c818d0` |
| truth CSV sha256 (frozen block) | `947b244a87b192bce8f6f7b772f3447a85398e3a67abbb06c8b41a97202100f8` |
| census | `bce597f2bedcf345bceadfcc50030aeac89d64e2754b319378a57d9b4ea91a71` |
| trade unit | `6459e9f6384af85af69efca1f70f7a8e8155e343fc18551d85c94d1d9afd4835` |
| artefact | `9c0b6d6e66a587c1b4e14e5f95ff5cedb3c7195f62f8ad4238191fdd75923a5e` |
| deploy manifest | `324c01f8e66d9b349d1b833c2e2dbb6037d560f45a379b7f2554e31251df18e0` |
| evidence doc | `b2827ff172f67c12a76419cb46ebc4382c44530de9edbe2fae83cd9a2726dc0d` |
| spec | `7d154314165fbae8349272ed54160fd20a636405beb65d09efa1108d9e250136` |
| uv.lock | `8f16bb3c4d4e76b9c6aca554d1e3d10ad17b3cc6ace75fe920fa946e2416af3e` |
| NBP manifest | `9b6f304e9883eddd7b6928f4a75ee9dd05f3c5000a2babaf3e347fbc70379de8` |
| NBP consumed cycles | `3aff5316909c6c085ce301c0e62cc4a51e14eb69f22039207127c6a3557c58fd` |
| process schedule | `d4bff99a561fe097a95892eba6ba714130b24429ee178285c34227baff63867a` |
| catalog slice manifest | `149098d8437577ec76db0031838b6d7e65761b56f9b9a8f8927ec6a7634baf00` |
| package set | `30126a7b40d029d60b7a242fecc69601981ac23adfa362668aa5946d051e3998` |
| episodes.jsonl | `c4e9cb484d9b9126fe04226c45dc33bebf00d9b69f73d7fd63776075e8274658` |
| tail csv source | `none` |
| verdict ledger | `/home/jon/.local/share/breezy/derived/maker_stage0/verdict_ledger.jsonl` |
| theta pin site | `src/breezy/adapters/polymarket_us/fees.py::taker_fee_coefficient_as_of (post-drift schedule)` |

| sidecar | label | sha256 |
|---|---|---|
| delta0_station_days.csv | run-time only, sha-pinned | `6457b8a4f87edd2443023b4136eb8801e85881ecdcbc2a90ce9d5b9117b001a3` |
| overlay_station_days.csv | run-time only, sha-pinned | `18316a2b30de168ea366b9977ca536448483f949d451099fb4d53378f004e238` |
| process_schedule_overlay.json | run-time only, sha-pinned | `d4e46ccc207900a03eee8ac1833831f0e25d1e3e0a1dede6c611babef090d1a6` |
| progress.jsonl | run-time only, sha-pinned | `f0b7481e413553a8c8ba766230eabaf2f7f42581f497cadf7683a154c39192a0` |
| stress_plus60_station_days.csv | run-time only, sha-pinned | `18316a2b30de168ea366b9977ca536448483f949d451099fb4d53378f004e238` |
| stress_poll_lag_station_days.csv | run-time only, sha-pinned | `421cae2754bb7241460fc51ba54a8948bef205e49af352c35f8536c232317af4` |
| wp0_agreement.json | run-time only, sha-pinned | `845de87f9510affc29a5ee395ade080f374ead827213f5c1cd15f20087878b5b` |

## Holdout

Holdout touch: replay days 2026-09-18..2026-09-30 and tail days 2026-07-01..2026-09-17 lie inside the frozen NBP holdout [2026-07-01, 2026-10-02); they are read under clause 3 of the holdout ruling as descriptive evidence only. 2026-10-01 is sealed and never read; 2026-10-02..2026-10-13 statistics are disclosed contamination for AUT-4 forward windows. This run fits nothing and never calls open_holdout.
```

