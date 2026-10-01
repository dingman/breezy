# FQ go-live plan: `forecast_quantile_ladder` (pm_us_crh_fq_v1) to live real orders

- **Date:** 2026-10-01
- **Authority:** `docs/evidence/RULING_operator_fq_live_real_orders_2026-10-01.md`. The operator chose "Real orders ASAP" and "Keep current caps".
- **Status:** **Revision 1.** It revises the draft after three blind REVISE reviews (security 80, architecture 76, market-mechanics 76); dispositions are in §8. This is ruling build gate 1. Nothing here is implemented yet.
- **Branch:** `feat/data-capture-and-risk`, HEAD `c8bb5c9d`. The node runs from this tree.
- **Platform:** Nautilus Trader 1.231.0. It is immutable: every change below is a Breezy Actor/Strategy/composition/persistence change.

---

## 0. Findings that reshape the build (read first)

The work goes beyond the 7 known gaps. These were verified against code and data this session.

| # | Finding | Evidence | Severity |
|---|---------|----------|----------|
| F1 | **The live calibration loader cannot read the real artefact.** `load_calibration_artefact` reads `payload["emos"]`. The selected artefact `nbp_validate_candidate_2026-09-30.json` (sha `9c0b6d6e…923a5e`) has no `emos` key; its keys are `emos_params_by_version`, `emos_draws_by_version`, and so on. The result is a `KeyError` at boot, which becomes `SettingsError`, and the boot ends in EXIT_CONFIG_ERROR. | `strategy/forecast_quantile_ladder/calibration_artefact.py:73`; `app/trade.py:703-741` | BLOCKER |
| F2 | **The bounds loader would crash on the real draw shape.** The real draws are triples `[a, gamma, delta]`, written by `NbpCalibrationArtefact.to_json_dict`, `analysis/nbp_calibration.py:2426-2429`. The loader unpacks `for a, gamma in version_draws` and raises a plain `ValueError`. `trade.py:721-737` does not catch a plain `ValueError`, so this is an uncaught crash, not a clean refusal. It would also silently drop each draw's own delta. | `artefact_bounds.py:149-151` | BLOCKER |
| F3 | **Draws are pooled across NBM versions.** The live bounds pool v4.0 through v5.0 draws into one set. Analysis M2 uses **per-version** parameters, `_emos_params_for_version`, `scripts/analysis/nbp_skill_study.py:1385-1387`. For example, v4.1 has a=0.29 and v5.0 has a=0.60. The live tape is entirely v5.0 (`header_model_version` = `5.0` in the Aug and Sep 2026 derived partitions). Also, `ForecastQuantileVector` carries no model version. | `artefact_bounds.py:148-151`; `ladder_ev/forecast_state.py:180-208` | BLOCKER (mispricing) |
| F4 | **The correction form is refused live.** This is known gap 2. `artefact_bounds.py:139-145`. The artefact has `correction_form=linear_lst_day_length`, coefficients `[-0.39835…, 4.28148…]`. Analysis adds `slope·day_length(lat, climate_day) + intercept` to `a` (`nbp_skill_study.py:1402`, `:1417-1433`; `nbp_calibration.py:1428-1438`). | — | BLOCKER |
| F5 | **SL-13p2 parity cannot run on real data as written.** (a) `_load_nbp_rows` (`nbp_shadow_parity.py:340-356`) keeps all 9 MAX leads per cycle, and the derived store has 9 per cycle (verified on `2026/09/nbp_20260920_13z.parquet`). It then stamps `climate_day` with the **UTC** date of `valid_start_ns`, which is one day after the LST climate day. Pushing 9 different days into one cycle raises `ValueError` (`forecast_state.py:236-243`), and `main` maps that to exit 2. (b) The live leg builds `ForecastPoint` with `valid_start/end = cycle_runtime_ns` and `model_version="stored"` (`:489-503`). That gives a LST-day-D vector, so every D+1 rung is refused `vector_day_mismatch`. (c) Both legs use `_point_bounds_provider`, not the live `ArtefactBoundsProvider`. Parity is therefore currently broken or vacuous for the actual take rule. | `scripts/analysis/nbp_shadow_parity.py`, `nbp_shadow_parity_pure.py` | BLOCKER (gate 5) |
| F6 | **Fee verification is unwired for fq.** The fq branch passes no `fee_verified` (`trade.py:703-720`), so `try_submit` skips the fee guard (`strategy.py:433`). `_build_fee_drift_probe` only works off `strategy.config.instrument_ids` (`trade.py:264-282`), which the fq config does not have. The two strategies also expect different callable shapes: the CRH holder is `(now_ns) -> bool` (`trade.py:309`), and fq is `() -> bool`. | — | HIGH |
| F7 | **The supervisor's subscribe marker can falsely pass.** `on_start` logs `ForecastQuantileLadderStrategy subscribed` unconditionally (`strategy.py:293`), even when every id was skipped as `no instrument … in the cache` (`:237-242`). The supervisor's self-check keys on that marker (`trade_supervisor_core.py:161-181`). | — | HIGH |
| F8 | **The NBP feed has no positive log line.** `NbmQuantileActor` logs only failures (`nbm_quantile_actor.py:440-525`). Ruling gate 7 ("forecast feed publishing") is unobservable from the node log today. | — | HIGH (proof gate) |
| F9 | **Four timers key off the supervisor's `BREEZY_SENDING_FAMILY_ID` with CRH semantics.** They are `score-live-trials-run.sh:153-165`, `replay-daily-run.sh:127-140`, `decision-funnel-digest-run.sh:45-58`, and `family-tally-v2-run.sh`. Switching the id makes them run CRH tooling against an fq manifest. | `deploy/systemd/*-run.sh` | MEDIUM |
| F10 | **The hypothesis ledger is outside the live import graph by contract.** Both directions are forbidden (`pyproject.toml:180-212`), and no live code reads it. H-FC-NBP-EV-2026-09 is **not** in `~/.local/share/breezy/derived/hypothesis/hypothesis_ledger.jsonl`, which holds 4 rows, none of them fq. | — | Decision, §2 D4 |

---

## 1. Scope and invariants (restated in every implementation brief)

- **Nautilus is immutable.** Extend it only through Actor/Strategy/StrategyConfig.
- **`allow_short` stays `False`.** `config.py:78-82` already raises otherwise. NO exposure comes only from a BUY on the native NO instrument.
- **No code reads, assigns, defaults or logs the two operator caps.** They are max daily budget and max per position (`operator.env`). They are enforced unchanged by `DailySpendLedger.authorize_order_cost` (`exec/client.py:5495-5506`) and by the permit session ceilings (`client.py:5459-5480`).
- **Never weaken or delete a safety, settlement, contract or NO-SEND test.** `tests/unit/test_forecast_quantile_ladder_manifest_and_markers.py::test_exec_client_is_byte_identical_to_its_pre_sl13_sha256` stays. **The exec client is not edited by this plan.**
- **Fail closed on any bad artefact, unknown version, missing ruling, or missing permit.**
- **The A1 halt on `pm_us_crh_v4` is untouched.** fq has its own halt key, `continuous_rung_hold/family_halt/pm_us_crh_fq_v1` (`trial_day_latch.py:293,319`).
- **Run every slice in its own worktree** with `PYTHONPATH=<worktree>/src` and the primary `.venv` interpreter. Never use `uv sync` or `uv run`. Run `lint-imports` after every slice. Read the gate's EXIT before any push.

---

## 2. Design decisions

