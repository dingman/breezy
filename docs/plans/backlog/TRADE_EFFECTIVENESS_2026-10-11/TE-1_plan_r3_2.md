# TE-1 plan r3.2 (coordinator pass over r3.1 per python confirm M-1 + notes): the bot reports its own live P&L for every family, including FQ

Status: r3.1. This is a targeted revision of r3. It applies items 1–13 of `reviews/TE-1-r3-merge.md`, which is binding. `reviews/TE-1-r2-merge.md` and `reviews/CORRECTION_2026-10-11_band_semantics.md` remain binding, as they were in r3. The r2→r3 change table is in `TE-1_plan_r3.md:9-36` and is not repeated here.

This was a read-only author pass. **It had no shell, so no Python ran and the fill store was not opened.** Every changed cite was re-checked this pass with Read, ripgrep or codegraph (projectPath `/home/jon/breezy`):
- `label_run.py:1-20` (the docstring is `:7`), `:684-697` (`UnitWiring` has 7 fields, `UnitFactory` returns `UnitWiring`), `:857-869` and `:875-895`;
- `tests/unit/test_aut2_label_run.py:581-591` (the only test hit for `not_wired`);
- `portfolio_roi_report.py:2217-2224`, `:4077-4090`, `:4216-4223` and `:4241`;
- `portfolio-roi-run.sh:103-115`;
- `closure_manifest.py:33-46`;
- `tests/unit/test_portfolio_roi_report.py:4708` and the schema-anchored `== 4` set.

The corrected targets come from `docs/evidence/TRADE_EFFECTIVENESS_2026-10-11.md:13-23`. Three independent read-only reproductions back them: the domain reviews `reviews/TE-1-r2-domain.md:4` and `reviews/TE-1-r3-domain.md:6-21`, and the Codex review `reviews/TE-1-r2-codex.md:6,13`. Stage 0 S0-1 and S0-5 still re-execute them before any WP brief.

Known stale coordinator text, outside TE-1 scope: `README.md:3,8-9` still quotes "2 wins, −4.63; FQ 0/25; NO-side 2/3". The coordinator corrects it when filing.

## Changes from r3
| Merge item / finding | Disposition in r3.1 |
|---|---|
| 1 / codex R3-F1, py H2 | S0-9 rewritten. The `== 4` pattern is now `== 4(?![0-9])` and is anchored to lines that also contain `schema_version` or `SCHEMA_VERSION`. **This pass found that the bare regex across `tests/` still returns about 150 unrelated hits** (for example `test_aut2_label_run.py:317`). The anchored form returns exactly the 10 P27 lines. `:4708` (`== 4000`) is listed as a known non-hit. `not_wired` is added to the patterns, with its 4 expected hits |
| 2 / py H1, arch N6 | P26 corrected: the `aut2.label` closure also contains `autonomy_sandbox.table`, `binds`, `registry.sites` and `alert_*`. R2 now has a general rule: any change to `table.py`, `sites.py`, `alert_*` or `closure_manifest` re-pins **both** producers. WP-C re-pins both. The dedupe move is credited to WP-A. Rollback carries both re-pins |
| 3 / py H2 | WP-A has a reviewed widening row for `test_aut2_label_run.py:581-591`. The test is renamed, not deleted. The fail-closed control stays through an unpinned producer, and the test asserts `reason=producer_unpinned`. The `label_run.py:7` docstring is updated. A measure-path twin is added |
| 4 / py M2, L1, arch N1 | The default factory is `factory(args) -> UnitWiring`, so the `UnitFactory` contract is unchanged. The stub returns a `UnitWiring` with sentinels for all 7 fields. One `_resolve_factory` helper serves both `main` (`:857`) and `_measure_main` (`:892`) |
| 5 / py M1, arch N2 | The import-linter forbidden contract and its pkgutil test are dropped. The AST guard is the only guard. It matches the fully qualified `breezy.analysis.labeling.accounting`, covers analysis-internal modules, and keeps its planted-mutation RED |
| 6 / arch N3 | `roi_accounting_status` is OK only if every fill is SETTLED_NWS_IMPLIED or EXIT. GATED_UNLABELLED_FQ is mapped explicitly. A derivation order and two tests are added (R6) |
| 7 / arch N4 | WP-E abort: the pre-WP-C wrapper exits **0** with the NO_INPUT journal token on the closed reason (`portfolio-roi-run.sh:103-109`), not 1. The abort sequence is now: disable, `mv` the outcomes dir, revert with both re-pins, unlink, `daemon-reload`, gate. P2 is corrected to match |
| 8 / arch N5 | S0-5 asserts `total_realised_pnl_all_settled(scored_trials)` (`:4241`) == SCORED-bucket Σ (−0.54). The WP-B LEGACY runtime check compares against the whole-store total only if that holds. Otherwise it compares against the SCORED-bucket subset |
| 9 / arch N7 | Risks: a future pre-epoch fill labelled before the CLI final gives UNATTRIBUTED, final, null P&L and a daily CRITICAL. It is known and outside the 34-fill goal |
| 10 / dom R3-2 | `PORTFOLIO_ROI_NO_INPUT` and `PORTFOLIO_ROI_LABEL_IDENTITY` are declared as **new** event names. E-TE1-b separates the alert from the wrapper journal token |
| 11 / dom R3-1 | S0-1: the store already holds `…^no.POLYMARKET_US` in `instrumentId` and camelCase `orderSide`. There is no normalisation step |
| 12 / py L2 | The subprocess import test passes `sys.executable` and `env` with `PYTHONPATH=<tree>/src` |
| 13 / codex S0-12 | New P36: `pm_us_crh_fq_v1` is non-retired; v4, cont and v2 are retired; so n=25. S0-12 re-confirms this |
| editorial | P28 restated in the terms `_gate_status_of` uses (`:4088-4089`): GATED_UNSETTLED_CAPITAL means the marker would be consumable if `pending` were 0 |

## Overview
TE-1 finishes F4 / AUT-2 r7 WP6-promote for pre-epoch fills. It also adds the accounting view that the planned path lacks.

**Option 1 is re-scoped. Option 2 is rejected:** it would rebuild the scorer, the C2 store, the marker, the coverage identity and `assert_ledger_partition` as a parallel architecture.

**Goal state:**
- Every one of the 34 ledger fills appears exactly once in a bot-written per-fill P&L table.
- The totals equal the corrected audit (4 wins / −2.63).
- A missing or overdue P&L alerts.

## Verified premises
r2 premises carried unchanged (citations in r2):
- P1 FQ skip: `score-live-trials-run.sh:185-189,202-217`
- P3 `not_wired`: `label_run.py:857-858,892-893`
- P4 `LabelRunDeps`: `label_core.py:113-131`
- P5 no epoch
- P6 pre-epoch bridge: `attribution.py:209-258`
- P7 memory gate
- P8 `deliver_with_proof`: `alert_proof.py:216`
- P9 no `breezy-autonomy-failed@`
- P10 FQ pre-epoch rows: `fq_scorer.py:352,421,451-452,457`
- P11 statistic ROI gap: `portfolio_roi_report.py:4068-4074,4109-4118,4216-4224`
- P12 there is no venue cross-check
- P13 the label bwrap row binds no `evidence/alerts`: `table.py:305-324`
- P14 lag rule: `label_core.py:124`; `verdicts.py:179-197`
- P15 `.storage_key` AST guard
- P16 staged units
- P17 pins: `pins.py:19-21`; `autonomy_health_cli.py:90-96`
- P18 the two fee-unreconciled fills are the two residuals
- P20 markers: `label_store.py:523-551`
- P22 deadline: `settlement_clock.py:36`; `sites.py:413`

