# F13 Phase A prereg pins and freeze protocol, r3 (2026-10-07)

Status: **frozen intent.** Every value and every derivation rule below is fixed now. Only the two blocked pins (§B) are filled in later, and only by applying their stated rule mechanically. One gated freeze follows around 2026-10-20 (§D). Until that freeze lands, no feature build counts toward scoring.

## History

- **r1** (2026-10-06): proposal from the prediction-market-reviewer.
- **r2** added the build pins (FB-R1..R15).
- **r3** merges the round-2 reviews:
  - prediction-market-reviewer: SOUND-WITH-CHANGES.
  - architect: REQUEST_CHANGES on the freeze process.
  - Every change both reviewers asked for is adopted. The rulings are PIN-R1..R10 below.

## A. Statistics pins (fixed now)

| Pin | Value |
|---|---|
| floor_multiple | 0.25 |
| leak_audit_spread_multiple | 3.0 |
| m0_prime_tolerance_crps_f | 0.03 |
| station_tolerance_crps_f | 0.05 |
| student_t_nu | 5 |
| sigma_floor_f | 0.75 |
| weight_sum_lambda | 1.0 |
| min_cell_rows | 60 |
| bootstrap_n | 10000 |
| bootstrap_seed | 20261006 |
| m0_bootstrap_draws | **200** (PIN-R1) |
| champion_cdf_method | The literal `CdfMethod` name read from the committed champion config. The freeze commit records the source path and commit (PIN-R2). |
| rung_edges_f | `[-20,-18,-16,…,118,120]`, written out in full in the JSON: 71 even integers (PIN-R2). |
| min_uncensored_lag_samples | 30 |
| embargo_days | 3 |
| veto.reference | `{"kind":"raw_nbp_cdf","method":"NORMAL","spread_prob":0.02}` |

## B. Build pins

| Pin | Value or rule |
|---|---|
| anchors | **D-1:** 18:00Z on the previous day. **D0:** 10:00 LST at fixed standard offsets (EST 15Z, CST 16Z, PST 18Z). The sensitivity variant `d0_12lst` is never mixed into the primary. |
| obs_source | `iem_routine_metar_tgroup_round_half_up_f` |
| obs_cadence_seconds | 3600 |
| obs_routine_minute_by_station | `{"KLAX":53,"KMDW":53,"KMIA":53,"KNYC":51,"KSFO":56}`, one value per station (PIN-R3). |
| obs_min_coverage_per_station_year | **0.95**, fixed a priori and never measured from a build (PIN-R4). |
| obs_max_pin_minute_excluded_share | **0.02**, a new pin (PIN-R4). |
| lag_arm_max_lost_fraction | **0.05** overall, 0.05 per horizon, 0.10 per station (PIN-R5). |
| source_lags_ns | **BLOCKED → rule.** Per source, the larger of the R29 floor and the C1 p99 over ≥14 measured days. The rule is enforced in code (PIN-R6). |
| source_breaks | **BLOCKED → rule.** A flat ISO-date list: the union of LAMP MDL/LAV basis changes, PFM layout eras, MOS model changes and NBM version changes. These are taken **only** from the archive and provenance reports, never from residuals or CRPS shifts. An empty list must be stated as "none considered" (PIN-R7). |

## C. Rulings

- **PIN-R1. `m0_bootstrap_draws = 200`.** That is `DEFAULT_BOOTSTRAP_DRAWS`, which keeps the positive control "M0 reproduces the committed champion".
- **PIN-R2. Exact literals.** Every pin is written in the freeze as an exact JSON literal. No "about" values.
- **PIN-R3. One routine minute per station, not per station-year.** The data show no drift, and per-year values would add free parameters.
- **PIN-R4. Coverage and minute-share consequence, pre-registered.**
  - A station-year counts as failing if its coverage is below 0.95, or if its share of reports excluded for being off the pin minute is above 0.02.
  - A failing station-year is **excluded from every arm, M0 included**, and is listed in the report.
  - The build does not refuse. It refuses only if every station-year fails.
  - The thresholds are never relaxed.
  - No threshold may be chosen while looking at the truth-gap diagnostic in the build report.
- **PIN-R5. Lag-arm loss caps.**
  - The caps apply overall, per horizon (D-1 and D0 separately) and per station. Exceeding any cap means the run is refused.
  - The twin's measured loss may only refuse a run. It can never loosen a cap.
  - The primary delta on the common keys is always reported.
- **PIN-R6. Lag rule enforced in code.** The runner refuses if any pinned `source_lags_ns` value is below that source's C1 observed p99.
- **PIN-R7. Source breaks.**
  - Breaks come from provenance only.
  - The runner refuses unless every break the builder observes (`source_breaks_observed`, NBP version breaks included) is in the pinned list.
  - Breaks define folds, so they feed the M0 fold SD and therefore the floor. They must be pinned before stage A.
