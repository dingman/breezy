# EDGE-5 — Dependency-ordered roadmap to a new A1-class re-arm ruling (plan r4, 2026-09-27)

**Author:** trading-bot-architect, revising r3 per coordinator round-3 ruling (python APPROVE; domain
REQUEST_CHANGES on wording; architect REQUEST_CHANGES on 5 blocking items). **Class:** CRIT programme
plan, build-time only. Authorises no order, no operator value, no live-trading enablement.

## r3→r4 changes

1. **[architect BLOCK 1] Triage input seam, added (NEW item RA-9c).** `hypothesis_triage.py:157`
   hardcodes the champion's `replay/replay_results.jsonl` path, so `candidate_replay_results.jsonl`
   (RA-9b's own output) could never reach `_triage_record` as written — RA-9b's "produces a take
   reaching `hypothesis_triage.py`" deploy-verification bullet (r3 §8) was therefore unbuildable as
   scoped. **RA-9c (NEW)**: `run()`'s single hardcoded source path becomes a small, explicit, ordered
   list of `(source_label, path)` pairs, threaded from a caller-supplied argument with the champion's
   own `replay_results.jsonl` as the ONLY entry when the argument is omitted — never a silent multi-path
   default. New RED `test_a_candidate_replay_row_reaches_triage_via_the_named_input_seam` constructs the
   seam with two sources and asserts a `candidate_replay_results.jsonl` row is visible to
   `_triage_record`; existing champion-only regression
   `test_triage_with_no_seam_argument_reads_only_replay_results_jsonl_byte_identically` pins the
   omitted-argument path unchanged. See §5.
2. **[architect BLOCK 2] O6 source corrected — trial-level, not row-level (RA-9b revised).** `run_ts`
   (`replay_daily_runner.py:1113`) is the runner's own wall clock at write time, not a take time, and
   `ReplayResult` is one row per **station-day**, not per take — deriving `hour_lst` from `run_ts` would
   have produced a single, wrong hour for a station-day that took in several different hours. **Corrected
   join:** `hour_lst` is derived per `FilledTrial` (`trial_scorer.py:83`, `filled_at_ns` at line 121 of
   that file) by calling `_local_hour(trial.filled_at_ns, std_utc_offset_hours)` (`strategy.py:214`)
   against each trial row read from the candidate unit's own `scored_trials_*.parquet`, using the
   station's `std_utc_offset_hours` already resolved by `default_registry().climate_day_window(...)`
   (`strategy.py:325-328`) — never a schema field on `ReplayResult` (O6, still PRIMARY). **Station-days
   with takes in several hours are POOLED AT THE TRIAL LEVEL, never at the station-day level**: each
   `FilledTrial` is individually classified into `{00-08, 17-23}` or excluded; a station-day with, say,
   one take at hour 03 and one at hour 14 contributes only the hour-03 trial to the pooled draw
   population — it is neither wholly included nor wholly excluded by virtue of having a mixed day. RA-9b's
   read layer filters at the trial level BEFORE aggregating to the per-station-day draws
   `hypothesis_triage.py` consumes (`_draw_for_station_day`, `station_day_mean_x`), so the ledger's
   existing station-day-clustered statistics keep their current shape unchanged; only the trial admission
   filter is new.
3. **[architect BLOCK 3] Strategy-class seam corrected — constructor-level, `_hunt_tick` untouched
   (RA-9b revised, r3's four-method plan retired).** Confirmed via codegraph: `_hunt_tick`
   (`continuous_strategy.py:1810-2144`, one method on the shared, LIVE `ContinuousRungHoldStrategy`, not
   `ContinuousRungHoldBacktestStrategy`) reads `_WINDOW_START_HOUR_LST`/`_WINDOW_END_HOUR_LST` as bare
   module names at `:1983` (imported from `strategy.py:154-155` at `continuous_strategy.py:91-92`), and
   calls the free function `evaluate_both_sides(...)` directly at `:2111` to produce `both_sides.yes`
   (the P_HOLD-gated YES decision) and `both_sides.no` (the shadow-only NO decision) — there is no
   existing hook to swap either. `minutes_since_window_open` (`:2245`) hardcodes the window length as the
   literal `12`. r3's plan to give `PooledOffWindowBacktestStrategy` a fourth override method
   duplicating/reimplementing `_hunt_tick`'s ~330 lines of gate logic (family halt, budget, latch,
   dedupe, refusal counters) is **retired** — it would break the byte-inherited discipline
   `continuous_backtest_only.py:47-51` exists to protect, for no reason the estimand requires.
   **Adopted instead (coordinator preference, minimal seams):** `ContinuousRungHoldStrategy.__init__`
   gains two new, defaulted, keyword-only constructor parameters —
   `window_start_hour_lst: int = _WINDOW_START_HOUR_LST`, `window_end_hour_lst: int =
   _WINDOW_END_HOUR_LST` — stored as `self._window_start_hour_lst`/`self._window_end_hour_lst`, read by
   `_hunt_tick:1983` and `minutes_since_window_open:2245` (replacing the literal `12` with
   `self._window_end_hour_lst - self._window_start_hour_lst`) in place of the bare module names. A THIRD
   parameter, `compose_decision: Callable[..., BothSides] = evaluate_both_sides`, stored as
   `self._compose_decision`, replaces the direct call at `:2111` with `self._compose_decision(...)` —
   identical arguments, identical default target function, so a live champion constructed with no
   overrides is byte-identical. `PooledOffWindowBacktestStrategy` needs no new override method at all: it
   passes non-default `window_start_hour_lst=0, window_end_hour_lst=8` (or the `{17,23}` half, composed
   as two candidate manifests or one manifest with a two-range window — RA-9's ruling artefact fixes
   which) and a non-default `compose_decision` at construction time. Its own AST pin reverts to the SAME
   **three**-method shape as `ContinuousRungHoldBacktestStrategy` (`__init__`, `on_start`,
   `_submission_armed`) — the separate four-method pin r3 introduced is dropped. **New REDs:**
   `test_hunt_tick_defaults_to_the_module_window_constants_and_evaluate_both_sides_byte_identically`
   (regression, pins the live champion's unchanged behaviour under default construction),
   `test_hunt_tick_honors_an_injected_window_and_composition_function_for_a_candidate_hypothesis`.
   **The concrete non-`P_HOLD` TAKE RULE is not invented in this roadmap.** It must be a price-only
   condition that never reads `running_max`/`P_HOLD_LOWER`/`P_HOLD_UPPER` — e.g. of the shape "take iff
   the executable leg's price clears `1 − taker_fee_coefficient − slippage_allowance − margin`" — and RA-9's
   two-peer ruling artefact must state the exact formula and margin value BEFORE RA-9b implements
   `compose_decision`'s replacement body; RA-9b's own file plan (§5) adds a RED test named for whatever
   formula that ruling states, not the placeholder name r3 used.
4. **[architect BLOCK 4] AUD-12 moves upstream of RA-10's first look, not merely AC-2's cosmetic effect
   (critical-path reorder).** Confirmed via codegraph: `_triage_record` (`hypothesis_triage.py:548-551`)
   skips a hypothesis with reason `"C_VALIDITY"` and returns **no look at all** whenever ANY row in
   `completed` fails `_passes_c_validity` — and `_passes_c_validity` reads the same `validity` field
   RA-3's `_append_terminal` branch controls, which defaults to `MECHANISM_ONLY` until
   `AUD11_AND_AUD12_LANDED` is `True` (r3 §2/§5, unchanged). `promotion_criteria.py:427` independently
   rejects `MECHANISM_ONLY` rows for the same reason. **This means every row RA-9b's candidate-replay unit
   produces is `MECHANISM_ONLY` until AUD-12 lands, so RA-10 can accrue (write) rows but its FIRST LOOK —
   and therefore any CONFIRMED/REJECTED disposition, and therefore RA-11/RA-12/RA-13 — is structurally
   blocked until AUD-12 lands, independent of RA-9/RA-9b/RA-10's own progress.** r3's framing (AUD-12 as
   an "undated side precondition on AC-2's real-world effect," §0/§9/§11) understated this: AUD-12 is now
   a hard, upstream gate on the whole trigger-4 critical path, not a downstream nicety. §0, §1 (AC-2), §7,
   and §11 are corrected below.
5. **[architect BLOCK 5] AUD-12 next actions — no bare stop.**
   - **AUD-12b's fix is EDGE-1** (the fee-drift probe's `WireFeeCoefficientError` envelope bug,
     `fee_drift_probe.py:348-369`) — the SAME landing event RA-1/A0 already waits on (r3 dependency item
     10). No new build item; EDGE-1's landing now doubly gates A0 AND AUD-12b.
   - **AUD-12a needs its own closing ruling, added as a new item.** `docs/evidence/
     MEASURED_SLIPPAGE_2026-09-24.md` (n=8 fills, mean slippage 0) explicitly states it does NOT replace
     the `0.01` placeholder. **New item AUD-12a-RULING**: a two-peer ruling that either (i) adopts the
     measured figure (0, or a stated shrinkage toward 0.01) in place of the placeholder, or (ii) sets a
     dated accrual target (a minimum n and a calendar date) before either figure is adopted. Since the A1
     halt blocks every new LIVE fill, the only source that can grow n beyond 8 is **replay** (RA-9b's
     candidate-replay unit or the existing paper-replay driver, both of which produce real fills against
     real historical asks/bids) — **never shadow**, which evaluates a decision but never executes an
     order and therefore has no realized fill price to measure slippage against. AUD-12a-RULING states
     this sourcing explicitly.
   - **New tracking item: add the AUD-12 row to `docs/core/PROGRESS.md`** (currently missing —
     `docs/evidence/... AUD-12…md:636-640` already names the gap) so the programme-level backlog reflects
     an item now on the critical path, not just this roadmap document.
6. **[domain] RA-9's MDE, its CONFIRMED determination, and goal-state (c)'s positive-EV claim also rest
   on the AUD-12 slippage placeholder.** `hypothesis_register.py:144,177` (`SLIPPAGE_ALLOWANCE = 0.01`) is
   the SAME unmeasured placeholder RA-3's validity flip depends on — not a second, independent open item.
   Any excess-per-take computed by RA-9b's engine, any MDE RA-9 cites, and any "trades a demonstrated
   positive-EV edge" claim under goal-state (c) is a claim NET OF a placeholder that is not yet a measured
   number. §2, §6 (AC-9), and §11 now say this explicitly rather than treating RA-9's plausibility-bound
   check and AUD-12 as unrelated.
7. **[domain] Wording fix — permanent cost, not a pause (§0, §2, §7, §9, §11).** r3 repeatedly described
   `H-ARCHIVE-RECAL-2026-09`'s corpus-sharing consequence as the hypothesis being "paused" or "not
   advancing for the duration of the trigger-4 critical path" — wording that implies the clock resumes
   once trigger-4 finishes. It does not: every post-2026-09-25 station-day RA-9b/RA-9/RA-8 touch under
   SEARCH is **permanently unusable** as CONFIRM-corpus for `H-ARCHIVE-RECAL` — that station-day can never
   later be re-classified CONFIRM once spent SEARCH. The priority decision is UNCHANGED (trigger-4 first,
   evidence-based, per r3 ruling 6) — only the consequence's description changes, from "paused" to "a
   permanent, accepted forfeiture of every post-freeze station-day this roadmap's critical path reads."
8. **[architect, no ruling needed] Candidate-replay unit's systemd placement and constraints
   corrected.** r3 placed the new unit at `deploy/timers/candidate-replay-runner.timer` — wrong location.
   Per `AUD-18…md:1276`'s own D5 pattern, units live in `deploy/systemd/breezy-*.{service,timer}` and copy
   D5's constraints verbatim: `Slice=breezy-studies.slice`, `MemoryHigh=`/`MemoryMax=` set, `flock -n
   breezy-studies.lock` around the run, `After=breezy-replay-daily.service`. B18's own scope stays
   `replay-daily-run.sh` only (`AUD-09…md:854`) — this unit is outside B18 and was never claimed to be in
   it; corrected here as a path/constraints fix, not a scope change.

---

## r2→r3 changes

1. **α mechanics — reading (a) adopted (coordinator ruling 1).** `0.025` replaces `PROGRAMME_ALPHA` in
   `register_hypothesis`'s own formula (`hypothesis_ledger.py:637-638`), so `per_variant_alpha =
   0.025/MAX_HYPOTHESES/k = 0.00625` at `k=1` — keeps programme-wide FWER at 0.025 (reading (b), applying
   0.025 per-hypothesis, would let FWER run to 0.10). **RA-8b is reclassified from a ruling-only item to a
   SMALL BUILD plus ruling:** `register_hypothesis` (or its caller in `hypothesis_register.py`) gains a
   parameterized alpha input for re-arm-gating hypotheses — a new RED, `test_rearm_gating_hypothesis_uses_
   0.025_not_programme_alpha`, pins `per_variant_alpha == 0.00625` at `k_variants=1` for that call path,
   never derived from the bare `PROGRAMME_ALPHA=0.05` module constant. **MDE recomputed** at the stricter
   alpha (`recompute_mde`, `hypothesis_ledger.py:469-482`, `POWER=0.80`, `VARIANCE_BOUND=0.25`): **n=300 →
   0.0964, n=600 → 0.0682** — both numbers now carried into RA-9's own plausibility-bound check.
2. **RA-9b is not buildable as scoped in r2 — redesigned (coordinator ruling 2).** The correct B18 set is
   **census, runner, promotion_proposal** (`replay-daily-run.sh:155,164,176`); `hypothesis_triage.py` is
   OUTSIDE it (`AUD-18…md:1276`). **Decision: a separate, standalone candidate-replay unit**, not a wrapper
   amendment. **O6 (read-time `hour_lst` derivation) is adopted as PRIMARY, not schema addition** (further
   corrected in r4 ruling 2 above).
3. **RA-3 rescoped again — the actual write site (coordinator ruling 3).** The real write site is
   `_append_terminal` (`replay_daily_runner.py:1119`), not `replay_results.py:55-58`. AUD-11 is DONE
   (closed 09-26, `581255b`). **AUD-12 is verified NOT DONE** (r4 ruling 4/5 elevate this further).
4. **RA-11a split; window-widening is NOT a Day-0 item (coordinator ruling 4).** Permit-TTL and the
   supervisor's stop/launch cycle stay in RA-11a, Day 0. Window widening is family-scoped, new item RA-11b,
   sequenced after RA-11 signs.
5. **Trigger-4 estimand corrected (coordinator ruling 5).** Hour 16 is inside the live window; the class
   becomes `{00-08, 17-23}`.
6. **Corpus declaration against `H-ARCHIVE-RECAL-2026-09` (coordinator ruling 6).** Every post-freeze
   station-day RA-9/RA-9b/RA-8 touch is declared SEARCH for `H-ARCHIVE-RECAL`; trigger-4 takes priority
   (wording of the consequence corrected in r4 ruling 7 above).

*(Full r2→r3 rationale preserved in plan r3; not re-quoted here to keep r4 legible — see
`EDGE-5_rearm_roadmap_plan_r3_2026-09-27.md` §"r2→r3 changes" for complete text.)*

## r1→r2 changes

*(Unchanged from r3; see r3 for full text — LD-OBF correction, RA-8b introduced, RA-3 first rescoped,
RA-9b first introduced, faster sanctioned path adopted, RA-11a introduced, RA-13 dated, learning loop
clarified, Python blockers folded into RA-2/RA-5a, dependencies recomputed.)*

---

## 0. Roadmap overview (read this first)

Two tracks, running in parallel from today:

- **FAST TRACK (build/evidence hygiene, days, mostly non-calendar-gated):** RA-1..RA-6, RA-8b, RA-11a
  (permit-TTL + supervisor cycle only). **Earliest completion unchanged at 2026-10-04** (bounded below by
  A0's 5-consecutive-day clock, RA-1). **r4: EDGE-1's landing now gates BOTH A0 (RA-1) AND AUD-12b** — a
  single fix, two downstream unblocks.
- **CRITICAL PATH (evidence accrual, calendar-gated):** RA-8b → RA-9 (trigger-4 registration, `{00-08,
  17-23}`, ruling artefact now ALSO states the concrete price-only take rule per r4 ruling 3, and the
  trial-level hour join per r4 ruling 2) → RA-9b (standalone candidate-replay unit; constructor-level
  window/composition seams on the SHARED `ContinuousRungHoldStrategy`, not a fourth override method; per
  r4 ruling 3) → **RA-9c (NEW, r4 ruling 1: named triage input seam, small, parallel with RA-9b)** →
  RA-10 (accrual can start as soon as RA-9b/RA-9c exist; **its first LOOK is now gated on AUD-12 landing,
  r4 ruling 4** — not merely on accrual volume) → RA-11 (ruling package) → RA-11b (family-scoped window
  widening) → RA-11a (already done) → RA-12 (operator enablement), OR → RA-13 (dated KILL, opens the
  Kalshi item) if RA-10 resolves negative or the dated no-trigger horizon elapses. RA-8 keeps running as a
  parallel, non-gating monitor for triggers 1/2, restricted to pre-freeze data only.

**AUD-12, elevated (r4 ruling 4/5):** AUD-12b = EDGE-1's own fee-probe fix (no new build item). AUD-12a
needs its own ruling (AUD-12a-RULING, NEW) adopting either the measured-slippage figure or a dated accrual
target, sourced from **replay only** (never shadow, which never executes and has no realized fill to
measure) since the A1 halt blocks new live fills. Until AUD-12b and AUD-12a-RULING both land, `validity`
stays `MECHANISM_ONLY` for every row, champion or candidate, and `_triage_record` (`hypothesis_triage.py:
548-551`) skips EVERY hypothesis with reason `C_VALIDITY` before it can take a look — **RA-10's first look
is therefore blocked on AUD-12, not merely accrual volume.** This is a hard, currently undated gate on the
entire trigger-4 critical path, independent of how fast RA-9/RA-9b/RA-10 otherwise move.

**`H-ARCHIVE-RECAL-2026-09` corpus consequence, wording corrected (r4 ruling 7):** every post-2026-09-25
station-day RA-9/RA-9b/RA-8 read under SEARCH is **permanently forfeited** as `H-ARCHIVE-RECAL` CONFIRM
corpus — not "paused," since that station-day can never later be reclassified CONFIRM. The priority
decision itself (trigger-4 first) is unchanged from r3.

**Learning-loop clarification (unchanged from r2/r3):** "learns from settled outcomes" means the existing
nightly `hypothesis_triage.py` (01:20Z) pipeline reaching real dispositions, and at the programme level,
retiring or replacing hypotheses across generations — never in-place recalibration (ruled INVALID,
`DECISION_FUNNEL_2026-09-20.md`).

**Honest time-to-demonstrated-edge, recomputed for r4:** RA-1 (A0) still cannot close before
**2026-09-30**. RA-2/RA-3(code)/RA-8b plausibly land by **~2026-10-02..03**. RA-9's registration ruling
(now carrying the concrete take-rule formula and the trial-level O6 join) plausibly issues
**~2026-10-04..06**, same order as r3 since it is a ruling, not a build. RA-9b (standalone unit +
constructor-level seams on the shared `ContinuousRungHoldStrategy`, RA-9c triage seam in parallel) is
**M→L**, same order of magnitude as r3 — the four-method-pin complexity r3 carried is retired, offset by
the added review scrutiny of touching shared, LIVE-inherited code (named as its own risk, §9, rather than
padding the estimate). **RA-10's accrual can start once RA-9b/RA-9c exist (~Day 8 onward, unchanged from
r3), but its FIRST LOOK cannot fire until AUD-12b (EDGE-1) and AUD-12a-RULING both land — no date is
available for either.** The domain-supplied **~3-5 month** accrual-to-disposition estimate therefore now
reads as: *3-5 months of RA-9b build + RA-10 accrual runtime, run in parallel with AUD-12's own landing;
if AUD-12 lands within that window the headline holds, if it does not, the first countable look — and
therefore any CONFIRMED/REJECTED disposition — is blocked open-endedly on AUD-12 alone, regardless of how
fast the rest of this roadmap moves.* This is a materially more honest, and more pessimistic, statement
than r3's framing. An evidenced KILL (RA-13) remains the domain reviewer's assessed more-likely outcome.

---

## 1. Goal & acceptance criteria

**Goal state** (operator-set, non-negotiable): a registered family that is (a) live-armed, (b) hunts at
all hours, (c) trades a demonstrated positive-EV edge, (d) learns from settled outcomes (§0 definition).

1. **AC-1.** Unchanged: A0 evidence pack exists, dated, `DOCUMENTED_TAKER_FEE_COEFFICIENT` unchanged
   (RA-1), blocked on EDGE-1.
2. **AC-2 (amended again, r4).** Neither structural gate blocks a non-trivial triage disposition
   unconditionally (RA-2, RA-3-code). **r4: this AC's real-world effect is now understood to gate the
   ENTIRE trigger-4 critical path, not only the champion's own row upgrade** — `_triage_record` skips
   every hypothesis (champion or candidate) with a `C_VALIDITY` reason until AUD-12b+AUD-12a-RULING land
   (§0, §2, §11).
3. **AC-3, AC-4, AC-5, AC-6.** Unchanged from r3.
4. **AC-7 (amended, r4).** A two-peer, pre-registered ruling for the pooled off-window hypothesis,
   `{00-08, 17-23}`, declaring: the non-`P_HOLD` estimand; its SEARCH-vs-CONFIRM corpus declaration
   against `H-ARCHIVE-RECAL` (permanent forfeiture, r4 ruling 7 wording); the trial-level `hour_lst` join
   (r4 ruling 2); and **the exact, price-only TAKE RULE formula and margin value** the composition seam
   will implement (r4 ruling 3) — RA-9b may not begin implementing `compose_decision`'s replacement body
   until this ruling states the formula.
5. **AC-8 (amended, r4).** A working, non-`P_HOLD`-gated composition path exists via constructor-level
   `window_start_hour_lst`/`window_end_hour_lst`/`compose_decision` seams on the shared
   `ContinuousRungHoldStrategy` (defaulting byte-identically for the live champion), consumed by a
   standalone candidate-replay unit that never invokes or amends B18, PLUS the new named triage input seam
   (RA-9c, AC-8b below) that lets `hypothesis_triage.py` actually read the candidate unit's output.
6. **AC-8b (NEW, r4, architect ruling 1).** `hypothesis_triage.py` accepts a named, explicit list of
   completed-result sources; omitting it reproduces today's champion-only behaviour byte-identically; a
   candidate source in the list is visible to `_triage_record` (RA-9c).
7. **AC-9 (amended, r4).** IF the hypothesis reaches CONFIRMED, a new A1-class ruling package meeting
   every `RULING_A1` §7 condition, plus SINGLE_LOOK/Bonferroni, plus the 0.025 budget, plus RA-1/RA-4/
   RA-5a/EDGE-2C/EDGE-3 all closed (RA-11). **r4: CONFIRMED itself, and the positive-EV claim under
   goal-state (c), are both net of the AUD-12 slippage placeholder — stated explicitly, not implied
   (domain ruling 6).**
8. **AC-10, AC-11.** Unchanged from r3.

---

## 2. Evidence / root cause, with file:line

**AUD-18 status, structural-gate circularity:** unchanged — `_has_registered_draw_binding` hardcoded
`False` at `hypothesis_triage.py:484-493`; the real remaining gap is `_append_terminal`.

**α budget:** unchanged from r3 (§2 there) — `0.025` substitutes for `PROGRAMME_ALPHA` in
`register_hypothesis`'s formula, giving `per_variant_alpha = 0.00625` at `k=1`; MDE 0.0964 at n=300, 0.0682
at n=600.

**RA-9b — engine, corrected again (r4 rulings 2, 3, 8):**
- **O6 join (ruling 2):** `hour_lst` is derived per `FilledTrial.filled_at_ns` (`trial_scorer.py:121`),
  via `_local_hour` (`strategy.py:214`), against each candidate row's `scored_trials_*.parquet` — NEVER
  from `ReplayResult.run_ts` (`replay_daily_runner.py:1113`, the runner's own wall clock, wrong
  granularity: one `ReplayResult` per station-day, not per take). Multi-hour station-days are split at the
  trial level before aggregation to the station-day draws `hypothesis_triage.py` already consumes.
- **Strategy seam (ruling 3):** `_hunt_tick` (`continuous_strategy.py:1810-2144`) stays byte-inherited;
  the shared `ContinuousRungHoldStrategy.__init__` gains three defaulted keyword-only parameters
  (`window_start_hour_lst`, `window_end_hour_lst`, `compose_decision`), read at `:1983`, `:2245`, `:2111`
  respectively, defaulting to today's module constants (`strategy.py:154-155`, imported at
  `continuous_strategy.py:91-92`) and today's `evaluate_both_sides` free function. No fourth override
  method; `PooledOffWindowBacktestStrategy`'s AST pin reverts to the champion's own three-method shape.
  The concrete take rule (a price-only formula net of fee + AUD-12 slippage + margin, never
  `running_max`/`P_HOLD_*`) is fixed by RA-9's ruling artefact, not invented in the file plan.
- **Systemd placement (ruling 8):** units live in `deploy/systemd/breezy-*.{service,timer}`, copying
  AUD-18 D5's constraints (`AUD-18…md:1276`): `Slice=breezy-studies.slice`, `MemoryHigh=`/`MemoryMax=`,
  `flock -n breezy-studies.lock`, `After=breezy-replay-daily.service`.

**RA-9c — triage input seam (NEW, r4 ruling 1):** `hypothesis_triage.py:157` hardcodes
`replay/replay_results.jsonl`; `run()` (`:619-755`) reads only that path via `_load_aud09`. The seam
becomes an explicit, ordered `(source_label, path)` list argument, defaulting to the single champion path
when omitted.

**RA-3 — the real write site, AUD-12 elevated (r4 ruling 4):** `_append_terminal`
(`replay_daily_runner.py:1088-1143`) constructs every `ReplayResult` with `validity=REPLAY_VALIDITY`
(`:1119`) unless an explicit `AUD11_AND_AUD12_LANDED`-shaped condition is `True` (currently `False`).
**Newly confirmed (r4):** `_triage_record`'s own C_VALIDITY branch (`hypothesis_triage.py:548-551`) means
this is not merely a cosmetic upgrade of the champion's own six rows — it is the ONE gate standing between
EVERY hypothesis (champion or candidate) and its first look. `promotion_criteria.py:427`'s own
`MECHANISM_ONLY` rejection is a second, independent enforcement of the same rule at a different consumer.
AUD-12b = EDGE-1's fee-probe fix (`fee_drift_probe.py:348-369`, `WireFeeCoefficientError`). AUD-12a needs
its own ruling (AUD-12a-RULING, NEW): `MEASURED_SLIPPAGE_2026-09-24.md` (n=8, mean 0) does not itself
replace the `0.01` placeholder (`hypothesis_register.py:144,177`) — the ruling decides whether it does, or
sets a dated accrual target, sourced from replay (never shadow — shadow has no realized fill to measure).

**Corpus vs `H-ARCHIVE-RECAL-2026-09` (wording corrected, r4 ruling 7):** the SEARCH/CONFIRM firewall
binds per station-day; every post-freeze station-day RA-9b/RA-9/RA-8 touch under SEARCH is **permanently**
unusable as `H-ARCHIVE-RECAL` CONFIRM corpus, not merely deferred. Priority decision (trigger-4 first)
unchanged from r3 ruling 6.

**A0 fee evidence, fresh manifest, learning loop, AUD-07/AUD-06b:** unchanged from r1/r2/r3 §2.

---

## 3. Options & trade-offs

O1-O8 carried forward from r3 unchanged.

**O9 (NEW, r4) — Constructor-level seam vs. a fourth override method for the strategy-class gap.**
Adopted: three defaulted constructor parameters on the shared `ContinuousRungHoldStrategy`
(`window_start_hour_lst`, `window_end_hour_lst`, `compose_decision`), all byte-identical under defaults.
Trade-off: touches the LIVE champion's own shared base class, not only a backtest-only subclass — a
strictly larger blast radius than r3's isolated new module, requiring a regression test proving the live
champion's default construction is unaffected. Rejected: r3's fourth-override-method plan on
`PooledOffWindowBacktestStrategy` alone — smaller blast radius on the shared base, but it would have
reimplemented `_hunt_tick`'s ~330 lines of gate logic (family halt, day-budget, latch, dedupe, refusal
counters) a second time, guaranteeing behavioural drift between the champion's and the candidate's shared
gates the first time either changes. Given `CLAUDE.md`'s engineering priority (reuse native/existing
capability, smallest correct extension) and the byte-inherited discipline `continuous_backtest_only.py:
47-51` already protects, three additive, defaulted parameters is the smaller true risk despite touching a
more sensitive file.

---

## 4. Architecture & data flow — the learning loop

Diagram and recalibration-cadence discussion carried forward from r1/r2/r3 §4 unchanged. r4 amendment: the
pooled off-window hypothesis's draw-set construction is fed by RA-9b's standalone unit through the shared
strategy's three new constructor seams (not a fourth override method), and reaches `hypothesis_triage.py`
through RA-9c's new named input seam rather than the hardcoded champion-only path; every draw is
simultaneously logged as a permanent SEARCH-cost entry against `H-ARCHIVE-RECAL-2026-09`'s corpus ledger
(§2 ruling 7 wording).

---

## 5. File-by-file plan

### RA-2, RA-5a, RA-8b — unchanged from r3

### RA-3 (`_append_terminal` validity branch) — unchanged from r3, AUD-12 sequencing now tracked
separately as its own critical-path item (see below), not folded into RA-3's own "Size S"

### RA-9b (revised again, r4 rulings 2/3/8)

**Files:**
- `deploy/families/<pooled-off-window-hypothesis>.json` (NEW) — candidate-family manifest, class
  `{00-08, 17-23}`, fee θ from A0, and the concrete take-rule formula/margin RA-9's ruling states.
- `scripts/analysis/candidate_replay_runner.py` (NEW) — standalone script, own
  `candidate_replay_results.jsonl` namespace, never the champion's.
- `src/breezy/strategy/current_rung_hold/continuous_strategy.py` — **shared, LIVE base class edit**:
  `ContinuousRungHoldStrategy.__init__` gains `window_start_hour_lst`, `window_end_hour_lst`,
  `compose_decision`, all defaulted; `_hunt_tick:1983,2245,2111` read the instance attributes/callable
  instead of the bare module constants/free-function call.
- `src/breezy/strategy/current_rung_hold/pooled_off_window_backtest_only.py` (NEW) —
  `PooledOffWindowBacktestStrategy`, three-method AST pin matching
  `ContinuousRungHoldBacktestStrategy`'s own shape (`__init__`, `on_start`, `_submission_armed`),
  constructing its parent with the non-default window/`compose_decision` arguments. The champion's own
  three-method pin (`continuous_backtest_only.py:47-51`) is untouched.
- `current_rung_hold_paper_replay.py:168-169`, `replay_sufficiency.py:206-221` — `[12,17)` LST bounds
  become a parameter threaded from the candidate manifest's declared window; the champion's own `[12,17)`
  default preserved byte-identically for every existing caller.
- `hour_lst` derivation: per-`FilledTrial`, at read time, via `_local_hour` (r4 ruling 2) — no
  `ReplayResult` schema change.
- `deploy/systemd/candidate-replay-runner.service` + `.timer` (NEW, corrected location, r4 ruling 8) —
  `Slice=breezy-studies.slice`, `MemoryHigh=`/`MemoryMax=` set, `flock -n breezy-studies.lock`,
  `After=breezy-replay-daily.service`; own schedule, independent of the champion's nightly cadence.
- **Tests (RED):**
  `test_candidate_replay_runner_never_writes_to_the_champion_replay_results_path`,
  `test_hunt_tick_defaults_to_the_module_window_constants_and_evaluate_both_sides_byte_identically`
  (regression, live champion unaffected),
  `test_hunt_tick_honors_an_injected_window_and_composition_function_for_a_candidate_hypothesis`,
  a RED named for RA-9's stated take-rule formula once that ruling issues (placeholder name retired),
  `test_hour_lst_is_derived_per_filled_trial_at_read_time_and_never_persisted_on_the_row`.
- Every candidate-family station-day this unit reads from post-2026-09-25 tape is logged, at write time,
  as a permanent SEARCH-cost entry against `H-ARCHIVE-RECAL-2026-09`'s tracking artefact.

Effort: **M→L** (unchanged order of magnitude from r3; the retired four-method pin offsets the added
review scrutiny of touching the shared, live-inherited `continuous_strategy.py` — named as risk R13b,
§9, rather than inflating the estimate).

### RA-9c (NEW, r4 ruling 1) — triage input seam

**Files:**
- `scripts/analysis/hypothesis_triage.py` — `run()`'s hardcoded `replay/replay_results.jsonl` read
  becomes an explicit, ordered `(source_label, path)` list argument (default: the single champion path,
  unchanged behaviour when omitted); `_load_aud09`/`_triage_record`'s `completed` input is the union of
  all listed sources.
- **Tests (RED):** `test_a_candidate_replay_row_reaches_triage_via_the_named_input_seam`; **regression**:
  `test_triage_with_no_seam_argument_reads_only_replay_results_jsonl_byte_identically`.

Effort: **S**. No dependency on RA-9b's build completing first; can proceed in parallel.

### AUD-12b / AUD-12a-RULING (elevated to a named, tracked critical-path item, r4 ruling 4/5)

- AUD-12b: no new file plan — it IS EDGE-1's fee-probe fix, tracked there.
- AUD-12a-RULING: evidence-only, no code — a two-peer ruling artefact under `docs/evidence/`, sourced
  from replay-accrued slippage (never shadow), deciding the placeholder's disposition.
- **New tracking action:** add the AUD-12 row to `docs/core/PROGRESS.md` (gap named in
  `AUD-12…md:636-640`).

---

## 6. `RULING_A1` §7 item 4 — unchanged from r2/r3

---

## 7. Execution order & parallelism (recomputed, r4)

```
Day 0 (today, 2026-09-27):
  start RA-2 build || RA-3 build || RA-5a verification-read || RA-6 observation
  || RA-8b build+ruling || RA-8 cadence setup (pre-freeze only, non-gating)
  || RA-11a build start (permit TTL / supervisor cycle only)
  RA-1 (A0) already running; blocked on EDGE-1 -- EDGE-1's landing ALSO unblocks AUD-12b (r4 ruling 5)
  RA-4 (AUD-07) segment already scheduled tonight

Day ~1-3:
  RA-3's code branch closes (S) -- validity stays MECHANISM_ONLY (both AUD-11 done, AUD-12 pending)
  RA-8b closes (small build + ruling)

Day ~3-5:
  RA-2, RA-5a converge; full gate green; merged
  RA-4's AC7 ruling issues

Day ~3 (2026-09-30):
  RA-1 (A0) closes -- contingent on EDGE-1

Day ~4-6 (once RA-2+RA-3(code)+RA-8b all closed):
  RA-9 -- trigger-4 registration, {00-08,17-23}, k_variants=1; ruling artefact NOW ALSO states the
  price-only take-rule formula/margin and the trial-level O6 join (r4 rulings 2, 3). Does not wait on
  RA-8's cluster count.

By ~2026-10-04:
  RA-1..RA-6, RA-8b, RA-11a done. AC-2's CODE closes. AC-8b (RA-9c) can close in parallel any time after
  Day 0 -- it has no dependency on RA-9/RA-9b.

Day ~8 onward:
  RA-9b (standalone unit + 3 constructor seams on the shared ContinuousRungHoldStrategy) -- M-L, dominant
  near-term cost, elevated review scrutiny for touching live-inherited code (R13b, §9).
  RA-10 starts once RA-9b/RA-9c exist: ACCRUAL (writing candidate rows) can begin immediately. Every
  post-freeze station-day it reads is a PERMANENT SEARCH cost against H-ARCHIVE-RECAL (r4 ruling 7).

  *** NEW GATE (r4 ruling 4): RA-10's FIRST LOOK cannot fire until BOTH AUD-12b (EDGE-1's fee-probe fix)
  AND AUD-12a-RULING (slippage figure or dated accrual target, replay-sourced) have landed -- undated,
  independent of RA-9/RA-9b/RA-10's own pace. Accrual can run indefinitely without ever producing a
  countable look while this gate is open. ***