**P2 (corrected): wrapper exits.**
- Closed reason `composition_kind_has_no_scorer`: the wrapper prints `PORTFOLIO ROI NO_INPUT -- upstream skipped: composition_kind_has_no_scorer` and **exits 0** without running the report (`portfolio-roi-run.sh:103-109`).
- Absent or unknown marker: exits 1 (`:112-115`).

**P19 is deleted:** the bot's scorer is right on both MIA cases.

| # | Premise | Evidence |
|---|---|---|
| P23 | Band rule. `gte{A}lt{B}` decodes to [A,B] **inclusive**. `lt{B}` decodes to (−∞, B−1]. `gte{A}` decodes to [A, ∞). `contains` is closed at both finite ends. `bucket_facts_from_instrument_id` is the bot's only band path, used by `fq_scorer._draft`, `legacy_crh_scorer._row`, the attribution bridge and the report | `symbology.py:483-500`; `weather_bucket_facts.py:64-73`; `instrument_facts.py:72-115` |
| P24 | `is_final_row` is: admissible ⇒ final; reason ∈ `_FINAL_REASONS` (including UNATTRIBUTED) ⇒ final; FEE_UNRECONCILED ⇒ final only after the horizon; WINDOW_INCOMPLETE ⇒ not final; otherwise final iff `settled_outcome is not None`. It lives in `analysis`, so `persistence` cannot call it | `completeness.py:52-62,82-93`; `pyproject.toml:152-160` |
| P25 | `LabelRunDeps.legacy_scorer_ids` defaults to `{LEGACY_SCORER_ID}`. `coverage_partition` takes the same parameter | `label_core.py:130`; `completeness.py:108`; `legacy_crh_scorer.py:38` |
| P26 | **Corrected.** The `aut6.health` closure contains `closure_manifest`, `registry.sites`, `runtime.alert_*` and `autonomy_sandbox.{binds,table,…}`, but not `label_store`. The `aut2.label` closure (219 modules, computed with `closure_from_grimp` in the python review) **also** contains `autonomy_sandbox.table`, `binds`, `registry.sites` and `alert_*`. It follows lazy imports, so `unit_wiring` and `unit_factory_default` are inside it. So a manifest regeneration changes `aut6.health`, and a change to `table.py`, `sites.py` or `alert_*` changes **both** shas | `closure_manifest.py:33-46`; `reviews/TE-1-r3-python.md:8,13` |
| P27 | Pin and closure tests that new entries break: `test_autonomy_closure.py:90`, and `test_autonomy_pins.py:101,599,688,745`. The schema lines (`(schema_version\|SCHEMA_VERSION).*== 4(?![0-9])`, re-run this pass) are all in `test_portfolio_roi_report.py`: `:283,423,2234,2295,4424,5165,5187,5909,5921,5922`. The frozenset is at `:5910` and the test name at `:5908`. `:4708` (`external_flow_cents == 4000`) is a non-hit | ripgrep, this pass |
| P28 | Label gate (`_gate_status_of`). A consumable marker gives `None`. A marker that would be consumable if `pending` were 0 gives GATED_UNSETTLED_CAPITAL. Anything else gives GATED_IDENTITY: absent, corrupt, stale (> `MARKER_STALE_H`) or FAILED_IDENTITY | `portfolio_roi_report.py:4077-4090`; `label_store.py:200-209` |
| P29 | `bucket_ledger_fills` partitions every fill into exactly one of SCORED / RESIDUAL / UNRECONCILED. The per-source totals are `realised_pnl_after_fees_total` (computed at `:4241` as `total_realised_pnl_all_settled(scored_trials)`, a **whole-store** sum) and `realised_pnl_residual_total` | `portfolio_roi_report.py:591-615,2576,2629,3812-3830,4241` |
| P30 | `LabelRow` carries `settlement_tmax_f` and `settled_outcome` | `label_store.py:165-166` |
| P31 | The lag verdict is built per **non-retired** family, from fills whose planned kind equals the family kind | `label_core.py:253-256,278-284` |
| P32 | The AUT-6 r15 NO_INPUT exit-0 rule appears at `:929`, `:1189`, `:1235` and `:1539`. `:1471` is the C2 boundary row | `AUT-6-drift-health_plan_r15.md` |
| P33 | The pinned producer set is `{"aut6.health"}` only | `pins.py:19-20` |
| P34 | `persistence` sits above `settlement` in the layers contract. `scored_trial_store` already imports `breezy.settlement.trial_scorer` | `pyproject.toml:78-99`; `scored_trial_store.py:49,172` |
| P35 | Rulings L-1, L-12, L-33, L-44, L-46 and L-55 exist with the meanings used here | `LESSONS.md:8,620,1282,1454,1497,1666` |
| P36 | **New.** `families()` observed read-only: `pm_us_crh_fq_v1` (forecast_quantile_ladder, retired=False); `pm_us_crh_v4` and `pm_us_crh_cont` (continuous_rung_hold, retired=True); `pm_us_crh_v2` (current_rung_hold, retired=True). Therefore LAG_BACKLOG n=25 | `reviews/TE-1-r3-codex.md:12-17` |
| P37 | **New.** `UnitWiring` is frozen with 7 fields: `deps`, `lock`, `unit_max_bytes`, `aut6`, `measured_peak_bytes`, `proof_window` and `slot_ns`. `UnitFactory = Callable[[Namespace], UnitWiring]`. `not_wired` appears only at `label_run.py:7,858,893` and `test_aut2_label_run.py:591` | `label_run.py:684-697,857-869,892-895`; ripgrep, this pass |

## Rulings (decided here; not deferred)
- **R1 Accounting set.**
  - NEW `breezy.analysis.labeling.accounting.accounting_rows(rows, *, legacy_scorer_ids)` selects a row when all of these hold:
    - `role is ENTRY`;
    - `scorer_id ∉ legacy_scorer_ids`;
    - `excluded_reason ∈ {UNATTRIBUTED, None}`;
    - `admissible`, or reason UNATTRIBUTED, or `settled_outcome is not None`.
  - The predicate is static: no `now_ns` and no deadline. The caller passes `LabelRunDeps`' default set (P25).
  - `test_accounting_predicate_equals_is_final_row_on_selected_set` checks equivalence with P24.
  - `persistence` gains nothing. `admissible_rows` stays the only statistics selector.
  - E-TE1-a narrows AUT-2 D3 to *statistics*, and the docstring at `label_store.py:409` says so. No verdict is built from accounting sums.
