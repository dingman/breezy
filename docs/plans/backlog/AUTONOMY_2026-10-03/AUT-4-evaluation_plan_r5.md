# AUT-4: Evaluation (offline screening, forward shadow, live sequential). Plan r5

## 0. Header

| Field | Value |
|---|---|
| ID | AUT-4 |
| Title | Evaluation: the `OFFLINE_CHALLENGER` (screening, no α), `FORWARD_SHADOW` (confirmatory, α per nomination) and `LIVE_SEQUENTIAL` C4 producers; the nomination-column function (`k_life`, `alpha_k`, `n_min_eff`, `n_cap`, `nomination_feasible`); the feasibility record with the window cap; the `engine_input/v1` schema; evaluator self-monitoring |
| Round | **r5** (2026-10-03), final polish. r4 stays unchanged at `docs/plans/backlog/AUTONOMY_2026-10-03/AUT-4-evaluation_plan_r4.md`. This round applies every item K1–K10 of `reviews/AUT-4-r4-merged.md` (prediction-market-reviewer 94, mle-reviewer 91; zero CRITICAL or HIGH; both endorse I-1 and I-2) and disposes them in **§R5**. The r4 rebase (§R4) stands except where §R5 supersedes it |
| ARCH consumed | **FROZEN Rev 9.2**: `docs/plans/backlog/AUTONOMY_2026-10-03/reviews/snapshots/ARCH_rev9_2.md`, 150 189 B, sha256 **`1b288d0e0172b233b791d875845e8002824a52d4a2e7819685ec0f2057572f42`** (verified with `sha256sum` on 2026-10-03; equals the README Items-table freeze), **plus** `docs/plans/backlog/AUTONOMY_2026-10-03/reviews/ARCH-ERRATA-rev9_2.md` (E-1..E-4; only E-3 touches this plan: Z labels cited here without the `R9.2-` prefix keep their pre-9.2 meaning, so "Z1" is the subject-sha binding and "Z4" the slot-anchored validity, exactly as ARCH C4 still cites them). No older snapshot is cited as a basis |
| Coordinator decisions | `reviews/ALPHA-decision.md` **as amended** (α per nomination; `k_life` never resets; ≤ 1 nomination per window; K_LIFETIME 4), `reviews/HOLDOUT-decision.md` (consumed through ARCH C4.1 by name), `reviews/ROLLBACK-FAILURE-decision.md` (no AUT-4 surface; an accepted LIVE FAIL feeds AUT-7 only through the engine). All binding |
| Repo HEAD read | `4b8347a6` (branch `feat/data-capture-and-risk`) |
| Current score | 2 |
| Target | 3 |
| Upstream | ARCH-0 (Wave 0: C1–C6 types, `verdict/v1` writer and identity, C5 store with the nomination columns and `lineage_counters`, registry read API, `pins.py` ceilings, the C4.1 ruling filed); AUT-1 (C1 including `forecast_input_sha256`, `depth_ref`/`quote_ref`, `LifecycleEvent`); AUT-2 (C2 admissible rows, the 14:15Z label slot, RECONCILIATION); AUT-3 (C3 candidates at ≤ 1 MINT per lineage per day; `refit_run/v1`); AUT-5 (the engine that writes the nomination PROMOTE row and the `engine_input/v1` journal; the policy ruling and its `autonomy-policy/v1` block; `DEFAULT_RESTRICTIVE_CLASS`); AUT-6 (`deliver_with_proof`; the intraday producer that runs `eval_staleness`; the memory-sum HEALTH verdict); AUT-7 (the drill child, screened only) |
| Downstream | AUT-5 (consumes every C4 verdict; calls `compute_nomination_columns` when it writes a SHADOW→CHALLENGER PROMOTE; files the policy ruling whose AUT-4 sections are drafted in §3.10); AUT-7 (an accepted LIVE_SEQUENTIAL FAIL is a DEMOTE cause and thus a rollback input) |
| Status | PLANNING. Nothing is implemented. Every ruling text below is a DRAFT for the peer-review loop; none is decided here. **(r5)** New cross-plan requests: AUT-5 (K3 transaction call and contract test; K4 newest-per-(family, kind) consumption), AUT-3 (K8 reproducibility-rerun end ≤ 10:45Z), ARCH-0 owner review of `src/breezy/persistence/autonomy/sample_size.py` (K2) |

**Headline (read first).**
- AUT-4 can reach score 3 as *machinery* before the 2027-01-25 KILL. The proof window opens only after the §6.4 prerequisites: the C4.1 ruling (Wave 0), the FQ boundary ruling R-B `PREREG_FQ_v1`, the AUT-5 policy ruling, ARCH-0's Wave 0 surfaces, and AUT-6's memory-sum PASS. No ARCH revision is awaited: Rev 9.2 already carries every item r3 listed as P4-7..P4-15.
- If R-B is not filed by **2026-12-01**, AUT-4 is declared **score 2**, because "every live family is evaluated on pre-registered sequential tests" would be false for FQ.
- **(r4) α is charged per nomination, and today no nomination is feasible.** A nomination is the engine's SHADOW→CHALLENGER PROMOTE on an accepted OFFLINE_CHALLENGER PASS. Its FORWARD_SHADOW n_min_eff (≥ 403 independent station-days at α_1, deff 1; 605 at deff 1.5; larger at deeper k) exceeds n_cap = ⌊4 × 28 × 0.8⌋ = 89, and exceeds the 120-day ceiling (≤ 480 at uptime 1.0). So every nomination is **infeasible**: `nomination_feasible=false`, `alpha_k = 0`, `k_life` unchanged, `infeasible_nominations` incremented, the window's single slot used, and every FORWARD_SHADOW for that nominee is `INCONCLUSIVE(window_cap_below_n_min)` by construction. Verdicts still flow daily, so the machinery is exercised; **no promotable path is claimed**, consistent with `promote_enabled=false`.
- Consequently, under today's σ and X, `k_life` stays 0 and no α is spent; K_LIFETIME (≤ 4) binds only once a nomination becomes feasible. r3's "k_life reaches 6 in two windows, then every candidate is nominal" is withdrawn: ARCH has no nominal tier and refuses a nomination past K_LIFETIME.
- OFFLINE_CHALLENGER is **screening only** (no α), scored on external weather on forward days (≥ 2026-10-02) after the candidate's training end, never on the C4.1 frozen holdout.
- The only verdict that can reach a decisive terminal state before the KILL is LIVE_SEQUENTIAL on FQ under R-B. Its probability of reaching n_max = 160 is 0.67–0.89 at node uptime ≥ 70% (§6.3). At n = 160 the power is ≈ 0.69 against a +0.10 effect; the 80%-power MDE is ≈ +0.113.
- **(r4)** A LIVE_SEQUENTIAL FAIL DEMOTEs even before the policy ruling is filed, through ARCH's restrictive fallback (`no_policy_ruling` + `DEFAULT_RESTRICTIVE_CLASS`). r3's "no autonomy DEMOTE before a policy ruling" gap is closed by ARCH.
- **(r5)** Every input to `compute_nomination_columns` is a pinned policy-block value (K1); the sample-size primitives are defined once in `src/breezy/persistence/autonomy/sample_size.py` (K2); resampling seeds are derived per (subject, slot, role), so a same-slot recompute is bit-identical (K7); `EVAL_OFFLINE_TIMEOUT_START_S` = 6299 (K5).
- Evidence class for any DONE claim: **"machinery proven, edge unproven"**.

**Path convention (programme rule).** Code and test paths are repo-root-relative to `/home/jon/breezy`. Runtime stores are under `~/.local/share/breezy/` with `~` = `/home/jon`; the shorthand `$STATE` below means exactly `/home/jon/.local/share/breezy`.

---

## 1. Goal state

**README AUT-4 score-3 criterion (verbatim).**
> - Every candidate from AUT-3 is evaluated automatically against the current champion on pre-registered, cost-aware metrics: out-of-sample Brier/CRPS, traded-rung calibration, and EV net of fees and slippage.
> - Every live family is evaluated daily on AUT-2 labels with the pre-registered sequential tests.
> - Every result is a machine-readable, schema-versioned verdict that AUT-5 consumes.
> - Every verdict states its own power or `n_min` and its time to verdict.
>
> **Live proof:** 7 consecutive days of automatic offline and live verdicts for every live family and every new candidate, each consumed by the AUT-5 policy engine as its input record.

The plan also meets README "Scale" criteria (a)–(f) and the ARCH §5.3 window rule:
- a day counts only if it has ≥ 1 real fill or a tagged canary fill;
- a window needs ≥ 5 real fills;
- canary and drill fills never count toward any n, look or the KILL clock.

**ARCH Rev 9.2 §10 obligations for AUT-4 (verbatim).**
> the replay-sufficiency check that admits forward-shadow tape days; station-day clustering; the measured qualifying station-days per day; the feasibility record (`n_min`, MDE at α_K, `eta_date`) handed to the policy ruling; lifetime nomination and α accounting (`k_life`, `alpha_k`, `n_min_eff`, `n_cap`, the window-cap rule, `BOOTSTRAP_B_MAX`; C4); the `engine_input/v1` schema and contract test (P4-9); `verdict_id` without `produced_at_ns` (P4-11); the two ruling-sha fields (P4-10) and the five `assumptions` tags (P4-12); the calibration non-inferiority margin and measured false-fail rate (P4-6); the FQ boundary ruling draft (P4-2); the slippage source and its `assumptions` tag; the live-sequential producer over admissible labels; `TimeoutStartSec` on its oneshots; the relative calibration test and `MIN_CALIBRATION_BUCKETS` (V16); the nomination columns (V4).

Also absorbed from ARCH Rev 9.2: §4.5 Z4 (`MAX_VERDICT_VALIDITY_H` ≤ 26), W1 (ATTEST cadence invariant), W7 (`forward_window_days` 28–120, tumbling), the K_LIFETIME / per-window / mint-rate / `BOOTSTRAP_B_MAX` / `MIN_CALIBRATION_BUCKETS` ceilings; C4.1; §5.2 locks, launch-window rule and memory (14G); §5.3 evidence rules.

| Obligation | Section / WP |
|---|---|
| Replay sufficiency | §3.4, WP3 |
| Station-day clustering | §3.2, WP2 |
| Measured qualifying rate | §6.3, WP0 |
| Feasibility record (`n_min`, MDE at α_K, `eta_date`, `n_cap`) | §3.8, WP7b |
| Nomination and α accounting (`k_life`, `alpha_k`, `n_min_eff`, `n_cap`, `nomination_feasible`, window cap, `BOOTSTRAP_B_MAX`) | §3.5, §3.2, WP5 |
| `engine_input/v1` schema and contract test | §3.13, WP8 |
| `verdict_id` without `produced_at_ns` | §3.1, WP2 |
| Two ruling-sha fields; five `assumptions` tags | §3.1, §3.1a, WP2/WP4 |
| Calibration NI margin, measured false-fail rate, `MIN_CALIBRATION_BUCKETS` | §3.10 R-C, WP0, WP2 |
| FQ boundary ruling draft | §3.10 R-B, WP7a |
| Slippage source and tag | §3.7, WP6 |
| Live-sequential producer over admissible labels | §3.6, WP4 |
| `TimeoutStartSec` on its oneshots | §3.9, WP4/WP6 |
| Nomination columns (V4) | §3.5, WP5 |

---

## 2. L-1 null hypothesis and reuse

The null hypothesis is that Nautilus or existing Breezy already provides each need. Rows unchanged from r3 are listed briefly; rows changed in r4 are marked **(r4)**.

| Need | Checked | Verdict |
|---|---|---|
| Statistics over shadow decisions (Brier, permutation, α ledger) | `.venv/lib/python3.13/site-packages/nautilus_trader/analysis/analyzer.py:38` `PortfolioAnalyzer`: realised-PnL statistics over *filled* positions. Nothing native does Brier, cluster permutation, LD-OBF or α spending | **The gap is real** for the statistics |
| Forward-shadow replay | `scripts/analysis/nbp_shadow_parity.py:275` `run_live_parity` (native `BacktestEngine` via `BreezyBacktestConfig`, `submit_veto` always refusing, Depth10) — re-verified by codegraph at `4b8347a6` | **Reuse.** Move it (WP1) |
| Tape read | Native `ParquetDataCatalog` (`scripts/analysis/nbp_shadow_parity.py:512`) | **Reuse** |
| Sequential looks and boundaries | `scripts/analysis/family_tally_v2.py:625` `run_sequential_looks` (codegraph-verified); `scripts/analysis/crh_group_sequential_boundaries.py:243`; `scripts/analysis/aud07_live_rule_crossing_sim.py:158,210`; `src/breezy/settlement/current_rung_hold_v2.py:296,346,365,433,470`; `src/breezy/persistence/gs_boundary_artefact.py:219` | **Reuse**, moved byte-identically (G36) |
| Brier, reliability, calibration leg, cluster bootstrap | `scripts/analysis/forecast_conditional_scoring.py:110,139,237,267,278,303,392,428` (`evaluate_calibration_leg` at `:392`, codegraph-verified); `src/breezy/settlement/roi_bound.py:93` `B_RESAMPLES`, `:97` `SEED` | **Reuse.** R-C reuses the reliability binning (`:303`) and the pinned seed |
| Market baseline, look-ahead guard | `scripts/analysis/wp7b_market_as_forecaster.py:169,232,372,475,707` | **Reuse**, moved (G36) |
| Replay sufficiency | `src/breezy/analysis/replay_sufficiency.py:651,694,207` | **Reuse**, plus a kind-keyed FQ window |
| Forecast vintage at decision | `src/breezy/strategy/ladder_ev/forecast_state.py:179-221,306-321`; `src/breezy/persistence/nbp_derived_store.py:142-153,196-243` | **Reuse** |
| Per-child timeout, peak RSS, remaining-budget launch | `scripts/analysis/replay_daily_runner.py:1014-1085` `_run_subprocess_with_rss`; `:1395-1484`; `:1818-1819`; `deploy/systemd/replay-daily-run.sh:48-50` | **Reuse the pattern** in `src/breezy/analysis/autonomy/subprocess_rss.py` and `budget.py` |
| Oneshot runtime bound | ARCH G29/G32; host systemd 259 `man systemd.service`; `deploy/systemd/breezy-replay-daily.service:62` `TimeoutStartSec=1800` | **Reuse `TimeoutStartSec`**; never `RuntimeMaxSec` |
| Holdout split and single-look marker | `src/breezy/analysis/nbp_calibration.py:273-278` `DEFAULT_SPLITS` (no holdout end, G37); `:353` `open_holdout` (codegraph-verified) | **Consume C4.1 by name.** AUT-4 never calls `open_holdout`; AUT-3 owns the `holdout_end_exclusive` widening |
| Slippage floor | `docs/evidence/RULING_AUD-12a_slippage_allowance_2026-09-27.md` (0.01) | **Reuse** as the floor (R-E) |
| Live IOC fill outcome | C1 `TrySubmit` + `LifecycleEvent` (production); exec store `retirement_reason` for the WP0 baseline only | AUT-4 never imports the exec store |
| **(r4)** Nomination bookkeeping | ARCH C5: the PROMOTE row's nomination columns (`k_life`, `alpha_k`, `n_min_eff`, `n_cap`, `nomination_feasible`), `lineage_counters.nominations`/`infeasible_nominations`/`alpha_spent`, the store's K_LIFETIME and distinct-k checks | **Consume.** AUT-4 supplies only the pure arithmetic that fills the columns (§3.5); it keeps no ledger of its own. r3's flock-serialised `assign_k_life` is deleted |
| **(r4)** Verdict writer, identity, registry reader, `pins.py`, engine input journal writer | ARCH-0 `src/breezy/persistence/autonomy/` (C4 identity excludes `produced_at_ns`); AUT-5 engine writes `engine_input/v1` | **Consume.** AUT-4 writes no new store; it owns the journal *schema and contract test* only |
| Run wall time and peak RSS | `resource.getrusage`; cgroup v2 `memory.peak`; systemd `ExecStopPost=` with `$SERVICE_RESULT`/`$EXIT_STATUS` | **Reuse**; only the small run-record writer is new (§3.11) |