- **PIN-R8. Freeze guards.**
  - (a) The builder refuses an UNFROZEN prereg unless it runs with `--draft-scratch`. That mode writes to a non-scoring location, stamps a non-scoring sidecar, and the runner refuses its output.
  - (b) The runner refuses if the prereg file's git history holds more than one commit with a non-`UNFROZEN` `frozen_sha`. In that case it has been re-frozen.
  - (c) A test pins the frozen content digest, after the freeze, the way M1-v3 does.
  - (d) Any amendment goes into a new `_v2.json` with an amendment record, and both results are reported.
- **PIN-R9. Required pins.** Every builder pin is added to the runner's `REQUIRED_PINS`, so a null value refuses by name: `anchors`, `source_lags_ns`, `obs_source`, `obs_cadence_seconds`, `obs_routine_minute_by_station`, `obs_min_coverage_per_station_year` and `obs_max_pin_minute_excluded_share`. The veto script must run the same frozen-blob check.
- **PIN-R10. Limits of the gate.**
  - The leak-audit spread (about 0.6 °F) catches only gross leaks. The +60 min lag twin is the real leak control and stays mandatory.
  - Passing Phase A means only that the blend forecasts better than NBP. It says nothing about beating the market. Phase B/C still has to show net edge after costs.

## D. Sequence

1. **Now:** build the PIN-R4..R9 guards, gated, and fill §A plus the fixed §B values into the skeleton.
   - `frozen_sha` stays `UNFROZEN`.
   - Draft builds may run only with `--draft-scratch`, as engineering smoke tests.
2. **Around 2026-10-20**, once C1 has ≥14 measured days and the backfills are complete:
   - derive `source_lags_ns` and `source_breaks` by their rules;
   - make **one** gated freeze commit and stamp it;
   - push.
3. **After the freeze:** build the scored primary pair and its lag twin, then run stages A–C.

## E. C1 lag-evidence rulings (coordinator, 2026-10-07)

`scripts/analysis/c1_lag_evidence.py` (branch `feat/f13-c1-lag-samples`) was run on the live ledgers. Only **lamp-mdl** and **pfm** have a live measurement path, each with 2 days of data so far. There is **no live path** for **lav-iem**, **mos-gfs** or **obs**.

- **C1-R1. Measure all five sources; never pin a lag from its floor alone.**
  - Add collector legs that record the first-seen time for three sources:
    - **lav-iem:** the IEM LAV product.
    - **mos-gfs:** GFS MOS MAV for the five stations.
    - **obs:** routine METAR, polled from the **same endpoint and client that the live obs ingest uses**, so the measured lag is the lag the bot would see.
  - The PIN-R6 rule `max(floor, p99)` then applies to all five sources.
  - **Consequence:** the freeze date becomes the later of 2026-10-20 and the date the last of these legs reaches 14 measured days.
- **C1-R2. `lamp-mdl` lag is measured on the live NOMADS LAMP feed.** That is the feed a live consumer reads. The pin key names the source family, not the archive host.
- **C1-R3. A lag bounded by poll cadence is accepted.** First-seen minus issuance overstates the true lag by up to one poll interval (pfm p99 is 160 min so far). For leak safety that error falls on the conservative side, so it is accepted.
- **C1-R4. Key unification.**
  - The runner's `_check_c1` counts by `LEVEL_SOURCES` (`lamp`, `pfm`, `mos`), while the pins use the five lag keys. `_check_c1` must count and require by the five pin keys.
  - The evidence file is produced only by `c1_lag_evidence.py`, using schema `c1_lag_evidence/v1`.

- **C1-R5. Collector lock contention (coordinator, 2026-10-08).** A long PFM history backfill holds the `us-pfm-afos` store lock. The pfm collector tried the lock once and logged `skipped_locked` for hours, writing no ledger row. The next free poll then stamped a late first-seen, and 2–3 h lock-recovery lags passed the 3 h `late` censor into the p99: 10 of 15 pfm samples above 2 h. Two fixes:
  - **Collector.** On a busy lock, retry with bounded backoff for up to `COLLECTOR_LOCK_WAIT_S` = 120 s. The wait CONSUMES the cycle's work budget, with a 30 s margin, and is never added on top of it. The launch window is rechecked after the wait.
  - **Evidence (revised after review).** A cycle that ends `skipped_locked` appends a ledger row of kind `skipped`. `c1_lag_evidence` censors a `seen` sample as `censored_poll_gap` iff a `skipped` row for that source lies in [first_seen − MAX_POLL_GAP_NS, first_seen). Skips logged before this change come from `docs/evidence/f13/c1_historical_skips_2026-10.json` (derived from the journal: 25 pfm skips, 10-06..10-08). The first design took the previous ledger row as the previous poll. It was rejected because ledgers are event-driven, so it censored normal fast samples on lav, mos and obs.
  - On the 10-08 live ledger, pfm went from measured_days 3 / uncensored 53 to 2 / 35, with 18 samples censored for poll gap. p99 went from 160.22 to 160.21 min. The remaining maximum is a refusal-driven KSFO firing, not a lock recovery.
  - **Consequence.** A PFM backfill costs pfm measured days. Run PFM backfills outside the days needed to reach the 14-day C1 minimum, or accept the later freeze date.