- **D1. Hours to settlement = LST midnight ending `climate_day`; the strategy's `expiration_ns` is wrong.** This resolves known gap 3.
  - Ruling A-6 defines h as "hours from decision to settlement" (`RULING_forecast_nbp_reopen_2026-09-29.md:319`).
  - The settled quantity is the CLI daily max over the **LST** climate day. It is fully determined at LST midnight, which is the same LST convention `decision._is_d_plus_1` uses (`decision.py:192-194`). The pure parity path already uses this definition (`nbp_shadow_parity_pure.py:186-201`).
  - The venue's `endDate`, which becomes `expiration_ns` (`adapters/polymarket_us/parsing.py:1388-1390`), is listing metadata. Captured payloads show 05:00Z, 06:00Z, 08:00Z and 23:59Z values, so it is not the settlement instant.
  - **Consequence, stated:** for every D+1 decision h ≥ 24, so `margin = m24 = 0.06` uniformly. The `expiration_ns` path could have lowered the margin late in the evening on a 05:00Z or 23:59Z listing.
- **D2. One live calibration loader, version-aware, with a shared correction.**
  - The pure correction math moves into `src/breezy/strategy/ladder_ev/location_correction.py`. Analysis is allowed to import strategy under the layers contract, `pyproject.toml:77-97`.
  - Analysis (`nbp_calibration.CorrectionForm`, `apply_correction_form`, `_correction_prediction`, `emos_params_from_draw_entry`) and the skill study (`_daylight_hours`) both delegate to it. That makes ONE implementation (DRY), and the live path never imports `breezy.analysis` (`pyproject.toml:155-163`).
  - The live loader resolves `(model_version_era, station latitude, climate_day)` to:
    - point `EmosParams(a_v + c, γ_v, δ)`;
    - draws `[EmosParams(a_i + c, γ_i, δ_i)]` for **that version only**.
  - `c = slope·daylight_hours(lat, climate_day) + intercept`.
  - The era is `f"v{model_version}"`, the same "header wins" rule as `scripts/analysis/nbp_backfill.py:224`.
- **D3. Enable path is a two-key gate, mirroring the existing `exit_gate` precedent** (`persistence/exit_gate.py:19-55`).
  - **Key 1:** the manifest gains an OPTIONAL key `live_orders_ruling`. It is accepted only on a `REGISTERED` manifest. It is omitted when absent, so every existing manifest keeps a byte-identical `manifest_sha256`.
  - **Key 2:** a new `src/breezy/persistence/live_orders_gate.py` holds a `Final` frozenset of **3-tuples**, `{("pm_us_crh_fq_v1", "RULING_operator_fq_live_real_orders_2026-10-01", "11c69d132a70d8e328d3720314336aa6f2cf176d52fd25d5f2e20a7189711c1f")}`. `live_orders_authorized` resolves `docs/evidence/<ruling>.md` against the repo root, requires `resolve().is_relative_to(repo_root/'docs/evidence')`, and requires the file's sha256 to equal the pinned value. The ruling file is currently untracked, so S8 commits it byte-unchanged; any later edit to it fails the gate closed.
  - `shadow_only=False` only when key 1 matches, key 2 matches, and `sending_permit is not None`. A declared ruling that fails key 2 or the file check **refuses boot** (EXIT_CONFIG_ERROR).
  - Neither key reads or writes a cap.
- **D4. Hypothesis register: no ledger write and no bypass code.** Live boot never consults the ledger, by import contract (F10). Registering H-FC-NBP would spend a programme slot and mislabel a non-confirmatory run as inferential (MAX_HYPOTHESES=4, `hypothesis_ledger.py:179`). The operator override is recorded instead by:
  - the manifest's `live_orders_ruling`;
  - a sentinel boundary artefact that makes any accidental `family_tally_v2` run on fq refuse (`family_tally_v2.py:1567-1569` sha check);
  - a PROGRESS.md line.
- **D5. Registered manifest fields** (S8):
  - `status=REGISTERED`
  - `d0_climate_day` = activation boot date + 1. It is the first D+1 climate day and is never retroactive.
  - `density_artefact_path=deploy/families/artefacts/nbp_calibration_pm_us_crh_fq_v1_2026-09-30.json`. This is a **byte copy** of the candidate, `density_artefact_sha256=9c0b6d6e66a587c1b4e14e5f95ff5cedb3c7195f62f8ad4238191fdd75923a5e`, cross-checked against the `.sha256` sidecar.
  - `boundary_artefact_path=deploy/families/artefacts/not_applicable_boundary.json` plus its real sha.
  - `taker_fee_coefficient="0.0695"`, `stations` unchanged, `live_orders_ruling=RULING_operator_fq_live_real_orders_2026-10-01`.
  - No `exit_rule`, so the family holds to settlement and the exit gate stays closed (`exit_gate.py:55`).
