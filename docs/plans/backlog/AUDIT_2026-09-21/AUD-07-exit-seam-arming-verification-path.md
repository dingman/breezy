# AUD-07 — EXIT-1: make the exit seam's verification path able to progress, and assemble the evidence an arming decision would need

## 1. ID and actionable title

**AUD-07** — Land **Revision 3** of `docs/plans/POSITION_EXIT_EXECUTION_2026-09-16.md`: reconcile
the plan's recorded §4 step-0 result against what the nightly study now produces (including a
concrete closing check on the negative timing anomaly), fix the nightly position-monitor report's
family binding and its **located** zero-position blindness, make corpus accumulation observable
rather than silently static, establish a standing P&L reconciliation with AUD-04, pre-assemble
the `pm_us_crh_exit_v4` registration artefacts, and complete the PREREG v4 DRAFT spec with
per-parameter provenance under the 09-21 ruling's no-peeking conditions. **This plan does not arm
anything** — arming requires a separate REGISTRATION act and, for live-trading enablement of the new
family, an operator decision; neither is authorised here.

**Ruling applied (revision 5).** `docs/evidence/RULING_study_units_order_ceiling_exit_prereq_2026-09-21.md`
RULING 3 (`:156-199`) and its Revision 2 addendum A3 (`:322-332`), peer-ENDORSED at
`docs/evidence/reviews/RULING_study_ceiling_exit_review_2026-09-21.md:67`. Three consequences are
carried into §4/§5/§6/§7/§8/§12 below: the frozen exit corpus is an **arming-gate precondition, not a
blocker of this item**; the PREREG v4 DRAFT is authorable/completable now under no-peeking conditions;
and the 1-lot positive control is a **bot-automated** step, not an operator UI gate.

## 2. Source finding and class

- **Gap:** G-12 (`AUTONOMY_ROI_AUDIT_2026-09-21.md:85-86`). Verdict **FALSE (alignment)**: EXIT-1
  (`PROGRESS.md:52`) — built `c96c7f4`, `pm_us_crh_exit_v4` DRAFT, live family never sells (V).
- **Existing item extended, not duplicated:** **EXIT-1**, plan
  `docs/plans/POSITION_EXIT_EXECUTION_2026-09-16.md` (Rev 2). Its §4 step 0 arming gates stand;
  its Appendix A.3 result (R-DEAD FAILS 0/5; R-THREAT 1/5 against a ≥3 gate) stands as the reason
  the seam shipped UNARMED.
- **Class:** **verification gap** (the path to a decision cannot currently progress), with a
  measured **integration failure** (§3 C) inside it.

**Evidence collected for this plan (read-only, 2026-09-21).** Nothing was armed, started, stopped or
modified. Every artefact figure below was independently re-confirmed verbatim by two blind round-1
reviewers.

## 3. Current behaviour, required behaviour, concrete gap

**Current — four findings, all measured:**

- **A. The gate is correctly closed, and both halves of the L-22 unforgeable split are visible.**
  `src/breezy/persistence/exit_gate.py:55` already carries
  `_EXIT_RULE_REGISTERED_FAMILIES = frozenset({"pm_us_crh_exit_v4"})` — the code half is DONE. The
  manifest half is not: `deploy/families/pm_us_crh_exit_v4.json` is `DRAFT_NOT_REGISTERED`, carries
  **no `exit_rule` key at all**, `d0_climate_day: "2099-01-01"`, and all-zero placeholder
  `boundary_inputs_sha256` / `density_artefact_sha256` — which `load_family_manifest` refuses
  (`POST_FORECAST_PHASE_2026-09-20.md` B-8). It also carries `taker_fee_coefficient: "0.06"` while
  the live family runs `"0.0695"`, and `composition_kind: "current_rung_hold"` while the live family
  is `"continuous_rung_hold"`. **The manifest could not be registered today even if the gates
  passed.**
- **B. The plan's recorded step-0 result has DRIFTED from what the study now produces.** Rev 2
  Appendix A.3 (run `20260916_initial`) records `Σ R-BEST = −0.44`, MDW [82,83] R-BEST "no signal",
  and "median minutes from last executable exit to DEAD +93". The nightly artefact
  `~/.local/share/breezy/derived/exit_window_study/2026-09-20_nightly/exit_window_study.md` reports
  `sum_r_best_pnl=-0.0400`, MDW [82,83] R-BEST `exited@0.41 pnl=0.1500`, and
  `median_minutes_last_executable_to_dead=50.28` — plus a **negative**
  `median_minutes_last_executable_to_threatened=-74.11908…`. **The arming gates were read against a
  table the current study no longer produces.** Whether the study improved or regressed is
  undetermined — and that is precisely the point: an arming decision cannot rest on an unreconciled
  divergence.
- **C. The nightly report that owns the arming read is blind to the corpus — and the cause is now
  LOCATED (R1 fix).** `position_monitor_report_2026-09-20.md` states `family: pm_us_crh_cont` — not
  the live `pm_us_crh_v4` — and `positions: 0 (settled 0, unsettled 0)`, `settled by source:
  scored_trials=0 summary=0`, while the exit-window study over the same host and period reports
  `n_positions=5`. The previous revision left "why" as implementer discovery. Read today:
  - **C1 — the family label is a DEFAULT LITERAL, not a binding.**
    `scripts/analysis/position_monitor_nightly_report.py:119` declares
    `_DEFAULT_MONITORED_FAMILY_ID: Final[str] = "pm_us_crh_cont"`, used whenever `--family-manifest`
    is absent (`main`, `:863-870`, `:885-890`, the arg is optional and loads with `allow_draft=True`
    when supplied). `deploy/systemd/position-monitor-report-run.sh`'s `ARGS` block (`:102-106`)
    passes `--summaries-dir`, `--scored-trials-dir`, `--out`, `--markdown` and optionally
    `--corpus-summary` — **never `--family-manifest`**. So the report is not mis-bound to a family;
    it is **unbound**, and prints a stale default that reads like a binding.
  - **C2 — the two artefacts count DIFFERENT position universes, and one of them is empty.** The
    report's position universe is `read_monitor_summaries(args.summaries_dir)` (`:873`), i.e. the
    live `PositionMonitor`'s own parquet summaries store; `_settle_summaries` (`:429-470`) then
    joins each summary to a `ScoredTrial` by `trial_id`. **`settled by source: scored_trials=0
    summary=0` is therefore downstream of an EMPTY summaries list — it is not evidence that the
    scored store is empty.** The exit-window study's `n_positions=5` comes from a different source
    entirely: `read_filled_trials_state_db` (the durable exec-state fill ledger,
    `scripts/analysis/current_rung_hold_exit_window_study.py:94,452`).
  - **C3 — the summaries store does not exist on disk.** The wrapper resolves
    `MONITOR_ROOT="$(dirname "$CATALOG_ROOT")/monitor"` (`:41`) and
    `SUMMARIES_DIR="$MONITOR_ROOT/summaries"` (`:42`), mirroring the node's own
    `monitor_root = catalog_root.parent / _MONITOR_CATALOG_DIRNAME` (`composition.py:563`) and
    `summaries_dir = monitor_root / _MONITOR_SUMMARIES_DIRNAME` (`:663`) — so the paths agree by
    construction. Verified read-only today: `~/.local/share/breezy/catalog/quote_tape/` contains
    `decisions/`, `observations/` and `polymarket_us/` — **there is no `monitor/` directory at
    all.** The live monitor has apparently never written a summary. **Whether that is because the
    monitor only flushes under conditions never met (the live family never sells, so positions never
    close) or because of a path/permission failure is the single most important thing step 0 must
    establish** — the two have different fixes.
- **D. The corpus cannot grow, and nothing says so.** `breezy-exit-window-study.timer` has run
  nightly since 09-17 and every run reports `n_positions=5` — because there have been no fills since
  2026-09-15 (G-01, and the fee halt). The nightly job re-derives the same five rows and exits 0,
  which is indistinguishable in the journal from accumulation.

**Required.** (i) One reconciled step-0 reading, with the negative timing anomaly *closed* rather
than re-observed; (ii) a nightly report bound to the family the node runs and able to see the
positions that exist; (iii) a corpus signal that distinguishes "N grew" from "N is frozen";
(iv) a standing P&L reconciliation with AUD-04; (v) a registration package that is complete and
honest, so that if the gates ever pass, arming is one decision rather than a scramble.

**Concrete gap.** The seam is built and the gate is closed; what is missing is a *working measurement
loop* that could ever move the arming gates, and an honest statement that it currently cannot.

## 4. Priority, rationale, dependencies, execution order

**Priority: P2.** Findings B and C are live measurement defects that will silently corrupt any
future arming read, and they are cheap to close. Finding D is honesty about a blocked loop. The
arming itself is P3-and-blocked and is not in this item.

**Priority honesty after the A1 ruling (revision 5).** `docs/evidence/RULING_A1_pm_us_crh_v4_disposition_2026-09-21.md`
rules **A1 = (ii) STOP TRADING THIS SURFACE** (`:219-227`): `pm_us_crh_v4` "may not SEND orders"
(`:270-271`), and the ruling is ENDORSED but **UNENFORCED until AUD-02b lands and the halt is set**
(`:3`). The consequence for this item, stated without softening: the exit corpus does not resume
growing when the fee halt clears — it resumes only when some **future** family trades. The N=5 corpus
is therefore frozen for an indefinite, unscheduled horizon, and **the arming decision has no date**.
That lowers the expected value of the arming path, not of this item's measurement fixes; the priority
stays **P2** for exactly that reason, and would be P3 if this plan's deliverable were the arming
decision rather than the measurement loop.

**Dependency ordering (STAGE 1, alongside AUD-04/AUD-05):**
- **Corpus growth depends on a future family trading** — G-01 (nothing reaches pricing), the fee halt,
  and now the A1 (ii) ruling against the entry family. This is an **arming-gate precondition**
  (RULING 3 item 1, `:165-169`), **not a blocker of this item**: every measurement fix here is
  executable today at N=5. Named by id as a dependency in fact, not owned here (PRECONDITION-1).
- **Bilateral with AUD-04** (new, R1): AUD-04's report and this item's exit-window study are each
  other's producer/consumer for exit P&L. The reconciliation is **standing** on both sides —
  AUD-04 §8 AC#4 carries the mirror obligation.
- **Interacts with AUD-05** (by id): finding C1's fix must not be made by hard-coding a second
  literal while `pm_us_crh_v4` and `pm_us_crh_cont` share a `trial_id_prefix`.
- **Sequenced behind AUD-06a** (DEP-3, downgraded from BLOCKER-3 by RULING 3 item 3, `:196-199`):
  provisional shas can be minted and pinned today while the manifest stays `DRAFT_NOT_REGISTERED`;
  only the future **REGISTRATION** step must wait on AUD-06a's boundary conclusion. It does not block
  any step of this item.
- **PRECONDITION-2 (NEW, R6) — the family halt is sender-global, and it vetoes EXITS too.**
  `FAMILY_HALT_KEY: Final[str] = "continuous_rung_hold/halt"`
  (`src/breezy/strategy/current_rung_hold/trial_day_latch.py:291`) is a single literal key, **not**
  parameterised by family; `continuous_family_halt_key` returns it "regardless of the argument" under
  cardinality-1 (`src/breezy/runtime/trade_supervisor_core.py:158-170`); and `submit_exit`
  (`src/breezy/strategy/current_rung_hold/exit_wiring.py:246`) reads
  `strategy._latch.is_family_halted()` (`trial_day_latch.py:1002`) **first** and returns without
  submitting (`exit_wiring.py:270-275`). The ENDORSED
  `docs/evidence/RULING_A1_pm_us_crh_v4_disposition_2026-09-21.md` (`:234-246`) sets that halt for the
  **entry** family via **AUD-02b**. **Consequence, stated plainly: while that halt stands,
  `pm_us_crh_exit_v4` — if it ever occupies the node's sender slot — has every order refused, including
  the 1-lot positive control this item's arming path culminates in.** It is therefore a named
  precondition of the positive control (§5 step (0)), not a discovery to be made at the exec veto. It
  blocks no step of THIS item, which sends nothing.