---

## 3. Design

### 3.1 Contracts; rules common to every producer

**Contracts.**
- **Consumes:**
  - C1: `DecisionRecord` Take/TrySubmit (`eval_ns`, `depth_ref` or `quote_ref`, `p_hat`, `forecast_input_sha256`), `LifecycleEvent`, `drill`, `source`.
  - C2: admissible `window_complete` rows with `p_source=c1_decision` only (a null `decision_id` row is never admissible; `canary`, `drill`, `voided_pair` rows never count).
  - C3: `forward_eval_start_utc`, `train_end_exclusive_utc`, `leakage_assertions` (incl. `no_sealed_holdout_rows_in_train`).
  - C5, read-only (`mode=ro`): the fold at `now`; the nominee's SHADOW→CHALLENGER PROMOTE row and its nomination columns; `lineage_counters` (`nominations`, `infeasible_nominations`, `alpha_spent`, `holdout_opens`); the bound artefact sha.
  - C6: the `Evaluator` slot (`offline`, `forward_shadow`, `live`).
- **Provides:**
  - C4 kinds `OFFLINE_CHALLENGER`, `FORWARD_SHADOW`, `LIVE_SEQUENTIAL`;
  - `HEALTH` detectors `eval_completeness`, `feasibility_consistency`, `eval_excluded_fraction`, `eval_n_stalled`, `eval_resource_creep`, **(r4)** `eval_replay_path`;
  - the detector function `eval_staleness`, evaluated by the AUT-6 intraday producer into an intraday HEALTH verdict (§3.9);
  - **(r4)** `compute_nomination_columns`, called by the AUT-5 engine (§3.5);
  - the `engine_input/v1` schema and contract test (§3.13).

**Bound subject sha (Z1).** `subject_artefact_sha256` is the family's bound sha from its BOOTSTRAP or MINT row (for the drill child, the incumbent's sha, by the C3 no-new-lineage rule).

**Validity anchored to the slot (Z4).**
- `valid_until_ns = slot_start_ns(today) + 26·3600·10⁹`, where `SLOT_UTC` equals the unit's `OnCalendar` (contract test).
- The producer refuses (ERROR) if `produced_at_ns < slot_start_ns`.
- The late bound is `TimeoutStartSec`, which includes the flock wait run inside `ExecStart`.
- Timers set `AccuracySec=1s`, `RandomizedDelaySec=0`, `Persistent=false`.
- Tests: `tests/unit/autonomy/test_verdict_validity.py::test_validity_anchored_to_slot_never_exceeds_ceiling`, `::test_worst_case_start_jitter_bounded`, `::test_offline_successor_lands_before_predecessor_expiry` (asserts `TimeoutStartSec + AccuracySec ≤ 7200 s − 900 s` for `breezy-autonomy-eval-offline`).

**(r4) Verdict identity (ARCH C4, P4-11).**
- `verdict_id = sha256(canonical body − {verdict_id, produced_at_ns})`, computed by the ARCH-0 `verdict/v1` identity function; AUT-4 calls it and never chooses. `valid_until_ns` stays in the body and is slot-anchored, so a recompute on identical inputs in the same slot yields the same id and the store treats the byte-equal body as an idempotent no-op; the store refuses a different body under an existing id (ARCH `test_differing_body_same_id_refused`).
- r3's `recompute_key` fallback is deleted.
- Test `tests/unit/autonomy/test_verdict_identity.py::test_recompute_same_slot_same_inputs_same_verdict_id`.

**(r5, K7) Resampling seeds are derived, never shared.** Every permutation and bootstrap draw (the §3.2 permutation test, the §3.5 screening bootstrap, the R-C paired bootstrap, the (b) `LB_ev` sign-flip) uses
`seed = roi_bound.SEED XOR int(sha256(subject_artefact_sha256 ‖ slot_date ‖ role).hexdigest()[:8], 16)`,
where `roi_bound.SEED` is `src/breezy/settlement/roi_bound.py:97` (20260904), `‖` is the byte `0x1F` between UTF-8 fields, `slot_date` is the ISO UTC date of `slot_start_ns`, and `role` is a closed literal from `{screen_brier_bootstrap, fs_a_permutation, fs_b_ev_signflip, fs_c_calibration_bootstrap}` (`src/breezy/analysis/autonomy/seeding.py::derive_seed`). So a same-slot recompute on identical inputs is bit-identical (which the verdict-identity rule above needs), and different subjects, days and statistics never reuse one draw stream. The R-B H0 MC keeps its own committed design seed. Tests `tests/unit/autonomy/test_seeding.py::test_same_slot_recompute_bit_identical` (two full producer runs in one slot on fixture inputs give byte-equal verdict bodies, p-values and bounds included), `::test_seed_differs_by_subject_slot_and_role`, `::test_role_is_closed_literal`.

**(r5, K9) Decimal serialisation.** `alpha_k` and `alpha_spent` are JSON strings in the canonical form `format(d.normalize(), "f")` (zero is exactly `"0"`; α_1 is `"0.0125"`), produced by the ARCH-0 `verdict/v1` writer ("money is a string-decimal"); AUT-4 never emits a float for either. Test `tests/unit/autonomy/test_verdict_schema.py::test_decimal_fields_canonical_string`. The §7 store queries compare with `tonumber`, so they hold whatever the exact canonical string.