- **R2 PRODUCER pin.**
  - `aut2.label` is added to `PRODUCER_SOURCE_SHA256`, with a closure entry for `breezy.analysis.labeling.label_run` regenerated by `scripts/ci/regen_closure_manifest.py`.
  - `unit_wiring.producer_pin_state()` mirrors `autonomy_health_cli.py:90-96`. If `aut2.label` is unpinned, the default factory raises `ProducerUnpinned`. `main` and `_measure_main` both print `LABEL_OUTCOMES REFUSED reason=producer_unpinned` and exit 2.
  - **General re-pin rule (P26):**
    - A change to `table.py`, `sites.py`, any `alert_*` module, or a `closure_manifest` regeneration re-pins **both** `aut2.label` and `aut6.health`.
    - A change confined to the `aut2.label` closure (for example `label_store`, `label_run`, `unit_wiring`) re-pins `aut2.label` only.
  - **Choreography:** WP-A runs before WP-B, never in parallel. Each WP ends with one re-pin commit:
    - WP-A: `aut2.label` (new entry, `oldest_marker_ns`, the dedupe move) and `aut6.health` (the manifest regeneration);
    - WP-B: `aut2.label` (the `label_store.py:409` docstring);
    - WP-C: **`aut2.label` and `aut6.health`** (the `table.py` bind).
  - AUT-6 co-signs every `aut6.health` re-pin. Every rollback revert includes the matching re-pin commit, and both producers where both moved.
- **R3 C2 vs FEE_UNRECONCILED.**
  - The two residual fills are booked at the recorded fee with `fee_unverified=true`. The FU-3d delta stays in Markdown (`portfolio_roi_report.py:656-661,1233`).
  - A fee-unreconciled C2 row keeps `realized_pnl=None` (`fq_scorer.py:421`). It is UNSETTLED, alerted CRITICAL and never booked.
  - S0-4 proves there are zero such FQ fills, so FQ −2.17 is reproducible.
- **R4 Label lag (option a).**
  - `lag_start_ns(f)` is `verdicts.lag_start_ns(first_record_ts, deadline)`, except when `f.ts_event < activation_ns`. Then it is `max(rule, activation_ns)`, and the run prints `AUT2 LAG_BACKLOG n=<k>`.
  - `k` counts the lag-checked fills (P31) whose start was raised. Expected k=25 (P36).
  - `activation_ns` = `oldest_marker_ns()` over the **live** labels root. It parses through `_marker_ns` (`label_store.py:544-550`), so a corrupt name raises. If no marker exists, it is `deps.now_ns`.
- **R5 NO_INPUT.**
  - The report emits the **new** event `PORTFOLIO_ROI_NO_INPUT` and exits 1 only when a fill has status UNPRICED.
  - `LABELS_GATED` fills are excluded (R7).
  - An absent score-live-trials marker still exits 1 in the wrapper.
  - E-TE1-b amends AUT-6 r15 `:929,:1189,:1235,:1471,:1539`, with AUT-6 co-sign. It states this distinction: the alert `PORTFOLIO_ROI_NO_INPUT` (report, exit 1, UNPRICED only) is **not** the wrapper journal token `PORTFOLIO ROI NO_INPUT -- upstream skipped` (`portfolio-roi-run.sh:107`, exit 0). WP-C retires that token for the closed reason in favour of `PORTFOLIO ROI upstream skipped (composition_kind_has_no_scorer); running report`.
- **R6 Two ROI fields.**
  - `realised_pnl_c2_total` and `roi*` stay statistics-only.
  - `GATED_ACCOUNTING_ONLY` is added to `_LABEL_GATED_STATUSES` (`:2217`).
  - New fields: `realised_pnl_accounting_total` (always published), `roi_accounting` (null unless OK, following the "a gated report publishes no ROI" convention at `:2215`), and `roi_accounting_status ∈ {OK, GATED_IDENTITY, GATED_UNLABELLED_FQ, GATED_UNSETTLED_CAPITAL}`.
  - `roi_accounting_status` derivation; the first match wins:
    1. GATED_IDENTITY: `gate_status == GATED_IDENTITY`. Every `LABELS_GATED` fill implies this.
    2. GATED_UNLABELLED_FQ: `_unlabelled_fq_fills(buckets, labels) > 0` (`:4217`). An after-run fill with a consumable marker lands here, never OK.
    3. GATED_UNSETTLED_CAPITAL: `gate_status == GATED_UNSETTLED_CAPITAL`, or any fill's R9 status ∉ {SETTLED_NWS_IMPLIED, EXIT}.
    4. OK: only when every fill is SETTLED_NWS_IMPLIED or EXIT.
- **R7 Gate states (P28).**
  - **Gate open (`None`):** book every `accounting_rows` row.
  - **GATED_UNSETTLED_CAPITAL:** book every `accounting_rows` row, since the predicate admits only final rows. A fill without a final row takes its R9 status, so only that fill can become UNPRICED.
  - **GATED_IDENTITY:** book **no label-sourced row**. Every UNRECONCILED-bucket fill becomes `LABELS_GATED`. Emit one `PORTFOLIO_ROI_LABEL_IDENTITY` (new event name) CRITICAL and exit 1. Do not emit NO_INPUT.
  - LEGACY and RESIDUAL always book from the scored store, independent of labels. `fill_pnl` uses the fixed source order legacy → residual → C2.
- **R8 Row 9 / Needs.**
  - Need 8 (AUT-1b) feeds only POST_EPOCH rows, and every fill is pre-epoch (P5).
  - Need 3 (quote-tape ingest) does not apply, because the wiring passes `venue_settlement_tmax_f=None`. A test asserts that no quote-tape module is in the `aut2.label` closure manifest.
  - PROGRESS row 9 records WP6-promote DONE-by-TE-1. AUT-1b acceptance gains the POST_EPOCH switch test.
- **R9 `fill_pnl` status vocabulary.** The first match wins:
  1. `EXIT`: SELL (`completeness.py:96-97`). None are expected.
  2. `SETTLED_NWS_IMPLIED`: the source booked a non-null net (LEGACY; RESIDUAL with a resolved payout; or a C2 accounting row with non-null `realized_pnl`).
  3. `RESIDUAL_PENDING`: RESIDUAL bucket with an unresolved payout.
  4. `UNSETTLED`: a C2 accounting row with `realized_pnl=None`. It is counted in `n_null_pnl_final` and alerted CRITICAL.
  5. `LABELS_GATED`: GATED_IDENTITY and UNRECONCILED bucket.
  6. `OPEN`: no booked net and `now < settlement_deadline_ns(fill) + LABEL_LAG_MAX_H`.
  7. `UNPRICED`: no booked net, past that bound. This is the R5 trigger.

  `win` and `payout` are **null** unless the status is SETTLED_NWS_IMPLIED.
