# EDGE-5 — Dependency-ordered roadmap to a new A1-class re-arm ruling (plan r1, 2026-09-27)

**Author:** trading-bot-architect (blind — no other EDGE-item agent's output visible). **Class:** CRIT
programme plan, build-time only. This document proposes and sequences work; it authorises no order,
no operator value, and no live-trading enablement.

## 0. Roadmap overview (read this first)

Two tracks, running in parallel from today:

- **FAST TRACK (build/evidence hygiene, days, mostly non-calendar-gated):** RA-1..RA-6 — closes A0,
  fixes the two structural gates that currently make AUD-18's nightly triage a no-op, finishes the
  exit seam, and hardens the observability the "learning loop" depends on. **Earliest completion:
  2026-10-04** (bounded below by A0's own 5-consecutive-day clock, RA-1).
- **CRITICAL PATH (evidence accrual, open-ended, calendar-gated, may never resolve): RA-7..RA-13** —
  the actual edge estimate. Every remaining §6.3 hypothesis class except "hours 10-11 / all-hours" is
  already a dead end (§2). That class is `BLOCKED-OPEN` behind `RULING_HUNT-1` and requires a
  measured trigger from **continuing capture that runs regardless of the A1 halt** (`RULING_A1
  §4`: "the node, capture, shadow valuation and the KILL clock keep running").

**Honest earliest possible re-arm date: no earlier than 2026-10-04, and that is a lower bound on
INFRASTRUCTURE readiness only — it is NOT a re-arm date.** The re-arm itself is gated on RA-8 firing,
which has no determinable date (§7). This is not a planning failure; it is what the operator's own
statistical design (AUD-18, peer-scored 100/100) is *for*: it makes "no edge exists here" and "an
edge exists and is this large" equally valid, evidenced, dated conclusions, and it names the next
evidence-producing action at every stop (§7, §9) — including the KILL branch (RA-13), which is not a
bare stop but a peer ruling with a named successor lever (Kalshi).

### Roadmap table

| ID | Title | Acceptance evidence | Depends on | Effort | Calendar-gated? |
|---|---|---|---|---|---|
| **RA-1** | A0 fee-drift evidence pack (= **EDGE-1**) | Dated doc under `docs/evidence/venue/polymarket_us/` with per-slug/per-day θ ≥5 consecutive days, wire-vs-tape-writer drift separated, maker field independent, extended RED-first pin test (`test_polymarket_us_fee_schedule_pin.py`) green without touching `fees.py:86` | WP-D1 (DONE, live) | S (mostly wall-clock) | **YES — earliest close 2026-09-30** (PROGRESS.md:50) |
| **RA-2** | AUD-18(b): schema-v2 hypothesis/variant → stratum/draw-population binding | RED→GREEN per §5 below; `_has_registered_draw_binding` returns a real predicate, not a hardcoded `False`; `read_hypothesis_ledger` accepts `{1,2}`, refuses else; the 3 existing v1 ledger lines round-trip byte-identical | none (buildable now) | M | No (build); live exercise gated on RA-9 |
| **RA-3** | `REPLAY_VALIDITY` tier flip + manifest-bound scheduled replay | New validity tier ruling + `replay_daily_runner` invoked with `--family-manifest` for the family under test; `params_match=True` achievable; `_passes_c_validity` passes on a real row without editing the MECHANISM_ONLY default for untagged runs | AUD-11 (DONE), AUD-12a/b (DONE) | M | No (build); exercised now against `pm_us_crh_v4` replay (shadow, not live) |
| **RA-4** | AUD-07 exit-seam completion | `breezy-aud07-m1c-seg-0927a` → AC7 ruling → base §7 steps 7, 7b, 8 → `pm_us_crh_exit_v4` registration-ready manifest (fee θ, composition_kind, `d0_climate_day` corrected; `exit_rule` key present) | none (running) | M (mostly spent) | Partially — tonight's window 02:10–08:40Z is fixed |
| **RA-5a** | Residual-sidecar family-keying — **verify or build** (A-9 clause 3) | Read `family_tally_v2.py`'s `store_dir` resolution against `assert_family_only`'s 4 checks (`family_barrier.py:75-96`); either (a) document why the existing directory partition already satisfies "v4 inherits no v3 residuals," or (b) add an explicit `assert_family_only`-shaped filter over `ExcludedFill` rows before any v5+ tally consumes them. RED test: a v3-window residual fixture must not appear in a v5-window tally | none (buildable now) | S–M | No |
| **RA-6** | Ops/learning-loop hardening residuals | ING-2 EXTEND-path observation, AUD-02 discovery-pull timer (`-m` fix) first real check, AUD-10b C12 judge-idempotency check, FU-17 first live exercise — each already scheduled in PROGRESS's "Order" line | none (running) | S (mostly observation) | Partially (specific timer windows) |
| **RA-7** | Learning-loop description and cadence (task item 6) | §4 below — no new build, a naming/verification exercise: nightly `breezy-hypothesis-triage.service` (01:20Z) reports "CLEAN no look-taking" honestly today, and will report real dispositions once RA-2+RA-3 land and RA-9 registers a look-taking hypothesis | RA-2, RA-3 | — (documentation of an existing pipeline) | No |
| **RA-8** | HUNT-1 trigger-monitoring cadence | A recurring (bi-weekly) unattended run of `hourly_ask_relative_edge.py` per hour in {00-08, 16-23}, comparing cluster counts to the 15-cluster floor (`RULING_HUNT-1` trigger 1); alert on ≥15 in any hour or on a live sub-degree observation source appearing (trigger 2) | none (capture already running) | S to build the cadence; **the wait is the item** | **YES — open-ended, no determinable date** |
| **RA-9** | AUD-18 §7 step-8 peer ruling for the new all-hours/off-window hypothesis (4th/reserved programme slot) | Two-peer (author + adversarial) `docs/evidence/RULING_<hypothesis_id>_horizon_<date>.md` fixing `min_station_days`, `look_policy=SINGLE_LOOK`, `per_variant_alpha`, MDE + plausibility bound, KILL horizon, pooled-P&L veto and leg-share cap, per §6.1 | RA-8 fires | M (ruling itself is days, not weeks) | No, once RA-8 fires |
| **RA-10** | Registration + accrual + first scheduled look | `hypothesis_register.py` registers the record; nightly `hypothesis_triage.py` (01:20Z) reports the disposition once `n_station_days_with_takes >= min_station_days`: `CONFIRMED`, `PRIMARY_PASSED_PNL_VETO`, `REJECTED`, or continued `PARKED_INSUFFICIENT_DATA` past horizon → `ABANDONED_CAP_EXHAUSTED` | RA-9, RA-2, RA-3 | S (build); accrual is the cost | **YES — accrual rate at that hour is unmeasured** |
| **RA-11** | New A1-class ruling package | Two-peer ruling meeting all of RULING_A1 §7's conditions **as corrected below (§6)**: CI-excludes-zero edge NOT `P_HOLD`-dependent (RA-10 CONFIRMED); RA-1's A0 pack; fresh manifest satisfying POST_FORECAST §A-9 item 2 in full including clause 3 (RA-5a); HUNT-1 met (RA-8/RA-10 IS the all-hours build); n reset to 0; fresh `per_variant_alpha` under SINGLE_LOOK Bonferroni (LD-OBF is WITHDRAWN, §6) | RA-10 = CONFIRMED, RA-1, RA-5a, RA-4 | M | No, once RA-10 resolves CONFIRMED |
| **RA-12** | Operator's one act: live-trading enablement | Operator flips enablement for the newly registered family; budget ceiling already established (RULING_A1 §7) and is never valued here | RA-11 | — (operator-only) | No |
| **RA-13** | Alternate terminus: programme-level KILL (§6.6) | If RA-8 never fires within a horizon the RA-9-equivalent ruling would set for archive-recal (600 station-days, already closed) applied by analogy, or if RA-10 resolves REJECTED/`ABANDONED_CAP_EXHAUSTED`, a peer ruling states "nothing arms, PM.us daily-high rungs close as a programme" and names Kalshi (`wip/kalshi-s4-registry`) as the successor lever — **this is a valid, evidence-producing, non-bare stop**, not a plan failure | RA-8/RA-10 negative outcome | S (ruling) | N/A — this is the honest alternative to RA-11 |
| **RA-14** | AUD-06b bounded allocation sizing | Explicitly OUT of critical path. Sizing above `order_quantity=1` is meaningless before a CONFIRMED unit-quantity edge exists (AUD-18 §12) | RA-11 (CONFIRMED + newly registered family) | L (own plan exists, `AUD-06b-bounded-allocation-sizing.md`) | No — but blocked structurally until RA-11 |

**Critical path:** RA-8 → RA-9 → RA-10 → RA-11 → RA-12 (or RA-8/RA-10 → RA-13 for the KILL branch).
Everything else (RA-1..RA-6) is parallel infrastructure that must be DONE before RA-11 can be *signed*,
but does not gate RA-8 from starting today.

---

## 1. Goal & acceptance criteria

**Goal state** (operator-set, non-negotiable, per task brief): a registered family that is (a)
live-armed, (b) hunts at all hours, (c) trades a demonstrated positive-EV edge, (d) learns from
settled outcomes.

Numbered, testable acceptance criteria for THIS roadmap (not for the eventual trading family itself):

1. **AC-1.** A0 evidence pack exists, dated, under `docs/evidence/venue/polymarket_us/`, meeting
   `POST_FORECAST_PHASE_2026-09-20.md`'s A0 row verbatim, with `DOCUMENTED_TAKER_FEE_COEFFICIENT`
   unchanged (RA-1).
2. **AC-2.** `scripts/analysis/hypothesis_triage.py`'s nightly run can, in principle, produce a
   non-trivial disposition (`CONFIRMED`/`PRIMARY_PASSED_PNL_VETO`/`REJECTED`) for SOME hypothesis —
   i.e. neither structural gate (`_has_registered_draw_binding` hardcoded `False`; `REPLAY_VALIDITY`
   hardcoded `MECHANISM_ONLY` for every scheduled run) blocks it unconditionally (RA-2, RA-3).
3. **AC-3.** `pm_us_crh_exit_v4`'s manifest is registration-ready: correct fee θ, correct
   `composition_kind`, a real `d0_climate_day`, and an `exit_rule` key (RA-4).
4. **AC-4.** A verified (not assumed) answer exists to "can a v5+ family's tally ever see a v3/v4
   residual fill" (RA-5a).
5. **AC-5.** A recurring, unattended, alerting cadence exists that will detect either HUNT-1 re-open
   trigger (≥15 clusters in an untested hour; a live sub-degree observation source) without a human
   re-running the study by hand (RA-8).
6. **AC-6.** IF a trigger fires: a two-peer, pre-registered ruling exists for the new hypothesis
   BEFORE any of its data is opened (RA-9), mirroring the discipline already proven on
   `H-ARCHIVE-RECAL-2026-09`/`H-NO-SIDE-2026-09`.
7. **AC-7.** IF that hypothesis reaches `CONFIRMED`: a new A1-class ruling package exists meeting
   every corrected condition in §6 below, and the fresh manifest satisfies `POST_FORECAST_PHASE
   §A-9` item 2 in full (RA-11).
8. **AC-8.** IF no trigger ever fires, or the hypothesis is `REJECTED`/exhausted: an evidenced-KILL
   ruling exists naming Kalshi as the next lever (RA-13) — the acceptance test's honest non-trading
   branch, per `AUD-18 §6.6` and `POST_FORECAST_PHASE` Amendment C §C-7.

---

## 2. Evidence / root cause, with file:line

**AUD-18 status (task item 1) — precisely which steps are done, which are blocked, and the claimed
circularity resolved:**

- §7 steps 1-7 (ledger, triage runner, scheduling, the forecast-taker zero-look registration): **DONE**
  (`4aa7894`, `8afa554`, `213ae2b`, `ae56ab8`). Nightly `breezy-hypothesis-triage.service` at 01:20Z is
  live and has passed its first observed tick (`813d7fb`, 09-26 01:20Z, AC5 all green).
- §7 step 8 (peer-ruling-before-registration for the two viable §6.3 classes at the time): **DONE**
  for `H-NO-SIDE-2026-09` (`RULING_H-NO-SIDE-2026-09_horizon_2026-09-25.md`, ENDORSED-WITH-NOTES,
  registered `UNDERPOWERED_NOT_REGISTERED` `04991ac`) and `H-ARCHIVE-RECAL-2026-09`
  (`RULING_H-ARCHIVE-RECAL-2026-09_horizon_2026-09-25.md`, CONFIRMED-WITH-NOTES, registered
  `UNDERPOWERED_NOT_REGISTERED` `12ea442`/`d4a5ecc`). **Both are dead ends as designed**: MDE at their
  pre-registered n exceeds their own plausibility bound. The archive-recalibration class specifically
  is "genuinely unknown" whether it can EVER clear `min_station_days` at this venue's tape growth
  rate (`AUD-18-...md:1504-1506`) — it is not merely slow, its own MDE (0.0629) may be structurally
  implausible for a mean-reversion-style recalibration on a corpus this size.
- §7 step 9 (first scheduled triage tick, observed by hand): **DONE** (`813d7fb`).
- **The item PROGRESS.md:53 calls "(b) schema-v2 stratum/draw binding BLOCKED":** verified directly at
  `scripts/analysis/hypothesis_triage.py:484-493` — `_has_registered_draw_binding` is a **hardcoded
  `return False`**, by design (`ae56ab8`'s own commit message: "fails CLOSED on a registered record
  with no stratum/draw binding... and alerts once"). It is consulted only for **look-taking, eligible**
  records (`run()` at `:642` filters `is_zero_look` records out before `_triage_record` ever runs), so
  today's 3 ledger rows (all zero-look) never touch it — **the gate is real but currently VACUOUS**,
  because nothing look-taking is registered yet.
- **Resolving the stated circularity.** PROGRESS's phrasing ("BLOCKED until a look-taking registration
  or REPLAY_VALIDITY flip") reads as circular — build needs a hypothesis, a hypothesis needs the
  build — but it is **not** circular on inspection:
  1. The **build** of `_has_registered_draw_binding` (a real predicate over a new schema field) does
     **not** require a live hypothesis to exist; it requires only a **concrete target stratum shape**,
     which the only remaining viable §6.3 class (hours 10-11 / all-hours) already supplies:
     `station × hour_lst × side × composition_kind` — exactly the axes `RULING_HUNT-1`'s own triggers
     name. RA-2 designs and unit-tests it against that shape now, using synthetic fixtures — no live
     registration needed for the BUILD, only for the eventual host EXERCISE (§5).
  2. **A second, independent gate exists that PROGRESS's line does not mention**, and it is the one
     that actually stops any hypothesis from ever being scored today even if RA-2 shipped tomorrow:
     `scripts/analysis/hypothesis_triage.py:352`, `_passes_c_validity` requires
     `row.validity != REPLAY_VALIDITY` — and `REPLAY_VALIDITY` is a **hardcoded module constant**
     (`src/breezy/analysis/replay_results.py:58`, `"MECHANISM_ONLY"`), written unconditionally by
     `scripts/analysis/replay_daily_runner.py:551,1119` on **every** scheduled row, because AUD-09's
     nightly runner invokes the paper-replay driver **without** `--family-manifest`
     (`current_rung_hold_paper_replay.py:1710-1712`, by AUD-09's own spec, `AUD-09-...md:899-915`,
     "not a failure — expected state"). So `params_match` COULD be `True` today (the driver DOES
     compute a real readback-vs-manifest comparison when a manifest is passed,
     `current_rung_hold_paper_replay.py:1723-1728`) but `validity` never leaves `MECHANISM_ONLY` on the
     scheduled path regardless. **This is RA-3, and it is the actual second half of "REPLAY_VALIDITY
     flip" — not something that resolves itself when a hypothesis is registered.**
  3. Net effect: the correct read of PROGRESS's line is **"nothing is lost by deferring RA-2 to when
     the first real target exists, AND nothing about that deferral is itself a hard blocker on
     building RA-2/RA-3 today"** — the plan amendment language ("BLOCKED until...") describes a
     *sequencing choice* (don't build a generic schema before you know what the first consumer needs),
     not a genuine circular dependency. This roadmap resolves it by building RA-2 and RA-3 NOW, scoped
     to the one concrete class that could still use them.

**A0 fee evidence (task item 2):** `AUD-02` completion plan §2/§5; PROGRESS.md:50 states "earliest
close 09-30." Depend on it as **EDGE-1** per the session brief's explicit instruction.

**Fresh manifest (task item 3):** `POST_FORECAST_PHASE_2026-09-20.md` §A-9 clauses 1-5.
`RULING_A1_pm_us_crh_v4_disposition_2026-09-21.md` §3.8 already flags clause 3 (residual sidecar
family-keying) **"NOT VERIFIED — did not locate and read the residual-sidecar code."** Verified
directly in this session: `src/breezy/persistence/residual_fills.py`'s `ExcludedFill` dataclass
carries **no `family_id` field at all** (grepped, absent); `scripts/analysis/family_tally_v2.py:1260`
resolves the sidecar path as `store_dir / _EXCLUDED_FILLS_FILENAME` — i.e. discrimination, if any,
happens only through **which directory** is passed in, not through any field on the record itself.
Whether that directory is already partitioned per family-lineage the way `assert_family_only`
(`family_barrier.py:75-96`) partitions admissible draws is **unverified in this session** — RA-5a
names the exact read needed to close this, and the exact fallback build if it is not already true.

**HUNT-1 (task item 4):** `RULING_HUNT-1_all_hours_hunting_2026-09-26.md` — BLOCKED-OPEN, CRIT/GATED,
"nothing built today," 4 falsifiable re-open triggers. `daf81a1`'s study covers 7/24 LST hours; the
other 17 are 1-6 clusters each against a 15-cluster power floor. Memory
`hunt-window-opens-after-repricing`: the concrete lever, if pursued actively rather than passively
waited on, is "hours 10-11 + a pre-window ask screen, never an earlier boot" — i.e. RA-8's cadence
should also watch for a build-side change to how early the pre-window ask screen opens, not only
passive cluster accrual.

**Ruling package and enablement (task item 5):** `RULING_A1_pm_us_crh_v4_disposition_2026-09-21.md`
§7 lists 6 conditions for overturning (ii). **Correction needed (found this session, not previously
flagged anywhere):** §7 item 4 says "fresh LD-OBF α," carried from the ORIGINAL `POST_FORECAST_PHASE`
A1 row and the session's own common brief. **`AUD-18`'s own peer-reviewed (100/100) design has since
WITHDRAWN `LD_OBF` entirely** (`AUD-18-...md` round 4: "`LD_OBF` is WITHDRAWN as a selectable look
policy... `SINGLE_LOOK` is the only admitted policy" — because `per_variant_alpha <= 0.0125` under any
multi-hypothesis budget can never reach the shipped boundary artefact's pinned `ALPHA_ONE_SIDED =
0.025`, `gs_boundary_artefact.py:78,82`). **A future A1-class ruling that asks for "a fresh LD-OBF α"
is asking for something AUD-18 cannot produce.** §6 below states the corrected condition.

**Learning loop (task item 6):** described in full in §4.

**AUD-07 / AUD-06b (task item 7):** `RULING_aud07_m1c_eps_k_decision_rule_2026-09-26.md` — the
segment running tonight (`breezy-aud07-m1c-seg-0927a`, 02:10-08:40Z) executes the pre-registered
decision rule (counterfactual → branch → 20k → `--final` → AC7 ruling), independent of the entry-edge
question. It matters to THIS roadmap because a re-armed family that can enter but cannot reliably exit
a loser is not a safe re-arm — the exit seam (`pm_us_crh_exit_v4`) is a **separate registered family**
gated on its own manifest hygiene (§3, `A. current behaviour`). AUD-06b (bounded allocation) is
explicitly `BLOCKED` on "an AUD-18 CONFIRMED edge + newly registered family" (PROGRESS.md:63) —
correctly so; it is placed at RA-14, off the critical path, and cannot be pulled forward without
violating AUD-18 §12's own `order_quantity=1` registration constraint.

---

## 3. Options & trade-offs

**O1 — Build RA-2/RA-3 now vs. defer until RA-9 registers something.**
Adopted: build now. Trade-off: some risk the eventual RA-9 hypothesis needs a stratum axis this
design didn't anticipate (e.g. a composite station-cluster key). Mitigated by scoping the DSL to
exactly the axes named in `RULING_HUNT-1`'s own triggers (§5) and keeping it a closed, validated enum
rather than a free-form string — a wrong or missing axis is a REFUSAL at registration, never a
silent gap, matching the repo's existing fail-closed convention (`register_hypothesis`).
Rejected alternative: wait for RA-9. Cost: RA-10's accrual clock would not start until RA-2/RA-3 AND
RA-9 both land serially, adding weeks for no benefit — capture keeps running either way.

**O2 — Pursue HUNT-1 passively (wait for clusters) vs. actively (pre-window ask screen change).**
Adopted: both, in parallel (RA-8 monitors; a build-side change to the pre-window screen is named as
an escalation path if RA-8 shows near-misses, e.g. an hour sitting at 10-14 clusters for months).
Not designing the active change here: it would touch the live decision funnel's pricing gates, which
is out of scope for a re-arm ROADMAP and belongs to its own AUD-01-lineage item if RA-8's data
justifies it — naming it now avoids a future "why wasn't this considered" gap, without building it
speculatively (YAGNI).

**O3 — Treat AUD-07's exit-seam completion as gating RA-11 vs. as parallel, non-gating work.**
Adopted: gating for the ENABLEMENT act (RA-12), not for the ruling package (RA-11) itself — a ruling
can state the entry edge is CONFIRMED while noting the exit seam is a separate registration the
operator should not enable ahead of. This avoids blocking RA-11's paperwork on RA-4's own (already
scheduled) completion while still protecting against "entry armed, no working exit."

**O4 — Fold RA-5a into RA-2 vs. keep separate.**
Adopted: separate. RA-2 is pure/unit-testable schema work; RA-5a is a settlement-boundary
verification that may turn out to be "already fine" (a documentation-only close) or may need an
`assert_family_only`-style filter — genuinely different shapes of work, and bundling them risks
scope creep in either ticket.

---

## 4. Architecture & data flow — the learning loop (task item 6)

```
capture (recorder, runs under A1 halt)
   -> offer tape / order_book_depths / quote_tick  (raw, forward-only, archived)
   -> shadow valuation (runs under A1 halt; no orders)
   -> nightly replay: replay_daily_runner.py + replay_sufficiency_census.py
        -> replay_results.jsonl   (validity=REPLAY_VALIDITY, today always MECHANISM_ONLY -- RA-3)
   -> promotion_proposal.py reads replay_results.jsonl + replay_sufficiency.jsonl (H4, read-only)
   -> hypothesis_triage.py (01:20Z, breezy-hypothesis-triage.service)
        -> filters is_zero_look records out (today: ALL 3 records are zero-look -> CLEAN no
           look-taking, honestly, every night)
        -> for a look-taking record: _has_registered_draw_binding (today: hardcoded False -- RA-2)
             then _passes_c_validity (today: always False, MECHANISM_ONLY -- RA-3)
             then draw-set construction (zero-take filter, §6.1) -> combine_station_day/score_combined
             then pooled-P&L veto + leg-share cap -> CONFIRMED / PRIMARY_PASSED_PNL_VETO / REJECTED
        -> hypothesis_ledger.jsonl (append-only) + hypothesis_evaluations.jsonl (H5 evidence)
   -> ALSO, independently: family_tally_v2.py (17:20Z, live fills only, current champion) ->
        decision_funnel digest (FU-12, 09:20Z) -> capital-flow reconciliation (FU-13b, 17:30Z) ->
        ROI report (17:40Z)
   -> a CONFIRMED hypothesis (H5) is an INPUT to a NEW A1-class ruling (RA-11) -- never a
      self-executing re-arm (RULING_A1 §12, restated)
   -> a new A1-class ruling + a fresh manifest (RA-5a/§A-9) + operator enablement (RA-12) closes the
      loop back to "capture" with a live, order-submitting family
   -> settled outcomes from THAT family feed family_tally_v2 and (if it is itself a NEW hypothesis
      class relative to what AUD-18 already evaluated) a NEW hypothesis_ledger entry for its own
      continued monitoring -- the loop is the same pipe, run again, per H6 (AUD-18 -> AUD-10b for a
      non-champion candidate family)
```

**Recalibration cadence:** there is deliberately **no separate "recalibration" job** distinct from the
above — `AUD-18`'s own design (§6.1 SINGLE_LOOK, no re-look) means a CONFIRMED/REJECTED hypothesis is
terminal; "recalibrating on the gate-pass subsample" is independently ruled INVALID
(`DECISION_FUNNEL_2026-09-20.md`, cited in `RULING_A1` §3.3). The only two knobs that legitimately
change the ESTIMATE going forward are (a) a genuinely new hypothesis id with its own ruling (never an
in-place edit) and (b) AUD-12's measured-slippage input, which — if it materially changes `BE_i` —
triggers a stated re-issue obligation for any AFFECTED ruling (AUD-18 §7 step 8, "re-issued if AUD-12
later publishes a measured slippage that changes BE").

---

## 5. File-by-file plan — RA-2 (schema-v2 stratum/draw binding)

**Files:**
- `src/breezy/analysis/hypothesis_ledger.py`
  - Bump nothing yet at the top-level constant blindly. Add `HYPOTHESIS_LEDGER_SCHEMA_VERSION_V2:
    Final[int] = 2` alongside the existing `HYPOTHESIS_LEDGER_SCHEMA_VERSION: Final[int] = 1` (kept,
    named `_V1` in comments) — **`read_hypothesis_ledger` must accept `schema_version in {1, 2}` and
    refuse anything else**, naming the unrecognised version exactly as today. This is a real
    backward-compatibility hazard found in this session: the CURRENT reader hard-refuses on ANY
    version mismatch (`hypothesis_ledger.py:838-843`), and the 3 existing ledger lines are written at
    version 1 — a naive "bump the constant to 2" would make every existing row unreadable and break
    the live 01:20Z timer outright. The fix reads the payload's own `schema_version` first and
    dispatches to a v1-shaped or v2-shaped field set before validating the rest.
  - Add `variant_stratum_filters: tuple[str, ...]` to `HypothesisRecord` (v2 only), length
    `k_variants`, each entry a canonical pipe-joined string over exactly four axes:
    `station=<ALL|comma-set>|hour_lst=<ALL|N|N-M>|side=<YES|NO|ALL>|composition_kind=<name>` — a
    closed, validated vocabulary (mirrors `ShadowRestSummary`'s pipe-joined `key` convention already
    in this codebase), never a free-form DSL.
  - Add `parse_stratum_filter(spec: str) -> StratumFilter` (pure), a frozen dataclass with validated
    fields; refuses an unknown axis name, a malformed range, or a duplicate axis.
  - `to_dict`/`from_dict`: v2 records serialise `schema_version: 2` and the new field; v1 records
    (read back) synthesize `variant_stratum_filters = ()` internally for API uniformity but this
    NEVER round-trips back to disk as a v2 row — an existing v1 line is read, used, and if ever
    re-appended (it is not, ledger is append-only) would stay v1.
- `scripts/analysis/hypothesis_triage.py`
  - Replace `_has_registered_draw_binding` (`:484-493`) with a real predicate: parse
    `record.variant_stratum_filters[index_for(variant_id)]`, refuse if empty/absent (still fails
    closed, now for a DIFFERENT reason — "no filter registered for this variant" — named distinctly
    from today's blanket message), else confirm the parsed filter matches the shape the reused
    `ReplayResult`/`replay_sufficiency` rows actually carry (station, an hour dimension IF the replay
    schema carries one — **flagged as an open question in §9**, since `ReplayResult` as read in this
    session carries `station`/`climate_day`/`strategy`/`lag_minutes`, not an explicit `hour_lst` — RA-2
    may need a companion field on `ReplayResult` or must derive `hour_lst` from the offer-tape join
    already used elsewhere; scoped as a RED in step 3 below, not assumed solved here).

## File-by-file plan — RA-3 (`REPLAY_VALIDITY` tier flip)

**Files:**
- `src/breezy/analysis/replay_results.py` — add a second named constant,
  `REPLAY_VALIDITY_PARAMS_VERIFIED: Final[str] = "PARAMS_VERIFIED"`, alongside the existing
  `REPLAY_VALIDITY = "MECHANISM_ONLY"` (kept as the default for any run without a manifest). Per B7's
  own discipline ("the literal appears in exactly one source file"), this is now TWO literals in one
  file, both asserted by a widened test.
- `scripts/analysis/replay_daily_runner.py` (`:551`, `:1119`) — accept an optional
  `--family-manifest` passthrough (already supported by the underlying paper-replay driver,
  `current_rung_hold_paper_replay.py:1710-1728`) scoped to a NAMED hypothesis's target family only
  (never the live champion's own scheduled run, which stays `MECHANISM_ONLY` by design until a
  ruling says otherwise for THAT family) — write `validity=REPLAY_VALIDITY_PARAMS_VERIFIED` **only
  when** `params_match is True`, else keep `MECHANISM_ONLY` (never write a verified tier off an
  unverified readback).
- A companion **ruling artefact**, not a silent constant edit (mirrors A0/A1's own governance): what
  conditions license moving a row out of `MECHANISM_ONLY` — proposed: `params_match is True` (readback
  proves the engine ran the manifest's own fee coefficient) AND the row's `(station, climate_day)` is
  independently confirmed `SUFFICIENT` by AUD-09's own census (already required by `_passes_c_validity`
  today) AND AUD-12's slippage figure used in the same run is the currently-evidenced one (`0.01`
  placeholder, `AUD-12a`). This governance step, not the code, is why RA-3 is scoped M not S.

## Tests (RED list, both items)

- `test_read_hypothesis_ledger_accepts_v1_and_v2_and_refuses_v3` — the 3 existing byte-identical v1
  lines still parse; an unknown version 3 still refuses naming it.
- `test_v1_record_round_trip_is_byte_unchanged` — preservation guard for the existing ledger file.
- `test_variant_stratum_filter_rejects_unknown_axis` / `..._malformed_range` / `..._duplicate_axis`.
- `test_has_registered_draw_binding_true_for_a_matching_filter` /
  `test_has_registered_draw_binding_false_and_names_the_missing_variant`.
- `test_replay_daily_runner_with_family_manifest_reports_params_match_true_on_matching_theta`.
- `test_replay_row_stays_mechanism_only_when_params_match_is_false`.
- `test_scheduled_champion_run_is_never_upgraded_off_mechanism_only_without_the_manifest_flag` — a
  non-regression RED protecting the LIVE champion's own nightly replay from an accidental upgrade.
- `test_c_validity_passes_on_a_params_verified_row_and_refuses_a_mechanism_only_row` (extends the
  existing `_passes_c_validity` coverage).

---

## 6. Correction to RULING_A1 §7 item 4 — "fresh LD-OBF α" is unreachable; the actual condition

`RULING_A1_pm_us_crh_v4_disposition_2026-09-21.md` §7 item 4 (echoing `POST_FORECAST_PHASE
§A-9` item 2 and this session's own common brief) requires "a fresh manifest... with n reset to 0 and
a fresh LD-OBF α." **`AUD-18`'s own, later, peer-scored-100/100 statistical design supersedes this**:
`LD_OBF` is withdrawn programme-wide because `per_variant_alpha` can never reach the shipped boundary
artefact's pinned `0.025` under any multi-hypothesis allocation (`gs_boundary_artefact.py:78,82`).
**Any future A1-class ruling (RA-11) must therefore require instead:** a fresh `hypothesis_id`, a
fresh `per_variant_alpha` freshly ASSIGNED by `register_hypothesis`'s fixed Bonferroni split (never
hand-picked), `look_policy = SINGLE_LOOK`, and the §7 step-8 peer ruling recording the MDE/power
check BEFORE any data is opened — this is what RA-9 already produces. RA-11 should cite RA-9's own
artefact as satisfying this condition, not ask for an LD-OBF boundary that cannot exist. This
correction should also be propagated to `POST_FORECAST_PHASE_2026-09-20.md`'s own A-9 item 2 text
when RA-11 is drafted (a documentation fix, not a re-ruling of A1 itself).

---

## 7. Execution order & parallelism

```
Day 0 (today, 2026-09-27):
  start RA-2 build || RA-3 build || RA-5a verification-read || RA-8 cadence setup
  RA-1 (A0) already running (WP-D1 landed); clock continues
  RA-4 (AUD-07) segment already scheduled tonight 02:10-08:40Z

Day ~3-5:
  RA-2, RA-3, RA-5a converge; full gate green; merged
  RA-4's AC7 ruling issues; base §7 steps 7/7b/8 proceed

Day ~3 (2026-09-30):
  RA-1 (A0) closes -- 5 consecutive days from WP-D1's confirmed day-list

By ~2026-10-04:
  ALL of RA-1..RA-6 done. Infrastructure is ready for a re-arm ruling THE MOMENT an edge exists.
  This is the "earliest possible" date the task asks for, and it is a floor on readiness, not on
  re-arm.

Ongoing, indefinite, from Day 0:
  RA-8 cadence runs bi-weekly. Each run either:
    (a) reports "no trigger" -> next evidence-producing action is simply "the next scheduled run,"
        which is not a bare stop because the cadence itself, its dashboard/alert, and the dated
        negative result are all artefacts (mirrors AUD-18's own §6.4 "measured, not assumed" nightly
        re-triage discipline); or
    (b) a trigger fires -> RA-9 starts within days.

If/when RA-8 fires:
  RA-9 (peer ruling, days) -> RA-10 (registration + accrual + first look; accrual duration UNKNOWN,
  bound below by whatever min_station_days RA-9's ruling sets)
    -> IF CONFIRMED: RA-11 (ruling package, days, requires RA-1/RA-4/RA-5a already done) -> RA-12
       (operator act)
    -> IF NOT: back to "no trigger" posture, OR (if AUD-18's own programme-level KILL condition is
       independently met, §6.6) RA-13 (evidenced-KILL ruling, names Kalshi)
```

No step in this roadmap requires touching Nautilus, weakening a safety/settlement/contract test, or
assigning an operator-reserved value. RA-12 and RA-13's "operator" mentions are NAMES of the
reserved act, never a proposed value.

---

## 8. Deploy & verification — what proves each milestone is live

- **RA-1:** the extended pin test is green in `scripts/ci/run_tests_no_egress.sh`'s output, and the
  dated evidence doc exists under `docs/evidence/venue/polymarket_us/` with a 5-day table.
- **RA-2/RA-3:** full gate green (`run_tests_no_egress.sh`, `lint-imports`, `mypy src/breezy`); a
  scratch host run of `hypothesis_triage.py` against a FIXTURE ledger (not the live one) shows a
  synthetic look-taking record reaching a real disposition, not `MISSING_STRATUM_BINDING`.
- **RA-4:** `docs/evidence/AUD07_M1c_eps_k_counterfactual_<date>.md` exists; the AC7 ruling is signed;
  `deploy/families/pm_us_crh_exit_v4.json` no longer carries placeholder shas or the stale θ/
  composition_kind.
- **RA-5a:** either a dated evidence note stating the existing directory partition already satisfies
  A-9 clause 3 (with the exact code read cited), or a merged fix plus a RED→GREEN pair proving a v3
  residual cannot reach a v5+ tally.
- **RA-8:** the cadence's systemd timer exists (`systemd-run --user` pattern per L-26), and a run log
  shows at least one completed pass with the current cluster counts recorded per untested hour.
- **RA-9/RA-11:** the `RULING_*.md` artefact exists under `docs/evidence/`, dated and two-peer signed,
  exactly like `RULING_H-ARCHIVE-RECAL-2026-09` and `RULING_A1` themselves.
- **RA-12:** the operator's enablement act plus the node's next boot showing the new family's permit
  and an order actually reaching the exec client — the ONLY point in this entire roadmap where a real
  order is placed, and it is entirely downstream of RA-11 being signed.

---

## 9. Risk register

| # | Risk | Likelihood | Mitigation |
|---|---|---|---|
| R1 | RA-2's schema bump breaks the live 01:20Z timer if the v1/v2 dual-read is not implemented correctly | MEDIUM if rushed | The dual-version RED (`test_read_hypothesis_ledger_accepts_v1_and_v2...`) must be written and GREEN before merge; verify against the actual on-disk `hypothesis_ledger.jsonl`, not a fixture copy, before deploy |
| R2 | `ReplayResult` may not carry an `hour_lst`-equivalent field needed for RA-2's stratum filter to be checkable against real replay rows | MEDIUM | Named explicitly as an open question in §5; resolve by codegraph-exploring `ReplayResult`'s full field set before writing the RED, not assumed here |
| R3 | RA-3's manifest-bound replay accidentally upgrades the LIVE champion's OWN scheduled replay row out of `MECHANISM_ONLY` without a ruling backing it | LOW but HIGH severity if it happens (a promotion-criteria contract implication) | Named non-regression RED (`test_scheduled_champion_run_is_never_upgraded...`); the `--family-manifest` flag must be opt-in per invocation, never a default |
| R4 | RA-8 never fires; the whole critical path stalls indefinitely with no forcing function | HIGH (this is the honest expectation per AUD-18 §9/§11) | This is why RA-13 exists as a named, dated, ruled alternative — not a silent stall. Re-run the cadence; do not extend it into "widen the window anyway," which `RULING_HUNT-1` explicitly forbids |
| R5 | RA-5a's read concludes the residual sidecar is NOT family-keyed, requiring a build inside `family_tally_v2.py`/`residual_fills.py` that turns out to be larger than S–M (e.g. touching every caller of `read_excluded_fills`) | MEDIUM | Scope as its own plan with a fresh estimate if the read surfaces this; do not silently absorb into RA-11's critical path — it is a precondition, not negotiable |
| R6 | A future drafter of RA-11 copies `POST_FORECAST_PHASE §A-9`'s "fresh LD-OBF α" language verbatim, reproducing an unreachable requirement | MEDIUM (already happened once, in this session's own common brief) | §6 above is the correction; RA-11's brief must cite §6, not the original A-9 text, for that one clause |

---

## 10. LESSONS / invariant compliance

- Nautilus untouched: nothing in RA-1..RA-14 touches `Actor`/engine internals; RA-3's replay driver
  changes are script-level (`scripts/analysis/`), reusing existing native extension points already in
  place.
- `allow_short` untouched; no operator-reserved value proposed anywhere in this roadmap.
- No safety/settlement/contract test weakened: RA-2/RA-3 both WIDEN an allow-list (schema versions;
  validity tiers) by exactly one reviewed value each, per L-12's spirit, never relaxing an existing
  refusal.
- `AUD-01a`/`AUD-01b` (closed-by-default NO-side calibration gate, LAX/MDW stall diagnosis) are
  already merged (`0dc1cae`, `ea1873c`) and stay untouched — they are defense-in-depth for whatever
  family RA-12 eventually enables, not a substitute for RA-11's own edge evidence.
- Live-trading enablement stays operator-only (RA-12); the two budget-ceiling values are never named
  or valued anywhere in this document, matching `RULING_A1` §7's own statement that they are "already
  established."
- No bare stop: every terminal state in §7's execution order (including RA-13's KILL branch) names its
  own next evidence-producing action or successor artefact.

---

## 11. Dependencies on other EDGE items

- **EDGE-1** — A0 fee-drift evidence pack. RA-1 in this roadmap IS EDGE-1's deliverable; this plan
  depends on it by ID exactly as the task brief specifies, and does not re-plan it.
- **EDGE-2, EDGE-3, EDGE-4, EDGE-6** — sibling items in this same planning session, authored blind
  (per the common brief, no other agent's output is visible to this one). Their exact scope is
  unknown here. Where this roadmap's items plausibly overlap with likely sibling scope (fresh
  manifest mechanics, HUNT-1 build detail, the learning-loop description, AUD-07/AUD-06b fold-in —
  task items 3, 4, 6, 7 respectively all explicitly named in this item's own brief), this plan takes
  them as ITS OWN scope per the explicit instructions in the EDGE-5 brief, and the coordinator's merge
  step (per the operating contract's §2 merge contract) is where any duplication or contradiction with
  EDGE-2/3/4/6 must be reconciled — this agent cannot see or resolve that from here.

---

## 12. Confidence self-assessment, with unknowns

**Confidence: ~70%** on the roadmap's sequencing and the fast-track items (RA-1..RA-6); **~35%** on
any DATE for the critical path (RA-8 onward), which is deliberately reported as open-ended rather than
guessed, per the evidence in §2.

**Unknowns, named plainly:**
- Whether `ReplayResult` already carries enough fields to check an hour-scoped stratum filter, or
  whether RA-2 needs a companion field addition to `replay_results.py` — flagged in §5/R2, not
  resolved here; the next agent building RA-2 must codegraph-explore `ReplayResult`'s full schema
  first.
- Whether RA-5a's read concludes "already fine" or "needs a build" — genuinely unknown from this
  session; the read itself (comparing `family_tally_v2.py`'s `store_dir` resolution against
  `assert_family_only`) was not completed in this session, only the fact that `ExcludedFill` itself
  carries no `family_id` field.
- The true accrual rate for off-window hours once (if) RA-9 registers a hypothesis — genuinely
  unmeasurable without RA-8 first providing a trigger, since the trigger IS the first credible signal
  that an hour's take-rate is nonzero enough to project an accrual rate from.
- Whether AUD-12's `0.01` slippage placeholder will still be current by the time RA-11 drafts — AUD-12a
  measured `0.0000` from n=8 live fills but KEPT the conservative placeholder; a larger live sample (if
  RA-12 ever fires and generates new fills) could change this and would trigger the stated re-issue
  obligation on RA-9/RA-11's own MDE inputs.
- This plan does not verify EDGE-1/2/3/4/6's actual content; any ID collision or scope overlap is a
  known, named integration risk for the coordinator's merge (§11), not resolved here.