**`inputs[]` roles** (`{path_role, sha256}`, no paths; each must resolve under its role's root for engine acceptance): `label_set`, `archive_dataset`, `tape_snapshot`, `boundary_artefact`, `fs_replay_output`, `sigma_source`, **(r4)** `screen_verdict` (the accepted OFFLINE_CHALLENGER PASS the nomination cites), `registry_export` (the newest `$STATE/evidence/registry/registry_<venue>_<date>.jsonl` whose chain carries the nomination row). The nomination row's `transition_id` is recorded as `metrics.nomination_transition_id`.

**(r4) Two ruling-sha fields (ARCH C4, P4-10).**
- `policy_ruling_sha256`: the AUT-5 policy ruling's sha on every AUT-4 verdict, null only with `assumptions ∋ no_policy_ruling`.
- `family_prereg_sha256`: `LIVE_SEQUENTIAL` only, the family's registered boundary ruling (`PREREG_FQ_v1` for FQ); null on every other kind.
- r3's Rev 5 fallback (policy sha in one field, PREREG in `inputs[family_prereg]`, the `accepted_family_preregs` policy key) is deleted.

**(r4) `assumptions` (closed five-tag enum, ARCH C4, P4-12).** Only `slippage_champion_proxy`, `slippage_floor_aud12a`, `fill_survivorship_unmodelled`, `no_policy_ruling`, `drill`. r3's proposed `fixture_candidate` and `fill_selection_sensitive` tags are withdrawn: the fixture path is isolated by state root (§6.1) and flagged `metrics.fixture_candidate=true`; fill-selection sensitivity is `metrics.fill_selection_sensitive` and handled by a policy key inside the producer (§3.7). `sigma_source_contaminated` is a metric, never an assumption.

**Single-look discipline (FORWARD_SHADOW only).**
- A **feasible** nominee's FORWARD_SHADOW is evaluated confirmatorily **once**, at the first run where n ≥ n_min_eff for every predicate, inside its window. Before that it is `UNDERPOWERED`, counts only. FAIL or INCONCLUSIVE at the look is final.
- An **infeasible** nominee (`nomination_feasible=false`) never gets a look: every daily verdict is `INCONCLUSIVE(window_cap_below_n_min)`, counts only.
- OFFLINE_CHALLENGER is screening without α and may be recomputed daily; it never claims a type-I level.

**Nothing to evaluate (ARCH C4 invariant, U10; r5 K6 made exact).** The invariant is per producer.
- `eval_offline` with no SHADOW candidate and no drill child writes exactly one `OFFLINE_CHALLENGER` verdict `INCONCLUSIVE` with `metrics.day_status=NO_INPUT` and the venue **champion** as subject (`comparator_family_id` = the champion too; `n = 0`; `n_min` = `SCREEN_MIN_STATION_DAYS`). It always also writes the `eval_replay_path` HEALTH verdict, so the producer is never silent.
- The FORWARD_SHADOW lane of `eval_offline` writes **nothing** when no open-window nominee exists: a FORWARD_SHADOW verdict needs the four C4 fields from a nomination row (I-1), so a NO_INPUT FORWARD_SHADOW would carry nulls ARCH forbids.
- `eval_live` always has ≥ 1 fold family (the champion), so it writes one LIVE_SEQUENTIAL per CHAMPION or HALTED family and never needs NO_INPUT.
- Tests `tests/unit/autonomy/test_offline_challenger.py::test_no_input_is_offline_challenger_on_champion`, `tests/unit/autonomy/test_forward_shadow.py::test_no_nominee_writes_no_forward_shadow`; completeness per §3.11.

**Fail-closed.**
- Any missing, stale, unknown-version or unverifiable input, any leakage assertion failure, any producer exception: `ERROR`, plus a CRITICAL through `deliver_with_proof`.
- `UNDERPOWERED`, `INCONCLUSIVE` and `ERROR` never promote. An `ERROR` verdict is never "fresh" for `eval_staleness`.
- A FORWARD_SHADOW verdict whose `k_life` differs from the nomination row's column is `ERROR`; the engine journals it `k_exceeded` (ARCH C4 "No `k_exceeded` in operation").

**Payload hygiene.** No paths in verdicts. `test_autonomy_payload_hygiene_scan` covers the AUT-4 writers.

### 3.2 Clustering, the design effect, the permutation test and the draw cap

- **Unit.** The independent station-day `(station, climate_day)` (Y14). `assert_nondegenerate_clustering` (`scripts/analysis/forecast_conditional_scoring.py:288-299`, moved) refuses a degenerate key.
- **Primary statistic.** A studentised date-cluster sign-flip permutation test, one-sided at α_k: per-station-day paired differences are summed per climate date; each date's sign is flipped as a block. **(r5)** Seeded by `derive_seed(subject, slot_date, role)` (§3.1, K7).
- **(r4) Draw cap `BOOTSTRAP_B_MAX` (ARCH §4.5, a `pins.py` literal).**
  - `B = min(BOOTSTRAP_B_MAX, max(10 000, ⌈200/α⌉))` for the level α actually tested.
  - Proposed literal (for the ARCH-0 owner; the value is left to the policy ruling's peer review by ARCH §8, within the code ceiling): **2¹⁹ = 524 288**. With K_LIFETIME = 4, the deepest level any test uses is α_4/3 = 0.025·2⁻⁴/3 ≈ 5.21·10⁻⁴ (the (b) component, §3.7), and ⌈200/(α_4/3)⌉ = 384 000 ≤ 2¹⁹. So **every** test that can be run gets its full Monte-Carlo B; the tail branch is unreachable in operation.
  - The ARCH-required tail beyond the cap is kept as a guard: `p_H = exp(−T²/(2·Σ_d D_d²))` (Hoeffding bound on the unstudentised date-sum sign-flip statistic, a valid conservative upper bound), reported as `metrics.p_method = "hoeffding_tail"`; reaching it raises a defect alert.
  - Flips are generated in chunks of 16 384 (≈ 16 MB at C = 120 dates). Exact enumeration when C ≤ 20.
  - Test `tests/unit/autonomy/test_permutation.py::test_b_capped_and_tail_beyond_cap`, `::test_b_max_covers_k_lifetime_over_three`.
- **Cluster floor.** The test runs only if `C ≥ C_min(α) = ⌈log2(10/α)⌉` (**(r5)** `sample_size.c_min`, K2), else `UNDERPOWERED(min_clusters)`. C_min at α_1…α_4 = 10, 11, 12, 13; at α_k/3 for (b): 12 … 15.
- **Design effect.** `deff = 1 + (m̄ − 1)·ρ̂` (**(r5)** `sample_size.deff`, K2), ρ̂ measured out-of-fold on archive days before 2026-07-01 (WP0) and **pinned in the policy block** as `deff_pinned` (§3.5); `n_min_eff` per predicate = `max(⌈deff_pinned·n_min⌉, 4·C_min)`.
- **Cluster sensitivity.** The same test with station-day blocks; disagreement gives `INCONCLUSIVE(cluster_sensitivity)`, final at the look.
- **Family pin.** `event_family="rung_2f_traded"`; the median binary is refused. `calibration_leg_rung` and `underconfidence_mean_signed_dev` are always reported.

### 3.3 Modules (analysis layer, never imported by live packages; one persistence addition)

| Path | Purpose |
|---|---|
| **(r4)** `src/breezy/analysis/stats/sequential_looks.py`, `group_sequential_boundaries.py`, `scoring_core.py`, `market_baseline.py`, `drift_freshness.py` | ARCH G36 / AUT-4a: the `scripts/analysis/` statistics moved **byte-identically** into the §4.3 pin closure; the scripts stay as thin CLI wrappers; a test pins the moved source |
| `src/breezy/analysis/autonomy/shadow_replay.py`, `subprocess_rss.py` | Moved `run_live_parity` path; per-child timeout and RSS share |
| `src/breezy/analysis/autonomy/eval_stats.py` | `mde_one_sided`, `power_one_sided`, `eta_days`, `eta_date`. **(r5, K2)** `n_min_one_sided`, `c_min`, `deff` and `n_min_eff` are **imported** from `breezy.persistence.autonomy.sample_size`, never redefined |
| **(r5, K2)** `src/breezy/persistence/autonomy/sample_size.py` | The single definition of `n_min_one_sided(sigma, mde, alpha, power=0.80)` (stdlib `statistics.NormalDist`, no numpy/scipy), `c_min(alpha) = ⌈log2(10/alpha)⌉`, `deff(m_bar, rho)` and `n_min_eff(n_min, deff, c_min)`. Imports stdlib and `decimal` only. AUT-4 addition to the ARCH-0 package under the ARCH-0 owner's review (same basis as `nomination.py`, I-2). Test `tests/unit/autonomy/test_eval_stats.py::test_sample_size_primitives_single_definition` (asserts `eval_stats.n_min_one_sided is sample_size.n_min_one_sided`, likewise `c_min`, `deff`, `n_min_eff`) |
| **(r5, K7)** `src/breezy/analysis/autonomy/seeding.py` | `derive_seed(subject_sha, slot_date, role) -> int` with the closed role literal (§3.1) |
| `src/breezy/analysis/autonomy/permutation.py` | `date_cluster_signflip(diffs_by_date, alpha, seed, b)`; reads `pins.BOOTSTRAP_B_MAX`; chunking; tail guard |
| **(r4)** `src/breezy/analysis/autonomy/calibration_ni.py` | `relative_calibration_ni(cand, champ, dates, alpha, margin, seed, b)` → `(ece_diff_ub, n_buckets_paired)`; `false_fail_rate(...)` for WP0 (§3.10 R-C) |
| `src/breezy/analysis/autonomy/metric_registry.py` | Closed metric names and the per-kind required-field table (§3.1a); **(r4)** `nomination_transition_id`, `fixture_candidate`, `fill_selection_sensitive`, `day_status`, `msd_diff`, `outcome_reason` |
| `src/breezy/analysis/autonomy/windows.py`, `leakage.py`, `tape_admission.py` | Forward-window arithmetic (anchor, tumbling, `window_end`), leakage assertions, FQ tape admission |
| **(r4)** `src/breezy/persistence/autonomy/nomination.py` | `compute_nomination_columns(policy_block, lineage_counters, window_state) -> NominationColumns(k_life, alpha_k, n_min_eff, n_cap, nomination_feasible)`: pure, stdlib + `Decimal`, imports only `pins` and **(r5)** `sample_size`; **(r5, K1)** arithmetic only: every statistical input is a named policy-block key (§3.5), nothing is estimated or read from a store. Authored by AUT-4 WP5 as an addition to the ARCH-0 package under the ARCH-0 owner's review, because the AUT-5 engine must call it and must not import `breezy.analysis` (G15). Replaces r3's `alpha_ledger.py` |
| `src/breezy/analysis/autonomy/fill_model.py` | Live IOC fill rate (unresolved AMBIGUOUS = miss); slippage proxy; the joint (b) bound at α_k/3 per component; `N_IOC_MIN` refusal; worst-case survivorship bound |
| `src/breezy/analysis/autonomy/budget.py` | `REPLAY_PARALLELISM` (P, from WP0), **(r5, K5)** `EVAL_OFFLINE_TIMEOUT_START_S = 6299`, `SCREEN_BUDGET_S = 900`, `SCORING_RESERVE_S = 600`, `SAFETY_S = 300`, `FLOCK_WAIT_S = 900`, `FS_REPLAY_CHILD_TIMEOUT_S` (derived, §3.12), `MAX_BACKLOG_DAYS_PER_RUN = 3` |
| `src/breezy/analysis/autonomy/run_record.py` | Producer run record and the `ExecStopPost` entry (§3.11) |
| `src/breezy/analysis/autonomy/evaluators/forecast_quantile_ladder.py`, `feasibility.py`, `health.py` | The FQ `Evaluator`, the feasibility record, the HEALTH detectors |
| `src/breezy/analysis/autonomy/producers/eval_live.py`, `eval_offline.py`, `fs_replay.py` | Producer entry modules (pinned as `eval_live`, `eval_offline`, `fs_replay` in `PRODUCER_SOURCE_SHA256`). `fs_replay` output: `$STATE/derived/autonomy/fs_replay/<family>/<closure_sha12>/<day>/<station>.jsonl` (0444, tmp + rename) |

`breezy.analysis.autonomy` imports `breezy.persistence.autonomy`, never the reverse; `breezy.persistence.autonomy ↛ breezy.adapters` (ARCH contract) is untouched.

#### 3.1a Required fields per verdict kind

`—` means null with the literal reason.

| Field | OFFLINE_CHALLENGER (screen) | FORWARD_SHADOW (nominee) | LIVE_SEQUENTIAL | AUT-4 HEALTH |
|---|---|---|---|---|
| `n`, `n_unit` | forward station-days (weather-only) after `train_end_exclusive_utc`, ≥ 2026-10-02 | admissible station-days after the nomination date, inside the window, with ≥ 1 scorable rung event | combined station-day draws | — `HEALTH_NO_TEST` |
| `n_min` | `SCREEN_MIN_STATION_DAYS` (policy) | the row's `n_min_eff` | n at the first registered look (10); `metrics.n_max` = registered n_max; or reason `no_registered_boundary` | — |
| `power`; `mde` | — `SCREEN_NO_ALPHA`; the screen threshold `X_SCREEN` | 0.80 (design); `mde_one_sided(σ_pinned, n_min_eff, α_k)` for (a) | registered design power; registered MDE at n_max | — |
| `comparator_family_id` | champion | `MARKET_ASK_IMPLIED` for (a)/(b); champion for (c) | `BREAK_EVEN` | — |
| `alpha_spent` | lineage cumulative from `lineage_counters.alpha_spent` (unchanged by screening) | the same, which includes this nominee's `alpha_k` (0 if infeasible) | LD-OBF cumulative α at the information fraction (`metrics.alpha_scope="family_prereg"`) | — |
| **(r4)** `k_life`, `alpha_k`, `n_min_eff`, `n_cap` | null (ARCH: FORWARD_SHADOW only) | copied from the nomination row columns, never recomputed | null | null |
| **(r4)** `policy_ruling_sha256` | policy sha, or null + `no_policy_ruling` | the same | the same | the same |
| **(r4)** `family_prereg_sha256` | null | null | the family's registered boundary ruling sha; null with outcome `INCONCLUSIVE(no_registered_boundary)` | null |
| `eta_to_verdict_days` | `eta_days(SCREEN_MIN_STATION_DAYS, n, rate)` | `eta_days(n_min_eff, n, rate)`, or null with reason `window_cap_below_n_min` | from the registered looks | — |

**Before a ruling is filed.** With no policy ruling, `policy_ruling_sha256 = null` and `assumptions ∋ no_policy_ruling`: the engine rejects OFFLINE and FORWARD_SHADOW verdicts as `no_ruling` (nothing widens), and accepts a LIVE_SEQUENTIAL FAIL for DEMOTE through `DEFAULT_RESTRICTIVE_CLASS` (§3.6). With no family boundary: `INCONCLUSIVE(no_registered_boundary)`, which never acts. Test `tests/unit/autonomy/test_verdict_schema.py::test_verdict_v1_schema_complete_per_kind`.

### 3.4 Replay sufficiency for forward-shadow tape days

Unchanged from r3 §3.4 (conditions 1–9; excluded-day bias guard with `EXCLUDED_FRACTION_MAX`; oversize quarantine shared with `scripts/analysis/replay_daily_runner.py`; the separate FQ census file). Condition 7 now reads "forward day outside the C4.1 frozen holdout [2026-07-01, 2026-10-02)". Condition 9 (one `fs_replay` closure; `PENDING_RECLOSURE`; `INCONCLUSIVE(mixed_closure)` breach guard) stands. **(r4)** A C1 row with `quote_ref` but no `depth_ref` (U8) is excluded from the Depth10-matched slippage proxy by name (`no_depth_ref`) but still scored for (a). Tests: `tests/unit/autonomy/test_tape_admission.py::test_n_counts_current_closure_days_only`, `::test_mixed_fs_replay_closure_is_inconclusive`, `::test_frozen_holdout_day_refused`.

### 3.5 OFFLINE_CHALLENGER (screening) and the nomination columns

**(r4) OFFLINE_CHALLENGER is the screening stage (ARCH C4).**
- Subjects: every SHADOW family of an allowlisted lineage in the fold (one MINT per lineage per day at most, AUT-3), plus the AUT-7 drill child.
- Data: external weather only, on forward climate days ≥ max(2026-10-02, the candidate's `train_end_exclusive_utc`), never inside C4.1's frozen window, never a day ≥ the candidate's nomination date (screening days are never confirmation days).
- Statistic: `brier_rung_diff_vs_champion` on the traded rung family, with the pinned cluster bootstrap (`src/breezy/settlement/roi_bound.py:93` `B_RESAMPLES`), date-clustered, **(r5, K7)** seeded by `derive_seed(subject, slot_date, "screen_brier_bootstrap")`. `crps_tmax_diff_vs_champion` and `underconfidence_mean_signed_dev` are reported.
- Outcomes at the ruling's fixed thresholds (R-D):
  - `UNDERPOWERED(screen_min_days)` while n < `SCREEN_MIN_STATION_DAYS`;
  - `INCONCLUSIVE(NOT_DISTINCT)` if max|Δp| vs the champion on the pinned grid ≤ AUT-3's delta (always for the drill child, with `assumptions ∋ drill`);
  - `PASS` iff mean improvement ≥ `X_SCREEN` **and** the pinned-bootstrap 95% upper bound of Δbrier < 0;
  - otherwise `FAIL(stage=screen)`.
- It charges **no α** and makes no type-I claim; daily recomputation is permitted. Rows from archive days before 2026-07-01 are used only by WP0 to measure σ, ρ̂ and the calibration false-fail rate for the policy block, never per candidate. r3's archive pre-screen, `prescreen_fold_wins` and confirmatory "stage 2" are deleted.

**(r4) Nomination (ARCH C4 "Two limits, one index"; C5 PROMOTE row).**
- A nomination is the AUT-5 engine's SHADOW→CHALLENGER **PROMOTE** on an accepted OFFLINE_CHALLENGER PASS, refused by the store when the lineage's current window already holds a nomination (`MAX_NOMINATIONS_PER_FORWARD_WINDOW` = 1) or when α-charging nominations have reached K_LIFETIME (`MAX_NOMINATIONS_PER_LINEAGE_LIFETIME` ≤ 4). Drill rows (DRILL_ADMIT) are never nominations.
- The engine, holding `registry/engine.lock` in one `BEGIN IMMEDIATE` transaction, calls AUT-4's pure `compute_nomination_columns` and writes the five required columns:
  - **(r5, K1) Inputs are pinned block values only:** `alpha_total`, `stations`, `forward_window_days`, `uptime_floor`, `deff_pinned`, `sigma_pinned` (a), `sigma_b_pinned` (b), `mde_a`, `mde_b`, `mde_c`, `n_min_c` (a table keyed k = 1…K_LIFETIME), plus `lineage_counters.nominations` and the window state (`window_index`, `window_end`, `nomination_in_window`). The function reads no store, estimates nothing, and refuses (raises) on a missing key.
  - `n_cap = ⌊stations · forward_window_days · uptime_floor⌋`. **(r5)** `stations` is the pinned block value; `feasibility_consistency` FAILs if it differs from the committed root manifest's station count (§3.8).
  - At the candidate level α_k* = alpha_total·2^−(nominations+1): (a) `n_min_a = n_min_one_sided(sigma_pinned, mde_a, α_k*)`, C_min(α_k*); (b) `n_min_b = n_min_one_sided(sigma_b_pinned, mde_b, α_k*/3)`, C_min(α_k*/3); (c) `n_min_c = n_min_c[k*]` (R-C, simulated by WP0 and pinned, because it has no closed form; `mde_c` is the ΔECE distance below the margin at which its power is stated).
  - `n_min_eff = max over (a), (b), (c) of n_min_eff(n_min_x, deff_pinned, C_min_x)` with `n_min_eff(n, d, c) = max(⌈d·n⌉, 4·c)` (`sample_size`, K2).
  - If `n_min_eff > n_cap`: `nomination_feasible = false`, `alpha_k = 0`, `k_life = lineage_counters.nominations` (unchanged), the store increments `infeasible_nominations`; the window's slot is used.
  - Else: `nomination_feasible = true`, `k_life = nominations + 1`, `alpha_k = α_total·2^−k_life` (`Decimal`), and the store increments `nominations` and sets `alpha_spent = α_total·(1 − 2^−k_life)`.
- `k_life` never resets across windows or epochs; only a new lineage root (a reviewed commit) starts a fresh budget. Two pending nominees never share a k (single engine writer, CAS, and ≤ 1 per window).
- FORWARD_SHADOW reads all five columns from the row and never recomputes them; a mismatch between a verdict's `k_life` and the row is `ERROR` (`k_exceeded`).
- **(r5, K3) AUT-5 request (binding on the engine once accepted).** The engine calls `compute_nomination_columns(policy_block, lineage_counters, window_state)` **inside** the same `BEGIN IMMEDIATE` transaction that inserts the SHADOW→CHALLENGER PROMOTE row (after the CAS read of `lineage_counters`, before the insert), passing the named keys above from the verified policy block; the five columns are written exactly as returned, and no other code path writes them. Contract tests (AUT-4, `tests/contract/test_nomination_columns_contract.py`): `::test_promote_row_columns_written_only_via_compute_nomination_columns` (the function is replaced by a spy returning sentinel columns; the committed row must carry the sentinels, and a PROMOTE write with the spy never called fails the test), `::test_called_inside_begin_immediate_with_named_keys` (the spy asserts an open `BEGIN IMMEDIATE` transaction on the registry connection and the exact key set), `::test_missing_policy_key_refuses_nomination`.
- Tests (RED first, WP5): `tests/unit/autonomy/test_nomination.py::test_feasible_nomination_charges_alpha_k_life`, `::test_infeasible_nomination_charges_no_alpha`, `::test_infeasible_nomination_uses_window_slot`, `::test_k_life_never_resets_across_windows`, `::test_n_cap_formula_floor`, `::test_n_min_eff_from_pinned_sigma_and_ruling_mde`, `::test_columns_are_pure_function_of_block_and_counters`, **(r5)** `::test_inputs_are_named_block_keys_only`, `::test_n_min_b_at_alpha_over_3_and_n_min_c_table`; `tests/unit/autonomy/test_forward_shadow.py::test_fs_reads_columns_never_recomputes`, `::test_k_life_mismatch_is_error_k_exceeded`. AUT-4 also supplies fixtures for ARCH's `test_two_pending_nominees_get_distinct_k`, `test_window_cap_below_n_min_is_inconclusive`, `test_infeasible_nomination_charges_no_alpha`, `test_nomination_refused_past_k_max_lifetime`, `test_alpha_index_never_resets`.

**Windows (W7).** Tumbling per lineage from the policy block's `forward_window_anchor_date` (proposed 2026-10-02) with `forward_window_days` (proposed 28; pins 28–120). A nominee uses only forward climate days strictly after its nomination's UTC date and ≤ its window end.

**Window-end rules.**
- Infeasible nominee: every daily FORWARD_SHADOW is `INCONCLUSIVE(window_cap_below_n_min)`, decided at nomination and immutable; after the window end the producer restates the final outcome without replay.
- Feasible nominee whose n has not reached n_min_eff by the window end: `INCONCLUSIVE(window_end_underpowered)`, final.
- Tests: `tests/unit/autonomy/test_forward_shadow.py::test_window_cap_below_n_min_is_inconclusive_by_construction`, `::test_no_forward_day_past_window_end`, `::test_no_forward_day_on_or_before_nomination_date`, `::test_window_end_underpowered_final`.

**Today.** FORWARD_SHADOW (a) n_min_eff ≥ 403 at α_1 (deff 1; 605 at deff 1.5) > n_cap 89 (28 days, floor 0.8) and > 480 (120 days, floor 1.0): every nomination infeasible, `k_life` stays 0, no α spent.

**Holdout (C4.1).** `RULING_holdout_freeze_and_forward_window_2026-10-03` is consumed by name and never restated; `open_holdout` (`src/breezy/analysis/nbp_calibration.py:353`) is never called by AUT-4; the contamination of [2026-07-01, 2026-10-01) is disclosed and `metrics.sigma_source_contaminated = true` wherever σ comes from that window. Until the ruling is filed (Wave 0): `INCONCLUSIVE(SEALED_WINDOW)`.

### 3.6 LIVE_SEQUENTIAL over admissible labels

As in r3: inputs are admissible `window_complete` C2 rows with `p_source=c1_decision`, combined by `combine_station_day` (L-40); the registered boundary via the moved `src/breezy/analysis/stats/group_sequential_boundaries.py`; mapping CONTINUE→UNDERPOWERED, SURVIVE→PASS (only at n_max), KILL→FAIL, refusal→ERROR; families enumerated from the fold (CHAMPION and HALTED); prefix exclusion (`climate_day < D0′`); `n_min` = first-look n (10); a FAIL from the R-B loss stop before that look carries `metrics.stop_reason = "loss_stop"`. ARCH: never a new α-spend; canary and drill never counted.

**(r4) Changes.**
- A family with no registered boundary gets `INCONCLUSIVE(no_registered_boundary)` (ARCH name), which never acts.
- `family_prereg_sha256` carries the boundary ruling's sha; `policy_ruling_sha256` the policy sha. The engine accepts the verdict only if both match (ARCH C4 Engine acceptance).
- **Restrictive fallback (ARCH C4, P4-10; AUT-5 M10).** With no filed or verifiable policy ruling, the verdict carries `policy_ruling_sha256 = null`, `assumptions ∋ no_policy_ruling`, and `declared_action_class` = the literal `DEFAULT_RESTRICTIVE_CLASS["live_sequential"]` (AUT-4 requests `DEMOTE`, cause class `RECOVERABLE_MODEL`, from the AUT-5/ARCH-0 `pins.py` owner). The engine accepts a FAIL for DEMOTE only, never a widening row. So a KILL DEMOTEs from the day R-B is filed, policy or not.
- Unit: `breezy-autonomy-eval-live` takes the **studies flock** (§3.9), not its own lock.
- Tests: `tests/unit/autonomy/test_eval_live.py::test_n_min_is_first_look_n`, `::test_loss_stop_fail_labelled`, `::test_no_registered_boundary_inconclusive_never_acts`; `tests/integration/autonomy/test_live_fail_demotes.py::test_live_fail_accepted_with_both_ruling_shas_and_demotes`, `::test_live_fail_without_policy_demotes_via_default_restrictive_class`, `::test_family_prereg_sha_mismatch_is_error`.

### 3.7 FORWARD_SHADOW and the slippage source

**(r4) Subjects.** Only CHALLENGER families with a SHADOW→CHALLENGER PROMOTE (nomination) row, whose four C4 fields come from that row. r3's champion baseline and drill-child FORWARD_SHADOW verdicts are withdrawn, because neither has a nomination and ARCH C4 makes the four fields part of every FORWARD_SHADOW. Their purposes move:
- the daily replay→admission→scoring path is exercised by the HEALTH detector `eval_replay_path` on the champion (§3.11), which carries admitted days, exclusions by reason, parity results and the closure sha, and never feeds a promotion;
- the drill child is screened only (OFFLINE `INCONCLUSIVE(NOT_DISTINCT)`, `assumptions ∋ drill`).
CHALLENGERs reached by SUPERSEDE or DISPLACED are rollback targets, not nominees, and get no FORWARD_SHADOW.

**Replay.** Per-(closure, artefact sha, station-day) `fs_replay` child; the cache key includes `artefact_sha256` and the manifest-modulo-allowlist sha, so the champion's `eval_replay_path` replay and any byte-identical subject share one output. Replays per day ≤ 4 stations × (1 open-window nominee + champion) per lineage (§3.12).

**Predicates** (intersection-union; each at α_k from the row; a feasible nominee only):
- **(a)** `brier_rung_diff_vs_market < 0` by the §3.2 test, against the market-implied baseline (moved `wp7b_market_as_forecaster`).
- **(b)** Joint lower bound on effective EV per take, as r3 §3.7(b): `ev_eff = p_fill·ev_cond`, `ev_cond = held − ask − θ·ask·(1−ask) − slippage_proxy`; three components each at α_k/3 (Bonferroni): `LB_ev` (date-cluster sign-flip), `UB_slip` (floored 0.01), `p_fill_LB` (Wilson, trailing 28 days of live FQ IOCs); `N_IOC_MIN` = 30 and `N_PROXY_MIN` = 30 gate the look (below); C_min at α_k/3; `LB_ev` seeded by `derive_seed(…, "fs_b_ev_signflip")`.
- **(c) (r4)** Relative calibration non-inferiority to the champion, the R-C test (§3.10): one one-sided paired test over the same station-days' paired calibration buckets against the ruling margin `CALIBRATION_NI_MARGIN`; `INCONCLUSIVE(calibration_buckets_below_min)` below `MIN_CALIBRATION_BUCKETS` paired buckets; the absolute leg (`evaluate_calibration_leg`, `scripts/analysis/forecast_conditional_scoring.py:392`, moved) reported, never required.
- **(d)** `n ≥ n_min_eff` (the row's value) in independent station-days.
- **Look rule (r5, K9).** The look fires once, at the first run inside the window where (d) holds **and** `n_ioc ≥ N_IOC_MIN` **and** `n_proxy ≥ N_PROXY_MIN`. Until then the verdict is `UNDERPOWERED` (counts only). The two counts are ancillary: they count the champion's live IOCs and admissible champion fills, not a function of the nominee's paired differences, so conditioning the look time on them leaves the level of (a)–(c) unchanged. If the window ends first, the verdict is `INCONCLUSIVE(fill_rate_underpowered)` or `INCONCLUSIVE(PROXY_UNDERPOWERED)` (first unmet count in that order), final; otherwise §3.5 window-end rules. Test `tests/unit/autonomy/test_forward_shadow.py::test_look_waits_for_n_ioc_min_inside_window`, `::test_window_end_before_n_ioc_min_is_fill_rate_underpowered_final`.

**Slippage source (Y12).** `slippage_point = max(0.01, mean_slip)` from C2 `slippage` over admissible champion fills (trailing 28 days, matched via C1 `depth_ref`). `assumptions ⊇ [slippage_champion_proxy, slippage_floor_aud12a, fill_survivorship_unmodelled]`. Without the policy ruling's acceptance of `slippage_champion_proxy` for the challenger's policy class, the verdict is `INCONCLUSIVE`.

**Survivorship** (direction as derived in r3 §3.7 and §R3 F4; unchanged): the estimator is anti-conservative if IOC misses concentrate in favourable decisions. `metrics.ev_eff_worst_case` (Manski bound) is reported. **(r4)** If `ev_eff_worst_case ≤ 0` while (b) passes, the producer sets `metrics.fill_selection_sensitive = true` and applies the policy key `ACCEPT_FILL_SELECTION_SENSITIVE` (bool, R-E): if false, (b) gives `INCONCLUSIVE(fill_selection_sensitive)`. No new `assumptions` tag.

Tests: `tests/unit/autonomy/test_forward_shadow.py::test_b_joint_bound_bonferroni_alpha_over_3`, `::test_fewer_than_n_ioc_min_inconclusive`, `::test_worst_case_survivorship_bound_reported`, `::test_fill_selection_sensitive_inconclusive_unless_accepted`, `::test_only_nominated_challengers_get_forward_shadow`, `::test_calibration_leg_relative_inconclusive_below_min_buckets` (the ARCH test name, AUT-4 implementation).

### 3.8 Feasibility record

`$STATE/evidence/autonomy/feasibility/feasibility_<YYYY-MM-DD>.json` (0444, daily, written by `eval_offline`), handed to the policy ruling (ARCH §4.2 Y12). Keys:
- `n_min` (independent station-days) per predicate at α_1 … α_K; the measured replay-sufficient qualifying station-days per day and its source; `sigma_pinned`, `deff_pinned`, their sources and `sigma_source_contaminated`;
- **(r4)** `mde_at_alpha_K` with α_K = α_total·2^−K_LIFETIME (= 0.025/16 at K_LIFETIME 4);
- `n_cap_forward_shadow`, `uptime_floor`, `forward_window_days`, `forward_window_anchor_date`, `bootstrap_b_max`, `k_lifetime`, `min_calibration_buckets`, `calibration_ni_margin`, `calibration_false_fail_rate`;
- `eta_date`, `kill_date` (2027-01-25), `drill_lost_live_days` (from AUT-5's drill accounting, ARCH §5.3 V19), and `promote_eligible_by_eta = (eta_date ≤ kill_date − forward_window_days)` with those lost days counted;
- `live_mde_at_n_max`, `live_power_at_n_max_by_delta`;
- **(r4)** `lineage: {nominations, infeasible_nominations, alpha_spent}` and `per_nominee: [{family_id, nomination_transition_id, k_life, alpha_k, n_min_eff, n_cap, nomination_feasible, window_end, eta_date}]`; `per_screen_candidate: [{family_id, screen_outcome, n, projected_n_min_eff, projected_n_cap, projected_feasible}]` (projections from `compute_nomination_columns` on the same pinned block and counters, descriptive).

**`feasibility_consistency`** FAILs if the block's `stations` differs from the committed root manifest's station count (r5, K1), or if `promote_enabled = true` in the policy block and any of: `promote_eligible_by_eta = false`; any live nominee has `nomination_feasible = false` or `eta_date > window_end`. Test `tests/unit/autonomy/test_feasibility.py::test_consistency_uses_row_columns_and_eta_bound`, `::test_record_reports_mde_at_alpha_K`, `::test_record_reports_live_power_at_n_max`, `::test_eta_bound_counts_drill_lost_days`, **(r5, K2)** `::test_projection_equals_engine_written_columns` (a fixture engine pass writes a nomination row; the record's `per_screen_candidate.projected_*` for that candidate, computed beforehand, equal the row's `n_min_eff`, `n_cap`, `nomination_feasible` exactly, and its `per_nominee` entry equals all five columns), `::test_stations_key_matches_root_manifest`.

### 3.9 Schedule, locks and the ATTEST interaction

| Unit (Type=oneshot) | OnCalendar (UTC) | Lock (`flock -w`, inside ExecStart) | **TimeoutStartSec** | Worst end | Memory |
|---|---|---|---|---|---|
| `breezy-autonomy-eval-offline` | 11:00 | `breezy-studies.lock`, 900 s | **(r5)** 6299 (includes the wait) | **(r5)** 12:45:00 (11:00:00 + 1 s AccuracySec + 6299 s) | **(r4)** `MemoryHigh=12G`, `MemoryMax=14G` (§5.2), in `breezy-studies.slice` |
| `breezy-autonomy-eval-live` | 14:45 | **(r4)** `breezy-studies.lock`, 300 s | 1500 | 15:10:01 | `MemoryHigh=768M`, `MemoryMax=1G`, in `breezy-studies.slice` |

- Both units: `OnFailure=breezy-study-failed@%n`, `ExecStopPost=` run record (§3.11) with `TimeoutStopSec=60`, `EnvironmentFile=-%h/.config/breezy/alerts.env` (G27). Neither sets `RuntimeMaxSec` (G32).
- **Launch window.** Both [start, start + W + TimeoutStartSec + TimeoutStopSec] intervals (11:00:00–12:46:00, 14:45:00–15:11:01) are disjoint from [16:30Z, 17:10Z) and end before the 15:30Z daily engine pass. Neither is a launch-path unit.
- **No offline expiry gap (r5, K5).** Previous verdict valid to 13:00:00 next day; successor lands by 12:45:00, exactly 900 s before. `test_offline_successor_lands_before_predecessor_expiry` asserts `TimeoutStartSec + AccuracySec ≤ 7200 − 900`, i.e. 6299 + 1 = 6300 ≤ 6300; r4's 6300 failed it by 1 s. The assertion is kept, never loosened.
- **eval-live contention.** AUT-2's 14:15Z label run holds the studies flock until ≤ 14:40Z; eval-live waits ≤ 300 s inside its 1500 s bound, so it ends ≤ 15:10Z, 20 min before the engine. If the label run overruns past 14:50Z, eval-live times out on the lock, writes no verdict, and `eval_staleness` FAILs by 15:25Z (fail-closed, alerted).
- Neighbouring slots (other plans): AUT-3 reproducibility rerun ≈ 09:30 (12G, studies flock); AUT-2 labels 14:15; engine 15:30; canary 15:45; post-STOP RECONCILIATION 16:41–16:43; pre-launch 16:45.
- **(r5, K8) Pre-11:00 studies end by 10:45Z.** Every unit that takes the studies flock with an `OnCalendar` before 11:00Z must satisfy `start + AccuracySec + TimeoutStartSec + TimeoutStopSec ≤ 10:45:00Z`, leaving eval-offline's 900 s wait a ≥ 30 min margin (it then holds the lock by 11:00 at the latest in the worst case, well inside the wait the §3.12 budget assumes). Contract test `tests/contract/test_autonomy_units.py::test_pre_offline_studies_units_end_by_1045z` parses every `deploy/systemd/breezy-*.service`/`.timer` pair in `breezy-studies.slice` or naming `breezy-studies.lock`. AUT-3 r3's rerun (09:35Z, 4800 s, worst end ≈ 10:57Z) violates it; AUT-4 requests AUT-3 either start at 09:24:00Z keeping 4800 s (ends 10:45:00 with a 60 s stop) or keep 09:35Z with `TimeoutStartSec` ≤ 4140 s. Widening eval-offline's flock wait was rejected: each extra second comes out of the 3599 s replay budget (§3.12).
- Contract tests: `tests/contract/test_autonomy_units.py::test_units_do_not_contend_on_flock`, `::test_eval_live_starts_after_label_slot_ends`, `::test_consumption_instants_inside_validity`, `::test_aut4_units_outside_launch_window` (with W, TimeoutStartSec and TimeoutStopSec), and the programme deploy test `tests/deploy/test_autonomy_oneshots_never_set_runtime_max_sec.py::test_no_autonomy_oneshot_sets_runtime_max_sec` (fails if any `deploy/systemd/breezy-autonomy-*.service` with `Type=oneshot` sets `RuntimeMaxSec`; complements ARCH `test_oneshot_units_use_timeout_start_sec_not_runtime_max_sec`).

**(r4) ATTEST (ARCH C5 ATTEST row, P4-7, W1).**
- ATTEST cites only intraday `HEALTH` and `RECONCILIATION` verdicts listed in `attest_required_detectors`; a daily 26 h AUT-4 verdict is never citable.
- AUT-4 supplies `health.eval_staleness(fold, verdict_store, now_ns)`; the AUT-6 intraday producer evaluates it and writes an intraday `HEALTH` verdict (detector `eval_staleness`) with `ATTEST_VERDICT_VALIDITY_H` (≤ 8 h) validity. AUT-4 drafts, for the AUT-5 policy, that `(HEALTH, eval_staleness)` is a member of `attest_required_detectors`; once it is, a dead evaluator withholds ATTEST and the node's `registry_attest_expired` veto stops entries.
- **Freshness.** A producer's newest verdict is fresh only if unexpired **and** outcome ≠ `ERROR`. `eval_staleness` FAILs if any CHAMPION or HALTED family lacks a fresh LIVE_SEQUENTIAL verdict after 15:25Z (14:45 + 1500 s + 15 min), or if any AUT-4 producer's newest verdict is not fresh.
- **(r5, K4) Today's slot.** At and after 15:25Z, `eval_staleness` also FAILs unless, for every producer in the policy key `eval_staleness_producers` (drafted `[eval_live]` until the eval-offline timer is enabled, then `[eval_live, eval_offline]`, amended in the enabling commit), the newest verdict's `slot_start_ns` falls on **today's UTC date**. An unexpired verdict from yesterday's slot (eval-offline's is valid to 13:00) therefore no longer passes at 15:25Z. "Newest" = max `slot_start_ns`, then max `produced_at_ns`. Before 15:25Z only the unexpired-and-not-ERROR rule applies. Tests `tests/unit/autonomy/test_health.py::test_staleness_fails_when_newest_slot_not_today`, `::test_staleness_producer_set_from_policy_key`.
- **(r5, K4) Engine consumption, AUT-5 request.** The engine acts only on the newest verdict per (subject family, kind) (per (subject family, kind, detector) for HEALTH), ordered as above. Older live verdicts it reads are journaled with their computed `acceptance` and `acted=false`; no new `reject_reason` is added to ARCH's closed set. Contract test `tests/contract/test_engine_input_journal_contract.py::test_engine_acts_on_newest_verdict_per_family_kind`.
- **Invariant (ARCH §4.5):** `ATTEST_PERIOD_H + L_max + ATTEST_MARGIN_H ≤ ATTEST_VERDICT_VALIDITY_H`, L_max = 60 min + 150 s = 1.04 h: 6 + 1.04 + 0.5 = 7.54 ≤ 8. Test `tests/unit/autonomy/test_health.py::test_attest_cadence_has_no_expiry_gap_with_eval_staleness`.

### 3.10 Ruling drafts (NOT decided; for the AUT-5 policy ruling and its peer review)

**Holdout.** No AUT-4 text; ARCH C4.1 is consumed by name.

**R-B `PREREG_FQ_v1` (the FQ boundary ruling, P4-2).** Text unchanged from r3 §3.10 R-B (LD-OBF, one-sided α = 0.025, a look every 10 combined station-days, n_max and loss stop derived in the committed design JSON from FQ take counts, data-free σ₀ = 0.5 and tape asks; D0′ prefix exclusion; `scripts/analysis/prereg_precommit_check.py` disclosure; the boundary from the moved `group_sequential_boundaries`, validated by a seeded H0 MC that replays the live look loop verbatim). **(r4)** Its sha is the value of `family_prereg_sha256` on every FQ LIVE_SEQUENTIAL verdict; "KILL (including the loss stop) → FAIL → DEMOTE (entry-only)" applies with or without the policy ruling (§3.6). Draft to the peer loop by ARCH's ≈ 2026-11-10; filing target 2026-10-24. The r3 disclosure limit (existence, not reads) stands.

**R-C, calibration non-inferiority (relative; r4 conformed to ARCH C4 (c), P4-15, V16, P4-6).**
> "On the verdict's own station-days, with the reliability bins of `forecast_conditional_scoring.py:303` (moved to `src/breezy/analysis/stats/scoring_core.py`), a bucket is **paired** when candidate and champion each hold ≥ 30 events in it. Statistic: ΔECE = ECE_cand − ECE_champ over paired buckets (n-weighted mean |obs − pred|). The conjunct holds iff the one-sided (1 − α_k) upper bound of ΔECE, from a paired date-cluster bootstrap (dates resampled jointly for both models; seed `derive_seed(subject, slot_date, "fs_c_calibration_bootstrap")` (§3.1, r5 K7); B per §3.2), is < `CALIBRATION_NI_MARGIN` (proposed 0.01).
> Fewer than `MIN_CALIBRATION_BUCKETS` paired buckets → `INCONCLUSIVE(calibration_buckets_below_min)`. `MIN_CALIBRATION_BUCKETS` is a `pins.py` floor (≥ 1) set from AUT-4's measured false-fail rate; the policy may only raise it (proposed policy value 3).
> `n_min_c` is the smallest n at which, under the out-of-fold archive differences, P(≥ `MIN_CALIBRATION_BUCKETS` paired buckets) ≥ 0.95 and the test's power at true ΔECE = `CALIBRATION_NI_MARGIN` − `mde_c` (proposed `mde_c` = the margin, i.e. true ΔECE = 0) is ≥ 0.80, computed by WP0 at α_1…α_K_LIFETIME and **pinned in the policy block as the table `n_min_c`** (r5, K1); it enters `n_min_eff`.
> The mean signed deviation difference (`metrics.msd_diff`) and the absolute leg (`evaluate_calibration_leg`, ε = 0.05) are reported and never gated."
>
> **Measured false-fail rate (P4-6).** WP0 runs the test with candidate = champion-equivalent perturbations (seeded resamples of the champion's own out-of-fold predictions on archive days before 2026-07-01) and reports the rejection rate at each candidate α; the margin and `MIN_CALIBRATION_BUCKETS` proposal must give a false-fail rate ≤ 0.20 at α_1, or the draft returns to review.

r3's second |MSD| leg (δ_M) is withdrawn: ARCH names one paired test and one margin.

**R-D, α and nominations (r4: ARCH C4 and the amended ALPHA decision adopted).**
> "α_total = 0.025 one-sided, charged **per feasible nomination** (SHADOW→CHALLENGER PROMOTE), lifetime-geometrically per lineage: α_k = α_total·2^−k_life; `k_life` counts α-charging nominations and never resets.
> K_LIFETIME = 4 (the `pins.py` ceiling `MAX_NOMINATIONS_PER_LINEAGE_LIFETIME` ≤ 4); `MAX_NOMINATIONS_PER_FORWARD_WINDOW` = 1. A nomination with `n_min_eff > n_cap` is infeasible: `alpha_k = 0`, no K_LIFETIME charge, the window slot used.
> Screening (OFFLINE_CHALLENGER) spends no α: `SCREEN_MIN_STATION_DAYS` = 28, `X_SCREEN` = 0.0152 (Brier), PASS also requires the pinned-bootstrap 95% upper bound of Δbrier < 0.
> Nominee selection when several SHADOW candidates hold an accepted PASS: the largest screen improvement, ties by MINT `seq`.
> `forward_window_days` = 28 (pins 28–120), `forward_window_anchor_date` = 2026-10-02; `uptime_floor` = 0.8; `alpha_total` = 0.025; `stations` = the committed root manifest's count at filing (4 today); `sigma_pinned`, `sigma_b_pinned`, `deff_pinned`, `mde_a`, `mde_b` (proposed = X_EV, 0.02 per contract), `mde_c` and the `n_min_c` table from the §3.8 record at filing; `BOOTSTRAP_B_MAX` = 2¹⁹ (within the pins literal); `eval_staleness_producers` per §3.9.
> X_EV = 0.02 per contract; `EXCLUDED_FRACTION_MAX` = 0.25; `N_PROXY_MIN` = 30; `N_IOC_MIN` = 30; `MIN_CALIBRATION_BUCKETS` = 3; `CALIBRATION_NI_MARGIN` = 0.01.
> CHALLENGER→CHAMPION PROMOTE requires accepted OFFLINE_CHALLENGER **and** FORWARD_SHADOW PASS and `promote_enabled` (ARCH C5)."

**R-E, slippage.** As r3, with the last clause replaced: "`ACCEPT_FILL_SELECTION_SENSITIVE` = [true | false]" (a policy key read by the producer, §3.7).

**R-F, feasibility.**
> "The §3.8 record at filing. With today's σ, X and window, every nomination is infeasible (n_min_eff ≥ 403 > n_cap 89), so every FORWARD_SHADOW is INCONCLUSIVE(window_cap_below_n_min) by construction, no α is spent, and `promote_enabled=false` (`eta_date` > KILL − `forward_window_days`; AUT-5 feasibility ETA 2027-05-06). PROMOTE is machinery-proven by the drill only. Evidence class: machinery proven, edge unproven."

**R-G, CHALLENGER admission.** As r2/r3.

**Detector → action class (draft for the policy map).** `offline_challenger`, `forward_shadow` → `NONE` (inputs to PROMOTE only); `live_sequential` → `DEMOTE` (`RECOVERABLE_MODEL`); `eval_completeness`, `feasibility_consistency`, `eval_excluded_fraction`, `eval_n_stalled`, `eval_resource_creep`, `eval_replay_path` → `ALERT`; `eval_staleness` → ATTEST-required (intraday HEALTH).

### 3.11 Evaluator self-monitoring

| Detector | Producer | FAIL condition | Proposed class |
|---|---|---|---|
| `eval_completeness` | each unit | a fold family or SHADOW/nominee lacks today's verdict of a required kind; **(r5, K6)** expected sets: OFFLINE_CHALLENGER = one per SHADOW candidate and drill child, or exactly one NO_INPUT on the champion when there are none; FORWARD_SHADOW = one per open-window nominee, **zero** when there is none (a FORWARD_SHADOW for a non-nominee, or a NO_INPUT FORWARD_SHADOW, FAILs); LIVE_SEQUENTIAL = one per CHAMPION/HALTED family; or `replay_backlog_days > 3 × MAX_BACKLOG_DAYS_PER_RUN` | ALERT |
| `eval_excluded_fraction` | eval_offline | as r2 | ALERT |
| `eval_n_stalled` | eval_live | as r2 | ALERT |
| `eval_resource_creep` | each unit | wall > 0.8 × TimeoutStartSec, or peak > 0.8 × `MemoryHigh` (cgroup) or > 0.8 × child share, on 2 of the last 3 runs; a killed run (`_stoppost.json` with `service_result ≠ success`) counts | ALERT |
| **(r4)** `eval_replay_path` | eval_offline | the champion's daily replay→admission→scoring path produced no admitted station-day for 3 consecutive tape days that the census marks replayable, or a parity failure | ALERT |
| `eval_staleness` | AUT-6 intraday producer | §3.9 | ATTEST-required |

**Run-record store** (unchanged from r3): `$STATE/derived/autonomy/eval_runs/<producer_id>/<YYYY-MM-DD>_<unit_start_ns>.json` plus `<…>_stoppost.json` (`$SERVICE_RESULT`, `$EXIT_STATUS`, cgroup `memory.peak`); 0444, one writer per file.

### 3.12 Memory and runtime budget

**(r4) Memory (ARCH §5.2, 14G).**
- `MemoryHigh=12G`, `MemoryMax=14G` on eval-offline; internal budget parent 2G + max(screen 4G, P·S) ≤ 12G, with S = ⌈1.25·R⌉ (WP0 per-child peak); P = 2 if S ≤ 5G, P = 1 if S ≤ 10G; hard fail above.
- The unit's measured peak is recorded before its timer is enabled (ARCH §5.2). A peak reaching `MemoryHigh` means a named raised cap (≤ 16G) in a slot outside [16:30Z, 01:15Z) shared with no other heavy unit, through review, or the WP returns to review. Never 01:00–04:30Z.
- **Enablement gate:** eval-offline is a > 4G study, so its timer is enabled only after AUT-6's daily memory-sum HEALTH verdict PASSes (the quote-tape-ingest 12G/14G drop-in currently FAILs it by name; ARCH §5.2).

**(r4) Per-run replay budget.**
- `deadline = unit_start + EVAL_OFFLINE_TIMEOUT_START_S − SAFETY_S` (pattern of `deploy/systemd/replay-daily-run.sh:48-50`).
- Replay wall budget at the worst wait (**r5, K5**): 6299 − 900 (flock) − 900 (screen) − 600 (scoring) − 300 (safety) = **3599 s**.
- **`FS_REPLAY_CHILD_TIMEOUT_S = ⌊P × 3599 / (4·(MAX_NOMINATIONS_PER_FORWARD_WINDOW + 1))⌋`** = ⌊P × 3599 / 8⌋: **899 s at P = 2, 449 s at P = 1** (r5; r4 900/450). 4 is the station count; the open-window nominee (≤ 1 per lineage by ARCH) plus the champion's `eval_replay_path` replay. With more than one live lineage the denominator is 4·Σ(1 + 1), re-derived in the same reviewed commit. Test `tests/unit/autonomy/test_budget.py::test_child_timeout_derived_from_budget` recomputes it from the literals and `pins.MAX_NOMINATIONS_PER_FORWARD_WINDOW`.
- Launch rule, order (today first: champion, then the nominee; then backlog ≤ 3 days), atomic per-output partial commit, `BACKLOG_EXPIRED`, and the WP0 hard-fail rule (`t_p95 ≤ 0.8 × FS_REPLAY_CHILD_TIMEOUT_S`, i.e. ≤ 719 s at P = 2, ≤ 359 s at P = 1) as r3.
- Tests: `tests/unit/autonomy/test_memory_budget.py::test_replay_budget_partial_commit_resumes_backlog`, `::test_no_child_launched_past_deadline`, `::test_backlog_expired_past_window_end`.

### 3.13 Engine input journal (AUT-4 owns the schema; AUT-5 writes it)

**(r4) Conformed to ARCH C5 (P4-9).**
- Path: `$STATE/evidence/engine_inputs/<venue>/<YYYY-MM-DD>/<mode>_<ts_ns>.jsonl` (write-once, 0444, one file per pass, single-read rule).
- Schema `engine_input/v1`, exact-set, one row per verdict read: `pass_id`, `pass_mode`, `verdict_id`, `kind`, `subject_family_id`, `detector`, `acceptance`, `reject_reason` (closed: `expired`, `unpinned_producer`, `sha_mismatch`, `no_ruling`, `action_class_mismatch`, `subject_unbound`, `k_exceeded`, `input_unresolved`), `acted`, `transition_id`.
- Contract tests (AUT-4, in `tests/contract/test_engine_input_journal_contract.py`): `::test_schema_exact_set_and_closed_reject_reasons`, `::test_every_live_verdict_journaled_once_per_daily_pass` and `::test_cause_verdict_ids_subset_of_acted_rows` (the ARCH names), `::test_no_widening_row_without_journal`, `::test_fixture_journal_never_under_production_state_root`.
- The fixture path (§6.1) journals under its own state root `/home/jon/.local/share/breezy-autonomy-fixture/evidence/engine_inputs/fixture/<date>/`.

---

## 4. Work packages

**Gate commands for every WP** (run by the coordinator, never trusted from an agent): interpreter `PYTHONPATH=<tree>/src /home/jon/breezy/.venv/bin/python`; `scripts/ci/run_tests_no_egress.sh`, the full gate after every merge (L-43), launched with `-p LimitNOFILE=524288` and basetemp on `~/.cache`; `cd <tree> && lint-imports` printing "N kept, 0 broken"; the mypy ratchet. Never `uv`/`pip` (L-51), never `git stash`. Activation is immediate on merge unless a technical reason is stated.

**WP0: measurements (read-only).** r3 items (i)–(x), plus **(r4)**: (xi) σ and ρ̂ for the policy block's pinned values (archive before 2026-07-01, out-of-fold); (xii) the R-C false-fail rate at α_1…α_4 and the paired-bucket occupancy that fixes `MIN_CALIBRATION_BUCKETS`; (xiii) eval-offline per-child peak R and t_p95 against the **899/449 s** timeouts (r5); **(r5)** (xiv) `sigma_b_pinned` (sd of per-take `ev_cond`) and the `n_min_c` table at α_1…α_4 for the block (K1). GREEN: every number sourced; the §3.12 hard-fail rules evaluated; the R-C false-fail bound met or the draft returned.

**WP1 (= ARCH AUT-4a, Wave 1): the G36 move.** Functions moved byte-identically into `src/breezy/analysis/stats/` (§3.3); scripts kept as thin CLI wrappers; characterisation-pinned (L-33) with mutation evidence. RED first: `tests/unit/analysis/stats/test_moved_source_pinned.py::test_moved_functions_byte_identical`, `::test_script_wrappers_delegate`; the existing `tests/unit/test_aud07_live_rule_crossing_sim.py`, `tests/unit/test_nbp_shadow_parity_live.py` and the family-tally golden stay byte-unchanged and green.

**WP2: pure evaluation core.** Files: `eval_stats.py`, `permutation.py`, `calibration_ni.py`, `metric_registry.py`, `windows.py`, `leakage.py`, `budget.py`, **(r5)** `seeding.py`, `src/breezy/persistence/autonomy/sample_size.py` (ARCH-0 owner review). RED first (r4 names): `tests/unit/autonomy/test_permutation.py::test_b_capped_and_tail_beyond_cap`, `::test_b_max_covers_k_lifetime_over_three`; `tests/unit/autonomy/test_calibration_ni.py::test_relative_calibration_one_sided_with_margin`, `::test_fewer_than_min_calibration_buckets_inconclusive`, `::test_n_min_c_enters_n_min_eff`, `::test_false_fail_rate_reported`; `tests/unit/autonomy/test_eval_stats.py::test_power_at_n_reported`; `tests/unit/autonomy/test_verdict_identity.py::test_recompute_same_slot_same_inputs_same_verdict_id`; `tests/unit/autonomy/test_verdict_schema.py::test_assumptions_closed_five_tags`, `::test_two_ruling_sha_fields_per_kind`; `tests/unit/autonomy/test_verdict_validity.py::test_offline_successor_lands_before_predecessor_expiry`; `tests/unit/autonomy/test_budget.py::test_child_timeout_derived_from_budget`; **(r5)** `tests/unit/autonomy/test_eval_stats.py::test_sample_size_primitives_single_definition`; `tests/unit/autonomy/test_seeding.py::test_seed_differs_by_subject_slot_and_role`, `::test_role_is_closed_literal`; `tests/unit/autonomy/test_verdict_schema.py::test_decimal_fields_canonical_string`.

**WP3: FQ tape admission and oversize quarantine.** As r3, plus `tests/unit/autonomy/test_tape_admission.py::test_frozen_holdout_day_refused`.

**WP4: LIVE_SEQUENTIAL and the `eval-live` unit** (Wave 2). Unit per §3.9 (studies flock, `TimeoutStartSec=1500`). RED first: the §3.6 tests. Activation: enable the timer on merge (≤ 1G, below the 4G enablement threshold).

**WP5: OFFLINE_CHALLENGER screening and the nomination columns** (Wave 3). Files: `src/breezy/analysis/autonomy/producers/eval_offline.py` (screen part), `src/breezy/persistence/autonomy/nomination.py` (with ARCH-0 review). RED first: the §3.5 tests, plus `tests/unit/autonomy/test_offline_challenger.py::test_screen_charges_no_alpha`, `::test_screen_never_reads_frozen_holdout_or_post_nomination_days`, `::test_drill_child_screen_not_distinct_with_drill_tag`, `::test_screen_fields_k_life_null`, **(r5)** `::test_no_input_is_offline_challenger_on_champion`; `tests/contract/test_nomination_columns_contract.py::*` (§3.5, K3; GREEN needs the AUT-5 engine write path, so it merges with or after AUT-5a); `tests/unit/autonomy/test_seeding.py::test_same_slot_recompute_bit_identical`.

**WP6: FORWARD_SHADOW, the `fs_replay` children and the `eval-offline` unit** (Wave 3). Unit per §3.9/§3.12. RED first: the §3.7 tests (incl. **(r5)** `::test_no_nominee_writes_no_forward_shadow`, `::test_look_waits_for_n_ioc_min_inside_window`, `::test_window_end_before_n_ioc_min_is_fill_rate_underpowered_final`); **(r5)** `tests/contract/test_autonomy_units.py::test_pre_offline_studies_units_end_by_1045z` (GREEN needs the AUT-3 rerun change, §3.9); `tests/unit/autonomy/test_memory_budget.py::*` (§3.12); `tests/unit/autonomy/test_pins.py::test_aut4_producer_ids_registered_in_pins`; existing `test_execution_egress_firewall_guard`, unchanged. **Activation (technical reason stated):** the timer is enabled only after (1) the measured peak is recorded and is below `MemoryHigh`, and (2) AUT-6's memory-sum HEALTH PASSes (ARCH §5.2: no autonomy study above 4G until the sum passes).

**WP7a: R-B design commit, H0 MC and precommit check** (starts now; docs, evidence, a read-only script). As r3 (`scripts/analysis/prereg_precommit_check.py` with RED tests `tests/unit/test_prereg_precommit_check.py::test_undisclosed_pre_commit_pnl_artefact_fails`, `::test_post_commit_artefact_ignored`, `::test_disclosed_artefact_passes`; design JSON `docs/evidence/PREREG_FQ_v1_design_<date>.json`; boundary + H0 MC as a capped unit run under `TimeoutStartSec`, outside 01:00–04:30Z and outside [16:30Z, 17:10Z)). Peer loop by ≈ 2026-11-10.

**WP7b: feasibility.** RED first: the §3.8 tests, including **(r5)** `::test_projection_equals_engine_written_columns` and `::test_stations_key_matches_root_manifest`.

**WP8: self-monitoring and the journal contract.** RED first: `tests/unit/autonomy/test_health.py::test_error_verdict_is_not_fresh`, `::test_resource_creep_counts_killed_run_from_stoppost_record`, `::test_backlog_growth_fails_completeness`, `::test_eval_replay_path_fails_on_three_dark_replayable_days`, `::test_attest_cadence_has_no_expiry_gap_with_eval_staleness`, **(r5)** `::test_staleness_fails_when_newest_slot_not_today`, `::test_staleness_producer_set_from_policy_key`, `::test_completeness_no_nominee_expects_zero_forward_shadow`, `::test_completeness_fails_on_forward_shadow_for_non_nominee`; `tests/unit/autonomy/test_run_record.py::test_stoppost_writes_service_result_and_memory_peak`; the §3.13 contract tests plus **(r5)** `::test_engine_acts_on_newest_verdict_per_family_kind`; `tests/deploy/test_autonomy_oneshots_never_set_runtime_max_sec.py::test_no_autonomy_oneshot_sets_runtime_max_sec`.

**WP9: live-proof run** (§6). No code.

**Producer-pin rotation runbook.** Append-only per §4.3 (Z9); an `fs_replay` rotation triggers `PENDING_RECLOSURE` re-replay through the §3.12 backlog.

---

## 5. Association

| Contract | From → AUT-4 | AUT-4 → |
|---|---|---|
| C1 | AUT-1: Take/TrySubmit, `forecast_input_sha256`, `depth_ref`/`quote_ref`, `LifecycleEvent` | — |
| C2 | AUT-2: admissible rows (`p_source=c1_decision`), `slippage`, `realized_pnl`; label slot ends ≤ 14:40Z | — |
| C3 | AUT-3: lineage windows; ≤ 1 MINT per lineage per day; `refit_run/v1` outcomes | **(r5, K8) request:** the reproducibility-rerun unit ends ≤ 10:45:00Z (start 09:24Z with 4800 s, or 09:35Z with `TimeoutStartSec` ≤ 4140 s); AUT-4 owns `test_pre_offline_studies_units_end_by_1045z` |
| C4 | — | AUT-5 engine (every kind; FORWARD_SHADOW with `k_life`, `alpha_k`, `n_min_eff`, `n_cap`; two ruling-sha fields); AUT-7 via accepted LIVE FAIL |
| C4.1 | ARCH-0 (filed in Wave 0) | consumed by name |
| C5 | AUT-5: fold, nomination row columns, `lineage_counters`, bound sha, registry export | **(r4)** `compute_nomination_columns`. **(r5, K3) request:** the engine calls it inside the PROMOTE's `BEGIN IMMEDIATE` transaction with the §3.5 named keys and writes the five columns only from its return; AUT-4 owns `tests/contract/test_nomination_columns_contract.py`. **(r5, K4) request:** the engine acts only on the newest verdict per (family, kind) (§3.9) |
| C6 | ARCH-0 Protocols | `FqEvaluator`; `eval_staleness` → AUT-6 |
| Engine input journal | AUT-5 writes it | AUT-4 owns schema and contract tests |
| Policy block | AUT-5 files it | AUT-4 drafts R-B…R-G and keys `SCREEN_MIN_STATION_DAYS`, `X_SCREEN`, `forward_window_days`, `forward_window_anchor_date`, `uptime_floor`, `sigma_pinned`, `deff_pinned`, **(r5, K1, pinned block values feeding `compute_nomination_columns`)** `alpha_total`, `stations`, `sigma_b_pinned`, `mde_a`, `mde_b`, `mde_c`, `n_min_c` (table k = 1…K_LIFETIME), **(r5, K4)** `eval_staleness_producers`, `X_EV`, `EXCLUDED_FRACTION_MAX`, `N_PROXY_MIN`, `N_IOC_MIN`, `MIN_CALIBRATION_BUCKETS`, `CALIBRATION_NI_MARGIN`, `ACCEPT_FILL_SELECTION_SENSITIVE`, the detector map, the `attest_required_detectors` entry for `eval_staleness` |
| `pins.py` | ARCH-0: `MAX_NOMINATIONS_PER_LINEAGE_LIFETIME`, `MAX_NOMINATIONS_PER_FORWARD_WINDOW`, `BOOTSTRAP_B_MAX`, `MIN_CALIBRATION_BUCKETS`, `DEFAULT_RESTRICTIVE_CLASS`, `MAX_VERDICT_VALIDITY_H` | AUT-4 registers producer ids `eval_live`, `eval_offline`, `fs_replay`; requests `DEFAULT_RESTRICTIVE_CLASS["live_sequential"] = DEMOTE`; proposes `BOOTSTRAP_B_MAX = 2¹⁹` |
| Memory | AUT-6 memory-sum HEALTH | eval-offline enabled only after it PASSes |
| Drill child | AUT-7 | OFFLINE screen verdicts tagged `drill` (§6.1 path 2) |
| Fixture engine pass | **AUT-5** (request): an engine pass runnable against the fixture state root | path 3 of §6.1 |

**Order.**
- **Now, in parallel:** WP0, WP7a.
- **Wave 1 (after ARCH-0):** WP1 (AUT-4a), then WP2 and WP3.
- **Wave 2 (after AUT-2a):** WP4.
- **Wave 3 (after AUT-3 + AUT-5a):** WP5, WP6; then WP7b (after WP0 + WP6).
- **After AUT-6's intraday producer + AUT-5's journal writer:** WP8.

---

## 6. Live-proof protocol

### 6.1 Artefact

`docs/evidence/AUT4_LIVE_PROOF_<start>_<end>.md`, produced by a read-only script run by an agent that did not build AUT-4, over 7 consecutive qualifying days (≥ 1 real fill per day, ≥ 5 real fills in the window). Per day:
- LIVE_SEQUENTIAL per fold family (never `no_registered_boundary`), with both ruling shas;
- OFFLINE_CHALLENGER per SHADOW candidate (outcome, n, screen metrics);
- FORWARD_SHADOW per nominee with its four fields and `nomination_feasible` (from the row);
- consumption: every verdict id in `$STATE/evidence/engine_inputs/<venue>/<date>/daily_<ts_ns>.jsonl` with its `acceptance`/`reject_reason`;
- `eval_completeness` and `eval_replay_path` PASS, the `eval_staleness` intraday HEALTH verdicts cited in the ATTEST rows, timer-only runs, and `producer_code_sha` values in `pins.py`.

**Candidate coverage.** At least 3 of the 7 days carry ≥ 1 candidate verdict from one of:
1. **Real AUT-3 candidates:** OFFLINE screen verdicts, plus FORWARD_SHADOW for any nominee.
2. **The AUT-7 drill child** while SHADOW or CHALLENGER on the real venue: its OFFLINE `INCONCLUSIVE(NOT_DISTINCT)` (tagged `drill`), journaled by the real engine pass.
3. **The fixture-candidate path (r4: isolated by state root):** the same pinned `eval_offline` closure runs against `/home/jon/.local/share/breezy-autonomy-fixture/` (its own registry, verdict, journal and evidence trees), holding a deterministic recalibration child of the champion artefact, on real archive and tape days; AUT-5's engine runs a pass against that root. Verdicts carry `metrics.fixture_candidate = true`, never enter the production state root, and exercise screen → nomination row (feasible or not) → FORWARD_SHADOW → journal end to end.

A day with no candidate verdict is otherwise acceptable only if AUT-3's `refit_run/v1` record names `NO_CHANGE(below_delta)`, `NOT_FITTABLE(reason)` or `MINT_REFUSED_CEILING`.

**Score if AUT-3 nominates no real candidate.** Target stays 3, reached through path 2 or 3; the DONE claim states "machinery proven (drill/fixture candidate path), edge unproven; no real AUT-3 candidate was evaluated in the window".

### 6.2 Drills

As r3: SIGKILL `eval_offline` → `OnFailure` CRITICAL `delivered=true`; `eval_staleness` FAIL; ATTEST withheld; recovery; `_stoppost.json` with `service_result=signal`. Oversize tape day. Unpinned producer. Forced `TimeoutStartSec` overrun in a test unit (partial commit, backlog resumed). **(r4)** Added: a fixture nomination with `n_min_eff > n_cap` in the fixture root, showing `nomination_feasible=false`, `alpha_k=0`, `infeasible_nominations` +1 and daily `INCONCLUSIVE(window_cap_below_n_min)`.

### 6.3 Accrual, power and pre-KILL probability

**Measured inputs (2026-10-03),** as r3: FQ IOC fill rate 12/14 = 0.857 (Wilson 95% [0.601, 0.960]); 3.5 station-days with a take per climate day (n = 2 days); σ(fc − mkt) = 0.099 (contaminated window, disclosed); deff assumed 1.5 until WP0; accrual cap 4 station-days a day.

| Verdict | n_min_eff | n_cap | Outcome before the KILL |
|---|---|---|---|
| FORWARD_SHADOW (a), first nomination (α_1) | 605 at deff 1.5 (403 at deff 1) | ⌊4 × 28 × 0.8⌋ = 89 (≤ 480 at 120 days, floor 1.0) | **infeasible**: `alpha_k = 0`, `k_life` stays 0, `INCONCLUSIVE(window_cap_below_n_min)` |
| Any later nomination | ≥ the above (α never deepens while infeasible) | 89 | the same |
| OFFLINE_CHALLENGER screen | `SCREEN_MIN_STATION_DAYS` = 28 (no α) | not capped | PASS/FAIL in ≈ 7 forward days per candidate; a recalibration child (gain ≈ 0.006) is expected to FAIL `X_SCREEN` = 0.0152 |
| LIVE_SEQUENTIAL FQ under R-B | first look 10; n_max per WP7a (r2 value 160) | not windowed | see below |

**Reach probability of n_max = 160** (r2 seeded simulation, seed 20261003, 4000 runs): D0′ 2026-10-25: 0.34 / 0.73 / 0.89 / 0.96 at u = 0.5 / 0.6 / 0.7 / 0.8; D0′ 2026-11-10: 0.05 / 0.33 / 0.67 / 0.86.

**Power at n = 160** (normal approximation, σ₀ = 0.5, one-sided 0.025, LD-OBF final ≈ 2.02): δ = 0.05 / 0.10 / 0.113 / 0.15 → ≈ 0.22 / 0.69 / 0.80 / 0.96. The unconditional SURVIVE probability at δ = 0.10, D0′ 10-25, u = 0.7 is ≈ 0.61. WP7a replaces these with MC values.

**Consequences.** `promote_enabled=false`; PROMOTE is machinery-proven by the AUT-7b drill only; filing R-B early is the only lever for a decisive live verdict; **(r4)** no α is spent and K_LIFETIME is not consumed while every nomination is infeasible, so the lineage keeps its full budget for the day σ or X changes.

### 6.4 Hard prerequisites and ETA

| # | Prerequisite | Owner | Target | Interim behaviour |
|---|---|---|---|---|
| 1 | C4.1 `RULING_holdout_freeze_and_forward_window_2026-10-03` filed (Wave 0) | ARCH-0 | Wave 0 | `INCONCLUSIVE(SEALED_WINDOW)` |
| 2 | R-B `PREREG_FQ_v1` filed; design JSON and boundary committed; precommit check exits 0 | WP7a + peer loop | file 2026-10-24; peer loop ≤ 2026-11-10 | `INCONCLUSIVE(no_registered_boundary)` |
| 3 | AUT-5 policy ruling filed (block with the §5 keys) | AUT-5 | — | OFFLINE/FS rejected `no_ruling`; LIVE FAIL still DEMOTEs via `DEFAULT_RESTRICTIVE_CLASS` |
| 4 | **(r4)** ARCH-0 Wave 0 surfaces shipped: `verdict/v1` (identity without `produced_at_ns`, two ruling-sha fields, five-tag enum, FS fields), C5 nomination columns and counters, `pins.py` ceilings incl. `DEFAULT_RESTRICTIVE_CLASS["live_sequential"]`, `nomination.py` reviewed | ARCH-0 (+ AUT-4 WP5 for `nomination.py`) | Wave 0 / Wave 3 | WP4–WP6 cannot merge (their RED tests import these types) |
| 5 | **(r4)** AUT-5 engine writes `engine_input/v1` and calls `compute_nomination_columns`; a fixture-root engine pass | AUT-5 | Wave 3 | no consumption evidence; the proof window does not open |
| 6 | **(r4)** AUT-6 intraday producer runs `eval_staleness`; policy lists it in `attest_required_detectors` | AUT-6 / AUT-5 | Wave 1 / filing | dead-evaluator veto not live; `eval_staleness` still alerts |
| 7 | **(r4)** AUT-6 memory-sum HEALTH PASS | AUT-6 (+ ING-2 S3a) | — | eval-offline timer not enabled (ARCH §5.2) |
| 8 | WP4–WP6 and WP8 merged and active | AUT-4 | — | — |
| 9 | **(r5)** AUT-3 reproducibility rerun ends ≤ 10:45Z (K8); AUT-5 accepts the K3/K4 requests | AUT-3 / AUT-5 | Wave 3 | WP6 (unit contract test) and WP5 (nomination contract test) stay RED and do not merge |

**ETA.** Earliest 2026-11-23; planning date 2026-11-30; latest acceptable 2026-12-31. If R-B is not filed by 2026-12-01, score 2 is declared in PROGRESS. If prerequisite 7 has not passed by 2026-12-15, PROGRESS records "AUT-4 forward-shadow blocked on the memory sum" and the proof window does not open. **Evidence class: machinery proven, edge unproven.**

---

## 7. Score-3 verification checklist (independent scorer)

| Criterion | Check |
|---|---|
| (a) unattended | `systemctl --user list-timers 'breezy-autonomy-eval-*'`; `journalctl --user -u breezy-autonomy-eval-live.service -u breezy-autonomy-eval-offline.service --since <start>` shows timer-triggered runs only; `ls $STATE/derived/autonomy/eval_runs/*/` shows one producer record and one `_stoppost.json` per run |
| (b) family-agnostic | `test_families_enumerated_from_fold_not_list`, `test_refusing_plugin_family_gets_error`, ARCH `test_family_plugin_exact_set`; one LIVE_SEQUENTIAL per fold family per day |
| (c) fails closed | tests **(r5)** `test_staleness_fails_when_newest_slot_not_today`, `test_same_slot_recompute_bit_identical`, `test_promote_row_columns_written_only_via_compute_nomination_columns`, `test_underpowered_verdict_carries_no_effect_estimate`, `test_forecast_vintage_after_eval_ns_is_leakage_error`, `test_fewer_than_n_proxy_min_fills_inconclusive`, `test_fewer_than_n_ioc_min_inconclusive`, `test_window_cap_below_n_min_is_inconclusive_by_construction`, `test_infeasible_nomination_charges_no_alpha`, `test_k_life_mismatch_is_error_k_exceeded`, `test_error_verdict_is_not_fresh`. Store queries over `$STATE/derived/verdicts/*/*/*.json`, each returning nothing: (1) `jq 'select(.n_min != null and (.outcome=="PASS" or .outcome=="FAIL") and .n < .n_min and .metrics.stop_reason != "loss_stop")'`; (2) `jq 'select(.kind=="LIVE_SEQUENTIAL" and .outcome=="PASS" and .n < .metrics.n_max)'`; (3) `jq 'select(.kind=="FORWARD_SHADOW" and .outcome=="PASS" and (.n_min_eff > .n_cap or (.alpha_k | tonumber) == 0))'` (**r5, K9:** `alpha_k` is a canonical string-decimal, §3.1; `tonumber` makes the query independent of its exact spelling); (4) `jq 'select(.kind=="OFFLINE_CHALLENGER" and .k_life != null)'` |
| (d) detected and delivered | the §6.2 SIGKILL drill: `$STATE/evidence/alerts/<date>/*_d.json` with `delivered=true`; the `eval_staleness` FAIL; no ATTEST row in that window; the `_stoppost.json` record |
| (e) RED→GREEN | RED and GREEN output per §4 test; the gate exits 0 at each merge sha; `lint-imports` "N kept, 0 broken"; WP1 mutation evidence |
| (f) live proof | the §6.1 file; every verdict id present once in that day's daily journal; candidate coverage ≥ 3/7 days with the path named; journal contract tests green |
| Nomination accounting | the registry export rows for each SHADOW→CHALLENGER PROMOTE carry all five columns; `lineage_counters.nominations` equals max `k_life`; `Decimal(alpha_spent) == Decimal("0.025")·(1 − 2^−nominations)` exactly, with `alpha_spent` read as the canonical string (§3.1) |
| Prerequisites | §6.4 rows: ruling files dated before `<start>`; `prereg_precommit_check.py` exit 0; ARCH-0 types at the cited merge shas; AUT-6 memory-sum PASS verdict id |
| Feasibility | daily record with `mde_at_alpha_K`, `n_cap`, `nomination_feasible`, `live_power_at_n_max_by_delta`; `feasibility_consistency` PASS |
| Schedule | `test_units_do_not_contend_on_flock`, `test_aut4_units_outside_launch_window`, `test_offline_successor_lands_before_predecessor_expiry`, `test_attest_cadence_has_no_expiry_gap_with_eval_staleness`, `test_no_autonomy_oneshot_sets_runtime_max_sec`, **(r5)** `test_pre_offline_studies_units_end_by_1045z`; `systemctl --user show -p TimeoutStartUSec breezy-autonomy-eval-offline.service` reports `1h 44min 59s` (6299 s); `/usr/bin/grep -L TimeoutStartSec deploy/systemd/breezy-autonomy-eval-*.service` is empty |
| Honesty | the DONE claim states "machinery proven, edge unproven" and names the candidate-coverage path |

---

## 8. Risks and failure modes

| Risk | Mitigation |
|---|---|
| **Statistical capacity / KILL 2027-01-25** | Infeasible nominations stated, not hidden; no α spent while infeasible; power at n = 160 reported; R-B early is the only lever; score-2 date set |
| Type I inflation across windows | Lifetime `k_life` never resets; ≤ 1 nomination per window; K_LIFETIME ≤ 4; single look; LD-OBF for live; screening carries no type-I claim |
| Uncomputable deep tests | `BOOTSTRAP_B_MAX` 2¹⁹ ≥ ⌈200/(α_4/3)⌉; tail guard alerts if reached |
| k collision | single engine writer under `engine.lock` with CAS; FS copies from the row; mismatch is `ERROR`/`k_exceeded` |
| Joint-bound under-coverage in (b) | Bonferroni α_k/3; `N_IOC_MIN`; Manski worst case; `ACCEPT_FILL_SELECTION_SENSITIVE` |
| Calibration conjunct false-fails | relative paired test, one margin, `MIN_CALIBRATION_BUCKETS` fail-closed; WP0 false-fail bound ≤ 0.20 |
| R-B tuned on the prefix | data-free σ₀; take counts; tape asks; precommit disclosure; limit stated |
| Mixed closures | closure-keyed outputs; current-closure n; `mixed_closure` breach guard |
| **(r5)** Non-reproducible resampling across same-slot recomputes | per-(subject, slot, role) derived seed; `test_same_slot_recompute_bit_identical` |
| **(r5)** Engine and feasibility record drift apart | one `sample_size` definition; all inputs pinned block keys; projection-equals-columns test; transaction contract test |
| **(r5)** A stale-but-unexpired verdict keeps ATTEST alive | today's-slot rule at 15:25Z; newest per (family, kind) consumption |
| **(r5)** A pre-11:00 study holds the flock into eval-offline's budget | end ≤ 10:45Z contract test; AUT-3 rerun request |
| Label run overruns into eval-live | shared studies flock with a 300 s wait; a timeout writes no verdict and `eval_staleness` alerts by 15:25Z |
| Oneshot unbounded | `TimeoutStartSec` on both units; programme deploy test |
| Memory on the 30 GiB host | 14G/12G per ARCH §5.2; measured peak before enablement; memory-sum gate; ≤ 16G raised cap only by review in a free slot; never 01:00–04:30Z; stop the study, never the node |
| Fixture path contaminates production | separate state root; `fixture_candidate` metric; contract test that no fixture journal lands under `$STATE` |
| Shared venv / concurrent agents | exact interpreter; no `uv`/`pip`/`stash`; worktree `PYTHONPATH`; per-agent scratchpads; explicit-path commits |

---

## 9. Binding-constraint compliance

- **Nautilus immutability:** only native `BacktestEngine`, `ParquetDataCatalog` and Actor composition, reused through the moved `run_live_parity`; nothing patched.
- **Caps:** never read, written or assigned. The R-B loss stop is a PREREG statistic in contract units. `test_autonomy_never_reads_or_writes_operator_controls` covers `breezy.analysis.autonomy` and `breezy.persistence.autonomy.nomination`.
- **allow_short=False:** untouched.
- **NO-SEND:** the refusing submit veto; no exec client; the exec store is never imported; `test_execution_egress_firewall_guard` unchanged.
- **Master enablement and permit:** never touched. The fixture path never writes the production registry.
- **PREREG via ruling:** R-B…R-G are drafts for the peer loop; C4.1 is consumed by name; no PREREG semantics change in this plan.
- **Safety tests:** none weakened; golden and contract tests byte-unchanged; the G36 move keeps the existing tests green; new tests only add.

---

## 10. Self-score

**(r5, K10) Re-scored excluding unmeasurable values.** Values that only WP0/WP7a can measure (σ, `sigma_b_pinned`, ρ̂/deff, per-child R and t_p95, the R-C false-fail rate and `n_min_c` table, the MC power and reach probabilities) are **excluded from the score**: neither credited nor deducted. Each has a stated hard-fail rule that returns the WP to review if the measurement breaks the design (§3.10 R-C ≤ 0.20 false-fail; §3.12 t_p95 and memory rules; feasibility record). r4 deducted 3 points for them under Correctness.

| Axis | Max | r4 | r5 | Note |
|---|---|---|---|---|
| Fidelity | 20 | 19 | 20 | Every Rev 9.2 §10 obligation mapped; errata E-3 applied; I-1 and I-2 endorsed by both reviewers, so r4's −1 is withdrawn |
| Correctness | 20 | 17 | 18 | K1–K9 close every reviewer finding (single sample-size definition, transaction call, today's-slot staleness, 6299 s bound, NO_INPUT kind, derived seeds, 10:45Z rule, look waiting on ancillary counts). −2: the ancillary-count look rule (K9) and the 10:45Z rule (K8) are new in r5 and unreviewed |
| Specificity | 15 | 14 | 15 | Every constant, key, seed formula, unit bound and test named |
| Acceptance | 20 | 17 | 18 | Checklist queries robust to Decimal spelling; new contract tests. −2: the proof window still waits on rulings, the memory sum, Wave 3 and the AUT-3/AUT-5 requests (dependencies, not unmeasurables) |
| Autonomy-safety | 15 | 14 | 14 | Fail-closed; stale-unexpired verdicts no longer keep ATTEST alive. −1: the dead-evaluator veto still depends on the policy listing `eval_staleness` |
| Reuse | 10 | 8 | 8 | −2: new permutation, calibration-NI, seeding and journal/nomination contract code |
| **Total** | 100 | 89 | **93** | Reviewers scored r4 at 94 and 91 (final 91), above r4's self-score; 93 sits inside that range |

### Contradictions with ARCH

**None open.** P4-7 to P4-15 are resolved by ARCH Rev 9.2 and deleted from this plan (see §R4). No new contradiction was found.

---

## §R5 Disposition (review `reviews/AUT-4-r4-merged.md`; ARCH Rev 9.2 sha `1b288d0e0172b233b791d875845e8002824a52d4a2e7819685ec0f2057572f42` + `reviews/ARCH-ERRATA-rev9_2.md`)

**10 items, 10 ACCEPTED, 0 rejected.** No ARCH contradiction introduced; no README criterion, cap, enablement, permit, NO-SEND or `allow_short` surface touched; no test weakened (r4's `test_offline_successor_lands_before_predecessor_expiry` assertion is kept and the constant fixed to meet it). New tests: 22. New cross-plan requests: 3 (AUT-5 ×2, AUT-3 ×1) plus one ARCH-0 owner review.

| # | Finding | Disposition | Where |
|---|---|---|---|
| K1 | [pm M1] Pin `n_min_c`, `alpha_total`, `stations`, per-predicate MDEs for (b), (c) in the §5 keys; `compute_nomination_columns` arithmetic only | **ACCEPTED.** Keys `alpha_total`, `stations`, `sigma_b_pinned`, `mde_a`, `mde_b`, `mde_c`, `n_min_c` (table k = 1…K_LIFETIME) added to the policy block; the function reads only named keys, raises on a missing one; `stations` checked against the root manifest by `feasibility_consistency`; WP0 (xiv) measures `sigma_b_pinned` and `n_min_c` | §3.3, §3.5, §3.8, §3.10 R-C/R-D, §4 WP0, §5 |
| K2 | [pm M2] Define `n_min_one_sided`, `c_min`, `deff` once in `src/breezy/persistence/autonomy/` (stdlib `NormalDist`); `eval_stats.py` imports; projection-equals-columns test | **ACCEPTED.** New `src/breezy/persistence/autonomy/sample_size.py` (also `n_min_eff`), ARCH-0 owner review as for `nomination.py` (I-2); identity test `test_sample_size_primitives_single_definition`; `test_projection_equals_engine_written_columns` | §3.2, §3.3, §3.8, WP2, WP7b |
| K3 | [pm M3] AUT-5 request: call inside `BEGIN IMMEDIATE` with named keys; contract test failing when columns are written without the call | **ACCEPTED.** Request written in §3.5 and §5; `tests/contract/test_nomination_columns_contract.py` (3 tests, spy-based); §6.4 row 9 | §3.5, §5, §6.4, WP5 |
| K4 | [mle 1] 15:25Z `eval_staleness` requires today's `slot_start` date for every producer; engine consumes newest per (family, kind) | **ACCEPTED.** Today's-slot rule over the policy key `eval_staleness_producers` (needed so the not-yet-enabled eval-offline does not FAIL ATTEST every day before prerequisite 7); "newest" ordering defined; engine request uses `acted=false`, never a new `reject_reason` (ARCH's set is closed) | §3.9, §5, WP8 |
| K5 | [mle 2] `EVAL_OFFLINE_TIMEOUT_START_S` = 6299 or loosen the assertion; recompute budget and worst end | **ACCEPTED, constant option** (the assertion is not loosened). Replay budget 3599 s; child timeouts 899/449 s; WP0 hard-fail 719/359 s; worst end 12:45:00; launch interval 11:00:00–12:46:00 | §3.3, §3.9, §3.12, WP0, §7 |
| K6 | [mle 3] NO_INPUT is OFFLINE_CHALLENGER on the champion; FS lane writes nothing without a nominee; cover in `eval_completeness` | **ACCEPTED.** Per-producer invariant stated; expected sets in `eval_completeness`; 4 tests | §3.1, §3.11, WP5/WP6/WP8 |
| K7 | [mle 4] Seed `SEED XOR int(sha256(subject_sha ‖ slot_date ‖ role)[:8])`; same-slot recompute bit-identical test | **ACCEPTED.** `seeding.derive_seed` with `‖` = 0x1F, hex `[:8]` base 16, closed role set; applied to the permutation, screening bootstrap, R-C bootstrap and (b) sign-flip; R-B MC keeps its design seed | §3.1, §3.2, §3.3, §3.5, §3.7, R-C, WP2/WP5 |
| K8 | [mle 5] Contract test that pre-11:00 studies units end by 10:45Z, or widen the flock wait | **ACCEPTED, contract-test option**; widening rejected (costs replay budget). AUT-3 r3's rerun (worst end ≈ 10:57Z) violates it: request to start 09:24Z with 4800 s or cap at 4140 s from 09:35Z | §3.9, §5, §6.4, WP6, §7 |
| K9 | [pm LOW] Single-look `fill_rate_underpowered` final by design, or wait for `N_IOC_MIN` inside the window; pin Decimal in query (3) | **ACCEPTED, wait option** (extended to `N_PROXY_MIN`, the same kind of ancillary count): the look waits for both counts; window end first → final INCONCLUSIVE. Decimal fields canonical `format(d.normalize(), "f")`; query (3) uses `tonumber`; the accounting check reads the string as `Decimal` | §3.1, §3.7, §7 |
| K10 | [mle 6] Re-score excluding unmeasurable values | **ACCEPTED.** Unmeasurables neither credited nor deducted; 93 | §10 |

---

## §R4 Rebase disposition (onto ARCH Rev 9.2, sha `1b288d0e0172b233b791d875845e8002824a52d4a2e7819685ec0f2057572f42`, plus `reviews/ARCH-ERRATA-rev9_2.md`)

**36 changes, all CONFORMED to ARCH or a binding decision; 0 rejected.** Every r3 contradiction was resolved by conforming the plan to ARCH. No README criterion changed. No cap, enablement, permit, NO-SEND or `allow_short` surface is touched. The r3 dispositions (§R3, F1–F14) stand except where a row below supersedes them.

**Resolved contradictions deleted from the plan.**

| r3 item | Resolved by (ARCH Rev 9.2) | r4 effect |
|---|---|---|
| P4-7 (detector-level ATTEST set) | C5 ATTEST row: `attest_required_detectors`, intraday HEALTH and RECONCILIATION only | §3.9; prerequisite removed |
| P4-8 (k vs K_max) | C4 "Two limits, one index"; already superseded in r3 | §3.5 |
| P4-9 (engine input journal) | C5 `engine_input/v1` | §3.13 conformed |
| P4-10 (two ruling shas) | C4 `policy_ruling_sha256` + `family_prereg_sha256`; restrictive fallback | §3.1, §3.6; Rev 5 fallback deleted |
| P4-11 (`verdict_id`) | C4 identity minus `verdict_id`, `produced_at_ns` | §3.1; `recompute_key` deleted |
| P4-12 (assumptions enum) | C4 closed five-tag enum | §3.1; r3's two extra tags withdrawn |
| P4-13 ("evaluated MINT") | ALPHA amendment + C4: α per nomination; a mint never nominated spends no α | §3.5 |
| P4-14 (C5 lifetime counter) | C5 `lineage_counters.nominations` + PROMOTE `k_life` column | §3.5 |
| P4-15 (absolute calibration leg) | C4 (c) relative NI, `MIN_CALIBRATION_BUCKETS` | §3.7, §3.10 R-C |

**Change log.**

| # | Change | ARCH / decision basis | Where |
|---|---|---|---|
| R4-1 | Basis Rev 5 → FROZEN Rev 9.2 sha `1b288d0e…` + errata; E-3 Z-label reading stated | README Items; PLAN_TEMPLATE ARCH-basis rule | §0 |
| R4-2 | OFFLINE_CHALLENGER becomes no-α screening on forward days after training end; archive pre-screen and confirmatory "stage 2" deleted; archive OOF used only for WP0 measurements | C4 Evaluation protocol | §3.5, §3.1a |
| R4-3 | Nomination = engine's SHADOW→CHALLENGER PROMOTE; AUT-4 supplies pure `compute_nomination_columns`; r3's flock-serialised `assign_k_life` and `alpha_ledger.py` deleted | C4, C5 nomination columns (V4); §5 AUT-4 owns α accounting | §3.3, §3.5 |
| R4-4 | Infeasible nomination charges no α and no K_LIFETIME, uses the window slot; `nomination_feasible` | C4 window-cap rule | §3.5, §6.3 |
| R4-5 | K_LIFETIME ≤ 4 and ≤ 1 nomination per window; `K_LIFETIME_EFFECTIVE`=6 and the nominal tier deleted | C4; §4.5; ALPHA amendment | §3.5, R-D |
| R4-6 | `mints_in_window`, K_max per window and `NO_CHANGE(k_max_reached)` deleted; mint rate is AUT-3's 1/day | C3 `refit_run/v1`; ALPHA amendment | §3.5, §5, §6.1 |
| R4-7 | `k_exceeded` redefined: FS `k_life` ≠ row → `ERROR`; `ERROR(mints_in_window_exceeded)` deleted | C4 "No `k_exceeded` in operation" | §3.1 |
| R4-8 | `BOOTSTRAP_B_MAX` is the pins literal; proposed 2¹⁹ covers α_4/3; tail kept as a guard; C_min table k = 1..4 | §4.5; C4 draw cap | §3.2 |
| R4-9 | C4 fields `k_life`, `alpha_k`, `n_min_eff`, `n_cap` on FORWARD_SHADOW only, copied from the row; null elsewhere; `mints_in_window` field removed | C4 Measurement | §3.1a |
| R4-10 | FS subjects are nominees only; champion baseline moved to HEALTH `eval_replay_path`; drill child screened only | C4 field rule; C5 DRILL_ADMIT (no nomination) | §3.7, §3.11 |
| R4-11 | Nominee uses only days after its nomination date inside its window | C4 multiple testing | §3.5 |
| R4-12 | FS (c) is one one-sided paired relative test, ruling margin, `MIN_CALIBRATION_BUCKETS`, reason `calibration_buckets_below_min`; |MSD| leg withdrawn; WP0 measures the false-fail rate | C4 (c), §4.5 V16, P4-6 | §3.7, R-C, WP0 |
| R4-13 | Two ruling-sha fields; `prereg_ruling_sha256` renamed; `accepted_family_preregs` deleted | C4 Provenance, P4-10 | §3.1, §3.6 |
| R4-14 | Restrictive fallback: a LIVE FAIL without policy DEMOTEs via `DEFAULT_RESTRICTIVE_CLASS`; r3's "honest gap" withdrawn | C4 Engine acceptance | §3.6, headline |
| R4-15 | No-boundary outcome renamed `no_registered_boundary` | C4 LIVE_SEQUENTIAL | §3.1a, §3.6 |
| R4-16 | `verdict_id` excludes `produced_at_ns`; `recompute_key` deleted | C4 Storage, P4-11 | §3.1 |
| R4-17 | `assumptions` limited to five tags; `fixture_candidate` and `fill_selection_sensitive` become metrics, the latter gated by policy key `ACCEPT_FILL_SELECTION_SENSITIVE` | C4, P4-12 | §3.1, §3.7, R-E |
| R4-18 | Engine input journal path and fields conformed; fixture journal under its own state root | C5 `engine_input/v1` | §3.13 |
| R4-19 | ATTEST cites only intraday HEALTH/RECONCILIATION; `eval_staleness` is an intraday HEALTH verdict; P4-7 prerequisite removed | C5 ATTEST row, §4.5 W1 | §3.9 |
| R4-20 | C4.1 consumed by name, filed in Wave 0; frozen window is [2026-07-01, 2026-10-02) | C4.1; HOLDOUT decision | §3.4, §3.5, §6.4 |
| R4-21 | eval-offline `MemoryHigh=12G`/`MemoryMax=14G`; peak measured before enablement; enabled only after AUT-6 memory-sum PASS | §5.2 Memory (V14, U6) | §3.9, §3.12, WP6 |
| R4-22 | eval-live takes the studies flock, not its own lock; contention with the label run bounded | §5.2 Locks | §3.6, §3.9 |
| R4-23 | Child timeout denominator 4·(`MAX_NOMINATIONS_PER_FORWARD_WINDOW`+1) = 8 → 900/450 s | C4 ≤ 1 nomination per window | §3.12 |
| R4-24 | G36 statistics moved byte-identically into `src/breezy/analysis/stats/` as WP1 = AUT-4a (Wave 1) | G36, §5.1 | §3.3, WP1 |
| R4-25 | `promote_enabled` bound `eta_date ≤ KILL − forward_window_days` with drill lost days; `feasibility_consistency` updated | §4.2 Y12, V19 | §3.8 |
| R4-26 | MDE at α_K = α_total·2^−K_LIFETIME in the feasibility record | C4; §4.2 | §3.8 |
| R4-27 | `INCONCLUSIVE` + `metrics.day_status=NO_INPUT` when nothing to evaluate | C4 Invariants (U10) | §3.1 |
| R4-28 | C2 inputs restricted to `p_source=c1_decision`; `voided_pair` excluded; `quote_ref`-only rows excluded from slippage by name | C2, C1 (U8) | §3.1, §3.4 |
| R4-29 | §6.4 prerequisites rewritten: ARCH Rev 7 items removed; ARCH-0 Wave 0, AUT-5 journal/fixture pass, AUT-6 ATTEST and memory sum added; Rev 7 deadline line removed | Rev 9.2 has every item | §6.4 |
| R4-30 | Contradictions P4-7..P4-15 deleted; "None open" | Rev 9.2 | §10 |
| R4-31 | Programme rules: deploy test against `RuntimeMaxSec` on autonomy oneshots; launch-window disjointness including W, TimeoutStartSec and TimeoutStopSec | PLAN_TEMPLATE systemd rule; §5.2 | §3.9, WP8 |
| R4-32 | All code, test and store paths made repo-root-relative or absolute (`$STATE` defined) | PLAN_TEMPLATE paths rule | throughout |
| R4-33 | Headline, §6.3 table and consequences rewritten: `k_life` stays 0 while infeasible; screening ETA ≈ 7 days | C4 window-cap rule | headline, §6.3 |
| R4-34 | R-D and R-F redrafted (K_LIFETIME 4, 1 per window, screening thresholds, nominee selection, keys); detector→class map drafted | C4; §4.2; §8 | §3.10 |
| R4-35 | R-B tied to `family_prereg_sha256`; peer-loop date ≈ 11-10 per ARCH; filing target 10-24 kept | C4 LIVE_SEQUENTIAL (P4-2) | §3.10, §6.4 |
| R4-36 | Self-score re-derived (89) | PLAN_TEMPLATE §10 | §10 |

**Interpretations stated (not contradictions; for the peer loop).**
- **I-1.** ARCH C4 lists `k_life`, `alpha_k`, `n_min_eff`, `n_cap` "for `FORWARD_SHADOW`". A subject with no nomination row has no values for them, so r4 produces FORWARD_SHADOW only for nominees (R4-10). If the ARCH owner instead intends FORWARD_SHADOW on non-nominees with these fields null, only `eval_replay_path` would move back to the FORWARD_SHADOW kind; no other section changes.
- **I-2.** `compute_nomination_columns` lives in `src/breezy/persistence/autonomy/nomination.py` because the engine calls it and must not import `breezy.analysis` (G15). It is an AUT-4 addition to an ARCH-0 package, reviewed by the ARCH-0 owner, not a change to any contract.