**Execution order:** step 0 (evidence, incl. the C3 cause) → C fix → D signal → standing
reconciliation → B reconciliation incl. the negative-median closing check → registration package (A)
→ PREREG v4 DRAFT provenance completion (7b) → Rev 3. **No step arms anything, and no step
registers anything.**

## 5. Scope and explicit exclusions

**In scope:** `scripts/analysis/current_rung_hold_exit_window_study.py` (corpus reporting only),
`scripts/analysis/position_monitor_nightly_report.py` (family binding, position sourcing),
`deploy/systemd/position-monitor-report-run.sh` (the missing `--family-manifest`), the
`pm_us_crh_exit_v4` manifest, **`docs/specs/PREREG_v4_crh_exit_DRAFT_2026-09-16.md` (provenance
completion only, status unchanged)**, Rev 3 of the exit plan, and one dated evidence artefact.

**Explicitly excluded — and these are the load-bearing exclusions of this item:**
- **NO ARMING, AND NO REGISTRATION.** `exit_gate.py` is byte-unchanged. No `exit_rule` value is
  activated. The §4 step-3 1-lot positive control is NOT run by this item. **Corrected classification
  (revision 5):** that control is a **bot-automated** step, not an operator UI gate — repo practice is
  that its "operator residue is **one command** … No UI clicks, no hand-placed order, no hand cancel,
  no manual flatness check" (`docs/plans/OP_SEQ_BOT_POSITIVE_CONTROL_2026-09-04.md:7,118`), and the
  exit-side control at `POSITION_EXIT_EXECUTION_2026-09-16.md:333-336` is likewise a bot action. It is
  excluded here by **sequencing**, not by operator authority: it may not run before (i) the corpus
  precondition clears, (ii) §4 step 1's preview capture distinguishes **reducing from opening** —
  "If the preview cannot distinguish reducing from opening, this step is NOT retired and step 3 stays
  blocked" (`POSITION_EXIT_EXECUTION_2026-09-16.md:322-328`), (iii) §4 step 2's mapping ruling is
  written, and (iv) `pm_us_crh_exit_v4` is actually REGISTERED (RULING 3 item 2(b) and its
  conservative guard, `:181-195`).
  **(0) — the FIRST step of that sequence, ahead of (i)-(iv) (R6, PRECONDITION-2):** read and report
  the sender-global family-halt state (`is_family_halted()`, `trial_day_latch.py:1002`, over
  `FAMILY_HALT_KEY`, `:291`). **Halted → the positive control is `BLOCKED_FAMILY_HALT_SET`: it is not
  attempted, and the block is never recorded as a control FAILURE** — a refusal at
  `exit_wiring.py:270-275` is an inherited safety state, not evidence about the exit seam. When a
  control must run while the halt stands, the required route is AUD-02's documented **clear → act →
  re-set** sequence (`AUD-02-edge-discovery-programme-status-and-fold-in.md:668,742`), executed by
  AUD-02b's CLIs (`src/breezy/strategy/current_rung_hold/clear_family_halt_cli.py`; the set path
  `breezy-set-family-halt` is AUD-02b's to build) — never an exit-only bypass of the veto, and never by
  this item, which runs no control.