- **D6. Activation = one unit line.** `deploy/systemd/breezy-trade-supervisor.service:128` changes `BREEZY_SENDING_FAMILY_ID=pm_us_crh_v4` to `pm_us_crh_fq_v1`. Cardinality-1 is structural (`settings.py:816-822`, `composition.py:257-291`), so v4 stops being the sending family by construction. Its manifest and its A1 halt are untouched.
- **D7. The supervisor marker map needs no edit.** `forecast_quantile_ladder` is already mapped (`trade_supervisor_core.py:161-166`). The self-check's family-halt and startup-evidence checks are family-id-parameterised (`trade_supervisor.py:457-488`, `trade_supervisor_core.py:466-482`). F7 is fixed on the strategy side.
- **D8. Reuse the crh exec paths unchanged.** The fq order is LIMIT/IOC/BUY/qty 1, not post-only (`strategy.py:470-478`), so it passes `submit_chain.unmappable_order_reason` (`exec/submit_chain.py:316-357`) for YES and NO legs alike. The OPEN-intent wait (`client.py:5425`), family-halt veto (`:5436`), permit consume (`:5459`), `DailySpendLedger` (`:5497`) and AMBIGUOUS handling (`:5529-5543`) are all family-agnostic. The permit mint is family-agnostic too (`order_enablement.py:190-222`).
  - **The NO-leg reconciliation path is reused, verified with codegraph.** "Family-agnostic by inspection" is not relied on:
    - **Wire price.** `submit_chain.build_order_body` (`exec/submit_chain.py:360-387`) applies `leg_prices.wire_price_for_leg` (`leg_prices.py:56-75`), giving the `1 − p` complement on NO.
    - **Echo check.** `assert_echo_matches_leg` (`leg_prices.py:129-148`) refuses anything except the NO echo `(ORDER_SIDE_SELL, ORDER_INTENT_BUY_SHORT)`.
    - **Fill booking.** `instrument_price_for_leg` (`:78-96`) inverts the wire price for the NO fill booking.
    - **Position sign.** `reports.position_leg` (`exec/reports.py:1406-1449`) applies the leg sign before reconciliation: a venue `outcome="No"` with netPosition −q maps to LONG q on the `^no` instrument, inside `parse_position_status_report` (`:1452-1546`). `client._map_position` (`client.py:4308-4412`) resolves it onto the real NO instrument and refuses when that instrument is absent.
    - **Ledger.** `_seed_spend_from_durable_fills` (`client.py:2214`) books a NO fill into the same `DailySpendLedger`. The first-NO-order key reconcile is `client.py:2275-2320`.
    - **Existing proving tests:**
      - `test_polymarket_us_exec_positions.py::test_an_explicit_no_outcome_maps_the_no_leg` (:151);
      - `test_polymarket_us_exec_client.py::test_a_no_holding_is_long_on_the_no_leg_instrument_in_a_mixed_payload` (:1414) and `::test_a_no_holding_with_no_no_leg_instrument_loaded_is_refused` (:1499);
      - `test_no_side_fill_attribution_2026_09_14.py::test_a_no_leg_fill_seeds_the_ledger_at_its_premium` (:322);
      - `test_no_side_boot_reconcile_2026_09_14.py` (:37, :78);
      - `test_leg_prices_2026_09_14.py` (:34, :91, :95);
      - `test_no_side_submit_chain_2026_09_14.py` (:111, :174).
    - **New go-live gate test (S6 #9)** re-drives this chain from an **fq-composed** order.
- **D9. Cardinality-1 is structural (verified, item 11).**
  - `BreezyTradeSettings.sending_family_id` is a single `str | None` slot (`runtime/settings.py:822`).
  - `run()` loads exactly ONE manifest, `_FAMILIES_DIR / f"{settings.sending_family_id}.json"` (`app/trade.py:492`), and dispatches on its `composition_kind` through a single `if/elif` chain (`:539-759`).
  - `build_continuous_rung_hold_strategies`, the only constructor of v4's `ContinuousRungHoldStrategy` and its position monitor (`current_rung_hold/composition.py:592-739`), is reachable **only** from the `continuous_rung_hold` branch (`trade.py:556-657`).
  - With `BREEZY_SENDING_FAMILY_ID=pm_us_crh_fq_v1`, the v4 manifest is never read, and no v4 strategy, latch factory, fee probe or monitor is composed. The only cross-family state is the shared exec store, so v4's halt row persists untouched.
  - No slice is needed.
- **D10. One side per rung per climate day (coordinator decision, item 9).** Once either side of a (station, climate_day, rung) Takes, the other side refuses with `Refuse("opposite_side_latched")`. This is enforced in `decision.evaluate` immediately after the own-side latch check (`decision.py:247-248`) via `latch.is_latched(..., side=opposite)`, so it is durable across restarts through `PersistentQuantileLadderLatch`'s `rung_id:side` composite keys (`persistent_latch.py:85-92`).
- **D11. The idle-timeout lesson's scope (item 12).** The Nautilus `WebSocketConfig.idle_timeout_ms` 60 s trip (memory `nautilus-idle-timeout-trips-on-quiet-feed`) applies only to the Polymarket.us **venue WebSocket** data and trade feed that the fq strategy subscribes through. It does **not** apply to `NbmQuantileActor`. That actor is a timer-driven, GET-only `httpx` poller (`ingest/nbm_quantile_transport.py:248-376`, `nbm_quantile_actor.py:311-338`) with its own connect/read timeouts, a stale-cycle alert (`NBM_NBP_STALE_CYCLE`) and next-timer retry; no WebSocket is involved.

---

## 3. Slices

Each slice uses tdd-guide plus python-reviewer, and keeps RED→GREEN output as its artefact.

**Merge rule (item 8), binding for EVERY slice below:**
1. Rebase onto the already-merged `feat/data-capture-and-risk` HEAD before merge. Agent worktrees can start stale.
2. Re-run the slice's focused tests on the rebased tree.
3. Merge (ff only).
4. Run the full gate after each merge, and read its EXIT before the next merge.

S2, S3, S6 and S10 all touch `strategy.py` and/or `decision.py`/`latch.py`, so they are rebased serially in the §4 merge order.

### S1. Shared location-correction math into `src` (DRY)

**Wave 1, parallel.**

- **Files:**
  - **new** `src/breezy/strategy/ladder_ev/location_correction.py`. It is pure and has no I/O. It contains:
    - `CorrectionForm`;
    - `daylight_hours(latitude_deg, day)`, the body moved verbatim from `nbp_skill_study.py:1359-1367`;
    - `correction_prediction_f(form, *, month, day_length_hours, month_offsets, linear_coefficients)`;
    - `emos_params_from_draw_entry`.
  - `src/breezy/analysis/nbp_calibration.py:1335-1379,1428-1438,2337-2355`: re-export and delegate.
  - `scripts/analysis/nbp_skill_study.py:1343-1367`: `_daylight_hours` keeps the latitude lookup and calls `daylight_hours`.
- **RED tests:** `tests/unit/test_location_correction_parity.py`.
  - Golden values are captured from the **pre-move** functions for {KLAX, KSFO, KMDW, KMIA} × every day of 2025 and 2026: `_daylight_hours`, `apply_correction_form(LINEAR_DAYLENGTH)` and `_correction_prediction`.
  - Assert exact float equality after the move.
  - `nbp_calibration.CorrectionForm is location_correction.CorrectionForm`.
  - A 2-element and a 3-element draw entry parse identically.
- **Acceptance:** goldens pass; `lint-imports` green; the SL-8f validate run reproduces byte-identical evidence JSON for the same inputs.
- **Depends on:** none. **Merge rule applies.**

### S2. Live calibration consumer: real schema, per-version, with correction

**Wave 2, after S1.**

- **Files:**
  - `strategy/forecast_quantile_ladder/calibration_artefact.py`, rewritten. It becomes ONE loader for the `NbpCalibrationArtefact` JSON shape (`schema_version` 1). It refuses on any of:
    - unpinned sha or a sha mismatch;
    - `fit_status != "OK"`;
    - any `converged_by_version` false;
    - `recalibration != "none"`;
    - a `correction_form` outside {`none`, `linear_lst_day_length`};
    - linear without coefficients;
    - empty draws for any version.

    It exposes `LiveCalibration.resolve(era, latitude_deg, climate_day) -> ResolvedCalibration(point, draws, correction_f)`, and an unknown era gives a typed refusal.
  - `artefact_bounds.py` computes from the resolved draws, so the duplicate loader is removed.
  - `bounds.py`: the `BoundsProvider` protocol becomes `(*, percentiles, draws, ladder, rung_id)`, retiring the `percentiles_fn` closure (`composition.py:106-133`).
  - `ladder_ev/forecast_state.py:180-269`: `ForecastQuantileVector.model_version`. `push(model_version=…)` refuses a mixed-version cycle.
  - `ladder_ev/forecast_subscriber.py:176-200`: pass `f"v{data.model_version}"`.
  - `decision.py:256-268`: use `resolve(...)`, with a new `Refuse("calibration_version_unavailable")`, and take a `latitude_deg` argument.
  - `strategy.py` `on_start`: cache the station latitude via `registry.enrichment_coordinates`, the same source as `nbp_skill_study.py:1336-1339`.
  - `composition.py:194-199`: one load.
  - `trade.py:721-737`: the new loader errors join the fail-closed tuple, typed rather than a bare `ValueError`.
- **RED tests:**
  1. `test_live_loader_accepts_the_committed_registered_artefact`, on a byte-copy fixture; it currently fails with `KeyError 'emos'`.
  2. `test_three_element_draws_keep_their_own_delta`.
  3. `test_draws_are_never_pooled_across_versions`.
  4. `test_unknown_model_version_refuses_closed`.
  5. `test_month_offset_form_is_refused_live`.
  6. Not-converged, bad-recalibration and missing-coefficient refusals.
  7. **Calibration parity** (`tests/unit/test_fq_live_calibration_parity.py`). For the real artefact × {LAX, SFO, MDW, MIA} × 24 dates spanning the year × the percentile fixtures:
     - live point-CDF rung probabilities == `nbp_skill_study.calibrated_m2_rung_probabilities(version="v5.0", correction_f=_correction_amount(...))`, with tolerance ≤ 1e-12;
     - live `correction_f` == `_correction_amount`, exactly;
     - each resolved draw == `EmosParams(a_i + c, γ_i, δ_i)`.
  8. A malformed artefact gives EXIT_CONFIG_ERROR, never an uncaught exception.
- **Acceptance:** green, including the existing `tests/strategy/forecast_quantile_ladder/*` tests after mechanical protocol updates. Test intent stays the same.
- **Depends on:** S1. **Merge rule applies.**

### S3. Margin horizon: LST-midnight hours to settlement (unchanged; PM-confirmed)

**Wave 1, parallel.**

- **Files:**
  - `margin.py`: `hours_to_settlement(*, now_ns, climate_day, std_utc_offset_hours)`.
  - `strategy.py:572` uses it.
  - `rung_expiration_ns` (`strategy.py:189-195,278-280`) stays as an observability field only.
  - The pure parity path keeps its own independent formula (`nbp_shadow_parity_pure.py:186-201`).
- **RED tests:**
  - A LAX rung with venue `expiration_ns` = 05:00Z gives the LST h.
  - Property test: every D+1 tick has `forecast_margin(h) == 0.06`.
  - Strategy and pure-path h agree.
- **Depends on:** none. **Merge rule applies.**

### S4. SL-13p2 parity harness repair (F5)

- **S4a. Wave 1, parallel.**
  - `_load_nbp_rows` (`nbp_shadow_parity.py:340-356`):
    - keeps only the nearest MAX column per (station, variable, cycle), the same rule as `nbm_quantile_actor._nearest_per_station_variable`, `:208-218`;
    - sets `climate_day` via `nbm_quantile_parse.max_column_lst_climate_day`;
    - carries `header_model_version`.
  - Add NO-side batch evaluation from NO-leg depth rows.
  - `to_counts_dict` carries per-(side, decision-kind) counts for both paths (counts only, plan §4.4).
  - Add a NO-depth census of the window: the number of days with at least 1 NO-leg depth row per station.
- **S4b. Wave 3, after S2, S3 and S10.**
  - The live leg builds `ForecastPoint` from the row's real `valid_start_ns`/`valid_end_ns` and `model_version`.
  - Both legs use the S2 calibration and bounds. The batch leg wires them independently; `tests/unit/test_nbp_shadow_parity_contract.py` stays.
  - The batch path mirrors D10's `opposite_side_latched` independently.
  - **Vacuity guard (item 6).** `main` returns 1 unless, on **each** path, **YES and NO each** have at least 1 evaluated decision that is neither `NotExecutable` nor `NotDPlus1` over the window.
  - If the S4a census shows the pre-freeze window holds **no** NO-leg depth for any station-day, the report states `no_side_unexercisable_in_window=true` and the guard requires YES only. In that case, a **synthetic NO-path parity case** becomes a mandatory gate test: `tests/unit/test_nbp_shadow_parity_no_side_synthetic.py`. Its fixture is a constructed tape with NO-leg Depth10 rows for 2 station-days and real-shaped NBP rows. Both paths must produce identical NO decision keys, including at least 1 NO `Take` and at least 1 `opposite_side_latched`, with mismatches 0.
- **RED tests:**
  - A real-partition fixture (9 leads) loads without `ValueError`, with `climate_day` equal to LST D+1.
  - `stored` is never used as a model_version.
  - A 1-day real-shaped fixture gives at least 1 non-vacuous decision per side on both legs, with mismatches 0.
  - The vacuity guard returns 1 on a YES-only run when NO is exercisable.
  - The synthetic NO case above.
- **Depends on:** S4a none; S4b needs S2, S3 and S10. **Merge rule applies.**

### S5. Enable path, ruling pin, path containment, shadow_only guard

**Wave 1, parallel.**

- **Files:**
  - `persistence/family_manifest.py`:
    - `_OPTIONAL_KEYS` gains `live_orders_ruling` (`:151-153`), with pattern `\ARULING_[A-Za-z0-9_.-]{1,120}\Z`;
    - the key is refused on `DRAFT_NOT_REGISTERED`;
    - add a getter that returns None when absent (`:399-424`);
    - **Path containment (item 10):** `boundary_artefact_path` and `density_artefact_path` must be relative, have no `..` component, and satisfy `(repo_root / p).resolve().is_relative_to((repo_root / "deploy/families").resolve())`. Otherwise `FamilyManifestValidationError`. The repo root is resolved from the manifest's own parent, as in `trade.py:111`.
  - **new** `persistence/live_orders_gate.py`: the 3-tuple allowlist (D3) and `live_orders_authorized(manifest, repo_root) -> LiveOrdersDecision(enabled, reason)`. Reasons are a closed enum: `no_ruling`, `not_allowlisted`, `ruling_missing`, `ruling_outside_evidence`, `ruling_sha_mismatch`, `permit_absent`, `ok`. All except `no_ruling` and `permit_absent` refuse boot.
  - `forecast_quantile_ladder/composition.py:136-152,232-241`: add `shadow_only: bool = True`.
  - `app/trade.py:658-743`: compute it and log `fq_live_orders enabled=<bool> family_id=<id> ruling=<id|none> reason=<enum> ruling_sha256=<sha|none> calibration_sha256=<sha>`.
- **RED tests:** `tests/unit/test_fq_live_orders_gate.py`.
  1. Draft manifest with the key → refused.
  2. REGISTERED without the key → `shadow_only=True` everywhere, `reason=no_ruling`.
  3. Not allowlisted → EXIT_CONFIG_ERROR.
  4. Ruling missing → EXIT_CONFIG_ERROR.
  5. **Ruling sha mismatch (one byte appended) → EXIT_CONFIG_ERROR.**
  6. **Ruling path escaping via symlink outside `docs/evidence` → refused.**
  7. Permit absent → `shadow_only=True`, `reason=permit_absent`.
  8. All good → `shadow_only=False` everywhere.
  9. **Path containment:** `density_artefact_path` of `../../etc/x`, an absolute path, or a symlink escaping `deploy/families` → `FamilyManifestValidationError`. Every committed manifest still loads.
  10. Caps scan: no new module references `MAX_DAILY_BUDGET_USD_ENV_VAR`, `MAX_POSITION_COST_USD_ENV_VAR` or `operator.env` (extend `test_operator_caps_through_the_live_composition.py`).
  11. **shadow_only guard (item 5)**, `tests/unit/test_shadow_only_false_is_only_the_gate_output.py`. It is an AST scan of every `src/**/*.py`, the same pattern as the operator-env scan. It fails if any `shadow_only=` keyword argument, `shadow_only:` annotated default, or `shadow_only = ` assignment carries a value other than `True` or the single permitted expression, `shadow_only=not live_orders.enabled`, located in `app/trade.py`'s fq branch. It also fails if the `ForecastQuantileLadderConfig.shadow_only` default (`config.py:75`) changes from `True`. A positive control injects a synthetic `shadow_only=False` source string and asserts the scanner flags it.
  12. `manifest_sha256` is byte-identical for every committed manifest.
- **Depends on:** none. **Merge rule applies.**

### S6. Real-order path for fq: fee, markers, D+1 readiness, order alerts, NO-leg gate test (F6–F8, items 1, 2)

**Wave 1, parallel; merged after S3.**

- **Files:**
  - **Fee probe.** `app/trade.py:264-282,313-432`: `_build_fee_drift_probe` takes `slug_fn: Callable[[], str | None]`, so a late D+1 resolution still binds. The fq branch builds the probe and `_FeeVerifiedHolder`, with the halt written to `forecast_halt_latch`; `fee_drift_resolve_client` is wired in `_after_build`.
  - **fee_verified shape.** `strategy.py:139-153,420-435`: `fee_verified: Callable[[int], bool]`, called with `self.clock.timestamp_ns()`. This is the same shape as CRH.
  - **B4, kept.** The final marker `ForecastQuantileLadderStrategy subscribed n=<k>` is emitted only when k ≥ 1, at the moment the first subscription is made.
  - **D+1 readiness poll (item 2), Nautilus-native with no patching.**
    - `composition.py:182-192` no longer raises when all stations resolve zero. It builds one strategy per manifest station regardless, each given a `d1_resolver: Callable[[], tuple[str, ...]]`. That is a closure over the unchanged `resolve_station_instrument_ids(catalog_root, _d_plus_1_climate_days(...))` for that station.
    - In `on_start`, a strategy with zero subscribable ids arms a native `self.clock.set_timer(name="fq-d1-readiness-<station>", interval=timedelta(minutes=D1_POLL_INTERVAL_MIN), stop_time=start + timedelta(minutes=D1_POLL_WINDOW_MIN), callback=...)`. The constants are build-side and live in `composition.py`: `D1_POLL_INTERVAL_MIN=5`, `D1_POLL_WINDOW_MIN=60`.
    - Each fire re-resolves the ids from the catalog, keeps those present in `self.cache`, and subscribes them through the same `on_start` resolution code, refactored into `_subscribe_ids()`.
    - At window expiry with still zero for **every** station, the poll logs ERROR `FQ_D1_NOT_READY_TERMINAL stations=<list> window_min=60`, emits a CRITICAL alert through `resolve_alert_sink()` with event `FQ_D1_NOT_READY`, and never subscribes later.
    - The NoTradable refusal moves from a boot crash to this bounded, alerted terminal state. A per-station expiry with others live logs WARN `FQ_D1_NOT_READY station=<s>`.
    - **Stated limit:** an instrument absent from the node cache cannot be loaded mid-run. The Polymarket.us data client implements no `_request_instrument`, verified by grep of `adapters/polymarket_us/*.py`. So the poll closes the catalog-vs-cache lag only, and a market listed after the boot-time discovery is a terminal refusal for that day. No adapter or Nautilus patch is made.
    - Supervisor interaction: with no marker at the 17:05Z SELF_CHECK, the supervisor FAILs and alerts, which is correct. The marker appears on first subscribe if the poll succeeds before 17:10Z.
  - **Order alerts.** Add `on_order_filled`, `on_order_denied`, `on_order_rejected` and `on_order_expired`, with markers `FQ_ORDER_FILLED|DENIED|REJECTED|EXPIRED instrument=… side=… client_order_id=… reason=…`. They emit through `resolve_alert_sink()`, never logging a cap value.
  - **Feed lines.** `nbm_quantile_actor._publish` logs `NBM_NBP_PUBLISHED cycle_ns=… stations=<n> points=<n> model_version=…`, and `ForecastQuantileStateActor` logs `FQ_VECTOR_COMPLETE station=… cycle_ns=… climate_day=… era=…`.
- **RED tests:**
  1. A fee DISAGREE halts fq, and the next take refuses `family_halt`.
  2. An unbound holder refuses `fee_unverified`.
  3. Zero cached ids → no marker.
  4. YES-leg and NO-leg fq orders pass `unmappable_order_reason`.
  5. Caps through fq: extend `test_operator_caps_through_the_live_composition.py:438-566` to the per-position deny, `DailyBudgetExhausted`, and the neither-control refusal.
  6. AMBIGUOUS through fq → `OPEN_INTENT_WAIT_REASON` on the next take.
  7. The exec-client sha pin passes, so the exec client is unedited.
  8. The publish line appears once per cycle.
  9. **NO-leg reconciliation go-live gate (item 1)**, `tests/unit/test_fq_no_leg_reconciliation_parity.py`. It reuses the fixtures of `test_no_side_fill_attribution_2026_09_14.py` and `test_polymarket_us_exec_client.py:1414`. It drives an **fq-composed** NO Take on its own `^no` instrument through the real exec client with a stub sender returning the captured NO accept-fill shape, then asserts:
     - (a) the wire body price equals `1 − p` and the echo `(SELL, BUY_SHORT)` is accepted;
     - (b) the `DurableFillRecord` has the `^no` `instrument_id` and an `instrument_price_for_leg`-inverted cost;
     - (c) the `DailySpendLedger` booking equals the NO premium, identically to the CRH run of the same fill;
     - (d) a following boot's `generate_position_status_reports` on a venue payload of `outcome="No", netPosition=-1` maps to LONG 1 on the same `^no` id with `avg_px_open` equal to the CRH run's;
     - (e) native position and PnL for fq equal the CRH run's, field for field.

     The test runs the CRH and fq compositions side by side on identical inputs.
  10. Readiness poll:
      - zero ids at start with ids appearing at the 2nd fire → subscribes, and the marker is emitted then;
      - never appearing → `FQ_D1_NOT_READY_TERMINAL` plus 1 CRITICAL alert, no subscription, and the timer stopped;
      - a mixed-station case → WARN only;
      - all use a `TestClock` advanced manually.
- **Depends on:** none (merged after S3). **Merge rule applies.**

### S7. Downstream timers composition-kind-aware (F9)

**Wave 1, parallel.**

- **Files:**
  - `score-live-trials-run.sh`
  - `replay-daily-run.sh`
  - `family-tally-v2-run.sh`

  Each prints `<UNIT> SKIPPED -- composition_kind=forecast_quantile_ladder has no <tool>` and exits 0 for fq. **`decision-funnel-digest-run.sh` is NOT skipped:** it dispatches to the fq digest (S11).
- **RED tests:** an fq-id case in each existing wrapper test.
- **Depends on:** none. **Merge rule applies.**

### S8. Registration artefacts

**Wave 3, after S2 and S5.**

- **Files:**
  - `deploy/families/artefacts/nbp_calibration_pm_us_crh_fq_v1_2026-09-30.json` (byte copy, sha `9c0b6d6e…923a5e`).
  - `deploy/families/artefacts/not_applicable_boundary.json` (sentinel).
  - `deploy/families/pm_us_crh_fq_v1.json`, with the D5 fields; `d0_climate_day` is set in S9.
  - **Commit `docs/evidence/RULING_operator_fq_live_real_orders_2026-10-01.md` byte-unchanged.** Its sha256 is `11c69d13…711c1f`, pinned in S5.
  - `tests/unit/test_forecast_quantile_ladder_manifest_and_markers.py:90-102`: `…_is_committed_and_draft` is replaced by `…_is_registered_with_the_operator_ruling`. That is a deliberate fixture state change; the DRAFT refusal stays covered at `:52-61`.
  - `docs/core/PROGRESS.md`: one line.
- **RED tests:**
  - The replaced test is RED against the draft.
  - The manifest loads without `allow_draft`.
  - The S2 loader accepts the pin.
  - The S5 gate returns `ok` against the committed ruling.
  - A `family_tally_v2` boundary load on the sentinel refuses.
- **Depends on:** S2, S5. **Merge rule applies.**

### S10. One side per rung per climate day (item 9, D10)

**Wave 2, after S3; owns `decision.py` and `latch.py`.**

- **Files:**
  - `decision.py:247-248`: after the own-side latch check, `if latch.is_latched(station=…, climate_day=…, rung_id=…, side=_OPPOSITE[side]): return Refuse(reason="opposite_side_latched")`. The new constant `OPPOSITE_SIDE_LATCHED` is exported.
  - `latch.py` gets no change in semantics; a test pins that its `is_latched` is side-keyed.
  - `PersistentQuantileLadderLatch` gets no change, because the composite keys are already per side.
- **RED tests:**
  - A YES Take, then a NO evaluation on the same rung, gives `Refuse("opposite_side_latched")`. The reverse also holds.
  - Persistence: a YES Take latched durably, then a new `PersistentQuantileLadderLatch` over the same store (a restart), then NO refuses `opposite_side_latched`.
  - Different rungs on the same station-day are unaffected.
  - The decision-log field round-trips the new reason.
- **Depends on:** S3 (`strategy.py`/`decision.py` adjacency). **Merge rule applies.**

### S11. fq daily decision-funnel digest: "why no trades" (item 3, required before go-live)

**Wave 2, after S6 and S10, because it needs the refusal taxonomy.**

- **Files:**
  - **Decision sink.** `composition.py` wires each strategy's existing `shadow_decision_sink` (`strategy.py:143,368-372`) to ONE shared in-process aggregator, `FqDecisionCounts`. It counts `(station, side, kind, reason)` and flushes 1 JSONL summary row per 15 min, plus 1 at `on_stop`, to `<catalog_root.parent>/decisions/fq_funnel_<boot_day>.jsonl`. That is the same sibling-directory convention as `current_rung_hold/composition.py:676-687`, with mode 0600 under `UMask=0077`.
  - Counts only, never prices or P&L. The vocabulary is the closed `decision.py` taxonomy: `NotDPlus1`, `NotExecutable`, and `Refuse` reasons `already_latched`, `opposite_side_latched`, `forecast_unavailable`, `vector_day_mismatch`, `calibration_version_unavailable`, `not_executable`, `below_margin`, plus `Take`. The try_submit outcomes `phase0_permit_absent`, `family_halt` and `fee_unverified`, and the `FQ_ORDER_*` events, also count. An unknown reason fails the flush closed with ERROR, rather than dropping it.
  - **Digest.** `scripts/analysis/decision_funnel_daily_digest.py` gains `fq_funnel_for_day()`, selected when the manifest's `composition_kind == "forecast_quantile_ladder"`. It renders, per station × side, counts by reason for the prior UTC trading window, plus the family halt status (the existing `read_family_halt_status`, `:122`), takes, orders and fills.
  - It is delivered by the existing `breezy-decision-funnel-digest.service`, whose only EnvironmentFile is `alerts.env` (`:33-36`), via `emit_alert` INFO.
  - `decision-funnel-digest-run.sh` passes the fq id through.
- **RED tests:**
  - Aggregator counts and flush cadence on a `TestClock`.
  - An unknown reason → ERROR, flush refused.
  - The digest renders every taxonomy reason per station × side from a fixture JSONL.
  - The webhook payload contains no price, P&L or cap field (closed-key assertion).
  - The wrapper dispatches fq to `fq_funnel_for_day`.
  - **Positive control:** a run with `--positive-control` emits a digest marked `[POSITIVE CONTROL]` through `alerts.env`.
- **Depends on:** S6, S10. **Merge rule applies.**

### S9. Activation, plus the SL-15 heartbeat install (item 7)

**Serial, last. It is executed only by the §5 runbook.**

- **Files:**
  - `deploy/systemd/breezy-trade-supervisor.service:128` → `Environment=BREEZY_SENDING_FAMILY_ID=pm_us_crh_fq_v1`.
  - `tests/unit/test_trade_supervisor_phase1_unit.py:37` → `"pm_us_crh_fq_v1"`.
  - `pm_us_crh_fq_v1.json` gets `d0_climate_day`.
  - The SL-15 units `deploy/systemd/breezy-nbp-learning-nightly.{service,timer}` already exist; `systemctl --user is-enabled` reports `not-found`, so they are not installed. They are installed in §5 step 3b **after** their positive control passes.
- **RED test:** the unit test is RED against the old line.
- **Acceptance:**
  - the full gate is green on the activation commit;
  - the §5 step 3b positive controls fired;
  - §5 steps 4–6 pass.
- **Depends on:** S1–S8, S10, S11, and §5 steps 1–3b.

### Peer-review stage

The three reviewers who returned REVISE re-review Revision 1, blind and in parallel, before any slice merges.

---

## 4. Dependency graph and waves

```
Wave 1 (parallel, separate worktrees): S1 · S3 · S4a · S5 · S6 · S7
Wave 2: S2 (needs S1) · S10 (needs S3) ; then S11 (needs S6, S10)
Wave 3 (parallel): S4b (needs S2, S3, S10) · S8 (needs S2, S5)
Verification: §5 steps 1–3b
Activation: S9 inside 01:00–16:40Z → first boot 16:50Z
```

- **Merge order**, each step rebased onto the merged HEAD with the full gate after each merge (item 8): S1 → S3 → S6 → S10 → S5 → S7 → S4a → S2 → S11 → S4b → S8 → S9.
- **Timing:** go-live is the first 16:50Z launch at which §5 steps 1–3b are green **and** the supervisor was restarted inside the window. If 16:40Z is missed, there is no switch and v4 keeps booting halted. There is no partial activation.

---

## 5. Go-live runbook

All commands run from `/home/jon/breezy`. "PY" means `/home/jon/breezy/.venv/bin/python`.

### Step 1: full gate (run after the final merge; read EXIT)

```
systemd-run --user --wait --pipe -p LimitNOFILE=524288 -p WorkingDirectory=/home/jon/breezy \
  scripts/ci/run_tests_no_egress.sh --basetemp="$HOME/.cache/breezy-gate/fq-golive"; echo EXIT=$?
.venv/bin/lint-imports; echo EXIT=$?
.venv/bin/ruff check src tests scripts; echo EXIT=$?
.venv/bin/mypy src; echo EXIT=$?
```

Required: every EXIT is 0. Read the exit code itself, never the `-q` summary.

### Step 2: SL-13p2 replay parity on real pre-freeze tape

This runs alone, in a quiet window, with a memory cap. It needs the quote-tape env, meaning the same EnvironmentFile set as `breezy-quote-tape.service`, because `load_quote_tape_settings` is called in `main`.

```
sha256sum deploy/families/artefacts/nbp_calibration_pm_us_crh_fq_v1_2026-09-30.json   # == 9c0b6d6e…923a5e
systemd-run --user --wait --pipe -p MemoryMax=12G -p WorkingDirectory=/home/jon/breezy \
  -p EnvironmentFile=%h/.config/breezy/breezy.env \
  .venv/bin/python scripts/analysis/nbp_shadow_parity.py \
  --start-date 2026-08-30 --end-date 2026-09-25 \
  --nbp-derived-root "$HOME/.local/share/breezy/derived/nbp" \
  --calibration-artefact deploy/families/artefacts/nbp_calibration_pm_us_crh_fq_v1_2026-09-30.json \
  --calibration-sha256 9c0b6d6e66a587c1b4e14e5f95ff5cedb3c7195f62f8ad4238191fdd75923a5e \
  --output docs/evidence/SL13P2_parity_pm_us_crh_fq_v1_2026-10-01.json; echo EXIT=$?
```

Required:
- EXIT is 0;
- the report has `n_mismatches=0` and `n_numeric_mismatches=0`;
- for each path, YES and NO each have at least 1 decision that is neither `NotExecutable` nor `NotDPlus1`. If the report says `no_side_unexercisable_in_window=true`, YES only, and the S4b synthetic NO parity test must be green in step 1;
- at least 14 distinct days;
- per-kind counts on both legs that include at least 1 non-`NotExecutable`/`NotDPlus1` decision (the S4b vacuity guard).

Commit the report as evidence. It holds counts only.

### Step 3: pre-activation state checks (read-only)

```
PY - <<'PY'
from pathlib import Path; import os
from breezy.strategy.current_rung_hold.trial_day_latch import read_family_halt_rows_readonly, decode_family_halt_state
store = Path(os.environ["POLYMARKET_US_EXEC_STATE_DB"])
for fam in ("pm_us_crh_fq_v1", "pm_us_crh_v4"):
    print(fam, decode_family_halt_state(fam, *read_family_halt_rows_readonly(store, fam)))
PY
```

Run it with `breezy-trade.env` loaded.
- Required: fq `halted=False source=none`, with `legacy` not equal to `halts_all`.
- Required: v4 still halted (A1 unchanged).
- If fq is halted, **stop**. This needs a peer-review ruling, not a clear.

Then check that D+1 instruments are in the catalog for each station:

```
PY -c "import time; from pathlib import Path; import os; \
from breezy.strategy.forecast_quantile_ladder.composition import _d_plus_1_climate_days; \
from breezy.strategy.current_rung_hold.composition import resolve_station_instrument_ids; \
m=_d_plus_1_climate_days(('LAX','MDW','MIA','SFO'), now_ns=time.time_ns()); \
print({k:len(v) for k,v in resolve_station_instrument_ids(Path(os.environ['BREEZY_TRADE_CATALOG_ROOT']), m).items()})"
```

Required: at least 1 per station. With 0 everywhere, the node would boot into the S6 readiness poll and probably end in `FQ_D1_NOT_READY_TERMINAL`. Activate anyway only if the venue already lists D+1, because the cache is filled from boot discovery and the catalog lags. Otherwise defer a day.

### Step 3b: install the SL-15 heartbeat and the fq digest after their positive controls (item 7, item 3)

```
# SL-15 heartbeat: positive control first. Both freshness alarms must fire through alerts.env.
systemd-run --user --wait --pipe -p MemoryMax=4G -p WorkingDirectory=/home/jon/breezy \
  -p EnvironmentFile=%h/.config/breezy/alerts.env \
  .venv/bin/python scripts/analysis/nbp_learning_nightly.py --positive-control all; echo EXIT=$?
#   required: EXIT=0, the run log shows the stale-cycle AND stale-label alerts, and the webhook received them
ln -sf /home/jon/breezy/deploy/systemd/breezy-nbp-learning-nightly.service ~/.config/systemd/user/
ln -sf /home/jon/breezy/deploy/systemd/breezy-nbp-learning-nightly.timer ~/.config/systemd/user/
systemctl --user daemon-reload && systemctl --user enable --now breezy-nbp-learning-nightly.timer
systemctl --user list-timers breezy-nbp-learning-nightly.timer   # next run 02:05Z
# fq funnel digest positive control (S11)
.venv/bin/python scripts/analysis/decision_funnel_daily_digest.py --store-path "$POLYMARKET_US_EXEC_STATE_DB" \
  --family-id pm_us_crh_fq_v1 --positive-control; echo EXIT=$?   # [POSITIVE CONTROL] digest arrives via alerts.env
```

If either positive control does not reach the webhook, **stop**. A detector without delivery is not a control.

### Step 4: activation (01:00Z ≤ now < 16:40Z only)

```
# commit S9 (unit line + test + manifest d0) by explicit path, gate green on that commit (step 1 again)
systemctl --user daemon-reload
systemctl --user restart breezy-trade-supervisor
systemctl --user show breezy-trade-supervisor --property=Environment | tr ' ' '\n' | grep SENDING_FAMILY_ID
#   -> BREEZY_SENDING_FAMILY_ID=pm_us_crh_fq_v1
grep -E 'supervisor_started' ~/.local/share/breezy/logs/breezy-trade-supervisor.log | tail -1
#   -> revision=<activation commit sha>
```

`KillMode=process` keeps the current v4 node alive. The 16:40Z `STOP_PRIOR` SIGTERMs it, and the 16:50Z `LAUNCH` spawns fq.

### Step 5: first-boot live proof (16:50Z–17:10Z)

The node log is `~/.local/share/breezy/logs/breezy-trade-<YYYYMMDD>T<HHMMSS>Z.log`. Check it in this order:

1. `boot_family_declared id=pm_us_crh_fq_v1`
2. `live-trading permit issued issued_at_ns=… expires_at_ns=… ttl_s=36000`. This is the permit line.
3. `boot_family id=pm_us_crh_fq_v1 composition_kind=forecast_quantile_ladder status=REGISTERED manifest_sha256=<S8 sha>`. This is the family line.
4. `family_halt_state family_id=pm_us_crh_fq_v1 halted=False source=none`
5. `fq_live_orders enabled=true family_id=pm_us_crh_fq_v1 ruling=RULING_operator_fq_live_real_orders_2026-10-01 … calibration_sha256=9c0b6d6e…`
6. `composed stations … from family_id=pm_us_crh_fq_v1`
7. `ForecastQuantileLadderStrategy subscribed <id>` lines, then `ForecastQuantileLadderStrategy subscribed n=<k≥1>` per station. This is the strategy-subscribing proof. If the readiness poll is active, expect `fq-d1-readiness` fires followed by the marker, never `FQ_D1_NOT_READY_TERMINAL`.
8. `resolver: zero-fill corroboration=activities_v1 …`, which proves the exec client reconciled.
9. `NBM_NBP_PUBLISHED cycle_ns=… points=28 model_version=5.0` and `FQ_VECTOR_COMPLETE … era=v5.0`, within the first poll. This is the forecast-feed proof.
10. `SHADOW_DECISION` lines whose `reason` is **not** `forecast_unavailable`, `calibration_version_unavailable` or `vector_day_mismatch`.
11. The fee-drift probe resolves AGREE. A DISAGREE halts fq; then stop and escalate to peer review.
12. In the supervisor log, `self_check result=PASS … continuous_family_not_halted=True`.

13. `<catalog_root.parent>/decisions/fq_funnel_<day>.jsonl` gains a row within 15 minutes, and the next 02:xxZ funnel digest arrives.

Absence checks (grep count must be 0): `Phase0PermitForbiddenError`, `FQ_D1_NOT_READY_TERMINAL`, `no instrument .* in the cache`, `max subscriptions per connection reached`, `NBM_NBP_STALE_CYCLE`, `Traceback`.

For the first real order, the expected sequence is `TAKE` → `create-order classified kind=ACCEPT_FILL|ZERO_FILL|AMBIGUOUS` → `FQ_ORDER_FILLED`, or a deny reason. AMBIGUOUS handling is the existing resolver; do not hand-clear the intent.

**Rollback:** set the unit line back to `pm_us_crh_v4`, run `daemon-reload` and restart in the window, and SIGTERM the fq node via the supervisor's STOP_PRIOR. If immediate containment is needed, use the existing family-halt tool on `pm_us_crh_fq_v1` (`breezy-set-family-halt`). That is reversible, and the caps are never touched.

---

## 6. Risks

| # | Risk | Severity | Mitigation |
|---|------|----------|------------|
| R1 | Real-artefact incompatibility (F1–F3) would crash the boot or misprice through version pooling | CRITICAL | S2 with a byte-copy fixture of the real artefact, plus the calibration parity test |
| R2 | SL-13p2 is broken or vacuous on real data (F5), so gate 5 would be satisfied by an empty set | CRITICAL | S4a/S4b, per-kind counts and the vacuity guard |
| R3 | No demonstrated edge. Fees make expected value negative absent edge (operator was told; the ruling accepts this) | HIGH (accepted) | Caps bound the loss per order and per day; qty is always 1; family-halt tool for containment |
| R4 | D+1 markets are not in the catalog or cache at 16:50Z | HIGH | S6 bounded native readiness poll (5 min × 60 min), then a CRITICAL terminal alert; marker only on a real subscribe; §5 step 3 check. A market listed after boot discovery cannot be loaded mid-run (no `_request_instrument` in the adapter); that is accepted as a lost day |
| R5 | Fee verification is unwired (F6) | HIGH | S6 |
| R6b | YES and NO taken on the same rung (a self-hedge that pays fees twice) | — | Closed by D10 / S10 (`opposite_side_latched`) |
| R6 | The latch is consumed at Take, before submit (`decision.py:294`). A deny (OPEN intent, veto) burns that rung's trial for the day | MEDIUM (conservative direction, accepted) | Logged with `FQ_ORDER_DENIED`; no retry loop by design |
| R7 | The correction's own estimation uncertainty is not in the bootstrap bounds. A fixed shift `c` is applied to every draw, matching analysis, which has no corrected-bounds path | MEDIUM | Stated in D2; prediction-market-reviewer to rule |
| R8 | A-5 shares pure math (`quantile_density`, `location_correction`), so a bug there is invisible to parity | MEDIUM | S1 goldens and S2 analysis-parity tests are the control |
| R9 | The WS subscription cap is shared (10/conn). The fq YES+NO D+1 ladders could hit it | MEDIUM | Proof step 5 absence check; sharding already exists |
| R10 | Downstream timers misfire on the fq id (F9); "why no trades" is unanswerable | MEDIUM | S7 skips; S11 fq digest; SL-15 heartbeat installed in step 3b |
| R14 | NO-leg exposure misreconciled (the venue nets NO as short YES) | HIGH | Reused `position_leg`/`_map_position` chain; S6 test 9 checks CRH vs fq equivalence |
| R15 | The ruling file or artefact paths are tampered with, or escape | MEDIUM | S5 sha pin and `is_relative_to` containment |
| R11 | D+1 fills reconcile as `EXTERNAL` at the next boot (no `external_order_claims` for fq) | LOW | Family-agnostic; reconciliation still attributes. Optional follow-up |
| R12 | `trial_id_prefix` (`…/pm_us_crh_fq_v1/`) ≠ the latch key prefix `forecast_quantile_ladder/trial/` (`persistent_latch.py:68`) | LOW | Tally-only; no live effect |
| R13 | Concurrent agents in one tree | MEDIUM | One worktree per slice, PYTHONPATH, no stash, full gate after every merge |

## 7. Operator-only actions

- **The two caps (max daily budget, max per position)**, held by reference in `operator.env`. They were **already decided**: "Keep current caps". There is no action and no edit.
- Nothing else. The enable switch is a build-side unit constant set under the 2026-10-01 ruling, which is itself the operator's enablement decision. Activation, rollback, halts and every review are the coordinator's, per the standing grant.

---

## 8. Revision 1: peer review dispositions

Reviews: security 80, architecture 76, market-mechanics 76; all three returned REVISE.

| # | Item (severity, reviewer) | Disposition | Where |
|---|---|---|---|
| 1 | NO-leg reconciliation (HIGH, PM) | **Accepted.** The reused chain was verified with codegraph and cited with file:line and its existing tests in D8. A new go-live gate test drives an fq NO fill through the real exec client and asserts that wire price, echo, durable record, `DailySpendLedger` booking, boot position mapping (netPosition −1 → LONG 1 on `^no`) and native PnL equal the CRH run's. | §2 D8; S6 test 9; R14 |
| 2 | Boot-time D+1 readiness (HIGH, ARCH) | **Accepted.** composition no longer hard-raises. A native `clock.set_timer` poll re-resolves every 5 min for 60 min, then logs a terminal `FQ_D1_NOT_READY_TERMINAL` and sends a CRITICAL alert. B4 is kept. Stated limit: no mid-run instrument load, since the adapter has no `_request_instrument`; there is no patching. | S6; R4; §5 steps 3 and 5 |
| 3 | "Why no trades" (HIGH, ARCH) | **Accepted.** New S11: an in-process count aggregator over the `decision.py` taxonomy per station × side, a 15-min JSONL flush, and an fq branch of `decision_funnel_daily_digest.py` delivered via `alerts.env`, with a positive control. It is required before go-live. S7 no longer skips the digest. | S11; S7; §5 step 3b |
| 4 | Ruling pin (MED, SEC) | **Accepted.** The allowlist is a 3-tuple carrying ruling sha256 `11c69d13…711c1f`, verified in `live_orders_authorized`. S8 commits the ruling byte-unchanged. | D3; S5 test 5; S8 |
| 5 | shadow_only guard (MED, SEC) | **Accepted.** An AST scan permits exactly one non-True `shadow_only` expression (the gate output in the `app/trade.py` fq branch), pins the config default True, and has a positive control. | S5 test 11 |
| 6 | Parity vacuity (MED, ARCH) | **Accepted.** The guard requires at least 1 non-`NotExecutable`/`NotDPlus1` decision for YES and for NO on each path. If the S4a census proves the window has no NO-leg depth, the report states so and a synthetic NO parity case becomes a mandatory gate test. | S4a, S4b; §5 step 2 |
| 7 | SL-15 heartbeat (MED, ARCH) | **Accepted.** The units exist but are not installed (`is-enabled` → not-found). They are installed in §5 step 3b after `--positive-control all` fires through `alerts.env`, and step 3b gates S9. | S9; §5 step 3b |
| 8 | Stale worktrees (MED, ARCH) | **Accepted.** A binding merge rule says every slice rebases onto the merged HEAD, re-runs focused tests, merges ff-only, and runs the full gate after each merge. The serial order covers `strategy.py`, `decision.py` and `latch.py` (S3 → S6 → S10 → S2 → S11 → S4b). | §3 preamble; each slice; §4 |
| 9 | YES+NO same rung (MED, PM; coordinator decision) | **Accepted.** D10 / new S10: `Refuse("opposite_side_latched")`, durable through the side-keyed persistent latch, with a restart test. The batch parity path mirrors it independently. | D10; S10; S4b |
| 10 | Path containment (LOW, SEC) | **Accepted.** Manifest artefact paths must be relative, contain no `..`, and satisfy `resolve().is_relative_to(deploy/families)`. The ruling path is contained to `docs/evidence`. | S5 bullets and tests 6, 9 |
| 11 | Cardinality-1 (VERIFY, SEC) | **Verified, no slice needed.** A single settings slot (`settings.py:822`), a single manifest load (`trade.py:492`), and a single `if/elif` dispatch (`:539-759`). The v4 constructors are reachable only from the `continuous_rung_hold` branch (`:556-657` → `composition.py:592-739`). v4 is **not composed**, not merely vetoed. | D9 |
| 12 | Idle-timeout note (LOW, ARCH) | **Accepted.** The 60 s `idle_timeout_ms` applies to the venue WebSocket only, not to the HTTP-polling `NbmQuantileActor`. | D11 |
| — | Margin to LST midnight, flat 0.06 for D+1 | **Kept** (PM-confirmed). | D1; S3 |
