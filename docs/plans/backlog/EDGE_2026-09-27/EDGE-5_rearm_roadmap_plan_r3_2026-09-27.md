# EDGE-5 — Dependency-ordered roadmap to a new A1-class re-arm ruling (plan r3, 2026-09-27)

**Author:** trading-bot-architect, revising r2 per coordinator round-2 ruling (architect/python/domain all
REQUEST_CHANGES). **Class:** CRIT programme plan, build-time only. Authorises no order, no operator
value, no live-trading enablement.

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
   0.0964, n=600 → 0.0682** — both numbers now carried into RA-9's own plausibility-bound check. **Citation
   fix:** r2's "pooled class, `k_variants=1`" is r2's own instantiation of `RULING_HUNT-1` trigger 4, not a
   verbatim quote from that ruling — restated as such throughout.
2. **RA-9b is not buildable as scoped in r2 — redesigned (coordinator ruling 2).** The correct B18 set is
   **census, runner, promotion_proposal** (`replay-daily-run.sh:155,164,176`); `hypothesis_triage.py` is
   OUTSIDE it (`AUD-18…md:1276`) — r2 wrongly implied `hypothesis_triage.py` was a fourth in-scope script.
   The wrapper resolves only the **REGISTERED sending family** (`replay-daily-run.sh:109-138`), so r2's
   "the existing invocation gains a family-scoped flag" plan cannot work without amending B18 itself.
   **Decision: a separate, standalone candidate-replay unit**, not a wrapper amendment — touching the
   frozen wrapper that resolves the champion's own sending family risks exactly the R3 hazard (silently
   widening what the champion's nightly run touches) for a candidate hypothesis that has no business inside
   the champion's invocation at all; a dedicated script + systemd oneshot timer is the smaller, more
   reversible extension (CLAUDE.md engineering priority: smallest correct extension). It reads the same
   tape/census artifacts B18 already produces but writes to its own namespace and is never invoked by, or
   able to mutate, the wrapper's three-script contract. **Both hardcoded-window files are added to the file
   plan:** `current_rung_hold_paper_replay.py:168-169` and `replay_sufficiency.py:206-221` hardcode
   `[12,17)` LST; the candidate-replay unit needs the window bounds parameterized per hypothesis so
   sufficiency/coverage can be classified over `{00-08, 17-23}` rather than silently reusing the champion's
   window. **A NEW backtest strategy class is named:** `PooledOffWindowBacktestStrategy`
   (`src/breezy/strategy/current_rung_hold/pooled_off_window_backtest_only.py`, new module), because the
   non-`P_HOLD`-gated composition path is a fourth override, not one of `ContinuousRungHoldBacktestStrategy`'s
   existing three (`continuous_backtest_only.py:47-51,95-97`) — the exact-method-set AST pin
   (`test_the_subclass_defines_exactly_three_methods`) is **widened to a new, separate four-method pin**
   scoped to this new class only; `ContinuousRungHoldBacktestStrategy`'s own three-method pin is untouched.
   **O6 (read-time `hour_lst` derivation) is adopted as PRIMARY, not schema addition:** `read_replay_results`
   refuses on any schema-version mismatch (`replay_results.py:376-381`, constant at `:53`), so adding a
   versioned field would recreate RA-2's dual-read hazard for a second record type; deriving `hour_lst` at
   read time (reusing `_local_hour`, imported never re-derived, exactly as
   `current_rung_hold_paper_replay.py` already does for its own window check) avoids the hazard entirely and
   needs no schema bump. This is sound and is adopted — the schema-addition path (r2's default) is
   **retired**, removing r2's R8 risk outright.
3. **RA-3 rescoped again — the actual write site (coordinator ruling 3).** r2 pointed at
   `replay_results.py:55-58`. The real write site is `_append_terminal`
   (`scripts/analysis/replay_daily_runner.py:1119`), which already receives `params_match` (`:1127`) but
   hardcodes `validity=REPLAY_VALIDITY` regardless. **The branch moves to `_append_terminal`**, not the
   module constant, which stays `MECHANISM_ONLY` as the shared default the module docstring already
   describes. **The flip is additionally conditioned in code on AUD-11 AND AUD-12 having landed**
   (`replay_results.py:55-57`'s own comment). AUD-11 is DONE (closed 09-26, `581255b`). **AUD-12 is
   verified NOT DONE**: `docs/evidence/venue/polymarket_us/FEE_DRIFT_EVIDENCE_2026-09-25.md` and the common
   brief's audit facts both show the fee-drift probe (AUD-12b) still logging
   `fee_drift_probe_unknown` CRITICAL every 2h since the 09-26 16:50Z boot, and every AUD-12-slippage
   reference through 09-25 (`RULING_H-ARCHIVE-RECAL…md:118-123`, `RULING_H-NO-SIDE…md:106-107`) still calls
   the `0.01` slippage figure an **unmeasured placeholder**, pending re-issue once AUD-12 publishes a real
   number. **This is a new, honest finding beyond the coordinator's ruling text:** the code branch can and
   should be built now (gated on an explicit `AUD11_AND_AUD12_LANDED` condition, defaulting to the
   `MECHANISM_ONLY` path), but its real effect — writing `PARAMS_VERIFIED` — stays **inert** until AUD-12
   lands. If `promotion_criteria.py:427`'s consumer requires non-`MECHANISM_ONLY` validity to let a
   disposition through (verification task, unchanged from r2's own list), **AC-2 does not fully close on
   RA-3 alone** — AUD-12 is a new, currently-undated hard precondition on AC-2's real-world effect, tracked
   separately in §11 and the risk register. **Risk-mitigation wording corrected:** the flip is not claimed
   to be protected by `params_match` in isolation — the wrapper always passes the champion's own manifest
   and all 6 on-disk rows already have `params_match=True` — so upgrading the champion's own replay rows to
   `PARAMS_VERIFIED` is an **intended consequence, only once AUD-11 and AUD-12 have both landed**, stated
   that way rather than as an accidental side effect params_match alone would prevent.
4. **RA-11a split; window-widening is NOT a Day-0 item (coordinator ruling 4).** Permit-TTL
   (`test_the_permit_ttl_is_pinned_to_ten_hours`) and the supervisor's 16:40Z/16:50Z stop-launch cycle may
   still run in parallel, Day 0, no evidence dependency — **RA-11a is narrowed to these two only.** Widening
   `_WINDOW_*` (module-level, `strategy.py:154-155`) on Day 0 **contradicts `RULING_HUNT-1:31,38`**
   ("never by widening the window") — window widening must be **family-scoped**, and can only happen once
   RA-9's pooled-hours family is `CONFIRMED` and RA-11 has ruled. **New item RA-11b** (window-widening,
   family-specific `_WINDOW_*` variant + the PREREG class-C amendment) is created, priced work that depends
   on RA-9, sequenced **after RA-11 signs, before RA-12** — moved OUT of the 2026-10-04 FAST-TRACK floor.
5. **Trigger-4 estimand corrected (coordinator ruling 5).** Hour 16 is inside the live window
   (`RULING_HUNT-1…md:22`) and is **removed** from the pooled off-window class: `{00-08, 16-23}` becomes
   **`{00-08, 17-23}`** everywhere in this roadmap. The registered estimand is restated as materially
   different from `P_HOLD`, not merely a different hour set: mean excess-per-take under the pooled-hours
   composition path (RA-9b's engine), over station-days in `{00-08, 17-23}` LST, `k_variants=1` — this
   satisfies `RULING_A1` §7 condition (1) (an edge estimate on real, non-synthetic ladders, station-day
   clustered, not `P_HOLD`-dependent) by construction, since the engine never consults `P_HOLD` at all.
6. **Corpus declaration against `H-ARCHIVE-RECAL-2026-09` (coordinator ruling 6).** r2 §0 wrongly listed
   `H-ARCHIVE-RECAL-2026-09` among "already-retired examples" — **corrected: it is NOT retired**, it is
   live and accruing (`EDGE-4_DISPOSITION_2026-09-27.md` fix, r2:85). Post-2026-09-25 tape is its own
   CONFIRM corpus. **Any statistic trigger-4's registration, RA-8's bi-weekly monitoring re-runs, or
   RA-9b's replay computes over post-freeze station-days is declared SEARCH for `H-ARCHIVE-RECAL-2026-09`**,
   cost recorded in both this plan (§2, §9) and `AUD-18a`'s own tracking. Station-days in scope: every
   post-2026-09-25 station-day up to RA-9's own ruling date (undated until RA-9 drafts; bounded below by
   whatever RA-9b's engine actually replays). **RA-8 is restricted to pre-freeze data only** for its
   trigger-1/2 cluster counting, so it never additionally spends `H-ARCHIVE-RECAL`'s corpus. **Priority,
   decided from evidence, not merely the coordinator's lean:** trigger-4 takes priority. `H-ARCHIVE-RECAL`
   is already `PARKED` under `EDGE-4`'s disposition with a ~20-station-day corpus against a 600-day bar —
   months away regardless — while trigger-4 is the only path to goal-state (b), all-hours hunting. The
   honest consequence, stated plainly: **`H-ARCHIVE-RECAL`'s post-freeze CONFIRM corpus does not advance
   while RA-9b/RA-9/RA-10 run**, because every day RA-9b's engine touches is SEARCH-only for
   `H-ARCHIVE-RECAL`, and RA-8's pre-freeze restriction means it contributes nothing to that corpus either.
   `H-ARCHIVE-RECAL` stays effectively paused for the duration of the trigger-4 critical path — consistent
   with, not a change to, its existing `PARKED` disposition.

---

## r1→r2 changes

1. **LD-OBF corrected (reverses r1 §6).** r1's "correction" was wrong. AUD-18 withdraws `LD_OBF` only as
   a *ledger* look policy (AUD-18…md:156-158, 807); live families keep sequential monitoring through
   their pinned boundary artefact (`deploy/families/pm_us_crh_v4.json:6` → `gs_boundary_pm_us_crh_v2.json`).
   `RULING_A1` §7 item 4's fresh LD-OBF α is kept EXACTLY as written. `SINGLE_LOOK` + Bonferroni
   `per_variant_alpha` is added as a SEPARATE, additional pre-arm condition for the ledger hypothesis
   only. Any wording change to `RULING_A1` itself goes through RA-11's two-peer ruling, never a
   documentation-only edit.
2. **New α-budget item, RA-8b, before RA-9.** `hypothesis_ledger.py:95`'s `PROGRAMME_ALPHA=0.05` traces
   to `PREREG_WP7`; PREREG v2 pins `0.025` (`gs_boundary_artefact.py:82`, confirmed
   `ALPHA_ONE_SIDED: Final[float] = 0.025`). Any hypothesis whose CONFIRMED status gates a `pm_us_crh`
   re-arm is tested at the stricter family-wise 0.025.
3. **RA-3 rescoped.** Premise was false: the nightly wrapper already passes `--family-manifest`
   (`replay-daily-run.sh:164-169`) and all 6 on-disk rows already have `params_match=True`. RA-3 is now a
   ruling plus a flip of `replay_results.py:55-58` conditioned on `params_match`, covering the consumer
   at `promotion_criteria.py:427`. Size S (was M). The "champion never upgraded" RED is dropped.
4. **New engine item, RA-9b, before RA-10** (merges architect RA-10 + domain Q1 — same gap). A
   candidate-family manifest plus a non-`P_HOLD`-gated decision/composition path producing simulated
   takes for the new hypothesis under replay, inside AUD-09's closed three-script invocation set (B18).
   Confirmed via codegraph: `ReplayResult.to_dict` (`replay_results.py:121-155`) carries no `hour`/
   `hour_lst` field. Adding one hits the same strict `from_dict` backward-compat hazard as RA-2 — priced
   into RA-9b's effort (M→L), not assumed free.
5. **Faster sanctioned path adopted (domain Q5).** `RULING_HUNT-1` trigger 4 is adopted: register the
   pooled off-window class `{00-08, 16-23}` directly through AUD-18 once RA-2 and RA-3 land, `k_variants=1`
   (AUD-18 §9 power lever) — this DECOUPLES RA-9 from waiting on RA-8's cluster trigger. RA-8 continues
   as parallel MONITORING (triggers 1/2 backstop), not a gate. "Hours 10-11" is struck as a viable class
   everywhere: `daf81a1` tested it — hour 11 negative, hour 10 flat. The registered hypothesis must
   declare its corpus under the EDGE-4 firewall rule (SEARCH vs post-freeze CONFIRM).
6. **New all-hours enablement item, RA-11a, between RA-11 and RA-12.** Covers the 10h permit-TTL pin
   (`test_the_permit_ttl_is_pinned_to_ten_hours`), the supervisor's 16:40Z stop / 16:50Z launch cycle
   (`CONTINUOUS_HUNTING_GAP_2026-09-20.md:84-93`), and widening `_WINDOW_*` plus the PREREG class-C
   amendment (`RULING_HUNT-1…md:24-26`). Without this item, goal-state (b) — hunts at all hours — is
   structurally unreachable even after RA-11 signs.
7. **RA-13 dated, Kalshi item concretised.** The no-trigger KILL horizon is now dated from measured
   per-hour cluster accrual rates (domain: ~0.05-0.29 clusters/day in untested hours; up to ~2/day in
   populated hours). RA-13 opens a concrete Kalshi roadmap item (Kalshi is outside AUD-18 scope,
   AUD-18…md:194) parked on `wip/kalshi-s4-registry` — "names Kalshi" alone is insufficient.
8. **§0 clarifies the learning loop (domain Q3).** "Learns from settled outcomes" means nightly triage
   plus retirement or replacement of hypotheses across generations, under `SINGLE_LOOK` — never in-place
   recalibration, which stays ruled INVALID.
9. **Python blockers folded into RA-2/RA-5a:**
   - RA-2: `to_dict` preserves each record's OWN `schema_version` (not a global bump); new RED
     `test_v1_record_to_dict_never_emits_variant_stratum_filters`; new mixed v1/v2 whole-file rewrite RED
     (the ledger is NOT append-only — `write_hypothesis_ledger` rewrites the whole file,
     `hypothesis_ledger.py:808-820`); `hypothesis_register.py` added to the file plan; existing passing
     guards relabelled "regression," not "RED."
   - RA-5a: exempt `no_taken_latch` `ExcludedFill` rows (blank `trial_id`/`station`/`climate_day`,
     `residual_fills.py:205-216`) from the family-keying assertion, mirroring `residual_fills.py:242-246`.
10. **Dependencies and dates recomputed.** Adds EDGE-1 (fee probe is blind — A0 readiness precondition),
    EDGE-2C (NO-side resolver crash — hard re-arm precondition), EDGE-3 (per-family halt, so a fresh
    family isn't blocked by v4's halt) and EDGE-6d (recorder next-day capture lag, speeds trigger-1
    accrual), each by ID. RA-1/A0 closes no earlier than 2026-09-30 (needs 5 consecutive complete days).
    Critical path and time-to-demonstrated-edge recomputed in §0/§7: ~3-5 months on the trigger-4 fast
    path, open-ended otherwise, with an evidenced KILL the more likely outcome.

---

## 0. Roadmap overview (read this first)

Two tracks, running in parallel from today:

- **FAST TRACK (build/evidence hygiene, days, mostly non-calendar-gated):** RA-1..RA-6, RA-8b (now ruling
  + small build), RA-11a (**narrowed in r3** to permit-TTL + supervisor cycle only — window-widening moved
  to RA-11b, below) — closes A0, fixes the two structural gates, finishes the exit seam, settles the
  α-budget question, and builds the non-window all-hours enablement infrastructure. **Earliest completion
  unchanged at 2026-10-04** (bounded below by A0's own 5-consecutive-day clock, RA-1) — RA-8b's added
  build scope roughly offsets RA-11a's reduced scope. **New in r3: AC-2's real-world effect (validity
  actually flipping off `MECHANISM_ONLY`) additionally depends on AUD-12 landing — verified NOT DONE as of
  today (§2) — which is undated and outside this roadmap's control.** This track is a floor on READINESS,
  not on re-arm, and not on AC-2's full closure.
- **CRITICAL PATH (evidence accrual, calendar-gated):** RA-8b → RA-9 (trigger-4 direct registration of the
  pooled `{00-08, 17-23}` class — hour 16 removed, r3 ruling 5 — corpus declared against `H-ARCHIVE-RECAL`,
  r3 ruling 6) → RA-9b (standalone candidate-replay unit + new backtest strategy class, outside B18, r3
  ruling 2) → RA-10 (accrual + first look) → RA-11 (ruling package) → **RA-11b (NEW: family-scoped window
  widening, sequenced after RA-11 signs)** → RA-11a (already done, permit TTL/supervisor cycle only) →
  RA-12 (operator enablement), OR → RA-13 (dated KILL, opens the Kalshi item) if RA-10 resolves negative or
  the dated no-trigger horizon (§7) elapses. RA-8 keeps running as a parallel, non-gating monitor for
  triggers 1/2, **restricted to pre-freeze data only** (r3 ruling 6) so it never spends `H-ARCHIVE-RECAL`'s
  corpus.

**Learning-loop clarification (domain Q3, binding for this roadmap, unchanged from r2):** "learns from
settled outcomes" means the existing nightly `hypothesis_triage.py` (01:20Z) pipeline reaching real
dispositions — `CONFIRMED` / `PRIMARY_PASSED_PNL_VETO` / `REJECTED` / `PARKED` →
`ABANDONED_CAP_EXHAUSTED` — and, at the programme level, retiring or replacing hypotheses across
generations. **`H-ARCHIVE-RECAL-2026-09` is corrected in r3: it is NOT one of the retired examples — it is
live, accruing, and currently PARKED, effectively paused for the duration of the trigger-4 critical path
(r3 ruling 6).** `H-NO-SIDE-2026-09` remains the one genuinely retired example. This is explicitly NOT
in-place recalibration of a live estimate on new data — independently ruled INVALID
(`DECISION_FUNNEL_2026-09-20.md`, cited in `RULING_A1` §3.3).

**Honest time-to-demonstrated-edge, recomputed for r3:** RA-1 (A0) still cannot close before **2026-09-30**.
RA-2/RA-3 (the branch now lives in `_append_terminal`, still size S as code) and RA-8b (small build + ruling,
pins 0.00625) plausibly land by **~2026-10-02..03**. RA-9's trigger-4 registration can start once
RA-2+RA-3(code)+RA-8b all close, drafting the `{00-08,17-23}` estimand and its SEARCH/CONFIRM corpus split
against `H-ARCHIVE-RECAL` — **~2026-10-04..06**. RA-9b is now an explicit standalone-unit build (new script,
new systemd timer, a new backtest strategy class with its own four-method pin, window-generalized
sufficiency in two files) rather than a flag added to the existing wrapper — priced the same order of
magnitude (M→L) as r2, since removing the schema hazard (O6) offsets the added unit/wiring scope. **The
domain-supplied accrual estimate is adopted unchanged: ~3-5 months to a demonstrated CONFIRMED/REJECTED
disposition on the trigger-4 fast path; open-ended on any other path.** **New in r3, not present in r2's
estimate:** AC-2's real closure (validity actually leaving `MECHANISM_ONLY`) is additionally gated on
AUD-12 landing — verified NOT DONE, no ETA — and RA-11b (family-scoped window widening) adds a further,
currently unpriced step between RA-11 signing and RA-12, since it can only be scoped once RA-9's family is
CONFIRMED. Neither changes the 3-5-month headline figure (both are downstream of or parallel to it), but
both are additional named risks to that headline landing on schedule even if RA-9/RA-10 do. Per the domain
reviewer's cluster-count evidence, an evidenced KILL (RA-13) remains the **more likely** outcome than a
CONFIRMED re-arm.

---

## 1. Goal & acceptance criteria

**Goal state** (operator-set, non-negotiable): a registered family that is (a) live-armed, (b) hunts at
all hours, (c) trades a demonstrated positive-EV edge, (d) learns from settled outcomes (§0 definition).

1. **AC-1.** Unchanged from r2: A0 evidence pack exists, dated, under
   `docs/evidence/venue/polymarket_us/`, `DOCUMENTED_TAKER_FEE_COEFFICIENT` unchanged (RA-1), blocked on
   EDGE-1's fee-probe fix.
2. **AC-2 (amended, r3).** Neither structural gate (`_has_registered_draw_binding` hardcoded `False`;
   `REPLAY_VALIDITY`-derived `validity` hardcoded for scheduled runs) blocks a non-trivial triage
   disposition unconditionally (RA-2, RA-3). **The RA-3 code branch alone does not fully close this AC**:
   its real effect stays inert until AUD-12 lands (verified NOT DONE today) — see §2, §9, §11.
3. **AC-3.** Unchanged: `pm_us_crh_exit_v4`'s manifest is registration-ready (RA-4).
4. **AC-4.** Unchanged: a verified answer to "can a v5+ family's tally ever see a v3/v4 residual fill,"
   exempting `no_taken_latch` sentinel rows (RA-5a).
5. **AC-5.** Unchanged: a recurring, unattended, alerting cadence for HUNT-1 triggers 1/2 as a monitoring
   backstop (RA-8, now explicitly pre-freeze-data-only, r3 ruling 6).
6. **AC-6.** A dated, evidenced ruling fixes the family-wise α budget (0.025) for any re-arm-gating
   hypothesis, BEFORE RA-9 assigns `per_variant_alpha`. **RA-8b is now a small build (parameterized alpha
   input, RED pinning 0.00625) plus the ruling, not a ruling alone (r3 ruling 1).**
7. **AC-7 (amended, r3).** A two-peer, pre-registered ruling for the pooled off-window hypothesis under
   trigger 4, **class `{00-08, 17-23}` (hour 16 removed)**, declaring a materially different, non-`P_HOLD`
   estimand satisfying `RULING_A1` §7 condition (1), AND explicitly declaring its corpus SEARCH vs
   `H-ARCHIVE-RECAL`'s post-freeze CONFIRM corpus (RA-9).
8. **AC-8 (amended, r3).** A working, non-`P_HOLD`-gated composition/decision path exists via a
   **standalone candidate-replay unit** (new script + systemd oneshot timer) that never invokes or amends
   B18 (census/runner/promotion_proposal), reusing `_local_hour` to derive `hour_lst` at read time (O6,
   PRIMARY) rather than a schema addition (RA-9b).
9. **AC-9.** Unchanged: IF the hypothesis reaches CONFIRMED, a new A1-class ruling package meeting every
   `RULING_A1` §7 condition AS WRITTEN, plus SINGLE_LOOK/Bonferroni, plus the 0.025 budget, plus RA-1/RA-4/
   RA-5a/EDGE-2C/EDGE-3 all closed (RA-11).
10. **AC-10 (amended, r3).** All-hours enablement infrastructure exists in TWO parts: (a) permit TTL +
    supervisor cycle (RA-11a) verified BEFORE RA-12; (b) family-scoped window widening (**RA-11b, NEW**)
    verified AFTER RA-9's family is CONFIRMED and RA-11 has signed, also before RA-12. Without both,
    goal-state (b) is unreachable.
11. **AC-11.** Unchanged: IF no trigger ever fires, trigger 4 is REJECTED/exhausted, or the dated
    no-trigger horizon elapses: an evidenced-KILL ruling naming Kalshi (`wip/kalshi-s4-registry`) (RA-13).

---

## 2. Evidence / root cause, with file:line

**AUD-18 status, structural-gate circularity:** unchanged from r1/r2 — `_has_registered_draw_binding`
hardcoded `False` at `hypothesis_triage.py:484-493`; the real remaining gap is `_append_terminal`
(below), not the module constant r2 pointed at.

**α budget — ruling 1 applied (r3):** `hypothesis_ledger.py:95` `PROGRAMME_ALPHA: Final[float] = 0.05`.
`register_hypothesis`'s own formula (`:637-638`) divides this by `MAX_HYPOTHESES` (4) and `k_variants` to
get `per_variant_alpha`; at `k=1` that is `0.0125` today. The coordinator adopts reading (a): for any
re-arm-gating hypothesis, **0.025 substitutes for `PROGRAMME_ALPHA` in that formula**, giving
`per_variant_alpha = 0.025/4/1 = 0.00625` — half of today's value, keeping programme-wide FWER at 0.025
rather than letting it run to 0.05-0.10. `recompute_mde` (`:469-482`, `POWER=0.80`, `VARIANCE_BOUND=0.25`)
at this stricter alpha gives **MDE 0.0964 at n=300, 0.0682 at n=600** — both numbers RA-9's own
plausibility-bound check must cite. RA-8b's build: `register_hypothesis`/`hypothesis_register.py` gains a
parameterized alpha input (never a silent global override) so a re-arm-gating call passes `0.025`
explicitly; a non-re-arm-gating call (e.g. a future unrelated hypothesis) is unaffected. **Citation
correction:** "pooled class, `k_variants=1`" is this roadmap's own instantiation of `RULING_HUNT-1` trigger
4 — the ruling itself does not use that exact phrase.

**RA-9b — the missing engine, redesigned (r3, ruling 2):** `ReplayResult.to_dict`
(`replay_results.py:121-155`) still carries no `hour`/`hour_lst` field. r2 proposed adding one plus a
wrapper flag reusing `--family-manifest`'s mechanism; both premises are now known false. The correct B18
set is **census, runner, promotion_proposal** (`replay-daily-run.sh:155,164,176`) —
`hypothesis_triage.py` is a *consumer*, not a member (`AUD-18…md:1276`). The wrapper resolves only the
REGISTERED **sending family** (`replay-daily-run.sh:109-138`): there is no hook to point it at an
unregistered candidate family without amending the wrapper itself, which this roadmap declines to do (see
r2→r3 item 2 for the reversibility argument). `current_rung_hold_paper_replay.py:168-169` and
`replay_sufficiency.py:206-221` both hardcode `[12,17)` LST — silently reusing them for `{00-08,17-23}`
would misclassify sufficiency/coverage for every candidate-replay day. `read_replay_results` refuses any
`schema_version` mismatch outright (`replay_results.py:376-381`, constant `:53`) — adding a versioned field
recreates RA-2's exact dual-read hazard for a second record type. O6 (derive `hour_lst` at read time from
the existing `_local_hour` derivation, imported never re-derived) sidesteps all of this and is adopted as
PRIMARY.

**RA-3 — the real write site (r3, ruling 3):** `_append_terminal`
(`scripts/analysis/replay_daily_runner.py:1088-1143`) already receives `params_match` as a parameter
(`:1102`, threaded to the row at `:1127`) but constructs every `ReplayResult` with
`validity=REPLAY_VALIDITY` unconditionally (`:1119`) — the bare module constant, never branched. The flip
belongs at `:1119`, not at the constant's definition (`replay_results.py:55-58`, which stays the shared
`MECHANISM_ONLY` default for the module's own AUD-11/AUD-12-gated flip). Verified today: AUD-11 (look-ahead)
closed 09-26 at `581255b`. AUD-12 (costs) is **NOT closed**: `FEE_DRIFT_EVIDENCE_2026-09-25.md` and the
common brief's audit facts show the fee-drift probe (AUD-12b) still logging `fee_drift_probe_unknown`
CRITICAL every 2h since the 09-26 16:50Z boot, and every slippage citation through 09-25
(`RULING_H-ARCHIVE-RECAL…md:118-123`, `RULING_H-NO-SIDE…md:106-107`) still calls AUD-12's `0.01` an
unmeasured placeholder pending re-issue. The in-code condition on `params_match`-driven `PARAMS_VERIFIED`
must therefore itself be gated on an explicit `AUD11_AND_AUD12_LANDED`-shaped check, currently `False` —
the branch ships inert. **All 6 on-disk rows already have `params_match=True`** because the wrapper always
passes the champion's own manifest; upgrading those rows to `PARAMS_VERIFIED` once both AUD items land is
an **intended consequence** of this design, not a leak `params_match` alone would otherwise prevent.

**RA-11a/RA-11b split (r3, ruling 4):** permit-TTL (`test_the_permit_ttl_is_pinned_to_ten_hours`) and the
supervisor's 16:40Z-stop/16:50Z-launch cycle (`CONTINUOUS_HUNTING_GAP_2026-09-20.md:84-93`) have no
evidence dependency and stay in RA-11a, Day 0. Widening `_WINDOW_*` (`strategy.py:154-155`, module-level)
on Day 0 contradicts `RULING_HUNT-1:31,38` ("never by widening the window") — window widening must be
family-scoped and can only happen once RA-9's family is CONFIRMED and RA-11 has ruled. RA-11b is the new,
separate item for exactly this, priced work dependent on RA-9's outcome, sequenced after RA-11 signs.

**Trigger-4 estimand (r3, ruling 5):** `RULING_HUNT-1…md:22` places hour 16 inside the live trading
window — r2's `{00-08, 16-23}` therefore double-counted a live hour as "off-window." Corrected class:
**`{00-08, 17-23}`**. The estimand is mean excess-per-take under RA-9b's composition path (never consulting
`P_HOLD`) over station-days in that hour set — materially different from `P_HOLD`, satisfying `RULING_A1`
§7 condition (1) by construction.

**Corpus vs `H-ARCHIVE-RECAL-2026-09` (r3, ruling 6):** `EDGE-4_DISPOSITION_2026-09-27.md` states
`H-ARCHIVE-RECAL-2026-09` is live, accruing, currently PARKED (~20 station-days against a 600-day bar),
with post-2026-09-25 tape as its CONFIRM corpus and a binding rule that any statistic computed on
post-freeze station-days by another item is SEARCH for it, cost recorded in both plans. RA-9's trigger-4
registration, RA-9b's replay engine, and RA-8's monitoring all read from the identical post-freeze tape;
the SEARCH/CONFIRM firewall binds on the corpus, not the statistic, so every station-day RA-9b touches is
SEARCH-only for `H-ARCHIVE-RECAL` and contributes nothing to its 600-day CONFIRM bar. RA-8 is restricted
to pre-freeze data only, so it does not additionally spend that corpus. Priority, decided from the
evidence: trigger-4, because `H-ARCHIVE-RECAL` is already `PARKED` and months away regardless, while
trigger-4 is the only path to goal-state (b). Consequence, stated plainly: `H-ARCHIVE-RECAL`'s revival
clock does not advance for the duration of the trigger-4 critical path.

**A0 fee evidence, fresh manifest, learning loop, AUD-07/AUD-06b:** unchanged from r1/r2 §2 (see r2 for
full text) — carried forward without amendment.

---

## 3. Options & trade-offs

O1-O6 carried forward from r2 unchanged (build RA-2/RA-3 now; pursue HUNT-1 both passively and actively;
gate RA-12 not RA-11 on the exit seam; keep RA-5a separate from RA-2; trigger-4 direct registration over
waiting on RA-8's cluster trigger).

**O7 (NEW, r3) — Amend the frozen wrapper (B18) vs a standalone candidate-replay unit for RA-9b.**
Adopted: standalone unit. Trade-off: a second script + systemd timer duplicates some tape-reading
boilerplate the wrapper already has, and creates a second thing to keep in sync with future B18 changes.
Rejected: amending `replay-daily-run.sh`'s family-resolution logic (`:109-138`) to accept an unregistered
candidate family — smaller diff, but widens what the champion's own frozen, audited nightly invocation can
be pointed at, for a hypothesis that has no legitimate reason to run inside the champion's path at all.
Given `RA-3`'s own R3 risk (a manifest-scoped flip must never silently touch the champion), amending B18's
family resolution for a *different* purpose in the same release window is the less reversible, more
entangled choice — rejected.

**O8 (NEW, r3) — `hour_lst` schema addition vs read-time derivation (O6), decided.**
r2 left this genuinely open (its own R8 risk). r3 resolves it: O6 (read-time derivation via `_local_hour`)
is adopted as PRIMARY. It needs no schema version bump, no dual-read discipline for `ReplayResult` (RA-2
already owns that hazard for `HypothesisRecord`; a second instance would double the surface with no
new benefit), and reuses an existing, already-imported derivation. The schema-addition path is retired.

---

## 4. Architecture & data flow — the learning loop

Diagram and recalibration-cadence discussion carried forward from r1/r2 §4 unchanged. r3 amendments: the
`hypothesis_triage.py` box's per-hypothesis α input reads from RA-8b's parameterized 0.025 (built, not
merely ruled) for any re-arm-gating hypothesis; the pooled off-window hypothesis's draw-set construction is
fed by RA-9b's **standalone candidate-replay unit** (outside B18) rather than by an amended wrapper
invocation; and every draw RA-9b produces from post-freeze tape is simultaneously logged as a SEARCH cost
against `H-ARCHIVE-RECAL-2026-09`'s own corpus ledger (§2 ruling 6) — a new, explicit cross-hypothesis
bookkeeping edge this diagram did not previously carry.

---

## 5. File-by-file plan

### RA-2 (schema-v2 stratum/draw binding) — unchanged from r2

All of r2 §5's RA-2 content carries forward unamended.

### RA-8b (NEW build, r3 ruling 1)

- `src/breezy/analysis/hypothesis_ledger.py` — `register_hypothesis` (or a thin wrapper in
  `hypothesis_register.py`) gains a parameterized alpha input (e.g. `programme_alpha_override:
  float | None`), read at call time, never a default-argument binding — mirroring the existing
  `NO_SIDE_*`/`ARCHIVE_RECAL_*` module-global-read-at-call-time pattern this file already uses.
- New RED: `test_rearm_gating_hypothesis_uses_0.025_not_programme_alpha` — pins
  `per_variant_alpha == 0.00625` at `k_variants=1` when the override is supplied; a call WITHOUT the
  override keeps today's `PROGRAMME_ALPHA=0.05`-derived value byte-unchanged (regression guard).
- RA-8b's ruling artefact cites the recomputed MDEs (n=300 → 0.0964, n=600 → 0.0682).

### RA-3 (`_append_terminal` validity branch) — rescoped, r3 ruling 3

Replaces r2's RA-3 file-by-file section entirely:

- `scripts/analysis/replay_daily_runner.py:1088-1143` (`_append_terminal`) — branch on `params_match`
  AND an explicit `AUD11_AND_AUD12_LANDED`-shaped condition (module-level constant, `False` today) when
  choosing the row's `validity`: write `PARAMS_VERIFIED` only when BOTH `params_match is True` AND the
  landed-condition is `True`; otherwise keep `REPLAY_VALIDITY` (`MECHANISM_ONLY`) exactly as today.
- `src/breezy/analysis/replay_results.py:55-58` — unchanged; the shared constant stays the default, no
  edit needed there (r2's plan to edit this file directly is dropped).
- `scripts/analysis/promotion_criteria.py:427` — verify (not assumed) whether it already branches
  correctly on `PARAMS_VERIFIED` vs `MECHANISM_ONLY`; add a covering test if not. **This verification also
  determines whether AC-2 fully closes on AUD-11 alone or needs AUD-12 too** — report the finding plainly
  either way.
- Ruling artefact: same licensing conditions as r2 (params_match True AND AUD-09 census SUFFICIENT AND
  current AUD-12 slippage figure), explicitly noting AUD-12 is NOT YET landed and the branch ships inert
  until it does.

Size: **S** (unchanged) for the code; the real-world effect date is undated pending AUD-12.

### RA-5a — unchanged from r2

### RA-9b (redesigned, r3 ruling 2 — replaces r2's RA-9b entirely)

**Files:**
- `deploy/families/<pooled-off-window-hypothesis>.json` (NEW) — candidate-family manifest, class
  `{00-08, 17-23}`, `composition_kind` matching RA-9's ruling, fee θ from the (by then closed) A0 pack.
  Consumed ONLY by the new standalone unit below, never by `replay-daily-run.sh`.
- `scripts/analysis/candidate_replay_runner.py` (NEW) — a standalone script, structurally similar to
  `replay_daily_runner.py` but scoped to one candidate family, reading the same tape/census artifacts and
  writing to its own `candidate_replay_results.jsonl` namespace (never the champion's `replay_results.jsonl`
  — no shared queue key, no chance of a `DuplicateReplayResultError` collision with the champion's rows).
- `src/breezy/strategy/current_rung_hold/pooled_off_window_backtest_only.py` (NEW) —
  `PooledOffWindowBacktestStrategy`, a fourth-override sibling of `ContinuousRungHoldBacktestStrategy`
  (own four-method AST pin: `__init__`, `on_start`, `_submission_armed`, plus the new non-`P_HOLD`
  composition override) — the champion's own `ContinuousRungHoldBacktestStrategy` three-method pin is
  untouched.
- `current_rung_hold_paper_replay.py:168-169`, `replay_sufficiency.py:206-221` — the `[12,17)` LST bounds
  become a parameter threaded from the candidate manifest's declared hour set, not a module constant, so
  the new unit can classify `{00-08,17-23}` sufficiency/coverage correctly; the champion's own `[12,17)`
  default is preserved byte-identically for every existing caller.
- `hour_lst` derivation: O6, at read time, reusing `_local_hour` (imported, never re-derived) against each
  candidate row's own `run_ts`/station timezone — no `ReplayResult` schema change.
- `deploy/timers/candidate-replay-runner.timer` + `.service` (NEW, systemd-run --user pattern) — its own
  schedule, independent of the champion's nightly wrapper cadence.
- Tests (RED): `test_candidate_replay_runner_never_writes_to_the_champion_replay_results_path`,
  `test_pooled_off_window_composition_path_produces_a_take_without_p_hold_gating`,
  `test_hour_lst_is_derived_at_read_time_and_never_persisted_on_the_row`,
  `test_composition_path_refuses_a_family_manifest_outside_the_pooled_hour_set`.
- Every candidate-family station-day this unit reads from post-2026-09-25 tape is logged, at write time,
  as a SEARCH-cost entry against `H-ARCHIVE-RECAL-2026-09`'s tracking artefact (§2 ruling 6) — a new
  logging obligation this file plan owns.

Effort: **M→L** (unchanged order of magnitude from r2; schema-hazard removed, standalone-unit scope added).

---

## 6. `RULING_A1` §7 item 4 — unchanged from r2

Carried forward verbatim: the fresh LD-OBF α is kept exactly as written for the live boundary artefact;
SINGLE_LOOK/Bonferroni is an ADDITION for the ledger hypothesis, not a replacement; no wording change to
`RULING_A1` is made by this roadmap document.

---

## 7. Execution order & parallelism (recomputed, r3)

```
Day 0 (today, 2026-09-27):
  start RA-2 build || RA-3 build (branch now in _append_terminal, still S) || RA-5a verification-read
  || RA-6 observation || RA-8b build+ruling (parameterized alpha, RED pinning 0.00625, no dependency)
  || RA-8 cadence setup (parallel monitor, PRE-FREEZE DATA ONLY, non-gating)
  || RA-11a build start (permit TTL / supervisor cycle ONLY -- window-widening moved to RA-11b, no
     dependency on evidence)
  RA-1 (A0) already running; blocked on EDGE-1's fee-probe fix landing (dependency item 10)
  RA-4 (AUD-07) segment already scheduled tonight 02:10-08:40Z

Day ~1-3:
  RA-3's code branch closes (S) -- REAL EFFECT STAYS INERT pending AUD-12 (undated, tracked separately)
  RA-8b closes (small build + ruling)

Day ~3-5:
  RA-2, RA-5a converge; full gate green; merged
  RA-4's AC7 ruling issues

Day ~3 (2026-09-30):
  RA-1 (A0) closes -- 5 consecutive days from WP-D1's confirmed day-list, contingent on EDGE-1

Day ~4-6 (once RA-2+RA-3(code)+RA-8b all closed):
  RA-9 -- trigger-4 direct registration of the pooled {00-08,17-23} class (hour 16 removed), k_variants=1,
  corpus declared SEARCH vs H-ARCHIVE-RECAL's post-freeze CONFIRM corpus (§2 ruling 6). Does NOT wait on
  RA-8's cluster count.

By ~2026-10-04:
  RA-1..RA-6, RA-8b, RA-11a (narrowed scope) done. AC-2's CODE closes; its REAL EFFECT stays open on AUD-12.

Day ~8 onward:
  RA-9b (standalone candidate-replay unit, new backtest strategy class, O6 hour_lst -- M-L) -- dominant
    near-term cost
  RA-10 starts once RA-9b exists: registration + accrual via the standalone unit's replay. Every
    post-freeze station-day it reads also books as SEARCH cost against H-ARCHIVE-RECAL (which therefore
    does not advance during this window -- accepted per §2 ruling 6 priority call).

Adopted estimate (domain, not independently re-derived here): ~3-5 months from today to a demonstrated
CONFIRMED/REJECTED disposition on this trigger-4 fast path; open-ended if RA-9b or RA-10 stalls.
NEW, not folded into this figure: AUD-12 landing (undated) is a separate hard precondition on AC-2's real
closure; RA-11b (family-scoped window widening) is a further, currently unpriced step after RA-11 signs.

  -> IF CONFIRMED: RA-11 (ruling package; requires RA-1, RA-4, RA-5a, EDGE-2C, EDGE-3 ALL closed)
       -> RA-11b (NEW: family-scoped window widening, priced only once RA-9's outcome is known)
       -> RA-11a already done (parallel-built) -> RA-12 (operator act)
  -> IF NOT, or if the dated no-trigger horizon (per-hour cluster rates, §2) elapses with no registration
       ever reaching CONFIRMED: RA-13 (evidenced-KILL ruling, opens the Kalshi item on
       wip/kalshi-s4-registry)

Ongoing, parallel, non-gating, PRE-FREEZE DATA ONLY:
  RA-8's bi-weekly cadence keeps watching triggers 1/2 across all untested pre-2026-09-25 hours -- a
  genuine backstop if the pooled trigger-4 class is REJECTED, without ever spending H-ARCHIVE-RECAL's
  corpus.
```

No step touches Nautilus, weakens a safety/settlement/contract test, or assigns an operator-reserved
value. RA-12/RA-13's "operator" mentions name the reserved act, never a proposed value.

---

## 8. Deploy & verification

r2 §8's RA-1/RA-2/RA-4/RA-5a/RA-9/RA-13 bullets carried forward, amended where the item changed:

- **RA-3:** the `_append_terminal` branch is green under `run_tests_no_egress.sh`; a scratch run against a
  fixture with `params_match=True` AND the landed-condition forced `True` shows `validity=PARAMS_VERIFIED`;
  the SAME fixture with the landed-condition `False` (today's real state) still shows `MECHANISM_ONLY`; the
  `promotion-criteria.py:427` consumer is exercised by an existing or new test.
- **RA-8b:** the ruling artefact exists, dated, under `docs/evidence/`, stating the 0.025 budget and citing
  the recomputed MDEs (0.0964 at n=300, 0.0682 at n=600); the RED pinning 0.00625 is green.
- **RA-9:** the `RULING_<hypothesis_id>_horizon_<date>.md` artefact exists, two-peer signed, names the
  `{00-08,17-23}` class explicitly (hour 16 absent), states the non-`P_HOLD` estimand, and declares its
  SEARCH corpus separately from `H-ARCHIVE-RECAL`'s CONFIRM corpus.
- **RA-9b:** the standalone unit's scratch run produces at least one simulated take reaching
  `hypothesis_triage.py` without a `P_HOLD` refusal; it never writes to the champion's `replay_results.jsonl`
  path (test above is green); every post-freeze day it reads is logged as an `H-ARCHIVE-RECAL` SEARCH cost.
- **RA-11a:** unchanged from r2, scoped to permit TTL + supervisor cycle only.
- **RA-11b (NEW):** the family-scoped `_WINDOW_*` variant is covered by a new test scoped to the CONFIRMED
  family only; the champion's own `_WINDOW_*` constants are verified byte-unchanged.

---

## 9. Risk register

r2's R1, R2, R4, R5, R6, R7, R9, R10 carried forward unchanged. R3 and R8 are superseded/retired below.

| # | Risk | Likelihood | Mitigation |
|---|---|---|---|
| R3 (r3, revised again) | RA-3's `_append_terminal` branch is applied to the LIVE champion's own scheduled run and silently upgrades its validity tier without AUD-12 having actually landed | LOW but HIGH severity | The branch requires BOTH `params_match=True` AND an explicit `AUD11_AND_AUD12_LANDED` condition, defaulting `False`; flipping that condition is a one-line, reviewed change gated on AUD-12's own closure evidence, never on `params_match` alone |
| R8 (r3) | **RETIRED.** r2's `hour_lst` schema-hazard risk no longer applies: O6 (read-time derivation) is adopted, no schema field is added. | — | — |
| R11 (NEW, r3) | AUD-12 has no committed date; AC-2's real closure (and therefore the champion's own validity upgrade) could stay blocked indefinitely, independent of everything else in this roadmap closing on schedule | MEDIUM-HIGH | Named explicitly in §0/§7/§11 as a hard, undated precondition rather than folded silently into RA-3's "Size S" close; the coordinator's merge step should track AUD-12 as its own dated item, not assume RA-3 subsumes it |
| R12 (NEW, r3) | RA-9b's standalone unit and RA-8's monitoring both inadvertently read post-freeze station-days without logging the SEARCH cost against `H-ARCHIVE-RECAL`, silently under-reporting how much of its corpus has been inspected | MEDIUM | RA-9b's file plan makes the SEARCH-cost log a build requirement (§5), not an afterthought; RA-8 is restricted to pre-freeze data ONLY at the query layer, not merely by convention |
| R13 (NEW, r3) | RA-11b's family-scoped window-widening is discovered to be more invasive than "priced work" once RA-9's actual family/composition_kind is known (e.g. `_WINDOW_*` is read from more call sites than `strategy.py:154-155` alone), delaying RA-12 after RA-11 has already signed | MEDIUM | RA-11b is explicitly unpriced in this plan rather than given a false estimate; the coordinator's merge step should re-scope it with a codegraph blast-radius check on `_WINDOW_START_HOUR_LST`/`_WINDOW_END_HOUR_LST` once RA-9 confirms, before RA-12 is scheduled |

---

## 10. LESSONS / invariant compliance

r1/r2's bullets carried forward unchanged (Nautilus untouched; `allow_short` untouched; no test weakened,
only widened by one reviewed value each; `AUD-01a`/`AUD-01b` untouched; live-trading enablement stays
operator-only; no bare stop). r3 adds: the AUD-12 undated-precondition finding (item 11) and the
`H-ARCHIVE-RECAL` corpus-priority call (item 6) are both now explicit, evidenced statements rather than
assumptions, closing two more gaps r2 left implicit or wrong.

---

## 11. Dependencies on other EDGE items

- **EDGE-1** — A0 fee-drift evidence pack. RA-1 IS EDGE-1's deliverable, unchanged from r2.
- **EDGE-2C** — the NO-side resolver crash. Hard precondition on RA-11/RA-12, unchanged from r2.
- **EDGE-3** — per-family halt. Hard precondition on RA-12, unchanged from r2.
- **EDGE-6d** — recorder next-day capture lag. Speeds RA-8's (now pre-freeze-only) trigger-1 accrual,
  unchanged from r2.
- **AUD-12 (NEW, r3, not an EDGE item but tracked here as a hard precondition)** — cost-model
  slippage/fee-drift measurement. Verified NOT DONE today (fee-drift probe still logging
  `fee_drift_probe_unknown` CRITICAL). RA-3's real-world validity flip cannot take effect until this lands;
  no date is available from any artifact reviewed this session — the coordinator's merge step should track
  it as its own dated item rather than assume RA-3's "Size S" subsumes it.
- **H-ARCHIVE-RECAL-2026-09 (NEW, r3, hypothesis-ledger item, not an EDGE item)** — corpus-sharing
  dependency with RA-9/RA-9b/RA-8, per §2 ruling 6. Its revival clock does not advance while the trigger-4
  critical path runs; this is an accepted, evidenced trade-off, not an oversight.
- **EDGE-2, EDGE-4, EDGE-6 (general)** — sibling items, scope not independently re-verified beyond the
  coordinator's ruling text and `EDGE-4_DISPOSITION_2026-09-27.md`, applied directly to RA-9's corpus
  declaration (§2 ruling 6) as binding.

---

## 12. Confidence self-assessment, with unknowns

**Confidence: ~75%** on sequencing and the fast-track items — unchanged from r2, since RA-8b's added
build scope and RA-11a's reduced scope roughly offset. **~30%** on any date for the critical path
(RA-9b onward) — unchanged from r2's revised figure; RA-9b's redesign (standalone unit) removes one
uncertainty (the schema hazard, R8, retired) but adds another (a genuinely new script + timer's own
integration risk, not yet built).

**Unknowns, named plainly:**
- Whether `promotion_criteria.py:427` already branches correctly on `PARAMS_VERIFIED` vs `MECHANISM_ONLY`,
  or needs its own edit — unresolved until RA-3's verification task runs (§5).
- **When AUD-12 will land** — genuinely unknown; no artifact reviewed this session gives a date, only that
  the fee-drift probe (its blocking dependency) is still broken as of 09-27.
- Whether RA-11b's family-scoped window-widening is as small as "priced work depending on RA-9" implies,
  or touches more call sites than `strategy.py:154-155` — unresolved until RA-9 confirms a family and a
  codegraph blast-radius check is run.
- The true accrual rate for the pooled `{00-08,17-23}` class specifically, as distinct from the general
  per-hour cluster rates the domain reviewer supplied — carried forward from r2, unresolved.
- Whether AUD-12's slippage placeholder changes before RA-9/RA-11 draft, triggering the stated re-issue
  obligation — carried forward from r1/r2, unresolved.
- This plan does not independently verify EDGE-1/2/2C/3/4/6's actual content or landing dates beyond what
  the coordinator's ruling text and cited artifacts supplied — a known, named integration risk for the
  coordinator's merge, not resolved here.