- **Authorisation chain, stated so no future reader stretches it (RULING 3 addendum A3, `:322-332`).**
  `pm_us_crh_exit_v4` is a **new, separately-manifested family** (`deploy/families/pm_us_crh_exit_v4.json`,
  gated independently by `src/breezy/persistence/exit_gate.py:55`). The 09-16 authorising operator
  ruling is **class-scoped, not family-scoped** ("Everything below the two budget caps is build-side
  and decided here", `POSITION_EXIT_EXECUTION_2026-09-16.md:8-12`) — which is why arming an exit rule
  on a new family raises no new operator residue. **Live-trading ENABLEMENT of `pm_us_crh_exit_v4`, if
  and when it is registered, remains operator-only** under the standing invariant at
  `docs/core/PROGRESS.md:39-42`. This item arms nothing and enables nothing.
- **No loosening of the §4 step-0 arming gates** (R-THREAT ≥3 of N firing before the exit side
  empties, Σ counterfactual ≥ Σ hold, at least one firing meeting the real
  `recoverable_value > E[settlement|state]` condition; R-DEAD ≥1 of N). Reconciling a drifted
  measurement must never become re-reading the gates against whichever number is friendlier.
- **No tuning of the PROVISIONAL constants** (`_P_HOLD_DROP_MARGIN`, confirmation counts/spans,
  `_LOCKED_HOUR_LST`, `monitor_decision.py:148-158`) off live firings without a registered
  amendment — Rev 2 §6 already forbids it.
- **No order-path change**, no `submit_chain.py` change, no multi-contract exit (the exit path stays
  "only a 1-contract order is mappable; refusing"), no `/v1/order/close-position`.
- No change to `allow_short`, the net-long guard, the submit-intent latch, or the daily-budget
  gross-entry-spend ruling (Rev 2 §5.8).
- **No change to the PositionMonitor's own write path** unless step 0 establishes C3 is a path or
  permission defect; if the cause is "the monitor legitimately never flushes because positions never
  close", the correct fix is in the *report's* sourcing (C2), not in the live node.

## 6. Proposed changes grounded in inspected code

**Null hypothesis (L-1) — already settled by Rev 2 §0 and not re-opened.** `Strategy.close_position`
is REFUTED for this use (`trading/strategy.pyx:1351-1416` constructs a MarketOrder, hardcoded, no
limit variant, and `submit_chain.py` refuses non-LIMIT — re-confirmed in round 1). Everything else is
CONFIRMED native: `Order.closing_side` (`model/orders/base.pyx:913`), the
`submit_order(order, position_id=position.id)` attribution idiom (`trading/strategy.pyx:1416`),
`cache.position()`/`positions_open()`, `OmsType.NETTING`. **This item builds no order path at all**,
so the null hypothesis is satisfied trivially: the changes below are to two offline analysis scripts,
one wrapper, and one JSON manifest.

- **C1 — bind the report to the family the node runs, generically.** Two changes, neither a second
  literal:
  (i) `position-monitor-report-run.sh` enumerates REGISTERED, `venue == polymarket_us` manifests
  under `deploy/families/` — exactly as `score-live-trials-run.sh:68-94` already does (the SD-1/L-38
  discipline) — and passes `--family-manifest` per family;
  (ii) `_DEFAULT_MONITORED_FAMILY_ID` (`:119`) is replaced by an explicit `UNBOUND` sentinel that
  renders as `family: UNBOUND (no manifest supplied)`, so an unbound run can never again *look* like
  a binding to a real family. Where two REGISTERED families share a `trial_id_prefix` (AUD-05 D-D),
  the report keys on `family_id` and reports ambiguous rows as `AMBIGUOUS_FAMILY` rather than
  picking.
- **C2/C3 — make the report's position universe reconcilable with the study's.** Whichever cause
  step 0 establishes:
  - if the monitor legitimately never writes summaries for positions that never close, the report
    must **state its universe explicitly** (`position universe: monitor summaries (N=…); ledger fills
    over the same period: M — DIFFERENT UNIVERSES`) and reconcile against the ledger count, rather
    than printing a bare `positions: 0` that reads as "there are none";
  - if it is a path/permission defect, fix the path and assert it with a test that the wrapper's
    `SUMMARIES_DIR` equals the node's `composition.py`-derived `summaries_dir` for the same
    `CATALOG_ROOT`.
  Either way the artefacts may no longer disagree silently.
- **D — make frozen corpus legible.** The study's summary block gains
  `corpus_first_fill_date`, `corpus_last_fill_date`, `n_positions`, and
  `n_positions_new_since_previous_run`. When the last is 0 for ≥3 consecutive runs, emit a
  dimensionless `EXIT_CORPUS_FROZEN` WARN through the existing alert sink
  (`resolve_alert_sink` / `emit_alert`, delivering since `f97c26f`).
  **Dedupe/latch, specified (R1 fix) and made RECURRING + ESCALATING (R2 MATERIAL fix).** Round 2
  established that the round-1 "one alert per frozen streak, never nightly" rule goes permanently
  silent for the life of an ongoing outage — and that **this control is already at or past its
  one-shot firing point on the live record today** (§11's baseline: `n_positions_new_since_previous_run`
  unreported for 4+ consecutive nights, no fills since 09-15). A control whose whole purpose is "a job
  that cannot progress says so" must keep saying so.

  This item therefore adopts the re-alert ladder specified in AUD-04 §6 D8 — and **as of revision 4 it
  adopts it BY IMPORT, not by prose reference (R3 fix, raised on both records).** Round 3 found that
  "by reference and without variation" was enforced only by two authors reading the same paragraph,
  while every other cross-artefact contract in this backlog is enforced by a shared function or a
  test. **AUD-04 owns the implementation**: `src/breezy/runtime/alert_ladder.py`
  (`evaluate_streak(...)` plus the UTC-ISO-week / UTC-day period keys and the latch read/write with
  its `schema_version`), with `tests/unit/test_alert_ladder.py` as the single place the state
  machine's semantics are asserted. **This item imports that module and re-specifies none of it**: its
  own RED-test list (§7 step 3) references the shared test module for the streak/period-key/restart/
  clear cases and tests only what is genuinely local here — this control's own event names, its own
  latch file, and its own `n_positions_new_since_previous_run == 0` streak predicate.
  **Dependency, by id, acyclic:** AUD-07 → AUD-04 for the module; AUD-04 → AUD-07 only as a DATA read
  of this item's published artefact at report time (the standing reconciliation), never an import.
  **Ship-order contingency:** if this item lands before AUD-04's module exists, it lands with the
  ladder inline **plus a RED-on-divergence cross-test** asserting its period-key function returns
  identical values to AUD-04's on a shared set of UTC timestamps spanning an ISO-week and a
  year boundary; that cross-test is deleted in the same commit that switches to the shared import.
  Forking the ladder permanently is prohibited.
  The table below is the ladder's *parameterisation for this control*, not a second specification of
  it:

  | Streak (consecutive runs with `n_positions_new_since_previous_run == 0`) | Severity | Re-emit cadence |
  |---|---|---|
  | `< 3` | — | silent |
  | `3 … 13` | `WARN` | once per **UTC ISO week** |
  | `≥ 14` | `CRITICAL` | once per **UTC day** (the AUD-05 §6 D-F daily-repeat cadence) |

  - **Latch file** `~/.local/share/breezy/derived/exit_window_study/.frozen_streak.json`, now holding
    `{"streak": int, "first_frozen_utc_day": str, "last_alert_severity": str,
    "last_alert_period_key": str}`. Each run increments `streak` when
    `n_positions_new_since_previous_run == 0` and resets it to 0 otherwise.
  - **Restart-surviving dedupe:** a run whose computed period key equals `last_alert_period_key` at
    the same severity emits nothing, so a reboot or a same-period retry never re-pages; a missed
    period is picked up on the next run. A missing or unparseable latch file is treated as
    `streak = 0` and re-alerts on the next qualifying run (fail-loud, never fail-silent).
  - **Clear condition and full re-arm:** any run with `n_positions_new_since_previous_run > 0` resets
    the streak, clears the alert keys and emits exactly one `INFO` `EXIT_CORPUS_FROZEN_CLEARED
    streak_len=<k>`, so recovery is observable rather than a mere absence; a later freeze fires `WARN`
    again at `streak == 3` and `CRITICAL` again at `14`. Escalation is one-way within a streak.
  - **This does not weaken the WP-R1 false-page discipline** (`PROGRESS.md:103-128`: "the cost of a
    false page is an operator who stops reading alerts"): the ladder pages at most **once a week**
    while the freeze is short, and reaches daily only after two weeks of a measurement loop making no
    progress at all — which is not a false page, it is the failure this control exists to report.
- **NEW — standing P&L reconciliation with AUD-04 (R1 fix), with "overlapping" DEFINED (R2 fix).**
  On any date for which both this study's artefact and AUD-04's portfolio report exist, the study
  asserts that its `sum_hold_pnl` over the overlapping positions equals AUD-04's
  `realised_pnl_after_fees_total` for the same rows (read through AUD-04's `schema_version` reader,
  never by re-parsing Markdown), or names the divergence and its cause.
  - **"Overlapping positions" means the inner join on `trial_id`** — not `(instrument_id, fill_ts)`
    and not station-day. `trial_id` is the one key both artefacts already carry: this study is
    per scored trial, and AUD-04 labels every reconciled fill with its `trial_id` through
    `admissible_scored_trials`. AUD-04 §8 AC#4 states the identical definition, so the two sides
    cannot drift.
  - **Why it must match EXACTLY today, not merely on average.** This study's `sum_hold_pnl` is a
    HOLD-strategy counterfactual while AUD-04's is realised P&L over actually settled fills. The two
    coincide wherever "hold" and "actual" are the same outcome — and **until any exit ever fires they
    are definitionally the same outcome for every row**, because the live family never sells:
    `exit_gate.py:55 _EXIT_RULE_REGISTERED_FAMILIES = frozenset({"pm_us_crh_exit_v4"})` and that
    family is not registered (§5, it stays `DRAFT_NOT_REGISTERED`). So the reconciliation must match
    **to the cent on every joined row**, and a partial-N mismatch is an **alarm**, never expected
    slack. Once any exit is exercised (post-arming, out of this item's scope) this becomes a genuine
    matched-subset comparison and this paragraph must be revised with it.
  - A persistent unexplained mismatch emits `EXIT_PNL_RECONCILIATION_MISMATCH` through the same sink,
    on the **same re-alert ladder** as `EXIT_CORPUS_FROZEN` above (streak = consecutive runs with an
    unexplained mismatch; weekly `WARN`, daily `CRITICAL` at `≥ 14`; own latch keys in the same file).
  **This is a standing obligation on both sides, not a one-shot AC** — AUD-04 §8 AC#4 carries the
  mirror.
- **B — reconcile the drift.** Re-run the study at the Rev 2 stamp inputs and at current inputs, and
  diff them row by row. The candidate causes to discriminate, stated before the numbers are read:
  (i) the staged-Depth10 substitution Rev 2 records for 4/5 rows ("the parquet catalog is stranded
  before the fills, ING-1") has since been replaced by real catalog rows — every current row reports
  `depth_source=catalog`, where Rev 2 recorded staging; (ii) an IEM observation cache refresh moved a
  settlement inference; (iii) a code change to the study since 09-16. Whichever it is, Rev 3 carries
  ONE table and states its provenance.
- **B2 (NEW, R1) — close the negative-median anomaly with a concrete, testable check.**
  `median_minutes_last_executable_to_threatened = -74.119…` is either a real ordering property
  (THREATENED confirming *after* the exit side emptied) or a sign-convention/labelling defect. It
  **must be closed before the reconciled table is trusted**, because the arming gate is literally
  "R-THREAT fires strictly before the exit side empties", so the sign of this series *is* the gate's
  subject matter. The closing check, in two parts:
  1. **Per-row structural assertion.** For every row, compute
     `delta_i = threatened_confirmed_ts_i − last_executable_exit_ts_i` and classify it:
     `delta_i >= 0` → `THREATENED_BEFORE_EXIT_SIDE_EMPTIED` (the gate-relevant case);
     `delta_i < 0` → `THREATENED_AFTER_EXIT_SIDE_EMPTIED`, which must be **individually explainable**
     from that row's own timestamps (i.e. the exit side genuinely emptied first). The study prints
     the classification per row and the count of each class. **The reconciled table may not be
     published while any row's sign is unexplained.**
  2. **RED test with a fixture through the real writer path (L-42), both orderings.**
     `test_a_threatened_confirmation_after_the_exit_side_empties_yields_a_negative_delta_and_is_labelled`
     and `test_a_threatened_confirmation_before_the_exit_side_empties_yields_a_positive_delta`.
     A synthetic fixture would hide exactly the class of defect the 0-vs-5 disagreement already
     demonstrates, so the fixture is built through the real writer.
  3. **Gate-reading consequence, stated in Rev 3:** rows classified
     `THREATENED_AFTER_EXIT_SIDE_EMPTIED` **do not count toward** the R-THREAT "≥3 of N firing before
     the exit side empties" gate, whatever the median says. The median is a summary; the gate is
     per-row. If closing the anomaly reduces the qualifying count, that is the honest reading.

> **ERRATUM (2026-09-25, domain review of steps 0-6 implementation).** The polarity stated above is
> **inverted**. The implemented and coordinator-ENDORSED rule (CORRECT_DEVIATION) is:
> `delta_i < 0` → `THREATENED_BEFORE_EXIT_SIDE_EMPTIED` (the gate-relevant case);
> `delta_i > 0` (or `= 0`) → `THREATENED_AFTER_EXIT_SIDE_EMPTIED`.
> Derivation: `delta_i = threatened_confirmed_ts_i − last_executable_exit_ts_i`. "Threatened confirmed
> **before** the exit side empties" means the threatened timestamp is the *earlier* of the two, i.e.
> `threatened_confirmed_ts_i < last_executable_exit_ts_i`, i.e. `delta_i < 0` — the opposite sign of
> what this section originally wrote. The real-writer-path fixture for the MIA 09-15 firing confirms
> this empirically: it has `delta = −74.12 min` and was already published (Rev 3, Finding B2) as
> `THREATENED_BEFORE_EXIT_SIDE_EMPTIED`, which is only consistent with `delta_i < 0 → BEFORE`. See
> `docs/evidence/EXIT_SEAM_VERIFICATION_STATE_2026-09-25.md` for the reconciled table and the
> `classify_threatened_delta` implementation this erratum describes. This erratum corrects the prose
> only; it does not reopen §6 B2's gate-reading consequence (item 3 above), which is stated correctly
> in terms of the class labels, not the raw sign.

- **A — complete the registration package, still DRAFT.** Mint real artefacts and fill the manifest:
  re-run `scripts/analysis/crh_group_sequential_boundaries.py` and pin the resulting `inputs_sha256`
  (Rev 2 §2's own instruction), set a real `density_artefact_sha256`, correct
  `composition_kind` to match the composition the successor actually runs, and add the
  `exit_rule` key `"crh_exit_v4:R_THREAT_PRIMARY+R_DEAD_BACKSTOP"` (Rev 2 §2). **`status` stays
  `DRAFT_NOT_REGISTERED` and `d0_climate_day` stays a placeholder** — registration is the arming
  decision's act, not this item's.

  **`taker_fee_coefficient` — read from the manifest at run time, NEVER a constant in this plan (R3
  fix).** Round 3 correctly found that "the coefficient in force at registration" cannot be known when
  this item's step 7 runs, since registration is a future, operator-gated event. The reviewer's
  proposed alternative — writing `TBD_AT_REGISTRATION` into the field — is **REJECTED with evidence:
  it would make the manifest unloadable.** `load_family_manifest` validates
  `taker_fee_coefficient` against `_TAKER_FEE_COEFFICIENT_RE` (a leading `0.` plus one to six decimal
  digits, `family_manifest.py:290-308`) and then requires `0 < θ < 1`; the key is in `_REQUIRED_KEYS`
  (`:109`) and `_STRING_FIELDS` (`:123`), and the allowed-key set is closed, so neither a sentinel
  string nor an extra `*_provenance` key can be added. The disposition is therefore:
  - The manifest field keeps a **parseable, provisional** decimal, and the value written at step 7 is
    **read at write time from the same source the node asserts against** (the instrument's own fee via
    `assert_fee_schedule_known` / `_guarded_fee_coefficient`, `continuous_strategy.py:2504-2512`), never
    typed in from this plan. **This plan states no coefficient value** — a literal here would be exactly
    the stale pin that produced the 09-17 fee drift.
  - The **consumer already reads the manifest at run time and must keep doing so**:
    `app/trade.py:239` and `:285` pass `required_fee_coefficient=manifest.taker_fee_coefficient`. No
    code path may hard-code or cache a coefficient.
  - The provisional status is recorded where it CAN be recorded — in
    `docs/evidence/EXIT_SEAM_VERIFICATION_STATE_2026-09-__.md`, naming the value written, the source it
    was read from, the timestamp, and the requirement that it be re-read and re-verified at actual
    registration. `status: DRAFT_NOT_REGISTERED` and the unchanged `exit_gate.py` code half mean
    nothing can fire on it while it is provisional.
  - RED test: `test_the_exit_v4_manifest_fee_coefficient_matches_the_live_fee_source_at_write_time`,
    and `test_no_fee_coefficient_literal_appears_in_this_items_diff`.

- **E (NEW, revision 5) — complete the PREREG v4 DRAFT spec's provenance, still DRAFT.** RULING 3
  item 2(a) (`:171-180`) holds that a PREREG v4 DRAFT can be authored now without peeking; precedents
  `docs/specs/PREREG_v5_crh_rest_DRAFT_2026-09-16.md` and
  `docs/specs/PREREG_v2_current_rung_hold_DRAFT_2026-09-04.md`. **Verified this revision: the DRAFT
  already exists** — `docs/specs/PREREG_v4_crh_exit_DRAFT_2026-09-16.md` (185 lines,
  `**Status: DRAFT_NOT_REGISTERED (2026-09-16). D0 unpinned.**` at `:3`, `d0_climate_day` **UNPINNED**
  at `:20`, boundary re-run-and-pin instruction at `:116`). The ruling's "author the DRAFT" is
  therefore satisfied in substance; **what is missing is the provenance and the attestation**, and
  that is what this item adds, in place, without touching any registered semantic:
  - a **provenance table** — one row per parameter: *parameter → source `doc:line` → the UTC timestamp
    of the git commit that INTRODUCED that line → status* — with every parameter inherited from
    `docs/plans/POSITION_EXIT_EXECUTION_2026-09-16.md` Rev 2 §2/§4 (boundary re-solved from unchanged
    inputs; the unchanged R-THREAT / R-DEAD gates). **Commit timestamp, never the file's name-date:**
    both source documents are named `...2026-09-16` yet were edited repeatedly through that day, so a
    name-date cannot separate pre- from post-readout content;
  - **the no-peeking ANCHOR, established from the repo this revision (R6 fix — the previous anchor was
    chronologically inverted).** No-peeking is about the exit **OUTCOME** readings a designer could
    have tuned toward, not about when a position was opened; a fill date precedes its own outcome
    verdict by construction, so `corpus_first_fill_date` tests nothing here. The anchor is
    **`first_exit_outcome_readout = 2026-09-16T03:36:32Z`** — commit `84d9042` ("docs(plan): Appendix
    A.3 — exit-window study result (R-DEAD 0/5 fillable, R-THREAT 1/5 ...)"), the first artefact in this
    repo reporting R-DEAD / R-THREAT readings over this corpus; the study artefact itself
    (`~/.local/share/breezy/derived/exit_window_study/20260916_initial/exit_window_study.{json,md}`)
    carries mtime `2026-09-16 03:45:42Z`, after the L-44 per-leg sign correction Appendix A.3 records.
    The chronology, each row verified this revision:

    | Event | UTC | Source |
    |---|---|---|
    | earliest fill in the N=5 exit corpus | 2026-09-13 | `POSITION_EXIT_EXECUTION_2026-09-16.md:478` (MIA 09-13); the other four rows are 09-15 (`:476-477,479-480`) |
    | last fill — corpus frozen since | 2026-09-15 | same table; §3 D |
    | 09-16 operator ruling + Rev 2 design doc | 2026-09-16 03:00:51Z | commit `ebe7c46`; the §4 step-0 arming gates (`>= 3 of N`, `>= 1 of N`) and R-THREAT's `recoverable_value > E[settlement \| state]` condition are already present in it |
    | PREREG v4 DRAFT spec created | 2026-09-16 03:06:57Z | commit `bdcfd38`; pre-anchor edit `7c558a5` at 03:24:56Z |
    | **first exit-OUTCOME readout — THE ANCHOR** | **2026-09-16 03:36:32Z** | commit `84d9042` (Appendix A.3) |
    | §5.4 / PREREG v4 §5b two-layer AMBIGUOUS-exit cover | 2026-09-16 05:52:43Z | commit `537783a` — **POSTDATES the anchor** |

  - **honest per-parameter disposition (R6), because some provenance does not clear the anchor.** A
    parameter whose introducing commit is at or before `2026-09-16T03:36:32Z` is attestable as
    un-peeked — on today's reading that covers the v3 entry-side inheritance, the PROVISIONAL
    `monitor_decision.py` constants, the order shape, both firing conditions and both arming gates
    (`ebe7c46` / `bdcfd38` / `7c558a5`). **A parameter whose introducing commit is later CANNOT be
    attested as un-peeked, and the spec must SAY SO rather than attest it anyway**: it is flagged
    `PROVENANCE_POSTDATES_READOUT` in the provenance table's status column. **Known today: §5b's
    two-layer AMBIGUOUS-exit cover (`537783a`, 05:52:43Z).** The remedy belongs to REGISTRATION, not to
    this item, which registers nothing: registration of the family requires EITHER re-deriving the
    flagged parameter from inputs that predate the anchor and re-citing it, OR an explicit ruling
    artefact accepting it — in which case the N=5 corpus rows are excluded from any confirmatory tally,
    which they already are, since `n` resets to 0 at registration
    (`POST_FORECAST_PHASE_2026-09-20.md` §A-9 item 2, `:211,217-218`). A flagged row may never be
    silently upgraded to attested, and a blanket prose attestation over a table containing one is
    false;
  - an explicit **attestation**: *no parameter, endpoint, boundary, window or firing threshold was
    chosen, tuned or justified against the N=5 exit corpus.* The N=5 readings (R-DEAD 0/5,
    R-THREAT 1/5) are **arming-gate reads, never design inputs**;
  - `status: DRAFT_NOT_REGISTERED` and `d0_climate_day` **unpinned**, both unchanged;
  - `n` **resets to 0 at registration** — authority `docs/plans/POST_FORECAST_PHASE_2026-09-20.md`
    §A-9 item 2 (`:211,217-218`), which is the correct citation for the reset (not L-34).
  **REGISTRATION is a separate, later act and is not authorised here**, by this item or by the ruling.

## 7. Ordered verification steps (RED first where code changes)

0. **EVIDENCE (read-only).** `docs/evidence/EXIT_SEAM_VERIFICATION_STATE_2026-09-__.md`: the four §3
   findings with their artefact paths and verbatim lines; the current nightly table beside Rev 2
   Appendix A.3; the enabled-timer inventory; **and the C3 determination** — does
   `<catalog_root>.parent/monitor/summaries` exist, has the live node ever written into it, and if
   not, is the cause (a) the monitor legitimately never flushing for positions that never close, or
   (b) a path/permission defect? Establish this from the node log and the on-disk tree; **the fix
   branch in §6 C2/C3 depends on the answer.**
   **(R3) Which branch is specified at finer grain, stated in advance so the asymmetry is deliberate
   and not an oversight:** branch (a) — "the monitor legitimately never flushes for positions that
   never close" — is specified at the finer grain, because it is the branch the evidence currently
   favours (`composition.py:563,663` derives `monitor_root = catalog_root.parent / "monitor"` and
   `summaries_dir = monitor_root / "summaries"`, and the wrapper's `MONITOR_ROOT="$(dirname
   "$CATALOG_ROOT")/monitor"` / `SUMMARIES_DIR="$MONITOR_ROOT/summaries"` derive the identical path, so
   the two agree by construction and a path mismatch is the less likely cause). Branch (b) is
   deliberately specified only to the level of "name the divergent path and the permission bits in the
   evidence doc, then re-scope", because a path/permission defect cannot be designed against before it
   is seen — its remedy depends on which of the two derivations is wrong and why. **If step 0 selects
   branch (b), this item's §6 C2/C3 is re-scoped in a revision before any code is written**, rather
   than implemented against a guess.
1. **RED (C):** `test_the_nightly_report_names_the_registered_live_family_not_a_literal`;
   `test_an_unbound_run_renders_UNBOUND_not_a_default_family`;
   `test_the_wrapper_passes_a_family_manifest_for_every_registered_polymarket_us_family`;
   `test_a_settled_position_present_in_the_store_is_counted_by_the_report` (fixture written through
   the real writer path, L-42 — the 0-vs-5 disagreement is exactly what a synthetic fixture would
   have hidden);
   `test_the_report_states_its_position_universe_and_the_ledger_count_over_the_same_period`;
   **NEW (R2)** `test_the_reports_stated_ledger_count_matches_an_independent_second_read_of_the_ledger`
   — the round-2 review correctly observed that "states a ledger count" is satisfiable by two
   independently-wrong reads that happen to agree. The test therefore derives the count a **second,
   structurally different way** and asserts equality: a direct read-only count of `DurableFillRecord`
   rows under `FILL_KEY_PREFIX`
   (`src/breezy/adapters/polymarket_us/exec/client.py:641` and `:384`) over the same period, using the
   `mode=ro` URI idiom at `fill_time_count.py:84-98` — the same read-only idiom this backlog already
   uses elsewhere, and the same ledger AUD-04 reads. Once AUD-04 ships, the assertion additionally
   compares against `n_ledger_fills` from its versioned reader; until then the second read is the
   independent check, so this test is **not** gated on AUD-04.
   `test_two_registered_families_are_each_reported_separately`.
2. **GREEN C.**
3. **RED (D), on the re-alert ladder (R2 — these replace the round-1 single-shot tests, which
   asserted the defect as intended behaviour).** **R4: the ladder's own state machine and period keys
   are asserted ONCE, in AUD-04's shared `tests/unit/test_alert_ladder.py`, which this list references
   rather than restates.** The tests below are this control's local wiring: that it calls
   `alert_ladder.evaluate_streak`, that its streak predicate is
   `n_positions_new_since_previous_run == 0`, and that its own event names and latch file behave. Where
   a test name below duplicates a case the shared module already owns, it is implemented as a thin
   integration assertion over this control's wrapper, never as a second copy of the arithmetic:
   `test_a_run_that_adds_no_positions_reports_zero_new`;
   `test_three_consecutive_zero_new_runs_emit_one_frozen_corpus_warn`;
   **NEW** `test_a_thirty_night_freeze_re_alerts_weekly_then_escalates_to_daily_critical` — drive 30
   consecutive zero-new runs and assert the exact emitted sequence (one `WARN` per UTC ISO week while
   `3 ≤ streak ≤ 13`, then one `CRITICAL` per UTC day from `streak == 14`). This is the day-N-repeat
   test; it fails against the round-1 latch;
   **NEW** `test_a_same_period_rerun_does_not_re_alert`;
   **NEW** `test_the_frozen_streak_latch_survives_a_restart_without_re_alerting`;
   **NEW** `test_a_missing_or_corrupt_frozen_streak_latch_re_alerts_rather_than_failing_silent`;
   **NEW** `test_a_new_position_clears_the_streak_emits_one_info_and_fully_re_arms` — the
   clear-then-refire test: a run with `n_positions_new_since_previous_run > 0` clears the streak and
   emits one `INFO` `EXIT_CORPUS_FROZEN_CLEARED`; a subsequent freeze fires `WARN` again at
   `streak == 3` and `CRITICAL` again at `14`;
   **NEW** `test_severity_never_de_escalates_within_one_streak`;
   `test_the_warning_carries_no_currency_denominated_field` — every ladder field (`streak`,
   `streak_len`, `n_positions_new_since_previous_run`) is dimensionless.
4. **GREEN D.**
5. **RED/GREEN (standing reconciliation):**
   `test_a_matching_aud04_report_and_study_reconcile_on_the_overlapping_rows`;
   **NEW (R2)** `test_overlap_is_the_inner_join_on_trial_id_and_matches_to_the_cent_on_every_row` —
   pins the join key and the exact-match expectation, and fails a "matches on average" implementation;
   **NEW (R2)** `test_a_row_present_in_only_one_artefact_is_reported_as_unjoined_never_dropped`;
   `test_a_divergence_is_named_and_emits_a_latched_mismatch_alert` — on the same ladder as D (weekly
   `WARN`, daily `CRITICAL` at `streak ≥ 14`);
   `test_the_reconciliation_reads_aud04_through_its_schema_version_reader`.
6. **B:** run both study configurations, diff, establish the cause, write the reconciled table.
   **B2 is a required sub-step of this step, not a note:** implement the per-row `delta_i`
   classification and its two RED tests (§6 B2), and **do not publish the reconciled table until
   every negative-delta row is individually explained.**
7. **A:** mint artefacts, update the manifest (status unchanged), with a RED test that
   `load_family_manifest` now **accepts** the manifest's shas while the family remains
   `DRAFT_NOT_REGISTERED` and `family_declares_exit_rule` still returns the gate-closed result for
   every family the node currently runs.
7b. **PREREG v4 DRAFT provenance completion (§6 E).** Amend
   `docs/specs/PREREG_v4_crh_exit_DRAFT_2026-09-16.md` in place with the provenance table, the
   no-peeking attestation, and the `n`-resets-at-registration citation; `status` and the unpinned
   `d0_climate_day` are asserted unchanged by diff. **Checkable against the RIGHT boundary, not merely
   declared (R6 fix — the previous anchor, `corpus_first_fill_date`, was chronologically inverted: it
   is `2026-09-13`, so every 09-16 design artefact postdates it and the check would have failed on real
   data while testing nothing about peeking).** Every provenance row carries the UTC timestamp of the
   commit that introduced its cited line, compared against the §6 E anchor
   `first_exit_outcome_readout = 2026-09-16T03:36:32Z` (`84d9042`) — the first moment an exit-OUTCOME
   reading over this corpus existed to peek at. Rows at or before the anchor are `ATTESTED`; later rows
   are `PROVENANCE_POSTDATES_READOUT` and carry the §6 E registration-time remedy. RED tests:
   `test_every_prereg_v4_parameter_provenance_row_carries_its_introducing_commit_timestamp`;
   `test_a_parameter_introduced_before_the_first_outcome_readout_is_classified_attested`;
   `test_a_parameter_introduced_after_the_first_outcome_readout_is_flagged_provenance_postdates_readout`
   — driven off the real `537783a` §5b row, so the flagged class is exercised on live data rather than
   asserted to be empty;
   `test_the_no_peeking_check_anchors_on_the_outcome_readout_never_on_the_first_fill_date` — fails an
   implementation that compares against `corpus_first_fill_date`;
   `test_a_flagged_row_makes_a_blanket_no_peeking_attestation_fail`; and
   `test_the_v4_draft_spec_status_and_d0_are_unchanged_by_this_item`. Nothing here registers anything,
   and the authorisation chain of §5 is restated in the spec.

7c. **(NEW, R6) Halt-state precondition for the positive control (read-only; builds and sends no
   order).** The registration package's pre-control checklist gains a sender-global halt-state read,
   recorded with its source and timestamp in
   `docs/evidence/EXIT_SEAM_VERIFICATION_STATE_2026-09-__.md`. RED tests:
   `test_the_positive_control_precondition_reads_the_sender_global_family_halt_state`;
   `test_a_set_family_halt_blocks_the_positive_control_as_BLOCKED_FAMILY_HALT_SET_not_as_a_failure`;
   `test_the_halt_precondition_reads_the_same_FAMILY_HALT_KEY_the_exit_veto_reads` — pins the literal
   against `trial_day_latch.py:291` so a future family-scoped key cannot silently diverge from
   `exit_wiring.py:270-275`. All three run under `scripts/ci/run_tests_no_egress.sh`.

8. **Rev 3** of the exit plan: one table, the reconciled gate reading (with the per-row R-THREAT
   classification, §6 B2.3), the §3 findings, and an explicit statement of what the arming decision
   would require.
9. `scripts/ci/run_tests_no_egress.sh` + `lint-imports`.

## 8. Measurable acceptance criteria and required evidence

1. The nightly position-monitor report names the family the node runs, resolved from
   `deploy/families/` via the wrapper rather than a default literal, on three consecutive nights;
   and an unbound run renders `UNBOUND`, proven by test.
2. On any night where the exit-window study reports `n_positions = N`, the position-monitor report's
   position count is **reconcilable** with `N` — either equal, or differing with the difference and
   its universe named in the artefact. **The silent 0-vs-5 disagreement is gone.** **(R2 addition:)**
   the stated ledger count is not merely stated but **independently verified** — it must equal a
   second, structurally different read-only count of `DurableFillRecord` rows under `FILL_KEY_PREFIX`
   over the same period, proven by
   `test_the_reports_stated_ledger_count_matches_an_independent_second_read_of_the_ledger`. Two
   independently-wrong reads that agree with each other no longer satisfy this criterion.
3. **(R2 — replaces the round-1 single-shot criterion, which locked the defect in as intended
   behaviour.)** The study's summary block carries the four corpus fields, and `EXIT_CORPUS_FROZEN`
   follows the §6 D **re-alert ladder**, delivered out-of-process: exactly one `WARN` on the first
   qualifying run of each UTC ISO week while `3 ≤ streak ≤ 13`, then exactly one `CRITICAL` per UTC
   day from `streak ≥ 14`; no duplicate within a period key, including across a restart; a new
   position clears the streak with one `INFO` `..._CLEARED` and fully re-arms. Proven by the
   day-N-repeat, restart and clear-then-refire tests in §7 step 3 and by the latch file's contents.
   The live record is **already past the trigger**, so the ladder is verifiable on day one.
4. **The negative-median anomaly is CLOSED, not re-observed:** every row carries a `delta_i`
   classification, every `THREATENED_AFTER_EXIT_SIDE_EMPTIED` row is individually explained in the
   artefact, both orderings are covered by tests through the real writer path, and Rev 3 states the
   per-row R-THREAT count (not the median) as the gate reading.
5. Rev 3 carries ONE step-0 table with stated provenance, and states the arming-gate reading against
   it **using Rev 2's unchanged gates**.
6. **The AUD-04 reconciliation is STANDING and EXACT (R2):** it executes on every date both artefacts
   exist, reads AUD-04 through its versioned reader, joins on `trial_id`, and — because no exit has
   ever fired — **matches to the cent on every joined row**, with any unjoined row reported rather
   than dropped. A persistent unexplained mismatch alerts on the same re-alert ladder as
   `EXIT_CORPUS_FROZEN` (weekly `WARN`, daily `CRITICAL` at `streak ≥ 14`), never once-then-silent.
   Evidence: two consecutive dates' reconciliation lines plus the test suite.
7. `pm_us_crh_exit_v4.json` passes `load_family_manifest`'s sha validation while remaining
   `DRAFT_NOT_REGISTERED`, proven by test; **`exit_gate.py` diff is empty.**
8. RED→GREEN output for steps 1–6.
8b. **(NEW, revision 5; ANCHOR CORRECTED, revision 6) The PREREG v4 DRAFT carries a CHECKABLE
   no-peeking attestation.** Its provenance table names, per parameter, a source `doc:line`, the UTC
   timestamp of the commit that introduced that line, and a status of `ATTESTED` or
   `PROVENANCE_POSTDATES_READOUT`. **Every `ATTESTED` row's commit timestamp is at or before
   `first_exit_outcome_readout = 2026-09-16T03:36:32Z`** (§6 E; commit `84d9042`) — the first
   exit-OUTCOME readout over this corpus, **not** `corpus_first_fill_date` (`2026-09-13`), which
   precedes every design artefact by construction and therefore tests nothing. Every later row is
   flagged and carries the §6 E remedy (re-derive from pre-anchor inputs, or an explicit ruling artefact
   at registration, with the N=5 rows excluded from any confirmatory tally). Proven by the five §7 step
   7b tests — including the one driven off the real post-anchor row (`537783a`) and the one that fails a
   first-fill-date implementation. The spec's `status: DRAFT_NOT_REGISTERED` and unpinned
   `d0_climate_day` are unchanged, proven by diff. A bare prose attestation without the per-row-dated,
   per-row-classified table does not satisfy this criterion, and no flagged row may be presented as
   attested.
8c. **(NEW, revision 6) The positive control's halt-state precondition is CHECKED and REPORTED, never
   discovered at the exec veto.** The evidence artefact records the sender-global halt state read from
   `FAMILY_HALT_KEY` (`trial_day_latch.py:291`) with its source and timestamp; a set halt renders the
   positive control `BLOCKED_FAMILY_HALT_SET` — not attempted, and not recorded as a control failure —
   and the clear → act → re-set route is cited by AUD-02 id rather than improvised. Proven by the §7
   step 7c tests.
9. **Negative criterion, explicitly asserted at merge:** no order was placed, no family was
   registered, no gate was opened, no positive control was run, and no live-trading enablement was
   touched.

## 9. Validation: failure cases, integration, autonomous operation

- **Reconciliation goes the wrong way.** If the reconciled table shows R-THREAT/R-DEAD passing
  their gates, that is **not** an arming trigger — Rev 2 §4 requires the positive control, the
  registration and the operator gate first, and Rev 2 §1 is explicit that a gate passed on N ≈ 4–6
  "licenses arming for measurement, never a claim of edge". The plan's own gravity is "resume"; this
  exclusion is what resists it. (Round 1 tested this specific failure mode and found the guard
  sound; it is unchanged.)
- **The negative-delta rows turn out to be real.** Then the R-THREAT qualifying count *falls*, and
  Rev 3 says so. Closing the anomaly is allowed to make the gate reading worse; it is not allowed to
  leave it ambiguous.
- **The manifest completion becomes a silent registration.** Guarded by criterion 7's test and by an
  empty `exit_gate.py` diff. The L-22 split means both halves must move; only one does here.
- **Family binding fixed by a second literal.** Guarded by criterion 1's tests (wrapper enumeration
  + `UNBOUND` sentinel), and interacts with AUD-05: while `pm_us_crh_v4` and `pm_us_crh_cont` share
  a `trial_id_prefix`, a prefix-based resolution is ambiguous — the report keys on `family_id`, and
  where rows are ambiguous it says so rather than picking.
- **The report's zero is "fixed" by changing its universe silently.** Guarded by criterion 2: the
  report must *state* its universe and the ledger count over the same period, so a future zero is
  legible rather than interpretable.
- **Frozen-corpus alert becomes noise (over-alerting).** Bounded by the §6 D ladder's period keys: at
  most one page per UTC ISO week while the freeze is short, reaching daily only after two consecutive
  weeks of no progress. Tested in §7 step 3.
- **Frozen-corpus alert goes silent during a genuinely dead loop (under-alerting) — R2, the opposite
  failure, and the one round 1 missed.** A dead measurement loop starts indistinguishably from a
  legitimately quiet one, so a fire-once latch would give exactly one page and then nothing for the
  remaining life of the outage. Closed by the ladder's weekly re-emission and the `CRITICAL`
  escalation at `streak ≥ 14`, with restart-surviving latch state so a reboot neither re-pages nor
  loses the rung. Tested by the day-N-repeat, restart and clear-then-refire tests in §7 step 3.
- **Autonomous operation:** both jobs already run unattended on timers with `Persistent=true`. This
  item's autonomy contribution is exactly findings C and D: making a job that *cannot progress* say
  so — and, after the R2 ladder, **keep** saying so for the duration of the outage — and making a
  report that cannot see its corpus admit it, instead of both exiting 0 forever. Residual limitation,
  stated honestly: every rung of the ladder still depends on the nightly timer firing at all; a
  stopped timer is detected only by systemd unit state, not by either new signal.

## 10. Deployment, observability, rollback

- **Deploy:** merged analysis-script and wrapper changes take effect at the next 15:00Z / 15:20Z
  timer tick. No unit file changes, no node restart, **no change to trading behaviour** — the live
  family still never sells.
- **Observability:** the two nightly artefacts, the new corpus fields, the position-universe line,
  the standing reconciliation line, and the two latched alerts.
- **Rollback:** revert the commit; the timers resume the previous scripts at the next tick. Fully
  reversible, because nothing here is a state change. The latch files are derived and are recreated
  on the next run.

## 11. Relationship to portfolio-level ROI and how it is evaluated

**Channel: protective, with a small and currently-bounded structural ceiling. This item does not add
ROI and must not be presented as doing so.**

**The measured ceiling, stated honestly.** Rev 2 §0 measures that on the only clean corpus,
sell-on-DEAD recovers ~0, and even a perfect-timing oracle recovers only a fraction of the held loss
— i.e. the *structural ceiling* of any exit policy on that tape is small. Finding B means even that
number needs reconciling, and finding B2 means the timing series feeding it is not yet trustworthy.

**The evaluation path, by field.** If an exit rule is ever armed (not by this item), its realised
benefit is read through AUD-04's `realised_pnl_after_fees_total` and `capital_deployed_total` over
matched periods against AUD-04's B0/B1 baselines, cross-checked **standingly** against this study's
`sum_hold_pnl` on the overlapping rows (§6, §8 AC#6). The nightly report's intervened-vs-control /
avoided-loss / premature-exit series remain **DESCRIPTIVE only** — never the sequential endpoint,
per Rev 2 C1 and L-2.

**Plausible vs demonstrated:**

| Claim | Status |
|---|---|
| "Fixing the measurement loop prevents arming on a drifted or blind table" | **DEMONSTRATED on delivery** — AC#2, AC#4, AC#6 are each directly observable. |
| "An armed exit rule would recover value" | **NOT DEMONSTRATED, and currently measured as small** (Rev 2 §0). Not claimed here. |
| "This item changes ROI today" | **FALSE.** It changes nothing the bot does; the family still never sells. |

**Baseline.** Today's measured state, as numbers: two nightly artefacts disagreeing 0 vs 5 on the
same corpus; one unreconciled step-0 table (Σ R-BEST −0.44 vs −0.0400); one negative timing median
(−74.1) of unknown provenance; `n_positions_new_since_previous_run` unreported for 4+ consecutive
nights. Post-change: 0 silent disagreements, 1 reconciled table with stated provenance, 0 unexplained
negative-delta rows, frozen corpus alerted once per streak.

**How it is evaluated.** Binary and structural, against that baseline — never "did the exit rule
help", which this item deliberately does not answer.

**Falsifier.** If Rev 3 is published with a reconciled table while any negative-delta row is
unexplained, or if the AUD-04 cross-check is executed once rather than standingly, the item has
failed even though every artefact exists.

**Dependency ordering.** Stage 1. PRECONDITION-1 gates *corpus growth and the arming decision only*
— every measurement defect above is fixable today at N=5. Bilateral with AUD-04; interacts with
AUD-05; its **registration step only** is sequenced behind AUD-06a (DEP-3).

**Arming-decision timeline, honestly (revision 5).** With A1 ruled (ii) — `pm_us_crh_v4` may not send
orders (`RULING_A1_pm_us_crh_v4_disposition_2026-09-21.md:219-227,270-271`) — the corpus grows only
once a *future* family trades. There is therefore **no date for the arming decision and no basis for
forecasting one**; this item's value is entirely the measurement loop and the registration package,
both delivered at N=5. Any future revision claiming an arming timeline must first name the family
that will produce the fills.

## 12. Assumptions, unresolved questions, blockers

- **PRECONDITION-1 (RECLASSIFIED, revision 5 — was BLOCKER-1):** the corpus cannot grow until some
  future family trades — G-01 (nothing reaches pricing), the fee halt, and the A1 (ii) ruling against
  the entry family. Per RULING 3 item 1 (`RULING_study_units_order_ceiling_exit_prereq_2026-09-21.md:165-169`)
  this is an **unavailable-evidence precondition of the ARMING DECISION ONLY**; it is **not a blocker
  of AUD-07**, because every measurement fix (B, B2, C1–C3, D) and the registration package (A, E) are
  executable today at N=5. It remains the honest reason arming is not scheduled.
- **PRECONDITION-2 (NEW, revision 6) — the sender-global family halt:** see §4. Verified from source
  this revision, not carried from another plan's text: one literal
  `FAMILY_HALT_KEY = "continuous_rung_hold/halt"` (`trial_day_latch.py:291`), returned
  family-agnostically by `continuous_family_halt_key` (`trade_supervisor_core.py:158-170`), read by
  `submit_exit` before anything else (`exit_wiring.py:246`, veto `:270-275`, state `:1002`). Under the
  ENDORSED A1 ruling (`RULING_A1_pm_us_crh_v4_disposition_2026-09-21.md:234-246`) AUD-02b sets it for
  the entry family, so it would silently refuse `pm_us_crh_exit_v4`'s positive control and any exit.
  **Design tension, recorded honestly rather than resolved here:** a sender-global halt means an exit
  family cannot protect the positions of a halted entry family. **Acceptable today**, on two stated
  grounds — the corpus has taken no fill since 2026-09-15 (§3 D), so there is nothing to protect; and
  AUD-02b refuses to set the halt unless a pre-set open-position read says the book is flat AND known,
  with UNKNOWN treated as open (`AUD-02-edge-discovery-programme-status-and-fold-in.md:150-153,663-668,738-744`).
  A **family-scoped** halt key — which `continuous_family_halt_key`'s own docstring anticipates as a
  one-function change if cardinality-1 is ever lifted — is a separate FUTURE item, **not this one**:
  this item proposes no change to the key, the veto, or their wiring.
- **DEP-2 (RECLASSIFIED, revision 5 — was BLOCKER-2; "operator-only hard gate" STRUCK):** arming
  requires (i) PREREG v4 **REGISTRATION** — a real `d0_climate_day`, `status: REGISTERED`, `n` reset
  to 0 (`POST_FORECAST_PHASE_2026-09-20.md` §A-9 item 2, `:211,217-218`) — and (ii) the §4 step-3
  1-lot positive control, which RULING 3 item 2(b) (`:181-190`) rules is a **bot-automated step, not
  an operator gate** (`OP_SEQ_BOT_POSITIVE_CONTROL_2026-09-04.md:7,118`). Both are **sequencing**
  dependencies behind PRECONDITION-1, behind §4 steps 1–2 of the exit-execution plan (the preview
  capture must distinguish reducing from opening, `POSITION_EXIT_EXECUTION_2026-09-16.md:322-328`,
  else the control stays blocked on evidence), and behind actual registration. The **one thing that
  does remain operator-only** is live-trading **enablement** of `pm_us_crh_exit_v4` as a new,
  separately-manifested family (addendum A3, `:322-332`; standing invariant `PROGRESS.md:39-42`) —
  nothing in this plan approaches it, and `exit_gate.py` keeps an empty diff.
- **DEP-3 (RECLASSIFIED, revision 5 — was BLOCKER-3):** Rev 2 §2 registers v4's boundary by
  re-running the boundary script with unchanged inputs. Per RULING 3 item 3 (`:196-199`) this is a
  **sequencing dependency of the REGISTRATION step only** — provisional shas are mintable and
  pinnable today while the manifest stays `DRAFT_NOT_REGISTERED` (§7 step 7). If AUD-06a changes
  anything about boundary validity, v4's *registration* package inherits it. Not a blocker of this
  item.
- **Unresolved until step 0:** the C3 cause — monitor-never-flushes vs path/permission defect. The
  §6 C2/C3 fix branches on it, and §5 forbids touching the node's write path unless step 0
  establishes the second cause.
- **Unresolved until step 6:** the cause of the study drift (finding B). Three candidates are named;
  the measurement decides.
- **No longer merely "unresolved" (R1 fix):** the negative
  `median_minutes_last_executable_to_threatened = -74.1` now has a concrete closing check (§6 B2)
  that is a required sub-step of step 6 with its own acceptance criterion (AC#4) and its own tests.
  It is no longer a §12 open question.
- **Assumption:** `pm_us_crh_exit_v4`'s `composition_kind` mismatch is a drafting error, not a
  deliberate successor to the v1/v2 `current_rung_hold` composition. Verify at step 7; if it is
  deliberate, the successor relationship needs stating in Rev 3.

## 13. Review history

**Baseline self-score (2026-09-21, author), 80/100** — carried-forward weaknesses folded into the
Revision 2 table below.

### Round 1 (2026-09-21) — independent blind peer review

| Reviewer | Total |
|---|---|
| mle-reviewer (statistical validation / measurement engineering) | 80/100 |
| prediction-market-reviewer (portfolio accounting / risk) | 79/100 |

**Dispositions:**

| # | Reviewer | Defect | Disposition |
|---|---|---|---|
| 1 | mle + pm | MINOR (both, independently) — the negative `median_minutes_last_executable_to_threatened` is flagged but has no concrete closing check; it sits in §12 as an open question | **ACCEPTED IN FULL and promoted out of §12.** New §6 B2 defines the check concretely: a per-row `delta_i = threatened_confirmed_ts − last_executable_exit_ts` classification into `THREATENED_BEFORE/AFTER_EXIT_SIDE_EMPTIED`, a rule that **the reconciled table may not be published while any negative-delta row is unexplained**, two RED tests covering BOTH orderings with fixtures through the real writer path (L-42), and — the part neither reviewer asked for but the gate requires — a stated consequence: the R-THREAT gate is read **per row**, so `AFTER` rows do not count toward "≥3 firing before the exit side empties", even if that lowers the qualifying count. §7 step 6 makes it a required sub-step, AC#4 makes it a criterion, §9 accepts that closing it may make the gate reading worse. |
| 2 | pm | MINOR — no standing AUD-04↔AUD-07 reconciliation; both plans state only a one-shot cross-check | **ACCEPTED, on both sides.** §6 adds a standing reconciliation executed on every date both artefacts exist, read through AUD-04's `schema_version` reader (never by re-parsing Markdown), with a latched `EXIT_PNL_RECONCILIATION_MISMATCH`. Three tests (§7 step 5), AC#6. AUD-04's §8 AC#4 carries the mirror obligation in the same revision round. |
| 3 | both | The position-monitor report's actual position-sourcing code path is not located; step 1 hides real discovery work | **ACCEPTED, and LOCATED by inspection today.** §3 C is rewritten as three findings with file:line: **C1** the family label is the default literal `_DEFAULT_MONITORED_FAMILY_ID = "pm_us_crh_cont"` (`position_monitor_nightly_report.py:119`) used because the wrapper's `ARGS` block (`position-monitor-report-run.sh:102-106`) never passes the optional `--family-manifest` (`:863-870`) — the report is **unbound**, not mis-bound; **C2** the report's universe is `read_monitor_summaries(--summaries-dir)` (`:873`) joined to `ScoredTrial` by `trial_id` (`_settle_summaries:429-470`), so `scored_trials=0 summary=0` is downstream of an EMPTY summaries list and is NOT evidence the scored store is empty, while the study's `n_positions=5` comes from `read_filled_trials_state_db` (`current_rung_hold_exit_window_study.py:94,452`) — **two different position universes**; **C3** verified read-only that `<catalog_root>.parent/monitor/` does not exist on disk at all, though the wrapper (`:41-42`) and the node (`composition.py:563,663`) derive the same path — so the monitor has apparently never written a summary. Step 0 must determine *why* (never-flushes vs path defect), and §5/§6 branch the fix on the answer, with an explicit prohibition on touching the node's write path unless the second cause is established. |
| 4 | mle | MINOR — the `EXIT_CORPUS_FROZEN` alert's dedupe/latch mechanism is unspecified | **ACCEPTED.** §6 D specifies the latch file path, its three fields, the increment/reset rule, and the exact emit condition (`streak == 3` while `last_alerted_streak < 3`), plus re-arm on reset. Two tests (§7 step 3), AC#3. |
| 5 | both | "Portfolio objective alignment" 5/10 — headline value depends on a corpus blocked by another gap | **ACCEPTED in cause, REJECTED as a reason to overstate the item.** The cause was that §11 asserted "protective, near zero" without an evaluation contract. §11 now gives the measured ceiling, the field-level path into AUD-04 with the standing cross-check, a three-row plausible-vs-demonstrated table whose last row states flatly that this item changes ROI **not at all** today, a numeric baseline (0-vs-5, −0.44 vs −0.0400, −74.1, 4+ unreported nights) with the post-change target, an evaluation rule, a falsifier and the dependency stage. Crucially §4 and §12 now state that BLOCKER-1 blocks **corpus growth only** — every measurement fix here is executable today at N=5 — which is what the reviewers' "depends on a blocked corpus" concern actually resolves to. |

**Rejections:** none. Two remedies were extended beyond what the reviewers asked (#1's per-row gate-reading consequence; #2's mirror obligation in AUD-04). All three blockers remain blockers; BLOCKER-2 is an operator-only hard gate no reviewer may resolve.

**Revision 2 self-score (2026-09-21, author), 89/100:**

| Criterion | Max | Score | Named remaining weakness |
|---|---|---|---|
| Fidelity to the gap and completeness | 20 | 18 | Extends EXIT-1 rather than duplicating it, keeps arming strictly out of scope, and surfaces four defects (B, B2, C, D) the audit did not name. Still loses points because G-12's literal content — "exit seam built, unarmed" — is addressed by explaining why it stays unarmed rather than by advancing toward arming. |
| Technical correctness and evidence grounding | 20 | 18 | Every finding is read from a live artefact or a source line inspected today, and finding C is now a three-part located diagnosis with file:line and an on-disk verification, not a symptom. Loses points because the drift's cause (B) remains three competing hypotheses, and C3's underlying reason is still a step-0 determination. |
| Implementation specificity and feasibility | 15 | 14 | The sourcing path, the default-literal, the wrapper's missing argument, the two position universes, the latch file's schema and the per-row anomaly classification are all named with file:line. Loses a point because the C2/C3 fix branches on a step-0 finding, so one of the two branches is specified at a coarser grain than the other. |
| Acceptance criteria and validation quality | 20 | 18 | Measurable, with a negative criterion, a cross-artefact reconciliation that is now standing, and an anomaly that must be closed rather than observed. Loses points because criterion 1's and 3's three-consecutive-night clocks make the acceptance window at least three days. |
| Autonomous operation, failure handling, recovery | 15 | 14 | Two genuine autonomy fixes (a job that cannot progress says so; a report that cannot see its corpus admits it), each with a fully specified latch and false-page discipline. Loses a point because both alerts depend on the nightly timers themselves running — a timer that stops firing is still detected only by systemd state. |
| Portfolio objective alignment, scope, dependencies | 10 | 7 | §11 now carries the measured ceiling, the field-level evaluation path with a standing cross-check, an explicit "changes ROI not at all today" row, a numeric baseline and a falsifier; and §4/§12 correct the dependency story — BLOCKER-1 blocks corpus growth only, not this item's fixes. Still mid-range because the item's *headline* value (an arming decision) genuinely cannot be reached until trading resumes. |

### Round 2 (2026-09-21) — independent blind peer review

| Reviewer | Total |
|---|---|
| prediction-market-reviewer (portfolio accounting / risk) | 91/100 |
| mle-reviewer (statistical validation / measurement engineering) | 81/100 |

**Round-2 readiness is the LOWER of the two: 81/100.**

**Dispositions (every defect, both reviewers):**

| # | Reviewer | Severity | Defect | Disposition |
|---|---|---|---|---|
| 1 | mle | MATERIAL | `EXIT_CORPUS_FROZEN` and `EXIT_PNL_RECONCILIATION_MISMATCH` fire once per streak and then go permanently silent for an indefinite outage — and the live record is already at or past that firing point | **ACCEPTED in full; the reviewer is right, including that round 1 designed this deliberately and that §9 addressed only the over-alerting half.** §6 D now adopts **by reference and without variation the re-alert ladder specified in AUD-04 §6 D8** (the two were explicitly designed as mirrors, and round 2 required an identical resolution): `WARN` once per UTC ISO week at `3 ≤ streak ≤ 13`, escalating to `CRITICAL` once per UTC day at `streak ≥ 14` — the daily cadence matching AUD-05 §6 D-F. The latch file `.frozen_streak.json` is re-specified with `streak`, `first_frozen_utc_day`, `last_alert_severity`, `last_alert_period_key`, **surviving restarts** (a period key already alerted at never re-pages; a missed period is picked up on the next run; a missing/corrupt latch fails loud). The clear condition emits one `INFO` `EXIT_CORPUS_FROZEN_CLEARED` and fully re-arms; escalation is one-way within a streak. `EXIT_PNL_RECONCILIATION_MISMATCH` rides the same ladder with its own latch keys. The WP-R1 false-page discipline is explicitly preserved and argued, not waived: at most one page a week while the freeze is short. |
| 2 | mle | MINOR | AC #3 and AC #6 assert the single-shot latch as correct, locking the gap in as intended behaviour | **ACCEPTED.** Both are rewritten to the ladder. AC #3 now requires the weekly-`WARN` / daily-`CRITICAL` sequence, period-key dedupe across restart, and the clear-and-re-arm path, and notes the live record is already past the trigger so the behaviour is verifiable on day one. AC #6 requires the mismatch alert on the same ladder. §9 gains a new failure case for the **under**-alerting half, which round 1 missed, alongside the existing over-alerting entry; §7 step 3 replaces the two single-shot tests with six ladder tests. |
| 3 | pm | MINOR | "Overlapping positions" in the AUD-04↔AUD-07 reconciliation is not defined precisely enough to implement (by `trial_id`? `(instrument_id, fill_ts)`? station-day?), and the reason the two should match exactly today is unstated | **ACCEPTED.** §6 defines overlap as the **inner join on `trial_id`** — the one key both artefacts already carry — and AUD-04 §8 AC#4 is edited in the same revision to state the identical definition, so the two sides cannot drift. The reviewer's reasoning is adopted and grounded: until any exit fires, "hold" and "actual" are definitionally the same outcome because the live family never sells, verified at `exit_gate.py:55 _EXIT_RULE_REGISTERED_FAMILIES = frozenset({"pm_us_crh_exit_v4"})` with that family staying `DRAFT_NOT_REGISTERED` per §5 — so the reconciliation must match **to the cent on every joined row**, and a partial mismatch is an alarm, not expected slack. The post-arming revision trigger is stated. Two new tests in §7 step 5; AC #6 restated. |
| 4 | pm | MINOR | `test_the_report_states_its_position_universe_and_the_ledger_count...` asserts only that a count is *stated*; two independently-wrong ledger reads that agree would pass AC #2 | **ACCEPTED.** §7 step 1 adds `test_the_reports_stated_ledger_count_matches_an_independent_second_read_of_the_ledger`, deriving the count a structurally different way — a direct read-only count of `DurableFillRecord` rows (`src/breezy/adapters/polymarket_us/exec/client.py:641`) under `FILL_KEY_PREFIX` (`:384`) via the `mode=ro` idiom at `fill_time_count.py:84-98`, the same ledger AUD-04 reads. Deliberately **not** gated on AUD-04 shipping: the second read is the independent check today, and AUD-04's versioned reader becomes an additional comparison once available. AC #2 restated to require verification, not statement. |
| 5 | mle | scoring note | Portfolio alignment 7/10 attributed to a structural ceiling, with **no named defect** ("I do not deduct further here"; "no remaining defect in it") | **RECORDED, no change made — round 3 must justify or award.** The prediction-market reviewer scored the same §11, unchanged, at **10/10**, stating the item's honest zero-contribution framing is correct and that no operator ruling is required to reach full marks. A deduction with no named defect and no requested change is not actionable. If round 3 deducts here it must name a concrete gap; otherwise the points should be awarded. |

**Rejections:** none. No scope removed and no criterion softened — AC #2, #3 and #6 were each tightened. The arming exclusion is untouched: `exit_gate.py` still takes an empty diff, the manifest stays `DRAFT_NOT_REGISTERED`, no order is placed and no gate is opened by this item. BLOCKER-1/2/3 remain blockers; BLOCKER-2 in particular is operator-only and no part of this revision approaches it.

**Revision 3 self-score (2026-09-21, author) — deliberately conservative, scored against the lower round-2 total:**

| Criterion | Max | Score | Named remaining weakness |
|---|---|---|---|
| Fidelity to the gap and completeness | 20 | 17 | Extends EXIT-1 rather than duplicating it and surfaces four defects the source audit did not name. Unchanged honest shortfall: G-12's literal ask (an armed or advancing-toward-armed seam) is answered by explaining why arming stays out of reach, not by narrowing the distance to it. |
| Technical correctness and evidence grounding | 20 | 17 | Every load-bearing citation survived two independent re-verifications, including the live on-disk absence of `monitor/`; the R2 additions cite `exit_gate.py:55`, `client.py:641`/`:384` and `fill_time_count.py:84-98`. Does not claim more: finding B is still three competing hypotheses until step 6 runs, so the item's central reconciliation is open at plan time. |
| Implementation specificity and feasibility | 15 | 12 | Sourcing path, default literal, missing wrapper argument, the two position universes, the ladder schema and the per-row anomaly classification are all named with file:line. Loses points for the C2/C3 branch-on-step-0 asymmetry, and because the ladder's period-key computation is shared with AUD-04 — if the two implementations diverge, nothing in either plan detects it. |
| Acceptance criteria and validation quality | 20 | 16 | AC #2 now demands independent verification, AC #3 tests the ladder instead of asserting the defect, AC #6 pins the join key and cent-exactness; the negative criterion (no order, no registration, no gate opened) is retained. Loses points because AC #6 cannot be exercised until AUD-04 ships, and AC #1/#3 need multi-night windows. |
| Autonomous operation, failure handling, recovery | 15 | 12 | The ladder closes the round-2 MATERIAL gap: a job that cannot progress now keeps saying so, with restart-surviving latch state and an escalation rung. Held well below full marks — every rung still depends on the nightly timer firing, and a stopped timer is caught only by systemd state, which this item does not fix. |
| Portfolio objective alignment, scope, dependencies | 10 | 7 | §11 states the measured structural ceiling, a field-level path into AUD-04 with a standing cross-check, a numeric baseline and a falsifier, and flatly concedes this item changes ROI not at all today. Held at the lower reviewer's mark pending round 3 naming a defect or awarding the points (disposition #5). |

### Round 3 (2026-09-21) — independent blind peer review

| Reviewer | Total |
|---|---|
| prediction-market-reviewer (portfolio accounting / risk) | 87/100 |
| mle-reviewer (statistical validation / measurement engineering) | 83/100 |

**Round-3 readiness is the LOWER of the two: 83/100.**

**Dispositions (every defect, both reviewers):**

| # | Reviewer | Severity | Defect | Disposition |
|---|---|---|---|---|
| 1 | mle (joint with AUD-04's record) | MINOR, elevated to required | The ladder is "adopted by reference and without variation" from AUD-04 but re-implemented in a second module with a second latch file; nothing enforces that the two period-key computations and streak transitions stay identical. Self-conceded in revision 3's §12 but carried as an accepted weakness rather than fixed | **ACCEPTED and closed by shared code, not by a cross-test.** §6 D now adopts the ladder **by import**: AUD-04 owns `src/breezy/runtime/alert_ladder.py` and the single `tests/unit/test_alert_ladder.py`; this item imports it and re-specifies none of it. §7 step 3 is re-headed so its test list is explicitly this control's local wiring (its event names, its latch file, its `n_positions_new_since_previous_run == 0` predicate) and references the shared module for the state machine, rather than restating those cases. The dependency is **AUD-07 → AUD-04 by id, acyclic** — AUD-04's reciprocal obligation is a data read of this item's published artefact at report time, never an import. A **ship-order contingency** covers this item landing first: ladder inline plus a RED-on-divergence cross-test over an ISO-week and a year boundary, deleted in the same commit that switches to the shared import. Forking the ladder permanently is prohibited. |
| 2 | pm | MINOR | §6 A instructs setting `taker_fee_coefficient` "to the coefficient in force at registration", a value that cannot be known when this item runs; suggests either pinning today's live `0.0695` as provisional or marking the field `TBD_AT_REGISTRATION` | **ACCEPTED as a defect; BOTH proposed remedies REJECTED with evidence, and a third adopted.** Read from source: `load_family_manifest` matches `taker_fee_coefficient` against `_TAKER_FEE_COEFFICIENT_RE` — a leading `0.` plus one to six decimal digits — then requires `0 < θ < 1` (`family_manifest.py:290-308`); the key is in `_REQUIRED_KEYS` (`:109`) and `_STRING_FIELDS` (`:123`) and the allowed-key set is closed. So `"TBD_AT_REGISTRATION"` would make the manifest **unloadable**, and an extra provenance key would be refused. Pinning a literal in the plan is equally wrong — a stale pinned θ is exactly what produced the 09-17 fee drift. Adopted instead: the field keeps a parseable **provisional** decimal whose value is **read at write time from the live fee source** the node itself asserts against (`assert_fee_schedule_known` / `_guarded_fee_coefficient`, `continuous_strategy.py:2504-2512`), never typed into this plan; **this plan states no coefficient value anywhere**; the consumer keeps reading it from the manifest at run time (`app/trade.py:239`, `:285`, `required_fee_coefficient=manifest.taker_fee_coefficient`); and the provisional status, source and re-verification requirement are recorded in the evidence artefact, which has no schema constraint. Two RED tests added. |
| 3 | pm | required change 3 | State which of C2/C3's two branches is expected to be specified at finer grain, or bring both to parity | **ACCEPTED.** §7 step 0 now states in advance that branch (a) is the finer-grained one and why (the wrapper's and `composition.py:563,663`'s path derivations agree by construction, so a path defect is the less likely cause), and that branch (b) is deliberately specified only to "name the divergent path and permission bits, then re-scope" — with the explicit rule that selecting (b) **re-scopes §6 C2/C3 in a revision before any code is written**, rather than implementing against a guess. |
| 4 | pm | required change 1 | Finding B (the Rev 2 / current-nightly artefact drift) remains three hypotheses until step 6 runs | **ACCEPTED as accurate, no change.** The reviewer classifies it as "a plan-execution gap, not a plan-text gap"; it is correctly deferred to step 6 and is named in the self-score rather than resolved on paper. |
| 5 | mle | verification | The independent-second-read test genuinely uses three distinct code paths; the B2 negative-delta per-row classification is methodologically sound; the weekly-first-repeat cadence is proportionate; `exit_gate.py:55` and `client.py:641`/`:384` re-verified exact | **NOTED, no change.** |
| 6 | both | scoring note | §11 awarded 10/10 by both reviewers with no named defect, resolving round-2 disposition #5 | **RESOLVED and awarded** — the revision-4 self-score raises this criterion from 7/10 to 10/10. |

**Rejections:** two sub-remedies within disposition #2, both evidenced against `family_manifest.py:109`/`:123`/`:290-308` — the `TBD_AT_REGISTRATION` sentinel (unloadable) and a plan-pinned `0.0695` literal (a stale pin of the kind that caused the 09-17 drift). The underlying defect is accepted in full and remedied by reading the value from the live source at write time. **No scope was removed and no criterion softened.** BLOCKER-1, BLOCKER-2 and BLOCKER-3 all stay blockers; BLOCKER-2 is operator-only.

**Points withheld in round 3 without a named defect or requested change — round 4 must justify or award:**

- **mle, "Fidelity" 17/20, "Technical correctness" 17/20, "Acceptance criteria" 16/20, "Autonomous operation" 12/15.** All four are recorded as "matches round 2/3 self-score", with the record's only required change being the shared ladder (now closed) and its own verification section finding every citation exact. The "Autonomous operation" deduction cites only the timer-firing dependency, which is a property of any scheduled unit and carries no requested change.
- **pm, "Autonomous operation" 13/15.** Same timer-firing dependency, explicitly described as "a limitation the plan states honestly but does not close" — no fixable gap named.
- **pm, "Acceptance criteria" 17/20.** The −3 is attributed to AC #6 being unexercisable until AUD-04 ships and AC #1/#3 needing multi-night windows, both of which the record calls "a real, named cross-plan dependency, not softened" — i.e. correctly handled, not a defect.

**Revision 4 self-score (2026-09-21, author) — deliberately conservative, scored against the lower round-3 total (83):**

| Criterion | Max | Score | Named remaining weakness |
|---|---|---|---|
| Fidelity to the gap and completeness | 20 | 17 | Extends EXIT-1 rather than duplicating it and surfaces four defects the source audit did not name. Loses points, as in rounds 2 and 3, because G-12's literal ask (an armed or advancing-toward-armed seam) is answered by explaining why arming stays out of reach rather than by narrowing the distance to it. |
| Technical correctness and evidence grounding | 20 | 18 | Every load-bearing citation re-verified; the fee-coefficient question is now answered against the manifest loader's actual validation rules rather than by adopting either proposed remedy on trust. Loses points because finding B is still three competing hypotheses until step 6 runs. |
| Implementation specificity and feasibility | 15 | 12 | The ladder is now one imported module rather than a second implementation, and the fee-coefficient write path, its source and its two tests are named. Loses points because the C2/C3 branch asymmetry is now *declared* rather than removed (branch (b) still re-scopes rather than being pre-designed), and because this item's ladder wiring is sequenced against a module AUD-04 has not shipped. |
| Acceptance criteria and validation quality | 20 | 17 | AC #2's independent second read, AC #3's ladder tests and AC #6's cent-exact join stay concrete and machine-checkable, now over a single-sourced ladder. Loses points because AC #6 cannot be exercised until AUD-04 ships and AC #1/#3 need multi-night acceptance windows. |
| Autonomous operation, failure handling, recovery | 15 | 13 | The ladder is restart-surviving, one-way-escalating and now impossible to drift from AUD-04's copy because there is only one copy. Loses points because every rung still depends on the nightly timer firing at all. |
| Portfolio objective alignment, scope, dependencies | 10 | 10 | §11 states the measured structural ceiling, a field-level path into AUD-04 with a standing cross-check, a numeric baseline and a falsifier, and flatly concedes this item changes ROI not at all today; both round-3 reviewers awarded 10/10 with no named defect. |

**Latest score:** 87/100 (Revision 4 self-score); round-3 peer readiness 83/100.
**Readiness: NOT READY — round 4 peer review closed at 100/100 (both reviewers); revision 5 applies a ruling and has not itself been reviewed. The recorded blockers are RECLASSIFIED below, not resolved.**

### Round 5 (2026-09-21) — ruling application, no peer review

Source: `docs/evidence/RULING_study_units_order_ceiling_exit_prereq_2026-09-21.md` RULING 3 (`:156-199`)
and Revision 2 addendum A3 (`:322-332`), peer-ENDORSED at
`docs/evidence/reviews/RULING_study_ceiling_exit_review_2026-09-21.md:67`; plus the endorsed
`docs/evidence/RULING_A1_pm_us_crh_v4_disposition_2026-09-21.md`.

| # | Recorded blocker / statement | Ruling | Change made |
|---|---|---|---|
| 1 | "Exit corpus frozen until trading resumes" stated as blocking the item | RULING 3 item 1 (`:165-169`) | **RECLASSIFIED to PRECONDITION-1** — a genuine unavailable-evidence precondition of the **arming decision only**. §4, §11 and §12 now say every measurement fix and the registration package are executable today at N=5. No scope removed. |
| 2 | "PREREG v4 + the operator positive control", carried as an operator-only hard gate | RULING 3 item 2(a)/(b) + conservative guard (`:171-195`) | **RECLASSIFIED to DEP-2**, "operator-only hard gate" STRUCK. New §6 E and §7 step 7b complete the **existing** DRAFT spec (`docs/specs/PREREG_v4_crh_exit_DRAFT_2026-09-16.md`) with a dated provenance table and a checkable no-peeking attestation (new AC #8b). The 1-lot control is recorded as **bot-automated** (`OP_SEQ_BOT_POSITIVE_CONTROL_2026-09-04.md:7,118`), excluded by **sequencing** behind PRECONDITION-1, §4 steps 1–2 (`POSITION_EXIT_EXECUTION_2026-09-16.md:322-328`) and actual registration. |
| 3 | "AUD-06a boundary result" as a blocker | RULING 3 item 3 (`:196-199`) | **RECLASSIFIED to DEP-3** — a sequencing dependency of the **registration step only**; provisional shas are mintable today. |
| 4 | Authorisation chain unstated | Addendum A3 (`:322-332`) | §5 now states it: `pm_us_crh_exit_v4` is a new separately-manifested family (`deploy/families/pm_us_crh_exit_v4.json`, `src/breezy/persistence/exit_gate.py:55`); the 09-16 ruling is class-scoped (`POSITION_EXIT_EXECUTION_2026-09-16.md:8-12`); **live-trading enablement stays operator-only** (`docs/core/PROGRESS.md:39-42`). |
| 5 | Arming timeline implied by "until trading resumes" | `RULING_A1_...:219-227,270-271,3` | §4 and §11 state honestly that with A1 ruled (ii) the corpus grows only when a **future** family trades, so **the arming decision has no date**; priority stays P2 because the deliverable is the measurement loop, not the arming decision. |

**Verified during this revision:** the PREREG v4 DRAFT already exists at
`docs/specs/PREREG_v4_crh_exit_DRAFT_2026-09-16.md` (`:3` status, `:20` d0 unpinned, `:116` boundary
re-run-and-pin). The ruling's "author the DRAFT" is therefore satisfied in substance; step 7b adds the
provenance and attestation it lacks rather than creating a second spec.

**Nothing was removed, softened or armed.** All §5 exclusions stand; `exit_gate.py` still takes an
empty diff; no order, registration, positive control or enablement is authorised by this revision.
Revision-5 self-score is not restated — the round-4 peer record stands, and the reclassifications
above change the item's dependency story, not its technical content.

### Round 6 (2026-09-21) — defect application from the round-5 blind peer records

Sources: `reviews/AUD-07-r5-mle-reviewer.md` (95/100) and
`reviews/AUD-07-r5-prediction-market-reviewer.md` (90/100).
**Round-5 peer readiness is the LOWER of the two: 90/100.**

| # | Reviewer | Severity | Defect | Disposition |
|---|---|---|---|---|
| 1 | mle | MATERIAL | §6 E / §7 step 7b / AC #8b anchor the no-peeking check on `corpus_first_fill_date`, which precedes the 09-16 design doc and DRAFT spec — so the check fails on real data or tests the wrong boundary | **ACCEPTED, with the chronology established from the repo rather than from the plan's own text.** Verified: corpus first fill `2026-09-13` (`POSITION_EXIT_EXECUTION_2026-09-16.md:478`), last fill `2026-09-15`; Rev 2 design doc `ebe7c46` 03:00:51Z; DRAFT spec `bdcfd38` 03:06:57Z (pre-anchor edit `7c558a5` 03:24:56Z); **first exit-OUTCOME readout `84d9042` 03:36:32Z** (Appendix A.3, R-DEAD 0/5 / R-THREAT 1/5; artefact mtime 03:45:42Z after the L-44 sign correction); §5b cover `537783a` 05:52:43Z. §6 E now fixes the anchor at `first_exit_outcome_readout = 2026-09-16T03:36:32Z`, carries that six-row chronology, and records provenance at **introducing-commit-timestamp** granularity because both source documents are named `...2026-09-16` yet were edited repeatedly through that day. **The check is not weakened into an unfalsifiable attestation:** rows at or before the anchor are `ATTESTED`; later rows are flagged `PROVENANCE_POSTDATES_READOUT` with a registration-time remedy (re-derive from pre-anchor inputs, or an explicit ruling artefact with the N=5 rows excluded from any confirmatory tally — which the `n`-resets-to-0 rule already enforces). **One flagged row exists today and is named**: §5b's two-layer AMBIGUOUS-exit cover. §7 step 7b's RED list and AC #8b are rewritten to the corrected boundary, including a test that FAILS a first-fill-date implementation and one driven off the real flagged row. |
| 2 | pm | MATERIAL | `FAMILY_HALT_KEY` is sender-global, not family-scoped, and the endorsed A1 ruling sets it for the entry family via AUD-02b — so `pm_us_crh_exit_v4`'s positive control and any exit would be silently refused; the plan never states it | **ACCEPTED in full, re-verified from source rather than from the review.** New **PRECONDITION-2** in §4 and §12 (`trial_day_latch.py:291`, `:1002`; `trade_supervisor_core.py:158-170`; `exit_wiring.py:246,270-275`; `RULING_A1_pm_us_crh_v4_disposition_2026-09-21.md:234-246`). §5 makes a halt-state read **step (0) of the positive-control sequence, ahead of (i)-(iv)**: halted → `BLOCKED_FAMILY_HALT_SET`, never attempted and never recorded as a control failure, with AUD-02's documented **clear → act → re-set** route cited by id (`AUD-02-edge-discovery-programme-status-and-fold-in.md:668,742`) and AUD-02b named as owner of the missing set path. New §7 step 7c (three read-only RED tests, no order built or sent) and new AC #8c. The design tension is recorded honestly in §12 — a sender-global halt means an exit family cannot protect a halted entry family's positions; acceptable today (no fill since 09-15; AUD-02b refuses to set while the book is non-flat or UNKNOWN), and a family-scoped key is a separate FUTURE item, not this one. |

**Rejections:** none. **No scope removed, no criterion softened, no gate loosened** — AC #8b's boundary
was corrected and tightened (a flagged row may never be presented as attested) and AC #8c is new.
`exit_gate.py` still takes an empty diff; no order, registration, positive control or live-trading
enablement is authorised by this revision, and this item still sends nothing.

<!-- COORDINATOR FINAL STATUS — appended after review; everything above this line is the reviewed revision -->

## Coordinator final status (2026-09-22) — authoritative

This block supersedes any score or readiness wording in §13 above, which plan revisers wrote
before review closed.

- **Reviewed revision sha256** (file content above the marker line): `911f5b8bf978a3a7f4ee69c68bedb0148b45c80bc4f84352dd6365f1b4b3da3f`
- **Baseline self-score:** 80/100
- **Final score (lowest reviewer, never averaged):** 100/100
  - `mle-reviewer` round 6: 100/100 — `reviews/AUD-07-r6-mle-reviewer.md`
  - `prediction-market-reviewer` round 6: 100/100 — `reviews/AUD-07-r6-prediction-market-reviewer.md`
- **Readiness:** **READY**
- **Unresolved blockers / notes:**
  - None on this item's own scope (measurement fixes, the PREREG v4 DRAFT provenance/attestation, the halt-state precondition). This item arms nothing.
  - Preconditions of the later ARMING DECISION, outside this item: exit-corpus growth needs a family that trades; registration is sequenced behind AUD-06a; the sender-global family halt (AUD-02b) blocks the positive control while set; live-trading enablement of `pm_us_crh_exit_v4` is operator-only.
  - One spec element (PREREG v4 §5b) is flagged `PROVENANCE_POSTDATES_READOUT` rather than attested.
- **Full review history:** 12 records, `reviews/AUD-07-r*-*.md`
- Planning only. Nothing in this plan has been implemented.
