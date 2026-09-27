# EDGE-5 — Dependency-ordered roadmap to a new A1-class re-arm ruling (plan r2, 2026-09-27)

**Author:** trading-bot-architect, revising r1 per coordinator round-1 ruling (architect/python/domain all
REQUEST_CHANGES). **Class:** CRIT programme plan, build-time only. Authorises no order, no operator
value, no live-trading enablement.

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

- **FAST TRACK (build/evidence hygiene, days, mostly non-calendar-gated):** RA-1..RA-6, RA-8b, RA-11a —
  closes A0, fixes the two structural gates that make AUD-18's nightly triage a no-op, finishes the exit
  seam, settles the α-budget question, and builds the all-hours enablement infrastructure. **Earliest
  completion: 2026-10-04** (bounded below by A0's own 5-consecutive-day clock, RA-1). This is a floor on
  READINESS, not on re-arm.
- **CRITICAL PATH (evidence accrual, calendar-gated):** RA-8b → RA-9 (trigger-4 direct registration, no
  longer waiting on RA-8's cluster count) → RA-9b (simulated-take engine) → RA-10 (accrual + first look)
  → RA-11 (ruling package) → RA-11a/EDGE-2C/EDGE-3 gate → RA-12 (operator enablement), OR → RA-13 (dated
  KILL, opens the Kalshi item) if RA-10 resolves negative or the dated no-trigger horizon (§7) elapses.
  RA-8 keeps running as a parallel, non-gating monitor for triggers 1/2 (a true forcing-function backstop
  if trigger-4's pooled off-window class itself resolves REJECTED).

**Learning-loop clarification (domain Q3, binding for this roadmap):** "learns from settled outcomes"
means the existing nightly `hypothesis_triage.py` (01:20Z) pipeline reaching real dispositions —
`CONFIRMED` / `PRIMARY_PASSED_PNL_VETO` / `REJECTED` / `PARKED` → `ABANDONED_CAP_EXHAUSTED` — and, at the
programme level, retiring or replacing hypotheses across generations (dead classes stay dead;
`H-ARCHIVE-RECAL-2026-09` and `H-NO-SIDE-2026-09` are the two already-retired examples). It is
**explicitly NOT** in-place recalibration of a live estimate on new data — that pattern is independently
ruled INVALID (`DECISION_FUNNEL_2026-09-20.md`, cited in `RULING_A1` §3.3) because it would silently
violate `SINGLE_LOOK`.

**Honest time-to-demonstrated-edge, recomputed:** RA-1 (A0) cannot close before **2026-09-30** (5
consecutive complete days from WP-D1's confirmed day-list). RA-2/RA-3 (rescoped, S/M) plausibly land by
**~2026-10-02**. RA-8b (a ruling, not a build) can close in parallel within days. RA-9's trigger-4
registration can then start **as soon as RA-2+RA-3+RA-8b all close (~2026-10-03..05)** rather than
waiting on RA-8's open-ended cluster trigger — this is the entire point of adopting trigger 4. From
there, RA-9b (engine build, priced with the `hour_lst` backward-compat hazard) and RA-10's accrual are
the dominant cost. Adopting the domain reviewer's evidenced estimate rather than re-deriving it bottom-up
here (this session did not independently model accrual rate): **~3-5 months to a demonstrated
CONFIRMED/REJECTED disposition on the trigger-4 fast path; open-ended on any other path.** Per the
domain reviewer's cluster-count evidence (item 7 below), an evidenced KILL (RA-13) is the **more likely**
outcome than a CONFIRMED re-arm. This roadmap reports that plainly rather than optimistically bounding it.

---

## 1. Goal & acceptance criteria

**Goal state** (operator-set, non-negotiable): a registered family that is (a) live-armed, (b) hunts at
all hours, (c) trades a demonstrated positive-EV edge, (d) learns from settled outcomes (§0 definition).

1. **AC-1.** A0 evidence pack exists, dated, under `docs/evidence/venue/polymarket_us/`, meeting
   `POST_FORECAST_PHASE_2026-09-20.md`'s A0 row verbatim, `DOCUMENTED_TAKER_FEE_COEFFICIENT` unchanged
   (RA-1). Blocked on EDGE-1's fee-probe fix landing first (item 10).
2. **AC-2.** Neither structural gate (`_has_registered_draw_binding` hardcoded `False`; `REPLAY_VALIDITY`
   hardcoded for scheduled runs) blocks a non-trivial triage disposition unconditionally (RA-2, RA-3).
3. **AC-3.** `pm_us_crh_exit_v4`'s manifest is registration-ready (RA-4).
4. **AC-4.** A verified answer exists to "can a v5+ family's tally ever see a v3/v4 residual fill,"
   correctly exempting `no_taken_latch` sentinel rows (RA-5a).
5. **AC-5.** A recurring, unattended, alerting cadence exists for HUNT-1 triggers 1/2 as a monitoring
   backstop (RA-8), independent of whether trigger 4 is separately exercised (RA-9).
6. **AC-6 (NEW).** A dated, evidenced ruling fixes the family-wise α budget (0.025, not 0.05) for any
   hypothesis gating a `pm_us_crh` re-arm, BEFORE RA-9 assigns `per_variant_alpha` to anything (RA-8b).
7. **AC-7.** A two-peer, pre-registered ruling exists for the pooled off-window hypothesis under trigger
   4, declaring its corpus under the EDGE-4 SEARCH/CONFIRM firewall, BEFORE any of its data is opened
   (RA-9).
8. **AC-8 (NEW).** A working, non-`P_HOLD`-gated composition/decision path exists that can produce
   simulated takes for that hypothesis under replay, inside AUD-09's closed script set (RA-9b).
9. **AC-9.** IF that hypothesis reaches `CONFIRMED`: a new A1-class ruling package exists meeting every
   condition in `RULING_A1` §7 AS WRITTEN for LD-OBF, plus the additional SINGLE_LOOK/Bonferroni
   condition (§6 below), plus the 0.025 budget (RA-8b), plus RA-1/RA-4/RA-5a/EDGE-2C/EDGE-3 all closed
   (RA-11).
10. **AC-10 (NEW).** All-hours enablement infrastructure (permit TTL, supervisor cycle, window widening)
    exists and is verified BEFORE RA-12's enablement act, or goal-state (b) is unreachable (RA-11a).
11. **AC-11.** IF no trigger ever fires, trigger 4 is `REJECTED`/exhausted, or the dated no-trigger
    horizon (§7) elapses: an evidenced-KILL ruling exists naming Kalshi (`wip/kalshi-s4-registry`) as the
    next lever (RA-13).

---

## 2. Evidence / root cause, with file:line

**AUD-18 status, structural-gate circularity:** unchanged from r1 — see r1 §2 for the full derivation
(`_has_registered_draw_binding` hardcoded `False` at `hypothesis_triage.py:484-493`, consulted only for
look-taking records, today's 3 rows all zero-look; `REPLAY_VALIDITY` hardcoded `MECHANISM_ONLY` at
`replay_results.py:58`, written unconditionally by the scheduled runner). RA-2/RA-3 close both gates now.

**LD-OBF — CORRECTED (reverses r1 §6; ruling item 1):** r1 claimed `AUD-18`'s withdrawal of `LD_OBF`
supersedes `RULING_A1` §7 item 4's "fresh LD-OBF α." **This was wrong.** AUD-18's withdrawal
(AUD-18…md:156-158, round-4 note at :807) applies to `LD_OBF` **as a hypothesis-ledger look policy** —
i.e. which look-spending rule governs `hypothesis_triage.py`'s own nightly evaluation of a REGISTERED
hypothesis. It says nothing about how a LIVE, order-submitting family monitors its own accruing edge
estimate in real time: that monitoring runs through the family's pinned group-sequential boundary
artefact (`deploy/families/pm_us_crh_v4.json:6` names `gs_boundary_pm_us_crh_v2.json`), which is exactly
the sequential (not single-look) machinery `RULING_A1` §7 item 4 is asking to be refreshed with a new α
for. These are two different consumers of "look policy": the ledger's registration-time hypothesis test,
and the live family's own boundary-crossing monitor. **RULING_A1 §7 item 4's "fresh LD-OBF α" is kept
exactly as written — a fresh manifest needs a fresh sequential-monitoring α, full stop.** What AUD-18
DOES add, correctly, is a second and separate requirement that r1 conflated with the first:
`SINGLE_LOOK` plus a Bonferroni-split `per_variant_alpha` for the LEDGER hypothesis test that produces
the CONFIRMED disposition feeding RA-11 in the first place. Both conditions are needed; neither
substitutes for the other. Per the coordinator's ruling, any actual wording change to `RULING_A1`'s own
text is out of scope for this roadmap document and must go through RA-11's two-peer ruling process.

**α budget (NEW, ruling item 2):** `hypothesis_ledger.py:95` sets `PROGRAMME_ALPHA: Final[float] = 0.05`,
sourced from `PREREG_WP7`. `PREREG v2` — the design actually governing the live boundary artefact — pins
a stricter value: confirmed via codegraph, `gs_boundary_artefact.py:82` reads
`ALPHA_ONE_SIDED: Final[float] = 0.025 # Two one-sided tests, each at this level (PREREG v2 rev b SS7).
An artefact declaring any other value is refused.` Using the ledger's looser `0.05` for a hypothesis
whose CONFIRMED status is what ultimately re-arms a family monitored at `0.025` is an internal budget
mismatch: it would let a hypothesis clear the LEDGER's bar at a false-positive rate the LIVE monitoring
artefact itself refuses to accept for its own boundary crossings. **RA-8b's ruling states: any hypothesis
whose CONFIRMED status gates a `pm_us_crh` re-arm is tested at the stricter, family-wise 0.025** — i.e.
the ledger borrows the boundary artefact's own pinned budget for THIS specific consumer, rather than
using the looser generic `PROGRAMME_ALPHA`. This is not a claim that `PROGRAMME_ALPHA=0.05` is wrong for
every ledger use (e.g. a hypothesis that never gates a re-arm, like the two already-retired classes, may
be a different case) — it is scoped narrowly to the re-arm-gating case per the coordinator's instruction.

**RA-3 — CORRECTED (ruling item 3):** r1 claimed the nightly runner "invokes the paper-replay driver
WITHOUT `--family-manifest`... by AUD-09's own spec... not a failure, expected state," making
`REPLAY_VALIDITY` unconditionally `MECHANISM_ONLY`. **This premise is false.** The nightly wrapper
`replay-daily-run.sh:164-169` already passes `--family-manifest`, and all 6 on-disk rows checked this
session have `params_match=True`. The actual remaining gap is narrower than r1 believed: `validity` is
still written as the bare string `MECHANISM_ONLY` regardless of `params_match`'s value
(`replay_results.py:55-58` defines only the one constant; nothing branches on `params_match` when
choosing which string to write). RA-3 is now: (a) flip `replay_results.py:55-58` to write
`PARAMS_VERIFIED` when `params_match is True` else keep `MECHANISM_ONLY`; (b) verify the consumer at
`promotion_criteria.py:427` (the champion-promotion path) reads `validity` correctly under both values and
does not itself need editing; (c) a short ruling stating the licensing condition (params_match plus AUD-09
census SUFFICIENT plus current AUD-12 slippage figure), same substance as r1's governance paragraph, kept.
Size **S**, not M. The "scheduled champion never upgraded without the flag" non-regression RED is
**dropped** — it protected against a hazard (accidentally invoking replay without the manifest flag) that
does not exist: the wrapper already always passes the flag.

**RA-9b — the missing engine (NEW, ruling item 4, merges architect RA-10 + domain Q1):** Even once RA-2
and RA-3 close the two structural gates, and even once RA-9's ruling registers the pooled off-window
hypothesis, there is nothing today that PRODUCES a simulated take for an off-window hour under replay —
the live decision funnel that actually emits takes is `P_HOLD`-gated end to end, and the pooled class
`{00-08, 16-23}` is precisely the set of hours that gate refuses live. Confirmed via codegraph this
session: `ReplayResult.to_dict` (`replay_results.py:121-155`) enumerates `schema_version, run_ts, station,
climate_day, strategy, lag_minutes, outcome, validity, blocked_reason, exception_type, family_id,
manifest_sha256, manifest_taker_fee_coefficient, engine_required_fee_coefficient, engine_params_source,
params_match, composition_kind, tape_instance_id, sufficiency_reason, trials, fills,
fill_price_vs_decision_ask, refusal_counts, wall_s, peak_rss_bytes, parquet_sha256, window_complete,
replayed_first_ns, replayed_last_ns, census_schema_version` — no hour-of-day field anywhere. RA-9's
stratum axes (`station × hour_lst × side × composition_kind`) cannot be checked against real replay rows
without either (a) an `hour_lst` field added to `ReplayResult`, hitting the identical strict
`from_dict`-refuses-unknown-version hazard RA-2 already has to solve for `HypothesisRecord`, or (b)
deriving `hour_lst` from the offer-tape join at read time without touching the schema. RA-9b prices
option (a) as the default (schema addition, versioned, same dual-read discipline as RA-2) since it also
serves as durable evidence, but names (b) as a fallback if the schema change proves too invasive under
AUD-09's frozen three-script contract (B18: replay_daily_runner.py, promotion_proposal.py,
hypothesis_triage.py — no fourth script). Effort raised to **M→L** to reflect this is a real build, not a
naming exercise as r1 implied by putting a paperwork-only RA-7 ahead of it.

**Faster sanctioned path (ruling item 5):** `RULING_HUNT-1_all_hours_hunting_2026-09-26.md` names 4
falsifiable re-open triggers. r1 treated only triggers 1/2 (cluster-count accrual) as live and left
trigger 4 (direct registration once the schema gates close) unexercised, making the whole critical path
hostage to an open-ended cluster count. The coordinator's ruling adopts trigger 4 explicitly: the pooled
off-window class registers through AUD-18 **as soon as RA-2+RA-3 land**, `k_variants=1` (AUD-18 §9's own
power lever for a single pre-registered class), independent of RA-8's cluster counts. RA-8 keeps running
as a parallel monitor (a genuine backstop if trigger 4's own hypothesis is REJECTED) but is no longer on
the gating path to RA-9. `daf81a1`'s own study **kills "hours 10-11" as a candidate class outright**:
hour 11 tested negative, hour 10 tested flat — struck everywhere in this roadmap (r1's O2 discussion of a
"pre-window ask screen at hours 10-11" is retired). Per `EDGE-4_DISPOSITION_2026-09-27.md`'s binding
firewall rule, the pooled-class hypothesis's own pre-registration ruling (RA-9) must explicitly declare
which corpus is SEARCH (already-inspected tape) versus post-freeze CONFIRM (new, un-inspected
station-days) — reusing `daf81a1`'s own inspected data as SEARCH evidence for hour selection, and dating
the CONFIRM corpus from RA-9's own ruling date forward, exactly as `H-ARCHIVE-RECAL-2026-09` already does.

**All-hours enablement gap (NEW, ruling item 6):** even a CONFIRMED, signed RA-11 ruling does not deliver
goal-state (b) — "hunts at all hours" — without three further infrastructure pieces, none built or
scheduled by r1: (1) the permit TTL is pinned to 10 hours
(`test_the_permit_ttl_is_pinned_to_ten_hours`) — a boot inside a 10h-hunting family's active window still
expires mid-session unless the pin itself is revisited or the supervisor re-permits before expiry; (2)
the supervisor's own 16:40Z stop / 16:50Z launch cycle (`CONTINUOUS_HUNTING_GAP_2026-09-20.md:84-93`)
creates a structural ~10-minute daily gap regardless of any family's own hour window; (3) `_WINDOW_*`
constants and the PREREG class-C amendment (`RULING_HUNT-1…md:24-26`) must be widened for the new
pooled-hours family specifically — none of this happens by virtue of RA-11 signing. RA-11a is a
standalone item for exactly this gap, sequenced before RA-12's enablement act.

**RA-13 KILL horizon dating (ruling item 7):** r1 left "RA-8 never fires" undated ("HIGH... this is why
RA-13 exists"). The coordinator's domain review supplies a measured basis: per-hour cluster accrual in
untested hours runs **~0.05-0.29 clusters/day**, versus **up to ~2/day** in already-populated (tested)
hours. At the low end of the untested range, clearing even a modest per-hour power floor (`daf81a1`'s own
15-cluster floor) takes on the order of a year per hour; at the high end, months. RA-13's ruling must
state this range explicitly rather than leaving the horizon unnamed, and must open a concrete Kalshi
roadmap item — Kalshi sits outside AUD-18's scope entirely (`AUD-18…md:194`) so "names Kalshi" without a
scoped next step is not itself an evidence-producing action. The successor work is parked on
`wip/kalshi-s4-registry` and RA-13 references it by branch name, not merely by product name.

**A0 fee evidence, fresh manifest, learning loop, AUD-07/AUD-06b:** unchanged from r1 §2 (see r1 for full
text) — carried forward without amendment.

---

## 3. Options & trade-offs

O1-O4 carried forward unchanged from r1 (build RA-2/RA-3 now; pursue HUNT-1 both passively and
(named-but-undesigned) actively; gate RA-12 not RA-11 on the exit seam; keep RA-5a separate from RA-2).

**O5 (NEW) — Trigger-4 direct registration vs. waiting on RA-8's cluster trigger.**
Adopted per coordinator ruling: trigger 4, once RA-2/RA-3/RA-8b close. Trade-off: registering a
pre-specified class before ANY of its own off-window cluster data has been inspected forgoes the
"observed near-miss" confidence a cluster count would have given, and commits the one remaining
`k_variants` slot to a class whose true effect size is completely unknown going in (unlike
`H-ARCHIVE-RECAL` or `H-NO-SIDE`, which at least had zero-look diagnostic passes before registration).
Accepted because the alternative (wait for RA-8) has no determinable date at all and the coordinator has
ruled it the faster sanctioned path; RA-9's own ruling must set a plausibility bound and MDE check before
data opens, exactly as `AUD-18` §7 step 8 requires for any hypothesis, pre-inspected or not.

**O6 (NEW) — Add `hour_lst` to `ReplayResult`'s schema vs. derive it from the offer-tape join at read
time.**
Adopted: schema addition as the default (RA-9b), matching RA-2's own versioned dual-read pattern and
producing a durable, queryable field rather than a recomputed one. Rejected-but-named fallback: derive at
read time from the existing offer-tape join if the schema change proves too invasive under AUD-09's
frozen three-script contract — avoids a schema migration but reintroduces a join dependency at every
consumer (`hypothesis_triage.py`, any future analysis script), trading a one-time migration cost for a
recurring coupling cost. RA-9b's own build should attempt the schema path first and fall back only with a
documented reason if it fails the B18 constraint.

---

## 4. Architecture & data flow — the learning loop

Diagram and recalibration-cadence discussion carried forward from r1 §4 unchanged, with one addition: the
`hypothesis_triage.py` box's per-hypothesis `α` input now explicitly reads from RA-8b's ruling (0.025 for
any re-arm-gating hypothesis) rather than the bare `PROGRAMME_ALPHA` module constant, and the pooled
off-window hypothesis's own draw-set construction step is fed by RA-9b's simulated-take engine rather
than by live decision-funnel takes (which the class structurally cannot produce, being off-window). The
§0 learning-loop clarification (nightly triage + generational retirement, never in-place recalibration)
governs this entire diagram; it is restated here as binding, not merely descriptive.

---

## 5. File-by-file plan

### RA-2 (schema-v2 stratum/draw binding) — amended

All of r1 §5's RA-2 content is carried forward, with these additions (ruling item 9a):

- `to_dict` preserves **each record's own `schema_version`** — a v1 record's `to_dict()` output still
  reads `schema_version: 1`; there is no global constant bump that would make every record claim v2.
  New RED: `test_v1_record_to_dict_never_emits_variant_stratum_filters` — a v1 record's serialised dict
  must not carry the key at all (not even as an empty tuple), distinguishing "this record predates the
  field" from "this record has zero filters," which are different facts.
- New RED: a mixed v1/v2 whole-file rewrite test. **The ledger is NOT append-only** —
  `write_hypothesis_ledger` rewrites the entire file (`hypothesis_ledger.py:808-820`), so any write that
  touches the file at all (even appending one new v2 record) re-serialises every existing v1 line too.
  The RED must assert that a rewrite triggered by adding one new v2 record leaves the pre-existing v1
  lines byte-identical (extends r1's `test_v1_record_round_trip_is_byte_unchanged` to the actual
  multi-record rewrite path, not just a single-record round trip).
- `hypothesis_register.py` (the registration entry point RA-9 will call) is added to the file plan — r1
  omitted it, describing only the ledger/triage read side.
- Existing tests that pass trivially against today's all-zero-look ledger (e.g. anything currently
  exercising `_has_registered_draw_binding`'s hardcoded `False` path) are labelled **regression**
  guards in the test plan, not **RED** — they are not new failing tests this change must turn green, they
  are protections against this change silently reintroducing the old hardcoded behaviour.

### RA-3 (`REPLAY_VALIDITY` tier flip) — rescoped, ruling item 3

Replaces r1's RA-3 file-by-file section entirely:

- `src/breezy/analysis/replay_results.py:55-58` — branch on `params_match`: write
  `REPLAY_VALIDITY_PARAMS_VERIFIED` when `params_match is True`, else keep the existing
  `REPLAY_VALIDITY = "MECHANISM_ONLY"` default. No change needed to `replay_daily_runner.py`'s
  `--family-manifest` wiring — it already exists and is already invoked nightly.
- `scripts/analysis/promotion_criteria.py:427` — read as the consumer of `validity`; verify (not
  assumed) that it already branches correctly on the new value; add a covering test if it does not.
- Ruling artefact: same licensing conditions as r1 (params_match True AND AUD-09 census SUFFICIENT AND
  current AUD-12 slippage figure), now scoped as a short ruling rather than new engineering, since the
  manifest-passing mechanism itself needed no build.

Size: **S** (was M).

### RA-5a (residual-sidecar family-keying) — amended, ruling item 9b

r1's file-by-file plan carried forward, with one addition: the family-keying check (whether verified
"already fine" or built as an `assert_family_only`-shaped filter) must **exempt `no_taken_latch`
`ExcludedFill` rows** — these carry blank `trial_id`/`station`/`climate_day`
(`residual_fills.py:205-216`) by design, mirroring the existing exemption pattern already in the codebase
at `residual_fills.py:242-246`. A family-keying filter that naively requires a non-blank `station`/
`climate_day` on every `ExcludedFill` row would incorrectly refuse or drop these sentinel rows instead of
passing them through unfiltered. New RED: a `no_taken_latch` fixture row must survive the family filter
unchanged regardless of which family's tally reads it.

### RA-9b (NEW — candidate-family manifest + simulated-take composition engine)

**Files:**
- `deploy/families/<pooled-off-window-hypothesis>.json` (NEW) — a candidate-family manifest scoped to
  the pooled `{00-08, 16-23}` hour set, `composition_kind` matching RA-9's ruling, fee θ from the (by
  then closed) A0 pack.
- `src/breezy/analysis/replay_results.py` — add `hour_lst: int | None` (v2-schema-shaped, same
  dual-version discipline as RA-2's `HypothesisRecord`; a v1-shaped `ReplayResult` on disk synthesizes
  `hour_lst=None` on read, never round-trips a v1 row forward as if it had one).
- A composition/decision path (exact module TBD by RA-9's ruling; likely a variant of the existing
  `current_rung_hold_paper_replay.py` composition step) that runs WITHOUT the live `P_HOLD` gate for this
  one candidate family only, inside AUD-09's frozen three-script invocation set — no fourth script is
  introduced; the existing `replay_daily_runner.py` invocation gains a family-scoped flag analogous to
  `--family-manifest`, reusing the mechanism RA-3 already confirmed works.
- Tests (RED): `test_hour_lst_field_v1_rows_read_as_none_never_written_back_with_a_value`,
  `test_pooled_off_window_composition_path_produces_a_take_without_p_hold_gating`,
  `test_composition_path_refuses_a_family_manifest_outside_the_pooled_hour_set`.

Effort: **M→L** (was folded invisibly into r1's RA-10; now explicit and priced with the schema hazard).

---

## 6. `RULING_A1` §7 item 4 — CORRECTED (reverses r1's incorrect "correction")

r1 claimed AUD-18's withdrawal of `LD_OBF` made `RULING_A1` §7 item 4's "fresh LD-OBF α" an unreachable
requirement, and proposed silently substituting a `SINGLE_LOOK`/Bonferroni condition in its place. **The
coordinator ruled this wrong** (§2 above has the full evidence). The corrected position:

- `RULING_A1` §7 item 4's "fresh LD-OBF α" is **kept exactly as written** — it governs the LIVE family's
  own sequential boundary-crossing monitor (the pinned `gs_boundary_pm_us_crh_v2.json` artefact), which
  is a different consumer from the ledger's hypothesis-registration look policy and was never withdrawn.
- **Additionally** (not instead), any ledger hypothesis whose CONFIRMED status is what RA-11 cites as
  satisfying item 4's edge-estimate clause must itself have been evaluated under `SINGLE_LOOK` with a
  Bonferroni-split `per_variant_alpha` — this is what RA-9's ruling produces, and RA-11 cites RA-9's own
  artefact for THIS clause, same as r1 proposed, but as an addition to item 4, not a replacement of it.
- **No wording change to `RULING_A1` or `POST_FORECAST_PHASE`'s own text is made by this roadmap
  document.** Any actual amendment to those artefacts' text must go through RA-11's own two-peer ruling
  process when RA-11 is drafted — this section states the correct reading, it does not itself constitute
  the amendment.

---

## 7. Execution order & parallelism

```
Day 0 (today, 2026-09-27):
  start RA-2 build || RA-3 build (now S, fast) || RA-5a verification-read || RA-6 observation
  || RA-8b ruling (alpha budget, no dependency) || RA-8 cadence setup (parallel monitor, non-gating)
  || RA-11a build start (permit TTL / supervisor cycle / window widening -- no dependency on evidence)
  RA-1 (A0) already running; blocked on EDGE-1's fee-probe fix landing (dependency item 10)
  RA-4 (AUD-07) segment already scheduled tonight 02:10-08:40Z

Day ~1-3:
  RA-3 closes (S, premise was already satisfied)
  RA-8b ruling closes (short, no build)

Day ~3-5:
  RA-2, RA-5a converge; full gate green; merged
  RA-4's AC7 ruling issues

Day ~3 (2026-09-30):
  RA-1 (A0) closes -- 5 consecutive days from WP-D1's confirmed day-list, contingent on EDGE-1

Day ~5-8 (once RA-2+RA-3+RA-8b all closed):
  RA-9 -- trigger-4 direct registration of the pooled off-window class, k_variants=1, corpus declared
  under the EDGE-4 SEARCH/CONFIRM firewall. Does NOT wait on RA-8's cluster count.

By ~2026-10-04:
  ALL of RA-1..RA-6, RA-8b, RA-11a done. Infrastructure + all-hours enablement both ready.

Day ~8 onward:
  RA-9b (engine build, M-L, includes the hour_lst schema hazard) -- dominant near-term cost
  RA-10 starts once RA-9b exists: registration + accrual via replay. Accrual duration is the dominant
    remaining cost, bound below by RA-9's own min_station_days.

Adopted estimate (domain, not independently re-derived here): ~3-5 months from today to a demonstrated
CONFIRMED/REJECTED disposition on this trigger-4 fast path; open-ended if RA-9b or RA-10 stalls.

  -> IF CONFIRMED: RA-11 (ruling package; requires RA-1, RA-4, RA-5a, EDGE-2C, EDGE-3 ALL closed)
       -> RA-11a already done (parallel-built) -> RA-12 (operator act)
  -> IF NOT, or if the dated no-trigger horizon (per-hour cluster rates, §2) elapses with no registration
       ever reaching CONFIRMED: RA-13 (evidenced-KILL ruling, opens the Kalshi item on
       wip/kalshi-s4-registry)

Ongoing, parallel, non-gating:
  RA-8's bi-weekly cadence keeps watching triggers 1/2 across all untested hours -- a genuine backstop if
  the pooled trigger-4 class is REJECTED but some OTHER hour cluster later crosses the power floor.
```

No step touches Nautilus, weakens a safety/settlement/contract test, or assigns an operator-reserved
value. RA-12/RA-13's "operator" mentions name the reserved act, never a proposed value.

---

## 8. Deploy & verification

r1 §8's RA-1/RA-2/RA-4 bullets carried forward unchanged. Amended/added:

- **RA-3:** the flip in `replay_results.py:55-58` is green under `run_tests_no_egress.sh`; a scratch run
  against a fixture with `params_match=True` shows `validity=PARAMS_VERIFIED`; the promotion-criteria
  consumer at `:427` is exercised by an existing or new test, not merely read.
- **RA-5a:** as r1, plus the new `no_taken_latch` exemption RED is green.
- **RA-8b:** the ruling artefact exists under `docs/evidence/`, dated, stating the 0.025 family-wise
  budget and its scope (re-arm-gating hypotheses only).
- **RA-9:** the `RULING_<hypothesis_id>_horizon_<date>.md` artefact exists, two-peer signed, and
  explicitly names its SEARCH corpus (e.g. `daf81a1`'s inspected data) separately from its post-ruling
  CONFIRM corpus.
- **RA-9b:** a scratch replay run against the candidate-family manifest produces at least one simulated
  take reaching `hypothesis_triage.py` without a `P_HOLD` refusal, and the `hour_lst` dual-read tests are
  green.
- **RA-11a:** `test_the_permit_ttl_is_pinned_to_ten_hours` still passes (or is updated with a fresh
  ruling if the pin itself changes); the supervisor's stop/launch cycle change is visible in the deployed
  systemd timer definitions; the widened `_WINDOW_*` constants are covered by a new test.
- **RA-13:** the KILL ruling states the measured per-hour accrual rates it used to date the horizon, and
  names the Kalshi branch explicitly.

---

## 9. Risk register

r1's R1, R2, R4, R5, R6 carried forward unchanged (R2's "open question" is now resolved into RA-9b rather
than left open; R3 is superseded, see below).

| # | Risk | Likelihood | Mitigation |
|---|---|---|---|
| R3 (revised) | RA-3's manifest-scoped replay flip is applied to the LIVE champion's OWN scheduled run instead of only the candidate family under test, silently upgrading its validity tier without a ruling | LOW but HIGH severity | The flip is conditioned strictly on `params_match`, which is only `True` when a manifest was passed for a NAMED family; the champion's own scheduled invocation is unaffected unless a manifest is added for it, which no item in this roadmap does |
| R7 (NEW) | RA-9 is drafted before RA-8b's alpha ruling closes, and assigns `per_variant_alpha` from the looser `PROGRAMME_ALPHA=0.05` by habit/copy-paste from an existing ledger row | MEDIUM (already happened once with LD-OBF in r1) | RA-8b is sequenced as a hard predecessor to RA-9 in §7, not merely "recommended first" |
| R8 (NEW) | Adding `hour_lst` to `ReplayResult` proves incompatible with AUD-09's frozen three-script contract (B18), forcing the O6 fallback (derive at read time) mid-build, after schema work has already started | MEDIUM | O6 names the fallback explicitly; RA-9b's build order attempts the schema path first specifically so the fallback decision is made early, not after sunk cost |
| R9 (NEW) | RA-11a (all-hours enablement) is not finished by the time RA-11 signs, delaying RA-12 even though the edge evidence is ready | MEDIUM | RA-11a is scheduled to build in parallel with the FAST TRACK (Day 0), not after RA-11 — it has no evidence dependency and should finish well before RA-9b/RA-10's multi-month accrual clock does |
| R10 (NEW) | EDGE-2C (NO-side resolver crash) or EDGE-3 (per-family halt) do not land before RA-11 is drafted, silently blocking RA-12 even after a signed ruling | MEDIUM-HIGH (both are external EDGE items, not controlled by this roadmap) | Named as hard RA-11 preconditions in §11; the coordinator's merge step must confirm their landing dates against this roadmap's critical path before RA-11 is scheduled |

---

## 10. LESSONS / invariant compliance

r1's bullets carried forward unchanged (Nautilus untouched; `allow_short` untouched; no test weakened,
only widened by one reviewed value each; `AUD-01a`/`AUD-01b` untouched; live-trading enablement stays
operator-only; no bare stop). Added: the α-budget correction (item 2) and the EDGE-4 corpus-declaration
requirement (item 5) are both now explicit, binding conditions on RA-8b/RA-9 respectively, closing two
gaps r1 left implicit.

---

## 11. Dependencies on other EDGE items

- **EDGE-1** — A0 fee-drift evidence pack. RA-1 IS EDGE-1's deliverable. **New in r2:** the fee-drift
  probe is currently blind (`fee_drift_probe_unknown` CRITICAL every 2h since 09-26 16:50Z,
  `probe_once` never halts on UNKNOWN) — EDGE-1's fix to that probe is itself the precondition for RA-1's
  own evidence pack being trustworthy, not merely a parallel item.
- **EDGE-2C** — the NO-side resolver crash. **New in r2, hard precondition on RA-11/RA-12**: a re-arm
  ruling cannot respectably claim a safe re-enablement while the resolver crashes on NO-side settlement;
  RA-11 lists this as a closed precondition, not an assumption.
- **EDGE-3** — per-family halt. **New in r2, hard precondition on RA-12**: the halt key today is NOT
  per-family (§ audit facts, common brief) — a fresh family registered under RA-9/RA-11 would otherwise
  inherit `pm_us_crh_v4`'s existing halt state at boot, defeating the entire re-arm. RA-12 cannot proceed
  until EDGE-3 lands.
- **EDGE-6d** — recorder next-day capture lag. **New in r2**: speeds RA-8's trigger-1 cluster accrual
  (the parallel monitor) by closing the gap between a market's later-day listing and the recorder's fixed
  09:00Z boot instrument set; does not directly affect the RA-9 trigger-4 path's own accrual, which runs
  through replay against already-captured tape, but shortens the RA-8 backstop's own timeline.
- **EDGE-2, EDGE-4, EDGE-6 (general)** — sibling items, scope not independently re-verified here beyond
  what the coordinator's ruling text supplied. `EDGE-4`'s SEARCH/CONFIRM firewall rule is read directly
  (`EDGE-4_DISPOSITION_2026-09-27.md`) and applied to RA-9's corpus declaration (item 5) as binding.

---

## 12. Confidence self-assessment, with unknowns

**Confidence: ~75%** on sequencing and the fast-track items (RA-1..RA-6, RA-8b, RA-11a) — higher than
r1's 70% because RA-3's premise correction removed a speculative build that never needed to happen.
**~30%** on any date for the critical path (RA-9b onward) — slightly lower than r1's 35% because RA-9b is
now an explicit, priced M→L build this roadmap previously hid inside RA-10, and the domain-supplied
3-5-month estimate is adopted, not independently re-derived, in this session.

**Unknowns, named plainly:**
- Whether the `hour_lst` schema addition (O6's primary path) actually fits AUD-09's frozen three-script
  contract, or whether the read-time-derivation fallback is needed — genuinely unresolved until RA-9b's
  build starts (R8).
- The true accrual rate for the pooled off-window class specifically, as distinct from the general
  per-hour cluster rates the domain reviewer supplied — those rates describe LIVE decision-funnel
  clusters, not simulated-replay takes from RA-9b's engine, which may accrue faster or slower once it
  exists.
- Whether EDGE-2C and EDGE-3 land on a timeline compatible with RA-11/RA-12, or become the actual
  binding constraint on re-arm once the edge-evidence side is otherwise ready (R10) — not resolved here,
  named as the coordinator's merge-step responsibility.
- Whether AUD-12's slippage placeholder changes before RA-9/RA-11 draft, triggering the stated re-issue
  obligation — carried forward from r1, unresolved.
- This plan does not independently verify EDGE-1/2/2C/3/4/6's actual content or landing dates beyond what
  the coordinator's ruling text supplied; any discrepancy is a known, named integration risk for the
  coordinator's merge, not resolved here.