Adopted estimate (domain, revised for r4): ~3-5 months of RA-9b build + RA-10 accrual RUNTIME, run in
PARALLEL with AUD-12's own landing. IF AUD-12 lands within that window, the 3-5-month headline holds for a
first look. IF IT DOES NOT, the first countable look -- and any CONFIRMED/REJECTED disposition -- is
blocked open-endedly on AUD-12 alone. No date exists for AUD-12b or AUD-12a-RULING today.

  -> IF CONFIRMED (net of the AUD-12 slippage placeholder resolution, domain ruling 6): RA-11 (ruling
       package; requires RA-1, RA-4, RA-5a, EDGE-2C, EDGE-3 ALL closed)
       -> RA-11b (family-scoped window widening, priced only once RA-9's outcome is known)
       -> RA-11a already done -> RA-12 (operator act)
  -> IF NOT, or if the dated no-trigger horizon elapses, or AUD-12 remains unresolved past the domain's
       own no-trigger horizon (a distinct, separately-named stall condition, not yet its own ruling):
       RA-13 (evidenced-KILL ruling, opens the Kalshi item on wip/kalshi-s4-registry)

Ongoing, parallel, non-gating, PRE-FREEZE DATA ONLY:
  RA-8's bi-weekly cadence.
```

No step touches Nautilus, weakens a safety/settlement/contract test, or assigns an operator-reserved
value.

---

## 8. Deploy & verification

r3 §8's bullets carried forward, amended:
- **RA-9c:** the named-source-seam RED is green; the no-argument regression is green; a scratch run with
  a synthetic `candidate_replay_results.jsonl` entry shows `_triage_record` sees the row.
- **RA-9b:** the champion's default-construction regression (`window_*`/`compose_decision` unset) is
  green under `run_tests_no_egress.sh`, proving `ContinuousRungHoldStrategy`'s live behaviour is
  unaffected; a scratch run with the candidate manifest's non-default seams produces a take without
  reading `P_HOLD`; the systemd unit exists at `deploy/systemd/candidate-replay-runner.{service,timer}`
  with AUD-18 D5's constraints present.
- **AUD-12:** tracked in `docs/core/PROGRESS.md`; AUD-12a-RULING artefact exists, dated, under
  `docs/evidence/`, stating the sourcing (replay, not shadow) and the adopted figure or accrual target.
- **RA-3, RA-8b, RA-9, RA-11a, RA-11b:** unchanged from r3.

---

## 9. Risk register

r3's R1, R2, R4-R7, R9-R13 carried forward unchanged except as amended below.

| # | Risk | Likelihood | Mitigation |
|---|---|---|---|
| R3 (unchanged from r3) | RA-3's branch silently upgrades the live champion's validity without AUD-12 having landed | LOW/HIGH | Gated on explicit `AUD11_AND_AUD12_LANDED`, defaulting `False` |
| R11 (r4, sharpened) | AUD-12 has no committed date; it now blocks RA-10's FIRST LOOK, not only AC-2's cosmetic effect -- the entire trigger-4 critical path can accrue data indefinitely without ever reaching a disposition | HIGH (raised from MEDIUM-HIGH) | Tracked as its own dated-target-or-adopt ruling (AUD-12a-RULING) plus a PROGRESS.md row; the coordinator's merge step should treat AUD-12 as gating, not incidental |
| R13b (NEW, r4) | The three new constructor seams on `ContinuousRungHoldStrategy` (a LIVE, shared base class) are found to have a subtler default-behaviour interaction than the regression test catches -- e.g. an existing caller constructs the class positionally and silently receives a wrong keyword | MEDIUM | Both new REDs (byte-identical regression + injected-seam test) required green before merge; codegraph blast-radius check on every `ContinuousRungHoldStrategy(...)` call site before this file plan lands |
| R14 (NEW, r4) | RA-9's ruling artefact states a take-rule formula/margin that, once implemented, cannot be shown to clear fee+slippage+margin without itself depending on the unresolved AUD-12 slippage figure -- a circular dependency between AC-7's ruling and AUD-12a-RULING | MEDIUM | Name the circularity explicitly in RA-9's ruling artefact; the formula can be STATED with `slippage_allowance` as a named, swappable input before AUD-12a-RULING fixes its value -- the ruling and the value resolution are sequenced, not merged |
| R8 (unchanged, RETIRED) | r2's schema hazard; no longer applies | -- | -- |
| R12 (unchanged from r3) | Under-reporting SEARCH-cost logging | MEDIUM | RA-9b's file plan makes SEARCH-cost logging a build requirement |

---

## 10. LESSONS / invariant compliance

Unchanged from r1/r2/r3. r4 adds: the constructor-level seam on `ContinuousRungHoldStrategy` (§5, §9 R13b)
is additive and defaulted, never a behaviour change for the live champion absent an explicit override --
consistent with "preserve existing architecture, minimal targeted changes" (CLAUDE.md). No test is
weakened; two are added (regression + injected-seam).

---

## 11. Dependencies on other EDGE items

- **EDGE-1** — A0 fee-drift evidence pack. RA-1 IS EDGE-1's deliverable. **r4: EDGE-1's landing also
  resolves AUD-12b** (same root cause, `WireFeeCoefficientError`) — one fix, two unblocks.
- **EDGE-2C, EDGE-3, EDGE-6d** — unchanged from r3.
- **AUD-12 (elevated, r4, not an EDGE item, tracked here as a HARD, UPSTREAM precondition on RA-10's first
  look, not only AC-2)** — AUD-12b = EDGE-1's fix; AUD-12a needs AUD-12a-RULING (NEW), sourced from replay
  slippage accrual (never shadow). No date available for either. A new PROGRESS.md row is required (r4
  ruling 5).
- **H-ARCHIVE-RECAL-2026-09** — corpus-sharing dependency; every post-freeze station-day RA-9/RA-9b/RA-8
  touch is **permanently** forfeited as its CONFIRM corpus (wording corrected, r4 ruling 7) — an accepted,
  evidenced trade-off, priority decision unchanged.
- **EDGE-2, EDGE-4, EDGE-6 (general)** — unchanged from r3.

---

## 12. Confidence self-assessment, with unknowns

**Confidence: ~75%** on sequencing and fast-track items, unchanged from r3. **~25%** (down from r3's
~30%) on any date for the critical path from RA-9b onward — lowered because AUD-12's gate on RA-10's first
look is now understood to be structural, not merely a side effect, and it has no date.

**Unknowns, named plainly:**
- Whether `promotion_criteria.py:427` needs its own edit beyond today's `MECHANISM_ONLY` rejection —
  unresolved until RA-3's verification task runs (unchanged from r3).
- When AUD-12b (EDGE-1) and AUD-12a-RULING will land — genuinely unknown, now on the direct critical path
  rather than a side risk.
- The exact price-only take-rule formula and margin RA-9's ruling will state — not invented here by
  design (architect ruling 3); RA-9b cannot start implementing `compose_decision`'s replacement body until
  it issues.
- Whether the three new `ContinuousRungHoldStrategy` constructor seams interact with any existing
  positional-argument call site in a way the regression test does not catch — flagged as R13b, resolved
  only by the codegraph blast-radius check named there.
- The true accrual rate for the pooled `{00-08,17-23}` class, carried forward unresolved from r2/r3.
- Whether AUD-12's eventual figure changes RA-9/RA-11's own math, triggering a re-issue obligation —
  carried forward from r1/r2/r3, unresolved.
- This plan does not independently re-verify EDGE-1/2/2C/3/4/6's actual content or landing dates beyond
  what prior rounds' cited artifacts supplied — a known, named integration risk for the coordinator's
  merge, not resolved here.

## r4 final amendment (coordinator, round-4 merge). BINDING, overrides anything above

Round-4 verdicts: the architect APPROVED blocks 1, 2, 4 and 5 and the take-rule deferral, and asked for changes to the block-3 seams (text-only fixes). The domain reviewer APPROVED the round-3 items and the take-rule deferral, and asked for a slippage estimand note. Python APPROVED in r3; its items are unchanged here. With AM-1..AM-4 applied: **READY** (programme plan; each RA item is built through its own plan, review and TDD cycle).

- **AM-1 (architect, a fabricated fact that breaks byte-identity).** `continuous_strategy.py:2245` is `max(0, hour_lst - _WINDOW_START_HOUR_LST) * 60`, i.e. minutes since the window opened. It is NOT a hardcoded window length of 12. Replace ONLY the start constant, with `self._window_start_hour_lst`. The formula `window_end - window_start` in r4 lines 54-55 is WRONG and must not be implemented: it would change `minutes_since_window_open` on every live champion offer-tape row.
- **AM-2 (architect, an incomplete seam).** Route ALL SIX window and composition sites through the instance attributes and `self._compose_decision`:
  - `_hunt_tick`'s window gate (`:1983`)
  - the YES composition call
  - the NO-only entry window check (`:1779`)
  - the `_hunt_no_only` `evaluate_both_sides` call (`:1580`)
  - `minutes_since_window_open` at `:2245` (offer tape)
  - `minutes_since_window_open` at `:2488` (NO shadow tape)
  
  Otherwise a candidate built with an off-window window still has its NO path filtered to 12-17 and composed by the champion's function.
- **AM-3 (architect, the byte-identity proof).** The default-construction regression RED must pin all of the following:
  - the offer-tape `minutes_since_window_open` values
  - the `:1580` and `:1779` NO-only paths
  - the NO shadow tape field
  - `_hunt_tick`'s YES decision
  
  `tests/unit/test_current_rung_hold_offer_tape.py` and `tests/unit/test_measured_slippage_from_fills.py` are named members of the regression gate and must stay green, unmodified.
- **AM-4 (domain, the slippage estimand gap and a circularity it exposes).**
  - Replay cannot measure slippage. `paper_replay.py:157-169` `ImpossibleFillPriceError` refuses `fill_px < entry_ask`, so every replay BUY IOC fills at exactly the displayed decision-time ask. Replay slippage is therefore about 0 by construction at qty 1, and at best a book-depth lower bound, never equivalent to live fill slippage. Every "replay-only accrual" source for AUD-12a in r4 is struck.
  - That leaves a circularity. Only LIVE fills measure slippage, live fills require a re-arm, and the re-arm requires AUD-12. The coordinator's recommended resolution, which the AUD-12a two-peer ruling decides: **close AUD-12a by ruling that the 0.01 placeholder is RETAINED as a deliberately conservative slippage allowance.** It dominates both the measured live mean (0 at n=8, `MEASURED_SLIPPAGE_2026-09-24.md:11-13`) and the replay floor, so any MDE, CONFIRMED or positive-EV claim computed with it is biased toward "no edge".
  - Post-re-arm, live fills re-measure slippage. If the measured value is at or above 0.01, that triggers a re-estimate. This record belongs in the PROGRESS AUD-12 row.
  - If the ruling rejects that resolution, it must name a non-circular measurement source. "Wait" is not a source.
- **Minor (domain, non-blocking).** Unequal admitted-trial counts per station-day mean unequal within-cluster weighting. Record this as a risk in the RA-9 ruling.
- **Minor (python).** `promotion_criteria.py` is at `src/breezy/analysis/promotion_criteria.py`. Units go in `deploy/systemd/breezy-*.{service,timer}`.
