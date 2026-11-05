# EDGE-4 — Live-feed / archive-table calibration parity (observability, not a pricing fix)

Scope: DESIGN ONLY, read-only against /home/jon/breezy. CODEGRAPH_USED: yes
(`decision.py`, `archive_table.py`, `running_extreme.py`, `offer_tape.py`
verified verbatim, current on-disk). Brief: EDGE-4, HIGH lever, live refuses
83-88% of decisions because the frozen `p_hold` archive was calibrated on
tenths-°C METAR with no ambiguity gate, while the live feed is ~93%
5-minute integer-°C.

## 0. Headline finding — read this before the rest

**No serve-side parity fix that changes what prices a trade is compatible
with Ruling A1 AND survives the evidence already in this repo.** Every route
has already been tried, independently, and closed:

1. **Recalibrate on the gate-pass subsample** (any resolution) — ruled an
   invalid COLLIDER by A1 §3.3/§4 and excluded again by AUD-18 §5. 79/240
   cells sit at p-hat exactly 1.0, n as low as 57, below the corpus's own
   `N_MIN=90` (`docs/evidence/DECISION_FUNNEL_2026-09-20.md:434-435,491-495`).
2. **Reconstruct a finer live feed** (METAR-only R(t), IEM `asos1min.py`,
   IEM/MADIS 5-min) — all three REJECTED on measurement, not opinion:
   `docs/evidence/DECISION_FUNNEL_2026-09-20.md:583-630` ("Consolidated:
   every identified fix is now closed" — table, options A/B/C). Even at zero
   lag a reconstructed tenths feed buys ~11-15 points of resolution and the
   MAJORITY of decision instants still refuse (55.8%→60.2% across L=0-60min
   vs a 70.7% NWS-only baseline, n=71 ladder-measured station-days).
3. **A new, non-P_HOLD, UNCONDITIONAL per-rung model at the live feed's own
   (integer-°C, interval) resolution** — this is the one candidate that is
   methodologically COMPATIBLE with A1 (no gate-pass conditioning: the
   denominator is every in-window row, ambiguous or not). It has already
   been BUILT and adversarially reviewed three rounds
   (`docs/plans/BAND_DECIDER_pm_us_crh_band_v1_Rev4_2026-09-17.md`) and its
   own Stage 0b go/no-go gate **FAILED** in the one bucket that matters —
   the market already prices integer-°C ambiguity as well as a climatological
   band model in the informative ask range:
   `docs/evidence/BAND_DECIDER_STAGE0B_SCREEN_2026-09-17.md:34` — ask
   `0.25-0.75`, n=3355, 32.46% positive margin (need ≥50%), median margin
   **-0.2993** (need ≥+0.03). Memory `band-decider-stopped-at-stage0b`
   confirms calibration itself was fine (LOYO Brier 0.227); the model was
   not wrong, it was **uninformative where the market is efficient**.

**So this plan does NOT propose a fourth pricing model.** It proposes the
one thing the CRITICAL constraint's own escape clause asks for: **a new,
non-P_HOLD estimator whose inputs match the live feed's resolution, built
from the population the live decision path actually draws from (the bot's
own captured tape since 2026-08-30, not an offline IEM/CLI archive), wired
to NOTHING in the trading path, delivered only as a citable input to
AUD-18's already-registered "archive-table recalibration" hypothesis
(`docs/plans/backlog/AUDIT_2026-09-21/AUD-18-strategy-design-backtest-iterate-programme.md`
§6.3, currently `PARKED_INSUFFICIENT_DATA`) and to EDGE-5.** Its job is
observability and evidence-accumulation, not edge-seeking — the edge
question on this exact shape of model is already closed by item 3 above.

## 1. Goal & acceptance criteria

**Goal.** Stop citing a corpus-population estimate (`P_HOLD_LOWER/UPPER`)
as if it describes the live-resolution decision population, replace today's
one-off manual funnel studies with a durable, scheduled, per-reason /
per-stratum refusal decomposition built from the REAL post-2026-08-30 tape,
and produce (or honestly refuse, per AUD-18's own §6.3 disposition) a
calibration report for a non-P_HOLD, non-collider, native-resolution
estimator — as an input artifact, never a trading change.

1. **Refusal decomposition, scheduled.** `decision_funnel_daily_digest.py`
   emits a per-`REFUSAL_REASONS`-member, per-stratum
   (`station × hour_lst × width_code × m_code`) breakdown for every
   climate-day, on its existing timer, with zero manual invocation. RED
   test asserts the breakdown sums to the digest's own funnel total
   (no reason double-counted or dropped) on a committed fixture.
2. **Scoring-coverage change (measured in the offline study, not live).**
   Today, a decision frame gets a defined `p_bound` only on gate-pass
   (`spans()==False`) rows — ~12-17% of frames live, 21.2% modelled
   (`DECISION_FUNNEL_2026-09-20.md:434`). The new unconditional estimator
   assigns a defined `rung_distribution` to every admissible frame
   regardless of `observation_ambiguous`/`illegal_cell`. Acceptance: on the
   committed real-tape fixture, "shadow-scored fraction" (frames with a
   defined estimate) is reported next to today's "gate-pass fraction"
   (frames reaching `_finalize_take`'s lookup) and the two numbers differ
   measurably — this is a coverage/observability metric, explicitly
   labelled NOT a would-trade rate.
3. **Calibration on held-out station-days.** Brier score and CITL (mean
   p vs mean y) per stratum, split by ask-price bucket (`<0.25`,
   `0.25-0.75`, `>0.75`) exactly as Stage 0b did, on a station-year (or, if
   insufficient span, a leave-one-station-out) holdout of the REAL tape
   corpus. Report every cell honestly, including `N < N_MIN=90` cells
   marked `uncalibrated`, never a default guess.
4. **The Stage 0b adverse-selection gate re-run on the CORRECTED corpus.**
   Same go/no-go rule the Band Decider used (≥20 rows, ≥50% positive
   margin, median ≥0.03, gate binds on the `0.25-0.75` bucket only) — but
   this time on the bot's own captured tape population, not an offline IEM
   archive. A repeat FAIL is an accepted, valuable outcome: a fourth,
   most-authoritative closure of "a coarse/climatological model beats the
   market here," ending the question on the best available corpus. A PASS
   is not a licence to trade — it is handed to AUD-18 §6.3 as new evidence
   for the archive-table-recalibration hypothesis, gated by AUD-18's own
   `MAX_HYPOTHESES`/MDE/pooled-P&L-veto machinery before it can reach
   `CONFIRMED`.
5. **No live-path change.** `src/breezy/strategy/current_rung_hold/{decision,strategy,tick_eval,archive_table}.py`
   are untouched; an import-linter forbidden-module test pins that the new
   module is never imported by them.

## 2. Evidence / root cause, file:line

- **The skew.** `src/breezy/strategy/current_rung_hold/archive_table.py:37-38`
  (`CORPUS_SHA256`, `STUDY_GIT_SHA`) freezes `P_HOLD_LOWER`/`P_HOLD_UPPER`
  (`:40-286+`) built from tenths-°C METAR with `is_complete_day`-only
  filtering (no ambiguity gate: `RunningMax.spans` is never called by the
  generator). Live reads the SAME table at
  `decision.py:108` (`from breezy.strategy.current_rung_hold.archive_table
  import P_HOLD_LOWER, P_HOLD_UPPER`) but refuses first:
  `evaluate_decision` (`decision.py:338-384`) calls `running_max.spans(inputs.ladder)`
  at `:355` and returns `Refuse("observation_ambiguous")` at `:356` before
  ever reading the table; `_is_legal_cell` (`:303-314`) refuses a second
  population at `:362-363`.
- **The measured refusal.** `DECISION_FUNNEL_2026-09-20.md:356-357`:
  51,398 decisions, **observation_ambiguous 42,820 (83%)**, **illegal_cell
  8,578 (17%)** — zero reach pricing. `:11-12`: rung resolved only 12% of
  rows (modelled 0.5%); cell legal on **0** rows either arm.
  `RunningMax.spans` itself: `running_extreme.py:172-202`, closed-closed
  interval containment, fails closed (`:183-186`) on either ambiguity or an
  out-of-ladder endpoint.
- **The collider.** `DECISION_FUNNEL_2026-09-20.md:491-495`: 79/240 cells
  at p-hat exactly 1.0 on the gate-pass subsample, n below `N_MIN=90`;
  `RULING_A1_pm_us_crh_v4_disposition_2026-09-21.md` §3.3 (evidence item 3)
  and §4 rule this invalid, restated by AUD-18 §5 as a standing exclusion.
- **Every reconstruction route closed.** `DECISION_FUNNEL_2026-09-20.md:583-630`,
  options A (METAR-only R(t), resolves onto a demonstrably-wrong rung
  19.1% of the time), B (IEM `asos1min.py`, whole-°F, no metar column), C
  (IEM/MADIS 5-min, whole-°C, majority still refuse at L=0) — all REJECTED.
  Memory `no-live-subdegree-observation-source`, `archive-table-train-serve-skew`
  corroborate.
- **The one compatible-but-already-failed candidate.**
  `docs/plans/BAND_DECIDER_pm_us_crh_band_v1_Rev4_2026-09-17.md` §3 item 1
  (unconditional `p_bound_band`, denominator = all in-window rows including
  outside-band) is exactly the non-collider shape A1 permits.
  `docs/evidence/BAND_DECIDER_STAGE0B_SCREEN_2026-09-17.md:29-37` is the
  STOP: gate FAILS in the `0.25-0.75` bucket. That study's corpus was the
  offline IEM 1-min archive + CLI `settled_f` (`:6-25`), NOT the bot's own
  captured tape — the gap this plan closes is corpus provenance, not
  methodology.
- **AUD-18 already tracks this hypothesis, data-blocked, not closed.**
  `AUD-18-strategy-design-backtest-iterate-programme.md` §6.3: "`pm_us_crh_v4`
  archive-table recalibration... BLOCKED on data, not closed... the live
  decision path needs interval-aware venue-priced ladders that only exist
  from tape start (2026-08-30) forward... Registered
  `PARKED_INSUFFICIENT_DATA`; re-triaged automatically... as AUD-09a's
  census accumulates SUFFICIENT station-days." This plan builds the
  instrument that measurement needs, sourced correctly.
- **The tape already carries the needed fields.**
  `src/breezy/strategy/current_rung_hold/offer_tape.py:213-267`
  (`OfferTapeRecord.to_dict`) records `running_max_lower`,
  `running_max_upper`, `running_max_exact`, `reason`, `hour_lst`,
  `width_code`, `m_code`, `ask`, `p_bound`, `break_even` on the existing
  quote-tape JSONL under `~/.local/share/breezy/catalog/quote_tape/decisions/`
  — the same source `DECISION_FUNNEL_2026-09-20.md` itself reads. **Open
  verification (Stage 0, §7):** confirm `running_max_lower/upper` are
  populated on `observation_ambiguous`/`illegal_cell` rows and not only on
  `Take`/`edge_below_break_even` rows — `Refuse.p_bound`/`break_even` are
  documented unset except on `edge_below_break_even` (`decision.py:238-244`),
  but the tape-write call site is a distinct layer from `Refuse` itself and
  was not read this session. If unpopulated, this plan's Stage 0 fallback is
  to widen the tape write (additive field only, same shape as the 11
  GAP-fix keys already added) rather than invent a second capture path.
- **AUD-18's own ledger is not yet accepting registrations.**
  `docs/core/PROGRESS.md:53`: "AUD-18 | MED | (b) schema-v2 stratum/draw
  binding BLOCKED until a look-taking registration or REPLAY_VALIDITY
  flip." This plan's output queues as a future intake, not an immediate one.

## 3. Options & trade-offs

| Option | Compatible with A1 §3.3/§4? | Status | Verdict |
|---|---|---|---|
| Recalibrate P_HOLD on gate-pass subsample (any resolution) | No — collider | Ruled invalid | REJECTED, do not build |
| Degrade archive to integer-°C, but still condition calibration on gate-pass/`spans()==False` | No — same collider, resolution is irrelevant to the conditioning defect | N/A | REJECTED, do not build |
| Reconstruct a finer live feed (METAR-only, IEM 1-min, IEM/MADIS 5-min) | Compatible in form, but empirically dead | REJECTED on measurement (§2) | Do not re-attempt |
| Unconditional per-rung model at native resolution, offline IEM/CLI corpus | Compatible | Built, STOPPED at Stage 0b | Do not rebuild verbatim on the same corpus |
| **Unconditional per-rung model at native resolution, bot's OWN captured tape corpus since 2026-08-30** | **Compatible** | **Not yet attempted on this corpus** | **ADOPTED — this plan** |
| Condition Band Decider v2 on forecast/real-time features | N/A | Forecast-edge is CLOSED TERMINAL (`forecast-edge-closed-pmus-rungs`); any forecast covariate re-opens that closed hunt | REJECTED by the brief's own instruction |

**Why the adopted option is different, not a retry.** The population the
live decision path actually observes (NWS 5-min feed via
`NwsObservationActor`, specific station set, specific gaps/lag) is not
identical to either the tenths-METAR study corpus (2021-2025, the skew this
item names) or the offline IEM 1-min archive Band Decider used (a different
external source with its own coverage holes, `BAND_DECIDER_STAGE0B_SCREEN_2026-09-17.md:6-14`).
Training and scoring on the SAME tape the live strategy reads removes the
population-mismatch mechanism named in memory
`archive-table-train-serve-skew` at its root, rather than approximating it
from a different feed. This is new evidence, not a re-litigation.

**Trade-off accepted:** the real-tape corpus is small (AUD-09b census:
127 station×climate-day rows, 87 SUFFICIENT, since tape start
2026-08-30 — `docs/evidence/AUD-09b_replay_sufficiency_v2_census_2026-09-25.md`).
This plan's own Stage 0b-style gate needs `N≥90` per scored cell and ≥20
rows in the mid ask-bucket; today's corpus will very likely fail on sample
size alone, independent of any edge question. That is treated as
`PARKED_INSUFFICIENT_DATA` (AUD-18's own vocabulary), not a defect — the
pipeline is built once and re-triages automatically as AUD-09a's census
grows, exactly as AUD-18 §6.3 already specifies for this hypothesis class.

## 4. Architecture & data flow

**Untouched (verified, no edit):** `NwsObservationActor`, `RunningMax`
(`running_extreme.py`), `evaluate_decision`/`_finalize_take`/`_is_legal_cell`
(`decision.py`), `archive_table.py`, `OfferTapeRecord` schema (read-only
consumer). No new market-data subscription, no new live capture path (§2's
open verification may add one additive tape field, nothing else).

**New, additive, analysis-only:**
1. `src/breezy/domain/live_population_parity.py` (pure, new). Frozen
   `ObservedInterval(lower_f, upper_f, exact_f)` and
   `Covariates(station, season, hour_lst, width_code, m_code)` — reuses the
   already-reviewed Band Decider covariate shape, keyed exactly like
   `archive_table.py`'s cell key so the two are directly comparable.
   `rung_distribution(interval, covariates, table) -> Mapping[int, Decimal]`,
   UNCONDITIONAL per rung (denominator = every admissible frame for the
   cell, ambiguous or legal-illegal alike), missing-cell → an
   `"uncalibrated"` sentinel, never a default. **Deliberately does not
   import `decision.py`/`running_extreme.py` internals** — a small
   (~10-line) rung-containment helper is re-implemented here rather than
   imported, the same intentional-independence choice `decision.py:287-300`'s
   own docstring already documents for its relationship to
   `RunningMax.spans`'s private `_rung_index` ("mirrors... exactly"): this
   keeps the observability module structurally unable to create a runtime
   dependency edge into the pricing path.
2. `scripts/analysis/live_population_parity_study.py` (new, ≤800 lines,
   split rather than grow past that, mirroring the `mb_current_rung_edge_study.py`
   precedent AUD-18 §6.2 already cites for line-count discipline). Reads
   `OfferTapeRecord` rows from
   `~/.local/share/breezy/catalog/quote_tape/decisions/*.jsonl` (all rows,
   every `reason`, not filtered to gate-pass) since climate-day
   2026-08-30, joins to CLI `settled_f` via the existing
   `finals_by_city`/`fetch_text_cached`/`cache_path_for_url` machinery
   (`settlement_alignment_study.py:359-371`, precedent already used by
   `BAND_DECIDER_STAGE0B_SCREEN_2026-09-17.md`'s own reproduce script).
   Builds (a) the frozen calibration table via `rung_distribution`, (b) the
   Stage-0b-style ask-bucket adverse-selection screen, (c) the Brier/CITL
   holdout report. Outputs: a generated frozen Python module (same shape as
   `archive_table.py` — `CORPUS_SHA256`/`STUDY_GIT_SHA`, sorted dict
   literal, `Decimal("...")`), loaded only by path
   (`hourly_ask_relative_edge.py:583-604`'s `load_p_bound_table` pattern —
   never importable as if it were the shipped selector), plus a markdown
   evidence doc under `docs/evidence/`.
3. `scripts/analysis/decision_funnel_daily_digest.py` — additive extension
   only (existing file, `_EVENT`/`_SITE` constants at `:73-74`, existing
   `DecisionTapeNotFound` class at `:179-184`): a new per-`REFUSAL_REASONS`
   × stratum section in the digest's output, reusing the digest's own
   existing tape-read path. No change to `_missing_tape_detail` or the halt
   distinction it already makes (`:757-769`).
4. Import-linter: new `type='forbidden'` contract,
   `source_modules=[current_rung_hold.decision, current_rung_hold.strategy,
   current_rung_hold.tick_eval, current_rung_hold.archive_table]`,
   `forbidden_modules=[live_population_parity]` (both the domain module and
   the study script) — reverse direction (study reads tape/settlement,
   never the strategy package) is allowed and unrestricted.

**Data flow:** offer-tape JSONL (all reasons) + CLI settled_f (existing
fetch/cache) → `live_population_parity_study.py` → generated frozen table +
evidence doc + adverse-selection verdict → `docs/evidence/` (citable) →
consumed BY REFERENCE (id only) by AUD-18 §6.3's archive-table
recalibration hypothesis row and by EDGE-5. Nothing flows back into the
live decision path.

## 5. File-by-file plan

- NEW `src/breezy/domain/live_population_parity.py` — pure module, §4 item 1.
- NEW `tests/unit/test_live_population_parity.py` — RED list §6.
- NEW `scripts/analysis/live_population_parity_study.py` — §4 item 2.
- NEW `tests/unit/test_live_population_parity_study.py` — deterministic
  fixture-driven tests, no network, inside `run_tests_no_egress.sh`.
- NEW committed fixture `tests/fixtures/live_population_parity/` — a
  trimmed real offer-tape slice (all reasons, one station, a few
  climate-days since 2026-08-30) + matching CLI settlement fixture.
- MODIFIED `scripts/analysis/decision_funnel_daily_digest.py` — additive
  section only, §4 item 3.
- MODIFIED `tests/unit/test_decision_funnel_daily_digest.py` (or the
  digest's existing test module — locate exact name at build time) —
  additive test for the new section.
- MODIFIED import-linter config (`.importlinter` or equivalent — locate
  exact path at build time, same file Band Decider Rev4 §5/T9 targeted) —
  new forbidden contract, §4 item 4.
- NEW `docs/evidence/EDGE-4_live_population_parity_<run-date>.md` — the
  study's own output report (Stage 0b-style verdict table + calibration
  report), written by the study script's build agent after a real run, not
  by this planning session.

**Untouched, verified by read:** `src/breezy/strategy/current_rung_hold/decision.py`,
`archive_table.py`, `strategy.py`, `tick_eval.py`,
`src/breezy/strategy/weather_common/running_extreme.py`,
`src/breezy/strategy/current_rung_hold/offer_tape.py` (read-only consumer;
schema widened only if Stage 0 verification (§2) finds
`running_max_lower/upper` unpopulated on refused rows, and then only by one
additive field with a default, same shape as the existing 11 GAP-fix keys).

## 6. Test strategy (RED first, named)

- **T0 (Stage 0 verification, precedes all code):**
  `test_offer_tape_running_max_fields_are_populated_on_observation_ambiguous_rows`
  — read a real captured JSONL slice, assert `running_max_lower`/`upper`
  are non-null on `reason=="observation_ambiguous"` rows. FAIL here forks
  the plan to the tape-widening fallback (§2) before Stage 1 proceeds.
- T1 `test_rung_distribution_is_unconditional_outside_band_mass_included`
  — mirrors Band Decider T11: a synthetic cell with 10% outside-band rows
  still nets out that mass; candidate-rung probabilities sum to ≤0.90, not
  renormalized to 1.0.
- T2 `test_rung_distribution_refuses_missing_cell_with_uncalibrated_sentinel_not_a_default`.
- T3 `test_ambiguity_classification_agrees_with_running_max_spans_on_committed_fixture`
  — the parity check: for every fixture row, this module's own interval
  reconstruction from the SAME `running_max_lower/upper/exact` tape fields
  classifies ambiguous-vs-resolved identically to what `RunningMax.spans`
  already decided live (cross-checked against the tape's own `reason`
  field). This is the literal "calibration parity" regression guard.
- T4 `test_study_output_is_deterministic_given_the_same_fixture_inputs`.
- T5 `test_import_linter_forbids_current_rung_hold_decision_strategy_tick_eval_archive_table_from_importing_live_population_parity`.
- T6 `test_calibration_denominator_is_every_admissible_row_not_gate_pass_only`
  — regression guard directly against the A1 §3.3 collider: constructs a
  cell where gate-pass rows are a biased subset of all rows and asserts the
  computed probability differs from (and is not silently equal to) the
  gate-pass-only estimate.
- T7 `test_adverse_selection_screen_reports_all_three_ask_buckets_and_gates_on_mid_bucket_only`
  — same rule as Stage 0b: `<0.25`/`0.25-0.75`/`>0.75`, ≥20 rows, ≥50%
  positive margin, median ≥0.03, gate binds on `0.25-0.75` alone; pooled
  numbers never substitute.
- T8 `test_cells_below_n_min_90_report_uncalibrated_never_a_wilson_point_estimate_alone`.
- T9 `test_digest_refusal_reason_breakdown_sums_to_the_digest_own_funnel_total`
  — for `decision_funnel_daily_digest.py`'s new section, on a committed
  fixture day.
- T10 (golden/fixture, committed, no network, runs inside
  `run_tests_no_egress.sh`): the trimmed real offer-tape + CLI-settlement
  fixture end-to-end through the study script; asserts the printed
  scoring-coverage number (goal §1.2) and the calibration report shape,
  not a specific pass/fail edge verdict (that depends on real data volume
  and must not be hardcoded).

## 7. Execution order & parallelism

- **Stage 0 (sequential, gates everything):** T0 verification against a
  real tape sample; confirm AUD-09b census station-day count and per-stratum
  cell coverage since 2026-08-30 (re-run or read
  `replay_sufficiency.jsonl`). STOP-and-report is a valid, complete outcome
  if coverage is too thin for even a Stage-2-preview-style report — this
  mirrors AUD-18 §6.3's own `PARKED_INSUFFICIENT_DATA` disposition and is
  not a plan failure.
- **Stage 1 (parallel, only if Stage 0 does not fork to the tape-widening
  fallback):** 1a `live_population_parity.py` + T1/T2/T6 (pure, no I/O).
  1b fixture construction (trim a real tape slice + CLI settlement) T3/T10
  setup. Reviewer: python-reviewer.
- **Stage 2 (depends on Stage 1's schema):** `live_population_parity_study.py`
  + T4/T7/T8, run once against the real corpus. Reviewer:
  prediction-market-reviewer (adverse-selection screen logic) +
  python-reviewer.
- **Stage 3 (parallel once Stage 2 lands):** 3a digest extension + T9;
  3b import-linter contract + T5. Reviewer: python-reviewer;
  security-reviewer only if the digest's alert-egress path is touched
  (should not be — additive fields only).
- **Stage 4 (sequential, doc-only):** write
  `docs/evidence/EDGE-4_live_population_parity_<run-date>.md` from the
  Stage 2 run's actual output (never pre-written); update AUD-18 §6.3's
  archive-table-recalibration row to cite it by id; note the AUD-18 ledger
  intake queue status (`PROGRESS.md:53`) rather than assuming immediate
  registration.

## 8. Deploy & verification (what proves it live)

This item ships no runtime/trading-path change, so "live" means the
**scheduled study/digest path**, not the trading node:
- `decision_funnel_daily_digest.py`'s extension deploys on its own existing
  systemd timer's next scheduled run (verify via `journalctl --user -u
  <digest-timer-unit>` and a diff of the output JSONL/report showing the
  new refusal-reason-breakdown section present).
- `live_population_parity_study.py` is a one-shot analysis run (mirroring
  other nightly studies), launched via `systemd-run --user` per
  memory `systemd-run-soft-nofile-1024` / oneshot-unit conventions; its
  ActiveState is polled to completion, never assumed from `is-active`.
  Proof of a real run: the generated frozen table's `CORPUS_SHA256`,
  the evidence doc under `docs/evidence/`, and the JSONL summary under
  `~/.local/share/breezy/derived/`.
- **Nothing here requires a node respawn or supervisor restart** — no file
  under `src/breezy/strategy/current_rung_hold/` changes (§5's "untouched"
  list), so the live `pm_us_crh_v4` halt state (A1, unaffected) and its
  eventual clearing are entirely out of this item's reach, by construction.

## 9. Risk register

- **R1 — accidental future wiring into the trading path.** Someone later
  imports `live_population_parity` from `decision.py`/`_finalize_take`,
  recreating a live pricing change without a fresh A1-class ruling.
  Mitigation: T5 import-linter contract (mechanical, not a policy note);
  a module-level docstring quoting A1 §4's "not permitted... as an
  implicit safety net" language verbatim.
- **R2 — corpus too small to say anything.** AUD-09b's own census (87
  SUFFICIENT rows total since 08-30) is almost certainly below `N_MIN=90`
  per scored cell. Mitigation: Stage 0/§1.4 treats this as
  `PARKED_INSUFFICIENT_DATA`, an honest and complete outcome, not a forced
  result — avoiding a fourth repeat of memory `implausible-result-is-a-leak`.
- **R3 — offer-tape fields unpopulated on refused rows.** If T0 fails, the
  entire premise needs the tape-widening fallback (§2), a small additive
  schema change with its own RED tests before Stage 1 can proceed.
- **R4 — the adverse-selection screen re-fails, again.** Expected, per
  prior art (three independent closures already listed in §0/§2). This is
  captured explicitly as an ACCEPTED, valuable outcome (a fourth,
  most-authoritative closure on the correct corpus), not a project failure
  — per memory `counterfactuals-need-a-mechanism` and
  `implausible-result-is-a-leak`, an honest negative is the deliverable,
  not a defect in the plan.
- **R5 — scope creep toward re-opening the forecast-taker hunt.** Any
  temptation to add forecast/NWP covariates to rescue the mid-ask-bucket
  screen (as band-decider's own memory note suggests as the only licensed
  reopening path) is explicitly OUT of scope here — forecast-edge is
  CLOSED TERMINAL and the brief forbids re-opening it. If a future item
  wants to explore non-forecast real-time covariates (e.g. time-since-METAR,
  minutes-since-window-open — already in the covariate set), that is a
  separate, explicitly-scoped follow-on, not silently folded in here.
- **R6 — AUD-18's ledger cannot yet accept this as a registered
  hypothesis.** `PROGRESS.md:53` records the ledger schema itself as
  BLOCKED pending a look-taking registration or `REPLAY_VALIDITY` flip.
  Mitigation: this item's hand-off is "citable evidence under
  `docs/evidence/`, referenced by id," not "a live registration" — it
  queues, it does not require AUD-18 to be unblocked first.

## 10. LESSONS / invariant compliance

- Nautilus untouched; no strategy/decision/pricing file edited (§5).
- `allow_short` untouched (no execution-path change at all).
- No safety/settlement/contract/NO-SEND test weakened; the import-linter
  contract ADDS a guard, never removes one.
- No operator-reserved value assigned (no budget/position cap touched); no
  live-trading enablement touched; A1's halt is untouched and unaddressed
  by this item on purpose.
- `archive-table-train-serve-skew`: this item is the "generalise" clause's
  own prescribed check — verifying the corpus applies the SAME refusal
  gates the live path applies — done by construction (unconditional
  denominator, T6).
- `band-decider-stopped-at-stage0b` / `no-live-subdegree-observation-source`:
  read, cited, and NOT reopened on the same corpus or with forecast
  covariates; reopened only on a corpus-provenance fix that is genuinely
  new evidence.
- `forecast-edge-closed-pmus-rungs`: not touched, not reopened (R5).
- `implausible-result-is-a-leak`, `counterfactuals-need-a-mechanism`: a
  repeat FAIL on the adverse-selection screen is reported as a valid,
  citable closure, not suppressed or re-run until it passes.
- `verify-agent-claims-against-artifact`: Stage 2's build agent must attach
  the actual run output (SHA256s, row counts) to the evidence doc, not a
  narrative claim.
- `lint-imports-after-every-slice`: T5 runs after every Stage 1/3 slice.
- `worktree-needs-pythonpath`: any worktree build brief must state
  `PYTHONPATH=<wt>/src` and `BREEZY_PYTHON=/home/jon/breezy/.venv/bin/python`.
- `operator-controls-are-budget-and-position`: nothing in this plan asks
  the operator for anything; the only operator-relevant fact (a future
  A1-class ruling would still be required before any live use) is stated,
  not enacted.

## 11. Dependencies on other EDGE items (by ID only)

- Feeds **EDGE-5** and **AUD-18** §6.3 (archive-table recalibration
  hypothesis) as a cited evidence input — never a self-executing re-arm.
- Depends on **AUD-09a**'s replay-sufficiency census for real corpus size
  (read-only dependency; this item does not modify AUD-09a).
- No dependency on **AUD-01** (NO-side calibration gate) — this item is
  YES-side/interval-resolution scoped; NO-side's own defect (`decision.py:439-441`,
  A1 §3.3 evidence item 2) is a separate, already-tracked hypothesis class.
- Unknown whether other EDGE_2026-09-27 items (EDGE-1/2/3) touch the same
  files — this plan was written blind per the coordinator's brief; the
  coordinator should check `decision_funnel_daily_digest.py` and the
  import-linter config for concurrent edits before merging.

## 12. Confidence self-assessment, unknowns

**Confidence: 0.65.** The negative findings (§0/§2) are strongly grounded —
verified directly against code and three independent evidence documents,
not summarized secondhand. The proposed build (§4-§7) is a conservative,
additive, non-wiring design that reuses established repo patterns
(Band Decider's covariate/table shape, `hourly_ask_relative_edge.py`'s
load-by-path isolation, the existing digest's tape-read path) rather than
inventing new machinery, which lowers implementation risk. Confidence is
capped below 0.8 by:

- **Unverified premise (T0):** whether `OfferTapeRecord.running_max_lower/upper`
  are actually populated on refused (not just Take) rows was not confirmed
  this session — the tape-write call site was not located/read. If false,
  Stage 0 forks to a schema-widening fallback not fully detailed here.
- **Sample size is very likely insufficient today** (§3, §9 R2) — the
  honest expected outcome of Stage 2 is `PARKED_INSUFFICIENT_DATA`, which
  is a valid but less immediately useful result than a scored calibration
  report; the acceptance criteria (§1) are written to make that outcome
  measurable and complete rather than requiring a pass.
- **AUD-18's own intake mechanism is not yet live** (`PROGRESS.md:53`), so
  "delivered as an input" is a documented hand-off, not a working pipeline
  integration, until AUD-18's own blocker clears — outside this item's
  control.
- I did not independently re-verify AUD-09b's 87-row SUFFICIENT count
  against a fresh census run this session (read from the existing evidence
  doc); if the census has moved materially since 2026-09-25, Stage 0's
  go/no-go arithmetic should be re-run against current numbers before
  Stage 1 starts.