- **R10 `cli_final_check`.**
  - It applies to SETTLED_NWS_IMPLIED rows only; every other status is `UNAVAILABLE`.
  - It compares the **booked** tmax (`ScoredTrial.settlement_tmax_f`, the residual resolver's tmax, or `LabelRow.settlement_tmax_f`) with a fresh `read_climate_day_including_corrections` FINAL tmax.
  - Equal tmax gives AGREE. Different tmax gives DISAGREE plus a disclosure-only `cli_final_net` from `score_trial` with the same band function (P23). It is never booked.

## Stage 0 (read-only; any failure STOPs TE-1 back to the coordinator)
Rules for every step:
- Interpreter: `/home/jon/breezy/.venv/bin/python`. Never `uv`.
- `--basetemp` goes under `~/.cache`.
- The store is opened only via `sqlite3.connect("file:<path>?mode=ro", uri=True)` plus `PRAGMA query_only=ON`.

Steps:
- **S0-1.** Read `exec/polymarket_us/fill/*`.
  - Expect 34 rows, all `orderSide=BUY`, qty 1, Σ cost 6.36, Σ fee 0.27.
  - The store already holds the 3 NO legs as `…^no.POLYMARKET_US` in `instrumentId`, with camelCase `orderSide`. There is **no normalisation step**; read the fields as stored.
  - Score every fill **only** through `bucket_facts_from_instrument_id(id).contains(tmax)`, with `^no` inversion via `leg_of_symbol`, against the corrections-aware FINAL (S0-3's reader, not `truth_cli_finals.csv`).
  - Expect 4 wins / −2.63:
    - Sep: 9 fills / 2 wins / −0.46.
    - FQ: 25 / 2 / −2.17, with wins MIA 10-03 `gte86lt87` and MIA 10-05 `gte89lt90`.
    - NO side: 3 / 1 / +0.65.
  - No hand-rolled band anywhere. STOP otherwise.
- **S0-2.** All 25 FQ fills bridge to `pm_us_crh_fq_v1` alone (`latch_key_exists`, one manifest window).
- **S0-3.** Every station-day has a FINAL tmax from `read_climate_day_including_corrections`. Record `correction_flag` and the record ts. Expected: no `correction_flag` is true.
- **S0-4.** Every FQ fill has `fee_reconciled=True`.
  - **S0-4b:** exactly two non-FQ fills are unreconciled, SFO 09-11 and MIA 09-13, and both are residual trial ids.
- **S0-5.** The legacy store agrees with the corrections-aware CLI final for all 9 legacy fills:
  - Map the fills to `bucket_ledger_fills` buckets: 7 SCORED, 2 RESIDUAL.
  - For each, compare the frozen `ScoredTrial.settlement_tmax_f` (or the residual resolver's tmax, run read-only) with S0-3. Expect 9/9 AGREE.
  - Booked crh net must equal −0.46: SCORED −0.54, RESIDUAL +0.08.
  - **Whole-store total (merge 8):** compute `total_realised_pnl_all_settled(scored_trials)` (`portfolio_roi_report.py:4241`) and record whether it equals the SCORED-bucket Σ (−0.54). This record selects the WP-B LEGACY runtime-check form. A difference is not a STOP. Record which scored trials have no ledger fill.
  - **Positive controls:**
    - MIA 09-13 YES `gte91lt92`, tmax 92 ∈ [91,92], WIN +0.30.
    - MIA 09-15 NO `gte92lt93^no`, tmax 93 ∈ [92,93], NO **loses** −0.09.
  - **Trial-id agreement:** for each legacy fill, the latch `trial_id` (the `legacy_join` path) must equal the family-manifest attribution (P29).
  - Any mismatch or DISAGREE is a STOP, and the case goes to the domain reviewer.
- **S0-7.** R4 positive control: under the plain rule, a fixture first run gives `aut2.label_lag` FAIL; under R4 it gives PASS.
- **S0-8.** The wiring passes `venue_settlement_tmax_f=None`.
- **S0-9 (rewritten).** Run each pattern below with `/usr/bin/grep -rnP` (or `re` under the interpreter above) over `tests/`. Every hit must be in a widening list below, or in the known non-hits:

  | Pattern | Scope | Expected hits |
  |---|---|---|
  | `(schema_version\|SCHEMA_VERSION).*== 4(?![0-9])` | `tests/` | exactly the 10 P27 lines |
  | `frozenset\(\{1, 2, 3, 4\}\)` | `tests/` | `test_portfolio_roi_report.py:5910` |
  | `NO_INPUT -- upstream skipped` | `tests/` | the WP-C rows |
  | `\{"aut6\.health"\}` | `tests/` | WP-A rows |
  | `CLOSURE_MODULES` | `tests/` | WP-A rows |
  | `breezy-autonomy-failed@` | `tests/` | WP-C rows |
  | `\bnot_wired\b` (word-bounded; excludes `*_reader_not_wired` in `analysis/autonomy/evidence_row.py:216-219` and `tests/unit/autonomy/test_evidence_row.py:289`) | `tests/` **and** `src/` | `label_run.py:7,858,893` and `test_aut2_label_run.py:591` |

  - Known non-hit: `test_portfolio_roi_report.py:4708` (`external_flow_cents == 4000`).
  - Do **not** run a bare `== 4` or `== 4(?![0-9])` over `tests/`. It returns about 150 unrelated hits (for example `test_aut2_label_run.py:317,440`).
- **S0-11.** Find the exec-store source for the AMBIGUOUS no-fill intents (09-05 SFO, 09-23 MIA). If none exists, `n_ambiguous_no_fill=UNKNOWN`, never 0.
- **S0-12.** Print `families()` with `kind` and `retired`. Expect P36, so n=25. If it differs, restate the expected k before WP-A.

Expected values are written to the TE-1 scratch record before any WP brief.

## Work packages
Build route: Grok → Codex → Claude tdd-guide. Each brief restates:
- Nautilus is immutable; `allow_short=False`.
- No safety, settlement, contract or NO-SEND test is weakened (L-12: widen, never relax).
- No operator cap, enablement, arming or halt is touched.
- Format only your own files. `--basetemp` goes under `~/.cache`. Use `PYTHONPATH=<tree>/src` in worktrees.

**Order: WP-A → WP-B → WP-D → WP-C → WP-E.** This is strictly sequential (R2).

Stubs first: every new symbol lands with a typed, neutral body, so each RED fails on an assertion. Tests that pass before any change are labelled **regression pins** (L-33: they need mutation evidence, not RED).

### WP-A: production label wiring
- **Files:**
  - NEW `src/breezy/analysis/labeling/unit_wiring.py`:
    - `producer_pin_state` and `ProducerUnpinned`;
    - the R4 `lag_start_ns`;
    - the deadline from P22;
    - the planner, which reuses `attribute_fill`, `C1Epoch`, `latch_key_exists`, `settlement_source_for`, `deliver_with_proof` and `OFFLINE_PLUGINS`, and adds no attribution rule.
  - NEW `src/breezy/analysis/labeling/unit_factory_default.py`: `factory(args) -> UnitWiring`, conforming to the existing `UnitFactory` (P37); the contract is unchanged. It checks `producer_pin_state()` first, then composes `unit_wiring` with `StudiesFlock`.
    - Its **stub** returns `UnitWiring` with these sentinels:
      - `deps`: a `LabelRunDeps` with `deliver=lambda *a: None`, `producer_code_sha="0"*64` and a `plan` returning an empty plan;
      - `lock`: a sentinel `Lock` that never takes the studies flock;
      - `unit_max_bytes=0`;
      - `aut6`: `missing_aut6_reading()` from `memory_gate.py` (status `missing`; `Aut6Reading.status ∈ {pass, not_pass, missing, corrupt}`);
      - `measured_peak_bytes=None`;
      - `proof_window=None`;
      - `slot_ns=0`.
  - `label_run.py`:
    - New `_resolve_factory(unit_factory)` returns the injected factory unchanged, or lazy-imports `unit_factory_default.factory` inside the function. There is no module-level import, so no cycle.
    - Both `main` (`:857`) and `_measure_main` (`:892`) call it and map `ProducerUnpinned` to `LABEL_OUTCOMES REFUSED reason=producer_unpinned`, exit 2. The `not_wired` branches are removed.
    - The module docstring at `:5-7` is updated: the default mode composes production deps through `unit_factory_default`, and refuses `reason=producer_unpinned` while `aut2.label` is unpinned.
  - NEW `src/breezy/analysis/labeling/legacy_join.py`:
    - maps fill → latch `trial_id` → frozen ScoredTrial, producing `LegacyFillInput`; residuals get `scored=None`;
    - **refuses** (`LegacyAttributionDisagreement`, CRITICAL, exit 1) when the latch trial id differs from the family-manifest attribution.
  - MOVE `dedupe_scored_trials`, `_scored_trial_economic_fingerprint`, `_SCORED_TRIAL_ECONOMIC_FIELDS`, `DuplicateScoredTrialEconomicsMismatchError` and `_default_scored_trials_dir`:
    - from `portfolio_roi_report.py:1264-1356,3606`;
    - to NEW `src/breezy/persistence/scored_trial_dedupe.py` (P34);
    - the script re-exports every name.
  - `label_store.py`: `oldest_marker_ns` via `_marker_ns`.
  - `pins.py` and `closure_manifest.py` (regenerated). One re-pin commit covers `aut2.label` and `aut6.health` (R2), with AUT-6 co-sign.
- **Reviewed widenings (same WP, re-pin commit):**
  - `test_autonomy_pins.py:101` → `{"aut6.health","aut2.label"}`, plus a length-64 assertion.
  - `test_autonomy_closure.py:90` → both entries, keeping the `ClosureUnavailable` control.
  - `test_autonomy_pins.py:688,745` go green only on the regenerated manifest.
  - **`tests/unit/test_aut2_label_run.py:581-591`** (merge 3; renamed, never deleted):
    - `test_default_mode_without_a_deps_wiring_fails_closed` becomes `test_default_mode_with_an_unpinned_producer_fails_closed`.
    - It injects no factory and monkeypatches `unit_wiring.producer_pin_state` to unpinned (the factory must call it through the module attribute `unit_wiring.producer_pin_state`, never a from-import, or the monkeypatch is bypassed; state this in the WP-A brief).
    - It asserts `rc == 2`, `"LABEL_OUTCOMES REFUSED reason=producer_unpinned"` in stdout, and that nothing exists under `tmp_path / "d"`. This keeps the fail-closed control.
- **RED tests** (NEW `tests/unit/test_te1_label_wiring.py`; the failure mode under the stubs follows each name):
  - `test_planner_pre_epoch_fq_fill_bridges_to_v1`: empty plan.
  - `test_planner_legacy_crh_fill_joins_frozen_scored_trial`: no legacy input.
  - `test_planner_residual_fill_gets_null_pnl_legacy_row_not_missing`: `missing_label` = 1.
  - `test_planner_unbridgeable_fill_is_unresolved` (positive control).
  - `test_legacy_join_refuses_on_trial_id_disagreement`: the stub accepts.
  - `test_wiring_settlements_is_nws_cli_final_for_polymarket_us`
  - `test_wiring_deliver_is_deliver_with_proof`: sentinel lambda.
  - `test_wiring_memory_gate_holds_above_4gib_without_aut6_reading`
  - `test_wiring_proof_window_none_while_wp7_inactive`
  - `test_wiring_producer_sha_is_pinned_closure_sha`: sentinel `"0"*64`.
  - `test_factory_returns_unit_wiring_with_every_field_real`: the sentinels fail.
  - `test_unpinned_producer_refuses_with_exit_2` (positive control).
  - `test_measure_peak_with_unpinned_producer_fails_closed`: `_measure_main` goes through `_resolve_factory`.
  - `test_lag_backlog_fill_starts_at_first_activation`: FAILs under the plain rule.
  - `test_lag_post_activation_fill_still_lag_checked` (positive control).
  - `test_lag_anchor_ignores_measure_output_root_markers`
  - `test_oldest_marker_ns_raises_on_corrupt_name`
  - `test_lag_backlog_counts_only_non_retired_family_fills`
  - `test_main_under_unit_runs_production_factory`: `not_wired` today (L-55).
  - `test_label_run_unit_wiring_and_factory_import_standalone`: one subprocess per module, run with `sys.executable` and `env={**os.environ, "PYTHONPATH": "<tree>/src"}`, so it never checks the primary tree.
  - `test_no_leg_buy_pays_one_when_yes_false` (L-44): expectations from `bucket_facts_from_instrument_id`.
  - `test_aut2_label_closure_has_no_quote_tape_module`
  - `test_moved_dedupe_lives_in_persistence`: asserts `_prr.dedupe_scored_trials.__module__ == "breezy.persistence.scored_trial_dedupe"`. It is RED today.
  - The re-export identity check is a regression pin.
- **Acceptance:**
  - A 34-fill fixture gives LABELLED, `missing_label = unresolved = pending = 0` and `durable_fill_count = 34`. Every FQ row is UNATTRIBUTED with non-null `realized_pnl`.
  - S0-9's word-bounded `\bnot_wired\b` pattern returns zero hits in `src/` and `tests/`.
  - `cd <tree> && lint-imports` prints "N kept, 0 broken" (L-46).

### WP-B: accounting P&L, `fill_pnl` / `family_pnl`, alerts (the TE-1 delta)
- **Files:**
  - NEW `src/breezy/analysis/labeling/accounting.py`. It is pure and holds:
    - `accounting_rows` (R1);
    - `build_fill_pnl(buckets, scored, residual, accounting, gate_status, cli_check, now_ns, deadline_ns)`, which **consumes `bucket_ledger_fills` output** (P29): SCORED → LEGACY, RESIDUAL → RESIDUAL, UNRECONCILED → C2 lookup by `client_order_id`;
    - `family_pnl`, derived from `fill_pnl`;
    - R5, R6 (`roi_accounting_status`), R9 and R10.
  - `label_store.py:409`: D3 docstring only.
  - `portfolio_roi_report.py`:
    - `_LabelView.c2_rows` is unchanged;
    - `_LabelView.accounting_rows()` calls `accounting.accounting_rows(self.rows, legacy_scorer_ids=frozenset({LEGACY_SCORER_ID}))`;
    - the overlap guard (`:4206`) is widened to `{accounting ∪ admissible}`;
    - the R6 fields, `GATED_ACCOUNTING_ONLY`, `PORTFOLIO_ROI_SCHEMA_VERSION = 5` and known-set `{1..5}` (`:2208`); v5 strictly requires the new keys;
    - the events `PORTFOLIO_ROI_NO_INPUT` and `PORTFOLIO_ROI_LABEL_IDENTITY` are **new names**, emitted through the existing `sink` / `emit_alert`.
  - **Runtime assertions:**
    - LEGACY-source Σ (merge 8):
      - if S0-5 recorded store total == SCORED Σ, assert LEGACY Σ == `realised_pnl_after_fees_total` (`:2576`, computed at `:4241`);
      - otherwise assert LEGACY Σ == `total_realised_pnl_all_settled` over the SCORED-bucket trials only.
    - RESIDUAL-source Σ equals `realised_pnl_residual_total` (`:2629`).
    - A mismatch raises and exits 1.
  - **Guard (merge 5).** There is no import-linter contract. The only guard is an AST test over every `.py` under `src/` (analysis-internal modules included) and `scripts/`. It flags:
    - any `Import` or `ImportFrom` whose resolved fully qualified target is `breezy.analysis.labeling.accounting`, including `from breezy.analysis.labeling import accounting`;
    - any `Attribute` chain resolving to `breezy.analysis.labeling.accounting[.*]`.

    Allowed: `scripts/analysis/portfolio_roi_report.py` and `accounting.py` itself. The bare name `accounting` is **not** matched, because `nautilus_trader.accounting` exists. The guard is RED by mutation: a planted attribute access in an analysis module must fail.
  - Re-pin commit: `aut2.label`.
- **`fill_pnl` row** (PRIVATE 0600 JSON):
  - `fill_key`, `family_id`, `source ∈ {LEGACY, RESIDUAL, C2, NONE}`, `status` (R9).
  - `win`, `payout` (null unless SETTLED), `cost`, `fee`, `net`, `fee_unverified`, `booked_tmax_f`, `cli_final_check` (R10), `venue_check=UNAVAILABLE`.
  - Pre-epoch rows use `attribution_basis=pre_epoch_bridge`.
- **Disclosures:**
  - `n_fee_unverified`, `n_null_pnl_final`, `n_settlement_disagree`, `cli_final_net_total`, `n_entry_ask_unknown`, `n_labels_gated`;
  - `n_ambiguous_no_fill` (S0-11);
  - `venue_positions_reconciled=false`;
  - `fee_delta_disclosure_ref`, pointing at the FU-3d Markdown line.
- **Exit and alerts:**
  - `len(fill_pnl) != n_ledger_rows` → FILL_COUNT_MISMATCH, exit 1.
  - UNPRICED → `PORTFOLIO_ROI_NO_INPUT`, exit 1.
  - GATED_IDENTITY → `PORTFOLIO_ROI_LABEL_IDENTITY`, exit 1, with no NO_INPUT.
  - `n_null_pnl_final > 0` → CRITICAL.
  - DISAGREE → WARN, exit 0.
  - The journal line stays dimensionless.
- **RED tests** (NEW `tests/unit/test_te1_accounting.py`; `tests/unit/test_portfolio_roi_report.py` is extended):
  - **Selector:**
    - `test_accounting_rows_selects_entry_nonlegacy_final_unattributed_or_none`: the stub returns `()`.
    - `test_accounting_predicate_equals_is_final_row_on_selected_set`
    - `test_accounting_rows_excludes_each_final_non_accounting_reason` (×6)
    - `test_accounting_rows_excludes_legacy_scorer_rows`
    - `test_accounting_rows_excludes_window_incomplete_and_unsettled_none_reason`
  - **Guard:**
    - `test_accounting_guard_rejects_planted_attribute_access` (mutation)
    - `test_accounting_guard_rejects_from_labeling_import_accounting` (mutation)
    - `test_accounting_guard_ignores_nautilus_trader_accounting` (positive control)
  - **`fill_pnl` assembly:**
    - `test_fill_pnl_consumes_bucket_ledger_fills_one_row_per_fill`
    - `test_legacy_and_residual_sums_equal_existing_totals`, with its mismatch-raises positive control
    - `test_legacy_check_uses_scored_bucket_subset_when_store_has_extra_trials` (merge 8)
    - `test_legacy_fill_never_counted_twice_with_its_label_row`
    - `test_overlap_guard_covers_accounting_rows`
    - `test_family_pnl_sums_to_accounting_total`
  - **ROI fields:**
    - `test_roi_gated_accounting_only_when_pnl_outside_admissible`: OK today.
    - `test_roi_ok_when_all_pnl_admissible` (positive control)
    - `test_c2_total_stays_admissible_only` (regression pin)
    - `test_roi_accounting_status_ok_only_when_every_fill_settled_or_exit`: parametrised over the R9 statuses.
    - `test_roi_accounting_status_maps_gated_unlabelled_fq`: an after-run fill with a consumable marker gives GATED_UNLABELLED_FQ and `roi_accounting=None`.
  - **Gate states:**
    - `test_gated_unsettled_capital_books_final_rows_and_marks_only_pending_fill`
    - `test_gated_identity_books_no_label_row_alerts_identity_not_no_input`
    - `test_stale_marker_is_identity_not_unsettled_capital`
  - **Statuses and nulls:**
    - `test_each_status_trigger` (R9, parametrised over 7)
    - `test_win_payout_null_for_non_settled_rows`
    - `test_null_pnl_final_row_unsettled_alerted_not_zero`
    - `test_c2_fee_unreconciled_not_booked_and_alerted`
    - `test_residual_fee_unverified_booked_at_recorded_fee`
  - **Settlement check:**
    - `test_cli_final_check_compares_booked_tmax_with_fresh_read`
    - `test_settlement_disagree_flagged_and_warned`: a **synthetic** correction fixture only.
  - **Alerts and exits:**
    - `test_overdue_unpriced_fill_alerts_no_input_exit_1`
    - `test_pending_inside_deadline_does_not_alert` (positive control)
    - `test_fill_count_mismatch_alerts_exit_1`
  - **Band fixtures:** `test_band_fixture_reproduces_through_bucket_facts`.
    - Expected values come from `bucket_facts_from_instrument_id`, never from a hand recipe.
    - Rows: `gte91lt92` YES at 92 (WIN); `gte92lt93^no` at 93 (NO loses); `gte62lt63^no` at 64 (NO wins); `lt70` at 69 (WIN) and 70 (LOSS); `gte90` at 90 (WIN).
    - Totals equal Σ of the per-row values.
  - **Schema and output:**
    - `test_schema_v5_reader_accepts_1_to_5_and_rejects_v5_missing_keys`
    - `test_disclosures_ambiguous_unknown_not_zero_and_venue_positions_false`
    - `test_journal_line_dimensionless` (regression pin)
- **Reviewed widenings** in `tests/unit/test_portfolio_roi_report.py`:
  - `:283,423,2234,2295,4424,5165,5187,5909,5921,5922` change `4` to `5`.
  - `:5910` becomes `frozenset({1,2,3,4,5})`.
  - `:5908` is renamed `test_schema_version_is_five_and_every_prior_version_stays_readable`.
  - `:4708` is untouched.
- **Errata filed with the merge:**
  - E-TE1-a (D3, R1).
  - E-TE1-b (R5) amends AUT-6 r15 `:929,:1189,:1235,:1471,:1539`, with AUT-6 co-sign. It includes the alert-versus-journal-token distinction from R5.

### WP-C: promotion as one change (F4-open-items steps 1, 2, 3, 6)
- **Files:**
  - `git mv tests/fixtures/aut2_units/breezy-label-outcomes.{service,timer}` → `deploy/systemd/`, with `MemoryHigh`/`MemoryMax` from WP-D and `OnFailure=breezy-autonomy-failed@%n breezy-study-failed@%n`. The slot guard lands with it.
  - `table.py`: the label row binds `evidence/alerts` (P13). **Re-pin commit: `aut2.label` and `aut6.health`** (R2, P26), with AUT-6 co-sign.
  - `portfolio-roi-run.sh` (`:103-109`): the closed reason `composition_kind_has_no_scorer` now prints `PORTFOLIO ROI upstream skipped (composition_kind_has_no_scorer); running report` and falls through to the report. The old `NO_INPUT -- upstream skipped` token is retired. An absent or unknown marker still exits 1 (`:112-115`).
  - `deploy/systemd/README.md`. Score-live-trials files are **not** touched.
- **RED tests and reviewed widenings** (each keeps a positive control):
  - `tests/unit/test_portfolio_roi_run_no_input.py`: `:64-72` is replaced by `test_closed_skip_reason_runs_the_report`. `:74-82`, `:85-92`, `:95-102` and `:105-112` are kept as controls.
  - `tests/contract/test_autonomy_units_programme.py`: the `NO_INPUT -- upstream skipped` alternative is removed from `_BENIGN_SKIP` (`:38`), which is stricter. `:260-268` is replaced by `test_portfolio_roi_closed_skip_reason_has_no_exit_before_report`.
  - `tests/unit/test_aut2_units_deploy.py:175-185`: a reviewed row for the `evidence/alerts` bind.
  - `test_label_unit_deployed_with_dual_onfailure`
  - `test_label_unit_memory_max_from_measured_peak`
  - `test_no_deployed_file_references_slot_guard_run_until_promotion`, plus one reviewed row.
  - `tests/unit/test_portfolio_roi_deploy.py`: row confirmed.
  - `tests/unit/test_unit_execstart_imports.py`
  - `test_autonomy_pins.py:599,688,745` must go green for **both** producers on the WP-C re-pin.
- **Acceptance:** the gate reads EXIT=0, and the `NeedDaemonReload` preflight is clean before install.

### WP-D: sizing (coordinator; after WP-A, gates WP-C)
- Run `label_run --measure-peak --output-root <scratch>` in a transient `aut2-label-peak-<ts>` unit. `label_run.py:120-122` already accepts that leaf. The run goes through `_resolve_factory`, so `aut2.label` must already be pinned (WP-A).
- Conditions: a quiet window, `MemAvailable ≥ 16 GiB`, one heavy job at a time, `-p LimitNOFILE=524288`.
- Confirm the run is not inside a cgroup namespace (`label_run.py:598-613`).
- Commit `aut2_memory_peak/v1` with WP-C.
- **Above 4 GiB: STOP** (FQ-R19 hold).

### WP-E: activation (coordinator)
- **Window:** the same day, 04:30–13:55Z. This avoids 13:55–14:30Z, [16:30, 17:10)Z and [01:00, 04:30)Z.
- **Before starting:**
  - Re-check that `derived/label_outcomes` is absent.
  - Expect `systemd-analyze verify` to warn about the missing `breezy-autonomy-failed@` (P9). Only that warning is accepted.
- **Steps:**
  1. Run the full gate on the branch and read EXIT before merging.
  2. ff-merge.
  3. `ln -s` the label pair.
  4. `verify` plus the `NeedDaemonReload` preflight.
  5. `daemon-reload`.
  6. `enable --now breezy-label-outcomes.timer`.
  7. Run the L-1 positive controls.
- **Abort path (merge 7):** if any of steps 3–7 fails, run this sequence and finish **before 16:30Z**:
  1. `systemctl --user disable --now breezy-label-outcomes.timer`.
  2. `mv derived/label_outcomes` to a dated sibling. Never delete it.
  3. `git revert` WP-C together with its re-pin commit (both `aut2.label` and `aut6.health`).
  4. Unlink the label pair, preflight, `daemon-reload`.
  5. Run the full gate and read EXIT.

  The 17:40Z report then runs the **pre-WP-C** wrapper. On the closed skip reason it prints `PORTFOLIO ROI NO_INPUT -- upstream skipped: composition_kind_has_no_scorer` and **exits 0** without running the report (`portfolio-roi-run.sh:103-109`). That is the unchanged pre-TE-1 behaviour; an absent marker still exits 1. Never leave the merged wrapper live without the label unit.

## Focused gate (every slice; the full gate after every merge, EXIT read before any push)
- `scripts/ci/run_tests_no_egress.sh` with:
  - `tests/unit/test_te1_label_wiring.py` and `tests/unit/test_te1_accounting.py`;
  - `tests/unit/test_execution_egress_firewall_guard.py`;
  - every `tests/**/test_autonomy_*`, including `tests/unit/test_autonomy_pins.py`, `tests/unit/test_autonomy_closure.py` and `tests/contract/test_autonomy_units_programme.py`;
  - `tests/unit/test_aut2_attribution.py`, `tests/unit/test_aut2_label_store.py`, `tests/unit/test_aut2_label_run.py`, `tests/unit/test_aut2_units_deploy.py`, `tests/unit/test_aut2_completeness.py`;
  - `tests/unit/test_portfolio_roi_report.py`, `tests/unit/test_portfolio_roi_run_no_input.py`, `tests/unit/test_portfolio_roi_deploy.py`;
  - `tests/unit/test_runtime_import_isolation.py`, `tests/unit/test_run_tests_no_egress_phases.py`, `tests/unit/test_unit_execstart_imports.py`.
- Then `cd <tree> && lint-imports`, requiring "N kept, 0 broken".
- `scripts/ci/regen_closure_manifest.py --check` must pass.

## Dependencies
- **DONE:** F4 WP0–3, 5, 6-build, 8; F2 truth (LIVE); AUT-6 WP1.
- **Conditional:** `aut6.memory_budget`, only if the peak exceeds 4 GiB.
- **Co-sign:** AUT-6 for the `aut6.health` re-pins (WP-A, WP-C) and for E-TE1-b.
- **Not required (R8):** AUT-6 notifier, AUT-1b, AUT-5a, WP7, WP9 legs (INCONCLUSIVE, a known gap).

## Decision-time ask: a separate row, not TE-1
TE-1 reports only `n_entry_ask_unknown`. Add a cross-link on PROGRESS row 8 (AUT-1b). Open TE-4 only if AUT-1 r12 does not capture `ask_px` for FQ takes.

## Risks and mitigations
- **The legacy store is frozen while the sender is FQ** (P1). A future NWS correction could leave a legacy row stale.
  - This is hypothetical: S0-3 and S0-5 expect 9/9 AGREE and no `correction_flag` today.
  - Mitigation: `cli_final_check=DISAGREE` plus a WARN on every run. The coordinator then decides on TE-1b. Booked figures are never edited by hand.
- **Shared-closure re-pin churn** (P26). `aut2.label` and `aut6.health` share `autonomy_sandbox.table`, `binds`, `registry.sites` and `alert_*`. A one-sided re-pin leaves the other producer unpinned, so the label unit exits 2 `producer_unpinned` at activation.
  - Mitigation: the R2 general rule, strict WP order, one re-pin commit per WP, AUT-6 co-sign, and loud failures from `test_autonomy_pins.py:599,688,745`.
- **A future pre-epoch fill labelled before the CLI final** (known; outside the 34-fill goal). It is written UNATTRIBUTED and final with null P&L, permanently (`fq_scorer.py:451-452`; `completeness.py:87-88`). R9 marks it UNSETTLED, which raises a **daily CRITICAL** through `n_null_pnl_final`.
  - Mitigation: it is loud by design and never zero (R3, R9). The fix (re-label on CLI final) is the coordinator's call, filed as a follow-up row if it happens. It is not in TE-1.
- **Pre-epoch rows are final at first write** (P10). Mitigation: S0-3; null P&L is never zero (R3, R9).
- **Contract-test widenings**, including the renamed `not_wired` test. Mitigation: every row is listed, and each change is stricter or reviewed (L-12). The fail-closed control survives as `producer_unpinned`.
- **Event-name ambiguity.** The report alert and the old wrapper token both say NO_INPUT. Mitigation: R5 / E-TE1-b names them apart, and WP-C retires the wrapper token for the closed reason.
- **Symlinked units.** Mitigation: one window, preflight, and the WP-E abort path.
- **Memory.** Mitigation: the studies flock, a measured `MemoryMax`, and a snapshot exec read.

## Live proof (LIVE = the first scheduled success has been seen)
1. The first **timer-fired** `breezy-label-outcomes` run (14:15Z):
   - exits 0;
   - LABELLED, `durable_fill_count=34 pending=unresolved=missing_label=0`;
   - `aut2.label_lag` PASS for `pm_us_crh_fq_v1`, with `AUT2 LAG_BACKLOG n=25` (or the S0-12 restated k);
   - verdicts carry the `aut2.label` pin sha;
   - no `producer_unpinned` line.
2. The same day's **timer-fired** `breezy-portfolio-roi` run (17:40Z) exits 0. **Totals are at the recorded fee.** The artefact shows:
   - `n_ledger_rows=34`, `len(fill_pnl)=34`, fees 0.27, cost 6.36;
   - `cli_final_net_total` −2.63 with **4 wins** (MIA 09-13 YES, MDW 09-22 NO, MIA 10-03, MIA 10-05);
   - `pm_us_crh_fq_v1` −2.17 (2 wins) and crh −0.46 (2 wins);
   - `booked_total == cli_final_net_total == −2.63`;
   - `n_settlement_disagree=0`, with all 9 legacy rows and all 25 C2 rows `cli_final_check=AGREE`;
   - `n_fee_unverified=2` (both RESIDUAL), with the FU-3d Markdown delta cited from the `.md` artefact;
   - `n_null_pnl_final=0`, `n_labels_gated=0`;
   - `roi_status=GATED_ACCOUNTING_ONLY`, `roi_accounting_status=OK` (every fill SETTLED_NWS_IMPLIED).

   Any mismatch is a STOP and a diagnosis. Numbers are never tuned to match.
3. **Delivery drill:**
   - A `--drill` run against an isolated output root and an empty labels root gives `PORTFOLIO_ROI_LABEL_IDENTITY` (absent marker, R7), with a `deliver_with_proof` delivered record and `drill=true`.
   - A second drill uses a fixture with one overdue UNPRICED fill and a consumable marker. It gives `PORTFOLIO_ROI_NO_INPUT`, delivered.
4. **Second day:** the second scheduled pair also succeeds. Until then the status is "built, not LIVE".

## Rollback
1. `systemctl --user disable --now breezy-label-outcomes.timer`.
2. `mv derived/label_outcomes` to a dated sibling. Then `git revert` WP-C together with its re-pin commit (**both** `aut2.label` and `aut6.health`, AUT-6 co-sign). Unlink, preflight, `daemon-reload`, gate.
3. **Never revert WP-B alone.**
   - If WP-B must go: first `mv` the label store and marker dirs (`portfolio_roi_report.py:3613`) to a dated sibling. Never delete them.
   - Then revert WP-B with its `aut2.label` re-pin. The reader still accepts v1–v4.
4. A WP-A revert includes the `aut2.label` pin, the closure entry and the `aut6.health` re-pin, with AUT-6 co-sign. It restores the `not_wired` refusal and the original test name.
5. The exec store is never written.

## Explicit non-goals
- TE-2 (FQ 2/25 root cause) and TE-3 (NO-side hypothesis).
- Any re-arm, enablement, halt or cap change.
- Persisting the decision-time ask.
- WP9 legs and venue-position reads.
- The proof window and the WP7 flip.
- AUT-3/4/5 label consumption and any change to `admissible`.
- Kalshi.
- KILL and tally semantics; M1-v3 data.
- Exec client, Nautilus or NO-SEND changes.
- Re-scoring the frozen legacy store (TE-1b, only on a real DISAGREE).
- Re-labelling pre-epoch rows written before the CLI final (Risks).
- Any hand-rolled band rule.

## Success criteria
- [ ] S0-1..S0-12 recorded before the WP-A brief:
  - S0-1 and S0-5 reproduce 4 / −2.63 / FQ −2.17 / crh −0.46 through `bucket_facts_from_instrument_id`, with a `mode=ro` store;
  - the S0-5 store-total-versus-SCORED-Σ record exists;
  - S0-9 returns only listed hits.
- [ ] RED → GREEN kept for WP-A, WP-B and WP-C, with regression pins labelled. Full gate EXIT=0 after each merge. `lint-imports` "N kept, 0 broken". `regen --check` clean.
- [ ] Re-pin commits present per WP. WP-C re-pins both producers. AUT-6 co-sign obtained.
- [ ] Errata E-TE1-a and E-TE1-b filed. PROGRESS row 9 and AUT-1b acceptance updated.
- [ ] Live proof 1–4 observed and cited (artefact paths, journal lines, SHAs) by a reviewer who did not build it.

Relevant paths:
- /home/jon/breezy/src/breezy/analysis/labeling/{label_run,label_core,fq_scorer,legacy_crh_scorer,attribution,completeness,verdicts,constants,instrument_facts}.py
- /home/jon/breezy/src/breezy/adapters/polymarket_us/symbology.py
- /home/jon/breezy/src/breezy/domain/weather_bucket_facts.py
- /home/jon/breezy/src/breezy/persistence/autonomy/{label_store,pins,closure_manifest,closure}.py
- /home/jon/breezy/src/breezy/persistence/scored_trial_store.py
- /home/jon/breezy/src/breezy/runtime/autonomy_health_cli.py
- /home/jon/breezy/src/breezy/runtime/autonomy_sandbox/table.py
- /home/jon/breezy/scripts/analysis/portfolio_roi_report.py
- /home/jon/breezy/deploy/systemd/portfolio-roi-run.sh
- /home/jon/breezy/tests/unit/{test_autonomy_pins,test_autonomy_closure,test_portfolio_roi_report,test_portfolio_roi_run_no_input,test_aut2_label_run}.py
- /home/jon/breezy/tests/contract/test_autonomy_units_programme.py
- /home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/AUT-6-drift-health_plan_r15.md
- /home/jon/breezy/docs/evidence/TRADE_EFFECTIVENESS_2026-10-11.md

## Changes from r3.1 (coordinator pass r3.2)
| Source | Disposition |
|---|---|
| r3.1 python M-1 (MED) | S0-9 `not_wired` pattern word-bounded (`\bnot_wired\b`). The bare pattern also matched `*_reader_not_wired` (5 extra hits), so WP-A acceptance could never pass. |
| r3.1 python note (aut6) | Sentinel is `missing_aut6_reading()`. |
| r3.1 python note (monkeypatch) | The factory calls `unit_wiring.producer_pin_state` through the module attribute, so the renamed fail-closed test's monkeypatch takes effect. |
